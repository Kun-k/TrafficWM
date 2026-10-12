#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="$(readlink -f "$0")"
# shellcheck source=common.sh
source "$(dirname "$SCRIPT_PATH")/common.sh"
load_browser_env

export VNC_PASSWORD
export KASM_URL="${KASM_URL:-https://127.0.0.1:6901/}"
export BENCHMARK_DURATION_MS="${BENCHMARK_DURATION_MS:-10000}"

cd "$SCRIPT_DIR/../.."
node "$SCRIPT_DIR/benchmark.js"

