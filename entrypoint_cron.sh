#!/bin/sh
# Cron container entrypoint.
# Dumps the current Docker environment into a sourced file so cron jobs
# inherit all variables passed by docker-compose (DB, PLAID, MAIL, etc.).

set -e

# Write env vars to a file that cron jobs can source.
# Use printenv to capture what docker-compose injected.
printenv | grep -v '^_=' | grep -v '^SHLVL=' > /etc/cron.env
chmod 0400 /etc/cron.env

# Install the application crontab
crontab /app/crontab.docker

echo "Cron container started. Schedule:"
crontab -l

# Run cron in the foreground so the container stays alive
exec cron -f
