# ──────────────────────────────────────────────────────────────
# Argus MCP — Project Makefile
# ──────────────────────────────────────────────────────────────
#
# Targets:
#   Testing & Quality    test, lint, typecheck, security, quality
#   Docker               docker-build
#   Install              dev-install, install-all
#   Uninstall            uninstall, uninstall-cli, uninstall-all
#
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
rust-build:
	python scripts/build_rust.py

.PHONY: rust-check
rust-check:
	@python scripts/build_rust.py --check

.PHONY: go-build
go-build:
	python scripts/build_go.py

.PHONY: go-check
go-check:
	@python scripts/build_go.py --check

.PHONY: go-build-all
go-build-all:
	python scripts/build_go.py --all

.PHONY: build-extensions
build-extensions:
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
docker-build:
	docker build -t $(IMAGE_DOCKERHUB):$(VERSION) -t $(IMAGE_DOCKERHUB):latest .
	@echo "Built $(IMAGE_DOCKERHUB):$(VERSION)"

.PHONY: docker-build-dhi
docker-build-dhi: ## Build DHI (Chainguard) Docker image
	docker build -f Dockerfile.dhi -t $(IMAGE_DOCKERHUB)-dhi:$(VERSION) -t $(IMAGE_DOCKERHUB)-dhi:latest .
	@echo "Built $(IMAGE_DOCKERHUB)-dhi:$(VERSION)"

# ══════════════════════════════════════════════════════════════
# Utilities
# ══════════════════════════════════════════════════════════════

.PHONY: dev-install
dev-install:
	uv sync --group dev
	@echo ""
	@echo "══ Building native extensions (optional) ══"
	@python scripts/build_rust.py || echo "  Skipping Rust extensions (toolchain not available)"
	@python scripts/build_go.py || echo "  Skipping Go daemon (toolchain not available)"

.PHONY: install-all
install-all: ## Install argus-mcp + argus-cli + all Rust/Go extensions
	@echo "══ Step 1/5: Installing dependencies ══"
	uv sync --group dev --no-install-project
	@echo ""
	@echo "══ Step 2/5: Building Rust PyO3 extensions ══"
	@python scripts/build_rust.py || echo "  ⚠ Skipping Rust extensions (toolchain not available)"
	@echo ""
	@echo "══ Step 3/5: Building Go binaries (argusd + docker-adapter) ══"
	@python scripts/build_go.py || echo "  ⚠ Skipping Go binaries (toolchain not available)"
	@echo ""
	@echo "══ Step 4/5: Installing argus-mcp (editable) ══"
	uv pip install setuptools setuptools-rust
	uv pip install -e . --no-build-isolation
	@echo ""
	@echo "══ Step 5/5: Installing argus-cli (editable) ══"
	uv pip install -e packages/argus_cli
	@echo ""
	@echo "══ All done ══"
	@echo "  argus-mcp:  $$(which argus-mcp 2>/dev/null || echo 'not on PATH')"
	@echo "  argus-cli:  $$(python -c 'import argus_cli; print(argus_cli.__file__)' 2>/dev/null || echo 'installed')"
	@echo "  Rust exts:  $$(python -c 'from argus_mcp.config._yaml_rs import yaml_rs; print("available")' 2>/dev/null || echo 'not built')"
	@echo "  argusd:     $$(ls packages/argusd/argusd 2>/dev/null || echo 'not built')"

.PHONY: uninstall
uninstall:
	uv pip uninstall argus-mcp 2>/dev/null || pip uninstall -y argus-mcp 2>/dev/null || true
	@echo "argus-mcp uninstalled"

.PHONY: uninstall-cli
uninstall-cli:
	uv pip uninstall argus-cli 2>/dev/null || pip uninstall -y argus-cli 2>/dev/null || true
	@echo "argus-cli uninstalled"

.PHONY: uninstall-all
uninstall-all:
	uv pip uninstall argus-mcp argus-cli 2>/dev/null || pip uninstall -y argus-mcp argus-cli 2>/dev/null || true
	rm -f packages/argusd/argusd
	rm -rf packages/argusd/dist/
	rm -f tools/docker-adapter/docker-adapter
	@echo "argus-mcp, argus-cli, and built binaries removed"

.PHONY: clean
clean:
	rm -rf build/ dist/ *.egg-info argus_mcp.egg-info/
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
