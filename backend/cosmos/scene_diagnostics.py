"""Build non-production RDS-HQ ablations for visual control diagnostics."""
from __future__ import annotations

import argparse
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any


def _read_json_tar(path: Path) -> tuple[str, dict[str, Any]]:
    with tarfile.open(path, "r") as archive:
        member = next(item for item in archive.getmembers() if item.name.endswith(".json"))
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError(f"Cannot read {member.name} from {path}")
        return member.name, json.load(stream)


def _write_json_tar(path: Path, member_name: str, payload: dict[str, Any]) -> None:
    import io

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))


def _filter_object_tar(path: Path) -> tuple[int, int]:
    import io

    members: list[tuple[tarfile.TarInfo, bytes]] = []
    before_ids: set[str] = set()
    after_ids: set[str] = set()
    with tarfile.open(path, "r") as source:
        for member in source.getmembers():
            stream = source.extractfile(member) if member.isfile() else None
            raw = stream.read() if stream is not None else b""
            if member.name.endswith(".json"):
                objects = json.loads(raw.decode("utf-8"))
                before_ids.update(str(track_id) for track_id in objects)
                objects = {
                    track_id: value
                    for track_id, value in objects.items()
                    if str(value.get("object_type") or "") not in {"Pedestrian", "Cyclist"}
                }
                after_ids.update(str(track_id) for track_id in objects)
                raw = json.dumps(
                    objects,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            clone = tarfile.TarInfo(member.name)
            clone.mode = member.mode
            clone.mtime = member.mtime
            clone.size = len(raw)
            members.append((clone, raw))

    with tarfile.open(path, "w") as target:
        for member, raw in members:
            target.addfile(member, io.BytesIO(raw) if member.isfile() else None)
    return len(before_ids), len(after_ids)


def build_ablation(source: Path, target: Path, clip_id: str, mode: str) -> dict[str, Any]:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)

    object_path = target / "all_object_info" / f"{clip_id}.tar"
    before, after = _filter_object_tar(object_path)

    emptied: list[str] = []
    if mode == "road_vehicle_only":
        for directory, key in (
            ("3d_traffic_lights", "labels"),
            ("3d_poles", "labels"),
            ("3d_crosswalks", "labels"),
            ("3d_wait_lines", "labels"),
        ):
            path = target / directory / f"{clip_id}.tar"
            tar_member, payload = _read_json_tar(path)
            payload[key] = []
            _write_json_tar(path, tar_member, payload)
            emptied.append(directory)
        status_path = target / "3d_traffic_lights_status" / f"{clip_id}.tar"
        status_member, status_payload = _read_json_tar(status_path)
        status_payload["traffic_light_states"] = {}
        _write_json_tar(status_path, status_member, status_payload)
        emptied.append("3d_traffic_lights_status")

    return {
        "mode": mode,
        "source": str(source),
        "target": str(target),
        "objects_before": before,
        "objects_after": after,
        "emptied_channels": emptied,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--mode", choices=("no_pedestrian", "road_vehicle_only"), required=True)
    args = parser.parse_args()
    print(json.dumps(build_ablation(args.source, args.target, args.clip_id, args.mode), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
