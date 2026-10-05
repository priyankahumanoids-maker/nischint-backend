"""Phase 7C-4 source/local contracts. No DB, provider, network, or app startup."""
from pathlib import Path
import os
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOBILE = Path(os.environ.get("NISCHINT_MOBILE_ROOT", r"D:\Nischint\cb"))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class Phase7C4Contracts(unittest.TestCase):
    def setUp(self):
        self.emergency = read("app/api/emergency.py")
        self.sos = read("app/api/sos.py")
        self.sos_auth = read("app/api/sos_auth.py")
        self.sos_service = read("app/services/auth_sos_credential_service.py")
        self.migration = read("migrations/versions/auth05_security_foundation.py")

    def test_credential_scope_is_raise_only(self):
        self.assertIn('SOS_SCOPE = "emergency:raise"', read("app/core/auth_foundation_policy.py"))
        self.assertIn('scope = \'emergency:raise\'', self.migration)

    def test_silent_sos_uses_limited_or_normal_auth_dependency(self):
        block = self.emergency[self.emergency.index('@router.post("/silent-sos")'):]
        self.assertIn("Depends(get_sos_trigger_user)", block[:600])

    def test_credential_issue_still_requires_normal_auth(self):
        block = self.emergency[self.emergency.index('@router.post("/credential")'):self.emergency.index('@router.post("/silent-sos")')]
        self.assertIn("Depends(get_current_user)", block)
        self.assertIn("current_local_session_id(request)", block)

    def test_issue_binds_installation_and_rotates(self):
        block = self.emergency[self.emergency.index('@router.post("/credential")'):self.emergency.index('@router.post("/silent-sos")')]
        self.assertIn("associate_installation", block)
        self.assertIn("rotate_sos_credential", block)
        self.assertIn("settings.jwt_secret.encode", block)

    def test_credential_lifetime_is_explicit_and_bounded(self):
        self.assertIn("SOS_CREDENTIAL_TTL_DAYS = 30", self.sos_auth)
        self.assertIn("timedelta(days=SOS_CREDENTIAL_TTL_DAYS)", self.emergency)

    def test_sos_credential_is_checked_before_bearer(self):
        credential_pos = self.sos_auth.index("resolve_sos_subject")
        bearer_pos = self.sos_auth.index('scheme, token = get_authorization_scheme_param', credential_pos)
        self.assertLess(credential_pos, bearer_pos)

    def test_sos_credential_falls_back_to_existing_bearer(self):
        self.assertIn("return await get_current_user(token=token, session=session)", self.sos_auth)

    def test_sos_subject_must_be_active(self):
        self.assertIn('bool(getattr(user, "is_active", True))', self.sos_auth)

    def test_rotate_revokes_previous_installation_credentials(self):
        self.assertIn("revoke_installation_sos_credentials", self.sos_service)
        self.assertIn("WHERE user_id=:uid AND installation_id=:iid AND revoked_at IS NULL", self.sos_service)
        self.assertIn("return await issue_sos_credential", self.sos_service)

    def test_credential_resolution_does_not_require_auth_session(self):
        resolve = self.sos_service[self.sos_service.index("async def resolve_sos_subject"):]
        self.assertNotIn("auth_sessions", resolve.split("async def revoke_sos_credential", 1)[0])

    def test_legacy_sos_trigger_accepts_limited_dependency(self):
        trigger = self.sos[self.sos.index('@router.post("/trigger")'):self.sos.index('# ── Cancel')]
        self.assertIn("Depends(_trigger_sos_user)", trigger)

    def test_cancel_does_not_accept_limited_dependency(self):
        cancel = self.sos[self.sos.index('@router.post("/cancel/{sos_id}")'):self.sos.index('# ── History')]
        self.assertIn("Depends(_trigger_role)", cancel)
        self.assertNotIn("get_sos_trigger_user", cancel)

    def test_history_does_not_accept_limited_dependency(self):
        history = self.sos[self.sos.index('@router.get("/history")'):]
        self.assertIn("Depends(_escape_role)", history)

    def test_location_cancel_resolve_keep_normal_auth(self):
        for route in ('@router.post("/location-update")', '@router.post("/cancel")', '@router.post("/resolve")'):
            start = self.emergency.index(route)
            block = self.emergency[start:start+900]
            self.assertIn("Depends(get_current_user)", block)
            self.assertNotIn("Depends(get_sos_trigger_user)", block)

    def test_existing_sos_engine_calls_remain(self):
        self.assertIn("trigger_silent_sos(", self.emergency)
        self.assertIn("notify_repeat_sos(", self.emergency)
        self.assertIn("update_emergency_location(", self.emergency)

    def test_no_new_7c4_schema_is_required(self):
        self.assertIn('"auth_sos_credentials"', self.migration)
        self.assertIn('"auth_installations"', self.migration)

    def test_mobile_uses_dedicated_header_only_for_trigger(self):
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertIn("'X-Nischint-SOS-Credential': credential", mobile)
        self.assertEqual(mobile.count("X-Nischint-SOS-Credential"), 1)

    def test_mobile_credential_is_securestore_only_not_web(self):
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertIn("SecureStore", mobile)
        self.assertIn("if (Platform.OS === 'web') return null", mobile)
        self.assertNotIn("localStorage.setItem", mobile)

    def test_mobile_installation_id_is_persistent_and_non_secret(self):
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertIn("nischint_auth_installation_id", mobile)
        self.assertIn("getInstallationId", mobile)

    def test_mobile_subject_binding_blocks_account_mixup(self):
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertIn("subject !== currentUserId", mobile)
        self.assertIn("returnedSubject !== currentUserId", mobile)

    def test_panic_path_does_not_wait_for_credential_provisioning(self):
        safety = (MOBILE / "services/deviceSafety.ts").read_text(encoding="utf-8")
        trigger = safety[safety.index("export async function triggerSilentSOS"):safety.index("// ── Cancel SOS")]
        self.assertNotIn("await emergencyService.ensureSOSCredential", trigger)
        self.assertIn("await emergencyService.triggerSOS", trigger)
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertIn("if (!credential) void ensureSOSCredential().catch(() => null)", mobile)

    def test_monitoring_start_primes_credential_nonblocking(self):
        safety = (MOBILE / "services/deviceSafety.ts").read_text(encoding="utf-8")
        start = safety[safety.index("export function startShakeDetection"):safety.index("export function stopShakeDetection")]
        self.assertIn("void emergencyService.ensureSOSCredential().catch(() => null)", start)

    def test_no_sos_credential_in_ordinary_authorization_header(self):
        mobile = (MOBILE / "services/emergency.ts").read_text(encoding="utf-8")
        self.assertNotIn("Authorization: `Bearer ${credential}`", mobile)
        self.assertNotIn("Authorization: credential", mobile)


if __name__ == "__main__":
    unittest.main()
