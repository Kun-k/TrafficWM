#!/usr/bin/env python3
"""Record manager, world-model, and GPU efficiency for one experiment."""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener


TERMINAL_STATES = {"completed", "error", "failed", "stopped", "interrupted", "cancelled"}
DIRECT_HTTP = build_opener(ProxyHandler({}))


def _json_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with DIRECT_HTTP.open(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _gpu_samples() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,utilization.gpu,memory.used,memory.total,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    samples = []
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 5:
            continue
        try:
            samples.append(
                {
                    "index": int(fields[0]),
                    "utilization_percent": float(fields[1]),
                    "memory_used_mib": float(fields[2]),
                    "memory_total_mib": float(fields[3]),
                    "power_w": float(fields[4]),
                }
            )
        except ValueError:
            continue
    return samples


def _nested(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = output.with_name(f"{output.stem}_summary.json")
    stop = False

    def _stop(_signum, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    started = time.time()
    samples: list[dict[str, Any]] = []
    query = urlencode({"experiment_id": args.experiment_id})
    experiment_url = f"{args.manager.rstrip('/')}/experiments?{query}"
    cosmos_url = f"{args.manager.rstrip('/')}/cosmos/status"
    omni_progress = (
        Path(args.workspace).resolve()
        / "output"
        / "cosmos"
        / "experiments"
        / args.experiment_id
        / "omnidreams"
        / "progress.json"
    )
    terminal_observations = 0
    with output.open("a", encoding="utf-8", buffering=1) as stream:
        while not stop:
            experiment_payload = _json_url(experiment_url)
            experiment = experiment_payload.get("experiment") or {}
            status = experiment.get("status") or experiment
            child_port = int(experiment.get("port", 0) or 0)
            if child_port:
                child_status = _json_url(
                    f"http://127.0.0.1:{child_port}/api/v1/status",
                    timeout=2.0,
                )
                if child_status.get("ok", True) and not child_status.get("error"):
                    status = {**status, **child_status}
            world = experiment.get("world_generation") or {}
            cosmos = _json_url(cosmos_url)
            progress = {}
            try:
                if omni_progress.is_file():
                    progress = json.loads(omni_progress.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                progress = {}
            sample = {
                "schema": "trafficwm.experiment-efficiency-sample.v1",
                "wall_time_unix": time.time(),
                "elapsed_seconds": round(time.time() - started, 3),
                "experiment_id": args.experiment_id,
                "traffic": {
                    "run_state": str(status.get("run_state") or experiment.get("run_state") or ""),
                    "step": int(status.get("step", experiment.get("step", 0)) or 0),
                    "sim_time": float(status.get("sim_time", experiment.get("sim_time", 0.0)) or 0.0),
                    "vehicles": int(status.get("vehicles", experiment.get("vehicles", 0)) or 0),
                    "world_local_vehicle_count": int(status.get("world_local_vehicle_count", 0) or 0),
                    "world_loop_route_pins": int(status.get("world_loop_route_pins", 0) or 0),
                    "world_loop_corridor_corrections": int(
                        status.get("world_loop_corridor_corrections", 0) or 0
                    ),
                    "world_loop_projection_rollouts": int(
                        status.get("world_loop_projection_rollouts", 0) or 0
                    ),
                    "world_loop_projection_max_m": float(
                        status.get("world_loop_projection_max_m", 0.0) or 0.0
                    ),
                    "collision_count": int(status.get("collision_count", 0) or 0),
                },
                "world": {
                    "run_state": str(world.get("run_state") or ""),
                    "stage": str(world.get("stage") or ""),
                    "progress": float(world.get("progress", 0.0) or 0.0),
                },
                "omnidreams": {
                    "stage": str(progress.get("stage") or ""),
                    "frames": int(progress.get("frames", 0) or 0),
                    "generated_video_time": float(progress.get("generated_video_time", 0.0) or 0.0),
                    "measured_generation_fps": float(progress.get("measured_generation_fps", 0.0) or 0.0),
                    "recent_generation_fps": float(progress.get("recent_generation_fps", 0.0) or 0.0),
                    "end_to_end_fps": float(progress.get("end_to_end_fps", 0.0) or 0.0),
                    "session_index": int(progress.get("session_index", 0) or 0),
                    "traffic_wait_seconds": float(progress.get("traffic_wait_seconds", 0.0) or 0.0),
                },
                "runtime": {
                    "ready": bool(cosmos.get("ready")),
                    "transfer_state": str(_nested(cosmos, "transfer", "run_state", default="")),
                    "omnidreams_state": str(_nested(cosmos, "omnidreams", "run_state", default="")),
                },
                "gpus": _gpu_samples(),
            }
            stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
            samples.append(sample)
            traffic_terminal = sample["traffic"]["run_state"] in TERMINAL_STATES
            world_terminal = (
                sample["world"]["run_state"] in TERMINAL_STATES
                or sample["omnidreams"]["stage"] in TERMINAL_STATES
            )
            terminal_observations = terminal_observations + 1 if traffic_terminal and world_terminal else 0
            if terminal_observations >= 2:
                break
            time.sleep(max(1.0, float(args.interval)))

    sim_samples = [sample for sample in samples if sample["traffic"]["sim_time"] > 0.0]
    sim_speed = 0.0
    if len(sim_samples) >= 2:
        wall_delta = sim_samples[-1]["wall_time_unix"] - sim_samples[0]["wall_time_unix"]
        sim_delta = sim_samples[-1]["traffic"]["sim_time"] - sim_samples[0]["traffic"]["sim_time"]
        sim_speed = sim_delta / wall_delta if wall_delta > 0 else 0.0
    gpu_rows: dict[int, list[dict[str, Any]]] = {}
    for sample in samples:
        for gpu in sample["gpus"]:
            gpu_rows.setdefault(int(gpu["index"]), []).append(gpu)
    gpu_summary = {
        str(index): {
            "samples": len(rows),
            "utilization_mean_percent": round(
                sum(row["utilization_percent"] for row in rows) / len(rows), 3
            ),
            "memory_used_peak_mib": max(row["memory_used_mib"] for row in rows),
            "power_mean_w": round(sum(row["power_w"] for row in rows) / len(rows), 3),
        }
        for index, rows in sorted(gpu_rows.items())
        if rows
    }
    summary = {
        "schema": "trafficwm.experiment-efficiency-summary.v1",
        "experiment_id": args.experiment_id,
        "sample_count": len(samples),
        "wall_seconds": round(time.time() - started, 3),
        "traffic_sim_seconds_per_wall_second": round(sim_speed, 6),
        "last_sample": samples[-1] if samples else {},
        "gpu_summary": gpu_summary,
        "samples_path": str(output),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--manager", default="http://127.0.0.1:8890")
    parser.add_argument("--workspace", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
