SHELL := /bin/sh

PYTHON ?= python3
VENV ?= .venv
COMPOSE ?= docker compose

.PHONY: help bootstrap doctor run test lint format docker-build up down logs clean

help:
	@printf '%s\n' \
		'Crypto Signal Agent MVP' \
		'' \
		'Targets:' \
		'  make bootstrap     Create local folders, venv, and .env when missing' \
		'  make doctor        Validate local configuration' \
		'  make run           Run the local agent entry point' \
		'  make test          Run pytest when available' \
		'  make lint          Run ruff check when available' \
		'  make format        Run ruff format when available' \
		'  make docker-build  Build the Docker image' \
		'  make up            Start Docker Compose service' \
		'  make down          Stop Docker Compose service' \
		'  make logs          Follow Docker Compose logs'

bootstrap:
	@scripts/bootstrap.sh

doctor:
	@scripts/doctor.sh

run:
	@scripts/run-local.sh

test:
	@if [ -x "$(VENV)/bin/python" ]; then PY="$(VENV)/bin/python"; else PY="$(PYTHON)"; fi; \
	$$PY -m pytest tests

lint:
	@if [ -x "$(VENV)/bin/ruff" ]; then "$(VENV)/bin/ruff" check .; \
	elif command -v ruff >/dev/null 2>&1; then ruff check .; \
	else echo "ruff is not installed"; exit 1; fi

format:
	@if [ -x "$(VENV)/bin/ruff" ]; then "$(VENV)/bin/ruff" format .; \
	elif command -v ruff >/dev/null 2>&1; then ruff format .; \
	else echo "ruff is not installed"; exit 1; fi

docker-build:
	@docker build -t crypto-agent-mvp:local .

up:
	@$(COMPOSE) up -d --build

down:
	@$(COMPOSE) down

logs:
	@$(COMPOSE) logs -f crypto-agent

clean:
	@rm -rf .pytest_cache .ruff_cache htmlcov .coverage
