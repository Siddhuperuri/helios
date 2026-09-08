# Helios — developer commands.
#
# The project had no task runner, so one is introduced here rather than bent into an
# existing system. It is a thin, readable wrapper: every target is a command you could
# have typed, which means the Makefile documents the workflow instead of hiding it.
#
# `make help` lists everything.

.DEFAULT_GOAL := help
.PHONY: help dev dev-backend dev-frontend install test test-backend test-frontend \
        test-integration lint typecheck migrate migration rollback seed stack stack-down \
        stack-logs prod prod-down build scan load-test load-test-console clean

BACKEND  := backend
FRONTEND := frontend
COMPOSE_DEV  := docker compose -f docker-compose.yml
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

help: ## List the available commands
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------------------

install: ## Install backend and frontend dependencies
	cd $(BACKEND) && python -m pip install -r requirements-dev.txt
	cd $(FRONTEND) && npm ci

# ---------------------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------------------

dev: ## Run the backend and frontend together (Ctrl-C stops both)
	@echo "Backend  → http://127.0.0.1:8000"
	@echo "Frontend → http://localhost:3000"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## Run the API with reload
	cd $(BACKEND) && uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Next.js dev server
	cd $(FRONTEND) && npm run dev

# ---------------------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------------------

test: test-backend test-frontend ## Run every test

test-backend: ## Backend tests (SQLite + in-process Redis stand-in; no services needed)
	cd $(BACKEND) && python -m pytest

test-frontend: ## Frontend tests
	cd $(FRONTEND) && npx vitest run

test-integration: ## Backend tests against real PostgreSQL and Redis
	@# The same suite, including the cross-instance tests, pointed at real infrastructure.
	@# Locally they run against a SQLite file and a named in-process Redis, which does
	@# exercise the shared-state code paths — but only this proves the behaviour against
	@# the engines production actually uses.
	cd $(BACKEND) && \
	  HELIOS_TEST_DATABASE_URL="postgresql+psycopg://helios:helios-dev-password@localhost:5432/helios_test" \
	  HELIOS_TEST_REDIS_URL="redis://localhost:6379/1" \
	  python -m pytest

lint: ## Lint the backend (the frontend has no linter configured — see below)
	cd $(BACKEND) && python -m ruff check app tests scripts alembic
	@# `next lint` is not run: there is no ESLint config or dependency in this project,
	@# so it drops into an interactive setup prompt. `make typecheck` is the frontend gate.

typecheck: ## Type-check both sides
	cd $(BACKEND) && python -m mypy app --ignore-missing-imports
	cd $(FRONTEND) && npx tsc --noEmit

# ---------------------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------------------

migrate: ## Apply migrations up to head
	cd $(BACKEND) && python -m alembic upgrade head

migration: ## Autogenerate a migration — make migration m="add widget table"
	@test -n "$(m)" || (echo 'Usage: make migration m="what changed"'; exit 1)
	cd $(BACKEND) && python -m alembic revision --autogenerate -m "$(m)"
	@echo
	@echo "Read the generated file before committing it. Autogenerate does not know about"
	@echo "rolling deployments: during a deploy the old release and the new one both talk to"
	@echo "this database, so a dropped or renamed column breaks the release still running."
	@echo "Add nullable, backfill, ship, remove later."

rollback: ## Step one migration back
	cd $(BACKEND) && python -m alembic downgrade -1

seed: ## Create sample accounts and estimates for development
	cd $(BACKEND) && python -m scripts.seed

# ---------------------------------------------------------------------------------------
# Stacks
# ---------------------------------------------------------------------------------------

stack: ## Start the development stack (Postgres, Redis, one backend, one frontend)
	$(COMPOSE_DEV) up --build -d
	@echo "Frontend → http://localhost:3000"
	@echo "API      → http://localhost:8000/api/docs"

stack-down: ## Stop the development stack
	$(COMPOSE_DEV) down

stack-logs: ## Follow the development stack's logs
	$(COMPOSE_DEV) logs -f

prod: ## Start the production topology (3 backends, 2 frontends, Nginx, PgBouncer)
	@test -f .env.production || (echo "Create .env.production from .env.example first"; exit 1)
	$(COMPOSE_PROD) --env-file .env.production up --build -d
	@echo "Site → http://localhost"

prod-down: ## Stop the production topology
	$(COMPOSE_PROD) down

build: ## Build both production images
	docker build -t helios-backend:local $(BACKEND)
	docker build -t helios-frontend:local $(FRONTEND)

scan: build ## Scan both images for vulnerabilities (fails on HIGH or CRITICAL)
	trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed helios-backend:local
	trivy image --exit-code 1 --severity HIGH,CRITICAL --ignore-unfixed helios-frontend:local

# ---------------------------------------------------------------------------------------
# Load testing
# ---------------------------------------------------------------------------------------

load-test: ## Consumer path load test — see docs/LOAD_TESTING.md
	cd loadtest && locust -f consumer.py --host $${HELIOS_HOST:-http://localhost}

load-test-console: ## Analysis console load test (CPU-heavy, 10-40s requests)
	cd loadtest && locust -f console.py --host $${HELIOS_HOST:-http://localhost}

# ---------------------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------------------

clean: ## Remove build artefacts and caches
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(BACKEND)/.mypy_cache
	rm -rf $(FRONTEND)/.next $(FRONTEND)/tsconfig.tsbuildinfo
