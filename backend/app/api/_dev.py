"""Dev/diagnostic endpoints — admin/operator-only.

Cheap, pasteable curl-introspection for systems we'd otherwise have to
tail logs to understand. Each handler is read-only and does NOT mutate
state. Intentionally sparse on auth granularity: roles `admin` and
`operator` are both allowed.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_db_session
from app.models.user import User
from app.services import risk_emitter, redis_service, ttfa_recorder, ttfa_state_stats
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/_dev", tags=["dev"])


def _require_admin_or_operator(user: User) -> None:
    """Soft role gate without bouncing through the dependency factory.
    Returns silently for admin/operator; otherwise 403.

    We allow `admin` OR `operator` because `_dev` endpoints are for
    on-call introspection and operators need them too."""
    user_roles: set[str] = set()
    if hasattr(user, "roles") and user.roles:
        rs = user.roles if isinstance(user.roles, list) else [user.roles]
        user_roles.update(str(r).lower() for r in rs)
    if hasattr(user, "role") and user.role:
        user_roles.add(str(user.role).lower())
    if not user_roles & {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="admin or operator role required")


@router.get("/risk-emitter/state")
async def risk_emitter_state(
    child_id: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    """Dump the current `risk_emitter` dedup state.

    Without `child_id` → returns a summary (counts only — never enumerates
    every child to keep the response O(1) at scale).
    With `child_id` → returns the per-child state (score, level, version,
    escalation tier, offline flag, version-counter from Redis).

    Why this exists: tuning predictive thresholds against real journeys
    means knowing exactly what the emitter saw last for a given child.
    Without this, every "is the threshold right?" question becomes a
    log-archaeology project.
    """
    _require_admin_or_operator(user)

    redis_up = redis_service.is_available()
    out = {
        "redis_available": redis_up,
        "score_delta_threshold": risk_emitter.SCORE_DELTA_THRESHOLD,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if child_id:
        cid = str(child_id)
        state = risk_emitter._get_state(cid)
        version_counter = None
        if redis_up:
            try:
                client = redis_service._get_client()
                if client is not None:
                    raw = client.get(risk_emitter._RS_VERSION_KEY.format(child_id=cid))
                    if raw is not None:
                        version_counter = int(raw)
            except Exception:
                version_counter = None
        out["child_id"] = cid
        out["state"] = (
            {
                "score":            state.score,
                "risk_level":       state.risk_level,
                "escalation_tier":  state.escalation_tier,
                "is_offline":       state.is_offline,
                "version":          state.version,
            }
            if state is not None else None
        )
        out["redis_version_counter"] = version_counter
        out["next_emit_key_would_be"] = (
            f"{cid}:{(version_counter or (state.version if state else 0)) + 1}"
        )
        return out

    # Summary mode — counts only, no per-child enumeration.
    local_count = len(risk_emitter._LOCAL_LAST_RISK)
    redis_state_count: Optional[int] = None
    redis_counter_count: Optional[int] = None
    if redis_up:
        try:
            client = redis_service._get_client()
            if client is not None:
                redis_state_count = sum(
                    1 for _ in client.scan_iter(match=f"nischint:{risk_emitter._RS_NS_STATE}:*")
                )
                redis_counter_count = sum(
                    1 for _ in client.scan_iter(match="nischint:risk:ver:*")
                )
        except Exception:
            redis_state_count = None
            redis_counter_count = None

    out["summary"] = {
        "local_state_entries":   local_count,
        "redis_state_entries":   redis_state_count,
        "redis_version_counters": redis_counter_count,
    }
    out["hint"] = "pass ?child_id=<uuid> to see a specific child's state"
    return out


@router.get("/alert-ttfa/stats")
async def alert_ttfa_stats(
    since: int = 3600,
    kind: Optional[str] = None,
    include_redis: bool = True,
    user: User = Depends(get_current_user),
):
    """Return Time-To-First-Alert percentile stats (NISCH-003).

    Query params:
        since:          time window in seconds (default 3600 = 1h, 0 = no cap)
        kind:           optional filter (`voice_distress`, `sos`, ...) —
                        the response always includes the full per-kind
                        breakdown; `kind` only adds a focused sub-block.
        include_redis:  also pull cross-instance samples from the Redis
                        mirror. Default true. Set false for a pod-only view.

    Why this exists: KRA target is **SOS → guardian push < 5s p95**. Without
    a real percentile read-out we can only assert "feels fast". This is the
    one curl-able answer to "are we hitting it?".

    Sample buffer: bounded ring (~1k local + ~4k Redis-mirrored). When the
    floor of `samples_considered` is < 20, treat percentiles as advisory.
    """
    _require_admin_or_operator(user)

    if since < 0:
        raise HTTPException(status_code=400, detail="`since` must be >= 0")
    if since > 30 * 24 * 3600:
        raise HTTPException(status_code=400, detail="`since` capped at 30 days")

    stats = ttfa_recorder.get_stats(
        since_s=int(since),
        kind=kind,
        include_redis=bool(include_redis),
    )
    stats["ts"] = datetime.now(timezone.utc).isoformat()
    if stats["samples_considered"] < 20:
        stats["confidence"] = "low"
        stats["hint"] = (
            "fewer than 20 samples in window — percentiles are advisory. "
            "Either widen `since` or wait for more alerts."
        )
    else:
        stats["confidence"] = "ok"
    return stats


@router.get("/ttfa/recent")
async def alert_ttfa_recent(
    n: int = 20,
    window_hours: int = 24,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the last `n` TTFA samples (NISCH-008d) plus per-state
    transition-latency percentiles (NISCH-006 Day 3+).

    Pure peek into the in-process ring buffer for the recent list, plus
    a query against `safety_incident_events` for durable per-state
    p50/p95. On-call can curl this directly when investigating an
    outage; the per-state stats are the *guardian responsiveness* KPI.

    `window_hours` controls the percentile window (default 24h, capped
    at 168h / 1 week to keep queries cheap).
    """
    _require_admin_or_operator(user)
    if n <= 0 or n > 200:
        raise HTTPException(status_code=400, detail="`n` must be between 1 and 200")
    if window_hours < 1 or window_hours > ttfa_state_stats.MAX_WINDOW_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f"`window_hours` must be between 1 and {ttfa_state_stats.MAX_WINDOW_HOURS}",
        )
    state_stats = await ttfa_state_stats.get_state_stats(
        session, window_hours=window_hours,
    )
    return {
        "ts":           datetime.now(timezone.utc).isoformat(),
        "count":        n,
        "events":       ttfa_recorder.get_recent_events(int(n)),
        "recent":       ttfa_recorder.get_recent_events(int(n)),  # alias per spec
        "state_stats":  state_stats,
        "window_hours": window_hours,
        "computed_at":  ttfa_state_stats.computed_at(),
    }


@router.get("/twilio/sla")
async def twilio_sla(
    since: int = 3600,
    user: User = Depends(get_current_user),
):
    """Single-decision SLA verdict for the Twilio escalation pipeline.

    Combines:
        - boot/runtime auth handshake (`twilio_health` semantics)
        - SMS p95 < 2000ms target (warning at 2000, fail at 5000)
        - Voice p95 < 4000ms target (warning at 4000, fail at 8000)
        - Success rate > 99% target (warning < 99%, fail < 95%)

    Returns:
        {
          "status":       "green" | "amber" | "red",
          "auth_ok":      bool,
          "sms_p95":      int,
          "voice_p95":    int,
          "success_rate": float,    # 0.0–1.0
          "since_s":      int,
          "samples":      {"sms": int, "voice": int},
          "thresholds":   {...},
          "reasons":      [str, ...],   # human-readable verdict drivers
          "ts":           "...iso..."
        }

    This is the curl-able summary an uptime monitor (Pingdom, UptimeRobot,
    StatusGator, BetterStack) should consume. Operators get a single
    🟢/🟠/🔴 decision instead of a percentile salad.
    """
    _require_admin_or_operator(user)

    if since < 60:
        raise HTTPException(status_code=400, detail="`since` must be >= 60 seconds")
    if since > 30 * 24 * 3600:
        raise HTTPException(status_code=400, detail="`since` capped at 30 days")

    # 1. Auth check — same path as `/twilio/health`.
    auth_ok = False
    auth_err: str | None = None
    twilio_configured = False
    try:
        from app.services import sms_service
        twilio_configured = bool(sms_service._twilio_client)
        if twilio_configured:
            sid_env = (sms_service.os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
            sms_service._twilio_client.api.accounts(sid_env).fetch()
            auth_ok = True
    except Exception as e:  # noqa: BLE001
        auth_err = f"{type(e).__name__}: {e}"

    # 2. Latency stats — pull `twilio:sms` + `twilio:voice` legs.
    stats = ttfa_recorder.get_stats(since_s=int(since), include_redis=True)
    sms_block   = stats["by_kind"].get("twilio:sms",   {"count": 0, "p95": 0})
    voice_block = stats["by_kind"].get("twilio:voice", {"count": 0, "p95": 0})

    # 3. Success rate — `priority="critical"` samples are successes;
    #    `priority="warning"` samples are GIVE_UP failures (per twilio_safe).
    total_attempts = 0
    total_failures = 0
    try:
        from app.services.ttfa_recorder import _BUFFER  # in-process slice
        cutoff = stats["now_ts"] - since
        for s in _BUFFER:
            kind = s.get("kind", "")
            if not kind.startswith("twilio:"):
                continue
            if float(s.get("ts", 0)) < cutoff:
                continue
            total_attempts += 1
            if s.get("priority") == "warning":
                total_failures += 1
    except Exception:
        pass
    success_rate = (
        round(1.0 - (total_failures / total_attempts), 4)
        if total_attempts > 0 else 1.0
    )

    THRESHOLDS = {
        "sms_p95_warn_ms":    2000,
        "sms_p95_fail_ms":    5000,
        "voice_p95_warn_ms":  4000,
        "voice_p95_fail_ms":  8000,
        "success_rate_warn":  0.99,
        "success_rate_fail":  0.95,
        "min_samples_for_confidence": 5,
    }

    reasons: list[str] = []
    status = "green"

    if not twilio_configured:
        status = "red"
        reasons.append("twilio_not_configured")
    if not auth_ok:
        status = "red"
        reasons.append(f"auth_failed: {auth_err or 'unknown'}")

    sms_count = int(sms_block.get("count", 0))
    voice_count = int(voice_block.get("count", 0))
    if sms_count + voice_count < THRESHOLDS["min_samples_for_confidence"]:
        if status == "green":
            status = "amber"
            reasons.append(f"low_sample_volume:{sms_count + voice_count}")

    sms_p95 = int(sms_block.get("p95", 0))
    if sms_count >= 1:
        if sms_p95 >= THRESHOLDS["sms_p95_fail_ms"]:
            status = "red"
            reasons.append(f"sms_p95_above_fail:{sms_p95}ms")
        elif sms_p95 >= THRESHOLDS["sms_p95_warn_ms"]:
            if status == "green":
                status = "amber"
            reasons.append(f"sms_p95_above_warn:{sms_p95}ms")

    voice_p95 = int(voice_block.get("p95", 0))
    if voice_count >= 1:
        if voice_p95 >= THRESHOLDS["voice_p95_fail_ms"]:
            status = "red"
            reasons.append(f"voice_p95_above_fail:{voice_p95}ms")
        elif voice_p95 >= THRESHOLDS["voice_p95_warn_ms"]:
            if status == "green":
                status = "amber"
            reasons.append(f"voice_p95_above_warn:{voice_p95}ms")

    if total_attempts >= THRESHOLDS["min_samples_for_confidence"]:
        if success_rate < THRESHOLDS["success_rate_fail"]:
            status = "red"
            reasons.append(f"success_rate_below_fail:{success_rate:.4f}")
        elif success_rate < THRESHOLDS["success_rate_warn"]:
            if status == "green":
                status = "amber"
            reasons.append(f"success_rate_below_warn:{success_rate:.4f}")

    if not reasons:
        reasons.append("all_within_thresholds")

    return {
        "status":       status,
        "auth_ok":      auth_ok,
        "sms_p95":      sms_p95,
        "voice_p95":    voice_p95,
        "success_rate": success_rate,
        "since_s":      int(since),
        "samples": {
            "sms":              sms_count,
            "voice":            voice_count,
            "local_attempts":   total_attempts,
            "local_failures":   total_failures,
        },
        "thresholds":   THRESHOLDS,
        "reasons":      reasons,
        "ts":           datetime.now(timezone.utc).isoformat(),
    }


@router.get("/twilio/health")
async def twilio_health(user: User = Depends(get_current_user)):
    """On-demand Twilio auth handshake (NISCH-008).

    Hits `accounts.fetch()` which requires the auth token to be valid.
    Returns the account state without exposing any secret material.

    This is the single source of truth operators should curl after
    rotating credentials. Boot-time logs may be stale if the .env was
    edited but supervisor hasn't been restarted.
    """
    _require_admin_or_operator(user)

    out: dict = {
        "ts":        datetime.now(timezone.utc).isoformat(),
        "configured": False,
        "auth_ok":   False,
        "from":      None,
        "account":   None,
        "error":     None,
    }
    try:
        from app.services import sms_service
        out["configured"] = bool(sms_service._twilio_client)
        out["from"] = sms_service._twilio_from
        if not out["configured"]:
            out["error"] = "Twilio client not initialized (credentials missing or import failed)"
            return out
        sid_env = (sms_service.os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
        acc = sms_service._twilio_client.api.accounts(sid_env).fetch()
        out["auth_ok"] = True
        out["account"] = {
            "name":   acc.friendly_name,
            "status": acc.status,
            "type":   acc.type,
        }
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
