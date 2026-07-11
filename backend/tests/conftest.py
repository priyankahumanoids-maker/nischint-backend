"""Pytest configuration shared across the backend test suite.

Currently registers the `live_pg` marker so end-to-end tests that
require the Neon Postgres connection (e.g. NISCH-007 E2E, the timeline
endpoint live tests) can be filtered with:

    pytest -m live_pg              # run only live-PG tests
    pytest -m "not live_pg"        # skip them in sqlite-only CI runs

Tests opt in by adding `pytestmark = pytest.mark.live_pg` to the file.
Without this registration, pytest emits a warning on every run.
"""
import os
import pathlib


def _bootstrap_frontend_env() -> None:
    """Make `REACT_APP_BACKEND_URL` (and friends) visible to backend
    tests that hit the live preview URL via `requests`.

    Several integration tests (`test_sequential_escalation_engine.py`,
    `test_guardian_escalation.py`) call `requests.post(f"{BASE_URL}/api/...")`
    where `BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "")`.
    That env var is canonical in `/app/frontend/.env` but pytest
    invoked from `/app/backend` doesn't see it by default — every
    such test fails with `MissingSchema: Invalid URL '/api/...'`.

    This bootstrap reads `frontend/.env` once at collection time so
    integration tests share the same backend URL the deployed app
    uses. Backend-canonical vars in `backend/.env` are NOT overridden
    (that would break the precedence model)."""
    fe_env = pathlib.Path(__file__).resolve().parents[2] / "frontend" / ".env"
    if not fe_env.exists():
        return
    for raw in fe_env.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        # Only seed if the var isn't already present — backend/.env wins.
        if k and k not in os.environ:
            os.environ[k] = v.strip()


_bootstrap_frontend_env()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_pg: tests that require the live Neon Postgres connection",
    )
