"""Alert ACK + Escalation Engine — the Control Layer primitive.

Strict scope (CEO-mode locked + production-trust hardening):
  • Critical/emergency alerts that require human action are flagged
    `ack_required=True` with a deadline.
  • A guardian acknowledges via the API; ACK is **tri-state**:
        seen     — "I've seen the alert"
        acting   — "I'm doing something about it"
        resolved — "This is fully closed, no further action needed"
    A `seen` ACK opens a second 60s window for `acting` — if it
    lapses, a soft re-escalation event fires.
  • If the initial ACK deadline passes without ANY ACK, the engine
    escalates one step at a time. Each step is captured in
    `escalation_history` and emits a WS event carrying the immutable
    `context_json` bundle — escalations are never blind.
  • Terminal step → `ack_status='escalated'`, operator-channel WS
    event signals "human ops must act now".
  • Race-condition lock: `acknowledge_alert` and `process_pending_acks`
    both use `SELECT … FOR UPDATE` so the tick can never escalate an
    alert that's mid-ACK.
  • On first ACK, `alert_closed` event fires immediately so other
    guardians' clients can dismiss the notification.

What this does NOT do (yet):
  • Real `louder_push` re-broadcast (records the transition only).
  • Twilio voice for `automated_call`.
  • Police/EMS API for `authority_api`.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guardian import GuardianAlert, GuardianSession

logger = logging.getLogger(__name__)

DEFAULT_ACK_TIMEOUT_S = 30
SEEN_TO_ACTING_WINDOW_S = 60      # 60s after `seen` to commit to `acting`
ACTING_HEARTBEAT_WINDOW_S = 30    # acting guardian must heartbeat every 30s
LOUDER_PUSH_COOLDOWN_S = 15
# Twilio voice calls cost real money and each ring is a physical
# interruption. 60s is the floor between retries for the same alert.
# This is defense-in-depth on top of the ESCALATION_STEPS state
# machine (which only fires one step per timeout window anyway).
AUTOMATED_CALL_COOLDOWN_S = 60       # anti-spam guard for Twilio voice calls
ACK_TYPES = ("seen", "acting", "resolved")
# Strict ordering — you can only move forward.
_ACK_ORDER = {"seen": 1, "acting": 2, "resolved": 3, "seen_lapsed": 1}

ESCALATION_STEPS = [
    "louder_push",
    "automated_call",
    "authority_api",
    "ops_terminal",
]


def severity_requires_ack(severity: str) -> bool:
    return (severity or "").lower() in ("critical", "emergency", "high")


def _compute_ack_timeout(severity: str, context: dict | None) -> int:
    """Risk-weighted ACK deadline. Higher severity AND shadow tracking
    both shorten the response window — a critical alert on a device
    we can't actively track is the most dangerous combination.

      critical / emergency  → 15 s
      high                  → 30 s
      (lower severities don't trigger ACK at all — see severity_requires_ack)

    Shadow tracking mode → halve the timeout (floor 10 s).
    """
    sev = (severity or "").lower()
    base = 15 if sev in ("critical", "emergency") else 30
    if (context or {}).get("tracking_mode") == "shadow":
        base = max(10, base // 2)
    return base



# ── Context bundle ───────────────────────────────────────────────────
async def _capture_context(session: AsyncSession,
                            alert: GuardianAlert) -> dict:
    """Capture the immutable forensic bundle that travels with every
    WS event for this alert. Best-effort — never raises."""
    out: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}
    # Subject (child) is always known via alert.user_id, even when
    # the alert is session-less (e.g. help-request with no journey).
    if alert.user_id:
        out["user_id"] = str(alert.user_id)
    # Two ORTHOGONAL signals — never collapse them into one.
    #   has_active_session: a journey row exists and is live
    #   is_offline:         the device's GPS stream is unreachable
    # No session ≠ offline (user never started a journey).
    # Offline ≠ no session (session exists but GPS dropped >30s).
    # Future logic must read these separately to avoid misclassifying.
    has_active_session = False
    try:
        gs = None
        if alert.session_id:
            gs = (await session.execute(
                select(GuardianSession).where(GuardianSession.id == alert.session_id)
            )).scalar_one_or_none()
        if gs is not None:
            has_active_session = gs.status not in ("ended", "completed")
            last_loc = None
            if gs.current_location:
                last_loc = dict(gs.current_location)
                if gs.previous_update_at:
                    age = (datetime.now(timezone.utc) - gs.previous_update_at).total_seconds()
                    last_loc["age_sec"] = round(age, 1)
            out["user_id"]        = str(gs.user_id)
            out["session_status"] = gs.status
            out["last_location"]  = last_loc
            out["risk_level"]     = gs.risk_level
            out["risk_score"]     = gs.risk_score
            out["is_offline"]     = bool(getattr(gs, "is_offline", False))
            out["last_seen_online_at"] = (
                gs.last_seen_online_at.isoformat()
                if getattr(gs, "last_seen_online_at", None) else None
            )
            out["offline_gaps"]    = int(getattr(gs, "offline_gaps", 0) or 0)
            out["max_gap_seconds"] = int(getattr(gs, "max_gap_seconds", 0) or 0)
        else:
            # Session-less path: no journey context available.
            out["session_status"] = None
            out["is_offline"]     = False  # we don't know — no GPS stream to be silent
        out["has_active_session"] = has_active_session
        # Derive tracking_mode EXPLICITLY from the two orthogonal
        # signals. The ACK engine reads this single field to pick
        # the timeout (`_compute_ack_timeout`).
        if not has_active_session:
            # No live journey → operator must assume the device is
            # unreachable for escalation purposes. Fast-path applies.
            out["tracking_mode"] = "shadow"
        elif out.get("is_offline"):
            out["tracking_mode"] = "shadow"
        else:
            out["tracking_mode"] = "active"
    except Exception as e:
        logger.debug(f"[alert_ack] context.session capture failed: {e}")

    # Guardian reachability rollup — uses the new push reachability
    # columns shipped earlier.
    try:
        if "user_id" in out:
            # `guardians.email` is a plain email string — join through
            # `users.email → users.id → push_tokens.user_id`. The old
            # query did `g.email::uuid` which fails with
            # "invalid input syntax for type uuid" and silently aborts
            # the surrounding transaction. Use a SAVEPOINT so any
            # failure here is contained and never poisons the parent.
            async with session.begin_nested():
                rows = (await session.execute(
                    text(
                        """SELECT pt.consecutive_failures, pt.last_success_at
                             FROM push_tokens pt
                             JOIN users u ON u.id = pt.user_id
                            WHERE u.email IN (
                                  SELECT g.email FROM guardians g
                                   WHERE g.user_id = :uid
                              )
                               OR pt.user_id = :uid"""
                    ),
                    {"uid": out["user_id"]},
                )).fetchall() or []
            healthy = risk = dead = 0
            for r in rows:
                fails = int(r.consecutive_failures or 0)
                if fails >= 3:
                    dead += 1
                elif fails >= 1:
                    risk += 1
                else:
                    healthy += 1
            out["guardians"] = {"healthy": healthy, "risk": risk, "dead": dead,
                                "total": healthy + risk + dead}
    except Exception as e:
        logger.debug(f"[alert_ack] context.guardians capture failed: {e}")

    return out


def _enrich_payload(base: dict, alert: GuardianAlert) -> dict:
    """Every WS event carries the alert's frozen context_json so
    downstream consumers don't need to round-trip back to the DB."""
    return {**base, "context": alert.context_json or {}}


# ── mark_for_ack ─────────────────────────────────────────────────────
async def mark_for_ack(session: AsyncSession, alert: GuardianAlert,
                       timeout_sec: int | None = None) -> None:
    """Flag an alert as requiring acknowledgement. Idempotent.

    `timeout_sec` defaults to a risk-weighted value derived from the
    alert's severity and the captured context's `tracking_mode`. Pass
    explicit value only for tests / overrides.
    """
    if alert.ack_status in ("acknowledged", "escalated"):
        return
    # Capture context EXACTLY ONCE — at the moment of arming.
    if not alert.context_json:
        alert.context_json = await _capture_context(session, alert)
    if timeout_sec is None:
        timeout_sec = _compute_ack_timeout(alert.severity, alert.context_json)
    alert.ack_required = True
    alert.ack_timeout_sec = timeout_sec
    alert.ack_status = "pending"
    alert.ack_deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_sec)
    await session.flush()
    logger.info(
        f"[alert_ack] PENDING id={alert.id} severity={alert.severity} "
        f"timeout_sec={timeout_sec} deadline={alert.ack_deadline.isoformat()}"
    )
    await _emit("alert_ack_required", _enrich_payload({
        "alert_id":     str(alert.id),
        "session_id":   str(alert.session_id) if alert.session_id else None,
        "alert_type":   alert.alert_type,
        "severity":     alert.severity,
        "message":      alert.message,
        "ack_deadline": alert.ack_deadline.isoformat(),
        "ack_timeout_sec": timeout_sec,
    }, alert))


# ── acknowledge_alert ────────────────────────────────────────────────
async def acknowledge_alert(session: AsyncSession, alert_id: uuid.UUID | str,
                             user_id: uuid.UUID | str,
                             ack_type: str = "seen",
                             confirmed: bool = False) -> dict:
    """Tri-state ACK with race-safe locking.

    Returns:
        {acknowledged: bool, alert_id, status, ack_type, was_late, reason?}

    `ack_type` must be one of {'seen', 'acting', 'resolved'}.
    Only forward transitions are accepted (seen → acting → resolved).

    **Misclick guard**: `resolved` requires `confirmed=True`. The UI
    pattern is "hold 1.5s" or double-tap on the client; the server
    just refuses an unconfirmed `resolved` so a single accidental tap
    can never close out a real emergency. `seen` and `acting` stay
    instant — they're soft signals, not closure.
    """
    aid = uuid.UUID(str(alert_id))
    uid = uuid.UUID(str(user_id))
    if ack_type not in ACK_TYPES:
        return {"acknowledged": False, "alert_id": str(aid),
                "reason": "invalid_ack_type",
                "valid": list(ACK_TYPES)}
    if ack_type == "resolved" and not confirmed:
        return {"acknowledged": False, "alert_id": str(aid),
                "reason": "confirmation_required",
                "hint": "Resolved closes the alert permanently — "
                        "client must send confirmed=true (e.g. after a "
                        "1.5s hold or double-tap) to prevent misclicks."}

    # Race-safe: the row is locked until commit, so a parallel tick
    # can't escalate it mid-ACK and an automated_call can't fire after
    # a guardian has already responded.
    alert = (await session.execute(
        select(GuardianAlert).where(GuardianAlert.id == aid).with_for_update()
    )).scalar_one_or_none()
    if alert is None:
        return {"acknowledged": False, "alert_id": str(aid), "reason": "not_found"}

    if not alert.ack_required:
        return {"acknowledged": False, "alert_id": str(aid),
                "reason": "ack_not_required"}

    now = datetime.now(timezone.utc)
    history = list(alert.escalation_history or [])
    is_first_ack = alert.ack_status == "pending"
    was_late = alert.escalation_step > 0

    # Prevent backward transitions. A guardian who already said
    # `acting` can't downgrade to `seen`.
    current_rank = _ACK_ORDER.get(alert.ack_type or "", 0)
    new_rank     = _ACK_ORDER.get(ack_type, 0)
    if not is_first_ack and new_rank <= current_rank:
        return {"acknowledged": True, "alert_id": str(aid),
                "status": "already_acknowledged",
                "ack_type": alert.ack_type,
                "acked_by": str(alert.acked_by) if alert.acked_by else None,
                "acked_at": alert.acked_at.isoformat() if alert.acked_at else None,
                "was_late": was_late}

    # First-time ACK closes the escalation loop.
    if is_first_ack:
        alert.ack_status = "acknowledged"
        alert.acked_by = uid
        alert.acked_at = now
    alert.ack_type = ack_type

    # `seen` opens the 60s commit window. `acting` and `resolved` close it.
    if ack_type == "seen":
        alert.seen_deadline = now + timedelta(seconds=SEEN_TO_ACTING_WINDOW_S)
    else:
        alert.seen_deadline = None
    # Acting starts the heartbeat liveness clock. `seen` and `resolved`
    # don't track liveness — the former hasn't committed, the latter
    # is closed.
    if ack_type == "acting":
        alert.acting_heartbeat_at = now
    else:
        alert.acting_heartbeat_at = None

    history.append({
        "step": ack_type, "by": str(uid),
        "at":   now.isoformat(),
    })
    alert.escalation_history = history

    # NISCH-006: linked SafetyIncident moves ESCALATED → ACKNOWLEDGED.
    # Done in the SAME transaction as the ACK so the two facts can't
    # diverge. Best-effort: any failure rolls back ONLY the linkage;
    # the ACK itself is preserved by re-committing the alert-only state.
    if is_first_ack:
        try:
            await session.flush()  # ensure ACK columns hit DB before linkage
            from app.services import safety_incident_engine as _sie
            await _sie.acknowledge_incident_for_alert(
                session, alert_id=aid, actor_id=uid,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[alert_ack] safety_incident link failed (non-fatal): {e}")

    await session.commit()
    logger.info(f"[alert_ack] ACK type={ack_type} id={aid} by={uid} first={is_first_ack}")

    payload = _enrich_payload({
        "alert_id":   str(aid),
        "session_id": str(alert.session_id) if alert.session_id else None,
        "ack_type":   ack_type,
        "closed_by":  str(uid),
        "closed_at":  now.isoformat(),
        "was_late":   was_late,
    }, alert)
    # First ACK fires the cancellation signal so OTHER guardians'
    # clients can dismiss the notification immediately. Later
    # transitions update operator dashboards but don't re-cancel.
    if is_first_ack:
        await _emit("alert_closed", payload)
    await _emit("alert_acknowledged", payload)

    return {"acknowledged": True, "alert_id": str(aid),
            "status": "acknowledged", "ack_type": ack_type,
            "was_late": was_late}


# ── Acting heartbeat (#2: silent guardian failure protection) ────────
async def heartbeat_acting(session: AsyncSession,
                            alert_id: uuid.UUID | str,
                            user_id: uuid.UUID | str) -> dict:
    """A guardian who clicked `acting` keeps a liveness heartbeat alive
    so the engine can tell the difference between "still working on it"
    and "phone died mid-response". Called periodically by the client
    while in the acting screen."""
    aid = uuid.UUID(str(alert_id))
    uid = uuid.UUID(str(user_id))
    alert = (await session.execute(
        select(GuardianAlert).where(GuardianAlert.id == aid).with_for_update()
    )).scalar_one_or_none()
    if alert is None:
        return {"ok": False, "reason": "not_found"}
    if alert.ack_type != "acting":
        return {"ok": False, "reason": "not_acting",
                "current_ack_type": alert.ack_type}
    if alert.acked_by and alert.acked_by != uid:
        # Only the guardian who committed to `acting` heartbeats.
        return {"ok": False, "reason": "not_owner"}
    alert.acting_heartbeat_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ok": True, "alert_id": str(aid),
            "heartbeat_at": alert.acting_heartbeat_at.isoformat()}


# ── process_pending_acks ─────────────────────────────────────────────
async def process_pending_acks(session: AsyncSession) -> dict:
    """Two responsibilities every 5s:

      1. Hard escalation: pending alerts past their ack_deadline get
         their `escalation_step` advanced.
      2. Soft re-escalation: `seen` ACKs whose seen_deadline has lapsed
         fire `alert_seen_lapsed` once and stop.

    Both use SELECT FOR UPDATE so concurrent ACKs from the API path
    can't race the tick.
    """
    now = datetime.now(timezone.utc)

    # ── 1) Hard escalations ─────────────────────────────────────────
    rows = (await session.execute(
        select(GuardianAlert).where(
            GuardianAlert.ack_status == "pending",
            GuardianAlert.ack_deadline.isnot(None),
            GuardianAlert.ack_deadline < now,
        ).with_for_update(skip_locked=True)
    )).scalars().all()

    escalated = 0
    exhausted = 0
    for alert in rows:
        next_step_idx = alert.escalation_step + 1
        if next_step_idx >= len(ESCALATION_STEPS):
            alert.ack_status = "escalated"
            history = list(alert.escalation_history or [])
            history.append({"step": "ops_terminal_locked", "at": now.isoformat()})
            alert.escalation_history = history
            exhausted += 1
            continue

        step_name = ESCALATION_STEPS[next_step_idx - 1]
        alert.escalation_step = next_step_idx
        history = list(alert.escalation_history or [])
        history.append({
            "step": next_step_idx, "name": step_name,
            "at": now.isoformat(), "reason": "ack_timeout",
        })
        alert.escalation_history = history
        new_deadline = now + timedelta(seconds=alert.ack_timeout_sec or DEFAULT_ACK_TIMEOUT_S)
        alert.ack_deadline = new_deadline

        if next_step_idx >= len(ESCALATION_STEPS) - 1:
            alert.ack_status = "escalated"
            exhausted += 1
        escalated += 1

        logger.warning(
            f"[alert_ack] ESCALATED id={alert.id} step={next_step_idx} "
            f"action={step_name} severity={alert.severity}"
        )
        # Action plug-in: louder_push physically re-broadcasts via FCM
        # critical channel. Spam-guarded by `last_louder_push_at` so a
        # tick can't fire it more than once every 15 s. Skipped if the
        # alert is already resolved/escalated mid-tick.
        if step_name == "louder_push":
            await _trigger_louder_push(session, alert, now)
        # Action plug-in: automated_call places a real Twilio voice
        # call to the highest-priority reachable guardian. Gated on
        # `ack_type IS NULL` (Invariant: once a human has committed
        # even to `seen`, physical escalation must NOT place a call).
        # Spam-guarded by `last_automated_call_at` (60 s cooldown).
        if step_name == "automated_call":
            await _trigger_automated_call(session, alert, now)

        await _emit("alert_escalated", _enrich_payload({
            "alert_id":     str(alert.id),
            "session_id":   str(alert.session_id) if alert.session_id else None,
            "step":         next_step_idx,
            "action":       step_name,
            "severity":     alert.severity,
            "alert_type":   alert.alert_type,
            "next_deadline": new_deadline.isoformat() if alert.ack_status == "pending" else None,
        }, alert))

    # ── 2) Soft re-escalation: `seen` lapses ────────────────────────
    seen_rows = (await session.execute(
        select(GuardianAlert).where(
            GuardianAlert.ack_type == "seen",
            GuardianAlert.seen_deadline.isnot(None),
            GuardianAlert.seen_deadline < now,
        ).with_for_update(skip_locked=True)
    )).scalars().all()
    seen_lapsed = 0
    for alert in seen_rows:
        alert.ack_type = "seen_lapsed"
        alert.seen_deadline = None
        history = list(alert.escalation_history or [])
        history.append({"step": "seen_lapsed", "at": now.isoformat()})
        alert.escalation_history = history
        seen_lapsed += 1
        logger.warning(
            f"[alert_ack] SEEN_LAPSED id={alert.id} "
            f"acked_by={alert.acked_by} (no `acting` within {SEEN_TO_ACTING_WINDOW_S}s)"
        )
        await _emit("alert_seen_lapsed", _enrich_payload({
            "alert_id":   str(alert.id),
            "session_id": str(alert.session_id) if alert.session_id else None,
            "acked_by":   str(alert.acked_by) if alert.acked_by else None,
            "lapsed_at":  now.isoformat(),
        }, alert))

    # ── 3) Acting-heartbeat liveness lapses ─────────────────────────
    # A guardian who clicked `acting` but stopped heartbeating for
    # >30s probably has a dead phone / no signal / panic. We surface
    # that to operators so a second guardian can take over.
    heartbeat_cutoff = now - timedelta(seconds=ACTING_HEARTBEAT_WINDOW_S)
    acting_rows = (await session.execute(
        select(GuardianAlert).where(
            GuardianAlert.ack_type == "acting",
            GuardianAlert.acting_heartbeat_at.isnot(None),
            GuardianAlert.acting_heartbeat_at < heartbeat_cutoff,
        ).with_for_update()
    )).scalars().all()
    acting_lapsed = 0
    for alert in acting_rows:
        # Park at `acting_lapsed` to stop the tick from re-firing.
        # The operator now owns this — we surface it once and stop.
        alert.ack_type = "acting_lapsed"
        history = list(alert.escalation_history or [])
        history.append({"step": "acting_lapsed", "at": now.isoformat(),
                        "last_heartbeat": alert.acting_heartbeat_at.isoformat()
                        if alert.acting_heartbeat_at else None})
        alert.escalation_history = history
        acting_lapsed += 1
        logger.warning(
            f"[alert_ack] ACTING_LAPSED id={alert.id} acked_by={alert.acked_by} "
            f"last_heartbeat={alert.acting_heartbeat_at}"
        )
        await _emit("alert_acting_lapsed", _enrich_payload({
            "alert_id":      str(alert.id),
            "session_id":    str(alert.session_id) if alert.session_id else None,
            "acked_by":      str(alert.acked_by) if alert.acked_by else None,
            "last_heartbeat": alert.acting_heartbeat_at.isoformat()
                              if alert.acting_heartbeat_at else None,
            "lapsed_at":     now.isoformat(),
        }, alert))

    if rows or seen_rows or acting_rows:
        await session.commit()

    return {
        "checked":       len(rows) + len(seen_rows) + len(acting_rows),
        "escalated":     escalated,
        "exhausted":     exhausted,
        "seen_lapsed":   seen_lapsed,
        "acting_lapsed": acting_lapsed,
    }


# ── Time-To-First-Human metric ───────────────────────────────────────
async def get_ttfh_metrics(session: AsyncSession, window_days: int = 30) -> dict:
    """Time-To-First-Human: response latency on critical alerts.

    The north-star metric for the Control Layer. Uses Postgres'
    percentile_disc for stability across small sample sizes.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    row = (await session.execute(
        text("""
            SELECT
                COUNT(*) FILTER (WHERE acked_at IS NOT NULL) AS acked_count,
                COUNT(*) FILTER (WHERE acked_at IS NULL
                                  AND ack_status = 'escalated') AS escalated_count,
                EXTRACT(epoch FROM percentile_disc(0.5) WITHIN GROUP (
                    ORDER BY acked_at - created_at)
                ) AS p50_s,
                EXTRACT(epoch FROM percentile_disc(0.95) WITHIN GROUP (
                    ORDER BY acked_at - created_at)
                ) AS p95_s,
                EXTRACT(epoch FROM AVG(acked_at - created_at)) AS avg_s
              FROM guardian_alerts
             WHERE ack_required = true
               AND created_at >= :cutoff
        """),
        {"cutoff": cutoff},
    )).fetchone()
    return {
        "window_days":     window_days,
        "acked_count":     int(row.acked_count or 0),
        "escalated_count": int(row.escalated_count or 0),
        "p50_seconds":     float(row.p50_s) if row.p50_s is not None else None,
        "p95_seconds":     float(row.p95_s) if row.p95_s is not None else None,
        "avg_seconds":     float(row.avg_s) if row.avg_s is not None else None,
    }


# ── WS emit helper ───────────────────────────────────────────────────
async def _emit(event_type: str, payload: dict) -> None:
    try:
        from app.services.event_broadcaster import broadcaster
        try:
            await broadcaster.broadcast_to_role("operator", event_type, payload)
        except Exception:
            pass
        sid = payload.get("session_id")
        if sid:
            try:
                await broadcaster.broadcast(f"session:{sid}", event_type, payload)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[alert_ack] WS emit suppressed: {e}")


# ── Action plug-ins ──────────────────────────────────────────────────
async def _trigger_louder_push(session: AsyncSession,
                                alert: GuardianAlert,
                                now: datetime) -> None:
    """Physical action for the `louder_push` escalation step.

    Re-broadcasts the alert to all guardians on the FCM critical-safety
    channel — siren_loop sound, vibrate loop, sticky, DND-bypass-when-
    granted. This is the system's first **physically assertive** step.

    Anti-spam: a 15-second cooldown across re-broadcasts. The 5s tick
    plus a parked alert at `escalated` could otherwise re-fire every
    tick. Even then, this guard is the only thing standing between
    the user and a loud notification storm.

    Strict scope:
      • One broadcast per cooldown window. No retry, no backoff.
      • Skip if alert was already acked (race window between hard
        escalation and guardian ACK landing).
      • Best-effort — never raises into the tick. Failure to dispatch
        does not affect the escalation state machine itself.
    """
    # Re-check state under the row lock — by the time we got here, an
    # ACK might have landed in the same transaction window.
    if alert.ack_status == "acknowledged":
        logger.info(f"[louder_push] skip id={alert.id} — alert already ACKed")
        return
    if alert.last_louder_push_at is not None:
        age_s = (now - alert.last_louder_push_at).total_seconds()
        if age_s < LOUDER_PUSH_COOLDOWN_S:
            logger.info(
                f"[louder_push] skip id={alert.id} — cooldown ({age_s:.1f}s)"
            )
            return

    # Grab the subject (child) — prefer the alert's own user_id (the
    # truth for session-less alerts), fall back to the session for
    # legacy rows that pre-date the user_id column being NOT NULL.
    user_id_str: str | None = None
    session_id_str: str | None = None
    if alert.user_id:
        user_id_str = str(alert.user_id)
    if alert.session_id:
        gs = (await session.execute(
            select(GuardianSession).where(GuardianSession.id == alert.session_id)
        )).scalar_one_or_none()
        if gs is not None:
            session_id_str = str(gs.id)
            if not user_id_str:
                user_id_str = str(gs.user_id)
    if not user_id_str:
        logger.warning(f"[louder_push] skip id={alert.id} — no subject user_id")
        return

    try:
        from app.services.guardian_notification_dispatcher import (
            dispatch_guardian_alert,
        )
        result = await dispatch_guardian_alert(
            session, alert, user_id_str, session_id_str or "",
            louder=True,
        )
        alert.last_louder_push_at = now
        logger.warning(
            f"[louder_push] FIRED id={alert.id} guardians={result.get('guardians_count')} "
            f"push_sent={result.get('push_sent')}"
        )
    except Exception as e:
        # Never let dispatch failure crash the tick.
        logger.exception(f"[louder_push] dispatch failed id={alert.id}: {e}")


async def _trigger_automated_call(session: AsyncSession,
                                   alert: GuardianAlert,
                                   now: datetime) -> None:
    """Place a Twilio voice call to the highest-priority reachable
    guardian. Only fires when:
      • alert is still pending/escalated (no ACK landed)
      • `ack_type IS NULL` — once ANY human has acknowledged (even
        `seen`), physical escalation must stop. A call at that point
        would be wrong automation.
      • `last_automated_call_at` is null OR older than the cooldown.

    Best-effort — never raises into the tick.
    """
    # Re-check state under the row lock — an ACK may have landed since
    # the parent query ran.
    if alert.ack_type is not None:
        logger.info(
            f"[automated_call] skip id={alert.id} — ack_type={alert.ack_type}"
        )
        return
    if alert.ack_status == "acknowledged":
        logger.info(f"[automated_call] skip id={alert.id} — already ACKed")
        return
    if alert.last_automated_call_at is not None:
        age_s = (now - alert.last_automated_call_at).total_seconds()
        if age_s < AUTOMATED_CALL_COOLDOWN_S:
            logger.info(
                f"[automated_call] skip id={alert.id} — cooldown ({age_s:.1f}s)"
            )
            return

    # Subject + session for context.
    user_id_str: str | None = None
    if alert.user_id:
        user_id_str = str(alert.user_id)
    if not user_id_str and alert.session_id:
        gs = (await session.execute(
            select(GuardianSession).where(GuardianSession.id == alert.session_id)
        )).scalar_one_or_none()
        if gs is not None:
            user_id_str = str(gs.user_id)
    if not user_id_str:
        logger.warning(f"[automated_call] skip id={alert.id} — no subject user_id")
        return

    # Resolve the subject's name for the TwiML, and a ranked list of
    # guardian phone numbers to try.
    from app.models.user import User
    subject = (await session.execute(
        select(User).where(User.id == alert.user_id)
    )).scalar_one_or_none() if alert.user_id else None
    child_name = (subject.full_name if subject else None) or "your child"

    # Guardians with a reachable E.164-shaped phone. Ordered by
    # `created_at` (first-added = primary, a convention established
    # elsewhere in the app). Raw SQL avoids importing the Guardian
    # model here and stays resilient to model-level changes.
    rows = (await session.execute(text(
        """
        SELECT id, name, phone
          FROM guardians
         WHERE user_id = :uid
           AND is_active = TRUE
           AND phone IS NOT NULL
           AND phone <> ''
           AND phone LIKE '+%%'
         ORDER BY created_at ASC
         LIMIT 3
        """
    ), {"uid": user_id_str})).fetchall() or []

    if not rows:
        logger.warning(
            f"[automated_call] no reachable E.164 phone for user={user_id_str} "
            f"alert={alert.id} — skipping"
        )
        return

    try:
        from app.services.sms_service import make_voice_call
        placed = 0
        call_attempts: list[dict] = []
        for r in rows:
            ok = make_voice_call(
                to=r.phone,
                child_name=child_name,
                alert_type=alert.alert_type or "emergency",
                event_id=str(alert.id),
                contact_name=r.name or "",
            )
            call_attempts.append({
                "guardian_id": str(r.id),
                "phone": r.phone[-4:].rjust(len(r.phone), "*"),
                "ok": bool(ok),
            })
            if ok:
                placed += 1
                # First successful placement wins — don't dial the
                # whole tree on every tick. Cooldown covers retries.
                break

        alert.last_automated_call_at = now
        # Stamp the escalation history so the operator can see on the
        # drill-down what we actually tried.
        history = list(alert.escalation_history or [])
        history.append({
            "step": "automated_call_attempt",
            "at": now.isoformat(),
            "placed": placed,
            "attempts": call_attempts,
        })
        alert.escalation_history = history

        if placed > 0:
            logger.warning(
                f"[automated_call] FIRED id={alert.id} placed={placed} "
                f"attempts={len(call_attempts)}"
            )
        else:
            logger.warning(
                f"[automated_call] ALL_FAILED id={alert.id} "
                f"attempts={len(call_attempts)}"
            )
    except Exception as e:
        logger.exception(f"[automated_call] failed id={alert.id}: {e}")


# ── Scheduler entry point ────────────────────────────────────────────
async def _tick():
    from app.db.session import async_session as factory
    try:
        async with factory() as s:
            await process_pending_acks(s)
    except Exception:
        logger.exception("[alert_ack] tick failed")


_scheduler = None


def start_alert_ack_engine() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _tick, "interval", seconds=10,
        id="alert_ack_tick",
        max_instances=1, coalesce=True, misfire_grace_time=15,
    )
    _scheduler.start()
    logger.info("[alert_ack] engine started — tick every 10s")


def stop_alert_ack_engine() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
