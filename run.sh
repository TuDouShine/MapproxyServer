#!/bin/bash

# MapProxy Server Linux Start Script
# usage: ./run.sh [port]

PORT=${1:-8080}
WORK_DIR=$(dirname "$(readlink -f "$0")")
cd "$WORK_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# 1. Environment Check
log_info "Checking environment..."

if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Please install python3."
    exit 1
fi

# Check for python3-venv (Debian/Ubuntu specific issue)
if ! python3 -m venv --help &> /dev/null; then
    log_error "python3-venv module is missing."
    log_error "On Ubuntu/Debian, please run: sudo apt-get install python3-venv"
    exit 1
fi

# 2. Launch Main Script
# main.py handles venv creation, dependency installation, and service startup
log_info "Launching MapProxy Server..."
exec python3 main.py --service --port "$PORT" --work-dir "$WORK_DIR"
