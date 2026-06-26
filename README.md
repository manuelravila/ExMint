# ExMint

**Self-hosted personal finance dashboard.** Connect your bank accounts via the [Plaid API](https://plaid.com/), track transactions, categorize spending, set budgets, and visualize cash flow — all on infrastructure you control.

![Python](https://img.shields.io/badge/python-3.13-blue)
![Flask](https://img.shields.io/badge/flask-3.0-lightgrey)
![License: AGPL v3](https://img.shields.io/badge/license-AGPL%20v3-blue)
![Version](https://img.shields.io/badge/version-1.1.5-green)

---

## Features

- **Bank connectivity** — link accounts at thousands of institutions via Plaid Link
- **Transaction sync** — real-time updates via Plaid webhooks plus on-demand manual sync
- **Custom categories** — create, color-code, and auto-apply category rules; override individual transactions
- **Transaction splitting** — divide a single transaction across multiple categories
- **Spending reports** — pivot by year → month → category with clickable drill-down to filtered transactions
- **Cash flow chart** — 12-month net income vs. expense line chart, filterable by category
- **Budgets** — set monthly targets per category with 6-month averages and current-month actuals
- **Maintenance tools** — detect and remove duplicate transactions, download full CSV backup
- **CSV / Excel export** — export filtered transactions to CSV or Excel
- **Secure auth** — Flask-Login sessions, bcrypt passwords, password reset via email
- **Data encryption** — Plaid access tokens encrypted at rest with Fernet

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask 3, SQLAlchemy, Alembic |
| Frontend | Vue.js, Bootstrap, Chart.js |
| Database | MySQL / MariaDB (SQLite for local dev) |
| Auth | Flask-Login, Flask-Bcrypt |
| API | Plaid Python SDK v24 |
| Deploy | Docker, Gunicorn |

---

## Quick Start (Docker)

### Prerequisites

- Docker + Docker Compose
- A free [Plaid developer account](https://dashboard.plaid.com/signup) — sandbox credentials work for local testing

### 1. Clone and configure

```bash
git clone https://github.com/manuelravila/ExMint.git
cd ExMint
cp .env.example .env.dev
```

Edit `.env.dev` and fill in your values. Minimum required for local dev:

```
FLASK_ENV=dev
DB_USER=exmint
DB_PASSWORD=change-me
DB_HOST=host.docker.internal
DB_PORT=3306
DB_NAME=exmint
SECRET_KEY=<generate: python -c "import secrets; print(secrets.token_hex(32))">
ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
PLAID_CLIENT_ID=<your Plaid client ID>
PLAID_SECRET=<your Plaid sandbox secret>
MAIL_SERVER=smtp.your-provider.com
MAIL_USERNAME=noreply@your-domain.com
MAIL_PASSWORD=your-mail-password
MAIL_PORT=587
APP_BASE_URL=http://localhost:5000
```

See [`.env.example`](.env.example) for the full variable reference.

### 2. Create the database

Create a MySQL/MariaDB database and user, then run migrations:

```bash
docker-compose --env-file .env.dev -p exmint-dev run --rm flask-app flask db upgrade
```

Or with a local Python environment:

```bash
pip install -r requirements.txt
flask db upgrade
```

### 3. Start the app

```bash
docker-compose --env-file .env.dev -p exmint-dev up -d --build
```

Open [http://localhost:5000](http://localhost:5000), register an account, and click **Connect a bank** to link your first institution.

---

## Plaid Setup

1. Sign up at [dashboard.plaid.com](https://dashboard.plaid.com/signup) — the **Sandbox** tier is free and lets you test with simulated accounts.
2. Create an app and copy your **Client ID** and **Sandbox Secret** into `.env.dev`.
3. Set `PLAID_ENV` to `sandbox` for testing (the default in `.env.example`).
4. (Optional) For real accounts, request **Development** or **Production** access and update `PLAID_SECRET` accordingly.
5. (Optional) To receive real-time transaction updates, expose a public webhook URL and set `PLAID_WEBHOOK_URL`.

---

## Local Dev (without Docker)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set env vars (copy and fill .env.example → .env, then source it or use a tool like direnv)
export FLASK_ENV=dev
# ... other vars ...

flask db upgrade
flask run
```

---

## Database Migrations

```bash
flask db migrate -m "describe your change"   # generate a migration
flask db upgrade                              # apply pending migrations
flask db downgrade                            # roll back one step
```

Migration files live in [`migrations/versions/`](migrations/versions/). Always review auto-generated files before committing.

---

## Secrets

ExMint resolves secrets with a two-tier lookup in [`secrets_manager.py`](secrets_manager.py):

1. **Environment variable** — `os.getenv('KEY')` (recommended for self-hosters)
2. **Bitwarden Secrets Manager** — used only when `BWS_ACCESS_TOKEN` is set (optional)

Self-hosters only need plain env vars. The BWS path is the maintainer's production deployment and is not required for anyone else.

---

## Deployment

The same `docker-compose.yml` serves all environments via `FLASK_ENV`:

```bash
# Staging
docker-compose --env-file .env.stag -p exmint-stag up -d --build

# Production
docker-compose --env-file .env.main -p exmint-prod up -d --build
```

See [`RUNBOOK.md`](RUNBOOK.md) for full deployment procedures, post-receive hooks, and rollback steps.

---

## Contributing

Contributions are welcome — bug reports, feature requests, and pull requests all help.

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR.

---

## License

ExMint is released under the [GNU Affero General Public License v3.0](LICENSE).

In short: you may use, modify, and distribute ExMint freely, but modifications and any SaaS deployments must also be released under AGPL v3.
