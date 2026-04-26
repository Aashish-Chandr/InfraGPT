"""
InfraGPT AI Engine — Anomaly Predictor

Runs as a long-lived Kubernetes Deployment. Every 60 seconds:
1. Fetches latest 5 minutes of metrics from Prometheus
2. Runs them through trained Prophet + Isolation Forest models
3. Computes anomaly scores (0-1) per pod/service
4. Exposes scores as Prometheus metrics
5. Publishes anomaly events to Redis when score > threshold
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
import redis
from prometheus_api_client import PrometheusConnect
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pythonjsonlogger import jsonlogger
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.predict")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── Configuration ────────────────────────────────────────────────────────────

PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring:9090",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis.production:6379/1")
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/data/models"))
ANOMALY_THRESHOLD = float(os.getenv("ANOMALY_THRESHOLD", "0.75"))
PREDICTION_INTERVAL = int(os.getenv("PREDICTION_INTERVAL", "60"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8080"))
REDIS_CHANNEL = "infragpt:anomalies"

# ─── Prometheus Custom Metrics ────────────────────────────────────────────────

ANOMALY_SCORE = Gauge(
    "infragpt_anomaly_score",
    "Anomaly score for a service/metric combination (0=normal, 1=anomalous)",
    ["service", "metric", "namespace"],
)

ANOMALY_EVENTS_TOTAL = Counter(
    "infragpt_anomaly_events_total",
    "Total number of anomaly events detected",
    ["service", "metric", "severity"],
)

PREDICTION_DURATION = Histogram(
    "infragpt_prediction_duration_seconds",
    "Time taken to run one prediction cycle",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

MODELS_LOADED = Gauge(
    "infragpt_models_loaded_total",
    "Number of models currently loaded",
    ["model_type"],
)

# ─── Prometheus Queries ───────────────────────────────────────────────────────

_NS = 'namespace="production"'
REALTIME_QUERIES = {
    "cpu_usage": (
        f'sum by (pod, namespace) '
        f'(rate(container_cpu_usage_seconds_total{{{_NS}, container!=""}}[5m]))'
    ),
    "memory_usage": (
        f'sum by (pod, namespace) '
        f'(container_memory_working_set_bytes{{{_NS}, container!=""}})'
    ),
    "http_error_rate": (
        f'sum by (app, namespace) '
        f'(rate(backend_http_requests_total{{{_NS}, status_code=~"5.."}}[5m]))'
    ),
    "request_latency_p99": (
        'histogram_quantile(0.99, sum by (le, app) '
        f'(rate(backend_http_request_duration_seconds_bucket{{{_NS}}}[5m])))'
    ),
}


# ─── Model Registry ───────────────────────────────────────────────────────────

class ModelRegistry:
    """Loads and caches trained models from disk."""

    def __init__(self, model_dir: Path):
        self.model_dir = model_dir
        self.prophet_models: dict = {}
        self.isolation_forest_models: dict = {}
        self.scalers: dict = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all available models from disk."""
        prophet_dir = self.model_dir / "prophet"
        if prophet_dir.exists():
            for metric_dir in prophet_dir.iterdir():
                if metric_dir.is_dir():
                    for model_file in metric_dir.glob("*.pkl"):
                        key = f"{metric_dir.name}/{model_file.stem}"
                        try:
                            self.prophet_models[key] = joblib.load(model_file)
                        except Exception as exc:
                            logger.warning(
                                "Failed to load Prophet model",
                                extra={"key": key, "error": str(exc)},
                            )

        iso_dir = self.model_dir / "isolation_forest"
        if iso_dir.exists():
            for metric_dir in iso_dir.iterdir():
                if metric_dir.is_dir():
                    model_file = metric_dir / "model.pkl"
                    scaler_file = metric_dir / "scaler.pkl"
                    if model_file.exists():
                        try:
                            self.isolation_forest_models[metric_dir.name] = (
                                joblib.load(model_file)
                            )
                            if scaler_file.exists():
                                self.scalers[metric_dir.name] = (
                                    joblib.load(scaler_file)
                                )
                        except Exception as exc:
                            logger.warning(
                                "Failed to load IF model",
                                extra={
                                    "metric": metric_dir.name,
                                    "error": str(exc),
                                },
                            )

        MODELS_LOADED.labels(model_type="prophet").set(
            len(self.prophet_models)
        )
        MODELS_LOADED.labels(model_type="isolation_forest").set(
            len(self.isolation_forest_models)
        )
        logger.info(
            "Models loaded",
            extra={
                "prophet": len(self.prophet_models),
                "isolation_forest": len(self.isolation_forest_models),
            },
        )

    def reload(self) -> None:
        """Reload models from disk."""
        self.prophet_models.clear()
        self.isolation_forest_models.clear()
        self.scalers.clear()
        self._load_all()


# ─── Anomaly Scoring ──────────────────────────────────────────────────────────

def compute_prophet_score(
    model: object,
    current_value: float,
    timestamp: datetime,
) -> float:
    """Compute anomaly score using Prophet's confidence interval."""
    try:
        future = pd.DataFrame({"ds": [timestamp.replace(tzinfo=None)]})
        forecast = model.predict(future)
        yhat_lower = forecast["yhat_lower"].iloc[0]
        yhat_upper = forecast["yhat_upper"].iloc[0]

        interval_width = yhat_upper - yhat_lower
        if interval_width <= 0:
            return 0.0

        if current_value > yhat_upper:
            deviation = (current_value - yhat_upper) / interval_width
        elif current_value < yhat_lower:
            deviation = (yhat_lower - current_value) / interval_width
        else:
            return 0.0

        score = 1 / (1 + np.exp(-deviation + 1))
        return float(np.clip(score, 0.0, 1.0))
    except Exception as exc:
        logger.debug("Prophet scoring failed", extra={"error": str(exc)})
        return 0.0


def compute_isolation_forest_score(
    model: object,
    scaler: Optional[object],
    features: np.ndarray,
) -> float:
    """Compute anomaly score using Isolation Forest."""
    try:
        if scaler is not None:
            features = scaler.transform(features.reshape(1, -1))
        else:
            features = features.reshape(1, -1)

        raw_score = model.decision_function(features)[0]
        normalized = 1 / (1 + np.exp(raw_score * 2))
        return float(np.clip(normalized, 0.0, 1.0))
    except Exception as exc:
        logger.debug(
            "Isolation Forest scoring failed",
            extra={"error": str(exc)},
        )
        return 0.0


def combine_scores(prophet_score: float, iso_score: float) -> float:
    """Combine Prophet and Isolation Forest scores."""
    return 0.6 * prophet_score + 0.4 * iso_score


# ─── Fetch Metrics ────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_current_metrics(prom: PrometheusConnect) -> dict:
    """Fetch current metric values from Prometheus."""
    results = {}
    for metric_name, query in REALTIME_QUERIES.items():
        try:
            data = prom.get_current_metric_value(metric_name=query)
            results[metric_name] = data
        except Exception as exc:
            logger.warning(
                "Failed to fetch metric",
                extra={"metric": metric_name, "error": str(exc)},
            )
            results[metric_name] = []
    return results


# ─── Main Prediction Loop ─────────────────────────────────────────────────────

def run_prediction_cycle(
    prom: PrometheusConnect,
    registry: ModelRegistry,
    redis_client: Optional[redis.Redis],
) -> None:
    """Run one complete prediction cycle."""
    with PREDICTION_DURATION.time():
        now = datetime.utcnow()
        current_metrics = fetch_current_metrics(prom)
        anomaly_events = []

        for metric_name, metric_data in current_metrics.items():
            for data_point in metric_data:
                labels = data_point.get("metric", {})
                value_str = data_point.get("value", [None, None])[1]
                if value_str is None:
                    continue

                try:
                    current_value = float(value_str)
                except (ValueError, TypeError):
                    continue

                entity_id = (
                    labels.get("pod")
                    or labels.get("app")
                    or labels.get("namespace", "unknown")
                )
                namespace = labels.get("namespace", "production")
                service = labels.get("app") or labels.get("pod", "unknown")

                prophet_key = f"{metric_name}/{entity_id}"
                prophet_score = 0.0
                if prophet_key in registry.prophet_models:
                    prophet_score = compute_prophet_score(
                        registry.prophet_models[prophet_key],
                        current_value,
                        now,
                    )

                iso_score = 0.0
                if metric_name in registry.isolation_forest_models:
                    features = np.array([current_value])
                    iso_score = compute_isolation_forest_score(
                        registry.isolation_forest_models[metric_name],
                        registry.scalers.get(metric_name),
                        features,
                    )

                combined_score = combine_scores(prophet_score, iso_score)

                ANOMALY_SCORE.labels(
                    service=service,
                    metric=metric_name,
                    namespace=namespace,
                ).set(combined_score)

                if combined_score >= ANOMALY_THRESHOLD:
                    severity = (
                        "critical" if combined_score >= 0.9 else "warning"
                    )
                    ANOMALY_EVENTS_TOTAL.labels(
                        service=service,
                        metric=metric_name,
                        severity=severity,
                    ).inc()

                    event = {
                        "timestamp": now.isoformat(),
                        "service": service,
                        "namespace": namespace,
                        "metric": metric_name,
                        "current_value": current_value,
                        "anomaly_score": combined_score,
                        "prophet_score": prophet_score,
                        "isolation_forest_score": iso_score,
                        "severity": severity,
                        "labels": labels,
                    }
                    anomaly_events.append(event)

                    logger.warning(
                        "Anomaly detected",
                        extra={
                            "service": service,
                            "metric": metric_name,
                            "score": f"{combined_score:.3f}",
                            "value": current_value,
                            "severity": severity,
                        },
                    )

                    if redis_client:
                        try:
                            redis_client.publish(
                                REDIS_CHANNEL, json.dumps(event)
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to publish to Redis",
                                extra={"error": str(exc)},
                            )

        logger.info(
            "Prediction cycle complete",
            extra={
                "anomalies_detected": len(anomaly_events),
                "metrics_evaluated": sum(
                    len(v) for v in current_metrics.values()
                ),
            },
        )


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main() -> None:
    """Main entry point."""
    logger.info(
        "Starting InfraGPT anomaly predictor",
        extra={
            "prometheus_url": PROMETHEUS_URL,
            "threshold": ANOMALY_THRESHOLD,
            "interval": PREDICTION_INTERVAL,
        },
    )

    start_http_server(METRICS_PORT)
    logger.info("Metrics server started", extra={"port": METRICS_PORT})

    prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)

    redis_client = None
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as exc:
        logger.warning(
            "Redis unavailable, anomaly events will not be published",
            extra={"error": str(exc)},
        )

    registry = ModelRegistry(MODEL_DIR)
    model_reload_interval = 3600
    last_model_reload = time.time()

    while True:
        cycle_start = time.time()

        try:
            if time.time() - last_model_reload > model_reload_interval:
                logger.info("Reloading models from disk")
                registry.reload()
                last_model_reload = time.time()

            run_prediction_cycle(prom, registry, redis_client)
        except Exception as exc:
            logger.error(
                "Prediction cycle failed",
                extra={"error": str(exc)},
            )

        elapsed = time.time() - cycle_start
        sleep_time = max(0, PREDICTION_INTERVAL - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
