from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "app" / "api" / "auth.py"
OTP = ROOT / "app" / "services" / "auth_otp_service.py"


def src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_signup_phone_otp_routes_compile_and_are_rate_limited():
    source = src(AUTH)
    ast.parse(source)
    assert '@router.post("/signup-phone/request", status_code=status.HTTP_202_ACCEPTED)' in source
    assert '@router.post("/signup-phone/verify")' in source
    assert '@limiter.limit("5/minute")' in source
    assert '@limiter.limit("10/minute")' in source


def test_signup_otp_reuses_hashed_durable_store_and_never_returns_code():
    source = src(AUTH)
    otp = src(OTP)
    assert 'SIGNUP_PHONE_OTP_PURPOSE = "signup_phone"' in source
    assert 'SIGNUP_PHONE_VERIFIED_PURPOSE = "signup_phone_verified"' in source
    assert 'store_otp(' in source and 'consume_otp(' in source
    assert 'code_digest' in otp and 'hmac.compare_digest' in otp
    request_start = source.index('async def request_signup_phone_otp(')
    verify_start = source.index('async def verify_signup_phone_otp(')
    request_block = source[request_start:verify_start]
    verify_block = source[verify_start:source.index('@router.post("/register"', verify_start)]
    assert 'sms_service.send_sms' in request_block
    assert 'await asyncio.to_thread' in request_block
    assert '"code": code' not in request_block
    assert '"code": req.code' not in verify_block
    assert 'secrets.token_urlsafe(32)' in verify_block


def test_verified_ticket_is_one_time_and_bound_to_normalized_phone_identity():
    source = src(AUTH)
    assert 'return f"signup-phone:{normalized_phone}"' in source
    consume_at = source.index('async def _consume_signup_phone_verification(')
    request_at = source.index('@router.post("/check-phone")', consume_at)
    block = source[consume_at:request_at]
    assert 'X-Signup-Phone-Verification' in block
    assert 'consume_otp(' in block
    assert 'SIGNUP_PHONE_VERIFIED_PURPOSE' in block


def test_both_registration_paths_require_verified_phone_ticket():
    source = src(AUTH)
    register_at = source.index('async def register(')
    login_at = source.index('@router.post("/login"', register_at)
    register_block = source[register_at:login_at]
    assert '_consume_signup_phone_verification(session, request, normalized_phone)' in register_block

    invite_at = source.index('async def verify_invite_code(')
    guardian_at = source.index('# â”€â”€ My Guardian', invite_at)
    invite_block = source[invite_at:guardian_at]
    assert '_consume_signup_phone_verification(session, request, normalized_phone)' in invite_block


def test_no_plaintext_signup_otp_schema_was_added():
    source = src(AUTH)
    assert 'CREATE TABLE' not in source[source.index('SIGNUP_PHONE_OTP_PURPOSE'):source.index('def _claim_local_refresh_once')]
    assert 'auth_signup_phone' not in source
