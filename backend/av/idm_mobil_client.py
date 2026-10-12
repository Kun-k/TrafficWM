"""Connect the deployed IDM/MOBIL model to the DenseWorld AV TCP stream."""
from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
from pathlib import Path
from typing import Any

from backend.algorithms.citynde.mixed_traffic_core import oriented_boxes_overlap


def _load_models(source_root: Path):
    package_root = source_root / "idm_mobil" / "src"
    if not package_root.is_dir():
        raise FileNotFoundError(f"IDM/MOBIL package not found: {package_root}")
    sys.path.insert(0, str(package_root))
    from idm_mobil.models import (  # type: ignore[import-not-found]
        IDMParameters,
        MOBILParameters,
        idm_acceleration,
        mobil_incentive,
    )

    return IDMParameters, MOBILParameters, idm_acceleration, mobil_incentive


class IDMMOBILStreamController:
    def __init__(
        self,
        source_root: Path,
        horizon: int = 20,
        desired_speed_mps: float | None = None,
    ):
        IDMParameters, MOBILParameters, self.idm_acceleration, self.mobil_incentive = _load_models(source_root)
        desired_speed = (
            float(desired_speed_mps)
            if desired_speed_mps is not None
            else float(IDMParameters().desired_speed)
        )
        self.idm = IDMParameters(desired_speed=max(1.0, min(35.0, desired_speed)))
        self.mobil = MOBILParameters()
        self.horizon = max(1, int(horizon))
        self.emergency_hold_frames = 0

    @staticmethod
    def _relative(ego: dict[str, Any], actor: dict[str, Any]) -> tuple[float, float]:
        heading = float(ego.get("heading", 0.0))
        dx = float(actor.get("x", 0.0)) - float(ego.get("x", 0.0))
        dy = float(actor.get("y", 0.0)) - float(ego.get("y", 0.0))
        return (
            dx * math.cos(heading) + dy * math.sin(heading),
            -dx * math.sin(heading) + dy * math.cos(heading),
        )

    def _neighbors(
        self,
        ego: dict[str, Any],
        actors: list[dict[str, Any]],
        lane_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        ego_lane_id = str(ego.get("lane_id", ""))
        use_geometric_corridor = bool(lane_id) and str(lane_id) == ego_lane_id
        same_lane = []
        for actor in actors:
            longitudinal, lateral = self._relative(ego, actor)
            same_lane_id = bool(lane_id) and str(actor.get("lane_id", "")) == str(lane_id)
            combined_half_width = 0.5 * (
                float(ego.get("width", 1.8)) + float(actor.get("width", 1.8))
            )
            heading_delta = math.atan2(
                math.sin(float(actor.get("heading", 0.0)) - float(ego.get("heading", 0.0))),
                math.cos(float(actor.get("heading", 0.0)) - float(ego.get("heading", 0.0))),
            )
            in_merging_corridor = (
                use_geometric_corridor
                and longitudinal > 0.0
                and abs(lateral) <= combined_half_width + 0.9
                and abs(heading_delta) <= math.radians(35.0)
            )
            if same_lane_id or in_merging_corridor:
                same_lane.append(actor)
        ahead = [(self._relative(ego, actor)[0], actor) for actor in same_lane]
        leaders = [(distance, actor) for distance, actor in ahead if distance > 0.0]
        followers = [(distance, actor) for distance, actor in ahead if distance <= 0.0]
        leader = min(leaders, key=lambda item: item[0])[1] if leaders else None
        follower = max(followers, key=lambda item: item[0])[1] if followers else None
        return leader, follower

    def _idm_for(self, ego: dict[str, Any], leader: dict[str, Any] | None) -> float:
        if leader is None:
            return float(self.idm_acceleration(float(ego.get("speed", 0.0)), None, None, self.idm))
        distance, _ = self._relative(ego, leader)
        gap = distance - 0.5 * float(ego.get("length", 3.8)) - 0.5 * float(leader.get("length", 3.8))
        return float(
            self.idm_acceleration(
                float(ego.get("speed", 0.0)),
                float(leader.get("speed", 0.0)),
                max(0.1, gap),
                self.idm,
            )
        )

    def _select_lane(
        self,
        ego: dict[str, Any],
        actors: list[dict[str, Any]],
        lane_context: dict[str, Any],
    ) -> tuple[str, float, float]:
        current_id = str(lane_context.get("current_id") or ego.get("lane_id") or "")
        current_leader, old_follower = self._neighbors(ego, actors, current_id)
        current_acceleration = self._idm_for(ego, current_leader)
        best = (current_id, current_acceleration, float("-inf"))
        route = lane_context.get("route") if isinstance(lane_context.get("route"), dict) else {}
        locked_route_ids = {
            str(lane_id) for lane_id in route.get("ids") or [] if str(lane_id)
        } if lane_context.get("route_locked") else set()
        for side, moving_right in (("left", False), ("right", True)):
            target = lane_context.get(side) if isinstance(lane_context.get(side), dict) else {}
            target_id = str(target.get("id") or "")
            if not target_id or (locked_route_ids and target_id not in locked_route_ids):
                continue
            new_leader, new_follower = self._neighbors(ego, actors, target_id)
            ego_after = self._idm_for(ego, new_leader)
            new_follower_before = self._idm_for(new_follower, new_leader) if new_follower else 0.0
            new_follower_after = self._idm_for(new_follower, ego) if new_follower else 0.0
            old_follower_before = self._idm_for(old_follower, ego) if old_follower else 0.0
            old_follower_after = self._idm_for(old_follower, current_leader) if old_follower else 0.0
            accepted, score = self.mobil_incentive(
                current_acceleration,
                ego_after,
                new_follower_before,
                new_follower_after,
                old_follower_before,
                old_follower_after,
                self.mobil,
                moving_right=moving_right,
            )
            if accepted and float(score) > best[2]:
                best = (target_id, ego_after, float(score))
        return best

    @staticmethod
    def _lane_points(lane_context: dict[str, Any], lane_id: str) -> list[list[float]]:
        if str(lane_context.get("current_id") or "") == str(lane_id):
            route = lane_context.get("route") if isinstance(lane_context.get("route"), dict) else {}
            route_points = [
                point for point in route.get("points") or [] if isinstance(point, list) and len(point) >= 2
            ]
            if route_points:
                return route_points
        for key in ("current", "left", "right"):
            lane = lane_context.get(key) if isinstance(lane_context.get(key), dict) else {}
            if str(lane.get("id") or "") == str(lane_id):
                return [point for point in lane.get("points") or [] if isinstance(point, list) and len(point) >= 2]
        return []

    @staticmethod
    def _signal_obstacle(ego: dict[str, Any], lane_context: dict[str, Any]) -> dict[str, Any] | None:
        candidates = []
        for signal in lane_context.get("signals") or []:
            if not isinstance(signal, dict) or int(signal.get("state", 3)) not in {1, 2}:
                continue
            distance = float(signal.get("distance_m", float("inf")))
            if not math.isfinite(distance) or distance < 0.0:
                continue
            if int(signal.get("state", 3)) == 1:
                speed = max(0.0, float(ego.get("speed", 0.0)))
                comfortable_stop_distance = 0.4 * speed + speed * speed / (2.0 * 3.5)
                if speed > 0.5 and distance + 1e-6 < comfortable_stop_distance:
                    # The ego is inside the yellow-light dilemma zone. Braking
                    # here would leave its body in the crosswalk, so clear the
                    # intersection instead of introducing a late hard stop.
                    continue
            candidates.append((distance, signal))
        if not candidates:
            return None
        distance, signal = min(candidates, key=lambda item: item[0])
        hold_at_current_pose = distance <= 0.25
        return {
            "id": f"traffic-light:{signal.get('id', '')}",
            "type": "TRAFFIC_LIGHT_STOP",
            "x": float(ego.get("x", 0.0)) if hold_at_current_pose else float(signal.get("stop_x", ego.get("x", 0.0))),
            "y": float(ego.get("y", 0.0)) if hold_at_current_pose else float(signal.get("stop_y", ego.get("y", 0.0))),
            "heading": float(ego.get("heading", 0.0)),
            "speed": 0.0,
            "length": 0.2,
            "width": max(2.0, float(ego.get("width", 1.8))),
            "lane_id": str(lane_context.get("current_id") or ego.get("lane_id") or ""),
            "signal_id": str(signal.get("id", "")),
            "signal_state": int(signal.get("state", 3)),
        }

    @staticmethod
    def _rollout_trajectory(
        ego: dict[str, Any],
        points: list[list[float]],
        acceleration: float,
        dt: float,
        horizon: int,
    ) -> list[dict[str, float]]:
        x = float(ego.get("x", 0.0))
        y = float(ego.get("y", 0.0))
        heading = float(ego.get("heading", 0.0))
        speed = max(0.0, float(ego.get("speed", 0.0)))
        trajectory = []
        for _ in range(horizon):
            speed = max(0.0, speed + acceleration * dt)
            if points:
                nearest = min(
                    range(len(points)),
                    key=lambda idx: (points[idx][0] - x) ** 2 + (points[idx][1] - y) ** 2,
                )
                target_index = min(len(points) - 1, nearest + max(1, int(round(speed * dt / 0.5))))
                target_x, target_y = float(points[target_index][0]), float(points[target_index][1])
                desired_heading = math.atan2(target_y - y, target_x - x)
                delta = math.atan2(math.sin(desired_heading - heading), math.cos(desired_heading - heading))
                heading += max(-0.12, min(0.12, delta))
            x += speed * math.cos(heading) * dt
            y += speed * math.sin(heading) * dt
            trajectory.append(
                {
                    "x": x,
                    "y": y,
                    "heading": heading,
                    "speed": speed,
                    "vx": speed * math.cos(heading),
                    "vy": speed * math.sin(heading),
                    "ax": acceleration * math.cos(heading),
                    "ay": acceleration * math.sin(heading),
                }
            )
        return trajectory

    @staticmethod
    def _predicted_hazard(
        ego: dict[str, Any],
        actors: list[dict[str, Any]],
        trajectory: list[dict[str, float]],
        dt: float,
    ) -> tuple[dict[str, Any] | None, float | None]:
        ego_size = (float(ego.get("length", 3.8)), float(ego.get("width", 1.8)))
        for index, state in enumerate(trajectory):
            time_offset = (index + 1) * dt
            for actor in actors:
                actor_heading = float(actor.get("heading", 0.0))
                actor_speed = max(0.0, float(actor.get("speed", 0.0)))
                longitudinal, _ = IDMMOBILStreamController._relative(ego, actor)
                heading_delta = abs(
                    math.atan2(
                        math.sin(actor_heading - float(ego.get("heading", 0.0))),
                        math.cos(actor_heading - float(ego.get("heading", 0.0))),
                    )
                )
                if longitudinal < 0.0 and heading_delta < math.radians(45.0):
                    continue
                actor_pose = (
                    float(actor.get("x", 0.0)) + actor_speed * math.cos(actor_heading) * time_offset,
                    float(actor.get("y", 0.0)) + actor_speed * math.sin(actor_heading) * time_offset,
                    actor_heading,
                )
                if oriented_boxes_overlap(
                    (state["x"], state["y"], state["heading"]),
                    ego_size,
                    actor_pose,
                    (float(actor.get("length", 3.8)), float(actor.get("width", 1.8))),
                    margin=0.35,
                ):
                    return actor, time_offset
        return None, None

    def compute(self, perception: dict[str, Any]) -> dict[str, Any]:
        frame = int(perception.get("frame", 0) or 0)
        dt = max(0.01, float(perception.get("step_seconds", 0.1) or 0.1))
        ego = dict(perception.get("av") or {})
        actors = [dict(actor) for actor in perception.get("actors") or []]
        lane_context = dict(perception.get("lane_context") or {})
        signal_obstacle = self._signal_obstacle(ego, lane_context)
        if signal_obstacle is not None:
            actors.append(signal_obstacle)
            target_lane = str(lane_context.get("current_id") or ego.get("lane_id") or "")
            selected_leader, _ = self._neighbors(ego, actors, target_lane)
            acceleration = self._idm_for(ego, selected_leader)
            mobil_score = float("-inf")
        else:
            target_lane, acceleration, mobil_score = self._select_lane(ego, actors, lane_context)
            selected_leader, _ = self._neighbors(ego, actors, target_lane)
        acceleration = max(-6.0, min(float(self.idm.max_acceleration), acceleration))
        points = self._lane_points(lane_context, target_lane)
        candidate = self._rollout_trajectory(ego, points, acceleration, dt, self.horizon)
        hazard, predicted_ttc = self._predicted_hazard(ego, actors, candidate, dt)
        emergency_braking = hazard is not None
        if emergency_braking:
            self.emergency_hold_frames = max(self.emergency_hold_frames, 5)
            acceleration = -6.0
        elif self.emergency_hold_frames > 0:
            self.emergency_hold_frames -= 1
            acceleration = min(acceleration, -3.0)
        trajectory = self._rollout_trajectory(ego, points, acceleration, dt, self.horizon)
        return {
            "type": "control",
            "frame": frame,
            "control_mode": "state",
            "trajectory": trajectory,
            "diagnostics": {
                "controller": "IDM_MOBIL",
                "desired_speed_mps": float(self.idm.desired_speed),
                "target_lane_id": target_lane,
                "leader_actor_id": str(selected_leader.get("id", "")) if selected_leader is not None else "",
                "signal_stop_id": str(signal_obstacle.get("signal_id", "")) if signal_obstacle is not None else "",
                "signal_stop_state": signal_obstacle.get("signal_state") if signal_obstacle is not None else None,
                "acceleration": acceleration,
                "mobil_score": mobil_score if math.isfinite(mobil_score) else None,
                "emergency_braking": emergency_braking or self.emergency_hold_frames > 0,
                "emergency_hold_frames": self.emergency_hold_frames,
                "hazard_actor_id": str(hazard.get("id", "")) if hazard is not None else "",
                "predicted_ttc_seconds": predicted_ttc,
            },
        }


def run_client(host: str, port: int, controller: IDMMOBILStreamController) -> None:
    command_count = 0
    while True:
        try:
            with socket.create_connection((host, port), timeout=5.0) as sock:
                sock.settimeout(None)
                stream = sock.makefile("rwb")
                json.loads(stream.readline())
                stream.write(json.dumps({"type": "hello", "client": "IDM_MOBIL"}).encode("utf-8") + b"\n")
                stream.flush()
                for raw in stream:
                    message = json.loads(raw)
                    if message.get("type") != "perception":
                        continue
                    command = controller.compute(message)
                    stream.write(json.dumps(command, separators=(",", ":")).encode("utf-8") + b"\n")
                    stream.flush()
                    command_count += 1
                    if command_count <= 3 or command_count % 25 == 0:
                        print(
                            json.dumps(
                                {
                                    "event": "control_sent",
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
            print(f"IDM/MOBIL stream reconnecting after: {exc}", flush=True)
            time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--source-root", type=Path, default=Path("/mnt/rk/cnde/autonomous_vehicles"))
    parser.add_argument("--desired-speed-mps", type=float)
    args = parser.parse_args(argv)
    run_client(
        args.host,
        args.port,
        IDMMOBILStreamController(
            args.source_root,
            desired_speed_mps=args.desired_speed_mps,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
