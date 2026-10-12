"""Command construction for the NeuralNDE child process."""
from __future__ import annotations

from pathlib import Path


def build_generation_command(
    *,
    python: str,
    script: Path,
    neuralnde_root: Path,
    dataset: str,
    output_dir: Path,
    experiment_id: str,
    experiment_name: str,
    max_sim_time: float,
    host: str,
    port: int,
    gui_dir: Path | None = None,
    gpu_id: str = "",
    seed: int = 42,
    realtime: bool = True,
    av_enabled: bool = False,
    av_selection_mode: str = "random",
    av_control_model: str = "DEFAULT_TCP",
    av_command_mode: str = "state",
    av_control_host: str = "127.0.0.1",
    av_control_port: int = 0,
    av_control_timeout: float = 0.04,
    av_rgb_uri: str = "",
    denseworld_warmup: bool = False,
    warmup_seconds: float = 1.0,
    world_sync_state: str = "",
    world_video_duration: float = 0.0,
    run_until_stopped: bool = False,
) -> list[str]:
    cmd = [
        python,
        str(script),
        "--neuralnde_root",
        str(neuralnde_root),
        "--dataset",
        str(dataset),
        "--output_dir",
        str(output_dir),
        "--experiment_id",
        str(experiment_id),
        "--experiment_name",
        str(experiment_name),
        "--max_sim_time",
        str(float(max_sim_time)),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--seed",
        str(int(seed)),
        "--world_video_duration",
        str(max(0.0, float(world_video_duration))),
    ]
    if gui_dir is not None and gui_dir.is_dir():
        cmd.extend(["--gui_dir", str(gui_dir)])
    if gpu_id:
        cmd.extend(["--gpu_id", str(gpu_id)])
    if realtime:
        cmd.append("--realtime")
    if denseworld_warmup:
        cmd.extend(["--denseworld_warmup", "--warmup_seconds", str(float(warmup_seconds))])
    if world_sync_state:
        cmd.extend(["--world_sync_state", str(world_sync_state)])
    if run_until_stopped:
        cmd.append("--run_until_stopped")
    if av_enabled:
        cmd.extend(
            [
                "--av_enabled",
                "--av_selection_mode",
                str(av_selection_mode),
                "--av_control_model",
                str(av_control_model),
                "--av_command_mode",
                str(av_command_mode),
                "--av_control_host",
                str(av_control_host),
                "--av_control_timeout",
                str(float(av_control_timeout)),
            ]
        )
        if int(av_control_port or 0) > 0:
            cmd.extend(["--av_control_port", str(int(av_control_port))])
        if av_rgb_uri:
            cmd.extend(["--av_rgb_uri", str(av_rgb_uri)])
    return cmd
