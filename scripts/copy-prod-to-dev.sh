#!/usr/bin/env bash
# Replace the development stack's database and datasets with production's.
#
#   scripts/copy-prod-to-dev.sh                 take a fresh production backup
#   scripts/copy-prod-to-dev.sh <archive>       use a production backup already made
#
# Production is only ever read. A fresh backup does stop production's API and
# workers until the database and the data volume are copied, exactly as
# `make backup` does - minutes on a large survey - so pass last night's archive
# instead during working hours.
#
# The development stack keeps its own secrets. Sign-in tokens from production
# do not work on it, and the Survey Solutions passwords stored on production's
# connections cannot be read with development's ENCRYPTION_KEY - which is what
# stops a copy from pulling from the live survey server on its own schedule.
set -euo pipefail
cd "$(dirname "$0")/.."

PROD_ENV="${PROD_ENV_FILE:-.env.prod}"
DEV_ENV="${DEV_ENV_FILE:-.env}"
PROD_BACKUP_DIR="${PROD_BACKUP_DIR:-backups/prod}"
ARCHIVE="${1:-}"

for file in "$PROD_ENV" "$DEV_ENV"; do
    [[ -f "$file" ]] || { echo "Missing $file" >&2; exit 1; }
done
[[ -z "$ARCHIVE" || -f "$ARCHIVE" ]] || { echo "No such archive: $ARCHIVE" >&2; exit 1; }

# The guard that matters most here. Two env files naming the same compose
# project are the same stack, and copying it "to dev" would restore production
# over itself from a backup taken a moment ago.
project() { docker compose --env-file "$1" config | sed -n 's/^name: //p'; }
prod="$(project "$PROD_ENV")"
dev="$(project "$DEV_ENV")"
[[ -n "$prod" && -n "$dev" ]] || { echo "Could not read the compose project names" >&2; exit 1; }
if [[ "$prod" == "$dev" ]]; then
    echo "$PROD_ENV and $DEV_ENV both name the compose project '$dev'." >&2
    echo "Set COMPOSE_PROJECT_NAME in $PROD_ENV so production is a stack of its own." >&2
    exit 1
fi

echo "This overwrites the database and dataset files of '$dev' ($DEV_ENV)"
echo "with a copy of '$prod' ($PROD_ENV)."
if [[ -z "$ARCHIVE" ]]; then
    echo "Taking the copy stops production's API and workers until the backup is done."
fi
read -rp "Type 'copy' to continue: " confirm
[[ "$confirm" == "copy" ]] || { echo "Cancelled."; exit 1; }

if [[ -z "$ARCHIVE" ]]; then
    echo "Backing up '$prod'"
    SURVEYHQ_ENV_FILE="$PROD_ENV" BACKUP_DIR="$PROD_BACKUP_DIR" ./scripts/backup.sh
    ARCHIVE="$(ls -1t "$PROD_BACKUP_DIR"/surveyhq-*.tar.gz | head -n 1)"
fi

echo "Restoring $ARCHIVE into '$dev'"
# The confirmation above stands in for restore's own.
printf 'restore\n' | SURVEYHQ_ENV_FILE="$DEV_ENV" SURVEYHQ_KEEP_OWN_KEY=1 \
    ./scripts/restore.sh "$ARCHIVE"

echo ""
echo "'$dev' now holds production's users, projects, datasets and dashboards."
echo "Sign in with your production password. Survey Solutions connections will"
echo "fail to sync on it until their passwords are entered again there."
if grep -Eq '^SMTP_HOST=.+' "$DEV_ENV"; then
    echo ""
    echo "WARNING: $DEV_ENV sets SMTP_HOST. Alert rules copied from production"
    echo "will email the real recipients from this stack too. Empty SMTP_HOST in"
    echo "$DEV_ENV and run 'make up' unless that is what you want."
fi
