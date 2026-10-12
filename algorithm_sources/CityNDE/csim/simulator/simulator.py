from __future__ import annotations
import os
import sys
import pickle

import numpy as np
import random
from matplotlib import pyplot as plt
import torch
import tqdm
import math
from typing import Iterable, Literal

import copy
import time
from pathlib import Path

from csim.scenario import BaseVectorMap, GPUVectorMap, RouteVectorMap
from csim.agent import TrafficLight, Vehicle, RoutedVehicle, RoadUserState, TrafficLightState
from csim.controller import BaseController, RouteTLController, RuleEnhancedController, IDM_MOBIL_AVController, EmptyController
from csim.manager import AgentRecordManager, ScenarioManager, VehicleRecordManager, RouteTLVectorMap, RouteTLScenarioManager

__all__ = ["BaseSimulator", "RouteTLSimulator"]

class BaseSimulator:
    def __init__(self, 
                 map_path: str = '',
                 sim_resolution: float = 0.1,
                 history_step: int = 11,
                 agent_controller: BaseController | None = None,
                 auto_agent_dep : bool = True,
                 auto_agent_arr : bool = True,):

        self.map = BaseVectorMap.create_from_file(map_path)
        self.agent_record = AgentRecordManager(formatted_state_dim=10)
        self.scenario_manager = ScenarioManager(self.agent_record, self.map, history_step=history_step)
        self.sim_resolution = sim_resolution
        self.agent_controller = agent_controller
        self.auto_agent_dep = auto_agent_dep
        self.auto_agent_arr = auto_agent_arr
        self.current_step = -1
        self.status: Literal["running", "terminated_collision", "terminated_finished"] = "running"
    
    @property
    def total_agent_num(self):
        return self.agent_record.total_agent_num
    
    def synchronize(self):
        self.current_step = self.scenario_manager.current_step
    
    @property
    def meta_info(self) -> dict:
        return {"simulator_meta_info":{
                    "type": f'{self.__class__.__name__}',
                    "resolution": self.sim_resolution,
                    "type_map_manager": f'{self.map.__class__.__name__}',
                    "type_agent_manager": f'{self.agent_record.__class__.__name__}',
                    "type_scenario_manager": f'{self.scenario_manager.__class__.__name__}',}
                }
        
    def init_scenario_agents(self, init_file:str|None = None, init_dict: dict|None = None, sparse: bool=True, proceed: bool=True):
        if init_file is None and init_dict is None:
            if proceed:
                self.direct_step(self.scenario_manager.history_step)
            return
        if init_file is not None:
            with open(init_file, 'rb') as f:
                init_sce = pickle.load(f)
        if init_dict is not None:
            init_sce = init_dict
        if not sparse:
            valid_keys = ["vehicle_id", "vehicle_states", "vehicle_mask", 
                          "dynamic_polyline_id", "dynamic_polyline_states", "dynamic_polyline_mask"]
        else:
            valid_keys = ["vehicle_id_per_step", "vehicle_state_per_step", "vehicle_static_attribute", 
                          "dynamic_polyline_id_per_step", "dynamic_polyline_state_per_step"]
        valid_sce = {k: v for k, v in init_sce.items() if k in valid_keys}
        self.scenario_manager.load(valid_sce, sparse=sparse, proceed=proceed)
            
            
    def direct_step(self, step:int):
        self.current_step += self.scenario_manager.proceed_step(step)
    
    def generate_agent(self):
        pass
    
    def remove_agent(self):
        pass
        
    def external_step(self, formatted_scenario: dict) -> dict:
        '''
        If using NDE simulator as main simulator, rewrite this function to manipulate original NDE output result. 
        The structure of input should remain unchanged.  
        '''
        return formatted_scenario
        
    def run(self, init_file: str|None=None, total_step: int=1000000, save_file:str|None=None, save_interval: int=1):
        if save_file is not None:
            os.makedirs(os.path.dirname(save_file), exist_ok=True)
        self.init_scenario_agents(init_file=init_file)
        for step in tqdm.trange(total_step, desc="step"):
            if self.check_termination():
                break
            scenario_update = self.step()
            self.update(scenario_update, save_file=save_file, save_interval=save_interval)
                
    
    def run_parallel(self, init_file: str|None=None, total_step: int=1000000, save_file:str|None=None, num_gpus:int=2):
        raise NotImplementedError
        self.init_scenario_agents(init_file=init_file)
        parallel_gpus = min(torch.cuda.device_count(), num_gpus)
        for step in tqdm.trange(total_step, desc="step"):
            if self.check_termination():
                break
            if self.auto_agent_dep_arr:
                self.generate_agent()
                self.remove_agent()
            if parallel_gpus <= 0:
                raise RuntimeError("No valid GPU found.")
            else:
                streams = [torch.cuda.Stream(device=i) for i in range(parallel_gpus)]
                parallel_scenarios_agent_ids = [list(scenario_id) for scenario_id in np.array_split(np.array(self.agent_record.get_current_active_agent_ids(), dtype=object), parallel_gpus)]
                parallel_scenario_update = []
                for i, stream in enumerate(streams):
                    with torch.cuda.device(i):
                        with torch.cuda.stream(stream):
                            formatted_scenario = self.scenario_manager.prepare_formatted_scenario(agent_ids=parallel_scenarios_agent_ids[i])
                            scenario_update = self.agent_controller.step(formatted_scenario)
                            parallel_scenario_update.append(self.external_step(scenario_update))
                for stream in streams:
                    stream.synchronize()
                scenario_update = {}
                for key in parallel_scenario_update[0].keys():
                    scenario_update[key] = np.concatenate([scenario[key] for scenario in parallel_scenario_update], axis=0)
        
            update_step = self.scenario_manager.update_scenario(scenario_update)
            if update_step >= 0:
                self.current_step += update_step
                
            if save_file is not None:
                self.save_to(save_file)
        
        
    def step(self) -> dict:
        t = time.time()
        if self.auto_agent_dep:
            self.generate_agent()
        if self.auto_agent_arr:
            self.remove_agent()
        print(f"generate and remove agent done, time: {time.time() - t}")
        t = time.time()
        formatted_scenario = self.scenario_manager.prepare_formatted_scenario()
        print(f"prepare formatted scenario done, time: {time.time() - t}")
        t = time.time()
        formatted_scenario = self.agent_controller.step(formatted_scenario)
        print(f"main step done, time: {time.time() - t}\n")
        return formatted_scenario
        
    def update(self, formatted_scenario: dict, save_file: str | None = None, save_interval: int = 1):
        self.scenario_manager.update_scenario(formatted_scenario)
        self.synchronize()
        if save_file is not None and self.current_step % save_interval == 0:
            self.save_to(save_file)
        
    def check_termination(self) -> bool:
        return False
    
    def reset(self):
        self.status = "running"
        self.scenario_manager.reset()
        self.synchronize()
    
    def export(self, sparse: bool = True) -> dict:
        return {**self.meta_info, **self.scenario_manager.export(sparse=sparse)}
    
    def load(self, dic: dict, sparse: bool = True, proceed: bool = True) -> BaseSimulator:
        if "simulator_meta_info" in dic.keys():
            meta_info = dic.pop("simulator_meta_info")
            for k, v in meta_info.items():
                assert self.meta_info[k] == v, f'Unmatched simulator meta information "{k}" from "{v}" to "{self.meta_info[k]}"'
        self.scenario_manager.load(dic=dic, sparse=sparse, proceed=proceed)
        return self
    
    def save_to(self, file:str):
        with open(file, "wb") as f:
            pickle.dump(self.export(), f)

class RouteTLSimulator(BaseSimulator):
    def __init__(self,
                 map_path: str = '',
                 sim_resolution: float = 0.1,
                 history_step: int = 11,
                 agent_controller: RouteTLController | None = None,
                 auto_agent_dep : bool = True,
                 auto_agent_arr : bool = True):

        self.map = RouteTLVectorMap()
        if Path(map_path).exists():
            with open(map_path, "rb") as m:
                map_info: dict = pickle.load(m)
            self.map.load_map(map_info)
        else:
            print(f"Warning: Map file {map_path} not found, using empty map")
        self.agent_record = VehicleRecordManager(formatted_state_dim=10, default_vehicle_type=RoutedVehicle)
        self.scenario_manager = RouteTLScenarioManager(self.agent_record, self.map, history_step=history_step)
        self.sim_resolution = sim_resolution
        self.agent_controller = agent_controller
        self.auto_agent_dep = auto_agent_dep
        self.auto_agent_arr = auto_agent_arr
        self.current_step = -1

    @property
    def history_step(self) -> int:
        return self.scenario_manager.history_step

    def update(self, formatted_scenario: dict, save_file: str | None = None, save_interval: int = 1):
        self.scenario_manager.update_scenario(formatted_scenario, 
                                              allow_modify_num_agents=True)
        self.synchronize()
        if save_file is not None and self.current_step % save_interval == 0:
            self.save_to(save_file)

    def synchronize(self):
        self.scenario_manager.runtime_check()
        self.current_step = self.scenario_manager.current_step
    
    def init_traffic_light(self, tls_id: list[int|str], tls_states: np.ndarray|None=None):
        assert set(tls_id) < set(self.map.polyline_ids), f"Traffic light id {set(tls_id) - set(self.map.polyline_ids)} not found in map"
        all_tls_phase = self.map.get_intersection_polyline_phase(tls_id)
        for i, (tl_id, tl_phase) in enumerate(zip(tls_id, all_tls_phase)):
            if tls_states is None:
                tl_states = np.empty((0, 4))
            else:
                tl_states = tls_states[i]
            tl_pos = self.map.polyline_dict[tl_id].center_location
            tl_start = self.map.polyline_dict[tl_id].points[0:1]
            self.map.add_agents_from_states(start=0,
                                            tls_id=tl_id,
                                            tls_states=tl_states,
                                            tls_phase=tl_phase,
                                            tls_loc=tl_pos,
                                            tls_start=tl_start)
            
    def init_scenario_agents(self, mode:Literal["random", "empty", "data", "data_random_tl", "random_tl_only"]="random", 
                             init_file: str | None = None, init_dict: dict | None = None, 
                             sparse: bool = True, proceed: bool = True, 
                             init_step: int=11, init_speed: float=2.):
        if mode in ["empty", "data"]:
            if mode == "empty":
                init_file = init_dict = None
            super().init_scenario_agents(init_file, init_dict, sparse=sparse, proceed=proceed)
        elif mode == "data_random_tl":
            # generate traffic lights
            tls_id = self.map.get_intersection_polyline_id()
            all_tls_phase = self.map.get_intersection_polyline_phase(tls_id)
            for tl_id, tl_phase in zip(tls_id, all_tls_phase):
                if tl_phase[0] == 'g':
                    gen_tl_states = TrafficLightState(states=np.array([[1,0,0,0]]).repeat(init_step, axis=0))
                else:
                    gen_tl_states = TrafficLightState(states=np.array([[0,0,1,0]]).repeat(init_step, axis=0))
                    
                tl_pos = self.map.polyline_dict[tl_id].center_location
                tl_start = self.map.polyline_dict[tl_id].points[0:1]
                self.map.add_agents_from_states(start=self.current_step + 1,
                                                tls_id=tl_id,
                                                tls_states=gen_tl_states,
                                                tls_phase=tl_phase,
                                                tls_loc=tl_pos,
                                                tls_start=tl_start)
            super().init_scenario_agents(init_file, init_dict, sparse, proceed)
            print(f'Initialization done, {self.agent_record.total_agent_num} vehicles, {self.map.total_agent_num} polylines with traffict light in total')
        elif mode == "random_tl_only":
            # generate traffic lights
            if proceed:
                self.direct_step(step=init_step)
            tls_id = self.map.get_intersection_polyline_id()
            all_tls_phase = self.map.get_intersection_polyline_phase(tls_id)
            for tl_id, tl_phase in zip(tls_id, all_tls_phase):
                if tl_phase[0] == 'g':
                    gen_tl_states = TrafficLightState(states=np.array([[1,0,0,0]]).repeat(init_step, axis=0))
                else:
                    gen_tl_states = TrafficLightState(states=np.array([[0,0,1,0]]).repeat(init_step, axis=0))
                    
                tl_pos = self.map.polyline_dict[tl_id].center_location
                tl_start = self.map.polyline_dict[tl_id].points[0:1]
                self.map.add_agents_from_history_states(tls_id=tl_id,
                                                        tls_states=gen_tl_states,
                                                        tls_phase=tl_phase,
                                                        tls_loc=tl_pos,
                                                        tls_start=tl_start)
            print(f'Initialization done, {self.agent_record.total_agent_num} vehicles, {self.map.total_agent_num} polylines with traffict light in total')
        elif mode == "random":
            # generate vehicles
            gen_dist = [25, 50]
            min_road_end_dist = 20
            prob = 0.8
            # gen_dist = [100, 150]
            # min_road_end_dist = 50
            # prob = 0.6
            
            if proceed:
                self.direct_step(step=init_step)
            
            visited_lanes = []
            i = 0
            for lane_id, lane_type in zip(self.map.polyline_ids, self.map.polyline_type):
                if lane_type != 0 or lane_id in visited_lanes:
                    continue
                lane_chain_backward = self.map.get_lane_chain(lane_id, backward=True, max_depth=100)
                lane_chain_forward = self.map.get_lane_chain(lane_id, backward=False, max_depth=100)
                lane_chain = lane_chain_backward[:-1] + lane_chain_forward if set(lane_chain_backward) != set(lane_chain_forward) else lane_chain_forward
                visited_lanes.extend(lane_chain)
                if np.random.uniform(0, 1) > prob:
                    continue
                polyline_len = self.map.polyline_length(lane_chain)
                lane_gen_dist = random.sample(range(gen_dist[0], gen_dist[1]+1), k=2)
                lane_gen_dist.sort()
                
                gen_pos = random.sample(lane_gen_dist, k=1)[0]
                
                while gen_pos + min_road_end_dist < polyline_len:
                    
                    generated_position_heading = self.map.polyline_relative_pos(lane_chain, lon=gen_pos)

                    if self.agent_record.simple_check_conflict(generated_position_heading[:2], extra_only=True):
                        break
                    
                    gen_vehicle_states = RoadUserState()
                    for i in range(init_step):
                        gen_vehicle_states.update([generated_position_heading[0] - ((init_step - i - 1) * init_speed * math.cos(generated_position_heading[2])) * self.sim_resolution,
                                                   generated_position_heading[1] - ((init_step - i - 1) * init_speed * math.sin(generated_position_heading[2])) * self.sim_resolution,
                                                   generated_position_heading[2],
                                                   init_speed * math.cos(generated_position_heading[2]), init_speed * math.sin(generated_position_heading[2]),
                                                   0., 0.,])
                        
                    self.agent_record.add_agents_from_history_states(vehicles_id=self.total_agent_num, 
                                                                     vehicles_states=gen_vehicle_states, 
                                                                     vehicles_static=np.array([3.8, 1.8, 1.5]),
                                                                     vehicles_type=RoutedVehicle)
                    
                    gen_pos += random.sample(lane_gen_dist, k=1)[0]
            
            # generate traffic lights
            tls_id = self.map.get_intersection_polyline_id()
            all_tls_phase = self.map.get_intersection_polyline_phase(tls_id)
            for tl_id, tl_phase in zip(tls_id, all_tls_phase):
                if tl_phase[0] == 'g':
                    gen_tl_states = TrafficLightState(states=np.array([[1,0,0,0]]).repeat(init_step, axis=0))
                else:
                    gen_tl_states = TrafficLightState(states=np.array([[0,0,1,0]]).repeat(init_step, axis=0))
                    
                tl_pos = self.map.polyline_dict[tl_id].center_location
                tl_start = self.map.polyline_dict[tl_id].points[0:1]
                self.map.add_agents_from_history_states(tls_id=tl_id,
                                                        tls_states=gen_tl_states,
                                                        tls_phase=tl_phase,
                                                        tls_loc=tl_pos,
                                                        tls_start=tl_start)
                
            print(f'Initialization done, {self.agent_record.total_agent_num} vehicles, {self.map.total_agent_num} polylines with traffict light in total')
            
            self.scenario_manager.track_current_agents()
        else:
            raise ValueError(f"unknown initilization strategy '{mode}'")
        if proceed:
            self.synchronize()
                
    def check_termination(self, mode: Literal["AV_collision", "None"]="AV_collision") -> bool:
        if mode == "AV_collision":
            collision_mat, agent_ids = self.agent_record.strict_check_conflict(verbose=True)
            colli_ids = np.array(agent_ids, dtype=object)[np.sum(collision_mat, axis=-1) > 1]
            if np.isin(colli_ids, self.agent_controller.AV_id).any():
                print(f"Simulation terminated: AV collision detected: {set(list(colli_ids))}")
                self.status = "terminated_collision"
                return True
            return False
        elif mode == "None":
            return False
        else:
            raise ValueError(f"unknown termination mode '{mode}', supported modes: 'AV_collision', 'None'")
    
    def step(self, predicted_green_tls: list[list[int|str]] | None = None):
        '''
        This function is a quick implementation for the case that the traffic light information is controlled by external controller.
        '''
        if self.auto_agent_dep:
            self.generate_agent()
        if self.auto_agent_arr:
            self.remove_agent()

        formatted_scenario = self.scenario_manager.prepare_formatted_scenario()
        # Pass explicit static IDs (set via interactive web actions) into controller pipeline.
        formatted_scenario["static_vehicle_ids"] = list(getattr(self, "static_vehicle_ids", set()))

        formatted_scenario = self.agent_controller.main_step(formatted_scenario)
        if predicted_green_tls is not None:
            formatted_scenario["predicted_green_lights"] = predicted_green_tls
        formatted_scenario = self.agent_controller.post_process(formatted_scenario)
        return formatted_scenario
        
    
    def run(self, init_mode:Literal["random", "empty", "data", "data_random_tl", "random_tl_only", "none"]="none", 
            init_file: str|None=None, init_dict: dict|None=None, 
            total_step: int=1000000, save_file:str|None=None, save_interval: int=1,
            termination_mode: Literal["AV_collision", "None"]="None"):
        if save_file is not None:
            os.makedirs(os.path.dirname(save_file), exist_ok=True)
        for step in tqdm.trange(total_step, desc="step"):
            if self.check_termination(mode=termination_mode):
                break
            if step == 0 and init_mode != "none":
                self.init_scenario_agents(mode=init_mode, init_file=init_file, init_dict=init_dict)
            # if hasattr(self.agent_controller, "debug_id"):
            #     self.agent_controller.debug_id = "".join([str_part + "_" for str_part in self.agent_controller.debug_id.split('_')[:-1]]) + str(step)
            scenario_update = self.step()
            scenario_update = self.external_step(scenario_update)
            self.update(scenario_update, save_file=save_file, save_interval=save_interval)
        else:
            self.status = "terminated_finished"
    
    
    def generate_agent(self, prob:float=4e-2, init_step:int=11, init_speed:float=2.):
        # TODO Fix these generation configs
        gen_pos = 5
        min_road_end_dist = 20
        # ------
        gen_v_num = 0
        
        for lane_id in self.map.start_lane:
            # neighbor_lanes = self.map.polyline_dict[lane_id].left_lanes_id + self.map.polyline_dict[lane_id].right_lanes_id
            # prob = 5.5e-2 if neighbor_lanes else 5e-2
            lane_chain = self.map.get_lane_chain(lane_id, max_depth=10)
            if np.random.uniform(0, 1) > prob or len(lane_chain) == 0: continue
            if self.map.polyline_length(lane_chain) - gen_pos < min_road_end_dist: continue
            generated_position_heading = self.map.polyline_relative_pos(lane_chain, lon=gen_pos)
            if self.agent_record.simple_check_conflict(generated_position_heading[:2], extra_only=True): continue
            generated_history_position_heading = self.map.polyline_relative_pos(lane_chain, lon=gen_pos - init_speed * self.sim_resolution * (init_step - 1))
            if self.agent_record.simple_check_conflict(generated_history_position_heading[:2], extra_only=True, time_step=-init_step): continue
            
            gen_vehicle_states = RoadUserState()
            for i in range(init_step):
                gen_vehicle_states.update([generated_position_heading[0] - ((init_step - i - 1) * init_speed * math.cos(generated_position_heading[2])) * self.sim_resolution,
                                           generated_position_heading[1] - ((init_step - i - 1) * init_speed * math.sin(generated_position_heading[2])) * self.sim_resolution,
                                           generated_position_heading[2],
                                           init_speed * math.cos(generated_position_heading[2]), init_speed * math.sin(generated_position_heading[2]),
                                           0., 0.,])
                
            # self.agent_record.add_agents_from_history_states(vehicles_id=self.total_agent_num, vehicles_states=gen_vehicle_states, vehicles_static=np.array([3.8, 1.8, 1.5]),
            #                                                  vehicles_type=RoutedVehicle)
            self.agent_record.add_agents_from_history_states(vehicles_id=max(self.agent_record._id_agent_mapping) + 1, vehicles_states=gen_vehicle_states, vehicles_static=np.array([3.8, 1.8, 1.5]),
                                                             vehicles_type=RoutedVehicle)
            
            gen_v_num += 1
                        
        print(f'Generation done, {gen_v_num} new vehicles in total')
        
    def remove_agent(self):
        max_lane_dist = 5
        agent_id, agents_state, agents_mask = self.agent_record[-1, :, :3]
        agent_id = np.array(agent_id, dtype=object)[agents_mask]
        agents_pos, agents_heading = agents_state[:, :2], agents_state[:, 2]
        agents_pos, agents_heading = agents_pos[agents_mask], agents_heading[agents_mask]
        
        agent_end = np.array([self.map.check_end(agents_pos[i], agents_heading[i]) for i in range(len(agents_pos))]).astype(bool)
        agent_off_road = np.array([self.map.get_current_lane(agents_pos[i])[1] for i in range(len(agents_pos))]) > max_lane_dist
        agent_colli_mat, colli_id = self.agent_record.simple_check_conflict(min_dist=1, verbose=True)
        colli_id = np.array(colli_id, dtype=object)[np.sum(agent_colli_mat, axis=-1) > 1]
        agent_colli = np.isin(agent_id, colli_id)
        agent_colli = np.zeros_like(agent_colli)
        agent_anomalous = np.isin(agent_id, self.scenario_manager.anomalous_vehicle_ids)
        agent_remove = agent_end | agent_off_road | agent_colli | agent_anomalous
        
        remove_id = agent_id[agent_remove]
        self.agent_record.delete_id_agents(remove_id)

        agent_off_road[agent_end] = False
        agent_colli[agent_off_road | agent_end] = False
        agent_anomalous[agent_colli | agent_off_road | agent_end] = False
    
        print(f'{int(np.sum(agent_remove))} vehicles removed, {int(np.sum(agent_end))} for reaching end, {int(np.sum(agent_off_road))} for off-road, {int(np.sum(agent_colli))} for collision, {int(np.sum(agent_anomalous))} for anomalous behavior')

        if agent_anomalous.any():
            print(f"Anomalous behavior detected: {self.scenario_manager.anomalous_vehicle_ids}")
