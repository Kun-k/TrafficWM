"""Conservative signal control for CityNDE maps without signalized lanes."""
from __future__ import annotations

import math
from typing import Any


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _set_attribute(value: Any, name: str, replacement: Any) -> None:
    if isinstance(value, dict):
        value[name] = replacement
    else:
        setattr(value, name, replacement)


def _polyline_type(value: Any) -> int:
    try:
        return int(_attribute(value, "type", -1))
    except (TypeError, ValueError):
        return -1


def _endpoint_and_heading(polyline: Any) -> tuple[tuple[float, float], float] | None:
    points = _attribute(polyline, "points", _attribute(polyline, "states", None))
    if points is None or len(points) < 2:
        return None
    x0, y0 = float(points[-2][0]), float(points[-2][1])
    x1, y1 = float(points[-1][0]), float(points[-1][1])
    if math.hypot(x1 - x0, y1 - y0) < 1e-6:
        return None
    return (x1, y1), math.atan2(y1 - y0, x1 - x0)


def signalize_unsignalized_citynde_map(
    map_obj: Any,
    *,
    enabled: bool,
    max_intersections: int = 12,
    cluster_radius_m: float = 22.0,
    minimum_heading_bins: int = 4,
) -> dict[str, Any]:
    """Mark a small set of high-confidence intersection connectors as type 4.

    NuPlan Boston has lane connectivity but no CityNDE ``type=4`` signal lanes.
    Branch approaches are clustered spatially; only clusters with approaches in
    at least four 45-degree heading bins are retained. Immediate connector lanes
    are marked, so stop lines remain at the junction rather than upstream.
    """
    polylines = _attribute(map_obj, "polyline_dict", {}) or {}
    existing = [
        lane_id
        for lane_id, lane in polylines.items()
        if _polyline_type(lane) == 4
    ]
    report: dict[str, Any] = {
        "schema": "trafficwm.citynde-signalization.v1",
        "enabled": bool(enabled),
        "applied": False,
        "existing_signal_lane_count": len(existing),
        "selected_intersection_count": 0,
        "marked_signal_lane_count": 0,
        "intersections": [],
    }
    if not enabled or existing:
        setattr(map_obj, "trafficwm_signalization_report", report)
        return report

    candidates: list[dict[str, Any]] = []
    for lane_id, lane in polylines.items():
        if _polyline_type(lane) != 0:
            continue
        next_ids = [
            candidate
            for candidate in list(_attribute(lane, "next_lanes_id", []) or [])
            if candidate in polylines
            and _polyline_type(polylines[candidate]) == 0
        ]
        if len(next_ids) < 2:
            continue
        geometry = _endpoint_and_heading(lane)
        if geometry is None:
            continue
        point, heading = geometry
        candidates.append(
            {
                "lane_id": lane_id,
                "point": point,
                "heading": heading,
                "next_ids": next_ids,
            }
        )

    remaining = set(range(len(candidates)))
    groups: list[list[int]] = []
    radius_squared = float(cluster_radius_m) ** 2
    while remaining:
        seed = remaining.pop()
        group = [seed]
        pending = [seed]
        while pending:
            current = pending.pop()
            cx, cy = candidates[current]["point"]
            connected = [
                index
                for index in remaining
                if (candidates[index]["point"][0] - cx) ** 2
                + (candidates[index]["point"][1] - cy) ** 2
                <= radius_squared
            ]
            for index in connected:
                remaining.remove(index)
                pending.append(index)
                group.append(index)
        groups.append(group)

    viable: list[tuple[int, int, float, float, list[int]]] = []
    for group in groups:
        heading_bins = {
            int(
                math.floor(
                    ((candidates[index]["heading"] + math.pi) % (2.0 * math.pi))
                    / (math.pi / 4.0)
                )
            )
            for index in group
        }
        if len(group) < minimum_heading_bins or len(heading_bins) < minimum_heading_bins:
            continue
        center_x = sum(candidates[index]["point"][0] for index in group) / len(group)
        center_y = sum(candidates[index]["point"][1] for index in group) / len(group)
        viable.append((len(heading_bins), len(group), center_x, center_y, group))

    viable.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    marked: set[Any] = set()
    intersections = []
    for intersection_index, (heading_bin_count, _, center_x, center_y, group) in enumerate(
        viable[: max(0, int(max_intersections))]
    ):
        connector_ids = []
        for index in group:
            approach_bin = int(
                math.floor(
                    ((candidates[index]["heading"] + math.pi / 4.0) % (2.0 * math.pi))
                    / (math.pi / 2.0)
                )
            )
            for lane_id in candidates[index]["next_ids"]:
                if lane_id in marked:
                    continue
                _set_attribute(polylines[lane_id], "type", 4)
                _set_attribute(
                    polylines[lane_id],
                    "trafficwm_signal_group",
                    f"derived-{intersection_index}-approach-{approach_bin}",
                )
                marked.add(lane_id)
                connector_ids.append(str(lane_id))
        if not connector_ids:
            continue
        intersections.append(
            {
                "center": [round(center_x, 3), round(center_y, 3)],
                "approach_count": len(group),
                "heading_bin_count": heading_bin_count,
                "signal_lane_ids": connector_ids,
            }
        )

    report.update(
        {
            "applied": bool(marked),
            "candidate_approach_count": len(candidates),
            "candidate_cluster_count": len(groups),
            "selected_intersection_count": len(intersections),
            "marked_signal_lane_count": len(marked),
            "intersections": intersections,
        }
    )
    polyline_ids = list(_attribute(map_obj, "polyline_ids", []) or [])
    if polyline_ids and hasattr(map_obj, "polyline_type"):
        map_obj.polyline_type = [
            _polyline_type(polylines[lane_id]) for lane_id in polyline_ids
        ]
    setattr(map_obj, "trafficwm_signalization_report", report)
    return report
