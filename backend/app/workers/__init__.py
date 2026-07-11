"""Worker entrypoints for out-of-API processes.

Currently:
  • scheduler_runner — APScheduler jobs only (NISCHINT_ROLE=scheduler)

Phase 2 will add ai_worker for LiteLLM inference isolation.
"""
