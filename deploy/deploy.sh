#!/bin/bash
# Deploy script for nischint.care production server
# Run this on the production server after git pull

set -e

echo "=== NISCHINT Production Deploy ==="

# 1. Install backend dependencies
echo "[1/6] Installing backend dependencies..."
cd backend
pip install -r requirements.txt --quiet
cd ..

# 2. Run database migrations
echo "[2/6] Running migrations..."
cd backend
alembic upgrade head
cd ..

# 3. SHADOW MACHINERY SMOKE TEST — must pass before we cycle backend.
#    A failure here means a taxonomy regression, a broken state
#    machine, or a broken autodisable safeguard. Better to block the
#    deploy here than discover it weeks later when real shadow
#    traffic should be accumulating.
#
#    Hard gate: || exit 1 propagates the failure. Cleanup is
#    handled inside the script's try/finally so no synthetic data
#    leaks into operator-facing shadow stats even on failure.
echo "[3/6] V2 shadow machinery smoke test..."
cd backend
python scripts/synthetic_shadow_validation.py || {
  echo "  ✗ V2 shadow machinery smoke test FAILED — aborting deploy"
  echo "    Investigate scripts/synthetic_shadow_validation.py output."
  echo "    A passing run is REQUIRED for deploy to proceed."
  exit 1
}
cd ..

# 4. Restart backend first (before nginx) and WAIT for readiness
echo "[4/6] Restarting backend..."
sudo supervisorctl restart backend

echo "[5/6] Waiting for backend /api/health..."
MAX_WAIT_SECONDS=60 /app/deploy/wait-for-backend.sh || {
  echo "  ✗ backend readiness gate failed — aborting deploy (nginx not reloaded)"
  exit 1
}

# 5. NOW reload nginx — backend is guaranteed live, no "Connection refused" race
echo "[6/6] Configuring nginx..."
sudo cp deploy/nginx/nischint.conf /etc/nginx/sites-available/nischint.conf
sudo ln -sf /etc/nginx/sites-available/nischint.conf /etc/nginx/sites-enabled/nischint.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
echo "  nginx configured: /api/* + SEO pages + /blog/* → :8001, /* → :3000"

# 5. Restart frontend (non-blocking — CRA dev server is separate)
sudo supervisorctl restart frontend

echo ""
echo "=== Deploy complete ==="
echo "Verify: curl -s https://nischint.care/api/health"
echo "Verify SEO: curl -A 'Googlebot' https://nischint.care/women-safety-app | grep '<title>'"
