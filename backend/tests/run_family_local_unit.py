"""Local unit/source tests only: no DB, network, env, subprocess or file writes.

Run with python -B tests/run_family_local_unit.py. This intentionally invokes
unit functions (including parametrization), not integration/conftest fixtures.
"""
import os
import sys
import platform
from pathlib import Path

platform.uname()
ROOT = Path(__file__).resolve().parents[1]


def guard(event, args):
    if event == "socket.connect":
        frame = sys._getframe(1)
        if frame.f_code.co_name == "socketpair" and Path(frame.f_code.co_filename).resolve() == Path(sys.base_prefix, "Lib", "socket.py").resolve():
            return
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo",
                 "os.putenv", "os.unsetenv", "subprocess.Popen",
                 "os.remove", "os.rmdir", "os.rename", "os.mkdir"}:
        raise RuntimeError("LOCAL_TEST_BLOCKED:" + event)
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0]))
        if path.name.lower().startswith(".env"):
            raise RuntimeError("LOCAL_TEST_BLOCKED:environment_file")
        mode, flags = args[1] or "", args[2] or 0
        if any(c in mode for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError("LOCAL_TEST_BLOCKED:write")


sys.addaudithook(guard)
sys.path.insert(0, str(ROOT))
import types
services = types.ModuleType("app.services")
services.__path__ = [str(ROOT / "app/services")]
sys.modules["app.services"] = services  # avoid service package startup imports
import pytest
import importlib.util
import inspect
import traceback

FILES = [
    "test_family_phase1a_age_foundation.py", "test_family_phase1b_circle_authority.py",
    "test_family_phase1c_shared_permissions.py", "test_family_phase2_plan_seat_trial.py",
    "test_signup_phone_otp_contract.py", "test_subscription_summary_hotpath_contract.py",
    "test_family_phase3_consent_minor_authority.py", "test_family_phase4_onboarding_invites.py",
    "test_family_phase5_safety_integration.py", "test_family_phase6_entitlement_lifecycle_audit.py",
    "test_phase7ab_boundaries.py",
    "test_phase7a_constraint_convergence.py",
]
passed = failed = 0
for index, name in enumerate(FILES):
    spec = importlib.util.spec_from_file_location("local_family_test_" + str(index), ROOT / "tests" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for test_name, fn in inspect.getmembers(module, inspect.isfunction):
        if not test_name.startswith("test_"):
            continue
        cases = [{}]
        for mark in getattr(fn, "pytestmark", []):
            if mark.name != "parametrize":
                raise RuntimeError("Unsupported test marker: " + mark.name)
            names = [value.strip() for value in mark.args[0].split(",")]
            cases = [dict(case, **dict(zip(names, [values] if len(names) == 1 else values)))
                     for case in cases for values in mark.args[1]]
        for case in cases:
            try:
                with pytest.MonkeyPatch.context() as mp:
                    if "monkeypatch" in inspect.signature(fn).parameters:
                        case["monkeypatch"] = mp
                    fn(**case)
                passed += 1
            except Exception:
                failed += 1
                print("FAIL", name, test_name)
                traceback.print_exc()
print(f"LOCAL FAMILY UNIT/SOURCE: passed={passed} failed={failed}")
raise SystemExit(bool(failed))
