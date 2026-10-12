from __future__ import annotations
import numpy as np
from typing import Callable, Literal
from scipy.interpolate import interp1d
from sklearn.cluster import KMeans
import pickle
import random
import tqdm
import os, sys
import re
import shutil
import torch
import random
from pykalman import KalmanFilter
from cutils import unique_id, scenario_affine_transform, rotate_points_along_z
import matplotlib.pyplot as plt
from pyproj import Proj as pyProj, transform as pytransform

# sys.path.append("/home/ubuntu/lishuCityNDE_/csim")
# from scenario_viewer import ScenarioViewer
import shapely.geometry as geo


'''
1. traj & map separately
2. interpolate traj
3. filter traj, denoise
4. generate kmeans center
5. parse scenario to period
6. add map
7. identify egos & assign routes
8. transform one scenario to ego-centric scenarios
'''

def get_utm_projection(lat, lon):
    # Calculate the UTM zone number
    zone_number = int((lon + 180) / 6) + 1
    # Determine hemisphere based on latitude
    hemisphere = "north" if lat >= 0 else "south"
    # Define the UTM projection for the zone and hemisphere
    utm_proj = pyProj(
        proj="utm", zone=zone_number, datum="WGS84", south=(hemisphere == "south")
    )
    return utm_proj


def convert_lonlat_to_xy(lon_arr, lat_arr, utm_proj):
    # print("UTM projection is: ", utm_proj)
    # Convert latitude and longitude to UTM coordinates
    wgs84 = pyProj(proj="latlong", datum="WGS84")
    x, y = pytransform(wgs84, utm_proj, lon_arr, lat_arr)
    return np.array((x, y)).transpose()


def interpolate_along_time(time, pts: np.ndarray, mask: np.ndarray|None=None, step=0.1, target_time=None, axis=1) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    '''
    :param pts: points to interpolate, shape (..., D)
    :param axis: the time axis for pts
    :return: points (and mask)
    '''
    eps = 1e-6
    if target_time is None:
        interp_time = np.arange(time[0], time[-1]+eps, step)
    else:
        interp_time = np.array(target_time)
    itp = interp1d(x=time, y=pts, kind='linear', axis=axis, assume_sorted=True)
    if mask is not None:
        itp_m = interp1d(x=time, y=mask.astype(float), kind='linear', axis=axis, assume_sorted=True)
        return itp(interp_time), itp_m(interp_time) >= 1
    else:
        return itp(interp_time)

def interpolate_along_space(pts, mask: np.ndarray|torch.tensor|None=None, space_dim=[0,1], head_dim:int|None=None, tgt_num_pts:int|None=None, tgt_dist:float|None=None) -> np.ndarray|torch.tensor:
    '''
    :param pts: points to interpolate, shape (N, D), other shapes will be coverted to (N, D)
    :param tgt_num_pts: result of points, only one of tgt_num_pts and tgt_dist should be provided
    :param tgt_dist: result of point dist, may not be exact becase of fixed start and end point 
    '''
    assert (tgt_num_pts is not None) + (tgt_dist is not None) == 1, "Only one of tgt_num_pts and tgt_dist should be provided"
    if isinstance(pts, torch.Tensor):
        pts_np = pts.cpu().numpy()
    else:
        pts_np = pts
    pts_2d = pts_np.reshape(-1, pts_np.shape[-1])
    if pts_2d.shape[0] == 1:
        return pts
    if mask is not None:
        mask_1d = mask.reshape(-1)
        pts_2d = pts_2d[mask_1d]
    cum_len = np.cumsum(np.hstack(([0], np.linalg.norm((pts_2d[1:, space_dim] - pts_2d[:-1, space_dim]), axis=-1))))
    if tgt_num_pts is not None:
        tgt_cum_len = np.linspace(0, cum_len[-1], tgt_num_pts)
    elif tgt_dist is not None:
        tgt_num_pts = int(np.ceil(cum_len[-1] / tgt_dist)) + 1
        tgt_cum_len = np.linspace(0, cum_len[-1], tgt_num_pts)
    itp = interp1d(x=cum_len, y=pts_2d, kind='linear', axis=0, assume_sorted=True)
    res = itp(tgt_cum_len)
    
    if head_dim is not None:
        d_loc = np.diff(res[:, space_dim], axis=0)
        res[1:, head_dim] = np.arctan2(d_loc[:, 1], d_loc[:, 0])
        res[0, head_dim] = res[1, head_dim]
        
    if isinstance(pts, torch.Tensor):
        return torch.from_numpy(res).to(pts.device)
    else:
        return res
    

def apply_heading_inference(loc: np.ndarray, mask: np.ndarray, smooth: int=0, map_enhance:"BaseVectorMap"=None) ->  np.ndarray:
    '''
    Infer heading. The hyper-parameters of this funciton are highly relavant to dataset and time resolution of data. 
    :param loc: 2D/3D location of agents (N, T, 2/3)
    :return: inferred heading
    '''
    # infer heading with average of forward and backward
    org_loc = loc.copy()
    loc = loc[..., :2]
    loc = loc.reshape(-1, *loc.shape[-2:])
    mask = mask.reshape(*loc.shape[:-1])
    d_loc = loc[..., 1:, :] - loc[..., :-1, :]
    interp_mask = mask[..., 1:] & mask[..., :-1]
    interp_hd = np.atan2(d_loc[..., 1], d_loc[..., 0])
    fwd_hd, fwd_mask = np.concatenate((np.zeros((*interp_hd.shape[:-1], 1)), interp_hd), axis=-1), np.concatenate((np.zeros((*interp_mask.shape[:-1], 1)).astype(bool), interp_mask), axis=-1)
    bwd_hd, bwd_mask = np.concatenate((interp_hd, np.zeros((*interp_hd.shape[:-1], 1))), axis=-1), np.concatenate((interp_mask, np.zeros((*interp_mask.shape[:-1], 1)).astype(bool)), axis=-1)
    fwd_hd[~fwd_mask] = 0
    bwd_hd[~bwd_mask] = 0
    infer_hd = fwd_hd + bwd_hd
    infer_hd[fwd_mask & bwd_mask] = np.angle((np.exp(fwd_hd*1j) + np.exp(bwd_hd*1j)) / 2)[fwd_mask & bwd_mask]
    # identify valid inferring point
    d_infer_hd = np.abs(infer_hd[:, 1:] - infer_hd[:, :-1])
    d_pos = np.linalg.norm(d_loc, axis=-1)
    infer_mask = (d_pos > 1e-1) & ((d_pos > 4e-1) | (d_infer_hd < 6e-1)) & interp_mask
    infer_mask = np.concatenate((infer_mask, np.ones((*infer_mask.shape[:-1], 1)).astype(bool)), axis=-1)
    infer_mask[..., 1:] &= infer_mask[..., :-1]
    infer_hd[~infer_mask] = 0

    
    # filter heading for static points and smoothing other points
    # set first step of mask to True for infer_mask
    fully_static_obj = (~np.any(infer_mask, axis=-1)) & np.any(mask, axis=-1)
    for i in range(infer_hd.shape[0]):
        if not fully_static_obj[i] and infer_mask[i, np.argmax(mask[i])] == False:
            infer_hd[i, np.argmax(mask[i])] = infer_hd[i, np.argmax(infer_mask[i])]
            infer_mask[i, np.argmax(mask[i])] = True
    
    # Kalman
    for i in range(infer_hd.shape[0]):
        infer_hd[i][infer_mask[i]] = np.unwrap(infer_hd[i][infer_mask[i]])
        
    infer_hd = apply_kalman_filter(states=infer_hd[..., None], mask=infer_mask, infer_mask=True,
                                   order_0_dim=[0], ob_noise=[5e-2], trans_rate=4e-2).squeeze(-1)       # 4e-1 ≈ 28.6°
    infer_hd = (infer_hd + np.pi) % (2 * np.pi) - np.pi
    infer_hd[~mask] = 0
            
    # deal with fully static agent 
    if np.any(fully_static_obj) and map_enhance == None:
        print(f"Warning: set {np.sum(fully_static_obj):d} static heading to 0 when inferring heading.")
    elif np.any(fully_static_obj):
        static_obj_valid_step = np.argmax(mask[fully_static_obj], axis=-1)
        static_loc = org_loc[fully_static_obj][np.arange(len(static_obj_valid_step)).astype(int), static_obj_valid_step, :]
        static_loc = map_enhance.normalize(static_loc, dim=[0,1])
        heading = [map_enhance.project_to_polyline(loc, map_enhance.get_current_lane(loc)[0], ret_dist=False)[-1] for loc in static_loc]
        for i, idx in enumerate(np.where(fully_static_obj)[0]):
            infer_hd[idx][mask[idx]] = heading[i]
        
    return infer_hd

def apply_kmeans_cluster(files: list[str], extract_fn:Callable, query_step=80, n_clusters=64, density=20):
    '''
    :param extract_fn: extract required data from file and convert to traj (..., N, T, D(position, heading)) and mask (..., N, T)
    :param density: timesteps to extract from data
    '''
    target_all = []
    for f in tqdm.tqdm(files, desc="loading"):
        with open(f, "rb") as ff:
            data = pickle.load(ff)
        trajs, mask = extract_fn(data)
        start_range = trajs.shape[-2] - query_step
        if start_range < density:
            continue
        starts = np.array(random.sample(range(start_range), k=density)).astype(np.intp)
        d = trajs[..., :, starts+query_step, :-1] - trajs[..., :, starts, :-1]
        hd = trajs[..., :, starts, -1]
        m = mask[..., :, starts+query_step] & mask[..., :, starts]
        d = d[m]
        hd = hd[m]
        d = rotate_points_along_z(d[:, None, :], -hd).reshape(-1, 2)
        target_all.append(d)
    
    target_all = np.concatenate(target_all, axis=0)
    kmeans = KMeans(n_clusters=n_clusters)
    print("applying kmeans")
    kmeans.fit(target_all)
    
    return np.array(kmeans.cluster_centers_)

def filter_objects(states:np.ndarray, mask:np.ndarray, obj_type=None, valid_type=None, min_living_step:int=1, min_moving_dist:float=2, pos_dim:list=[0,1]):
    if obj_type is not None and valid_type is not None:
        type_mask = np.isin(obj_type, valid_type)
        states, mask = states[type_mask], mask[type_mask]
    
    living_step_mask = np.sum(mask, axis=-1) > min_living_step
    states, mask = states[living_step_mask], mask[living_step_mask]
    n_obj, n_step = mask.shape

    first_valid_time = np.argmax(mask, axis=-1)
    last_valid_time = n_step - 1 - np.argmax(mask[:, ::-1], axis=-1)
    first_valid_pos = states[np.arange(n_obj), first_valid_time][..., pos_dim]
    last_valid_pos = states[np.arange(n_obj), last_valid_time][..., pos_dim]
    moving_dist_mask = np.linalg.norm(last_valid_pos - first_valid_pos, axis=-1) > min_moving_dist
    states, mask = states[moving_dist_mask], mask[moving_dist_mask]
    return states, mask


def apply_kalman_filter(states:np.ndarray, mask:np.ndarray, step=0.1, order_0_dim=[0,1], order_1_dim=[], order_2_dim=[], use_em=True, infer_mask=False, *, ob_noise, trans_rate, default:Literal['hold', 'static']='static') -> np.ndarray:
    '''
    Apply Kalman filter to states, return filtered states (mask not changed)
    :param state: [(N), T, D]
    :param mask: [(N), T]
    :param step: time step interval
    :param order_0_dim, order_1_dim, order_2_dim: dimension of states before filter, support 3 order of states currently (eg. pos, vel, acc)
    :param ob_noise: level to trust different orders of state, means σ for each step
    :param trans_rate: rate of the highest order of state to change, 
        (e.g. given acc -> σ_jerk = trans_rate m/s^2 / step, given vel -> σ_acc = trans_rate m/s / step)
    '''
    assert len(order_0_dim) - len(order_1_dim) == 0 or len(order_1_dim) == 0, "Unmatched dimension of input dims for Kalman filter"
    assert len(order_1_dim) - len(order_2_dim) == 0 or len(order_2_dim) == 0, "Unmatched dimension of input dims for Kalman filter"
    assert len(order_0_dim) == len(ob_noise), "Noise dimension not consistent with states for filter"
    single_dim_len = len(order_0_dim)
    valid_state_dim = order_0_dim + order_1_dim + order_2_dim
    if states.ndim == 2:
        states_new, mask = states[None], mask[None]
    else:
        states_new = states.copy()
        
    # extend to one higher order for input observation and define Kalman arguments
    transition_matrix = np.eye(len(valid_state_dim)+single_dim_len) + np.diag([step]*len(valid_state_dim), k=single_dim_len)
    if default == 'static':
        transition_matrix[range(-single_dim_len, 0), range(-single_dim_len, 0)] = 0.2
    states_valid = states_new[..., valid_state_dim]
    states_valid_with_mask = np.ma.array(states_valid, mask=~mask[..., None].repeat(states_valid.shape[-1], axis=-1))
    first_valid = np.argmax(mask, axis=1)
    obseravation_matrix = np.eye(transition_matrix.shape[-1])[:-single_dim_len]
    observation_covariance = np.eye(obseravation_matrix.shape[0]) * np.array(ob_noise).repeat(single_dim_len)
    transition_covariance= np.zeros_like(transition_matrix)
    transition_covariance[range(-single_dim_len, 0), range(-single_dim_len, 0)] = trans_rate
    initial_covariance = transition_covariance.copy()
    initial_covariance[:-single_dim_len, :-single_dim_len] = observation_covariance.copy()

    # filter for each object
    for i in range(states_valid.shape[0]):
        if first_valid[i] + 1 >= states_valid.shape[1] or not np.any(mask[i]):
            continue
        kf = KalmanFilter(transition_matrices=transition_matrix,
                          observation_matrices=obseravation_matrix,
                          transition_covariance=transition_covariance,
                          observation_covariance=observation_covariance,
                          initial_state_mean=np.hstack((states_valid[i, first_valid[i]], [0]*single_dim_len)),
                          initial_state_covariance=initial_covariance,
                          em_vars=['transition_covariance', 'observation_covariance', 'initial_state_mean', 'initial_state_covariance'] if use_em else None)
        smooth_state = kf.smooth(states_valid_with_mask[i, first_valid[i]:])[0][..., :-single_dim_len]
        states_new[i][first_valid[i]:, valid_state_dim] = smooth_state
    if not infer_mask:
        states_new[~mask] = 0
    return states_new.reshape(states.shape)

def transform_to_ego_center_with_route_map(states: np.ndarray, mask: np.ndarray, map:"RouteVectorMap", interval, scenario_len=91, scenario_radius=80, core_step_idx=10, ego_mask:np.ndarray|None=None,
                                           *, state_pos_dim, map_pos_dim, state_head_dim, map_head_dim, state_rotation_pairs, map_rotation_pairs):
    ret_scenarios = []
    total_t = states.shape[-2]
    start = np.random.randint(0, interval)
    states = map.normalize(states, dim=state_pos_dim)
    states[~mask] = 0
    for start in range(np.random.randint(0, interval), total_t - scenario_len, interval):
        period = states[:, start:start+scenario_len, :]
        period_mask = mask[:, start:start+scenario_len]
        # Identify ego, if no ego, continue
        valid_agent = period_mask[..., core_step_idx]
        period, period_mask = period[valid_agent], period_mask[valid_agent]
        
        ego_cand = np.all(period_mask, axis=-1)
        period_dynamic_mask = np.linalg.norm(period[:, -1][..., state_pos_dim] - period[:, 0][..., state_pos_dim], axis=-1) > 1
        ego_cand &= period_dynamic_mask
        if ego_mask is not None:
            ego_cand &= ego_mask
        if not np.any(ego_cand):
            continue

        scenario_min = np.min(period[period_mask][..., state_pos_dim], axis=0)
        scenario_max = np.max(period[period_mask][..., state_pos_dim], axis=0)
        
        scenario_center = (scenario_min + scenario_max) / 2
        all_scenario_radius = np.linalg.norm(scenario_max - scenario_min) / 2 + scenario_radius
        polyline_id = map.get_surrounding_polylines(scenario_center, all_scenario_radius)
        scenario_polyline_info = map.formatted_state(polyline_id)
        polyline_center, polyline_states, polyline_mask = scenario_polyline_info["polyline_center"], scenario_polyline_info["polyline_states"], scenario_polyline_info["polyline_mask"]
        
        agent_centers = period[:, core_step_idx, state_pos_dim]
        
        ego_idx = np.where(ego_cand)[0]
        for idx in ego_idx:
            ego_period = np.roll(period, shift=-idx, axis=0)
            ego_period_mask = np.roll(period_mask, shift=-idx, axis=0)
            ego_centers = np.roll(agent_centers, shift=-idx, axis=0)
            
            core_pos = ego_period[0][core_step_idx, state_pos_dim].copy()
            core_heading = ego_period[0][core_step_idx, state_head_dim].copy()

            valid_agent = np.linalg.norm(ego_centers - ego_centers[0:1], axis=-1) < scenario_radius
            valid_map = np.linalg.norm(polyline_center - ego_centers[0:1], axis=-1) < scenario_radius
            route = map.get_route_based_on_traj(ego_period[0, 10::10][..., [state_pos_dim]])
            # map.check_route(file_name=unique_id(), route=route, ref_lines=[[ego_period[0]]], ref_desc=["ego"])
            route_info = map.formatted_state(route)
            route_polyline, route_mask = route_info["polyline_states"], route_info["polyline_mask"]

            rotated_states, rotated_map, rotated_route = scenario_affine_transform(-core_pos, -core_heading, 
                                                                                   (ego_period[valid_agent], state_head_dim, state_rotation_pairs, [state_pos_dim]),
                                                                                   (polyline_states[valid_map], map_head_dim, map_rotation_pairs, [map_pos_dim]),
                                                                                   (route_polyline, map_head_dim, map_rotation_pairs, [map_pos_dim]))
            
            rotated_states[~ego_period_mask[valid_agent]] = 0
            rotated_map[~polyline_mask[valid_map]] = 0
            rotated_route[~route_mask] = 0
            
            scenario = {"ego_id_period": (start, start+interval, idx),
                        "center_pos_heading": (core_pos, core_heading),
                        "vehicle_states": rotated_states,
                        "vehicle_mask": ego_period_mask[valid_agent],
                        "polyline_states": rotated_map,
                        "polyline_mask": polyline_mask[valid_map],
                        "route_polyline_states": rotated_route,
                        "route_polyline_mask": route_mask}
            
            ret_scenarios.append(scenario)
            
    return ret_scenarios

def merge_scenario_agents_to_1(scenarios: list[dict], pos_dim = [0, 1]) -> dict:
    vehicle_id, vehicle_states, vehicle_mask = [], [], []
    initialized_area: list[geo.Polygon] = []
    
    for sce in scenarios:
        if len(sce.get("vehicle_id", [])) == 0:
            continue
        mask = sce.get("vehicle_mask", np.ones(sce["vehicle_states"].shape[:-1]).astype(bool))
        valid_v = np.any(mask, axis=-1)
        if not np.any(valid_v):
            continue
        states = sce["vehicle_states"][valid_v]
        mask = mask[valid_v]
        valid_state_pos = states[mask][..., pos_dim]
        x_min, x_max = np.min(valid_state_pos[..., 0]), np.max(valid_state_pos[..., 0])
        y_min, y_max = np.min(valid_state_pos[..., 1]), np.max(valid_state_pos[..., 1])
        new_area = geo.box(x_min, y_min, x_max, y_max)
        for area in initialized_area:
            if area.intersects(new_area):
                break
        else:
            initialized_area.append(new_area)
            vehicle_id.extend(list(range(len(vehicle_id), len(vehicle_id)+len(valid_v))))
            vehicle_states.append(states)
            vehicle_mask.append(mask)
    
    if len(vehicle_id) == 0:
        raise RuntimeError("No vehicles found in all scenarios to merge")
    
    return {"vehicle_id": vehicle_id,
            "vehicle_states": np.concatenate(vehicle_states, axis=0),
            "vehicle_mask": np.concatenate(vehicle_mask, axis=0)}
    
def read_map_file(map_file: str):
    with open(map_file, "rb") as m:
        map_info = pickle.load(m)
    if 'map' in map_info.keys():
        polyline_info = map_info['map']['polyline']
    else:
        polyline_info = map_info['polyline']
    return map_info, polyline_info

def split_files(dir, subdir1, subdir2, ratio=0.8):
    os.makedirs(subdir1, exist_ok=True)
    os.makedirs(subdir2, exist_ok=True)
    
    all_files = [f for f in os.listdir(dir) if os.path.isfile(os.path.join(dir, f))]
    
    if not all_files:
        return

    total_files = len(all_files)
    split_index = int(total_files * ratio)
    random.shuffle(all_files)

    subfile1 = all_files[:split_index]
    subfile2 = all_files[split_index:]

    for file in tqdm.tqdm(subfile1, desc="dir1"):
        shutil.move(os.path.join(dir, file), os.path.join(subdir1, file))

    for file in tqdm.tqdm(subfile2, desc="dir2"):
        shutil.move(os.path.join(dir, file), os.path.join(subdir2, file))

    print(f"Spliting result: {len(subfile1)} files in {subdir1}, {len(subfile2)} files in {subdir2}")

def assign_tl_phase(tl_polylines: dict, logic:Literal['default', 'start_direction']='default'):
    '''
    assign tl phase to tl polylines based on the logic
    :param tl_polylines: dict of {tl_polyline_id: tl_polyline_info}
    :return: dict of {tl_polyline_id: tl_phase}
    '''
    tl_polylines_id = list(tl_polylines.keys())
    intersection_start_lane = []
    for lane_id, lane_info in tl_polylines.items():
        prev_lanes = lane_info['prev_lanes_id']
        if prev_lanes is None or prev_lanes == []:
            intersection_start_lane.append(lane_id)
            continue
        if prev_lanes[0] in tl_polylines_id:
            continue
        intersection_start_lane.append(lane_id)
    
    intersection_sequences = []
    for lane_id in intersection_start_lane:
        lane_seq = [lane_id]
        while True:
            if tl_polylines[lane_seq[-1]]['next_lanes_id'] is None or tl_polylines[lane_seq[-1]]['next_lanes_id'] == []:
                break
            if tl_polylines[lane_seq[-1]]['next_lanes_id'][0] not in tl_polylines_id:
                break
            if tl_polylines[lane_seq[-1]]['next_lanes_id'][0] in lane_seq:
                break
            lane_seq.append(tl_polylines[lane_seq[-1]]['next_lanes_id'][0])
        intersection_sequences.append(lane_seq)
        
    tl_direction = {}
    for lane_seq in intersection_sequences:
        start_id, end_id = lane_seq[0], lane_seq[-1]
        
        start_heading = tl_polylines[start_id]['states'][0, -1]
        end_heading = tl_polylines[end_id]['states'][-1, -1]
        delta_heading = (end_heading - start_heading + np.pi) % (np.pi * 2) - np.pi
        start_heading = (start_heading + np.pi) % (np.pi * 2) - np.pi
        
        if logic == 'default':
            if -np.pi/4 <= start_heading <= np.pi/4 or start_heading >= 3*np.pi/4 or start_heading <= -3*np.pi/4:
                p_drct = "ew"
            else:
                p_drct = "ns"
            if -np.pi/4 <= delta_heading <= np.pi/4:
                p_drct += "_s"
            elif np.pi/4 <= delta_heading <= 3*np.pi/4:
                p_drct += "_l"
            elif -3*np.pi/4 <= delta_heading <= -np.pi/4:
                p_drct += "_r"
            else:
                p_drct += "_l"
        elif logic == 'start_direction':
            if -np.pi/4 <= start_heading <= np.pi/4:
                p_drct = "e"
            elif start_heading >= 3*np.pi/4 or start_heading <= -3*np.pi/4:
                p_drct = "w"
            elif np.pi/4 <= start_heading <= 3*np.pi/4:
                p_drct = "n"
            elif -3*np.pi/4 <= start_heading <= -np.pi/4:
                p_drct = "s"
            else:
                raise ValueError(f"Invalid start heading: {start_heading} (supposed to be in [-pi, pi])")
            if -3*np.pi/4 <= delta_heading <= -np.pi/4:
                p_drct += "_r"
        tl_direction.update({lane_id: p_drct for lane_id in lane_seq})
    
    if logic == 'default':
        tl_dirction_2_phase = {
            "ew_s": "grrrrrrr",
            "ew_l": "rrgrrrrr",
            "ns_s": "rrrrgrrr",
            "ns_l": "rrrrrrgr",
            "ew_r": "g",
            "ns_r": "g",
        }
    elif logic == 'start_direction':
        tl_dirction_2_phase = {
            "e": "grrrrrrr",
            "n": "rrgrrrrr",
            "w": "rrrrgrrr",
            "s": "rrrrrrgr",
            "e_r": "g",
            "w_r": "g",
            "s_r": "g",
            "n_r": "g",
        }
    else:
        raise ValueError(f"Unsupported tl phase logic: {logic}")
        
    return {tl_id: tl_dirction_2_phase[direction] for tl_id, direction in tl_direction.items()}

if __name__ == "__main__":
    split_files(dir="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part",
                subdir1="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part/train", 
                subdir2="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part/eval",
                ratio=0.9)
    
    split_files(dir="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part/eval",
                subdir1="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part/eval", 
                subdir2="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic_part/test",
                ratio=0.5)
    
    split_files(dir="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic",
                subdir1="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic/train", 
                subdir2="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic/eval",
                ratio=0.9)
    
    split_files(dir="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic/eval",
                subdir1="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic/eval", 
                subdir2="/mnt/sdc/ubuntu/NDEdata/tianjin/complete_dynamic/test",
                ratio=0.5)