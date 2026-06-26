#!/bin/bash
# ExMint PROD Deploy — merge dev→main and deploy to PROD container
# Run from dev working directory after testing is complete.
# Usage: ./deploy-prod.sh [--force]

set -e

DEV_DIR="/home/mrar1995/dev/exmint"
PROD_DIR="/home/mrar1995/web/exmint-app.automatos.ca/public_html"
PROJECT_NAME="main"
COMPOSE_FILE="$PROD_DIR/docker-compose.yml"
ENV_FILE="$PROD_DIR/.env.main"

cd "$DEV_DIR"

# 1. Confirm there's nothing to commit first
if ! git diff --quiet; then
  echo "Uncommitted changes in dev working directory. Commit or stash first."
  exit 1
fi

# 2. Get current version
VERSION=$(grep __version__ version.py | cut -d"'" -f2)
echo "Deploying version $VERSION to PROD"

# 3. Merge dev into main (fast-forward)
git checkout main 2>/dev/null || git checkout -b main
if ! git merge --ff-only dev; then
  echo "Fast-forward merge failed. Run: git merge dev  (resolve conflicts, then retry)"
  exit 1
fi

# 4. Push to GitHub
git push origin main
git push origin dev

# 5. Sync PROD folder with main branch
cd "$PROD_DIR"
git fetch origin
git checkout main
git pull origin main

# 6. Build and restart PROD container
docker-compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" -p "$PROJECT_NAME" up -d --build flask-app

# 7. Wait for health check
sleep 3
if curl -s -o /dev/null -w "" https://exmint-app.automatos.ca/ 2>/dev/null; then
  echo "PROD deploy successful — exmint-app.automatos.ca is serving v$VERSION"
else
  echo "WARNING: Container started but health check failed — check docker logs"
fi

# 8. Return to dev branch
cd "$DEV_DIR"
git checkout dev

echo "Deployment complete: v$VERSION → PROD"
