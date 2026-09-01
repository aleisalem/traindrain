# Release 0 — Project scaffold

Implements ticket 1 of Release 0 (`.scratch/release-0-foundation/tickets.md`).

## What changed

- Added `src/backend`: FastAPI app with a `GET /api/health` endpoint, SQLAlchemy 2.0 async engine,
  and Alembic wired to Postgres via `app.core.config` (no hardcoded connection string — sourced
  from `DATABASE_URL`). Includes an initial near-empty baseline migration.
- Added `src/frontend`: Vite + React + TypeScript SPA with react-i18next (English/German locale
  files under `src/i18n/locales`) and a Tailwind CSS-variable theme system (`src/styles/themes.css`)
  covering light, dark, and a colorblind-friendly (Okabe-Ito palette) theme, switchable via a
  `data-theme` attribute on `<html>`.
- Added root `docker-compose.yml`: Postgres, LocalStack (SES emulation, Community edition), the
  backend (runs Alembic migrations on container start), and an nginx-served prod-style frontend
  build that proxies `/api` to the backend.
- The Vite dev server (run natively on the host, not containerized) proxies `/api` to the backend
  for local HMR work, per the project's dev-workflow convention.
- Updated root `README.md` with local run/test instructions; AWS deployment instructions are
  explicitly deferred (no Terraform yet).

## Notes

- `LOCALSTACK_AUTH_TOKEN` is optional for this ticket — SES emulation works on LocalStack's free
  Community edition. It's wired into `docker-compose.yml`/`.env.example` for when a later feature
  needs a Pro-only service.
- No authentication or data model exists yet — that's ticket 2.
