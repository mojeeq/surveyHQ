#!/usr/bin/env bash
# One-shot installer for SurveyHQ on Ubuntu 22.04 / 24.04.
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

    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET_KEY}|"                   .env
    sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENCRYPTION_KEY}|"       .env
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|"    .env
    sed -i "s|^FIRST_ADMIN_PASSWORD=.*|FIRST_ADMIN_PASSWORD=${ADMIN_PASSWORD}|" .env

    read -rp "Administrator email [admin@example.com]: " ADMIN_EMAIL
    ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
    sed -i "s|^FIRST_ADMIN_EMAIL=.*|FIRST_ADMIN_EMAIL=${ADMIN_EMAIL}|" .env

    read -rp "Port to serve on [8080]: " WEB_PORT
    WEB_PORT="${WEB_PORT:-8080}"
    sed -i "s|^WEB_PORT=.*|WEB_PORT=${WEB_PORT}|" .env
    sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=http://localhost:${WEB_PORT}|" .env
    sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:${WEB_PORT}|" .env
    chmod 600 .env
    ok "Wrote .env"
fi

WEB_PORT="$(grep -E '^WEB_PORT=' .env | cut -d= -f2 || echo 8080)"

# --- Build and start --------------------------------------------------------
say "Building images (this takes a few minutes the first time)"
$DC build

say "Starting services"
$DC up -d

say "Waiting for the API to become healthy"
for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:${WEB_PORT}/health" >/dev/null 2>&1; then
        ok "API is responding"
        break
    fi
    sleep 3
done

echo
echo -e "${GREEN}SurveyHQ is running.${NC}"
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
