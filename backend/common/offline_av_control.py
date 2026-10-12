"""Offline AV control helpers shared by replay adapters."""
from __future__ import annotations

import json
import math
import socketserver
import threading
from dataclasses import dataclass, field
from typing import Any

CONTROL_FIELDS = ("speed", "acceleration", "x", "y", "angle", "heading")
TCP_MODELS = {"EXTERNAL_TCP", "VTD_TCP"}


@dataclass
class OfflineAVCommand:
    frame: int | None = None
    validate_frame: bool = False
    values: dict[str, float] = field(default_factory=dict)

    def valid_for(self, frame: int | None) -> bool:
        if not self.validate_frame:
            return True
        return self.frame is not None and frame is not None and int(self.frame) == int(frame)


def parse_offline_av_command(payload: dict[str, Any]) -> OfflineAVCommand:
    raw_frame = payload.get("frame")
    try:
        frame = int(raw_frame) if raw_frame is not None else None
    except (TypeError, ValueError):
        frame = None
    command = OfflineAVCommand(frame=frame, validate_frame=bool(payload.get("validate_frame", False)))
    controls = payload.get("controls") if isinstance(payload.get("controls"), dict) else {}
    for name in CONTROL_FIELDS:
        enabled = False
        value = None
        item = controls.get(name)
        if isinstance(item, dict):
            enabled = bool(item.get("enabled", item.get("use", False)))
            value = item.get("value")
        elif item is not None:
            enabled = True
            value = item
        flat_flag = payload.get(f"use_{name}")
        if flat_flag is not None:
            enabled = bool(flat_flag)
            value = payload.get(name, value)
        if enabled:
            try:
                command.values[name] = float(value)
            except (TypeError, ValueError):
                continue
    return command


class _CommandState:
    def __init__(self):
        self._lock = threading.Lock()
        self._command = OfflineAVCommand()

    def set(self, command: OfflineAVCommand):
        with self._lock:
            self._command = command

    def get(self) -> OfflineAVCommand:
        with self._lock:
            return OfflineAVCommand(
                frame=self._command.frame,
                validate_frame=self._command.validate_frame,
                values=dict(self._command.values),
            )


class _TCPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        state: _CommandState = self.server.control_state  # type: ignore[attr-defined]
        for raw in self.rfile:
            try:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
                state.set(parse_offline_av_command(payload))
                self.wfile.write(b'{"ok": true}\n')
            except Exception as exc:
                message = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8") + b"\n"
                self.wfile.write(message)


class OfflineAVController:
    """Marks the selected replay vehicle as AV and optionally overrides it via TCP."""

    def __init__(self):
        self.av_id = ""
        self.av_enabled = False
        self.av_model = "DEFAULT_TCP"
        self.host = "127.0.0.1"
        self.port = 0
        self.state = _CommandState()
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def configure(
        self,
        *,
        av_id: str = "",
        av_enabled: bool = False,
        av_model: str = "DEFAULT_TCP",
        host: str = "127.0.0.1",
        port: int | str | None = None,
        start_tcp: bool = True,
    ):
        self.av_id = str(av_id or self.av_id or "")
        self.av_enabled = bool(av_enabled)
        self.av_model = str(av_model or "DEFAULT_TCP").upper()
        self.host = str(host or self.host or "127.0.0.1")
        try:
            next_port = int(port) if port not in (None, "") else int(self.port or 0)
        except (TypeError, ValueError):
            next_port = int(self.port or 0)
        if next_port > 0:
            self.port = next_port
        if self.av_enabled and self.av_model in TCP_MODELS and start_tcp and self.port > 0:
            self.start()
        elif not (self.av_enabled and self.av_model in TCP_MODELS):
            self.close()

    def start(self):
        if self._server is not None:
            return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        server = Server((self.host, int(self.port)), _TCPHandler)
        server.control_state = self.state  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name=f"OfflineAVTCP-{self.port}", daemon=True)
        self._thread.start()

    def close(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None

    def apply(self, vehicles: list[dict[str, Any]], frame: int | None = None) -> list[dict[str, Any]]:
        if not self.av_id:
            return vehicles
        command = self.state.get() if self.av_enabled and self.av_model in TCP_MODELS else OfflineAVCommand()
        can_apply = bool(self.av_enabled and self.av_model in TCP_MODELS and command.valid_for(frame))
        values = command.values if can_apply else {}
        out = []
        for vehicle in vehicles:
            next_vehicle = dict(vehicle)
            if str(next_vehicle.get("id", "")) == str(self.av_id):
                next_vehicle["type"] = "av"
                next_vehicle["is_av"] = True
                next_vehicle["offline_av"] = True
                if values:
                    if "x" in values:
                        next_vehicle["x"] = values["x"]
                    if "y" in values:
                        next_vehicle["y"] = values["y"]
                    if "speed" in values:
                        next_vehicle["speed"] = max(0.0, values["speed"])
                    if "acceleration" in values:
                        next_vehicle["acceleration"] = values["acceleration"]
                    if "heading" in values:
                        next_vehicle["heading"] = values["heading"]
                    elif "angle" in values:
                        next_vehicle["heading"] = math.radians(90.0 - values["angle"])
            out.append(next_vehicle)
        return out

