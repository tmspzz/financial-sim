#!/usr/bin/env bash
# setup.sh — one-time developer setup for tax-risk-sim
# Run this once after cloning. It checks required tools and installs RTK.
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}!${RESET} $*"; }
fail() { echo -e "${RED}✗${RESET} $*"; }

echo -e "\n${BOLD}tax-risk-sim — developer setup${RESET}\n"

# ── 1. Docker ─────────────────────────────────────────────────────────────────
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    ok "Docker is running ($(docker --version | awk '{print $3}' | tr -d ','))"
else
    fail "Docker not found or not running."
    echo "   Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    echo "   Start it, then re-run this script."
    exit 1
fi

# ── 2. Git ────────────────────────────────────────────────────────────────────
if command -v git &>/dev/null; then
    ok "git is available ($(git --version | awk '{print $3}'))"
else
    fail "git not found. Install via your package manager or https://git-scm.com"
    exit 1
fi

# ── 3. RTK (Rust Token Killer) ────────────────────────────────────────────────
# RTK is a transparent CLI proxy that reduces AI agent token consumption by
# 60–90% by filtering and compressing command output. It integrates automatically
# with Claude Code, Cursor, Copilot, and other AI coding tools — no agent-side
# changes needed.
echo ""
if command -v rtk &>/dev/null; then
    ok "rtk is already installed ($(rtk --version 2>/dev/null || echo 'version unknown'))"
else
    warn "rtk not found — installing..."
    OS="$(uname -s)"
    if [[ "$OS" == "Darwin" ]] && command -v brew &>/dev/null; then
        brew install rtk
    else
        curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh | sh
    fi
    if command -v rtk &>/dev/null; then
        ok "rtk installed successfully"
    else
        warn "rtk install may need a shell restart. Run: source ~/.zshrc  (or ~/.bashrc)"
    fi
fi

# ── 4. Pull the Docker image ──────────────────────────────────────────────────
echo ""
echo "Pulling the project Docker image (this is slow once, fast after)..."
docker pull quay.io/jupyter/scipy-notebook:latest
ok "Docker image ready"

# ── 5. Smoke test ─────────────────────────────────────────────────────────────
echo ""
echo "Running quality checks inside Docker to verify the setup..."
docker run --rm \
  -v "$PWD":/home/jovyan/work \
  -w /home/jovyan/work \
  -e PYTHONPATH=/home/jovyan/work/src \
  quay.io/jupyter/scipy-notebook:latest \
  sh -lc "python -m pip install --quiet -r requirements-dev.txt && pytest -q && ruff format --check src scripts tests && ruff check src scripts tests"
ok "All checks pass"

echo ""
echo -e "${BOLD}Setup complete.${RESET}"
echo ""
echo "Start JupyterLab:"
echo "  docker compose up"
echo ""
echo "Then open: http://localhost:8888/lab"
echo ""
