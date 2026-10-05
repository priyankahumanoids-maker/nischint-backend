"""Explicit Phase 7C-3 offline regression runner.

No pytest collection, app startup, database, Redis, provider, cloud, or network.
"""
from __future__ import annotations

from pathlib import Path
import re
import runpy
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def run_file(name: str) -> tuple[int, int]:
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tests" / name)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    output = result.stdout + result.stderr
    match = re.search(r"Ran (\d+) tests", output)
    count = int(match.group(1)) if match else 0
    print(f"{name}: {count} tests; {'PASS' if result.returncode == 0 else 'FAIL'}")
    if result.returncode:
        print(output)
    return count, 0 if result.returncode == 0 else 1


def main() -> int:
    total = 0
    failed = 0

    for name in (
        "test_auth_phase7c1_foundation.py",
        "test_auth_phase7c2_local.py",
        "test_auth_phase7c3_local.py",
    ):
        count, failures = run_file(name)
        total += count
        failed += failures

    for name in (
        "test_signup_phone_otp_contract.py",
        "test_auth_foundation_contract.py",
        "test_family_phase1a_age_foundation.py",
    ):
        scope = runpy.run_path(str(ROOT / "tests" / name), run_name="offline_contract")
        funcs = [(n, f) for n, f in scope.items() if n.startswith("test_") and callable(f)]
        local_failed = 0
        for test_name, func in funcs:
            try:
                func()
            except Exception as exc:
                local_failed += 1
                failed += 1
                print(f"FAIL {name}:{test_name}: {type(exc).__name__}: {exc}")
        total += len(funcs)
        print(f"{name}: {len(funcs)} source/unit contracts; {'PASS' if local_failed == 0 else 'FAIL'}")

    compile_files = (
        "app/core/config.py",
        "app/core/security.py",
        "app/services/auth_session_service.py",
        "app/api/auth.py",
        "app/api/phone_auth.py",
        "app/services/auth_phone_otp_service.py",
        "tests/test_auth_phase7c3_local.py",
        "tests/run_auth_phase7c3_safe.py",
    )
    for rel in compile_files:
        compile((ROOT / rel).read_text(encoding="utf-8"), rel, "exec")
    print(f"In-memory Python syntax compilation: {len(compile_files)}/{len(compile_files)} PASS")

    # Source-only deployment guard: shorter ordinary access tokens are not
    # authorization to deploy before the independent 7C-4 SOS auth path exists.
    config = (ROOT / "app/core/config.py").read_text(encoding="utf-8")
    if "jwt_expires_minutes: int = Field(default=15" not in config:
        print("FAIL: 15-minute source access-token default missing")
        failed += 1

    migrations = list((ROOT / "migrations" / "versions").glob("*.py"))
    unexpected = [
        p.name
        for p in migrations
        if p.name.casefold().startswith("auth06")
        or "phase7c3" in p.name.casefold()
        or "phase_7c3" in p.name.casefold()
    ]
    if unexpected:
        print("FAIL: unexpected 7C-3 migration(s):", unexpected)
        failed += 1
    else:
        print("7C-3 schema delta: NONE")

    print(f"Local tests/contracts executed: {total}; failing cases/processes: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
        raise SystemExit(main())
