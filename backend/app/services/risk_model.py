"""
NISCHINT AI Learning Loop — Phase 2: Risk Prediction Model

XGBoost classifier trained on historical incident data.
Input: feature vector from Feature Store
Output: risk_probability (0.0–1.0) + risk_factors explaining why.

Model is saved to disk as models/risk_model.pkl and metadata in Redis.
Retrain via APScheduler or on-demand.
"""
import os
import logging
import json
from datetime import datetime, timezone
from pathlib import Path

# ── Feature flag ────────────────────────────────────────────────────
# ML inference (XGBoost/RandomForest) can be disabled via ML_ENABLED=false
# on resource-constrained deployments (e.g., small Kubernetes pods).
# When disabled:
#   • predict()       → returns {"error": "ml_disabled"} (no CPU burn)
#   • train_model()   → returns {"error": "ml_disabled"} and scheduler no-ops
#   • load_model()    → returns False (as if the .pkl didn't exist)
# Default: true — preserves existing behaviour in dev/staging where ML runs.
ML_ENABLED = os.getenv("ML_ENABLED", "true").lower() == "true"

# CRITICAL FOR MEMORY: numpy + joblib alone cost ~66 MB RSS at import time.
# When ML_ENABLED=false (production OOM-mitigation deployments), the
# predict() / train_model() / load_model() functions early-return without
# ever touching np or joblib, so importing them is pure dead weight.
# Gate the imports behind the feature flag.
if ML_ENABLED:
    try:
        import joblib
        HAS_JOBLIB = True
    except ImportError:
        joblib = None
        HAS_JOBLIB = False
        logging.getLogger(__name__).warning("joblib not available — ML model persistence disabled")

    try:
        import numpy as np
        HAS_NUMPY = True
    except ImportError:
        np = None
        HAS_NUMPY = False
        logging.getLogger(__name__).warning("numpy not available — ML features disabled")
else:
    joblib = None
    np = None
    HAS_JOBLIB = False
    HAS_NUMPY = False

HAS_ML = HAS_NUMPY and HAS_JOBLIB and ML_ENABLED

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"
MODEL_PATH = MODEL_DIR / "risk_model.pkl"
META_PATH = MODEL_DIR / "risk_model_meta.json"

# Feature columns used by the model
FEATURE_COLS = [
    "hour_of_day", "day_of_week",
    "location_lat", "location_lng",
    "area_risk_score", "movement_speed",
    "time_since_last_incident", "anomaly_count",
    "zone_type_encoded",
]

ZONE_TYPE_MAP = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Singleton model
_model = None
_model_meta = None


def _ensure_model_dir():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _encode_zone(zone_type: str) -> int:
    return ZONE_TYPE_MAP.get(zone_type, 0)


def features_to_array(features: dict):
    """Convert a feature dict to a numpy array for prediction."""
    if not HAS_NUMPY:
        return None
    return np.array([[
        features.get("hour_of_day", 12),
        features.get("day_of_week", 3),
        features.get("location_lat", 19.076),
        features.get("location_lng", 72.877),
        features.get("area_risk_score", 0.1),
        features.get("movement_speed", 0.0),
        features.get("time_since_last_incident", 720.0),
        features.get("anomaly_count", 0),
        _encode_zone(features.get("zone_type", "low")),
    ]])


def features_list_to_xy(data: list[dict]):
    """Convert list of feature dicts to X, y arrays for training."""
    if not HAS_NUMPY:
        return None, None
    X = []
    y = []
    for row in data:
        X.append([
            row.get("hour_of_day", 12),
            row.get("day_of_week", 3),
            row.get("location_lat", 19.076),
            row.get("location_lng", 72.877),
            row.get("area_risk_score", 0.1),
            row.get("movement_speed", 0.0),
            row.get("time_since_last_incident", 720.0),
            row.get("anomaly_count", 0),
            _encode_zone(row.get("zone_type", "low")),
        ])
        y.append(1 if row.get("incident_occurred", False) else 0)
    return np.array(X), np.array(y)


def train_model(training_data: list[dict], feedback_weights: dict = None) -> dict:
    """
    Train XGBoost classifier on historical data.
    Returns metadata about the trained model.

    No-op when ML_ENABLED=false or required libs aren't installed — returns a
    structured error dict so the scheduler/API layer can log and carry on.
    """
    if not HAS_ML:
        reason = "ml_disabled" if not ML_ENABLED else "ml_libs_unavailable"
        logger.info(f"[RISK_MODEL] train skipped ({reason})")
        return {"error": reason, "samples_used": 0}
    global _model, _model_meta

    if not HAS_ML:
        logger.warning("ML packages not installed — training skipped")
        return {"error": "ml_not_available", "message": "ML packages not installed on this environment"}

    if len(training_data) < 20:
        logger.warning(f"Insufficient training data ({len(training_data)} rows, need 20+)")
        return {"error": "insufficient_data", "rows": len(training_data)}

    X, y = features_list_to_xy(training_data)

    positive_count = int(y.sum())
    negative_count = len(y) - positive_count

    if positive_count == 0 or negative_count == 0:
        logger.warning("No positive or negative labels — using balanced synthetic augmentation")
        # Add synthetic positive samples based on high-risk patterns
        for row in training_data[:min(20, len(training_data))]:
            synthetic = row.copy()
            synthetic["incident_occurred"] = True
            synthetic["area_risk_score"] = max(0.7, row.get("area_risk_score", 0.5))
            synthetic["hour_of_day"] = 23  # Late night
            synthetic["time_since_last_incident"] = 2.0  # Recent
            synthetic["anomaly_count"] = max(5, row.get("anomaly_count", 0))
            training_data.append(synthetic)

        # Add synthetic negative samples
        for row in training_data[:min(20, len(training_data))]:
            synthetic = row.copy()
            synthetic["incident_occurred"] = False
            synthetic["area_risk_score"] = 0.1
            synthetic["hour_of_day"] = 10  # Daytime
            synthetic["time_since_last_incident"] = 720.0  # Long ago
            synthetic["anomaly_count"] = 0
            training_data.append(synthetic)

        X, y = features_list_to_xy(training_data)
        positive_count = int(y.sum())
        negative_count = len(y) - positive_count

    # Apply feedback weights if available
    sample_weights = np.ones(len(y))
    if feedback_weights:
        for idx, row in enumerate(training_data[:len(y)]):
            uid = row.get("user_id", "")
            ts = row.get("timestamp", "")
            key = f"{uid}:{ts}"
            if key in feedback_weights:
                sample_weights[idx] = feedback_weights[key]

    # Train XGBoost
    try:
        from xgboost import XGBClassifier

        scale_pos_weight = max(1.0, negative_count / max(1, positive_count))

        model = XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            scale_pos_weight=scale_pos_weight,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
        )
        model.fit(X, y, sample_weight=sample_weights)

    except Exception as e:
        logger.warning(f"XGBoost training failed ({e}), falling back to RandomForest")
        from sklearn.ensemble import RandomForestClassifier
        model = RandomForestClassifier(
            n_estimators=100, max_depth=5, random_state=42, class_weight="balanced",
        )
        model.fit(X, y, sample_weight=sample_weights)

    # Save model
    _ensure_model_dir()
    if HAS_JOBLIB:
        joblib.dump(model, MODEL_PATH)

    # Feature importances
    importances = dict(zip(FEATURE_COLS, [round(float(v), 4) for v in model.feature_importances_]))

    # Model version
    version = datetime.now(timezone.utc).strftime("v%Y%m%d.%H%M")

    meta = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": len(y),
        "positive_samples": positive_count,
        "negative_samples": negative_count,
        "feature_importances": importances,
        "model_type": type(model).__name__,
    }

    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    _model = model
    _model_meta = meta

    logger.info(f"Model trained: {version}, {len(y)} samples, {positive_count} positives, type={type(model).__name__}")
    return meta


def load_model():
    """Load model from disk if not already in memory."""
    global _model, _model_meta

    if not HAS_ML:
        return False

    if _model is not None:
        return True

    if not MODEL_PATH.exists():
        logger.info("No trained model found on disk")
        return False

    try:
        _model = joblib.load(MODEL_PATH)
        if META_PATH.exists():
            with open(META_PATH) as f:
                _model_meta = json.load(f)
        logger.info(f"Model loaded: {_model_meta.get('version', 'unknown') if _model_meta else 'unknown'}")
        return True
    except Exception as e:
        logger.error(f"Model load failed: {e}")
        return False


def predict(features: dict) -> dict:
    """
    Predict risk probability for a feature vector.
    Returns risk_probability, risk_level, risk_factors, confidence.
    """
    if not load_model():
        return {"error": "model_not_available"}

    X = features_to_array(features)

    try:
        proba = _model.predict_proba(X)[0]
        risk_prob = float(proba[1]) if len(proba) > 1 else float(proba[0])
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return {"error": str(e)}

    # Confidence from probability distance from 0.5
    confidence = round(abs(risk_prob - 0.5) * 2, 2)

    # Risk level
    if risk_prob >= 0.75:
        risk_level = "critical"
    elif risk_prob >= 0.5:
        risk_level = "high"
    elif risk_prob >= 0.3:
        risk_level = "moderate"
    else:
        risk_level = "low"

    # Generate human-readable risk factors
    risk_factors = _explain_risk(features, risk_prob)

    return {
        "risk_probability": round(risk_prob, 3),
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "confidence": confidence,
        "model_version": _model_meta.get("version", "unknown") if _model_meta else "unknown",
    }


def _explain_risk(features: dict, risk_prob: float) -> list[str]:
    """Generate human-readable risk factor explanations."""
    factors = []

    hour = features.get("hour_of_day", 12)
    if hour >= 22 or hour <= 5:
        factors.append(f"High-risk hour: {hour}:00 (late night)")
    elif hour >= 18:
        factors.append(f"Evening hours: {hour}:00")

    area_risk = features.get("area_risk_score", 0)
    if area_risk >= 0.7:
        factors.append(f"High-risk area (score: {area_risk:.1f})")
    elif area_risk >= 0.4:
        factors.append(f"Moderate-risk area (score: {area_risk:.1f})")

    time_since = features.get("time_since_last_incident", 720)
    if time_since < 24:
        factors.append(f"Recent incident ({time_since:.0f}h ago)")
    elif time_since < 72:
        factors.append(f"Incident within last {time_since:.0f}h")

    anomaly = features.get("anomaly_count", 0)
    if anomaly >= 5:
        factors.append(f"High anomaly count: {anomaly} in last 30 days")
    elif anomaly >= 2:
        factors.append(f"Behavioral anomalies detected: {anomaly}")

    zone = features.get("zone_type", "low")
    if zone in ("high", "critical"):
        factors.append(f"Currently in {zone}-risk zone")

    speed = features.get("movement_speed", 0)
    if speed > 15:
        factors.append(f"Unusual movement speed: {speed:.1f} km/h")

    if not factors:
        if risk_prob >= 0.5:
            factors.append("Elevated risk based on combined pattern analysis")
        else:
            factors.append("Normal risk profile")

    return factors


def get_model_info() -> dict:
    """Get current model metadata."""
    if _model_meta:
        return _model_meta
    if META_PATH.exists():
        with open(META_PATH) as f:
            return json.load(f)
    return {"status": "no_model_trained"}
