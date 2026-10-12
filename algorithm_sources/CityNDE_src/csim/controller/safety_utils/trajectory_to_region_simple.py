import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Tuple, Set
from collections import defaultdict
import torch
from igraph import Graph


def cluster_trajectories(trajectories: np.ndarray, cluster_radius: float = 10., down_sample_rate: int = 1):
    """
    Cluster trajectories into regions based on the distance between them.

    Args:
        trajectories (np.ndarray): (N, T, D>=2) The trajectories to cluster.
        cluster_radius (float, optional): The radius to cluster trajectories. Defaults to 10..
        down_sample_rate (int, optional): The rate to down sample trajectories. Defaults to 1.

    Returns:
        List[List[int]]: The clustered trajectories.
    """
    trajectories = torch.from_numpy(trajectories[:, :, :2]).cuda()
    N, T, _ = trajectories.shape
    down_sample_positions = trajectories[:, ::down_sample_rate]
    down_sample_T = down_sample_positions.shape[1]
    edges = []
    for source in range(N - 1):
        target_positions = down_sample_positions[source + 1:].reshape(-1, 2)
        distances = torch.cdist(down_sample_positions[source], target_positions)
        distances = distances.reshape(down_sample_T, N - source - 1, down_sample_T)
        nearby = (distances <= cluster_radius).any(dim=(0, 2)).nonzero(as_tuple=False).flatten()
        edges.extend((source, source + 1 + int(offset)) for offset in nearby.tolist())
    edge_index = edges
    g = Graph(edge_index, n=N, directed=False)
    components = g.clusters()
    connected_components = [list(c) for c in components]
    return connected_components
