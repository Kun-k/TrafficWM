"""Small HTTP API surface used by platform algorithm adapters.

The class in this file intentionally has no CityNDE or NeuralNDE imports. It
serves the GUI-compatible `/api/v1` contract for one running algorithm process:
status, vector map state, vector scene state, metrics, actions, pause/resume,
and optional static GUI assets.
"""
from __future__ import annotations

import json
import mimetypes
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class _FastThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


class HttpApiViewer:
    def __init__(
        self,
        mode: str,
        host: str = "127.0.0.1",
        port: int = 8890,
        gui_dir: str | None = None,
        manager_mode: bool = False,
        workspace_root: str | None = None,
        **_: object,
    ):
        self.host = str(host or "127.0.0.1")
        self.port = int(port)
        self._gui_dir = Path(gui_dir).resolve() if gui_dir else None
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._manager_mode = bool(manager_mode)

        self._state_lock = threading.Lock()
        self._action_cv = threading.Condition(self._state_lock)
        self._sim_state_cv = threading.Condition(self._state_lock)
        self._action_queue: deque[dict] = deque()
        self._action_event = threading.Event()
        self._action_seq = 0
        self._action_results: dict[int, dict] = {}
        self._pause_flag = False
        self._resume_flag = False
        self._closed = False

        self._maps: list[str] = []
        self._scenarios: list[str] = []
        self._map_state_response: bytes | None = None
        self._map_image_response: bytes | None = None
        self._map_image_content_type = "image/png"
        self._sim_state_response: bytes | None = None
        self._sim_state_version = 0
        self._sim_state_next_version = 0
        self._sim_state_publish_lock = threading.Lock()
        self._sim_state_publish_event = threading.Event()
        self._sim_state_publish_stop = threading.Event()
        self._sim_state_pending: deque[tuple[int, dict]] = deque(maxlen=64)
        self._sim_state_history: deque[tuple[int, bytes]] = deque(maxlen=256)
        self._sim_state_frames_dropped = 0
        self._metrics: dict | None = None
        self._status = {
            "step": 0,
            "vehicles": 0,
            "mode": mode,
            "paused": False,
            "pause_pending": False,
            "last_error": "",
            "last_error_nonce": 0,
            "avg_speed": None,
            "avg_ttc": None,
            "avg_headway": None,
            "collision_count": None,
            "speed_samples": [],
            "ttc_samples": [],
            "headway_samples": [],
            "arrival_rate": 0.0,
            "run_state": "idle",
            "manager_mode": bool(manager_mode),
            "waiting_for_start": False,
            "experiment_completed": False,
            "replay_loading": False,
            "sim_resolution": 0.1,
            "replay_step_seconds": 0.1,
            "total_step": 0,
            "max_sim_time": 0.0,
            "sim_time": 0.0,
            "progress": 0.0,
            "api_version": "v1",
            "schema_version": "status.v1",
        }

        viewer = self

        class Handler(BaseHTTPRequestHandler):
            @staticmethod
            def _api_route(path: str) -> str:
                if path == "/api/v1":
                    return "/"
                if path.startswith("/api/v1/"):
                    return path[len("/api/v1") :] or "/"
                return path

            def _headers(self, content_type: str = "application/json", status: int = 200, length: int = 0):
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

            def _write_json_body(self, body: bytes, status: int = 200):
                self._headers("application/json", status, len(body))
                self.wfile.write(body)

            def _read_json(self) -> dict:
                size = int(self.headers.get("Content-Length", "0") or "0")
                if size <= 0:
                    return {}
                raw = self.rfile.read(size)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _serve_static(self, rel: str) -> bool:
                if viewer._gui_dir is None:
                    return False
                try:
                    target = (viewer._gui_dir / rel).resolve()
                    target.relative_to(viewer._gui_dir)
                except ValueError:
                    return False
                if not target.is_file():
                    return False
                mime, _ = mimetypes.guess_type(str(target))
                data = target.read_bytes()
                self._headers(mime or "application/octet-stream", 200, len(data))
                self.wfile.write(data)
                return True

            def do_OPTIONS(self):
                self._headers("text/plain", 204, 0)

            def do_GET(self):
                try:
                    parsed = urlparse(self.path)
                    route = self._api_route(parsed.path)
                    query = parse_qs(parsed.query)

                    if route in ("/", "/index.html"):
                        if self._serve_static("index.html"):
                            return
                        self._write_json({"ok": False, "error": "GUI directory is not configured"}, 503)
                        return

                    if route == "/status":
                        with viewer._state_lock:
                            payload = dict(viewer._status)
                        self._write_json(payload)
                        return

                    if route == "/map_state":
                        with viewer._state_lock:
                            body = viewer._map_state_response
                        if body is None:
                            self._write_json({"ok": False, "error": "Map state is not ready"}, 404)
                        else:
                            self._write_json_body(body)
                        return

                    if route == "/map.jpg":
                        with viewer._state_lock:
                            body = viewer._map_image_response
                            content_type = viewer._map_image_content_type
                        if body is None:
                            self._write_json({"ok": False, "error": "Map image is not ready"}, 404)
                        else:
                            self._headers(content_type, 200, len(body))
                            self.wfile.write(body)
                        return

                    if route == "/sim_state":
                        body = viewer.sim_state_response(query)
                        if body is None:
                            self._write_json({"ok": False, "error": "Simulation state is not ready"}, 404)
                        else:
                            self._write_json_body(body)
                        return

                    if route == "/metrics":
                        payload = viewer.metrics_payload(query)
                        self._write_json(payload, 200 if payload.get("ok") else 404)
                        return

                    if route == "/maps":
                        with viewer._state_lock:
                            maps = list(viewer._maps)
                        self._write_json({"ok": True, "maps": maps})
                        return

                    if route == "/scenarios":
                        with viewer._state_lock:
                            scenarios = list(viewer._scenarios)
                        self._write_json({"ok": True, "scenarios": scenarios})
                        return

                    if route == "/experiments":
                        with viewer._state_lock:
                            status = dict(viewer._status)
                        record = {
                            "id": str(status.get("experiment_id") or "current"),
                            "kind": "replay" if str(status.get("run_state")) in {"playback", "playback_loading"} else "experiment",
                            "name": str(status.get("experiment_name") or "current"),
                            "run_state": str(status.get("run_state") or "idle"),
                            "paused": bool(status.get("paused", False)),
                            "step": int(status.get("step", 0) or 0),
                            "vehicles": int(status.get("vehicles", 0) or 0),
                            "progress": float(status.get("progress", 0.0) or 0.0),
                            "total_step": int(status.get("total_step", 0) or 0),
                            "save_file": str(status.get("save_file", "")),
                            "scenario": str(status.get("scenario", "")),
                            "port": viewer.port,
                        }
                        self._write_json({"ok": True, "experiments": [] if record["run_state"] == "idle" else [record]})
                        return

                    if route == "/capabilities":
                        self._write_json(viewer.capabilities_payload())
                        return

                    if route == "/frame.jpg":
                        self._headers("text/plain", 204, 0)
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
                    if route == "/pause":
                        with viewer._state_lock:
                            viewer._pause_flag = True
                            viewer._resume_flag = False
                            viewer._status["pause_pending"] = True
                        viewer._action_event.set()
                        self._write_json({"ok": True, "message": "Pause requested"})
                        return
                    if route == "/resume":
                        with viewer._state_lock:
                            viewer._pause_flag = False
                            viewer._resume_flag = True
                            viewer._status["pause_pending"] = False
                        viewer._action_event.set()
                        self._write_json({"ok": True, "message": "Resume requested"})
                        return
                    if route == "/action":
                        payload = self._read_json()
                        with viewer._action_cv:
                            viewer._action_seq += 1
                            sync_id = viewer._action_seq
                            payload["_sync_id"] = sync_id
                            act_type = str(payload.get("type", "")).strip().lower()
                            if act_type == "terminate_experiment":
                                viewer._action_queue.appendleft(payload)
                            else:
                                viewer._action_queue.append(payload)
                            viewer._action_event.set()
                            viewer._action_cv.notify_all()
                            deadline = time.time() + 4.0
                            result = None
                            while time.time() < deadline:
                                result = viewer._action_results.pop(sync_id, None)
                                if result is not None:
                                    break
                                viewer._action_cv.wait(timeout=max(0.0, deadline - time.time()))
                        self._write_json(result or {"ok": True, "message": "Request accepted"})
                        return
                    self._headers("text/plain", 404, 0)
                except BrokenPipeError:
                    return
                except Exception as exc:
                    self._write_json({"ok": False, "error": str(exc)}, 500)

            def log_message(self, format, *args):
                pass

        self._server = _FastThreadingHTTPServer((self.host, self.port), Handler)
        self._sim_state_publish_thread = threading.Thread(
            target=self._sim_state_publish_worker,
            name=f"sim-state-publisher-{self.port}",
            daemon=True,
        )
        self._sim_state_publish_thread.start()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        display_host = self.host
        if display_host in ("0.0.0.0", "::"):
            display_host = self._guess_lan_ip()
        print(f"[HttpApiViewer] {mode} API: http://127.0.0.1:{self.port} / LAN http://{display_host}:{self.port}")

    @staticmethod
    def _guess_lan_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    def update(self, frame, step: int, vehicle_count: int, mode: str, paused: bool, extra_status: dict | None = None):
        with self._state_lock:
            sim_resolution = float(self._status.get("sim_resolution", 0.1) or 0.1)
            total_step = int(self._status.get("total_step", 0) or 0)
            progress = float(step) / float(total_step) if total_step > 0 else float(self._status.get("progress", 0.0) or 0.0)
            self._status.update(
                {
                    "step": int(step),
                    "vehicles": int(vehicle_count),
                    "mode": str(mode),
                    "paused": bool(paused),
                    "sim_time": float(step) * sim_resolution,
                    "progress": max(0.0, min(1.0, progress)),
                }
            )
            if total_step > 0 and int(step) >= total_step and self._status.get("run_state") == "running":
                self._status.update({"run_state": "completed", "experiment_completed": True, "progress": 1.0})
            if extra_status:
                self._status.update(extra_status)

    def set_maps(self, maps: list[str]):
        with self._state_lock:
            self._maps = list(maps)

    def set_scenarios(self, scenarios: list[str]):
        with self._state_lock:
            self._scenarios = list(scenarios)

    def set_replay_metrics(self, metrics: dict):
        with self._state_lock:
            self._metrics = dict(metrics)

    def set_map_state(self, state: dict):
        payload = {"ok": True, "api_version": "v1", "schema_version": "map_state.v1", **dict(state)}
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._state_lock:
            self._map_state_response = body

    def set_map_image(self, image: bytes | str | Path, content_type: str = "image/png"):
        data = Path(image).read_bytes() if isinstance(image, (str, Path)) else bytes(image)
        with self._state_lock:
            self._map_image_response = data
            self._map_image_content_type = str(content_type or "image/png")

    def set_sim_state(self, state: dict):
        with self._sim_state_publish_lock:
            self._sim_state_next_version += 1
            version = self._sim_state_next_version
        payload = {
            "ok": True,
            "api_version": "v1",
            "schema_version": "scene_state.v1",
            "frame_version": version,
            **dict(state),
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._sim_state_cv:
            self._sim_state_response = body
            self._sim_state_version = version
            self._sim_state_history.append((version, body))
            self._status["sim_state_version"] = version
            self._sim_state_cv.notify_all()

    def set_sim_state_latest(self, state: dict):
        """Queue an immutable scene snapshot without blocking the simulation thread."""
        with self._sim_state_publish_lock:
            self._sim_state_next_version += 1
            version = self._sim_state_next_version
            if len(self._sim_state_pending) == self._sim_state_pending.maxlen:
                self._sim_state_frames_dropped += 1
            self._sim_state_pending.append((version, dict(state)))
        self._sim_state_publish_event.set()

    def _sim_state_publish_worker(self):
        while not self._sim_state_publish_stop.is_set():
            self._sim_state_publish_event.wait(timeout=0.5)
            if self._sim_state_publish_stop.is_set():
                break
            with self._sim_state_publish_lock:
                pending = list(self._sim_state_pending)
                self._sim_state_pending.clear()
                self._sim_state_publish_event.clear()
            if not pending:
                continue
            with self._sim_state_cv:
                for version, state in pending:
                    payload = {
                        "ok": True,
                        "api_version": "v1",
                        "schema_version": "scene_state.v1",
                        "frame_version": version,
                        **state,
                    }
                    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    self._sim_state_response = body
                    self._sim_state_version = version
                    self._sim_state_history.append((version, body))
                self._status["sim_state_version"] = self._sim_state_version
                self._status["sim_state_frames_dropped"] = self._sim_state_frames_dropped
                self._sim_state_cv.notify_all()

    def sim_state_response(self, query: dict | None = None) -> bytes | None:
        query = query or {}
        try:
            after = int(float((query.get("after") or ["-1"])[0]))
        except (TypeError, ValueError):
            after = -1
        try:
            wait_ms = max(0, min(2000, int(float((query.get("wait_ms") or ["0"])[0]))))
        except (TypeError, ValueError):
            wait_ms = 0
        delivery = str((query.get("delivery") or ["latest"])[0]).strip().lower()

        deadline = time.monotonic() + wait_ms / 1000.0
        with self._sim_state_cv:
            while (
                not self._closed
                and wait_ms > 0
                and (self._sim_state_response is None or self._sim_state_version <= after)
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sim_state_cv.wait(timeout=remaining)
            if self._sim_state_response is None:
                return None
            if self._sim_state_version <= after:
                return json.dumps(
                    {"ok": True, "unchanged": True, "frame_version": self._sim_state_version},
                    separators=(",", ":"),
                ).encode("utf-8")
            if delivery == "next":
                next_body = next(
                    (body for version, body in self._sim_state_history if version > after),
                    None,
                )
                if next_body is not None:
                    return next_body
            return self._sim_state_response

    def set_status_fields(self, fields: dict):
        with self._state_lock:
            self._status.update(fields)

    def status_field(self, key: str, default=None):
        with self._state_lock:
            return self._status.get(key, default)

    @property
    def pause_requested(self) -> bool:
        with self._state_lock:
            if self._pause_flag:
                self._pause_flag = False
                return True
        return False

    @property
    def resume_requested(self) -> bool:
        with self._state_lock:
            if self._resume_flag:
                self._resume_flag = False
                return True
        return False

    def pop_action(self) -> dict | None:
        with self._state_lock:
            if self._action_queue:
                return self._action_queue.popleft()
        return None

    def wait_for_action(self, timeout: float) -> bool:
        ready = self._action_event.wait(timeout=max(0.0, float(timeout)))
        self._action_event.clear()
        return ready

    def set_action_result(self, sync_id: int | None, result: dict):
        if sync_id is None:
            return
        with self._action_cv:
            self._action_results[int(sync_id)] = dict(result)
            self._action_cv.notify_all()

    def set_paused(self, paused: bool):
        with self._state_lock:
            p = bool(paused)
            self._status["paused"] = p
            if p:
                self._status["pause_pending"] = False

    @staticmethod
    def _metrics_total_steps(metrics: dict) -> int:
        total = int(metrics.get("total_steps", 0) or 0)
        for value in metrics.values():
            if isinstance(value, list):
                total = max(total, len(value))
        return total

    def metrics_payload(self, query: dict | None = None) -> dict:
        query = query or {}
        with self._state_lock:
            metrics = dict(self._metrics) if self._metrics is not None else None
        if metrics is None:
            return {"ok": False, "error": "No metrics available"}
        total = self._metrics_total_steps(metrics)
        start_step = None
        try:
            raw_since = (query.get("since") or [""])[0]
            if raw_since != "":
                start_step = max(0, min(total, int(float(raw_since))))
        except (TypeError, ValueError):
            start_step = None
        try:
            raw_tail = (query.get("tail") or [""])[0]
            if start_step is None and raw_tail != "":
                start_step = max(0, total - max(1, int(float(raw_tail))))
        except (TypeError, ValueError):
            start_step = None
        payload = {"ok": True, "api_version": "v1", "schema_version": "metrics.v1", "total_steps": total}
        if start_step is not None:
            payload["start_step"] = start_step
        for key, value in metrics.items():
            payload[key] = value[start_step:] if isinstance(value, list) and start_step is not None else value
        return payload

    def capabilities_payload(self) -> dict:
        return {
            "ok": True,
            "api_version": "v1",
            "schema_version": "capabilities.v1",
            "mode": self._status.get("mode", ""),
            "backend_model": self._status.get("backend_model", ""),
            "manager_mode": bool(self._manager_mode),
            "features": {
                "manager_proxy": False,
                "multi_experiment": False,
                "incremental_metrics": True,
                "latest_state_long_poll": True,
                "static_gui_required": True,
            },
        }

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._sim_state_publish_stop.set()
        self._sim_state_publish_event.set()
        self._action_event.set()
        with self._sim_state_cv:
            self._sim_state_cv.notify_all()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        self._sim_state_publish_thread.join(timeout=2.0)
        print("[HttpApiViewer] Server stopped.")


WebViewer = HttpApiViewer
