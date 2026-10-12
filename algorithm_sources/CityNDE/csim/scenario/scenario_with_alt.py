import numpy as np
from dataclasses import dataclass
from scenario import MapPolyline, BaseVectorMap, GPUVectorMap
from typing import Iterable
import pickle

@dataclass
class Polyline_v2(MapPolyline):
    state_dim: int = 4
    
    def __len__(self) -> int:
        return len(self.states)
    
    @property
    def points(self):
        return self.states[:, :3] if self.states is not None else None
    
    @points.setter
    def points(self, new_points: np.ndarray):
        self.states[:, :3] = new_points
    
    @property
    def heading(self):
        return self.states[:, 3] if self.states is not None else None
    
    @heading.setter
    def heading(self, new_heading: np.ndarray):
        self.states[:, 3] = new_heading
    
    @property
    def cos_heading(self):
        return np.cos(self.states[:, 3]) if self.states is not None else None
    
    @property
    def sin_heading(self):
        return np.sin(self.states[:, 3]) if self.states is not None else None

    
class VectorMap_v2(BaseVectorMap):
    def __init__(self, formatted_map_state_dim:Iterable[int]=[20, 10], map_path=None):
        super().__init__(formatted_map_state_dim, map_path)
        
    def load(self, dic: dict, strict: bool=False):
        self.polyline_dict:dict[str|int, Polyline_v2] = {p_id: Polyline_v2().load({p_id: p_info}, strict=strict) for p_id, p_info in dic["polyline"].items()}
        self.polyline_ids = list(self.polyline_dict.keys())
        self.polyline_type = [t.type for t in self.polyline_dict.values()]
        self._normalize()
        return self
        
class GPUVectorMap_v2(GPUVectorMap, VectorMap_v2):
    def __init__(self, formatted_map_state_dim: Iterable[int]=[20, 10], map_path=None, device='cuda'):
        super().__init__(formatted_map_state_dim, map_path, device)