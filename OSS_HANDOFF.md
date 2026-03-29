# ExMint OSS Transition — Handoff Document

Read this at the start of the next conversation to resume exactly where we left off.

---

## Current State (as of 2026-03-28, v1.1.5)

### What has been completed

1. **Git history purged** — sensitive files removed from all 308 commits using `git filter-repo --force`
2. **GitHub force-pushed** — all three branches (dev, stag, main) now have clean history on GitHub (manuelravila/ExMint, currently private)
3. **`.gitignore` expanded** — committed on `dev`, covers: keys, certs, `.env.*`, DBs, venv, logs, tokens.csv, tasks.json
4. **New files written to `/tmp/` on local machine, ready to be pushed into container 109** — NOT YET committed:
   - `/tmp/secrets_manager.py` — env var fallback added, BWS now optional
   - `/tmp/config.py` — hardcoded personal identifiers removed, DB creds via env vars
   - `/tmp/env.example` — full documentation of all required env vars
   - `/tmp/RUNBOOK.md` — personal details scrubbed (IP, paths, usernames replaced with placeholders)
   - `/tmp/CLAUDE.md` — project guide for Claude Code sessions

5. **Still missing** (not yet written):
   - `LICENSE` (AGPL v3)
   - `CONTRIBUTING.md`
   - `CODE_OF_CONDUCT.md`
   - New `README.md`
   - GitHub issue/PR templates
   - GitHub Actions CI workflow

### What still needs to be done in Phase 1

The `/tmp/` files above need to be pushed into container 109 and committed on `dev`:

```bash
# From local machine:
scp /tmp/secrets_manager.py /tmp/config.py /tmp/env.example /tmp/RUNBOOK.md /tmp/CLAUDE.md root@192.168.50.100:/tmp/

ssh root@192.168.50.100 "
pct push 109 /tmp/secrets_manager.py /code/ExMint/secrets_manager.py
pct push 109 /tmp/config.py /code/ExMint/config.py
pct push 109 /tmp/env.example /code/ExMint/.env.example
pct push 109 /tmp/RUNBOOK.md /code/ExMint/RUNBOOK.md
pct push 109 /tmp/CLAUDE.md /code/ExMint/CLAUDE.md
"

# Then inside container 109:
ssh root@192.168.50.100 "pct exec 109 -- bash -c '
cd /code/ExMint &&
git checkout dev &&
rm -rf ExMint2 &&
git add secrets_manager.py config.py .env.example RUNBOOK.md CLAUDE.md &&
git rm -r --cached ExMint2 2>/dev/null; rm -rf ExMint2 &&
git commit -m \"Phase 1: OSS-ready secrets, config, env example, scrubbed runbook, CLAUDE.md\"
'"
```

---

## Infrastructure

- **Proxmox host**: 192.168.50.100 (SSH as root, key already configured)
- **Dev container**: LXC 109, named `code`
- **Code path in container**: `/code/ExMint`
- **Access**: `ssh root@192.168.50.100 "pct exec 109 -- bash -c '<cmd>'"`
- **GitHub repo**: manuelravila/ExMint (private, will be made public after Phase 2)
- **VPS**: separate machine, hosts staging + production via Docker + post-receive hooks

---

## Key Decisions Made

- **License**: AGPL v3
- **Secrets strategy**: `get_secret()` checks env var first (community path), falls back to Bitwarden Secrets Manager if `BWS_ACCESS_TOKEN` is set (maintainer path). Zero code change for Manuel's existing setup once he adds DB_USER/DB_NAME/DB_HOST to his .env files.
- **One repo**: public GitHub repo IS the codebase. Manuel's private VPS deployment uses the same repo — sensitive files are gitignored, never committed.
- **Branch workflow**: all work on `dev` first, promote to `stag` → `main` via `--ff-only` merge. Manuel controls what community PRs get merged.
- **CLAUDE.md**: permanent file in repo root, maintained across all sessions.

---

## Manuel's .env.dev needs updating

After the history purge, `.env.dev` was deleted from disk. Manuel needs to recreate it:

```
FLASK_ENV=dev
BWS_ACCESS_TOKEN=<new token from Bitwarden — he rotated it>
DB_USER=mrar1995_xmnt_dev
DB_HOST=127.0.0.1
DB_PORT=3307
DB_NAME=mrar1995_xmnt_dev_db
APP_BASE_URL=https://exmint-app-dev.automatos.ca
PLAID_WEBHOOK_URL=https://<ngrok-url>/api/plaid/webhook
```

`DB_PASSWORD`, `SECRET_KEY`, `ENCRYPTION_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET`, `MAIL_PASSWORD` all come from BWS — no need to set them as env vars.

Same pattern for `.env.stag` and `.env.main` with their respective values.

---

## Remaining Phases

### Phase 2 — OSS Documentation (all on `dev` first)
- New `README.md` with features, screenshots, Docker quickstart, Plaid setup guide
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- GitHub issue templates (bug report, feature request)
- PR template
- GitHub Actions: Docker build check on PRs

### Phase 3 — Website
- Static HTML landing page at `exmint.automatos.ca`
- Hosted on Manuel's Hostinger VPS (same server as automatos.ca WordPress)
- Buy Me a Coffee + PayPal donation buttons

### Phase 4 — Make repo public
- After Phase 2 is on `main`
- Set repo to public on GitHub
- Add repo description, topics, social preview image

---

## Notes for Next Session

- Always work on `dev` branch first — never touch `stag` or `main` directly
- Check `git branch` before any file changes
- The `/tmp/` files on the local machine may or may not still exist — verify with `ls /tmp/*.py /tmp/*.md /tmp/*.example` before relying on them
- `git push origin` from the container requires GitHub credentials — use a PAT configured temporarily in the remote URL, then remove it
