.DEFAULT_GOAL := help
COMPOSE := docker compose

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

install: ## Install deps into a local venv (uv)
	uv sync --extra dev

db-up: ## Start local Postgres, load schema + seed venues
	$(COMPOSE) up -d db
	@echo "waiting for postgres..." && sleep 3
	$(COMPOSE) exec -T db psql -U pulse -d pulse -f /docker-entrypoint-initdb.d/00_schema.sql || true
	$(COMPOSE) exec -T db psql -U pulse -d pulse -f /docker-entrypoint-initdb.d/01_seed.sql || true

db-down: ## Stop and remove the local Postgres
	$(COMPOSE) down

run: ## Run the discovery scout over the seeded venues
	uv run discovery-agent

demo: db-up install run ## One-shot: db + deps + scout

lint: ## Ruff check
	uv run ruff check .

format: ## Ruff format
	uv run ruff format .

test: ## Run tests
	uv run pytest -q

.PHONY: help install db-up db-down run demo lint format test
