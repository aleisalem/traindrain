# TrainDrain

A customizable e-learning and security-awareness platform. See [AGENTS.md](AGENTS.md) for the
full product vision and [docs/ROADMAP.md](docs/ROADMAP.md) for how it's being built out release
by release.

## Currently supported

Release 0 is in progress. So far:

- Local dev environment: Postgres, a FastAPI backend, LocalStack (SES emulation), and a
  prod-style static frontend build, all runnable via `docker-compose up`.
- Backend health-check endpoint (`GET /api/health`) with Alembic migrations wired to Postgres.
- Frontend i18n (English/German via react-i18next) and a Tailwind CSS-variable theme system
  (light, dark, colorblind-friendly).
- Core identity schema: `users`, `roles` (seeded with Administrator, Content Manager, Learner),
  `user_roles`, `sessions`, and `audit_log` tables, plus a bootstrap Administrator account seeded
  on first migration (its one-time random password is written to the backend's logs). Shared
  Argon2id password hashing and a password-policy validator (12-char minimum, HIBP breach check)
  live in `app.security` for reuse by the login/invite features that consume them next.

No login, invites, or learning-content features exist yet — the schema above has no endpoints in
front of it until ticket 3.

## Project structure

```
src/
  backend/         FastAPI app (Python, SQLAlchemy 2.0 async, Alembic)
    app/           Application code (config, DB session, models, security helpers, routes)
    alembic/       Database migrations
    tests/         pytest suite, run against a real Postgres instance
  frontend/        React + Vite SPA (TypeScript)
    src/
      i18n/        react-i18next config and en/de locale files
      styles/      Tailwind CSS-variable theme definitions (light/dark/colorblind)
      theme/       Theme-selection hook
docs/              Feature summaries and research notes
.scratch/          Working specs/tickets for the release currently in progress
```

## Running locally

Prerequisites: Docker and Docker Compose.

```bash
cp .env.example .env   # required — docker-compose needs POSTGRES_PASSWORD set
docker-compose up
```

This starts:

- Postgres on `localhost:5433` (mapped off the default 5432 to avoid clashing with a host-installed
  Postgres; override with `POSTGRES_HOST_PORT` in `.env`)
- LocalStack (SES emulation) on `localhost:4566`
- The backend API on `localhost:8000` (runs Alembic migrations on startup, which seeds a
  bootstrap Administrator account — find its one-time password with
  `docker-compose logs backend | grep traindrain.bootstrap`)
- A prod-style static build of the frontend, served via nginx, on `localhost:8080`

For day-to-day frontend development with hot-module-reload, run the Vite dev server natively on
the host instead of relying on the containerized build:

```bash
cd src/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the backend at `localhost:8000`, so keep the
backend (and Postgres) running via `docker-compose up` (or `docker-compose up postgres backend
localstack`) while you work on the frontend.

## Running tests

Backend (requires a reachable Postgres — `docker-compose up postgres` is enough):

```bash
cd src/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest   # defaults to postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain;
         # override with DATABASE_URL if your Postgres differs
```

Tests run against a real Postgres database — the fixtures in `tests/conftest.py` apply Alembic
migrations once per test session and wrap each test in a transaction that's rolled back
afterwards, so tests can freely write data without polluting `docker-compose`'s dev database.

Frontend:

```bash
cd src/frontend
npm install
npm run test        # Vitest + React Testing Library
npx tsc -b           # typecheck
```

## Deploying to AWS

Not yet set up. Terraform under `.deploy/<environment>` and the ECS Fargate / S3+CloudFront
infrastructure described in the Release 0 spec (`.scratch/release-0-foundation/PRD.md`) land in a
later ticket.
