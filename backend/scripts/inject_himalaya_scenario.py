#!/usr/bin/env python3
"""SF-01 v2 Day 4 — Himalaya scenario injection CLI.

End-to-end smoke driver for the 3-phase fusion demo. Hits the live
preview backend (or any base URL passed via `--base-url`):

  1. Logs in as the operator account.
  2. Calls `POST /api/operator/dev/scenario` (himalaya_landslide).
  3. Asserts composite ≥ 0.65 and action ∈ {alert, emergency}.
  4. Re-fires within 300 s and asserts cooldown_suppressed == True.
  5. Prints a single-line green PASS / red FAIL summary.

Usage:
    python -m backend.scripts.inject_himalaya_scenario [--base-url URL]

This script is the demo gate. If anything in the fusion chain
regresses, this fails loudly. No screen-capture or fancy output —
the Command Center button (Day 4 Task 4) is the operator-facing
demo; this CLI is the QA / CI variant.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional

import httpx


# ── Defaults ─────────────────────────────────────────────────────

DEFAULT_BASE_URL = os.environ.get(
    "NISCHINT_BASE_URL",
    "https://gps-mic-restart.preview.emergentagent.com",
)
DEFAULT_OPERATOR_EMAIL = os.environ.get(
    "NISCHINT_OPERATOR_EMAIL", "operator@nischint.com",
)
DEFAULT_OPERATOR_PASSWORD = os.environ.get(
    "NISCHINT_OPERATOR_PASSWORD", "OperatorSecure!2026",
)
DEFAULT_TARGET_EMAIL = os.environ.get(
    "NISCHINT_TARGET_EMAIL", "nischint4parents@gmail.com",
)


# ── ANSI helpers ─────────────────────────────────────────────────


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m" if sys.stdout.isatty() else s


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m" if sys.stdout.isatty() else s


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if sys.stdout.isatty() else s


# ── HTTP wrapper ─────────────────────────────────────────────────


class NischintClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token: Optional[str] = None
        self.client = httpx.Client(timeout=15.0)

    def login(self, email: str, password: str) -> None:
        r = self.client.post(
            f"{self.base}/api/auth/login",
            json={"email": email, "password": password},
        )
        r.raise_for_status()
        self.token = r.json()["access_token"]

    @property
    def auth_headers(self) -> dict:
        if not self.token:
            raise RuntimeError("Not logged in")
        return {"Authorization": f"Bearer {self.token}"}

    def whoami(self) -> dict:
        r = self.client.get(
            f"{self.base}/api/auth/me", headers=self.auth_headers,
        )
        r.raise_for_status()
        return r.json()

    def fire_scenario(
        self,
        scenario: str,
        target_user_id: str,
        ttl_minutes: int = 5,
    ) -> dict:
        r = self.client.post(
            f"{self.base}/api/operator/dev/scenario",
            headers=self.auth_headers,
            json={
                "scenario":       scenario,
                "target_user_id": target_user_id,
                "ttl_minutes":    ttl_minutes,
            },
        )
        r.raise_for_status()
        return r.json()


# ── Assertions ───────────────────────────────────────────────────


def _assert(cond: bool, label: str, detail: str = "") -> bool:
    if cond:
        print(f"  {_green('✓')} {label}{(' — ' + detail) if detail else ''}")
        return True
    print(f"  {_red('✗')} {label}{(' — ' + detail) if detail else ''}")
    return False


# ── Main ─────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--target-email", default=DEFAULT_TARGET_EMAIL)
    ap.add_argument(
        "--scenario", default="himalaya_landslide",
        choices=["himalaya_landslide", "urban_flood", "cyclone_coast"],
    )
    ap.add_argument("--ttl-minutes", type=int, default=5)
    args = ap.parse_args()

    print(_bold("┏━━━ NISCHINT Himalaya Scenario Injection ━━━━━━━━━━━┓"))
    print(f"  base url        : {args.base_url}")
    print(f"  scenario        : {args.scenario}")
    print(f"  target          : {args.target_email}")
    print(f"  ttl (minutes)   : {args.ttl_minutes}")
    print(_bold("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"))

    c = NischintClient(args.base_url)

    # 1. Login as operator (also doubles as the demo viewer — the
    # target_user_id is resolved server-side from the operator's
    # account, OR explicitly via the target_email arg below).
    try:
        c.login(DEFAULT_OPERATOR_EMAIL, DEFAULT_OPERATOR_PASSWORD)
    except Exception as exc:  # noqa: BLE001
        print(_red(f"FAIL: operator login → {exc}"))
        return 2

    # 2. Resolve the target user id. Operator account is fine for
    # the demo — composite recalc fires regardless of which user_id
    # the scenario targets.
    me = c.whoami()
    target_user_id = me["id"]

    print()
    print(_bold("Phase 1 — Fire the scenario"))
    try:
        r1 = c.fire_scenario(
            args.scenario, target_user_id, args.ttl_minutes,
        )
    except httpx.HTTPStatusError as exc:
        print(_red(f"FAIL: scenario inject → HTTP {exc.response.status_code}"))
        print(_red(exc.response.text[:500]))
        return 2

    composite = float(r1["composite"])
    pre_mult  = float(r1["pre_mult_score"])
    mult      = float(r1["env_multiplier"])
    action    = r1["action"]
    print(f"  pre-mult score : {pre_mult:.3f}")
    print(f"  env multiplier : ×{mult:.2f}")
    print(f"  composite      : {composite:.3f}")
    print(f"  action         : {_bold(action.upper())}")
    print(f"  env match      : {r1['env_hazard_match']}")
    print(f"  env type       : {r1['env_hazard_type']}")

    ok = True
    ok &= _assert(r1["env_hazard_match"] is True,
                  "env_hazard_match fires",
                  f"matched={r1['env_hazard_match']}")
    ok &= _assert(abs(mult - 1.30) < 1e-6,
                  "env multiplier == 1.30",
                  f"got {mult}")
    ok &= _assert(composite >= 0.65,
                  "composite ≥ 0.65 (alert tier)",
                  f"got {composite:.3f}")
    ok &= _assert(action in ("alert", "emergency"),
                  "action ∈ {alert, emergency}",
                  f"got {action}")
    ok &= _assert(r1["alert_fired"] is True,
                  "alert_fired == True")

    print()
    print(_bold("Phase 2 — Re-fire within 300 s (cooldown check)"))
    time.sleep(2)  # any non-zero delay is fine; cooldown is keyed in Redis
    try:
        r2 = c.fire_scenario(
            args.scenario, target_user_id, args.ttl_minutes,
        )
    except httpx.HTTPStatusError as exc:
        print(_red(f"FAIL: scenario re-fire → HTTP {exc.response.status_code}"))
        return 2

    ok &= _assert(
        r2["cooldown_suppressed"] is True,
        "second fire within 300s → cooldown_suppressed",
        f"got {r2['cooldown_suppressed']}",
    )
    ok &= _assert(
        r2["composite"] >= 0.65,
        "second composite still ≥ 0.65 (math reproducible)",
        f"got {r2['composite']:.3f}",
    )

    print()
    print(_bold("Summary"))
    if ok:
        print(_green(_bold("  ✓ HIMALAYA SCENARIO PASSED — demo arc is live")))
        return 0
    print(_red(_bold("  ✗ HIMALAYA SCENARIO FAILED — see assertions above")))
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(_red("interrupted"))
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001
        print(_red(f"FATAL: {exc}"))
        import traceback
        traceback.print_exc()
        sys.exit(2)
