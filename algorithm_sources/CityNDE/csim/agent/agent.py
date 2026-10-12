from __future__ import annotations
import numpy as np

from typing import Iterable
from .state import BaseState, RoadUserState, TrafficLightState

class BaseAgent:
    def __init__(self, id:int|str, spawn_time_step:int=0, 
                 warm_up_states:np.ndarray | BaseState | None=None, warm_up_mask:np.ndarray|None=None,
                 complete_info: bool=True):
        self.id = id
        self.spawn_time_step = int(spawn_time_step)
        
        # update states
        if warm_up_states is not None:
            if isinstance(warm_up_states, np.ndarray):
                self._states_per_step = BaseState(warm_up_states, warm_up_mask, complete_info=complete_info)
            elif isinstance(warm_up_states, BaseState):
                self._states_per_step = warm_up_states
            else:
                raise TypeError(f"Unknown states type {type(warm_up_states)}")
        else:
            self._states_per_step = BaseState(complete_info=complete_info)
        
        self.formatted_state_dim = self._states_per_step.state_dim
    
    def update(self, next_states:list[float] | np.ndarray | BaseState, states_mask: np.ndarray|None=None, start:int|None=None):
        
        if self.complete_info and states_mask is not None:
            if not np.all(states_mask):
                raise RuntimeError(f"Unable to update agent {self.id} with incomplete states mask")
        self._states_per_step.update(next_states, states_mask, start)
    
    @property
    def first_valid_step(self) -> int:
        if self.complete_info:
            return self.spawn_time_step
        else:
            return self.spawn_time_step + int(np.argmax(self.states_mask))
    
    @property
    def last_valid_step(self) -> int:
        if self.complete_info:
            return self.last_step
        else:
            return self.spawn_time_step + len(self.states_mask) - 1 - int(np.argmax(self.states_mask[::-1])) - 1
        
    @property
    def last_step(self) -> int:
        return self.spawn_time_step + len(self.states) - 1
    
    @property
    def complete_info(self) -> bool:
        return self._states_per_step.complete_info
        
    @property
    def states(self) -> np.ndarray:
        return self._states_per_step.states
    
    @property
    def state_dim(self) -> int:
        return self._states_per_step.state_dim

    def get_absolute_states(self, time_step: int|slice|None=None, key:str='states') -> np.ndarray:
        if not hasattr(self._states_per_step, key):
            raise AttributeError(f"Agent {self.id} does not have attribute {key}")
        key_item = getattr(self._states_per_step, key)
        if isinstance(key_item, tuple):
            key_item = key_item[0]
        if time_step is None:
            return np.concatenate((np.zeros((self.spawn_time_step, *key_item.shape[1:])), key_item), axis=0)
        if isinstance(time_step, int):
            if time_step < 0:
                time_step = self.last_valid_step - time_step + 1
            if time_step < self.spawn_time_step:
                return np.zeros(*key_item.shape[1:])
            else:
                return key_item[time_step - self.spawn_time_step]
        if isinstance(time_step, slice):
            return np.concatenate((np.zeros((self.spawn_time_step, *key_item.shape[1:])), key_item), axis=0)[time_step]

    def get_absolute_mask(self, time_step: int|slice|None=None) -> np.ndarray:
        if time_step is None:
            return np.concatenate((np.zeros((self.spawn_time_step, *self.states_mask.shape[1:])).astype(bool), self.states_mask), axis=0)
        if isinstance(time_step, int):
            if time_step < self.spawn_time_step:
                return False
            else:
                return self.states_mask[time_step - self.spawn_time_step]
        if isinstance(time_step, slice):
            return np.concatenate((np.zeros((self.spawn_time_step, *self.states_mask.shape[1:])).astype(bool), self.states_mask), axis=0)[time_step]
        
    @property
    def states_mask(self):
        if not self.complete_info:
            return self._states_per_step.states_mask
        else:
            return np.ones_like(self.states[..., 0]).astype(bool)
    
    def get_states(self, current_time_step:int=-1):
        return self.states[current_time_step]
    
    def formatted_state_with_mask(self, timesteps:int|slice|None=None) -> tuple[np.ndarray, np.ndarray]:
        '''
        get formatted state with mask since the spawn step
        '''
        if timesteps is None:
            ret_states = (self.states, self.states_mask)
        elif isinstance(timesteps, slice) or isinstance(timesteps, int):
            ret_states = (self.states[timesteps], self.states_mask[timesteps])
        else:
            raise TypeError(f"Timestep index type should be slice/int, got {type(timesteps)}")
        return ret_states
    
class TrafficLight(BaseAgent):
    def __init__(self, id:int|str, spawn_time_step:int=0, static_pos: np.ndarray|None = None, start_point: np.ndarray|None = None, phase: str|None=None,
                 warm_up_states:np.ndarray | TrafficLightState | None=None, warm_up_mask:np.ndarray|None=None,
                 complete_info: bool=True):
        self.id = id
        self.static_pos = static_pos
        self.start_point = start_point
        self.phase = phase
        self.spawn_time_step = int(spawn_time_step)
        
        # update states
        if warm_up_states is not None:
            if isinstance(warm_up_states, np.ndarray):
                self._states_per_step = TrafficLightState(warm_up_states, warm_up_mask, complete_info=complete_info)
            elif isinstance(warm_up_states, TrafficLightState):
                self._states_per_step = warm_up_states
            else:
                raise TypeError(f"Unknown states type {type(warm_up_states)}")
        else:
            self._states_per_step = TrafficLightState(complete_info=complete_info)
        
        self.formatted_state_dim = self._states_per_step.state_dim

    @property
    def isgreen(self):
        return self._states_per_step.isgreen
    
    @property
    def isyellow(self):
        return self._states_per_step.isyellow
    
    @property
    def isred(self):
        return self._states_per_step.isred
    
    @property
    def isunknown(self):
        return self._states_per_step.isunknown
    
class RoadUser(BaseAgent):
    def __init__(self, id:int|str, spawn_time_step:int=0, 
                 warm_up_states:np.ndarray | RoadUserState | None=None, warm_up_mask:np.ndarray|None=None,
                 complete_info: bool=True):
        self.id = id
        self.spawn_time_step = int(spawn_time_step)
        
        # update states
        if warm_up_states is not None:
            if isinstance(warm_up_states, np.ndarray):
                self._states_per_step = RoadUserState(warm_up_states, warm_up_mask, complete_info=complete_info)
            elif isinstance(warm_up_states, RoadUserState):
                self._states_per_step = warm_up_states
            else:
                raise TypeError(f"Unknown states type {type(warm_up_states)}")
        else:
            self._states_per_step = RoadUserState(complete_info=complete_info)
        
        self.formatted_state_dim = self._states_per_step.state_dim

    @property
    def x(self):
        return self._states_per_step.x
    
    @property
    def y(self):
        return self._states_per_step.y
    
    @property
    def pos(self):
        return self._states_per_step.pos
    
    @property
    def heading(self):
        return self._states_per_step.heading
    
    @property
    def vx(self):
        return self._states_per_step.vx
    
    @property
    def vy(self):
        return self._states_per_step.vy
    
    @property
    def ax(self):
        return self._states_per_step.ax
    
    @property
    def ay(self):
        return self._states_per_step.ay
    
    
    # time_step used in get_* are all absolute time steps, not the relative time steps, -1 means the last valid step
    def get_pos(self, current_time_step:int=-1):
        if not self.get_absolute_mask(current_time_step):
            raise RuntimeError(f"Attempt to get pos of invalid agent {self.id} at time {current_time_step}")
        return self.get_absolute_states(current_time_step, key='pos')

        
    def get_moving_distance(self, start_time_step:int|None=None, end_time_step:int|None=None):
        '''
        start_time_step and end_time_step are the absolute time steps, not the relative time steps
        '''
        if start_time_step is None or start_time_step < self.spawn_time_step:
            start_time_step = self.spawn_time_step
        start_time_step -= self.spawn_time_step
        if end_time_step is None or end_time_step > self.last_valid_step:
            end_time_step = self.last_valid_step + 1
        end_time_step -= self.spawn_time_step
        if end_time_step <= start_time_step + 1:
            return 0
        valid_pos = self.pos[start_time_step:end_time_step]
        if isinstance(valid_pos, tuple):    # incomplete info
            valid_pos = valid_pos[0][valid_pos[1]]
        return np.sum(np.linalg.norm(valid_pos[1:] - valid_pos[:-1], axis=-1))
    
    def get_moving_step(self):
        return self.last_valid_step - self.first_valid_step + 1
    
    def get_average_speed(self, start_time_step:int|None=None, end_time_step:int|None=None, state_resolution:float=0.1):
        return self.get_moving_distance(start_time_step, end_time_step) / (end_time_step - start_time_step) / state_resolution
    
class Vehicle(RoadUser):
    def __init__(self, id: int | str, spawn_time_step: int = 0, 
                 warm_up_states: np.ndarray | RoadUserState | None = None, warm_up_mask: np.ndarray | None = None, 
                 static_lwh: np.ndarray|None = None, 
                 complete_info: bool = True):
        
        super().__init__(id, spawn_time_step, warm_up_states, warm_up_mask, complete_info)
        if static_lwh is not None:
            assert len(static_lwh) == 3, f"Wrong vehicle static shape {static_lwh.shape}"
            self.static_lwh = static_lwh
        else:
            self.static_lwh = np.array([3.8, 1.8, 1.5])
        self.formatted_state_dim = self._states_per_step.state_dim + 3
        
    def formatted_state_with_mask(self, timesteps:int|slice|None = None) -> tuple[np.ndarray, np.ndarray]:
        formatted_states, formatted_mask = super().formatted_state_with_mask(timesteps)
        if formatted_states.ndim > 1:
            formatted_states = np.concatenate((formatted_states, self.static_lwh[None, :].repeat(len(formatted_states), axis=0)), axis=-1)
        else:
            formatted_states = np.concatenate((formatted_states, self.static_lwh), axis=-1)
        return formatted_states, formatted_mask
        
class Pedestrain(RoadUser):
    pass

class Cyclist(RoadUser):
    pass

class RoutedVehicle(Vehicle):
    def __init__(self, id: int | str, spawn_time_step: int = 0, 
                 warm_up_states: np.ndarray | BaseState | None = None, warm_up_mask: np.ndarray | None = None, 
                 static_lwh: np.ndarray = np.array([3.8, 1.8, 1.5]),
                 left_route: list[int|str] = [],
                 right_route: list[int|str] = [],
                 route: list[int|str] = [], 
                 complete_info: bool = True):
        '''
        vehicle with route, structured as a list of polyline ids
        '''
        super().__init__(id, spawn_time_step, warm_up_states, warm_up_mask, static_lwh, complete_info)
        self.left_route = left_route
        self.right_route = right_route
        self.route = route
        self.visited_route = set()
        
    @property
    def has_route(self):
        return len(self.route) > 0
    
    def assign_left_route(self, left_route:list[int|str]):
        self.left_route = left_route
    
    def assign_right_route(self, right_route:list[int|str]):
        self.right_route = right_route
    
    def assign_route(self, route:list[int|str]):
        self.route = route
    
    def add_visited_route(self, route:list[int|str]):
        self.visited_route.update(route)
        
if __name__ == "__main__":
    v = RoutedVehicle(id=1, warm_up_states=np.arange(70).reshape(10,7))
    v2 = RoutedVehicle(id=2, warm_up_states=np.arange(21).reshape(3,7))
    v.update(v2.states, start=11)
    print(v.states)

        