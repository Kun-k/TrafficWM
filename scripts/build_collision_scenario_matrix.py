#!/usr/bin/env python3
"""Build deterministic straight-road and Yizhuang roundabout collision scenarios."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.algorithms.citynde.mixed_traffic_core import oriented_boxes_overlap  # noqa: E402
from scripts import build_tianjin_realtime_scenarios as shared  # noqa: E402


STEP_SECONDS = 0.1
DURATION_SECONDS = 12.0
FRAME_COUNT = int(round(DURATION_SECONDS / STEP_SECONDS)) + 1
HISTORY_FRAMES = 11
AV_ID = "AV"
COLLISION_ACTOR_ID = "BV-collision"
BACKGROUND_IDS = ("BV-background-1", "BV-background-2")
ACTOR_IDS = (AV_ID, COLLISION_ACTOR_ID, *BACKGROUND_IDS)
VEHICLE_SIZE = np.asarray([4.65, 1.84, 1.48], dtype=np.float32)

BASE_RECORDING = ROOT / "output/scenarios/citynde/library/xa_wenying_rule_seeded.pkl"
STRAIGHT_MAP = ROOT / "algorithm_sources/CityNDE_src/assets/map/cnde_map_xa_wenying.pkl"
ROUNDABOUT_MAP = (
    ROOT
    / "algorithm_sources/CityNDE_src/assets/map/cnde_map_yizhuang_roundabout_small_signalized.pkl"
)

STRAIGHT_PROMPT = (
    "Natural photorealistic 120-degree forward dashcam footage on a straight divided urban "
    "boulevard in clear neutral daylight. Preserve the supplied HD-map geometry, dry dark-gray "
    "asphalt, crisp white lane markings, concrete curbs, trees, restrained mid-rise buildings, "
    "and every mapped vehicle position. Vehicles remain upright and aligned with their lanes; "
    "body orientation changes continuously without spinning, snapping, floating, duplication, "
    "or deformation. Show a physically plausible traffic collision without fire, explosion, "
    "debris, injury, camera cut, logo, watermark, or cinematic effects."
)
ROUNDABOUT_PROMPT = (
    "Natural photorealistic footage from a fixed forward-facing automotive camera mounted behind "
    "the windshield at conventional road-camera height. The optical axis remains level and only "
    "a narrow dark dashboard edge is visible at the bottom. The ego vehicle circulates through a "
    "compact modern urban roundabout in Beijing Yizhuang under clear neutral daylight. Preserve "
    "the supplied curved HD-map lanes, landscaped central island, curbs, lane markings, roadside trees, streetlights, "
    "and every mapped vehicle position. All vehicles follow the roundabout curvature with stable "
    "upright bodies and continuous steering, without spinning, snapping, floating, duplication, "
    "warped roads, or deformation. Show a physically plausible low-severity traffic collision "
    "without fire, explosion, debris, injury, camera cut, logo, watermark, or cinematic effects."
)
ROUNDABOUT_TRANSFER_NEGATIVE_PROMPT = (
    "aerial view, bird eye view, drone view, overhead view, elevated camera, downward-looking "
    "camera, hood-mounted camera, oversized ego hood, large dashboard, visible car logo, ramp, "
    "overpass, raised roadway, miniature road, parking lot, test track, warped roundabout, "
    "distorted road, broken lane markings, floating vehicle, duplicated vehicle, deformed "
    "vehicle, blurry vehicle, motion blur, low resolution, oversaturation, flicker, jump cut, "
    "watermark, text"
)


@dataclass(frozen=True)
class ScenarioSpec:
    slug: str
    library_id: str
    name: str
    road_form: str
    collision_type: str
    speed_class: str
    map_path: Path
    collision_time: float
    av_start_s: float
    collision_start_s: float
    av_speed: float
    collision_speed: float
    lead_impact_speed: float
    av_impact_speed: float
    av_post_speed: float
    collision_post_speed: float


SPECS = (
    ScenarioSpec(
        slug="collision_straight_low_rearend",
        library_id="collision-straight-low-rearend-transfer1",
        name="事故场景-直道低速-主车追尾前车-Transfer1",
        road_form="straight",
        collision_type="rearend",
        speed_class="low",
        map_path=STRAIGHT_MAP,
        collision_time=5.2,
        av_start_s=32.0,
        collision_start_s=55.0,
        av_speed=6.0,
        collision_speed=5.0,
        lead_impact_speed=0.0,
        av_impact_speed=3.5,
        av_post_speed=0.0,
        collision_post_speed=2.0,
    ),
    ScenarioSpec(
        slug="collision_straight_low_cutin",
        library_id="collision-straight-low-cutin-transfer1",
        name="事故场景-直道低速-侧后车切入碰撞主车-Transfer1",
        road_form="straight",
        collision_type="cutin",
        speed_class="low",
        map_path=STRAIGHT_MAP,
        collision_time=4.5,
        av_start_s=42.0,
        collision_start_s=34.0,
        av_speed=6.0,
        collision_speed=8.5,
        lead_impact_speed=8.0,
        av_impact_speed=6.0,
        av_post_speed=1.5,
        collision_post_speed=9.0,
    ),
    ScenarioSpec(
        slug="collision_straight_high_rearend",
        library_id="collision-straight-high-rearend-transfer1",
        name="事故场景-直道高速-主车追尾前车-Transfer1",
        road_form="straight",
        collision_type="rearend",
        speed_class="high",
        map_path=STRAIGHT_MAP,
        collision_time=3.4,
        av_start_s=32.0,
        collision_start_s=57.0,
        av_speed=16.0,
        collision_speed=13.0,
        lead_impact_speed=4.0,
        av_impact_speed=12.0,
        av_post_speed=5.0,
        collision_post_speed=10.0,
    ),
    ScenarioSpec(
        slug="collision_straight_high_cutin",
        library_id="collision-straight-high-cutin-transfer1",
        name="事故场景-直道高速-侧后车切入碰撞主车-Transfer1",
        road_form="straight",
        collision_type="cutin",
        speed_class="high",
        map_path=STRAIGHT_MAP,
        collision_time=3.2,
        av_start_s=34.0,
        collision_start_s=25.0,
        av_speed=15.0,
        collision_speed=19.0,
        lead_impact_speed=18.0,
        av_impact_speed=15.0,
        av_post_speed=7.0,
        collision_post_speed=10.0,
    ),
    ScenarioSpec(
        slug="collision_yizhuang_roundabout_rearend",
        library_id="collision-yizhuang-roundabout-rearend-transfer1",
        name="事故场景-亦庄环岛-主车追尾前车-Transfer1",
        road_form="roundabout",
        collision_type="rearend",
        speed_class="urban",
        map_path=ROUNDABOUT_MAP,
        collision_time=4.6,
        av_start_s=18.0,
        collision_start_s=42.0,
        av_speed=8.0,
        collision_speed=7.0,
        lead_impact_speed=1.0,
        av_impact_speed=5.0,
        av_post_speed=1.5,
        collision_post_speed=5.0,
    ),
    ScenarioSpec(
        slug="collision_yizhuang_roundabout_cutin",
        library_id="collision-yizhuang-roundabout-cutin-transfer1",
        name="事故场景-亦庄环岛-侧后车切入碰撞主车-Transfer1",
        road_form="roundabout",
        collision_type="cutin",
        speed_class="urban",
        map_path=ROUNDABOUT_MAP,
        collision_time=4.0,
        av_start_s=24.0,
        collision_start_s=16.0,
        av_speed=8.0,
        collision_speed=10.5,
        lead_impact_speed=10.0,
        av_impact_speed=8.0,
        av_post_speed=2.5,
        collision_post_speed=11.0,
    ),
)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _wrap_angle(value: np.ndarray | float) -> np.ndarray | float:
    return np.arctan2(np.sin(value), np.cos(value))


def _smoothstep5(value: np.ndarray | float) -> np.ndarray | float:
    value = np.clip(value, 0.0, 1.0)
    return value**3 * (value * (value * 6.0 - 15.0) + 10.0)


def _quintic_values(
    times: np.ndarray,
    start_time: float,
    end_time: float,
    start_position: float,
    start_speed: float,
    end_position: float,
    end_speed: float,
    start_acceleration: float = 0.0,
    end_acceleration: float = 0.0,
) -> np.ndarray:
    duration = float(end_time - start_time)
    if duration <= 0.0:
        raise ValueError("Quintic segment duration must be positive")
    c0 = float(start_position)
    c1 = float(start_speed) * duration
    c2 = 0.5 * float(start_acceleration) * duration * duration
    rhs = np.asarray(
        [
            end_position - c0 - c1 - c2,
            end_speed * duration - c1 - 2.0 * c2,
            end_acceleration * duration * duration - 2.0 * c2,
        ],
        dtype=np.float64,
    )
    c3, c4, c5 = np.linalg.solve(
        np.asarray(
            [[1.0, 1.0, 1.0], [3.0, 4.0, 5.0], [6.0, 12.0, 20.0]],
            dtype=np.float64,
        ),
        rhs,
    )
    tau = np.clip((times - start_time) / duration, 0.0, 1.0)
    return c0 + c1 * tau + c2 * tau**2 + c3 * tau**3 + c4 * tau**4 + c5 * tau**5


def _controlled_longitudinal(
    times: np.ndarray,
    *,
    start_s: float,
    start_speed: float,
    bridge_start: float,
    impact_time: float,
    impact_s: float,
    impact_speed: float,
    post_speed: float,
    settle_seconds: float = 1.4,
) -> np.ndarray:
    values = start_s + start_speed * times
    bridge_start_s = start_s + start_speed * bridge_start
    bridge_mask = (times >= bridge_start) & (times <= impact_time)
    values[bridge_mask] = _quintic_values(
        times[bridge_mask],
        bridge_start,
        impact_time,
        bridge_start_s,
        start_speed,
        impact_s,
        impact_speed,
    )
    settle_end = min(float(times[-1]), impact_time + settle_seconds)
    settle_distance = 0.5 * (impact_speed + post_speed) * (settle_end - impact_time)
    settle_mask = (times > impact_time) & (times <= settle_end)
    values[settle_mask] = _quintic_values(
        times[settle_mask],
        impact_time,
        settle_end,
        impact_s,
        impact_speed,
        impact_s + settle_distance,
        post_speed,
    )
    after_mask = times > settle_end
    values[after_mask] = impact_s + settle_distance + post_speed * (times[after_mask] - settle_end)
    return values


class RoadPath:
    def __init__(self, points: np.ndarray, *, closed: bool, smoothing_passes: int = 0):
        points = np.asarray(points, dtype=np.float64)[:, :2]
        if len(points) < 4:
            raise ValueError("Road path requires at least four points")
        keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-4]
        points = points[keep]
        if closed and np.linalg.norm(points[-1] - points[0]) > 1e-3:
            points = np.vstack([points, points[0]])
        segment = np.linalg.norm(np.diff(points, axis=0), axis=1)
        distance = np.r_[0.0, np.cumsum(segment)]
        sample_count = max(16, int(math.ceil(distance[-1] / 0.25)))
        uniform = np.linspace(0.0, distance[-1], sample_count, endpoint=not closed)
        sampled = np.column_stack(
            [np.interp(uniform, distance, points[:, axis]) for axis in range(2)]
        )
        for _ in range(max(0, int(smoothing_passes))):
            if closed:
                sampled = (
                    np.roll(sampled, 2, axis=0)
                    + 4.0 * np.roll(sampled, 1, axis=0)
                    + 6.0 * sampled
                    + 4.0 * np.roll(sampled, -1, axis=0)
                    + np.roll(sampled, -2, axis=0)
                ) / 16.0
            else:
                padded = np.pad(sampled, ((2, 2), (0, 0)), mode="edge")
                sampled = (
                    padded[:-4]
                    + 4.0 * padded[1:-3]
                    + 6.0 * padded[2:-2]
                    + 4.0 * padded[3:-1]
                    + padded[4:]
                ) / 16.0
        if closed:
            closed_points = np.vstack([sampled, sampled[0]])
            cumulative = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(closed_points, axis=0), axis=1))]
            self.points = sampled
            self.sample_distance = cumulative[:-1]
            self.length = float(cumulative[-1])
            previous = np.roll(sampled, 1, axis=0)
            following = np.roll(sampled, -1, axis=0)
            tangent = following - previous
        else:
            self.points = sampled
            cumulative = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(sampled, axis=0), axis=1))]
            self.sample_distance = cumulative
            self.length = float(cumulative[-1])
            tangent = np.gradient(sampled, axis=0, edge_order=2)
        norm = np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)
        self.tangent = tangent / norm[:, None]
        self.closed = bool(closed)

    def sample(self, longitudinal: np.ndarray, lateral: np.ndarray | float = 0.0) -> np.ndarray:
        longitudinal = np.asarray(longitudinal, dtype=np.float64)
        lateral = np.broadcast_to(np.asarray(lateral, dtype=np.float64), longitudinal.shape)
        query = np.mod(longitudinal, self.length) if self.closed else np.clip(longitudinal, 0.0, self.length)
        if self.closed:
            xp = np.r_[self.sample_distance, self.length]
            px = np.r_[self.points[:, 0], self.points[0, 0]]
            py = np.r_[self.points[:, 1], self.points[0, 1]]
            tx = np.r_[self.tangent[:, 0], self.tangent[0, 0]]
            ty = np.r_[self.tangent[:, 1], self.tangent[0, 1]]
        else:
            xp = self.sample_distance
            px, py = self.points[:, 0], self.points[:, 1]
            tx, ty = self.tangent[:, 0], self.tangent[:, 1]
        position = np.column_stack([np.interp(query, xp, px), np.interp(query, xp, py)])
        tangent = np.column_stack([np.interp(query, xp, tx), np.interp(query, xp, ty)])
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1), 1e-9)[:, None]
        left_normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
        return position + lateral[:, None] * left_normal


def _chain_points(polylines: dict[str, Any], start_lane: str) -> np.ndarray:
    path, _ = shared._chain_path(polylines, shared._lane_chain(polylines, start_lane))
    return np.asarray(path, dtype=np.float64)[:, :2]


def _roundabout_cycle(polylines: dict[str, Any], start_lane: str) -> np.ndarray:
    center = np.asarray([1555.0, 1740.0], dtype=np.float64)
    lanes = {
        str(key): value
        for key, value in polylines.items()
        if int(value.get("type", -1)) == 0 and len(value.get("states", [])) >= 2
    }
    candidates = set()
    for key, value in lanes.items():
        radius = np.linalg.norm(np.asarray(value["states"], dtype=np.float64)[:, :2] - center, axis=1)
        if float(radius.min()) < 100.0 and float(radius.max()) < 125.0:
            candidates.add(key)
    graph = {
        key: [str(item) for item in lanes[key].get("next_lanes_id", []) if str(item) in candidates]
        for key in candidates
    }
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[set[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], indices[target])
        if lowlink[node] != indices[node]:
            return
        component: set[str] = set()
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == node:
                break
        components.append(component)

    for lane_id in graph:
        if lane_id not in indices:
            visit(lane_id)
    component = next((item for item in components if start_lane in item and len(item) > 20), None)
    if component is None:
        raise ValueError(f"Roundabout cycle containing lane {start_lane} was not found")

    def polar_angle(lane_id: str) -> float:
        states = np.asarray(lanes[lane_id]["states"], dtype=np.float64)
        midpoint = states[len(states) // 2, :2] - center
        return math.atan2(float(midpoint[1]), float(midpoint[0]))

    sequence = [start_lane]
    current = start_lane
    while len(sequence) <= len(component) + 2:
        current_states = np.asarray(lanes[current]["states"], dtype=np.float64)
        options = []
        for target in lanes[current].get("next_lanes_id", []):
            target = str(target)
            if target not in component:
                continue
            target_states = np.asarray(lanes[target]["states"], dtype=np.float64)
            angular_progress = (polar_angle(target) - polar_angle(current)) % (2.0 * math.pi)
            gap = float(np.linalg.norm(current_states[-1, :2] - target_states[0, :2]))
            heading_jump = abs(
                math.atan2(
                    math.sin(float(target_states[0, 2] - current_states[-1, 2])),
                    math.cos(float(target_states[0, 2] - current_states[-1, 2])),
                )
            )
            options.append((angular_progress + 0.02 * gap + 0.1 * heading_jump, target))
        if not options:
            raise ValueError(f"Roundabout cycle ended at lane {current}")
        target = min(options)[1]
        if target == start_lane:
            break
        if target in sequence:
            raise ValueError(f"Roundabout cycle repeated at lane {target}")
        sequence.append(target)
        current = target
    else:
        raise ValueError("Roundabout cycle did not close")
    chunks = []
    for lane_id in sequence:
        states = np.asarray(lanes[lane_id]["states"], dtype=np.float64)[:, :2]
        if chunks and np.linalg.norm(chunks[-1][-1] - states[0]) < 0.1:
            states = states[1:]
        chunks.append(states)
    return np.concatenate(chunks, axis=0)


def _load_road(spec: ScenarioSpec) -> tuple[RoadPath, dict[str, Any]]:
    with spec.map_path.open("rb") as stream:
        map_bundle = pickle.load(stream)
    polylines = map_bundle["polyline"]
    if spec.road_form == "roundabout":
        points = _roundabout_cycle(polylines, "15185")
        road = RoadPath(points, closed=True, smoothing_passes=6)
    else:
        road = RoadPath(_chain_points(polylines, "1547"), closed=False, smoothing_passes=2)
    return road, map_bundle


def _lateral_profile(
    times: np.ndarray,
    *,
    start: float,
    merge_start: float,
    impact_time: float,
    impact: float,
    final: float,
) -> np.ndarray:
    values = np.full_like(times, start, dtype=np.float64)
    merge_mask = (times >= merge_start) & (times <= impact_time)
    progress = (times[merge_mask] - merge_start) / (impact_time - merge_start)
    values[merge_mask] = start + (impact - start) * _smoothstep5(progress)
    settle_end = impact_time + 1.4
    settle_mask = (times > impact_time) & (times <= settle_end)
    progress = (times[settle_mask] - impact_time) / (settle_end - impact_time)
    values[settle_mask] = impact + (final - impact) * _smoothstep5(progress)
    values[times > settle_end] = final
    return values


def _states_from_positions(positions: np.ndarray, *, max_yaw_rate: float) -> np.ndarray:
    positions = np.asarray(positions, dtype=np.float64)
    velocity = np.gradient(positions, STEP_SECONDS, axis=0, edge_order=2)
    speed = np.linalg.norm(velocity, axis=1)
    raw_heading = np.unwrap(np.arctan2(velocity[:, 1], velocity[:, 0]))
    valid = speed > 0.05
    if not np.any(valid):
        raw_heading[:] = 0.0
    else:
        valid_indices = np.flatnonzero(valid)
        raw_heading = np.interp(np.arange(len(raw_heading)), valid_indices, raw_heading[valid_indices])
    heading = np.empty_like(raw_heading)
    heading[0] = raw_heading[0]
    max_step = max(0.01, float(max_yaw_rate) * STEP_SECONDS)
    for index in range(1, len(heading)):
        delta = float(_wrap_angle(raw_heading[index] - heading[index - 1]))
        heading[index] = heading[index - 1] + float(np.clip(delta, -max_step, max_step))
    acceleration = np.gradient(velocity, STEP_SECONDS, axis=0, edge_order=2)
    return np.column_stack(
        [positions, _wrap_angle(heading), velocity, acceleration]
    ).astype(np.float64)


def _build_tracks(spec: ScenarioSpec, road: RoadPath) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    times = np.arange(FRAME_COUNT, dtype=np.float64) * STEP_SECONDS
    impact_index = int(round(spec.collision_time / STEP_SECONDS))
    lane_offset = 3.65 if spec.road_form == "straight" else 4.0
    impact_gap = 4.58
    diagnostics: dict[str, Any] = {
        "initial_longitudinal": {},
        "initial_lateral": {},
        "longitudinal": {},
        "lateral": {},
    }

    if spec.collision_type == "rearend":
        lead_bridge_start = 1.8 if spec.speed_class == "low" else 1.0
        if spec.road_form == "roundabout":
            lead_bridge_start = 1.3
        lead_impact_s = (
            spec.collision_start_s
            + spec.collision_speed * lead_bridge_start
            + 0.5
            * (spec.collision_speed + spec.lead_impact_speed)
            * (spec.collision_time - lead_bridge_start)
        )
        collision_s = _controlled_longitudinal(
            times,
            start_s=spec.collision_start_s,
            start_speed=spec.collision_speed,
            bridge_start=lead_bridge_start,
            impact_time=spec.collision_time,
            impact_s=lead_impact_s,
            impact_speed=spec.lead_impact_speed,
            post_speed=spec.collision_post_speed,
        )
        av_impact_s = lead_impact_s - impact_gap
        av_s = _controlled_longitudinal(
            times,
            start_s=spec.av_start_s,
            start_speed=spec.av_speed,
            bridge_start=0.8,
            impact_time=spec.collision_time,
            impact_s=av_impact_s,
            impact_speed=spec.av_impact_speed,
            post_speed=spec.av_post_speed,
        )
        post_impact = times > spec.collision_time
        separation_progress = _smoothstep5(
            (times[post_impact] - spec.collision_time) / 0.5
        )
        minimum_gap = impact_gap + 1.2 * separation_progress
        collision_s[post_impact] = np.maximum(
            collision_s[post_impact],
            av_s[post_impact] + minimum_gap,
        )
        av_lateral = np.zeros_like(times)
        collision_lateral = np.zeros_like(times)
    else:
        av_impact_s = spec.av_start_s + spec.av_speed * spec.collision_time
        av_s = _controlled_longitudinal(
            times,
            start_s=spec.av_start_s,
            start_speed=spec.av_speed,
            bridge_start=max(0.0, spec.collision_time - 0.8),
            impact_time=spec.collision_time,
            impact_s=av_impact_s,
            impact_speed=spec.av_impact_speed,
            post_speed=spec.av_post_speed,
        )
        collision_impact_s = av_impact_s + 4.05
        collision_s = _controlled_longitudinal(
            times,
            start_s=spec.collision_start_s,
            start_speed=spec.collision_speed,
            bridge_start=0.7,
            impact_time=spec.collision_time,
            impact_s=collision_impact_s,
            impact_speed=spec.lead_impact_speed,
            post_speed=spec.collision_post_speed,
        )
        av_lateral = np.zeros_like(times)
        collision_lateral = _lateral_profile(
            times,
            start=lane_offset,
            merge_start=max(0.5, spec.collision_time - 1.4),
            impact_time=spec.collision_time,
            impact=1.35,
            final=0.0,
        )

    if spec.road_form == "roundabout" and spec.collision_type == "cutin":
        background_1_s = spec.av_start_s + 30.0 + min(spec.av_speed + 0.5, 9.0) * times
    else:
        background_1_s = spec.av_start_s - (25.0 if spec.road_form == "straight" else 70.0) + min(spec.av_speed, 9.0) * times
    background_2_s = spec.av_start_s + (68.0 if spec.road_form == "straight" else 140.0) + min(spec.av_speed, 7.0) * times
    background_1_lateral = (
        np.zeros_like(times)
        if spec.road_form == "roundabout" and spec.collision_type == "cutin"
        else np.full_like(times, lane_offset)
    )
    background_2_lateral = np.full_like(times, lane_offset)
    longitudinal = {
        AV_ID: av_s,
        COLLISION_ACTOR_ID: collision_s,
        BACKGROUND_IDS[0]: background_1_s,
        BACKGROUND_IDS[1]: background_2_s,
    }
    lateral = {
        AV_ID: av_lateral,
        COLLISION_ACTOR_ID: collision_lateral,
        BACKGROUND_IDS[0]: background_1_lateral,
        BACKGROUND_IDS[1]: background_2_lateral,
    }
    max_yaw_rate = (
        0.95
        if spec.road_form == "straight" and spec.collision_type == "cutin"
        else 0.65
        if spec.road_form == "roundabout" and spec.collision_type == "cutin"
        else 0.55
        if spec.road_form == "roundabout"
        else 0.65
    )
    tracks = {
        actor_id: _states_from_positions(
            road.sample(longitudinal[actor_id], lateral[actor_id]),
            max_yaw_rate=max_yaw_rate,
        )
        for actor_id in ACTOR_IDS
    }
    diagnostics["initial_longitudinal"] = {
        actor_id: float(values[0]) for actor_id, values in longitudinal.items()
    }
    diagnostics["initial_lateral"] = {
        actor_id: float(values[0]) for actor_id, values in lateral.items()
    }
    diagnostics["longitudinal"] = longitudinal
    diagnostics["lateral"] = lateral
    diagnostics["impact_index"] = impact_index
    return tracks, diagnostics


def _collision_events(tracks: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    events = []
    for step in range(FRAME_COUNT):
        pairs = []
        for first_index, first_id in enumerate(ACTOR_IDS):
            for second_id in ACTOR_IDS[first_index + 1 :]:
                if oriented_boxes_overlap(
                    tracks[first_id][step, :3],
                    VEHICLE_SIZE[:2],
                    tracks[second_id][step, :3],
                    VEHICLE_SIZE[:2],
                ):
                    pairs.append(sorted([first_id, second_id]))
        if pairs:
            events.append(
                {
                    "step": step,
                    "time_seconds": round(step * STEP_SECONDS, 3),
                    "pairs": pairs,
                }
            )
    return events


def _validate_tracks(
    spec: ScenarioSpec,
    tracks: dict[str, np.ndarray],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    events = _collision_events(tracks)
    intended_pair = sorted([AV_ID, COLLISION_ACTOR_ID])
    intended_events = [
        event for event in events if intended_pair in [sorted(pair) for pair in event["pairs"]]
    ]
    unexpected_pairs = sorted(
        {
            tuple(sorted(pair))
            for event in events
            for pair in event["pairs"]
            if sorted(pair) != intended_pair
        }
    )
    if not intended_events:
        raise ValueError(f"{spec.slug} did not produce the intended AV collision")
    if unexpected_pairs:
        raise ValueError(f"{spec.slug} contains unexpected collisions: {unexpected_pairs}")
    if len(intended_events) > 8:
        raise ValueError(f"{spec.slug} collision persists for {len(intended_events)} frames")

    heading_metrics = {}
    for actor_id, states in tracks.items():
        heading_step = np.abs(_wrap_angle(np.diff(states[:, 2])))
        velocity_heading = np.arctan2(states[:, 4], states[:, 3])
        speed = np.linalg.norm(states[:, 3:5], axis=1)
        moving = speed > 0.5
        alignment = np.abs(_wrap_angle(velocity_heading[moving] - states[moving, 2]))
        max_heading_step = float(np.max(heading_step)) if len(heading_step) else 0.0
        max_alignment = float(np.max(alignment)) if len(alignment) else 0.0
        if max_heading_step > 0.11:
            raise ValueError(
                f"{spec.slug} {actor_id} heading changes {math.degrees(max_heading_step):.2f} deg/frame"
            )
        if max_alignment > 0.25:
            raise ValueError(
                f"{spec.slug} {actor_id} body/velocity mismatch is {math.degrees(max_alignment):.2f} deg"
            )
        heading_metrics[actor_id] = {
            "max_heading_change_degrees_per_frame": round(math.degrees(max_heading_step), 4),
            "max_body_velocity_alignment_error_degrees": round(math.degrees(max_alignment), 4),
        }

    first = intended_events[0]
    last = intended_events[-1]
    av_s = diagnostics["longitudinal"][AV_ID]
    collision_s = diagnostics["longitudinal"][COLLISION_ACTOR_ID]
    lateral = diagnostics["lateral"][COLLISION_ACTOR_ID]
    if spec.collision_type == "rearend":
        if collision_s[0] <= av_s[0]:
            raise ValueError(f"{spec.slug} lead vehicle does not start in front of the AV")
    else:
        if collision_s[0] >= av_s[0] or lateral[0] < 3.0:
            raise ValueError(f"{spec.slug} cut-in vehicle is not initially side-rear")
        collision_step = int(first["step"])
        if collision_s[collision_step] <= av_s[collision_step]:
            raise ValueError(f"{spec.slug} cut-in vehicle does not reach the AV side-front")

    return {
        "schema": "trafficwm.collision-scenario-validation.v2",
        "scenario": spec.slug,
        "road_form": spec.road_form,
        "collision_type": spec.collision_type,
        "speed_class": spec.speed_class,
        "frames": FRAME_COUNT,
        "duration_seconds": DURATION_SECONDS,
        "fps": 1.0 / STEP_SECONDS,
        "ego_id": AV_ID,
        "collision_actor_id": COLLISION_ACTOR_ID,
        "collision_pair": intended_pair,
        "collision_frames": len(intended_events),
        "first_collision_step": int(first["step"]),
        "first_collision_time_seconds": float(first["time_seconds"]),
        "last_collision_step": int(last["step"]),
        "last_collision_time_seconds": float(last["time_seconds"]),
        "unexpected_collision_pairs": [list(pair) for pair in unexpected_pairs],
        "initial_relation": (
            "AV follows lead vehicle"
            if spec.collision_type == "rearend"
            else "collision vehicle starts side-rear and reaches AV side-front"
        ),
        "initial_av_speed_mps": round(float(np.linalg.norm(tracks[AV_ID][0, 3:5])), 4),
        "initial_collision_actor_speed_mps": round(
            float(np.linalg.norm(tracks[COLLISION_ACTOR_ID][0, 3:5])), 4
        ),
        "heading_continuity": heading_metrics,
    }


def _empty_mixed_traffic() -> dict[str, Any]:
    return {
        "schema": "trafficwm.mixed-traffic.v1",
        "enabled": False,
        "cyclist_ratio": 0.0,
        "pedestrians_per_crosswalk": 0,
        "max_pedestrians": 0,
        "vehicle_size_mode": "passenger_only",
        "crosswalks": 0,
    }


def _build_recording(
    spec: ScenarioSpec,
    tracks: dict[str, np.ndarray],
    map_bundle: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    with BASE_RECORDING.open("rb") as stream:
        recording = pickle.load(stream)
    recording = copy.deepcopy(recording)
    recording["vehicle_id_per_step"] = [list(ACTOR_IDS) for _ in range(FRAME_COUNT)]
    recording["vehicle_state_per_step"] = [
        np.stack([tracks[actor_id][step] for actor_id in ACTOR_IDS]).astype(np.float64)
        for step in range(FRAME_COUNT)
    ]
    recording["vehicle_static_attribute"] = {
        actor_id: VEHICLE_SIZE.copy() for actor_id in ACTOR_IDS
    }
    recording["road_user_type"] = {actor_id: "vehicle" for actor_id in ACTOR_IDS}
    recording["vehicle_class"] = {actor_id: "sedan" for actor_id in ACTOR_IDS}
    recording["vehicle_type"] = {
        actor_id: "csim.agent.agent.RoutedVehicle" for actor_id in ACTOR_IDS
    }
    recording["pedestrian_id_per_step"] = [[] for _ in range(FRAME_COUNT)]
    recording["pedestrian_state_per_step"] = [[] for _ in range(FRAME_COUNT)]
    recording["pedestrian_static_attribute"] = {}
    recording["pedestrian_crosswalk"] = {}
    recording["dynamic_polyline_id_per_step"] = [[] for _ in range(FRAME_COUNT)]
    recording["dynamic_polyline_state_per_step"] = [[] for _ in range(FRAME_COUNT)]
    all_points = np.concatenate(
        [np.asarray(value["states"], dtype=np.float64)[:, :2] for value in map_bundle["polyline"].values()]
    )
    recording["map"] = {
        "polyline": map_bundle["polyline"],
        "map_center": np.mean(all_points, axis=0),
    }
    recording["routes"] = {}
    recording["mixed_traffic"] = _empty_mixed_traffic()
    recording.pop("experiment_params", None)
    simulator = dict(recording.get("simulator_meta_info") or {})
    simulator.update(
        {
            "resolution": STEP_SECONDS,
            "trafficwm_collision_scenario": {
                "schema": "trafficwm.scripted-collision.v2",
                "collision_type": spec.collision_type,
                "road_form": spec.road_form,
                "speed_class": spec.speed_class,
                "ego_id": AV_ID,
                "collision_actor_id": COLLISION_ACTOR_ID,
                "collision_pair": report["collision_pair"],
                "collision_start_step": report["first_collision_step"],
                "collision_start_time_seconds": report["first_collision_time_seconds"],
            },
        }
    )
    recording["simulator_meta_info"] = simulator
    return recording


def _build_initialization(
    recording: dict[str, Any],
    road: RoadPath,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    history = copy.deepcopy(recording)
    history_times = np.linspace(-(HISTORY_FRAMES - 1) * STEP_SECONDS, 0.0, HISTORY_FRAMES)
    history_tracks = {}
    for actor_id in ACTOR_IDS:
        start_s = float(diagnostics["initial_longitudinal"][actor_id])
        start_lateral = float(diagnostics["initial_lateral"][actor_id])
        initial_state = np.asarray(recording["vehicle_state_per_step"][0][ACTOR_IDS.index(actor_id)])
        speed = float(np.linalg.norm(initial_state[3:5]))
        positions = road.sample(start_s + speed * history_times, start_lateral)
        states = _states_from_positions(
            positions,
            max_yaw_rate=0.95 if not road.closed else 0.55,
        )
        states[-1] = initial_state
        history_tracks[actor_id] = states
    history["vehicle_id_per_step"] = [list(ACTOR_IDS) for _ in range(HISTORY_FRAMES)]
    history["vehicle_state_per_step"] = [
        np.stack([history_tracks[actor_id][step] for actor_id in ACTOR_IDS]).astype(np.float64)
        for step in range(HISTORY_FRAMES)
    ]
    for key in (
        "pedestrian_id_per_step",
        "pedestrian_state_per_step",
        "dynamic_polyline_id_per_step",
        "dynamic_polyline_state_per_step",
    ):
        history[key] = [[] for _ in range(HISTORY_FRAMES)]
    simulator = dict(history.get("simulator_meta_info") or {})
    simulator["trafficwm_seed_initialization"] = {
        "schema": "trafficwm.scripted-collision-initialization.v2",
        "history_steps": HISTORY_FRAMES,
        "ego_id": AV_ID,
    }
    history["simulator_meta_info"] = simulator
    return history


def _prompt(spec: ScenarioSpec) -> str:
    base = ROUNDABOUT_PROMPT if spec.road_form == "roundabout" else STRAIGHT_PROMPT
    if spec.collision_type == "rearend":
        event = (
            " The ego vehicle follows a sedan in the same lane. The lead sedan brakes normally "
            "or stops while remaining aligned with the road, and the rear ego vehicle makes a "
            "brief front-to-rear contact with its rear bumper."
        )
    else:
        event = (
            " A sedan begins in the adjacent lane behind and beside the ego vehicle, accelerates "
            "forward, follows one continuous steering arc toward the ego lane, reaches the ego "
            "side-front, and makes brief side contact before separating ahead."
        )
    return base + event


def _publish(
    spec: ScenarioSpec,
    recording: dict[str, Any],
    initialization: dict[str, Any],
    report: dict[str, Any],
    *,
    library_dir: Path,
) -> dict[str, Any]:
    target = library_dir / f"{spec.slug}.pkl"
    init_target = library_dir / f"{spec.slug}.init.pkl"
    seed_target = library_dir / f"{spec.slug}.seed.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        pickle.dump(recording, stream, protocol=pickle.HIGHEST_PROTOCOL)
    with init_target.open("wb") as stream:
        pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
    seed_target.unlink(missing_ok=True)
    scenario_hash = shared._step_sha256(recording, 0)
    initialization_hash = shared._step_sha256(initialization, -1)
    if scenario_hash != initialization_hash:
        raise ValueError(f"{spec.slug} initialization does not end at scenario frame zero")
    prompt = _prompt(spec)
    metadata = {
        "schema": "denseworld.standard-scenario.v2",
        "library_id": spec.library_id,
        "library_name": spec.name,
        "library_description": (
            f"{spec.road_form} {spec.speed_class} {spec.collision_type} deterministic AV collision"
        ),
        "library_category": "normal",
        "library_tags": [
            "collision",
            spec.road_form,
            spec.speed_class,
            spec.collision_type,
            "AV",
            "Transfer1",
        ],
        "backend_model": "rulebased",
        "standard_backend_locked": True,
        "traffic_controller": "deterministic_collision_replay_v2",
        "map_path": _relative(spec.map_path),
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
        "max_pedestrians": 0,
        "vehicle_size_mode": "passenger_only",
        "initial_speed_mode": "recorded",
        "signalize_unsignalized_map": False,
        "world_loop_ego": False,
        "participants": {"motorized": len(ACTOR_IDS), "pedestrians": 0, "cyclists": 0},
        "peak_participants": {"motorized": len(ACTOR_IDS), "pedestrians": 0, "cyclists": 0},
        "source_path": _relative(target),
        "source_format": "trafficwm.scripted-collision.v2",
        "source_start_seconds": 0.0,
        "source_end_seconds": DURATION_SECONDS,
        "native_traffic_fps": 10.0,
        "default_world_prompt": prompt,
        "default_transfer_prompt": prompt,
        "default_transfer_negative_prompt": (
            ROUNDABOUT_TRANSFER_NEGATIVE_PROMPT if spec.road_form == "roundabout" else ""
        ),
        "world_omnidreams_seed": (
            0 if spec.slug == "collision_yizhuang_roundabout_rearend" else 1
        ),
        "world_omnidreams_actor_allow_overlap": True,
        "world_omnidreams_actor_hood_occlusion_distance_m": 0.0,
        "world_omnidreams_actor_hood_occlusion_lateral_m": 0.0,
        "world_omnidreams_actor_oncoming_lateral_exclusion_m": 0.0,
        "world_omnidreams_actor_max_count": 3,
        "world_seed_map_radius_m": 115.0,
        "world_map_radius_m": 145.0,
        "world_local_target_count": len(ACTOR_IDS),
        "world_initial_vehicle_limit": len(ACTOR_IDS),
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
        "seed_source_fps": 24.0,
        "seed_warmup_seconds": 0.0,
        "seed_scenario_state_step": 0,
        "seed_initialization_state_step": HISTORY_FRAMES - 1,
        "seed_initialization_history_frames": HISTORY_FRAMES,
        "seed_alignment": "exact_control_frame_t0",
        "seed_ego_id": AV_ID,
        "seed_width": 1280,
        "seed_height": 704,
        "seed_sha256": "",
        "seed_init_sha256": hashlib.sha256(init_target.read_bytes()).hexdigest(),
        "seed_state_sha256": scenario_hash,
        "expected_collision": {
            "type": spec.collision_type,
            "road_form": spec.road_form,
            "speed_class": spec.speed_class,
            "ego_id": AV_ID,
            "collision_actor_id": COLLISION_ACTOR_ID,
            "pair": report["collision_pair"],
            "first_time_seconds": report["first_collision_time_seconds"],
            "last_time_seconds": report["last_collision_time_seconds"],
            "frames": report["collision_frames"],
            "persistent_contact_after_impact": False,
        },
        "rule_control": {
            "bv_controller": "DeterministicCollisionScriptV2",
            "av_controller": "DeterministicCollisionScriptV2",
            "collision_type": spec.collision_type,
            "road_form": spec.road_form,
            "speed_class": spec.speed_class,
        },
    }
    metadata_path = target.with_suffix(target.suffix + ".meta.json")
    metadata_path.write_text(
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
                "actor_tracks": len(ACTOR_IDS),
                "expected_collision": metadata["expected_collision"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "id": spec.library_id,
        "name": spec.name,
        "path": _relative(target),
        "metadata": _relative(metadata_path),
        "map_path": metadata["map_path"],
        "collision_type": spec.collision_type,
        "road_form": spec.road_form,
        "speed_class": spec.speed_class,
        "collision_time_seconds": report["first_collision_time_seconds"],
        "collision_frames": report["collision_frames"],
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
        default=ROOT / "output/validation/collision_scenario_matrix_20260828",
    )
    args = parser.parse_args()
    args.library_dir.mkdir(parents=True, exist_ok=True)
    args.validation_dir.mkdir(parents=True, exist_ok=True)
    records = []
    validations = []
    for spec in SPECS:
        road, map_bundle = _load_road(spec)
        tracks, diagnostics = _build_tracks(spec, road)
        report = _validate_tracks(spec, tracks, diagnostics)
        recording = _build_recording(spec, tracks, map_bundle, report)
        initialization = _build_initialization(recording, road, diagnostics)
        published = _publish(
            spec,
            recording,
            initialization,
            report,
            library_dir=args.library_dir,
        )
        report_path = args.validation_dir / f"{spec.slug}.json"
        report["path"] = _relative(report_path)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        records.append(published)
        validations.append(report)
    manifest = {
        "schema": "trafficwm.collision-scenario-matrix.v2",
        "count": len(records),
        "records": records,
        "validation": validations,
    }
    manifest_path = args.validation_dir / "scenarios.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({**manifest, "manifest": _relative(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
