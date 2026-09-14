#!/usr/bin/env bash
# Restore only a complete, verified backup. Keep writers stopped on failure.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
ARCHIVE="${1:-}"
[[ -f "$ARCHIVE" ]] || { echo "Usage: $0 <backup archive>"; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# Reject paths outside the extraction directory before unpacking.
if tar tzf "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo "Unsafe backup member path" >&2; exit 1
fi
tar xzf "$ARCHIVE" -C "$WORK" --no-same-owner
for name in database.sql data.tar.gz env.backup SHA256SUMS; do
    [[ -s "$WORK/$name" && ! -L "$WORK/$name" ]] || { echo "Missing or invalid $name" >&2; exit 1; }
done
(cd "$WORK" && sha256sum --check SHA256SUMS)
tar tzf "$WORK/data.tar.gz" > /dev/null
echo "This overwrites the current database and dataset files."
read -rp "Type 'restore' to continue: " confirm
[[ "$confirm" == "restore" ]] || { echo "Cancelled."; exit 1; }
# shellcheck disable=SC1091
[[ -f .env ]] && source .env
DB_USER="${POSTGRES_USER:-surveyhq}"
DB_NAME="${POSTGRES_DB:-surveyhq}"
# A restored database needs the encryption key that protected its credentials.
# Read with Python's dotenv parser, without executing the backed-up environment.
backup_key=$(docker compose run --rm -T --no-deps api python -c \
    'import sys; from dotenv import dotenv_values; print(dotenv_values(stream=sys.stdin).get("ENCRYPTION_KEY", ""))' < "$WORK/env.backup")
[[ "$backup_key" == "${ENCRYPTION_KEY:-}" ]] || {
    echo "ENCRYPTION_KEY differs. Restore that key from env.backup into .env before retrying." >&2; exit 1;
}
echo "Stopping all application writers"
docker compose stop api worker worker-monitoring beat
echo "Restoring database"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 --single-transaction -U "$DB_USER" -d "$DB_NAME" < "$WORK/database.sql"
echo "Restoring data volume"
docker compose run --rm -T --no-deps api sh -c \
    'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf - -C /data' < "$WORK/data.tar.gz"
# The restored schema may predate the code currently installed.
docker compose run --rm -T --no-deps api python -m app.cli migrate
docker compose start api worker worker-monitoring beat
echo "Restore complete."
