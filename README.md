# Nischint

> India's AI Safety Operating System — real-time GPS tracking, voice
> distress detection, predictive risk fusion, and guardian alerts for
> women, children, and families across 200+ cities.

[![Performance](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/your-github-user/your-gist-id/raw/lighthouse-performance.json)](https://nischint.care/)
[![Accessibility](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/your-github-user/your-gist-id/raw/lighthouse-accessibility.json)](https://nischint.care/)
[![Best Practices](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/your-github-user/your-gist-id/raw/lighthouse-best_practices.json)](https://nischint.care/)
[![SEO](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/your-github-user/your-gist-id/raw/lighthouse-seo.json)](https://nischint.care/)
[![Lighthouse CI](https://github.com/your-github-user/nischint/actions/workflows/lighthouse.yml/badge.svg?branch=main)](https://github.com/your-github-user/nischint/actions/workflows/lighthouse.yml)
[![pip-audit](https://github.com/your-github-user/nischint/actions/workflows/pip-audit.yml/badge.svg?branch=main)](https://github.com/your-github-user/nischint/actions/workflows/pip-audit.yml)

> 🛈 The four Lighthouse score badges average across home,
> women-safety, kids-safety, and family-safety landing pages and are
> refreshed on every push to `main` and daily at 06:00 UTC.
> Setup steps for the badge gist: see [`.github/LIGHTHOUSE.md`](.github/LIGHTHOUSE.md).

## What's inside

- **Web SPA** (`frontend/`): React 18 single-page app, Tailwind, Leaflet, Recharts. Code-split by route (~36 chunks, marketing pages ship < 900 KB main bundle).
- **Mobile** (`mobile/`): Expo SDK 55, React Native 0.83, EAS Build/Update, react-native-maps + Google Maps.
- **Backend** (`backend/`): FastAPI + WebSockets, PostgreSQL/Supabase (asyncpg), MongoDB (motor), Redis. Two-process supervisor split: `api` (FastAPI request handlers) and `nischint-scheduler` (14 APScheduler jobs in their own process).
- **Infra**: Cloudflare Workers, Nginx, Supervisor, EAS, Sentry, PostHog.
- **Integrations**: Firebase FCM, Twilio, Mapbox / Google Maps, OpenWeather One Call, TomTom Traffic, SendGrid, Stripe.

## Quality gates

| Workflow | Trigger | What it does |
|---|---|---|
| [`lighthouse.yml`](.github/workflows/lighthouse.yml) | Push to `main`, daily 06:00 UTC, manual | Audits the live production site on 4 pages. Fails the build on score regressions. Updates README badges via Shields.io + Gist endpoint. |
| [`pip-audit.yml`](.github/workflows/pip-audit.yml) | PR + push touching backend deps | Scans the actual installed Python dependency graph for known CVEs. Fails the PR if a new vulnerability appears outside the allowlist (`backend/pip-audit-allowlist.txt`). |
| [`dependabot.yml`](.github/dependabot.yml) | Weekly Mondays 06:00 IST | Opens grouped dependency-update PRs for backend (pip), web (npm), mobile (npm), and CI actions. Assigned to `@metavp369` for review. Security updates jump the queue in their own PRs. |

## Test credentials (preview / staging)

See [`memory/test_credentials.md`](memory/test_credentials.md).

## Architecture & changelog

- [`memory/PRD.md`](memory/PRD.md) — original requirements + architecture
- [`memory/CHANGELOG.md`](memory/CHANGELOG.md) — what's been implemented, dated

## License

Proprietary. © 2025–2026 Nischint Technologies.
