import pickle
import numpy as np
import torch
import tqdm
from shapely.geometry import Point, LineString, Polygon
from shapely.geometry.base import CAP_STYLE
import copy
from collections import defaultdict, deque
import os
from concurrent.futures import ThreadPoolExecutor
from scipy.spatial import cKDTree

from nuplan.planning.simulation.observation.idm.idm_states import IDMLeadAgentState, IDMAgentState
from nuplan.planning.simulation.observation.idm.idm_policy import IDMPolicy

from nuplan.common.actor_state.state_representation import StateSE2
from tuplan_garage.planning.simulation.planner.pdm_planner.utils.pdm_path import PDMPath
from cnde.models.utils.motion_smoother import MotionNonlinearSmoother
from cutils import sparse2dense
from .safety_utils import search_collision_free_modes, generate_trajectory_batch, trajectory_to_region, build_collision_matrix, cluster_trajectories

__all__ = ["RuleController"]

speed_limit_fraction = [0.2, 1.0] # Target velocity as fractions of current speed-limit
speed_limit_detail_fraction = [0.1, 0.2, 0.3, 0.4, 0.6, 0.8] #[1.0, 0.8, 0.6, 0.4, 0.2, 0.01] #[0.01, 0.2, 0.4, 0.6, 0.8, 1.0]
lateral_offsets = [0]
fallback_target_velocity = 15.0 # Desired fallback velocity in free traffic [m/s]
min_gap_to_lead_agent = 0.5 # Minimum relative distance to lead vehicle [m]
headway_time = 5.0 # Desired time headway. The minimum possible time to the vehicle in front [s]
accel_max = 4.0 # Maximum acceleration [m/s^2]
decel_max = 4.0


from enum import IntEnum
class StateIndex:
    """Index mapping for array representation of ego states."""

    _X = 0
    _Y = 1
    _HEADING = 2
    _VELOCITY_X = 3
    _VELOCITY_Y = 4
    _ACCELERATION_X = 5
    _ACCELERATION_Y = 6
    _STEERING_ANGLE = 7
    _STEERING_RATE = 8
    _ANGULAR_VELOCITY = 9
    _ANGULAR_ACCELERATION = 10

    @classmethod
    def size(cls):
        valid_attributes = [
            attribute
            for attribute in dir(cls)
            if attribute.startswith("_")
            and not attribute.startswith("__")
            and not callable(getattr(cls, attribute))
        ]
        return len(valid_attributes)

    @classmethod
    @property
    def X(cls):
        return cls._X

    @classmethod
    @property
    def Y(cls):
        return cls._Y

    @classmethod
    @property
    def HEADING(cls):
        return cls._HEADING

    @classmethod
    @property
    def VELOCITY_X(cls):
        return cls._VELOCITY_X

    @classmethod
    @property
    def VELOCITY_Y(cls):
        return cls._VELOCITY_Y

    @classmethod
    @property
    def ACCELERATION_X(cls):
        return cls._ACCELERATION_X

    @classmethod
    @property
    def ACCELERATION_Y(cls):
        return cls._ACCELERATION_Y

    @classmethod
    @property
    def STEERING_ANGLE(cls):
        return cls._STEERING_ANGLE

    @classmethod
    @property
    def STEERING_RATE(cls):
        return cls._STEERING_RATE

    @classmethod
    @property
    def ANGULAR_VELOCITY(cls):
        return cls._ANGULAR_VELOCITY

    @classmethod
    @property
    def ANGULAR_ACCELERATION(cls):
        return cls._ANGULAR_ACCELERATION

    @classmethod
    @property
    def POINT(cls):
        # assumes X, Y have subsequent indices
        return slice(cls._X, cls._Y + 1)

    @classmethod
    @property
    def STATE_SE2(cls):
        # assumes X, Y, HEADING have subsequent indices
        return slice(cls._X, cls._HEADING + 1)

    @classmethod
    @property
    def VELOCITY_2D(cls):
        # assumes velocity X, Y have subsequent indices
        return slice(cls._VELOCITY_X, cls._VELOCITY_Y + 1)

    @classmethod
    @property
    def ACCELERATION_2D(cls):
        # assumes acceleration X, Y have subsequent indices
        return slice(cls._ACCELERATION_X, cls._ACCELERATION_Y + 1)


class SE2Index(IntEnum):
    """Index mapping for state se2 (x,y,θ) arrays."""

    X = 0
    Y = 1
    HEADING = 2


class DynamicStateIndex(IntEnum):
    """Index mapping for dynamic car state (output of controller)."""

    ACCELERATION_X = 0
    STEERING_RATE = 1


class StateIDMIndex(IntEnum):
    """Index mapping for IDM states."""

    PROGRESS = 0
    VELOCITY = 1


class LeadingAgentIndex(IntEnum):
    """Index mapping for leading agent state (for IDM policies)."""

    PROGRESS = 0
    VELOCITY = 1
    LENGTH_REAR = 2


class BBCoordsIndex(IntEnum):
    """Index mapping for corners and center of bounding boxes."""

    FRONT_LEFT = 0
    REAR_LEFT = 1
    REAR_RIGHT = 2
    FRONT_RIGHT = 3
    CENTER = 4


class EgoAreaIndex(IntEnum):
    """Index mapping for area of ego agent (used in PDMScorer)."""

    MULTIPLE_LANES = 0
    NON_DRIVABLE_AREA = 1
    ONCOMING_TRAFFIC = 2


class MultiMetricIndex(IntEnum):
    """Index mapping multiplicative metrics (used in PDMScorer)."""

    NO_COLLISION = 0
    DRIVABLE_AREA = 1
    DRIVING_DIRECTION = 2


class WeightedMetricIndex(IntEnum):
    """Index mapping weighted metrics (used in PDMScorer)."""

    PROGRESS = 0
    TTC = 1
    COMFORTABLE = 2


class RuleController:
    def __init__(self):
        cpu_threads = max(1, int(os.getenv("CITYNDE_CPU_THREADS", "1")))
        if torch.get_num_threads() != cpu_threads:
            torch.set_num_threads(cpu_threads)
        self.vehicle_priority_record: list[int|str] = []
        self.deadlock_vehicle_dict: dict[int|str, float] = {}
        self.potential_deadlock_vehicle: set[int|str] = set()
        self.adaptive_vehicle_attr: dict[int|str, list] = {}
        self._lane_geometry_source = None
        self._lane_segment_a = None
        self._lane_segment_vector = None
        self._lane_segment_length_sq = None
        self._lane_segment_heading = None
        self._lane_segment_parent = None
        self._lane_segment_tree = None
        self._lane_segment_max_half_length = None
        self._motion_smoother_cache = {}
        self._get_motion_smoother(20, 0.1, warm_up=True)

    def _get_motion_smoother(self, trajectory_len, dt, warm_up=False):
        key = (int(trajectory_len), float(dt))
        if key not in self._motion_smoother_cache:
            smoother = MotionNonlinearSmoother(*key)
            self._motion_smoother_cache[key] = smoother
            if warm_up:
                x_curr = np.zeros(4, dtype=np.float32)
                reference = np.zeros((key[0] + 1, 3), dtype=np.float32)
                smoother.set_reference_trajectory(x_curr, reference)
                smoother.solve()
        return self._motion_smoother_cache[key]
        
    def get_deadlocks(self, threshold: float = 5.):
        return [v_id for v_id, t in self.deadlock_vehicle_dict.items() if t >= threshold]
    
    @staticmethod
    def _rotate_points_along_z(points, angle):
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
    
    @staticmethod
    def _angle_wrap(radians: np.ndarray) -> np.ndarray:
        """This function wraps angles to lie within [-pi, pi).

        Args:
            radians (np.ndarray): The input array of angles (in radians).

        Returns:
            np.ndarray: Wrapped angles that lie within [-pi, pi).
        """
        return (radians + np.pi) % (2 * np.pi) - np.pi
    
    @staticmethod
    def _interpolate(
        pts, num_pts=None, max_dist=None, has_heading=True,
    ) -> np.ndarray:
        """
        interpolate points either based on cumulative distances from the first one (`num_pts`)
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
        pos_dim: int = min(pts.shape[-1], 2)
        if has_heading:
            heading_dim = pts.shape[-1] - 1


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

            if has_heading:
                # Heading, so make sure to unwrap, interpolate, and wrap it.
                xyz_inter[:, heading_dim] = RuleController._angle_wrap(
                    np.interp(steps, xp=cum_dist, fp=np.unwrap(pts[:, heading_dim]))
                )

            return xyz_inter

        elif max_dist is not None:
            unwrapped_pts: np.ndarray = pts
            if has_heading:
                unwrapped_pts[..., heading_dim] = np.unwrap(unwrapped_pts[..., heading_dim])

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
            if has_heading:
                new_pts[..., heading_dim] = RuleController._angle_wrap(new_pts[..., heading_dim])

            return new_pts
    
    @staticmethod
    def _get_batch_box_pts_from_center_heading(length, width, xc, yc, heading):
        def _rotate_pt(x, y, a):
            return np.cos(a)*x - np.sin(a)*y, np.sin(a)*x + np.cos(a)*y
        l, w = length / 2.0 , width / 2.0

        ## box
        x1, y1 = l, w
        x2, y2 = l, -w
        x3, y3 = -l, -w
        x4, y4 = -l, w

        ## rotation
        a = heading
        x1_, y1_ = _rotate_pt(x1, y1, a)
        x2_, y2_ = _rotate_pt(x2, y2, a)
        x3_, y3_ = _rotate_pt(x3, y3, a)
        x4_, y4_ = _rotate_pt(x4, y4, a)
        
        pt1 = [x1_ + xc, y1_ + yc]
        pt2 = [x2_ + xc, y2_ + yc]
        pt3 = [x3_ + xc, y3_ + yc]
        pt4 = [x4_ + xc, y4_ + yc]

        return [pt1, pt2, pt3, pt4]
                   
    
    def forward(self, global_states, centers, controlled_id=None, *, 
                tl_location_id_list, tl_location_states_start, tl_location_states_center, 
                start_time_step, predicted_green_lights, 
                vehicle_ids_last_step, vehicle_states_last_step, vehicle_static_attributes, vehicle_routes,
                nn_route, nn_pred_trajs, nn_pred_scores,
                all_lane_polyline_ids, all_lane_polyline_centers, all_lane_polylines, route_backward_record,
                static_vehicle_ids_set,
                nn_once_forward_step=5, simulation_interval=0.1, num_future_frames=80,
                desc=None) -> dict:
        import time

        controlled_ids = set(controlled_id or [])
        controlled_indices = [
            index for index, vehicle_id in enumerate(vehicle_ids_last_step)
            if vehicle_id in controlled_ids or str(vehicle_id) in {str(item) for item in controlled_ids}
        ]
        controlled_global_states = {
            index: np.array(global_states[index], copy=True) for index in controlled_indices
        }
        
        magnification = 1.0
        collision_threshold = np.array([1.0, 0.5], dtype=np.float64)

        def wrap_to_pi(a):
            return (a + np.pi) % (2 * np.pi) - np.pi
        
        def find_turning_points(route_states, turn_angle_threshold=75):
            route_size = len(route_states)
            total_angle_diff = 0
            len_idx, angle_idx = None, None
            route_end = False
            
            diffs = np.diff(route_states[:, :2], axis=0)
            cum = np.concatenate(([0.0], np.cumsum(np.hypot(diffs[:, 0], diffs[:, 1]))))
            mask = cum > 15.0
            len_idx = np.flatnonzero(mask)[0] if np.any(mask) else None
            
            i = 1
            while i < route_size:
                if abs(route_states[i, 2]) < 1e-6 or abs(route_states[i - 1, 2]) < 1e-6:
                    i += 1
                    continue
                
                total_angle_diff += abs(wrap_to_pi(route_states[i, 2] - route_states[i - 1, 2]))
                if abs(total_angle_diff) > np.deg2rad(turn_angle_threshold):
                    angle_idx = i
                    break
                else:
                    i += 1
            
            idx = min([i for i in [len_idx, angle_idx, len(route_states) - 1] if i is not None])
            if idx == len(route_states) - 1 and cum[idx] < 8.0:
                route_end = True
            
            return route_states[idx, :], idx, route_end
        
        def generate_bezier_curve(P0, h0, P3, h3, start_straight_len=0.0, end_straight_len=0.0):
            def bezier(P0, P1, P2, P3, t):
                mt = 1 - t
                return (mt**3)[:, None]*P0 + (3*mt**2*t)[:, None]*P1 + (3*mt*t**2)[:, None]*P2 + (t**3)[:, None]*P3

            def bezier_derivative(P0, P1, P2, P3, t):
                mt = 1 - t
                return (3*mt**2)[:, None]*(P1-P0) + (6*mt*t)[:, None]*(P2-P1) + (3*t**2)[:, None]*(P3-P2)
            
            min_turn_radius, max_turn_radius = 8.0, 30.0
            spacing = 0.5
            
            v0 = np.array([np.cos(h0), np.sin(h0)], dtype=float)
            v3 = np.array([np.cos(h3), np.sin(h3)], dtype=float)
            
            start_straight_len = max(0.0, start_straight_len)
            end_straight_len = max(0.0, end_straight_len)
            
            P0 += start_straight_len * v0
            P3 -= end_straight_len * v3
            
            chord = np.linalg.norm(P3 - P0)
            theta = abs(wrap_to_pi(h3 - h0))
            
            if theta < 1e-3:
                P1 = P0 + (P3 - P0) / 3.0
                P2 = P0 + 2.0 * (P3 - P0) / 3.0
            else:
                R = chord / (2.0 * max(np.sin(theta / 2.0), 1e-6))
                R = float(np.clip(R, min_turn_radius, max_turn_radius))
                L_arc = (4.0 / 3.0) * R * np.tan(theta / 4.0)
                L_arc = float(np.clip(L_arc, 1.0, max(0.45 * max(chord, 1.0), 1.0)))
                P1 = P0 + L_arc * v0
                P2 = P3 - L_arc * v3
            
            denom = v0[0] * v3[1] - v0[1] * v3[0]
            if abs(denom) < 1e-6 and chord < 1.0:
                P1 = P0 + 0.25 * (P3 - P0)
                P2 = P0 + 0.75 * (P3 - P0)
            
            rough_len = max(chord, 2.0, 1.0)
            N_fine = int(np.clip(int(rough_len / spacing) * 20, 200, 4000))
            t_fine = np.linspace(0.0, 1.0, N_fine)
            pts_fine = bezier(P0, P1, P2, P3, t_fine)
            
            dxyz = np.diff(pts_fine, axis=0)
            seglen = np.hypot(dxyz[:, 0], dxyz[:, 1])
            cumlen = np.concatenate([[0.0], np.cumsum(seglen)])
            total_len = float(cumlen[-1])
            if total_len < spacing:
                t_samples = np.array([0.0, 1.0])
            else:
                target_ds = np.concatenate([np.arange(0.0, total_len - 1e-6, spacing), [total_len]])
                t_samples = np.interp(target_ds, cumlen, t_fine)
            
            pts = bezier(P0, P1, P2, P3, t_samples)
            dvec = bezier_derivative(P0, P1, P2, P3, t_samples)
            if np.linalg.norm(dvec[0]) < 1e-6:
                dvec[0] = v0
            if np.linalg.norm(dvec[-1]) < 1e-6:
                dvec[-1] = v3
            hd = wrap_to_pi(np.arctan2(dvec[:, 1], dvec[:, 0]))
            bezier_states = np.column_stack([pts[:, 0], pts[:, 1], hd])
            
            if start_straight_len > 0.0:
                start_xy = P0 - start_straight_len * v0
                start_state = np.array([[start_xy[0], start_xy[1], h0]])
                bezier_states = np.vstack([start_state, bezier_states])
            
            if end_straight_len > 0.0:
                end_xy = P3 + end_straight_len * v3
                end_state = np.array([[end_xy[0], end_xy[1], h3]])
                bezier_states = np.vstack([bezier_states, end_state])
            
            return bezier_states
        
        def _build_forward_path(vid_index: int, lead_veh: tuple[float, float]|None = None, off_road_future=False, deadlock=False) -> np.ndarray:
            ego_state = vehicle_states_last_step[vid_index].copy()
            ego_state[2] = wrap_to_pi(ego_state[2])
            # map related
            match_route = vehicle_routes[vehicle_ids_last_step[vid_index]][:5]
            if len(match_route) == 0:
                return None
                
            lane_midline_pts_list = []
            for id, m_r in enumerate(match_route):
                lane_midline_pts = all_lane_polylines[np.array(all_lane_polyline_ids, dtype=object) == m_r].reshape(-1, 2)
                polyline_heading=np.arctan2(
                    np.concatenate([lane_midline_pts[1:2] - lane_midline_pts[0:1], lane_midline_pts[1:] - lane_midline_pts[:-1]], axis=0)[..., 1],
                    np.concatenate([lane_midline_pts[1:2] - lane_midline_pts[0:1], lane_midline_pts[1:] - lane_midline_pts[:-1]], axis=0)[..., 0],
                )
                lane_midline_pts_list.append(np.concatenate([lane_midline_pts.reshape(-1, 2), polyline_heading.reshape(-1, 1)], axis=-1))
            
            lane_midline_pts_before_vehicle = np.concatenate(lane_midline_pts_list).reshape(1, -1, 3)[..., :2]
            lane_midline_pts_before_vehicle[:, :, :] -= ego_state[:2].reshape(1, 1, 2)
            lane_midline_pts_before_vehicle = RuleController._rotate_points_along_z(
                lane_midline_pts_before_vehicle.reshape(1, -1, 2),
                -ego_state[..., 2].reshape(1)
            ).reshape(-1, 2)
            valid_mask = (lane_midline_pts_before_vehicle[:, 0] > 0) #& (lane_midline_pts_before_vehicle[:, 0] < 100)
            route_states = np.concatenate(lane_midline_pts_list, axis=0)[valid_mask]
            if len(route_states) == 0:
                return None
            
            point_end, point_idx, route_end = find_turning_points(route_states)
            
            P0 = np.array([ego_state[0], ego_state[1]], dtype=float)
            h0 = float(ego_state[2])
            
            P3 = point_end[:2]
            h3 = point_end[2]
            
            bezier_states = generate_bezier_curve(P0, h0, P3, h3, start_straight_len=0.2 if deadlock else 0.0)
            joined_states = np.vstack([bezier_states, route_states[point_idx:]])
            
            joined_local_xy = joined_states[:, :2] - ego_state[:2]
            joined_local_xy = RuleController._rotate_points_along_z(
                joined_local_xy.reshape(1, -1, 2), -ego_state[2].reshape(1)
            ).reshape(-1, 2)
            joined_local_h = wrap_to_pi(joined_states[:, 2] - ego_state[2])
            centerlines = [StateSE2(joined_local_xy[k, 0], joined_local_xy[k, 1], joined_local_h[k]) for k in range(len(joined_local_h))]
            centerline = PDMPath(centerlines)
            
            updated_states_for_bi = []
            current_vxy_local = RuleController._rotate_points_along_z(
                ego_state[3:5].reshape(1, 1, 2), -ego_state[2].reshape(1)
            ).reshape(-1, 2)
            current_v = float(current_vxy_local[0, 0])
            
            if lead_veh is None:
                cl_xy = np.array([(s.x, s.y) for s in centerlines], dtype=float)
                ls = LineString(cl_xy.tolist())
                cur_s = ls.project(Point(0.0, 0.0))
                
                seg = np.diff(cl_xy, axis=0)
                seglen = np.hypot(seg[:, 0], seg[:, 1])
                cumlen = np.concatenate([[0.0], np.cumsum(seglen)])
                start_k = int(np.searchsorted(cumlen, cur_s + 1e-6))
                
                L_e = float(vehicle_static_attributes[vehicle_ids_last_step[vid_index]][0]) * magnification + collision_threshold[0]
                W_e = float(vehicle_static_attributes[vehicle_ids_last_step[vid_index]][1]) * magnification + collision_threshold[1]

                lead_progress = cumlen[-1]
                lead_vid = None
                lead_vel = 15.0
                
                other_polys = polys[:vid_index] + polys[vid_index+1:]
                other_bboxes = bboxes[:vid_index] + bboxes[vid_index+1:]
                other_vids = vehicle_ids_last_step[:vid_index] + vehicle_ids_last_step[vid_index+1:]
                
                for k in range(start_k, len(centerlines)):
                    x_l = centerlines[k].x
                    y_l = centerlines[k].y
                    h_l = centerlines[k].heading
                    xy_glob = RuleController._rotate_points_along_z(
                        np.array([[x_l, y_l]], dtype=float).reshape(1, 1, 2),
                        ego_state[2].reshape(1)
                    ).reshape(2) + ego_state[:2]
                    x_e, y_e = float(xy_glob[0]), float(xy_glob[1])
                    h_e = wrap_to_pi(h_l + ego_state[2])
                    
                    ego_poly_k = _rect_poly(x_e, y_e, h_e, L_e, W_e)
                    ego_bbox_k = _bbox(ego_poly_k)
                    
                    hit_any = False
                    for poly_o, bb_o, vid_o in zip(other_polys, other_bboxes, other_vids):
                        if not _aabb_hit(ego_bbox_k, bb_o):
                            continue
                        if ego_poly_k.intersects(poly_o) and abs(wrap_to_pi(h_e - vehicle_states_last_step[vehicle_ids_last_step.index(vid_o)][2])) < 0.75 * np.pi:
                            lead_progress = cumlen[k]
                            lead_vid = vid_o
                            hit_any = True
                            break
                    if hit_any:
                        break
                
                rel_progress = min(max(lead_progress - cur_s, 2.0), 15.0)
                if lead_vid is not None:
                    lead_idx = vehicle_ids_last_step.index(lead_vid)
                    vx_o, vy_o = vehicle_states_last_step[lead_idx][3:5]
                    lead_vel = np.hypot(vx_o, vy_o)
            
            else:
                rel_progress, lead_vel = lead_veh
            
            lead_agent = IDMLeadAgentState(progress=rel_progress, velocity=lead_vel, length_rear=0.0)
            current_progress: float = centerline.project(Point(0., 0., 0.))
            
            if off_road_future:
                target_velocity = max(current_v, 5.0)
            elif deadlock:
                target_velocity = max(current_v, 10.0)
            else:
                target_velocity = 15.0
            
            policy = IDMPolicy(
                target_velocity=target_velocity,
                min_gap_to_lead_agent=1.5,
                headway_time=5.0,
                accel_max=4.0,
                decel_max=4.0,
            )
            
            for _ in range(collision_check_forward_step):
                velocity = current_v
                sol = policy.solve_forward_euler_idm_policy(
                    IDMAgentState(current_progress, velocity), lead_agent, 0.1
                )
                current_progress = sol.progress
                update_velocity = sol.velocity
                st = centerline.interpolate([current_progress])[0]
                after_xyhvxy = [st.x, st.y, st.heading, sol.velocity * np.cos(st.heading), sol.velocity * np.sin(st.heading)]
                updated_states_for_bi.append(np.array(after_xyhvxy))
                current_v = update_velocity
            
            updated_states_for_bi = np.stack(updated_states_for_bi)
            updated_xy = RuleController._rotate_points_along_z(
                updated_states_for_bi[:, :2].reshape(1, -1, 2), ego_state[2].reshape(1)
            ).reshape(-1, 2)
            updated_xy = updated_xy + ego_state[:2]
            updated_h = wrap_to_pi(updated_states_for_bi[:, 2] + ego_state[2])
            updated_vxy = RuleController._rotate_points_along_z(
                updated_states_for_bi[:, 3:5].reshape(1, -1, 2), ego_state[2].reshape(1)
            ).reshape(-1, 2)
            
            return updated_xy, updated_h, updated_vxy, route_end
        
        def _assemble_backward_chain(vid_index: int) -> np.ndarray|None:
            vid = vehicle_ids_last_step[vid_index]
            ego_state = vehicle_states_last_step[vid_index].copy()
            ego_xy = ego_state[:2]
            ego_yaw = wrap_to_pi(ego_state[2])
            
            if len(vehicle_routes[vid]) == 0:
                return None
            cur_lane_id = vehicle_routes[vid][0]
            
            backward_paths = route_backward_record.get(cur_lane_id, [])
            if not backward_paths:
                return None
            path = max(backward_paths, key=len)
            
            lane_midline_states = []
            for lane_id in path:
                idx = np.where(np.array(all_lane_polyline_ids, dtype=object) == lane_id)[0]
                pts = all_lane_polylines[idx[0]].reshape(-1, 2)
                diffs = np.concatenate([pts[1:2] - pts[0:1], pts[1:] - pts[:-1]], axis=0)
                headings = np.arctan2(diffs[:, 1], diffs[:, 0])
                lane_midline_states.append(
                    np.concatenate([pts, headings[:, None]], axis=-1)
                )
            
            route_states_world = np.concatenate(lane_midline_states, axis=0)
            route_pts_shift = route_states_world[:, :2] - ego_xy.reshape(1, 2)
            route_pts_ego = RuleController._rotate_points_along_z(
                route_pts_shift.reshape(1, -1, 2),
                -ego_yaw
            ).reshape(-1, 2)
            valid_mask = route_pts_ego[:, 0] < 0
            route_states_world = route_states_world[valid_mask][::-1]
            if route_states_world.shape[0] == 0:
                return None
            
            point_start, _, _ = find_turning_points(route_states_world)
            
            return point_start
        
        def _build_reverse_traj(vid_index: int, use_motion_smoother=False) -> np.ndarray:
            ego_state = vehicle_states_last_step[vid_index].copy()
            P3 = np.array([ego_state[0], ego_state[1]], dtype=float)
            h3 = float(ego_state[2])
            
            point_start = _assemble_backward_chain(vid_index)
            if point_start is None:
                point_start = np.array([
                    ego_state[0] - 15.0 * np.cos(ego_state[2]),
                    ego_state[1] - 15.0 * np.sin(ego_state[2]),
                    wrap_to_pi(ego_state[2])
                ], dtype=float)
            P0 = point_start[:2]
            h0 = point_start[2]
            
            bezier_states = generate_bezier_curve(P0, h0, P3, h3, end_straight_len=0.2)
            joined_states = bezier_states[::-1]
            
            joined_local_xy = joined_states[:, :2] - ego_state[:2]
            joined_local_xy = RuleController._rotate_points_along_z(
                joined_local_xy.reshape(1, -1, 2), -ego_state[2].reshape(1)
            ).reshape(-1, 2)
            joined_local_h = wrap_to_pi(joined_states[:, 2] - ego_state[2])
            centerlines = [StateSE2(joined_local_xy[k, 0], joined_local_xy[k, 1], joined_local_h[k]) for k in range(len(joined_local_h))]
            centerline = PDMPath(centerlines)
            
            updated_states_for_bi = []
            current_vxy_local = RuleController._rotate_points_along_z(
                ego_state[3:5].reshape(1, 1, 2), -ego_state[2].reshape(1)
            ).reshape(-1, 2)
            current_v = -float(current_vxy_local[0, 0])
            
            back_agent = IDMLeadAgentState(progress=2.0, velocity=2.0, length_rear=0.0)
            current_progress: float = centerline.project(Point(0., 0., 0.))
            
            policy = IDMPolicy(
                target_velocity=2.0,
                min_gap_to_lead_agent=1.0,
                headway_time=1.0,
                accel_max=2.0,
                decel_max=2.0
            )
            
            for _ in range(collision_check_forward_step):
                velocity = max(current_v, 0)
                sol = policy.solve_forward_euler_idm_policy(
                    IDMAgentState(current_progress, velocity), back_agent, 0.1
                )
                current_progress = sol.progress
                update_velocity = sol.velocity
                st = centerline.interpolate([current_progress])[0]
                after_xyhvxy = [st.x, st.y, st.heading, sol.velocity * np.cos(st.heading), sol.velocity * np.sin(st.heading)]
                updated_states_for_bi.append(np.array(after_xyhvxy))
                current_v = update_velocity
            
            updated_states_for_bi = np.stack(updated_states_for_bi)
            updated_xy = RuleController._rotate_points_along_z(
                updated_states_for_bi[:, :2].reshape(1, -1, 2), ego_state[2].reshape(1)
            ).reshape(-1, 2)
            updated_xy = updated_xy + ego_state[:2]
            updated_h = wrap_to_pi(updated_states_for_bi[:, 2] + ego_state[2])
            
            output_state = np.column_stack([updated_xy, updated_h])
            
            if use_motion_smoother:
                center = ego_state[:2]
                ego_yaw = ego_state[2]
                
                v0 = float(np.hypot(ego_state[3], ego_state[4]))
                x_curr = np.array([0.0, 0.0, wrap_to_pi(ego_yaw + np.pi), v0], dtype=float)
                
                ref = np.vstack((
                    np.array([[0.0, 0.0, wrap_to_pi(ego_yaw + np.pi)]], dtype=np.float32),
                    np.column_stack([
                        updated_xy[:, :2] - center,
                        wrap_to_pi(updated_h + np.pi),
                    ]),
                ))
                ref[:, 2] = np.unwrap(ref[:, 2])
                
                motion_smoother = _get_motion_smoother()
                motion_smoother.set_reference_trajectory(x_curr, ref)
                sol = motion_smoother.solve()
                
                smoother = motion_smoother
                traj_smoothed = np.stack(
                    [
                        sol.value(smoother.position_x), 
                        sol.value(smoother.position_y), 
                        wrap_to_pi(sol.value(smoother.yaw) + np.pi), 
                    ],
                    axis=-1
                )
                output_state = traj_smoothed[1:].reshape(-1, 3)
                output_state[..., :2] = output_state[..., :2] + center
            
            return output_state
        
        def _rect_poly(x, y, h, L, W):
            pts = RuleController._get_batch_box_pts_from_center_heading(
                length=np.array([L]), width=np.array([W]),
                xc=np.array([x]), yc=np.array([y]), heading=np.array([h])
            )
            return Polygon([
                (pts[0][0][0], pts[0][1][0]),
                (pts[1][0][0], pts[1][1][0]),
                (pts[2][0][0], pts[2][1][0]),
                (pts[3][0][0], pts[3][1][0]),
            ])
        
        def _bbox(poly: Polygon):
            minx, miny, maxx, maxy = poly.bounds
            return minx, miny, maxx, maxy
        
        def _aabb_hit(b1, b2):
            minx1, miny1, maxx1, maxy1 = b1
            minx2, miny2, maxx2, maxy2 = b2
            return (maxx1 >= minx2) and (maxx2 >= minx1) and (maxy1 >= miny2) and (maxy2 >= miny1)
        
        timer = time.time()
        
        polys, bboxes = [], []
        for idx, vid in enumerate(vehicle_ids_last_step):
            x, y, h = vehicle_states_last_step[idx][0], vehicle_states_last_step[idx][1], vehicle_states_last_step[idx][2]
            L, W = float(vehicle_static_attributes[vid][0]) * magnification + collision_threshold[0], float(vehicle_static_attributes[vid][1]) * magnification + collision_threshold[1]
            poly = _rect_poly(x, y, h, L, W)
            
            polys.append(poly)
            bboxes.append(_bbox(poly))
        
        collision_check_forward_step = nn_once_forward_step * 4
        rule_dict = {vid: np.zeros((collision_check_forward_step, 4), dtype=bool) for vid in vehicle_ids_last_step}  # vid: [stop, launch, off_road, safety_layer]
        
        updated_states = []
        
        motion_smoother_start = None

        def _get_motion_smoother():
            nonlocal motion_smoother_start
            if motion_smoother_start is None:
                motion_smoother_start = self._get_motion_smoother(collision_check_forward_step, 0.1)
            return motion_smoother_start
        # '''
        vehicle_moving_distance = np.linalg.norm(np.diff(global_states[..., :2], axis=1), axis=-1)[:, :collision_check_forward_step].sum(-1)
        stop_vehicle_bool = vehicle_moving_distance < 1.0
        
        # trajectory based traffic lights
        tl_ids = tl_location_id_list
        tl_start = tl_location_states_start if len(tl_ids) > 0 else np.empty((0, 2))
        if isinstance(predicted_green_lights, np.ndarray):
            predicted_green_lights = predicted_green_lights.tolist()
        
        timer_start = time.time()
        tl_id_set = set(tl_location_id_list)
        tl_lane_mask = np.fromiter(
            (lane_id in tl_id_set for lane_id in all_lane_polyline_ids),
            dtype=bool,
            count=len(all_lane_polyline_ids),
        )
        tl_lane_polylines = all_lane_polylines[tl_lane_mask]
        tl_lane_ids = np.asarray(all_lane_polyline_ids, dtype=object)[tl_lane_mask]
        position_to_map_distance = global_states[:, 0, :2].reshape(-1, 1, 2) - tl_lane_polylines[:, 0].reshape(1, -1, 2)
        position_to_map_mask = np.linalg.norm(position_to_map_distance, axis=-1) < 20
        print(f"traffic light preparation done, time: {time.time() - timer_start}")
        
        timer_route = 0
        timer_red = 0
        timer_off_road = 0
        timer_launch_main = 0
        timer_motion_smoother = 0

        if self._lane_geometry_source is not all_lane_polylines:
            lane_segment_a = all_lane_polylines[:, :-1, :2]
            lane_segment_vector = all_lane_polylines[:, 1:, :2] - lane_segment_a
            self._lane_geometry_source = all_lane_polylines
            self._lane_segment_a = lane_segment_a
            self._lane_segment_vector = lane_segment_vector
            self._lane_segment_length_sq = np.maximum(np.sum(lane_segment_vector ** 2, axis=-1), 1e-6)
            self._lane_segment_heading = np.arctan2(lane_segment_vector[..., 1], lane_segment_vector[..., 0])
            segment_length = np.linalg.norm(lane_segment_vector, axis=-1)
            lane_segment_b = lane_segment_a + lane_segment_vector
            self._lane_segment_tree = cKDTree(((lane_segment_a + lane_segment_b) / 2).reshape(-1, 2))
            self._lane_segment_parent = np.repeat(np.arange(len(all_lane_polylines)), lane_segment_a.shape[1])
            self._lane_segment_max_half_length = float(segment_length.max(initial=0)) / 2

        def _check_off_road(vid_index):
            state_timeseries = global_states[vid_index]
            final_state = state_timeseries[nn_once_forward_step * 4 - 1, :5]
            near_mask = np.linalg.norm(all_lane_polyline_centers - final_state[None, :2], axis=1) < 60.0
            if not np.any(near_mask):
                return False

            p_A = self._lane_segment_a[near_mask].reshape(-1, 2)
            vec_AB = self._lane_segment_vector[near_mask].reshape(-1, 2)
            len_sq_AB = self._lane_segment_length_sq[near_mask].reshape(-1)
            lane_segments_heading = self._lane_segment_heading[near_mask].reshape(-1)

            future_xy = state_timeseries[:nn_once_forward_step * 4, :2]
            future_h = state_timeseries[:nn_once_forward_step * 4, 2]
            vec_AP = future_xy[:, None] - p_A[None, :]
            t_proj = np.sum(vec_AP * vec_AB[None, :, :], axis=2) / len_sq_AB[None, :]
            t_clamped = np.clip(t_proj, 0.0, 1.0)
            closest_points = p_A[None, :] + t_clamped[:, :, None] * vec_AB[None, :]
            dists = np.linalg.norm(future_xy[:, None, :] - closest_points, axis=2)
            diff_h = wrap_to_pi(future_h[:, None] - lane_segments_heading[None, :])
            dists = np.where(np.abs(diff_h) <= np.pi / 2, dists, 1e10)
            return bool(np.any(dists.min(axis=1) > 2.0))

        def _check_off_road_spatial_batch():
            forward_steps = nn_once_forward_step * 4
            final_xy = global_states[:, forward_steps - 1, :2]
            near_masks = np.linalg.norm(
                all_lane_polyline_centers[None, :, :] - final_xy[:, None, :], axis=2
            ) < 60.0
            has_near_polyline = np.any(near_masks, axis=1)
            future_xy = global_states[:, :forward_steps, :2]
            future_heading = global_states[:, :forward_steps, 2]
            flat_xy = future_xy.reshape(-1, 2)
            candidate_radius = 2.0 + self._lane_segment_max_half_length + 1e-6
            candidate_lists = self._lane_segment_tree.query_ball_point(flat_xy, candidate_radius)
            candidate_counts = np.fromiter(
                (len(candidates) for candidates in candidate_lists), dtype=np.intp, count=len(candidate_lists)
            )
            if np.sum(candidate_counts) == 0:
                result = np.ones(len(global_states), dtype=bool)
                result[~has_near_polyline] = False
                return result.tolist()

            point_indices = np.repeat(np.arange(len(candidate_lists)), candidate_counts)
            candidates = np.concatenate(candidate_lists).astype(np.intp, copy=False)
            vehicle_indices = point_indices // forward_steps
            parent = self._lane_segment_parent[candidates]
            candidate_is_near = near_masks[vehicle_indices, parent]
            point_indices = point_indices[candidate_is_near]
            candidates = candidates[candidate_is_near]
            parent = parent[candidate_is_near]

            segment = candidates % self._lane_segment_a.shape[1]
            p_A = self._lane_segment_a[parent, segment]
            vec_AB = self._lane_segment_vector[parent, segment]
            len_sq_AB = self._lane_segment_length_sq[parent, segment]
            vec_AP = flat_xy[point_indices] - p_A
            t_proj = np.sum(vec_AP * vec_AB, axis=1) / len_sq_AB
            closest_points = p_A + np.clip(t_proj, 0.0, 1.0)[:, None] * vec_AB
            dists = np.linalg.norm(flat_xy[point_indices] - closest_points, axis=1)
            lane_heading = self._lane_segment_heading[parent, segment]
            heading_diff = wrap_to_pi(future_heading.reshape(-1)[point_indices] - lane_heading)
            dists = np.where(np.abs(heading_diff) <= np.pi / 2, dists, 1e10)

            min_distances = np.full(len(candidate_lists), 1e10, dtype=dists.dtype)
            np.minimum.at(min_distances, point_indices, dists)
            result = np.any(min_distances.reshape(len(global_states), forward_steps) > 2.0, axis=1)
            result[~has_near_polyline] = False
            return result.tolist()

        timer_off_road_start = time.time()
        off_road_batch = _check_off_road_spatial_batch()
        if os.getenv("CITYNDE_VALIDATE_SPATIAL_OFFROAD") == "1":
            with ThreadPoolExecutor(max_workers=min(8, len(global_states))) as executor:
                exact_batch = list(executor.map(_check_off_road, range(len(global_states))))
            mismatch = np.flatnonzero(np.asarray(exact_batch) != np.asarray(off_road_batch))
            if len(mismatch) > 0:
                raise AssertionError(f"off-road spatial mismatch: {mismatch.tolist()}")
        timer_off_road += time.time() - timer_off_road_start

        for bi, state_timeseries in enumerate(global_states):
            timer_route_start = time.time()
            possible_polyline = tl_lane_polylines[position_to_map_mask[bi]][..., :2].reshape(-1, 20, 2)
            possible_ids = tl_lane_ids[position_to_map_mask[bi]]
            distance_real = np.linalg.norm(possible_polyline - global_states[bi, 0, :2], axis=-1).min(-1)
            try:
                idx = np.argmin(distance_real)
                cur_lane = possible_ids[idx]
                if distance_real[idx] > 2.:
                    cur_lane = None
            except:
                cur_lane = None
            
            final_state = vehicle_states_last_step[bi][:5].copy()
            updated_state_timeseries = []

            # route based traffic lights
            possible_lane_id_list = []
            possible_lane_start_list = []
            for tl_index, id in enumerate(tl_ids):
                if id in vehicle_routes[vehicle_ids_last_step[bi]][:5]:
                    possible_lane_id_list.append(id)
                    possible_lane_start_list.append(tl_start[tl_index].reshape(1, 2))
            lane_id = None
            # filter tl far from current positions
            if len(possible_lane_start_list) == 0:
                pass
            else:
                distance = np.linalg.norm(np.concatenate(possible_lane_start_list).reshape(1, -1, 2) - global_states[bi, 0, :2], axis=-1).min()
                distance_flag = False
                if distance > 20:
                    distance_flag = True
                    
                if distance_flag or cur_lane in tl_ids:
                    pass
                else:
                    assert len(list(possible_lane_id_list)) == len(list(set(possible_lane_id_list)))
                    unique_id = possible_lane_id_list
                    lane_id = None
                    min_dis = 2000
                    for id in unique_id:
                        match_distance_2 = np.linalg.norm(global_states[bi, 0, :2].reshape(2, ) - tl_start.reshape(-1, 2)[tl_ids.index(id)].reshape(2, ), axis=-1)
                        center_tl_checked = tl_start.reshape(-1, 2)[tl_ids.index(id)].reshape(1, 1, 2)
                        center_tl_checked = center_tl_checked - global_states[bi, 0, :2]
                        center_tl_checked = RuleController._rotate_points_along_z(
                            center_tl_checked[..., :2].reshape(1, 1, 2),
                            -global_states[bi, 0, 2].reshape(1)
                        ).reshape(2)
                        
                        if match_distance_2 < min_dis:
                            min_dis = match_distance_2
                            
                            if match_distance_2 < 30:
                                center_tl_checked = tl_start.reshape(-1, 2)[tl_ids.index(id)].reshape(1, 1, 2)
                                center_tl_checked = center_tl_checked - global_states[bi, 0, :2]
                                center_tl_checked = RuleController._rotate_points_along_z(
                                    center_tl_checked[..., :2].reshape(1, 1, 2),
                                    -global_states[bi, 0, 2].reshape(1)
                                ).reshape(2)
                                if center_tl_checked[0] > -1. and np.abs(center_tl_checked[1]) < 2.:
                                    lane_id = id
            
            if lane_id is not None:
                center_tl_checked = tl_start.reshape(-1, 2)[tl_ids.index(lane_id)].reshape(1, 1, 2)
                center_tl_checked = center_tl_checked - global_states[bi, 0, :2]
                center_tl_checked = RuleController._rotate_points_along_z(
                    center_tl_checked[..., :2].reshape(1, 1, 2),
                    -global_states[bi, 0, 2].reshape(1)
                ).reshape(2)
                if center_tl_checked[0] < -1. or np.abs(center_tl_checked[1]) > 2.:
                    lane_id = None
                if lane_id not in vehicle_routes[vehicle_ids_last_step[bi]][:5]:
                    lane_id = None
            
            try:
                vehicle_heading = final_state[2]
                possible_lane = all_lane_polylines[all_lane_polyline_ids.index(lane_id)]
                if possible_lane.shape[0] > 1:
                    lane_heading = np.arctan2(possible_lane[1][1] - possible_lane[0][1], possible_lane[1][0] - possible_lane[0][0])
                    if np.abs((lane_heading - vehicle_heading + np.pi) % (2 * np.pi) - np.pi) > np.pi / 2:
                        lane_id = None
            except:
                pass
            
            red_light, green_light = False, False
            for poly_id in vehicle_routes[vehicle_ids_last_step[bi]][:5]:
                if poly_id in tl_ids:
                    if poly_id not in predicted_green_lights[0]:
                        red_light = True
                    else:
                        green_light = True
                    break
            timer_route += time.time() - timer_route_start
            
            timer_red_start = time.time()
            red_traffic_light_updated = False
            for t, state_t in enumerate(state_timeseries):
                if t == collision_check_forward_step:
                    break
                
                absolute_t_step = t + start_time_step
                
                current_traffic_light_status = None
                last_traffic_light_status = None
                tl_translation = None
                if absolute_t_step < len(predicted_green_lights):
                    if lane_id in predicted_green_lights[absolute_t_step]:
                        current_traffic_light_status = 'green'
                    elif lane_id is not None:
                        current_traffic_light_status = 'red'
                    if lane_id in predicted_green_lights[absolute_t_step - 1]:
                        last_traffic_light_status = 'green'
                    elif lane_id is not None:
                        last_traffic_light_status = 'red'
                        
                elif absolute_t_step >= len(predicted_green_lights):
                    if lane_id is not None:
                        current_traffic_light_status = 'green'
                        last_traffic_light_status = 'green'
                    
                tl_translation = f"{last_traffic_light_status}-{current_traffic_light_status}"
                
                if current_traffic_light_status is not None:
                    assert tl_translation is not None
                
                if tl_translation == 'green-red' or tl_translation == 'red-red':
                    ghost_vehicle_position = tl_start.reshape(-1, 2)[tl_ids.index(lane_id)].reshape(1, 1, 2)
                    relative_distance = np.linalg.norm(ghost_vehicle_position.reshape(2,) - state_t[:2])
                    bi_global_states = global_states[bi]
                    # if relative_distance < 6.0:
                    #     bi_global_states = global_states[bi]
                    # else:
                    #     bi_global_states = generate_bezier_curve(
                    #         P0=final_state[:2],
                    #         h0=final_state[2],
                    #         P3=ghost_vehicle_position.reshape(2,),
                    #         h3=final_state[2],
                    #     )
                    ghost_vehicle_position = ghost_vehicle_position - final_state[:2]
                    ghost_vehicle_position = RuleController._rotate_points_along_z(
                        ghost_vehicle_position[..., :2].reshape(1, 1, 2),
                        -final_state[2].reshape(1)
                    ).reshape(2)
                    global_states_bi_xy = bi_global_states[:, :2].reshape(1, -1, 2)
                    global_states_bi_xy = global_states_bi_xy - final_state[:2]
                    global_states_bi_xy = RuleController._rotate_points_along_z(
                        global_states_bi_xy,
                        -final_state[2].reshape(1)
                    ).reshape(-1, 2)
                    current_vxy = final_state[3:5].reshape(1, -1, 2)
                    current_vxy = RuleController._rotate_points_along_z(
                        current_vxy,
                        -final_state[2].reshape(1)
                    ).reshape(-1, 2)
                    current_v = current_vxy[0, 0]
                    current_xy = [0, 0]
                    global_states_bi_h = bi_global_states[:, 2] - final_state[2]
                    for i in range(1, len(global_states_bi_xy)):
                        if global_states_bi_xy[i, 0] < 0.0:
                            global_states_bi_xy[i] = global_states_bi_xy[i - 1]
                    centerlines = [StateSE2(global_states_bi_xy[sub_t, 0], global_states_bi_xy[sub_t, 1], global_states_bi_h[sub_t]) for sub_t in range(len(global_states_bi_h))]
                    centerlines.insert(0, StateSE2(0., 0., 0.))
                    centerline = PDMPath(centerlines)
                    current_progress: float = centerline.project(
                        Point(0.,0.,0.)
                    )
                    
                    policy = IDMPolicy(
                        target_velocity = 6.0,
                        min_gap_to_lead_agent = 0.5,
                        headway_time = 0.5,
                        accel_max = 2.0,
                        decel_max = 10.0
                    )
                    updated_states_for_bi = []
                    after_compute_xyhvxy = [0., 0., 0.]
                    half_length = vehicle_static_attributes[vehicle_ids_last_step[bi]][0] * 0.8
                    for sub_t in range(collision_check_forward_step - t):
                        velocity = max(current_v, 0)
                        relative_distance = np.sqrt((ghost_vehicle_position[0] - current_xy[0]) ** 2 + (ghost_vehicle_position[1]- current_xy[1]) ** 2)
                        if velocity < 0.2 and relative_distance < half_length + 0.5:
                            updated_states_for_bi.append(np.array([after_compute_xyhvxy[0], after_compute_xyhvxy[1], after_compute_xyhvxy[2], 0., 0.]))
                            continue
                        lead_agent = IDMLeadAgentState(progress=relative_distance, velocity=0.0, length_rear=half_length)
                        solution = policy.solve_forward_euler_idm_policy(
                            IDMAgentState(current_progress, velocity), lead_agent, 0.1
                        )
                        
                        current_progress = solution.progress
                        update_velocity = max(solution.velocity, 0)
                        after_compute_xyh_statese2 = centerline.interpolate([current_progress])[0]
                        after_compute_xyhvxy = [after_compute_xyh_statese2.x, after_compute_xyh_statese2.y, after_compute_xyh_statese2.heading, 
                                                solution.velocity * np.cos(after_compute_xyh_statese2.heading), solution.velocity * np.sin(after_compute_xyh_statese2.heading)]
                        updated_states_for_bi.append(np.array(after_compute_xyhvxy))
                        
                        current_v = update_velocity
                        current_xy = [after_compute_xyh_statese2.x, after_compute_xyh_statese2.y]
                    
                    updated_states_for_bi = np.stack(updated_states_for_bi)
                    updated_xy = RuleController._rotate_points_along_z(
                        updated_states_for_bi[:, :2].reshape(1, -1, 2),
                        final_state[2].reshape(1)
                    ).reshape(-1, 2)
                    updated_xy = updated_xy + final_state[:2]
                    updated_h = updated_states_for_bi[:, 2] + final_state[2]
                    updated_h = (updated_h + np.pi) % (np.pi * 2) - np.pi
                    updated_vxy = RuleController._rotate_points_along_z(
                        updated_states_for_bi[:, 3:5].reshape(1, -1, 2),
                        final_state[2].reshape(1)
                    ).reshape(-1, 2)
                        
                    for sub_t in range(collision_check_forward_step - t):   
                        updated_state_timeseries.append(np.array([updated_xy[sub_t, 0], updated_xy[sub_t, 1], updated_h[sub_t], updated_vxy[sub_t, 0], updated_vxy[sub_t, 1]]))
                        rule_dict[vehicle_ids_last_step[bi]][t + sub_t, 0] = True  # stop
                    red_traffic_light_updated = True
                    break
                else:
                    final_state = state_t[:5]
                    updated_state_timeseries.append(final_state)
            timer_red += time.time() - timer_red_start
            
            use_guidance = True
            
            if use_guidance:
                timer_off_road_start = time.time()
                if red_traffic_light_updated or (not cur_lane in tl_ids and red_light) or stop_vehicle_bool[bi]:
                    off_road_future = False
                else:
                    off_road_future = off_road_batch[bi]
                
                timer_off_road += time.time() - timer_off_road_start
            
            else:
                off_road_future = False
            
            if (stop_vehicle_bool[bi] or off_road_future) and (not red_traffic_light_updated) and (not red_light or cur_lane in tl_ids) and (vehicle_ids_last_step[bi] not in static_vehicle_ids_set):
            # if ((green_light or cur_lane in tl_ids) and stop_vehicle_bool[bi]) or off_road_future:
                timer_launch_main_start = time.time()
                
                plan_state = _build_forward_path(bi, off_road_future=off_road_future)
                if plan_state is None:
                    updated_states.append(np.stack(updated_state_timeseries).reshape(collision_check_forward_step, 5))
                    continue
                
                updated_xy, updated_h, updated_vxy, route_end = plan_state
                output_state = np.column_stack([updated_xy, updated_h, updated_vxy])
                
                if off_road_future or route_end:
                    ego_state = vehicle_states_last_step[bi].copy()
                    ego_state[2] = wrap_to_pi(ego_state[2])
                    
                    center = ego_state[:2]
                    ego_yaw = ego_state[2]
                    
                    v0 = float(np.hypot(ego_state[3], ego_state[4]))
                    x_curr = np.array([0.0, 0.0, ego_yaw, v0], dtype=np.float32)
                    
                    ref = np.vstack((
                        np.array([[0.0, 0.0, ego_yaw]], dtype=np.float32),
                        np.column_stack([
                            updated_xy[:, :2] - center,
                            updated_h,
                        ]).astype(np.float32),
                    ))
                    ref[:, 2] = np.unwrap(ref[:, 2])
                    
                    timer_motion_smoother_start = time.time()
                    motion_smoother = _get_motion_smoother()
                    motion_smoother.set_reference_trajectory(x_curr, ref)
                    sol = motion_smoother.solve()
                    timer_motion_smoother += time.time() - timer_motion_smoother_start
                    
                    smoother = motion_smoother
                    traj_smoothed = np.stack(
                        [
                            sol.value(smoother.position_x), 
                            sol.value(smoother.position_y), 
                            sol.value(smoother.yaw), 
                            sol.value(smoother.speed) * np.cos(sol.value(smoother.yaw)), 
                            sol.value(smoother.speed) * np.sin(sol.value(smoother.yaw)),
                        ], 
                        axis=-1
                    )
                    traj_smoothed[:, 2] = wrap_to_pi(traj_smoothed[:, 2])
                    output_state = traj_smoothed[1:].reshape(-1, 5)
                    output_state[..., :2] = output_state[..., :2] + center
                    
                    rule_dict[vehicle_ids_last_step[bi]][:, 2] = True  # off road
                
                else:
                    rule_dict[vehicle_ids_last_step[bi]][:, 1] = True  # launch
                
                updated_states.append(output_state)
                timer_launch_main += time.time() - timer_launch_main_start
            
            else:
                updated_states.append(np.stack(updated_state_timeseries).reshape(collision_check_forward_step, 5))
        
        global_states = np.stack(updated_states).reshape(-1, collision_check_forward_step, 5)
        for index, external_states in controlled_global_states.items():
            horizon = min(global_states.shape[1], external_states.shape[0])
            dimensions = min(global_states.shape[2], external_states.shape[1])
            global_states[index, :horizon, :dimensions] = external_states[:horizon, :dimensions]
        
        accxaccy = (global_states[..., 1:, 3:5] - global_states[..., :-1, 3:5]) / simulation_interval
        accxaccy_first = (global_states[..., 0:1, 3:5] - np.concatenate(vehicle_states_last_step).reshape(-1, 1, 7)[..., 3:5]) / simulation_interval
        global_states = np.concatenate(
            [global_states, np.concatenate([accxaccy_first, accxaccy], axis=1)], axis=2
        )
        print(f"route match done, time: {timer_route}")
        print(f"red light control done, time: {timer_red}")
        print(f"off road check done, time: {timer_off_road}")
        print(f"launch main done, time: {timer_launch_main - timer_motion_smoother}")
        print(f"motion smoother done, time: {timer_motion_smoother}")
        print(f"traffic light control done, time: {time.time() - timer}\n")
        # '''
        # check vehicle on the end lanes or not        
        updated_vehicle_ids = [[] for _ in range(collision_check_forward_step)]
        updated_vehicle_states = [[] for _ in range(collision_check_forward_step)]
        for index, id in enumerate(vehicle_ids_last_step):
            # final_position = global_states[index, -1, :2]
            for t in range(collision_check_forward_step):
                updated_vehicle_ids[t].append(id)
                updated_vehicle_states[t].append(global_states[index, t])
        
        # Safety Layer
        use_safe = True        # reconstructed safety layer
        
        if use_safe:
            K = 8
            use_reverse_traj = True
            
            current_future_trajs = np.concatenate((vehicle_states_last_step[:, None, :3], global_states[:, :, :3]), axis=1)
            query_trajectory_batch = generate_trajectory_batch(current_future_trajs, K)[:, :, 1:, :]
            src_trajectory_batch = query_trajectory_batch[:, :, :nn_once_forward_step, :]
            
            time_start = time.time()
            region_list = cluster_trajectories(current_future_trajs, cluster_radius=8., down_sample_rate=4)
            print(f"cluster_trajectories time: {time.time() - time_start}")
            print(f"region_list: {region_list}")
            
            time_start = time.time()
            # adaptive adjustment of vehicle dimension
            static_vehicle_dim = np.array([
                [float(vehicle_static_attributes[vid][0]) * magnification + collision_threshold[0], float(vehicle_static_attributes[vid][1]) * magnification + collision_threshold[1]]
                for vid in vehicle_ids_last_step
            ])
            static_collision_matrix = build_collision_matrix(query_trajectory_batch[:, [-1]], region_list, static_vehicle_dim, collision_threshold=0.0)
            np.fill_diagonal(static_collision_matrix, 1)
            
            row_no_collision = static_collision_matrix.all(axis=1)
            col_no_collision = static_collision_matrix.all(axis=0)
            for idx, vid in enumerate(vehicle_ids_last_step):
                if row_no_collision[idx] and col_no_collision[idx]:
                    self.adaptive_vehicle_attr[vid] = static_vehicle_dim[idx]
                if vid not in self.adaptive_vehicle_attr:
                    self.adaptive_vehicle_attr[vid] = vehicle_static_attributes[vid][:2].astype(float) + collision_threshold * 0.1
            
            self.potential_deadlock_vehicle.intersection_update(vehicle_ids_last_step)
            to_unlock_vehicle = []
            for vid in self.potential_deadlock_vehicle:
                adaptive_vehicle_dim = self.adaptive_vehicle_attr[vid] - collision_threshold * 0.1
                min_vehicle_dim = vehicle_static_attributes[vid][:2].astype(float) + collision_threshold * 0.1
                self.adaptive_vehicle_attr[vid] = np.maximum(adaptive_vehicle_dim, min_vehicle_dim)
                for region in region_list:
                    if vehicle_ids_last_step.index(vid) in region:
                        v_idx = vehicle_ids_last_step.index(vid)
                        other_deadlock_idxs = [vehicle_ids_last_step.index(v) for v in self.potential_deadlock_vehicle if v != vid and vehicle_ids_last_step.index(v) in region]
                        if np.all(self.adaptive_vehicle_attr[vid] > min_vehicle_dim):
                            heading_diff = [
                                wrap_to_pi(vehicle_states_last_step[v_idx][2] - vehicle_states_last_step[other_idx][2])
                                for other_idx in other_deadlock_idxs
                            ]
                            if np.all(np.abs(heading_diff) < np.pi / 4):
                                to_unlock_vehicle.append(vid)
                        break
            
            self.potential_deadlock_vehicle.difference_update(to_unlock_vehicle)
            if to_unlock_vehicle:
                print(f"unlock vehicles from abnormal deadlock: {to_unlock_vehicle}")
            print(f"adjust vehicle dimension time: {time.time() - time_start}")
            
            time_start = time.time()
            vehicle_dimensions = np.array([self.adaptive_vehicle_attr[vid] for vid in vehicle_ids_last_step])
            collision_matrix = build_collision_matrix(query_trajectory_batch, region_list, vehicle_dimensions, collision_threshold=0.0)
            print(f"build_collision_matrix time: {time.time() - time_start}")
            
            time_start = time.time()
            
            valid_vid_priority_list = [vid for vid in self.vehicle_priority_record if vid in vehicle_ids_last_step]
            prev_priority_list = [vehicle_ids_last_step.index(vid) for vid in valid_vid_priority_list]
            
            fixed_modes = {index: 0 for index in controlled_indices}
            c, priority_list, deadlock_list = search_collision_free_modes(
                collision_matrix,
                region_list,
                K,
                priority_list=prev_priority_list,
                fixed_modes=fixed_modes,
            )
            deadlock_vid_list = [vehicle_ids_last_step[i] for i in deadlock_list if i not in fixed_modes]
            self.potential_deadlock_vehicle.update(deadlock_vid_list)
            
            self.deadlock_vehicle_dict = {v_id: t + simulation_interval * nn_once_forward_step for v_id, t in self.deadlock_vehicle_dict.items() if v_id in deadlock_vid_list}
            for vid in deadlock_vid_list:
                if vid not in self.deadlock_vehicle_dict:
                    self.deadlock_vehicle_dict[vid] = simulation_interval * nn_once_forward_step
            
            print(f"search_collision_free_modes time: {time.time() - time_start}")
            
            time_start = time.time()
            # maintain the priority order of vehicles in the potential deadlock
            locked = [v for v in prev_priority_list if vehicle_ids_last_step[v] in self.potential_deadlock_vehicle]
            priority_list = locked + [v for v in priority_list if v not in locked]
            
            self.vehicle_priority_record = [vehicle_ids_last_step[i] for i in priority_list]
            potential_deadlock_list = [vehicle_ids_last_step.index(vid) for vid in self.potential_deadlock_vehicle if self.deadlock_vehicle_dict.get(vid) != simulation_interval * nn_once_forward_step]
            
            if len(potential_deadlock_list) > 0 and use_reverse_traj:
                polys, bboxes = [], []
                for idx, vid in enumerate(vehicle_ids_last_step):
                    veh_state = global_states[idx][nn_once_forward_step]
                    x, y, h = veh_state[0], veh_state[1], veh_state[2]
                    L, W = float(vehicle_static_attributes[vid][0]) * magnification + collision_threshold[0], float(vehicle_static_attributes[vid][1]) * magnification + collision_threshold[1]
                    poly = _rect_poly(x, y, h, L, W)
                    
                    polys.append(poly)
                    bboxes.append(_bbox(poly))
                    
                global_rank = {v: i for i, v in enumerate(priority_list)}
                
                def _compute_reverse_traj_cached(idx: int):
                    traj = _build_reverse_traj(idx)
                    return idx, traj
                
                for region in region_list:
                    region_deadlock_list = [i for i in region if i in potential_deadlock_list]
                    if len(region_deadlock_list) == 0:
                        continue
                    deadlock_states = np.zeros((len(region), global_states.shape[1], 3), dtype=np.float64)
                    
                    reverse_traj_cache = {}
                    max_workers = min(len(region), os.cpu_count() // 2 or 1)
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = [executor.submit(_compute_reverse_traj_cached, idx) for idx in region]
                        for fut in futures:
                            vid_index, traj = fut.result()
                            reverse_traj_cache[vid_index] = traj
                    
                    region_sorted = sorted(region, key=lambda x: (x in region_deadlock_list, -global_rank[x]))
                    region_deadlock_list = [idx for idx in region_sorted if idx in region_deadlock_list]
                    anchor = region_sorted[-1]
                    
                    for i, vid_index in enumerate(region_sorted[:-1]):
                        deadlock_states[i] = reverse_traj_cache[vid_index]
                    plan_state = _build_forward_path(anchor, lead_veh=(15.0, 2.0), deadlock=True)
                    if plan_state is None:
                        deadlock_states[-1] = global_states[anchor][:, :3]
                    else:
                        updated_xy, updated_h, _, _ = plan_state
                        deadlock_states[-1] = np.column_stack([updated_xy, updated_h])
                    
                    anchor_polys, anchor_bboxes = [], []
                    anchor_L, anchor_W = self.adaptive_vehicle_attr[vehicle_ids_last_step[anchor]][0], self.adaptive_vehicle_attr[vehicle_ids_last_step[anchor]][1]
                    for time_step in (0, collision_check_forward_step - 1):
                        anchor_state = deadlock_states[-1][time_step]
                        x, y, h = anchor_state[0], anchor_state[1], anchor_state[2]
                        poly = _rect_poly(x, y, h, anchor_L, anchor_W)
                        
                        anchor_polys.append(poly)
                        anchor_bboxes.append(_bbox(poly))
                    
                    adjust_priority = True
                    
                    queue = deque(region_deadlock_list)
                    visited = []
                    while queue:
                        vid_index = queue.popleft()
                        if vid_index in visited:
                            continue
                        visited.append(vid_index)
                        
                        L_e = self.adaptive_vehicle_attr[vehicle_ids_last_step[vid_index]][0]
                        W_e = self.adaptive_vehicle_attr[vehicle_ids_last_step[vid_index]][1]
                        
                        other_polys = polys[:vid_index] + polys[vid_index+1:]
                        other_bboxes = bboxes[:vid_index] + bboxes[vid_index+1:]
                        other_vids = vehicle_ids_last_step[:vid_index] + vehicle_ids_last_step[vid_index+1:]
                        
                        back_index = []
                        for st in deadlock_states[region_sorted.index(vid_index)][[0, nn_once_forward_step-1, collision_check_forward_step-1]]:
                            x_e, y_e, h_e = st
                            ego_poly_k = _rect_poly(x_e, y_e, h_e, L_e, W_e)
                            ego_bbox_k = _bbox(ego_poly_k)
                            
                            for poly_o, bb_o, vid_o in zip(other_polys, other_bboxes, other_vids):
                                if not _aabb_hit(ego_bbox_k, bb_o):
                                    continue
                                if ego_poly_k.intersects(poly_o):
                                    block_index = vehicle_ids_last_step.index(vid_o)
                                    if block_index not in back_index and block_index != anchor and block_index in region_sorted:
                                        back_index.append(block_index)
                                    
                                    if vid_index == region_deadlock_list[0] and block_index == anchor and adjust_priority:
                                        collision_with_anchor = True
                                        for poly_a, bb_a in zip(anchor_polys, anchor_bboxes):
                                            if not _aabb_hit(ego_bbox_k, bb_a) or not ego_poly_k.intersects(poly_a):
                                                collision_with_anchor = False
                                                break
                                        
                                        if collision_with_anchor:
                                            vid_1 = vehicle_ids_last_step[anchor]
                                            vid_2 = vehicle_ids_last_step[vid_index]
                                            
                                            i, j = self.vehicle_priority_record.index(vid_1), self.vehicle_priority_record.index(vid_2)
                                            self.vehicle_priority_record[i], self.vehicle_priority_record[j] = self.vehicle_priority_record[j], self.vehicle_priority_record[i]
                                            adjust_priority = False
                                    
                                    break
                        
                        if len(back_index) > 0:
                            queue.extend(back_index)
                    
                    visited.remove(anchor)
                    if adjust_priority:
                        visited_vid = [vehicle_ids_last_step[i] for i in visited]
                        self.vehicle_priority_record = [vid for vid in self.vehicle_priority_record if vid not in visited_vid] + visited_vid
                    
                    visited.insert(0, anchor)                    
                    keep_index = [region_sorted.index(i) for i in region_sorted if i not in visited]
                    for i in keep_index:
                        deadlock_states[i] = global_states[region_sorted[i]][:, :3]
                    
                    sub_indices = region_sorted
                    deadlock_future_trajs = np.concatenate((vehicle_states_last_step[np.array(sub_indices), None, :3], deadlock_states), axis=1)
                    sub_dims = np.array([
                        [self.adaptive_vehicle_attr[vehicle_ids_last_step[idx]][0], 
                         self.adaptive_vehicle_attr[vehicle_ids_last_step[idx]][1]]
                        for idx in sub_indices
                    ])
                    sub_region_list = [list(range(len(sub_indices)))]
                    sub_priority = [region_sorted.index(idx) for idx in visited][::-1] + keep_index[::-1]
                    
                    sub_query_trajectory_batch = generate_trajectory_batch(deadlock_future_trajs, K)[:, :, 1:, :]
                    sub_collision_matrix = build_collision_matrix(
                        sub_query_trajectory_batch,
                        sub_region_list,
                        sub_dims,
                        collision_threshold=0.0
                    )
                    sub_fixed_modes = {
                        local_index: 0
                        for local_index, global_index in enumerate(sub_indices)
                        if global_index in controlled_indices
                    }
                    sub_c, _, _ = search_collision_free_modes(
                        sub_collision_matrix,
                        sub_region_list,
                        K,
                        priority_list=sub_priority,
                        preset_priority=True,
                        fixed_modes=sub_fixed_modes,
                    )
                    
                    for local_i, mode in enumerate(sub_c):
                        global_i = sub_indices[local_i]
                        c[global_i] = mode
                        src_trajectory_batch[global_i, :, :nn_once_forward_step, :] = sub_query_trajectory_batch[local_i, :, :nn_once_forward_step, :]
            
                    # build regional blocking matrix of vehicles in the potential deadlock
                    unlock_states = np.zeros((len(region_deadlock_list), global_states.shape[1], 3), dtype=np.float64)
                    for i, vid_index in enumerate(region_deadlock_list):
                        plan_state = _build_forward_path(vid_index, lead_veh=(15.0, 2.0), deadlock=True)
                        if plan_state is None:
                            unlock_states[i] = global_states[vid_index][:, :3]
                        else:
                            updated_xy, updated_h, _, _ = plan_state
                            unlock_states[i] = np.column_stack([updated_xy, updated_h])
                    
                    unlock_future_trajs = np.concatenate((vehicle_states_last_step[np.array(region_deadlock_list), None, :3], unlock_states), axis=1)
                    unlock_dims = np.array([
                        [self.adaptive_vehicle_attr[vehicle_ids_last_step[idx]][0],
                         self.adaptive_vehicle_attr[vehicle_ids_last_step[idx]][1]]
                        for idx in region_deadlock_list
                    ])
                    unlock_query_trajectory_batch = generate_trajectory_batch(unlock_future_trajs, 2)[:, :, 1:, :]
                    unlock_collision_matrix = build_collision_matrix(
                        unlock_query_trajectory_batch,
                        [list(range(len(region_deadlock_list)))],
                        unlock_dims,
                        collision_threshold=0.0
                    )
                    deadlock_blocking_matrix = 1 - unlock_collision_matrix[1::2, 0::2]
                    np.fill_diagonal(deadlock_blocking_matrix, 0)
                    
                    # remove vehicles not blocking others from the potential deadlock
                    region_deadlock_vid = [vehicle_ids_last_step[idx] for idx in region_deadlock_list]
                    row_has_block = deadlock_blocking_matrix.any(axis=1)
                    col_has_block = deadlock_blocking_matrix.any(axis=0)
                    to_unlock_vehicle = [
                        vid for vid, idx in zip(region_deadlock_vid, range(len(region_deadlock_list)))
                        if (not row_has_block[idx]) and (not col_has_block[idx])
                    ]
                    # if len(to_unlock_vehicle) == len(region_deadlock_list):
                    self.potential_deadlock_vehicle.difference_update(to_unlock_vehicle)
            
            print(f"unlock time: {time.time() - time_start}")
            
            for index in controlled_indices:
                c[index] = 0
            states = src_trajectory_batch[np.arange(len(src_trajectory_batch)), c]
        
            collision_id = np.array(vehicle_ids_last_step)[np.array(c) != 0]
            for vid in collision_id:
                rule_dict[vid][:, 3] = True  # safety layer
        
        # motion_smoother_start = MotionNonlinearSmoother(nn_once_forward_step, simulation_interval)
        # distance = np.linalg.norm(states[:, 0, :2] - np.concatenate(vehicle_states_last_step).reshape(-1, 7)[:, :2], axis=-1)
        # for idx, d in enumerate(distance):
        #     if d > 0.5:
        #         center = vehicle_states_last_step[idx][:2]
        #         x_curr = np.concatenate(
        #             [
        #                 np.array([0.]).reshape(1, 1),
        #                 np.array([0.]).reshape(1, 1),
        #                 vehicle_states_last_step[idx][2:3].reshape(1, 1),
        #                 np.sqrt(vehicle_states_last_step[idx][..., 3:4] ** 2 + vehicle_states_last_step[idx][..., 4:5] ** 2).reshape(1, 1),
        #             ], axis=1
        #         )[0]
        #         ref = np.concatenate([vehicle_states_last_step[idx][:3].reshape(1, 3), states[idx, :, :3].reshape(nn_once_forward_step, 3)]).reshape(nn_once_forward_step + 1, 3)
        #         ref[:, :2] = ref[:, :2] - center
        #         # print(ref)
        #         reference_traj = ref.reshape(nn_once_forward_step + 1, 3)
        #         motion_smoother_start.set_reference_trajectory(x_curr, reference_traj)
        #         sol = motion_smoother_start.solve()
        #         smoother = motion_smoother_start
        #         traj_smoothed = np.stack(
        #             [sol.value(smoother.position_x), sol.value(smoother.position_y), sol.value(smoother.yaw), sol.value(smoother.speed) * np.cos(sol.value(smoother.yaw)), sol.value(smoother.speed) * np.sin(sol.value(smoother.yaw))], axis=-1)
        #         output_state = traj_smoothed[1:].reshape(-1, 5)
        #         output_state[..., :2] = output_state[..., :2] + center
        #         states[idx, :, :5] = output_state
        
        if not use_safe:
            states = global_states[..., :3]
        
        for i in range(states.shape[0]):
            for t in range(nn_once_forward_step):
                updated_vehicle_states[t][i][:3] = states[i, t]
                if t > 0:
                    updated_vehicle_states[t][i][3:5] = (updated_vehicle_states[t][i][0:2] - updated_vehicle_states[t - 1][i][0:2]) / 0.1
                    updated_vehicle_states[t][i][5:7] = (updated_vehicle_states[t][i][3:5] - updated_vehicle_states[t - 1][i][3:5]).clip(-0.4, 0.4) / 0.1
                else:
                    updated_vehicle_states[t][i][3:5] = (updated_vehicle_states[t][i][0:2] - vehicle_states_last_step[i][0:2]) / 0.1
                    updated_vehicle_states[t][i][5:7] = (updated_vehicle_states[t][i][3:5] - vehicle_states_last_step[i][3:5]).clip(-0.4, 0.4) / 0.1

        updated_vehicle_states = [np.vstack(states) for states in updated_vehicle_states]
        vehicle_id, vehicle_states, vehicle_mask = sparse2dense(updated_vehicle_ids[:nn_once_forward_step], updated_vehicle_states[:nn_once_forward_step])
        rule_dict = {vid: rule_dict[vid][:nn_once_forward_step] for vid in vehicle_id}
        assert np.all(vehicle_mask), "invalid vehicle occurs in after_step"
        return {"vehicle_id": vehicle_id,
                "vehicle_states": vehicle_states,
                "deadlock_vehicle_id": self.get_deadlocks(),
                "rule_dict": rule_dict}
        
if __name__ == "__main__":
    print("import success")
