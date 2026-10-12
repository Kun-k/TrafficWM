from __future__ import annotations
import os

_CITYNDE_DETERMINISTIC = os.getenv("CITYNDE_DETERMINISTIC", "1") != "0"
if _CITYNDE_DETERMINISTIC:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import time
import numpy as np
import random
from matplotlib import pyplot as plt
import torch
if _CITYNDE_DETERMINISTIC:
    torch.use_deterministic_algorithms(True)
import tqdm
import math
from typing import Literal, Iterable

import copy
import sys, shutil
from shapely.geometry import Point, LineString

from cnde.models.model import MotionTransformer
from ..scenario import BaseVectorMap, GPUVectorMap
from ..manager import RouteTLVectorMap, AgentRecordManager, ScenarioManager, VehicleRecordManager
from cutils import rotate_points_along_z, interpolate, scenario_affine_transform, cubic_hermite_curve
from ..viewer import ScenarioViewer
from .rule_controller import RuleController
from .safety_utils import search_collision_free_modes

# viewer = ScenarioViewer()

class BaseController:
    '''
    The format of data should be aligned with the record managers.
    Controller behaviors bind with input feature information, so hard code of input feature dimension is unavoidable.
    '''
    def __init__(self, 
                 core,
                 control_step:int):
        self.core = core
        self.control_step = control_step


    def batch_control(self, scenario: dict, batch_size: int) -> dict:
        '''
        batch_control() should update input scenario instead of returning a new scenario
        batch_control() is only for nn controller
        '''
        self.core = self.core.cuda()
            
        inst_num = list(scenario.values())[0].shape[0]
        batch_num = (inst_num + batch_size - 1) // batch_size
        batch_output:list[dict] = []
        for i in range(batch_num):
            batch_scenario = {k: v[i*batch_size:(i+1)*batch_size] for k, v in scenario.items()}
            batch_output.append(self.core(batch_scenario))
        scenario_output = {}
        for key in batch_output[0].keys():
            scenario_output[key] = torch.cat([batch[key] for batch in batch_scenario], dim=0)
            
        scenario.update(scenario_output)
        return scenario
    
    def step(self, formatted_scenario: dict, batch_size: int=128):
        '''
        main_step() and post_process() are separated because external controller might inject some traffic light information before post_process().
        '''
        t = time.time()
        output_scenario = self.main_step(formatted_scenario, batch_size=batch_size)
        print(f"main step done, time: {time.time() - t}")
        t = time.time()
        output_scenario = self.post_process(output_scenario)
        print(f"post process done, time: {time.time() - t}")
        return output_scenario
    
    def main_step(self, formatted_scenario: dict, batch_size: int=128):
        t = time.time()
        scenario = self._to_agent_centric_scenario(formatted_scenario)
        print(f"to agent centric scenario done, time: {time.time() - t}")
        t = time.time()
        output_scenario = self.batch_control(scenario, batch_size=batch_size)
        print(f"batch control done, time: {time.time() - t}")
        return output_scenario
    
    def _to_agent_centric_scenario(self, scenario: dict) -> dict:
        '''
        Default _to_agent_centric_scenario() only returns useful information for controller
        '''
        return scenario
    
    def post_process(self, scenario: dict) -> dict:
        return scenario
    
    def reset(self):
        pass
    
class ConstController(BaseController):
    def __init__(self, control_step):
        def f(scenario):
            ret_scenario = {}
            ret_scenario["vehicle_id"] = scenario["vehicle_id"]
            ret_scenario["vehicle_states"] = scenario["vehicle_states"][:, -control_step:, :7]
            ret_scenario["vehicle_states"][..., -2:] = 0
            ret_scenario["vehicle_states"][..., 3] = scenario["vehicle_states"][:, -1:, 3]
            ret_scenario["vehicle_states"][:, :-1, 3:5] = ret_scenario["vehicle_states"][:, -1:, 3:5]
            for i in range(control_step):
                ret_scenario["vehicle_states"][:, :-i-1, :2] = scenario["vehicle_states"][:, -1:, :2] + scenario["vehicle_states"][:, -1:, 3:5] * 0.1 * i
            ret_scenario["vehicle_mask"] = np.ones_like(scenario["vehicle_mask"][:, -1:])
            ret_scenario["dynamic_polyline_id"] = scenario["dynamic_polyline_id"]
            ret_scenario["dynamic_polyline_states"] = scenario["dynamic_polyline_states"][:, -1:, :5]
            ret_scenario["dynamic_polyline_mask"] = np.ones_like(scenario["dynamic_polyline_mask"][:, -1:])
            return ret_scenario
        super().__init__(f, control_step)
        
    def batch_control(self, scenario: dict, batch_size: int = 16384) -> dict:
        scenario.update(self.core(scenario))
        return scenario

class EmptyController(BaseController):
    def __init__(self, control_step):
        super().__init__(None, control_step)
    
    def step(self, scenario: dict) -> dict:
        return {"vehicle_id": [], "vehicle_states": torch.empty((0, 7))}
    
    def main_step(self, scenario: dict) -> dict:
        return {"vehicle_id": [], "vehicle_states": torch.empty((0, 7))}
    
class RouteController(BaseController):
    def __init__(self, core: MotionTransformer, control_step:int, control_resolution: float, sample_strategy: str='argmax-u'):
        super().__init__(core, control_step)
        self.core = self.core.cuda()
        self.control_resolution = control_resolution
        self.sample_strategy = sample_strategy
        
    def batch_control(self, scenario: dict, batch_size: int) -> dict:
        if 'vehicle_id' not in scenario.keys():
            print("No vehicle in scenario, control skipped")
            return scenario
        if len(scenario['vehicle_id']) == 0:
            print("No vehicle in scenario")
            return scenario
        
        scenario_for_nn = {}
        scenario_for_nn['past_trajectory'] = scenario['vehicle_states']
        scenario_for_nn['past_mask'] = scenario['vehicle_mask']
        scenario_for_nn['map_polyline'] = scenario['map_polyline']
        scenario_for_nn['map_polyline_mask'] = scenario['map_polyline_mask']
        scenario_for_nn['route_polyline'] = scenario['route_polyline']
        scenario_for_nn['route_polyline_mask'] = scenario['route_polyline_mask']
        scenario_for_nn['dynamic_map_states'] = torch.zeros_like(scenario['dynamic_polyline_states'])
        scenario_for_nn['dynamic_map_mask'] = torch.zeros_like(scenario['dynamic_polyline_mask'])

        # control vehicles
        inst_num = list(scenario.values())[0].shape[0]
        batch_num = (inst_num + batch_size - 1) // batch_size
        batch_output:list[dict] = []
        for i in range(batch_num):
            batch_scenario = {k: v[i*batch_size:(i+1)*batch_size] for k, v in scenario_for_nn.items()}
            batch_output.append(self.core(batch_scenario))
        scenario_output = {"vehicle_id": scenario["vehicle_id"],
                           "vehicle_states": scenario["vehicle_states"]}
        for key in batch_output[0].keys():
            if key in ["pred_scores", "pred_trajs"]:
                scenario_output[key] = torch.cat([batch[key] for batch in batch_output], dim=0)
        
        scenario.update(scenario_output)
        return scenario
        
    def _to_agent_centric_scenario(self, scenario: dict, centric_radius: float=70.) -> dict:
        for k, v in scenario.items():
            if isinstance(v, np.ndarray):
                scenario[k] = torch.from_numpy(v).cuda()
            if isinstance(v, list):
                scenario[k] = np.array(v, dtype=object)
            if isinstance(scenario[k], torch.Tensor):
                if scenario[k].dtype == torch.float64 and k != "vehicle_states": # This is because of the numerical error caused by collision avoidance
                    scenario[k] = scenario[k].to(torch.float32)
        
        # get vehicle neibourhood items
        num_agent = len(scenario["vehicle_id"])
        if num_agent == 0:
            return scenario
        agent_center = scenario["vehicle_states"][:, -1, :2]
        assert torch.all(scenario["vehicle_mask"][:, -1]), "Trying to control vehicle with mask False in current step"
        assert torch.all(scenario["dynamic_polyline_mask"][:, -1]), "Trying to control traffic light with mask False in current step"
        all_center = torch.cat((scenario["vehicle_states"][:, -1, :2], scenario["polyline_center"]), dim=0)
        agent_neibourhood = torch.norm(agent_center[:, None, :] - all_center[None, :, :], dim=-1) <= centric_radius
        valid_vehicles, valid_polyline = agent_neibourhood[:, :agent_center.shape[0]], agent_neibourhood[:, agent_center.shape[0]:]
        num_valid_agent, num_valid_polyline = torch.sum(valid_vehicles, dim=-1), torch.sum(valid_polyline, dim=-1)
        max_num_agent = int(torch.max(num_valid_agent).item())
        max_num_polyline = int(torch.max(num_valid_polyline).item())
        device = valid_vehicles.device
        
        # define nn input batch
        vehicle_states = torch.zeros(num_agent, max_num_agent, *scenario["vehicle_states"].shape[1:], dtype=torch.float64, device=device)
        vehicle_mask = torch.zeros(num_agent, max_num_agent, *scenario["vehicle_mask"].shape[1:], dtype=torch.bool, device=device)
        map_polyline = torch.zeros(num_agent, max_num_polyline, *scenario["polyline_states"].shape[1:], device=device)
        map_polyline_mask = torch.zeros(num_agent, max_num_polyline, *scenario["polyline_mask"].shape[1:], dtype=torch.bool, device=device)
        route_polyline = scenario["route_polyline_states"]
        route_polyline_mask = scenario["route_polyline_mask"].to(torch.bool)
        dynamic_polyline_states = torch.zeros(num_agent, max_num_polyline, *scenario["dynamic_polyline_states"].shape[1:], device=device)
        dynamic_polyline_mask = torch.zeros(num_agent, max_num_polyline, *scenario["dynamic_polyline_mask"].shape[1:], dtype=torch.bool, device=device)
        
        dynamic_map_id_index_mapping = {m_id: idx for idx, m_id in enumerate(scenario["dynamic_polyline_id"])}
        
        # Preserve the original rolled neighbor order while packing all rows at once.
        row_index = torch.arange(num_agent, device=device)[:, None]
        vehicle_order = (row_index + torch.arange(num_agent, device=device)[None, :]) % num_agent
        ordered_valid_vehicles = torch.gather(valid_vehicles, 1, vehicle_order)
        vehicle_rows, vehicle_order_columns = torch.nonzero(ordered_valid_vehicles, as_tuple=True)
        vehicle_columns = ordered_valid_vehicles.long().cumsum(dim=1)[vehicle_rows, vehicle_order_columns] - 1
        vehicle_sources = vehicle_order[vehicle_rows, vehicle_order_columns]
        vehicle_states[vehicle_rows, vehicle_columns] = scenario["vehicle_states"][vehicle_sources]
        vehicle_mask[vehicle_rows, vehicle_columns] = scenario["vehicle_mask"][vehicle_sources]

        map_rows, map_sources = torch.nonzero(valid_polyline, as_tuple=True)
        map_columns = valid_polyline.long().cumsum(dim=1)[map_rows, map_sources] - 1
        map_polyline[map_rows, map_columns] = scenario["polyline_states"][map_sources]
        map_polyline_mask[map_rows, map_columns] = scenario["polyline_mask"][map_sources]

        polyline_dynamic_index = torch.tensor(
            [dynamic_map_id_index_mapping.get(polyline_id, -1) for polyline_id in scenario["polyline_id"]],
            dtype=torch.long,
            device=device,
        )
        selected_dynamic_index = polyline_dynamic_index[map_sources]
        dynamic_entries = selected_dynamic_index >= 0
        dynamic_rows = map_rows[dynamic_entries]
        dynamic_columns = map_columns[dynamic_entries]
        selected_dynamic_index = selected_dynamic_index[dynamic_entries]
        dynamic_polyline_states[dynamic_rows, dynamic_columns] = scenario["dynamic_polyline_states"][selected_dynamic_index]
        dynamic_polyline_mask[dynamic_rows, dynamic_columns] = scenario["dynamic_polyline_mask"][selected_dynamic_index]

        # rotate each batch to agent-centric
        self._center_position, self._center_heading = vehicle_states[:, 0, -1, :2].clone(), vehicle_states[:, 0, -1, 2].clone()
        vehicle_states = vehicle_states.float()
        vehicle_states[..., :2] = vehicle_states[..., :2] - self._center_position[:, None, None]
        vehicle_states[..., 2] = vehicle_states[..., 2] - self._center_heading[:, None, None]
        vehicle_states[..., 2] = (vehicle_states[..., 2] + torch.pi) % (torch.pi * 2) - torch.pi
        
        map_polyline[..., :2] = map_polyline[..., :2] - self._center_position[:, None, None]
        map_polyline[..., 2] = map_polyline[..., 2] - self._center_heading[:, None, None]
        map_polyline[..., 2] = (map_polyline[..., 2] + torch.pi) % (torch.pi * 2) - torch.pi
        map_polyline[..., 3] = torch.cos(map_polyline[..., 2])
        map_polyline[..., 4] = torch.sin(map_polyline[..., 2])
        
        route_polyline[..., :2] = route_polyline[..., :2] - self._center_position[:, None, None]
        route_polyline[..., 2] = route_polyline[..., 2] - self._center_heading[:, None, None]
        route_polyline[..., 2] = (route_polyline[..., 2] + torch.pi) % (torch.pi * 2) - torch.pi
        route_polyline[..., 3] = torch.cos(route_polyline[..., 2])
        route_polyline[..., 4] = torch.sin(route_polyline[..., 2])
        
        vehicle_states[..., :2] = rotate_points_along_z(
            vehicle_states[..., :2].reshape(vehicle_states.shape[0], -1, 2), -self._center_heading
            ).reshape(*vehicle_states.shape[:-1], 2)
        vehicle_states[..., 3:5] = rotate_points_along_z(
            vehicle_states[..., 3:5].reshape(vehicle_states.shape[0], -1, 2), -self._center_heading
            ).reshape(*vehicle_states.shape[:-1], 2)
        vehicle_states[..., 5:7] = rotate_points_along_z(
            vehicle_states[..., 5:7].reshape(vehicle_states.shape[0], -1, 2), -self._center_heading
            ).reshape(*vehicle_states.shape[:-1], 2)
        
        map_polyline[..., :2] = rotate_points_along_z(
            map_polyline[..., :2].reshape(map_polyline.shape[0], -1, 2), -self._center_heading
            ).reshape(*map_polyline.shape[:-1], 2)
        route_polyline[..., :2] = rotate_points_along_z(
            route_polyline[..., :2].reshape(route_polyline.shape[0], -1, 2), -self._center_heading
            ).reshape(*route_polyline.shape[:-1], 2)
        
        # only return useful information
        return {'vehicle_id': scenario["vehicle_id"], 
                'required_update_vehicle_ids': scenario["required_update_vehicle_ids"],
                'vehicle_states': vehicle_states,
                'vehicle_mask': vehicle_mask,
                'map_polyline': map_polyline,
                'map_polyline_mask': map_polyline_mask,
                'route_polyline': route_polyline,
                'route_polyline_mask': route_polyline_mask,
                'dynamic_polyline_states': dynamic_polyline_states,
                'dynamic_polyline_mask': dynamic_polyline_mask,
                'static_vehicle_ids': scenario["static_vehicle_ids"] if "static_vehicle_ids" in scenario.keys() else np.array([], dtype=object)
                }
        
    def _to_absolute_scenario(self, scenario: dict) -> dict:
        vehicle_pred_states = scenario["vehicle_states"]
        vehicle_pred_states[..., :2] = rotate_points_along_z(vehicle_pred_states[..., :2], self._center_heading)
        vehicle_pred_states[..., 3:5] = rotate_points_along_z(vehicle_pred_states[..., 3:5], self._center_heading)
        vehicle_pred_states[..., 5:7] = rotate_points_along_z(vehicle_pred_states[..., 5:7], self._center_heading)
        vehicle_pred_states[..., :2] += self._center_position[:, None]
        vehicle_pred_states[..., 2] += self._center_heading[:, None]
        scenario["vehicle_id"] = list(scenario["vehicle_id"])
        scenario["vehicle_states"] = vehicle_pred_states
        scenario["vehicle_mask"] = np.ones(vehicle_pred_states.shape[:-1]).astype(bool)
        return scenario

    def _interpolate_full_states(self, scenario: dict) -> dict:
        '''
        convert vehicle_states (dim 0, 1, 2, 3, 4 -> x, y, hd, vx, vy) to general states (last dim = 7)
        :param scenario: dict, required keys "vehicle_last_states", "vehicle_states" as torch.Tensor
        '''
        # concat current and predicted states
        vehicle_cur_pred_state = torch.cat((scenario["vehicle_last_states"][:, 0, -1:, :5], scenario["vehicle_states"][..., :5]), axis=-2)
        # padding zeros to target dimension
        vehicle_cur_pred_state = torch.cat((vehicle_cur_pred_state, torch.zeros((*vehicle_cur_pred_state.shape[:-1], scenario["vehicle_last_states"].shape[-1]-vehicle_cur_pred_state.shape[-1])).cuda()), dim=-1)
        vehicle_cur_pred_state[:, 1:, 3:5] = (vehicle_cur_pred_state[:, 1:, :2] - vehicle_cur_pred_state[:, :-1, :2]) / self.control_resolution
        vehicle_cur_pred_state[:, 1:, 5:7] = ((vehicle_cur_pred_state[:, 1:, 3:5] - vehicle_cur_pred_state[:, :-1, 3:5]) / self.control_resolution).clip(-4, 4)
        # select predicted states
        scenario.update({"vehicle_states": vehicle_cur_pred_state[:, 1:, :7]})
        return scenario
    
    def _extract_control_scenario(self, scenario: dict) -> dict:
        '''
        Extract valid keys, valid steps and convert to numpy
        '''
        required_update_vehicle_ids = scenario["required_update_vehicle_ids"]
        
        scenario = {k: v for k, v in scenario.items() if k in ["vehicle_id", "vehicle_states"]}
        for k, v in scenario.items():
            if isinstance(v, torch.Tensor): scenario[k] = scenario[k][:, :self.control_step, :].cpu().numpy()
        if 'vehicle_id' in scenario.keys():
            update_vehicle_mask = np.isin(np.array(scenario['vehicle_id'], dtype=object), np.array(required_update_vehicle_ids, dtype=object))
            scenario['vehicle_id'] = np.array(scenario['vehicle_id'], dtype=object)[update_vehicle_mask].tolist()
            scenario['vehicle_states'] = scenario['vehicle_states'][update_vehicle_mask]
        return scenario
    
    def post_process(self, scenario: dict) -> dict:
        if 'vehicle_id' not in scenario:
            scenario = self._extract_control_scenario(scenario)
            return scenario
        if len(scenario['vehicle_id']) == 0:
            scenario = self._extract_control_scenario(scenario)
            return scenario
        
        pred_trajs, pred_scores = scenario["pred_trajs"], scenario["pred_scores"]
        if self.sample_strategy == 'argmax-u':
            sampled_trajs = pred_trajs[torch.arange(pred_trajs.shape[0]), torch.argmax(pred_scores, dim=1)]
        if self.sample_strategy == 'topk3-u':
            sorted_score_id = torch.argsort(pred_scores, dim=-1, descending=True)
            sorted_scores = pred_scores[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sorted_trajs = pred_trajs[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sampled_ids = torch.multinomial(sorted_scores, 1).squeeze()
            sampled_trajs = sorted_trajs[torch.arange(sorted_trajs.shape[0]), sampled_ids]
        
        scenario["vehicle_last_states"] = scenario["vehicle_states"]
        scenario["vehicle_states"] = sampled_trajs[:, :self.control_step, [0, 1, 7, 5, 6]]
        scenario = self._interpolate_full_states(scenario)
        scenario = self._to_absolute_scenario(scenario)
        scenario = self._extract_control_scenario(scenario)
        return scenario
    
class MTRController(RouteController):
    '''
    This controller is unfinished
    '''
    def batch_control(self, scenario: dict, batch_size: int) -> dict:
        if 'vehicle_id' not in scenario.keys():
            return {}
        if len(scenario['vehicle_id']) == 0:
            return {}
        
        scenario_for_nn = {}
        # extract basic information
        scenario_for_nn['obj_trajs'] = torch.zeros((*scenario['vehicle_states'].shape[:-1], 10))
        scenario_for_nn['obj_trajs'][..., 0:2] = scenario['vehicle_states'][..., 0:2]
        scenario_for_nn['obj_trajs'][..., 3:6] = scenario['vehicle_states'][..., 9:12]
        scenario_for_nn['obj_trajs'][..., 6] = scenario['vehicle_states'][..., 2]
        scenario_for_nn['obj_trajs'][..., 7:9] = scenario['vehicle_states'][..., 5:7]
        scenario_for_nn['obj_trajs'][..., 9] = 1
        scenario_for_nn['obj_trajs_mask'] = scenario['vehicle_mask']
        scenario_for_nn['map_polylines'] = torch.zeros((*scenario['map_polyline'].shape[:-1], 9))
        scenario_for_nn['map_polylines'][..., 0:2] = scenario['map_polyline'][..., 0:2]
        scenario_for_nn['map_polylines'][..., 1:, 7:9] = scenario['map_polyline'][..., :-1, 0:2]
        scenario_for_nn['map_polylines'][..., 0, 7:9] = scenario['map_polyline'][..., 0, 0:2]
        scenario_for_nn['map_polylines'][..., 0, 3:5] = scenario['map_polyline'][..., 0, 3:5]
        int_type = torch.argmax(scenario['map_polyline'][..., -4:], dim=-1)
        int_type[int_type == 1] = 6
        int_type[int_type == 2] = 15
        int_type[int_type == 0 | int_type == 3] = 1
        scenario_for_nn['map_polylines'][..., 6] = int_type
        
        scenario_for_nn['map_polylines_mask'] = scenario['map_polyline_mask']
        scenario_for_nn['obj_trajs_last_pos'] = scenario['vehicle_states'][:, :, -1, :]
        scenario_for_nn['track_index_to_predict'] = torch.zeros(scenario['vehicle_states'].shape[0]).to(torch.int)
        scenario_for_nn['map_polylines_center'] = torch.sum(scenario['map_polyline'], dim=-2) / torch.sum(scenario['map_polyline_mask'], dim=-1)

        # convert to MTR input format
        object_onehot_mask = torch.zeros((*scenario['vehicle_states'].shape[:-1], 5))
        object_onehot_mask[:, 1:, ..., 0] = 1
        object_onehot_mask[:, 0, ..., 3] = 1

        num_timestamps = scenario['vehicle_states'].shape[-2]
        timestamps = torch.arange(0, self.control_resolution*num_timestamps+1e-2, self.control_resolution)
        object_time_embedding = torch.zeros((*scenario['vehicle_states'].shape[:-1], num_timestamps + 1))
        object_time_embedding[:, :, torch.arange(num_timestamps), torch.arange(num_timestamps)] = 1
        object_time_embedding[:, :, torch.arange(num_timestamps), -1] = timestamps

        object_heading_embedding = scenario['vehicle_states'][..., 3:5]


        vel = scenario_for_nn['obj_trajs'][:, :, :, 7:9]  # (num_centered_objects, num_objects, num_timestamps, 2)
        vel_pre = torch.roll(vel, shifts=1, dims=2)
        acce = (vel - vel_pre) / 0.1  # (num_centered_objects, num_objects, num_timestamps, 2)
        acce[:, :, 0, :] = acce[:, :, 1, :]

        scenario_for_nn['obj_trajs'] = torch.cat((
            scenario_for_nn['obj_trajs'][:, :, :, 0:6], 
            object_onehot_mask,
            object_time_embedding, 
            object_heading_embedding,
            scenario_for_nn['obj_trajs'][:, :, :, 7:9], 
            acce,
        ), dim=-1)

        scenario_for_nn['obj_trajs'][scenario_for_nn['obj_trajs_mask'] == 0] = 0

        # control vehicles
        self.core = self.core.cuda()
        inst_num = list(scenario.values())[0].shape[0]
        batch_num = (inst_num + batch_size - 1) // batch_size
        batch_output:list[dict] = []
        for i in range(batch_num):
            batch_scenario = {k: v[i*batch_size:(i+1)*batch_size] for k, v in scenario_for_nn.items()}
            batch_scenario = {"input_dict": batch_scenario}
            batch_output.append(self.core(batch_scenario))
        scenario_output = {"vehicle_id": scenario["vehicle_id"],
                           "vehicle_states": scenario["vehicle_states"]}
        for key in batch_output[0].keys():
            if key in ["pred_scores", "pred_trajs"]:
                scenario_output[key] = torch.cat([batch[key] for batch in batch_output], dim=0)
        
        scenario.update(scenario_output)
        return scenario

class RouteTLController(RouteController):
    '''
    Compared with RouteController, traffic lights are controlled.
    '''
    def __init__(self, core: MotionTransformer, control_step:int, control_resolution: float, sample_strategy: str='argmax-u', 
                 tl_phase_step: list[int] = [150, 10, 150, 10, 150, 10, 150, 10]):
        super().__init__(core, control_step, control_resolution, sample_strategy)
        self.tl_phase_step = tl_phase_step
        self.cum_phase_step = np.cumsum(self.tl_phase_step)
        
    def batch_control(self, scenario: dict, batch_size: int) -> dict:
        # control vehicles
        scenario_output = super().batch_control(scenario, batch_size)
            
        # control traffic lights
        scenario_for_tl_rule = {}
        scenario_for_tl_rule['current_step'] = scenario['current_step']
        scenario_for_tl_rule['all_dynamic_polyline_id'] = scenario['all_dynamic_polyline_id']
        scenario_for_tl_rule['all_dynamic_polyline_phase'] = np.array(scenario['all_dynamic_polyline_phase'], dtype=object)
        pred_step = scenario_output["pred_trajs"].shape[-2] if "pred_trajs" in scenario_output.keys() else self.control_step
        
        if len(scenario_for_tl_rule['all_dynamic_polyline_phase']) == 0:
            scenario_output["dynamic_polyline_id"] = scenario['all_dynamic_polyline_id']
            scenario_output["dynamic_polyline_states"] = torch.empty(0, pred_step, 4).cuda()
            return scenario_output

        dynamic_polyline_states = torch.zeros((len(scenario_for_tl_rule['all_dynamic_polyline_phase']), pred_step, 4))
        right_turn = scenario_for_tl_rule["all_dynamic_polyline_phase"] == "g"
        dynamic_polyline_states[right_turn, :, 0] = 1
        
        
        current_phase_id = np.searchsorted(self.cum_phase_step, scenario_for_tl_rule['current_step']%self.cum_phase_step[-1], side='right')
        phase_remain_step = int(self.cum_phase_step[current_phase_id]-1-scenario_for_tl_rule['current_step']%self.cum_phase_step[-1])
        controlled_step = 0
        control_remain_step = pred_step
        while control_remain_step > phase_remain_step:
            current_green = [phase[current_phase_id % len(phase)] == 'g' for phase in scenario_for_tl_rule["all_dynamic_polyline_phase"]]
            dynamic_polyline_states[current_green, controlled_step:controlled_step+phase_remain_step, 0] = 1
            controlled_step += phase_remain_step
            control_remain_step -= phase_remain_step
            current_phase_id = (current_phase_id + 1) % len(self.tl_phase_step)
            phase_remain_step = self.tl_phase_step[current_phase_id]
            
        current_green = [phase[current_phase_id % len(phase)] == 'g' for phase in scenario_for_tl_rule["all_dynamic_polyline_phase"]]
        dynamic_polyline_states[current_green, controlled_step:controlled_step+control_remain_step, 0] = 1
        fill_mask = torch.zeros_like(dynamic_polyline_states).to(torch.bool)
        red_polyline_steps = torch.sum(dynamic_polyline_states, dim=-1) == 0
        fill_mask[..., 2] = red_polyline_steps
        dynamic_polyline_states = dynamic_polyline_states.masked_fill(fill_mask, 1)
        
        scenario_output["required_update_traffic_light_ids"] = scenario['required_update_traffic_light_ids']
        scenario_output["dynamic_polyline_id"] = scenario_for_tl_rule["all_dynamic_polyline_id"]
        scenario_output["dynamic_polyline_states"] = dynamic_polyline_states.cuda()
        
        return scenario_output
        
    def _to_agent_centric_scenario(self, scenario: dict, centric_radius: float=70.) -> dict:
        tl_relevant_scenario = {'current_step': scenario["current_step"],
                                'required_update_traffic_light_ids': scenario['required_update_traffic_light_ids'],
                                'all_dynamic_polyline_id': scenario['all_dynamic_polyline_id'],
                                'all_dynamic_polyline_phase': scenario['all_dynamic_polyline_phase']}
        scenario = super()._to_agent_centric_scenario(scenario, centric_radius)
        scenario.update(tl_relevant_scenario)
        return scenario
    
    def _extract_control_scenario(self, scenario: dict) -> dict:
        scenario = {**{k: v for k, v in scenario.items() if k in ["required_update_traffic_light_ids", "dynamic_polyline_id", "dynamic_polyline_states",
                                                                  "required_update_vehicle_ids", "vehicle_id", "vehicle_states"]},
                    **super()._extract_control_scenario(scenario)}

        required_update_traffic_light_ids = scenario["required_update_traffic_light_ids"]
        for k, v in scenario.items():
            if isinstance(v, torch.Tensor): scenario[k] = scenario[k][:, :self.control_step, :].cpu().numpy()
        if 'dynamic_polyline_id' in scenario.keys():
            update_traffic_light_mask = np.isin(np.array(scenario['dynamic_polyline_id'], dtype=object), np.array(required_update_traffic_light_ids, dtype=object))
            scenario['dynamic_polyline_id'] = np.array(scenario['dynamic_polyline_id'], dtype=object)[update_traffic_light_mask].tolist()
            scenario['dynamic_polyline_states'] = scenario['dynamic_polyline_states'][update_traffic_light_mask]
        return scenario

class RuleEnhancedController(RouteTLController):
    def __init__(self, core, control_step, control_resolution, sample_strategy = 'argmax-u',
                 map_enhance: RouteTLVectorMap | None = None, agent_enhance: VehicleRecordManager | None = None):
        super().__init__(core, control_step, control_resolution, sample_strategy)
        self.map_enhance = map_enhance
        self.agent_enhance = agent_enhance
        self.safety_layer_cache = {}
        self.rule_controller = RuleController()
        self.external_av_id = None
        self.external_av_trajectory = None
        self.safety_approximate_fallback_count = 0

    def set_external_av_trajectory(self, vehicle_id=None, trajectory=None):
        self.external_av_id = vehicle_id
        self.external_av_trajectory = None if trajectory is None else np.asarray(trajectory, dtype=float)
    
    def _extract_control_scenario(self, scenario: dict) -> dict:
        scenario = {**{k: v for k, v in scenario.items() if k in ["deadlock_vehicle_id"]},
                    **super()._extract_control_scenario(scenario)}
        return scenario
    
    def post_process(self, scenario: dict) -> dict:
        if 'vehicle_id' not in scenario.keys() or len(scenario['vehicle_id']) == 0:
            scenario = self._extract_control_scenario(scenario)
            return scenario
        
        # sample
        pred_trajs, pred_scores = scenario["pred_trajs"], scenario["pred_scores"]
        if self.sample_strategy == 'argmax-u':
            sampled_trajs = pred_trajs[torch.arange(pred_trajs.shape[0]), torch.argmax(pred_scores, dim=1)]
        if self.sample_strategy == 'topk3-u':
            sorted_score_id = torch.argsort(pred_scores, dim=-1, descending=True)
            sorted_scores = pred_scores[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sorted_trajs = pred_trajs[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sampled_ids = torch.multinomial(sorted_scores, 1).squeeze()
            sampled_trajs = sorted_trajs[torch.arange(sorted_trajs.shape[0]), sampled_ids]
            
        scenario["vehicle_last_states"] = scenario["vehicle_states"]
        scenario["vehicle_states"] = sampled_trajs[:, :, [0, 1, 7, 5, 6]]
        scenario = self._interpolate_full_states(scenario)
        scenario = self._to_absolute_scenario(scenario)
        scenario = self._safety_layer_forward(scenario)
        scenario = self._extract_control_scenario(scenario)
        return scenario
    
    def _prepare_rule_forward_scenario(self, scenario):

        rule_forward_scenario = {}
        rule_forward_scenario["desc"] = scenario["current_step"]
        rule_forward_scenario["global_states"] = scenario["vehicle_states"].cpu().numpy()
        rule_forward_scenario["centers"] = torch.hstack((self._center_position.cpu(), self._center_heading[:, None].cpu()))
        
        rule_forward_scenario["tl_location_id_list"] = list(scenario["all_dynamic_polyline_id"])
        rule_forward_scenario["tl_location_states_center"] = self.map_enhance.get_location(rule_forward_scenario["tl_location_id_list"])
        rule_forward_scenario["tl_location_states_start"] = self.map_enhance.get_start_point(rule_forward_scenario["tl_location_id_list"])
        
        rule_forward_scenario["start_time_step"] = 0
        
        
        if "predicted_green_lights" not in scenario.keys():
            tl_id_array = np.array(rule_forward_scenario["tl_location_id_list"], dtype=object)
            pred_step = scenario["vehicle_states"].shape[-2]
            tl_is_green = scenario["dynamic_polyline_states"][:, :, 0].cpu().numpy().astype(bool)
            rule_forward_scenario["predicted_green_lights"] = [list(tl_id_array[tl_is_green[:, i]]) for i in range(pred_step)]
        else:
            rule_forward_scenario["predicted_green_lights"] = scenario["predicted_green_lights"]
        
        rule_forward_scenario["vehicle_ids_last_step"] = scenario["vehicle_id"]
        rule_forward_scenario["vehicle_states_last_step"] = np.zeros((len(scenario["vehicle_id"]), 7))
        rule_forward_scenario["vehicle_states_last_step"][..., :2] = self._center_position.cpu().numpy()
        rule_forward_scenario["vehicle_states_last_step"][..., 2] = self._center_heading.cpu().numpy()
        rule_forward_scenario["vehicle_states_last_step"][..., 3:5] = rotate_points_along_z(scenario["vehicle_last_states"][:, 0, -1:, 3:5].cpu().numpy(), self._center_heading.cpu().numpy()).squeeze()

        static_ids = set(np.array(scenario.get("static_vehicle_ids", []), dtype=object).tolist())
        rule_forward_scenario["static_vehicle_ids_set"] = static_ids
        if len(static_ids) > 0:
            static_mask = np.array([vid in static_ids for vid in scenario["vehicle_id"]], dtype=bool)
            if np.any(static_mask):
                static_pos_heading = rule_forward_scenario["vehicle_states_last_step"][static_mask, :3]
                rule_forward_scenario["global_states"][static_mask, :, :3] = static_pos_heading[:, None, :]
                if rule_forward_scenario["global_states"].shape[-1] >= 5:
                    rule_forward_scenario["global_states"][static_mask, :, 3:5] = 0.0
                if rule_forward_scenario["global_states"].shape[-1] >= 7:
                    rule_forward_scenario["global_states"][static_mask, :, 5:7] = 0.0
        rule_forward_scenario["vehicle_routes"] = {id: self.agent_enhance.get_agents(id).route for id in scenario["vehicle_id"]}
        vehicle_static = scenario["vehicle_last_states"].cpu().numpy()[:, 0, 0, 7:10]
        rule_forward_scenario["vehicle_static_attributes"] = {scenario["vehicle_id"][i]: vehicle_static[i] for i in range(len(scenario["vehicle_id"]))}
        rule_forward_scenario["nn_route"] = {"route_polyline": scenario["route_polyline"].cpu().numpy(),
                                             "route_polyline_mask": scenario["route_polyline_mask"].cpu().numpy()}
        rule_forward_scenario["nn_pred_trajs"] = scenario["pred_trajs"].cpu().numpy()
        rule_forward_scenario["nn_pred_scores"] = scenario["pred_scores"].cpu().numpy()
        rule_forward_scenario["route_backward_record"] = self.map_enhance.route_backward_record
        
        # reusable information
        if "all_lane_polyline_ids" in self.safety_layer_cache.keys():   
            rule_forward_scenario["all_lane_polyline_ids"] = self.safety_layer_cache["all_lane_polyline_ids"]
            rule_forward_scenario["all_lane_polyline_centers"] = self.safety_layer_cache["all_lane_polyline_centers"]
            rule_forward_scenario["all_lane_polylines"] = self.safety_layer_cache["all_lane_polylines"]
        else:
            valid_polyline_id = [id for id in self.map_enhance.polyline_ids if self.map_enhance.is_lane_center(id)]
            all_lane_polyline_info = self.map_enhance.formatted_state(polyline_ids=valid_polyline_id, past_time_steps=1)    

            rule_forward_scenario["all_lane_polyline_ids"] = all_lane_polyline_info["polyline_id"]
            rule_forward_scenario["all_lane_polyline_centers"] = all_lane_polyline_info["polyline_center"]
            rule_forward_scenario["all_lane_polylines"] = all_lane_polyline_info["polyline_states"][..., :2]
            polyline_mask = all_lane_polyline_info["polyline_mask"]

            for i, (polyline, mask) in enumerate(zip(rule_forward_scenario["all_lane_polylines"], polyline_mask)):
                if not np.all(mask):
                    rule_forward_scenario["all_lane_polylines"][i] = interpolate(polyline[mask], num_pts=20)
            rule_forward_scenario["all_lane_polylines"] = np.stack(rule_forward_scenario["all_lane_polylines"])
            
            self.safety_layer_cache["all_lane_polyline_ids"] = rule_forward_scenario["all_lane_polyline_ids"]
            self.safety_layer_cache["all_lane_polyline_centers"] = rule_forward_scenario["all_lane_polyline_centers"]
            self.safety_layer_cache["all_lane_polylines"] = rule_forward_scenario["all_lane_polylines"]
            
        return rule_forward_scenario
    
    def _safety_layer_forward(self, scenario):
        external_index = None
        external_trajectory = self.external_av_trajectory
        if self.external_av_id is not None and external_trajectory is not None:
            external_index = next(
                (index for index, vehicle_id in enumerate(scenario["vehicle_id"])
                 if str(vehicle_id) == str(self.external_av_id)),
                None,
            )
            if external_index is not None and external_trajectory.ndim == 2:
                horizon = min(scenario["vehicle_states"].shape[1], external_trajectory.shape[0])
                dimensions = min(scenario["vehicle_states"].shape[2], external_trajectory.shape[1])
                source = torch.as_tensor(
                    external_trajectory[:horizon, :dimensions],
                    dtype=scenario["vehicle_states"].dtype,
                    device=scenario["vehicle_states"].device,
                )
                scenario["vehicle_states"][external_index, :horizon, :dimensions] = source
        rule_forward_scenario = self._prepare_rule_forward_scenario(scenario)
        rule_forward_scenario["controlled_id"] = (
            [scenario["vehicle_id"][external_index]] if external_index is not None else []
        )
        fallback_count_before = getattr(search_collision_free_modes, "approximate_fallback_count", 0)
        safety_ret_scenario = self.rule_controller.forward(**rule_forward_scenario)
        fallback_count_after = getattr(search_collision_free_modes, "approximate_fallback_count", 0)
        self.safety_approximate_fallback_count += max(0, fallback_count_after - fallback_count_before)
        id2idx = {vid: idx for idx, vid in enumerate(safety_ret_scenario["vehicle_id"])}
        indices = [id2idx[vid] for vid in scenario["vehicle_id"]]
        scenario["vehicle_states"] = torch.from_numpy(safety_ret_scenario["vehicle_states"][indices]).to(scenario["vehicle_states"].device)
        if external_index is not None:
            horizon = min(scenario["vehicle_states"].shape[1], external_trajectory.shape[0])
            dimensions = min(scenario["vehicle_states"].shape[2], external_trajectory.shape[1])
            scenario["vehicle_states"][external_index, :horizon, :dimensions] = torch.as_tensor(
                external_trajectory[:horizon, :dimensions],
                dtype=scenario["vehicle_states"].dtype,
                device=scenario["vehicle_states"].device,
            )
        scenario["deadlock_vehicle_id"] = safety_ret_scenario["deadlock_vehicle_id"]
        return scenario

class IDM_MOBIL_AVController(RuleEnhancedController):
    '''
    Note that currently AV controlling is done in post_process(), since controlling AV needs 
    the information of other vehicles after safety layer in post_process().
    '''
    def __init__(self, core, control_step, control_resolution, sample_strategy = 'argmax-u', 
                 map_enhance: RouteTLVectorMap | None = None, agent_enhance: VehicleRecordManager | None = None,
                 AV_id: list[str | int] = []):
        super().__init__(core, control_step, control_resolution, sample_strategy, map_enhance, agent_enhance)
        self.AV_id = AV_id
        self.default_IDM_params = {
            "v0": 10.0,
            "a": 3.0,
            "b": 4.0,
            "T": 1.0,
            "s0": 10.0,
            "delta": 4.0,
        }
        self.AV_IDM_params: dict[str | int, dict] = {}
        self.default_MOBIL_params = {
            "p": 0.2,
            "a_th": 0.1,
            "b_safe": -2.0,
            "a_thr": 0.2,
            "v_min": 4.0,
            # "a_th": -10.0,      # parameters for unit test
            # "b_safe": -10.0,     # parameters for unit test
            # "a_thr": -10.0,     # parameters for unit test
        }
        self.AV_MOBIL_params: dict[str | int, dict] = {}
        self.AV_lane_change_step: int = 20

    def set_AV_id(self, AV_id: str | int | list[str | int]):
        if isinstance(AV_id, str) or isinstance(AV_id, int):
            AV_id = [AV_id]
        self.AV_id = AV_id

    def set_AV_IDM_params(self, AV_id: str | int | list[int|str], IDM_params: dict):
        if isinstance(AV_id, str) or isinstance(AV_id, int):
            AV_id = [AV_id]
        if not set(self.default_IDM_params.keys()) == set(IDM_params.keys()):
            print(f"Skipping setting IDM parameters for {AV_id} because it must contain {self.default_IDM_params.keys()}")
            return
        for id in AV_id:
            self.AV_IDM_params[id] = IDM_params

    def _to_agent_centric_scenario(self, scenario: dict, centric_radius: float=70.) -> dict:
        # self.debug_current_step = scenario["current_step"]
        IDM_MOBIL_relevant_info = {"route_polyline_id": scenario["route_polyline_id"]}  # route_polyline_id is for road topology search
        scenario = super()._to_agent_centric_scenario(scenario, centric_radius)
        scenario.update(IDM_MOBIL_relevant_info)
        return scenario

    def _AV_control(self, scenario: dict) -> dict:
        assert "vehicle_id" in scenario.keys()
        vehicle_is_AV = np.isin(scenario["vehicle_id"], self.AV_id)
        AV_origin_index = torch.where(torch.from_numpy(vehicle_is_AV))[0].tolist()
        AV_num = len(AV_origin_index)
        if AV_num == 0:
            return scenario
        
        AV_valid_route = []             # list[m, 9]
        AV_route_tl_start_and_state = []

        # rotate AV route to absolute coordinate and extract valid route
        for index in AV_origin_index:
            crt_AV_route = scenario["route_polyline"][index][..., :3]
            crt_AV_route_mask = scenario["route_polyline_mask"][index]
            crt_AV_valid_route = crt_AV_route[crt_AV_route_mask]
            assert crt_AV_valid_route.shape[0] > 0, f"No valid route for IDM MOBIL AV {scenario['vehicle_id'][index]}"
            crt_AV_valid_route = rotate_points_along_z(crt_AV_valid_route, self._center_heading[index])
            crt_AV_valid_route[..., :2] += self._center_position[index]
            crt_AV_valid_route[..., 2] += self._center_heading[index]
            AV_valid_route.append(crt_AV_valid_route)

        # rotate all vehicle states to absolute coordinate
        vehicle_last_states = scenario["vehicle_last_states"][:, 0, -1, :5]
        vehicle_future_states = scenario["vehicle_states"][..., :5]
        
        vehicle_last_states[..., :2] = rotate_points_along_z(vehicle_last_states[..., None, :2], self._center_heading).squeeze(-2)
        vehicle_last_states[..., 3:5] = rotate_points_along_z(vehicle_last_states[..., None, 3:5], self._center_heading).squeeze(-2)
        vehicle_last_states[..., :2] += self._center_position
        vehicle_last_states[..., 2] += self._center_heading

        vehicle_last_and_future_state = torch.cat((vehicle_last_states[..., None, :], vehicle_future_states), dim=-2)

        # get red light segment start
        AV_route_tl_start_and_state = self._find_tl_start_and_state_on_route([scenario["route_polyline_id"][index] for index in AV_origin_index], 
                                                                             np.array(scenario["all_dynamic_polyline_id"], dtype=object), 
                                                                              scenario["dynamic_polyline_states"][:, :self.control_step])
        # reorganize tl_start_and_state for each time step
        AV_route_tl_start_and_state_t = [[] for _ in range(AV_num)]
        for i in range(AV_num):
            if AV_route_tl_start_and_state[i] is not None and \
                scenario["route_polyline_id"][AV_origin_index[i]][0] not in scenario["all_dynamic_polyline_id"]:
                start, state = AV_route_tl_start_and_state[i]
                AV_route_tl_start_and_state_t[i] = [(start, state[:, t]) for t in range(self.control_step)]
            else:
                AV_route_tl_start_and_state_t[i] = None

        assert self.control_step <= vehicle_future_states.shape[-2]
        # IDM control
        for i in range(AV_num):
            crt_AV_future_state = []
            crt_AV_route = AV_valid_route[i][..., :2]
            crt_AV_origin_index = AV_origin_index[i]
            crt_AV_last_state = vehicle_last_states[crt_AV_origin_index]
            crt_AV_id = scenario["vehicle_id"][crt_AV_origin_index]
            other_vehicle_last_and_future_state = torch.cat((vehicle_last_and_future_state[:crt_AV_origin_index], vehicle_last_and_future_state[crt_AV_origin_index+1:]), dim=0)
            
            potential_conflict_state = self._infer_potential_conflict_state(other_vehicle_last_and_future_state[:, 0], crt_AV_route, crt_AV_last_state)
            for t in range(self.control_step):
                # get possible leading vehicle
                possible_leading_state = self._get_same_route_agent_state(other_vehicle_last_and_future_state[:, t], crt_AV_route, 
                                                                          AV_route_tl_start_and_state_t[i][t] if AV_route_tl_start_and_state_t[i] is not None else None)
                possible_leading_state = torch.vstack((possible_leading_state, potential_conflict_state))
                crt_AV_next_state = self._IDM_control_along_route(crt_AV_last_state, crt_AV_route, possible_leading_state, IDM_params=self.AV_IDM_params[crt_AV_id] if crt_AV_id in self.AV_IDM_params.keys() else self.default_IDM_params)
                crt_AV_future_state.append(crt_AV_next_state)
                crt_AV_last_state = crt_AV_next_state

            crt_AV_future_state = torch.stack(crt_AV_future_state)
            scenario["vehicle_states"][crt_AV_origin_index] = crt_AV_future_state
            
        # MOBIL control based on current step
        lane_change_additional_states = {"vehicle_id": [], "vehicle_states": []}
        for i in range(AV_num):
            crt_AV_origin_index = AV_origin_index[i]
            crt_AV_last_state = vehicle_last_states[crt_AV_origin_index]
            crt_AV_id = scenario["vehicle_id"][crt_AV_origin_index]
            other_vehicle_current_state = torch.cat((vehicle_last_and_future_state[:crt_AV_origin_index, 0], vehicle_last_and_future_state[crt_AV_origin_index+1:, 0]), dim=0)
            crt_AV_route_id = scenario["route_polyline_id"][crt_AV_origin_index]
            crt_AV_lane_id = crt_AV_route_id[0]
            crt_AV_backward_route_id = self.map_enhance.get_backward_routes(current_lane_id=crt_AV_lane_id, full=False)
            crt_AV_full_route_id = crt_AV_backward_route_id[:-1] + crt_AV_route_id
            polyline_formatted_state = self.map_enhance.polyline_formatted_state(polyline_ids=crt_AV_full_route_id)
            crt_AV_full_route, crt_AV_full_route_mask = polyline_formatted_state["polyline_states"][..., :2], polyline_formatted_state["polyline_mask"]
            crt_AV_full_route = torch.from_numpy(crt_AV_full_route[crt_AV_full_route_mask]).cuda()
            crt_AV_route_tl_start_and_state = AV_route_tl_start_and_state_t[i]
            if crt_AV_route_tl_start_and_state is not None:
                # use current step tl_start_and_state
                crt_AV_route_tl_start_and_state = crt_AV_route_tl_start_and_state[0]
            crt_AV_lane_states = self._get_same_route_agent_state(other_vehicle_current_state, crt_AV_full_route, crt_AV_route_tl_start_and_state)
            crt_AV_left_lane_id = self.map_enhance.polyline_dict[crt_AV_lane_id].left_lanes_id
            crt_AV_right_lane_id = self.map_enhance.polyline_dict[crt_AV_lane_id].right_lanes_id
            if crt_AV_left_lane_id:
                crt_AV_left_route_id = self.map_enhance.get_routes(current_lane_id=crt_AV_left_lane_id[0], full=False)
                crt_AV_left_backward_route_id = self.map_enhance.get_backward_routes(current_lane_id=crt_AV_left_lane_id[0], full=False)
                crt_AV_left_full_route_id = crt_AV_left_backward_route_id[:-1] + crt_AV_left_route_id
                polyline_formatted_state = self.map_enhance.polyline_formatted_state(polyline_ids=crt_AV_left_full_route_id)
                crt_AV_left_full_route, crt_AV_left_full_route_mask = polyline_formatted_state["polyline_states"][..., :2], polyline_formatted_state["polyline_mask"]
                crt_AV_left_full_route = torch.from_numpy(crt_AV_left_full_route[crt_AV_left_full_route_mask]).cuda()
                crt_AV_left_route_tl_start_and_state = self._find_tl_start_and_state_on_route([np.array(crt_AV_left_route_id, dtype=object)], 
                                                                                              np.array(scenario["all_dynamic_polyline_id"], dtype=object), 
                                                                                              scenario["dynamic_polyline_states"][:, 0])

                crt_AV_left_route_tl_start_and_state = crt_AV_left_route_tl_start_and_state[0]
                crt_AV_left_states = self._get_same_route_agent_state(other_vehicle_current_state, crt_AV_left_full_route, crt_AV_left_route_tl_start_and_state)
            else:
                crt_AV_left_full_route = None
                crt_AV_left_states = None
            if crt_AV_right_lane_id:
                crt_AV_right_route_id = self.map_enhance.get_routes(current_lane_id=crt_AV_right_lane_id[0], full=False)
                crt_AV_right_backward_route_id = self.map_enhance.get_backward_routes(current_lane_id=crt_AV_right_lane_id[0], full=False)
                crt_AV_right_full_route_id = crt_AV_right_backward_route_id[:-1] + crt_AV_right_route_id
                polyline_formatted_state = self.map_enhance.polyline_formatted_state(polyline_ids=crt_AV_right_full_route_id)
                crt_AV_right_full_route, crt_AV_right_full_route_mask = polyline_formatted_state["polyline_states"][..., :2], polyline_formatted_state["polyline_mask"]
                crt_AV_right_full_route = torch.from_numpy(crt_AV_right_full_route[crt_AV_right_full_route_mask]).cuda()
                crt_AV_right_route_tl_start_and_state = self._find_tl_start_and_state_on_route([np.array(crt_AV_right_route_id, dtype=object)], 
                                                                                                np.array(scenario["all_dynamic_polyline_id"], dtype=object), 
                                                                                                scenario["dynamic_polyline_states"][:, 0])
                crt_AV_right_route_tl_start_and_state = crt_AV_right_route_tl_start_and_state[0]
                crt_AV_right_states = self._get_same_route_agent_state(other_vehicle_current_state, crt_AV_right_full_route, crt_AV_right_route_tl_start_and_state)
            else:
                crt_AV_right_full_route = None
                crt_AV_right_states = None

            crt_AV_MOBIL_decision = self._MOBIL_decision(crt_AV_last_state, 
                                                         crt_AV_full_route, crt_AV_lane_states,
                                                         crt_AV_left_full_route, crt_AV_left_states,
                                                         crt_AV_right_full_route, crt_AV_right_states,
                                                         IDM_params=self.AV_IDM_params[crt_AV_id] if crt_AV_id in self.AV_IDM_params.keys() else self.default_IDM_params,
                                                         MOBIL_params=self.AV_MOBIL_params[crt_AV_id] if crt_AV_id in self.AV_MOBIL_params.keys() else self.default_MOBIL_params)
            
            if crt_AV_MOBIL_decision == 0:
                continue
            assert crt_AV_MOBIL_decision in [-1, 1]

            if crt_AV_MOBIL_decision == -1:
                target_route = crt_AV_left_full_route
            elif crt_AV_MOBIL_decision == 1:
                target_route = crt_AV_right_full_route
            original_AV_future_state = scenario["vehicle_states"][crt_AV_origin_index]
            if original_AV_future_state.shape[0] < self.AV_lane_change_step:
                add_step = self.AV_lane_change_step - original_AV_future_state.shape[0]
                final_step_v = torch.norm(original_AV_future_state[-1, 3:5])
                original_AV_future_state_add = self._interpolate_states_on_route_with_speed(crt_AV_full_route, original_AV_future_state[-1, :5], [final_step_v]*add_step)
                original_AV_future_state = torch.cat((original_AV_future_state, original_AV_future_state_add), dim=0)
            lane_change_AV_future_state = self._lane_change_control_to_route(original_AV_future_state, crt_AV_full_route, target_route, self.AV_lane_change_step)
            
            scenario["vehicle_states"][crt_AV_origin_index] = lane_change_AV_future_state[:self.control_step]
            if lane_change_AV_future_state.shape[0] > self.control_step:
                lane_change_additional_states["vehicle_id"].append(crt_AV_id)
                lane_change_additional_states["vehicle_states"].append(lane_change_AV_future_state[self.control_step:])
                
            # self.debug_info = []
            # debug_info = {"vehicle_id": crt_AV_id, 
            #               "lane_change_decision": "left" if crt_AV_MOBIL_decision == -1 else "right",
            #               "current_route": crt_AV_full_route.cpu().numpy(),
            #               "target_route": target_route.cpu().numpy(),
            #               "original_AV_future_state": original_AV_future_state.cpu().numpy(),
            #               "lane_change_common_state": lane_change_AV_future_state[:self.control_step].cpu().numpy(),
            #               "lane_change_additional_state": lane_change_AV_future_state[self.control_step:].cpu().numpy()}
            # self.debug_info.append(debug_info)
                
        if len(lane_change_additional_states["vehicle_id"]) > 0:
            lane_change_additional_states["vehicle_id"] = np.array(lane_change_additional_states["vehicle_id"], dtype=object)
            lane_change_additional_states["vehicle_states"] = torch.stack(lane_change_additional_states["vehicle_states"])
            scenario["heterogenous_update"] = [lane_change_additional_states]
                
        print(f"The following AVs are controlled by IDM-MOBIL: {[scenario['vehicle_id'][index] for index in AV_origin_index]}")
        return scenario
    
    def _extract_control_scenario(self, scenario: dict) -> dict:
        '''
        Extract valid vehicles, valid keys, valid steps and convert to numpy
        '''
        # extract valid keys
        scenario = {**{k: v for k, v in scenario.items() if k in ["vehicle_id", "vehicle_states", "dynamic_polyline_id", "dynamic_polyline_states",
                                                                  "heterogenous_update", "required_update_vehicle_ids", "required_update_traffic_light_ids"]},
                    **super()._extract_control_scenario(scenario)}
        
        def rec_to_numpy(elem: dict | list):
            if isinstance(elem, torch.Tensor):
                elem = elem.cpu().numpy()
            elif isinstance(elem, dict):
                for k, v in elem.items():
                    elem[k] = rec_to_numpy(v)
            elif isinstance(elem, list):
                for i in range(len(elem)):
                    elem[i] = rec_to_numpy(elem[i])
            return elem

        # extract valid vehicles
        valid_vehicle_ids = np.array(scenario["required_update_vehicle_ids"], dtype=object)
        valid_traffic_light_ids = np.array(scenario["required_update_traffic_light_ids"], dtype=object)

        if "heterogenous_update" in scenario.keys():
            scenario["heterogenous_update"] = rec_to_numpy(scenario["heterogenous_update"])
            valid_hetero_update_idx = []
            for i in range(len(scenario["heterogenous_update"])):
                valid_tag = False
                if "vehicle_id" in scenario["heterogenous_update"][i].keys():
                    valid_vehicle_mask = np.isin(np.array(scenario["heterogenous_update"][i]["vehicle_id"], dtype=object), valid_vehicle_ids)
                    scenario["heterogenous_update"][i]["vehicle_id"] = scenario["heterogenous_update"][i]["vehicle_id"][valid_vehicle_mask]
                    scenario["heterogenous_update"][i]["vehicle_states"] = scenario["heterogenous_update"][i]["vehicle_states"][valid_vehicle_mask]
                    if len(scenario["heterogenous_update"][i]["vehicle_id"]) > 0:
                        valid_tag = True
                if "dynamic_polyline_id" in scenario["heterogenous_update"][i].keys():
                    valid_traffic_light_mask = np.isin(np.array(scenario["heterogenous_update"][i]["dynamic_polyline_id"], dtype=object), valid_traffic_light_ids)
                    scenario["heterogenous_update"][i]["dynamic_polyline_id"] = scenario["heterogenous_update"][i]["dynamic_polyline_id"][valid_traffic_light_mask]
                    scenario["heterogenous_update"][i]["dynamic_polyline_states"] = scenario["heterogenous_update"][i]["dynamic_polyline_states"][valid_traffic_light_mask]
                    if len(scenario["heterogenous_update"][i]["dynamic_polyline_id"]) > 0:
                        valid_tag = True                        
                if valid_tag:
                    valid_hetero_update_idx.append(i)
            scenario["heterogenous_update"] = [scenario["heterogenous_update"][i] for i in valid_hetero_update_idx]
            
        # if hasattr(self, "debug_info") and self.debug_info:
        #     for debug_info in self.debug_info:
        #         viewer.quick_view_scenario(save_file=f"/home/ubuntu/lishu/CityNDE_/output/tmp_fig/step_{self.debug_current_step}_AV_{debug_info['vehicle_id']}_{debug_info['vehicle_id'] in valid_vehicle_ids}.pdf",
        #                                     lines=[[debug_info["target_route"][..., :2]],
        #                                             [debug_info["current_route"][..., :2]],
        #                                             [debug_info["lane_change_common_state"][..., :2]], 
        #                                             [debug_info["lane_change_additional_state"][..., :2]],
        #                                             [debug_info["original_AV_future_state"][..., :2]]],
        #                                     l_desc=[f"{debug_info['lane_change_decision']}_target_route", "current_route", "lane_change_1", "lane_change_2", "original_state"],
        #                                     plot_drct=True,
        #                                     axis="on")
        #     self.debug_info = []
                
        return scenario
    
    def _find_tl_start_and_state_on_route(self, route_polyline_id: list[np.ndarray] | list[list[int|str]], dynamic_polyline_id: np.ndarray, dynamic_polyline_states: torch.Tensor):
        '''
        Find red light segment start and state on route
        :param route_polyline_id: list of route polyline id, list of np.ndarray (dtype=object) / list of list of int | str
        :param dynamic_polyline_id: dynamic polyline id, np.ndarray (dtype=object)
        :param dynamic_polyline_states: dynamic polyline states, shape: (n, ..., >=3)
        :return: traffic light segment start state and whether it is red, shape: tuple(torch.FloatTensor(n, 5), torch.BoolTensor(n, ...)), None if not found
        :rtype: list[tuple[torch.FloatTensor, torch.BoolTensor] | None]
        '''
        tl_start_and_state = []
        for single_route_polyline_id in route_polyline_id:
            if isinstance(single_route_polyline_id, list):
                single_route_polyline_id = np.array(single_route_polyline_id, dtype=object)
                
            # get red light segment start
            tl_in_route = np.isin(dynamic_polyline_id, single_route_polyline_id)
            if not np.any(tl_in_route):
                tl_start_and_state.append(None)
                continue
            tl_is_red = dynamic_polyline_states[..., 2].to(torch.bool)
            tl_in_route_is_red = tl_is_red[tl_in_route]

            tl_in_route_id = dynamic_polyline_id[tl_in_route]
            route_in_tl = np.isin(single_route_polyline_id, dynamic_polyline_id)
            route_to_tl_index = torch.tensor([np.where(tl_in_route_id == id)[0][0] for id in single_route_polyline_id[route_in_tl]]).cuda()

            route_tl_start = torch.from_numpy(self.map_enhance.get_start_point(single_route_polyline_id[route_in_tl])).cuda()
            route_tl_start_full = torch.zeros(route_tl_start.shape[0], 5).cuda()
            route_tl_start_full[..., :2] = route_tl_start
            route_tl_start_full = route_tl_start_full[route_to_tl_index]
            tl_start_and_state.append((route_tl_start_full, tl_in_route_is_red))

        return tl_start_and_state
    
    def _infer_potential_conflict_state(self, other_vehicle_states: torch.Tensor, route: torch.Tensor, current_state: torch.Tensor, 
                                        forecast_step: int=20, downsample_step: int=5, conflict_threshold: float=4.0):
        '''
        Infer potential conflict state from other vehicle states and current state
        :param other_vehicle_states: other vehicle states (n, 5)
        :param route: route polyline points (n, 2)
        :param current_state: current state (x, y, heading, vx, vy)
        :param forecast_step: forecast step
        :param downsample_step: downsample step to accelerate inference
        :return: potential conflict state (n, 5)
        '''
        route_line = LineString(route.cpu().numpy())
        current_point = Point(current_state[0].item(), current_state[1].item())
        current_projected_dist = route_line.project(current_point)
        current_v = torch.norm(current_state[3:5]).item()
        potential_conflict_state = torch.empty(0, other_vehicle_states.shape[-1]).cuda()
        for t in range(downsample_step-1, forecast_step, downsample_step):
            other_vehicle_infer_state_t = other_vehicle_states.clone()
            other_vehicle_infer_state_t[..., :2] = other_vehicle_infer_state_t[..., :2] + other_vehicle_infer_state_t[..., 3:5] * t * self.control_resolution
            self_infer_pos = route_line.interpolate(current_projected_dist + current_v * t * self.control_resolution)
            self_infer_pos = torch.tensor([self_infer_pos.x, self_infer_pos.y]).cuda()
            infer_confict_mask = torch.norm(self_infer_pos[None, :] - other_vehicle_infer_state_t[..., :2], dim=-1) < conflict_threshold
            conflict_infer_state = other_vehicle_infer_state_t[infer_confict_mask]
            potential_conflict_state = torch.vstack((potential_conflict_state, conflict_infer_state))
        return potential_conflict_state
    
    def _get_same_route_agent_state(self, other_vehicle_states: torch.Tensor, route: torch.Tensor, tl_start_and_state: tuple[torch.Tensor, torch.Tensor]|None=None):
        '''
        Get other vehicle state along route in single time step (leading state and following state, tls are also regarded as leading state, [x, y, heading, vx, vy])
        :param other_vehicle_states: other vehicle states (n, 5)
        :param route: route polyline points (n, 2)
        :param tl_start_and_state: tuple [red light segment start (n, 2), state is red (bool) (n, )] or None
        :return: possible state (n, 5) or None
        :rtype: torch.Tensor (n, 5)
        '''
        # get possible leading vehicle
        vehicle_on_route_threshold = 2.5
        vehicle_on_route_mask = torch.any(torch.norm(route[None, ..., :2] - other_vehicle_states[..., None, :2], dim=-1) < vehicle_on_route_threshold, dim=-1)

        possible_vehicle_index = torch.where(vehicle_on_route_mask)[0]
        possible_state = other_vehicle_states[possible_vehicle_index, :5]
        
        if tl_start_and_state is not None: 
            tl_start, tl_in_route_is_red = tl_start_and_state
            tl_start = tl_start[tl_in_route_is_red]
            possible_state = torch.vstack((possible_state, torch.hstack((tl_start, torch.zeros(tl_start.shape[0], possible_state.shape[-1] - tl_start.shape[-1]).cuda()))))

        return possible_state
        
    def _IDM_control_along_route(self, current_state, route, possible_leading_state=None, IDM_params: dict|None=None):
        """
        Control vehicle along route based on current position and target speed, and IDM parameters
        
        Args:
            current_state: current state (x, y, heading, vx, vy)
            route: route polyline points (n, 2)
            possible_leading_state: leading vehicle state (x, y, heading, vx, vy) or None
            IDM_params: dict of IDM parameters or None

        Returns:
            future_state: next full states along route (x, y, heading, vx, vy, ax, ay)
        """
        route_line = LineString(route.cpu().numpy())
        current_point = Point(current_state[0].item(), current_state[1].item())

        # compute IDM next speed
        leading_projected_state = self._get_leading_and_following_state(current_state, route, possible_leading_state, leading=True, following=False)
        next_speed = self._IDM_decision(torch.norm(current_state[3:5]), leading_projected_state[2], leading_projected_state[3], IDM_params)

        return self._interpolate_states_on_route_with_speed(route_line, current_state, next_speed)


    def _interpolate_states_on_route_with_speed(self, route_line:LineString | torch.Tensor, current_state:torch.Tensor, speed_schedule:float|Iterable[float]):
        '''
        :param current_state: current state (x, y, h, vx, vy)
        :param speed_schedule: speed schedule (n, ) or float
        :return: future state ((n, 7) or (7,))
        '''
        if not isinstance(route_line, LineString):
            route_line = LineString(route_line.cpu().numpy())
        current_point = Point(current_state[0].item(), current_state[1].item())
        current_projected_dist = route_line.project(current_point)
        if not isinstance(speed_schedule, Iterable):
            speed_schedule_iter = [speed_schedule]
        else:
            speed_schedule_iter = speed_schedule
        future_state = torch.empty(0, 7).cuda()
        for speed in speed_schedule_iter:
            if isinstance(speed, torch.Tensor):
                speed = speed.item()
            if current_projected_dist > route_line.length:
                future_state = torch.vstack((future_state,
                                             torch.cat((future_state[-1, :3], torch.zeros(4).cuda()), dim=0)[None]))
                continue
            future_pos = route_line.interpolate(current_projected_dist + speed * self.control_resolution)
            future_pos = torch.tensor([future_pos.x, future_pos.y]).cuda()
            if speed < 1e-1:
                virtual_future_pos = route_line.interpolate(current_projected_dist + 1e-1)
                future_heading = torch.atan2(torch.tensor(virtual_future_pos.y) - current_state[1], torch.tensor(virtual_future_pos.x) - current_state[0])
            else:
                future_heading = torch.atan2(future_pos[1] - current_state[1], future_pos[0] - current_state[0])
            future_v = torch.tensor([torch.cos(future_heading) * speed, torch.sin(future_heading) * speed]).cuda()
            future_acc = torch.clamp((future_v - current_state[3:5]) / self.control_resolution, min=-4, max=4)
            future_state = torch.vstack((future_state, 
                                         torch.cat((future_pos, future_heading[None], future_v, future_acc), dim=0)[None]))
            current_state = future_state[-1, :5]
            current_projected_dist += speed * self.control_resolution

        if not isinstance(speed_schedule, Iterable):
            future_state = future_state[0]
        return future_state

    def _lane_change_control_to_route(self, original_state:torch.Tensor, current_route:torch.Tensor, target_route:torch.Tensor, duration_step:int|None=None):
        '''
        Control vehicle to target route in duration_step, original_state should be on current route for 
        projection to target_route. length of original_state should be equal to or large than duration_step. 
        :param original_state: original state (n, 7)
        :param current_route: current route (n, 2), current route is needed because the points in the original_state may exceed 
        the limit of target route when projected and produce unexpected results.
        :param target_route: target route (n, 2)
        :param duration_step: duration step
        :return: future state (n, 7)
        '''
        if duration_step is None:
            duration_step = original_state.shape[0]
        assert duration_step <= original_state.shape[0] and duration_step > 1

        current_route_line = LineString(current_route.cpu().numpy())
        target_route_line = LineString(target_route.cpu().numpy())

        start_state = original_state[0, :3]
        end_state = original_state[duration_step-1, :3]
        start_current_projected_dist = current_route_line.project(Point(start_state[0].item(), start_state[1].item()))
        start_target_projected_dist = target_route_line.project(Point(start_state[0].item(), start_state[1].item()))
        end_state_current_projected_dist = current_route_line.project(Point(end_state[0].item(), end_state[1].item()))
        end_state_projected_dist = end_state_current_projected_dist - start_current_projected_dist + start_target_projected_dist
        end_state_projected = target_route_line.interpolate(end_state_projected_dist)
        end_state_delta_projected = target_route_line.interpolate(end_state_projected_dist + 1e-1)
        end_state_heading = torch.atan2(torch.tensor(end_state_delta_projected.y) - torch.tensor(end_state_projected.y), torch.tensor(end_state_delta_projected.x) - torch.tensor(end_state_projected.x))
        end_state = torch.cat((torch.tensor([end_state_projected.x]), torch.tensor([end_state_projected.y]), torch.tensor([end_state_heading])))
        future_state = torch.zeros_like(original_state)
        
        # print(start_state, end_state)
        future_pos = cubic_hermite_curve(start_state, end_state, duration_step)
        future_state[:duration_step, :2] = torch.from_numpy(future_pos).cuda()
        future_state[0, 2:] = original_state[0, 2:]
        future_state[1:duration_step, 3:5] = (future_state[1:duration_step, :2] - future_state[:duration_step-1, :2]) / self.control_resolution
        future_state[1:duration_step, 5:7] = (future_state[1:duration_step, 3:5] - future_state[:duration_step-1, 3:5]) / self.control_resolution
        future_state[1:duration_step, 2] = torch.atan2((future_state[1:duration_step, :2]-future_state[:duration_step-1, :2])[..., 1], 
                                                       (future_state[1:duration_step, :2]-future_state[:duration_step-1, :2])[..., 0])

        if duration_step < original_state.shape[0]:
            v_after_lane_change = torch.norm(original_state[duration_step, 3:5])
            future_state[duration_step:] = self._interpolate_states_on_route_with_speed(target_route_line, future_state[duration_step-1, :5], v_after_lane_change.item())
        return future_state

    def _get_leading_and_following_state(self, current_state, route, state_candidate:torch.Tensor|None=None, leading:bool=True, following:bool=True) -> None | torch.Tensor | tuple[torch.Tensor]:
        '''
        Get leading and following state from state candidate
        :param current_state: current state (x, y, heading, vx, vy). For now only x and y are used.
        :param route: route polyline points (n, 2)
        :param state_candidate: state candidate (n, 5)
        :param leading: whether to get leading state
        :param following: whether to get following state
        :return: leading or following state projected on route or tuple of both or None according to parameters leading and following 
        :rtype: torch.Tensor (4,) (x, y, dist, v) | tuple[torch.Tensor (4,), torch.Tensor (4,)] | None
        '''
        dist_inf = 1e5

        if not leading and not following:
            return None
        
        if state_candidate is None:
            if leading and following:
                return torch.tensor([dist_inf, dist_inf, dist_inf, 0, 0]), torch.tensor([dist_inf, dist_inf, dist_inf, 0, 0])
            else:
                return torch.tensor([dist_inf, dist_inf, dist_inf, 0, 0])
        
        current_point = Point(current_state[0].item(), current_state[1].item())
        route_line = LineString(route.cpu().numpy())
        current_projected_dist = route_line.project(current_point)

        possible_state_num = state_candidate.shape[0]
        leading_dist = following_dist = dist_inf
        for i in range(possible_state_num):
            projected_dist = route_line.project(Point(state_candidate[i, 0].item(), state_candidate[i, 1].item()))
            if leading and projected_dist - current_projected_dist > 0:
                if projected_dist - current_projected_dist < leading_dist:
                    leading_state = state_candidate[i]
                    leading_dist = projected_dist - current_projected_dist
            if following and current_projected_dist - projected_dist > 0:
                if current_projected_dist - projected_dist < following_dist:
                    following_state = state_candidate[i]
                    following_dist = current_projected_dist - projected_dist
        
        if leading_dist < dist_inf:
            leading_projected_point = route_line.interpolate(leading_dist + current_projected_dist)
        if following_dist < dist_inf:
            following_projected_point = route_line.interpolate(current_projected_dist - following_dist)
        
        leading_projected_state = following_projected_state = torch.tensor([dist_inf, dist_inf, dist_inf, 0, 0])
        if leading and leading_dist < dist_inf:
            leading_delta_dist = leading_dist + current_projected_dist + 1e-1
            leading_delta_projected_point = route_line.interpolate(leading_delta_dist)
            leading_heading = torch.atan2(torch.tensor(leading_delta_projected_point.y) - torch.tensor(leading_projected_point.y), torch.tensor(leading_delta_projected_point.x) - torch.tensor(leading_projected_point.x))
            leading_heading_projected_delta = leading_heading - leading_state[2]
            leading_projected_longitude_v = torch.norm(leading_state[3:5]) * torch.cos(leading_heading_projected_delta)
            leading_projected_state = torch.tensor([leading_projected_point.x, leading_projected_point.y, leading_dist.item(), leading_projected_longitude_v.item()]).cuda()

        if following and following_dist < dist_inf:
            following_delta_dist = current_projected_dist - following_dist + 1e-1
            following_delta_projected_point = route_line.interpolate(following_delta_dist)
            following_heading = torch.atan2(torch.tensor(following_delta_projected_point.y) - torch.tensor(following_projected_point.y), torch.tensor(following_delta_projected_point.x) - torch.tensor(following_projected_point.x))
            following_heading_projected_delta = following_heading - following_state[2]
            following_projected_longitude_v = torch.norm(following_state[3:5]) * torch.cos(following_heading_projected_delta)
            following_projected_state = torch.tensor([following_projected_point.x, following_projected_point.y, following_dist.item(), following_projected_longitude_v.item()]).cuda()

        if leading and following:
            return (leading_projected_state, following_projected_state)
        else:
            return leading_projected_state if leading else following_projected_state
        
    def _IDM_decision(self, current_v, leading_pos, leading_v, IDM_params: dict|None=None, ret_acc:bool=False) -> float:
        if IDM_params is None:
            IDM_params = self.default_IDM_params
        else:
            assert set(self.default_IDM_params.keys()) == set(IDM_params.keys())

        # print(f"IDM control: current_v: {current_v}, leading_v: {leading_v}, leading_pos: {leading_pos}")
        
        d_v = current_v - leading_v
        s_star = IDM_params["s0"] + current_v * IDM_params["T"] + current_v * d_v / (2 * np.sqrt(IDM_params["a"] * IDM_params["b"]))
        acc = IDM_params["a"] * (1 - (current_v / IDM_params["v0"]) ** IDM_params["delta"] - (s_star / (leading_pos)))
        if isinstance(acc, (torch.Tensor, np.ndarray)):
            acc = acc.item()
        if isinstance(current_v, (torch.Tensor, np.ndarray)):
            current_v = current_v.item()
        # print(f"IDM control result: acc: {acc}, next_v: {current_v + acc * self.control_resolution}")
        if ret_acc:
            return acc
        else:
            return max(0, current_v + acc * self.control_resolution)
    
    def _MOBIL_decision(self, current_state, 
                        route, current_lane_state=None, 
                        left_route=None, left_lane_state=None,
                        right_route=None, right_lane_state=None,
                        MOBIL_params: dict|None=None, IDM_params: dict|None=None) -> Literal[-1, 0, 1]:
        if MOBIL_params is None:
            MOBIL_params = self.default_MOBIL_params
        else:
            assert set(self.default_MOBIL_params.keys()) == set(MOBIL_params.keys())
        if IDM_params is None:
            IDM_params = self.default_IDM_params
        else:
            assert set(self.default_IDM_params.keys()) == set(IDM_params.keys())

        if left_route is None and right_route is None:
            return 0    # 0: keep, -1: left, 1: right
        
        current_v = torch.norm(current_state[3:5])
        if current_v < MOBIL_params["v_min"]:
            return 0
        
        current_leading_state, current_following_state = self._get_leading_and_following_state(current_state, route, current_lane_state, leading=True, following=True)
        
        if left_route is not None:
            left_leading_state, left_following_state = self._get_leading_and_following_state(current_state, left_route, left_lane_state, leading=True, following=True)
            left_leading_dist, left_leading_v = left_leading_state[2:4]
            left_following_dist, left_following_v = left_following_state[2:4]

        if right_route is not None:
            right_leading_state, right_following_state = self._get_leading_and_following_state(current_state, right_route, right_lane_state, leading=True, following=True)
            right_leading_dist, right_leading_v = right_leading_state[2:4]
            right_following_dist, right_following_v = right_following_state[2:4]

        current_leading_dist, current_leading_v = current_leading_state[2:4]
        current_following_dist, current_following_v = current_following_state[2:4]
        
        
        a_self_old = self._IDM_decision(current_v, current_leading_dist, current_leading_v, IDM_params, ret_acc=True)
        a_following_old = self._IDM_decision(current_following_v, current_following_dist, current_v, self.default_IDM_params, ret_acc=True)
        a_following_new = self._IDM_decision(current_following_v, current_following_dist + current_leading_dist, current_leading_v, self.default_IDM_params, ret_acc=True)
    
        if left_route is not None:
            a_left_old = self._IDM_decision(left_following_v, left_following_dist + left_leading_dist, left_leading_v, self.default_IDM_params, ret_acc=True)
            a_self_left_new = self._IDM_decision(current_v, left_leading_dist, left_leading_v, IDM_params, ret_acc=True)  
            a_left_new = self._IDM_decision(left_following_v, left_following_dist, current_v, self.default_IDM_params, ret_acc=True)      
            left_change_delta_a = a_self_left_new - a_self_old + MOBIL_params["p"] * (a_left_new - a_left_old + a_following_new - a_following_old)
            is_left_change_safe = a_left_new - a_left_old > MOBIL_params["b_safe"]
        if right_route is not None:
            a_right_old = self._IDM_decision(right_following_v, right_following_dist + right_leading_dist, right_leading_v, self.default_IDM_params, ret_acc=True)
            a_self_right_new = self._IDM_decision(current_v, right_leading_dist, right_leading_v, IDM_params, ret_acc=True)
            a_right_new = self._IDM_decision(right_following_v, right_following_dist, current_v, self.default_IDM_params, ret_acc=True)
            right_change_delta_a = a_self_right_new - a_self_old + MOBIL_params["p"] * (a_right_new - a_right_old + a_following_new - a_following_old)
            is_right_change_safe = a_right_new - a_right_old > MOBIL_params["b_safe"]
        
        decision = 0
        if left_route is not None:
            if left_change_delta_a > MOBIL_params["a_th"] and a_self_left_new - a_self_old > MOBIL_params["a_thr"] and is_left_change_safe:
                decision = -1
        if right_route is not None:
            if right_change_delta_a > MOBIL_params["a_th"] and a_self_right_new - a_self_old > MOBIL_params["a_thr"] and is_right_change_safe:
                decision = 1
        return decision

    def post_process(self, scenario: dict) -> dict:
        t = time.time()
        if 'vehicle_id' not in scenario:
            scenario = self._extract_control_scenario(scenario)
            return scenario
        if len(scenario['vehicle_id']) == 0:
            scenario = self._extract_control_scenario(scenario)
            return scenario
        
        # sample
        pred_trajs, pred_scores = scenario["pred_trajs"], scenario["pred_scores"]
        if self.sample_strategy == 'argmax-u':
            sampled_trajs = pred_trajs[torch.arange(pred_trajs.shape[0]), torch.argmax(pred_scores, dim=1)]
        if self.sample_strategy == 'topk3-u':
            sorted_score_id = torch.argsort(pred_scores, dim=-1, descending=True)
            sorted_scores = pred_scores[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sorted_trajs = pred_trajs[torch.arange(0, pred_scores.shape[0])[:, None].repeat(1, pred_scores.shape[1]), sorted_score_id][:, :3]
            sampled_ids = torch.multinomial(sorted_scores, 1).squeeze()
            sampled_trajs = sorted_trajs[torch.arange(sorted_trajs.shape[0]), sampled_ids]
            
        scenario["vehicle_last_states"] = scenario["vehicle_states"]
        scenario["vehicle_states"] = sampled_trajs[:, :, [0, 1, 7, 5, 6]]
        scenario = self._interpolate_full_states(scenario)
        print(f"interpolate full states done, time: {time.time() - t}")
        t = time.time()
        scenario = self._to_absolute_scenario(scenario)
        print(f"to absolute scenario done, time: {time.time() - t}")
        t = time.time()
        scenario = self._safety_layer_forward(scenario)
        print(f"safety layer forward done, time: {time.time() - t}")
        t = time.time()
        scenario = self._AV_control(scenario)
        scenario = self._extract_control_scenario(scenario)
        print(f"post process done, time: {time.time() - t}")
        return scenario
    
class TJNoAccController(RouteTLController):
    def _interpolate_full_states(self, scenario):
        scenario =  super()._interpolate_full_states(scenario)
        if "vehicle_states" in scenario.keys():
            vehicle_pred_states = scenario["vehicle_states"]
            # vehicle_interp_heading = torch.atan2(vehicle_pred_states[..., 4], vehicle_pred_states[..., 3])
            # vehicle_static = torch.norm(vehicle_pred_states[..., 3:5], dim=-1) < 1
            # vehicle_pred_states[..., 2][~vehicle_static] = vehicle_interp_heading[~vehicle_static]
            scenario["vehicle_states"] = vehicle_pred_states
        return scenario
    
    def _extract_control_scenario(self, scenario):
        scenario = super()._extract_control_scenario(scenario)
        if "vehicle_states" in scenario.keys():
            vehicle_pred_states = scenario["vehicle_states"]
            vehicle_pred_states[..., 5:7] = 0
            scenario["vehicle_states"] = vehicle_pred_states
        return scenario
    
class TJRuleEnhancedController(RuleEnhancedController, TJNoAccController):
    pass
        
    
    
