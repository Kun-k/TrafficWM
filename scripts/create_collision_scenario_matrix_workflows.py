#!/usr/bin/env python3
"""Publish six deterministic collision-matrix workflows to the local manager."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8890/api/v1"
LIBRARY_DIR = ROOT / "output/scenarios/citynde/library"
SCENARIO_MANIFEST = ROOT / "output/validation/collision_scenario_matrix_20260828/scenarios.json"
OUTPUT = ROOT / "output/validation/collision_scenario_matrix_20260828/workflows.json"


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


def _workflow(metadata: dict[str, Any]) -> dict[str, Any]:
    duration_seconds = (
        6
        if (metadata.get("expected_collision") or {}).get("road_form") == "roundabout"
        else 12
    )
    return {
        "name": f"{metadata['library_name']}-{duration_seconds}秒验证",
        "task_id": "DW-TASK-0001",
        "scenario_mode": "library",
        "scenario_execution_mode": "replay",
        "scenario_id": str(metadata["library_id"]),
        "map_path": "",
        "map_init_mode": "data",
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
        "traffic_model": "cnde",
        "duration_seconds": duration_seconds,
        "gpu_id": "4",
        "arrival_rate": 0.0,
        "world_local_target_count": int(metadata["participants"]["motorized"]),
        "world_initial_vehicle_limit": int(metadata["participants"]["motorized"]),
        "world_loop_ego": False,
        "max_pedestrians": 0,
        "world_omnidreams_actor_max_count": int(
            metadata.get("world_omnidreams_actor_max_count") or 3
        ),
        "world_omnidreams_actor_allow_overlap": True,
        "world_omnidreams_actor_hood_occlusion_distance_m": 0.0,
        "world_omnidreams_actor_hood_occlusion_lateral_m": 0.0,
        "world_omnidreams_actor_oncoming_lateral_exclusion_m": 0.0,
        "world_omnidreams_save_control_video": True,
        "multimodal_enabled": True,
        "dreams_enabled": True,
        "world_seed_backend": "transfer1",
        "world_seed_alignment_mode": "opening_restart",
        "world_transfer_seed": 1,
        "world_omnidreams_seed": int(
            metadata["world_omnidreams_seed"]
            if metadata.get("world_omnidreams_seed") is not None
            else 1
        ),
        "world_prompt": str(metadata.get("default_world_prompt") or ""),
        "world_omnidreams_segment_seconds": 0.0,
        "world_omnidreams_rollover_mode": "latest",
        "world_omnidreams_transition_frames": 0,
        "world_stationary_anchor_enabled": False,
        "use_existing_seed": bool(metadata.get("seed_image")),
        "evaluation": {"safety": 45, "comfort": 25, "efficiency": 30},
        "evaluation_system_id": "DW-EVAL-0001",
        "evaluation_system_name": "碰撞轨迹、航向连续性与视频一致性评价",
        "scenario_count": 1,
        "seed": 42,
        "vehicle_size_mode": "passenger_only",
        "initial_speed_mode": "recorded",
        "save_result": True,
        "mixed_traffic_enabled": False,
        "expected_collision": dict(metadata.get("expected_collision") or {}),
    }


def main() -> int:
    manifest = json.loads(SCENARIO_MANIFEST.read_text(encoding="utf-8"))
    existing = _request("/workflows").get("workflows") or []
    by_scenario = {str(item.get("scenario_id") or ""): item for item in existing}
    records = []
    for record in manifest["records"]:
        scenario_path = ROOT / record["path"]
        metadata = json.loads(
            scenario_path.with_suffix(scenario_path.suffix + ".meta.json").read_text(
                encoding="utf-8"
            )
        )
        workflow = _workflow(metadata)
        current = by_scenario.get(str(metadata["library_id"]))
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
                "duration_seconds": saved["duration_seconds"],
                "world_seed_backend": saved["world_seed_backend"],
                "expected_collision": metadata["expected_collision"],
            }
        )
    output = {
        "schema": "trafficwm.collision-scenario-matrix-workflows.v1",
        "count": len(records),
        "workflows": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**output, "path": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
