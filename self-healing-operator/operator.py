"""
InfraGPT Self-Healing Kubernetes Operator

Uses kopf (Kubernetes Operator Pythonic Framework) to:
- Watch HealingPolicy CRDs and evaluate conditions every 30 seconds
- Automatically rollback, restart, or scale deployments when conditions are met
- Watch all Deployments for failed rollouts and auto-rollback
- Create Kubernetes Events for full audit trail
- Send Slack notifications for every healing action
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import kopf
import kubernetes
import requests
from prometheus_api_client import PrometheusConnect
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from pythonjsonlogger import jsonlogger
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.operator")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── Configuration ────────────────────────────────────────────────────────────

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.monitoring:9090")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
METRICS_PORT = int(os.getenv("METRICS_PORT", "8080"))

# ─── Prometheus Metrics ───────────────────────────────────────────────────────

HEALING_ACTIONS_TOTAL = Counter(
    "infragpt_healing_actions_total",
    "Total number of self-healing actions taken",
    ["action", "service", "namespace", "trigger"],
)

HEALING_DURATION = Histogram(
    "infragpt_healing_duration_seconds",
    "Time taken to complete a healing action",
    ["action", "service"],
    buckets=[1, 5, 10, 30, 60, 120, 300],
)

ACTIVE_POLICIES = Gauge(
    "infragpt_active_healing_policies",
    "Number of active HealingPolicy resources",
)

CONDITION_EVALUATIONS = Counter(
    "infragpt_condition_evaluations_total",
    "Total condition evaluations",
    ["metric", "result"],
)

# ─── Kubernetes Clients ───────────────────────────────────────────────────────

def get_k8s_clients():
    """Initialize Kubernetes API clients."""
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()

    return {
        "apps": kubernetes.client.AppsV1Api(),
        "core": kubernetes.client.CoreV1Api(),
        "autoscaling": kubernetes.client.AutoscalingV2Api(),
        "custom": kubernetes.client.CustomObjectsApi(),
    }


# ─── Prometheus Client ────────────────────────────────────────────────────────

def get_prometheus() -> PrometheusConnect:
    """Get Prometheus client."""
    return PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)


# ─── Condition Evaluation ─────────────────────────────────────────────────────

def evaluate_condition(
    prom: PrometheusConnect,
    condition: dict,
) -> tuple[bool, float]:
    """
    Evaluate a single condition against Prometheus.
    Returns (is_triggered, current_value).
    """
    metric_query = condition["metric"]
    threshold = float(condition["threshold"])
    operator = condition.get("operator", "gt")

    try:
        data = prom.get_current_metric_value(metric_name=metric_query)
        if not data:
            CONDITION_EVALUATIONS.labels(metric=metric_query[:50], result="no_data").inc()
            return False, 0.0

        # Use the first result's value
        value_str = data[0].get("value", [None, None])[1]
        if value_str is None:
            return False, 0.0

        current_value = float(value_str)

        triggered = {
            "gt": current_value > threshold,
            "gte": current_value >= threshold,
            "lt": current_value < threshold,
            "lte": current_value <= threshold,
        }.get(operator, current_value > threshold)

        result = "triggered" if triggered else "ok"
        CONDITION_EVALUATIONS.labels(metric=metric_query[:50], result=result).inc()
        return triggered, current_value
    except Exception as exc:
        logger.warning(
            "Condition evaluation failed",
            extra={"query": metric_query[:100], "error": str(exc)},
        )
        CONDITION_EVALUATIONS.labels(metric=metric_query[:50], result="error").inc()
        return False, 0.0


# ─── Healing Actions ──────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def action_rollback(
    clients: dict,
    deployment_name: str,
    namespace: str,
) -> str:
    """Roll back a deployment to its previous revision."""
    apps_api = clients["apps"]

    # Get current deployment
    deployment = apps_api.read_namespaced_deployment(deployment_name, namespace)
    current_revision = int(
        deployment.metadata.annotations.get("deployment.kubernetes.io/revision", "1")
    )

    if current_revision <= 1:
        return f"Cannot rollback {deployment_name} — already at revision 1"

    # Get the previous ReplicaSet
    label_selector = ",".join(
        f"{k}={v}" for k, v in deployment.spec.selector.match_labels.items()
    )
    replica_sets = apps_api.list_namespaced_replica_set(
        namespace, label_selector=label_selector
    )

    # Find the RS with revision = current - 1
    target_revision = str(current_revision - 1)
    previous_rs = None
    for rs in replica_sets.items:
        rs_revision = rs.metadata.annotations.get("deployment.kubernetes.io/revision", "0")
        if rs_revision == target_revision:
            previous_rs = rs
            break

    if not previous_rs:
        # Fallback: use kubectl rollout undo equivalent via patch
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }
        apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
        return f"Triggered restart for {deployment_name} (previous RS not found)"

    # Patch deployment with previous RS's pod template
    patch = {
        "spec": {
            "template": previous_rs.spec.template.to_dict()
        }
    }
    apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
    return f"Rolled back {deployment_name} from revision {current_revision} to {target_revision}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def action_restart(
    clients: dict,
    deployment_name: str,
    namespace: str,
) -> str:
    """Restart a deployment by deleting its pods (rolling restart)."""
    apps_api = clients["apps"]
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.utcnow().isoformat()
                    }
                }
            }
        }
    }
    apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
    return f"Triggered rolling restart for {deployment_name}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def action_scale_up(
    clients: dict,
    deployment_name: str,
    namespace: str,
    target_replicas: int,
) -> str:
    """Scale up a deployment's HPA minimum replicas."""
    autoscaling_api = clients["autoscaling"]
    try:
        hpa = autoscaling_api.read_namespaced_horizontal_pod_autoscaler(
            deployment_name, namespace
        )
        current_min = hpa.spec.min_replicas or 1
        new_min = max(current_min, target_replicas)
        patch = {"spec": {"minReplicas": new_min}}
        autoscaling_api.patch_namespaced_horizontal_pod_autoscaler(
            deployment_name, namespace, patch
        )
        return f"Scaled up {deployment_name} HPA min replicas from {current_min} to {new_min}"
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            # No HPA — patch deployment directly
            apps_api = clients["apps"]
            patch = {"spec": {"replicas": target_replicas}}
            apps_api.patch_namespaced_deployment(deployment_name, namespace, patch)
            return f"Scaled {deployment_name} to {target_replicas} replicas (no HPA found)"
        raise


def create_kubernetes_event(
    clients: dict,
    namespace: str,
    deployment_name: str,
    action: str,
    message: str,
    reason: str = "SelfHealing",
) -> None:
    """Create a Kubernetes Event for audit trail visibility."""
    core_api = clients["core"]
    now = datetime.utcnow()
    event = kubernetes.client.CoreV1Event(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"infragpt-{deployment_name}-{int(now.timestamp())}",
            namespace=namespace,
        ),
        involved_object=kubernetes.client.V1ObjectReference(
            api_version="apps/v1",
            kind="Deployment",
            name=deployment_name,
            namespace=namespace,
        ),
        reason=reason,
        message=message,
        type="Warning" if action != "notify-only" else "Normal",
        event_time=now,
        first_timestamp=now,
        last_timestamp=now,
        reporting_component="infragpt-operator",
        reporting_instance="self-healing-operator",
        action=action,
        count=1,
    )
    try:
        core_api.create_namespaced_event(namespace, event)
    except Exception as exc:
        logger.warning("Failed to create Kubernetes event", extra={"error": str(exc)})


def send_slack_alert(
    service: str,
    namespace: str,
    action: str,
    message: str,
    trigger: str,
) -> None:
    """Send a Slack notification for a healing action."""
    if not SLACK_WEBHOOK_URL:
        return

    action_emoji = {
        "rollback": "⏪",
        "restart": "🔄",
        "scale-up": "📈",
        "notify-only": "📢",
    }
    emoji = action_emoji.get(action, "🔧")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Self-Healing Action: {action.upper()} — {service}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n{service}"},
                    {"type": "mrkdwn", "text": f"*Namespace:*\n{namespace}"},
                    {"type": "mrkdwn", "text": f"*Action:*\n{action}"},
                    {"type": "mrkdwn", "text": f"*Trigger:*\n{trigger}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Result:*\n{message}"},
            },
        ]
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as exc:
        logger.warning("Failed to send Slack alert", extra={"error": str(exc)})


# ─── Cooldown Tracking ────────────────────────────────────────────────────────

# In-memory cooldown tracker: {policy_uid: last_action_time}
_cooldown_tracker: dict[str, datetime] = {}


def is_in_cooldown(policy_uid: str, cooldown_period: str) -> bool:
    """Check if a policy is in its cooldown period."""
    last_action = _cooldown_tracker.get(policy_uid)
    if not last_action:
        return False

    # Parse cooldown period (e.g., "10m", "1h")
    period_str = cooldown_period.rstrip("mhsd")
    unit = cooldown_period[-1]
    try:
        period_value = int(period_str)
    except ValueError:
        return False

    delta_map = {"m": timedelta(minutes=period_value), "h": timedelta(hours=period_value), "s": timedelta(seconds=period_value)}
    delta = delta_map.get(unit, timedelta(minutes=10))

    return datetime.utcnow() - last_action < delta


def set_cooldown(policy_uid: str) -> None:
    """Record that a healing action was just taken."""
    _cooldown_tracker[policy_uid] = datetime.utcnow()


# ─── kopf Handlers ────────────────────────────────────────────────────────────

@kopf.on.startup()
def startup(settings: kopf.OperatorSettings, **kwargs):
    """Configure operator settings on startup."""
    settings.persistence.finalizer = "infragpt.io/healing-policy-finalizer"
    settings.posting.level = logging.WARNING
    start_http_server(METRICS_PORT)
    logger.info("Self-healing operator started", extra={"metrics_port": METRICS_PORT})


@kopf.on.create("infragpt.io", "v1alpha1", "healingpolicies")
def on_policy_created(spec, name, namespace, uid, **kwargs):
    """Handle HealingPolicy creation."""
    ACTIVE_POLICIES.inc()
    logger.info(
        "HealingPolicy created",
        extra={"name": name, "namespace": namespace, "target": spec.get("targetService")},
    )
    return {"message": f"Policy {name} registered for service {spec.get('targetService')}"}


@kopf.on.delete("infragpt.io", "v1alpha1", "healingpolicies")
def on_policy_deleted(spec, name, namespace, **kwargs):
    """Handle HealingPolicy deletion."""
    ACTIVE_POLICIES.dec()
    logger.info("HealingPolicy deleted", extra={"name": name, "namespace": namespace})


@kopf.timer("infragpt.io", "v1alpha1", "healingpolicies", interval=30.0, initial_delay=10.0)
def evaluate_healing_policy(spec, name, namespace, uid, patch, **kwargs):
    """
    Core healing loop — runs every 30 seconds for every HealingPolicy.
    Evaluates conditions and takes action if triggered.
    """
    if not spec.get("enabled", True):
        return

    target_service = spec["targetService"]
    target_namespace = spec.get("targetNamespace", namespace)
    conditions = spec.get("conditions", [])
    actions = spec.get("actions", [])
    cooldown_period = spec.get("cooldownPeriod", "10m")

    # Check cooldown
    if is_in_cooldown(uid, cooldown_period):
        logger.debug("Policy in cooldown", extra={"policy": name, "service": target_service})
        return

    prom = get_prometheus()
    clients = get_k8s_clients()

    # Evaluate all conditions
    triggered_conditions = []
    for condition in conditions:
        is_triggered, current_value = evaluate_condition(prom, condition)
        if is_triggered:
            triggered_conditions.append({
                "condition": condition,
                "current_value": current_value,
            })

    if not triggered_conditions:
        return

    # Conditions met — take action
    trigger_description = "; ".join(
        f"{c['condition']['metric'][:50]}={c['current_value']:.4f} (threshold: {c['condition']['threshold']})"
        for c in triggered_conditions
    )

    logger.warning(
        "Healing conditions triggered",
        extra={
            "policy": name,
            "service": target_service,
            "namespace": target_namespace,
            "conditions_triggered": len(triggered_conditions),
        },
    )

    # Execute actions in order
    for action_spec in actions:
        action_type = action_spec["type"]
        start_time = time.time()

        try:
            if action_type == "rollback":
                result = action_rollback(clients, target_service, target_namespace)
            elif action_type == "restart":
                result = action_restart(clients, target_service, target_namespace)
            elif action_type == "scale-up":
                target_replicas = action_spec.get("scaleReplicas", 3)
                result = action_scale_up(clients, target_service, target_namespace, target_replicas)
            elif action_type == "notify-only":
                result = f"Notification sent for {target_service} — no automated action taken"
            else:
                logger.warning("Unknown action type", extra={"action": action_type})
                continue

            duration = time.time() - start_time
            HEALING_ACTIONS_TOTAL.labels(
                action=action_type,
                service=target_service,
                namespace=target_namespace,
                trigger=triggered_conditions[0]["condition"]["metric"][:50],
            ).inc()
            HEALING_DURATION.labels(action=action_type, service=target_service).observe(duration)

            # Create Kubernetes Event
            create_kubernetes_event(
                clients,
                target_namespace,
                target_service,
                action_type,
                f"InfraGPT self-healing: {result}. Trigger: {trigger_description}",
            )

            # Send Slack notification
            if action_spec.get("notifySlack", True):
                send_slack_alert(
                    target_service,
                    target_namespace,
                    action_type,
                    result,
                    trigger_description,
                )

            logger.info(
                "Healing action completed",
                extra={
                    "action": action_type,
                    "service": target_service,
                    "result": result,
                    "duration_seconds": f"{duration:.2f}",
                },
            )

            # Update policy status
            patch.status["lastActionTime"] = datetime.utcnow().isoformat()
            patch.status["lastAction"] = action_type
            patch.status["totalActionsCount"] = (
                kwargs.get("status", {}).get("totalActionsCount", 0) + 1
            )

            # Set cooldown after successful action
            set_cooldown(uid)
            break  # Stop after first successful action

        except Exception as exc:
            logger.error(
                "Healing action failed",
                extra={"action": action_type, "service": target_service, "error": str(exc)},
            )


@kopf.on.field("apps", "v1", "deployments", field="status.conditions")
def on_deployment_conditions_changed(
    old, new, name, namespace, spec, status, **kwargs
):
    """
    Watch all Deployments for failed rollouts.
    Auto-rollback when a deployment enters Progressing=False state.
    """
    if not new:
        return

    # Check for failed progression
    for condition in new:
        if (
            condition.get("type") == "Progressing"
            and condition.get("status") == "False"
            and condition.get("reason") == "ProgressDeadlineExceeded"
        ):
            logger.warning(
                "Deployment rollout failed — triggering auto-rollback",
                extra={"deployment": name, "namespace": namespace},
            )

            clients = get_k8s_clients()
            try:
                result = action_rollback(clients, name, namespace)
                create_kubernetes_event(
                    clients,
                    namespace,
                    name,
                    "rollback",
                    f"Auto-rollback triggered: {result}. Reason: ProgressDeadlineExceeded",
                    reason="AutoRollback",
                )
                send_slack_alert(
                    name,
                    namespace,
                    "rollback",
                    f"Auto-rollback: {result}",
                    "ProgressDeadlineExceeded",
                )
                HEALING_ACTIONS_TOTAL.labels(
                    action="rollback",
                    service=name,
                    namespace=namespace,
                    trigger="ProgressDeadlineExceeded",
                ).inc()
                logger.info("Auto-rollback completed", extra={"deployment": name, "result": result})
            except Exception as exc:
                logger.error(
                    "Auto-rollback failed",
                    extra={"deployment": name, "error": str(exc)},
                )


@kopf.on.probe(id="healthz")
def health_probe(**kwargs):
    """Liveness probe for the operator."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
