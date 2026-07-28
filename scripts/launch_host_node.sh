#!/usr/bin/env bash
# ==============================================================================
# Public Intelligence - Host Node Daemon Launcher Harness
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
NODE_DIR="${PROJECT_ROOT}/Node"
PID_FILE="${NODE_DIR}/node.pid"
LOG_FILE="${NODE_DIR}/node.log"
VENV_PYTHON="${NODE_DIR}/.venv/bin/python3"
VENV_NODE_CLI="${NODE_DIR}/.venv/bin/public-intelligence-node"

# Default host/port if not specified
HOST="${NODE_HOST:-0.0.0.0}"
PORT="${NODE_PORT:-8080}"

usage() {
    echo "Usage: $0 {start|stop|restart|status|logs} [options]"
    echo ""
    echo "Commands:"
    echo "  start     Launch host node in background daemon mode"
    echo "  stop      Gracefully stop host node daemon"
    echo "  restart   Restart host node daemon"
    echo "  status    Check host node daemon status"
    echo "  logs      Follow host node log output"
    echo ""
    echo "Options:"
    echo "  --host IP    Host interface to bind (default: 0.0.0.0)"
    echo "  --port PORT  Port to listen on (default: 8080)"
    echo "  -h, --help   Show this help message"
    exit 1
}

ACTION="${1:-}"
if [[ -z "$ACTION" ]]; then
    usage
fi
shift || true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

get_pid() {
    if [[ -f "$PID_FILE" ]]; then
        cat "$PID_FILE"
    fi
}

is_running() {
    local pid
    pid=$(get_pid)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

start_node() {
    if is_running; then
        local pid
        pid=$(get_pid)
        echo "Host node daemon is already running (PID: ${pid})."
        return 0
    fi

    echo "Starting Public Intelligence Host Node daemon..."

    local EXEC_CMD
    if [[ -x "$VENV_NODE_CLI" ]]; then
        EXEC_CMD="$VENV_NODE_CLI --host $HOST --port $PORT"
    elif [[ -x "$VENV_PYTHON" ]]; then
        EXEC_CMD="$VENV_PYTHON -m node.main --host $HOST --port $PORT"
    else
        EXEC_CMD="python3 -m node.main --host $HOST --port $PORT"
    fi

    echo "Executable command: ${EXEC_CMD}"
    echo "Output log: ${LOG_FILE}"

    (
        cd "$NODE_DIR"
        export PYTHONPATH="${NODE_DIR}/src:${PYTHONPATH:-}"
        nohup $EXEC_CMD >> "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
    )

    sleep 1

    if is_running; then
        local pid
        pid=$(get_pid)
        echo "Host node daemon started successfully (PID: ${pid})."
    else
        echo "Failed to start host node daemon. Check ${LOG_FILE} for error logs."
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop_node() {
    if ! is_running; then
        echo "Host node daemon is not running."
        rm -f "$PID_FILE"
        return 0
    fi

    local pid
    pid=$(get_pid)
    echo "Stopping host node daemon (PID: ${pid})..."

    kill -15 "$pid" 2>/dev/null || true

    local count=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        count=$((count + 1))
        if [[ $count -ge 10 ]]; then
            echo "Process ${pid} did not exit within 10 seconds. Sending SIGKILL..."
            kill -9 "$pid" 2>/dev/null || true
            break
        fi
    done

    rm -f "$PID_FILE"
    echo "Host node daemon stopped."
}

status_node() {
    if is_running; then
        local pid
        pid=$(get_pid)
        echo "Host node daemon is RUNNING (PID: ${pid})."
        echo "Log file: ${LOG_FILE}"
        echo "Endpoint: http://${HOST}:${PORT}"
    else
        echo "Host node daemon is STOPPED."
        if [[ -f "$PID_FILE" ]]; then
            echo "Warning: Stale PID file found at ${PID_FILE}."
        fi
        return 1
    fi
}

logs_node() {
    if [[ ! -f "$LOG_FILE" ]]; then
        echo "Log file ${LOG_FILE} does not exist yet."
        exit 1
    fi
    echo "Tailing ${LOG_FILE} (Ctrl+C to exit)..."
    tail -n 50 -f "$LOG_FILE"
}

case "$ACTION" in
    start)
        start_node
        ;;
    stop)
        stop_node
        ;;
    restart)
        stop_node
        sleep 1
        start_node
        ;;
    status)
        status_node
        ;;
    logs)
        logs_node
        ;;
    *)
        usage
        ;;
esac
