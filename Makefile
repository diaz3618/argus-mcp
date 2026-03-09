# ──────────────────────────────────────────────────────────────
# Argus MCP — Project Makefile
# ──────────────────────────────────────────────────────────────
#
# Targets:
#   Testing & Quality    test, lint, typecheck, security, quality
#   Docker               docker-build
#   Utilities            clean, dev-install
#
# Release targets live in Makefile.release (not tracked in git).
#
# Prerequisites:
#   uv, docker, semgrep, snyk
# ──────────────────────────────────────────────────────────────

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Load .env (if present) and export all variables ─────────
-include .env
export

# ── Project metadata (read from pyproject.toml) ─────────────
VERSION := $(shell python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null || echo "0.0.0")
IMAGE_DOCKERHUB := diaz3618/argus-mcp

# ── Semgrep rule packs tailored to this project ─────────────
SEMGREP_PACKS := p/python p/security-audit p/secrets p/dockerfile

# ── Help ────────────────────────────────────────────────────
.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ══════════════════════════════════════════════════════════════
# Testing & Quality
# ══════════════════════════════════════════════════════════════

.PHONY: test
test: ## Run pytest suite
	uv run pytest tests/ -q

.PHONY: lint
lint: ## Run ruff linter
	uv run ruff check argus_mcp/ tests/

.PHONY: typecheck
typecheck: ## Run mypy type checker
	uv run mypy argus_mcp/

.PHONY: semgrep
semgrep: ## Run semgrep (custom + registry rules)
	semgrep scan --config .semgrep.yml $(addprefix --config ,$(SEMGREP_PACKS)) argus_mcp/

.PHONY: snyk
snyk: ## Run Snyk code scan (SAST)
	snyk code test --severity-threshold=medium

.PHONY: snyk-sca
snyk-sca: ## Run Snyk SCA scan (dependency vulnerabilities)
	uv export --format requirements-txt --no-hashes --no-emit-project 2>/dev/null | \
		grep -v '^\s*#' | grep -v '^\s*$$' | sed 's/ ;.*//' > .snyk-requirements.txt
	snyk test --file=.snyk-requirements.txt --package-manager=pip --severity-threshold=medium; \
		SCA_EXIT=$$?; rm -f .snyk-requirements.txt; \
		if [ $$SCA_EXIT -ne 0 ]; then exit $$SCA_EXIT; fi

.PHONY: security
security: semgrep snyk ## Run all security scans (semgrep + snyk)

.PHONY: quality
quality: lint typecheck test security ## Full quality gate (lint + types + tests + security)

# ══════════════════════════════════════════════════════════════
# Docker — Build
# ══════════════════════════════════════════════════════════════

.PHONY: docker-build
docker-build: ## Build Docker image (local, current arch)
	docker build -t $(IMAGE_DOCKERHUB):$(VERSION) -t $(IMAGE_DOCKERHUB):latest .
	@echo "Built $(IMAGE_DOCKERHUB):$(VERSION)"

# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

.PHONY: dev-install
dev-install: ## Install project + dev dependencies via uv
	uv sync --group dev

.PHONY: clean
clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info argus_mcp.egg-info/
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
