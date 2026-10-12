"""Runtime integration for heterogeneous CityNDE traffic participants.

This module is imported only after the configured CityNDE source root has been
added to ``sys.path``. It deliberately keeps pedestrians outside the neural
agent record and injects them only into the rule-based safety layer.
"""
from __future__ import annotations

import math
import pickle
from typing import Any

import numpy as np
import torch

from backend.algorithms.citynde.map_signalization import (
    signalize_unsignalized_citynde_map,
)
from backend.algorithms.citynde.mixed_traffic_core import (
    CyclistRouteCorridor,
    CrosswalkGeometry,
    RulePedestrian,
    SignalTimingPlan,
    agent_state_at_absolute_step,
    build_cyclist_route_corridor,
    constant_speed_history,
    oriented_boxes_overlap,
    oriented_trajectory_has_clearance,
    pedestrian_stream_offset,
    project_point_to_segment,
    rollback_state_before_oriented_obstacles,
    sample_vehicle_profile,
    select_rightmost_route,
    shift_signal_stop_points,
    stop_trajectory_before_oriented_obstacle,
)
from backend.scene.semantic_map import build_citynde_semantics

from csim.agent import RoadUserState, RoutedVehicle
from csim.controller import RuleEnhancedController
from csim.controller.safety_utils import search_collision_free_modes
from csim.simulator.interactive_simulator import InteractiveRouteTLSimulator


class RoutedNonMotorizedVehicle(RoutedVehicle):
    """Model-controlled small road user constrained to rightmost lanes/crosswalks."""

    actor_type = "cyclist"
    vehicle_class = "non_motorized"
    rightmost_only = True
    crosswalk_required = True

    def __init__(self, *args, static_lwh: np.ndarray | None = None, **kwargs):
        self._rightmost_route_selector = None
        self._crossing_corridor: CyclistRouteCorridor | None = None
        self._corridor_route_signature: tuple[str, ...] = ()
        self._corridor_locked = False
        if static_lwh is None:
            static_lwh = np.asarray([1.85, 0.65, 1.55], dtype=np.float64)
        super().__init__(*args, static_lwh=static_lwh, **kwargs)

    def set_rightmost_route_selector(self, selector) -> None:
        self._rightmost_route_selector = selector

    def assign_route(self, route):
        candidate = list(route or [])
        current_route = list(getattr(self, "route", []) or [])
        if getattr(self, "_corridor_locked", False) and current_route:
            if not candidate or candidate[0] not in current_route:
                return
        if candidate and self._rightmost_route_selector is not None:
            selected = list(self._rightmost_route_selector(candidate[0]) or [])
            if not selected:
                return
            candidate = selected
        signature = tuple(map(str, candidate))
        if signature != getattr(self, "_corridor_route_signature", ()):
            self._crossing_corridor = None
            self._corridor_locked = False
        super().assign_route(candidate)

    def assign_left_route(self, left_route):
        # RouteTLScenarioManager normally exposes a left-lane candidate to the
        # neural model. A non-motorized road user must keep its rightmost route.
        self.left_route = list(self.route)

    def assign_right_route(self, right_route):
        self.right_route = list(self.route)

    def set_crossing_corridor(self, corridor: CyclistRouteCorridor | None) -> None:
        self._crossing_corridor = corridor
        self._corridor_route_signature = tuple(map(str, self.route))
        self._corridor_locked = bool(corridor is not None and corridor.passages)


class MixedTrafficRuleEnhancedController(RuleEnhancedController):
    """CNDE controller with explicit signal timing and fixed pedestrian obstacles."""

    def __init__(
        self,
        *args,
        signal_plan: SignalTimingPlan | None = None,
        inference_batch_size: int = 128,
        inference_precision: str = "fp32",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.signal_plan = signal_plan or SignalTimingPlan(float(getattr(self, "control_resolution", 0.1)))
        self.inference_batch_size = max(1, int(inference_batch_size))
        self.inference_precision = str(inference_precision or "fp32").strip().lower()
        if self.inference_precision not in {"fp32", "tf32"}:
            raise ValueError(f"Unsupported CityNDE inference precision: {self.inference_precision}")
        self.tl_phase_step = list(self.signal_plan.stage_steps)
        self.cum_phase_step = np.cumsum(self.tl_phase_step)
        self.external_safety_participants: list[dict[str, Any]] = []
        self.cyclist_trajectory_constraint = None
        self.pedestrian_conflict_count = 0
        self.pedestrian_correction_count = 0

    def step(self, formatted_scenario: dict, batch_size: int | None = None) -> dict:
        effective_batch_size = self.inference_batch_size
        if batch_size is not None:
            effective_batch_size = min(effective_batch_size, max(1, int(batch_size)))
        return super().step(formatted_scenario, batch_size=effective_batch_size)

    def set_external_safety_participants(self, participants: list[dict[str, Any]] | None = None):
        self.external_safety_participants = list(participants or [])

    def set_cyclist_trajectory_constraint(self, constraint=None) -> None:
        self.cyclist_trajectory_constraint = constraint

    def batch_control(self, scenario: dict, batch_size: int) -> dict:
        # CityNDE's upstream inference loop does not disable autograd, so every
        # sub-batch otherwise retains a full backward graph until concatenation.
        previous_matmul_precision = torch.get_float32_matmul_precision()
        if self.inference_precision == "tf32":
            torch.set_float32_matmul_precision("high")
        try:
            with torch.inference_mode():
                output = super().batch_control(scenario, batch_size)
        finally:
            torch.set_float32_matmul_precision(previous_matmul_precision)
        raw_phases = scenario.get("all_dynamic_polyline_phase")
        raw_light_ids = scenario.get("all_dynamic_polyline_id")
        phase_strings = list(raw_phases) if raw_phases is not None else []
        light_ids = list(raw_light_ids) if raw_light_ids is not None else []
        pred_step = int(output["pred_trajs"].shape[-2]) if "pred_trajs" in output else int(self.control_step)
        device = output["pred_trajs"].device if "pred_trajs" in output else torch.device("cuda")
        states = torch.zeros((len(phase_strings), pred_step, 4), dtype=torch.float32, device=device)
        current_step = int(scenario.get("current_step", 0))
        for light_index, phase in enumerate(phase_strings):
            phase = str(phase or "")
            for offset in range(pred_step):
                stage_index = self.signal_plan.stage_index(current_step + offset)
                value = phase[stage_index] if stage_index < len(phase) else "r"
                channel = 0 if value == "g" else 1 if value == "y" else 2
                states[light_index, offset, channel] = 1.0
        output["required_update_traffic_light_ids"] = scenario.get("required_update_traffic_light_ids", light_ids)
        output["dynamic_polyline_id"] = light_ids
        output["dynamic_polyline_states"] = states
        return output

    @staticmethod
    def _fit_trajectory(trajectory: np.ndarray, horizon: int) -> np.ndarray:
        values = np.asarray(trajectory, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] < 7 or len(values) == 0:
            raise ValueError("External safety trajectory must have shape (T, >=7)")
        values = values[:, :7]
        if len(values) >= horizon:
            return values[:horizon]
        return np.concatenate((values, np.repeat(values[-1:], horizon - len(values), axis=0)), axis=0)

    def _prepare_rule_forward_scenario(self, scenario):
        prepared = super()._prepare_rule_forward_scenario(scenario)
        # The upstream SafetyLayer otherwise keeps its five-frame default even
        # when the adapter consumes a longer model rollout. Its off-road check
        # evaluates four times this window, so the adapter caps control_step at
        # 20 against the model's native 80-frame prediction horizon.
        prepared["nn_once_forward_step"] = int(self.control_step)
        prepared["tl_location_states_start"] = shift_signal_stop_points(
            self.map_enhance,
            prepared["tl_location_id_list"],
            prepared["tl_location_states_start"],
        )
        original_ids = list(prepared["vehicle_ids_last_step"])
        normalized_ids = [str(vehicle_id) for vehicle_id in original_ids]
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("SafetyLayer actor IDs are ambiguous after string normalization")
        prepared["vehicle_ids_last_step"] = normalized_ids
        prepared["vehicle_routes"] = {
            str(vehicle_id): route for vehicle_id, route in prepared["vehicle_routes"].items()
        }
        prepared["vehicle_static_attributes"] = {
            str(vehicle_id): attributes
            for vehicle_id, attributes in prepared["vehicle_static_attributes"].items()
        }
        prepared["static_vehicle_ids_set"] = {
            str(vehicle_id) for vehicle_id in prepared["static_vehicle_ids_set"]
        }
        participants = self.external_safety_participants
        if not participants:
            prepared["external_safety_ids"] = []
            return prepared

        horizon = int(prepared["global_states"].shape[1])
        ids = []
        trajectories = []
        current_states = []
        centers = []
        for participant in participants:
            participant_id = str(participant["id"])
            trajectory = self._fit_trajectory(participant["trajectory"], horizon)
            current_value = participant.get("current_state")
            static_value = participant.get("static_lwh")
            current = np.asarray(trajectory[0] if current_value is None else current_value, dtype=np.float64).reshape(-1)[:7]
            static_lwh = np.asarray(
                [0.55, 0.55, 1.72] if static_value is None else static_value, dtype=np.float64
            )
            ids.append(participant_id)
            trajectories.append(trajectory)
            current_states.append(current)
            centers.append(current[:3])
            prepared["vehicle_static_attributes"][participant_id] = static_lwh
            prepared["vehicle_routes"][participant_id] = []
            prepared["static_vehicle_ids_set"].add(participant_id)

        prepared["global_states"] = np.concatenate((prepared["global_states"], np.stack(trajectories)), axis=0)
        prepared["vehicle_states_last_step"] = np.concatenate(
            (prepared["vehicle_states_last_step"], np.stack(current_states)), axis=0
        )
        prepared["centers"] = np.concatenate(
            (np.asarray(prepared["centers"], dtype=np.float64), np.stack(centers)), axis=0
        )
        prepared["vehicle_ids_last_step"] = list(prepared["vehicle_ids_last_step"]) + ids
        prepared["external_safety_ids"] = ids
        return prepared

    @staticmethod
    def _has_pedestrian_conflict(prepared: dict, pedestrian_ids: list[str]) -> bool:
        if not pedestrian_ids:
            return False
        ids = list(prepared["vehicle_ids_last_step"])
        trajectories = np.asarray(prepared["global_states"], dtype=np.float64)
        pedestrian_indices = [ids.index(pid) for pid in pedestrian_ids if pid in ids]
        vehicle_indices = [index for index, value in enumerate(ids) if value not in pedestrian_ids]
        for ped_index in pedestrian_indices:
            ped_dims = np.asarray(prepared["vehicle_static_attributes"][ids[ped_index]], dtype=float)[:2]
            for vehicle_index in vehicle_indices:
                vehicle_dims = np.asarray(prepared["vehicle_static_attributes"][ids[vehicle_index]], dtype=float)[:2]
                threshold = 0.5 * float(np.linalg.norm(ped_dims) + np.linalg.norm(vehicle_dims))
                distance = np.linalg.norm(
                    trajectories[ped_index, :, :2] - trajectories[vehicle_index, :, :2], axis=-1
                )
                if np.any(distance <= threshold):
                    return True
        return False

    def _safety_layer_forward(self, scenario):
        external_index = None
        external_trajectory = self.external_av_trajectory
        if self.external_av_id is not None and external_trajectory is not None:
            external_index = next(
                (
                    index
                    for index, vehicle_id in enumerate(scenario["vehicle_id"])
                    if str(vehicle_id) == str(self.external_av_id)
                ),
                None,
            )
            if external_index is not None and external_trajectory.ndim == 2:
                horizon = min(scenario["vehicle_states"].shape[1], external_trajectory.shape[0])
                dimensions = min(scenario["vehicle_states"].shape[2], external_trajectory.shape[1])
                scenario["vehicle_states"][external_index, :horizon, :dimensions] = torch.as_tensor(
                    external_trajectory[:horizon, :dimensions],
                    dtype=scenario["vehicle_states"].dtype,
                    device=scenario["vehicle_states"].device,
                )
        if self.cyclist_trajectory_constraint is not None:
            scenario = self.cyclist_trajectory_constraint(scenario)

        original_states = scenario["vehicle_states"].detach().cpu().numpy().copy()
        prepared = self._prepare_rule_forward_scenario(scenario)
        pedestrian_ids = list(prepared.pop("external_safety_ids", []))
        controlled_ids = list(pedestrian_ids)
        for vehicle_id in scenario["vehicle_id"]:
            agent = self.agent_enhance.get_agents(vehicle_id)
            if isinstance(agent, RoutedNonMotorizedVehicle):
                controlled_ids.append(str(vehicle_id))
        if external_index is not None:
            controlled_ids.append(str(scenario["vehicle_id"][external_index]))
        prepared["controlled_id"] = controlled_ids

        had_pedestrian_conflict = self._has_pedestrian_conflict(prepared, pedestrian_ids)
        if had_pedestrian_conflict:
            self.pedestrian_conflict_count += 1
        fallback_before = getattr(search_collision_free_modes, "approximate_fallback_count", 0)
        safety_result = self.rule_controller.forward(**prepared)
        fallback_after = getattr(search_collision_free_modes, "approximate_fallback_count", 0)
        self.safety_approximate_fallback_count += max(0, fallback_after - fallback_before)

        index_by_id = {str(vehicle_id): index for index, vehicle_id in enumerate(safety_result["vehicle_id"])}
        original_indices = [index_by_id[str(vehicle_id)] for vehicle_id in scenario["vehicle_id"]]
        scenario["vehicle_states"] = torch.from_numpy(safety_result["vehicle_states"][original_indices]).to(
            scenario["vehicle_states"].device
        )
        if had_pedestrian_conflict:
            updated_states = scenario["vehicle_states"].detach().cpu().numpy()
            comparison_horizon = min(original_states.shape[1], updated_states.shape[1])
            if not np.allclose(
                original_states[:, :comparison_horizon, :3],
                updated_states[:, :comparison_horizon, :3],
                atol=1e-4,
            ):
                self.pedestrian_correction_count += 1
        if external_index is not None:
            horizon = min(scenario["vehicle_states"].shape[1], external_trajectory.shape[0])
            dimensions = min(scenario["vehicle_states"].shape[2], external_trajectory.shape[1])
            scenario["vehicle_states"][external_index, :horizon, :dimensions] = torch.as_tensor(
                external_trajectory[:horizon, :dimensions],
                dtype=scenario["vehicle_states"].dtype,
                device=scenario["vehicle_states"].device,
            )
        original_id_by_text = {str(vehicle_id): vehicle_id for vehicle_id in scenario["vehicle_id"]}
        scenario["deadlock_vehicle_id"] = [
            original_id_by_text.get(str(vehicle_id), vehicle_id)
            for vehicle_id in safety_result["deadlock_vehicle_id"]
            if str(vehicle_id) not in pedestrian_ids
        ]
        return scenario


class MixedTrafficInteractiveSimulator(InteractiveRouteTLSimulator):
    """Interactive CityNDE simulator with heterogeneous vehicles and rule pedestrians."""

    def __init__(
        self,
        *args,
        mixed_traffic_enabled: bool = True,
        cyclist_ratio: float = 0.08,
        pedestrians_per_crosswalk: int = 2,
        max_pedestrians: int = 32,
        vehicle_size_mode: str = "mixed",
        initial_speed_mode: str = "citynde",
        mixed_traffic_seed: int = 42,
        signalize_unsignalized_map: bool = False,
        preserve_loaded_state: bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.signalization_report = signalize_unsignalized_citynde_map(
            self.map,
            enabled=bool(signalize_unsignalized_map),
        )
        self.mixed_traffic_enabled = bool(mixed_traffic_enabled)
        self.preserve_loaded_state = bool(preserve_loaded_state)
        self.cyclist_ratio = float(np.clip(cyclist_ratio, 0.0, 0.5))
        self.pedestrians_per_crosswalk = max(0, min(4, int(pedestrians_per_crosswalk)))
        self.max_pedestrians = max(0, int(max_pedestrians))
        self.vehicle_size_mode = "passenger_only" if str(vehicle_size_mode) == "passenger_only" else "mixed"
        self.initial_speed_mode = (
            "urban_sampled" if str(initial_speed_mode) == "urban_sampled" else "citynde"
        )
        self.initial_speed_summary: dict[str, float | int | str] = {
            "mode": self.initial_speed_mode,
            "count": 0,
        }
        self.mixed_rng = np.random.default_rng(int(mixed_traffic_seed))
        self.signal_plan = getattr(self.agent_controller, "signal_plan", SignalTimingPlan(self.sim_resolution))
        try:
            intersection_ids = list(self.map.get_intersection_polyline_id())
            self._movement_by_lane = self.map.get_intersection_polyline_direction(intersection_ids)
        except (AttributeError, TypeError, ValueError):
            self._movement_by_lane = {}
        self.semantic_map = (
            build_citynde_semantics(self.map)
            if self.mixed_traffic_enabled
            else {"crosswalks": [], "traffic_lights": [], "wait_lines": []}
        )
        self.crosswalks = [
            crosswalk
            for item in self.semantic_map.get("crosswalks") or []
            if (crosswalk := CrosswalkGeometry.from_semantic(item)) is not None and crosswalk.state_keys
        ]
        self.pedestrians: dict[str, RulePedestrian] = {}
        self._pedestrian_history: dict[int, dict[str, np.ndarray]] = {}
        self._restored_profile_ids: set[Any] = set()
        self._cyclist_counter = 0
        self.cyclist_crosswalk_corrections = 0
        self.cyclist_route_corrections = 0
        self.cyclist_signal_stops = 0
        self.cyclist_corridors_built = 0
        self.cyclist_pedestrian_conflicts = 0
        self.cyclist_pedestrian_yields = 0
        self.cyclist_av_conflicts = 0
        self.cyclist_av_yields = 0
        self.runtime_cyclist_safety_corrections = 0
        self.runtime_pedestrian_safety_blocks = 0
        self.runtime_unresolved_vulnerable_conflicts = 0
        self.invalid_spawn_rejections = 0
        self.nonfinite_agent_repairs = 0
        self.nonfinite_agent_removals = 0
        self._configure_signal_phases()
        if hasattr(self.agent_controller, "set_cyclist_trajectory_constraint"):
            self.agent_controller.set_cyclist_trajectory_constraint(
                self._constrain_cyclist_predictions
            )

    @staticmethod
    def _agent_actor_type(agent: Any) -> str:
        return str(getattr(agent, "actor_type", "vehicle"))

    def _configure_signal_phases(self) -> None:
        traffic_light_ids = list(self.map.get_intersection_polyline_id())
        if not traffic_light_ids:
            return
        directions = self.map.get_intersection_polyline_direction(traffic_light_ids)
        for lane_id in traffic_light_ids:
            movement = directions.get(lane_id)
            if not movement:
                lane = self.map.polyline_dict[lane_id]
                heading = float(np.asarray(lane.heading).reshape(-1)[0])
                movement = "ew_s" if abs(math.cos(heading)) >= abs(math.sin(heading)) else "ns_s"
            self.map.polyline_dict[lane_id].phase = self.signal_plan.phase_string(movement)

    def _next_vehicle_id(self) -> int:
        numeric = [value for value in self.agent_record._id_agent_mapping if isinstance(value, (int, np.integer))]
        return int(max(numeric) + 1) if numeric else 0

    def _next_cyclist_id(self) -> str:
        while True:
            candidate = f"cyclist-{self._cyclist_counter}"
            self._cyclist_counter += 1
            if candidate not in self.agent_record._id_agent_mapping:
                return candidate

    def _is_rightmost_lane(self, lane_id: Any) -> bool:
        lane = self.map.polyline_dict.get(lane_id)
        if lane is None:
            return False
        right_ids = list(getattr(lane, "right_lanes_id", []) or [])
        return not any(candidate in self.map.polyline_dict and self.map.is_lane_center(candidate) for candidate in right_ids)

    def _route_is_straight_compatible(self, route: list[Any]) -> bool:
        movements = [
            self.signal_plan.normalize_movement(self._movement_by_lane.get(lane_id))
            for lane_id in route
            if self._movement_by_lane.get(lane_id)
        ]
        return not movements or all(movement.endswith("_s") for movement in movements)

    def _spawn_clearance_ok(
        self,
        pose: np.ndarray,
        *,
        length: float,
        width: float,
        margin: float = 1.5,
    ) -> bool:
        x, y, heading = map(float, pose[:3])
        current_step = int(getattr(self.agent_record, "current_step", -1))
        try:
            active_ids = list(
                self.agent_record.get_valid_agent_ids(timestep=current_step)
            )
        except Exception:
            active_ids = []
        for agent_id in active_ids:
            agent = self.agent_record.get_agents(agent_id)
            other = agent_state_at_absolute_step(agent, current_step)
            if other is None:
                continue
            other_lwh = np.asarray(getattr(agent, "static_lwh", [3.8, 1.8, 1.5]), dtype=float)
            if oriented_boxes_overlap(
                [x, y, heading],
                [length, width],
                other[:3],
                other_lwh[:2],
                margin=margin,
            ):
                return False
        clearance_radius = 0.5 * math.hypot(length, width) + 0.5 * math.hypot(
            RulePedestrian.length, RulePedestrian.width
        ) + margin
        return all(
            float(np.linalg.norm(pedestrian.position() - pose[:2])) > clearance_radius
            for pedestrian in self.pedestrians.values()
        )

    def _spawn_history_clearance_ok(
        self,
        states: np.ndarray,
        *,
        length: float,
        width: float,
        margin: float = 1.0,
    ) -> bool:
        values = np.asarray(states, dtype=np.float64)
        current_step = int(getattr(self.agent_record, "current_step", -1))
        start_step = current_step - len(values) + 1
        obstacles_per_step = []
        for offset in range(len(values)):
            absolute_step = start_step + offset
            obstacles = []
            try:
                active_ids = list(
                    self.agent_record.get_valid_agent_ids(timestep=absolute_step)
                )
            except Exception:
                active_ids = []
            for agent_id in active_ids:
                agent = self.agent_record.get_agents(agent_id)
                other = agent_state_at_absolute_step(agent, absolute_step)
                if other is None:
                    continue
                other_lwh = np.asarray(
                    getattr(agent, "static_lwh", [3.8, 1.8, 1.5]),
                    dtype=float,
                )
                obstacles.append((other[:3], other_lwh[:2]))
            for pedestrian_state in (
                getattr(self, "_pedestrian_history", {}).get(absolute_step, {}).values()
            ):
                pedestrian_state = np.asarray(pedestrian_state, dtype=np.float64)
                if pedestrian_state.size >= 3 and np.isfinite(pedestrian_state[:3]).all():
                    obstacles.append(
                        (
                            pedestrian_state[:3],
                            [RulePedestrian.length, RulePedestrian.width],
                        )
                    )
            obstacles_per_step.append(obstacles)
        return oriented_trajectory_has_clearance(
            values,
            [length, width],
            obstacles_per_step,
            margin=margin,
        )

    def _spawn_actor_on_lane(
        self,
        lane_id: Any,
        *,
        cyclist: bool,
        init_step: int,
        speed: float,
        longitudinal: float = 5.0,
    ) -> bool:
        lane_chain = self.map.get_lane_chain(lane_id, max_depth=10)
        lane_length = float(self.map.polyline_length(lane_chain)) if lane_chain else 0.0
        if not lane_chain or not math.isfinite(lane_length) or lane_length - longitudinal < 20.0:
            if lane_chain and not math.isfinite(lane_length):
                self.invalid_spawn_rejections += 1
            return False
        pose = np.asarray(self.map.polyline_relative_pos(lane_chain, lon=longitudinal), dtype=np.float64)
        if pose.size < 3 or not np.isfinite(pose[:3]).all() or not math.isfinite(float(speed)):
            self.invalid_spawn_rejections += 1
            return False
        profile = None if cyclist else sample_vehicle_profile(self.mixed_rng)
        spawn_lwh = (
            np.asarray([1.85, 0.65, 1.55], dtype=np.float64)
            if cyclist
            else profile.lwh
            if self.vehicle_size_mode == "mixed"
            else np.asarray([3.8, 1.8, 1.5], dtype=np.float64)
        )
        if self.agent_record.simple_check_conflict(pose[:2], min_dist=3.0 if cyclist else 6.0, extra_only=True):
            return False
        if not self._spawn_clearance_ok(
            pose,
            length=float(spawn_lwh[0]),
            width=float(spawn_lwh[1]),
        ):
            return False
        states = RoadUserState()
        for index in range(init_step):
            dt = (init_step - index - 1) * self.sim_resolution
            states.update(
                [
                    pose[0] - speed * math.cos(pose[2]) * dt,
                    pose[1] - speed * math.sin(pose[2]) * dt,
                    pose[2],
                    speed * math.cos(pose[2]),
                    speed * math.sin(pose[2]),
                    0.0,
                    0.0,
                ]
            )
        if not np.isfinite(np.asarray(states.states, dtype=np.float64)).all():
            self.invalid_spawn_rejections += 1
            return False
        if not self._spawn_history_clearance_ok(
            states.states,
            length=float(spawn_lwh[0]),
            width=float(spawn_lwh[1]),
        ):
            return False
        if cyclist:
            route = select_rightmost_route(self.map, lane_id)
            if not route or not self._route_is_straight_compatible(route):
                return False
            actor = RoutedNonMotorizedVehicle(
                id=self._next_cyclist_id(),
                spawn_time_step=self.agent_record.current_step - init_step + 1,
                warm_up_states=states,
            )
            actor.set_rightmost_route_selector(lambda current_lane: select_rightmost_route(self.map, current_lane))
            actor.assign_route(route)
            actor.left_route = list(route)
            actor.right_route = list(route)
            self._ensure_cyclist_corridor(actor)
            self.agent_record.add_agents(actor)
        else:
            vehicle_id = self._next_vehicle_id()
            self.agent_record.add_agents_from_history_states(
                vehicles_id=vehicle_id,
                vehicles_states=states,
                vehicles_static=spawn_lwh,
                vehicles_type=RoutedVehicle,
            )
            added = self.agent_record.get_agents(vehicle_id)
            if added is not None:
                added.actor_type = "vehicle"
                added.vehicle_class = profile.name if self.vehicle_size_mode == "mixed" else "passenger"
        return True

    def _assign_existing_vehicle_profiles(self) -> None:
        for agent_id, agent in self.agent_record._id_agent_mapping.items():
            if isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            if agent_id in self._restored_profile_ids:
                continue
            profile = sample_vehicle_profile(self.mixed_rng)
            agent.static_lwh = (
                profile.lwh if self.vehicle_size_mode == "mixed" else np.asarray([3.8, 1.8, 1.5])
            )
            agent.actor_type = "vehicle"
            agent.vehicle_class = profile.name if self.vehicle_size_mode == "mixed" else "passenger"

    def _sample_initial_speed(self, agent: Any) -> float:
        if isinstance(agent, RoutedNonMotorizedVehicle):
            low, high = 3.0, 5.0
        else:
            vehicle_class = str(getattr(agent, "vehicle_class", "passenger")).lower()
            if vehicle_class in {"truck", "bus"}:
                low, high = 4.0, 6.0
            elif vehicle_class == "van":
                low, high = 4.5, 7.5
            elif vehicle_class == "suv":
                low, high = 5.0, 8.0
            else:
                low, high = 5.5, 9.0
        return float(self.mixed_rng.uniform(low, high))

    def _resample_random_initial_histories(self) -> None:
        if self.initial_speed_mode != "urban_sampled":
            return
        speeds = []
        for agent_id in self.agent_record.get_valid_agent_ids(timestep=-1):
            agent = self.agent_record.get_agents(agent_id)
            if agent is None:
                continue
            states = np.asarray(getattr(agent, "states", []), dtype=np.float64)
            if states.ndim != 2 or len(states) == 0 or states.shape[1] < 5:
                continue
            final_state = states[-1].copy()
            if not np.isfinite(final_state[:3]).all():
                continue
            speed = self._sample_initial_speed(agent)
            states[:, :] = constant_speed_history(states, speed, self.sim_resolution)
            speeds.append(speed)
        if speeds:
            self.initial_speed_summary = {
                "mode": self.initial_speed_mode,
                "count": len(speeds),
                "minimum_mps": round(float(np.min(speeds)), 4),
                "mean_mps": round(float(np.mean(speeds)), 4),
                "maximum_mps": round(float(np.max(speeds)), 4),
            }

    def _spawn_initial_cyclists(self) -> None:
        if not self.mixed_traffic_enabled or self.cyclist_ratio <= 0.0:
            return
        active_agents = [
            self.agent_record.get_agents(agent_id)
            for agent_id in self.agent_record.get_valid_agent_ids(timestep=-1)
        ]
        existing = sum(isinstance(agent, RoutedNonMotorizedVehicle) for agent in active_agents)
        motorized_count = len(active_agents) - existing
        target = int(round(motorized_count * self.cyclist_ratio / max(1.0 - self.cyclist_ratio, 1e-6)))
        if target <= 0 and motorized_count > 0:
            target = 1
        target = max(0, target - existing)
        lanes = [lane_id for lane_id in self.map.start_lane if self._is_rightmost_lane(lane_id)]
        self.mixed_rng.shuffle(lanes)
        spawned = 0
        for lane_id in lanes:
            if spawned >= target:
                break
            if self._spawn_actor_on_lane(
                lane_id,
                cyclist=True,
                init_step=self.history_step,
                speed=float(self.mixed_rng.uniform(3.0, 5.0)),
                longitudinal=float(self.mixed_rng.uniform(4.0, 12.0)),
            ):
                spawned += 1

    def _convert_initial_cyclists(self) -> None:
        if not self.mixed_traffic_enabled or self.cyclist_ratio <= 0.0:
            return
        active_ids = list(self.agent_record.get_valid_agent_ids(timestep=-1))
        existing = sum(
            isinstance(self.agent_record.get_agents(agent_id), RoutedNonMotorizedVehicle)
            for agent_id in active_ids
        )
        target = int(round(len(active_ids) * self.cyclist_ratio))
        if target <= existing:
            return
        candidates = []
        for agent_id in active_ids:
            agent = self.agent_record.get_agents(agent_id)
            if isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            try:
                lane_id, distance = self.map.get_current_lane(agent.states[-1, :2], float(agent.states[-1, 2]))
            except Exception:
                continue
            if float(distance) <= 2.5 and self._is_rightmost_lane(lane_id):
                route = select_rightmost_route(self.map, lane_id)
                if route and self._route_is_straight_compatible(route):
                    candidates.append((agent_id, lane_id, route))
        self.mixed_rng.shuffle(candidates)
        for agent_id, lane_id, route in candidates[: max(0, target - existing)]:
            agent = self.agent_record.get_agents(agent_id)
            agent.__class__ = RoutedNonMotorizedVehicle
            agent.set_rightmost_route_selector(
                lambda current_lane: select_rightmost_route(self.map, current_lane)
            )
            agent.static_lwh = np.asarray([1.85, 0.65, 1.55], dtype=np.float64)
            agent.actor_type = "cyclist"
            agent.vehicle_class = "non_motorized"
            if route:
                agent.assign_route(route)
                agent.left_route = list(agent.route)
                agent.right_route = list(agent.route)
                self._ensure_cyclist_corridor(agent)

    def _active_vehicle_positions(self) -> np.ndarray:
        try:
            _, states, mask = self.agent_record[-1]
            mask = np.asarray(mask).reshape(-1).astype(bool)
            return np.asarray(states, dtype=np.float64)[mask, :2]
        except Exception:
            return np.empty((0, 2), dtype=np.float64)

    def _activate_nearby_crosswalks(self, radius: float = 120.0) -> None:
        if not self.mixed_traffic_enabled or self.pedestrians_per_crosswalk <= 0 or not self.crosswalks:
            return
        positions = self._active_vehicle_positions()
        scored = []
        for crosswalk in self.crosswalks:
            center = (crosswalk.start + crosswalk.end) * 0.5
            distance = float(np.min(np.linalg.norm(positions - center, axis=-1))) if len(positions) else float(np.linalg.norm(center))
            if len(positions) and distance > radius:
                continue
            scored.append((distance, crosswalk.id, crosswalk))
        for _, _, crosswalk in sorted(scored):
            existing = sum(ped.crosswalk.id == crosswalk.id for ped in self.pedestrians.values())
            for local_index in range(existing, self.pedestrians_per_crosswalk):
                if len(self.pedestrians) >= self.max_pedestrians:
                    return
                pedestrian_id = f"pedestrian-{crosswalk.id}-{local_index}"
                self.pedestrians[pedestrian_id] = RulePedestrian(
                    pedestrian_id,
                    crosswalk,
                    direction=1 if local_index % 2 == 0 else -1,
                    speed=float(self.mixed_rng.uniform(1.15, 1.55)),
                    lateral_offset=pedestrian_stream_offset(crosswalk, local_index),
                    reaction_time=float(self.mixed_rng.uniform(0.35, 1.25)),
                )

    def _record_pedestrian_snapshot(self, step: int) -> None:
        self._pedestrian_history[int(step)] = {
            pedestrian_id: pedestrian.state_vector().copy()
            for pedestrian_id, pedestrian in self.pedestrians.items()
        }

    def _restore_pedestrians_from_source(self, source: dict[str, Any]) -> None:
        ids_per_step = list(source.get("pedestrian_id_per_step") or [])
        states_per_step = list(source.get("pedestrian_state_per_step") or [])
        if not ids_per_step or not states_per_step:
            return
        for step, (pedestrian_ids, pedestrian_states) in enumerate(
            zip(ids_per_step, states_per_step)
        ):
            values = np.asarray(pedestrian_states, dtype=np.float64)
            if not pedestrian_ids or values.size == 0:
                self._pedestrian_history[step] = {}
                continue
            values = values.reshape(len(pedestrian_ids), -1)
            self._pedestrian_history[step] = {
                str(pedestrian_id): values[index, :7].copy()
                for index, pedestrian_id in enumerate(pedestrian_ids)
                if values.shape[1] >= 7
            }

        latest_step = next(
            (
                step
                for step in range(min(len(ids_per_step), len(states_per_step)) - 1, -1, -1)
                if ids_per_step[step] and len(np.asarray(states_per_step[step]).reshape(-1))
            ),
            None,
        )
        if latest_step is None:
            return
        crosswalk_by_id = {crosswalk.id: crosswalk for crosswalk in self.crosswalks}
        source_crosswalks = source.get("pedestrian_crosswalk") or {}
        latest_states = np.asarray(states_per_step[latest_step], dtype=np.float64).reshape(
            len(ids_per_step[latest_step]), -1
        )
        for index, raw_id in enumerate(ids_per_step[latest_step]):
            if latest_states.shape[1] < 7:
                continue
            pedestrian_id = str(raw_id)
            state = latest_states[index, :7]
            crosswalk_id = str(
                source_crosswalks.get(raw_id, source_crosswalks.get(pedestrian_id, ""))
            )
            crosswalk = crosswalk_by_id.get(crosswalk_id)
            if crosswalk is None and self.crosswalks:
                crosswalk = min(
                    self.crosswalks,
                    key=lambda item: project_point_to_segment(
                        state[:2], item.start, item.end
                    )[1],
                )
            if crosswalk is None:
                continue
            projected, _, progress = project_point_to_segment(
                state[:2], crosswalk.start, crosswalk.end
            )
            line = crosswalk.end - crosswalk.start
            line_length = max(float(np.linalg.norm(line)), 1e-9)
            normal = np.asarray([-line[1], line[0]], dtype=np.float64) / line_length
            direction = 1 if float(np.dot(state[3:5], line)) >= 0.0 else -1
            if float(np.linalg.norm(state[3:5])) <= 0.05:
                heading_delta = abs(
                    (float(state[2]) - crosswalk.heading + math.pi)
                    % (2.0 * math.pi)
                    - math.pi
                )
                direction = 1 if heading_delta <= math.pi * 0.5 else -1
            pedestrian = RulePedestrian(
                pedestrian_id,
                crosswalk,
                direction=direction,
                speed=max(1.15, min(1.55, float(np.linalg.norm(state[3:5])) or 1.35)),
                initial_progress=progress,
                lateral_offset=float(np.dot(state[:2] - projected, normal)),
                reaction_time=float(self.mixed_rng.uniform(0.35, 1.25)),
            )
            pedestrian.mode = "crossing" if float(np.linalg.norm(state[3:5])) > 0.05 else "waiting"
            pedestrian.wait_seconds = 0.5 if pedestrian.mode == "waiting" else 0.0
            self.pedestrians[pedestrian_id] = pedestrian

    def _drop_incomplete_history_agents(self) -> int:
        current_step = int(self.agent_record.current_step)
        remove_ids = []
        for agent_id in list(self.agent_record.get_valid_agent_ids(timestep=-1)):
            agent = self.agent_record.get_agents(agent_id)
            relative_start = current_step - self.history_step + 1 - int(agent.spawn_time_step)
            relative_end = relative_start + self.history_step
            mask = np.asarray(agent.states_mask, dtype=bool).reshape(-1)
            if relative_start < 0 or relative_end > len(mask) or not np.all(mask[relative_start:relative_end]):
                remove_ids.append(agent_id)
        if remove_ids:
            self.agent_record.delete_id_agents(remove_ids)
            current_ids = self.agent_record._agents_id_per_step[current_step]
            remove_set = set(remove_ids)
            self.agent_record._agents_id_per_step[current_step] = [
                agent_id for agent_id in current_ids if agent_id not in remove_set
            ]
        self.agent_record.current_track_agent_ids = list(
            self.agent_record._agents_id_per_step[current_step]
        )
        return len(remove_ids)

    def init_scenario_agents(
        self,
        mode="random",
        init_file=None,
        init_dict=None,
        sparse=True,
        proceed=True,
        init_step=11,
        init_speed=2.0,
    ):
        source = init_dict
        if source is None and init_file is not None and mode in {"data", "data_random_tl"}:
            with open(init_file, "rb") as stream:
                source = pickle.load(stream)
        result = super().init_scenario_agents(
            mode=mode,
            init_file=None if source is not None else init_file,
            init_dict=source,
            sparse=sparse,
            proceed=proceed,
            init_step=init_step,
            init_speed=init_speed,
        )
        if mode in {"data", "data_random_tl"}:
            self._drop_incomplete_history_agents()
        if isinstance(source, dict):
            road_user_type = source.get("road_user_type") or {}
            vehicle_class = source.get("vehicle_class") or {}
            for agent_id, agent in self.agent_record._id_agent_mapping.items():
                source_type = str(road_user_type.get(agent_id, road_user_type.get(str(agent_id), "vehicle")))
                source_class = str(vehicle_class.get(agent_id, vehicle_class.get(str(agent_id), "vehicle")))
                if source_type.lower() in {"cyclist", "non_motorized", "bicycle"}:
                    agent.__class__ = RoutedNonMotorizedVehicle
                    agent._crossing_corridor = None
                    agent._corridor_route_signature = ()
                    agent._corridor_locked = False
                    agent.set_rightmost_route_selector(
                        lambda current_lane: select_rightmost_route(self.map, current_lane)
                    )
                    agent.actor_type = "cyclist"
                    agent.vehicle_class = "non_motorized"
                    self._ensure_cyclist_corridor(agent)
                else:
                    agent.actor_type = "vehicle"
                    agent.vehicle_class = source_class
                    if source_class.lower() not in {"", "vehicle", "car"}:
                        self._restored_profile_ids.add(agent_id)
            self._restore_pedestrians_from_source(source)
        if self.mixed_traffic_enabled and not self.preserve_loaded_state:
            self._assign_existing_vehicle_profiles()
            self._convert_initial_cyclists()
            self._spawn_initial_cyclists()
        if mode == "random":
            self._resample_random_initial_histories()
        if self.mixed_traffic_enabled and not self.preserve_loaded_state:
            self._activate_nearby_crosswalks()
        self._record_pedestrian_snapshot(self.current_step)
        return result

    def generate_agent(self, prob: float = 4e-2, init_step: int = 11, init_speed: float = 2.0):
        generated = 0
        for lane_id in self.map.start_lane:
            lane_probability = float(self.lane_arrival_rates.get(lane_id, self.default_arrival_rate))
            if self.mixed_rng.random() > lane_probability:
                continue
            cyclist = bool(
                self.mixed_traffic_enabled
                and self._is_rightmost_lane(lane_id)
                and self.mixed_rng.random() < self.cyclist_ratio
            )
            speed = float(self.mixed_rng.uniform(3.0, 5.0)) if cyclist else float(init_speed)
            if self._spawn_actor_on_lane(lane_id, cyclist=cyclist, init_step=init_step, speed=speed):
                generated += 1
        print(f"Generation done, {generated} new mixed road users in total")

    def _repair_or_remove_nonfinite_agents(self) -> None:
        agent_ids, current_states, current_mask = self.agent_record[-1, :, :3]
        active_ids = np.asarray(agent_ids, dtype=object)[current_mask]
        active_states = np.asarray(current_states, dtype=np.float64)[current_mask]
        invalid_ids = active_ids[~np.isfinite(active_states).all(axis=1)]
        remove_ids = []
        for agent_id in invalid_ids:
            agent = self.agent_record.get_agents(agent_id)
            history = np.asarray(getattr(agent, "states", []), dtype=np.float64)
            finite_rows = (
                np.flatnonzero(np.isfinite(history[:, :3]).all(axis=1))
                if history.ndim == 2 and history.shape[1] >= 3
                else np.asarray([], dtype=np.intp)
            )
            if len(finite_rows) and int(finite_rows[-1]) < len(history) - 1:
                repaired = history[int(finite_rows[-1])].copy()
                if repaired.size >= 5:
                    repaired[3:5] = 0.0
                if repaired.size >= 7:
                    repaired[5:7] = 0.0
                agent.states[-1] = repaired
                self.nonfinite_agent_repairs += 1
            else:
                remove_ids.append(agent_id)
        if remove_ids:
            self.agent_record.delete_id_agents(remove_ids)
            self.nonfinite_agent_removals += len(remove_ids)
        if len(invalid_ids):
            print(
                "Non-finite road users sanitized before lane lookup: "
                f"repaired={len(invalid_ids) - len(remove_ids)}, removed={len(remove_ids)}"
            )

    def remove_agent(self):
        self._repair_or_remove_nonfinite_agents()
        return super().remove_agent()

    def add_vehicle(self, *args, vehicle_id=None, **kwargs):
        if vehicle_id is None:
            vehicle_id = self._next_vehicle_id()
        result = super().add_vehicle(*args, vehicle_id=vehicle_id, **kwargs)
        agent = self.agent_record.get_agents(result)
        if agent is not None:
            agent.actor_type = "vehicle"
            agent.vehicle_class = "manual"
        return result

    def _route_points_and_mask(
        self, route: list[Any]
    ) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
        points: list[np.ndarray] = []
        intersection_mask: list[bool] = []
        for lane_id in route:
            lane = self.map.polyline_dict.get(lane_id)
            if lane is None:
                continue
            lane_points = np.asarray(getattr(lane, "points", []), dtype=np.float64)
            if lane_points.ndim != 2 or len(lane_points) < 2 or lane_points.shape[1] < 2:
                continue
            lane_points = lane_points[:, :2]
            if points and float(np.linalg.norm(points[-1] - lane_points[-1])) < float(
                np.linalg.norm(points[-1] - lane_points[0])
            ):
                lane_points = lane_points[::-1]
            for point in lane_points:
                points.append(point.copy())
                intersection_mask.append(int(getattr(lane, "type", -1) or -1) == 4)
        if len(points) < 2:
            return None, None
        return np.stack(points), np.asarray(intersection_mask, dtype=bool)

    def _ensure_cyclist_corridor(
        self, agent: RoutedNonMotorizedVehicle
    ) -> CyclistRouteCorridor | None:
        signature = tuple(map(str, list(getattr(agent, "route", []) or [])))
        current = getattr(agent, "_crossing_corridor", None)
        if current is not None and signature == getattr(agent, "_corridor_route_signature", ()):
            return current
        route_points, intersection_mask = self._route_points_and_mask(list(agent.route))
        if route_points is None or intersection_mask is None:
            agent.set_crossing_corridor(None)
            return None
        try:
            corridor = build_cyclist_route_corridor(
                route_points,
                intersection_mask,
                self.crosswalks,
            )
            if len(agent.states):
                corridor = corridor.anchored_at(agent.states[-1, :2])
        except ValueError:
            agent.set_crossing_corridor(None)
            return None
        agent.set_crossing_corridor(corridor)
        if corridor.passages:
            self.cyclist_corridors_built += 1
        return corridor

    def _enforce_cyclist_routes(self) -> None:
        for agent_id in self.agent_record.get_current_active_agent_ids():
            agent = self.agent_record.get_agents(agent_id)
            if not isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            corridor = self._ensure_cyclist_corridor(agent)
            if corridor is not None and getattr(agent, "_corridor_locked", False):
                try:
                    progress = corridor.project_progress(agent.states[-1, :2])
                    final_blend = max(
                        (passage.blend_end_progress for passage in corridor.passages),
                        default=0.0,
                    )
                    if progress <= final_blend + 1.0:
                        continue
                    agent._corridor_locked = False
                except (IndexError, TypeError, ValueError):
                    pass
            try:
                lane_id, _ = self.map.get_current_lane(agent.states[-1, :2], float(agent.heading[-1]))
                route = select_rightmost_route(self.map, lane_id)
            except Exception:
                route = []
            if route:
                if self._route_is_straight_compatible(route):
                    agent.assign_route(route)
                    agent.left_route = list(route)
                    agent.right_route = list(route)
                    self._ensure_cyclist_corridor(agent)

    def _safety_participants(self, horizon: int = 80) -> list[dict[str, Any]]:
        start_step = int(self.current_step) + 1
        return [
            {
                "id": pedestrian.id,
                "current_state": pedestrian.state_vector(),
                "trajectory": pedestrian.forecast(start_step, horizon, self.signal_plan),
                "static_lwh": [pedestrian.length, pedestrian.width, pedestrian.height],
                "type": "pedestrian",
            }
            for pedestrian in self.pedestrians.values()
            if pedestrian.requires_vehicle_yield(start_step, self.signal_plan)
        ]

    def _yield_cyclists_to_pedestrians(
        self,
        vehicle_ids: list[Any],
        states: np.ndarray,
        *,
        start_step: int,
    ) -> np.ndarray:
        if not self.pedestrians or states.ndim != 3 or states.shape[1] == 0:
            return states
        horizon = int(states.shape[1])
        pedestrian_trajectories = [
            pedestrian.forecast(start_step, horizon, self.signal_plan)
            for pedestrian in self.pedestrians.values()
            if pedestrian.requires_vehicle_yield(start_step, self.signal_plan)
        ]
        if not pedestrian_trajectories:
            return states

        def conflicts(trajectory: np.ndarray) -> bool:
            return any(
                np.any(
                    np.linalg.norm(trajectory[:, :2] - pedestrian[:, :2], axis=-1)
                    <= 0.95
                )
                for pedestrian in pedestrian_trajectories
            )

        for index, vehicle_id in enumerate(vehicle_ids):
            agent = self.agent_record.get_agents(vehicle_id)
            if not isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            trajectory = np.asarray(states[index], dtype=np.float64).copy()
            conflict_mask = np.zeros(horizon, dtype=bool)
            for pedestrian in pedestrian_trajectories:
                conflict_mask |= (
                    np.linalg.norm(trajectory[:, :2] - pedestrian[:, :2], axis=-1)
                    <= 0.95
                )
            if not np.any(conflict_mask):
                continue
            self.cyclist_pedestrian_conflicts += 1
            first_conflict = int(np.flatnonzero(conflict_mask)[0])
            selected = None
            for stop_index in range(first_conflict - 1, -2, -1):
                candidate = trajectory.copy()
                if stop_index < 0:
                    stop_state = np.asarray(agent.states[-1], dtype=np.float64)[:7]
                    candidate[:, :3] = stop_state[None, :3]
                    candidate[:, 3:7] = 0.0
                else:
                    candidate[stop_index + 1 :, :3] = candidate[stop_index, None, :3]
                    candidate[stop_index + 1 :, 3:7] = 0.0
                if not conflicts(candidate):
                    selected = candidate
                    break
            if selected is None:
                selected = trajectory.copy()
                stop_state = np.asarray(agent.states[-1], dtype=np.float64)[:7]
                selected[:, :3] = stop_state[None, :3]
                selected[:, 3:7] = 0.0
            states[index] = selected
            self.cyclist_pedestrian_yields += 1
        return states

    def _yield_cyclists_to_external_av(
        self,
        vehicle_ids: list[Any],
        states: np.ndarray,
    ) -> np.ndarray:
        external_id = getattr(self.agent_controller, "external_av_id", None)
        external_trajectory = getattr(self.agent_controller, "external_av_trajectory", None)
        if external_id is None or external_trajectory is None or states.ndim != 3:
            return states
        av_index = next(
            (index for index, vehicle_id in enumerate(vehicle_ids) if str(vehicle_id) == str(external_id)),
            None,
        )
        if av_index is None:
            return states
        av_agent = self.agent_record.get_agents(vehicle_ids[av_index])
        if av_agent is None:
            return states
        external_horizon = min(len(np.asarray(external_trajectory)), states.shape[1])
        if external_horizon <= 0:
            return states
        av_states = np.asarray(states[av_index, :external_horizon], dtype=np.float64)
        av_size = np.asarray(getattr(av_agent, "static_lwh", [3.8, 1.8, 1.5]), dtype=np.float64)[:2]
        for index, vehicle_id in enumerate(vehicle_ids):
            agent = self.agent_record.get_agents(vehicle_id)
            if not isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            cyclist_size = np.asarray(agent.static_lwh, dtype=np.float64)[:2]
            corrected, yielded, conflict_index = stop_trajectory_before_oriented_obstacle(
                states[index],
                current_state=np.asarray(agent.states[-1], dtype=np.float64),
                actor_size=cyclist_size,
                obstacle_trajectory=av_states,
                obstacle_size=av_size,
                margin=0.65,
            )
            if conflict_index is None:
                continue
            self.cyclist_av_conflicts += 1
            if yielded:
                states[index] = corrected
                self.cyclist_av_yields += 1
        return states

    def _constrain_cyclist_predictions(self, scenario: dict) -> dict:
        vehicle_ids = list(scenario.get("vehicle_id") or [])
        states = scenario.get("vehicle_states")
        if states is None or len(vehicle_ids) == 0:
            return scenario
        tensor_states = torch.is_tensor(states)
        output_values = (
            states.detach().cpu().numpy().copy()
            if tensor_states
            else np.asarray(states, dtype=np.float64).copy()
        )
        for index, vehicle_id in enumerate(vehicle_ids):
            agent = self.agent_record.get_agents(vehicle_id)
            if not isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            output_values[index, :, 2] = (
                output_values[index, :, 2] + math.pi
            ) % (2.0 * math.pi) - math.pi
            corridor = self._ensure_cyclist_corridor(agent)
            if corridor is None:
                continue
            source = output_values[index]
            values, corrections, signal_stops = corridor.constrain_states(
                source,
                current_position=np.asarray(agent.states[-1, :2], dtype=np.float64),
                start_step=int(scenario.get("current_step", self.current_step)) + 1,
                signal_plan=self.signal_plan,
                current_velocity=np.asarray(agent.states[-1, 3:5], dtype=np.float64),
            )
            self.cyclist_route_corrections += corrections
            if corridor.passages:
                self.cyclist_crosswalk_corrections += corrections
            self.cyclist_signal_stops += signal_stops
            output_values[index] = values
        start_step = int(scenario.get("current_step", self.current_step)) + 1
        output_values = self._yield_cyclists_to_pedestrians(
            vehicle_ids,
            output_values,
            start_step=start_step,
        )
        output_values = self._yield_cyclists_to_external_av(vehicle_ids, output_values)
        scenario["vehicle_states"] = (
            torch.as_tensor(output_values, dtype=states.dtype, device=states.device)
            if tensor_states
            else output_values
        )
        return scenario

    def _current_agent_obstacles(
        self,
        absolute_step: int,
        *,
        excluded_id: Any | None = None,
    ) -> list[tuple[np.ndarray, np.ndarray]]:
        obstacles: list[tuple[np.ndarray, np.ndarray]] = []
        for agent_id in self.agent_record.get_valid_agent_ids(timestep=absolute_step):
            if excluded_id is not None and str(agent_id) == str(excluded_id):
                continue
            agent = self.agent_record.get_agents(agent_id)
            if agent is None:
                continue
            try:
                state = np.asarray(agent.get_absolute_states(absolute_step), dtype=np.float64)
            except (AttributeError, IndexError, TypeError, ValueError):
                continue
            if state.size < 3 or not np.isfinite(state[:3]).all():
                continue
            size = np.asarray(
                getattr(agent, "static_lwh", [3.8, 1.8, 1.5]), dtype=np.float64
            )
            obstacles.append((state[:3].copy(), size[:2].copy()))
        return obstacles

    def _enforce_runtime_cyclist_safety(self, absolute_step: int) -> None:
        for agent_id in list(self.agent_record.get_valid_agent_ids(timestep=absolute_step)):
            agent = self.agent_record.get_agents(agent_id)
            if not isinstance(agent, RoutedNonMotorizedVehicle):
                continue
            relative_index = int(absolute_step) - int(agent.spawn_time_step)
            states = np.asarray(agent.states, dtype=np.float64)
            if not 0 <= relative_index < len(states):
                continue
            states[relative_index:, 2] = (
                states[relative_index:, 2] + math.pi
            ) % (2.0 * math.pi) - math.pi
            obstacles = self._current_agent_obstacles(
                absolute_step, excluded_id=agent_id
            )
            obstacles.extend(
                (
                    pedestrian.state_vector()[:3],
                    np.asarray([pedestrian.length, pedestrian.width]),
                )
                for pedestrian in self.pedestrians.values()
                if pedestrian.requires_vehicle_yield(absolute_step, self.signal_plan)
            )
            stopped, corrected, source_index = rollback_state_before_oriented_obstacles(
                states,
                relative_index,
                np.asarray(agent.static_lwh, dtype=np.float64)[:2],
                obstacles,
            )
            if corrected:
                states[relative_index:, :7] = stopped[None, :]
                self.runtime_cyclist_safety_corrections += 1
            elif source_index is None:
                self.runtime_unresolved_vulnerable_conflicts += 1

    def _advance_pedestrians_safely(self, absolute_step: int) -> None:
        vehicle_obstacles = self._current_agent_obstacles(absolute_step)
        for pedestrian_id, pedestrian in self.pedestrians.items():
            pedestrian_obstacles = [
                (
                    other.state_vector()[:3],
                    np.asarray([other.length, other.width]),
                )
                for other_id, other in self.pedestrians.items()
                if other_id != pedestrian_id
            ]
            advanced = pedestrian.advance_if_clear(
                self.sim_resolution,
                self.signal_plan.pedestrian_walk_allowed(
                    pedestrian.crosswalk.crossing_axis, absolute_step
                ),
                [*vehicle_obstacles, *pedestrian_obstacles],
            )
            if not advanced:
                self.runtime_pedestrian_safety_blocks += 1

    def step(self, predicted_green_tls=None):
        self._activate_nearby_crosswalks()
        self._enforce_cyclist_routes()
        if hasattr(self.agent_controller, "set_external_safety_participants"):
            self.agent_controller.set_external_safety_participants(self._safety_participants())
        try:
            return super().step(predicted_green_tls)
        finally:
            if hasattr(self.agent_controller, "set_external_safety_participants"):
                self.agent_controller.set_external_safety_participants()

    def advance_mixed_traffic(self, step: int = 1) -> None:
        step = max(0, int(step))
        first_step = int(self.current_step) - step + 1
        for absolute_step in range(first_step, int(self.current_step) + 1):
            self._enforce_runtime_cyclist_safety(absolute_step)
            self._advance_pedestrians_safely(absolute_step)
            self._record_pedestrian_snapshot(absolute_step)

    def get_pedestrian_actors(self, history_points: int = 30, future_points: int = 20) -> list[dict[str, Any]]:
        current_step = int(self.current_step)
        actors = []
        for pedestrian in self.pedestrians.values():
            actor = pedestrian.as_actor()
            actor["past"] = [
                snapshot[pedestrian.id][:2].astype(float).tolist()
                for step, snapshot in sorted(self._pedestrian_history.items())
                if current_step - history_points <= step <= current_step and pedestrian.id in snapshot
            ]
            actor["future"] = pedestrian.forecast(current_step + 1, future_points, self.signal_plan)[:, :2].tolist()
            actors.append(actor)
        return actors

    def export(self, sparse: bool = True) -> dict:
        exported = super().export(sparse=sparse)
        road_user_type = {}
        vehicle_class = {}
        vehicle_type = {}
        for agent_id, agent in self.agent_record._id_agent_mapping.items():
            road_user_type[agent_id] = self._agent_actor_type(agent)
            vehicle_class[agent_id] = str(getattr(agent, "vehicle_class", "vehicle"))
            vehicle_type[agent_id] = f"{type(agent).__module__}.{type(agent).__qualname__}"
        exported["road_user_type"] = road_user_type
        exported["vehicle_class"] = vehicle_class
        exported["vehicle_type"] = vehicle_type

        total_steps = max(len(exported.get("vehicle_id_per_step") or []), int(self.current_step) + 1)
        pedestrian_ids = []
        pedestrian_states = []
        for step in range(total_steps):
            snapshot = self._pedestrian_history.get(step, {})
            ids = sorted(snapshot)
            pedestrian_ids.append(ids)
            pedestrian_states.append(np.stack([snapshot[value] for value in ids]) if ids else [])
        exported["pedestrian_id_per_step"] = pedestrian_ids
        exported["pedestrian_state_per_step"] = pedestrian_states
        exported["pedestrian_static_attribute"] = {
            pedestrian_id: np.asarray([pedestrian.length, pedestrian.width, pedestrian.height], dtype=np.float64)
            for pedestrian_id, pedestrian in self.pedestrians.items()
        }
        exported["pedestrian_crosswalk"] = {
            pedestrian_id: pedestrian.crosswalk.id for pedestrian_id, pedestrian in self.pedestrians.items()
        }
        exported["mixed_traffic"] = {
            "schema": "trafficwm.mixed-traffic.v1",
            "enabled": self.mixed_traffic_enabled,
            "cyclist_ratio": self.cyclist_ratio,
            "pedestrians_per_crosswalk": self.pedestrians_per_crosswalk,
            "max_pedestrians": self.max_pedestrians,
            "vehicle_size_mode": self.vehicle_size_mode,
            "signal_timing": self.signal_plan.as_dict(),
            "crosswalks": len(self.crosswalks),
            "cyclist_corridors_built": self.cyclist_corridors_built,
            "cyclist_route_corrections": self.cyclist_route_corrections,
            "cyclist_crosswalk_corrections": self.cyclist_crosswalk_corrections,
            "cyclist_signal_stops": self.cyclist_signal_stops,
            "cyclist_pedestrian_conflicts": self.cyclist_pedestrian_conflicts,
            "cyclist_pedestrian_yields": self.cyclist_pedestrian_yields,
            "cyclist_av_conflicts": self.cyclist_av_conflicts,
            "cyclist_av_yields": self.cyclist_av_yields,
            "runtime_cyclist_safety_corrections": self.runtime_cyclist_safety_corrections,
            "runtime_pedestrian_safety_blocks": self.runtime_pedestrian_safety_blocks,
            "runtime_unresolved_vulnerable_conflicts": self.runtime_unresolved_vulnerable_conflicts,
            "invalid_spawn_rejections": self.invalid_spawn_rejections,
            "nonfinite_agent_repairs": self.nonfinite_agent_repairs,
            "nonfinite_agent_removals": self.nonfinite_agent_removals,
            "pedestrian_conflicts": int(getattr(self.agent_controller, "pedestrian_conflict_count", 0)),
            "pedestrian_safety_corrections": int(
                getattr(self.agent_controller, "pedestrian_correction_count", 0)
            ),
        }
        return exported
