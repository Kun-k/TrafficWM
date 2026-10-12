"""Build normalized traffic-control geometry without depending on SUMO at runtime."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


Point = list[float]

CITYNDE_SIDEWALK_WAITING_CLEARANCE_M = 1.25


def _float(value: Any, default: float) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _points_from_shape(shape: str) -> list[Point]:
    points: list[Point] = []
    for token in str(shape or "").split():
        values = token.split(",")
        if len(values) < 2:
            continue
        try:
            points.append([float(values[0]), float(values[1])])
        except ValueError:
            continue
    return points


def _xy_points(value: Any) -> list[Point]:
    points: list[Point] = []
    if value is None:
        return points
    try:
        rows = value.tolist()
    except AttributeError:
        rows = value
    for row in rows or []:
        if len(row) < 2:
            continue
        x, y = _float(row[0], float("nan")), _float(row[1], float("nan"))
        if math.isfinite(x) and math.isfinite(y):
            points.append([x, y])
    return points


def _unit_direction(points: Sequence[Point], at_end: bool = True) -> tuple[float, float]:
    pairs = zip(reversed(points[:-1]), reversed(points[1:])) if at_end else zip(points[:-1], points[1:])
    for first, second in pairs:
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            return dx / length, dy / length
    return 1.0, 0.0


def _outline(points: Sequence[Point], width: float) -> list[Point]:
    if len(points) < 2:
        return []
    half = max(0.2, float(width) / 2.0)
    left: list[Point] = []
    right: list[Point] = []
    for index, point in enumerate(points):
        before = points[max(0, index - 1)]
        after = points[min(len(points) - 1, index + 1)]
        dx, dy = after[0] - before[0], after[1] - before[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            nx, ny = 0.0, 1.0
        else:
            nx, ny = -dy / length, dx / length
        left.append([point[0] + nx * half, point[1] + ny * half])
        right.append([point[0] - nx * half, point[1] - ny * half])
    polygon = left + list(reversed(right))
    polygon.append(polygon[0])
    return polygon


def _line_across_lane(points: Sequence[Point], width: float, setback: float = 0.0) -> tuple[list[Point], Point, tuple[float, float]]:
    dx, dy = _unit_direction(points, at_end=True)
    center = [points[-1][0] - dx * setback, points[-1][1] - dy * setback]
    nx, ny = -dy, dx
    half = max(0.5, width / 2.0)
    return (
        [[center[0] - nx * half, center[1] - ny * half], [center[0] + nx * half, center[1] + ny * half]],
        center,
        (dx, dy),
    )


def _quality(source: str, crosswalks: list[dict], stop_lines: list[dict], signals: list[dict], warnings: list[str]) -> dict:
    exact = sum(item.get("source_kind") == "explicit" for item in crosswalks + stop_lines + signals)
    derived = len(crosswalks) + len(stop_lines) + len(signals) - exact
    total = exact + derived
    features = crosswalks + stop_lines + signals
    confidence = sum(_float(item.get("confidence"), 0.0) for item in features)
    score = 1.0 if total == 0 else max(0.0, min(1.0, confidence / total - min(0.25, 0.02 * len(warnings))))
    return {
        "schema": "denseworld.semantic-map-quality.v1",
        "source": source,
        "score": round(score, 3),
        "exact_features": exact,
        "derived_features": derived,
        "crosswalk_count": len(crosswalks),
        "stop_line_count": len(stop_lines),
        "traffic_signal_count": len(signals),
        "warnings": warnings,
    }


def build_sumo_semantics(net_path: Optional[Path]) -> dict[str, Any]:
    """Parse crosswalks and signal bindings from a SUMO net.xml file."""
    empty = {"crosswalks": [], "stop_lines": [], "traffic_signals": []}
    if not net_path or not Path(net_path).is_file():
        empty["semantic_quality"] = _quality("sumo", [], [], [], ["SUMO net file is unavailable"])
        return empty

    root = ET.parse(str(net_path)).getroot()
    lane_info: dict[str, dict[str, Any]] = {}
    crosswalks: list[dict] = []
    stop_lines: list[dict] = []
    signals: list[dict] = []
    warnings: list[str] = []

    for edge in root.findall("edge"):
        edge_id = str(edge.get("id") or "")
        function = str(edge.get("function") or "")
        for lane in edge.findall("lane"):
            lane_id = str(lane.get("id") or "")
            points = _points_from_shape(str(lane.get("shape") or ""))
            width = max(0.4, _float(lane.get("width"), 3.5))
            if lane_id and len(points) >= 2:
                lane_info[lane_id] = {"edge_id": edge_id, "points": points, "width": width, "function": function}
            if function == "crossing" and len(points) >= 2:
                polygon = _outline(points, width)
                if polygon:
                    crosswalks.append(
                        {
                            "id": edge_id or lane_id,
                            "lane_id": lane_id,
                            "polygon": polygon,
                            "centerline": points,
                            "width": width,
                            "stripe_spacing": 0.8,
                            "source": "sumo.edge[function=crossing]",
                            "source_kind": "explicit",
                            "confidence": 1.0,
                        }
                    )

    controlled_lanes: dict[tuple[str, str], dict[str, Any]] = {}
    pedestrian_lanes: dict[tuple[str, str], dict[str, Any]] = {}
    for connection in root.findall("connection"):
        tl_id = str(connection.get("tl") or "")
        if not tl_id:
            continue
        from_edge = str(connection.get("from") or "")
        from_lane = str(connection.get("fromLane") or "0")
        lane_id = f"{from_edge}_{from_lane}"
        lane = lane_info.get(lane_id)
        if not lane:
            warnings.append(f"Signal {tl_id} references missing incoming lane {lane_id}")
            continue
        link_index = str(connection.get("linkIndex") or "0")
        state_key = f"{tl_id}:{link_index}"
        key = (tl_id, lane_id)
        collection = pedestrian_lanes if lane.get("function") in {"crossing", "walkingarea"} else controlled_lanes
        item = collection.setdefault(key, {"lane": lane, "state_keys": [], "link_indices": []})
        if state_key not in item["state_keys"]:
            item["state_keys"].append(state_key)
            item["link_indices"].append(int(link_index))

    for index, ((tl_id, lane_id), item) in enumerate(sorted(controlled_lanes.items())):
        lane = item["lane"]
        points = lane["points"]
        width = lane["width"]
        line, center, (dx, dy) = _line_across_lane(points, width, setback=0.6)
        stop_id = f"sumo-stop-{tl_id}-{lane_id}"
        stop_lines.append(
            {
                "id": stop_id,
                "lane_id": lane_id,
                "points": line,
                "state_keys": item["state_keys"],
                "source": "sumo.connection",
                "source_kind": "derived",
                "confidence": 0.95,
            }
        )
        nx, ny = -dy, dx
        signal_position = [center[0] - nx * (width / 2.0 + 0.8), center[1] - ny * (width / 2.0 + 0.8)]
        mast_arm_end = [center[0] + nx * (width / 2.0 + 0.2), center[1] + ny * (width / 2.0 + 0.2)]
        signals.append(
            {
                "id": f"sumo-signal-{index}",
                "controller_id": tl_id,
                "lane_id": lane_id,
                "position": signal_position,
                "mast_arm_end": mast_arm_end,
                "head_positions": [
                    {
                        "movement": "combined",
                        "position": [center[0], center[1]],
                        "state_keys": list(item["state_keys"]),
                    }
                ],
                "heading": math.atan2(dy, dx),
                "state_keys": item["state_keys"],
                "link_indices": item["link_indices"],
                "source": "sumo.connection",
                "source_kind": "derived",
                "confidence": 0.92,
            }
        )

    for (tl_id, lane_id), item in sorted(pedestrian_lanes.items()):
        lane = item["lane"]
        points = lane["points"]
        width = lane["width"]
        _line, center, (dx, dy) = _line_across_lane(points, width, setback=0.25)
        nx, ny = -dy, dx
        signals.append(
            {
                "id": f"sumo-pedestrian-signal-{tl_id}-{lane_id}",
                "controller_id": tl_id,
                "lane_id": lane_id,
                "signal_type": "pedestrian",
                "position": [center[0] - nx * (width / 2.0 + 0.4), center[1] - ny * (width / 2.0 + 0.4)],
                "heading": math.atan2(dy, dx),
                "state_keys": item["state_keys"],
                "link_indices": item["link_indices"],
                "source": "sumo pedestrian connection",
                "source_kind": "derived",
                "confidence": 0.88,
            }
        )

    if controlled_lanes and not signals:
        warnings.append("Traffic-light programs exist but no signal geometry was generated")
    result = {"crosswalks": crosswalks, "stop_lines": stop_lines, "traffic_signals": signals}
    result["semantic_quality"] = _quality("sumo", crosswalks, stop_lines, signals, warnings[:100])
    return result


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _angle_distance(first: float, second: float) -> float:
    return abs((first - second + math.pi) % (2.0 * math.pi) - math.pi)


def _mean_heading(values: Iterable[float]) -> float:
    values = list(values)
    return math.atan2(sum(math.sin(value) for value in values), sum(math.cos(value) for value in values))


def build_citynde_semantics(map_obj: Any) -> dict[str, Any]:
    """Derive conservative control geometry from CityNDE intersection lanes."""
    polylines = _attribute(map_obj, "polyline_dict", {}) or {}
    try:
        traffic_light_ids = list(map_obj.get_intersection_polyline_id())
        movement_by_id = map_obj.get_intersection_polyline_direction(traffic_light_ids)
    except (AttributeError, TypeError, ValueError):
        movement_by_id = {}
    candidates: list[dict[str, Any]] = []
    for polyline_id, polyline in polylines.items():
        if int(_attribute(polyline, "type", 0) or 0) != 4:
            continue
        points = _xy_points(_attribute(polyline, "points"))
        if len(points) < 2:
            continue
        previous_ids = list(_attribute(polyline, "prev_lanes_id", []) or [])
        is_entry = not previous_ids or any(
            int(_attribute(polylines.get(previous_id), "type", -1) or -1) != 4 for previous_id in previous_ids
        )
        if not is_entry:
            continue
        dx, dy = _unit_direction(points, at_end=False)
        candidates.append(
            {
                "id": str(polyline_id),
                "raw_id": polyline_id,
                "point": points[0],
                "heading": math.atan2(dy, dx),
                "movement": str(movement_by_id.get(polyline_id) or ""),
                "signal_group": str(_attribute(polyline, "trafficwm_signal_group", "") or ""),
            }
        )

    groups: list[list[dict[str, Any]]] = []
    for candidate in candidates:
        explicit_group = candidate.get("signal_group") or ""
        if explicit_group:
            selected = next(
                (
                    group
                    for group in groups
                    if group and group[0].get("signal_group") == explicit_group
                ),
                None,
            )
            if selected is None:
                groups.append([candidate])
            else:
                selected.append(candidate)
            continue
        matching_groups = []
        for group in groups:
            if any(
                not member.get("signal_group")
                and math.hypot(
                    candidate["point"][0] - member["point"][0],
                    candidate["point"][1] - member["point"][1],
                )
                <= 9.0
                and _angle_distance(candidate["heading"], member["heading"])
                <= math.radians(25.0)
                for member in group
            ):
                matching_groups.append(group)
        if not matching_groups:
            groups.append([candidate])
            continue
        selected = matching_groups[0]
        selected.append(candidate)
        for duplicate in matching_groups[1:]:
            selected.extend(duplicate)
            groups.remove(duplicate)

    crosswalks: list[dict] = []
    stop_lines: list[dict] = []
    signals: list[dict] = []
    for index, group in enumerate(groups):
        heading = _mean_heading(item["heading"] for item in group)
        dx, dy = math.cos(heading), math.sin(heading)
        nx, ny = -dy, dx
        center = [sum(item["point"][0] for item in group) / len(group), sum(item["point"][1] for item in group) / len(group)]
        lateral = [(item["point"][0] - center[0]) * nx + (item["point"][1] - center[1]) * ny for item in group]
        left_extent = min(lateral) - 1.8
        right_extent = max(lateral) + 1.8
        stop_center = [center[0] - dx * 0.7, center[1] - dy * 0.7]
        stop_points = [
            [stop_center[0] + nx * left_extent, stop_center[1] + ny * left_extent],
            [stop_center[0] + nx * right_extent, stop_center[1] + ny * right_extent],
        ]
        state_keys = [item["id"] for item in group]
        movement_groups: dict[str, list[str]] = {}
        for item in group:
            movement = item.get("movement") or "unknown"
            movement_groups.setdefault(movement, []).append(item["id"])
        stop_lines.append(
            {
                "id": f"cnde-stop-{index}",
                "points": stop_points,
                "lane_ids": state_keys,
                "state_keys": state_keys,
                "source": "CityNDE type=4 entry lanes",
                "source_kind": "derived",
                "confidence": 0.72,
            }
        )
        crossing_center = [center[0] + dx * 1.6, center[1] + dy * 1.6]
        half_depth = 1.75
        crossing_start = [crossing_center[0] + nx * left_extent, crossing_center[1] + ny * left_extent]
        crossing_end = [crossing_center[0] + nx * right_extent, crossing_center[1] + ny * right_extent]
        waiting_start = [
            crossing_start[0] - nx * CITYNDE_SIDEWALK_WAITING_CLEARANCE_M,
            crossing_start[1] - ny * CITYNDE_SIDEWALK_WAITING_CLEARANCE_M,
        ]
        waiting_end = [
            crossing_end[0] + nx * CITYNDE_SIDEWALK_WAITING_CLEARANCE_M,
            crossing_end[1] + ny * CITYNDE_SIDEWALK_WAITING_CLEARANCE_M,
        ]
        road_axis = "ew" if abs(dx) >= abs(dy) else "ns"
        crossing_axis = "ns" if road_axis == "ew" else "ew"
        polygon = [
            [crossing_center[0] + nx * left_extent - dx * half_depth, crossing_center[1] + ny * left_extent - dy * half_depth],
            [crossing_center[0] + nx * right_extent - dx * half_depth, crossing_center[1] + ny * right_extent - dy * half_depth],
            [crossing_center[0] + nx * right_extent + dx * half_depth, crossing_center[1] + ny * right_extent + dy * half_depth],
            [crossing_center[0] + nx * left_extent + dx * half_depth, crossing_center[1] + ny * left_extent + dy * half_depth],
        ]
        polygon.append(polygon[0])
        crosswalks.append(
            {
                "id": f"cnde-crosswalk-{index}",
                "polygon": polygon,
                "centerline": [crossing_start, crossing_end],
                "waiting_points": [waiting_start, waiting_end],
                "width": 3.5,
                "stripe_spacing": 0.8,
                "signalized": True,
                "state_keys": state_keys,
                "road_axis": road_axis,
                "crossing_axis": crossing_axis,
                "allowed_actor_types": ["pedestrian", "cyclist"],
                "source": "CityNDE type=4 entry lanes",
                "source_kind": "derived",
                "confidence": 0.58,
            }
        )
        pole_offset = right_extent + 0.9
        pole_position = [
            stop_center[0] + nx * pole_offset,
            stop_center[1] + ny * pole_offset,
        ]
        mast_arm_end = [
            stop_center[0] + nx * (left_extent - 0.35),
            stop_center[1] + ny * (left_extent - 0.35),
        ]
        head_positions = []
        for movement, lane_ids in sorted(movement_groups.items()):
            members = [item for item in group if item["id"] in lane_ids]
            if not members:
                continue
            head_positions.append(
                {
                    "movement": movement,
                    "position": [
                        sum(item["point"][0] for item in members) / len(members) - dx * 0.7,
                        sum(item["point"][1] for item in members) / len(members) - dy * 0.7,
                    ],
                    "state_keys": list(lane_ids),
                }
            )
        signals.append(
            {
                "id": f"cnde-signal-{index}",
                "position": pole_position,
                "mast_arm_end": mast_arm_end,
                "head_positions": head_positions,
                "heading": heading,
                "state_keys": state_keys,
                "heads": min(3, max(1, len(movement_groups))),
                "controlled_lane_count": len(group),
                "movement_groups": movement_groups,
                "source": "CityNDE type=4 entry lanes",
                "source_kind": "derived",
                "confidence": 0.7,
            }
        )

    warnings = []
    if candidates:
        warnings.append("CityNDE has no explicit crosswalk or pole labels; geometry is derived from signalized entry lanes")
    result = {"crosswalks": crosswalks, "stop_lines": stop_lines, "traffic_signals": signals}
    result["semantic_quality"] = _quality("citynde", crosswalks, stop_lines, signals, warnings)
    return result
