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
import os
from ..agent import *
from ..viewer import ScenarioViewer
from cutils.utils import onehot_time_embedding, hashable_input, sparse2dense
from cutils.data_util import interpolate_along_space
from functools import lru_cache
import shapely.geometry as geo
import shapely.affinity as aff
from copy import deepcopy


__all__ = ["MapPolyline", "BaseVectorMap", "GPUVectorMap", "RouteVectorMap"]

@dataclass
class MapPolyline:
    id: int|str=None
    states: np.ndarray|None=None
    type: int|None=None
    center_location: np.ndarray|None=None
    prev_lanes_id: list[str | int]|None=None
    next_lanes_id: list[str | int]|None=None
    left_lanes_id: list[str | int]|None=None
    right_lanes_id: list[str | int]|None=None
    phase: str|None=None
    segment_center_location: np.ndarray|None=None
    segment_len: int = 20
    
    def __len__(self) -> int:
        return len(self.states)
    
    @property
    def state_dim(self):
        return self.states.shape[-1] if self.states is not None else None
    
    @property
    def point_dim(self):
        return self.state_dim - 1 if self.state_dim is not None else None
    
    @property
    def points(self):
        return self.states[:, :self.point_dim] if self.states is not None else None
    
    @points.setter
    def points(self, new_points: np.ndarray):
        self.states[:, :self.point_dim] = new_points
    
    @property
    def heading(self):
        return self.states[:, -1] if self.states is not None else None
    
    @heading.setter
    def heading(self, new_heading: np.ndarray):
        self.states[:, -1] = new_heading
    
    @property
    def cos_heading(self):
        return np.cos(self.heading) if self.states is not None else None
    
    @property
    def sin_heading(self):
        return np.sin(self.heading) if self.states is not None else None
    
    @property
    def length(self) -> float:
        return np.sum(np.linalg.norm(self.points[1:]-self.points[:-1], axis=-1)) if len(self.points) > 1 else 0
    
    @property
    def _type_onehot(self) -> np.ndarray:
        t = np.zeros(4)
        type_t = self.type if self.type != 4 else 0
        t[type_t] = 1
        return t
    
    @property
    def has_heading(self) -> bool:
        return self.heading is not None
    
    @property
    def is_lane_center(self) -> bool:
        return self.type == 0 or self.type == 4
    
    @property
    def is_intersection(self) -> bool:
        return self.type == 4
    
    def export(self) -> dict:
        required_attrib = ["states", "type"]
        optional_attrib = ["center_location", "prev_lanes_id", "next_lanes_id", "left_lanes_id", "right_lanes_id", "segment_center_location", "phase"]
        ret_dict = {self.id: {}}
        for k in required_attrib:
            if getattr(self, k) is None:
                return {}
            ret_dict[self.id][k] = getattr(self, k)
        for k in optional_attrib:
            if getattr(self, k) is not None:
                ret_dict[self.id][k] = getattr(self, k)
        return ret_dict
    
    def load(self, dic: dict, strict: bool=False):
        assert len(dic) == 1
        for id, info in dic.items():
            self.id = id
            
        if strict:
            for k in info.keys():
                assert hasattr(self, k), f'Unknown attribute "{k}" when loading {type(self)}'
        else:
            for k, v in info.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        if self.center_location is None:
            self.center_location = np.average(self.points, axis=0, keepdims=True)
        return self
    
    def formatted_state_with_mask(self) -> tuple[np.ndarray, np.ndarray]:
        '''
        :return: polyline (n*point_per_segment*state_dim), polyline_center, polyline_mask
        '''
        polyline = np.concatenate((self.states, self.cos_heading[:, None], self.sin_heading[:, None], self._type_onehot[None, :].repeat(len(self), axis=0)), 
                                  axis=-1)
        addition = (self.segment_len - len(self) % self.segment_len) % self.segment_len
        polyline = np.concatenate((polyline, np.zeros((addition, polyline.shape[-1]))), axis=0)
        polyline_mask = np.zeros(polyline.shape[0]).astype(bool)
        polyline_mask[:len(self)] = True
        polyline, polyline_mask = polyline.reshape(-1, self.segment_len, polyline.shape[-1]), polyline_mask.reshape(-1, self.segment_len)
        if self.segment_center_location is None:
            self.segment_center_location = np.sum(polyline[..., :self.point_dim], axis=-2) / np.sum(polyline_mask, axis=-1, keepdims=True)
        return polyline, self.segment_center_location, polyline_mask

                    
class BaseVectorMap:
    def __init__(self, formatted_map_state_dim:Iterable[int]=[20, 9]):
        self.formatted_map_state_dim = formatted_map_state_dim
        
    @classmethod
    def create_from_file(cls, map_path: str, formatted_map_state_dim:Iterable[int]=[20, 9]):
        obj = cls(formatted_map_state_dim)
        with open(map_path, "rb") as m:
            polyline_info:dict = pickle.load(m)
        obj.load(polyline_info)
        return obj
        
    def export(self) -> dict:
        ret_dict = {"polyline": {},
                    "map_center": self.pos_offset}
        for p in self.polyline_dict.values():
            ret_dict["polyline"].update(p.export())
        return ret_dict
    
    def _normalize(self):
        map_center = np.zeros(self.polyline_dict[self.polyline_ids[0]].point_dim)
        num_points = 0
        for polyline in self.polyline_dict.values():
            map_center += np.sum(polyline.points, axis=0)
            num_points += len(polyline)
        map_center /= num_points
        for polyline in self.polyline_dict.values():
            polyline.points -= map_center
            if polyline.center_location is not None:
                polyline.center_location -= map_center
        self.pos_offset = map_center
    
    def normalize(self, polyline_points: np.ndarray, dim=[0,1,2]) -> np.ndarray:
        if len(polyline_points) == 0:
            return polyline_points
        polyline_points = polyline_points.copy()
        if not hasattr(self, "pos_offset"):
            print("Warning: polyline nomalize function called before normalizing map and skipped")
            return polyline_points
        if len(dim) >= len(self.pos_offset):
            dim = dim[:len(self.pos_offset)]
        polyline_points[..., dim] -= self.pos_offset[:len(dim)]
        return polyline_points
    
    def denormalize(self, polyline_points: np.ndarray, dim=[0,1,2]) -> np.ndarray:
        polyline_points = polyline_points.copy()
        if not hasattr(self, "pos_offset"):
            print("Warning: polyline denomalize function called before normalize and skipped")
            return polyline_points
        if len(dim) >= len(self.pos_offset):
            dim = dim[:len(self.pos_offset)]
        else:
            raise RuntimeError(f"Unmatched normalize dimensions {dim} and offset shape {len(self.pos_offset)}")
        polyline_points[..., dim] += self.pos_offset
        return polyline_points
        
    def load(self, dic: dict, strict: bool=False):
        if "polyline" not in dic.keys():
            return self
        self.polyline_dict:dict[str|int, MapPolyline] = {p_id: MapPolyline().load({p_id: p_info}, strict=strict) for p_id, p_info in dic["polyline"].items()}
        self.polyline_ids = list(self.polyline_dict.keys())
        self.polyline_type = [t.type for t in self.polyline_dict.values()]
        self.pos_offset = np.zeros(2)
        # if "map_center" in dic.keys():
        #     self.pos_offset = dic["map_center"]
        # else:
        #     self._normalize()
        return self
    
    def project_to_polyline(self, position: np.ndarray, polyline_id: int|str|Iterable[int|str], ret_dist: bool=False) -> np.ndarray|tuple[np.ndarray, float]:
        '''
        project point to polyline, only project on 2D space
        :return: projected position (x, y, heading), 
        '''
        point = geo.Point(position.reshape(-1)[:2])
        if isinstance(polyline_id, int) or isinstance(polyline_id, str):
            polyline_id = [polyline_id]

        polyline_points = np.concatenate([self.polyline_dict[id].points[..., :2] for id in polyline_id], axis=0)
        if len(polyline_points) == 0:
            raise RuntimeError("invalid polyline ids")
        elif len(polyline_points) > 1:
            polyline = geo.LineString(polyline_points)      # may raise warning when same points occur in polyline_points

        if len(polyline_points) > 1: 
            proj_dist = polyline.project(point)
        else:
            proj_dist = 0
        pos_hd = self.polyline_relative_pos(polyline_id=polyline_id, lon=proj_dist)

        if not ret_dist:
            return pos_hd
        else:
            return pos_hd, np.linalg.norm(point.coords - pos_hd[:2])
    
    def polyline_relative_pos(self, polyline_id:int|str|Iterable[int|str], lon: float, lat: float=0) -> np.ndarray:
        '''
        pos is calculated in 2D space
        :param lat: latitude offset, right hand side of heading is positive
        :return: relative postion in the polyline (x, y, heading)
        '''
        if isinstance(polyline_id, Iterable) and not isinstance(polyline_id, str):
            polyline_points = np.concatenate([self.polyline_dict[id].points[..., :2] for id in polyline_id])
            polyline_heading = np.concatenate([self.polyline_dict[id].heading for id in polyline_id])
        else:
            polyline_points = self.polyline_dict[polyline_id].points[..., :2]
            polyline_heading = self.polyline_dict[polyline_id].heading
        segment_len = np.linalg.norm(polyline_points[1:] - polyline_points[:-1], axis=-1)
        i = 0
        exceed = True
        for seg_len in segment_len:
            if lon - seg_len <= 0:
                exceed = False
                break
            else:
                lon -= seg_len
                i += 1
        
        if lon > 0 and exceed:
            # print("Warning: Longitute position exceeds polyline length limit. Returning the last point of polyline")
            i = len(polyline_points) - 1
            lon = 0
        heading = polyline_heading[i]
        new_pos = polyline_points[i] + lon * np.array([np.cos(heading), np.sin(heading)]) + lat * np.array([np.cos(heading-np.pi/2), np.sin(heading-np.pi/2)])
        return np.append(new_pos, heading)
    
    def is_intersection(self, laneid: int|str) -> bool:
        return self.polyline_dict[laneid].is_intersection
        
    def is_lane_center(self, laneid: int|str) -> bool:
        return self.polyline_dict[laneid].is_lane_center
    
    def get_current_lane_from_candidate(self, position: np.ndarray, polyline_cand_id: Iterable[int|str], ret_dist:bool=False) -> str|int|tuple[str|int, float]:
        polyline_cand_id = list(polyline_cand_id)
        dist = [self.project_to_polyline(position, polyline_id, ret_dist=True)[-1] for polyline_id in polyline_cand_id]
        if not ret_dist:
            return polyline_cand_id[np.argmin(dist)]
        else:
            return polyline_cand_id[np.argmin(dist)], np.min(dist)
    
    def polyline_length(self, polyline_id:int|str|Iterable[int|str]) -> float:
        if isinstance(polyline_id, int) or isinstance(polyline_id, str):
            return self.polyline_dict[polyline_id].length
        else:
            points = np.concatenate([self.polyline_dict[p_id].points for p_id in polyline_id], axis=0)
            return np.sum(np.linalg.norm(points[1:]-points[:-1], axis=-1)) if len(points) > 1 else 0
    
    def get_lane_chain(self, polyline_id:int|str, crt_chain:list[int|str]=[], backward:bool=False, max_depth:int|None=None) -> list[int|str]:
        '''
        Find chain of lanes from current lane without any possible branches and intersections
        '''
        if max_depth is not None and max_depth <= 0:
            return crt_chain
        if self.is_intersection(polyline_id) or not self.is_lane_center(polyline_id):
            return crt_chain
        if not backward:
            if polyline_id in crt_chain:
                print("Warning: polyline loop detected")
                return crt_chain
            if self.polyline_dict[polyline_id].next_lanes_id is None or len(self.polyline_dict[polyline_id].next_lanes_id) != 1 or \
                self.polyline_dict[self.polyline_dict[polyline_id].next_lanes_id[0]].prev_lanes_id is None or \
                len(self.polyline_dict[self.polyline_dict[polyline_id].next_lanes_id[0]].prev_lanes_id) != 1:
                return crt_chain + [polyline_id]
            return self.get_lane_chain(self.polyline_dict[polyline_id].next_lanes_id[0], crt_chain + [polyline_id], backward=backward, 
                                       max_depth=None if max_depth is None else max_depth-1)
        else:
            if polyline_id in crt_chain:
                print("Warning: polyline loop detected")
                return crt_chain
            if self.polyline_dict[polyline_id].prev_lanes_id is None or len(self.polyline_dict[polyline_id].prev_lanes_id) != 1 or \
                self.polyline_dict[self.polyline_dict[polyline_id].prev_lanes_id[0]].next_lanes_id is None or \
                len(self.polyline_dict[self.polyline_dict[polyline_id].prev_lanes_id[0]].next_lanes_id) != 1:
                return [polyline_id] + crt_chain
            return self.get_lane_chain(self.polyline_dict[polyline_id].prev_lanes_id[0] , [polyline_id] + crt_chain, backward=backward, 
                                       max_depth=None if max_depth is None else max_depth-1)
    
    def formatted_state(self, polyline_ids: int|str|Iterable[int|str]|None = None) -> dict:
        if polyline_ids is None:
            states_and_masks = [polyline.formatted_state_with_mask() for polyline in self.polyline_dict.values()]
            polyline_ids = list(self.polyline_dict.keys())
        elif isinstance(polyline_ids, int) or isinstance(polyline_ids, str):
            polyline_ids:list[int|str] = [polyline_ids]
        states_and_masks = [self.polyline_dict[p_id].formatted_state_with_mask() if p_id in self.polyline_dict.keys() else (np.zeros((1, *self.formatted_map_state_dim)), np.zeros((1, self.formatted_map_state_dim[0]))) for p_id in polyline_ids]
        if len(states_and_masks) == 0:
            polylines, center, polyline_masks = [np.empty((0, *self.formatted_map_state_dim))], [np.empty((0, self.polyline_dict[self.polyline_ids[0]].point_dim))], [np.empty((0, self.formatted_map_state_dim[0])).astype(bool)]
        else:
            polylines, center, polyline_masks = zip(*states_and_masks)
        segment_ids = [polyline_ids[i] for i, polyline_seg in enumerate(polylines) for __ in range(polyline_seg.shape[0])]
        return {"polyline_id": segment_ids,  
                "polyline_center": np.concatenate(center, axis=0),
                "polyline_states": np.concatenate(polylines, axis=0), 
                "polyline_mask": np.concatenate(polyline_masks, axis=0)}
        
    def get_intersection_polyline_id(self) -> list[int|str]:
        intersection_polyline_id = []
        for polyline_id, polyline in self.polyline_dict.items():
            if polyline.is_intersection:
                intersection_polyline_id.append(polyline_id)
        return intersection_polyline_id
    
    def get_intersection_polyline_phase(self, traffic_light_ids: list[int|str]|None=None) -> list[str]:
        tl_polylines = [polyline for polyline in self.polyline_dict.values() if polyline.id in traffic_light_ids]
        tl_phase = [polyline.phase for polyline in tl_polylines]
        if None in tl_phase:
            # raise RuntimeError("Debug")
            from cutils.data_util import assign_tl_phase
            tl_polyline_dict = {}
            for polyline in tl_polylines:
                tl_polyline_dict.update(polyline.export())
            new_tl_phase = assign_tl_phase(tl_polyline_dict, logic='start_direction')
            tl_phase = [phase if phase is not None else new_tl_phase[id] for phase, id in zip(tl_phase, traffic_light_ids)]
        return tl_phase
    
    def get_intersection_polyline_direction(self, traffic_light_ids: list[int|str]|None=None) -> dict:
        '''
        :return: dict of {intersection polyline id: type (left turn, straight, right turn, ...)} 
        '''
        if traffic_light_ids is None:
            traffic_light_ids = self.get_intersection_polyline_id()
        
        intersection_start_lane = []
        for lane_id, lane_info in self.polyline_dict.items():
            if lane_id in traffic_light_ids:
                prev_lanes = lane_info.prev_lanes_id
                if prev_lanes is None or prev_lanes == []:
                    continue
                if prev_lanes[0] in traffic_light_ids:
                    continue
                intersection_start_lane.append(lane_id)
        
        intersection_sequences = []
        for lane_id in intersection_start_lane:
            lane_seq = [lane_id]
            while True:
                if self.polyline_dict[lane_seq[-1]].next_lanes_id is None or self.polyline_dict[lane_seq[-1]].next_lanes_id == []:
                    break
                if self.polyline_dict[lane_seq[-1]].next_lanes_id[0] not in traffic_light_ids:
                    break
                if self.polyline_dict[lane_seq[-1]].next_lanes_id[0] in lane_seq:
                    break
                lane_seq.append(self.polyline_dict[lane_seq[-1]].next_lanes_id[0])
            intersection_sequences.append(lane_seq)
            
        polyline_direction = {}
        for lane_seq in intersection_sequences:
            start_id, end_id = lane_seq[0], lane_seq[-1]
            if start_id not in self.polyline_dict.keys() or end_id not in self.polyline_dict.keys():
                if start_id not in self.polyline_dict.keys():
                    print(f"Warning: dynamic polyline {start_id} not found in map")
                if end_id not in self.polyline_dict.keys():
                    print(f"Warning: dynamic polyline {end_id} not found in map")
                p_drct = None
                polyline_direction.update({lane_id: p_drct for lane_id in lane_seq})
                continue
            start_heading = self.polyline_dict[start_id].heading[0]
            end_heading = self.polyline_dict[end_id].heading[-1]
            delta_heading = (end_heading - start_heading + np.pi) % (np.pi * 2) - np.pi
            start_heading = (start_heading + np.pi) % (np.pi * 2) - np.pi
            
            if -np.pi/4 <= start_heading <= np.pi/4 or start_heading >= 3*np.pi/4 or start_heading <= -3*np.pi/4:
                p_drct = "ew_"
            else:
                p_drct = "ns_"

            if -np.pi/4 <= delta_heading <= np.pi/4:
                p_drct += "s"
            elif np.pi/4 <= delta_heading <= 3*np.pi/4:
                p_drct += "l"
            elif -3*np.pi/4 <= delta_heading <= -np.pi/4:
                p_drct += "r"
            else:
                p_drct += "l"
            polyline_direction.update({lane_id: p_drct for lane_id in lane_seq})
            
        return polyline_direction

class GPUVectorMap(BaseVectorMap):
    def __init__(self, formatted_map_state_dim: Iterable[int]=[20, 9], device='cuda'):
        self.device = device
        super().__init__(formatted_map_state_dim)
        
    @classmethod
    def create_from_file(cls, map_path: str, formatted_map_state_dim: Iterable[int]=[20, 9], device='cuda'):
        obj = cls(formatted_map_state_dim, device)
        with open(map_path, "rb") as m:
            polyline_info:dict = pickle.load(m)
        obj.load(polyline_info)
        return obj
    
    def _map_api_init(self):
        max_polyline_points = 0
        self.center_lane_ids = []
        for id, polyline in self.polyline_dict.items():
            if polyline.is_lane_center: 
                self.center_lane_ids.append(id)
                if len(polyline.points) > max_polyline_points:
                    max_polyline_points = len(polyline.points)

        self.polyline_center_lane = torch.zeros((len(self.center_lane_ids), max_polyline_points, self.polyline_dict[self.polyline_ids[0]].point_dim))
        self.polyline_center_lane_heading = torch.zeros((len(self.center_lane_ids), max_polyline_points))
        self.center_lane_mask = torch.zeros((len(self.center_lane_ids), max_polyline_points)).to(torch.bool)
        for i, id in enumerate(self.center_lane_ids):
            t_polyline = torch.from_numpy(self.polyline_dict[id].points)
            self.polyline_center_lane[i, :len(t_polyline), :] = t_polyline
            self.polyline_center_lane_heading[i, :len(t_polyline)] = torch.from_numpy(self.polyline_dict[id].heading)
            self.center_lane_mask[i, :len(t_polyline)] = True
        
            
        self.start_lane, self.end_lane = [], []
        for id in self.center_lane_ids:
            if self.polyline_dict[id].next_lanes_id is not None:
                if len(self.polyline_dict[id].next_lanes_id) > 0:
                    continue
            self.end_lane.append(id)
        
        for id in self.center_lane_ids:
            if self.polyline_dict[id].prev_lanes_id is not None:
                if len(self.polyline_dict[id].prev_lanes_id) > 0:
                    continue
            self.start_lane.append(id)
        
        self.center_lane_ids = np.array(self.center_lane_ids, dtype=object)
        
        self.polyline_center_lane = self.polyline_center_lane.to(self.device)
        self.polyline_center_lane_heading = self.polyline_center_lane_heading.to(self.device)
        self.center_lane_mask = self.center_lane_mask.to(self.device)

        self._init_temp_val()
    
    def _init_temp_val(self):
        self._AB = self.polyline_center_lane[:, 1:, :] - self.polyline_center_lane[:, :-1, :]
        self._l_AB = torch.norm(self._AB, dim=-1)
        self._l_AB[self._l_AB == 0] = 1
        self._d_mask = (self.center_lane_mask[:, 1:]) & (self.center_lane_mask[:, :-1])
        self._AB_heading = self.polyline_center_lane_heading[:, 1:]
        
    def load(self, dic: dict, strict: bool = False):
        super().load(dic, strict)
        self._map_api_init()
        return self
        
    def set_device(self, device: str):
        self.device = device
        self._map_api_init()
    
    @hashable_input
    @lru_cache(maxsize=1024)
    def get_current_lane(self, position: np.ndarray|torch.Tensor, heading: float|None=None) -> tuple[int|str, float]:
        '''
        :return: closest lane, min distance
        '''
        if not isinstance(position, torch.Tensor):
            position = torch.tensor(position)
        position = position.reshape(1, 1, -1).to(self.device)
        AP = position - self.polyline_center_lane[:, :-1, :]
        # segment AB, point P, projection Q
        l_AP = torch.norm(AP, dim=-1)
        l_AQ = torch.sum(self._AB * AP, dim=-1) / self._l_AB
        tag_out = (l_AQ / self._l_AB > 1) | (l_AQ / self._l_AB < 0)
        l_PQ = torch.sqrt(torch.abs(l_AP ** 2 - l_AQ ** 2))         # may be negative because of numerical error, so use abs
        l_PB = torch.norm(position - self.polyline_center_lane[:, 1:, :], dim=-1)
        d = l_PQ
        d[tag_out] = torch.min(l_AP, l_PB)[tag_out]
        d[self._d_mask == False] = torch.inf
        if heading is not None:
            heading_weight = 0.7
            heading_threshold = np.pi/2
            heading_diff = torch.abs((self._AB_heading - heading + np.pi) % (np.pi * 2) - np.pi)
            heading_diff_mask = heading_diff > heading_threshold
            d[heading_diff_mask] = torch.inf
            d_with_heading = d * (1 - heading_weight) + heading_diff * heading_weight
            idx_min = torch.argmin(d_with_heading) // d.shape[-1]
        else:
            idx_min = torch.argmin(d) // d.shape[-1]
        return self.center_lane_ids[idx_min], torch.min(d).item()
        
    def get_surrounding_polylines(self, position: torch.Tensor|np.ndarray, dist: float) -> list[int|str]:
        position = torch.tensor(position).reshape(-1, self.polyline_dict[self.polyline_ids[0]].point_dim).to(self.device)
        polyline_center = torch.from_numpy(np.concatenate([polyline.center_location for polyline in self.polyline_dict.values()], axis=0)).to(self.device)
        valid_polyline = torch.any(torch.norm(position[:, None, :] - polyline_center[None, ...], dim=-1) <= dist, dim=0)
        return [self.polyline_ids[i] for i, is_valid in enumerate(valid_polyline) if is_valid]
        
    def batch_get_current_lane(self, position, return_distance=False):
        '''
        Get batch current lane according to batch input position.
        This function is easy to trigger CUDA OOM. Supposed not to use.
        This function is deprecated. Use "get_current_lane" instead.
        '''
        if not isinstance(position, torch.Tensor):
            position = torch.tensor(position)
        position = position.reshape(1, 1, -1, self.polyline_dict[self.polyline_ids[0]].point_dim).to(self.device)
        # Segment AB, point P, projection Q
        AP = position - self.polyline_center_lane[:, :-1, None, :]
        l_AP = torch.norm(AP, dim=-1)
        l_AQ = torch.sum(self._AB[..., None, :] * AP, dim=-1) / self._l_AB[..., None]
        del AP
        tag_out = (l_AQ / self._l_AB[..., None] > 1) | (l_AQ / self._l_AB[..., None] < 0)
        d = torch.sqrt(torch.abs(l_AP ** 2 - l_AQ ** 2))
        del l_AQ
        l_PB = torch.norm(position - self.polyline_center_lane[:, 1:, None, :], dim=-1)
        d[tag_out] = torch.min(l_AP, l_PB)[tag_out]
        d[self._d_mask == False] = torch.inf
        del l_AP, l_PB
        
        
        min_val, idx_min = torch.min(d.view(-1, position.shape[-2]), dim=0)
        idx_min = idx_min // self.polyline_center_lane.shape[-2]
        
        if not return_distance:
            return self.center_lane_ids[idx_min.cpu().numpy()]
        else:
            return self.center_lane_ids[idx_min.cpu().numpy()], min_val.cpu().numpy()
    
    def check_end(self, current_position, current_heading) -> bool:
        dist = 5
        current_lane = self.get_current_lane(current_position, current_heading)[0]
        if current_lane in self.end_lane:
            end_pos = self.polyline_dict[current_lane].points[-1, :]
            if np.linalg.norm(end_pos - np.array(current_position)) <= dist:
                return True
        
        for next_lane in self.polyline_dict[current_lane].next_lanes_id:
            if next_lane in self.end_lane:
                next_end_pos = self.polyline_dict[next_lane].points[-1, :]
                if np.linalg.norm(next_end_pos - np.array(current_position)) <= dist:
                    return True
        
        return False

class RouteVectorMap(GPUVectorMap):
    def __init__(self, formatted_map_state_dim: Iterable[int]=[20, 9], device="cuda"):
        '''
        route load from route_path is of the format dict{current_lane_id: list[list[lane_id]}
        '''
        super().__init__(formatted_map_state_dim, device=device)
                
    def get_route_based_on_traj(self, traj:np.ndarray|torch.Tensor, traj_is_future: bool=True):
        '''
        The efficiency of this function is a bit low
        '''
        traj = torch.tensor(traj.reshape(-1, traj.shape[-1]))
        
        lane_id = set([self.get_current_lane(pos)[0] for pos in traj])
        route_cand = list(set([tuple(route) for id in lane_id for route in self.route_related_record[id]]))
        point_proj_dist = [[self.project_to_polyline(pos.cpu().numpy(), polyline_id=route, ret_dist=True)[1] for pos in traj] for route in route_cand]
        route_idx = np.argmin([np.max(dist) for dist in point_proj_dist])
        if not traj_is_future:
            crt_lane_id = self.get_current_lane_from_candidate(traj[-1].cpu().numpy(), route_cand[route_idx])
        else:
            crt_lane_id = self.get_current_lane_from_candidate(traj[0].cpu().numpy(), route_cand[route_idx])
        if not traj_is_future:
            return self.get_routes(current_lane_id=crt_lane_id, full=False)
        else:
            start_id = route_cand[route_idx].index(crt_lane_id)
            route_part = list(route_cand[route_idx][start_id:])
            route_full = self.get_routes(current_lane_id=crt_lane_id)
            final_route_cand = [route for route in route_full if route[:len(route_part)] == route_part]
            return random.choice(final_route_cand)
    
    def get_routes(self, current_position:torch.Tensor|np.ndarray|None=None, current_lane_id:str|int|list[str|int]|None=None, full: bool=True, visited_route:set[str|int]|None=None):
        if current_lane_id is None:
            assert current_position is not None, "invalid route query input"
            current_lane_id = self.get_current_lane(current_position)[0]
        if isinstance(current_lane_id, int) | isinstance(current_lane_id, str):
            assert current_lane_id in self.route_record.keys(), f"unknown center lane id {current_lane_id}"
            start_id = current_lane_id
            current_lane_id = [current_lane_id]
        else:
            assert current_lane_id[0] in self.route_record.keys(), f"unknown center lane id {current_lane_id}"
            start_id = current_lane_id[0]
        route_cand = self.route_record[start_id]
        final_route_cand = [route for route in route_cand if route[:len(current_lane_id)] == current_lane_id]
        assert len(final_route_cand) > 0, f"invalid current lane id {current_lane_id}"
        if full:
            return final_route_cand
        else:
            if visited_route is None:
                return random.choice(final_route_cand)
            
            preferred_route = [route for route in final_route_cand if route[-1] not in visited_route]
            if len(preferred_route) > 0:
                return random.choice(preferred_route)
            else:
                return random.choice(final_route_cand)
        
    def get_backward_routes(self, current_position:torch.Tensor|np.ndarray|None=None, current_lane_id:str|int|list[str|int]|None=None, full: bool=True):
        if current_lane_id is None:
            assert current_position is not None, "invalid route query input"
            current_lane_id = self.get_current_lane(current_position)[0]
        if isinstance(current_lane_id, int) | isinstance(current_lane_id, str):
            assert current_lane_id in self.route_backward_record.keys(), f"unknown center lane id {current_lane_id}"
            end_id = current_lane_id
            current_lane_id = [current_lane_id]
        else:
            assert current_lane_id[0] in self.route_backward_record.keys(), f"unknown center lane id {current_lane_id}"
            end_id = current_lane_id[0]
        route_cand = self.route_backward_record[end_id]
        final_route_cand = [route for route in route_cand if route[-len(current_lane_id):] == current_lane_id]
        assert len(final_route_cand) > 0, f"invalid current lane id {current_lane_id}"
        if full:
            return final_route_cand
        else:
            return random.choice(final_route_cand)

        
    def init_route_record(self, route: dict[int|str, list[list[int|str]]]):
        self.route_record = route
        self.route_backward_record = {k: [] for k in self.route_record.keys()}
        self.route_related_record = deepcopy(route)
        for routes in self.route_record.values():
            for single_route in routes:
                for line_id in single_route[1:]:
                    self.route_related_record[line_id].append(single_route)
                for i in range(len(single_route)):
                    part_route = single_route[:len(single_route) - i]
                    tmp_route = []
                    is_new_route = True
                    for current_backward_route in self.route_backward_record[part_route[-1]]:
                        if current_backward_route == part_route[-len(current_backward_route):]:
                            if part_route not in tmp_route:
                                tmp_route.append(part_route)
                                is_new_route = False
                            continue
                        if part_route == current_backward_route[-len(part_route):]:
                            is_new_route = False
                        tmp_route.append(current_backward_route)
                            
                    if is_new_route:
                        tmp_route.append(part_route)
                    self.route_backward_record[part_route[-1]] = tmp_route
    
    def load(self, dic: dict, strict: bool = False):
        if "map" in dic.keys():
            super().load(dic["map"], strict)
        elif "polyline" in dic.keys():
            super().load(dic, strict)
        if "routes" in dic.keys():
            self.init_route_record(dic["routes"])
        else:
            self.init_route_record(self.generate_route(depth=8))
        return self

            
    def export(self) -> dict:
        ret_dict = {}
        ret_dict["map"] = super().export()
        if self.route_record is not None:
            ret_dict["routes"] = self.route_record
        return ret_dict
    
    def generate_route(self, depth:int=8):
        connection_dict = {}
        for p_id, p_info in self.polyline_dict.items():
            if not self.is_lane_center(p_id):
                continue
            if p_info.next_lanes_id is not None:
                connection_dict[p_id] = [l_id for l_id in p_info.next_lanes_id if l_id in self.polyline_ids]
            else:
                connection_dict[p_id] = []

        # search from "route" with "connection_dict" and append new lanes in "route" to form 2d list
        def rec_search(max_depth, route: list, connection_dict: dict):
            if len(route) >= max_depth:
                return [route]
            next_route = []
            for next_lane in connection_dict[route[-1]]:
                if next_lane in connection_dict.keys():
                    next_route.append(route[:] + [next_lane])

            if len(next_route) == 0:
                return [route]
            else:
                ret = []
                for r in next_route:
                    ret.extend(rec_search(max_depth, r, connection_dict))
                return ret
        
        route_all = {}
        for p_id in self.polyline_ids:
            if p_id in connection_dict.keys():
                route_all[p_id] = rec_search(depth, [p_id], connection_dict)
        
        return route_all
    
    def check_route(self, file_name:str, start_id:int|str|None=None, route:list[int|str]|None=None, 
                    ref_lines:list[list[np.ndarray]]=[[]], ref_desc:list[str]=[]):
        if len(self.route_record) == 0:
            print("No route found")
            return
        if start_id is None:
            start_id = random.choice(list(self.route_record.keys()))
        if start_id not in self.route_record.keys():
            print("No route found")
            return
        if route is not None:
            start_id = route[0]
            connect_id = route[1:]
        else:
            connect_id = random.choice(self.route_record[start_id])[1:]
            
        start_polyline = self.formatted_state(polyline_ids=start_id)
        connect_polyline = self.formatted_state(polyline_ids=connect_id)
        
        start_view, connect_view = [], []

        for i in range(start_polyline["polyline_states"].shape[0]):
            valid_pl = start_polyline["polyline_states"][i][start_polyline["polyline_mask"][i]]
            start_view.append(valid_pl)
        for i in range(connect_polyline["polyline_states"].shape[0]):
            valid_pl = connect_polyline["polyline_states"][i][connect_polyline["polyline_mask"][i]]
            connect_view.append(valid_pl)

        ScenarioViewer.quick_view_scenario(file_name, 
                                           lines=[start_view, connect_view, *ref_lines], 
                                           l_desc=["start", "connect", *ref_desc],
                                           axis='on', plot_drct=True)


def main_record3():
    from ..viewer import ScenarioViewer
    rmap = RouteVectorMap.create_from_file(map_path="/mnt/sdc/ubuntu/NDEdata/tianjin/processed_map/sequence/map_wanji_tianjin_with_route_2d.pkl")
    p_drct_dict = rmap.get_intersection_polyline_direction()
    plot_dict = {"ew_l": [], "ew_s": [], "ew_r": [], "ns_l": [], "ns_s": [], "ns_r": []}
    for lane_id, drct in p_drct_dict.items():
        plot_dict[drct].append(rmap.polyline_dict[lane_id].points)
    ScenarioViewer.quick_view_scenario(save_file="drct.pdf", lines=[v for v in plot_dict.values()], l_desc=[k for k in plot_dict.keys()], axis='on')

def check_map_connectivity():
    rmap = RouteVectorMap.create_from_file(map_path="/home/ubuntu/lishu/data/mcity/mcity_cnde_rebuild.pkl")
    # rmap = RouteVectorMap.create_from_file(map_path="/home/ubuntu/lishuCityNDE_/csim/tmp_trans/map/mcity_cnde.pkl")
    # rmap = RouteVectorMap.create_from_file(map_path="/home/ubuntu/lishu/temp/map_process/map/mcity_cnde_rebuild.pkl")
    for i in range(100):
        rmap.check_route(f"/home/ubuntu/lishu/CityNDE_/output/tmp_fig/mcity_route_{i}.pdf")
    
if __name__ == '__main__':
    check_map_connectivity()