"""Phase 7C-5 source/policy contracts. Offline only; no DB/network/provider."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT.parent.parent  # used only when package validation copies helper beside payload


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class Phase7C5Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = read("app/api/auth.py")
        cls.step = read("app/api/stepup_auth.py")
        cls.phone = read("app/api/phone_change_auth.py")
        cls.phone_service = read("app/services/auth_phone_change_service.py")
        cls.policy = read("app/core/auth_foundation_policy.py")

    def test_01_all_six_stepup_actions_remain_defined(self):
        for action in ("ownership_transfer", "circle_delete", "member_remove", "plan_cancel", "phone_change", "minor_add"):
            self.assertIn(f'"{action}"', self.policy)

    def test_02_generic_stepup_phone_change_shortcut_blocked(self):
        self.assertIn('_GENERIC_ACTIONS = STEP_UP_ACTIONS - {"phone_change"}', self.step)
        self.assertIn('Use the verified phone-change workflow', self.step)

    def test_03_stepup_requires_current_server_session(self):
        self.assertIn("decode_local_token_claims", self.step)
        self.assertIn('claims or {}).get("sid")', self.step)
        self.assertIn("requires a current server session", self.step)

    def test_04_stepup_challenge_is_action_target_bound(self):
        self.assertIn("stepup-challenge:{binding.user_id}:{binding.session_id}", self.step)
        self.assertIn("{binding.action}:{binding.circle_id or '-'}:{binding.target_id or '-'}", self.step)

    def test_05_stepup_uses_shared_phone_otp_security_boundary(self):
        self.assertIn("issue_phone_code", self.step)
        self.assertIn("verify_phone_code", self.step)

    def test_06_stepup_proof_issued_only_after_verified_otp(self):
        verify_pos = self.step.index("await verify_phone_code")
        issue_pos = self.step.index("await issue_after_verified_otp", verify_pos)
        self.assertGreater(issue_pos, verify_pos)

    def test_07_stepup_proof_consumed_in_caller_transaction(self):
        self.assertIn("consume_bound_proof", self.step)
        self.assertNotIn("await session.commit()", self.step[self.step.index("async def consume_stepup_for_action"):self.step.index('@router.post("/step-up/request"')])

    def test_08_legacy_member_namespace_is_explicitly_noncanonical(self):
        self.assertIn("legacy_member_namespace", self.step)
        self.assertIn("does NOT assert Family membership", self.step)

    def test_09_direct_me_phone_mutation_closed(self):
        segment = self.auth[self.auth.index('@router.patch("/me/phone")'):self.auth.index("class UpdateMyProfileRequest")]
        self.assertIn("Use the phone-change workflow", segment)
        self.assertNotIn("db_user.phone =", segment)

    def test_10_profile_phone_bypass_closed_but_name_update_retained(self):
        segment = self.auth[self.auth.index('@router.patch("/me/profile")'):self.auth.index('@router.get("/two-factor/status")')]
        self.assertIn("requested_name", segment)
        self.assertIn("db_user.full_name = requested_name", segment)
        self.assertIn("Use the phone-change workflow", segment)
        self.assertNotIn("db_user.phone = normalized_phone", segment)

    def test_11_auth_mounts_stepup_and_phone_change_routers(self):
        self.assertIn("router.include_router(stepup_auth_router)", self.auth)
        self.assertIn("router.include_router(phone_change_auth_router)", self.auth)

    def test_11b_same_phone_legacy_profile_payload_remains_noop_compatible(self):
        segment = self.auth[self.auth.index('@router.patch("/me/profile")'):self.auth.index('@router.get("/two-factor/status")')]
        self.assertIn("same_phone_payload = True", segment)
        self.assertIn('"unchanged": True', segment)
        self.assertNotIn("db_user.phone =", segment)

    def test_12_normal_phone_change_starts_with_old_phone_otp(self):
        self.assertIn('purpose=OLD_PURPOSE', self.phone)
        self.assertIn('next": "verify_old"', self.phone)

    def test_13_normal_phone_change_requires_old_before_new(self):
        self.assertIn('Verify the current mobile number first', self.phone)

    def test_14_recovery_waits_until_eligible(self):
        self.assertIn("recovery_is_eligible", self.phone)
        self.assertIn("Phone recovery is not yet eligible", self.phone)
        self.assertIn("PHONE_RECOVERY_SECONDS", self.phone_service)
        self.assertIn("pending_phone_change_exists", self.phone)
        self.assertIn("pending_phone_change_exists", self.phone_service)
        self.assertIn("A phone change is already pending", self.phone)

    def test_15_recovery_queues_owner_notice(self):
        self.assertIn("queue_recovery_owner_notice", self.phone)
        self.assertIn("family_notification_outbox", self.phone_service)
        self.assertIn("c.owner_user_id", self.phone_service)
        self.assertIn("phone_change_recovery_requested", self.phone_service)

    def test_16_recovery_outside_circle_is_explicit_not_required(self):
        self.assertIn("owner_notice_state='not_required'", self.phone_service)

    def test_17_new_number_must_match_operation_digest(self):
        self.assertIn("phone_matches_operation", self.phone)
        self.assertIn("new_phone_digest", self.phone_service)
        self.assertIn("phone_security_key", self.phone_service)

    def test_18_raw_phone_is_not_persisted_in_operation_service(self):
        insert = self.phone_service[self.phone_service.index("INSERT INTO auth_phone_change_operations"):]
        self.assertIn("old_phone_digest", insert)
        self.assertIn("new_phone_digest", insert)
        self.assertNotIn("old_phone,", insert.split("VALUES", 1)[0])
        self.assertNotIn("new_phone,", insert.split("VALUES", 1)[0])

    def test_18b_abandoned_phone_change_can_be_cancelled_without_identity_mutation(self):
        self.assertIn('@router.post("/phone-change/cancel")', self.phone)
        self.assertIn("cancel_phone_change", self.phone)
        self.assertIn("status='cancelled', cancelled_at=:now", self.phone_service)
        cancel_segment = self.phone[self.phone.index('async def cancel_pending_phone_change'):self.phone.index('@router.post("/phone-change/request-old", status_code=status.HTTP_202_ACCEPTED)')]
        self.assertNotIn("db_user.phone", cancel_segment)
        self.assertNotIn("revoke_all_auth_sessions", cancel_segment)

    def test_19_new_phone_verification_issues_phone_change_bound_proof(self):
        verify = self.phone[self.phone.index('async def verify_new_phone'):self.phone.index('@router.post("/phone-change/complete")')]
        self.assertIn('action="phone_change"', verify)
        self.assertIn("target_id=body.operation_id", verify)
        self.assertIn("issue_after_verified_otp", verify)

    def test_20_completion_rechecks_full_operation_readiness(self):
        complete = self.phone[self.phone.index('async def complete_phone_change'):]
        self.assertIn("operation_ready(row, now=now)", complete)

    def test_21_completion_serializes_user_auth_boundary(self):
        self.assertIn("lock_user_auth_boundary", self.phone)
        self.assertIn("pg_advisory_xact_lock", self.phone)

    def test_22_completion_rechecks_number_uniqueness_after_lock(self):
        complete = self.phone[self.phone.index('async def complete_phone_change'):]
        self.assertIn("await _ensure_phone_available", complete)

    def test_23_proof_consumption_precedes_phone_mutation(self):
        complete = self.phone[self.phone.index('async def complete_phone_change'):]
        self.assertLess(complete.index("consume_bound_proof"), complete.index("db_user.phone = new_phone"))

    def test_24_phone_change_updates_sms_2fa_binding(self):
        self.assertIn("UPDATE auth_two_factor_settings", self.phone)
        self.assertIn("phone_hash=:phone_hash", self.phone)

    def test_25_phone_change_revokes_all_prior_sessions(self):
        self.assertIn('revoke_all_auth_sessions(session, user.id, reason="phone_change")', self.phone)
        self.assertIn("bump_user_token_epoch", self.phone)

    def test_26_phone_change_revokes_sos_credentials(self):
        self.assertIn("UPDATE auth_sos_credentials", self.phone)
        self.assertIn("revoked_at=COALESCE", self.phone)

    def test_27_phone_change_clears_push_destinations(self):
        self.assertIn("DELETE FROM push_tokens WHERE user_id=:uid", self.phone)

    def test_28_phone_change_preserves_user_identity_not_recreate_account(self):
        self.assertIn("db_user.phone = new_phone", self.phone)
        self.assertNotIn("DELETE FROM users", self.phone)
        self.assertNotIn("INSERT INTO users", self.phone)

    def test_29_operation_completion_and_proof_share_one_commit(self):
        complete = self.phone[self.phone.index('async def complete_phone_change'):]
        self.assertEqual(complete.count("await session.commit()"), 1)
        self.assertLess(complete.index("consume_bound_proof"), complete.index("await session.commit()"))
        self.assertLess(complete.index("mark_completed"), complete.index("await session.commit()"))

    def test_30_recovery_ready_requires_notice_handoff(self):
        self.assertIn("owner_notice_state", self.phone_service)
        self.assertIn('{"delivered", "not_required"}', self.phone_service)

    def test_31_no_new_7c5_migration_expected(self):
        migrations = list((ROOT / "migrations" / "versions").glob("*.py"))
        unexpected = [p.name for p in migrations if p.name.casefold().startswith("auth06") or "7c5" in p.name.casefold()]
        self.assertEqual(unexpected, [])

    def test_32_auth05_still_contains_phone_change_and_stepup_state(self):
        migration = read("migrations/versions/auth05_security_foundation.py")
        self.assertIn("auth_phone_change_operations", migration)
        self.assertIn("proof_session_id", migration)
        self.assertIn("stepup:phone_change", migration)

    def test_33_policy_recovery_boundary_is_24_hours(self):
        ns = {}
        exec(compile(self.policy, "auth_foundation_policy.py", "exec"), ns)
        now = datetime.now(timezone.utc)
        self.assertEqual(ns["PHONE_RECOVERY_SECONDS"], 24 * 60 * 60)
        self.assertFalse(ns["phone_change_ready"](
            recovery=True,
            requested_at=now,
            eligible_after=now + timedelta(hours=24),
            old_verified_at=None,
            new_verified_at=now,
            now=now + timedelta(hours=23, minutes=59),
        ))

    def test_34_policy_normal_change_requires_both_numbers(self):
        ns = {}
        exec(compile(self.policy, "auth_foundation_policy.py", "exec"), ns)
        now = datetime.now(timezone.utc)
        self.assertFalse(ns["phone_change_ready"](
            recovery=False,
            requested_at=now,
            eligible_after=now,
            old_verified_at=None,
            new_verified_at=now,
            now=now,
        ))
        self.assertTrue(ns["phone_change_ready"](
            recovery=False,
            requested_at=now,
            eligible_after=now,
            old_verified_at=now,
            new_verified_at=now,
            now=now,
        ))

    def test_35_action_binding_requires_phone_operation_target(self):
        ns = {}
        exec(compile(self.policy, "auth_foundation_policy.py", "exec"), ns)
        with self.assertRaises(ValueError):
            ns["ActionBinding"](user_id=uuid4(), session_id=uuid4(), action="phone_change")

    def test_36_legacy_guardian_removal_requires_fresh_stepup(self):
        guardian_path = ROOT / "app/api/guardian_network.py"
        self.assertTrue(guardian_path.is_file(), "guardian_network.py is required for the 7C-5 compatibility boundary")
        source = guardian_path.read_text(encoding="utf-8")
        start = source.index('@router.delete("/{relationship_id}")')
        end = source.index('@router.get("/escalation-chain")', start)
        segment = source[start:end]
        self.assertIn("consume_stepup_for_action", segment)
        self.assertIn('action="member_remove"', segment)
        self.assertIn("legacy_member_namespace=True", segment)
        self.assertIn("with_for_update()", segment)

    def test_37_legacy_guardian_removal_does_not_mutate_canonical_membership(self):
        source = (ROOT / "app/api/guardian_network.py").read_text(encoding="utf-8")
        start = source.index('@router.delete("/{relationship_id}")')
        end = source.index('@router.get("/escalation-chain")', start)
        segment = source[start:end]
        self.assertIn("rel.is_active = False", segment)
        self.assertNotIn("circle_memberships", segment)
        # Explanatory comments/docstrings may name CircleMembership.  What is
        # forbidden here is executable canonical-membership access/mutation.
        for forbidden in (
            "select(CircleMembership",
            "update(CircleMembership",
            "delete(CircleMembership",
            "session.delete(CircleMembership",
            "session.add(CircleMembership",
        ):
            self.assertNotIn(forbidden, segment)


if __name__ == "__main__":
    unittest.main()
