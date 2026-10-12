#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"

name="${1:-trafficwm_$(date +%Y%m%d_%H%M%S)}"
docker exec "$CONTAINER_NAME" trafficwm-record start "$name"

