"""File and video helpers for the DenseWorld Cosmos pipeline."""
from __future__ import annotations

import json
import pickle
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from backend.cosmos.transfer_scene_exporter import CAMERAS, VIEW_KEYS
from backend.scene.semantic_map import build_citynde_semantics


DEFAULT_PROMPT = (
    "Natural documentary dashcam footage from a passenger car moving smoothly along an "
    "ordinary urban roadway. The dry charcoal-gray asphalt has subtle repaired patches, crisp "
    "white road paint, concrete curbs, and unobstructed mapped lanes. Mature leafy street trees, "
    "trimmed green shrubs, and restrained light-stone and concrete mid-rise buildings line the "
    "road. Clear dry late-morning weather, a soft blue sky, and directional natural sunlight "
    "produce stable shadows and neutral color. The atmosphere is calm and physically grounded. "
    "Road geometry, traffic identity, camera motion, object scale, and fine detail remain coherent "
    "across all synchronized camera views."
)
DEFAULT_NEGATIVE_PROMPT = (
    "The video captures a series of frames showing ugly scenes, static with no motion, motion "
    "blur, over-saturation, shaky footage, low resolution, grainy texture, pixelated images, "
    "poorly lit areas, underexposed and overexposed scenes, poor color balance, washed out "
    "colors, choppy sequences, jerky movements, low frame rate, artifacting, color banding, "
    "unnatural transitions, outdated special effects, fake elements, unconvincing visuals, "
    "poorly edited content, jump cuts, visual noise, and flickering. Overall, the video is of "
    "poor quality."
)
TRANSFER_NATIVE_FRAMES = 29
# Keep the official single-frame AR overlap. A five-frame overlap adds a full
# chunk to a 15 s render and caused stronger cumulative color/detail drift in
# controlled A/B testing, despite reducing the raw discontinuity count.
TRANSFER_CHUNK_OVERLAP = 1
# Five pixel frames are the longest conditioning prefix supported by the
# official Transfer2.5 multiview configuration. Reusing that whole prefix is
# materially more stable than restarting every native window from one image.
TRANSFER_SEGMENT_CONDITION_FRAMES = 5
TRANSFER_SEGMENT_BLEND_FRAMES = TRANSFER_SEGMENT_CONDITION_FRAMES
WARMUP_TERMINAL_FRAME_INDEX = 10
SAME_RECORDING_ANCHOR_MIN_GEOMETRY_F1 = 0.65


def omnidreams_session_frame_budget(
    segment_seconds: float,
    *,
    fps: int = 30,
    first_chunk_frames: int = 5,
    continuation_chunk_frames: int = 8,
) -> int:
    """Align a requested session duration to OmniDreams' 5 + 8n output contract."""
    fps = max(1, int(fps))
    first_chunk_frames = max(1, int(first_chunk_frames))
    continuation_chunk_frames = max(1, int(continuation_chunk_frames))
    requested_frames = max(
        first_chunk_frames,
        int(round(max(0.0, float(segment_seconds)) * fps)),
    )
    continuation_chunks = max(
        0,
        (requested_frames - first_chunk_frames) // continuation_chunk_frames,
    )
    return first_chunk_frames + continuation_chunks * continuation_chunk_frames


def omnidreams_rollover_frame_indices(
    duration_seconds: float,
    segment_seconds: float,
    *,
    fps: int = 30,
    first_chunk_frames: int = 5,
    continuation_chunk_frames: int = 8,
) -> list[int]:
    """Return global output frames at which a finite run starts a new session."""
    fps = max(1, int(fps))
    output_frames = max(1, int(round(max(0.0, float(duration_seconds)) * fps)))
    stride = omnidreams_session_frame_budget(
        segment_seconds,
        fps=fps,
        first_chunk_frames=first_chunk_frames,
        continuation_chunk_frames=continuation_chunk_frames,
    )
    minimum_tail = max(1, int(first_chunk_frames)) + max(
        1, int(continuation_chunk_frames)
    )
    return [
        frame
        for frame in range(stride, output_frames, stride)
        if output_frames - frame > minimum_tail
    ]


def probe_video(path: Path, *, count_frames: bool = True) -> dict[str, Any]:
    """Read an exact, decoder-backed video contract with ffprobe."""
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"Video does not exist or is empty: {path}")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
    ]
    if count_frames:
        command.append("-count_frames")
    command.extend(
        [
            "-show_entries",
            "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,duration",
            "-of",
            "json",
            str(path),
        ]
    )
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    streams = (json.loads(result.stdout or "{}").get("streams") or [])
    if not streams:
        raise ValueError(f"Video has no decodable video stream: {path}")
    stream = streams[0]
    rate_text = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    try:
        fps = float(Fraction(rate_text))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    raw_frames = stream.get("nb_read_frames") or stream.get("nb_frames") or 0
    try:
        frames = int(raw_frames)
    except (TypeError, ValueError):
        frames = 0
    duration = float(stream.get("duration") or 0.0)
    if duration <= 0.0 and frames > 0 and fps > 0.0:
        duration = frames / fps
    return {
        "path": str(path),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
        "frames": frames,
        "duration_seconds": duration,
    }


def transfer_spec_frame_contract(spec: dict[str, Any]) -> dict[str, int | float | bool]:
    """Resolve the exact native frame requirements encoded by a Transfer spec."""
    fps = max(1, int(spec.get("fps", 10) or 10))
    autoregressive = bool(spec.get("enable_autoregressive", False))
    chunks = max(1, int(spec.get("num_chunks", 1) or 1)) if autoregressive else 1
    overlap = (
        max(0, min(TRANSFER_NATIVE_FRAMES - 1, int(spec.get("chunk_overlap", 1) or 1)))
        if autoregressive
        else 0
    )
    native_frames = TRANSFER_NATIVE_FRAMES + (
        (TRANSFER_NATIVE_FRAMES - overlap) * (chunks - 1) if autoregressive else 0
    )
    return {
        "fps": fps,
        "autoregressive": autoregressive,
        "chunks": chunks,
        "chunk_overlap": overlap,
        "native_frames": native_frames,
    }


def validate_transfer_spec_media(spec_path: Path) -> dict[str, Any]:
    """Reject controls that would make Transfer silently clamp autoregressive chunks."""
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    contract = transfer_spec_frame_contract(spec)
    desired_fps = float(contract["fps"])
    required_frames = int(contract["native_frames"])
    views: dict[str, Any] = {}
    for view in VIEW_KEYS.values():
        config = spec.get(view)
        if not isinstance(config, dict) or not config.get("control_path"):
            continue
        media: dict[str, Any] = {}
        for media_key in ("control_path", "input_path"):
            value = str(config.get(media_key) or "").strip()
            if not value:
                continue
            report = probe_video(Path(value))
            source_fps = float(report["fps"])
            if source_fps <= 0.0 or desired_fps <= 0.0:
                raise ValueError(f"Transfer {view} {media_key} has invalid FPS: {source_fps:g}")
            factor = source_fps / desired_fps
            rounded_factor = int(round(factor))
            if rounded_factor < 1 or abs(factor - rounded_factor) > 1e-3:
                raise ValueError(
                    f"Transfer {view} {media_key} FPS {source_fps:g} is not evenly divisible "
                    f"by requested {desired_fps:g} FPS"
                )
            available_frames = int(report["frames"]) // rounded_factor
            if available_frames < required_frames:
                raise ValueError(
                    f"Transfer {view} {media_key} provides {available_frames} frames at "
                    f"{desired_fps:g} FPS after downsampling, but the requested "
                    f"{int(contract['chunks'])}-chunk rollout requires {required_frames}; "
                    "the model would silently shorten the video"
                )
            media[media_key] = {
                **report,
                "downsample_factor": rounded_factor,
                "available_model_frames": available_frames,
            }
        views[view] = media
    if not views:
        raise ValueError(f"Transfer spec has no active control view: {spec_path}")
    return {"spec_path": str(spec_path), "contract": contract, "views": views}


def validate_transfer_outputs(
    spec_path: Path,
    output_dir: Path,
    *,
    minimum_frames: int | None = None,
) -> dict[str, Any]:
    """Verify that every requested view was saved at the exact native contract."""
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    contract = transfer_spec_frame_contract(spec)
    required_frames = int(minimum_frames or contract["native_frames"])
    expected_fps = float(contract["fps"])
    name = str(spec.get("name") or "").strip()
    if not name:
        raise ValueError(f"Transfer spec has no sample name: {spec_path}")
    reports: dict[str, Any] = {}
    for view in VIEW_KEYS.values():
        config = spec.get(view)
        if not isinstance(config, dict) or not config.get("control_path"):
            continue
        path = Path(output_dir).resolve() / f"{name}_{view}.mp4"
        report = probe_video(path)
        if int(report["frames"]) < required_frames:
            raise RuntimeError(
                f"Transfer {view} output has {int(report['frames'])} frames, expected at least "
                f"{required_frames}; generation was truncated"
            )
        if abs(float(report["fps"]) - expected_fps) > 0.02:
            raise RuntimeError(
                f"Transfer {view} output FPS is {float(report['fps']):g}, expected {expected_fps:g}"
            )
        reports[view] = report
    return {"contract": contract, "views": reports}


def scene_prompt(export_report: dict[str, Any], custom_prompt: str = "") -> str:
    """Describe the exported route without contradicting its control geometry."""
    if str(custom_prompt or "").strip():
        return str(custom_prompt).strip()

    route = export_report.get("ego_route") or {}
    maneuver = str(route.get("maneuver") or "unknown")
    road_form = str(route.get("road_form") or "intersection")
    intersection_ahead = bool(route.get("intersection_ahead")) or road_form in {
        "intersection",
        "t_junction",
    }
    maneuver_text = {
        "left_turn": "makes a smooth left-turn along the visible lane",
        "right_turn": "makes a smooth right-turn along the visible lane",
        "straight": (
            "continues smoothly through the intersection"
            if intersection_ahead
            else "continues smoothly along the road"
        ),
    }.get(
        maneuver,
        "moves smoothly through the intersection"
        if intersection_ahead
        else "continues smoothly along the road",
    )
    road_form_text = (
        "The route follows a compact modern roundabout with a landscaped central island, "
        "yield markings, curbs, and clearly separated entry and exit lanes. "
        if road_form == "roundabout"
        else
        "The current road meets a transverse cross street, so ordinary buildings and sidewalks "
        "may be visible straight ahead beyond the far curb. "
        if road_form == "t_junction"
        else "Buildings and sidewalks remain outside the supplied road boundaries. "
    )
    counts = export_report.get("source_object_type_counts") or {}
    actors = ["ordinary cars"]
    if int(counts.get("Truck", 0) or 0):
        actors.append("trucks")
    if int(counts.get("Pedestrian", 0) or 0):
        actors.append("correctly scaled pedestrians")
    if int(counts.get("Cyclist", 0) or 0):
        actors.append("cyclists")
    location_text = (
        "entering a compact urban roundabout"
        if road_form == "roundabout"
        else f"approaching a broad signalized {road_form.replace('_', '-')}"
        if intersection_ahead
        else "traveling on a broad ordinary urban arterial"
    )
    controlled_features = (
        "yield markings and lane separators, "
        if road_form == "roundabout"
        else "stop lines, crosswalks, traffic lights, " if intersection_ahead else ""
    )
    return (
        "Natural documentary dashcam footage from a normal passenger car "
        f"{location_text} in clear, dry late-morning weather. The ego vehicle {maneuver_text}. "
        f"{road_form_text}The paved driving surface is flat and unobstructed. Visible "
        f"road boundaries, {controlled_features}camera horizon, and object scale remain coherent. "
        f"Traffic includes {', '.join(actors)} where they are visible in the scene controls. "
        "The dry charcoal-gray asphalt has subtle repaired patches and crisp white road paint. "
        "Concrete curbs, mature leafy street trees, clipped green shrubs, and restrained pale-stone "
        "and light-gray concrete mid-rise buildings line the roadway. A soft blue sky and directional "
        "natural sunlight create stable shadows, neutral color, and a calm physically grounded urban "
        "atmosphere. Road structure, traffic identity, camera motion, and fine detail remain temporally "
        "consistent across all synchronized camera views."
    )


def generated_anchor_control_path(anchor_path: Path) -> Path | None:
    """Find the front control video that produced a saved TrafficWM seed."""
    anchor_path = Path(anchor_path).resolve()
    seed_dir = next((parent for parent in anchor_path.parents if parent.name == "seed"), None)
    if seed_dir is None:
        return None
    experiment_root = seed_dir.parent
    candidates = sorted(
        (experiment_root / "controls").glob(
            "warmup-*/warmup-*.camera_front_wide_120fov.mp4"
        )
    )
    return candidates[0].resolve() if len(candidates) == 1 else None


def control_geometry_similarity(first: Path, second: Path) -> dict[str, Any]:
    """Compare projected lane geometry while ignoring colored dynamic objects."""
    import cv2
    import numpy as np

    def geometry_mask(path: Path) -> np.ndarray:
        capture = cv2.VideoCapture(str(Path(path).resolve()))
        try:
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok or frame is None:
            raise ValueError(f"Cannot decode control video: {path}")
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        white_map = (hsv[:, :, 1] <= 80) & (hsv[:, :, 2] >= 130)
        magenta_boundary = (
            (hsv[:, :, 0] >= 140)
            & (hsv[:, :, 0] <= 175)
            & (hsv[:, :, 1] >= 100)
            & (hsv[:, :, 2] >= 100)
        )
        mask = (white_map | magenta_boundary).astype(np.uint8)
        mask[: int(round(mask.shape[0] * 0.18)), :] = 0
        return mask

    first_mask = geometry_mask(first)
    second_mask = geometry_mask(second)
    if first_mask.shape != second_mask.shape:
        second_mask = cv2.resize(
            second_mask,
            (first_mask.shape[1], first_mask.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )
    first_pixels = int(first_mask.sum())
    second_pixels = int(second_mask.sum())
    tolerance_pixels = 2
    kernel = np.ones((2 * tolerance_pixels + 1, 2 * tolerance_pixels + 1), np.uint8)
    first_dilated = cv2.dilate(first_mask, kernel)
    second_dilated = cv2.dilate(second_mask, kernel)
    first_coverage = int(np.logical_and(first_mask, second_dilated).sum()) / max(
        1, first_pixels
    )
    second_coverage = int(np.logical_and(second_mask, first_dilated).sum()) / max(
        1, second_pixels
    )
    coverage_f1 = 2.0 * first_coverage * second_coverage / max(
        1e-9, first_coverage + second_coverage
    )
    return {
        "schema": "denseworld.control-geometry-similarity.v1",
        "first": str(Path(first).resolve()),
        "second": str(Path(second).resolve()),
        "tolerance_pixels": tolerance_pixels,
        "first_coverage": round(first_coverage, 6),
        "second_coverage": round(second_coverage, 6),
        "coverage_f1": round(coverage_f1, 6),
        "first_geometry_pixels": first_pixels,
        "second_geometry_pixels": second_pixels,
    }


def verify_transfer_anchor_geometry(
    anchor: dict[str, Any],
    target_control: Path,
) -> dict[str, Any]:
    """Verify that an RGB anchor was rendered from the target camera geometry."""
    verified = dict(anchor or {})
    selection = str(verified.get("selection") or "")
    source_value = str(verified.get("control_path") or "").strip()
    if not source_value:
        if selection == "same_recording_omnidreams_frame":
            raise ValueError(
                "Same-recording OmniDreams anchor is missing its paired HD-map frame"
            )
        return verified
    source_control = Path(source_value).expanduser().resolve()
    if not source_control.is_file():
        raise FileNotFoundError(
            f"Transfer replay appearance-anchor control does not exist: {source_control}"
        )
    minimum = float(
        verified.get("geometry_min_f1")
        or (
            SAME_RECORDING_ANCHOR_MIN_GEOMETRY_F1
            if selection == "same_recording_omnidreams_frame"
            else 0.9
        )
    )
    geometry = control_geometry_similarity(source_control, Path(target_control))
    geometry.update(
        {
            "required_coverage_f1": minimum,
            "status": "verified",
        }
    )
    verified["geometry"] = geometry
    verified["alignment_status"] = "verified_control_geometry"
    if float(geometry["coverage_f1"]) < minimum:
        raise ValueError(
            "The replay appearance anchor is incompatible with the selected traffic geometry "
            f"(coverage F1={float(geometry['coverage_f1']):.3f}, required >= {minimum:.3f})"
        )
    return verified


def _mapping_value(mapping: dict, actor_id: Any, default: Any = None) -> Any:
    if actor_id in mapping:
        return mapping[actor_id]
    actor_text = str(actor_id)
    if actor_text in mapping:
        return mapping[actor_text]
    try:
        numeric_id = int(actor_text)
        if numeric_id in mapping:
            return mapping[numeric_id]
    except ValueError:
        pass
    return next((value for key, value in mapping.items() if str(key) == actor_text), default)


def _recording_actor_type(data: dict[str, Any], actor_id: Any) -> str:
    road_user_type = data.get("road_user_type") or {}
    vehicle_class = data.get("vehicle_class") or {}
    source_type = str(_mapping_value(road_user_type, actor_id, "vehicle") or "vehicle").lower()
    source_class = str(_mapping_value(vehicle_class, actor_id, "vehicle") or "vehicle").lower()
    if source_type == "pedestrian":
        return "pedestrian"
    if source_type in {"cyclist", "non_motorized", "bicycle"}:
        return "cyclist"
    if source_class in {"truck", "bus"}:
        return "truck"
    return "car"


def _is_motorized_recording_actor(data: dict[str, Any], actor_id: Any) -> bool:
    return _recording_actor_type(data, actor_id) not in {"pedestrian", "cyclist"}


def operational_ego_id(export_ego_id: str, status: dict[str, Any], *, av_enabled: bool) -> str:
    """Prefer the active controlled AV over the exporter fallback ego."""
    controlled_av_id = str(status.get("av_id") or "")
    if av_enabled and controlled_av_id:
        return controlled_av_id
    return str(export_ego_id or "")


def inspect_recording_window(
    recording_path: Path,
    *,
    start_step: int,
    end_step: int,
    ego_id: str = "",
    max_duration_seconds: float = 15.0,
) -> dict[str, Any]:
    """Validate an inclusive CityNDE replay window for seven-view export."""
    recording_path = Path(recording_path).resolve()
    with recording_path.open("rb") as stream:
        data = pickle.load(stream)
    id_steps = list(data.get("vehicle_id_per_step") or [])
    state_steps = list(data.get("vehicle_state_per_step") or [])
    frame_count = min(len(id_steps), len(state_steps))
    experiment_metadata = (
        data.get("experiment_params") if isinstance(data.get("experiment_params"), dict) else {}
    )
    experiment_metadata = dict(experiment_metadata)
    sidecar = recording_path.with_suffix(recording_path.suffix + ".meta.json")
    try:
        sidecar_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if isinstance(sidecar_metadata, dict):
            experiment_metadata.update(sidecar_metadata)
    except (OSError, TypeError, ValueError):
        pass

    requested_start_step = int(start_step)
    requested_end_step = int(end_step)
    if frame_count < 2:
        raise ValueError("Recording does not contain at least two traffic frames")

    configured_steps = max(0, int(experiment_metadata.get("total_step", 0) or 0))
    explicit_offset = experiment_metadata.get("recording_operational_start_step")
    if explicit_offset is not None:
        operational_offset = max(0, int(explicit_offset or 0))
    elif configured_steps and frame_count >= configured_steps + 1:
        # CityNDE persists its model history (and DenseWorld warmup when enabled)
        # before display time t=0. Completed legacy recordings did not store the
        # offset explicitly, but their configured frame count makes it exact.
        operational_offset = frame_count - (configured_steps + 1)
    else:
        operational_offset = 0
    if operational_offset >= frame_count - 1:
        operational_offset = 0
    operational_frame_count = frame_count - operational_offset

    if (
        requested_start_step < 0
        or requested_end_step <= requested_start_step
        or requested_end_step >= operational_frame_count
    ):
        raise ValueError(
            f"Frame range must satisfy 0 <= start < end < {operational_frame_count}; "
            f"received {requested_start_step}..{requested_end_step}"
        )
    recording_start_step = requested_start_step + operational_offset
    recording_end_step = requested_end_step + operational_offset
    simulator_metadata = data.get("simulator_meta_info") or {}
    resolution = float(simulator_metadata.get("resolution", 0.1) or 0.1)
    if resolution <= 0:
        resolution = 0.1
    source_fps = 1.0 / resolution
    duration_seconds = (requested_end_step - requested_start_step) * resolution
    if duration_seconds > float(max_duration_seconds) + 1e-6:
        raise ValueError(
            f"Replay window is {duration_seconds:.3f}s; maximum supported duration is "
            f"{float(max_duration_seconds):g}s"
        )
    window_ids = id_steps[recording_start_step : recording_end_step + 1]
    persistent = {str(value) for value in window_ids[0]}
    for values in window_ids[1:]:
        persistent.intersection_update(str(value) for value in values)
    if not persistent:
        raise ValueError("Replay window has no vehicle present in every selected frame")
    selected_ego = str(ego_id or experiment_metadata.get("av_id") or "")
    motorized_persistent = sorted(value for value in persistent if _is_motorized_recording_actor(data, value))
    if not motorized_persistent:
        raise ValueError("Replay window has no persistent motorized actor for the Cosmos camera rig")
    if selected_ego not in motorized_persistent:
        selected_ego = motorized_persistent[0]

    start_ids = [str(value) for value in id_steps[recording_start_step]]
    start_states = state_steps[recording_start_step]
    ego_pose: dict[str, float | str] = {"id": selected_ego}
    if selected_ego in start_ids:
        values = list(start_states[start_ids.index(selected_ego)])
        if len(values) >= 3:
            ego_pose.update(
                {
                    "x": float(values[0]),
                    "y": float(values[1]),
                    "heading": float(values[2]),
                }
            )

    raw_map = (data.get("map") or {}).get("polyline") or {}
    normalized_polylines = {}
    for polyline_id, value in raw_map.items():
        if not isinstance(value, dict):
            continue
        normalized_polylines[polyline_id] = {
            **value,
            "points": value.get("points") if value.get("points") is not None else value.get("states"),
        }
    semantics = build_citynde_semantics({"polyline_dict": normalized_polylines})
    return {
        "frame_count": frame_count,
        "operational_frame_count": operational_frame_count,
        "operational_offset_steps": operational_offset,
        "start_step": requested_start_step,
        "end_step": requested_end_step,
        "recording_start_step": recording_start_step,
        "recording_end_step": recording_end_step,
        "source_steps": requested_end_step - requested_start_step + 1,
        "source_fps": source_fps,
        "duration_seconds": duration_seconds,
        "ego_id": selected_ego,
        "ego_pose": ego_pose,
        "map_path": str(experiment_metadata.get("map_path") or ""),
        "persistent_vehicle_count": len(persistent),
        "map_state": semantics,
    }


def transfer_frame_plan(duration_seconds: float, fps: int = 10) -> dict[str, int | bool]:
    target_frames = max(1, int(round(max(0.1, float(duration_seconds)) * fps)))
    autoregressive = target_frames > TRANSFER_NATIVE_FRAMES
    stride = TRANSFER_NATIVE_FRAMES - TRANSFER_CHUNK_OVERLAP
    chunks = (
        max(1, (max(0, target_frames - TRANSFER_NATIVE_FRAMES) + stride - 1) // stride + 1)
        if autoregressive
        else 1
    )
    native_frames = TRANSFER_NATIVE_FRAMES + stride * (chunks - 1)
    return {
        "target_frames": target_frames,
        "autoregressive": autoregressive,
        "chunks": chunks,
        "native_frames": native_frames,
        "control_frames_30fps": native_frames * 3,
    }


def transfer_segment_plan(
    duration_seconds: float,
    fps: int = 10,
    overlap_frames: int = TRANSFER_SEGMENT_BLEND_FRAMES,
) -> dict[str, Any]:
    """Plan native windows whose shared prefix is used for conditional chaining."""
    target_frames = max(1, int(round(max(0.1, float(duration_seconds)) * fps)))
    overlap = max(0, min(int(overlap_frames), TRANSFER_NATIVE_FRAMES - 1))
    segments: list[dict[str, int | float]] = []
    start_frame = 0
    while start_frame < target_frames:
        output_frames = min(TRANSFER_NATIVE_FRAMES, target_frames - start_frame)
        segments.append(
            {
                "index": len(segments),
                "start_frame": start_frame,
                "start_seconds": start_frame / float(fps),
                "output_frames": output_frames,
            }
        )
        if start_frame + output_frames >= target_frames:
            break
        start_frame += max(1, output_frames - overlap)
    return {
        "target_frames": target_frames,
        "fps": int(fps),
        "overlap_frames": overlap if len(segments) > 1 else 0,
        "segments": segments,
    }


def transfer_replay_strategy(
    frame_plan: dict[str, Any],
    *,
    view_mode: str,
    anchor_selection: str,
    requested: str = "auto",
) -> str:
    """Choose long-video generation only when exact RGB resets are available."""
    requested = str(requested or "auto").strip().lower()
    if requested not in {"auto", "autoregressive", "segmented"}:
        raise ValueError(
            "world_transfer_long_strategy must be auto, autoregressive, or segmented"
        )
    if not bool(frame_plan.get("autoregressive")):
        return "native_window"
    exact_segment_anchors = (
        str(view_mode).strip().lower() == "front"
        and str(anchor_selection).strip() == "same_recording_omnidreams_frame"
    )
    if requested == "segmented" and not exact_segment_anchors:
        raise ValueError(
            "Segmented Transfer replay requires exact same-recording OmniDreams anchors"
        )
    if requested != "autoregressive" and exact_segment_anchors:
        return "segmented_exact_anchors"
    return "official_autoregressive"


def transfer_anchor_frame_indices(
    duration_seconds: float,
    *,
    start_seconds: float = 0.0,
    source_fps: float = 30.0,
) -> list[int]:
    """Return exact source-video frames needed by segmented replay anchors."""
    if source_fps <= 0.0:
        raise ValueError("Transfer anchor source FPS must be positive")
    return [
        max(
            0,
            int(
                round(
                    (float(start_seconds) + float(segment["start_seconds"]))
                    * float(source_fps)
                )
            ),
        )
        for segment in transfer_segment_plan(duration_seconds)["segments"]
    ]


def recording_to_traffic_frames(
    recording_path: Path,
    *,
    duration_seconds: float,
    ego_id: str = "",
    source_fps: int = 10,
) -> tuple[list[dict[str, Any]], str]:
    with Path(recording_path).open("rb") as stream:
        data = pickle.load(stream)
    id_steps = list(data.get("vehicle_id_per_step") or [])
    state_steps = list(data.get("vehicle_state_per_step") or [])
    source_steps = int(round(float(duration_seconds) * source_fps)) + 1
    if source_steps < 2 or len(id_steps) < source_steps or len(state_steps) < source_steps:
        raise ValueError(
            f"Recording has {len(id_steps)} steps; {source_steps} are required for {duration_seconds:.3f}s"
        )
    start = len(id_steps) - source_steps
    window_ids = id_steps[start:]
    persistent = {str(item) for item in window_ids[0]}
    for ids in window_ids[1:]:
        persistent.intersection_update(str(item) for item in ids)
    motorized_persistent = sorted(value for value in persistent if _is_motorized_recording_actor(data, value))
    if not motorized_persistent:
        raise ValueError("Recording window has no persistent motorized actor for the Cosmos camera rig")
    if str(ego_id) not in motorized_persistent:
        ego_id = motorized_persistent[0]
    static = data.get("vehicle_static_attribute") or {}
    static_by_id = {str(key): value for key, value in static.items()}
    light_ids = list(data.get("dynamic_polyline_id_per_step") or [])
    light_states = list(data.get("dynamic_polyline_state_per_step") or [])
    pedestrian_ids = list(data.get("pedestrian_id_per_step") or [])
    pedestrian_states = list(data.get("pedestrian_state_per_step") or [])
    pedestrian_static = data.get("pedestrian_static_attribute") or {}
    pedestrian_static_by_id = {str(key): value for key, value in pedestrian_static.items()}

    frames: list[dict[str, Any]] = []
    for local_index, (ids, states) in enumerate(zip(window_ids, state_steps[start:])):
        actors = []
        ego = {}
        for vehicle_id, state in zip(ids, states):
            values = list(state)
            dims = static_by_id.get(str(vehicle_id), [3.8, 1.8, 1.5])
            item = {
                "id": str(vehicle_id),
                "x": float(values[0]),
                "y": float(values[1]),
                "heading": float(values[2]),
                "vx": float(values[3]),
                "vy": float(values[4]),
                "ax": float(values[5]) if len(values) > 5 else 0.0,
                "ay": float(values[6]) if len(values) > 6 else 0.0,
                "speed": float((float(values[3]) ** 2 + float(values[4]) ** 2) ** 0.5),
                "length": float(dims[0]),
                "width": float(dims[1]),
                "height": float(dims[2]),
                "type": _recording_actor_type(data, vehicle_id),
            }
            if str(vehicle_id) == str(ego_id):
                ego = item
            else:
                actors.append(item)
        absolute_index = start + local_index
        if absolute_index < len(pedestrian_ids) and absolute_index < len(pedestrian_states):
            for pedestrian_id, state in zip(pedestrian_ids[absolute_index], pedestrian_states[absolute_index]):
                values = list(state)
                dims = pedestrian_static_by_id.get(str(pedestrian_id), [0.55, 0.55, 1.72])
                actors.append(
                    {
                        "id": str(pedestrian_id),
                        "x": float(values[0]),
                        "y": float(values[1]),
                        "heading": float(values[2]),
                        "vx": float(values[3]),
                        "vy": float(values[4]),
                        "ax": float(values[5]) if len(values) > 5 else 0.0,
                        "ay": float(values[6]) if len(values) > 6 else 0.0,
                        "speed": float((float(values[3]) ** 2 + float(values[4]) ** 2) ** 0.5),
                        "length": float(dims[0]),
                        "width": float(dims[1]),
                        "height": float(dims[2]),
                        "type": "pedestrian",
                    }
                )
        lights = {}
        if absolute_index < len(light_ids) and absolute_index < len(light_states):
            for light_id, raw_state in zip(light_ids[absolute_index], light_states[absolute_index]):
                values = list(raw_state)
                lights[str(light_id)] = int(max(range(min(4, len(values))), key=lambda idx: values[idx])) if values else 3
        frames.append(
            {
                "sim_time": round(local_index / float(source_fps), 6),
                "ego": ego,
                "actors": actors,
                "traffic_lights": lights,
            }
        )
    return frames, str(ego_id)


def control_paths(control_root: Path, clip_id: str, cameras: list[str] | tuple[str, ...] | None = None) -> dict[str, Path]:
    directory = control_root / clip_id
    camera_names = tuple(cameras or CAMERAS)
    paths = {camera: directory / f"{clip_id}.{camera}.mp4" for camera in camera_names}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing rendered control videos: " + ", ".join(missing))
    return paths


def prepare_transfer_input_media(
    source: Path,
    target: Path,
    *,
    frames: int = 87,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Wrap a still appearance anchor in the video container Transfer expects."""
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Transfer appearance anchor does not exist: {source}")
    if source.suffix.lower() not in {".bmp", ".jpeg", ".jpg", ".png", ".webp"}:
        return source

    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # OmniDreams emits the calibrated 1280x704 crop used by the world model.
    # Contain-and-pad restores Transfer's 1280x720 container without changing
    # horizontal FOV; cover-and-crop would silently zoom the geometry by 2.3%.
    video_filter = (
        f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
        f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-i", str(source), "-vf", video_filter,
            "-frames:v", str(max(1, int(frames))), "-r", str(max(1, int(fps))),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
        ],
        check=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError(f"Failed to create Transfer input video: {target}")
    return target


def prepare_transfer_conditioning_video(
    source: Path,
    target: Path,
    *,
    start_model_frame: int = 0,
    conditional_frames: int = TRANSFER_SEGMENT_CONDITION_FRAMES,
    frames: int = TRANSFER_NATIVE_FRAMES * 3,
    fps: int = 30,
    model_fps: int = 10,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Build a 30 Hz Transfer input with an exact moving conditional prefix."""
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Transfer conditioning source does not exist: {source}")
    source_report = probe_video(source)
    source_fps = float(source_report["fps"])
    if source_fps <= 0.0 or model_fps <= 0 or fps <= 0:
        raise ValueError("Transfer conditioning video requires positive frame rates")
    source_factor_value = source_fps / float(model_fps)
    source_factor = int(round(source_factor_value))
    if source_factor < 1 or abs(source_factor_value - source_factor) > 1e-3:
        raise ValueError(
            f"Conditioning source FPS {source_fps:g} is not evenly divisible by "
            f"Transfer model FPS {model_fps:g}"
        )
    output_factor_value = float(fps) / float(model_fps)
    output_factor = int(round(output_factor_value))
    if output_factor < 1 or abs(output_factor_value - output_factor) > 1e-3:
        raise ValueError(
            f"Transfer input FPS {fps:g} is not an integer multiple of model FPS {model_fps:g}"
        )
    conditional_frames = int(conditional_frames)
    if conditional_frames not in {1, 5}:
        raise ValueError("Transfer conditioning prefix must contain 1 or 5 model frames")
    start_model_frame = max(0, int(start_model_frame))
    available_model_frames = int(source_report["frames"]) // source_factor
    if start_model_frame + conditional_frames > available_model_frames:
        raise ValueError(
            f"Conditioning source has {available_model_frames} model-rate frames, but frames "
            f"{start_model_frame}..{start_model_frame + conditional_frames - 1} were requested"
        )

    # Select exact source frames rather than relying on timestamp rounding. The
    # selected prefix is placed at 10 Hz, padded to the native 29-frame window,
    # then repeated at 30 Hz so Transfer's official factor-3 loader recovers the
    # same five frames at indices 0, 3, 6, 9, and 12.
    source_indices = [
        (start_model_frame + offset) * source_factor
        for offset in range(conditional_frames)
    ]
    select = "+".join(f"eq(n\\,{index})" for index in source_indices)
    model_frames = max(1, int(frames) // output_factor)
    if model_frames < conditional_frames:
        raise ValueError(
            f"Transfer input contract has {model_frames} model frames, fewer than the "
            f"{conditional_frames} conditioning frames"
        )
    video_filter = (
        f"select='{select}',setpts=N/({int(model_fps)}*TB),"
        f"fps={int(model_fps)},"
        f"tpad=stop_mode=clone:stop={model_frames - conditional_frames},"
        f"fps={int(fps)},trim=end_frame={int(frames)},setpts=N/({int(fps)}*TB),"
        f"scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
        f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p"
    )
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vf", video_filter,
            "-frames:v", str(int(frames)), "-an", "-r", str(int(fps)),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
        ],
        check=True,
    )
    report = probe_video(target)
    if (
        int(report["frames"]) != int(frames)
        or abs(float(report["fps"]) - float(fps)) > 0.02
        or int(report["width"]) != int(width)
        or int(report["height"]) != int(height)
    ):
        raise RuntimeError(
            "Prepared Transfer conditioning video violates its media contract: "
            f"{report}"
        )
    return target


def write_transfer_spec(
    path: Path,
    *,
    name: str,
    controls: dict[str, Path],
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    duration_seconds: float = 1.0,
    num_steps: int = 35,
    seed: int = 0,
    input_paths: dict[str, Path] | None = None,
    num_conditional_frames: int | None = None,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = path.parent / "prompt.txt"
    prompt_path.write_text(prompt.strip() or DEFAULT_PROMPT, encoding="utf-8")
    duration_seconds = max(0.1, float(duration_seconds))
    plan = transfer_frame_plan(duration_seconds)
    enable_ar = bool(plan["autoregressive"])
    target_frames = int(plan["target_frames"])
    num_chunks = int(plan["chunks"])
    input_paths = dict(input_paths or {})
    if input_paths and set(input_paths) != set(controls):
        raise ValueError("Transfer image conditioning requires one input path for every active camera")
    conditional_frames = (
        int(num_conditional_frames)
        if num_conditional_frames is not None
        else (1 if input_paths else 0)
    )
    if conditional_frames not in {0, 1, 5}:
        raise ValueError("Transfer num_conditional_frames must be 0, 1, or 5")
    if conditional_frames > 0 and not input_paths:
        raise ValueError("Transfer conditional frames require input media for every active camera")
    spec: dict[str, Any] = {
        "name": name,
        "prompt_path": str(prompt_path.resolve()),
        "negative_prompt": str(negative_prompt or DEFAULT_NEGATIVE_PROMPT),
        "seed": int(seed),
        "num_conditional_frames": conditional_frames,
        "fps": 10,
        "num_steps": max(1, int(num_steps)),
        "save_combined_views": False,
        "enable_autoregressive": enable_ar,
        "num_chunks": num_chunks,
        "chunk_overlap": TRANSFER_CHUNK_OVERLAP if enable_ar else 1,
    }
    for camera, control_path in controls.items():
        view = {"control_path": str(control_path.resolve())}
        if camera in input_paths:
            input_path = Path(input_paths[camera]).resolve()
            if not input_path.is_file():
                raise FileNotFoundError(f"Transfer input image/video does not exist: {input_path}")
            view["input_path"] = str(input_path)
        spec[VIEW_KEYS[camera]] = view
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**spec, "target_frames": target_frames}


def discover_transfer_views(output_dir: Path, name: str, views: list[str] | tuple[str, ...] | None = None) -> dict[str, Path]:
    view_names = tuple(views or VIEW_KEYS.values())
    paths = {view: output_dir / f"{name}_{view}.mp4" for view in view_names}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Transfer did not produce expected views: " + ", ".join(missing))
    return paths


def trim_views(
    views: dict[str, Path],
    output_dir: Path,
    *,
    frames: int,
    fps: int = 10,
    start_frame: int = 0,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    start_frame = max(0, int(start_frame))
    trimmed: dict[str, Path] = {}
    for view, source in views.items():
        source_report = probe_video(source)
        if int(source_report["frames"]) < start_frame + int(frames):
            raise ValueError(
                f"Cannot trim Transfer {view} frames {start_frame}.."
                f"{start_frame + int(frames) - 1}; source only has "
                f"{int(source_report['frames'])} frames"
            )
        target = output_dir / f"{view}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-vf",
                (
                    f"trim=start_frame={start_frame}:"
                    f"end_frame={start_frame + int(frames)},setpts=PTS-STARTPTS"
                ),
                "-an", "-r", str(fps), "-c:v", "libx264", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
            ],
            check=True,
        )
        report = probe_video(target)
        if int(report["frames"]) != int(frames):
            raise RuntimeError(
                f"Trimmed Transfer {view} has {int(report['frames'])} frames, expected {int(frames)}"
            )
        if abs(float(report["fps"]) - float(fps)) > 0.02:
            raise RuntimeError(
                f"Trimmed Transfer {view} FPS is {float(report['fps']):g}, expected {int(fps)}"
            )
        trimmed[view] = target
    return trimmed


def create_playback_proxy(
    source: Path,
    target: Path,
    *,
    duration_seconds: float,
    fps: int = 30,
) -> Path:
    """Create a fast-start display proxy without changing the native model artifact."""
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source),
            "-vf", f"tpad=stop_mode=clone:stop_duration=0.2,minterpolate=fps={int(fps)}:mi_mode=blend",
            "-t", f"{max(0.1, float(duration_seconds)):.6f}",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
        ],
        check=True,
    )
    return target


def pad_controls(
    controls: dict[str, Path],
    output_dir: Path,
    *,
    minimum_frames: int = 87,
    fps: int = 30,
) -> dict[str, Path]:
    """Clone the terminal traffic state to satisfy Transfer's native window."""
    output_dir.mkdir(parents=True, exist_ok=True)
    padded: dict[str, Path] = {}
    for camera, source in controls.items():
        target = output_dir / source.name
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-threads", "2", "-i", str(source), "-vf",
            f"tpad=stop_mode=clone:stop_duration=30,trim=end_frame={int(minimum_frames)},setpts=PTS-STARTPTS",
            "-an", "-r", str(fps), "-c:v", "libx264", "-threads", "2", "-crf", "16",
            "-pix_fmt", "yuv420p", str(target),
        ]
        for attempt in range(3):
            try:
                subprocess.run(command, check=True)
                break
            except subprocess.CalledProcessError as exc:
                if exc.returncode not in {-6, 134} or attempt == 2:
                    raise
                # gRPC's at-fork handlers can transiently abort a child while
                # resident model threads are starting. Retrying the standalone
                # media transform is deterministic and does not rerun a model.
                time.sleep(0.5 * (attempt + 1))
        report = probe_video(target)
        if int(report["frames"]) != int(minimum_frames):
            raise RuntimeError(
                f"Padded Transfer control {camera} has {int(report['frames'])} frames, "
                f"expected {int(minimum_frames)}"
            )
        if abs(float(report["fps"]) - float(fps)) > 0.02:
            raise RuntimeError(
                f"Padded Transfer control {camera} FPS is {float(report['fps']):g}, "
                f"expected {int(fps)}"
            )
        padded[camera] = target
    return padded


def slice_and_pad_controls(
    controls: dict[str, Path],
    output_dir: Path,
    *,
    start_frame: int,
    minimum_frames: int = TRANSFER_NATIVE_FRAMES * 3,
    fps: int = 30,
) -> dict[str, Path]:
    """Extract a control window and clone its terminal state to the native contract."""
    output_dir.mkdir(parents=True, exist_ok=True)
    sliced: dict[str, Path] = {}
    for camera, source in controls.items():
        target = output_dir / source.name
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-vf",
                (
                    f"trim=start_frame={max(0, int(start_frame))},setpts=PTS-STARTPTS,"
                    f"tpad=stop_mode=clone:stop_duration=30,"
                    f"trim=end_frame={int(minimum_frames)},setpts=PTS-STARTPTS"
                ),
                "-an", "-r", str(fps), "-c:v", "libx264", "-crf", "16",
                "-pix_fmt", "yuv420p", str(target),
            ],
            check=True,
        )
        report = probe_video(target)
        if int(report["frames"]) != int(minimum_frames):
            raise RuntimeError(
                f"Sliced Transfer control {camera} has {int(report['frames'])} frames, "
                f"expected {int(minimum_frames)}"
            )
        sliced[camera] = target
    return sliced


def stitch_transfer_segments(
    segments: list[Path],
    target: Path,
    *,
    segment_frames: list[int],
    overlap_frames: int,
    target_frames: int,
    fps: int = 10,
    transition: str = "crossfade",
) -> Path:
    """Stitch native Transfer windows using a cross-fade or exact overlap removal."""
    if not segments or len(segments) != len(segment_frames):
        raise ValueError("Transfer segment paths and frame counts must be non-empty and aligned")
    target.parent.mkdir(parents=True, exist_ok=True)
    if len(segments) == 1:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(segments[0]),
                "-vf", f"trim=end_frame={int(target_frames)},setpts=PTS-STARTPTS",
                "-frames:v", str(int(target_frames)), "-an", "-r", str(int(fps)),
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(target),
            ],
            check=True,
        )
        return target

    overlap = max(1, int(overlap_frames))
    if transition not in {"crossfade", "drop_overlap"}:
        raise ValueError("Transfer segment transition must be crossfade or drop_overlap")
    inputs: list[str] = []
    filters: list[str] = []
    for index, path in enumerate(segments):
        inputs.extend(["-i", str(path)])
        start = overlap if transition == "drop_overlap" and index else 0
        filters.append(
            f"[{index}:v]trim=start_frame={start}:end_frame={int(segment_frames[index])},"
            f"settb=AVTB,setpts=PTS-STARTPTS[s{index}]"
        )
    if transition == "drop_overlap":
        labels = "".join(f"[s{index}]" for index in range(len(segments)))
        filters.append(f"{labels}concat=n={len(segments)}:v=1:a=0[stitched]")
        previous = "stitched"
    else:
        composed_frames = int(segment_frames[0])
        previous = "s0"
        duration = overlap / float(fps)
        for index in range(1, len(segments)):
            output = f"x{index}"
            offset = (composed_frames - overlap) / float(fps)
            filters.append(
                f"[{previous}][s{index}]xfade=transition=fade:duration={duration:.6f}:"
                f"offset={offset:.6f}[{output}]"
            )
            composed_frames += int(segment_frames[index]) - overlap
            previous = output
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", ";".join(filters), "-map", f"[{previous}]",
            "-frames:v", str(int(target_frames)), "-an", "-r", str(int(fps)),
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(target),
        ],
        check=True,
    )
    return target


def analyze_transfer_segment_boundaries(
    segments: list[Path],
    output_dir: Path,
    *,
    overlap_frames: int,
) -> dict[str, Any]:
    """Compare independently generated windows at their shared source times."""
    import cv2
    import numpy as np

    if len(segments) < 2:
        raise ValueError("Transfer boundary QA requires at least two segments")
    overlap = max(1, int(overlap_frames))
    decoded: list[list[np.ndarray]] = []
    internal_differences: list[float] = []
    for path in segments:
        capture = cv2.VideoCapture(str(Path(path).resolve()))
        frames: list[np.ndarray] = []
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(
                    cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
                )
        finally:
            capture.release()
        if len(frames) < overlap:
            raise ValueError(
                f"Transfer segment {path} has {len(frames)} frames, fewer than overlap {overlap}"
            )
        decoded.append(frames)
        internal_differences.extend(
            float(np.mean(np.abs(second.astype(np.float32) - first.astype(np.float32))))
            for first, second in zip(frames, frames[1:])
        )

    internal = np.asarray(internal_differences, dtype=np.float64)
    internal_p95 = float(np.percentile(internal, 95)) if internal.size else 0.0
    # Exact overlap frames describe the same traffic timestamp. Allow normal
    # compression/model variation, but reject a boundary that differs much more
    # than motion between adjacent frames inside either native window.
    threshold = max(18.0, 1.5 * internal_p95)
    boundaries: list[dict[str, Any]] = []
    contact_rows: list[np.ndarray] = []
    errors: list[str] = []
    for boundary_index, (before, after) in enumerate(zip(decoded, decoded[1:])):
        comparisons: list[dict[str, float | int]] = []
        contact_frames: list[np.ndarray] = []
        for offset in range(overlap):
            before_frame = before[-overlap + offset]
            after_frame = after[offset]
            color_mae = float(
                np.mean(
                    np.abs(
                        before_frame.astype(np.float32)
                        - after_frame.astype(np.float32)
                    )
                )
            )
            before_gray = cv2.cvtColor(before_frame, cv2.COLOR_BGR2GRAY)
            after_gray = cv2.cvtColor(after_frame, cv2.COLOR_BGR2GRAY)
            luminance_mae = float(
                np.mean(
                    np.abs(before_gray.astype(np.float32) - after_gray.astype(np.float32))
                )
            )
            comparisons.append(
                {
                    "overlap_offset": offset,
                    "color_mae": round(color_mae, 4),
                    "luminance_mae": round(luminance_mae, 4),
                }
            )
            for label, frame in (("tail", before_frame), ("head", after_frame)):
                annotated = frame.copy()
                cv2.rectangle(annotated, (0, 0), (320, 25), (15, 23, 42), -1)
                cv2.putText(
                    annotated,
                    f"b{boundary_index + 1} {label} t+{offset} mae={color_mae:.1f}",
                    (7, 17),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.42,
                    (248, 250, 252),
                    1,
                    cv2.LINE_AA,
                )
                contact_frames.append(annotated)
        color_values = np.asarray(
            [float(item["color_mae"]) for item in comparisons], dtype=np.float64
        )
        median_color_mae = float(np.median(color_values))
        passed = median_color_mae <= threshold
        if not passed:
            errors.append(
                f"Transfer segment boundary {boundary_index + 1} overlap color MAE "
                f"{median_color_mae:.3f} exceeds {threshold:.3f}"
            )
        boundaries.append(
            {
                "boundary": boundary_index + 1,
                "left_segment": boundary_index,
                "right_segment": boundary_index + 1,
                "passed": passed,
                "median_color_mae": round(median_color_mae, 4),
                "maximum_color_mae": round(float(color_values.max()), 4),
                "comparisons": comparisons,
            }
        )
        contact_rows.append(np.hstack(contact_frames))

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    contact_sheet = output_dir / "boundary_contact_sheet.jpg"
    if not cv2.imwrite(str(contact_sheet), np.vstack(contact_rows)):
        raise OSError(f"Failed to write Transfer boundary contact sheet: {contact_sheet}")
    report = {
        "schema": "denseworld.transfer-segment-boundary-qa.v1",
        "passed": not errors,
        "errors": errors,
        "segment_count": len(segments),
        "overlap_frames": overlap,
        "internal_adjacent_color_mae": {
            "median": round(float(np.median(internal)), 4) if internal.size else 0.0,
            "p95": round(internal_p95, 4),
        },
        "boundary_median_threshold": round(threshold, 4),
        "boundaries": boundaries,
        "contact_sheet": str(contact_sheet),
    }
    (output_dir / "boundary_consistency.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def assess_transfer_crossfade_boundaries(report: dict[str, Any]) -> dict[str, Any]:
    """Classify raw overlap differences before evaluating the displayed cross-fade."""
    assessed = dict(report or {})
    internal = assessed.get("internal_adjacent_color_mae") or {}
    internal_p95 = max(0.0, float(internal.get("p95", 0.0) or 0.0))
    # Moderate appearance differences are exactly what the five-frame blend is
    # intended to absorb. A difference beyond both an absolute 32/255 bound and
    # 2.5x normal motion is too large to hide without visible double exposure.
    hard_threshold = max(32.0, 2.5 * internal_p95)
    gross_errors = []
    for boundary in assessed.get("boundaries") or []:
        median = float(boundary.get("median_color_mae", 0.0) or 0.0)
        if median > hard_threshold:
            gross_errors.append(
                f"Transfer segment boundary {int(boundary.get('boundary', 0) or 0)} "
                f"overlap color MAE {median:.3f} exceeds cross-fade hard limit "
                f"{hard_threshold:.3f}"
            )
    assessed.update(
        {
            "candidate_overlap_passed": bool(assessed.get("passed")),
            "candidate_overlap_warnings": list(assessed.get("errors") or []),
            "crossfade_hard_threshold": round(hard_threshold, 4),
            "crossfade_acceptable": not gross_errors,
            "crossfade_errors": gross_errors,
            "final_output_qa_required": True,
        }
    )
    return assessed


def extract_seed_frame(
    front_video: Path,
    target: Path,
    frame_index: int = WARMUP_TERMINAL_FRAME_INDEX,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(front_video), "-vf",
            f"select=eq(n\\,{max(0, int(frame_index))}),crop=1280:704:0:8",
            "-frames:v", "1", str(target),
        ],
        check=True,
    )
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError("Failed to extract the Transfer terminal seed frame")
    return target


def state_to_traffic_frame(
    state: dict[str, Any],
    ego_id: str = "",
    *,
    strict_ego: bool = False,
) -> tuple[dict[str, Any], str]:
    vehicles = list(state.get("vehicles") or state.get("actors") or [])
    ego = None
    if strict_ego and ego_id:
        ego = next(
            (
                item
                for item in vehicles
                if str(item.get("id")) == ego_id
                and str(item.get("road_user_type") or item.get("type") or "vehicle").lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ),
            None,
        )
        if ego is None:
            raise RuntimeError(
                f"World camera ego {ego_id!r} is absent; refusing to switch the video viewpoint"
            )
    if ego is None:
        ego = next(
            (item for item in vehicles if str(item.get("type") or "").upper() == "AV"),
            None,
        )
    if ego is None and ego_id:
        ego = next(
            (
                item
                for item in vehicles
                if str(item.get("id")) == ego_id
                and str(item.get("road_user_type") or item.get("type") or "vehicle").lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ),
            None,
        )
    if ego is None:
        ego = next(
            (
                item
                for item in vehicles
                if str(item.get("road_user_type") or item.get("type") or "vehicle").lower()
                not in {"pedestrian", "cyclist", "non_motorized"}
            ),
            None,
        )
    ego = dict(ego or {})
    ego_id = str(ego.get("id") or ego_id)
    actors = [dict(item) for item in vehicles if str(item.get("id")) != ego_id]
    return (
        {
            "sim_time": float(state.get("sim_time", 0.0) or 0.0),
            "ego": ego,
            "vehicles": actors,
            "traffic_lights": state.get("traffic_lights") or {},
            "lane_context": (
                dict(state.get("lane_context") or {})
                if isinstance(state.get("lane_context"), dict)
                else {}
            ),
        },
        ego_id,
    )
