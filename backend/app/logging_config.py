"""Structured JSON logging configuration for production."""
import logging
import json
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line."""
    def format(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None),
            "msg": record.getMessage(),
        }
        # Merge any extra structured fields
        for key in ("user_id", "session_id", "alert_type", "status", "child_id", "guardian_id", "check_in_id", "count", "lat", "lng"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging():
    """Configure root logger with JSON formatter for production."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Remove default handlers, add JSON
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy libraries
    for name in ("apscheduler", "httpcore", "httpx", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # apscheduler's "Execution of job X skipped: maximum number of
    # running instances reached" warnings fire whenever a previous
    # run hasn't finished when the next tick is due. With
    # `max_instances=1, coalesce=True` this is the CORRECT safety
    # behavior — never stack. Logging it every time buries real
    # signal. Elevate the scheduler logger to ERROR so we only hear
    # about actual failures.
    logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)
    # slowapi emits a WARNING for every rate-limit hit ("ratelimit X
    # per Y exceeded at endpoint: ..."). Under a brute-force burst from
    # a single IP this floods the log stream and buries real signal.
    # The 429 response itself is the user-visible signal; we only want
    # to know when slowapi actually fails internally.
    logging.getLogger("slowapi").setLevel(logging.ERROR)
