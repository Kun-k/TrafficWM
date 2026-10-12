#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM_ENV_PREFIX="${PLATFORM_ENV_PREFIX:-$ROOT_DIR/envs/platform}"
CNDE_ENV_PREFIX="${CNDE_ENV_PREFIX:-$ROOT_DIR/envs/cnde}"
CARLA_ENV_PREFIX="${CARLA_ENV_PREFIX:-$ROOT_DIR/envs/carla}"
NEURALNDE_ROOT="${NEURALNDE_ROOT:-/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment}"
CITYNDE_ROOT="${CITYNDE_ROOT:-$ROOT_DIR/algorithm_sources/CityNDE_src}"
if [[ "$CITYNDE_ROOT" != /* ]]; then
  CITYNDE_ROOT="$ROOT_DIR/$CITYNDE_ROOT"
fi
MANAGER_PYTHON="${MANAGER_PYTHON:-$PLATFORM_ENV_PREFIX/bin/python}"
CITYNDE_PYTHON="${CITYNDE_PYTHON:-$CNDE_ENV_PREFIX/bin/python}"
CARLA_PYTHON="${CARLA_PYTHON:-$CARLA_ENV_PREFIX/bin/python}"
NEURALNDE_PYTHON="${NEURALNDE_PYTHON:-$NEURALNDE_ROOT/.venv/bin/python}"
CARLA_ROOT="${CARLA_ROOT:-/data/rk/cnde/CARLA_0.9.16}"

if [[ ! -x "$MANAGER_PYTHON" ]]; then
  echo "Platform Python not found: $MANAGER_PYTHON" >&2
  exit 1
fi
if [[ ! -x "$CITYNDE_PYTHON" ]]; then
  echo "CityNDE Python not found: $CITYNDE_PYTHON" >&2
  exit 1
fi
if [[ ! -x "$NEURALNDE_PYTHON" ]]; then
  echo "NeuralNDE environment not found: $NEURALNDE_PYTHON" >&2
  echo "Run: $NEURALNDE_ROOT/setup_h800.sh" >&2
  exit 1
fi

mkdir -p \
  "$ROOT_DIR/output/scenarios/citynde" \
  "$ROOT_DIR/output/experiments" \
  "$ROOT_DIR/output/cosmos" \
  "$ROOT_DIR/output/runtime"
if [[ ! -e "$CITYNDE_ROOT/output" && ! -L "$CITYNDE_ROOT/output" ]]; then
  ln -s "$ROOT_DIR/output/scenarios/citynde" "$CITYNDE_ROOT/output"
fi
CITYNDE_ABI_SHIM_SOURCE="$ROOT_DIR/backend/algorithms/citynde/interface/torch_legacy_abi_shim.cpp"
CITYNDE_ABI_SHIM_LIBRARY="$ROOT_DIR/backend/algorithms/citynde/interface/torch_legacy_abi_shim.so"
if [[ ! -f "$CITYNDE_ABI_SHIM_LIBRARY" || "$CITYNDE_ABI_SHIM_SOURCE" -nt "$CITYNDE_ABI_SHIM_LIBRARY" ]]; then
  g++ -std=c++17 -shared -fPIC -O2 -D_GLIBCXX_USE_CXX11_ABI=0 \
    "$CITYNDE_ABI_SHIM_SOURCE" -o "$CITYNDE_ABI_SHIM_LIBRARY"
fi
export LD_PRELOAD="$CITYNDE_ABI_SHIM_LIBRARY${LD_PRELOAD:+:$LD_PRELOAD}"

"$MANAGER_PYTHON" -c "import yaml; print('[platform] PyYAML', yaml.__version__)"
PYTHONPATH="$CITYNDE_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
  "$CITYNDE_PYTHON" -c "import torch; from cnde.models.model import MotionTransformer; from csim.simulator.interactive_simulator import InteractiveRouteTLSimulator; print(f'[citynde] source=$CITYNDE_ROOT, torch {torch.__version__}, CUDA architectures: {torch.cuda.get_arch_list()}')"
"$NEURALNDE_PYTHON" -c "import torch, cv2, yaml; print('[neuralnde] torch', torch.__version__, 'CUDA', torch.cuda.is_available())"
if [[ -x "$CARLA_PYTHON" ]]; then
  "$CARLA_PYTHON" -c "import carla; from importlib.metadata import version; assert version('carla') == '0.9.16'; print('[carla] Python API', version('carla'))"
else
  echo "[carla] environment not installed; run scripts/setup_carla_0916.sh"
fi

cat > "$ROOT_DIR/.env.conda" <<EOF
PLATFORM_ENV_PREFIX=$PLATFORM_ENV_PREFIX
CNDE_ENV_PREFIX=$CNDE_ENV_PREFIX
CARLA_ENV_PREFIX=$CARLA_ENV_PREFIX
MANAGER_PYTHON=$MANAGER_PYTHON
CITYNDE_PYTHON=$CITYNDE_PYTHON
CARLA_PYTHON=$CARLA_PYTHON
CARLA_ROOT=$CARLA_ROOT
CITYNDE_ROOT=$CITYNDE_ROOT
NEURALNDE_ROOT=$NEURALNDE_ROOT
NEURALNDE_PYTHON=$NEURALNDE_PYTHON
EOF

echo "[done] wrote $ROOT_DIR/.env.conda"
echo "[run]  scripts/run_manager.sh"
