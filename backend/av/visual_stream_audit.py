"""Validate OmniDreams RGB and BEV frames against the LEAD TFv6 stream contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


TFV6_WIDTH = 1152
TFV6_HEIGHT = 384
TFV6_DECISION_FPS = 10.0


def _traffic_frames(path: Path):
    """Yield traffic frames without retaining a long recording in memory."""
    stream_path = path if path.suffix == ".ndjson" else path.with_suffix(".ndjson")
    if stream_path.is_file():
        with stream_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    raise ValueError(f"Traffic frame {line_number} is not an object")
                yield frame
        return

    frames = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(frames, list):
        raise ValueError("Traffic stream must be a JSON array or NDJSON stream")
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("Traffic stream contains a non-object frame")
        yield frame


class _NearestTrafficFrame:
    """Select nearest monotonically-timed traffic frames in one streaming pass."""

    def __init__(self, path: Path):
        self._frames = iter(_traffic_frames(path))
        try:
            self.current = next(self._frames)
        except StopIteration as exc:
            raise ValueError("Traffic stream must contain at least one frame") from exc
        self.first = self.current
        self.last = self.current
        self._next = next(self._frames, None)

    @staticmethod
    def _time(frame: dict[str, Any]) -> float:
        return float(frame.get("sim_time", 0.0) or 0.0)

    def nearest(self, target_time: float) -> dict[str, Any]:
        while self._next is not None and abs(self._time(self._next) - target_time) <= abs(
            self._time(self.current) - target_time
        ):
            self.current = self._next
            self.last = self.current
            self._next = next(self._frames, None)
        return self.current

    def finish(self) -> dict[str, Any]:
        if self._next is not None:
            self.last = self._next
        for frame in self._frames:
            self.last = frame
        self._next = None
        return self.last


def audit_visual_stream(
    video_path: Path,
    traffic_path: Path,
    output_path: Path,
    *,
    decision_fps: float = TFV6_DECISION_FPS,
) -> dict[str, Any]:
    video_path = video_path.resolve()
    traffic_path = traffic_path.resolve()
    started = time.perf_counter()
    traffic = _NearestTrafficFrame(traffic_path)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise OSError(f"Cannot open visual stream: {video_path}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    source_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    source_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if source_fps <= 0.0:
        capture.release()
        raise ValueError("Visual stream does not report a valid frame rate")

    sample_period = max(1, int(round(source_fps / max(0.1, float(decision_fps)))))
    decoded_frames = 0
    sampled_frames = 0
    blank_samples: list[int] = []
    duplicate_samples: list[int] = []
    bev_matches = 0
    ego_matches = 0
    actor_counts: list[int] = []
    previous_digest = ""
    first_ego = traffic.first.get("ego") if isinstance(traffic.first.get("ego"), dict) else {}
    ego_id = str(traffic.first.get("ego_id") or first_ego.get("id") or "")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frame_index = decoded_frames
            decoded_frames += 1
            if frame_index % sample_period:
                continue
            resized = cv2.resize(frame, (TFV6_WIDTH, TFV6_HEIGHT), interpolation=cv2.INTER_AREA)
            sample_index = sampled_frames
            sampled_frames += 1
            if float(np.std(resized)) < 1.0:
                blank_samples.append(sample_index)
            digest = hashlib.sha256(resized.tobytes()).hexdigest()
            if digest == previous_digest:
                duplicate_samples.append(sample_index)
            previous_digest = digest

            target_time = frame_index / source_fps
            traffic_frame = traffic.nearest(target_time)
            if abs(float(traffic_frame.get("sim_time", 0.0)) - target_time) <= 0.051:
                bev_matches += 1
            vehicles = list(traffic_frame.get("vehicles") or [])
            actors = list(traffic_frame.get("actors") or [])
            traffic_ego = (
                traffic_frame.get("ego") if isinstance(traffic_frame.get("ego"), dict) else {}
            )
            actor_counts.append(len(actors) if actors else max(0, len(vehicles) - 1))
            if ego_id and (
                str(traffic_ego.get("id") or "") == ego_id
                or any(str(vehicle.get("id")) == ego_id for vehicle in vehicles)
            ):
                ego_matches += 1
    finally:
        capture.release()

    duration = decoded_frames / source_fps
    last_traffic_frame = traffic.finish()
    last_traffic_time = float(last_traffic_frame.get("sim_time", 0.0) or 0.0)
    full_contract = {
        "rgb_1152x384": sampled_frames > 0 and not blank_samples,
        "ego_speed": True,
        "bev_actor_stream": bev_matches == sampled_frames and sampled_frames > 0,
        "lidar_history_10": False,
        "radar_sensors_4": False,
        "route_target": False,
        "high_level_command": False,
    }
    missing = [name for name, available in full_contract.items() if not available]
    report = {
        "schema": "denseworld.visual-av-stream-audit.v1",
        "algorithm": "LEAD_TFV6",
        "rgb_source": "cosmos-dreams",
        "video": str(video_path),
        "traffic_stream": str(traffic_path),
        "source": {
            "width": source_width,
            "height": source_height,
            "fps": round(source_fps, 6),
            "decoded_frames": decoded_frames,
            "duration_seconds": round(duration, 6),
        },
        "decision_stream": {
            "width": TFV6_WIDTH,
            "height": TFV6_HEIGHT,
            "fps": round(source_fps / sample_period, 6),
            "sample_period": sample_period,
            "sampled_frames": sampled_frames,
            "blank_sample_indices": blank_samples,
            "duplicate_sample_indices": duplicate_samples,
            "bev_timestamp_matches": bev_matches,
            "ego_present_matches": ego_matches,
            "ego_id": ego_id,
            "mean_surrounding_actors": round(float(np.mean(actor_counts)), 4) if actor_counts else 0.0,
        },
        "tfv6_input_contract": full_contract,
        "missing_inputs": missing,
        "rgb_bev_stream_ready": bool(
            sampled_frames > 0
            and not blank_samples
            and bev_matches == sampled_frames
            and ego_matches == sampled_frames
        ),
        "full_tfv6_contract_met": not missing,
        "tfv6_inference_executed": False,
        "control_effect_guaranteed": False,
        "limitation": (
            "The integrated DenseWorld stream supplies synchronized RGB and BEV actors, but the deployed "
            "TFv6 checkpoint also requires 10-frame LiDAR history, four radars, a route target, and a "
            "high-level command. Official TFv6 inference is therefore kept on its verified CARLA sensor path."
        ),
        "verified_carla_assets": {
            "verification": "/mnt/rk/cnde/autonomous_vehicles/VERIFICATION.md",
            "checkpoint": "/mnt/rk/cnde/autonomous_vehicles/outputs/checkpoints/tfv6_resnet34/model_0030_0.pth",
            "town04_input_video": "/mnt/rk/cnde/autonomous_vehicles/lead_tfv6/outputs/local_evaluation/town04_smoke/Town04_input.mp4",
        },
        "audit_seconds": round(time.perf_counter() - started, 4),
    }
    if not math.isclose(duration, last_traffic_time, abs_tol=0.11):
        report["duration_warning"] = "RGB and traffic stream durations differ by more than one traffic step"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--traffic", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decision-fps", type=float, default=TFV6_DECISION_FPS)
    args = parser.parse_args()
    print(json.dumps(audit_visual_stream(args.video, args.traffic, args.output, decision_fps=args.decision_fps)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
