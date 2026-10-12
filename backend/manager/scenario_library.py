"""Build reusable CityNDE library clips without changing recording semantics."""
from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


LIBRARY_CATEGORIES = {"normal", "pedestrian", "cyclist"}


def _step_sha256(recording: dict[str, Any], step: int) -> str:
    id_steps = recording.get("vehicle_id_per_step")
    if id_steps is None or not len(id_steps):
        return ""
    index = step if step >= 0 else len(id_steps) + step
    if index < 0 or index >= len(id_steps):
        return ""
    payload = {}
    for key, value in recording.items():
        if not str(key).endswith("_per_step"):
            continue
        if len(value) <= index:
            return ""
        payload[str(key)] = value[index]
    return hashlib.sha256(
        pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    ).hexdigest()


def _vehicle_ids(recording: dict[str, Any], step: int) -> set[str]:
    steps = recording.get("vehicle_id_per_step")
    if steps is None or not len(steps):
        return set()
    index = step if step >= 0 else len(steps) + step
    if index < 0 or index >= len(steps):
        return set()
    return {str(actor_id) for actor_id in steps[index]}


def inspect_scenario_seed_bundle(
    scenario_path: Path,
    metadata: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    """Validate that a reusable RGB seed belongs to the exact scenario boundary."""
    scenario_path = Path(scenario_path).resolve()
    workspace_root = Path(workspace_root).resolve()

    def unavailable(status: str, reason: str) -> dict[str, Any]:
        return {
            "available": False,
            "status": status,
            "reason": reason,
            "image_path": "",
            "initialization_path": "",
        }

    if not bool(metadata.get("use_existing_seed")):
        return unavailable(
            "missing",
            str(metadata.get("seed_failure_reason") or "No matched RGB first frame is stored"),
        )
    required = {
        "seed_image": str(metadata.get("seed_image") or "").strip(),
        "seed_init_file": str(metadata.get("seed_init_file") or "").strip(),
        "seed_ego_id": str(metadata.get("seed_ego_id") or "").strip(),
        "seed_sha256": str(metadata.get("seed_sha256") or "").strip(),
        "seed_init_sha256": str(metadata.get("seed_init_sha256") or "").strip(),
        "seed_state_sha256": str(metadata.get("seed_state_sha256") or "").strip(),
    }
    if any(not value for value in required.values()):
        return unavailable("incomplete", "Reusable first-frame metadata is incomplete")

    def resolve(reference: str) -> Path:
        target = Path(reference)
        return (target if target.is_absolute() else workspace_root / target).resolve()

    image_path = resolve(required["seed_image"])
    initialization_path = resolve(required["seed_init_file"])
    try:
        image_path.relative_to(workspace_root)
        initialization_path.relative_to(workspace_root)
    except ValueError:
        return unavailable("invalid", "First-frame files are outside the workspace")
    if image_path != scenario_path.with_suffix(".seed.png"):
        return unavailable("invalid", "RGB first frame is not adjacent to its scenario")
    if initialization_path != scenario_path.with_suffix(".init.pkl"):
        return unavailable("invalid", "Initialization history is not adjacent to its scenario")
    if not image_path.is_file() or image_path.stat().st_size <= 0:
        return unavailable("missing", "RGB first-frame file is missing")
    if not initialization_path.is_file() or initialization_path.stat().st_size <= 0:
        return unavailable("missing", "First-frame initialization history is missing")
    if hashlib.sha256(image_path.read_bytes()).hexdigest() != required["seed_sha256"]:
        return unavailable("invalid", "RGB first-frame checksum does not match metadata")
    if hashlib.sha256(initialization_path.read_bytes()).hexdigest() != required["seed_init_sha256"]:
        return unavailable("invalid", "Initialization-history checksum does not match metadata")
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        return unavailable("invalid", f"RGB first-frame image is unreadable: {exc}")
    if width < 640 or height < 352:
        return unavailable("invalid", f"RGB first frame is too small ({width}x{height})")
    if abs(width / max(1, height) - 1280.0 / 704.0) > 0.12:
        return unavailable("invalid", "RGB first-frame aspect ratio does not match 1280:704")

    try:
        with scenario_path.open("rb") as stream:
            scenario = pickle.load(stream)
        with initialization_path.open("rb") as stream:
            initialization = pickle.load(stream)
        initialization_steps = len(initialization.get("vehicle_id_per_step") or [])
        scenario_hash = _step_sha256(scenario, 0)
        initialization_hash = _step_sha256(initialization, -1)
    except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
        return unavailable("invalid", f"First-frame state validation failed: {exc}")
    if initialization_steps != 11:
        return unavailable("invalid", "First-frame initialization history must contain 11 states")
    if (
        not scenario_hash
        or scenario_hash != initialization_hash
        or scenario_hash != required["seed_state_sha256"]
    ):
        return unavailable("invalid", "RGB first-frame state does not match scenario frame 0")
    ego_id = required["seed_ego_id"]
    if ego_id not in _vehicle_ids(scenario, 0) or ego_id not in _vehicle_ids(initialization, -1):
        return unavailable("invalid", "First-frame camera ego is absent from the scenario boundary")
    return {
        "available": True,
        "status": "ready",
        "reason": "Matched RGB first frame and CityNDE initialization history are ready",
        "image_path": required["seed_image"],
        "initialization_path": required["seed_init_file"],
        "source": str(metadata.get("seed_source") or ""),
        "source_experiment_id": str(metadata.get("seed_source_experiment_id") or ""),
        "source_time_seconds": float(metadata.get("seed_source_time_seconds", 0.0) or 0.0),
        "ego_id": ego_id,
        "width": int(width),
        "height": int(height),
    }


def _recording_resolution(recording: dict[str, Any]) -> float:
    simulator = recording.get("simulator_meta_info") or {}
    for value in (simulator.get("resolution"), simulator.get("sim_resolution")):
        try:
            resolution = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(resolution) and resolution > 0.0:
            return resolution
    return 0.1


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "").strip()).strip("._-")
    return (stem or "standard_scenario")[:72]


def _actor_counts(recording: dict[str, Any]) -> dict[str, int]:
    vehicle_ids = {
        str(actor_id)
        for step in recording.get("vehicle_id_per_step") or []
        for actor_id in step
    }
    pedestrian_ids = {
        str(actor_id)
        for step in recording.get("pedestrian_id_per_step") or []
        for actor_id in step
    }
    actor_types = {
        str(actor_id): str(actor_type).lower()
        for actor_id, actor_type in (recording.get("road_user_type") or {}).items()
    }
    cyclists = {
        actor_id
        for actor_id in vehicle_ids
        if "cycl" in actor_types.get(actor_id, "")
    }
    embedded_pedestrians = {
        actor_id
        for actor_id in vehicle_ids
        if "ped" in actor_types.get(actor_id, "")
    }
    return {
        "motorized": len(vehicle_ids - cyclists - embedded_pedestrians),
        "pedestrians": len(pedestrian_ids | embedded_pedestrians),
        "cyclists": len(cyclists),
    }


def prune_citynde_recording_vehicles(
    recording: dict[str, Any],
    *,
    remove_ids: set[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Remove selected vehicles while preserving aligned CityNDE step streams."""
    removed = {str(actor_id) for actor_id in remove_ids}
    if not removed:
        return dict(recording), {
            "removed_ids": [],
            "vehicle_count_before": len((recording.get("vehicle_id_per_step") or [[]])[0]),
            "vehicle_count_after": len((recording.get("vehicle_id_per_step") or [[]])[0]),
        }
    id_steps = recording.get("vehicle_id_per_step")
    state_steps = recording.get("vehicle_state_per_step")
    if not isinstance(id_steps, (list, tuple)) or not isinstance(state_steps, (list, tuple)):
        raise ValueError("Recording has no aligned vehicle step streams")
    if len(id_steps) != len(state_steps):
        raise ValueError("Vehicle ID and state streams have different frame counts")

    pruned = dict(recording)
    pruned_ids = []
    pruned_states = []
    for frame_index, (actor_ids, actor_states) in enumerate(zip(id_steps, state_steps)):
        if len(actor_ids) != len(actor_states):
            raise ValueError(
                f"Vehicle ID and state counts differ at frame {frame_index}"
            )
        keep_indices = [
            index
            for index, actor_id in enumerate(actor_ids)
            if str(actor_id) not in removed
        ]
        pruned_ids.append([actor_ids[index] for index in keep_indices])
        if hasattr(actor_states, "shape"):
            pruned_states.append(actor_states[keep_indices])
        else:
            pruned_states.append([actor_states[index] for index in keep_indices])
    pruned["vehicle_id_per_step"] = pruned_ids
    pruned["vehicle_state_per_step"] = pruned_states

    for key in (
        "vehicle_static_attribute",
        "road_user_type",
        "vehicle_class",
        "vehicle_type",
    ):
        values = recording.get(key)
        if isinstance(values, dict):
            pruned[key] = {
                actor_id: value
                for actor_id, value in values.items()
                if str(actor_id) not in removed
            }

    before = len(id_steps[0]) if id_steps else 0
    after = len(pruned_ids[0]) if pruned_ids else 0
    return pruned, {
        "removed_ids": sorted(removed),
        "vehicle_count_before": before,
        "vehicle_count_after": after,
        "participants": _actor_counts(pruned),
    }


def slice_citynde_recording(
    recording: dict[str, Any],
    *,
    start_seconds: float,
    end_seconds: float,
    operational_offset_steps: int = 0,
    max_duration_seconds: float = 100.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Slice every ``*_per_step`` stream while retaining static map and actor data."""
    if not isinstance(recording, dict):
        raise ValueError("CityNDE recording must be a dictionary")
    vehicle_steps = recording.get("vehicle_id_per_step")
    if not isinstance(vehicle_steps, (list, tuple)) or len(vehicle_steps) < 2:
        raise ValueError("Recording has no usable vehicle_id_per_step stream")
    resolution = _recording_resolution(recording)
    operational_offset = max(0, int(operational_offset_steps or 0))
    if operational_offset >= len(vehicle_steps) - 1:
        raise ValueError("Recording operational offset exceeds the available timeline")
    available_seconds = (len(vehicle_steps) - 1 - operational_offset) * resolution
    start = float(start_seconds)
    end = float(end_seconds)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("Scenario time range must be finite")
    if start < 0.0 or end <= start:
        raise ValueError("Scenario end time must be greater than start time")
    if end - start > float(max_duration_seconds) + 1e-9:
        raise ValueError(f"Scenario clips are limited to {float(max_duration_seconds):g}s")
    if end > available_seconds + resolution * 0.5:
        raise ValueError(
            f"Requested end time {end:g}s exceeds recording duration {available_seconds:g}s"
        )

    requested_start_index = max(0, int(round(start / resolution)))
    requested_end_index = min(
        len(vehicle_steps) - 1 - operational_offset,
        int(round(end / resolution)),
    )
    if requested_end_index <= requested_start_index:
        raise ValueError("Scenario time range contains fewer than two frames")
    start_index = operational_offset + requested_start_index
    end_index = operational_offset + requested_end_index

    sliced = dict(recording)
    for key, value in recording.items():
        if not str(key).endswith("_per_step"):
            continue
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"Recording field {key} is not a step sequence")
        if len(value) != len(vehicle_steps):
            raise ValueError(
                f"Recording field {key} has {len(value)} steps; expected {len(vehicle_steps)}"
            )
        sliced[key] = list(value[start_index : end_index + 1])

    simulator = dict(recording.get("simulator_meta_info") or {})
    simulator["trafficwm_library_slice"] = {
        "start_seconds": round(requested_start_index * resolution, 6),
        "end_seconds": round(requested_end_index * resolution, 6),
        "recording_start_step": start_index,
        "recording_end_step": end_index,
        "source_steps": len(vehicle_steps),
    }
    sliced["simulator_meta_info"] = simulator
    actual_duration = (end_index - start_index) * resolution
    summary = {
        "resolution": resolution,
        "source_frames": len(vehicle_steps),
        "start_step": requested_start_index,
        "end_step": requested_end_index,
        "recording_start_step": start_index,
        "recording_end_step": end_index,
        "frame_count": end_index - start_index + 1,
        "duration_seconds": round(actual_duration, 6),
        "participants": _actor_counts(sliced),
    }
    return sliced, summary


def create_standard_scenario(
    source_path: Path,
    library_root: Path,
    *,
    name: str,
    category: str,
    description: str,
    start_seconds: float,
    end_seconds: float,
    source_reference: str,
    source_metadata: dict[str, Any] | None = None,
    max_duration_seconds: float = 100.0,
) -> dict[str, Any]:
    source_path = Path(source_path).resolve()
    library_root = Path(library_root).resolve()
    if not source_path.is_file():
        raise ValueError("Source scenario file does not exist")
    category = str(category or "").strip().lower()
    if category not in LIBRARY_CATEGORIES:
        raise ValueError("Scenario category must be normal, pedestrian, or cyclist")
    display_name = str(name or "").strip()
    if not display_name:
        raise ValueError("Scenario name is required")
    if len(display_name) > 80:
        raise ValueError("Scenario name must not exceed 80 characters")

    with source_path.open("rb") as stream:
        source = pickle.load(stream)
    sliced, summary = slice_citynde_recording(
        source,
        start_seconds=float(start_seconds),
        end_seconds=float(end_seconds),
        operational_offset_steps=int(
            (source_metadata or {}).get("recording_operational_start_step", 0) or 0
        ),
        max_duration_seconds=float(max_duration_seconds),
    )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    library_id = f"custom-{stamp}-{suffix}"
    target = library_root / f"{_safe_stem(display_name)}_{suffix}.pkl"
    library_root.mkdir(parents=True, exist_ok=True)

    metadata = dict(source_metadata or {})
    for key in ("library_id", "library_name", "library_description", "library_category"):
        metadata.pop(key, None)
    for key in list(metadata):
        if key == "use_existing_seed" or str(key).startswith("seed_"):
            metadata.pop(key, None)
    metadata.update(
        {
            "library_id": library_id,
            "library_name": display_name,
            "library_description": str(description or "").strip(),
            "library_category": category,
            "library_tags": ["generated", category, "time-window"],
            "source_path": str(source_reference),
            "source_start_seconds": summary["start_step"] * summary["resolution"],
            "source_end_seconds": summary["end_step"] * summary["resolution"],
            "sim_resolution": summary["resolution"],
            "total_step": summary["frame_count"] - 1,
            "max_sim_time": summary["duration_seconds"],
            "recording_operational_start_step": 0,
            "participants": summary["participants"],
            "use_existing_seed": False,
            "seed_image": "",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    temp_recording = target.with_suffix(target.suffix + ".tmp")
    temp_metadata = target.with_suffix(target.suffix + ".meta.json.tmp")
    metadata_path = target.with_suffix(target.suffix + ".meta.json")
    try:
        with temp_recording.open("wb") as stream:
            pickle.dump(sliced, stream, protocol=pickle.HIGHEST_PROTOCOL)
            stream.flush()
            os.fsync(stream.fileno())
        temp_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_recording.replace(target)
        temp_metadata.replace(metadata_path)
    finally:
        temp_recording.unlink(missing_ok=True)
        temp_metadata.unlink(missing_ok=True)

    return {
        "library_id": library_id,
        "path": target,
        "metadata_path": metadata_path,
        "metadata": metadata,
        **summary,
    }


def create_accident_scenario(
    source_path: Path,
    accident_root: Path,
    *,
    accident_id: str,
    name: str,
    start_seconds: float,
    end_seconds: float,
    source_reference: str,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a confirmed AV collision window as a standalone replayable PKL."""
    source_path = Path(source_path).resolve()
    accident_root = Path(accident_root).resolve()
    if not source_path.is_file():
        raise ValueError("Source scenario file does not exist")
    display_name = str(name or "").strip() or str(accident_id)
    with source_path.open("rb") as stream:
        source = pickle.load(stream)
    resolution = _recording_resolution(source)
    frame_count = len(source.get("vehicle_id_per_step") or [])
    operational_offset = int(
        (source_metadata or {}).get("recording_operational_start_step", 0) or 0
    )
    available_seconds = max(0.0, (frame_count - 1 - operational_offset) * resolution)
    requested_duration = max(0.1, float(end_seconds) - float(start_seconds))
    clipped_end = min(float(end_seconds), available_seconds)
    clipped_start = max(0.0, float(start_seconds))
    if clipped_start >= clipped_end:
        clipped_start = max(0.0, clipped_end - min(5.0, requested_duration))
    sliced, summary = slice_citynde_recording(
        source,
        start_seconds=clipped_start,
        end_seconds=clipped_end,
        operational_offset_steps=operational_offset,
    )

    suffix = uuid.uuid4().hex[:6]
    target = accident_root / f"{_safe_stem(display_name)}_{suffix}.pkl"
    accident_root.mkdir(parents=True, exist_ok=True)
    metadata = dict(source_metadata or {})
    for key in (
        "library_id",
        "library_name",
        "library_description",
        "library_category",
        "library_tags",
    ):
        metadata.pop(key, None)
    for key in list(metadata):
        if key == "use_existing_seed" or str(key).startswith("seed_"):
            metadata.pop(key, None)
    metadata.update(
        {
            "kind": "accident_scenario",
            "accident_id": str(accident_id),
            "accident_name": display_name[:80],
            "source_path": str(source_reference),
            "source_start_seconds": summary["start_step"] * summary["resolution"],
            "source_end_seconds": summary["end_step"] * summary["resolution"],
            "sim_resolution": summary["resolution"],
            "total_step": summary["frame_count"] - 1,
            "max_sim_time": summary["duration_seconds"],
            "recording_operational_start_step": 0,
            "participants": summary["participants"],
            "use_existing_seed": False,
            "seed_image": "",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    temp_recording = target.with_suffix(target.suffix + ".tmp")
    temp_metadata = target.with_suffix(target.suffix + ".meta.json.tmp")
    metadata_path = target.with_suffix(target.suffix + ".meta.json")
    try:
        with temp_recording.open("wb") as stream:
            pickle.dump(sliced, stream, protocol=pickle.HIGHEST_PROTOCOL)
            stream.flush()
            os.fsync(stream.fileno())
        temp_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_recording.replace(target)
        temp_metadata.replace(metadata_path)
    finally:
        temp_recording.unlink(missing_ok=True)
        temp_metadata.unlink(missing_ok=True)
    return {
        "path": target,
        "metadata_path": metadata_path,
        "metadata": metadata,
        **summary,
    }
