#!/usr/bin/env bash
# Why is susoDash not answering? Run this on the server and read from the top.
#
# A 502 on the sign-in page is never a password problem: nginx could not get an
# answer out of the api container, so nothing ever reached the part of the
# platform that checks a password. This gathers what says why, in the order it
# is worth reading.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

line() { printf '\n== %s ==\n' "$1"; }

if ! docker compose version >/dev/null 2>&1; then
    echo "docker compose is not available here. Run this on the server that"
    echo "hosts susoDash, from the directory holding docker-compose.yml."
    exit 1
fi

line "Containers"
# The first thing to know: which of them are up, and which keep restarting.
docker compose ps

line "Disk"
# A full disk is the most common cause of a healthy-looking stack that answers
# 502: Postgres stops accepting writes and the api gives up on start-up.
df -h . | tail -n +1
echo
echo "Docker's own usage:"
docker system df 2>/dev/null || echo "  (could not read)"

line "API log, last 80 lines"
# The actual answer is almost always here.
docker compose logs --tail=80 --no-color api 2>&1 || echo "  (no api container)"

line "Database log, last 30 lines"
docker compose logs --tail=30 --no-color postgres 2>&1 || echo "  (no postgres container)"

line "Can the API be reached from inside the network?"
# Straight to the container, past nginx: this separates "the api is down" from
# "nginx cannot see it".
docker compose exec -T api python -c \
    "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())" \
    2>&1 || echo "  The api container did not answer its own health check."

line "What nginx sees"
docker compose exec -T web wget -qO- --timeout=5 http://api:8000/health 2>&1 \
    || echo "  nginx cannot reach api:8000 - which is exactly what a 502 is."

line "Is R switched on?"
docker compose exec -T api python -c \
    "from app.core.config import get_settings; s = get_settings(); print('R_SCRIPTS_ENABLED =', s.r_scripts_enabled)" \
    2>&1 || echo "  (could not ask)"

cat <<'NOTES'

== What to do with this ==

  Containers show api as "Exit" or "Restarting"
      Read the API log above. It says why on the last few lines.

  The API log ends in "Database not ready (attempt 30/30)"
      Postgres did not come up in time. Check the database log and the disk.

  Disk is at 100%
      That is the cause: Postgres stops accepting writes and the api gives up.
      Free space, then: docker compose up -d
      Old images from previous rebuilds are usually where it went:
          docker image prune -a
      NEVER add --volumes to a prune here. The database and every uploaded
      dataset live in Docker volumes, and pruning volumes while the stack is
      down deletes them. Take a backup first either way: ./scripts/backup.sh

  Everything is up and the health check answers, but the browser still 502s
      Your browser is talking to a different deployment, or nginx is stale:
          docker compose restart web

  Nothing above looks wrong
      docker compose logs --no-color --since 30m > /tmp/susodash.log
      and send that file on.
NOTES
