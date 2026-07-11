# Push Token Router
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.deps import get_db_session, get_current_user
from app.core.rbac import require_role
from app.models.user import User

router = APIRouter(prefix="/push", tags=["push"])


class PushTokenRequest(BaseModel):
    token: str


@router.post("/token", status_code=status.HTTP_201_CREATED)
async def register_push_token(
    body: PushTokenRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Register an FCM push token for the current user."""
    await session.execute(
        text(
            "INSERT INTO push_tokens (user_id, token) VALUES (:uid, :tok) "
            "ON CONFLICT (user_id, token) DO NOTHING"
        ),
        {"uid": current_user.id, "tok": body.token},
    )
    await session.commit()
    return {"status": "registered"}


# ── Reachability classifier ──────────────────────────────────────────
# Decay rule: success without follow-up for 24h is no longer evidence
# of a healthy device — the user could have uninstalled, the phone
# could be dead. We downgrade a stale `last_success_at` to `unknown`
# rather than `risk` because we have NO failure signal — we just
# don't know.
HEALTHY_WINDOW_S = 3600          # 🟢 success within last hour
SUCCESS_DECAY_S  = 24 * 3600     # ⚪ healthy → unknown after 24h silence
DEAD_FAILURES    = 3             # 🔴 N consecutive failures = dead


def _classify(last_success_at, last_failure_at, consecutive_failures: int,
              now) -> str:
    """Map raw counters → operational status.
        🟢 healthy    last_success < 1h, no consecutive failures
        🟡 risk       success rate slipping (recent success + recent failure)
        🔴 dead       3+ consecutive failures (or only failures recorded)
        ⚪ unknown    no signal yet, OR success older than 24h with no
                      failure to confirm/deny health
    """
    if consecutive_failures >= DEAD_FAILURES:
        return "dead"
    if last_success_at is None and last_failure_at is None:
        return "unknown"
    if last_success_at is None:
        return "dead"
    age_s = (now - last_success_at).total_seconds()
    # Decay: a long-stale success without any failure to refute it is
    # ambiguous — don't pretend the device is still healthy.
    if age_s >= SUCCESS_DECAY_S and consecutive_failures == 0:
        return "unknown"
    if age_s < HEALTHY_WINDOW_S and consecutive_failures == 0:
        return "healthy"
    if consecutive_failures >= 1:
        return "risk"
    # Success between 1h and 24h, no failures → healthy still.
    return "healthy"


@router.get("/reachability/me")
async def my_push_reachability(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Reachability snapshot for the calling user's own tokens."""
    from datetime import datetime, timezone
    rows = (await session.execute(
        text("""SELECT token, last_success_at, last_failure_at,
                       consecutive_failures, last_failure_reason, created_at
                  FROM push_tokens WHERE user_id = :uid"""),
        {"uid": current_user.id},
    )).fetchall()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        status_ = _classify(r.last_success_at, r.last_failure_at,
                            int(r.consecutive_failures or 0), now)
        out.append({
            "token_suffix":          r.token[-8:],
            "status":                status_,
            "last_success_at":       r.last_success_at.isoformat() if r.last_success_at else None,
            "last_failure_at":       r.last_failure_at.isoformat() if r.last_failure_at else None,
            "consecutive_failures":  int(r.consecutive_failures or 0),
            "last_failure_reason":   r.last_failure_reason,
            "registered_at":         r.created_at.isoformat() if r.created_at else None,
        })
    return {"count": len(out), "tokens": out}


@router.get("/reachability/users",
            dependencies=[Depends(require_role(["admin", "operator"]))])
async def push_reachability_index(
    session: AsyncSession = Depends(get_db_session),
):
    """Per-user reachability roll-up — for Command Center guardian
    health badge. Worst-of across the user's tokens wins
    (dead > risk > unknown > healthy)."""
    from datetime import datetime, timezone
    rows = (await session.execute(
        text("""SELECT user_id, token, last_success_at, last_failure_at,
                       consecutive_failures, last_failure_reason
                  FROM push_tokens""")
    )).fetchall()
    now = datetime.now(timezone.utc)
    rank = {"dead": 3, "risk": 2, "unknown": 1, "healthy": 0}
    by_user: dict[str, dict] = {}
    for r in rows:
        st = _classify(r.last_success_at, r.last_failure_at,
                       int(r.consecutive_failures or 0), now)
        prev = by_user.get(str(r.user_id))
        if prev is None or rank[st] > rank[prev["status"]]:
            by_user[str(r.user_id)] = {
                "user_id": str(r.user_id),
                "status":  st,
                "last_success_at": r.last_success_at.isoformat() if r.last_success_at else None,
                "consecutive_failures": int(r.consecutive_failures or 0),
                "last_failure_reason":  r.last_failure_reason,
            }
    return {
        "count": len(by_user),
        "users": list(by_user.values()),
    }


# ── Dev/Test helpers ────────────────────────────────────────────────
class TestLouderPushRequest(BaseModel):
    title: str | None = None
    body: str | None = None


@router.post("/test/louder")
async def test_louder_push(
    body: TestLouderPushRequest | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Fire a `louder_push` (critical_safety channel) FCM notification to
    the caller's own registered devices. For E2E channel validation —
    confirms the Android client has the `critical_safety` channel
    registered with siren sound, MAX importance, and DND bypass.

    Returns the count of tokens the message was dispatched to. A
    response of `{"sent": 0, ...}` typically means the user has no
    push tokens registered, or FCM is not configured server-side.
    """
    from app.services.push_service import (
        get_user_push_tokens,
        send_push_to_tokens,
    )
    tokens = await get_user_push_tokens(session, current_user.id)
    if not tokens:
        return {
            "sent": 0,
            "tokens": 0,
            "reason": "no_push_tokens_registered",
            "hint": "Open the mobile app, grant notification permission, then retry.",
        }
    payload = body or TestLouderPushRequest()
    sent = await send_push_to_tokens(
        tokens,
        title=payload.title or "TEST: Critical Safety Alert",
        body=payload.body or "If you can hear the siren and see this on lock screen, the channel works.",
        data={
            "tag": "louder_push.test",
            "test": "true",
        },
        louder=True,
    )
    return {
        "sent": sent,
        "tokens": len(tokens),
        "channel": "critical_safety",
        "louder": True,
    }
