"""Live Risk Panel — the Control Layer's single answer to:
"What needs attention in the next 10 seconds?"

Strict scope (v1):
  • Headline counters (active critical alerts, shadow sessions,
    offline sessions, TTFH p50/p95).
  • A short, urgency-ranked list of incidents with just enough
    context to decide without drilling in.
  • System-health rollup (SSE subscribers, push reachability,
    watchdog flips).

Performance contract: this gets polled every ~5s. Target <200ms.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.models.guardian import GuardianAlert, GuardianSession
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/command-center", tags=["Command Center"])

# Anything older than this on `previous_update_at` is "shadow" for
# panel purposes — same threshold as the watchdog uses.
SHADOW_GAP_S = 30

# Urgency ranks (higher = more attention). Pure number for sorting.
_URGENCY = {
    "escalated":           100,
    "ack_pending":          80,
    "shadow_session":       60,
    "active_alert":         40,
    "stale_session":        20,
}


def _rank_for(row_kind: str, alert: dict | None = None) -> int:
    """Rank rules — kept obvious so changes are auditable."""
    if row_kind == "alert":
        if alert and alert.get("ack_status") == "escalated":
            return _URGENCY["escalated"]
        if alert and alert.get("ack_status") == "pending":
            return _URGENCY["ack_pending"]
        return _URGENCY["active_alert"]
    if row_kind == "session_shadow":
        return _URGENCY["shadow_session"]
    if row_kind == "session_stale":
        return _URGENCY["stale_session"]
    return 0


async def _summary_counters(s: AsyncSession) -> dict[str, int | float | None]:
    """Top-strip counters. One round-trip via a CTE — keeps the panel
    fast under polling."""
    row = (await s.execute(text(
        """
        WITH alerts AS (
            SELECT
                COUNT(*) FILTER (WHERE ack_status = 'pending')    AS pending,
                COUNT(*) FILTER (WHERE ack_status = 'escalated')  AS escalated,
                COUNT(*) FILTER (WHERE severity   = 'critical'
                                  AND ack_status IN ('pending','escalated'))
                                                                  AS active_critical
              FROM guardian_alerts
             WHERE created_at >= NOW() - INTERVAL '24 hours'
        ),
        sessions AS (
            SELECT
                COUNT(*) FILTER (WHERE status = 'active')         AS active,
                COUNT(*) FILTER (WHERE status = 'active'
                                  AND is_offline = TRUE)          AS offline,
                COUNT(*) FILTER (WHERE status = 'active'
                                  AND is_offline = FALSE
                                  AND previous_update_at <
                                      NOW() - (:gap || ' seconds')::interval)
                                                                  AS stale
              FROM guardian_sessions
        )
        SELECT
            (SELECT pending          FROM alerts)   AS pending,
            (SELECT escalated        FROM alerts)   AS escalated,
            (SELECT active_critical  FROM alerts)   AS active_critical,
            (SELECT active           FROM sessions) AS active_sessions,
            (SELECT offline          FROM sessions) AS offline_sessions,
            (SELECT stale            FROM sessions) AS stale_sessions
        """
    ), {"gap": str(SHADOW_GAP_S)})).fetchone()
    return {
        "active_critical_alerts": int(row.active_critical or 0),
        "pending_acks":           int(row.pending or 0),
        "escalated_alerts":       int(row.escalated or 0),
        "active_sessions":        int(row.active_sessions or 0),
        "offline_sessions":       int(row.offline_sessions or 0),
        # `shadow_sessions` = offline + stale — operator's working
        # definition: "device unreachable right now". Watchdog will
        # flip stale → offline at the next 20s tick.
        "shadow_sessions":        int(row.offline_sessions or 0) + int(row.stale_sessions or 0),
    }


async def _ttfh_block(s: AsyncSession) -> dict[str, Any]:
    from app.services.alert_ack_engine import get_ttfh_metrics
    # Last 7 days — operationally relevant window. The /alerts/metrics
    # endpoint exposes 30d; the panel cares about "right now" trends.
    return await get_ttfh_metrics(s, window_days=7)


async def _incidents(s: AsyncSession, limit: int = 25) -> list[dict[str, Any]]:
    """Build the urgency-ranked incidents list.

    Two sources, merged + sorted:
      1. Open critical/high alerts (ack_status in pending/escalated)
      2. Active sessions whose device is unreachable (offline or stale)
         BUT only if no open alert already represents them — operator
         only needs one row per attention-needing entity.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    shadow_cutoff = now - timedelta(seconds=SHADOW_GAP_S)

    # 1) Open alerts (with subject user + linked session if any).
    alert_rows = (await s.execute(text(
        """
        SELECT a.id              AS alert_id,
               a.user_id         AS user_id,
               a.session_id      AS session_id,
               a.alert_type      AS alert_type,
               a.severity        AS severity,
               a.message         AS message,
               a.ack_status      AS ack_status,
               a.ack_type        AS ack_type,
               a.ack_deadline    AS ack_deadline,
               a.escalation_step AS escalation_step,
               a.created_at      AS created_at,
               a.context_json    AS context_json,
               u.full_name       AS user_name,
               s.status          AS session_status,
               s.is_offline      AS is_offline,
               s.previous_update_at AS previous_update_at,
               s.current_location   AS current_location
          FROM guardian_alerts a
          JOIN users u ON u.id = a.user_id
          LEFT JOIN guardian_sessions s ON s.id = a.session_id
         WHERE a.ack_required = true
           AND a.ack_status IN ('pending', 'escalated')
           AND a.created_at >= :cutoff
         ORDER BY a.created_at DESC
         LIMIT :lim
        """
    ), {"cutoff": cutoff_24h, "lim": limit})).fetchall() or []

    incidents: list[dict[str, Any]] = []
    covered_user_ids: set[str] = set()

    for r in alert_rows:
        user_id = str(r.user_id)
        ctx = r.context_json or {}
        ack_deadline_iso = r.ack_deadline.isoformat() if r.ack_deadline else None
        deadline_in_s = (
            int((r.ack_deadline - now).total_seconds())
            if r.ack_deadline else None
        )
        incident = {
            "kind":          "alert",
            "alert_id":      str(r.alert_id),
            "session_id":    str(r.session_id) if r.session_id else None,
            "user_id":       user_id,
            "child_name":    r.user_name,
            "alert_type":    r.alert_type,
            "severity":      r.severity,
            "message":       r.message,
            "ack_status":    r.ack_status,
            "ack_type":      r.ack_type,
            "ack_deadline":  ack_deadline_iso,
            "deadline_in_s": deadline_in_s,
            "escalation_step": int(r.escalation_step or 0),
            "tracking_mode": ctx.get("tracking_mode")
                             or ("shadow" if r.is_offline else "active"),
            "is_offline":    bool(r.is_offline) if r.is_offline is not None
                             else bool(ctx.get("is_offline", False)),
            "guardians":     ctx.get("guardians") or {},
            "last_location": (dict(r.current_location)
                              if r.current_location else
                              ctx.get("last_location")),
            "stale_seconds": (
                int((now - r.previous_update_at).total_seconds())
                if r.previous_update_at else None
            ),
            "created_at":    r.created_at.isoformat() if r.created_at else None,
            "rank":          _rank_for("alert", {"ack_status": r.ack_status}),
        }
        incidents.append(incident)
        covered_user_ids.add(user_id)

    # 2) Active sessions whose device is unreachable, NOT already
    #    represented by an open alert above.
    session_rows = (await s.execute(
        select(GuardianSession, User)
        .join(User, User.id == GuardianSession.user_id)
        .where(
            GuardianSession.status == "active",
            (
                (GuardianSession.is_offline == True) |  # noqa: E712
                (GuardianSession.previous_update_at < shadow_cutoff)
            ),
        )
        .order_by(GuardianSession.previous_update_at.asc())
        .limit(limit)
    )).all() or []

    for gs, u in session_rows:
        uid = str(gs.user_id)
        if uid in covered_user_ids:
            continue
        is_off = bool(gs.is_offline)
        gap_s = (
            int((now - gs.previous_update_at).total_seconds())
            if gs.previous_update_at else None
        )
        incidents.append({
            "kind":          "session",
            "alert_id":      None,
            "session_id":    str(gs.id),
            "user_id":       uid,
            "child_name":    u.full_name,
            "alert_type":    None,
            "severity":      None,
            "message":       (
                "Device offline" if is_off
                else f"GPS silent {gap_s}s"
            ),
            "ack_status":    None,
            "ack_type":      None,
            "ack_deadline":  None,
            "deadline_in_s": None,
            "escalation_step": 0,
            "tracking_mode": "shadow",
            "is_offline":    is_off,
            "guardians":     {},
            "last_location": dict(gs.current_location) if gs.current_location else None,
            "stale_seconds": gap_s,
            "created_at":    gs.previous_update_at.isoformat() if gs.previous_update_at else None,
            "rank":          _rank_for("session_shadow" if is_off else "session_stale"),
        })
        covered_user_ids.add(uid)

    incidents.sort(key=lambda i: (-i["rank"], i.get("deadline_in_s") or 1e9))
    return incidents[:limit]


async def _system_health(s: AsyncSession) -> dict[str, Any]:
    """SSE subscribers + watchdog flip rate + push success last hour."""
    out: dict[str, Any] = {}
    # SSE subscribers — broadcaster keeps them in-process.
    try:
        from app.services.event_broadcaster import broadcaster
        sub_count = sum(len(qs) for qs in broadcaster._subscribers.values())  # noqa: SLF001
        channel_count = len(broadcaster._subscribers)
        out["sse_subscribers"] = int(sub_count)
        out["sse_channels"]    = int(channel_count)
    except Exception as e:
        logger.debug(f"[risk_panel] sse rollup failed: {e}")
        out["sse_subscribers"] = None
        out["sse_channels"]    = None

    # Push reachability — % of tokens that succeeded last 24h vs total.
    try:
        row = (await s.execute(text(
            """
            SELECT
              COUNT(*)                                              AS total,
              COUNT(*) FILTER (WHERE consecutive_failures = 0)      AS healthy,
              COUNT(*) FILTER (WHERE consecutive_failures BETWEEN 1 AND 2) AS at_risk,
              COUNT(*) FILTER (WHERE consecutive_failures >= 3)     AS dead
            FROM push_tokens
            """
        ))).fetchone()
        total = int(row.total or 0)
        healthy = int(row.healthy or 0)
        out["push_tokens"] = {
            "total":    total,
            "healthy":  healthy,
            "at_risk":  int(row.at_risk or 0),
            "dead":     int(row.dead or 0),
            "health_pct": round((healthy / total) * 100, 1) if total else None,
        }
    except Exception as e:
        logger.debug(f"[risk_panel] push tokens rollup failed: {e}")
        out["push_tokens"] = None

    # Watchdog flips — in the last hour, how many sessions transitioned
    # to offline? Proxy: `last_seen_online_at` between (now-1h, now-30s).
    try:
        row = (await s.execute(text(
            """
            SELECT COUNT(*) AS flips
              FROM guardian_sessions
             WHERE is_offline = TRUE
               AND last_seen_online_at >= NOW() - INTERVAL '1 hour'
            """
        ))).fetchone()
        out["watchdog_flips_1h"] = int(row.flips or 0)
    except Exception as e:
        logger.debug(f"[risk_panel] watchdog rollup failed: {e}")
        out["watchdog_flips_1h"] = None

    return out


@router.get("/risk-panel")
async def risk_panel(
    incidents_limit: int = 25,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """Single answer to: 'what needs attention in the next 10 seconds?'

    Operator/admin only. Returns a 3-block payload designed for a
    docked Command Center tile that polls every 5s.

    Caching: 10s Redis TTL. Stale-by-10s is acceptable for a polled
    tile and turns the Neon-RTT cost (~2-3s per cold call) into a
    ~10ms cache hit on the polling cadence.
    """
    if user.role not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="Operator or admin only")

    cap = max(1, min(int(incidents_limit), 50))
    cache_ns = "risk_panel"
    cache_key = f"v1:{cap}"

    # Cache hit fast-path. Best-effort — Redis down → fail through.
    set_json = None
    try:
        from app.services.redis_service import get_json as _get_json, set_json as _set_json
        cached = _get_json(cache_ns, cache_key)
        if cached is not None:
            cached["_cache"] = "hit"
            return cached
        set_json = _set_json
    except Exception as e:
        logger.debug(f"[risk_panel] cache read skipped: {e}")

    summary = await _summary_counters(session)
    ttfh    = await _ttfh_block(session)
    inc     = await _incidents(session, limit=cap)
    sysh    = await _system_health(session)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary":      {**summary, "ttfh": ttfh},
        "incidents":    inc,
        "system":       sysh,
    }

    # Best-effort cache write.
    try:
        if set_json is not None:
            # 10s TTL: comfortably overlaps a 5s polling cadence even
            # under slow network conditions (each poll returns in 1-4s
            # from a remote DB; we want the next poll to still hit).
            # Stale-by-up-to-10s is fine for an operator panel — much
            # better than burning 4s of latency on every poll.
            set_json(cache_ns, cache_key, payload, ttl=10)
    except Exception:
        pass
    payload["_cache"] = "miss"
    return payload
