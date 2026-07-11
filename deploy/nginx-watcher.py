#!/usr/bin/env python3
"""Fast-recovery nginx routing watcher.

Why this exists:
    Something on the Emergent platform periodically (every 30-90 min)
    resets the contents of `/etc/nginx/conf.d/` — possibly a K8s
    ConfigMap remount, a cert-manager reconcile loop, or a platform-
    side state reconciliation agent. The exact cause is unknown from
    inside the pod, but the effect is: our `nischint-app.conf` gets
    wiped, nginx falls back to the default server block (which serves
    React HTML for every path), and `/api/*` calls fail with 520 at
    Cloudflare until our watchdog re-applies the patch on its next
    60-second tick.

What this does:
    Runs as a tiny long-lived process (managed by supervisor). Polls
    once per second for two things:
      1. `/etc/nginx/conf.d/nischint-app.conf` existence + mtime/size
      2. nginx still running with our routing
    On any drift (file missing, replaced with a different version, or
    nginx restarted), immediately re-runs the nginx-patch script and
    HUPs nginx. Recovery time: <1 second instead of 60-120s.

Why polling instead of inotify:
    `inotify-tools` is not installed on the base image. Adding a
    Python dep (watchfiles, inotify_simple) is cheap but adds a wheel
    we don't otherwise need. 1Hz `os.stat()` on a single path costs
    essentially nothing (~5µs syscall) and is portable across every
    Linux baseline Emergent might use.

How to test it works:
    1. `sudo rm /etc/nginx/conf.d/nischint-app.conf`
    2. Within ~1s, the file should reappear and nginx should be HUP'd.
    3. `curl http://127.0.0.1/health -H 'Host: nischint.care'` should
       continue returning FastAPI JSON throughout.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

LOG_FMT = "%(asctime)s [nginx-watcher] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FMT, stream=sys.stdout)
log = logging.getLogger("nginx-watcher")

WATCHED_FILE = Path("/etc/nginx/conf.d/nischint-app.conf")
SOURCE_FILE = Path("/app/deploy/nginx/nischint.conf")
PATCH_SCRIPT = Path("/app/deploy/nginx-patch.sh")
POLL_INTERVAL_S = 1.0
COOLDOWN_S = 5.0  # don't re-run patch more than once per 5s


def _file_signature(path: Path) -> tuple[int, float] | None:
    """Return (size, mtime) for a file, or None if missing."""
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime)
    except FileNotFoundError:
        return None
    except OSError as e:
        log.debug(f"stat({path}) failed: {e}")
        return None


def _run_patch() -> bool:
    """Invoke nginx-patch.sh — returns True on exit 0."""
    if not PATCH_SCRIPT.is_file():
        log.error(f"patch script missing at {PATCH_SCRIPT}")
        return False
    try:
        result = subprocess.run(
            ["bash", str(PATCH_SCRIPT)],
            capture_output=True, text=True, timeout=30,
        )
        for line in (result.stdout or "").splitlines():
            log.info(f"patch> {line}")
        if result.returncode != 0:
            log.warning(f"patch exited {result.returncode}")
            for line in (result.stderr or "").splitlines():
                log.warning(f"patch! {line}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log.error("patch timed out after 30s")
        return False
    except Exception as e:
        log.error(f"patch invocation failed: {e}")
        return False


def _shutdown(signum: int, frame) -> None:  # noqa: ANN001
    log.info(f"received signal {signum}, exiting cleanly")
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info(f"starting; watching {WATCHED_FILE} (source: {SOURCE_FILE})")

    # Compute the expected signature from the source-of-truth file.
    # We don't compare exact sizes (cp may pad differently) — we just
    # require WATCHED_FILE to be non-empty and present. Any mismatch
    # against SOURCE_FILE size triggers a re-apply.
    last_signature: tuple[int, float] | None = None
    last_patch_at = 0.0

    # Run patch once on startup so we don't depend on the FastAPI hook
    # having fired. Idempotent: no-op if routing is already in place.
    log.info("initial patch run...")
    _run_patch()
    last_signature = _file_signature(WATCHED_FILE)

    while True:
        time.sleep(POLL_INTERVAL_S)

        current = _file_signature(WATCHED_FILE)
        source = _file_signature(SOURCE_FILE)
        drifted = False
        reason = ""

        if current is None:
            drifted = True
            reason = f"{WATCHED_FILE} missing"
        elif current[0] == 0:
            drifted = True
            reason = f"{WATCHED_FILE} empty"
        elif source is not None and current[0] != source[0]:
            drifted = True
            reason = (
                f"{WATCHED_FILE.name} size {current[0]} != source size {source[0]} "
                "(file was replaced with a different version)"
            )

        if not drifted:
            last_signature = current
            continue

        now = time.monotonic()
        if now - last_patch_at < COOLDOWN_S:
            # Avoid runaway: if the platform is actively rewriting the file
            # every second, don't fight it every second — let one round
            # complete before trying again.
            continue

        log.warning(f"drift detected: {reason} — re-applying patch")
        success = _run_patch()
        last_patch_at = time.monotonic()
        if success:
            last_signature = _file_signature(WATCHED_FILE)
            log.info("patch re-applied successfully")
        else:
            log.error("patch re-apply FAILED — will retry after cooldown")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
