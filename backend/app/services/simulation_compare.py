# Simulation Comparison Service — Pure read-only battery config comparison
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def compare_battery_configs(
    session: AsyncSession,
    config_a: dict,
    config_b: dict,
    min_heartbeats: int,
) -> dict:
    """
    Compare two battery threshold configs against live telemetry.
    Pure read-only — no DB writes, no side effects.

    A device is "matched" if:
      - It has >= min_heartbeats heartbeats in the last sustain_minutes
      - ALL battery readings in that window are < battery_percent

    Returns a diff report with matched devices for each config and delta analysis.
    """
    eval_window = max(config_a["sustain_minutes"], config_b["sustain_minutes"])
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=eval_window)

    # Single query: fetch all heartbeat telemetry with battery_level in the window,
    # joined to device → senior → guardian for display names.
    # Exclude simulated data.
    rows = (await session.execute(text("""
        SELECT d.device_identifier,
               s.full_name AS senior_name,
               u.full_name AS guardian_full_name,
               u.email AS guardian_email,
               (t.metric_value->>'battery_level')::float AS battery_level,
               t.created_at
        FROM telemetries t
        JOIN devices d ON t.device_id = d.id
        JOIN seniors s ON d.senior_id = s.id
        JOIN users u ON s.guardian_id = u.id
        WHERE t.metric_type = 'heartbeat'
          AND t.is_simulated = false
          AND t.created_at >= :cutoff
          AND (t.metric_value->>'battery_level') IS NOT NULL
        ORDER BY d.device_identifier, t.created_at DESC
    """), {"cutoff": cutoff})).fetchall()

    # Group by device
    devices: dict[str, dict] = {}
    for r in rows:
        did = r.device_identifier
        if did not in devices:
            devices[did] = {
                "device_identifier": did,
                "senior_name": r.senior_name,
                "guardian_name": r.guardian_full_name or r.guardian_email,
                "readings": [],
            }
        devices[did]["readings"].append({
            "battery_level": r.battery_level,
            "created_at": r.created_at,
        })

    def _matches(device_data: dict, cfg: dict) -> bool:
        """Check if device matches a config's sustained low-battery condition."""
        sustain_cutoff = datetime.now(timezone.utc) - timedelta(minutes=cfg["sustain_minutes"])
        window_readings = [
            rd for rd in device_data["readings"]
            if rd["created_at"] >= sustain_cutoff
        ]
        if len(window_readings) < min_heartbeats:
            return False
        return all(rd["battery_level"] < cfg["battery_percent"] for rd in window_readings)

    # Evaluate both configs
    matched_a: set[str] = set()
    matched_b: set[str] = set()

    for did, ddata in devices.items():
        if _matches(ddata, config_a):
            matched_a.add(did)
        if _matches(ddata, config_b):
            matched_b.add(did)

    # Compute delta sets
    newly_flagged = matched_b - matched_a
    no_longer_flagged = matched_a - matched_b
    intersection = matched_a & matched_b

    def _device_list(identifiers: set) -> list[dict]:
        return [
            {
                "device_identifier": did,
                "senior_name": devices[did]["senior_name"],
                "guardian_name": devices[did]["guardian_name"],
            }
            for did in sorted(identifiers)
        ]

    return {
        "metric": "battery_level",
        "evaluation_window_minutes": eval_window,
        "min_heartbeats": min_heartbeats,
        "a": {
            "threshold": config_a,
            "matched_devices_count": len(matched_a),
        },
        "b": {
            "threshold": config_b,
            "matched_devices_count": len(matched_b),
        },
        "delta": {
            "newly_flagged_count": len(newly_flagged),
            "no_longer_flagged_count": len(no_longer_flagged),
            "intersection_count": len(intersection),
        },
        "newly_flagged_devices": _device_list(newly_flagged),
        "no_longer_flagged_devices": _device_list(no_longer_flagged),
        "matched_in_both": _device_list(intersection),
    }
