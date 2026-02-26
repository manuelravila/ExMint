# ExMint Deployment Runbook

This document is the authoritative reference for ExMint's environment layout,
git workflow, VPS configuration, and deployment procedures. Keep it up to date
whenever infrastructure changes are made.

---

## Table of Contents

1. [Environments Overview](#1-environments-overview)
2. [Git Branches and Remotes](#2-git-branches-and-remotes)
3. [VPS Layout](#3-vps-layout)
4. [Post-Receive Hooks](#4-post-receive-hooks)
5. [Docker Setup](#5-docker-setup)
6. [Standard Deployment Workflow](#6-standard-deployment-workflow)
7. [Re-triggering a Deployment Without Code Changes](#7-re-triggering-a-deployment-without-code-changes)
8. [Troubleshooting](#8-troubleshooting)
9. [Version and Changelog Management](#9-version-and-changelog-management)

---

## 1. Environments Overview

| Environment | URL | Branch | VPS Path |
|-------------|-----|--------|----------|
| Development | local / Docker on dev machine | `dev` | `/code/ExMint` |
| Staging | exmint-app-stg.automatos.ca | `stag` | `/home/mrar1995/web/exmint-app-stg.automatos.ca/public_html` |
| Production | exmint-app.automatos.ca | `main` | `/home/mrar1995/web/exmint-app.automatos.ca/public_html` |

---

## 2. Git Branches and Remotes

### Branches

| Branch | Purpose |
|--------|---------|
| `dev` | Active development — all new work starts here |
| `stag` | Staging — merged from `dev` for QA before production |
| `main` | Production — merged from `stag` when ready to release |

Changes always flow **dev → stag → main**. Never commit directly to `stag` or `main`.

### Remotes

| Remote | URL | Purpose |
|--------|-----|---------|
| `origin` | `https://github.com/manuelravila/ExMint` | GitHub mirror — requires credentials from local machine; cannot push from the dev container |
| `vps-stag` | `vps-exmint:/root/repos/exmint-stag.git` | VPS staging bare repo — triggers staging deployment on push |
| `vps-prod` | `vps-exmint:/root/repos/exmint-prod.git` | VPS production bare repo — triggers production deployment on push |

### SSH Alias (`~/.ssh/config`)

```
Host vps-exmint
    HostName 82.180.163.19
    User root
    IdentityFile /code/ExMint/vps_key
    StrictHostKeyChecking no
```

The private key is `vps_key` in the project root (not tracked by git).

---

## 3. VPS Layout

### Bare Repos (receive pushes, run hooks)

| Environment | Path |
|-------------|------|
| Staging | `/root/repos/exmint-stag.git` |
| Production | `/root/repos/exmint-prod.git` |

These are standard bare git repositories. **All post-receive hooks live here**, not
in the working directory's `.git/hooks/`.

### Working Directories (deployed code, Docker context)

| Environment | Path |
|-------------|------|
| Staging | `/home/mrar1995/web/exmint-app-stg.automatos.ca/public_html` |
| Production | `/home/mrar1995/web/exmint-app.automatos.ca/public_html` |

The hooks deploy code here using `GIT_WORK_TREE`. The `docker-compose.yml` and
env files live in these directories and must be present before the first deploy.

---

## 4. Post-Receive Hooks

### Staging — `/root/repos/exmint-stag.git/hooks/post-receive`

```bash
#!/bin/bash
TARGET=/home/mrar1995/web/exmint-app-stg.automatos.ca/public_html
GIT_DIR=/root/repos/exmint-stag.git

while read oldrev newrev ref; do
    branch=${ref#refs/heads/}
    if [ "$branch" = "stag" ]; then
        git --work-tree="$TARGET" --git-dir="$GIT_DIR" checkout -f "$branch"
        echo "Deployed branch '$branch' to $TARGET"

        cd "$TARGET" || exit 1

        echo "Stopping and removing old staging containers..."
        docker-compose --env-file .env.stag -p exmint-stag down

        echo "Building and starting new staging container..."
        docker-compose --env-file .env.stag -p exmint-stag up -d --build

        echo "--- Staging deployment complete. ---"
    fi
done
```

### Production — `/root/repos/exmint-prod.git/hooks/post-receive`

```bash
#!/bin/bash
TARGET=/home/mrar1995/web/exmint-app.automatos.ca/public_html
GIT_DIR=/root/repos/exmint-prod.git

while read oldrev newrev ref; do
    branch=${ref#refs/heads/}
    if [ "$branch" = "main" ]; then
        git --work-tree="$TARGET" --git-dir="$GIT_DIR" checkout -f "$branch"
        echo "Deployed branch '$branch' to $TARGET"

        cd "$TARGET" || exit 1

        echo "Stopping and removing old production containers..."
        docker-compose --env-file .env.main -p exmint-prod down

        echo "Building and starting new production container..."
        docker-compose --env-file .env.main -p exmint-prod up -d --build

        echo "--- PRODUCTION deployment complete. ---"
    fi
done
```

**Key design points:**
- `GIT_WORK_TREE` + `--git-dir` deploy directly from the bare repo — no dependency on GitHub.
- `cd "$TARGET"` before `docker-compose` so it finds `docker-compose.yml`.
- The hook must be executable: `chmod +x <hook-path>`.

---

## 5. Docker Setup

### `docker-compose.yml`

Single shared file. The `FLASK_ENV` variable controls which env file and container
name are used:

| Variable | Staging value | Production value |
|----------|--------------|-----------------|
| `FLASK_ENV` | `stag` | `main` |
| Container name | `stag_flask_app` | `main_flask_app` |
| Compose project | `exmint-stag` | `exmint-prod` |
| Env file | `.env.stag` | `.env.main` |
| Host port | `5001` | `5000` |
| Network name | `stag_app_net` | `main_app_net` |

### Dockerfile

- Base image: `python:3.13-slim` (bumped from 3.9 — required by `greenlet>=3.3.0` and other packages)
- Installs Bitwarden Secrets Manager CLI (`bws`) for secret retrieval at startup
- Copies `dev_docker_key` as the SSH identity inside the container
- Entry point: `/app/start.sh`

### Useful Docker Commands (run from the working directory)

```bash
# Check running containers
docker-compose --env-file .env.stag -p exmint-stag ps

# View live logs
docker-compose --env-file .env.stag -p exmint-stag logs -f

# Force rebuild without pushing
docker-compose --env-file .env.stag -p exmint-stag down
docker-compose --env-file .env.stag -p exmint-stag up -d --build
```

Replace `--env-file .env.stag -p exmint-stag` with `--env-file .env.main -p exmint-prod` for production.

---

## 6. Standard Deployment Workflow

### Dev → Staging

```bash
# 1. Commit all changes on dev
git checkout dev
git add <files>
git commit -m "..."

# 2. Merge into stag (always fast-forward)
git checkout stag
git merge --ff-only dev

# 3. Push to VPS — hook deploys and rebuilds Docker automatically
git push vps-stag stag

# 4. Return to dev
git checkout dev
```

### Staging → Production

```bash
# 1. Confirm stag is stable, then merge into main
git checkout main
git merge --ff-only stag

# 2. Push to VPS — hook deploys and rebuilds Docker automatically
git push vps-prod main

# 3. Return to dev
git checkout dev
```

### Syncing GitHub (optional, from local machine with credentials)

```bash
git push origin dev stag main
```

This cannot be done from the dev container — GitHub credentials are only available
on the developer's local machine.

---

## 7. Re-triggering a Deployment Without Code Changes

If the hook needs to run again (e.g., after fixing the hook itself) but there are
no new commits, git will refuse to push ("Everything up-to-date") and the hook
won't fire. Create an empty commit to force it:

```bash
git checkout dev
git commit --allow-empty -m "Trigger stag deployment"
git checkout stag
git merge --ff-only dev
git push vps-stag stag
git checkout dev
```

Use the same pattern substituting `stag`/`vps-stag` with `main`/`vps-prod` for
production.

---

## 8. Troubleshooting

### Changes not reflected after push

1. Confirm the hook fired — the push output should show `Deployed branch '...' to ...`.
2. SSH into the VPS and check the working directory:
   ```bash
   cd /home/mrar1995/web/exmint-app-stg.automatos.ca/public_html
   cat version.py          # confirm correct version is on disk
   git log --oneline -3    # shows TARGET_DIR's own git history (may differ from bare repo)
   ```
3. If files are correct but the container is stale, rebuild manually:
   ```bash
   docker-compose --env-file .env.stag -p exmint-stag down
   docker-compose --env-file .env.stag -p exmint-stag up -d --build
   ```

### `docker-compose: No such file` error from hook

The hook ran docker-compose from the bare repo directory instead of the working
directory. Ensure the hook has `cd "$TARGET" || exit 1` **before** the
`docker-compose` commands. See [Section 4](#4-post-receive-hooks) for the
correct hook content.

### `git pull origin stag` reverts deployed code

Occurs when a hook uses `git pull origin stag` and `origin` inside the working
directory points to GitHub (which may be behind the bare repo). **Never use
`git pull origin` inside a post-receive hook.** Use the `GIT_WORK_TREE` +
`--git-dir` approach instead (already in place — see Section 4).

### Docker build fails: package version incompatibility

Symptoms: `No matching distribution found for greenlet==X.Y.Z` or
`Requires-Python >=3.10`.
Cause: Dockerfile base image is Python < 3.10.
Fix: Ensure `Dockerfile` uses `FROM python:3.13-slim`.

### Container running but app shows old version

The Docker image may not have been rebuilt. Run `up -d --build` (not just
`up -d`) to force a rebuild from the current working directory.

---

## 9. Version and Changelog Management

- **`version.py`** — single source of truth for the app version string
  (`__version__ = 'X.Y.Z'`). Displayed in the dashboard footer.
- **`CHANGELOG.md`** — human-readable release notes, newest entry at the top.

### Versioning convention

| Increment | When |
|-----------|------|
| Major (`X`) | Significant milestones or breaking changes |
| Minor (`Y`) | New features |
| Patch (`Z`) | Bug fixes and small improvements |

Both files must be updated together before merging to `stag` or `main`.
