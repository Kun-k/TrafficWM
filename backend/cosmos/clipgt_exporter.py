"""Export normalized TrafficWM map state to OmniDreams ClipGT parquet files."""
from __future__ import annotations

import argparse
import json
import math
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from backend.cosmos.camera_calibration import omnidreams_camera_calibration


EGO_LABEL = "trafficwm:egomotion:v1"
MAP_VERSION = "trafficwm-v1"


def _point(value: Sequence[float], z: float = 0.0) -> dict[str, float]:
    return {"x": float(value[0]), "y": float(value[1]), "z": float(value[2]) if len(value) > 2 else float(z)}


def _key(clip_id: str, kind: str, feature_id: Any) -> dict[str, str]:
    return {
        "clip_id": clip_id,
        "label_class_id": f"trafficwm:{kind}:v1",
        "map_id": str(feature_id),
        "map_id_version": MAP_VERSION,
    }


def _write(rows: list[dict[str, Any]], path: Path) -> None:
    if rows:
        pd.DataFrame(rows).to_parquet(path, index=False)
    else:
        path.unlink(missing_ok=True)


def _ego_path(traffic_frames: Sequence[dict[str, Any]]) -> list[tuple[float, float]]:
    path: list[tuple[float, float]] = []
    for frame in traffic_frames:
        ego = frame.get("ego") or {}
        try:
            point = (float(ego["x"]), float(ego["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in point):
            continue
        if not path or math.hypot(point[0] - path[-1][0], point[1] - path[-1][1]) > 1e-6:
            path.append(point)
    return path


def _points_near_path(
    points: Sequence[Sequence[float]],
    ego_path: Sequence[tuple[float, float]],
    radius_m: float,
) -> bool:
    if not ego_path:
        return True
    radius_sq = float(radius_m) ** 2
    for point in points:
        if len(point) < 2:
            continue
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        if any((x - ego_x) ** 2 + (y - ego_y) ** 2 <= radius_sq for ego_x, ego_y in ego_path):
            return True
    return False


def _item_near_path(
    item: dict[str, Any],
    ego_path: Sequence[tuple[float, float]],
    radius_m: float,
    *geometry_keys: str,
) -> bool:
    for key in geometry_keys:
        geometry = item.get(key) or []
        if geometry and isinstance(geometry[0], (int, float)):
            geometry = [geometry]
        if _points_near_path(geometry, ego_path, radius_m):
            return True
    return False


def _lane_line_style(polyline: dict[str, Any]) -> str:
    """Keep CityNDE map semantics identical in Transfer and OmniDreams."""
    polyline_type = int(polyline.get("type", 0) or 0)
    if polyline_type == 3:
        return "SHORT_DASHED_SINGLE"
    return "LONG_DASHED_SINGLE"


def _yaw_quaternion(yaw: float) -> dict[str, float]:
    return {"x": 0.0, "y": 0.0, "z": math.sin(yaw / 2.0), "w": math.cos(yaw / 2.0)}


def _cluster_signal_items(items: Sequence[dict[str, Any]], *, radius_m: float = 4.0) -> list[dict[str, Any]]:
    clusters: list[list[dict[str, Any]]] = []
    centers: list[tuple[float, float]] = []
    for item in items:
        position = item.get("position") or []
        if len(position) < 2:
            continue
        x, y = float(position[0]), float(position[1])
        assigned = False
        for index, center in enumerate(centers):
            same_signal_type = str(item.get("signal_type") or "vehicle") == str(
                clusters[index][0].get("signal_type") or "vehicle"
            )
            if same_signal_type and math.hypot(x - center[0], y - center[1]) <= radius_m:
                clusters[index].append(item)
                xs = [float((member.get("position") or [0.0, 0.0])[0]) for member in clusters[index]]
                ys = [float((member.get("position") or [0.0, 0.0])[1]) for member in clusters[index]]
                centers[index] = (sum(xs) / len(xs), sum(ys) / len(ys))
                assigned = True
                break
        if not assigned:
            clusters.append([item])
            centers.append((x, y))

    output = []
    for index, members in enumerate(clusters):
        center = centers[index]
        headings = [float(member.get("heading", 0.0)) for member in members]
        sin_sum = sum(math.sin(value) for value in headings)
        cos_sum = sum(math.cos(value) for value in headings)
        heading = math.atan2(sin_sum, cos_sum) if headings else 0.0
        head_positions: list[dict[str, Any]] = []
        for member in members:
            for head in member.get("head_positions") or []:
                position = list(head.get("position") or [])
                if len(position) < 2:
                    continue
                candidate = {
                    "movement": str(head.get("movement") or "combined"),
                    "position": [float(position[0]), float(position[1])],
                    "state_keys": [str(key) for key in head.get("state_keys") or []],
                }
                if not any(
                    existing["movement"] == candidate["movement"]
                    and math.dist(existing["position"], candidate["position"]) <= 0.5
                    for existing in head_positions
                ):
                    head_positions.append(candidate)

        if head_positions:
            head_center = (
                sum(item["position"][0] for item in head_positions) / len(head_positions),
                sum(item["position"][1] for item in head_positions) / len(head_positions),
            )
            base_candidates = [
                (float(member["position"][0]), float(member["position"][1]))
                for member in members
                if len(member.get("position") or []) >= 2
            ]
            center = max(
                base_candidates,
                key=lambda item: math.hypot(item[0] - head_center[0], item[1] - head_center[1]),
            )

        arm_candidates = [
            (float(arm_end[0]), float(arm_end[1]))
            for member in members
            if len((arm_end := list(member.get("mast_arm_end") or []))) >= 2
        ]
        if arm_candidates:
            mast_arm_end = max(
                arm_candidates,
                key=lambda item: math.hypot(item[0] - center[0], item[1] - center[1]),
            )
        elif head_positions and str(members[0].get("signal_type") or "vehicle") != "pedestrian":
            farthest = max(
                (item["position"] for item in head_positions),
                key=lambda item: math.hypot(item[0] - center[0], item[1] - center[1]),
            )
            distance = max(math.hypot(farthest[0] - center[0], farthest[1] - center[1]), 1e-6)
            mast_arm_end = (
                farthest[0] + (farthest[0] - center[0]) / distance * 0.35,
                farthest[1] + (farthest[1] - center[1]) / distance * 0.35,
            )
        elif str(members[0].get("signal_type") or "vehicle") != "pedestrian":
            normal = (-math.sin(heading), math.cos(heading))
            mast_arm_end = (center[0] + normal[0] * 4.0, center[1] + normal[1] * 4.0)
            head_positions = [
                {
                    "movement": "combined",
                    "position": [center[0] + normal[0] * 2.8, center[1] + normal[1] * 2.8],
                    "state_keys": [],
                }
            ]
        else:
            mast_arm_end = None
            head_positions = [
                {"movement": "pedestrian", "position": [center[0], center[1]], "state_keys": []}
            ]
        output.append(
            {
                "id": f"trafficwm-signal-cluster-{index}",
                "position": [center[0], center[1]],
                "mast_arm_end": list(mast_arm_end) if mast_arm_end is not None else [],
                "head_positions": head_positions,
                "heading": heading,
                "signal_type": str(members[0].get("signal_type") or "vehicle"),
                "source_signal_ids": [str(member.get("id", idx)) for idx, member in enumerate(members)],
            }
        )
    return output


def _lane_line_row(
    clip_id: str,
    feature_id: Any,
    points: Sequence[dict[str, float]],
    *,
    style: str = "SOLID_SINGLE",
) -> dict[str, Any]:
    point_list = list(points)
    return {
        "key": _key(clip_id, "lane-lines", feature_id),
        "lane_line": {
            "line_rail": point_list,
            "styles": [style] * len(point_list),
            "colors": ["WHITE"] * len(point_list),
        },
        "version": 0,
    }


def _camera_rig(camera_name: str, width: int, height: int, fov_degrees: float) -> str:
    calibration = omnidreams_camera_calibration(
        camera_name,
        width,
        height,
        fov_degrees=fov_degrees,
    )
    ftheta = calibration["ftheta"]
    camera_to_vehicle = calibration["camera_to_vehicle_flu"]
    linear_cde = ftheta["linear_cde"]
    colon_name = camera_name.replace("_", ":")
    payload = {
        "rig": {
            "sensors": [
                {
                    "name": colon_name,
                    "properties": {
                        "height": str(height),
                        "width": str(width),
                        "cx": str(ftheta["principal_point"][0]),
                        "cy": str(ftheta["principal_point"][1]),
                        "linear-c": str(linear_cde[0]),
                        "linear-d": str(linear_cde[1]),
                        "linear-e": str(linear_cde[2]),
                        "polynomial": " ".join(str(value) for value in ftheta["polynomial"]),
                        "polynomial-type": (
                            "pixeldistance-to-angle"
                            if ftheta["is_backward"]
                            else "angle-to-pixeldistance"
                        ),
                        "Model": "ftheta",
                    },
                    "nominalSensor2Rig_FLU": {
                        "roll-pitch-yaw": camera_to_vehicle["rpy_degrees"],
                        "t": camera_to_vehicle["translation"],
                    },
                }
            ]
        }
    }
    return json.dumps(payload, separators=(",", ":"))


def _ego_rows(clip_id: str, traffic_frames: list[dict[str, Any]], fps: int) -> list[dict[str, Any]]:
    source = traffic_frames or [{"sim_time": 0.0, "ego": {"x": 0.0, "y": 0.0, "z": 0.0, "heading": 0.0}}]
    if len(source) == 1:
        source = [source[0], {**source[0], "sim_time": 1.0 / fps}]
    rows = []
    for index, frame in enumerate(source):
        ego = frame.get("ego") or {}
        timestamp = int(round(float(frame.get("sim_time", index / fps)) * 1_000_000)) + 1_000_000
        rows.append(
            {
                "key": {"clip_id": clip_id, "timestamp_micros": timestamp, "label_class_id": EGO_LABEL},
                "egomotion_estimate": {
                    "name": "trafficwm",
                    "location": {"x": float(ego.get("x", 0.0)), "y": float(ego.get("y", 0.0)), "z": float(ego.get("z", 0.0))},
                    "orientation": _yaw_quaternion(float(ego.get("heading", 0.0))),
                },
                "version": 0,
            }
        )
    return rows


def export_clipgt(
    map_state: dict[str, Any],
    traffic_frames: list[dict[str, Any]],
    output_dir: Path,
    *,
    clip_id: str = "",
    camera_name: str = "camera_front_wide_120fov",
    width: int = 1280,
    height: int = 704,
    fov_degrees: float = 120.0,
    fps: int = 30,
    map_radius_m: float | None = None,
    map_crop_path: list[list[float]] | None = None,
) -> dict[str, Any]:
    clip_id = clip_id or f"trafficwm-{uuid.uuid4().hex[:12]}"
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / clip_id
    ego_path = _ego_path(traffic_frames)
    crop_path = [
        [float(point[0]), float(point[1])]
        for point in (map_crop_path or [])
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ] or ego_path
    local_radius = float(map_radius_m) if map_radius_m is not None else math.inf
    if not math.isfinite(local_radius) and map_radius_m is not None:
        raise ValueError("map_radius_m must be finite")
    if local_radius <= 0.0:
        raise ValueError("map_radius_m must be positive")

    calibration_rows = [
        {
            "key": {"clip_id": clip_id, "timestamp_micros": 0, "label_class_id": "trafficwm:calibration:v1"},
            "calibration_estimate": {"name": "TRAFFICWM_RIG_V1", "rig_json": _camera_rig(camera_name, width, height, fov_degrees)},
            "version": 0,
        }
    ]
    _write(calibration_rows, prefix.with_suffix(".calibration_estimate.parquet"))
    _write(_ego_rows(clip_id, traffic_frames, fps), prefix.with_suffix(".egomotion_estimate.parquet"))

    lane_rows: list[dict[str, Any]] = []
    lane_line_rows: list[dict[str, Any]] = []
    boundary_rows: list[dict[str, Any]] = []
    source_polylines = list(map_state.get("polylines") or [])
    local_polylines = [
        polyline
        for polyline in source_polylines
        if _points_near_path(polyline.get("points") or [], crop_path, local_radius)
    ]
    omitted_centerlines = 0
    for index, polyline in enumerate(local_polylines):
        points = polyline.get("points") or []
        if len(points) < 2:
            continue
        feature_id = polyline.get("id", index)
        point_structs = [_point(point) for point in points]
        polyline_type = int(polyline.get("type", 0) or 0)
        if polyline.get("lane_center") or polyline_type in {0, 4}:
            # CityNDE types 0/4 are routing centerlines. Offsetting them creates
            # duplicate rails that were never observed in the source map.
            omitted_centerlines += 1
        elif polyline_type == 2 or polyline.get("road_boundary"):
            boundary_rows.append(
                {
                    "key": _key(clip_id, "road-boundaries", feature_id),
                    "road_boundary": {"category": "curb", "location": point_structs},
                    "version": 0,
                }
            )
        else:
            lane_line_rows.append(
                _lane_line_row(
                    clip_id,
                    feature_id,
                    point_structs,
                    style=_lane_line_style(polyline),
                )
            )
    _write(lane_rows, prefix.with_suffix(".lane.parquet"))
    _write(lane_line_rows, prefix.with_suffix(".lane_line.parquet"))
    _write(boundary_rows, prefix.with_suffix(".road_boundary.parquet"))

    crosswalk_rows = [
        {
            "key": _key(clip_id, "crosswalks", item.get("id", index)),
            "crosswalk": {"category": "PEDESTRIAN", "location": [_point(point) for point in item.get("polygon") or []]},
            "version": 0,
        }
        for index, item in enumerate(map_state.get("crosswalks") or [])
        if len(item.get("polygon") or []) >= 3
        and _item_near_path(item, crop_path, local_radius, "polygon", "centerline")
    ]
    _write(crosswalk_rows, prefix.with_suffix(".crosswalk.parquet"))

    wait_rows = [
        {
            "key": _key(clip_id, "wait-lines", item.get("id", index)),
            "wait_line": {"category": "STOP", "location": [_point(point) for point in item.get("points") or []], "is_implicit": False},
            "version": 0,
        }
        for index, item in enumerate(map_state.get("stop_lines") or [])
        if len(item.get("points") or []) >= 2
        and _item_near_path(item, crop_path, local_radius, "points")
    ]
    _write(wait_rows, prefix.with_suffix(".wait_line.parquet"))

    light_rows: list[dict[str, Any]] = []
    pole_rows: list[dict[str, Any]] = []
    local_signals = [
        item
        for item in map_state.get("traffic_signals") or []
        if _item_near_path(item, crop_path, local_radius, "position")
    ]
    clustered_signals = _cluster_signal_items(local_signals)
    for index, item in enumerate(clustered_signals):
        position = item.get("position") or []
        if len(position) < 2:
            continue
        heading = float(item.get("heading", 0.0))
        feature_id = item.get("id", index)
        for head_index, head in enumerate(item.get("head_positions") or []):
            head_position = list(head.get("position") or [])
            if len(head_position) < 2:
                continue
            light_rows.append(
                {
                    "key": _key(
                        clip_id,
                        "traffic-lights",
                        f"{feature_id}-head-{head_index}-{head.get('movement', 'combined')}",
                    ),
                    "traffic_light": {
                        "center": _point([head_position[0], head_position[1], 4.2]),
                        "dimensions": {"x": 0.35, "y": 0.75, "z": 1.25},
                        "orientation": _yaw_quaternion(heading),
                        "category": "traffic_light",
                    },
                    "version": 0,
                }
            )
        arm_end = list(item.get("mast_arm_end") or [])
        pole_location = [
            _point([position[0], position[1], 0.0]),
            _point([position[0], position[1], 4.8]),
        ]
        if len(arm_end) >= 2:
            pole_location.append(_point([arm_end[0], arm_end[1], 4.8]))
        pole_rows.append(
            {
                "key": _key(clip_id, "poles", feature_id),
                "pole": {"category": "TRAFFIC_LIGHT", "location": pole_location},
                "version": 0,
            }
        )
    _write(light_rows, prefix.with_suffix(".traffic_light.parquet"))
    _write(pole_rows, prefix.with_suffix(".pole.parquet"))

    archive_path = output_dir / f"{clip_id}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.glob(f"{clip_id}.*")):
            if path != archive_path:
                archive.write(path, path.name)
    manifest = {
        "schema": "denseworld.clipgt-export.v1",
        "clip_id": clip_id,
        "archive": str(archive_path),
        "camera_name": camera_name,
        "camera_calibration": omnidreams_camera_calibration(
            camera_name,
            width,
            height,
            fov_degrees=fov_degrees,
        ),
        "map_crop": {
            "mode": (
                "route_corridor"
                if map_crop_path
                else "ego_path_radius"
                if math.isfinite(local_radius)
                else "full_map"
            ),
            "radius_m": round(local_radius, 3) if math.isfinite(local_radius) else None,
            "ego_path_points": len(ego_path),
            "crop_path_points": len(crop_path),
            "source_polylines": len(source_polylines),
            "included_polylines": len(local_polylines),
        },
        "trajectory_contract": {
            "static_egomotion_role": "coordinate_frame_bootstrap",
            "static_egomotion_samples": len(traffic_frames) if traffic_frames else 2,
            "runtime_rig_trajectory_role": "authoritative_per_chunk",
            "runtime_rig_trajectory_fps": fps,
            "runtime_interpolation_source_fps": 10,
        },
        "control_contract": {
            "static_map": "clipgt-hdmap",
            "lane_topology": "omit-unobserved-centerline-rails",
            "dynamic_actors": "authoritative-grpc-per-chunk",
            "traffic_lights": "static-mast-arm-and-head-geometry-only",
            "traffic_signal_cluster_radius_m": 4.0,
        },
        "counts": {
            "lanes": len(lane_rows),
            "lane_lines": len(lane_line_rows),
            "road_boundaries": len(boundary_rows),
            "crosswalks": len(crosswalk_rows),
            "wait_lines": len(wait_rows),
            "traffic_lights": len(light_rows),
            "poles": len(pole_rows),
            "source_traffic_signals": len(map_state.get("traffic_signals") or []),
            "included_traffic_signals": len(local_signals),
            "omitted_centerline_topology": omitted_centerlines,
        },
        "semantic_quality": map_state.get("semantic_quality") or {},
        "ludus_compatible": bool(lane_line_rows or boundary_rows),
    }
    (output_dir / "clipgt_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-state", type=Path, required=True)
    parser.add_argument("--traffic-frames", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clip-id", default="")
    parser.add_argument("--camera-name", default="camera_front_wide_120fov")
    parser.add_argument("--map-radius-m", type=float)
    args = parser.parse_args()
    map_state = json.loads(args.map_state.read_text(encoding="utf-8"))
    traffic_frames = json.loads(args.traffic_frames.read_text(encoding="utf-8")) if args.traffic_frames else []
    print(json.dumps(export_clipgt(
        map_state,
        traffic_frames,
        args.output_dir,
        clip_id=args.clip_id,
        camera_name=args.camera_name,
        map_radius_m=args.map_radius_m,
    )))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
