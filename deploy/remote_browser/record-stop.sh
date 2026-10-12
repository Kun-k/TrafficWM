#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"

docker exec "$CONTAINER_NAME" trafficwm-record stop

