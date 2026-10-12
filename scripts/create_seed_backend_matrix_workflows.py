#!/usr/bin/env python3
"""Create or update the 18 visible workflow records for the seed-backend matrix."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8890/api/v1"
OUTPUT = ROOT / "output/validation/seed_backend_matrix_20260826/workflows.json"
LIBRARY_ROOT = ROOT / "output/scenarios/citynde/library"

SCENARIOS = (
    {
        "slug": "current",
        "label": "当前文瀛",
        "metadata": LIBRARY_ROOT / "matrix_current_xa_wenying.pkl.meta.json",
    },
    {
        "slug": "pedestrian",
        "label": "信号路口双行人",
        "metadata": LIBRARY_ROOT / "matrix_signalized_two_pedestrians.pkl.meta.json",
    },
    {
        "slug": "cyclist",
        "label": "无信号非机动车",
        "metadata": LIBRARY_ROOT / "matrix_unsignalized_cyclist.pkl.meta.json",
    },
)
DURATIONS = (10, 20, 60)
SEED_BACKENDS = (
    ("transfer1", "Transfer1"),
    ("transfer2.5", "Transfer2.5"),
)

EVALUATION_METRICS = {
    "safety": {
        "enabled": True,
        "metrics": {
            "av_overlap_frames": {"enabled": True, "weight": 40},
            "minimum_ttc": {"enabled": True, "weight": 40},
            "traffic_violation_rate": {"enabled": True, "weight": 20},
        },
    },
    "comfort": {
        "enabled": True,
        "metrics": {
            "longitudinal_acceleration_rms": {"enabled": True, "weight": 34},
            "lateral_acceleration_rms": {"enabled": True, "weight": 33},
            "jerk_p95": {"enabled": True, "weight": 33},
        },
    },
    "efficiency": {
        "enabled": True,
        "metrics": {
            "mean_speed": {"enabled": True, "weight": 40},
            "elapsed_time": {"enabled": True, "weight": 20},
            "stopped_time_ratio": {"enabled": True, "weight": 40},
        },
    },
}


def _request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with opener.open(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok", False):
        raise RuntimeError(str(result.get("error") or result))
    return result


def _workflow(
    scenario: dict[str, str],
    metadata: dict[str, Any],
    duration: int,
    seed_backend: str,
    seed_label: str,
) -> dict[str, Any]:
    participants = dict(metadata.get("participants") or {})
    motorized = int(participants.get("motorized") or 0)
    total_participants = sum(int(value or 0) for value in participants.values())
    long_run = duration >= 60
    local_target_count = int(
        metadata.get("world_local_target_count") or max(2, motorized)
    )
    actor_max_count = int(
        metadata.get("world_omnidreams_actor_max_count")
        or max(4, total_participants)
    )
    return {
        "name": f"种子矩阵-{scenario['label']}-{duration}秒-{seed_label}",
        "task_id": "DW-TASK-0001",
        "scenario_mode": "library",
        "scenario_execution_mode": "continue",
        "scenario_id": str(metadata["library_id"]),
        "map_path": "",
        "map_init_mode": "random_tl_only",
        "av_selection_mode": "existing",
        "av_model": "NONE",
        "command_mode": "state",
        "connection_mode": "internal",
        "observations": {
            "camera": True,
            "vehicle_state": True,
            "map": True,
            "traffic_lights": True,
            "traffic": True,
            "lidar": False,
        },
        "camera_config": {
            "enabled": True,
            "name": "前向主摄像头",
            "preset": "front_wide_120",
            "intrinsic_file": "",
            "extrinsic_file": "",
            "intrinsic_data": None,
            "extrinsic_data": None,
        },
        "traffic_model": str(metadata.get("backend_model") or "cnde"),
        "duration_seconds": int(duration),
        "gpu_id": "4",
        "arrival_rate": 0.0,
        "world_local_target_count": local_target_count,
        "world_initial_vehicle_limit": int(
            metadata.get("world_initial_vehicle_limit") or max(2, total_participants)
        ),
        "world_ego_speed_cap_mps": float(
            metadata.get("world_ego_speed_cap_mps") or 0.0
        ),
        "world_loop_ego": bool(metadata.get("world_loop_ego", False)),
        "max_pedestrians": int(metadata.get("max_pedestrians") or 0),
        "world_omnidreams_actor_max_count": actor_max_count,
        "rule_desired_speed_mps": float(
            (metadata.get("rule_control") or {}).get("bv_desired_speed_mps") or 5.0
        ),
        "av_desired_speed_mps": float(
            (metadata.get("rule_control") or {}).get("av_desired_speed_mps")
            or (metadata.get("rule_control") or {}).get("bv_desired_speed_mps")
            or 5.0
        ),
        "multimodal_enabled": True,
        "dreams_enabled": True,
        "world_seed_backend": seed_backend,
        "world_seed_alignment_mode": str(
            metadata.get("world_seed_alignment_mode") or "terminal_continue"
        ),
        "world_transfer_seed": int(metadata.get("world_transfer_seed") or 1),
        "world_omnidreams_seed": (
            7
            if long_run and seed_backend == "transfer1"
            else int(metadata.get("world_omnidreams_seed") or 1)
        ),
        "world_prompt": str(metadata.get("default_world_prompt") or ""),
        # Keep one continuous autoregressive session. Transfer-conditioned
        # rollovers visibly changed appearance at the boundary, while the
        # validated seed-1/light-VAE path remains stable with continuous input.
        "world_omnidreams_segment_seconds": (
            20.0 if long_run and seed_backend == "transfer2.5" else 0.0
        ),
        "world_omnidreams_rollover_mode": "latest",
        "world_omnidreams_anchor_mode": "conditioned_front",
        "world_omnidreams_anchor_transfer_steps": 12,
        "world_omnidreams_anchor_transfer_seed": int(
            metadata.get("world_transfer_seed") or 1
        ),
        "world_omnidreams_transition_frames": (
            8 if long_run and seed_backend == "transfer2.5" else 0
        ),
        "world_omnidreams_rollover_chroma_blur_radius": 0.0,
        "world_omnidreams_rollover_saturation_percent": 100,
        "world_omnidreams_rollover_image_format": (
            "png" if long_run and seed_backend == "transfer2.5" else "jpeg"
        ),
        # Keep the complete run in one autoregressive session. Stationary
        # anchor resets caused visible appearance discontinuities on long runs.
        "world_stationary_anchor_enabled": False,
        "world_stationary_speed_threshold_mps": 0.35,
        "world_stationary_exit_speed_mps": 0.8,
        "world_stationary_enter_seconds": 0.75,
        "world_stationary_reset_seconds": 6.0,
        "use_existing_seed": False,
        "evaluation": {"safety": 45, "comfort": 25, "efficiency": 30},
        "evaluation_metrics": EVALUATION_METRICS,
        "evaluation_system_id": "DW-EVAL-0001",
        "evaluation_system_name": "自然交通流自动驾驶综合评价",
        "scenario_count": 1,
        "seed": 42,
        "vehicle_size_mode": str(metadata.get("vehicle_size_mode") or "mixed"),
        "initial_speed_mode": "citynde",
        "save_result": True,
        "mixed_traffic_enabled": bool(metadata.get("mixed_traffic_enabled", False)),
        "matrix": {
            "schema": "trafficwm.seed-backend-matrix-run.v1",
            "scenario_slug": scenario["slug"],
            "duration_seconds": int(duration),
            "seed_backend": seed_backend,
        },
    }


def main() -> int:
    existing = _request("/workflows").get("workflows") or []
    by_name = {str(record.get("name") or ""): record for record in existing}
    records = []
    for seed_backend, seed_label in SEED_BACKENDS:
        for scenario in SCENARIOS:
            metadata = json.loads(Path(scenario["metadata"]).read_text(encoding="utf-8"))
            for duration in DURATIONS:
                workflow = _workflow(scenario, metadata, duration, seed_backend, seed_label)
                current = by_name.get(workflow["name"])
                if current:
                    workflow["id"] = current["id"]
                    workflow["created_at"] = current.get("created_at")
                result = _request("/workflows/action", {"type": "save", "workflow": workflow})
                saved = dict(result["workflow"])
                records.append(
                    {
                        "id": saved["id"],
                        "name": saved["name"],
                        "scenario_id": saved["scenario_id"],
                        "traffic_model": saved["traffic_model"],
                        "duration_seconds": saved["duration_seconds"],
                        "world_seed_backend": saved["world_seed_backend"],
                        "recording_name": (
                            f"matrix_{scenario['slug']}_{duration}s_"
                            f"{seed_backend.replace('.', '')}"
                        ),
                    }
                )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "schema": "trafficwm.seed-backend-matrix-workflows.v1",
                "count": len(records),
                "workflows": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"count": len(records), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
