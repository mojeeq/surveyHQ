#!/usr/bin/env bash
# Can this server confine an R script?
#
# Run it before turning R on, and after an upgrade. It answers the one question
# that decides whether R will work: can the kernel enforce Landlock here. The
# platform asks the same question through the launcher's own self-test, so if
# this says yes the interface will too.
#
#   surveyhq-check-r-sandbox                        # inside the api container
#   docker compose exec api surveyhq-check-r-sandbox
#
# Exits 0 when R can run sandboxed, 1 when it cannot. The message says which.
set -uo pipefail

SANDBOX="${SURVEYHQ_R_SANDBOX:-/usr/local/bin/surveyhq-r-sandbox}"
status=0

say() { printf '%-34s %s\n' "$1" "$2"; }

kernel=$(uname -r)
say "kernel" "$kernel"

# Landlock landed in 5.13. Compared numerically rather than as text, or 5.9
# sorts above 5.13.
major=${kernel%%.*}
rest=${kernel#*.}
minor=${rest%%.*}
minor=${minor%%[!0-9]*}
if [ "${major:-0}" -gt 5 ] 2>/dev/null || { [ "${major:-0}" -eq 5 ] && [ "${minor:-0}" -ge 13 ]; } 2>/dev/null; then
  say "kernel has Landlock (>= 5.13)" "yes"
else
  say "kernel has Landlock (>= 5.13)" "NO - Landlock needs Linux 5.13 or newer"
  status=1
fi

if [ ! -x "$SANDBOX" ]; then
  say "sandbox launcher" "MISSING at $SANDBOX"
  echo
  echo "The launcher is built during the Docker build. An image from before the"
  echo "sandbox existed needs rebuilding:"
  echo "    docker compose build api worker && docker compose up -d"
  exit 1
fi
say "sandbox launcher" "$SANDBOX"

probe=$("$SANDBOX" --surveyhq-sandbox-probe 2>&1)
if [ "$probe" = "surveyhq-r-sandbox-v1" ]; then
  say "identifies itself" "yes ($probe)"
else
  say "identifies itself" "NO - answered: $probe"
  status=1
fi

if selftest=$("$SANDBOX" --surveyhq-sandbox-selftest 2>&1); then
  say "can confine on this host" "yes ($selftest)"
else
  say "can confine on this host" "NO"
  echo "    $selftest"
  status=1
fi

echo
if [ "$status" -eq 0 ]; then
  echo "R can run sandboxed here. R_SCRIPTS_ENABLED=true is safe to set."
else
  echo "R cannot be sandboxed here, so the platform will refuse to run it."
  echo "Either fix the above, or accept unconfined R deliberately with"
  echo "R_SANDBOX_REQUIRED=false - which lets any project's script read every"
  echo "other project's files on this server."
fi
exit "$status"
