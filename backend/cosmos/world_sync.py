"""Atomic synchronization state shared by traffic and world-video workers."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


SCHEMA = "denseworld.traffic-video-sync.v1"
_MONOTONIC_FIELDS = ("requested_traffic_time", "generated_video_time")
_TERMINAL_STAGES = {"completed", "error", "failed", "stopped", "interrupted", "cancelled"}


def read_world_sync(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_world_sync(path: str | Path, **fields: Any) -> dict[str, Any]:
    """Merge and atomically publish progress without moving time backwards."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = read_world_sync(target)
    payload.setdefault("schema", SCHEMA)
    for key, value in fields.items():
        if key in _MONOTONIC_FIELDS:
            try:
                value = max(float(payload.get(key, 0.0) or 0.0), float(value or 0.0))
            except (TypeError, ValueError):
                continue
        payload[key] = value
    payload["updated_at_unix"] = time.time()
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return payload


def traffic_step_permitted(
    path: str | Path | None,
    next_sim_time: float,
    *,
    tolerance: float = 1e-6,
) -> tuple[bool, dict[str, Any]]:
    if not path:
        return True, {}
    state = read_world_sync(path)
    if not state:
        return False, {}
    if str(state.get("stage") or "").strip().lower() in _TERMINAL_STAGES:
        return True, state
    try:
        requested = float(state.get("requested_traffic_time", 0.0) or 0.0)
    except (TypeError, ValueError):
        requested = 0.0
    return float(next_sim_time) <= requested + max(0.0, float(tolerance)), state


def traffic_capture_wait_is_expected(
    path: str | Path | None,
    latest_sim_time: float,
    *,
    tolerance: float = 0.05,
) -> bool:
    """Return true when capture is intentionally caught up to video demand."""
    state = read_world_sync(path)
    if not state or str(state.get("stage") or "").strip().lower() in _TERMINAL_STAGES:
        return False
    try:
        requested = float(state.get("requested_traffic_time", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return float(latest_sim_time) + max(0.0, float(tolerance)) >= requested
