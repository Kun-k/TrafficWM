"""Pure mixed-traffic rules shared by CityNDE runtime and tests."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class VehicleProfile:
    name: str
    length: float
    width: float
    height: float
    weight: float

    @property
    def lwh(self) -> np.ndarray:
        return np.asarray([self.length, self.width, self.height], dtype=np.float64)


VEHICLE_PROFILES = (
    VehicleProfile("compact", 4.10, 1.76, 1.48, 0.46),
    VehicleProfile("sedan", 4.65, 1.84, 1.48, 0.27),
    VehicleProfile("suv", 4.75, 1.94, 1.72, 0.14),
    VehicleProfile("van", 5.35, 2.05, 2.35, 0.07),
    VehicleProfile("truck", 7.50, 2.45, 3.20, 0.04),
    VehicleProfile("bus", 10.50, 2.50, 3.25, 0.02),
)


def sample_vehicle_profile(rng: np.random.Generator) -> VehicleProfile:
    weights = np.asarray([profile.weight for profile in VEHICLE_PROFILES], dtype=np.float64)
    weights /= weights.sum()
    return VEHICLE_PROFILES[int(rng.choice(len(VEHICLE_PROFILES), p=weights))]


def constant_speed_history(
    states: np.ndarray,
    speed: float,
    step_seconds: float,
) -> np.ndarray:
    """Rebuild a finite history while preserving its final pose."""
    values = np.asarray(states, dtype=np.float64)
    if values.ndim != 2 or len(values) == 0 or values.shape[1] < 5:
        raise ValueError("states must have shape (T, >=5)")
    final_state = values[-1].copy()
    if not np.isfinite(final_state[:3]).all() or not math.isfinite(float(speed)):
        raise ValueError("final pose and speed must be finite")
    result = values.copy()
    heading = float(final_state[2])
    vx = float(speed) * math.cos(heading)
    vy = float(speed) * math.sin(heading)
    for index in range(len(result)):
        elapsed = (len(result) - index - 1) * float(step_seconds)
        result[index, 0] = final_state[0] - vx * elapsed
        result[index, 1] = final_state[1] - vy * elapsed
        result[index, 2] = heading
        result[index, 3] = vx
        result[index, 4] = vy
        if result.shape[1] >= 7:
            result[index, 5:7] = 0.0
    return result


def agent_state_at_absolute_step(agent: Any, absolute_step: int) -> np.ndarray | None:
    """Read an agent state at simulation time, not at its predicted tail."""
    try:
        state = np.asarray(agent.get_absolute_states(int(absolute_step)), dtype=np.float64)
    except (AttributeError, IndexError, TypeError, ValueError):
        states = np.asarray(getattr(agent, "states", []), dtype=np.float64)
        relative_step = int(absolute_step) - int(getattr(agent, "spawn_time_step", 0))
        if states.ndim != 2 or not 0 <= relative_step < len(states):
            return None
        state = states[relative_step]
    state = np.asarray(state, dtype=np.float64).reshape(-1)
    if state.size < 3 or not np.isfinite(state[:3]).all():
        return None
    return state


def oriented_trajectory_has_clearance(
    candidate_states: np.ndarray,
    candidate_size: Iterable[float],
    obstacles_per_step: Iterable[Iterable[tuple[Iterable[float], Iterable[float]]]],
    *,
    margin: float = 0.0,
) -> bool:
    """Check every backfilled trajectory state against same-time obstacles."""
    states = np.asarray(candidate_states, dtype=np.float64)
    if states.ndim != 2 or states.shape[1] < 3 or not np.isfinite(states[:, :3]).all():
        return False
    obstacle_steps = list(obstacles_per_step)
    if len(obstacle_steps) != len(states):
        return False
    for state, obstacles in zip(states, obstacle_steps):
        for obstacle_pose, obstacle_size in obstacles:
            if oriented_boxes_overlap(
                state[:3],
                candidate_size,
                obstacle_pose,
                obstacle_size,
                margin=margin,
            ):
                return False
    return True


def oriented_boxes_overlap(
    first_pose: Iterable[float],
    first_size: Iterable[float],
    second_pose: Iterable[float],
    second_size: Iterable[float],
    *,
    margin: float = 0.0,
) -> bool:
    """Check two planar oriented boxes with the separating-axis theorem."""
    first = np.asarray(tuple(first_pose), dtype=np.float64).reshape(-1)
    second = np.asarray(tuple(second_pose), dtype=np.float64).reshape(-1)
    first_lw = np.asarray(tuple(first_size), dtype=np.float64).reshape(-1)
    second_lw = np.asarray(tuple(second_size), dtype=np.float64).reshape(-1)
    if min(len(first), len(second)) < 3 or min(len(first_lw), len(second_lw)) < 2:
        raise ValueError("poses require x/y/heading and sizes require length/width")
    cos_first, sin_first = math.cos(float(first[2])), math.sin(float(first[2]))
    cos_second, sin_second = math.cos(float(second[2])), math.sin(float(second[2]))
    delta_x, delta_y = float(second[0] - first[0]), float(second[1] - first[1])
    clearance = max(0.0, float(margin))
    for axis_x, axis_y in (
        (cos_first, sin_first),
        (-sin_first, cos_first),
        (cos_second, sin_second),
        (-sin_second, cos_second),
    ):
        center_distance = abs(delta_x * axis_x + delta_y * axis_y)
        first_radius = 0.5 * (
            first_lw[0] * abs(cos_first * axis_x + sin_first * axis_y)
            + first_lw[1] * abs(-sin_first * axis_x + cos_first * axis_y)
        )
        second_radius = 0.5 * (
            second_lw[0] * abs(cos_second * axis_x + sin_second * axis_y)
            + second_lw[1] * abs(-sin_second * axis_x + cos_second * axis_y)
        )
        if center_distance > first_radius + second_radius + clearance:
            return False
    return True


def _oriented_box_overlap_depth(
    first_pose: Iterable[float],
    first_size: Iterable[float],
    second_pose: Iterable[float],
    second_size: Iterable[float],
    *,
    margin: float = 0.0,
) -> float:
    """Return the minimum SAT penetration depth, or zero for separated boxes."""
    first = np.asarray(tuple(first_pose), dtype=np.float64).reshape(-1)
    second = np.asarray(tuple(second_pose), dtype=np.float64).reshape(-1)
    first_lw = np.asarray(tuple(first_size), dtype=np.float64).reshape(-1)
    second_lw = np.asarray(tuple(second_size), dtype=np.float64).reshape(-1)
    if min(len(first), len(second)) < 3 or min(len(first_lw), len(second_lw)) < 2:
        raise ValueError("poses require x/y/heading and sizes require length/width")
    cos_first, sin_first = math.cos(float(first[2])), math.sin(float(first[2]))
    cos_second, sin_second = math.cos(float(second[2])), math.sin(float(second[2]))
    delta_x, delta_y = float(second[0] - first[0]), float(second[1] - first[1])
    clearance = max(0.0, float(margin))
    minimum_overlap = math.inf
    for axis_x, axis_y in (
        (cos_first, sin_first),
        (-sin_first, cos_first),
        (cos_second, sin_second),
        (-sin_second, cos_second),
    ):
        center_distance = abs(delta_x * axis_x + delta_y * axis_y)
        first_radius = 0.5 * (
            first_lw[0] * abs(cos_first * axis_x + sin_first * axis_y)
            + first_lw[1] * abs(-sin_first * axis_x + cos_first * axis_y)
        )
        second_radius = 0.5 * (
            second_lw[0] * abs(cos_second * axis_x + sin_second * axis_y)
            + second_lw[1] * abs(-sin_second * axis_x + cos_second * axis_y)
        )
        overlap = first_radius + second_radius + clearance - center_distance
        if overlap < 0.0:
            return 0.0
        minimum_overlap = min(minimum_overlap, overlap)
    return max(0.0, float(minimum_overlap))


def stop_trajectory_before_oriented_obstacle(
    trajectory: np.ndarray,
    *,
    current_state: np.ndarray,
    actor_size: Iterable[float],
    obstacle_trajectory: np.ndarray,
    obstacle_size: Iterable[float],
    margin: float = 0.5,
) -> tuple[np.ndarray, bool, int | None]:
    """Freeze a predicted actor at the latest pose that stays clear of an obstacle."""
    output = np.asarray(trajectory, dtype=np.float64).copy()
    obstacle = np.asarray(obstacle_trajectory, dtype=np.float64)
    current = np.asarray(current_state, dtype=np.float64).reshape(-1)
    if output.ndim != 2 or output.shape[1] < 7 or len(output) == 0:
        raise ValueError("trajectory must have shape (T, >=7)")
    if obstacle.ndim != 2 or obstacle.shape[1] < 3 or len(obstacle) == 0:
        raise ValueError("obstacle_trajectory must have shape (T, >=3)")
    if len(current) < 3:
        raise ValueError("current_state must contain x/y/heading")
    horizon = min(len(output), len(obstacle))

    def conflict_indices(candidate: np.ndarray) -> list[int]:
        return [
            index
            for index in range(horizon)
            if oriented_boxes_overlap(
                candidate[index, :3],
                actor_size,
                obstacle[index, :3],
                obstacle_size,
                margin=margin,
            )
        ]

    conflicts = conflict_indices(output)
    if not conflicts:
        return output, False, None
    first_conflict = conflicts[0]
    for stop_index in range(first_conflict - 1, -2, -1):
        candidate = output.copy()
        if stop_index < 0:
            candidate[:, :3] = current[None, :3]
            candidate[:, 3:7] = 0.0
        else:
            candidate[stop_index + 1 :, :3] = candidate[stop_index, None, :3]
            candidate[stop_index + 1 :, 3:7] = 0.0
        if not conflict_indices(candidate):
            return candidate, True, first_conflict
    return output, False, first_conflict


@dataclass(frozen=True)
class SignalStage:
    name: str
    duration_seconds: float
    green_movements: frozenset[str] = frozenset()
    yellow_movements: frozenset[str] = frozenset()
    pedestrian_axis: str | None = None
    pure_straight: bool = False


class SignalTimingPlan:
    """Protected-left, pedestrian lead, then through/right signal timing."""

    def __init__(self, step_seconds: float = 0.1):
        self.step_seconds = max(1e-3, float(step_seconds))
        self.stages = (
            SignalStage("ew_left", 8.0, frozenset({"ew_l"})),
            SignalStage("ew_left_yellow", 3.0, yellow_movements=frozenset({"ew_l"})),
            SignalStage("ew_clearance", 1.0),
            SignalStage(
                "ew_pedestrian_lead",
                6.0,
                frozenset({"ew_s"}),
                pedestrian_axis="ew",
                pure_straight=True,
            ),
            SignalStage("ew_through_right", 18.0, frozenset({"ew_s", "ew_r"})),
            SignalStage(
                "ew_through_right_yellow",
                3.0,
                yellow_movements=frozenset({"ew_s", "ew_r"}),
            ),
            SignalStage("ew_all_red", 1.0),
            SignalStage("ns_left", 8.0, frozenset({"ns_l"})),
            SignalStage("ns_left_yellow", 3.0, yellow_movements=frozenset({"ns_l"})),
            SignalStage("ns_clearance", 1.0),
            SignalStage(
                "ns_pedestrian_lead",
                6.0,
                frozenset({"ns_s"}),
                pedestrian_axis="ns",
                pure_straight=True,
            ),
            SignalStage("ns_through_right", 18.0, frozenset({"ns_s", "ns_r"})),
            SignalStage(
                "ns_through_right_yellow",
                3.0,
                yellow_movements=frozenset({"ns_s", "ns_r"}),
            ),
            SignalStage("ns_all_red", 1.0),
        )
        self.stage_steps = tuple(max(1, int(round(stage.duration_seconds / self.step_seconds))) for stage in self.stages)
        self.cumulative_steps = np.cumsum(self.stage_steps)
        self.cycle_steps = int(self.cumulative_steps[-1])

    @staticmethod
    def normalize_movement(movement: str | None) -> str:
        text = str(movement or "").strip().lower()
        if text in {"e", "w"}:
            return "ew_s"
        if text in {"n", "s"}:
            return "ns_s"
        if text.startswith(("e_", "w_")):
            return "ew_" + text[-1]
        if text.startswith(("n_", "s_")):
            return "ns_" + text[-1]
        return text if text in {"ew_s", "ew_l", "ew_r", "ns_s", "ns_l", "ns_r"} else ""

    def stage_index(self, step: int) -> int:
        offset = int(step) % self.cycle_steps
        return int(np.searchsorted(self.cumulative_steps, offset, side="right"))

    def stage(self, step: int) -> SignalStage:
        return self.stages[self.stage_index(step)]

    def state(self, movement: str | None, step: int) -> str:
        normalized = self.normalize_movement(movement)
        stage = self.stage(step)
        if normalized in stage.green_movements:
            return "g"
        if normalized in stage.yellow_movements:
            return "y"
        return "r"

    def phase_string(self, movement: str | None) -> str:
        normalized = self.normalize_movement(movement)
        chars = []
        for stage in self.stages:
            if normalized in stage.green_movements:
                chars.append("g")
            elif normalized in stage.yellow_movements:
                chars.append("y")
            else:
                chars.append("r")
        return "".join(chars)

    def pedestrian_walk_allowed(self, crossing_axis: str, step: int) -> bool:
        stage = self.stage(step)
        return bool(stage.pure_straight and stage.pedestrian_axis == str(crossing_axis).lower())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "trafficwm.signal-timing.v1",
            "step_seconds": self.step_seconds,
            "cycle_seconds": round(self.cycle_steps * self.step_seconds, 3),
            "stages": [
                {
                    "name": stage.name,
                    "duration_seconds": stage.duration_seconds,
                    "green_movements": sorted(stage.green_movements),
                    "yellow_movements": sorted(stage.yellow_movements),
                    "pedestrian_axis": stage.pedestrian_axis,
                    "pure_straight": stage.pure_straight,
                }
                for stage in self.stages
            ],
        }


def axis_from_heading(heading: float) -> str:
    return "ew" if abs(math.cos(float(heading))) >= abs(math.sin(float(heading))) else "ns"


def crossing_axis_from_heading(road_heading: float) -> str:
    return "ns" if axis_from_heading(road_heading) == "ew" else "ew"


def shift_signal_stop_points(
    map_obj: Any,
    lane_ids: Iterable[Any],
    stop_points: np.ndarray,
    offset_m: float = 1.5,
) -> np.ndarray:
    """Move virtual stop points upstream without changing rendered map geometry."""
    shifted = np.asarray(stop_points, dtype=np.float64).copy()
    if shifted.size == 0:
        return shifted
    if shifted.ndim < 2 or shifted.shape[-1] < 2:
        raise ValueError("signal stop points must have shape (..., >=2)")
    flat = shifted.reshape(-1, shifted.shape[-1])
    distance = max(0.0, float(offset_m))
    if distance == 0.0:
        return shifted
    for index, lane_id in enumerate(lane_ids):
        if index >= len(flat):
            break
        lane = getattr(map_obj, "polyline_dict", {}).get(lane_id)
        points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
        if points.ndim != 2 or len(points) < 2 or points.shape[1] < 2:
            continue
        deltas = points[1:, :2] - points[:-1, :2]
        norms = np.linalg.norm(deltas, axis=1)
        valid = np.flatnonzero(norms > 1e-6)
        if not len(valid):
            continue
        direction = deltas[int(valid[0])] / norms[int(valid[0])]
        flat[index, :2] -= direction * distance
    return shifted


@dataclass(frozen=True)
class CrosswalkGeometry:
    id: str
    start: np.ndarray
    end: np.ndarray
    road_axis: str
    crossing_axis: str
    state_keys: tuple[str, ...]
    width: float = 3.5

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    @property
    def heading(self) -> float:
        delta = self.end - self.start
        return math.atan2(float(delta[1]), float(delta[0]))

    @classmethod
    def from_semantic(cls, item: dict[str, Any]) -> "CrosswalkGeometry | None":
        waiting_points = item.get("waiting_points")
        source_line = (
            waiting_points
            if waiting_points is not None and len(waiting_points) >= 2
            else item.get("centerline") or []
        )
        line = np.asarray(source_line, dtype=np.float64)
        if line.ndim != 2 or len(line) < 2 or line.shape[1] < 2:
            return None
        road_axis = str(item.get("road_axis") or "").lower()
        crossing_axis = str(item.get("crossing_axis") or "").lower()
        if crossing_axis not in {"ew", "ns"}:
            delta = line[-1, :2] - line[0, :2]
            crossing_axis = axis_from_heading(math.atan2(float(delta[1]), float(delta[0])))
        if road_axis not in {"ew", "ns"}:
            road_axis = "ns" if crossing_axis == "ew" else "ew"
        return cls(
            id=str(item.get("id") or "crosswalk"),
            start=line[0, :2].copy(),
            end=line[-1, :2].copy(),
            road_axis=road_axis,
            crossing_axis=crossing_axis,
            state_keys=tuple(str(value) for value in item.get("state_keys") or ()),
            width=max(1.0, float(item.get("width") or 3.5)),
        )


class RulePedestrian:
    """Rule-controlled pedestrian that waits at, and only traverses, one crosswalk."""

    length = 0.55
    width = 0.55
    height = 1.72

    def __init__(
        self,
        pedestrian_id: str,
        crosswalk: CrosswalkGeometry,
        *,
        direction: int = 1,
        speed: float = 1.35,
        initial_progress: float | None = None,
        lateral_offset: float = 0.0,
        reaction_time: float = 0.5,
    ):
        self.id = str(pedestrian_id)
        self.crosswalk = crosswalk
        self.direction = 1 if int(direction) >= 0 else -1
        self.speed = max(0.5, min(2.2, float(speed)))
        self.progress = float(0.0 if self.direction > 0 else 1.0) if initial_progress is None else float(initial_progress)
        self.progress = float(np.clip(self.progress, 0.0, 1.0))
        max_offset = max(0.0, self.crosswalk.width * 0.5 - self.width * 0.5)
        self.lateral_offset = float(np.clip(lateral_offset, -max_offset, max_offset))
        self.reaction_time = max(0.2, min(2.0, float(reaction_time)))
        self.mode = "waiting"
        self.wait_seconds = 0.0
        self.blocked = False

    def clone(self) -> "RulePedestrian":
        other = RulePedestrian(
            self.id,
            self.crosswalk,
            direction=self.direction,
            speed=self.speed,
            initial_progress=self.progress,
            lateral_offset=self.lateral_offset,
            reaction_time=self.reaction_time,
        )
        other.mode = self.mode
        other.wait_seconds = self.wait_seconds
        other.blocked = self.blocked
        return other

    def position(self) -> np.ndarray:
        line = self.crosswalk.end - self.crosswalk.start
        length = max(float(np.linalg.norm(line)), 1e-9)
        normal = np.asarray([-line[1], line[0]], dtype=np.float64) / length
        return self.crosswalk.start + line * self.progress + normal * self.lateral_offset

    def heading(self) -> float:
        heading = self.crosswalk.heading
        return heading if self.direction > 0 else (heading + math.pi) % (2.0 * math.pi) - math.pi

    def advance(self, dt: float, walk_allowed: bool) -> None:
        dt = max(0.0, float(dt))
        self.blocked = False
        if self.mode == "waiting":
            if not walk_allowed:
                self.wait_seconds = 0.0
                return
            self.wait_seconds += dt
            if self.wait_seconds + 1e-9 >= self.reaction_time:
                self.mode = "crossing"
                self.wait_seconds = 0.0
        if self.mode != "crossing":
            return
        distance = max(self.crosswalk.length, 1e-6)
        self.progress += self.direction * self.speed * dt / distance
        if self.progress >= 1.0:
            self.progress = 1.0
            self.direction = -1
            self.mode = "waiting"
            self.wait_seconds = 0.0
        elif self.progress <= 0.0:
            self.progress = 0.0
            self.direction = 1
            self.mode = "waiting"
            self.wait_seconds = 0.0

    def advance_if_clear(
        self,
        dt: float,
        walk_allowed: bool,
        obstacles: Iterable[tuple[Iterable[float], Iterable[float]]],
        *,
        margin: float = 0.1,
    ) -> bool:
        """Advance one rule step only when the resulting pedestrian OBB is clear.

        The AV predictor keeps a larger look-ahead margin. This smaller local
        clearance lets a pedestrian already in the crosswalk move away from a
        stopped AV instead of leaving both actors blocked.
        """
        candidate = self.clone()
        candidate.advance(dt, walk_allowed)
        current_state = self.state_vector()
        candidate_state = candidate.state_vector()
        for obstacle_pose, obstacle_size in obstacles:
            if oriented_boxes_overlap(
                candidate_state[:3],
                (self.length, self.width),
                obstacle_pose,
                obstacle_size,
                margin=margin,
            ):
                current_depth = _oriented_box_overlap_depth(
                    current_state[:3],
                    (self.length, self.width),
                    obstacle_pose,
                    obstacle_size,
                    margin=margin,
                )
                candidate_depth = _oriented_box_overlap_depth(
                    candidate_state[:3],
                    (self.length, self.width),
                    obstacle_pose,
                    obstacle_size,
                    margin=margin,
                )
                if current_depth <= 0.0 or candidate_depth >= current_depth - 1e-6:
                    self.blocked = True
                    return False
        self.progress = candidate.progress
        self.direction = candidate.direction
        self.mode = candidate.mode
        self.wait_seconds = candidate.wait_seconds
        self.blocked = False
        return True

    def state_vector(self) -> np.ndarray:
        heading = self.heading()
        moving = self.mode == "crossing" and not self.blocked
        speed = self.speed if moving else 0.0
        position = self.position()
        return np.asarray(
            [position[0], position[1], heading, speed * math.cos(heading), speed * math.sin(heading), 0.0, 0.0],
            dtype=np.float64,
        )

    def forecast(self, start_step: int, horizon: int, plan: SignalTimingPlan) -> np.ndarray:
        pedestrian = self.clone()
        states = []
        for offset in range(max(1, int(horizon))):
            pedestrian.advance(
                plan.step_seconds,
                plan.pedestrian_walk_allowed(pedestrian.crosswalk.crossing_axis, int(start_step) + offset),
            )
            states.append(pedestrian.state_vector())
        return np.stack(states, axis=0)

    def requires_vehicle_yield(self, step: int, plan: SignalTimingPlan) -> bool:
        """Return whether this pedestrian can occupy the roadway now.

        A pedestrian waiting for a red walk signal is on the sidewalk and must
        not become a static obstacle in the vehicle safety graph. Pedestrians
        already crossing remain protected after their walk phase ends.
        """
        return self.mode == "crossing" or plan.pedestrian_walk_allowed(
            self.crosswalk.crossing_axis,
            int(step),
        )

    def as_actor(self) -> dict[str, Any]:
        state = self.state_vector()
        return {
            "id": self.id,
            "type": "pedestrian",
            "road_user_type": "pedestrian",
            "x": float(state[0]),
            "y": float(state[1]),
            "heading": float(state[2]),
            "vx": float(state[3]),
            "vy": float(state[4]),
            "speed": float(np.linalg.norm(state[3:5])),
            "length": self.length,
            "width": self.width,
            "height": self.height,
            "crosswalk_id": self.crosswalk.id,
            "pedestrian_state": self.mode,
            "safety_blocked": self.blocked,
            "static": self.mode != "crossing" or self.blocked,
            "past": [],
            "future": [],
        }


def rollback_state_before_oriented_obstacles(
    states: np.ndarray,
    current_index: int,
    actor_size: Iterable[float],
    obstacles: Iterable[tuple[Iterable[float], Iterable[float]]],
    *,
    margin: float = 0.25,
    history_limit: int = 50,
) -> tuple[np.ndarray, bool, int | None]:
    """Return a stopped current/prior state whose OBB clears every obstacle."""
    values = np.asarray(states, dtype=np.float64)
    index = int(current_index)
    if values.ndim != 2 or values.shape[1] < 7 or not 0 <= index < len(values):
        raise ValueError("states must have shape (T, >=7) and contain current_index")
    obstacle_values = [
        (
            np.asarray(tuple(pose), dtype=np.float64).reshape(-1),
            np.asarray(tuple(size), dtype=np.float64).reshape(-1),
        )
        for pose, size in obstacles
    ]

    def stopped_state(source_index: int) -> np.ndarray:
        state = values[source_index, :7].copy()
        state[2] = (float(state[2]) + math.pi) % (2.0 * math.pi) - math.pi
        state[3:7] = 0.0
        return state

    def clear(candidate: np.ndarray) -> bool:
        return not any(
            oriented_boxes_overlap(
                candidate[:3],
                actor_size,
                obstacle_pose[:3],
                obstacle_size[:2],
                margin=margin,
            )
            for obstacle_pose, obstacle_size in obstacle_values
        )

    current = stopped_state(index)
    if clear(current):
        return current, False, index
    lower = max(0, index - max(1, int(history_limit)))
    for source_index in range(index - 1, lower - 1, -1):
        candidate = stopped_state(source_index)
        if clear(candidate):
            return candidate, True, source_index
    return current, False, None


def pedestrian_stream_offset(crosswalk: CrosswalkGeometry, local_index: int) -> float:
    """Assign opposing pedestrian streams to separate parts of a crosswalk."""
    index = max(0, int(local_index))
    max_offset = max(0.0, crosswalk.width * 0.5 - RulePedestrian.width * 0.5)
    magnitude = min(max_offset, 0.45 + 0.75 * (index // 2))
    return -magnitude if index % 2 == 0 else magnitude


def _heading_delta(first: float, second: float) -> float:
    return abs((float(first) - float(second) + math.pi) % (2.0 * math.pi) - math.pi)


def select_rightmost_route(map_obj: Any, current_lane: Any, max_candidates: int = 256) -> list[Any]:
    """Choose a straight route whose non-intersection lanes are all rightmost."""
    try:
        routes = list(map_obj.get_routes(current_lane_id=current_lane, full=True))
    except Exception:
        return []
    if not routes:
        return []
    movement_by_id = getattr(map_obj, "_trafficwm_movement_by_id", None)
    if movement_by_id is None:
        try:
            intersection_ids = list(map_obj.get_intersection_polyline_id())
            movement_by_id = map_obj.get_intersection_polyline_direction(intersection_ids)
        except (AttributeError, TypeError, ValueError):
            movement_by_id = {}
        try:
            map_obj._trafficwm_movement_by_id = movement_by_id
        except (AttributeError, TypeError):
            pass

    def is_strictly_rightmost(route: Iterable[Any]) -> bool:
        for lane_id in route:
            lane = map_obj.polyline_dict.get(lane_id)
            if lane is None or bool(getattr(lane, "is_intersection", False)):
                continue
            if int(getattr(lane, "type", 0) or 0) == 4:
                continue
            for neighbor_id in list(getattr(lane, "right_lanes_id", []) or []):
                neighbor = map_obj.polyline_dict.get(neighbor_id)
                if neighbor is None:
                    continue
                is_lane_center = getattr(neighbor, "is_lane_center", None)
                if is_lane_center is None:
                    is_lane_center = int(getattr(neighbor, "type", 0) or 0) in {0, 4}
                if bool(is_lane_center):
                    return False
        return True

    def score(route: Iterable[Any]) -> tuple[float, int, str]:
        route = list(route)
        turn_penalty = 0.0
        signal_turn_penalty = 0.0
        previous_heading = None
        for lane_id in route:
            lane = map_obj.polyline_dict.get(lane_id)
            if lane is None:
                continue
            movement = SignalTimingPlan.normalize_movement(movement_by_id.get(lane_id))
            if movement and not movement.endswith("_s"):
                signal_turn_penalty += 1.0
            headings = np.asarray(getattr(lane, "heading", []), dtype=np.float64).reshape(-1)
            if headings.size:
                if previous_heading is not None:
                    turn_penalty += _heading_delta(previous_heading, float(headings[0]))
                previous_heading = float(headings[-1])
        return (
            signal_turn_penalty * 1000.0 + turn_penalty * 20.0,
            len(route),
            "|".join(map(str, route)),
        )

    candidates = [
        list(route)
        for route in routes[: max(1, int(max_candidates))]
        if is_strictly_rightmost(route)
    ]
    return list(min(candidates, key=score)) if candidates else []


def project_point_to_segment(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> tuple[np.ndarray, float, float]:
    point = np.asarray(point, dtype=np.float64)[:2]
    start = np.asarray(start, dtype=np.float64)[:2]
    end = np.asarray(end, dtype=np.float64)[:2]
    segment = end - start
    length_sq = float(np.dot(segment, segment))
    if length_sq <= 1e-9:
        return start.copy(), float(np.linalg.norm(point - start)), 0.0
    scalar = float(np.clip(np.dot(point - start, segment) / length_sq, 0.0, 1.0))
    projected = start + scalar * segment
    return projected, float(np.linalg.norm(point - projected)), scalar


def _clean_polyline(
    points: np.ndarray,
    intersection_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2 or len(values) < 2 or values.shape[1] < 2:
        raise ValueError("Route polyline must have shape (N, >=2) with at least two points")
    values = values[:, :2]
    flags = np.zeros(len(values), dtype=bool)
    if intersection_mask is not None:
        source_flags = np.asarray(intersection_mask, dtype=bool).reshape(-1)
        if len(source_flags) != len(values):
            raise ValueError("intersection_mask must match the route polyline length")
        flags[:] = source_flags
    retained_points = [values[0]]
    retained_flags = [bool(flags[0])]
    for point, flag in zip(values[1:], flags[1:]):
        if float(np.linalg.norm(point - retained_points[-1])) <= 1e-6:
            retained_flags[-1] = retained_flags[-1] or bool(flag)
            continue
        retained_points.append(point)
        retained_flags.append(bool(flag))
    if len(retained_points) < 2:
        raise ValueError("Route polyline has no non-zero-length segment")
    return np.stack(retained_points), np.asarray(retained_flags, dtype=bool)


def _polyline_lengths(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.concatenate((np.asarray([0.0]), np.cumsum(segment_lengths)))
    return segment_lengths, cumulative


def project_point_to_polyline(
    point: np.ndarray,
    points: np.ndarray,
    cumulative: np.ndarray | None = None,
) -> tuple[np.ndarray, float, float, int]:
    values = np.asarray(points, dtype=np.float64)[:, :2]
    if len(values) < 2:
        raise ValueError("Polyline projection needs at least two points")
    segment = values[1:] - values[:-1]
    length_sq = np.einsum("ij,ij->i", segment, segment)
    relative = np.asarray(point, dtype=np.float64)[:2] - values[:-1]
    scalar = np.divide(
        np.einsum("ij,ij->i", relative, segment),
        length_sq,
        out=np.zeros_like(length_sq),
        where=length_sq > 1e-12,
    )
    scalar = np.clip(scalar, 0.0, 1.0)
    projected = values[:-1] + segment * scalar[:, None]
    distances = np.linalg.norm(projected - np.asarray(point, dtype=np.float64)[:2], axis=1)
    index = int(np.argmin(distances))
    if cumulative is None:
        _, cumulative = _polyline_lengths(values)
    progress = float(cumulative[index] + scalar[index] * (cumulative[index + 1] - cumulative[index]))
    return projected[index], float(distances[index]), progress, index


def sample_polyline(points: np.ndarray, cumulative: np.ndarray, progress: float) -> tuple[np.ndarray, float]:
    progress = float(np.clip(progress, 0.0, float(cumulative[-1])))
    index = int(np.searchsorted(cumulative, progress, side="right") - 1)
    index = max(0, min(index, len(points) - 2))
    segment = points[index + 1] - points[index]
    length = max(float(cumulative[index + 1] - cumulative[index]), 1e-9)
    scalar = float(np.clip((progress - cumulative[index]) / length, 0.0, 1.0))
    return points[index] + scalar * segment, math.atan2(float(segment[1]), float(segment[0]))


@dataclass(frozen=True)
class CrosswalkPassage:
    crosswalk: CrosswalkGeometry
    entry_progress: float
    exit_progress: float
    blend_start_progress: float
    blend_end_progress: float
    entry_point: np.ndarray
    exit_point: np.ndarray


class CyclistRouteCorridor:
    """A lane route smoothly diverted through each compatible signalized crosswalk."""

    def __init__(
        self,
        route_points: np.ndarray,
        passages: Iterable[CrosswalkPassage],
        blocked_entries: Iterable[float] = (),
    ):
        self.route_points, _ = _clean_polyline(route_points)
        _, self.cumulative = _polyline_lengths(self.route_points)
        self.passages = tuple(sorted(passages, key=lambda item: item.entry_progress))
        self.blocked_entries = tuple(sorted(float(value) for value in blocked_entries))

    @property
    def total_length(self) -> float:
        return float(self.cumulative[-1])

    @property
    def crosswalk_ids(self) -> tuple[str, ...]:
        return tuple(passage.crosswalk.id for passage in self.passages)

    @staticmethod
    def _smoothstep(value: float) -> float:
        value = float(np.clip(value, 0.0, 1.0))
        return value * value * (3.0 - 2.0 * value)

    def project_progress(self, point: np.ndarray) -> float:
        return project_point_to_polyline(point, self.route_points, self.cumulative)[2]

    def anchored_at(self, current_position: np.ndarray) -> "CyclistRouteCorridor":
        """Avoid a lateral jump when attaching a corridor to an existing track."""
        current_position = np.asarray(current_position, dtype=np.float64)[:2]
        current_progress = self.project_progress(current_position)
        passages = []
        for passage in self.passages:
            if passage.blend_start_progress < current_progress < passage.entry_progress:
                passage = CrosswalkPassage(
                    crosswalk=passage.crosswalk,
                    entry_progress=passage.entry_progress,
                    exit_progress=passage.exit_progress,
                    blend_start_progress=current_progress,
                    blend_end_progress=passage.blend_end_progress,
                    entry_point=passage.entry_point,
                    exit_point=passage.exit_point,
                )
            elif passage.entry_progress <= current_progress <= passage.exit_progress:
                passage = CrosswalkPassage(
                    crosswalk=passage.crosswalk,
                    entry_progress=current_progress,
                    exit_progress=passage.exit_progress,
                    blend_start_progress=current_progress,
                    blend_end_progress=passage.blend_end_progress,
                    entry_point=current_position.copy(),
                    exit_point=passage.exit_point,
                )
            elif passage.exit_progress < current_progress < passage.blend_end_progress:
                continue
            passages.append(passage)
        blocked_entries = [value for value in self.blocked_entries if value > current_progress]
        return CyclistRouteCorridor(self.route_points, passages, blocked_entries)

    def _target_position(self, progress: float) -> np.ndarray:
        route_point, _ = sample_polyline(self.route_points, self.cumulative, progress)
        for passage in self.passages:
            if progress < passage.blend_start_progress or progress > passage.blend_end_progress:
                continue
            route_entry, _ = sample_polyline(
                self.route_points, self.cumulative, passage.entry_progress
            )
            route_exit, _ = sample_polyline(
                self.route_points, self.cumulative, passage.exit_progress
            )
            if progress < passage.entry_progress:
                denominator = max(passage.entry_progress - passage.blend_start_progress, 1e-6)
                alpha = self._smoothstep(
                    (progress - passage.blend_start_progress) / denominator
                )
                return route_point + alpha * (passage.entry_point - route_entry)
            if progress <= passage.exit_progress:
                denominator = max(passage.exit_progress - passage.entry_progress, 1e-6)
                alpha = float(np.clip((progress - passage.entry_progress) / denominator, 0.0, 1.0))
                return passage.entry_point + alpha * (passage.exit_point - passage.entry_point)
            denominator = max(passage.blend_end_progress - passage.exit_progress, 1e-6)
            alpha = 1.0 - self._smoothstep(
                (progress - passage.exit_progress) / denominator
            )
            return route_point + alpha * (passage.exit_point - route_exit)
        return route_point

    def sample(self, progress: float) -> tuple[np.ndarray, float]:
        progress = float(np.clip(progress, 0.0, self.total_length))
        point = self._target_position(progress)
        delta = min(0.25, max(self.total_length * 1e-4, 0.05))
        before = self._target_position(max(0.0, progress - delta))
        after = self._target_position(min(self.total_length, progress + delta))
        tangent = after - before
        if float(np.linalg.norm(tangent)) <= 1e-9:
            _, heading = sample_polyline(self.route_points, self.cumulative, progress)
        else:
            heading = math.atan2(float(tangent[1]), float(tangent[0]))
        return point, heading

    def constrain_states(
        self,
        states: np.ndarray,
        *,
        current_position: np.ndarray,
        start_step: int,
        signal_plan: SignalTimingPlan,
        current_velocity: np.ndarray | None = None,
        wait_margin: float = 0.8,
        max_speed: float = 8.0,
        max_acceleration: float = 2.0,
    ) -> tuple[np.ndarray, int, int]:
        output = np.asarray(states, dtype=np.float64).copy()
        if output.ndim != 2 or output.shape[1] < 7:
            raise ValueError("Cyclist states must have shape (T, >=7)")
        raw_previous = self.project_progress(current_position)
        output_progress = raw_previous
        previous_position = np.asarray(current_position, dtype=np.float64)[:2].copy()
        previous_velocity = (
            np.asarray(current_velocity, dtype=np.float64).reshape(-1)[:2].copy()
            if current_velocity is not None
            else np.asarray(output[0, 3:5], dtype=np.float64).copy()
        )
        previous_speed = min(float(max_speed), float(np.linalg.norm(previous_velocity)))
        corrections = 0
        signal_stops = 0
        for offset, state in enumerate(output):
            raw_progress = max(raw_previous, self.project_progress(state[:2]))
            model_delta = min(
                max(0.0, raw_progress - raw_previous),
                max(0.5, float(max_speed)) * signal_plan.step_seconds,
            )
            desired_progress = min(self.total_length, output_progress + model_delta)
            raw_previous = raw_progress

            for blocked_entry in self.blocked_entries:
                stop_progress = max(0.0, blocked_entry - wait_margin)
                if output_progress <= stop_progress < desired_progress:
                    desired_progress = stop_progress

            for passage in self.passages:
                stop_progress = max(0.0, passage.entry_progress - wait_margin)
                already_crossing = passage.entry_progress <= output_progress <= passage.exit_progress
                reaches_crossing = output_progress <= stop_progress < desired_progress
                if already_crossing or not reaches_crossing:
                    continue
                if not signal_plan.pedestrian_walk_allowed(
                    passage.crosswalk.crossing_axis, int(start_step) + offset
                ):
                    desired_progress = stop_progress
                    signal_stops = 1

            target, heading = self.sample(desired_progress)
            displacement = target - previous_position
            allowed_speed = min(
                float(max_speed),
                previous_speed + max(0.0, float(max_acceleration)) * signal_plan.step_seconds,
            )
            max_displacement = max(0.05, allowed_speed) * signal_plan.step_seconds
            displacement_norm = float(np.linalg.norm(displacement))
            if displacement_norm > max_displacement:
                base_target, _ = self.sample(output_progress)
                if float(np.linalg.norm(base_target - previous_position)) <= 1e-4:
                    lower = output_progress
                    upper = desired_progress
                    for _ in range(18):
                        middle = (lower + upper) * 0.5
                        middle_target, _ = self.sample(middle)
                        if float(np.linalg.norm(middle_target - previous_position)) <= max_displacement:
                            lower = middle
                        else:
                            upper = middle
                    desired_progress = lower
                    target, heading = self.sample(desired_progress)
                    displacement = target - previous_position
                else:
                    displacement *= max_displacement / displacement_norm
                    target = previous_position + displacement
                    desired_progress = output_progress
                    heading = math.atan2(float(displacement[1]), float(displacement[0]))
            stopped_at_progress = desired_progress <= output_progress + 1e-6
            if float(np.linalg.norm(state[:2] - target)) > 0.05 or _heading_delta(state[2], heading) > 0.03:
                corrections += 1
            state[:2] = target
            state[2] = heading
            stopped = stopped_at_progress and float(np.linalg.norm(displacement)) <= 1e-6
            velocity = np.zeros(2, dtype=np.float64) if stopped else displacement / signal_plan.step_seconds
            state[3:5] = velocity
            if stopped:
                state[5:7] = 0.0
            else:
                state[5:7] = np.clip(
                    (velocity - previous_velocity) / signal_plan.step_seconds,
                    -4.0,
                    4.0,
                )
            output_progress = desired_progress
            previous_position = target
            previous_velocity = velocity
            previous_speed = float(np.linalg.norm(velocity))
        return output, corrections, signal_stops


def build_cyclist_route_corridor(
    route_points: np.ndarray,
    intersection_mask: np.ndarray,
    crosswalks: Iterable[CrosswalkGeometry],
    *,
    max_lateral_distance: float = 48.0,
    intersection_margin: float = 8.0,
) -> CyclistRouteCorridor:
    points, flags = _clean_polyline(route_points, intersection_mask)
    _, cumulative = _polyline_lengths(points)
    intervals: list[tuple[float, float]] = []
    start_index = None
    for index, flag in enumerate(flags):
        if flag and start_index is None:
            start_index = index
        if start_index is not None and (not flag or index == len(flags) - 1):
            end_index = index if flag and index == len(flags) - 1 else max(start_index, index - 1)
            intervals.append((float(cumulative[start_index]), float(cumulative[end_index])))
            start_index = None

    passages: list[CrosswalkPassage] = []
    blocked_entries: list[float] = []
    used_crosswalks: set[str] = set()
    for interval_start, interval_end in intervals:
        candidates = []
        interval_center = (interval_start + interval_end) * 0.5
        _, route_heading = sample_polyline(points, cumulative, interval_center)
        for crosswalk in crosswalks:
            if crosswalk.id in used_crosswalks:
                continue
            heading_error = min(
                _heading_delta(route_heading, crosswalk.heading),
                _heading_delta(route_heading, crosswalk.heading + math.pi),
            )
            if heading_error > math.radians(40.0):
                continue
            _, start_distance, start_progress, _ = project_point_to_polyline(
                crosswalk.start, points, cumulative
            )
            _, end_distance, end_progress, _ = project_point_to_polyline(
                crosswalk.end, points, cumulative
            )
            entry_point = crosswalk.start
            exit_point = crosswalk.end
            if end_progress < start_progress:
                start_progress, end_progress = end_progress, start_progress
                start_distance, end_distance = end_distance, start_distance
                entry_point, exit_point = exit_point, entry_point
            span = end_progress - start_progress
            center_progress = (start_progress + end_progress) * 0.5
            lateral_distance = max(start_distance, end_distance)
            if span < max(2.0, crosswalk.length * 0.35):
                continue
            if lateral_distance > max_lateral_distance:
                continue
            if not (
                interval_start - intersection_margin
                <= center_progress
                <= interval_end + intersection_margin
            ):
                continue
            score = lateral_distance + abs(center_progress - interval_center) * 0.08 + heading_error * 4.0
            candidates.append(
                (
                    score,
                    crosswalk.id,
                    crosswalk,
                    start_progress,
                    end_progress,
                    entry_point,
                    exit_point,
                    lateral_distance,
                )
            )
        if not candidates:
            if interval_start > 1.0:
                blocked_entries.append(interval_start)
            continue
        (
            _,
            _,
            crosswalk,
            entry_progress,
            exit_progress,
            entry_point,
            exit_point,
            lateral_distance,
        ) = min(candidates, key=lambda item: (item[0], item[1]))
        used_crosswalks.add(crosswalk.id)
        entry_point = np.asarray(entry_point, dtype=np.float64).copy()
        exit_point = np.asarray(exit_point, dtype=np.float64).copy()
        crossing_vector = exit_point - entry_point
        crossing_length = max(float(np.linalg.norm(crossing_vector)), 1e-9)
        right_normal = np.asarray(
            [crossing_vector[1], -crossing_vector[0]], dtype=np.float64
        ) / crossing_length
        cyclist_offset = min(1.0, max(0.35, crosswalk.width * 0.28))
        entry_point += right_normal * cyclist_offset
        exit_point += right_normal * cyclist_offset
        blend_distance = max(14.0, min(55.0, lateral_distance * 2.5))
        passages.append(
            CrosswalkPassage(
                crosswalk=crosswalk,
                entry_progress=entry_progress,
                exit_progress=exit_progress,
                blend_start_progress=max(0.0, entry_progress - blend_distance),
                blend_end_progress=min(float(cumulative[-1]), exit_progress + blend_distance),
                entry_point=entry_point,
                exit_point=exit_point,
            )
        )
    return CyclistRouteCorridor(points, passages, blocked_entries)


def constrain_to_crosswalks(
    states: np.ndarray,
    crosswalks: Iterable[CrosswalkGeometry],
    *,
    max_distance: float = 2.5,
    max_heading_error: float = math.radians(35.0),
) -> tuple[np.ndarray, int]:
    """Project cyclist predictions onto aligned crosswalk centerlines when entering one."""
    output = np.asarray(states, dtype=np.float64).copy()
    corrections = 0
    crosswalks = list(crosswalks)
    for state in output:
        best = None
        for crosswalk in crosswalks:
            heading_error = min(
                _heading_delta(float(state[2]), crosswalk.heading),
                _heading_delta(float(state[2]), crosswalk.heading + math.pi),
            )
            if heading_error > max_heading_error:
                continue
            projected, distance, scalar = project_point_to_segment(state[:2], crosswalk.start, crosswalk.end)
            if distance > max_distance or scalar <= 0.01 or scalar >= 0.99:
                continue
            candidate = (distance, projected, crosswalk)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            continue
        _, projected, crosswalk = best
        state[:2] = projected
        forward = np.asarray([math.cos(state[2]), math.sin(state[2])])
        line = crosswalk.end - crosswalk.start
        if float(np.dot(forward, line)) < 0.0:
            line = -line
        state[2] = math.atan2(float(line[1]), float(line[0]))
        speed = float(np.linalg.norm(state[3:5]))
        state[3:5] = speed * np.asarray([math.cos(state[2]), math.sin(state[2])])
        corrections += 1
    return output, corrections
