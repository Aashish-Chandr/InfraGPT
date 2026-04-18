"""
InfraGPT AI Engine — Model Training

Trains Prophet (time-series forecasting) and Isolation Forest (anomaly detection)
models on collected Prometheus metrics. Saves models as .pkl files.
"""

import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from prophet import Prophet
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from pythonjsonlogger import jsonlogger

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*cmdstanpy.*")

# ─── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("infragpt.train")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ─── Configuration ────────────────────────────────────────────────────────────

DATA_DIR = Path(os.getenv("DATA_DIR", "/data/metrics"))
MODEL_DIR = Path(os.getenv("MODEL_DIR", "/data/models"))
MIN_TRAINING_ROWS = int(os.getenv("MIN_TRAINING_ROWS", "100"))

# Prophet configuration
PROPHET_CONFIG = {
    "changepoint_prior_scale": 0.05,
    "seasonality_prior_scale": 10.0,
    "holidays_prior_scale": 10.0,
    "seasonality_mode": "multiplicative",
    "interval_width": 0.95,  # 95% confidence interval
    "daily_seasonality": True,
    "weekly_seasonality": True,
    "yearly_seasonality": False,
}

# Isolation Forest configuration
ISOLATION_FOREST_CONFIG = {
    "n_estimators": 200,
    "contamination": 0.05,  # Expect ~5% anomalies
    "max_samples": "auto",
    "random_state": 42,
    "n_jobs": -1,
}


# ─── Data Loading ─────────────────────────────────────────────────────────────

def load_metric_data(metric_name: str) -> Optional[pd.DataFrame]:
    """Load all Parquet files for a metric and concatenate."""
    metric_dir = DATA_DIR / metric_name
    if not metric_dir.exists():
        logger.warning("No data directory for metric", extra={"metric": metric_name})
        return None

    parquet_files = sorted(metric_dir.glob("*.parquet"))
    if not parquet_files:
        logger.warning("No Parquet files found", extra={"metric": metric_name})
        return None

    dfs = []
    for f in parquet_files:
        try:
            df = pd.read_parquet(f, engine="pyarrow")
            dfs.append(df)
        except Exception as exc:
            logger.warning("Failed to read Parquet file", extra={"file": str(f), "error": str(exc)})

    if not dfs:
        return None

    combined = pd.concat(dfs, ignore_index=False)
    combined = combined.sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    logger.info(
        "Loaded metric data",
        extra={"metric": metric_name, "rows": len(combined), "files": len(parquet_files)},
    )
    return combined


# ─── Prophet Training ─────────────────────────────────────────────────────────

def train_prophet_model(
    series: pd.Series,
    entity_id: str,
    metric_name: str,
) -> Optional[Prophet]:
    """Train a Prophet model for a single time series."""
    if len(series) < MIN_TRAINING_ROWS:
        logger.warning(
            "Insufficient data for Prophet training",
            extra={"entity": entity_id, "metric": metric_name, "rows": len(series)},
        )
        return None

    # Prophet requires columns 'ds' (datetime) and 'y' (value)
    df_prophet = pd.DataFrame({
        "ds": series.index.tz_localize(None) if series.index.tz else series.index,
        "y": series.values.astype(float),
    })

    # Remove NaN and infinite values
    df_prophet = df_prophet.replace([np.inf, -np.inf], np.nan).dropna()

    if len(df_prophet) < MIN_TRAINING_ROWS:
        return None

    # Cap extreme outliers at 3 standard deviations for stable training
    mean, std = df_prophet["y"].mean(), df_prophet["y"].std()
    if std > 0:
        df_prophet["y"] = df_prophet["y"].clip(mean - 3 * std, mean + 3 * std)

    try:
        model = Prophet(**PROPHET_CONFIG)
        # Suppress Prophet's verbose output
        import logging as _logging
        _logging.getLogger("prophet").setLevel(_logging.WARNING)
        _logging.getLogger("cmdstanpy").setLevel(_logging.WARNING)

        model.fit(df_prophet)
        logger.info(
            "Prophet model trained",
            extra={"entity": entity_id, "metric": metric_name, "training_rows": len(df_prophet)},
        )
        return model
    except Exception as exc:
        logger.error(
            "Prophet training failed",
            extra={"entity": entity_id, "metric": metric_name, "error": str(exc)},
        )
        return None


# ─── Isolation Forest Training ────────────────────────────────────────────────

def train_isolation_forest(
    df: pd.DataFrame,
    metric_name: str,
) -> Optional[tuple[IsolationForest, StandardScaler]]:
    """Train an Isolation Forest on the full metric dataset."""
    # Pivot to wide format: rows=timestamps, columns=entities
    try:
        # Get numeric columns only
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            return None

        feature_matrix = df[numeric_cols].fillna(0).replace([np.inf, -np.inf], 0)

        if len(feature_matrix) < MIN_TRAINING_ROWS:
            return None

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(feature_matrix)

        model = IsolationForest(**ISOLATION_FOREST_CONFIG)
        model.fit(X_scaled)

        # Compute training anomaly rate
        predictions = model.predict(X_scaled)
        anomaly_rate = (predictions == -1).mean()
        logger.info(
            "Isolation Forest trained",
            extra={
                "metric": metric_name,
                "training_rows": len(feature_matrix),
                "features": len(numeric_cols),
                "anomaly_rate": f"{anomaly_rate:.2%}",
            },
        )
        return model, scaler
    except Exception as exc:
        logger.error(
            "Isolation Forest training failed",
            extra={"metric": metric_name, "error": str(exc)},
        )
        return None


# ─── Model Persistence ────────────────────────────────────────────────────────

def save_model(model: object, model_type: str, metric_name: str, entity_id: str = "global") -> Path:
    """Save a trained model to disk."""
    model_dir = MODEL_DIR / model_type / metric_name
    model_dir.mkdir(parents=True, exist_ok=True)
    # Sanitize entity_id for use as filename
    safe_entity = entity_id.replace("/", "_").replace(":", "_")
    model_path = model_dir / f"{safe_entity}.pkl"
    joblib.dump(model, model_path)
    logger.info("Model saved", extra={"path": str(model_path)})
    return model_path


# ─── Main Training Loop ───────────────────────────────────────────────────────

def train_all_models() -> dict:
    """Train Prophet and Isolation Forest models for all collected metrics."""
    results = {"prophet": {}, "isolation_forest": {}}

    metrics = [d.name for d in DATA_DIR.iterdir() if d.is_dir()]
    if not metrics:
        logger.error("No metric data found in DATA_DIR", extra={"data_dir": str(DATA_DIR)})
        return results

    logger.info("Starting model training", extra={"metrics": metrics})

    for metric_name in metrics:
        df = load_metric_data(metric_name)
        if df is None or df.empty:
            continue

        # ── Prophet: one model per entity (pod/service) ──────────────────────
        entity_columns = [c for c in df.columns if c not in ("metric_name", "value")]
        value_col = "value" if "value" in df.columns else df.select_dtypes(include=[np.number]).columns[0]

        # Group by entity labels if available
        label_cols = [c for c in df.columns if c not in (value_col, "metric_name")]
        if label_cols:
            grouped = df.groupby(label_cols)
            for entity_key, group_df in grouped:
                entity_id = "_".join(str(v) for v in (entity_key if isinstance(entity_key, tuple) else [entity_key]))
                series = group_df[value_col].sort_index()
                model = train_prophet_model(series, entity_id, metric_name)
                if model:
                    save_model(model, "prophet", metric_name, entity_id)
                    results["prophet"][f"{metric_name}/{entity_id}"] = "trained"
        else:
            series = df[value_col].sort_index()
            model = train_prophet_model(series, "global", metric_name)
            if model:
                save_model(model, "prophet", metric_name, "global")
                results["prophet"][metric_name] = "trained"

        # ── Isolation Forest: one model per metric ────────────────────────────
        iso_result = train_isolation_forest(df, metric_name)
        if iso_result:
            iso_model, scaler = iso_result
            save_model(iso_model, "isolation_forest", metric_name, "model")
            save_model(scaler, "isolation_forest", metric_name, "scaler")
            results["isolation_forest"][metric_name] = "trained"

    logger.info(
        "Training complete",
        extra={
            "prophet_models": len(results["prophet"]),
            "isolation_forest_models": len(results["isolation_forest"]),
        },
    )
    return results


if __name__ == "__main__":
    logger.info("Starting model training pipeline")
    results = train_all_models()
    if not results["prophet"] and not results["isolation_forest"]:
        logger.error("No models were trained — check that data collection has run first")
        sys.exit(1)
    logger.info("Training pipeline complete", extra={"results": results})
