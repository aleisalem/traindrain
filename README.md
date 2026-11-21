# TrainDrain

A customizable e-learning and security-awareness platform. See [AGENTS.md](AGENTS.md) for the
product vision and [docs/ROADMAP.md](docs/ROADMAP.md) for the release plan. Per-feature details
live in [docs/](docs/).

## Currently supported

**Release 0 — foundation**
- Local stack via `docker-compose` (Postgres, FastAPI, LocalStack S3/SES, nginx-served frontend).
- Email+password login with server-side sessions, forced first-login password change, forgot/reset
  password, opt-in TOTP 2FA with recovery codes, and rate limiting.
- Admin area: invites (EN/DE emails), user disable/erase (GDPR), role assignment, user groups.
- Self-service preferences: name, password, language (EN/DE), theme (light/dark/colorblind),
  navigation placement. Single `AppShell` navigation, role-aware.

**Release 1 — learning modules**
- Content Manager authoring: modules, Tiptap page editor (stored as validated ProseMirror JSON,
  never HTML), image/attachment assets (hostile-upload checks, presigned URLs), tags and search.
- Publishing with immutable version snapshots (minor/substantive), unpublish, duplicate, delete
  (tombstone), native zip export/import, Markdown/DOCX/PDF document import.
- Translations via translation groups; learner catalog, viewer with progress and attestation.
- Assignment to groups/individuals with due dates, daily reminder job, module reports
  (privacy-split: group counts for Content Managers, full roster/CSV for Administrators).

**Release 2 — campaigns and grading**
- Campaigns: drafts, collaborators, activation/close, suspend/resume, sequential modules,
  edit safeguards, reminders, and reports.
- Quizzes: single/multiple-choice and true/false, server-side grading, pass mark and attempt caps,
  completion gating, attempt administration, quiz reports.

**Infrastructure**: Terraform for Release 1/2 AWS additions under `.deploy/dev` (module-assets S3
bucket, IAM, EventBridge-scheduled reminder task, SES templates). See
[docs/references/infrastructure.md](docs/references/infrastructure.md).

## Repository structure

```
src/
  backend/           FastAPI app (Python, SQLAlchemy 2.0 async, Alembic)
    app/
      routes/        API routers
      models/        SQLAlchemy models
      schemas/       Pydantic request/response models
      security/      Passwords, sessions, tokens, rate limiting, audit log, mailer
      content/       ProseMirror schema + validator, upload sniffer, document converters, import/export
      jobs/          Script entrypoints (e.g. send_reminders — the daily scheduled job)
      access.py      The single "who may read a module" decision
      assignments.py, campaigns.py, reminders.py, reporting.py,
      quiz*.py, search.py, storage.py, dependencies.py   Domain logic shared by routes
    alembic/         Database migrations
    tests/           pytest suite (real Postgres)
  frontend/          React + Vite SPA (TypeScript)
    src/
      shell/         AppShell, nav config
      features/      auth, admin, content, learning, invites, profile, twoFactor
      content/       Checked-in ProseMirror schema and Tiptap extensions
      i18n/          en/de locale files
      styles/, theme/  Light/dark/colorblind themes
.deploy/<env>/       Terraform per environment (currently `dev`)
docs/                Feature summaries and research notes
scripts/             Helper scripts (e.g. show-emails.py)
.scratch/            Working specs/tickets for the release in progress
```

## Adding a new feature

Follow the process in [AGENTS.md](AGENTS.md):

1. Clarify scope — use the `wayfinder` skill if unsure how to approach it, or `grilling` to gather
   requirements.
2. `to-spec` → write the spec; `to-tickets` → break it into small tickets.
3. `implement` → build one ticket at a time, with unit and integration tests, EN/DE strings, and all
   three themes. Keep endpoints atomic, require authentication, deny by default, never hardcode
   secrets, and update `.deploy/` Terraform for any new AWS service.
4. `code-review` the result.
5. Update this README (summary, structure if changed) and add a brief summary under `docs/`.

## Running locally

Prerequisites: Docker and Docker Compose.

```bash
cp .env.example .env   # required — sets POSTGRES_PASSWORD
# Generate TWO_FACTOR_ENCRYPTION_KEY and put it in .env (needed for 2FA):
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
docker-compose up
```

| Service | Address |
|---|---|
| Frontend (nginx, prod-style build) | `localhost:8080` |
| Backend API | `localhost:8000` |
| Postgres | `localhost:5433` |
| LocalStack (S3, SES) | `localhost:4566` |
| `reminder-runner` | loops `python -m app.jobs.send_reminders` hourly |

- Bootstrap Administrator password: `docker-compose logs backend | grep traindrain.bootstrap`
- Read "sent" emails: `python3 scripts/show-emails.py` (`-t <email>`, `-n <count>`, `--clear`)
- Run the reminder job once: `docker-compose run --rm reminder-runner python -m app.jobs.send_reminders`
- Frontend with hot reload: `cd src/frontend && npm install && npm run dev` (proxies `/api` to
  `localhost:8000`; keep the backend running).

## Running tests

Backend (needs Postgres: `docker-compose up postgres`):

```bash
cd src/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Some tests assert on global state, so if you have used the app by hand, use a separate database:

```bash
createdb -h localhost -p 5433 -U traindrain traindrain_test   # once
DATABASE_URL=postgresql+asyncpg://traindrain:traindrain@localhost:5433/traindrain_test pytest
```

S3 is faked in the suite; LocalStack is not needed.

Frontend:

```bash
cd src/frontend
npm install
npm run test    # Vitest; also checks the ProseMirror schema copies are identical
npm run lint    # oxlint; dangerouslySetInnerHTML fails the build
npx tsc -b      # typecheck
```

If you change the ProseMirror schema, change both copies:
`src/frontend/src/content/prosemirrorSchema.json` and `src/backend/app/content/prosemirror_schema.json`.

## Deploying to AWS

Target region: `eu-central-1`. Infrastructure is Terraform under `.deploy/<env>`.

Release 0's baseline stack (VPC, ECS Fargate cluster/ALB, S3+CloudFront frontend; see
`docs/release-0-foundation/PRD.md`) is **not yet in this repository**. `.deploy/dev` covers the
later additions — module-assets S3 bucket, backend IAM policy, EventBridge Scheduler + ECS task for
the reminder job, SES templates — and takes the baseline's cluster, subnets, security groups, task
roles and secrets as input variables.

```bash
cd .deploy/dev
terraform init
terraform validate   # works without an AWS account
terraform plan       # needs AWS credentials and the baseline resource names as variables
terraform apply
```

See [.deploy/dev/README.md](.deploy/dev/README.md) and
[docs/references/infrastructure.md](docs/references/infrastructure.md) for the variables and for
exactly what is and isn't provisioned.
