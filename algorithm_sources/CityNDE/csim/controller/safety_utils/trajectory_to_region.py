import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Tuple, Set
from collections import defaultdict


class TrajectoryRegionAnalyzer:
    """
    Analyzes vehicle trajectories to identify vehicles that share spatial regions.
    Based on the RegionMerger class from simulator_core.py
    """
    
    def __init__(self, trajectories: np.ndarray, collision_regions_x: int = 10, collision_regions_y: int = 10, radius: float = 5.0):
        """
        Initialize the trajectory region analyzer.
        
        Args:
            trajectories: Array of shape (N, T, 3) where last dimension is (x, y, heading)
            collision_regions_x: Number of grid regions in x direction
            collision_regions_y: Number of grid regions in y direction
            radius: Radius in meters to consider around each vehicle position
        """
        self.trajectories = trajectories
        self.N, self.T, _ = trajectories.shape
        self.collision_regions_x = collision_regions_x
        self.collision_regions_y = collision_regions_y
        self.radius = radius
        
        # Extract positions (x, y) from trajectories
        self.position_all_vehicles = trajectories[:, :, :2]  # Shape: (N, T, 2)
        
        # Calculate grid bounds
        all_positions = self.position_all_vehicles.reshape(-1, 2)
        self.x_min, self.x_max = np.min(all_positions[:, 0]), np.max(all_positions[:, 0])
        self.y_min, self.y_max = np.min(all_positions[:, 1]), np.max(all_positions[:, 1])
        
        # Add small padding to avoid edge cases
        padding = 0.01 * max(self.x_max - self.x_min, self.y_max - self.y_min)
        self.x_min -= padding
        self.x_max += padding
        self.y_min -= padding
        self.y_max += padding
        
        # Calculate grid cell sizes
        self.dx = (self.x_max - self.x_min) / self.collision_regions_x
        self.dy = (self.y_max - self.y_min) / self.collision_regions_y
        
        # Get radius-based grid cells for each vehicle
        self.vehicle_grid_cells = self._get_radius_based_grid_cells(self.position_all_vehicles, radius)
        
        # Initialize Union-Find data structure
        self.parent = np.arange(self.collision_regions_x * self.collision_regions_y)
        
        # Analyze vehicle movement based on number of unique cells each vehicle occupies
        self.unique_grid_counts = np.array([len(cells) for cells in self.vehicle_grid_cells])
        self.moving_vehicles = self.unique_grid_counts > 1
    
    def _positions_to_grid_indices(self, positions: np.ndarray, radius: float = 5.0) -> np.ndarray:
        """
        Convert vehicle positions to grid indices, considering a radius around each position.
        A vehicle is considered to be in a region if any point of its trajectory is within
        the specified radius of that region.
        
        Args:
            positions: Array of shape (N, T, 2) containing (x, y) positions
            radius: Radius in meters to consider around each position
            
        Returns:
            Array of shape (N, T, 2) containing grid indices (i, j)
        """
        # Normalize positions to grid coordinates
        normalized_pos = (positions - [self.x_min, self.y_min]) / [self.dx, self.dy]
        
        # Convert to grid indices
        grid_indices = np.floor(normalized_pos).astype(int)
        
        # Clip to valid grid range
        grid_indices = np.clip(grid_indices, 0, [self.collision_regions_x - 1, self.collision_regions_y - 1])
        
        return grid_indices
    
    def _get_radius_based_grid_cells(self, positions: np.ndarray, radius: float = 5.0) -> List[Set[Tuple[int, int]]]:
        """
        Get all grid cells within radius of each trajectory point.
        
        Args:
            positions: Array of shape (N, T, 2) containing (x, y) positions
            radius: Radius in meters to consider around each position
            
        Returns:
            List of sets, where each set contains all grid cells (i, j) that the vehicle
            is considered to be in based on the radius
        """
        # Convert radius to grid units
        radius_x = radius / self.dx
        radius_y = radius / self.dy
        
        vehicle_grid_cells = []
        
        for car_id in range(positions.shape[0]):
            car_cells = set()
            
            for t in range(positions.shape[1]):
                x, y = positions[car_id, t]
                
                # Convert to grid coordinates
                grid_x = (x - self.x_min) / self.dx
                grid_y = (y - self.y_min) / self.dy
                
                # Find all grid cells within radius
                min_i = max(0, int(np.floor(grid_x - radius_x)))
                max_i = min(self.collision_regions_x - 1, int(np.ceil(grid_x + radius_x)))
                min_j = max(0, int(np.floor(grid_y - radius_y)))
                max_j = min(self.collision_regions_y - 1, int(np.ceil(grid_y + radius_y)))
                
                for i in range(min_i, max_i + 1):
                    for j in range(min_j, max_j + 1):
                        # Calculate distance from trajectory point to grid cell center
                        cell_center_x = self.x_min + (i + 0.5) * self.dx
                        cell_center_y = self.y_min + (j + 0.5) * self.dy
                        
                        distance = np.sqrt((x - cell_center_x)**2 + (y - cell_center_y)**2)
                        
                        if distance <= radius:
                            car_cells.add((i, j))
            
            vehicle_grid_cells.append(car_cells)
        
        return vehicle_grid_cells
    
    def find(self, x: int) -> int:
        """Find root of element x in Union-Find structure."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def union(self, x: int, y: int):
        """Union two elements in Union-Find structure."""
        root_x = self.find(x)
        root_y = self.find(y)
        if root_x != root_y:
            self.parent[root_y] = root_x
    
    def merge_regions(self):
        """
        Merge adjacent grid regions that contain the same vehicles.
        Uses Union-Find to group connected regions.
        Performs iterative merging until no new merges are found.
        """
        # Create mapping from grid cells to vehicles that pass through them
        grid_dict = {}
        for car_id, car_cells in enumerate(self.vehicle_grid_cells):
            for grid_cell in car_cells:
                if grid_cell not in grid_dict:
                    grid_dict[grid_cell] = set()
                grid_dict[grid_cell].add(car_id)
        
        # Iterative merging until no new merges are found
        iteration = 0
        while True:
            iteration += 1
            merges_found = 0
            
            # Check all pairs of adjacent cells for merging
            for (i, j), vehicles in grid_dict.items():
                # Check 4-connected neighbors
                for di, dj in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    ni, nj = i + di, j + dj
                    neighbor_cell = (ni, nj)
                    
                    # Check if neighbor exists and shares vehicles with current cell
                    if (neighbor_cell in grid_dict and 
                        not vehicles.isdisjoint(grid_dict[neighbor_cell])):
                        
                        current_idx = i * self.collision_regions_y + j
                        neighbor_idx = ni * self.collision_regions_y + nj
                        
                        # Check if they're not already in the same group
                        if self.find(current_idx) != self.find(neighbor_idx):
                            self.union(current_idx, neighbor_idx)
                            merges_found += 1
            
            # If no merges were found in this iteration, we're done
            if merges_found == 0:
                break
                
            print(f'Iteration {iteration}: {merges_found} merges found')
        
        print(f'Region merging completed after {iteration} iterations. {self.collision_regions_x * self.collision_regions_y} cells processed.')
    
    def get_merged_regions(self) -> Dict[int, List[Tuple[int, int]]]:
        """
        Get all merged regions after union-find operations.
        
        Returns:
            Dictionary mapping root_id to list of grid cells in that region
        """
        merged_regions = {}
        for i in range(self.collision_regions_x):
            for j in range(self.collision_regions_y):
                root = self.find(i * self.collision_regions_y + j)
                if root not in merged_regions:
                    merged_regions[root] = []
                merged_regions[root].append((i, j))
        return merged_regions
    
    def get_vehicles_in_same_regions(self) -> Dict[Tuple, List[int]]:
        """
        Get vehicles that are in the same merged regions.
        
        Returns:
            Dictionary mapping region_id to list of vehicle indices in that region
        """
        merged_regions = self.get_merged_regions()
        vehicles_in_regions = {}
        
        for root, cells in merged_regions.items():
            region_id = tuple(sorted(cells))
            vehicles_in_regions[region_id] = []
            
            # Find all vehicles that pass through any cell in this region
            for car_id, car_cells in enumerate(self.vehicle_grid_cells):
                if any(cell in cells for cell in car_cells):
                    vehicles_in_regions[region_id].append(car_id)
        
        return vehicles_in_regions
    
    def count_vehicles_per_region(self) -> Dict[Tuple, int]:
        """
        Count number of vehicles in each merged region.
        
        Returns:
            Dictionary mapping region_id to vehicle count
        """
        merged_regions = self.get_merged_regions()
        region_counts = {}
        
        for root, cells in merged_regions.items():
            region_id = tuple(sorted(cells))
            region_counts[region_id] = 0
            
            # Count vehicles that pass through any cell in this region
            for car_id, car_cells in enumerate(self.vehicle_grid_cells):
                if any(cell in cells for cell in car_cells):
                    region_counts[region_id] += 1
        
        return region_counts
    
    def get_vehicle_relationships(self) -> List[List[int]]:
        """
        Get list of vehicle groups that share regions.
        
        Returns:
            List of lists, where each inner list contains vehicle indices that share regions
        """
        vehicles_in_regions = self.get_vehicles_in_same_regions()
        
        # Create a mapping from vehicle to all regions it belongs to
        vehicle_to_regions = defaultdict(set)
        for region_id, vehicles in vehicles_in_regions.items():
            for vehicle_id in vehicles:
                vehicle_to_regions[vehicle_id].add(region_id)
        
        # Group vehicles that share at least one region
        vehicle_groups = []
        processed_vehicles = set()
        
        for vehicle_id in range(self.N):
            if vehicle_id in processed_vehicles:
                continue
                
            # Find all vehicles that share regions with this vehicle
            current_group = {vehicle_id}
            to_process = [vehicle_id]
            
            while to_process:
                current_vehicle = to_process.pop()
                if current_vehicle in processed_vehicles:
                    continue
                    
                processed_vehicles.add(current_vehicle)
                
                # Find all other vehicles that share regions with current vehicle
                for other_vehicle in range(self.N):
                    if (other_vehicle != current_vehicle and 
                        other_vehicle not in processed_vehicles and
                        not vehicle_to_regions[current_vehicle].isdisjoint(vehicle_to_regions[other_vehicle])):
                        current_group.add(other_vehicle)
                        to_process.append(other_vehicle)
            
            # Convert set to sorted list and include all groups (even single vehicles)
            vehicle_groups.append(sorted(list(current_group)))
        
        return vehicle_groups
    
    def visualize_regions(self, save_path: str = None, show_grid: bool = True):
        """
        Visualize the trajectory regions and vehicle relationships.
        
        Args:
            save_path: Path to save the plot. If None, uses default naming.
            show_grid: Whether to show the grid overlay
        """
        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Get vehicle relationships for consistent coloring
        vehicle_groups = self.get_vehicle_relationships()
        
        # Assign colors to groups
        group_colors = plt.cm.tab20(np.linspace(0, 1, len(vehicle_groups)))
        vehicle_colors = {}
        
        for group_idx, group in enumerate(vehicle_groups):
            color = group_colors[group_idx]
            for vehicle_id in group:
                vehicle_colors[vehicle_id] = color
        
        # Plot trajectories with group-based colors
        for i in range(self.N):
            trajectory = self.trajectories[i]
            x_coords = trajectory[:, 0]
            y_coords = trajectory[:, 1]
            color = vehicle_colors[i]
            ax.plot(x_coords, y_coords, color=color, linewidth=2, alpha=0.7, label=f'Vehicle {i}')
            ax.scatter(x_coords[0], y_coords[0], color=color, s=100, marker='o', zorder=5)
            ax.scatter(x_coords[-1], y_coords[-1], color=color, s=100, marker='s', zorder=5)
        
        # Plot grid if requested
        if show_grid:
            for i in range(self.collision_regions_x + 1):
                x = self.x_min + i * self.dx
                ax.axvline(x, color='gray', alpha=0.3, linewidth=0.5)
            
            for j in range(self.collision_regions_y + 1):
                y = self.y_min + j * self.dy
                ax.axhline(y, color='gray', alpha=0.3, linewidth=0.5)
        
        # Highlight merged regions
        merged_regions = self.get_merged_regions()
        region_colors = plt.cm.Set3(np.linspace(0, 1, len(merged_regions)))
        
        for region_idx, (root, cells) in enumerate(merged_regions.items()):
            if len(cells) > 1:  # Only highlight multi-cell regions
                for i, j in cells:
                    x_start = self.x_min + i * self.dx
                    y_start = self.y_min + j * self.dy
                    rect = plt.Rectangle((x_start, y_start), self.dx, self.dy, 
                                       facecolor=region_colors[region_idx], alpha=0.3)
                    ax.add_patch(rect)
        
        ax.set_xlabel('X Coordinate')
        ax.set_ylabel('Y Coordinate')
        ax.set_title('Vehicle Trajectories and Merged Regions')
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.grid(True, alpha=0.3)
        ax.set_aspect('equal')
        
        if save_path is None:
            save_path = 'trajectory_regions.png'
        
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Region visualization saved as: {save_path}")


def trajectory_to_region(trajectories: np.ndarray, collision_regions_x: int = 10, 
                        collision_regions_y: int = 10, radius: float = 5.0) -> List[List[int]]:
    """
    Analyze vehicle trajectories to find vehicles that share spatial regions.
    
    Args:
        trajectories: Array of shape (N, T, 3) where last dimension is (x, y, heading)
        collision_regions_x: Number of grid regions in x direction
        collision_regions_y: Number of grid regions in y direction
        radius: Radius in meters to consider around each vehicle position
        
    Returns:
        List of lists, where each inner list contains vehicle indices that share regions.
        Vehicles in the same group will have the same color in visualization.
        Format: [[v for v in group 1], [v for v in group 2], ...]
    """
    analyzer = TrajectoryRegionAnalyzer(trajectories, collision_regions_x, collision_regions_y, radius)
    analyzer.merge_regions()
    return analyzer.get_vehicle_relationships()


def test_trajectory_region_analysis():
    """
    Test the trajectory region analysis with sample data.
    """
    print("Testing trajectory region analysis...")
    
    # Create sample trajectories
    N = 12  # Number of vehicles
    T = 80  # Number of time steps
    
    trajectories = np.zeros((N, T, 3))
    
    # Create different trajectory patterns
    t = np.linspace(0, 4*np.pi, T)
    
    # Vehicle 0: Straight line
    trajectories[0, :, 0] = t
    trajectories[0, :, 1] = 0
    trajectories[0, :, 2] = 0
    
    # Vehicle 1: Parallel straight line
    trajectories[1, :, 0] = t
    trajectories[1, :, 1] = 2
    trajectories[1, :, 2] = 0
    
    # Vehicle 2: Crossing trajectory
    trajectories[2, :, 0] = 10 - t
    trajectories[2, :, 1] = t
    trajectories[2, :, 2] = np.pi/4
    
    # Vehicle 3: Circular path
    radius = 3
    center_x, center_y = 5, 5
    trajectories[3, :, 0] = center_x + radius * np.cos(t)
    trajectories[3, :, 1] = center_y + radius * np.sin(t)
    trajectories[3, :, 2] = t + np.pi/2
    
    # Vehicle 4: Smaller circle (should overlap with vehicle 3)
    radius = 2
    trajectories[4, :, 0] = center_x + radius * np.cos(t)
    trajectories[4, :, 1] = center_y + radius * np.sin(t)
    trajectories[4, :, 2] = t + np.pi/2
    
    # Vehicle 5: Isolated trajectory
    trajectories[5, :, 0] = 15 + t
    trajectories[5, :, 1] = 15 + t
    trajectories[5, :, 2] = np.pi/4
    
    # Vehicle 6: Another isolated trajectory
    trajectories[6, :, 0] = -5 + t
    trajectories[6, :, 1] = -5 + t
    trajectories[6, :, 2] = np.pi/4
    
    # Vehicle 7: Close to vehicle 0
    trajectories[7, :, 0] = t + 0.5
    trajectories[7, :, 1] = 0.5
    trajectories[7, :, 2] = 0
    
    print(f"Input shape: {trajectories.shape}")
    
    # Analyze regions
    analyzer = TrajectoryRegionAnalyzer(trajectories, collision_regions_x=8, collision_regions_y=8, radius=5.0)
    analyzer.merge_regions()
    
    # Get vehicle relationships
    vehicle_relationships = analyzer.get_vehicle_relationships()
    
    print(f"\nFound {len(vehicle_relationships)} vehicle groups:")
    for i, group in enumerate(vehicle_relationships):
        print(f"  Group {i}: {group}")
    
    # Get region statistics
    region_counts = analyzer.count_vehicles_per_region()
    print(f"\nRegion statistics:")
    for region_id, count in region_counts.items():
        if count > 1:
            print(f"  Region {region_id}: {count} vehicles")
    
    # Visualize results
    print("\nGenerating visualization...")
    analyzer.visualize_regions(save_path="trajectory_regions_test.png")
    
    return vehicle_relationships


if __name__ == "__main__":
    # Run the test
    relationships = test_trajectory_region_analysis()
    print(relationships)
    print("\n✓ Test completed successfully!")
