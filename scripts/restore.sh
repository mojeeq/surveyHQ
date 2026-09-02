#!/usr/bin/env bash
# Restores a backup produced by scripts/backup.sh.
#
#   ./scripts/restore.sh backups/surveyhq-2026-01-01-120000.tar.gz

set -euo pipefail
cd "$(dirname "$0")/.."

ARCHIVE="${1:-}"
[[ -f "$ARCHIVE" ]] || { echo "Usage: $0 <backup archive>"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar xzf "$ARCHIVE" -C "$WORK"

echo "This overwrites the current database and dataset files."
read -rp "Type 'restore' to continue: " confirm
[[ "$confirm" == "restore" ]] || { echo "Cancelled."; exit 1; }

# shellcheck disable=SC1091
[[ -f .env ]] && source .env
DB_USER="${POSTGRES_USER:-surveyhq}"
DB_NAME="${POSTGRES_DB:-surveyhq}"

echo "==> Stopping application services"
docker compose stop api worker beat

echo "==> Restoring the database"
docker compose exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" < "$WORK/database.sql"

if [[ -f "$WORK/data.tar.gz" ]]; then
    echo "==> Restoring dataset files"
    docker compose run --rm --no-deps -v "$WORK:/backup" api \
        sh -c 'rm -rf /data/* && tar xzf /backup/data.tar.gz -C /data'
fi

echo "==> Starting services"
docker compose start api worker beat
echo "Restore complete."
