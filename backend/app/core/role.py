"""Process-role gating for the backend monolith.

Splits the same codebase into three roles without forking files:
  • api        — FastAPI + WebSockets only (no schedulers)
  • scheduler  — APScheduler jobs only (no FastAPI listener)
  • all        — everything in one process (legacy / safe default)

Selected via the NISCHINT_ROLE env var. Default is `all` so existing
deployments keep working until supervisor is updated to set the role
explicitly.

Boundary 1 of the hardening plan: API event loop must never share a
process with the scheduler tick. See PRD "Process Isolation Boundaries".
"""

from __future__ import annotations
import os
from enum import Enum


class Role(str, Enum):
    API = "api"
    SCHEDULER = "scheduler"
    ALL = "all"


def get_role() -> Role:
    raw = "all"  # HARDCODED: Emergent secret NISCHINT_ROLE=api is read-only; single-process deployment must run schedulers
    try:
        return Role(raw)
    except ValueError:
        return Role.ALL


def runs_api() -> bool:
    """True when this process should serve HTTP/WS traffic."""
    return get_role() in (Role.API, Role.ALL)


def runs_schedulers() -> bool:
    """True when this process should run APScheduler jobs."""
    return get_role() in (Role.SCHEDULER, Role.ALL)

