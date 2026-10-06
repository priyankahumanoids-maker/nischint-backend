"""Explicit offline F03-F06 + three requested regression modules; no pytest discovery."""
from pathlib import Path
import importlib.util
import inspect
import itertools
import socket
import sys
import traceback
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pytest


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def execute(module):
    passed = failed = 0
    for name, fn in vars(module).items():
        if not name.startswith("test_") or not inspect.isfunction(fn):
            continue
        cases = [{}]
        for mark in getattr(fn, "pytestmark", []):
            if mark.name != "parametrize":
                raise AssertionError("Unsupported test mark: " + mark.name)
            names, values = mark.args[:2]
            names = [s.strip() for s in names.split(",")] if isinstance(names, str) else names
            expanded = []
            for case, value in itertools.product(cases, values):
                value = (value,) if len(names) == 1 else value
                expanded.append({**case, **dict(zip(names, value))})
            cases = expanded
        for case in cases:
            monkeypatch = pytest.MonkeyPatch()
            try:
                if "monkeypatch" in inspect.signature(fn).parameters:
                    case["monkeypatch"] = monkeypatch
                fn(**case)
                passed += 1
            except Exception:
                failed += 1
                print("FAIL:", name)
                traceback.print_exc(limit=3)
            finally:
                monkeypatch.undo()
    print(f"{Path(module.__file__).name}: {passed}/{passed + failed} PASS")
    return passed, failed


def main():
    # Block accidental environment/DB loading before any application code.
    class NoInfrastructure:
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(("app.db", "app.core.config", "psycopg", "asyncpg")):
                raise AssertionError("Forbidden infrastructure import: " + fullname)
    sys.meta_path.insert(0, NoInfrastructure())
    def no_network(*args, **kwargs):
        raise AssertionError("Network unavailable in offline source tests")
    original_connect = socket.socket.connect
    def guarded_connect(sock, address):
        # Windows asyncio implements its internal wakeup pipe with socketpair.
        caller = sys._getframe(1).f_code
        if (caller.co_name == "socketpair" and caller.co_filename == socket.__file__
                and address[0] in {"127.0.0.1", "::1"}):
            return original_connect(sock, address)
        return no_network()
    with patch.object(socket.socket, "connect", guarded_connect), patch.object(socket, "create_connection", no_network):
        target = load(ROOT / "tests/test_family_phase7c6a_core.py", "phase7c6a_tests")
        target.bootstrap()
        passed, failed = execute(target)
        print(f"TARGETED: {passed}/{passed + failed}")
        regression_pass = regression_fail = 0
        for filename in (
            "test_family_phase5_safety_integration.py",
            "test_family_phase3_consent_minor_authority.py",
            "test_phase7ab_boundaries.py",
        ):
            module = load(ROOT / "tests" / filename, "offline_" + filename[:-3])
            p, f = execute(module)
            regression_pass += p
            regression_fail += f
        print(f"REGRESSION: {regression_pass}/{regression_pass + regression_fail}")
        for rel in (
            "app/services/family_circle_runtime_authority.py",
            "app/services/member_monitoring_policy.py",
            "app/services/family_circle_invite_service.py",
            "tests/test_family_phase7c6a_core.py",
            "tests/run_family_phase7c6a_safe.py",
        ):
            compile((ROOT / rel).read_text(encoding="utf-8"), rel, "exec")
        print("IN-MEMORY SYNTAX: 5/5")
        return int(bool(failed or regression_fail))


if __name__ == "__main__":
    raise SystemExit(main())
