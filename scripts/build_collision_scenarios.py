#!/usr/bin/env python3
"""Build deterministic cut-in and rear-end collision replay scenarios."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pickle
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.algorithms.citynde.mixed_traffic_core import oriented_boxes_overlap  # noqa: E402
from scripts import build_tianjin_realtime_scenarios as shared  # noqa: E402


STEP_SECONDS = 0.1
DURATION_SECONDS = 12.0
FRAME_COUNT = int(round(DURATION_SECONDS / STEP_SECONDS)) + 1
AV_ID = "AV"
FOLLOWER_ID = "BV-main-1"
LEADER_ID = "BV-main-2"
MAIN_START_LANE = "1547"
ADJACENT_START_LANE = "1559"
OPPOSITE_START_LANE = "1591"
SOURCE_STEM = "xa_wenying_rule_seeded"

COMMON_PROMPT = (
    "Official 120-degree f-theta forward dashcam footage on a perfectly straight divided "
    "urban boulevard in Xi'an under clear neutral daylight. Preserve the supplied camera "
    "calibration, straight lane geometry, crisp white markings, dry charcoal-gray asphalt, "
    "low median, plane trees, hedges, streetlights, restrained pale mid-rise buildings, "
    "vehicle identity, scale, and mapped motion in every frame. Passenger cars remain sharply "
    "resolved with coherent body panels, windows, lamps, wheels, and natural reflections. "
    "The collision is a physically plausible low-speed traffic contact without fire, smoke, "
    "explosion, debris, injury, camera cut, or dramatic cinematic effects. Only a narrow stable "
    "strip of the plain ego hood is visible along the bottom edge. "
)

TRANSFER_PROMPT = (
    "A photorealistic 120-degree f-theta forward dashcam view from a passenger car on a "
    "perfectly straight divided urban boulevard in Xi'an. Preserve the supplied HD-map "
    "geometry and every mapped vehicle position exactly. Render all nearby sedans with crisp "
    "body contours, windows, lamps, tires, and realistic scale. The road has dry dark-gray "
    "asphalt, sharp white dashed lane markings, concrete curbs, a low median, plane trees, "
    "trimmed hedges, slender streetlights, and pale mid-rise buildings in clear neutral "
    "daylight. The ego camera moves smoothly forward; no logo, watermark, text, blur, warped "
    "road, duplicate vehicle, floating vehicle, or vehicle outside a lane."
)

DEFINITIONS = {
    "cutin": {
        "id": "xa-wenying-scripted-cutin-collision",
        "name": "事故场景-车辆切入并碰撞主车-Transfer1",
        "description": (
            "西安文瀛直路固定交通初态，前车进入左侧相邻车道后强制回切，与主车前侧发生碰撞。"
        ),
        "stem": "xa_wenying_scripted_cutin_collision",
        "tags": ["XiAn", "Wenying", "collision", "cut-in", "AV", "transfer1", "replay"],
        "expected_window_seconds": [4.8, 6.2],
        "prompt": COMMON_PROMPT
        + (
            "A clearly visible sedan ahead first moves into the adjacent left lane, then makes "
            "a decisive rightward cut-in across the ego path and makes brief low-speed contact "
            "with the front corner of the ego car. Keep that sedan ahead of the camera before, "
            "during, and after contact. The ego camera brakes without rolling, tilting, or "
            "leaving its lane."
        ),
    },
    "rearend": {
        "id": "xa-wenying-scripted-rearend-collision",
        "name": "事故场景-主车追尾急停前车-Transfer1",
        "description": "西安文瀛直路固定交通初态，主车前方车辆急停，主车继续前进并发生追尾碰撞。",
        "stem": "xa_wenying_scripted_rearend_collision",
        "tags": ["XiAn", "Wenying", "collision", "rear-end", "AV", "transfer1", "replay"],
        "expected_window_seconds": [4.0, 5.2],
        "prompt": COMMON_PROMPT
        + (
            "A clearly visible sedan directly ahead brakes firmly to a stop in its lane. The "
            "ego car continues forward and makes brief low-speed front-to-rear contact with its "
            "rear bumper. Keep the stopped sedan centered ahead of the camera and preserve the "
            "straight road and stable camera through the contact."
        ),
    },
}


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, float(value)))
    return value * value * (3.0 - 2.0 * value)


def _ramp(t: float, start: float, end: float, first: float, second: float) -> float:
    if t <= start:
        return first
    if t >= end:
        return second
    return first + (second - first) * _smoothstep((t - start) / (end - start))


def _project_path(path: np.ndarray, distance: np.ndarray, point: np.ndarray) -> tuple[float, float]:
    starts = path[:-1, :2]
    vectors = path[1:, :2] - starts
    lengths_squared = np.sum(vectors * vectors, axis=1)
    fractions = np.clip(
        np.sum((point[:2] - starts) * vectors, axis=1) / np.maximum(lengths_squared, 1e-12),
        0.0,
        1.0,
    )
    projections = starts + fractions[:, None] * vectors
    errors = np.sum((projections - point[:2]) ** 2, axis=1)
    index = int(np.argmin(errors))
    segment_length = math.sqrt(float(lengths_squared[index]))
    longitudinal = float(distance[index] + fractions[index] * segment_length)
    pose = shared._sample_path(path, distance, longitudinal)
    dx = float(point[0] - pose[0])
    dy = float(point[1] - pose[1])
    lateral = -math.sin(float(pose[2])) * dx + math.cos(float(pose[2])) * dy
    return longitudinal, lateral


def _path_position(
    path: np.ndarray,
    distance: np.ndarray,
    longitudinal: float,
    lateral: float,
) -> np.ndarray:
    pose = shared._sample_path(path, distance, longitudinal)
    return np.asarray(
        [
            float(pose[0]) - math.sin(float(pose[2])) * lateral,
            float(pose[1]) + math.cos(float(pose[2])) * lateral,
        ],
        dtype=np.float64,
    )


def _integrate_speed(initial_s: float, times: np.ndarray, speed_fn: Callable[[float], float]) -> np.ndarray:
    values = np.empty(len(times), dtype=np.float64)
    values[0] = float(initial_s)
    previous_speed = float(speed_fn(float(times[0])))
    for index in range(1, len(times)):
        speed = float(speed_fn(float(times[index])))
        values[index] = values[index - 1] + 0.5 * (previous_speed + speed) * STEP_SECONDS
        previous_speed = speed
    return values


def _kinematic_states(
    positions: np.ndarray,
    *,
    initial_state: np.ndarray,
    freeze_from: int | None = None,
) -> np.ndarray:
    positions = np.asarray(positions, dtype=np.float64).copy()
    if freeze_from is not None:
        positions[freeze_from:] = positions[freeze_from]
    velocity = np.zeros_like(positions)
    velocity[1:] = np.diff(positions, axis=0) / STEP_SECONDS
    velocity[0] = np.asarray(initial_state[3:5], dtype=np.float64)
    if freeze_from is not None and freeze_from + 1 < len(velocity):
        velocity[freeze_from + 1 :] = 0.0
    heading = np.empty(len(positions), dtype=np.float64)
    heading[0] = float(initial_state[2])
    for index in range(1, len(positions)):
        speed = float(np.linalg.norm(velocity[index]))
        heading[index] = (
            math.atan2(float(velocity[index, 1]), float(velocity[index, 0]))
            if speed > 1e-6
            else heading[index - 1]
        )
    acceleration = np.zeros_like(velocity)
    acceleration[1:] = np.diff(velocity, axis=0) / STEP_SECONDS
    states = np.concatenate(
        [positions, heading[:, None], velocity, acceleration], axis=1
    ).astype(np.float64)
    states[0] = np.asarray(initial_state, dtype=np.float64)
    return states


def _collision_pairs(
    states_by_id: dict[str, np.ndarray],
    sizes: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    actor_ids = sorted(states_by_id)
    events: list[dict[str, Any]] = []
    for step in range(FRAME_COUNT):
        pairs = []
        for first_index, first_id in enumerate(actor_ids):
            for second_id in actor_ids[first_index + 1 :]:
                if oriented_boxes_overlap(
                    states_by_id[first_id][step, :3],
                    sizes[first_id][:2],
                    states_by_id[second_id][step, :3],
                    sizes[second_id][:2],
                ):
                    pairs.append([first_id, second_id])
        if pairs:
            events.append(
                {
                    "step": step,
                    "time_seconds": round(step * STEP_SECONDS, 3),
                    "pairs": pairs,
                }
            )
    return events


def _load_paths(map_path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    with map_path.open("rb") as stream:
        source = pickle.load(stream)
    polylines = source.get("polyline") if isinstance(source, dict) else None
    if not isinstance(polylines, dict):
        polylines = ((source or {}).get("map") or {}).get("polyline")
    if not isinstance(polylines, dict):
        raise ValueError(f"Unsupported map bundle: {map_path}")
    return {
        "main": shared._chain_path(polylines, shared._lane_chain(polylines, MAIN_START_LANE)),
        "adjacent": shared._chain_path(
            polylines, shared._lane_chain(polylines, ADJACENT_START_LANE)
        ),
        "opposite": shared._chain_path(
            polylines, shared._lane_chain(polylines, OPPOSITE_START_LANE)
        ),
    }


def _build_trajectory(
    kind: str,
    source_recording: dict[str, Any],
    paths: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    first_ids = [str(actor_id) for actor_id in source_recording["vehicle_id_per_step"][0]]
    first_states = np.asarray(source_recording["vehicle_state_per_step"][0], dtype=np.float64)
    initial = {actor_id: first_states[index].copy() for index, actor_id in enumerate(first_ids)}
    sizes = {
        actor_id: np.asarray(
            source_recording["vehicle_static_attribute"].get(actor_id, [4.65, 1.84, 1.48]),
            dtype=np.float64,
        )
        for actor_id in first_ids
    }
    times = np.arange(FRAME_COUNT, dtype=np.float64) * STEP_SECONDS
    main_path, main_distance = paths["main"]
    adjacent_path, adjacent_distance = paths["adjacent"]
    opposite_path, opposite_distance = paths["opposite"]

    projection: dict[str, tuple[str, float, float]] = {}
    for actor_id in first_ids:
        lane = "opposite" if actor_id.startswith("BV-opposite") else "main"
        path, distance = paths[lane]
        longitudinal, lateral = _project_path(path, distance, initial[actor_id][:2])
        projection[actor_id] = (lane, longitudinal, lateral)

    initial_av_speed = float(np.linalg.norm(initial[AV_ID][3:5]))
    initial_follower_speed = float(np.linalg.norm(initial[FOLLOWER_ID][3:5]))
    initial_leader_speed = float(np.linalg.norm(initial[LEADER_ID][3:5]))
    planned_collision_step = int(round((5.6 if kind == "cutin" else 4.6) / STEP_SECONDS))

    av_initial_s = projection[AV_ID][1]
    target_initial_s = projection[FOLLOWER_ID][1]
    if kind == "cutin":
        av_speed = lambda t: _ramp(t, 0.0, 1.2, initial_av_speed, 9.2)
        target_speed = lambda t: _ramp(t, 0.0, 1.0, initial_follower_speed, 5.2)
        approach_start_step = int(round(2.8 / STEP_SECONDS))
        impact_gap_m = 4.35
        impact_lane_weight = 0.32
    else:
        av_speed = lambda t: _ramp(t, 0.0, 1.2, initial_av_speed, 8.0)
        target_speed = lambda t: (
            initial_follower_speed
            if t <= 0.6
            else _ramp(t, 0.6, 1.9, initial_follower_speed, 0.0)
        )
        approach_start_step = int(round(2.0 / STEP_SECONDS))
        impact_gap_m = 4.55
        impact_lane_weight = 0.0

    av_longitudinal = _integrate_speed(av_initial_s, times, av_speed)
    target_longitudinal = _integrate_speed(target_initial_s, times, target_speed)
    approach_start_gap = float(
        target_longitudinal[approach_start_step] - av_longitudinal[approach_start_step]
    )
    for step in range(approach_start_step, planned_collision_step + 1):
        weight = _smoothstep(
            (step - approach_start_step)
            / max(1, planned_collision_step - approach_start_step)
        )
        gap = approach_start_gap + (impact_gap_m - approach_start_gap) * weight
        target_longitudinal[step] = av_longitudinal[step] + gap
    target_longitudinal[planned_collision_step + 1 :] = target_longitudinal[
        planned_collision_step
    ]
    av_longitudinal[planned_collision_step + 1 :] = av_longitudinal[planned_collision_step]

    def lane_weight(t: float) -> float:
        if kind != "cutin":
            return 0.0
        if t <= 0.5:
            return 0.0
        if t < 1.7:
            return _smoothstep((t - 0.5) / 1.2)
        if t <= 3.0:
            return 1.0
        if t <= planned_collision_step * STEP_SECONDS:
            progress = (t - 3.0) / (planned_collision_step * STEP_SECONDS - 3.0)
            return 1.0 + (impact_lane_weight - 1.0) * _smoothstep(progress)
        if t < 6.4:
            progress = (t - planned_collision_step * STEP_SECONDS) / (
                6.4 - planned_collision_step * STEP_SECONDS
            )
            return impact_lane_weight * (1.0 - _smoothstep(progress))
        return 0.0

    positions_by_id: dict[str, np.ndarray] = {}
    for actor_id in first_ids:
        lane, initial_s, lateral = projection[actor_id]
        if actor_id == AV_ID:
            longitudinal = av_longitudinal.copy()
        elif actor_id == FOLLOWER_ID:
            longitudinal = target_longitudinal.copy()
        else:
            constant_speed = max(4.0, float(np.linalg.norm(initial[actor_id][3:5])))
            longitudinal = initial_s + constant_speed * times

        if actor_id == FOLLOWER_ID and kind == "cutin":
            adjacent_s, _ = _project_path(adjacent_path, adjacent_distance, initial[actor_id][:2])
            adjacent_longitudinal = adjacent_s + (longitudinal - initial_s)
            main_positions = np.stack(
                [_path_position(main_path, main_distance, value, lateral) for value in longitudinal]
            )
            adjacent_positions = np.stack(
                [
                    _path_position(adjacent_path, adjacent_distance, value, lateral)
                    for value in adjacent_longitudinal
                ]
            )
            weights = np.asarray([lane_weight(float(t)) for t in times])[:, None]
            positions = main_positions * (1.0 - weights) + adjacent_positions * weights
        else:
            path, distance = (
                (opposite_path, opposite_distance)
                if lane == "opposite"
                else (main_path, main_distance)
            )
            positions = np.stack(
                [_path_position(path, distance, value, lateral) for value in longitudinal]
            )
        positions[0] = initial[actor_id][:2]
        positions_by_id[actor_id] = positions

    preliminary = {
        actor_id: _kinematic_states(positions, initial_state=initial[actor_id])
        for actor_id, positions in positions_by_id.items()
    }
    preliminary_events = _collision_pairs(preliminary, sizes)
    intended_pair = sorted([AV_ID, FOLLOWER_ID])
    collision_follower_id = FOLLOWER_ID if kind == "cutin" else AV_ID
    collision_leader_id = AV_ID if kind == "cutin" else FOLLOWER_ID
    first_intended = next(
        (
            event
            for event in preliminary_events
            if intended_pair in [sorted(pair) for pair in event["pairs"]]
        ),
        None,
    )
    if first_intended is None:
        raise ValueError(f"{kind} trajectory did not produce the intended AV collision")
    collision_step = int(first_intended["step"])
    collision_positions = {
        actor_id: np.asarray(positions, dtype=np.float64).copy()
        for actor_id, positions in positions_by_id.items()
    }
    target_heading = float(preliminary[FOLLOWER_ID][collision_step, 2])
    target_forward = np.asarray(
        [math.cos(target_heading), math.sin(target_heading)], dtype=np.float64
    )
    post_impact_roll_m = 8.0 if kind == "cutin" else 4.0
    for step in range(collision_step, FRAME_COUNT):
        settle = _smoothstep((step - collision_step) * STEP_SECONDS / 1.8)
        collision_positions[AV_ID][step] = (
            positions_by_id[AV_ID][collision_step] + target_forward * (0.08 * settle)
        )
        collision_positions[FOLLOWER_ID][step] = (
            positions_by_id[FOLLOWER_ID][collision_step]
            + target_forward * (post_impact_roll_m * settle)
        )
    states_by_id = {
        actor_id: _kinematic_states(positions, initial_state=initial[actor_id])
        for actor_id, positions in collision_positions.items()
    }

    events = _collision_pairs(states_by_id, sizes)
    first_event = events[0] if events else None
    unexpected_pairs = sorted(
        {
            tuple(sorted(pair))
            for event in events
            for pair in event["pairs"]
            if sorted(pair) != intended_pair
        }
    )
    if first_event is None or intended_pair not in [sorted(pair) for pair in first_event["pairs"]]:
        raise ValueError(f"{kind} first collision is not the intended AV contact")
    if unexpected_pairs:
        raise ValueError(f"{kind} contains unexpected collision pairs: {unexpected_pairs}")
    expected_start, expected_end = DEFINITIONS[kind]["expected_window_seconds"]
    collision_time = float(first_event["time_seconds"])
    if not expected_start <= collision_time <= expected_end:
        raise ValueError(
            f"{kind} collision at {collision_time:.1f}s is outside "
            f"{expected_start:.1f}-{expected_end:.1f}s"
        )

    impact_target = states_by_id[FOLLOWER_ID][collision_step, :2]
    impact_ego = states_by_id[AV_ID][collision_step, :2]
    impact_pair_distance = float(np.linalg.norm(impact_target - impact_ego))
    intended_collision_events = [
        event
        for event in events
        if intended_pair in [sorted(pair) for pair in event["pairs"]]
    ]
    if len(intended_collision_events) > 8:
        raise ValueError(
            f"{kind} AV contact persists too long: {len(intended_collision_events)} frames"
        )

    if kind == "cutin":
        target_positions = states_by_id[FOLLOWER_ID][:, :2]
        maximum_lateral_shift = float(
            np.max(np.linalg.norm(target_positions - target_positions[0], axis=1))
        )
        adjacent_shift = float(
            np.linalg.norm(target_positions[int(round(3.0 / STEP_SECONDS))] - positions_by_id[FOLLOWER_ID][0])
        )
        # Longitudinal motion dominates the raw displacement; compare the two
        # lane center positions directly at the adjacent-lane hold interval.
        main_reference = _path_position(
            main_path,
            main_distance,
            target_longitudinal[int(round(2.5 / STEP_SECONDS))],
            projection[FOLLOWER_ID][2],
        )
        lane_shift = float(
            np.linalg.norm(target_positions[int(round(2.5 / STEP_SECONDS))] - main_reference)
        )
        if lane_shift < 2.5:
            raise ValueError(f"cut-in lateral lane shift is too small: {lane_shift:.3f} m")
    else:
        maximum_lateral_shift = 0.0
        adjacent_shift = 0.0
        lane_shift = 0.0
        target_stop_step = next(
            index
            for index, state in enumerate(states_by_id[FOLLOWER_ID])
            if index > 0 and float(np.linalg.norm(state[3:5])) < 0.05
        )
        if target_stop_step >= collision_step:
            raise ValueError("rear-end target did not stop before impact")

    recording = copy.deepcopy(source_recording)
    recording["vehicle_id_per_step"] = [list(first_ids) for _ in range(FRAME_COUNT)]
    recording["vehicle_state_per_step"] = [
        np.stack([states_by_id[actor_id][step] for actor_id in first_ids]).astype(np.float64)
        for step in range(FRAME_COUNT)
    ]
    for key in (
        "dynamic_polyline_id_per_step",
        "dynamic_polyline_state_per_step",
        "pedestrian_id_per_step",
        "pedestrian_state_per_step",
    ):
        values = source_recording.get(key) or []
        terminal = copy.deepcopy(values[0]) if values else []
        recording[key] = [copy.deepcopy(terminal) for _ in range(FRAME_COUNT)]
    # Preserve the exact loaded frame-zero objects as one bundle. The standard
    # scenario fingerprint intentionally includes NumPy dtype/object memoization,
    # so numerically equal reconstructed arrays are not sufficient here.
    for key, values in source_recording.items():
        if str(key).endswith("_per_step") and len(values):
            recording[key][0] = values[0]
    simulator = dict(recording.get("simulator_meta_info") or {})
    simulator["resolution"] = STEP_SECONDS
    simulator["trafficwm_collision_scenario"] = {
        "schema": "trafficwm.scripted-collision.v1",
        "type": kind,
        "ego_id": AV_ID,
        "follower_id": collision_follower_id,
        "leader_id": collision_leader_id,
        "background_actor_id": LEADER_ID,
        "collision_pair": intended_pair,
        "collision_step": collision_step,
        "collision_time_seconds": collision_time,
    }
    recording["simulator_meta_info"] = simulator

    report = {
        "schema": "trafficwm.collision-scenario-validation.v1",
        "type": kind,
        "frames": FRAME_COUNT,
        "duration_seconds": DURATION_SECONDS,
        "fps": 1.0 / STEP_SECONDS,
        "ego_id": AV_ID,
        "follower_id": collision_follower_id,
        "leader_id": collision_leader_id,
        "collision_actor_id": FOLLOWER_ID,
        "background_actor_id": LEADER_ID,
        "collision_step": collision_step,
        "collision_time_seconds": collision_time,
        "collision_frames": len(intended_collision_events),
        "last_collision_time_seconds": intended_collision_events[-1]["time_seconds"],
        "first_collision": first_event,
        "impact_pair_center_distance_m": round(impact_pair_distance, 4),
        "post_impact_target_roll_m": post_impact_roll_m,
        "av_collision_verified": True,
        "collision_pair": intended_pair,
        "unexpected_collision_pairs": [list(pair) for pair in unexpected_pairs],
        "cutin_lane_shift_m": round(lane_shift, 4),
        "cutin_raw_displacement_m": round(adjacent_shift, 4),
        "maximum_target_displacement_m": round(maximum_lateral_shift, 4),
        "initial_ego_speed_mps": round(initial_av_speed, 4),
        "initial_follower_speed_mps": round(
            initial_follower_speed if kind == "cutin" else initial_av_speed, 4
        ),
        "initial_leader_speed_mps": round(
            initial_av_speed if kind == "cutin" else initial_follower_speed, 4
        ),
        "initial_collision_actor_speed_mps": round(initial_follower_speed, 4),
        "initial_background_actor_speed_mps": round(initial_leader_speed, 4),
        "final_ego_speed_mps": round(float(np.linalg.norm(states_by_id[AV_ID][-1, 3:5])), 4),
        "final_follower_speed_mps": round(
            float(np.linalg.norm(states_by_id[collision_follower_id][-1, 3:5])), 4
        ),
        "final_leader_speed_mps": round(
            float(np.linalg.norm(states_by_id[collision_leader_id][-1, 3:5])), 4
        ),
        "final_collision_actor_speed_mps": round(
            float(np.linalg.norm(states_by_id[FOLLOWER_ID][-1, 3:5])), 4
        ),
        "final_background_actor_speed_mps": round(
            float(np.linalg.norm(states_by_id[LEADER_ID][-1, 3:5])), 4
        ),
    }
    return recording, report


def _publish_one(
    kind: str,
    recording: dict[str, Any],
    report: dict[str, Any],
    *,
    source_init: Path,
    source_metadata: dict[str, Any],
    map_path: Path,
    library_dir: Path,
) -> dict[str, Any]:
    definition = DEFINITIONS[kind]
    target = library_dir / f"{definition['stem']}.pkl"
    init_target = library_dir / f"{definition['stem']}.init.pkl"
    seed_target = library_dir / f"{definition['stem']}.seed.png"
    with target.open("wb") as stream:
        pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
    shutil.copy2(source_init, init_target)
    seed_target.unlink(missing_ok=True)

    scenario_hash = shared._step_sha256(recording, 0)
    with init_target.open("rb") as stream:
        initialization = pickle.load(stream)
    initialization_hash = shared._step_sha256(initialization, -1)
    if scenario_hash != initialization_hash:
        raise ValueError(f"{kind} frame zero does not match the initialization terminal state")

    metadata = {
        "schema": "denseworld.standard-scenario.v2",
        "library_id": definition["id"],
        "library_name": definition["name"],
        "library_description": definition["description"],
        "library_category": "normal",
        "library_tags": definition["tags"],
        "backend_model": "rulebased",
        "standard_backend_locked": True,
        "traffic_controller": "scripted_collision_replay",
        "map_path": _relative(map_path),
        "init_mode": "data",
        "init_file": _relative(init_target),
        "initialization_seed": 42,
        "total_step": FRAME_COUNT - 1,
        "sim_resolution": STEP_SECONDS,
        "max_sim_time": DURATION_SECONDS,
        "recording_operational_start_step": 0,
        "arrival_rate": 0.0,
        "lane_arrival_rates": {},
        "mixed_traffic_enabled": False,
        "cyclist_ratio": 0.0,
        "pedestrians_per_crosswalk": 0,
        "max_pedestrians": 0,
        "vehicle_size_mode": "passenger_only",
        "initial_speed_mode": "recorded",
        "signalize_unsignalized_map": False,
        "world_loop_ego": False,
        "participants": {"motorized": 6, "pedestrians": 0, "cyclists": 0},
        "peak_participants": {"motorized": 6, "pedestrians": 0, "cyclists": 0},
        "source_path": _relative(target),
        "source_format": "trafficwm.scripted-collision.v1",
        "source_start_seconds": 0.0,
        "source_end_seconds": DURATION_SECONDS,
        "native_traffic_fps": 10.0,
        "default_world_prompt": definition["prompt"],
        "default_transfer_prompt": TRANSFER_PROMPT,
        "world_omnidreams_seed": 1,
        "world_omnidreams_actor_allow_overlap": True,
        "world_omnidreams_actor_hood_occlusion_distance_m": 0.0,
        "world_omnidreams_actor_hood_occlusion_lateral_m": 0.0,
        "world_omnidreams_actor_oncoming_lateral_exclusion_m": 3.0,
        "world_omnidreams_actor_max_count": 3,
        "world_seed_map_radius_m": 120.0,
        "world_local_target_count": 6,
        "world_initial_vehicle_limit": 6,
        "world_seed_backend": "transfer1",
        "world_seed_alignment_mode": "opening_restart",
        "allow_recorded_runtime_seed": True,
        "use_existing_seed": False,
        "seed_image": "",
        "seed_init_file": _relative(init_target),
        "seed_source": "runtime-transfer1-required",
        "seed_source_experiment_id": "",
        "seed_source_time_seconds": 0.0,
        "seed_source_frame": 0,
        "seed_source_fps": float(source_metadata.get("seed_source_fps") or 30.0),
        "seed_warmup_seconds": 0.0,
        "seed_scenario_state_step": 0,
        "seed_initialization_state_step": 10,
        "seed_initialization_history_frames": 11,
        "seed_alignment": "exact_control_frame_t0",
        "seed_ego_id": AV_ID,
        "seed_width": int(source_metadata.get("seed_width") or 1280),
        "seed_height": int(source_metadata.get("seed_height") or 704),
        "seed_sha256": "",
        "seed_init_sha256": hashlib.sha256(init_target.read_bytes()).hexdigest(),
        "seed_state_sha256": scenario_hash,
        "expected_collision": {
            "type": kind,
            "ego_id": AV_ID,
            "follower_id": FOLLOWER_ID if kind == "cutin" else AV_ID,
            "leader_id": AV_ID if kind == "cutin" else FOLLOWER_ID,
            "pair": sorted([AV_ID, FOLLOWER_ID]),
            "time_seconds": report["collision_time_seconds"],
            "step": report["collision_step"],
            "persistent_contact_after_impact": False,
        },
        "rule_control": {
            "bv_controller": "DeterministicCollisionScript",
            "av_controller": "DeterministicCollisionScript",
            "collision_type": kind,
            "initial_speed_mps": report["initial_ego_speed_mps"],
        },
    }
    target.with_suffix(target.suffix + ".meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    target.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "schema": "denseworld.normalized-recording.v1",
                "recording": _relative(target),
                "source_frames": FRAME_COUNT,
                "source_fps": 10.0,
                "recording_frames": FRAME_COUNT,
                "duration_seconds": DURATION_SECONDS,
                "actor_tracks": 6,
                "expected_collision": metadata["expected_collision"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "id": definition["id"],
        "name": definition["name"],
        "path": _relative(target),
        "metadata": _relative(target.with_suffix(target.suffix + ".meta.json")),
        "collision_time_seconds": report["collision_time_seconds"],
        "collision_step": report["collision_step"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=ROOT / "output/scenarios/citynde/library",
    )
    parser.add_argument(
        "--validation-dir",
        type=Path,
        default=ROOT / "output/validation/collision_scenarios_20260828",
    )
    parser.add_argument(
        "--map",
        type=Path,
        default=ROOT / "algorithm_sources/CityNDE_src/assets/map/cnde_map_xa_wenying.pkl",
    )
    args = parser.parse_args()

    library_dir = args.library_dir.resolve()
    validation_dir = args.validation_dir.resolve()
    map_path = args.map.resolve()
    source_recording_path = library_dir / f"{SOURCE_STEM}.pkl"
    source_init = library_dir / f"{SOURCE_STEM}.init.pkl"
    source_metadata_path = source_recording_path.with_suffix(
        source_recording_path.suffix + ".meta.json"
    )
    for required in (source_recording_path, source_init, source_metadata_path, map_path):
        if not required.is_file():
            raise FileNotFoundError(required)
    with source_recording_path.open("rb") as stream:
        source_recording = pickle.load(stream)
    source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    paths = _load_paths(map_path)
    library_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    records = []
    reports = []
    for kind in ("cutin", "rearend"):
        recording, report = _build_trajectory(kind, source_recording, paths)
        report_path = validation_dir / f"{kind}_validation.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        record = _publish_one(
            kind,
            recording,
            report,
            source_init=source_init,
            source_metadata=source_metadata,
            map_path=map_path,
            library_dir=library_dir,
        )
        records.append(record)
        reports.append({**report, "path": _relative(report_path)})

    manifest = {
        "schema": "trafficwm.collision-scenarios.v1",
        "created_from": _relative(source_recording_path),
        "map_path": _relative(map_path),
        "count": len(records),
        "records": records,
        "validation": reports,
    }
    manifest_path = validation_dir / "scenarios.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**manifest, "manifest": _relative(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
