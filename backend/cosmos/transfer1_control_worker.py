"""Subprocess entry point for the official Cosmos-Drive-Dreams HDMap renderer."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
from pathlib import Path


CAMERA = "camera_front_wide_120fov"
CAMERA_MODEL = "ftheta"
OFFICIAL_LAYER_ORDER = (
    "lanelines",
    "lanes",
    "road_boundaries",
    "crosswalks",
    "road_markings",
    "wait_lines",
    "poles",
    "traffic_signs",
    "traffic_lights",
)


def _route_lane_controls_enabled(scene_root: Path) -> bool:
    report_path = scene_root / "trafficwm_export_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    strategy = str((report.get("lane_topology") or {}).get("strategy") or "")
    return strategy == "ego-path-matched-virtual-lane-rails"


def _sample_key(tar_path: Path) -> str:
    with tarfile.open(tar_path, "r") as archive:
        member = next(item for item in archive.getmembers() if item.name.endswith(".json"))
    parts = Path(member.name).name.split(".")
    return ".".join(parts[1:]) if len(parts) > 2 else Path(member.name).name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit-root", type=Path, required=True)
    parser.add_argument("--scene-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    os.environ["USE_RAY"] = "False"
    toolkit_root = args.toolkit_root.resolve()
    sys.path.insert(0, str(toolkit_root))
    from render_from_rds_hq import render_sample_hdmap

    scene_root = args.scene_root.resolve()
    route_lane_controls_enabled = _route_lane_controls_enabled(scene_root)
    available_layers: list[str] = []
    skipped_layers: dict[str, str] = {}
    for layer in OFFICIAL_LAYER_ORDER:
        if layer == "lanes" and not route_lane_controls_enabled:
            skipped_layers[layer] = "not ego-path-matched"
            continue
        source = scene_root / f"3d_{layer}" / f"{args.clip_id}.tar"
        if not source.is_file():
            skipped_layers[layer] = "missing"
            continue
        key = _sample_key(source)
        if key != f"{layer}.json":
            skipped_layers[layer] = f"unexpected sample key {key}"
            continue
        available_layers.append(layer)
    if not {"lanelines", "road_boundaries"}.intersection(available_layers):
        raise RuntimeError("Transfer1 HDMap rendering requires lane or road-boundary geometry")

    frame_count = max(1, int(args.frames))
    settings = {
        "CAMERAS": [CAMERA],
        "MINIMAP_TYPES": available_layers,
        "INPUT_POSE_FPS": 30,
        "NOT_POST_TRAINING": {
            "TARGET_RENDER_FPS": 30,
            "TARGET_CHUNK_FRAME": frame_count,
            "OVERLAP_FRAME": 0,
            "MAX_CHUNK": 1,
            "TO_COSMOS_RESOLUTION": "resize",
        },
        "POST_TRAINING": {
            "TARGET_RENDER_FPS": 30,
            "TARGET_CHUNK_FRAME": frame_count,
            "OVERLAP_FRAME": 0,
            "MAX_CHUNK": 1,
            "TO_COSMOS_RESOLUTION": "center-crop",
        },
    }
    output_root = args.output_root.resolve()
    render_sample_hdmap(
        str(scene_root),
        str(output_root),
        args.clip_id,
        settings,
        CAMERA_MODEL,
        False,
        None,
        (1280, 720),
        (1280, 704),
    )
    output_video = (
        output_root
        / "hdmap"
        / f"{CAMERA_MODEL}_{CAMERA}"
        / f"{args.clip_id}_0.mp4"
    )
    if not output_video.is_file():
        raise FileNotFoundError(f"Official HDMap renderer produced no video: {output_video}")
    manifest = {
        "schema": "trafficwm.transfer1-official-hdmap.v1",
        "renderer": str(toolkit_root / "render_from_rds_hq.py"),
        "clip_id": args.clip_id,
        "camera": CAMERA,
        "camera_model": CAMERA_MODEL,
        "frames": frame_count,
        "fps": 30,
        "layers": available_layers,
        "skipped_layers": skipped_layers,
        "output_video": str(output_video),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
