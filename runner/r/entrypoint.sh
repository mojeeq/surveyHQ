#!/bin/sh
# Watch for jobs and run them. One at a time, deliberately.
#
# A poll loop over a shared directory rather than a queue, because the point of
# this container is that it can reach nothing: no Redis, no database, no
# network at all. A directory both sides can see is the only channel left, and
# it is enough.
#
# The platform writes everything a job needs, then creates READY last. Nothing
# here looks at a directory without that marker, so a job is never started
# half-written.
set -eu

WORK="${RUNNER_WORK:-/work}"
POLL="${RUNNER_POLL_SECONDS:-1}"
# A script that will not finish is a script that has gone wrong. The platform
# sets its own deadline too; this is the one that stops a runaway holding the
# only runner for ever.
LIMIT="${RUNNER_TIMEOUT_SECONDS:-300}"

echo "runner: watching $WORK, ${LIMIT}s limit per job"

while true; do
  for job in "$WORK"/*; do
    [ -d "$job" ] || continue
    [ -f "$job/READY" ] || continue
    [ -f "$job/DONE" ] && continue
    [ -f "$job/CLAIMED" ] && continue

    # Claimed before anything else, so a second runner added later cannot pick
    # up the same job.
    : > "$job/CLAIMED"
    echo "runner: $job"

    # timeout kills the whole process group, so an R script that spawned
    # something does not outlive it.
    if timeout -k 5 "$LIMIT" Rscript /opt/runner/harness.R "$job"; then
      :
    else
      status=$?
      # The harness writes its own result when it fails cleanly. This is for
      # when it could not: killed on the time limit, or out of memory, where
      # nothing in R runs again and only the supervisor is left to say so.
      if [ ! -f "$job/DONE" ]; then
        if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
          reason="the script ran longer than ${LIMIT}s and was stopped"
        else
          reason="the script was stopped before it finished (exit $status), which is usually running out of memory"
        fi
        printf '{"ok":false,"error":"%s"}' "$reason" > "$job/result.json"
        : > "$job/DONE"
      fi
    fi
  done
  sleep "$POLL"
done
