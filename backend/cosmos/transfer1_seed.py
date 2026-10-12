"""Run Cosmos-Transfer1 Sample-AV as the TrafficWM world-seed generator."""
from __future__ import annotations

import json
import hashlib
import os
import signal
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from backend.cosmos.pipeline_utils import probe_video


TRANSFER1_NATIVE_FPS = 24
TRANSFER1_NATIVE_FRAMES = 121
TRANSFER1_WARMUP_FRAME_INDEX = TRANSFER1_NATIVE_FRAMES - 1
TRANSFER1_WARMUP_SECONDS = TRANSFER1_WARMUP_FRAME_INDEX / TRANSFER1_NATIVE_FPS
TRANSFER1_CONTAINER_SECONDS = TRANSFER1_NATIVE_FRAMES / TRANSFER1_NATIVE_FPS
_TRANSFER1_LOCK = threading.Lock()


def _tail(path: Path, limit: int = 6000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _free_port() -> int:
    preferred = int(os.environ.get("COSMOS_TRANSFER1_MASTER_PORT", "29641") or 29641)
    for candidate in range(preferred, preferred + 32):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
                # torchrun listens on all local interfaces. Probing only the
                # loopback address can miss a listener owned by another CUDA
                # process on the host interface.
                stream.bind(("0.0.0.0", candidate))
                return candidate
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("0.0.0.0", 0))
        return int(stream.getsockname()[1])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _transfer1_cache_identity(
    *,
    root: Path,
    prepared_control: Path,
    prompt: str,
    negative_prompt: str,
    num_steps: int,
    guidance: float,
    seed: int,
    gpu_count: int,
) -> tuple[str, dict]:
    checkpoint_paths = (
        root / "checkpoints" / "nvidia" / "Cosmos-Transfer1-7B-Sample-AV" / "base_model.pt",
        root / "checkpoints" / "nvidia" / "Cosmos-Transfer1-7B-Sample-AV" / "hdmap_control.pt",
    )
    checkpoint_signature = []
    for checkpoint in checkpoint_paths:
        stat = checkpoint.stat()
        checkpoint_signature.append(
            {
                "name": checkpoint.name,
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
            }
        )
    identity = {
        "schema": "denseworld.transfer1-seed-cache.v1",
        "control_sha256": _sha256(prepared_control),
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "num_steps": max(1, int(num_steps)),
        "guidance": float(guidance),
        "seed": int(seed),
        "gpu_count": int(gpu_count),
        "native_frames": TRANSFER1_NATIVE_FRAMES,
        "native_fps": TRANSFER1_NATIVE_FPS,
        "checkpoints": checkpoint_signature,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), identity


def _terminate_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=15.0)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass


def prepare_transfer1_hdmap_control(source: Path, target: Path) -> dict:
    """Convert a TrafficWM front HDMap stream to Transfer1's native contract."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    source_media = probe_video(source)
    source_fps = float(source_media["fps"])
    source_frames = int(source_media["frames"])
    source_span_seconds = (source_frames - 1) / source_fps
    if source_span_seconds + 1e-3 < TRANSFER1_WARMUP_SECONDS:
        raise ValueError(
            f"Transfer1 requires {TRANSFER1_WARMUP_SECONDS:g} seconds of dynamic HDMap "
            f"control, but the source spans only {source_span_seconds:.3f} seconds"
        )
    width = int(source_media["width"])
    height = int(source_media["height"])
    if width == 1280 and height == 720:
        geometry_filter = "crop=1280:704:0:8"
    elif width == 1280 and height == 704:
        geometry_filter = "null"
    else:
        geometry_filter = (
            "scale=1280:704:force_original_aspect_ratio=increase,"
            "crop=1280:704"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            (
                f"{geometry_filter},fps={TRANSFER1_NATIVE_FPS},"
                "tpad=stop_mode=clone:stop_duration=10,"
                f"trim=end_frame={TRANSFER1_NATIVE_FRAMES},setpts=PTS-STARTPTS"
            ),
            "-an",
            "-r",
            str(TRANSFER1_NATIVE_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
    )
    media = probe_video(target)
    if int(media["frames"]) != TRANSFER1_NATIVE_FRAMES:
        raise RuntimeError(
            f"Transfer1 control has {int(media['frames'])} frames; "
            f"expected {TRANSFER1_NATIVE_FRAMES}"
        )
    if abs(float(media["fps"]) - TRANSFER1_NATIVE_FPS) > 0.02:
        raise RuntimeError(
            f"Transfer1 control FPS is {float(media['fps']):g}; "
            f"expected {TRANSFER1_NATIVE_FPS}"
        )
    if int(media["width"]) != 1280 or int(media["height"]) != 704:
        raise RuntimeError("Transfer1 control must be 1280x704")
    return {
        "source": str(source),
        "source_media": source_media,
        "source_span_seconds": source_span_seconds,
        "warmup_endpoint_seconds": TRANSFER1_WARMUP_SECONDS,
        "media": media,
    }


def extract_transfer1_warmup_frame(
    source: Path,
    target: Path,
    *,
    frame_index: int = TRANSFER1_WARMUP_FRAME_INDEX,
) -> Path:
    """Extract one native frame for a declared traffic-boundary alignment."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    frame_index = int(frame_index)
    if not 0 <= frame_index < TRANSFER1_NATIVE_FRAMES:
        raise ValueError(
            f"Transfer1 frame index must be in [0, {TRANSFER1_NATIVE_FRAMES - 1}], "
            f"got {frame_index}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"select=eq(n\\,{frame_index})",
            "-frames:v",
            "1",
            str(target),
        ],
        check=True,
    )
    if not target.is_file() or target.stat().st_size <= 0:
        raise RuntimeError(f"Failed to extract Transfer1 frame {frame_index}")
    return target


def create_transfer1_seed_preview(source: Path, target: Path) -> Path:
    """Keep the complete native Transfer1 output as the inspectable seed preview."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vf",
            (
                f"fps={TRANSFER1_NATIVE_FPS},"
                f"trim=end_frame={TRANSFER1_NATIVE_FRAMES},setpts=PTS-STARTPTS"
            ),
            "-an",
            "-r",
            str(TRANSFER1_NATIVE_FPS),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
    )
    media = probe_video(target)
    if (
        int(media["frames"]) != TRANSFER1_NATIVE_FRAMES
        or abs(float(media["fps"]) - TRANSFER1_NATIVE_FPS) > 0.02
    ):
        raise RuntimeError(
            f"Transfer1 seed preview must contain {TRANSFER1_NATIVE_FRAMES} frames "
            f"at {TRANSFER1_NATIVE_FPS} fps"
        )
    return target


def run_transfer1_seed(
    source_control: Path,
    work_dir: Path,
    *,
    output_name: str,
    prompt: str,
    negative_prompt: str,
    num_steps: int,
    seed: int,
    cancelled: Callable[[], bool] | None = None,
) -> dict:
    """Run one official Sample-AV HDMap job and return its validated artifact."""
    root = Path(
        os.environ.get("COSMOS_TRANSFER1_ROOT", "/mnt/rk/cosmos/Cosmos-Drive-Dreams")
    ).expanduser().resolve()
    launcher = root / "run_sample_av.sh"
    if not launcher.is_file():
        raise FileNotFoundError(f"Transfer1 launcher not found: {launcher}")
    gpu_list = [
        item.strip()
        for item in os.environ.get("COSMOS_TRANSFER1_GPUS", "4,5,6,7").split(",")
        if item.strip()
    ]
    if not gpu_list:
        raise ValueError("COSMOS_TRANSFER1_GPUS must contain at least one GPU")

    work_dir = Path(work_dir).resolve()
    output_dir = work_dir / "transfer_raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared_control = work_dir / "front_wide_hdmap_121f_24fps.mp4"
    control_contract = prepare_transfer1_hdmap_control(source_control, prepared_control)
    spec_path = work_dir / "transfer1_hdmap_spec.json"
    spec_path.write_text(
        json.dumps(
            {"hdmap": {"control_weight": 1.0, "input_control": str(prepared_control)}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    log_path = work_dir / "transfer1.log"
    timeout_seconds = max(
        300.0, float(os.environ.get("COSMOS_TRANSFER1_TIMEOUT_SECONDS", "7200"))
    )
    guidance = float(os.environ.get("COSMOS_TRANSFER1_GUIDANCE", "5"))
    command = [
        str(launcher),
        str(spec_path),
        str(output_dir),
        output_name,
        prompt,
        "--negative_prompt",
        negative_prompt,
        "--sigma_max",
        "80",
        "--num_steps",
        str(max(1, int(num_steps))),
        "--guidance",
        str(guidance),
        "--seed",
        str(int(seed)),
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": ",".join(gpu_list),
            "NUM_GPUS": str(len(gpu_list)),
            "MASTER_PORT": str(_free_port()),
            "PYTHONUNBUFFERED": "1",
        }
    )

    started = time.perf_counter()
    output_video = output_dir / f"{output_name}.mp4"
    cache_enabled = os.environ.get("COSMOS_TRANSFER1_CACHE_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
    cache_key, cache_identity = _transfer1_cache_identity(
        root=root,
        prepared_control=prepared_control,
        prompt=prompt,
        negative_prompt=negative_prompt,
        num_steps=num_steps,
        guidance=guidance,
        seed=seed,
        gpu_count=len(gpu_list),
    )
    repository_root = Path(__file__).resolve().parents[2]
    cache_root = Path(
        os.environ.get(
            "COSMOS_TRANSFER1_CACHE_DIR",
            str(repository_root / "output" / "cosmos" / "cache" / "transfer1_seed"),
        )
    ).expanduser().resolve()
    cache_video = cache_root / f"{cache_key}.mp4"
    cache_manifest = cache_root / f"{cache_key}.json"
    cache_hit = False
    with _TRANSFER1_LOCK, log_path.open("w", encoding="utf-8") as log_stream:
        if cancelled is not None and cancelled():
            raise RuntimeError("Transfer1 seed generation was cancelled")
        if cache_enabled and cache_video.is_file() and cache_manifest.is_file():
            try:
                cached_identity = json.loads(cache_manifest.read_text(encoding="utf-8"))
                cached_media = probe_video(cache_video)
                cache_hit = (
                    cached_identity == cache_identity
                    and int(cached_media["frames"]) == TRANSFER1_NATIVE_FRAMES
                    and abs(float(cached_media["fps"]) - TRANSFER1_NATIVE_FPS) <= 0.02
                )
            except (OSError, TypeError, ValueError):
                cache_hit = False
        if cache_hit:
            shutil.copy2(cache_video, output_video)
            (output_dir / f"{output_name}.txt").write_text(prompt, encoding="utf-8")
            log_stream.write(f"Transfer1 exact-input cache hit: {cache_key}\n")
            return_code = 0
        else:
            process = subprocess.Popen(
                command,
                cwd=root,
                env=environment,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if cancelled is not None and cancelled():
                    _terminate_process_group(process)
                    raise RuntimeError("Transfer1 seed generation was cancelled")
                if time.monotonic() >= deadline:
                    _terminate_process_group(process)
                    raise TimeoutError(
                        f"Transfer1 seed generation exceeded {timeout_seconds:g} seconds"
                    )
                time.sleep(1.0)
            return_code = int(process.returncode or 0)
        if return_code == 0 and cache_enabled and not cache_hit:
            generated_media = probe_video(output_video)
            if (
                int(generated_media["frames"]) == TRANSFER1_NATIVE_FRAMES
                and abs(float(generated_media["fps"]) - TRANSFER1_NATIVE_FPS) <= 0.02
            ):
                cache_root.mkdir(parents=True, exist_ok=True)
                temporary_video = cache_video.with_suffix(f".tmp-{os.getpid()}.mp4")
                temporary_manifest = cache_manifest.with_suffix(f".tmp-{os.getpid()}.json")
                shutil.copy2(output_video, temporary_video)
                temporary_manifest.write_text(
                    json.dumps(cache_identity, ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8",
                )
                temporary_video.replace(cache_video)
                temporary_manifest.replace(cache_manifest)

    generation_seconds = time.perf_counter() - started
    if return_code != 0:
        raise RuntimeError(
            f"Transfer1 seed generation exited with code {return_code}: {_tail(log_path)}"
        )
    media = probe_video(output_video)
    if int(media["frames"]) != TRANSFER1_NATIVE_FRAMES:
        raise RuntimeError(
            f"Transfer1 output has {int(media['frames'])} frames; "
            f"expected {TRANSFER1_NATIVE_FRAMES}"
        )
    if abs(float(media["fps"]) - TRANSFER1_NATIVE_FPS) > 0.02:
        raise RuntimeError(
            f"Transfer1 output FPS is {float(media['fps']):g}; "
            f"expected {TRANSFER1_NATIVE_FPS}"
        )
    return {
        "id": output_name,
        "run_state": "completed",
        "backend": "cosmos-transfer1-7b-sample-av",
        "generation_seconds": generation_seconds,
        "cache_hit": cache_hit,
        "cache_key": cache_key,
        "gpus": gpu_list,
        "num_steps": max(1, int(num_steps)),
        "seed": int(seed),
        "spec_path": str(spec_path),
        "prepared_control": str(prepared_control),
        "control_contract": control_contract,
        "output_video": str(output_video),
        "output_contract": media,
        "log_path": str(log_path),
    }
