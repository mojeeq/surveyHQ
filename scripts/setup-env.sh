#!/usr/bin/env bash
# Create a stack's env file from the template, with generated secrets.
#
#   scripts/setup-env.sh          .env      - the development stack, or the only
#                                             stack on a single install
#   scripts/setup-env.sh prod     .env.prod - a production stack beside it
#
# The production file differs from the template in what keeps two stacks on
# one machine apart: its own compose project name (so its own containers,
# database and data volumes), its own ports and its own staging folder. Its
# secrets are generated fresh rather than copied, so a sign-in token or a
# stored connection password from one stack means nothing to the other.
set -euo pipefail
cd "$(dirname "$0")/.."

STACK="${1:-dev}"
case "$STACK" in
    dev)  FILE=.env ;;
    prod) FILE=.env.prod ;;
    *)    echo "Usage: $0 [dev|prod]" >&2; exit 1 ;;
esac

if [[ -f "$FILE" ]]; then
    echo "$FILE already exists, leaving it alone."
    exit 0
fi

SECRET=$(openssl rand -hex 32)
FERNET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
DBPASS=$(openssl rand -hex 16)
ADMINPASS=$(openssl rand -base64 18 | tr -d '/+=')

cp .env.example "$FILE"
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" "$FILE"
sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$FERNET|" "$FILE"
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DBPASS|" "$FILE"
sed -i "s|^FIRST_ADMIN_PASSWORD=.*|FIRST_ADMIN_PASSWORD=$ADMINPASS|" "$FILE"

if [[ "$STACK" == prod ]]; then
    sed -i "s|^#\?COMPOSE_PROJECT_NAME=.*|COMPOSE_PROJECT_NAME=surveyhq-prod|" "$FILE"
    sed -i "s|^#\?INCOMING_DIR=.*|INCOMING_DIR=./incoming-prod|" "$FILE"
    sed -i "s|^WEB_PORT=.*|WEB_PORT=8081|" "$FILE"
    sed -i "s|^API_PORT=.*|API_PORT=8001|" "$FILE"
    sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=http://localhost:8081|" "$FILE"
    sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://localhost:8081|" "$FILE"
    mkdir -p incoming-prod
fi

echo "Created $FILE with generated secrets."
echo ""
echo "  Administrator: $(grep '^FIRST_ADMIN_EMAIL=' "$FILE" | cut -d= -f2)"
echo "  Password:      $ADMINPASS"
echo ""
if [[ "$STACK" == prod ]]; then
    echo "Set PUBLIC_URL, CORS_ORIGINS and FIRST_ADMIN_EMAIL in $FILE to the"
    echo "production values, write the password down, then run: make up STACK=prod"
else
    echo "Write those down, then run: make up"
fi
