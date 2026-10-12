"""Unified platform manager for GUI-driven traffic experiments.

The manager is intentionally outside algorithm source trees. It exposes the
GUI's `/api/v1` contract, starts model-specific adapter processes, and proxies
experiment detail traffic through one public HTTP port.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import pickle
import re
import shlex
import shutil
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urlparse
import urllib.error
import urllib.request

from PIL import Image

from backend.algorithms.citynde.interface.citynde_adapter import (
    build_generation_command,
    build_replay_command,
)
from backend.algorithms.neuralnde.interface.neuralnde_adapter import (
    build_generation_command as build_neuralnde_generation_command,
)
from backend.av.visual_stream_audit import audit_visual_stream
from backend.manager.experiment_store import ExperimentStore
from backend.manager.accident_store import AccidentStore
from backend.manager.reporting import build_experiment_report
from backend.manager.scenario_library import (
    create_accident_scenario,
    create_standard_scenario,
    inspect_scenario_seed_bundle,
)
from backend.cosmos.clipgt_exporter import export_clipgt
from backend.cosmos.appearance_anchors import (
    load_appearance_anchors,
    select_pose_matched_anchor,
)
from backend.cosmos.pipeline_utils import (
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_PROMPT,
    WARMUP_TERMINAL_FRAME_INDEX,
    analyze_transfer_segment_boundaries,
    assess_transfer_crossfade_boundaries,
    control_paths,
    create_playback_proxy,
    discover_transfer_views,
    extract_seed_frame,
    generated_anchor_control_path,
    inspect_recording_window,
    omnidreams_rollover_frame_indices,
    omnidreams_session_frame_budget,
    operational_ego_id,
    pad_controls,
    prepare_transfer_conditioning_video,
    prepare_transfer_input_media,
    recording_to_traffic_frames,
    scene_prompt,
    slice_and_pad_controls,
    state_to_traffic_frame,
    stitch_transfer_segments,
    transfer_anchor_frame_indices,
    transfer_frame_plan,
    transfer_replay_strategy,
    transfer_segment_plan,
    trim_views,
    probe_video,
    validate_transfer_outputs,
    validate_transfer_spec_media,
    verify_transfer_anchor_geometry,
    write_transfer_spec,
)
from backend.cosmos.runtime_manager import CosmosRuntimeManager
from backend.cosmos.seed_alignment import (
    SEED_ALIGNMENT_OPENING_RESTART,
    SEED_ALIGNMENT_TERMINAL_CONTINUE,
    audit_seed_traffic_boundary,
    normalize_seed_alignment_mode,
)
from backend.cosmos.traffic_scene_adapter import traffic_frames_to_recording
from backend.cosmos.transfer1_control import render_transfer1_hdmap_control
from backend.cosmos.transfer1_seed import (
    TRANSFER1_CONTAINER_SECONDS,
    TRANSFER1_NATIVE_FPS,
    TRANSFER1_NATIVE_FRAMES,
    TRANSFER1_WARMUP_FRAME_INDEX,
    TRANSFER1_WARMUP_SECONDS,
    create_transfer1_seed_preview,
    extract_transfer1_warmup_frame,
    run_transfer1_seed,
)
from backend.cosmos.transfer2_seed_cache import (
    default_cache_root as transfer2_seed_cache_root,
    restore as restore_transfer2_seed_cache,
    store as store_transfer2_seed_cache,
)
from backend.cosmos.transfer_scene_exporter import (
    CAMERAS,
    TRANSFER_WINDOW_SOURCE_STEPS,
    VIEW_KEYS,
    export_citynde_scene,
    prepare_citynde_transfer_window,
)
from backend.cosmos.video_qa import analyze_group
from backend.cosmos.world_sync import traffic_capture_wait_is_expected, update_world_sync
from backend.validation.joint_flow_audit import audit_joint_flow
from backend.validation.traffic_safety_audit import audit_traffic_safety

_DIRECT_HTTP_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_TRANSFER2_SEED_CACHE_LOCK = threading.Lock()


def _blend_preview_jpeg(previous: bytes, current: bytes, ratio: float) -> bytes:
    """Blend adjacent generated frames for display-only 30 Hz MJPEG pacing."""
    ratio = max(0.0, min(1.0, float(ratio)))
    if ratio >= 1.0 or not previous:
        return current
    with Image.open(io.BytesIO(previous)) as previous_image, Image.open(
        io.BytesIO(current)
    ) as current_image:
        target = current_image.convert("RGB")
        source = previous_image.convert("RGB")
        if source.size != target.size:
            source = source.resize(target.size, Image.Resampling.BILINEAR)
        blended = Image.blend(source, target, ratio)
        output = io.BytesIO()
        blended.save(output, format="JPEG", quality=88, subsampling=1)
        return output.getvalue()


def _preview_stream_rate(
    arrival_fps: float,
    buffered_frames: int,
    *,
    target_buffer_seconds: float,
    fps_limit: float,
) -> tuple[float, float]:
    """Pace bursty model chunks from measured end-to-end frame arrivals."""
    arrival_fps = max(0.25, float(arrival_fps))
    buffer_seconds = max(0.0, int(buffered_frames)) / arrival_fps
    target = max(0.5, float(target_buffer_seconds))
    if buffer_seconds < target * 0.4:
        scale = 0.90
    elif buffer_seconds < target * 0.75:
        scale = 0.93
    elif buffer_seconds < target:
        scale = 0.96
    elif buffer_seconds > target * 1.6:
        scale = 1.05
    else:
        scale = 0.99
    return (
        max(0.25, min(float(fps_limit), arrival_fps * scale)),
        buffer_seconds,
    )

HIGH_RISK_ACTIONS = {
    "terminate_experiment",
    "delete_experiment",
    "delete_experiments",
}
HIGH_RISK_DATA_ACTIONS = {
    "delete_scenario",
    "delete_scenarios",
    "rename_scenario",
}
PUBLIC_GET_ROUTES = {"/status", "/capabilities", "/auth/me", "/favicon.ico"}
PUBLIC_POST_ROUTES = {"/auth/login", "/auth/register"}


class WorldJobCancelled(RuntimeError):
    """Raised when an individual world-generation job is explicitly stopped."""


def _world_map_radii(
    request: dict,
    duration_seconds: float,
    *,
    route_extent_m: float = 0.0,
    route_corridor: bool = False,
) -> tuple[float, float]:
    """Keep the short seed scene local while allowing long replay coverage."""
    seed_radius = max(
        60.0,
        min(150.0, float(request.get("world_seed_map_radius_m") or 90.0)),
    )
    requested_radius = request.get("world_map_radius_m")
    if requested_radius not in {None, ""}:
        replay_radius = min(2500.0, float(requested_radius))
    elif route_corridor:
        replay_radius = 120.0
    elif math.isfinite(float(route_extent_m)) and float(route_extent_m) > 0.0:
        # Long-running loop traffic needs the whole ego route, not the whole
        # city. A local static ClipGT keeps Ludus geometry buffers bounded.
        replay_radius = min(900.0, float(route_extent_m) + 120.0)
    else:
        replay_radius = min(
            2500.0,
            75.0 + max(0.1, float(duration_seconds)) * 6.0,
        )
    replay_radius = max(seed_radius, replay_radius)
    return seed_radius, replay_radius


def _world_route_crop_path(status: dict, map_state: dict) -> list[list[float]]:
    """Resolve the selected CityNDE loop into an ordered map corridor."""
    route_ids = [str(item) for item in status.get("world_loop_route_lane_ids") or []]
    if not route_ids:
        return []
    polylines = {
        str(item.get("id")): item
        for item in map_state.get("polylines") or []
        if item.get("id") is not None
    }
    points: list[list[float]] = []
    for lane_id in route_ids:
        for point in (polylines.get(lane_id) or {}).get("points") or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append([x, y])
    return points


def _citynde_seed_init_mode(
    init_mode: str,
    *,
    requested_existing_seed: bool,
    scenario_metadata: dict,
) -> str:
    """Resolve stale UI signal randomization against an exact saved seed."""
    normalized = str(init_mode or "random_tl_only").strip()
    if (
        requested_existing_seed
        and normalized == "data_random_tl"
        and bool(scenario_metadata.get("use_existing_seed"))
    ):
        return "data"
    return normalized


def _traffic_runs_until_stopped(request: dict) -> bool:
    value = request.get("run_until_stopped", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "unlimited"}
    return bool(value)


def _traffic_duration_seconds(request: dict) -> float:
    """Return the configured finite horizon, or zero for an open-ended run."""
    if _traffic_runs_until_stopped(request):
        return 0.0
    resolution = max(1e-3, float(request.get("sim_resolution", 0.1) or 0.1))
    total_steps = max(0, int(request.get("total_step", 0) or 0))
    if total_steps:
        return max(resolution, total_steps * resolution)
    return max(resolution, float(request.get("max_sim_time", resolution) or resolution))


def _world_video_follows_traffic(request: dict) -> bool:
    """Return whether world generation should use the full traffic horizon."""
    value = request.get("world_video_follow_traffic", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "follow", "traffic"}
    return bool(value)


def _world_video_runs_until_stopped(request: dict) -> bool:
    return _traffic_runs_until_stopped(request) and _world_video_follows_traffic(request)


def _world_video_duration_seconds(request: dict) -> float:
    """Resolve a finite horizon, or zero when video follows an open-ended run."""
    traffic_duration = _traffic_duration_seconds(request)
    if _world_video_follows_traffic(request):
        return traffic_duration
    requested = max(0.1, float(request.get("world_video_duration", 15.0) or 15.0))
    if _traffic_runs_until_stopped(request):
        return requested
    return min(requested, traffic_duration)


def _world_actor_velocity(actor: dict) -> tuple[float, float]:
    try:
        if actor.get("vx") is not None and actor.get("vy") is not None:
            return float(actor["vx"]), float(actor["vy"])
    except (TypeError, ValueError):
        pass
    speed = float(actor.get("speed", 0.0) or 0.0)
    heading = float(actor.get("heading", 0.0) or 0.0)
    return speed * math.cos(heading), speed * math.sin(heading)


def _interpolate_world_actor(first: dict, second: dict, ratio: float, span: float = 0.0) -> dict:
    result = dict(second)
    ratio = max(0.0, min(1.0, float(ratio)))
    for key in ("z", "speed", "vx", "vy", "ax", "ay", "length", "width", "height"):
        try:
            start = float(first[key])
            end = float(second[key])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(start) and math.isfinite(end):
            result[key] = start + (end - start) * ratio
    has_motion = all(
        actor.get("speed") is not None
        or (actor.get("vx") is not None and actor.get("vy") is not None)
        for actor in (first, second)
    )
    if span > 0.0 and has_motion:
        first_velocity = _world_actor_velocity(first)
        second_velocity = _world_actor_velocity(second)
        t2, t3 = ratio * ratio, ratio * ratio * ratio
        h00, h10 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + ratio
        h01, h11 = -2 * t3 + 3 * t2, t3 - t2
        for index, key in enumerate(("x", "y")):
            try:
                start, end = float(first[key]), float(second[key])
            except (KeyError, TypeError, ValueError):
                continue
            result[key] = h00 * start + h10 * span * first_velocity[index] + h01 * end + h11 * span * second_velocity[index]
    else:
        for key in ("x", "y"):
            try:
                start, end = float(first[key]), float(second[key])
            except (KeyError, TypeError, ValueError):
                continue
            result[key] = start + (end - start) * ratio
    try:
        start_heading = float(first.get("heading", 0.0) or 0.0)
        end_heading = float(second.get("heading", 0.0) or 0.0)
        delta = math.atan2(
            math.sin(end_heading - start_heading),
            math.cos(end_heading - start_heading),
        )
        result["heading"] = start_heading + delta * ratio
    except (TypeError, ValueError):
        pass
    return result


def _extrapolate_world_actor(actor: dict, seconds: float) -> dict:
    result = dict(actor)
    vx, vy = _world_actor_velocity(actor)
    result["x"] = float(actor.get("x", 0.0) or 0.0) + vx * seconds
    result["y"] = float(actor.get("y", 0.0) or 0.0) + vy * seconds
    return result


def _interpolate_world_capture(frames: list[dict], target_time: float) -> dict:
    """Interpolate a captured 10 Hz traffic stream at an exact video-frame time."""
    if not frames:
        return {}
    times = [float(frame.get("sim_time", 0.0) or 0.0) for frame in frames]
    upper = bisect.bisect_left(times, float(target_time))
    if upper <= 0:
        result = dict(frames[0])
        result["sim_time"] = max(times[0], float(target_time))
        return result
    if upper >= len(frames):
        return dict(frames[-1])
    first, second = frames[upper - 1], frames[upper]
    first_time, second_time = times[upper - 1], times[upper]
    span = max(second_time - first_time, 1e-9)
    ratio = (float(target_time) - first_time) / span

    first_actors = {
        str(actor.get("id")): actor
        for actor in [first.get("ego") or {}, *(first.get("vehicles") or first.get("actors") or [])]
        if actor.get("id") is not None
    }
    second_actors = {
        str(actor.get("id")): actor
        for actor in [second.get("ego") or {}, *(second.get("vehicles") or second.get("actors") or [])]
        if actor.get("id") is not None
    }
    ego_id = str((second.get("ego") or first.get("ego") or {}).get("id", ""))
    interpolated: dict[str, dict] = {}
    for actor_id in sorted(set(first_actors) | set(second_actors)):
        if actor_id in first_actors and actor_id in second_actors:
            interpolated[actor_id] = _interpolate_world_actor(
                first_actors[actor_id], second_actors[actor_id], ratio, span
            )
        elif actor_id in second_actors:
            interpolated[actor_id] = _extrapolate_world_actor(
                second_actors[actor_id], -(1.0 - ratio) * span
            )
        else:
            interpolated[actor_id] = _extrapolate_world_actor(
                first_actors[actor_id], ratio * span
            )

    result = dict(second)
    result["sim_time"] = float(target_time)
    result["ego"] = interpolated.pop(ego_id, dict(second.get("ego") or {}))
    result["vehicles"] = list(interpolated.values())
    result.pop("actors", None)
    return result


def _world_transfer_seed(request: dict) -> int:
    """Preserve an explicit zero and otherwise use Transfer's official seed."""
    value = request.get("world_transfer_seed")
    return 0 if value is None or value == "" else int(value)


def _world_seed_backend(request: dict) -> str:
    """Resolve the control-to-world model used only for the startup seed."""
    value = str(
        request.get("world_seed_backend")
        or os.environ.get("COSMOS_SEED_BACKEND", "transfer2.5")
    ).strip().lower()
    aliases = {
        "transfer1": "transfer1",
        "transfer1_sample_av": "transfer1",
        "cosmos-transfer1": "transfer1",
        "transfer2": "transfer2.5",
        "transfer2.5": "transfer2.5",
        "cosmos-transfer2.5": "transfer2.5",
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported world seed backend {value!r}; expected transfer1 or transfer2.5"
        ) from exc


def _world_omnidreams_seed(request: dict) -> int:
    """Keep the video rollout seed independent from the traffic RNG seed."""
    value = request.get("world_omnidreams_seed")
    if value is None or value == "":
        value = os.environ.get("OMNIDREAMS_SEED", "1")
    return int(value)


def _omnidreams_preview_frame_index(
    output_frame_index: int,
    *,
    output_fps: int,
    preview_fps: int,
) -> int:
    """Map a 30 fps output index to the bounded preview sequence index."""
    output_fps = max(1, int(output_fps))
    preview_fps = max(1, int(preview_fps))
    preview_stride = max(1, int(round(output_fps / preview_fps)))
    return max(0, int(output_frame_index)) // preview_stride


def _world_seed_alignment_mode(request: dict) -> str:
    value = request.get("world_seed_alignment_mode")
    if value in {None, ""}:
        value = os.environ.get(
            "COSMOS_SEED_ALIGNMENT_MODE",
            SEED_ALIGNMENT_TERMINAL_CONTINUE,
        )
    return normalize_seed_alignment_mode(value)


def _world_save_omnidreams_control(request: dict) -> bool:
    value = request.get("world_omnidreams_save_control_video")
    if value is None:
        value = os.environ.get("OMNIDREAMS_SAVE_CONTROL_VIDEO", "1")
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _world_generation_defaults(request: dict) -> dict:
    """Apply quality defaults while preserving explicit A/B overrides."""
    normalized = dict(request)
    if not bool(normalized.get("world_generation_enabled", False)):
        return normalized
    normalized["world_use_cached_appearance_anchor"] = False
    normalized["world_transfer_two_stage_seed"] = False
    seed_image = str(normalized.get("world_seed_image") or "").strip()
    normalized["world_seed_backend"] = _world_seed_backend(normalized)
    normalized["world_seed_mode"] = (
        "existing_scenario_frame"
        if seed_image
        else "single_view_transfer1_quality"
        if normalized["world_seed_backend"] == "transfer1"
        else "multiview_quality"
    )
    normalized["world_seed_image"] = seed_image
    normalized["world_seed_alignment_mode"] = _world_seed_alignment_mode(normalized)
    if normalized["world_seed_backend"] == "transfer1" and not seed_image:
        # Sample-AV has one fixed 121-frame temporal contract. Keep traffic's
        # held endpoint exactly aligned with generated frame 120.
        normalized["warmup_seconds"] = TRANSFER1_WARMUP_SECONDS
    if normalized.get("world_omnidreams_segment_seconds") is None:
        normalized["world_omnidreams_segment_seconds"] = float(
            os.environ.get("OMNIDREAMS_SEGMENT_SECONDS", "0")
        )
    if normalized.get("world_omnidreams_seed") in {None, ""}:
        normalized["world_omnidreams_seed"] = _world_omnidreams_seed(normalized)
    if normalized.get("world_omnidreams_rollover_mode") is None:
        normalized["world_omnidreams_rollover_mode"] = str(
            os.environ.get("OMNIDREAMS_ROLLOVER_MODE", "latest")
        ).strip().lower()
    if normalized.get("world_omnidreams_transition_frames") is None:
        normalized["world_omnidreams_transition_frames"] = int(
            os.environ.get("OMNIDREAMS_TRANSITION_FRAMES", "0")
        )
    if normalized.get("world_stationary_anchor_enabled") is None:
        normalized["world_stationary_anchor_enabled"] = str(
            os.environ.get("OMNIDREAMS_STATIONARY_REFERENCE", "0")
        ).strip().lower() not in {"0", "false", "no", "off"}
    if normalized.get("world_stationary_reset_seconds") is None:
        normalized["world_stationary_reset_seconds"] = float(
            os.environ.get("OMNIDREAMS_STATIONARY_RESET_SECONDS", "6")
        )
    if normalized.get("world_stationary_enter_seconds") is None:
        normalized["world_stationary_enter_seconds"] = float(
            os.environ.get("OMNIDREAMS_STATIONARY_ENTER_SECONDS", "1.0")
        )
    if normalized.get("world_stationary_speed_threshold_mps") is None:
        normalized["world_stationary_speed_threshold_mps"] = float(
            os.environ.get("OMNIDREAMS_STATIONARY_SPEED_THRESHOLD_MPS", "0.10")
        )
    if normalized.get("world_stationary_exit_speed_mps") is None:
        normalized["world_stationary_exit_speed_mps"] = float(
            os.environ.get("OMNIDREAMS_STATIONARY_EXIT_SPEED_MPS", "0.8")
        )
    if normalized.get("world_omnidreams_rollover_sharpen_percent") is None:
        normalized["world_omnidreams_rollover_sharpen_percent"] = int(
            os.environ.get("OMNIDREAMS_ROLLOVER_SHARPEN_PERCENT", "0")
        )
    if normalized.get("world_omnidreams_anchor_transfer_steps") is None:
        normalized["world_omnidreams_anchor_transfer_steps"] = int(
            os.environ.get("OMNIDREAMS_ANCHOR_TRANSFER_STEPS", "12")
        )
    if normalized.get("world_omnidreams_anchor_mode") is None:
        normalized["world_omnidreams_anchor_mode"] = str(
            os.environ.get("OMNIDREAMS_ANCHOR_MODE", "conditioned_front")
        ).strip().lower()
    if normalized.get("world_transfer_seed_max_attempts") is None:
        normalized["world_transfer_seed_max_attempts"] = int(
            os.environ.get("TRANSFER_SEED_MAX_ATTEMPTS", "3")
        )
    if normalized.get("world_omnidreams_anchor_max_attempts") is None:
        normalized["world_omnidreams_anchor_max_attempts"] = int(
            os.environ.get("OMNIDREAMS_ANCHOR_MAX_ATTEMPTS", "3")
        )
    if normalized.get("world_transfer_seed") in {None, ""}:
        normalized["world_transfer_seed"] = 0
    return normalized


def _world_pipeline_should_release_child(
    info: dict[str, Any] | None,
    child_status: dict[str, Any] | None = None,
) -> bool:
    """Release owned batch runs and traffic processes that reached a terminal state."""
    if not info:
        return False
    if info.get("batch_id"):
        return True
    status = child_status or info.get("last_status") or {}
    return str(status.get("run_state") or "").strip().lower() in {
        "completed",
        "error",
        "stopped",
        "interrupted",
    }


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _safe_event_details(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key)
            if any(token in key_text.lower() for token in ("password", "token", "secret")):
                out[key_text] = "***"
            else:
                out[key_text] = _safe_event_details(item)
        return out
    if isinstance(value, list):
        return [_safe_event_details(item) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _compact_experiment_list_record(record: dict) -> dict:
    """Keep high-frequency experiment polling independent of artifact manifests."""
    compact = dict(record)
    if str(compact.get("run_state") or "") not in {
        "starting",
        "warming_up",
        "world_seed_pending",
        "running",
        "playback",
        "playback_loading",
    }:
        # A persisted PID belongs to the manager process that created the row.
        # Exposing it after completion or a manager restart makes a historical
        # experiment look live and can point at an unrelated reused PID.
        compact["pid"] = None
    world = record.get("world_generation")
    if isinstance(world, dict):
        compact["world_generation"] = {
            key: world[key]
            for key in (
                "experiment_id",
                "stage",
                "run_state",
                "progress",
                "message",
                "error",
                "created_at",
                "updated_at",
            )
            if key in world
        }
    artifacts = record.get("artifacts")
    if isinstance(artifacts, list):
        compact["artifact_count"] = len(artifacts)
        video_artifacts = [
            item
            for item in artifacts
            if isinstance(item, dict)
            and (
                str(item.get("mime_type") or "").startswith("video/")
                or Path(str(item.get("path") or "")).suffix.lower() in {".mp4", ".webm", ".mov"}
            )
        ]
        compact["video_artifact_count"] = len(video_artifacts)
        compact["video_artifact_kinds"] = sorted(
            {str(item.get("kind") or "video") for item in video_artifacts}
        )
        compact.pop("artifacts", None)
    for key in ("last_error", "av_adapter_error", "carla_error"):
        value = compact.get(key)
        if isinstance(value, str) and len(value) > 1000:
            compact[key] = value[-1000:]
    return compact


class SecurityManager:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.enabled = os.environ.get("TRAFFICWM_AUTH_DISABLED", "").strip().lower() not in {"1", "true", "yes"}
        self.session_timeout = max(60, int(os.environ.get("TRAFFICWM_SESSION_TIMEOUT_SECONDS", "3600") or "3600"))
        self.data_dir = self.root / "backend" / "manager" / "data" / "security"
        self.users_path = self.data_dir / "users.json"
        self.events_path = self.data_dir / "security_events.jsonl"
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_admin_user()

    @staticmethod
    def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, 120_000)
        return salt.hex(), digest.hex()

    @staticmethod
    def _valid_username(username: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", str(username or "")))

    def _read_store(self) -> dict:
        try:
            loaded = json.loads(self.users_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("users"), list):
                return loaded
        except Exception:
            pass
        return {"version": 1, "users": []}

    def _write_store(self, store: dict):
        tmp = self.users_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.users_path)

    def _sanitize_user(self, user: dict) -> dict:
        return {
            "id": str(user.get("id", "")),
            "username": str(user.get("username", "")),
            "role": str(user.get("role", "operator")),
            "enabled": bool(user.get("enabled", True)),
            "created_at": str(user.get("created_at", "")),
            "last_login": str(user.get("last_login", "")),
        }

    def _ensure_admin_user(self):
        with self._lock:
            store = self._read_store()
            users = store.setdefault("users", [])
            if any(str(user.get("role")) == "admin" for user in users):
                return
            username = os.environ.get("TRAFFICWM_ADMIN_USER", "admin").strip() or "admin"
            password = os.environ.get("TRAFFICWM_ADMIN_PASSWORD", "admin123")
            salt, password_hash = self._hash_password(password)
            users.append(
                {
                    "id": uuid.uuid4().hex,
                    "username": username,
                    "role": "admin",
                    "enabled": True,
                    "salt": salt,
                    "password_hash": password_hash,
                    "created_at": _now_text(),
                    "last_login": "",
                }
            )
            self._write_store(store)

    def list_users(self) -> list[dict]:
        with self._lock:
            store = self._read_store()
            return [self._sanitize_user(user) for user in store.get("users", [])]

    def create_user(self, username: str, password: str, role: str = "operator", enabled: bool = True) -> dict:
        username = str(username or "").strip()
        role = str(role or "operator").strip().lower()
        if role not in {"admin", "operator", "viewer"}:
            return {"ok": False, "error": "Invalid role"}
        if not self._valid_username(username):
            return {"ok": False, "error": "Username must be 3-32 ASCII letters, numbers, '.', '_' or '-'"}
        if len(str(password or "")) < 6:
            return {"ok": False, "error": "Password must be at least 6 characters"}
        with self._lock:
            store = self._read_store()
            users = store.setdefault("users", [])
            if any(str(user.get("username", "")).lower() == username.lower() for user in users):
                return {"ok": False, "error": "Username already exists"}
            salt, password_hash = self._hash_password(str(password))
            user = {
                "id": uuid.uuid4().hex,
                "username": username,
                "role": role,
                "enabled": bool(enabled),
                "salt": salt,
                "password_hash": password_hash,
                "created_at": _now_text(),
                "last_login": "",
            }
            users.append(user)
            self._write_store(store)
            return {"ok": True, "user": self._sanitize_user(user)}

    def update_user(self, actor: dict | None, payload: dict) -> dict:
        action = str(payload.get("type", "")).strip().lower()
        target_id = str(payload.get("user_id") or payload.get("id") or "").strip()
        target_name = str(payload.get("username") or "").strip().lower()
        actor_id = str((actor or {}).get("id") or "")
        with self._lock:
            store = self._read_store()
            users = store.setdefault("users", [])
            target = next(
                (
                    user
                    for user in users
                    if (target_id and str(user.get("id")) == target_id)
                    or (target_name and str(user.get("username", "")).lower() == target_name)
                ),
                None,
            )
            if target is None:
                return {"ok": False, "error": "User not found"}
            if action == "set_role":
                role = str(payload.get("role") or "").strip().lower()
                if role not in {"admin", "operator", "viewer"}:
                    return {"ok": False, "error": "Invalid role"}
                if str(target.get("role")) == "admin" and role != "admin" and self._enabled_admin_count(users) <= 1:
                    return {"ok": False, "error": "Cannot remove the last enabled admin"}
                target["role"] = role
            elif action == "set_enabled":
                enabled = bool(payload.get("enabled"))
                if not enabled and str(target.get("role")) == "admin" and self._enabled_admin_count(users) <= 1:
                    return {"ok": False, "error": "Cannot disable the last enabled admin"}
                target["enabled"] = enabled
            elif action == "reset_password":
                password = str(payload.get("password") or "")
                if len(password) < 6:
                    return {"ok": False, "error": "Password must be at least 6 characters"}
                salt, password_hash = self._hash_password(password)
                target["salt"] = salt
                target["password_hash"] = password_hash
            elif action == "delete_user":
                if str(target.get("id")) == actor_id:
                    return {"ok": False, "error": "Cannot delete your own account"}
                if str(target.get("role")) == "admin" and self._enabled_admin_count(users) <= 1:
                    return {"ok": False, "error": "Cannot delete the last enabled admin"}
                users.remove(target)
            else:
                return {"ok": False, "error": f"Unknown user action: {action}"}
            self._write_store(store)
            return {"ok": True, "users": [self._sanitize_user(user) for user in users]}

    @staticmethod
    def _enabled_admin_count(users: list[dict]) -> int:
        return sum(1 for user in users if str(user.get("role")) == "admin" and bool(user.get("enabled", True)))

    def login(self, username: str, password: str, *, ip: str = "", user_agent: str = "") -> dict:
        username = str(username or "").strip()
        with self._lock:
            store = self._read_store()
            users = store.setdefault("users", [])
            user = next((item for item in users if str(item.get("username", "")).lower() == username.lower()), None)
            if user is None or not bool(user.get("enabled", True)):
                self.log_event("abnormal_access", "login_failed", username=username, ip=ip, details={"reason": "unknown_or_disabled"})
                return {"ok": False, "error": "Invalid username or password"}
            salt = str(user.get("salt") or "")
            expected = str(user.get("password_hash") or "")
            _, actual = self._hash_password(password, salt)
            if not hmac.compare_digest(expected, actual):
                self.log_event("abnormal_access", "login_failed", username=username, ip=ip, details={"reason": "bad_password"})
                return {"ok": False, "error": "Invalid username or password"}
            user["last_login"] = _now_text()
            self._write_store(store)
            token = secrets.token_urlsafe(32)
            session = {
                "token": token,
                "user": self._sanitize_user(user),
                "created_at": time.time(),
                "expires_at": time.time() + self.session_timeout,
                "ip": ip,
                "user_agent": user_agent[:200],
            }
            self._sessions[token] = session
        self.log_event("auth", "login_success", user=session["user"], ip=ip)
        return {"ok": True, "token": token, "expires_in": self.session_timeout, "user": session["user"]}

    def session_for_token(self, token: str | None) -> dict | None:
        if not self.enabled:
            return {"user": {"id": "system", "username": "system", "role": "admin", "enabled": True}}
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(str(token))
            if not session:
                return None
            if float(session.get("expires_at", 0)) < time.time():
                self._sessions.pop(str(token), None)
                return None
            session["expires_at"] = time.time() + self.session_timeout
            return dict(session)

    def logout(self, token: str | None):
        if not token:
            return
        with self._lock:
            self._sessions.pop(str(token), None)

    def log_event(
        self,
        category: str,
        action: str,
        *,
        user: dict | None = None,
        username: str = "",
        ip: str = "",
        method: str = "",
        path: str = "",
        status: str = "",
        details=None,
    ):
        event = {
            "time": _now_text(),
            "category": str(category or "security"),
            "action": str(action or ""),
            "username": username or str((user or {}).get("username") or ""),
            "role": str((user or {}).get("role") or ""),
            "ip": ip,
            "method": method,
            "path": path,
            "status": status,
            "details": _safe_event_details(details or {}),
        }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def list_events(self, *, limit: int = 200, category: str = "") -> list[dict]:
        limit = max(1, min(1000, int(limit or 200)))
        category = str(category or "").strip()
        if not self.events_path.is_file():
            return []
        try:
            lines = self.events_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        out = []
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if category and event.get("category") != category:
                continue
            out.append(event)
            if len(out) >= limit:
                break
        return out


def _tail_text(path: str | Path, max_bytes: int = 4096) -> str:
    try:
        p = Path(path)
        with p.open("rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - max_bytes), os.SEEK_SET)
            return f.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _recording_first_vehicle_ids(recording: dict[str, Any]) -> set[str]:
    steps = recording.get("vehicle_id_per_step")
    if steps is None or len(steps) == 0:
        return set()
    return {str(actor_id) for actor_id in steps[0]}


def _recording_last_vehicle_ids(recording: dict[str, Any]) -> set[str]:
    steps = recording.get("vehicle_id_per_step")
    if steps is None or len(steps) == 0:
        return set()
    return {str(actor_id) for actor_id in steps[-1]}


def _recording_initialization_history(
    recording: dict[str, Any],
    *,
    end_step: int,
    history_steps: int = 11,
) -> dict[str, Any]:
    vehicle_steps = recording.get("vehicle_id_per_step")
    if vehicle_steps is None:
        raise ValueError("Recording has no vehicle timeline")
    end_step = int(end_step)
    history_steps = max(2, int(history_steps))
    start_step = end_step - history_steps + 1
    if start_step < 0 or end_step >= len(vehicle_steps):
        raise ValueError(
            f"Scenario first frame needs {history_steps} source states ending at step {end_step}"
        )
    history = dict(recording)
    timeline_length = len(vehicle_steps)
    for key, value in recording.items():
        if not str(key).endswith("_per_step"):
            continue
        try:
            value_length = len(value)
        except TypeError as exc:
            raise ValueError(f"Recording field {key} is not a step sequence") from exc
        if value_length != timeline_length:
            raise ValueError(
                f"Recording field {key} has {value_length} steps; expected {timeline_length}"
            )
        history[key] = list(value[start_step : end_step + 1])
    simulator = dict(recording.get("simulator_meta_info") or {})
    simulator["trafficwm_seed_initialization"] = {
        "source_start_step": start_step,
        "source_end_step": end_step,
        "history_steps": history_steps,
    }
    history["simulator_meta_info"] = simulator
    return history


def _recording_actor_state(
    recording: dict[str, Any],
    actor_id: str,
    *,
    step: int,
) -> tuple[float, ...] | None:
    id_steps = recording.get("vehicle_id_per_step")
    state_steps = recording.get("vehicle_state_per_step")
    if id_steps is None or state_steps is None or not len(id_steps) or not len(state_steps):
        return None
    index = step if step >= 0 else len(id_steps) + step
    if index < 0 or index >= min(len(id_steps), len(state_steps)):
        return None
    actor_index = next(
        (offset for offset, value in enumerate(id_steps[index]) if str(value) == str(actor_id)),
        None,
    )
    if actor_index is None:
        return None
    state = state_steps[index][actor_index]
    return tuple(float(value) for value in state[:5])


def _recording_step_sha256(recording: dict[str, Any], *, step: int) -> str:
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


class _FastThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class ManagerServer:
    def __init__(
        self,
        *,
        root: Path,
        host: str = "0.0.0.0",
        port: int = 8890,
        gui_dir: Path | None = None,
        child_host: str = "127.0.0.1",
        child_port_start: int = 8900,
        citynde_root: Path | None = None,
        neuralnde_root: Path | None = None,
        citynde_python: str | None = None,
        neuralnde_python: str | None = None,
        carla_python: str | None = None,
        carla_gateway_port: int = 8892,
        carla_root: Path | None = None,
        cosmos_autostart: bool = False,
        transfer_root: Path | None = None,
        omnidreams_root: Path | None = None,
        transfer_gpus: str = "0,1,2,3",
        anchor_transfer_gpus: str = "",
        omnidreams_gpus: str = "7",
        transfer_port: int = 8895,
        anchor_transfer_port: int = 8896,
        omnidreams_port: int = 50051,
        omnidreams_profile: str = "quality",
        omnidreams_pipeline_config: str = "omnidreams-sv-2steps-chunk2-loc6-vae-vae",
        omnidreams_checkpoint_path: str = "",
        transfer_container_image: str = "trafficwm-cosmos-runtime:cu128",
        transfer_container_venv: str = "cosmos-transfer25-venv",
    ):
        self.root = root.resolve()
        self.host = str(host or "0.0.0.0")
        self.port = int(port)
        self.gui_dir = (gui_dir or self.root / "GUI").resolve()
        self.child_host = str(child_host or "127.0.0.1")
        self.child_port_start = int(child_port_start)
        sources_root = self.root / "algorithm_sources"
        self.citynde_root = (citynde_root or sources_root / "CityNDE_src").resolve()
        self.output_root = self.root / "output"
        self.scenario_root = self.output_root / "scenarios" / "citynde"
        self.runtime_root = self.output_root / "runtime"
        self.platform_data_root = self.output_root / "platform"
        self.workflow_store_path = self.platform_data_root / "workflows.json"
        self.evaluation_store_path = self.platform_data_root / "evaluation_systems.json"
        self._workflow_lock = threading.Lock()
        self._evaluation_lock = threading.Lock()
        default_neuralnde_root = Path(
            os.environ.get(
                "NEURALNDE_ROOT",
                str(sources_root / "NeuralNDE")
                if (sources_root / "NeuralNDE").is_dir()
                else "/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment",
            )
        )
        self.neuralnde_root = (neuralnde_root or default_neuralnde_root).resolve()
        self.citynde_python = citynde_python or os.environ.get("CITYNDE_PYTHON") or sys.executable
        self.citynde_container_image = os.environ.get(
            "CITYNDE_CONTAINER_IMAGE", transfer_container_image
        ).strip()
        self.citynde_container_venv = os.environ.get(
            "CITYNDE_CONTAINER_VENV", transfer_container_venv
        ).strip()
        self.neuralnde_python = (
            neuralnde_python
            or os.environ.get("NEURALNDE_PYTHON")
            or str(self.neuralnde_root / ".venv" / "bin" / "python")
        )
        self.carla_python = carla_python or os.environ.get("CARLA_PYTHON") or str(self.root / "envs" / "carla" / "bin" / "python")
        self.carla_gateway_port = int(carla_gateway_port)
        self.carla_root = (carla_root or Path(os.environ.get("CARLA_ROOT", "/data/rk/cnde/CARLA_0.9.16"))).resolve()
        self.carla_gateway_script = self.root / "backend" / "bridge" / "carla_gateway.py"
        self._carla_gateway_process: subprocess.Popen | None = None
        self._carla_gateway_log = None
        self.citynde_script = (
            self.root / "backend" / "algorithms" / "citynde" / "interface" / "citynde_gui_adapter.py"
        )
        self.neuralnde_adapter_script = (
            self.root / "backend" / "algorithms" / "neuralnde" / "interface" / "neuralnde_gui_adapter.py"
        )
        self.neuralnde_replay_script = (
            self.root / "backend" / "algorithms" / "neuralnde" / "interface" / "neuralnde_replay_adapter.py"
        )
        self._lock = threading.Lock()
        self._experiments: dict[str, dict] = {}
        self._citynde_metadata_cache: dict[str, tuple[float, dict]] = {}
        self.security = SecurityManager(self.root)
        self.experiment_store = ExperimentStore(self.root / "output" / "trafficwm.sqlite3")
        self.accident_store = AccidentStore(self.platform_data_root / "accidents.json")
        self._accident_sync_lock = threading.Lock()
        self._accident_sync_at = 0.0
        self.experiment_store.recover_interrupted()
        self._recover_completed_transfer_replays()
        self.cosmos = CosmosRuntimeManager(
            app_root=self.root,
            transfer_root=transfer_root or Path("/mnt/rk/cosmos/cosmos_transfer2.5/cosmos-transfer2.5"),
            omnidreams_root=omnidreams_root or Path("/mnt/rk/cosmos/flashdreams"),
            autostart=cosmos_autostart,
            transfer_gpus=transfer_gpus,
            anchor_transfer_gpus=anchor_transfer_gpus,
            omnidreams_gpus=omnidreams_gpus,
            transfer_port=transfer_port,
            anchor_transfer_port=anchor_transfer_port,
            omnidreams_port=omnidreams_port,
            omnidreams_profile=omnidreams_profile,
            omnidreams_pipeline_config=omnidreams_pipeline_config,
            omnidreams_checkpoint_path=omnidreams_checkpoint_path,
            transfer_container_image=transfer_container_image,
            transfer_container_venv=transfer_container_venv,
        )
        self._cosmos_status_lock = threading.Lock()
        self._cosmos_status_cache: dict[str, Any] = {
            "ok": True,
            "enabled": bool(self.cosmos.enabled),
            "ready": False,
            "refreshing": True,
        }
        self._cosmos_status_cache_at = 0.0
        self._cosmos_status_refreshing = False
        self._dashboard_lock = threading.Lock()
        self._dashboard_cache: dict[str, Any] = {}
        self._dashboard_cache_at = 0.0
        self._dashboard_refreshing = False
        self._world_stop = threading.Event()
        self._world_threads: dict[str, threading.Thread] = {}
        self._world_cancel_events: dict[str, threading.Event] = {}
        self._world_captures: dict[str, dict[str, Any]] = {}
        self._world_preview_frames: dict[str, int] = {}
        self._world_preview_rates: dict[str, float] = {}
        self._world_preview_status: dict[str, dict[str, Any]] = {}
        self._world_preview_clients: dict[str, int] = {}
        self._world_preview_clocks: dict[str, dict[str, Any]] = {}
        self._batch_threads: dict[str, threading.Thread] = {}
        self._closed = False

        manager = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            @staticmethod
            def _api_route(path: str) -> str:
                if path == "/api/v1":
                    return "/"
                if path.startswith("/api/v1/"):
                    return path[len("/api/v1") :] or "/"
                return path

            def _headers(self, content_type: str, status: int, length: int = 0):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Connection", "close")
                self.end_headers()

            def _write_json(self, payload: dict, status: int = 200):
                body = json.dumps(payload).encode("utf-8")
                self._headers("application/json", status, len(body))
                self.wfile.write(body)

            def _client_ip(self) -> str:
                forwarded = self.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
                return forwarded or (self.client_address[0] if self.client_address else "")

            def _bearer_token(self, query: dict | None = None) -> str:
                auth = self.headers.get("Authorization", "").strip()
                if auth.lower().startswith("bearer "):
                    return auth.split(" ", 1)[1].strip()
                if query:
                    return str((query.get("access_token") or [""])[0]).strip()
                return ""

            def _session(self, query: dict | None = None) -> dict | None:
                return manager.security.session_for_token(self._bearer_token(query))

            def _require_user(self, route: str, query: dict | None = None, *, admin: bool = False, write: bool = False) -> dict | None:
                if not manager.security.enabled:
                    return {"id": "system", "username": "system", "role": "admin", "enabled": True}
                session = self._session(query)
                if not session:
                    manager.security.log_event(
                        "abnormal_access",
                        "unauthorized",
                        ip=self._client_ip(),
                        method=self.command,
                        path=route,
                        status="401",
                        details={"reason": "missing_or_expired_session"},
                    )
                    self._write_json({"ok": False, "error": "Login required", "auth_required": True}, 401)
                    return None
                user = session.get("user") or {}
                if admin and str(user.get("role")) != "admin":
                    manager.security.log_event(
                        "abnormal_access",
                        "permission_denied",
                        user=user,
                        ip=self._client_ip(),
                        method=self.command,
                        path=route,
                        status="403",
                        details={"required_role": "admin"},
                    )
                    self._write_json({"ok": False, "error": "Admin role required"}, 403)
                    return None
                if write and str(user.get("role")) not in {"admin", "operator"}:
                    manager.security.log_event(
                        "abnormal_access",
                        "permission_denied",
                        user=user,
                        ip=self._client_ip(),
                        method=self.command,
                        path=route,
                        status="403",
                        details={"required_role": "operator"},
                    )
                    self._write_json({"ok": False, "error": "Operator role required"}, 403)
                    return None
                return user

            def _auth_me_payload(self, query: dict | None = None) -> dict:
                if not manager.security.enabled:
                    return {
                        "ok": True,
                        "auth_required": False,
                        "authenticated": False,
                        "user": None,
                        "session_timeout": manager.security.session_timeout,
                    }
                session = self._session(query)
                user = session.get("user") if session else None
                return {
                    "ok": True,
                    "auth_required": bool(manager.security.enabled),
                    "authenticated": bool(user),
                    "user": user,
                    "session_timeout": manager.security.session_timeout,
                }

            def _read_json(self) -> dict:
                size = int(self.headers.get("Content-Length", "0") or "0")
                if size <= 0:
                    return {}
                raw = self.rfile.read(size)
                return json.loads(raw.decode("utf-8")) if raw else {}

            def _send_bytes(self, data: bytes, filename: str, content_type: str):
                safe_name = filename.replace('"', "_")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def _serve_static(self, rel: str) -> bool:
                try:
                    target = (manager.gui_dir / rel).resolve()
                    target.relative_to(manager.gui_dir)
                except ValueError:
                    return False
                if not target.is_file():
                    return False
                mime, _ = mimetypes.guess_type(str(target))
                data = target.read_bytes()
                self._headers(mime or "application/octet-stream", 200, len(data))
                self.wfile.write(data)
                return True

            def _artifact_target(self, rel: str, *, require_file: bool = True) -> Path | None:
                try:
                    target = (manager.root / unquote(rel)).resolve()
                    target.relative_to((manager.root / "output").resolve())
                except ValueError:
                    return None
                if require_file and not target.is_file():
                    return None
                return target

            def _serve_artifact(self, rel: str) -> bool:
                target = self._artifact_target(rel)
                if target is None:
                    return False
                size = target.stat().st_size
                start, end = 0, max(0, size - 1)
                status = 200
                range_header = str(self.headers.get("Range") or "")
                if range_header.startswith("bytes=") and size:
                    values = range_header[6:].split("-", 1)
                    try:
                        if values[0]:
                            start = int(values[0])
                            end = int(values[1]) if len(values) > 1 and values[1] else end
                        else:
                            suffix_length = max(0, int(values[1]))
                            start = max(0, size - suffix_length)
                            end = size - 1
                    except ValueError:
                        start, end = 0, size - 1
                    start = max(0, min(start, size - 1))
                    end = max(start, min(end, size - 1))
                    status = 206
                length = max(0, end - start + 1) if size else 0
                mime, _ = mimetypes.guess_type(str(target))
                self.send_response(status)
                self.send_header("Content-Type", mime or "application/octet-stream")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "private, max-age=60")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with target.open("rb") as stream:
                    stream.seek(start)
                    remaining = length
                    while remaining > 0:
                        block = stream.read(min(1024 * 1024, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
                return True

            def _serve_live_mjpeg(self, rel: str, experiment_id: str = "") -> bool:
                target = self._artifact_target(rel, require_file=False)
                if target is None or target.suffix.lower() not in {".jpg", ".jpeg"}:
                    return False
                boundary = b"trafficwm-frame"
                try:
                    self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    pass
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={boundary.decode('ascii')}",
                )
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                last_signature: tuple[int, int] | None = None
                sequence_dir = target.parent / f"{target.stem}_frames"
                sequence_started = False
                last_sequence_index: int | None = None
                terminal_since: float | None = None

                if experiment_id:
                    with manager._lock:
                        manager._world_preview_clients[experiment_id] = (
                            manager._world_preview_clients.get(experiment_id, 0) + 1
                        )

                def _send_frame(frame: bytes) -> None:
                    self.wfile.write(b"--" + boundary + b"\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()

                try:
                    while not manager._closed:
                        now = time.monotonic()
                        status = manager._refresh_live_preview_clock(experiment_id)
                        sequence_index = (
                            int(status.get("playback_index"))
                            if status.get("started") and status.get("playback_index") is not None
                            else None
                        )
                        if sequence_index is not None and sequence_index != last_sequence_index:
                            frame_path = sequence_dir / f"{sequence_index:08d}.jpg"
                            try:
                                frame = frame_path.read_bytes()
                            except OSError:
                                frame = b""
                            if frame:
                                _send_frame(frame)
                                sequence_started = True
                                last_sequence_index = sequence_index
                                continue

                        if status.get("terminal"):
                            terminal_since = terminal_since or now
                            if (
                                status.get("started")
                                and status.get("playback_index") == status.get("newest_index")
                                and now - terminal_since >= 2.0
                            ):
                                break

                        if not sequence_started:
                            try:
                                stat = target.stat()
                                signature = (int(stat.st_mtime_ns), int(stat.st_size))
                                if stat.st_size > 0 and signature != last_signature:
                                    _send_frame(target.read_bytes())
                                    last_signature = signature
                            except FileNotFoundError:
                                pass
                        time.sleep(1.0 / 60.0)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    if experiment_id:
                        with manager._lock:
                            clients = max(
                                0, manager._world_preview_clients.get(experiment_id, 1) - 1
                            )
                            manager._world_preview_clients[experiment_id] = clients
                            status = dict(manager._world_preview_status.get(experiment_id) or {})
                            status.update(
                                {
                                    "active": clients > 0,
                                    "clients": clients,
                                    "updated_at_unix": time.time(),
                                }
                            )
                            manager._world_preview_status[experiment_id] = status
                self.close_connection = True
                return True

            def _write_proxy_response(self, result: dict):
                if not result.get("ok"):
                    self._write_json(result, int(result.get("status", 502)))
                    return
                body = result.get("body", b"") or b""
                if isinstance(body, str):
                    body = body.encode("utf-8")
                content_type = str(result.get("content_type") or "application/octet-stream")
                self._headers(content_type, int(result.get("status", 200)), len(body))
                if body:
                    self.wfile.write(body)

            def _read_multipart_files(self) -> list[tuple[str, bytes]]:
                size = int(self.headers.get("Content-Length", "0") or "0")
                boundary = self.headers.get_boundary()
                if size <= 0 or not boundary:
                    return []
                raw = self.rfile.read(size)
                marker = ("--" + boundary).encode("utf-8")
                files: list[tuple[str, bytes]] = []
                for part in raw.split(marker):
                    part = part.strip(b"\r\n")
                    if not part or part == b"--" or b"\r\n\r\n" not in part:
                        continue
                    header_blob, body = part.split(b"\r\n\r\n", 1)
                    headers = header_blob.decode("utf-8", errors="ignore").split("\r\n")
                    disposition = next((h for h in headers if h.lower().startswith("content-disposition:")), "")
                    if "filename=" not in disposition:
                        continue
                    filename = ""
                    for item in disposition.split(";"):
                        item = item.strip()
                        if item.startswith("filename="):
                            filename = item.split("=", 1)[1].strip().strip('"')
                            break
                    if not filename:
                        continue
                    if body.endswith(b"\r\n"):
                        body = body[:-2]
                    files.append((filename, body))
                return files

            @staticmethod
            def _confirmed(payload: dict) -> bool:
                return bool(payload.get("high_risk_confirmed") or payload.get("confirmed"))

            def _enforce_high_risk(self, action_type: str, payload: dict, user: dict, *, route: str) -> bool:
                if action_type not in HIGH_RISK_ACTIONS and action_type not in HIGH_RISK_DATA_ACTIONS:
                    return True
                if not self._confirmed(payload):
                    manager.security.log_event(
                        "high_risk",
                        f"{action_type}_blocked",
                        user=user,
                        ip=self._client_ip(),
                        method=self.command,
                        path=route,
                        status="409",
                        details={"payload": _safe_event_details(payload), "reason": "confirmation_missing"},
                    )
                    self._write_json({"ok": False, "error": "High-risk operation requires secondary confirmation"}, 409)
                    return False
                manager.security.log_event(
                    "high_risk",
                    action_type,
                    user=user,
                    ip=self._client_ip(),
                    method=self.command,
                    path=route,
                    status="accepted",
                    details={"payload": _safe_event_details(payload)},
                )
                return True

            def do_OPTIONS(self):
                self._headers("text/plain", 204, 0)

            def do_GET(self):
                try:
                    parsed = urlparse(self.path)
                    route = self._api_route(parsed.path)
                    query = parse_qs(parsed.query)
                    if route.startswith("/proxy/"):
                        user = self._require_user(route, query)
                        if user is None:
                            return
                        self._write_proxy_response(
                            manager.proxy_request(route, parsed.query, method="GET")
                        )
                        return
                    if route in ("/", "/index.html"):
                        if self._serve_static("index.html"):
                            return
                        self._write_json({"ok": False, "error": "GUI directory is not configured"}, 503)
                        return
                    if route == "/status":
                        self._write_json(manager.status_payload())
                        return
                    if route == "/auth/me":
                        self._write_json(self._auth_me_payload(query))
                        return
                    if route == "/admin/users":
                        if self._require_user(route, query, admin=True) is None:
                            return
                        self._write_json({"ok": True, "users": manager.security.list_users()})
                        return
                    if route == "/admin/security/events":
                        if self._require_user(route, query, admin=True) is None:
                            return
                        limit = int((query.get("limit") or ["200"])[0] or "200")
                        category = str((query.get("category") or [""])[0] or "")
                        self._write_json({"ok": True, "events": manager.security.list_events(limit=limit, category=category)})
                        return
                    rel_static = route.lstrip("/")
                    if rel_static and self._serve_static(rel_static):
                        return
                    if route not in PUBLIC_GET_ROUTES:
                        if self._require_user(route, query) is None:
                            return
                    if route == "/maps":
                        backend_model = str((query.get("backend_model") or query.get("model") or ["cnde"])[0])
                        self._write_json({"ok": True, "maps": manager.list_maps(backend_model)})
                        return
                    if route == "/maps/preview":
                        backend_model = str((query.get("backend_model") or ["cnde"])[0])
                        map_path = str((query.get("path") or [""])[0])
                        result = manager.map_preview(backend_model, map_path)
                        self._write_json(result, 200 if result.get("ok") else 404)
                        return
                    if route == "/scenarios":
                        self._write_json({"ok": True, "scenarios": [r["path"] for r in manager.list_scenario_records() if r.get("replayable", True)]})
                        return
                    if route == "/experiments":
                        experiment_id = str((query.get("experiment_id") or [""])[0]).strip()
                        if experiment_id:
                            experiment = manager.get_experiment(experiment_id)
                            if experiment is None:
                                self._write_json({"ok": False, "error": "Experiment not found"}, 404)
                            else:
                                self._write_json({"ok": True, "experiment": experiment})
                        else:
                            self._write_json({"ok": True, "experiments": manager.list_experiments()})
                        return
                    if route == "/reports/experiment":
                        experiment_id = str((query.get("experiment_id") or [""])[0]).strip()
                        report = manager.experiment_report(experiment_id)
                        self._write_json(report, 200 if report.get("ok") else 404)
                        return
                    if route == "/data/scenarios":
                        self._write_json({"ok": True, "records": manager.list_scenario_records()})
                        return
                    if route == "/data/standard-scenarios":
                        self._write_json(
                            {
                                "ok": True,
                                "records": manager.list_standard_scenario_records(),
                            }
                        )
                        return
                    if route == "/data/scenario-preview":
                        record_path = str((query.get("path") or [""])[0])
                        try:
                            max_frames = int((query.get("max_frames") or ["60"])[0])
                        except (TypeError, ValueError):
                            max_frames = 60
                        result = manager.scenario_preview(record_path, max_frames=max_frames)
                        self._write_json(result, 200 if result.get("ok") else 404)
                        return
                    if route == "/data/catalogs":
                        self._write_json(manager.data_catalog_payload())
                        return
                    if route == "/data/natural/tree":
                        dataset_id = str((query.get("id") or [""])[0])
                        relative_path = str((query.get("path") or [""])[0])
                        result = manager.natural_dataset_tree(dataset_id, relative_path)
                        self._write_json(result, 200 if result.get("ok") else 404)
                        return
                    if route == "/data/natural/download":
                        dataset_id = str((query.get("id") or [""])[0])
                        relative_path = str((query.get("path") or [""])[0])
                        result = manager.download_natural_dataset(dataset_id, relative_path)
                        if not result.get("ok"):
                            self._write_json(result, 404)
                            return
                        self._send_bytes(
                            result["data"],
                            result["filename"],
                            result.get("content_type") or "application/zip",
                        )
                        return
                    if route == "/dashboard":
                        self._write_json(manager.dashboard_payload())
                        return
                    if route == "/workflows":
                        self._write_json({"ok": True, "workflows": manager.list_workflows()})
                        return
                    if route == "/evaluation-systems":
                        self._write_json(
                            {
                                "ok": True,
                                "evaluation_systems": manager.list_evaluation_systems(),
                            }
                        )
                        return
                    if route == "/markers":
                        marker_scope = str((query.get("scope") or [""])[0])
                        result = manager.list_replay_markers(marker_scope)
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/data/download":
                        rel = unquote((query.get("path") or [""])[0])
                        result = manager.read_scenario_record(rel)
                        if not result.get("ok"):
                            self._write_json(result, 400)
                            return
                        self._send_bytes(
                            result["data"],
                            result.get("filename") or Path(rel).name or "record",
                            result.get("content_type") or "application/octet-stream",
                        )
                        return
                    if route == "/artifacts":
                        experiment_id = str((query.get("experiment_id") or [""])[0])
                        artifacts = manager.experiment_store.list_artifacts(experiment_id)
                        world_generation = manager.experiment_store.world_job(experiment_id)
                        if str((query.get("compact") or [""])[0]).lower() in {"1", "true", "yes"}:
                            artifacts = [
                                {
                                    key: value
                                    for key, value in artifact.items()
                                    if key != "metadata"
                                }
                                for artifact in artifacts
                            ]
                            world_generation = manager._compact_world_job(world_generation)
                        self._write_json(
                            {
                                "ok": True,
                                "artifacts": artifacts,
                                "world_generation": world_generation,
                                "live_preview": manager.live_preview_status(experiment_id),
                            }
                        )
                        return
                    if route == "/artifacts/file":
                        rel = str((query.get("path") or [""])[0])
                        if self._serve_artifact(rel):
                            return
                        self._write_json({"ok": False, "error": "Artifact not found"}, 404)
                        return
                    if route == "/artifacts/live.mjpeg":
                        rel = str((query.get("path") or [""])[0])
                        experiment_id = str((query.get("experiment_id") or [""])[0])
                        if self._serve_live_mjpeg(rel, experiment_id):
                            return
                        self._write_json({"ok": False, "error": "Live preview not found"}, 404)
                        return
                    if route == "/cosmos/benchmarks":
                        self._write_json({"ok": True, "benchmarks": manager.experiment_store.list_benchmarks()})
                        return
                    if route == "/batches":
                        self._write_json({"ok": True, "batches": manager.experiment_store.list_batches()})
                        return
                    if route == "/capabilities":
                        self._write_json(manager.capabilities_payload())
                        return
                    if route == "/cosmos/status":
                        self._write_json(manager.cached_cosmos_status())
                        return
                    if route == "/carla/status":
                        experiment_id = str((query.get("experiment_id") or [""])[0])
                        result = manager.carla_status(experiment_id)
                        self._write_json(result, 200 if result.get("ok") else 503)
                        return
                    if route == "/carla/frame.jpg":
                        experiment_id = str((query.get("experiment_id") or [""])[0])
                        result = manager.carla_request(
                            f"/frame.jpg?experiment_id={quote(experiment_id)}",
                            timeout=3.0,
                        )
                        if not result.get("ok"):
                            self._write_json(result, int(result.get("status", 503)))
                            return
                        body = result.get("body", b"") or b""
                        self._headers(str(result.get("content_type") or "image/jpeg"), 200, len(body))
                        self.wfile.write(body)
                        return
                    if route == "/metrics":
                        self._write_json({"ok": False, "error": "Select an experiment to read metrics"}, 404)
                        return
                    rel = route.lstrip("/")
                    if rel and self._serve_static(rel):
                        return
                    self._headers("text/plain", 404, 0)
                except BrokenPipeError:
                    return
                except Exception as exc:
                    self._write_json({"ok": False, "error": str(exc)}, 500)

            def do_POST(self):
                try:
                    parsed = urlparse(self.path)
                    route = self._api_route(parsed.path)
                    query = parse_qs(parsed.query)
                    if route == "/auth/login":
                        payload = self._read_json()
                        result = manager.security.login(
                            str(payload.get("username") or ""),
                            str(payload.get("password") or ""),
                            ip=self._client_ip(),
                            user_agent=self.headers.get("User-Agent", ""),
                        )
                        self._write_json(result, 200 if result.get("ok") else 401)
                        return
                    if route == "/auth/register":
                        payload = self._read_json()
                        result = manager.security.create_user(
                            str(payload.get("username") or ""),
                            str(payload.get("password") or ""),
                            role="operator",
                            enabled=True,
                        )
                        manager.security.log_event(
                            "auth",
                            "register" if result.get("ok") else "register_failed",
                            username=str(payload.get("username") or ""),
                            ip=self._client_ip(),
                            method=self.command,
                            path=route,
                            status="200" if result.get("ok") else "400",
                            details={"result": _safe_event_details(result)},
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/auth/logout":
                        user = self._require_user(route, query)
                        if user is None:
                            return
                        manager.security.logout(self._bearer_token(query))
                        manager.security.log_event("auth", "logout", user=user, ip=self._client_ip(), method=self.command, path=route)
                        self._write_json({"ok": True})
                        return
                    if route == "/admin/users":
                        user = self._require_user(route, query, admin=True)
                        if user is None:
                            return
                        payload = self._read_json()
                        result = manager.security.create_user(
                            str(payload.get("username") or ""),
                            str(payload.get("password") or ""),
                            role=str(payload.get("role") or "operator"),
                            enabled=bool(payload.get("enabled", True)),
                        )
                        manager.security.log_event(
                            "user_admin",
                            "create_user" if result.get("ok") else "create_user_failed",
                            user=user,
                            ip=self._client_ip(),
                            method=self.command,
                            path=route,
                            status="200" if result.get("ok") else "400",
                            details={"payload": _safe_event_details(payload), "result": _safe_event_details(result)},
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/admin/users/action":
                        user = self._require_user(route, query, admin=True)
                        if user is None:
                            return
                        payload = self._read_json()
                        result = manager.security.update_user(user, payload)
                        manager.security.log_event(
                            "user_admin",
                            str(payload.get("type") or "user_action"),
                            user=user,
                            ip=self._client_ip(),
                            method=self.command,
                            path=route,
                            status="200" if result.get("ok") else "400",
                            details={"payload": _safe_event_details(payload), "result": _safe_event_details(result)},
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route not in PUBLIC_POST_ROUTES:
                        user = self._require_user(
                            route,
                            query,
                            admin=route.startswith("/admin/"),
                            write=route not in {"/data/download_zip"},
                        )
                        if user is None:
                            return
                    else:
                        user = {}
                    if route == "/carla/focus":
                        payload = self._read_json()
                        result = manager.carla_action("/focus", payload)
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route.startswith("/proxy/"):
                        size = int(self.headers.get("Content-Length", "0") or "0")
                        payload = self.rfile.read(size) if size > 0 else b""
                        try:
                            proxy_path = "/" + (route.split("/", 3)[3] if len(route.split("/", 3)) > 3 else "status").lstrip("/")
                            if proxy_path in {"/action", "/api/v1/action"}:
                                action_payload = json.loads(payload.decode("utf-8")) if payload else {}
                                action_type = str(action_payload.get("type", "")).strip().lower()
                                if not self._enforce_high_risk(action_type, action_payload, user, route=route):
                                    return
                        except json.JSONDecodeError:
                            pass
                        result = manager.proxy_request(
                            route,
                            parsed.query,
                            method="POST",
                            payload=payload,
                            content_type=self.headers.get("Content-Type", ""),
                        )
                        self._write_proxy_response(result)
                        return
                    if route in {"/pause", "/resume"}:
                        result = manager.control_latest_experiment(route.lstrip("/"))
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/cosmos/restart":
                        manager.cosmos.restart()
                        self._write_json({"ok": True, "status": manager.cosmos.status()})
                        return
                    if route == "/action":
                        payload = self._read_json()
                        action_type = str(payload.get("type", "")).strip().lower()
                        if not self._enforce_high_risk(action_type, payload, user, route=route):
                            return
                        try:
                            result = manager.handle_action(payload)
                        except Exception as exc:
                            manager.security.log_event(
                                "manager_action",
                                "action_exception",
                                user=user,
                                ip=self._client_ip(),
                                method=self.command,
                                path=route,
                                status="500",
                                details={
                                    "action_type": action_type,
                                    "error": str(exc),
                                    "payload": _safe_event_details(payload),
                                },
                            )
                            raise
                        manager.security.log_event(
                            "manager_action",
                            "action_succeeded" if result.get("ok") else "action_rejected",
                            user=user,
                            ip=self._client_ip(),
                            method=self.command,
                            path=route,
                            status="200" if result.get("ok") else "400",
                            details={
                                "action_type": action_type,
                                "error": str(result.get("error") or ""),
                                "experiment_id": str(
                                    (result.get("experiment") or {}).get("id") or ""
                                ),
                            },
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/workflows/action":
                        result = manager.handle_workflow_action(self._read_json())
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/evaluation-systems/action":
                        result = manager.handle_evaluation_system_action(
                            self._read_json()
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/markers/action":
                        result = manager.handle_replay_marker_action(self._read_json())
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/data/upload":
                        result = manager.upload_scenario_records(self._read_multipart_files())
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/data/natural/upload":
                        dataset_id = str((query.get("id") or [""])[0])
                        target_path = str((query.get("path") or [""])[0])
                        result = manager.upload_natural_dataset(
                            self._read_multipart_files(),
                            dataset_id=dataset_id,
                            target_path=target_path,
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/data/standard/import":
                        category = str((query.get("category") or ["normal"])[0])
                        map_path = str((query.get("map_path") or [""])[0])
                        result = manager.import_standard_scenario_records(
                            self._read_multipart_files(),
                            category=category,
                            map_path=map_path,
                        )
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    if route == "/data/download_zip":
                        result = manager.zip_scenario_records(self._read_json().get("paths", []))
                        if not result.get("ok"):
                            self._write_json(result, 400)
                            return
                        self._send_bytes(result["data"], result["filename"], "application/zip")
                        return
                    if route == "/data/action":
                        payload = self._read_json()
                        action_type = str(payload.get("type", "")).strip().lower()
                        if not self._enforce_high_risk(action_type, payload, user, route=route):
                            return
                        result = manager.handle_data_action(payload)
                        self._write_json(result, 200 if result.get("ok") else 400)
                        return
                    self._headers("text/plain", 404, 0)
                except BrokenPipeError:
                    return
                except Exception as exc:
                    self._write_json({"ok": False, "error": str(exc)}, 500)

            def log_message(self, format, *args):
                pass

        self._server = _FastThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        lan_host = self._guess_lan_ip() if self.host in {"0.0.0.0", "::"} else self.host
        print(f"[Manager] GUI: http://127.0.0.1:{self.port}")
        print(f"[Manager] LAN: http://{lan_host}:{self.port}")
        print(f"[Manager] Child API bind: {self.child_host}, ports from {self.child_port_start}")

    @staticmethod
    def _guess_lan_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def status_payload(self) -> dict:
        cosmos_status = self.cached_cosmos_status()
        return {
            "ok": True,
            "api_version": "v1",
            "schema_version": "status.v1",
            "mode": "manager",
            "backend_model": "manager",
            "run_state": "idle",
            "paused": False,
            "step": 0,
            "vehicles": 0,
            "progress": 0.0,
            "sim_time": 0.0,
            "manager_mode": True,
            "multi_experiment": True,
            "experiment_count": self.experiment_store.count(),
            "auth_required": bool(self.security.enabled),
            "cosmos_ready": bool(cosmos_status.get("ready")),
            "cosmos_enabled": bool(cosmos_status.get("enabled")),
        }

    def cached_cosmos_status(self, max_age_seconds: float = 1.5) -> dict[str, Any]:
        """Return immediately while refreshing resident-model health off-thread."""
        now = time.monotonic()
        with self._cosmos_status_lock:
            cached = dict(self._cosmos_status_cache)
            fresh = now - self._cosmos_status_cache_at <= max_age_seconds
            if fresh:
                return cached
            if self._cosmos_status_refreshing:
                cached["refreshing"] = True
                return cached
            self._cosmos_status_refreshing = True

        def refresh() -> None:
            try:
                status = self.cosmos.status()
                status["refreshing"] = False
                with self._cosmos_status_lock:
                    self._cosmos_status_cache = status
                    self._cosmos_status_cache_at = time.monotonic()
            finally:
                with self._cosmos_status_lock:
                    self._cosmos_status_refreshing = False

        threading.Thread(target=refresh, name="CosmosStatus", daemon=True).start()
        cached["refreshing"] = True
        return cached

    def live_preview_status(self, experiment_id: str) -> dict[str, Any]:
        """Return the consumer clock; generation progress is a separate clock."""
        experiment_id = str(experiment_id or "")
        self._refresh_live_preview_clock(experiment_id)
        with self._lock:
            status = dict(self._world_preview_status.get(experiment_id) or {})
            clients = int(self._world_preview_clients.get(experiment_id, 0) or 0)
        status.setdefault("active", clients > 0)
        status["clients"] = clients
        return status

    @staticmethod
    def _compact_world_job(world_job: dict[str, Any]) -> dict[str, Any]:
        """Remove historical inference detail from the one-second UI heartbeat."""
        compact = dict(world_job or {})
        payload = dict(compact.get("payload") or {})
        for key in ("artifacts", "transfer_attempts", "transfer_job", "scene_export", "clipgt"):
            payload.pop(key, None)
        progress = dict(payload.get("omnidreams_progress") or {})
        for key in ("recent_chunks", "control_contract", "sessions", "session_ids"):
            progress.pop(key, None)
        if progress:
            payload["omnidreams_progress"] = progress
        compact["payload"] = payload
        return compact

    def _refresh_live_preview_clock(self, experiment_id: str) -> dict[str, Any]:
        """Advance one transport-independent clock over generated preview frames."""
        experiment_id = str(experiment_id or "").strip()
        if not experiment_id or not hasattr(self, "root"):
            return {}
        output_dir = self.root / "output" / "cosmos" / "experiments" / experiment_id / "omnidreams"
        progress_path = output_dir / "progress.json"
        sequence_dir = output_dir / "camera_front_wide_120fov_latest_frames"
        now = time.monotonic()
        with self._lock:
            cached_clock = getattr(self, "_world_preview_clocks", {}).get(experiment_id, {})
            use_cached_scan = (
                now - float(cached_clock.get("scan_at", 0.0) or 0.0) < 0.08
                and cached_clock.get("first_index") is not None
                and cached_clock.get("newest_index") is not None
            )
            cached_progress = dict(cached_clock.get("progress") or {})
            cached_first = cached_clock.get("first_index")
            cached_newest = cached_clock.get("newest_index")
        if use_cached_scan:
            progress = cached_progress
            first_index = int(cached_first)
            newest_index = int(cached_newest)
        else:
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                progress = {}
            try:
                available = sorted(sequence_dir.glob("*.jpg"))
            except OSError:
                available = []
            if not available:
                return {}
            first_index = int(available[0].stem)
            newest_index = int(available[-1].stem)
        output_fps = max(1.0, float(progress.get("fps", 30.0) or 30.0))
        preview_limit = max(1.0, float(progress.get("preview_fps", 15.0) or 15.0))
        preview_stride = max(1, int(round(output_fps / preview_limit)))
        generation_warmed = bool(progress.get("generation_warmed", False))
        stage = str(progress.get("stage") or "")
        terminal = stage in {"completed", "error", "failed", "stopped", "interrupted", "cancelled"}
        measured_output_fps = float(
            progress.get("recent_generation_fps", 0.0)
            or progress.get("sustained_generation_fps", 0.0)
            or 0.0
        )
        produced_preview_fps = (
            measured_output_fps / preview_stride if measured_output_fps > 0.0 else preview_limit
        )
        startup_buffer_seconds = max(
            0.1,
            min(
                10.0,
                float(os.environ.get("OMNIDREAMS_PREVIEW_BUFFER_SECONDS", "2.0") or 2.0),
            ),
        )
        available_video_seconds = max(
            0.0,
            float((newest_index - first_index) * preview_stride) / output_fps,
        )
        target_rate = preview_limit if terminal else min(preview_limit, max(0.25, produced_preview_fps * 0.96))
        with self._lock:
            clocks = getattr(self, "_world_preview_clocks", None)
            if clocks is None:
                self._world_preview_clocks = {}
                clocks = self._world_preview_clocks
            clock = clocks.setdefault(
                experiment_id,
                {
                    "position": float(first_index),
                    "rate": target_rate,
                    "last_tick": now,
                    "started": False,
                },
            )
            if not use_cached_scan:
                clock["scan_at"] = now
                clock["first_index"] = first_index
                clock["newest_index"] = newest_index
                clock["progress"] = dict(progress)
            elapsed = max(0.0, min(2.0, now - float(clock.get("last_tick", now) or now)))
            clock["last_tick"] = now
            current_rate = max(0.25, float(clock.get("rate", target_rate) or target_rate))
            # Rate changes are intentionally damped so chunk-level inference jitter
            # cannot become visible as stop/start playback.
            current_rate += (target_rate - current_rate) * min(1.0, elapsed * 0.8)
            clock["rate"] = current_rate
            position = max(float(first_index), float(clock.get("position", first_index) or first_index))
            if not bool(clock.get("started")) and (
                terminal
                or (generation_warmed and available_video_seconds >= startup_buffer_seconds)
            ):
                clock["started"] = True
                position = float(first_index)
            if bool(clock.get("started")):
                position = min(float(newest_index), position + elapsed * current_rate)
            clock["position"] = position

            playback_index = max(first_index, min(newest_index, int(math.floor(position))))
            playback_frame = float(playback_index * preview_stride)
            newest_source_frame = float(newest_index * preview_stride)
            playback_time = playback_frame / output_fps
            generated_video_time = float(
                progress.get("generated_video_time", (newest_source_frame + preview_stride) / output_fps)
                or 0.0
            )
            # This is source-video backlog, not wall time needed to drain a queue.
            buffer_seconds = max(0.0, (newest_source_frame - playback_frame) / output_fps)
            timeline_rate = max(1e-6, current_rate * preview_stride / output_fps)
            traffic_interval_ms = 100.0 / timeline_rate
            clients = int(self._world_preview_clients.get(experiment_id, 0) or 0)
            status = {
                "active": clients > 0,
                "clients": clients,
                "started": bool(clock.get("started")),
                "playback_index": playback_index,
                "first_index": first_index,
                "newest_index": newest_index,
                "preview_stride": preview_stride,
                "playback_frame": playback_frame,
                "playback_time": playback_time,
                "generated_video_time": generated_video_time,
                "buffer_seconds": round(buffer_seconds, 3),
                "startup_buffer_seconds": startup_buffer_seconds,
                "startup_buffer_ready": available_video_seconds >= startup_buffer_seconds,
                "playback_fps": round(current_rate, 3),
                "source_playback_fps": round(current_rate * preview_stride, 3),
                "timeline_rate": round(timeline_rate, 4),
                "traffic_interval_ms": round(traffic_interval_ms, 3),
                "display_interpolation": "client-linear-30hz",
                "generation_preview_fps": round(produced_preview_fps, 3),
                "arrival_preview_fps": round(produced_preview_fps, 3),
                "output_fps": output_fps,
                "generation_warmed": generation_warmed,
                "terminal": terminal,
                "updated_at_unix": time.time(),
            }
            self._world_preview_frames[experiment_id] = playback_frame
            self._world_preview_rates[experiment_id] = current_rate
            self._world_preview_status[experiment_id] = status
            return dict(status)

    @staticmethod
    def _memory_usage() -> dict[str, float]:
        values: dict[str, float] = {}
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, raw = line.split(":", 1)
                values[key] = float(raw.strip().split()[0]) * 1024.0
        except (OSError, ValueError, IndexError):
            return {"used_gb": 0.0, "total_gb": 0.0, "percent": 0.0}
        total = values.get("MemTotal", 0.0)
        available = values.get("MemAvailable", values.get("MemFree", 0.0))
        used = max(0.0, total - available)
        return {
            "used_gb": round(used / 1024**3, 1),
            "total_gb": round(total / 1024**3, 1),
            "percent": round(100.0 * used / total, 1) if total else 0.0,
        }

    @staticmethod
    def _gpu_usage() -> dict[str, Any]:
        command = [
            "nvidia-smi",
            "--query-gpu=index,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=1.5,
            )
        except (OSError, subprocess.SubprocessError):
            return {"count": 0, "percent": 0.0, "used_gb": 0.0, "total_gb": 0.0}
        devices = []
        for line in result.stdout.splitlines():
            try:
                index, utilization, used, total = [float(value.strip()) for value in line.split(",")]
            except (TypeError, ValueError):
                continue
            devices.append(
                {
                    "index": int(index),
                    "percent": utilization,
                    "used_gb": used / 1024.0,
                    "total_gb": total / 1024.0,
                }
            )
        total_memory = sum(item["total_gb"] for item in devices)
        used_memory = sum(item["used_gb"] for item in devices)
        return {
            "count": len(devices),
            "percent": round(
                sum(item["percent"] for item in devices) / len(devices), 1
            )
            if devices
            else 0.0,
            "used_gb": round(used_memory, 1),
            "total_gb": round(total_memory, 1),
            "devices": devices,
        }

    def _collect_dashboard(self) -> dict[str, Any]:
        cpu_count = max(1, int(os.cpu_count() or 1))
        try:
            load = float(os.getloadavg()[0])
        except (AttributeError, OSError):
            load = 0.0
        memory = self._memory_usage()
        disk = shutil.disk_usage(self.output_root)
        experiments = self.experiment_store.list(limit=1000)
        active_states = {"running", "playback", "playback_loading", "paused"}
        active = sum(
            str(record.get("run_state") or "").lower() in active_states
            for record in experiments
        )
        scenario_files = [
            path
            for path in self.scenario_root.rglob("*.pkl")
            if not path.name.endswith(".init.pkl")
        ]
        scenario_bytes = sum(
            path.stat().st_size for path in scenario_files if path.is_file()
        )
        return {
            "ok": True,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "resources": {
                "cpu": {
                    "percent": round(min(100.0, load * 100.0 / cpu_count), 1),
                    "load_1m": round(load, 2),
                    "cores": cpu_count,
                },
                "memory": memory,
                "gpu": self._gpu_usage(),
                "storage": {
                    "percent": round(100.0 * disk.used / disk.total, 1),
                    "used_gb": round(disk.used / 1024**3, 1),
                    "total_gb": round(disk.total / 1024**3, 1),
                },
            },
            "experiments": {
                "total": len(experiments),
                "active": active,
                "completed": sum(
                    str(record.get("run_state") or "").lower() == "completed"
                    for record in experiments
                ),
            },
            "data": {
                "scenario_count": len(scenario_files),
                "scenario_gb": round(scenario_bytes / 1024**3, 2),
                "standard_scenario_count": len(self.list_standard_scenario_records()),
            },
            "cosmos": self.cached_cosmos_status(),
        }

    def dashboard_payload(self, max_age_seconds: float = 2.0) -> dict[str, Any]:
        now = time.monotonic()
        with self._dashboard_lock:
            cached = dict(self._dashboard_cache)
            if cached and now - self._dashboard_cache_at <= max_age_seconds:
                return cached
            if self._dashboard_refreshing:
                return cached or {"ok": True, "refreshing": True}
            self._dashboard_refreshing = True

        def refresh() -> None:
            try:
                payload = self._collect_dashboard()
                with self._dashboard_lock:
                    self._dashboard_cache = payload
                    self._dashboard_cache_at = time.monotonic()
            finally:
                with self._dashboard_lock:
                    self._dashboard_refreshing = False

        threading.Thread(target=refresh, name="DashboardStatus", daemon=True).start()
        return cached or {"ok": True, "refreshing": True}

    def capabilities_payload(self) -> dict:
        return {
            "ok": True,
            "api_version": "v1",
            "schema_version": "capabilities.v1",
            "mode": "manager",
            "backend_model": "manager",
            "manager_mode": True,
            "features": {
                "manager_proxy": True,
                "multi_experiment": True,
                "single_public_port": True,
                "carla_3d_visualization": False,
                "auth": bool(self.security.enabled),
                "user_management": False,
                "security_events": True,
                "model_adapters": ["cnde", "neuralnde", "rulebased"],
                "cosmos_resident_models": True,
                "cosmos_warmup_pipeline": True,
                "standard_scenario_library": True,
                "operations_dashboard": True,
                "workflow_management": True,
            },
            "algorithms": {
                "cnde": {
                    "label": "CityNDE",
                    "generation": True,
                    "replay": True,
                    "data_management": True,
                    "init_modes": True,
                    "init_data": True,
                    "arrival_rate": True,
                    "vehicle_ops": True,
                    "av_access": True,
                    "output_kind": "scenario_pkl",
                    "metrics": {
                        "speed": True,
                        "ttc": True,
                        "headway": True,
                        "collision": True,
                        "arrival_rate": True,
                    },
                    "parameters": {
                        "av_model": ["DEFAULT_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM", "EXTERNAL_TCP", "VTD_TCP"],
                        "av_selection": ["manual", "random"],
                        "av_command_mode": ["state", "actuator"],
                        "av_tcp": True,
                    },
                    "reserved": {"infeasible_region": True, "multimodal": True},
                },
                "neuralnde": {
                    "label": "NeuralNDE",
                    "generation": True,
                    "replay": False,
                    "data_management": True,
                    "init_modes": False,
                    "init_data": False,
                    "arrival_rate": False,
                    "vehicle_ops": False,
                    "av_access": True,
                    "output_kind": "traffic_frames_jsonl",
                    "metrics": {
                        "speed": True,
                        "ttc": True,
                        "headway": True,
                        "collision": True,
                        "arrival_rate": False,
                    },
                    "parameters": {
                        "datasets": ["AA_rdbt", "rounD"],
                        "model_resolution": 0.4,
                        "stream_resolution": 0.04,
                        "av_model": ["DEFAULT_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM", "EXTERNAL_TCP", "VTD_TCP"],
                        "av_selection": ["manual", "random"],
                        "av_command_mode": ["state", "actuator"],
                        "av_tcp": True,
                    },
                    "reserved": {"infeasible_region": True, "multimodal": True},
                },
                "rulebased": {
                    "label": "IDM Rules (MOBIL criterion)",
                    "generation": True,
                    "replay": True,
                    "data_management": True,
                    "init_modes": True,
                    "init_data": True,
                    "arrival_rate": True,
                    "vehicle_ops": True,
                    "av_access": True,
                    "output_kind": "scenario_pkl",
                    "metrics": {
                        "speed": True,
                        "ttc": True,
                        "headway": True,
                        "collision": True,
                        "arrival_rate": True,
                    },
                    "parameters": {
                        "controller": "idm_mobil",
                        "recommended_vehicle_count": 8,
                        "model_resolution": 0.5,
                        "stream_resolution": 0.1,
                        "av_model": ["DEFAULT_TCP", "IDM_MOBIL", "EXTERNAL_TCP"],
                        "av_selection": ["manual", "random"],
                        "av_command_mode": ["state", "actuator"],
                        "av_tcp": True,
                    },
                    "reserved": {"infeasible_region": True, "multimodal": True},
                },
            },
        }

    def _is_port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", int(port)))
                return True
            except OSError:
                return False

    def _allocate_child_port(self) -> int:
        with self._lock:
            used = {int(info.get("port", 0) or 0) for info in self._experiments.values()}
        port = self.child_port_start
        while port in used or not self._is_port_free(port):
            port += 1
        return port

    @staticmethod
    def _safe_name(raw_name: str, fallback: str = "experiment") -> str:
        safe = []
        for ch in str(raw_name or "").strip():
            if ch.isalnum() or ch in ("-", "_"):
                safe.append(ch)
            elif ch.isspace():
                safe.append("_")
        return ("".join(safe).strip("_") or fallback)[:80]

    def _http_json(self, url: str, method: str = "GET", payload: dict | None = None, timeout: float = 0.75) -> dict | None:
        try:
            data = None
            headers = {}
            if payload is not None:
                data = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with _DIRECT_HTTP_OPENER.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except Exception:
            return None

    @property
    def _carla_gateway_url(self) -> str:
        return f"http://127.0.0.1:{self.carla_gateway_port}"

    def _ensure_carla_gateway(self) -> dict:
        status = self._http_json(f"{self._carla_gateway_url}/status", timeout=1.0)
        if status and status.get("gateway"):
            return status
        if not Path(self.carla_python).is_file():
            return {"ok": False, "error": f"CARLA Python environment not found: {self.carla_python}"}
        if not self.carla_gateway_script.is_file():
            return {"ok": False, "error": f"CARLA gateway not found: {self.carla_gateway_script}"}
        proc = self._carla_gateway_process
        if proc is None or proc.poll() is not None:
            log_dir = self.root / "backend" / "bridge" / "data"
            log_dir.mkdir(parents=True, exist_ok=True)
            self._carla_gateway_log = open(log_dir / "gateway.log", "ab", buffering=0)
            env = os.environ.copy()
            env.pop("LD_PRELOAD", None)
            env.pop("PYTHONPATH", None)
            env["PYTHONNOUSERSITE"] = "1"
            command = [
                self.carla_python,
                str(self.carla_gateway_script),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.carla_gateway_port),
                "--carla-root",
                str(self.carla_root),
            ]
            try:
                self._carla_gateway_process = subprocess.Popen(
                    command,
                    cwd=str(self.root),
                    env=env,
                    stdout=self._carla_gateway_log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                )
            except OSError as exc:
                return {"ok": False, "error": f"Failed to start CARLA gateway: {exc}"}
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            status = self._http_json(f"{self._carla_gateway_url}/status", timeout=1.0)
            if status and status.get("gateway"):
                return status
            proc = self._carla_gateway_process
            if proc is not None and proc.poll() is not None:
                return {
                    "ok": False,
                    "error": _tail_text(self.root / "backend" / "bridge" / "data" / "gateway.log")
                    or f"CARLA gateway exited with code {proc.poll()}",
                }
            time.sleep(0.25)
        return {"ok": False, "error": "Timed out waiting for CARLA gateway"}

    def carla_request(
        self,
        route: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        timeout: float = 5.0,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            request = urllib.request.Request(
                f"{self._carla_gateway_url}{route}",
                data=data,
                headers=headers,
                method=method,
            )
            with _DIRECT_HTTP_OPENER.open(request, timeout=timeout) as response:
                return {
                    "ok": True,
                    "status": int(response.status),
                    "content_type": response.headers.get("Content-Type", "application/octet-stream"),
                    "body": response.read(),
                }
        except urllib.error.HTTPError as exc:
            return {
                "ok": False,
                "status": int(exc.code),
                "error": exc.read().decode("utf-8", errors="replace"),
            }
        except Exception as exc:
            return {"ok": False, "status": 503, "error": str(exc)}

    def carla_status(self, experiment_id: str = "") -> dict:
        status = self._http_json(f"{self._carla_gateway_url}/status", timeout=1.5)
        if not status:
            return {"ok": False, "state": "not_started", "error": "CARLA gateway is not running"}
        active_id = str(status.get("experiment_id") or "")
        if experiment_id and active_id and experiment_id != active_id:
            return {
                "ok": False,
                "state": "inactive",
                "error": f"CARLA is attached to experiment {active_id}",
                "experiment_id": active_id,
            }
        return status

    def carla_action(self, route: str, payload: dict) -> dict:
        ready = self._ensure_carla_gateway()
        if not ready.get("ok"):
            return ready
        response = self.carla_request(route, method="POST", payload=payload, timeout=5.0)
        if not response.get("ok"):
            return response
        try:
            return json.loads((response.get("body") or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "error": "Invalid CARLA gateway response"}

    def _start_carla_session(self, exp_id: str) -> None:
        def worker():
            with self._lock:
                info = self._experiments.get(exp_id)
            if not info:
                return
            ready = self._ensure_carla_gateway()
            if not ready.get("ok"):
                info["carla_state"] = "error"
                info["carla_error"] = ready.get("error", "CARLA gateway failed to start")
                return
            child_ready = self._wait_child_ready(exp_id, timeout=60.0)
            if not child_ready.get("ok"):
                info["carla_state"] = "error"
                info["carla_error"] = child_ready.get("error", "Experiment adapter failed to start")
                return
            payload = {
                "experiment_id": exp_id,
                "state_url": f"http://127.0.0.1:{info['port']}/sim_state",
                "status_url": f"http://127.0.0.1:{info['port']}/status",
                "backend_model": info.get("backend_model", ""),
                "map_path": info.get("map_path", ""),
                "quality": info.get("carla_quality", "Epic"),
                "carla_gpu_id": info.get("carla_gpu_id", "1"),
                "carla_scene_path": info.get("carla_scene_path", ""),
                "environment_limit": info.get("carla_environment_limit", 450),
                "render_fps": info.get("carla_render_fps", 15),
                "startup_timeout": 150,
            }
            result = self.carla_action("/session/start", payload)
            info["carla_state"] = str(result.get("state") or ("starting" if result.get("ok") else "error"))
            info["carla_error"] = "" if result.get("ok") else str(result.get("error") or "")

        threading.Thread(target=worker, name=f"CARLAStart-{exp_id}", daemon=True).start()

    def _stop_carla_session(self, exp_id: str) -> None:
        status = self._http_json(f"{self._carla_gateway_url}/status", timeout=0.75)
        if status and str(status.get("experiment_id") or "") == exp_id:
            self.carla_action("/session/stop", {"experiment_id": exp_id})

    def proxy_request(
        self,
        route: str,
        query: str = "",
        *,
        method: str = "GET",
        payload: bytes | None = None,
        content_type: str = "",
    ) -> dict:
        parts = str(route or "").split("/", 3)
        if len(parts) < 3 or parts[1] != "proxy" or not parts[2]:
            return {"ok": False, "status": 400, "error": "Invalid proxy path"}
        exp_id = unquote(parts[2])
        subpath = "/" + (parts[3] if len(parts) > 3 and parts[3] else "status").lstrip("/")
        api_prefix = "/api/v1"
        endpoint_path = subpath[len(api_prefix):] if subpath.startswith(f"{api_prefix}/") else subpath
        with self._lock:
            info = self._experiments.get(exp_id)
        if not info:
            persisted = self.get_experiment(exp_id)
            if method.upper() == "GET" and endpoint_path == "/status":
                if persisted is not None:
                    return {
                        "ok": True,
                        "status": 200,
                        "content_type": "application/json",
                        "body": json.dumps(
                            persisted,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8"),
                    }
            if method.upper() == "GET" and endpoint_path == "/capabilities":
                return {
                    "ok": True,
                    "status": 200,
                    "content_type": "application/json",
                    "body": json.dumps(
                        self.capabilities_payload(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                }
            if method.upper() == "GET" and endpoint_path == "/maps":
                params = parse_qs(query)
                backend_model = str((params.get("backend_model") or ["cnde"])[0])
                body = {"ok": True, "maps": self.list_maps(backend_model)}
                return {
                    "ok": True,
                    "status": 200,
                    "content_type": "application/json",
                    "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                }
            if method.upper() == "GET" and endpoint_path == "/map_state" and persisted:
                preview = self.map_preview(
                    str(persisted.get("backend_model") or "cnde"),
                    str(persisted.get("map_path") or ""),
                )
                if preview.get("ok") and isinstance(preview.get("map_state"), dict):
                    body = {"ok": True, **preview["map_state"]}
                    return {
                        "ok": True,
                        "status": 200,
                        "content_type": "application/json",
                        "body": json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                    }
            return {"ok": False, "status": 404, "error": f"Experiment not found: {exp_id}"}
        proc = info.get("process")
        if proc is not None and proc.poll() is not None:
            info["return_code"] = proc.poll()
        if method.upper() == "GET" and endpoint_path == "/status" and (
            proc is None or proc.poll() is not None
        ):
            return {
                "ok": True,
                "status": 200,
                "content_type": "application/json",
                "body": json.dumps(
                    self.snapshot(exp_id, info),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8"),
            }
        if method.upper() == "GET" and endpoint_path == "/sim_state":
            synchronized = self._synchronized_world_state(exp_id)
            if synchronized is not None:
                params = parse_qs(query)
                try:
                    after_version = int((params.get("after") or ["-1"])[0])
                except (TypeError, ValueError):
                    after_version = -1
                if after_version >= int(synchronized.get("frame_version", 0) or 0):
                    synchronized = {
                        "ok": True,
                        "unchanged": True,
                        "frame_version": int(synchronized.get("frame_version", 0) or 0),
                    }
                return {
                    "ok": True,
                    "status": 200,
                    "content_type": "application/json",
                    "body": json.dumps(synchronized, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                }
        target_url = f"http://127.0.0.1:{int(info['port'])}{subpath}"
        if query:
            target_url += "?" + query
        headers = {"Content-Type": content_type} if content_type else {}
        try:
            req = urllib.request.Request(
                target_url,
                data=payload if method.upper() == "POST" else None,
                headers=headers,
                method=method.upper(),
            )
            timeout = 12.0 if method.upper() == "POST" else 3.0
            with _DIRECT_HTTP_OPENER.open(req, timeout=timeout) as resp:
                return {
                    "ok": True,
                    "status": int(resp.status),
                    "content_type": resp.headers.get("Content-Type", "application/octet-stream"),
                    "body": resp.read(),
                }
        except urllib.error.HTTPError as exc:
            return {
                "ok": True,
                "status": int(exc.code),
                "content_type": exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json",
                "body": exc.read(),
            }
        except Exception as exc:
            return {"ok": False, "status": 502, "error": str(exc)}

    def _synchronized_world_state(self, experiment_id: str) -> dict | None:
        preview_status = self._refresh_live_preview_clock(experiment_id)
        with self._lock:
            capture = getattr(self, "_world_captures", {}).get(experiment_id)
            preview_frame = getattr(self, "_world_preview_frames", {}).get(experiment_id)
            preview_fps = getattr(self, "_world_preview_rates", {}).get(experiment_id, 10.0)
        if capture is None or preview_frame is None:
            return None
        frames = list(capture.get("frames") or [])
        if not frames:
            return None
        output_fps = max(1.0, float(preview_status.get("output_fps", 30.0) or 30.0))
        preview_time = max(0.0, float(preview_frame) / output_fps)
        sampled_step = float(
            frames[1].get("sim_time", 0.1) - frames[0].get("sim_time", 0.0)
            if len(frames) > 1
            else 0.1
        )
        source_step = max(0.001, min(0.1, sampled_step))
        traffic_step = max(0, int(math.floor((preview_time + 1e-9) / source_step)))
        traffic_time = traffic_step * source_step
        selected = _interpolate_world_capture(frames, traffic_time)
        vehicles = []
        ego = selected.get("ego")
        if isinstance(ego, dict) and ego:
            vehicles.append(dict(ego))
        vehicles.extend(dict(item) for item in selected.get("vehicles") or selected.get("actors") or [])
        version = traffic_step + 1
        traffic_interval_ms = float(
            preview_status.get("traffic_interval_ms", 1000.0 / max(0.25, float(preview_fps)))
            or 100.0
        )
        return {
            "ok": True,
            "api_version": "v1",
            "schema_version": "scene_state.v1",
            "frame_version": version,
            "step": max(0, version - 1),
            "sim_time": float(selected.get("sim_time", 0.0) or 0.0),
            "vehicles": vehicles,
            "traffic_lights": selected.get("traffic_lights") or {},
            "world_video_frame": int(preview_frame),
            "world_video_time": preview_time,
            "world_preview_fps": float(preview_fps),
            "world_preview_interval_ms": traffic_interval_ms,
            "world_timeline_rate": float(preview_status.get("timeline_rate", 1.0) or 1.0),
            "world_synchronized": True,
        }

    def _read_workflows_unlocked(self) -> list[dict[str, Any]]:
        if not self.workflow_store_path.is_file():
            return []
        try:
            payload = json.loads(self.workflow_store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        records = payload.get("workflows", []) if isinstance(payload, dict) else payload
        return [dict(item) for item in records if isinstance(item, dict)]

    def _write_workflows_unlocked(self, workflows: list[dict[str, Any]]) -> None:
        self.platform_data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.workflow_store_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"version": 1, "workflows": workflows}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.workflow_store_path)

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._workflow_lock:
            records = self._read_workflows_unlocked()
        return sorted(
            records,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )

    @staticmethod
    def _next_workflow_id(workflows: list[dict[str, Any]]) -> str:
        date = time.strftime("%Y%m%d")
        prefix = f"DW-WF-{date}-"
        sequence = 0
        for workflow in workflows:
            workflow_id = str(workflow.get("id") or "")
            if not workflow_id.startswith(prefix):
                continue
            try:
                sequence = max(sequence, int(workflow_id[len(prefix) :]))
            except ValueError:
                continue
        return f"{prefix}{sequence + 1:04d}"

    def handle_workflow_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("type") or "save").strip().lower()
        with self._workflow_lock:
            workflows = self._read_workflows_unlocked()
            if action == "save":
                candidate = payload.get("workflow")
                if not isinstance(candidate, dict):
                    return {"ok": False, "error": "workflow object required"}
                workflow = dict(candidate)
                name = str(workflow.get("name") or "").strip()
                if not name:
                    return {"ok": False, "error": "Workflow name is required"}
                if len(name) > 80:
                    return {"ok": False, "error": "Workflow name must be at most 80 characters"}
                if str(workflow.get("scenario_mode") or "library") != "library":
                    workflow["use_existing_seed"] = False
                camera_config = workflow.get("camera_config")
                if isinstance(camera_config, dict):
                    camera_config = dict(camera_config)
                    for data_key, name_key in (
                        ("intrinsic_data", "intrinsic_file"),
                        ("extrinsic_data", "extrinsic_file"),
                    ):
                        calibration = camera_config.get(data_key)
                        if not isinstance(calibration, dict):
                            continue
                        content = str(calibration.get("content") or "")
                        content_bytes = content.encode("utf-8")
                        if len(content_bytes) > 256 * 1024:
                            return {
                                "ok": False,
                                "error": f"{data_key} must be at most 256 KiB",
                            }
                        filename = Path(str(calibration.get("name") or "calibration.txt")).name
                        camera_config[data_key] = {
                            "name": filename,
                            "type": str(calibration.get("type") or "text/plain")[:80],
                            "size": len(content_bytes),
                            "content": content,
                            "sha256": hashlib.sha256(content_bytes).hexdigest(),
                        }
                        camera_config[name_key] = filename
                    workflow["camera_config"] = camera_config
                workflow_id = str(workflow.get("id") or "").strip()
                current = next(
                    (item for item in workflows if str(item.get("id") or "") == workflow_id),
                    None,
                )
                duplicate = next(
                    (
                        item
                        for item in workflows
                        if str(item.get("name") or "").strip().casefold() == name.casefold()
                        and str(item.get("id") or "") != workflow_id
                    ),
                    None,
                )
                if duplicate is not None:
                    return {
                        "ok": False,
                        "error": f"Workflow name already exists: {name}",
                    }
                if not workflow_id:
                    workflow_id = self._next_workflow_id(workflows)
                elif current is None:
                    return {
                        "ok": False,
                        "error": "A new workflow ID must be allocated by the server",
                    }
                now = _now_text()
                workflow.update(
                    {
                        "id": workflow_id,
                        "name": name,
                        "task_id": str(workflow.get("task_id") or "DW-TASK-0001"),
                        "created_at": str((current or {}).get("created_at") or now),
                        "updated_at": now,
                    }
                )
                if current is None:
                    workflows.append(workflow)
                else:
                    workflows[workflows.index(current)] = workflow
                self._write_workflows_unlocked(workflows)
                return {"ok": True, "workflow": workflow, "workflows": workflows}
            if action == "delete":
                workflow_id = str(payload.get("workflow_id") or payload.get("id") or "").strip()
                remaining = [
                    item
                    for item in workflows
                    if str(item.get("id") or "") != workflow_id
                ]
                if len(remaining) == len(workflows):
                    return {"ok": False, "error": "Workflow not found"}
                self._write_workflows_unlocked(remaining)
                return {"ok": True, "workflow_id": workflow_id, "workflows": remaining}
        return {"ok": False, "error": f"Unsupported workflow action: {action}"}

    def _read_evaluation_systems_unlocked(self) -> list[dict[str, Any]]:
        if not self.evaluation_store_path.is_file():
            return []
        try:
            payload = json.loads(
                self.evaluation_store_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return []
        records = payload.get("evaluation_systems", []) if isinstance(payload, dict) else payload
        return [dict(item) for item in records if isinstance(item, dict)]

    def _write_evaluation_systems_unlocked(
        self, systems: list[dict[str, Any]]
    ) -> None:
        self.platform_data_root.mkdir(parents=True, exist_ok=True)
        temporary = self.evaluation_store_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "evaluation_systems": systems},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.evaluation_store_path)

    def list_evaluation_systems(self) -> list[dict[str, Any]]:
        with self._evaluation_lock:
            records = self._read_evaluation_systems_unlocked()
        return sorted(
            records,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )

    @staticmethod
    def _next_evaluation_system_id(systems: list[dict[str, Any]]) -> str:
        date = time.strftime("%Y%m%d")
        prefix = f"DW-EVAL-{date}-"
        sequence = 0
        for system in systems:
            system_id = str(system.get("id") or "")
            if not system_id.startswith(prefix):
                continue
            try:
                sequence = max(sequence, int(system_id[len(prefix) :]))
            except ValueError:
                continue
        return f"{prefix}{sequence + 1:04d}"

    def handle_evaluation_system_action(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        action = str(payload.get("type") or "save").strip().lower()
        with self._evaluation_lock:
            systems = self._read_evaluation_systems_unlocked()
            if action == "save":
                candidate = payload.get("evaluation_system")
                if not isinstance(candidate, dict):
                    return {"ok": False, "error": "evaluation_system object required"}
                system = dict(candidate)
                name = str(system.get("name") or "").strip()
                if not name:
                    return {"ok": False, "error": "Evaluation system name is required"}
                if len(name) > 80:
                    return {"ok": False, "error": "Evaluation system name must be at most 80 characters"}
                weights = system.get("weights")
                metrics = system.get("metrics")
                if not isinstance(weights, dict) or not isinstance(metrics, dict):
                    return {"ok": False, "error": "Evaluation weights and metrics are required"}
                try:
                    normalized_weights = {
                        key: float(weights.get(key, 0.0) or 0.0)
                        for key in ("safety", "comfort", "efficiency")
                    }
                except (TypeError, ValueError):
                    return {"ok": False, "error": "Evaluation weights must be numeric"}
                if any(value < 0.0 or value > 100.0 for value in normalized_weights.values()):
                    return {"ok": False, "error": "Evaluation weights must be between 0 and 100"}
                if abs(sum(normalized_weights.values()) - 100.0) > 0.001:
                    return {"ok": False, "error": "Evaluation weights must total 100"}
                system_id = str(system.get("id") or "").strip()
                current = next(
                    (item for item in systems if str(item.get("id") or "") == system_id),
                    None,
                )
                duplicate = next(
                    (
                        item
                        for item in systems
                        if str(item.get("name") or "").strip().casefold() == name.casefold()
                        and str(item.get("id") or "") != system_id
                    ),
                    None,
                )
                if duplicate is not None:
                    return {"ok": False, "error": f"Evaluation system name already exists: {name}"}
                if not system_id:
                    system_id = self._next_evaluation_system_id(systems)
                elif current is None:
                    return {"ok": False, "error": "A new evaluation system ID must be allocated by the server"}
                now = _now_text()
                system.update(
                    {
                        "id": system_id,
                        "name": name,
                        "weights": normalized_weights,
                        "readonly": False,
                        "created_at": str((current or {}).get("created_at") or now),
                        "updated_at": now,
                    }
                )
                if current is None:
                    systems.append(system)
                else:
                    systems[systems.index(current)] = system
                self._write_evaluation_systems_unlocked(systems)
                return {
                    "ok": True,
                    "evaluation_system": system,
                    "evaluation_systems": systems,
                }
            if action == "delete":
                system_id = str(payload.get("evaluation_system_id") or payload.get("id") or "").strip()
                remaining = [
                    item for item in systems if str(item.get("id") or "") != system_id
                ]
                if len(remaining) == len(systems):
                    return {"ok": False, "error": "Evaluation system not found"}
                self._write_evaluation_systems_unlocked(remaining)
                return {
                    "ok": True,
                    "evaluation_system_id": system_id,
                    "evaluation_systems": remaining,
                }
        return {"ok": False, "error": f"Unsupported evaluation system action: {action}"}

    def list_maps(self, backend_model: str = "cnde") -> list[str]:
        model = str(backend_model or "cnde").strip().lower()
        if model in {"neuralnde", "neural_nde"}:
            return [
                dataset
                for dataset in ("AA_rdbt", "rounD")
                if (self.neuralnde_root / "configs" / f"{dataset}_inference.yml").is_file()
            ]
        if model not in {"cnde", "citynde", "rulebased", "rule_based", "idm_mobil"}:
            return []
        if not self.citynde_root.is_dir():
            return []
        map_root = self.citynde_root / "assets" / "map"
        if not map_root.is_dir():
            return []
        return [str(p.relative_to(self.citynde_root)).replace("\\", "/") for p in sorted(map_root.rglob("*.pkl"))]

    def map_preview(self, backend_model: str, map_path: str) -> dict[str, Any]:
        model = str(backend_model or "cnde").strip().lower()
        requested = str(map_path or "").strip()
        if model in {"cnde", "citynde", "rulebased", "rule_based", "idm_mobil"} and requested:
            candidate = Path(requested)
            if candidate.is_absolute():
                try:
                    requested = str(candidate.resolve().relative_to(self.citynde_root)).replace("\\", "/")
                except ValueError:
                    pass
            else:
                citynde_prefix = self._repo_rel(self.citynde_root).rstrip("/") + "/"
                if requested.startswith(citynde_prefix):
                    requested = requested[len(citynde_prefix):]
        if requested not in self.list_maps(model):
            return {"ok": False, "error": "Map is not present in the configured map catalog"}
        if model in {"neuralnde", "neural_nde"}:
            candidates = sorted(
                (self.output_root / "cosmos" / "experiments").glob(
                    "neuralnde_*/map_state.json"
                ),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for candidate in candidates:
                try:
                    map_state = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError):
                    continue
                if str(map_state.get("map_path") or "") == requested:
                    return {"ok": True, "source": self._repo_rel(candidate), "map_state": map_state}
            return {"ok": False, "error": "NeuralNDE map preview cache is not available"}

        source = (self.citynde_root / requested).resolve()
        if not _is_relative_to(source, self.citynde_root) or not source.is_file():
            return {"ok": False, "error": "CityNDE map file not found"}
        cache_root = self.output_root / "cache" / "citynde_map_state"
        for candidate in sorted(cache_root.glob("*.json")):
            try:
                cached = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                continue
            if Path(str(cached.get("map_path") or "")).resolve() != source:
                continue
            map_state = cached.get("map_state")
            if isinstance(map_state, dict):
                map_state = dict(map_state)
                if model in {"rulebased", "rule_based", "idm_mobil"}:
                    map_state["backend_model"] = "rulebased"
                return {"ok": True, "source": self._repo_rel(candidate), "map_state": map_state}
        return {
            "ok": False,
            "error": "CityNDE map preview cache is not available; start one short scene to create it",
        }

    def _citynde_rel(self, path: Path) -> str:
        return self._repo_rel(path)

    def _repo_rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root)).replace("\\", "/")

    def _normalize_record_path(self, path: str) -> str:
        text = str(path or "").replace("\\", "/")
        if not text:
            return ""
        citynde_prefix = self._repo_rel(self.citynde_root).rstrip("/") + "/"
        misplaced_cosmos_prefix = citynde_prefix + "output/cosmos/"
        if text.startswith(misplaced_cosmos_prefix):
            workspace_path = "output/cosmos/" + text[len(misplaced_cosmos_prefix) :]
            if (self.root / workspace_path).exists():
                return workspace_path
        if text.startswith("algorithm_sources/"):
            return text
        if text.startswith("output/"):
            return self._repo_rel(self.root / text)
        return text

    def _recover_completed_transfer_replays(self) -> None:
        """Promote legacy boundary-gate failures only after validating the saved video."""
        legacy_error_markers = (
            "five-frame chain failed boundary consistency checks",
            "failed boundary consistency checks",
        )
        for record in self.experiment_store.list():
            if str(record.get("backend_model") or "") != "cosmos_transfer2.5":
                continue
            if str(record.get("run_state") or "") != "error":
                continue
            experiment_id = str(record.get("id") or "").strip()
            if not experiment_id:
                continue
            world_job = self.experiment_store.world_job(experiment_id)
            failure = str(world_job.get("error") or record.get("last_error") or "").lower()
            if not any(marker in failure for marker in legacy_error_markers):
                continue

            output_root = self.root / "output" / "cosmos" / "replay_jobs" / experiment_id
            manifest_path = output_root / "segments" / "manifest.json"
            video_path = output_root / "videos" / "front_wide.mp4"
            if not manifest_path.is_file() or not video_path.is_file():
                continue
            started = time.perf_counter()
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                boundary_quality = assess_transfer_crossfade_boundaries(
                    manifest.get("boundary_quality") or {}
                )
                if not boundary_quality.get("crossfade_acceptable"):
                    continue
                plan = manifest.get("plan") or {}
                fps = max(1, int(plan.get("fps", 10) or 10))
                target_frames = max(1, int(plan.get("target_frames", 0) or 0))
                media = probe_video(video_path)
                if (
                    target_frames <= 0
                    or int(media.get("frames", 0) or 0) != target_frames
                    or abs(float(media.get("fps", 0.0) or 0.0) - fps) > 0.02
                ):
                    continue
                duration = target_frames / float(fps)
                quality = analyze_group(
                    [video_path],
                    output_root / "qa" / "transfer",
                    expected_duration=duration,
                    expected_fps=float(fps),
                    quality_profile="generated_driving",
                )
                if not quality.get("passed"):
                    continue
                playback = create_playback_proxy(
                    video_path,
                    output_root / "playback" / "transfer_replay_front_wide_30fps.mp4",
                    duration_seconds=duration,
                    fps=30,
                )
                manifest.update(
                    {
                        "boundary_quality": boundary_quality,
                        "final_output_quality": quality,
                        "passed": True,
                        "recovered_from_legacy_boundary_gate": True,
                    }
                )
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                recovered_artifacts = [
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_segment_manifest",
                        manifest_path,
                        mime_type="application/json",
                    ),
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_front_wide",
                        video_path,
                        mime_type="video/mp4",
                        metadata={"view": "front_wide", "fps": fps, "frames": target_frames},
                    ),
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_front_wide_smooth",
                        playback,
                        mime_type="video/mp4",
                        metadata={"native_fps": fps, "display_fps": 30, "interpolation": "frame_blend"},
                    ),
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_qa",
                        output_root / "qa" / "transfer" / "video_qa.json",
                        mime_type="application/json",
                    ),
                ]
                payload = dict(world_job.get("payload") or {})
                payload.update(
                    {
                        "transfer_quality": quality,
                        "generation_strategy": manifest.get("strategy"),
                        "recovered_from_legacy_boundary_gate": True,
                        "artifacts": [*(payload.get("artifacts") or []), *recovered_artifacts],
                    }
                )
                timings = dict(world_job.get("timings") or {})
                timings["recovery_qa_seconds"] = round(time.perf_counter() - started, 4)
                self.experiment_store.upsert_world_job(
                    experiment_id,
                    stage="transfer_full",
                    run_state="completed",
                    progress=1.0,
                    message="Replay video recovered after final output validation",
                    error="",
                    payload=payload,
                    timings=timings,
                )
                record.update(
                    {
                        "run_state": "completed",
                        "progress": 1.0,
                        "last_error": "",
                        "output_dir": self._repo_rel(output_root),
                        "world_generation": self.experiment_store.world_job(experiment_id),
                    }
                )
                record["last_status"] = {
                    **(record.get("last_status") or {}),
                    "run_state": "completed",
                    "progress": 1.0,
                    "experiment_completed": True,
                    "last_error": "",
                }
                self.experiment_store.upsert(record)
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
                print(f"[Manager] Transfer replay recovery skipped for {experiment_id}: {exc}")

    def revalidate_world_output(self, experiment_id: str) -> dict:
        if not experiment_id:
            return {"ok": False, "error": "experiment_id is required"}
        with self._lock:
            info = self._experiments.get(experiment_id)
            active = self._world_threads.get(experiment_id)
        record = info if info is not None else self.experiment_store.get(experiment_id)
        if record is None:
            return {"ok": False, "error": "Experiment not found"}
        if active is not None and active.is_alive():
            return {"ok": False, "error": "DenseWorld job is still running"}
        output_root = self.root / "output" / "cosmos" / "experiments" / experiment_id
        video_path = output_root / "omnidreams" / "camera_front_wide_120fov.mp4"
        if not video_path.is_file():
            return {"ok": False, "error": "Completed OmniDreams video was not found"}

        cancel_event = threading.Event()
        world_job = self._set_world_job(
            experiment_id,
            stage="qa_revalidation",
            run_state="running",
            progress=0.99,
            message="Revalidating the completed OmniDreams video",
            error="",
        )
        if info is not None:
            with self._lock:
                info["last_error"] = ""
                info["last_status"] = {
                    **(info.get("last_status") or {}),
                    "run_state": "running",
                    "paused": False,
                    "progress": 0.99,
                    "experiment_completed": False,
                    "last_error": "",
                }
            record = self.snapshot(experiment_id, info)
        else:
            record = dict(record)
            record.update(
                {
                    "run_state": "running",
                    "paused": False,
                    "progress": 0.99,
                    "last_error": "",
                    "world_generation": world_job,
                }
            )
        self.experiment_store.upsert(record)
        thread = threading.Thread(
            target=self._revalidate_world_output_worker,
            args=(experiment_id, output_root, video_path),
            name=f"WorldQARevalidation-{experiment_id}",
            daemon=True,
        )
        with self._lock:
            self._world_cancel_events[experiment_id] = cancel_event
            self._world_threads[experiment_id] = thread
        thread.start()
        experiment = self.get_experiment(experiment_id)
        return {"ok": True, "experiment": experiment}

    def _revalidate_world_output_worker(
        self,
        experiment_id: str,
        output_root: Path,
        video_path: Path,
    ) -> None:
        started = time.perf_counter()
        try:
            media = probe_video(video_path)
            duration = float(media.get("duration_seconds", 0.0) or 0.0)
            fps = float(media.get("fps", 0.0) or 0.0)
            quality = analyze_group(
                [video_path],
                output_root / "qa" / "omnidreams",
                expected_duration=duration,
                expected_fps=fps,
                quality_profile="generated_driving",
            )
            if not quality.get("passed"):
                errors = [
                    error
                    for view in quality.get("views") or []
                    for error in view.get("errors") or []
                ]
                raise RuntimeError(
                    "OmniDreams output failed driving-scene QA: "
                    + ("; ".join(errors[:4]) or "unknown visual-quality failure")
                )
            manifest_path = output_root / "omnidreams" / "manifest.json"
            manifest = {}
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            control_path_value = str(
                manifest.get("hdmap_condition_video") or ""
            ).strip()
            control_path = (
                Path(control_path_value).resolve()
                if control_path_value
                else output_root
                / "omnidreams"
                / "camera_front_wide_120fov_hdmap.mp4"
            )
            control_quality = {}
            if control_path.is_file():
                control_media = probe_video(control_path)
                control_quality = analyze_group(
                    [control_path],
                    output_root / "qa" / "omnidreams_control",
                    expected_duration=float(
                        control_media.get("duration_seconds", duration) or duration
                    ),
                    expected_fps=float(control_media.get("fps", fps) or fps),
                    quality_profile="semantic_control",
                )
                if not control_quality.get("passed"):
                    errors = [
                        error
                        for view in control_quality.get("views") or []
                        for error in view.get("errors") or []
                    ]
                    raise RuntimeError(
                        "OmniDreams control video failed QA: "
                        + ("; ".join(errors[:4]) or "unknown control-video failure")
                    )
            control_trace_value = str(manifest.get("control_trace") or "").strip()
            control_trace = (
                Path(control_trace_value).resolve() if control_trace_value else None
            )
            world_job = self.experiment_store.world_job(experiment_id)
            artifacts = list((world_job.get("payload") or {}).get("artifacts") or [])
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "omnidreams_video",
                    video_path,
                    mime_type="video/mp4",
                    metadata=manifest,
                )
            )
            if control_path.is_file():
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "omnidreams_hdmap_control",
                        control_path,
                        mime_type="video/mp4",
                        metadata={
                            "fps": float(control_media.get("fps", fps) or fps),
                            "control_contract": manifest.get("control_contract"),
                            "dynamic_actor_count_range": manifest.get(
                                "dynamic_actor_count_range"
                            ),
                        },
                    )
                )
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "omnidreams_control_qa",
                        output_root
                        / "qa"
                        / "omnidreams_control"
                        / "video_qa.json",
                        mime_type="application/json",
                    )
                )
            if control_trace is not None and control_trace.is_file():
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "omnidreams_control_trace",
                        control_trace,
                        mime_type="application/x-ndjson",
                        metadata={
                            "dynamic_actor_membership": manifest.get(
                                "dynamic_actor_membership"
                            ),
                        },
                    )
                )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "omnidreams_qa",
                    output_root / "qa" / "omnidreams" / "video_qa.json",
                    mime_type="application/json",
                )
            )
            self._set_world_job(
                experiment_id,
                stage="completed",
                run_state="completed",
                progress=1.0,
                message="Completed OmniDreams video passed QA revalidation",
                error="",
                payload={
                    "omnidreams": manifest,
                    "omnidreams_quality": quality,
                    "omnidreams_control_quality": control_quality,
                    "qa_revalidated": True,
                    "artifacts": artifacts,
                },
                timing=("qa_revalidation_seconds", time.perf_counter() - started),
            )
            with self._lock:
                info = self._experiments.get(experiment_id)
                if info is not None:
                    info["last_error"] = ""
                    info["last_status"] = {
                        **(info.get("last_status") or {}),
                        "run_state": "completed",
                        "paused": False,
                        "progress": 1.0,
                        "experiment_completed": True,
                        "last_error": "",
                    }
            if info is not None:
                record = self.snapshot(experiment_id, info)
            else:
                record = self.experiment_store.get(experiment_id)
                if record is not None:
                    record.update(
                        {
                            "run_state": "completed",
                            "paused": False,
                            "progress": 1.0,
                            "last_error": "",
                            "world_generation": self.experiment_store.world_job(
                                experiment_id
                            ),
                        }
                    )
            if record is not None:
                # Historical experiments are not restored into ``_experiments``.
                # Revalidation adds rows to the artifact table, so refresh the
                # embedded list before persisting the compact experiment record.
                record["artifacts"] = self.experiment_store.list_artifacts(
                    experiment_id
                )
                self.experiment_store.upsert(record)
            update_world_sync(
                output_root / "traffic_video_sync.json",
                stage="completed",
                error="",
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            error = str(exc)
            self._set_world_job(
                experiment_id,
                stage="error",
                run_state="error",
                progress=1.0,
                message="OmniDreams QA revalidation failed",
                error=error,
                timing=("qa_revalidation_seconds", time.perf_counter() - started),
            )
            with self._lock:
                info = self._experiments.get(experiment_id)
                if info is not None:
                    info["last_error"] = error
                    info["last_status"] = {
                        **(info.get("last_status") or {}),
                        "run_state": "error",
                        "paused": False,
                        "progress": 1.0,
                        "last_error": error,
                    }
            if info is not None:
                record = self.snapshot(experiment_id, info)
            else:
                record = self.experiment_store.get(experiment_id)
                if record is not None:
                    record.update(
                        {
                            "run_state": "error",
                            "paused": False,
                            "progress": 1.0,
                            "last_error": error,
                            "world_generation": self.experiment_store.world_job(
                                experiment_id
                            ),
                        }
                    )
            if record is not None:
                self.experiment_store.upsert(record)
            update_world_sync(
                output_root / "traffic_video_sync.json",
                stage="error",
                error=error,
            )
        finally:
            with self._lock:
                self._world_threads.pop(experiment_id, None)
                self._world_cancel_events.pop(experiment_id, None)

    def _scenario_target(self, rel_path: str, *, require_output: bool = True) -> tuple[Path | None, dict | None]:
        if not rel_path:
            return None, {"ok": False, "error": "path is required"}
        raw = Path(rel_path)
        if raw.is_absolute():
            target = raw.resolve()
        elif str(rel_path).replace("\\", "/").startswith(("algorithm_sources/", "output/")):
            target = (self.root / rel_path).resolve()
        else:
            canonical_candidate = (self.scenario_root / rel_path).resolve()
            legacy_candidate = (self.citynde_root / rel_path).resolve()
            target = canonical_candidate if canonical_candidate.exists() else legacy_candidate
        managed_roots = [self.scenario_root.resolve(), (self.citynde_root / "output").resolve()]
        if not any(_is_relative_to(target, root) for root in managed_roots):
            return None, {"ok": False, "error": "Scenario path outside managed CityNDE outputs"}
        if require_output:
            if not any(_is_relative_to(target, root) for root in managed_roots):
                return None, {"ok": False, "error": f"Only scenario files under {self._repo_rel(self.scenario_root)} can be managed"}
        if target.suffix.lower() != ".pkl":
            return None, {"ok": False, "error": "Only .pkl files are supported"}
        if target.name.endswith(".init.pkl"):
            return None, {
                "ok": False,
                "error": "Seed initialization sidecars cannot be managed as scenarios",
            }
        return target, None

    def list_scenario_records(self) -> list[dict]:
        records = []
        seen: set[Path] = set()
        for output_dir in (self.scenario_root, self.citynde_root / "output"):
            if not output_dir.is_dir():
                continue
            for path in sorted(output_dir.rglob("*.pkl")):
                if not path.is_file():
                    continue
                if path.name.endswith(".init.pkl"):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                try:
                    st = path.stat()
                    metadata = self._citynde_scenario_metadata(path, st.st_mtime)
                    records.append(
                        {
                            "path": self._citynde_rel(path),
                            "size": int(st.st_size),
                            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                            "algorithm": "citynde",
                            "kind": "scenario_pkl",
                            "replayable": True,
                            **metadata,
                        }
                    )
                except OSError:
                    continue
        return records

    def list_standard_scenario_records(self) -> list[dict]:
        library_root = self.scenario_root / "library"
        if not library_root.is_dir():
            return []
        records = []
        archive_root = self.scenario_root / "archive"
        candidates = list(library_root.glob("*.pkl"))
        if archive_root.is_dir():
            candidates.extend(archive_root.glob("*/*.pkl"))
        for path in sorted(candidates):
            if path.name.endswith(".init.pkl"):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            metadata = self._citynde_scenario_metadata(path, stat.st_mtime)
            if not metadata.get("library_id"):
                continue
            seed_bundle = inspect_scenario_seed_bundle(path, metadata, self.root)
            backend_model = str(metadata.get("backend_model") or "cnde").strip().lower()
            records.append(
                {
                    "path": self._citynde_rel(path),
                    "size": int(stat.st_size),
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
                    ),
                    "algorithm": backend_model,
                    "kind": "standard_scenario",
                    "replayable": True,
                    **metadata,
                    "seed_available": bool(seed_bundle.get("available")),
                    "seed_status": str(seed_bundle.get("status") or "missing"),
                    "seed_reason": str(seed_bundle.get("reason") or ""),
                    "seed_bundle": seed_bundle,
                }
            )
        order = {"normal": 0, "pedestrian": 1, "cyclist": 2}
        return sorted(
            records,
            key=lambda record: (
                order.get(str(record.get("library_category") or ""), 99),
                str(record.get("library_name") or ""),
            ),
        )

    def scenario_preview(self, rel_path: str, *, max_frames: int = 60) -> dict[str, Any]:
        """Return a compact trajectory sample without starting a replay process."""
        target, error, model = self._record_target(rel_path)
        if error is not None or target is None or not target.is_file():
            return error or {"ok": False, "error": "Scenario file not found"}
        if model != "citynde":
            return {"ok": False, "error": "Only CityNDE PKL preview is currently supported"}
        try:
            with target.open("rb") as stream:
                data = pickle.load(stream)
            id_steps = list(data.get("vehicle_id_per_step") or [])
            state_steps = list(data.get("vehicle_state_per_step") or [])
            frame_count = min(len(id_steps), len(state_steps))
            if frame_count <= 0:
                raise ValueError("Scenario has no traffic frames")
            static = {
                str(key): value
                for key, value in (data.get("vehicle_static_attribute") or {}).items()
            }
            actor_types = {
                str(key): value
                for key, value in (data.get("road_user_type") or {}).items()
            }
            metadata = self._citynde_scenario_metadata(target)
            ego_id = str(metadata.get("seed_ego_id") or metadata.get("av_id") or "")
            requested = max(2, min(180, int(max_frames or 60)))
            indices = sorted(
                {
                    min(
                        frame_count - 1,
                        int(round(index * (frame_count - 1) / max(1, requested - 1))),
                    )
                    for index in range(min(requested, frame_count))
                }
            )
            resolution = float(
                (data.get("simulator_meta_info") or {}).get("resolution")
                or metadata.get("sim_resolution")
                or 0.1
            )
            frames = []
            bounds = [math.inf, math.inf, -math.inf, -math.inf]
            for source_index in indices:
                actors = []
                for actor_id, raw_state in zip(id_steps[source_index], state_steps[source_index]):
                    values = list(raw_state)
                    if len(values) < 3:
                        continue
                    dimensions = list(static.get(str(actor_id), [3.8, 1.8, 1.5]))
                    vx = float(values[3]) if len(values) > 3 else 0.0
                    vy = float(values[4]) if len(values) > 4 else 0.0
                    actor = {
                        "id": str(actor_id),
                        "x": round(float(values[0]), 4),
                        "y": round(float(values[1]), 4),
                        "heading": round(float(values[2]), 5),
                        "speed": round(math.hypot(vx, vy), 4),
                        "length": round(float(dimensions[0]), 3),
                        "width": round(float(dimensions[1]), 3),
                        "type": str(actor_types.get(str(actor_id), "vehicle")),
                        "is_ego": bool(ego_id and str(actor_id) == ego_id),
                    }
                    actors.append(actor)
                    bounds[0] = min(bounds[0], actor["x"])
                    bounds[1] = min(bounds[1], actor["y"])
                    bounds[2] = max(bounds[2], actor["x"])
                    bounds[3] = max(bounds[3], actor["y"])
                frames.append(
                    {
                        "source_step": source_index,
                        "sim_time": round(source_index * resolution, 4),
                        "vehicles": actors,
                    }
                )
            if not all(math.isfinite(value) for value in bounds):
                bounds = [-10.0, -10.0, 10.0, 10.0]
            return {
                "ok": True,
                "path": self._repo_rel(target),
                "frame_count": frame_count,
                "sample_count": len(frames),
                "sim_resolution": resolution,
                "duration_seconds": max(0.0, (frame_count - 1) * resolution),
                "ego_id": ego_id,
                "map_path": str(metadata.get("map_path") or ""),
                "backend_model": str(metadata.get("backend_model") or "cnde"),
                "bounds": bounds,
                "frames": frames,
            }
        except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            return {"ok": False, "error": f"Scenario preview failed: {exc}"}

    @staticmethod
    def _dataset_directory_record(
        dataset_id: str,
        name: str,
        algorithm: str,
        path: Path,
        description: str,
        *,
        read_only: bool = True,
    ) -> dict[str, Any]:
        files = []
        total_size = 0
        file_types: dict[str, int] = {}
        image_file_count = 0
        trajectory_file_count = 0
        if path.is_dir():
            # The catalog is an index, not a storage audit. Recursively walking
            # model datasets made every data-page visit scale with all source
            # assets even though the UI only needs top-level availability.
            for item in path.iterdir():
                if not item.is_file():
                    continue
                try:
                    total_size += item.stat().st_size
                    files.append(item.name)
                    suffix = item.suffix.lower().lstrip(".") or "none"
                    file_types[suffix] = file_types.get(suffix, 0) + 1
                    if suffix in {"jpg", "jpeg", "png", "webp", "bmp"}:
                        image_file_count += 1
                    if suffix in {"pkl", "pickle"}:
                        trajectory_file_count += 1
                except OSError:
                    continue
        return {
            "id": dataset_id,
            "name": name,
            "algorithm": algorithm,
            "kind": "natural_dataset",
            "path": str(path),
            "description": description,
            "file_count": len(files),
            "size": total_size,
            "frame_count": None,
            "frame_status": "raw source assets do not expose a normalized timeline",
            "trajectory_file_count": trajectory_file_count,
            "image_asset_count": image_file_count,
            "file_types": dict(sorted(file_types.items())),
            "inventory_scope": "top_level",
            "read_only": bool(read_only),
            "downloadable": path.is_dir(),
            "replayable": False,
        }

    def natural_dataset_records(self) -> list[dict[str, Any]]:
        neural_data = self.neuralnde_root / "data"
        records = [
            self._dataset_directory_record(
                "citynde-nuplan-boston",
                "CityNDE nuPlan Boston 先验",
                "citynde",
                self.citynde_root / "assets" / "intention_priors",
                "CityNDE Boston 路口意图先验与时间间隔配置。",
            ),
            self._dataset_directory_record(
                "neuralnde-aa-rdbt",
                "NeuralNDE AA_rdbt",
                "neuralnde",
                neural_data / "inference" / "AA_rdbt",
                "AA 环岛推理地图、行为网络与安全映射模型。",
            ),
            self._dataset_directory_record(
                "neuralnde-round",
                "NeuralNDE rounD",
                "neuralnde",
                neural_data / "inference" / "rounD",
                "rounD 环岛推理地图、行为网络与安全映射模型。",
            ),
        ]
        import_root = self.output_root / "datasets" / "natural" / "imports"
        if import_root.is_dir():
            for path in sorted(item for item in import_root.iterdir() if item.is_dir()):
                records.append(
                    self._dataset_directory_record(
                        f"natural-import-{path.name}",
                        path.name,
                        "imported",
                        path,
                        "用户按目录导入的自然驾驶数据。",
                        read_only=False,
                    )
                )
        return records

    @staticmethod
    def _marker_scope(value: object) -> str:
        scope = str(value or "").strip()
        if not scope or len(scope) > 256:
            return ""
        return scope

    def list_replay_markers(self, marker_scope: str) -> dict[str, Any]:
        scope = self._marker_scope(marker_scope)
        if not scope:
            return {"ok": False, "error": "A valid marker scope is required"}
        return {"ok": True, "scope": scope, "markers": self.experiment_store.list_markers(scope)}

    def handle_replay_marker_action(self, payload: dict) -> dict[str, Any]:
        action = str(payload.get("type") or "").strip().lower()
        scope = self._marker_scope(payload.get("scope"))
        if not scope:
            return {"ok": False, "error": "A valid marker scope is required"}
        if action == "upsert":
            marker = payload.get("marker") if isinstance(payload.get("marker"), dict) else {}
            try:
                saved = self.experiment_store.upsert_marker(scope, marker)
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "marker": saved, "markers": self.experiment_store.list_markers(scope)}
        if action == "delete":
            deleted = self.experiment_store.delete_marker(scope, str(payload.get("marker_id") or ""))
            return {
                "ok": True,
                "deleted": deleted,
                "markers": self.experiment_store.list_markers(scope),
            }
        return {"ok": False, "error": f"Unsupported marker action: {action}"}

    def list_accident_records(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._accident_sync_lock:
            if now - self._accident_sync_at < 10.0:
                return self.accident_store.list()
            self._accident_sync_at = now
        for experiment in self.experiment_store.list(limit=100):
            if not experiment.get("save_file"):
                continue
            audit: dict[str, Any] = {}
            world_job = self.experiment_store.world_job(str(experiment.get("id") or ""))
            payload = world_job.get("payload") if isinstance(world_job.get("payload"), dict) else {}
            if isinstance(payload.get("traffic_safety_audit"), dict):
                audit = payload["traffic_safety_audit"]
            if not audit:
                for artifact in self.experiment_store.list_artifacts(str(experiment.get("id") or "")):
                    if str(artifact.get("kind") or "") != "traffic_safety_audit":
                        continue
                    path = (self.root / str(artifact.get("path") or "")).resolve()
                    if not _is_relative_to(path, self.root):
                        continue
                    try:
                        value = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, TypeError, ValueError):
                        continue
                    if isinstance(value, dict):
                        audit = value
                        break
            if audit:
                self.accident_store.sync_audit(experiment, audit)
        return self.accident_store.list()

    def data_catalog_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "natural_datasets": self.natural_dataset_records(),
            "standard_scenarios": self.list_standard_scenario_records(),
            "accidents": self.list_accident_records(),
            "maps": {
                "citynde": self.list_maps("cnde"),
                "neuralnde": self.list_maps("neuralnde"),
            },
            "regulations": [
                "signal_compliance",
                "pedestrian_priority",
                "safe_following_distance",
                "lane_boundary_and_direction",
            ],
        }

    def _citynde_scenario_metadata(self, path: Path, mtime: float | None = None) -> dict:
        metadata_path = path.with_suffix(path.suffix + ".meta.json")
        cache_key = str(metadata_path.resolve())
        try:
            stat_mtime = float(metadata_path.stat().st_mtime)
        except OSError:
            return {}
        cached = self._citynde_metadata_cache.get(cache_key)
        if cached and cached[0] == stat_mtime:
            return dict(cached[1])
        metadata: dict[str, object] = {}
        try:
            params = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(params, dict):
                map_path = str(params.get("map_path") or "")
                if map_path:
                    metadata["map_path"] = map_path
                if params.get("arrival_rate") is not None:
                    metadata["arrival_rate"] = params.get("arrival_rate")
                if params.get("experiment_name"):
                    metadata["experiment_name"] = str(params.get("experiment_name"))
                if params.get("total_step") is not None:
                    metadata["total_step"] = params.get("total_step")
                if params.get("sim_resolution") is not None:
                    metadata["sim_resolution"] = params.get("sim_resolution")
                if params.get("max_sim_time") is not None:
                    metadata["max_sim_time"] = params.get("max_sim_time")
                if params.get("recording_operational_start_step") is not None:
                    metadata["recording_operational_start_step"] = params.get(
                        "recording_operational_start_step"
                    )
                for key in (
                    "kind",
                    "accident_id",
                    "accident_name",
                    "library_id",
                    "library_name",
                    "library_description",
                    "library_category",
                    "source_path",
                    "seed_image",
                    "seed_source",
                    "seed_source_experiment_id",
                    "seed_ego_id",
                    "seed_sha256",
                    "seed_init_file",
                    "seed_init_sha256",
                    "seed_state_sha256",
                    "seed_failure_reason",
                    "seed_acquired_at",
                    "vehicle_size_mode",
                    "initial_speed_mode",
                    "backend_model",
                    "dataset",
                    "traffic_controller",
                    "source_format",
                    "seed_alignment",
                    "default_world_prompt",
                    "default_transfer_prompt",
                    "default_transfer_negative_prompt",
                    "init_mode",
                    "init_file",
                ):
                    if params.get(key) not in {None, ""}:
                        metadata[key] = str(params.get(key))
                for key in (
                    "library_tags",
                    "participants",
                    "lane_arrival_rates",
                    "rule_control",
                ):
                    if params.get(key) is not None:
                        metadata[key] = params.get(key)
                for key in (
                    "mixed_traffic_enabled",
                    "use_existing_seed",
                    "signalize_unsignalized_map",
                    "standard_backend_locked",
                    "allow_recorded_runtime_seed",
                    "world_loop_ego",
                    "world_omnidreams_actor_allow_overlap",
                ):
                    if params.get(key) is not None:
                        metadata[key] = bool(params.get(key))
                for key in (
                    "cyclist_ratio",
                    "pedestrians_per_crosswalk",
                    "seed_source_time_seconds",
                    "seed_source_frame",
                    "seed_source_fps",
                    "seed_warmup_seconds",
                    "seed_width",
                    "seed_height",
                    "max_pedestrians",
                    "seed_source_state_step",
                    "seed_scenario_state_step",
                    "seed_initialization_state_step",
                    "seed_initialization_history_frames",
                    "source_start_seconds",
                    "source_end_seconds",
                    "initialization_seed",
                    "native_traffic_fps",
                    "world_omnidreams_actor_hood_occlusion_distance_m",
                    "world_omnidreams_actor_hood_occlusion_lateral_m",
                    "world_omnidreams_actor_oncoming_lateral_exclusion_m",
                    "world_omnidreams_actor_max_count",
                    "world_local_target_count",
                    "world_initial_vehicle_limit",
                    "world_ego_speed_cap_mps",
                    "world_omnidreams_seed",
                    "world_seed_map_radius_m",
                    "world_map_radius_m",
                ):
                    if params.get(key) is not None:
                        metadata[key] = params.get(key)
        except Exception:
            metadata = {}
        self._citynde_metadata_cache[cache_key] = (stat_mtime, dict(metadata))
        return metadata


    def _record_target(self, rel_path: str) -> tuple[Path | None, dict | None, str]:
        target, error = self._scenario_target(rel_path)
        if error is None and target is not None:
            return target, None, "citynde"
        return None, error or {"ok": False, "error": "Record path is outside the CityNDE scenario root"}, ""

    def read_scenario_record(self, rel_path: str) -> dict:
        target, error, model = self._record_target(rel_path)
        if error is not None:
            return error
        if target is None:
            return {"ok": False, "error": "Data record not found"}
        if not target.is_file():
            return {"ok": False, "error": "Scenario file not found"}
        return {"ok": True, "data": target.read_bytes(), "filename": target.name, "content_type": "application/octet-stream"}

    def _zip_directory(self, target: Path) -> dict:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(target.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=str(Path(target.name) / path.relative_to(target)).replace("\\", "/"))
        return {"filename": f"{target.name}.zip", "data": buf.getvalue()}

    @staticmethod
    def _safe_record_name(name: str) -> str:
        base = Path(str(name or "")).name
        if base.lower().endswith(".pkl"):
            base = base[:-4]
        safe = []
        for ch in base:
            if ch.isalnum() or ch in ("_", "-", "."):
                safe.append(ch)
            elif ch.isspace():
                safe.append("_")
        out = "".join(safe).strip("._-")
        return (out or f"scenario_{int(time.time())}")[:96] + ".pkl"

    def upload_scenario_records(self, files: list[tuple[str, bytes]]) -> dict:
        if not files:
            return {"ok": False, "error": "No files uploaded"}
        upload_dir = self.scenario_root / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        for filename, data in files:
            if Path(filename).suffix.lower() != ".pkl":
                continue
            target = upload_dir / self._safe_record_name(filename)
            if target.exists():
                target = upload_dir / f"{target.stem}_{int(time.time())}.pkl"
            target.write_bytes(data)
            saved.append(self._citynde_rel(target))
        if not saved:
            return {"ok": False, "error": "No .pkl files were saved"}
        return {"ok": True, "saved": saved, "records": self.list_scenario_records()}

    def import_standard_scenario_records(
        self,
        files: list[tuple[str, bytes]],
        *,
        category: str = "normal",
        map_path: str = "",
    ) -> dict[str, Any]:
        if not files:
            return {"ok": False, "error": "No files uploaded"}
        if len(files) > 100:
            return {"ok": False, "error": "A standard scenario batch is limited to 100 files"}
        category = str(category or "normal").strip().lower()
        if category not in {"normal", "pedestrian", "cyclist"}:
            return {"ok": False, "error": "Unsupported standard scenario category"}
        requested_map = str(map_path or "").strip()
        if requested_map and requested_map not in self.list_maps("cnde"):
            return {"ok": False, "error": "Selected CityNDE map is not available"}
        temporary_root = self.runtime_root / "standard_imports"
        temporary_root.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for filename, data in files:
            if Path(filename).suffix.lower() != ".pkl":
                errors.append({"file": Path(filename).name, "error": "not a .pkl recording"})
                continue
            temp_path = temporary_root / f"{uuid.uuid4().hex}.pkl"
            try:
                temp_path.write_bytes(data)
                with temp_path.open("rb") as stream:
                    recording = pickle.load(stream)
                if not isinstance(recording, dict):
                    raise ValueError("recording root must be a dictionary")
                vehicle_steps = recording.get("vehicle_id_per_step")
                if vehicle_steps is None or not hasattr(vehicle_steps, "__len__") or len(vehicle_steps) < 2:
                    raise ValueError("recording requires at least two traffic frames")
                simulator = recording.get("simulator_meta_info") or {}
                resolution = float(
                    simulator.get("resolution")
                    or simulator.get("sim_resolution")
                    or 0.1
                )
                if not math.isfinite(resolution) or resolution <= 0.0:
                    raise ValueError("recording resolution is invalid")
                bound_map = str(
                    requested_map
                    or recording.get("map_path")
                    or simulator.get("map_path")
                    or ""
                ).strip()
                if not bound_map:
                    raise ValueError("a CityNDE map must be selected for imported recordings")
                if bound_map not in self.list_maps("cnde"):
                    raise ValueError("recording map is not available in the CityNDE map catalog")
                duration = (len(vehicle_steps) - 1) * resolution
                result = create_standard_scenario(
                    temp_path,
                    self.scenario_root / "library",
                    name=Path(filename).stem,
                    category=category,
                    description="批量导入的完整标准场景。",
                    start_seconds=0.0,
                    end_seconds=duration,
                    source_reference=f"import://{Path(filename).name}",
                    source_metadata={"map_path": bound_map},
                    max_duration_seconds=max(100.0, duration),
                )
                saved.append(
                    {
                        "library_id": result["library_id"],
                        "path": self._citynde_rel(result["path"]),
                    }
                )
            except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
                errors.append({"file": Path(filename).name, "error": str(exc)})
            finally:
                temp_path.unlink(missing_ok=True)
        if not saved:
            return {"ok": False, "error": "No standard scenarios were imported", "errors": errors}
        return {
            "ok": True,
            "saved": saved,
            "errors": errors,
            "records": self.list_standard_scenario_records(),
        }

    def _natural_dataset_target(
        self,
        dataset_id: str,
        relative_path: str = "",
        *,
        writable: bool = False,
    ) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any] | None]:
        record = next(
            (item for item in self.natural_dataset_records() if item.get("id") == dataset_id),
            None,
        )
        if record is None:
            return None, None, {"ok": False, "error": "Natural dataset not found"}
        if writable and bool(record.get("read_only", True)):
            return record, None, {"ok": False, "error": "The selected natural dataset is read-only"}
        root = Path(str(record.get("path") or "")).resolve()
        if not root.is_dir():
            return record, None, {"ok": False, "error": "Natural dataset directory is unavailable"}
        normalized = str(relative_path or "").replace("\\", "/").strip("/")
        parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
        if any(part == ".." for part in parts):
            return record, None, {"ok": False, "error": "Natural dataset path is invalid"}
        target = root.joinpath(*parts).resolve()
        if not _is_relative_to(target, root):
            return record, None, {"ok": False, "error": "Natural dataset path is outside its root"}
        return record, target, None

    def natural_dataset_tree(self, dataset_id: str, relative_path: str = "") -> dict[str, Any]:
        record, target, error = self._natural_dataset_target(dataset_id, relative_path)
        if error is not None:
            return error
        if target is None or not target.is_dir():
            return {"ok": False, "error": "Natural dataset level is not a directory"}
        root = Path(str(record.get("path") or "")).resolve()
        entries = []
        for path in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": path.name,
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "kind": "directory" if path.is_dir() else "file",
                    "size": int(stat.st_size) if path.is_file() else None,
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                }
            )
        current_path = str(target.relative_to(root)).replace("\\", "/")
        return {
            "ok": True,
            "dataset": {key: value for key, value in record.items() if key != "path"},
            "path": "" if current_path == "." else current_path,
            "entries": entries,
            "writable": not bool(record.get("read_only", True)),
        }

    def upload_natural_dataset(
        self,
        files: list[tuple[str, bytes]],
        *,
        dataset_id: str = "",
        target_path: str = "",
    ) -> dict:
        if not files:
            return {"ok": False, "error": "No directory files uploaded"}
        if len(files) > 10000:
            return {"ok": False, "error": "A directory upload is limited to 10000 files"}
        total_size = sum(len(data) for _name, data in files)
        if total_size > 512 * 1024 * 1024:
            return {"ok": False, "error": "A directory upload is limited to 512 MiB"}
        if dataset_id:
            record, target_root, error = self._natural_dataset_target(
                dataset_id, target_path, writable=True
            )
            if error is not None:
                return error
            if target_root is None:
                return {"ok": False, "error": "Natural dataset target is unavailable"}
            target_root.mkdir(parents=True, exist_ok=True)
            dataset_name = str(record.get("name") or dataset_id)
        else:
            import_root = self.output_root / "datasets" / "natural" / "imports"
            dataset_name = f"dataset_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            target_root = import_root / dataset_name
        saved = 0
        for filename, data in files:
            normalized = str(filename or "").replace("\\", "/")
            if not normalized or normalized.startswith("/"):
                continue
            parts = [part for part in PurePosixPath(normalized).parts if part not in {"", "."}]
            if not parts or any(part == ".." for part in parts):
                continue
            target = target_root.joinpath(*parts).resolve()
            if not _is_relative_to(target, target_root.resolve()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            saved += 1
        if saved == 0:
            if not dataset_id:
                shutil.rmtree(target_root, ignore_errors=True)
            return {"ok": False, "error": "No safe files were saved"}
        dataset_root = (
            Path(str(record.get("path") or ""))
            if dataset_id
            else target_root
        )
        record = self._dataset_directory_record(
            dataset_id or f"natural-import-{dataset_name}",
            dataset_name,
            "imported",
            dataset_root,
            "用户按目录导入的自然驾驶数据。",
            read_only=False,
        )
        return {"ok": True, "record": record, "saved_files": saved}

    def download_natural_dataset(self, dataset_id: str, relative_path: str = "") -> dict:
        _record, target, error = self._natural_dataset_target(dataset_id, relative_path)
        if error is not None:
            return error
        if target is None or not target.exists():
            return {"ok": False, "error": "Natural dataset path is unavailable"}
        if target.is_dir():
            result = self._zip_directory(target)
            return {"ok": True, "content_type": "application/zip", **result}
        return {
            "ok": True,
            "filename": target.name,
            "data": target.read_bytes(),
            "content_type": mimetypes.guess_type(str(target))[0] or "application/octet-stream",
        }

    def zip_scenario_records(self, paths: list) -> dict:
        if not isinstance(paths, list) or not paths:
            return {"ok": False, "error": "paths is required"}
        buf = io.BytesIO()
        added = 0
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel in paths:
                target, error, model = self._record_target(str(rel))
                if error is not None or target is None:
                    continue
                if target.is_file():
                    zf.write(target, arcname=target.name)
                else:
                    continue
                for sidecar in (
                    target.with_suffix(target.suffix + ".meta.json"),
                    target.with_suffix(".manifest.json"),
                    target.with_suffix(".seed.png"),
                    target.with_suffix(".init.pkl"),
                ):
                    if sidecar.is_file():
                        zf.write(sidecar, arcname=sidecar.name)
                added += 1
        if added == 0:
            return {"ok": False, "error": "No valid scenario files selected"}
        return {"ok": True, "filename": f"citynde_scenarios_{time.strftime('%Y%m%d_%H%M%S')}.zip", "data": buf.getvalue()}

    def handle_data_action(self, payload: dict) -> dict:
        act_type = str(payload.get("type", "")).strip().lower()
        if act_type == "set_experiment_retention":
            experiment_id = str(payload.get("experiment_id") or "").strip()
            if not experiment_id:
                return {"ok": False, "error": "experiment_id is required"}
            keep = bool(payload.get("save_test_result"))
            with self._lock:
                info = self._experiments.get(experiment_id)
                if info is not None:
                    info["save_test_result"] = keep
                    record = self.snapshot(experiment_id, info)
                else:
                    record = self.experiment_store.get(experiment_id)
            if record is None:
                return {"ok": False, "error": "Experiment not found"}
            record["save_test_result"] = keep
            self.experiment_store.upsert(record)
            return {
                "ok": True,
                "experiment_id": experiment_id,
                "save_test_result": keep,
            }
        if act_type == "generate_standard_scenario":
            return self._generate_standard_scenario(payload)
        if act_type == "refresh_standard_scenario_seed":
            return self._refresh_standard_scenario_seed(payload)
        if act_type == "save_accident":
            return self._save_accident_record(payload)
        if act_type == "ignore_accident":
            accident_id = str(payload.get("accident_id") or "").strip()
            updated = self.accident_store.update(accident_id, status="ignored")
            return (
                {"ok": True, "accident": updated, "message": "Accident candidate ignored"}
                if updated
                else {"ok": False, "error": "Accident candidate not found"}
            )
        if act_type == "delete_scenario":
            return self._delete_scenario_record(str(payload.get("path", "")).strip())
        if act_type == "delete_scenarios":
            deleted = []
            errors = []
            for rel in payload.get("paths", []):
                result = self._delete_scenario_record(str(rel))
                if result.get("ok"):
                    deleted.append(str(rel))
                else:
                    errors.append({"path": str(rel), "error": result.get("error", "")})
            return {"ok": bool(deleted), "deleted": deleted, "errors": errors}
        if act_type == "rename_scenario":
            return self._rename_scenario_record(str(payload.get("path", "")).strip(), str(payload.get("new_name", "")).strip())
        return {"ok": False, "error": f"Unknown data action: {act_type}"}

    def _generate_standard_scenario(self, payload: dict) -> dict:
        source_reference = str(payload.get("source_path") or "").strip()
        source, error = self._scenario_target(source_reference)
        if error is not None:
            return error
        if source is None or not source.is_file():
            return {"ok": False, "error": "Source scenario file not found"}
        try:
            result = create_standard_scenario(
                source,
                self.scenario_root / "library",
                name=str(payload.get("name") or ""),
                category=str(payload.get("category") or ""),
                description=str(payload.get("description") or ""),
                start_seconds=float(payload.get("start_seconds") or 0.0),
                end_seconds=float(payload.get("end_seconds") or 0.0),
                source_reference=self._citynde_rel(source),
                source_metadata=self._citynde_scenario_metadata(source),
            )
            try:
                seed_result = self._attach_scenario_seed(
                    result,
                    source,
                    source_start_seconds=float(payload.get("start_seconds") or 0.0),
                )
            except Exception as seed_exc:
                seed_result = {"available": False, "reason": str(seed_exc)}
        except (OSError, ValueError, TypeError, pickle.UnpicklingError) as exc:
            return {"ok": False, "error": str(exc)}
        records = self.list_standard_scenario_records()
        record = next(
            (item for item in records if item.get("library_id") == result["library_id"]),
            None,
        )
        return {
            "ok": True,
            "record": record,
            "message": "Standard scenario generated",
            "seed": seed_result,
        }

    def _refresh_standard_scenario_seed(self, payload: dict) -> dict:
        scenario_reference = str(payload.get("path") or "").strip()
        target, error = self._scenario_target(scenario_reference)
        if error is not None:
            return error
        library_root = (self.scenario_root / "library").resolve()
        if (
            target is None
            or not target.is_file()
            or not _is_relative_to(target, library_root)
        ):
            return {"ok": False, "error": "A managed standard scenario is required"}
        metadata_path = target.with_suffix(target.suffix + ".meta.json")
        metadata = self._citynde_scenario_metadata(target)
        if not metadata.get("library_id") or not metadata_path.is_file():
            return {"ok": False, "error": "Standard scenario metadata is unavailable"}
        current = inspect_scenario_seed_bundle(target, metadata, self.root)
        if current.get("available"):
            return {
                "ok": True,
                "seed": current,
                "record": next(
                    (
                        item
                        for item in self.list_standard_scenario_records()
                        if item.get("path") == self._citynde_rel(target)
                    ),
                    None,
                ),
                "message": "The matched scenario first frame is already ready",
            }

        source_reference = str(metadata.get("source_path") or "").strip()
        if not source_reference:
            return {
                "ok": True,
                "seed": current,
                "message": "No source recording is recorded for first-frame acquisition",
            }
        source = Path(source_reference).expanduser()
        if not source.is_absolute():
            source = self.root / source
        source = source.resolve()
        if (
            not _is_relative_to(source, self.root)
            or source.suffix.lower() != ".pkl"
            or source.name.endswith(".init.pkl")
            or not source.is_file()
        ):
            return {
                "ok": True,
                "seed": {
                    **current,
                    "reason": "The source recording for this standard scenario is unavailable",
                },
                "message": "The source recording for this standard scenario is unavailable",
            }
        result = {
            "path": target,
            "metadata_path": metadata_path,
            "metadata": metadata,
        }
        try:
            acquired = self._attach_scenario_seed(
                result,
                source,
                source_start_seconds=float(metadata.get("source_start_seconds", 0.0) or 0.0),
            )
        except Exception as exc:
            acquired = {"available": False, "reason": str(exc)}
        refreshed_metadata = self._citynde_scenario_metadata(target)
        seed_bundle = inspect_scenario_seed_bundle(target, refreshed_metadata, self.root)
        return {
            "ok": True,
            "seed": seed_bundle,
            "acquisition": acquired,
            "record": next(
                (
                    item
                    for item in self.list_standard_scenario_records()
                    if item.get("path") == self._citynde_rel(target)
                ),
                None,
            ),
            "message": (
                "Matched scenario first frame acquired"
                if seed_bundle.get("available")
                else str(acquired.get("reason") or seed_bundle.get("reason") or "No matched first frame was found")
            ),
        }

    def _save_accident_record(self, payload: dict) -> dict:
        accident_id = str(payload.get("accident_id") or "").strip()
        candidate = self.accident_store.get(accident_id)
        if candidate is None:
            return {"ok": False, "error": "Accident candidate not found"}
        if candidate.get("status") == "saved" and candidate.get("saved_path"):
            return {"ok": True, "accident": candidate, "message": "Accident already saved"}
        source_reference = str(candidate.get("source_path") or "")
        source, error = self._scenario_target(source_reference)
        if error is not None:
            return error
        if source is None or not source.is_file():
            return {"ok": False, "error": "Accident source scenario not found"}
        name = str(payload.get("name") or "").strip() or (
            f"AV事故_{candidate.get('experiment_id')}_{float(candidate.get('first_time_seconds') or 0.0):.1f}s"
        )
        try:
            result = create_accident_scenario(
                source,
                self.scenario_root / "accidents",
                accident_id=accident_id,
                name=name,
                start_seconds=float(candidate.get("start_seconds") or 0.0),
                end_seconds=float(candidate.get("end_seconds") or 0.0),
                source_reference=self._citynde_rel(source),
                source_metadata=self._citynde_scenario_metadata(source),
            )
            try:
                seed_result = self._attach_scenario_seed(
                    result,
                    source,
                    source_start_seconds=float(candidate.get("start_seconds") or 0.0),
                )
            except Exception as seed_exc:
                seed_result = {"available": False, "reason": str(seed_exc)}
        except (OSError, ValueError, TypeError, pickle.UnpicklingError) as exc:
            return {"ok": False, "error": str(exc)}
        saved_path = self._citynde_rel(result["path"])
        updated = self.accident_store.update(
            accident_id,
            status="saved",
            name=name,
            saved_path=saved_path,
            saved_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            replayable=True,
        )
        return {
            "ok": True,
            "accident": updated,
            "record": next(
                (item for item in self.list_scenario_records() if item.get("path") == saved_path),
                None,
            ),
            "message": "Accident scenario saved",
            "seed": seed_result,
        }

    def _attach_scenario_seed(
        self,
        result: dict[str, Any],
        source_recording: Path,
        *,
        source_start_seconds: float,
        warmup_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Attach an exact same-recording OmniDreams frame when one is available."""
        target_recording = Path(result["path"]).resolve()
        metadata_path = Path(result["metadata_path"]).resolve()
        metadata = dict(result.get("metadata") or {})
        source_recording = Path(source_recording).resolve()
        source_video: Path | None = None
        source_experiment_id = ""
        seed_ego_id = ""
        source_fps = 0.0
        source_traffic_stream: Path | None = None
        failure_reason = "No same-recording OmniDreams RGB video was available"

        for record in self.experiment_store.list(limit=1000):
            save_file = str(record.get("save_file") or "").strip()
            if not save_file:
                continue
            try:
                if self._resolve_recording_reference(save_file) != source_recording:
                    continue
            except (OSError, ValueError):
                continue
            experiment_id = str(record.get("id") or "")
            qa_path = (
                self.root
                / "output"
                / "cosmos"
                / "experiments"
                / experiment_id
                / "qa"
                / "omnidreams"
                / "video_qa.json"
            )
            try:
                qa_report = json.loads(qa_path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                continue
            if not isinstance(qa_report, dict) or not qa_report.get("passed"):
                continue
            candidates = [
                item
                for item in self.experiment_store.list_artifacts(experiment_id)
                if str(item.get("kind") or "") == "omnidreams_video"
            ]
            for item in reversed(candidates):
                candidate = (self.root / str(item.get("path") or "")).resolve()
                if _is_relative_to(candidate, self.root) and candidate.is_file():
                    source_video = candidate
                    source_experiment_id = experiment_id
                    break
            if source_video is None:
                candidate = (
                    self.root
                    / "output"
                    / "cosmos"
                    / "experiments"
                    / experiment_id
                    / "omnidreams"
                    / "camera_front_wide_120fov.mp4"
                ).resolve()
                if candidate.is_file():
                    source_video = candidate
                    source_experiment_id = experiment_id
            if source_video is not None:
                traffic_stream = (
                    self.root
                    / "output"
                    / "cosmos"
                    / "experiments"
                    / experiment_id
                    / "operational_traffic.ndjson"
                )
                if traffic_stream.is_file():
                    source_traffic_stream = traffic_stream
                break

        seed_target = target_recording.with_suffix(".seed.png")
        seed_init_target = target_recording.with_suffix(".init.pkl")
        seed_source = ""
        seed_time = 0.0
        seed_source_state_step = -1
        if source_video is not None:
            media = probe_video(source_video)
            fps = max(1.0, float(media.get("fps", 30.0) or 30.0))
            source_fps = fps
            duration = max(
                0.0,
                float(media.get("duration_seconds", 0.0) or 0.0),
            )
            requested_time = max(0.0, float(source_start_seconds) + float(warmup_seconds))
            seed_time = min(requested_time, max(0.0, duration - 1.0 / fps))
            if duration <= 0.0 or seed_time + 1e-6 < float(source_start_seconds):
                source_video = None
                failure_reason = "The matching OmniDreams video does not cover the requested scenario time"
            else:
                self._extract_video_frame(
                    source_video,
                    seed_target,
                    seed_time,
                    source_fps=max(1, int(round(fps))),
                )
                seed_source = "same_recording_omnidreams"

        if seed_target.is_file() and source_traffic_stream is not None:
            try:
                traffic_frame = self._traffic_stream_at_time(
                    source_traffic_stream,
                    float(source_start_seconds),
                )
                seed_ego_id = str((traffic_frame.get("ego") or {}).get("id") or "")
            except (OSError, TypeError, ValueError):
                seed_ego_id = ""

        if seed_target.is_file() and seed_source == "same_recording_omnidreams":
            temp_initialization = seed_init_target.with_suffix(
                seed_init_target.suffix + ".tmp"
            )
            try:
                with source_recording.open("rb") as stream:
                    source_recording_data = pickle.load(stream)
                source_metadata = self._citynde_scenario_metadata(source_recording)
                simulator = dict(source_recording_data.get("simulator_meta_info") or {})
                source_resolution = float(
                    simulator.get("resolution")
                    or simulator.get("sim_resolution")
                    or source_metadata.get("sim_resolution")
                    or 0.1
                )
                source_operational_offset = int(
                    source_metadata.get("recording_operational_start_step", 0) or 0
                )
                source_state_step = source_operational_offset + int(
                    round(float(source_start_seconds) / source_resolution)
                )
                seed_source_state_step = source_state_step
                initialization = _recording_initialization_history(
                    source_recording_data,
                    end_step=source_state_step,
                    history_steps=11,
                )
                with temp_initialization.open("wb") as stream:
                    pickle.dump(initialization, stream, protocol=pickle.HIGHEST_PROTOCOL)
                    stream.flush()
                    os.fsync(stream.fileno())
                temp_initialization.replace(seed_init_target)
            except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
                temp_initialization.unlink(missing_ok=True)
                seed_target.unlink(missing_ok=True)
                seed_init_target.unlink(missing_ok=True)
                seed_source = ""
                failure_reason = f"Failed to build exact CityNDE seed history: {exc}"

        if (
            (not seed_target.is_file() or not seed_init_target.is_file())
            and float(source_start_seconds) <= 1e-6
        ):
            source_metadata = self._citynde_scenario_metadata(source_recording)
            inherited = str(source_metadata.get("seed_image") or "").strip()
            inherited_init = str(source_metadata.get("seed_init_file") or "").strip()
            seed_ego_id = str(source_metadata.get("seed_ego_id") or "")
            if inherited and inherited_init:
                inherited_path = Path(inherited)
                inherited_init_path = Path(inherited_init)
                if not inherited_path.is_absolute():
                    inherited_path = self.root / inherited_path
                if not inherited_init_path.is_absolute():
                    inherited_init_path = self.root / inherited_init_path
                inherited_path = inherited_path.resolve()
                inherited_init_path = inherited_init_path.resolve()
                if (
                    _is_relative_to(inherited_path, self.root)
                    and _is_relative_to(inherited_init_path, self.root)
                    and inherited_path.is_file()
                    and inherited_init_path.is_file()
                ):
                    shutil.copy2(inherited_path, seed_target)
                    shutil.copy2(inherited_init_path, seed_init_target)
                    seed_source = "inherited_scenario_seed"
                    seed_time = float(source_metadata.get("seed_source_time_seconds", 0.0) or 0.0)
                    source_fps = float(source_metadata.get("seed_source_fps", 30.0) or 30.0)
                    source_experiment_id = str(
                        source_metadata.get("seed_source_experiment_id") or ""
                    )
                    inherited_source_step = source_metadata.get(
                        "seed_source_state_step", -1
                    )
                    seed_source_state_step = int(
                        -1 if inherited_source_step is None else inherited_source_step
                    )

        if seed_target.is_file() and seed_init_target.is_file():
            try:
                with target_recording.open("rb") as stream:
                    scenario_recording = pickle.load(stream)
                with seed_init_target.open("rb") as stream:
                    initialization_recording = pickle.load(stream)
                initial_ids = _recording_first_vehicle_ids(scenario_recording)
                history_ids = _recording_last_vehicle_ids(initialization_recording)
                target_state = _recording_actor_state(
                    scenario_recording, seed_ego_id, step=0
                )
                history_state = _recording_actor_state(
                    initialization_recording, seed_ego_id, step=-1
                )
                target_state_hash = _recording_step_sha256(scenario_recording, step=0)
                history_state_hash = _recording_step_sha256(
                    initialization_recording, step=-1
                )
            except (OSError, TypeError, ValueError, pickle.UnpicklingError):
                initial_ids = set()
                history_ids = set()
                target_state = None
                history_state = None
                target_state_hash = ""
                history_state_hash = ""
            if (
                not seed_ego_id
                or seed_ego_id not in initial_ids
                or seed_ego_id not in history_ids
                or target_state is None
                or history_state is None
                or target_state_hash != history_state_hash
            ):
                seed_target.unlink(missing_ok=True)
                seed_init_target.unlink(missing_ok=True)
                seed_source = ""
                failure_reason = (
                    "The saved RGB seed, CityNDE initialization history, and scenario first frame do not share one exact state"
                )

        if (
            not seed_target.is_file()
            or seed_target.stat().st_size <= 0
            or not seed_init_target.is_file()
            or seed_init_target.stat().st_size <= 0
        ):
            for key in list(metadata):
                if key == "use_existing_seed" or str(key).startswith("seed_"):
                    metadata.pop(key, None)
            metadata.update(
                {
                    "use_existing_seed": False,
                    "seed_image": "",
                    "seed_failure_reason": failure_reason,
                }
            )
            temp_metadata = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
            temp_metadata.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temp_metadata.replace(metadata_path)
            result["metadata"] = metadata
            return {"available": False, "reason": failure_reason}

        seed_media = probe_video(seed_target, count_frames=False)
        for key in list(metadata):
            if key == "use_existing_seed" or str(key).startswith("seed_"):
                metadata.pop(key, None)
        metadata.update(
            {
                "use_existing_seed": True,
                "seed_image": self._repo_rel(seed_target),
                "seed_init_file": self._repo_rel(seed_init_target),
                "seed_source": seed_source,
                "seed_source_experiment_id": source_experiment_id,
                "seed_source_time_seconds": round(seed_time, 6),
                "seed_source_frame": int(round(seed_time * source_fps)),
                "seed_source_fps": round(source_fps, 6),
                "seed_warmup_seconds": float(warmup_seconds),
                "seed_source_state_step": int(seed_source_state_step),
                "seed_scenario_state_step": 0,
                "seed_initialization_state_step": 10,
                "seed_initialization_history_frames": 11,
                "seed_ego_id": seed_ego_id,
                "seed_width": int(seed_media.get("width", 0) or 0),
                "seed_height": int(seed_media.get("height", 0) or 0),
                "seed_sha256": hashlib.sha256(seed_target.read_bytes()).hexdigest(),
                "seed_init_sha256": hashlib.sha256(
                    seed_init_target.read_bytes()
                ).hexdigest(),
                "seed_state_sha256": target_state_hash,
                "seed_acquired_at": _now_text(),
            }
        )
        temp_metadata = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        temp_metadata.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_metadata.replace(metadata_path)
        result["metadata"] = metadata
        return {
            "available": True,
            "path": metadata["seed_image"],
            "initialization_path": metadata["seed_init_file"],
            "source": seed_source,
            "source_experiment_id": source_experiment_id,
            "source_time_seconds": round(seed_time, 6),
        }

    def _delete_scenario_record(self, rel_path: str) -> dict:
        target, error, model = self._record_target(rel_path)
        if error is not None:
            return error
        if target is None:
            return {"ok": False, "error": "Data record not found"}
        if not target.is_file():
            return {"ok": False, "error": "Scenario file not found"}
        target.unlink()
        for sidecar in (
            target.with_suffix(target.suffix + ".meta.json"),
            target.with_suffix(".manifest.json"),
            target.with_suffix(".seed.png"),
            target.with_suffix(".init.pkl"),
        ):
            sidecar.unlink(missing_ok=True)
        return {"ok": True, "path": rel_path, "message": "Scenario deleted"}

    def _rename_scenario_record(self, rel_path: str, new_name: str) -> dict:
        target, error = self._scenario_target(rel_path)
        if error is not None:
            return error
        if target is None or not target.is_file():
            return {"ok": False, "error": "Scenario file not found"}
        new_target = target.with_name(self._safe_record_name(new_name))
        if new_target.exists():
            return {"ok": False, "error": "Target filename already exists"}
        target.rename(new_target)
        sidecars = (
            (target.with_suffix(target.suffix + ".meta.json"), new_target.with_suffix(new_target.suffix + ".meta.json")),
            (target.with_suffix(".manifest.json"), new_target.with_suffix(".manifest.json")),
            (target.with_suffix(".seed.png"), new_target.with_suffix(".seed.png")),
            (target.with_suffix(".init.pkl"), new_target.with_suffix(".init.pkl")),
        )
        for old_sidecar, new_sidecar in sidecars:
            if old_sidecar.is_file():
                old_sidecar.rename(new_sidecar)
        metadata_path = new_target.with_suffix(new_target.suffix + ".meta.json")
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(metadata, dict) and metadata.get("seed_image"):
                    metadata["seed_image"] = self._repo_rel(new_target.with_suffix(".seed.png"))
                    if metadata.get("seed_init_file"):
                        metadata["seed_init_file"] = self._repo_rel(
                            new_target.with_suffix(".init.pkl")
                        )
                    metadata_path.write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            except (OSError, TypeError, ValueError):
                pass
        return {"ok": True, "path": self._citynde_rel(new_target), "old_path": rel_path}

    def _write_manifest(self, model: str, exp_id: str, payload: dict, backend_model: str | None = None):
        meta_dir = self.runtime_root / model / "metadata"
        meta_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "experiment_id": exp_id,
            "backend_model": backend_model or model,
            "storage_model": model,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload,
        }
        (meta_dir / f"{exp_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _with_av_port(payload: dict, child_port: int) -> dict:
        next_payload = dict(payload)
        model = str(next_payload.get("av_control_model") or "").upper()
        if bool(next_payload.get("av_enabled")) and model in {
            "EXTERNAL_TCP", "VTD_TCP", "IDM_MOBIL", "LEAD_TFV6_STREAM"
        }:
            try:
                port = int(next_payload.get("av_control_port") or 0)
            except (TypeError, ValueError):
                port = 0
            if port <= 0:
                next_payload["av_control_port"] = int(child_port) + 1000
        return next_payload

    def _start_builtin_av_client(self, experiment_id: str, payload: dict) -> None:
        model = str(payload.get("av_control_model") or "").upper()
        if not bool(payload.get("av_enabled")) or model not in {"IDM_MOBIL", "LEAD_TFV6_STREAM"}:
            return
        with self._lock:
            info = self._experiments.get(experiment_id)
        if info is None:
            return
        port = int(payload.get("av_control_port") or 0)
        source_root = Path(os.environ.get("AUTONOMOUS_VEHICLES_ROOT", "/mnt/rk/cnde/autonomous_vehicles"))
        log_dir = self.runtime_root / "av" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_suffix = "idm_mobil" if model == "IDM_MOBIL" else "lead_tfv6_stream"
        log_path = log_dir / f"{experiment_id}.{log_suffix}.log"
        log_file = open(log_path, "ab", buffering=0)
        command = [
            sys.executable,
            "-m",
            "backend.av.idm_mobil_client" if model == "IDM_MOBIL" else "backend.av.lead_tfv6_stream_client",
            "--host",
            str(payload.get("av_control_host") or "127.0.0.1"),
            "--port",
            str(port),
            "--source-root",
            str(source_root),
        ]
        if model == "LEAD_TFV6_STREAM":
            command.extend(
                [
                    "--audit-path",
                    str(
                        self.root
                        / "output"
                        / "cosmos"
                        / "experiments"
                        / experiment_id
                        / "av_stream"
                        / "lead_tfv6_live.jsonl"
                    ),
                ]
            )
        elif model == "IDM_MOBIL":
            command.extend(
                [
                    "--desired-speed-mps",
                    str(
                        max(
                            1.0,
                            min(
                                35.0,
                                float(payload.get("av_desired_speed_mps", 19.44) or 19.44),
                            ),
                        )
                    ),
                ]
            )
        process = subprocess.Popen(
            command,
            cwd=str(self.root),
            env=os.environ.copy(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        info.update(
            {
                "av_adapter_process": process,
                "av_adapter_log_file": log_file,
                "av_adapter_log_path": str(log_path),
                "av_adapter_state": "starting",
            }
        )

        def _monitor() -> None:
            main_process = info.get("process")
            info["av_adapter_state"] = "running"
            while process.poll() is None and main_process is not None and main_process.poll() is None:
                time.sleep(0.5)
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
            info["av_adapter_state"] = "completed" if process.returncode == 0 else "stopped"
            try:
                log_file.close()
            except OSError:
                pass

        threading.Thread(target=_monitor, name=f"AVAdapter-{experiment_id}", daemon=True).start()

    def handle_action(self, payload: dict) -> dict:
        act_type = str(payload.get("type", "")).strip().lower()
        if act_type == "start_experiment":
            scenario_count = max(1, min(1000, int(payload.get("scenario_count", 1) or 1)))
            if scenario_count > 1 and _traffic_runs_until_stopped(payload):
                return {
                    "ok": False,
                    "error": "Open-ended experiments support one scenario at a time; stop it manually before starting another.",
                }
            if scenario_count > 1:
                return self.launch_experiment_batch(payload, scenario_count)
            return self._launch_experiment_once(payload)
        if act_type == "start_playback":
            scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
            if (
                str(payload.get("backend_model") or "").strip().lower() in {"neuralnde", "neural_nde"}
                or scenario.lower().endswith(".jsonl")
            ):
                return self.launch_neuralnde_replay(payload)
            return self.launch_citynde_replay(payload)
        if act_type == "start_offline_test":
            payload = {**payload, "offline_test": True}
            scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
            return self.launch_citynde_replay(payload)
        if act_type == "start_offline_preview":
            payload = {**payload, "offline_test": True, "offline_preview": True}
            scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
            return self.launch_citynde_replay(payload)
        if act_type == "start_transfer_replay":
            return self.launch_transfer_replay(payload)
        if act_type == "revalidate_world_output":
            return self.revalidate_world_output(
                str(payload.get("experiment_id") or "").strip()
            )
        if act_type == "pause_experiments":
            return self.pause_experiments([str(x) for x in payload.get("experiment_ids") or payload.get("ids") or []])
        if act_type == "terminate_experiment":
            ids = payload.get("experiment_ids") or payload.get("ids")
            if not ids and payload.get("experiment_id"):
                ids = [payload.get("experiment_id")]
            if not ids:
                ids = list(self._experiments.keys())
            return self.terminate_experiments(
                [str(x) for x in ids],
                save_data=bool(payload.get("save_data", True)),
            )
        if act_type in {"delete_experiment", "delete_experiments"}:
            ids = payload.get("experiment_ids") or payload.get("ids")
            if not ids and payload.get("experiment_id"):
                ids = [payload.get("experiment_id")]
            if not ids:
                return {"ok": False, "error": "experiment_ids required"}
            return self.delete_experiments([str(x) for x in ids])
        if act_type == "refresh_scenarios":
            return {"ok": True, "scenarios": [r["path"] for r in self.list_scenario_records() if r.get("replayable", True)]}
        return {"ok": False, "error": f"Unknown manager action type: {act_type}"}

    def _launch_experiment_once(self, payload: dict) -> dict:
        backend_model = str(payload.get("backend_model") or payload.get("traffic_model") or "cnde").strip().lower()
        if backend_model in {"neuralnde", "neural_nde"}:
            return self.launch_neuralnde(payload)
        if backend_model in {"rulebased", "rule_based", "idm_mobil"}:
            standard_scenario = (
                str(payload.get("init_mode") or "").strip().lower()
                in {"data", "data_random_tl"}
                and bool(str(payload.get("init_file") or "").strip())
            )
            rule_payload = {
                **payload,
                "traffic_controller": "idm_mobil",
                "mixed_traffic_enabled": False,
                "cyclist_ratio": 0.0,
                "pedestrians_per_crosswalk": 0,
                "max_pedestrians": 0,
                "arrival_rate": (
                    0.0 if payload.get("arrival_rate") is None else payload.get("arrival_rate")
                ),
            }
            # Seeded standard scenes carry an exact actor count. Let their
            # metadata set the limits instead of applying the map-init default.
            if not standard_scenario:
                rule_payload["world_local_target_count"] = int(
                    payload.get("world_local_target_count", 8) or 8
                )
                rule_payload["world_initial_vehicle_limit"] = int(
                    payload.get("world_initial_vehicle_limit", 8) or 8
                )
            return self.launch_citynde(
                rule_payload
            )
        if backend_model in {"cnde", "citynde"}:
            return self.launch_citynde(payload)
        return {"ok": False, "error": f"Unsupported traffic model: {backend_model}"}

    def _batch_payload(self, payload: dict, batch_id: str, index: int, count: int) -> dict:
        item = dict(payload)
        base_name = self._safe_name(str(payload.get("experiment_name") or "batch"), fallback="batch")
        base_seed = int(payload.get("seed", 42) or 42)
        item.update(
            {
                "scenario_count": 1,
                "batch_id": batch_id,
                "batch_index": index + 1,
                "batch_count": count,
                "experiment_name": f"{base_name}_{index + 1:03d}",
                "seed": base_seed + index,
            }
        )
        return item

    def _release_batch_process(self, experiment_id: str, terminal_state: str) -> None:
        with self._lock:
            info = self._experiments.get(experiment_id)
        if info is None:
            return
        process = info.get("process")
        final_status = self._http_json(
            f"http://127.0.0.1:{info['port']}/status",
            timeout=1.5,
        )
        if final_status:
            info["last_status"] = final_status
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=8.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=3.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        av_process = info.get("av_adapter_process")
        if av_process is not None and av_process.poll() is None:
            try:
                av_process.terminate()
                av_process.wait(timeout=5.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    av_process.kill()
                    av_process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        info["av_adapter_process"] = None
        av_log_file = info.get("av_adapter_log_file")
        if av_log_file:
            try:
                av_log_file.close()
            except OSError:
                pass
            info["av_adapter_log_file"] = None
        info["process"] = None
        info.pop("return_code", None)
        previous = info.get("last_status") if isinstance(info.get("last_status"), dict) else {}
        info["last_status"] = {
            **previous,
            "run_state": terminal_state,
            "paused": False,
            "progress": 1.0 if terminal_state == "completed" else float(previous.get("progress", 0.0) or 0.0),
            "experiment_completed": terminal_state == "completed",
        }
        log_file = info.get("log_file")
        if log_file:
            try:
                log_file.close()
            except OSError:
                pass
            info["log_file"] = None
        self.experiment_store.upsert(self.snapshot(experiment_id, info))

    def _wait_for_batch_item(self, experiment_id: str, *, world_enabled: bool) -> str:
        while not self._world_stop.wait(1.0):
            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is None:
                return "error"
            snapshot = self.snapshot(experiment_id, info)
            self.experiment_store.upsert(snapshot)
            state = str(snapshot.get("run_state") or "")
            if world_enabled:
                world_state = str(self.experiment_store.world_job(experiment_id).get("run_state") or "")
                if world_state in {"completed", "error"}:
                    terminal = "completed" if world_state == "completed" else "error"
                    self._release_batch_process(experiment_id, terminal)
                    return terminal
            if state in {"completed", "error", "stopped", "interrupted"}:
                self._release_batch_process(experiment_id, state)
                return state
        return "interrupted"

    def launch_experiment_batch(self, payload: dict, scenario_count: int) -> dict:
        backend_model = str(payload.get("backend_model") or payload.get("traffic_model") or "cnde").strip().lower()
        batch_id = f"batch_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        name = self._safe_name(str(payload.get("experiment_name") or "batch"), fallback="batch")
        first_payload = self._batch_payload(payload, batch_id, 0, scenario_count)
        first = self._launch_experiment_once(first_payload)
        if not first.get("ok"):
            return first
        first_id = str((first.get("experiment") or {}).get("id") or "")
        experiment_ids = [first_id]
        self.experiment_store.upsert_batch(
            batch_id,
            backend_model=backend_model,
            name=name,
            run_state="running",
            scenario_count=scenario_count,
            current_index=1,
            experiment_ids=experiment_ids,
            payload=payload,
        )

        def _worker() -> None:
            completed = 0
            failed = 0
            current_id = first_id
            final_state = "completed"
            try:
                for index in range(scenario_count):
                    if index > 0:
                        result = self._launch_experiment_once(
                            self._batch_payload(payload, batch_id, index, scenario_count)
                        )
                        if not result.get("ok"):
                            failed += 1
                            self.experiment_store.upsert_batch(
                                batch_id,
                                backend_model=backend_model,
                                name=name,
                                run_state="running",
                                scenario_count=scenario_count,
                                completed_count=completed,
                                failed_count=failed,
                                current_index=index + 1,
                                experiment_ids=experiment_ids,
                                payload=payload,
                            )
                            continue
                        current_id = str((result.get("experiment") or {}).get("id") or "")
                        experiment_ids.append(current_id)
                    terminal = self._wait_for_batch_item(
                        current_id,
                        world_enabled=bool(payload.get("world_generation_enabled")),
                    )
                    if terminal == "completed":
                        completed += 1
                    elif terminal in {"stopped", "interrupted"}:
                        final_state = "interrupted"
                        break
                    else:
                        failed += 1
                    self.experiment_store.upsert_batch(
                        batch_id,
                        backend_model=backend_model,
                        name=name,
                        run_state="running",
                        scenario_count=scenario_count,
                        completed_count=completed,
                        failed_count=failed,
                        current_index=index + 1,
                        experiment_ids=experiment_ids,
                        payload=payload,
                    )
                if final_state == "completed" and failed:
                    final_state = "completed_with_errors"
            except Exception:
                final_state = "error"
                failed += 1
            finally:
                self.experiment_store.upsert_batch(
                    batch_id,
                    backend_model=backend_model,
                    name=name,
                    run_state=final_state,
                    scenario_count=scenario_count,
                    completed_count=completed,
                    failed_count=failed,
                    current_index=min(scenario_count, completed + failed),
                    experiment_ids=experiment_ids,
                    payload=payload,
                )
                self._batch_threads.pop(batch_id, None)

        thread = threading.Thread(target=_worker, name=f"SimulationBatch-{batch_id}", daemon=True)
        self._batch_threads[batch_id] = thread
        thread.start()
        return {
            **first,
            "batch": {
                "id": batch_id,
                "run_state": "running",
                "scenario_count": scenario_count,
                "current_index": 1,
                "experiment_ids": experiment_ids,
            },
        }

    def launch_citynde(self, payload: dict) -> dict:
        payload = dict(payload)
        traffic_controller = str(
            payload.get("traffic_controller") or "citynde"
        ).strip().lower()
        rulebased = traffic_controller == "idm_mobil"
        backend_model = "rulebased" if rulebased else "cnde"
        workflow_id = str(payload.get("workflow_id") or "").strip()
        workflow = next(
            (
                item
                for item in self.list_workflows()
                if str(item.get("id") or "") == workflow_id
            ),
            None,
        )
        if workflow and str(workflow.get("scenario_mode") or "library") == "map":
            map_init_mode = str(workflow.get("map_init_mode") or "random_tl_only")
            if payload.get("world_generation_enabled") and map_init_mode == "random_tl_only":
                map_init_mode = "random"
            payload["init_mode"] = map_init_mode
            payload["init_file"] = ""
            payload["world_use_existing_seed"] = False
            payload["world_seed_image"] = ""
            if (
                str(payload.get("av_selection_mode") or "random") == "manual"
                and not str(payload.get("av_id") or "").strip()
            ):
                payload["av_selection_mode"] = "random"
        requested_existing_seed = bool(payload.get("world_use_existing_seed"))
        requested_seed_path = str(payload.get("world_seed_image") or "").strip()
        init_mode_value = str(payload.get("init_mode") or "random_tl_only").strip()
        init_file_value = str(payload.get("init_file") or "").strip()
        scenario_target: Path | None = None
        scenario_metadata: dict[str, Any] = {}
        if init_mode_value in {"data", "data_random_tl"}:
            if not init_file_value:
                return {
                    "ok": False,
                    "error": "CityNDE data initialization requires an initialization scenario",
                }
            scenario_target, scenario_error = self._scenario_target(init_file_value)
            if scenario_error is not None:
                return scenario_error
            if scenario_target is None or not scenario_target.is_file():
                return {"ok": False, "error": "Initialization scenario file was not found"}
            scenario_metadata = self._citynde_scenario_metadata(scenario_target)
            if (
                not str(payload.get("world_prompt") or "").strip()
                and scenario_metadata.get("default_world_prompt")
            ):
                payload["world_prompt"] = str(
                    scenario_metadata["default_world_prompt"]
                ).strip()
            if (
                not str(payload.get("world_transfer_prompt") or "").strip()
                and scenario_metadata.get("default_transfer_prompt")
            ):
                payload["world_transfer_prompt"] = str(
                    scenario_metadata["default_transfer_prompt"]
                ).strip()
            if (
                not str(payload.get("world_transfer_negative_prompt") or "").strip()
                and scenario_metadata.get("default_transfer_negative_prompt")
            ):
                payload["world_transfer_negative_prompt"] = str(
                    scenario_metadata["default_transfer_negative_prompt"]
                ).strip()
            locked_backend = str(
                scenario_metadata.get("backend_model") or "cnde"
            ).strip().lower()
            if (
                scenario_metadata.get("standard_backend_locked")
                and str(payload.get("scenario_execution_mode") or "continue").strip().lower()
                != "replay"
                and locked_backend != backend_model
            ):
                return {
                    "ok": False,
                    "error": (
                        f"The selected standard scenario is bound to {locked_backend}, "
                        f"not {backend_model}"
                    ),
                }
            scenario_map_path = str(scenario_metadata.get("map_path") or "").strip()
            if scenario_metadata.get("library_id") and not scenario_map_path:
                return {
                    "ok": False,
                    "error": "The selected standard scenario has no bound map metadata",
                }
            if scenario_map_path:
                map_reference = Path(scenario_map_path)
                if not map_reference.is_absolute():
                    normalized_map = scenario_map_path.replace("\\", "/")
                    map_reference = (
                        self.root / map_reference
                        if normalized_map.startswith(("algorithm_sources/", "output/"))
                        else self.citynde_root / map_reference
                    )
                map_target = map_reference.resolve()
                if (
                    not _is_relative_to(map_target, self.citynde_root.resolve())
                    or not map_target.is_file()
                ):
                    return {
                        "ok": False,
                        "error": "The map bound to the selected scenario is unavailable",
                    }
                payload["map_path"] = scenario_map_path
                payload["scenario_configuration_locked"] = True
            if payload.get("arrival_rate") is None and scenario_metadata.get("arrival_rate") is not None:
                payload["arrival_rate"] = scenario_metadata["arrival_rate"]
            if not payload.get("arrival_rates") and isinstance(scenario_metadata.get("lane_arrival_rates"), dict):
                payload["arrival_rates"] = dict(scenario_metadata["lane_arrival_rates"])
            for key in (
                "mixed_traffic_enabled",
                "cyclist_ratio",
                "pedestrians_per_crosswalk",
                "max_pedestrians",
                "vehicle_size_mode",
                "initial_speed_mode",
                "signalize_unsignalized_map",
                "world_omnidreams_actor_allow_overlap",
                "world_omnidreams_actor_hood_occlusion_distance_m",
                "world_omnidreams_actor_hood_occlusion_lateral_m",
                "world_omnidreams_actor_oncoming_lateral_exclusion_m",
                "world_omnidreams_actor_max_count",
                "world_local_target_count",
                "world_initial_vehicle_limit",
                "world_ego_speed_cap_mps",
                "world_omnidreams_seed",
                "world_seed_map_radius_m",
                "world_map_radius_m",
            ):
                if payload.get(key) is None and scenario_metadata.get(key) is not None:
                    payload[key] = scenario_metadata[key]
            if not str(payload.get("world_seed_ego_id") or "").strip():
                scenario_ego_id = str(
                    scenario_metadata.get("seed_ego_id") or ""
                ).strip()
                if scenario_ego_id:
                    payload["world_seed_ego_id"] = scenario_ego_id
            rule_control = scenario_metadata.get("rule_control") or {}
            if (
                rulebased
                and payload.get("rule_desired_speed_mps") is None
                and rule_control.get("bv_desired_speed_mps") is not None
            ):
                payload["rule_desired_speed_mps"] = rule_control["bv_desired_speed_mps"]

            # A standard scenario recording is optimized for catalog preview and
            # can contain fewer than CityNDE's required 11 history states.  In
            # continuation mode, initialize from the bound history bundle while
            # retaining scenario_target for provenance, seed validation, and
            # replay mode.
            if (
                scenario_metadata.get("library_id")
                and str(payload.get("scenario_execution_mode") or "continue")
                .strip()
                .lower()
                != "replay"
            ):
                continuation_reference = str(
                    scenario_metadata.get("init_file")
                    or scenario_metadata.get("seed_init_file")
                    or ""
                ).strip()
                if continuation_reference:
                    continuation_target = Path(continuation_reference)
                    if not continuation_target.is_absolute():
                        continuation_target = self.root / continuation_target
                    continuation_target = continuation_target.resolve()
                    if (
                        not _is_relative_to(
                            continuation_target, self.scenario_root.resolve()
                        )
                        or not continuation_target.is_file()
                    ):
                        return {
                            "ok": False,
                            "error": (
                                "The selected standard scenario continuation "
                                "initialization is unavailable"
                            ),
                        }
                    init_file_value = self._repo_rel(continuation_target)
                    payload["init_file"] = init_file_value
        init_mode_value = _citynde_seed_init_mode(
            init_mode_value,
            requested_existing_seed=requested_existing_seed,
            scenario_metadata=scenario_metadata,
        )
        payload["init_mode"] = init_mode_value
        if requested_existing_seed:
            if init_mode_value != "data" or not init_file_value:
                return {
                    "ok": False,
                    "error": "Existing scenario seeds require exact CityNDE data initialization; data_random_tl would replace the saved signal state",
                }
            if scenario_target is None:
                return {"ok": False, "error": "Seed scenario file was not found"}
            if not _is_relative_to(scenario_target, self.scenario_root.resolve()):
                return {
                    "ok": False,
                    "error": "Reusable seeds are limited to the managed CityNDE scenario library",
                }
            seed_reference = str(scenario_metadata.get("seed_image") or "").strip()
            seed_init_reference = str(
                scenario_metadata.get("seed_init_file") or ""
            ).strip()
            if (
                not scenario_metadata.get("use_existing_seed")
                or not seed_reference
                or not seed_init_reference
            ):
                return {
                    "ok": False,
                    "error": "The selected scenario has no complete reusable RGB and CityNDE state seed",
                }
            seed_ego_id = str(scenario_metadata.get("seed_ego_id") or "").strip()
            if not seed_ego_id:
                return {"ok": False, "error": "The selected scenario seed has no camera ego provenance"}

            seed_target = Path(seed_reference)
            if not seed_target.is_absolute():
                seed_target = self.root / seed_target
            seed_target = seed_target.resolve()
            seed_init_target = Path(seed_init_reference)
            if not seed_init_target.is_absolute():
                seed_init_target = self.root / seed_init_target
            seed_init_target = seed_init_target.resolve()
            expected_seed_target = scenario_target.with_suffix(".seed.png").resolve()
            expected_seed_init_target = scenario_target.with_suffix(".init.pkl").resolve()
            if (
                seed_target != expected_seed_target
                or seed_init_target != expected_seed_init_target
                or not seed_target.is_file()
                or not seed_init_target.is_file()
            ):
                return {
                    "ok": False,
                    "error": "The selected scenario seed bundle is incomplete or not adjacent to its recording",
                }
            if requested_seed_path:
                requested_target = Path(requested_seed_path)
                if not requested_target.is_absolute():
                    requested_target = self.root / requested_target
                if requested_target.resolve() != seed_target:
                    return {
                        "ok": False,
                        "error": "The requested RGB seed does not belong to the selected scenario",
                    }

            expected_seed_hash = str(
                scenario_metadata.get("seed_sha256") or ""
            ).strip().lower()
            expected_init_hash = str(
                scenario_metadata.get("seed_init_sha256") or ""
            ).strip().lower()
            expected_state_hash = str(
                scenario_metadata.get("seed_state_sha256") or ""
            ).strip().lower()
            if not expected_seed_hash or not expected_init_hash or not expected_state_hash:
                return {
                    "ok": False,
                    "error": "The selected scenario seed bundle predates exact state validation and must be regenerated",
                }
            actual_seed_hash = hashlib.sha256(seed_target.read_bytes()).hexdigest()
            actual_init_hash = hashlib.sha256(seed_init_target.read_bytes()).hexdigest()
            if not hmac.compare_digest(expected_seed_hash, actual_seed_hash):
                return {
                    "ok": False,
                    "error": "The selected scenario RGB seed checksum does not match its metadata",
                }
            if not hmac.compare_digest(expected_init_hash, actual_init_hash):
                return {
                    "ok": False,
                    "error": "The selected scenario initialization checksum does not match its metadata",
                }
            try:
                with scenario_target.open("rb") as stream:
                    scenario_recording = pickle.load(stream)
                with seed_init_target.open("rb") as stream:
                    initialization_recording = pickle.load(stream)
                initial_ids = _recording_first_vehicle_ids(scenario_recording)
                initialization_ids = _recording_last_vehicle_ids(
                    initialization_recording
                )
                initialization_timeline = initialization_recording.get(
                    "vehicle_id_per_step"
                )
                initialization_steps = (
                    len(initialization_timeline)
                    if initialization_timeline is not None
                    else 0
                )
                scenario_state_hash = _recording_step_sha256(
                    scenario_recording, step=0
                )
                initialization_state_hash = _recording_step_sha256(
                    initialization_recording, step=-1
                )
            except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
                return {"ok": False, "error": f"Failed to validate the seed scenario: {exc}"}
            expected_history_steps = int(
                scenario_metadata.get("seed_initialization_history_frames", 0) or 0
            )
            if initialization_steps != 11 or expected_history_steps != 11:
                return {
                    "ok": False,
                    "error": "The selected scenario seed must contain exactly 11 CityNDE initialization states",
                }
            if seed_ego_id not in initial_ids or seed_ego_id not in initialization_ids:
                return {
                    "ok": False,
                    "error": "The saved seed camera ego is absent from the scenario or initialization boundary",
                }
            if (
                not scenario_state_hash
                or scenario_state_hash != initialization_state_hash
                or not hmac.compare_digest(expected_state_hash, scenario_state_hash)
            ):
                return {
                    "ok": False,
                    "error": "The RGB seed initialization boundary does not match scenario frame 0",
                }

            seed_media = probe_video(seed_target, count_frames=False)
            seed_width = int(seed_media.get("width", 0) or 0)
            seed_height = int(seed_media.get("height", 0) or 0)
            expected_width = int(scenario_metadata.get("seed_width", 0) or 0)
            expected_height = int(scenario_metadata.get("seed_height", 0) or 0)
            if seed_width < 640 or seed_height < 352:
                return {
                    "ok": False,
                    "error": f"The selected scenario RGB seed is too small ({seed_width}x{seed_height})",
                }
            if abs(seed_width / max(1, seed_height) - 1280.0 / 704.0) > 0.12:
                return {
                    "ok": False,
                    "error": "The selected scenario RGB seed aspect ratio does not match OmniDreams 1280:704 input",
                }
            if (
                expected_width > 0
                and expected_height > 0
                and (seed_width, seed_height) != (expected_width, expected_height)
            ):
                return {
                    "ok": False,
                    "error": "The selected scenario RGB seed dimensions do not match its metadata",
                }

            scenario_map_path = str(scenario_metadata.get("map_path") or "").strip()
            if scenario_map_path:
                map_reference = Path(scenario_map_path)
                if not map_reference.is_absolute():
                    normalized_map = scenario_map_path.replace("\\", "/")
                    map_reference = (
                        self.root / map_reference
                        if normalized_map.startswith(("algorithm_sources/", "output/"))
                        else self.citynde_root / map_reference
                    )
                map_target = map_reference.resolve()
                if (
                    not _is_relative_to(map_target, self.citynde_root.resolve())
                    or not map_target.is_file()
                ):
                    return {
                        "ok": False,
                        "error": "The map bound to the selected scenario is unavailable",
                    }
                payload["map_path"] = scenario_map_path
                payload["scenario_configuration_locked"] = True

            if payload.get("arrival_rate") is None and scenario_metadata.get("arrival_rate") is not None:
                payload["arrival_rate"] = scenario_metadata["arrival_rate"]
            if not payload.get("arrival_rates") and isinstance(scenario_metadata.get("lane_arrival_rates"), dict):
                payload["arrival_rates"] = dict(
                    scenario_metadata["lane_arrival_rates"]
                )
            for key in (
                "mixed_traffic_enabled",
                "cyclist_ratio",
                "pedestrians_per_crosswalk",
                "max_pedestrians",
                "vehicle_size_mode",
                "initial_speed_mode",
                "signalize_unsignalized_map",
                "world_omnidreams_actor_allow_overlap",
                "world_omnidreams_actor_hood_occlusion_distance_m",
                "world_omnidreams_actor_hood_occlusion_lateral_m",
                "world_omnidreams_actor_oncoming_lateral_exclusion_m",
                "world_omnidreams_actor_max_count",
                "world_local_target_count",
                "world_initial_vehicle_limit",
                "world_ego_speed_cap_mps",
                "world_omnidreams_seed",
                "world_seed_map_radius_m",
                "world_map_radius_m",
            ):
                if payload.get(key) is None and scenario_metadata.get(key) is not None:
                    payload[key] = scenario_metadata[key]
            payload["world_seed_image"] = self._repo_rel(seed_target)
            payload["world_seed_init_file"] = self._repo_rel(seed_init_target)
            payload["world_existing_seed_gate"] = True
            payload["world_seed_ego_id"] = seed_ego_id
            payload["warmup_seconds"] = 0.0
        elif requested_seed_path:
            return {
                "ok": False,
                "error": "Select 'load existing scenario first frame' instead of passing an arbitrary seed path",
            }
        payload = _world_generation_defaults(payload)
        if (
            str(payload.get("scenario_execution_mode") or "continue").strip().lower()
            == "replay"
        ):
            if scenario_target is None:
                return {"ok": False, "error": "Recorded trajectory mode requires a managed standard scenario"}
            runtime_seed_allowed = bool(
                scenario_metadata.get("allow_recorded_runtime_seed")
                and payload.get("world_generation_enabled")
                and not requested_existing_seed
                and str(payload.get("world_seed_backend") or "").strip().lower()
                == "transfer1"
            )
            if not payload.get("world_existing_seed_gate") and not runtime_seed_allowed:
                return {"ok": False, "error": "Recorded trajectory mode requires the scenario's validated RGB first frame"}
            payload["world_recorded_runtime_seed"] = runtime_seed_allowed
            return self._launch_citynde_recorded_world(
                payload,
                scenario_target=scenario_target,
                scenario_metadata=scenario_metadata,
            )
        if not self.citynde_script.is_file():
            return {"ok": False, "error": f"CityNDE adapter not found: {self.citynde_script}"}
        init_mode = str(payload.get("init_mode") or "random_tl_only").strip()
        map_path = str(payload.get("map_path") or "assets/map/map_tianjin_part_5type_rebuild.pkl").strip()
        init_file = str(payload.get("init_file") or "").strip()
        gpu_id = str(payload.get("gpu_id") or "4").strip()
        run_until_stopped = _traffic_runs_until_stopped(payload)
        max_sim_time = 0.0 if run_until_stopped else float(payload.get("max_sim_time", 0.0) or 0.0)
        total_step = 0 if run_until_stopped else max(1, int(payload.get("total_step", 10000) or 10000))
        world_generation_enabled = bool(payload.get("world_generation_enabled", False))
        requested_world_duration = (
            _world_video_duration_seconds(payload) if world_generation_enabled else 0.0
        )
        signalize_unsignalized_map = bool(
            payload.get(
                "signalize_unsignalized_map",
                world_generation_enabled and "boston" in map_path.lower(),
            )
        )
        world_loop_ego = bool(
            payload.get(
                "world_loop_ego",
                world_generation_enabled
                and (run_until_stopped or requested_world_duration >= 120.0),
            )
        )
        payload["signalize_unsignalized_map"] = signalize_unsignalized_map
        payload["world_loop_ego"] = world_loop_ego
        requested_initial_speed_mode = str(payload.get("initial_speed_mode") or "").strip()
        initial_speed_mode = (
            requested_initial_speed_mode
            if requested_initial_speed_mode in {"citynde", "urban_sampled"}
            else "urban_sampled"
            if world_generation_enabled and init_mode == "random"
            else "citynde"
        )
        if world_generation_enabled and not run_until_stopped:
            world_duration = _world_video_duration_seconds(payload)
            max_sim_time = max(max_sim_time, world_duration)
            total_step = max(total_step, int(math.ceil(world_duration / 0.1)))
        if payload.get("save_interval") is not None:
            save_interval = max(1, int(payload.get("save_interval") or 1))
        elif run_until_stopped:
            # A growing CityNDE pickle is expensive to rewrite. Checkpoint once
            # per simulated minute and always save again on manual termination.
            save_interval = max(1, int(round(60.0 / 0.1)))
        elif world_generation_enabled and total_step > 0:
            save_interval = max(10, int(math.ceil(total_step / 20.0)))
        else:
            save_interval = 10
        exp_name = self._safe_name(str(payload.get("experiment_name", "")), fallback=init_mode)
        exp_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        port = int(payload.get("port") or self._allocate_child_port())
        payload = self._with_av_port(payload, port)
        save_dir = self.scenario_root / "experiments"
        save_dir.mkdir(parents=True, exist_ok=True)
        save_file = save_dir / f"scenario_{exp_name}_{exp_id}.pkl"
        payload["total_step"] = total_step
        payload["max_sim_time"] = 0.0 if run_until_stopped else (max_sim_time or total_step * 0.1)
        payload["run_until_stopped"] = run_until_stopped
        payload["sim_resolution"] = 0.1
        # Full Transfer generation is an offline replay operation. Running it here
        # would hold OmniDreams until the traffic window has already completed.
        payload["world_transfer_full_enabled"] = False
        world_sync_path = (
            self.root
            / "output"
            / "cosmos"
            / "experiments"
            / exp_id
            / "traffic_video_sync.json"
        )
        world_sync_enabled = world_generation_enabled and bool(
            payload.get("world_dreams_enabled", True)
        )
        if world_sync_enabled:
            update_world_sync(
                world_sync_path,
                stage="waiting_for_seed",
                experiment_id=exp_id,
                requested_traffic_time=0.0,
                generated_video_time=0.0,
            )
        arrival_rates = payload.get("arrival_rates", {}) if isinstance(payload.get("arrival_rates", {}), dict) else {}
        av_control_model = str(payload.get("av_control_model") or "DEFAULT_TCP").upper()
        av_rgb_uri = ""
        if bool(payload.get("enable_3d_simulation")):
            av_rgb_uri = f"http://127.0.0.1:{self.carla_gateway_port}/frame.jpg?experiment_id={quote(exp_id)}"
        elif world_generation_enabled and av_control_model == "LEAD_TFV6_STREAM":
            av_rgb_uri = str(
                self.root
                / "output"
                / "cosmos"
                / "experiments"
                / exp_id
                / "omnidreams"
                / "camera_front_wide_120fov_latest.jpg"
            )
        cmd = build_generation_command(
            python=self.citynde_python,
            script=self.citynde_script,
            citynde_root=self.citynde_root,
            map_path=map_path,
            init_mode=init_mode,
            total_step=total_step,
            max_sim_time=max_sim_time or total_step * 0.1,
            save_file=save_file,
            experiment_name=exp_name,
            save_interval=save_interval,
            host=self.child_host,
            port=port,
            seed=int(payload.get("seed", 42) or 42),
            gui_dir=self.gui_dir,
            init_file=(
                str(payload.get("world_seed_init_file") or "")
                if payload.get("world_existing_seed_gate")
                else init_file
            ),
            gpu_id=gpu_id,
            arrival_rate=payload.get("arrival_rate", None),
            arrival_rates=arrival_rates,
            av_enabled=bool(payload.get("av_enabled")),
            av_selection_mode=str(payload.get("av_selection_mode") or "random"),
            av_control_model=av_control_model,
            av_command_mode=str(payload.get("av_command_mode") or "state").lower(),
            av_control_host=str(payload.get("av_control_host") or "127.0.0.1"),
            av_control_port=int(payload.get("av_control_port") or 0),
            av_control_timeout=float(payload.get("av_control_timeout") or 1.0),
            av_rgb_uri=av_rgb_uri,
            denseworld_warmup=bool(payload.get("world_generation_enabled", False)),
            warmup_seconds=float(payload.get("warmup_seconds", 1.0)),
            denseworld_existing_seed=bool(payload.get("world_existing_seed_gate")),
            world_seed_ego_id=str(payload.get("world_seed_ego_id") or ""),
            mixed_traffic_enabled=bool(payload.get("mixed_traffic_enabled", True)),
            cyclist_ratio=max(0.0, min(0.5, float(payload.get("cyclist_ratio", 0.08) or 0.0))),
            pedestrians_per_crosswalk=max(
                0, min(4, int(payload.get("pedestrians_per_crosswalk", 2) or 0))
            ),
            max_pedestrians=max(0, min(256, int(payload.get("max_pedestrians", 32) or 0))),
            vehicle_size_mode=(
                "passenger_only"
                if str(payload.get("vehicle_size_mode") or "mixed") == "passenger_only"
                else "mixed"
            ),
            initial_speed_mode=initial_speed_mode,
            world_anchor_catalog=str(
                self.root / "assets" / "cosmos" / "appearance_anchors" / "catalog.json"
            ) if (
                world_generation_enabled
                and bool(payload.get("world_use_cached_appearance_anchor", False))
            ) else "",
            world_sync_state=str(world_sync_path) if world_sync_enabled else "",
            run_until_stopped=run_until_stopped,
            signalize_unsignalized_map=signalize_unsignalized_map,
            world_loop_ego=world_loop_ego,
            world_ego_speed_cap_mps=max(
                0.0,
                min(
                    35.0,
                    float(payload.get("world_ego_speed_cap_mps", 0.0) or 0.0),
                ),
            ),
            world_context_mode=str(payload.get("world_context_mode") or "auto"),
            world_local_target_count=max(
                0, min(48, int(payload.get("world_local_target_count", 0) or 0))
            ),
            world_initial_vehicle_limit=max(
                0, min(128, int(payload.get("world_initial_vehicle_limit", 0) or 0))
            ),
            world_spawn_visibility_guard_m=max(
                0.0,
                min(
                    180.0,
                    float(payload.get("world_spawn_visibility_guard_m", 100.0) or 0.0),
                ),
            ),
            control_step=max(
                1,
                min(
                    20,
                    int(payload.get("control_step", 5) or 5),
                ),
            ),
            inference_precision=str(payload.get("inference_precision") or "fp32"),
            traffic_controller=traffic_controller,
            rule_desired_speed_mps=max(
                1.0,
                min(
                    35.0,
                    float(payload.get("rule_desired_speed_mps", 10.0) or 10.0),
                ),
            ),
        )
        cmd = self._citynde_container_command(cmd, exp_id=exp_id, gpu_id=gpu_id)
        result = self._spawn_experiment(
            exp_id=exp_id,
            model="rulebased" if rulebased else "citynde",
            backend_model=backend_model,
            kind="experiment",
            name=exp_name,
            cmd=cmd,
            cwd=self.citynde_root,
            gpu_id=gpu_id,
            port=port,
            map_path=map_path,
            init_mode=init_mode,
            total_step=total_step,
            max_sim_time=0.0 if run_until_stopped else (max_sim_time or total_step * 0.1),
            save_file=self._citynde_rel(save_file),
            scenario="",
            payload=payload,
        )
        if result.get("ok"):
            self._start_builtin_av_client(exp_id, payload)
        if result.get("ok") and bool(payload.get("world_generation_enabled", False)):
            self._start_world_pipeline(exp_id, payload)
            with self._lock:
                info = self._experiments.get(exp_id)
            if info is not None:
                result["experiment"] = self.snapshot(exp_id, info)
        return result

    def _set_world_job(
        self,
        experiment_id: str,
        *,
        stage: str,
        run_state: str = "running",
        progress: float = 0.0,
        message: str = "",
        error: str = "",
        payload: dict | None = None,
        timing: tuple[str, float] | None = None,
    ) -> dict:
        if run_state == "running":
            self._raise_if_world_job_cancelled(experiment_id)
        with self._lock:
            info = self._experiments.get(experiment_id)
            previous = dict(info.get("world_generation") or {}) if info else {}
            timings = dict(previous.get("timings") or {})
            merged_payload = dict(previous.get("payload") or {})
            if payload:
                merged_payload.update(payload)
            if timing:
                timings[timing[0]] = round(float(timing[1]), 4)
            current = {
                "experiment_id": experiment_id,
                "stage": stage,
                "run_state": run_state,
                "progress": max(0.0, min(1.0, float(progress))),
                "message": message,
                "error": error,
                "payload": merged_payload,
                "timings": timings,
                "updated_at": _now_text(),
            }
            if info is not None:
                info["world_generation"] = current
        try:
            self.experiment_store.upsert_world_job(
                experiment_id,
                stage=stage,
                run_state=run_state,
                progress=progress,
                message=message,
                error=error,
                payload=merged_payload,
                timings=timings,
            )
        except Exception:
            if not self._closed:
                raise
        return current

    def _add_world_artifact(
        self,
        experiment_id: str,
        kind: str,
        path: Path,
        *,
        mime_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> dict:
        resolved = path.resolve()
        resolved.relative_to(self.root)
        relative = str(resolved.relative_to(self.root)).replace("\\", "/")
        item = {
            "kind": kind,
            "path": relative,
            "url": f"/api/v1/artifacts/file?path={quote(relative)}",
            "mime_type": mime_type,
            "metadata": metadata or {},
        }
        self.experiment_store.add_artifact(
            experiment_id,
            kind=kind,
            path=relative,
            mime_type=mime_type,
            metadata=item["metadata"],
        )
        return item

    def _start_world_pipeline(self, experiment_id: str, payload: dict) -> None:
        seed_image = str(payload.get("world_seed_image") or "").strip()
        seed_backend = _world_seed_backend(payload)
        seed_alignment_mode = _world_seed_alignment_mode(payload)
        payload["world_seed_backend"] = seed_backend
        payload["world_seed_alignment_mode"] = seed_alignment_mode
        payload["world_seed_mode"] = (
            "existing_scenario_frame"
            if seed_image
            else "single_view_transfer1_quality"
            if seed_backend == "transfer1"
            else "multiview_quality"
        )
        payload["world_seed_image"] = seed_image
        payload["world_use_cached_appearance_anchor"] = False
        seed_views = 1 if seed_image or seed_backend == "transfer1" else 7
        existing_seed_gate = bool(payload.get("world_existing_seed_gate"))
        self._set_world_job(
            experiment_id,
            stage="waiting_for_models",
            progress=0.02,
            message=(
                "Waiting for OmniDreams and the initialized scenario frame"
                if existing_seed_gate
                else (
                    "Waiting for Cosmos Dreams and the native 5 second Transfer1 traffic warmup"
                    if seed_backend == "transfer1"
                    else "Waiting for resident Cosmos models and the 1 second traffic warmup"
                )
            ),
            payload={
                "warmup_seconds": float(payload.get("warmup_seconds", 1.0)),
                "duration_seconds": (
                    None
                    if _world_video_runs_until_stopped(payload)
                    else _world_video_duration_seconds(payload)
                ),
                "traffic_duration_seconds": (
                    None if _traffic_runs_until_stopped(payload) else _traffic_duration_seconds(payload)
                ),
                "run_until_stopped": _traffic_runs_until_stopped(payload),
                "views": seed_views,
                "transfer_fps": 24 if seed_backend == "transfer1" else 10,
                "world_seed_backend": seed_backend,
                "world_seed_alignment_mode": seed_alignment_mode,
                "omnidreams_fps": 30,
            },
        )
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._world_pipeline_worker,
            args=(experiment_id, dict(payload)),
            name=f"DenseWorld-{experiment_id}",
            daemon=True,
        )
        self._world_cancel_events[experiment_id] = cancel_event
        self._world_threads[experiment_id] = thread
        thread.start()

    def _raise_if_world_job_cancelled(self, experiment_id: str) -> None:
        if self._world_stop.is_set():
            raise WorldJobCancelled("Manager shutdown interrupted world generation")
        cancel_event = self._world_cancel_events.get(experiment_id)
        if cancel_event is not None and cancel_event.is_set():
            raise WorldJobCancelled("World generation was stopped by the user")

    def _wait_for_world_seed_state(
        self,
        experiment_id: str,
        timeout: float = 900.0,
        *,
        require_dreams: bool = True,
        require_transfer: bool = True,
    ) -> tuple[dict, dict]:
        deadline = time.monotonic() + timeout
        restart_attempted = False
        while time.monotonic() < deadline and not self._world_stop.is_set():
            self._raise_if_world_job_cancelled(experiment_id)
            cosmos_status = self.cosmos.status()
            required_services = []
            if require_transfer:
                required_services.append(("Transfer2.5", cosmos_status.get("transfer") or {}))
            if require_dreams:
                required_services.append(("Cosmos Dreams", cosmos_status.get("omnidreams") or {}))
            failed_services = [
                (service_name, service_status)
                for service_name, service_status in required_services
                if service_status.get("run_state") == "error"
            ]
            if failed_services and not restart_attempted:
                restart_attempted = True
                names = ", ".join(name for name, _status in failed_services)
                self._set_world_job(
                    experiment_id,
                    stage="waiting_for_models",
                    progress=0.02,
                    message=f"Restarting failed resident Cosmos service: {names}",
                )
                self.cosmos.restart()
                continue
            if failed_services:
                service_name, service_status = failed_services[0]
                detail = str(service_status.get("log_tail") or "").strip()[-2000:]
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"{service_name} resident service exited after restart{suffix}")
            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is None:
                raise RuntimeError("Experiment was removed while preparing the world seed")
            process = info.get("process")
            if process is not None and process.poll() is not None:
                raise RuntimeError(
                    _tail_text(info.get("log_path", ""))
                    or f"{info.get('backend_model', 'traffic model')} exited during warmup"
                )
            status = self._http_json(f"http://127.0.0.1:{info['port']}/status", timeout=1.0) or {}
            transfer_ready = bool((cosmos_status.get("transfer") or {}).get("model_loaded"))
            dreams_ready = bool((cosmos_status.get("omnidreams") or {}).get("model_loaded"))
            models_ready = (transfer_ready or not require_transfer) and (
                dreams_ready or not require_dreams
            )
            if status.get("run_state") == "world_seed_pending" and models_ready:
                map_state = self._http_json(f"http://127.0.0.1:{info['port']}/map_state", timeout=5.0)
                if map_state and map_state.get("ok"):
                    return status, map_state
            time.sleep(0.5)
        if self._world_stop.is_set():
            raise RuntimeError("Manager is stopping")
        raise TimeoutError("Timed out waiting for Cosmos readiness and traffic-model warmup")

    def _collect_world_traffic(
        self,
        experiment_id: str,
        *,
        duration_seconds: float,
        ego_id: str,
    ) -> tuple[list[dict], str]:
        with self._lock:
            info = self._experiments.get(experiment_id)
        if info is None:
            raise RuntimeError("Experiment is no longer active")
        port = int(info["port"])
        frames: list[dict] = []
        version = -1
        deadline = time.monotonic() + max(300.0, duration_seconds * 30.0)
        while time.monotonic() < deadline and not self._world_stop.is_set():
            state = self._http_json(
                f"http://127.0.0.1:{port}/sim_state?after={version}&wait_ms=1500&delivery=next",
                timeout=2.5,
            ) or {}
            if not state.get("unchanged") and state.get("ok"):
                candidate_version = int(state.get("frame_version", version) or version)
                try:
                    frame, ego_id = state_to_traffic_frame(
                        state,
                        ego_id,
                        strict_ego=bool(ego_id),
                    )
                except RuntimeError:
                    if not frames:
                        continue
                    raise
                version = candidate_version
                sim_time = float(frame.get("sim_time", 0.0))
                if not frames or sim_time > float(frames[-1].get("sim_time", -1.0)) + 1e-9:
                    frames.append(frame)
                if sim_time + 1e-6 >= duration_seconds:
                    break
            status = self._http_json(f"http://127.0.0.1:{port}/status", timeout=0.8) or {}
            if status.get("run_state") in {"completed", "error"}:
                break
        if not frames:
            raise RuntimeError("No operational traffic frames were received for OmniDreams")
        if len(frames) == 1:
            duplicate = dict(frames[0])
            duplicate["sim_time"] = float(frames[0].get("sim_time", 0.0)) + 0.1
            frames.append(duplicate)
        return frames, ego_id

    def _start_world_traffic_capture(
        self,
        experiment_id: str,
        *,
        duration_seconds: float | None,
        ego_id: str,
        output_path: Path,
    ) -> tuple[dict[str, Any], threading.Thread]:
        with self._lock:
            info = self._experiments.get(experiment_id)
        if info is None:
            raise RuntimeError("Experiment is no longer active")
        port = int(info["port"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        status_path = output_path.with_suffix(".status.json")
        stream_path = output_path.with_suffix(".ndjson")
        sync_state_path = output_path.parent / "traffic_video_sync.json"
        finite_duration = (
            float(duration_seconds)
            if duration_seconds is not None and float(duration_seconds) > 0.0
            else None
        )
        open_ended = finite_duration is None
        result: dict[str, Any] = {
            "frames": [],
            "ego_id": ego_id,
            "error": "",
            "done": False,
            "status_path": str(status_path),
            "stream_path": str(stream_path),
            "open_ended": open_ended,
            "total_frames": 0,
        }
        with self._lock:
            if not hasattr(self, "_world_captures"):
                self._world_captures = {}
            self._world_captures[experiment_id] = result

        def _write_frames(frames: list[dict]) -> None:
            temporary = output_path.with_suffix(output_path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(frames, stream, ensure_ascii=False, separators=(",", ":"))
            temporary.replace(output_path)

        def _write_status(stage: str, frames: list[dict], error: str = "") -> None:
            latest_time = float(frames[-1].get("sim_time", 0.0)) if frames else None
            payload = {
                "schema": "denseworld.traffic-capture.v1",
                "stage": stage,
                "experiment_id": experiment_id,
                "frames": int(result.get("total_frames", len(frames)) or 0),
                "buffered_frames": len(frames),
                "latest_sim_time": latest_time,
                "required_sim_time": finite_duration,
                "open_ended": open_ended,
                "error": error,
                "updated_at_unix": time.time(),
            }
            temporary = status_path.with_suffix(status_path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(status_path)

        def _persisted_termination_detail(child_info: dict[str, Any]) -> str:
            candidates: list[Path] = []
            output_dir = str(child_info.get("output_dir") or "").strip()
            if output_dir:
                candidates.append(Path(output_dir) / "summary.json")
            save_file = str(child_info.get("save_file") or "").strip()
            if save_file:
                save_path = Path(save_file)
                candidates.extend((save_path.parent / "summary.json", save_path.parent.parent / "summary.json"))
            for candidate in candidates:
                try:
                    summary = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                detail = str(summary.get("last_error") or summary.get("termination_reason") or "").strip()
                if detail:
                    return detail
            return ""

        def _worker() -> None:
            frames: list[dict] = []
            version = -1
            current_ego_id = ego_id
            deadline = (
                time.monotonic() + max(300.0, finite_duration * 30.0)
                if finite_duration is not None
                else None
            )
            last_progress_at = time.monotonic()
            terminal_drain_deadline: float | None = None
            max_buffer_frames = 12000 if open_ended else 0
            try:
                _write_frames(frames)
                stream_path.write_text("", encoding="utf-8")
                _write_status("running", frames)
                with stream_path.open("a", encoding="utf-8") as live_stream:
                    while (
                        (deadline is None or time.monotonic() < deadline)
                        and not self._world_stop.is_set()
                    ):
                        cancel_event = getattr(self, "_world_cancel_events", {}).get(experiment_id)
                        if cancel_event is not None and cancel_event.is_set():
                            break
                        delivery = "latest" if version < 0 else "next"
                        state = self._http_json(
                            f"http://127.0.0.1:{port}/sim_state?after={version}&wait_ms=1500&delivery={delivery}",
                            timeout=2.5,
                        ) or {}
                        if not state.get("unchanged") and state.get("ok"):
                            candidate_version = int(state.get("frame_version", version) or version)
                            try:
                                frame, current_ego_id = state_to_traffic_frame(
                                    state,
                                    current_ego_id,
                                    strict_ego=bool(current_ego_id),
                                )
                            except RuntimeError:
                                if not frames:
                                    continue
                                raise
                            version = candidate_version
                            sim_time = float(frame.get("sim_time", 0.0))
                            if not frames or sim_time > float(frames[-1].get("sim_time", -1.0)) + 1e-9:
                                frames.append(frame)
                                result["frames"] = frames
                                result["ego_id"] = current_ego_id
                                result["total_frames"] = int(result.get("total_frames", 0) or 0) + 1
                                live_stream.write(json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n")
                                live_stream.flush()
                                if max_buffer_frames and len(frames) > max_buffer_frames:
                                    del frames[:-max_buffer_frames]
                                _write_status("running", frames)
                                last_progress_at = time.monotonic()
                            if finite_duration is not None and sim_time + 1e-6 >= finite_duration:
                                break
                        status = self._http_json(f"http://127.0.0.1:{port}/status", timeout=0.8) or {}
                        with self._lock:
                            child_info = self._experiments.get(experiment_id) or info
                        child_process = child_info.get("process")
                        return_code = child_process.poll() if child_process is not None else child_info.get("return_code")
                        run_state = str(status.get("run_state") or "")
                        terminal = run_state in {"completed", "error"} or return_code is not None
                        latest_time = float(frames[-1].get("sim_time", 0.0)) if frames else -1.0
                        if terminal and (
                            finite_duration is None or latest_time + 1e-6 < finite_duration
                        ):
                            # The simulation can mark itself completed while the asynchronous
                            # scene-state publisher still has its final snapshots queued. Drain
                            # those versions before treating a normal completion as truncation.
                            try:
                                published_version = int(status.get("sim_state_version", version) or version)
                            except (TypeError, ValueError):
                                published_version = version
                            try:
                                terminal_sim_time = float(status.get("sim_time", latest_time) or latest_time)
                            except (TypeError, ValueError):
                                terminal_sim_time = latest_time
                            normal_completion_pending = (
                                run_state == "completed"
                                and (
                                    published_version > version
                                    or (
                                        finite_duration is not None
                                        and terminal_sim_time + 1e-6 >= finite_duration
                                    )
                                )
                            )
                            if normal_completion_pending:
                                if terminal_drain_deadline is None:
                                    terminal_drain_deadline = time.monotonic() + 5.0
                                if time.monotonic() < terminal_drain_deadline:
                                    continue
                            if open_ended and (
                                run_state == "completed"
                                or (return_code == 0 and run_state != "error")
                            ):
                                break
                            persisted_detail = _persisted_termination_detail(child_info)
                            log_detail = (
                                _tail_text(child_info.get("log_path", ""))
                                if return_code not in {None, 0}
                                else ""
                            )
                            detail = str(
                                status.get("last_error")
                                or status.get("termination_reason")
                                or persisted_detail
                                or log_detail
                                or f"child process exited with return code {return_code}"
                            ).strip()
                            if open_ended:
                                raise RuntimeError(
                                    f"Traffic simulation ended at {latest_time:.3f}s: {detail[-2000:]}"
                                )
                            raise RuntimeError(
                                f"Traffic simulation ended at {latest_time:.3f}s before required "
                                f"{finite_duration:.3f}s: {detail[-2000:]}"
                            )
                        if traffic_capture_wait_is_expected(sync_state_path, latest_time):
                            last_progress_at = time.monotonic()
                        elif time.monotonic() - last_progress_at > max(
                            90.0,
                            float(os.environ.get("TRAFFIC_CAPTURE_STALL_SECONDS", "300") or 300.0),
                        ):
                            detail = str(status.get("last_error") or status.get("termination_reason") or "").strip()
                            suffix = f": {detail}" if detail else ""
                            raise TimeoutError(
                                "Traffic simulation made no progress after "
                                f"{latest_time:.3f}s for the configured stall timeout{suffix}"
                            )
                latest_time = float(frames[-1].get("sim_time", 0.0)) if frames else -1.0
                cancel_event = getattr(self, "_world_cancel_events", {}).get(experiment_id)
                capture_cancelled = cancel_event is not None and cancel_event.is_set()
                if (
                    finite_duration is not None
                    and latest_time + 1e-6 < finite_duration
                    and not capture_cancelled
                ):
                    reason = "manager shutdown" if self._world_stop.is_set() else "capture deadline exceeded"
                    raise TimeoutError(
                        f"Traffic capture stopped at {latest_time:.3f}s before required "
                        f"{finite_duration:.3f}s ({reason})"
                    )
                if len(frames) == 1:
                    duplicate = dict(frames[0])
                    duplicate["sim_time"] = float(frames[0].get("sim_time", 0.0)) + 0.1
                    frames.append(duplicate)
                    result["frames"] = frames
                    result["total_frames"] = int(result.get("total_frames", 1) or 1) + 1
                    with stream_path.open("a", encoding="utf-8") as live_stream:
                        live_stream.write(json.dumps(duplicate, ensure_ascii=False, separators=(",", ":")) + "\n")
                if not frames:
                    raise RuntimeError("No operational traffic frames were received for OmniDreams")
            except Exception as exc:
                result["error"] = str(exc)
                _write_status("error", frames, str(exc))
            finally:
                try:
                    _write_frames(frames)
                except OSError as exc:
                    result["error"] = result["error"] or f"Failed to finalize traffic JSON: {exc}"
                result["done"] = True
                if result["error"]:
                    _write_status("error", frames, str(result["error"]))
                elif (
                    (getattr(self, "_world_cancel_events", {}).get(experiment_id) is not None)
                    and getattr(self, "_world_cancel_events", {})[experiment_id].is_set()
                ):
                    _write_status("stopped", frames)
                else:
                    _write_status("completed", frames)

        thread = threading.Thread(target=_worker, name=f"WorldTrafficCapture-{experiment_id}", daemon=True)
        thread.start()
        return result, thread

    def _start_omnidreams_transfer_anchor_worker(
        self,
        experiment_id: str,
        *,
        capture_result: dict[str, Any],
        map_state: dict[str, Any],
        ego_id: str,
        pipeline_root: Path,
        effective_prompt: str,
        duration_seconds: float | None,
        segment_seconds: float,
        source_fps: float,
        map_radius_m: float,
        world_sync_path: Path,
        transfer_steps: int,
        transfer_seed: int,
        max_attempts: int,
        anchor_mode: str,
    ) -> tuple[Path, dict[str, Any], threading.Thread, threading.Event]:
        """Produce geometry-matched Transfer frames ahead of OmniDreams rollovers."""
        video_fps = 30
        source_fps = max(1.0, float(source_fps))
        anchor_mode = str(anchor_mode or "conditioned_front").strip().lower()
        if anchor_mode not in {"conditioned_front", "unconditioned_multiview"}:
            raise ValueError(
                "OmniDreams anchor mode must be conditioned_front or "
                "unconditioned_multiview"
            )
        anchor_cameras = (
            [CAMERAS[0]]
            if anchor_mode == "conditioned_front"
            else list(CAMERAS)
        )
        segment_frames = omnidreams_session_frame_budget(
            segment_seconds,
            fps=video_fps,
        )
        finite_duration = (
            max(0.0, float(duration_seconds))
            if duration_seconds is not None and float(duration_seconds) > 0.0
            else None
        )
        manifest_path = pipeline_root / "omnidreams" / "transfer_anchors" / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        stop_event = threading.Event()
        result: dict[str, Any] = {"error": "", "completed": False, "anchors": 0}
        manifest: dict[str, Any] = {
            "schema": "denseworld.omnidreams-transfer-anchors.v1",
            "experiment_id": experiment_id,
            "video_fps": video_fps,
            "source_traffic_fps": source_fps,
            "requested_segment_seconds": float(segment_seconds),
            "session_frame_budget": segment_frames,
            "actual_segment_seconds": segment_frames / float(video_fps),
            "transfer_steps": max(1, int(transfer_steps)),
            "transfer_seed": int(transfer_seed),
            "max_attempts": max(1, min(5, int(max_attempts))),
            "anchor_mode": anchor_mode,
            "camera_topology": (
                "single_front_view_appearance_conditioned"
                if anchor_mode == "conditioned_front"
                else "seven_view_unconditioned"
            ),
            "resident_service": (
                "anchor_transfer" if anchor_mode == "conditioned_front" else "transfer"
            ),
            "anchors": [],
            "completed": False,
            "error": "",
        }

        if finite_duration is not None:
            target_frames = omnidreams_rollover_frame_indices(
                finite_duration,
                segment_seconds,
                fps=video_fps,
            )
            manifest["anchors"] = [
                {
                    "index": index,
                    "target_frame": target_frame,
                    "target_time_seconds": round(target_frame / float(video_fps), 6),
                    "status": "pending",
                }
                for index, target_frame in enumerate(target_frames)
            ]

        def _write_manifest() -> None:
            manifest["updated_at_unix"] = time.time()
            temporary = manifest_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(manifest_path)

        def _cancelled() -> bool:
            cancel_event = getattr(self, "_world_cancel_events", {}).get(experiment_id)
            return bool(
                stop_event.is_set()
                or self._world_stop.is_set()
                or (cancel_event is not None and cancel_event.is_set())
            )

        def _wait_for_source_window(target_time: float) -> tuple[list[dict], float]:
            source_end = math.floor(target_time * source_fps + 1e-6) / source_fps
            source_end = max(1.0, source_end)
            source_start = source_end - 1.0
            deadline = time.monotonic() + 3600.0
            while time.monotonic() < deadline and not _cancelled():
                frames = list(capture_result.get("frames") or [])
                if frames and float(frames[-1].get("sim_time", 0.0) or 0.0) + 1e-6 >= source_end:
                    sampled = [
                        _interpolate_world_capture(frames, source_start + index / source_fps)
                        for index in range(int(round(source_fps)) + 1)
                    ]
                    return sampled, source_end
                if capture_result.get("done"):
                    detail = str(capture_result.get("error") or "traffic stream ended").strip()
                    raise RuntimeError(
                        f"Traffic ended before Transfer anchor at {source_end:.3f}s: {detail}"
                    )
                time.sleep(0.25)
            if _cancelled():
                raise WorldJobCancelled("Transfer anchor generation was stopped")
            raise TimeoutError(
                f"Timed out waiting for traffic state at {source_end:.3f}s"
            )

        def _wait_for_appearance_frame(
            source_end: float,
            anchor_root: Path,
        ) -> tuple[Path, int, float]:
            appearance_time = max(0.0, source_end - 1.0)
            frame_index = max(0, int(round(appearance_time * video_fps)))
            sequence_root = (
                pipeline_root
                / "omnidreams"
                / "camera_front_wide_120fov_latest_frames"
            )
            target_path = anchor_root / "appearance" / f"omnidreams_{frame_index:08d}.jpg"
            progress_path = pipeline_root / "omnidreams" / "progress.json"
            started = time.monotonic()
            deadline = started + 3600.0
            while time.monotonic() < deadline and not _cancelled():
                preview_fps = max(
                    1,
                    int(os.environ.get("OMNIDREAMS_LIVE_PREVIEW_FPS", "15") or 15),
                )
                try:
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
                    preview_fps = max(1, int(progress.get("preview_fps") or preview_fps))
                except (OSError, TypeError, ValueError):
                    pass
                preview_frame_index = _omnidreams_preview_frame_index(
                    frame_index,
                    output_fps=video_fps,
                    preview_fps=preview_fps,
                )
                source_path = sequence_root / f"{preview_frame_index:08d}.jpg"
                try:
                    payload = source_path.read_bytes()
                except OSError:
                    payload = b""
                if len(payload) > 1024 and payload.startswith(b"\xff\xd8"):
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target_path.with_suffix(".jpg.tmp")
                    temporary.write_bytes(payload)
                    temporary.replace(target_path)
                    return target_path, frame_index, time.monotonic() - started
                time.sleep(0.1)
            if _cancelled():
                raise WorldJobCancelled("Transfer anchor generation was stopped")
            raise TimeoutError(
                "Timed out waiting for OmniDreams appearance frame "
                f"{frame_index} at output fps ({appearance_time:.3f}s)"
            )

        def _entry_for(target_frame: int, index: int) -> dict[str, Any]:
            existing = next(
                (
                    item
                    for item in manifest["anchors"]
                    if int(item.get("target_frame", -1) or -1) == int(target_frame)
                ),
                None,
            )
            if existing is not None:
                return existing
            entry = {
                "index": index,
                "target_frame": int(target_frame),
                "target_time_seconds": round(target_frame / float(video_fps), 6),
                "status": "pending",
            }
            manifest["anchors"].append(entry)
            _write_manifest()
            return entry

        def _worker() -> None:
            index = 0
            next_target_frame = segment_frames
            stationary_appearance_reference: dict[str, Any] = {}
            try:
                _write_manifest()
                while not _cancelled():
                    if finite_duration is not None:
                        planned = manifest["anchors"]
                        if index >= len(planned):
                            break
                        target_frame = int(planned[index]["target_frame"])
                    else:
                        target_frame = next_target_frame
                    entry = _entry_for(target_frame, index)
                    target_time = target_frame / float(video_fps)
                    lookahead_time = (target_frame + segment_frames) / float(video_fps)
                    if finite_duration is not None:
                        lookahead_time = min(finite_duration, lookahead_time)
                    # The traffic gate can only satisfy source-frame timestamps.
                    requested_traffic_time = (
                        math.ceil(lookahead_time * source_fps - 1e-9) / source_fps
                    )
                    update_world_sync(
                        world_sync_path,
                        stage="prefetching_transfer_anchor",
                        requested_traffic_time=requested_traffic_time,
                        transfer_anchor_target_time=target_time,
                        transfer_anchor_index=index,
                    )
                    entry.update({"status": "waiting_for_traffic", "started_at_unix": time.time()})
                    _write_manifest()
                    source_frames, source_end = _wait_for_source_window(target_time)
                    anchor_root = manifest_path.parent / f"anchor_{index:05d}_{target_frame:08d}"
                    recording_path = anchor_root / "traffic_1s.pkl"
                    traffic_report = traffic_frames_to_recording(
                        source_frames,
                        map_state,
                        recording_path,
                        source_fps=source_fps,
                        duration_seconds=1.0,
                    )
                    prepared_path = anchor_root / "transfer_window.pkl"
                    transfer_window = prepare_citynde_transfer_window(
                        recording_path,
                        prepared_path,
                        real_source_steps=int(traffic_report["recording_frames"]),
                        target_source_steps=TRANSFER_WINDOW_SOURCE_STEPS,
                        source_fps=source_fps,
                    )
                    clip_id = f"anchor-{experiment_id}-{index:05d}"
                    scene_root = anchor_root / "rds_hq"
                    entry["status"] = "rendering_control"
                    _write_manifest()
                    export_report = export_citynde_scene(
                        prepared_path,
                        scene_root,
                        clip_id=clip_id,
                        source_steps=int(transfer_window["native_source_steps"]),
                        source_fps=source_fps,
                        target_fps=30,
                        ego_id=ego_id or None,
                        map_state=map_state,
                        map_radius_m=map_radius_m,
                    )
                    control_root = anchor_root / "controls"
                    render_report = self.cosmos.render_controls(
                        scene_root,
                        control_root,
                        clip_id=clip_id,
                        cameras=anchor_cameras,
                    )
                    controls = control_paths(
                        control_root,
                        clip_id,
                        cameras=anchor_cameras,
                    )
                    ego_samples = [
                        dict(frame.get("ego") or {})
                        for frame in source_frames
                        if (frame.get("ego") or {}).get("id") is not None
                    ]
                    ego_displacement_m = math.inf
                    ego_max_speed_mps = math.inf
                    if len(ego_samples) >= 2:
                        ego_displacement_m = math.hypot(
                            float(ego_samples[-1].get("x", 0.0) or 0.0)
                            - float(ego_samples[0].get("x", 0.0) or 0.0),
                            float(ego_samples[-1].get("y", 0.0) or 0.0)
                            - float(ego_samples[0].get("y", 0.0) or 0.0),
                        )
                        ego_max_speed_mps = max(
                            max(0.0, float(item.get("speed", 0.0) or 0.0))
                            for item in ego_samples
                        )
                    stationary_ego = bool(
                        len(ego_samples) >= 2
                        and ego_displacement_m <= 0.5
                        and ego_max_speed_mps <= 0.5
                    )
                    entry["traffic_window"] = {
                        "start_time_seconds": round(source_end - 1.0, 6),
                        "end_time_seconds": round(source_end, 6),
                        "ego_displacement_m": round(ego_displacement_m, 4),
                        "ego_max_speed_mps": round(ego_max_speed_mps, 4),
                        "stationary_ego": stationary_ego,
                    }
                    control_qa = analyze_group(
                        list(controls.values()),
                        anchor_root / "qa" / "controls",
                        expected_duration=int(export_report["output_frames"]) / 30.0,
                        expected_fps=30.0,
                        quality_profile=(
                            "semantic_control_stationary"
                            if stationary_ego
                            else "semantic_control"
                        ),
                    )
                    if not control_qa.get("passed"):
                        errors = [
                            error
                            for view in control_qa.get("views") or []
                            for error in view.get("errors") or []
                        ]
                        raise RuntimeError(
                            "Transfer anchor controls failed QA: "
                            + ("; ".join(errors[:4]) or "unknown control error")
                        )
                    padded = pad_controls(
                        controls,
                        anchor_root / "controls_transfer_window",
                        minimum_frames=87,
                        fps=30,
                    )
                    transfer_inputs: dict[str, Path] = {}
                    appearance_path: Path | None = None
                    appearance_frame_index: int | None = None
                    appearance_wait_seconds = 0.0
                    if anchor_mode == "conditioned_front":
                        expected_appearance_frame = max(
                            0,
                            int(round((source_end - 1.0) * video_fps)),
                        )
                        reference_reused = False
                        current_pose = dict(ego_samples[0]) if ego_samples else {}
                        reference_pose = dict(
                            stationary_appearance_reference.get("ego_pose") or {}
                        )
                        if stationary_ego and reference_pose:
                            pose_distance = math.hypot(
                                float(current_pose.get("x", 0.0) or 0.0)
                                - float(reference_pose.get("x", 0.0) or 0.0),
                                float(current_pose.get("y", 0.0) or 0.0)
                                - float(reference_pose.get("y", 0.0) or 0.0),
                            )
                            heading_delta = abs(
                                math.atan2(
                                    math.sin(
                                        float(current_pose.get("heading", 0.0) or 0.0)
                                        - float(reference_pose.get("heading", 0.0) or 0.0)
                                    ),
                                    math.cos(
                                        float(current_pose.get("heading", 0.0) or 0.0)
                                        - float(reference_pose.get("heading", 0.0) or 0.0)
                                    ),
                                )
                            )
                            reference_path = Path(
                                str(stationary_appearance_reference.get("path") or "")
                            )
                            if (
                                pose_distance <= 0.5
                                and heading_delta <= math.radians(5.0)
                                and reference_path.is_file()
                            ):
                                appearance_path = reference_path
                                appearance_frame_index = int(
                                    stationary_appearance_reference["frame_index"]
                                )
                                reference_reused = True
                        if appearance_path is None:
                            if not stationary_ego:
                                stationary_appearance_reference.clear()
                            entry["status"] = "waiting_for_omnidreams_appearance"
                            _write_manifest()
                            (
                                appearance_path,
                                appearance_frame_index,
                                appearance_wait_seconds,
                            ) = _wait_for_appearance_frame(source_end, anchor_root)
                            if stationary_ego:
                                stationary_appearance_reference = {
                                    "path": str(appearance_path),
                                    "frame_index": appearance_frame_index,
                                    "ego_pose": current_pose,
                                }
                        prepared_input = prepare_transfer_input_media(
                            appearance_path,
                            anchor_root / "appearance" / "front_wide_input_87f.mp4",
                            frames=87,
                            fps=30,
                        )
                        transfer_inputs = {CAMERAS[0]: prepared_input}
                        entry["appearance"] = {
                            "source_path": str(appearance_path),
                            "source_frame": appearance_frame_index,
                            "source_time_seconds": round(
                                float(appearance_frame_index) / video_fps,
                                6,
                            ),
                            "prepared_input_path": str(prepared_input),
                            "wait_seconds": round(appearance_wait_seconds, 4),
                            "num_conditional_frames": 1,
                            "expected_current_frame": expected_appearance_frame,
                            "stationary_reference_reused": reference_reused,
                            "reference_age_seconds": round(
                                max(
                                    0.0,
                                    (
                                        expected_appearance_frame
                                        - float(appearance_frame_index)
                                    )
                                    / video_fps,
                                ),
                                6,
                            ),
                        }
                        _write_manifest()
                    transfer_attempts: list[dict[str, Any]] = []
                    image_path: Path | None = None
                    qa_view: dict[str, Path] = {}
                    generated_qa: dict[str, Any] = {}
                    transfer_job: dict[str, Any] = {}
                    selected_seed = int(transfer_seed)
                    for attempt_index in range(max(1, min(5, int(max_attempts)))):
                        attempt_number = attempt_index + 1
                        attempt_seed = (
                            int(transfer_seed) + attempt_index * 104729
                        ) % (2**31)
                        attempt_root = anchor_root / f"transfer_attempt_{attempt_number:02d}"
                        transfer_name = (
                            f"omni_anchor_{experiment_id}_{index:05d}_attempt_{attempt_number:02d}"
                        )
                        spec_path = attempt_root / "transfer_spec.json"
                        write_transfer_spec(
                            spec_path,
                            name=transfer_name,
                            controls=padded,
                            prompt=effective_prompt,
                            duration_seconds=1.0,
                            num_steps=max(1, int(transfer_steps)),
                            seed=attempt_seed,
                            input_paths=transfer_inputs or None,
                            num_conditional_frames=(
                                1 if anchor_mode == "conditioned_front" else 0
                            ),
                        )
                        entry.update(
                            {
                                "status": "generating_transfer",
                                "attempt": attempt_number,
                                "attempt_seed": attempt_seed,
                            }
                        )
                        _write_manifest()
                        transfer_output = attempt_root / "transfer_raw"
                        runner = (
                            self._run_anchor_transfer_job
                            if anchor_mode == "conditioned_front"
                            else self._run_transfer_job
                        )
                        candidate_job = runner(
                            spec_path,
                            transfer_output,
                            job_id=(
                                f"omni-anchor-{experiment_id}-{index:05d}"
                                f"-attempt-{attempt_number:02d}"
                            ),
                            experiment_id=experiment_id,
                        )
                        raw_views = discover_transfer_views(
                            transfer_output,
                            transfer_name,
                            views=[VIEW_KEYS[camera] for camera in anchor_cameras],
                        )
                        candidate_image = extract_seed_frame(
                            raw_views["front_wide"],
                            attempt_root / "front_wide_terminal.png",
                            WARMUP_TERMINAL_FRAME_INDEX,
                        )
                        candidate_qa_view = trim_views(
                            {"front_wide": raw_views["front_wide"]},
                            attempt_root / "front_wide_1s",
                            frames=10,
                            fps=10,
                        )
                        candidate_qa_dir = attempt_root / "qa" / "generated"
                        candidate_qa = analyze_group(
                            list(candidate_qa_view.values()),
                            candidate_qa_dir,
                            expected_duration=1.0,
                            expected_fps=10.0,
                            quality_profile=(
                                "generated_driving_i2v_window"
                                if anchor_mode == "conditioned_front"
                                else "generated_driving_seed"
                            ),
                        )
                        terminal_qa: dict[str, Any] = {"passed": True, "views": []}
                        terminal_qa_dir = attempt_root / "qa" / "terminal"
                        if anchor_mode == "conditioned_front":
                            terminal_views = trim_views(
                                {"front_wide": raw_views["front_wide"]},
                                attempt_root / "front_wide_terminal_tail",
                                start_frame=max(0, WARMUP_TERMINAL_FRAME_INDEX - 3),
                                frames=5,
                                fps=10,
                            )
                            terminal_qa = analyze_group(
                                list(terminal_views.values()),
                                terminal_qa_dir,
                                expected_duration=0.5,
                                expected_fps=10.0,
                                quality_profile="generated_driving_seed",
                            )
                        attempt_errors = [
                            error
                            for report in (candidate_qa, terminal_qa)
                            for view in report.get("views") or []
                            for error in view.get("errors") or []
                        ]
                        attempt_passed = bool(
                            candidate_qa.get("passed") and terminal_qa.get("passed")
                        )
                        transfer_attempts.append(
                            {
                                "attempt": attempt_number,
                                "seed": attempt_seed,
                                "passed": attempt_passed,
                                "errors": attempt_errors,
                                "spec_path": str(spec_path),
                                "generated_qa": str(candidate_qa_dir / "video_qa.json"),
                                "terminal_qa": (
                                    str(terminal_qa_dir / "video_qa.json")
                                    if anchor_mode == "conditioned_front"
                                    else ""
                                ),
                                "generation_seconds": float(
                                    candidate_job.get("generation_seconds", 0.0) or 0.0
                                ),
                            }
                        )
                        entry["transfer_attempts"] = transfer_attempts
                        _write_manifest()
                        if attempt_passed:
                            image_path = candidate_image
                            qa_view = candidate_qa_view
                            generated_qa = candidate_qa
                            transfer_job = candidate_job
                            selected_seed = attempt_seed
                            break
                        entry["status"] = "retrying_transfer"
                        _write_manifest()
                    if image_path is None:
                        errors = list((transfer_attempts or [{}])[-1].get("errors") or [])
                        raise RuntimeError(
                            "Transfer anchor failed generated-driving QA after "
                            f"{len(transfer_attempts)} attempts: "
                            + ("; ".join(errors[:4]) or "unknown generated-video error")
                        )
                    entry.update(
                        {
                            "status": "ready",
                            "source_time_seconds": source_end,
                            "image_path": str(image_path),
                            "control_path": str(controls[CAMERAS[0]]),
                            "video_path": str(qa_view["front_wide"]),
                            "traffic_recording": str(recording_path),
                            "scene_export": str(scene_root / "trafficwm_export_report.json"),
                            "control_qa": str(anchor_root / "qa" / "controls" / "video_qa.json"),
                            "generated_qa": str(
                                Path(str(transfer_attempts[-1]["generated_qa"]))
                            ),
                            "terminal_qa": str(
                                transfer_attempts[-1].get("terminal_qa") or ""
                            ),
                            "anchor_mode": anchor_mode,
                            "appearance_path": (
                                str(appearance_path) if appearance_path is not None else ""
                            ),
                            "appearance_frame_index": appearance_frame_index,
                            "appearance_wait_seconds": round(
                                appearance_wait_seconds,
                                4,
                            ),
                            "control_render_seconds": float(render_report.get("seconds", 0.0) or 0.0),
                            "transfer_generation_seconds": sum(
                                float(item.get("generation_seconds", 0.0) or 0.0)
                                for item in transfer_attempts
                            ),
                            "selected_transfer_seed": selected_seed,
                            "ready_at_unix": time.time(),
                        }
                    )
                    result["anchors"] = index + 1
                    _write_manifest()
                    index += 1
                    next_target_frame += segment_frames
                manifest["completed"] = not _cancelled()
                result["completed"] = bool(manifest["completed"])
            except WorldJobCancelled:
                manifest["stopped"] = True
            except BaseException as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
                manifest["error"] = result["error"]
                if index < len(manifest["anchors"]):
                    manifest["anchors"][index].update(
                        {"status": "error", "error": result["error"]}
                    )
            finally:
                _write_manifest()

        thread = threading.Thread(
            target=_worker,
            name=f"OmniTransferAnchors-{experiment_id}",
            daemon=True,
        )
        thread.start()
        return manifest_path, result, thread, stop_event

    def _recover_completed_transfer_outputs(self, spec_path: Path, output_dir: Path, *, job_id: str, started_at: float) -> dict | None:
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        name = str(spec.get("name") or "").strip()
        if not name:
            return None
        view_names = [
            view
            for view in VIEW_KEYS.values()
            if isinstance(spec.get(view), dict) and spec.get(view, {}).get("control_path")
        ]
        if not view_names:
            return None
        outputs = [output_dir / f"{name}_{view}.mp4" for view in view_names]
        if not all(path.is_file() and path.stat().st_size > 0 for path in outputs):
            return None
        try:
            output_contract = validate_transfer_outputs(spec_path, output_dir)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            return None
        finished_at = max(path.stat().st_mtime for path in outputs)
        return {
            "id": job_id,
            "run_state": "completed",
            "outputs": [str(path.resolve()) for path in outputs],
            "started_at_unix": started_at,
            "finished_at_unix": finished_at,
            "generation_seconds": round(max(0.0, finished_at - started_at), 3),
            "recovered_from_outputs": True,
            "output_contract": output_contract,
        }

    def _run_transfer_job(
        self,
        spec_path: Path,
        output_dir: Path,
        *,
        job_id: str,
        experiment_id: str = "",
    ) -> dict:
        if experiment_id:
            self._raise_if_world_job_cancelled(experiment_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        input_contract = validate_transfer_spec_media(spec_path)
        seed_cache_enabled = (
            job_id.startswith("seed-")
            and os.environ.get("COSMOS_TRANSFER2_SEED_CACHE_ENABLED", "1")
            .strip()
            .lower()
            not in {"0", "false", "no", "off"}
        )
        seed_cache_root = transfer2_seed_cache_root(self.root)
        cache_error = ""
        if seed_cache_enabled:
            try:
                with _TRANSFER2_SEED_CACHE_LOCK:
                    cached = restore_transfer2_seed_cache(
                        spec_path,
                        output_dir,
                        seed_cache_root,
                    )
                if cached is not None:
                    output_contract = validate_transfer_outputs(spec_path, output_dir)
                    return {
                        "id": job_id,
                        "run_state": "completed",
                        "outputs": cached["outputs"],
                        "generation_seconds": 0.0,
                        "cache_hit": True,
                        "cache_key": cached["cache_key"],
                        "cache_manifest": cached["cache_manifest"],
                        "input_contract": input_contract,
                        "output_contract": output_contract,
                    }
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                cache_error = f"{type(exc).__name__}: {exc}"
        attempt = 0
        resolved_id = job_id
        submitted_at = time.time()
        submitted = self.cosmos.submit_transfer(spec_path, output_dir, job_id=resolved_id)
        if not submitted.get("ok"):
            raise RuntimeError(str(submitted.get("error") or "Transfer worker rejected the job"))
        resolved_id = str((submitted.get("job") or {}).get("id") or resolved_id)
        submitted_at = float((submitted.get("job") or {}).get("submitted_at_unix") or submitted_at)
        deadline = time.monotonic() + 21600.0

        def _restart_and_resubmit(reason: str) -> tuple[str, float]:
            nonlocal attempt
            attempt += 1
            if experiment_id:
                self._raise_if_world_job_cancelled(experiment_id)
            self.cosmos.restart()
            ready_deadline = time.monotonic() + 900.0
            while time.monotonic() < ready_deadline and not self._world_stop.is_set():
                if experiment_id:
                    self._raise_if_world_job_cancelled(experiment_id)
                transfer_status = self.cosmos.status().get("transfer") or {}
                if transfer_status.get("model_loaded"):
                    retry_id = f"{job_id}-retry{attempt}"
                    retry_submitted_at = time.time()
                    retry = self.cosmos.submit_transfer(spec_path, output_dir, job_id=retry_id)
                    if not retry.get("ok"):
                        raise RuntimeError(
                            str(retry.get("error") or f"Transfer worker rejected retry for {job_id}: {reason}")
                        )
                    retry_id = str((retry.get("job") or {}).get("id") or retry_id)
                    retry_submitted_at = float(
                        (retry.get("job") or {}).get("submitted_at_unix") or retry_submitted_at
                    )
                    return retry_id, retry_submitted_at
                if transfer_status.get("run_state") == "error":
                    detail = str(transfer_status.get("log_tail") or transfer_status.get("error") or reason).strip()
                    raise RuntimeError(f"Transfer2.5 failed to reload: {detail[-2000:]}")
                time.sleep(1.0)
            if self._world_stop.is_set():
                raise RuntimeError("Manager is stopping while Transfer2.5 reloads")
            raise TimeoutError("Timed out reloading Transfer2.5 for a camera-topology change")

        while time.monotonic() < deadline and not self._world_stop.is_set():
            if experiment_id:
                self._raise_if_world_job_cancelled(experiment_id)
            transfer_status = self.cosmos.status().get("transfer") or {}
            if transfer_status.get("run_state") == "error":
                detail = str(transfer_status.get("log_tail") or "").strip()[-2000:]
                recovered = self._recover_completed_transfer_outputs(
                    spec_path,
                    output_dir,
                    job_id=resolved_id,
                    started_at=submitted_at,
                )
                if recovered is not None:
                    recovered["warning"] = "Transfer resident exited after writing expected outputs"
                    recovered["log_tail"] = detail
                    return recovered
                if attempt < 1:
                    resolved_id, submitted_at = _restart_and_resubmit(detail or "resident service exited")
                    continue
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"Transfer2.5 resident service exited during job {resolved_id}{suffix}")
            response = self.cosmos.transfer_job(resolved_id)
            if not response.get("ok"):
                recovered = self._recover_completed_transfer_outputs(
                    spec_path,
                    output_dir,
                    job_id=resolved_id,
                    started_at=submitted_at,
                )
                if recovered is not None:
                    recovered["warning"] = "Transfer job disappeared after writing expected outputs"
                    return recovered
                if attempt < 1 and "not found" in str(response.get("error", "")).lower():
                    attempt += 1
                    resolved_id = f"{job_id}-retry{attempt}"
                    submitted_at = time.time()
                    submitted = self.cosmos.submit_transfer(spec_path, output_dir, job_id=resolved_id)
                    if not submitted.get("ok"):
                        raise RuntimeError(str(submitted.get("error") or "Transfer worker rejected retry"))
                    resolved_id = str((submitted.get("job") or {}).get("id") or resolved_id)
                    submitted_at = float((submitted.get("job") or {}).get("submitted_at_unix") or submitted_at)
                    continue
            job = response.get("job") or {}
            if job.get("run_state") == "completed":
                output_contract = validate_transfer_outputs(spec_path, output_dir)
                job["input_contract"] = input_contract
                job["output_contract"] = output_contract
                job["cache_hit"] = False
                if cache_error:
                    job["cache_restore_warning"] = cache_error
                if seed_cache_enabled:
                    try:
                        with _TRANSFER2_SEED_CACHE_LOCK:
                            cache_record = store_transfer2_seed_cache(
                                spec_path,
                                output_dir,
                                seed_cache_root,
                            )
                        job.update(
                            {
                                "cache_key": cache_record["cache_key"],
                                "cache_manifest": cache_record["cache_manifest"],
                            }
                        )
                    except (OSError, TypeError, ValueError, RuntimeError) as exc:
                        job["cache_store_warning"] = f"{type(exc).__name__}: {exc}"
                return job
            if job.get("run_state") == "error":
                job_error = str(job.get("error") or "Transfer generation failed")
                if attempt < 1 and "TRANSFER_TOPOLOGY_CHANGE" in job_error:
                    resolved_id, submitted_at = _restart_and_resubmit(job_error)
                    continue
                raise RuntimeError(job_error)
            time.sleep(3.0)
        raise TimeoutError(f"Transfer job {resolved_id} timed out")

    def _run_anchor_transfer_job(
        self,
        spec_path: Path,
        output_dir: Path,
        *,
        job_id: str,
        experiment_id: str = "",
    ) -> dict:
        """Run one front-view anchor without disturbing the primary multiview service."""
        if experiment_id:
            self._raise_if_world_job_cancelled(experiment_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        input_contract = validate_transfer_spec_media(spec_path)
        submitted_at = time.time()
        submitted = self.cosmos.submit_anchor_transfer(
            spec_path,
            output_dir,
            job_id=job_id,
        )
        if not submitted.get("ok"):
            raise RuntimeError(
                str(submitted.get("error") or "Anchor Transfer worker rejected the job")
            )
        resolved_id = str((submitted.get("job") or {}).get("id") or job_id)
        submitted_at = float(
            (submitted.get("job") or {}).get("submitted_at_unix") or submitted_at
        )
        deadline = time.monotonic() + 3600.0
        while time.monotonic() < deadline and not self._world_stop.is_set():
            if experiment_id:
                self._raise_if_world_job_cancelled(experiment_id)
            service = self.cosmos.status().get("anchor_transfer") or {}
            if service.get("run_state") == "error":
                recovered = self._recover_completed_transfer_outputs(
                    spec_path,
                    output_dir,
                    job_id=resolved_id,
                    started_at=submitted_at,
                )
                if recovered is not None:
                    recovered["warning"] = (
                        "Anchor Transfer resident exited after writing expected outputs"
                    )
                    return recovered
                detail = str(
                    service.get("log_tail") or service.get("error") or ""
                ).strip()
                suffix = f": {detail[-2000:]}" if detail else ""
                raise RuntimeError(
                    f"Anchor Transfer2.5 resident exited during job {resolved_id}{suffix}"
                )
            response = self.cosmos.anchor_transfer_job(resolved_id)
            if not response.get("ok"):
                recovered = self._recover_completed_transfer_outputs(
                    spec_path,
                    output_dir,
                    job_id=resolved_id,
                    started_at=submitted_at,
                )
                if recovered is not None:
                    recovered["warning"] = (
                        "Anchor Transfer job disappeared after writing expected outputs"
                    )
                    return recovered
                raise RuntimeError(
                    str(response.get("error") or "Anchor Transfer job lookup failed")
                )
            job = response.get("job") or {}
            if job.get("run_state") == "completed":
                job["input_contract"] = input_contract
                job["output_contract"] = validate_transfer_outputs(
                    spec_path,
                    output_dir,
                )
                return job
            if job.get("run_state") == "error":
                raise RuntimeError(
                    str(job.get("error") or "Anchor Transfer generation failed")
                )
            time.sleep(1.0)
        if self._world_stop.is_set():
            raise RuntimeError("Manager is stopping while anchor Transfer runs")
        raise TimeoutError(f"Anchor Transfer job {resolved_id} timed out")

    def launch_transfer_replay(self, payload: dict) -> dict:
        scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
        target, error, model = self._record_target(scenario)
        if error is not None:
            return error
        if model != "citynde" or target is None or not target.is_file():
            return {"ok": False, "error": "Transfer replay currently requires a CityNDE .pkl recording"}
        try:
            max_transfer_duration = (
                300.0 if bool(payload.get("allow_segmented_transfer", False)) else 15.0
            )
            window = inspect_recording_window(
                target,
                start_step=int(payload.get("start_step", 0) or 0),
                end_step=int(payload.get("end_step", 0) or 0),
                ego_id=str(payload.get("ego_id") or ""),
                max_duration_seconds=max_transfer_duration,
            )
        except (OSError, EOFError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        transfer_status = self.cosmos.status().get("transfer") or {}
        if not transfer_status.get("model_loaded"):
            return {"ok": False, "error": "Resident Cosmos Transfer2.5 service is not ready"}

        job_id = f"transfer_replay_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        name = self._safe_name(str(payload.get("experiment_name") or target.stem), fallback="transfer_replay")
        output_root = self.root / "output" / "cosmos" / "replay_jobs" / job_id
        public_window = {key: value for key, value in window.items() if key != "map_state"}
        public_window["semantic_quality"] = (window.get("map_state") or {}).get("semantic_quality") or {}
        info = {
            "id": job_id,
            "kind": "cosmos_transfer",
            "name": name,
            "backend_model": "cosmos_transfer2.5",
            "process": None,
            "port": 0,
            "url": f"/?view=experiment&experiment_id={quote(job_id)}",
            "gpu_id": ",".join(self.cosmos.transfer_gpus),
            "map_path": str((self._citynde_scenario_metadata(target) or {}).get("map_path") or ""),
            "init_mode": "replay_window",
            "total_step": int(window["source_steps"]),
            "max_sim_time": float(window["duration_seconds"]),
            "sim_resolution": 1.0 / float(window["source_fps"]),
            "save_file": self._repo_rel(target),
            "output_dir": self._repo_rel(output_root),
            "scenario": self._repo_rel(target),
            "derived_from_path": self._repo_rel(target),
            "last_status": {
                "run_state": "running",
                "progress": 0.0,
                "step": 0,
                "vehicles": int(window["persistent_vehicle_count"]),
            },
            "last_step": 0,
            "last_vehicles": int(window["persistent_vehicle_count"]),
            "started_at": _now_text(),
            "carla_enabled": False,
            "carla_state": "disabled",
        }
        with self._lock:
            self._experiments[job_id] = info
        snapshot = self.snapshot(job_id, info)
        self.experiment_store.upsert(snapshot, config={**payload, "recording_window": public_window})
        self._set_world_job(
            job_id,
            stage="scene_export",
            progress=0.02,
            message="Validating replay window and exporting the seven-camera scene",
            payload={"scenario": self._repo_rel(target), "recording_window": public_window},
        )
        thread = threading.Thread(
            target=self._transfer_replay_worker,
            args=(job_id, target, window, dict(payload)),
            name=f"TransferReplay-{job_id}",
            daemon=True,
        )
        self._world_cancel_events[job_id] = threading.Event()
        self._world_threads[job_id] = thread
        thread.start()
        return {"ok": True, "experiment": snapshot, "viewer_url": info["url"], "recording_window": public_window}

    def _resolve_recording_reference(self, value: str | Path) -> Path:
        path = Path(str(value or "")).expanduser()
        candidates = [path] if path.is_absolute() else [self.root / path, self.citynde_root / path]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        return candidates[0].resolve()

    @staticmethod
    def _traffic_stream_frame(path: Path, index: int) -> dict:
        with path.open("r", encoding="utf-8") as stream:
            for frame_index, line in enumerate(stream):
                if not line.strip():
                    continue
                if frame_index == index:
                    payload = json.loads(line)
                    return payload if isinstance(payload, dict) else {}
        return {}

    @staticmethod
    def _traffic_stream_at_time(path: Path, target_seconds: float) -> dict:
        target_seconds = max(0.0, float(target_seconds))
        best: dict[str, Any] = {}
        best_delta = math.inf
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    continue
                sim_time = float(payload.get("sim_time", 0.0) or 0.0)
                delta = abs(sim_time - target_seconds)
                if delta < best_delta:
                    best = payload
                    best_delta = delta
                if sim_time > target_seconds and delta > best_delta:
                    break
        return best

    @staticmethod
    def _extract_video_frame(
        source: Path,
        target: Path,
        timestamp: float,
        *,
        source_fps: int = 30,
    ) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        frame_index = max(0, int(round(float(timestamp) * int(source_fps))))
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "1", "-filter_threads", "1",
            "-i", str(source), "-vf", f"select=eq(n\\,{frame_index})",
            "-frames:v", "1", "-an", str(target),
        ]
        failure = ""
        for attempt in range(3):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                return target
            failure = (result.stderr or result.stdout or "").strip()
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))
        detail = f": {failure[-1200:]}" if failure else ""
        raise RuntimeError(
            f"Failed to extract frame {frame_index} from replay appearance video "
            f"{source} after 3 attempts{detail}"
        )

    def _automatic_replay_anchor(
        self,
        recording_path: Path,
        window: dict,
        output_root: Path,
        request: dict,
    ) -> dict:
        """Use exact prior RGB when possible, otherwise require a pose-matched catalog anchor."""
        recording_path = recording_path.resolve()
        records = self.experiment_store.list()
        with self._lock:
            active = [
                {**info, "id": experiment_id}
                for experiment_id, info in self._experiments.items()
            ]
        seen: set[str] = set()
        for record in [*active, *records]:
            source_id = str(record.get("id") or "")
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            save_file = str(record.get("save_file") or "").strip()
            if not save_file or self._resolve_recording_reference(save_file) != recording_path:
                continue
            source_root = self.root / "output" / "cosmos" / "experiments" / source_id
            source_video = source_root / "omnidreams" / "camera_front_wide_120fov.mp4"
            source_hdmap = source_root / "omnidreams" / "camera_front_wide_120fov_hdmap.mp4"
            source_traffic = source_root / "operational_traffic.ndjson"
            if (
                not source_video.is_file()
                or not source_hdmap.is_file()
                or not source_traffic.is_file()
            ):
                continue
            source_video_media = probe_video(source_video)
            source_hdmap_media = probe_video(source_hdmap)
            source_video_fps = float(source_video_media["fps"])
            source_hdmap_fps = float(source_hdmap_media["fps"])
            if abs(source_hdmap_fps - source_video_fps) > 0.02:
                continue
            expected_time = float(window["start_step"]) / float(window["source_fps"])
            required_anchor_frames = transfer_anchor_frame_indices(
                float(window["duration_seconds"]),
                start_seconds=expected_time,
                source_fps=source_video_fps,
            )
            conditioning_tail_frames = int(round(4.0 * source_video_fps / 10.0))
            if (
                not required_anchor_frames
                or max(required_anchor_frames) + conditioning_tail_frames
                >= int(source_video_media["frames"])
                or max(required_anchor_frames) + conditioning_tail_frames
                >= int(source_hdmap_media["frames"])
            ):
                continue
            source_frame = self._traffic_stream_frame(source_traffic, int(window["start_step"]))
            source_ego = source_frame.get("ego") if isinstance(source_frame.get("ego"), dict) else {}
            source_ego_id = str(source_ego.get("id") or source_frame.get("ego_id") or "")
            expected_ego = window.get("ego_pose") or {}
            if source_ego_id != str(window.get("ego_id") or ""):
                continue
            position_error = math.hypot(
                float(source_ego.get("x", 0.0)) - float(expected_ego.get("x", 0.0)),
                float(source_ego.get("y", 0.0)) - float(expected_ego.get("y", 0.0)),
            )
            heading_error = abs(
                (
                    float(source_ego.get("heading", 0.0))
                    - float(expected_ego.get("heading", 0.0))
                    + math.pi
                )
                % (2.0 * math.pi)
                - math.pi
            )
            source_time = float(source_frame.get("sim_time", -1.0) or 0.0)
            if (
                position_error > 0.25
                or math.degrees(heading_error) > 1.0
                or abs(source_time - expected_time) > 0.051
            ):
                continue
            image_path = self._extract_video_frame(
                source_video,
                output_root / "appearance" / "source_omnidreams.png",
                expected_time,
                source_fps=max(1, int(round(source_video_fps))),
            )
            hdmap_path = str(
                self._extract_video_frame(
                    source_hdmap,
                    output_root / "appearance" / "source_omnidreams_hdmap.png",
                    expected_time,
                    source_fps=max(1, int(round(source_hdmap_fps))),
                )
            )
            return {
                "selection": "same_recording_omnidreams_frame",
                "image_path": str(image_path),
                "control_path": hdmap_path,
                "geometry_min_f1": 0.65,
                "source_experiment_id": source_id,
                "source_video": str(source_video),
                "source_hdmap_video": str(source_hdmap),
                "source_video_frame": required_anchor_frames[0],
                "source_video_fps": source_video_fps,
                "source_video_frames": int(source_video_media["frames"]),
                "source_hdmap_frames": int(source_hdmap_media["frames"]),
                "required_anchor_frames": required_anchor_frames,
                "source_hdmap_frame": hdmap_path,
                "source_sim_time": source_time,
                "traffic_source": "selected_recording",
                "ego_id": source_ego_id,
                "position_error_m": round(position_error, 6),
                "heading_error_deg": round(math.degrees(heading_error), 6),
                "alignment_status": "exact_recording_frame",
            }

        map_path = str(window.get("map_path") or "")
        anchors = load_appearance_anchors(
            map_path,
            self.root / "assets" / "cosmos" / "appearance_anchors" / "catalog.json",
        )
        pose = dict(window.get("ego_pose") or {})
        match = select_pose_matched_anchor(
            [pose] if {"x", "y", "heading"}.issubset(pose) else [],
            anchors,
            seed=_world_transfer_seed(request),
        )
        if match is None:
            return {}
        anchor = match["anchor"]
        return {
            "selection": "map_pose_matched_catalog",
            "image_path": str(anchor["image_path"]),
            "control_path": str(anchor["control_path"]),
            "anchor_id": str(anchor.get("id") or ""),
            "traffic_source": "selected_recording",
            "ego_id": str(window.get("ego_id") or ""),
            "position_error_m": round(float(match["position_error_m"]), 6),
            "heading_error_deg": round(float(match["heading_error_deg"]), 6),
            "alignment_status": "pose_matched_pending_control_check",
        }

    def _run_segmented_transfer_replay(
        self,
        experiment_id: str,
        recording_path: Path,
        window: dict,
        request: dict,
        controls: dict[str, Path],
        output_root: Path,
        initial_anchor: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Path], Path, dict[str, Any]]:
        """Generate long front-view replay with five-frame native-window chaining."""
        duration = float(window["duration_seconds"])
        plan = transfer_segment_plan(duration)
        segments = list(plan["segments"])
        if len(segments) < 2:
            raise ValueError("Segmented Transfer replay requires more than one native window")
        if str(initial_anchor.get("selection") or "") != "same_recording_omnidreams_frame":
            raise ValueError("Segmented Transfer replay requires exact same-recording RGB anchors")

        base_seed = _world_transfer_seed(request)
        num_steps = max(1, int(request.get("world_transfer_steps", 35) or 35))
        prompt = str(request.get("world_prompt") or DEFAULT_PROMPT)
        segment_paths: dict[str, list[Path]] = {"front_wide": []}
        segment_frames: list[int] = []
        segment_reports: list[dict[str, Any]] = []
        generation_seconds = 0.0
        overlap_frames = int(plan["overlap_frames"])

        for segment in segments:
            index = int(segment["index"])
            start_frame = int(segment["start_frame"])
            output_frames = int(segment["output_frames"])
            segment_root = output_root / "segments" / f"{index:02d}"
            segment_controls = slice_and_pad_controls(
                controls,
                segment_root / "controls",
                start_frame=start_frame * 3,
            )
            anchor = dict(initial_anchor)
            conditioning_source = Path(str(anchor["source_video"]))
            source_hdmap = Path(str(anchor.get("source_hdmap_video") or ""))
            if not source_hdmap.is_file():
                raise FileNotFoundError(
                    "Same-recording OmniDreams HD-map video is unavailable for segmented replay"
                )
            source_fps = float(anchor.get("source_video_fps", 30.0) or 30.0)
            source_frame = int(anchor.get("source_video_frame", 0) or 0)
            conditioning_start = (
                int(round(source_frame * 10.0 / source_fps)) + start_frame
            )
            conditioning_timestamp = conditioning_start / 10.0
            anchor["image_path"] = str(
                self._extract_video_frame(
                    conditioning_source,
                    segment_root / "appearance" / "source_omnidreams.png",
                    conditioning_timestamp,
                    source_fps=max(1, int(round(source_fps))),
                )
            )
            anchor["control_path"] = str(
                self._extract_video_frame(
                    source_hdmap,
                    segment_root / "appearance" / "source_omnidreams_hdmap.png",
                    conditioning_timestamp,
                    source_fps=max(1, int(round(source_fps))),
                )
            )
            anchor = verify_transfer_anchor_geometry(
                anchor,
                segment_controls["camera_front_wide_120fov"],
            )
            conditioning_selection = "same_recording_omnidreams_five_frame_prefix"
            anchor.update(
                {
                    "segment_index": index,
                    "segment_start_frame": start_frame,
                    "segment_start_seconds": float(segment["start_seconds"]),
                    "conditioning_selection": conditioning_selection,
                    "conditioning_source": str(conditioning_source),
                    "conditioning_start_model_frame": conditioning_start,
                    "conditioning_timestamp_seconds": conditioning_timestamp,
                    "conditional_frames": overlap_frames,
                }
            )
            anchor_path = segment_root / "appearance" / "selection.json"
            anchor_path.parent.mkdir(parents=True, exist_ok=True)
            anchor_path.write_text(
                json.dumps(anchor, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            prepared_input = prepare_transfer_conditioning_video(
                conditioning_source,
                segment_root / "seed_input" / "front_wide_conditioning.mp4",
                start_model_frame=conditioning_start,
                conditional_frames=overlap_frames,
                frames=87,
            )
            input_paths = {"camera_front_wide_120fov": prepared_input}
            segment_name = f"replay_{experiment_id}_segment_{index:02d}"
            spec_path = segment_root / "transfer_spec.json"
            write_transfer_spec(
                spec_path,
                name=segment_name,
                controls=segment_controls,
                prompt=prompt,
                duration_seconds=output_frames / 10.0,
                num_steps=num_steps,
                seed=base_seed,
                input_paths=input_paths,
                num_conditional_frames=overlap_frames,
            )
            self._set_world_job(
                experiment_id,
                stage="transfer_segmented",
                progress=0.52 + 0.34 * index / max(1, len(segments)),
                message=f"Generating Transfer native window {index + 1}/{len(segments)}",
                payload={"transfer_segment_plan": plan, "active_segment": segment},
            )
            raw_root = segment_root / "transfer_raw"
            job = self._run_transfer_job(
                spec_path,
                raw_root,
                job_id=f"replay-{experiment_id}-segment-{index:02d}",
                experiment_id=experiment_id,
            )
            raw_views = discover_transfer_views(
                raw_root,
                segment_name,
                views=["front_wide"],
            )
            views = trim_views(
                raw_views,
                segment_root / "videos",
                frames=output_frames,
                fps=10,
            )
            qa = analyze_group(
                list(views.values()),
                segment_root / "qa",
                expected_duration=output_frames / 10.0,
                expected_fps=10.0,
                quality_profile="generated_driving_i2v5_window",
            )
            if not qa.get("passed"):
                errors = [
                    error
                    for report in qa.get("views") or []
                    for error in report.get("errors") or []
                ]
                raise RuntimeError(
                    f"Transfer native window {index + 1} failed quality checks: "
                    + ("; ".join(errors[:4]) or "unknown visual-quality failure")
                )
            segment_paths["front_wide"].append(views["front_wide"])
            segment_frames.append(output_frames)
            generation_seconds += float(job.get("generation_seconds", 0.0) or 0.0)
            segment_reports.append(
                {
                    **segment,
                    "seed": base_seed,
                    "anchor": anchor,
                    "job": job,
                    "quality": qa,
                    "video": str(views["front_wide"]),
                }
            )

        final_views: dict[str, Path] = {}
        for view, paths in segment_paths.items():
            target = output_root / "videos" / f"{view}.mp4"
            final_views[view] = stitch_transfer_segments(
                paths,
                target,
                segment_frames=segment_frames,
                overlap_frames=int(plan["overlap_frames"]),
                target_frames=int(plan["target_frames"]),
                fps=10,
                transition="crossfade",
            )
        boundary_quality = assess_transfer_crossfade_boundaries(
            analyze_transfer_segment_boundaries(
                segment_paths["front_wide"],
                output_root / "segments" / "qa",
                overlap_frames=int(plan["overlap_frames"]),
            )
        )
        manifest = {
            "schema": "denseworld.transfer-segmented-replay.v1",
            "strategy": "same_recording_five_frame_anchors_with_crossfade",
            "plan": plan,
            "base_seed": base_seed,
            "num_steps": num_steps,
            "generation_seconds": round(generation_seconds, 3),
            "boundary_quality": boundary_quality,
            "segments": segment_reports,
        }
        manifest_path = output_root / "segments" / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not boundary_quality.get("crossfade_acceptable"):
            errors = list(boundary_quality.get("crossfade_errors") or [])
            raise RuntimeError(
                "Transfer time-aligned windows are too different for a clean cross-fade: "
                + ("; ".join(errors[:4]) or "unknown boundary-quality failure")
                + f". Report: {manifest_path}"
            )
        aggregate_job = {
            "id": f"replay-{experiment_id}-segmented",
            "run_state": "completed",
            "generation_seconds": round(generation_seconds, 3),
            "segment_count": len(segment_reports),
            "segments": [report["job"] for report in segment_reports],
        }
        return aggregate_job, final_views, manifest_path, plan

    def _transfer_replay_worker(
        self,
        experiment_id: str,
        recording_path: Path,
        window: dict,
        request: dict,
    ) -> None:
        started_total = time.perf_counter()
        artifacts: list[dict] = []
        output_root = self.root / "output" / "cosmos" / "replay_jobs" / experiment_id
        view_mode = str(request.get("transfer_view_mode") or "front").strip().lower()
        replay_cameras = (
            list(CAMERAS)
            if view_mode == "multiview"
            else ["camera_front_wide_120fov"]
        )
        try:
            output_root.mkdir(parents=True, exist_ok=True)
            scene_root = output_root / "rds_hq"
            clip_id = f"replay-{experiment_id}"
            started = time.perf_counter()
            export_report = export_citynde_scene(
                recording_path,
                scene_root,
                clip_id=clip_id,
                source_steps=int(window["source_steps"]),
                source_fps=float(window["source_fps"]),
                target_fps=30,
                start_step=int(window.get("recording_start_step", window["start_step"])),
                ego_id=str(window["ego_id"]),
                map_state=window.get("map_state") or {},
            )
            effective_prompt = scene_prompt(
                export_report,
                str(request.get("world_prompt") or ""),
            )
            effective_transfer_prompt = scene_prompt(
                export_report,
                str(
                    request.get("world_transfer_prompt")
                    or request.get("world_prompt")
                    or ""
                ),
            )
            effective_transfer_negative_prompt = str(
                request.get("world_transfer_negative_prompt") or DEFAULT_NEGATIVE_PROMPT
            ).strip()
            export_report["effective_prompt"] = effective_prompt
            export_report["effective_transfer_prompt"] = effective_transfer_prompt
            export_report["effective_transfer_negative_prompt"] = (
                effective_transfer_negative_prompt
            )
            (scene_root / "trafficwm_export_report.json").write_text(
                json.dumps(export_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "replay_scene_export_report",
                    scene_root / "trafficwm_export_report.json",
                    mime_type="application/json",
                )
            )
            self._set_world_job(
                experiment_id,
                stage="control_render",
                progress=0.22,
                message=(
                    "Rendering seven synchronized 30 Hz control videos"
                    if view_mode == "multiview"
                    else "Rendering the front-wide 30 Hz control video"
                ),
                payload={"scene_export": export_report, "view_mode": view_mode, "artifacts": artifacts},
                timing=("scene_export_seconds", time.perf_counter() - started),
            )
            control_root = output_root / "controls"
            render_result = self.cosmos.render_controls(
                scene_root,
                control_root,
                clip_id=clip_id,
                cameras=replay_cameras,
            )
            controls = control_paths(control_root, clip_id, cameras=replay_cameras)
            control_qa = analyze_group(
                list(controls.values()),
                output_root / "qa" / "controls",
                expected_duration=float(export_report["output_frames"]) / 30.0,
                expected_fps=30.0,
                quality_profile="semantic_control",
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "replay_control_grid",
                    Path(control_qa["contact_sheet"]),
                    mime_type="image/jpeg",
                )
            )
            duration = float(window["duration_seconds"])
            frame_plan = transfer_frame_plan(duration)
            transfer_controls = pad_controls(
                controls,
                output_root / "controls_transfer_window",
                minimum_frames=int(frame_plan["control_frames_30fps"]),
                fps=30,
            )
            replay_input_paths: dict[str, Path] = {}
            generation_strategy = "official_autoregressive"
            seed_image_value = str(request.get("world_seed_image") or "").strip()
            anchor_metadata: dict[str, Any] = {}
            if not seed_image_value and view_mode == "front":
                anchor_metadata = self._automatic_replay_anchor(
                    recording_path,
                    window,
                    output_root,
                    request,
                )
                seed_image_value = str(anchor_metadata.get("image_path") or "")
            if seed_image_value:
                seed_image = Path(seed_image_value).expanduser()
                if not seed_image.is_absolute():
                    seed_image = self.root / seed_image
                seed_image = seed_image.resolve()
                if not seed_image.is_file():
                    raise FileNotFoundError(
                        f"Transfer replay appearance anchor does not exist: {seed_image}"
                    )
                if view_mode == "multiview":
                    raise ValueError(
                        "A single appearance anchor can only condition front-view Transfer replay"
                    )
                if not anchor_metadata:
                    anchor_metadata = {
                        "selection": "explicit_user_anchor",
                        "image_path": str(seed_image),
                        "traffic_source": "selected_recording",
                        "alignment_status": "unverified_external_anchor",
                    }
                if not str(anchor_metadata.get("control_path") or "").strip():
                    generated_control = generated_anchor_control_path(seed_image)
                    if generated_control is not None:
                        anchor_metadata["control_path"] = str(generated_control)
                anchor_metadata = verify_transfer_anchor_geometry(
                    anchor_metadata,
                    controls["camera_front_wide_120fov"],
                )
                anchor_manifest_path = output_root / "appearance" / "selection.json"
                anchor_manifest_path.parent.mkdir(parents=True, exist_ok=True)
                anchor_manifest_path.write_text(
                    json.dumps(anchor_metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_appearance_selection",
                        anchor_manifest_path,
                        mime_type="application/json",
                        metadata=anchor_metadata,
                    )
                )
            generation_strategy = transfer_replay_strategy(
                frame_plan,
                view_mode=view_mode,
                anchor_selection=str(anchor_metadata.get("selection") or ""),
                requested=str(request.get("world_transfer_long_strategy") or "auto"),
            )
            segmented_replay = generation_strategy == "segmented_exact_anchors"
            if seed_image_value and not segmented_replay:
                condition_frames = int(frame_plan["control_frames_30fps"])
                prepared_input = prepare_transfer_input_media(
                    seed_image,
                    output_root / "seed_input" / "front_wide_anchor.mp4",
                    frames=condition_frames,
                )
                replay_input_paths["camera_front_wide_120fov"] = prepared_input
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_input_video",
                        prepared_input,
                        mime_type="video/mp4",
                        metadata={
                            "source": str(seed_image),
                            "fps": 30,
                            "frames": condition_frames,
                            "conditional_frames": 1,
                            "appearance_anchor": anchor_metadata,
                        },
                    )
                )
            self._set_world_job(
                experiment_id,
                stage="transfer_segmented" if segmented_replay else "transfer_full",
                progress=0.52,
                message=(
                    f"Generating time-aligned five-frame native windows for {duration:g}s replay"
                    if segmented_replay
                    else (
                        f"Generating {duration:g}s Transfer2.5 video for seven views"
                        if view_mode == "multiview"
                        else f"Generating {duration:g}s front-wide Transfer2.5 video"
                    )
                ),
                payload={
                    "control_quality": control_qa,
                    "transfer_frame_plan": frame_plan,
                    "view_mode": view_mode,
                    "appearance_anchor": anchor_metadata,
                    "generation_strategy": generation_strategy,
                    "artifacts": artifacts,
                },
                timing=("control_render_seconds", float(render_result["seconds"])),
            )
            segmented_manifest: Path | None = None
            if segmented_replay:
                transfer_job, views, segmented_manifest, segment_plan = (
                    self._run_segmented_transfer_replay(
                        experiment_id,
                        recording_path,
                        window,
                        {**request, "world_prompt": effective_transfer_prompt},
                        controls,
                        output_root,
                        anchor_metadata,
                    )
                )
                frame_plan = {**frame_plan, "segmented": segment_plan}
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_replay_segment_manifest",
                        segmented_manifest,
                        mime_type="application/json",
                    )
                )
            else:
                transfer_name = f"replay_{experiment_id}"
                spec_path = output_root / "transfer_spec.json"
                write_transfer_spec(
                    spec_path,
                    name=transfer_name,
                    controls=transfer_controls,
                    prompt=effective_transfer_prompt,
                    duration_seconds=duration,
                    num_steps=max(1, int(request.get("world_transfer_steps", 35) or 35)),
                    seed=_world_transfer_seed(request),
                    input_paths=replay_input_paths,
                )
                raw_root = output_root / "transfer_raw"
                transfer_job = self._run_transfer_job(
                    spec_path,
                    raw_root,
                    job_id=f"replay-{experiment_id}",
                    experiment_id=experiment_id,
                )
                raw_views = discover_transfer_views(
                    raw_root,
                    transfer_name,
                    views=[VIEW_KEYS[camera] for camera in replay_cameras],
                )
                views = trim_views(
                    raw_views,
                    output_root / "videos",
                    frames=int(frame_plan["target_frames"]),
                    fps=10,
                )
            quality = analyze_group(
                list(views.values()),
                output_root / "qa" / "transfer",
                expected_duration=duration,
                expected_fps=10.0,
                quality_profile="generated_driving",
            )
            if segmented_manifest is not None:
                manifest_payload = json.loads(
                    segmented_manifest.read_text(encoding="utf-8")
                )
                manifest_payload["final_output_quality"] = quality
                manifest_payload["passed"] = bool(quality.get("passed")) and bool(
                    (manifest_payload.get("boundary_quality") or {}).get(
                        "crossfade_acceptable"
                    )
                )
                segmented_manifest.write_text(
                    json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if segmented_replay and not quality.get("passed"):
                errors = [
                    error
                    for report in quality.get("views") or []
                    for error in report.get("errors") or []
                ]
                raise RuntimeError(
                    "Segmented Transfer replay failed final quality checks: "
                    + ("; ".join(errors[:4]) or "unknown visual-quality failure")
                )
            replay_playback_proxy = create_playback_proxy(
                views["front_wide"],
                output_root / "playback" / "transfer_replay_front_wide_30fps.mp4",
                duration_seconds=duration,
                fps=30,
            )
            for view, path in views.items():
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        f"transfer_replay_{view}",
                        path,
                        mime_type="video/mp4",
                        metadata={
                            "view": view,
                            "derived_from_path": self._repo_rel(recording_path),
                            "fps": 10,
                            "frames": int(frame_plan["target_frames"]),
                            "source_start_step": int(window["start_step"]),
                            "source_end_step": int(window["end_step"]),
                            "recording_start_step": int(
                                window.get("recording_start_step", window["start_step"])
                            ),
                            "appearance_anchor": anchor_metadata,
                            "generation_strategy": (
                                "same_recording_five_frame_anchors_with_crossfade"
                                if segmented_replay
                                else "official_autoregressive"
                            ),
                        },
                    )
                )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "transfer_replay_front_wide_smooth",
                    replay_playback_proxy,
                    mime_type="video/mp4",
                    metadata={
                        "view": "front_wide",
                        "derived_from_path": self._repo_rel(recording_path),
                        "native_fps": 10,
                        "display_fps": 30,
                        "interpolation": "frame_blend",
                    },
                )
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "transfer_replay_qa",
                    output_root / "qa" / "transfer" / "video_qa.json",
                    mime_type="application/json",
                )
            )
            self._set_world_job(
                experiment_id,
                stage="transfer_full",
                run_state="completed",
                progress=1.0,
                message=(
                    "Replay range and all seven Transfer videos are complete"
                    if view_mode == "multiview"
                    else "Replay range and the front-wide Transfer video are complete"
                ),
                payload={
                    "transfer_job": transfer_job,
                    "transfer_quality": quality,
                    "transfer_frame_plan": frame_plan,
                    "generation_strategy": (
                        "independent_native_windows"
                        if segmented_replay
                        else "official_autoregressive"
                    ),
                    "artifacts": artifacts,
                },
                timing=("transfer_generation_seconds", float(transfer_job.get("generation_seconds", 0.0) or 0.0)),
            )
            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is not None:
                info["last_status"] = {
                    **(info.get("last_status") or {}),
                    "run_state": "completed",
                    "progress": 1.0,
                    "step": int(window["source_steps"]),
                    "experiment_completed": True,
                }
                info["output_dir"] = self._repo_rel(output_root)
                self.experiment_store.upsert(self.snapshot(experiment_id, info))
        except WorldJobCancelled as exc:
            self._set_world_job(
                experiment_id,
                stage="stopped",
                run_state="stopped",
                progress=0.0,
                message="Transfer replay generation stopped",
                payload={"artifacts": artifacts, "termination_reason": str(exc)},
                timing=("end_to_end_seconds", time.perf_counter() - started_total),
            )
            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is not None:
                info["last_status"] = {
                    **(info.get("last_status") or {}),
                    "run_state": "stopped",
                    "paused": False,
                    "termination_reason": str(exc),
                }
                self.experiment_store.upsert(self.snapshot(experiment_id, info))
        except Exception as exc:
            self._set_world_job(
                experiment_id,
                stage="transfer_full",
                run_state="error",
                progress=0.0,
                message="Transfer replay generation failed",
                error=str(exc),
                payload={"artifacts": artifacts},
                timing=("end_to_end_seconds", time.perf_counter() - started_total),
            )
            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is not None:
                info["last_status"] = {
                    **(info.get("last_status") or {}),
                    "run_state": "error",
                    "last_error": str(exc),
                }
                self.experiment_store.upsert(self.snapshot(experiment_id, info))
        finally:
            self._world_threads.pop(experiment_id, None)
            self._world_cancel_events.pop(experiment_id, None)

    def _recording_path(self, experiment_id: str) -> Path:
        with self._lock:
            info = self._experiments.get(experiment_id)
        if info is None:
            raise RuntimeError("Experiment is no longer active")
        path = Path(str(info.get("save_file") or ""))
        if path.is_absolute():
            return path.resolve()
        repo_path = (self.root / path).resolve()
        if repo_path.exists() or str(path).startswith(("algorithm_sources/", "output/")):
            return repo_path
        return (self.citynde_root / path).resolve()

    def _world_pipeline_worker(self, experiment_id: str, request: dict) -> None:
        pipeline_started = time.perf_counter()
        artifacts: list[dict] = []
        traffic_activated = False
        anchor_thread: threading.Thread | None = None
        anchor_stop_event: threading.Event | None = None
        anchor_result: dict[str, Any] | None = None
        external_anchor_manifest: Path | None = None
        try:
            seed_backend = _world_seed_backend(request)
            seed_alignment_mode = _world_seed_alignment_mode(request)
            if bool(request.get("world_existing_seed_gate")):
                # Reusable scenarios already start at their validated RGB/state
                # boundary and do not have a generated warmup timeline to rewind.
                seed_alignment_mode = SEED_ALIGNMENT_TERMINAL_CONTINUE
            status, map_state = self._wait_for_world_seed_state(
                experiment_id,
                require_dreams=bool(request.get("world_dreams_enabled", True)),
                require_transfer=(
                    not bool(request.get("world_existing_seed_gate"))
                    and seed_backend == "transfer2.5"
                ),
            )
            pipeline_root = self.root / "output" / "cosmos" / "experiments" / experiment_id
            pipeline_root.mkdir(parents=True, exist_ok=True)
            map_state_path = pipeline_root / "map_state.json"
            map_state_path.write_text(json.dumps(map_state, ensure_ascii=False, indent=2), encoding="utf-8")
            backend_model = str(status.get("backend_model") or "cnde").strip().lower()
            warmup_frames_path = Path(str(status.get("warmup_frames_file") or "")).resolve()
            if not warmup_frames_path.is_file():
                raise FileNotFoundError(f"{backend_model} warmup traffic frames are incomplete")
            warmup_frames = json.loads(warmup_frames_path.read_text(encoding="utf-8"))
            source_steps = max(1, int(status.get("warmup_frames") or len(warmup_frames)))
            transfer_window_path = pipeline_root / "conditioning" / "warmup_transfer_window.pkl"
            source_fps = 10.0
            if backend_model == "neuralnde":
                normalized_source_fps = float(status.get("warmup_source_fps") or 25.0)
                normalized_recording_path = (
                    pipeline_root / "conditioning" / "neuralnde_warmup_10hz.pkl"
                )
                normalized_report = traffic_frames_to_recording(
                    warmup_frames,
                    map_state,
                    normalized_recording_path,
                    source_fps=source_fps,
                    duration_seconds=float(status.get("raw_sim_time") or 1.0),
                )
                warmup_pickle = normalized_recording_path
                source_steps = int(normalized_report["recording_frames"])
            else:
                normalized_source_fps = 10.0
                normalized_report = None
                warmup_pickle = Path(str(status.get("warmup_save_file") or "")).resolve()
                if not warmup_pickle.is_file():
                    raise FileNotFoundError("CityNDE warmup recording is incomplete")
            transfer_window_report = prepare_citynde_transfer_window(
                warmup_pickle,
                transfer_window_path,
                real_source_steps=source_steps,
                target_source_steps=max(source_steps, TRANSFER_WINDOW_SOURCE_STEPS),
                source_fps=source_fps,
            )
            if normalized_report is not None:
                transfer_window_report["normalized_source"] = normalized_report
                transfer_window_report["native_traffic_fps"] = normalized_source_fps
            transfer_source_steps = int(transfer_window_report["native_source_steps"])
            warmup_boundary_index = (
                0
                if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                else -1
            )
            warmup_ego_id = str(
                ((warmup_frames or [{}])[warmup_boundary_index].get("ego") or {}).get("id")
                or ""
            )
            open_ended_world = _world_video_runs_until_stopped(request)
            duration = 0.0 if open_ended_world else _world_video_duration_seconds(request)
            follow_traffic = _world_video_follows_traffic(request)
            world_route_crop_path = _world_route_crop_path(status, map_state)
            seed_map_radius_m, replay_map_radius_m = _world_map_radii(
                request,
                duration if duration > 0.0 else 10000.0,
                route_extent_m=float(status.get("world_loop_route_extent_m") or 0.0),
                route_corridor=bool(world_route_crop_path),
            )
            if (
                bool(request.get("world_loop_ego"))
                and (open_ended_world or duration >= 120.0)
                and not world_route_crop_path
            ):
                raise RuntimeError(
                    "Long-horizon CityNDE world generation requires a reachable ego loop "
                    "before Transfer seeding; refusing an unbounded whole-map ClipGT export"
                )

            self._set_world_job(
                experiment_id,
                stage="scene_export",
                progress=0.08,
                message="Exporting seven-camera RDS-HQ scene with traffic controls",
            )
            started = time.perf_counter()
            scene_root = pipeline_root / "rds_hq"
            clip_id = f"warmup-{experiment_id}"
            export_report = export_citynde_scene(
                transfer_window_path,
                scene_root,
                clip_id=clip_id,
                source_steps=transfer_source_steps,
                source_fps=source_fps,
                target_fps=30,
                ego_id=warmup_ego_id or None,
                map_state=map_state,
                map_radius_m=seed_map_radius_m,
            )
            export_report["transfer_control_window"] = transfer_window_report
            export_report["seed_map_radius_m"] = seed_map_radius_m
            export_report["replay_map_radius_m"] = replay_map_radius_m
            if backend_model == "neuralnde":
                export_report["ego_route"] = {
                    **(export_report.get("ego_route") or {}),
                    "road_form": "roundabout",
                    "intersection_ahead": False,
                }
            effective_prompt = scene_prompt(
                export_report,
                str(request.get("world_prompt") or ""),
            )
            effective_transfer_prompt = scene_prompt(
                export_report,
                str(
                    request.get("world_transfer_prompt")
                    or request.get("world_prompt")
                    or ""
                ),
            )
            effective_transfer_negative_prompt = str(
                request.get("world_transfer_negative_prompt") or DEFAULT_NEGATIVE_PROMPT
            ).strip()
            export_report["effective_prompt"] = effective_prompt
            export_report["effective_transfer_prompt"] = effective_transfer_prompt
            export_report["effective_transfer_negative_prompt"] = (
                effective_transfer_negative_prompt
            )
            report_path = scene_root / "trafficwm_export_report.json"
            report_path.write_text(
                json.dumps(export_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            export_seconds = time.perf_counter() - started
            artifacts.append(self._add_world_artifact(experiment_id, "scene_export_report", report_path, mime_type="application/json"))
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "transfer_control_window_manifest",
                    transfer_window_path.with_suffix(".manifest.json"),
                    mime_type="application/json",
                    metadata=transfer_window_report,
                )
            )
            seed_image_value = str(request.get("world_seed_image") or "").strip()
            existing_seed_image: Path | None = None
            if seed_image_value:
                candidate_seed = Path(seed_image_value).expanduser()
                if not candidate_seed.is_absolute():
                    candidate_seed = self.root / candidate_seed
                candidate_seed = candidate_seed.resolve()
                if not _is_relative_to(candidate_seed, self.root):
                    raise ValueError("Existing scenario seed must be stored inside the workspace")
                media = probe_video(candidate_seed, count_frames=False)
                width = int(media.get("width", 0) or 0)
                height = int(media.get("height", 0) or 0)
                if width < 640 or height < 352:
                    raise ValueError(
                        f"Existing scenario seed is too small ({width}x{height}); expected at least 640x352"
                    )
                if abs(width / max(1, height) - 1280.0 / 704.0) > 0.12:
                    raise ValueError(
                        f"Existing scenario seed aspect ratio {width}:{height} does not match 1280:704"
                    )
                existing_seed_image = candidate_seed
            seed_mode = (
                "existing_scenario_frame"
                if existing_seed_image is not None
                else "single_view_transfer1_quality"
                if seed_backend == "transfer1"
                else "multiview_quality"
            )
            requested_seed_steps = max(1, int(request.get("world_transfer_steps", 35) or 35))
            seed_steps = requested_seed_steps
            seed_cameras = (
                ["camera_front_wide_120fov"]
                if seed_backend == "transfer1"
                else list(CAMERAS)
            )
            seed_view_keys = [VIEW_KEYS[camera] for camera in seed_cameras]
            self._set_world_job(
                experiment_id,
                stage="control_render",
                progress=0.16,
                message=(
                    "Reusing the exact scenario RGB frame; seed control rendering is skipped"
                    if existing_seed_image is not None
                    else "Rendering the native front HDMap control for Transfer1 Sample-AV"
                    if seed_backend == "transfer1"
                    else "Rendering a continuous native control window for seven seed cameras"
                ),
                payload={"scene_export": export_report, "seed_mode": seed_mode, "artifacts": artifacts},
                timing=("scene_export_seconds", export_seconds),
            )

            control_root = pipeline_root / "controls"
            render_result: dict[str, Any] = {"seconds": 0.0, "skipped": True}
            controls: dict[str, Path] = {}
            anchor_geometry: dict[str, Any] = (
                {
                    "status": "existing_scenario_frame",
                    "selection": "exact_recording_frame",
                    "conditioning": "omnidreams_first_frame",
                    "quality_tier": "recorded",
                    "views": ["front_wide"],
                    "conditional_rgb_frames": 1,
                    "image_path": str(existing_seed_image),
                    "reason": "The saved RGB frame belongs to this reusable scenario and bypasses Transfer seeding.",
                }
                if existing_seed_image is not None
                else {
                    "status": "official_control_only",
                    "selection": "none",
                    "conditioning": "control_to_video",
                    "quality_tier": "native",
                    "views": seed_view_keys,
                    "conditional_rgb_frames": 0,
                    "reason": (
                        "Transfer1 Sample-AV uses one front-view HDMap control and no RGB input."
                        if seed_backend == "transfer1"
                        else "Transfer uses one official joint multiview environment-to-world sample "
                        "with seven calibrated control videos and no RGB input."
                    ),
                }
            )
            if existing_seed_image is not None:
                control_qa = {
                    "schema": "denseworld.seed-control-skip.v1",
                    "passed": True,
                    "skipped": True,
                    "reason": "existing_scenario_frame",
                    "views": [],
                }
                transfer_controls: dict[str, Path] = {}
            else:
                if seed_backend == "transfer1":
                    render_result = render_transfer1_hdmap_control(
                        scene_root,
                        control_root,
                        clip_id=clip_id,
                        expected_frames=int(export_report["output_frames"]),
                    )
                else:
                    render_result = self.cosmos.render_controls(
                        scene_root,
                        control_root,
                        clip_id=clip_id,
                        cameras=seed_cameras,
                    )
                controls = control_paths(control_root, clip_id, cameras=seed_cameras)
                control_qa = analyze_group(
                    list(controls.values()),
                    pipeline_root / "qa" / "controls",
                    expected_duration=(int(export_report["output_frames"]) / 30.0),
                    expected_fps=30.0,
                    quality_profile="semantic_control",
                )
                artifacts.append(self._add_world_artifact(experiment_id, "control_grid", Path(control_qa["contact_sheet"]), mime_type="image/jpeg"))
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "control_qa",
                        pipeline_root / "qa" / "controls" / "video_qa.json",
                        mime_type="application/json",
                        metadata={"passed": bool(control_qa.get("passed"))},
                    )
                )
                if not control_qa.get("passed"):
                    errors = [
                        error
                        for view in control_qa.get("views") or []
                        for error in view.get("errors") or []
                    ]
                    raise RuntimeError(
                        "Transfer semantic controls failed QA: "
                        + ("; ".join(errors[:4]) or "unknown control-quality failure")
                    )
                transfer_controls = (
                    controls
                    if seed_backend == "transfer1"
                    else pad_controls(
                        controls,
                        pipeline_root / "controls_transfer_window",
                        minimum_frames=87,
                        fps=30,
                    )
                )
            appearance_manifest = {
                "schema": "denseworld.appearance-conditioning.v1",
                "seed_mode": seed_mode,
                "cached_anchor_enabled": False,
                "explicit_seed_image": existing_seed_image is not None,
                **anchor_geometry,
            }
            appearance_manifest_path = pipeline_root / "appearance" / "selection.json"
            appearance_manifest_path.parent.mkdir(parents=True, exist_ok=True)
            appearance_manifest_path.write_text(
                json.dumps(appearance_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "transfer_seed_appearance_selection",
                    appearance_manifest_path,
                    mime_type="application/json",
                    metadata=appearance_manifest,
                )
            )
            self._set_world_job(
                experiment_id,
                stage="transfer_seed",
                progress=0.28,
                message=(
                    "Validating the saved scenario first frame (Transfer seed is skipped)"
                    if existing_seed_image is not None
                    else "Cosmos Transfer1 Sample-AV is generating the front-view world seed (traffic is held at warmed t=0)"
                    if seed_backend == "transfer1"
                    else "Cosmos Transfer2.5 is jointly generating the synchronized seven-view world seed (traffic is held at warmed t=0)"
                ),
                payload={
                    "control_quality": control_qa,
                    "seed_map_radius_m": seed_map_radius_m,
                    "replay_map_radius_m": replay_map_radius_m,
                    "anchor_geometry": anchor_geometry,
                    "appearance_conditioning": appearance_manifest,
                    "seed_mode": seed_mode,
                    "world_seed_backend": seed_backend,
                    "world_seed_alignment_mode": seed_alignment_mode,
                    "transfer_expected_seconds": None,
                    "traffic_clock_state": "held_at_warmed_t0",
                    "artifacts": artifacts,
                },
                timing=("control_render_seconds", float(render_result["seconds"])),
            )

            transfer_seed = _world_transfer_seed(request)
            transfer_attempt_limit = max(
                1,
                min(
                    5,
                    int(request.get("world_transfer_seed_max_attempts", 3) or 3),
                ),
            )
            if seed_backend == "transfer1":
                transfer_attempt_limit = min(
                    transfer_attempt_limit,
                    max(1, int(os.environ.get("COSMOS_TRANSFER1_MAX_ATTEMPTS", "1"))),
                )
            attempts_root = pipeline_root / "transfer_seed_attempts"
            transfer_attempts: list[dict[str, Any]] = []
            transfer_job: dict[str, Any] = {}
            transfer_qa: dict[str, Any] = {}
            transfer_qa_path = pipeline_root / "qa" / "transfer_seed" / "video_qa.json"
            seed_frame: Path | None = None
            seed_views: dict[str, Path] = {}
            selected_spec_path: Path | None = None
            seed_frame_index = (
                0
                if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                else (
                    TRANSFER1_WARMUP_FRAME_INDEX
                    if seed_backend == "transfer1"
                    else WARMUP_TERMINAL_FRAME_INDEX
                )
            )
            if existing_seed_image is not None:
                seed_frame = pipeline_root / "seed" / "front_wide_terminal.png"
                seed_frame.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(existing_seed_image),
                        "-vf", "scale=1280:704:force_original_aspect_ratio=decrease,pad=1280:704:(ow-iw)/2:(oh-ih)/2",
                        "-frames:v", "1", str(seed_frame),
                    ],
                    check=True,
                )
                static_seed_video = pipeline_root / "seed_views" / "front_wide.mp4"
                static_seed_video.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-loop", "1", "-i", str(seed_frame),
                        "-t", "1", "-r", "10", "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                        "-pix_fmt", "yuv420p", str(static_seed_video),
                    ],
                    check=True,
                )
                seed_media = probe_video(static_seed_video)
                seed_views = {"front_wide": static_seed_video}
                transfer_job = {
                    "skipped": True,
                    "reason": "existing_scenario_frame",
                    "generation_seconds": 0.0,
                }
                transfer_qa = {
                    "schema": "denseworld.existing-seed-validation.v1",
                    "passed": True,
                    "transfer_skipped": True,
                    "source": str(existing_seed_image),
                    "normalized_frame": str(seed_frame),
                    "preview_video": str(static_seed_video),
                    "media": seed_media,
                }
                transfer_qa_path.parent.mkdir(parents=True, exist_ok=True)
                transfer_qa_path.write_text(
                    json.dumps(transfer_qa, ensure_ascii=False, indent=2), encoding="utf-8"
                )

            attempt_indices = (
                range(0) if existing_seed_image is not None else range(transfer_attempt_limit)
            )
            for attempt_index in attempt_indices:
                attempt_number = attempt_index + 1
                attempt_seed = (transfer_seed + attempt_index * 104729) % (2**31)
                attempt_root = attempts_root / f"attempt_{attempt_number:02d}"
                transfer_name = f"seed_{experiment_id}_attempt_{attempt_number:02d}"
                if seed_backend == "transfer1":
                    cancel_event = self._world_cancel_events.get(experiment_id)
                    candidate_job = run_transfer1_seed(
                        transfer_controls[seed_cameras[0]],
                        attempt_root,
                        output_name=transfer_name,
                        prompt=effective_transfer_prompt,
                        negative_prompt=effective_transfer_negative_prompt,
                        num_steps=seed_steps,
                        seed=attempt_seed,
                        cancelled=lambda: self._world_stop.is_set()
                        or bool(cancel_event is not None and cancel_event.is_set()),
                    )
                    candidate_spec_path = Path(candidate_job["spec_path"])
                    raw_views = {"front_wide": Path(candidate_job["output_video"])}
                    candidate_seed_frame = extract_transfer1_warmup_frame(
                        raw_views["front_wide"],
                        attempt_root
                        / (
                            "front_wide_opening.png"
                            if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                            else "front_wide_terminal.png"
                        ),
                        frame_index=seed_frame_index,
                    )
                    candidate_preview = create_transfer1_seed_preview(
                        raw_views["front_wide"],
                        attempt_root / "seed_views" / "front_wide.mp4",
                    )
                    candidate_seed_views = {"front_wide": candidate_preview}
                else:
                    candidate_spec_path = attempt_root / "transfer_seed_spec.json"
                    write_transfer_spec(
                        candidate_spec_path,
                        name=transfer_name,
                        controls=transfer_controls,
                        prompt=effective_transfer_prompt,
                        duration_seconds=1.0,
                        num_steps=seed_steps,
                        seed=attempt_seed,
                    )
                    candidate_output = attempt_root / "transfer_raw"
                    candidate_job = self._run_transfer_job(
                        candidate_spec_path,
                        candidate_output,
                        job_id=f"seed-{experiment_id}-attempt-{attempt_number:02d}",
                        experiment_id=experiment_id,
                    )
                    raw_views = discover_transfer_views(
                        candidate_output,
                        transfer_name,
                        views=seed_view_keys,
                    )
                    candidate_seed_frame = extract_seed_frame(
                        raw_views["front_wide"],
                        attempt_root
                        / (
                            "front_wide_opening.png"
                            if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                            else "front_wide_terminal.png"
                        ),
                        seed_frame_index,
                    )
                    candidate_seed_views = trim_views(
                        raw_views,
                        attempt_root / "seed_views",
                        frames=10,
                        fps=10,
                    )
                candidate_qa_dir = attempt_root / "qa"
                candidate_qa = analyze_group(
                    list(candidate_seed_views.values()),
                    candidate_qa_dir,
                    expected_duration=(
                        TRANSFER1_CONTAINER_SECONDS
                        if seed_backend == "transfer1"
                        else 1.0
                    ),
                    expected_fps=(
                        float(TRANSFER1_NATIVE_FPS)
                        if seed_backend == "transfer1"
                        else 10.0
                    ),
                    quality_profile="generated_driving_seed",
                )
                attempt_errors = [
                    error
                    for view in candidate_qa.get("views") or []
                    for error in view.get("errors") or []
                ]
                transfer_attempts.append(
                    {
                        "attempt": attempt_number,
                        "backend": seed_backend,
                        "seed": attempt_seed,
                        "num_steps": seed_steps,
                        "passed": bool(candidate_qa.get("passed")),
                        "errors": attempt_errors,
                        "quality": candidate_qa,
                        "spec_path": str(candidate_spec_path),
                        "generation_seconds": float(
                            candidate_job.get("generation_seconds", 0.0) or 0.0
                        ),
                        "cache_hit": bool(candidate_job.get("cache_hit", False)),
                        "cache_key": str(candidate_job.get("cache_key") or ""),
                        "cache_manifest": str(candidate_job.get("cache_manifest") or ""),
                    }
                )
                if not candidate_qa.get("passed"):
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            f"transfer_seed_attempt_{attempt_number:02d}_failed_qa",
                            candidate_qa_dir / "video_qa.json",
                            mime_type="application/json",
                            metadata={"seed": attempt_seed, "errors": attempt_errors},
                        )
                    )
                    self._set_world_job(
                        experiment_id,
                        stage="transfer_seed",
                        progress=0.28,
                        message=(
                            "Transfer seed failed strict QA; retrying with a deterministic "
                            f"alternate seed ({attempt_number}/{transfer_attempt_limit})"
                        ),
                        payload={"transfer_attempts": transfer_attempts, "artifacts": artifacts},
                    )
                    continue

                canonical_seed_frame = (
                    pipeline_root
                    / "seed"
                    / (
                        "front_wide_opening.png"
                        if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                        else "front_wide_terminal.png"
                    )
                )
                canonical_seed_frame.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate_seed_frame, canonical_seed_frame)
                canonical_seed_views_root = pipeline_root / "seed_views"
                canonical_seed_views_root.mkdir(parents=True, exist_ok=True)
                canonical_seed_views = {}
                for view, candidate_path in candidate_seed_views.items():
                    target = canonical_seed_views_root / f"{view}.mp4"
                    shutil.copy2(candidate_path, target)
                    canonical_seed_views[view] = target
                canonical_qa_dir = pipeline_root / "qa" / "transfer_seed"
                shutil.copytree(candidate_qa_dir, canonical_qa_dir, dirs_exist_ok=True)
                selected_spec_path = pipeline_root / "transfer_seed_spec.json"
                shutil.copy2(candidate_spec_path, selected_spec_path)
                seed_frame = canonical_seed_frame
                seed_views = canonical_seed_views
                transfer_qa = candidate_qa
                transfer_job = candidate_job
                break

            attempts_manifest = attempts_root / "manifest.json"
            attempts_manifest.parent.mkdir(parents=True, exist_ok=True)
            attempts_manifest.write_text(
                json.dumps(
                    {
                        "schema": "denseworld.transfer-seed-attempts.v1",
                        "experiment_id": experiment_id,
                        "max_attempts": transfer_attempt_limit,
                        "selected_attempt": next(
                            (
                                int(item["attempt"])
                                for item in transfer_attempts
                                if item.get("passed")
                            ),
                            None,
                        ),
                        "selected_spec_path": (
                            str(selected_spec_path) if selected_spec_path is not None else ""
                        ),
                        "seed_mode": seed_mode,
                        "world_seed_backend": seed_backend,
                        "world_seed_alignment_mode": seed_alignment_mode,
                        "seed_frame_index": seed_frame_index,
                        "transfer_skipped": existing_seed_image is not None,
                        "attempts": transfer_attempts,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "transfer_seed_attempt_manifest",
                    attempts_manifest,
                    mime_type="application/json",
                )
            )
            if seed_frame is None or not seed_views or not transfer_qa.get("passed"):
                errors = list((transfer_attempts or [{}])[-1].get("errors") or [])
                raise RuntimeError(
                    "Transfer seed failed strict driving-scene QA after "
                    f"{len(transfer_attempts)} attempts: "
                    + ("; ".join(errors[:4]) or "unknown visual-quality failure")
                    + (
                        ". Inspect the front HDMap control, Transfer1 log, and QA contact sheet."
                        if seed_backend == "transfer1"
                        else ". Inspect the seven-view controls and per-attempt QA contact sheets."
                    )
                )
            seed_native_duration = (
                TRANSFER1_CONTAINER_SECONDS
                if seed_backend == "transfer1" and existing_seed_image is None
                else 1.0
            )
            seed_native_fps = (
                TRANSFER1_NATIVE_FPS
                if seed_backend == "transfer1" and existing_seed_image is None
                else 10
            )
            seed_native_frames = (
                TRANSFER1_NATIVE_FRAMES
                if seed_backend == "transfer1" and existing_seed_image is None
                else 10
            )
            seed_display_frames = max(1, int(round(seed_native_duration * 30.0)))
            seed_playback_proxy = create_playback_proxy(
                seed_views["front_wide"],
                pipeline_root / "playback" / "transfer_seed_front_wide_30fps.mp4",
                duration_seconds=seed_native_duration,
                fps=30,
            )
            seed_artifact_prefix = (
                "existing_seed" if existing_seed_image is not None else "transfer_seed"
            )
            selected_transfer_seed = (
                int(transfer_attempts[-1]["seed"]) if transfer_attempts else None
            )
            for view, path in seed_views.items():
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        f"{seed_artifact_prefix}_{view}",
                        path,
                        mime_type="video/mp4",
                        metadata={
                            "view": view,
                            "fps": seed_native_fps,
                            "frames": seed_native_frames,
                            "seed_mode": seed_mode,
                            "num_steps": seed_steps,
                            "seed": selected_transfer_seed,
                            "native_frames": seed_native_frames,
                            "control_fps": 30,
                            "world_seed_alignment_mode": seed_alignment_mode,
                            "seed_frame_index": seed_frame_index,
                            "conditioning": (
                                "saved_scenario_rgb"
                                if existing_seed_image is not None
                                else "control_to_video"
                            ),
                        },
                    )
                )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    f"{seed_artifact_prefix}_front_wide_smooth",
                    seed_playback_proxy,
                    mime_type="video/mp4",
                    metadata={
                        "view": "front_wide",
                        "native_fps": seed_native_fps,
                        "display_fps": 30,
                        "frames": seed_display_frames,
                        "interpolation": "frame_blend",
                    },
                )
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    f"{seed_artifact_prefix}_frame",
                    seed_frame,
                    mime_type="image/png",
                    metadata={
                        "source": (
                            "saved_scenario_rgb"
                            if existing_seed_image is not None
                            else "native_transfer1_output"
                            if seed_backend == "transfer1"
                            else "native_transfer2.5_output"
                        ),
                        "frame_index": (
                            0
                            if existing_seed_image is not None
                            else seed_frame_index
                        ),
                        "warmup_time_seconds": (
                            0.0
                            if (
                                existing_seed_image is not None
                                or seed_alignment_mode
                                == SEED_ALIGNMENT_OPENING_RESTART
                            )
                            else TRANSFER1_WARMUP_SECONDS
                            if seed_backend == "transfer1"
                            else 1.0
                        ),
                        "world_seed_alignment_mode": seed_alignment_mode,
                        "operational_time_seconds": 0.0,
                    },
                )
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    f"{seed_artifact_prefix}_qa",
                    transfer_qa_path,
                    mime_type="application/json",
                )
            )
            self._set_world_job(
                experiment_id,
                stage="operational_traffic",
                progress=0.52,
                message=(
                    "Saved scenario seed is ready; operational traffic starts at t=0"
                    if existing_seed_image is not None
                    else "Transfer seed is ready; operational traffic starts at t=0"
                ),
                payload={
                    "transfer_job": transfer_job,
                    "transfer_attempts": transfer_attempts,
                    "transfer_quality": transfer_qa,
                    "artifacts": artifacts,
                },
                timing=(
                    "transfer_generation_seconds",
                    sum(float(item.get("generation_seconds", 0.0) or 0.0) for item in transfer_attempts),
                ),
            )

            with self._lock:
                info = self._experiments.get(experiment_id)
            if info is None:
                raise RuntimeError("Experiment was removed before world seed activation")
            if str(request.get("av_control_model") or "").upper() == "LEAD_TFV6_STREAM":
                live_preview = (
                    pipeline_root
                    / "omnidreams"
                    / "camera_front_wide_120fov_latest.jpg"
                )
                live_preview.parent.mkdir(parents=True, exist_ok=True)
                temporary_preview = live_preview.with_name(
                    f"{live_preview.stem}.tmp.jpg"
                )
                subprocess.run(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(seed_frame), "-frames:v", "1", "-q:v", "2",
                        str(temporary_preview),
                    ],
                    check=True,
                )
                temporary_preview.replace(live_preview)
            ego_id = str(export_report.get("ego_id") or "")
            operational_status = self._http_json(
                f"http://127.0.0.1:{info['port']}/status",
                timeout=2.0,
            ) or {}
            ego_id = operational_ego_id(
                ego_id,
                operational_status,
                av_enabled=bool(request.get("av_enabled")),
            )
            alignment_activation = self._http_json(
                f"http://127.0.0.1:{info['port']}/action",
                method="POST",
                payload={
                    "type": "world_seed_align",
                    "mode": seed_alignment_mode,
                },
                timeout=30.0,
            )
            if not alignment_activation or not alignment_activation.get("ok"):
                raise RuntimeError(
                    str(
                        (alignment_activation or {}).get("error")
                        or f"{backend_model} rejected the world-seed alignment mode"
                    )
                )
            traffic_path = pipeline_root / "operational_traffic.json"
            capture_result, capture_thread = self._start_world_traffic_capture(
                experiment_id,
                duration_seconds=None if open_ended_world else duration,
                ego_id=ego_id,
                output_path=traffic_path,
            )
            initial_deadline = time.monotonic() + 60.0
            while time.monotonic() < initial_deadline:
                traffic_frames = list(capture_result.get("frames") or [])
                if traffic_frames:
                    break
                if capture_result.get("done") and capture_result.get("error"):
                    raise RuntimeError(str(capture_result.get("error")))
                time.sleep(0.25)
            else:
                raise TimeoutError("Timed out capturing the warmed traffic-model t=0 state")

            first_sim_time = float(traffic_frames[0].get("sim_time", -1.0))
            if abs(first_sim_time) > 1e-6:
                raise RuntimeError(
                    f"Operational traffic must start from the warmed t=0 state, got {first_sim_time:.3f}s"
                )
            expected_boundary_frame = (
                warmup_frames[0]
                if seed_alignment_mode == SEED_ALIGNMENT_OPENING_RESTART
                else warmup_frames[-1]
            )
            seed_alignment_audit = audit_seed_traffic_boundary(
                expected_boundary_frame,
                traffic_frames[0],
                alignment_mode=seed_alignment_mode,
            )
            seed_alignment_audit["seed_frame"] = str(seed_frame)
            seed_alignment_audit["seed_frame_index"] = seed_frame_index
            seed_alignment_audit["child_audit"] = alignment_activation.get("audit")
            seed_alignment_audit_path = (
                pipeline_root / "qa" / "seed_traffic_alignment.json"
            )
            seed_alignment_audit_path.parent.mkdir(parents=True, exist_ok=True)
            seed_alignment_audit_path.write_text(
                json.dumps(seed_alignment_audit, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "seed_traffic_alignment",
                    seed_alignment_audit_path,
                    mime_type="application/json",
                    metadata={
                        "passed": bool(seed_alignment_audit["passed"]),
                        "alignment_mode": seed_alignment_mode,
                        "seed_frame_index": seed_frame_index,
                    },
                )
            )
            if not seed_alignment_audit["passed"]:
                raise RuntimeError(
                    "Operational traffic does not match the selected Transfer frame: "
                    f"ego={seed_alignment_audit['actual_ego_id']!r} "
                    f"(expected {seed_alignment_audit['expected_ego_id']!r}), "
                    f"missing={seed_alignment_audit['missing_actor_ids']}, "
                    f"unexpected={seed_alignment_audit['unexpected_actor_ids']}, "
                    f"violations={len(seed_alignment_audit['violations'])}"
                )

            world_sync_path = pipeline_root / "traffic_video_sync.json"
            if bool(request.get("world_dreams_enabled", True)):
                # One source frame after t=0 is enough to build ClipGT while the
                # first OmniDreams request publishes its exact chunk horizon.
                update_world_sync(
                    world_sync_path,
                    stage="starting_live_pipeline",
                    experiment_id=experiment_id,
                    requested_traffic_time=0.1,
                    generated_video_time=0.0,
                )

            activation = self._http_json(
                f"http://127.0.0.1:{info['port']}/action",
                method="POST",
                payload={
                    "type": "world_seed_ready",
                    "video": str(seed_views["front_wide"]),
                    "frame": str(seed_frame),
                    "alignment_mode": seed_alignment_mode,
                },
                timeout=10.0,
            )
            if not activation or not activation.get("ok"):
                raise RuntimeError(
                    str((activation or {}).get("error") or f"{backend_model} rejected the world seed")
                )
            traffic_activated = True

            initial_deadline = time.monotonic() + 60.0
            while time.monotonic() < initial_deadline:
                traffic_frames = list(capture_result.get("frames") or [])
                if len(traffic_frames) >= 2:
                    break
                if capture_result.get("done") and capture_result.get("error"):
                    raise RuntimeError(str(capture_result.get("error")))
                time.sleep(0.25)
            else:
                raise TimeoutError("Timed out waiting for live operational traffic frames")
            ego_id = str(capture_result.get("ego_id") or ego_id)
            traffic_stream_path = Path(str(capture_result.get("stream_path") or ""))
            operational_source_fps = (
                25.0 if backend_model == "neuralnde" else 10.0
            )
            operational_artifact = self._add_world_artifact(
                experiment_id,
                "operational_traffic",
                traffic_path,
                mime_type="application/json",
                metadata={"frames": len(traffic_frames), "ego_id": ego_id, "capture_stage": "running"},
            )
            artifacts.append(operational_artifact)
            artifacts.append(
                self._add_world_artifact(
                    experiment_id,
                    "operational_traffic_stream",
                    traffic_stream_path,
                    mime_type="application/x-ndjson",
                    metadata={"frames": len(traffic_frames), "ego_id": ego_id, "capture_stage": "running"},
                )
            )

            rollover_mode = str(
                request.get("world_omnidreams_rollover_mode") or "latest"
            ).strip().lower()
            segment_seconds = max(
                0.0,
                float(request.get("world_omnidreams_segment_seconds", 0.0) or 0.0),
            )
            if (
                bool(request.get("world_dreams_enabled", True))
                and rollover_mode == "transfer"
            ):
                if segment_seconds <= 0.0:
                    raise ValueError(
                        "Transfer-anchored OmniDreams requires a positive session segment"
                    )
                (
                    external_anchor_manifest,
                    anchor_result,
                    anchor_thread,
                    anchor_stop_event,
                ) = self._start_omnidreams_transfer_anchor_worker(
                    experiment_id,
                    capture_result=capture_result,
                    map_state=map_state,
                    ego_id=ego_id,
                    pipeline_root=pipeline_root,
                    effective_prompt=effective_prompt,
                    duration_seconds=None if open_ended_world else duration,
                    segment_seconds=segment_seconds,
                    source_fps=operational_source_fps,
                    map_radius_m=replay_map_radius_m,
                    world_sync_path=world_sync_path,
                    transfer_steps=max(
                        1,
                        int(request.get("world_omnidreams_anchor_transfer_steps", 12) or 12),
                    ),
                    transfer_seed=(
                        transfer_seed
                        if request.get("world_omnidreams_anchor_transfer_seed") in {None, ""}
                        else int(request["world_omnidreams_anchor_transfer_seed"])
                    ),
                    max_attempts=max(
                        1,
                        min(
                            5,
                            int(
                                request.get(
                                    "world_omnidreams_anchor_max_attempts", 3
                                )
                                or 3
                            ),
                        ),
                    ),
                    anchor_mode=str(
                        request.get("world_omnidreams_anchor_mode")
                        or "conditioned_front"
                    ),
                )
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "omnidreams_transfer_anchor_manifest",
                        external_anchor_manifest,
                        mime_type="application/json",
                        metadata={
                            "mode": "transfer",
                            "anchor_mode": str(
                                request.get("world_omnidreams_anchor_mode")
                                or "conditioned_front"
                            ),
                            "segment_seconds": segment_seconds,
                            "transfer_steps": max(
                                1,
                                int(
                                    request.get(
                                        "world_omnidreams_anchor_transfer_steps", 12
                                    )
                                    or 12
                                ),
                            ),
                            "transfer_seed": (
                                transfer_seed
                                if request.get("world_omnidreams_anchor_transfer_seed")
                                in {None, ""}
                                else int(request["world_omnidreams_anchor_transfer_seed"])
                            ),
                        },
                    )
                )

            def _refresh_operational_artifact() -> dict[str, Any]:
                status_payload: dict[str, Any] = {}
                status_path = Path(str(capture_result.get("status_path") or ""))
                try:
                    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
                final_metadata = {
                    "frames": int(capture_result.get("total_frames", len(traffic_frames)) or 0),
                    "buffered_frames": len(traffic_frames),
                    "ego_id": ego_id,
                    "duration_seconds": (
                        float(traffic_frames[-1].get("sim_time", 0.0))
                        if open_ended_world and traffic_frames
                        else float(duration)
                    ),
                    "run_until_stopped": open_ended_world,
                    "source_fps": operational_source_fps,
                    "first_sim_time": float(traffic_frames[0].get("sim_time", 0.0)) if traffic_frames else None,
                    "last_sim_time": float(traffic_frames[-1].get("sim_time", 0.0)) if traffic_frames else None,
                    "live_stream_path": self._repo_rel(traffic_stream_path),
                    "capture_stage": str(
                        status_payload.get("stage")
                        or ("completed" if capture_result.get("done") else "running")
                    ),
                }
                updated = self._add_world_artifact(
                    experiment_id,
                    "operational_traffic",
                    traffic_path,
                    mime_type="application/json",
                    metadata=final_metadata,
                )
                stream_updated = self._add_world_artifact(
                    experiment_id,
                    "operational_traffic_stream",
                    traffic_stream_path,
                    mime_type="application/x-ndjson",
                    metadata={
                        "frames": int(capture_result.get("total_frames", len(traffic_frames)) or 0),
                        "buffered_frames": len(traffic_frames),
                        "ego_id": ego_id,
                        "duration_seconds": final_metadata["duration_seconds"],
                        "source_fps": operational_source_fps,
                        "capture_stage": final_metadata["capture_stage"],
                    },
                )
                replacements = {updated["path"]: updated, stream_updated["path"]: stream_updated}
                for index, item in enumerate(artifacts):
                    if item.get("path") in replacements:
                        artifacts[index] = replacements[item["path"]]
                return final_metadata

            def _audit_operational_traffic() -> dict[str, Any]:
                audit_path = pipeline_root / "qa" / "traffic_safety_audit.json"
                local_target = max(
                    0, int(request.get("world_local_target_count", 0) or 0)
                )
                minimum_motorized_60m = 6
                minimum_motorized_120m = 12
                if backend_model in {"cnde", "rulebased"} and local_target > 0:
                    cyclist_ratio = max(
                        0.0,
                        min(0.5, float(request.get("cyclist_ratio", 0.08) or 0.0)),
                    )
                    cyclist_target = (
                        max(1, int(round(local_target * cyclist_ratio)))
                        if cyclist_ratio > 0.0
                        else 0
                    )
                    motorized_target = max(1, local_target - cyclist_target)
                    minimum_motorized_60m = min(
                        6,
                        max(4, int(math.ceil(motorized_target * 0.5))),
                    )
                    minimum_motorized_120m = min(
                        12,
                        max(minimum_motorized_60m, motorized_target - 1),
                    )
                report = audit_traffic_safety(
                    traffic_stream_path,
                    audit_path,
                    expected_fps=operational_source_fps,
                    require_local_density=backend_model != "neuralnde",
                    minimum_motorized_60m=minimum_motorized_60m,
                    minimum_motorized_120m=minimum_motorized_120m,
                )
                artifact = self._add_world_artifact(
                    experiment_id,
                    "traffic_safety_audit",
                    audit_path,
                    mime_type="application/json",
                    metadata={"passed": report["passed"], "checks": report["checks"]},
                )
                for index, item in enumerate(artifacts):
                    if item.get("path") == artifact["path"]:
                        artifacts[index] = artifact
                        break
                else:
                    artifacts.append(artifact)
                return report

            recording_path = self._recording_path(experiment_id)
            av_report_path = recording_path.with_suffix(recording_path.suffix + ".av.json")
            if av_report_path.is_file():
                try:
                    av_report = json.loads(av_report_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    av_report = {}
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "av_control_report",
                        av_report_path,
                        mime_type="application/json",
                        metadata=av_report,
                    )
                )

            if bool(request.get("world_transfer_full_enabled", False)) and duration > 1.0:
                capture_thread.join(timeout=max(300.0, duration * 30.0))
                if capture_result.get("error"):
                    raise RuntimeError(str(capture_result.get("error")))
                traffic_frames = list(capture_result.get("frames") or traffic_frames)
                ego_id = str(capture_result.get("ego_id") or ego_id)
                try:
                    traffic_frames, ego_id = recording_to_traffic_frames(
                        recording_path,
                        duration_seconds=duration,
                        ego_id=ego_id,
                    )
                    traffic_path.write_text(json.dumps(traffic_frames, ensure_ascii=False, indent=2), encoding="utf-8")
                except (OSError, EOFError, ValueError) as exc:
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "recording_fallback_warning",
                            traffic_path,
                            mime_type="application/json",
                            metadata={"warning": f"Using live traffic capture because final recording is incomplete: {exc}"},
                        )
                    )
                _refresh_operational_artifact()
                full_source_steps = int(round(duration * 10.0)) + 1
                full_clip_id = f"traffic-{experiment_id}"
                self._set_world_job(
                    experiment_id,
                    stage="full_scene_export",
                    progress=0.58,
                    message=f"Exporting the complete {duration:g}s seven-camera traffic window",
                    payload={"traffic_frames": len(traffic_frames), "artifacts": artifacts},
                )
                full_scene_root = pipeline_root / "rds_hq_full"
                full_export = export_citynde_scene(
                    recording_path,
                    full_scene_root,
                    clip_id=full_clip_id,
                    source_steps=full_source_steps,
                    source_fps=10.0,
                    target_fps=30,
                    ego_id=ego_id,
                    map_state=map_state,
                    map_radius_m=replay_map_radius_m,
                )
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "full_scene_export_report",
                        full_scene_root / "trafficwm_export_report.json",
                        mime_type="application/json",
                    )
                )
                self._set_world_job(
                    experiment_id,
                    stage="full_control_render",
                    progress=0.64,
                    message=f"Rendering {full_export['output_frames']} control frames for seven cameras",
                    payload={"full_scene_export": full_export, "artifacts": artifacts},
                )
                full_control_root = pipeline_root / "controls_full"
                full_render = self.cosmos.render_controls(
                    full_scene_root,
                    full_control_root,
                    clip_id=full_clip_id,
                    cameras=list(CAMERAS),
                )
                full_controls = control_paths(full_control_root, full_clip_id)
                full_control_qa = analyze_group(
                    list(full_controls.values()),
                    pipeline_root / "qa" / "controls_full",
                    expected_duration=duration + 1.0 / 30.0,
                    expected_fps=30.0,
                    quality_profile="semantic_control",
                )
                artifacts.append(self._add_world_artifact(experiment_id, "full_control_grid", Path(full_control_qa["contact_sheet"]), mime_type="image/jpeg"))

                frame_plan = transfer_frame_plan(duration)
                full_transfer_controls = pad_controls(
                    full_controls,
                    pipeline_root / "controls_full_transfer_window",
                    minimum_frames=int(frame_plan["control_frames_30fps"]),
                    fps=30,
                )
                full_name = f"traffic_{experiment_id}"
                full_spec_path = pipeline_root / "transfer_full_spec.json"
                write_transfer_spec(
                    full_spec_path,
                    name=full_name,
                    controls=full_transfer_controls,
                    prompt=effective_prompt,
                    duration_seconds=duration,
                    num_steps=int(request.get("world_transfer_steps", 35) or 35),
                )
                self._set_world_job(
                    experiment_id,
                    stage="transfer_full",
                    progress=0.72,
                    message=f"Cosmos Transfer2.5 is generating the complete {duration:g}s seven-view video",
                    payload={"full_control_quality": full_control_qa, "transfer_frame_plan": frame_plan, "artifacts": artifacts},
                    timing=("full_control_render_seconds", float(full_render["seconds"])),
                )
                full_transfer_output = pipeline_root / "transfer_full_raw"
                full_transfer_job = self._run_transfer_job(
                    full_spec_path,
                    full_transfer_output,
                    job_id=f"full-{experiment_id}",
                    experiment_id=experiment_id,
                )
                full_raw_views = discover_transfer_views(full_transfer_output, full_name)
                full_views = trim_views(
                    full_raw_views,
                    pipeline_root / "transfer_full_views",
                    frames=int(frame_plan["target_frames"]),
                    fps=10,
                )
                full_transfer_qa = analyze_group(
                    list(full_views.values()),
                    pipeline_root / "qa" / "transfer_full",
                    expected_duration=duration,
                    expected_fps=10.0,
                    quality_profile="generated_driving",
                )
                full_playback_proxy = create_playback_proxy(
                    full_views["front_wide"],
                    pipeline_root / "playback" / "transfer_full_front_wide_30fps.mp4",
                    duration_seconds=duration,
                    fps=30,
                )
                for view, path in full_views.items():
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            f"transfer_full_{view}",
                            path,
                            mime_type="video/mp4",
                            metadata={"view": view, "fps": 10, "frames": int(frame_plan["target_frames"])},
                        )
                    )
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "transfer_full_front_wide_smooth",
                        full_playback_proxy,
                        mime_type="video/mp4",
                        metadata={
                            "view": "front_wide",
                            "native_fps": 10,
                            "display_fps": 30,
                            "interpolation": "frame_blend",
                        },
                    )
                )
                artifacts.append(self._add_world_artifact(experiment_id, "transfer_full_qa", pipeline_root / "qa" / "transfer_full" / "video_qa.json", mime_type="application/json"))
                self._set_world_job(
                    experiment_id,
                    stage="clipgt_export",
                    progress=0.84,
                    message="Building the OmniDreams HD-map archive",
                    payload={"full_transfer_job": full_transfer_job, "full_transfer_quality": full_transfer_qa, "artifacts": artifacts},
                    timing=("full_transfer_generation_seconds", float(full_transfer_job.get("generation_seconds", 0.0) or 0.0)),
                )

            self._set_world_job(
                experiment_id,
                stage="clipgt_export",
                progress=0.86 if duration > 1.0 else 0.64,
                message="Building the OmniDreams HD-map archive",
                payload={"traffic_frames": len(traffic_frames), "artifacts": artifacts},
            )
            clipgt_manifest = export_clipgt(
                map_state,
                traffic_frames,
                pipeline_root / "clipgt",
                clip_id=f"dreams-{experiment_id}",
                map_radius_m=replay_map_radius_m,
                map_crop_path=world_route_crop_path,
            )
            clipgt_archive = Path(clipgt_manifest["archive"])
            artifacts.append(self._add_world_artifact(experiment_id, "clipgt_hdmap", clipgt_archive, mime_type="application/zip", metadata=clipgt_manifest))

            if bool(request.get("world_dreams_enabled", True)):
                self._set_world_job(
                    experiment_id,
                    stage="omnidreams",
                    progress=0.9 if duration > 1.0 else 0.72,
                    message="OmniDreams is generating a temporally consistent video",
                    payload={"clipgt": clipgt_manifest, "artifacts": artifacts},
                )
                dreams_output = pipeline_root / "omnidreams"
                dreams_profile = self.cosmos.omnidreams_profile
                visual_stream_av = (
                    str(request.get("av_control_model") or "").upper()
                    == "LEAD_TFV6_STREAM"
                )
                traffic_prefetch_seconds = (
                    0.0
                    if visual_stream_av
                    else max(
                        0.0,
                        float(
                            request.get(
                                "world_omnidreams_traffic_prefetch_seconds",
                                dreams_profile.traffic_prefetch_seconds,
                            )
                            or 0.0
                        ),
                    )
                )
                dreams_spec = {
                    "server": f"127.0.0.1:{self.cosmos.omnidreams_port}",
                    "hdmap_zip": str(clipgt_archive),
                    "initial_frame": str(seed_frame),
                    "traffic_frames": str(traffic_path),
                    "traffic_stream_frames": str(traffic_stream_path),
                    "traffic_capture_status": str(capture_result.get("status_path") or ""),
                    "world_sync_state": str(world_sync_path),
                    "live_traffic_frames": True,
                    "follow_traffic": follow_traffic,
                    "run_until_traffic_ends": open_ended_world,
                    "traffic_wait_timeout_seconds": (
                        1800.0 if open_ended_world else max(300.0, duration * 30.0)
                    ),
                    "output_dir": str(dreams_output),
                    "duration_seconds": None if open_ended_world else duration,
                    "fps": 30,
                    "runtime_profile": dreams_profile.name,
                    "pipeline_config": self.cosmos.omnidreams_pipeline_config,
                    "gpu_ids": list(self.cosmos.omnidreams_gpus),
                    "live_preview_fps": max(
                        1,
                        min(
                            30,
                            int(
                                os.environ.get(
                                    "OMNIDREAMS_LIVE_PREVIEW_FPS",
                                    str(dreams_profile.live_preview_fps),
                                )
                                or dreams_profile.live_preview_fps
                            ),
                        ),
                    ),
                    "traffic_prefetch_seconds": traffic_prefetch_seconds,
                    "encoder_preset": dreams_profile.encoder_preset,
                    "encoder_crf": dreams_profile.encoder_crf,
                    "session_segment_seconds": segment_seconds,
                    "rollover_initial_frame_mode": rollover_mode,
                    "external_anchor_manifest": (
                        str(external_anchor_manifest)
                        if external_anchor_manifest is not None
                        else ""
                    ),
                    "external_anchor_timeout_seconds": max(
                        1800.0,
                        float(
                            request.get("world_omnidreams_anchor_timeout_seconds", 3600.0)
                            or 3600.0
                        ),
                    ),
                    "rollover_sharpen_percent": max(
                        0,
                        min(
                            100,
                            int(request.get("world_omnidreams_rollover_sharpen_percent", 0) or 0),
                        ),
                    ),
                    "rollover_chroma_blur_radius": max(
                        0.0,
                        min(
                            4.0,
                            float(
                                request.get("world_omnidreams_rollover_chroma_blur_radius", 0.0)
                                or 0.0
                            ),
                        ),
                    ),
                    "rollover_saturation_percent": max(
                        0,
                        min(
                            150,
                            int(
                                request.get("world_omnidreams_rollover_saturation_percent", 100)
                                or 0
                            ),
                        ),
                    ),
                    "rollover_image_format": str(
                        request.get("world_omnidreams_rollover_image_format") or "jpeg"
                    ).strip().lower(),
                    "session_seed_stride": int(
                        request.get("world_omnidreams_session_seed_stride", 0) or 0
                    ),
                    "stationary_anchor_enabled": bool(
                        request.get("world_stationary_anchor_enabled", True)
                        and rollover_mode != "transfer"
                    ),
                    "stationary_speed_threshold_mps": max(
                        0.0,
                        float(request.get("world_stationary_speed_threshold_mps", 0.35) or 0.0),
                    ),
                    "stationary_exit_speed_mps": max(
                        0.0,
                        float(request.get("world_stationary_exit_speed_mps", 0.8) or 0.0),
                    ),
                    "stationary_enter_seconds": max(
                        0.1,
                        float(request.get("world_stationary_enter_seconds", 1.0) or 0.1),
                    ),
                    "stationary_reset_seconds": max(
                        1.0,
                        float(request.get("world_stationary_reset_seconds", 6.0) or 1.0),
                    ),
                    "session_transition_frames": max(
                        0,
                        min(
                            30,
                            int(request.get("world_omnidreams_transition_frames", 0) or 0),
                        ),
                    ),
                    "source_traffic_fps": operational_source_fps,
                    "traffic_interpolation": (
                        "hermite_velocity_position_shortest_angle_25hz_to_30hz"
                        if backend_model == "neuralnde"
                        else "hermite_velocity_position_shortest_angle_10hz_to_30hz"
                    ),
                    "actor_radius_m": 90.0,
                    "actor_clearance_m": 2.0,
                    "actor_allow_overlap": bool(
                        request.get("world_omnidreams_actor_allow_overlap", False)
                    ),
                    "actor_fov_degrees": 120.0,
                    "actor_fov_margin_degrees": 8.0,
                    "actor_rear_margin_m": 3.0,
                    "actor_hood_occlusion_distance_m": max(
                        0.0,
                        min(
                            50.0,
                            float(
                                request.get(
                                    "world_omnidreams_actor_hood_occlusion_distance_m",
                                    0.0,
                                )
                                or 0.0
                            ),
                        ),
                    ),
                    "actor_hood_occlusion_lateral_m": max(
                        0.0,
                        min(
                            10.0,
                            float(
                                request.get(
                                    "world_omnidreams_actor_hood_occlusion_lateral_m",
                                    0.0,
                                )
                                or 0.0
                            ),
                        ),
                    ),
                    "actor_oncoming_lateral_exclusion_m": max(
                        0.0,
                        min(
                            20.0,
                            float(
                                request.get(
                                    "world_omnidreams_actor_oncoming_lateral_exclusion_m",
                                    0.0,
                                )
                                or 0.0
                            ),
                        ),
                    ),
                    "actor_max_count": max(
                        1,
                        min(
                            128,
                            int(request.get("world_omnidreams_actor_max_count", 20) or 20),
                        ),
                    ),
                    "actor_max_pedestrians": max(
                        0,
                        min(
                            32,
                            int(request.get("world_omnidreams_actor_max_pedestrians", 4) or 0),
                        ),
                    ),
                    "actor_max_cyclists": max(
                        0,
                        min(
                            32,
                            int(request.get("world_omnidreams_actor_max_cyclists", 2) or 0),
                        ),
                    ),
                    "width": 1280,
                    "height": 704,
                    "camera_name": "camera_front_wide_120fov",
                    "camera_calibration": clipgt_manifest["camera_calibration"],
                    "fov_degrees": 120.0,
                    "prompt": effective_prompt,
                    "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
                    "return_hdmap_frames": (
                        dreams_profile.return_hdmap_frames
                        or _world_save_omnidreams_control(request)
                    ),
                    "random_seed": _world_omnidreams_seed(request),
                }
                dreams_spec_path = pipeline_root / "omnidreams_spec.json"
                dreams_spec_path.write_text(json.dumps(dreams_spec, ensure_ascii=False, indent=2), encoding="utf-8")
                live_preview = dreams_output / "camera_front_wide_120fov_latest.jpg"
                live_progress = dreams_output / "progress.json"
                artifacts.append(self._add_world_artifact(experiment_id, "omnidreams_live_preview", live_preview, mime_type="image/jpeg"))
                artifacts.append(self._add_world_artifact(experiment_id, "omnidreams_progress", live_progress, mime_type="application/json"))

                def _dreams_progress(progress_payload: dict) -> None:
                    progress_value = float(progress_payload.get("progress", 0.0) or 0.0)
                    generated_frames = int(progress_payload.get("frames", 0) or 0)
                    target_frames = progress_payload.get("target_frames")
                    if open_ended_world or target_frames is None:
                        progress_message = (
                            f"OmniDreams is following live traffic at frame {generated_frames}; "
                            "generation continues until the experiment is stopped"
                        )
                    else:
                        progress_message = (
                            f"OmniDreams is generating frame {generated_frames}/{int(target_frames or 0)}"
                        )
                    self._set_world_job(
                        experiment_id,
                        stage="omnidreams",
                        progress=(0.9 if duration > 1.0 else 0.72) + 0.08 * max(0.0, min(1.0, progress_value)),
                        message=progress_message,
                        payload={"omnidreams_progress": progress_payload, "artifacts": artifacts},
                    )

                def _run_dreams() -> dict:
                    return self.cosmos.run_omnidreams(
                        dreams_spec_path,
                        timeout=None if open_ended_world else max(14400.0, duration * 30.0),
                        progress_callback=_dreams_progress,
                        cancellation_callback=lambda: self._raise_if_world_job_cancelled(
                            experiment_id
                        ),
                    )

                try:
                    dreams_manifest = _run_dreams()
                except RuntimeError as exc:
                    detail = str(exc)
                    recoverable_markers = (
                        "CUDA error",
                        "out of memory",
                        "illegal memory access",
                        "StatusCode.UNAVAILABLE",
                        "Socket closed",
                        "failed to connect to all addresses",
                    )
                    if not any(marker.lower() in detail.lower() for marker in recoverable_markers):
                        raise
                    self._set_world_job(
                        experiment_id,
                        stage="waiting_for_models",
                        progress=0.9 if duration > 1.0 else 0.72,
                        message="Restarting the resident OmniDreams service after a CUDA/RPC fault",
                        payload={
                            "omnidreams_recovery_attempt": 1,
                            "omnidreams_recovery_reason": detail[-2000:],
                            "artifacts": artifacts,
                        },
                    )
                    self.cosmos.restart()
                    ready_deadline = time.monotonic() + 900.0
                    while time.monotonic() < ready_deadline:
                        self._raise_if_world_job_cancelled(experiment_id)
                        omni_status = self.cosmos.status().get("omnidreams") or {}
                        if omni_status.get("model_loaded"):
                            break
                        if omni_status.get("run_state") == "error":
                            raise RuntimeError(
                                "OmniDreams failed to reload: "
                                + str(
                                    omni_status.get("log_tail")
                                    or omni_status.get("error")
                                    or "unknown service error"
                                )[-2000:]
                            )
                        time.sleep(1.0)
                    else:
                        raise TimeoutError("Timed out reloading OmniDreams after a CUDA/RPC fault")
                    shutil.rmtree(dreams_output, ignore_errors=True)
                    dreams_output.mkdir(parents=True, exist_ok=True)
                    dreams_manifest = _run_dreams()
                capture_thread.join(
                    timeout=30.0 if open_ended_world else max(300.0, duration * 30.0)
                )
                if capture_result.get("error"):
                    raise RuntimeError(str(capture_result.get("error")))
                traffic_frames = list(capture_result.get("frames") or traffic_frames)
                ego_id = str(capture_result.get("ego_id") or ego_id)
                traffic_metadata = _refresh_operational_artifact()
                traffic_safety_report = _audit_operational_traffic()
                try:
                    final_dreams_progress = json.loads(live_progress.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    final_dreams_progress = {}
                dreams_video = Path(dreams_manifest["output"])
                dreams_hdmap_value = str(
                    dreams_manifest.get("hdmap_condition_video") or ""
                ).strip()
                dreams_hdmap_video = (
                    Path(dreams_hdmap_value).resolve()
                    if dreams_hdmap_value
                    else None
                )
                dreams_control_trace_value = str(
                    dreams_manifest.get("control_trace") or ""
                ).strip()
                dreams_control_trace = (
                    Path(dreams_control_trace_value).resolve()
                    if dreams_control_trace_value
                    else None
                )
                dreams_qa = analyze_group(
                    [dreams_video],
                    pipeline_root / "qa" / "omnidreams",
                    expected_duration=float(dreams_manifest.get("duration_seconds", duration) or duration),
                    expected_fps=30.0,
                    quality_profile="generated_driving",
                )
                artifacts.append(self._add_world_artifact(experiment_id, "omnidreams_video", dreams_video, mime_type="video/mp4", metadata=dreams_manifest))
                if dreams_hdmap_video is not None and dreams_hdmap_video.is_file():
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "omnidreams_hdmap_control",
                            dreams_hdmap_video,
                            mime_type="video/mp4",
                            metadata={
                                "fps": 30,
                                "control_contract": dreams_manifest.get(
                                    "control_contract"
                                ),
                                "dynamic_actor_count_range": dreams_manifest.get(
                                    "dynamic_actor_count_range"
                                ),
                            },
                        )
                    )
                if (
                    dreams_control_trace is not None
                    and dreams_control_trace.is_file()
                ):
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "omnidreams_control_trace",
                            dreams_control_trace,
                            mime_type="application/x-ndjson",
                            metadata={
                                "dynamic_actor_membership": dreams_manifest.get(
                                    "dynamic_actor_membership"
                                ),
                            },
                        )
                    )
                artifacts.append(self._add_world_artifact(experiment_id, "omnidreams_qa", pipeline_root / "qa" / "omnidreams" / "video_qa.json", mime_type="application/json"))
                if not dreams_qa.get("passed"):
                    errors = [
                        error
                        for view in dreams_qa.get("views") or []
                        for error in view.get("errors") or []
                    ]
                    raise RuntimeError(
                        "OmniDreams output failed driving-scene QA: "
                        + ("; ".join(errors[:4]) or "unknown visual-quality failure")
                    )
                visual_av_report = None
                if str(request.get("av_control_model") or "").upper() == "LEAD_TFV6_STREAM":
                    visual_av_report_path = pipeline_root / "av_stream" / "lead_tfv6_stream_audit.json"
                    visual_av_report = audit_visual_stream(
                        dreams_video,
                        traffic_path,
                        visual_av_report_path,
                    )
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "visual_av_stream_audit",
                            visual_av_report_path,
                            mime_type="application/json",
                            metadata={
                                "algorithm": "LEAD_TFV6",
                                "rgb_bev_stream_ready": visual_av_report["rgb_bev_stream_ready"],
                                "full_tfv6_contract_met": visual_av_report["full_tfv6_contract_met"],
                            },
                        )
                    )
                joint_audit = None
                joint_audit_path = pipeline_root / "qa" / "joint_flow_audit.json"
                if av_report_path.is_file() and (pipeline_root / "qa" / "transfer_full" / "video_qa.json").is_file():
                    joint_audit = audit_joint_flow(
                        pipeline_root,
                        av_report_path,
                        warmup_frames_path,
                        joint_audit_path,
                    )
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "joint_flow_audit",
                            joint_audit_path,
                            mime_type="application/json",
                            metadata={"passed": joint_audit["passed"]},
                        )
                    )
                self._set_world_job(
                    experiment_id,
                    stage="completed",
                    run_state="completed",
                    progress=1.0,
                    message="Traffic, appearance seed, OmniDreams video, and QA are complete",
                    payload={
                        "omnidreams": dreams_manifest,
                        "omnidreams_transfer_anchors": anchor_result,
                        "omnidreams_progress": final_dreams_progress,
                        "omnidreams_quality": dreams_qa,
                        "traffic_frames": len(traffic_frames),
                        "traffic_capture": traffic_metadata,
                        "world_seed_alignment": seed_alignment_audit,
                        "traffic_safety_audit": traffic_safety_report,
                        "visual_av_stream": visual_av_report,
                        "joint_flow_audit": joint_audit,
                        "artifacts": artifacts,
                    },
                    timing=("pipeline_end_to_end_seconds", time.perf_counter() - pipeline_started),
                )
            else:
                capture_thread.join(
                    timeout=None if open_ended_world else max(300.0, duration * 30.0)
                )
                if capture_result.get("error"):
                    raise RuntimeError(str(capture_result.get("error")))
                traffic_frames = list(capture_result.get("frames") or traffic_frames)
                ego_id = str(capture_result.get("ego_id") or ego_id)
                traffic_metadata = _refresh_operational_artifact()
                traffic_safety_report = _audit_operational_traffic()
                self._set_world_job(
                    experiment_id,
                    stage="completed",
                    run_state="completed",
                    progress=1.0,
                    message="Transfer seed and operational traffic artifacts are complete",
                    payload={
                        "traffic_frames": len(traffic_frames),
                        "traffic_capture": traffic_metadata,
                        "world_seed_alignment": seed_alignment_audit,
                        "traffic_safety_audit": traffic_safety_report,
                        "artifacts": artifacts,
                    },
                    timing=("pipeline_end_to_end_seconds", time.perf_counter() - pipeline_started),
                )
        except WorldJobCancelled as exc:
            terminal_state = "interrupted" if self._world_stop.is_set() else "stopped"
            partial_dreams_video = (
                self.root
                / "output"
                / "cosmos"
                / "experiments"
                / experiment_id
                / "omnidreams"
                / "camera_front_wide_120fov.mp4"
            )
            if partial_dreams_video.is_file() and partial_dreams_video.stat().st_size > 0:
                artifacts.append(
                    self._add_world_artifact(
                        experiment_id,
                        "omnidreams_stopped_video",
                        partial_dreams_video,
                        mime_type="video/mp4",
                        metadata={"partial": True, "termination_reason": str(exc)},
                    )
                )
            self._set_world_job(
                experiment_id,
                stage=terminal_state,
                run_state=terminal_state,
                progress=0.0,
                message="DenseWorld generation interrupted" if terminal_state == "interrupted" else "DenseWorld generation stopped",
                payload={"artifacts": artifacts, "termination_reason": str(exc)},
                timing=("pipeline_end_to_end_seconds", time.perf_counter() - pipeline_started),
            )
        except BaseException as exc:
            if not self._world_stop.is_set():
                partial_dreams_video = (
                    self.root
                    / "output"
                    / "cosmos"
                    / "experiments"
                    / experiment_id
                    / "omnidreams"
                    / "camera_front_wide_120fov.mp4"
                )
                if partial_dreams_video.is_file() and partial_dreams_video.stat().st_size > 0:
                    artifacts.append(
                        self._add_world_artifact(
                            experiment_id,
                            "omnidreams_partial_video",
                            partial_dreams_video,
                            mime_type="video/mp4",
                            metadata={"partial": True, "error": str(exc)},
                        )
                    )
                self._set_world_job(
                    experiment_id,
                    stage="error",
                    run_state="error",
                    progress=1.0,
                    message="DenseWorld generation failed",
                    error=str(exc),
                    payload={"artifacts": artifacts},
                    timing=("pipeline_end_to_end_seconds", time.perf_counter() - pipeline_started),
                )
                if not traffic_activated:
                    with self._lock:
                        pending_info = self._experiments.get(experiment_id)
                    if pending_info is not None:
                        self._http_json(
                            f"http://127.0.0.1:{pending_info['port']}/action",
                            method="POST",
                            payload={"type": "terminate_experiment", "save_data": True},
                            timeout=6.0,
                        )
                        self._release_batch_process(experiment_id, "error")
        finally:
            if anchor_stop_event is not None:
                anchor_stop_event.set()
            if anchor_thread is not None and anchor_thread.is_alive():
                anchor_thread.join(timeout=10.0)
            world_job = self.experiment_store.world_job(experiment_id) or {}
            world_state = str(world_job.get("run_state") or "")
            terminal_world_states = {"completed", "error", "stopped", "interrupted"}
            if (
                world_state in terminal_world_states
                and bool(request.get("world_dreams_enabled", True))
            ):
                update_world_sync(
                    self.root
                    / "output"
                    / "cosmos"
                    / "experiments"
                    / experiment_id
                    / "traffic_video_sync.json",
                    stage=world_state,
                    error=str(world_job.get("error") or ""),
                )
            with self._lock:
                active_info = self._experiments.get(experiment_id)
            child_status: dict[str, Any] = {}
            if active_info is not None:
                child_status = self._http_json(
                    f"http://127.0.0.1:{active_info['port']}/status",
                    timeout=1.0,
                ) or {}
            # Batch runs intentionally end with their requested world horizon.
            # Interactive traffic runs continue when a shorter fixed clip ends,
            # but completed finite simulations must not leave a container alive.
            if (
                world_state in terminal_world_states
                and active_info is not None
                and _world_pipeline_should_release_child(active_info, child_status)
            ):
                self._release_batch_process(experiment_id, world_state)
            self._world_threads.pop(experiment_id, None)
            self._world_cancel_events.pop(experiment_id, None)

    def _citynde_container_command(
        self,
        command: list[str],
        *,
        exp_id: str,
        gpu_id: str,
    ) -> list[str]:
        """Run the legacy CityNDE environment in a modern-glibc CUDA container."""
        if not self.citynde_container_image:
            return command
        shim = self.root / "backend" / "algorithms" / "citynde" / "interface" / "torch_legacy_abi_shim.so"
        python_path = "/workspace/.venv/bin/python"
        inner_command = [python_path, *command[1:]]
        python_paths = [
            self.root / "envs" / "cnde" / "lib" / "python3.10" / "site-packages",
            self.root,
            self.citynde_root,
            self.root / "algorithm_sources" / "CityNDE" / "tuplan_garage",
        ]
        exports = [
            f"export PYTHONPATH={shlex.quote(':'.join(str(path) for path in python_paths))}",
            f"export LD_PRELOAD={shlex.quote(str(shim))}",
            f"export CUDA_VISIBLE_DEVICES={shlex.quote(gpu_id or '0')}",
            "export PYTHONHASHSEED=0",
            f"cd {shlex.quote(str(self.citynde_root))}",
            "exec " + shlex.join(inner_command),
        ]
        container_name = "trafficwm-city-" + re.sub(r"[^a-zA-Z0-9_.-]", "-", exp_id)[-48:]
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--gpus",
            "all",
            "--network",
            "host",
            "--shm-size",
            "16g",
            "-v",
            f"{self.root}:{self.root}",
        ]
        if not str(self.citynde_root).startswith(str(self.root) + os.sep):
            docker_command.extend(["-v", f"{self.citynde_root}:{self.citynde_root}"])
        if self.citynde_container_venv:
            docker_command.extend(["-v", f"{self.citynde_container_venv}:/workspace/.venv"])
        docker_command.extend(
            [
                "--entrypoint",
                "bash",
                self.citynde_container_image,
                "-lc",
                "; ".join(exports),
            ]
        )
        return ["sg", "docker", "-c", shlex.join(docker_command)]

    def launch_neuralnde(self, payload: dict) -> dict:
        payload = dict(payload)
        standard_scenario = str(payload.get("standard_scenario_path") or "").strip()
        standard_target: Path | None = None
        if standard_scenario:
            standard_target, scenario_error = self._scenario_target(standard_scenario)
            if scenario_error is not None:
                return scenario_error
            if standard_target is None or not standard_target.is_file():
                return {"ok": False, "error": "Standard scenario file was not found"}
            standard_metadata = self._citynde_scenario_metadata(standard_target)
            if not standard_metadata.get("library_id"):
                return {"ok": False, "error": "The selected file is not a managed standard scenario"}
            if str(standard_metadata.get("backend_model") or "").strip().lower() != "neuralnde":
                return {"ok": False, "error": "The selected standard scenario is not bound to NeuralNDE"}
            dataset = str(
                standard_metadata.get("dataset")
                or standard_metadata.get("map_path")
                or "AA_rdbt"
            ).strip()
            payload["dataset"] = dataset
            payload["map_path"] = dataset
            payload["seed"] = int(standard_metadata.get("initialization_seed", 42) or 42)
            payload["scenario_configuration_locked"] = True
            if bool(payload.get("world_use_existing_seed")):
                seed_bundle = inspect_scenario_seed_bundle(
                    standard_target,
                    standard_metadata,
                    self.root,
                )
                if not seed_bundle.get("available"):
                    return {
                        "ok": False,
                        "error": f"The selected NeuralNDE first frame is invalid: {seed_bundle.get('reason') or 'unknown reason'}",
                    }
                seed_reference = str(seed_bundle.get("image_path") or "")
                requested_seed = str(payload.get("world_seed_image") or "").strip()
                if requested_seed:
                    requested_target = Path(requested_seed)
                    if not requested_target.is_absolute():
                        requested_target = self.root / requested_target
                    expected_target = Path(seed_reference)
                    if not expected_target.is_absolute():
                        expected_target = self.root / expected_target
                    if requested_target.resolve() != expected_target.resolve():
                        return {
                            "ok": False,
                            "error": "The requested RGB seed does not belong to the selected NeuralNDE scenario",
                        }
                payload["world_seed_image"] = seed_reference
                payload["world_seed_init_file"] = str(
                    seed_bundle.get("initialization_path") or ""
                )
                payload["world_existing_seed_gate"] = True
                payload["world_seed_ego_id"] = str(seed_bundle.get("ego_id") or "")
                payload["warmup_seconds"] = float(
                    standard_metadata.get("seed_warmup_seconds", 1.0) or 1.0
                )
        payload = _world_generation_defaults(payload)
        if not self.neuralnde_root.is_dir():
            return {"ok": False, "error": f"NeuralNDE root not found: {self.neuralnde_root}"}
        if not Path(self.neuralnde_python).is_file():
            return {"ok": False, "error": f"NeuralNDE Python not found: {self.neuralnde_python}"}
        if not self.neuralnde_adapter_script.is_file():
            return {"ok": False, "error": f"NeuralNDE adapter not found: {self.neuralnde_adapter_script}"}

        dataset = str(payload.get("map_path") or payload.get("dataset") or "AA_rdbt").strip()
        if dataset not in {"AA_rdbt", "rounD"}:
            return {"ok": False, "error": f"Unsupported NeuralNDE dataset: {dataset}"}
        if not (self.neuralnde_root / "configs" / f"{dataset}_inference.yml").is_file():
            return {"ok": False, "error": f"NeuralNDE dataset is not configured: {dataset}"}

        run_until_stopped = _traffic_runs_until_stopped(payload)
        max_sim_time = (
            0.0
            if run_until_stopped
            else max(0.04, float(payload.get("max_sim_time", 60.0) or 60.0))
        )
        world_generation_enabled = bool(payload.get("world_generation_enabled", False))
        if world_generation_enabled and not run_until_stopped:
            max_sim_time = max(max_sim_time, _world_video_duration_seconds(payload))
        total_step = 0 if run_until_stopped else max(1, int(math.ceil(max_sim_time / 0.04)))
        gpu_id = str(payload.get("gpu_id") or "4").strip()
        seed = int(payload.get("seed", 42) or 42)
        exp_name = self._safe_name(str(payload.get("experiment_name", "")), fallback=f"neuralnde_{dataset}")
        exp_id = f"neuralnde_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        port = int(payload.get("port") or self._allocate_child_port())
        payload = self._with_av_port(payload, port)
        output_dir = self.root / "output" / "experiments" / exp_id
        output_dir.mkdir(parents=True, exist_ok=True)
        payload["max_sim_time"] = max_sim_time
        payload["total_step"] = total_step
        payload["sim_resolution"] = 0.04
        payload["run_until_stopped"] = run_until_stopped
        payload["world_transfer_full_enabled"] = False
        world_sync_path = (
            self.root
            / "output"
            / "cosmos"
            / "experiments"
            / exp_id
            / "traffic_video_sync.json"
        )
        world_sync_enabled = world_generation_enabled and bool(
            payload.get("world_dreams_enabled", True)
        )
        if world_sync_enabled:
            update_world_sync(
                world_sync_path,
                stage="waiting_for_seed",
                experiment_id=exp_id,
                requested_traffic_time=0.0,
                generated_video_time=0.0,
            )
        av_control_model = str(payload.get("av_control_model") or "DEFAULT_TCP").upper()
        av_rgb_uri = ""
        if bool(payload.get("enable_3d_simulation")):
            av_rgb_uri = (
                f"http://127.0.0.1:{self.carla_gateway_port}/frame.jpg?experiment_id={quote(exp_id)}"
            )
        elif world_generation_enabled and av_control_model == "LEAD_TFV6_STREAM":
            av_rgb_uri = str(
                self.root
                / "output"
                / "cosmos"
                / "experiments"
                / exp_id
                / "omnidreams"
                / "camera_front_wide_120fov_latest.jpg"
            )
        cmd = build_neuralnde_generation_command(
            python=self.neuralnde_python,
            script=self.neuralnde_adapter_script,
            neuralnde_root=self.neuralnde_root,
            dataset=dataset,
            output_dir=output_dir,
            experiment_id=exp_id,
            experiment_name=exp_name,
            max_sim_time=max_sim_time,
            host=self.child_host,
            port=port,
            gui_dir=self.gui_dir,
            gpu_id=gpu_id,
            seed=seed,
            realtime=bool(payload.get("realtime", True)),
            av_enabled=bool(payload.get("av_enabled")),
            av_selection_mode=str(payload.get("av_selection_mode") or "random"),
            av_control_model=av_control_model,
            av_command_mode=str(payload.get("av_command_mode") or "state").lower(),
            av_control_host=str(payload.get("av_control_host") or "127.0.0.1"),
            av_control_port=int(payload.get("av_control_port") or 0),
            av_control_timeout=float(payload.get("av_control_timeout") or 0.04),
            av_rgb_uri=av_rgb_uri,
            denseworld_warmup=world_generation_enabled,
            warmup_seconds=float(payload.get("warmup_seconds", 1.0) or 1.0),
            world_sync_state=str(world_sync_path) if world_sync_enabled else "",
            world_video_duration=(
                _world_video_duration_seconds(payload) if world_generation_enabled else 0.0
            ),
            run_until_stopped=run_until_stopped,
        )
        result = self._spawn_experiment(
            exp_id=exp_id,
            model="neuralnde",
            backend_model="neuralnde",
            kind="experiment",
            name=exp_name,
            cmd=cmd,
            cwd=self.neuralnde_root,
            gpu_id=gpu_id,
            port=port,
            map_path=dataset,
            init_mode="official_dataset",
            total_step=total_step,
            max_sim_time=max_sim_time,
            sim_resolution=0.04,
            save_file=str(output_dir / "traffic" / "frames.jsonl"),
            scenario=self._repo_rel(standard_target) if standard_target else "",
            payload=payload,
            initial_status={
                "run_state": "starting",
                "backend_model": "neuralnde",
                "sim_resolution": 0.04,
                "model_resolution": 0.4,
                "progress": 0.0,
            },
        )
        if result.get("ok"):
            with self._lock:
                info = self._experiments.get(exp_id)
                if info is not None:
                    info["output_dir"] = str(output_dir)
            self._start_builtin_av_client(exp_id, payload)
            for kind, path, mime_type in (
                ("neuralnde_summary", output_dir / "summary.json", "application/json"),
                ("neuralnde_frames", output_dir / "traffic" / "frames.jsonl", "application/x-ndjson"),
                ("neuralnde_keyframes", output_dir / "traffic" / "keyframes.pklstream", "application/octet-stream"),
                ("av_control_report", output_dir / "av_control_report.json", "application/json"),
            ):
                self.experiment_store.add_artifact(
                    exp_id,
                    kind=kind,
                    path=self._repo_rel(path),
                    mime_type=mime_type,
                )
            if world_generation_enabled:
                self._start_world_pipeline(exp_id, payload)
                with self._lock:
                    info = self._experiments.get(exp_id)
                if info is not None:
                    result["experiment"] = self.snapshot(exp_id, info)
        return result


    def launch_neuralnde_replay(self, payload: dict) -> dict:
        scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
        if not scenario:
            return {"ok": False, "error": "scenario_path required"}
        source = Path(scenario)
        if not source.is_absolute():
            source = self.root / source
        source = source.resolve()
        experiment_root = (self.root / "output" / "experiments").resolve()
        if (
            not _is_relative_to(source, experiment_root)
            or source.name != "frames.jsonl"
            or not source.is_file()
        ):
            return {
                "ok": False,
                "error": "NeuralNDE replay requires a managed normalized frames.jsonl recording",
            }
        output_dir = source.parent.parent
        config: dict[str, Any] = {}
        config_path = output_dir / "config.json"
        try:
            value = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                config = value
        except (OSError, TypeError, ValueError):
            config = {}
        dataset = str(
            payload.get("map_path")
            or payload.get("dataset")
            or config.get("dataset")
            or "AA_rdbt"
        ).strip()
        if dataset not in {"AA_rdbt", "rounD"}:
            return {"ok": False, "error": f"Unsupported NeuralNDE dataset: {dataset}"}
        exp_id = f"neuralnde_replay_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        map_state_path = output_dir / "map_state.json"
        if not map_state_path.is_file():
            cosmos_map = self.output_root / "cosmos" / "experiments" / output_dir.name / "map_state.json"
            if cosmos_map.is_file():
                map_state_path = cosmos_map
            else:
                preview = self.map_preview("neuralnde", dataset)
                map_state = preview.get("map_state") if isinstance(preview, dict) else None
                if isinstance(map_state, dict):
                    map_state_path = self.runtime_root / f"{exp_id}_map_state.json"
                    map_state_path.parent.mkdir(parents=True, exist_ok=True)
                    map_state_path.write_text(
                        json.dumps(map_state, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8",
                    )
        try:
            with source.open("r", encoding="utf-8") as stream:
                total_steps = sum(1 for line in stream if line.strip())
        except OSError as exc:
            return {"ok": False, "error": f"Failed to read NeuralNDE recording: {exc}"}
        if total_steps <= 0:
            return {"ok": False, "error": "NeuralNDE recording contains no frames"}
        step_seconds = max(0.001, float(config.get("output_resolution", 0.04) or 0.04))
        port = int(payload.get("port") or self._allocate_child_port())
        name = self._safe_name(
            str(payload.get("experiment_name") or output_dir.name),
            fallback="neuralnde_replay",
        )
        command = [
            sys.executable,
            str(self.neuralnde_replay_script),
            "--frames",
            str(source),
            "--dataset",
            dataset,
            "--experiment-name",
            name,
            "--host",
            self.child_host,
            "--port",
            str(port),
            "--gui-dir",
            str(self.gui_dir),
            "--workspace-root",
            str(self.root),
        ]
        if map_state_path.is_file():
            command.extend(["--map-state", str(map_state_path)])
        replay_payload = {
            **payload,
            "backend_model": "neuralnde",
            "scenario_path": str(source),
            "scenario": str(source),
            "map_path": dataset,
            "sim_resolution": step_seconds,
        }
        return self._spawn_experiment(
            exp_id=exp_id,
            model="neuralnde",
            backend_model="neuralnde",
            kind="replay",
            name=name,
            cmd=command,
            cwd=self.root,
            gpu_id="",
            port=port,
            map_path=dataset,
            init_mode="replay",
            total_step=total_steps,
            max_sim_time=max(0.0, (total_steps - 1) * step_seconds),
            sim_resolution=step_seconds,
            save_file=str(source),
            scenario=str(source),
            payload=replay_payload,
            initial_status={
                "run_state": "playback_loading",
                "backend_model": "neuralnde",
                "sim_resolution": step_seconds,
                "replay_step_seconds": step_seconds,
                "replay_total_steps": total_steps,
                "progress": 0.0,
            },
        )


    def _launch_citynde_recorded_world(
        self,
        payload: dict,
        *,
        scenario_target: Path,
        scenario_metadata: dict[str, Any],
    ) -> dict:
        try:
            with scenario_target.open("rb") as stream:
                recording = pickle.load(stream)
            timeline = recording.get("vehicle_id_per_step")
            if timeline is None or len(timeline) < 2:
                raise ValueError("recording contains fewer than two traffic frames")
            resolution = max(
                1e-3,
                float(
                    scenario_metadata.get("sim_resolution")
                    or (recording.get("simulator_meta_info") or {}).get("resolution")
                    or 0.1
                ),
            )
        except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            return {"ok": False, "error": f"Failed to inspect recorded trajectory: {exc}"}

        available_duration = (len(timeline) - 1) * resolution
        requested_duration = _world_video_duration_seconds(payload)
        duration = min(
            available_duration,
            requested_duration if requested_duration > 0.0 else available_duration,
        )
        if duration <= 0.0:
            return {"ok": False, "error": "Recorded trajectory has no usable duration"}

        exp_name = self._safe_name(
            str(payload.get("experiment_name") or scenario_metadata.get("library_name") or "recorded_trajectory"),
            fallback="recorded_trajectory",
        )
        exp_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        port = int(payload.get("port") or self._allocate_child_port())
        gpu_id = str(payload.get("gpu_id") or "").strip()
        payload = self._with_av_port(dict(payload), port)
        payload.update(
            {
                "scenario_execution_mode": "replay",
                "run_until_stopped": False,
                "max_sim_time": duration,
                "total_step": max(1, int(round(duration / resolution))),
                "sim_resolution": resolution,
                "world_video_duration": duration,
                "world_video_follow_traffic": True,
                "recorded_source_duration": available_duration,
            }
        )
        world_sync_path = (
            self.root / "output" / "cosmos" / "experiments" / exp_id / "traffic_video_sync.json"
        )
        update_world_sync(
            world_sync_path,
            stage="waiting_for_seed",
            experiment_id=exp_id,
            requested_traffic_time=0.0,
            generated_video_time=0.0,
        )
        cmd = build_replay_command(
            python=self.citynde_python,
            script=self.citynde_script,
            citynde_root=self.citynde_root,
            scenario=str(scenario_target),
            experiment_name=exp_name,
            host=self.child_host,
            port=port,
            map_path=str(payload.get("map_path") or scenario_metadata.get("map_path") or ""),
            gui_dir=self.gui_dir,
            gpu_id=gpu_id,
            denseworld_warmup=True,
            seed_init_file=str(payload.get("world_seed_init_file") or ""),
            world_seed_ego_id=str(payload.get("world_seed_ego_id") or ""),
            world_sync_state=str(world_sync_path),
            max_sim_time=duration,
        )
        cmd = self._citynde_container_command(cmd, exp_id=exp_id, gpu_id=gpu_id)
        result = self._spawn_experiment(
            exp_id=exp_id,
            model="citynde",
            backend_model="cnde",
            kind="experiment",
            name=exp_name,
            cmd=cmd,
            cwd=self.citynde_root,
            gpu_id=gpu_id,
            port=port,
            map_path=str(payload.get("map_path") or scenario_metadata.get("map_path") or ""),
            init_mode="recorded_replay",
            total_step=int(payload["total_step"]),
            max_sim_time=duration,
            sim_resolution=resolution,
            save_file=self._repo_rel(scenario_target),
            scenario=self._repo_rel(scenario_target),
            payload=payload,
            initial_status={
                "run_state": "starting",
                "backend_model": "cnde",
                "scenario_execution_mode": "replay",
                "recorded_source_duration": available_duration,
                "sim_resolution": resolution,
                "progress": 0.0,
            },
        )
        if result.get("ok"):
            self._start_world_pipeline(exp_id, payload)
            with self._lock:
                info = self._experiments.get(exp_id)
            if info is not None:
                result["experiment"] = self.snapshot(exp_id, info)
        return result

    def launch_citynde_replay(self, payload: dict) -> dict:
        scenario = str(payload.get("scenario_path") or payload.get("scenario") or "").strip()
        if not scenario:
            return {"ok": False, "error": "scenario_path required"}
        scenario_target, scenario_error = self._scenario_target(scenario)
        if scenario_error is not None:
            return scenario_error
        if scenario_target is None or not scenario_target.is_file():
            return {"ok": False, "error": f"Scenario file not found: {scenario}"}
        scenario_metadata = self._citynde_scenario_metadata(scenario_target)
        replay_ego_id = str(
            payload.get("offline_av_id")
            or payload.get("replay_ego_id")
            or scenario_metadata.get("seed_ego_id")
            or scenario_metadata.get("av_id")
            or ""
        )
        scenario = str(scenario_target)
        payload = {
            **payload,
            "scenario_path": scenario,
            "scenario": scenario,
            "offline_av_id": replay_ego_id,
            "replay_ego_id": replay_ego_id,
        }
        gpu_id = str(payload.get("gpu_id") or "").strip()
        offline = bool(payload.get("offline_test"))
        preview = bool(payload.get("offline_preview"))
        exp_id = f"{'offline' if offline else 'replay'}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        name = self._safe_name(Path(scenario).stem, fallback="offline_test" if offline else "replay")
        port = int(payload.get("port") or self._allocate_child_port())
        payload = self._with_av_port(payload, port)
        cmd = build_replay_command(
            python=self.citynde_python,
            script=self.citynde_script,
            citynde_root=self.citynde_root,
            scenario=scenario,
            experiment_name=name,
            host=self.child_host,
            port=port,
            map_path=str(payload.get("map_path") or ""),
            gui_dir=self.gui_dir,
            gpu_id=gpu_id,
        )
        cmd = self._citynde_container_command(cmd, exp_id=exp_id, gpu_id=gpu_id)
        result = self._spawn_experiment(
            exp_id=exp_id,
            model="citynde",
            backend_model="cnde",
            kind="offline" if offline else "replay",
            name=name,
            cmd=cmd,
            cwd=self.citynde_root,
            gpu_id=gpu_id,
            port=port,
            map_path="",
            init_mode="replay",
            total_step=0,
            max_sim_time=0.0,
            save_file=scenario,
            scenario=scenario,
            payload=payload,
            initial_status={
                "run_state": "playback_loading",
                "paused": False,
                "replay_loading": True,
                "offline_test": offline,
                "offline_preview": preview,
                "replay_params": {
                    "scenario_path": scenario,
                    "gpu_id": gpu_id,
                    "offline_test": offline,
                    "offline_preview": preview,
                    "offline_av_id": str(payload.get("offline_av_id") or ""),
                    "replay_ego_id": replay_ego_id,
                    "av_enabled": bool(payload.get("av_enabled")),
                    "av_control_model": str(payload.get("av_control_model") or ""),
                    "av_control_host": str(payload.get("av_control_host") or ""),
                    "av_control_port": payload.get("av_control_port", ""),
                    "marker_scope": str(payload.get("marker_scope") or ""),
                },
                "scenario": scenario,
                "progress": 0.0,
            },
        )
        if result.get("ok"):
            self._auto_start_replay(exp_id, scenario, gpu_id, payload)
            result["loading"] = True
        return result


    def _wait_child_ready(self, exp_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                info = self._experiments.get(exp_id)
            if not info:
                return {"ok": False, "error": f"Experiment not found: {exp_id}"}
            proc = info.get("process")
            if proc is not None and proc.poll() is not None:
                info["return_code"] = proc.poll()
                return {"ok": False, "error": _tail_text(info.get("log_path", "")) or "Replay process exited before ready"}
            status = self._http_json(f"http://127.0.0.1:{info['port']}/status", timeout=0.75)
            if status:
                info["last_status"] = status
                return {"ok": True, "experiment": self.snapshot(exp_id, info)}
            time.sleep(0.4)
        with self._lock:
            info = self._experiments.get(exp_id)
        detail = _tail_text(info.get("log_path", "")) if info else ""
        return {"ok": False, "error": detail or "Timed out waiting for replay child"}

    def _spawn_experiment(
        self,
        *,
        exp_id: str,
        model: str,
        kind: str,
        name: str,
        cmd: list[str],
        cwd: Path,
        gpu_id: str,
        port: int,
        map_path: str,
        init_mode: str,
        total_step: int,
        max_sim_time: float,
        save_file: str,
        scenario: str,
        payload: dict,
        initial_status: dict | None = None,
        backend_model: str | None = None,
        sim_resolution: float = 0.1,
    ) -> dict:
        env = os.environ.copy()
        mpl_cache = self.root / ".cache" / "matplotlib"
        mpl_cache.mkdir(parents=True, exist_ok=True)
        env.setdefault("MPLCONFIGDIR", str(mpl_cache))
        if gpu_id:
            env["CUDA_VISIBLE_DEVICES"] = gpu_id
        log_dir = self.runtime_root / model / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{exp_id}.log"
        log_f = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=log_f, stderr=subprocess.STDOUT, close_fds=True)
        detail_view = "offline" if kind == "offline" else ("replay" if kind == "replay" else "experiment")
        url = f"/?view={detail_view}&experiment_id={quote(exp_id)}"
        if scenario and kind in {"replay", "offline"}:
            url += f"&scenario={quote(scenario)}"
        carla_enabled = bool(payload.get("enable_3d_simulation")) and kind == "experiment"
        if carla_enabled:
            url += "&carla=1"
        info = {
            "id": exp_id,
            "kind": kind,
            "name": name,
            "backend_model": backend_model or model,
            "process": proc,
            "log_file": log_f,
            "log_path": str(log_path),
            "port": int(port),
            "url": url,
            "gpu_id": gpu_id,
            "map_path": map_path,
            "init_mode": init_mode,
            "total_step": int(total_step or 0),
            "max_sim_time": float(max_sim_time or 0.0),
            "run_until_stopped": _traffic_runs_until_stopped(payload),
            "sim_resolution": float(sim_resolution),
            "save_file": save_file,
            "output_dir": "",
            "scenario": scenario,
            "derived_from_path": str(payload.get("derived_from_path") or scenario),
            "av_enabled": bool(payload.get("av_enabled")),
            "av_control_model": str(payload.get("av_control_model") or ""),
            "av_control_host": str(payload.get("av_control_host") or ""),
            "av_control_port": payload.get("av_control_port", ""),
            "av_selection_mode": str(payload.get("av_selection_mode") or ""),
            "av_command_mode": str(payload.get("av_command_mode") or ""),
            "batch_id": str(payload.get("batch_id") or ""),
            "batch_index": int(payload.get("batch_index", 0) or 0),
            "batch_count": int(payload.get("batch_count", 0) or 0),
            "task_id": str(payload.get("task_id") or ""),
            "workflow_id": str(payload.get("workflow_id") or ""),
            "workflow_name": str(payload.get("workflow_name") or ""),
            "save_test_result": bool(payload.get("save_test_result", True)),
            "observations": (
                dict(payload.get("observations") or {})
                if isinstance(payload.get("observations"), dict)
                else {}
            ),
            "camera_config": (
                dict(payload.get("camera_config") or {})
                if isinstance(payload.get("camera_config"), dict)
                else {}
            ),
            "evaluation_config": (
                dict(payload.get("evaluation_config") or {})
                if isinstance(payload.get("evaluation_config"), dict)
                else {}
            ),
            "marker_scope": str(payload.get("marker_scope") or exp_id),
            "last_status": dict(initial_status or {}),
            "last_step": 0,
            "last_vehicles": 0,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "carla_enabled": carla_enabled,
            "carla_state": "starting" if carla_enabled else "disabled",
            "carla_error": "",
            "carla_quality": str(payload.get("carla_quality") or "Epic"),
            "carla_gpu_id": str(payload.get("carla_gpu_id", "1") or "1"),
            "carla_scene_path": str(payload.get("carla_scene_path") or ""),
            "carla_environment_limit": max(0, int(payload.get("carla_environment_limit", 450) or 450)),
            "carla_render_fps": max(5.0, min(30.0, float(payload.get("carla_render_fps", 15) or 15))),
        }
        with self._lock:
            self._experiments[exp_id] = info
        self._write_manifest(model, exp_id, {"cmd": cmd, **payload}, backend_model=backend_model or model)
        if carla_enabled:
            self._start_carla_session(exp_id)
        snapshot = self.snapshot(exp_id, info)
        self.experiment_store.upsert(snapshot, config={"cmd": cmd, **payload})
        return {"ok": True, "experiment": snapshot, "viewer_url": url}

    def _auto_start_replay(self, exp_id: str, scenario: str, gpu_id: str, extra_payload: dict | None = None):
        def _worker():
            deadline = time.time() + 60.0
            extra = dict(extra_payload or {})
            action_type = "start_offline_preview" if extra.get("offline_preview") else "start_playback"
            payload = {
                **extra,
                "type": action_type,
                "scenario": scenario,
                "gpu_id": gpu_id,
                "replay_clock": "client",
            }
            while time.time() < deadline:
                with self._lock:
                    info = self._experiments.get(exp_id)
                if not info:
                    return
                proc = info.get("process")
                if proc is not None and proc.poll() is not None:
                    info["return_code"] = proc.poll()
                    return
                result = self._http_json(f"http://127.0.0.1:{info['port']}/action", method="POST", payload=payload, timeout=3.0)
                if result and result.get("ok"):
                    info["last_status"] = {
                        **(info.get("last_status") if isinstance(info.get("last_status"), dict) else {}),
                        "run_state": result.get("run_state", "idle" if extra.get("offline_preview") else "playback_loading"),
                        "paused": False,
                        "replay_loading": bool(result.get("loading", True)),
                        "offline_test": bool(extra.get("offline_test")),
                        "offline_preview": bool(extra.get("offline_preview")),
                        "replay_params": {
                            "scenario_path": scenario,
                            "gpu_id": gpu_id,
                            "offline_test": bool(extra.get("offline_test")),
                            "offline_preview": bool(extra.get("offline_preview")),
                            "offline_av_id": str(extra.get("offline_av_id") or ""),
                            "replay_ego_id": str(extra.get("replay_ego_id") or ""),
                            "av_enabled": bool(extra.get("av_enabled")),
                            "av_control_model": extra.get("av_control_model", ""),
                            "av_control_host": extra.get("av_control_host", ""),
                            "av_control_port": extra.get("av_control_port", ""),
                        },
                        "scenario": scenario,
                    }
                    return
                time.sleep(0.5)
            with self._lock:
                info = self._experiments.get(exp_id)
            if info:
                info["last_status"] = {
                    **(info.get("last_status") if isinstance(info.get("last_status"), dict) else {}),
                    "run_state": "idle",
                    "paused": False,
                    "replay_loading": False,
                    "last_error": "Replay child did not accept start_playback in time",
                }

        threading.Thread(target=_worker, name=f"ReplayAutoStart-{exp_id}", daemon=True).start()

    def snapshot(self, exp_id: str, info: dict) -> dict:
        kind = info.get("kind", "experiment")
        proc = info.get("process")
        return_code = proc.poll() if proc is not None else info.get("return_code")
        if return_code is not None:
            info["return_code"] = return_code
        status = None
        # A restored or released record has no live child to query. Probing its
        # historical port adds a timeout per row and made replay pages appear hung.
        if return_code is None and proc is not None:
            status = self._http_json(f"http://127.0.0.1:{info['port']}/status", timeout=0.75)
            if status:
                info["last_status"] = status
        status_for_display = status or (info.get("last_status") if isinstance(info.get("last_status"), dict) else {}) or {}
        failed = return_code is not None and int(return_code) != 0
        replay_like = kind in {"replay", "offline"}
        run_state = "running" if return_code is None else ("idle" if replay_like or failed else "completed")
        paused = bool(status_for_display.get("paused", False))
        step = int(info.get("last_step", 0) or 0)
        vehicles = int(info.get("last_vehicles", 0) or 0)
        if status_for_display:
            run_state = str(status_for_display.get("run_state", run_state))
            next_step = int(status_for_display.get("step", step) or 0)
            next_vehicles = int(status_for_display.get("vehicles", vehicles) or 0)
            if return_code is None and next_step < step:
                next_step = step
                next_vehicles = vehicles
            step = next_step
            vehicles = next_vehicles
            info["last_step"] = step
            info["last_vehicles"] = vehicles
        total_step = int(status_for_display.get("total_step") or info.get("total_step") or 0)
        replay_total = int(status_for_display.get("replay_total_steps") or 0)
        sim_resolution = float(status_for_display.get("sim_resolution") or info.get("sim_resolution") or 0.1)
        replay_step_seconds = float(status_for_display.get("replay_step_seconds") or sim_resolution or 0.1)
        progress = status_for_display.get("progress", None)
        if progress is None:
            denom = replay_total if replay_like else total_step
            progress = (float(status_for_display.get("replay_step", step) or step) / float(denom)) if denom else (1.0 if run_state == "completed" else 0.0)
        progress = max(0.0, min(1.0, float(progress or 0.0)))
        if failed:
            run_state = "error"
            paused = False
            progress = 0.0 if step <= 0 else progress
            last_error = status_for_display.get("last_error") or _tail_text(info.get("log_path", ""))
            info["last_status"] = {
                **status_for_display,
                "run_state": "error",
                "paused": False,
                "progress": progress,
                "last_error": last_error,
                "return_code": return_code,
            }
        elif not replay_like and (
            run_state == "completed"
            or bool(status_for_display.get("experiment_completed"))
            or return_code is not None
            or (total_step > 0 and (step >= total_step or progress >= 1.0))
        ):
            run_state = "completed"
            paused = False
            progress = 1.0
            info["last_status"] = {**status_for_display, "run_state": "completed", "paused": False, "experiment_completed": True, "progress": 1.0}
        if replay_like and return_code is not None:
            run_state = "idle"
            paused = False
        replay_params = status_for_display.get("replay_params", {}) if isinstance(status_for_display.get("replay_params", {}), dict) else {}
        scenario = self._normalize_record_path(str(replay_params.get("scenario_path") or replay_params.get("scenario") or info.get("scenario", "")))
        output_dir = self._normalize_record_path(str(status_for_display.get("output_dir") or info.get("output_dir") or ""))
        save_file = self._normalize_record_path(str(status_for_display.get("save_file") or info.get("save_file", "") or output_dir))
        if save_file:
            info["save_file"] = save_file
        if output_dir:
            info["output_dir"] = output_dir
        sim_time = status_for_display.get("sim_time", None)
        if sim_time is None:
            sim_time = float(status_for_display.get("replay_step", step) or step) * (replay_step_seconds if replay_like else sim_resolution)
        if not replay_like and total_step > 0:
            sim_time = min(float(sim_time or 0.0), total_step * sim_resolution)
        world_generation = info.get("world_generation") or self.experiment_store.world_job(exp_id)
        world_state = str((world_generation or {}).get("run_state") or "")
        if world_state == "running":
            run_state = "running"
            paused = False
            progress = max(0.0, min(1.0, float(world_generation.get("progress", 0.0) or 0.0)))
        elif world_state == "error":
            run_state = "error"
            paused = False
            progress = max(0.0, min(1.0, float(world_generation.get("progress", progress) or 0.0)))
        elif world_state == "completed":
            run_state = "completed"
            paused = False
            progress = 1.0
        display_error = str(status_for_display.get("last_error", "") or "")
        if run_state == "error" and world_state == "error":
            display_error = str(world_generation.get("error") or display_error)
        if run_state != "error":
            display_error = ""
        return {
            "id": exp_id,
            "kind": kind,
            "name": info.get("name", exp_id),
            "backend_model": info.get("backend_model", ""),
            "run_state": run_state,
            "paused": paused,
            "step": step,
            "replay_step": status_for_display.get("replay_step", None),
            "replay_total_steps": replay_total,
            "sim_resolution": sim_resolution,
            "replay_step_seconds": replay_step_seconds,
            "sim_time": float(sim_time or 0.0),
            "progress": progress,
            "total_step": total_step,
            "max_sim_time": float(info.get("max_sim_time") or status_for_display.get("max_sim_time") or 0.0),
            "run_until_stopped": bool(
                status_for_display.get("run_until_stopped")
                or info.get("run_until_stopped")
            ),
            "vehicles": vehicles,
            "init_mode": info.get("init_mode", ""),
            "map_path": info.get("map_path", ""),
            "gpu_id": info.get("gpu_id", ""),
            "port": int(info.get("port", 0) or 0),
            "pid": int(proc.pid) if proc is not None else None,
            "child_available": bool(proc is not None and proc.poll() is None),
            "url": info.get("url", ""),
            "save_file": save_file,
            "output_dir": output_dir,
            "scenario": scenario,
            "derived_from_path": self._normalize_record_path(
                str(info.get("derived_from_path") or scenario)
            ),
            "offline_test": bool(status_for_display.get("offline_test") or replay_params.get("offline_test") or kind == "offline"),
            "offline_preview": bool(status_for_display.get("offline_preview") or replay_params.get("offline_preview")),
            "offline_av_id": str(status_for_display.get("offline_av_id") or replay_params.get("offline_av_id") or ""),
            "av_enabled": bool(
                status_for_display.get("av_enabled")
                or replay_params.get("av_enabled")
                or info.get("av_enabled")
            ),
            "av_control_model": str(
                status_for_display.get("av_control_model")
                or replay_params.get("av_control_model")
                or info.get("av_control_model")
                or ""
            ),
            "av_control_host": str(
                status_for_display.get("av_control_host")
                or replay_params.get("av_control_host")
                or info.get("av_control_host")
                or ""
            ),
            "av_control_port": (
                status_for_display.get("av_control_port")
                or replay_params.get("av_control_port")
                or info.get("av_control_port")
                or ""
            ),
            "av_id": str(status_for_display.get("av_id") or replay_params.get("av_id") or ""),
            "av_selection_mode": str(
                status_for_display.get("av_selection_mode")
                or replay_params.get("av_selection_mode")
                or info.get("av_selection_mode")
                or ""
            ),
            "av_command_mode": str(
                status_for_display.get("av_command_mode")
                or replay_params.get("av_command_mode")
                or info.get("av_command_mode")
                or ""
            ),
            "batch_id": str(info.get("batch_id") or ""),
            "batch_index": int(info.get("batch_index", 0) or 0),
            "batch_count": int(info.get("batch_count", 0) or 0),
            "task_id": str(info.get("task_id") or ""),
            "workflow_id": str(info.get("workflow_id") or ""),
            "workflow_name": str(info.get("workflow_name") or ""),
            "save_test_result": bool(info.get("save_test_result", True)),
            "observations": dict(info.get("observations") or {}),
            "camera_config": dict(info.get("camera_config") or {}),
            "evaluation_config": dict(info.get("evaluation_config") or {}),
            "marker_scope": str(info.get("marker_scope") or exp_id),
            "av_control_endpoint": str(status_for_display.get("av_control_endpoint") or replay_params.get("av_control_endpoint") or ""),
            "av_connected": bool(status_for_display.get("av_connected")),
            "av_perception_frame_count": int(status_for_display.get("av_perception_frame_count", 0) or 0),
            "av_command_frame_count": int(status_for_display.get("av_command_frame_count", 0) or 0),
            "av_command_timeout_count": int(status_for_display.get("av_command_timeout_count", 0) or 0),
            "av_command_success_rate": float(status_for_display.get("av_command_success_rate", 0.0) or 0.0),
            "av_command_latency_ms": status_for_display.get("av_command_latency_ms"),
            "av_adapter_state": str(info.get("av_adapter_state") or "external"),
            "av_adapter_error": (
                _tail_text(info.get("av_adapter_log_path", ""))
                if info.get("av_adapter_process") is not None
                and info["av_adapter_process"].poll() not in {None, 0}
                else ""
            ),
            "waiting_for_av_selection": bool(status_for_display.get("waiting_for_av_selection")),
            "termination_reason": str(status_for_display.get("termination_reason") or ""),
            "replay_params": replay_params,
            "started_at": info.get("started_at", ""),
            "return_code": return_code,
            "last_error": display_error,
            "carla_enabled": bool(info.get("carla_enabled")),
            "carla_state": str(info.get("carla_state") or "disabled"),
            "carla_error": str(info.get("carla_error") or ""),
            "world_generation": world_generation,
            "artifacts": self.experiment_store.list_artifacts(exp_id),
        }

    def list_experiments(self) -> list[dict]:
        with self._lock:
            items = list(self._experiments.items())
        active = [self.snapshot(exp_id, info) for exp_id, info in items]
        for record in active:
            self.experiment_store.upsert(record)
        merged = {str(record.get("id")): record for record in self.experiment_store.list() if record.get("id")}
        merged.update({str(record.get("id")): record for record in active if record.get("id")})
        records = sorted(merged.values(), key=lambda record: record.get("started_at", ""), reverse=True)
        return [_compact_experiment_list_record(record) for record in records]

    def get_experiment(self, experiment_id: str) -> dict | None:
        with self._lock:
            info = self._experiments.get(str(experiment_id))
        if info is not None:
            record = self.snapshot(str(experiment_id), info)
            self.experiment_store.upsert(record)
        else:
            record = self.experiment_store.get(str(experiment_id))
        if record is None:
            return None
        compact = _compact_experiment_list_record(record)
        if info is None:
            compact["child_available"] = False
        return compact

    def _ensure_report_traffic_audit(
        self,
        snapshot: dict,
        world_job: dict,
        artifacts: list[dict],
    ) -> tuple[dict[str, Any], str]:
        payload = world_job.get("payload") if isinstance(world_job.get("payload"), dict) else {}
        embedded = payload.get("traffic_safety_audit")
        if isinstance(embedded, dict) and embedded:
            return embedded, ""
        for artifact in artifacts:
            if str(artifact.get("kind") or "") != "traffic_safety_audit":
                continue
            path = (self.root / str(artifact.get("path") or "")).resolve()
            if not _is_relative_to(path, self.root):
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError):
                continue
            if isinstance(value, dict) and value:
                return value, ""

        if str(snapshot.get("backend_model") or "").lower() not in {"cnde", "citynde"}:
            return {}, "当前模型没有可用于离线报告的 CityNDE 记录"
        source, error, _model = self._record_target(str(snapshot.get("save_file") or ""))
        if error is not None or source is None or not source.is_file():
            return {}, str((error or {}).get("error") or "实验场景记录不存在")
        try:
            with source.open("rb") as stream:
                recording = pickle.load(stream)
            id_steps = list(recording.get("vehicle_id_per_step") or [])
            state_steps = list(recording.get("vehicle_state_per_step") or [])
            frame_count = min(len(id_steps), len(state_steps))
            if frame_count < 2:
                raise ValueError("实验场景记录不足两帧")
            simulator = recording.get("simulator_meta_info") or {}
            resolution = float(
                simulator.get("resolution")
                or simulator.get("sim_resolution")
                or snapshot.get("sim_resolution")
                or 0.1
            )
            if not math.isfinite(resolution) or resolution <= 0.0:
                resolution = 0.1
            source_metadata = self._citynde_scenario_metadata(source)
            offset = max(
                0,
                int(source_metadata.get("recording_operational_start_step", 0) or 0),
            )
            if offset >= frame_count - 1:
                offset = 0
            duration = (frame_count - offset - 1) * resolution
            duration = min(100.0, duration)
            source_fps = max(1, int(round(1.0 / resolution)))
            frames, ego_id = recording_to_traffic_frames(
                source,
                duration_seconds=duration,
                ego_id=str(snapshot.get("av_id") or ""),
                source_fps=source_fps,
            )
            safe_id = re.sub(
                r"[^A-Za-z0-9_.-]+", "_", str(snapshot.get("id") or "experiment")
            ).strip("._") or "experiment"
            report_root = self.platform_data_root / "reports" / safe_id
            report_root.mkdir(parents=True, exist_ok=True)
            traffic_path = report_root / "traffic_audit_source.ndjson"
            with traffic_path.open("w", encoding="utf-8") as stream:
                for frame in frames:
                    stream.write(
                        json.dumps(
                            {
                                "sim_time": frame.get("sim_time", 0.0),
                                "ego": frame.get("ego") or {},
                                "vehicles": frame.get("actors") or [],
                                "traffic_lights": frame.get("traffic_lights") or {},
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            audit_path = report_root / "traffic_safety_audit.json"
            audit = audit_traffic_safety(
                traffic_path,
                audit_path,
                expected_fps=float(source_fps),
                require_local_density=True,
            )
            self._add_world_artifact(
                str(snapshot.get("id") or ""),
                "report_traffic_stream",
                traffic_path,
                mime_type="application/x-ndjson",
                metadata={
                    "frames": len(frames),
                    "duration_seconds": duration,
                    "ego_id": ego_id,
                    "source_fps": source_fps,
                },
            )
            self._add_world_artifact(
                str(snapshot.get("id") or ""),
                "traffic_safety_audit",
                audit_path,
                mime_type="application/json",
                metadata={"passed": audit.get("passed"), "checks": audit.get("checks") or {}},
            )
            return audit, ""
        except (OSError, TypeError, ValueError, pickle.UnpicklingError) as exc:
            return {}, str(exc)

    @staticmethod
    def _aggregate_batch_reports(batch: dict, reports: list[dict]) -> dict:
        valid = [report for report in reports if report.get("ok")]
        overall_scores = [
            float(report["evaluation"]["overall_score"])
            for report in valid
            if (report.get("evaluation") or {}).get("overall_score") is not None
        ]
        categories: dict[str, dict] = {}
        metric_values: dict[str, list[float]] = {}
        metric_names: dict[str, str] = {}
        for report in valid:
            for category_id, category in ((report.get("evaluation") or {}).get("categories") or {}).items():
                if category.get("score") is not None:
                    categories.setdefault(category_id, {"name": category.get("name"), "scores": []})["scores"].append(float(category["score"]))
                for metric in category.get("metrics") or []:
                    value = metric.get("value")
                    if metric.get("status") != "measured" or not isinstance(value, (int, float)):
                        continue
                    metric_id = str(metric.get("id") or "")
                    metric_values.setdefault(metric_id, []).append(float(value))
                    metric_names[metric_id] = str(metric.get("name") or metric_id)
        return {
            "batch_id": str(batch.get("id") or ""),
            "scenario_count": int(batch.get("scenario_count") or 0),
            "included_experiments": len(valid),
            "failed_count": int(batch.get("failed_count") or 0),
            "overall_score": round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else None,
            "categories": {
                key: {
                    "name": value.get("name"),
                    "score": round(sum(value["scores"]) / len(value["scores"]), 2),
                }
                for key, value in categories.items()
                if value.get("scores")
            },
            "metrics": {
                key: {
                    "name": metric_names.get(key, key),
                    "value": round(sum(values), 4) if key == "av_overlap_frames" else round(sum(values) / len(values), 4),
                    "aggregation": "sum" if key == "av_overlap_frames" else "mean",
                    "samples": len(values),
                }
                for key, values in metric_values.items()
                if values
            },
        }

    def experiment_report(self, experiment_id: str, *, include_batch: bool = True) -> dict:
        experiment_id = str(experiment_id or "").strip()
        if not experiment_id:
            return {"ok": False, "error": "experiment_id is required"}
        with self._lock:
            info = self._experiments.get(experiment_id)
        snapshot = self.snapshot(experiment_id, info) if info is not None else self.experiment_store.get(experiment_id)
        if snapshot is None:
            return {"ok": False, "error": "Experiment not found"}

        config = self.experiment_store.get_config(experiment_id)
        world_job = self.experiment_store.world_job(experiment_id)
        artifacts = self.experiment_store.list_artifacts(experiment_id)
        traffic_audit, audit_error = self._ensure_report_traffic_audit(
            snapshot, world_job, artifacts
        )
        if traffic_audit:
            world_job = dict(world_job)
            payload = dict(world_job.get("payload") or {})
            payload["traffic_safety_audit"] = traffic_audit
            world_job["payload"] = payload
            self.accident_store.sync_audit(snapshot, traffic_audit)
            artifacts = self.experiment_store.list_artifacts(experiment_id)
        report = build_experiment_report(snapshot, config, world_job, artifacts)
        batch_id = str(snapshot.get("batch_id") or "")
        if include_batch and batch_id:
            batch = next(
                (item for item in self.experiment_store.list_batches(limit=1000) if str(item.get("id")) == batch_id),
                None,
            )
            if batch is not None:
                member_reports = [
                    self.experiment_report(str(member_id), include_batch=False)
                    for member_id in batch.get("experiment_ids") or []
                ]
                report["batch_aggregate"] = self._aggregate_batch_reports(batch, member_reports)
        if audit_error:
            report["warnings"].append(f"离线交通审计未生成：{audit_error}")
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", experiment_id).strip("._") or "experiment"
        report_path = self.platform_data_root / "reports" / safe_id / "report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report["artifact_path"] = self._normalize_record_path(str(report_path))
        report["execution"]["artifact_count"] = len(
            {str(item.get("path") or "") for item in artifacts} | {str(report["artifact_path"])}
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.experiment_store.add_artifact(
            experiment_id,
            kind="experiment_report",
            path=str(report_path),
            mime_type="application/json",
            metadata={
                "schema": report["schema"],
                "overall_score": report["evaluation"]["overall_score"],
                "coverage": report["evaluation"]["coverage"],
                "provisional": report["evaluation"]["provisional"],
            },
        )
        return report

    def pause_experiments(self, ids: list[str]) -> dict:
        acted = []
        for exp_id in ids:
            with self._lock:
                info = self._experiments.get(exp_id)
            if not info:
                continue
            if self._http_json(f"http://127.0.0.1:{info['port']}/pause", method="POST", payload={}) is not None:
                acted.append(exp_id)
        return {"ok": True, "paused": acted}

    def control_latest_experiment(self, control: str) -> dict:
        if control not in {"pause", "resume"}:
            return {"ok": False, "error": f"Unsupported control: {control}"}
        with self._lock:
            items = list(self._experiments.items())
        if not items:
            return {"ok": False, "error": "No active experiment"}
        snapshots = [(exp_id, info, self.snapshot(exp_id, info)) for exp_id, info in items]
        candidates = [
            item for item in snapshots
            if item[2].get("run_state") in {"running", "playback", "playback_loading"}
        ] or snapshots
        exp_id, info, _snapshot = sorted(candidates, key=lambda item: item[2].get("started_at", ""), reverse=True)[0]
        ok = self._http_json(f"http://127.0.0.1:{info['port']}/{control}", method="POST", payload={}) is not None
        return {"ok": ok, "experiment_id": exp_id, "control": control}

    def terminate_experiments(self, ids: list[str], *, save_data: bool = True) -> dict:
        acted = []
        for exp_id in ids:
            with self._lock:
                info = self._experiments.get(exp_id)
            if not info:
                continue
            cancel_event = getattr(self, "_world_cancel_events", {}).get(exp_id)
            if cancel_event is not None:
                cancel_event.set()
                previous_world = dict(
                    info.get("world_generation")
                    or self.experiment_store.world_job(exp_id)
                    or {}
                )
                self._set_world_job(
                    exp_id,
                    stage="stopped",
                    run_state="stopped",
                    progress=float(previous_world.get("progress", 0.0) or 0.0),
                    message="World generation stopped by the user",
                    payload={"termination_reason": "user_requested"},
                )
            proc = info.get("process")
            self._http_json(
                f"http://127.0.0.1:{info['port']}/action",
                method="POST",
                payload={"type": "terminate_experiment", "save_data": bool(save_data)},
                timeout=6.0,
            )
            info["save_test_result"] = bool(save_data)
            status = self._http_json(f"http://127.0.0.1:{info['port']}/status", timeout=0.75)
            if status:
                info["last_status"] = status
            if proc is not None and proc.poll() is not None:
                info["return_code"] = proc.poll()
            self._stop_carla_session(exp_id)
            terminal_state = (
                "stopped"
                if str(info.get("kind") or "") in {"replay", "offline", "cosmos_transfer"}
                else "completed"
            )
            self._release_batch_process(exp_id, terminal_state)
            acted.append(exp_id)
        return {"ok": True, "terminated": acted, "save_data": bool(save_data)}

    def delete_experiments(self, ids: list[str]) -> dict:
        deleted = []
        for exp_id in ids:
            with self._lock:
                info = self._experiments.pop(exp_id, None)
            if not info:
                deleted.append(exp_id)
                continue
            self._stop_carla_session(exp_id)
            proc = info.get("process")
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            log_f = info.get("log_file")
            try:
                if log_f:
                    log_f.close()
            except Exception:
                pass
            deleted.append(exp_id)
        self.experiment_store.delete(deleted)
        return {"ok": True, "deleted": deleted}

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._world_stop.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        with self._lock:
            items = list(self._experiments.items())
            self._experiments.clear()
        for exp_id, info in items:
            snapshot = self.snapshot(exp_id, info)
            if snapshot.get("run_state") in {"starting", "warming_up", "world_seed_pending", "running", "playback", "playback_loading"}:
                snapshot.update(
                    {
                        "run_state": "interrupted",
                        "paused": False,
                        "termination_reason": "manager_shutdown",
                    }
                )
            self.experiment_store.upsert(snapshot)
            self._stop_carla_session(exp_id)
            proc = info.get("process")
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            log_f = info.get("log_file")
            if log_f:
                try:
                    log_f.close()
                except Exception:
                    pass
        if self._carla_gateway_process is not None and self._carla_gateway_process.poll() is None:
            try:
                self._carla_gateway_process.terminate()
                self._carla_gateway_process.wait(timeout=8.0)
            except subprocess.TimeoutExpired:
                self._carla_gateway_process.kill()
        if self._carla_gateway_log is not None:
            self._carla_gateway_log.close()
        self.cosmos.close()
        self.experiment_store.close()
        print("[Manager] Server stopped.")


def main(argv: list[str] | None = None):
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="TrafficWM unified GUI manager")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8890")))
    parser.add_argument("--gui_dir", default=str(root / "GUI"))
    parser.add_argument("--child_host", default=os.environ.get("CHILD_HOST", "127.0.0.1"))
    parser.add_argument("--child_port_start", type=int, default=int(os.environ.get("CHILD_PORT_START", "8900")))
    parser.add_argument("--citynde_root", default=str(root / "algorithm_sources" / "CityNDE_src"))
    parser.add_argument(
        "--neuralnde_root",
        default=os.environ.get(
            "NEURALNDE_ROOT",
            str(root / "algorithm_sources" / "NeuralNDE")
            if (root / "algorithm_sources" / "NeuralNDE").is_dir()
            else "/mnt/rk/cnde/Learning-Naturalistic-Driving-Environment",
        ),
    )
    parser.add_argument("--citynde_python", default=os.environ.get("CITYNDE_PYTHON", sys.executable))
    parser.add_argument("--neuralnde_python", default=os.environ.get("NEURALNDE_PYTHON", ""))
    parser.add_argument("--carla_python", default=os.environ.get("CARLA_PYTHON", str(root / "envs" / "carla" / "bin" / "python")))
    parser.add_argument("--carla_gateway_port", type=int, default=int(os.environ.get("CARLA_GATEWAY_PORT", "8892")))
    parser.add_argument("--carla_root", default=os.environ.get("CARLA_ROOT", "/data/rk/cnde/CARLA_0.9.16"))
    parser.add_argument(
        "--cosmos_autostart",
        action="store_true",
        default=os.environ.get("COSMOS_AUTOSTART", "").strip().lower() in {"1", "true", "yes"},
    )
    parser.add_argument("--no_cosmos_autostart", action="store_false", dest="cosmos_autostart")
    parser.add_argument("--transfer_root", default=os.environ.get("COSMOS_TRANSFER_ROOT", "/mnt/rk/cosmos/cosmos_transfer2.5/cosmos-transfer2.5"))
    parser.add_argument("--omnidreams_root", default=os.environ.get("OMNIDREAMS_ROOT", "/mnt/rk/cosmos/flashdreams"))
    parser.add_argument("--transfer_gpus", default=os.environ.get("COSMOS_TRANSFER_GPUS", "0,1,2,3"))
    parser.add_argument(
        "--anchor_transfer_gpus",
        default=os.environ.get("COSMOS_ANCHOR_TRANSFER_GPUS", ""),
    )
    parser.add_argument("--omnidreams_gpus", default=os.environ.get("OMNIDREAMS_GPUS", "7"))
    parser.add_argument("--transfer_port", type=int, default=int(os.environ.get("COSMOS_TRANSFER_PORT", "8895")))
    parser.add_argument(
        "--anchor_transfer_port",
        type=int,
        default=int(os.environ.get("COSMOS_ANCHOR_TRANSFER_PORT", "8896")),
    )
    parser.add_argument("--omnidreams_port", type=int, default=int(os.environ.get("OMNIDREAMS_PORT", "50051")))
    parser.add_argument(
        "--omnidreams_profile",
        choices=("quality", "realtime", "realtime_fast"),
        default=os.environ.get("OMNIDREAMS_PROFILE", "quality"),
    )
    parser.add_argument(
        "--omnidreams_pipeline_config",
        default=os.environ.get(
            "OMNIDREAMS_PIPELINE_CONFIG",
            "omnidreams-sv-2steps-chunk2-loc6-vae-vae",
        ),
    )
    parser.add_argument(
        "--omnidreams_checkpoint_path",
        default=os.environ.get("OMNIDREAMS_CHECKPOINT_PATH", ""),
    )
    parser.add_argument("--transfer_container_image", default=os.environ.get("COSMOS_TRANSFER_CONTAINER_IMAGE", "trafficwm-cosmos-runtime:cu128"))
    parser.add_argument("--transfer_container_venv", default=os.environ.get("COSMOS_TRANSFER_CONTAINER_VENV", "cosmos-transfer25-venv"))
    args = parser.parse_args(argv)
    server = ManagerServer(
        root=root,
        host=args.host,
        port=args.port,
        gui_dir=Path(args.gui_dir),
        child_host=args.child_host,
        child_port_start=args.child_port_start,
        citynde_root=Path(args.citynde_root),
        neuralnde_root=Path(args.neuralnde_root),
        citynde_python=args.citynde_python,
        neuralnde_python=args.neuralnde_python or None,
        carla_python=args.carla_python,
        carla_gateway_port=args.carla_gateway_port,
        carla_root=Path(args.carla_root),
        cosmos_autostart=args.cosmos_autostart,
        transfer_root=Path(args.transfer_root),
        omnidreams_root=Path(args.omnidreams_root),
        transfer_gpus=args.transfer_gpus,
        anchor_transfer_gpus=args.anchor_transfer_gpus,
        omnidreams_gpus=args.omnidreams_gpus,
        transfer_port=args.transfer_port,
        anchor_transfer_port=args.anchor_transfer_port,
        omnidreams_port=args.omnidreams_port,
        omnidreams_profile=args.omnidreams_profile,
        omnidreams_pipeline_config=args.omnidreams_pipeline_config,
        omnidreams_checkpoint_path=args.omnidreams_checkpoint_path,
        transfer_container_image=args.transfer_container_image,
        transfer_container_venv=args.transfer_container_venv,
    )
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.close()


if __name__ == "__main__":
    main()
