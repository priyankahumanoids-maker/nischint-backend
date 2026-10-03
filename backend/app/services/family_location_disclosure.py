"""Field filtering shared by the live-status disclosure boundary (no I/O)."""
import math


def has_coordinates(value) -> bool:
    if isinstance(value, dict):
        lat = value.get("lat", value.get("latitude"))
        lng = value.get("lng", value.get("longitude"))
        if (isinstance(lat, (int, float)) and not isinstance(lat, bool)
                and isinstance(lng, (int, float)) and not isinstance(lng, bool)
                and math.isfinite(lat) and math.isfinite(lng)
                and -90 <= lat <= 90 and -180 <= lng <= 180):
            return True
        return any(has_coordinates(v) for v in value.values() if isinstance(v, (dict, list)))
    if isinstance(value, list):
        return any(has_coordinates(v) for v in value)
    return False


def filter_live_status(payload: dict, *, activity: bool, history: bool, ai: bool) -> dict:
    result = dict(payload)
    current = dict(result.get("session") or {})
    if not activity:
        current = {k: v for k, v in current.items()
                   if k in {"session_id", "current_location", "last_update_seconds"}}
        result["session_active"] = None
    if not history:
        current.pop("route_points", None)
    if not ai:
        for key in ("risk_level", "risk_score", "is_idle", "is_night",
                    "route_deviated", "escalation_level", "alert_count"):
            current.pop(key, None)
        result.update(risk=None, behavior_pattern=None, recommendation=None)
    result["session"] = current or None
    if not (history and activity and ai):
        # Alert messages/recommendations may themselves contain inference or
        # historical coordinates. Do not leak them through free-form text.
        result["recent_alerts"] = []
    result["past_sessions"] = [
        {k: v for k, v in item.items() if ai or k != "risk_level"}
        for item in result.get("past_sessions", [])
    ] if history and activity else []
    return result
