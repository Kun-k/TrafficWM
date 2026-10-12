from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray
import random
import torch
import pickle
import json
import time
import tqdm
from typing import Iterable, Generator, Literal, Any
import os, sys
from ..agent import *
from ..viewer import ScenarioViewer
from ..scenario import BaseVectorMap, GPUVectorMap, RouteVectorMap
from cutils import onehot_time_embedding, hashable_input, sparse2dense, dense2sparse, unique_id
from cutils.data_util import interpolate_along_space
from functools import lru_cache
import shapely.geometry as geo
import shapely.affinity as aff
from copy import deepcopy
from pydoc import locate


__all__ = ["AgentRecordManager", "TrafficLightManager", "TrafficLightRuleManager", "VehicleRecordManager", "RouteTLVectorMap", "ScenarioManager", "RouteTLScenarioManager"]

class AgentRecordManager:
    def __init__(self, formatted_state_dim: int):
        '''
        :param formatted_state_dim: the dim of agent feature (independent feature only, extra features like time embedding/tag are not included). When getting formatted states, extra features are added.
        '''
        self._agents_id_per_step: list[list[int|str]] = []       # the id of agents in simulation at specifc timesteps
        self._agents_id_future_step: list[list[int|str]] = []    # the id of agents to be in simulation at specific timesteps
        self.current_track_agent_ids: list[int|str] = []        # the controlling agent ids, actual state of these agent will be update each step
        self._id_agent_mapping: dict[int|str, BaseAgent] = {}
        self.formatted_state_dim = formatted_state_dim
        
    @classmethod
    def create_from_file(cls, record_path: str, formatted_state_dim: int, sparse: bool=True, proceed: bool=False):
        obj = cls(formatted_state_dim)
        with open(record_path, "rb") as m:
            record_info:dict = pickle.load(m)
        obj.load(record_info, sparse=sparse, proceed=proceed)
        return obj
    
    def reset(self):
        self._agents_id_per_step: list[list[int|str]] = [] 
        self._agents_id_future_step: list[list[int|str]] = [] 
        self.current_track_agent_ids: list[int|str] = [] 
        self._id_agent_mapping: dict[int|str, BaseAgent] = {}
    
    def agent_len(self, timestep: int) -> int:
        return len(self._agents_id_per_step[timestep])
    
    def __len__(self):
        return len(self._agents_id_per_step)
    
    @property
    def current_step(self):
        '''
        the timestep index for the latest record (record length - 1)
        '''
        return len(self._agents_id_per_step) - 1
    
    @property
    def all_recorded_agent_ids(self) -> list[int|str]:
        return list(self._id_agent_mapping.keys())
    
    @property
    def total_agent_num(self) -> int:
        return len(self.all_recorded_agent_ids)

    def get_valid_agent_ids(self, timestep: int|slice|None = None) -> list[int|str]:
        '''
        Get valid agent ids in spcified timesteps, default all ids in history.
        '''
        if timestep is None:
            return self.all_recorded_agent_ids
        if len(self._agents_id_per_step) == 0:
            return []

        if isinstance(timestep, int):
            return self._agents_id_per_step[timestep]
        else:
            unique_agent_ids= set()
            for valid_agent_ids in self._agents_id_per_step[timestep]:
                unique_agent_ids.update(valid_agent_ids)
            return list(unique_agent_ids)
    
    def get_current_active_agent_ids(self) -> list[int|str]:
        return list(set(self.get_valid_agent_ids(timestep=-1)) & set(self.current_track_agent_ids))
    
    def get_required_update_agent_ids(self, update_step: int = 1) -> list[int|str]:
        '''
        As some agents may not be required to be updated at current step. 
        Possible reason: (1) agent have already been updated and had future steps (2) agent is not active at current step (removed or marked as no update)
        update_step: the number of steps to be updated
        '''
        
        active_agent_ids = self.get_current_active_agent_ids()
        active_agents: list[BaseAgent] = self.get_agents(active_agent_ids)
        required_update_agent_ids = [a_id for (a_id, agent) in zip(active_agent_ids, active_agents) if agent.last_step <= self.current_step + update_step - 1]
        return required_update_agent_ids
        
    def get_valid_agents(self, timestep: int|slice|None = None) -> Generator[BaseAgent, None, None]:
        '''
        Get valid agent in spcified timesteps, default all agents in history.
        '''
        valid_ids = self.get_valid_agent_ids(timestep=timestep)
        for id in valid_ids:
            yield self._id_agent_mapping[id]
            
    def get_complete_history_active_agent_ids(self, history_step: int = 11) -> list[int|str]:
        '''
        Agents with complete history info and 
        '''
        active_agent_ids = self.get_current_active_agent_ids()
        active_agents: list[BaseAgent] = self.get_agents(active_agent_ids)
        complete_history_agent_ids = [a_id for (a_id, agent) in zip(active_agent_ids, active_agents) if agent.first_valid_step + history_step - 1 <= self.current_step]
    
        return complete_history_agent_ids
        
    def get_agents(self, ids:int|str|Iterable[int|str]) -> BaseAgent | None | list[BaseAgent|None]:
        if isinstance(ids, int) or isinstance(ids, str):
            if ids in self._id_agent_mapping.keys():
                return self._id_agent_mapping[ids]
            else:
                print(f"Warning: Getting agent with non-exist id '{ids}' in records")
                return None
        elif isinstance(ids, Iterable):
            ret_agents = []
            for id in ids:
                if id in self._id_agent_mapping.keys():
                    ret_agents.append(self._id_agent_mapping[id])
                else:
                    print(f"Warning: Getting agent with non-exist id '{id}' in records")
                    ret_agents.append(None)
            if len(set(ids)) != len(ids):
                print(f"Warning: Duplicate agents appear when getting agents in records")
            return ret_agents

    @staticmethod
    def _adapt_slice_to_range(slc:slice|int, original_length:int, idx_start:int=0, length:int|None=None) -> tuple[slice, int, int, int]:
        '''
        Original array A and target array B, B starting at idx_start for A, adapt a slice for A to B.
        idx_start is the relative postion of start of B to start of A. Negative value means start of B is before start of A, NOT inverse visiting A.
        
        :return: new slice, valid number of items, number of extra items before start, number of extra items after end. 
        '''
        if length is None:
            length = original_length
        if isinstance(slc, int):
            slc = slice(slc, slc+1 if slc != -1 else None)
            
        start = slc.start if slc.start is not None else 0
        stop = slc.stop if slc.stop is not None else original_length
        
        if start < 0:
            start += original_length
        if stop < 0:
            stop += original_length
        
        new_start = start - idx_start
        new_stop = stop - idx_start
        new_step = slc.step if slc.step is not None else 1
        
        # calculate item num
        valid_len, extra_prev, extra_next = 0, 0, 0 
        if (new_stop - new_start) ^ new_step >= 0:
            if new_step > 0:
                if new_start < 0:
                    extra_prev = - ((new_start - min(new_stop, 0)) // new_step)
                if new_stop > length:
                    extra_next = (new_start - max(new_start, length)) // new_step - (new_start - new_stop) // new_step
            else:   # step < 0
                if new_start > length - 1:
                    extra_prev = - ((new_start - max(new_stop, length-1)) // new_step)
                if new_stop < -1:
                    extra_next = (new_start - min(new_start, -1)) // new_step - (new_start - new_stop) // new_step
            valid_len = - ((new_start - new_stop) // new_step) - extra_prev - extra_next

        # convert to slice index value
        if new_step > 0:
            if new_start < 0:
                new_start %= new_step
            if new_stop < 0:
                new_stop = 0
        else:
            if new_start >= length:
                new_start -= ((new_start - length + 1) // new_step) * new_step
            if new_start < 0:
                new_start = 0
            if new_stop < 0:
                new_stop = None
            
        return slice(new_start, new_stop, new_step), valid_len, extra_prev, extra_next
    
    def __getitem__(self, key:slice|int|tuple[slice|int, int|str|Iterable[int|str]|slice, int|slice|None])-> tuple[int|str|list[int|str], np.ndarray, np.ndarray]:
        '''
        :param key: tuple(timesteps, agent ids, dimensions) agent ids indicate which agents among this period of time and dimensions indicate which dimensions to get
        Example: record[t_start:t_end], record[:, [agent_id_1, agent_id_2]], record[time, agent_id]
        :return: (agent ids, agent states array, agent states mask)
        '''
        if isinstance(key, slice) or isinstance(key, int):
            key_time = key
            agent_ids = self.get_valid_agent_ids(key_time)
            key_dim = slice(None)
        elif isinstance(key, tuple):
            key_time, agent_ids = key[0], key[1]
            if isinstance(agent_ids, slice):
                assert agent_ids == slice(None), f"Unrecognized vehicle id index {agent_ids}"
                agent_ids = self.get_valid_agent_ids(key_time)
            if len(key) >= 3:
                key_dim = key[2]
            else:
                key_dim = slice(None)
            assert isinstance(key_time, int) or isinstance(key_time, slice), f"Time index type should be slice/int, got {type(key_time)}"
            assert isinstance(agent_ids, int) or isinstance(agent_ids, str) or isinstance(agent_ids, Iterable), f"Time index type should be int/str/iterable, got {type(agent_ids)}"
        else:
            raise TypeError(f"Index type should be slice/int/tuple, got {type(key)}")
        
        valid_agents = self.get_agents(agent_ids)
        if not isinstance(valid_agents, list):
            valid_agents = [valid_agents]
        
        if isinstance(agent_ids, Iterable):
            num_agents = len(agent_ids)
            agent_ids = list(agent_ids)
        else:   # only one agent
            num_agents = 1
            
        adapt_key_time, num_timestep, extra_time_prev, extra_time_next = AgentRecordManager._adapt_slice_to_range(key_time, self.__len__())
        if (adapt_key_time.step > 0 and extra_time_next > 0) or (adapt_key_time.step < 0 and extra_time_prev > 0):
            raise IndexError(f"Unable to get states from future, total step: {self.__len__()}, visiting index: {key_time}")

        agents_states = np.zeros((num_timestep, num_agents, self.formatted_state_dim))
        valid_id_per_step = self._agents_id_per_step[adapt_key_time]
        agents_mask = [np.isin(np.array(agent_ids, dtype=object), np.array(valid_id_single_step, dtype=object))[None] for valid_id_single_step in valid_id_per_step]
        agents_mask = np.vstack(agents_mask).astype(bool) # (num_timestep, num_agents)

        # get agents states
        if num_timestep > 0 and num_agents > 0: 
            for i, agent in enumerate(valid_agents):
                if agent is None:
                    continue
                agent_key_time, valid_len, start_idx, __ = AgentRecordManager._adapt_slice_to_range(adapt_key_time, self.__len__(), agent.spawn_time_step, len(agent.states))
                single_agent_state, single_agent_mask = agent.formatted_state_with_mask(agent_key_time)
                agents_states[start_idx:start_idx+valid_len, i, :] = single_agent_state
                # agents_mask[start_idx:start_idx+valid_len, i] = single_agent_mask         # agents_mask is already generated from _agents_id_per_step
        
        # extend result to unrecorded history
        if extra_time_prev > 0:
            agents_states = np.concatenate((np.zeros((extra_time_prev, *agents_states.shape[1:])), agents_states), axis=0)
            agents_mask = np.concatenate((np.zeros((extra_time_prev, *agents_mask.shape[1:])).astype(bool), agents_mask), axis=0)
        if extra_time_next > 0:
            agents_states = np.concatenate((agents_states, np.zeros((extra_time_next, *agents_states.shape[1:]))), axis=0)
            agents_mask = np.concatenate((agents_mask, np.zeros((extra_time_next, *agents_mask.shape[1:])).astype(bool)), axis=0)
        
        # adapt output dimensions according to input
        if not isinstance(agent_ids, list):
            agents_states, agents_mask = agents_states.squeeze(axis=1)[..., key_dim], agents_mask.squeeze(axis=1)
        if not isinstance(key_time, slice):
            agents_states, agents_mask = agents_states.squeeze(axis=0)[..., key_dim], agents_mask.squeeze(axis=0)
            
        return agent_ids, agents_states, agents_mask
        
    
    def __setitem__(self, key: slice|int, value: tuple[list[int|str], np.ndarray, np.ndarray]):
        '''
        This function allows too much flexibility.
        value: (agent ids list, agent states array, agent states mask)
        '''
        raise NotImplementedError
    
    def track_id_agents(self, ids: int|str|Iterable[int|str]):
        if isinstance(ids, int) or isinstance(ids, str):
            ids = [ids]
        for id in ids:
            if id not in self.all_recorded_agent_ids:
                print(f"Warning: skipping tracking non-exist id {id}")
                continue
            if id not in self.current_track_agent_ids:
                self.current_track_agent_ids.append(id)
    
    def track_current_agents(self):
        '''
        Track all valid agents in current step.
        '''
        if len(self._agents_id_per_step) == 0:
            raise RuntimeError("Cannot track agents when no data is recorded")
        for id in self._agents_id_per_step[-1]:
            if id not in self.current_track_agent_ids:
                self.current_track_agent_ids.append(id)
                
    def track_next_step_agents(self):
        if len(self._agents_id_future_step) == 0:
            return
        for id in self._agents_id_future_step[-1]:
            if id not in self.current_track_agent_ids:
                self.current_track_agent_ids.append(id)
                
    def formatted_update(self, dic: dict, proceed=True) -> int:
        raise NotImplementedError
    
    def update(self, agents_id: int|str|Iterable[int|str], agents_states: np.ndarray, agents_mask: np.ndarray|None=None, proceed: bool=True) -> int:
        '''
        Update record with (agent id or list of agent_id, agents_states (T) * (N) * D, (mask))
        '''
        if (isinstance(agents_id, list) and agents_states.ndim == 2) or (not isinstance(agents_id, list) and agents_states.ndim == 1):
            agents_states = agents_states[None, ...]
            if agents_mask is not None:
                agents_mask = agents_mask[None, ...]
        
        if isinstance(agents_id, int) or isinstance(agents_id, str):
            agents_id: list[int|str] = [agents_id]
            agents_states = agents_states[:, None, :]
            if agents_mask is not None:
                agents_mask = agents_mask[:, None, :]
        
        update_step = agents_states.shape[0]
        extra_future_step = update_step - len(self._agents_id_future_step)
        for __ in range(extra_future_step):
            self._agents_id_future_step.append([])
            
        for i, id in enumerate(agents_id):
            if id not in self.current_track_agent_ids:
                continue
            agent = self._id_agent_mapping[id]
            
            if agents_mask is not None:
                agent_valid_step = np.where(agents_mask[:, i])[0]
                for s in range(update_step):
                    if s not in agent_valid_step and id in self._agents_id_future_step[s]:
                        self._agents_id_future_step[s].remove(id)
                    elif s in agent_valid_step and id not in self._agents_id_future_step[s]:
                        self._agents_id_future_step[s].append(id)
                agent.update(agents_states[:, i], agents_mask[:, i], start=self.current_step - agent.spawn_time_step + 1)
            else:
                for s in range(update_step):
                    if id not in self._agents_id_future_step[s]:
                        self._agents_id_future_step[s].append(id)
                agent.update(agents_states[:, i], start=self.current_step - agent.spawn_time_step + 1)
        
        if proceed:    
            self.proceed_step(update_step)
            return update_step
        else:
            return 0
    
    def proceed_step_to(self, to_step:int) -> None:
        if to_step <= self.current_step:
            print(f"Warning: proceeding to history timestep {to_step} is skipped, current step index {self.current_step}")
            return
        self.proceed_step(to_step - self.current_step)
    
    def proceed_step(self, step:int=1) -> None:
        '''
        Proceed record directly to future to update records without controlling agents
        '''
        # Update tracked but not updated agent with mask False
        for id in self.current_track_agent_ids:
            agent = self._id_agent_mapping[id]
            missing_step = step + self.current_step - agent.last_step 
            if missing_step > 0:
                assert agent.complete_info, f"Agent {agent.id} must be updated at each time step"
                agent.update(np.zeros((missing_step, agent.state_dim)), np.zeros(missing_step).astype(bool))
        
        for __ in range(step):
            if len(self._agents_id_future_step) > 0:
                self._agents_id_per_step.append(self._agents_id_future_step.pop(0))
            else:
                self._agents_id_per_step.append([])
    
    def add_agents_from_history_states(self, agents_type:type|list[type], agents_id: int|str|list[int|str], agents_states: np.ndarray|BaseState|list[BaseState], 
                                       agents_mask: np.ndarray|None=None, **agents_attrib:dict[str, Any|list[Any]]):
        if isinstance(agents_states, np.ndarray):
            if (isinstance(agents_id, list) and agents_states.ndim == 2) or (not isinstance(agents_id, list) and agents_states.ndim == 1):
                update_step = 1
            else:
                update_step = agents_states.shape[0]
            start = self.__len__()-update_step
        elif isinstance(agents_states, BaseState):
            start = self.__len__() - len(agents_states)
        elif isinstance(agents_states, list):
            start = [self.__len__() - len(single_state) for single_state in agents_states]
        
        self.add_agents_from_states(start=start, 
                                    agents_type=agents_type, 
                                    agents_id=agents_id, 
                                    agents_states=agents_states, 
                                    agents_mask=agents_mask,
                                    **agents_attrib)
    
    def add_agents_from_states(self, start: int|list[int], agents_type:type|list[type], agents_id: int|str|list[int|str], agents_states: np.ndarray|BaseState|list[BaseState], 
                               agents_mask: np.ndarray|None=None, **agents_attrib:dict[str, Any|list[Any]]):
        '''
        Create agents from states and add to record. only valid agents in the LATEST or NEXT record step will be tracked and updated for further simulation.
        '''
        if isinstance(agents_states, np.ndarray):
            
            if (isinstance(agents_id, list) and agents_states.ndim == 2) or (not isinstance(agents_id, list) and agents_states.ndim == 1):
                agents_states = agents_states[None, ...]
                if agents_mask is not None:
                    agents_mask = agents_mask[None, ...]
            
            if not isinstance(agents_id, list):
                agents_id: list[int|str] = [agents_id]
                agents_states = agents_states[:, None, :]
                if agents_mask is not None:
                    agents_mask = agents_mask[:, None, :]
                    
        else:
            if not isinstance(agents_id, list):
                agents_id: list[int|str] = [agents_id]
            if not isinstance(agents_states, list):
                agents_states: list[BaseState] = [agents_states]    
                
        if not isinstance(agents_type, list):
            agents_type = [agents_type] * len(agents_id)
            
        if not isinstance(start, list):
            start = [start] * len(agents_id)
            
        assert len(start) == len(agents_type) == len(agents_id), f"Unmatched shape: agent type {len(agents_type)} - agent id {len(agents_id)} - time start {len(start)}"
        
        for name, attrib in agents_attrib.items():
            if not isinstance(attrib, list):
                agents_attrib[name] = [attrib] * len(agents_id)
            assert len(agents_attrib[name]) == len(agents_id), f"Unmatched shape: {agents_attrib[name]} {len(agents_type)} - agent id {len(agents_id)}"
        agents_attrib_sep = [{name: attrib[i] for name, attrib in agents_attrib.items()} for i in range(len(agents_id))]
            
        
        if isinstance(agents_states, list):
            assert len(agents_states) == len(agents_id), f"Unmatched shape of agent states {len(agents_states)} and vehicle id {len(agents_id)}"
        
        agents_to_add: list[type] = []
        
        for i, a_id in enumerate(agents_id):
            if a_id in self._id_agent_mapping.keys():
                raise ValueError(f"Unable to add agent with id '{a_id}' to record, id already existed")
            if isinstance(agents_states, np.ndarray):
                if agents_mask is None:
                    agents_to_add.append(agents_type[i](id=a_id, spawn_time_step=start[i], warm_up_states=agents_states[:, i, :], **agents_attrib_sep[i]))
                else:
                    agents_to_add.append(agents_type[i](id=a_id, spawn_time_step=start[i], warm_up_states=agents_states[:, i, :], 
                                                        warm_up_mask=agents_mask[:, i], complete_info=False, **agents_attrib_sep[i]))
            else:
                agents_to_add.append(agents_type[i](id=a_id, spawn_time_step=start[i], warm_up_states=agents_states[i], **agents_attrib_sep[i]))
        
        self.add_agents(agents_to_add)
    
    def add_agents(self, agents:BaseAgent|list[BaseAgent]):
        '''
        Add agents to simulation record, only valid agents in the LATEST or NEXT record step will be tracked and updated automatically for further simulation.
        '''
        if isinstance(agents, BaseAgent):
            agents:list[BaseAgent] = [agents]
            
        for agent in agents:
            if agent.id in self._id_agent_mapping.keys():
                raise ValueError(f"Cannot add agent to record: agent id '{agent.id}' already existed")
            assert agent.formatted_state_dim == self.formatted_state_dim, f"Unmatched formatted state dim {agent.formatted_state_dim} for {type(agent)} to supposed dim {self.formatted_state_dim}"
            self._id_agent_mapping[agent.id] = agent
            
            agent_valid_step = np.where(agent.states_mask)[0] + agent.spawn_time_step
            extra_future_step = agent_valid_step[-1] - self.current_step - len(self._agents_id_future_step) if len(agent_valid_step) > 0 else 0
            for __ in range(extra_future_step):
                self._agents_id_future_step.append([])
            
            for step in agent_valid_step:
                if step < 0:
                    continue
                if step <= self.current_step:
                    self._agents_id_per_step[step].append(agent.id)
                else:
                    self._agents_id_future_step[step - self.current_step - 1].append(agent.id)
            
            if self.current_step in agent_valid_step or self.current_step + 1 in agent_valid_step:
                 self.current_track_agent_ids.append(agent.id)
                    
    def delete_id_agents(self, agents_id: int|str|Iterable[int|str]):
        '''
        Delete agents from controlling agents, the state of these agents will not be updated later. 
        Note that once an agent is deleted, the same id shall not be added again. If the agent leaves 
        temporarily, it should not be deleted but updated with invalid state mask.
        '''
        if isinstance(agents_id, int) or isinstance(agents_id, str):
            agents_id:list[int|str] = [agents_id]
        
        for id in agents_id:
            if id in self.current_track_agent_ids:
                self.current_track_agent_ids.remove(id)
                for ftr_ids in self._agents_id_future_step:
                    if id in ftr_ids:
                        ftr_ids.remove(id)
            else:
                print(f"Warning: removal of unknown agent '{id}' is skipped")
                
    def delete_agents(self, agents: BaseAgent|list[BaseAgent]):
        if isinstance(agents, BaseAgent):
            agents:list[BaseAgent] = [agents]
        
        for agent in agents:
            if agent is self._id_agent_mapping[agent.id]:
                if agent.id in self.current_track_agent_ids:
                    self.current_track_agent_ids.remove(agent.id)
                else:
                    print(f"Warning: removal of unknown agent '{agent.id}' is skipped")
            else:
                print(f"Warning: removal of unknown agent '{agent.id}' is skipped")
                
    def export(self, sparse: bool=True) -> dict:
        raise NotImplementedError
    
    def load(self, dic: dict, sparse: bool=True, proceed: bool=True):
        raise NotImplementedError
    
    def formatted_state(self, past_time_steps:int, agent_ids:int|str|Iterable[int|str]|None=None) -> tuple[list[int|str], np.ndarray, np.ndarray]:
        if agent_ids is None:
            a_id, a_states, a_mask = self[-past_time_steps:]
        else:
            if isinstance(agent_ids, int) or isinstance(agent_ids, str):
                agent_ids = [agent_ids]
            a_id, a_states, a_mask = self[-past_time_steps:, agent_ids]
        return a_id, a_states.transpose(1, 0, 2), a_mask.transpose(1, 0)

class TrafficLightManager(AgentRecordManager):
    def __init__(self, formatted_tl_state_dim: int=4):
        super().__init__(formatted_tl_state_dim)
        self._id_agent_mapping: dict[int|str, TrafficLight]
        
    @classmethod
    def create_from_file(cls, record_path: str, formatted_tl_state_dim: int=4, sparse: bool=True, proceed: bool=False):
        obj = cls(formatted_tl_state_dim)
        with open(record_path, "rb") as m:
            record_info:dict = pickle.load(m)
        obj.load(record_info, sparse=sparse, proceed=proceed)
        return obj
 
    def get_phase(self, tls_id:int|str|Iterable[int|str]) -> str|int|list[str|int]:
        if not isinstance(tls_id, Iterable):
            return self._id_agent_mapping[tls_id].phase
        else:
            return [self._id_agent_mapping[tl_id].phase for tl_id in tls_id]
        
    def get_location(self, tls_id:int|str|Iterable[int|str]) -> np.ndarray:
        if not isinstance(tls_id, Iterable):
            return self._id_agent_mapping[tls_id].static_pos
        else:
            location = [self._id_agent_mapping[tl_id].static_pos for tl_id in tls_id]
            return np.vstack(location) if len(location) > 0 else []
        
    def get_start_point(self, tls_id:int|str|Iterable[int|str]) -> np.ndarray:
        if not isinstance(tls_id, Iterable):
            return self._id_agent_mapping[tls_id].start_point
        else:
            start_point = [self._id_agent_mapping[tl_id].start_point for tl_id in tls_id]
            return np.vstack(start_point) if len(start_point) > 0 else []
        
    def set_phase(self, tls_id:int|str|Iterable[int|str], tls_phase: str|Iterable[str]):
        if isinstance(tls_id, (int, str)):
            tls_id = [tls_id]
            assert isinstance(tls_phase, str), f"Type of attributes should match with type of tls ids, got {type(tls_phase)} and {type(tls_id[0])}"
            tls_phase = [tls_phase]
        for tl_id, tl_phase in zip(tls_id, tls_phase):
            self._id_agent_mapping[tl_id].phase = tl_phase
            
    def set_location(self, tls_id:int|str|Iterable[int|str], tls_loc: np.ndarray|Iterable[np.ndarray]):
        if isinstance(tls_id, (int, str)):
            tls_id = [tls_id]
            assert isinstance(tls_loc, np.ndarray), f"Type of attributes should match with type of tls ids, got {type(tls_loc)} and {type(tls_id)}"
            tls_loc = [tls_loc]
        for tl_id, tl_loc in zip(tls_id, tls_loc):
            self._id_agent_mapping[tl_id].static_pos = tl_loc
            
    def set_start_point(self, tls_id:int|str|Iterable[int|str], tls_start: np.ndarray|Iterable[np.ndarray]):
        if isinstance(tls_id, (int, str)):
            tls_id = [tls_id]
            assert isinstance(tls_start, np.ndarray), f"Type of attributes should match with type of tls ids, got {type(tls_start)} and {type(tls_id)}"
            tls_start = [tls_start]
        for tl_id, tl_start in zip(tls_id, tls_start):
            self._id_agent_mapping[tl_id].start_point = tl_start
    
    def add_agents_from_states(self, 
                               start: int|list[int],
                               tls_id: int|str|list[int|str], 
                               tls_states: np.ndarray|TrafficLightState|list[TrafficLightState], 
                               tls_mask: np.ndarray|None=None,
                               tls_phase: str|list[str]|None=None, 
                               tls_loc: np.ndarray|list[np.ndarray]|None=None,
                               tls_start: np.ndarray|list[np.ndarray]|None=None):
        '''
        Create traffic lights from states and add to record. only valid tls in the LATEST or NEXT record step will be tracked and updated for further simulation.
        '''
        extra_attrib = {}
        if tls_phase is not None:
            extra_attrib["phase"] = tls_phase
        if tls_loc is not None:
            extra_attrib["static_pos"] = tls_loc
        if tls_start is not None:
            extra_attrib["start_point"] = tls_start
            
        super().add_agents_from_states(start=start,
                                       agents_type=TrafficLight,
                                       agents_id=tls_id,
                                       agents_states=tls_states,
                                       agents_mask=tls_mask,
                                       **extra_attrib)
        
    def add_agents_from_history_states(self, 
                                       tls_id: int|str|list[int|str], 
                                       tls_states: np.ndarray|TrafficLightState|list[TrafficLightState], 
                                       tls_mask: np.ndarray|None=None,
                                       tls_phase: str|list[str]|None=None, 
                                       tls_loc: np.ndarray|list[np.ndarray]|None=None, 
                                       tls_start: np.ndarray|list[np.ndarray]|None=None):
        if isinstance(tls_states, np.ndarray):
            if (isinstance(tls_id, list) and tls_states.ndim == 2) or (not isinstance(tls_id, list) and tls_states.ndim == 1):
                update_step = 1
            else:
                update_step = tls_states.shape[0]
            start = self.__len__()-update_step
        elif isinstance(tls_states, TrafficLightState):
            start = self.__len__() - len(tls_states)
        elif isinstance(tls_states, list):
            start = [self.__len__() - len(single_state) for single_state in tls_states]
        self.add_agents_from_states(start=start, 
                                    tls_id=tls_id, 
                                    tls_states=tls_states, 
                                    tls_mask=tls_mask,
                                    tls_phase=tls_phase,
                                    tls_loc=tls_loc,
                                    tls_start=tls_start)

    
    def formatted_update(self, dic: dict, proceed=True) -> int:
        if "dynamic_polyline_id" not in dic.keys() or len(dic["dynamic_polyline_id"]) == 0:
            return 0
        return self.update(agents_id=dic["dynamic_polyline_id"],
                           agents_states=dic["dynamic_polyline_states"].transpose(1, 0, 2),
                           agents_mask=dic["dynamic_polyline_mask"].transpose(1, 0) if "dynamic_polyline_mask" in dic.keys() else None,
                           proceed=proceed)
        
    def formatted_state(self, past_time_steps: int, tl_ids: int | str | list[int | str] | None = None) -> dict:
        tl_id, tl_state, tl_mask = super().formatted_state(past_time_steps, tl_ids)
        tl_state = np.concatenate((tl_state, tl_mask[..., None].astype(tl_state.dtype), onehot_time_embedding(shape_prefix=tl_state.shape[:-1], time_axis=-1)), axis=-1)
        return {"dynamic_polyline_id": tl_id,
                "dynamic_polyline_states": tl_state,
                "dynamic_polyline_mask": tl_mask}
    
    def get_agents(self, ids: int | str | list[int|str]) -> TrafficLight | list[TrafficLight]:
        return super().get_agents(ids)
    
    def load(self, dic: dict, sparse: bool = True, proceed: bool = True):
        if self.__len__() > 0:
            raise RuntimeError("Cannot load previosly initialized record with dict")
        
        if sparse:  
            tls_id, tls_states, tls_mask = sparse2dense(dic["dynamic_polyline_id_per_step"], dic["dynamic_polyline_state_per_step"])
            tls_states = tls_states.transpose(1, 0, 2)
            tls_mask = tls_mask.transpose(1, 0) 
        else:
            tls_id:list[int|str] = dic["dynamic_polyline_id"]
            tls_states:np.ndarray = dic["dynamic_polyline_states"].transpose(1, 0, 2)
            tls_mask:np.ndarray = dic["dynamic_polyline_mask"].transpose(1, 0)
        
        extra_tls_attrib = {}
        if "dynamic_polyline_phase" in dic.keys():
            extra_tls_attrib["tls_phase"] = dic["dynamic_polyline_phase"]
        if "dynamic_polyline_location" in dic.keys():
            extra_tls_attrib["tls_loc"] = dic["dynamic_polyline_location"]
        if "dynamic_polyline_start" in dic.keys():
            extra_tls_attrib["tls_start"] = dic["dynamic_polyline_start"]
            
        self.add_agents_from_states(start = self.current_step + 1,
                                    tls_id = tls_id,
                                    tls_states = tls_states,
                                    tls_mask = tls_mask,
                                    **extra_tls_attrib)
        
        if proceed:
            self.proceed_step(tls_states.shape[0])
            
    def export(self, sparse: bool=True) -> dict:
        if sparse:
            ret_dict = {"dynamic_polyline_id_per_step": self._agents_id_per_step,
                        "dynamic_polyline_state_per_step": []}
            for step, dynamic_polyline_id_single_step in enumerate(self._agents_id_per_step):
                states_single_step = []
                dynamic_polyline_single_step: list[TrafficLight] = self.get_agents(dynamic_polyline_id_single_step)
                for tl in dynamic_polyline_single_step:
                    states_single_step.append(tl.get_absolute_states(step))
                if len(states_single_step) > 0:
                    ret_dict["dynamic_polyline_state_per_step"].append(np.stack(states_single_step, axis=0))
                else:
                    ret_dict["dynamic_polyline_state_per_step"].append(states_single_step)
        else:
            tl_id, tls_states, tls_mask = self[:]
            ret_dict = {"dynamic_polyline_id": tl_id,
                        "dynamic_polyline_states": tls_states.transpose(1, 0, 2),
                        "dynamic_polyline_mask": tls_mask.transpose(1, 0)}
        return ret_dict
    
class TrafficLightRuleManager(TrafficLightManager):
    def formatted_state(self, past_time_steps, tl_ids = None):
        scenario = super().formatted_state(past_time_steps, tl_ids)
        scenario.update({"all_dynamic_polyline_id": self.all_recorded_agent_ids,
                         "all_dynamic_polyline_phase": self.get_phase(self.all_recorded_agent_ids)})
        return scenario

class VehicleRecordManager(AgentRecordManager):
    def __init__(self, formatted_state_dim: int, default_vehicle_type: type=Vehicle):
        super().__init__(formatted_state_dim)
        self.default_vehicle_type = default_vehicle_type
        
    def add_agents_from_states(self, 
                               start:int|list[int], 
                               vehicles_id: int|str|list[int|str], 
                               vehicles_states: np.ndarray|RoadUserState|list[RoadUserState], 
                               vehicles_mask: np.ndarray|None=None,
                               vehicles_static: np.ndarray|list[np.ndarray]|None=None,
                               vehicles_type: type|list[type]=type(None)):
        '''
        Create vehicles from states and add to record. only valid vehicles in the LATEST or NEXT record step will be tracked and updated for further simulation.
        '''
        if vehicles_type is type(None):
            vehicles_type = self.default_vehicle_type
        super().add_agents_from_states(start=start,
                                       agents_type=vehicles_type,
                                       agents_id=vehicles_id,
                                       agents_states=vehicles_states,
                                       agents_mask=vehicles_mask,
                                       static_lwh=vehicles_static)
    
    
    def add_agents_from_history_states(self, vehicles_id: int|str|list[int|str], 
                                       vehicles_states: np.ndarray|RoadUserState|list[RoadUserState], 
                                       vehicles_mask: np.ndarray|None=None,
                                       vehicles_static: np.ndarray|list[np.ndarray]|None=None, 
                                       vehicles_type: type|list[type]=type(None)):
        '''
        Create vehicles from states and align the last step of states to the latest record.
        '''
        if vehicles_type is type(None):
            vehicles_type = self.default_vehicle_type
        if isinstance(vehicles_states, np.ndarray):
            if (isinstance(vehicles_id, list) and vehicles_states.ndim == 2) or (not isinstance(vehicles_id, list) and vehicles_states.ndim == 1):
                update_step = 1
            else:
                update_step = vehicles_states.shape[0]
            start = self.__len__()-update_step
        elif isinstance(vehicles_states, RoadUserState):
            start = self.__len__() - len(vehicles_states)
        elif isinstance(vehicles_states, list):
            start = [self.__len__() - len(single_state) for single_state in vehicles_states]
        self.add_agents_from_states(start=start, 
                                    vehicles_id=vehicles_id, 
                                    vehicles_states=vehicles_states, 
                                    vehicles_mask=vehicles_mask,
                                    vehicles_static=vehicles_static,
                                    vehicles_type=vehicles_type)
    
    def formatted_update(self, dic: dict, proceed=True) -> int:
        if "vehicle_id" not in dic.keys() or len(dic["vehicle_id"]) == 0:
            return 0
        return self.update(vehicles_id=dic["vehicle_id"],
                           vehicles_states=dic["vehicle_states"].transpose(1, 0, 2),
                           vehicles_mask=dic["vehicle_mask"].transpose(1, 0) if "vehicle_mask" in dic.keys() else None,
                           proceed=proceed)
        
    def formatted_state(self, past_time_steps: int, vehicle_ids: int | str | list[int | str] | None = None) -> dict:
        v_id, v_state, v_mask = super().formatted_state(past_time_steps, vehicle_ids)
        v_state = np.concatenate((v_state, onehot_time_embedding(shape_prefix=v_state.shape[:-1], time_axis=-1)), axis=-1)
        return {"vehicle_id": v_id,
                "vehicle_states": v_state,
                "vehicle_mask": v_mask}
    
    def update(self, vehicles_id: int|str|list[int|str], vehicles_states: np.ndarray, vehicles_mask: np.ndarray|None=None, proceed: bool=True) -> int:
        return super().update(agents_id=vehicles_id, agents_states=vehicles_states, agents_mask=vehicles_mask, proceed=proceed)
    
    def export(self, sparse: bool=True) -> dict:
        if sparse:
            ret_dict = {"vehicle_id_per_step": self._agents_id_per_step,
                        "vehicle_state_per_step": [],
                        "vehicle_static_attribute": {}}
            for step, vehicles_id_single_step in enumerate(self._agents_id_per_step):
                states_single_step = []
                vehicles_single_step: list[Vehicle] = self.get_agents(vehicles_id_single_step)
                for vehicle in vehicles_single_step:
                    states_single_step.append(vehicle.get_absolute_states(step))
                    if vehicle.id not in ret_dict["vehicle_static_attribute"]:
                        ret_dict["vehicle_static_attribute"][vehicle.id] = vehicle.static_lwh
                if len(states_single_step) > 0:
                    ret_dict["vehicle_state_per_step"].append(np.stack(states_single_step, axis=0))
                else:
                    ret_dict["vehicle_state_per_step"].append(states_single_step)
        else:
            v_id, vehicle_states, vehicle_mask = self[:]
            ret_dict = {"vehicle_id": v_id,
                        "vehicle_states": vehicle_states.transpose(1, 0, 2),
                        "vehicle_mask": vehicle_mask.transpose(1, 0)}
        return ret_dict
                
    def load(self, dic: dict, sparse: bool=True, proceed: bool=True):
        if self.__len__() > 0:
            raise RuntimeError("Cannot load previosly initialized record with dict")
        
        if sparse:  
            vehicles_id, vehicles_states, vehicles_mask = sparse2dense(dic["vehicle_id_per_step"], dic["vehicle_state_per_step"])
            vehicles_states = vehicles_states.transpose(1, 0, 2)
            vehicles_mask = vehicles_mask.transpose(1, 0) 
            vehicles_static = [dic["vehicle_static_attribute"][v_id] for v_id in vehicles_id]
            if "vehicle_type" in dic.keys():
                vehicles_type = [locate(dic["vehicle_type"][v_id]) for v_id in vehicles_id]
            else:
                vehicles_type = [self.default_vehicle_type] * len(vehicles_id)
        else:
            vehicles_id:list[int|str] = dic["vehicle_id"]
            vehicles_states:np.ndarray = dic["vehicle_states"].transpose(1, 0, 2)
            vehicles_mask:np.ndarray = dic["vehicle_mask"].transpose(1, 0)    
            valid_vehicle = np.any(vehicles_mask, axis=0)
            valid_index = list(np.arange(len(vehicles_id)).astype(np.intp)[valid_vehicle])
            valid_vehicles_id = [vehicles_id[i] for i in valid_index]
            vehicles_states = vehicles_states[:, valid_vehicle]
            vehicles_mask = vehicles_mask[:, valid_vehicle]
            
            if "vehicle_type" in dic.keys():
                vehicles_type = [locate(dic["vehicle_type"][v_id]) for v_id in vehicles_id]
            else:
                vehicles_type = [self.default_vehicle_type] * len(vehicles_id)
            
            vehicles_static = []
            
            for i in range(len(valid_vehicles_id)):
                vehicle_states_dim, vehicle_static_dim = vehicles_type[i](id=None).state_dim, self.formatted_state_dim - vehicles_type[i](id=None).state_dim
                vehicles_static.append(vehicles_states[:, i, -vehicle_static_dim:][vehicles_mask[:, i]][0])
            vehicles_id = valid_vehicles_id
            vehicles_states = vehicles_states[..., :vehicle_states_dim]
        
        
        self.add_agents_from_states(start=self.current_step + 1,
                                    vehicles_id=vehicles_id,
                                    vehicles_states=vehicles_states,
                                    vehicles_mask=vehicles_mask,
                                    vehicles_static=vehicles_static,
                                    vehicles_type=vehicles_type)
        if proceed:
            self.proceed_step(vehicles_states.shape[0])
            
    def simple_check_conflict(self, new_positions: np.ndarray | torch.Tensor | None = None, min_dist: float = 6, 
                               time_step: int=-1, verbose: bool=False, gpu: bool=False, extra_only: bool=False) -> bool | tuple[np.ndarray, np.ndarray]:
        '''
        :return: conflict (simple) / conflict matrix & agent_ids (verbose) - Note that diagnal elements are always True 
        ''' 
        if time_step < 0:
            assert time_step + self.current_step + 1 >= 0, f"Time step {time_step} is out of range"
            time_step = time_step + self.current_step + 1
        else:
            assert time_step <= self.current_step, f"Time step {time_step} is out of range"
        if len(self.get_valid_agent_ids(timestep=time_step)) > 0:
            all_positions = np.stack([self._id_agent_mapping[v_id].get_pos(time_step) for v_id in self.get_valid_agent_ids(timestep=time_step)], axis=0)
        else:
            all_positions = np.empty((0, 2))
        if new_positions is not None:
            assert new_positions.shape[-1] == 2, f"The shape for the last dim of position should be 2, got {new_positions.shape}"
            new_positions = new_positions.reshape(-1, 2)
            if not gpu:
                if isinstance(new_positions, torch.Tensor):
                    new_positions = new_positions.cpu().numpy()
                all_positions = np.concatenate((all_positions, new_positions), axis=0)
            else:
                if isinstance(new_positions, np.ndarray):
                    new_positions = torch.from_numpy(new_positions)
                all_positions = torch.cat((torch.from_numpy(all_positions).cuda(), new_positions.cuda()), dim=0)
        elif gpu:
            all_positions = torch.from_numpy(all_positions).cuda()
            
        if not gpu:
            coll_mat = np.linalg.norm(all_positions[None, ...] - all_positions[:, None, ...], axis=-1) <= min_dist
        else:
            coll_mat = (torch.norm(all_positions[None, ...] - all_positions[:, None, ...], dim=-1) < min_dist).cpu().numpy()
        
        
        if verbose:
            if extra_only:
                return coll_mat[-new_positions.shape[0]:], self.get_valid_agent_ids(-1)
            else:
                return coll_mat, self.get_valid_agent_ids(-1)
        else:
            self_mask = np.eye(coll_mat.shape[0]).astype(bool)
            if extra_only:
                return np.any(coll_mat[-new_positions.shape[0]:][~self_mask[-new_positions.shape[0]:]])
            else:
                return np.any(coll_mat[~self_mask])
            
    def strict_check_conflict(self, new_positions: np.ndarray | torch.Tensor | None = None, new_lwh: np.ndarray | torch.Tensor | None = None, 
                              verbose: bool=False, extra_only: bool=False) -> np.ndarray | np.ndarray:
        '''
        Check collision of vehicles in simulator using bounding box. Written by Yizhou Xu. Modified by Shu Li. 
        '''
        import shapely.geometry as geo
        import shapely.affinity as aff
        vehicle_polygon_list = []
        for vehicle_id in self.current_track_agent_ids:
            l, w, h = self.get_agents(vehicle_id).static_lwh
            polygon = geo.Polygon([[-l/2, -w/2], [l/2, -w/2], [l/2, w/2], [-l/2, w/2]])
            polygon = aff.rotate(polygon, self.get_agents(vehicle_id).heading[-1], use_radians=True)
            polygon = aff.translate(polygon, self.get_agents(vehicle_id).x[-1], self.get_agents(vehicle_id).y[-1])
            vehicle_polygon_list.append(polygon)
        num_vehicles = len(self.current_track_agent_ids)
        agent_colli_mat = np.zeros((num_vehicles, num_vehicles), dtype=bool) + np.identity(num_vehicles, dtype=bool)
        collision_flag = False
        for i in range(num_vehicles):
            for j in range(i+1, num_vehicles):
                if vehicle_polygon_list[i].intersects(vehicle_polygon_list[j]):
                    agent_colli_mat[i, j] = agent_colli_mat[j, i] = True
                    collision_flag = True
        if verbose:
            return agent_colli_mat, self.current_track_agent_ids
        else:
            return collision_flag
             
class TLVectorMap(BaseVectorMap, TrafficLightManager):
    def __init__(self, formatted_map_state_dim: Iterable[int]=[20, 9], formatted_tl_state_dim:int=4):
        BaseVectorMap.__init__(self, formatted_map_state_dim)
        TrafficLightManager.__init__(self, formatted_tl_state_dim)
        
    @classmethod
    def create_from_file(cls, data_path: str, formatted_map_state_dim: Iterable[int]=[20, 9], formatted_tl_state_dim:int=4,
                         strict: bool=False, sparse: bool=True, proceed: bool=False):
        obj = cls(formatted_map_state_dim, formatted_tl_state_dim)
        with open(data_path, "rb") as m:
            data_info: dict = pickle.load(m)
        obj.load(data_info, strict=strict, sparse=sparse, proceed=proceed)
        return obj
    
    def load(self, dic: dict, strict: bool=False, sparse: bool=True, proceed: bool=True):
        if set(["map", "polyline"]) & set(dic.keys()) != set():
            BaseVectorMap.load(self, dic=dic, strict=strict)
        if set(["dynamic_polyline_id", "dynamic_polyline_states", "dynamic_polyline_mask"]) <= set(dic.keys()) or set(["dynamic_polyline_id_per_step", "dynamic_polyline_state_per_step"]) <= set(dic.keys()):
            TrafficLightRuleManager.load(self, dic=dic, sparse=sparse, proceed=proceed)
         
class RouteTLVectorMap(RouteVectorMap, TrafficLightRuleManager):
    def __init__(self, formatted_map_state_dim: Iterable[int]=[20, 9], formatted_tl_state_dim:int=4, device:str='cuda'):
        RouteVectorMap.__init__(self, formatted_map_state_dim, device)
        TrafficLightRuleManager.__init__(self, formatted_tl_state_dim)
        
    @classmethod
    def create_from_file(cls, data_path: str, formatted_map_state_dim: Iterable[int]=[20, 9], formatted_tl_state_dim:int=4, device:str='cuda',
                         strict: bool=False, sparse: bool=True, proceed: bool=False):
        obj = cls(formatted_map_state_dim, formatted_tl_state_dim, device)
        with open(data_path, "rb") as m:
            data_info: dict = pickle.load(m)
        obj.load(data_info, strict=strict, sparse=sparse, proceed=proceed)
        return obj
    
    def load_map(self, dic: dict, strict: bool=False):
        RouteVectorMap.load(self, dic=dic, strict=strict)
    
    def load_tls(self, dic: dict, sparse: bool=True, proceed: bool=True):
        TrafficLightRuleManager.load(self, dic=dic, sparse=sparse, proceed=proceed)
        
    def load(self, dic: dict, strict: bool=False, sparse: bool=True, proceed: bool=True):
        if set(["map", "routes", "polyline"]) & set(dic.keys()) != set():
            self.load_map(dic=dic, strict=strict)
        if set(["dynamic_polyline_id", "dynamic_polyline_states", "dynamic_polyline_mask"]) <= set(dic.keys()) or set(["dynamic_polyline_id_per_step", "dynamic_polyline_state_per_step"]) <= set(dic.keys()):
            self.load_tls(dic=dic, sparse=sparse, proceed=proceed)
            self.update_tls_attrib_from_map()
    
    def update_tls_attrib_from_map(self):
        tls_id = TrafficLightRuleManager.get_valid_agent_ids(self)
        tls_phase = self.get_phase(tls_id)
        if None in tls_phase:
            new_tls_phase = self.get_intersection_polyline_phase(tls_id)
            tls_phase = [phase if phase is not None else new_phase for phase, new_phase in zip(tls_phase, new_tls_phase)]
            self.set_phase(tls_id, tls_phase)
            
        tls_loc, tls_start = [], []
        for tl_id in tls_id:
            if tl_id in self.polyline_dict.keys():
                tls_loc.append(self.polyline_dict[tl_id].center_location)
                tls_start.append(self.polyline_dict[tl_id].points[0:1])
            else:
                print(f"Warning: Traffic light {tl_id} not found in static map")
                tls_loc.append(None)
                tls_start.append(None)
        self.set_location(tls_id, tls_loc)
        self.set_start_point(tls_id, tls_start)
    
    def export(self, sparse: bool=True) -> dict:
        return {**RouteVectorMap.export(self), **TrafficLightRuleManager.export(self, sparse)}
    
    def polyline_formatted_state(self, polyline_ids: int|str|Iterable[int|str]|None = None) -> dict:
        return RouteVectorMap.formatted_state(self, polyline_ids)
    
    def formatted_state(self, past_time_steps: int, polyline_ids: int|str|Iterable[int|str]|None = None) -> dict:
        traffic_light_ids = [p_id for p_id in polyline_ids if p_id in TrafficLightRuleManager.get_valid_agent_ids(self)]
        return {**RouteVectorMap.formatted_state(self, polyline_ids), **TrafficLightRuleManager.formatted_state(self, past_time_steps, traffic_light_ids)}
    
    def formatted_update(self, dic: dict, proceed: bool=True) -> int:
        return TrafficLightRuleManager.formatted_update(self, dic, proceed)

class ScenarioManager():
    def __init__(self,
                 agent_records: AgentRecordManager,
                 vector_map: BaseVectorMap,
                 history_step: int):
        self.agent_records = agent_records
        self.vector_map = vector_map
        self.history_step = history_step
        
    @property
    def current_step(self):
        return self.agent_records.current_step    
    
    def get_complete_history_active_agent_ids(self) -> list[int|str]:
        return self.agent_records.get_complete_history_active_agent_ids(self.history_step)
    
    def prepare_formatted_scenario(self, history_step:int|None=None, scenario_radius:float=70, agent_ids:list[int|str]|None = None) -> dict:
        if history_step is not None:
            self.history_step = history_step
        if agent_ids is None:
            control_agent_ids = self.get_complete_history_active_agent_ids()
        else:
            control_agent_ids = agent_ids
        basic_info ={"required_update_vehicle_ids": self.agent_records.get_required_update_agent_ids()}
        if set(basic_info["required_update_vehicle_ids"]) > set(control_agent_ids):
            print(f"Warning: In prepared scenario, the agents that need updating are not a subset of the agents that are controllable.")
        extra_res = self._agent_map_interaction(control_agent_ids, scenario_radius)
        formatted_map = self.vector_map.formatted_state(polyline_ids=extra_res["polyline_id"] if "polyline_id" in extra_res.keys() else None)
        formatted_agent = self.agent_records.formatted_state(self.history_step, control_agent_ids)
        return {**basic_info, **extra_res, **formatted_map, **formatted_agent}
    
    @staticmethod
    def _filter_agent_with_id(target_id:Iterable[int|str], original_id:Iterable[int|str], *filter_elements:tuple[np.ndarray]) -> list[list[int|str], np.ndarray]:
        valid_mask = np.isin(original_id, list(target_id), assume_unique=True)
        return [[id for id in original_id if id in target_id]] + [elem[valid_mask] for elem in filter_elements]
            
    def _agent_map_interaction(self, interaction_agent_id: list[int|str], scenario_radius:float) -> dict:
        return {}
    
    def update_scenario(self, formatted_scenario: dict, allow_modify_num_agents: bool=False, proceed: bool=True) -> int:
        '''
        :return: how many steps are updated
        '''
        if not allow_modify_num_agents:
            return self.agent_records.formatted_update(formatted_scenario, proceed=proceed)
        else:
            raise NotImplementedError

    def proceed_step(self, step:int) -> int:
        self.agent_records.proceed_step(step)
        return step
        
    def export(self, sparse: bool = True) -> dict:
        return {**self.vector_map.export(), **self.agent_records.export(sparse=sparse)}
    
    def track_current_agents(self):
        self.agent_records.track_current_agents()
    
    def reset(self):
        self.agent_records.reset()
    
    def load(self, dic: dict, sparse: bool = True, proceed: bool = True) -> ScenarioManager:
        self.vector_map.load(dic)
        if sparse:
            assert "vehicle_id_per_step" in dic.keys(), "Sparse scenario should contain vehicle_id_per_step"
            for step, states in enumerate(dic["vehicle_state_per_step"]):
                dic["vehicle_state_per_step"][step] = self.vector_map.normalize(states)
        else:
            assert "vehicle_id" in dic.keys(), "Dense scenario should contain vehicle_id"
            dic["vehicle_states"] = self.vector_map.normalize(dic["vehicle_states"])
        self.agent_records.load(dic, sparse=sparse, proceed=proceed)
        return self
    
class RouteTLScenarioManager(ScenarioManager):
    def __init__(self,
                 agent_records: VehicleRecordManager,
                 vector_map: RouteTLVectorMap,
                 history_step: int):
        super().__init__(agent_records, vector_map, history_step)
        self.vector_map: RouteTLVectorMap
        self.agent_records: VehicleRecordManager
        self.anomalous_vehicle_ids = []
        
    def runtime_check(self):
        assert self.vector_map.current_step == self.agent_records.current_step, \
            f"Unmatched step for TL: {self.vector_map.current_step} and agent: {self.agent_records.current_step}"
            
    def track_current_agents(self):
        self.vector_map.track_current_agents()
        self.agent_records.track_current_agents()
        
    def prepare_formatted_scenario(self, history_step:int|None=None, scenario_radius:float=70, agent_ids:list[int|str]|None = None) -> dict:
        self.runtime_check()
        if history_step is not None:
            self.history_step = history_step
        if agent_ids is None:
            control_agent_ids = self.get_complete_history_active_agent_ids()
        else:
            control_agent_ids = agent_ids
        basic_info ={"current_step": self.current_step,
                     "required_update_vehicle_ids": self.agent_records.get_required_update_agent_ids(update_step=5),
                     "required_update_traffic_light_ids": self.vector_map.get_required_update_agent_ids(update_step=5)}  
        if set(basic_info["required_update_vehicle_ids"]) > set(control_agent_ids):
            print(f"Warning: In prepared scenario, the agents that need updating are not a subset of the agents that are controllable.")
        extra_res = self._agent_map_interaction(control_agent_ids, scenario_radius)
        formatted_map = self.vector_map.formatted_state(self.history_step,
                                                        polyline_ids=extra_res["polyline_id"] if "polyline_id" in extra_res.keys() else None)
        formatted_agent = self.agent_records.formatted_state(self.history_step, control_agent_ids)
        return {**basic_info, **extra_res, **formatted_map, **formatted_agent}

    
    def _agent_map_interaction(self, interaction_agent_id: list[int|str], scenario_radius:float) -> dict:
        '''
        Assign routes for agents and get valid polylines.
        '''
        switch_route_dist = 2
        assign_route_dist = 5e3
        if len(interaction_agent_id) > 0:
            __, agents_state, agents_mask = self.agent_records[-1, interaction_agent_id, :3]
            agents_pos = agents_state[:, :2]
            agents_heading = agents_state[:, 2]
            agents_pos = agents_pos[agents_mask]
            interaction_agent_id = [interaction_agent_id[i] for i, valid in enumerate(agents_mask) if valid]
        else:
            empty_route_mask = self.vector_map.polyline_formatted_state([])
            ret_scenario = {"polyline_id": [],
                            "route_polyline_id": [],
                            "route_polyline_states": empty_route_mask["polyline_states"],
                            "route_polyline_mask": empty_route_mask["polyline_mask"]}
            return ret_scenario
        
        ret_scenario = {"polyline_id": self.vector_map.get_surrounding_polylines(agents_pos, scenario_radius)}
        agent_route_id, agent_route_states, agent_route_mask, agent_route_start = [], [], [], []
        for i, agent_id in enumerate(interaction_agent_id):
            agent: RoutedVehicle = self.agent_records.get_agents(agent_id)
            reassign_route = False
            if len(agent.route) > 0:
                agent_lane, agent_route_dist = self.vector_map.get_current_lane_from_candidate(agents_pos[i], agent.route, ret_dist=True)
                if agent_route_dist < switch_route_dist and agent_lane == agent.route[0]:
                    pass
                elif agent_route_dist >= switch_route_dist:
                    reassign_route = True
                else:
                    agent.assign_route(self.vector_map.get_routes(current_lane_id=agent.route[agent.route.index(agent_lane):], full=False, visited_route=agent.visited_route))
            else:
                reassign_route = True
            
            # if not reassign_route:
            #     agent_lane_nearest, nearest_dist = self.vector_map.get_current_lane(agents_pos[i], agents_heading[i])
            #     neighbor_lanes = self.vector_map.polyline_dict[agent_lane].left_lanes_id + self.vector_map.polyline_dict[agent_lane].right_lanes_id
            #     if nearest_dist < assign_route_dist and agent_lane_nearest in neighbor_lanes:
            #         reassign_route = True
            
            if reassign_route:
                agent_lane, dist = self.vector_map.get_current_lane(agents_pos[i], agents_heading[i])
                assert self.vector_map.is_lane_center(agent_lane), f"Agent {agent_id} is not matched to a center lane"
                if dist < assign_route_dist:
                    agent.assign_route(self.vector_map.get_routes(current_lane_id=agent_lane, full=False, visited_route=agent.visited_route))
                else:
                    agent.assign_route([])
            
            def get_chain(cur, count):
                neighbor_route = []
                for _ in range(count):
                    if cur is None:
                        break
                    neighbor_route.append(cur)
                    nxt = self.vector_map.polyline_dict[cur].next_lanes_id
                    cur = random.choice(nxt) if len(nxt) > 0 else None
                
                return neighbor_route
            
            agent_route = None
            
            base_len = 2
            if len(agent.route) >= base_len:
                lane_info = self.vector_map.polyline_dict[agent.route[base_len - 1]]
                left_ids = lane_info.left_lanes_id or []
                right_ids = lane_info.right_lanes_id or []
                
                if left_ids:
                    left_id = left_ids[0]
                    reassign_left_route = False
                    if len(agent.left_route) > base_len:
                        if left_id == agent.left_route[base_len]:
                            pass
                        elif left_id in agent.left_route[base_len:]:
                            left_lanes = self.vector_map.get_routes(current_lane_id=agent.left_route[agent.left_route.index(left_id):], full=False)
                            agent.assign_left_route(agent.route[:base_len] + left_lanes[:8 - base_len])
                        else:
                            reassign_left_route = True
                    
                    else:
                        reassign_left_route = True
                    
                    if reassign_left_route:
                        left_lanes = get_chain(left_id, 8 - base_len)
                        agent.assign_left_route(agent.route[:base_len] + left_lanes)
                    
                    agent_route = agent.left_route
                
                # elif right_ids and random.random() < 0.05:
                #     right_id = right_ids[0]
                #     reassign_right_route = False
                #     if len(agent.right_route) > base_len:
                #         if right_id == agent.right_route[base_len]:
                #             pass
                #         elif right_id in agent.right_route[base_len:]:
                #             right_lanes = self.vector_map.get_routes(current_lane_id=agent.right_route[agent.right_route.index(right_id):], full=False)
                #             agent.assign_right_route(agent.route[:base_len] + right_lanes[:8 - base_len])
                #         else:
                #             reassign_right_route = True
                    
                #     else:
                #         reassign_right_route = True
                    
                #     if reassign_right_route:
                #         right_lanes = get_chain(right_id, 8 - base_len)
                #         agent.assign_right_route(agent.route[:base_len] + right_lanes)
                    
                #     agent_route = agent.right_route
                
                else:
                    agent_route = agent.route
            
            else:
                agent_route = agent.route
            
            agent.add_visited_route(agent.route)
            
            polyline_dict = self.vector_map.polyline_formatted_state(polyline_ids=agent_route)
            agent_route_id.append(agent_route)
            agent_route_states.append(polyline_dict["polyline_states"])
            agent_route_mask.append(polyline_dict["polyline_mask"])
        max_route_polyline = max(agent_route_states, key=lambda x: x.shape[0]).shape[0]
        route_polyline_states = np.zeros((len(interaction_agent_id), max_route_polyline, *agent_route_states[0].shape[-2:]))
        route_polyline_mask = np.zeros((len(interaction_agent_id), max_route_polyline, agent_route_mask[0].shape[-1]))
        for i in range(len(interaction_agent_id)):
            route_polyline_states[i, :agent_route_states[i].shape[0]] = agent_route_states[i]
            route_polyline_mask[i, :agent_route_states[i].shape[0]] = agent_route_mask[i]
        ret_scenario.update({"route_polyline_id": agent_route_id,
                             "route_polyline_states": route_polyline_states,
                             "route_polyline_mask": route_polyline_mask})
        return ret_scenario
    
    def update_scenario(self, scenario: dict, 
                        allow_modify_num_agents: bool=False, ref_agent_ids: list[int|str] | None = None,
                        proceed: bool=True, update_step: int | None = None) -> int:
        '''
        :param allow_modify_num_agents: delete or add agents according to the scenario, trafficlight should not be add/delete from this
        :param ref_agent_ids: Used for add/delete agents. Specify original agents.
        :param update_step: update step, if is None, use the max step of map traffic lights and agents
        :return step: how many steps are updated
        '''
        heterogenous_scenario = scenario.pop("heterogenous_update", [])
        self.anomalous_vehicle_ids = scenario.pop("deadlock_vehicle_id", [])
        formatted_scenario = scenario
        map_step = self.vector_map.formatted_update(formatted_scenario, proceed=proceed if update_step is None else False)
        if not allow_modify_num_agents:
            agent_step = self.agent_records.formatted_update(formatted_scenario, proceed=proceed if update_step is None else False)
        else:
            new_agent_ids = formatted_scenario["vehicle_id"] if "vehicle_id" in formatted_scenario.keys() else []
            expected_update_step = max(map_step, formatted_scenario["vehicle_states"].shape[-2]) if update_step is None else update_step
            if ref_agent_ids is None:
                # print('current_step: ', self.agent_records.current_step)
                # print('current_track_agent_ids: ', self.agent_records.current_track_agent_ids)
                # print('new_agent_ids: ', new_agent_ids)
                # print('add_agent_ids: ', set(new_agent_ids) - set(self.agent_records.current_track_agent_ids))
                # print('remove_agent_ids: ', set(self.agent_records.current_track_agent_ids) - set(new_agent_ids))
                ref_agent_ids = self.agent_records.current_track_agent_ids
            id_to_add = list(set(new_agent_ids) - set(ref_agent_ids))
            required_update_vehicle_ids = scenario.get("required_update_vehicle_ids", self.agent_records.get_required_update_agent_ids(expected_update_step))
            id_to_remove = list((set(ref_agent_ids) - set(new_agent_ids)) & set(required_update_vehicle_ids))
            id_to_maintain = list(set(new_agent_ids) & set(ref_agent_ids))
            if len(id_to_add) > 0:
                if "vehicle_mask" in formatted_scenario.keys():
                    id_to_add, states_to_add, mask_to_add = \
                        RouteTLScenarioManager._filter_agent_with_id(id_to_add, formatted_scenario["vehicle_id"], 
                                                                    formatted_scenario["vehicle_states"], formatted_scenario["vehicle_mask"])
                    self.agent_records.add_agents_from_states(start=self.agent_records.current_step+1, vehicles_type=self.agent_records.default_vehicle_type,
                                                              vehicles_id=id_to_add, vehicles_states=states_to_add.transpose(1,0,2), vehicles_mask=mask_to_add)
                else:
                    id_to_add, states_to_add = \
                        RouteTLScenarioManager._filter_agent_with_id(id_to_add, formatted_scenario["vehicle_id"], 
                                                                    formatted_scenario["vehicle_states"])
                    self.agent_records.add_agents_from_states(start=self.agent_records.current_step+1, vehicles_type=self.agent_records.default_vehicle_type,
                                                              vehicles_id=id_to_add, vehicles_states=states_to_add.transpose(1,0,2))

            if len(id_to_remove) > 0:
                print(f"{len(id_to_remove)} vehicles removed by controller")
                self.agent_records.delete_id_agents(id_to_remove)
            if len(id_to_maintain) > 0:
                if "vehicle_mask" in formatted_scenario.keys():
                    formatted_scenario["vehicle_id"], formatted_scenario["vehicle_states"], formatted_scenario["vehicle_mask"] = \
                        RouteTLScenarioManager._filter_agent_with_id(id_to_maintain, formatted_scenario["vehicle_id"], 
                                                                    formatted_scenario["vehicle_states"], formatted_scenario["vehicle_mask"])
                else:
                    formatted_scenario["vehicle_id"], formatted_scenario["vehicle_states"] = \
                        RouteTLScenarioManager._filter_agent_with_id(id_to_maintain, formatted_scenario["vehicle_id"], 
                                                                    formatted_scenario["vehicle_states"])
                
            agent_step = self.agent_records.formatted_update(formatted_scenario, proceed=proceed if update_step is None else False)

        if proceed:
            if update_step is None:
                update_step = max(map_step, agent_step)
            if map_step < update_step:
                self.vector_map.proceed_step(update_step - map_step)
            if agent_step < update_step:
                self.agent_records.proceed_step(update_step - agent_step)
        else:
            update_step = 0
        self.runtime_check()

        if len(heterogenous_scenario) > 0:
            for single_scenario in heterogenous_scenario:
                if 'vehicle_id' in single_scenario.keys():
                    self.agent_records.formatted_update(single_scenario, proceed=False)
                if 'dynamic_polyline_id' in single_scenario.keys():
                    self.vector_map.formatted_update(single_scenario, proceed=False)

        return update_step
        
    def proceed_step(self, step:int) -> int:
        self.vector_map.proceed_step(step)
        self.agent_records.proceed_step(step)
        self.runtime_check()
        return step
    
    def reset(self):
        self.vector_map.reset()
        self.agent_records.reset()
        self.runtime_check()
    
    def export(self, sparse: bool = True) -> dict:
        return {**self.vector_map.export(sparse=sparse), **self.agent_records.export(sparse=sparse)}
    
    def load(self, dic: dict, strict: bool=False, sparse: bool = True, proceed: bool = True) -> RouteTLScenarioManager:
        self.vector_map.load(dic, strict=strict, sparse=sparse, proceed=proceed)
        # normalize vehicle states according to vector map
        if sparse:
            assert "vehicle_id_per_step" in dic.keys(), "Sparse scenario should contain vehicle_id_per_step"
            for step, states in enumerate(dic["vehicle_state_per_step"]):
                dic["vehicle_state_per_step"][step] = self.vector_map.normalize(states)
        else:
            assert "vehicle_id" in dic.keys(), "Dense scenario should contain vehicle_id"
            dic["vehicle_states"] = self.vector_map.normalize(dic["vehicle_states"])
        self.agent_records.load(dic, sparse=sparse, proceed=proceed)
        if self.vector_map.current_step < self.agent_records.current_step:
            self.vector_map.proceed_step(self.agent_records.current_step - self.vector_map.current_step)
        elif self.agent_records.current_step < self.vector_map.current_step:
            self.agent_records.proceed_step(self.vector_map.current_step - self.agent_records.current_step)
        self.runtime_check()
        return self

def main_record1():
    # test of record manager
    record = VehicleRecordManager(10)
    record.proceed_step_to(5)
    vid = [1,2,3]
    # vehicle_states = np.random.rand(4, 3, 7)
    vehicle_states = [BaseState(states=np.random.rand(i,7)) for i in range(3)]
    record.add_agents_from_history_states(vid, vehicle_states)
    
    for i in range(10):
        new_record = np.random.rand(2, 3, 7)
        record.update(vehicles_id=[1,2,3], vehicles_states=new_record)
    
    rec = VehicleRecordManager(10)
    rec.load(pickle.load(open("temp_rec.pkl", "rb")), sparse=False)
    
    for i in range(5):
        new_record = np.random.rand(2, 7)
        rec.update(vehicles_id=[1,3], vehicles_states=new_record)
        
    for i in range(5):
        new_record = np.random.rand(2, 7)
        rec.update(vehicles_id=[2,3], vehicles_states=new_record)
        
    exp = rec.export(sparse=False)
    print(rec.export(sparse=True))

def check_map_connectivity():
    rmap = RouteVectorMap(map_path="/home/ubuntu/lishu/data/mcity/mcity_cnde_rebuild.pkl")
    # rmap = RouteVectorMap(map_path="/home/ubuntu/lishu/CityNDE_/Simulator/tmp_trans/map/mcity_cnde.pkl")
    # rmap = RouteVectorMap(map_path="/home/ubuntu/lishu/temp/map_process/map/mcity_cnde_rebuild.pkl")
    for i in range(100):
        rmap.check_route(f"tmp_fig/mcity_route_{i}.pdf")
    
if __name__ == '__main__':
    main_record1()