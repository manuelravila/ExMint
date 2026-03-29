# CLAUDE.md — ExMint Project Guide

This file is read automatically by Claude Code at session start. Keep it up to date
whenever the project structure, conventions, or deployment setup changes.

---

## Project Overview

ExMint is an open-source personal finance dashboard. It connects to bank accounts via
the Plaid API and provides transaction tracking, categorization, budgeting, and
spending reports. Backend: Flask (Python). Frontend: Vue.js + Bootstrap. DB: MySQL/MariaDB
(SQLite for local dev). Deployed via Docker.

---

## Repository & Branch Strategy

| Branch | Purpose | Deployment |
|--------|---------|------------|
| `dev`  | All new work starts here | Local Docker |
| `stag` | QA before production | VPS staging |
| `main` | Production-ready code | VPS production |

**Rules:**
- Never commit directly to `stag` or `main`
- Changes always flow: `dev → stag → main`
- Merge with `--ff-only` to keep history linear
- Bump `version.py` and add a `CHANGELOG.md` entry before merging to `stag` or `main`

---

## Secrets & Configuration

Secrets use a **two-tier resolution** in `secrets_manager.py`:

1. **Plain environment variable** (default — recommended for self-hosters)
2. **Bitwarden Secrets Manager** (optional — maintainer's production path, requires `BWS_ACCESS_TOKEN`)

`get_secret('KEY')` checks `os.getenv('KEY')` first. BWS is only used if the env var is
absent and `BWS_ACCESS_TOKEN` is set.

See `.env.example` for all required variables.

**Never commit `.env.*` files, keys, certs, or any secrets to git.**

---

## Environment Variables

All config lives in `.env.<branch>` files (gitignored). Required vars:

```
FLASK_ENV            dev | stag | main
DB_USER              database username
DB_PASSWORD          database password (or set via BWS)
DB_HOST              database host
DB_PORT              3307 for dev (SSH tunnel), 3306 for stag/main
DB_NAME              database name
SECRET_KEY           Flask secret key
ENCRYPTION_KEY       Fernet encryption key
PLAID_CLIENT_ID      Plaid API client ID
PLAID_SECRET         Plaid API secret
MAIL_SERVER          SMTP server
MAIL_USERNAME        sender address
MAIL_PASSWORD        SMTP password (or set via BWS)
MAIL_PORT            587
APP_BASE_URL         public base URL of the app
```

---

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app factory |
| `views.py` | Auth routes (login, register, profile) |
| `core_views.py` | All API endpoints (`/api/...`) |
| `models.py` | SQLAlchemy models |
| `config.py` | App configuration, reads from env / BWS |
| `secrets_manager.py` | Secret resolution: env vars → BWS |
| `migrations/` | Alembic DB migrations |
| `static/js/vuePlaid.js` | Main Vue.js frontend |
| `static/js/vueProfile.js` | Profile page Vue component |
| `templates/dashboard.html` | Main dashboard template |
| `ARCHITECTURE.md` | Architecture deep-dive |
| `RUNBOOK.md` | Deployment procedures |
| `CHANGELOG.md` | Release history |

---

## Versioning

- Version string lives in `version.py` only: `__version__ = 'X.Y.Z'`
- Semver: major = milestones/breaking, minor = new features, patch = bug fixes
- Always update `version.py` AND `CHANGELOG.md` together before promoting to `stag`/`main`

---

## Docker

Single `docker-compose.yml` serves all environments via `FLASK_ENV`:

```bash
# Dev
docker-compose --env-file .env.dev -p exmint-dev up -d --build

# Staging
docker-compose --env-file .env.stag -p exmint-stag up -d --build

# Production
docker-compose --env-file .env.main -p exmint-prod up -d --build
```

---

## Database Migrations

```bash
flask db migrate -m "description"   # generate migration
flask db upgrade                    # apply migrations
```

Always review auto-generated migrations before committing. Migration files live in
`migrations/versions/`.

---

## Open Source Notes

- License: **AGPL v3** — modifications must be open-sourced; SaaS deployments must
  publish source
- The maintainer runs a private hosted instance at `exmint-app.automatos.ca`
- Community PRs are reviewed and selectively merged into `dev`
- Contribution guide: `CONTRIBUTING.md`
