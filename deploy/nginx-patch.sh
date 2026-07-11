#!/bin/bash
# NISCHINT nginx routing installer — Kubernetes / Emergent-style runtime apply.
#
# WHY THIS EXISTS (read before "fixing"):
#   - We do NOT own the Docker image build. Emergent's platform ships a
#     base image whose /etc/nginx/* is restored on every pod start.
#   - Therefore, on every fresh pod, we MUST re-establish our routing.
#   - This script is invoked from two places:
#       1. supervisor program  /etc/supervisor/conf.d/nginx_patch.conf
#       2. FastAPI startup hook in /app/backend/server.py
#     Either firing is sufficient. Both is safe (the script is idempotent).
#
# STRATEGY (most-to-least preferred):
#   A. Drop `nischint.conf` into /etc/nginx/conf.d/  → nginx auto-includes
#      it via the stock `include /etc/nginx/conf.d/*.conf;` line. NO sed.
#   B. As a fallback, sed-inject `include /app/deploy/nginx/nischint.conf;`
#      into the active nginx.conf's http{} block.
#   Either A or B is sufficient. Doing both is harmless (the server block
#   only appears once because the conf.d file points at the same file via
#   include — see Step 2A below where we use the original repo path).
#
# VERIFICATION:
#   After applying + HUP, the script self-probes
#   `curl http://127.0.0.1/health -H "Host: nischint.care"` and logs the
#   HTTP code. Any non-200 = patch failed → next watchdog tick re-runs.

set +e

APP_CONF="/app/deploy/nginx/nischint.conf"
CONFD_DST="/etc/nginx/conf.d/nischint-app.conf"
SUPERVISOR_SRC="/app/deploy/nginx_patch.conf"
SUPERVISOR_DST="/etc/supervisor/conf.d/nginx_patch.conf"

echo "[nginx-patch] === nginx-patch starting at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# --- Diagnostics (so we can debug from logs if it ever fails) ---
echo "[nginx-patch] nginx processes:"
ps -eo pid,user,args 2>/dev/null | grep -E "nginx" | grep -v grep | sed 's/^/[nginx-patch]   /' \
    || echo "[nginx-patch]   (no nginx processes yet)"

echo "[nginx-patch] /etc/nginx contents:"
ls -la /etc/nginx/ 2>/dev/null | sed 's/^/[nginx-patch]   /'
echo "[nginx-patch] /etc/nginx/conf.d contents:"
ls -la /etc/nginx/conf.d/ 2>/dev/null | sed 's/^/[nginx-patch]   /' \
    || echo "[nginx-patch]   (no /etc/nginx/conf.d)"

# --- Sanity: our source conf must exist ---
if [ ! -f "$APP_CONF" ]; then
    echo "[nginx-patch] FATAL: source conf missing at $APP_CONF — aborting"
    exit 0
fi

# === STRATEGY A: drop into /etc/nginx/conf.d/ (zero sed) ====================
# Works on every nginx whose default nginx.conf has
# `include /etc/nginx/conf.d/*.conf;` inside its http{} (which is the
# stock debian/alpine/ubuntu/nginx-official layout).
if [ -d /etc/nginx/conf.d ]; then
    # We copy the file (not symlink) so it survives even if /app is unmounted
    # mid-deploy, and to keep nginx happy with absolute paths in the conf.
    if ! cmp -s "$APP_CONF" "$CONFD_DST" 2>/dev/null; then
        cp "$APP_CONF" "$CONFD_DST"
        echo "[nginx-patch] [A] Installed $CONFD_DST"
    else
        echo "[nginx-patch] [A] $CONFD_DST already up to date"
    fi
else
    echo "[nginx-patch] [A] /etc/nginx/conf.d missing — falling back to strategy B only"
fi

# === STRATEGY B: sed-inject into active nginx.conf (belt + suspenders) =====
NGINX_CONF=$(ps -eo args 2>/dev/null | grep "nginx: master" | grep -v grep | sed -n 's/.*-c \(\/[^ ]*\).*/\1/p' | head -1)
if [ -z "$NGINX_CONF" ] || [ ! -f "$NGINX_CONF" ]; then
    for candidate in \
        /etc/nginx/nginx-code-server.conf \
        /etc/nginx/nginx.conf \
        /usr/local/nginx/conf/nginx.conf \
        /opt/nginx/conf/nginx.conf
    do
        if [ -f "$candidate" ]; then
            NGINX_CONF="$candidate"
            break
        fi
    done
fi

if [ -n "$NGINX_CONF" ] && [ -f "$NGINX_CONF" ]; then
    echo "[nginx-patch] [B] Active nginx config: $NGINX_CONF"

    # If conf.d/*.conf is already auto-included by this nginx.conf, strategy A
    # alone is sufficient and we skip the sed entirely (cleaner config).
    if grep -qE "include\s+/etc/nginx/conf\.d/\*\.conf\s*;" "$NGINX_CONF"; then
        echo "[nginx-patch] [B] $NGINX_CONF already auto-includes /etc/nginx/conf.d/*.conf — skipping sed"
    elif ! grep -q "nischint" "$NGINX_CONF"; then
        sed -i 's|http {|http {\n    include /etc/nginx/mime.types;\n    include '"$APP_CONF"';|' "$NGINX_CONF"
        if grep -q "nischint" "$NGINX_CONF"; then
            echo "[nginx-patch] [B] Injected include into $NGINX_CONF"
        else
            echo "[nginx-patch] [B] sed injection FAILED (no 'http {' marker)"
            head -40 "$NGINX_CONF" | sed 's/^/[nginx-patch]   /'
        fi
    else
        echo "[nginx-patch] [B] Routing already present in $NGINX_CONF"
    fi
else
    echo "[nginx-patch] [B] Could not locate active nginx.conf — relying on strategy A"
fi

# === Install supervisor program for future pod boots =======================
if [ -f "$SUPERVISOR_SRC" ] && [ ! -f "$SUPERVISOR_DST" ]; then
    cp "$SUPERVISOR_SRC" "$SUPERVISOR_DST"
    supervisorctl reread 2>/dev/null || true
    supervisorctl update 2>/dev/null || true
    echo "[nginx-patch] Installed supervisor program at $SUPERVISOR_DST"
fi

# === Install nginx-watcher supervisor program (fast-recovery, 1Hz poll) =====
# Detects platform-side config wipes within ~1s instead of waiting for the
# 60s in-process watchdog. Re-applies this patch + HUPs nginx immediately.
WATCHER_SRC="/app/deploy/nginx-watcher.conf"
WATCHER_DST="/etc/supervisor/conf.d/nginx-watcher.conf"
if [ -f "$WATCHER_SRC" ] && [ ! -f "$WATCHER_DST" ]; then
    cp "$WATCHER_SRC" "$WATCHER_DST"
    supervisorctl reread 2>/dev/null || true
    supervisorctl update 2>/dev/null || true
    echo "[nginx-patch] Installed nginx-watcher supervisor program at $WATCHER_DST"
fi

# === Reload nginx ==========================================================
sleep 1
if nginx -t 2>&1 | sed 's/^/[nginx-patch]   nginx -t: /'; then
    MASTER_PID=$(pgrep -f "nginx: master" | head -1)
    if [ -n "$MASTER_PID" ]; then
        kill -HUP "$MASTER_PID"
        echo "[nginx-patch] HUP'd nginx (PID $MASTER_PID)"
    else
        echo "[nginx-patch] nginx not running yet — include will take effect on first start"
    fi
else
    echo "[nginx-patch] ERROR: nginx -t failed — NOT reloading"
fi

# === Self-probe ============================================================
sleep 1
PROBE=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: nischint.care" http://127.0.0.1/health 2>/dev/null || echo "000")
echo "[nginx-patch] Self-probe: curl http://127.0.0.1/health (Host: nischint.care) → HTTP $PROBE"

# Body sniff — distinguishes "FastAPI JSON" vs "React HTML fallback"
SNIFF=$(curl -s -H "Host: nischint.care" http://127.0.0.1/health 2>/dev/null | head -c 80)
echo "[nginx-patch] Self-probe body (first 80 chars): $SNIFF"

echo "[nginx-patch] === nginx-patch complete ==="
exit 0
