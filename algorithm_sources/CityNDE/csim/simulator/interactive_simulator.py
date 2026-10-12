from __future__ import annotations

import math
import os
import pickle
import queue
import select
import sys
import threading
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import tqdm

from csim.agent import RoadUserState, RoutedVehicle
from csim.manager import RouteTLVectorMap
from csim.simulator.simulator import RouteTLSimulator
from csim.viewer.realtime_viewer import RealtimeViewer
from csim.viewer.web_viewer import WebViewer

from .interactive_commands import HELP_TEXT, parse_command

__all__ = ["InteractiveRouteTLSimulator"]


def _check_stdin():
    """Non-blocking check for terminal input (Unix)."""
    try:
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.readline().strip().lower()
    except Exception:
        pass
    return None


class InteractiveRouteTLSimulator(RouteTLSimulator):
    def __init__(
        self,
        map_path: str = "",
        sim_resolution: float = 0.1,
        history_step: int = 11,
        agent_controller=None,
        auto_agent_dep: bool = True,
        auto_agent_arr: bool = True,
        visualize: bool = False,
        viewer_mode: Literal["overview", "region", "region_full"] = "overview",
        region_center: np.ndarray | None = None,
        roi_radius: float = 180.0,
        image_size: int = 1024,
        render_interval: int = 5,
        async_render: bool = True,
        pause_interval: int = 0,
        port: int = 8890,
        default_spawn_speed: float = 2.0,
    ):
        super().__init__(
            map_path=map_path,
            sim_resolution=sim_resolution,
            history_step=history_step,
            agent_controller=agent_controller,
            auto_agent_dep=auto_agent_dep,
            auto_agent_arr=auto_agent_arr,
        )

        self.lane_arrival_rates: dict[int | str, float] = {}
        self.default_arrival_rate: float = 0.06
        self.default_spawn_speed: float = float(default_spawn_speed)
        self.click_spawn_max_lane_distance: float = 2.0
        self.click_delete_max_vehicle_distance: float = 2.0

        self.static_vehicle_ids: set[int | str] = set()
        self.paused: bool = False
        self._quit_requested: bool = False
        self._step_budget: int = 0
        self._pause_interval: int = pause_interval
        self._pause_pending: bool = False
        self._render_interval: int = max(1, int(render_interval))
        self._async_render: bool = bool(async_render and visualize)
        self._render_queue: queue.Queue | None = None
        self._render_stop: threading.Event | None = None
        self._render_thread: threading.Thread | None = None

        self._future_behavior_overrides: dict[int | str, np.ndarray] = {}

        self.workspace_root = Path(__file__).resolve().parents[2]
        self.map_root = (self.workspace_root / "assets" / "map").resolve()

        self.visualize = visualize
        self.viewer: RealtimeViewer | None = None
        self.web_viewer: WebViewer | None = None
        if visualize:
            self.viewer = RealtimeViewer(
                map_ref=self.map,
                mode=viewer_mode,
                region_center=region_center,
                roi_radius=roi_radius,
                image_size=image_size,
            )
            self.web_viewer = WebViewer(mode=viewer_mode, port=port)
            self.web_viewer.set_maps(self._list_available_maps())
            self.web_viewer.set_status_fields(
                {
                    "default_spawn_speed": self.default_spawn_speed,
                    "show_vehicle_id": bool(self.viewer.plot_id),
                    "pause_pending": bool(self._pause_pending),
                }
            )
            if self._async_render:
                self._render_queue = queue.Queue(maxsize=1)
                self._render_stop = threading.Event()
                self._render_thread = threading.Thread(target=self._render_worker, daemon=True)
                self._render_thread.start()

    def run(
        self,
        init_mode: Literal["random", "empty", "data", "data_random_tl", "random_tl_only", "none"] = "none",
        init_file: str | None = None,
        init_dict: dict | None = None,
        total_step: int = 10000,
        save_file: str | None = None,
        save_interval: int = 1,
        termination_mode: Literal["AV_collision", "None"] = "None",
    ):
        if save_file is not None:
            os.makedirs(os.path.dirname(save_file), exist_ok=True)

        try:
            for step in tqdm.trange(total_step, desc="step"):
                if self._quit_requested:
                    break
                if self.check_termination(mode=termination_mode):
                    break
                if step == 0 and init_mode != "none":
                    self.init_scenario_agents(mode=init_mode, init_file=init_file, init_dict=init_dict)

                scenario_update = self.step()
                scenario_update = self.external_step(scenario_update)
                self.update(scenario_update, save_file=save_file, save_interval=save_interval)

                self._schedule_render(force=False)

                if self.web_viewer is not None:
                    self.web_viewer.set_paused(self.paused)
                    self.web_viewer.set_status_fields({"pause_pending": bool(self._pause_pending)})
                    self._process_web_actions()

                stdin_line = _check_stdin()
                if stdin_line in ("pause", "p"):
                    self._pause_pending = True
                elif stdin_line in ("quit", "q"):
                    self._quit_requested = True
                    break

                if self.web_viewer is not None and self.web_viewer.pause_requested:
                    self._pause_pending = True

                if self._pause_pending:
                    cs = getattr(self.agent_controller, "control_step", 1) if self.agent_controller else 1
                    if self.current_step % cs == 0:
                        self.paused = True
                        self._pause_pending = False
                        print(f"\n[Paused at step {self.current_step}]")

                if self._step_budget > 0:
                    self._step_budget -= 1
                    if self._step_budget == 0:
                        self.paused = True

                if (
                    self._pause_interval > 0
                    and step > 0
                    and step % self._pause_interval == 0
                    and not self.paused
                ):
                    self.paused = True
                    print(f"\n[Auto-pause at step {step}]")

                if self.paused:
                    self._command_loop()
                    if self._quit_requested:
                        break
                    if self.web_viewer is not None:
                        self.web_viewer.set_paused(False)
            else:
                self.status = "terminated_finished"
        finally:
            self._stop_render_worker()
            if self.web_viewer is not None:
                self.web_viewer.close()

    def _render_worker(self):
        assert self._render_queue is not None
        assert self._render_stop is not None
        while not self._render_stop.is_set():
            try:
                payload = self._render_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if payload is None:
                break
            self._render_and_publish(payload)

    def _stop_render_worker(self):
        if self._render_thread is None:
            return
        assert self._render_stop is not None
        assert self._render_queue is not None
        self._render_stop.set()
        try:
            self._render_queue.put_nowait(None)
        except queue.Full:
            try:
                _ = self._render_queue.get_nowait()
            except Exception:
                pass
            try:
                self._render_queue.put_nowait(None)
            except Exception:
                pass
        self._render_thread.join(timeout=2.0)
        self._render_thread = None

    def _build_render_payload(self, paused_override: bool | None = None) -> dict | None:
        if not self.visualize or self.viewer is None:
            return None

        agent_ids, agents_state, agents_mask = self.agent_record[-1]
        if not isinstance(agent_ids, list):
            agent_ids = [agent_ids]
        agent_ids = np.array(agent_ids, dtype=object)
        agents_mask = agents_mask.reshape(-1)

        if np.any(agents_mask):
            valid_ids = np.array(agent_ids[agents_mask], dtype=object)
            valid_states = np.array(agents_state[agents_mask][:, :3], dtype=float, copy=True)
            valid_statics = np.array(agents_state[agents_mask][:, -3:], dtype=float, copy=True)
        else:
            valid_ids = np.array([], dtype=object)
            valid_states = np.empty((0, 3), dtype=float)
            valid_statics = np.empty((0, 3), dtype=float)

        tl_type_by_id = self._get_current_tl_type_map()
        paused = self.paused if paused_override is None else bool(paused_override)

        return {
            "step": self.current_step,
            "vehicle_count": int(len(valid_ids)),
            "mode": self.viewer.mode,
            "paused": paused,
            "valid_ids": valid_ids,
            "valid_states": valid_states,
            "valid_statics": valid_statics,
            "static_vehicle_ids": set(self.static_vehicle_ids),
            "tl_type_by_id": tl_type_by_id,
        }

    def _render_and_publish(self, payload: dict):
        if self.viewer is None:
            return
        frame = self.viewer.render_frame_from_snapshot(
            current_step=payload["step"],
            valid_ids=payload["valid_ids"],
            valid_states=payload["valid_states"],
            valid_statics=payload["valid_statics"],
            static_vehicle_ids=payload["static_vehicle_ids"],
            tl_type_by_id=payload["tl_type_by_id"],
        )
        if self.web_viewer is not None:
            self.web_viewer.update(
                frame,
                payload["step"],
                payload["vehicle_count"],
                payload["mode"],
                payload["paused"],
                extra_status={
                    "default_spawn_speed": float(self.default_spawn_speed),
                    "show_vehicle_id": bool(self.viewer.plot_id),
                },
            )

    def _schedule_render(self, force: bool = False, paused_override: bool | None = None):
        if not self.visualize or self.viewer is None:
            return
        if not force and (self.current_step % self._render_interval != 0):
            return

        payload = self._build_render_payload(paused_override=paused_override)
        if payload is None:
            return

        if not self._async_render:
            self._render_and_publish(payload)
            return

        try:
            self._render_queue.put_nowait(payload)
        except queue.Full:
            try:
                _ = self._render_queue.get_nowait()
            except Exception:
                pass
            try:
                self._render_queue.put_nowait(payload)
            except Exception:
                pass

    def _get_current_tl_type_map(self) -> dict[int | str, int]:
        try:
            tl_ids, tl_states, tl_mask = self.map[-1, :, :4]
            if not isinstance(tl_ids, list):
                tl_ids = [tl_ids]
            tl_ids = np.array(tl_ids, dtype=object)
            tl_mask = np.array(tl_mask).reshape(-1).astype(bool)
            if tl_ids.size == 0 or tl_mask.size == 0 or not np.any(tl_mask):
                return {}

            valid_ids = tl_ids[tl_mask]
            valid_states = np.array(tl_states)[tl_mask]
            if valid_states.ndim == 1:
                valid_states = valid_states.reshape(1, -1)
            if valid_states.shape[-1] < 4:
                return {}

            tl_types = np.argmax(valid_states[:, :4], axis=-1).astype(int)
            return {tid: int(t) for tid, t in zip(valid_ids.tolist(), tl_types.tolist())}
        except Exception:
            return {}

    def _count_active_vehicles(self) -> int:
        try:
            _, _, mask = self.agent_record[-1, :, :1]
            return int(np.sum(mask.reshape(-1)))
        except Exception:
            return 0

    def _list_available_maps(self) -> list[str]:
        if not self.map_root.exists():
            return []
        maps = []
        for p in sorted(self.map_root.rglob("*.pkl")):
            maps.append(str(p.relative_to(self.workspace_root)).replace("\\", "/"))
        return maps

    def _normalize_vehicle_id(self, vehicle_id):
        if isinstance(vehicle_id, int):
            return vehicle_id
        if vehicle_id is None:
            return None
        s = str(vehicle_id).strip()
        if s == "":
            return None
        try:
            return int(s)
        except ValueError:
            return s

    def _resolve_workspace_path(self, raw_path: str) -> Path:
        if not raw_path:
            raise ValueError("Empty path")
        p = Path(raw_path)
        if not p.is_absolute():
            p = (self.workspace_root / p).resolve()
        else:
            p = p.resolve()

        # forbidden = str((self.workspace_root.parent / "CityNDE_bin").resolve())
        # if str(p).startswith(forbidden):
        #     raise ValueError("Access to /home/lzy/CityNDE_bin is forbidden")
        return p

    def set_all_lane_arrival_rate(self, prob: float):
        prob = max(0.0, min(1.0, float(prob)))
        for lane_id in self.map.start_lane:
            self.lane_arrival_rates[lane_id] = prob
        print(f"All start lanes arrival rate set to {prob:.4f}")

    def set_lane_arrival_rate(self, lane_id: int | str, prob: float):
        if lane_id not in self.map.start_lane:
            print(f"Warning: lane {lane_id} is not a start lane. Available: {self.map.start_lane}")
            return
        self.lane_arrival_rates[lane_id] = max(0.0, min(1.0, float(prob)))
        print(f"Lane {lane_id} arrival rate set to {self.lane_arrival_rates[lane_id]:.4f}")

    def generate_agent(self, prob: float = 4e-2, init_step: int = 11, init_speed: float = 2.0):
        gen_pos = 5
        min_road_end_dist = 20
        gen_v_num = 0

        for lane_id in self.map.start_lane:
            lane_prob = self.lane_arrival_rates.get(lane_id, self.default_arrival_rate)
            lane_chain = self.map.get_lane_chain(lane_id, max_depth=10)
            if np.random.uniform(0, 1) > lane_prob or len(lane_chain) == 0:
                continue
            if self.map.polyline_length(lane_chain) - gen_pos < min_road_end_dist:
                continue
            generated_position_heading = self.map.polyline_relative_pos(lane_chain, lon=gen_pos)
            if self.agent_record.simple_check_conflict(generated_position_heading[:2], extra_only=True):
                continue
            generated_history_position_heading = self.map.polyline_relative_pos(
                lane_chain, lon=gen_pos - init_speed * self.sim_resolution * (init_step - 1)
            )
            if self.agent_record.simple_check_conflict(
                generated_history_position_heading[:2], extra_only=True, time_step=-init_step
            ):
                continue

            gen_vehicle_states = RoadUserState()
            for i in range(init_step):
                gen_vehicle_states.update(
                    [
                        generated_position_heading[0]
                        - ((init_step - i - 1) * init_speed * math.cos(generated_position_heading[2]))
                        * self.sim_resolution,
                        generated_position_heading[1]
                        - ((init_step - i - 1) * init_speed * math.sin(generated_position_heading[2]))
                        * self.sim_resolution,
                        generated_position_heading[2],
                        init_speed * math.cos(generated_position_heading[2]),
                        init_speed * math.sin(generated_position_heading[2]),
                        0.0,
                        0.0,
                    ]
                )

            self.agent_record.add_agents_from_history_states(
                vehicles_id=max(self.agent_record._id_agent_mapping) + 1 if len(self.agent_record._id_agent_mapping) > 0 else 0,
                vehicles_states=gen_vehicle_states,
                vehicles_static=np.array([3.8, 1.8, 1.5]),
                vehicles_type=RoutedVehicle,
            )
            gen_v_num += 1

        print(f"Generation done, {gen_v_num} new vehicles in total")

    def step(self, predicted_green_tls=None):
        result = super().step(predicted_green_tls)

        if "vehicle_id" in result and "vehicle_states" in result:
            vehicle_ids = list(result["vehicle_id"])

            # Apply queued future behavior overrides on top of controller output.
            stale_vids = []
            for vid, future_states in self._future_behavior_overrides.items():
                if vid not in vehicle_ids:
                    continue
                idx = vehicle_ids.index(vid)
                horizon = min(result["vehicle_states"].shape[1], len(future_states))
                if horizon > 0:
                    result["vehicle_states"][idx, :horizon, :7] = future_states[:horizon]
                if len(future_states) <= 1:
                    stale_vids.append(vid)
                else:
                    self._future_behavior_overrides[vid] = future_states[1:]
            for vid in stale_vids:
                self._future_behavior_overrides.pop(vid, None)


        return result

    def reload_map(self, new_map_path: str):
        if not Path(new_map_path).exists():
            print(f"Error: Map file '{new_map_path}' not found.")
            return

        with open(new_map_path, "rb") as f:
            map_info = pickle.load(f)

        self.map.load_map(map_info)

        if hasattr(self.agent_controller, "map_enhance"):
            self.agent_controller.map_enhance = self.map

        if hasattr(self.agent_controller, "safety_layer_cache"):
            self.agent_controller.safety_layer_cache = {}

        self._clear_all_vehicle_routes()
        self._remove_off_road_vehicles()

        if self.viewer is not None:
            self.viewer.invalidate_map_cache()

        if self.web_viewer is not None:
            self.web_viewer.set_maps(self._list_available_maps())

        print(f"Map reloaded from '{new_map_path}'. Off-road vehicles removed.")

    def _clear_all_vehicle_routes(self):
        for agent in self.agent_record._id_agent_mapping.values():
            if hasattr(agent, "route") and len(agent.route) > 0:
                agent.assign_route([])
            if hasattr(agent, "left_route"):
                agent.left_route = []
            if hasattr(agent, "right_route"):
                agent.right_route = []

    def _remove_off_road_vehicles(self, max_lane_dist: float = 5.0):
        agent_ids, agents_state, agents_mask = self.agent_record[-1, :, :3]
        if not isinstance(agent_ids, list):
            agent_ids = [agent_ids]
        agent_ids = np.array(agent_ids, dtype=object)
        agents_mask = agents_mask.reshape(-1)

        if not np.any(agents_mask):
            return

        valid_ids = agent_ids[agents_mask]
        valid_pos = agents_state[agents_mask, :2]

        off_road_ids = []
        for vid, pos in zip(valid_ids, valid_pos):
            try:
                _, dist = self.map.get_current_lane(pos)
                if dist > max_lane_dist:
                    off_road_ids.append(vid)
            except Exception:
                off_road_ids.append(vid)

        if off_road_ids:
            self.agent_record.delete_id_agents(off_road_ids)
            self.static_vehicle_ids -= set(off_road_ids)
            print(f"Removed {len(off_road_ids)} off-road vehicles after map reload.")

    def add_vehicle(
        self,
        x: float,
        y: float,
        heading: float,
        vx: float = 0.0,
        vy: float = 0.0,
        static: bool = False,
        length: float = 3.8,
        width: float = 1.8,
        height: float = 1.5,
        init_step: int = 11,
        vehicle_id: int | str | None = None,
    ) -> int | str:
        if not self._can_place_vehicle(x, y, heading, length, width):
            raise ValueError("Spawn rejected: collision check failed with existing vehicles")

        if vehicle_id is None:
            new_id = max(self.agent_record._id_agent_mapping) + 1
        else:
            new_id = vehicle_id

        gen_vehicle_states = RoadUserState()
        for i in range(init_step):
            dt = (init_step - i - 1) * self.sim_resolution
            gen_vehicle_states.update([x - vx * dt, y - vy * dt, heading, vx, vy, 0.0, 0.0])

        self.agent_record.add_agents_from_history_states(
            vehicles_id=new_id,
            vehicles_states=gen_vehicle_states,
            vehicles_static=np.array([length, width, height]),
            vehicles_type=RoutedVehicle,
        )

        if static:
            self.static_vehicle_ids.add(new_id)

        print(
            f"Vehicle {new_id} added at ({x:.1f}, {y:.1f}) heading={heading:.2f}"
            f" v=({vx:.1f}, {vy:.1f}){' [static]' if static else ''}"
        )
        return new_id

    def remove_vehicle(self, vehicle_id: int | str):
        self.agent_record.delete_id_agents(vehicle_id)
        # Remove from current recorded ids as well so paused rendering updates immediately.
        try:
            cur_step = self.agent_record.current_step
            if cur_step >= 0:
                cur_ids = self.agent_record._agents_id_per_step[cur_step]
                self.agent_record._agents_id_per_step[cur_step] = [vid for vid in cur_ids if vid != vehicle_id]
        except Exception:
            pass
        self.static_vehicle_ids.discard(vehicle_id)
        self._future_behavior_overrides.pop(vehicle_id, None)
        print(f"Vehicle {vehicle_id} removed.")

    def _toggle_vehicle_control_mode(
        self,
        vehicle_id: int | str | None,
    ) -> tuple[int | str, bool]:
        vid = self._normalize_vehicle_id(vehicle_id)
        if vid is None:
            raise ValueError("vehicle_id is required")
        if vid not in self.agent_record._id_agent_mapping:
            raise ValueError(f"Vehicle {vid} not found")

        now_static = vid in self.static_vehicle_ids
        if now_static:
            self.static_vehicle_ids.discard(vid)
            # Clear injected overrides so simulator logic fully resumes control.
            self._future_behavior_overrides.pop(vid, None)
            return vid, False

        self.static_vehicle_ids.add(vid)
        # Keep static behavior deterministic after toggling.
        self._future_behavior_overrides.pop(vid, None)
        return vid, True

    def _find_vehicle_at_world(self, x: float, y: float, max_center_dist: float | None = None) -> int | str | None:
        agent_ids, agents_state, agents_mask = self.agent_record[-1]
        if not isinstance(agent_ids, list):
            agent_ids = [agent_ids]
        agent_ids = np.array(agent_ids, dtype=object)
        agents_mask = np.array(agents_mask).reshape(-1).astype(bool)
        if not np.any(agents_mask):
            return None

        valid_ids = agent_ids[agents_mask]
        valid_states = np.array(agents_state[agents_mask][:, :3], dtype=float)
        valid_statics = np.array(agents_state[agents_mask][:, -3:], dtype=float)

        if max_center_dist is not None:
            center_dist = np.linalg.norm(valid_states[:, :2] - np.array([[float(x), float(y)]], dtype=float), axis=-1)
            if center_dist.size == 0 or float(np.min(center_dist)) > float(max_center_dist):
                return None

        boxes = self._compute_boxes(valid_states, valid_statics)
        point = (float(x), float(y))
        for vid, box in zip(valid_ids, boxes):
            contour = np.array(box, dtype=np.float32)
            if cv2.pointPolygonTest(contour, point, measureDist=False) >= 0:
                return vid
        return None

    def _compute_boxes(self, valid_states: np.ndarray, valid_statics: np.ndarray) -> np.ndarray:
        # `get_rotated_box` is imported in RealtimeViewer module, use same geometry from state vectors.
        from cutils import get_rotated_box

        return get_rotated_box(
            valid_states[:, 0],
            valid_states[:, 1],
            valid_statics[:, 0],
            valid_statics[:, 1],
            valid_states[:, 2],
        )
    
    @staticmethod
    def _rectangles_overlap(box_a: np.ndarray, box_b: np.ndarray) -> bool:
        cnt_a = np.array(box_a, dtype=np.float32)
        cnt_b = np.array(box_b, dtype=np.float32)
        inter_area, _ = cv2.intersectConvexConvex(cnt_a, cnt_b)
        return float(inter_area) > 1e-6

    def _can_place_vehicle(self, x: float, y: float, heading: float, length: float, width: float) -> bool:
        magnification = 1.0
        collision_threshold = np.array([1.0, 0.8], dtype=np.float64)

        agent_ids, agents_state, agents_mask = self.agent_record[-1]
        if not isinstance(agent_ids, list):
            agent_ids = [agent_ids]
        agents_mask = np.array(agents_mask).reshape(-1).astype(bool)
        if not np.any(agents_mask):
            return True

        valid_states = np.array(agents_state[agents_mask][:, :3], dtype=float)
        valid_statics = np.array(agents_state[agents_mask][:, -3:], dtype=float)
        if valid_states.shape[0] == 0:
            return True

        expanded_existing = valid_statics.copy()
        expanded_existing[:, 0] = expanded_existing[:, 0] * magnification + collision_threshold[0]
        expanded_existing[:, 1] = expanded_existing[:, 1] * magnification + collision_threshold[1]
        existing_boxes = self._compute_boxes(valid_states, expanded_existing)

        from cutils import get_rotated_box

        expanded_length = float(length) * magnification + float(collision_threshold[0])
        expanded_width = float(width) * magnification + float(collision_threshold[1])
        new_box = get_rotated_box(
            np.array([x], dtype=float),
            np.array([y], dtype=float),
            np.array([expanded_length], dtype=float),
            np.array([expanded_width], dtype=float),
            np.array([heading], dtype=float),
        )[0]

        for box in existing_boxes:
            if self._rectangles_overlap(new_box, box):
                return False
        return True

    def _spawn_from_click(
        self,
        click_x: float,
        click_y: float,
        scale: float,
        tx: float,
        ty: float,
        image_w: int,
        image_h: int,
        spawn_mode: str,
        speed: float | None,
        dry_run: bool = False,
    ):
        if self.viewer is None:
            raise RuntimeError("Viewer is not enabled")
        if scale <= 0:
            raise ValueError("Invalid scale")

        img_x = (float(click_x) - float(tx)) / float(scale)
        img_y = (float(click_y) - float(ty)) / float(scale)

        world_xy = self.viewer.image_pixel_to_world(img_x, img_y)
        lane_id, lane_dist = self.map.get_current_lane(world_xy)
        if float(lane_dist) > float(self.click_spawn_max_lane_distance):
            raise ValueError("CLICK_OUT_OF_RANGE")
        lane_pose = self.map.project_to_polyline(world_xy, lane_id)
        lane_x, lane_y, lane_heading = lane_pose[0], lane_pose[1], lane_pose[2]

        if not self._can_place_vehicle(float(lane_x), float(lane_y), float(lane_heading), 3.8, 1.8):
            raise ValueError("Spawn rejected: collision check failed with existing vehicles")

        if dry_run:
            return None

        if spawn_mode == "static":
            return self.add_vehicle(x=lane_x, y=lane_y, heading=lane_heading, vx=0.0, vy=0.0, static=True)

        move_speed = float(speed if speed is not None else self.default_spawn_speed)
        self.default_spawn_speed = move_speed
        return self.add_vehicle(
            x=lane_x,
            y=lane_y,
            heading=lane_heading,
            vx=move_speed * math.cos(lane_heading),
            vy=move_speed * math.sin(lane_heading),
            static=False,
            init_step=self.history_step,
        )

    def _load_pkl(self, raw_path: str) -> dict:
        p = self._resolve_workspace_path(raw_path)
        if not p.exists():
            raise FileNotFoundError(f"PKL file not found: {p}")
        with open(p, "rb") as f:
            return pickle.load(f)

    def _advanced_add_from_pkl(self, raw_path: str, vehicle_id=None):
        data = self._load_pkl(raw_path)
        vid_filter = self._normalize_vehicle_id(vehicle_id)

        added = 0
        if isinstance(data, dict) and "ops" in data:
            for op in data.get("ops", []):
                if str(op.get("type", "")).lower() != "add":
                    continue
                vid = self._normalize_vehicle_id(op.get("vehicle_id"))
                if vid_filter is not None and vid != vid_filter:
                    continue
                states = np.array(op.get("states", []), dtype=float)
                if states.ndim != 2 or states.shape[1]:
                    continue
                lwh = np.array(op.get("static_lwh", [3.8, 1.8, 1.5]), dtype=float)
                if vid is None:
                    vid = max(self.agent_record._id_agent_mapping) + 1
                spawn_state = np.array(states[-1, :7], dtype=float)
                if not self._can_place_vehicle(float(spawn_state[0]), float(spawn_state[1]), float(spawn_state[2]), float(lwh[0]), float(lwh[1])):
                    print(f"[UI] Skip add op for vehicle {vid}: collision check failed")
                    continue
                self.agent_record.add_agents_from_history_states(
                    vehicles_id=vid,
                    vehicles_states=states[:, :7],
                    vehicles_static=lwh,
                    vehicles_type=RoutedVehicle,
                )
                if bool(op.get("static", False)):
                    self.static_vehicle_ids.add(vid)
                added += 1
            return added

        if not isinstance(data, dict):
            return added
        if "vehicle_id_per_step" not in data or "vehicle_state_per_step" not in data:
            return added

        all_ids = []
        for ids in data["vehicle_id_per_step"]:
            all_ids.extend(ids)
        unique_ids = list(dict.fromkeys(all_ids))

        if vid_filter is not None:
            unique_ids = [vid_filter]

        static_attr = data.get("vehicle_static_attribute", {})
        for vid in unique_ids:
            frames = []
            for ids, states in zip(data["vehicle_id_per_step"], data["vehicle_state_per_step"]):
                if vid in ids:
                    idx = ids.index(vid)
                    frames.append(np.array(states[idx], dtype=float)[:7])
                    if len(frames) >= self.history_step:
                        break
            if len(frames) == 0:
                continue
            lwh = np.array(static_attr.get(vid, [3.8, 1.8, 1.5]), dtype=float)
            spawn_state = np.array(frames[-1], dtype=float)
            if not self._can_place_vehicle(float(spawn_state[0]), float(spawn_state[1]), float(spawn_state[2]), float(lwh[0]), float(lwh[1])):
                print(f"[UI] Skip add from scenario for vehicle {vid}: collision check failed")
                continue
            self.agent_record.add_agents_from_history_states(
                vehicles_id=vid,
                vehicles_states=np.array(frames, dtype=float),
                vehicles_static=lwh,
                vehicles_type=RoutedVehicle,
            )
            added += 1
        return added

    def _advanced_control_from_pkl(self, raw_path: str, vehicle_id=None, horizon: int = 20):
        data = self._load_pkl(raw_path)
        vid_filter = self._normalize_vehicle_id(vehicle_id)
        horizon = max(1, int(horizon))

        controlled = 0
        if isinstance(data, dict) and "ops" in data:
            for op in data.get("ops", []):
                if str(op.get("type", "")).lower() != "control":
                    continue
                vid = self._normalize_vehicle_id(op.get("vehicle_id"))
                if vid is None:
                    continue
                if vid_filter is not None and vid != vid_filter:
                    continue
                states = np.array(op.get("states", []), dtype=float)
                if states.ndim != 2 or states.shape[1] < 7:
                    continue
                self._future_behavior_overrides[vid] = states[:horizon, :7]
                controlled += 1
            return controlled

        if not isinstance(data, dict):
            return controlled
        if "vehicle_id_per_step" not in data or "vehicle_state_per_step" not in data:
            return controlled

        candidate_ids = []
        if vid_filter is not None:
            candidate_ids = [vid_filter]
        else:
            if self.current_step + 1 < len(data["vehicle_id_per_step"]):
                candidate_ids = list(data["vehicle_id_per_step"][self.current_step + 1])

        for vid in candidate_ids:
            seq = []
            start = max(self.current_step + 1, 0)
            end = min(start + horizon, len(data["vehicle_id_per_step"]))
            for step in range(start, end):
                ids = data["vehicle_id_per_step"][step]
                states = data["vehicle_state_per_step"][step]
                if vid in ids:
                    idx = ids.index(vid)
                    seq.append(np.array(states[idx], dtype=float)[:7])
            if len(seq) == 0:
                continue
            self._future_behavior_overrides[vid] = np.array(seq, dtype=float)
            controlled += 1
        return controlled

    def _report_action_error(self, message: str):
        if self.web_viewer is not None:
            self.web_viewer.set_status_fields({
                "last_error": str(message),
                "last_error_nonce": time.time(),
            })

    def _clear_action_error(self):
        if self.web_viewer is not None:
            self.web_viewer.set_status_fields({"last_error": ""})

    def _publish_render_now(self):
        if not self.visualize or self.viewer is None:
            return
        if self._render_queue is not None:
            while True:
                try:
                    _ = self._render_queue.get_nowait()
                except Exception:
                    break
        payload = self._build_render_payload(paused_override=self.paused)
        if payload is not None:
            self._render_and_publish(payload)

    def _process_web_actions(self):
        if self.web_viewer is None:
            return

        allow_when_running = {"set_rate", "toggle_vehicle_id"}

        while True:
            action = self.web_viewer.pop_action()
            if action is None:
                break

            act_type = str(action.get("type", "")).strip().lower()
            sync_id = action.get("_sync_id", None)
            dry_run = bool(action.get("dry_run", False))
            result = {"ok": True}

            self._clear_action_error()

            if (not self.paused) and act_type not in allow_when_running:
                result = {
                    "ok": False,
                    "error": "This action is only available while paused",
                }
                self.web_viewer.set_action_result(sync_id, result)
                continue

            try:
                if act_type == "switch_map":
                    rel_map = str(action.get("map_path", "")).strip()
                    map_abs = self._resolve_workspace_path(rel_map)
                    if not str(map_abs).startswith(str(self.map_root)):
                        raise ValueError("Map path must be inside assets/map")
                    if dry_run:
                        result = {"ok": True, "message": "Map path is valid"}
                    else:
                        self.reload_map(str(map_abs))
                        result = {"ok": True, "message": "Map switched"}

                elif act_type == "set_rate":
                    lane_id = action.get("lane_id", "all")
                    prob = float(action.get("prob", self.default_arrival_rate))
                    if dry_run:
                        result = {"ok": True, "message": "Arrival rate input is valid"}
                    elif isinstance(lane_id, str) and lane_id.strip().lower() == "all":
                        self.set_all_lane_arrival_rate(prob)
                        result = {"ok": True, "message": "Arrival rate updated for all start lanes"}
                    else:
                        self.set_lane_arrival_rate(self._normalize_vehicle_id(lane_id), prob)
                        result = {"ok": True, "message": "Arrival rate updated"}

                elif act_type == "set_default_spawn_speed":
                    speed = max(0.0, float(action.get("speed", self.default_spawn_speed)))
                    if dry_run:
                        result = {"ok": True, "message": "Spawn speed is valid"}
                    else:
                        self.default_spawn_speed = speed
                        result = {"ok": True, "message": "Default spawn speed updated"}

                elif act_type == "add_vehicle_manual":
                    x = float(action.get("x"))
                    y = float(action.get("y"))
                    heading = float(action.get("heading"))
                    spawn_mode = str(action.get("spawn_mode", "moving")).strip().lower()
                    speed = float(action.get("speed", self.default_spawn_speed))
                    if not np.isfinite([x, y, heading]).all():
                        raise ValueError("x/y/heading must be finite numbers")
                    if not self._can_place_vehicle(x, y, heading, 3.8, 1.8):
                        raise ValueError("Spawn rejected: collision check failed with existing vehicles")
                    if dry_run:
                        result = {"ok": True, "message": "Position is valid. Confirm to add vehicle."}
                    elif spawn_mode == "static":
                        self.add_vehicle(x=x, y=y, heading=heading, vx=0.0, vy=0.0, static=True)
                        result = {"ok": True, "message": "Static vehicle added"}
                    else:
                        self.default_spawn_speed = max(0.0, speed)
                        self.add_vehicle(
                            x=x,
                            y=y,
                            heading=heading,
                            vx=self.default_spawn_speed * math.cos(heading),
                            vy=self.default_spawn_speed * math.sin(heading),
                            static=False,
                            init_step=self.history_step,
                        )
                        result = {"ok": True, "message": "Moving vehicle added"}

                elif act_type == "remove_vehicle":
                    vid = self._normalize_vehicle_id(action.get("vehicle_id"))
                    if vid is None:
                        raise ValueError("vehicle_id is required")
                    if vid not in self.agent_record._id_agent_mapping:
                        raise ValueError(f"Vehicle {vid} not found")
                    if dry_run:
                        result = {"ok": True, "message": f"Vehicle {vid} found. Confirm to delete."}
                    else:
                        self.remove_vehicle(vid)
                        result = {"ok": True, "message": f"Vehicle {vid} removed"}

                elif act_type == "toggle_vehicle_id":
                    if self.viewer is None:
                        raise RuntimeError("Viewer is not enabled")
                    if dry_run:
                        result = {"ok": True, "message": "Toggle is available"}
                    else:
                        self.viewer.plot_id = not self.viewer.plot_id
                        print(f"Vehicle ID display set to {self.viewer.plot_id}")
                        result = {
                            "ok": True,
                            "message": f"Vehicle ID display {'ON' if self.viewer.plot_id else 'OFF'}",
                        }

                elif act_type == "toggle_vehicle_control_mode":
                    vid = self._normalize_vehicle_id(action.get("vehicle_id"))
                    if vid is None:
                        raise ValueError("vehicle_id is required")
                    if vid not in self.agent_record._id_agent_mapping:
                        raise ValueError(f"Vehicle {vid} not found")

                    will_be_static = vid not in self.static_vehicle_ids
                    target_mode = "static" if will_be_static else "simulator control"
                    if dry_run:
                        result = {
                            "ok": True,
                            "message": f"Vehicle {vid} found. Confirm to switch to {target_mode}.",
                        }
                    else:
                        vid, is_static = self._toggle_vehicle_control_mode(vid)
                        mode_msg = "static (stay at current position)" if is_static else "simulator control"
                        result = {"ok": True, "message": f"Vehicle {vid} switched to {mode_msg}"}

                elif act_type == "canvas_click":
                    click_mode = str(action.get("click_mode", "none")).strip().lower()
                    if click_mode == "spawn":
                        self._spawn_from_click(
                            click_x=float(action.get("click_x", 0.0)),
                            click_y=float(action.get("click_y", 0.0)),
                            scale=float(action.get("scale", 1.0)),
                            tx=float(action.get("tx", 0.0)),
                            ty=float(action.get("ty", 0.0)),
                            image_w=int(action.get("image_w", self.viewer.get_mode_canvas_size()[0] if self.viewer else 1024)),
                            image_h=int(action.get("image_h", self.viewer.get_mode_canvas_size()[1] if self.viewer else 1024)),
                            spawn_mode=str(action.get("spawn_mode", "moving")).strip().lower(),
                            speed=float(action.get("speed", self.default_spawn_speed)),
                            dry_run=dry_run,
                        )
                        result = {
                            "ok": True,
                            "message": "Clicked location is valid for spawn. Confirm to add vehicle."
                            if dry_run
                            else "Vehicle added from click",
                        }
                    elif click_mode == "delete":
                        if self.viewer is None:
                            raise RuntimeError("Viewer is not enabled")
                        img_x = (float(action.get("click_x", 0.0)) - float(action.get("tx", 0.0))) / max(
                            float(action.get("scale", 1.0)), 1e-6
                        )
                        img_y = (float(action.get("click_y", 0.0)) - float(action.get("ty", 0.0))) / max(
                            float(action.get("scale", 1.0)), 1e-6
                        )
                        world_xy = self.viewer.image_pixel_to_world(img_x, img_y)
                        vid = self._find_vehicle_at_world(
                            float(world_xy[0]),
                            float(world_xy[1]),
                            max_center_dist=self.click_delete_max_vehicle_distance,
                        )
                        if vid is None:
                            raise ValueError(
                                f"No vehicle found near click point (within {self.click_delete_max_vehicle_distance:.1f}m)"
                            )
                        if dry_run:
                            result = {"ok": True, "message": f"Vehicle {vid} selected. Confirm to delete."}
                        else:
                            self.remove_vehicle(vid)
                            result = {"ok": True, "message": f"Vehicle {vid} removed from click"}

                    elif click_mode == "toggle_control":
                        if self.viewer is None:
                            raise RuntimeError("Viewer is not enabled")
                        img_x = (float(action.get("click_x", 0.0)) - float(action.get("tx", 0.0))) / max(
                            float(action.get("scale", 1.0)), 1e-6
                        )
                        img_y = (float(action.get("click_y", 0.0)) - float(action.get("ty", 0.0))) / max(
                            float(action.get("scale", 1.0)), 1e-6
                        )
                        world_xy = self.viewer.image_pixel_to_world(img_x, img_y)
                        vid = self._find_vehicle_at_world(
                            float(world_xy[0]),
                            float(world_xy[1]),
                            max_center_dist=self.click_delete_max_vehicle_distance,
                        )
                        if vid is None:
                            raise ValueError(
                                f"No vehicle found near click point (within {self.click_delete_max_vehicle_distance:.1f}m)"
                            )
                        will_be_static = vid not in self.static_vehicle_ids
                        target_mode = "static" if will_be_static else "simulator control"
                        if dry_run:
                            result = {
                                "ok": True,
                                "message": f"Vehicle {vid} selected. Confirm to switch to {target_mode}.",
                            }
                        else:
                            vid, is_static = self._toggle_vehicle_control_mode(vid)
                            mode_msg = "static (stay at current position)" if is_static else "simulator control"
                            result = {
                                "ok": True,
                                "message": f"Vehicle {vid} switched to {mode_msg} from click",
                            }

                elif act_type == "advanced_add_from_pkl":
                    added = self._advanced_add_from_pkl(
                        raw_path=str(action.get("pkl_path", "")).strip(),
                        vehicle_id=action.get("vehicle_id", None),
                    )
                    print(f"[UI] Added {added} vehicle(s) from pkl")
                    result = {"ok": True, "message": f"Added {added} vehicle(s) from PKL"}

                elif act_type == "advanced_control_from_pkl":
                    controlled = self._advanced_control_from_pkl(
                        raw_path=str(action.get("pkl_path", "")).strip(),
                        vehicle_id=action.get("vehicle_id", None),
                        horizon=int(action.get("horizon", 20)),
                    )
                    print(f"[UI] Injected control for {controlled} vehicle(s)")
                    result = {"ok": True, "message": f"Injected control for {controlled} vehicle(s)"}

                else:
                    result = {"ok": False, "error": f"Unknown action type: {act_type}"}

            except Exception as exc:
                print(f"[UI] action '{act_type}' failed: {exc}")
                err = str(exc)
                if err != "CLICK_OUT_OF_RANGE":
                    self._report_action_error(err)
                result = {"ok": False, "error": err}

            if result.get("ok", False):
                if self.paused:
                    self._publish_render_now()
                else:
                    self._schedule_render(force=True, paused_override=self.paused)

            self.web_viewer.set_action_result(sync_id, result)

    def _command_loop(self):

        print("\n=== Simulation Paused (Web UI enabled) ===")
        while self.paused and not self._quit_requested:
            self._publish_render_now()

            if self.web_viewer is not None:
                self.web_viewer.set_paused(True)
                self._process_web_actions()
                if self.web_viewer.resume_requested:
                    self.paused = False
                    break

            stdin_line = _check_stdin()
            if stdin_line:
                cmd = parse_command(stdin_line)
                self._execute_command(cmd)

            time.sleep(0.03)

    def _execute_command(self, cmd):
        kind = cmd.kind
        args = cmd.args

        if kind == "noop":
            return

        if kind == "help":
            print(HELP_TEXT)

        elif kind == "resume":
            self.paused = False

        elif kind == "quit":
            self._quit_requested = True
            self.paused = False

        elif kind == "status":
            print(f"  Current step:  {self.current_step}")
            print(f"  Active vehicles: {self._count_active_vehicles()}")
            print(f"  Static vehicles:   {self.static_vehicle_ids or 'none'}")
            print(f"  Lane overrides: {self.lane_arrival_rates or 'none'}")
            print(f"  Viewer mode:   {self.viewer.mode if self.viewer else 'off'}")

        elif kind == "step":
            n = args.get("n", 1)
            self._step_budget = n
            self.paused = False

        elif kind == "map":
            self.reload_map(args["path"])

        elif kind == "rate":
            self.set_lane_arrival_rate(args["lane_id"], args["prob"])

        elif kind == "add":
            self.add_vehicle(
                x=args["x"],
                y=args["y"],
                heading=args["heading"],
                vx=args["vx"],
                vy=args["vy"],
                static=args["static"],
                length=args["length"],
                width=args["width"],
                height=args["height"],
            )

        elif kind == "remove":
            self.remove_vehicle(args["vehicle_id"])

        elif kind == "view":
            mode = args["mode"]
            if mode == "overview":
                if self.viewer:
                    self.viewer.switch_mode("overview")
                    print("Switched to overview mode.")
            elif mode == "region":
                center = np.array([args["x"], args["y"]])
                if self.viewer:
                    self.viewer.switch_mode("region", region_center=center)
                    print(f"Switched to region mode, center=({args['x']}, {args['y']})")
            elif mode == "region_full":
                if self.viewer:
                    self.viewer.switch_mode("region_full")
                    print("Switched to region_full mode (full-map detail).")

            if self.viewer is not None:
                if self.paused:
                    self._publish_render_now()
                else:
                    self._schedule_render(force=True, paused_override=self.paused)

    def _toggle_view(self):
        if self.viewer is None:
            return

        if self.viewer.mode == "overview":
            self.viewer.switch_mode("region")
            print("Switched to region-centric mode.")
        elif self.viewer.mode == "region":
            self.viewer.switch_mode("region_full")
            print("Switched to region_full mode (full-map detail).")
        else:
            self.viewer.switch_mode("overview")
            print("Switched to overview mode.")
