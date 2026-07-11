#!/usr/bin/env bash
# pip-audit gate — runs pip-audit against the installed environment
# and FAILS if any vulnerability is detected outside the project
# allowlist in `pip-audit-allowlist.txt`.
#
# Intended use:
#   * Pre-commit hook on `backend/requirements.txt` changes
#   * GitHub Actions workflow on PR / push
#   * Local dev:  bash backend/scripts/pip_audit_check.sh
#
# Exit codes:
#   0 — no new vulnerabilities outside allowlist
#   1 — new vulnerability detected (must add to allowlist with
#       rationale, OR upgrade the package)
#   2 — pip-audit itself failed (e.g., network, missing tool)
#
# Why this exists:
#   2026-05-30 — Audit found 5 orphaned langchain ecosystem packages
#   holding RCE CVEs that had survived prior cleanup. This gate
#   prevents that recurrence: any new vuln must be either fixed
#   (preferred) or explicitly accepted via the allowlist (with
#   rationale recorded in the same file).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ALLOWLIST="$BACKEND_DIR/pip-audit-allowlist.txt"

if [[ ! -f "$ALLOWLIST" ]]; then
    echo "❌ Allowlist file not found: $ALLOWLIST" >&2
    exit 2
fi

# Validate pip-audit is installed (fail soft with an installation hint
# rather than a cryptic shell error).
if ! command -v pip-audit >/dev/null 2>&1; then
    echo "❌ pip-audit not installed. Run: pip install pip-audit" >&2
    exit 2
fi

# Build the `--ignore-vuln` flag list from the allowlist. Strip
# comments (#…) and blank lines. The transformation is intentionally
# explicit (no fancy xargs) so the failure mode is debuggable.
IGNORE_FLAGS=()
while IFS= read -r line; do
    # Strip leading/trailing whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    # Skip blanks and comments
    [[ -z "$line" || "$line" == \#* ]] && continue
    IGNORE_FLAGS+=("--ignore-vuln" "$line")
done < "$ALLOWLIST"

echo "🔍 Running pip-audit with ${#IGNORE_FLAGS[@]} flag tokens "\
"(allowlist: $(grep -cE '^[A-Z]' "$ALLOWLIST") known IDs)"

# Run pip-audit against the installed env. We don't pass `-r` because
# our requirements.txt has a transitive openai/emergentintegrations
# resolver conflict that breaks --requirement scanning (this is a
# pre-existing platform constraint; the *installed* env is what
# actually runs in prod, so we scan that).
#
# We deliberately do NOT pass `--strict` because `emergentintegrations`
# is an Emergent-internal package not published to PyPI, which pip-audit
# would otherwise treat as a fatal "audit incomplete" error. Without
# `--strict`, pip-audit still exits non-zero on any *vulnerability*
# (the regression-prevention guarantee we want) — it just downgrades
# the PyPI-lookup-miss to a stderr warning.
if pip-audit "${IGNORE_FLAGS[@]}" 2>&1; then
    echo ""
    echo "✅ pip-audit: no vulnerabilities outside the allowlist."
    exit 0
else
    rc=$?
    echo ""
    echo "❌ pip-audit: new vulnerability detected (or pip-audit failed)."
    echo ""
    echo "Options:"
    echo "  1. Upgrade the vulnerable package (preferred) — pip install --upgrade <pkg>"
    echo "  2. Accept the risk: add the CVE/PYSEC/GHSA id to:"
    echo "     $ALLOWLIST"
    echo "     with a 1-line rationale comment above it."
    echo ""
    exit "$rc"
fi
