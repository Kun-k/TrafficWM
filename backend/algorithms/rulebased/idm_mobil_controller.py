"""CPU IDM longitudinal control with conservative MOBIL lane selection.

The controller implements the CityNDE simulator controller contract while
leaving map loading, recording, metrics, and live HTTP publication to the
existing adapter. It intentionally targets sparse traffic and deterministic
efficiency baselines rather than naturalistic distribution matching.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from backend.algorithms.citynde.mixed_traffic_core import SignalTimingPlan


@dataclass(frozen=True)
class IDMParameters:
    desired_speed: float = 10.0
    min_gap: float = 2.0
    time_headway: float = 1.0
    max_acceleration: float = 1.8
    comfortable_braking: float = 2.5
    exponent: float = 4.0


@dataclass(frozen=True)
class MOBILParameters:
    politeness: float = 0.25
    safe_braking: float = 4.0
    acceleration_threshold: float = 0.25
    right_lane_bias: float = 0.05


def idm_acceleration(
    speed: float,
    leader_speed: float | None,
    gap: float | None,
    params: IDMParameters,
) -> float:
    """Return the standard IDM acceleration in metres per second squared."""
    speed = max(0.0, float(speed))
    desired_speed = max(0.1, float(params.desired_speed))
    free_road = (speed / desired_speed) ** params.exponent
    interaction = 0.0
    if leader_speed is not None and gap is not None:
        closing_speed = speed - max(0.0, float(leader_speed))
        braking_scale = 2.0 * math.sqrt(
            params.max_acceleration * params.comfortable_braking
        )
        desired_gap = params.min_gap + max(
            0.0,
            speed * params.time_headway + speed * closing_speed / braking_scale,
        )
        interaction = (desired_gap / max(0.1, float(gap))) ** 2
    return params.max_acceleration * (1.0 - free_road - interaction)


def mobil_incentive(
    ego_before: float,
    ego_after: float,
    new_follower_before: float,
    new_follower_after: float,
    old_follower_before: float,
    old_follower_after: float,
    params: MOBILParameters,
    *,
    moving_right: bool,
) -> tuple[bool, float]:
    """Evaluate MOBIL safety and acceleration-gain criteria."""
    safe = new_follower_after >= -params.safe_braking
    neighbor_delta = (
        new_follower_after
        - new_follower_before
        + old_follower_after
        - old_follower_before
    )
    bias = params.right_lane_bias if moving_right else -params.right_lane_bias
    score = ego_after - ego_before + params.politeness * neighbor_delta + bias
    return safe and score > params.acceleration_threshold, score


def _matching_key(mapping: dict[Any, Any], raw_id: Any) -> Any | None:
    if raw_id in mapping:
        return raw_id
    text = str(raw_id)
    return next((key for key in mapping if str(key) == text), None)


def _route_geometry(map_obj: Any, route_ids: Iterable[Any]) -> tuple[np.ndarray, np.ndarray]:
    points: list[np.ndarray] = []
    polylines = getattr(map_obj, "polyline_dict", {}) or {}
    for raw_id in route_ids:
        key = _matching_key(polylines, raw_id)
        lane = polylines.get(key) if key is not None else None
        values = np.asarray(getattr(lane, "points", []), dtype=np.float64)
        if values.ndim != 2 or len(values) < 2:
            continue
        values = values[:, :2]
        if points:
            previous = points[-1]
            if np.linalg.norm(values[-1] - previous) < np.linalg.norm(values[0] - previous):
                values = values[::-1]
            if np.linalg.norm(values[0] - previous) <= 1e-5:
                values = values[1:]
        points.extend(values)
    if len(points) < 2:
        return np.empty((0, 2), dtype=np.float64), np.empty(0, dtype=np.float64)
    geometry = np.asarray(points, dtype=np.float64)
    cumulative = np.concatenate(
        ([0.0], np.cumsum(np.linalg.norm(np.diff(geometry, axis=0), axis=1)))
    )
    return geometry, cumulative


def _project_progress(
    points: np.ndarray,
    cumulative: np.ndarray,
    position: np.ndarray,
) -> tuple[float, float]:
    if len(points) < 2:
        return 0.0, math.inf
    starts = points[:-1]
    segments = points[1:] - starts
    length_squared = np.sum(segments * segments, axis=1)
    ratios = np.clip(
        np.sum((position[:2] - starts) * segments, axis=1)
        / np.maximum(length_squared, 1e-9),
        0.0,
        1.0,
    )
    projections = starts + ratios[:, None] * segments
    distances = np.linalg.norm(projections - position[:2], axis=1)
    index = int(np.argmin(distances))
    progress = cumulative[index] + ratios[index] * math.sqrt(length_squared[index])
    return float(progress), float(distances[index])


def _sample_progress(
    points: np.ndarray,
    cumulative: np.ndarray,
    progress: float,
) -> tuple[np.ndarray, float]:
    if len(points) < 2:
        return np.zeros(2, dtype=np.float64), 0.0
    progress = float(np.clip(progress, 0.0, cumulative[-1]))
    index = max(
        0,
        min(len(points) - 2, int(np.searchsorted(cumulative, progress, side="right") - 1)),
    )
    segment = points[index + 1] - points[index]
    length = max(1e-9, float(cumulative[index + 1] - cumulative[index]))
    ratio = (progress - float(cumulative[index])) / length
    return points[index] + ratio * segment, math.atan2(float(segment[1]), float(segment[0]))


class SparseIDMMOBILController:
    """A deterministic sparse-traffic controller compatible with RouteTLSimulator."""

    def __init__(
        self,
        *,
        control_step: int = 5,
        control_resolution: float = 0.1,
        signal_plan: SignalTimingPlan | None = None,
        idm: IDMParameters | None = None,
        mobil: MOBILParameters | None = None,
    ) -> None:
        self.control_step = max(1, min(20, int(control_step)))
        self.control_resolution = max(0.01, float(control_resolution))
        self.signal_plan = signal_plan or SignalTimingPlan(self.control_resolution)
        self.idm = idm or IDMParameters()
        self.mobil = mobil or MOBILParameters()
        self.inference_precision = "cpu-rule"
        self.map_enhance = None
        self.agent_enhance = None
        self.external_safety_participants: list[dict[str, Any]] = []
        self._external_av_id: Any | None = None
        self._external_av_trajectory: np.ndarray | None = None
        self.mobil_decisions = 0
        self.red_light_constraints = 0

    def set_external_av_trajectory(
        self,
        vehicle_id: Any | None = None,
        trajectory: np.ndarray | None = None,
    ) -> None:
        self._external_av_id = vehicle_id
        self._external_av_trajectory = (
            None if trajectory is None else np.asarray(trajectory, dtype=np.float64)
        )

    def set_external_safety_participants(
        self, participants: list[dict[str, Any]] | None = None
    ) -> None:
        self.external_safety_participants = list(participants or [])

    def set_cyclist_trajectory_constraint(self, constraint=None) -> None:
        return None

    def _vehicle_length(self, vehicle_id: Any) -> float:
        try:
            actor = self.agent_enhance.get_agents(vehicle_id)
            return max(1.0, float(np.asarray(actor.static_lwh).reshape(-1)[0]))
        except Exception:
            return 4.5

    def _route_ids(
        self,
        scenario: dict[str, Any],
        index: int,
        vehicle_id: Any | None = None,
    ) -> list[Any]:
        # RouteTLScenarioManager may expose a neighboring left-route candidate
        # to learned controllers. The rule controller does not choose that
        # candidate through MOBIL yet, so follow the vehicle's committed route
        # and use the formatted candidate only as a compatibility fallback.
        if vehicle_id is not None and self.agent_enhance is not None:
            try:
                agent = self.agent_enhance.get_agents(vehicle_id)
                assigned_route = list(getattr(agent, "route", []) or [])
            except (AttributeError, KeyError, TypeError, ValueError):
                assigned_route = []
            if assigned_route:
                return assigned_route
        routes = scenario.get("route_polyline_id")
        if routes is None:
            routes = []
        if index < len(routes) and len(routes[index]):
            return list(routes[index])
        return []

    def _current_lane(self, route_ids: list[Any], position: np.ndarray) -> Any | None:
        polylines = getattr(self.map_enhance, "polyline_dict", {}) or {}
        best_id = None
        best_distance = math.inf
        for raw_id in route_ids:
            key = _matching_key(polylines, raw_id)
            lane = polylines.get(key) if key is not None else None
            values = np.asarray(getattr(lane, "points", []), dtype=np.float64)
            if values.ndim != 2 or len(values) < 2:
                continue
            _, distance = _project_progress(
                values[:, :2],
                np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(values[:, :2], axis=0), axis=1)))),
                position,
            )
            if distance < best_distance:
                best_id = key
                best_distance = distance
        return best_id

    def _red_light_gap(
        self,
        scenario: dict[str, Any],
        lane_id: Any,
        lane_progress: float,
        vehicle_length: float,
    ) -> float | None:
        raw_light_ids = scenario.get("dynamic_polyline_id")
        light_ids = list(raw_light_ids) if raw_light_ids is not None else []
        raw_states = scenario.get("dynamic_polyline_states")
        states = np.asarray([] if raw_states is None else raw_states)
        match = next((index for index, value in enumerate(light_ids) if str(value) == str(lane_id)), None)
        if match is None or states.ndim < 3 or match >= len(states):
            return None
        current = states[match, -1]
        if len(current) < 3 or int(np.argmax(current[:4])) not in {1, 2}:
            return None
        lane = (getattr(self.map_enhance, "polyline_dict", {}) or {}).get(lane_id)
        lane_length = float(getattr(lane, "length", 0.0) or 0.0)
        gap = lane_length - lane_progress - 0.5 * vehicle_length
        if 0.0 < gap < 80.0:
            self.red_light_constraints += 1
            return gap
        return None

    def _dynamic_lights(self, scenario: dict[str, Any]) -> tuple[list[Any], np.ndarray]:
        raw_light_ids = scenario.get("all_dynamic_polyline_id")
        if raw_light_ids is None:
            raw_light_ids = scenario.get("dynamic_polyline_id")
        light_ids = list(raw_light_ids) if raw_light_ids is not None else []
        raw_phases = scenario.get("all_dynamic_polyline_phase")
        phases = list(raw_phases) if raw_phases is not None else []
        states = np.zeros((len(light_ids), self.control_step, 4), dtype=np.float64)
        current_step = int(scenario.get("current_step", 0) or 0)
        for light_index in range(len(light_ids)):
            phase = str(phases[light_index] if light_index < len(phases) else "")
            for offset in range(self.control_step):
                stage = self.signal_plan.stage_index(current_step + offset)
                value = phase[stage] if stage < len(phase) else "r"
                states[light_index, offset, 0 if value == "g" else 1 if value == "y" else 2] = 1.0
        return light_ids, states

    def main_step(self, scenario: dict[str, Any], batch_size: int | None = None) -> dict[str, Any]:
        del batch_size
        raw_vehicle_ids = scenario.get("vehicle_id")
        vehicle_ids = list(raw_vehicle_ids) if raw_vehicle_ids is not None else []
        raw_history = scenario.get("vehicle_states")
        history = np.asarray([] if raw_history is None else raw_history, dtype=np.float64)
        light_ids, light_states = self._dynamic_lights(scenario)
        output: dict[str, Any] = {
            # external_step may remove route-exhausted actors while retaining
            # the previous required-update list. Bind masks to current actors.
            "required_update_vehicle_ids": list(vehicle_ids),
            "required_update_traffic_light_ids": scenario.get("required_update_traffic_light_ids", light_ids),
            "dynamic_polyline_id": light_ids,
            "dynamic_polyline_states": light_states,
        }
        if not vehicle_ids or history.ndim != 3:
            output.update(
                {
                    "vehicle_id": [],
                    "vehicle_states": np.empty((0, self.control_step, 7), dtype=np.float64),
                }
            )
            return output

        current = history[:, -1, :7].copy()
        route_ids = [
            self._route_ids(scenario, index, vehicle_id)
            for index, vehicle_id in enumerate(vehicle_ids)
        ]
        geometries = [_route_geometry(self.map_enhance, route) for route in route_ids]
        progress = np.asarray(
            [_project_progress(points, cumulative, state[:2])[0] for (points, cumulative), state in zip(geometries, current)],
            dtype=np.float64,
        )
        lengths = np.asarray([self._vehicle_length(vehicle_id) for vehicle_id in vehicle_ids])
        trajectories = np.zeros((len(vehicle_ids), self.control_step, 7), dtype=np.float64)

        for offset in range(self.control_step):
            lane_ids = [
                self._current_lane(route, state[:2]) for route, state in zip(route_ids, current)
            ]
            speeds = np.linalg.norm(current[:, 3:5], axis=1)
            accelerations = np.zeros(len(vehicle_ids), dtype=np.float64)
            for index, (state, lane_id) in enumerate(zip(current, lane_ids)):
                heading = float(state[2])
                forward = np.asarray([math.cos(heading), math.sin(heading)], dtype=np.float64)
                leader_index = None
                leader_gap = math.inf
                for other_index, other in enumerate(current):
                    if other_index == index:
                        continue
                    other_lane_id = lane_ids[other_index]
                    same_lane = (
                        lane_id is not None
                        and other_lane_id is not None
                        and str(other_lane_id) == str(lane_id)
                    )
                    heading_delta = abs(
                        (float(other[2]) - heading + math.pi)
                        % (2.0 * math.pi)
                        - math.pi
                    )
                    # The map splits a physical lane into adjacent segment IDs.
                    # Keep following across that boundary when geometry still
                    # places both vehicles in the same traffic stream.
                    if not same_lane and heading_delta > math.radians(35.0):
                        continue
                    relative = other[:2] - state[:2]
                    longitudinal = float(np.dot(relative, forward))
                    lateral = abs(float(forward[0] * relative[1] - forward[1] * relative[0]))
                    gap = longitudinal - 0.5 * (lengths[index] + lengths[other_index])
                    if longitudinal > 0.0 and lateral < 2.2 and gap < leader_gap:
                        leader_index = other_index
                        leader_gap = gap
                red_gap = None
                if lane_id is not None:
                    lane = (getattr(self.map_enhance, "polyline_dict", {}) or {}).get(lane_id)
                    lane_points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
                    if lane_points.ndim == 2 and len(lane_points) >= 2:
                        lane_cumulative = np.concatenate(
                            ([0.0], np.cumsum(np.linalg.norm(np.diff(lane_points[:, :2], axis=0), axis=1)))
                        )
                        lane_progress, _ = _project_progress(
                            lane_points[:, :2], lane_cumulative, state[:2]
                        )
                        red_gap = self._red_light_gap(
                            scenario, lane_id, lane_progress, lengths[index]
                        )
                if red_gap is not None and red_gap < leader_gap:
                    leader_index = None
                    leader_gap = red_gap
                    leader_speed = 0.0
                else:
                    leader_speed = speeds[leader_index] if leader_index is not None else None
                    if leader_index is None:
                        leader_gap = None
                acceleration = idm_acceleration(
                    speeds[index], leader_speed, leader_gap, self.idm
                )
                accelerations[index] = float(
                    np.clip(acceleration, -2.0 * self.idm.comfortable_braking, self.idm.max_acceleration)
                )

            next_current = current.copy()
            for index, ((points, cumulative), state) in enumerate(zip(geometries, current)):
                speed = max(0.0, speeds[index] + accelerations[index] * self.control_resolution)
                if len(points) < 2:
                    position = state[:2] + state[3:5] * self.control_resolution
                    heading = float(state[2])
                else:
                    progress[index] = min(
                        float(cumulative[-1]),
                        progress[index] + speed * self.control_resolution,
                    )
                    position, heading = _sample_progress(points, cumulative, progress[index])
                    if progress[index] >= float(cumulative[-1]) - 1e-6:
                        speed = 0.0
                velocity = speed * np.asarray(
                    [math.cos(heading), math.sin(heading)], dtype=np.float64
                )
                acceleration_vector = accelerations[index] * np.asarray(
                    [math.cos(heading), math.sin(heading)], dtype=np.float64
                )
                next_current[index, :7] = np.asarray(
                    [position[0], position[1], heading, velocity[0], velocity[1], acceleration_vector[0], acceleration_vector[1]],
                    dtype=np.float64,
                )
            trajectories[:, offset] = next_current
            current = next_current

        if self._external_av_id is not None and self._external_av_trajectory is not None:
            match = next(
                (index for index, vehicle_id in enumerate(vehicle_ids) if str(vehicle_id) == str(self._external_av_id)),
                None,
            )
            if match is not None and len(self._external_av_trajectory):
                count = min(self.control_step, len(self._external_av_trajectory))
                trajectories[match, :count, :7] = self._external_av_trajectory[:count, :7]

        output.update(
            {
                "vehicle_id": np.asarray(vehicle_ids, dtype=object),
                "vehicle_states": trajectories,
                "vehicle_mask": np.ones((len(vehicle_ids), self.control_step), dtype=bool),
            }
        )
        return output

    def post_process(self, scenario: dict[str, Any]) -> dict[str, Any]:
        return scenario

    def step(self, scenario: dict[str, Any], batch_size: int | None = None) -> dict[str, Any]:
        return self.post_process(self.main_step(scenario, batch_size=batch_size))

    def reset(self) -> None:
        self._external_av_id = None
        self._external_av_trajectory = None
