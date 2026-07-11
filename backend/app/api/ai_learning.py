"""
NISCHINT AI Learning Loop — Phase 3 & 4: Prediction API + Feedback Loop

GET  /api/ai/predict-risk?user_id={id}  — ML-based risk prediction
POST /api/ai/feedback                   — Guardian feedback for model improvement
GET  /api/ai/model-info                 — Current model status
POST /api/ai/retrain                    — Trigger manual retrain
GET  /api/ai/training-data-stats        — Feature store stats
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.user import User
from app.services.feature_store import extract_all_training_data, get_live_features
from app.services.risk_model import predict, train_model, get_model_info, load_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-learning"])


@router.get("/predict-risk")
async def predict_risk(
    user_id: str = Query(..., description="User/guardian ID to predict risk for"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    ML-based risk prediction for a user.
    Returns risk_probability, risk_level, risk_factors, confidence, model_version.
    """
    # Get live features
    features = await get_live_features(session, user_id)
    if not features:
        return {"error": "no_data", "message": "No device data found for this user"}

    # Predict
    result = predict(features)

    if "error" in result and result["error"] == "model_not_available":
        # Auto-train if no model exists
        logger.info("No model available, triggering auto-train")
        training_data = await extract_all_training_data(session)
        if training_data:
            meta = train_model(training_data)
            if "error" not in meta:
                result = predict(features)
            else:
                return {
                    "risk_probability": 0.0,
                    "risk_level": "unknown",
                    "risk_factors": ["Model training failed — insufficient data"],
                    "confidence": 0.0,
                    "model_version": "none",
                    "fallback": True,
                }

    # Add next retrain time (midnight UTC)
    now = datetime.now(timezone.utc)
    next_retrain = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if next_retrain <= now:
        from datetime import timedelta
        next_retrain += timedelta(days=1)
    result["next_retrain"] = next_retrain.isoformat()
    result["features_used"] = features

    # Log to Sentry for monitoring
    try:
        import sentry_sdk
        sentry_sdk.set_context("ai_prediction", {
            "user_id": user_id,
            "risk_probability": result.get("risk_probability"),
            "risk_level": result.get("risk_level"),
            "model_version": result.get("model_version"),
        })
    except Exception:
        pass

    return result


class FeedbackRequest(BaseModel):
    incident_id: str
    alert_was_useful: bool
    guardian_response_time_sec: int = 0


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Submit feedback on an alert. Stored in model_feedback table.
    Useful alerts reinforce the pattern; false positives reduce weight.
    """
    # Ensure table exists
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS model_feedback (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            incident_id UUID NOT NULL,
            user_id UUID NOT NULL,
            alert_was_useful BOOLEAN NOT NULL,
            guardian_response_time_sec INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))

    await session.execute(text("""
        INSERT INTO model_feedback (incident_id, user_id, alert_was_useful, guardian_response_time_sec)
        VALUES (:iid, :uid, :useful, :time)
    """), {
        "iid": body.incident_id,
        "uid": str(current_user.id),
        "useful": body.alert_was_useful,
        "time": body.guardian_response_time_sec,
    })
    await session.commit()

    logger.info(f"Feedback stored: incident={body.incident_id}, useful={body.alert_was_useful}")
    return {"status": "stored", "incident_id": body.incident_id}


@router.post("/retrain")
async def retrain_model(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Manually trigger model retraining on latest data."""
    training_data = await extract_all_training_data(session)
    if not training_data:
        return {"error": "no_training_data", "message": "No training data available"}

    # Load feedback weights
    feedback_weights = await _load_feedback_weights(session)

    meta = train_model(training_data, feedback_weights)
    return {"status": "retrained", **meta}


@router.get("/model-info")
async def model_info(
    current_user: User = Depends(get_current_user),
):
    """Get current model metadata and status."""
    info = get_model_info()

    # Add feedback stats
    return {"model": info}


@router.get("/training-data-stats")
async def training_data_stats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get stats about available training data."""
    result = await session.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM telemetries) AS telemetry_count,
            (SELECT COUNT(*) FROM incidents WHERE status != 'false_alarm') AS incident_count,
            (SELECT COUNT(*) FROM behavior_anomalies) AS anomaly_count,
            (SELECT COUNT(*) FROM location_risk_zones) AS risk_zone_count,
            (SELECT COUNT(*) FROM city_risk_snapshots) AS snapshot_count,
            (SELECT COUNT(DISTINCT device_id) FROM telemetries) AS device_count,
            (SELECT COUNT(DISTINCT senior_id) FROM incidents) AS seniors_with_incidents
    """))
    row = result.fetchone()
    return {
        "telemetry_rows": row[0],
        "incident_rows": row[1],
        "anomaly_rows": row[2],
        "risk_zones": row[3],
        "city_snapshots": row[4],
        "devices_tracked": row[5],
        "seniors_with_incidents": row[6],
    }


async def _load_feedback_weights(session: AsyncSession) -> dict:
    """Load feedback weights for training. Useful=2.0x weight, not useful=0.3x."""
    try:
        result = await session.execute(text("""
            SELECT i.device_id::text, i.created_at, mf.alert_was_useful
            FROM model_feedback mf
            JOIN incidents i ON i.id = mf.incident_id
        """))
        weights = {}
        for r in result.fetchall():
            key = f"{r[0]}:{r[1].isoformat() if r[1] else ''}"
            weights[key] = 2.0 if r[2] else 0.3
        return weights
    except Exception:
        return {}
