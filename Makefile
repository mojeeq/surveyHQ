# SurveyHQ operations. Run `make help` for the list.

# Which stack a target acts on. Two can run side by side on one machine, each
# with its own containers, database, data volumes and ports:
#   make up                  development, configured by .env (the only stack on
#                            a single install)
#   make up STACK=prod       production, configured by .env.prod
# See "Development and production on one server" in docs/deployment.md.
STACK ?= dev
ifeq ($(STACK),dev)
ENV_FILE      := .env
STACK_BACKUPS := backups
else ifeq ($(STACK),prod)
ENV_FILE      := .env.prod
STACK_BACKUPS := backups/prod
else
$(error STACK must be dev or prod, not "$(STACK)")
endif
# A BACKUP_DIR set in the environment still wins, as it always has.
BACKUP_DIR ?= $(STACK_BACKUPS)
export SURVEYHQ_ENV_FILE := $(ENV_FILE)
export BACKUP_DIR

COMPOSE := docker compose --env-file $(ENV_FILE)
DEV     := $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the stack's env file and generate secrets (STACK=prod for .env.prod)
	./scripts/setup-env.sh $(STACK)

# Both stacks build from this checkout, so production is built from whatever
# is in it at the time. A tree with uncommitted changes would put them live
# with no commit to say what they were; FORCE=1 accepts that knowingly.
.PHONY: prod-guard
prod-guard:
ifeq ($(STACK),prod)
	@test -f $(ENV_FILE) || (echo "No $(ENV_FILE) yet. Run: make setup STACK=prod" && exit 1)
	@if [ -z "$(FORCE)" ] && [ -n "$$(git status --porcelain)" ]; then \
		echo "Uncommitted changes in this checkout would be built into production:"; \
		git status --short; \
		echo "Commit or stash them, or run again with FORCE=1."; \
		exit 1; \
	fi
	@echo "Building production from $$(git rev-parse --abbrev-ref HEAD) at $$(git rev-parse --short HEAD)"
endif

.PHONY: up
up: prod-guard ## Build and start the whole stack
	$(COMPOSE) up -d --build
	@echo "SurveyHQ ($(STACK)) is starting on http://localhost:$$(grep -E '^WEB_PORT=' $(ENV_FILE) | cut -d= -f2 | grep . || echo 8080)"

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
dev: ## Start the development stack with hot reload
ifeq ($(STACK),prod)
	@echo "Hot reload mounts the source into the containers; it is for development only." && exit 1
endif
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

.PHONY: import
import: ## Import a file staged in ./incoming: make import FILE=/incoming/roster.dta PROJECT="Household Census 2017"
	@test -n "$(FILE)" || (echo 'Usage: make import FILE=/incoming/file.dta [PROJECT="Name"] [NAME="Dataset"]' && exit 1)
	$(COMPOSE) exec api python -m app.cli import "$(FILE)" $(if $(PROJECT),--project "$(PROJECT)") $(if $(NAME),--name "$(NAME)") $(if $(USER_EMAIL),--user "$(USER_EMAIL)")

.PHONY: backup
backup: ## Back up the database and stored datasets into ./backups (production: ./backups/prod)
	./scripts/backup.sh

.PHONY: restore
restore: ## Restore from a backup: make restore FILE=backups/surveyhq-2026-01-01.tar.gz
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/....tar.gz" && exit 1)
	./scripts/restore.sh "$(FILE)"

.PHONY: copy-prod-to-dev
copy-prod-to-dev: ## Replace development's data with production's: make copy-prod-to-dev [FILE=backups/prod/....tar.gz]
	./scripts/copy-prod-to-dev.sh $(if $(FILE),"$(FILE)")

.PHONY: update
update: ## Pull the latest code and rebuild
	git pull
	$(MAKE) up
	@echo "Updated. Check 'make logs$(if $(filter prod,$(STACK)), STACK=prod)' for the rollout."

.PHONY: clean
clean: ## Stop the stack and DELETE ALL DATA
	@echo "This deletes the $(STACK) stack's database and every imported dataset."
	@read -p "Type 'delete $(STACK)' to confirm: " answer && [ "$$answer" = "delete $(STACK)" ] || exit 1
	$(COMPOSE) down -v
