#!/usr/bin/env python3
"""Preserve rolling OmniDreams preview frames for long-run visual QA."""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


TERMINAL_STAGES = {"completed", "error", "failed", "stopped", "cancelled"}
BOUNDARY_OFFSETS = (-8, -4, -1, 0, 1, 4, 8)


def _read_progress(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _copy_frame(source_dir: Path, output_dir: Path, frame: int, name: str) -> bool:
    source = source_dir / f"{frame:08d}.jpg"
    target = output_dir / name
    if target.exists() or not source.is_file():
        return False
    shutil.copy2(source, target)
    return True


def run(args: argparse.Namespace) -> int:
    progress_path = Path(args.progress).expanduser().resolve()
    source_dir = Path(args.frames_dir).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "watcher.jsonl"
    milestone_seconds = sorted({max(0, int(value)) for value in args.milestones.split(",") if value.strip()})

    while True:
        progress = _read_progress(progress_path)
        copied: list[str] = []
        for session in progress.get("sessions") or []:
            try:
                start = int(session.get("start_frame", 0))
            except (AttributeError, TypeError, ValueError):
                continue
            for offset in BOUNDARY_OFFSETS:
                frame = start + offset
                if frame < 0:
                    continue
                name = f"session_{start:06d}_offset_{offset:+03d}.jpg"
                if _copy_frame(source_dir, output_dir, frame, name):
                    copied.append(name)

        fps = max(1, int(progress.get("fps", args.fps) or args.fps))
        for seconds in milestone_seconds:
            frame = seconds * fps
            name = f"milestone_{seconds:04d}s.jpg"
            if _copy_frame(source_dir, output_dir, frame, name):
                copied.append(name)

        sample = {
            "wall_time_unix": time.time(),
            "stage": str(progress.get("stage") or ""),
            "frames": int(progress.get("frames", 0) or 0),
            "generated_video_time": float(progress.get("generated_video_time", 0.0) or 0.0),
            "session_index": int(progress.get("session_index", 0) or 0),
            "copied": copied,
        }
        if copied or sample["stage"] in TERMINAL_STAGES:
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(sample, ensure_ascii=False) + "\n")
        if sample["stage"] in TERMINAL_STAGES:
            return 0
        time.sleep(max(0.2, float(args.interval)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", required=True)
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--milestones",
        default="30,60,120,300,600,900,1200,1500,1800,1995",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
