"""CityNDE adapter for the unified TrafficWM GUI.

This file lives outside the CityNDE source tree. It imports CityNDE classes,
runs generation or replay, and exposes the same `/api/v1` contract used by the
frontend and manager.
"""
from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import itertools
import json
import math
import os
import pickle
import random
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[4]
CITYNDE_ROOT = Path(
    os.environ.get("CITYNDE_ROOT", REPO_ROOT / "algorithm_sources" / "CityNDE_src")
).resolve()
MAP_STATE_CACHE_VERSION = "citynde-map-state-v4"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.common.http_api_viewer import HttpApiViewer
from backend.scene.semantic_map import build_citynde_semantics
from backend.common.offline_av_control import OfflineAVController
from backend.common.av_tcp import AVCommand, AVTCPBridge
from backend.dynamics import rollout_control
from backend.algorithms.citynde.long_horizon import (
    cycle_route_window,
    find_reachable_lane_cycle,
    route_spatial_extent,
)
from backend.algorithms.citynde.mixed_traffic_core import oriented_boxes_overlap
from backend.cosmos.appearance_anchors import (
    load_appearance_anchors,
    select_pose_matched_anchor,
)
from backend.cosmos.seed_alignment import (
    SEED_ALIGNMENT_OPENING_RESTART,
    SEED_ALIGNMENT_TERMINAL_CONTINUE,
    audit_seed_traffic_boundary,
    normalize_seed_alignment_mode,
)


def _configure_citynde_imports(citynde_root: Path) -> None:
    import_roots = [
        citynde_root,
        citynde_root / "nuplan-devkit",
        citynde_root / "tuplan_garage",
    ]
    for import_root in reversed(import_roots):
        if import_root.is_dir():
            path = str(import_root.resolve())
            if path in sys.path:
                sys.path.remove(path)
            sys.path.insert(0, path)
    os.environ["CITYNDE_ROOT"] = str(citynde_root)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except (TypeError, ValueError):
        pass
    return default


def _env_flag(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


class CityNDEProfiler:
    def __init__(self, args: argparse.Namespace, citynde_root: Path):
        self.enabled = bool(args.profile)
        self.step = 0
        self.phase_ms: dict[str, float] = {}
        self.trace_steps = {
            int(item)
            for item in str(args.profile_steps or "").split(",")
            if item.strip().isdigit() and int(item) > 0
        }
        default_name = f"profile_{args.experiment_id or args.experiment_name or int(time.time())}.jsonl"
        self.output_path = Path(args.profile_output).expanduser() if args.profile_output else (
            citynde_root.parent.parent / "backend" / "algorithms" / "citynde" / "data" / "profiles" / default_name
        )
        if self.enabled:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text("", encoding="utf-8")

    @staticmethod
    def _cuda_sync():
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()

    @staticmethod
    def _cuda_memory() -> dict[str, float]:
        import torch

        if not torch.cuda.is_available():
            return {}
        scale = 1024.0 * 1024.0
        return {
            "cuda_allocated_mb": round(torch.cuda.memory_allocated() / scale, 3),
            "cuda_reserved_mb": round(torch.cuda.memory_reserved() / scale, 3),
            "cuda_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / scale, 3),
            "cuda_peak_reserved_mb": round(torch.cuda.max_memory_reserved() / scale, 3),
        }

    def _write(self, payload: dict):
        if not self.enabled:
            return
        with self.output_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def record_initialization(self, elapsed_ms: float):
        if not self.enabled:
            return
        self._write({"event": "initialization", "elapsed_ms": round(elapsed_ms, 3), **self._cuda_memory()})

    def begin_step(self, step: int, vehicles: int):
        if not self.enabled:
            return
        import torch

        self.step = step
        self.phase_ms = {}
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        self._write({"event": "step_begin", "step": step, "vehicles": vehicles, **self._cuda_memory()})

    def timed(self, phase: str, operation):
        if not self.enabled:
            return operation()
        self._cuda_sync()
        started = time.perf_counter()
        result = operation()
        self._cuda_sync()
        self.phase_ms[phase] = (time.perf_counter() - started) * 1000.0
        return result

    def traced(self, phase: str, operation):
        if not self.enabled or self.step not in self.trace_steps:
            return self.timed(phase, operation)
        import cProfile
        import io
        import pstats
        import torch

        self._cuda_sync()
        started = time.perf_counter()
        python_profiler = cProfile.Profile()
        with torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU, torch.profiler.ProfilerActivity.CUDA],
            record_shapes=True,
            profile_memory=True,
            with_stack=False,
        ) as profiler:
            python_profiler.enable()
            result = operation()
            python_profiler.disable()
        self._cuda_sync()
        self.phase_ms[phase] = (time.perf_counter() - started) * 1000.0
        trace_path = self.output_path.with_name(f"{self.output_path.stem}_step_{self.step}.json")
        pstats_path = self.output_path.with_name(f"{self.output_path.stem}_step_{self.step}.pstats")
        profiler.export_chrome_trace(str(trace_path))
        python_profiler.dump_stats(str(pstats_path))
        python_summary = io.StringIO()
        pstats.Stats(python_profiler, stream=python_summary).strip_dirs().sort_stats("cumulative").print_stats(40)
        print(f"[CityNDEProfile] step={self.step} trace={trace_path}", flush=True)
        print(profiler.key_averages().table(sort_by="self_cuda_time_total", row_limit=30), flush=True)
        print(python_summary.getvalue(), flush=True)
        return result

    def end_step(self, vehicles: int):
        if not self.enabled:
            return
        self._write(
            {
                "event": "step_end",
                "step": self.step,
                "vehicles": vehicles,
                "phase_ms": {name: round(value, 3) for name, value in self.phase_ms.items()},
                "total_ms": round(sum(self.phase_ms.values()), 3),
                **self._cuda_memory(),
            }
        )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _display_path(path: Path | str, root: Path = CITYNDE_ROOT) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        pass
    try:
        return str(p.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _resolve_citynde_path(raw_path: str | Path, root: Path = CITYNDE_ROOT) -> Path:
    p = Path(raw_path)
    if not p.is_absolute():
        text = str(raw_path).replace("\\", "/")
        p = REPO_ROOT / p if text.startswith(("algorithm_sources/", "output/")) else root / p
    return p.resolve()


def _map_state_cache_path(map_path: Path) -> Path:
    digest = hashlib.sha256()
    digest.update(MAP_STATE_CACHE_VERSION.encode("ascii"))
    with map_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return REPO_ROOT / "output" / "cache" / "citynde_map_state" / f"{digest.hexdigest()}.json"


def _empty_metrics(total_steps: int = 0, step_seconds: float = 0.1) -> dict[str, Any]:
    return {
        "ok": True,
        "step_seconds": float(step_seconds),
        "sim_resolution": float(step_seconds),
        "computed_steps": 0,
        "total_steps": int(total_steps),
        "vehicle_count_per_step": [],
        "speed_per_step": [],
        "min_ttc_per_step": [],
        "headway_per_step": [],
        "collision_count_per_step": [],
        "collision_rate_per_step": [],
        "speed_samples_per_step": [],
        "ttc_samples_per_step": [],
        "headway_samples_per_step": [],
        "av_min_ttc_per_step": [],
        "av_headway_per_step": [],
        "av_collision_count_per_step": [],
        "av_ttc_samples_per_step": [],
        "av_headway_samples_per_step": [],
        "arrival_rate_per_step": [],
    }


def _set_metric(metrics: dict, key: str, idx: int, value, fill=None):
    arr = metrics.setdefault(key, [])
    while len(arr) <= idx:
        arr.append(fill)
    arr[idx] = value


def _traffic_metrics(vehicles: list[dict], *, pair_limit: int = 180) -> dict[str, Any]:
    traffic_vehicles = [
        vehicle for vehicle in vehicles if str(vehicle.get("type") or "vehicle").lower() != "pedestrian"
    ]
    speeds = [
        float(v.get("speed", 0.0))
        for v in traffic_vehicles
        if math.isfinite(float(v.get("speed", 0.0)))
    ]
    avg_speed = (sum(speeds) / len(speeds)) if speeds else None
    actor_counts = {
        "motorized_count": sum(
            str(vehicle.get("type") or "vehicle").lower() not in {"pedestrian", "cyclist", "non_motorized"}
            for vehicle in vehicles
        ),
        "cyclist_count": sum(
            str(vehicle.get("type") or "").lower() in {"cyclist", "non_motorized"} for vehicle in vehicles
        ),
        "pedestrian_count": sum(
            str(vehicle.get("type") or "").lower() == "pedestrian" for vehicle in vehicles
        ),
    }

    def overlap_count(items: list[dict]) -> int:
        if len(items) < 2:
            return 0
        overlap_limit = max(pair_limit, 512)
        if len(items) > overlap_limit:
            vulnerable = [
                item
                for item in items
                if str(item.get("type") or "").lower()
                in {"pedestrian", "cyclist", "non_motorized"}
            ]
            motorized = [
                item
                for item in items
                if str(item.get("type") or "").lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ]
            remaining = max(0, overlap_limit - len(vulnerable))
            stride = max(1, int(math.ceil(len(motorized) / max(1, remaining))))
            items = (vulnerable + motorized[::stride][:remaining])[:overlap_limit]
        values = np.asarray(
            [
                [
                    float(item.get("x", 0.0)),
                    float(item.get("y", 0.0)),
                    float(item.get("heading", 0.0)),
                    max(0.1, float(item.get("length", 3.8))),
                    max(0.1, float(item.get("width", 1.8))),
                ]
                for item in items
            ],
            dtype=np.float64,
        )
        # A rectangle can only overlap another rectangle when their
        # circumscribed circles overlap. This exact broad phase removes almost
        # every OBB pair on normal roads while preserving all true collisions.
        delta = values[:, None, :2] - values[None, :, :2]
        distance_sq = np.sum(delta * delta, axis=2)
        radius = 0.5 * np.hypot(values[:, 3], values[:, 4])
        candidates = np.transpose(
            np.nonzero(
                np.triu(
                    distance_sq <= (radius[:, None] + radius[None, :]) ** 2,
                    k=1,
                )
            )
        )
        return sum(
            oriented_boxes_overlap(
                values[int(first_index), :3],
                values[int(first_index), 3:5],
                values[int(second_index), :3],
                values[int(second_index), 3:5],
            )
            for first_index, second_index in candidates
        )

    n = len(traffic_vehicles)
    if n < 2:
        return {
            "avg_speed": avg_speed,
            "speeds": speeds,
            "avg_ttc": None,
            "min_ttc": None,
            "avg_headway": None,
            "ttc_samples": [],
            "headway_samples": [],
            "collision_count": overlap_count(vehicles),
            **actor_counts,
        }

    sample = traffic_vehicles
    if n > pair_limit:
        stride = max(1, int(math.ceil(n / pair_limit)))
        sample = traffic_vehicles[::stride][:pair_limit]

    values = np.asarray(
        [
            [
                float(vehicle.get("x", 0.0)),
                float(vehicle.get("y", 0.0)),
                float(vehicle.get("heading", 0.0)),
                float(vehicle.get("speed", 0.0)),
                max(0.1, float(vehicle.get("length", 3.8))),
                max(0.1, float(vehicle.get("width", 1.8))),
            ]
            for vehicle in sample
        ],
        dtype=np.float64,
    )
    x, y, heading, speed, length, width = values.T
    dx = x[None, :] - x[:, None]
    dy = y[None, :] - y[:, None]
    cos_heading = np.cos(heading)[:, None]
    sin_heading = np.sin(heading)[:, None]
    longitudinal = dx * cos_heading + dy * sin_heading
    lateral = np.abs(-dx * sin_heading + dy * cos_heading)
    different_vehicle = ~np.eye(len(sample), dtype=bool)
    front_mask = (
        different_vehicle
        & (longitudinal > 0.0)
        & (lateral <= np.maximum(2.5, (width[:, None] + width[None, :]) * 0.75))
    )
    gaps = np.maximum(0.0, longitudinal - (length[:, None] + length[None, :]) * 0.5)

    headway_values = np.min(np.where(front_mask, gaps, np.inf), axis=1)
    headway_samples = [round(float(value), 3) for value in headway_values if np.isfinite(value)]

    closing_speed = speed[:, None] - speed[None, :]
    ttc_mask = front_mask & (closing_speed > 0.1)
    ttc_values = np.min(
        np.where(ttc_mask, gaps / np.maximum(closing_speed, 1e-12), np.inf),
        axis=1,
    )
    ttc_samples = [round(float(value), 3) for value in ttc_values if np.isfinite(value)]

    avg_headway = (sum(headway_samples) / len(headway_samples)) if headway_samples else None
    avg_ttc = (sum(ttc_samples) / len(ttc_samples)) if ttc_samples else None
    min_ttc = min(ttc_samples) if ttc_samples else None
    return {
        "avg_speed": avg_speed,
        "speeds": speeds,
        "avg_ttc": avg_ttc,
        "min_ttc": min_ttc,
        "avg_headway": avg_headway,
        "ttc_samples": ttc_samples,
        "headway_samples": headway_samples,
        "collision_count": overlap_count(vehicles),
        **actor_counts,
    }


def _av_safety_metrics(vehicles: list[dict]) -> dict[str, Any]:
    av = next(
        (
            vehicle
            for vehicle in vehicles
            if bool(vehicle.get("is_av")) or str(vehicle.get("type") or "").lower() == "av"
        ),
        None,
    )
    empty = {
        "av_avg_ttc": None,
        "av_min_ttc": None,
        "av_avg_headway": None,
        "av_ttc_samples": [],
        "av_headway_samples": [],
        "av_collision_count": None,
    }
    if av is None:
        return empty

    av_id = str(av.get("id"))
    av_x, av_y = float(av.get("x", 0.0)), float(av.get("y", 0.0))
    av_heading = float(av.get("heading", 0.0))
    av_speed = float(av.get("speed", 0.0))
    av_length = max(0.1, float(av.get("length", 3.8)))
    av_width = max(0.1, float(av.get("width", 1.8)))
    cos_heading, sin_heading = math.cos(av_heading), math.sin(av_heading)
    ttc_samples: list[float] = []
    headway_samples: list[float] = []
    collisions = 0
    for actor in vehicles:
        if str(actor.get("id")) == av_id:
            continue
        actor_x, actor_y = float(actor.get("x", 0.0)), float(actor.get("y", 0.0))
        actor_heading = float(actor.get("heading", 0.0))
        actor_speed = float(actor.get("speed", 0.0))
        actor_length = max(0.1, float(actor.get("length", 3.8)))
        actor_width = max(0.1, float(actor.get("width", 1.8)))
        if oriented_boxes_overlap(
            (av_x, av_y, av_heading),
            (av_length, av_width),
            (actor_x, actor_y, actor_heading),
            (actor_length, actor_width),
        ):
            collisions += 1
        dx, dy = actor_x - av_x, actor_y - av_y
        longitudinal = dx * cos_heading + dy * sin_heading
        lateral = abs(-dx * sin_heading + dy * cos_heading)
        if longitudinal <= 0.0 or lateral > max(2.5, 0.75 * (av_width + actor_width)):
            continue
        gap = max(0.0, longitudinal - 0.5 * (av_length + actor_length))
        headway_samples.append(round(gap, 3))
        closing_speed = av_speed - actor_speed
        if closing_speed > 0.1:
            ttc_samples.append(round(gap / closing_speed, 3))
    return {
        "av_avg_ttc": sum(ttc_samples) / len(ttc_samples) if ttc_samples else None,
        "av_min_ttc": min(ttc_samples) if ttc_samples else None,
        "av_avg_headway": sum(headway_samples) / len(headway_samples) if headway_samples else None,
        "av_ttc_samples": ttc_samples,
        "av_headway_samples": headway_samples,
        "av_collision_count": collisions,
    }


def _vehicle_dicts_from_record(agent_record, step: int | None = None) -> list[dict]:
    try:
        key = -1 if step is None else int(step)
        ids, states, mask = agent_record[key]
    except Exception:
        return []
    if not isinstance(ids, list):
        ids = [ids]
    ids_arr = np.array(ids, dtype=object)
    mask_arr = np.array(mask).reshape(-1).astype(bool)
    if ids_arr.size == 0 or mask_arr.size == 0 or not np.any(mask_arr):
        return []
    states_arr = np.array(states)[mask_arr]
    ids_valid = ids_arr[mask_arr]
    vehicles = []
    for vid, state in zip(ids_valid.tolist(), states_arr):
        row = np.array(state, dtype=float).reshape(-1)
        x = _safe_float(row[0] if row.size > 0 else 0.0)
        y = _safe_float(row[1] if row.size > 1 else 0.0)
        heading = _safe_float(row[2] if row.size > 2 else 0.0)
        heading = (heading + math.pi) % (2.0 * math.pi) - math.pi
        vx = _safe_float(row[3] if row.size > 3 else 0.0)
        vy = _safe_float(row[4] if row.size > 4 else 0.0)
        length = _safe_float(row[-3] if row.size >= 3 else 3.8, 3.8)
        width = _safe_float(row[-2] if row.size >= 2 else 1.8, 1.8)
        height = _safe_float(row[-1] if row.size >= 1 else 1.5, 1.5)
        agent = getattr(agent_record, "_id_agent_mapping", {}).get(vid)
        actor_type = str(getattr(agent, "actor_type", "vehicle"))
        vehicles.append(
            {
                "id": str(vid),
                "type": actor_type,
                "road_user_type": actor_type,
                "vehicle_class": str(getattr(agent, "vehicle_class", "vehicle")),
                "x": x,
                "y": y,
                "heading": heading,
                "vx": vx,
                "vy": vy,
                "ax": _safe_float(row[5] if row.size > 5 else 0.0),
                "ay": _safe_float(row[6] if row.size > 6 else 0.0),
                "speed": math.hypot(vx, vy),
                "length": max(0.1, length),
                "width": max(0.1, width),
                "height": max(0.1, height),
                "model_controlled": True,
                "static": False,
                "past": [],
                "future": [],
            }
        )
    return vehicles


def _actor_dicts_from_simulator(sim, step: int | None = None) -> list[dict]:
    actors = _vehicle_dicts_from_record(sim.agent_record, step=step)
    if step is None and hasattr(sim, "get_pedestrian_actors"):
        actors.extend(sim.get_pedestrian_actors())
    return actors


WORLD_CONTEXT_MODES = {
    "auto",
    "vehicles",
    "crosswalk_pedestrian",
    "cyclist",
}


def _actor_context_kind(actor: dict[str, Any]) -> str:
    actor_type = str(
        actor.get("road_user_type") or actor.get("type") or "vehicle"
    ).lower()
    if actor_type == "pedestrian":
        return "pedestrian"
    if actor_type in {"cyclist", "non_motorized", "bicycle", "bike"}:
        return "cyclist"
    return "motorized"


def _world_context_features(
    position: np.ndarray | list[float] | tuple[float, float],
    actors: list[dict[str, Any]],
    crosswalk_centers: np.ndarray | list[list[float]],
    *,
    exclude_id: Any = None,
    radius_m: float = 80.0,
) -> dict[str, float | int]:
    """Summarize observable road users and crosswalk proximity around an ego candidate."""
    center = np.asarray(position, dtype=float).reshape(-1)[:2]
    counts = {"motorized": 0, "pedestrian": 0, "cyclist": 0}
    nearest = {"pedestrian": math.inf, "cyclist": math.inf}
    excluded = None if exclude_id is None else str(exclude_id)
    for actor in actors:
        if excluded is not None and str(actor.get("id")) == excluded:
            continue
        actor_position = np.asarray(
            [float(actor.get("x", 0.0)), float(actor.get("y", 0.0))],
            dtype=float,
        )
        distance = float(np.linalg.norm(actor_position - center))
        kind = _actor_context_kind(actor)
        if distance <= radius_m:
            counts[kind] += 1
        if kind in nearest:
            nearest[kind] = min(nearest[kind], distance)

    crosswalk_array = np.asarray(crosswalk_centers, dtype=float)
    if crosswalk_array.ndim == 2 and len(crosswalk_array) and crosswalk_array.shape[1] >= 2:
        nearest_crosswalk = float(
            np.min(np.linalg.norm(crosswalk_array[:, :2] - center, axis=1))
        )
    else:
        nearest_crosswalk = math.inf
    return {
        "motorized_count_80m": counts["motorized"],
        "pedestrian_count_80m": counts["pedestrian"],
        "cyclist_count_80m": counts["cyclist"],
        "nearest_pedestrian_m": nearest["pedestrian"],
        "nearest_cyclist_m": nearest["cyclist"],
        "nearest_crosswalk_m": nearest_crosswalk,
    }


def _world_context_score(mode: str, features: dict[str, float | int]) -> float:
    """Score a candidate without overriding the mandatory loop-route constraint."""
    mode = str(mode or "auto").strip().lower()
    if mode not in WORLD_CONTEXT_MODES:
        raise ValueError(f"Unsupported DenseWorld context mode: {mode}")
    if mode == "auto":
        return 0.0

    motorized = float(features.get("motorized_count_80m", 0) or 0)
    pedestrians = float(features.get("pedestrian_count_80m", 0) or 0)
    cyclists = float(features.get("cyclist_count_80m", 0) or 0)
    crosswalk_distance = min(
        100.0,
        float(features.get("nearest_crosswalk_m", math.inf) or math.inf),
    )
    pedestrian_distance = min(
        80.0,
        float(features.get("nearest_pedestrian_m", math.inf) or math.inf),
    )
    cyclist_distance = min(
        80.0,
        float(features.get("nearest_cyclist_m", math.inf) or math.inf),
    )
    if mode == "vehicles":
        return (
            motorized * 1200.0
            - pedestrians * 600.0
            - cyclists * 800.0
            + crosswalk_distance * 20.0
        )
    if mode == "crosswalk_pedestrian":
        return (
            pedestrians * 6000.0
            + (100.0 - crosswalk_distance) * 300.0
            + (80.0 - pedestrian_distance) * 300.0
        )
    return (
        cyclists * 10000.0
        + (80.0 - cyclist_distance) * 350.0
        + motorized * 100.0
    )


def _world_loop_compactness_penalty(extent_m: float, lane_count: int) -> float:
    """Reject city-scale loops while treating all local loops as equivalent."""
    return (
        max(0.0, min(float(extent_m), 5000.0) - 450.0) * 200.0
        + max(0, min(int(lane_count), 1000) - 64) * 100.0
    )


def _finite_context_features(features: dict[str, float | int]) -> dict[str, float | int | None]:
    result: dict[str, float | int | None] = {}
    for key, value in features.items():
        if isinstance(value, float):
            result[key] = round(value, 3) if math.isfinite(value) else None
        else:
            result[key] = value
    return result


def _traffic_lights_from_map(map_obj) -> dict[str, int]:
    try:
        tl_ids, tl_states, tl_mask = map_obj[-1, :, :4]
    except Exception:
        return {}
    if not isinstance(tl_ids, list):
        tl_ids = [tl_ids]
    tl_ids_arr = np.array(tl_ids, dtype=object)
    mask = np.array(tl_mask).reshape(-1).astype(bool)
    if tl_ids_arr.size == 0 or mask.size == 0 or not np.any(mask):
        return {}
    states = np.array(tl_states)[mask]
    if states.ndim == 1:
        states = states.reshape(1, -1)
    out = {}
    for tid, state in zip(tl_ids_arr[mask].tolist(), states):
        if len(state) >= 4:
            out[str(tid)] = int(np.argmax(state[:4]))
    return out


def _matching_mapping_key(mapping: dict, raw_id: Any) -> Any | None:
    if raw_id in mapping:
        return raw_id
    raw_text = str(raw_id)
    return next((key for key in mapping if str(key) == raw_text), None)


def _nearest_route_lane(
    map_obj,
    route_ids: list[Any],
    position: np.ndarray,
) -> tuple[Any | None, float]:
    """Return the planned route lane closest to an actor's ground position."""
    polylines = getattr(map_obj, "polyline_dict", {}) or {}
    point = np.asarray(position, dtype=np.float64).reshape(-1)[:2]
    best_lane = None
    best_distance = math.inf
    for route_id in route_ids:
        lane_key = _matching_mapping_key(polylines, route_id)
        lane = polylines.get(lane_key) if lane_key is not None else None
        points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
        if points.ndim != 2 or len(points) < 2:
            continue
        starts = points[:-1, :2]
        segments = points[1:, :2] - starts
        lengths_squared = np.sum(segments * segments, axis=1)
        valid = lengths_squared > 1e-9
        if not np.any(valid):
            continue
        starts = starts[valid]
        segments = segments[valid]
        lengths_squared = lengths_squared[valid]
        projections = np.clip(
            np.sum((point - starts) * segments, axis=1) / lengths_squared,
            0.0,
            1.0,
        )
        closest = starts + projections[:, None] * segments
        distance = float(np.min(np.linalg.norm(closest - point, axis=1)))
        if distance < best_distance:
            best_lane = route_id
            best_distance = distance
    return best_lane, best_distance


def _nearest_route_projection(
    map_obj,
    route_ids: list[Any],
    position: np.ndarray,
    heading: float,
) -> tuple[Any | None, np.ndarray | None, float, float]:
    """Project a state onto a directed route while preserving its travel direction."""
    polylines = getattr(map_obj, "polyline_dict", {}) or {}
    point = np.asarray(position, dtype=np.float64).reshape(-1)[:2]
    best_lane = None
    best_point = None
    best_heading = float(heading)
    best_distance = math.inf
    best_score = math.inf
    for route_id in route_ids:
        lane_key = _matching_mapping_key(polylines, route_id)
        lane = polylines.get(lane_key) if lane_key is not None else None
        points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
        if points.ndim != 2 or len(points) < 2:
            continue
        for start, end in zip(points[:-1, :2], points[1:, :2]):
            segment = end - start
            length_squared = float(np.dot(segment, segment))
            if length_squared <= 1e-9:
                continue
            ratio = float(np.clip(np.dot(point - start, segment) / length_squared, 0.0, 1.0))
            projected = start + ratio * segment
            distance = float(np.linalg.norm(projected - point))
            segment_heading = math.atan2(float(segment[1]), float(segment[0]))
            heading_delta = (segment_heading - heading + math.pi) % (2.0 * math.pi) - math.pi
            if abs(heading_delta) > math.pi / 2.0:
                segment_heading = (segment_heading + math.pi) % (2.0 * math.pi)
                heading_delta = (segment_heading - heading + math.pi) % (2.0 * math.pi) - math.pi
            score = distance + 0.75 * abs(heading_delta)
            if score < best_score:
                best_lane = route_id
                best_point = projected
                best_heading = (segment_heading + math.pi) % (2.0 * math.pi) - math.pi
                best_distance = distance
                best_score = score
    return best_lane, best_point, best_heading, best_distance


def _route_centerline_geometry(
    map_obj,
    route_ids: list[Any],
) -> tuple[np.ndarray, np.ndarray, list[tuple[str, float]]]:
    """Build one directed centerline and lane-start offsets for a route window."""
    polylines = getattr(map_obj, "polyline_dict", {}) or {}
    route_points: list[np.ndarray] = []
    lane_start_indices: list[tuple[str, int]] = []
    for route_id in route_ids:
        lane_key = _matching_mapping_key(polylines, route_id)
        lane = polylines.get(lane_key) if lane_key is not None else None
        points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
        if points.ndim != 2 or len(points) < 2:
            continue
        values = points[:, :2]
        shares_previous_endpoint = bool(
            route_points and np.linalg.norm(route_points[-1] - values[0]) <= 1e-6
        )
        lane_start_index = len(route_points) - 1 if shares_previous_endpoint else len(route_points)
        if shares_previous_endpoint:
            values = values[1:]
        if len(values) == 0:
            continue
        lane_start_indices.append((str(route_id), lane_start_index))
        route_points.extend(values)
    if len(route_points) < 2:
        return np.empty((0, 2), dtype=np.float64), np.empty(0), []
    point_array = np.asarray(route_points, dtype=np.float64)
    cumulative = np.concatenate(
        ([0.0], np.cumsum(np.linalg.norm(np.diff(point_array, axis=0), axis=1)))
    )
    lane_starts = [
        (lane_id, float(cumulative[min(index, len(cumulative) - 1)]))
        for lane_id, index in lane_start_indices
    ]
    return point_array, cumulative, lane_starts


def _polyline_progress(
    points: np.ndarray,
    cumulative: np.ndarray,
    position: np.ndarray,
) -> tuple[float, float]:
    if len(points) < 2 or len(cumulative) != len(points):
        return 0.0, math.inf
    starts = points[:-1]
    segments = points[1:] - starts
    length_squared = np.sum(segments * segments, axis=1)
    valid_length = np.maximum(length_squared, 1e-9)
    ratios = np.clip(
        np.sum((np.asarray(position, dtype=np.float64)[:2] - starts) * segments, axis=1)
        / valid_length,
        0.0,
        1.0,
    )
    projections = starts + ratios[:, None] * segments
    distances = np.linalg.norm(projections - np.asarray(position, dtype=np.float64)[:2], axis=1)
    index = int(np.argmin(distances))
    segment_length = math.sqrt(float(length_squared[index]))
    return (
        float(cumulative[index] + ratios[index] * segment_length),
        float(distances[index]),
    )


def _sample_route_centerline(
    points: np.ndarray,
    cumulative: np.ndarray,
    progress: float,
) -> tuple[np.ndarray, float]:
    progress = float(np.clip(progress, 0.0, float(cumulative[-1])))
    index = max(
        0,
        min(len(points) - 2, int(np.searchsorted(cumulative, progress, side="right") - 1)),
    )
    segment = points[index + 1] - points[index]
    length = max(1e-9, float(cumulative[index + 1] - cumulative[index]))
    ratio = (progress - float(cumulative[index])) / length
    point = points[index] + ratio * segment
    heading = math.atan2(float(segment[1]), float(segment[0]))
    return point, heading


def _route_visibility_report(map_obj, agent_record, vehicle: dict) -> dict[str, float | int | bool]:
    """Measure how much of an actor's planned route remains in the front camera."""
    actor_id = vehicle.get("id")
    agent_mapping = getattr(agent_record, "_id_agent_mapping", {}) or {}
    actor_key = _matching_mapping_key(agent_mapping, actor_id)
    agent = agent_mapping.get(actor_key) if actor_key is not None else None
    route_ids = list(getattr(agent, "route", []) or [])
    position = np.asarray(
        [float(vehicle.get("x", 0.0)), float(vehicle.get("y", 0.0))],
        dtype=np.float64,
    )
    heading = float(vehicle.get("heading", 0.0) or 0.0)

    try:
        current_id = map_obj.get_current_lane(position, heading)
        if isinstance(current_id, tuple):
            current_id = current_id[0]
    except Exception:
        current_id = None

    polylines = getattr(map_obj, "polyline_dict", {}) or {}
    current_key = _matching_mapping_key(polylines, current_id) if current_id is not None else None
    route_keys = []
    for route_id in route_ids:
        key = _matching_mapping_key(polylines, route_id)
        if key is not None:
            route_keys.append(key)
    if current_key is not None:
        matching_index = next(
            (index for index, key in enumerate(route_keys) if str(key) == str(current_key)),
            None,
        )
        route_keys = route_keys[matching_index:] if matching_index is not None else [current_key, *route_keys]

    route_points: list[np.ndarray] = []
    for lane_id in route_keys[:16]:
        points = np.asarray(getattr(polylines.get(lane_id), "points", []), dtype=np.float64)
        if points.ndim != 2 or len(points) < 2:
            continue
        lane_points = points[:, :2]
        if route_points:
            previous = route_points[-1]
            if float(np.linalg.norm(lane_points[-1] - previous)) < float(
                np.linalg.norm(lane_points[0] - previous)
            ):
                lane_points = lane_points[::-1]
        for point in lane_points:
            if not route_points or float(np.linalg.norm(point - route_points[-1])) > 1e-3:
                route_points.append(point)

    if len(route_points) < 2:
        return {
            "valid": False,
            "route_lane_count": len(route_keys),
            "remaining_route_m": 0.0,
            "front_visible_route_m": 0.0,
            "max_heading_change_deg": 180.0,
        }

    points = np.asarray(route_points, dtype=np.float64)
    segment_vectors = np.diff(points, axis=0)
    segment_length_sq = np.sum(segment_vectors * segment_vectors, axis=1)
    valid_segments = segment_length_sq > 1e-8
    if not np.any(valid_segments):
        return {
            "valid": False,
            "route_lane_count": len(route_keys),
            "remaining_route_m": 0.0,
            "front_visible_route_m": 0.0,
            "max_heading_change_deg": 180.0,
        }

    ratios = np.clip(
        np.sum((position - points[:-1]) * segment_vectors, axis=1)
        / np.maximum(segment_length_sq, 1e-8),
        0.0,
        1.0,
    )
    projections = points[:-1] + ratios[:, None] * segment_vectors
    distances = np.linalg.norm(projections - position, axis=1)
    distances[~valid_segments] = np.inf
    start_index = int(np.argmin(distances))
    remaining_vectors = segment_vectors[start_index:].copy()
    remaining_vectors[0] = points[start_index + 1] - projections[start_index]
    remaining_lengths = np.linalg.norm(remaining_vectors, axis=1)
    remaining_vectors = remaining_vectors[remaining_lengths > 1e-4]
    remaining_lengths = remaining_lengths[remaining_lengths > 1e-4]
    if not len(remaining_lengths):
        return {
            "valid": False,
            "route_lane_count": len(route_keys),
            "remaining_route_m": 0.0,
            "front_visible_route_m": 0.0,
            "max_heading_change_deg": 180.0,
        }

    segment_headings = np.arctan2(remaining_vectors[:, 1], remaining_vectors[:, 0])
    heading_changes = np.abs(
        (segment_headings - heading + math.pi) % (2.0 * math.pi) - math.pi
    )
    cumulative = np.cumsum(remaining_lengths)
    sharp_turn = np.flatnonzero(heading_changes > math.radians(35.0))
    front_visible = (
        float(cumulative[int(sharp_turn[0]) - 1])
        if len(sharp_turn) and int(sharp_turn[0]) > 0
        else (0.0 if len(sharp_turn) else float(cumulative[-1]))
    )
    return {
        "valid": True,
        "route_lane_count": len(route_keys),
        "remaining_route_m": round(float(cumulative[-1]), 3),
        "front_visible_route_m": round(front_visible, 3),
        "max_heading_change_deg": round(float(np.degrees(np.max(heading_changes))), 3),
    }


def _simplify_display_polyline(points: np.ndarray, tolerance: float = 0.08) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)[:, :2]
    if len(values) <= 2:
        return values
    retained = np.zeros(len(values), dtype=bool)
    retained[[0, -1]] = True
    pending = [(0, len(values) - 1)]
    while pending:
        start, end = pending.pop()
        if end <= start + 1:
            continue
        segment = values[end] - values[start]
        length = float(np.linalg.norm(segment))
        middle = values[start + 1 : end]
        if length <= 1e-9:
            distances = np.linalg.norm(middle - values[start], axis=1)
        else:
            relative = middle - values[start]
            distances = np.abs(segment[0] * relative[:, 1] - segment[1] * relative[:, 0]) / length
        local_index = int(np.argmax(distances))
        if float(distances[local_index]) <= tolerance:
            continue
        index = start + 1 + local_index
        retained[index] = True
        pending.extend(((start, index), (index, end)))
    return values[retained]


def build_map_state(map_obj, map_path: str = "") -> dict:
    polylines = []
    start_lanes = []
    source_point_count = 0
    display_point_count = 0
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for polyline_id, polyline in getattr(map_obj, "polyline_dict", {}).items():
        points_raw = getattr(polyline, "points", None)
        if points_raw is None:
            continue
        points_arr = np.array(points_raw, dtype=float)
        if points_arr.ndim != 2 or points_arr.shape[0] < 2:
            continue
        points = points_arr[:, :2]
        source_point_count += len(points)
        min_x = min(min_x, float(np.min(points[:, 0])))
        min_y = min(min_y, float(np.min(points[:, 1])))
        max_x = max(max_x, float(np.max(points[:, 0])))
        max_y = max(max_y, float(np.max(points[:, 1])))
        p_type = int(getattr(polyline, "type", 0) or 0)
        display_points = _simplify_display_polyline(points)
        display_point_count += len(display_points)
        polylines.append(
            {
                "id": str(polyline_id),
                "raw_id": polyline_id,
                "type": p_type,
                "points": [[round(float(x), 3), round(float(y), 3)] for x, y in display_points.tolist()],
            }
        )
    for lane_id in getattr(map_obj, "start_lane", []) or []:
        start_lanes.append(str(lane_id))
    if not math.isfinite(min_x) or not math.isfinite(max_x) or min_x == max_x or min_y == max_y:
        min_x, min_y, max_x, max_y = -100.0, -100.0, 100.0, 100.0
    result = {
        "backend_model": "cnde",
        "map_path": map_path,
        "bounds": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
        "polylines": polylines,
        "start_lanes": start_lanes,
        "display_simplification": {
            "algorithm": "ramer-douglas-peucker",
            "tolerance_m": 0.08,
            "source_point_count": source_point_count,
            "display_point_count": display_point_count,
        },
    }
    signalization_report = getattr(map_obj, "trafficwm_signalization_report", None)
    if isinstance(signalization_report, dict):
        result["signalization"] = dict(signalization_report)
    result.update(build_citynde_semantics(map_obj))
    return result


def load_or_build_map_state(map_obj, map_path: Path, display_path: str) -> dict:
    cache_path = _map_state_cache_path(map_path)
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("cache_version") == MAP_STATE_CACHE_VERSION
            and Path(str(cached.get("map_path") or "")).resolve() == map_path.resolve()
            and isinstance(cached.get("map_state"), dict)
        ):
            return dict(cached["map_state"])
    except (OSError, TypeError, ValueError):
        pass

    map_state = build_map_state(map_obj, display_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "cache_version": MAP_STATE_CACHE_VERSION,
                "map_path": str(map_path.resolve()),
                "map_state": map_state,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(cache_path)
    return map_state


class CityNDEGenerationAdapter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.traffic_controller = str(
            getattr(args, "traffic_controller", "citynde") or "citynde"
        ).strip().lower()
        self.backend_model = (
            "rulebased" if self.traffic_controller == "idm_mobil" else "cnde"
        )
        self.rule_desired_speed_mps = max(
            1.0,
            min(35.0, float(getattr(args, "rule_desired_speed_mps", 10.0) or 10.0)),
        )
        self.citynde_root = Path(args.citynde_root).resolve()
        self.map_path = _resolve_citynde_path(args.map_path, self.citynde_root)
        self.save_file = _resolve_citynde_path(args.save_file, self.citynde_root)
        self.run_until_stopped = bool(getattr(args, "run_until_stopped", False))
        self.total_step = 0 if self.run_until_stopped else max(1, int(args.total_step or 1))
        self.step_seconds = float(args.sim_resolution or 0.1)
        self.max_sim_time = (
            0.0
            if self.run_until_stopped
            else float(args.max_sim_time or self.total_step * self.step_seconds)
        )
        self.experiment_name = args.experiment_name or self.save_file.stem
        self.metrics = _empty_metrics(self.total_step, self.step_seconds)
        self.stop_requested = False
        self.run_stop_requested = False
        self.completed = False
        self.paused = False
        self.last_error_nonce = 0
        self.profiler = CityNDEProfiler(args, self.citynde_root)
        self._last_vehicles: list[dict] = []
        self._last_traffic_metrics: dict[str, Any] | None = None
        self._last_published_step = -1
        self.av_enabled = bool(args.av_enabled)
        self.av_control_model = str(args.av_control_model or "DEFAULT_TCP").upper()
        self.av_selection_mode = str(args.av_selection_mode or "random").lower()
        self.av_command_mode = str(args.av_command_mode or "state").lower()
        self.av_control_timeout = max(0.05, float(args.av_control_timeout or 1.0))
        self.av_rgb_uri = str(args.av_rgb_uri or "").strip()
        self.world_seed_frame = ""
        self.world_seed_alignment_mode = SEED_ALIGNMENT_TERMINAL_CONTINUE
        self.world_seed_alignment_prepared = False
        self._world_opening_snapshot: dict[str, Any] | None = None
        self._world_opening_rng_state: dict[str, Any] = {}
        self._world_opening_routes: dict[str, list[Any]] = {}
        self.av_id = None
        self.waiting_for_av_selection = False
        self.termination_reason = ""
        self.existing_seed_gate = bool(
            args.denseworld_warmup and getattr(args, "denseworld_existing_seed", False)
        )
        self.world_seed_ego_id = str(getattr(args, "world_seed_ego_id", "") or "").strip()
        self.world_ego_speed_cap_mps = max(
            0.0,
            min(35.0, float(getattr(args, "world_ego_speed_cap_mps", 0.0) or 0.0)),
        )
        self.warmup_steps = (
            0
            if self.existing_seed_gate
            else
            max(1, int(round(float(args.warmup_seconds or 1.0) / self.step_seconds)))
            if bool(args.denseworld_warmup)
            else 0
        )
        self.world_seed_pending = False
        self.world_sync_state = (
            Path(args.world_sync_state).resolve()
            if str(args.world_sync_state or "").strip()
            else None
        )
        self.world_sync_waiting = False
        self.world_ego_id = None
        self.world_region_center: tuple[float, float] | None = None
        self.world_region_radius = 220.0
        self.world_local_target_count = 28
        self.world_requested_local_target_count = max(
            0,
            min(48, int(getattr(args, "world_local_target_count", 0) or 0)),
        )
        self.world_initial_vehicle_limit = max(
            0,
            min(128, int(getattr(args, "world_initial_vehicle_limit", 0) or 0)),
        )
        self.world_spawn_visibility_guard_m = max(
            0.0,
            min(
                180.0,
                float(getattr(args, "world_spawn_visibility_guard_m", 100.0) or 0.0),
            ),
        )
        self.world_last_flow_update_step = -1
        self.world_initial_flow_prepared = False
        self.world_appearance_anchors = (
            load_appearance_anchors(self.map_path, args.world_anchor_catalog)
            if self.warmup_steps and str(args.world_anchor_catalog or "").strip()
            else []
        )
        self.world_appearance_anchor: dict[str, Any] = {}
        self.world_pruned_exhausted_agents = 0
        self.world_pruned_route_end_agents = 0
        self.world_pruned_outside_agents = 0
        self.world_local_replaced_agents = 0
        self.av_fallback_extrapolation_count = 0
        self.world_loop_ego = bool(args.world_loop_ego)
        self.world_context_mode = str(args.world_context_mode or "auto").strip().lower()
        if self.world_context_mode not in WORLD_CONTEXT_MODES:
            raise ValueError(f"Unsupported DenseWorld context mode: {self.world_context_mode}")
        self.world_loop_route_prefix: list[Any] = []
        self.world_loop_route_cycle: list[Any] = []
        self.world_loop_route_pins = 0
        self.world_loop_corridor_corrections = 0
        self.world_loop_projection_rollouts = 0
        self.world_loop_projected_states = 0
        self.world_loop_projection_max_m = 0.0
        self.world_loop_fallback_count = 0
        self.world_loop_anomaly_protections = 0
        self.world_loop_recovery_rollouts = 0
        self.world_loop_recovery_blocked_rollouts = 0
        self.world_loop_recovery_distance_m = 0.0
        self.world_loop_route_extent_m = 0.0
        self.warmup_save_file = self.save_file.with_suffix(".warmup.pkl")
        self.warmup_frames_file = self.save_file.with_suffix(".warmup.json")
        self._warmup_frames: list[dict[str, Any]] = []
        self.av_command_timeout_count = 0
        self.av_perception_frame_count = 0
        self.av_command_frame_count = 0
        self.av_command_latencies_ms: list[float] = []
        self.av_first_command_frame: int | None = None
        self.av_last_command_frame: int | None = None
        self.av_start_state: dict[str, Any] = {}
        self.av_end_state: dict[str, Any] = {}
        self.av_last_diagnostics: dict[str, Any] = {}
        self.av_collision_details: dict[str, Any] = {}
        self._last_remote_command_time = 0.0
        self.av_bridge = None
        if self.av_enabled and self.av_control_model in {"EXTERNAL_TCP", "VTD_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM"}:
            av_port = int(args.av_control_port or (int(args.port) + 1000))
            self.av_bridge = AVTCPBridge(args.av_control_host, av_port)
            self.av_bridge.start()

        from backend.algorithms.citynde.mixed_traffic import (
            MixedTrafficInteractiveSimulator,
        )
        from backend.algorithms.citynde.mixed_traffic_core import SignalTimingPlan
        from cutils import setup_seed

        setup_seed(int(args.seed))
        signal_plan = SignalTimingPlan(self.step_seconds)
        if self.traffic_controller == "idm_mobil":
            from backend.algorithms.rulebased.idm_mobil_controller import (
                IDMParameters,
                SparseIDMMOBILController,
            )

            controller = SparseIDMMOBILController(
                control_step=max(1, min(20, int(args.control_step or 5))),
                control_resolution=self.step_seconds,
                signal_plan=signal_plan,
                idm=IDMParameters(desired_speed=self.rule_desired_speed_mps),
            )
        else:
            from cnde.config import cfg as origin_cfg, cfg_from_yaml_file
            from cnde.ops.knn import knn_utils
            from backend.algorithms.citynde.memory_bounded_knn import knn_batch_chunked
            from cnde.models.model import MotionTransformer
            from backend.algorithms.citynde.mixed_traffic import (
                MixedTrafficRuleEnhancedController,
            )
            from backend.algorithms.citynde.trajectory_clustering import (
                cluster_trajectories_cpu,
            )
            from csim.controller import rule_controller as citynde_rule_controller
            import torch

            knn_utils.knn_batch = knn_batch_chunked
            knn_utils.knn_batch_mlogk = knn_batch_chunked
            citynde_rule_controller.cluster_trajectories = cluster_trajectories_cpu
            cfg = cfg_from_yaml_file(
                str(_resolve_citynde_path(args.cfg_file, self.citynde_root)), origin_cfg
            )
            model = MotionTransformer(config=cfg.MODEL)
            ckpt_path = _resolve_citynde_path(args.ckpt_file, self.citynde_root)
            try:
                checkpoint = torch.load(
                    str(ckpt_path), map_location="cpu", weights_only=True
                )
            except TypeError:
                checkpoint = torch.load(str(ckpt_path), map_location="cpu")
            model.load_state_dict(checkpoint["model_state"], strict=True)
            model.eval().requires_grad_(False)
            controller = MixedTrafficRuleEnhancedController(
                core=model,
                control_step=max(1, min(20, int(args.control_step or 5))),
                control_resolution=self.step_seconds,
                signal_plan=signal_plan,
                inference_batch_size=32 if bool(args.denseworld_warmup) else 128,
                inference_precision=str(args.inference_precision or "fp32"),
            )
        self.controller = controller

        self.sim = MixedTrafficInteractiveSimulator(
            map_path=str(self.map_path),
            sim_resolution=self.step_seconds,
            history_step=11,
            agent_controller=controller,
            visualize=False,
            default_spawn_speed=float(args.default_spawn_speed or 2.0),
            mixed_traffic_enabled=bool(args.mixed_traffic_enabled),
            cyclist_ratio=float(args.cyclist_ratio),
            pedestrians_per_crosswalk=int(args.pedestrians_per_crosswalk),
            max_pedestrians=int(args.max_pedestrians),
            vehicle_size_mode=str(args.vehicle_size_mode),
            initial_speed_mode=str(args.initial_speed_mode),
            mixed_traffic_seed=int(args.seed),
            signalize_unsignalized_map=bool(args.signalize_unsignalized_map),
            preserve_loaded_state=self.existing_seed_gate,
        )
        if self.backend_model == "rulebased":
            self.sim.map.set_device("cpu")
        display_map_path = _display_path(self.map_path, self.citynde_root)
        map_state = load_or_build_map_state(
            self.sim.map, self.map_path, display_map_path
        )
        world_semantics = map_state
        crosswalk_centers = []
        for crosswalk in world_semantics.get("crosswalks") or []:
            polygon = np.asarray(crosswalk.get("polygon") or [], dtype=float)
            if polygon.ndim == 2 and len(polygon) and polygon.shape[1] >= 2:
                crosswalk_centers.append(np.mean(polygon[:, :2], axis=0))
        self.world_crosswalk_centers = (
            np.asarray(crosswalk_centers, dtype=float)
            if crosswalk_centers
            else np.empty((0, 2), dtype=float)
        )
        controller.map_enhance = self.sim.map
        controller.agent_enhance = self.sim.agent_record
        self.sim.web_viewer = None

        self.viewer = HttpApiViewer(
            mode="citynde",
            host=args.host,
            port=args.port,
            gui_dir=args.gui_dir,
            workspace_root=str(self.citynde_root),
        )
        self.viewer.set_maps(self._list_maps())
        self.viewer.set_scenarios(self._list_scenarios())
        map_state["backend_model"] = self.backend_model
        self.viewer.set_map_state(map_state)
        self.viewer.set_replay_metrics(self.metrics)
        self.viewer.set_status_fields(
            {
                "mode": "citynde",
                "backend_model": self.backend_model,
                "traffic_controller": self.traffic_controller,
                "rule_desired_speed_mps": self.rule_desired_speed_mps,
                "algorithm_source": _display_path(self.citynde_root, self.citynde_root.parent),
                "run_state": "running",
                "paused": False,
                "experiment_id": args.experiment_id or self.save_file.stem,
                "experiment_name": self.experiment_name,
                "map_path": _display_path(self.map_path, self.citynde_root),
                "save_file": _display_path(self.save_file, self.citynde_root),
                "init_mode": args.init_mode,
                "gpu_id": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
                "sim_resolution": self.step_seconds,
                "control_step": int(self.controller.control_step),
                "control_horizon_seconds": round(
                    int(self.controller.control_step) * self.step_seconds,
                    3,
                ),
                "inference_precision": str(self.controller.inference_precision),
                "total_step": self.total_step,
                "max_sim_time": self.max_sim_time,
                "run_until_stopped": self.run_until_stopped,
                "sim_time": 0.0,
                "progress": 0.0,
                "experiment_completed": False,
                "av_enabled": self.av_enabled,
                "av_id": "",
                "av_selection_mode": self.av_selection_mode,
                "av_control_model": self.av_control_model,
                "av_command_mode": self.av_command_mode,
                "av_control_endpoint": self.av_bridge.endpoint if self.av_bridge is not None else "",
                "av_connected": False,
                "av_perception_frame_count": 0,
                "av_command_frame_count": 0,
                "av_command_timeout_count": 0,
                "av_command_success_rate": 0.0,
                "av_command_latency_ms": None,
                "waiting_for_av_selection": False,
                "termination_reason": "",
                "denseworld_warmup": bool(args.denseworld_warmup),
                "denseworld_existing_seed": self.existing_seed_gate,
                "warmup_seconds": self.warmup_steps * self.step_seconds,
                "raw_sim_time": 0.0,
                "world_seed_pending": False,
                "world_appearance_anchor_count": len(self.world_appearance_anchors),
                "mixed_traffic_enabled": bool(args.mixed_traffic_enabled),
                "cyclist_ratio": float(args.cyclist_ratio),
                "pedestrians_per_crosswalk": int(args.pedestrians_per_crosswalk),
                "vehicle_size_mode": str(args.vehicle_size_mode),
                "initial_speed_mode": str(args.initial_speed_mode),
                "signal_cycle_seconds": signal_plan.as_dict()["cycle_seconds"],
                "signalization": dict(getattr(self.sim, "signalization_report", {}) or {}),
                "world_loop_ego": self.world_loop_ego,
                "world_ego_speed_cap_mps": self.world_ego_speed_cap_mps,
                "world_context_mode": self.world_context_mode,
            }
        )
        self._apply_arrival_config(args.arrival_rate, args.lane_arrival_rates)

    def _list_maps(self) -> list[str]:
        root = self.citynde_root / "assets" / "map"
        if not root.is_dir():
            return []
        return [str(p.relative_to(self.citynde_root)).replace("\\", "/") for p in sorted(root.rglob("*.pkl"))]

    def _list_scenarios(self) -> list[str]:
        root = self.citynde_root / "output"
        if not root.is_dir():
            return []
        return [str(p.relative_to(self.citynde_root)).replace("\\", "/") for p in sorted(root.rglob("*.pkl"))]

    def _set_error(self, message: str):
        self.last_error_nonce += 1
        self.viewer.set_status_fields({"last_error": str(message), "last_error_nonce": self.last_error_nonce})

    def _apply_arrival_config(self, arrival_rate, lane_rates_json: str = ""):
        lane_rates = {}
        if lane_rates_json:
            try:
                parsed = json.loads(lane_rates_json)
                if isinstance(parsed, dict):
                    lane_rates = parsed
            except json.JSONDecodeError:
                lane_rates = {}
        if arrival_rate is not None:
            prob = max(0.0, min(1.0, float(arrival_rate)))
            self.sim.default_arrival_rate = prob
            for lane_id in getattr(self.sim.map, "start_lane", []) or []:
                self.sim.lane_arrival_rates[lane_id] = prob
        for lane_id, prob in lane_rates.items():
            actual = next((x for x in self.sim.map.start_lane if str(x) == str(lane_id)), lane_id)
            self.sim.lane_arrival_rates[actual] = max(0.0, min(1.0, float(prob)))
        self.viewer.set_status_fields({"arrival_rate": self._arrival_rate()})

    def _arrival_rate(self) -> float:
        if getattr(self.sim, "lane_arrival_rates", None):
            return float(np.mean(list(self.sim.lane_arrival_rates.values())))
        return float(getattr(self.sim, "default_arrival_rate", 0.0))

    def _experiment_params(self) -> dict:
        lane_rates = {
            str(lane_id): float(rate)
            for lane_id, rate in (getattr(self.sim, "lane_arrival_rates", {}) or {}).items()
        }
        return {
            "backend_model": self.backend_model,
            "traffic_controller": self.traffic_controller,
            "rule_desired_speed_mps": self.rule_desired_speed_mps,
            "map_path": _display_path(self.map_path, self.citynde_root),
            "init_mode": self.args.init_mode,
            "init_file": self.args.init_file.strip(),
            "experiment_name": self.experiment_name,
            "gpu_id": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
            "total_step": self.total_step,
            "sim_resolution": self.step_seconds,
            "max_sim_time": self.max_sim_time,
            "run_until_stopped": self.run_until_stopped,
            "arrival_rate": self._arrival_rate(),
            "lane_arrival_rates": lane_rates,
            "av_enabled": self.av_enabled,
            "av_id": "" if self.av_id is None else str(self.av_id),
            "av_selection_mode": self.av_selection_mode,
            "av_control_model": self.av_control_model,
            "av_command_mode": self.av_command_mode,
            "av_control_endpoint": self.av_bridge.endpoint if self.av_bridge is not None else "",
            "termination_reason": self.termination_reason,
            "mixed_traffic_enabled": bool(self.args.mixed_traffic_enabled),
            "cyclist_ratio": float(self.args.cyclist_ratio),
            "pedestrians_per_crosswalk": int(self.args.pedestrians_per_crosswalk),
            "max_pedestrians": int(self.args.max_pedestrians),
            "vehicle_size_mode": str(self.args.vehicle_size_mode),
            "initial_speed_mode": str(self.args.initial_speed_mode),
            "signalization": dict(getattr(self.sim, "signalization_report", {}) or {}),
            "world_loop_ego": self.world_loop_ego,
            "world_ego_speed_cap_mps": self.world_ego_speed_cap_mps,
            "world_context_mode": self.world_context_mode,
            "world_loop_route_pins": self.world_loop_route_pins,
            "world_loop_corridor_corrections": self.world_loop_corridor_corrections,
            "world_loop_projection_rollouts": self.world_loop_projection_rollouts,
            "world_loop_projected_states": self.world_loop_projected_states,
            "world_loop_projection_max_m": round(self.world_loop_projection_max_m, 3),
            "world_loop_route_extent_m": round(self.world_loop_route_extent_m, 3),
            "world_loop_fallback_count": self.world_loop_fallback_count,
            "world_loop_anomaly_protections": self.world_loop_anomaly_protections,
            "world_loop_recovery_rollouts": self.world_loop_recovery_rollouts,
            "world_loop_recovery_blocked_rollouts": self.world_loop_recovery_blocked_rollouts,
            "world_loop_recovery_distance_m": round(self.world_loop_recovery_distance_m, 3),
            "recording_operational_start_step": int(
                getattr(self, "recording_operational_start_step", 0)
            ),
            "initial_speed_summary": dict(
                getattr(self.sim, "initial_speed_summary", {}) if self.sim is not None else {}
            ),
        }

    def _metadata_path(self) -> Path:
        return self.save_file.with_suffix(self.save_file.suffix + ".meta.json")

    def _save_metadata_sidecar(self):
        metadata_path = self._metadata_path()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(self._experiment_params(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_scenario(self):
        self.save_file.parent.mkdir(parents=True, exist_ok=True)
        self.sim.save_to(str(self.save_file))
        try:
            self._save_metadata_sidecar()
            self._save_av_report()
        except Exception as exc:
            self._set_error(f"Scenario metadata write failed: {exc}")

    @staticmethod
    def _av_state_fields(vehicle: dict[str, Any]) -> dict[str, Any]:
        return {
            key: vehicle.get(key)
            for key in ("id", "x", "y", "heading", "speed", "vx", "vy", "ax", "ay", "lane_id")
            if vehicle.get(key) is not None
        }

    def _record_av_state(self, vehicles: list[dict], frame: int) -> None:
        if self.av_id is None:
            return
        vehicle = next((item for item in vehicles if str(item.get("id")) == str(self.av_id)), None)
        if vehicle is None:
            return
        state = {"frame": int(frame), **self._av_state_fields(vehicle)}
        if not self.av_start_state:
            self.av_start_state = dict(state)
        self.av_end_state = dict(state)

    def _av_report(self) -> dict[str, Any]:
        latencies = np.asarray(self.av_command_latencies_ms, dtype=float)
        displacement = 0.0
        if self.av_start_state and self.av_end_state:
            displacement = math.hypot(
                float(self.av_end_state.get("x", 0.0)) - float(self.av_start_state.get("x", 0.0)),
                float(self.av_end_state.get("y", 0.0)) - float(self.av_start_state.get("y", 0.0)),
            )
        return {
            "schema": "denseworld.av-control-report.v1",
            "enabled": self.av_enabled,
            "model": self.av_control_model,
            "selection_mode": self.av_selection_mode,
            "command_mode": self.av_command_mode,
            "endpoint": self.av_bridge.endpoint if self.av_bridge is not None else "",
            "av_id": "" if self.av_id is None else str(self.av_id),
            "world_ego_id": "" if self.world_ego_id is None else str(self.world_ego_id),
            "camera_matches_av": self.av_id is not None and str(self.av_id) == str(self.world_ego_id),
            "perception_frames": self.av_perception_frame_count,
            "command_frames": self.av_command_frame_count,
            "timeout_frames": self.av_command_timeout_count,
            "command_success_rate": round(
                self.av_command_frame_count / max(1, self.av_perception_frame_count), 6
            ),
            "first_command_frame": self.av_first_command_frame,
            "last_command_frame": self.av_last_command_frame,
            "latency_ms": {
                "median": round(float(np.median(latencies)), 4) if len(latencies) else None,
                "p95": round(float(np.percentile(latencies, 95)), 4) if len(latencies) else None,
                "maximum": round(float(np.max(latencies)), 4) if len(latencies) else None,
            },
            "start_state": self.av_start_state,
            "end_state": self.av_end_state,
            "displacement_m": round(displacement, 4),
            "last_diagnostics": self.av_last_diagnostics,
            "collision_details": self.av_collision_details,
            "safety_approximate_fallback_count": int(
                getattr(self.controller, "safety_approximate_fallback_count", 0) or 0
            ),
            "termination_reason": self.termination_reason,
            "sensor_contract": {
                "bev_actor_stream": True,
                "traffic_lights": True,
                "cosmos_transfer_seed_available": bool(self.world_seed_frame),
                "dynamic_rgb_available": bool(self.av_rgb_uri),
                "dynamic_rgb_source": (
                    "cosmos-dreams"
                    if "output/cosmos/experiments" in self.av_rgb_uri
                    else ("carla" if self.av_rgb_uri else "")
                ),
                "cosmos_dreams_online_frames": bool(
                    self.av_rgb_uri and "output/cosmos/experiments" in self.av_rgb_uri
                ),
                "lidar_available": False,
                "radar_count": 0,
            },
        }

    def _save_av_report(self) -> None:
        if not self.av_enabled:
            return
        path = self.save_file.with_suffix(self.save_file.suffix + ".av.json")
        path.write_text(json.dumps(self._av_report(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _release_simulator(self):
        if self.sim is None:
            return
        self.sim.web_viewer = None
        self.sim = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:
            pass

    def _append_metrics(self, display_step: int, vehicles: list[dict]):
        idx = max(0, int(display_step))
        traffic_metrics = _traffic_metrics(vehicles)
        av_metrics = _av_safety_metrics(vehicles)
        speeds = traffic_metrics["speeds"]
        avg_speed = traffic_metrics["avg_speed"]
        _set_metric(
            self.metrics,
            "vehicle_count_per_step",
            idx,
            int(traffic_metrics["motorized_count"] + traffic_metrics["cyclist_count"]),
            0,
        )
        _set_metric(self.metrics, "speed_per_step", idx, avg_speed, None)
        _set_metric(self.metrics, "speed_samples_per_step", idx, [round(x, 3) for x in speeds], [])
        _set_metric(self.metrics, "arrival_rate_per_step", idx, self._arrival_rate(), None)
        _set_metric(self.metrics, "min_ttc_per_step", idx, traffic_metrics["min_ttc"], None)
        _set_metric(self.metrics, "headway_per_step", idx, traffic_metrics["avg_headway"], None)
        _set_metric(self.metrics, "collision_count_per_step", idx, traffic_metrics["collision_count"], None)
        _set_metric(self.metrics, "ttc_samples_per_step", idx, traffic_metrics["ttc_samples"], [])
        _set_metric(self.metrics, "headway_samples_per_step", idx, traffic_metrics["headway_samples"], [])
        _set_metric(self.metrics, "av_min_ttc_per_step", idx, av_metrics["av_min_ttc"], None)
        _set_metric(self.metrics, "av_headway_per_step", idx, av_metrics["av_avg_headway"], None)
        _set_metric(self.metrics, "av_collision_count_per_step", idx, av_metrics["av_collision_count"], None)
        _set_metric(self.metrics, "av_ttc_samples_per_step", idx, av_metrics["av_ttc_samples"], [])
        _set_metric(self.metrics, "av_headway_samples_per_step", idx, av_metrics["av_headway_samples"], [])
        self.metrics["computed_steps"] = max(int(self.metrics.get("computed_steps", 0) or 0), idx + 1)
        self.metrics["total_steps"] = max(int(self.metrics.get("total_steps", 0) or 0), self.total_step)
        self.viewer.set_replay_metrics(self.metrics)
        return {**traffic_metrics, **av_metrics}

    def _mark_av(self, vehicles: list[dict]) -> list[dict]:
        if self.av_id is None:
            return vehicles
        marked = []
        for vehicle in vehicles:
            next_vehicle = dict(vehicle)
            next_vehicle.pop("is_av", None)
            if next_vehicle.get("type") == "av":
                next_vehicle["type"] = "car"
            if str(next_vehicle.get("id")) == str(self.av_id):
                next_vehicle.update({"type": "av", "is_av": True})
            marked.append(next_vehicle)
        return marked

    def _active_vehicle_id(self, raw_id) -> Any | None:
        if self.sim is None:
            return None
        for vehicle_id in self.sim.agent_record.get_valid_agent_ids(timestep=-1):
            if str(vehicle_id) == str(raw_id):
                agent = self.sim.agent_record.get_agents(vehicle_id)
                if str(getattr(agent, "actor_type", "vehicle")).lower() in {
                    "pedestrian",
                    "cyclist",
                    "non_motorized",
                }:
                    return None
                return vehicle_id
        return None

    def _select_av(self, raw_id) -> dict:
        if not self.av_enabled:
            raise RuntimeError("AV access is disabled")
        if self.av_id is not None and not self.waiting_for_av_selection:
            raise RuntimeError("AV selection is locked after the experiment starts")
        vehicle_id = self._active_vehicle_id(raw_id)
        if vehicle_id is None:
            raise ValueError(f"Vehicle {raw_id} is not active in the first frame")
        self.av_id = vehicle_id
        if self.warmup_steps and not self.world_seed_pending:
            self.world_ego_id = vehicle_id
        self.waiting_for_av_selection = False
        self.paused = False
        self.viewer.set_status_fields(
            {
                "av_id": str(vehicle_id),
                "world_ego_id": str(self.world_ego_id or vehicle_id),
                "waiting_for_av_selection": False,
                "paused": False,
                "pause_pending": False,
            }
        )
        return {"ok": True, "message": "AV selected", "av_id": str(vehicle_id)}

    def _random_select_av(self) -> dict:
        candidates = (
            [
                vehicle_id
                for vehicle_id in self.sim.agent_record.get_valid_agent_ids(timestep=-1)
                if str(getattr(self.sim.agent_record.get_agents(vehicle_id), "actor_type", "vehicle")).lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ]
            if self.sim is not None
            else []
        )
        if not candidates:
            raise RuntimeError("No active vehicle is available for AV selection")
        index = int(np.random.randint(0, len(candidates)))
        return self._select_av(candidates[index])

    def _prepare_av_selection(self, vehicles: list[dict]):
        if not self.av_enabled or self.av_id is not None or not vehicles:
            return
        if self.av_selection_mode == "manual":
            self.waiting_for_av_selection = True
            self.paused = True
            self.viewer.set_status_fields(
                {
                    "waiting_for_av_selection": True,
                    "paused": True,
                    "pause_pending": False,
                }
            )
        else:
            self._random_select_av()

    def _lane_id(self, vehicle: dict) -> str:
        try:
            lane = self.sim.map.get_current_lane(
                np.array([float(vehicle["x"]), float(vehicle["y"])]),
                float(vehicle.get("heading", 0.0)),
            )
            if isinstance(lane, tuple):
                lane = lane[0]
            return "" if lane is None else str(lane)
        except Exception:
            return ""

    def _lane_descriptor(self, lane_id: Any) -> dict[str, Any]:
        actual_id = next(
            (item for item in getattr(self.sim.map, "polyline_dict", {}) if str(item) == str(lane_id)),
            lane_id,
        )
        lane = getattr(self.sim.map, "polyline_dict", {}).get(actual_id)
        if lane is None:
            return {}
        points = np.asarray(getattr(lane, "points", []), dtype=float)
        if points.ndim != 2 or not len(points):
            return {"id": str(actual_id), "points": []}
        stride = max(1, int(math.ceil(len(points) / 80.0)))
        return {
            "id": str(actual_id),
            "points": [[round(float(point[0]), 4), round(float(point[1]), 4)] for point in points[::stride]],
        }

    def _av_route_ids(self, current_id: Any) -> list[Any]:
        vehicle_id = self._active_vehicle_id(self.av_id)
        agent = self.sim.agent_record.get_agents(vehicle_id) if vehicle_id is not None else None
        route = list(getattr(agent, "route", []) or [])
        actual_current = next(
            (item for item in getattr(self.sim.map, "polyline_dict", {}) if str(item) == str(current_id)),
            None,
        )
        if actual_current is None:
            return route
        matching_index = next((index for index, item in enumerate(route) if str(item) == str(actual_current)), None)
        if matching_index is not None:
            return route[matching_index:]
        return [actual_current, *route]

    def _route_context(self, vehicle: dict, current_id: Any) -> dict[str, Any]:
        route_ids = self._av_route_ids(current_id)
        route_points: list[list[float]] = []
        segment_starts: dict[str, int] = {}
        for lane_id in route_ids[:16]:
            actual_id = next(
                (item for item in getattr(self.sim.map, "polyline_dict", {}) if str(item) == str(lane_id)),
                None,
            )
            lane = getattr(self.sim.map, "polyline_dict", {}).get(actual_id) if actual_id is not None else None
            points = np.asarray(getattr(lane, "points", []), dtype=float)
            if points.ndim != 2 or not len(points):
                continue
            first_point = [round(float(points[0, 0]), 4), round(float(points[0, 1]), 4)]
            segment_starts[str(actual_id)] = (
                len(route_points) - 1
                if route_points
                and math.hypot(
                    first_point[0] - route_points[-1][0],
                    first_point[1] - route_points[-1][1],
                ) <= 1e-3
                else len(route_points)
            )
            for point in points[:, :2]:
                value = [round(float(point[0]), 4), round(float(point[1]), 4)]
                if not route_points or math.hypot(
                    value[0] - route_points[-1][0], value[1] - route_points[-1][1]
                ) > 1e-3:
                    route_points.append(value)

        signals = []
        traffic_lights = _traffic_lights_from_map(self.sim.map)
        if route_points and segment_starts and traffic_lights:
            points_array = np.asarray(route_points, dtype=float)
            deltas = np.diff(points_array, axis=0)
            segment_lengths = np.linalg.norm(deltas, axis=1)
            cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
            vehicle_position = np.asarray(
                [float(vehicle.get("x", 0.0)), float(vehicle.get("y", 0.0))], dtype=float
            )
            segment_length_sq = np.maximum(np.sum(deltas * deltas, axis=1), 1e-9)
            vehicle_ratios = np.clip(
                np.sum((vehicle_position - points_array[:-1]) * deltas, axis=1)
                / segment_length_sq,
                0.0,
                1.0,
            )
            vehicle_projections = points_array[:-1] + vehicle_ratios[:, None] * deltas
            vehicle_segment = int(
                np.argmin(np.linalg.norm(vehicle_projections - vehicle_position, axis=1))
            )
            vehicle_progress = float(
                cumulative[vehicle_segment]
                + vehicle_ratios[vehicle_segment] * segment_lengths[vehicle_segment]
            )
            ego_stop_offset = 0.5 * max(0.2, float(vehicle.get("length", 3.8))) + 1.0
            skip_initial_signal_block = bool(
                route_ids and str(route_ids[0]) in traffic_lights
            )
            in_signal_block = False
            for lane_id in route_ids[:16]:
                key = str(lane_id)
                if key not in traffic_lights:
                    skip_initial_signal_block = False
                    in_signal_block = False
                    continue
                if skip_initial_signal_block or in_signal_block:
                    continue
                in_signal_block = True
                if key not in segment_starts:
                    continue
                point_index = segment_starts[key]
                distance = float(cumulative[point_index] - vehicle_progress)
                if distance < -0.25:
                    continue
                state = int(traffic_lights[key])
                stop_distance = max(0.0, float(cumulative[point_index]) - ego_stop_offset)
                stop_segment = max(
                    0,
                    min(
                        len(route_points) - 2,
                        int(np.searchsorted(cumulative, stop_distance, side="right") - 1),
                    ),
                )
                span = max(1e-9, float(cumulative[stop_segment + 1] - cumulative[stop_segment]))
                ratio = (stop_distance - float(cumulative[stop_segment])) / span
                stop_point = points_array[stop_segment] + ratio * (
                    points_array[stop_segment + 1] - points_array[stop_segment]
                )
                signals.append(
                    {
                        "id": key,
                        "state": state,
                        "state_name": {0: "green", 1: "yellow", 2: "red"}.get(state, "unknown"),
                        "stop_x": round(float(stop_point[0]), 4),
                        "stop_y": round(float(stop_point[1]), 4),
                        "distance_m": round(max(0.0, distance - ego_stop_offset), 4),
                        "map_stop_x": route_points[point_index][0],
                        "map_stop_y": route_points[point_index][1],
                        "ego_stop_offset_m": round(ego_stop_offset, 4),
                    }
                )
        return {
            "ids": [str(item) for item in route_ids[:16]],
            "points": route_points,
            "signals": signals,
        }

    def _lane_context(self, vehicle: dict | None) -> dict[str, Any]:
        if not vehicle:
            return {}
        current_id = self._lane_id(vehicle)
        actual_id = next(
            (item for item in getattr(self.sim.map, "polyline_dict", {}) if str(item) == current_id),
            None,
        )
        lane = getattr(self.sim.map, "polyline_dict", {}).get(actual_id) if actual_id is not None else None
        left_ids = list(getattr(lane, "left_lanes_id", []) or []) if lane is not None else []
        right_ids = list(getattr(lane, "right_lanes_id", []) or []) if lane is not None else []
        route = self._route_context(vehicle, actual_id)
        return {
            "current_id": current_id,
            "current": self._lane_descriptor(actual_id),
            "left": self._lane_descriptor(left_ids[0]) if left_ids else {},
            "right": self._lane_descriptor(right_ids[0]) if right_ids else {},
            "route": route,
            "route_locked": bool(
                self.world_loop_ego and self.av_control_model == "IDM_MOBIL"
            ),
            "signals": route["signals"],
        }

    def _perception_payload(self, display_step: int, vehicles: list[dict]) -> dict:
        actors = []
        av = None
        for vehicle in vehicles:
            source_type = str(vehicle.get("type") or "vehicle").lower()
            actor_type = (
                "AV"
                if str(vehicle.get("id")) == str(self.av_id)
                else "PEDESTRIAN"
                if source_type == "pedestrian"
                else "CYCLIST"
                if source_type in {"cyclist", "non_motorized"}
                else "BV"
            )
            actor = {
                "id": str(vehicle.get("id", "")),
                "type": actor_type,
                "x": float(vehicle.get("x", 0.0)),
                "y": float(vehicle.get("y", 0.0)),
                "heading": float(vehicle.get("heading", 0.0)),
                "speed": float(vehicle.get("speed", 0.0)),
                "length": float(vehicle.get("length", 3.8)),
                "width": float(vehicle.get("width", 1.8)),
                "lane_id": self._lane_id(vehicle),
            }
            if actor["type"] == "AV":
                av = actor
            else:
                actors.append(actor)
        sensors = {}
        if self.av_rgb_uri:
            rgb_source = "cosmos-dreams" if "output/cosmos/experiments" in self.av_rgb_uri else "carla"
            sensors["rgb_front"] = {
                "transport": "file" if Path(self.av_rgb_uri).is_absolute() else "http",
                "uri": self.av_rgb_uri,
                "encoding": "image/jpeg",
                "source": rgb_source,
                "width": 1280,
                "height": 704 if rgb_source == "cosmos-dreams" else 720,
                "nominal_fps": 10,
            }
        if self.world_seed_frame:
            sensors["cosmos_seed"] = {
                "transport": "file",
                "uri": self.world_seed_frame,
                "encoding": "image/png",
                "source": "cosmos-transfer2.5",
                "dynamic": False,
            }
        return {
            "sim_time": float(display_step) * self.step_seconds,
            "step_seconds": self.step_seconds,
            "av": av or {},
            "actors": actors,
            "lane_context": self._lane_context(av),
            "traffic_lights": _traffic_lights_from_map(self.sim.map),
            "sensors": sensors,
            "sensor_contract": {
                "rgb_available": bool(self.av_rgb_uri),
                "lidar_available": False,
                "radar_count": 0,
            },
        }

    @staticmethod
    def _state_vector(state: dict[str, Any]) -> np.ndarray:
        return np.array(
            [
                float(state.get("x", 0.0)),
                float(state.get("y", 0.0)),
                float(state.get("heading", 0.0)),
                float(state.get("vx", 0.0)),
                float(state.get("vy", 0.0)),
                float(state.get("ax", 0.0)),
                float(state.get("ay", 0.0)),
            ],
            dtype=float,
        )

    def _external_av_trajectory(self, display_step: int, vehicles: list[dict]) -> list[dict[str, float]] | None:
        if self.av_bridge is None or self.av_id is None:
            return None
        current = next((vehicle for vehicle in vehicles if str(vehicle.get("id")) == str(self.av_id)), None)
        if current is None:
            return None
        self.av_perception_frame_count += 1
        self._record_av_state(vehicles, display_step)
        self.viewer.set_status_fields({"av_connected": self.av_bridge.connected, "waiting_for_av_command": True})
        started = time.perf_counter()
        command = self.av_bridge.exchange(
            self._perception_payload(display_step, vehicles),
            frame=display_step,
            timeout=self.av_control_timeout,
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.viewer.set_status_fields(
            {
                "av_connected": self.av_bridge.connected,
                "waiting_for_av_command": False,
                "av_last_command_frame": command.frame if command is not None else None,
            }
        )
        if command is None:
            self.av_command_timeout_count += 1
            self.viewer.set_status_fields({"av_command_timeout_count": self.av_command_timeout_count})
            command = AVCommand(control_mode=self.av_command_mode)
        else:
            self.av_command_frame_count += 1
            self.av_command_latencies_ms.append(latency_ms)
            self.av_first_command_frame = (
                display_step if self.av_first_command_frame is None else self.av_first_command_frame
            )
            self.av_last_command_frame = display_step
            self.av_last_diagnostics = dict(command.diagnostics)
        success_rate = self.av_command_frame_count / max(1, self.av_perception_frame_count)
        self.viewer.set_status_fields(
            {
                "av_perception_frame_count": self.av_perception_frame_count,
                "av_command_frame_count": self.av_command_frame_count,
                "av_command_success_rate": round(success_rate, 6),
                "av_command_latency_ms": round(latency_ms, 4),
            }
        )
        self._handle_remote_command(command)
        return rollout_control(
            current,
            mode=command.control_mode or self.av_command_mode,
            state=command.state,
            actuators=command.actuators,
            trajectory=command.trajectory,
            horizon=20,
            dt=self.step_seconds,
        )

    def _handle_remote_command(self, command: AVCommand | None = None):
        if command is None and self.av_bridge is not None:
            command = self.av_bridge.latest_command()
        if command is None or command.received_at <= self._last_remote_command_time:
            return
        self._last_remote_command_time = command.received_at
        if command.command_type == "pause":
            self.paused = True
            self.viewer.set_status_fields({"paused": True, "pause_pending": False})
        elif command.command_type == "resume":
            self.paused = False
            self.viewer.set_status_fields({"paused": False, "pause_pending": False})
        elif command.command_type == "terminate":
            self.run_stop_requested = True
            self.termination_reason = "av_requested_termination"

    def _overwrite_av_next_state(self, trajectory: list[dict[str, float]] | None):
        if self.av_id is None or not trajectory:
            return
        self.sim.agent_record.update(self.av_id, self._state_vector(trajectory[0]), proceed=False)

    def _av_has_collision(self, vehicles: list[dict]) -> bool:
        av = next((vehicle for vehicle in vehicles if str(vehicle.get("id")) == str(self.av_id)), None)
        if av is None:
            return False
        for other in vehicles:
            if str(other.get("id")) == str(self.av_id):
                continue
            if oriented_boxes_overlap(
                (float(av.get("x", 0.0)), float(av.get("y", 0.0)), float(av.get("heading", 0.0))),
                (float(av.get("length", 3.8)), float(av.get("width", 1.8))),
                (
                    float(other.get("x", 0.0)),
                    float(other.get("y", 0.0)),
                    float(other.get("heading", 0.0)),
                ),
                (float(other.get("length", 3.8)), float(other.get("width", 1.8))),
            ):
                self.av_collision_details = {
                    "av_id": str(self.av_id),
                    "other_id": str(other.get("id", "")),
                    "other_type": str(other.get("type") or "vehicle"),
                    "other_vehicle_class": str(other.get("vehicle_class") or ""),
                    "av_speed_mps": round(float(av.get("speed", 0.0)), 4),
                    "other_speed_mps": round(float(other.get("speed", 0.0)), 4),
                    "method": "oriented_box_sat",
                }
                self.viewer.set_status_fields({"av_collision_details": self.av_collision_details})
                return True
        return False

    def _finish_with_reason(self, reason: str):
        self.termination_reason = reason
        self.completed = True
        self.run_stop_requested = True
        self.paused = False
        self.viewer.set_status_fields(
            {
                "termination_reason": reason,
                "run_state": "completed",
                "experiment_completed": True,
                "paused": False,
            }
        )

    def _warmup_frame(self, raw_step: int, vehicles: list[dict]) -> dict[str, Any]:
        ordered = sorted(vehicles, key=lambda item: str(item.get("id", "")))
        ego_candidates = [
            item
            for item in ordered
            if str(item.get("type") or "vehicle").lower() not in {"pedestrian", "cyclist", "non_motorized"}
        ]
        ego = next(
            (dict(item) for item in ordered if str(item.get("id")) == str(self.world_ego_id)),
            dict(ego_candidates[0]) if ego_candidates else {},
        )
        actors = [dict(item) for item in ordered if str(item.get("id")) != str(ego.get("id"))]
        return {
            "raw_sim_time": round(raw_step * self.step_seconds, 6),
            "sim_time": round((raw_step - self.warmup_steps) * self.step_seconds, 6),
            "ego": ego,
            "vehicles": actors,
            "traffic_lights": _traffic_lights_from_map(self.sim.map),
        }

    def _prepare_denseworld_local_flow(self) -> None:
        vehicles = _vehicle_dicts_from_record(self.sim.agent_record)
        if not vehicles:
            return
        context_actors = _actor_dicts_from_simulator(self.sim)
        signal_points = []
        for polyline in getattr(self.sim.map, "polyline_dict", {}).values():
            if int(getattr(polyline, "type", 0) or 0) != 4:
                continue
            points = np.asarray(getattr(polyline, "points", []), dtype=float)
            if points.ndim == 2 and len(points):
                signal_points.append(points[0, :2])

        positions = np.asarray([[float(item["x"]), float(item["y"])] for item in vehicles], dtype=float)
        signal_array = np.asarray(signal_points, dtype=float) if signal_points else np.empty((0, 2), dtype=float)
        map_points = []
        for polyline in getattr(self.sim.map, "polyline_dict", {}).values():
            if int(getattr(polyline, "type", 0) or 0) not in {0, 1, 2, 3, 4}:
                continue
            points = np.asarray(getattr(polyline, "points", []), dtype=float)
            if points.ndim == 2 and len(points):
                stride = max(1, len(points) // 20)
                map_points.extend(points[::stride, :2])
        map_array = np.asarray(map_points, dtype=float) if map_points else np.empty((0, 2), dtype=float)
        motorized_indices = [
            index
            for index, item in enumerate(vehicles)
            if str(item.get("type") or "vehicle").lower()
            not in {"pedestrian", "cyclist", "non_motorized"}
        ]
        if not motorized_indices:
            return
        if self.world_seed_ego_id:
            requested_indices = [
                index
                for index in motorized_indices
                if str(vehicles[index].get("id")) == self.world_seed_ego_id
            ]
            # Some standard scenarios name an actor that is deterministically
            # replenished during the warmup rather than stored in the opening
            # PKL frame. Lock it here when already present; otherwise retain a
            # valid initial crop and enforce the requested ID after warmup.
            if requested_indices:
                motorized_indices = requested_indices
        best_index = motorized_indices[0]
        best_score = float("-inf")
        best_angular_coverage = 0
        best_front_blocking_score = 0.0
        best_front_context_count = 0
        best_route_report: dict[str, float | int | bool] = {}
        best_context_features: dict[str, float | int] = {}
        best_context_score = 0.0
        best_loop_ready = False
        best_loop_extent_m = math.inf
        best_loop_lane_count = 0
        for index in motorized_indices:
            position = positions[index]
            neighbor_count = int(np.sum(np.linalg.norm(positions - position, axis=1) <= 120.0))
            signal_distance = (
                float(np.min(np.linalg.norm(signal_array - position, axis=1)))
                if len(signal_array)
                else 200.0
            )
            angular_coverage = 0
            if len(map_array):
                deltas = map_array - position
                distances = np.linalg.norm(deltas, axis=1)
                nearby = deltas[(distances >= 5.0) & (distances <= 100.0)]
                if len(nearby):
                    bins = np.floor((np.arctan2(nearby[:, 1], nearby[:, 0]) + math.pi) / (math.pi / 4.0))
                    angular_coverage = len(set(np.clip(bins.astype(int), 0, 7).tolist()))
            heading = float(vehicles[index].get("heading", 0.0) or 0.0)
            cosine, sine = math.cos(heading), math.sin(heading)
            relative = positions - position
            forward = relative[:, 0] * cosine + relative[:, 1] * sine
            lateral = -relative[:, 0] * sine + relative[:, 1] * cosine
            front_blocking_score = 0.0
            front_context_count = 0
            for other_index, (forward_m, lateral_m) in enumerate(zip(forward, lateral)):
                if other_index == index or forward_m <= 1.0:
                    continue
                angle = abs(math.atan2(float(lateral_m), float(forward_m)))
                if 16.0 <= forward_m <= 70.0 and angle <= math.radians(50.0):
                    front_context_count += 1
                if forward_m >= 25.0 or angle > math.radians(55.0):
                    continue
                field_width = float(forward_m) * math.tan(math.radians(55.0)) + 1.0
                centrality = max(0.0, 1.0 - abs(float(lateral_m)) / field_width)
                front_blocking_score += max(0.0, 18.0 - float(forward_m)) * centrality
            route_report = _route_visibility_report(
                self.sim.map,
                self.sim.agent_record,
                vehicles[index],
            )
            front_route_m = float(route_report.get("front_visible_route_m", 0.0) or 0.0)
            remaining_route_m = float(route_report.get("remaining_route_m", 0.0) or 0.0)
            route_score = (
                min(front_route_m, 80.0) * 60.0
                + min(remaining_route_m, 100.0) * 10.0
                - max(0.0, 35.0 - front_route_m) * 150.0
            )
            score = (
                angular_coverage * 1000.0
                + neighbor_count * 10.0
                + min(4, front_context_count) * 300.0
                - min(signal_distance, 500.0) * 5.0
                - front_blocking_score * 120.0
                + route_score
            )
            context_features = _world_context_features(
                position,
                context_actors,
                self.world_crosswalk_centers,
                exclude_id=vehicles[index].get("id"),
            )
            context_score = _world_context_score(
                self.world_context_mode,
                context_features,
            )
            score += context_score
            loop_ready = False
            loop_extent_m = math.inf
            loop_lane_count = 0
            if self.world_loop_ego:
                try:
                    current_lane, _ = self.sim.map.get_current_lane(position, heading)
                    reachable_prefix, reachable_cycle = find_reachable_lane_cycle(
                        self.sim.map,
                        current_lane,
                    )
                    loop_extent_m = route_spatial_extent(
                        self.sim.map,
                        [*reachable_prefix, *reachable_cycle],
                        [float(position[0]), float(position[1])],
                    )
                    loop_ready = bool(reachable_cycle)
                    loop_lane_count = len(reachable_prefix) + len(reachable_cycle)
                except (AttributeError, TypeError, ValueError):
                    loop_ready = False
                score += (
                    1000000.0
                    - _world_loop_compactness_penalty(
                        loop_extent_m,
                        loop_lane_count,
                    )
                    if loop_ready
                    else -1000000.0
                )
            if score > best_score:
                best_index, best_score = index, score
                best_angular_coverage = angular_coverage
                best_front_blocking_score = front_blocking_score
                best_front_context_count = front_context_count
                best_route_report = route_report
                best_context_features = context_features
                best_context_score = context_score
                best_loop_ready = loop_ready
                best_loop_extent_m = loop_extent_m
                best_loop_lane_count = loop_lane_count

        if self.world_loop_ego and not best_loop_ready:
            raise RuntimeError(
                "No CityNDE ego candidate has a reachable directed lane cycle"
            )

        selected = vehicles[best_index]
        anchor_match = (
            select_pose_matched_anchor(
                vehicles,
                self.world_appearance_anchors,
                seed=int(self.args.seed),
            )
            if self.world_context_mode == "auto" and not self.world_loop_ego
            and not self.world_seed_ego_id
            else None
        )
        if anchor_match is not None:
            matched_id = str(anchor_match["actor_id"])
            matched_index = next(
                (index for index, item in enumerate(vehicles) if str(item.get("id")) == matched_id),
                None,
            )
            if matched_index is not None:
                best_index = matched_index
                selected = vehicles[best_index]
                center = positions[best_index]
                anchor = dict(anchor_match["anchor"])
                self.world_appearance_anchor = {
                    "id": str(anchor["id"]),
                    "image_path": str(anchor["image_path"]),
                    "control_path": str(anchor["control_path"]),
                    "actor_id": matched_id,
                    "position_error_m": round(float(anchor_match["position_error_m"]), 4),
                    "heading_error_deg": round(float(anchor_match["heading_error_deg"]), 4),
                    "candidate_count": int(anchor_match["candidate_count"]),
                    "traffic_source": "current_simulation",
                }
                best_context_features = _world_context_features(
                    center,
                    context_actors,
                    self.world_crosswalk_centers,
                    exclude_id=selected.get("id"),
                )
                best_context_score = _world_context_score(
                    self.world_context_mode,
                    best_context_features,
                )
        center = positions[best_index]
        radius = self.world_region_radius
        distances_from_center = np.linalg.norm(positions - center, axis=1)
        nearby_indices = [
            index
            for index, distance in enumerate(distances_from_center)
            if float(distance) <= radius
        ]
        if self.world_initial_vehicle_limit > 0:
            nearby_indices.sort(
                key=lambda index: (
                    0 if index == best_index else 1,
                    float(distances_from_center[index]),
                    str(vehicles[index].get("id")),
                )
            )
            nearby_indices = nearby_indices[: self.world_initial_vehicle_limit]
        keep_ids = {vehicles[index].get("id") for index in nearby_indices}
        for item in vehicles:
            if item.get("id") not in keep_ids:
                vehicle_id = item.get("id")
                if hasattr(self.sim, "_normalize_vehicle_id"):
                    vehicle_id = self.sim._normalize_vehicle_id(vehicle_id)
                self.sim.remove_vehicle(vehicle_id)

        self.world_ego_id = selected.get("id")
        self.world_region_center = (float(center[0]), float(center[1]))
        # DenseWorld replenishes the moving local crop explicitly below. Leaving
        # every nearby start lane at CityNDE's per-step arrival rate lets dozens
        # of lanes overfill the crop before occupancy checks catch up.
        local_rate = 0.0
        for lane_id in getattr(self.sim.map, "start_lane", []) or []:
            lane = self.sim.map.polyline_dict.get(lane_id)
            points = np.asarray(getattr(lane, "points", []), dtype=float)
            near_region = bool(
                points.ndim == 2
                and len(points)
                and float(np.min(np.linalg.norm(points[:, :2] - center, axis=1))) <= radius
            )
            self.sim.lane_arrival_rates[lane_id] = local_rate if near_region else 0.0
        local_context_count = sum(
            1
            for index, distance in enumerate(distances_from_center)
            if vehicles[index].get("id") in keep_ids and float(distance) <= 140.0
        )
        self.world_local_target_count = (
            self.world_requested_local_target_count
            if self.world_requested_local_target_count > 0
            else max(24, min(48, local_context_count))
        )
        self.viewer.set_status_fields(
            {
                "world_ego_id": str(self.world_ego_id),
                "world_region_center": [round(float(center[0]), 3), round(float(center[1]), 3)],
                "world_region_radius": radius,
                "world_local_vehicle_count": len(keep_ids),
                "world_local_target_count": self.world_local_target_count,
                "world_requested_local_target_count": self.world_requested_local_target_count,
                "world_initial_vehicle_limit": self.world_initial_vehicle_limit,
                "world_angular_coverage": best_angular_coverage,
                "world_front_blocking_score": round(best_front_blocking_score, 3),
                "world_front_context_count": best_front_context_count,
                "world_route_visibility": best_route_report,
                "world_appearance_anchor": dict(self.world_appearance_anchor),
                "world_context_mode": self.world_context_mode,
                "world_context_features": _finite_context_features(best_context_features),
                "world_context_score": round(best_context_score, 3),
                "world_loop_candidate_ready": best_loop_ready,
                "world_loop_candidate_extent_m": (
                    round(best_loop_extent_m, 3)
                    if math.isfinite(best_loop_extent_m)
                    else None
                ),
                "world_loop_candidate_lane_count": best_loop_lane_count,
            }
        )
        self._pin_world_ego_route(vehicles)

    def _pin_world_ego_route(self, vehicles: list[dict]) -> bool:
        if not self.world_loop_ego or self.world_ego_id is None:
            return False
        focus = next(
            (item for item in vehicles if str(item.get("id")) == str(self.world_ego_id)),
            None,
        )
        active_id = self._active_vehicle_id(self.world_ego_id)
        if focus is None or active_id is None:
            return False
        try:
            current_lane, lane_distance = self.sim.map.get_current_lane(
                np.asarray([float(focus["x"]), float(focus["y"])], dtype=float),
                float(focus.get("heading", 0.0) or 0.0),
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

        prefix = list(self.world_loop_route_prefix)
        cycle = list(self.world_loop_route_cycle)
        detected_lane = current_lane
        corridor_distance = math.inf
        if current_lane not in prefix and current_lane not in cycle and (prefix or cycle):
            corridor_lane, corridor_distance = _nearest_route_lane(
                self.sim.map,
                [*prefix, *cycle],
                np.asarray([float(focus["x"]), float(focus["y"])], dtype=float),
            )
            # get_current_lane can select an adjacent parallel lane after a
            # learned lateral rollout. Keep the DenseWorld camera actor on its
            # established directed cycle while it remains inside that corridor.
            if corridor_lane is not None and corridor_distance <= 6.0:
                current_lane = corridor_lane
                lane_distance = corridor_distance
                self.world_loop_corridor_corrections = (
                    int(getattr(self, "world_loop_corridor_corrections", 0)) + 1
                )
        if current_lane in cycle:
            cycle_index = cycle.index(current_lane)
            cycle = cycle[cycle_index:] + cycle[:cycle_index]
            prefix = []
        elif current_lane in prefix:
            prefix = prefix[prefix.index(current_lane) :]
        else:
            prefix, cycle = find_reachable_lane_cycle(self.sim.map, current_lane)
        if not cycle:
            self.viewer.set_status_fields(
                {
                    "world_loop_route_ready": False,
                    "world_loop_route_error": f"No directed lane cycle reachable from {current_lane}",
                }
            )
            return False

        route = cycle_route_window(prefix, cycle, maximum_lane_count=8)
        # RouteTLVectorMap only accepts prefixes from its native depth-eight
        # route table. Validate the intended cycle window and progressively
        # shorten it only when a source map has a stricter route record. The
        # route table returns a random continuation to a map exit, so it must
        # only be used for validation; replacing the window with that return
        # value makes a nominal loop ego leave the scene after one traversal.
        while len(route) > 1:
            try:
                self.sim.map.get_routes(
                    current_lane_id=route,
                    full=False,
                    visited_route=set(),
                )
                break
            except (AssertionError, KeyError, TypeError, ValueError):
                route = route[:-1]
        if len(route) <= 1:
            try:
                route = list(
                    self.sim.map.get_routes(
                        current_lane_id=current_lane,
                        full=False,
                        visited_route=set(),
                    )
                )
            except (AssertionError, KeyError, TypeError, ValueError):
                return False
        agent = self.sim.agent_record.get_agents(active_id)
        if agent is None:
            return False
        external_av_controls_route = (
            self.av_id is not None
            and self.av_control_model
            in {"EXTERNAL_TCP", "VTD_TCP", "LEAD_TFV6_STREAM"}
        )
        if not external_av_controls_route:
            if not hasattr(agent, "assign_route"):
                return False
            agent.assign_route(route)
        self.world_loop_route_prefix = list(prefix)
        self.world_loop_route_cycle = list(cycle)
        loop_route = [*prefix, *cycle]
        self.world_loop_route_extent_m = route_spatial_extent(
            self.sim.map,
            loop_route,
            [float(focus["x"]), float(focus["y"])],
        )
        self.world_loop_route_pins += 1
        self.viewer.set_status_fields(
            {
                "world_loop_route_ready": True,
                "world_loop_route_error": "",
                "world_loop_current_lane": str(current_lane),
                "world_loop_detected_lane": str(detected_lane),
                "world_loop_lane_distance_m": round(float(lane_distance), 3),
                "world_loop_corridor_distance_m": (
                    round(float(corridor_distance), 3)
                    if math.isfinite(corridor_distance)
                    else None
                ),
                "world_loop_corridor_corrections": int(
                    getattr(self, "world_loop_corridor_corrections", 0)
                ),
                "world_loop_prefix_lane_count": len(prefix),
                "world_loop_cycle_lane_count": len(cycle),
                "world_loop_route_window_lane_count": len(route),
                "world_loop_route_extent_m": round(self.world_loop_route_extent_m, 3),
                "world_loop_route_lane_ids": [str(lane_id) for lane_id in loop_route],
                "world_loop_route_pins": self.world_loop_route_pins,
                "world_loop_route_control": (
                    "external_av"
                    if external_av_controls_route
                    else "internal_av"
                    if self.av_id is not None and self.av_control_model == "IDM_MOBIL"
                    else "citynde"
                ),
            }
        )
        return True

    def _protect_world_ego_from_anomaly_removal(self) -> bool:
        """Keep the selected world camera actor through transient deadlock flags."""
        if not self.world_loop_ego or self.world_ego_id is None or self.av_id is not None:
            return False
        manager = getattr(self.sim, "scenario_manager", None)
        anomalous_ids = list(getattr(manager, "anomalous_vehicle_ids", []) or [])
        retained_ids = [
            vehicle_id
            for vehicle_id in anomalous_ids
            if str(vehicle_id) != str(self.world_ego_id)
        ]
        if len(retained_ids) == len(anomalous_ids):
            return False
        manager.anomalous_vehicle_ids = retained_ids
        self.world_loop_anomaly_protections = int(
            getattr(self, "world_loop_anomaly_protections", 0)
        ) + 1
        self.viewer.set_status_fields(
            {
                "world_loop_anomaly_protections": self.world_loop_anomaly_protections,
                "world_loop_last_protected_ego_id": str(self.world_ego_id),
            }
        )
        return True

    def _constrain_world_ego_rollout(
        self,
        required_steps: int,
        *,
        recover_from_anomaly: bool = False,
    ) -> bool:
        """Keep the DenseWorld camera actor on its selected lane cycle."""
        internal_loop_av = (
            self.av_id is not None
            and self.av_control_model == "IDM_MOBIL"
            and str(self.av_id) == str(self.world_ego_id)
        )
        if (
            not self.world_loop_ego
            or self.world_ego_id is None
            or (self.av_id is not None and not internal_loop_av)
        ):
            return False
        record = self.sim.agent_record
        active_id = self._active_vehicle_id(self.world_ego_id)
        agent = record.get_agents(active_id) if active_id is not None else None
        if agent is None:
            return False
        required_steps = max(1, int(required_steps))
        state_start = int(record.current_step) - int(agent.spawn_time_step) + 1
        future = np.asarray(
            agent.states[state_start : state_start + required_steps],
            dtype=float,
        ).copy()
        if len(future) != required_steps or future.ndim != 2 or future.shape[1] < 5:
            return False
        route_ids = list(getattr(agent, "route", []) or [])
        if not route_ids:
            route_ids = cycle_route_window(
                self.world_loop_route_prefix,
                self.world_loop_route_cycle,
                maximum_lane_count=8,
            )
        if not route_ids:
            return False

        projected_count = 0
        maximum_distance = 0.0
        projected_lanes: list[str] = []
        for state in future:
            lane_id, projected, route_heading, distance = _nearest_route_projection(
                self.sim.map,
                route_ids,
                state[:2],
                float(state[2]),
            )
            if projected is None or not math.isfinite(distance):
                continue
            speed = float(math.hypot(float(state[3]), float(state[4])))
            acceleration = (
                float(math.hypot(float(state[5]), float(state[6])))
                if state.shape[0] >= 7
                else 0.0
            )
            state[0:2] = projected
            state[2] = route_heading
            state[3] = speed * math.cos(route_heading)
            state[4] = speed * math.sin(route_heading)
            if state.shape[0] >= 7:
                state[5] = acceleration * math.cos(route_heading)
                state[6] = acceleration * math.sin(route_heading)
            projected_count += 1
            maximum_distance = max(maximum_distance, distance)
            projected_lanes.append(str(lane_id))
        if projected_count != required_steps:
            return False

        recovery_reason = ""
        recovery_distance = 0.0
        recovery_peak_speed = 0.0
        if recover_from_anomaly:
            points, cumulative, lane_starts = _route_centerline_geometry(
                self.sim.map,
                route_ids,
            )
            if len(points) >= 2:
                current_index = max(0, state_start - 1)
                current_state = np.asarray(agent.states[current_index], dtype=float)
                current_progress, _ = _polyline_progress(
                    points,
                    cumulative,
                    current_state[:2],
                )
                maximum_travel = max(0.0, float(cumulative[-1]) - current_progress)

                traffic_lights = _traffic_lights_from_map(self.sim.map)
                for lane_id, lane_progress in lane_starts:
                    distance = lane_progress - current_progress
                    if distance <= 0.25 or lane_id not in traffic_lights:
                        continue
                    if int(traffic_lights[lane_id]) != 0:
                        ego_length = float(current_state[7]) if len(current_state) > 7 else 4.5
                        stop_distance = max(0.0, distance - 0.5 * ego_length - 1.0)
                        if stop_distance < maximum_travel:
                            maximum_travel = stop_distance
                            recovery_reason = "red_or_yellow_signal"
                    break

                for actor in _actor_dicts_from_simulator(self.sim):
                    if str(actor.get("id")) == str(self.world_ego_id):
                        continue
                    actor_type = str(actor.get("type") or "vehicle").lower()
                    actor_progress, lateral_distance = _polyline_progress(
                        points,
                        cumulative,
                        np.asarray(
                            [float(actor.get("x", 0.0)), float(actor.get("y", 0.0))],
                            dtype=float,
                        ),
                    )
                    distance = actor_progress - current_progress
                    if distance <= 0.0 or lateral_distance > 2.8:
                        continue
                    ego_length = float(current_state[7]) if len(current_state) > 7 else 4.5
                    ego_width = float(current_state[8]) if len(current_state) > 8 else 1.8
                    actor_length = max(0.4, float(actor.get("length", 4.0) or 4.0))
                    actor_width = max(0.3, float(actor.get("width", 1.8) or 1.8))
                    if actor_type == "pedestrian":
                        route_point, route_heading = _sample_route_centerline(
                            points,
                            cumulative,
                            actor_progress,
                        )
                        if not oriented_boxes_overlap(
                            (float(route_point[0]), float(route_point[1]), route_heading),
                            (ego_length, ego_width),
                            (
                                float(actor.get("x", 0.0)),
                                float(actor.get("y", 0.0)),
                                float(actor.get("heading", 0.0)),
                            ),
                            (actor_length, actor_width),
                            margin=0.15,
                        ):
                            continue
                    clearance = 0.5 * (ego_length + actor_length) + 2.0
                    actor_limit = max(0.0, distance - clearance)
                    if actor_limit < maximum_travel:
                        maximum_travel = actor_limit
                        recovery_reason = f"lead_{actor_type}"

                step_seconds = max(1e-3, float(self.step_seconds))
                speed = math.hypot(float(current_state[3]), float(current_state[4]))
                target_speed = min(4.0, max(2.5, speed))
                travelled = 0.0
                for state in future:
                    remaining = max(0.0, maximum_travel - travelled)
                    safe_speed = math.sqrt(2.0 * 2.5 * remaining)
                    next_speed = min(target_speed, speed + 1.5 * step_seconds, safe_speed)
                    if remaining <= 0.05:
                        next_speed = 0.0
                    step_distance = min(
                        remaining,
                        0.5 * (speed + next_speed) * step_seconds,
                    )
                    travelled += step_distance
                    point, route_heading = _sample_route_centerline(
                        points,
                        cumulative,
                        current_progress + travelled,
                    )
                    acceleration = (next_speed - speed) / step_seconds
                    state[0:2] = point
                    state[2] = route_heading
                    state[3] = next_speed * math.cos(route_heading)
                    state[4] = next_speed * math.sin(route_heading)
                    if state.shape[0] >= 7:
                        state[5] = acceleration * math.cos(route_heading)
                        state[6] = acceleration * math.sin(route_heading)
                    speed = next_speed
                    recovery_peak_speed = max(recovery_peak_speed, next_speed)
                recovery_distance = travelled
                self.world_loop_recovery_rollouts = int(
                    getattr(self, "world_loop_recovery_rollouts", 0)
                ) + 1
                self.world_loop_recovery_distance_m = float(
                    getattr(self, "world_loop_recovery_distance_m", 0.0)
                ) + travelled
                if travelled <= 0.05:
                    self.world_loop_recovery_blocked_rollouts = int(
                        getattr(self, "world_loop_recovery_blocked_rollouts", 0)
                    ) + 1

        record.update(active_id, future, proceed=False)
        self.world_loop_projection_rollouts += 1
        self.world_loop_projected_states += projected_count
        self.world_loop_projection_max_m = max(
            self.world_loop_projection_max_m,
            maximum_distance,
        )
        self.viewer.set_status_fields(
            {
                "world_loop_projection_rollouts": self.world_loop_projection_rollouts,
                "world_loop_projected_states": self.world_loop_projected_states,
                "world_loop_projection_last_max_m": round(maximum_distance, 3),
                "world_loop_projection_max_m": round(self.world_loop_projection_max_m, 3),
                "world_loop_projection_lanes": projected_lanes,
                "world_loop_recovery_rollouts": int(
                    getattr(self, "world_loop_recovery_rollouts", 0)
                ),
                "world_loop_recovery_blocked_rollouts": int(
                    getattr(self, "world_loop_recovery_blocked_rollouts", 0)
                ),
                "world_loop_recovery_distance_m": round(
                    float(getattr(self, "world_loop_recovery_distance_m", 0.0)), 3
                ),
                "world_loop_recovery_last_distance_m": round(recovery_distance, 3),
                "world_loop_recovery_peak_speed_mps": round(recovery_peak_speed, 3),
                "world_loop_recovery_constraint": recovery_reason,
            }
        )
        return True

    def _cap_world_ego_rollout_speed(self, required_steps: int) -> bool:
        """Bound camera-ego progress without replacing CityNDE route choices."""
        if (
            self.world_ego_speed_cap_mps <= 0.0
            or self.world_ego_id is None
            or self.av_id is not None
        ):
            return False
        record = self.sim.agent_record
        active_id = self._active_vehicle_id(self.world_ego_id)
        agent = record.get_agents(active_id) if active_id is not None else None
        if agent is None:
            return False
        required_steps = max(1, int(required_steps))
        state_start = int(record.current_step) - int(agent.spawn_time_step) + 1
        future = np.asarray(
            agent.states[state_start : state_start + required_steps],
            dtype=float,
        ).copy()
        if len(future) != required_steps or future.ndim != 2 or future.shape[1] < 5:
            return False

        current_index = max(0, state_start - 1)
        current = np.asarray(agent.states[current_index], dtype=float)
        position = current[:2].copy()
        previous_raw_position = current[:2].copy()
        previous_velocity = np.asarray(current[3:5], dtype=float).copy()
        step_seconds = max(1e-3, float(self.step_seconds))
        maximum_speed = 0.0
        for state in future:
            raw_position = state[:2].copy()
            displacement = raw_position - previous_raw_position
            distance = float(np.linalg.norm(displacement))
            predicted_speed = float(np.linalg.norm(state[3:5]))
            if distance > 1e-6:
                direction = displacement / distance
            elif predicted_speed > 1e-6:
                direction = state[3:5] / predicted_speed
            else:
                direction = np.asarray(
                    [math.cos(float(state[2])), math.sin(float(state[2]))],
                    dtype=float,
                )
            bounded_speed = min(
                self.world_ego_speed_cap_mps,
                predicted_speed,
                distance / step_seconds,
            )
            position += direction * bounded_speed * step_seconds
            velocity = direction * bounded_speed
            state[0:2] = position
            state[2] = math.atan2(float(direction[1]), float(direction[0]))
            state[3:5] = velocity
            if state.shape[0] >= 7:
                state[5:7] = (velocity - previous_velocity) / step_seconds
            previous_raw_position = raw_position
            previous_velocity = velocity
            maximum_speed = max(maximum_speed, bounded_speed)

        record.update(active_id, future, proceed=False)
        self.viewer.set_status_fields(
            {
                "world_ego_speed_cap_mps": self.world_ego_speed_cap_mps,
                "world_ego_capped_rollout_peak_mps": round(maximum_speed, 3),
            }
        )
        return True

    def _maintain_denseworld_local_flow(
        self,
        vehicles: list[dict],
        display_step: int,
        *,
        next_prediction_due: bool = True,
        force_initial: bool = False,
        allow_dense_reserve: bool = True,
    ) -> int:
        if (
            not (
                self.warmup_steps
                or bool(getattr(self, "existing_seed_gate", False))
            )
            or self.world_seed_pending
            or not vehicles
            or not next_prediction_due
        ):
            return 0
        # Replenish on every CityNDE prediction boundary. Waiting a full second
        # leaves a fast ego under-populated for two consecutive rollouts.
        interval_steps = max(
            1,
            int(
                getattr(
                    getattr(self, "controller", None),
                    "control_step",
                    round(0.5 / max(self.step_seconds, 1e-6)),
                )
            ),
        )
        if not force_initial and (
            display_step <= 0
            or display_step - self.world_last_flow_update_step < interval_steps
        ):
            return 0
        self.world_last_flow_update_step = display_step
        focus_id = self.av_id if self.av_id is not None else self.world_ego_id
        focus = next((item for item in vehicles if str(item.get("id")) == str(focus_id)), None)
        if focus is None:
            return 0

        center = np.asarray([float(focus.get("x", 0.0)), float(focus.get("y", 0.0))], dtype=float)
        self.world_region_center = (float(center[0]), float(center[1]))
        spawn_visibility_guard_m = max(
            0.0,
            float(getattr(self, "world_spawn_visibility_guard_m", 100.0) or 0.0),
        )
        arrival_radius = max(280.0, self.world_region_radius)
        local_rate = 0.0
        for lane_id in getattr(self.sim.map, "start_lane", []) or []:
            lane = self.sim.map.polyline_dict.get(lane_id)
            points = np.asarray(getattr(lane, "points", []), dtype=float)
            near_focus = bool(
                points.ndim == 2
                and len(points)
                and float(np.min(np.linalg.norm(points[:, :2] - center, axis=1))) <= arrival_radius
            )
            self.sim.lane_arrival_rates[lane_id] = local_rate if near_focus else 0.0

        prune_radius = max(220.0, self.world_region_radius)
        outside_ids = []
        retained_vehicles = []
        for item in vehicles:
            actor_type = str(item.get("type") or "vehicle").lower()
            if actor_type == "pedestrian":
                retained_vehicles.append(item)
                continue
            distance = float(
                np.linalg.norm(
                    np.asarray([item.get("x", 0.0), item.get("y", 0.0)], dtype=float)
                    - center
                )
            )
            if str(item.get("id")) != str(focus_id) and distance > prune_radius:
                outside_ids.append(item.get("id"))
            else:
                retained_vehicles.append(item)
        removed_outside = 0
        for vehicle_id in outside_ids:
            normalized_id = (
                self.sim._normalize_vehicle_id(vehicle_id)
                if hasattr(self.sim, "_normalize_vehicle_id")
                else vehicle_id
            )
            if normalized_id not in self.sim.agent_record._id_agent_mapping:
                continue
            self.sim.remove_vehicle(normalized_id)
            removed_outside += 1
        if removed_outside:
            self.world_pruned_outside_agents = int(
                getattr(self, "world_pruned_outside_agents", 0)
            ) + removed_outside
        pruned_outside = int(getattr(self, "world_pruned_outside_agents", 0))

        def local_snapshot(source: list[dict]):
            road_users = []
            distances: dict[str, float] = {}
            for item in source:
                if str(item.get("id")) == str(focus_id):
                    continue
                actor_type = str(
                    item.get("road_user_type") or item.get("type") or "vehicle"
                ).lower()
                if actor_type == "pedestrian":
                    continue
                distance = float(
                    np.linalg.norm(
                        np.asarray([item.get("x", 0.0), item.get("y", 0.0)], dtype=float)
                        - center
                    )
                )
                if distance <= 140.0:
                    road_users.append(item)
                    distances[str(item.get("id"))] = distance
            cyclists = [
                item
                for item in road_users
                if str(item.get("road_user_type") or item.get("type") or "vehicle").lower()
                in {"cyclist", "non_motorized"}
            ]
            motorized = [item for item in road_users if item not in cyclists]
            motorized_60 = [
                item for item in motorized if distances[str(item.get("id"))] <= 60.0
            ]
            motorized_120 = [
                item for item in motorized if distances[str(item.get("id"))] <= 120.0
            ]
            return road_users, cyclists, motorized, motorized_60, motorized_120

        (
            local_road_users,
            local_cyclists,
            local_motorized,
            local_motorized_60,
            local_motorized_120,
        ) = local_snapshot(retained_vehicles)
        cyclist_target = (
            max(1, int(round(self.world_local_target_count * float(self.sim.cyclist_ratio))))
            if self.sim.mixed_traffic_enabled and float(self.sim.cyclist_ratio) > 0.0
            else 0
        )
        # A single 140 m quota can remain full while a fast AV leaves its near
        # field behind. Tiered motorized quotas keep both the controller and
        # generated camera view populated without bypassing spawn clearance.
        motorized_target = max(1, self.world_local_target_count - cyclist_target)
        motorized_60_target = min(
            motorized_target,
            max(8, int(math.ceil(self.world_local_target_count * 0.2))),
        )
        motorized_120_target = min(
            motorized_target,
            max(14, int(math.ceil(self.world_local_target_count * 0.4))),
        )
        cyclist_deficit = max(0, cyclist_target - len(local_cyclists))
        total_deficit = max(0, self.world_local_target_count - len(local_road_users))
        motorized_total_deficit = max(0, motorized_target - len(local_motorized))
        motorized_60_deficit = max(0, motorized_60_target - len(local_motorized_60))
        motorized_120_deficit = max(0, motorized_120_target - len(local_motorized_120))
        required_spawns = max(
            total_deficit,
            cyclist_deficit
            + max(
                motorized_total_deficit,
                motorized_60_deficit,
                motorized_120_deficit,
            ),
        )
        explicit_low_load = (
            int(getattr(self, "world_requested_local_target_count", 0) or 0) > 0
        )
        replaced = 0
        if (
            explicit_low_load
            and force_initial
            and required_spawns > 0
            and len(local_road_users) >= self.world_local_target_count
            and hasattr(self.sim, "_spawn_actor_on_lane")
        ):
            replacement_candidates = []
            for item in local_motorized:
                distance = float(
                    np.linalg.norm(
                        np.asarray([item.get("x", 0.0), item.get("y", 0.0)], dtype=float)
                        - center
                    )
                )
                if distance > 60.0 or cyclist_deficit > 0:
                    replacement_candidates.append((distance, item))
            replacement_candidates.sort(key=lambda entry: entry[0], reverse=True)
            removed_ids: set[str] = set()
            replacement_budget = min(4, required_spawns, len(replacement_candidates))
            for _distance, item in replacement_candidates[:replacement_budget]:
                vehicle_id = item.get("id")
                normalized_id = (
                    self.sim._normalize_vehicle_id(vehicle_id)
                    if hasattr(self.sim, "_normalize_vehicle_id")
                    else vehicle_id
                )
                mapping = getattr(self.sim.agent_record, "_id_agent_mapping", {})
                if mapping and normalized_id not in mapping:
                    continue
                self.sim.remove_vehicle(normalized_id)
                removed_ids.add(str(vehicle_id))
                replaced += 1
            if removed_ids:
                retained_vehicles = [
                    item
                    for item in retained_vehicles
                    if str(item.get("id")) not in removed_ids
                ]
                (
                    local_road_users,
                    local_cyclists,
                    local_motorized,
                    local_motorized_60,
                    local_motorized_120,
                ) = local_snapshot(retained_vehicles)
                cyclist_deficit = max(0, cyclist_target - len(local_cyclists))
                total_deficit = max(
                    0, self.world_local_target_count - len(local_road_users)
                )
                motorized_total_deficit = max(
                    0, motorized_target - len(local_motorized)
                )
                motorized_60_deficit = max(
                    0, motorized_60_target - len(local_motorized_60)
                )
                motorized_120_deficit = max(
                    0, motorized_120_target - len(local_motorized_120)
                )
                required_spawns = max(
                    total_deficit,
                    cyclist_deficit
                    + max(
                        motorized_total_deficit,
                        motorized_60_deficit,
                        motorized_120_deficit,
                    ),
                )
                self.world_local_replaced_agents = int(
                    getattr(self, "world_local_replaced_agents", 0)
                ) + replaced
        # An explicit count is not necessarily a low-load request. Dense
        # scenes need a small off-screen reserve so a fast ego does not drain
        # the 60 m near field before newly spawned traffic can enter it.
        if explicit_low_load:
            overflow_capacity = (
                max(2, min(8, int(math.ceil(self.world_local_target_count * 0.5))))
                if (
                    self.world_local_target_count >= 10
                    and not force_initial
                    and allow_dense_reserve
                )
                else 0
            )
        else:
            overflow_capacity = 10
        local_capacity = max(
            0,
            self.world_local_target_count + overflow_capacity - len(local_road_users),
        )
        spawn_budget = min(8, required_spawns, local_capacity)
        if spawn_budget <= 0 or not hasattr(self.sim, "_spawn_actor_on_lane"):
            self.viewer.set_status_fields(
                {
                    "world_region_center": [round(float(center[0]), 3), round(float(center[1]), 3)],
                    "world_local_vehicle_count": len(local_road_users),
                    "world_local_target_count": self.world_local_target_count,
                    "world_local_motorized_count": len(local_motorized),
                    "world_local_motorized_60m_count": len(local_motorized_60),
                    "world_local_motorized_60m_target": motorized_60_target,
                    "world_local_motorized_120m_count": len(local_motorized_120),
                    "world_local_motorized_120m_target": motorized_120_target,
                    "world_local_cyclist_count": len(local_cyclists),
                    "world_local_cyclist_target_count": cyclist_target,
                    "world_local_spawned": 0,
                    "world_local_replaced": replaced,
                    "world_local_replaced_total": int(
                        getattr(self, "world_local_replaced_agents", 0)
                    ),
                    "world_local_counts_exclude_av": True,
                    "world_local_flow_sim_time": round(display_step * self.step_seconds, 3),
                    "world_local_arrival_rate": local_rate,
                    "world_pruned_outside_agents": pruned_outside,
                }
            )
            return 0

        focus_heading = float(focus.get("heading", 0.0) or 0.0)
        focus_speed = max(0.0, float(focus.get("speed", 0.0) or 0.0))
        focus_velocity = np.asarray(
            [float(focus.get("vx", 0.0) or 0.0), float(focus.get("vy", 0.0) or 0.0)],
            dtype=float,
        )
        if float(np.linalg.norm(focus_velocity)) < 1e-3 and focus_speed > 0.0:
            focus_velocity = focus_speed * np.asarray(
                [math.cos(focus_heading), math.sin(focus_heading)], dtype=float
            )
        estimated_spawn_speed = min(10.0, max(6.0, focus_speed))
        candidates: list[
            tuple[float, Any, float, bool, tuple[Any, int], float]
        ] = []
        for lane_id, lane in getattr(self.sim.map, "polyline_dict", {}).items():
            try:
                if not self.sim.map.is_lane_center(lane_id) or int(getattr(lane, "type", -1)) == 4:
                    continue
            except (AttributeError, TypeError, ValueError):
                continue
            points = np.asarray(getattr(lane, "points", []), dtype=float)
            if points.ndim != 2 or len(points) < 2 or points.shape[1] < 2:
                continue
            distances = np.linalg.norm(points[:, :2] - center, axis=1)
            minimum_spawn_distance = (
                35.0 if force_initial else spawn_visibility_guard_m
            )
            valid = np.where(
                (distances >= minimum_spawn_distance) & (distances <= 180.0)
            )[0]
            if not len(valid):
                continue
            target_distances = (
                (50.0, 90.0)
                if force_initial
                else (
                    max(minimum_spawn_distance, 110.0),
                    max(minimum_spawn_distance + 25.0, 140.0),
                )
            )
            for target_distance in target_distances:
                point_index = int(valid[np.argmin(np.abs(distances[valid] - target_distance))])
                segments = np.linalg.norm(np.diff(points[: point_index + 1, :2], axis=0), axis=1)
                longitudinal = max(5.0, float(np.sum(segments)))
                if point_index + 1 < len(points):
                    tangent = points[point_index + 1, :2] - points[point_index, :2]
                else:
                    tangent = points[point_index, :2] - points[point_index - 1, :2]
                tangent_norm = float(np.linalg.norm(tangent))
                relative = points[point_index, :2] - center
                relative_norm = max(1e-6, float(np.linalg.norm(relative)))
                candidate_velocity = (
                    estimated_spawn_speed * tangent / tangent_norm
                    if tangent_norm > 1e-6
                    else np.zeros(2, dtype=float)
                )
                closing_rate = max(
                    0.0,
                    -float(
                        np.dot(relative / relative_norm, candidate_velocity - focus_velocity)
                    ),
                )
                candidates.append(
                    (
                        float(distances[point_index]),
                        lane_id,
                        longitudinal,
                        bool(
                            self.sim.mixed_traffic_enabled
                            and float(self.sim.cyclist_ratio) > 0.0
                            and self.sim._is_rightmost_lane(lane_id)
                        ),
                        (lane_id, point_index),
                        closing_rate,
                    )
                )
        self.sim.mixed_rng.shuffle(candidates)
        cyclist_spawns = min(spawn_budget, cyclist_deficit)
        remaining = spawn_budget - cyclist_spawns
        inner_spawns = min(remaining, motorized_60_deficit)
        remaining -= inner_spawns
        middle_spawns = min(remaining, max(0, motorized_120_deficit - inner_spawns))
        inner_spawn_distance = (
            50.0
            if force_initial
            else max(spawn_visibility_guard_m, 110.0)
        )
        outer_spawn_distance = (
            90.0
            if force_initial
            else max(spawn_visibility_guard_m + 25.0, 140.0)
        )
        spawn_plan: list[tuple[float, bool]] = [
            *((outer_spawn_distance, False) for _ in range(cyclist_spawns)),
            *((inner_spawn_distance, True) for _ in range(inner_spawns)),
            *((outer_spawn_distance, True) for _ in range(middle_spawns)),
            *((outer_spawn_distance, False) for _ in range(remaining - middle_spawns)),
        ]

        spawned = 0
        spawned_cyclists = 0
        spawned_motorized = 0
        spawned_inner_motorized = 0
        spawned_middle_motorized = 0
        used_candidates: set[tuple[Any, int]] = set()
        for preferred_distance, force_motorized in spawn_plan:
            prioritize_closing = bool(
                allow_dense_reserve
                and self.world_local_target_count >= 10
                and force_motorized
                and preferred_distance <= inner_spawn_distance + 1e-6
            )
            ordered_candidates = sorted(
                candidates,
                key=lambda item: (
                    1 if not force_motorized and cyclist_deficit > spawned_cyclists and not item[3] else 0,
                    (
                        max(0.0, item[0] - 60.0) / item[5]
                        if prioritize_closing and item[5] > 0.1
                        else (math.inf if prioritize_closing else 0.0)
                    ),
                    abs(item[0] - preferred_distance),
                ),
            )
            for (
                _,
                lane_id,
                longitudinal,
                rightmost,
                candidate_key,
                _closing_rate,
            ) in ordered_candidates:
                if candidate_key in used_candidates:
                    continue
                cyclist = bool(
                    not force_motorized
                    and self.sim.mixed_traffic_enabled
                    and rightmost
                    and spawned_cyclists < cyclist_deficit
                )
                speed = float(
                    self.sim.mixed_rng.uniform(3.0, 5.0)
                    if cyclist
                    else self.sim.mixed_rng.uniform(6.0, 10.0)
                )
                if not self.sim._spawn_actor_on_lane(
                    lane_id,
                    cyclist=cyclist,
                    init_step=self.sim.history_step,
                    speed=speed,
                    longitudinal=longitudinal,
                ):
                    continue
                used_candidates.add(candidate_key)
                spawned += 1
                if cyclist:
                    spawned_cyclists += 1
                else:
                    spawned_motorized += 1
                    if preferred_distance <= 60.0:
                        spawned_inner_motorized += 1
                    elif preferred_distance <= 120.0:
                        spawned_middle_motorized += 1
                break
        refreshed_vehicles = _actor_dicts_from_simulator(self.sim)
        if refreshed_vehicles:
            (
                local_road_users,
                local_cyclists,
                local_motorized,
                local_motorized_60,
                local_motorized_120,
            ) = local_snapshot(refreshed_vehicles)
            status_local_count = len(local_road_users)
            status_cyclist_count = len(local_cyclists)
            status_motorized_count = len(local_motorized)
            status_motorized_60_count = len(local_motorized_60)
            status_motorized_120_count = len(local_motorized_120)
        else:
            status_local_count = len(local_road_users) + spawned
            status_cyclist_count = len(local_cyclists) + spawned_cyclists
            status_motorized_count = len(local_motorized) + spawned_motorized
            status_motorized_60_count = len(local_motorized_60) + spawned_inner_motorized
            status_motorized_120_count = (
                len(local_motorized_120)
                + spawned_inner_motorized
                + spawned_middle_motorized
            )
        self.viewer.set_status_fields(
            {
                "world_region_center": [round(float(center[0]), 3), round(float(center[1]), 3)],
                "world_local_vehicle_count": status_local_count,
                "world_local_target_count": self.world_local_target_count,
                "world_local_motorized_count": status_motorized_count,
                "world_local_motorized_60m_count": status_motorized_60_count,
                "world_local_motorized_60m_target": motorized_60_target,
                "world_local_motorized_120m_count": status_motorized_120_count,
                "world_local_motorized_120m_target": motorized_120_target,
                "world_local_cyclist_count": status_cyclist_count,
                "world_local_cyclist_target_count": cyclist_target,
                "world_local_spawned": spawned,
                "world_local_replaced": replaced,
                "world_local_replaced_total": int(
                    getattr(self, "world_local_replaced_agents", 0)
                ),
                "world_local_counts_exclude_av": True,
                "world_local_flow_sim_time": round(display_step * self.step_seconds, 3),
                "world_local_arrival_rate": round(local_rate, 4),
                "world_pruned_outside_agents": pruned_outside,
            }
        )
        return spawned

    def _prune_rule_vehicles_at_route_end(self, vehicles: list[dict]) -> list[dict]:
        """Remove spent background routes before stopped actors stack at an endpoint."""
        if self.traffic_controller != "idm_mobil" or not vehicles:
            return vehicles
        focus_id = self.av_id if self.av_id is not None else self.world_ego_id
        mapping = getattr(self.sim.agent_record, "_id_agent_mapping", {}) or {}
        removable: list[Any] = []
        for vehicle in vehicles:
            vehicle_id = vehicle.get("id")
            if str(vehicle_id) == str(focus_id):
                continue
            actor_type = str(
                vehicle.get("road_user_type") or vehicle.get("type") or "vehicle"
            ).lower()
            if actor_type in {"pedestrian", "cyclist", "non_motorized"} or bool(
                vehicle.get("static")
            ):
                continue
            speed = float(vehicle.get("speed", 0.0) or 0.0)
            if speed > 0.75:
                continue
            actor_key = _matching_mapping_key(mapping, vehicle_id)
            agent = mapping.get(actor_key) if actor_key is not None else None
            if not list(getattr(agent, "route", []) or []):
                continue
            report = _route_visibility_report(
                self.sim.map,
                self.sim.agent_record,
                vehicle,
            )
            remaining_route_m = float(report.get("remaining_route_m", 0.0) or 0.0)
            vehicle_length = max(1.0, float(vehicle.get("length", 4.5) or 4.5))
            if remaining_route_m > max(1.0, 0.25 * vehicle_length):
                continue
            removable.append(actor_key)

        removed = 0
        for vehicle_id in removable:
            if vehicle_id not in getattr(
                self.sim.agent_record, "_id_agent_mapping", {}
            ):
                continue
            self.sim.remove_vehicle(vehicle_id)
            removed += 1
        if not removed:
            return vehicles
        self.world_pruned_route_end_agents += removed
        self.viewer.set_status_fields(
            {
                "world_pruned_route_end_agents": self.world_pruned_route_end_agents,
            }
        )
        return _actor_dicts_from_simulator(self.sim)

    def _ensure_next_tracked_states(self, required_steps: int = 1) -> dict[str, Any]:
        """Prevent exhausted controller tracks from crashing CityNDE's next step."""
        record = self.sim.agent_record
        current_step = int(record.current_step)
        required_steps = max(1, int(required_steps))
        future_schedule = list(record._agents_id_future_step[:required_steps])
        exhausted = []
        for agent_id in list(record.current_track_agent_ids):
            agent = record.get_agents(agent_id)
            if agent is None:
                continue
            has_full_rollout = len(future_schedule) == required_steps and all(
                agent_id in future_ids for future_ids in future_schedule
            )
            if not has_full_rollout:
                exhausted.append(agent_id)

        av_fallback = False
        active_av_id = self._active_vehicle_id(self.av_id) if self.av_id is not None else None
        if active_av_id in exhausted:
            agent = record.get_agents(active_av_id)
            relative_step = current_step - int(getattr(agent, "spawn_time_step", current_step))
            state_index = min(max(0, relative_step), len(agent.states) - 1)
            state = np.asarray(agent.states[state_index], dtype=float).copy()
            fallback_states = []
            for _ in range(required_steps):
                state = state.copy()
                state[0] += float(state[3]) * self.step_seconds
                state[1] += float(state[4]) * self.step_seconds
                fallback_states.append(state)
            record.update(active_av_id, np.asarray(fallback_states), proceed=False)
            exhausted.remove(active_av_id)
            av_fallback = True
            self.av_fallback_extrapolation_count += 1

        world_fallback = False
        active_world_id = (
            self._active_vehicle_id(self.world_ego_id)
            if getattr(self, "world_loop_ego", False)
            and getattr(self, "world_ego_id", None) is not None
            else None
        )
        if active_world_id in exhausted:
            agent = record.get_agents(active_world_id)
            relative_step = current_step - int(getattr(agent, "spawn_time_step", current_step))
            state_index = min(max(0, relative_step), len(agent.states) - 1)
            state = np.asarray(agent.states[state_index], dtype=float).copy()
            state[3:] = 0.0
            record.update(
                active_world_id,
                np.repeat(state[None, :], required_steps, axis=0),
                proceed=False,
            )
            exhausted.remove(active_world_id)
            world_fallback = True
            self.world_loop_fallback_count = int(
                getattr(self, "world_loop_fallback_count", 0)
            ) + 1

        if exhausted:
            record.delete_id_agents(exhausted)
            self.world_pruned_exhausted_agents += len(exhausted)

        if exhausted or av_fallback or world_fallback:
            self.viewer.set_status_fields(
                {
                    "world_pruned_exhausted_agents": self.world_pruned_exhausted_agents,
                    "av_fallback_extrapolation_count": self.av_fallback_extrapolation_count,
                    "world_loop_fallback_count": int(
                        getattr(self, "world_loop_fallback_count", 0)
                    ),
                }
            )
        return {
            "pruned": exhausted,
            "av_fallback": av_fallback,
            "world_fallback": world_fallback,
        }

    def _initialize_scenario_agents(self, init_file: str | None) -> None:
        self.sim.init_scenario_agents(mode=self.args.init_mode, init_file=init_file)
        self.viewer.set_status_fields(
            {"initial_speed_summary": dict(self.sim.initial_speed_summary)}
        )
        if self.warmup_steps:
            # Standard scenarios use data initialization. They need the same
            # local-flow target and ego preparation as random initialization;
            # otherwise the legacy target of 28 is restored after the seed.
            self._prepare_denseworld_local_flow()

    def _reselect_world_ego_after_warmup(self, vehicles: list[dict]) -> None:
        if not vehicles or not self._warmup_frames:
            return
        if self.av_enabled and self.av_selection_mode == "manual" and not self.existing_seed_gate:
            return
        if self.av_enabled and self.world_initial_flow_prepared and self.av_id is not None:
            self.world_ego_id = self.av_id
            self.viewer.set_status_fields(
                {
                    "world_ego_id": str(self.av_id),
                    "camera_matches_av": True,
                    "world_ego_reselected_after_warmup": False,
                    "world_ego_locked_by_initial_flow": True,
                }
            )
            return

        # Transfer1 renders the complete warmup timeline, so changing the
        # camera ego inside that interval breaks the RGB/state boundary even
        # when the terminal actor states are identical. Prefer an actor that
        # exists for the full window. Arrival-only starts may have none, in
        # which case the final 0.5 s remains the bounded fallback.
        persistence_window = self._warmup_frames
        persistent_ids: set[str] | None = None
        for frame in persistence_window:
            participants = [frame.get("ego") or {}, *(frame.get("vehicles") or [])]
            frame_ids = {str(item.get("id")) for item in participants if item.get("id") is not None}
            persistent_ids = frame_ids if persistent_ids is None else persistent_ids & frame_ids
        if not persistent_ids:
            persistence_window = self._warmup_frames[-min(5, len(self._warmup_frames)) :]
            persistent_ids = None
            for frame in persistence_window:
                participants = [frame.get("ego") or {}, *(frame.get("vehicles") or [])]
                frame_ids = {
                    str(item.get("id"))
                    for item in participants
                    if item.get("id") is not None
                }
                persistent_ids = (
                    frame_ids
                    if persistent_ids is None
                    else persistent_ids & frame_ids
                )
        candidates = [
            item
            for item in vehicles
            if str(item.get("id")) in (persistent_ids or set())
            and str(item.get("type") or "vehicle").lower() not in {"pedestrian", "cyclist", "non_motorized"}
        ]
        if not candidates:
            candidates = [
                item
                for item in vehicles
                if str(item.get("type") or "vehicle").lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ]
        if not candidates:
            raise RuntimeError("No motorized CityNDE ego candidate exists after warmup")
        if self.world_seed_ego_id:
            selected = next(
                (item for item in candidates if str(item.get("id")) == self.world_seed_ego_id),
                None,
            )
            if selected is None:
                raise RuntimeError(
                    f"Requested world camera ego {self.world_seed_ego_id!r} is absent after warmup"
                )
            candidates = [selected]

        positions = np.asarray(
            [[float(item.get("x", 0.0)), float(item.get("y", 0.0))] for item in candidates],
            dtype=float,
        )
        signal_points = []
        for polyline in getattr(self.sim.map, "polyline_dict", {}).values():
            if int(getattr(polyline, "type", 0) or 0) != 4:
                continue
            points = np.asarray(getattr(polyline, "points", []), dtype=float)
            if points.ndim == 2 and len(points):
                signal_points.append(points[0, :2])
        signal_array = np.asarray(signal_points, dtype=float) if signal_points else np.empty((0, 2), dtype=float)

        best_index = 0
        best_score = float("-inf")
        best_context_count = 0
        best_blocking_score = 0.0
        best_loop_ready = False
        best_loop_extent_m = math.inf
        best_loop_lane_count = 0
        best_context_features: dict[str, float | int] = {}
        best_context_score = 0.0
        for index, (candidate, position) in enumerate(zip(candidates, positions)):
            heading = float(candidate.get("heading", 0.0) or 0.0)
            cosine, sine = math.cos(heading), math.sin(heading)
            relative = positions - position
            forward = relative[:, 0] * cosine + relative[:, 1] * sine
            lateral = -relative[:, 0] * sine + relative[:, 1] * cosine
            front_context_count = 0
            front_context_score = 0.0
            front_blocking_score = 0.0
            for other_index, (forward_m, lateral_m) in enumerate(zip(forward, lateral)):
                if other_index == index or forward_m <= 1.0:
                    continue
                angle = abs(math.atan2(float(lateral_m), float(forward_m)))
                if 16.0 <= forward_m <= 70.0 and angle <= math.radians(50.0):
                    front_context_count += 1
                    front_context_score += max(0.0, 1.0 - angle / math.radians(50.0))
                if forward_m >= 25.0 or angle > math.radians(55.0):
                    continue
                field_width = float(forward_m) * math.tan(math.radians(55.0)) + 1.0
                centrality = max(0.0, 1.0 - abs(float(lateral_m)) / field_width)
                front_blocking_score += max(0.0, 18.0 - float(forward_m)) * centrality
            neighbor_count = int(np.sum(np.linalg.norm(positions - position, axis=1) <= 120.0))
            signal_distance = (
                float(np.min(np.linalg.norm(signal_array - position, axis=1)))
                if len(signal_array)
                else 200.0
            )
            score = (
                neighbor_count * 10.0
                + min(4.0, front_context_score) * 300.0
                - min(signal_distance, 500.0) * 5.0
                - front_blocking_score * 120.0
            )
            context_features = _world_context_features(
                position,
                vehicles,
                self.world_crosswalk_centers,
                exclude_id=candidate.get("id"),
            )
            context_score = _world_context_score(
                self.world_context_mode,
                context_features,
            )
            score += context_score
            loop_ready = False
            loop_extent_m = math.inf
            loop_lane_count = 0
            if self.world_loop_ego:
                try:
                    current_lane, _ = self.sim.map.get_current_lane(
                        position,
                        heading,
                    )
                    reachable_prefix, reachable_cycle = find_reachable_lane_cycle(
                        self.sim.map,
                        current_lane,
                    )
                    loop_extent_m = route_spatial_extent(
                        self.sim.map,
                        [*reachable_prefix, *reachable_cycle],
                        [float(position[0]), float(position[1])],
                    )
                    loop_ready = bool(reachable_cycle)
                    loop_lane_count = len(reachable_prefix) + len(reachable_cycle)
                except (AttributeError, TypeError, ValueError):
                    loop_ready = False
                score += (
                    1000000.0
                    - _world_loop_compactness_penalty(
                        loop_extent_m,
                        loop_lane_count,
                    )
                    if loop_ready
                    else -1000000.0
                )
            if score > best_score:
                best_index = index
                best_score = score
                best_context_count = front_context_count
                best_blocking_score = front_blocking_score
                best_loop_ready = loop_ready
                best_loop_extent_m = loop_extent_m
                best_loop_lane_count = loop_lane_count
                best_context_features = context_features
                best_context_score = context_score

        if self.world_loop_ego and not best_loop_ready:
            raise RuntimeError(
                "No CityNDE ego candidate has a reachable directed lane cycle"
            )

        selected_id = candidates[best_index].get("id")
        self.world_ego_id = selected_id
        selected_position = positions[best_index]
        self.world_region_center = (
            float(selected_position[0]),
            float(selected_position[1]),
        )
        self.world_loop_route_prefix = []
        self.world_loop_route_cycle = []
        if self.av_enabled:
            active_id = self._active_vehicle_id(selected_id)
            if active_id is not None:
                self.av_id = active_id

        for frame in self._warmup_frames:
            participants = [dict(frame.get("ego") or {}), *(dict(item) for item in frame.get("vehicles") or [])]
            selected = next((item for item in participants if str(item.get("id")) == str(selected_id)), None)
            if selected is None:
                continue
            actors = []
            for item in participants:
                item.pop("is_av", None)
                if item.get("type") == "av":
                    item["type"] = "car"
                if str(item.get("id")) != str(selected_id):
                    actors.append(item)
            if self.av_enabled:
                selected["type"] = "av"
                selected["is_av"] = True
            frame["ego"] = selected
            frame["vehicles"] = actors

        self.viewer.set_status_fields(
            {
                "world_ego_id": str(selected_id),
                "av_id": str(self.av_id) if self.av_id is not None else "",
                "camera_matches_av": self.av_id is not None and str(self.av_id) == str(selected_id),
                "world_front_context_count": best_context_count,
                "world_front_blocking_score": round(best_blocking_score, 3),
                "world_ego_reselected_after_warmup": True,
                "world_loop_candidate_ready": best_loop_ready,
                "world_loop_candidate_extent_m": round(best_loop_extent_m, 3),
                "world_loop_candidate_lane_count": best_loop_lane_count,
                "world_region_center": [
                    round(float(selected_position[0]), 3),
                    round(float(selected_position[1]), 3),
                ],
                "world_context_mode": self.world_context_mode,
                "world_context_features": _finite_context_features(best_context_features),
                "world_context_score": round(best_context_score, 3),
                "world_ego_persistence_window_frames": len(persistence_window),
            }
        )
        self._pin_world_ego_route(vehicles)

    def _enter_world_seed_pending(self, vehicles: list[dict]) -> None:
        self._reselect_world_ego_after_warmup(vehicles)
        self.recording_operational_start_step = max(
            0, len(self.sim.agent_record) - 1
        )
        self.sim.save_to(str(self.warmup_save_file))
        self.warmup_frames_file.write_text(
            json.dumps(self._warmup_frames, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.world_seed_pending = True
        self.world_seed_alignment_prepared = False
        # Operational display time restarts at zero after the seed boundary.
        # Keep the replenishment scheduler on that same clock.
        self.world_last_flow_update_step = 0
        self.paused = True
        self.viewer.set_sim_state_latest(
            {
                "backend_model": self.backend_model,
                "step": 0,
                "sim_time": 0.0,
                "raw_sim_time": self.warmup_steps * self.step_seconds,
                "vehicles": self._mark_av(vehicles),
                "traffic_lights": _traffic_lights_from_map(self.sim.map),
            }
        )
        self.viewer.set_status_fields(
            {
                "run_state": "world_seed_pending",
                "paused": True,
                "step": 0,
                "sim_time": 0.0,
                "raw_sim_time": self.warmup_steps * self.step_seconds,
                "progress": 0.0,
                "world_seed_pending": True,
                "world_seed_alignment_mode": self.world_seed_alignment_mode,
                "world_seed_alignment_prepared": False,
                "warmup_frames": len(self._warmup_frames),
                "warmup_save_file": str(self.warmup_save_file),
                "warmup_frames_file": str(self.warmup_frames_file),
                "world_spawn_visibility_guard_m": self.world_spawn_visibility_guard_m,
            }
        )

    def _capture_world_opening_snapshot(self) -> None:
        """Retain the exact simulator state represented by Transfer frame zero."""
        self._world_opening_snapshot = copy.deepcopy(self.sim.export(sparse=True))
        self._world_opening_routes = {}
        for actor_id in list(self.sim.agent_record.current_track_agent_ids):
            actor = self.sim.agent_record.get_agents(actor_id)
            route = list(getattr(actor, "route", []) or []) if actor is not None else []
            if route:
                self._world_opening_routes[str(actor_id)] = copy.deepcopy(route)
        rng_state: dict[str, Any] = {
            "python": random.getstate(),
            "numpy": np.random.get_state(),
        }
        mixed_rng = getattr(self.sim, "mixed_rng", None)
        if mixed_rng is not None:
            rng_state["mixed"] = copy.deepcopy(mixed_rng.bit_generator.state)
        self._world_opening_rng_state = rng_state

    def _restore_world_opening_snapshot(self) -> int:
        if self._world_opening_snapshot is None:
            raise RuntimeError("The traffic opening state was not captured before warmup")
        snapshot = copy.deepcopy(self._world_opening_snapshot)
        # CityNDE's sparse exporter emits a plain [] for an empty actor frame,
        # while sparse2dense requires every state frame to expose ``shape``.
        # This is common on unsignalized maps, where all traffic-light frames
        # are empty, and must be normalized before restoring the opening state.
        for key, state_width in (
            ("vehicle_state_per_step", 7),
            ("dynamic_polyline_state_per_step", 4),
        ):
            values = snapshot.get(key)
            if not isinstance(values, list):
                continue
            normalized_values = []
            for value in values:
                array = np.asarray(value, dtype=np.float64)
                normalized_values.append(
                    array.reshape(-1, state_width)
                    if array.size
                    else np.empty((0, state_width), dtype=np.float64)
                )
            snapshot[key] = normalized_values
        self.sim.reset()
        if hasattr(self.sim, "pedestrians"):
            self.sim.pedestrians.clear()
        if hasattr(self.sim, "_pedestrian_history"):
            self.sim._pedestrian_history.clear()
        if hasattr(self.sim, "_restored_profile_ids"):
            self.sim._restored_profile_ids.clear()
        preserve_loaded_state = bool(getattr(self.sim, "preserve_loaded_state", False))
        self.sim.preserve_loaded_state = True
        try:
            self.sim.init_scenario_agents(
                mode="data",
                init_dict=snapshot,
                sparse=True,
                proceed=True,
            )
        finally:
            self.sim.preserve_loaded_state = preserve_loaded_state
        self.sim.synchronize()
        restored_routes = 0
        for actor_id, route in self._world_opening_routes.items():
            active_id = self._active_vehicle_id(actor_id)
            actor = (
                self.sim.agent_record.get_agents(active_id)
                if active_id is not None
                else None
            )
            if actor is None or not hasattr(actor, "assign_route"):
                continue
            actor.assign_route(copy.deepcopy(route))
            restored_routes += 1
        if hasattr(self.controller, "reset"):
            self.controller.reset()
        self.controller.agent_enhance = self.sim.agent_record
        self.controller.set_external_av_trajectory()
        rng_state = self._world_opening_rng_state
        if rng_state.get("python") is not None:
            random.setstate(rng_state["python"])
        if rng_state.get("numpy") is not None:
            np.random.set_state(rng_state["numpy"])
        mixed_rng = getattr(self.sim, "mixed_rng", None)
        if mixed_rng is not None and rng_state.get("mixed") is not None:
            mixed_rng.bit_generator.state = copy.deepcopy(rng_state["mixed"])
        self.recording_operational_start_step = max(
            0, len(self.sim.agent_record) - 1
        )
        self.world_last_flow_update_step = -1
        return restored_routes

    def _prepare_world_seed_alignment(self, mode: str) -> dict[str, Any]:
        if not self.world_seed_pending:
            raise RuntimeError("No world seed is pending")
        normalized = normalize_seed_alignment_mode(mode)
        restored_routes = 0
        if normalized == SEED_ALIGNMENT_OPENING_RESTART:
            restored_routes = self._restore_world_opening_snapshot()
            expected = self._warmup_frames[0]
        else:
            expected = self._warmup_frames[-1]
        vehicles = self._mark_av(_actor_dicts_from_simulator(self.sim))
        actual = self._warmup_frame(
            0
            if normalized == SEED_ALIGNMENT_OPENING_RESTART
            else self.warmup_steps,
            vehicles,
        )
        audit = audit_seed_traffic_boundary(
            expected,
            actual,
            alignment_mode=normalized,
        )
        if not audit["passed"]:
            raise RuntimeError(
                "Traffic state does not match the selected Transfer seed boundary: "
                f"missing={audit['missing_actor_ids']}, "
                f"unexpected={audit['unexpected_actor_ids']}, "
                f"violations={len(audit['violations'])}"
            )
        self.world_seed_alignment_mode = normalized
        self.world_seed_alignment_prepared = True
        self.viewer.set_sim_state_latest(
            {
                "backend_model": self.backend_model,
                "step": 0,
                "sim_time": 0.0,
                "raw_sim_time": (
                    0.0
                    if normalized == SEED_ALIGNMENT_OPENING_RESTART
                    else self.warmup_steps * self.step_seconds
                ),
                "vehicles": vehicles,
                "traffic_lights": _traffic_lights_from_map(self.sim.map),
            }
        )
        self.viewer.set_status_fields(
            {
                "world_seed_alignment_mode": normalized,
                "world_seed_alignment_prepared": True,
                "world_seed_alignment_audit": audit,
                "world_opening_routes_restored": (
                    restored_routes
                    if normalized == SEED_ALIGNMENT_OPENING_RESTART
                    else 0
                ),
            }
        )
        return audit

    def _prune_existing_seed_traffic(self, vehicles: list[dict]) -> list[dict]:
        """Apply the configured local vehicle limit before exporting the world seed."""
        limit = self.world_initial_vehicle_limit
        if self.world_requested_local_target_count > 0:
            # Existing-seed startup bypasses _prepare_denseworld_local_flow,
            # where this effective target is normally initialized. Without
            # this assignment the replenisher silently restores its legacy
            # target of 28 immediately after pruning the seed to a sparse set.
            self.world_local_target_count = self.world_requested_local_target_count
        traffic_vehicles = [
            item
            for item in vehicles
            if str(item.get("road_user_type") or item.get("type") or "vehicle").lower()
            != "pedestrian"
        ]
        if limit <= 0 or len(traffic_vehicles) <= limit:
            return vehicles

        focus_id = self.world_ego_id or self.world_seed_ego_id
        focus = next(
            (item for item in traffic_vehicles if str(item.get("id")) == str(focus_id)),
            None,
        )
        if focus is None:
            return vehicles

        center = np.asarray(
            [float(focus.get("x", 0.0)), float(focus.get("y", 0.0))],
            dtype=float,
        )
        ranked = sorted(
            traffic_vehicles,
            key=lambda item: (
                0 if str(item.get("id")) == str(focus_id) else 1,
                float(
                    np.linalg.norm(
                        np.asarray(
                            [float(item.get("x", 0.0)), float(item.get("y", 0.0))],
                            dtype=float,
                        )
                        - center
                    )
                ),
                str(item.get("id")),
            ),
        )
        keep_ids = {str(item.get("id")) for item in ranked[:limit]}
        removed = 0
        for item in traffic_vehicles:
            if str(item.get("id")) in keep_ids:
                continue
            vehicle_id = item.get("id")
            if hasattr(self.sim, "_normalize_vehicle_id"):
                vehicle_id = self.sim._normalize_vehicle_id(vehicle_id)
            self.sim.remove_vehicle(vehicle_id)
            removed += 1

        for lane_id in getattr(self.sim.map, "start_lane", []) or []:
            self.sim.lane_arrival_rates[lane_id] = 0.0

        self.world_region_center = (float(center[0]), float(center[1]))
        self.world_initial_flow_prepared = True
        self.viewer.set_status_fields(
            {
                "world_initial_vehicle_limit": limit,
                "world_initial_vehicle_count": len(traffic_vehicles),
                "world_initial_vehicle_kept": len(keep_ids),
                "world_initial_vehicle_removed": removed,
                "world_initial_seed_pruned": True,
                "world_local_target_count": self.world_local_target_count,
            }
        )
        return _actor_dicts_from_simulator(self.sim)

    def _publish(
        self,
        display_step: int,
        vehicles: list[dict] | None = None,
        traffic_metrics: dict[str, Any] | None = None,
    ):
        if vehicles is None:
            vehicles = _actor_dicts_from_simulator(self.sim)
        vehicles = self._mark_av(vehicles)
        self._record_av_state(vehicles, display_step)
        if traffic_metrics is None:
            traffic_metrics = self._append_metrics(display_step, vehicles)
        sim_time = (
            max(0, display_step)
            if self.run_until_stopped
            else min(max(0, display_step), self.total_step)
        ) * self.step_seconds
        raw_sim_time = (max(0, display_step) + self.warmup_steps) * self.step_seconds
        progress = (
            0.0
            if self.run_until_stopped
            else min(1.0, max(0.0, display_step / max(self.total_step, 1)))
        )
        self._last_vehicles = vehicles
        self._last_traffic_metrics = traffic_metrics
        self._last_published_step = int(display_step)
        self.viewer.set_sim_state_latest(
            {
                "backend_model": self.backend_model,
                "step": int(display_step),
                "sim_time": sim_time,
                "raw_sim_time": raw_sim_time,
                "vehicles": vehicles,
                "traffic_lights": _traffic_lights_from_map(self.sim.map),
            }
        )
        self.viewer.set_status_fields(
            {
                "run_state": "completed" if self.completed else "running",
                "paused": self.paused,
                "step": int(display_step),
                "vehicles": int(traffic_metrics["motorized_count"] + traffic_metrics["cyclist_count"]),
                "road_users": len(vehicles),
                "motorized_count": int(traffic_metrics["motorized_count"]),
                "cyclist_count": int(traffic_metrics["cyclist_count"]),
                "pedestrian_count": int(traffic_metrics["pedestrian_count"]),
                "sim_time": sim_time,
                "raw_sim_time": raw_sim_time,
                "progress": 1.0 if self.completed else progress,
                "avg_speed": traffic_metrics["avg_speed"],
                "avg_ttc": traffic_metrics["avg_ttc"],
                "avg_headway": traffic_metrics["avg_headway"],
                "collision_count": traffic_metrics["collision_count"],
                "av_avg_ttc": traffic_metrics.get("av_avg_ttc"),
                "av_min_ttc": traffic_metrics.get("av_min_ttc"),
                "av_avg_headway": traffic_metrics.get("av_avg_headway"),
                "av_collision_count": traffic_metrics.get("av_collision_count"),
                "av_ttc_samples": traffic_metrics.get("av_ttc_samples", [])[:96],
                "av_headway_samples": traffic_metrics.get("av_headway_samples", [])[:96],
                "speed_samples": traffic_metrics["speeds"][:96],
                "ttc_samples": traffic_metrics["ttc_samples"][:96],
                "headway_samples": traffic_metrics["headway_samples"][:96],
                "arrival_rate": self._arrival_rate(),
                "safety_computed": True,
                "pedestrian_conflicts": int(getattr(self.controller, "pedestrian_conflict_count", 0)),
                "pedestrian_safety_corrections": int(
                    getattr(self.controller, "pedestrian_correction_count", 0)
                ),
                "cyclist_crosswalk_corrections": int(
                    getattr(self.sim, "cyclist_crosswalk_corrections", 0)
                ),
                "cyclist_signal_stops": int(getattr(self.sim, "cyclist_signal_stops", 0)),
                "cyclist_pedestrian_conflicts": int(
                    getattr(self.sim, "cyclist_pedestrian_conflicts", 0)
                ),
                "cyclist_pedestrian_yields": int(
                    getattr(self.sim, "cyclist_pedestrian_yields", 0)
                ),
                "cyclist_av_conflicts": int(getattr(self.sim, "cyclist_av_conflicts", 0)),
                "cyclist_av_yields": int(getattr(self.sim, "cyclist_av_yields", 0)),
            }
        )

    def _handle_action(self, action: dict):
        sync_id = action.get("_sync_id")
        act_type = str(action.get("type", "")).strip().lower()
        result = {"ok": True}
        try:
            if act_type == "terminate_experiment":
                if not self.completed and bool(action.get("save_data", True)):
                    self._save_scenario()
                self.completed = True
                self.run_stop_requested = True
                self.termination_reason = self.termination_reason or "user_terminated"
                self.paused = False
                self.viewer.set_status_fields(
                    {
                        "run_state": "completed",
                        "paused": False,
                        "experiment_completed": True,
                        "progress": 1.0,
                        "save_file": _display_path(self.save_file, self.citynde_root),
                    }
                )
                result = {"ok": True, "message": "Experiment terminated", "run_state": "completed"}
            elif act_type == "set_rate":
                if self.sim is None:
                    raise RuntimeError("Experiment already completed")
                lane_id = action.get("lane_id", "all")
                prob = max(0.0, min(1.0, float(action.get("prob", self._arrival_rate()))))
                if isinstance(lane_id, str) and lane_id.strip().lower() == "all":
                    self.sim.default_arrival_rate = prob
                    for start_lane in getattr(self.sim.map, "start_lane", []) or []:
                        self.sim.lane_arrival_rates[start_lane] = prob
                else:
                    actual = next((x for x in self.sim.map.start_lane if str(x) == str(lane_id)), lane_id)
                    self.sim.lane_arrival_rates[actual] = prob
                self.viewer.set_status_fields({"arrival_rate": self._arrival_rate()})
                result = {"ok": True, "message": "Arrival rate updated"}
            elif act_type == "select_av":
                result = self._select_av(action.get("vehicle_id"))
            elif act_type == "random_select_av":
                result = self._random_select_av()
            elif act_type == "world_seed_ready":
                if not self.world_seed_pending:
                    raise RuntimeError("No world seed is pending")
                if not self.world_seed_alignment_prepared:
                    self._prepare_world_seed_alignment(
                        SEED_ALIGNMENT_TERMINAL_CONTINUE
                    )
                self.world_seed_frame = str(action.get("frame") or "").strip()
                self.world_seed_pending = False
                self.paused = False
                operational_vehicles = self._mark_av(_actor_dicts_from_simulator(self.sim))
                self.av_start_state = {}
                self.av_end_state = {}
                self._record_av_state(operational_vehicles, 0)
                self.viewer.set_status_fields(
                    {
                        "run_state": "running",
                        "paused": False,
                        "world_seed_pending": False,
                        "world_seed_alignment_mode": self.world_seed_alignment_mode,
                        "world_seed_alignment_prepared": True,
                        "world_seed_video": str(action.get("video") or ""),
                        "world_seed_frame": str(action.get("frame") or ""),
                        "operational_started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                result = {
                    "ok": True,
                    "message": "World seed accepted",
                    "run_state": "running",
                    "av_id": "" if self.av_id is None else str(self.av_id),
                    "world_seed_alignment_mode": self.world_seed_alignment_mode,
                }
            elif act_type == "world_seed_align":
                audit = self._prepare_world_seed_alignment(
                    str(action.get("mode") or SEED_ALIGNMENT_TERMINAL_CONTINUE)
                )
                result = {
                    "ok": True,
                    "message": "World seed traffic boundary aligned",
                    "run_state": "world_seed_pending",
                    "world_seed_alignment_mode": self.world_seed_alignment_mode,
                    "audit": audit,
                }
            elif act_type == "add_vehicle_manual":
                if self.sim is None:
                    raise RuntimeError("Experiment already completed")
                x = float(action.get("x"))
                y = float(action.get("y"))
                heading = float(action.get("heading"))
                speed = max(0.0, float(action.get("speed", self.args.default_spawn_speed or 2.0)))
                self.sim.add_vehicle(
                    x=x,
                    y=y,
                    heading=heading,
                    vx=speed * math.cos(heading),
                    vy=speed * math.sin(heading),
                    static=str(action.get("spawn_mode", "moving")).lower() == "static",
                )
                result = {"ok": True, "message": "Vehicle added"}
            elif act_type == "remove_vehicle":
                if self.sim is None:
                    raise RuntimeError("Experiment already completed")
                vid_raw = action.get("vehicle_id")
                vid = self.sim._normalize_vehicle_id(vid_raw) if hasattr(self.sim, "_normalize_vehicle_id") else vid_raw
                self.sim.remove_vehicle(vid)
                result = {"ok": True, "message": "Vehicle removed"}
            elif act_type in {"toggle_vehicle_id", "set_infeasible_region", "clear_infeasible_region", "clear_infeasible_regions", "refresh_scenarios", "start_experiment"}:
                result = {"ok": True, "message": "Accepted"}
            else:
                result = {"ok": False, "error": f"Unsupported CityNDE action: {act_type}"}
        except Exception as exc:
            self._set_error(str(exc))
            result = {"ok": False, "error": str(exc)}
        self.viewer.set_action_result(sync_id, result)

    def _handle_pending_actions(self):
        while True:
            action = self.viewer.pop_action()
            if action is None:
                break
            self._handle_action(action)
        if self.viewer.pause_requested:
            self.paused = True
            self.viewer.set_status_fields({"paused": True, "pause_pending": False})
        if self.viewer.resume_requested and not self.world_seed_pending:
            self.paused = False
            self.viewer.set_status_fields({"paused": False, "pause_pending": False})
        self._handle_remote_command()

    def _wait_for_world_video_demand(self, next_display_step: int) -> bool:
        if self.world_sync_state is None or self.world_seed_pending:
            return True
        from backend.cosmos.world_sync import traffic_step_permitted

        next_sim_time = max(0, int(next_display_step)) * self.step_seconds
        while not self.stop_requested and not self.run_stop_requested:
            self._handle_pending_actions()
            permitted, sync_state = traffic_step_permitted(
                self.world_sync_state,
                next_sim_time,
            )
            if permitted and not self.paused:
                if self.world_sync_waiting:
                    self.world_sync_waiting = False
                    self.viewer.set_status_fields({"world_sync_waiting": False})
                return True
            self.world_sync_waiting = not self.paused
            self.viewer.set_status_fields(
                {
                    "world_sync_waiting": self.world_sync_waiting,
                    "world_sync_requested_time": float(
                        sync_state.get("requested_traffic_time", 0.0) or 0.0
                    ),
                    "world_sync_generated_video_time": float(
                        sync_state.get("generated_video_time", 0.0) or 0.0
                    ),
                    "world_sync_next_sim_time": next_sim_time,
                }
            )
            time.sleep(0.02)
        return False

    def run(self):
        def _stop(signum, frame):
            self.stop_requested = True
            self.termination_reason = self.termination_reason or "process_signal"

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        init_file = self.args.init_file.strip() or None
        if init_file:
            init_file = str(_resolve_citynde_path(init_file, self.citynde_root))
        self.save_file.parent.mkdir(parents=True, exist_ok=True)
        display_step = 0
        raw_step = 0
        rollout_remaining = 0
        try:
            if self.args.init_mode != "none":
                self.profiler.timed(
                    "init_scenario_agents",
                    lambda: self._initialize_scenario_agents(init_file),
                )
            current_vehicles = _actor_dicts_from_simulator(self.sim)
            self.recording_operational_start_step = max(
                0, len(self.sim.agent_record) - 1
            )
            if self.existing_seed_gate:
                self._warmup_frames = [self._warmup_frame(0, current_vehicles)]
                self._reselect_world_ego_after_warmup(current_vehicles)
                current_vehicles = self._prune_existing_seed_traffic(current_vehicles)
                self._warmup_frames = [self._warmup_frame(0, current_vehicles)]
                self._enter_world_seed_pending(current_vehicles)
                while (
                    self.world_seed_pending
                    and not self.stop_requested
                    and not self.run_stop_requested
                ):
                    self._handle_pending_actions()
                    time.sleep(0.1)
                current_vehicles = _actor_dicts_from_simulator(self.sim)
            elif self.warmup_steps:
                if self.av_enabled:
                    if self.av_selection_mode == "manual":
                        self._prepare_av_selection(current_vehicles)
                    elif self.world_ego_id is not None:
                        self._select_av(self.world_ego_id)
                    else:
                        self._prepare_av_selection(current_vehicles)
                for _attempt in range(6):
                    spawned = self._maintain_denseworld_local_flow(
                        self._mark_av(current_vehicles),
                        display_step=0,
                        next_prediction_due=True,
                        force_initial=True,
                        allow_dense_reserve=False,
                    )
                    current_vehicles = _actor_dicts_from_simulator(self.sim)
                    if spawned <= 0:
                        break
                self.world_initial_flow_prepared = self.world_ego_id is not None
                if self.av_enabled:
                    self._publish(0, self._mark_av(current_vehicles))
                self._capture_world_opening_snapshot()
                self._warmup_frames = [self._warmup_frame(0, current_vehicles)]
                self.viewer.set_status_fields({"run_state": "warming_up", "raw_sim_time": 0.0})
            else:
                self._prepare_av_selection(current_vehicles)
                self._publish(0, self._mark_av(current_vehicles))

            step_indices = (
                itertools.count()
                if self.run_until_stopped
                else range(self.total_step + self.warmup_steps)
            )
            for idx in step_indices:
                self._handle_pending_actions()
                while self.paused and not self.stop_requested and not self.run_stop_requested:
                    self._handle_pending_actions()
                    time.sleep(0.1)
                if self.stop_requested or self.run_stop_requested:
                    break
                if raw_step >= self.warmup_steps and not self._wait_for_world_video_demand(
                    display_step + 1
                ):
                    break
                vehicles_before = len(self.sim.agent_record.get_valid_agent_ids(timestep=-1)) if self.profiler.enabled else 0
                operation_step_before = max(0, raw_step - self.warmup_steps)
                self.profiler.begin_step(operation_step_before + 1, vehicles_before)
                current_vehicles = _actor_dicts_from_simulator(self.sim)
                if raw_step >= self.warmup_steps:
                    self._prepare_av_selection(current_vehicles)
                if self.paused:
                    self._publish(display_step, self._mark_av(current_vehicles))
                    while self.paused and not self.stop_requested and not self.run_stop_requested:
                        self._handle_pending_actions()
                        time.sleep(0.1)
                    if self.stop_requested or self.run_stop_requested:
                        break
                    current_vehicles = _actor_dicts_from_simulator(self.sim)
                if self.av_id is not None and self._active_vehicle_id(self.av_id) is None:
                    self._finish_with_reason("av_left_scene")
                    break

                av_trajectory = (
                    self._external_av_trajectory(operation_step_before, current_vehicles)
                    if raw_step >= self.warmup_steps
                    else None
                )
                if self.run_stop_requested:
                    break
                while self.paused and not self.stop_requested and not self.run_stop_requested:
                    self._handle_pending_actions()
                    time.sleep(0.1)

                if rollout_remaining <= 0:
                    self._pin_world_ego_route(current_vehicles)
                    recover_world_ego = self._protect_world_ego_from_anomaly_removal()
                    external_states = None
                    if av_trajectory:
                        external_states = np.array([self._state_vector(state) for state in av_trajectory], dtype=float)
                    self.controller.set_external_av_trajectory(self.av_id, external_states)
                    scenario_update = self.profiler.traced("sim_step", self.sim.step)
                    scenario_update = self.profiler.timed("external_step", lambda: self.sim.external_step(scenario_update))
                    self.controller.set_external_av_trajectory()
                    self.profiler.timed(
                        "sim_stage",
                        lambda: self.sim.scenario_manager.update_scenario(
                            scenario_update,
                            # IDM+MOBIL never creates or deletes actors. Actor
                            # lifecycle is owned by the simulator's arrival,
                            # pruning, and local-flow code, which can run
                            # between prediction boundaries. Letting the rule
                            # output modify the actor set can therefore pair a
                            # stale ID list with an already-pruned mask.
                            allow_modify_num_agents=self.traffic_controller
                            != "idm_mobil",
                            proceed=False,
                        ),
                    )
                    rollout_remaining = int(getattr(self.controller, "control_step", 5) or 5)
                    self._ensure_next_tracked_states(rollout_remaining)
                    self._constrain_world_ego_rollout(
                        rollout_remaining,
                        recover_from_anomaly=recover_world_ego,
                    )
                    self._cap_world_ego_rollout_speed(rollout_remaining)

                self._overwrite_av_next_state(av_trajectory)
                if self.av_id is not None and self.av_control_model == "IDM_MOBIL":
                    self._constrain_world_ego_rollout(1)
                self._ensure_next_tracked_states(1)
                self.sim.scenario_manager.proceed_step(1)
                self.sim.synchronize()
                if hasattr(self.sim, "advance_mixed_traffic"):
                    self.sim.advance_mixed_traffic(1)
                rollout_remaining -= 1
                raw_step = idx + 1
                display_step = max(0, raw_step - self.warmup_steps)
                current_vehicles = self._mark_av(_actor_dicts_from_simulator(self.sim))
                if rollout_remaining <= 0:
                    current_vehicles = self._mark_av(
                        self._prune_rule_vehicles_at_route_end(current_vehicles)
                    )
                if (
                    self.world_ego_id is not None
                    and not any(
                        str(vehicle.get("id")) == str(self.world_ego_id)
                        for vehicle in current_vehicles
                    )
                ):
                    self._finish_with_reason("world_ego_left_scene")
                    self.profiler.end_step(len(current_vehicles))
                    break
                if raw_step > 0:
                    spawned = self._maintain_denseworld_local_flow(
                        current_vehicles,
                        raw_step if raw_step <= self.warmup_steps else display_step,
                        next_prediction_due=rollout_remaining <= 0,
                        allow_dense_reserve=raw_step > self.warmup_steps,
                    )
                    if spawned:
                        current_vehicles = self._mark_av(_actor_dicts_from_simulator(self.sim))
                if raw_step <= self.warmup_steps:
                    self._warmup_frames.append(self._warmup_frame(raw_step, current_vehicles))
                    self.viewer.set_status_fields(
                        {
                            "run_state": "warming_up",
                            "raw_sim_time": raw_step * self.step_seconds,
                            "sim_time": 0.0,
                            "warmup_progress": raw_step / max(1, self.warmup_steps),
                        }
                    )
                    if raw_step == self.warmup_steps:
                        self._enter_world_seed_pending(current_vehicles)
                        while self.world_seed_pending and not self.stop_requested and not self.run_stop_requested:
                            self._handle_pending_actions()
                            time.sleep(0.1)
                    self.profiler.end_step(len(current_vehicles))
                    continue
                if display_step % max(1, int(self.args.save_interval or 10)) == 0:
                    self.profiler.timed("scenario_save", lambda: self.sim.save_to(str(self.save_file)))

                traffic_metrics = self.profiler.timed(
                    "metrics", lambda: self._append_metrics(display_step, current_vehicles)
                )
                if (
                    display_step % max(1, int(self.args.render_interval or 1)) == 0
                    or (not self.run_until_stopped and display_step == self.total_step)
                ):
                    self.profiler.timed(
                        "publish",
                        lambda: self._publish(display_step, current_vehicles, traffic_metrics),
                    )
                self.profiler.end_step(len(current_vehicles))
                if self.av_id is not None and not any(str(v.get("id")) == str(self.av_id) for v in current_vehicles):
                    self._finish_with_reason("av_left_scene")
                    break
                if self.av_id is not None and self._av_has_collision(current_vehicles):
                    self._finish_with_reason("av_collision")
                    break
            if not self.completed:
                self.completed = True
                self.termination_reason = self.termination_reason or (
                    "stopped" if self.run_until_stopped else "configured_steps_completed"
                )
                self._save_scenario()
                if self._last_published_step != display_step:
                    self._publish(display_step, self._last_vehicles, self._last_traffic_metrics)
                self.viewer.set_status_fields(
                    {
                        "run_state": "completed",
                        "paused": False,
                        "experiment_completed": True,
                        "progress": 1.0,
                        "save_file": _display_path(self.save_file, self.citynde_root),
                        "termination_reason": self.termination_reason,
                    }
                )
            elif self.termination_reason:
                self._save_scenario()
            scenario_update = None
            current_vehicles = None
            self._release_simulator()
            while not self.stop_requested and not self.run_stop_requested:
                self._handle_pending_actions()
                time.sleep(0.2)
        finally:
            if self.av_bridge is not None:
                self.av_bridge.close()
            self.viewer.close()


class CityNDEReplayAdapter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.citynde_root = Path(args.citynde_root).resolve()
        self.scenario_path = _resolve_citynde_path(args.scenario, self.citynde_root)
        self.step_seconds = float(args.sim_resolution or 0.1)
        self.stop_requested = False
        self.paused = False
        self.active = False
        self.client_clock = False
        self.current_step = 0
        self._metrics_generation = 0
        self._metrics_thread: threading.Thread | None = None
        self.data = self._load_scenario(self.scenario_path)
        self._bind_recording_data()
        if float(args.max_sim_time or 0.0) > 0.0:
            self.total_steps = min(
                self.total_steps,
                max(2, int(math.floor(float(args.max_sim_time) / self.step_seconds + 1e-9)) + 1),
            )
        self.experiment_params = self._experiment_params_from_data()
        self.metrics = _empty_metrics(self.total_steps, self.step_seconds)
        self.offline_av = OfflineAVController()
        self.replay_ego_id = str(
            args.world_seed_ego_id
            or self.experiment_params.get("seed_ego_id")
            or self.experiment_params.get("av_id")
            or ""
        )
        self.world_seed_pending = bool(args.denseworld_warmup)
        self.world_seed_alignment_mode = SEED_ALIGNMENT_TERMINAL_CONTINUE
        self.world_seed_alignment_prepared = False
        self.warmup_save_file = (
            _resolve_citynde_path(args.init_file, self.citynde_root)
            if str(args.init_file or "").strip()
            else self.scenario_path
        )
        sync_path = Path(args.world_sync_state).resolve() if args.world_sync_state else None
        self.warmup_frames_file = (
            sync_path.parent / "replay_warmup.json"
            if sync_path is not None
            else self.scenario_path.with_suffix(".replay_warmup.json")
        )
        self.offline_av.configure(av_id=self.replay_ego_id, start_tcp=False)
        self.viewer = HttpApiViewer(
            mode="citynde_replay",
            host=args.host,
            port=args.port,
            gui_dir=args.gui_dir,
            workspace_root=str(self.citynde_root),
        )
        self.viewer.set_status_fields(
            {
                "mode": "citynde_replay",
                "backend_model": "cnde",
                "run_state": "playback_loading",
                "replay_loading": True,
                "experiment_id": args.experiment_id or self.scenario_path.stem,
                "experiment_name": args.experiment_name or self.scenario_path.stem,
                "scenario": _display_path(self.scenario_path, self.citynde_root),
                "save_file": _display_path(self.scenario_path, self.citynde_root),
                "replay_total_steps": self.total_steps,
                "replay_step_seconds": self.step_seconds,
                "sim_resolution": self.step_seconds,
                "total_step": self.total_steps,
                "replay_ego_id": self.replay_ego_id,
                "av_id": self.replay_ego_id,
            }
        )
        map_path = str(self.experiment_params.get("map_path") or args.map_path or "assets/map/routed_map_nuplan_boston.pkl")
        map_state = self._load_map_state(map_path)
        self._map_path = map_path
        self._map_state = map_state
        self.viewer.set_map_state(map_state)
        self.viewer.set_replay_metrics(self.metrics)
        self.viewer.set_status_fields(
            {
                "mode": "citynde_replay",
                "backend_model": "cnde",
                "run_state": "playback",
                "replay_loading": False,
                "paused": False,
                "experiment_id": args.experiment_id or self.scenario_path.stem,
                "experiment_name": args.experiment_name or self.scenario_path.stem,
                "scenario": _display_path(self.scenario_path, self.citynde_root),
                "save_file": _display_path(self.scenario_path, self.citynde_root),
                "replay_params": {
                    "scenario_path": _display_path(self.scenario_path, self.citynde_root),
                    "map_path": map_state.get("map_path", map_path),
                    "gpu_id": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
                    "experiment_name": args.experiment_name or self.scenario_path.stem,
                    "arrival_rate": self.experiment_params.get("arrival_rate"),
                    "total_step": self.total_steps,
                    "sim_resolution": self.step_seconds,
                },
                "replay_total_steps": self.total_steps,
                "replay_step_seconds": self.step_seconds,
                "sim_resolution": self.step_seconds,
                "total_step": self.total_steps,
                "progress": 0.0,
                "replay_ego_id": self.replay_ego_id,
                "av_id": self.replay_ego_id,
            }
        )
        self._publish(0)
        if self.world_seed_pending:
            self._enter_world_seed_pending()
        self._start_metrics_computation()

    def _enter_world_seed_pending(self) -> None:
        warmup_frame_count = 1
        try:
            with self.warmup_save_file.open("rb") as stream:
                warmup_recording = pickle.load(stream)
            warmup_frame_count = max(
                1, len(warmup_recording.get("vehicle_id_per_step") or [])
            )
        except (OSError, TypeError, ValueError, pickle.UnpicklingError):
            pass
        vehicles = sorted(self._vehicles_at(0), key=lambda item: str(item.get("id", "")))
        ego = next(
            (dict(item) for item in vehicles if str(item.get("id")) == self.replay_ego_id),
            dict(vehicles[0]) if vehicles else {},
        )
        frame = {
            "raw_sim_time": 0.0,
            "sim_time": 0.0,
            "ego": ego,
            "vehicles": [item for item in vehicles if str(item.get("id")) != str(ego.get("id"))],
            "traffic_lights": self._traffic_lights_at(0),
        }
        self.warmup_frames_file.parent.mkdir(parents=True, exist_ok=True)
        self.warmup_frames_file.write_text(
            json.dumps([frame], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.active = False
        self.paused = True
        self.viewer.set_status_fields(
            {
                "run_state": "world_seed_pending",
                "paused": True,
                "world_seed_pending": True,
                "warmup_frames": warmup_frame_count,
                "warmup_save_file": str(self.warmup_save_file),
                "warmup_frames_file": str(self.warmup_frames_file),
                "raw_sim_time": (warmup_frame_count - 1) * self.step_seconds,
                "sim_time": 0.0,
            }
        )

    @staticmethod
    def _load_scenario(path: Path) -> dict:
        with path.open("rb") as f:
            data = pickle.load(f)
        if not isinstance(data, dict):
            raise ValueError("Scenario file must contain a dictionary")
        return data

    def _bind_recording_data(self) -> None:
        self.ids_per_step = self.data.get("vehicle_id_per_step", []) or []
        self.states_per_step = self.data.get("vehicle_state_per_step", []) or []
        self.static_attr = self.data.get("vehicle_static_attribute", {}) or {}
        self.road_user_type = self.data.get("road_user_type", {}) or {}
        self.vehicle_class = self.data.get("vehicle_class", {}) or {}
        self.pedestrian_ids_per_step = self.data.get("pedestrian_id_per_step", []) or []
        self.pedestrian_states_per_step = self.data.get("pedestrian_state_per_step", []) or []
        self.pedestrian_static_attr = self.data.get("pedestrian_static_attribute", {}) or {}
        self.pedestrian_crosswalk = self.data.get("pedestrian_crosswalk", {}) or {}
        self.total_steps = max(len(self.ids_per_step), len(self.pedestrian_ids_per_step))

    def _experiment_params_from_data(self) -> dict:
        params = self.data.get("experiment_params", {}) if isinstance(self.data.get("experiment_params", {}), dict) else {}
        if params:
            return params
        sidecar = self.scenario_path.with_suffix(self.scenario_path.suffix + ".meta.json")
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _load_map_state(self, raw_map_path: str) -> dict:
        try:
            from csim.manager import RouteTLVectorMap

            map_path = _resolve_citynde_path(raw_map_path, self.citynde_root)
            cache_path = _map_state_cache_path(map_path)
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if (
                    isinstance(cached, dict)
                    and cached.get("cache_version") == MAP_STATE_CACHE_VERSION
                    and isinstance(cached.get("map_state"), dict)
                ):
                    return cached["map_state"]
            except (OSError, ValueError):
                pass
            map_obj = RouteTLVectorMap()
            with map_path.open("rb") as f:
                map_obj.load_map(pickle.load(f))
            map_state = build_map_state(
                map_obj,
                _display_path(map_path, self.citynde_root),
            )
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "cache_version": MAP_STATE_CACHE_VERSION,
                            "map_path": str(map_path),
                            "map_state": map_state,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ),
                    encoding="utf-8",
                )
                os.replace(temporary, cache_path)
            except OSError:
                pass
            return map_state
        except Exception:
            return build_map_state(type("EmptyMap", (), {"polyline_dict": {}, "start_lane": []})(), str(raw_map_path))

    def _vehicles_at(self, step: int) -> list[dict]:
        if self.total_steps <= 0:
            return []
        idx = max(0, min(int(step), self.total_steps - 1))
        ids = self.ids_per_step[idx] if idx < len(self.ids_per_step) else []
        states = np.array(self.states_per_step[idx], dtype=float) if idx < len(self.states_per_step) else np.empty((0, 7))
        vehicles = []
        for pos, vid in enumerate(ids):
            row = np.array(states[pos], dtype=float).reshape(-1)
            static = self.static_attr.get(vid, self.static_attr.get(str(vid), [3.8, 1.8, 1.5]))
            lwh = np.array(static, dtype=float).reshape(-1)
            vx = _safe_float(row[3] if row.size > 3 else 0.0)
            vy = _safe_float(row[4] if row.size > 4 else 0.0)
            actor_type = str(self.road_user_type.get(vid, self.road_user_type.get(str(vid), "vehicle")))
            vehicles.append(
                {
                    "id": str(vid),
                    "type": actor_type,
                    "road_user_type": actor_type,
                    "vehicle_class": str(
                        self.vehicle_class.get(vid, self.vehicle_class.get(str(vid), "vehicle"))
                    ),
                    "x": _safe_float(row[0] if row.size > 0 else 0.0),
                    "y": _safe_float(row[1] if row.size > 1 else 0.0),
                    "heading": _safe_float(row[2] if row.size > 2 else 0.0),
                    "speed": math.hypot(vx, vy),
                    "length": max(0.1, _safe_float(lwh[0] if lwh.size > 0 else 3.8, 3.8)),
                    "width": max(0.1, _safe_float(lwh[1] if lwh.size > 1 else 1.8, 1.8)),
                    "height": max(0.1, _safe_float(lwh[2] if lwh.size > 2 else 1.5, 1.5)),
                    "vx": vx,
                    "vy": vy,
                    "model_controlled": True,
                    "static": False,
                    "past": [],
                    "future": [],
                }
            )
        pedestrian_ids = self.pedestrian_ids_per_step[idx] if idx < len(self.pedestrian_ids_per_step) else []
        pedestrian_states = (
            np.asarray(self.pedestrian_states_per_step[idx], dtype=float)
            if idx < len(self.pedestrian_states_per_step) and len(self.pedestrian_states_per_step[idx])
            else np.empty((0, 7), dtype=float)
        )
        for pos, pedestrian_id in enumerate(pedestrian_ids):
            if pos >= len(pedestrian_states):
                continue
            row = pedestrian_states[pos].reshape(-1)
            static = self.pedestrian_static_attr.get(
                pedestrian_id,
                self.pedestrian_static_attr.get(str(pedestrian_id), [0.55, 0.55, 1.72]),
            )
            lwh = np.asarray(static, dtype=float).reshape(-1)
            vx = _safe_float(row[3] if row.size > 3 else 0.0)
            vy = _safe_float(row[4] if row.size > 4 else 0.0)
            vehicles.append(
                {
                    "id": str(pedestrian_id),
                    "type": "pedestrian",
                    "road_user_type": "pedestrian",
                    "x": _safe_float(row[0] if row.size > 0 else 0.0),
                    "y": _safe_float(row[1] if row.size > 1 else 0.0),
                    "heading": _safe_float(row[2] if row.size > 2 else 0.0),
                    "vx": vx,
                    "vy": vy,
                    "speed": math.hypot(vx, vy),
                    "length": max(0.1, _safe_float(lwh[0] if lwh.size > 0 else 0.55, 0.55)),
                    "width": max(0.1, _safe_float(lwh[1] if lwh.size > 1 else 0.55, 0.55)),
                    "height": max(0.1, _safe_float(lwh[2] if lwh.size > 2 else 1.72, 1.72)),
                    "crosswalk_id": str(
                        self.pedestrian_crosswalk.get(
                            pedestrian_id, self.pedestrian_crosswalk.get(str(pedestrian_id), "")
                        )
                    ),
                    "model_controlled": False,
                    "static": math.hypot(vx, vy) < 0.05,
                    "past": [],
                    "future": [],
                }
            )
        return vehicles

    def _traffic_lights_at(self, step: int) -> dict[str, int]:
        ids_per_step = self.data.get("dynamic_polyline_id_per_step", [])
        states_per_step = self.data.get("dynamic_polyline_state_per_step", [])
        if not ids_per_step or not states_per_step:
            return {}
        idx = max(0, min(int(step), len(ids_per_step) - 1))
        out = {}
        for tl_id, state in zip(ids_per_step[idx], states_per_step[idx]):
            row = np.array(state, dtype=float).reshape(-1)
            if row.size >= 4:
                out[str(tl_id)] = int(np.argmax(row[:4]))
        return out

    def _compute_metrics(self) -> dict:
        metrics = _empty_metrics(self.total_steps, self.step_seconds)
        for idx in range(self.total_steps):
            self._append_metric_step(metrics, idx)
        metrics["computed_steps"] = self.total_steps
        return metrics

    def _append_metric_step(self, metrics: dict, idx: int) -> None:
        vehicles = self._vehicles_at(idx)
        traffic_metrics = _traffic_metrics(vehicles)
        av_metrics = _av_safety_metrics(vehicles)
        _set_metric(
            metrics,
            "vehicle_count_per_step",
            idx,
            int(traffic_metrics["motorized_count"] + traffic_metrics["cyclist_count"]),
            0,
        )
        _set_metric(metrics, "speed_per_step", idx, traffic_metrics["avg_speed"], None)
        _set_metric(
            metrics,
            "speed_samples_per_step",
            idx,
            [round(x, 3) for x in traffic_metrics["speeds"]],
            [],
        )
        _set_metric(metrics, "min_ttc_per_step", idx, traffic_metrics["min_ttc"], None)
        _set_metric(metrics, "headway_per_step", idx, traffic_metrics["avg_headway"], None)
        _set_metric(
            metrics,
            "collision_count_per_step",
            idx,
            traffic_metrics["collision_count"],
            None,
        )
        _set_metric(metrics, "ttc_samples_per_step", idx, traffic_metrics["ttc_samples"], [])
        _set_metric(
            metrics,
            "headway_samples_per_step",
            idx,
            traffic_metrics["headway_samples"],
            [],
        )
        _set_metric(metrics, "av_min_ttc_per_step", idx, av_metrics["av_min_ttc"], None)
        _set_metric(metrics, "av_headway_per_step", idx, av_metrics["av_avg_headway"], None)
        _set_metric(metrics, "av_collision_count_per_step", idx, av_metrics["av_collision_count"], None)
        _set_metric(metrics, "av_ttc_samples_per_step", idx, av_metrics["av_ttc_samples"], [])
        _set_metric(metrics, "av_headway_samples_per_step", idx, av_metrics["av_headway_samples"], [])
        _set_metric(
            metrics,
            "arrival_rate_per_step",
            idx,
            self.experiment_params.get("arrival_rate"),
            None,
        )

    @staticmethod
    def _metrics_snapshot(metrics: dict) -> dict:
        return {
            key: list(value) if isinstance(value, list) else value
            for key, value in metrics.items()
        }

    def _start_metrics_computation(self) -> None:
        self._metrics_generation += 1
        generation = self._metrics_generation
        metrics = _empty_metrics(self.total_steps, self.step_seconds)
        self.metrics = metrics
        self.viewer.set_replay_metrics(self._metrics_snapshot(metrics))
        self.viewer.set_status_fields(
            {
                "metrics_loading": self.total_steps > 0,
                "metrics_computed_steps": 0,
                "metrics_total_steps": self.total_steps,
            }
        )

        def worker() -> None:
            last_publish = time.monotonic()
            for idx in range(self.total_steps):
                if self.stop_requested or generation != self._metrics_generation:
                    return
                self._append_metric_step(metrics, idx)
                if self.stop_requested or generation != self._metrics_generation:
                    return
                metrics["computed_steps"] = idx + 1
                now = time.monotonic()
                if idx < 4 or idx + 1 == self.total_steps or now - last_publish >= 0.25:
                    snapshot = self._metrics_snapshot(metrics)
                    self.metrics = snapshot
                    self.viewer.set_replay_metrics(snapshot)
                    self.viewer.set_status_fields(
                        {
                            "metrics_loading": idx + 1 < self.total_steps,
                            "metrics_computed_steps": idx + 1,
                            "metrics_total_steps": self.total_steps,
                        }
                    )
                    last_publish = now
                # Keep HTTP actions and 10 Hz playback responsive while the
                # complete safety history is filled in.
                time.sleep(0.002)

        self._metrics_thread = threading.Thread(
            target=worker,
            name=f"citynde-replay-metrics-{self.args.port}",
            daemon=True,
        )
        self._metrics_thread.start()

    def _publish(self, step: int):
        if self.total_steps <= 0:
            step = 0
            vehicles = []
        else:
            step = max(0, min(int(step), self.total_steps - 1))
            vehicles = self._vehicles_at(step)
        vehicles = self.offline_av.apply(vehicles, step)
        traffic_metrics = _traffic_metrics(vehicles)
        av_metrics = _av_safety_metrics(vehicles)
        progress = (step / max(self.total_steps - 1, 1)) if self.total_steps > 1 else 1.0
        self.current_step = step
        sim_state = {
            "backend_model": "cnde",
            "step": step,
            "replay_step": step,
            "sim_time": step * self.step_seconds,
            "vehicles": vehicles,
            "traffic_lights": self._traffic_lights_at(step),
        }
        self.viewer.set_sim_state(sim_state)
        self.viewer.set_status_fields(
            {
                "run_state": (
                    "running"
                    if self.args.denseworld_warmup and not self.world_seed_pending
                    else "playback"
                ),
                "paused": self.paused,
                "step": step,
                "replay_step": step,
                "vehicles": int(traffic_metrics["motorized_count"] + traffic_metrics["cyclist_count"]),
                "road_users": len(vehicles),
                "motorized_count": int(traffic_metrics["motorized_count"]),
                "cyclist_count": int(traffic_metrics["cyclist_count"]),
                "pedestrian_count": int(traffic_metrics["pedestrian_count"]),
                "sim_time": step * self.step_seconds,
                "progress": progress,
                "avg_speed": traffic_metrics["avg_speed"],
                "avg_ttc": traffic_metrics["avg_ttc"],
                "avg_headway": traffic_metrics["avg_headway"],
                "collision_count": traffic_metrics["collision_count"],
                "av_avg_ttc": av_metrics["av_avg_ttc"],
                "av_min_ttc": av_metrics["av_min_ttc"],
                "av_avg_headway": av_metrics["av_avg_headway"],
                "av_collision_count": av_metrics["av_collision_count"],
                "av_ttc_samples": av_metrics["av_ttc_samples"],
                "av_headway_samples": av_metrics["av_headway_samples"],
                "speed_samples": traffic_metrics["speeds"],
                "ttc_samples": traffic_metrics["ttc_samples"],
                "headway_samples": traffic_metrics["headway_samples"],
                "safety_computed": True,
                "replay_ego_id": self.replay_ego_id,
                "av_id": self.replay_ego_id,
            }
        )
        return {"ok": True, **sim_state}

    def _handle_action(self, action: dict):
        sync_id = action.get("_sync_id")
        act_type = str(action.get("type", "")).strip().lower()
        result = {"ok": True}
        try:
            if act_type == "replay_seek":
                step = _safe_int(action.get("step", self.current_step), self.current_step)
                sim_state = self._publish(step)
                result = {
                    "ok": True,
                    "message": "Seek completed",
                    "replay_step": self.current_step,
                    "total_steps": self.total_steps,
                    "step_seconds": self.step_seconds,
                    "sim_state": sim_state,
                }
            elif act_type == "terminate_experiment":
                self.active = False
                self.paused = False
                self.viewer.set_status_fields({"run_state": "idle", "paused": False, "progress": 0.0})
                self.viewer.set_sim_state({"backend_model": "cnde", "step": 0, "vehicles": [], "traffic_lights": {}})
                result = {"ok": True, "message": "Playback terminated", "run_state": "idle"}
            elif act_type == "world_seed_ready":
                if not self.world_seed_pending:
                    raise RuntimeError("No replay world seed is pending")
                self.world_seed_pending = False
                self.active = True
                self.client_clock = False
                self.paused = False
                self._publish(0)
                self.viewer.set_status_fields(
                    {
                        "run_state": "running",
                        "paused": False,
                        "world_seed_pending": False,
                        "world_seed_video": str(action.get("video") or ""),
                        "world_seed_frame": str(action.get("frame") or ""),
                    }
                )
                result = {"ok": True, "message": "Replay world seed accepted", "run_state": "running"}
            elif act_type == "world_seed_align":
                if not self.world_seed_pending:
                    raise RuntimeError("No replay world seed is pending")
                mode = normalize_seed_alignment_mode(action.get("mode"))
                vehicles = sorted(
                    self._vehicles_at(0), key=lambda item: str(item.get("id", ""))
                )
                ego = next(
                    (
                        dict(item)
                        for item in vehicles
                        if str(item.get("id")) == self.replay_ego_id
                    ),
                    dict(vehicles[0]) if vehicles else {},
                )
                boundary = {
                    "raw_sim_time": 0.0,
                    "sim_time": 0.0,
                    "ego": ego,
                    "vehicles": [
                        item
                        for item in vehicles
                        if str(item.get("id")) != str(ego.get("id"))
                    ],
                    "traffic_lights": self._traffic_lights_at(0),
                }
                audit = audit_seed_traffic_boundary(
                    boundary,
                    boundary,
                    alignment_mode=mode,
                )
                self.world_seed_alignment_mode = mode
                self.world_seed_alignment_prepared = True
                self.viewer.set_status_fields(
                    {
                        "world_seed_alignment_mode": mode,
                        "world_seed_alignment_prepared": True,
                        "world_seed_alignment_audit": audit,
                    }
                )
                result = {
                    "ok": True,
                    "message": "Replay frame-zero world seed alignment verified",
                    "world_seed_alignment_mode": mode,
                    "audit": audit,
                }
            elif act_type in {"start_playback", "start_offline_preview", "start_offline_test"}:
                preview = act_type == "start_offline_preview"
                offline = act_type in {"start_offline_preview", "start_offline_test"} or bool(action.get("offline_test"))
                scenario = str(action.get("scenario_path") or action.get("scenario") or "").strip()
                if scenario:
                    requested_path = _resolve_citynde_path(scenario, self.citynde_root)
                    scenario_changed = requested_path != self.scenario_path
                    if scenario_changed:
                        self.scenario_path = requested_path
                        self.data = self._load_scenario(self.scenario_path)
                        self._bind_recording_data()
                        self.experiment_params = self._experiment_params_from_data()
                        self.replay_ego_id = str(
                            action.get("offline_av_id")
                            or action.get("replay_ego_id")
                            or self.experiment_params.get("seed_ego_id")
                            or self.experiment_params.get("av_id")
                            or ""
                        )
                    map_path = str(self.experiment_params.get("map_path") or self.args.map_path or "assets/map/routed_map_nuplan_boston.pkl")
                    if scenario_changed or map_path != self._map_path:
                        self._map_state = self._load_map_state(map_path)
                        self._map_path = map_path
                        self.viewer.set_map_state(self._map_state)
                    self.viewer.set_status_fields(
                        {
                            "scenario": _display_path(self.scenario_path, self.citynde_root),
                            "save_file": _display_path(self.scenario_path, self.citynde_root),
                            "replay_params": {
                                "scenario_path": _display_path(self.scenario_path, self.citynde_root),
                                "map_path": self._map_state.get("map_path", map_path),
                                "arrival_rate": self.experiment_params.get("arrival_rate"),
                                "total_step": self.total_steps,
                                "sim_resolution": self.step_seconds,
                                "offline_test": offline,
                                "offline_preview": preview,
                                "offline_av_id": str(action.get("offline_av_id") or ""),
                                "av_enabled": bool(action.get("av_enabled")),
                                "av_control_model": str(action.get("av_control_model") or ""),
                                "av_control_host": str(action.get("av_control_host") or ""),
                                "av_control_port": action.get("av_control_port", ""),
                            },
                            "replay_total_steps": self.total_steps,
                            "total_step": self.total_steps,
                            "offline_test": offline,
                            "offline_preview": preview,
                            "offline_av_id": str(action.get("offline_av_id") or ""),
                            "av_enabled": bool(action.get("av_enabled")),
                            "av_control_model": str(action.get("av_control_model") or ""),
                            "av_control_host": str(action.get("av_control_host") or ""),
                            "av_control_port": action.get("av_control_port", ""),
                        }
                    )
                    if scenario_changed:
                        self._start_metrics_computation()
                offline_av_id = str(action.get("offline_av_id") or "")
                if not offline_av_id:
                    offline_av_id = self.replay_ego_id
                if offline_av_id:
                    selected = next(
                        (vehicle for vehicle in self._vehicles_at(0) if str(vehicle.get("id")) == offline_av_id),
                        None,
                    )
                    if selected is None or str(selected.get("type") or "vehicle").lower() in {
                        "pedestrian",
                        "cyclist",
                        "non_motorized",
                    }:
                        raise ValueError("Offline AV must be a motorized vehicle")
                self.offline_av.configure(
                    av_id=offline_av_id,
                    av_enabled=bool(action.get("av_enabled")) and not preview,
                    av_model=str(action.get("av_control_model") or "DEFAULT_TCP"),
                    host=str(action.get("av_control_host") or "127.0.0.1"),
                    port=action.get("av_control_port"),
                    start_tcp=not preview,
                )
                self.replay_ego_id = offline_av_id
                self.active = True
                self.client_clock = str(action.get("replay_clock") or "server").lower() == "client"
                self.paused = preview
                self.viewer.set_status_fields(
                    {
                        "run_state": "idle" if preview else "playback",
                        "paused": False,
                        "offline_test": offline,
                        "offline_preview": preview,
                        "offline_av_id": str(action.get("offline_av_id") or ""),
                        "replay_ego_id": self.replay_ego_id,
                        "av_id": self.replay_ego_id,
                        "av_enabled": bool(action.get("av_enabled")),
                        "av_control_model": str(action.get("av_control_model") or ""),
                        "av_control_host": str(action.get("av_control_host") or ""),
                        "av_control_port": action.get("av_control_port", ""),
                    }
                )
                sim_state = self._publish(0)
                if preview:
                    self.viewer.set_status_fields(
                        {
                            "run_state": "idle",
                            "paused": False,
                            "offline_test": True,
                            "offline_preview": True,
                            "offline_av_id": str(action.get("offline_av_id") or ""),
                        }
                    )
                result = {
                    "ok": True,
                    "message": "Offline preview ready" if preview else "Playback ready",
                    "loading": False,
                    "run_state": "idle" if preview else "playback",
                    "replay_step": self.current_step,
                    "total_steps": self.total_steps,
                    "step_seconds": self.step_seconds,
                    "sim_state": sim_state,
                }
            elif act_type in {"refresh_scenarios", "toggle_vehicle_id"}:
                result = {"ok": True, "message": "Accepted"}
            else:
                result = {"ok": False, "error": f"Unsupported replay action: {act_type}"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.viewer.set_action_result(sync_id, result)

    def _handle_pending_actions(self):
        while True:
            action = self.viewer.pop_action()
            if action is None:
                break
            self._handle_action(action)
        if self.viewer.pause_requested:
            self.paused = True
            self.viewer.set_status_fields({"paused": True, "pause_pending": False})
        if self.viewer.resume_requested:
            self.paused = False
            self.viewer.set_status_fields({"paused": False, "pause_pending": False})

    def run(self):
        def _stop(signum, frame):
            self.stop_requested = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        last_tick = time.time()
        try:
            while not self.stop_requested:
                self._handle_pending_actions()
                now = time.time()
                if (
                    self.active
                    and not self.client_clock
                    and not self.paused
                    and self.total_steps > 0
                    and now - last_tick >= self.step_seconds
                ):
                    last_tick = now
                    next_step = min(self.current_step + 1, self.total_steps - 1)
                    self._publish(next_step)
                    if next_step >= self.total_steps - 1:
                        self.active = False
                        self.viewer.set_status_fields(
                            {"run_state": "completed", "experiment_completed": True, "progress": 1.0}
                        )
                self.viewer.wait_for_action(0.03)
        finally:
            self._metrics_generation += 1
            self.offline_av.close()
            self.viewer.close()


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="CityNDE GUI adapter")
    parser.add_argument("--mode", choices=["generate", "replay"], default="generate")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--gui_dir", default=None)
    parser.add_argument("--citynde_root", default=str(CITYNDE_ROOT))
    parser.add_argument("--map_path", default="assets/map/routed_map_nuplan_boston.pkl")
    parser.add_argument("--scenario", default="")
    parser.add_argument("--init_mode", default="random_tl_only", choices=["random", "empty", "data", "data_random_tl", "random_tl_only", "none"])
    parser.add_argument("--init_file", default="")
    parser.add_argument("--total_step", type=int, default=10000)
    parser.add_argument("--max_sim_time", type=float, default=0.0)
    parser.add_argument("--run_until_stopped", action="store_true")
    parser.add_argument("--sim_resolution", type=float, default=0.1)
    parser.add_argument(
        "--control_step",
        type=int,
        default=int(os.environ.get("TRAFFICWM_CNDE_CONTROL_STEP", "5") or 5),
        help="Number of 0.1 s model predictions consumed before the next CityNDE inference (1-20)",
    )
    parser.add_argument(
        "--inference_precision",
        choices=["fp32", "tf32"],
        default=str(os.environ.get("TRAFFICWM_CNDE_INFERENCE_PRECISION", "fp32") or "fp32").lower(),
        help="CityNDE neural inference precision; TF32 is optional and exported trajectories remain FP32",
    )
    parser.add_argument(
        "--traffic_controller",
        choices=["citynde", "idm_mobil"],
        default="citynde",
        help="Vehicle controller used by generation mode",
    )
    parser.add_argument(
        "--rule_desired_speed_mps",
        type=float,
        default=10.0,
        help="IDM desired speed for rule-controlled background vehicles",
    )
    parser.add_argument("--save_file", default="output/scenario_debug_test.pkl")
    parser.add_argument("--experiment_name", default="")
    parser.add_argument("--experiment_id", default="")
    parser.add_argument("--save_interval", type=int, default=10)
    parser.add_argument("--render_interval", type=int, default=1)
    parser.add_argument("--profile", action="store_true", default=_env_flag("TRAFFICWM_CNDE_PROFILE"))
    parser.add_argument("--profile_steps", default=os.environ.get("TRAFFICWM_CNDE_PROFILE_STEPS", ""))
    parser.add_argument("--profile_output", default=os.environ.get("TRAFFICWM_CNDE_PROFILE_OUTPUT", ""))
    parser.add_argument("--arrival_rate", type=float, default=None)
    parser.add_argument("--lane_arrival_rates", default="")
    parser.add_argument("--default_spawn_speed", type=float, default=2.0)
    parser.add_argument("--disable_mixed_traffic", action="store_false", dest="mixed_traffic_enabled")
    parser.set_defaults(mixed_traffic_enabled=True)
    parser.add_argument("--cyclist_ratio", type=float, default=0.08)
    parser.add_argument("--pedestrians_per_crosswalk", type=int, default=2)
    parser.add_argument("--max_pedestrians", type=int, default=32)
    parser.add_argument("--vehicle_size_mode", choices=["mixed", "passenger_only"], default="mixed")
    parser.add_argument("--initial_speed_mode", choices=["citynde", "urban_sampled"], default="citynde")
    parser.add_argument("--signalize_unsignalized_map", action="store_true")
    parser.add_argument("--cfg_file", default="assets/config/model_cfg.yaml")
    parser.add_argument("--ckpt_file", default="assets/ckpt/nn_weights.pth")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gpu_id", default="")
    parser.add_argument("--av_enabled", action="store_true")
    parser.add_argument("--av_selection_mode", choices=["manual", "random"], default="random")
    parser.add_argument(
        "--av_control_model",
        choices=["DEFAULT_TCP", "EXTERNAL_TCP", "VTD_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM"],
        default="DEFAULT_TCP",
    )
    parser.add_argument("--av_command_mode", choices=["state", "actuator"], default="state")
    parser.add_argument("--av_control_host", default="127.0.0.1")
    parser.add_argument("--av_control_port", type=int, default=0)
    parser.add_argument("--av_control_timeout", type=float, default=1.0)
    parser.add_argument("--av_rgb_uri", default="")
    parser.add_argument("--denseworld_warmup", action="store_true")
    parser.add_argument("--denseworld_existing_seed", action="store_true")
    parser.add_argument("--world_seed_ego_id", default="")
    parser.add_argument("--warmup_seconds", type=float, default=1.0)
    parser.add_argument("--world_anchor_catalog", default="")
    parser.add_argument("--world_sync_state", default="")
    parser.add_argument("--world_loop_ego", action="store_true")
    parser.add_argument("--world_ego_speed_cap_mps", type=float, default=0.0)
    parser.add_argument("--world_local_target_count", type=int, default=0)
    parser.add_argument("--world_initial_vehicle_limit", type=int, default=0)
    parser.add_argument("--world_spawn_visibility_guard_m", type=float, default=100.0)
    parser.add_argument(
        "--world_context_mode",
        choices=sorted(WORLD_CONTEXT_MODES),
        default="auto",
    )
    args = parser.parse_args(argv)
    citynde_root = Path(args.citynde_root).resolve()
    gui_dir = Path(args.gui_dir).resolve() if args.gui_dir else None
    if not (citynde_root / "cnde").is_dir() or not (citynde_root / "csim").is_dir():
        parser.error(f"invalid CityNDE source root: {citynde_root}")
    _configure_citynde_imports(citynde_root)
    args.citynde_root = str(citynde_root)
    args.gui_dir = str(gui_dir) if gui_dir else None
    os.chdir(citynde_root)
    if args.gpu_id.strip():
        os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu_id.strip()
    init_started = time.perf_counter()
    if args.profile:
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
        except Exception:
            pass
    if args.mode == "replay":
        adapter = CityNDEReplayAdapter(args)
    else:
        adapter = CityNDEGenerationAdapter(args)
    if args.profile and hasattr(adapter, "profiler"):
        adapter.profiler._cuda_sync()
        adapter.profiler.record_initialization((time.perf_counter() - init_started) * 1000.0)
        print(f"[CityNDEProfile] output={adapter.profiler.output_path}", flush=True)
    adapter.run()


if __name__ == "__main__":
    main()
