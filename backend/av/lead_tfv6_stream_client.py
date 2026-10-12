"""Consume live OmniDreams RGB while using an explicit safe control fallback.

The deployed LEAD TFv6 checkpoint is not an RGB-only policy. Its official
runtime also requires LiDAR history, radar, route targets, and high-level
commands. This bridge validates the live RGB leg of that contract and keeps
the AV controllable through the verified IDM/MOBIL stream controller without
misrepresenting the fallback as TFv6 inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.av.idm_mobil_client import IDMMOBILStreamController


TFV6_WIDTH = 1152
TFV6_HEIGHT = 384


class LEADTFv6StreamController:
    def __init__(
        self,
        fallback: IDMMOBILStreamController,
        *,
        audit_path: Path | None = None,
    ):
        self.fallback = fallback
        self.audit_path = audit_path.resolve() if audit_path else None
        self.previous_digest = ""
        self.rgb_frames = 0
        self.rgb_failures = 0
        self.duplicate_frames = 0
        if self.audit_path is not None:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_sensor_bytes(sensor: dict[str, Any]) -> bytes:
        uri = str(sensor.get("uri") or "").strip()
        if not uri:
            raise ValueError("RGB sensor URI is empty")
        transport = str(sensor.get("transport") or "file").lower()
        if transport == "file" or uri.startswith("file://"):
            return Path(uri.removeprefix("file://")).read_bytes()
        request = urllib.request.Request(uri, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=0.5) as response:
            return response.read()

    def _consume_rgb(self, perception: dict[str, Any]) -> dict[str, Any]:
        sensor = dict((perception.get("sensors") or {}).get("rgb_front") or {})
        try:
            encoded = self._read_sensor_bytes(sensor)
            image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                raise ValueError("RGB frame cannot be decoded")
            resized = cv2.resize(image, (TFV6_WIDTH, TFV6_HEIGHT), interpolation=cv2.INTER_AREA)
            digest = hashlib.sha256(resized.tobytes()).hexdigest()
            duplicate = digest == self.previous_digest
            self.previous_digest = digest
            self.rgb_frames += 1
            self.duplicate_frames += int(duplicate)
            return {
                "available": True,
                "source_width": int(image.shape[1]),
                "source_height": int(image.shape[0]),
                "tfv6_width": TFV6_WIDTH,
                "tfv6_height": TFV6_HEIGHT,
                "digest": digest,
                "duplicate": duplicate,
                "blank": bool(float(np.std(resized)) < 1.0),
                "error": "",
            }
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.rgb_failures += 1
            return {
                "available": False,
                "source_width": 0,
                "source_height": 0,
                "tfv6_width": TFV6_WIDTH,
                "tfv6_height": TFV6_HEIGHT,
                "digest": "",
                "duplicate": False,
                "blank": False,
                "error": str(exc),
            }

    def _append_audit(self, payload: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")

    def compute(self, perception: dict[str, Any]) -> dict[str, Any]:
        rgb = self._consume_rgb(perception)
        command = self.fallback.compute(perception)
        diagnostics = dict(command.get("diagnostics") or {})
        diagnostics.update(
            {
                "controller": "LEAD_TFV6_STREAM",
                "rgb_source": "cosmos-dreams",
                "rgb_frame_available": bool(rgb["available"]),
                "rgb_frame_digest": rgb["digest"],
                "rgb_duplicate": bool(rgb["duplicate"]),
                "rgb_blank": bool(rgb["blank"]),
                "rgb_frames": self.rgb_frames,
                "rgb_failures": self.rgb_failures,
                "tfv6_inference_executed": False,
                "control_effect_guaranteed": False,
                "control_source": "IDM_MOBIL_SAFETY_FALLBACK",
                "missing_tfv6_inputs": [
                    "lidar_history_10",
                    "radar_sensors_4",
                    "route_target",
                    "high_level_command",
                ],
            }
        )
        command["diagnostics"] = diagnostics
        self._append_audit(
            {
                "frame": int(perception.get("frame", 0) or 0),
                "sim_time": float(perception.get("sim_time", 0.0) or 0.0),
                "rgb": rgb,
                "tfv6_inference_executed": False,
                "control_source": "IDM_MOBIL_SAFETY_FALLBACK",
                "recorded_at_unix": time.time(),
            }
        )
        return command


def run_client(host: str, port: int, controller: LEADTFv6StreamController) -> None:
    command_count = 0
    while True:
        try:
            with socket.create_connection((host, port), timeout=5.0) as sock:
                sock.settimeout(None)
                stream = sock.makefile("rwb")
                json.loads(stream.readline())
                stream.write(json.dumps({"type": "hello", "client": "LEAD_TFV6_STREAM"}).encode() + b"\n")
                stream.flush()
                for raw in stream:
                    message = json.loads(raw)
                    if message.get("type") != "perception":
                        continue
                    command = controller.compute(message)
                    stream.write(json.dumps(command, separators=(",", ":")).encode() + b"\n")
                    stream.flush()
                    command_count += 1
                    if command_count <= 3 or command_count % 25 == 0:
                        print(
                            json.dumps(
                                {
                                    "event": "visual_stream_control_sent",
                                    "frame": command.get("frame"),
                                    "command_count": command_count,
                                    "diagnostics": command.get("diagnostics") or {},
                                },
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            flush=True,
                        )
        except (ConnectionError, OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"LEAD TFv6 stream reconnecting after: {exc}", flush=True)
            time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("/mnt/rk/cnde/autonomous_vehicles"))
    parser.add_argument("--audit-path", type=Path, required=True)
    args = parser.parse_args(argv)
    fallback = IDMMOBILStreamController(args.source_root)
    run_client(args.host, args.port, LEADTFv6StreamController(fallback, audit_path=args.audit_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
