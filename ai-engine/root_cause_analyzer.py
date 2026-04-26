"""
InfraGPT AI Engine — Root Cause Analyzer

Subscribes to the Redis anomaly channel. When an anomaly event arrives:
1. Fetches recent metric history from Prometheus
2. Fetches recent deployment history from ArgoCD API
3. Calls Anthropic Claude with all context
4. Sends the plain-English explanation to Slack
5. Stores the incident in PostgreSQL
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import anthropic
import numpy as np
import redis
import requests
import sqlalchemy
from prometheus_api_client import PrometheusConnect
from pythonjsonlogger import jsonlogger
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.root_cause_analyzer")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── Configuration ────────────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://redis.production:6379/1")
REDIS_CHANNEL = "infragpt:anomalies"
PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring:9090",
)
ARGOCD_URL = os.getenv("ARGOCD_URL", "http://argocd-server.argocd:80")
ARGOCD_TOKEN = os.getenv("ARGOCD_TOKEN", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://infragpt_admin:password@localhost:5432/infragpt",
)

# ─── Database Setup ───────────────────────────────────────────────────────────

engine = sqlalchemy.create_engine(DATABASE_URL, pool_pre_ping=True)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service VARCHAR(255) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    metric VARCHAR(255) NOT NULL,
    anomaly_score FLOAT NOT NULL,
    severity VARCHAR(50) NOT NULL,
    current_value FLOAT,
    root_cause_analysis TEXT,
    healing_action VARCHAR(100),
    healing_success BOOLEAN,
    healing_duration_seconds FLOAT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents(service);
CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_severity ON incidents(severity);
"""


def init_database() -> None:
    """Initialize the incidents table."""
    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(CREATE_TABLE_SQL))
        conn.commit()
    logger.info("Database initialized")


def store_incident(event: dict, analysis: str) -> int:
    """Store an incident in PostgreSQL and return the incident ID."""
    sql = sqlalchemy.text(
        """
        INSERT INTO incidents
            (timestamp, service, namespace, metric,
             anomaly_score, severity, current_value, root_cause_analysis)
        VALUES
            (:timestamp, :service, :namespace, :metric,
             :anomaly_score, :severity, :current_value, :analysis)
        RETURNING id
        """
    )
    with engine.connect() as conn:
        result = conn.execute(
            sql,
            {
                "timestamp": event["timestamp"],
                "service": event["service"],
                "namespace": event["namespace"],
                "metric": event["metric"],
                "anomaly_score": event["anomaly_score"],
                "severity": event["severity"],
                "current_value": event.get("current_value"),
                "analysis": analysis,
            },
        )
        conn.commit()
        incident_id = result.fetchone()[0]
    logger.info(
        "Incident stored",
        extra={"incident_id": incident_id, "service": event["service"]},
    )
    return incident_id


# ─── Context Gathering ────────────────────────────────────────────────────────

def _build_query(service: str, metric: str) -> str:
    """Build a PromQL query for the given service and metric."""
    ns = "production"
    queries = {
        "cpu_usage": (
            f'sum(rate(container_cpu_usage_seconds_total'
            f'{{namespace="{ns}", pod=~"{service}-.*"}}[5m]))'
        ),
        "memory_usage": (
            f'sum(container_memory_working_set_bytes'
            f'{{namespace="{ns}", pod=~"{service}-.*"}})'
        ),
        "http_error_rate": (
            f'sum(rate(backend_http_requests_total'
            f'{{namespace="{ns}", app="{service}", status_code=~"5.."}}[5m]))'
        ),
        "request_latency_p99": (
            f'histogram_quantile(0.99, sum by (le) '
            f'(rate(backend_http_request_duration_seconds_bucket'
            f'{{namespace="{ns}", app="{service}"}}[5m])))'
        ),
    }
    return queries.get(
        metric,
        f'sum(rate(container_cpu_usage_seconds_total{{pod=~"{service}-.*"}}[5m]))',
    )


def fetch_metric_history(
    prom: PrometheusConnect,
    service: str,
    metric: str,
    hours: int = 3,
) -> str:
    """Fetch recent metric history and return a summary string."""
    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=hours)
        query = _build_query(service, metric)
        data = prom.get_metric_range_data(
            metric_name=query,
            start_time=start_time,
            end_time=end_time,
        )
        if not data:
            return f"No historical data available for {metric}"

        values = [
            float(v[1])
            for series in data
            for v in series.get("values", [])
        ]
        if not values:
            return "No values in historical data"

        half = len(values) // 2
        trend = "increasing" if values[-1] > np.mean(values[:half]) else "decreasing"
        return (
            f"Last {hours}h stats for {metric}: "
            f"min={np.min(values):.4f}, "
            f"max={np.max(values):.4f}, "
            f"mean={np.mean(values):.4f}, "
            f"current={values[-1]:.4f}, "
            f"trend={trend}"
        )
    except Exception as exc:
        return f"Failed to fetch metric history: {exc}"


def fetch_recent_deployments(service: str) -> str:
    """Fetch recent ArgoCD deployment history for the service."""
    if not ARGOCD_TOKEN:
        return "ArgoCD token not configured — deployment history unavailable"

    headers = {"Authorization": f"Bearer {ARGOCD_TOKEN}"}
    try:
        resp = requests.get(
            f"{ARGOCD_URL}/api/v1/applications",
            headers=headers,
            timeout=10,
            verify=False,
        )
        resp.raise_for_status()
        apps = resp.json().get("items", [])
        relevant = [
            a for a in apps
            if service in a.get("metadata", {}).get("name", "")
        ]
        if not relevant:
            return f"No ArgoCD application found for service '{service}'"

        app_name = relevant[0]["metadata"]["name"]
        sync_resp = requests.get(
            f"{ARGOCD_URL}/api/v1/applications/{app_name}",
            headers=headers,
            timeout=10,
            verify=False,
        )
        sync_resp.raise_for_status()
        history = sync_resp.json().get("status", {}).get("history", [])
        if not history:
            return "No deployment history available"

        lines = []
        for h in reversed(history[-3:]):
            deployed_at = h.get("deployedAt", "unknown")
            revision = h.get("revision", "unknown")[:8]
            lines.append(f"  - {deployed_at}: revision {revision}")
        return f"Recent deployments for {app_name}:\n" + "\n".join(lines)
    except Exception as exc:
        return f"Failed to fetch deployment history: {exc}"


# ─── LLM Analysis ─────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=30),
)
def analyze_with_llm(
    event: dict,
    metric_history: str,
    deployment_history: str,
) -> str:
    """Call Anthropic Claude to generate a root cause analysis."""
    if not ANTHROPIC_API_KEY:
        return generate_rule_based_analysis(event)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = (
        "You are an expert SRE analyzing a Kubernetes anomaly.\n\n"
        f"Service: {event['service']}\n"
        f"Metric: {event['metric']}\n"
        f"Anomaly Score: {event['anomaly_score']:.3f}\n"
        f"Severity: {event['severity']}\n\n"
        f"Metric History:\n{metric_history}\n\n"
        f"Deployment History:\n{deployment_history}\n\n"
        "Provide a 3-sentence root cause analysis with:\n"
        "**What's happening:** ...\n"
        "**Likely cause:** ...\n"
        "**Recommended action:** ..."
    )
    message = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def generate_rule_based_analysis(event: dict) -> str:
    """Fallback rule-based analysis when LLM is unavailable."""
    metric = event["metric"]
    service = event["service"]
    score = event["anomaly_score"]
    analyses = {
        "cpu_usage": (
            f"High CPU on {service} (score: {score:.2f}). "
            "Possible infinite loop or traffic spike. "
            "Recommended: check recent deployments and scale up."
        ),
        "memory_usage": (
            f"Memory anomaly on {service} (score: {score:.2f}). "
            "Possible memory leak. "
            "Recommended: restart pod and investigate recent changes."
        ),
        "http_error_rate": (
            f"High error rate on {service} (score: {score:.2f}). "
            "Possible deployment regression. "
            "Recommended: check logs and consider rollback."
        ),
        "request_latency_p99": (
            f"High p99 latency on {service} (score: {score:.2f}). "
            "Possible DB slowness or resource contention. "
            "Recommended: check slow query logs."
        ),
    }
    return analyses.get(
        metric,
        f"Anomaly on {service} for {metric} (score: {score:.2f}). "
        "Manual investigation recommended.",
    )


# ─── Slack Notification ───────────────────────────────────────────────────────

def send_slack_notification(
    event: dict, analysis: str, incident_id: int
) -> None:
    """Send a formatted Slack notification for the anomaly."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("Slack webhook not configured, skipping notification")
        return

    emoji_map = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}
    emoji = emoji_map.get(event["severity"], "⚠️")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} InfraGPT Anomaly — {event['service']}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{event['service']}"},
                    {"type": "mrkdwn", "text": f"*Severity:*\n{event['severity'].upper()}"},
                    {"type": "mrkdwn", "text": f"*Metric:*\n{event['metric']}"},
                    {"type": "mrkdwn", "text": f"*Score:*\n{event['anomaly_score']:.3f}"},
                    {"type": "mrkdwn", "text": f"*Namespace:*\n{event['namespace']}"},
                    {"type": "mrkdwn", "text": f"*Incident:*\n#{incident_id}"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Root Cause Analysis:*\n{analysis}",
                },
            },
        ]
    }
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info(
            "Slack notification sent",
            extra={"incident_id": incident_id},
        )
    except Exception as exc:
        logger.error(
            "Failed to send Slack notification",
            extra={"error": str(exc)},
        )


# ─── Main Loop ────────────────────────────────────────────────────────────────

def process_anomaly_event(event: dict, prom: PrometheusConnect) -> None:
    """Process a single anomaly event end-to-end."""
    service = event["service"]
    metric = event["metric"]
    logger.info(
        "Processing anomaly event",
        extra={
            "service": service,
            "metric": metric,
            "score": event["anomaly_score"],
        },
    )
    metric_history = fetch_metric_history(prom, service, metric)
    deployment_history = fetch_recent_deployments(service)
    analysis = analyze_with_llm(event, metric_history, deployment_history)
    incident_id = store_incident(event, analysis)
    send_slack_notification(event, analysis, incident_id)
    logger.info(
        "Anomaly event processed",
        extra={"incident_id": incident_id, "service": service},
    )


def main() -> None:
    """Main entry point — subscribe to Redis and process anomaly events."""
    logger.info("Starting root cause analyzer")
    init_database()
    prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)

    while True:
        try:
            r = redis.from_url(REDIS_URL, decode_responses=True)
            r.ping()
            logger.info("Connected to Redis")
            break
        except Exception as exc:
            logger.warning(
                "Redis not available, retrying in 5s",
                extra={"error": str(exc)},
            )
            time.sleep(5)

    pubsub = r.pubsub()
    pubsub.subscribe(REDIS_CHANNEL)
    logger.info(
        "Subscribed to Redis channel",
        extra={"channel": REDIS_CHANNEL},
    )

    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            event = json.loads(message["data"])
            process_anomaly_event(event, prom)
        except json.JSONDecodeError as exc:
            logger.error(
                "Invalid JSON in anomaly event",
                extra={"error": str(exc)},
            )
        except Exception as exc:
            logger.error(
                "Failed to process anomaly event",
                extra={"error": str(exc)},
            )


if __name__ == "__main__":
    main()
