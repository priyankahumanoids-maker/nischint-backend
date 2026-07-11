# pip-audit Sweep — May 30, 2026

Post-podcast retirement audit. Scanning installed env at `/root/.venv`.

## TL;DR

| Action | Package | Reason | Disk |
|---|---|---|---|
| **REMOVE** | `langgraph==0.2.76` | not imported, no reverse deps, has RCE CVE | 1.3 MB |
| **REMOVE** | `langgraph-checkpoint==2.1.2` | not imported, no reverse deps, **2 RCE CVEs** | 0.4 MB |
| **REMOVE** | `langgraph-prebuilt==1.0.9` | not imported, no reverse deps | small |
| **REMOVE** | `langgraph-sdk==0.1.74` | only reverse dep is `langgraph` (also removed) | small |
| **REMOVE** | `langsmith==0.1.147` | not imported, no reverse deps, **2 CVEs** (data leak + RCE) | 1.7 MB |
| **UPGRADE** | `litellm==1.80.0 → 1.83.7+` | required by `emergentintegrations`, has **auth bypass + RCE CVEs** | (no size change) |
| **UPGRADE** | `pillow==12.1.1 → 12.2.0` | 4 CVEs (integer overflow, decompression bomb, infinite loop, OOB write) | (no size change) |
| **UPGRADE** | `cryptography==46.0.5 → 46.0.7` | 2 CVEs (buffer overflow + name-constraint validation bypass) | (no size change) |
| **UPGRADE** | `pyjwt==2.11.0 → 2.12.0` | RFC §4.1.11 `crit` header validation bypass | (no size change) |
| **UPGRADE** | `mako==1.3.10 → 1.3.12` | path traversal on Windows (low impact on Linux) | (no size change) |
| **UPGRADE** | `pyasn1==0.6.2 → 0.6.3` | DoS via uncontrolled recursion in ASN.1 decoder | (no size change) |
| **UPGRADE** | `pymongo==4.5.0 → 4.6.3` | OOB read in BSON parser | (no size change) |

## Critical removals (P0 — orphaned langchain ecosystem)

Per the handoff summary, podcast pipeline + `chromadb` + `langchain` were retired. **But** these 5 langgraph/langsmith packages survived the cleanup:

```
langgraph==0.2.76
langgraph-checkpoint==2.1.2
langgraph-prebuilt==1.0.9
langgraph-sdk==0.1.74
langsmith==0.1.147
```

Verification that they're orphaned:
* `grep -rn "import langgraph\|from langgraph\|import langsmith\|from langsmith" /app/backend/ --include="*.py"` → **0 matches**
* `pip show langgraph langsmith langgraph-checkpoint langgraph-prebuilt` → `Required-by:` is empty for all
* `pip show langgraph-sdk` → required only by `langgraph` (itself orphaned)

They have critical security advisories:
* `langgraph-checkpoint` — **CVE-2025-64439** (RCE via JSON serializer) + **CVE-2026-27794** (RCE via pickle fallback in cache backend)
* `langsmith` — **CVE-2026-41182** (streaming output redaction bypass) + **CVE-2026-45134** (deserialization RCE via prompt pulls)
* `langgraph` — **PYSEC-2026-83** (msgpack deserialization RCE)

**Recommended action**: delete these 5 lines from `requirements.txt`, run `pip uninstall` of each in the prod image.

## Critical upgrades (P0 — auth bypass + RCE in litellm)

`litellm==1.80.0` is pulled in transitively by `emergentintegrations` (so we can't remove it). But the installed version has **4 critical CVEs**:

* **GHSA-69x8-hrgq-fjj8** — full authentication bypass chain (unsalted SHA-256 hashes + pass-the-hash + hash exposure)
* **CVE-2026-35029** — RCE via `/config/update` (missing admin role check)
* **CVE-2026-35030** — JWT cache-collision identity inheritance
* **CVE-2026-42271** — RCE via MCP test endpoints (arbitrary command execution)

All fixed in `litellm==1.83.7`. **Recommend pinning to 1.83.7 or higher.**

This will need a coordinated change with `emergentintegrations` — if the integration playbook pins an older litellm, we'll need an override. Suggested: add `litellm>=1.83.7` AFTER the `emergentintegrations` line in requirements.txt so pip's resolver picks the higher version.

## Lower-priority upgrades (P1)

These are CVEs in pure-library packages with realistic exploit preconditions. Worth bundling into one PR:

* `pillow==12.1.1 → 12.2.0` — 4 CVEs around malformed image parsing. Practical impact only if we accept untrusted image uploads (we do via profile pics + driving incident attachments).
* `cryptography==46.0.5 → 46.0.7` — buffer overflow on non-contiguous buffers + DNS name-constraint validation bypass. Touches JWT signing path.
* `pyjwt==2.11.0 → 2.12.0` — RFC `crit` header validation bypass. Touches auth.
* `pymongo==4.5.0 → 4.6.3` — BSON OOB read. Touches Mongo motor driver.
* `mako==1.3.10 → 1.3.12` — path traversal on Windows only (we run Linux, but still).
* `pyasn1==0.6.2 → 0.6.3` — DoS via deeply-nested ASN.1. Touches certificate parsing.

## Recommended PR sequence

1. **PR-1** (security-critical, no functional risk):
   ```
   pip uninstall -y langgraph langgraph-checkpoint langgraph-prebuilt langgraph-sdk langsmith
   # Then delete lines 86–90 from requirements.txt
   pip freeze > requirements.txt   # only if you want a frozen rebuild
   ```
   **Saves**: 3.5 MB disk + closes 5 high-severity CVEs.

2. **PR-2** (litellm upgrade — requires coordination):
   * Test `pip install --upgrade litellm` in a venv first to confirm no API breaks
   * Add `litellm>=1.83.7` to requirements.txt
   * Smoke-test all 5 LiteLLM call sites listed in PRD §"AI metrics layer"

3. **PR-3** (bundled library upgrades):
   * Run `pip install --upgrade pillow cryptography pyjwt pymongo mako pyasn1`
   * Pin new versions in requirements.txt
   * Run full pytest sweep

## Out-of-scope

* `black==26.1.0 → 26.3.1` — dev-only cache file write issue, no production impact.
* `ecdsa==0.19.1` — CVE-2024-23342 (Minerva timing attack) — project explicitly says side-channel attacks are out of scope; CVE-2026-33936 (DER parsing DoS) is fixed in 0.19.2 → low priority upgrade.
* `pytest`, `pip` — dev/CI tooling, not in the production image.
