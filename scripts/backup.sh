#!/usr/bin/env bash
# Capture a consistent database and data volume; any failure fails the backup.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-backups}"
STAMP="$(date +%Y-%m-%d-%H%M%S)"
WORK="$(mktemp -d)"
writers=()
cleanup() {
    result=$?
    if ((${#writers[@]})); then docker compose start "${writers[@]}" || result=1; fi
    rm -rf "$WORK"
    exit "$result"
}
trap cleanup EXIT
mkdir -p "$BACKUP_DIR"
running="$(docker compose ps --services --filter status=running)"
mapfile -t writers < <(printf '%s\n' "$running" | grep -E '^(api|worker|worker-monitoring|beat)$' || true)
if ((${#writers[@]})); then docker compose stop "${writers[@]}"; fi
echo "Dumping database"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' > "$WORK/database.sql"
echo "Copying data volume"
# Stream to the host: the non-root image never needs access to mktemp's 0700 directory.
docker compose run --rm -T --no-deps api tar czf - -C /data . > "$WORK/data.tar.gz"
tar tzf "$WORK/data.tar.gz" > /dev/null
[[ -s "$WORK/database.sql" ]] || { echo "Empty database dump" >&2; exit 1; }
cp .env "$WORK/env.backup"
(cd "$WORK" && sha256sum database.sql data.tar.gz env.backup > SHA256SUMS)
ARCHIVE="$BACKUP_DIR/surveyhq-$STAMP.tar.gz"
tar czf "$ARCHIVE.partial" -C "$WORK" .
mv "$ARCHIVE.partial" "$ARCHIVE"
echo "Wrote $ARCHIVE"
# Retention runs only after all files and checksums were captured successfully.
ls -1t "$BACKUP_DIR"/surveyhq-*.tar.gz | tail -n +15 | xargs -r rm --
