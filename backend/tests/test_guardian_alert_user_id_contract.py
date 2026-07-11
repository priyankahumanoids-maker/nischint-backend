"""Regression: every GuardianAlert(...) construction MUST set user_id.

Background: `guardian_alerts.user_id` is NOT NULL at the DB layer
(see migration policy + `app/models/guardian.py`). Five service-layer
sites historically constructed `GuardianAlert(...)` without
`user_id`, relying on a try/except higher up to swallow the resulting
IntegrityError. Effect: push + SSE fired (guardian saw the alert),
but the audit row was rolled back. Operators lost forensic replay.

This test sweeps every `GuardianAlert(` construction site in
`app/` and asserts that `user_id=` appears within a small window
of the call. It is intentionally a *source-level* test: any new
caller that forgets `user_id` will fail CI before a corrupt
deployment ships.
"""
from __future__ import annotations

import re
import pathlib

import pytest

# All in-tree sites that construct a GuardianAlert. The audit log
# (line numbers may drift) is captured below for review-trail clarity.
_TRACKED_FILES = [
    "app/api/child.py",
    "app/services/voice_distress_service.py",
    "app/services/checkin_service.py",
    "app/services/demo_engine.py",
    "app/services/auto_escalation_engine.py",
    "app/services/guardian_mode_engine.py",
    "app/services/night_guardian_engine.py",
    "app/services/alert_trigger.py",
]

# Acceptable forms — every direct GuardianAlert(...) must include
# `user_id=` somewhere inside the constructor call.
_CALL_RE = re.compile(r"\bGuardianAlert\(", re.MULTILINE)


def _iter_calls(text: str):
    """Yield (line_no, full_call_text) for every GuardianAlert(...) call.

    Naive parenthesis matcher — fine for the kwargs-only style used
    in this codebase."""
    for m in _CALL_RE.finditer(text):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            continue
        call = text[m.start(): i + 1]
        line_no = text[: m.start()].count("\n") + 1
        yield line_no, call


@pytest.mark.parametrize("rel_path", _TRACKED_FILES)
def test_every_guardian_alert_construction_passes_user_id(rel_path):
    """Source-level audit: any `GuardianAlert(...)` call inside the
    tracked files MUST include a `user_id=` keyword argument.

    Excludes the model definition itself (`app/models/guardian.py`)
    and test files. Subclasses or aliases are not in scope — adding
    one would require updating this audit."""
    root = pathlib.Path(__file__).resolve().parents[1]
    path = root / rel_path
    assert path.exists(), f"audit target missing: {path}"
    text = path.read_text()
    calls = list(_iter_calls(text))
    assert calls, (
        f"{rel_path}: expected at least one GuardianAlert(...) "
        f"construction; found none (audit list out of date?)"
    )
    failing = [
        (line_no, call.split('\n', 1)[0])
        for line_no, call in calls
        if "user_id=" not in call
    ]
    assert not failing, (
        f"{rel_path}: GuardianAlert(...) calls missing `user_id=` "
        f"would silently fail the NOT NULL constraint and lose audit "
        f"rows even though push/SSE already fired.\n"
        f"Offending lines: {failing}"
    )
