import os, sys
import matplotlib as mpl
import matplotlib.cm as cm
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.colors import to_rgba
from matplotlib.ticker import FuncFormatter
import pickle
import numpy as np
import cv2
import random
from itertools import groupby
from typing import Iterable, Literal
import tqdm
import ast  
from pathlib import Path
from cutils import get_rotated_box, interpolate, dense2sparse, extract_polyline_dict
from argparse import ArgumentParser
from collections import deque

random.seed(0)
    
class ScenarioViewer:
    def __init__(self, scenario_file: str=''):
        self.agent_loaded, self.map_loaded = False, False
        self.load_default_cfg()
        if os.path.isfile(scenario_file):
            self.load_scenario(scenario_file)
            self.agent_loaded, self.map_loaded = True, True
        
    
    @property
    def scenario_loaded(self):
        return self.agent_loaded and self.map_loaded
    
    @scenario_loaded.setter
    def scenario_loaded(self, loaded: bool):
        self.agent_loaded = self.map_loaded = loaded
            
    def load_scenario(self, scenario_file: str = None, scenario_dict: dict = None, map_offset: bool = False):
        if scenario_file is not None:
            scenario = pickle.load(open(scenario_file, "rb"))
        if scenario_dict is not None:
            scenario = scenario_dict
        self.simulator_meta = scenario["simulator_meta_info"] if "simulator_meta_info" in scenario.keys() else "No simulator information found"
        
        self.load_map(map_dict=scenario, map_offset=map_offset)
        self.load_agent(agent_dict=scenario, map_offset=map_offset)
        self.scenario_loaded = True
        
        self._update_related_cfg()
        
        if scenario_file is not None:
            print(f"Successfully load scenario '{scenario_file}'")
        print(self.simulator_meta)
        
    def load_map(self, map_file: str = None, map_dict: dict = None, map_offset: bool = False):
        if map_file is not None:
            scenario = pickle.load(open(map_file, "rb"))
        if map_dict is not None:
            scenario = map_dict
        if "map" in scenario.keys():
            scenario = scenario["map"]
        self.map_center = scenario.get("map_center", np.zeros(len(self.polyline_pos_dim)))
        if "polyline" in scenario.keys():
            scenario = scenario["polyline"] 
        
        self.map = scenario
        for polyline_id, polyline_info in self.map.items():
            self.map[polyline_id]["states"] = interpolate(polyline_info["states"], max_dist=2)
            if map_offset:
                self.map[polyline_id]["states"][..., self.polyline_pos_dim] += self.map_center[:len(self.polyline_pos_dim)]
        
        self.map_loaded = True
        
        self._update_related_map_cfg()
        
        if map_file is not None:
            print(f"Successfully load map from '{map_file}'")
            
    def load_agent(self, agent_file: str = None, agent_dict: dict = None, map_offset: bool = False):
        if agent_file is not None:
            scenario = pickle.load(open(agent_file, "rb"))
        if agent_dict is not None:
            scenario = agent_dict

        self.vehicle_id_per_step = scenario["vehicle_id_per_step"]
        self.vehicle_state_per_step = scenario["vehicle_state_per_step"]
        self.vehicle_static_attribute = scenario["vehicle_static_attribute"]
        
        if map_offset:
            for t in range(len(self.vehicle_state_per_step)):
                self.vehicle_state_per_step[t][..., self.vehicle_pos_dim] += self.map_center[:len(self.vehicle_pos_dim)]
    
        self.all_vehicle_ids = list(self.vehicle_static_attribute.keys())
        self.num_vehicle = len(self.all_vehicle_ids)
        self.vid_to_index = {self.all_vehicle_ids[i]: i for i in range(self.num_vehicle)}
        self.total_step = len(self.vehicle_id_per_step)
        
        if "dynamic_polyline_id_per_step" in agent_dict.keys():
            self.tl_id_per_step = scenario["dynamic_polyline_id_per_step"]
            self.tl_type_per_step = [np.argmax(state, axis=-1) if len(state) > 0 else [] for state in scenario["dynamic_polyline_state_per_step"] ]
        else:
            self.tl_id_per_step = [[] for __ in range(self.total_step)]
            self.tl_type_per_step = [[] for __ in range(self.total_step)]
        
        self.agent_loaded = True
        
        self._update_related_agent_cfg()
        
        if agent_file is not None:
            print(f"Successfully load agent from '{agent_file}'")
    
    def load_default_cfg(self):
        # configs
        self.video_frame_interval = 5
        self.video_fps = 10
        self.ROI_radius = 160
        self.history_frame = 8
        self.video_dpi = 300
        
        # visulization effect config
        self.color_gradient_interp_step = 2
        self.alpha_start, self.alpha_end = 0.05, 0.8     # color alpha change from alpha_start (-history_frame) to alpha_end (now)
        self.ego_color = 'maroon'
        self.default_vehicle_color_list = ['dodgerblue', 'darkgreen', 'indigo', 'darkcyan', 'mediumslateblue', 'lightgreen', 'lightblue', 'cyan', 'orange']
        self.vehicle_color_dict = {230: "red"}
        
        # dimension config
        self.vehicle_pos_dim = [0, 1]
        self.vehicle_h_dim = [2]
        self.polyline_pos_dim = [0, 1]
        self.polyline_h_dim = [-1]
        
        self._update_related_cfg()

    def _update_related_cfg(self):
        self._update_related_viewer_cfg()
        if self.agent_loaded:
            self._update_related_agent_cfg()
        if self.map_loaded:
            self._update_related_map_cfg()
    
    def _update_related_viewer_cfg(self):
        target_accum_alpha = np.linspace(self.alpha_start, self.alpha_end, (self.color_gradient_interp_step+1)*self.history_frame+1)
        alpha_list = [1 - target_accum_alpha[0]]
        for alpha in target_accum_alpha[1:]:
            alpha_list.append((1 - alpha) / np.prod(alpha_list))
        self.alpha_list = [1 - alpha for alpha in alpha_list]
        
    def _update_related_agent_cfg(self):
        self.vehicle_colors = {id:self.default_vehicle_color_list[random.randint(0, len(self.default_vehicle_color_list)-1)] for id in self.all_vehicle_ids}
        self.vehicle_colors.update(self.vehicle_color_dict)
        
        
    def _update_related_map_cfg(self):
        pass
     
    @staticmethod
    def group_sequence_with_mask(seq, mask):
        group_index = []        # pairs of indices for <group start: group end>
        prev_mask, prev_mask_id = False, -1
        for i in range(len(mask)):
            if mask[i] == True and prev_mask == False:
                prev_mask, prev_mask_id = mask[i], i
            elif mask[i] == False and prev_mask == True:
                group_index.append([prev_mask_id, i])
                prev_mask, prev_mask_id = mask[i], i
                
        if prev_mask == True:
            group_index.append([prev_mask_id, len(mask)])
            
        if len(group_index) > 0:
            grouped_seq = [seq[index[0]:index[1]] for index in group_index]
            return grouped_seq, group_index
        else:
            return [], []
        
    def set_config(self, **tgt_cfg):
        self.video_frame_interval = tgt_cfg.get("video_frame_interval", self.video_frame_interval)
        self.video_fps = tgt_cfg.get("video_fps", self.video_fps)
        self.video_dpi = tgt_cfg.get("video_dpi", self.video_dpi)
        self.ROI_radius = tgt_cfg.get("ROI_radius", self.ROI_radius)
        self.history_frame = tgt_cfg.get("history_frame", self.history_frame)
        self.alpha_start = tgt_cfg.get("alpha_start", self.alpha_start)
        self.alpha_end = tgt_cfg.get("alpha_end", self.alpha_end)
        self.ego_color = tgt_cfg.get("ego_color", self.ego_color)
        self.default_vehicle_color_list = tgt_cfg.get("vehicle_color_list", self.default_vehicle_color_list)
        self.vehicle_color_dict = tgt_cfg.get("vehicle_color_dict", self.vehicle_color_dict)
        self.vehicle_pos_dim = tgt_cfg.get("vehicle_pos_dim", self.vehicle_pos_dim)
        self.vehicle_h_dim = tgt_cfg.get("vehicle_h_dim", self.vehicle_h_dim)
        self.polyline_pos_dim = tgt_cfg.get("polyline_pos_dim", self.polyline_pos_dim)
        self.polyline_h_dim = tgt_cfg.get("polyline_h_dim", self.polyline_h_dim)
        self._update_related_cfg()

    def view_map(self, inf=None, sup=None, ourput_dir="./", map_desc="tmpmap", 
                 showaxis=False, 
                 plot_start_end=False, 
                 plot_drct=False, 
                 plot_id_topology=False, 
                 max_topo_num=100,
                 plot_mesh=False):
        assert not (plot_id_topology and plot_drct), "plot_id_topology and plot_drct cannot be True at the same time"
        
        if sup is None:
            sup = np.max(np.concatenate([np.max(info["states"][..., :2], axis=0, keepdims=True) for info in self.map.values()]), axis=0)
        if inf is None:
            inf = np.min(np.concatenate([np.min(info["states"][..., :2], axis=0, keepdims=True) for info in self.map.values()]), axis=0)
        sup, inf = np.array(sup), np.array(inf)
        
        polyline_ids, polylines, polyline_types = [], [], []
        for p_id, p_info in self.map.items():
            polyline_ids.append(p_id)
            points = p_info["states"][..., self.polyline_pos_dim]
            mask = np.logical_and(np.all(points >= inf.reshape(1, 2), axis=-1), np.all(points <= sup.reshape(-1, 2), axis=-1))
            polylines.extend(ScenarioViewer.group_sequence_with_mask(p_info["states"][..., self.polyline_pos_dim+self.polyline_h_dim], mask)[0])
            polyline_types.extend([p_info["type"]]*(len(polylines)-len(polyline_types)))
        
        if plot_id_topology or plot_start_end:
            center_lane_type = [0, 4]
            prev_lanes_id = {}
            next_lanes_id = {}
            for p_id, p_info in self.map.items():
                if p_info["type"] in center_lane_type:
                    prev_lanes_id[p_id] = p_info["prev_lanes_id"]
                    next_lanes_id[p_id] = p_info["next_lanes_id"]
            random_selected_id = random.choices(list(prev_lanes_id.keys()), k=max_topo_num)
        
        plt.figure(facecolor='lightgray')
        plt.gca().set_facecolor('lightgray')
        plt.xlim(inf[0], sup[0])
        plt.ylim(inf[1], sup[1])
        plt.axis('equal')
        if not showaxis:
            plt.axis('off')
        
        # 0: white, 1: dimgray, 2: black, 3: gray, 4: light blue
        polyline_color = {0: "white", 1: 'dimgray', 2: 'black', 3: 'gray', 4: '#dfdfff'}
        polyline_style = {0: "dashed", 1: 'solid', 2:'solid', 3:'dashed', 4: "dashed"}  
        polyline_width = {0: 1, 1: 1, 2: 1.5, 3: 1, 4: 1}
        lw_scale = 100 / max(sup - inf)
        txt_scale = 0.1
        polyline_arrow_num = 2
        for polyline_id, polyline_type, polyline in zip(polyline_ids, polyline_types, polylines):
            color = polyline_color[polyline_type]
            if plot_start_end:
                if polyline_type in center_lane_type:
                    if len(prev_lanes_id[polyline_id]) > 0 and len(next_lanes_id[polyline_id]) == 0:
                        color = "yellow"
                    elif len(prev_lanes_id[polyline_id]) == 0 and len(next_lanes_id[polyline_id]) > 0:
                        color = "green"
                    elif len(prev_lanes_id[polyline_id]) == 0 and len(next_lanes_id[polyline_id]) == 0:
                        color = "red"
            plt.plot(polyline[:, 0], 
                     polyline[:, 1],
                     color=color,
                     linestyle=polyline_style[polyline_type],
                     linewidth=polyline_width[polyline_type] * lw_scale,
                     zorder=0,
                     alpha=0.5)
            if plot_drct:
                step = (len(polyline) + polyline_arrow_num - 1) // polyline_arrow_num
                plt.quiver(polyline[::step, 0], polyline[::step, 1], 
                           np.cos(polyline[::step, 2]), np.sin(polyline[::step, 2]), 
                           angles='xy', scale_units='xy', scale=0.5, 
                           width=0.002 * polyline_width[polyline_type] * lw_scale, headwidth=3, headlength=5, headaxislength=5,
                           linestyle=polyline_style[polyline_type], color="blue", zorder=1)
            if plot_id_topology:
                if polyline_type not in center_lane_type:
                    continue
                text = str(polyline_id)
                color = "black"
                if polyline_id in random_selected_id:
                    prev_text, next_text = "", ""
                    prev_text = [f"p{str(p_id)}" for p_id in prev_lanes_id[polyline_id]]
                    prev_text = "-" + "-".join(prev_text)
                    next_text = [f"n{str(n_id)}" for n_id in next_lanes_id[polyline_id]]
                    next_text = "+" + "+".join(next_text)
                    text = f"{text}{prev_text}{next_text}"
                    color = "red"
                plt.text(polyline[len(polyline)//2, 0], polyline[len(polyline)//2, 1], text, fontsize=txt_scale, 
                         ha='center', va='center', zorder=10 if color == "black" else 20, color=color)
                
        if plot_mesh:
            # edit ticks to times of 10
            int_inf = (inf // 10 * 10).astype(int)
            int_sup = -(-sup // 10 * 10).astype(int)
            
            print(inf, int_inf, sup, int_sup)
            plt.xticks(range(int_inf[0], int_sup[0], 10), fontsize=0.5, rotation=-90)
            plt.yticks(range(int_inf[1], int_sup[1], 10), fontsize=0.5)
            plt.xlim(inf[0], sup[0])
            plt.ylim(inf[1], sup[1])
            # plt.grid(color="grey", ls='--', lw=0.005)
            
            for i, x in enumerate(range(int_inf[0]+10, int_sup[0], 10)):
                c = "grey" if i % 2 == 0 else "brown"
                plt.plot([x,x], [int_inf[1], int_sup[1]], c=c, ls='--', lw=0.01)
            for i, y in enumerate(range(int_inf[1]+10, int_sup[1], 10)):
                c = "grey" if i % 2 == 0 else "brown"
                plt.plot([int_inf[0], int_sup[0]], [y, y], c=c, ls='--', lw=0.01)


        plt.savefig(os.path.join(ourput_dir, f"{map_desc}.pdf"), bbox_inches="tight")
        print(f"save map to {os.path.join(ourput_dir, f'{map_desc}.pdf')}, range {inf} to {sup}")
    
    def make_agent_centric_video(self, video_desc: str, output_dir: str="./", 
                                 ego_num: int=1, ego_id:int|str|list[int|str]|None=None, 
                                 step_range=[None, None],
                                 showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        if ego_id is not None:
            if not isinstance(ego_id, list):
                ego_id = [ego_id]
            if not set(ego_id).issubset(self.all_vehicle_ids):
                print(f"remove unknown vehicle id {set(ego_id) - set(self.all_vehicle_ids)}")
                ego_id = list(set(ego_id) & set(self.all_vehicle_ids))
            ego_num = len(ego_id)
        else:
            ego_num = min(self.num_vehicle, ego_num)
            ego_id = random.sample(self.all_vehicle_ids, k=ego_num)
        
        step_range = list(step_range)
        if step_range[0] is None:
            step_range[0] = -1
        if step_range[1] is None:
            step_range[1] = float('inf')
            
        for center_vehicle in ego_id:    # only for center vehicle with continuous trajactory
            traj_history = deque(maxlen=self.history_frame + 1)
            traj_history_mask = deque(maxlen=self.history_frame + 1)
            
            out = None
            
            for t in tqdm.trange(0, self.total_step, self.video_frame_interval, leave=False, desc=f"ego {center_vehicle} - video frame"):
                current_vehicles = self.vehicle_id_per_step[t]
                if center_vehicle not in current_vehicles:
                    continue
                if t < step_range[0] or t > step_range[1]:
                    continue
                
                current_vehicle_states = np.array(self.vehicle_state_per_step[t])[..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)   # xyheading 
                center_position = current_vehicle_states[current_vehicles.index(center_vehicle)][:2]
                
                # find valid polylines
                valid_polylines = []
                valid_polyline_ids = []
                valid_polyline_types = []
                for polyline_id, polyline_info in self.map.items():
                    polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                    valid_polyline_mask = np.linalg.norm(polyline_point - center_position[None, :], axis=-1) < self.ROI_radius
                    valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                    valid_polyline_ids.extend([polyline_id]*(len(valid_polylines)-len(valid_polyline_ids)))
                    valid_polyline_types.extend([polyline_info["type"]]*(len(valid_polylines)-len(valid_polyline_types)))

                # find valid vehicles
                valid_vehicle_mask = np.linalg.norm(center_position[None, :] - current_vehicle_states[..., :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_vehicle_states[valid_vehicle_mask]
                valid_vehicle_static = np.array([self.vehicle_static_attribute[id] for id in valid_vehicle_ids])
                    
                frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                for vehicle_id, vehicle_state in zip(valid_vehicle_ids, valid_vehicle_states):
                    v_index = self.vid_to_index[vehicle_id]
                    frame_traj[v_index] = vehicle_state[:2]
                    frame_mask[v_index] = True
                
                traj_history.append(frame_traj)
                traj_history_mask.append(frame_mask)
                
                hist_traj = np.stack(traj_history, axis=0)
                hist_mask = np.stack(traj_history_mask, axis=0)
                valid_history_frame = hist_traj.shape[0] - 1
                
                fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
                ax = plt.gca()
                plt.xlim(center_position[0]-self.ROI_radius, center_position[0]+self.ROI_radius)
                plt.ylim(center_position[1]-self.ROI_radius, center_position[1]+self.ROI_radius)
                if not showaxis:
                    plt.axis('off')
                if plot_step:
                    plt.title(f"Step {t}")
                
                # draw polylines
                polyline_color = {0: "white", 1: 'dimgray', 2:'black', 3:'gray', 4:'white'}
                tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'gray'}
                polyline_style = {0: "dashed", 1: 'solid', 2:'solid', 3:'dashed', 4: "dashed"}
                polyline_width = {0: 0.5, 1: 0.5, 2: 0.8, 3: 0.5, 4: 0.5}
                for polyline_id, polyline_type, polyline in zip(valid_polyline_ids, valid_polyline_types, valid_polylines):
                    if polyline_id in self.tl_id_per_step[t]:
                        color = tl_polyline_color[self.tl_type_per_step[t][self.tl_id_per_step[t].index(polyline_id)]]
                    else:
                        color = polyline_color[polyline_type]
                    plt.plot(polyline[:, 0], 
                            polyline[:, 1],
                            color=color,
                            linestyle=polyline_style[polyline_type],
                            linewidth=polyline_width[polyline_type],
                            zorder=0)
                    
                # draw vehicles
                vehicle_boxes = get_rotated_box(valid_vehicle_states[:, 0], valid_vehicle_states[:, 1], 
                                                valid_vehicle_static[:, 0], valid_vehicle_static[:, 1], valid_vehicle_states[:, 2])
                for vehicle_id, box in zip(valid_vehicle_ids, vehicle_boxes):
                    patch = plt.Polygon(box, facecolor=self.vehicle_colors[vehicle_id] if vehicle_id != center_vehicle else 'maroon', edgecolor='black', linewidth=0.5, zorder=10)
                    ax.add_patch(patch)
                if plot_id:
                    for vehicle_id, vehicle_pos in zip(valid_vehicle_ids, valid_vehicle_states):
                        ax.text(vehicle_pos[0], vehicle_pos[1], str(vehicle_id), ha='center', va='center', color='white', fontsize=3, zorder=20)
                    
                # draw history trajactories
                color_step = self.color_gradient_interp_step + 1
                active_indices = np.where(hist_mask.any(axis=0))[0]
                for i in active_indices:
                    vehicle_id = self.all_vehicle_ids[i]
                    vehicle_history_traj = hist_traj[:, i, :]
                    vehicle_history_mask = hist_mask[:, i]
                    
                    grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(vehicle_history_traj, vehicle_history_mask)
                    for traj, traj_index in zip(grouped_traj, group_index):
                        step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                        for j in range(step_from_first_frame * color_step):
                            plt.plot(traj[:, 0],
                                    traj[:, 1],
                                    color=self.vehicle_colors[vehicle_id] if vehicle_id != center_vehicle else 'maroon',
                                    linewidth=3,
                                    alpha=self.alpha_list[j],       
                                    zorder=1)
                        
                        interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]))
                        for j in range(interp_traj.shape[1]):
                            interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]), np.arange(traj.shape[0]) * color_step, traj[:, j])
                        for j in range(len(interp_traj)):
                            plt.plot(interp_traj[j:, 0],
                                    interp_traj[j:, 1],
                                    color=self.vehicle_colors[vehicle_id] if vehicle_id != center_vehicle else 'maroon',
                                    linewidth=3,
                                    alpha=self.alpha_list[j + step_from_first_frame * color_step],       
                                    zorder=1)
                
                # export to array    
                canvas = FigureCanvas(fig)
                canvas.draw() 
                width, height = fig.canvas.get_width_height()
                image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
                image = cv2.cvtColor(image.reshape((height, width, 4))[..., :3], cv2.COLOR_BGR2RGB)
                plt.close()
                
                if out is None:
                    os.makedirs(os.path.dirname(os.path.abspath(f'{os.path.join(output_dir, video_desc)}.mp4')), exist_ok=True)
                    video_name = f'{os.path.join(output_dir, video_desc)}_ego_id_{center_vehicle}.mp4'
                    out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), self.video_fps, (image.shape[1], image.shape[0]))
                
                out.write(image)
            
            if out is None:
                print(f"skip invalid ego {center_vehicle}")
                continue
            
            out.release()
            print(f"save video to {video_name}")
    
    def make_region_photo(self, photo_desc: str, output_dir: str="./",
                          region_center: np.ndarray|None=None, steps=[0], 
                          showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        for step in steps:    
            if region_center is None:
                vehicle_states_center_frame = self.vehicle_state_per_step[step]
                if len(vehicle_states_center_frame) == 0:
                    for i in range(self.total_step):
                        if len(self.vehicle_state_per_step[i]) != 0:
                            vehicle_states_center_frame = self.vehicle_state_per_step[i]
                            break
                if len(vehicle_states_center_frame) == 0:
                    print("No default region position inferred")
                    return
                max_vehicle_loc = np.max(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0)
                min_vehicle_loc = np.min(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0)
                single_region_center = (max_vehicle_loc + min_vehicle_loc) / 2
            else:
                single_region_center = np.array(region_center).flatten()[:2]
            
            valid_polylines = []
            valid_polyline_ids = []
            valid_polyline_types = []
            for polyline_id, polyline_info in self.map.items():
                polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                valid_polyline_mask = (np.linalg.norm(polyline_point - single_region_center[None, :], axis=-1) < self.ROI_radius)
                valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
                valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))
            
            x_min, x_max = single_region_center[0] - self.ROI_radius, single_region_center[0] + self.ROI_radius
            y_min, y_max = single_region_center[1] - self.ROI_radius, single_region_center[1] + self.ROI_radius
            
            traj_history = deque(maxlen=self.history_frame + 1)
            traj_history_mask = deque(maxlen=self.history_frame + 1)
            
            start_step = max(0, step - self.history_frame * self.video_frame_interval)
            for t in range(start_step, step + 1, self.video_frame_interval):
                frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                
                current_vehicles = self.vehicle_id_per_step[t]
                current_vehicle_states = self.vehicle_state_per_step[t][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)   # xyheading 
                valid_vehicle_mask = np.linalg.norm(single_region_center[None, :] - current_vehicle_states[..., :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_vehicle_states[valid_vehicle_mask]
                
                for v_id, v_state in zip(valid_vehicle_ids, valid_vehicle_states):
                    v_index = self.vid_to_index[v_id]
                    frame_traj[v_index] = v_state[:2]
                    frame_mask[v_index] = True
                
                traj_history.append(frame_traj)
                traj_history_mask.append(frame_mask)
            
            fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            if not showaxis:
                ax.axis('off')
            if plot_step:
                ax.set_title(f"Step {step}")
            
            static_map_img = self._render_static_region_map(x_min, x_max, y_min, y_max, single_region_center)
            ax.imshow(static_map_img, extent=(x_min, x_max, y_min, y_max), zorder=0)
            
            tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'white'}
            for polyline_id, polyline in zip(valid_polyline_ids, valid_polylines):
                if polyline_id not in self.tl_id_per_step[step]:
                    continue
                ax.plot(polyline[:, 0], 
                        polyline[:, 1],
                        color=tl_polyline_color[self.tl_type_per_step[step][self.tl_id_per_step[step].index(polyline_id)]],
                        linestyle="dashed",
                        linewidth=0.5,
                        zorder=0)
            
            hist_traj = np.stack(traj_history, axis=0)
            hist_mask = np.stack(traj_history_mask, axis=0)
            valid_history_frame = hist_traj.shape[0] - 1
            color_step = self.color_gradient_interp_step + 1
            active_indices = np.where(hist_mask.any(axis=0))[0]

            for i in active_indices:
                vehicle_id = self.all_vehicle_ids[i]
                v_traj, v_mask = hist_traj[:, i, :], hist_mask[:, i]
                grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(v_traj, v_mask)
                
                for traj, traj_index in zip(grouped_traj, group_index):
                    if len(traj) < 2:
                        continue
                    step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                    
                    interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]), dtype=float)
                    for j in range(interp_traj.shape[1]):
                        interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]), np.arange(traj.shape[0]) * color_step, traj[:, j])
                    
                    for j in range(0, len(interp_traj) - 1):
                        alpha_idx = min(j + step_from_first_frame * color_step, len(self.alpha_list) - 1)
                        ax.plot(interp_traj[j:j+2, 0], interp_traj[j:j+2, 1],
                                color=self.vehicle_colors[vehicle_id], linewidth=3,
                                alpha=self.alpha_list[alpha_idx], zorder=1)
            
            current_vehicles = self.vehicle_id_per_step[step]
            if len(current_vehicles) > 0:
                current_states = self.vehicle_state_per_step[step][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)
                v_mask = np.linalg.norm(single_region_center[None, :] - current_states[..., :2], axis=-1) < self.ROI_radius
                valid_ids = np.array(current_vehicles, dtype=object)[v_mask]
                valid_states = current_states[v_mask]
                valid_static = np.array([self.vehicle_static_attribute[vid] for vid in valid_ids])

                vehicle_boxes = get_rotated_box(valid_states[:, 0], valid_states[:, 1], 
                                                valid_static[:, 0], valid_static[:, 1], valid_states[:, 2])
                for vid, box in zip(valid_ids, vehicle_boxes):
                    patch = plt.Polygon(box, facecolor=self.vehicle_colors[vid], edgecolor='black', linewidth=0.5, zorder=10)
                    ax.add_patch(patch)
                    if plot_id:
                        ax.text(box[0,0], box[0,1], str(vid), ha='center', va='center', color='white', fontsize=3, zorder=20)
            
            os.makedirs(output_dir, exist_ok=True)
            photo_name = f'{os.path.join(output_dir, photo_desc)}_step{step}_loc_{int(single_region_center[0])}_{int(single_region_center[1])}.png'
            
            canvas = FigureCanvas(fig)
            canvas.draw()
            width, height = fig.canvas.get_width_height()
            image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
            image = image.reshape((height, width, 4))[..., :3] # RGBA to RGB
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            
            cv2.imwrite(photo_name, image)
            plt.close(fig)
            print(f"Save photo to {photo_name}")
        
    def make_region_centric_video(self, video_desc: str, output_dir: str="./", 
                                  region_center: np.ndarray|None=None, step_range=[None, None], 
                                  showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        if region_center is None:
            center_frame = self.total_step // 2
            vehicle_states_center_frame = self.vehicle_state_per_step[center_frame]
            if len(vehicle_states_center_frame) == 0:
                for i in range(self.total_step):
                    if len(self.vehicle_state_per_step[i]) != 0:
                        vehicle_states_center_frame = self.vehicle_state_per_step[i]
                        break
            if len(vehicle_states_center_frame) == 0:
                print("No default region position inferred for empty scenario")
                return
            max_vehicle_loc = np.max(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0, keepdims=True)
            min_vehicle_loc = np.min(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0, keepdims=True)
            region_center = (max_vehicle_loc + min_vehicle_loc) / 2
        else:
            region_center = np.array(region_center).reshape(-1, 2)
        
        step_range = list(step_range)
        if step_range[0] is None:
            step_range[0] = -1
        if step_range[1] is None:
            step_range[1] = float('inf')
        
        for single_region_center in region_center:
            # find valid polylines
            valid_polylines = []
            valid_polyline_ids = []
            valid_polyline_types = []
            for polyline_id, polyline_info in self.map.items():
                polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                valid_polyline_mask = (np.linalg.norm(polyline_point - single_region_center[None, :], axis=-1) < self.ROI_radius)
                valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
                valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))
            
            x_min = single_region_center[0] - self.ROI_radius
            x_max = single_region_center[0] + self.ROI_radius
            y_min = single_region_center[1] - self.ROI_radius
            y_max = single_region_center[1] + self.ROI_radius
            
            static_map_img = self._render_static_region_map(
                x_min, x_max, y_min, y_max,
                single_region_center
            )
            
            traj_history = deque(maxlen=self.history_frame + 1)
            traj_history_mask = deque(maxlen=self.history_frame + 1)
            
            out = None
            started = False
            
            for t in tqdm.trange(0, self.total_step, self.video_frame_interval,
                                leave=False, desc='region centric - video frame'):
                current_vehicles = self.vehicle_id_per_step[t]
                if len(current_vehicles) == 0 and not started:
                    continue
                else:
                    started = True
                if t < step_range[0] or t > step_range[1]:
                    continue
                
                current_vehicle_states = self.vehicle_state_per_step[t][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)   # xyheading 
                valid_vehicle_mask = np.linalg.norm(single_region_center[None, :] - current_vehicle_states[..., :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_vehicle_states[valid_vehicle_mask]
                valid_vehicle_static = np.array([self.vehicle_static_attribute[id] for id in valid_vehicle_ids])
                
                if not np.any(valid_vehicle_mask):
                    frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                    frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                    traj_history.append(frame_traj)
                    traj_history_mask.append(frame_mask)
                    continue
                
                frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                for vehicle_id, vehicle_state in zip(valid_vehicle_ids, valid_vehicle_states):
                    v_index = self.vid_to_index[vehicle_id]
                    frame_traj[v_index] = vehicle_state[:2]
                    frame_mask[v_index] = True
                
                traj_history.append(frame_traj)
                traj_history_mask.append(frame_mask)
                
                hist_traj = np.stack(traj_history, axis=0)
                hist_mask = np.stack(traj_history_mask, axis=0)
                valid_history_frame = hist_traj.shape[0] - 1
                
                fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
                ax = fig.add_axes([0, 0, 1, 1])
                ax.set_xlim(x_min, x_max)
                ax.set_ylim(y_min, y_max)
                if not showaxis:
                    ax.axis('off')
                if plot_step:
                    ax.set_title(f"Step {t}")
                
                # draw polylines
                ax.imshow(
                    static_map_img, 
                    extent=(x_min, x_max, y_min, y_max), 
                    zorder=0
                )
                
                tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'gray'}
                for polyline_id, polyline in zip(valid_polyline_ids, valid_polylines):
                    if polyline_id not in self.tl_id_per_step[t]:
                        continue
                    ax.plot(polyline[:, 0], 
                             polyline[:, 1],
                             color=tl_polyline_color[self.tl_type_per_step[t][self.tl_id_per_step[t].index(polyline_id)]],
                             linestyle="dashed",
                             linewidth=0.5,
                             zorder=0)
                    
                # draw vehicles
                if len(valid_vehicle_ids) > 0:
                    vehicle_boxes = get_rotated_box(valid_vehicle_states[:, 0], valid_vehicle_states[:, 1], 
                                                    valid_vehicle_static[:, 0], valid_vehicle_static[:, 1], valid_vehicle_states[:, 2])
                    for vehicle_id, box in zip(valid_vehicle_ids, vehicle_boxes):
                        patch = plt.Polygon(box, facecolor=self.vehicle_colors[vehicle_id], edgecolor='black', linewidth=0.5, zorder=10)
                        ax.add_patch(patch)
                    if plot_id:
                        for vehicle_id, vehicle_pos in zip(valid_vehicle_ids, valid_vehicle_states):
                            ax.text(vehicle_pos[0], vehicle_pos[1], str(vehicle_id), ha='center', va='center', color='white', fontsize=3, zorder=20)

                # draw history trajactories
                color_step = self.color_gradient_interp_step + 1
                active_indices = np.where(hist_mask.any(axis=0))[0]
                for i in active_indices:
                    vehicle_id = self.all_vehicle_ids[i]
                    vehicle_history_traj = hist_traj[:, i, :]
                    vehicle_history_mask = hist_mask[:, i]

                    grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(vehicle_history_traj, vehicle_history_mask)
                    for traj, traj_index in zip(grouped_traj, group_index):
                        step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                        for j in range(step_from_first_frame * color_step):
                            ax.plot(
                                traj[:, 0],
                                traj[:, 1],
                                color=self.vehicle_colors[vehicle_id],
                                linewidth=3,
                                alpha=self.alpha_list[j],
                                zorder=1,
                            )
                        
                        interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]), dtype=float)
                        for j in range(interp_traj.shape[1]):
                            interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]), np.arange(traj.shape[0]) * color_step, traj[:, j])
                        for j in range(len(interp_traj)):
                            ax.plot(
                                interp_traj[j:, 0],
                                interp_traj[j:, 1],
                                color=self.vehicle_colors[vehicle_id],
                                linewidth=3,
                                alpha=self.alpha_list[j + step_from_first_frame * color_step],
                                zorder=1,
                            )
                fig.text(
                    0.03, 0.97,
                    f"{int(self.video_fps / 10 * self.video_frame_interval)}× Speed",
                    ha='left', va='top',
                    color='black',
                    fontsize=20,
                    zorder=100,
                )
                
                canvas = FigureCanvas(fig)
                canvas.draw()
                width, height = fig.canvas.get_width_height()
                image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
                image = cv2.cvtColor(image.reshape((height, width, 4))[..., :3], cv2.COLOR_BGR2RGB)
                plt.close()

                if out is None:
                    os.makedirs(os.path.dirname(os.path.abspath(f'{os.path.join(output_dir, video_desc)}.mp4')), exist_ok=True)
                    video_name = f'{os.path.join(output_dir, video_desc)}_location_{int(single_region_center[0])}_{int(single_region_center[1])}.mp4'
                    out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), self.video_fps, (image.shape[1], image.shape[0]))
                
                out.write(image)

            out.release()
            print(f"save video to {video_name}")
    
    def make_region_centric_video_lane_closure(self, video_desc: str, output_dir: str="./", 
                                               region_center: np.ndarray|None=None, step_range=[None, None], 
                                               lc_polygon: list[np.ndarray] = [None], lc_step_range = [None, None],
                                               showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        if region_center is None:
            center_frame = self.total_step // 2
            vehicle_states_center_frame = self.vehicle_state_per_step[center_frame]
            if len(vehicle_states_center_frame) == 0:
                for i in range(self.total_step):
                    if len(self.vehicle_state_per_step[i]) != 0:
                        vehicle_states_center_frame = self.vehicle_state_per_step[i]
                        break
            if len(vehicle_states_center_frame) == 0:
                print("No default region position inferred for empty scenario")
                return
            max_vehicle_loc = np.max(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0, keepdims=True)
            min_vehicle_loc = np.min(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0, keepdims=True)
            region_center = (max_vehicle_loc + min_vehicle_loc) / 2
        else:
            region_center = np.array(region_center).reshape(-1, 2)
        
        step_range = list(step_range)
        if step_range[0] is None:
            step_range[0] = -1
        if step_range[1] is None:
            step_range[1] = float('inf')
        
        for single_region_center in region_center:
            # find valid polylines
            valid_polylines = []
            valid_polyline_ids = []
            valid_polyline_types = []
            for polyline_id, polyline_info in self.map.items():
                polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                valid_polyline_mask = (np.linalg.norm(polyline_point - single_region_center[None, :], axis=-1) < self.ROI_radius)
                valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
                valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))
            
            x_min = single_region_center[0] - self.ROI_radius
            x_max = single_region_center[0] + self.ROI_radius
            y_min = single_region_center[1] - self.ROI_radius
            y_max = single_region_center[1] + self.ROI_radius
            
            static_map_img = self._render_static_region_map(
                x_min, x_max, y_min, y_max,
                single_region_center
            )
            
            traj_history = deque(maxlen=self.history_frame + 1)
            traj_history_mask = deque(maxlen=self.history_frame + 1)
            
            out = None
            started = False
            
            for t in tqdm.trange(0, self.total_step, self.video_frame_interval,
                                leave=False, desc='region centric - video frame'):
                current_vehicles = self.vehicle_id_per_step[t]
                if len(current_vehicles) == 0 and not started:
                    continue
                else:
                    started = True
                if t < step_range[0] or t > step_range[1]:
                    continue
                
                current_vehicle_states = self.vehicle_state_per_step[t][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)   # xyheading 
                valid_vehicle_mask = np.linalg.norm(single_region_center[None, :] - current_vehicle_states[..., :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_vehicle_states[valid_vehicle_mask]
                valid_vehicle_static = np.array([self.vehicle_static_attribute[id] for id in valid_vehicle_ids])
                
                if not np.any(valid_vehicle_mask):
                    frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                    frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                    traj_history.append(frame_traj)
                    traj_history_mask.append(frame_mask)
                    continue
                
                frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                for vehicle_id, vehicle_state in zip(valid_vehicle_ids, valid_vehicle_states):
                    v_index = self.vid_to_index[vehicle_id]
                    frame_traj[v_index] = vehicle_state[:2]
                    frame_mask[v_index] = True
                
                traj_history.append(frame_traj)
                traj_history_mask.append(frame_mask)
                
                hist_traj = np.stack(traj_history, axis=0)
                hist_mask = np.stack(traj_history_mask, axis=0)
                valid_history_frame = hist_traj.shape[0] - 1
                
                fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
                ax = fig.add_axes([0, 0, 1, 1])
                ax.set_xlim(x_min, x_max)
                ax.set_ylim(y_min, y_max)
                if not showaxis:
                    ax.axis('off')
                if plot_step:
                    ax.set_title(f"Step {t}")
                
                # draw polylines
                ax.imshow(
                    static_map_img, 
                    extent=(x_min, x_max, y_min, y_max), 
                    zorder=0
                )
                
                if lc_step_range[0] <= t <= lc_step_range[1]:
                    for poly in lc_polygon:
                        if poly is not None:
                            lc_patch = plt.Polygon(
                                poly, 
                                facecolor=to_rgba('orange', alpha=0.7),
                                edgecolor='red', 
                                hatch='/////',
                                linewidth=0.6, 
                                zorder=5
                            )
                            ax.add_patch(lc_patch)
                
                tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'gray'}
                for polyline_id, polyline in zip(valid_polyline_ids, valid_polylines):
                    if polyline_id not in self.tl_id_per_step[t]:
                        continue
                    ax.plot(polyline[:, 0], 
                             polyline[:, 1],
                             color=tl_polyline_color[self.tl_type_per_step[t][self.tl_id_per_step[t].index(polyline_id)]],
                             linestyle="dashed",
                             linewidth=0.5,
                             zorder=0)
                    
                # draw vehicles
                if len(valid_vehicle_ids) > 0:
                    vehicle_boxes = get_rotated_box(valid_vehicle_states[:, 0], valid_vehicle_states[:, 1], 
                                                    valid_vehicle_static[:, 0], valid_vehicle_static[:, 1], valid_vehicle_states[:, 2])
                    for vehicle_id, box in zip(valid_vehicle_ids, vehicle_boxes):
                        patch = plt.Polygon(box, facecolor=self.vehicle_colors[vehicle_id], edgecolor='black', linewidth=0.5, zorder=10)
                        ax.add_patch(patch)
                    if plot_id:
                        for vehicle_id, vehicle_pos in zip(valid_vehicle_ids, valid_vehicle_states):
                            ax.text(vehicle_pos[0], vehicle_pos[1], str(vehicle_id), ha='center', va='center', color='white', fontsize=3, zorder=20)

                # draw history trajactories
                color_step = self.color_gradient_interp_step + 1
                active_indices = np.where(hist_mask.any(axis=0))[0]
                for i in active_indices:
                    vehicle_id = self.all_vehicle_ids[i]
                    vehicle_history_traj = hist_traj[:, i, :]
                    vehicle_history_mask = hist_mask[:, i]

                    grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(vehicle_history_traj, vehicle_history_mask)
                    for traj, traj_index in zip(grouped_traj, group_index):
                        step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                        for j in range(step_from_first_frame * color_step):
                            ax.plot(
                                traj[:, 0],
                                traj[:, 1],
                                color=self.vehicle_colors[vehicle_id],
                                linewidth=3,
                                alpha=self.alpha_list[j],
                                zorder=1,
                            )
                        
                        interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]), dtype=float)
                        for j in range(interp_traj.shape[1]):
                            interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]), np.arange(traj.shape[0]) * color_step, traj[:, j])
                        for j in range(len(interp_traj)):
                            ax.plot(
                                interp_traj[j:, 0],
                                interp_traj[j:, 1],
                                color=self.vehicle_colors[vehicle_id],
                                linewidth=3,
                                alpha=self.alpha_list[j + step_from_first_frame * color_step],
                                zorder=1,
                            )
                fig.text(
                    0.03, 0.97,
                    f"{int(self.video_fps / 10 * self.video_frame_interval)}× Speed",
                    ha='left', va='top',
                    color='black',
                    fontsize=20,
                    zorder=100,
                )
                
                canvas = FigureCanvas(fig)
                canvas.draw()
                width, height = fig.canvas.get_width_height()
                image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
                image = cv2.cvtColor(image.reshape((height, width, 4))[..., :3], cv2.COLOR_BGR2RGB)
                plt.close()

                if out is None:
                    os.makedirs(os.path.dirname(os.path.abspath(f'{os.path.join(output_dir, video_desc)}.mp4')), exist_ok=True)
                    video_name = f'{os.path.join(output_dir, video_desc)}_location_{int(single_region_center[0])}_{int(single_region_center[1])}.mp4'
                    out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), self.video_fps, (image.shape[1], image.shape[0]))
                
                out.write(image)

            out.release()
            print(f"save video to {video_name}")
    
    def make_region_photo_lane_closure(self, photo_desc: str, output_dir: str="./",
                                       region_center: np.ndarray|None=None, steps=[0],
                                       lc_polygon: list[np.ndarray] = [None], lc_step_range = [None, None],
                                       showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        for step in steps:
            if step < 0:
                step = self.total_step + step
            if region_center is None:
                vehicle_states_center_frame = self.vehicle_state_per_step[step]
                if len(vehicle_states_center_frame) == 0:
                    for i in range(self.total_step):
                        if len(self.vehicle_state_per_step[i]) != 0:
                            vehicle_states_center_frame = self.vehicle_state_per_step[i]
                            break
                if len(vehicle_states_center_frame) == 0:
                    print("No default region position inferred")
                    return
                max_vehicle_loc = np.max(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0)
                min_vehicle_loc = np.min(vehicle_states_center_frame[..., self.vehicle_pos_dim], axis=0)
                single_region_center = (max_vehicle_loc + min_vehicle_loc) / 2
            else:
                single_region_center = np.array(region_center).flatten()[:2]
            
            valid_polylines = []
            valid_polyline_ids = []
            valid_polyline_types = []
            for polyline_id, polyline_info in self.map.items():
                polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                valid_polyline_mask = (np.linalg.norm(polyline_point - single_region_center[None, :], axis=-1) < self.ROI_radius)
                valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
                valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))
            
            x_min, x_max = single_region_center[0] - self.ROI_radius, single_region_center[0] + self.ROI_radius
            y_min, y_max = single_region_center[1] - self.ROI_radius, single_region_center[1] + self.ROI_radius
            
            traj_history = deque(maxlen=self.history_frame + 1)
            traj_history_mask = deque(maxlen=self.history_frame + 1)
            
            start_step = max(0, step - self.history_frame * self.video_frame_interval)
            for t in range(start_step, step + 1, self.video_frame_interval):
                frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
                frame_mask = np.zeros(self.num_vehicle, dtype=bool)
                
                current_vehicles = self.vehicle_id_per_step[t]
                current_vehicle_states = self.vehicle_state_per_step[t][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)   # xyheading 
                valid_vehicle_mask = np.linalg.norm(single_region_center[None, :] - current_vehicle_states[..., :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_vehicle_states[valid_vehicle_mask]
                
                for v_id, v_state in zip(valid_vehicle_ids, valid_vehicle_states):
                    v_index = self.vid_to_index[v_id]
                    frame_traj[v_index] = v_state[:2]
                    frame_mask[v_index] = True
                
                traj_history.append(frame_traj)
                traj_history_mask.append(frame_mask)
            
            fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
            ax = fig.add_axes([0, 0, 1, 1])
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(y_min, y_max)
            if not showaxis:
                ax.axis('off')
            if plot_step:
                ax.set_title(f"Step {step}")
            
            static_map_img = self._render_static_region_map(x_min, x_max, y_min, y_max, single_region_center)
            ax.imshow(static_map_img, extent=(x_min, x_max, y_min, y_max), zorder=0)
            
            if lc_step_range[0] <= step <= lc_step_range[1]:
                for poly in lc_polygon:
                    if poly is not None:
                        lc_patch = plt.Polygon(
                            poly, 
                            facecolor=to_rgba('orange', alpha=0.7),
                            edgecolor='red', 
                            hatch='/////',
                            linewidth=0.6, 
                            zorder=5
                        )
                        ax.add_patch(lc_patch)
            
            tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'white'}
            for polyline_id, polyline in zip(valid_polyline_ids, valid_polylines):
                if polyline_id not in self.tl_id_per_step[step]:
                    continue
                ax.plot(polyline[:, 0], 
                        polyline[:, 1],
                        color=tl_polyline_color[self.tl_type_per_step[step][self.tl_id_per_step[step].index(polyline_id)]],
                        linestyle="dashed",
                        linewidth=0.5,
                        zorder=0)
            
            hist_traj = np.stack(traj_history, axis=0)
            hist_mask = np.stack(traj_history_mask, axis=0)
            valid_history_frame = hist_traj.shape[0] - 1
            color_step = self.color_gradient_interp_step + 1
            active_indices = np.where(hist_mask.any(axis=0))[0]

            for i in active_indices:
                vehicle_id = self.all_vehicle_ids[i]
                v_traj, v_mask = hist_traj[:, i, :], hist_mask[:, i]
                grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(v_traj, v_mask)
                
                for traj, traj_index in zip(grouped_traj, group_index):
                    if len(traj) < 2:
                        continue
                    step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                    
                    interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]), dtype=float)
                    for j in range(interp_traj.shape[1]):
                        interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]), np.arange(traj.shape[0]) * color_step, traj[:, j])
                    
                    for j in range(0, len(interp_traj) - 1):
                        alpha_idx = min(j + step_from_first_frame * color_step, len(self.alpha_list) - 1)
                        ax.plot(interp_traj[j:j+2, 0], interp_traj[j:j+2, 1],
                                color=self.vehicle_colors[vehicle_id], linewidth=3,
                                alpha=self.alpha_list[alpha_idx], zorder=1)
            
            current_vehicles = self.vehicle_id_per_step[step]
            if len(current_vehicles) > 0:
                current_states = self.vehicle_state_per_step[step][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)
                v_mask = np.linalg.norm(single_region_center[None, :] - current_states[..., :2], axis=-1) < self.ROI_radius
                valid_ids = np.array(current_vehicles, dtype=object)[v_mask]
                valid_states = current_states[v_mask]
                valid_static = np.array([self.vehicle_static_attribute[vid] for vid in valid_ids])

                vehicle_boxes = get_rotated_box(valid_states[:, 0], valid_states[:, 1], 
                                                valid_static[:, 0], valid_static[:, 1], valid_states[:, 2])
                for vid, box in zip(valid_ids, vehicle_boxes):
                    patch = plt.Polygon(box, facecolor=self.vehicle_colors[vid], edgecolor='black', linewidth=0.5, zorder=10)
                    ax.add_patch(patch)
                    if plot_id:
                        ax.text(box[0,0], box[0,1], str(vid), ha='center', va='center', color='white', fontsize=3, zorder=20)
            
            os.makedirs(output_dir, exist_ok=True)
            photo_name = f'{os.path.join(output_dir, photo_desc)}_step{step}_loc_{int(single_region_center[0])}_{int(single_region_center[1])}.png'
            
            canvas = FigureCanvas(fig)
            canvas.draw()
            width, height = fig.canvas.get_width_height()
            image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
            image = image.reshape((height, width, 4))[..., :3] # RGBA to RGB
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            
            cv2.imwrite(photo_name, image)
            plt.close(fig)
            print(f"Save photo to {photo_name}")
    
    def make_interaction_figure(self, region_center: np.ndarray, step_range: tuple[int, int], ego_id: list[int|str],
                                figure_desc: str, output_dir: str="./", showaxis=False, plot_id=False, plot_step=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario")
        
        for vid in ego_id:
            self.vehicle_colors.update({vid: 'orange'})
        self.vehicle_colors = {k: "dimgray" if k not in ego_id else v for k, v in self.vehicle_colors.items()}

        start_step, end_step = step_range
        single_region_center = np.array(region_center).flatten()[:2]
        
        x_min, x_max = single_region_center[0] - self.ROI_radius, single_region_center[0] + self.ROI_radius
        y_min, y_max = single_region_center[1] - self.ROI_radius, single_region_center[1] + self.ROI_radius
        
        valid_polylines = []
        valid_polyline_ids = []
        for polyline_id, polyline_info in self.map.items():
            polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
            valid_polyline_mask = (np.linalg.norm(polyline_point - single_region_center[None, :], axis=-1) < self.ROI_radius)
            grouped_segments, _ = ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)
            valid_polylines.extend(grouped_segments)
            valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
        
        fig = plt.figure(dpi=600, facecolor='lightgray')
        ax = fig.add_axes([0, 0, 0.9, 1])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        if not showaxis:
            ax.axis('off')
        if plot_step:
            ax.set_title(f"Interaction: Step {start_step} to {end_step}")
        
        dt = getattr(self, 'dt', 0.1) 
        duration_steps = end_step - start_step
        duration_seconds = duration_steps * dt
        
        cmap = cm.get_cmap('rainbow_r')
        norm = mpl.colors.Normalize(vmin=0, vmax=duration_seconds)
        sm = cm.ScalarMappable(norm=norm, cmap=cmap)
        
        cbar_ax = fig.add_axes([0.88, 0.1, 0.02, 0.8])
        cbar = fig.colorbar(sm, cax=cbar_ax)
        
        def time_formatter(x, pos):
            return f"{x:.1f}s"
        
        cbar = fig.colorbar(sm, cax=cbar_ax)
        cbar.ax.yaxis.set_major_formatter(FuncFormatter(time_formatter))
        cbar.ax.tick_params(labelsize=10)
        
        static_map_img = self._render_static_region_map(x_min, x_max, y_min, y_max, single_region_center)
        ax.imshow(static_map_img, extent=(x_min, x_max, y_min, y_max), zorder=0)
        
        tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'gray'}
        for polyline_id, polyline in zip(valid_polyline_ids, valid_polylines):
            if polyline_id in self.tl_id_per_step[start_step]:
                color_idx = self.tl_type_per_step[start_step][self.tl_id_per_step[start_step].index(polyline_id)]
                ax.plot(polyline[:, 0], polyline[:, 1], color=tl_polyline_color[color_idx],
                        linestyle="dashed", linewidth=0.5, zorder=1)
        
        color_step = self.color_gradient_interp_step + 1

        for v_id in ego_id:
            if v_id not in self.vid_to_index:
                continue
            
            future_coords = []
            for t in range(start_step, min(end_step + 1, self.total_step)):
                if v_id in self.vehicle_id_per_step[t]:
                    v_state_idx = self.vehicle_id_per_step[t].index(v_id)
                    future_coords.append(self.vehicle_state_per_step[t][v_state_idx, self.vehicle_pos_dim])
            
            if len(future_coords) < 2:
                continue
            traj = np.array(future_coords)
            
            interp_len = (traj.shape[0] - 1) * color_step + 1
            interp_traj = np.zeros((interp_len, 2), dtype=float)
            for k in range(2):
                interp_traj[:, k] = np.interp(
                    np.arange(interp_len), 
                    np.arange(traj.shape[0]) * color_step, 
                    traj[:, k]
                )
            
            roi_mask = (np.linalg.norm(interp_traj - single_region_center[None, :], axis=-1) < self.ROI_radius)
            interp_traj = interp_traj[roi_mask]
            
            num_segments = len(interp_traj) - 1
            for j in range(num_segments):
                time_ratio = j / num_segments
                current_time_color = cmap(time_ratio)
                
                ax.plot(
                    interp_traj[j:j+2, 0],
                    interp_traj[j:j+2, 1],
                    color=current_time_color,
                    linewidth=4,
                    alpha=1.0,
                    zorder=5,
                    solid_capstyle='round',
                )
        
        current_v_ids = self.vehicle_id_per_step[start_step]
        if len(current_v_ids) > 0:
            states = self.vehicle_state_per_step[start_step][..., self.vehicle_pos_dim+self.vehicle_h_dim].reshape(-1, 3)
            dist = np.linalg.norm(single_region_center[None, :] - states[..., :2], axis=-1)
            v_mask = dist < self.ROI_radius
            
            valid_ids = np.array(current_v_ids, dtype=object)[v_mask]
            valid_states = states[v_mask]
            
            for vid, v_state in zip(valid_ids, valid_states):
                body_color = self.vehicle_colors[vid] if vid in ego_id else 'darkgray'
                edge_color = 'black' if vid in ego_id else 'DimGray'
                
                v_static = self.vehicle_static_attribute[vid]
                box = get_rotated_box(v_state[0], v_state[1], v_static[0], v_static[1], v_state[2])
                
                patch = plt.Polygon(box[0], facecolor=body_color, edgecolor=edge_color, 
                                    linewidth=0.8, zorder=10 if vid in ego_id else 9)
                ax.add_patch(patch)
                
                if plot_id:
                    ax.text(v_state[0], v_state[1], str(vid), ha='center', va='center', 
                            color='white' if vid in ego_id else 'lightgray', fontsize=3, zorder=20)
        
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, f"{figure_desc}_{int(single_region_center[0])}_{int(single_region_center[1])}_step_{start_step}_{end_step}.png")
        
        canvas = FigureCanvas(fig)
        canvas.draw()
        image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
        image = image.reshape((fig.canvas.get_width_height()[1], fig.canvas.get_width_height()[0], 4))[..., :3]
        cv2.imwrite(file_path, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        plt.close(fig)
    
    def make_grid_video(self, video_desc: str, output_dir: str="./", 
                        ego_id:int|str|list[int|str]|None=None, 
                        showaxis=False, plot_id=False):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        if ego_id is not None:
            if not isinstance(ego_id, list):
                ego_ids = [ego_id]
            else:
                ego_ids = list(ego_id)
            ego_ids = [vid for vid in ego_ids if vid in self.all_vehicle_ids]
            if len(ego_ids) == 0:
                print("all given ego_ids are invalid, will sample from all vehicles")
        else:
            ego_ids = []
        
        ego_color_palette = ["maroon", "darkorange", "mediumseagreen", "purple", "slategray"]
        bg_vehicle_color = "lightskyblue"
        
        need_num = min(5, self.num_vehicle) - len(ego_ids)
        need_steps = 3200
        
        if len(ego_ids) == 0:
            intersect_steps = []
            while len(intersect_steps) == 0:
                condidate_ids = random.choice(self.vehicle_id_per_step).copy()
                random.shuffle(condidate_ids)
                condidate_ids = condidate_ids[:need_num]
                
                for t in range(self.total_step):
                    current_vehicles = self.vehicle_id_per_step[t]
                    if all(eid in current_vehicles for eid in condidate_ids):
                        intersect_steps.append(t)
                
                if len(intersect_steps) < need_steps:
                    intersect_steps = []
            
            ego_ids.extend(condidate_ids)
        
        elif need_num > 0:
            def backtrack(selected_ids, candidates, current_steps):
                if len(selected_ids) == need_num:
                    return current_steps
                
                if len(selected_ids) + len(candidates) < need_num:
                    return False
                
                for i, candidate_id in enumerate(candidates):
                    new_steps = {t for t in current_steps if candidate_id in self.vehicle_id_per_step[t]}
                    if len(new_steps) >= need_steps:
                        selected_ids.append(candidate_id)
                        result = backtrack(selected_ids, candidates[i + 1:], new_steps)
                        if result:
                            return result
                        
                        selected_ids.pop()
                
                return False
            
            valid_steps = {t for t, step_ids in enumerate(self.vehicle_id_per_step) if all(eid in step_ids for eid in ego_ids)}
            valid_ids = list(set(vid for t in valid_steps for vid in self.vehicle_id_per_step[t] if vid not in ego_ids))
            random.shuffle(valid_ids)
            
            random_ids = []
            intersect_steps = backtrack(random_ids, valid_ids, valid_steps)
            if not intersect_steps:
                print("Cannot find enough ego vehicles with sufficient common time steps")
                return
            
            ego_ids.extend(random_ids)
        
        else:
            intersect_steps = []
            for t in range(self.total_step):
                current_vehicles = self.vehicle_id_per_step[t]
                if all(eid in current_vehicles for eid in ego_ids):
                    intersect_steps.append(t)
    
            if len(intersect_steps) == 0:
                print("No common time steps where all selected ego vehicles exist")
                return
        
        print(f"selected ego ids for grid video: {ego_ids}")
        
        intersect_steps = sorted(intersect_steps)
        frame_steps = intersect_steps[::self.video_frame_interval]
        if len(frame_steps) == 0:
            frame_steps = [intersect_steps[0]]
        
        ego_color_map = {}
        for i, vid in enumerate(ego_ids):
            ego_color_map[vid] = ego_color_palette[i % len(ego_color_palette)]
        ego_labels = {vid: chr(ord('a') + i) for i, vid in enumerate(ego_ids[:5])}
        
        all_ego_positions = []
        for t in intersect_steps:
            current_vehicles = self.vehicle_id_per_step[t]
            current_states = np.array(self.vehicle_state_per_step[t])[..., self.vehicle_pos_dim + self.vehicle_h_dim].reshape(-1, 3)
            for eid in ego_ids:
                idx = current_vehicles.index(eid)
                all_ego_positions.append(current_states[idx, :2])
        
        all_ego_positions = np.array(all_ego_positions)
        x_min = float(np.min(all_ego_positions[:, 0]))
        x_max = float(np.max(all_ego_positions[:, 0]))
        y_min = float(np.min(all_ego_positions[:, 1]))
        y_max = float(np.max(all_ego_positions[:, 1]))
        
        all_polyline_states = np.concatenate([info["states"][..., self.polyline_pos_dim] for info in self.map.values()], axis=0)
        x_min_map = float(np.min(all_polyline_states[:, 0]))
        x_max_map = float(np.max(all_polyline_states[:, 0]))
        y_min_map = float(np.min(all_polyline_states[:, 1]))
        y_max_map = float(np.max(all_polyline_states[:, 1]))
        
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        half_length = (x_max - x_min) / 2.0
        half_width = (y_max - y_min) / 2.0
        
        ratio = 4.0 / 3.0
        if half_length / half_width > ratio:
            half_width = half_length / ratio
            if center_y - half_width < y_min_map and center_y + half_width < y_max_map:
                center_y = y_min_map + half_width
            elif center_y - half_width > y_min_map and center_y + half_width > y_max_map:
                center_y = y_max_map - half_width
            elif center_y - half_width < y_min_map and center_y + half_width > y_max_map:
                center_y = (y_min_map + y_max_map) / 2.0
        else:
            half_length = half_width * ratio
            if center_x - half_length < x_min_map and center_x + half_length < x_max_map:
                center_x = x_min_map + half_length
            elif center_x - half_length > x_min_map and center_x + half_length > x_max_map:
                center_x = x_max_map - half_length
            elif center_x - half_length < x_min_map and center_x + half_length > x_max_map:
                center_x = (x_min_map + x_max_map) / 2.0        
        
        half_length += self.ROI_radius * 1.1
        half_width += self.ROI_radius * 1.1
        
        x_min = center_x - half_length
        x_max = center_x + half_length
        y_min = center_y - half_width
        y_max = center_y + half_width
        
        static_map_img = self._render_static_overview_map(
            x_min, x_max, y_min, y_max,
        )
        
        traj_history = deque(maxlen=self.history_frame + 1)
        traj_history_mask = deque(maxlen=self.history_frame + 1)
        
        out = None

        for t in tqdm.trange(len(frame_steps), leave=False, desc="grid - video frame"):
            step = frame_steps[t]
            current_vehicles = self.vehicle_id_per_step[step]
            current_states = np.array(self.vehicle_state_per_step[step])[..., self.vehicle_pos_dim + self.vehicle_h_dim].reshape(-1, 3)
            
            frame_traj = np.zeros((self.num_vehicle, 2), dtype=float)
            frame_mask = np.zeros(self.num_vehicle, dtype=bool)
            for vid, state in zip(current_vehicles, current_states):
                v_index = self.vid_to_index[vid]
                frame_traj[v_index] = state[:2]
                frame_mask[v_index] = True
            
            traj_history.append(frame_traj)
            traj_history_mask.append(frame_mask)

            hist_traj = np.stack(traj_history, axis=0)
            hist_mask = np.stack(traj_history_mask, axis=0)
            valid_history_frame = hist_traj.shape[0] - 1
            
            fig = plt.figure(dpi=self.video_dpi * 2, facecolor='lightgray')
            fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)
            gs = gridspec.GridSpec(3, 3, figure=fig)
            
            fig.text(
                0.02, 0.98,
                f"{self.video_frame_interval}× Speed",
                ha='left', va='top',
                color='black',
                fontsize=10,
                zorder=100,
            )
            
            ax_overview = fig.add_subplot(gs[:2, :2])
            ax_ego_0 = fig.add_subplot(gs[0, 2])
            ax_ego_1 = fig.add_subplot(gs[1, 2])
            ax_ego_2 = fig.add_subplot(gs[2, 0])
            ax_ego_3 = fig.add_subplot(gs[2, 1])
            ax_ego_4 = fig.add_subplot(gs[2, 2])
            ego_axes = [ax_ego_0, ax_ego_1, ax_ego_2, ax_ego_3, ax_ego_4]
            
            if not showaxis:
                # ax_overview.set_xticks([])
                # ax_overview.set_yticks([])
                ax_overview.axis('off')
                for ax in ego_axes:
                    ax.set_xticks([])
                    ax.set_yticks([])
                    ax.set_facecolor('none')
            
            # for spine in ax_overview.spines.values():
            #     spine.set_visible(True)
            #     spine.set_edgecolor('silver')
            #     spine.set_linewidth(1.0)
            #     spine.set_linestyle('solid')
            
            ax_overview.set_xlim(x_min, x_max)
            ax_overview.set_ylim(y_min, y_max)
            ax_overview.set_aspect('auto')
            ax_overview.set_anchor('C')
            
            ax_overview.imshow(
                static_map_img,
                extent=[x_min, x_max, y_min, y_max],
                origin='upper',
                zorder=0,
                aspect='auto',
            )
            
            ego_mask_list = [vid in ego_ids for vid in current_vehicles]
            ego_mask_arr = np.array(ego_mask_list, dtype=bool)
            if np.any(~ego_mask_arr):
                bg_pos = current_states[~ego_mask_arr, :2]
                ax_overview.scatter(bg_pos[:, 0], bg_pos[:, 1], s=0.3, edgecolor="none", c="dodgerblue", zorder=5)
            if np.any(ego_mask_arr):
                ego_pos = current_states[ego_mask_arr, :2]
                ego_ids_in_step = np.array(current_vehicles, dtype=object)[ego_mask_arr]
                
                for eid, pos in zip(ego_ids_in_step, ego_pos):
                    ring_color = ego_color_map.get(eid, "red")
                    ax_overview.scatter(pos[0], pos[1], s=0.5, c=ring_color, edgecolor="none", zorder=10)
                    circle = plt.Circle(
                        (pos[0], pos[1]),
                        radius=self.ROI_radius,
                        fill=False,
                        edgecolor=ring_color,
                        linewidth=0.4,
                        zorder=9,
                    )
                    ax_overview.add_patch(circle)
                    
                    ax_overview.text(
                        pos[0] - self.ROI_radius, pos[1] + self.ROI_radius,
                        ego_labels[eid],
                        ha='center', va='center',
                        color='black',
                        fontsize=5,
                        zorder=11,
                    )
            
            polyline_color = {0: "white", 1: 'dimgray', 2: 'black', 3: 'gray', 4: 'white'}
            polyline_style = {0: "dashed", 1: 'solid', 2: 'solid', 3: 'dashed', 4: "dashed"}
            polyline_width = {0: 0.2, 1: 0.2, 2: 0.4, 3: 0.2, 4: 0.2}
            tl_polyline_color = {0: 'green', 1: 'yellow', 2: 'red', 3: 'gray'}
            
            color_step = self.color_gradient_interp_step + 1

            for i, center_vehicle in enumerate(ego_ids):
                if i >= len(ego_axes):
                    break
                ax = ego_axes[i]
                
                ax.text(
                    0.03, 0.97, 
                    ego_labels[center_vehicle],
                    transform=ax.transAxes,
                    ha='left', va='top',
                    color='black',
                    fontsize=8,
                    zorder=30,
                )
                
                dash_pattern = (4, 4)
                dash_period = float(sum(dash_pattern))
                dash_offset = t % dash_period

                for spine in ax.spines.values():
                    spine.set_visible(True)
                    spine.set_edgecolor(ego_color_map.get(center_vehicle, "black"))
                    spine.set_linewidth(0.5)
                    spine.set_linestyle((dash_offset, dash_pattern))
                
                center_position = current_states[current_vehicles.index(center_vehicle)][:2]
                
                ax.set_xlim(center_position[0] - self.ROI_radius, center_position[0] + self.ROI_radius)
                ax.set_ylim(center_position[1] - self.ROI_radius, center_position[1] + self.ROI_radius)
                
                valid_polylines = []
                valid_polyline_ids = []
                valid_polyline_types = []
                for polyline_id, polyline_info in self.map.items():
                    polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
                    valid_polyline_mask = np.linalg.norm(polyline_point - center_position[None, :], axis=-1) < self.ROI_radius
                    valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
                    valid_polyline_ids.extend([polyline_id] * (len(valid_polylines) - len(valid_polyline_ids)))
                    valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))

                # find valid vehicles
                valid_vehicle_mask = np.linalg.norm(center_position[None, :] - current_states[:, :2], axis=-1) < self.ROI_radius
                valid_vehicle_ids = np.array(current_vehicles, dtype=object)[valid_vehicle_mask]
                valid_vehicle_states = current_states[valid_vehicle_mask]
                valid_vehicle_static = np.array([self.vehicle_static_attribute[vid] for vid in valid_vehicle_ids])
                
                # draw polylines
                for pid, ptype, polyline in zip(valid_polyline_ids, valid_polyline_types, valid_polylines):
                    if pid in self.tl_id_per_step[step]:
                        color = tl_polyline_color[self.tl_type_per_step[step][self.tl_id_per_step[step].index(pid)]]
                    else:
                        color = polyline_color[ptype]
                    ax.plot(polyline[:, 0],
                            polyline[:, 1],
                            color=color,
                            linestyle=polyline_style[ptype],
                            linewidth=polyline_width[ptype],
                            zorder=0)
                
                # draw vehicles
                vehicle_boxes = get_rotated_box(valid_vehicle_states[:, 0], valid_vehicle_states[:, 1],
                                                valid_vehicle_static[:, 0], valid_vehicle_static[:, 1],
                                                valid_vehicle_states[:, 2])
                for vid, box in zip(valid_vehicle_ids, vehicle_boxes):
                    patch = plt.Polygon(box,
                                        facecolor=ego_color_map.get(vid, bg_vehicle_color),
                                        edgecolor='black' if vid in ego_ids else 'dimgray',
                                        linewidth=0.2,
                                        zorder=10)
                    ax.add_patch(patch)
                if plot_id:
                    for vid, vpos in zip(valid_vehicle_ids, valid_vehicle_states):
                        ax.text(vpos[0], vpos[1], str(vid),
                                ha='center', va='center',
                                color='white', fontsize=3, zorder=20)

                # draw history trajactories
                active_vehicle_ids = set(valid_vehicle_ids)
                for idx, vid in enumerate(self.all_vehicle_ids):
                    if vid not in active_vehicle_ids:
                        continue
                    
                    vehicle_history_traj = hist_traj[:, idx, :]
                    vehicle_history_mask = hist_mask[:, idx]
                    
                    grouped_traj, group_index = ScenarioViewer.group_sequence_with_mask(vehicle_history_traj, vehicle_history_mask)
                    for traj, traj_index in zip(grouped_traj, group_index):
                        step_from_first_frame = traj_index[0] + (self.history_frame - valid_history_frame)
                        for j in range(step_from_first_frame * color_step):
                            ax.plot(traj[:, 0],
                                    traj[:, 1],
                                    color=ego_color_map.get(vid, bg_vehicle_color),
                                    linewidth=1,
                                    alpha=self.alpha_list[j],
                                    zorder=1)
                        
                        interp_traj = np.zeros(((traj.shape[0] - 1) * color_step + 1, traj.shape[1]))
                        for j in range(interp_traj.shape[1]):
                            interp_traj[:, j] = np.interp(np.arange(interp_traj.shape[0]),
                                                          np.arange(traj.shape[0]) * color_step,
                                                          traj[:, j])
                        for j in range(len(interp_traj)):
                            ax.plot(interp_traj[j:, 0],
                                    interp_traj[j:, 1],
                                    color=ego_color_map.get(vid, bg_vehicle_color),
                                    linewidth=1,
                                    alpha=self.alpha_list[j + step_from_first_frame * color_step],
                                    zorder=1)
            
            canvas = FigureCanvas(fig)
            canvas.draw()
            width, height = fig.canvas.get_width_height()
            image = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
            image = cv2.cvtColor(image.reshape((height, width, 4))[..., :3], cv2.COLOR_BGR2RGB)
            plt.close(fig)

            if out is None:
                os.makedirs(os.path.dirname(os.path.abspath(f'{os.path.join(output_dir, video_desc)}.mp4')), exist_ok=True)
                video_name = f'{os.path.join(output_dir, video_desc)}_grid_{ego_ids}.mp4'
                out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*'mp4v'), self.video_fps, (image.shape[1], image.shape[0]))
            
            out.write(image)
        
        out.release()
        print(f"save grid video to {video_name}")
    
    def make_overview_video(self, video_desc: str, output_dir: str="./",
                            ego_id: int|str|list[int|str]|None=None,
                            video_frame_interval=5):
        if not self.scenario_loaded:
            raise RuntimeError(f"Cannot view partially loaded scenario: map_loaded - {self.map_loaded}, agent_loaded - {self.agent_loaded}")
        
        if ego_id is None:
            ego_set = set()
        else:
            if not isinstance(ego_id, list):
                ego_id = [ego_id]
            if not set(ego_id).issubset(self.all_vehicle_ids):
                print(f"remove unknown vehicle id {set(ego_id) - set(self.all_vehicle_ids)}")
            ego_set = set(ego_id) & set(self.all_vehicle_ids)
            if len(ego_set) == 0:
                print("Warning: all given ego_id are not in scenario, no ego will be highlighted.")
        
        all_points = np.concatenate([info["states"][..., self.polyline_pos_dim] for info in self.map.values()], axis=0)
        inf = np.min(all_points, axis=0)
        sup = np.max(all_points, axis=0)
        center = (inf + sup) / 2.0
        cx, cy = center[0], center[1]
        
        half_extent = (sup - inf) / 2.0
        R = float(max(half_extent) * 1.05)
        
        valid_polylines = []
        valid_polyline_types = []
        for pinfo in self.map.values():
            ptype = pinfo["type"]
            if ptype not in (1, 2, 3):
                continue
            pts = pinfo["states"][..., self.polyline_pos_dim]
            valid_polylines.append(pts)
            valid_polyline_types.append(ptype)
        
        color_map = {
            1: (169, 169, 169),  # dimgray
            2: (0, 0, 0),        # black
            3: (128, 128, 128),  # gray
        }
        thickness_map = {1: 1, 2: 1, 3: 1}  # px
        
        H = 4096
        W = 4096
        base_img = np.full((H, W, 3), 230, dtype=np.uint8)
        
        def world_to_pixel(x, y):
            px = int((x - (cx - R)) / (2 * R) * W)
            py = int((cy + R - y) / (2 * R) * H)
            return px, py
        
        for ptype, poly in zip(valid_polyline_types, valid_polylines):
            if poly.shape[0] < 2:
                continue
            
            # convert to pixel
            pts_px = [world_to_pixel(x, y) for x, y in poly]
            color = color_map[ptype]
            thick = thickness_map[ptype]

            if ptype == 3:
                # dashed line
                for i in range(len(pts_px) - 1):
                    if i % 2 == 0:
                        cv2.line(base_img, pts_px[i], pts_px[i+1], color, thick)
            else:
                # solid line
                for i in range(len(pts_px) - 1):
                    cv2.line(base_img, pts_px[i], pts_px[i+1], color, thick)
        
        os.makedirs(os.path.dirname(os.path.abspath(f"{os.path.join(output_dir, video_desc)}.mp4")), exist_ok=True)
        video_name = f"{os.path.join(output_dir, video_desc)}_overview.mp4"
        out = cv2.VideoWriter(video_name, cv2.VideoWriter_fourcc(*"mp4v"), self.video_fps, (W, H))
        
        for t in tqdm.trange(0, self.total_step, video_frame_interval,
                            leave=False, desc='overview - video frame'):
            frame = base_img.copy()
            
            # draw vehicles
            vehicle_ids = np.array(self.vehicle_id_per_step[t], dtype=object)
            vehicle_states = np.array(self.vehicle_state_per_step[t])[..., self.vehicle_pos_dim + self.vehicle_h_dim].reshape(-1, 3)
            
            if len(vehicle_states) > 0 and len(vehicle_ids) > 0:
                vehicle_xy = vehicle_states[:, :2]
                
                if len(ego_set) > 0:
                    ego_mask = np.isin(vehicle_ids, list(ego_set))
                    other_xy = vehicle_xy[~ego_mask]
                    ego_xy = vehicle_xy[ego_mask]
                else:
                    other_xy = vehicle_xy
                    ego_xy = None
                
                if other_xy is not None and other_xy.size > 0:
                    for (x, y) in other_xy:
                        px, py = world_to_pixel(x, y)
                        cv2.circle(frame, (px, py), 3, (255, 0, 0), -1)  # blue
                
                if ego_xy is not None and ego_xy.size > 0:
                    for (x, y) in ego_xy:
                        px, py = world_to_pixel(x, y)
                        cv2.circle(frame, (px, py), 3, (0, 0, 255), -1)  # red
            
            out.write(frame)
            
        out.release()
        print(f"save video to {video_name}")

    def _render_static_region_map(self, x_min, x_max, y_min, y_max, region_center):
        valid_polylines = []
        valid_polyline_types = []
        for polyline_info in self.map.values():
            polyline_point = polyline_info["states"][..., self.polyline_pos_dim]
            valid_polyline_mask = (np.linalg.norm(polyline_point - region_center[None, :], axis=-1) < self.ROI_radius)
            valid_polylines.extend(ScenarioViewer.group_sequence_with_mask(polyline_point, valid_polyline_mask)[0])
            valid_polyline_types.extend([polyline_info["type"]] * (len(valid_polylines) - len(valid_polyline_types)))
        
        fig = plt.figure(dpi=self.video_dpi, facecolor='lightgray')
        ax = fig.add_subplot([0, 0, 1, 1])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.axis('off')
        
        polyline_color = {0: "white", 1: 'dimgray', 2: 'black', 3: 'gray', 4: 'white'}
        polyline_style = {0: "dashed", 1: 'solid', 2: 'solid', 3: 'dashed', 4: "dashed"}
        polyline_width = {0: 0.5, 1: 0.5, 2: 0.8, 3: 0.5, 4: 0.5}
        
        for polyline_type, polyline in zip(valid_polyline_types, valid_polylines):
            if polyline_type not in (0, 1, 2, 3):
                continue
            ax.plot(polyline[:, 0], 
                     polyline[:, 1],
                     color=polyline_color[polyline_type],
                     linestyle=polyline_style[polyline_type],
                     linewidth=polyline_width[polyline_type],
                     zorder=0)
        
        canvas = FigureCanvas(fig)
        canvas.draw()
        width, height = fig.canvas.get_width_height()
        img = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape(height, width, 4)
        plt.close(fig)
        
        return img

    def _render_static_overview_map(self, x_min, x_max, y_min, y_max):
        world_w = x_max - x_min
        world_h = y_max - y_min
        if world_h <= 0:
            world_h = 1.0
        ratio = world_w / world_h
        
        base_h = 4.0
        fig_w = base_h * ratio
        fig_h = base_h
        
        fig = plt.figure(figsize=(fig_w, fig_h), dpi=self.video_dpi * 2, facecolor='lightgray')
        ax = fig.add_subplot([0, 0, 1, 1])
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_aspect('equal', adjustable='box')
        ax.axis('off')
        
        polyline_color = {0: "white", 1: 'dimgray', 2: 'black', 3: 'gray', 4: 'white'}
        polyline_style = {0: "dashed", 1: 'solid', 2: 'solid', 3: 'dashed', 4: "dashed"}
        polyline_width = {0: 0.05, 1: 0.05, 2: 0.1, 3: 0.05, 4: 0.05}
        
        for polyline_info in self.map.values():
            p_type = polyline_info["type"]
            if p_type not in (1, 2, 3):
                continue
            pts = polyline_info["states"][..., self.polyline_pos_dim]
            ax.plot(
                pts[:, 0], pts[:, 1],
                color=polyline_color[p_type],
                linestyle=polyline_style[p_type],
                linewidth=polyline_width[p_type],
            )
        
        canvas = FigureCanvas(fig)
        canvas.draw()
        width, height = fig.canvas.get_width_height()
        img = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8).reshape(height, width, 4)
        plt.close(fig)
        
        return img
    
    @staticmethod
    def quick_view_scenario(save_file:str, points:list[np.ndarray]=[], lines:list[list[np.ndarray]]=[], 
                            p_desc:list[str]=[], l_desc:list[str]=[], axis:Literal['off', 'on']='off', plot_drct:bool=False,
                            show: bool=False):
        color1 = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        color2 = color1[:]
        random.shuffle(color2)
        
        if len(points) > 0:
            pinf = np.min(np.array([np.min(p[..., :2], axis=0) for p in points]), axis=0)
            psup = np.max(np.array([np.max(p[..., :2], axis=0) for p in points]), axis=0)
        else:
            psup, pinf = np.array([-np.inf, -np.inf]), np.array([np.inf, np.inf])
            
        if len(lines) > 0:
            linf = np.min(np.array(([np.min(ll[..., :2], axis=0) for l in lines for ll in l if len(ll) > 0])), axis=0)
            lsup = np.max(np.array(([np.max(ll[..., :2], axis=0) for l in lines for ll in l if len(ll) > 0])), axis=0)
        else:
            lsup, linf = np.array([-np.inf, -np.inf]), np.array([np.inf, np.inf])
            
        sup = np.max(np.vstack((psup, lsup)), axis=0)
        inf = np.min(np.vstack((pinf, linf)), axis=0)
        
        lw_scale = 100 / max(sup - inf)
        
        plt.figure()
        plt.axis('equal')
        if axis == 'off':
            plt.axis('off')
        for i, p in enumerate(points):
            plt.scatter(p[..., 0], p[..., 1], c=color1[i], marker='x', label=p_desc[i] if i < len(p_desc) else None, lw=lw_scale, zorder=i)
        for i, l in enumerate(lines):
            for j, ll in enumerate(l):
                plt.plot(ll[..., 0], ll[..., 1], c=color2[i], label=l_desc[i] if i < len(l_desc) and j == 0 else None, lw=lw_scale, alpha=0.75, zorder=i-100)
                if plot_drct and len(ll) > 1:
                    arrow_interval = 5
                    if ll.shape[-1] > 2:
                        uv = np.hstack((np.cos(ll[..., 2:3]), np.sin(ll[..., 2:3])))
                    else:
                        uv = ll[1:] - ll[:-1]
                        uv = np.concatenate((uv, uv[-1:]), axis=0)
                        uv /= np.linalg.norm(uv[..., :2], axis=-1, keepdims=True)+1e-6
                    plt.quiver(ll[::arrow_interval, 0], ll[::arrow_interval, 1], 
                               uv[::arrow_interval, 0], uv[::arrow_interval, 1],
                               angles='xy', scale_units='xy', scale=0.5, 
                               width=0.004 * lw_scale,
                               headwidth=3, headlength=5, headaxislength=5,
                               color=color2[i],
                               zorder=i-100)

        if len(p_desc + l_desc) > 0:
            plt.legend()
        if show:
            plt.show()
        plt.savefig(save_file)
        print(f"Save quick-view scenario to {save_file}")
        plt.close()
        
def history1():
    # view waymo cnde nn input scenario (no route)
    view_dir = "/mnt/sdd/dhlin/Waymo-CityNDE"
    viewer = ScenarioViewer()
    scenario_file = os.listdir(view_dir)[::1000]
    random.shuffle(scenario_file)
    for file in tqdm.tqdm(scenario_file, desc="scenario"):
        scenario = pickle.load(open(os.path.join(view_dir, file), "rb"))
        id_per_step, state_per_step, static = dense2sparse(state=scenario["trajs"], mask=scenario["trajs_mask"], static_idx=7)
        polyline_info = extract_polyline_dict(scenario["map_polyline"], mask=scenario["map_polyline_mask"], state_dim=[0,1,2])
        viewer.load_map(map_dict=polyline_info)
        viewer.load_agent(agent_dict={"vehicle_id_per_step": id_per_step, "vehicle_state_per_step": state_per_step, "vehicle_static_attribute": static})
        
        viewer.make_agent_centric_video(video_desc=f"{file[:-4]}", 
                                        output_dir="/mnt/sdc/ubuntu/NDEdata/WaymoMotion/view_final/training",
                                        ego_id=0,
                                        showaxis=True)
    
def history2():
    # view nuplan cnde nn input scenario (with route)
    view_dir = "/mnt/sdd/dhlin/NuPlan-CityNDE"
    viewer = ScenarioViewer()
    scenario_file = os.listdir(view_dir)[::1000]
    random.shuffle(scenario_file)
    for file in tqdm.tqdm(scenario_file, desc="scenario"):
        scenario = pickle.load(open(os.path.join(view_dir, file), "rb"))
        id_per_step, state_per_step, static = dense2sparse(state=scenario["trajs"], mask=scenario["trajs_mask"], static_idx=7)
        polyline_info = extract_polyline_dict(scenario["map_polyline"], mask=np.ones(scenario["map_polyline"].shape[:-1], dtype=bool), state_dim=[0,1,2])
        viewer.load_map(map_dict=polyline_info)
        viewer.load_agent(agent_dict={"vehicle_id_per_step": id_per_step, "vehicle_state_per_step": state_per_step, "vehicle_static_attribute": static})
        
        viewer.make_agent_centric_video(video_desc=f"{file[:-4]}", 
                                        output_dir="/mnt/sdc/ubuntu/NDEdata/Nuplan/view_final/training",
                                        ego_id=0,
                                        showaxis=True)
        
def history3():
    # view agents without map
    view_dir = "/home/ubuntu/lishu/data/kargo"
    viewer = ScenarioViewer()
    scenario_file = os.listdir(view_dir)
    random.shuffle(scenario_file)
    for file in tqdm.tqdm(scenario_file, desc="scenario"):
        if not file.endswith("process.pkl"):
            continue
        scenario = pickle.load(open(os.path.join(view_dir, file), "rb"))
        id_per_step, state_per_step, static = dense2sparse(state=scenario["vehicle_states"], mask=scenario["vehicle_mask"], ids=scenario["vehicle_id"], static_idx=7)
        polyline_info = extract_polyline_dict(np.zeros((2, 7)), mask=np.ones(2), state_dim=[0,1,2])
        viewer.load_map(map_dict=polyline_info)
        viewer.load_agent(agent_dict={"vehicle_id_per_step": id_per_step, "vehicle_state_per_step": state_per_step, "vehicle_static_attribute": static})
        
        viewer.make_agent_centric_video(video_desc=f"{file[:-4]}", 
                                        output_dir="/home/ubuntu/lishu/data/kargo",
                                        ego_id='ego',
                                        showaxis=True)

def view_map():
    # map_path = "/home/ubuntu/lishu/data/boston/map_nuplan_boston_5type_rebuild.pkl"
    # map_path = "/home/ubuntu/lishu/data/ann_arbor_1km_new/cnde_map_ann_arbor_1km_rebuild.pkl"
    map_path = "/home/ubuntu/lishu/data/XiongAn/cnde_map_xiong_an_rebuild.pkl"
    viewer = ScenarioViewer()
    viewer.load_map(map_file=map_path)
    viewer.view_map(showaxis=True, plot_start_end=True, plot_mesh=True)

def main():
    parser = ArgumentParser()
    parser.add_argument("--ego_id", type=str, default="")
    parser.add_argument("--ego_num", type=int, default=20)
    parser.add_argument("--region_centric", action="store_true")
    parser.add_argument("--region_center", type=ast.literal_eval, default=None)
    parser.add_argument("--video_frame_interval", type=int, default=5)
    parser.add_argument("--color_mode", type=str, choices=["default", "av"], default="default")
    args, file_desc = parser.parse_known_args()

    if len(args.ego_id) > 0:
        args.ego_id = eval(args.ego_id)

    if len(file_desc) > 0:
        file_name = file_desc[0]
    else:
        file_name = '*'

    file_dir = Path('/home/ubuntu/lishu/CityNDE_/output/tmp_res')
    print(f'Find {len(list(file_dir.glob(file_name)))} scenarios: {list(file_dir.glob(file_name))}')
    for scenario_file in tqdm.tqdm(file_dir.glob(file_name)):
        viewer = ScenarioViewer(scenario_file=scenario_file)
        viewer.set_config(video_frame_interval=args.video_frame_interval)
        if args.color_mode == "av":
            viewer.set_config(vehicle_color_dict={id: 'maroon' for id in range(0,1000,20)})
        if not args.region_centric:
            if args.ego_id != '':
                viewer.make_agent_centric_video(video_desc=scenario_file.stem, 
                                                output_dir="/home/ubuntu/lishu/CityNDE_/output/tmp_videos", 
                                                plot_id=True, 
                                                plot_step=True, 
                                                ego_id=args.ego_id)
            else:
                viewer.make_agent_centric_video(video_desc=scenario_file.stem, 
                                                output_dir="/home/ubuntu/lishu/CityNDE_/output/tmp_videos", 
                                                plot_id=True, 
                                                plot_step=True, 
                                                ego_num=args.ego_num)
        else:
            if args.region_center is not None:
                args.region_center = np.array(args.region_center)
                assert args.region_center.size == 2, "region_center must be a 2D position"
            viewer.make_region_centric_video(video_desc=scenario_file.stem,
                                             plot_id=True,
                                             region_center=args.region_center,
                                             output_dir="/home/ubuntu/lishu/CityNDE_/output/tmp_videos")
            
if __name__ == "__main__":
    main()
    # view_map()
        
    