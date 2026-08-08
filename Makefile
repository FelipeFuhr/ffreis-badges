SHELL := /bin/bash

COVERAGE_MIN     ?= 75
GITLEAKS         ?= gitleaks
LEFTHOOK_VERSION ?= 1.7.10
LEFTHOOK_DIR     ?= $(CURDIR)/.bin
LEFTHOOK_BIN     ?= $(LEFTHOOK_DIR)/lefthook

.PHONY: help fmt fmt-check lint test coverage coverage-gate quality-gates \
        secrets-scan-staged \
        lefthook-bootstrap lefthook-install lefthook-run lefthook setup

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

fmt: ## Format code with ruff
	uv run ruff format .

fmt-check: ## Fail if code is not formatted
	uv run ruff format --check .

lint: ## Run ruff + mypy
	uv run ruff check .
	uv run mypy scripts tests

test: ## Run tests
	uv run pytest

coverage: ## Run tests with coverage gate (fails below COVERAGE_MIN)
	uv run pytest --cov --cov-fail-under=$(COVERAGE_MIN)

coverage-gate: coverage ## Coverage floor gate (alias used by the complex lefthook tier)

quality-gates: ## Full pre-push quality gates
	$(MAKE) fmt-check
	$(MAKE) lint
	$(MAKE) coverage

secrets-scan-staged: ## Scan staged diff for secrets
	@command -v $(GITLEAKS) >/dev/null 2>&1 || { echo "Missing tool: $(GITLEAKS)"; exit 1; }
	$(GITLEAKS) protect --staged --redact

lefthook-bootstrap: ## Download lefthook binary into ./.bin
	LEFTHOOK_VERSION="$(LEFTHOOK_VERSION)" BIN_DIR="$(LEFTHOOK_DIR)" bash ./scripts/bootstrap_lefthook.sh

lefthook-install: lefthook-bootstrap ## Install git hooks if missing
	@if [ -x "$(LEFTHOOK_BIN)" ] && [ -x ".git/hooks/pre-commit" ] && [ -x ".git/hooks/commit-msg" ]; then \
		echo "lefthook hooks already installed"; exit 0; \
	fi
	LEFTHOOK="$(LEFTHOOK_BIN)" "$(LEFTHOOK_BIN)" install

lefthook-run: lefthook-bootstrap ## Run hooks
	LEFTHOOK="$(LEFTHOOK_BIN)" "$(LEFTHOOK_BIN)" run pre-commit
	@tmp_msg="$$(mktemp)"; \
	echo "chore(hooks): validate commit-msg hook" > "$$tmp_msg"; \
	LEFTHOOK="$(LEFTHOOK_BIN)" "$(LEFTHOOK_BIN)" run commit-msg -- "$$tmp_msg"; \
	rm -f "$$tmp_msg"

lefthook: lefthook-bootstrap lefthook-install lefthook-run ## Install hooks and run them

setup: lefthook-install ## Bootstrap hooks and sync dependencies
	uv sync
	@echo "Dev environment ready."
