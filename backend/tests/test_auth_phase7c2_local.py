"""Isolated fake-state/unit/source tests; run directly with python -B.

Never imports application config, package initializers, engine or startup.
Fake state proves branch/commit ordering, NOT PostgreSQL locking/concurrency.
"""
import ast
import asyncio
import importlib.util
import sys
import types
import unittest
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Column, String
from sqlalchemy.orm import declarative_base

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.auth_foundation_policy import PhoneState, phone_result, PHONE_LOCK_SECONDS
from app.core.age_policy import calculate_age


def module(name, **values):
    m = types.ModuleType(name)
    m.__dict__.update(values)
    sys.modules[name] = m
    return m


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


# Synthetic key only. No application settings/env files loaded.
KEY = bytes(range(32))
module("app.core.config", settings=types.SimpleNamespace(jwt_secret=KEY.hex()))
services = module("app.services")
services.__path__ = []
models = module("app.models")
models.__path__ = []
Base = declarative_base()


class User(Base):
    __tablename__ = "unit_only_user"
    id = Column(String, primary_key=True)
    phone = Column(String)
    email = Column(String)


module("app.models.user", User=User)


async def unlimited(*args, **kwargs):
    pass


module("app.core.rate_limiter", enforce_otp_limit=unlimited)
otp = load("app.services.auth_otp_service", "app/services/auth_otp_service.py")
locks = load("app.services.auth_phone_security_service", "app/services/auth_phone_security_service.py")
phone = load("app.services.auth_phone_otp_service", "app/services/auth_phone_otp_service.py")
admission = load("app.services.auth_registration_admission", "app/services/auth_registration_admission.py")
quota = load("app.core.otp_rate_limit", "app/core/otp_rate_limit.py")
NOW = datetime.now(timezone.utc)
PHONE = "+919876543210"
REQUEST = types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host="127.0.0.1"))


def run(coro):
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coro.close()
    raise AssertionError("Unexpected external await in isolated test")


class Result:
    def __init__(self, row=None, values=(), scalar=None):
        self.row, self.values, self.scalar = row, values, scalar
    def mappings(self): return self
    def first(self): return self.row
    def one(self): return self.row
    def scalars(self): return self
    def all(self): return self.values
    def scalar_one_or_none(self): return self.scalar


class FakeSession:
    """Small AUTH03/05 statement interpreter; never claims SQL engine fidelity."""
    def __init__(self):
        self.state, self.otps, self.events = PhoneState(), {}, []
        self.commits, self.users, self.duplicate_email = 0, [], None
    async def commit(self):
        self.commits += 1
        self.events.append("commit")
    async def execute(self, statement, params=None):
        q, p = " ".join(str(statement).split()), params or {}
        self.events.append(q)
        if "auth_phone_security" in q:
            if q.startswith("SELECT"):
                return Result({"failure_count": self.state.failures, "locked_until": self.state.locked_until})
            if q.startswith("UPDATE"):
                self.state = PhoneState(p["failures"], p["locked_until"])
            return Result()
        if "auth_otps" in q:
            k = p["email_hash"], p["purpose"]
            row = self.otps.get(k)
            if q.startswith("SELECT"):
                return Result(row)
            if q.startswith("INSERT"):
                self.otps[k] = {"code_digest": p["code_digest"], "attempts": 0,
                               "resend_available_at": NOW + timedelta(seconds=p["cooldown_seconds"]),
                               "ttl": p["ttl_seconds"]}
            elif q.startswith("DELETE"):
                if "expires_at <= NOW()" not in q:
                    self.otps.pop(k, None)
            elif q.startswith("UPDATE"):
                row["attempts"] = p["attempts"]
            return Result()
        if q.startswith("SELECT pg_advisory"):
            return Result()
        if "lower(" in q:
            return Result(scalar=self.duplicate_email)
        return Result(values=self.users)


def source(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def function(rel, name):
    s = source(rel)
    node = next(n for n in ast.parse(s).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(s, node)


def executable(rel, name, **namespace):
    n = ast.parse(function(rel, name)).body[0]
    n.decorator_list = []
    n.args.defaults = []
    n.args.kw_defaults = [None] * len(n.args.kwonlyargs)
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), n], type_ignores=[])
    ast.fix_missing_locations(tree)
    exec(compile(tree, rel, "exec"), namespace)
    return namespace[name]


class PhonePolicyTests(unittest.TestCase):
    def setUp(self): self.s = FakeSession()
    def issue(self, purpose=phone.PHONE_LOGIN):
        return run(phone.issue_phone_code(self.s, REQUEST, phone=PHONE, purpose=purpose))
    def verify(self, code, purpose=phone.PHONE_LOGIN):
        return run(phone.verify_phone_code(self.s, REQUEST, phone=PHONE, purpose=purpose, code=code))
    def test_exact_phone_timing(self):
        self.issue()
        row = next(iter(self.s.otps.values()))
        self.assertEqual(row["ttl"], 300)
        self.assertEqual(phone.OTP_RESEND_COOLDOWN_SECONDS, 30)
    def test_resend_within_window_denied(self):
        self.issue()
        with self.assertRaises(HTTPException) as err: self.issue()
        self.assertEqual(err.exception.status_code, 429)
        self.assertEqual(len(self.s.otps), 1)
    def test_fifth_failure_commits_900_second_lock(self):
        self.issue()
        for _ in range(5):
            with self.assertRaises(HTTPException): self.verify("wrong")
        self.assertEqual(self.s.commits, 5)
        self.assertEqual(self.s.state.failures, 5)
        self.assertAlmostEqual((self.s.state.locked_until - datetime.now(timezone.utc)).total_seconds(), 900, delta=2)
        self.assertFalse(self.s.otps)
        self.assertEqual(self.s.events[-1], "commit")
    def test_lock_survives_deleted_challenge_and_purpose_switch(self):
        self.s.state = PhoneState(5, NOW + timedelta(seconds=900))
        for purpose in [phone.PHONE_LOGIN, phone.SIGNUP_PHONE, "two_factor_login", "two_factor_enable"]:
            with self.assertRaises(HTTPException) as err: self.issue(purpose)
            self.assertEqual(err.exception.status_code, 429)
        self.assertFalse(self.s.otps)
        self.assertEqual(self.s.state.failures, 5)
    def test_active_lock_cannot_be_lifted_by_valid_code(self):
        code = self.issue()
        self.s.state = PhoneState(5, NOW + timedelta(seconds=900))
        with self.assertRaises(HTTPException): self.verify(code)
        self.assertEqual(len(self.s.otps), 1)
    def test_success_is_single_use_and_caller_owns_commit(self):
        code = self.issue()
        self.assertTrue(self.verify(code))
        self.assertEqual(self.s.commits, 0)
        with self.assertRaises(HTTPException): self.verify(code)
        self.assertEqual(self.s.commits, 1)
    def test_purpose_separation(self):
        code = self.issue()
        for purpose in [phone.SIGNUP_PHONE, phone.SIGNUP_PROOF, "password_reset", "step_up", "two_factor_login"]:
            self.assertNotEqual(otp.otp_digest("identity", phone.PHONE_LOGIN, code), otp.otp_digest("identity", purpose, code))
        with self.assertRaises(HTTPException): self.verify(code, phone.SIGNUP_PHONE)
        self.assertEqual(len(self.s.otps), 1)
    def test_resend_does_not_reset_phone_failures(self):
        self.s.state = PhoneState(4)
        self.issue()
        self.assertEqual(self.s.state.failures, 4)
    def test_normalization_preserves_international_identity(self):
        self.assertEqual(phone.canonical_phone("98765 43210"), PHONE)
        self.assertEqual(phone.canonical_phone("+1234567890"), "+1234567890")
        self.assertNotEqual(phone.canonical_phone("+449876543210"), PHONE)
    def test_invalid_phone_denied(self):
        for value in [None, "letters9876543210", "+00000000000", "123"]:
            with self.assertRaises(HTTPException): phone.canonical_phone(value)
    def test_phone_lookup_is_full_number_not_last_ten(self):
        run(phone.users_for_phone(self.s, PHONE))
        sql = self.s.events[-1]
        self.assertIn("CASE WHEN", sql)
        self.assertNotIn("right(", sql)
        self.assertIn("LIMIT", sql)
    def test_legacy_email_defaults_unchanged(self):
        run(otp.store_otp(self.s, email="unit@example.invalid", purpose="email_verification", code="123456"))
        self.assertEqual(next(iter(self.s.otps.values()))["ttl"], 600)
    def test_old_phone_challenges_are_capped_at_300_but_tickets_are_preserved(self):
        seen = []
        async def consume(*args, **kwargs):
            seen.append(kwargs)
            return True
        with patch.object(phone, "consume_otp", consume):
            self.verify("123456")
            self.verify("synthetic-proof", phone.SIGNUP_PROOF)
        self.assertEqual(seen[0]["max_age_seconds"], 300)
        self.assertIsNone(seen[1]["max_age_seconds"])
        sql_source = function("app/services/auth_otp_service.py", "consume_otp")
        self.assertIn("clock_timestamp()", sql_source)
        self.assertIn("created_at >", sql_source)
    def test_quota_denial_precedes_db_work(self):
        async def deny(*args, **kwargs): raise HTTPException(503, "unavailable")
        with patch.object(phone, "enforce_otp_limit", deny), self.assertRaises(HTTPException): self.issue()
        self.assertEqual(self.s.events, [])


class AdmissionTests(unittest.TestCase):
    def test_minor_denied_before_proof_or_db(self):
        s = FakeSession()
        with self.assertRaises(HTTPException) as err:
            run(admission.admit_independent_account(s, REQUEST, phone=PHONE, email="minor@example.invalid", date_of_birth=date.today()))
        self.assertEqual(err.exception.status_code, 403)
        self.assertEqual(s.events, [])
    def test_exact_birthday(self):
        today = date(2026, 10, 5)
        with patch.object(admission, "calculate_age", lambda dob: calculate_age(dob, today)):
            admission.require_adult(date(2008, 10, 5))
            with self.assertRaises(HTTPException): admission.require_adult(date(2008, 10, 6))
    def test_leap_day(self):
        with patch.object(admission, "calculate_age", lambda dob: calculate_age(dob, date(2026, 2, 28))):
            with self.assertRaises(HTTPException): admission.require_adult(date(2008, 2, 29))
        with patch.object(admission, "calculate_age", lambda dob: calculate_age(dob, date(2026, 3, 1))):
            admission.require_adult(date(2008, 2, 29))
    def test_invalid_future_missing_dob(self):
        for dob in [None, "invalid", date(2999, 1, 1)]:
            with self.assertRaises(HTTPException): admission.require_adult(dob)
    def test_adult_still_requires_phone_proof(self):
        with self.assertRaises(HTTPException) as err:
            run(admission.admit_independent_account(FakeSession(), REQUEST, phone=PHONE, email="adult@example.invalid", date_of_birth=date(1990, 1, 1)))
        self.assertEqual(err.exception.status_code, 403)
    def test_registration_ticket_single_use(self):
        s, ticket = FakeSession(), "synthetic-proof-" + "x" * 32
        run(otp.store_otp(s, email=phone.challenge_identity(PHONE, phone.SIGNUP_PROOF), purpose=phone.SIGNUP_PROOF, code=ticket))
        req = types.SimpleNamespace(headers={"X-Signup-Phone-Verification": ticket})
        args = dict(phone=PHONE, email="adult@example.invalid", date_of_birth=date(1990, 1, 1))
        self.assertEqual(run(admission.admit_independent_account(s, req, **args)), PHONE)
        self.assertEqual(s.commits, 0)
        with self.assertRaises(HTTPException): run(admission.admit_independent_account(s, req, **args))
        self.assertEqual(s.commits, 1)
    def test_duplicate_account_denied_without_consuming_proof(self):
        s = FakeSession()
        s.duplicate_email = "existing-user"
        req = types.SimpleNamespace(headers={"X-Signup-Phone-Verification": "x" * 40})
        with self.assertRaises(HTTPException) as err:
            run(admission.admit_independent_account(s, req, phone=PHONE, email="e@example.invalid", date_of_birth=date(1990, 1, 1)))
        self.assertEqual(err.exception.status_code, 409)
        self.assertFalse(any("DELETE FROM auth_otps" in q for q in s.events))
    def test_unknown_cognito_cannot_provision(self):
        with self.assertRaises(HTTPException) as err: admission.require_registration_admission()
        self.assertEqual(err.exception.status_code, 403)


class QuotaTests(unittest.TestCase):
    def args(self, **changes):
        return dict(identity="phone:" + PHONE, ip="127.0.0.1", purpose="phone_login", operation="issue", key=KEY, **changes)
    def test_phone_shared_across_purposes(self):
        a = self.args()
        k1, _ = quota.quota_spec(**a)
        a["purpose"] = "signup_phone"
        k2, _ = quota.quota_spec(**a)
        self.assertEqual(k1[:2], k2[:2])
        self.assertNotEqual(k1[2], k2[2])
    def test_ip_shared_across_phones(self):
        a = self.args()
        k1, _ = quota.quota_spec(**a)
        a["identity"] = "phone:+441234567890"
        k2, _ = quota.quota_spec(**a)
        self.assertEqual(k1[0], k2[0])
        self.assertNotEqual(k1[1], k2[1])
    def test_quota_keys_contain_no_raw_identity(self):
        keys, _ = quota.quota_spec(**self.args())
        self.assertNotIn(PHONE, str(keys))
        self.assertNotIn("127.0.0.1", str(keys))
    def test_missing_redis_denies(self):
        with self.assertRaises(quota.QuotaUnavailable): quota.check_quota(None, **self.args())
    def test_redis_exception_denies(self):
        class Broken:
            def eval(self, *args): raise ConnectionError("synthetic outage")
        with self.assertRaises(quota.QuotaUnavailable): quota.check_quota(Broken(), **self.args())
    def test_redis_success_and_limit(self):
        class Fake:
            def eval(self, *args): return 0
        self.assertEqual(quota.check_quota(Fake(), **self.args()), 0)
        class Limited:
            def eval(self, *args): return 45
        self.assertEqual(quota.check_quota(Limited(), **self.args()), 45)
    def test_supplemental_phone_quota_does_not_double_charge_peer(self):
        keys, values = quota.quota_spec(**self.args(include_peer=False))
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(values), 3)
    def test_forwarded_ip_not_read(self):
        body = function("app/core/rate_limiter.py", "enforce_otp_limit")
        self.assertIn('"client"', body)
        self.assertNotIn("request.headers", body)
        self.assertIn("503", body)
        self.assertIn('"Retry-After": "30"', body)

    def test_actual_wrapper_outage_is_503_without_memory_fallback(self):
        module("app.services.redis_service", _get_client=lambda: None)
        fn = executable("app/core/rate_limiter.py", "enforce_otp_limit")
        async def inline(callback): return callback()
        req = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"),
                                    headers={"X-Forwarded-For": "spoofed"})
        with patch.object(asyncio, "to_thread", inline), self.assertRaises(HTTPException) as err:
            run(fn(req, identity="phone:" + PHONE, purpose="phone_login", operation="issue", key=KEY, include_peer=True))
        self.assertEqual(err.exception.status_code, 503)
        self.assertEqual(err.exception.headers["Retry-After"], "30")

    def test_actual_wrapper_uses_peer_not_forwarded_header(self):
        seen = []
        class Client:
            def eval(self, *args):
                seen.append(args)
                return 0
        module("app.services.redis_service", _get_client=Client)
        fn = executable("app/core/rate_limiter.py", "enforce_otp_limit")
        async def inline(callback): return callback()
        req = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"),
                                    headers={"X-Forwarded-For": "spoofed"})
        with patch.object(asyncio, "to_thread", inline):
            run(fn(req, identity="phone:" + PHONE, purpose="phone_login", operation="issue", key=KEY, include_peer=True))
        keys, _ = quota.quota_spec(**self.args())
        self.assertEqual(seen[0][2], keys[0])


class ProviderAdmissionTests(unittest.TestCase):
    def google(self, existing):
        async def by_email(*args): return existing
        return executable("app/api/google_auth.py", "_provision_google_user",
                          user_service=types.SimpleNamespace(get_user_by_email=by_email),
                          User=lambda **values: types.SimpleNamespace(**values))

    def test_existing_google_user_needs_no_new_proof_or_dob(self):
        user = types.SimpleNamespace(id="old-google-id", cognito_sub="google_known", full_name="Existing")
        s = FakeSession()
        async def flush(): pass
        s.flush = flush
        result, new = run(self.google(user)(s, {"email": "e@example.invalid"}, phone=None, date_of_birth=None, request=None))
        self.assertIs(result, user)
        self.assertFalse(new)
        self.assertEqual(s.events, [])

    def test_new_google_minor_is_rejected_before_user_creation(self):
        s = FakeSession()
        with self.assertRaises(HTTPException) as err:
            run(self.google(None)(s, {"email": "new@example.invalid"}, phone=PHONE,
                                  date_of_birth=date.today(), request=REQUEST))
        self.assertEqual(err.exception.status_code, 403)
        self.assertEqual(s.events, [])

    def test_new_google_adult_cannot_bypass_phone_proof(self):
        with self.assertRaises(HTTPException) as err:
            run(self.google(None)(FakeSession(), {"email": "new@example.invalid"}, phone=PHONE,
                                  date_of_birth=date(1990, 1, 1), request=REQUEST))
        self.assertEqual(err.exception.status_code, 403)

    def test_existing_cognito_sub_preserves_identity(self):
        user = types.SimpleNamespace(id="old-cognito-id")
        async def by_sub(*args): return user
        async def by_email(*args): raise AssertionError("Must use existing sub")
        fn = executable("app/services/user_service.py", "auto_provision_cognito_user",
                        get_user_by_cognito_sub=by_sub, get_user_by_email=by_email)
        self.assertIs(run(fn(FakeSession(), "known", "e@example.invalid", None, None, "guardian")), user)

    def test_unknown_cognito_cannot_create_even_if_provider_calls_it_minor(self):
        async def missing(*args): return None
        fn = executable("app/services/user_service.py", "auto_provision_cognito_user",
                        get_user_by_cognito_sub=missing, get_user_by_email=missing)
        for role in ["guardian", "child"]:
            with self.assertRaises(HTTPException) as err:
                run(fn(FakeSession(), "new", "new@example.invalid", "Name", PHONE, role))
            self.assertEqual(err.exception.status_code, 403)


class LoginTests(unittest.TestCase):
    def verify(self, *, valid, users):
        s, calls = FakeSession(), []
        installation_id = UUID("00000000-0000-4000-8000-000000000001")
        session_id = UUID("00000000-0000-4000-8000-000000000002")
        # Retain the existing response sentinel assertion while representing
        # the session field consumed by the accepted installation binding.
        class SessionResponse(str):
            pass
        response = SessionResponse("session-response")
        response.session_id = session_id
        async def associate(session, *, user_id, session_id, installation_id, key, now):
            self.assertIs(session, s)
            self.assertEqual(user_id, users[0].id)
            self.assertEqual(session_id, response.session_id)
            self.assertEqual(installation_id, UUID("00000000-0000-4000-8000-000000000001"))
            self.assertEqual(key, KEY.hex().encode("utf-8"))
            self.assertIsNotNone(now.tzinfo)
            calls.append("associate_installation")
        module("app.services.auth_installation_service", associate_installation=associate)
        async def verifier(*args, **kwargs):
            calls.append("verify")
            if not valid: raise HTTPException(400, "invalid")
        async def lookup(*args):
            calls.append("lookup")
            return users
        async def state(*args, **kwargs): return {"configured": False}
        async def issuer(session, user, request, **kwargs):
            calls.append(("issue", user.id))
            return response
        module("app.api.auth", _issue_local_session_response=issuer)
        fn = executable("app/api/phone_auth.py", "verify_phone_login", canonical_phone=phone.canonical_phone,
                        verify_phone_code=verifier, users_for_phone=lookup, PHONE_LOGIN=phone.PHONE_LOGIN,
                        HTTPException=HTTPException, UUID=UUID, datetime=datetime, timezone=timezone,
                        settings=types.SimpleNamespace(jwt_secret=KEY.hex()),
                        auth_two_factor_service=types.SimpleNamespace(get_sms_two_factor_state=state),
                        user_cache=types.SimpleNamespace(cache_user=lambda *args: calls.append("cache")))
        try:
            result = run(fn(REQUEST, types.SimpleNamespace(phone=PHONE, code="123456", installation_id=installation_id), s))
        except HTTPException as exc:
            result = exc.status_code
        return result, calls, s
    def test_no_session_or_lookup_before_success(self):
        result, calls, _ = self.verify(valid=False, users=[])
        self.assertEqual(result, 400)
        self.assertEqual(calls, ["verify"])
    def test_verified_phone_uses_existing_id_and_session_issuer(self):
        user = types.SimpleNamespace(id="preserved-id", is_active=True, phone=PHONE)
        result, calls, s = self.verify(valid=True, users=[user])
        self.assertEqual(result, "session-response")
        self.assertEqual(calls[:3], ["verify", "lookup", ("issue", "preserved-id")])
        self.assertEqual(calls[3:], ["associate_installation", "cache"])
        self.assertEqual(s.commits, 1)
    def test_unknown_phone_creates_no_user_or_session(self):
        result, calls, s = self.verify(valid=True, users=[])
        self.assertEqual(result, 401)
        self.assertEqual(calls, ["verify", "lookup"])
        self.assertEqual(s.commits, 1)
    def test_ambiguous_phone_fails_closed(self):
        result, calls, _ = self.verify(valid=True, users=[object(), object()])
        self.assertEqual(result, 401)
        self.assertEqual(calls, ["verify", "lookup"])
    def test_inactive_account_cannot_issue(self):
        result, calls, _ = self.verify(valid=True, users=[types.SimpleNamespace(is_active=False)])
        self.assertEqual(result, 401)
        self.assertEqual(calls, ["verify", "lookup"])
    def test_issue_no_existence_query_or_account_response(self):
        s = function("app/api/phone_auth.py", "request_phone_login")
        self.assertNotIn("users_for_phone", s)
        self.assertNotIn("select(", s)
        self.assertIn('"accepted": True', s)
        self.assertLess(s.index("await session.commit()"), s.index("sms_service.send_sms"))


class SourceContracts(unittest.TestCase):
    def test_public_users_service_requires_admission(self):
        body = function("app/services/user_service.py", "create_user")
        self.assertLess(body.index("admit_independent_account("), body.index("user = User("))
        self.assertIn("request=request", function("app/api/users.py", "create_user"))
    def test_google_existing_path_precedes_new_admission(self):
        body = function("app/api/google_auth.py", "_provision_google_user")
        self.assertLess(body.index("return user, False"), body.index("admit_independent_account("))
        self.assertLess(body.index("admit_independent_account("), body.index("user = User("))
        self.assertIn("date_of_birth=date_of_birth", body)
    def test_cognito_preserves_existing_branches_and_denies_unknown(self):
        body = function("app/services/user_service.py", "auto_provision_cognito_user")
        self.assertIn("return existing", body)
        self.assertIn("return by_email", body)
        self.assertNotIn("User(", body)
        self.assertIn("require_registration_admission()", body)
    def test_independent_register_uses_shared_admission(self):
        body = function("app/api/auth.py", "register")
        self.assertLess(body.index("admit_independent_account("), body.index("_cognito_register("))
        self.assertIn("_local_register(", body)
    def test_parental_invites_keep_canonical_minor_authority(self):
        body = function("app/api/auth.py", "verify_invite_code")
        self.assertIn("accept_invite_for_user(", body)
        self.assertEqual(body.count("_consume_signup_phone_verification(session, request, normalized_phone, email=req.email)"), 2)
        self.assertIn("_require_adult_self_registration(req.date_of_birth)", body)
    def test_phone_routes_use_shared_boundary(self):
        matrix = {
            "request_signup_phone_otp": "issue_phone_code(", "verify_signup_phone_otp": "verify_phone_code(",
            "_send_sms_two_factor_code": "issue_phone_code(", "confirm_two_factor_enable": "verify_phone_code(",
            "confirm_two_factor_disable": "verify_phone_code(", "verify_two_factor_login": "verify_phone_code(",
        }
        for name, call in matrix.items():
            with self.subTest(route=name): self.assertIn(call, function("app/api/auth.py", name))
    def test_other_public_otp_routes_share_quota(self):
        for name in ["confirm", "request_email_verification", "confirm_email_verification", "forgot_password", "reset_password"]:
            with self.subTest(route=name): self.assertIn("limit_account_otp(", function("app/api/auth.py", name))
    def test_two_factor_resend_uses_same_issue_owner(self):
        self.assertIn("_send_sms_two_factor_code(", function("app/api/auth.py", "resend_two_factor_login"))
    def test_legacy_login_and_refresh_issuance_not_replaced(self):
        body = function("app/api/auth.py", "login")
        self.assertIn("_cognito_login(", body)
        self.assertIn("_local_login(", body)
        issuer = function("app/api/auth.py", "_issue_local_session_response")
        self.assertIn("create_auth_session(", issuer)
        self.assertIn("create_refresh_token(", issuer)
    def test_no_new_schema_or_startup_call_in_boundary(self):
        for rel in ["app/api/phone_auth.py", "app/services/auth_registration_admission.py", "app/services/auth_phone_otp_service.py"]:
            s = source(rel)
            self.assertNotIn("CREATE TABLE", s)
            self.assertNotIn("create_async_engine", s)
            self.assertNotIn("ensure_two_factor_schema", s)


if __name__ == "__main__":
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
        unittest.main(verbosity=2)
