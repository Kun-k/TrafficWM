"""Memory-bounded trajectory clustering for the CityNDE safety layer."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def cluster_trajectories_cpu(
    trajectories: np.ndarray,
    cluster_radius: float = 10.0,
    down_sample_rate: int = 1,
) -> list[list[int]]:
    """Return connected trajectory groups using the original point-distance rule."""
    values = np.asarray(trajectories)
    if values.ndim != 3 or values.shape[-1] < 2:
        raise ValueError("trajectories must have shape (N, T, D>=2)")
    count = int(values.shape[0])
    if count == 0:
        return []
    stride = max(1, int(down_sample_rate))
    points_per_trajectory = np.ascontiguousarray(values[:, ::stride, :2], dtype=np.float64)
    points_per_track = int(points_per_trajectory.shape[1])
    if points_per_track == 0:
        return [[index] for index in range(count)]

    points = points_per_trajectory.reshape(-1, 2)
    owners = np.repeat(np.arange(count, dtype=np.int64), points_per_track)
    parent = np.arange(count, dtype=np.int64)
    rank = np.zeros(count, dtype=np.int8)

    def find(item: int) -> int:
        while int(parent[item]) != item:
            parent[item] = parent[int(parent[item])]
            item = int(parent[item])
        return item

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1

    tree = cKDTree(points)
    candidate_pairs = tree.query_pairs(r=max(0.0, float(cluster_radius)), output_type="ndarray")
    for left_point, right_point in candidate_pairs:
        left_owner = int(owners[int(left_point)])
        right_owner = int(owners[int(right_point)])
        if left_owner != right_owner:
            union(left_owner, right_owner)

    components: dict[int, list[int]] = {}
    for index in range(count):
        components.setdefault(find(index), []).append(index)
    return sorted(components.values(), key=lambda component: component[0])
