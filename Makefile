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
help:
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ══════════════════════════════════════════════════════════════
# Native Extensions (Rust + Go)
# ══════════════════════════════════════════════════════════════

.PHONY: rust-build
rust-build: ## Build all Rust PyO3 extensions (maturin)
	python scripts/build_rust.py

.PHONY: rust-check
rust-check: ## Check Rust toolchain availability
	@python scripts/build_rust.py --check

.PHONY: go-build
go-build: ## Build argusd Go daemon
	python scripts/build_go.py

.PHONY: go-check
go-check: ## Check Go toolchain availability
	@python scripts/build_go.py --check

.PHONY: go-build-all
go-build-all: ## Cross-compile argusd for all platforms
	python scripts/build_go.py --all

.PHONY: build-extensions
build-extensions: ## Build all native extensions (Rust + Go)
	@echo "══ Building Rust extensions ══"
	@python scripts/build_rust.py
	@echo ""
	@echo "══ Building Go daemon ══"
	@python scripts/build_go.py

# ══════════════════════════════════════════════════════════════
# Testing & Quality
# ══════════════════════════════════════════════════════════════

.PHONY: test
test:
	uv run pytest tests/ -q

.PHONY: lint
lint:
	uv run ruff check argus_mcp/ tests/

.PHONY: typecheck
typecheck:
	uv run mypy argus_mcp/

.PHONY: semgrep
semgrep:
	semgrep scan --config .semgrep.yml $(addprefix --config ,$(SEMGREP_PACKS)) argus_mcp/

.PHONY: snyk
snyk:
	snyk code test --severity-threshold=medium

.PHONY: snyk-sca
snyk-sca:
	uv export --format requirements-txt --no-hashes --no-emit-project 2>/dev/null | \
		grep -v '^\s*#' | grep -v '^\s*$$' | sed 's/ ;.*//' > .snyk-requirements.txt
	snyk test --file=.snyk-requirements.txt --package-manager=pip --severity-threshold=medium; \
		SCA_EXIT=$$?; rm -f .snyk-requirements.txt; \
		if [ $$SCA_EXIT -ne 0 ]; then exit $$SCA_EXIT; fi

.PHONY: security
security: semgrep snyk

.PHONY: quality
quality: lint typecheck test security

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
dev-install: ## Install project + dev dependencies via uv, then build native extensions
	uv sync --group dev
	@echo ""
	@echo "══ Building native extensions (optional) ══"
	@python scripts/build_rust.py || echo "  Skipping Rust extensions (toolchain not available)"
	@python scripts/build_go.py || echo "  Skipping Go daemon (toolchain not available)"

.PHONY: clean
clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info argus_mcp.egg-info/
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
