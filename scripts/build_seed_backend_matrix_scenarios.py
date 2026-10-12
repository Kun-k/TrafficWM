#!/usr/bin/env python3
"""Build the three deterministic scenario initializations used by the seed matrix."""

from __future__ import annotations

import argparse
import copy
import json
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.algorithms.citynde.long_horizon import find_reachable_lane_cycle


LIBRARY_ROOT = ROOT / "output/scenarios/citynde/library"
HISTORY_STEPS = 11
STEP_SECONDS = 0.1

CURRENT_SOURCE = LIBRARY_ROOT / "xa_wenying_rule_dense_seeded.init.pkl"
CURRENT_METADATA = LIBRARY_ROOT / "xa_wenying_rule_dense_seeded.pkl.meta.json"
PEDESTRIAN_SOURCE = LIBRARY_ROOT / "pedestrian_low_density.pkl"

SIGNALIZED_MAP = (
    "algorithm_sources/CityNDE_src/assets/map/"
    "routed_map_nuplan_boston_015_small_signalized.pkl"
)
WENYING_MAP = "algorithm_sources/CityNDE_src/assets/map/cnde_map_xa_wenying.pkl"
UNSIGNALIZED_WENYING_MAP = (
    "algorithm_sources/CityNDE_src/assets/map/cnde_map_xa_wenying_unsignalized.pkl"
)

PEDESTRIAN_IDS = (
    "pedestrian-cnde-crosswalk-2-0",
    "pedestrian-cnde-crosswalk-2-1",
)
PEDESTRIAN_CROSSWALK_ID = "cnde-crosswalk-2"

CURRENT_WORLD_PROMPT = (
    "Natural low-contrast documentary footage from an official 120-degree front-wide dashcam "
    "on a straight divided urban boulevard in Xi'an. The road and central vanishing point remain "
    "clearly visible through an open streetscape while dense but orderly passenger traffic moves "
    "forward in the mapped lanes. Dry charcoal-gray asphalt, crisp white dashed lane markings, "
    "concrete curbs, a low median, sparse roadside trees, clipped hedges, slender streetlights, and "
    "restrained pale mid-rise buildings remain sharp and geometrically stable. Avoid close building "
    "facades, dense overhead foliage, harsh highlights, or cinematic color grading. Use soft clear "
    "late-morning daylight, neutral color, realistic vehicle scale, stable road structure, and a "
    "plain hood without text."
)
PEDESTRIAN_WORLD_PROMPT = (
    "Natural low-contrast footage from an official 120-degree front-wide dashcam approaching an open, "
    "signal-controlled Boston urban intersection. The roadway, crosswalk, and central vanishing point "
    "remain clearly visible without close building facades or dense overhead foliage. "
    "Cars remain in their mapped lanes and obey the mast-arm traffic signals. Exactly two adult "
    "pedestrians wait at opposite sides of one clearly painted zebra crossing and walk only during "
    "the protected pedestrian phase. Gray asphalt, white lane markings, curbs, sidewalks, brick and "
    "stone buildings, roadside trees, and signal poles remain sharp, stable, and physically grounded. "
    "Use soft clear daytime light, neutral color, realistic scale, smooth forward camera motion, no "
    "harsh highlights, no cinematic color grading, no text, and no watermark."
)
CYCLIST_WORLD_PROMPT = (
    "Natural low-contrast documentary footage from an official 120-degree front-wide dashcam on an "
    "open, unsignalized urban boulevard in Xi'an that begins straight and follows a gradual right-hand "
    "bend. The roadway and central vanishing point "
    "remain clearly visible without close building facades or dense overhead foliage. The ego car "
    "follows one clearly visible cyclist traveling forward at a steady urban cycling speed along the "
    "rightmost lane, with two orderly passenger cars and no traffic lights. Dry charcoal-gray asphalt, "
    "crisp white lane markings, concrete curbs, a low median, sparse roadside trees, clipped hedges, "
    "slender streetlights, and restrained pale mid-rise buildings remain sharp and geometrically "
    "stable. Use soft clear daytime light, neutral color, realistic actor scale, smooth forward "
    "motion, no harsh highlights, no cinematic color grading, a plain hood, no text, and no watermark."
)


def _load_pickle(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        value = pickle.load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"{path} does not contain a scenario dictionary")
    return value


def _write_pickle(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _history(source: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    if end - start != HISTORY_STEPS:
        raise ValueError(f"Expected {HISTORY_STEPS} history frames")
    result = copy.deepcopy(source)
    for key, value in list(source.items()):
        if str(key).endswith("_per_step"):
            result[key] = copy.deepcopy(list(value[start:end]))
    result.pop("map", None)
    result.pop("routes", None)
    return result


def _metadata(
    *,
    library_id: str,
    name: str,
    description: str,
    category: str,
    backend_model: str,
    map_path: str,
    init_path: Path,
    source_path: str,
    ego_id: str,
    participants: dict[str, int],
    prompt: str,
    mixed_enabled: bool,
    cyclist_ratio: float = 0.0,
    pedestrians_per_crosswalk: int = 0,
    max_pedestrians: int = 0,
    seed_alignment_mode: str = "terminal_continue",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    relative_init = init_path.relative_to(ROOT).as_posix()
    transfer_prompt = (
        f"{prompt} Render a clean, photorealistic first-frame seed aligned exactly to every "
        "lane, road user, crosswalk, curb, and traffic control shown by the HD-map control."
    )
    return {
        "schema": "denseworld.standard-scenario.v2",
        "library_id": library_id,
        "library_name": name,
        "library_description": description,
        "library_category": category,
        "library_tags": tags or [],
        "backend_model": backend_model,
        "standard_backend_locked": True,
        "traffic_controller": "idm_mobil" if backend_model == "rulebased" else "cnde",
        "map_path": map_path,
        "init_mode": "data",
        "init_file": relative_init,
        "initialization_seed": 42,
        "total_step": 600,
        "sim_resolution": STEP_SECONDS,
        "max_sim_time": 60.0,
        "recording_operational_start_step": 0,
        "arrival_rate": 0.0,
        "lane_arrival_rates": {},
        "mixed_traffic_enabled": mixed_enabled,
        "cyclist_ratio": cyclist_ratio,
        "pedestrians_per_crosswalk": pedestrians_per_crosswalk,
        "max_pedestrians": max_pedestrians,
        "vehicle_size_mode": "mixed" if mixed_enabled else "passenger_only",
        "initial_speed_mode": "fixed",
        "signalize_unsignalized_map": False,
        "world_loop_ego": False,
        "participants": participants,
        "peak_participants": participants,
        "source_path": source_path,
        "source_format": "trafficwm.seed-backend-matrix-init.v1",
        "source_start_seconds": 0.0,
        "source_end_seconds": 1.0,
        "native_traffic_fps": 10.0,
        "default_world_prompt": prompt,
        "default_transfer_prompt": transfer_prompt,
        "world_transfer_seed": 1,
        "world_seed_alignment_mode": seed_alignment_mode,
        "world_omnidreams_seed": 1,
        "world_omnidreams_actor_hood_occlusion_distance_m": 25.0,
        "world_omnidreams_actor_hood_occlusion_lateral_m": 3.0,
        "world_omnidreams_actor_oncoming_lateral_exclusion_m": 3.0,
        "world_seed_map_radius_m": 100.0,
        "world_omnidreams_actor_max_count": max(4, sum(participants.values())),
        "world_local_target_count": max(2, participants.get("motorized", 0)),
        "world_initial_vehicle_limit": max(2, sum(participants.values())),
        "use_existing_seed": False,
        "seed_image": "",
        "seed_ego_id": ego_id,
    }


def _publish(stem: str, recording: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    scenario_path = LIBRARY_ROOT / f"{stem}.pkl"
    init_path = LIBRARY_ROOT / f"{stem}.init.pkl"
    _write_pickle(scenario_path, recording)
    _write_pickle(init_path, recording)
    _write_json(scenario_path.with_suffix(".pkl.meta.json"), metadata)
    return {
        "library_id": metadata["library_id"],
        "scenario": scenario_path.relative_to(ROOT).as_posix(),
        "initialization": init_path.relative_to(ROOT).as_posix(),
        "participants": metadata["participants"],
        "backend_model": metadata["backend_model"],
        "map_path": metadata["map_path"],
    }


def build_current() -> dict[str, Any]:
    source = _load_pickle(CURRENT_SOURCE)
    source_metadata = json.loads(CURRENT_METADATA.read_text(encoding="utf-8"))
    stem = "matrix_current_xa_wenying"
    init_path = LIBRARY_ROOT / f"{stem}.init.pkl"
    metadata = _metadata(
        library_id="matrix-current-xa-wenying",
        name="矩阵基准：当前文瀛密集直路",
        description="沿用当前文瀛规则交通流初始化，20 辆固定车辆，无行人与非机动车。",
        category="normal",
        backend_model="rulebased",
        map_path=WENYING_MAP,
        init_path=init_path,
        source_path=CURRENT_SOURCE.relative_to(ROOT).as_posix(),
        # Keep the camera bound to the AV present in the recorded opening.
        # At 2.5 m/s its straight route remains valid for the full 60 s run.
        ego_id="AV",
        participants={"motorized": 20, "pedestrians": 0, "cyclists": 0},
        prompt=CURRENT_WORLD_PROMPT,
        mixed_enabled=False,
        tags=["matrix", "current", "XiAn", "straight-road", "dense"],
    )
    metadata["rule_control"] = copy.deepcopy(source_metadata.get("rule_control") or {})
    metadata["rule_control"].update(
        {
            "bv_desired_speed_mps": 2.5,
            "av_desired_speed_mps": 2.5,
            "initial_speed_mps": 2.5,
        }
    )
    metadata["world_omnidreams_actor_max_count"] = int(
        source_metadata.get("world_omnidreams_actor_max_count") or 12
    )
    metadata["world_loop_ego"] = False
    return _publish(stem, source, metadata)


def build_pedestrian() -> dict[str, Any]:
    source = _load_pickle(PEDESTRIAN_SOURCE)
    recording = _history(source, 10, 21)
    source_ids = [str(value) for value in source["pedestrian_id_per_step"][20]]
    source_states = np.asarray(source["pedestrian_state_per_step"][20], dtype=np.float64)
    selected_states = np.stack(
        [source_states[source_ids.index(pedestrian_id), :7] for pedestrian_id in PEDESTRIAN_IDS]
    )
    recording["pedestrian_id_per_step"] = [list(PEDESTRIAN_IDS) for _ in range(HISTORY_STEPS)]
    recording["pedestrian_state_per_step"] = [selected_states.copy() for _ in range(HISTORY_STEPS)]
    recording["pedestrian_static_attribute"] = {
        pedestrian_id: copy.deepcopy(source["pedestrian_static_attribute"][pedestrian_id])
        for pedestrian_id in PEDESTRIAN_IDS
    }
    recording["pedestrian_crosswalk"] = {
        pedestrian_id: str(source["pedestrian_crosswalk"][pedestrian_id])
        for pedestrian_id in PEDESTRIAN_IDS
    }
    mixed = copy.deepcopy(source.get("mixed_traffic") or {})
    mixed.update(
        {
            "enabled": True,
            "cyclist_ratio": 0.0,
            "pedestrians_per_crosswalk": 2,
            "max_pedestrians": 2,
        }
    )
    recording["mixed_traffic"] = mixed
    simulator = copy.deepcopy(recording.get("simulator_meta_info") or {})
    simulator["trafficwm_matrix_initialization"] = {
        "schema": "trafficwm.seed-backend-matrix-init.v1",
        "source_frame": 20,
        "pedestrian_ids": list(PEDESTRIAN_IDS),
        "crosswalk_id": PEDESTRIAN_CROSSWALK_ID,
    }
    recording["simulator_meta_info"] = simulator

    stem = "matrix_signalized_two_pedestrians"
    init_path = LIBRARY_ROOT / f"{stem}.init.pkl"
    metadata = _metadata(
        library_id="matrix-signalized-two-pedestrians",
        name="矩阵场景：信号路口双行人",
        description="Boston 信号路口，8 辆机动车与同一斑马线两侧的 2 名规则行人。",
        category="pedestrian",
        backend_model="cnde",
        map_path=SIGNALIZED_MAP,
        init_path=init_path,
        source_path=PEDESTRIAN_SOURCE.relative_to(ROOT).as_posix(),
        # Actor 9 reaches crosswalk 2 during its short signal stop, then keeps
        # following a continuous route with substantially less stationary time.
        ego_id="9",
        participants={"motorized": 8, "pedestrians": 2, "cyclists": 0},
        prompt=PEDESTRIAN_WORLD_PROMPT,
        mixed_enabled=True,
        pedestrians_per_crosswalk=2,
        max_pedestrians=2,
        seed_alignment_mode="opening_restart",
        tags=["matrix", "Boston", "signalized", "crosswalk", "two-pedestrians"],
    )
    # This Boston crop has no directed lane cycle. Keep the camera vehicle on
    # its native CityNDE route long enough for the 60 s matrix run.
    metadata["world_ego_speed_cap_mps"] = 2.5
    return _publish(stem, recording, metadata)


def _build_unsignalized_wenying_map() -> Path:
    source_path = ROOT / WENYING_MAP
    target_path = ROOT / UNSIGNALIZED_WENYING_MAP
    map_data = _load_pickle(source_path)
    polylines = map_data.get("polyline") or {}
    converted = 0
    for polyline in polylines.values():
        if isinstance(polyline, dict) and int(polyline.get("type", -1)) == 4:
            polyline["type"] = 0
            converted += 1
    if converted <= 0:
        raise ValueError("Wenying source map has no signalized intersection lanes to convert")
    _write_pickle(target_path, map_data)
    return target_path


def build_cyclist() -> dict[str, Any]:
    source = _load_pickle(CURRENT_SOURCE)
    unsignalized_map_path = _build_unsignalized_wenying_map()
    unsignalized_map = _load_pickle(unsignalized_map_path)
    source_history = _history(source, 0, HISTORY_STEPS)
    route_start_lane = "1615"
    polylines = unsignalized_map["polyline"]
    route_prefix, route_cycle = find_reachable_lane_cycle(
        SimpleNamespace(polyline_dict=polylines),
        route_start_lane,
    )
    route = [*route_prefix, *route_cycle]
    if not route_cycle:
        raise ValueError(f"Wenying lane {route_start_lane} has no reachable cycle")
    route_states = np.concatenate(
        [np.asarray(polylines[lane_id]["states"], dtype=np.float64) for lane_id in route],
        axis=0,
    )
    route_points = route_states[:, :2]
    route_lengths = np.linalg.norm(np.diff(route_points, axis=0), axis=1)
    route_progress = np.concatenate([[0.0], np.cumsum(route_lengths)])

    def sample_route(distance_m: float) -> tuple[np.ndarray, float]:
        distance = float(np.clip(distance_m, 0.0, route_progress[-1]))
        segment = min(
            len(route_lengths) - 1,
            max(0, int(np.searchsorted(route_progress, distance, side="right") - 1)),
        )
        segment_length = max(1e-9, float(route_lengths[segment]))
        fraction = (distance - float(route_progress[segment])) / segment_length
        position = route_points[segment] * (1.0 - fraction) + route_points[segment + 1] * fraction
        direction = route_points[segment + 1] - route_points[segment]
        return position, float(np.arctan2(direction[1], direction[0]))

    actor_offsets = {
        "AV": 0.0,
        "cyclist-0": 28.0,
        0: 55.0,
    }
    actor_speeds = {
        "AV": 6.0,
        "cyclist-0": 6.0,
        0: 6.0,
    }
    actor_ids = list(actor_offsets)
    actor_histories: dict[str, np.ndarray] = {}
    for actor_id, offset_m in actor_offsets.items():
        states = []
        for step in range(HISTORY_STEPS):
            speed = actor_speeds[actor_id]
            position, heading = sample_route(offset_m + step * STEP_SECONDS * speed)
            direction = np.asarray([np.cos(heading), np.sin(heading)])
            state = np.asarray(
                [position[0], position[1], heading, *(speed * direction), 0.0, 0.0],
                dtype=np.float64,
            )
            states.append(state)
        actor_histories[actor_id] = np.stack(states)
    recording = {
        "simulator_meta_info": copy.deepcopy(source_history.get("simulator_meta_info") or {}),
        "vehicle_id_per_step": [list(actor_ids) for _ in range(HISTORY_STEPS)],
        "vehicle_state_per_step": [
            np.stack([actor_histories[actor_id][step] for actor_id in actor_ids])
            for step in range(HISTORY_STEPS)
        ],
        "dynamic_polyline_id_per_step": [[] for _ in range(HISTORY_STEPS)],
        "dynamic_polyline_state_per_step": [
            np.empty((0, 4), dtype=np.float64) for _ in range(HISTORY_STEPS)
        ],
        "vehicle_static_attribute": {
            "AV": np.asarray([4.65, 1.84, 1.48], dtype=np.float64),
            "cyclist-0": np.asarray([1.85, 0.65, 1.55], dtype=np.float64),
            0: np.asarray([4.75, 1.86, 1.52], dtype=np.float64),
        },
        "road_user_type": {
            "AV": "vehicle",
            "cyclist-0": "cyclist",
            0: "vehicle",
        },
        "vehicle_class": {
            "AV": "sedan",
            "cyclist-0": "non_motorized",
            0: "suv",
        },
        "vehicle_type": {
            actor_id: (
                "backend.algorithms.citynde.mixed_traffic.RoutedNonMotorizedVehicle"
                if actor_id == "cyclist-0"
                else "csim.agent.agent.RoutedVehicle"
            )
            for actor_id in actor_ids
        },
        "pedestrian_id_per_step": [[] for _ in range(HISTORY_STEPS)],
        "pedestrian_state_per_step": [
            np.empty((0, 7), dtype=np.float64) for _ in range(HISTORY_STEPS)
        ],
        "pedestrian_static_attribute": {},
        "pedestrian_crosswalk": {},
        "mixed_traffic": {
            "schema": "trafficwm.mixed-traffic.v1",
            "enabled": True,
            "cyclist_ratio": 0.25,
            "pedestrians_per_crosswalk": 0,
            "max_pedestrians": 0,
            "vehicle_size_mode": "mixed",
        },
    }
    recording["simulator_meta_info"]["trafficwm_matrix_initialization"] = {
        "schema": "trafficwm.seed-backend-matrix-init.v1",
        "source_frames": [0, 10],
        "unsignalized": True,
        "ego_following_distance_m": 28.0,
        "cyclist_id": "cyclist-0",
        "route_start_lane": route_start_lane,
        "route_prefix_lane_count": len(route_prefix),
        "route_cycle_lane_count": len(route_cycle),
        "route_available_distance_m": round(float(route_progress[-1]), 3),
        "actor_route_offsets_m": actor_offsets,
        "source_map": WENYING_MAP,
        "converted_map": UNSIGNALIZED_WENYING_MAP,
        "converted_intersection_lane_type": {"from": 4, "to": 0},
    }

    stem = "matrix_unsignalized_cyclist"
    init_path = LIBRARY_ROOT / f"{stem}.init.pkl"
    metadata = _metadata(
        library_id="matrix-unsignalized-cyclist",
        name="矩阵场景：无信号路口非机动车",
        description="文瀛无信号道路，主车前方最右侧车道有 1 辆稳速非机动车。",
        category="cyclist",
        backend_model="rulebased",
        map_path=UNSIGNALIZED_WENYING_MAP,
        init_path=init_path,
        source_path=CURRENT_SOURCE.relative_to(ROOT).as_posix(),
        ego_id="AV",
        participants={"motorized": 2, "pedestrians": 0, "cyclists": 1},
        prompt=CYCLIST_WORLD_PROMPT,
        mixed_enabled=True,
        cyclist_ratio=0.25,
        seed_alignment_mode="opening_restart",
        tags=["matrix", "XiAn", "Wenying", "unsignalized", "rightmost", "cyclist"],
    )
    metadata["world_loop_ego"] = True
    metadata["rule_control"] = {
        "bv_controller": "SparseIDMMOBILController",
        "bv_desired_speed_mps": 6.0,
        "av_controller": "IDMMOBILStreamController",
        "av_desired_speed_mps": 6.0,
        "initial_speed_mps": 6.0,
    }
    return _publish(stem, recording, metadata)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output/validation/seed_backend_matrix_20260826/scenarios.json",
    )
    args = parser.parse_args()
    records = [build_current(), build_pedestrian(), build_cyclist()]
    report = {
        "schema": "trafficwm.seed-backend-matrix-scenarios.v1",
        "history_steps": HISTORY_STEPS,
        "step_seconds": STEP_SECONDS,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
