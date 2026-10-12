import numpy as np
import torch
from typing import Iterable
from functools import wraps
import uuid
import time
import random

def unique_id():
    return str(uuid.uuid4())

def setup_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)

def onehot_time_embedding(shape_prefix:Iterable[int], time_axis:int=-1) -> np.ndarray:
    if time_axis < 0:
        time_axis = len(shape_prefix) + time_axis
        assert time_axis >= 0, f"Axis {time_axis - len(shape_prefix)} exceeded the dimiension {len(shape_prefix)}"
    I = np.eye(shape_prefix[time_axis])
    for dim, shape in enumerate(shape_prefix):
        if dim < time_axis:
            I = I[..., None, :, :].repeat(shape, axis=-3)
        elif dim > time_axis:
            I = I[..., None, :].repeat(shape, axis=-2)
    return I

def rotate_points_along_z(points, angle):
    """
    Args:
        points: (B, N, 3 + C)
        angle: (B), angle along z-axis, angle increases x ==> y
    Returns:
    """
    def check_numpy_to_torch(x):
        if isinstance(x, np.ndarray):
            return torch.from_numpy(x).float(), True
        if isinstance(x, float):
            return torch.tensor(x).float(), True
        return x, False

    ret_shape = points.shape
    points, is_numpy = check_numpy_to_torch(points)
    angle, _ = check_numpy_to_torch(angle)
    while points.ndim < 3:
        points = points[None, ]
    while angle.ndim < 1:
        angle = angle[None, ]

    cosa = torch.cos(angle)
    sina = torch.sin(angle)
    zeros = angle.new_zeros(points.shape[0])
    if points.shape[-1] == 2:
        rot_matrix = torch.stack((
            cosa, sina,
            -sina, cosa
        ), dim=1).view(-1, 2, 2).float()
        points_rot = torch.matmul(points, rot_matrix).reshape(*ret_shape)
    else:
        ones = angle.new_ones(points.shape[0])
        rot_matrix = torch.stack((
            cosa, sina, zeros,
            -sina, cosa, zeros,
            zeros, zeros, ones
        ), dim=1).view(-1, 3, 3).float()
        points_rot = torch.matmul(points[:, :, 0:3], rot_matrix)
        points_rot = torch.cat((points_rot, points[:, :, 3:]), dim=-1).reshape(*ret_shape)
    return points_rot.numpy() if is_numpy else points_rot

def scenario_affine_transform(offset:np.ndarray|torch.Tensor, angle:np.ndarray|torch.Tensor, core_element, *scenario_elements, rotation_first=False):
    '''
    offset:((B), d_c)
    angle: ((B), )
    element: Tuple(states: np.ndarray|torch.Tensor ((B), N, T, D), 
                   head_dim: int or None, 
                   rotation_pairs: list[list[int, int]] or [], 
                   offset_pairs: list[list[int, int]] or [])
    '''
    if isinstance(angle, float):
        if isinstance(offset, np.ndarray):
            angle = np.array(angle)
        elif isinstance(offset, torch.Tensor):
            angle = torch.tensor(angle).to(offset.device)
    offset, angle = offset[..., None, None, :], angle[..., None, None]
    B = offset.shape[0] if offset.ndim == 2 else 1

    ret_elements = []
    for states, head_dim, rotation_pairs, offset_pairs in (core_element, *scenario_elements):
        if head_dim is not None:
            states[..., head_dim] += angle
        if not rotation_first:
            if len(offset_pairs) > 0:
                for pair in offset_pairs:
                    states[..., pair] += offset
            if len(rotation_pairs) > 0:
                for pair in rotation_pairs:
                    states[..., pair] = rotate_points_along_z(states[..., pair].reshape(B, -1, 2), angle.squeeze()).reshape(*states[..., pair].shape)
        else:
            if len(rotation_pairs) > 0:
                for pair in rotation_pairs:
                    states[..., pair] = rotate_points_along_z(states[..., pair].reshape(B, -1, 2), angle.squeeze()).reshape(*states[..., pair].shape)
            if len(offset_pairs) > 0:
                for pair in offset_pairs:
                    states[..., pair] += offset
        ret_elements.append(states)
    
    return ret_elements

def tensor_to_hashable(tensor: torch.Tensor | np.ndarray):
    return tuple(tensor.reshape(-1).tolist())

def hashable_input(func):
    @wraps(func)
    def unhashable_inp_func(*args, **kwargs):
        hashable_args = tuple(
            tensor_to_hashable(arg) if isinstance(arg, torch.Tensor) or isinstance(arg, np.ndarray) else arg
            for arg in args
        )
        hashable_kwargs = {
            k: tensor_to_hashable(v) if isinstance(v, torch.Tensor) or isinstance(v, np.ndarray) else v
            for k, v in kwargs.items()
        }
        return func(*hashable_args, **hashable_kwargs)
    
    return unhashable_inp_func


def debug_call(func):
    @wraps(func)
    def print_time(*args, **kwargs):
        uid = str(uuid.uuid4())[:10]
        start_t = time.time()
        print(f"{func}(id: {uid}) called at time {start_t:.4f}")
        ret_val = func(*args, **kwargs)
        end_t = time.time()
        print(f"{func}(id: {uid}) returned at time {end_t:.4f}, excecution time {end_t - start_t:.4f}s")
        return ret_val
    
    return print_time

def rec_time(func):
    @wraps(func)
    def print_time(*args, **kwargs):
        start_t = time.time()
        ret_val = func(*args, **kwargs)
        print(f"{func} time cost: {time.time() - start_t:.6f}s")
        return ret_val
    
    return print_time

def get_rotated_box(x_center, y_center, length, width, heading):
    centroids = np.column_stack([x_center, y_center])

    l = length / 2
    w = width / 2
    c = np.cos(heading)
    s = np.sin(heading)

    lc = l * c
    ls = l * s
    wc = w * c
    ws = w * s

    rotated_bbox_vertices = np.empty((centroids.shape[0], 4, 2))

    # front-right
    rotated_bbox_vertices[:, 0, 0] = lc - ws
    rotated_bbox_vertices[:, 0, 1] = ls + wc
    # rear-right
    rotated_bbox_vertices[:, 1, 0] = -lc - ws
    rotated_bbox_vertices[:, 1, 1] = -ls + wc
    # rear-left
    rotated_bbox_vertices[:, 2, 0] = -lc + ws
    rotated_bbox_vertices[:, 2, 1] = -ls - wc
    # front-left
    rotated_bbox_vertices[:, 3, 0] = lc + ws
    rotated_bbox_vertices[:, 3, 1] = ls - wc

    rotated_bbox_vertices += np.expand_dims(centroids, axis=1)

    return rotated_bbox_vertices

def interpolate(pts, num_pts=None, max_dist=None) -> np.ndarray:
    """
    Interpolate points either based on cumulative distances from the first one (`num_pts`)
    or by adding extra points until neighboring points are within `max_dist` of each other.

    In particular, `num_pts` will interpolate using a variable step such that we always get
    the requested number of points.

    Args:
        pts (np.ndarray): XYZ(H) coords.
        num_pts (int, optional): Desired number of total points.
        max_dist (float, optional): Maximum distance between points of the polyline.

    Note:
        Only one of `num_pts` or `max_dist` can be specified.

    Returns:
        np.ndarray: The new interpolated coordinates.
    """
    if num_pts is not None and max_dist is not None:
        raise ValueError("Only one of num_pts or max_dist can be used!")

    if pts.ndim != 2:
        raise ValueError("pts is expected to be 2 dimensional")

    # 3 because XYZ (heading does not count as a positional distance).
    pos_dim: int = min(pts.shape[-1], 3)

    if num_pts is not None:
        assert num_pts > 1, f"num_pts must be at least 2, but got {num_pts}"

        if pts.shape[0] == num_pts:
            return pts

        cum_dist: np.ndarray = np.cumsum(
            np.linalg.norm(np.diff(pts[..., :pos_dim], axis=0), axis=-1)
        )
        cum_dist = np.insert(cum_dist, 0, 0)

        steps: np.ndarray = np.linspace(cum_dist[0], cum_dist[-1], num_pts)
        xyz_inter: np.ndarray = np.empty((num_pts, pts.shape[-1]), dtype=pts.dtype)
        for i in range(pos_dim):
            xyz_inter[:, i] = np.interp(steps, xp=cum_dist, fp=pts[:, i])

        return xyz_inter
    
    elif max_dist is not None:
        unwrapped_pts: np.ndarray = pts

        segments = unwrapped_pts[..., 1:, :] - unwrapped_pts[..., :-1, :]
        seg_lens = np.linalg.norm(segments[..., :pos_dim], axis=-1)
        new_pts = [unwrapped_pts[..., 0:1, :]]
        for i in range(segments.shape[-2]):
            num_extra_points = seg_lens[..., i] // max_dist
            if num_extra_points > 0:
                step_vec = segments[..., i, :] / (num_extra_points + 1)
                new_pts.append(
                    unwrapped_pts[..., i, np.newaxis, :]
                    + step_vec[..., np.newaxis, :]
                    * np.arange(1, num_extra_points + 1)[:, np.newaxis]
                )

            new_pts.append(unwrapped_pts[..., i + 1 : i + 2, :])

        new_pts = np.concatenate(new_pts, axis=-2)

        return new_pts
    
    
def sparse2dense(id_per_step, state_per_step, static:dict|None=None) -> tuple[list[int|str], np.ndarray, np.ndarray]:
    '''
    :return: id_list, state, mask
    '''
    total_step = len(id_per_step)
    flat_ids = [id for id_list in id_per_step for id in id_list]
    ids:list[int|str] = list(set(flat_ids))
    state_dim = state_per_step[0].shape[-1]
    static_dim = 0 if static is None else static[ids[0]].shape[-1]
    if static is not None:
        dense_static = [static[id] for id in ids]
    index = {ids[i]:i for i in range(len(ids))}
    dense_state = np.zeros((len(ids), total_step, state_dim+static_dim))
    mask = np.zeros((len(ids), total_step), dtype=bool)
    
    for step, (agent, states) in enumerate(zip(id_per_step, state_per_step)):
        for id, state in zip(agent, states):
            dense_state[index[id], step, :state_dim] = state
            if static_dim > 0:
                dense_state[index[id], step, -static_dim:] = dense_static[index[id]]
            mask[index[id], step] = True
            
    return ids, dense_state, mask


def dense2sparse(state, mask, ids=None, static_idx:int|None=None):
    '''
    :return: id_per_step, state_per_step, static (if static_idx is specified)
    '''
    total_step = state.shape[1]
    if ids is None:
        ids = list(range(state.shape[0]))
    if static_idx is not None:
        static = {}
        no_static_state, static_state = state[..., :static_idx], state[..., static_idx:]
    else:
        no_static_state = state
    id_per_step, state_per_step = [[] for __ in range(total_step)], [[] for __ in range(total_step)]
    for t in range(total_step):
        for i in range(len(ids)):
            if mask[i, t]:
                id_per_step[t].append(ids[i])
                state_per_step[t].append(no_static_state[i:i+1, t])
                if static_idx is not None:
                    if ids[i] not in static.keys():
                        static[ids[i]] = static_state[i, t]
        
        state_per_step[t] = np.concatenate(state_per_step[t], axis=0) if len(state_per_step[t]) > 0 else np.empty((0, static_idx))
    
    if static_idx is None:
        return id_per_step, state_per_step
    else:
        return id_per_step, state_per_step, static
    
def extract_polyline_dict(polyline: np.ndarray, mask: np.ndarray, ids=None, state_dim=[0,1,2], type_onehot_dim=[-4,-3,-2,-1]):
    '''
    :param polyline: shape (..., N * S * D)
    :param mask: shape(..., N * S * D)
    :return: polyline_info: dict, key: id, value: {"states": state, "type": type}
    '''
    polyline = polyline.reshape(-1, *polyline.shape[-2:])
    mask = mask.reshape(-1, mask.shape[-1]).astype(bool)
    polyline_state = polyline[..., state_dim]
    polyilne_type_onehot = polyline[..., type_onehot_dim]
    polyilne_type = np.argmax(polyilne_type_onehot[:, 0, :], axis=-1)
    if ids != None:
        assert len(ids) == polyline.shape[0] and len(ids) == len(set(ids))
    else:
        ids = list(range(polyline_state.shape[0]))
    polyline_info = {}
    for i, state, m, t in zip(ids, polyline_state, mask, polyilne_type):
        if not np.any(m):
            continue
        state = state[m]
        polyline_info[i] = {"states": state, "type": t}
    return polyline_info

def extract_valid_state_mask(states: np.ndarray | torch.Tensor, mask: np.ndarray | torch.Tensor):
    valid = mask.any(-1)
    states = states[valid]
    mask = mask[valid]
    states[~mask] = 0
    return states, mask

def recursive_dict_to_list(array_dict: dict) -> dict:
    for k, v in array_dict.items():
        if isinstance(v, dict):
            array_dict[k] = recursive_dict_to_list(v)
        elif isinstance(v, np.ndarray) or isinstance(v, torch.Tensor):
            array_dict[k] = v.tolist()
    return array_dict

def recursive_dict_to_array(list_dict: dict) -> dict:
    for k, v in list_dict.items():
        if isinstance(v, dict):
            list_dict[k] = recursive_dict_to_array(v)
        elif isinstance(v, list):
            if any(isinstance(item, str) for item in v):
                list_dict[k] = np.array(v, dtype=object)
            elif all(isinstance(item, int) for item in v): 
                list_dict[k] = np.array(v, dtype=int)
            else:
                list_dict[k] = np.array(v)
    return list_dict

def merge_mapping_dict(*mapping_dicts: list[dict]) -> dict:
    '''
    :param mapping_dicts: list of mapping dicts, each dict is a mapping from old id to new id
    :return: merged mapping dict
    '''
    if len(mapping_dicts) == 0:
        return {}
    merged_mapping = mapping_dicts[0]
    for i, mapping_dict in enumerate(mapping_dicts[1:]):
        for k, v in merged_mapping.items():
            if v in mapping_dict.keys():
                merged_mapping[k] = mapping_dict[v]
            else:
                print(f"Warning: key {k} in the {i+2}th dict is not found in value of the {i+1}th dict")
    return merged_mapping

def cubic_hermite_curve(start: np.ndarray | torch.Tensor, end: np.ndarray | torch.Tensor, n_points: int, tension: float = 1.):
    '''
    Generate a cubic Hermite curve between two points with given headings.
    
    :param start: (3,) array with (x, y, heading) - start position and heading in radians
    :param end: (3,) array with (x, y, heading) - end position and heading in radians  
    :param n_points: number of points to interpolate along the curve
    :param tension: scaling factor for tangent vectors (default=1.0, higher values create tighter curves)
    :return: (n_points, 2) array of (x, y) coordinates along the curve
    '''
    # Convert to numpy if needed
    if isinstance(start, torch.Tensor):
        start = start.detach().cpu().numpy()
    if isinstance(end, torch.Tensor):
        end = end.detach().cpu().numpy()
    
    # Extract positions and tangents
    p0 = start[:2]  # start position (x, y)
    p1 = end[:2]    # end position (x, y)
    
    # Convert heading to tangent vectors with tension scaling
    t0 = tension * np.array([np.cos(start[2]), np.sin(start[2])])  # start tangent
    t1 = tension * np.array([np.cos(end[2]), np.sin(end[2])])      # end tangent
    
    # Generate parameter t from 0 to 1
    t = np.linspace(0, 1, n_points)
    
    # Hermite basis functions
    h00 = 2*t**3 - 3*t**2 + 1
    h10 = t**3 - 2*t**2 + t
    h01 = -2*t**3 + 3*t**2
    h11 = t**3 - t**2
    
    # Reshape for broadcasting: (n_points,) -> (n_points, 1) for broadcasting with (2,)
    h00 = h00.reshape(-1, 1)
    h10 = h10.reshape(-1, 1)
    h01 = h01.reshape(-1, 1)
    h11 = h11.reshape(-1, 1)
    
    # Calculate curve points using Hermite interpolation
    # P(t) = h00(t)*P0 + h10(t)*T0 + h01(t)*P1 + h11(t)*T1
    # Broadcasting: (n_points, 1) * (2,) -> (n_points, 2)
    curve_points = (h00 * p0 + h10 * t0 + h01 * p1 + h11 * t1)
    
    if isinstance(start, torch.Tensor):
        return torch.from_numpy(curve_points).to(start.device)
    else:
        return curve_points

                
                
            
if __name__ == "__main__":
    # print(rotate_points_along_z(np.array([[1,2], [2,3]]), np.array(np.pi)))
    # print(cubic_hermite_curve(np.array([1,2,3]), np.array([2,3,4]), 10))
    dict1 = {"a": 1, "b": 2, "c": 3}
    dict2 = {1: "3", 2: "4", 3: "5", 4: "6"}