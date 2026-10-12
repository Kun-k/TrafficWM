"""Route helpers for long-running DenseWorld CityNDE experiments."""
from __future__ import annotations

import math
from typing import Any


def _attribute(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _polyline_type(value: Any) -> int:
    try:
        return int(_attribute(value, "type", -1))
    except (TypeError, ValueError):
        return -1


def _lane_neighbors(map_obj: Any, lane_id: Any) -> list[Any]:
    polylines = _attribute(map_obj, "polyline_dict", {}) or {}
    lane = polylines.get(lane_id)
    if lane is None:
        return []
    return [
        candidate
        for candidate in list(_attribute(lane, "next_lanes_id", []) or [])
        if candidate in polylines
        and _polyline_type(polylines[candidate]) in {0, 4}
    ]


def find_reachable_lane_cycle(
    map_obj: Any,
    start_lane: Any,
    *,
    max_visited_lanes: int = 10000,
) -> tuple[list[Any], list[Any]]:
    """Return the path to and one directed cycle reachable from ``start_lane``."""
    if not _lane_neighbors(map_obj, start_lane):
        return [], []
    path = [start_lane]
    path_index = {start_lane: 0}
    visited: set[Any] = set()
    stack: list[tuple[Any, list[Any], int]] = [
        (start_lane, _lane_neighbors(map_obj, start_lane), 0)
    ]
    while stack and len(visited) <= max(1, int(max_visited_lanes)):
        node, neighbors, offset = stack[-1]
        if offset >= len(neighbors):
            stack.pop()
            visited.add(node)
            path_index.pop(node, None)
            path.pop()
            continue
        neighbor = neighbors[offset]
        stack[-1] = (node, neighbors, offset + 1)
        if neighbor in path_index:
            cycle_start = path_index[neighbor]
            return list(path[:cycle_start]), list(path[cycle_start:])
        if neighbor in visited:
            continue
        path_index[neighbor] = len(path)
        path.append(neighbor)
        stack.append((neighbor, _lane_neighbors(map_obj, neighbor), 0))
    return [], []


def repeated_cycle_route(
    prefix: list[Any],
    cycle: list[Any],
    *,
    minimum_lane_count: int = 64,
) -> list[Any]:
    if not cycle:
        return list(prefix)
    route = list(prefix)
    target_lane_count = max(len(route) + len(cycle), int(minimum_lane_count))
    while len(route) < target_lane_count:
        route.extend(cycle)
    return route


def cycle_route_window(
    prefix: list[Any],
    cycle: list[Any],
    *,
    maximum_lane_count: int = 8,
) -> list[Any]:
    """Build a connected route window accepted by CityNDE's route table.

    CityNDE generates route candidates with a depth of eight. Supplying a
    longer repeated cycle makes its native suffix lookup fail as soon as the
    vehicle enters the next lane. The adapter refreshes this bounded window
    before each model rollout instead.
    """
    limit = max(1, int(maximum_lane_count))
    route = list(prefix)
    if cycle:
        while len(route) < limit:
            route.extend(cycle)
    return route[:limit]


def route_spatial_extent(
    map_obj: Any,
    route: list[Any],
    origin_xy: tuple[float, float] | list[float],
) -> float:
    """Return the farthest route-map point from ``origin_xy`` in metres."""
    try:
        origin_x, origin_y = float(origin_xy[0]), float(origin_xy[1])
    except (IndexError, TypeError, ValueError):
        return math.inf
    polylines = _attribute(map_obj, "polyline_dict", {}) or {}
    maximum = 0.0
    found = False
    for lane_id in route:
        lane = polylines.get(lane_id)
        points = _attribute(lane, "points", [])
        if points is None:
            continue
        for point in points:
            try:
                distance = math.hypot(float(point[0]) - origin_x, float(point[1]) - origin_y)
            except (IndexError, TypeError, ValueError):
                continue
            maximum = max(maximum, distance)
            found = True
    return maximum if found else math.inf
