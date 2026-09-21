import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOBILE = Path(
    os.environ.get("NISCHINT_MOBILE_ROOT") or (ROOT.parent / "mobile")
).resolve()


def test_subscription_service_contract_present():
    text = (ROOT / "app/services/subscription_service.py").read_text(encoding="utf-8")
    assert "protected_member_user_id UUID NULL" in text
    assert "free_protected_member_slots" in text
    assert "NEW_SUBSCRIPTION_REQUIRED" in text
    assert "wearable\": premium" in text
    assert "advanced_sensor_monitoring\": premium" in text


def test_invite_consumes_slot_only_on_successful_join():
    text = (ROOT / "app/api/auth.py").read_text(encoding="utf-8")
    assert "reserve_slot_for_invite" in text
    assert "bind_reserved_subscription" in text
    assert "clear_invite_reservation" in text


def test_cancel_uses_current_guardian_and_no_stale_undefined_guardian():
    text = (ROOT / "app/api/auth.py").read_text(encoding="utf-8")
    cancel = text.split('@router.post("/family/cancel-invite-code")', 1)[1].split('@router.get("/family/invite-history")', 1)[0]
    assert "guardian_user_id=user.id" in cancel
    assert "guardian_user_id=guardian.id" not in cancel


def test_qr_client_has_short_timeout_and_no_double_generate_retry():
    endpoints = (MOBILE / "services/endpoints.ts").read_text(encoding="utf-8")
    settings = (MOBILE / "app/(tabs)/settings.tsx").read_text(encoding="utf-8")
    assert "timeout: 6000" in endpoints
    assert "generateInviteCode(purpose)" in settings
    assert "const retry = await authService.generateInviteCode" not in settings


def test_old_premium_five_member_bypass_removed():
    home = (MOBILE / "app/(tabs)/home.tsx").read_text(encoding="utf-8")
    settings = (MOBILE / "app/(tabs)/settings.tsx").read_text(encoding="utf-8")
    assert "subPlan === 'premium' ? 5 : 1" not in home
    assert "Visa ending 4242" not in settings


def test_subscription_ui_is_per_member():
    settings = (MOBILE / "app/(tabs)/settings.tsx").read_text(encoding="utf-8")
    assert "Each subscription includes 1 Parent + 1 Co-Parent + 1 Protected Member" in settings
    assert "The slot is consumed only after a protected member successfully joins" in settings
    assert "Premium ₹499 required" in (MOBILE / "app/(tabs)/incidents.tsx").read_text(encoding="utf-8")
