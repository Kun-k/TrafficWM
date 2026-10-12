#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"

docker ps --filter "name=^/${CONTAINER_NAME}$" \
    --format 'container={{.Names}} status={{.Status}} ports={{.Ports}}'
docker stats --no-stream --format \
    'cpu={{.CPUPerc}} memory={{.MemUsage}} network={{.NetIO}} pids={{.PIDs}}' \
    "$CONTAINER_NAME" 2>/dev/null || true
docker exec "$CONTAINER_NAME" trafficwm-record status 2>/dev/null || true

