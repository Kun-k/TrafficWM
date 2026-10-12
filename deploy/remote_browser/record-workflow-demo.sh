#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
enter_docker_group "$@"
load_browser_env

workflow_id="${1:?usage: record-workflow-demo.sh WORKFLOW_ID DEMO_NAME}"
demo_name="${2:?usage: record-workflow-demo.sh WORKFLOW_ID DEMO_NAME}"
result_path="$RUNTIME_ROOT/recordings/${demo_name}.json"

stop_recording() {
    docker exec "$CONTAINER_NAME" trafficwm-record stop >/dev/null 2>&1 || true
}
trap stop_recording EXIT INT TERM

docker exec "$CONTAINER_NAME" trafficwm-record start "$demo_name"

cd "$SCRIPT_DIR/../.."
env \
    -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    NO_PROXY=127.0.0.1 no_proxy=127.0.0.1 \
    DEMO_WORKFLOW_ID="$workflow_id" \
    DEMO_NAME="$demo_name" \
    DEMO_RESULT_PATH="$result_path" \
    TRAFFICWM_CDP_URL="http://127.0.0.1:9222" \
    node "$SCRIPT_DIR/record_workflow_demo.js"
