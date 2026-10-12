#!/usr/bin/env python3
"""Build seeded CNDE and rule scenarios for cnde_map_xa_wenying."""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_tianjin_realtime_scenarios as shared  # noqa: E402


MAIN_START_LANE = "1547"
OPPOSITE_START_LANE = "1591"
AV_ID = "AV"
HISTORY_STEPS = 11
STEP_SECONDS = 0.1
DEFAULT_PROMPT = (
    "Official 120-degree f-theta forward dashcam footage from a passenger car driving smoothly "
    "on a straight divided urban boulevard in Xi'an under clear daylight. The road continues "
    "perfectly straight for the entire sequence, with a fixed central vanishing point, constant "
    "lane count, parallel curbs, a straight median, and straight crisp lane markings. A clearly "
    "resolved ordinary sedan travels at medium distance ahead in the same lane, with additional "
    "sparse cars farther ahead in their mapped lanes. Preserve the supplied camera calibration, "
    "HD-map geometry, vehicle identity, scale, and motion in every frame. Dry charcoal-gray "
    "asphalt, mature plane trees, clipped green hedges, slender streetlights, and restrained "
    "pale-stone and light-gray mid-rise buildings remain realistic and stable. Natural neutral "
    "late-morning light produces consistent shadows. Only a narrow unchanged strip of the ego "
    "hood is visible along the bottom edge."
)
DENSE_RULE_PROMPT = (
    "Official 120-degree f-theta forward dashcam footage from a passenger car driving smoothly "
    "on a straight divided urban boulevard in Xi'an under clear daylight. The road continues "
    "perfectly straight for the entire sequence, with a fixed central vanishing point, constant "
    "lane count, parallel curbs, a straight median, and straight crisp lane markings. Dense but "
    "orderly passenger traffic moves in the mapped lanes. One clearly resolved sedan travels "
    "about twenty meters ahead in the same lane; its rear body, windows, lights, wheels, and edges "
    "remain sharp and stable, while additional correctly scaled sedans follow at safe intervals. "
    "Preserve the supplied camera calibration, HD-map geometry, vehicle identity, scale, and "
    "motion in every frame. Dry charcoal-gray asphalt, mature plane trees, clipped green hedges, "
    "slender streetlights, and restrained pale-stone and light-gray mid-rise buildings remain "
    "realistic and stable. Natural neutral late-morning light produces consistent shadows. Only "
    "a narrow unchanged strip of the ego hood is visible along the bottom edge."
)

SPARSE_TRANSFER_PROMPT = (
    "The video is captured by an official 120-degree f-theta front-wide camera mounted on a "
    "normal passenger car. The car drives forward on a perfectly straight divided boulevard in "
    "Xi'an. A clearly resolved modern sedan is centered about twenty meters ahead in the same "
    "lane, with a sharp rear body, windows, tail lamps, wheels, and natural paint reflections. "
    "Several additional sedans remain farther ahead in sparse orderly traffic. Dry dark-gray "
    "asphalt, crisp white dashed lane markings, straight concrete curbs, a low straight median, "
    "mature plane trees, clipped hedges, slender streetlights, and four-to-eight-story pale stone "
    "buildings line the road. Clear late-morning daylight, neutral color, stable shadows, a fixed "
    "central vanishing point, and only a narrow strip of plain ego hood at the bottom."
)
DENSE_TRANSFER_PROMPT = (
    "The video is captured by an official 120-degree f-theta front-wide camera mounted on a "
    "normal passenger car. The car drives forward on a perfectly straight divided boulevard in "
    "Xi'an. A clearly resolved modern sedan is centered about eighteen meters ahead in the same "
    "lane, showing a sharp rear body, windows, tail lamps, wheels, and natural paint reflections. "
    "Several correctly scaled sedans continue at safe intervals in dense orderly mapped traffic. "
    "Dry dark-gray asphalt, crisp white dashed lane markings, straight concrete curbs, a low "
    "straight median, mature plane trees, clipped hedges, slender streetlights, and four-to-eight-"
    "story pale stone buildings line the road. Clear late-morning daylight, neutral color, stable "
    "shadows, a fixed central vanishing point, and only a narrow strip of plain ego hood at the bottom."
)

SPARSE_DEFINITIONS = (
    {
        "id": "xa-wenying-cnde-seeded",
        "name": "西安文瀛直路 CityNDE 稀疏交通",
        "description": "文瀛地图约 214 m 双向直路，6 辆机动车，固定首帧，由 CityNDE 继续生成交通流。",
        "stem": "xa_wenying_cnde_seeded",
        "backend_model": "cnde",
        "traffic_controller": "citynde",
        "tags": ["XiAn", "Wenying", "straight-road", "sparse", "seeded", "CityNDE"],
    },
    {
        "id": "xa-wenying-rule-seeded",
        "name": "西安文瀛直路 IDM+MOBIL 稀疏交通",
        "description": "文瀛地图约 214 m 双向直路，6 辆机动车，固定首帧，由 IDM+MOBIL 规则模型继续生成交通流。",
        "stem": "xa_wenying_rule_seeded",
        "backend_model": "rulebased",
        "traffic_controller": "idm_mobil",
        "tags": ["XiAn", "Wenying", "straight-road", "sparse", "seeded", "IDM", "MOBIL"],
    },
)

DENSE_RULE_DEFINITIONS = (
    {
        "id": "xa-wenying-rule-dense-seeded",
        "name": "西安文瀛直路 IDM+MOBIL 密集交通",
        "description": (
            "文瀛地图约 214 m 双向直路，20 辆固定机动车，"
            "由 IDM+MOBIL 规则模型实时生成连续交通流。"
        ),
        "stem": "xa_wenying_rule_dense_seeded",
        "backend_model": "rulebased",
        "traffic_controller": "idm_mobil",
        "tags": ["XiAn", "Wenying", "straight-road", "dense", "seeded", "IDM", "MOBIL"],
    },
)

PROFILE_ACTOR_POSITIONS = {
    "sparse": {
        # A 20 m center-to-center lead gap is large enough for IDM at 5 m/s,
        # while remaining resolvable in the official 120-degree camera.
        "main": (10.0, 30.0, 65.0, 105.0),
        # Keep oncoming actors outside the near field at the end of the 5 s
        # Transfer1 warmup window.
        "opposite": (45.0, 105.0),
        "output_stem": "xa_wenying_sparse",
        "definitions": SPARSE_DEFINITIONS,
        "max_sim_time": 60.0,
        "desired_speed_mps": 5.0,
        "default_prompt": DEFAULT_PROMPT,
        "default_transfer_prompt": SPARSE_TRANSFER_PROMPT,
        "omnidreams_actor_max_count": 8,
    },
    "dense": {
        # The first lead is 18 m ahead and subsequent vehicles use 22 m gaps.
        # This improves Transfer1 vehicle pixel coverage without entering the
        # oversized near-field box regime.
        "main": (10.0, 28.0, 50.0, 72.0, 94.0, 116.0, 138.0, 160.0, 182.0),
        # At the 5 s warmup boundary these oncoming actors remain at least
        # roughly 34 m longitudinally ahead instead of crossing beside the rig.
        "opposite": (10.0, 22.0, 34.0, 46.0, 58.0, 70.0, 82.0, 94.0, 106.0, 118.0, 130.0),
        "output_stem": "xa_wenying_dense_rule",
        "definitions": DENSE_RULE_DEFINITIONS,
        "max_sim_time": 40.0,
        "desired_speed_mps": 5.0,
        "default_prompt": DENSE_RULE_PROMPT,
        "default_transfer_prompt": DENSE_TRANSFER_PROMPT,
        "omnidreams_actor_max_count": 12,
    },
}


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _load_map(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    polylines = payload.get("polyline") if isinstance(payload, dict) else None
    if not isinstance(polylines, dict):
        polylines = ((payload or {}).get("map") or {}).get("polyline")
    if not isinstance(polylines, dict):
        raise ValueError(f"Unsupported CityNDE map bundle: {path}")
    return {
        "map": {"polyline": polylines},
        "map_metadata": {"name": "cnde_map_xa_wenying"},
    }


def build_initialization(
    map_path: Path,
    output_dir: Path,
    speed_mps: float,
    *,
    profile: str = "sparse",
) -> dict[str, Any]:
    profile_config = PROFILE_ACTOR_POSITIONS[profile]
    source = _load_map(map_path)
    polylines = source["map"]["polyline"]
    main_lanes = shared._lane_chain(polylines, MAIN_START_LANE)
    opposite_lanes = shared._lane_chain(polylines, OPPOSITE_START_LANE)
    main_path, main_distance = shared._chain_path(polylines, main_lanes)
    opposite_path, opposite_distance = shared._chain_path(polylines, opposite_lanes)
    if main_distance[-1] < 200.0 or opposite_distance[-1] < 200.0:
        raise ValueError("Configured Wenying corridor must provide at least 200 m per direction")

    actor_specs = []
    for index, longitudinal in enumerate(profile_config["main"]):
        actor_id = AV_ID if index == 0 else f"BV-main-{index}"
        actor_specs.append(
            (actor_id, shared._history(main_path, main_distance, longitudinal, speed_mps))
        )
    for index, longitudinal in enumerate(profile_config["opposite"], start=1):
        actor_specs.append(
            (
                f"BV-opposite-{index}",
                shared._history(opposite_path, opposite_distance, longitudinal, speed_mps),
            )
        )
    vehicle_ids = [actor_id for actor_id, _states in actor_specs]
    vehicle_frames = [
        np.stack([states[step] for _actor_id, states in actor_specs], axis=0)
        for step in range(HISTORY_STEPS)
    ]
    dynamic_ids, dynamic_states = shared._traffic_light_history(polylines)
    initialization = {
        "simulator_meta_info": {
            "type": "MixedTrafficInteractiveSimulator",
            "resolution": STEP_SECONDS,
            "type_map_manager": "RouteTLVectorMap",
            "type_agent_manager": "VehicleRecordManager",
            "type_scenario_manager": "RouteTLScenarioManager",
            "trafficwm_realtime_initialization": {
                "schema": "trafficwm.xa-wenying-init.v1",
                "history_steps": HISTORY_STEPS,
                "ego_id": AV_ID,
            },
        },
        "dynamic_polyline_id_per_step": dynamic_ids,
        "dynamic_polyline_state_per_step": dynamic_states,
        "vehicle_id_per_step": [list(vehicle_ids) for _ in range(HISTORY_STEPS)],
        "vehicle_state_per_step": vehicle_frames,
        "vehicle_static_attribute": {
            actor_id: np.asarray([4.65, 1.84, 1.48], dtype=np.float32)
            for actor_id in vehicle_ids
        },
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
        "schema": "trafficwm.xa-wenying-scenario.v1",
        "map": "cnde_map_xa_wenying",
        "main_start_lane": MAIN_START_LANE,
        "opposite_start_lane": OPPOSITE_START_LANE,
        "main_lane_count": len(main_lanes),
        "opposite_lane_count": len(opposite_lanes),
        "main_length_m": round(float(main_distance[-1]), 3),
        "opposite_length_m": round(float(opposite_distance[-1]), 3),
        "vehicle_count": len(vehicle_ids),
        "ego_id": AV_ID,
        "speed_mps": float(speed_mps),
        "history_steps": HISTORY_STEPS,
        "step_seconds": STEP_SECONDS,
        "initial_vehicle_ids": vehicle_ids,
        "profile": profile,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{profile_config['output_stem']}.init.pkl"
    with target.open("wb") as stream:
        pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
    report_path = target.with_suffix(target.suffix + ".json")
    report_path.write_text(
        json.dumps({**report, "path": _relative(target)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"path": target, "report": report, "report_path": report_path}


def build_initialization_from_recording(
    recording_path: Path,
    output_dir: Path,
    *,
    boundary_step: int,
) -> dict[str, Any]:
    with recording_path.open("rb") as stream:
        source = pickle.load(stream)
    end = int(boundary_step) + 1
    start = end - HISTORY_STEPS
    vehicle_steps = source.get("vehicle_id_per_step") or []
    if start < 0 or end > len(vehicle_steps):
        raise ValueError(
            f"Boundary step {boundary_step} cannot provide {HISTORY_STEPS} history frames"
        )
    initialization = dict(source)
    for key, values in source.items():
        if str(key).endswith("_per_step"):
            initialization[key] = list(values[start:end])
    simulator = dict(initialization.get("simulator_meta_info") or {})
    simulator["trafficwm_realtime_initialization"] = {
        "schema": "trafficwm.xa-wenying-init.v1",
        "history_steps": HISTORY_STEPS,
        "ego_id": AV_ID,
        "source_recording": _relative(recording_path),
        "source_boundary_step": int(boundary_step),
    }
    initialization["simulator_meta_info"] = simulator
    final_ids = list(initialization["vehicle_id_per_step"][-1])
    ego_index = next(index for index, actor_id in enumerate(final_ids) if str(actor_id) == AV_ID)
    ego_state = np.asarray(initialization["vehicle_state_per_step"][-1][ego_index])
    speed_mps = float(np.linalg.norm(ego_state[3:5]))
    report = {
        "schema": "trafficwm.xa-wenying-scenario.v1",
        "map": "cnde_map_xa_wenying",
        "main_start_lane": MAIN_START_LANE,
        "opposite_start_lane": OPPOSITE_START_LANE,
        "vehicle_count": len(final_ids),
        "ego_id": AV_ID,
        "speed_mps": round(speed_mps, 4),
        "history_steps": HISTORY_STEPS,
        "step_seconds": STEP_SECONDS,
        "source_recording": _relative(recording_path),
        "source_boundary_step": int(boundary_step),
        "initial_vehicle_ids": final_ids,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "xa_wenying_sparse.init.pkl"
    with target.open("wb") as stream:
        pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
    report_path = target.with_suffix(target.suffix + ".json")
    report_path.write_text(
        json.dumps({**report, "path": _relative(target)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"path": target, "report": report, "report_path": report_path}


def publish(
    map_path: Path,
    initialization_path: Path,
    seed_image: Path,
    library_dir: Path,
    *,
    seed_source_experiment_id: str,
    profile: str = "sparse",
) -> list[dict[str, Any]]:
    profile_config = PROFILE_ACTOR_POSITIONS[profile]
    with initialization_path.open("rb") as stream:
        initialization = pickle.load(stream)
    if len(initialization.get("vehicle_id_per_step") or []) != HISTORY_STEPS:
        raise ValueError("The seed initialization must contain exactly 11 history states")
    with Image.open(seed_image) as image:
        width, height = image.size
        image.verify()
    if (width, height) != (1280, 704):
        raise ValueError(f"Seed image is {width}x{height}; expected 1280x704")

    recording = shared._terminal_recording(initialization)
    scenario_hash = shared._step_sha256(recording, 0)
    if scenario_hash != shared._step_sha256(initialization, -1):
        raise ValueError("Scenario and initialization boundaries do not match")
    library_dir.mkdir(parents=True, exist_ok=True)
    final_ids = [str(actor_id) for actor_id in initialization["vehicle_id_per_step"][-1]]
    ego_index = final_ids.index(AV_ID)
    initial_speed = float(
        np.linalg.norm(
            np.asarray(
                initialization["vehicle_state_per_step"][-1][ego_index],
                dtype=np.float64,
            )[3:5]
        )
    )
    records = []
    actor_count = len(final_ids)
    for definition in profile_config["definitions"]:
        target = library_dir / f"{definition['stem']}.pkl"
        init_target = library_dir / f"{definition['stem']}.init.pkl"
        image_target = library_dir / f"{definition['stem']}.seed.png"
        with target.open("wb") as stream:
            pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
        shutil.copy2(initialization_path, init_target)
        shutil.copy2(seed_image, image_target)
        metadata = {
            "schema": "denseworld.standard-scenario.v2",
            "library_id": definition["id"],
            "library_name": definition["name"],
            "library_description": definition["description"],
            "library_category": "normal",
            "library_tags": definition["tags"],
            "backend_model": definition["backend_model"],
            "standard_backend_locked": True,
            "traffic_controller": definition["traffic_controller"],
            "map_path": _relative(map_path),
            "init_mode": "data",
            "init_file": _relative(init_target),
            "initialization_seed": 42,
            "total_step": int(round(float(profile_config["max_sim_time"]) / STEP_SECONDS)),
            "sim_resolution": STEP_SECONDS,
            "max_sim_time": float(profile_config["max_sim_time"]),
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
            "participants": {"motorized": actor_count, "pedestrians": 0, "cyclists": 0},
            "peak_participants": {"motorized": actor_count, "pedestrians": 0, "cyclists": 0},
            "source_path": _relative(initialization_path),
            "source_format": "trafficwm.xa-wenying-init.v1",
            "source_start_seconds": 0.0,
            "source_end_seconds": 0.1,
            "native_traffic_fps": 10.0,
            "default_world_prompt": profile_config["default_prompt"],
            "default_transfer_prompt": profile_config["default_transfer_prompt"],
            "world_omnidreams_seed": 1,
            "world_omnidreams_actor_hood_occlusion_distance_m": 25.0,
            "world_omnidreams_actor_hood_occlusion_lateral_m": 3.0,
            "world_omnidreams_actor_oncoming_lateral_exclusion_m": 3.0,
            "world_seed_map_radius_m": 120.0,
            "world_omnidreams_actor_max_count": min(
                int(profile_config["omnidreams_actor_max_count"]), actor_count
            ),
            "world_local_target_count": actor_count,
            "world_initial_vehicle_limit": actor_count,
            "use_existing_seed": True,
            "seed_image": _relative(image_target),
            "seed_init_file": _relative(init_target),
            "seed_source": "cosmos-transfer2.5-seven-view-matched-control",
            "seed_source_experiment_id": str(seed_source_experiment_id),
            "seed_source_time_seconds": 0.0,
            "seed_source_frame": 0,
            "seed_source_fps": 10.0,
            "seed_warmup_seconds": 0.0,
            "seed_scenario_state_step": 0,
            "seed_initialization_state_step": 10,
            "seed_initialization_history_frames": HISTORY_STEPS,
            "seed_alignment": "exact_control_frame_t0",
            "seed_ego_id": AV_ID,
            "seed_width": width,
            "seed_height": height,
            "seed_sha256": hashlib.sha256(image_target.read_bytes()).hexdigest(),
            "seed_init_sha256": hashlib.sha256(init_target.read_bytes()).hexdigest(),
            "seed_state_sha256": scenario_hash,
            "initial_speed_mps": round(initial_speed, 3),
        }
        if definition["backend_model"] == "rulebased":
            metadata["rule_control"] = {
                "bv_controller": "SparseIDMMOBILController",
                "bv_desired_speed_mps": float(profile_config["desired_speed_mps"]),
                "av_controller": "IDMMOBILStreamController",
                "av_desired_speed_mps": float(profile_config["desired_speed_mps"]),
                "initial_speed_mps": round(initial_speed, 3),
            }
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        target.with_suffix(".manifest.json").write_text(
            json.dumps(
                {
                    "schema": "denseworld.normalized-recording.v1",
                    "recording": _relative(target),
                    "source_frames": 2,
                    "source_fps": 10.0,
                    "recording_frames": 2,
                    "duration_seconds": 0.1,
                    "actor_tracks": actor_count,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        records.append({"id": definition["id"], "path": _relative(target)})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        type=Path,
        default=ROOT / "algorithm_sources/CityNDE_src/assets/map/cnde_map_xa_wenying.pkl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output/validation/xa_wenying_standard_scene",
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=ROOT / "output/scenarios/citynde/library",
    )
    parser.add_argument("--speed-mps", type=float, default=4.0)
    parser.add_argument("--profile", choices=sorted(PROFILE_ACTOR_POSITIONS), default="sparse")
    parser.add_argument("--boundary-recording", type=Path)
    parser.add_argument("--boundary-step", type=int, default=20)
    parser.add_argument("--seed-image", type=Path)
    parser.add_argument("--seed-source-experiment-id", default="")
    args = parser.parse_args()

    built = (
        build_initialization_from_recording(
            args.boundary_recording.resolve(),
            args.output_dir.resolve(),
            boundary_step=args.boundary_step,
        )
        if args.boundary_recording
        else build_initialization(
            args.map.resolve(),
            args.output_dir.resolve(),
            args.speed_mps,
            profile=args.profile,
        )
    )
    result: dict[str, Any] = {
        "schema": "trafficwm.xa-wenying-standard-scenes.v1",
        "map_path": _relative(args.map),
        "initialization": _relative(built["path"]),
        "report": built["report"],
        "default_world_prompt": PROFILE_ACTOR_POSITIONS[args.profile]["default_prompt"],
    }
    if args.seed_image:
        result["library"] = publish(
            args.map.resolve(),
            built["path"],
            args.seed_image.resolve(),
            args.library_dir.resolve(),
            seed_source_experiment_id=args.seed_source_experiment_id,
            profile=args.profile,
        )
    manifest = args.output_dir.resolve() / "manifest.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**result, "manifest": _relative(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
