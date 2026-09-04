#!/usr/bin/env bash
# One-shot installer for susoDash on Ubuntu 22.04 / 24.04.
#
#   curl -fsSL https://get.docker.com | sh   # if you prefer to do it yourself
#   ./scripts/install-ubuntu.sh
#
# Installs Docker if it is missing, generates .env with fresh secrets, then
# builds and starts the stack.

set -euo pipefail

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { echo -e "${BLUE}==>${NC} $*"; }
ok()   { echo -e "${GREEN}  ok${NC} $*"; }
warn() { echo -e "${YELLOW}  !${NC} $*"; }
die()  { echo -e "${RED}error:${NC} $*" >&2; exit 1; }

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

[[ $EUID -eq 0 ]] && warn "Running as root. Docker will work, but consider a normal user in the docker group."

# --- Docker -----------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    say "Installing Docker Engine"
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER" || true
    ok "Docker installed. You may need to log out and back in for group membership."
else
    ok "Docker is already installed ($(docker --version))"
fi

docker compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing. Install docker-compose-plugin."

# Group membership from usermod does not apply to the shell that ran it, so a
# freshly added user still cannot reach the daemon socket until they log back
# in. Fall back to sudo for this run rather than failing.
DC="docker compose"
if ! docker info >/dev/null 2>&1; then
    if sudo -n docker info >/dev/null 2>&1 || sudo docker info >/dev/null 2>&1; then
        DC="sudo docker compose"
        warn "Using sudo for Docker this run. Log out and back in to drop the sudo."
    else
        die "Cannot reach the Docker daemon. Is it running? Try: sudo systemctl start docker"
    fi
fi

# --- Configuration ----------------------------------------------------------

# Writes KEY=VALUE into .env. sed expands an unescaped & in the replacement to
# the whole matched line, and an unescaped | would end the expression early, so
# any value containing them must be escaped or it silently corrupts the file.
set_env() {
    local key="$1" value="$2" escaped
    escaped=$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')
    sed -i "s|^${key}=.*|${key}=${escaped}|" .env
}

# Reads one answer, falling back to a default. Re-asks until the answer matches
# the pattern, so a mistyped or accidentally pasted line cannot reach .env.
ask() {
    local prompt="$1" default="$2" pattern="$3" complaint="$4" answer
    if [[ ! -t 0 ]]; then
        printf '%s' "$default"
        return
    fi
    while true; do
        read -rp "$prompt [$default]: " answer < /dev/tty
        answer="${answer:-$default}"
        if [[ "$answer" =~ $pattern ]]; then
            printf '%s' "$answer"
            return
        fi
        printf '  !\033[0m %s\n' "$complaint" >&2
    done
}

if [[ -f .env ]]; then
    ok ".env already exists, keeping your settings"
    ADMIN_PASSWORD="$(grep -E '^FIRST_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)"
else
    say "Generating .env with fresh secrets"
    cp .env.example .env
    SECRET_KEY="$(openssl rand -hex 32)"
    ENCRYPTION_KEY="$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')"
    DB_PASSWORD="$(openssl rand -hex 16)"
    ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=')"

    set_env SECRET_KEY          "$SECRET_KEY"
    set_env ENCRYPTION_KEY      "$ENCRYPTION_KEY"
    set_env POSTGRES_PASSWORD   "$DB_PASSWORD"
    set_env FIRST_ADMIN_PASSWORD "$ADMIN_PASSWORD"

    ADMIN_EMAIL="$(ask "Administrator email" "admin@example.com" \
        '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' \
        "That does not look like an email address. Try again.")"
    set_env FIRST_ADMIN_EMAIL "$ADMIN_EMAIL"

    WEB_PORT="$(ask "Port to serve on" "8080" \
        '^[0-9]{1,5}$' \
        "A port must be a number between 1 and 65535.")"
    set_env WEB_PORT     "$WEB_PORT"
    set_env PUBLIC_URL   "http://localhost:${WEB_PORT}"
    set_env CORS_ORIGINS "http://localhost:${WEB_PORT}"
    chmod 600 .env
    ok "Wrote .env"
fi

WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2- || true)"
# A bad value here surfaces from docker compose as a cryptic "invalid hostPort",
# so catch it while we can still say what to do about it.
if ! [[ "$WEB_PORT" =~ ^[0-9]{1,5}$ ]] || (( WEB_PORT < 1 || WEB_PORT > 65535 )); then
    die "WEB_PORT in .env is not a valid port: '${WEB_PORT}'
       Fix that line in .env (WEB_PORT=8080, and match PUBLIC_URL and CORS_ORIGINS),
       or delete .env and run this script again to start over."
fi

# --- Build and start --------------------------------------------------------
say "Building images (this takes a few minutes the first time)"
$DC build

say "Starting services"
$DC up -d

# curl is only installed by the Docker branch above, so a server that already had
# Docker may not have it. Probe with whatever is present, and fall back to asking
# the api container itself, which always has curl.
probe_health() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "http://localhost:${WEB_PORT}/health" >/dev/null 2>&1
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O /dev/null "http://localhost:${WEB_PORT}/health" 2>/dev/null
    else
        $DC exec -T api curl -fsS http://localhost:8000/health >/dev/null 2>&1
    fi
}

say "Waiting for the API to become healthy (up to 2 minutes)"
API_READY=0
for _ in $(seq 1 40); do
    if probe_health; then
        API_READY=1
        printf '\n'
        ok "API is responding"
        break
    fi
    printf '.'
    sleep 3
done

echo
if [[ "$API_READY" -eq 1 ]]; then
    echo -e "${GREEN}susoDash is running.${NC}"
else
    # Never claim success we did not observe.
    printf '\n'
    warn "The containers started, but the API did not answer on port ${WEB_PORT} in time."
    warn "It may still be finishing its first boot. Check with:"
    echo "    docker compose ps"
    echo "    docker compose logs api --tail=50"
    echo
    echo -e "${YELLOW}Details below are correct once the API comes up.${NC}"
fi
echo
echo "  URL:      http://localhost:${WEB_PORT}"
echo "  Email:    $(grep -E '^FIRST_ADMIN_EMAIL=' .env | cut -d= -f2-)"
[[ -n "${ADMIN_PASSWORD:-}" ]] && echo "  Password: ${ADMIN_PASSWORD}"
echo
echo "  Logs:     make logs"
echo "  Stop:     make down"
echo "  Backup:   make backup"
echo
echo "Secrets live in ${ROOT}/.env - keep it safe and back it up. If you lose"
echo "ENCRYPTION_KEY, stored Survey Solutions passwords cannot be decrypted."
