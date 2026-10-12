#!/usr/bin/env python3
"""CARLA 0.9.16 visualization gateway for TrafficWM scene generation."""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

try:
    import carla
except ImportError as exc:  # pragma: no cover - reported through the status API
    carla = None
    CARLA_IMPORT_ERROR = str(exc)
else:
    CARLA_IMPORT_ERROR = ""


def _json_request(url: str, *, timeout: float = 2.5) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class CarlaGateway:
    def __init__(
        self,
        *,
        root: Path,
        host: str,
        port: int,
        carla_host: str,
        carla_port: int,
        carla_root: Path,
    ) -> None:
        self.root = root.resolve()
        self.host = host
        self.port = int(port)
        self.carla_host = carla_host
        self.carla_port = int(carla_port)
        self.carla_root = carla_root.resolve()
        self._lock = threading.RLock()
        self._frame_cv = threading.Condition(self._lock)
        self._frame: bytes | None = None
        self._frame_number = 0
        self._raw_frames: queue.Queue[tuple[int, int, bytes]] = queue.Queue(maxsize=1)
        self._encoder_stop = threading.Event()
        self._session_stop = threading.Event()
        self._session_thread: threading.Thread | None = None
        self._session_serial = 0
        self._carla_process: subprocess.Popen | None = None
        self._carla_process_group = 0
        self._carla_log = None
        self._world = None
        self._loaded_scene = ""
        self._environment_actors: list[Any] = []
        self._dynamic_actors: dict[str, Any] = {}
        self._last_vehicles: list[dict[str, Any]] = []
        self._camera = None
        self._camera_target = ""
        self._focus_vehicle_id = ""
        self._state: dict[str, Any] = {
            "ok": True,
            "gateway": True,
            "carla_version": "0.9.16",
            "state": "idle",
            "message": "CARLA gateway is ready",
            "carla_connected": False,
            "experiment_id": "",
            "focused_vehicle_id": "",
            "actors": 0,
            "frame_number": 0,
        }
        self._encoder_thread = threading.Thread(target=self._encode_frames, name="CARLAFrameEncoder", daemon=True)
        self._encoder_thread.start()

    def _update_state(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)
            self._state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["frame_number"] = self._frame_number
            state["focused_vehicle_id"] = self._focus_vehicle_id
            state["actors"] = len(self._dynamic_actors)
            state["carla_process_running"] = self._managed_carla_running()
            return state

    def _managed_carla_running(self) -> bool:
        process_group = self._carla_process_group
        if process_group <= 0:
            return False
        process = self._carla_process
        if process is not None and process.poll() is None:
            return True
        try:
            os.killpg(process_group, 0)
        except OSError:
            return False
        for proc_path in Path("/proc").glob("[0-9]*/stat"):
            try:
                stat = proc_path.read_text(encoding="utf-8")
                fields = stat[stat.rfind(")") + 2 :].split()
                if len(fields) >= 3 and int(fields[2]) == process_group and fields[0] != "Z":
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _stop_managed_carla(self) -> None:
        process_group = self._carla_process_group
        if process_group > 0 and self._managed_carla_running():
            try:
                os.killpg(process_group, signal.SIGTERM)
                deadline = time.monotonic() + 3.0
                while self._managed_carla_running() and time.monotonic() < deadline:
                    time.sleep(0.1)
            except OSError:
                pass
            if self._managed_carla_running():
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except OSError:
                    pass
        process = self._carla_process
        if process is not None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        self._carla_process = None
        self._carla_process_group = 0
        self._world = None
        self._loaded_scene = ""
        self._environment_actors = []
        self._dynamic_actors.clear()
        self._last_vehicles = []
        self._camera = None
        self._camera_target = ""

    def frame(self, experiment_id: str = "") -> bytes | None:
        with self._lock:
            if experiment_id and experiment_id != self._state.get("experiment_id"):
                return None
            return self._frame

    def focus(self, experiment_id: str, vehicle_id: str) -> dict[str, Any]:
        with self._lock:
            active = str(self._state.get("experiment_id") or "")
            if experiment_id and active and experiment_id != active:
                return {"ok": False, "error": f"CARLA session is attached to {active}"}
            self._focus_vehicle_id = str(vehicle_id or "")
            self._state["focused_vehicle_id"] = self._focus_vehicle_id
        return {
            "ok": True,
            "experiment_id": active,
            "focused_vehicle_id": self._focus_vehicle_id,
        }

    def start_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = str(payload.get("experiment_id") or "").strip()
        state_url = str(payload.get("state_url") or "").strip()
        status_url = str(payload.get("status_url") or "").strip()
        if not experiment_id or not state_url:
            return {"ok": False, "error": "experiment_id and state_url are required"}
        self.stop_session(wait=True)
        with self._lock:
            self._session_serial += 1
            serial = self._session_serial
            self._session_stop = threading.Event()
            self._focus_vehicle_id = ""
            self._frame = None
            self._frame_number = 0
            self._last_vehicles = []
            self._state.update(
                {
                    "ok": True,
                    "state": "starting",
                    "message": "Connecting to CARLA 0.9.16",
                    "experiment_id": experiment_id,
                    "backend_model": str(payload.get("backend_model") or ""),
                    "map_path": str(payload.get("map_path") or ""),
                    "carla_connected": False,
                    "last_error": "",
                }
            )
        thread = threading.Thread(
            target=self._session_worker,
            args=(serial, dict(payload), state_url, status_url, self._session_stop),
            name=f"CARLASession-{experiment_id}",
            daemon=True,
        )
        self._session_thread = thread
        thread.start()
        return {"ok": True, "state": "starting", "experiment_id": experiment_id}

    def stop_session(self, experiment_id: str = "", *, wait: bool = False) -> dict[str, Any]:
        with self._lock:
            active = str(self._state.get("experiment_id") or "")
            if experiment_id and active and experiment_id != active:
                return {"ok": True, "stopped": False, "experiment_id": active}
            stop_event = self._session_stop
            thread = self._session_thread
            stop_event.set()
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(timeout=8.0)
        return {"ok": True, "stopped": bool(active), "experiment_id": active}

    def _ensure_server(self, payload: dict[str, Any]) -> bool:
        if carla is None:
            self._update_state(state="error", message="CARLA Python API unavailable", last_error=CARLA_IMPORT_ERROR)
            return False
        if self._connect_client(timeout=2.0) is not None:
            return True
        executable = self.carla_root / "CarlaUE4.sh"
        if not executable.is_file():
            self._update_state(
                state="error",
                message="CARLA 0.9.16 is not installed",
                last_error=f"Missing {executable}",
            )
            return False
        with self._lock:
            running = self._managed_carla_running()
        if running:
            self._stop_managed_carla()
            running = False
        if not running:
            quality = str(payload.get("quality") or "Epic").strip().capitalize()
            if quality not in {"Epic", "Low"}:
                quality = "Epic"
            gpu_id = str(payload.get("carla_gpu_id", "1") or "1")
            log_dir = self.root / "backend" / "bridge" / "data"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "carla_0916.log"
            self._carla_log = open(log_path, "ab", buffering=0)
            command = [
                str(executable),
                "-RenderOffScreen",
                "-nosound",
                f"-quality-level={quality}",
                f"-graphicsadapter={gpu_id}",
                f"-carla-rpc-port={self.carla_port}",
                "-log",
                "-stdout",
                "-FullStdOutLogOutput",
            ]
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = gpu_id
            try:
                self._carla_process = subprocess.Popen(
                    command,
                    cwd=str(self.carla_root),
                    env=env,
                    stdout=self._carla_log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
                self._carla_process_group = self._carla_process.pid
            except OSError as exc:
                self._update_state(state="error", message="Failed to start CARLA", last_error=str(exc))
                return False
            self._update_state(state="starting", message="CARLA process started; waiting for RPC")
        deadline = time.monotonic() + max(15.0, _finite(payload.get("startup_timeout"), 120.0))
        while time.monotonic() < deadline and not self._session_stop.is_set():
            if self._connect_client(timeout=2.0) is not None:
                return True
            if not self._managed_carla_running():
                with self._lock:
                    proc = self._carla_process
                self._update_state(
                    state="error",
                    message="CARLA process exited during startup",
                    last_error=f"exit code {proc.poll() if proc is not None else 'unknown'}",
                )
                return False
            time.sleep(1.0)
        self._update_state(state="error", message="CARLA RPC startup timed out", last_error="RPC is not reachable")
        return False

    def _connect_client(self, timeout: float = 5.0):
        if carla is None:
            return None
        try:
            client = carla.Client(self.carla_host, self.carla_port)
            client.set_timeout(timeout)
            client.get_server_version()
            return client
        except RuntimeError:
            return None

    def _resolve_scene(self, payload: dict[str, Any]) -> Path | None:
        explicit = str(payload.get("carla_scene_path") or "").strip()
        if explicit:
            path = Path(explicit)
            path = path if path.is_absolute() else self.root / path
            if path.is_file():
                return path.resolve()
        map_path = str(payload.get("map_path") or "").lower()
        if "nuplan" in map_path or str(payload.get("backend_model") or "").lower() == "cnde":
            candidate = self.root / "maps" / "nuplan_boston_carla" / "scene.json"
            if candidate.is_file():
                return candidate
        return None

    def _prepare_world(self, client, payload: dict[str, Any], stop_event: threading.Event):
        scene_path = self._resolve_scene(payload)
        scene_key = str(scene_path or "builtin")
        if self._world is not None and self._loaded_scene == scene_key:
            return self._world
        self._destroy_dynamic_actors(client)
        self._environment_actors = []
        self._update_state(state="loading_map", message="Loading CARLA map")
        if scene_path is not None:
            scene = json.loads(scene_path.read_text(encoding="utf-8"))
            xodr_path = scene_path.parent / str(scene.get("xodr") or "")
            if not xodr_path.is_file():
                raise RuntimeError(f"OpenDRIVE file not found: {xodr_path}")
            parameters = carla.OpendriveGenerationParameters(
                vertex_distance=1.5,
                max_road_length=50.0,
                wall_height=0.0,
                additional_width=0.15,
                smooth_junctions=True,
                enable_mesh_visibility=True,
                enable_pedestrian_navigation=False,
            )
            client.set_timeout(180.0)
            world = client.generate_opendrive_world(xodr_path.read_text(encoding="utf-8"), parameters)
            client.set_timeout(8.0)
            self._world = world
            self._loaded_scene = scene_key
            self._spawn_environment(world, scene, stop_event, int(payload.get("environment_limit") or 450))
        else:
            self._world = client.get_world()
            self._loaded_scene = scene_key
        settings = self._world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        settings.no_rendering_mode = False
        self._world.apply_settings(settings)
        self._world.set_weather(carla.WeatherParameters.ClearNoon)
        return self._world

    def _spawn_environment(
        self,
        world,
        scene: dict[str, Any],
        stop_event: threading.Event,
        limit: int,
    ) -> None:
        try:
            blueprint = world.get_blueprint_library().find("static.prop.mesh")
        except RuntimeError:
            self._update_state(message="Map loaded; bundled environment meshes are unavailable")
            return
        specs = list(scene.get("environment") or [])
        if limit > 0 and len(specs) > limit:
            groups = {
                kind: [item for item in specs if str(item.get("kind")) == kind]
                for kind in ("ground", "building", "tree", "grass")
            }
            base = groups["ground"] + groups["building"]
            if len(base) >= limit:
                ground_limit = min(len(groups["ground"]), max(1, round(limit * 0.6)))
                specs = groups["ground"][:ground_limit]
                specs.extend(groups["building"][: max(0, limit - len(specs))])
            else:
                specs = list(base)
                remaining = limit - len(specs)
                tree_limit = min(len(groups["tree"]), round(remaining * 0.7))
                specs.extend(groups["tree"][:tree_limit])
                specs.extend(groups["grass"][: max(0, limit - len(specs))])
            if len(specs) < limit:
                selected_ids = {id(item) for item in specs}
                specs.extend(item for item in scene.get("environment") or [] if id(item) not in selected_ids)
                specs = specs[:limit]
        for idx, spec in enumerate(specs):
            if stop_event.is_set():
                break
            source = spec.get("source_location") or {}
            transform = carla.Transform(
                carla.Location(
                    x=_finite(source.get("x")),
                    y=-_finite(source.get("y")),
                    z=_finite(source.get("z"), 0.05),
                ),
                carla.Rotation(yaw=-_finite(spec.get("yaw"))),
            )
            blueprint.set_attribute("mesh_path", str(spec.get("mesh_path") or ""))
            blueprint.set_attribute("scale", str(_finite(spec.get("scale"), 1.0)))
            blueprint.set_attribute("role_name", f"trafficwm_environment_{idx}")
            try:
                actor = world.try_spawn_actor(blueprint, transform)
            except RuntimeError:
                actor = None
            if actor is not None:
                self._environment_actors.append(actor)
        self._update_state(message=f"Map ready with {len(self._environment_actors)} environment objects")

    def _session_worker(
        self,
        serial: int,
        payload: dict[str, Any],
        state_url: str,
        status_url: str,
        stop_event: threading.Event,
    ) -> None:
        client = None
        retry_payload: dict[str, Any] | None = None
        server_failed = False
        try:
            if not self._ensure_server(payload):
                return
            client = self._connect_client(timeout=8.0)
            if client is None:
                raise RuntimeError("CARLA RPC is not reachable")
            world = self._prepare_world(client, payload, stop_event)
            self._update_state(
                state="running",
                message="CARLA visualization connected",
                carla_connected=True,
                server_version=client.get_server_version(),
                client_version=client.get_client_version(),
            )
            version = -1
            last_status_poll = 0.0
            target_fps = max(5.0, min(30.0, _finite(payload.get("render_fps"), 15.0)))
            frame_interval = 1.0 / target_fps
            next_tick = time.monotonic()
            self._update_state(render_fps_limit=target_fps)
            while not stop_event.is_set() and serial == self._session_serial:
                separator = "&" if "?" in state_url else "?"
                state = _json_request(f"{state_url}{separator}after={version}&wait_ms=0", timeout=0.5)
                changed = bool(state and state.get("ok") and not state.get("unchanged"))
                if changed:
                    version = int(state.get("frame_version", version + 1))
                    vehicles = state.get("vehicles") if isinstance(state.get("vehicles"), list) else []
                    self._last_vehicles = vehicles
                    self._sync_actors(client, world, vehicles)
                    self._update_state(
                        state="running",
                        message="CARLA visualization connected",
                        source_frame=version,
                        source_step=state.get("step"),
                        source_sim_time=state.get("sim_time"),
                    )
                self._ensure_camera(world, self._last_vehicles)
                world.tick()
                now = time.monotonic()
                next_tick = max(next_tick + frame_interval, now)
                if status_url and now - last_status_poll >= 1.0:
                    last_status_poll = now
                    status = _json_request(status_url, timeout=0.8)
                    if status and str(status.get("run_state") or "") == "error":
                        self._update_state(state="error", message="Scene generation failed", last_error=status.get("last_error", ""))
                    elif status and str(status.get("run_state") or "") == "completed":
                        self._update_state(state="completed", message="Scene generation completed")
                stop_event.wait(max(0.0, next_tick - time.monotonic()))
        except Exception as exc:
            server_failed = True
            recovery_count = int(payload.get("_recovery_count") or 0)
            self._stop_managed_carla()
            if (
                recovery_count < 2
                and not stop_event.is_set()
                and serial == self._session_serial
            ):
                retry_payload = {**payload, "_recovery_count": recovery_count + 1}
                self._update_state(
                    state="recovering",
                    message=f"CARLA crashed; restarting ({recovery_count + 1}/2)",
                    last_error=str(exc),
                    carla_connected=False,
                )
            else:
                self._update_state(
                    state="error",
                    message="CARLA integration failed",
                    last_error=str(exc),
                    carla_connected=False,
                )
        finally:
            if client is not None and not server_failed:
                self._destroy_dynamic_actors(client)
            with self._lock:
                if (
                    retry_payload is None
                    and serial == self._session_serial
                    and self._state.get("state") not in {"error", "completed"}
                ):
                    self._state.update(
                        {
                            "state": "stopped",
                            "message": "CARLA visualization stopped",
                            "carla_connected": False,
                        }
                    )
        if retry_payload is not None and not stop_event.wait(2.0):
            self._session_worker(serial, retry_payload, state_url, status_url, stop_event)

    def _actor_blueprint(self, world, vehicle: dict[str, Any]):
        library = world.get_blueprint_library()
        actor_type = str(vehicle.get("type") or vehicle.get("agent_type") or "vehicle").lower()
        cartype = str(vehicle.get("cartype") or vehicle.get("vehicle_type") or "").lower()
        if any(token in actor_type or token in cartype for token in ("pedestrian", "walker", "person")):
            choices = list(library.filter("walker.pedestrian.*"))
        elif any(token in actor_type or token in cartype for token in ("bike", "bicycle", "cyclist")):
            choices = list(library.filter("vehicle.*crossbike*")) or list(library.filter("vehicle.*"))
        elif any(token in actor_type or token in cartype for token in ("motor", "scooter")):
            choices = list(library.filter("vehicle.*motorcycle*")) or list(library.filter("vehicle.*"))
        else:
            choices = [
                bp
                for bp in library.filter("vehicle.*")
                if not bp.has_attribute("number_of_wheels")
                or int(bp.get_attribute("number_of_wheels").as_int()) == 4
            ]
        if not choices:
            raise RuntimeError(f"No CARLA blueprint for actor type {actor_type}")
        actor_id = str(vehicle.get("id") or "")
        blueprint = choices[abs(hash((actor_id, cartype))) % len(choices)]
        if blueprint.has_attribute("role_name"):
            blueprint.set_attribute("role_name", f"trafficwm:{actor_id}")
        if blueprint.has_attribute("color"):
            colors = blueprint.get_attribute("color").recommended_values
            if colors:
                blueprint.set_attribute("color", colors[abs(hash(actor_id)) % len(colors)])
        return blueprint

    @staticmethod
    def _actor_transform(vehicle: dict[str, Any]):
        heading = _finite(vehicle.get("heading"))
        if abs(heading) > math.tau * 1.5:
            heading = math.radians(heading)
        return carla.Transform(
            carla.Location(
                x=_finite(vehicle.get("x")),
                y=-_finite(vehicle.get("y")),
                z=max(0.25, _finite(vehicle.get("z"), 0.35)),
            ),
            carla.Rotation(yaw=-math.degrees(heading)),
        )

    def _sync_actors(self, client, world, vehicles: list[dict[str, Any]]) -> None:
        incoming = {str(item.get("id")): item for item in vehicles if item.get("id") is not None}
        removed = set(self._dynamic_actors) - set(incoming)
        if removed:
            client.apply_batch([carla.command.DestroyActor(self._dynamic_actors[actor_id].id) for actor_id in removed])
            for actor_id in removed:
                self._dynamic_actors.pop(actor_id, None)
        transform_commands = []
        for actor_id, vehicle in incoming.items():
            actor = self._dynamic_actors.get(actor_id)
            transform = self._actor_transform(vehicle)
            if actor is None or not actor.is_alive:
                try:
                    actor = world.try_spawn_actor(self._actor_blueprint(world, vehicle), transform)
                except RuntimeError:
                    actor = None
                if actor is None:
                    continue
                try:
                    actor.set_simulate_physics(False)
                    actor.set_enable_gravity(False)
                except RuntimeError:
                    pass
                self._dynamic_actors[actor_id] = actor
            else:
                transform_commands.append(carla.command.ApplyTransform(actor.id, transform))
        if transform_commands:
            client.apply_batch(transform_commands)

    def _ensure_camera(self, world, vehicles: list[dict[str, Any]]) -> None:
        requested = self._focus_vehicle_id
        target = self._dynamic_actors.get(requested) if requested else None
        target_key = requested if target is not None and target.is_alive else ""
        if self._camera is not None and self._camera.is_alive and self._camera_target == target_key:
            if not target_key and vehicles:
                xs = [_finite(item.get("x")) for item in vehicles]
                ys = [-_finite(item.get("y")) for item in vehicles]
                transform = carla.Transform(
                    carla.Location(x=float(np.mean(xs)), y=float(np.mean(ys)), z=90.0),
                    carla.Rotation(pitch=-78.0),
                )
                self._camera.set_transform(transform)
            return
        self._destroy_camera()
        library = world.get_blueprint_library()
        blueprint = library.find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", "1280")
        blueprint.set_attribute("image_size_y", "720")
        blueprint.set_attribute("fov", "90")
        blueprint.set_attribute("sensor_tick", "0.04")
        if target_key:
            transform = carla.Transform(carla.Location(x=-8.0, z=4.2), carla.Rotation(pitch=-14.0))
            camera = world.spawn_actor(
                blueprint,
                transform,
                attach_to=target,
                attachment_type=carla.AttachmentType.Rigid,
            )
        else:
            if vehicles:
                cx = float(np.mean([_finite(item.get("x")) for item in vehicles]))
                cy = float(np.mean([-_finite(item.get("y")) for item in vehicles]))
            else:
                cx = cy = 0.0
            transform = carla.Transform(
                carla.Location(x=cx, y=cy, z=90.0),
                carla.Rotation(pitch=-78.0),
            )
            camera = world.spawn_actor(blueprint, transform)
        camera.listen(self._on_camera_frame)
        self._camera = camera
        self._camera_target = target_key
        self._update_state(
            focused_vehicle_id=target_key,
            message=f"Following vehicle {target_key}" if target_key else "CARLA overview camera",
        )

    def _on_camera_frame(self, image) -> None:
        raw = (int(image.width), int(image.height), bytes(image.raw_data))
        try:
            self._raw_frames.put_nowait(raw)
        except queue.Full:
            try:
                self._raw_frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._raw_frames.put_nowait(raw)
            except queue.Full:
                pass

    def _encode_frames(self) -> None:
        while not self._encoder_stop.is_set():
            try:
                width, height, raw = self._raw_frames.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                image = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1).convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=False)
                encoded = output.getvalue()
            except Exception as exc:
                self._update_state(last_error=f"Frame encoding failed: {exc}")
                continue
            with self._frame_cv:
                self._frame = encoded
                self._frame_number += 1
                self._state["frame_number"] = self._frame_number
                self._frame_cv.notify_all()

    def _destroy_camera(self) -> None:
        camera = self._camera
        self._camera = None
        self._camera_target = ""
        if camera is not None:
            try:
                camera.stop()
                camera.destroy()
            except RuntimeError:
                pass

    def _destroy_dynamic_actors(self, client) -> None:
        self._destroy_camera()
        actors = list(self._dynamic_actors.values())
        self._dynamic_actors.clear()
        self._last_vehicles = []
        if actors and client is not None:
            try:
                client.apply_batch([carla.command.DestroyActor(actor.id) for actor in actors if actor.is_alive])
            except RuntimeError:
                pass

    def close(self) -> None:
        self.stop_session(wait=True)
        self._encoder_stop.set()
        self._encoder_thread.join(timeout=2.0)
        self._destroy_camera()
        self._stop_managed_carla()
        if self._carla_log is not None:
            self._carla_log.close()


class GatewayHttpServer:
    def __init__(self, gateway: CarlaGateway) -> None:
        self.gateway = gateway
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _payload(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or "0")
                if length <= 0:
                    return {}
                return json.loads(self.rfile.read(length).decode("utf-8"))

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                route = parsed.path
                query = parse_qs(parsed.query)
                if route in {"/", "/status", "/api/v1/status"}:
                    self._json(outer.gateway.status())
                    return
                if route in {"/frame.jpg", "/api/v1/frame.jpg"}:
                    experiment_id = str((query.get("experiment_id") or [""])[0])
                    frame = outer.gateway.frame(experiment_id)
                    if frame is None:
                        self._json({"ok": False, "error": "CARLA frame is not ready"}, 404)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(frame)
                    return
                self._json({"ok": False, "error": "Not found"}, 404)

            def do_POST(self) -> None:
                route = urlparse(self.path).path
                try:
                    payload = self._payload()
                    if route in {"/session/start", "/api/v1/session/start"}:
                        result = outer.gateway.start_session(payload)
                    elif route in {"/session/stop", "/api/v1/session/stop"}:
                        result = outer.gateway.stop_session(str(payload.get("experiment_id") or ""))
                    elif route in {"/focus", "/api/v1/focus"}:
                        result = outer.gateway.focus(
                            str(payload.get("experiment_id") or ""),
                            str(payload.get("vehicle_id") or ""),
                        )
                    else:
                        self._json({"ok": False, "error": "Not found"}, 404)
                        return
                    self._json(result, 200 if result.get("ok") else 400)
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)}, 500)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((gateway.host, gateway.port), Handler)

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.25)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("CARLA_GATEWAY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CARLA_GATEWAY_PORT", "8892")))
    parser.add_argument("--carla-host", default=os.environ.get("CARLA_HOST", "127.0.0.1"))
    parser.add_argument("--carla-port", type=int, default=int(os.environ.get("CARLA_PORT", "2000")))
    parser.add_argument("--carla-root", default=os.environ.get("CARLA_ROOT", "/data/rk/cnde/CARLA_0.9.16"))
    args = parser.parse_args()
    gateway = CarlaGateway(
        root=root,
        host=args.host,
        port=args.port,
        carla_host=args.carla_host,
        carla_port=args.carla_port,
        carla_root=Path(args.carla_root),
    )
    server = GatewayHttpServer(gateway)
    shutdown_requested = False

    def _request_stop(_signum, _frame) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            return
        shutdown_requested = True
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _request_stop)
    print(f"[CARLAGateway] API http://{args.host}:{args.port}/status", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        gateway.close()


if __name__ == "__main__":
    main()
