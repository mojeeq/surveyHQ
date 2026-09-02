#!/usr/bin/env bash
# Backs up the Postgres database and every stored dataset into ./backups.

set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-backups}"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$BACKUP_DIR"

# shellcheck disable=SC1091
[[ -f .env ]] && source .env
DB_USER="${POSTGRES_USER:-surveyhq}"
DB_NAME="${POSTGRES_DB:-surveyhq}"

echo "==> Dumping the database"
docker compose exec -T postgres pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    > "$WORK/database.sql"

echo "==> Copying stored datasets"
docker compose run --rm --no-deps -v "$WORK:/backup" api \
    tar czf /backup/data.tar.gz -C /data . 2>/dev/null || {
        echo "    (no dataset files yet)"
        tar czf "$WORK/data.tar.gz" -T /dev/null
    }

cp .env "$WORK/env.backup" 2>/dev/null || true

ARCHIVE="$BACKUP_DIR/surveyhq-$STAMP.tar.gz"
tar czf "$ARCHIVE" -C "$WORK" .
echo "==> Wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# Keep the 14 most recent backups
ls -1t "$BACKUP_DIR"/surveyhq-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm --
echo "Done."
