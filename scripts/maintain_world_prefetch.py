#!/usr/bin/env python3
"""Keep a bounded traffic lead so simulation and world generation can overlap."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from backend.cosmos.world_sync import update_world_sync


TERMINAL_STAGES = {"completed", "error", "failed", "stopped", "cancelled"}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def run(args: argparse.Namespace) -> int:
    progress_path = Path(args.progress).expanduser().resolve()
    sync_path = Path(args.sync).expanduser().resolve()
    log_path = Path(args.log).expanduser().resolve() if args.log else None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    lead_seconds = max(0.0, float(args.lead_seconds))

    while True:
        progress = _read_json(progress_path)
        stage = str(progress.get("stage") or "")
        if stage in TERMINAL_STAGES:
            return 0
        if progress:
            required_time = float(progress.get("required_traffic_time", 0.0) or 0.0)
            requested_time = required_time + lead_seconds
            target_frames = progress.get("target_frames")
            fps = float(progress.get("fps", 30.0) or 30.0)
            start_time = float(progress.get("traffic_start_time_seconds", 0.0) or 0.0)
            if target_frames is not None and fps > 0.0:
                requested_time = min(
                    requested_time,
                    start_time + float(target_frames) / fps,
                )
            sync = update_world_sync(
                sync_path,
                requested_traffic_time=requested_time,
            )
            if log_path is not None:
                sample = {
                    "wall_time_unix": time.time(),
                    "stage": stage,
                    "required_traffic_time": required_time,
                    "requested_traffic_time": float(
                        sync.get("requested_traffic_time", 0.0) or 0.0
                    ),
                    "generated_video_time": float(
                        sync.get("generated_video_time", 0.0) or 0.0
                    ),
                    "lead_seconds": lead_seconds,
                }
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
        time.sleep(max(0.05, float(args.interval)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", required=True)
    parser.add_argument("--sync", required=True)
    parser.add_argument("--lead-seconds", type=float, default=1.0)
    parser.add_argument("--interval", type=float, default=0.2)
    parser.add_argument("--log", default="")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
