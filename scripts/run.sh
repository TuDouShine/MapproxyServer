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

SCRIPT_DIR="$(get_script_dir)"
PARENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$PARENT_DIR/main.py" ] && [ -d "$PARENT_DIR/src" ]; then
    WORK_DIR="$PARENT_DIR"
elif [ -f "$SCRIPT_DIR/main.py" ] && [ -d "$SCRIPT_DIR/src" ]; then
    WORK_DIR="$SCRIPT_DIR"
else
    echo "[ERROR] Unable to locate project root from script directory: $SCRIPT_DIR" >&2
    echo "[ERROR] Expected 'main.py' and 'src/' in script directory or its parent." >&2
    exit 1
fi
PORT="${1:-8080}"

# Navigate to work directory
cd "$WORK_DIR"

# Colors for logging
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

print_install_hint() {
    local need_venv="$1"
    local need_tk="$2"

    if [ -f /etc/debian_version ]; then
        local pkgs=()
        if [ "$need_venv" -eq 1 ]; then
            pkgs+=("python3-venv")
        fi
        if [ "$need_tk" -eq 1 ]; then
            pkgs+=("python3-tk")
        fi
        if [ ${#pkgs[@]} -gt 0 ]; then
            log_info "Detected Debian/Ubuntu system."
            log_info "Please run the following command:"
            echo -e "${YELLOW}    sudo apt-get update && sudo apt-get install -y ${pkgs[*]}${NC}"
        fi
    elif [ -f /etc/redhat-release ]; then
        local pkgs=()
        if [ "$need_venv" -eq 1 ]; then
            pkgs+=("python3-virtualenv")
        fi
        if [ "$need_tk" -eq 1 ]; then
            pkgs+=("python3-tkinter")
        fi
        if [ ${#pkgs[@]} -gt 0 ]; then
            log_info "Detected RHEL/CentOS/Fedora system."
            echo -e "${YELLOW}    sudo dnf install ${pkgs[*]}${NC}"
        fi
    else
        if [ "$need_venv" -eq 1 ] && [ "$need_tk" -eq 1 ]; then
            log_info "Please install both 'python3-venv' and 'python3-tk' packages for your Linux distribution."
        elif [ "$need_venv" -eq 1 ]; then
            log_info "Please install the 'python3-venv' package for your Linux distribution."
        elif [ "$need_tk" -eq 1 ]; then
            log_info "Please install the 'python3-tk' package for your Linux distribution."
        fi
    fi
}

# 1. Environment Check
log_info "Checking environment..."

# Check Python 3 availability
if ! command -v python3 &> /dev/null; then
    log_error "Python 3 is not installed. Please install python3."
    exit 1
fi

PYTHON_EXEC="$(command -v python3)"
log_info "Using Python interpreter: $PYTHON_EXEC"

# Check Write Permissions
if [ ! -w "$WORK_DIR" ]; then
    log_error "No write permission in work directory: $WORK_DIR"
    log_error "Please check file permissions."
    exit 1
fi

# 2. Dependency Check (venv/ensurepip)
log_info "Checking virtual environment support..."

MISSING_VENV=0
MISSING_TK=0

if ! "$PYTHON_EXEC" -c "import ensurepip" &> /dev/null; then
    MISSING_VENV=1
fi

if ! "$PYTHON_EXEC" -c "import tkinter" &> /dev/null; then
    MISSING_TK=1
fi

if [ "$MISSING_VENV" -eq 1 ]; then
    log_error "The 'ensurepip' module is missing. This prevents creating a virtual environment."
    log_error "Root cause: The 'python3-venv' package is likely not installed."
    if [ "$MISSING_TK" -eq 1 ]; then
        log_warn "The 'tkinter' module is also missing. GUI mode may not work until 'python3-tk' is installed."
    fi
    print_install_hint "$MISSING_VENV" "$MISSING_TK"
    exit 1
fi

if [ "$MISSING_TK" -eq 1 ]; then
    log_warn "The 'tkinter' module is missing. GUI mode may not work."
    print_install_hint 0 "$MISSING_TK"
fi

# 3. Launch Main Script

# Pre-flight check for venv integrity (if it exists)
VENV_DIR="$WORK_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    # Check for mapproxy-seed in standard Linux venv path
    SEED_BIN="$VENV_DIR/bin/mapproxy-seed"
    if [ ! -f "$SEED_BIN" ]; then
        log_warn "Virtual environment exists but '$SEED_BIN' is missing."
        log_warn "This may indicate a broken installation or missing dependencies."
        log_warn "The main script will attempt to reinstall dependencies."
    fi
fi

log_info "Launching MapProxy Server..."
log_info "Work Dir: $WORK_DIR"
log_info "Port: $PORT"

# Pass the explicitly resolved python path to main.py to ensure consistency
exec "$PYTHON_EXEC" main.py --service --port "$PORT" --host "0.0.0.0" --work-dir "$WORK_DIR" --python-path "$PYTHON_EXEC"
