from __future__ import annotations

import random

import numpy as np
import matplotlib.pyplot as plt
from typing import List, Tuple, Dict
if not __package__:
    from trajectory_to_region import trajectory_to_region
    from trajectory_to_region_simple import cluster_trajectories
    from collision_matrix_graph import build_collision_matrix, VehiclePriorityGraph
    from collision_matrix_graph import *
    from trajectory_to_batch import generate_trajectory_batch
else:
    from .trajectory_to_region import trajectory_to_region
    from .trajectory_to_region_simple import cluster_trajectories
    from .collision_matrix_graph import build_collision_matrix, VehiclePriorityGraph
    from .collision_matrix_graph import *
    from .trajectory_to_batch import generate_trajectory_batch

# Ensure matplotlib backend is set properly
plt.switch_backend('Agg')  # Use non-interactive backend

import torch
import torch.nn.functional as F
from typing import Tuple, Optional, Union, Callable
from functools import partial
import time


import numpy as np

def check_trajectory_collision(traj1, traj2, width1, width2, length1, length2):
    """
    Check if two trajectories will collide considering vehicle dimensions.
    
    Returns:
    --------
    dict
        'collides': bool - whether collision occurs
        'time': int - time step of first collision
        'distance': float - distance to collision point from traj1 start
    """
    T = traj1.shape[0]
    
    # Combined width for collision detection
    combined_width = (width1 + width2) / 2
    combined_length = (length1 + length2) / 2
    
    for t in range(T):
        pos1 = traj1[t]
        pos2 = traj2[t]
        
        # Simple distance check (can be made more sophisticated)
        dist = np.linalg.norm(pos1 - pos2)
        
        # Check if vehicles overlap at this time step
        if dist < combined_width:
            # Calculate distance along trajectory to collision point
            if t > 0:
                dist_to_collision = np.sum([
                    np.linalg.norm(traj1[i+1] - traj1[i]) 
                    for i in range(t)
                ])
            else:
                dist_to_collision = 0
                
            return {
                'collides': True,
                'time': t,
                'distance': dist_to_collision
            }
    
    return {
        'collides': False,
        'time': -1,
        'distance': float('inf')
    }



def test_solve_collision():
    """
    Test the collision matrix generation with sample data.
    """
    print("Testing collision matrix generation...")
    
    # Create sample trajectory batch
    N = 8  # Number of vehicles (increased from 4)
    K = 20  # Number of trajectory variants per vehicle (increased from 3)
    T = 25  # Number of time steps (increased for more complex trajectories)
    
    # Generate trajectory batch using the trajectory_to_batch function
    
    
    # Create base trajectories for 8 vehicles with 3 distinct regions
    base_trajectories = np.zeros((N, T, 3))
    t = np.linspace(0, 15, T)
    
    # Region 1: Vehicles 0, 1, 2 - Intersection area
    # Vehicle 0: Straight line (horizontal)
    base_trajectories[0, :, 0] = t
    base_trajectories[0, :, 1] = 0
    base_trajectories[0, :, 2] = 0
    
    # Vehicle 1: Parallel line (close to vehicle 0)
    base_trajectories[1, :, 0] = t
    base_trajectories[1, :, 1] = 3.8  # Close to vehicle 0
    base_trajectories[1, :, 2] = 0
    
    # Vehicle 2: Crossing trajectory (vertical)
    base_trajectories[2, :, 0] = 7.5
    base_trajectories[2, :, 1] = t - 7.5
    base_trajectories[2, :, 2] = np.pi/2
    
    # Region 2: Vehicles 3, 4, 5 - Curved path area
    # Vehicle 3: Circular arc
    theta = np.linspace(0, np.pi, T)
    base_trajectories[3, :, 0] = 20 + 5 * np.cos(theta)
    base_trajectories[3, :, 1] = 5 + 5 * np.sin(theta)
    base_trajectories[3, :, 2] = theta + np.pi/2
    
    # Vehicle 4: Parallel circular arc
    base_trajectories[4, :, 0] = 20 + 8 * np.cos(theta)
    base_trajectories[4, :, 1] = 5 + 8 * np.sin(theta)
    base_trajectories[4, :, 2] = theta + np.pi/2
    
    # Vehicle 5: Tangent to circular path
    base_trajectories[5, :, 0] = 15 + t/2
    base_trajectories[5, :, 1] = 2 + t/3
    base_trajectories[5, :, 2] = np.pi/6
    
    # Region 3: Vehicles 6, 7 - Highway merge area
    # Vehicle 6: Main highway lane
    base_trajectories[6, :, 0] = t
    base_trajectories[6, :, 1] = 15
    base_trajectories[6, :, 2] = 0
    
    # Vehicle 7: Merging from on-ramp
    base_trajectories[7, :, 0] = 5 + t * 0.8
    base_trajectories[7, :, 1] = 12 + t * 0.3
    base_trajectories[7, :, 2] = np.arctan2(0.3, 0.8)
    
    # Generate trajectory batch
    time_start = time.time()
    trajectory_batch = generate_trajectory_batch(base_trajectories, K)
    print(f"Trajectory batch shape: {trajectory_batch.shape}")
    print(f"Trajectory batch generation time: {time.time() - time_start} seconds")
    
    # Get region list using trajectory_to_region with adjusted parameters to ensure 3 regions
    region_list = cluster_trajectories(base_trajectories, cluster_radius=4.)
    print(f"Region list: {region_list}")
    print(f"Region list generation time: {time.time() - time_start} seconds")
    
    # Ensure we have exactly 3 regions by manually adjusting if needed
    # if len(region_list) != 3:
    #     print(f"Warning: Expected 3 regions, got {len(region_list)}. Manually creating 3 regions...")
    #     region_list = [
    #         [0, 1, 2],  # Region 1: Intersection area
    #         [3, 4, 5],  # Region 2: Curved path area  
    #         [6, 7]      # Region 3: Highway merge area
    #     ]
    #     print(f"Manual region list: {region_list}")
    
    # Define vehicle dimensions [length, width] for 8 vehicles
    vehicle_dimensions = np.array([
        [4.5, 2.0],  # Vehicle 0: sedan
        [4.5, 2.0],  # Vehicle 1: sedan
        [5.0, 2.2],  # Vehicle 2: SUV
        [4.0, 1.8],  # Vehicle 3: compact
        [4.8, 2.1],  # Vehicle 4: mid-size sedan
        [5.2, 2.3],  # Vehicle 5: large SUV
        [4.6, 2.0],  # Vehicle 6: sedan
        [4.3, 1.9],  # Vehicle 7: compact
    ])
    
    collision_matrix = build_collision_matrix(
            trajectory_batch, region_list, vehicle_dimensions, collision_threshold=0.5
        )
    print(f"Collision matrix generation time: {time.time() - time_start} seconds")
    
    # visualize_trajectories_with_collisions(
    #     trajectory_batch, collision_matrix, vehicle_dimensions, N, K,
    #     save_path="trajectory_collisions_test.png"
    # )
    # print(f"Trajectory visualization time: {time.time() - time_start} seconds")
    
    # # Visualize each collision matrix individually
    # visualize_collision_matrix(
    #      collision_matrix, N, K, save_path=f"collision_matrix_solving_original_test.png"
    # )
    # print(f"Collision matrix visualization time: {time.time() - time_start} seconds")
    
    selected_modes, all_priority_list = search_collision_free_modes(collision_matrix, region_list, K, priority_list=[7, 6, 5, 4, 3, 2, 1, 0])
    print(f"Selected modes: {selected_modes}")
    print(f"All priority list: {all_priority_list}")
    trajectory_batch_selected = trajectory_batch[np.arange(N), selected_modes]
    print(f"Trajectory batch selected time: {time.time() - time_start} seconds")
    
    # visualize_trajectories_with_collisions(
    #     trajectory_batch_selected[:, None], collision_matrix, vehicle_dimensions, N, 1,
    #     save_path="trajectory_collisions_selected_test.png"
    # )
    print(f"Trajectory batch selected visualization time: {time.time() - time_start} seconds")

def search_collision_free_modes(collision_matrix: np.ndarray, region_list: list[list[int]], K: int,
                                approximate_solution_time: float=1, priority_list: list | None = None,
                                preset_priority=False, fixed_modes: dict[int, int] | None = None):
    """
    Search for collision-free modes in the order provided by priority_list.

    Args:
        collision_matrix (np.ndarray): Collision matrix of shape (N*K, N*K)
        region_list (list): List of vehicles in each region
        K (int): Number of trajectories per vehicle
        approximate_solution_time (float, optional): Time limit for approximate solution. Defaults to 1.
        priority_list (list | None, optional): Priority list for vehicles. Defaults to None.
        fixed_modes: Global vehicle index to trajectory mode. Fixed vehicles participate in
            collision checks but the solver is not allowed to alter their trajectory.

    Returns:
        list: Selected modes for each vehicle
        list: Priority lists for all vehicles
        list: Deadlock list for all vehicles
    """
    assert collision_matrix.shape[0] % K == 0, "Error: collision matrix shape is not divisible by K"
    fixed_modes = {
        int(vehicle_index): max(0, min(K - 1, int(mode)))
        for vehicle_index, mode in (fixed_modes or {}).items()
    }
    search_collision_free_modes.last_used_approximate = False
    all_selected_modes = [None] * (collision_matrix.shape[0] // K)
    all_priority_list = []
    all_deadlock_list = []
    for vehicle_in_region in region_list:
        sub_collision_matrix = np.zeros((len(vehicle_in_region) * K, len(vehicle_in_region) * K))
        for i in range(len(vehicle_in_region)):
            for j in range(len(vehicle_in_region)):
                sub_collision_matrix[i * K:(i + 1) * K, j * K:(j + 1) * K] = collision_matrix[vehicle_in_region[i] * K:(vehicle_in_region[i] + 1) * K, vehicle_in_region[j] * K:(vehicle_in_region[j] + 1) * K]
        # print(f"Sub collision matrix shape: {sub_collision_matrix.shape} ({len(vehicle_in_region)} vehicles, {K} modes)")
        
        if priority_list:
            local_priority_list = [vehicle_in_region.index(glb_idx) for glb_idx in priority_list if glb_idx in vehicle_in_region]
        else:
            local_priority_list = None
        
        # get vehicle priority
        vehicle_priority_graph = VehiclePriorityGraph(sub_collision_matrix, K)
        # print(f"Vehicle priority graph: {vehicle_priority_graph.get_edgelist()}")
        vehicle_priority_graph.build_DAG_graph(local_priority_list)
        next_priority_list = vehicle_priority_graph.topological_sort_with_priority(local_priority_list) if not preset_priority else local_priority_list
        # External AV trajectories are immutable. Visit them first so the fallback can
        # always preserve their fixed mode and yield conflicting background vehicles.
        fixed_local = [
            local_index
            for local_index, global_index in enumerate(vehicle_in_region)
            if global_index in fixed_modes
        ]
        next_priority_list = fixed_local + [index for index in next_priority_list if index not in fixed_local]
        # print(f"Priority list: {priority_list}")
        priority_vehicle_idx = [vehicle_in_region[p] for p in next_priority_list]
        all_priority_list.append(priority_vehicle_idx)
        deadlock_idx = list(vehicle_priority_graph.get_deadlock_vertices())
        all_deadlock_list.extend([vehicle_in_region[d] for d in deadlock_idx])
        def check_safe(center, other):
            return np.all(sub_collision_matrix[center, other])
        
        def check_time(start_time, max_time):
            return time.time() - start_time <= max_time
        
        def backtracking_search(visiting: int, visited: list, to_visit: list, selected_modes: list, runtime_checker: Callable = lambda: True):
            '''
            Searching for a combination of collision-free modes in the order provided by to_visit list.
            return 1 if found a solution, 0 if not found, -1 if timeout
            '''
            if not runtime_checker():
                return -1
            assert visiting not in visited, "Error: visiting visited vehicle"
            visited.append(visiting)
            next_visit = to_visit.pop(0) if len(to_visit) > 0 else None
            global_visiting = vehicle_in_region[visiting]
            candidate_modes = (
                [fixed_modes[global_visiting]]
                if global_visiting in fixed_modes
                else (range(K) if visiting not in deadlock_idx else [K - 1])
            )
            for sub_i in candidate_modes:
                if check_safe(visiting * K + sub_i, selected_modes):
                    selected_modes.append(visiting * K + sub_i)
                    if next_visit is None:
                        return True
                    else:
                        res = backtracking_search(next_visit, visited, to_visit, selected_modes, runtime_checker)
                        if res == 0:
                            selected_modes.pop(-1)
                            continue
                        else:
                            return res
            visited.pop(-1)
            to_visit.insert(0, next_visit)
            return 0
        
        sub_selected_modes = []
        res = backtracking_search(next_priority_list[0], [], next_priority_list[1:], sub_selected_modes, partial(check_time, time.time(), approximate_solution_time))
        if res == 1:
            pass
            # print(f"Found optimal solution")
        else:
            if res == 0:
                print(f"No solution found, switch to approximate solution")
            else:
                print(f"Search timeout, switch to approximate solution")
            search_collision_free_modes.last_used_approximate = True
            search_collision_free_modes.approximate_fallback_count = (
                getattr(search_collision_free_modes, "approximate_fallback_count", 0) + 1
            )
            sub_selected_modes = [priority_id*K + K - 1 for priority_id in next_priority_list]
            def approximate_search(visiting: int, visited: list, to_visit: list, selected_modes: list):
                '''
                Searching for an approximate solution of collision-free modes in the order provided by to_visit list.
                '''
                assert visiting not in visited, "Error: visiting visited vehicle"
                visiting_index = len(visited)
                visited.append(visiting)
                next_visit = to_visit.pop(0) if len(to_visit) > 0 else None
                global_visiting = vehicle_in_region[visiting]
                candidate_modes = (
                    [fixed_modes[global_visiting]]
                    if global_visiting in fixed_modes
                    else (range(K) if visiting not in deadlock_idx else [K - 1])
                )
                for sub_i in candidate_modes:
                    if (
                        global_visiting in fixed_modes
                        or check_safe(
                            visiting * K + sub_i,
                            selected_modes[:visiting_index] + selected_modes[visiting_index + 1:],
                        )
                        or sub_i == K - 1
                    ):
                        selected_modes[visiting_index] = visiting * K + sub_i
                        if next_visit is None:
                            return
                        else:
                            approximate_search(next_visit, visited, to_visit, selected_modes)
                            return
                else:
                    raise RuntimeError
            approximate_search(next_priority_list[0], [], next_priority_list[1:], sub_selected_modes)
                
        assert len(sub_selected_modes) == len(vehicle_in_region)
        for v_idx, mode in zip(priority_vehicle_idx, sub_selected_modes):
            all_selected_modes[v_idx] = mode % K
    assert None not in all_selected_modes, "Error: selected modes contain None"
    random.shuffle(all_priority_list)
    all_priority_list = [p for sub_priority_list in all_priority_list for p in sub_priority_list]
    return all_selected_modes, all_priority_list, all_deadlock_list

def test_backtracking_search():
    def check_safe(center, other):
            return np.all(sub_collision_matrix[center, other])
        
    def check_time(start_time, max_time):
        return time.time() - start_time <= max_time
    
    def backtracking_search(visiting: int, visited: list, to_visit: list, selected_modes: list, runtime_checker: Callable = lambda: True):
        '''
        Searching for a combination of collision-free modes in the order provided by to_visit list.
        return 1 if found a solution, 0 if not found, -1 if timeout
        '''
        if not runtime_checker():
            return -1
        assert visiting not in visited, "Error: visiting visited vehicle"
        visited.append(visiting)
        next_visit = to_visit.pop(0) if len(to_visit) > 0 else None
        for sub_i in range(K):
            if check_safe(visiting * K + sub_i, selected_modes):
                selected_modes.append(visiting * K + sub_i)
                if next_visit is None:
                    return True
                else:
                    res = backtracking_search(next_visit, visited, to_visit, selected_modes, runtime_checker)
                    if res == 0:
                        selected_modes.pop(-1)
                        continue
                    else:
                        return res
        visited.pop(-1)
        to_visit.insert(0, next_visit)
        return 0
    sub_collision_matrix = np.load("sub_collision_matrix.npy")
    priority_list = np.load("priority_list.npy").tolist()
    K = sub_collision_matrix.shape[0] // len(priority_list)
    sub_sub_collision_matrix = sub_collision_matrix[::K, ::K]
    print(f"{sub_sub_collision_matrix}")
    selected_modes = []
    res = backtracking_search(priority_list[0], [], priority_list[1:], selected_modes)
    print(f"Result: {res}")
    print(selected_modes)

if __name__ == "__main__":
    test_solve_collision()
