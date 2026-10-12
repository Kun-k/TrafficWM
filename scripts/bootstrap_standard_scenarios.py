#!/usr/bin/env python3
"""Materialize the managed standard scenarios used by the UI."""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from backend.cosmos.traffic_scene_adapter import traffic_frames_to_recording
from backend.manager.scenario_library import (
    _step_sha256,
    prune_citynde_recording_vehicles,
)


SCENARIOS = (
    {
        "id": "normal-low-density",
        "name": "正常交通流",
        "description": "8 辆机动车，低到达率，无行人和非机动车。",
        "category": "normal",
        "source": "output/validation/pedestrian_flow_20260815/baseline_no_ped_40s.pkl",
        "target": "normal_low_density.pkl",
        "participants": {"motorized": 8, "pedestrians": 0, "cyclists": 0},
        "mixed_traffic_enabled": False,
        "cyclist_ratio": 0.0,
        "pedestrians_per_crosswalk": 0,
    },
    {
        "id": "pedestrian-low-density",
        "name": "信号路口行人",
        "description": "8 辆机动车与 12 条连续行人轨迹，行人按信号通过斑马线。",
        "category": "pedestrian",
        "source": "output/validation/pedestrian_flow_20260815/filtered_ped_40s.pkl",
        "target": "pedestrian_low_density.pkl",
        "participants": {"motorized": 8, "pedestrians": 12, "cyclists": 0},
        "mixed_traffic_enabled": True,
        "cyclist_ratio": 0.0,
        "pedestrians_per_crosswalk": 2,
    },
    {
        "id": "cyclist-low-density",
        "name": "最右侧非机动车",
        "description": "8 辆机动车与 1 辆非机动车，保留右侧车道和斑马线通行轨迹。",
        "category": "cyclist",
        "source": "output/validation/pedestrian_flow_20260815/scenario.pkl",
        "target": "cyclist_low_density.pkl",
        "participants": {"motorized": 8, "pedestrians": 0, "cyclists": 1},
        "mixed_traffic_enabled": True,
        "cyclist_ratio": 0.04,
        "pedestrians_per_crosswalk": 0,
        "strip_pedestrians": True,
    },
)


SEEDED_BACKEND_SCENARIOS = (
    {
        "id": "citynde-sparse-seeded",
        "name": "CityNDE 稀疏交通",
        "description": "15 辆机动车的 Boston 稀疏交通流，使用 CityNDE 续推并绑定同源 Transfer 首帧。",
        "category": "normal",
        "backend_model": "cnde",
        "target": "citynde_sparse_seeded.pkl",
        "traffic": "output/cosmos/experiments/20260816_185043_9fde88d7/operational_traffic.json",
        "map_state": "output/cosmos/experiments/20260816_185043_9fde88d7/map_state.json",
        "warmup": "output/scenarios/citynde/experiments/scenario_自然交通流低密度验证_1786877439939_20260816_185043_9fde88d7.warmup.pkl",
        "seed": "output/cosmos/experiments/20260816_185043_9fde88d7/seed/front_wide_terminal.png",
        "source_metadata": "output/scenarios/citynde/experiments/scenario_自然交通流低密度验证_1786877439939_20260816_185043_9fde88d7.pkl",
        "source_experiment_id": "20260816_185043_9fde88d7",
        "map_path": "algorithm_sources/CityNDE_src/assets/map/routed_map_nuplan_boston_015_small_signalized.pkl",
        "ego_id": "25",
        "initialization_seed": 42,
        "tags": ["Boston", "signalized", "sparse", "seeded", "CityNDE"],
    },
    {
        "id": "neuralnde-roundabout-seeded",
        "name": "NeuralNDE 环岛交通",
        "description": "AA_rdbt 环岛的 NeuralNDE 确定性初始化场景，绑定 dataset=AA_rdbt、seed=42 和同源首帧。",
        "category": "normal",
        "backend_model": "neuralnde",
        "target": "neuralnde_roundabout_seeded.pkl",
        "traffic": "output/cosmos/experiments/neuralnde_20260816_123141_94cf9ad4/operational_traffic.json",
        "map_state": "output/cosmos/experiments/neuralnde_20260816_123141_94cf9ad4/map_state.json",
        "warmup": "output/cosmos/experiments/neuralnde_20260816_123141_94cf9ad4/conditioning/neuralnde_warmup_10hz.pkl",
        "seed": "output/cosmos/experiments/neuralnde_20260816_123141_94cf9ad4/seed/front_wide_terminal.png",
        "source_metadata": "",
        "source_experiment_id": "neuralnde_20260816_123141_94cf9ad4",
        "map_path": "AA_rdbt",
        "dataset": "AA_rdbt",
        "ego_id": "3304",
        "initialization_seed": 42,
        "native_traffic_fps": 25.0,
        "tags": ["AA_rdbt", "roundabout", "seeded", "NeuralNDE"],
    },
    {
        "id": "rulebased-sparse-seeded",
        "name": "IDM+MOBIL 规则稀疏交通",
        "description": "8 辆机动车的 Boston 规则交通流，使用 IDM 跟驰和 MOBIL 换道并绑定同源首帧。",
        "category": "normal",
        "backend_model": "rulebased",
        "target": "rulebased_sparse_seeded.pkl",
        "traffic": "output/cosmos/experiments/20260819_005713_2a3c09c4/operational_traffic.json",
        "map_state": "output/cosmos/experiments/20260819_005713_2a3c09c4/map_state.json",
        "warmup": "output/scenarios/citynde/experiments/scenario_rulebased_sparse8_final_hot_10s_20260819_005713_2a3c09c4.warmup.pkl",
        "seed": "output/cosmos/experiments/20260819_005713_2a3c09c4/seed/front_wide_terminal.png",
        "source_metadata": "output/scenarios/citynde/experiments/scenario_rulebased_sparse8_final_hot_10s_20260819_005713_2a3c09c4.pkl",
        "source_experiment_id": "20260819_005713_2a3c09c4",
        "map_path": "algorithm_sources/CityNDE_src/assets/map/routed_map_nuplan_boston_015_small_signalized.pkl",
        "ego_id": "25",
        "initialization_seed": 42,
        "traffic_controller": "idm_mobil",
        "tags": ["Boston", "signalized", "sparse", "seeded", "IDM", "MOBIL"],
    },
)


def _read_metadata(source: Path) -> dict[str, Any]:
    path = source.with_suffix(source.suffix + ".meta.json")
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _without_pedestrians(source: Path, target: Path) -> None:
    with source.open("rb") as stream:
        data = pickle.load(stream)
    steps = len(data.get("vehicle_id_per_step") or [])
    data["pedestrian_id_per_step"] = [[] for _ in range(steps)]
    data["pedestrian_state_per_step"] = [[] for _ in range(steps)]
    data["pedestrian_static_attribute"] = {}
    with target.open("wb") as stream:
        pickle.dump(data, stream, protocol=pickle.HIGHEST_PROTOCOL)


def _tail_initialization(recording: dict[str, Any], history_frames: int = 11) -> dict[str, Any]:
    step_keys = [
        str(key)
        for key, value in recording.items()
        if str(key).endswith("_per_step") and hasattr(value, "__len__")
    ]
    if not step_keys:
        raise ValueError("Warmup recording has no per-step streams")
    frame_count = min(len(recording[key]) for key in step_keys)
    if frame_count < history_frames:
        raise ValueError(
            f"Warmup recording has {frame_count} states; {history_frames} are required"
        )
    initialization = dict(recording)
    for key in step_keys:
        initialization[key] = [
            deepcopy(value) for value in recording[key][frame_count - history_frames : frame_count]
        ]
    return initialization


def _align_first_state(
    recording: dict[str, Any], initialization: dict[str, Any]
) -> None:
    """Use the exact warmup terminal state as the reusable scene boundary."""
    for key in list(initialization):
        if str(key).endswith("_per_step") and key not in recording:
            initialization.pop(key)
    for key, values in recording.items():
        if not str(key).endswith("_per_step"):
            continue
        history = initialization.get(key)
        if not values or history is None or not len(history):
            raise ValueError(f"Initialization history is missing {key}")
        values[0] = deepcopy(history[-1])


def _peak_participants(recording: dict[str, Any]) -> dict[str, int]:
    actor_types = {
        str(actor_id): str(actor_type).lower()
        for actor_id, actor_type in (recording.get("road_user_type") or {}).items()
    }
    peak_motorized = 0
    peak_cyclists = 0
    for actor_ids in recording.get("vehicle_id_per_step") or []:
        cyclist_count = sum(
            "cycl" in actor_types.get(str(actor_id), "") for actor_id in actor_ids
        )
        peak_cyclists = max(peak_cyclists, cyclist_count)
        peak_motorized = max(peak_motorized, len(actor_ids) - cyclist_count)
    peak_pedestrians = max(
        (len(actor_ids) for actor_ids in recording.get("pedestrian_id_per_step") or []),
        default=0,
    )
    return {
        "motorized": int(peak_motorized),
        "pedestrians": int(peak_pedestrians),
        "cyclists": int(peak_cyclists),
    }


def _initial_participants(recording: dict[str, Any]) -> dict[str, int]:
    actor_types = {
        str(actor_id): str(actor_type).lower()
        for actor_id, actor_type in (recording.get("road_user_type") or {}).items()
    }
    actor_ids = [
        str(actor_id)
        for actor_id in (recording.get("vehicle_id_per_step") or [[]])[0]
    ]
    cyclists = sum("cycl" in actor_types.get(actor_id, "") for actor_id in actor_ids)
    embedded_pedestrians = sum(
        "ped" in actor_types.get(actor_id, "") for actor_id in actor_ids
    )
    pedestrians = len((recording.get("pedestrian_id_per_step") or [[]])[0])
    return {
        "motorized": len(actor_ids) - cyclists - embedded_pedestrians,
        "pedestrians": pedestrians + embedded_pedestrians,
        "cyclists": cyclists,
    }


def _workspace_reference(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def _materialize_seeded_backend_scenario(
    root: Path,
    target_root: Path,
    definition: dict[str, Any],
) -> dict[str, str]:
    required = {
        key: (root / str(definition[key])).resolve()
        for key in ("traffic", "map_state", "warmup", "seed")
    }
    missing = [str(path.relative_to(root)) for path in required.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))

    frames = json.loads(required["traffic"].read_text(encoding="utf-8"))
    map_state = json.loads(required["map_state"].read_text(encoding="utf-8"))
    if not isinstance(frames, list) or len(frames) < 2:
        raise ValueError(f"Traffic source has no usable timeline: {required['traffic']}")
    if not isinstance(map_state, dict):
        raise ValueError(f"Map state is invalid: {required['map_state']}")

    target = target_root / str(definition["target"])
    traffic_frames_to_recording(
        frames,
        map_state,
        target,
        source_fps=10.0,
        duration_seconds=10.0,
    )
    with target.open("rb") as stream:
        recording = pickle.load(stream)
    initial_actor_ids = {
        str(actor_id) for actor_id in recording["vehicle_id_per_step"][0]
    }
    all_actor_ids = {
        str(actor_id)
        for actor_ids in recording["vehicle_id_per_step"]
        for actor_id in actor_ids
    }
    recording, _ = prune_citynde_recording_vehicles(
        recording,
        remove_ids=all_actor_ids - initial_actor_ids,
    )
    with required["warmup"].open("rb") as stream:
        initialization = _tail_initialization(pickle.load(stream))
    _align_first_state(recording, initialization)

    initialization_path = target.with_suffix(".init.pkl")
    image_path = target.with_suffix(".seed.png")
    with target.open("wb") as stream:
        pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
    with initialization_path.open("wb") as stream:
        pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
    shutil.copy2(required["seed"], image_path)

    ego_id = str(definition.get("ego_id") or "").strip()
    if not ego_id:
        ego_id = str((frames[0].get("ego") or {}).get("id") or "").strip()
    first_ids = {str(actor_id) for actor_id in recording["vehicle_id_per_step"][0]}
    if not ego_id or ego_id not in first_ids:
        raise ValueError(
            f"Camera ego {ego_id or '<missing>'} is absent from {definition['id']}"
        )

    scenario_hash = _step_sha256(recording, 0)
    initialization_hash = _step_sha256(initialization, -1)
    if not scenario_hash or scenario_hash != initialization_hash:
        raise ValueError(f"First-state alignment failed for {definition['id']}")
    with Image.open(image_path) as image:
        width, height = image.size
        image.verify()
    if (width, height) != (1280, 704):
        raise ValueError(
            f"First frame for {definition['id']} is {width}x{height}, expected 1280x704"
        )

    source_metadata_path = str(definition.get("source_metadata") or "").strip()
    source_metadata = (
        _read_metadata(root / source_metadata_path) if source_metadata_path else {}
    )
    for key in list(source_metadata):
        if key == "use_existing_seed" or str(key).startswith("seed_"):
            source_metadata.pop(key, None)
    backend_model = str(definition["backend_model"])
    metadata = {
        **source_metadata,
        "schema": "denseworld.standard-scenario.v2",
        "library_id": definition["id"],
        "library_name": definition["name"],
        "library_description": definition["description"],
        "library_category": definition["category"],
        "library_tags": list(definition.get("tags") or []),
        "backend_model": backend_model,
        "standard_backend_locked": True,
        "traffic_controller": str(definition.get("traffic_controller") or ""),
        "dataset": str(definition.get("dataset") or ""),
        "map_path": str(definition["map_path"]),
        "init_mode": "official_dataset" if backend_model == "neuralnde" else "data",
        "init_file": _workspace_reference(root, initialization_path),
        "initialization_seed": int(definition.get("initialization_seed", 42)),
        "total_step": 100,
        "sim_resolution": 0.1,
        "max_sim_time": 10.0,
        "recording_operational_start_step": 0,
        "arrival_rate": 0.0,
        "lane_arrival_rates": {},
        "mixed_traffic_enabled": False,
        "cyclist_ratio": 0.0,
        "pedestrians_per_crosswalk": 0,
        "max_pedestrians": 0,
        "participants": _initial_participants(recording),
        "peak_participants": _peak_participants(recording),
        "source_path": _workspace_reference(root, required["traffic"]),
        "source_format": "denseworld.normalized-traffic",
        "source_start_seconds": 0.0,
        "source_end_seconds": 10.0,
        "native_traffic_fps": float(definition.get("native_traffic_fps", 10.0)),
        "use_existing_seed": True,
        "seed_image": _workspace_reference(root, image_path),
        "seed_init_file": _workspace_reference(root, initialization_path),
        "seed_source": "same_initialization_world_seed",
        "seed_source_experiment_id": definition["source_experiment_id"],
        "seed_source_time_seconds": 0.0,
        "seed_source_frame": 0,
        "seed_source_fps": 30.0,
        "seed_warmup_seconds": 1.0,
        "seed_scenario_state_step": 0,
        "seed_initialization_state_step": 10,
        "seed_initialization_history_frames": 11,
        "seed_alignment": "exact_traffic_boundary",
        "seed_ego_id": ego_id,
        "seed_width": width,
        "seed_height": height,
        "seed_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "seed_init_sha256": hashlib.sha256(initialization_path.read_bytes()).hexdigest(),
        "seed_state_sha256": scenario_hash,
    }
    metadata_path = target.with_suffix(target.suffix + ".meta.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "id": str(definition["id"]),
        "path": _workspace_reference(root, target),
        "source": _workspace_reference(root, required["traffic"]),
    }


def bootstrap(root: Path) -> dict[str, Any]:
    root = root.resolve()
    target_root = root / "output" / "scenarios" / "citynde" / "library"
    target_root.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []
    for definition in SCENARIOS:
        source = root / str(definition["source"])
        if not source.is_file():
            missing.append(str(definition["source"]))
            continue
        target = target_root / str(definition["target"])
        refresh = not target.is_file() or source.stat().st_mtime > target.stat().st_mtime
        existing_metadata = _read_metadata(target)
        if refresh:
            if definition.get("strip_pedestrians"):
                _without_pedestrians(source, target)
                shutil.copystat(source, target)
            else:
                shutil.copy2(source, target)

        metadata = _read_metadata(source)
        for key in list(metadata):
            if key == "use_existing_seed" or str(key).startswith("seed_"):
                metadata.pop(key, None)
        preserved_seed = {
            key: value
            for key, value in existing_metadata.items()
            if key == "use_existing_seed" or str(key).startswith("seed_")
        }
        preserve_seed = bool(
            not refresh
            and preserved_seed.get("use_existing_seed")
            and target.with_suffix(".seed.png").is_file()
            and target.with_suffix(".init.pkl").is_file()
        )
        metadata.update(
            {
                "library_id": definition["id"],
                "library_name": definition["name"],
                "library_description": definition["description"],
                "library_category": definition["category"],
                "library_tags": ["Boston", "signalized", "low-density"],
                "participants": definition["participants"],
                "source_path": str(definition["source"]),
                "arrival_rate": 0.0002,
                "mixed_traffic_enabled": definition["mixed_traffic_enabled"],
                "cyclist_ratio": definition["cyclist_ratio"],
                "pedestrians_per_crosswalk": definition["pedestrians_per_crosswalk"],
                # A source refresh invalidates the old RGB/state pair. Otherwise a
                # previously acquired and adjacent seed bundle survives restarts.
                "use_existing_seed": False,
                "seed_image": "",
            }
        )
        if preserve_seed:
            metadata.update(preserved_seed)
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        records.append(
            {
                "id": definition["id"],
                "path": str(target.relative_to(root)).replace("\\", "/"),
                "source": str(definition["source"]),
            }
        )
    for definition in SEEDED_BACKEND_SCENARIOS:
        try:
            records.append(
                _materialize_seeded_backend_scenario(root, target_root, definition)
            )
        except (FileNotFoundError, OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            missing.append(f"{definition['id']}: {exc}")
    return {"ok": not missing, "records": records, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = bootstrap(args.root)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
