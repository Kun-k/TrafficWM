"""Stream TrafficWM trajectories through a resident OmniDreams gRPC server."""
from __future__ import annotations

import argparse
import bisect
import fcntl
import io
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Sequence

import grpc
from omnidreams.grpc.protos import camera_pb2, common_pb2, video_model_pb2, video_model_pb2_grpc
from PIL import Image, ImageEnhance, ImageFilter

from backend.cosmos.camera_calibration import omnidreams_camera_calibration
from backend.cosmos.pipeline_utils import omnidreams_session_frame_budget
from backend.cosmos.world_sync import read_world_sync, update_world_sync


_GRPC_OPTIONS = (
    ("grpc.max_send_message_length", 100 * 1024 * 1024),
    ("grpc.max_receive_message_length", 100 * 1024 * 1024),
    ("grpc.enable_http_proxy", 0),
)


@contextmanager
def _exclusive_inference_slot(spec: dict[str, Any]):
    """Serialize clients because the resident server owns one active session."""
    server = str(spec.get("server") or "127.0.0.1:50051")
    safe_server = "".join(char if char.isalnum() else "_" for char in server)
    configured_path = str(os.environ.get("COSMOS_OMNIDREAMS_INFERENCE_LOCK") or "").strip()
    lock_path = Path(configured_path or f"/tmp/trafficwm-omnidreams-{safe_server}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    wait_started = time.perf_counter()
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        print(
            f"Waiting for exclusive OmniDreams inference slot: {lock_path}",
            file=sys.stderr,
            flush=True,
        )
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        waited_seconds = time.perf_counter() - wait_started
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "server": server,
                    "output_dir": str(spec.get("output_dir") or ""),
                    "acquired_at": time.time(),
                    "queue_wait_seconds": round(waited_seconds, 4),
                },
                ensure_ascii=False,
            )
        )
        lock_file.flush()
        print(
            f"Acquired OmniDreams inference slot after {waited_seconds:.3f}s",
            file=sys.stderr,
            flush=True,
        )
        try:
            yield waited_seconds
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _disable_local_grpc_proxy() -> None:
    for key in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "grpc_proxy",
        "GRPC_PROXY",
    ):
        os.environ.pop(key, None)
    no_proxy = [item for item in os.environ.get("NO_PROXY", "").split(",") if item]
    for item in ("127.0.0.1", "localhost", "::1"):
        if item not in no_proxy:
            no_proxy.append(item)
    os.environ["NO_PROXY"] = ",".join(no_proxy)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    os.environ["GRPC_ARG_ENABLE_HTTP_PROXY"] = "0"


def _open_channel(server: str, timeout_seconds: float):
    channel = grpc.insecure_channel(server, options=_GRPC_OPTIONS)
    try:
        grpc.channel_ready_future(channel).result(timeout=timeout_seconds)
    except BaseException:
        channel.close()
        raise
    return channel, video_model_pb2_grpc.WorldModelServiceStub(channel)


def _prepare_rollover_frame(
    data: bytes,
    *,
    sharpen_percent: int,
    chroma_blur_radius: float = 0.0,
    saturation_percent: int = 100,
    image_format: str = "JPEG",
) -> bytes:
    """Prepare a generated frame for reuse without amplifying chroma artifacts."""
    sharpen_percent = max(0, min(100, int(sharpen_percent)))
    chroma_blur_radius = max(0.0, min(4.0, float(chroma_blur_radius)))
    saturation_percent = max(0, min(150, int(saturation_percent)))
    image_format = str(image_format or "JPEG").strip().upper()
    if image_format not in {"JPEG", "PNG"}:
        raise ValueError("rollover image format must be JPEG or PNG")
    if (
        sharpen_percent <= 0
        and chroma_blur_radius <= 0.0
        and saturation_percent == 100
        and image_format == "JPEG"
    ):
        return data
    with Image.open(io.BytesIO(data)) as source:
        restored = source.convert("RGB")
        if chroma_blur_radius > 0.0:
            luminance, chroma_blue, chroma_red = restored.convert("YCbCr").split()
            chroma_blue = chroma_blue.filter(ImageFilter.GaussianBlur(chroma_blur_radius))
            chroma_red = chroma_red.filter(ImageFilter.GaussianBlur(chroma_blur_radius))
            restored = Image.merge("YCbCr", (luminance, chroma_blue, chroma_red)).convert("RGB")
        if saturation_percent != 100:
            restored = ImageEnhance.Color(restored).enhance(saturation_percent / 100.0)
        if sharpen_percent > 0:
            restored = restored.filter(
                ImageFilter.UnsharpMask(radius=1.2, percent=sharpen_percent, threshold=3)
            )
        output = io.BytesIO()
        if image_format == "PNG":
            restored.save(output, format="PNG", compress_level=3)
        else:
            restored.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()


def _wait_for_external_transfer_anchor(
    manifest_path: Path,
    target_frame: int,
    *,
    timeout_seconds: float,
    poll_seconds: float = 0.25,
) -> tuple[bytes, int, dict[str, Any]]:
    """Wait for the exact geometry-matched Transfer anchor published by the manager."""
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    last_status = "manifest_missing"
    while time.monotonic() < deadline:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            time.sleep(max(0.05, float(poll_seconds)))
            continue
        manifest_error = str(manifest.get("error") or "").strip()
        if manifest_error:
            raise RuntimeError(f"Transfer anchor producer failed: {manifest_error}")
        anchors = manifest.get("anchors") or []
        entry = next(
            (
                item
                for item in anchors
                if isinstance(item, dict)
                and int(item.get("target_frame", -1) or -1) == int(target_frame)
            ),
            None,
        )
        if entry is None:
            last_status = "anchor_not_scheduled"
            if bool(manifest.get("completed")):
                break
            time.sleep(max(0.05, float(poll_seconds)))
            continue
        last_status = str(entry.get("status") or "pending").strip().lower()
        if last_status == "error":
            raise RuntimeError(
                f"Transfer anchor {target_frame} failed: "
                f"{str(entry.get('error') or 'unknown producer error')}"
            )
        if last_status != "ready":
            time.sleep(max(0.05, float(poll_seconds)))
            continue
        image_value = str(entry.get("image_path") or "").strip()
        image_path = Path(image_value)
        if not image_path.is_absolute():
            image_path = (manifest_path.parent / image_path).resolve()
        try:
            data = image_path.read_bytes()
            with Image.open(io.BytesIO(data)) as image:
                source_format = str(image.format or "").strip().upper()
                image.verify()
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Transfer anchor {target_frame} is not a decodable image: {image_path}"
            ) from exc
        if source_format not in {"JPEG", "PNG"}:
            raise ValueError(
                f"Transfer anchor {target_frame} must be JPEG or PNG, got {source_format}"
            )
        frame_format = (
            video_model_pb2.ImageFormat.PNG
            if source_format == "PNG"
            else video_model_pb2.ImageFormat.JPEG
        )
        return data, frame_format, {**entry, "image_path": str(image_path)}
    raise TimeoutError(
        f"Timed out waiting for Transfer anchor at output frame {target_frame} "
        f"({last_status}): {manifest_path}"
    )


def _yaw_quat(yaw: float) -> common_pb2.Quat:
    return common_pb2.Quat(w=math.cos(yaw / 2.0), x=0.0, y=0.0, z=math.sin(yaw / 2.0))


def _pose(value: dict[str, Any]) -> common_pb2.Pose:
    return common_pb2.Pose(
        vec=common_pb2.Vec3(x=float(value.get("x", 0.0)), y=float(value.get("y", 0.0)), z=float(value.get("z", 0.0))),
        quat=_yaw_quat(float(value.get("heading", 0.0))),
    )


def _actor_center_pose(value: dict[str, Any]) -> common_pb2.Pose:
    """Convert a ground-contact actor state to OmniDreams' box-center pose."""
    centered = dict(value)
    centered["z"] = float(value.get("z", 0.0)) + 0.5 * max(
        0.2, float(value.get("height", 1.6))
    )
    return _pose(centered)


def _angle_lerp(first: float, second: float, ratio: float) -> float:
    delta = (second - first + math.pi) % (2.0 * math.pi) - math.pi
    return first + delta * ratio


def _velocity(state: dict[str, Any]) -> tuple[float, float]:
    try:
        if state.get("vx") is not None and state.get("vy") is not None:
            return float(state["vx"]), float(state["vy"])
    except (TypeError, ValueError):
        pass
    speed = float(state.get("speed", 0.0) or 0.0)
    heading = float(state.get("heading", 0.0) or 0.0)
    return speed * math.cos(heading), speed * math.sin(heading)


def _lerp_state(
    first: dict[str, Any], second: dict[str, Any], ratio: float, span: float = 0.0
) -> dict[str, Any]:
    result = dict(first)
    for key in ("z", "speed", "length", "width", "height"):
        result[key] = float(first.get(key, second.get(key, 0.0))) + (
            float(second.get(key, first.get(key, 0.0))) - float(first.get(key, second.get(key, 0.0)))
        ) * ratio
    has_motion = all(
        state.get("speed") is not None
        or (state.get("vx") is not None and state.get("vy") is not None)
        for state in (first, second)
    )
    if span > 0.0 and has_motion:
        first_velocity = _velocity(first)
        second_velocity = _velocity(second)
        t2, t3 = ratio * ratio, ratio * ratio * ratio
        h00, h10 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + ratio
        h01, h11 = -2 * t3 + 3 * t2, t3 - t2
        for index, key in enumerate(("x", "y")):
            start = float(first.get(key, second.get(key, 0.0)))
            end = float(second.get(key, first.get(key, 0.0)))
            result[key] = h00 * start + h10 * span * first_velocity[index] + h01 * end + h11 * span * second_velocity[index]
    else:
        for key in ("x", "y"):
            result[key] = float(first.get(key, second.get(key, 0.0))) + (
                float(second.get(key, first.get(key, 0.0))) - float(first.get(key, second.get(key, 0.0)))
            ) * ratio
    result["heading"] = _angle_lerp(float(first.get("heading", 0.0)), float(second.get("heading", 0.0)), ratio)
    return result


def _extrapolate_state(state: dict[str, Any], seconds: float) -> dict[str, Any]:
    result = dict(state)
    vx, vy = _velocity(state)
    result["x"] = float(state.get("x", 0.0) or 0.0) + vx * seconds
    result["y"] = float(state.get("y", 0.0) or 0.0) + vy * seconds
    return result


def _sample_frame(frames: list[dict[str, Any]], target_time: float) -> dict[str, Any]:
    times = [float(frame.get("sim_time", index)) for index, frame in enumerate(frames)]
    right = bisect.bisect_left(times, target_time)
    if right <= 0:
        return frames[0]
    if right >= len(frames):
        return frames[-1]
    left = right - 1
    span = max(1e-9, times[right] - times[left])
    ratio = max(0.0, min(1.0, (target_time - times[left]) / span))
    first, second = frames[left], frames[right]
    first_actors = {str(item.get("id")): item for item in _frame_actors(first)}
    second_actors = {str(item.get("id")): item for item in _frame_actors(second)}
    actors = [
        {"id": actor_id, **_lerp_state(first_actors[actor_id], second_actors[actor_id], ratio, span)}
        for actor_id in sorted(first_actors.keys() & second_actors.keys())
    ]
    actors.extend(
        {"id": actor_id, **_extrapolate_state(first_actors[actor_id], ratio * span)}
        for actor_id in sorted(first_actors.keys() - second_actors.keys())
    )
    actors.extend(
        {"id": actor_id, **_extrapolate_state(second_actors[actor_id], -(1.0 - ratio) * span)}
        for actor_id in sorted(second_actors.keys() - first_actors.keys())
    )
    return {
        "sim_time": target_time,
        "ego": _lerp_state(first.get("ego") or {}, second.get("ego") or {}, ratio, span),
        "actors": actors,
        "traffic_lights": (
            dict(first.get("traffic_lights") or {})
            if ratio < 0.5
            else dict(second.get("traffic_lights") or {})
        ),
    }


def _frame_actors(frame: dict[str, Any]) -> list[dict[str, Any]]:
    actors: dict[str, dict[str, Any]] = {}
    for key in ("actors", "vehicles", "cyclists", "pedestrians"):
        for item in frame.get(key) or []:
            if isinstance(item, dict) and item.get("id") is not None:
                actors[str(item["id"])] = item
    return list(actors.values())


def _read_traffic_frames(path: Path) -> list[dict[str, Any]]:
    try:
        frames = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return frames if isinstance(frames, list) else []


class _TrafficFrameReader:
    def __init__(
        self,
        json_path: Path,
        stream_path: Path | None = None,
        *,
        max_stream_frames: int = 12000,
    ):
        self.json_path = Path(json_path)
        self.stream_path = Path(stream_path) if stream_path is not None else None
        self.frames: list[dict[str, Any]] = []
        self._stream_offset = 0
        self._pending = ""
        self.max_stream_frames = max(16, int(max_stream_frames))

    def _read_stream(self) -> None:
        if self.stream_path is None:
            return
        try:
            size = self.stream_path.stat().st_size
            if size < self._stream_offset:
                self.frames = []
                self._stream_offset = 0
                self._pending = ""
            with self.stream_path.open("r", encoding="utf-8") as stream:
                stream.seek(self._stream_offset)
                chunk = stream.read()
                self._stream_offset = stream.tell()
        except OSError:
            return
        if not chunk:
            return
        lines = (self._pending + chunk).split("\n")
        self._pending = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            if not isinstance(frame, dict):
                continue
            sim_time = float(frame.get("sim_time", 0.0) or 0.0)
            if not self.frames or sim_time > float(self.frames[-1].get("sim_time", -1.0)) + 1e-9:
                self.frames.append(frame)
        if len(self.frames) > self.max_stream_frames:
            del self.frames[:-self.max_stream_frames]

    def read(self) -> list[dict[str, Any]]:
        self._read_stream()
        if not self.frames:
            self.frames = _read_traffic_frames(self.json_path)
        return self.frames


def _read_capture_status(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _wait_for_traffic_frames(
    path: Path,
    *,
    min_time: float,
    live: bool,
    timeout_seconds: float,
    capture_status_path: Path | None = None,
    reader: _TrafficFrameReader | None = None,
    allow_terminal_shortfall: bool = False,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    last_frames: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        capture_status = _read_capture_status(capture_status_path)
        capture_error = str(capture_status.get("error") or "").strip()
        capture_terminal = str(capture_status.get("stage") or "").strip().lower() in {
            "completed",
            "stopped",
            "interrupted",
            "cancelled",
        }
        if live and capture_error:
            raise RuntimeError(f"Live traffic capture failed: {capture_error}")
        frames = reader.read() if reader is not None else _read_traffic_frames(path)
        if frames:
            last_frames = frames
            last_time = max(float(frame.get("sim_time", 0.0) or 0.0) for frame in frames)
            if not live or last_time + 1e-6 >= min_time:
                if len(frames) == 1:
                    duplicate = dict(frames[0])
                    duplicate["sim_time"] = float(frames[0].get("sim_time", 0.0) or 0.0) + 0.1
                    return [frames[0], duplicate]
                return frames
            if allow_terminal_shortfall and capture_terminal:
                return frames
        if not live:
            break
        time.sleep(0.25)
    if last_frames:
        last_time = max(float(frame.get("sim_time", 0.0) or 0.0) for frame in last_frames)
        if live and last_time + 1e-6 < min_time:
            raise TimeoutError(
                f"Traffic frames at {path} ended at {last_time:.3f}s before required {min_time:.3f}s"
            )
        return last_frames
    raise TimeoutError(f"Timed out waiting for traffic frames at {path}")


def _class_id(actor: dict[str, Any]) -> int:
    value = " ".join(
        str(actor.get(key) or "").lower()
        for key in ("type", "class", "road_user_type", "vehicle_class")
    )
    if "truck" in value or "bus" in value:
        return video_model_pb2.ActorClassId.TRUCK
    if "ped" in value or "person" in value:
        return video_model_pb2.ActorClassId.PEDESTRIAN
    if "cycl" in value or "bike" in value:
        return video_model_pb2.ActorClassId.CYCLIST
    return video_model_pb2.ActorClassId.CAR


def _actor_control_clearance(actor: dict[str, Any], vehicle_clearance_m: float) -> float:
    """Keep vulnerable road users visible until their boxes actually reach the ego."""
    class_id = _class_id(actor)
    if class_id == video_model_pb2.ActorClassId.PEDESTRIAN:
        return 0.0
    if class_id == video_model_pb2.ActorClassId.CYCLIST:
        return min(0.5, max(0.0, float(vehicle_clearance_m)))
    return max(0.0, float(vehicle_clearance_m))


def _stationary_actor_signature(
    sample: dict[str, Any],
    actor_ids: set[str],
) -> dict[str, tuple[float, float, float]]:
    """Capture authoritative poses for actors represented in the last chunk."""
    if not actor_ids:
        return {}
    return {
        str(actor.get("id")): (
            float(actor.get("x", 0.0)),
            float(actor.get("y", 0.0)),
            float(actor.get("heading", 0.0)),
        )
        for actor in _frame_actors(sample)
        if str(actor.get("id")) in actor_ids
    }


def _stationary_actor_signatures_match(
    reference: dict[str, tuple[float, float, float]],
    current: dict[str, tuple[float, float, float]],
    *,
    position_tolerance_m: float = 0.75,
    heading_tolerance_rad: float = math.radians(12.0),
) -> bool:
    if reference.keys() != current.keys():
        return False
    for actor_id, (x, y, heading) in reference.items():
        current_x, current_y, current_heading = current[actor_id]
        if math.hypot(current_x - x, current_y - y) > position_tolerance_m:
            return False
        heading_delta = abs((current_heading - heading + math.pi) % (2.0 * math.pi) - math.pi)
        if heading_delta > heading_tolerance_rad:
            return False
    return True


def _trajectory(samples: Sequence[dict[str, Any]], timestamps: Sequence[int], key: str) -> common_pb2.Trajectory:
    return common_pb2.Trajectory(
        poses=[common_pb2.PoseAtTime(timestamp_us=timestamp, pose=_pose(sample.get(key) or {})) for sample, timestamp in zip(samples, timestamps)]
    )


def _actor_control_hazard(
    actor: dict[str, Any],
    ego: dict[str, Any],
    *,
    hood_occlusion_distance_m: float,
    hood_occlusion_lateral_m: float,
    oncoming_lateral_exclusion_m: float,
) -> bool:
    """Return whether a vehicle box would create an unstable front-view control."""
    actor_class = _class_id(actor)
    if actor_class not in {
        video_model_pb2.ActorClassId.CAR,
        video_model_pb2.ActorClassId.TRUCK,
    }:
        return False

    dx = float(actor.get("x", 0.0)) - float(ego.get("x", 0.0))
    dy = float(actor.get("y", 0.0)) - float(ego.get("y", 0.0))
    ego_heading = float(ego.get("heading", 0.0))
    cos_ego, sin_ego = math.cos(ego_heading), math.sin(ego_heading)
    forward = cos_ego * dx + sin_ego * dy
    lateral = -sin_ego * dx + cos_ego * dy
    heading_delta = float(actor.get("heading", 0.0)) - ego_heading
    cos_delta, sin_delta = abs(math.cos(heading_delta)), abs(math.sin(heading_delta))
    actor_length = max(0.2, float(actor.get("length", 4.5)))
    actor_width = max(0.2, float(actor.get("width", 1.8)))
    actor_forward_extent = 0.5 * (cos_delta * actor_length + sin_delta * actor_width)
    actor_lateral_extent = 0.5 * (sin_delta * actor_length + cos_delta * actor_width)
    center_lateral = abs(lateral)
    visible_lateral = max(0.0, center_lateral - actor_lateral_extent)

    if (
        oncoming_lateral_exclusion_m > 0.0
        and center_lateral >= oncoming_lateral_exclusion_m
        and math.cos(heading_delta) < 0.0
    ):
        return True

    if hood_occlusion_distance_m <= 0.0 or hood_occlusion_lateral_m <= 0.0:
        return False
    nearest_box_distance = math.hypot(
        max(0.0, abs(forward) - actor_forward_extent),
        visible_lateral,
    )
    return (
        center_lateral >= hood_occlusion_lateral_m
        and nearest_box_distance < hood_occlusion_distance_m
    )


def _renderable_actor(
    actor: dict[str, Any],
    ego: dict[str, Any],
    *,
    radius_m: float,
    clearance_m: float,
    fov_degrees: float = 120.0,
    fov_margin_degrees: float = 8.0,
    rear_margin_m: float = 3.0,
    hood_occlusion_distance_m: float = 0.0,
    hood_occlusion_lateral_m: float = 0.0,
    oncoming_lateral_exclusion_m: float = 0.0,
    allow_overlap: bool = False,
) -> bool:
    dx = float(actor.get("x", 0.0)) - float(ego.get("x", 0.0))
    dy = float(actor.get("y", 0.0)) - float(ego.get("y", 0.0))
    if math.hypot(dx, dy) > radius_m:
        return False

    ego_heading = float(ego.get("heading", 0.0))
    cos_ego, sin_ego = math.cos(ego_heading), math.sin(ego_heading)
    forward = cos_ego * dx + sin_ego * dy
    lateral = -sin_ego * dx + cos_ego * dy
    heading_delta = float(actor.get("heading", 0.0)) - ego_heading
    cos_delta, sin_delta = abs(math.cos(heading_delta)), abs(math.sin(heading_delta))
    actor_length = max(0.2, float(actor.get("length", 4.5)))
    actor_width = max(0.2, float(actor.get("width", 1.8)))
    actor_forward_extent = 0.5 * (cos_delta * actor_length + sin_delta * actor_width)
    actor_lateral_extent = 0.5 * (sin_delta * actor_length + cos_delta * actor_width)
    if forward + actor_forward_extent < -rear_margin_m:
        return False
    visible_forward = max(0.1, forward + actor_forward_extent)
    visible_lateral = max(0.0, abs(lateral) - actor_lateral_extent)
    half_fov = min(89.0, max(1.0, 0.5 * fov_degrees + fov_margin_degrees))
    if math.atan2(visible_lateral, visible_forward) > math.radians(half_fov):
        return False
    if _actor_control_hazard(
        actor,
        ego,
        hood_occlusion_distance_m=hood_occlusion_distance_m,
        hood_occlusion_lateral_m=hood_occlusion_lateral_m,
        oncoming_lateral_exclusion_m=oncoming_lateral_exclusion_m,
    ):
        # Sparse front-view controls cannot represent a close side pass without
        # the projected box crossing the ego hood. Exclude the track before it
        # reaches that unstable image region.
        return False
    forward_gap = abs(forward) - (0.5 * max(0.2, float(ego.get("length", 4.5))) + actor_forward_extent)
    lateral_gap = abs(lateral) - (0.5 * max(0.2, float(ego.get("width", 1.8))) + actor_lateral_extent)
    return allow_overlap or forward_gap >= clearance_m or lateral_gap >= clearance_m


def _dynamic_state(
    samples: Sequence[dict[str, Any]],
    timestamps: Sequence[int],
    *,
    actor_radius_m: float = 90.0,
    actor_clearance_m: float = 2.0,
    actor_fov_degrees: float = 120.0,
    actor_fov_margin_degrees: float = 8.0,
    actor_rear_margin_m: float = 3.0,
    actor_hood_occlusion_distance_m: float = 0.0,
    actor_hood_occlusion_lateral_m: float = 0.0,
    actor_oncoming_lateral_exclusion_m: float = 0.0,
    actor_allow_overlap: bool = False,
    actor_max_count: int = 20,
    actor_max_pedestrians: int = 4,
    actor_max_cyclists: int = 2,
    actor_selection_state: set[str] | None = None,
) -> video_model_pb2.DynamicWorldState:
    tracks: dict[str, list[tuple[dict[str, Any], int]]] = {}
    priorities: dict[str, float] = {}
    previous_ids = set(actor_selection_state or ())
    retained_priorities: dict[str, float] = {}
    hazardous_ids: set[str] = set()
    for sample, timestamp in zip(samples, timestamps):
        ego = sample.get("ego") or {}
        for actor in _frame_actors(sample):
            actor_id = str(actor.get("id"))
            tracks.setdefault(actor_id, []).append((actor, timestamp))
            if _actor_control_hazard(
                actor,
                ego,
                hood_occlusion_distance_m=actor_hood_occlusion_distance_m,
                hood_occlusion_lateral_m=actor_hood_occlusion_lateral_m,
                oncoming_lateral_exclusion_m=actor_oncoming_lateral_exclusion_m,
            ):
                hazardous_ids.add(actor_id)
            control_clearance = _actor_control_clearance(actor, actor_clearance_m)
            distance = math.hypot(
                float(actor.get("x", 0.0)) - float(ego.get("x", 0.0)),
                float(actor.get("y", 0.0)) - float(ego.get("y", 0.0)),
            )
            if _renderable_actor(
                actor,
                ego,
                radius_m=actor_radius_m,
                clearance_m=control_clearance,
                fov_degrees=actor_fov_degrees,
                fov_margin_degrees=actor_fov_margin_degrees,
                rear_margin_m=actor_rear_margin_m,
                hood_occlusion_distance_m=actor_hood_occlusion_distance_m,
                hood_occlusion_lateral_m=actor_hood_occlusion_lateral_m,
                oncoming_lateral_exclusion_m=actor_oncoming_lateral_exclusion_m,
                allow_overlap=actor_allow_overlap,
            ):
                priorities[actor_id] = min(priorities.get(actor_id, math.inf), distance)
            if actor_id in previous_ids and _renderable_actor(
                actor,
                ego,
                radius_m=actor_radius_m * 1.15,
                clearance_m=control_clearance,
                fov_degrees=min(175.0, actor_fov_degrees + 20.0),
                fov_margin_degrees=actor_fov_margin_degrees + 10.0,
                rear_margin_m=actor_rear_margin_m + 5.0,
                hood_occlusion_distance_m=actor_hood_occlusion_distance_m,
                hood_occlusion_lateral_m=actor_hood_occlusion_lateral_m,
                oncoming_lateral_exclusion_m=actor_oncoming_lateral_exclusion_m,
                allow_overlap=actor_allow_overlap,
            ):
                retained_priorities[actor_id] = min(
                    retained_priorities.get(actor_id, math.inf), distance
                )
    for actor_id in hazardous_ids:
        priorities.pop(actor_id, None)
        retained_priorities.pop(actor_id, None)
    selected_ids: set[str] = set()
    selected_pedestrians = 0
    selected_cyclists = 0
    retained = sorted(
        retained_priorities,
        key=lambda actor_id: (retained_priorities[actor_id], actor_id),
    )
    newcomers = [
        actor_id
        for actor_id in sorted(priorities, key=lambda value: (priorities[value], value))
        if actor_id not in retained_priorities
    ]
    for actor_id in [*retained, *newcomers]:
        observations = tracks.get(actor_id) or []
        if len(observations) < 2:
            continue
        class_id = _class_id(observations[0][0])
        if class_id == video_model_pb2.ActorClassId.PEDESTRIAN:
            if selected_pedestrians >= max(0, int(actor_max_pedestrians)):
                continue
            selected_pedestrians += 1
        elif class_id == video_model_pb2.ActorClassId.CYCLIST:
            if selected_cyclists >= max(0, int(actor_max_cyclists)):
                continue
            selected_cyclists += 1
        selected_ids.add(actor_id)
        if len(selected_ids) >= max(1, int(actor_max_count)):
            break
    if actor_selection_state is not None:
        actor_selection_state.clear()
        actor_selection_state.update(selected_ids)
    actors = []
    for actor_id, observations in sorted(tracks.items()):
        if actor_id not in selected_ids or len(observations) < 2:
            continue
        first = observations[0][0]
        actors.append(
            video_model_pb2.DynamicActor(
                class_id=_class_id(first),
                bbox_dims=common_pb2.AABB(
                    size_x=max(0.2, float(first.get("length", 4.5))),
                    size_y=max(0.2, float(first.get("width", 1.8))),
                    size_z=max(0.2, float(first.get("height", 1.6))),
                ),
                trajectory=common_pb2.Trajectory(
                    poses=[
                        common_pb2.PoseAtTime(
                            timestamp_us=timestamp,
                            pose=_actor_center_pose(actor),
                        )
                        for actor, timestamp in observations
                    ]
                ),
            )
        )
    return video_model_pb2.DynamicWorldState(actors=actors)


def _control_trace_entry(
    samples: Sequence[dict[str, Any]],
    selected_actor_ids: set[str],
    *,
    chunk_index: int,
    global_start_frame: int,
    entered_actor_ids: set[str],
    exited_actor_ids: set[str],
) -> dict[str, Any]:
    tracks: dict[str, list[dict[str, Any]]] = {
        actor_id: [] for actor_id in selected_actor_ids
    }
    for sample in samples:
        for actor in _frame_actors(sample):
            actor_id = str(actor.get("id"))
            if actor_id in tracks:
                tracks[actor_id].append(actor)

    def pose(actor: dict[str, Any]) -> dict[str, Any]:
        return {
            "x": round(float(actor.get("x", 0.0)), 6),
            "y": round(float(actor.get("y", 0.0)), 6),
            "z_center": round(
                float(actor.get("z", 0.0))
                + 0.5 * max(0.2, float(actor.get("height", 1.6))),
                6,
            ),
            "heading": round(float(actor.get("heading", 0.0)), 7),
            "speed": round(float(actor.get("speed", 0.0)), 5),
        }

    actor_tracks = []
    for actor_id in sorted(tracks):
        observations = tracks[actor_id]
        if not observations:
            continue
        first = observations[0]
        actor_tracks.append(
            {
                "id": actor_id,
                "class_id": int(_class_id(first)),
                "size_lwh": [
                    round(float(first.get("length", 4.5)), 4),
                    round(float(first.get("width", 1.8)), 4),
                    round(float(first.get("height", 1.6)), 4),
                ],
                "observations": len(observations),
                "first": pose(first),
                "last": pose(observations[-1]),
            }
        )
    first_sample = samples[0] if samples else {}
    last_sample = samples[-1] if samples else {}
    return {
        "schema": "denseworld.omnidreams-control-chunk.v1",
        "chunk": int(chunk_index),
        "global_start_frame": int(global_start_frame),
        "frames": len(samples),
        "sim_time_start": first_sample.get("sim_time"),
        "sim_time_end": last_sample.get("sim_time"),
        "selected_actor_ids": sorted(selected_actor_ids),
        "entered_actor_ids": sorted(entered_actor_ids),
        "exited_actor_ids": sorted(exited_actor_ids),
        "ego_first": pose(first_sample.get("ego") or {}),
        "ego_last": pose(last_sample.get("ego") or {}),
        "actor_tracks": actor_tracks,
    }


class _VideoPipe:
    _ENCODER_PRESETS = {
        "ultrafast",
        "superfast",
        "veryfast",
        "faster",
        "fast",
        "medium",
        "slow",
        "slower",
        "veryslow",
    }

    def __init__(
        self,
        path: Path,
        fps: int,
        *,
        preview_path: Path | None = None,
        preview_fps: int | None = None,
        encoder_preset: str = "medium",
        encoder_crf: int = 18,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoder_preset = str(encoder_preset or "medium").strip().lower()
        if encoder_preset not in self._ENCODER_PRESETS:
            raise ValueError(f"Unsupported ffmpeg encoder preset: {encoder_preset}")
        encoder_crf = max(0, min(51, int(encoder_crf)))
        self.process = subprocess.Popen(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "image2pipe", "-vcodec", "mjpeg", "-r", str(fps), "-i", "-",
                "-an", "-c:v", "libx264", "-preset", encoder_preset,
                "-crf", str(encoder_crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
            ],
            stdin=subprocess.PIPE,
        )
        self.path = path
        self.encoder_preset = encoder_preset
        self.encoder_crf = encoder_crf
        self.frames = 0
        self._last_frame = b""
        self._transition_base = b""
        self._transition_total = 0
        self._transition_index = 0
        # Encoding is independent from model inference. A bounded queue keeps
        # memory predictable while allowing FFmpeg to consume the previous
        # chunk as OmniDreams renders the next one.
        self._encoder_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=128)
        self._encoder_error: BaseException | None = None
        self._encoder_closed = False
        self._encoder_thread = threading.Thread(
            target=self._write_video_frames,
            name=f"OmniDreamsEncoder-{path.stem}",
            daemon=True,
        )
        self._encoder_thread.start()
        self.preview_path = preview_path
        effective_preview_fps = max(1, int(preview_fps or fps))
        self.preview_stride = max(1, int(round(fps / effective_preview_fps)))
        self.preview_sequence_dir = (
            preview_path.parent / f"{preview_path.stem}_frames" if preview_path is not None else None
        )
        # Keep two minutes of preview keys. The old fixed 300-frame ring held
        # only 20 seconds at 15 fps and forced visible 10-second timeline jumps
        # whenever a remote viewer temporarily fell behind.
        self.preview_sequence_limit = max(300, effective_preview_fps * 120)
        self._preview_queue: queue.Queue[tuple[int, bytes] | None] = queue.Queue(maxsize=128)
        self._preview_thread: threading.Thread | None = None
        self._preview_closed = False
        if self.preview_sequence_dir is not None:
            self.preview_sequence_dir.mkdir(parents=True, exist_ok=True)
            for stale in self.preview_sequence_dir.glob("*.jpg"):
                stale.unlink(missing_ok=True)
        if self.preview_path is not None:
            self._preview_thread = threading.Thread(
                target=self._write_preview_frames,
                name=f"OmniDreamsPreview-{path.stem}",
                daemon=True,
            )
            self._preview_thread.start()

    def _write_video_frames(self) -> None:
        while True:
            data = self._encoder_queue.get()
            try:
                if data is None:
                    return
                if self._encoder_error is not None:
                    continue
                try:
                    if self.process.stdin is None:
                        raise RuntimeError("ffmpeg input pipe is closed")
                    self.process.stdin.write(data)
                except BaseException as exc:
                    self._encoder_error = exc
            finally:
                self._encoder_queue.task_done()

    def _raise_encoder_error(self) -> None:
        if self._encoder_error is not None:
            raise RuntimeError(f"ffmpeg input failed: {self.path}") from self._encoder_error

    def _close_encoder(self, *, drain: bool) -> None:
        if self._encoder_closed:
            return
        self._encoder_closed = True
        if drain:
            self._encoder_queue.join()
        else:
            while True:
                try:
                    self._encoder_queue.get_nowait()
                    self._encoder_queue.task_done()
                except queue.Empty:
                    break
        self._encoder_queue.put(None)
        self._encoder_thread.join(timeout=120 if drain else 10)
        if self._encoder_thread.is_alive():
            raise RuntimeError(f"ffmpeg input worker did not stop: {self.path}")

    def _write_preview_frames(self) -> None:
        while True:
            item = self._preview_queue.get()
            try:
                if item is None:
                    return
                preview_index, data = item
                if self.preview_path is not None:
                    temporary = self.preview_path.with_suffix(self.preview_path.suffix + ".tmp")
                    temporary.write_bytes(data)
                    temporary.replace(self.preview_path)
                if self.preview_sequence_dir is not None:
                    frame_path = self.preview_sequence_dir / f"{preview_index:08d}.jpg"
                    temporary = frame_path.with_suffix(".jpg.tmp")
                    temporary.write_bytes(data)
                    temporary.replace(frame_path)
                    stale_index = preview_index - self.preview_sequence_limit
                    if stale_index >= 0:
                        (self.preview_sequence_dir / f"{stale_index:08d}.jpg").unlink(missing_ok=True)
            finally:
                self._preview_queue.task_done()

    def _close_preview(self, *, drain: bool) -> None:
        if self._preview_closed or self._preview_thread is None:
            return
        self._preview_closed = True
        if drain:
            self._preview_queue.join()
        else:
            while True:
                try:
                    self._preview_queue.get_nowait()
                    self._preview_queue.task_done()
                except queue.Empty:
                    break
        self._preview_queue.put(None)
        self._preview_thread.join(timeout=10)

    def begin_transition(self, frame_count: int) -> None:
        frame_count = max(0, int(frame_count))
        self._transition_base = self._last_frame if frame_count else b""
        self._transition_total = frame_count if self._transition_base else 0
        self._transition_index = 0

    @staticmethod
    def _blend_frames(base_data: bytes, current_data: bytes, ratio: float) -> bytes:
        ratio = max(0.0, min(1.0, float(ratio)))
        with Image.open(io.BytesIO(base_data)) as base_image, Image.open(io.BytesIO(current_data)) as current_image:
            current = current_image.convert("RGB")
            base = base_image.convert("RGB")
            if base.size != current.size:
                base = base.resize(current.size, Image.Resampling.BILINEAR)
            blended = Image.blend(base, current, ratio)
            output = io.BytesIO()
            blended.save(output, format="JPEG", quality=95, subsampling=0)
            return output.getvalue()

    def write(self, data: bytes) -> None:
        if self._encoder_closed:
            raise RuntimeError("ffmpeg input pipe is closed")
        self._raise_encoder_error()
        if self._transition_index < self._transition_total:
            self._transition_index += 1
            data = self._blend_frames(
                self._transition_base,
                data,
                self._transition_index / self._transition_total,
            )
        self._encoder_queue.put(data)
        self._raise_encoder_error()
        self._last_frame = data
        frame_index = self.frames
        self.frames += 1
        preview_frame = frame_index % self.preview_stride == 0
        if self.preview_path is not None and preview_frame:
            preview_index = frame_index // self.preview_stride
            self._preview_queue.put((preview_index, data))

    def close(self) -> None:
        encoder_error: BaseException | None = None
        try:
            self._close_encoder(drain=True)
            self._raise_encoder_error()
        except BaseException as exc:
            encoder_error = exc
        finally:
            if self.process.stdin is not None:
                self.process.stdin.close()
        code = self.process.wait(timeout=120)
        self._close_preview(drain=True)
        if encoder_error is not None:
            raise encoder_error
        if code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {code}: {self.path}")

    def abort(self) -> None:
        try:
            self._close_encoder(drain=False)
        except RuntimeError:
            self.process.kill()
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)
        self._close_preview(drain=False)


def _camera_spec(
    name: str,
    width: int,
    height: int,
    calibration: dict[str, Any],
) -> camera_pb2.CameraSpec:
    ftheta = calibration["ftheta"]
    linear_cde = ftheta["linear_cde"]
    is_backward = bool(ftheta["is_backward"])
    kwargs = {
        "principal_point_x": float(ftheta["principal_point"][0]),
        "principal_point_y": float(ftheta["principal_point"][1]),
        "reference_poly": (
            camera_pb2.FthetaCameraParam.PIXELDIST_TO_ANGLE
            if is_backward
            else camera_pb2.FthetaCameraParam.ANGLE_TO_PIXELDIST
        ),
        "linear_cde": camera_pb2.LinearCde(
            linear_c=float(linear_cde[0]),
            linear_d=float(linear_cde[1]),
            linear_e=float(linear_cde[2]),
        ),
    }
    if is_backward:
        kwargs["pixeldist_to_angle_poly"] = [float(value) for value in ftheta["polynomial"]]
    else:
        kwargs["angle_to_pixeldist_poly"] = [float(value) for value in ftheta["polynomial"]]
    return camera_pb2.CameraSpec(
        logical_id=name,
        resolution_h=height,
        resolution_w=width,
        shutter_type=camera_pb2.ShutterType.GLOBAL,
        ftheta_param=camera_pb2.FthetaCameraParam(**kwargs),
    )


def _rig_to_camera_pose(calibration: dict[str, Any]) -> common_pb2.Pose:
    camera_to_vehicle = calibration["camera_to_vehicle_flu"]
    translation = camera_to_vehicle["translation"]
    quaternion = camera_to_vehicle["quaternion"]
    return common_pb2.Pose(
        vec=common_pb2.Vec3(
            x=float(translation[0]),
            y=float(translation[1]),
            z=float(translation[2]),
        ),
        quat=common_pb2.Quat(
            w=float(quaternion["w"]),
            x=float(quaternion["x"]),
            y=float(quaternion["y"]),
            z=float(quaternion["z"]),
        ),
    )


def run(spec: dict[str, Any]) -> dict[str, Any]:
    server = str(spec.get("server") or "127.0.0.1:50051")
    hdmap_zip = Path(spec["hdmap_zip"]).resolve()
    initial_frame = Path(spec["initial_frame"]).resolve()
    output_dir = Path(spec["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_path = Path(spec["traffic_frames"]).resolve()
    stream_frames_value = str(spec.get("traffic_stream_frames") or "").strip()
    stream_frames_path = Path(stream_frames_value).resolve() if stream_frames_value else None
    traffic_reader = _TrafficFrameReader(frames_path, stream_frames_path)
    capture_status_value = str(spec.get("traffic_capture_status") or "").strip()
    capture_status_path = Path(capture_status_value).resolve() if capture_status_value else None
    sync_state_value = str(spec.get("world_sync_state") or "").strip()
    sync_state_path = Path(sync_state_value).resolve() if sync_state_value else None
    live_traffic = bool(spec.get("live_traffic_frames", False))
    follow_traffic = bool(spec.get("follow_traffic", False))
    run_until_traffic_ends = bool(spec.get("run_until_traffic_ends", False))
    if run_until_traffic_ends and not live_traffic:
        raise ValueError("run_until_traffic_ends requires live_traffic_frames")
    traffic_start_time_seconds = max(
        0.0, float(spec.get("traffic_start_time_seconds", 0.0) or 0.0)
    )
    source_frames = _wait_for_traffic_frames(
        frames_path,
        min_time=traffic_start_time_seconds,
        live=live_traffic,
        timeout_seconds=float(spec.get("traffic_wait_timeout_seconds", 1800.0)),
        capture_status_path=capture_status_path,
        reader=traffic_reader,
    )
    if not source_frames:
        raise ValueError("traffic_frames must contain at least one frame")

    fps = int(spec.get("fps", 30))
    if run_until_traffic_ends:
        duration: float | None = None
        output_frames: int | None = None
    else:
        duration = max(1.0 / max(1, fps), float(spec.get("duration_seconds", 10.0)))
        output_frames = max(1, int(round(duration * fps)))
    first_chunk, continuation_chunk = 5, 8
    session_segment_seconds = max(0.0, float(spec.get("session_segment_seconds", 0.0) or 0.0))
    session_segment_requested_frames = (
        max(first_chunk, int(round(session_segment_seconds * fps)))
        if session_segment_seconds > 0.0
        else 0
    )
    session_segment_frames = (
        omnidreams_session_frame_budget(
            session_segment_seconds,
            fps=fps,
            first_chunk_frames=first_chunk,
            continuation_chunk_frames=continuation_chunk,
        )
        if session_segment_seconds > 0.0
        else 0
    )
    rollover_initial_frame_mode = str(
        spec.get("rollover_initial_frame_mode") or "latest"
    ).strip().lower()
    if rollover_initial_frame_mode not in {"latest", "reference", "transfer"}:
        raise ValueError(
            "rollover_initial_frame_mode must be latest, reference, or transfer"
        )
    external_anchor_value = str(spec.get("external_anchor_manifest") or "").strip()
    external_anchor_manifest = (
        Path(external_anchor_value).resolve() if external_anchor_value else None
    )
    external_anchor_timeout_seconds = max(
        1.0,
        float(spec.get("external_anchor_timeout_seconds", 1800.0) or 1800.0),
    )
    if rollover_initial_frame_mode == "transfer" and external_anchor_manifest is None:
        raise ValueError("transfer rollover mode requires external_anchor_manifest")
    rollover_sharpen_percent = max(
        0, min(100, int(spec.get("rollover_sharpen_percent", 0) or 0))
    )
    rollover_chroma_blur_radius = max(
        0.0,
        min(4.0, float(spec.get("rollover_chroma_blur_radius", 0.0) or 0.0)),
    )
    rollover_saturation_percent = max(
        0,
        min(150, int(spec.get("rollover_saturation_percent", 100) or 0)),
    )
    rollover_image_format = str(
        spec.get("rollover_image_format") or "jpeg"
    ).strip().lower()
    if rollover_image_format not in {"jpeg", "png"}:
        raise ValueError("rollover_image_format must be either 'jpeg' or 'png'")
    rollover_frame_format = (
        video_model_pb2.ImageFormat.PNG
        if rollover_image_format == "png"
        else video_model_pb2.ImageFormat.JPEG
    )
    session_seed_stride = int(spec.get("session_seed_stride", 0) or 0)
    stationary_anchor_enabled = bool(spec.get("stationary_anchor_enabled", True))
    if rollover_initial_frame_mode == "transfer" and stationary_anchor_enabled:
        raise ValueError(
            "stationary session resets cannot be combined with scheduled Transfer anchors"
        )
    stationary_speed_threshold = max(
        0.0, float(spec.get("stationary_speed_threshold_mps", 0.35) or 0.0)
    )
    stationary_exit_speed = max(
        stationary_speed_threshold,
        float(spec.get("stationary_exit_speed_mps", 0.8) or 0.0),
    )
    stationary_enter_frames = max(
        1,
        int(round(max(0.0, float(spec.get("stationary_enter_seconds", 1.0) or 0.0)) * fps)),
    )
    stationary_reset_frames = max(
        first_chunk,
        int(round(max(0.1, float(spec.get("stationary_reset_seconds", 6.0) or 0.1)) * fps)),
    )
    session_transition_frames = max(
        0, min(fps, int(spec.get("session_transition_frames", 0) or 0))
    )

    camera_name = str(spec.get("camera_name") or "camera_front_wide_120fov")
    width, height = int(spec.get("width", 1280)), int(spec.get("height", 704))
    calibration = spec.get("camera_calibration")
    if not isinstance(calibration, dict):
        calibration = omnidreams_camera_calibration(
            camera_name,
            width,
            height,
            fov_degrees=float(spec.get("fov_degrees", 120.0) or 120.0),
        )
    image_format = video_model_pb2.ImageFormat.PNG if initial_frame.suffix.lower() == ".png" else video_model_pb2.ImageFormat.JPEG
    channel, stub = _open_channel(
        server,
        float(spec.get("connect_timeout_seconds", 60.0)),
    )
    session_id = ""
    session_ids: list[str] = []
    sessions: list[dict[str, Any]] = []
    session_frames = 0
    session_chunk_index = 0
    output_path = output_dir / f"{camera_name}.mp4"
    control_trace_path = output_dir / "control_trace.ndjson"
    control_trace_path.write_text("", encoding="utf-8")
    preview_path = output_dir / f"{camera_name}_latest.jpg"
    progress_path = output_dir / "progress.json"
    live_preview_fps = max(1, min(fps, int(spec.get("live_preview_fps", 10) or 10)))
    runtime_profile = str(spec.get("runtime_profile") or "custom").strip().lower()
    pipeline_config = str(spec.get("pipeline_config") or "").strip()
    gpu_ids = [str(item) for item in (spec.get("gpu_ids") or [])]
    traffic_prefetch_seconds = max(
        0.0, float(spec.get("traffic_prefetch_seconds", 0.0) or 0.0)
    )
    encoder_preset = str(spec.get("encoder_preset") or "medium").strip().lower()
    encoder_crf = max(0, min(51, int(spec.get("encoder_crf", 18) or 18)))
    writer: _VideoPipe | None = None
    hdmap_writer: _VideoPipe | None = None
    timings = []
    total_started = time.perf_counter()
    failed = False
    interrupted = False
    generation_seconds = 0.0
    traffic_wait_seconds = 0.0
    encoder_feed_seconds = 0.0
    current_required_traffic_time = traffic_start_time_seconds
    hdmap_bytes = hdmap_zip.read_bytes()
    reference_frame_bytes = initial_frame.read_bytes()
    # Publish the appearance seed immediately. The first render calls may spend
    # tens of seconds compiling CUDA kernels, but the live view should never be
    # blank while that one-time work is in progress.
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(io.BytesIO(reference_frame_bytes)) as seed_image:
            seed_preview = io.BytesIO()
            seed_image.convert("RGB").save(
                seed_preview,
                format="JPEG",
                quality=95,
                subsampling=0,
            )
        preview_path.write_bytes(seed_preview.getvalue())
    except OSError:
        # Some protocol tests use opaque placeholder bytes. Production seed
        # frames are validated images before this client is invoked.
        preview_path.write_bytes(reference_frame_bytes)
    positive_prompt = str(
        spec.get("prompt")
        or "A realistic front-facing urban driving scene with stable geometry and natural lighting."
    )
    negative_prompt = str(
        spec.get("negative_prompt")
        or "flicker, warped vehicles, inconsistent road markings, duplicate objects"
    )
    camera_spec = _camera_spec(camera_name, width, height, calibration)
    rig_to_camera = _rig_to_camera_pose(calibration)
    actor_radius_m = max(10.0, float(spec.get("actor_radius_m", 90.0) or 90.0))
    actor_clearance_m = max(0.0, float(spec.get("actor_clearance_m", 2.0) or 0.0))
    actor_fov_degrees = max(30.0, min(180.0, float(spec.get("actor_fov_degrees", spec.get("fov_degrees", 120.0)) or 120.0)))
    actor_fov_margin_degrees = max(0.0, min(30.0, float(spec.get("actor_fov_margin_degrees", 8.0) or 0.0)))
    actor_rear_margin_m = max(0.0, min(15.0, float(spec.get("actor_rear_margin_m", 3.0) or 0.0)))
    actor_hood_occlusion_distance_m = max(
        0.0,
        min(50.0, float(spec.get("actor_hood_occlusion_distance_m", 0.0) or 0.0)),
    )
    actor_hood_occlusion_lateral_m = max(
        0.0,
        min(10.0, float(spec.get("actor_hood_occlusion_lateral_m", 0.0) or 0.0)),
    )
    actor_oncoming_lateral_exclusion_m = max(
        0.0,
        min(
            20.0,
            float(spec.get("actor_oncoming_lateral_exclusion_m", 0.0) or 0.0),
        ),
    )
    actor_allow_overlap = bool(spec.get("actor_allow_overlap", False))
    actor_max_count = max(1, min(128, int(spec.get("actor_max_count", 20) or 20)))
    actor_max_pedestrians = max(
        0, min(32, int(spec.get("actor_max_pedestrians", 4) or 0))
    )
    actor_max_cyclists = max(
        0, min(32, int(spec.get("actor_max_cyclists", 2) or 0))
    )
    source_traffic_fps = max(
        1.0, float(spec.get("source_traffic_fps", 10.0) or 10.0)
    )
    traffic_interpolation = str(
        spec.get("traffic_interpolation")
        or "hermite_velocity_position_shortest_angle_10hz_to_30hz"
    )
    control_contract = {
        "static_map": "clipgt-hdmap",
        "rig_trajectory": "authoritative-grpc-per-chunk",
        "dynamic_actors": "authoritative-grpc-per-chunk",
        "dynamic_actor_pose_origin": "bbox-center-z=ground-z+height/2",
        "source_traffic_fps": source_traffic_fps,
        "output_fps": fps,
        "traffic_interpolation": traffic_interpolation,
        "pre_rendered_control_video": False,
        "returned_condition_video": bool(spec.get("return_hdmap_frames")),
        "control_trace": "authoritative-grpc-chunk-requests-with-trafficwm-actor-ids",
        "dynamic_traffic_lights": "unsupported-by-grpc-schema",
        "dynamic_actor_limits": {
            "total": actor_max_count,
            "pedestrians": actor_max_pedestrians,
            "cyclists": actor_max_cyclists,
        },
        "actor_allow_overlap": actor_allow_overlap,
        "dynamic_actor_selection": "sticky_ids_with_exit_hysteresis",
        "stationary_anchor": "stable_reference_or_latest_when_actor_geometry_changes",
    }
    dynamic_actor_selection: set[str] = set()
    control_membership_additions = 0
    control_membership_removals = 0
    control_membership_change_chunks = 0
    stationary_active = False
    stationary_candidate_frame: int | None = None
    stationary_anchor_bytes = b""
    stationary_anchor_actor_signature: dict[str, tuple[float, float, float]] = {}
    stationary_anchor_frame = -1
    stationary_last_reset_frame = -1
    stationary_reset_count = 0
    stationary_dynamic_refresh_count = 0
    stationary_reference_reuse_count = 0
    external_anchor_wait_seconds = 0.0
    external_anchor_uses: list[dict[str, Any]] = []

    def ego_speed(sample: dict[str, Any]) -> float:
        ego = sample.get("ego") or {}
        if ego.get("speed") is not None:
            return max(0.0, float(ego.get("speed") or 0.0))
        return math.hypot(float(ego.get("vx", 0.0) or 0.0), float(ego.get("vy", 0.0) or 0.0))

    def write_progress(*, stage: str, chunk_index: int = 0, error: str = "") -> None:
        generated_video_time = traffic_start_time_seconds + (
            (writer.frames if writer is not None else 0) / fps
        )
        sync_snapshot = read_world_sync(sync_state_path)
        requested_traffic_time = float(
            sync_snapshot.get("requested_traffic_time", traffic_start_time_seconds) or 0.0
        )
        generated_frames = writer.frames if writer is not None else 0
        measured_seconds = sum(float(item.get("seconds", 0.0) or 0.0) for item in timings)
        measured_frames = sum(int(item.get("written_frames", 0) or 0) for item in timings)
        recent_rates = sorted(
            float(item.get("written_frames", 0) or 0) / max(
                float(item.get("seconds", 0.0) or 0.0), 1e-9
            )
            for item in timings[-3:]
            if int(item.get("written_frames", 0) or 0) > 0
            and float(item.get("seconds", 0.0) or 0.0) > 0.0
        )
        recent_generation_fps = (
            recent_rates[len(recent_rates) // 2] if recent_rates else None
        )
        warm_rate_floor = max(2.0, fps * 0.2)
        warm_rates = [
            float(item.get("written_frames", 0) or 0) / max(
                float(item.get("seconds", 0.0) or 0.0), 1e-9
            )
            for item in timings[-6:]
            if int(item.get("written_frames", 0) or 0) > 0
            and float(item.get("seconds", 0.0) or 0.0) > 0.0
            and (
                float(item.get("written_frames", 0) or 0)
                / max(float(item.get("seconds", 0.0) or 0.0), 1e-9)
            ) >= warm_rate_floor
        ]
        generation_warmed = len(warm_rates) >= 2
        sustained_generation_fps = (
            sorted(warm_rates)[len(warm_rates) // 2] if generation_warmed else None
        )
        elapsed_seconds = max(0.0, time.perf_counter() - total_started)
        end_to_end_fps = generated_frames / elapsed_seconds if elapsed_seconds > 0.0 else None
        payload = {
            "schema": "denseworld.omnidreams-progress.v1",
            "stage": stage,
            "session_id": session_id,
            "session_ids": list(session_ids),
            "session_index": max(0, len(session_ids) - 1),
            "session_frames": session_frames,
            "session_segment_requested_frames": session_segment_requested_frames,
            "session_segment_frames": session_segment_frames,
            "session_segment_seconds": session_segment_seconds,
            "rollover_initial_frame_mode": rollover_initial_frame_mode,
            "rollover_sharpen_percent": rollover_sharpen_percent,
            "rollover_chroma_blur_radius": rollover_chroma_blur_radius,
            "rollover_saturation_percent": rollover_saturation_percent,
            "rollover_image_format": rollover_image_format,
            "session_seed_stride": session_seed_stride,
            "external_anchor_manifest": (
                str(external_anchor_manifest) if external_anchor_manifest is not None else ""
            ),
            "external_anchor_wait_seconds": round(external_anchor_wait_seconds, 4),
            "external_anchor_uses": external_anchor_uses[-16:],
            "traffic_start_time_seconds": traffic_start_time_seconds,
            "runtime_profile": runtime_profile,
            "pipeline_config": pipeline_config,
            "gpu_ids": gpu_ids,
            "traffic_prefetch_seconds": traffic_prefetch_seconds,
            "required_traffic_time": current_required_traffic_time,
            "encoder_preset": encoder_preset,
            "encoder_crf": encoder_crf,
            "stationary_anchor_enabled": stationary_anchor_enabled,
            "stationary_active": stationary_active,
            "stationary_speed_threshold_mps": stationary_speed_threshold,
            "stationary_exit_speed_mps": stationary_exit_speed,
            "stationary_enter_seconds": round(stationary_enter_frames / fps, 6),
            "stationary_reset_seconds": round(stationary_reset_frames / fps, 6),
            "session_transition_frames": session_transition_frames,
            "session_transition_seconds": round(session_transition_frames / fps, 6),
            "stationary_anchor_frame": stationary_anchor_frame,
            "stationary_reset_count": stationary_reset_count,
            "stationary_anchor_actor_count": len(stationary_anchor_actor_signature),
            "stationary_dynamic_refresh_count": stationary_dynamic_refresh_count,
            "stationary_reference_reuse_count": stationary_reference_reuse_count,
            "actor_radius_m": actor_radius_m,
            "actor_clearance_m": actor_clearance_m,
            "actor_fov_degrees": actor_fov_degrees,
            "actor_fov_margin_degrees": actor_fov_margin_degrees,
            "actor_rear_margin_m": actor_rear_margin_m,
            "actor_hood_occlusion_distance_m": actor_hood_occlusion_distance_m,
            "actor_hood_occlusion_lateral_m": actor_hood_occlusion_lateral_m,
            "actor_oncoming_lateral_exclusion_m": actor_oncoming_lateral_exclusion_m,
            "actor_allow_overlap": actor_allow_overlap,
            "actor_max_count": actor_max_count,
            "actor_max_pedestrians": actor_max_pedestrians,
            "actor_max_cyclists": actor_max_cyclists,
            "control_contract": control_contract,
            "sessions": sessions,
            "output": str(output_path),
            "preview_frame": str(preview_path),
            "preview_sequence": str(output_dir / f"{preview_path.stem}_frames"),
            "preview_fps": live_preview_fps,
            "fps": fps,
            "frames": generated_frames,
            "generated_video_time": generated_video_time,
            "requested_traffic_time": requested_traffic_time,
            "traffic_lead_seconds": max(0.0, requested_traffic_time - generated_video_time),
            "measured_generation_fps": (
                round(measured_frames / measured_seconds, 4) if measured_seconds > 0 else None
            ),
            "recent_generation_fps": (
                round(recent_generation_fps, 4)
                if recent_generation_fps is not None
                else None
            ),
            "generation_warmed": generation_warmed,
            "sustained_generation_fps": (
                round(sustained_generation_fps, 4)
                if sustained_generation_fps is not None
                else None
            ),
            "recent_realtime_factor": (
                round(recent_generation_fps / fps, 4)
                if recent_generation_fps is not None
                else None
            ),
            "end_to_end_fps": round(end_to_end_fps, 4) if end_to_end_fps is not None else None,
            "traffic_wait_seconds": round(traffic_wait_seconds, 4),
            "encoder_feed_seconds": round(encoder_feed_seconds, 4),
            "target_frames": output_frames,
            "progress": (
                min(1.0, float(writer.frames) / float(output_frames))
                if writer is not None and output_frames
                else None if run_until_traffic_ends else 0.0
            ),
            "chunk": chunk_index,
            "completed_chunks": len(timings),
            "recent_chunks": timings[-64:],
            "error": error,
            "updated_at_unix": time.time(),
        }
        temporary = progress_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(progress_path)
        if sync_state_path is not None:
            update_world_sync(
                sync_state_path,
                stage=stage,
                generated_video_time=generated_video_time,
                video_frames=writer.frames if writer is not None else 0,
                video_target_frames=output_frames,
                video_fps=fps,
                error=error,
            )

    def close_current_session(*, reason: str, end_frame: int) -> None:
        nonlocal session_id
        if not session_id:
            return
        started = time.perf_counter()
        try:
            stub.close_session(
                video_model_pb2.SessionCloseRequest(session_id=session_id),
                timeout=float(spec.get("session_close_timeout_seconds", 120.0)),
            )
        except grpc.RpcError:
            if not failed:
                raise
        finally:
            if sessions and sessions[-1].get("session_id") == session_id:
                sessions[-1].update(
                    {
                        "end_frame": int(end_frame),
                        "frames": max(0, int(end_frame) - int(sessions[-1]["start_frame"])),
                        "close_reason": reason,
                        "close_seconds": round(time.perf_counter() - started, 4),
                    }
                )
            session_id = ""

    def start_new_session(
        *,
        frame_data: bytes,
        frame_format: int,
        start_frame: int,
        reason: str,
    ) -> None:
        nonlocal session_id, session_frames, session_chunk_index
        write_progress(stage="starting_session", chunk_index=len(timings))
        started = time.perf_counter()
        session_seed = int(spec.get("random_seed", 42)) + len(session_ids) * session_seed_stride
        response = stub.start_session(
            video_model_pb2.SessionRequest(
                static_world_map=video_model_pb2.StaticWorldMap(hdmap_parquets=hdmap_bytes),
                text_prompt=video_model_pb2.TextPrompt(
                    positive=positive_prompt,
                    negative=negative_prompt,
                ),
                debug_options=video_model_pb2.DebugOptions(
                    return_hdmap_frames=bool(spec.get("return_hdmap_frames")),
                    skip_video_generation=False,
                ),
                camera_specs=[camera_spec],
                initial_frames=[video_model_pb2.Image(data=frame_data, format=frame_format)],
                rig_to_camera=[rig_to_camera],
                random_seed=session_seed,
            ),
            timeout=float(spec.get("session_timeout_seconds", 300.0)),
        )
        session_id = response.session_id
        if not session_id:
            raise RuntimeError("OmniDreams start_session returned an empty session ID")
        session_ids.append(session_id)
        sessions.append(
            {
                "index": len(session_ids) - 1,
                "session_id": session_id,
                "start_frame": int(start_frame),
                "start_time_seconds": round(float(start_frame) / fps, 6),
                "start_reason": reason,
                "random_seed": session_seed,
                "setup_seconds": round(time.perf_counter() - started, 4),
            }
        )
        session_frames = 0
        session_chunk_index = 0

    try:
        write_progress(stage="connecting")
        start_new_session(
            frame_data=reference_frame_bytes,
            frame_format=image_format,
            start_frame=0,
            reason="initial_frame",
        )
        writer = _VideoPipe(
            output_path,
            fps,
            preview_path=preview_path,
            preview_fps=live_preview_fps,
            encoder_preset=encoder_preset,
            encoder_crf=encoder_crf,
        )
        if spec.get("return_hdmap_frames"):
            hdmap_writer = _VideoPipe(
                output_dir / f"{camera_name}_hdmap.mp4",
                fps,
                encoder_preset=encoder_preset,
                encoder_crf=encoder_crf,
            )
        write_progress(stage="running")
        chunk_index = 0
        while output_frames is None or writer.frames < output_frames:
            chunk_size = first_chunk if session_chunk_index == 0 else continuation_chunk
            offset = writer.frames
            traffic_end_time = (
                traffic_start_time_seconds + duration
                if duration is not None
                else None
            )
            required_time = traffic_start_time_seconds + max(
                (offset + chunk_size - 1) / fps,
                0.0,
            )
            if traffic_end_time is not None:
                required_time = min(traffic_end_time, required_time)
            if live_traffic:
                required_time = (
                    math.ceil(required_time * source_traffic_fps - 1e-9)
                    / source_traffic_fps
                )
                if traffic_end_time is not None:
                    required_time = min(traffic_end_time, required_time)
                current_required_traffic_time = required_time
                requested_time = required_time + traffic_prefetch_seconds
                requested_time = (
                    math.ceil(requested_time * source_traffic_fps - 1e-9)
                    / source_traffic_fps
                )
                if traffic_end_time is not None:
                    requested_time = min(traffic_end_time, requested_time)
                if sync_state_path is not None:
                    update_world_sync(
                        sync_state_path,
                        stage="requesting_traffic",
                        requested_traffic_time=requested_time,
                        generated_video_time=traffic_start_time_seconds + writer.frames / fps,
                        video_frames=writer.frames,
                        video_target_frames=output_frames,
                        video_fps=fps,
                    )
                write_progress(stage="waiting_for_traffic", chunk_index=chunk_index)
                traffic_wait_started = time.perf_counter()
                source_frames = _wait_for_traffic_frames(
                    frames_path,
                    min_time=required_time,
                    live=True,
                    timeout_seconds=float(spec.get("traffic_wait_timeout_seconds", 1800.0)),
                    capture_status_path=capture_status_path,
                    reader=traffic_reader,
                    allow_terminal_shortfall=run_until_traffic_ends,
                )
                traffic_wait_seconds += time.perf_counter() - traffic_wait_started
                if run_until_traffic_ends:
                    capture_status = _read_capture_status(capture_status_path)
                    capture_terminal = str(
                        capture_status.get("stage") or ""
                    ).strip().lower() in {
                        "completed",
                        "stopped",
                        "interrupted",
                        "cancelled",
                    }
                    if capture_terminal:
                        last_traffic_time = max(
                            float(frame.get("sim_time", 0.0) or 0.0)
                            for frame in source_frames
                        )
                        output_frames = max(
                            1,
                            int(
                                round(
                                    max(
                                        0.0,
                                        last_traffic_time - traffic_start_time_seconds,
                                    )
                                    * fps
                                )
                            ),
                        )
                        if writer.frames >= output_frames:
                            break
            current_sample = _sample_frame(
                source_frames,
                traffic_start_time_seconds + offset / fps,
            )
            current_speed = ego_speed(current_sample)
            restart_frame_data: bytes | None = None
            restart_frame_format = video_model_pb2.ImageFormat.JPEG
            restart_reason = ""
            if stationary_anchor_enabled and writer.frames > 0:
                if stationary_active:
                    if current_speed >= stationary_exit_speed:
                        stationary_active = False
                        stationary_candidate_frame = None
                        stationary_anchor_bytes = b""
                        stationary_anchor_actor_signature = {}
                        stationary_anchor_frame = -1
                        stationary_last_reset_frame = -1
                        restart_frame_data = _prepare_rollover_frame(
                            preview_path.read_bytes(),
                            sharpen_percent=rollover_sharpen_percent,
                            chroma_blur_radius=rollover_chroma_blur_radius,
                            saturation_percent=rollover_saturation_percent,
                            image_format=rollover_image_format,
                        )
                        restart_frame_format = rollover_frame_format
                        restart_reason = "moving_resume_latest"
                    elif writer.frames - stationary_last_reset_frame >= stationary_reset_frames:
                        current_actor_signature = _stationary_actor_signature(
                            current_sample,
                            dynamic_actor_selection,
                        )
                        if _stationary_actor_signatures_match(
                            stationary_anchor_actor_signature,
                            current_actor_signature,
                        ):
                            restart_reason = "stationary_refresh_reference"
                            stationary_reference_reuse_count += 1
                        else:
                            stationary_anchor_bytes = _prepare_rollover_frame(
                                preview_path.read_bytes(),
                                sharpen_percent=rollover_sharpen_percent,
                                chroma_blur_radius=rollover_chroma_blur_radius,
                                saturation_percent=rollover_saturation_percent,
                                image_format=rollover_image_format,
                            )
                            stationary_anchor_actor_signature = current_actor_signature
                            stationary_anchor_frame = max(0, writer.frames - 1)
                            restart_reason = "stationary_refresh_dynamic_latest"
                            stationary_dynamic_refresh_count += 1
                        restart_frame_data = stationary_anchor_bytes
                        restart_frame_format = rollover_frame_format
                        stationary_last_reset_frame = writer.frames
                        stationary_reset_count += 1
                elif current_speed <= stationary_speed_threshold:
                    if stationary_candidate_frame is None:
                        stationary_candidate_frame = writer.frames
                    elif writer.frames - stationary_candidate_frame >= stationary_enter_frames:
                        stationary_active = True
                        stationary_anchor_bytes = _prepare_rollover_frame(
                            preview_path.read_bytes(),
                            sharpen_percent=rollover_sharpen_percent,
                            chroma_blur_radius=rollover_chroma_blur_radius,
                            saturation_percent=rollover_saturation_percent,
                            image_format=rollover_image_format,
                        )
                        stationary_anchor_actor_signature = _stationary_actor_signature(
                            current_sample,
                            dynamic_actor_selection,
                        )
                        stationary_anchor_frame = max(0, writer.frames - 1)
                        stationary_last_reset_frame = writer.frames
                        restart_frame_data = stationary_anchor_bytes
                        restart_frame_format = rollover_frame_format
                        restart_reason = "stationary_anchor_latest"
                        stationary_reset_count += 1
                else:
                    stationary_candidate_frame = None

            if (
                restart_frame_data is None
                and session_segment_frames
                and session_chunk_index > 0
                and (
                    output_frames is None
                    or output_frames - writer.frames > first_chunk + continuation_chunk
                )
                and session_frames + chunk_size > session_segment_frames
            ):
                if rollover_initial_frame_mode == "reference":
                    restart_frame_data = reference_frame_bytes
                    restart_frame_format = image_format
                elif rollover_initial_frame_mode == "transfer":
                    if external_anchor_manifest is None:
                        raise RuntimeError("Transfer rollover manifest is unavailable")
                    write_progress(stage="waiting_for_transfer_anchor", chunk_index=chunk_index)
                    anchor_wait_started = time.perf_counter()
                    (
                        restart_frame_data,
                        restart_frame_format,
                        anchor_metadata,
                    ) = _wait_for_external_transfer_anchor(
                        external_anchor_manifest,
                        writer.frames,
                        timeout_seconds=external_anchor_timeout_seconds,
                    )
                    external_anchor_wait_seconds += time.perf_counter() - anchor_wait_started
                    external_anchor_uses.append(
                        {
                            **anchor_metadata,
                            "consumed_at_unix": time.time(),
                            "wait_seconds": round(
                                time.perf_counter() - anchor_wait_started, 4
                            ),
                        }
                    )
                else:
                    restart_frame_data = _prepare_rollover_frame(
                        preview_path.read_bytes(),
                        sharpen_percent=rollover_sharpen_percent,
                        chroma_blur_radius=rollover_chroma_blur_radius,
                        saturation_percent=rollover_saturation_percent,
                        image_format=rollover_image_format,
                    )
                    restart_frame_format = rollover_frame_format
                restart_reason = f"quality_rollover_{rollover_initial_frame_mode}"

            if restart_frame_data is not None:
                close_current_session(reason=restart_reason, end_frame=writer.frames)
                start_new_session(
                    frame_data=restart_frame_data,
                    frame_format=restart_frame_format,
                    start_frame=writer.frames,
                    reason=restart_reason,
                )
                writer.begin_transition(session_transition_frames)
                chunk_size = first_chunk
                write_progress(stage="running", chunk_index=chunk_index)

            chunk_samples = [
                _sample_frame(source_frames, traffic_start_time_seconds + index / fps)
                for index in range(offset, offset + chunk_size)
            ]
            chunk_timestamps = [
                1_000_000 + int(round((session_frames + index) * 1_000_000 / fps))
                for index in range(chunk_size)
            ]
            started = time.perf_counter()
            previous_actor_selection = set(dynamic_actor_selection)
            dynamic_state = _dynamic_state(
                chunk_samples,
                chunk_timestamps,
                actor_radius_m=actor_radius_m,
                actor_clearance_m=actor_clearance_m,
                actor_fov_degrees=actor_fov_degrees,
                actor_fov_margin_degrees=actor_fov_margin_degrees,
                actor_rear_margin_m=actor_rear_margin_m,
                actor_hood_occlusion_distance_m=actor_hood_occlusion_distance_m,
                actor_hood_occlusion_lateral_m=actor_hood_occlusion_lateral_m,
                actor_oncoming_lateral_exclusion_m=actor_oncoming_lateral_exclusion_m,
                actor_allow_overlap=actor_allow_overlap,
                actor_max_count=actor_max_count,
                actor_max_pedestrians=actor_max_pedestrians,
                actor_max_cyclists=actor_max_cyclists,
                actor_selection_state=dynamic_actor_selection,
            )
            entered_actor_ids = dynamic_actor_selection - previous_actor_selection
            exited_actor_ids = previous_actor_selection - dynamic_actor_selection
            control_membership_additions += len(entered_actor_ids)
            control_membership_removals += len(exited_actor_ids)
            if entered_actor_ids or exited_actor_ids:
                control_membership_change_chunks += 1
            control_trace = _control_trace_entry(
                chunk_samples,
                dynamic_actor_selection,
                chunk_index=chunk_index,
                global_start_frame=offset,
                entered_actor_ids=entered_actor_ids,
                exited_actor_ids=exited_actor_ids,
            )
            with control_trace_path.open("a", encoding="utf-8") as trace_stream:
                trace_stream.write(
                    json.dumps(control_trace, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                )
            request = video_model_pb2.VideoChunkRequest(
                session_id=video_model_pb2.SessionId(session_id=session_id),
                rig_trajectory=_trajectory(chunk_samples, chunk_timestamps, "ego"),
                dynamic_state=dynamic_state,
            )
            retry_count = 0
            max_attempts = max(1, int(spec.get("chunk_retry_attempts", 3)))
            for attempt in range(max_attempts):
                try:
                    response = stub.render_video_chunk(
                        request,
                        timeout=float(spec.get("chunk_timeout_seconds", 1800.0)),
                    )
                    break
                except grpc.RpcError as exc:
                    retryable = exc.code() in {
                        grpc.StatusCode.UNAVAILABLE,
                        grpc.StatusCode.DEADLINE_EXCEEDED,
                    }
                    if not retryable or attempt + 1 >= max_attempts:
                        raise
                    retry_count += 1
                    write_progress(stage="reconnecting", chunk_index=chunk_index, error=str(exc))
                    channel.close()
                    time.sleep(min(5.0, 1.5 * (attempt + 1)))
                    channel, stub = _open_channel(
                        server,
                        float(spec.get("connect_timeout_seconds", 60.0)),
                    )
            chunk_seconds = time.perf_counter() - started
            if len(response.camera_outputs) != 1:
                raise RuntimeError(f"Expected one camera output, received {len(response.camera_outputs)}")
            output = response.camera_outputs[0]
            before = writer.frames
            encoder_started = time.perf_counter()
            for image in output.rgb_frames:
                if output_frames is not None and writer.frames >= output_frames:
                    break
                writer.write(image.data)
            if hdmap_writer is not None:
                for image in output.hdmap_condition_frames:
                    if output_frames is not None and hdmap_writer.frames >= output_frames:
                        break
                    hdmap_writer.write(image.data)
            chunk_encoder_seconds = time.perf_counter() - encoder_started
            encoder_feed_seconds += chunk_encoder_seconds
            timings.append(
                {
                    "chunk": chunk_index,
                    "session_index": len(session_ids) - 1,
                    "session_chunk": session_chunk_index,
                    "global_start_frame": offset,
                    "requested_frames": chunk_size,
                    "written_frames": writer.frames - before,
                    "dynamic_actor_count": len(dynamic_state.actors),
                    "dynamic_actor_ids": sorted(dynamic_actor_selection),
                    "dynamic_actor_entered_ids": sorted(entered_actor_ids),
                    "dynamic_actor_exited_ids": sorted(exited_actor_ids),
                    "dynamic_pedestrian_count": sum(
                        actor.class_id == video_model_pb2.ActorClassId.PEDESTRIAN
                        for actor in dynamic_state.actors
                    ),
                    "dynamic_cyclist_count": sum(
                        actor.class_id == video_model_pb2.ActorClassId.CYCLIST
                        for actor in dynamic_state.actors
                    ),
                    "seconds": round(chunk_seconds, 4),
                    "encoder_feed_seconds": round(chunk_encoder_seconds, 4),
                    "retries": retry_count,
                }
            )
            session_frames += writer.frames - before
            session_chunk_index += 1
            write_progress(stage="running", chunk_index=chunk_index)
            chunk_index += 1
        generation_seconds = sum(item["seconds"] for item in timings)
    except KeyboardInterrupt:
        interrupted = True
        generation_seconds = sum(item["seconds"] for item in timings)
        write_progress(stage="stopped")
    except BaseException as exc:
        failed = True
        write_progress(stage="error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if session_id:
            try:
                close_current_session(
                    reason="error" if failed else "stopped" if interrupted else "completed",
                    end_frame=writer.frames if writer is not None else 0,
                )
            except (grpc.RpcError, RuntimeError):
                pass
        if writer is not None:
            writer.abort() if failed else writer.close()
        if hdmap_writer is not None:
            hdmap_writer.abort() if failed else hdmap_writer.close()
        channel.close()

    manifest = {
        "schema": "denseworld.omnidreams-generation.v1",
        "server": server,
        "session_id": session_ids[-1] if session_ids else "",
        "session_ids": session_ids,
        "sessions": sessions,
        "session_segment_seconds": session_segment_seconds,
        "session_segment_requested_frames": session_segment_requested_frames,
        "session_segment_frames": session_segment_frames,
        "rollover_initial_frame_mode": rollover_initial_frame_mode,
        "rollover_sharpen_percent": rollover_sharpen_percent,
        "rollover_chroma_blur_radius": rollover_chroma_blur_radius,
        "rollover_saturation_percent": rollover_saturation_percent,
        "rollover_image_format": rollover_image_format,
        "session_seed_stride": session_seed_stride,
        "external_anchor_manifest": (
            str(external_anchor_manifest) if external_anchor_manifest is not None else ""
        ),
        "external_anchor_wait_seconds": round(external_anchor_wait_seconds, 4),
        "external_anchor_uses": external_anchor_uses,
        "traffic_start_time_seconds": traffic_start_time_seconds,
        "runtime_profile": runtime_profile,
        "pipeline_config": pipeline_config,
        "gpu_ids": gpu_ids,
        "traffic_prefetch_seconds": traffic_prefetch_seconds,
        "encoder_preset": encoder_preset,
        "encoder_crf": encoder_crf,
        "follow_traffic": follow_traffic,
        "run_until_traffic_ends": run_until_traffic_ends,
        "interrupted": interrupted,
        "stationary_anchor_enabled": stationary_anchor_enabled,
        "stationary_speed_threshold_mps": stationary_speed_threshold,
        "stationary_exit_speed_mps": stationary_exit_speed,
        "stationary_enter_seconds": round(stationary_enter_frames / fps, 6),
        "stationary_reset_seconds": round(stationary_reset_frames / fps, 6),
        "stationary_reset_count": stationary_reset_count,
        "stationary_anchor_actor_count": len(stationary_anchor_actor_signature),
        "stationary_dynamic_refresh_count": stationary_dynamic_refresh_count,
        "stationary_reference_reuse_count": stationary_reference_reuse_count,
        "session_transition_frames": session_transition_frames,
        "session_transition_seconds": round(session_transition_frames / fps, 6),
        "actor_radius_m": actor_radius_m,
        "actor_clearance_m": actor_clearance_m,
        "actor_fov_degrees": actor_fov_degrees,
        "actor_fov_margin_degrees": actor_fov_margin_degrees,
        "actor_rear_margin_m": actor_rear_margin_m,
        "actor_hood_occlusion_distance_m": actor_hood_occlusion_distance_m,
        "actor_hood_occlusion_lateral_m": actor_hood_occlusion_lateral_m,
        "actor_oncoming_lateral_exclusion_m": actor_oncoming_lateral_exclusion_m,
        "actor_allow_overlap": actor_allow_overlap,
        "actor_max_count": actor_max_count,
        "actor_max_pedestrians": actor_max_pedestrians,
        "actor_max_cyclists": actor_max_cyclists,
        "control_contract": control_contract,
        "dynamic_actor_count_range": [
            min((int(item["dynamic_actor_count"]) for item in timings), default=0),
            max((int(item["dynamic_actor_count"]) for item in timings), default=0),
        ],
        "dynamic_actor_membership": {
            "change_chunks": control_membership_change_chunks,
            "additions": control_membership_additions,
            "removals": control_membership_removals,
        },
        "control_trace": str(control_trace_path),
        "output": str(output_path),
        "hdmap_condition_video": (
            str(output_dir / f"{camera_name}_hdmap.mp4")
            if bool(spec.get("return_hdmap_frames"))
            else ""
        ),
        "preview_frame": str(preview_path),
        "preview_sequence": str(output_dir / f"{preview_path.stem}_frames"),
        "preview_fps": live_preview_fps,
        "progress": str(progress_path),
        "fps": fps,
        "frames": writer.frames if writer is not None else 0,
        "duration_seconds": (writer.frames if writer is not None else 0) / fps,
        "session_setup_seconds": round(sum(float(item.get("setup_seconds", 0.0)) for item in sessions), 4),
        "generation_seconds": round(generation_seconds, 4),
        "inference_queue_wait_seconds": round(
            float(spec.get("_inference_queue_wait_seconds") or 0.0), 4
        ),
        "traffic_wait_seconds": round(traffic_wait_seconds, 4),
        "encoder_feed_seconds": round(encoder_feed_seconds, 4),
        "measured_generation_fps": round(
            (writer.frames if writer is not None else 0) / generation_seconds, 4
        ) if generation_seconds > 0.0 else None,
        "model_realtime_factor": round(
            ((writer.frames if writer is not None else 0) / generation_seconds) / fps,
            4,
        ) if generation_seconds > 0.0 else None,
        "end_to_end_seconds": round(time.perf_counter() - total_started, 4),
        "chunks": timings,
        "dynamic_traffic_light_state_supported": False,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_progress(
        stage="stopped" if interrupted else "completed",
        chunk_index=len(timings),
    )
    return manifest


def main() -> int:
    _disable_local_grpc_proxy()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    with _exclusive_inference_slot(spec) as queue_wait_seconds:
        spec["_inference_queue_wait_seconds"] = queue_wait_seconds
        print(json.dumps(run(spec), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
