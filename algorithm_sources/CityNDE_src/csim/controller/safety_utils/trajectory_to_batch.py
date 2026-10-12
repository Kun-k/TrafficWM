import numpy as np
import matplotlib.pyplot as plt
from typing import Tuple
from scipy.interpolate import interp1d
from typing import Literal

def generate_trajectory_batch(trajectories: np.ndarray, K: int, mode: Literal["linear", "exponential"] = "linear") -> np.ndarray:
    """
    Generate K trajectories for each input trajectory with scaled distances.
    Args:
        trajectories: Input trajectories of shape (N, T, 3) where last dimension is (x, y, heading)
        K: Number of trajectories to generate for each input trajectory
    Returns:
        Batch of trajectories of shape (N, K, T, 3)
        - N, 0, T, 3: Original trajectory
        - N, k, T, 3: Scaled trajectory with distance scaled by (1 - k/(K-1))
    """
    if K == 1:
        print("Warning: K == 1, return original trajectories")
        return trajectories[:, None, :, :]
    elif mode == "linear":
        scale_factors = 1 - np.arange(K) / (K - 1)  # (K,)
    elif mode == "exponential":
        scale_factors = np.append(np.power(0.5, np.arange(K - 1)), 0)
        
    N, T, _ = trajectories.shape
    batch_trajectories = np.zeros((N, K, T, 3), dtype=trajectories.dtype)

    distances = np.linalg.norm(np.diff(trajectories[:, :, :2], axis=1), axis=-1)           # (N, T-1)
    cumulative_length = np.concatenate(
        [np.zeros((N, 1), dtype=trajectories.dtype), np.cumsum(distances, axis=1)], axis=1
    )  # (N, T)
    interp_length = cumulative_length[:, None, :].repeat(K, axis=1) * scale_factors[None, :, None]
    trajectories[..., 2] = np.unwrap(trajectories[..., 2], axis=-1)
    for i in range(N):
        if (cumulative_length[i] < 1e-5).all():
            batch_trajectories[i, ..., :] = trajectories[i, None, 0:1, :]
        else:
            finterp1d = interp1d(x=cumulative_length[i], y=trajectories[i, ..., :3], kind='linear', axis=0, assume_sorted=True)
            batch_trajectories[i, ..., :3] = finterp1d(interp_length[i])
    batch_trajectories[..., 2] = (batch_trajectories[..., 2] + np.pi) % (2 * np.pi) - np.pi
    batch_trajectories[:, 0, :, :] = trajectories
    return batch_trajectories
