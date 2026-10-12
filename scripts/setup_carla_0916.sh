#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CARLA_ENV_PREFIX="${CARLA_ENV_PREFIX:-$ROOT_DIR/envs/carla}"
PLATFORM_PYTHON="${PLATFORM_PYTHON:-$ROOT_DIR/envs/platform/bin/python}"
CARLA_ROOT="${CARLA_ROOT:-/data/rk/cnde/CARLA_0.9.16}"
CARLA_ARCHIVE="${CARLA_ARCHIVE:-/data/rk/cnde/downloads/CARLA_0.9.16.tar.gz}"
CARLA_URL="${CARLA_URL:-https://carla-releases.b-cdn.net/Linux/CARLA_0.9.16.tar.gz}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

platform_version="$("$PLATFORM_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
env_version=""
if [[ -x "$CARLA_ENV_PREFIX/bin/python" ]]; then
  env_version="$("$CARLA_ENV_PREFIX/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
fi
if [[ "$env_version" != "$platform_version" ]]; then
  "$PLATFORM_PYTHON" -m virtualenv --clear --python "$PLATFORM_PYTHON" "$CARLA_ENV_PREFIX"
fi
"$CARLA_ENV_PREFIX/bin/python" -m pip install \
  --index-url "$PIP_INDEX_URL" \
  --trusted-host "$("$PLATFORM_PYTHON" -c "from urllib.parse import urlparse; print(urlparse('$PIP_INDEX_URL').hostname or '')")" \
  "carla==0.9.16" "numpy<2" "pillow>=10,<13" "PyYAML>=6,<7"

if [[ ! -x "$CARLA_ROOT/CarlaUE4.sh" ]]; then
  mkdir -p "$(dirname "$CARLA_ARCHIVE")" "$CARLA_ROOT"
  curl -L --fail --retry 5 --continue-at - --output "$CARLA_ARCHIVE" "$CARLA_URL"
  tar -xzf "$CARLA_ARCHIVE" -C "$CARLA_ROOT"
fi

version="$("$CARLA_ENV_PREFIX/bin/python" -c 'from importlib.metadata import version; print(version("carla"))')"
if [[ "$version" != "0.9.16" ]]; then
  echo "Unexpected CARLA Python API version: $version" >&2
  exit 1
fi
echo "[done] CARLA $version"
echo "[package] $CARLA_ROOT"
echo "[python]  $CARLA_ENV_PREFIX/bin/python"
