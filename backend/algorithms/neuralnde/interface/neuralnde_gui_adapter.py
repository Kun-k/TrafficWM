"""Interactive NeuralNDE adapter with 25 Hz AV synchronization.

The upstream model predicts one 0.4 second keyframe at a time. This adapter
interpolates each model interval into ten 0.04 second frames, exchanges AV
commands on every fine-grained frame, and feeds the resulting AV keyframe back
into the next NeuralNDE history window.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import pickle
import random
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.common.av_tcp import AVCommand, AVTCPBridge
from backend.common.http_api_viewer import HttpApiViewer
from backend.dynamics import rollout_control


MODEL_RESOLUTION = 0.4
OUTPUT_RESOLUTION = 0.04
SUBSTEPS = int(round(MODEL_RESOLUTION / OUTPUT_RESOLUTION))


def _seed_runtime(seed: int) -> None:
    random.seed(int(seed))
    np.random.seed(int(seed))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))


def _normal_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _angle_lerp_degrees(start: float, end: float, ratio: float) -> float:
    delta = (float(end) - float(start) + 180.0) % 360.0 - 180.0
    return (float(start) + delta * ratio) % 360.0


def _vehicle_size(vehicle) -> tuple[float, float, float]:
    size = getattr(vehicle, "size", None)
    return (
        float(getattr(size, "length", None) or 3.6),
        float(getattr(size, "width", None) or 1.8),
        float(getattr(size, "height", None) or 1.5),
    )


def _clone_vehicle_at(vehicle, *, x: float, y: float, heading_deg: float):
    cloned = copy.deepcopy(vehicle)
    cloned.location.x = float(x)
    cloned.location.y = float(y)
    cloned.speed_heading = float(heading_deg) % 360.0
    cloned.update_poly_box_and_realworld_4_vertices()
    cloned.update_safe_poly_box()
    return cloned


def _frame_index(frame) -> dict[str, Any]:
    return {str(vehicle.id): vehicle for vehicle in frame}


def _interpolate_frames(current, target, substeps: int = SUBSTEPS) -> list[list[Any]]:
    current_by_id = _frame_index(current)
    target_by_id = _frame_index(target)
    ordered_ids = list(current_by_id)
    ordered_ids.extend(vehicle_id for vehicle_id in target_by_id if vehicle_id not in current_by_id)
    frames = []
    for step in range(1, substeps + 1):
        ratio = step / float(substeps)
        frame = []
        for vehicle_id in ordered_ids:
            before = current_by_id.get(vehicle_id)
            after = target_by_id.get(vehicle_id)
            if before is None:
                if step == substeps and after is not None:
                    frame.append(copy.deepcopy(after))
                continue
            if after is None:
                if step < substeps:
                    frame.append(copy.deepcopy(before))
                continue
            frame.append(
                _clone_vehicle_at(
                    before,
                    x=float(before.location.x) + (float(after.location.x) - float(before.location.x)) * ratio,
                    y=float(before.location.y) + (float(after.location.y) - float(before.location.y)) * ratio,
                    heading_deg=_angle_lerp_degrees(before.speed_heading, after.speed_heading, ratio),
                )
            )
        frames.append(frame)
    return frames


def _split_open_contour_sides(
    contour: np.ndarray,
    *,
    minimum_points: int = 6,
) -> list[np.ndarray]:
    """Remove the short end caps from a long lane-region contour."""
    points = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
    if len(points) < minimum_points:
        return []
    centered = points - points.mean(axis=0, keepdims=True)
    _, singular_values, axes = np.linalg.svd(centered, full_matrices=False)
    if len(singular_values) < 2 or singular_values[0] <= 1e-6:
        return []
    # Roundabout lane masks are annuli and must stay closed. Entrance/exit
    # masks are elongated polygons whose short end caps are not road paint.
    if singular_values[1] / singular_values[0] >= 0.58:
        return [points]
    longitudinal = centered @ axes[0]
    span = float(np.ptp(longitudinal))
    if span <= 1e-6:
        return []
    keep = (longitudinal > longitudinal.min() + 0.06 * span) & (
        longitudinal < longitudinal.max() - 0.06 * span
    )
    if bool(np.all(keep)):
        return [points]
    runs: list[np.ndarray] = []
    doubled = np.concatenate((keep, keep))
    start = None
    for index, active in enumerate(doubled):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= minimum_points:
                indices = np.arange(start, index) % len(points)
                run = points[indices]
                if len({int(value) for value in indices}) == len(indices):
                    runs.append(run)
            start = None
        if index >= len(points) and start is None:
            break
    unique: list[np.ndarray] = []
    for run in runs:
        if not any(
            np.linalg.norm(run.mean(axis=0) - existing.mean(axis=0)) < 1.0
            for existing in unique
        ):
            unique.append(run)
    return unique[:2]


def _select_world_ego_id(
    warmup_frames: list[dict[str, Any]],
    current_vehicles: list[dict[str, Any]],
    bounds: dict[str, Any],
    *,
    preferred_id: str = "",
    minimum_horizon_seconds: float = 0.0,
) -> str:
    persistent_ids: set[str] | None = None
    for frame in warmup_frames:
        frame_ids = {str(item.get("id")) for item in frame.get("vehicles") or []}
        persistent_ids = frame_ids if persistent_ids is None else persistent_ids & frame_ids
    current = {str(vehicle["id"]): vehicle for vehicle in current_vehicles}
    candidates = sorted((persistent_ids or set()) & current.keys())
    if not candidates:
        raise RuntimeError("NeuralNDE warmup has no persistent vehicle for the Cosmos camera rig")
    if str(preferred_id) in candidates:
        return str(preferred_id)

    center_x = 0.5 * (float(bounds["min_x"]) + float(bounds["max_x"]))
    center_y = 0.5 * (float(bounds["min_y"]) + float(bounds["max_y"]))
    required_forward_clearance = (
        min(90.0, max(25.0, 5.0 * float(minimum_horizon_seconds)))
        if minimum_horizon_seconds > 0.0
        else 0.0
    )

    def forward_clearance(vehicle: dict[str, Any]) -> float:
        x, y = float(vehicle["x"]), float(vehicle["y"])
        heading = float(vehicle.get("heading", 0.0) or 0.0)
        dx, dy = math.cos(heading), math.sin(heading)
        intersections = []
        if dx > 1e-9:
            intersections.append((float(bounds["max_x"]) - x) / dx)
        elif dx < -1e-9:
            intersections.append((float(bounds["min_x"]) - x) / dx)
        if dy > 1e-9:
            intersections.append((float(bounds["max_y"]) - y) / dy)
        elif dy < -1e-9:
            intersections.append((float(bounds["min_y"]) - y) / dy)
        return max(0.0, min((value for value in intersections if value >= 0.0), default=0.0))

    def camera_score(vehicle_id: str) -> tuple[int, float, float, int, float, float, float, int, float]:
        vehicle = current[vehicle_id]
        x, y = float(vehicle["x"]), float(vehicle["y"])
        distances = [
            math.hypot(float(other["x"]) - x, float(other["y"]) - y)
            for other_id, other in current.items()
            if other_id != vehicle_id
        ]
        nearest = min(distances, default=100.0)
        nearby = sum(distance <= 55.0 for distance in distances)
        center_distance = math.hypot(x - center_x, y - center_y)
        minimum_clearance = max(8.0, float(vehicle.get("length", 3.6)) + 3.0)
        route_clearance = forward_clearance(vehicle)
        boundary_depth = min(
            x - float(bounds["min_x"]),
            float(bounds["max_x"]) - x,
            y - float(bounds["min_y"]),
            float(bounds["max_y"]) - y,
        )
        entry_score = -max(0.0, boundary_depth) if minimum_horizon_seconds > 0.0 else 0.0
        history = vehicle.get("past") or []
        history_travel = sum(
            math.hypot(
                float(second[0]) - float(first[0]),
                float(second[1]) - float(first[1]),
            )
            for first, second in zip(history, history[1:])
            if len(first) >= 2 and len(second) >= 2
        )
        # Prefer an inward, long-lived route before framing qualities. NeuralNDE
        # removes actors at dataset boundaries, so an outward ego can truncate
        # the synchronized world-video run even when the simulation is longer.
        return (
            int(route_clearance >= required_forward_clearance),
            entry_score,
            -min(history_travel, 100.0),
            int(nearest >= minimum_clearance),
            min(route_clearance, 120.0),
            -center_distance,
            min(nearest, 25.0),
            nearby,
            float(vehicle.get("speed", 0.0) or 0.0),
        )

    return max(candidates, key=camera_score)


def _build_map_state(configs: dict, dataset: str) -> dict:
    map_path = Path(configs["basemap_dir"]).resolve()
    bounds_path = map_path.with_suffix(".json")
    bounds_config = json.loads(bounds_path.read_text(encoding="utf-8"))
    xs = [float(point[0]) for point in bounds_config.values()]
    ys = [float(point[1]) for point in bounds_config.values()]
    bounds = {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}

    road = cv2.imread(str(Path(configs["drivable_map_dir"]).resolve()), cv2.IMREAD_GRAYSCALE)
    if road is None:
        raise FileNotFoundError(f"NeuralNDE drivable map is unavailable: {configs['drivable_map_dir']}")
    road = cv2.resize(road, (int(configs["map_width"]), int(configs["map_height"])))
    _, mask = cv2.threshold(road, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:32]
    polylines = []
    width = max(1, int(configs["map_width"]) - 1)
    height = max(1, int(configs["map_height"]) - 1)

    def world_point(px: float, py: float) -> list[float]:
        return [
            bounds["min_x"] + float(px) / width * (bounds["max_x"] - bounds["min_x"]),
            bounds["max_y"] - float(py) / height * (bounds["max_y"] - bounds["min_y"]),
        ]

    for idx, contour in enumerate(contours):
        if cv2.arcLength(contour, True) < 60.0 or cv2.contourArea(contour) < 80.0:
            continue
        approx = cv2.approxPolyDP(contour, 1.2, True).reshape(-1, 2)
        points = [world_point(px, py) for px, py in approx[:: max(1, len(approx) // 360)]]
        if len(points) >= 2:
            points.append(points[0])
            polylines.append(
                {
                    "id": f"road-boundary-{idx}",
                    "type": 2,
                    "road_boundary": True,
                    "points": [[round(value, 4) for value in point] for point in points],
                }
            )

    # NeuralNDE has no vector HD map. Its lane ROI masks are authoritative for
    # where vehicles may travel, so derive paired lane edges from each ROI
    # instead of mislabelling the whole drivable-area outline as lane paint.
    roi_root = Path(configs.get("ROI_map_dir") or "").resolve()
    lane_masks = sorted((roi_root / "entrance").glob("*.jpg"))
    lane_masks.extend(sorted((roi_root / "exit").glob("*.jpg")))
    lane_masks.extend(sorted((roi_root / "at-circle-lane").glob("*.jpg")))
    lane_line_index = 0
    for lane_index, lane_path in enumerate(lane_masks):
        raw_lane = cv2.imread(str(lane_path), cv2.IMREAD_GRAYSCALE)
        if raw_lane is None:
            continue
        lane_mask = cv2.resize(raw_lane, (width + 1, height + 1))
        lane_mask = np.where(lane_mask >= 96, 255, 0).astype(np.uint8)
        lane_contours, _ = cv2.findContours(lane_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        if not lane_contours:
            continue
        for contour in sorted(lane_contours, key=cv2.contourArea, reverse=True)[:3]:
            if cv2.contourArea(contour) < 40.0 or cv2.arcLength(contour, True) < 45.0:
                continue
            approx = cv2.approxPolyDP(contour, 0.8, True).reshape(-1, 2)
            pieces = (
                [np.asarray(approx, dtype=np.float64)]
                if lane_path.parent.name == "at-circle-lane"
                else _split_open_contour_sides(approx)
            )
            for piece in pieces:
                points = [
                    world_point(px, py)
                    for px, py in piece[:: max(1, len(piece) // 240)]
                ]
                if len(points) < 3:
                    continue
                if lane_path.parent.name == "at-circle-lane":
                    points.append(points[0])
                polylines.append(
                    {
                        "id": f"lane-edge-{lane_index}-{lane_line_index}",
                        "type": 1,
                        "lane_boundary": True,
                        "source": "NeuralNDE lane ROI boundary",
                        "points": [
                            [round(value, 4) for value in point] for point in points
                        ],
                    }
                )
                lane_line_index += 1

    crosswalks = []
    crosswalk_path = roi_root / "crosswalk" / "crosswalk-map.jpg"
    if crosswalk_path.is_file():
        crosswalk_mask = cv2.imread(str(crosswalk_path), cv2.IMREAD_GRAYSCALE)
        if crosswalk_mask is not None:
            crosswalk_mask = cv2.resize(crosswalk_mask, (width + 1, height + 1))
            _, crosswalk_mask = cv2.threshold(crosswalk_mask, 96, 255, cv2.THRESH_BINARY)
            crosswalk_contours, _ = cv2.findContours(
                crosswalk_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for index, contour in enumerate(sorted(crosswalk_contours, key=cv2.contourArea, reverse=True)[:8]):
                if cv2.contourArea(contour) < 20.0:
                    continue
                polygon = [world_point(px, py) for px, py in cv2.approxPolyDP(contour, 1.0, True).reshape(-1, 2)]
                if len(polygon) >= 3:
                    polygon.append(polygon[0])
                    crosswalks.append(
                        {
                            "id": f"neuralnde-crosswalk-{index}",
                            "polygon": polygon,
                            "source": "NeuralNDE ROI crosswalk mask",
                            "source_kind": "explicit",
                            "confidence": 0.9,
                        }
                    )
    return {
        "backend_model": "neuralnde",
        "map_path": dataset,
        "bounds": bounds,
        "polylines": polylines,
        "crosswalks": crosswalks,
        "stop_lines": [],
        "traffic_signals": [],
        "semantic_quality": {
            "schema": "denseworld.semantic-map-quality.v1",
            "source": "neuralnde-drivable-and-lane-roi-masks",
            "score": 0.82,
            "exact_features": len(crosswalks),
            "derived_features": len(polylines),
            "crosswalk_count": len(crosswalks),
            "stop_line_count": 0,
            "traffic_signal_count": 0,
            "warnings": [],
            "traffic_signal_policy": "none_roundabout",
        },
        "raster_url": "map.jpg",
        "raster_bounds": bounds,
    }


def _traffic_metrics(vehicles: list[dict]) -> dict[str, Any]:
    speeds = [float(vehicle.get("speed", 0.0)) for vehicle in vehicles]
    ttc_samples = []
    headways = []
    collisions = 0
    sample = vehicles[:96]
    for index, first in enumerate(sample):
        for second in sample[index + 1 :]:
            dx = float(second["x"]) - float(first["x"])
            dy = float(second["y"]) - float(first["y"])
            distance = math.hypot(dx, dy)
            clearance = distance - 0.5 * (float(first.get("length", 3.6)) + float(second.get("length", 3.6)))
            if clearance <= 0.0:
                collisions += 1
            headways.append(max(0.0, clearance))
            if distance <= 1e-6:
                continue
            first_vx = float(first.get("speed", 0.0)) * math.cos(float(first.get("heading", 0.0)))
            first_vy = float(first.get("speed", 0.0)) * math.sin(float(first.get("heading", 0.0)))
            second_vx = float(second.get("speed", 0.0)) * math.cos(float(second.get("heading", 0.0)))
            second_vy = float(second.get("speed", 0.0)) * math.sin(float(second.get("heading", 0.0)))
            closing = -((second_vx - first_vx) * dx + (second_vy - first_vy) * dy) / distance
            if closing > 1e-3:
                ttc_samples.append(max(0.0, clearance) / closing)
    return {
        "avg_speed": sum(speeds) / len(speeds) if speeds else None,
        "speeds": speeds,
        "min_ttc": min(ttc_samples) if ttc_samples else None,
        "avg_ttc": sum(ttc_samples) / len(ttc_samples) if ttc_samples else None,
        "avg_headway": sum(headways) / len(headways) if headways else None,
        "ttc_samples": ttc_samples,
        "headway_samples": headways,
        "collision_count": collisions,
    }


class NeuralNDEAdapter:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_until_stopped = bool(getattr(args, "run_until_stopped", False))
        self.root = Path(args.neuralnde_root).resolve()
        self.dataset = str(args.dataset)
        self.output_dir = Path(args.output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "traffic").mkdir(parents=True, exist_ok=True)
        self.frames_path = self.output_dir / "traffic" / "frames.jsonl"
        self.keyframes_path = self.output_dir / "traffic" / "keyframes.pklstream"
        self.summary_path = self.output_dir / "summary.json"
        self.av_report_path = self.output_dir / "av_control_report.json"
        self.performance_path = self.output_dir / "performance.json"
        self.warmup_frames_path = self.output_dir / "traffic" / "warmup_frames.json"
        self._frames_file = self.frames_path.open("a", encoding="utf-8")
        self._keyframes_file = self.keyframes_path.open("ab")

        config_path = self.root / "configs" / f"{self.dataset}_inference.yml"
        if not config_path.is_file():
            raise FileNotFoundError(f"Unsupported NeuralNDE dataset: {self.dataset}")
        self.configs = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        self.configs.update(
            {
                "use_gpu": True,
                "device": torch.device("cuda:0" if torch.cuda.is_available() else "cpu"),
                "sim_num": 1,
                # The adapter drives inference incrementally. Keep the official
                # engine's bookkeeping horizon positive for open-ended runs.
                "sim_wall_time": max(MODEL_RESOLUTION, float(args.max_sim_time or 0.0)),
                "gen_realistic_metric_flag": False,
                "save_collision_data_flag": False,
                "save_simulated_TIME_BUFF_flag": False,
                "viz_flag": False,
                "save_viz_flag": False,
                "interpolate_flag": True,
                "intep_steps": SUBSTEPS - 1,
                "realistic_metric_save_folder": str(self.output_dir / "metrics"),
                "simulated_TIME_BUFF_save_folder": str(self.output_dir / "traffic"),
                "save_viz_folder": str(self.output_dir / "video"),
            }
        )
        from simulation_modeling.simulation_inference import SimulationInference

        runtime_seed = int(args.seed)
        _seed_runtime(runtime_seed)
        self.engine = SimulationInference(configs=self.configs)
        # Upstream Basemap resets NumPy from system entropy during construction.
        # Restore every simulation RNG after the model and map are initialized.
        _seed_runtime(runtime_seed)
        self.engine.traffic_generator.np_random = np.random.RandomState(runtime_seed)
        self.time_buff, self.traj_pool = self.engine.initialize_sim()
        self.current_frame = self.time_buff[-1]
        self.total_steps = (
            0
            if self.run_until_stopped
            else max(1, int(math.ceil(float(args.max_sim_time) / OUTPUT_RESOLUTION)))
        )
        self.warmup_steps = (
            max(1, int(round(float(args.warmup_seconds or 1.0) / OUTPUT_RESOLUTION)))
            if bool(args.denseworld_warmup)
            else 0
        )
        self.display_step = 0
        self.paused = False
        self.stop_requested = False
        self.completed = False
        self.termination_reason = ""
        self.world_seed_pending = False
        self.world_seed_frame = ""
        self.world_sync_state = (
            Path(args.world_sync_state).resolve()
            if str(args.world_sync_state or "").strip()
            else None
        )
        self.world_sync_waiting = False
        self.world_ego_id: str | None = None
        self._warmup_frames: list[dict[str, Any]] = []
        self._inference_seconds: list[float] = []
        self._publish_seconds: list[float] = []
        self._sync_wait_seconds = 0.0
        self._seed_wait_seconds = 0.0
        self._seed_wait_started = 0.0
        self._started_wall = time.perf_counter()
        self._last_remote_command_time = 0.0
        self.av_command_timeout_count = 0
        self.av_perception_frame_count = 0
        self.av_command_frame_count = 0
        self.av_command_latencies_ms: list[float] = []
        self.av_first_command_frame: int | None = None
        self.av_last_command_frame: int | None = None
        self.av_start_state: dict[str, Any] = {}
        self.av_end_state: dict[str, Any] = {}
        self.av_last_diagnostics: dict[str, Any] = {}
        self.av_enabled = bool(args.av_enabled)
        self.av_id: str | None = None
        self.av_selection_mode = str(args.av_selection_mode or "random").lower()
        self.av_control_model = str(args.av_control_model or "DEFAULT_TCP").upper()
        self.av_command_mode = str(args.av_command_mode or "state").lower()
        self.av_control_timeout = max(0.005, float(args.av_control_timeout or OUTPUT_RESOLUTION))
        self.av_rgb_uri = str(args.av_rgb_uri or "").strip()
        self.waiting_for_av_selection = False
        self.av_bridge = None
        if self.av_enabled and self.av_control_model in {"EXTERNAL_TCP", "VTD_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM"}:
            av_port = int(args.av_control_port or (int(args.port) + 1000))
            self.av_bridge = AVTCPBridge(args.av_control_host, av_port)
            self.av_bridge.start()

        self._past: dict[str, deque[list[float]]] = {}
        self._previous_positions: dict[str, tuple[float, float]] = {}
        self._last_speeds: dict[str, float] = {}
        self._distance_traveled: dict[str, float] = {}
        if len(self.time_buff) >= 2:
            previous_keyframe = _frame_index(self.time_buff[-2])
            for vehicle in self.current_frame:
                previous = previous_keyframe.get(str(vehicle.id))
                if previous is not None:
                    self._last_speeds[str(vehicle.id)] = math.hypot(
                        float(vehicle.location.x) - float(previous.location.x),
                        float(vehicle.location.y) - float(previous.location.y),
                    ) / MODEL_RESOLUTION
        for history_frame in self.time_buff:
            for vehicle in history_frame:
                history = self._past.setdefault(str(vehicle.id), deque(maxlen=125))
                history.append([float(vehicle.location.x), float(vehicle.location.y)])
        self.metrics = {
            "ok": True,
            "step_seconds": OUTPUT_RESOLUTION,
            "sim_resolution": OUTPUT_RESOLUTION,
            "computed_steps": 0,
            "total_steps": self.total_steps,
            "vehicle_count_per_step": [],
            "speed_per_step": [],
            "min_ttc_per_step": [],
            "headway_per_step": [],
            "collision_count_per_step": [],
            "speed_samples_per_step": [],
            "ttc_samples_per_step": [],
            "headway_samples_per_step": [],
            "arrival_rate_per_step": [],
        }

        self.viewer = HttpApiViewer(
            mode="neuralnde",
            host=args.host,
            port=args.port,
            gui_dir=args.gui_dir,
            workspace_root=str(self.root),
        )
        self.viewer.set_maps(["AA_rdbt", "rounD"])
        self.map_state = _build_map_state(self.configs, self.dataset)
        self.viewer.set_map_state(self.map_state)
        (self.output_dir / "map_state.json").write_text(
            json.dumps(self.map_state, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        self.viewer.set_map_image(self.configs["basemap_dir"], "image/png")
        self.viewer.set_replay_metrics(self.metrics)
        self.viewer.set_status_fields(
            {
                "mode": "neuralnde",
                "backend_model": "neuralnde",
                "run_state": "running",
                "experiment_id": str(args.experiment_id),
                "experiment_name": str(args.experiment_name),
                "map_path": self.dataset,
                "save_file": str(self.frames_path),
                "output_dir": str(self.output_dir),
                "gpu_id": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
                "sim_resolution": OUTPUT_RESOLUTION,
                "model_resolution": MODEL_RESOLUTION,
                "model_inference_stride": SUBSTEPS,
                "traffic_stream_fps": 1.0 / OUTPUT_RESOLUTION,
                "total_step": self.total_steps,
                "max_sim_time": float(args.max_sim_time),
                "run_until_stopped": self.run_until_stopped,
                "world_video_duration": float(args.world_video_duration),
                "av_enabled": self.av_enabled,
                "av_id": "",
                "av_selection_mode": self.av_selection_mode,
                "av_control_model": self.av_control_model,
                "av_command_mode": self.av_command_mode,
                "av_control_endpoint": self.av_bridge.endpoint if self.av_bridge else "",
                "av_connected": False,
                "av_perception_frame_count": 0,
                "av_command_frame_count": 0,
                "av_command_timeout_count": 0,
                "av_command_success_rate": 0.0,
                "av_command_latency_ms": None,
                "waiting_for_av_selection": False,
                "world_seed_pending": False,
                "warmup_seconds": self.warmup_steps * OUTPUT_RESOLUTION,
                "warmup_frames_file": "",
                "experiment_completed": False,
            }
        )
        (self.output_dir / "config.json").write_text(
            json.dumps(
                {
                    "schema": "denseworld.experiment.v1",
                    "backend_model": "neuralnde",
                    "dataset": self.dataset,
                    "model_resolution": MODEL_RESOLUTION,
                    "output_resolution": OUTPUT_RESOLUTION,
                    "traffic_stream_fps": 1.0 / OUTPUT_RESOLUTION,
                    "warmup_seconds": self.warmup_steps * OUTPUT_RESOLUTION,
                    "max_sim_time": float(args.max_sim_time),
                    "run_until_stopped": self.run_until_stopped,
                    "world_video_duration": float(args.world_video_duration),
                    "realtime": bool(args.realtime),
                    "av_enabled": self.av_enabled,
                    "av_selection_mode": self.av_selection_mode,
                    "av_control_model": self.av_control_model,
                    "av_command_mode": self.av_command_mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _lane_id(self, vehicle) -> str:
        try:
            point = self.engine.sim.road_matcher._world2pxl([vehicle.location.x, vehicle.location.y])
            point[1] = np.clip(point[1], 0, self.engine.sim.road_matcher.road_map.shape[0] - 1)
            point[0] = np.clip(point[0], 0, self.engine.sim.road_matcher.road_map.shape[1] - 1)
            region = self.engine.sim.ROI_matcher.region_position_matching(point)
            lane = self.engine.sim.ROI_matcher.at_circle_lane_matching(point)
            return "/".join(str(value) for value in (region, lane) if value not in (None, ""))
        except Exception:
            return ""

    def _vehicle_dicts(self, frame, *, update_tracking: bool = True) -> list[dict]:
        output = []
        active_ids = set()
        for vehicle in frame:
            vehicle_id = str(vehicle.id)
            active_ids.add(vehicle_id)
            x = float(vehicle.location.x)
            y = float(vehicle.location.y)
            previous = self._previous_positions.get(vehicle_id)
            if previous is not None:
                distance = math.hypot(x - previous[0], y - previous[1])
                speed = distance / OUTPUT_RESOLUTION if distance > 1e-7 else self._last_speeds.get(vehicle_id, 0.0)
            else:
                speed = self._last_speeds.get(vehicle_id, float(getattr(vehicle, "speed", None) or 0.0))
            length, width, height = _vehicle_size(vehicle)
            history = self._past.setdefault(vehicle_id, deque(maxlen=125))
            if update_tracking and (not history or math.hypot(history[-1][0] - x, history[-1][1] - y) > 1e-5):
                history.append([x, y])
            if update_tracking and previous is not None and distance > 1e-7:
                self._distance_traveled[vehicle_id] = self._distance_traveled.get(vehicle_id, 0.0) + distance
            output.append(
                {
                    "id": vehicle_id,
                    "type": "av" if vehicle_id == self.av_id else "vehicle",
                    "is_av": vehicle_id == self.av_id,
                    "x": x,
                    "y": y,
                    "heading": _normal_angle(math.radians(float(vehicle.speed_heading or 0.0))),
                    "speed": speed,
                    "distance_traveled_m": self._distance_traveled.get(vehicle_id, 0.0),
                    "length": length,
                    "width": width,
                    "height": height,
                    "lane_id": self._lane_id(vehicle),
                    "past": list(history),
                    "future": [],
                }
            )
            if update_tracking:
                self._previous_positions[vehicle_id] = (x, y)
                self._last_speeds[vehicle_id] = speed
        for vehicle_id in list(self._past):
            if vehicle_id not in active_ids and len(self._past[vehicle_id]) == 0:
                self._past.pop(vehicle_id, None)
        return output

    def _append_metrics(self, vehicles: list[dict]) -> dict:
        values = _traffic_metrics(vehicles)
        for key, value in (
            ("vehicle_count_per_step", len(vehicles)),
            ("speed_per_step", values["avg_speed"]),
            ("min_ttc_per_step", values["min_ttc"]),
            ("headway_per_step", values["avg_headway"]),
            ("collision_count_per_step", values["collision_count"]),
            ("speed_samples_per_step", values["speeds"][:96]),
            ("ttc_samples_per_step", values["ttc_samples"][:96]),
            ("headway_samples_per_step", values["headway_samples"][:96]),
            ("arrival_rate_per_step", None),
        ):
            self.metrics[key].append(value)
        self.metrics["computed_steps"] = len(self.metrics["vehicle_count_per_step"])
        self.viewer.set_replay_metrics(self.metrics)
        return values

    def _record_frame(self, vehicles: list[dict]):
        payload = {
            "schema": "denseworld.traffic-frame.v1",
            "experiment_id": str(self.args.experiment_id),
            "backend_model": "neuralnde",
            "dataset": self.dataset,
            "frame": self.display_step,
            "sim_time": round(self.display_step * OUTPUT_RESOLUTION, 6),
            "step_seconds": OUTPUT_RESOLUTION,
            "vehicles": vehicles,
        }
        self._frames_file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        if self.display_step % 25 == 0:
            self._frames_file.flush()

    def _warmup_snapshot(self, raw_step: int, vehicles: list[dict]) -> dict[str, Any]:
        return {
            "sim_time": round(int(raw_step) * OUTPUT_RESOLUTION, 6),
            "ego": {},
            "vehicles": [dict(vehicle) for vehicle in vehicles],
            "traffic_lights": {},
        }

    def _enter_world_seed_pending(self) -> None:
        selected_id = _select_world_ego_id(
            self._warmup_frames,
            self._vehicle_dicts(self.current_frame, update_tracking=False),
            self.map_state["bounds"],
            preferred_id=str(self.av_id or "") if self.av_selection_mode == "manual" else "",
            minimum_horizon_seconds=(
                60.0 if self.run_until_stopped else float(self.args.world_video_duration)
            ),
        )
        self.world_ego_id = selected_id
        if self.av_enabled and selected_id != str(self.av_id or ""):
            self.av_id = selected_id
            self._prioritize_av_history()

        normalized_frames = []
        for frame in self._warmup_frames:
            actors = [dict(item) for item in frame.get("vehicles") or []]
            ego = next(item for item in actors if str(item.get("id")) == selected_id)
            others = []
            for actor in actors:
                actor["is_av"] = self.av_enabled and str(actor.get("id")) == selected_id
                actor["type"] = "av" if actor["is_av"] else "vehicle"
                if str(actor.get("id")) != selected_id:
                    others.append(actor)
            normalized_frames.append({**frame, "ego": ego, "vehicles": others})
        self._warmup_frames = normalized_frames
        current_vehicles = self._vehicle_dicts(self.current_frame, update_tracking=False)
        self._distance_traveled = {str(vehicle["id"]): 0.0 for vehicle in current_vehicles}
        self._previous_positions = {
            str(vehicle["id"]): (float(vehicle["x"]), float(vehicle["y"]))
            for vehicle in current_vehicles
        }
        self.warmup_frames_path.write_text(
            json.dumps(self._warmup_frames, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.world_seed_pending = True
        self._seed_wait_started = time.perf_counter()
        self.paused = True
        vehicles = self._vehicle_dicts(self.current_frame, update_tracking=False)
        self.viewer.set_sim_state_latest(
            {
                "backend_model": "neuralnde",
                "dataset": self.dataset,
                "step": 0,
                "sim_time": 0.0,
                "raw_sim_time": self.warmup_steps * OUTPUT_RESOLUTION,
                "vehicles": vehicles,
                "traffic_lights": {},
            }
        )
        self.viewer.set_status_fields(
            {
                "run_state": "world_seed_pending",
                "paused": True,
                "step": 0,
                "sim_time": 0.0,
                "raw_sim_time": self.warmup_steps * OUTPUT_RESOLUTION,
                "progress": 0.0,
                "world_seed_pending": True,
                "world_ego_id": selected_id,
                "warmup_frames": len(self._warmup_frames),
                "warmup_frames_file": str(self.warmup_frames_path),
                "warmup_source_fps": 1.0 / OUTPUT_RESOLUTION,
            }
        )

    def _record_keyframe(self, frame):
        pickle.dump(
            {"sim_time": round(self.display_step * OUTPUT_RESOLUTION, 6), "vehicles": frame},
            self._keyframes_file,
            protocol=4,
        )
        self._keyframes_file.flush()

    def _publish(self, frame):
        started = time.perf_counter()
        vehicles = self._vehicle_dicts(frame)
        self._record_av_state(vehicles)
        metrics = self._append_metrics(vehicles)
        self._record_frame(vehicles)
        sim_time = self.display_step * OUTPUT_RESOLUTION
        if not self.run_until_stopped:
            sim_time = min(float(self.args.max_sim_time), sim_time)
        progress = (
            0.0
            if self.run_until_stopped
            else min(1.0, sim_time / max(float(self.args.max_sim_time), OUTPUT_RESOLUTION))
        )
        self.viewer.set_sim_state_latest(
            {
                "backend_model": "neuralnde",
                "dataset": self.dataset,
                "step": self.display_step,
                "sim_time": sim_time,
                "vehicles": vehicles,
                "traffic_lights": {},
            }
        )
        self.viewer.set_status_fields(
            {
                "step": self.display_step,
                "sim_time": sim_time,
                "progress": progress,
                "vehicles": len(vehicles),
                "paused": self.paused,
                "av_id": self.av_id or "",
                "av_connected": self.av_bridge.connected if self.av_bridge else False,
                "waiting_for_av_selection": self.waiting_for_av_selection,
                "avg_speed": metrics["avg_speed"],
                "avg_ttc": metrics["avg_ttc"],
                "avg_headway": metrics["avg_headway"],
                "collision_count": metrics["collision_count"],
                "speed_samples": metrics["speeds"][:96],
                "ttc_samples": metrics["ttc_samples"][:96],
                "headway_samples": metrics["headway_samples"][:96],
                "safety_computed": True,
            }
        )
        self._publish_seconds.append(time.perf_counter() - started)

    def _active_vehicle(self, raw_id: Any, frame=None):
        target = str(raw_id)
        for vehicle in frame or self.current_frame:
            if str(vehicle.id) == target:
                return vehicle
        return None

    def _select_av(self, raw_id: Any) -> dict:
        if not self.av_enabled:
            raise RuntimeError("AV access is disabled")
        vehicle = self._active_vehicle(raw_id)
        if vehicle is None:
            raise ValueError(f"Vehicle {raw_id} is not active in the first frame")
        self.av_id = str(vehicle.id)
        self.waiting_for_av_selection = False
        self.paused = False
        self._prioritize_av_history()
        self.viewer.set_status_fields(
            {"av_id": self.av_id, "waiting_for_av_selection": False, "paused": False, "pause_pending": False}
        )
        return {"ok": True, "message": "AV selected", "av_id": self.av_id}

    def _random_select_av(self) -> dict:
        if not self.current_frame:
            raise RuntimeError("No active vehicle is available for AV selection")
        return self._select_av(random.choice(self.current_frame).id)

    def _prepare_av_selection(self):
        if not self.av_enabled or self.av_id is not None or not self.current_frame:
            return
        if self.av_selection_mode == "manual":
            self.waiting_for_av_selection = True
            self.paused = True
            self.viewer.set_status_fields({"waiting_for_av_selection": True, "paused": True})
        else:
            self._random_select_av()

    def _prioritize_av_history(self):
        if self.av_id is None:
            return
        for index, frame in enumerate(self.time_buff):
            self.time_buff[index] = sorted(frame, key=lambda vehicle: str(vehicle.id) != self.av_id)
        self.traj_pool = self.engine.sim.time_buff_to_traj_pool(self.time_buff)

    def _current_av_mapping(self) -> dict[str, float] | None:
        vehicle = self._active_vehicle(self.av_id)
        if vehicle is None:
            return None
        previous = self._previous_positions.get(self.av_id or "")
        speed = self._last_speeds.get(
            self.av_id or "",
            math.hypot(float(vehicle.location.x) - previous[0], float(vehicle.location.y) - previous[1]) / OUTPUT_RESOLUTION
            if previous
            else float(getattr(vehicle, "speed", None) or 0.0),
        )
        sensors = {}
        if self.av_rgb_uri:
            sensors["rgb_front"] = {
                "transport": "http",
                "uri": self.av_rgb_uri,
                "encoding": "image/jpeg",
                "source": "carla",
                "width": 1280,
                "height": 720,
                "nominal_fps": 25,
            }
        return {
            "x": float(vehicle.location.x),
            "y": float(vehicle.location.y),
            "heading": _normal_angle(math.radians(float(vehicle.speed_heading or 0.0))),
            "speed": speed,
        }

    def _coarse_av_prediction(self) -> list[dict[str, float]] | None:
        current = self._current_av_mapping()
        if current is None or self.av_bridge is None:
            return None
        command = self.av_bridge.latest_command()
        trajectory = command.trajectory
        if len(trajectory) >= SUBSTEPS * 5:
            trajectory = [trajectory[(index + 1) * SUBSTEPS - 1] for index in range(5)]
        return rollout_control(
            current,
            mode=command.control_mode or self.av_command_mode,
            state=command.state,
            actuators=command.actuators,
            trajectory=trajectory,
            horizon=5,
            dt=MODEL_RESOLUTION,
        )

    def _set_prediction_av(self, arrays, coarse_prediction):
        if self.av_id is None or not coarse_prediction:
            return None
        pred_lat, pred_lon, pred_cos, pred_sin, pred_vid = arrays
        try:
            numeric_id = float(self.av_id)
        except ValueError:
            return None
        rows = np.where(np.isclose(pred_vid[:, 0], numeric_id, equal_nan=False))[0]
        if not len(rows):
            return None
        row = int(rows[0])
        for index, state in enumerate(coarse_prediction[: pred_lat.shape[1]]):
            heading = float(state["heading"])
            pred_lat[row, index] = float(state["x"])
            pred_lon[row, index] = float(state["y"])
            pred_cos[row, index] = math.cos(heading)
            pred_sin[row, index] = math.sin(heading)
        return row

    @staticmethod
    def _restore_prediction_av(arrays, row: int | None, coarse_prediction):
        if row is None or not coarse_prediction:
            return
        pred_lat, pred_lon, pred_cos, pred_sin, _ = arrays
        for index, state in enumerate(coarse_prediction[: pred_lat.shape[1]]):
            heading = float(state["heading"])
            pred_lat[row, index] = float(state["x"])
            pred_lon[row, index] = float(state["y"])
            pred_cos[row, index] = math.cos(heading)
            pred_sin[row, index] = math.sin(heading)

    def _predict_keyframe(self):
        started = time.perf_counter()
        pred_lat, pred_lon, pred_cos, pred_sin, pred_vid, buff_vid, _, _ = self.engine.sim.run_forwardpass(self.traj_pool)
        arrays = [pred_lat, pred_lon, pred_cos, pred_sin, pred_vid]
        coarse_av = self._coarse_av_prediction()
        av_row = self._set_prediction_av(arrays, coarse_av)
        output_delta_position_mask = np.zeros(buff_vid.shape, dtype=bool)
        if self.engine.use_neural_safety_mapping:
            do_safety_mapping = True
            if self.engine.use_conflict_critic_module:
                candidate = self.engine.sim.prediction_to_trajectory_rolling_horizon(
                    pred_lat, pred_lon, pred_cos, pred_sin, pred_vid, self.time_buff, rolling_step=1
                )
                do_safety_mapping = self.engine.conflict_critic_agent.main_func(TIME_BUFF=candidate)
            if do_safety_mapping:
                pred_lat, pred_lon, pred_cos, pred_sin, pred_vid, output_delta_position_mask = self.engine.sim.do_safety_mapping(
                    pred_lat,
                    pred_lon,
                    pred_cos,
                    pred_sin,
                    pred_vid,
                    buff_vid,
                    output_delta_position_mask=True,
                )
                arrays = [pred_lat, pred_lon, pred_cos, pred_sin, pred_vid]
                self._restore_prediction_av(arrays, av_row, coarse_av)
        next_buff = self.engine.sim.prediction_to_trajectory_rolling_horizon(
            pred_lat, pred_lon, pred_cos, pred_sin, pred_vid, self.time_buff, rolling_step=1
        )
        next_buff = self.engine.sim.remove_out_of_bound_vehicles(next_buff, dataset=self.dataset)
        next_buff = self.engine.traffic_generator.generate_veh_at_source_pos(next_buff)
        self._inference_seconds.append(time.perf_counter() - started)
        return next_buff

    def _perception_payload(self, vehicles: list[dict]) -> dict:
        av = next((vehicle for vehicle in vehicles if str(vehicle["id"]) == str(self.av_id)), None)
        actors = [vehicle for vehicle in vehicles if str(vehicle["id"]) != str(self.av_id)]
        if av:
            actors.sort(key=lambda actor: math.hypot(float(actor["x"]) - float(av["x"]), float(actor["y"]) - float(av["y"])))
            actors = [
                actor
                for actor in actors
                if math.hypot(float(actor["x"]) - float(av["x"]), float(actor["y"]) - float(av["y"])) <= float(self.args.local_radius)
            ][: int(self.args.local_agent_limit)]
        sensors = {}
        if self.av_rgb_uri:
            sensors["rgb_front"] = {
                "transport": "http",
                "uri": self.av_rgb_uri,
                "encoding": "image/jpeg",
                "source": "carla",
                "width": 1280,
                "height": 720,
                "nominal_fps": 25,
            }
        return {
            "sim_time": self.display_step * OUTPUT_RESOLUTION,
            "step_seconds": OUTPUT_RESOLUTION,
            "av": av or {},
            "actors": [
                {
                    "id": actor["id"],
                    "type": "BV",
                    "x": actor["x"],
                    "y": actor["y"],
                    "heading": actor["heading"],
                    "speed": actor["speed"],
                    "length": actor["length"],
                    "width": actor["width"],
                    "lane_id": actor.get("lane_id", ""),
                }
                for actor in actors
            ],
            "traffic_lights": {},
            "sensors": sensors,
            "sensor_contract": {
                "rgb_available": bool(self.av_rgb_uri),
                "lidar_available": False,
                "radar_count": 0,
            },
        }

    def _handle_remote_command(self, command: AVCommand | None):
        if command is None or command.received_at <= self._last_remote_command_time:
            return
        self._last_remote_command_time = command.received_at
        if command.command_type == "pause":
            self.paused = True
        elif command.command_type == "resume":
            self.paused = False
        elif command.command_type == "terminate":
            self.stop_requested = True
            self.termination_reason = "av_requested_termination"

    def _apply_external_av(self, frame):
        if self.av_bridge is None or self.av_id is None:
            return frame
        predicted_vehicle = self._active_vehicle(self.av_id, frame)
        current_vehicle = self._active_vehicle(self.av_id, self.current_frame)
        if predicted_vehicle is None or current_vehicle is None:
            self.stop_requested = True
            self.termination_reason = "av_left_scene"
            return frame
        # NeuralNDE supplies the fine-frame BV interpolation. The AV must advance
        # exclusively from its last externally controlled state.
        control_frame = [
            current_vehicle if str(vehicle.id) == self.av_id else vehicle
            for vehicle in frame
        ]
        dicts = self._vehicle_dicts(control_frame, update_tracking=False)
        current = next(vehicle for vehicle in dicts if str(vehicle["id"]) == self.av_id)
        self.av_perception_frame_count += 1
        self.viewer.set_status_fields({"waiting_for_av_command": True, "av_connected": self.av_bridge.connected})
        started = time.perf_counter()
        command = self.av_bridge.exchange(
            self._perception_payload(dicts), frame=self.display_step + 1, timeout=self.av_control_timeout
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        self.viewer.set_status_fields({"waiting_for_av_command": False, "av_connected": self.av_bridge.connected})
        if command is None:
            self.av_command_timeout_count += 1
            self.viewer.set_status_fields({"av_command_timeout_count": self.av_command_timeout_count})
            command = self.av_bridge.latest_command()
        else:
            self.av_command_frame_count += 1
            self.av_command_latencies_ms.append(latency_ms)
            frame_number = self.display_step + 1
            self.av_first_command_frame = frame_number if self.av_first_command_frame is None else self.av_first_command_frame
            self.av_last_command_frame = frame_number
            self.av_last_diagnostics = dict(command.diagnostics)
        self.viewer.set_status_fields(
            {
                "av_perception_frame_count": self.av_perception_frame_count,
                "av_command_frame_count": self.av_command_frame_count,
                "av_command_success_rate": round(
                    self.av_command_frame_count / max(1, self.av_perception_frame_count), 6
                ),
                "av_command_latency_ms": round(latency_ms, 4),
            }
        )
        self._handle_remote_command(command)
        trajectory = rollout_control(
            current,
            mode=command.control_mode or self.av_command_mode,
            state=command.state,
            actuators=command.actuators,
            trajectory=command.trajectory[:1],
            horizon=1,
            dt=OUTPUT_RESOLUTION,
        )
        state = trajectory[0]
        controlled = _clone_vehicle_at(
            current_vehicle,
            x=state["x"],
            y=state["y"],
            heading_deg=math.degrees(state["heading"]),
        )
        controlled.speed = state["speed"]
        return [controlled if str(vehicle.id) == self.av_id else vehicle for vehicle in frame]

    def _av_collision(self, frame) -> bool:
        if self.av_id is None:
            return False
        av = self._active_vehicle(self.av_id, frame)
        if av is None:
            return False
        return any(str(vehicle.id) != self.av_id and av.poly_box.intersects(vehicle.poly_box) for vehicle in frame)

    def _replace_keyframe_av(self, frame):
        if self.av_id is None:
            return
        av = self._active_vehicle(self.av_id, frame)
        if av is None:
            return
        self.time_buff[-1] = [av if str(vehicle.id) == self.av_id else vehicle for vehicle in self.time_buff[-1]]

    def _handle_action(self, action: dict):
        sync_id = action.get("_sync_id")
        action_type = str(action.get("type") or "").strip().lower()
        try:
            if action_type == "select_av":
                result = self._select_av(action.get("vehicle_id"))
            elif action_type == "random_select_av":
                result = self._random_select_av()
            elif action_type == "world_seed_ready":
                if not self.world_seed_pending:
                    raise RuntimeError("No NeuralNDE world seed is pending")
                self.world_seed_frame = str(action.get("frame") or "").strip()
                if self._seed_wait_started:
                    self._seed_wait_seconds += time.perf_counter() - self._seed_wait_started
                    self._seed_wait_started = 0.0
                self.world_seed_pending = False
                self.paused = False
                self.av_start_state = {}
                self.av_end_state = {}
                self._operational_wall_started = time.monotonic()
                self._publish(self.current_frame)
                self.viewer.set_status_fields(
                    {
                        "run_state": "running",
                        "paused": False,
                        "world_seed_pending": False,
                        "world_seed_video": str(action.get("video") or ""),
                        "world_seed_frame": self.world_seed_frame,
                        "operational_started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
                result = {
                    "ok": True,
                    "message": "NeuralNDE world seed accepted",
                    "run_state": "running",
                    "av_id": self.av_id or "",
                }
            elif action_type == "terminate_experiment":
                self.stop_requested = True
                self.termination_reason = "user_terminated"
                result = {"ok": True, "message": "Experiment termination requested"}
            elif action_type in {"start_experiment", "refresh_scenarios"}:
                result = {"ok": True, "message": "Accepted"}
            else:
                result = {"ok": False, "error": f"Unsupported NeuralNDE action: {action_type}"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            self.viewer.set_status_fields({"last_error": str(exc), "last_error_nonce": time.time_ns()})
        self.viewer.set_action_result(sync_id, result)

    def _handle_pending_actions(self):
        while True:
            action = self.viewer.pop_action()
            if action is None:
                break
            self._handle_action(action)
        if self.viewer.pause_requested:
            self.paused = True
        if self.viewer.resume_requested and not self.world_seed_pending:
            self.paused = False
        self.viewer.set_paused(self.paused)

    def _wait_if_paused(self):
        while self.paused and not self.stop_requested:
            self._handle_pending_actions()
            time.sleep(0.02)

    def _wait_for_world_video_demand(self, next_display_step: int) -> bool:
        if self.world_sync_state is None or self.world_seed_pending:
            return True
        from backend.cosmos.world_sync import traffic_step_permitted

        next_sim_time = max(0, int(next_display_step)) * OUTPUT_RESOLUTION
        started = time.perf_counter()
        while not self.stop_requested:
            self._handle_pending_actions()
            permitted, sync_state = traffic_step_permitted(self.world_sync_state, next_sim_time)
            if permitted and not self.paused:
                if self.world_sync_waiting:
                    self.world_sync_waiting = False
                    self.viewer.set_status_fields({"world_sync_waiting": False})
                self._sync_wait_seconds += time.perf_counter() - started
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
        self._sync_wait_seconds += time.perf_counter() - started
        return False

    def _finish(self):
        self.completed = True
        if not self.termination_reason:
            self.termination_reason = (
                "stopped" if self.run_until_stopped else "configured_time_completed"
            )
        self._frames_file.flush()
        self._keyframes_file.flush()
        summary = {
            "schema": "denseworld.experiment-summary.v1",
            "experiment_id": str(self.args.experiment_id),
            "backend_model": "neuralnde",
            "dataset": self.dataset,
            "frames": self.display_step + 1,
            "sim_time": round(self.display_step * OUTPUT_RESOLUTION, 6),
            "termination_reason": self.termination_reason,
            "av_id": self.av_id or "",
            "artifacts": {
                "frames": str(self.frames_path),
                "keyframes": str(self.keyframes_path),
                "av_control_report": str(self.av_report_path) if self.av_enabled else "",
                "performance": str(self.performance_path),
            },
        }
        inference = np.asarray(self._inference_seconds, dtype=float)
        publish = np.asarray(self._publish_seconds, dtype=float)
        wall_seconds = time.perf_counter() - self._started_wall
        performance = {
            "schema": "denseworld.algorithm-performance.v1",
            "backend_model": "neuralnde",
            "model_resolution_seconds": MODEL_RESOLUTION,
            "stream_resolution_seconds": OUTPUT_RESOLUTION,
            "stream_fps": 1.0 / OUTPUT_RESOLUTION,
            "operational_frames": self.display_step + 1,
            "model_inference_calls": len(inference),
            "model_inference_seconds": round(float(inference.sum()), 6),
            "model_inference_mean_seconds": round(float(inference.mean()), 6) if len(inference) else None,
            "model_inference_p95_seconds": round(float(np.percentile(inference, 95)), 6) if len(inference) else None,
            "publish_seconds": round(float(publish.sum()), 6),
            "world_sync_wait_seconds": round(self._sync_wait_seconds, 6),
            "world_seed_wait_seconds": round(self._seed_wait_seconds, 6),
            "wall_seconds": round(wall_seconds, 6),
            "generated_sim_seconds": round(self.display_step * OUTPUT_RESOLUTION, 6),
            "simulation_realtime_factor_excluding_world_wait": round(
                self.display_step * OUTPUT_RESOLUTION
                / max(1e-9, wall_seconds - self._sync_wait_seconds - self._seed_wait_seconds),
                4,
            ),
        }
        self.performance_path.write_text(
            json.dumps(performance, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if self.av_enabled:
            self.av_report_path.write_text(
                json.dumps(self._av_report(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.viewer.set_status_fields(
            {
                "run_state": "completed",
                "paused": False,
                "experiment_completed": True,
                "progress": 1.0,
                "termination_reason": self.termination_reason,
                "save_file": str(self.frames_path),
                "output_dir": str(self.output_dir),
            }
        )

    def _record_av_state(self, vehicles: list[dict]) -> None:
        if self.av_id is None:
            return
        vehicle = next((item for item in vehicles if str(item.get("id")) == str(self.av_id)), None)
        if vehicle is None:
            return
        state = {
            "frame": self.display_step,
            **{
                key: vehicle.get(key)
                for key in ("id", "x", "y", "heading", "speed", "lane_id")
                if vehicle.get(key) is not None
            },
        }
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
            "backend_model": "neuralnde",
            "enabled": self.av_enabled,
            "model": self.av_control_model,
            "selection_mode": self.av_selection_mode,
            "command_mode": self.av_command_mode,
            "endpoint": self.av_bridge.endpoint if self.av_bridge else "",
            "av_id": self.av_id or "",
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
            "termination_reason": self.termination_reason,
            "sensor_contract": {
                "bev_actor_stream": True,
                "traffic_lights": False,
                "dynamic_rgb_available": bool(self.av_rgb_uri),
                "dynamic_rgb_source": "carla" if self.av_rgb_uri else "",
                "lidar_available": False,
                "radar_count": 0,
            },
        }

    def run(self):
        def stop_handler(_signum, _frame):
            self.stop_requested = True
            self.termination_reason = self.termination_reason or "process_signal"

        signal.signal(signal.SIGTERM, stop_handler)
        signal.signal(signal.SIGINT, stop_handler)
        wall_started = time.monotonic()
        try:
            # Select the world camera after warmup so it is persistent and has
            # useful surrounding traffic instead of being a random edge actor.
            if not self.warmup_steps or self.av_selection_mode == "manual":
                self._prepare_av_selection()
            self._record_keyframe(self.current_frame)
            if self.warmup_steps:
                warmup_vehicles = self._vehicle_dicts(self.current_frame)
                self._warmup_frames = [self._warmup_snapshot(0, warmup_vehicles)]
                self.viewer.set_sim_state_latest(
                    {
                        "backend_model": "neuralnde",
                        "dataset": self.dataset,
                        "step": 0,
                        "sim_time": 0.0,
                        "raw_sim_time": 0.0,
                        "vehicles": warmup_vehicles,
                        "traffic_lights": {},
                    }
                )
                self.viewer.set_status_fields(
                    {"run_state": "warming_up", "sim_time": 0.0, "raw_sim_time": 0.0}
                )
            else:
                self._publish(self.current_frame)
                self._wait_if_paused()

            raw_step = 0
            while (
                self.run_until_stopped or self.display_step < self.total_steps
            ) and not self.stop_requested:
                self._handle_pending_actions()
                self._wait_if_paused()
                if self.stop_requested:
                    break
                before = self.current_frame
                self.time_buff = self._predict_keyframe()
                target = self.time_buff[-1]
                for fine_frame in _interpolate_frames(before, target):
                    if (
                        raw_step >= self.warmup_steps
                        and not self.run_until_stopped
                        and self.display_step >= self.total_steps
                    ) or self.stop_requested:
                        break
                    self._handle_pending_actions()
                    self._wait_if_paused()
                    operational = raw_step >= self.warmup_steps
                    if operational and not self._wait_for_world_video_demand(self.display_step + 1):
                        break
                    if operational:
                        fine_frame = self._apply_external_av(fine_frame)
                    self.current_frame = fine_frame
                    raw_step += 1
                    if raw_step <= self.warmup_steps:
                        warmup_vehicles = self._vehicle_dicts(fine_frame)
                        self._warmup_frames.append(self._warmup_snapshot(raw_step, warmup_vehicles))
                        self.viewer.set_sim_state_latest(
                            {
                                "backend_model": "neuralnde",
                                "dataset": self.dataset,
                                "step": 0,
                                "sim_time": 0.0,
                                "raw_sim_time": raw_step * OUTPUT_RESOLUTION,
                                "vehicles": warmup_vehicles,
                                "traffic_lights": {},
                            }
                        )
                        self.viewer.set_status_fields(
                            {
                                "run_state": "warming_up",
                                "sim_time": 0.0,
                                "raw_sim_time": raw_step * OUTPUT_RESOLUTION,
                                "warmup_progress": raw_step / max(1, self.warmup_steps),
                            }
                        )
                        if raw_step == self.warmup_steps:
                            self._enter_world_seed_pending()
                            self._wait_if_paused()
                            wall_started = time.monotonic()
                        continue

                    self.display_step += 1
                    self._publish(fine_frame)
                    if self.av_id is not None and self._active_vehicle(self.av_id, fine_frame) is None:
                        self.stop_requested = True
                        self.termination_reason = "av_left_scene"
                    elif self._av_collision(fine_frame):
                        self.stop_requested = True
                        self.termination_reason = "av_collision"
                    if self.args.realtime and self.world_sync_state is None:
                        delay = wall_started + self.display_step * OUTPUT_RESOLUTION - time.monotonic()
                        if delay > 0:
                            time.sleep(delay)
                self._replace_keyframe_av(self.current_frame)
                self._prioritize_av_history()
                self.current_frame = self.time_buff[-1]
                self._record_keyframe(self.current_frame)
            self._finish()
            while not self.stop_requested:
                self._handle_pending_actions()
                time.sleep(0.2)
        except Exception as exc:
            self.termination_reason = "adapter_error"
            self.viewer.set_status_fields(
                {
                    "run_state": "error",
                    "last_error": str(exc),
                    "last_error_nonce": time.time_ns(),
                    "termination_reason": self.termination_reason,
                }
            )
            raise
        finally:
            self._frames_file.close()
            self._keyframes_file.close()
            if self.av_bridge is not None:
                self.av_bridge.close()
            self.viewer.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neuralnde_root", required=True)
    parser.add_argument("--dataset", choices=("AA_rdbt", "rounD"), default="AA_rdbt")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--experiment_id", required=True)
    parser.add_argument("--experiment_name", default="neuralnde")
    parser.add_argument("--max_sim_time", type=float, default=60.0)
    parser.add_argument("--run_until_stopped", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--gui_dir", default="")
    parser.add_argument("--gpu_id", default="0")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--denseworld_warmup", action="store_true")
    parser.add_argument("--warmup_seconds", type=float, default=1.0)
    parser.add_argument("--world_sync_state", default="")
    parser.add_argument("--world_video_duration", type=float, default=0.0)
    parser.add_argument("--local_radius", type=float, default=100.0)
    parser.add_argument("--local_agent_limit", type=int, default=31)
    parser.add_argument("--av_enabled", action="store_true")
    parser.add_argument("--av_selection_mode", choices=("manual", "random"), default="random")
    parser.add_argument("--av_control_model", default="DEFAULT_TCP")
    parser.add_argument("--av_command_mode", choices=("state", "actuator"), default="state")
    parser.add_argument("--av_control_host", default="127.0.0.1")
    parser.add_argument("--av_control_port", type=int, default=0)
    parser.add_argument("--av_control_timeout", type=float, default=OUTPUT_RESOLUTION)
    parser.add_argument("--av_rgb_uri", default="")
    return parser


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    root = Path(args.neuralnde_root).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    if str(args.gpu_id).strip():
        os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu_id).strip()
    adapter = NeuralNDEAdapter(args)
    adapter.run()


if __name__ == "__main__":
    main()
