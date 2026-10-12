#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"

if docker container inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
    docker exec "$CONTAINER_NAME" trafficwm-record stop >/dev/null 2>&1 || true
    docker stop --time 15 "$CONTAINER_NAME"
else
    echo "$CONTAINER_NAME is not installed."
fi

