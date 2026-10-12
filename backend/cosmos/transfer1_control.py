"""Render Transfer1 HDMap controls with the official Cosmos-Drive-Dreams toolkit."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from backend.cosmos.pipeline_utils import probe_video


TRANSFER1_CAMERA = "camera_front_wide_120fov"


def _tail(path: Path, limit: int = 6000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def render_transfer1_hdmap_control(
    scene_root: Path,
    output_root: Path,
    *,
    clip_id: str,
    expected_frames: int,
) -> dict:
    """Run the official traditional HDMap renderer and normalize its output path."""
    project_root = Path(__file__).resolve().parents[2]
    drive_root = Path(
        os.environ.get("COSMOS_TRANSFER1_ROOT", "/mnt/rk/cosmos/Cosmos-Drive-Dreams")
    ).expanduser().resolve()
    python = drive_root / ".venv" / "bin" / "python"
    toolkits = drive_root / "cosmos-drive-dreams-toolkits"
    worker = Path(__file__).with_name("transfer1_control_worker.py")
    if not python.is_file():
        raise FileNotFoundError(f"Transfer1 Python environment not found: {python}")
    if not (toolkits / "render_from_rds_hq.py").is_file():
        raise FileNotFoundError(f"Transfer1 HDMap renderer not found: {toolkits}")

    scene_root = Path(scene_root).resolve()
    output_root = Path(output_root).resolve()
    native_root = output_root / "official_renderer"
    native_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "transfer1_hdmap_render.json"
    log_path = output_root / "transfer1_hdmap_render.log"
    command = [
        str(python),
        str(worker),
        "--toolkit-root",
        str(toolkits),
        "--scene-root",
        str(scene_root),
        "--output-root",
        str(native_root),
        "--clip-id",
        str(clip_id),
        "--frames",
        str(max(1, int(expected_frames))),
        "--manifest",
        str(manifest_path),
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "USE_RAY": "False",
            "PYTHONPATH": os.pathsep.join(
                [str(toolkits), str(project_root), environment.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep),
            "PYTHONUNBUFFERED": "1",
        }
    )
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log_stream:
        result = subprocess.run(
            command,
            cwd=toolkits,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=max(
                120.0,
                float(os.environ.get("COSMOS_TRANSFER1_RENDER_TIMEOUT_SECONDS", "1800")),
            ),
            check=False,
        )
    seconds = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(
            f"Official Transfer1 HDMap renderer exited with code {result.returncode}: "
            f"{_tail(log_path)}"
        )
    if not manifest_path.is_file():
        raise RuntimeError("Official Transfer1 HDMap renderer did not write its manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    native_video = Path(str(manifest.get("output_video") or "")).resolve()
    if not native_video.is_file():
        raise FileNotFoundError(f"Official Transfer1 HDMap output is missing: {native_video}")

    canonical = output_root / clip_id / f"{clip_id}.{TRANSFER1_CAMERA}.mp4"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(native_video, canonical)
    media = probe_video(canonical)
    if int(media["frames"]) != max(1, int(expected_frames)):
        raise RuntimeError(
            f"Official Transfer1 HDMap control has {int(media['frames'])} frames; "
            f"expected {max(1, int(expected_frames))}"
        )
    if abs(float(media["fps"]) - 30.0) > 0.02:
        raise RuntimeError(
            f"Official Transfer1 HDMap control FPS is {float(media['fps']):g}; expected 30"
        )
    return {
        "seconds": seconds,
        "mode": "official_transfer1_hdmap",
        "camera": TRANSFER1_CAMERA,
        "output_video": str(canonical),
        "media": media,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
        "log_path": str(log_path),
    }
