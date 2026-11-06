#!/usr/bin/env bash
# Restore only a complete, verified backup. Keep writers stopped on failure.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
ARCHIVE="${1:-}"
# Which stack: the env file names its compose project, so its containers.
ENV_FILE="${SURVEYHQ_ENV_FILE:-.env}"
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
dc() { docker compose --env-file "$ENV_FILE" "$@"; }
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
# A restored database needs the encryption key that protected its credentials.
# Read with Python's dotenv parser, without executing the backed-up environment.
#
# Except when the archive is another stack's on purpose: a copy of production
# restored into development keeps development's key, so production's stored
# connection passwords stay unreadable there rather than syncing from the live
# server. copy-prod-to-dev.sh asks for that; nothing else should.
if [[ "${SURVEYHQ_KEEP_OWN_KEY:-}" == 1 ]]; then
    echo "Keeping this stack's ENCRYPTION_KEY: stored connection passwords will need entering again."
else
    dc run --rm -T --no-deps api python -c \
        'import os, sys; from dotenv import dotenv_values; key = dotenv_values(stream=sys.stdin).get("ENCRYPTION_KEY"); sys.exit(0 if key and key == os.environ.get("ENCRYPTION_KEY") else "ENCRYPTION_KEY differs. Restore that key from env.backup into '"$ENV_FILE"' before retrying.")' < "$WORK/env.backup"
fi
echo "Stopping all application writers"
dc stop api worker worker-monitoring beat
echo "Restoring database"
dc exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$WORK/database.sql"
echo "Restoring data volume"
dc run --rm -T --no-deps api sh -c \
    'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar xzf - -C /data' < "$WORK/data.tar.gz"
# The restored schema may predate the code currently installed.
dc run --rm -T --no-deps api python -m app.cli migrate
dc start api worker worker-monitoring beat
echo "Restore complete."
