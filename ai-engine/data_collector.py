"""
InfraGPT AI Engine — Data Collector

Fetches 30 days of Prometheus metrics and stores them as Parquet files.
Runs as a Kubernetes CronJob once per day.
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from prometheus_api_client import PrometheusConnect, MetricRangeDataFrame
from pythonjsonlogger import jsonlogger
from tenacity import retry, stop_after_attempt, wait_exponential

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.data_collector")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── Configuration ────────────────────────────────────────────────────────────

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://kube-prometheus-stack-prometheus.monitoring:9090")
DATA_DIR = Path(os.getenv("DATA_DIR", "/data/metrics"))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "30"))
STEP = os.getenv("STEP", "1m")  # 1-minute resolution

# Metrics to collect — (name, PromQL query, description)
METRICS_TO_COLLECT = [
    (
        "cpu_usage",
        'sum by (pod, namespace) (rate(container_cpu_usage_seconds_total{namespace="production", container!=""}[5m]))',
        "CPU usage per pod",
    ),
    (
        "memory_usage",
        'sum by (pod, namespace) (container_memory_working_set_bytes{namespace="production", container!=""})',
        "Memory usage per pod",
    ),
    (
        "http_request_rate",
        'sum by (app, namespace) (rate(backend_http_requests_total{namespace="production"}[5m]))',
        "HTTP request rate per service",
    ),
    (
        "http_error_rate",
        'sum by (app, namespace) (rate(backend_http_requests_total{namespace="production", status_code=~"5.."}[5m]))',
        "HTTP 5xx error rate per service",
    ),
    (
        "pod_restarts",
        'sum by (pod, namespace) (increase(kube_pod_container_status_restarts_total{namespace="production"}[1h]))',
        "Pod restart count per hour",
    ),
    (
        "request_latency_p99",
        'histogram_quantile(0.99, sum by (le, app) (rate(backend_http_request_duration_seconds_bucket{namespace="production"}[5m])))',
        "p99 request latency per service",
    ),
]


# ─── Prometheus Client ────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_prometheus_client() -> PrometheusConnect:
    """Create and verify Prometheus connection."""
    prom = PrometheusConnect(url=PROMETHEUS_URL, disable_ssl=True)
    if not prom.check_prometheus_connection():
        raise ConnectionError(f"Cannot connect to Prometheus at {PROMETHEUS_URL}")
    logger.info("Connected to Prometheus", extra={"url": PROMETHEUS_URL})
    return prom


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_metric(
    prom: PrometheusConnect,
    metric_name: str,
    query: str,
    start_time: datetime,
    end_time: datetime,
) -> Optional[pd.DataFrame]:
    """Fetch a single metric from Prometheus and return as DataFrame."""
    try:
        logger.info(
            "Fetching metric",
            extra={"metric": metric_name, "start": start_time.isoformat(), "end": end_time.isoformat()},
        )
        data = prom.get_metric_range_data(
            metric_name=query,
            start_time=start_time,
            end_time=end_time,
            chunk_size=timedelta(days=1),
        )
        if not data:
            logger.warning("No data returned for metric", extra={"metric": metric_name})
            return None

        df = MetricRangeDataFrame(data)
        df.index = pd.to_datetime(df.index, unit="s", utc=True)
        df["metric_name"] = metric_name
        logger.info(
            "Fetched metric data",
            extra={"metric": metric_name, "rows": len(df), "columns": list(df.columns)},
        )
        return df
    except Exception as exc:
        logger.error("Failed to fetch metric", extra={"metric": metric_name, "error": str(exc)})
        raise


def save_metric(df: pd.DataFrame, metric_name: str, date_str: str) -> Path:
    """Save metric DataFrame as Parquet file."""
    output_dir = DATA_DIR / metric_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{date_str}.parquet"
    df.to_parquet(output_path, engine="pyarrow", compression="snappy")
    logger.info(
        "Saved metric data",
        extra={"metric": metric_name, "path": str(output_path), "rows": len(df)},
    )
    return output_path


def collect_all_metrics() -> dict[str, int]:
    """Main collection loop — fetch all metrics and save to disk."""
    prom = get_prometheus_client()
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=LOOKBACK_DAYS)
    date_str = end_time.strftime("%Y-%m-%d")

    results: dict[str, int] = {}

    for metric_name, query, description in METRICS_TO_COLLECT:
        logger.info("Collecting metric", extra={"metric": metric_name, "description": description})
        try:
            df = fetch_metric(prom, metric_name, query, start_time, end_time)
            if df is not None and not df.empty:
                save_metric(df, metric_name, date_str)
                results[metric_name] = len(df)
            else:
                results[metric_name] = 0
        except Exception as exc:
            logger.error(
                "Failed to collect metric",
                extra={"metric": metric_name, "error": str(exc)},
            )
            results[metric_name] = -1

    return results


if __name__ == "__main__":
    logger.info("Starting data collection", extra={"lookback_days": LOOKBACK_DAYS})
    try:
        results = collect_all_metrics()
        total_rows = sum(v for v in results.values() if v > 0)
        failed = [k for k, v in results.items() if v < 0]
        logger.info(
            "Data collection complete",
            extra={"total_rows": total_rows, "metrics": results, "failed": failed},
        )
        if failed:
            logger.warning("Some metrics failed to collect", extra={"failed": failed})
            sys.exit(1)
    except Exception as exc:
        logger.error("Data collection failed", extra={"error": str(exc)})
        sys.exit(1)
