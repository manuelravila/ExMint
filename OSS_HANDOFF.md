# ExMint OSS Transition — Handoff Document

Read this at the start of the next conversation to resume exactly where we left off.

---

## Current State (as of 2026-03-28, v1.1.5)

### Completed Phases

**Phase 1 — Codebase cleanup** (commit `8e986593` on `dev`)
- Git history purged of all sensitive files (308 commits rewritten)
- GitHub force-pushed — all three branches (dev, stag, main) have clean history
- `.gitignore` expanded
- `secrets_manager.py` — env var fallback, BWS now optional
- `config.py` — hardcoded identifiers removed, DB creds via env vars
- `.env.example` — full env var documentation
- `RUNBOOK.md` — personal details scrubbed
- `CLAUDE.md` — project guide for Claude Code sessions

**Phase 2 — OSS Documentation** (commit `cd2b2ef6` on `dev`)
- `README.md` — full rewrite with features, tech stack, Docker quickstart, Plaid setup
- `LICENSE` — AGPL v3
- `CONTRIBUTING.md` — setup, PR workflow, code style, migration guidance
- `CODE_OF_CONDUCT.md` — Contributor Covenant-based
- `.github/ISSUE_TEMPLATE/bug_report.yml` — structured bug report form
- `.github/ISSUE_TEMPLATE/feature_request.yml` — feature request form
- `.github/PULL_REQUEST_TEMPLATE.md` — PR checklist
- `.github/workflows/ci.yml` — flake8 lint on push/PR to `dev`

### What still needs to be done

**Phase 3 — Website** (optional, separate from repo)
- Static HTML landing page at `exmint.automatos.ca`
- Hosted on Manuel's Hostinger VPS (same server as automatos.ca WordPress)
- Buy Me a Coffee + PayPal donation buttons

**Phase 4 — Make repo public**
- Promote `dev → stag → main` via `--ff-only` merge
- Set repo to public on GitHub (manuelravila/ExMint)
- Add repo description, topics, social preview image

---

## Infrastructure

- **Proxmox host**: 192.168.50.100 (SSH as root, key already configured)
- **Dev container**: LXC 109, named `code`
- **Code path in container**: `/code/ExMint`
- **Access**: `ssh root@192.168.50.100 "pct exec 109 -- bash -c '<cmd>'"`
- **GitHub repo**: manuelravila/ExMint (private, will be made public after Phase 2 is on main)
- **VPS**: separate machine, hosts staging + production via Docker + post-receive hooks

---

## Key Decisions Made

- **License**: AGPL v3
- **Secrets strategy**: `get_secret()` checks env var first, falls back to BWS if `BWS_ACCESS_TOKEN` is set
- **CI**: flake8 lint only (no Docker build — Dockerfile copies SSH key which breaks CI runners)
- **Branch workflow**: all work on `dev` first, promote to `stag` → `main` via `--ff-only`

---

## Manuel's .env.dev needs recreating

After the history purge, `.env.dev` was deleted. Manuel needs to recreate it:

```
FLASK_ENV=dev
BWS_ACCESS_TOKEN=<rotated token from Bitwarden>
DB_USER=mrar1995_xmnt_dev
DB_HOST=127.0.0.1
DB_PORT=3307
DB_NAME=mrar1995_xmnt_dev_db
APP_BASE_URL=https://exmint-app-dev.automatos.ca
PLAID_WEBHOOK_URL=https://<ngrok-url>/api/plaid/webhook
```

`DB_PASSWORD`, `SECRET_KEY`, `ENCRYPTION_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `MAIL_PASSWORD` all come from BWS.

---

## Notes for Next Session

- Always work on `dev` branch — never touch `stag` or `main` directly
- Check `git branch` before any file changes
- `git push origin` requires GitHub PAT configured temporarily in the remote URL, then removed
