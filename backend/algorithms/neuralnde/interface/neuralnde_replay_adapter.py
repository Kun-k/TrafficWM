"""Replay normalized NeuralNDE NDJSON frames through the shared GUI API."""
from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.common.http_api_viewer import HttpApiViewer


def _load_frames(path: Path) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"Invalid NDJSON frame at line {line_number}: {exc}") from exc
            if not isinstance(frame, dict) or not isinstance(frame.get("vehicles"), list):
                raise ValueError(f"Invalid normalized traffic frame at line {line_number}")
            frames.append(frame)
    if not frames:
        raise ValueError("NeuralNDE recording contains no frames")
    return frames


def _fallback_map_state(frames: list[dict[str, Any]], dataset: str) -> dict[str, Any]:
    points = [
        (float(vehicle.get("x", 0.0)), float(vehicle.get("y", 0.0)))
        for frame in frames
        for vehicle in frame.get("vehicles") or []
    ]
    xs = [point[0] for point in points] or [-50.0, 50.0]
    ys = [point[1] for point in points] or [-50.0, 50.0]
    margin = 15.0
    return {
        "backend_model": "neuralnde",
        "map_path": dataset,
        "bounds": {
            "min_x": min(xs) - margin,
            "max_x": max(xs) + margin,
            "min_y": min(ys) - margin,
            "max_y": max(ys) + margin,
        },
        "lanes": [],
        "traffic_lights": {},
        "preview_degraded": True,
    }


def _frame_state(frame: dict[str, Any], *, include_history: bool, include_future: bool) -> dict[str, Any]:
    vehicles = []
    for source in frame.get("vehicles") or []:
        vehicle = dict(source)
        if not include_history:
            vehicle.pop("past", None)
        if not include_future:
            vehicle.pop("future", None)
        vehicles.append(vehicle)
    return {
        "backend_model": "neuralnde",
        "step": int(frame.get("frame", 0) or 0),
        "sim_time": float(frame.get("sim_time", 0.0) or 0.0),
        "vehicles": vehicles,
        "pedestrians": list(frame.get("pedestrians") or []),
        "traffic_lights": dict(frame.get("traffic_lights") or {}),
    }


def _frame_metrics(frame: dict[str, Any]) -> dict[str, Any]:
    vehicles = frame.get("vehicles") or []
    speeds = [float(vehicle.get("speed", 0.0) or 0.0) for vehicle in vehicles]
    return {
        "vehicles": len(vehicles),
        "avg_speed": sum(speeds) / len(speeds) if speeds else None,
        "speed_samples": speeds,
        "avg_ttc": None,
        "avg_headway": None,
        "collision_count": None,
        "motorized_count": sum(
            str(vehicle.get("type") or "vehicle").lower() not in {"cyclist", "pedestrian", "non_motorized"}
            for vehicle in vehicles
        ),
        "cyclist_count": sum(
            str(vehicle.get("type") or "").lower() in {"cyclist", "non_motorized"}
            for vehicle in vehicles
        ),
        "pedestrian_count": len(frame.get("pedestrians") or []),
    }


def run(args: argparse.Namespace) -> int:
    frames_path = Path(args.frames).resolve()
    frames = _load_frames(frames_path)
    step_seconds = float(frames[0].get("step_seconds", 0.04) or 0.04)
    if not math.isfinite(step_seconds) or step_seconds <= 0.0:
        step_seconds = 0.04
    map_state = None
    if args.map_state:
        map_path = Path(args.map_state).resolve()
        if map_path.is_file():
            value = json.loads(map_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                map_state = value.get("map_state") if isinstance(value.get("map_state"), dict) else value
    map_state = map_state or _fallback_map_state(frames, args.dataset)

    viewer = HttpApiViewer(
        "replay",
        host=args.host,
        port=args.port,
        gui_dir=args.gui_dir,
        workspace_root=args.workspace_root,
    )
    viewer.set_map_state(map_state)
    viewer.set_scenarios([str(frames_path)])
    metrics_per_frame = [_frame_metrics(frame) for frame in frames]
    viewer.set_replay_metrics(
        {
            "total_steps": len(frames),
            "computed_steps": len(frames),
            "speed_per_step": [metric["avg_speed"] for metric in metrics_per_frame],
            "vehicle_count_per_step": [metric["vehicles"] for metric in metrics_per_frame],
            "min_ttc_per_step": [None] * len(frames),
            "headway_per_step": [None] * len(frames),
            "collision_count_per_step": [None] * len(frames),
            "collision_rate_per_step": [None] * len(frames),
            "speed_samples_per_step": [metric["speed_samples"] for metric in metrics_per_frame],
            "ttc_samples_per_step": [[] for _frame in frames],
            "headway_samples_per_step": [[] for _frame in frames],
            "arrival_rate_per_step": [None] * len(frames),
        }
    )
    stopped = False
    paused = False
    current_step = 0

    def publish(step: int, action: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal current_step
        current_step = max(0, min(int(step), len(frames) - 1))
        frame = frames[current_step]
        state = _frame_state(
            frame,
            include_history=bool((action or {}).get("include_history", True)),
            include_future=bool((action or {}).get("include_future", True)),
        )
        metrics = _frame_metrics(frame)
        viewer.set_sim_state(state)
        viewer.set_status_fields(
            {
                "run_state": "playback",
                "backend_model": "neuralnde",
                "experiment_name": args.experiment_name,
                "scenario": str(frames_path),
                "save_file": str(frames_path),
                "map_path": args.dataset,
                "step": current_step,
                "replay_step": current_step,
                "replay_total_steps": len(frames),
                "total_step": len(frames),
                "sim_resolution": step_seconds,
                "replay_step_seconds": step_seconds,
                "sim_time": float(frame.get("sim_time", current_step * step_seconds)),
                "progress": current_step / max(1, len(frames) - 1),
                "paused": paused,
                **metrics,
            }
        )
        return {"ok": True, **state}

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    publish(0)
    try:
        while not stopped:
            action = viewer.pop_action()
            if action is None:
                viewer.wait_for_action(0.25)
                if viewer.pause_requested:
                    paused = True
                    viewer.set_paused(True)
                if viewer.resume_requested:
                    paused = False
                    viewer.set_paused(False)
                continue
            sync_id = action.get("_sync_id")
            action_type = str(action.get("type") or "").strip().lower()
            if action_type == "replay_seek":
                state = publish(int(action.get("step", current_step) or 0), action)
                viewer.set_action_result(
                    sync_id,
                    {
                        "ok": True,
                        "replay_step": current_step,
                        "total_steps": len(frames),
                        "step_seconds": step_seconds,
                        "sim_state": state,
                    },
                )
            elif action_type == "terminate_experiment":
                viewer.set_action_result(sync_id, {"ok": True, "run_state": "idle"})
                stopped = True
            elif action_type in {"toggle_vehicle_id", "refresh_scenarios"}:
                viewer.set_action_result(sync_id, {"ok": True})
            else:
                viewer.set_action_result(sync_id, {"ok": False, "error": f"Unsupported replay action: {action_type}"})
    finally:
        viewer.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", required=True)
    parser.add_argument("--map-state", default="")
    parser.add_argument("--dataset", default="AA_rdbt")
    parser.add_argument("--experiment-name", default="neuralnde_replay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--gui-dir", default="")
    parser.add_argument("--workspace-root", default="")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
