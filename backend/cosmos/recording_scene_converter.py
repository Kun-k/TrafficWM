#!/usr/bin/env python3
"""Convert a normalized traffic pickle recording to Cosmos RDS-HQ scene data.

The source pickle format used by the recording in this directory contains:

* ``map.polyline``: vector-map polylines. ``states`` columns are ``x, y, heading``.
* ``vehicle_state_per_step``: ``x, y, heading, vx, vy, ax, ay``.
* ``vehicle_static_attribute``: ``length, width, height``.
* ``dynamic_polyline_*_per_step``: traffic-light ids and one-hot
  ``green, yellow, red, unknown`` states.

The output is the RDS-HQ/WebDataset directory layout understood by the
Cosmos-Transfer2.5 world-scenario loader. Camera calibration and camera poses
use the five-camera Waymo pinhole convention already bundled with
the TrafficWM Cosmos integration.

Pickle files can execute code while loading. Only use this tool with trusted
recordings.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import pickle
import tarfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

REPO_ROOT = Path(__file__).resolve().parents[2]
COSMOS_ASSET_ROOT = REPO_ROOT / "assets" / "cosmos"
WAYMO_EXAMPLE_ID = "10017090168044687777_6380_000_6400_000"
DEFAULT_WAYMO_INTRINSICS = COSMOS_ASSET_ROOT / f"waymo_pinhole_intrinsic_{WAYMO_EXAMPLE_ID}.npy"
DEFAULT_WAYMO_EXTRINSICS = (
    COSMOS_ASSET_ROOT / f"waymo_camera_name_to_camera_to_vehicle_{WAYMO_EXAMPLE_ID}.npy"
)

WAYMO_CAMERA_NAMES = ("front", "front_left", "front_right", "side_left", "side_right")
SOURCE_STATE_COLUMNS = ("x", "y", "heading", "vx", "vy", "ax", "ay")
TRAFFIC_LIGHT_STATE_NAMES = ("GREEN", "YELLOW", "RED", "UNKNOWN")
# Match the physical housing used by the official ClipGT exporter. The former
# 0.18 m-wide cuboid was valid geometry but made its state color disappear at
# normal driving distances after 720p projection and H.264 encoding.
TRAFFIC_LIGHT_HEAD_DIMENSIONS_M = (0.35, 0.75, 1.25)

# CityNDE MapPolyline semantics:
#   0: lane center, 4: signal-controlled/intersection lane center.
# The remaining types are line-like map geometry. The recording format does not
# retain an authoritative Waymo semantic name for each of them. The mapping below
# preserves all lines while keeping the strong road-edge-looking type 2 separate.
LANE_LINE_TYPES = frozenset({0, 1, 3, 4})
ROAD_BOUNDARY_TYPES = frozenset({2})

ArrayF = NDArray[np.floating[Any]]


@dataclass(frozen=True)
class ConversionConfig:
    input_path: str
    output_root: str
    clip_id: str
    ego_id: str
    source_fps: float
    target_fps: int
    start_step: int
    source_steps: int
    map_radius_m: float
    map_max_segment_length_m: float
    agent_radius_m: float
    traffic_light_height_m: float
    waymo_intrinsics: str
    waymo_extrinsics: str


@dataclass
class ConversionReport:
    clip_id: str
    input_steps: int
    output_frames: int
    duration_seconds: float
    ego_id: str
    cameras: list[str]
    source_vehicle_tracks: int
    exported_object_tracks: int
    exported_object_observations: int
    exported_lane_lines: int
    exported_road_boundaries: int
    removed_map_jump_segments: int
    source_traffic_light_observations: int
    exported_traffic_lights: int
    stabilized_low_speed_heading_observations: int
    warnings: list[str]


def load_trusted_pickle(path: Path) -> dict[str, Any]:
    """Load a trusted pickle and validate its top-level shape."""
    with path.open("rb") as stream:
        data = pickle.load(stream)
    if not isinstance(data, dict):
        raise TypeError(f"Expected pickle root to be dict, got {type(data)!r}")

    required = {
        "map",
        "vehicle_id_per_step",
        "vehicle_state_per_step",
        "vehicle_static_attribute",
    }
    missing = sorted(required.difference(data))
    if missing:
        raise KeyError(f"Input pickle is missing required keys: {missing}")
    return data


def resolve_id(requested: str | None, available: Iterable[Any]) -> Any:
    """Resolve a CLI string id against mixed int/string pickle ids."""
    available_list = list(available)
    if not available_list:
        raise ValueError("No ids are available")
    if requested is None:
        return available_list[0]
    for candidate in available_list:
        if str(candidate) == str(requested):
            return candidate
    preview = ", ".join(str(value) for value in available_list[:20])
    raise ValueError(f"Unknown id {requested!r}; first available ids: {preview}")


def pose_matrix(x: float, y: float, yaw: float, z: float = 0.0) -> NDArray[np.float64]:
    """Return an FLU object/vehicle-to-world transform."""
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    pose = np.eye(4, dtype=np.float64)
    pose[:2, :2] = ((cosine, -sine), (sine, cosine))
    pose[:3, 3] = (x, y, z)
    return pose


def camera_flu_to_opencv(camera_to_world_flu: ArrayF) -> NDArray[np.float64]:
    """Change camera basis from FLU (x forward) to OpenCV RDF (z forward)."""
    result = np.empty((4, 4), dtype=np.float64)
    result[:, 0] = -camera_to_world_flu[:, 1]  # RDF right = -FLU left
    result[:, 1] = -camera_to_world_flu[:, 2]  # RDF down = -FLU up
    result[:, 2] = camera_to_world_flu[:, 0]  # RDF forward = FLU forward
    result[:, 3] = camera_to_world_flu[:, 3]
    return result


def interpolate_angle(start: float, end: float, alpha: float) -> float:
    """Interpolate an angle along its shortest wrapped arc."""
    delta = (end - start + math.pi) % (2.0 * math.pi) - math.pi
    return start + alpha * delta


def target_frame_samples(
    source_steps: int,
    source_fps: float,
    target_fps: int,
) -> list[tuple[int, int, float]]:
    """Map every target frame to bracketing local source-frame indices."""
    if source_steps < 2:
        raise ValueError("At least two source steps are required")
    duration = (source_steps - 1) / source_fps
    output_frames = int(round(duration * target_fps)) + 1
    samples: list[tuple[int, int, float]] = []
    for target_index in range(output_frames):
        source_position = target_index * source_fps / target_fps
        left = min(int(math.floor(source_position)), source_steps - 1)
        right = min(left + 1, source_steps - 1)
        alpha = source_position - left if right != left else 0.0
        samples.append((left, right, alpha))
    return samples


def interpolate_state(left: ArrayF, right: ArrayF, alpha: float) -> NDArray[np.float64]:
    """Interpolate a seven-column road-user state."""
    result = (1.0 - alpha) * np.asarray(left, dtype=np.float64) + alpha * np.asarray(
        right, dtype=np.float64
    )
    result[2] = interpolate_angle(float(left[2]), float(right[2]), alpha)
    return result


def build_step_vehicles(
    data: Mapping[str, Any],
    start_step: int,
    source_steps: int,
) -> list[dict[Any, NDArray[np.float64]]]:
    """Convert sparse per-step ids/states into dictionaries."""
    id_steps = data["vehicle_id_per_step"]
    state_steps = data["vehicle_state_per_step"]
    end_step = start_step + source_steps
    if start_step < 0 or end_step > len(id_steps):
        raise IndexError(
            f"Requested source range [{start_step}, {end_step}) is outside "
            f"the recording with {len(id_steps)} steps"
        )

    result: list[dict[Any, NDArray[np.float64]]] = []
    for absolute_step in range(start_step, end_step):
        ids = list(id_steps[absolute_step])
        states = np.asarray(state_steps[absolute_step], dtype=np.float64)
        if states.shape != (len(ids), 7):
            raise ValueError(
                f"Step {absolute_step}: expected states shape ({len(ids)}, 7), "
                f"got {states.shape}"
            )
        result.append({vehicle_id: states[index] for index, vehicle_id in enumerate(ids)})
    return result


def stabilize_low_speed_headings(
    step_vehicles: Sequence[Mapping[Any, ArrayF]],
    *,
    speed_threshold_mps: float = 0.5,
) -> tuple[list[dict[Any, NDArray[np.float64]]], int]:
    """Hold the last reliable heading when near-zero velocity makes yaw noisy."""
    normalized = [
        {
            actor_id: np.asarray(state, dtype=np.float64).copy()
            for actor_id, state in vehicles.items()
        }
        for vehicles in step_vehicles
    ]
    actor_ids = {actor_id for vehicles in normalized for actor_id in vehicles}
    changed = 0
    for actor_id in actor_ids:
        observations = [
            (index, vehicles[actor_id])
            for index, vehicles in enumerate(normalized)
            if actor_id in vehicles
        ]
        reliable_headings = {
            index: float(state[2])
            for index, state in observations
            if np.isfinite(state[2])
            and float(np.linalg.norm(state[3:5])) >= speed_threshold_mps
        }
        if reliable_headings:
            first_reliable_index = min(reliable_headings)
            held_heading = reliable_headings[first_reliable_index]
        else:
            first_finite = next(
                (float(state[2]) for _, state in observations if np.isfinite(state[2])),
                0.0,
            )
            first_reliable_index = observations[0][0] if observations else 0
            held_heading = first_finite

        for index, state in observations:
            speed = float(np.linalg.norm(state[3:5]))
            if index in reliable_headings:
                held_heading = reliable_headings[index]
                continue
            replacement = (
                reliable_headings[first_reliable_index]
                if index < first_reliable_index and reliable_headings
                else held_heading
            )
            if speed < speed_threshold_mps and (
                not np.isfinite(state[2])
                or abs(interpolate_angle(float(state[2]), replacement, 1.0) - float(state[2]))
                > 1e-9
            ):
                state[2] = replacement
                changed += 1
    return normalized, changed


def interpolate_ego_states(
    step_vehicles: Sequence[Mapping[Any, ArrayF]],
    ego_id: Any,
    samples: Sequence[tuple[int, int, float]],
) -> list[NDArray[np.float64]]:
    """Interpolate ego states and require continuous ego presence."""
    missing = [index for index, vehicles in enumerate(step_vehicles) if ego_id not in vehicles]
    if missing:
        preview = ", ".join(str(index) for index in missing[:20])
        raise ValueError(f"Ego id {ego_id!r} is absent at local source steps: {preview}")

    return [
        interpolate_state(step_vehicles[left][ego_id], step_vehicles[right][ego_id], alpha)
        for left, right, alpha in samples
    ]


def interpolate_objects_at_frame(
    step_vehicles: Sequence[Mapping[Any, ArrayF]],
    static_attributes: Mapping[Any, Any],
    ego_id: Any,
    left_index: int,
    right_index: int,
    alpha: float,
    selected_object_ids: set[Any],
) -> dict[str, dict[str, Any]]:
    """Interpolate preselected objects that exist in both bracketing frames."""
    left_objects = step_vehicles[left_index]
    right_objects = step_vehicles[right_index]
    if left_index == right_index or alpha <= 1e-9:
        common_ids = set(left_objects).intersection(selected_object_ids)
    else:
        common_ids = set(left_objects).intersection(right_objects, selected_object_ids)

    result: dict[str, dict[str, Any]] = {}
    for object_id in sorted(common_ids, key=str):
        if object_id == ego_id:
            continue
        if object_id not in static_attributes:
            continue

        if left_index == right_index or alpha <= 1e-9:
            state = np.asarray(left_objects[object_id], dtype=np.float64)
        else:
            state = interpolate_state(
                left_objects[object_id],
                right_objects[object_id],
                alpha,
            )

        dimensions = np.asarray(static_attributes[object_id], dtype=np.float64).reshape(-1)
        if dimensions.shape != (3,) or np.any(dimensions <= 0):
            continue
        length, width, height = dimensions
        transform = pose_matrix(float(state[0]), float(state[1]), float(state[2]), height / 2.0)
        speed = float(np.linalg.norm(state[3:5]))
        result[str(object_id)] = {
            "object_to_world": transform.tolist(),
            "object_lwh": [float(length), float(width), float(height)],
            "object_is_moving": speed > 0.2,
            "object_type": "Car",
        }
    return result


def select_object_tracks(
    step_vehicles: Sequence[Mapping[Any, ArrayF]],
    static_attributes: Mapping[Any, Any],
    ego_id: Any,
    agent_radius_m: float,
) -> set[Any]:
    """Select complete clip tracks whose minimum ego distance is within the radius.

    Applying the radius once per track avoids objects blinking on and off when
    they oscillate around the clipping boundary.
    """
    selected: set[Any] = set()
    for vehicles in step_vehicles:
        ego_state = vehicles[ego_id]
        ego_xy = np.asarray(ego_state[:2], dtype=np.float64)
        for object_id, state in vehicles.items():
            if object_id == ego_id or object_id not in static_attributes:
                continue
            if np.linalg.norm(np.asarray(state[:2], dtype=np.float64) - ego_xy) <= agent_radius_m:
                selected.add(object_id)
    return selected


def points_xyz(polyline_info: Mapping[str, Any]) -> NDArray[np.float64]:
    """Convert CityNDE x/y/heading map states to Cosmos x/y/z points."""
    states = np.asarray(polyline_info["states"], dtype=np.float64)
    if states.ndim != 2 or states.shape[0] < 2 or states.shape[1] < 2:
        return np.empty((0, 3), dtype=np.float64)
    return np.column_stack((states[:, 0], states[:, 1], np.zeros(len(states))))


def split_polyline_at_jumps(
    points: ArrayF,
    max_segment_length_m: float,
    headings: ArrayF | None = None,
    max_heading_error_degrees: float = 60.0,
) -> tuple[list[NDArray[np.float64]], int]:
    """Split long segments only when their direction disagrees with road headings.

    CityNDE road boundaries can legitimately use two vertices tens of metres
    apart, so point distance alone is not evidence of a broken connection.
    """
    points_array = np.asarray(points, dtype=np.float64)
    if len(points_array) < 2:
        return [], 0
    if max_segment_length_m <= 0:
        raise ValueError("map_max_segment_length_m must be positive")

    delta = np.diff(points_array[:, :2], axis=0)
    distances = np.linalg.norm(delta, axis=1)
    invalid = ~np.isfinite(distances)
    long_segment = distances > max_segment_length_m
    if headings is None:
        invalid |= long_segment
    else:
        heading_array = np.asarray(headings, dtype=np.float64).reshape(-1)
        if len(heading_array) != len(points_array):
            raise ValueError("headings length must match points length")
        segment_heading = np.arctan2(delta[:, 1], delta[:, 0])
        average_heading = np.arctan2(
            np.sin(heading_array[:-1]) + np.sin(heading_array[1:]),
            np.cos(heading_array[:-1]) + np.cos(heading_array[1:]),
        )
        heading_error = np.abs((segment_heading - average_heading + np.pi) % (2.0 * np.pi) - np.pi)
        # Some map polylines are stored in reverse order.
        heading_error = np.minimum(heading_error, np.pi - heading_error)
        invalid |= long_segment & (heading_error > np.deg2rad(max_heading_error_degrees))

    jump_indices = np.flatnonzero(invalid)
    chunks: list[NDArray[np.float64]] = []
    start = 0
    for jump_index in jump_indices:
        end = int(jump_index) + 1
        if end - start >= 2:
            chunks.append(points_array[start:end])
        start = end
    if len(points_array) - start >= 2:
        chunks.append(points_array[start:])
    return chunks, len(jump_indices)


def polyline_is_near_path(
    points: ArrayF,
    ego_xy: ArrayF,
    radius_m: float,
) -> bool:
    """Return whether any point is within radius of the ego path."""
    if not len(points):
        return False
    # Source clips are short (normally 41 poses), so this bounded matrix is
    # smaller and more reliable than a dependency on a spatial-index package.
    delta = points[:, None, :2] - ego_xy[None, :, :2]
    return bool(np.any(np.sum(delta * delta, axis=-1) <= radius_m * radius_m))


def lane_line_label(
    feature_id: Any,
    points: ArrayF,
    map_type: int,
) -> dict[str, Any]:
    """Build an RDS-HQ lane-line label."""
    # This recording does not preserve authoritative solid/dashed marking
    # semantics. Keep geometry continuous instead of inventing dashed lines.
    style = "SOLID_SINGLE"
    vertices = np.asarray(points, dtype=np.float64).tolist()
    return {
        "labelData": {
            "shape3d": {
                "polyline3d": {"vertices": vertices},
                "attributes": [
                    {
                        "name": "colors",
                        "enumsList": {"enumsList": ["WHITE"] * len(vertices)},
                    },
                    {
                        "name": "styles",
                        "enumsList": {"enumsList": [style] * len(vertices)},
                    },
                    {"name": "feature_id", "text": str(feature_id)},
                ],
            }
        }
    }


def road_boundary_label(feature_id: Any, points: ArrayF) -> dict[str, Any]:
    """Build an RDS-HQ road-boundary label."""
    return {
        "labelData": {
            "shape3d": {
                "polyline3d": {"vertices": np.asarray(points, dtype=np.float64).tolist()},
                "attributes": [{"name": "feature_id", "text": str(feature_id)}],
            }
        }
    }


def cuboid_vertices(
    center: Sequence[float],
    dimensions: Sequence[float],
    yaw: float,
) -> NDArray[np.float64]:
    """Build vertices in the ordering expected by Transfer2.5 RDSHQLoader."""
    length, width, height = dimensions
    local = np.array(
        [
            [length / 2, width / 2, height / 2],
            [length / 2, -width / 2, height / 2],
            [-length / 2, -width / 2, height / 2],
            [-length / 2, width / 2, height / 2],
            [length / 2, width / 2, -height / 2],
            [length / 2, -width / 2, -height / 2],
            [-length / 2, -width / 2, -height / 2],
            [-length / 2, width / 2, -height / 2],
        ],
        dtype=np.float64,
    )
    rotation = pose_matrix(0.0, 0.0, yaw)[:3, :3]
    return (rotation @ local.T).T + np.asarray(center, dtype=np.float64)


def upsample_traffic_light_states(
    source_states: Sequence[str],
    samples: Sequence[tuple[int, int, float]],
) -> list[str]:
    """Upsample discrete signal states with zero-order hold."""
    if not source_states:
        return ["UNKNOWN"] * len(samples)
    return [source_states[min(left, len(source_states) - 1)] for left, _, _ in samples]


def decode_traffic_light_state(raw_state: Any) -> str:
    """Decode CityNDE one-hot [green, yellow, red, unknown] traffic-light state."""
    values = np.asarray(raw_state, dtype=np.float64).reshape(-1)
    if values.size < 4 or not np.all(np.isfinite(values[:4])):
        return "UNKNOWN"
    return TRAFFIC_LIGHT_STATE_NAMES[int(np.argmax(values[:4]))]


def collect_traffic_lights(
    data: Mapping[str, Any],
    map_polylines: Mapping[Any, Mapping[str, Any]],
    start_step: int,
    source_steps: int,
    samples: Sequence[tuple[int, int, float]],
    height_m: float,
    ego_xy: ArrayF,
    map_radius_m: float,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int, list[str]]:
    """Convert dynamic polyline states to RDS-HQ light geometry and status."""
    id_steps = data.get("dynamic_polyline_id_per_step", [])
    state_steps = data.get("dynamic_polyline_state_per_step", [])
    warnings: list[str] = []
    if not id_steps or not state_steps:
        warnings.append("The pickle has no dynamic traffic-light arrays.")
        return [], {}, 0, warnings

    per_light: dict[Any, list[str | None]] = defaultdict(lambda: [None] * source_steps)
    source_observations = 0
    for local_step in range(source_steps):
        absolute_step = start_step + local_step
        ids = list(id_steps[absolute_step])
        states = list(state_steps[absolute_step])
        if len(ids) != len(states):
            raise ValueError(
                f"Traffic-light ids/states length mismatch at step {absolute_step}: "
                f"{len(ids)} vs {len(states)}"
            )
        for feature_id, raw_state in zip(ids, states):
            per_light[feature_id][local_step] = decode_traffic_light_state(raw_state)
            source_observations += 1

    labels: list[dict[str, Any]] = []
    status: dict[str, dict[str, Any]] = {}
    for feature_id in sorted(per_light, key=str):
        map_key = resolve_id(str(feature_id), map_polylines.keys())
        map_info = map_polylines[map_key]
        points = points_xyz(map_info)
        if not polyline_is_near_path(points, ego_xy, map_radius_m):
            continue

        source_sequence = per_light[feature_id]
        last_state = "UNKNOWN"
        filled_sequence: list[str] = []
        for state in source_sequence:
            if state is not None:
                last_state = state
            filled_sequence.append(last_state)

        map_states = np.asarray(map_info["states"], dtype=np.float64)
        stop_point = map_states[0]
        yaw = float(stop_point[2]) if stop_point.size >= 3 else 0.0
        center = (float(stop_point[0]), float(stop_point[1]), height_m)
        dimensions = TRAFFIC_LIGHT_HEAD_DIMENSIONS_M
        vertices = cuboid_vertices(center, dimensions, yaw)
        labels.append(
            {
                "labelData": {
                    "shape3d": {
                        "cuboid3d": {"vertices": vertices.tolist()},
                        "attributes": [{"name": "feature_id", "text": str(feature_id)}],
                    }
                }
            }
        )
        status[str(len(status))] = {
            "feature_id": str(feature_id),
            "state": upsample_traffic_light_states(filled_sequence, samples),
        }

    if not per_light:
        warnings.append(
            "Traffic-light fields exist, but every selected source frame contains "
            "zero light ids/states."
        )
    return labels, status, source_observations, warnings


def encode_member(value: Any, suffix: str) -> bytes:
    """Encode one WebDataset member based on its file suffix."""
    if suffix.endswith(".npy"):
        buffer = io.BytesIO()
        np.save(buffer, np.asarray(value), allow_pickle=False)
        return buffer.getvalue()
    if suffix.endswith(".json"):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raise ValueError(f"Unsupported WebDataset member suffix: {suffix}")


def write_webdataset_tar(
    output_path: Path,
    clip_id: str,
    members: Mapping[str, Any],
) -> None:
    """Write one WebDataset sample without requiring webdataset at conversion time."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w") as archive:
        for suffix, value in members.items():
            payload = encode_member(value, suffix)
            info = tarfile.TarInfo(name=f"{clip_id}.{suffix}")
            info.size = len(payload)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(payload))


def build_map_members(
    map_polylines: Mapping[Any, Mapping[str, Any]],
    ego_xy: ArrayF,
    radius_m: float,
    max_segment_length_m: float,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    """Build lane-line and road-boundary RDS-HQ JSON blobs."""
    lane_labels: list[dict[str, Any]] = []
    boundary_labels: list[dict[str, Any]] = []
    removed_jump_segments = 0
    for feature_id, info in map_polylines.items():
        map_type = int(info.get("type", -1))
        points = points_xyz(info)
        states = np.asarray(info["states"], dtype=np.float64)
        headings = states[:, 2] if states.shape[1] >= 3 else None
        chunks, jump_count = split_polyline_at_jumps(
            points,
            max_segment_length_m,
            headings=headings,
        )
        removed_jump_segments += jump_count
        for chunk_index, chunk in enumerate(chunks):
            if not polyline_is_near_path(chunk, ego_xy, radius_m):
                continue
            chunk_id = f"{feature_id}:{chunk_index}"
            if map_type in LANE_LINE_TYPES:
                lane_labels.append(lane_line_label(chunk_id, chunk, map_type))
            elif map_type in ROAD_BOUNDARY_TYPES:
                boundary_labels.append(road_boundary_label(chunk_id, chunk))
    return (
        {"labels": lane_labels},
        {"labels": boundary_labels},
        removed_jump_segments,
    )


def load_waymo_calibration(
    intrinsics_path: Path,
    extrinsics_path: Path,
) -> tuple[dict[str, NDArray[np.float64]], dict[str, NDArray[np.float64]]]:
    """Load the existing Waymo five-camera calibration dictionaries."""
    intrinsic_raw = np.load(intrinsics_path, allow_pickle=True).item()
    extrinsic_raw = np.load(extrinsics_path, allow_pickle=True).item()
    intrinsics: dict[str, NDArray[np.float64]] = {}
    extrinsics: dict[str, NDArray[np.float64]] = {}
    for camera_name in WAYMO_CAMERA_NAMES:
        intrinsic_key = f"pinhole_intrinsic.{camera_name}.npy"
        if intrinsic_key not in intrinsic_raw or camera_name not in extrinsic_raw:
            raise KeyError(f"Waymo calibration is missing camera {camera_name!r}")
        intrinsic = np.asarray(intrinsic_raw[intrinsic_key], dtype=np.float64)
        extrinsic = np.asarray(extrinsic_raw[camera_name], dtype=np.float64)
        if intrinsic.shape != (6,) or extrinsic.shape != (4, 4):
            raise ValueError(
                f"Invalid calibration for {camera_name}: intrinsic={intrinsic.shape}, "
                f"extrinsic={extrinsic.shape}"
            )
        intrinsics[camera_name] = intrinsic
        extrinsics[camera_name] = extrinsic
    return intrinsics, extrinsics


def convert(config: ConversionConfig) -> ConversionReport:
    """Run the complete conversion."""
    input_path = Path(config.input_path)
    output_root = Path(config.output_root)
    data = load_trusted_pickle(input_path)
    step_vehicles = build_step_vehicles(data, config.start_step, config.source_steps)
    step_vehicles, stabilized_heading_count = stabilize_low_speed_headings(step_vehicles)
    ego_id = resolve_id(config.ego_id, step_vehicles[0].keys())
    samples = target_frame_samples(config.source_steps, config.source_fps, config.target_fps)
    ego_states = interpolate_ego_states(step_vehicles, ego_id, samples)
    ego_xy = np.asarray([state[:2] for state in ego_states], dtype=np.float64)
    selected_object_ids = select_object_tracks(
        step_vehicles=step_vehicles,
        static_attributes=data["vehicle_static_attribute"],
        ego_id=ego_id,
        agent_radius_m=config.agent_radius_m,
    )

    intrinsics, camera_to_vehicle = load_waymo_calibration(
        Path(config.waymo_intrinsics),
        Path(config.waymo_extrinsics),
    )

    vehicle_pose_members: dict[str, Any] = {}
    camera_pose_members: dict[str, Any] = {}
    object_members: dict[str, Any] = {}
    object_track_ids: set[str] = set()
    object_observations = 0

    for frame_index, ((left, right, alpha), ego_state) in enumerate(zip(samples, ego_states)):
        vehicle_to_world = pose_matrix(
            float(ego_state[0]),
            float(ego_state[1]),
            float(ego_state[2]),
        )
        vehicle_pose_members[f"{frame_index:06d}.vehicle_pose.npy"] = vehicle_to_world
        for camera_name in WAYMO_CAMERA_NAMES:
            camera_to_world_flu = vehicle_to_world @ camera_to_vehicle[camera_name]
            camera_pose_members[f"{frame_index:06d}.pose.{camera_name}.npy"] = camera_flu_to_opencv(
                camera_to_world_flu
            )

        frame_objects = interpolate_objects_at_frame(
            step_vehicles=step_vehicles,
            static_attributes=data["vehicle_static_attribute"],
            ego_id=ego_id,
            left_index=left,
            right_index=right,
            alpha=alpha,
            selected_object_ids=selected_object_ids,
        )
        object_members[f"{frame_index:06d}.all_object_info.json"] = frame_objects
        object_track_ids.update(frame_objects)
        object_observations += len(frame_objects)

    map_root = data["map"]
    map_polylines = map_root["polyline"] if "polyline" in map_root else map_root
    lanelines, road_boundaries, removed_map_jump_segments = build_map_members(
        map_polylines,
        ego_xy,
        config.map_radius_m,
        config.map_max_segment_length_m,
    )
    light_labels, light_status, light_observations, warnings = collect_traffic_lights(
        data=data,
        map_polylines=map_polylines,
        start_step=config.start_step,
        source_steps=config.source_steps,
        samples=samples,
        height_m=config.traffic_light_height_m,
        ego_xy=ego_xy,
        map_radius_m=config.map_radius_m,
    )

    intrinsic_members = {
        f"pinhole_intrinsic.{camera_name}.npy": intrinsics[camera_name]
        for camera_name in WAYMO_CAMERA_NAMES
    }
    write_webdataset_tar(
        output_root / "vehicle_pose" / f"{config.clip_id}.tar",
        config.clip_id,
        vehicle_pose_members,
    )
    write_webdataset_tar(
        output_root / "pose" / f"{config.clip_id}.tar",
        config.clip_id,
        camera_pose_members,
    )
    write_webdataset_tar(
        output_root / "all_object_info" / f"{config.clip_id}.tar",
        config.clip_id,
        object_members,
    )
    write_webdataset_tar(
        output_root / "pinhole_intrinsic" / f"{config.clip_id}.tar",
        config.clip_id,
        intrinsic_members,
    )
    write_webdataset_tar(
        output_root / "3d_lanelines" / f"{config.clip_id}.tar",
        config.clip_id,
        {"lanelines.json": lanelines},
    )
    write_webdataset_tar(
        output_root / "3d_road_boundaries" / f"{config.clip_id}.tar",
        config.clip_id,
        {"road_boundaries.json": road_boundaries},
    )
    if light_labels:
        write_webdataset_tar(
            output_root / "3d_traffic_lights" / f"{config.clip_id}.tar",
            config.clip_id,
            {"3d_traffic_lights.json": {"labels": light_labels}},
        )
        write_webdataset_tar(
            output_root / "3d_traffic_lights_status" / f"{config.clip_id}.tar",
            config.clip_id,
            {"aggregated_states.json": {"traffic_light_states": light_status}},
        )

    duration = (config.source_steps - 1) / config.source_fps
    report = ConversionReport(
        clip_id=config.clip_id,
        input_steps=config.source_steps,
        output_frames=len(samples),
        duration_seconds=duration,
        ego_id=str(ego_id),
        cameras=list(WAYMO_CAMERA_NAMES),
        source_vehicle_tracks=len(data["vehicle_static_attribute"]),
        exported_object_tracks=len(object_track_ids),
        exported_object_observations=object_observations,
        exported_lane_lines=len(lanelines["labels"]),
        exported_road_boundaries=len(road_boundaries["labels"]),
        removed_map_jump_segments=removed_map_jump_segments,
        source_traffic_light_observations=light_observations,
        exported_traffic_lights=len(light_labels),
        stabilized_low_speed_heading_observations=stabilized_heading_count,
        warnings=warnings,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "conversion_report.json").open("w", encoding="utf-8") as stream:
        json.dump(
            {"config": asdict(config), "report": asdict(report)},
            stream,
            indent=2,
            ensure_ascii=False,
        )
        stream.write("\n")
    return report


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a normalized traffic pickle recording to Cosmos RDS-HQ scene data."
    )
    parser.add_argument("input", type=Path, help="Trusted input pickle")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).resolve().parent / "cosmos_scene",
        help="Output RDS-HQ root (default: test/cosmos_scene)",
    )
    parser.add_argument("--clip-id", default=None, help="Output clip id (default: pickle stem)")
    parser.add_argument(
        "--ego-id",
        default=None,
        help="Vehicle id used as ego (default: first vehicle at --start-step)",
    )
    parser.add_argument("--start-step", type=int, default=0)
    parser.add_argument(
        "--source-steps",
        type=int,
        default=41,
        help="Number of 10 Hz source steps; 41 steps produce 121 frames at 30 FPS",
    )
    parser.add_argument("--source-fps", type=float, default=None)
    parser.add_argument("--target-fps", type=int, default=30)
    parser.add_argument("--map-radius", type=float, default=150.0)
    parser.add_argument(
        "--map-max-segment-length",
        type=float,
        default=3.0,
        help=(
            "Minimum length considered by heading-based map discontinuity "
            "detection (default: 3 m)"
        ),
    )
    parser.add_argument("--agent-radius", type=float, default=120.0)
    parser.add_argument("--traffic-light-height", type=float, default=4.5)
    parser.add_argument(
        "--waymo-intrinsics",
        type=Path,
        default=DEFAULT_WAYMO_INTRINSICS,
    )
    parser.add_argument(
        "--waymo-extrinsics",
        type=Path,
        default=DEFAULT_WAYMO_EXTRINSICS,
    )
    return parser


def main() -> None:
    args = make_parser().parse_args()
    data = load_trusted_pickle(args.input)
    resolution = float(data.get("simulator_meta_info", {}).get("resolution", 0.1))
    source_fps = args.source_fps if args.source_fps is not None else 1.0 / resolution
    first_step_ids = data["vehicle_id_per_step"][args.start_step]
    ego_id = resolve_id(args.ego_id, first_step_ids)
    config = ConversionConfig(
        input_path=str(args.input.resolve()),
        output_root=str(args.output_root.resolve()),
        clip_id=args.clip_id or args.input.stem,
        ego_id=str(ego_id),
        source_fps=float(source_fps),
        target_fps=args.target_fps,
        start_step=args.start_step,
        source_steps=args.source_steps,
        map_radius_m=args.map_radius,
        map_max_segment_length_m=args.map_max_segment_length,
        agent_radius_m=args.agent_radius,
        traffic_light_height_m=args.traffic_light_height,
        waymo_intrinsics=str(args.waymo_intrinsics.resolve()),
        waymo_extrinsics=str(args.waymo_extrinsics.resolve()),
    )
    report = convert(config)
    print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    print(f"Saved Cosmos RDS-HQ scene to: {config.output_root}")


if __name__ == "__main__":
    main()
