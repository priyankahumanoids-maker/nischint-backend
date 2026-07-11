# Lighthouse CI — one-time setup

The Lighthouse workflow at `.github/workflows/lighthouse.yml` runs four
audits against the production site (`https://nischint.care/`,
`/women-safety-app`, `/kids-safety-app`, `/family-safety-app`) on
**every push to `main`**, **daily at 06:00 UTC**, and on **manual
dispatch** from the Actions tab.

It does two things:

1. **Fails the build** if Performance < 50, Accessibility < 90,
   Best-Practices < 75, or SEO < 90 on any of the four pages. These
   budgets are intentionally below the current measured baseline so the
   gate catches *regression*, not natural run-to-run noise.
2. **Updates a badge Gist** with the average scores. The README badges
   read from that Gist via Shields.io, so they always reflect the latest
   successful main-branch run.

Without the Gist secrets the gate still runs (and still fails on
regression) — only the badge-update step is skipped.

## Required one-time setup

You need two secrets in the repo settings (`Settings → Secrets and
variables → Actions → New repository secret`):

### 1. Create the badge Gist

1. Sign in to GitHub as the owner of the repo.
2. Visit <https://gist.github.com/> and click **+ New gist**.
3. Description: `nischint-lighthouse-badges`
4. Add four files (placeholder content — the workflow will overwrite
   them on the first run):

   `lighthouse-performance.json`
   ```json
   {"schemaVersion": 1, "label": "Performance", "message": "pending", "color": "lightgrey"}
   ```

   `lighthouse-accessibility.json`
   ```json
   {"schemaVersion": 1, "label": "Accessibility", "message": "pending", "color": "lightgrey"}
   ```

   `lighthouse-best_practices.json`
   ```json
   {"schemaVersion": 1, "label": "Best Practices", "message": "pending", "color": "lightgrey"}
   ```

   `lighthouse-seo.json`
   ```json
   {"schemaVersion": 1, "label": "SEO", "message": "pending", "color": "lightgrey"}
   ```

5. Click **Create public gist** (public is required for Shields.io to
   read it — the JSON contains only scores, no secrets).
6. Copy the gist ID from the URL: `https://gist.github.com/<user>/<GIST_ID>`.

### 2. Create a Personal Access Token for Gist write

1. Visit <https://github.com/settings/tokens/new>.
2. Name: `nischint-lighthouse-gist`
3. Expiration: 1 year (or no-expiry if your org policy allows).
4. Scopes: tick **`gist`** only (least privilege — this PAT cannot
   touch any repo).
5. Click **Generate token**, copy the value (`ghp_…`).

### 3. Add the secrets to the repo

In the repo's `Settings → Secrets and variables → Actions`, add:

| Name          | Value                                                         |
|---------------|---------------------------------------------------------------|
| `GIST_ID`     | The gist ID from step 1.6                                     |
| `GIST_TOKEN`  | The PAT from step 2.5                                         |

### 4. Update the README badge URLs

The README badges currently point at the gist user `your-github-user`
and gist ID `your-gist-id`. Replace those with your actual values so
the badges resolve:

```md
![Performance](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/<USER>/<GIST_ID>/raw/lighthouse-performance.json)
![Accessibility](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/<USER>/<GIST_ID>/raw/lighthouse-accessibility.json)
![Best Practices](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/<USER>/<GIST_ID>/raw/lighthouse-best_practices.json)
![SEO](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/<USER>/<GIST_ID>/raw/lighthouse-seo.json)
```

A `sed` one-liner makes this safe:

```sh
sed -i 's|your-github-user|<your-username>|g; s|your-gist-id|<your-gist-id>|g' README.md
```

## Verifying the setup

After landing the workflow + secrets on `main`:

1. Go to the **Actions** tab → **lighthouse** workflow → **Run workflow**.
2. The four matrix legs run for ~6–8 min total.
3. If green, the `publish-badges` job updates the gist.
4. Refresh the README — badges should now show real numbers.

If you'd rather test without merging first, push to a feature branch
and run the workflow from there. Note the badge update only runs on
pushes to `main` to avoid PR drafts overwriting the public scores.

## Adjusting budgets

The pass/fail thresholds live in
`.github/workflows/lighthouse.yml` under `Enforce score budgets`. Edit
the four `MIN_*` env vars to tighten or relax. Recommended cadence:
when the average score has been ≥ 10 points above the budget for two
consecutive weeks, bump the budget up by 5 to harden the floor.
