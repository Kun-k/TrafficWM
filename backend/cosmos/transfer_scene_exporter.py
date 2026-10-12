"""Export CityNDE recordings as seven-camera Cosmos Transfer RDS-HQ scenes."""
from __future__ import annotations

import io
import json
import math
import os
import pickle
import re
import sys
import tarfile
import types
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np

from backend.cosmos.camera_calibration import (
    camera_calibration,
    default_ftheta_intrinsics_path,
)


CAMERAS = (
    "camera_front_wide_120fov",
    "camera_front_tele_30fov",
    "camera_cross_right_120fov",
    "camera_cross_left_120fov",
    "camera_rear_left_70fov",
    "camera_rear_right_70fov",
    "camera_rear_tele_30fov",
)

VIEW_KEYS = {
    "camera_front_wide_120fov": "front_wide",
    "camera_front_tele_30fov": "front_tele",
    "camera_cross_right_120fov": "cross_right",
    "camera_cross_left_120fov": "cross_left",
    "camera_rear_left_70fov": "rear_left",
    "camera_rear_right_70fov": "rear_right",
    "camera_rear_tele_30fov": "rear",
}

CAMERA_FOV = {
    "camera_front_wide_120fov": 120.0,
    "camera_front_tele_30fov": 30.0,
    "camera_cross_right_120fov": 120.0,
    "camera_cross_left_120fov": 120.0,
    "camera_rear_left_70fov": 70.0,
    "camera_rear_right_70fov": 70.0,
    "camera_rear_tele_30fov": 30.0,
}

DEFAULT_MAP_RADIUS_M = 75.0
DEFAULT_AGENT_RADIUS_M = 90.0
TRANSFER_WINDOW_SOURCE_STEPS = 30


def _load_converter(path: Path):
    module_name = "trafficwm_recording_scene_converter"
    source = path.read_text(encoding="utf-8")
    # The host manager uses Python 3.9 and an older NumPy. This alias is only
    # static typing metadata and is not needed by the conversion runtime.
    source = source.replace("ArrayF = NDArray[np.floating[Any]]", "ArrayF = Any")
    source = source.replace(
        '"object_type": "Car",',
        '"object_type": OBJECT_TYPES.get(str(object_id), "Car"),',
    )
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.OBJECT_TYPES = {}
    sys.modules[module_name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    module.WAYMO_CAMERA_NAMES = CAMERAS
    # CityNDE types 0/4 are lane centers used for topology, not observed road
    # markings or lane boundaries. RDS-HQ accepts map categories as optional,
    # so these centerlines must not be turned into visible control geometry.
    module.LANE_LINE_TYPES = frozenset({1, 3})
    module.ROAD_BOUNDARY_TYPES = frozenset({2})
    return module


def _mapping_value(mapping: dict, actor_id: Any, default: Any = None) -> Any:
    if actor_id in mapping:
        return mapping[actor_id]
    actor_text = str(actor_id)
    if actor_text in mapping:
        return mapping[actor_text]
    try:
        numeric_id = int(actor_text)
        if numeric_id in mapping:
            return mapping[numeric_id]
    except ValueError:
        pass
    return next((value for key, value in mapping.items() if str(key) == actor_text), default)


def _cosmos_object_type(data: dict[str, Any], actor_id: Any) -> str:
    road_user_type = data.get("road_user_type") or {}
    vehicle_class = data.get("vehicle_class") or {}
    source_type = str(_mapping_value(road_user_type, actor_id, "vehicle") or "vehicle").lower()
    source_class = str(_mapping_value(vehicle_class, actor_id, "vehicle") or "vehicle").lower()
    if source_type == "pedestrian":
        return "Pedestrian"
    if source_type in {"cyclist", "non_motorized", "bicycle"}:
        return "Cyclist"
    if source_class in {"truck", "bus"}:
        return "Truck"
    return "Car"


def _with_pedestrian_tracks(data: dict[str, Any]) -> dict[str, Any]:
    pedestrian_ids = list(data.get("pedestrian_id_per_step") or [])
    pedestrian_states = list(data.get("pedestrian_state_per_step") or [])
    if not pedestrian_ids or not pedestrian_states:
        return data
    merged = dict(data)
    vehicle_ids = [list(values) for values in data.get("vehicle_id_per_step") or []]
    vehicle_states = [np.asarray(values, dtype=np.float64) for values in data.get("vehicle_state_per_step") or []]
    for step in range(min(len(vehicle_ids), len(vehicle_states), len(pedestrian_ids), len(pedestrian_states))):
        step_pedestrian_ids = list(pedestrian_ids[step])
        step_pedestrian_states = np.asarray(pedestrian_states[step], dtype=np.float64)
        if not step_pedestrian_ids or step_pedestrian_states.size == 0:
            continue
        step_pedestrian_states = step_pedestrian_states.reshape(len(step_pedestrian_ids), -1)
        vehicle_ids[step].extend(step_pedestrian_ids)
        current = vehicle_states[step]
        current = current.reshape(len(current), -1) if current.size else np.empty((0, step_pedestrian_states.shape[1]))
        vehicle_states[step] = np.concatenate((current, step_pedestrian_states), axis=0)
    static_attributes = dict(data.get("vehicle_static_attribute") or {})
    static_attributes.update(data.get("pedestrian_static_attribute") or {})
    road_user_type = dict(data.get("road_user_type") or {})
    for step_ids in pedestrian_ids:
        for pedestrian_id in step_ids:
            road_user_type[pedestrian_id] = "pedestrian"
    merged["vehicle_id_per_step"] = vehicle_ids
    merged["vehicle_state_per_step"] = vehicle_states
    merged["vehicle_static_attribute"] = static_attributes
    merged["road_user_type"] = road_user_type
    return merged


def _wrapped_delta(start: float, end: float) -> float:
    return (float(end) - float(start) + math.pi) % (2.0 * math.pi) - math.pi


def _road_user_motion(
    actor_id: Any,
    id_steps: list[list[Any]],
    state_steps: list[np.ndarray],
    source_fps: float,
) -> tuple[np.ndarray, float]:
    """Return the terminal state and a robust short-horizon yaw rate."""
    history: list[np.ndarray] = []
    actor_text = str(actor_id)
    for ids, states in zip(id_steps, state_steps):
        index = next((i for i, value in enumerate(ids) if str(value) == actor_text), None)
        if index is None or index >= len(states):
            continue
        state = np.asarray(states[index], dtype=np.float64).reshape(-1)
        if state.size >= 7 and np.all(np.isfinite(state[:7])):
            history.append(state[:7].copy())
    if not history:
        raise ValueError(f"Cannot extrapolate missing terminal actor {actor_id!r}")

    tail = history[-6:]
    heading_deltas = [
        _wrapped_delta(first[2], second[2]) * float(source_fps)
        for first, second in zip(tail, tail[1:])
    ]
    yaw_rate = float(np.median(heading_deltas)) if heading_deltas else 0.0
    # The tail only supplies temporal context to Transfer. Limiting curvature
    # prevents noisy 0.1 s headings from sending geometry off the roadway.
    yaw_rate = max(-0.45, min(0.45, yaw_rate))
    return history[-1], yaw_rate


def _extrapolate_road_users(
    id_steps: list[list[Any]],
    state_steps: list[Any],
    *,
    extra_steps: int,
    source_fps: float,
) -> tuple[list[list[Any]], list[np.ndarray]]:
    ids_out = [list(values) for values in id_steps]
    states_out = [np.asarray(values, dtype=np.float64).copy() for values in state_steps]
    if extra_steps <= 0 or not ids_out:
        return ids_out, states_out

    terminal_ids = list(ids_out[-1])
    motions = {
        str(actor_id): _road_user_motion(actor_id, ids_out, states_out, source_fps)
        for actor_id in terminal_ids
    }
    dt = 1.0 / float(source_fps)
    current = {str(actor_id): motions[str(actor_id)][0].copy() for actor_id in terminal_ids}
    for _ in range(int(extra_steps)):
        next_states: list[np.ndarray] = []
        for actor_id in terminal_ids:
            key = str(actor_id)
            state = current[key].copy()
            yaw_rate = motions[key][1]
            vx, vy = float(state[3]), float(state[4])
            speed = math.hypot(vx, vy)
            heading = float(state[2])
            if speed > 1e-4:
                velocity_heading = math.atan2(vy, vx)
                direction = -1.0 if abs(_wrapped_delta(heading, velocity_heading)) > math.pi / 2.0 else 1.0
                signed_speed = direction * speed
                midpoint_heading = heading + 0.5 * yaw_rate * dt
                state[0] += signed_speed * math.cos(midpoint_heading) * dt
                state[1] += signed_speed * math.sin(midpoint_heading) * dt
                state[2] = (heading + yaw_rate * dt + math.pi) % (2.0 * math.pi) - math.pi
                state[3] = signed_speed * math.cos(float(state[2]))
                state[4] = signed_speed * math.sin(float(state[2]))
            state[5:7] = 0.0
            current[key] = state
            next_states.append(state.copy())
        ids_out.append(list(terminal_ids))
        states_out.append(np.asarray(next_states, dtype=np.float64))
    return ids_out, states_out


def prepare_citynde_transfer_window(
    input_path: Path,
    output_path: Path,
    *,
    real_source_steps: int,
    target_source_steps: int = TRANSFER_WINDOW_SOURCE_STEPS,
    source_fps: float = 10.0,
) -> dict[str, Any]:
    """Build a continuous native control window without advancing CityNDE.

    Transfer2.5 jointly denoises 29 frames at 10 Hz and consumes 87 control
    frames at 30 Hz. A one-second warmup has 11 endpoint-inclusive states; a
    bounded kinematic tail supplies the other 19 states. Model frame 10 still
    corresponds exactly to the real paused simulation state.
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    with input_path.open("rb") as stream:
        source = pickle.load(stream)
    if not isinstance(source, dict):
        raise TypeError(f"Expected CityNDE recording dict, got {type(source)!r}")
    source_fps = float(source_fps)
    if not math.isfinite(source_fps) or source_fps <= 0.0:
        raise ValueError("source_fps must be a positive finite number")

    vehicle_ids = list(source.get("vehicle_id_per_step") or [])
    vehicle_states = list(source.get("vehicle_state_per_step") or [])
    real_source_steps = int(real_source_steps)
    target_source_steps = int(target_source_steps)
    if (
        real_source_steps < 1
        or real_source_steps > len(vehicle_ids)
        or real_source_steps > len(vehicle_states)
    ):
        raise ValueError(
            f"Requested {real_source_steps} real states from a recording with "
            f"{min(len(vehicle_ids), len(vehicle_states))} states"
        )
    if target_source_steps < real_source_steps:
        raise ValueError("target_source_steps cannot be shorter than the real source window")

    start = len(vehicle_ids) - real_source_steps
    prepared = dict(source)
    actual_vehicle_ids = [list(values) for values in vehicle_ids[start:]]
    actual_vehicle_states = [
        np.asarray(values, dtype=np.float64).copy() for values in vehicle_states[start:]
    ]
    extra_steps = target_source_steps - real_source_steps
    prepared["vehicle_id_per_step"], prepared["vehicle_state_per_step"] = _extrapolate_road_users(
        actual_vehicle_ids,
        actual_vehicle_states,
        extra_steps=extra_steps,
        source_fps=source_fps,
    )

    pedestrian_ids = list(source.get("pedestrian_id_per_step") or [])
    pedestrian_states = list(source.get("pedestrian_state_per_step") or [])
    if len(pedestrian_ids) >= real_source_steps and len(pedestrian_states) >= real_source_steps:
        prepared["pedestrian_id_per_step"], prepared["pedestrian_state_per_step"] = _extrapolate_road_users(
            [list(values) for values in pedestrian_ids[-real_source_steps:]],
            [np.asarray(values, dtype=np.float64).copy() for values in pedestrian_states[-real_source_steps:]],
            extra_steps=extra_steps,
            source_fps=source_fps,
        )

    for ids_key, states_key in (
        ("dynamic_polyline_id_per_step", "dynamic_polyline_state_per_step"),
    ):
        ids_values = list(source.get(ids_key) or [])
        state_values = list(source.get(states_key) or [])
        if len(ids_values) < real_source_steps or len(state_values) < real_source_steps:
            continue
        prepared[ids_key] = [deepcopy(value) for value in ids_values[-real_source_steps:]]
        prepared[states_key] = [
            np.asarray(value).copy() for value in state_values[-real_source_steps:]
        ]
        for _ in range(extra_steps):
            prepared[ids_key].append(deepcopy(prepared[ids_key][-1]))
            prepared[states_key].append(np.asarray(prepared[states_key][-1]).copy())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        pickle.dump(prepared, stream, protocol=pickle.HIGHEST_PROTOCOL)
    report = {
        "schema": "denseworld.transfer-control-window.v1",
        "source": str(input_path),
        "prepared_recording": str(output_path),
        "source_fps": source_fps,
        "real_source_steps": real_source_steps,
        "real_duration_seconds": (real_source_steps - 1) / source_fps,
        "synthetic_tail_steps": extra_steps,
        "native_source_steps": target_source_steps,
        "native_duration_seconds": (target_source_steps - 1) / source_fps,
        "tail_method": "bounded_constant_turn_rate_and_speed",
        "terminal_vehicle_count": len(prepared["vehicle_id_per_step"][-1]),
        "terminal_pedestrian_count": len((prepared.get("pedestrian_id_per_step") or [[]])[-1]),
        "traffic_light_tail": "zero_order_hold",
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _calibration(output_dir: Path, width: int = 1280, height: int = 720) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    intrinsics: dict[str, Any] = {"__key__": "trafficwm-seven-camera-rig-v1"}
    extrinsics: dict[str, Any] = {}
    for camera, fov in CAMERA_FOV.items():
        focal = width / (2.0 * math.tan(math.radians(fov) / 2.0))
        intrinsics[f"pinhole_intrinsic.{camera}.npy"] = np.array(
            [focal, focal, width / 2.0, height / 2.0, width, height], dtype=np.float64
        )
        extrinsics[camera] = np.asarray(
            camera_calibration(camera, width, height)["camera_to_vehicle_flu"]["matrix"],
            dtype=np.float64,
        )
    intrinsics_path = output_dir / "intrinsics.npy"
    extrinsics_path = output_dir / "extrinsics.npy"
    np.save(intrinsics_path, intrinsics, allow_pickle=True)
    np.save(extrinsics_path, extrinsics, allow_pickle=True)
    return intrinsics_path, extrinsics_path


def _line_label(feature_id: str, points: list[list[float]]) -> dict[str, Any]:
    vertices = [[float(point[0]), float(point[1]), 0.015] for point in points]
    count = len(vertices)
    return {
        "labelData": {
            "shape3d": {
                "polyline3d": {"vertices": vertices},
                "attributes": [
                    {"name": "colors", "enumsList": {"enumsList": ["WHITE"] * count}},
                    {"name": "styles", "enumsList": {"enumsList": ["SOLID_SINGLE"] * count}},
                    {"name": "feature_id", "text": feature_id},
                ],
            }
        }
    }


def _surface_label(feature_id: str, points: list[list[float]]) -> dict[str, Any]:
    vertices = [[float(point[0]), float(point[1]), 0.02] for point in points]
    if len(vertices) > 1 and np.allclose(vertices[0], vertices[-1]):
        vertices.pop()
    return {
        "labelData": {
            "shape3d": {
                "surface": {"vertices": vertices},
                "attributes": [{"name": "feature_id", "text": feature_id}],
            }
        }
    }


def _near_ego_path(
    points: list[list[float]],
    ego_xy: np.ndarray | None,
    radius_m: float,
) -> bool:
    if ego_xy is None or not len(ego_xy):
        return True
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or not len(values) or values.shape[1] < 2:
        return False
    delta = values[:, None, :2] - ego_xy[None, :, :2]
    return bool(np.any(np.sum(delta * delta, axis=-1) <= radius_m * radius_m))


def _write_semantic_map_features(
    scene_root: Path,
    clip_id: str,
    map_state: dict[str, Any],
    *,
    ego_xy: np.ndarray | None = None,
    radius_m: float = DEFAULT_MAP_RADIUS_M,
) -> dict[str, int]:
    crosswalk_labels: list[dict[str, Any]] = []
    for index, crosswalk in enumerate(map_state.get("crosswalks") or []):
        polygon = crosswalk.get("polygon") or []
        if len(polygon) < 3 or not _near_ego_path(polygon, ego_xy, radius_m):
            continue
        crosswalk_labels.append(_surface_label(f"trafficwm-crosswalk-{index}", polygon))

    wait_line_labels: list[dict[str, Any]] = []
    for index, stop_line in enumerate(map_state.get("stop_lines") or []):
        points = stop_line.get("points") or []
        if len(points) >= 2 and _near_ego_path(points, ego_xy, radius_m):
            wait_line_labels.append(_line_label(f"trafficwm-stop-line-{index}", points))

    crosswalk_path = scene_root / "3d_crosswalks" / f"{clip_id}.tar"
    crosswalk_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tar_json(
        crosswalk_path,
        f"{clip_id}.crosswalks.json",
        {"labels": crosswalk_labels},
    )
    wait_line_path = scene_root / "3d_wait_lines" / f"{clip_id}.tar"
    wait_line_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tar_json(
        wait_line_path,
        f"{clip_id}.wait_lines.json",
        {"labels": wait_line_labels},
    )
    return {
        "crosswalks": len(crosswalk_labels),
        "wait_lines": len(wait_line_labels),
    }


def _read_tar_json(tar_path: Path) -> tuple[str, dict[str, Any]]:
    with tarfile.open(tar_path, "r") as archive:
        member = next(item for item in archive.getmembers() if item.name.endswith(".json"))
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(f"Cannot read {member.name} from {tar_path}")
        return member.name, json.load(stream)


def _write_tar_json(tar_path: Path, member_name: str, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with tarfile.open(tar_path, "w") as archive:
        info = tarfile.TarInfo(name=member_name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _feature_id(label: dict[str, Any]) -> str:
    attributes = (
        label.get("labelData", {})
        .get("shape3d", {})
        .get("attributes", [])
    )
    for attribute in attributes:
        if attribute.get("name") == "feature_id":
            return str(attribute.get("text") or "")
    return ""


def _set_feature_id(label: dict[str, Any], feature_id: str) -> None:
    attributes = (
        label.setdefault("labelData", {})
        .setdefault("shape3d", {})
        .setdefault("attributes", [])
    )
    attributes[:] = [item for item in attributes if item.get("name") != "feature_id"]
    attributes.append({"name": "feature_id", "text": feature_id})


def _write_official_ftheta_intrinsics(scene_root: Path, clip_id: str) -> dict[str, Any]:
    source_path = default_ftheta_intrinsics_path()
    if not source_path.is_file():
        raise FileNotFoundError(f"Cosmos f-theta calibration not found: {source_path}")

    payloads: dict[str, bytes] = {}
    with tarfile.open(source_path, "r") as source:
        for camera in CAMERAS:
            suffix = f".ftheta_intrinsic.{camera}.npy"
            member = next(
                (item for item in source.getmembers() if item.isfile() and item.name.endswith(suffix)),
                None,
            )
            if member is None:
                raise KeyError(f"Official f-theta calibration is missing {camera}")
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError(f"Cannot read {member.name} from {source_path}")
            payloads[camera] = stream.read()

    target_path = scene_root / "ftheta_intrinsic" / f"{clip_id}.tar"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target_path, "w") as target:
        for camera, data in payloads.items():
            info = tarfile.TarInfo(name=f"{clip_id}.ftheta_intrinsic.{camera}.npy")
            info.size = len(data)
            info.mtime = 0
            target.addfile(info, io.BytesIO(data))
    return {
        "model": "ftheta",
        "source": str(source_path),
        "camera_count": len(payloads),
        "rig": {
            camera: camera_calibration(camera, 1280, 720)["camera_to_vehicle_flu"]
            for camera in CAMERAS
        },
    }


def _citynde_segment_key(feature_id: str) -> tuple[str, int] | None:
    """Parse ``road_id_segment:chunk`` without joining converter jump chunks."""
    source_id, separator, chunk_text = feature_id.rpartition(":")
    if not separator or chunk_text != "0":
        return None
    match = re.fullmatch(r"(.+)_([0-9]+)", source_id)
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def _laneline_vertices(label: dict[str, Any]) -> list[list[float]]:
    return (
        label.get("labelData", {})
        .get("shape3d", {})
        .get("polyline3d", {})
        .get("vertices", [])
    )


def _can_merge_lanelines(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    max_gap_m: float = 1.0,
    max_heading_change_degrees: float = 30.0,
) -> bool:
    left_vertices = np.asarray(_laneline_vertices(left), dtype=np.float64)
    right_vertices = np.asarray(_laneline_vertices(right), dtype=np.float64)
    if left_vertices.ndim != 2 or right_vertices.ndim != 2:
        return False
    if len(left_vertices) < 2 or len(right_vertices) < 2:
        return False
    gap = right_vertices[0, :2] - left_vertices[-1, :2]
    gap_length = float(np.linalg.norm(gap))
    if not math.isfinite(gap_length) or gap_length > max_gap_m:
        return False
    left_tangent = left_vertices[-1, :2] - left_vertices[-2, :2]
    right_tangent = right_vertices[1, :2] - right_vertices[0, :2]
    left_norm = float(np.linalg.norm(left_tangent))
    right_norm = float(np.linalg.norm(right_tangent))
    if left_norm <= 1e-9 or right_norm <= 1e-9:
        return False
    minimum_cosine = math.cos(math.radians(max_heading_change_degrees))
    if float(np.dot(left_tangent, right_tangent) / (left_norm * right_norm)) < minimum_cosine:
        return False
    if gap_length > 1e-6:
        gap_direction = gap / gap_length
        if float(np.dot(left_tangent / left_norm, gap_direction)) < minimum_cosine:
            return False
        if float(np.dot(gap_direction, right_tangent / right_norm)) < minimum_cosine:
            return False
    return True


def _merge_citynde_lanelines(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restore complete lines split into fixed-size CityNDE storage segments."""
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    ungrouped: list[dict[str, Any]] = []
    for label in labels:
        key = _citynde_segment_key(_feature_id(label))
        if key is None:
            ungrouped.append(label)
            continue
        grouped.setdefault(key[0], []).append((key[1], label))

    merged = list(ungrouped)
    for segments in grouped.values():
        segments.sort(key=lambda item: item[0])
        current_index, current = segments[0]
        for next_index, candidate in segments[1:]:
            if next_index != current_index + 1 or not _can_merge_lanelines(current, candidate):
                merged.append(current)
                current_index, current = next_index, candidate
                continue
            current_vertices = _laneline_vertices(current)
            current_vertices.extend(_laneline_vertices(candidate))
            attributes = current["labelData"]["shape3d"].setdefault("attributes", [])
            for attribute_name in ("colors", "styles"):
                attribute = next(
                    (item for item in attributes if item.get("name") == attribute_name),
                    None,
                )
                if attribute is None:
                    continue
                values = attribute.get("enumsList", {}).get("enumsList", [])
                if values:
                    attribute["enumsList"]["enumsList"] = [values[0]] * len(current_vertices)
            current_index = next_index
        merged.append(current)
    return merged


def _style_citynde_lanelines(
    scene_root: Path,
    clip_id: str,
    map_types: dict[str, int],
) -> dict[str, int]:
    tar_path = scene_root / "3d_lanelines" / f"{clip_id}.tar"
    member_name, payload = _read_tar_json(tar_path)
    counts = {"long_dashed": 0, "short_dashed": 0, "solid": 0, "unknown": 0}
    for label in payload.get("labels") or []:
        feature_id = _feature_id(label)
        source_id = feature_id.rsplit(":", 1)[0]
        map_type = map_types.get(source_id)
        if map_type == 3:
            style = "SHORT_DASHED_SINGLE"
            count_key = "short_dashed"
        elif map_type == 1:
            # CityNDE's MTR adapter maps type 1 to Waymo map type 6
            # (broken single white). Cosmos names that rendered pattern
            # LONG_DASHED_SINGLE.
            style = "LONG_DASHED_SINGLE"
            count_key = "long_dashed"
        else:
            counts["unknown"] += 1
            continue
        vertices = (
            label.get("labelData", {})
            .get("shape3d", {})
            .get("polyline3d", {})
            .get("vertices", [])
        )
        attributes = (
            label.setdefault("labelData", {})
            .setdefault("shape3d", {})
            .setdefault("attributes", [])
        )
        attributes[:] = [item for item in attributes if item.get("name") != "styles"]
        attributes.append(
            {"name": "styles", "enumsList": {"enumsList": [style] * len(vertices)}}
        )
        counts[count_key] += 1
    source_segments = len(payload.get("labels") or [])
    payload["labels"] = _merge_citynde_lanelines(list(payload.get("labels") or []))
    counts["source_segments"] = source_segments
    counts["rendered_lines"] = len(payload["labels"])
    counts["merged_segments"] = source_segments - len(payload["labels"])
    _write_tar_json(tar_path, member_name, payload)
    return counts


def _write_citynde_lanes(
    scene_root: Path,
    clip_id: str,
    map_polylines: dict[Any, dict[str, Any]],
    *,
    ego_xy: np.ndarray,
    radius_m: float,
    lane_width_m: float = 3.5,
    selected_lane_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Export selected CityNDE centerlines as virtual RDS-HQ lane rails."""
    source_counts = {"regular": 0, "intersection": 0}
    labels: list[dict[str, Any]] = []

    def text_list(values: Any) -> dict[str, list[str]]:
        normalized = [str(value) for value in values or []]
        return {"textList": normalized} if normalized else {}

    def neighbor_width(polyline: dict[str, Any], states: np.ndarray) -> float:
        candidates: list[float] = []
        neighbor_ids = [
            *(polyline.get("left_lanes_id") or []),
            *(polyline.get("right_lanes_id") or []),
        ]
        for neighbor_id in neighbor_ids:
            neighbor = _mapping_value(map_polylines, neighbor_id, {}) or {}
            raw_neighbor_states = neighbor.get("states")
            neighbor_states = np.asarray(
                raw_neighbor_states if raw_neighbor_states is not None else [],
                dtype=np.float64,
            )
            if neighbor_states.ndim != 2 or len(neighbor_states) < 2:
                continue
            delta = states[:, None, :2] - neighbor_states[None, :, :2]
            distances = np.sqrt(np.sum(delta * delta, axis=-1))
            candidates.append(float(np.median(np.min(distances, axis=1))))
        plausible = [value for value in candidates if 2.4 <= value <= 4.8]
        return min(plausible) if plausible else lane_width_m

    for lane_id, polyline in map_polylines.items():
        map_type = int(polyline.get("type", -1))
        if map_type not in {0, 4}:
            continue
        if selected_lane_ids is not None and str(lane_id) not in selected_lane_ids:
            continue
        raw_states = polyline.get("states")
        states = np.asarray(raw_states if raw_states is not None else [], dtype=np.float64)
        if states.ndim != 2 or len(states) < 2 or states.shape[1] < 2:
            continue
        if not _near_ego_path(states[:, :2].tolist(), ego_xy, radius_m):
            continue
        source_counts["intersection" if map_type == 4 else "regular"] += 1
        headings = (
            states[:, 2]
            if states.shape[1] >= 3
            else np.arctan2(
                np.gradient(states[:, 1]),
                np.gradient(states[:, 0]),
            )
        )
        half_width = 0.5 * neighbor_width(polyline, states)
        normal = np.column_stack((-np.sin(headings), np.cos(headings)))
        left = states[:, :2] + half_width * normal
        right = states[:, :2] - half_width * normal
        left_vertices = [[float(x), float(y), 0.015] for x, y in left]
        right_vertices = [[float(x), float(y), 0.015] for x, y in right]
        point_count = len(left_vertices)
        left_ids = [str(value) for value in polyline.get("left_lanes_id") or []]
        right_ids = [str(value) for value in polyline.get("right_lanes_id") or []]
        attributes = [
            {"name": "feature_id", "text": str(lane_id)},
            {"name": "label_name", "enum": "lane"},
            {
                "name": "left_edge_colors",
                "enumsList": {"enumsList": ["UNKNOWN"] * point_count},
            },
            {
                "name": "right_edge_colors",
                "enumsList": {"enumsList": ["UNKNOWN"] * point_count},
            },
            {
                "name": "left_edge_styles",
                "enumsList": {"enumsList": ["VIRTUAL"] * point_count},
            },
            {
                "name": "right_edge_styles",
                "enumsList": {"enumsList": ["VIRTUAL"] * point_count},
            },
            {
                "name": "previous_lane_ids",
                "textList": text_list(polyline.get("prev_lanes_id")),
            },
            {
                "name": "next_lane_ids",
                "textList": text_list(polyline.get("next_lanes_id")),
            },
            {"name": "left_lane_id", "text": left_ids[0] if left_ids else "-1"},
            {"name": "right_lane_id", "text": right_ids[0] if right_ids else "-1"},
            {"name": "lane_direction", "enum": "STRAIGHT"},
            {"name": "vehicle_types", "enumsList": {"enumsList": ["CAR"]}},
        ]
        labels.append(
            {
                "labelData": {
                    "shape3d": {
                        "attributes": attributes,
                        "unit": "METRIC",
                        "polylines3d": {
                            "polylines": [
                                {"vertices": left_vertices},
                                {"vertices": right_vertices},
                            ]
                        },
                    }
                }
            }
        )

    tar_path = scene_root / "3d_lanes" / f"{clip_id}.tar"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tar_json(
        tar_path,
        f"{clip_id}.lanes.json",
        {"labels": labels},
    )
    path_matched = selected_lane_ids is not None
    return {
        "strategy": (
            "ego-path-matched-virtual-lane-rails"
            if path_matched
            else "topology-only-virtual-lane-rails"
        ),
        "reason": (
            "Only lane segments matched to the ego trajectory and heading are rendered, "
            "preventing nearby roundabout branches from crossing the forward control."
            if path_matched
            else "CityNDE types 0/4 provide lane topology for non-rendering consumers."
        ),
        "lanes": len(labels),
        "rails": 2 * len(labels),
        "source_counts": source_counts,
    }


def _match_ego_path_lane_ids(
    map_polylines: dict[Any, dict[str, Any]],
    ego_states: np.ndarray,
    *,
    heading_weight_m: float = 4.0,
    max_distance_m: float = 6.0,
    max_heading_error_degrees: float = 45.0,
) -> list[str]:
    """Match every ego state to one lane without pulling in adjacent branches."""
    states = np.asarray(ego_states, dtype=np.float64)
    if states.ndim != 2 or not len(states) or states.shape[1] < 3:
        return []
    candidates: list[tuple[str, np.ndarray]] = []
    for lane_id, lane in map_polylines.items():
        if int(lane.get("type", -1)) not in {0, 4}:
            continue
        raw_lane_states = lane.get("states")
        lane_states = np.asarray(
            raw_lane_states if raw_lane_states is not None else [],
            dtype=np.float64,
        )
        if lane_states.ndim != 2 or len(lane_states) < 2 or lane_states.shape[1] < 3:
            continue
        candidates.append((str(lane_id), lane_states))

    selected: list[str] = []
    max_heading_error = math.radians(max_heading_error_degrees)
    for ego_state in states:
        best: tuple[float, str, float, float] | None = None
        for lane_id, lane_states in candidates:
            distances = np.linalg.norm(lane_states[:, :2] - ego_state[None, :2], axis=1)
            nearest = int(np.argmin(distances))
            distance = float(distances[nearest])
            heading_error = abs(_wrap_angle(float(lane_states[nearest, 2]) - float(ego_state[2])))
            score = distance + float(heading_weight_m) * heading_error
            candidate = (score, lane_id, distance, heading_error)
            if best is None or candidate < best:
                best = candidate
        if best is None or best[2] > max_distance_m or best[3] > max_heading_error:
            continue
        if best[1] not in selected:
            selected.append(best[1])
    return selected


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _infer_ego_route(
    data: dict[str, Any],
    map_polylines: dict[Any, dict[str, Any]],
    ego_state: np.ndarray,
) -> dict[str, Any]:
    """Summarize the route geometry used to keep text and controls consistent."""
    lane_candidates: list[tuple[float, str]] = []
    for lane_id, lane in map_polylines.items():
        if int(lane.get("type", -1)) not in {0, 4}:
            continue
        states = np.asarray(lane.get("states") if lane.get("states") is not None else [], dtype=np.float64)
        if states.ndim != 2 or len(states) < 2 or states.shape[1] < 3:
            continue
        distances = np.linalg.norm(states[:, :2] - ego_state[None, :2], axis=1)
        nearest = int(np.argmin(distances))
        heading_error = abs(_wrap_angle(float(states[nearest, 2]) - float(ego_state[2])))
        lane_candidates.append((float(distances[nearest]) + 4.0 * heading_error, str(lane_id)))
    if not lane_candidates:
        return {"maneuver": "unknown", "road_form": "intersection", "route_candidates": 0}

    start_lane = min(lane_candidates)[1]
    raw_routes = _mapping_value(data.get("routes") or {}, start_lane, []) or []
    routes = [list(route) for route in raw_routes if isinstance(route, (list, tuple)) and route]
    if not routes:
        route = [start_lane]
        seen = {start_lane}
        while len(route) < 12:
            lane = _mapping_value(map_polylines, route[-1], {}) or {}
            next_ids = [str(value) for value in lane.get("next_lanes_id") or []]
            next_id = next((value for value in next_ids if value not in seen), "")
            if not next_id:
                break
            route.append(next_id)
            seen.add(next_id)
        routes = [route]

    route_deltas: list[float] = []
    route_has_intersection: list[bool] = []
    route_intersection_distances: list[float] = []
    for route in routes:
        route_lanes = [
            _mapping_value(map_polylines, lane_id, {}) or {}
            for lane_id in route
        ]
        valid_states = [
            np.asarray(lane.get("states"), dtype=np.float64)
            for lane in route_lanes
            if lane.get("states") is not None
        ]
        valid_states = [states for states in valid_states if states.ndim == 2 and len(states) and states.shape[1] >= 3]
        if not valid_states:
            continue
        route_deltas.append(math.degrees(_wrap_angle(float(valid_states[-1][-1, 2]) - float(ego_state[2]))))
        route_has_intersection.append(any(int(lane.get("type", -1)) == 4 for lane in route_lanes))
        intersection_points = [
            states[:, :2]
            for lane, states in zip(route_lanes, valid_states)
            if int(lane.get("type", -1)) == 4 and states.shape[1] >= 2
        ]
        route_intersection_distances.append(
            min(
                (
                    float(np.min(np.linalg.norm(points - ego_state[None, :2], axis=1)))
                    for points in intersection_points
                ),
                default=float("inf"),
            )
        )

    maneuvers = []
    for delta in route_deltas:
        if delta >= 25.0:
            maneuvers.append("left_turn")
        elif delta <= -25.0:
            maneuvers.append("right_turn")
        else:
            maneuvers.append("straight")
    maneuver = maneuvers[0] if maneuvers and len(set(maneuvers)) == 1 else "unknown"
    forced_sharp_turn = bool(route_deltas) and all(abs(delta) >= 55.0 for delta in route_deltas)
    nearest_intersection_m = min(route_intersection_distances, default=float("inf"))
    intersection_ahead = math.isfinite(nearest_intersection_m) and nearest_intersection_m <= 90.0
    return {
        "start_lane_id": start_lane,
        "maneuver": maneuver,
        "road_form": (
            "t_junction"
            if forced_sharp_turn and intersection_ahead
            else "intersection"
            if intersection_ahead
            else "urban_road"
        ),
        "route_candidates": len(routes),
        "heading_deltas_degrees": [round(delta, 3) for delta in route_deltas],
        "contains_intersection_lane": any(route_has_intersection),
        "intersection_ahead": intersection_ahead,
        "nearest_route_intersection_m": (
            round(nearest_intersection_m, 3) if math.isfinite(nearest_intersection_m) else None
        ),
    }


def _write_signal_poles(
    scene_root: Path,
    clip_id: str,
    supports: list[Any],
    *,
    height_m: float = 4.05,
) -> int:
    labels = []
    for index, support in enumerate(supports):
        if isinstance(support, dict):
            center = list(support.get("base") or support.get("position") or [])
            arm_end = list(support.get("arm_end") or [])
        else:
            center = list(support)
            arm_end = []
        if len(center) < 2:
            continue
        x, y = float(center[0]), float(center[1])
        ground_z = float(center[2]) if len(center) >= 3 else 0.0
        vertices = [
            [x, y, ground_z],
            [x, y, ground_z + float(height_m)],
        ]
        if len(arm_end) >= 2 and math.hypot(float(arm_end[0]) - x, float(arm_end[1]) - y) > 0.25:
            vertices.append(
                [
                    float(arm_end[0]),
                    float(arm_end[1]),
                    ground_z + float(height_m),
                ]
            )
        labels.append(
            {
                "labelData": {
                    "shape3d": {
                        "polyline3d": {"vertices": vertices},
                        "attributes": [
                            {"name": "feature_id", "text": f"trafficwm-signal-pole-{index}"}
                        ],
                    }
                }
            }
        )
    tar_path = scene_root / "3d_poles" / f"{clip_id}.tar"
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    _write_tar_json(tar_path, f"{clip_id}.poles.json", {"labels": labels})
    return len(labels)


def _cuboid_center(label: dict[str, Any]) -> tuple[float, float, float] | None:
    vertices = (
        label.get("labelData", {})
        .get("shape3d", {})
        .get("cuboid3d", {})
        .get("vertices", [])
    )
    if len(vertices) != 8:
        return None
    points = np.asarray(vertices, dtype=np.float64)
    if points.shape != (8, 3) or not np.all(np.isfinite(points)):
        return None
    center = points.mean(axis=0)
    return float(center[0]), float(center[1]), float(center[2])


def _shift_cuboid_label(label: dict[str, Any], target_xy: tuple[float, float]) -> dict[str, Any]:
    result = json.loads(json.dumps(label))
    vertices = (
        result.get("labelData", {})
        .get("shape3d", {})
        .get("cuboid3d", {})
        .get("vertices", [])
    )
    center = _cuboid_center(result)
    if center is None:
        return result
    dx, dy = float(target_xy[0]) - center[0], float(target_xy[1]) - center[1]
    for vertex in vertices:
        vertex[0] = float(vertex[0]) + dx
        vertex[1] = float(vertex[1]) + dy
    return result


def _merge_light_state(states: list[str]) -> str:
    priority = ("RED", "YELLOW", "GREEN", "UNKNOWN")
    normalized = [str(item or "UNKNOWN").strip().upper() for item in states]
    for state in priority:
        if state in normalized:
            return state
    return "UNKNOWN"


def _cluster_traffic_lights(scene_root: Path, clip_id: str, *, radius_m: float = 6.0) -> dict[str, Any]:
    lights_tar = scene_root / "3d_traffic_lights" / f"{clip_id}.tar"
    status_tar = scene_root / "3d_traffic_lights_status" / f"{clip_id}.tar"
    if not lights_tar.is_file():
        return {"before": 0, "after": 0, "strategy": "spatial-fallback"}
    light_member, light_payload = _read_tar_json(lights_tar)
    labels = list(light_payload.get("labels") or [])
    centers = [_cuboid_center(label) for label in labels]
    valid = [(index, center) for index, center in enumerate(centers) if center is not None]
    if len(valid) <= 1:
        return {"before": len(labels), "after": len(labels), "strategy": "spatial-fallback"}

    clusters: list[list[int]] = []
    cluster_centers: list[tuple[float, float, float]] = []
    for index, center in valid:
        assert center is not None
        assigned = False
        for cluster_index, cluster_xy in enumerate(cluster_centers):
            if math.hypot(center[0] - cluster_xy[0], center[1] - cluster_xy[1]) <= radius_m:
                clusters[cluster_index].append(index)
                xs = [centers[item][0] for item in clusters[cluster_index] if centers[item] is not None]
                ys = [centers[item][1] for item in clusters[cluster_index] if centers[item] is not None]
                zs = [centers[item][2] for item in clusters[cluster_index] if centers[item] is not None]
                cluster_centers[cluster_index] = (
                    float(np.mean(xs)),
                    float(np.mean(ys)),
                    float(np.mean(zs)),
                )
                assigned = True
                break
        if not assigned:
            clusters.append([index])
            cluster_centers.append((center[0], center[1], center[2]))

    if len(clusters) == len(valid):
        return {"before": len(labels), "after": len(labels), "strategy": "spatial-fallback"}

    status_payload: dict[str, Any] = {}
    traffic_states: dict[str, dict[str, Any]] = {}
    if status_tar.is_file():
        status_member, status_payload = _read_tar_json(status_tar)
        traffic_states = dict(status_payload.get("traffic_light_states") or {})
    else:
        status_member = "aggregated_states.json"

    next_labels: list[dict[str, Any]] = []
    next_states: dict[str, dict[str, Any]] = {}
    for cluster_index, source_indices in enumerate(clusters):
        representative = source_indices[0]
        cluster_label = _shift_cuboid_label(
            labels[representative], cluster_centers[cluster_index][:2]
        )
        feature_id = f"trafficwm-signal-cluster-{cluster_index}"
        _set_feature_id(cluster_label, feature_id)
        next_labels.append(cluster_label)

        source_sequences = [
            list((traffic_states.get(str(index)) or {}).get("state") or [])
            for index in source_indices
        ]
        max_len = max((len(item) for item in source_sequences), default=0)
        merged = [
            _merge_light_state(
                [
                    sequence[frame] if frame < len(sequence) else "UNKNOWN"
                    for sequence in source_sequences
                ]
            )
            for frame in range(max_len)
        ]
        next_states[str(cluster_index)] = {"feature_id": feature_id, "state": merged}

    light_payload["labels"] = next_labels
    status_payload["traffic_light_states"] = next_states
    _write_tar_json(lights_tar, f"{clip_id}.traffic_lights.json", light_payload)
    _write_tar_json(status_tar, status_member, status_payload)
    pole_bases = [
        (x, y, z - 4.5)
        for x, y, z in cluster_centers[: len(next_labels)]
    ]
    pole_count = _write_signal_poles(scene_root, clip_id, pole_bases)
    return {
        "before": len(labels),
        "after": len(next_labels),
        "pole_count": pole_count,
        "strategy": "spatial-fallback",
        "radius_m": radius_m,
    }


def _consolidate_traffic_lights(
    scene_root: Path,
    clip_id: str,
    map_state: dict[str, Any],
    *,
    pole_radius_m: float = 4.0,
) -> dict[str, Any]:
    lights_tar = scene_root / "3d_traffic_lights" / f"{clip_id}.tar"
    status_tar = scene_root / "3d_traffic_lights_status" / f"{clip_id}.tar"
    semantic_signals = list(map_state.get("traffic_signals") or [])
    if not lights_tar.is_file() or not status_tar.is_file() or not semantic_signals:
        return _cluster_traffic_lights(scene_root, clip_id)

    light_member, light_payload = _read_tar_json(lights_tar)
    status_member, status_payload = _read_tar_json(status_tar)
    labels = list(light_payload.get("labels") or [])
    traffic_states = dict(status_payload.get("traffic_light_states") or {})
    label_by_feature = {
        feature_id: label
        for label in labels
        if (feature_id := _feature_id(label))
    }
    state_by_feature: dict[str, list[str]] = {}
    for index, value in traffic_states.items():
        feature_id = str(value.get("feature_id") or "")
        if not feature_id:
            try:
                feature_id = _feature_id(labels[int(index)])
            except (IndexError, TypeError, ValueError):
                feature_id = ""
        if feature_id:
            state_by_feature[feature_id] = list(value.get("state") or [])

    candidates: list[dict[str, Any]] = []
    for signal in semantic_signals:
        position = list(signal.get("position") or [])
        if len(position) < 2:
            continue
        try:
            point = (float(position[0]), float(position[1]))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in point):
            continue
        source_keys = [
            str(key)
            for key in signal.get("state_keys") or []
            if str(key) in label_by_feature
        ]
        if not source_keys:
            continue
        movement_groups = signal.get("movement_groups") or {}
        semantic_head_positions = {
            str(item.get("movement") or "combined"): tuple(
                float(value) for value in list(item.get("position") or [])[:2]
            )
            for item in signal.get("head_positions") or []
            if len(item.get("position") or []) >= 2
        }
        heads = []
        if isinstance(movement_groups, dict):
            for movement, keys in sorted(movement_groups.items(), key=lambda item: str(item[0])):
                head_keys = [
                    str(key)
                    for key in keys or []
                    if str(key) in label_by_feature
                ]
                if head_keys:
                    heads.append(
                        {
                            "movement": str(movement),
                            "source_keys": head_keys,
                            "position": semantic_head_positions.get(str(movement)),
                        }
                    )
        if not heads:
            heads.append(
                {
                    "movement": "combined",
                    "source_keys": source_keys,
                    "position": semantic_head_positions.get("combined"),
                }
            )
        arm_end = list(signal.get("mast_arm_end") or [])
        candidates.append(
            {
                "id": str(signal.get("id") or f"signal-{len(candidates)}"),
                "position": point,
                "ground_z": float(position[2]) if len(position) >= 3 else 0.0,
                "source_keys": source_keys,
                "heading": float(signal.get("heading") or 0.0),
                "heads": heads,
                "arm_end": (
                    (float(arm_end[0]), float(arm_end[1]))
                    if len(arm_end) >= 2
                    else None
                ),
            }
        )
    if not candidates:
        return _cluster_traffic_lights(scene_root, clip_id)

    clusters: list[list[dict[str, Any]]] = []
    centers: list[tuple[float, float, float]] = []
    for candidate in candidates:
        selected_index = next(
            (
                index
                for index, center in enumerate(centers)
                if math.hypot(
                    candidate["position"][0] - center[0],
                    candidate["position"][1] - center[1],
                )
                <= pole_radius_m
            ),
            None,
        )
        if selected_index is None:
            clusters.append([candidate])
            centers.append(
                (
                    candidate["position"][0],
                    candidate["position"][1],
                    candidate["ground_z"],
                )
            )
            continue
        clusters[selected_index].append(candidate)
        centers[selected_index] = (
            float(np.mean([item["position"][0] for item in clusters[selected_index]])),
            float(np.mean([item["position"][1] for item in clusters[selected_index]])),
            float(np.mean([item["ground_z"] for item in clusters[selected_index]])),
        )

    next_labels: list[dict[str, Any]] = []
    next_states: dict[str, dict[str, Any]] = {}
    used_source_keys: set[str] = set()
    pole_supports: list[dict[str, Any]] = []
    heads_per_pole: list[int] = []
    for cluster_index, cluster in enumerate(clusters):
        head_groups: dict[str, dict[str, Any]] = {}
        for candidate in cluster:
            for head in candidate["heads"]:
                movement = str(head["movement"] or "combined")
                group = head_groups.setdefault(
                    movement,
                    {"source_keys": [], "positions": []},
                )
                for source_key in head["source_keys"]:
                    if source_key not in group["source_keys"]:
                        group["source_keys"].append(source_key)
                if head.get("position") is not None:
                    group["positions"].append(head["position"])
        head_groups = {
            movement: group
            for movement, group in sorted(head_groups.items())
            if group["source_keys"]
        }
        if not head_groups:
            continue
        heads_per_pole.append(len(head_groups))
        headings = [float(candidate["heading"]) for candidate in cluster]
        heading = math.atan2(
            sum(math.sin(value) for value in headings),
            sum(math.cos(value) for value in headings),
        )
        normal = (-math.sin(heading), math.cos(heading))
        head_targets: list[tuple[float, float]] = []
        for head_index, (movement, group) in enumerate(head_groups.items()):
            source_keys = group["source_keys"]
            used_source_keys.update(source_keys)
            if group["positions"]:
                target_xy = (
                    float(np.mean([item[0] for item in group["positions"]])),
                    float(np.mean([item[1] for item in group["positions"]])),
                )
            else:
                source_centers = [
                    center
                    for source_key in source_keys
                    if (center := _cuboid_center(label_by_feature[source_key])) is not None
                ]
                if source_centers:
                    target_xy = (
                        float(np.mean([item[0] for item in source_centers])),
                        float(np.mean([item[1] for item in source_centers])),
                    )
                else:
                    lateral_offset = (head_index - (len(head_groups) - 1) * 0.5) * 0.55
                    target_xy = (
                        centers[cluster_index][0] + normal[0] * lateral_offset,
                        centers[cluster_index][1] + normal[1] * lateral_offset,
                    )
            head_targets.append(target_xy)
            feature_id = f"trafficwm-signal-pole-{cluster_index}-head-{head_index}-{movement}"
            label = _shift_cuboid_label(label_by_feature[source_keys[0]], target_xy)
            _set_feature_id(label, feature_id)
            next_labels.append(label)

            sequences = [state_by_feature.get(key, []) for key in source_keys]
            max_len = max((len(sequence) for sequence in sequences), default=0)
            merged = [
                _merge_light_state(
                    [
                        sequence[frame_index] if frame_index < len(sequence) else "UNKNOWN"
                        for sequence in sequences
                    ]
                )
                for frame_index in range(max_len)
            ]
            next_states[str(len(next_states))] = {
                "feature_id": feature_id,
                "state": merged,
            }

        semantic_arm_ends = [
            candidate["arm_end"]
            for candidate in cluster
            if candidate.get("arm_end") is not None
        ]
        if semantic_arm_ends:
            arm_end = [
                float(np.mean([item[0] for item in semantic_arm_ends])),
                float(np.mean([item[1] for item in semantic_arm_ends])),
            ]
        elif head_targets:
            base_xy = centers[cluster_index][:2]
            farthest = max(
                head_targets,
                key=lambda item: math.hypot(item[0] - base_xy[0], item[1] - base_xy[1]),
            )
            arm_end = [
                farthest[0] + normal[0] * 0.35,
                farthest[1] + normal[1] * 0.35,
            ]
        else:
            arm_end = [
                centers[cluster_index][0] + normal[0] * 4.0,
                centers[cluster_index][1] + normal[1] * 4.0,
            ]
        pole_supports.append(
            {
                "base": centers[cluster_index],
                "arm_end": arm_end,
            }
        )

    if not next_labels:
        return _cluster_traffic_lights(scene_root, clip_id)
    light_payload["labels"] = next_labels
    status_payload["traffic_light_states"] = next_states
    _write_tar_json(lights_tar, f"{clip_id}.traffic_lights.json", light_payload)
    _write_tar_json(status_tar, status_member, status_payload)
    pole_count = _write_signal_poles(scene_root, clip_id, pole_supports)
    return {
        "before": len(labels),
        "semantic_groups": len(candidates),
        "after": len(next_labels),
        "source_keys_used": len(used_source_keys),
        "pole_count": pole_count,
        "heads_per_pole": heads_per_pole,
        "strategy": "movement-heads-and-pole-position",
        "radius_m": pole_radius_m,
    }


def export_citynde_scene(
    input_path: Path,
    output_root: Path,
    *,
    clip_id: str,
    source_steps: int,
    source_fps: float = 10.0,
    target_fps: int = 30,
    start_step: int | None = None,
    ego_id: str | int | None = None,
    map_state: dict[str, Any] | None = None,
    map_radius_m: float | None = None,
    agent_radius_m: float | None = None,
    converter_path: Path | None = None,
) -> dict[str, Any]:
    converter_path = converter_path or Path(
        os.environ.get(
            "TRAFFICWM_RECORDING_SCENE_CONVERTER",
            str(Path(__file__).with_name("recording_scene_converter.py")),
        )
    )
    if not converter_path.is_file():
        raise FileNotFoundError(f"Traffic recording scene converter not found: {converter_path}")
    converter = _load_converter(converter_path)
    map_radius_m = float(
        map_radius_m
        if map_radius_m is not None
        else os.environ.get("TRAFFICWM_COSMOS_MAP_RADIUS_M", DEFAULT_MAP_RADIUS_M)
    )
    agent_radius_m = float(
        agent_radius_m
        if agent_radius_m is not None
        else os.environ.get("TRAFFICWM_COSMOS_AGENT_RADIUS_M", DEFAULT_AGENT_RADIUS_M)
    )
    if not math.isfinite(map_radius_m) or map_radius_m <= 0.0:
        raise ValueError("map_radius_m must be a positive finite number")
    if not math.isfinite(agent_radius_m) or agent_radius_m <= 0.0:
        raise ValueError("agent_radius_m must be a positive finite number")
    intrinsics, extrinsics = _calibration(output_root / "calibration")
    with input_path.open("rb") as stream:
        data = _with_pedestrian_tracks(pickle.load(stream))
    converter.OBJECT_TYPES = {
        str(actor_id): _cosmos_object_type(data, actor_id)
        for actor_id in (data.get("vehicle_static_attribute") or {})
    }
    converter_loader = converter.load_trusted_pickle
    converter.load_trusted_pickle = lambda path: (
        data if Path(path).resolve() == input_path.resolve() else converter_loader(path)
    )
    ids = data.get("vehicle_id_per_step") or []
    if not ids:
        raise ValueError("Warmup recording has no vehicle available for the camera rig")
    source_steps = int(source_steps)
    if source_steps < 2 or source_steps > len(ids):
        raise ValueError(f"Requested {source_steps} source steps from a {len(ids)} step recording")
    start_step = max(0, len(ids) - source_steps) if start_step is None else int(start_step)
    if start_step < 0 or start_step + source_steps > len(ids) or not ids[start_step]:
        raise ValueError("Requested source window has no vehicle available for the camera rig")
    requested_ego_id = ego_id
    window_ids = ids[start_step : start_step + source_steps]
    persistent_ids = {str(item) for item in window_ids[0]}
    for step_ids in window_ids[1:]:
        persistent_ids.intersection_update(str(item) for item in step_ids)
    motorized_ids = sorted(
        actor_id
        for actor_id in persistent_ids
        if _cosmos_object_type(data, actor_id) not in {"Pedestrian", "Cyclist"}
    )
    if not motorized_ids:
        raise ValueError("Source window has no persistent motorized actor for the Cosmos camera rig")
    selected_ego_id = str(requested_ego_id or "")
    if selected_ego_id not in motorized_ids:
        selected_ego_id = motorized_ids[0]
    ego_id = next(item for item in ids[start_step] if str(item) == selected_ego_id)
    warmup_frames_path = input_path.with_suffix(".json")
    if requested_ego_id is None and warmup_frames_path.is_file():
        try:
            warmup_frames = json.loads(warmup_frames_path.read_text(encoding="utf-8"))
            requested_ego = ((warmup_frames or [{}])[0].get("ego") or {}).get("id")
            requested_text = str(requested_ego or "")
            if requested_text in motorized_ids:
                ego_id = next((item for item in ids[start_step] if str(item) == requested_text), ego_id)
        except (OSError, ValueError, TypeError):
            pass
    config = converter.ConversionConfig(
        input_path=str(input_path.resolve()),
        output_root=str(output_root.resolve()),
        clip_id=clip_id,
        ego_id=str(ego_id),
        source_fps=float(source_fps),
        target_fps=int(target_fps),
        start_step=start_step,
        source_steps=source_steps,
        map_radius_m=map_radius_m,
        map_max_segment_length_m=3.0,
        agent_radius_m=agent_radius_m,
        traffic_light_height_m=4.5,
        waymo_intrinsics=str(intrinsics),
        waymo_extrinsics=str(extrinsics),
    )
    report = converter.convert(config)
    state_steps = data.get("vehicle_state_per_step") or []
    ego_path = []
    ego_lane_match_states = []
    for step_ids, step_states in zip(
        ids[start_step : start_step + source_steps],
        state_steps[start_step : start_step + source_steps],
    ):
        ego_index = next(
            (index for index, vehicle_id in enumerate(step_ids) if str(vehicle_id) == str(ego_id)),
            None,
        )
        if ego_index is not None and ego_index < len(step_states):
            ego_state = step_states[ego_index]
            ego_path.append([float(ego_state[0]), float(ego_state[1])])
            ego_lane_match_states.append(
                [float(ego_state[0]), float(ego_state[1]), float(ego_state[2])]
            )
    ego_xy = np.asarray(ego_path, dtype=np.float64)

    raw_polylines = (data.get("map") or {}).get("polyline") or {}
    ego_state_at_start = np.asarray(
        state_steps[start_step][
            next(
                index
                for index, actor_id in enumerate(ids[start_step])
                if str(actor_id) == str(ego_id)
            )
        ],
        dtype=np.float64,
    )
    ego_route_report = _infer_ego_route(data, raw_polylines, ego_state_at_start)
    map_types = {
        str(polyline_id): int(polyline.get("type", -1))
        for polyline_id, polyline in raw_polylines.items()
        if isinstance(polyline, dict)
    }
    calibration_report = _write_official_ftheta_intrinsics(output_root, clip_id)
    lane_style_report = _style_citynde_lanelines(output_root, clip_id, map_types)
    matched_ego_lane_ids = _match_ego_path_lane_ids(
        raw_polylines,
        np.asarray(ego_lane_match_states, dtype=np.float64),
    )
    lane_topology_report = _write_citynde_lanes(
        output_root,
        clip_id,
        raw_polylines,
        ego_xy=ego_xy,
        radius_m=map_radius_m,
        selected_lane_ids=set(matched_ego_lane_ids),
    )
    lane_topology_report["matched_lane_ids"] = matched_ego_lane_ids
    semantic_feature_report = _write_semantic_map_features(
        output_root,
        clip_id,
        map_state or {},
        ego_xy=ego_xy,
        radius_m=map_radius_m,
    )
    light_cluster_report = _consolidate_traffic_lights(
        output_root,
        clip_id,
        map_state or {},
    )
    report_data = dict(vars(report))
    report_data["source_start_step"] = start_step
    active_ids = {
        str(vehicle_id)
        for step_ids in ids[start_step : start_step + source_steps]
        for vehicle_id in step_ids
    }
    report_data["active_source_vehicle_tracks"] = len(active_ids)
    report_data["active_source_vehicle_observations"] = sum(
        len(step_ids) for step_ids in ids[start_step : start_step + source_steps]
    )
    object_type_counts: dict[str, int] = {}
    for actor_id in active_ids:
        object_type = _cosmos_object_type(data, actor_id)
        object_type_counts[object_type] = object_type_counts.get(object_type, 0) + 1
    report_data["source_object_type_counts"] = object_type_counts
    report_data["traffic_light_clustering"] = light_cluster_report
    report_data["exported_traffic_lights"] = int(light_cluster_report.get("after") or report_data.get("exported_traffic_lights", 0) or 0)
    report_data["base_exported_lane_lines"] = int(report_data.get("exported_lane_lines", 0) or 0)
    report_data["semantic_features"] = semantic_feature_report
    report_data["semantic_line_count"] = 0
    report_data["exported_lane_lines"] = report_data["base_exported_lane_lines"]
    report_data["map_radius_m"] = map_radius_m
    report_data["agent_radius_m"] = agent_radius_m
    report_data["lane_line_styles"] = lane_style_report
    report_data["lane_topology"] = lane_topology_report
    report_data["ego_route"] = ego_route_report
    report_data["exported_lanes"] = int(lane_topology_report["lanes"])
    report_data["semantic_quality"] = (map_state or {}).get("semantic_quality") or {}
    report_data["camera_calibration"] = calibration_report
    report_data["camera_view_keys"] = {camera: VIEW_KEYS[camera] for camera in CAMERAS}
    (output_root / "trafficwm_export_report.json").write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report_data
