#!/bin/bash
set -euo pipefail

# MapProxy Server Linux Start Script
# Usage: ./run.sh [port]

# Resolve script directory correctly, handling symlinks
get_script_dir() {
  local source="${BASH_SOURCE[0]}"
  while [ -h "$source" ]; do
    local dir="$( cd -P "$( dirname "$source" )" && pwd )"
    source="$(readlink "$source")"
    [[ $source != /* ]] && source="$dir/$source"
  done
  echo "$( cd -P "$( dirname "$source" )" && pwd )"
}

WORK_DIR="$(get_script_dir)"
PORT="${1:-8080}"

# Navigate to work directory
cd "$WORK_DIR"

# Colors for logging
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
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
log_info "Launching MapProxy Server..."
log_info "Work Dir: $WORK_DIR"
log_info "Port: $PORT"

# Use exec to replace the shell process with python
exec python3 main.py --service --port "$PORT" --work-dir "$WORK_DIR"
