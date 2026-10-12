#!/usr/bin/env python3
"""Build deterministic sparse CityNDE initial states on a Tianjin road corridor."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image


MAIN_START_LANE = "9965511162_0"
OPPOSITE_START_LANE = "9990985350_0"
AV_ID = "AV"
HISTORY_STEPS = 11
STEP_SECONDS = 0.1

RULE_DEMO_DEFINITIONS = (
    {
        "id": "tianjin-rule-low-seeded",
        "name": "天津直路规则低速",
        "description": "天津约 426 m 双向直路，8 辆机动车，AV 从道路起端出发；BV 与 AV 均使用 IDM+MOBIL 低速规则控制。",
        "stem": "tianjin_rule_low_seeded",
        "init_name": "tianjin_straight_rule_low.init.pkl",
        "target_speed_mps": 3.5,
        "tags": ["Tianjin", "straight-road", "sparse", "seeded", "IDM", "MOBIL", "low-speed"],
    },
    {
        "id": "tianjin-rule-high-seeded",
        "name": "天津直路规则高速",
        "description": "天津约 426 m 双向直路，8 辆机动车，AV 从道路起端出发；BV 与 AV 均使用 IDM+MOBIL 高速档规则控制。",
        "stem": "tianjin_rule_high_seeded",
        "init_name": "tianjin_straight_rule_high.init.pkl",
        "target_speed_mps": 6.5,
        "tags": ["Tianjin", "straight-road", "sparse", "seeded", "IDM", "MOBIL", "high-speed"],
    },
)

RULE_DEMO_WORKFLOWS = (
    {
        "id": "DW-WF-20260820-0004",
        "name": "演示-03 天津直路规则低速 60秒",
        "scenario_id": "tianjin-rule-low-seeded",
        "speed_mps": 3.5,
        "prompt": "A clear daytime forward-facing dashcam view moving slowly along a straight two-way urban boulevard in Tianjin, China. Mid-rise buildings line both sides, lane markings and curbs remain geometrically stable, sparse passenger cars keep safe spacing, realistic road surface, natural daylight, stable camera, consistent vehicle identity and motion.",
    },
    {
        "id": "DW-WF-20260820-0005",
        "name": "演示-04 天津直路规则高速 60秒",
        "scenario_id": "tianjin-rule-high-seeded",
        "speed_mps": 6.5,
        "prompt": "A clear daytime forward-facing dashcam view traveling steadily along a straight two-way urban boulevard in Tianjin, China. Mid-rise buildings line both sides, lane markings and curbs remain geometrically stable, sparse passenger cars follow realistic traffic flow, natural daylight, stable camera, consistent vehicle identity and smooth forward motion.",
    },
)


def _angle_difference(first: float, second: float) -> float:
    return abs((float(first) - float(second) + math.pi) % (2.0 * math.pi) - math.pi)


def _lane_chain(polylines: dict[Any, dict[str, Any]], start_lane: Any) -> list[Any]:
    chain: list[Any] = []
    current = start_lane
    while (
        current in polylines
        and current not in chain
        and int(polylines[current].get("type", -1)) == 0
        and len(chain) < 512
    ):
        chain.append(current)
        candidates = [
            lane_id
            for lane_id in polylines[current].get("next_lanes_id", [])
            if lane_id in polylines
            and lane_id not in chain
            and int(polylines[lane_id].get("type", -1)) == 0
        ]
        if not candidates:
            break
        current_heading = float(np.asarray(polylines[current]["states"])[-1, 2])
        current = min(
            candidates,
            key=lambda lane_id: (
                _angle_difference(
                    current_heading,
                    float(np.asarray(polylines[lane_id]["states"])[0, 2]),
                ),
                str(lane_id),
            ),
        )
    return chain


def _chain_path(
    polylines: dict[Any, dict[str, Any]],
    lane_ids: Iterable[Any],
) -> tuple[np.ndarray, np.ndarray]:
    points: list[np.ndarray] = []
    for lane_id in lane_ids:
        states = np.asarray(polylines[lane_id]["states"], dtype=np.float64)
        if states.ndim != 2 or states.shape[1] < 3 or len(states) < 2:
            raise ValueError(f"Lane {lane_id!r} has invalid states")
        if points and np.linalg.norm(points[-1][-1, :2] - states[0, :2]) < 1e-6:
            states = states[1:]
        points.append(states[:, :3])
    path = np.concatenate(points, axis=0)
    segment_lengths = np.linalg.norm(np.diff(path[:, :2], axis=0), axis=1)
    distance = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    keep = np.concatenate(([True], np.diff(distance) > 1e-7))
    return path[keep], distance[keep]


def _sample_path(path: np.ndarray, distance: np.ndarray, longitudinal: float) -> np.ndarray:
    target = float(np.clip(longitudinal, distance[0], distance[-1]))
    upper = int(np.searchsorted(distance, target, side="right"))
    upper = min(max(1, upper), len(distance) - 1)
    lower = upper - 1
    span = max(1e-9, float(distance[upper] - distance[lower]))
    alpha = (target - float(distance[lower])) / span
    xy = path[lower, :2] * (1.0 - alpha) + path[upper, :2] * alpha
    heading_delta = (
        float(path[upper, 2]) - float(path[lower, 2]) + math.pi
    ) % (2.0 * math.pi) - math.pi
    heading = float(path[lower, 2]) + alpha * heading_delta
    return np.asarray([xy[0], xy[1], heading], dtype=np.float32)


def _history(path: np.ndarray, distance: np.ndarray, final_s: float, speed: float) -> np.ndarray:
    states = []
    for index in range(HISTORY_STEPS):
        seconds_before_final = (HISTORY_STEPS - index - 1) * STEP_SECONDS
        pose = _sample_path(path, distance, final_s - speed * seconds_before_final)
        heading = float(pose[2])
        states.append(
            [
                float(pose[0]),
                float(pose[1]),
                heading,
                speed * math.cos(heading),
                speed * math.sin(heading),
                0.0,
                0.0,
            ]
        )
    return np.asarray(states, dtype=np.float32)


def _traffic_light_history(polylines: dict[Any, dict[str, Any]]) -> tuple[list[list[Any]], list[np.ndarray]]:
    lane_ids = [
        lane_id
        for lane_id, lane in polylines.items()
        if int(lane.get("type", -1)) == 4
    ]
    states = []
    for lane_id in lane_ids:
        phase = str(polylines[lane_id].get("phase") or "r")
        states.append([1.0, 0.0, 0.0, 0.0] if phase[:1] == "g" else [0.0, 0.0, 1.0, 0.0])
    state_array = np.asarray(states, dtype=np.float32)
    return (
        [list(lane_ids) for _ in range(HISTORY_STEPS)],
        [state_array.copy() for _ in range(HISTORY_STEPS)],
    )


def _build_initialization(
    source: dict[str, Any],
    *,
    main_vehicle_count: int,
    opposite_vehicle_count: int,
    speed: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    polylines = source["map"]["polyline"]
    main_lanes = _lane_chain(polylines, MAIN_START_LANE)
    opposite_lanes = _lane_chain(polylines, OPPOSITE_START_LANE)
    if len(main_lanes) < 40 or len(opposite_lanes) < 40:
        raise ValueError("Configured Tianjin corridor is shorter than expected")
    if any(int(polylines[lane_id].get("type", -1)) != 0 for lane_id in [*main_lanes, *opposite_lanes]):
        raise ValueError("Configured corridor contains a signal-controlled lane")

    main_path, main_distance = _chain_path(polylines, main_lanes)
    opposite_path, opposite_distance = _chain_path(polylines, opposite_lanes)
    if main_distance[-1] < 400.0 or opposite_distance[-1] < 400.0:
        raise ValueError("Configured corridor must provide at least 400 m in both directions")
    if _angle_difference(main_path[len(main_path) // 2, 2], opposite_path[len(opposite_path) // 2, 2]) < math.radians(150.0):
        raise ValueError("Configured corridor lanes are not opposing directions")

    main_positions = [10.0, 45.0, 80.0, 120.0, 160.0, 200.0][:main_vehicle_count]
    opposite_positions = [65.0, 190.0][:opposite_vehicle_count]
    actor_specs: list[tuple[Any, np.ndarray]] = []
    for index, longitudinal in enumerate(main_positions):
        actor_id: Any = AV_ID if index == 0 else f"BV-main-{index}"
        actor_specs.append((actor_id, _history(main_path, main_distance, longitudinal, speed)))
    for index, longitudinal in enumerate(opposite_positions):
        actor_specs.append(
            (
                f"BV-opposite-{index + 1}",
                _history(opposite_path, opposite_distance, longitudinal, speed),
            )
        )

    vehicle_ids = [actor_id for actor_id, _states in actor_specs]
    vehicle_frames = [
        np.stack([states[step] for _actor_id, states in actor_specs], axis=0)
        for step in range(HISTORY_STEPS)
    ]
    dynamic_ids, dynamic_states = _traffic_light_history(polylines)
    static = {actor_id: np.asarray([4.65, 1.84, 1.48], dtype=np.float32) for actor_id in vehicle_ids}
    initialization = {
        "simulator_meta_info": {
            "type": "MixedTrafficInteractiveSimulator",
            "resolution": STEP_SECONDS,
            "type_map_manager": "RouteTLVectorMap",
            "type_agent_manager": "VehicleRecordManager",
            "type_scenario_manager": "RouteTLScenarioManager",
            "trafficwm_realtime_initialization": {
                "schema": "trafficwm.tianjin-realtime-init.v1",
                "history_steps": HISTORY_STEPS,
                "ego_id": AV_ID,
            },
        },
        "dynamic_polyline_id_per_step": dynamic_ids,
        "dynamic_polyline_state_per_step": dynamic_states,
        "vehicle_id_per_step": [list(vehicle_ids) for _ in range(HISTORY_STEPS)],
        "vehicle_state_per_step": vehicle_frames,
        "vehicle_static_attribute": static,
        "road_user_type": {actor_id: "vehicle" for actor_id in vehicle_ids},
        "vehicle_class": {actor_id: "sedan" for actor_id in vehicle_ids},
        "vehicle_type": {
            actor_id: "csim.agent.agent.RoutedVehicle" for actor_id in vehicle_ids
        },
        "pedestrian_id_per_step": [[] for _ in range(HISTORY_STEPS)],
        "pedestrian_state_per_step": [[] for _ in range(HISTORY_STEPS)],
        "pedestrian_static_attribute": {},
        "pedestrian_crosswalk": {},
        "mixed_traffic": {
            "schema": "trafficwm.mixed-traffic.v1",
            "enabled": False,
            "cyclist_ratio": 0.0,
            "pedestrians_per_crosswalk": 0,
            "max_pedestrians": 0,
            "vehicle_size_mode": "passenger_only",
        },
    }
    report = {
        "schema": "trafficwm.tianjin-realtime-scenario.v1",
        "map": str(source.get("map_metadata", {}).get("name") or "Tianjin"),
        "main_start_lane": MAIN_START_LANE,
        "opposite_start_lane": OPPOSITE_START_LANE,
        "main_lane_count": len(main_lanes),
        "opposite_lane_count": len(opposite_lanes),
        "main_length_m": round(float(main_distance[-1]), 3),
        "opposite_length_m": round(float(opposite_distance[-1]), 3),
        "signal_lane_count": 0,
        "vehicle_count": len(vehicle_ids),
        "main_direction_vehicle_count": len(main_positions),
        "opposite_direction_vehicle_count": len(opposite_positions),
        "ego_id": AV_ID,
        "speed_mps": float(speed),
        "history_steps": HISTORY_STEPS,
        "step_seconds": STEP_SECONDS,
        "initial_vehicle_ids": vehicle_ids,
    }
    return initialization, report


def build(
    map_path: Path,
    output_dir: Path,
    speed: float,
    *,
    low_speed: float = 3.0,
    high_speed: float = 5.5,
) -> dict[str, Any]:
    with map_path.open("rb") as stream:
        source = pickle.load(stream)
    if not isinstance(source, dict) or "map" not in source:
        raise ValueError(f"Unsupported CityNDE map bundle: {map_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    definitions = (
        ("tianjin_unsignalized_bidirectional_8v.init.pkl", 6, 2, speed),
        ("tianjin_unsignalized_av_only.init.pkl", 1, 0, speed),
        ("tianjin_straight_rule_low.init.pkl", 6, 2, low_speed),
        ("tianjin_straight_rule_high.init.pkl", 6, 2, high_speed),
    )
    records = []
    for filename, main_count, opposite_count, initial_speed in definitions:
        initialization, report = _build_initialization(
            copy.deepcopy(source),
            main_vehicle_count=main_count,
            opposite_vehicle_count=opposite_count,
            speed=initial_speed,
        )
        target = output_dir / filename
        with target.open("wb") as stream:
            pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
        report_path = target.with_suffix(target.suffix + ".json")
        report_path.write_text(
            json.dumps({**report, "path": str(target)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        records.append({**report, "path": str(target), "report": str(report_path)})

    manifest = {
        "schema": "trafficwm.tianjin-realtime-scenarios.v1",
        "map_path": str(map_path),
        "records": records,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {**manifest, "manifest": str(manifest_path)}


def _step_sha256(recording: dict[str, Any], step: int) -> str:
    ids = recording.get("vehicle_id_per_step") or []
    index = step if step >= 0 else len(ids) + step
    payload = {
        str(key): value[index]
        for key, value in recording.items()
        if str(key).endswith("_per_step")
    }
    return hashlib.sha256(
        pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    ).hexdigest()


def _terminal_recording(initialization: dict[str, Any]) -> dict[str, Any]:
    recording = copy.deepcopy(initialization)
    for key, values in list(recording.items()):
        if str(key).endswith("_per_step"):
            if not len(values):
                raise ValueError(f"Initialization stream {key} is empty")
            recording[key] = [copy.deepcopy(values[-1]), copy.deepcopy(values[-1])]
    return recording


def publish_rule_demo_library(
    root: Path,
    output_dir: Path,
    library_dir: Path,
    seed_image: Path,
    map_path: Path,
) -> dict[str, Any]:
    if not seed_image.is_file():
        raise FileNotFoundError(seed_image)
    with Image.open(seed_image) as image:
        seed_width, seed_height = image.size
        image.verify()
    if (seed_width, seed_height) != (1280, 704):
        raise ValueError(
            f"Tianjin seed image is {seed_width}x{seed_height}; expected 1280x704"
        )

    library_dir.mkdir(parents=True, exist_ok=True)
    published = []
    for definition in RULE_DEMO_DEFINITIONS:
        source_init = output_dir / str(definition["init_name"])
        with source_init.open("rb") as stream:
            initialization = pickle.load(stream)
        if len(initialization.get("vehicle_id_per_step") or []) != HISTORY_STEPS:
            raise ValueError(f"{source_init} does not contain {HISTORY_STEPS} history states")
        recording = _terminal_recording(initialization)

        target = library_dir / f"{definition['stem']}.pkl"
        init_target = library_dir / f"{definition['stem']}.init.pkl"
        image_target = library_dir / f"{definition['stem']}.seed.png"
        with target.open("wb") as stream:
            pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
        shutil.copy2(source_init, init_target)
        shutil.copy2(seed_image, image_target)

        scenario_hash = _step_sha256(recording, 0)
        initialization_hash = _step_sha256(initialization, -1)
        if scenario_hash != initialization_hash:
            raise ValueError(f"Scenario/init boundary mismatch for {definition['id']}")
        relative = lambda path: str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
        initial_speed = float(
            np.linalg.norm(
                np.asarray(initialization["vehicle_state_per_step"][-1][0], dtype=np.float64)[3:5]
            )
        )
        target_speed = float(definition["target_speed_mps"])
        metadata = {
            "schema": "denseworld.standard-scenario.v2",
            "library_id": definition["id"],
            "library_name": definition["name"],
            "library_description": definition["description"],
            "library_category": "normal",
            "library_tags": definition["tags"],
            "backend_model": "rulebased",
            "standard_backend_locked": True,
            "traffic_controller": "idm_mobil",
            "map_path": relative(map_path),
            "init_mode": "data",
            "init_file": relative(init_target),
            "initialization_seed": 42,
            "total_step": 600,
            "sim_resolution": STEP_SECONDS,
            "max_sim_time": 60.0,
            "recording_operational_start_step": 0,
            "arrival_rate": 0.0,
            "lane_arrival_rates": {},
            "mixed_traffic_enabled": False,
            "cyclist_ratio": 0.0,
            "pedestrians_per_crosswalk": 0,
            "max_pedestrians": 0,
            "vehicle_size_mode": "passenger_only",
            "initial_speed_mode": "fixed",
            "signalize_unsignalized_map": False,
            "world_loop_ego": False,
            "participants": {"motorized": 8, "pedestrians": 0, "cyclists": 0},
            "peak_participants": {"motorized": 8, "pedestrians": 0, "cyclists": 0},
            "source_path": relative(source_init),
            "source_format": "trafficwm.tianjin-realtime-init.v1",
            "source_start_seconds": 0.0,
            "source_end_seconds": 0.1,
            "native_traffic_fps": 10.0,
            "use_existing_seed": True,
            "seed_image": relative(image_target),
            "seed_init_file": relative(init_target),
            "seed_source": "cosmos-transfer2.5-seven-view-matched-control",
            "seed_source_experiment_id": "20260820_233536_f0ce1194",
            "seed_source_time_seconds": 0.0,
            "seed_source_frame": 0,
            "seed_source_fps": 30.0,
            "seed_warmup_seconds": 0.0,
            "seed_scenario_state_step": 0,
            "seed_initialization_state_step": 10,
            "seed_initialization_history_frames": HISTORY_STEPS,
            "seed_alignment": "exact_control_frame_t0",
            "seed_ego_id": AV_ID,
            "seed_width": seed_width,
            "seed_height": seed_height,
            "seed_sha256": hashlib.sha256(image_target.read_bytes()).hexdigest(),
            "seed_init_sha256": hashlib.sha256(init_target.read_bytes()).hexdigest(),
            "seed_state_sha256": scenario_hash,
            "rule_control": {
                "bv_controller": "SparseIDMMOBILController",
                "bv_desired_speed_mps": target_speed,
                "av_controller": "IDMMOBILStreamController",
                "av_desired_speed_mps": target_speed,
                "initial_speed_mps": round(initial_speed, 3),
            },
        }
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_path = target.with_suffix(".manifest.json")
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "denseworld.normalized-recording.v1",
                    "recording": str(target),
                    "source_frames": 2,
                    "source_fps": 10.0,
                    "recording_frames": 2,
                    "duration_seconds": 0.1,
                    "actor_tracks": 8,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        published.append(
            {
                "id": definition["id"],
                "path": relative(target),
                "target_speed_mps": target_speed,
                "initial_speed_mps": round(initial_speed, 3),
            }
        )
    return {"schema": "trafficwm.tianjin-rule-demo-library.v1", "records": published}


def update_rule_demo_workflows(workflow_path: Path) -> dict[str, Any]:
    payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflows = payload.get("workflows") if isinstance(payload, dict) else payload
    if not isinstance(workflows, list):
        raise ValueError(f"Invalid workflow store: {workflow_path}")
    updated = []
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for definition in RULE_DEMO_WORKFLOWS:
        workflow = next(
            (
                item
                for item in workflows
                if str(item.get("id") or "") == str(definition["id"])
            ),
            None,
        )
        if workflow is None:
            raise ValueError(f"Workflow {definition['id']} does not exist")
        workflow.update(
            {
                "name": definition["name"],
                "scenario_mode": "library",
                "scenario_execution_mode": "continue",
                "scenario_id": definition["scenario_id"],
                "map_path": "",
                "map_init_mode": "data",
                "av_selection_mode": "existing",
                "av_model": "IDM_MOBIL",
                "command_mode": "state",
                "connection_mode": "internal",
                "traffic_model": "rulebased",
                "duration_seconds": 60,
                "gpu_id": "4",
                "arrival_rate": 0.0,
                # Keep a small moving near field around the ego. The source
                # bundle already contains seven BVs, so a target of eight
                # (which excludes the ego) causes unnecessary burst spawning.
                "world_local_target_count": 4,
                "world_initial_vehicle_limit": 8,
                "max_pedestrians": 0,
                "world_omnidreams_actor_max_count": 8,
                "rule_desired_speed_mps": float(definition["speed_mps"]),
                "av_desired_speed_mps": float(definition["speed_mps"]),
                "multimodal_enabled": True,
                "dreams_enabled": True,
                "world_prompt": definition["prompt"],
                "use_existing_seed": True,
                "scenario_count": 1,
                "seed": 42,
                "vehicle_size_mode": "passenger_only",
                "initial_speed_mode": "fixed",
                "save_result": True,
                "mixed_traffic_enabled": False,
                "updated_at": now,
            }
        )
        updated.append(
            {
                "id": definition["id"],
                "name": definition["name"],
                "scenario_id": definition["scenario_id"],
                "speed_mps": definition["speed_mps"],
            }
        )
    temporary = workflow_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "workflows": workflows}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(workflow_path)
    return {"schema": "trafficwm.tianjin-rule-demo-workflows.v1", "records": updated}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        type=Path,
        default=root / "algorithm_sources" / "CityNDE_src" / "assets" / "map" / "map_tianjin_part_5type_rebuild.pkl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "output" / "validation" / "tianjin_realtime_scenarios",
    )
    parser.add_argument("--speed", type=float, default=8.0)
    parser.add_argument("--low-speed", type=float, default=3.0)
    parser.add_argument("--high-speed", type=float, default=5.5)
    parser.add_argument("--publish-library", action="store_true")
    parser.add_argument("--update-workflows", action="store_true")
    parser.add_argument(
        "--workflow-store",
        type=Path,
        default=root / "output" / "platform" / "workflows.json",
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=root / "output" / "scenarios" / "citynde" / "library",
    )
    parser.add_argument(
        "--seed-image",
        type=Path,
        default=root
        / "output"
        / "validation"
        / "tianjin_realtime_scenarios"
        / "omnidreams_10s_fast"
        / "seed"
        / "front_wide_terminal.png",
    )
    args = parser.parse_args()
    result = build(
        args.map.resolve(),
        args.output_dir.resolve(),
        args.speed,
        low_speed=args.low_speed,
        high_speed=args.high_speed,
    )
    if args.publish_library:
        result["library"] = publish_rule_demo_library(
            root,
            args.output_dir.resolve(),
            args.library_dir.resolve(),
            args.seed_image.resolve(),
            args.map.resolve(),
        )
    if args.update_workflows:
        result["workflows"] = update_rule_demo_workflows(
            args.workflow_store.resolve()
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
