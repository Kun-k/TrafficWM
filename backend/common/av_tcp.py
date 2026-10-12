"""Bidirectional newline-delimited JSON transport for online AV testing."""
from __future__ import annotations

import json
import socketserver
import threading
import time
from dataclasses import dataclass, field
from typing import Any


PROTOCOL_SCHEMA = "denseworld.av.v1"
CONTROL_TYPES = {"control", "pause", "resume", "terminate"}


@dataclass(frozen=True)
class AVCommand:
    command_type: str = "control"
    frame: int | None = None
    control_mode: str = "state"
    state: dict[str, float] = field(default_factory=dict)
    actuators: dict[str, float] = field(default_factory=dict)
    trajectory: list[dict[str, float]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    received_at: float = 0.0


def _float_fields(value: Any, names: tuple[str, ...]) -> dict[str, float]:
    source = value if isinstance(value, dict) else {}
    output = {}
    for name in names:
        if source.get(name) is None:
            continue
        try:
            output[name] = float(source[name])
        except (TypeError, ValueError):
            continue
    return output


def parse_av_command(payload: dict[str, Any]) -> AVCommand:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    command_type = str(payload.get("type") or "control").strip().lower()
    if command_type == "hello":
        command_type = "control"
    if command_type not in CONTROL_TYPES:
        raise ValueError(f"unsupported command type: {command_type}")
    try:
        frame = int(payload["frame"]) if payload.get("frame") is not None else None
    except (TypeError, ValueError):
        frame = None

    state_source = payload.get("state") if isinstance(payload.get("state"), dict) else payload
    actuator_source = payload.get("actuators") if isinstance(payload.get("actuators"), dict) else payload.get("control")
    state = _float_fields(
        state_source,
        ("x", "y", "heading", "angle", "speed", "acceleration", "vx", "vy", "ax", "ay"),
    )
    actuators = _float_fields(actuator_source, ("throttle", "brake", "steering", "steer"))

    # Accept the legacy flat/controls envelope used by the existing offline test.
    controls = payload.get("controls") if isinstance(payload.get("controls"), dict) else {}
    for name in ("x", "y", "heading", "angle", "speed", "acceleration"):
        item = controls.get(name)
        if isinstance(item, dict) and bool(item.get("enabled", item.get("use", False))):
            try:
                state[name] = float(item.get("value"))
            except (TypeError, ValueError):
                pass

    mode = str(payload.get("control_mode") or payload.get("mode") or ("actuator" if actuators else "state")).lower()
    if mode not in {"state", "actuator"}:
        raise ValueError("control_mode must be state or actuator")
    trajectory = []
    for point in payload.get("trajectory") or []:
        if isinstance(point, dict):
            trajectory.append(
                _float_fields(point, ("x", "y", "heading", "angle", "speed", "acceleration", "vx", "vy", "ax", "ay"))
            )
    return AVCommand(
        command_type=command_type,
        frame=frame,
        control_mode=mode,
        state=state,
        actuators=actuators,
        trajectory=trajectory,
        diagnostics=dict(payload.get("diagnostics") or {}) if isinstance(payload.get("diagnostics"), dict) else {},
        received_at=time.time(),
    )


class _BridgeState:
    def __init__(self):
        self.condition = threading.Condition()
        self.sequence = 0
        self.command = AVCommand()
        self.handler: _AVTCPHandler | None = None

    def attach(self, handler: "_AVTCPHandler"):
        with self.condition:
            old_handler = self.handler
            self.handler = handler
            self.condition.notify_all()
        if old_handler is not None and old_handler is not handler:
            try:
                old_handler.request.shutdown(2)
            except OSError:
                pass

    def detach(self, handler: "_AVTCPHandler"):
        with self.condition:
            if self.handler is handler:
                self.handler = None
            self.condition.notify_all()

    def set_command(self, command: AVCommand, *, notify: bool = True) -> int:
        with self.condition:
            self.sequence += 1
            self.command = command
            if notify:
                self.condition.notify_all()
            return self.sequence

    def notify_command(self):
        with self.condition:
            self.condition.notify_all()

    def wait_connected(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self.condition:
            while self.handler is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self.condition.wait(remaining)
            return True

    def wait_command(self, after: int, frame: int, timeout: float) -> AVCommand | None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self.condition:
            while True:
                if self.sequence > after and (self.command.frame is None or self.command.frame == frame):
                    return self.command
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self.condition.wait(remaining)


class _AVTCPHandler(socketserver.StreamRequestHandler):
    def setup(self):
        super().setup()
        self._write_lock = threading.Lock()
        self.server.bridge_state.attach(self)  # type: ignore[attr-defined]

    def finish(self):
        self.server.bridge_state.detach(self)  # type: ignore[attr-defined]
        super().finish()

    def send_json(self, payload: dict[str, Any]):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._write_lock:
            self.wfile.write(data)
            self.wfile.flush()

    def handle(self):
        self.send_json(
            {
                "type": "hello",
                "schema": PROTOCOL_SCHEMA,
                "server": "DenseWorld-Drive",
                "control_modes": ["state", "actuator"],
            }
        )
        for raw in self.rfile:
            try:
                payload = json.loads(raw.decode("utf-8"))
                if str(payload.get("type") or "").lower() == "hello":
                    self.send_json({"type": "hello_ack", "schema": PROTOCOL_SCHEMA, "ok": True})
                    continue
                command = parse_av_command(payload)
                sequence = self.server.bridge_state.set_command(command, notify=False)  # type: ignore[attr-defined]
                self.send_json({"type": "command_ack", "ok": True, "frame": command.frame, "sequence": sequence})
                self.server.bridge_state.notify_command()  # type: ignore[attr-defined]
            except Exception as exc:
                self.send_json({"type": "error", "ok": False, "error": str(exc)})


class AVTCPBridge:
    """Owns one AV client connection and synchronizes one command per frame."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = str(host or "127.0.0.1")
        self.port = int(port or 0)
        self.state = _BridgeState()
        self._server: socketserver.ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        with self.state.condition:
            return self.state.handler is not None

    @property
    def endpoint(self) -> str:
        return f"tcp://{self.host}:{self.port}" if self.port > 0 else ""

    def latest_command(self) -> AVCommand:
        with self.state.condition:
            return self.state.command

    def start(self):
        if self._server is not None:
            return
        if self.port <= 0:
            raise ValueError("AV TCP port must be greater than zero")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        server = Server((self.host, self.port), _AVTCPHandler)
        server.bridge_state = self.state  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name=f"AVTCP-{self.port}", daemon=True)
        self._thread.start()

    def exchange(self, perception: dict[str, Any], *, frame: int, timeout: float = 1.0) -> AVCommand | None:
        if self._server is None:
            self.start()
        wait_timeout = max(0.0, float(timeout))
        start = time.monotonic()
        if not self.state.wait_connected(wait_timeout):
            return None
        with self.state.condition:
            sequence = self.state.sequence
            handler = self.state.handler
        if handler is None:
            return None
        handler.send_json({"type": "perception", "schema": PROTOCOL_SCHEMA, "frame": int(frame), **perception})
        remaining = max(0.0, wait_timeout - (time.monotonic() - start))
        return self.state.wait_command(sequence, int(frame), remaining)

    def close(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
