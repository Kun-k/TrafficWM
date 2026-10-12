from __future__ import annotations
import numpy as np
import random
import torch
import pickle
from typing import Iterable


class BaseState:
    def __init__(self, states:np.ndarray|None=None, states_mask:np.ndarray|None=None, complete_info:bool=True, state_dim:int=-1):
        self.state_dim = state_dim
        if states is not None:
            assert states.shape[-1] == self.state_dim, f"Unmatched shape of agent state: {states.shape} to state dimension {self.state_dim}"
            if states.ndim == 1:
                states = states[None, :]
            self.states = states.copy()
        else:
            self.states = np.empty((0, self.state_dim))
            
        self.complete_info = complete_info
        if not complete_info:
            if states_mask is None:
                self.states_mask = np.ones_like(self.states[..., 0]).astype(bool)
            else:
                assert states_mask.shape == states.shape[:-1], f"Unmatched shape of agent state: {states.shape} and state mask: {states_mask.shape}"
                self.states_mask = states_mask
        else:
            self.states_mask = None
            
    def __len__(self):
        return len(self.states)
    
    def update(self, next_states:Iterable[float] | np.ndarray | BaseState, states_mask: np.ndarray|None=None, start:int|None=None):
        '''
        Update states based on input next states (and mask).
        '''
        if isinstance(next_states, np.ndarray) or isinstance(next_states, Iterable):
            if not isinstance(next_states, np.ndarray):
                next_states = np.array(next_states)
            if next_states.ndim == 1:
                next_states = next_states[None]
            assert next_states.shape[-1] == self.state_dim, f"Unmatched shape of agent state: {next_states.shape} to {self.states.shape}"
            if states_mask is None:
                states_mask = np.ones_like(next_states[..., 0]).astype(bool)
                    
        elif isinstance(next_states, BaseState):
            assert next_states.state_dim == self.state_dim, f"Unmatched dim of agent state: {next_states.state_dim} to {self.state_dim}"
            if next_states.complete_info:
                states_mask = np.ones_like(next_states.states[..., 0].astype(bool))
            else:
                states_mask = next_states.states_mask
            next_states = next_states.states
                    
        update_len = next_states.shape[0]
        if start is None:
            start = self.__len__()
        if start > self.__len__():
            raise IndexError(f"Start of update index {start} exceeds the state length {self.__len__()}")
        
        assert next_states.shape[:-1] == states_mask.shape, f"Unmatched shape of agent state: {next_states.shape} and state mask: {states_mask.shape}"
        if self.complete_info:
            assert np.all(states_mask), "Unable to update state with complete information with incomplete information"
        else:
            self.states_mask = np.concatenate((self.states_mask[:start], states_mask, self.states_mask[start+update_len:]), axis=0)
            
        self.states = np.concatenate((self.states[:start], next_states, self.states[start+update_len:]), axis=0)
    
    def __getitem__(self, key: slice|int):
        if not self.complete_info:
            return self.states[key], self.states_mask[key]
        else:
            return self.states[key]
    
    def __setitem__(self, key: slice|int, value: np.ndarray | tuple[np.ndarray, np.ndarray | bool]):
        '''
        input states (complete info) or states and states_mask (incomplete info)
        '''
        assert isinstance(key, slice) or isinstance(key, int), f"Wrong array index type {type(key)}, index type must be slice or int"
        if self.complete_info:
            self.states[key] = value
        else:
            self.states[key] = value[0]
            self.states_mask[key] = value[1]
        
class RoadUserState(BaseState):
    def __init__(self, states:np.ndarray|None=None, states_mask:np.ndarray|None=None, complete_info:bool=True):
        # explicit state dim for concrete state of agent
        state_dim = 7
        return super().__init__(states=states, states_mask=states_mask, complete_info=complete_info, state_dim=state_dim)
    
    @property
    def x(self):
        if not self.complete_info:
            return self.states[:, 0], self.states_mask
        else:
            return self.states[:, 0]
    
    @property
    def y(self):
        if not self.complete_info:
            return self.states[:, 1], self.states_mask
        else:
            return self.states[:, 1]
            
    @property
    def pos(self):
        if not self.complete_info:
            return self.states[:, :2], self.states_mask
        else:
            return self.states[:, :2]
    
    @property
    def heading(self):
        if not self.complete_info:
            return self.states[:, 2], self.states_mask
        else:
            return self.states[:, 2]
    
    @property
    def v(self):
        if not self.complete_info:
            return self.states[:, 3:5], self.states_mask
        else:
            return self.states[:, 3:5]
    
    @property
    def vx(self):
        if not self.complete_info:
            return self.states[:, 3], self.states_mask
        else:
            return self.states[:, 3]
    
    @property
    def vy(self):
        if not self.complete_info:
            return self.states[:, 4], self.states_mask
        else:
            return self.states[:, 4]
    
    @property
    def a(self):
        if not self.complete_info:
            return self.states[:, 5:7], self.states_mask
        else:
            return self.states[:, 5:7]
    
    @property
    def ax(self):
        if not self.complete_info:
            return self.states[:, 5], self.states_mask
        else:
            return self.states[:, 5]
    
    @property
    def ay(self):
        if not self.complete_info:
            return self.states[:, 6], self.states_mask
        else:
            return self.states[:, 6]
        
class TrafficLightState(BaseState):
    def __init__(self, states:np.ndarray|None=None, states_mask:np.ndarray|None=None, complete_info:bool=True):
        # explicit state dim for concrete state of agent
        state_dim = 4
        return super().__init__(states=states, states_mask=states_mask, complete_info=complete_info, state_dim=state_dim)
    
    @property
    def isgreen(self):
        if not self.complete_info:
            return self.states[:, 0], self.states_mask
        else:
            return self.states[:, 0]
    
    @property
    def isyellow(self):
        if not self.complete_info:
            return self.states[:, 1], self.states_mask
        else:
            return self.states[:, 1]
        
    @property
    def isred(self):
        if not self.complete_info:
            return self.states[:, 2], self.states_mask
        else:
            return self.states[:, 2]
        
    @property
    def isunknown(self):
        if not self.complete_info:
            return self.states[:, 3], self.states_mask
        else:
            return self.states[:, 3]
        
    def _check_conflict(self):
        if self.states is None:
            return False
        if not self.complete_info:
            check_states = self.states[self.states_mask]
        else:
            check_states = self.states
        return not np.all(np.sum(check_states, axis=-1) == 1)
    
    def update(self, next_states:Iterable[float] | np.ndarray | TrafficLightState, states_mask: np.ndarray|None=None, start:int|None=None):
        super().update(next_states, states_mask, start)
        if self._check_conflict():
            raise RuntimeError("Traffic light state updated with invalid input")

    def __setitem__(self, key: slice|int, value: np.ndarray | tuple[np.ndarray, np.ndarray | bool]):
        super().__setitem__(key, value)
        if self._check_conflict():
            raise RuntimeError("Traffic light state updated with invalid input")
            
