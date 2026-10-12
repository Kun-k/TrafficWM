"""Convert normalized traffic frames into the trusted RDS-HQ recording schema."""
from __future__ import annotations

import bisect
import json
import math
import pickle
from pathlib import Path
from typing import Any, Sequence

import numpy as np


def _actors(frame: dict[str, Any]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for actor in [frame.get("ego") or {}, *(frame.get("vehicles") or frame.get("actors") or [])]:
        if isinstance(actor, dict) and actor.get("id") is not None:
            values[str(actor["id"])] = dict(actor)
    return list(values.values())


def _lerp_actor(first: dict[str, Any], second: dict[str, Any], ratio: float) -> dict[str, Any]:
    result = dict(second)
    for key in ("x", "y", "z", "speed", "length", "width", "height"):
        try:
            start, end = float(first[key]), float(second[key])
        except (KeyError, TypeError, ValueError):
            continue
        result[key] = start + (end - start) * float(ratio)
    first_heading = float(first.get("heading", 0.0) or 0.0)
    second_heading = float(second.get("heading", 0.0) or 0.0)
    delta = math.atan2(math.sin(second_heading - first_heading), math.cos(second_heading - first_heading))
    result["heading"] = first_heading + delta * float(ratio)
    return result


def resample_traffic_frames(
    frames: Sequence[dict[str, Any]],
    *,
    target_fps: float,
    duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Sample a normalized actor stream on an endpoint-inclusive fixed timebase."""
    ordered = sorted((dict(frame) for frame in frames), key=lambda item: float(item.get("sim_time", 0.0)))
    if len(ordered) < 2:
        raise ValueError("At least two traffic frames are required")
    times = [float(frame.get("sim_time", 0.0) or 0.0) for frame in ordered]
    if any(second <= first for first, second in zip(times, times[1:])):
        raise ValueError("Traffic frame times must be strictly increasing")
    start_time = times[0]
    available_duration = times[-1] - start_time
    duration = available_duration if duration_seconds is None else float(duration_seconds)
    if duration <= 0.0 or duration > available_duration + 1e-6:
        raise ValueError(
            f"Requested {duration:g}s from a traffic stream with {available_duration:g}s available"
        )
    count = int(round(duration * float(target_fps))) + 1
    output = []
    for index in range(count):
        target = start_time + index / float(target_fps)
        upper = bisect.bisect_left(times, target)
        if upper <= 0:
            source = dict(ordered[0])
        elif upper >= len(ordered):
            source = dict(ordered[-1])
        else:
            first, second = ordered[upper - 1], ordered[upper]
            ratio = (target - times[upper - 1]) / max(times[upper] - times[upper - 1], 1e-9)
            first_actors = {str(actor["id"]): actor for actor in _actors(first)}
            second_actors = {str(actor["id"]): actor for actor in _actors(second)}
            common = first_actors.keys() & second_actors.keys()
            interpolated = {
                actor_id: _lerp_actor(first_actors[actor_id], second_actors[actor_id], ratio)
                for actor_id in common
            }
            ego_id = str((second.get("ego") or first.get("ego") or {}).get("id") or "")
            source = {
                "sim_time": target,
                "ego": interpolated.pop(ego_id, dict(second.get("ego") or first.get("ego") or {})),
                "vehicles": list(interpolated.values()),
                "traffic_lights": dict(
                    (first if ratio < 0.5 else second).get("traffic_lights") or {}
                ),
            }
        source["sim_time"] = round(index / float(target_fps), 6)
        output.append(source)
    return output


def _map_polylines(map_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for index, polyline in enumerate(map_state.get("polylines") or []):
        points = np.asarray(polyline.get("points") or [], dtype=np.float64)
        if points.ndim != 2 or len(points) < 2 or points.shape[1] < 2:
            continue
        xyz = np.zeros((len(points), 3), dtype=np.float64)
        xyz[:, :2] = points[:, :2]
        deltas = np.gradient(xyz[:, :2], axis=0)
        xyz[:, 2] = np.arctan2(deltas[:, 1], deltas[:, 0])
        raw_type = polyline.get("type", 2)
        output[str(polyline.get("id") or f"map-{index}")] = {
            "states": xyz,
            "type": int(2 if raw_type is None else raw_type),
            "prev_lanes_id": [],
            "next_lanes_id": [],
            "left_lanes_id": [],
            "right_lanes_id": [],
        }
    return output


def traffic_frames_to_recording(
    frames: Sequence[dict[str, Any]],
    map_state: dict[str, Any],
    output_path: Path,
    *,
    source_fps: float,
    duration_seconds: float,
) -> dict[str, Any]:
    """Write a model-neutral traffic stream in the converter's trusted pickle schema."""
    sampled = resample_traffic_frames(
        frames, target_fps=float(source_fps), duration_seconds=float(duration_seconds)
    )
    ids_per_step: list[list[str]] = []
    states_per_step: list[np.ndarray] = []
    static: dict[str, np.ndarray] = {}
    road_user_type: dict[str, str] = {}
    for frame in sampled:
        ids: list[str] = []
        states: list[list[float]] = []
        for actor in _actors(frame):
            actor_id = str(actor["id"])
            heading = float(actor.get("heading", 0.0) or 0.0)
            speed = max(0.0, float(actor.get("speed", 0.0) or 0.0))
            ids.append(actor_id)
            states.append(
                [
                    float(actor.get("x", 0.0) or 0.0),
                    float(actor.get("y", 0.0) or 0.0),
                    heading,
                    speed * math.cos(heading),
                    speed * math.sin(heading),
                    float(actor.get("ax", 0.0) or 0.0),
                    float(actor.get("ay", 0.0) or 0.0),
                ]
            )
            static.setdefault(
                actor_id,
                np.asarray(
                    [
                        max(0.2, float(actor.get("length", 4.5) or 4.5)),
                        max(0.2, float(actor.get("width", 1.8) or 1.8)),
                        max(0.2, float(actor.get("height", 1.5) or 1.5)),
                    ],
                    dtype=np.float64,
                ),
            )
            actor_type = str(actor.get("road_user_type") or actor.get("type") or "vehicle").lower()
            road_user_type[actor_id] = "cyclist" if "cycl" in actor_type else "pedestrian" if "ped" in actor_type else "vehicle"
        ids_per_step.append(ids)
        states_per_step.append(np.asarray(states, dtype=np.float64).reshape(-1, 7))

    recording = {
        "simulator_meta_info": {
            "source": "normalized_traffic_frames",
            "source_fps": float(source_fps),
        },
        "map": {"polyline": _map_polylines(map_state), "map_center": [0.0, 0.0]},
        "routes": {},
        "dynamic_polyline_id_per_step": [[] for _ in sampled],
        "dynamic_polyline_state_per_step": [np.empty((0, 4), dtype=np.float64) for _ in sampled],
        "vehicle_id_per_step": ids_per_step,
        "vehicle_state_per_step": states_per_step,
        "vehicle_static_attribute": static,
        "road_user_type": road_user_type,
    }
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
    report = {
        "schema": "denseworld.normalized-recording.v1",
        "recording": str(output_path),
        "source_frames": len(frames),
        "source_fps": float(source_fps),
        "recording_frames": len(sampled),
        "duration_seconds": float(duration_seconds),
        "actor_tracks": len(static),
        "map_polylines": len(recording["map"]["polyline"]),
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
