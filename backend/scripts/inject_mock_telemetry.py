"""
inject_mock_telemetry.py — Mock Telemetry Injector for NISCHINT AI Brain

Activates the entire pipeline end-to-end by simulating 60 seconds of
realistic multi-user telemetry:
    • Location/GPS trail for 3 personas (child/mother/admin) — Mumbai area
    • Sensor signals (battery, activity, network) via AI Brain directly
    • Contextual risk scoring via /api/journey/risk/score
    • One medium-risk event for the child user (risk ≈ 0.6, NOT a full SOS)

Runs for 60 s (DURATION_SEC), posting once every 5 s (INTERVAL_SEC).

NO AUTH REQUIRED — the journey endpoints operate by session_id / user_id
which is the production shape of the mobile client. Auth-gated endpoints
are deliberately avoided.

Usage:
    cd /app/backend
    python scripts/inject_mock_telemetry.py

    # Override backend URL (default: REACT_APP_BACKEND_URL from frontend/.env)
    API_URL=https://example.com python scripts/inject_mock_telemetry.py

    # Shorter run for quick tests
    DURATION_SEC=20 INTERVAL_SEC=3 python scripts/inject_mock_telemetry.py
"""
from __future__ import annotations

import math
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

# ── Config ─────────────────────────────────────────────────────────

DURATION_SEC = int(os.environ.get("DURATION_SEC", "60"))
INTERVAL_SEC = int(os.environ.get("INTERVAL_SEC", "5"))
RISK_SPIKE_AT_SEC = int(os.environ.get("RISK_SPIKE_AT_SEC", "20"))  # inject medium-risk event after 20s

# Mumbai base coords
BASE_LAT = 19.0760
BASE_LNG = 72.8777


def _load_api_url() -> str:
    env = os.environ.get("API_URL") or os.environ.get("REACT_APP_BACKEND_URL")
    if env:
        return env.rstrip("/")
    # Fallback: read /app/frontend/.env
    env_path = Path("/app/frontend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    return "http://localhost:8001"


API_URL = _load_api_url()

# Persona definitions (session_id uniquely identifies each telemetry source,
# which journey_sync + ai_brain keys all state on)
PERSONAS: List[Dict[str, Any]] = [
    {
        "name": "child",
        "email": "kidnischint@gmail.com",
        "session_id": "sess_child_mock",
        "user_id": "user_child_mock",
        "user_type": "child",
        "mode": "moving",       # wanders around Mumbai
        "base_lat": BASE_LAT,
        "base_lng": BASE_LNG,
        "speed_mps": 1.3,        # walking speed
    },
    {
        "name": "mother",
        "email": "mothernischint@gmail.com",
        "session_id": "sess_mother_mock",
        "user_id": "user_mother_mock",
        "user_type": "adult",
        "mode": "stationary",    # at home
        "base_lat": BASE_LAT + 0.0120,   # ~1.3 km north
        "base_lng": BASE_LNG + 0.0080,
        "speed_mps": 0.0,
    },
    {
        "name": "admin",
        "email": "nischint4parents@gmail.com",
        "session_id": "sess_admin_mock",
        "user_id": "user_admin_mock",
        "user_type": "adult",
        "mode": "stationary",    # at office
        "base_lat": BASE_LAT - 0.0080,   # ~0.9 km south
        "base_lng": BASE_LNG + 0.0200,
        "speed_mps": 0.0,
    },
]


# ── Metrics ────────────────────────────────────────────────────────

class Counters:
    location_ok = 0
    location_err = 0
    signals_ok = 0
    signals_err = 0
    risk_ok = 0
    risk_err = 0
    brain_ok = 0
    brain_err = 0
    spike_fired = False
    final_risk_scores: Dict[str, Dict[str, Any]] = {}


# ── Helpers ────────────────────────────────────────────────────────

def _jitter_coords(persona: Dict[str, Any], tick: int) -> Dict[str, float]:
    """
    Moving persona: walks in a small circle so the trail looks natural.
    Stationary persona: tiny ±2m GPS noise (realistic phone drift).
    """
    if persona["mode"] == "moving":
        # 0.0001° lat ≈ 11 m → tick creates a slow orbit
        angle = (tick * 0.35) % (2 * math.pi)
        radius = 0.0006 + random.random() * 0.0002   # ~60–80 m radius
        lat = persona["base_lat"] + radius * math.sin(angle)
        lng = persona["base_lng"] + radius * math.cos(angle)
    else:
        lat = persona["base_lat"] + (random.random() - 0.5) * 0.00004
        lng = persona["base_lng"] + (random.random() - 0.5) * 0.00004
    return {"lat": round(lat, 6), "lng": round(lng, 6)}


def _post(path: str, payload: Dict[str, Any], timeout: float = 6.0) -> tuple[bool, Any]:
    try:
        r = requests.post(f"{API_URL}{path}", json=payload, timeout=timeout)
        if r.status_code < 400:
            return True, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ── 1. Location + sync events ──────────────────────────────────────

def post_location_sync(persona: Dict[str, Any], coords: Dict[str, float], tick: int) -> None:
    """
    Post a location update as a 'location' sync event. This is the shape the
    mobile client sends via POST /api/journey/sync.
    """
    event = {
        "id": f"loc_{persona['session_id']}_{tick}",
        "type": "location",
        "priority": "low",
        "createdAt": int(time.time() * 1000),
        "payload": {
            "session_id": persona["session_id"],
            "user_id": persona["user_id"],
            "lat": coords["lat"],
            "lng": coords["lng"],
            "accuracy_m": round(5 + random.random() * 10, 1),
            "speed_mps": persona["speed_mps"] + random.random() * 0.3,
            "heading_deg": round(random.random() * 360, 1),
            "ts": int(time.time() * 1000),
        },
    }
    ok, _ = _post("/api/journey/sync", {"events": [event]})
    if ok:
        Counters.location_ok += 1
    else:
        Counters.location_err += 1


# ── 2. Sensor signals — via AI Brain + risk/score (combined path) ──

def post_sensor_signals(persona: Dict[str, Any], coords: Dict[str, float], tick: int) -> Dict[str, Any] | None:
    """
    Push device telemetry through the AI Brain. The brain is the single
    entry point that fuses GPS + motion + device into a decision, which is
    exactly what a real device would do every tick.

    Returns the brain decision dict (or None on error).
    """
    motion = "still" if persona["mode"] == "stationary" else "walk"
    payload = {
        "user_id": persona["user_id"],
        "user_type": persona["user_type"],
        "signals": {
            "gps": {"lat": coords["lat"], "lng": coords["lng"], "accuracy_m": 6.0},
            "motion": {
                "activity": motion,
                "accel_magnitude": 9.81 + (random.random() - 0.5) * 0.6,
                "idle_sec": 0 if motion == "walk" else random.randint(10, 60),
            },
            "device": {
                "battery": 0.75 + (random.random() - 0.5) * 0.05,   # 72–78%
                "network": True,
                "app_state": "active",
            },
            "time": {"hour": time.localtime().tm_hour},
        },
        "skip_behavior": True,
        "auto_execute": True,
    }
    ok, resp = _post("/api/ai-brain/decide", payload, timeout=8.0)
    if ok:
        Counters.brain_ok += 1
        Counters.signals_ok += 1
        if isinstance(resp, dict):
            Counters.final_risk_scores[persona["name"]] = {
                "risk_score": resp.get("risk_score"),
                "risk_level": resp.get("risk_level"),
                "recommended_action": resp.get("recommended_action"),
            }
            return resp
    else:
        Counters.brain_err += 1
        Counters.signals_err += 1
        print(f"  [brain-err] {persona['name']}: {resp}")
    return None


# ── 3. Contextual risk score (additional path — the legacy engine) ──

def post_risk_score(persona: Dict[str, Any], coords: Dict[str, float], idle_ms: int = 0) -> None:
    payload = {
        "session_id": persona["session_id"],
        "location": {"lat": coords["lat"], "lng": coords["lng"]},
        "idle_ms": idle_ms,
        "is_moving": persona["mode"] == "moving",
        "speed": persona["speed_mps"] * 3.6,
        "battery": 0.75,
        "network": "online",
        "anomaly_count": 0,
        "sos_active": False,
    }
    ok, _ = _post("/api/journey/risk/score", payload)
    if ok:
        Counters.risk_ok += 1
    else:
        Counters.risk_err += 1


# ── 4. Medium-risk spike for the child (fires ONCE at ~20s mark) ───

def trigger_medium_risk_spike() -> Dict[str, Any] | None:
    """
    Inject a medium-risk signal for the child — panic keyword + still motion +
    late-night simulated hour. Expected brain output: risk ≈ 55–70, level
    YELLOW/RED, action NOTIFY_GUARDIAN or INCREASE_MONITORING.
    This is NOT a full SOS — just elevated telemetry to verify escalation
    pipeline responds.
    """
    child = next(p for p in PERSONAS if p["name"] == "child")
    payload = {
        "user_id": child["user_id"],
        "user_type": "child",
        "signals": {
            "gps": {"lat": child["base_lat"], "lng": child["base_lng"]},
            "voice": {
                "amplitude": 0.72,
                "stress_score": 0.65,
                "keyword_flag": False,  # NOT a full panic keyword — just elevated
            },
            "motion": {"activity": "still", "idle_sec": 180, "accel_magnitude": 9.5},
            "device": {"battery": 0.68, "network": True, "app_state": "active"},
            "time": {"hour": 22},  # late-ish
        },
        "skip_behavior": True,
        "auto_execute": False,  # preview-only: do NOT fire guardians on the real world
    }
    ok, resp = _post("/api/ai-brain/decide", payload, timeout=8.0)
    Counters.spike_fired = ok
    return resp if ok else None


# ── Main ───────────────────────────────────────────────────────────

def main() -> int:
    print(f"━━━ NISCHINT Mock Telemetry Injector ━━━")
    print(f"  API:       {API_URL}")
    print(f"  Duration:  {DURATION_SEC}s   Interval: {INTERVAL_SEC}s")
    print(f"  Personas:  {', '.join(p['name'] for p in PERSONAS)}")
    print(f"  Spike at:  T+{RISK_SPIKE_AT_SEC}s (child medium-risk)")
    print()

    # Pre-flight: health check
    try:
        h = requests.get(f"{API_URL}/api/health", timeout=5)
        if h.status_code != 200:
            print(f"✗ Health check failed: HTTP {h.status_code}")
            return 1
    except Exception as e:
        print(f"✗ Backend unreachable: {e}")
        return 1
    print(f"✓ Backend /api/health OK\n")

    start = time.time()
    tick = 0
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= DURATION_SEC:
            break
        tick += 1
        print(f"[T+{elapsed:>2}s  tick#{tick:>2}] injecting telemetry…", flush=True)

        for persona in PERSONAS:
            coords = _jitter_coords(persona, tick)
            post_location_sync(persona, coords, tick)
            post_sensor_signals(persona, coords, tick)
            post_risk_score(persona, coords)

        # Fire the medium-risk spike once at T+RISK_SPIKE_AT_SEC
        if not Counters.spike_fired and elapsed >= RISK_SPIKE_AT_SEC:
            print(f"  ↳ firing medium-risk spike for child user…")
            spike = trigger_medium_risk_spike()
            if spike:
                print(
                    f"  ↳ spike response: risk={spike.get('risk_score')} "
                    f"level={spike.get('risk_level')} action={spike.get('recommended_action')}"
                )

        sleep_for = max(0, INTERVAL_SEC - (time.time() - start - elapsed))
        time.sleep(sleep_for)

    # ── Summary ────────────────────────────────────────────────────
    print()
    print("━━━ Injection complete ━━━")
    print(f"  Duration actual:        {int(time.time() - start)}s over {tick} ticks")
    print(f"  Location events sent:   {Counters.location_ok} ok, {Counters.location_err} err")
    print(f"  Sensor signals sent:    {Counters.signals_ok} ok, {Counters.signals_err} err  (via AI Brain)")
    print(f"  Risk scores sent:       {Counters.risk_ok} ok, {Counters.risk_err} err")
    print(f"  AI Brain decisions:     {Counters.brain_ok}")
    print(f"  Medium-risk spike:      {'✓ fired' if Counters.spike_fired else '✗ not fired'}")
    print()
    print("  Final risk per persona:")
    for name, s in Counters.final_risk_scores.items():
        print(f"    - {name:<7} risk={s.get('risk_score')}  level={s.get('risk_level')}  action={s.get('recommended_action')}")

    # Confirm the brain's decision log caught everything
    try:
        r = requests.get(f"{API_URL}/api/ai-brain/decisions?limit=5", timeout=5)
        if r.status_code == 200:
            decisions = r.json().get("decisions", [])
            print(f"\n  Last 5 brain decisions ({len(decisions)} returned):")
            for d in decisions:
                print(
                    f"    {d.get('decided_at', '')[:19]}  "
                    f"{d.get('user_id', '?'):<20}  "
                    f"{d.get('risk_level', '?'):<8} "
                    f"{d.get('recommended_action', '?'):<22} "
                    f"reason={(d.get('reason') or '')[:60]}…"
                )
    except Exception as e:
        print(f"\n  (could not fetch decisions: {e})")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
