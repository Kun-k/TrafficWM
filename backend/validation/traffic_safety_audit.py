"""Streamed geometry and local-density audit for DenseWorld traffic captures."""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable

from backend.algorithms.citynde.mixed_traffic_core import oriented_boxes_overlap


LOCAL_RADII_METERS = (30.0, 60.0, 120.0, 140.0)


def _summary(values: list[float | int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "p10": 0, "median": 0, "p90": 0, "max": 0, "mean": 0.0}
    ordered = sorted(values)

    def quantile(fraction: float) -> float | int:
        return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))]

    return {
        "min": min(values),
        "p10": quantile(0.1),
        "median": statistics.median(values),
        "p90": quantile(0.9),
        "max": max(values),
        "mean": round(statistics.fmean(values), 4),
    }


def _rms(values: list[float]) -> float | None:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return None
    return round(math.sqrt(statistics.fmean(value * value for value in finite)), 4)


def _percentile(values: list[float], fraction: float) -> float | None:
    finite = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not finite:
        return None
    index = min(len(finite) - 1, max(0, int(round((len(finite) - 1) * fraction))))
    return round(finite[index], 4)


def _frames(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"Traffic frame {line_number} is not an object")
            yield value


def _actor_values(actor: dict[str, Any]) -> tuple[float, ...]:
    return (
        float(actor.get("x", 0.0)),
        float(actor.get("y", 0.0)),
        float(actor.get("heading", 0.0)),
        max(0.1, float(actor.get("length", 3.8))),
        max(0.1, float(actor.get("width", 1.8))),
    )


def _frame_overlaps(actors: list[dict[str, Any]]) -> list[tuple[str, str]]:
    prepared = []
    for actor in actors:
        x, y, heading, length, width = _actor_values(actor)
        x_radius = 0.5 * (length * abs(math.cos(heading)) + width * abs(math.sin(heading)))
        y_radius = 0.5 * (length * abs(math.sin(heading)) + width * abs(math.cos(heading)))
        prepared.append(
            {
                "id": str(actor.get("id", "")),
                "x": x,
                "y": y,
                "heading": heading,
                "length": length,
                "width": width,
                "x_radius": x_radius,
                "y_radius": y_radius,
            }
        )
    prepared.sort(key=lambda item: item["x"])
    maximum_x_radius = max((item["x_radius"] for item in prepared), default=0.0)
    overlaps = []
    for first_index, first in enumerate(prepared):
        for second in prepared[first_index + 1 :]:
            if second["x"] - first["x"] > first["x_radius"] + maximum_x_radius:
                break
            if abs(second["y"] - first["y"]) > first["y_radius"] + second["y_radius"]:
                continue
            if oriented_boxes_overlap(
                (first["x"], first["y"], first["heading"]),
                (first["length"], first["width"]),
                (second["x"], second["y"], second["heading"]),
                (second["length"], second["width"]),
            ):
                overlaps.append(tuple(sorted((first["id"], second["id"]))))
    return overlaps


def audit_traffic_safety(
    traffic_stream_path: Path,
    output_path: Path,
    *,
    expected_fps: float = 10.0,
    require_local_density: bool = True,
    minimum_motorized_60m: int = 6,
    minimum_motorized_120m: int = 12,
) -> dict[str, Any]:
    """Audit every captured state without loading the large NDJSON file into memory."""
    traffic_stream_path = traffic_stream_path.resolve()
    actor_counts: list[int] = []
    av_speeds: list[float] = []
    sim_times: list[float] = []
    positions: list[tuple[float, float]] = []
    longitudinal_accelerations: list[float] = []
    lateral_accelerations: list[float] = []
    minimum_ttc_samples: list[float] = []
    minimum_headway_samples: list[float] = []
    local_all = {radius: [] for radius in LOCAL_RADII_METERS}
    local_motorized = {radius: [] for radius in LOCAL_RADII_METERS}
    local_cyclists = {radius: [] for radius in LOCAL_RADII_METERS}
    overlap_frames = 0
    av_overlap_frames = 0
    overlap_observations = 0
    overlap_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    first_ids: set[str] = set()
    all_ids: set[str] = set()
    first_type_counts: dict[str, int] = {}
    last_type_counts: dict[str, int] = {}
    nonfinite_observations = 0
    heading_range_violations = 0
    violation_evaluated_frames = 0
    off_lane_frames = 0
    red_light_crossing_events = 0
    previous_red_stopline_ids: set[str] = set()
    ego_id = ""

    for frame_index, frame in enumerate(_frames(traffic_stream_path)):
        ego = frame.get("ego") or {}
        if not isinstance(ego, dict) or not ego:
            raise ValueError(f"Traffic frame {frame_index} has no ego state")
        ego_id = str(ego.get("id", ego_id))
        actors = [ego, *(frame.get("vehicles") or [])]
        actor_counts.append(len(actors))
        sim_times.append(float(frame.get("sim_time", 0.0)))
        ego_x, ego_y = float(ego.get("x", 0.0)), float(ego.get("y", 0.0))
        positions.append((ego_x, ego_y))
        av_speeds.append(float(ego.get("speed", 0.0)))
        lane_context = frame.get("lane_context")
        if isinstance(lane_context, dict) and lane_context:
            violation_evaluated_frames += 1
            if not str(lane_context.get("current_id") or "").strip():
                off_lane_frames += 1
            signals = lane_context.get("signals")
            signals = signals if isinstance(signals, list) else []
            current_signal_ids = {
                str(signal.get("id") or "")
                for signal in signals
                if isinstance(signal, dict) and str(signal.get("id") or "")
            }
            if av_speeds[-1] >= 0.35:
                red_light_crossing_events += len(
                    previous_red_stopline_ids - current_signal_ids
                )
            previous_red_stopline_ids = {
                str(signal.get("id") or "")
                for signal in signals
                if isinstance(signal, dict)
                and int(signal.get("state", -1) or -1) == 2
                and float(signal.get("distance_m", float("inf")) or 0.0) <= max(
                    0.75,
                    av_speeds[-1] / max(1.0, float(expected_fps)) + 0.25,
                )
            }
        else:
            previous_red_stopline_ids = set()
        ego_heading = float(ego.get("heading", 0.0))
        heading_cos = math.cos(ego_heading)
        heading_sin = math.sin(ego_heading)
        ego_ax = float(ego.get("ax", 0.0))
        ego_ay = float(ego.get("ay", 0.0))
        longitudinal_accelerations.append(ego_ax * heading_cos + ego_ay * heading_sin)
        lateral_accelerations.append(-ego_ax * heading_sin + ego_ay * heading_cos)

        ego_vx = float(ego.get("vx", av_speeds[-1] * heading_cos))
        ego_vy = float(ego.get("vy", av_speeds[-1] * heading_sin))
        ego_length = max(0.1, float(ego.get("length", 3.8)))
        ego_width = max(0.1, float(ego.get("width", 1.8)))
        frame_headways: list[float] = []
        frame_ttcs: list[float] = []
        for actor in frame.get("vehicles") or []:
            actor_type = str(actor.get("road_user_type") or actor.get("type") or "vehicle").lower()
            if actor_type == "pedestrian":
                continue
            dx = float(actor.get("x", 0.0)) - ego_x
            dy = float(actor.get("y", 0.0)) - ego_y
            longitudinal = dx * heading_cos + dy * heading_sin
            lateral = abs(-dx * heading_sin + dy * heading_cos)
            actor_length = max(0.1, float(actor.get("length", 3.8)))
            actor_width = max(0.1, float(actor.get("width", 1.8)))
            lane_width = max(2.5, 0.75 * (ego_width + actor_width))
            if longitudinal <= 0.0 or lateral > lane_width:
                continue
            gap = max(0.0, longitudinal - 0.5 * (ego_length + actor_length))
            frame_headways.append(gap)
            actor_vx = float(actor.get("vx", float(actor.get("speed", 0.0)) * math.cos(float(actor.get("heading", 0.0)))))
            actor_vy = float(actor.get("vy", float(actor.get("speed", 0.0)) * math.sin(float(actor.get("heading", 0.0)))))
            closing_speed = (ego_vx - actor_vx) * heading_cos + (ego_vy - actor_vy) * heading_sin
            if closing_speed > 0.1:
                frame_ttcs.append(gap / closing_speed)
        if frame_headways:
            minimum_headway_samples.append(min(frame_headways))
        if frame_ttcs:
            minimum_ttc_samples.append(min(frame_ttcs))
        frame_ids = {str(actor.get("id", "")) for actor in actors}
        if frame_index == 0:
            first_ids = set(frame_ids)
        all_ids.update(frame_ids)

        type_counts: dict[str, int] = {}
        for actor in actors:
            actor_type = str(actor.get("road_user_type") or actor.get("type") or "vehicle").lower()
            type_counts[actor_type] = type_counts.get(actor_type, 0) + 1
            values = _actor_values(actor)
            if not all(math.isfinite(value) for value in values):
                nonfinite_observations += 1
            if abs(values[2]) > math.pi + 1e-6:
                heading_range_violations += 1
        if frame_index == 0:
            first_type_counts = dict(type_counts)
        last_type_counts = dict(type_counts)

        for radius in LOCAL_RADII_METERS:
            nearby = [
                actor
                for actor in actors
                if str(actor.get("id", "")) != ego_id
                and math.hypot(float(actor.get("x", 0.0)) - ego_x, float(actor.get("y", 0.0)) - ego_y)
                <= radius
            ]
            local_all[radius].append(len(nearby))
            local_motorized[radius].append(
                sum(
                    str(actor.get("road_user_type") or actor.get("type") or "vehicle").lower()
                    not in {"pedestrian", "cyclist", "non_motorized"}
                    for actor in nearby
                )
            )
            local_cyclists[radius].append(
                sum(
                    str(actor.get("road_user_type") or actor.get("type") or "").lower()
                    in {"cyclist", "non_motorized"}
                    for actor in nearby
                )
            )

        overlaps = _frame_overlaps(actors)
        if overlaps:
            overlap_frames += 1
            overlap_observations += len(overlaps)
        if any(ego_id in pair for pair in overlaps):
            av_overlap_frames += 1
        for pair in overlaps:
            item = overlap_pairs.setdefault(
                pair,
                {
                    "ids": list(pair),
                    "frames": 0,
                    "first_time_seconds": sim_times[-1],
                    "last_time_seconds": sim_times[-1],
                },
            )
            item["frames"] += 1
            item["last_time_seconds"] = sim_times[-1]

    if not sim_times:
        raise ValueError("Traffic capture is empty")
    time_step = 1.0 / max(1e-9, float(expected_fps))
    time_deltas = [right - left for left, right in zip(sim_times, sim_times[1:])]
    timeline_matches_source = bool(
        math.isclose(sim_times[0], 0.0, abs_tol=1e-6)
        and all(math.isclose(delta, time_step, abs_tol=1e-5) for delta in time_deltas)
    )
    path_distance = sum(
        math.hypot(right[0] - left[0], right[1] - left[1])
        for left, right in zip(positions, positions[1:])
    )
    moving = [speed >= 0.35 for speed in av_speeds]
    stationary_runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for index, is_moving in enumerate(moving):
        if not is_moving and run_start is None:
            run_start = index
        elif is_moving and run_start is not None:
            stationary_runs.append((run_start, index - 1))
            run_start = None
    if run_start is not None:
        stationary_runs.append((run_start, len(moving) - 1))
    longest = max(stationary_runs, key=lambda item: item[1] - item[0], default=(0, -1))
    jerk_magnitudes = [
        math.hypot(right_long - left_long, right_lat - left_lat) / time_step
        for left_long, right_long, left_lat, right_lat in zip(
            longitudinal_accelerations,
            longitudinal_accelerations[1:],
            lateral_accelerations,
            lateral_accelerations[1:],
        )
    ]

    checks = {
        "timeline_matches_source_fps": timeline_matches_source,
        "all_states_are_finite": nonfinite_observations == 0,
        "headings_are_normalized": heading_range_violations == 0,
        "all_actor_obb_clear": overlap_frames == 0,
        "av_obb_clear": av_overlap_frames == 0,
    }
    if math.isclose(float(expected_fps), 10.0, abs_tol=1e-6):
        checks["timeline_matches_10hz"] = timeline_matches_source
    if require_local_density:
        minimum_motorized_60m = max(0, int(minimum_motorized_60m))
        minimum_motorized_120m = max(0, int(minimum_motorized_120m))
        checks.update(
            {
                "av_local_motorized_60m_minimum": (
                    min(local_motorized[60.0]) >= minimum_motorized_60m
                ),
                "av_local_motorized_120m_minimum": (
                    min(local_motorized[120.0]) >= minimum_motorized_120m
                ),
            }
        )
    report = {
        "schema": "denseworld.traffic-safety-audit.v1",
        "passed": all(checks.values()),
        "checks": checks,
        "source": str(traffic_stream_path),
        "timeline": {
            "frames": len(sim_times),
            "duration_seconds": sim_times[-1] - sim_times[0],
            "expected_fps": float(expected_fps),
            "require_local_density": bool(require_local_density),
            "first_sim_time": sim_times[0],
            "last_sim_time": sim_times[-1],
        },
        "actors": {
            "count": _summary(actor_counts),
            "type_count_first": first_type_counts,
            "type_count_last": last_type_counts,
            "unique_ids": len(all_ids),
            "new_ids_after_t0": len(all_ids - first_ids),
            "nonfinite_observations": nonfinite_observations,
            "heading_range_violations": heading_range_violations,
        },
        "local_density": {
            "minimum_motorized_60m": minimum_motorized_60m,
            "minimum_motorized_120m": minimum_motorized_120m,
            "all": {str(int(radius)): _summary(local_all[radius]) for radius in LOCAL_RADII_METERS},
            "motorized": {
                str(int(radius)): _summary(local_motorized[radius]) for radius in LOCAL_RADII_METERS
            },
            "cyclists": {
                str(int(radius)): _summary(local_cyclists[radius]) for radius in LOCAL_RADII_METERS
            },
        },
        "av": {
            "id": ego_id,
            "speed_mps": _summary(av_speeds),
            "moving_frame_ratio": round(sum(moving) / len(moving), 4),
            "path_distance_m": round(path_distance, 4),
            "displacement_m": round(
                math.hypot(
                    positions[-1][0] - positions[0][0],
                    positions[-1][1] - positions[0][1],
                ),
                4,
            ),
            "longest_stationary_run": {
                "start_seconds": sim_times[longest[0]] if longest[1] >= longest[0] else 0.0,
                "end_seconds": sim_times[longest[1]] if longest[1] >= longest[0] else 0.0,
                "duration_seconds": round((longest[1] - longest[0] + 1) * time_step, 4)
                if longest[1] >= longest[0]
                else 0.0,
            },
            "comfort": {
                "longitudinal_acceleration_rms_mps2": _rms(longitudinal_accelerations),
                "lateral_acceleration_rms_mps2": _rms(lateral_accelerations),
                "jerk_magnitude_p95_mps3": _percentile(jerk_magnitudes, 0.95),
            },
            "following": {
                "minimum_ttc_seconds": min(minimum_ttc_samples) if minimum_ttc_samples else None,
                "ttc_p10_seconds": _percentile(minimum_ttc_samples, 0.1),
                "minimum_headway_m": min(minimum_headway_samples) if minimum_headway_samples else None,
                "headway_p10_m": _percentile(minimum_headway_samples, 0.1),
            },
        },
        "collisions": {
            "overlap_frames": overlap_frames,
            "overlap_observations": overlap_observations,
            "av_overlap_frames": av_overlap_frames,
            "pairs": sorted(overlap_pairs.values(), key=lambda item: (-item["frames"], item["ids"])),
        },
        "violations": {
            "available": violation_evaluated_frames > 0,
            "evaluated_frames": violation_evaluated_frames,
            "off_lane_frames": off_lane_frames,
            "red_light_crossing_events": red_light_crossing_events,
            "violation_observations": off_lane_frames + red_light_crossing_events,
            "rate_percent": round(
                100.0
                * (off_lane_frames + red_light_crossing_events)
                / violation_evaluated_frames,
                4,
            )
            if violation_evaluated_frames > 0
            else None,
        },
    }
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
