#!/usr/bin/env bash
# ==============================================================================
# Public Intelligence - One-Click Host Node Installer & Hardware Auto-Discovery
# ==============================================================================
set -e

# Color output definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

DRY_RUN=false
FORCE=false
SKIP_DOCKER=false
SKIP_VENV=false

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_dry_run() {
    echo -e "${MAGENTA}[DRY-RUN]${NC} $1"
}

usage() {
    echo "Public Intelligence One-Click Host Node Installer"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --dry-run       Simulate installation, hardware discovery, and configuration without making changes"
    echo "  --force         Force overwrite existing .env configuration and virtual environment"
    echo "  --skip-docker   Skip Docker daemon connectivity requirement check"
    echo "  --skip-venv     Skip Python virtual environment creation"
    echo "  -h, --help      Display this help message"
    exit 0
}

# Parse command-line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --skip-docker)
            SKIP_DOCKER=true
            shift
            ;;
        --skip-venv)
            SKIP_VENV=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

echo -e "${BLUE}"
echo "=============================================================================="
echo "          Public Intelligence Decentralized Compute Node Installer            "
echo "=============================================================================="
echo -e "${NC}"

if [[ "$DRY_RUN" == "true" ]]; then
    log_dry_run "Executing installer in DRY-RUN mode. System state will NOT be modified."
fi

# ------------------------------------------------------------------------------
# 1. Multi-Platform Hardware Auto-Discovery
# ------------------------------------------------------------------------------
detect_hardware() {
    log_info "Detecting host system hardware capabilities..."

    OS_TYPE="$(uname -s)"
    ARCH="$(uname -m)"

    CPU_CORES=0
    TOTAL_RAM_BYTES=0
    GPU_NAME="None"
    GPU_VENDOR="None"
    VRAM_BYTES=0

    # CPU Core Count
    if command -v nproc >/dev/null 2>&1; then
        CPU_CORES=$(nproc)
    elif [[ "$OS_TYPE" == "Darwin" ]]; then
        CPU_CORES=$(sysctl -n hw.ncpu 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 1)
    else
        CPU_CORES=$(grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 1)
    fi

    # Total System RAM
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        TOTAL_RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    elif [[ -f /proc/meminfo ]]; then
        local mem_kb
        mem_kb=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)
        TOTAL_RAM_BYTES=$((mem_kb * 1024))
    fi

    TOTAL_RAM_GB=$(awk "BEGIN {printf \"%.2f\", ${TOTAL_RAM_BYTES}/1073741824}")

    # Multi-vendor GPU Discovery (NVIDIA -> Apple Silicon -> AMD ROCm -> CPU fallback)
    if command -v nvidia-smi >/dev/null 2>&1; then
        log_info "NVIDIA GPU detected via nvidia-smi utility."
        GPU_VENDOR="NVIDIA"
        local nv_info
        nv_info=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)
        if [[ -n "$nv_info" ]]; then
            GPU_NAME=$(echo "$nv_info" | cut -d',' -f1 | xargs)
            local vram_mb
            vram_mb=$(echo "$nv_info" | cut -d',' -f2 | xargs)
            if [[ "$vram_mb" =~ ^[0-9]+$ ]]; then
                VRAM_BYTES=$((vram_mb * 1024 * 1024))
            fi
        else
            GPU_NAME="NVIDIA Accelerator"
        fi
    elif [[ "$OS_TYPE" == "Darwin" ]]; then
        log_info "Apple Silicon / macOS Metal GPU architecture detected."
        GPU_VENDOR="Apple"
        local chip_name
        chip_name=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "")
        if [[ -z "$chip_name" ]] && command -v system_profiler >/dev/null 2>&1; then
            chip_name=$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chipset Model" | head -n1 | cut -d':' -f2 | xargs || echo "")
        fi
        if [[ -n "$chip_name" ]]; then
            GPU_NAME="$chip_name"
        else
            GPU_NAME="Apple Silicon (Metal Unified Memory)"
        fi
        # Unified Memory functions as shared VRAM on Apple Silicon
        VRAM_BYTES=$TOTAL_RAM_BYTES
    elif command -v rocm-smi >/dev/null 2>&1; then
        log_info "AMD ROCm GPU detected via rocm-smi utility."
        GPU_VENDOR="AMD"
        GPU_NAME="AMD ROCm GPU"
        local rocm_vram
        rocm_vram=$(rocm-smi --showmeminfo vram 2>/dev/null | grep -i total | awk '{print $NF}' | head -n1 || echo 0)
        if [[ "$rocm_vram" =~ ^[0-9]+$ ]]; then
            VRAM_BYTES=$rocm_vram
        fi
    else
        log_info "No discrete GPU acceleration tool detected. Host defaulting to CPU backend."
        GPU_VENDOR="CPU"
        GPU_NAME="CPU Host (${CPU_CORES} logical threads)"
        VRAM_BYTES=0
    fi

    VRAM_GB=$(awk "BEGIN {printf \"%.2f\", ${VRAM_BYTES}/1073741824}")

    log_success "Hardware Auto-Discovery Results:"
    log_success "  - Operating System  : ${OS_TYPE} (${ARCH})"
    log_success "  - CPU Logical Cores : ${CPU_CORES} cores"
    log_success "  - Host System RAM   : ${TOTAL_RAM_GB} GB"
    log_success "  - GPU Vendor / Model: ${GPU_VENDOR} (${GPU_NAME})"
    log_success "  - Dedicated/VRAM    : ${VRAM_GB} GB"
}

# ------------------------------------------------------------------------------
# 2. Prerequisites Verification
# ------------------------------------------------------------------------------
check_prerequisites() {
    log_info "Verifying system prerequisites..."

    # Python >= 3.10 Check
    if ! command -v python3 >/dev/null 2>&1; then
        log_error "Python 3 is not installed or not in PATH. Python >= 3.10 is required."
        exit 1
    fi

    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d'.' -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d'.' -f2)

    if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
        log_error "Python version ${PY_VER} found. Public Intelligence requires Python >= 3.10."
        exit 1
    fi
    log_success "Python version ${PY_VER} verified."

    # Git Check
    if ! command -v git >/dev/null 2>&1; then
        log_error "Git is not installed. Git is required for sandbox worktree isolation."
        exit 1
    fi
    log_success "Git version $(git --version | awk '{print $3}') verified."

    # Docker Daemon Check
    if [[ "$SKIP_DOCKER" == "true" ]]; then
        log_warn "Skipping Docker daemon verification (--skip-docker specified)."
    else
        if ! command -v docker >/dev/null 2>&1; then
            log_warn "Docker binary not found. Docker sandbox container runtime will be disabled."
        elif ! docker info >/dev/null 2>&1; then
            log_warn "Docker daemon is not accessible. Docker sandbox container runtime will be disabled."
        else
            log_success "Docker daemon accessibility verified."
        fi
    fi
}

# ------------------------------------------------------------------------------
# 3. P2P WAN Environment Configuration
# ------------------------------------------------------------------------------
configure_environment() {
    log_info "Configuring P2P WAN Node Environment..."

    local ENV_FILE="${PROJECT_ROOT}/Node/.env"
    local HOSTNAME_RAW
    HOSTNAME_RAW=$(hostname 2>/dev/null | tr -cd 'a-zA-Z0-9' | tr '[:upper:]' '[:lower:]' || echo "host")
    if [[ -z "$HOSTNAME_RAW" ]]; then
        HOSTNAME_RAW="host"
    fi

    local NODE_ID_VAL="node-host-${HOSTNAME_RAW}"
    local TELEMETRY_KEY_VAL="pi_telemetry_secure_default_secret_key"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_dry_run "Would configure ${ENV_FILE} with:"
        log_dry_run "  NODE_ID=${NODE_ID_VAL}"
        log_dry_run "  NODE_HOST=0.0.0.0"
        log_dry_run "  NODE_PORT=8080"
        log_dry_run "  NODE_SCHEDULER_URL=http://localhost:8080"
        log_dry_run "  NODE_OLLAMA_HOST=http://localhost:11434"
        log_dry_run "  NODE_BOOTSTRAP_ROUTERS=[\"tcp/bootstrap.public-intelligence.net:7447\"]"
        log_dry_run "  NODE_ZENOH_GOSSIP_SCOUTING=true"
        log_dry_run "  NODE_ZENOH_MULTICAST_SCOUTING=true"
        log_dry_run "  TELEMETRY_SECRET_KEY=${TELEMETRY_KEY_VAL}"
        return 0
    fi

    local SCHEDULER_URL_VAL="${SCHEDULER_URL:-http://localhost:8000}"

    if [[ ! -f "$ENV_FILE" ]] || [[ "$FORCE" == "true" ]]; then
        cat <<EOF > "$ENV_FILE"
# Auto-generated by install.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
NODE_ID=${NODE_ID_VAL}
NODE_HOSTNAME=localhost
NODE_HOST=0.0.0.0
NODE_PORT=8080
NODE_SCHEDULER_URL=${SCHEDULER_URL_VAL}
NODE_OLLAMA_HOST=http://localhost:11434
NODE_BOOTSTRAP_ROUTERS=["tcp/bootstrap.public-intelligence.net:7447"]
NODE_ZENOH_GOSSIP_SCOUTING=true
NODE_ZENOH_MULTICAST_SCOUTING=true
TELEMETRY_SECRET_KEY=${TELEMETRY_KEY_VAL}
EOF
        log_success "Created ${ENV_FILE} with P2P WAN endpoints."
    else
        if grep -q "^NODE_SCHEDULER_URL=" "$ENV_FILE"; then
            sed -i.bak "s|^NODE_SCHEDULER_URL=.*|NODE_SCHEDULER_URL=${SCHEDULER_URL_VAL}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
        else
            echo "NODE_SCHEDULER_URL=${SCHEDULER_URL_VAL}" >> "$ENV_FILE"
        fi
        log_success "Updated NODE_SCHEDULER_URL=${SCHEDULER_URL_VAL} in ${ENV_FILE}."
    fi
}

# ------------------------------------------------------------------------------
# 4. Python Virtual Environment Setup & Dependencies Installation
# ------------------------------------------------------------------------------
setup_virtual_environment() {
    if [[ "$SKIP_VENV" == "true" ]]; then
        log_warn "Skipping Python virtual environment setup (--skip-venv specified)."
        return 0
    fi

    log_info "Setting up Python Virtual Environment in Node/.venv..."

    local VENV_DIR="${PROJECT_ROOT}/Node/.venv"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_dry_run "Would create virtual environment at ${VENV_DIR} if missing."
        log_dry_run "Would run: ${VENV_DIR}/bin/pip install -e ${PROJECT_ROOT}/Node"
        return 0
    fi

    if [[ ! -d "$VENV_DIR" ]] || [[ "$FORCE" == "true" ]]; then
        python3 -m venv "$VENV_DIR"
        log_success "Created virtual environment at ${VENV_DIR}."
    else
        log_info "Virtual environment at ${VENV_DIR} already exists."
    fi

    log_info "Installing public-intelligence-node package and dependencies..."
    "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    "${VENV_DIR}/bin/pip" install -e "${PROJECT_ROOT}/Node"
    log_success "Successfully installed public-intelligence-node executable in virtual environment."
}

# ------------------------------------------------------------------------------
# 5. Executable Permissions & Symlinks
# ------------------------------------------------------------------------------
setup_executables() {
    log_info "Configuring runner executable permissions and links..."

    local LAUNCH_SCRIPT="${PROJECT_ROOT}/scripts/launch_host_node.sh"
    local NODE_RUNNER_LINK="${PROJECT_ROOT}/public-intelligence-node"
    local VENV_CLI="${PROJECT_ROOT}/Node/.venv/bin/public-intelligence-node"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_dry_run "Would grant executable permissions (chmod +x) on install.sh and scripts/launch_host_node.sh."
        log_dry_run "Would link ${NODE_RUNNER_LINK} -> ${VENV_CLI} (or launch script)."
        return 0
    fi

    chmod +x "${PROJECT_ROOT}/install.sh" 2>/dev/null || true
    chmod +x "${LAUNCH_SCRIPT}" 2>/dev/null || true

    if [[ -x "$VENV_CLI" ]]; then
        ln -sf "$VENV_CLI" "$NODE_RUNNER_LINK"
    else
        ln -sf "$LAUNCH_SCRIPT" "$NODE_RUNNER_LINK"
    fi

    log_success "Host runner executable linked at ${NODE_RUNNER_LINK}."
}

# ------------------------------------------------------------------------------
# Main Execution Sequence
# ------------------------------------------------------------------------------
detect_hardware
check_prerequisites
configure_environment
setup_virtual_environment
setup_executables

echo ""
echo -e "${GREEN}=============================================================================="
if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "       [DRY-RUN] Installation Simulation Complete (No changes written)      "
else
    echo -e "         Public Intelligence Host Node Installation Completed Successfully!   "
fi
echo -e "==============================================================================${NC}"

if [[ "$DRY_RUN" == "false" ]]; then
    echo "To start the host node daemon:"
    echo "  ./scripts/launch_host_node.sh start"
    echo ""
    echo "To check daemon status:"
    echo "  ./scripts/launch_host_node.sh status"
    echo ""
    echo "To run CLI directly:"
    echo "  ./public-intelligence-node --host 0.0.0.0 --port 8080"
fi
echo ""
