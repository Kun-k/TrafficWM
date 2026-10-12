#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_ROOT="${TRAFFICWM_BROWSER_ROOT:-/mnt/rk/trafficwm-browser}"
ENV_FILE="${TRAFFICWM_BROWSER_ENV:-$SCRIPT_DIR/.env}"
CONTAINER_NAME="trafficwm-browser"

enter_docker_group() {
    if docker info >/dev/null 2>&1; then
        return
    fi

    local command
    printf -v command '%q ' "$SCRIPT_PATH" "$@"
    exec sg docker -c "$command"
}

load_browser_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Missing $ENV_FILE. Copy .env.example and set both VNC passwords." >&2
        exit 1
    fi

    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a

    if [[ -z "${VNC_PASSWORD:-}" || "$VNC_PASSWORD" == "change-me" ]]; then
        echo "VNC_PASSWORD must be set in $ENV_FILE." >&2
        exit 1
    fi
}

