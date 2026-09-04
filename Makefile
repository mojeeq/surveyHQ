# susoDash operations. Run `make help` for the list.

COMPOSE := docker compose
DEV     := docker compose -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create .env from the template and generate secrets
	@test -f .env && echo ".env already exists, leaving it alone." || ( \
		cp .env.example .env && \
		SECRET=$$(openssl rand -hex 32) && \
		FERNET=$$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())") && \
		DBPASS=$$(openssl rand -hex 16) && \
		ADMINPASS=$$(openssl rand -base64 18 | tr -d '/+=') && \
		sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$$SECRET|" .env && \
		sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$$FERNET|" .env && \
		sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$$DBPASS|" .env && \
		sed -i "s|^FIRST_ADMIN_PASSWORD=.*|FIRST_ADMIN_PASSWORD=$$ADMINPASS|" .env && \
		echo "Created .env with generated secrets." && \
		echo "" && \
		echo "  Administrator: $$(grep '^FIRST_ADMIN_EMAIL=' .env | cut -d= -f2)" && \
		echo "  Password:      $$ADMINPASS" && \
		echo "" && \
		echo "Write those down, then run: make up" )

.PHONY: up
up: ## Build and start the whole stack
	$(COMPOSE) up -d --build
	@echo "susoDash is starting on http://localhost:$${WEB_PORT:-8080}"

.PHONY: down
down: ## Stop the stack (data is kept)
	$(COMPOSE) down

.PHONY: restart
restart: ## Restart every service
	$(COMPOSE) restart

.PHONY: logs
logs: ## Follow logs from every service
	$(COMPOSE) logs -f --tail=100

.PHONY: logs-api
logs-api: ## Follow API logs only
	$(COMPOSE) logs -f --tail=100 api

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: dev
dev: ## Start the stack with hot reload
	$(DEV) up --build

.PHONY: shell
shell: ## Open a shell in the API container
	$(COMPOSE) exec api /bin/bash

.PHONY: psql
psql: ## Open psql on the database
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-surveyhq} -d $${POSTGRES_DB:-surveyhq}

.PHONY: test
test: ## Run the backend test suite
	$(COMPOSE) run --rm -e DATABASE_URL_OVERRIDE=sqlite:////tmp/test.db api \
		python -m pytest tests -q

.PHONY: create-admin
create-admin: ## Create or promote an administrator: make create-admin EMAIL=you@org PASS=secret
	@test -n "$(EMAIL)" || (echo "Usage: make create-admin EMAIL=you@org PASS=secret" && exit 1)
	$(COMPOSE) exec api python -m app.cli create-admin "$(EMAIL)" "$(PASS)"

.PHONY: reset-password
reset-password: ## Reset a password: make reset-password EMAIL=you@org PASS=newsecret
	@test -n "$(EMAIL)" || (echo "Usage: make reset-password EMAIL=you@org PASS=newsecret" && exit 1)
	$(COMPOSE) exec api python -m app.cli reset-password "$(EMAIL)" "$(PASS)"

.PHONY: backup
backup: ## Back up the database and stored datasets into ./backups
	./scripts/backup.sh

.PHONY: restore
restore: ## Restore from a backup: make restore FILE=backups/surveyhq-2026-01-01.tar.gz
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/....tar.gz" && exit 1)
	./scripts/restore.sh "$(FILE)"

.PHONY: update
update: ## Pull the latest code and rebuild
	git pull
	$(COMPOSE) up -d --build
	@echo "Updated. Check 'make logs' for the rollout."

.PHONY: clean
clean: ## Stop the stack and DELETE ALL DATA
	@echo "This deletes the database and every imported dataset."
	@read -p "Type 'delete' to confirm: " answer && [ "$$answer" = "delete" ] || exit 1
	$(COMPOSE) down -v
