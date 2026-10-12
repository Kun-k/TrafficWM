"""CityNDE adapter command helpers for the platform manager."""
from __future__ import annotations

import json
from pathlib import Path


def build_generation_command(
    *,
    python: str,
    script: Path,
    citynde_root: Path,
    map_path: str,
    init_mode: str,
    total_step: int,
    max_sim_time: float,
    save_file: Path,
    experiment_name: str,
    save_interval: int,
    host: str,
    port: int,
    seed: int = 42,
    gui_dir: Path | None = None,
    init_file: str = "",
    gpu_id: str = "",
    arrival_rate=None,
    arrival_rates: dict | None = None,
    av_enabled: bool = False,
    av_selection_mode: str = "random",
    av_control_model: str = "DEFAULT_TCP",
    av_command_mode: str = "state",
    av_control_host: str = "127.0.0.1",
    av_control_port: int = 0,
    av_control_timeout: float = 1.0,
    av_rgb_uri: str = "",
    denseworld_warmup: bool = False,
    warmup_seconds: float = 1.0,
    denseworld_existing_seed: bool = False,
    world_seed_ego_id: str = "",
    mixed_traffic_enabled: bool = True,
    cyclist_ratio: float = 0.08,
    pedestrians_per_crosswalk: int = 2,
    max_pedestrians: int = 32,
    vehicle_size_mode: str = "mixed",
    initial_speed_mode: str = "citynde",
    world_anchor_catalog: str = "",
    world_sync_state: str = "",
    run_until_stopped: bool = False,
    signalize_unsignalized_map: bool = False,
    world_loop_ego: bool = False,
    world_ego_speed_cap_mps: float = 0.0,
    world_context_mode: str = "auto",
    world_local_target_count: int = 0,
    world_initial_vehicle_limit: int = 0,
    world_spawn_visibility_guard_m: float = 100.0,
    control_step: int = 5,
    inference_precision: str = "fp32",
    traffic_controller: str = "citynde",
    rule_desired_speed_mps: float = 10.0,
) -> list[str]:
    cmd = [
        python,
        str(script),
        "--mode",
        "generate",
        "--citynde_root",
        str(citynde_root),
        "--map_path",
        map_path,
        "--init_mode",
        init_mode,
        "--total_step",
        str(int(total_step)),
        "--max_sim_time",
        str(float(max_sim_time or 0.0)),
        "--save_file",
        str(save_file),
        "--experiment_name",
        experiment_name,
        "--save_interval",
        str(int(save_interval)),
        "--host",
        host,
        "--port",
        str(int(port)),
        "--seed",
        str(int(seed)),
        "--cyclist_ratio",
        str(float(cyclist_ratio)),
        "--pedestrians_per_crosswalk",
        str(int(pedestrians_per_crosswalk)),
        "--max_pedestrians",
        str(int(max_pedestrians)),
        "--vehicle_size_mode",
        "passenger_only" if str(vehicle_size_mode) == "passenger_only" else "mixed",
        "--initial_speed_mode",
        "urban_sampled" if str(initial_speed_mode) == "urban_sampled" else "citynde",
        "--world_context_mode",
        str(world_context_mode or "auto"),
        "--control_step",
        str(max(1, min(20, int(control_step or 5)))),
        "--inference_precision",
        str(inference_precision or "fp32").lower(),
        "--traffic_controller",
        "idm_mobil" if str(traffic_controller).lower() == "idm_mobil" else "citynde",
        "--rule_desired_speed_mps",
        str(max(1.0, min(35.0, float(rule_desired_speed_mps or 10.0)))),
    ]
    if not mixed_traffic_enabled:
        cmd.append("--disable_mixed_traffic")
    if signalize_unsignalized_map:
        cmd.append("--signalize_unsignalized_map")
    if arrival_rate is not None:
        cmd.extend(["--arrival_rate", str(arrival_rate)])
    if arrival_rates:
        cmd.extend(["--lane_arrival_rates", json.dumps(arrival_rates)])
    if gui_dir is not None and gui_dir.is_dir():
        cmd.extend(["--gui_dir", str(gui_dir)])
    if init_file:
        cmd.extend(["--init_file", init_file])
    if gpu_id:
        cmd.extend(["--gpu_id", gpu_id])
    if av_enabled:
        cmd.append("--av_enabled")
        cmd.extend(["--av_selection_mode", av_selection_mode])
        cmd.extend(["--av_control_model", av_control_model])
        cmd.extend(["--av_command_mode", av_command_mode])
        cmd.extend(["--av_control_host", av_control_host])
        cmd.extend(["--av_control_timeout", str(float(av_control_timeout))])
        if av_rgb_uri:
            cmd.extend(["--av_rgb_uri", str(av_rgb_uri)])
        if int(av_control_port or 0) > 0:
            cmd.extend(["--av_control_port", str(int(av_control_port))])
    if denseworld_warmup:
        cmd.append("--denseworld_warmup")
        cmd.extend(["--warmup_seconds", str(float(warmup_seconds))])
        if denseworld_existing_seed:
            cmd.append("--denseworld_existing_seed")
        if str(world_seed_ego_id).strip():
            cmd.extend(["--world_seed_ego_id", str(world_seed_ego_id).strip()])
        if world_anchor_catalog:
            cmd.extend(["--world_anchor_catalog", str(world_anchor_catalog)])
        if world_sync_state:
            cmd.extend(["--world_sync_state", str(world_sync_state)])
    if run_until_stopped:
        cmd.append("--run_until_stopped")
    if world_loop_ego:
        cmd.append("--world_loop_ego")
    if float(world_ego_speed_cap_mps or 0.0) > 0.0:
        cmd.extend(
            ["--world_ego_speed_cap_mps", str(float(world_ego_speed_cap_mps))]
        )
    if int(world_local_target_count or 0) > 0:
        cmd.extend(["--world_local_target_count", str(int(world_local_target_count))])
    if int(world_initial_vehicle_limit or 0) > 0:
        cmd.extend(["--world_initial_vehicle_limit", str(int(world_initial_vehicle_limit))])
    cmd.extend(
        [
            "--world_spawn_visibility_guard_m",
            str(max(0.0, float(world_spawn_visibility_guard_m or 0.0))),
        ]
    )
    return cmd


def build_replay_command(
    *,
    python: str,
    script: Path,
    citynde_root: Path,
    scenario: str,
    experiment_name: str,
    host: str,
    port: int,
    map_path: str = "",
    gui_dir: Path | None = None,
    gpu_id: str = "",
    denseworld_warmup: bool = False,
    seed_init_file: str = "",
    world_seed_ego_id: str = "",
    world_sync_state: str = "",
    max_sim_time: float = 0.0,
) -> list[str]:
    cmd = [
        python,
        str(script),
        "--mode",
        "replay",
        "--citynde_root",
        str(citynde_root),
        "--scenario",
        scenario,
        "--experiment_name",
        experiment_name,
        "--host",
        host,
        "--port",
        str(int(port)),
    ]
    if map_path:
        cmd.extend(["--map_path", map_path])
    if gui_dir is not None and gui_dir.is_dir():
        cmd.extend(["--gui_dir", str(gui_dir)])
    if gpu_id:
        cmd.extend(["--gpu_id", gpu_id])
    if float(max_sim_time or 0.0) > 0.0:
        cmd.extend(["--max_sim_time", str(float(max_sim_time))])
    if denseworld_warmup:
        cmd.extend(["--denseworld_warmup", "--denseworld_existing_seed"])
        if seed_init_file:
            cmd.extend(["--init_file", seed_init_file])
        if world_seed_ego_id:
            cmd.extend(["--world_seed_ego_id", world_seed_ego_id])
        if world_sync_state:
            cmd.extend(["--world_sync_state", world_sync_state])
    return cmd
