"""Explicit offline allowlist runner. No pytest/conftest/app startup/env loading."""
import ast
from pathlib import Path
import re
import runpy
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def main():
    total, failed = 0, 0
    for name in ["test_auth_phase7c1_foundation.py", "test_auth_phase7c2_local.py"]:
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tests" / name)],
                                cwd=ROOT, text=True, capture_output=True)
        output = result.stdout + result.stderr
        match = re.search(r"Ran (\d+) tests", output)
        count = int(match.group(1)) if match else 0
        total += count
        print(f"{name}: {count} tests; {'PASS' if result.returncode == 0 else 'FAIL'}")
        if result.returncode:
            print(output)
            failed += 1
    # These files contain only AST/read-only and isolated exact-age tests.
    for name in ["test_signup_phone_otp_contract.py", "test_auth_foundation_contract.py",
                 "test_family_phase1a_age_foundation.py"]:
        scope = runpy.run_path(str(ROOT / "tests" / name), run_name="offline_contract")
        functions = [(n, f) for n, f in scope.items() if n.startswith("test_") and callable(f)]
        for n, f in functions:
            try:
                f()
            except Exception as exc:
                print(f"FAIL {name}:{n}: {type(exc).__name__}: {exc}")
                failed += 1
        total += len(functions)
        print(f"{name}: executed {len(functions)} source/unit contracts")

    # Verify the high-risk compatibility helpers against the local Git parent.
    before = subprocess.check_output(["git", "show", "HEAD:backend/app/api/auth.py"], cwd=ROOT).decode("utf-8")
    after = (ROOT / "app/api/auth.py").read_text(encoding="utf-8")
    def funcs(s):
        return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(s).body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    old, new = funcs(before), funcs(after)
    protected = ["_issue_local_session_response", "_claim_local_refresh_once", "refresh",
                 "_store_local_password_reset", "_consume_local_password_reset",
                 "_local_register", "_cognito_register", "logout", "get_me"]
    for name in protected:
        if old[name] != new[name]:
            print(f"FAIL protected helper changed: {name}")
            failed += 1
    print(f"Protected existing auth helper comparison: {len(protected)} checked")

    files = ["app/api/auth.py", "app/api/phone_auth.py", "app/api/google_auth.py", "app/api/users.py",
             "app/core/rate_limiter.py", "app/core/otp_rate_limit.py", "app/schemas/user.py",
             "app/services/user_service.py", "app/services/auth_otp_service.py",
             "app/services/auth_phone_otp_service.py", "app/services/auth_registration_admission.py",
             "tests/test_signup_phone_otp_contract.py", "tests/test_auth_foundation_contract.py",
             "tests/test_family_phase1a_age_foundation.py", "tests/test_auth_phase7c2_local.py",
             "tests/run_auth_phase7c2_safe.py"]
    for rel in files:
        compile((ROOT / rel).read_text(encoding="utf-8"), rel, "exec")
    print(f"In-memory Python syntax compilation: {len(files)} files PASS; no bytecode written")
    print(f"Local tests executed: {total}; failing cases/processes: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
        raise SystemExit(main())
