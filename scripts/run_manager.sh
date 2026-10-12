#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CITYNDE_ROOT_OVERRIDE="${CITYNDE_ROOT:-}"

for env_file in "$ROOT_DIR/.env" "$ROOT_DIR/.env.local" "$ROOT_DIR/.env.conda"; do
  if [[ -f "$env_file" ]]; then
    # shellcheck disable=SC1090
    source "$env_file"
  fi
done

OMNIDREAMS_CONFIG_FILE="${OMNIDREAMS_CONFIG_FILE:-$ROOT_DIR/backend/config/omnidreams.env}"
if [[ -f "$OMNIDREAMS_CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$OMNIDREAMS_CONFIG_FILE"
fi

PLATFORM_ENV_PREFIX="${PLATFORM_ENV_PREFIX:-$ROOT_DIR/envs/platform}"
CNDE_ENV_PREFIX="${CNDE_ENV_PREFIX:-$ROOT_DIR/envs/cnde}"
CARLA_ENV_PREFIX="${CARLA_ENV_PREFIX:-$ROOT_DIR/envs/carla}"
[[ -d "$PLATFORM_ENV_PREFIX" ]] || PLATFORM_ENV_PREFIX="$ROOT_DIR/envs/platform"
[[ -d "$CNDE_ENV_PREFIX" ]] || CNDE_ENV_PREFIX="$ROOT_DIR/envs/cnde"
[[ -d "$CARLA_ENV_PREFIX" ]] || CARLA_ENV_PREFIX="$ROOT_DIR/envs/carla"
NEURALNDE_ROOT="${NEURALNDE_ROOT:-/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment}"
CITYNDE_ROOT="${CITYNDE_ROOT_OVERRIDE:-${CITYNDE_ROOT:-$ROOT_DIR/algorithm_sources/CityNDE_src}}"
if [[ "$CITYNDE_ROOT" != /* ]]; then
  CITYNDE_ROOT="$ROOT_DIR/$CITYNDE_ROOT"
fi
MANAGER_PYTHON="${MANAGER_PYTHON:-$PLATFORM_ENV_PREFIX/bin/python}"
CITYNDE_PYTHON="${CITYNDE_PYTHON:-$CNDE_ENV_PREFIX/bin/python}"
CARLA_PYTHON="${CARLA_PYTHON:-$CARLA_ENV_PREFIX/bin/python}"
NEURALNDE_PYTHON="${NEURALNDE_PYTHON:-$NEURALNDE_ROOT/.venv/bin/python}"
CARLA_ROOT="${CARLA_ROOT:-/data/rk/cnde/CARLA_0.9.16}"

# Older deployments stored absolute /data paths. Keep local copied environments
# relocatable when the workspace is mounted at /mnt or another root.
[[ -x "$MANAGER_PYTHON" ]] || MANAGER_PYTHON="$ROOT_DIR/envs/platform/bin/python"
[[ -x "$CITYNDE_PYTHON" ]] || CITYNDE_PYTHON="$ROOT_DIR/envs/cnde/bin/python"
[[ -d "$CITYNDE_ROOT" ]] || CITYNDE_ROOT="$ROOT_DIR/algorithm_sources/CityNDE_src"

mkdir -p \
  "$ROOT_DIR/output/scenarios/citynde" \
  "$ROOT_DIR/output/experiments" \
  "$ROOT_DIR/output/cosmos" \
  "$ROOT_DIR/output/runtime"
if [[ ! -e "$CITYNDE_ROOT/output" && ! -L "$CITYNDE_ROOT/output" ]]; then
  ln -s "$ROOT_DIR/output/scenarios/citynde" "$CITYNDE_ROOT/output"
fi

for python_path in "$CITYNDE_PYTHON" "$NEURALNDE_PYTHON"; do
  if [[ ! -x "$python_path" ]]; then
    echo "Project Python not found: $python_path" >&2
    echo "Run: scripts/setup_conda_envs.sh" >&2
    exit 1
  fi
done

if ! "$MANAGER_PYTHON" -c "import sys" >/dev/null 2>&1; then
  echo "Manager Python is not compatible with the host glibc; using NeuralNDE Python." >&2
  MANAGER_PYTHON="$NEURALNDE_PYTHON"
fi
for dataset in AA_rdbt rounD; do
  if [[ ! -f "$NEURALNDE_ROOT/configs/${dataset}_inference.yml" ]]; then
    echo "NeuralNDE dataset config not found: $NEURALNDE_ROOT/configs/${dataset}_inference.yml" >&2
    exit 1
  fi
done

CITYNDE_ABI_SHIM_SOURCE="$ROOT_DIR/backend/algorithms/citynde/interface/torch_legacy_abi_shim.cpp"
CITYNDE_ABI_SHIM_LIBRARY="$ROOT_DIR/backend/algorithms/citynde/interface/torch_legacy_abi_shim.so"
if [[ ! -f "$CITYNDE_ABI_SHIM_LIBRARY" || "$CITYNDE_ABI_SHIM_SOURCE" -nt "$CITYNDE_ABI_SHIM_LIBRARY" ]]; then
  g++ -std=c++17 -shared -fPIC -O2 -D_GLIBCXX_USE_CXX11_ABI=0 \
    "$CITYNDE_ABI_SHIM_SOURCE" -o "$CITYNDE_ABI_SHIM_LIBRARY"
fi
# The ABI shim is injected only into the CityNDE container. Preloading it into
# the manager changes unrelated Python extension ABIs.

required_citynde_assets=(
  "assets/map/routed_map_nuplan_boston.pkl"
  "assets/config/model_cfg.yaml"
  "assets/intention_priors/nuplan-boston-cluster-64-past-011-future-080-timeinterval-0.100000.pkl"
  "assets/ckpt/nn_weights.pth"
)
for relative_path in "${required_citynde_assets[@]}"; do
  if [[ ! -f "$CITYNDE_ROOT/$relative_path" ]]; then
    echo "CityNDE runtime asset not found: $CITYNDE_ROOT/$relative_path" >&2
    exit 1
  fi
done

export PLATFORM_ENV_PREFIX CNDE_ENV_PREFIX
export CARLA_ENV_PREFIX CARLA_PYTHON CARLA_ROOT
export NEURALNDE_ROOT NEURALNDE_PYTHON
export CITYNDE_ROOT
export MANAGER_PYTHON CITYNDE_PYTHON
export PYTHONNOUSERSITE=1
# User management is temporarily disabled for the integrated experiment UI.
export TRAFFICWM_AUTH_DISABLED="${TRAFFICWM_AUTH_DISABLED:-1}"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
# The manager launches ffmpeg while resident gRPC runtimes are active. Disable
# gRPC's process-fork handlers so unrelated media children do not inherit its
# polling state.
export GRPC_ENABLE_FORK_SUPPORT="${GRPC_ENABLE_FORK_SUPPORT:-0}"
export OMNIDREAMS_CONFIG_FILE
unset PYTHONPATH
unset PYTHONHOME

OMNIDREAMS_PROFILE="${OMNIDREAMS_PROFILE:-quality}"
case "$OMNIDREAMS_PROFILE" in
  quality)
    OMNIDREAMS_PROFILE_GPUS="7"
    ANCHOR_TRANSFER_PROFILE_GPUS=""
    OMNIDREAMS_PROFILE_ROLLOVER_MODE="latest"
    OMNIDREAMS_PROFILE_ANCHOR_MODE="conditioned_front"
    OMNIDREAMS_PROFILE_PIPELINE="omnidreams-sv-2steps-chunk2-loc6-vae-vae"
    ;;
  realtime)
    OMNIDREAMS_PROFILE_GPUS="4,5,6,7"
    ANCHOR_TRANSFER_PROFILE_GPUS=""
    OMNIDREAMS_PROFILE_ROLLOVER_MODE="latest"
    OMNIDREAMS_PROFILE_ANCHOR_MODE="conditioned_front"
    OMNIDREAMS_PROFILE_PIPELINE="omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf"
    ;;
  realtime_fast)
    OMNIDREAMS_PROFILE_GPUS="0,1,2,3"
    ANCHOR_TRANSFER_PROFILE_GPUS=""
    OMNIDREAMS_PROFILE_ROLLOVER_MODE="latest"
    OMNIDREAMS_PROFILE_ANCHOR_MODE="conditioned_front"
    OMNIDREAMS_PROFILE_PIPELINE="omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf"
    ;;
  *)
    echo "Unknown OMNIDREAMS_PROFILE: $OMNIDREAMS_PROFILE (expected quality, realtime, or realtime_fast)" >&2
    exit 2
    ;;
esac
ANCHOR_TRANSFER_EFFECTIVE_GPUS="${COSMOS_ANCHOR_TRANSFER_GPUS-$ANCHOR_TRANSFER_PROFILE_GPUS}"
OMNIDREAMS_EFFECTIVE_PIPELINE="${OMNIDREAMS_PIPELINE_CONFIG:-$OMNIDREAMS_PROFILE_PIPELINE}"
case "${COSMOS_TRANSFER_ENABLED:-1}" in
  0|false|FALSE|no|NO)
    TRANSFER_EFFECTIVE_GPUS=""
    ;;
  *)
    TRANSFER_EFFECTIVE_GPUS="${COSMOS_TRANSFER_GPUS:-0,1,2,3}"
    ;;
esac
if [[ -n "${OMNIDREAMS_GPUS:-}" ]]; then
  OMNIDREAMS_EFFECTIVE_GPUS="$OMNIDREAMS_GPUS"
elif [[ -n "$TRANSFER_EFFECTIVE_GPUS" && "$OMNIDREAMS_PROFILE" == "realtime_fast" ]]; then
  OMNIDREAMS_EFFECTIVE_GPUS="4,5,6,7"
else
  OMNIDREAMS_EFFECTIVE_GPUS="$OMNIDREAMS_PROFILE_GPUS"
fi
export OMNIDREAMS_ROLLOVER_MODE="${OMNIDREAMS_ROLLOVER_MODE:-$OMNIDREAMS_PROFILE_ROLLOVER_MODE}"
export OMNIDREAMS_ANCHOR_MODE="${OMNIDREAMS_ANCHOR_MODE:-$OMNIDREAMS_PROFILE_ANCHOR_MODE}"

"$MANAGER_PYTHON" "$ROOT_DIR/scripts/bootstrap_standard_scenarios.py" --root "$ROOT_DIR"

cd "$ROOT_DIR"
exec "$MANAGER_PYTHON" -m backend.manager.server \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-8890}" \
  --child_host "${CHILD_HOST:-127.0.0.1}" \
  --child_port_start "${CHILD_PORT_START:-8900}" \
  --gui_dir GUI \
  --citynde_root "$CITYNDE_ROOT" \
  --neuralnde_root "$NEURALNDE_ROOT" \
  --citynde_python "$CITYNDE_PYTHON" \
  --neuralnde_python "$NEURALNDE_PYTHON" \
  --carla_python "$CARLA_PYTHON" \
  --carla_root "$CARLA_ROOT" \
  --carla_gateway_port "${CARLA_GATEWAY_PORT:-8892}" \
  --cosmos_autostart \
  --transfer_root "${COSMOS_TRANSFER_ROOT:-/mnt/rk/cosmos/cosmos_transfer2.5/cosmos-transfer2.5}" \
  --omnidreams_root "${OMNIDREAMS_ROOT:-/mnt/rk/cosmos/flashdreams}" \
  --transfer_gpus "$TRANSFER_EFFECTIVE_GPUS" \
  --anchor_transfer_gpus "$ANCHOR_TRANSFER_EFFECTIVE_GPUS" \
  --omnidreams_gpus "$OMNIDREAMS_EFFECTIVE_GPUS" \
  --transfer_port "${COSMOS_TRANSFER_PORT:-8895}" \
  --anchor_transfer_port "${COSMOS_ANCHOR_TRANSFER_PORT:-8896}" \
  --omnidreams_port "${OMNIDREAMS_PORT:-50051}" \
  --omnidreams_profile "$OMNIDREAMS_PROFILE" \
  --omnidreams_pipeline_config "$OMNIDREAMS_EFFECTIVE_PIPELINE" \
  --omnidreams_checkpoint_path "${OMNIDREAMS_CHECKPOINT_PATH:-}" \
  --transfer_container_image "${COSMOS_TRANSFER_CONTAINER_IMAGE:-trafficwm-cosmos-runtime:cu128}" \
  --transfer_container_venv "${COSMOS_TRANSFER_CONTAINER_VENV:-cosmos-transfer25-venv}" \
  "$@"
