# ──────────────────────────────────────────────────────────────
# Argus MCP — Multi-stage Docker build (Rust + Go + Python)
# ──────────────────────────────────────────────────────────────
# Stage 1: Rust builder     — compile 7 PyO3 extension modules
# Stage 2: Go builder       — compile docker-adapter + mcp-stdio-wrapper
# Stage 3: Python builder   — assemble venv with native extensions
# Stage 4: Slim runtime image
#
# Usage:
#   docker build -t argus-mcp .
#   docker run -p 9000:9000 -v ./config.yaml:/app/config.yaml argus-mcp
#
# Mount a custom config:
#   docker run -p 8080:8080 \
#     -v ./my-config.yaml:/app/config.yaml \
#     argus-mcp server --host 0.0.0.0 --port 8080
#
# For stdio-based backend MCP servers that need Node.js (npx):
#   The runtime image includes Node.js LTS for npx-based servers.
# ──────────────────────────────────────────────────────────────

# ── Stage 1: Rust Builder ──────────────────────────────────
# nosemgrep: docker-user-root (builder stage is discarded)
FROM rust:1.94-slim AS rust-builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-dev python3-pip && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY argus_mcp/ ./argus_mcp/
COPY pyproject.toml Cargo.lock* ./

# Build each Rust extension with maturin (abi3 → single .so per crate)
RUN pip install --no-cache-dir --break-system-packages maturin && \
    for crate in \
      argus_mcp/config/_yaml_rs \
      argus_mcp/audit/_audit_rs \
      argus_mcp/bridge/_filter_rs \
      argus_mcp/bridge/auth/_token_cache_rs \
      argus_mcp/bridge/health/_circuit_breaker_rs \
      argus_mcp/plugins/_hash_rs \
      argus_mcp/plugins/builtins_rust; \
    do \
      echo "=== Building $crate ===" && \
      maturin build --release --manifest-path "$crate/Cargo.toml" --out /build/wheels || exit 1; \
    done

# ── Stage 2: Go Builder ───────────────────────────────────
# nosemgrep: docker-user-root (builder stage is discarded)
FROM golang:1.26-alpine AS go-builder

COPY tools/docker-adapter/ /src/docker-adapter/
COPY tools/mcp-stdio-wrapper/ /src/mcp-stdio-wrapper/

RUN cd /src/docker-adapter && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /go-bin/docker-adapter . && \
    cd /src/mcp-stdio-wrapper && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /go-bin/mcp-stdio-wrapper .

# ── Stage 3: Python Builder ───────────────────────────────
# nosemgrep: docker-user-root (builder stage is discarded; runtime uses USER argus)
FROM python:3.14-slim AS builder

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv

WORKDIR /build

# Copy dependency metadata first (cache-friendly layer)
COPY pyproject.toml ./
COPY argus_mcp/ ./argus_mcp/

# Install the package and all runtime dependencies into a virtual env.
# setuptools-rust extensions are optional=true, so no Rust toolchain needed here.
# nosemgrep: docker-pip-no-cache, dependency-docker-no-unpinned-pip-install
RUN uv venv /opt/venv && \
    UV_LINK_MODE=copy uv pip install --no-cache --python /opt/venv/bin/python .

# Install pre-built Rust extension wheels from Stage 1
COPY --from=rust-builder /build/wheels/ /tmp/wheels/
RUN uv pip install --no-cache --python /opt/venv/bin/python /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels

# Place Go binaries in the package's _bin/ directory
COPY --from=go-builder /go-bin/ /opt/venv/lib/python3.14/site-packages/argus_mcp/_bin/

RUN find /opt/venv -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true


# ── Stage 4: Runtime ───────────────────────────────────────
# nosemgrep: docker-user-root (USER argus set below)
FROM python:3.14-slim AS runtime

LABEL org.opencontainers.image.title="Argus MCP" \
      org.opencontainers.image.description="Central aggregation server for MCP (Model Context Protocol) backends" \
      org.opencontainers.image.source="https://github.com/diaz3618/argus-mcp" \
      org.opencontainers.image.licenses="GPL-3.0-only"

# Install Node.js 22 LTS via NodeSource APT repo (GPG-verified, no pipe-to-bash)
# Supply-chain hardening: pinned versions, GPG-verified packages
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    npm cache clean --force && \
    apt-get purge -y curl gnupg && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* \
           /etc/apt/keyrings/nodesource.gpg \
           /etc/apt/sources.list.d/nodesource.list \
           /root/.npm

# Pin pip to known-good version
RUN pip install --no-cache-dir pip==25.1.1

# Copy the pre-built virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Put the venv on PATH
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create non-root user for runtime security
RUN groupadd -r argus && useradd -r -g argus -d /app argus

WORKDIR /app

# Copy example config as fallback (user should mount their own config.yaml)
COPY example_config.yaml ./example_config.yaml
COPY example_config.yaml ./config.yaml

# Create directories for logs, PID files, and session state (owned by argus user)
RUN mkdir -p /app/logs /app/pids /app/.argus/sessions && chown -R argus:argus /app

# Switch to non-root user
USER argus

# Default port
EXPOSE 9000

# Health check via the management API
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/manage/v1/health')" || exit 1

# Run the server bound to all interfaces
ENTRYPOINT ["argus-mcp"]
CMD ["server", "--host", "0.0.0.0", "--port", "9000"]
