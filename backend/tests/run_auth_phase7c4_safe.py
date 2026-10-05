"""Explicit Phase 7C-4 offline regression runner.

No pytest collection, app startup, database, Redis, provider, cloud, or network.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
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
        env=os.environ.copy(),
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

    # Reuse the validated 7C-3 runner so 7C-1/2/3 stay frozen and regression-checked.
    prior = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tests" / "run_auth_phase7c3_safe.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    prior_output = prior.stdout + prior.stderr
    match = re.search(r"Local tests/contracts executed: (\d+); failing cases/processes: (\d+)", prior_output)
    if match:
        prior_count = int(match.group(1))
        prior_failed = int(match.group(2))
    else:
        prior_count = 0
        prior_failed = 1 if prior.returncode else 0
    total += prior_count
    failed += prior_failed
    print(f"Phase 7C-1/2/3 regression runner: {prior_count} tests/contracts; {'PASS' if prior.returncode == 0 else 'FAIL'}")
    if prior.returncode:
        print(prior_output)

    count, failures = run_file("test_auth_phase7c4_local.py")
    total += count
    failed += failures

    compile_files = (
        "app/api/emergency.py",
        "app/api/sos.py",
        "app/api/sos_auth.py",
        "app/services/auth_sos_credential_service.py",
        "tests/test_auth_phase7c4_local.py",
        "tests/run_auth_phase7c4_safe.py",
    )
    for rel in compile_files:
        compile((ROOT / rel).read_text(encoding="utf-8"), rel, "exec")
    print(f"In-memory Python syntax compilation: {len(compile_files)}/{len(compile_files)} PASS")

    config = (ROOT / "app/core/config.py").read_text(encoding="utf-8")
    if "jwt_expires_minutes: int = Field(default=15" not in config:
        print("FAIL: 7C-3 15-minute access-token source policy is missing")
        failed += 1
    else:
        print("7C-3 15-minute access policy: PRESERVED")

    migrations = list((ROOT / "migrations" / "versions").glob("*.py"))
    unexpected = [
        p.name for p in migrations
        if p.name.casefold().startswith("auth06")
        or "phase7c4" in p.name.casefold()
        or "phase_7c4" in p.name.casefold()
    ]
    if unexpected:
        print("FAIL: unexpected 7C-4 migration(s):", unexpected)
        failed += 1
    else:
        print("7C-4 schema delta: NONE")

    print(f"Local tests/contracts executed: {total}; failing cases/processes: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")), \
         patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
        raise SystemExit(main())
