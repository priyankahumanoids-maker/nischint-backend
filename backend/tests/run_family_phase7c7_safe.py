"""Focused Phase 7C-7 runner; no DB/network/application startup."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TEST = ROOT / "tests" / "test_family_phase7c7_staff_security.py"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("phase7c7_tests", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    mod = load_module(TEST)
    tests = [
        (name, value)
        for name, value in vars(mod).items()
        if name.startswith("test_") and callable(value)
    ]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"PASS | {name}")
        except Exception as exc:
            failed.append((name, exc))
            print(f"FAIL | {name} | {type(exc).__name__}: {exc}")
    print("-" * 72)
    print(f"PHASE 7C-7 STAFF SECURITY: {len(tests)-len(failed)}/{len(tests)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
