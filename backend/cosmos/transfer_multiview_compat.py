"""Compatibility helpers for seven-view Transfer2.5 inference on four CP ranks.

The upstream multiview VAE assigns at most one camera to each context-parallel
rank.  The diffusion model itself does not have that restriction.  TrafficWM
keeps the official joint multiview diffusion path and batches only VAE
encode/decode work when there are more cameras than ranks.
"""
from __future__ import annotations

from typing import Any


def view_batches(n_views: int, cp_size: int) -> tuple[tuple[int, int], ...]:
    """Return half-open camera batches that fit one view per CP rank."""
    n_views = int(n_views)
    cp_size = int(cp_size)
    if n_views < 1:
        raise ValueError("n_views must be positive")
    if cp_size < 1:
        raise ValueError("cp_size must be positive")
    return tuple(
        (start, min(n_views, start + cp_size))
        for start in range(0, n_views, cp_size)
    )


def install_multiview_vae_batching() -> dict[str, Any]:
    """Patch the upstream VAE scheduler without changing model computation."""
    import torch
    import torch.distributed as dist
    from einops import rearrange
    from megatron.core import parallel_state
    from torch.distributed import get_process_group_ranks

    from cosmos_transfer2._src.imaginaire.utils.context_parallel import (
        broadcast_split_tensor,
    )
    from cosmos_transfer2._src.transfer2_multiview.models.multiview_vid2vid_model_control_vace_rectified_flow import (
        MultiviewControlVideo2WorldModelRectifiedFlow,
    )

    model_class = MultiviewControlVideo2WorldModelRectifiedFlow
    if getattr(model_class, "_trafficwm_batched_vae", False):
        return {"enabled": True, "already_installed": True}

    original_encode_cp = model_class.encode_cp
    original_decode_cp = model_class.decode_cp

    @torch.no_grad()
    def encode_cp(self, state: torch.Tensor) -> torch.Tensor:
        cp_group = parallel_state.get_context_parallel_group()
        cp_size = len(get_process_group_ranks(cp_group))
        pixel_frames = self.tokenizer.get_pixel_num_frames(self.state_t)
        n_views = state.shape[2] // pixel_frames
        if n_views <= cp_size:
            return original_encode_cp(self, state)

        views = rearrange(state, "B C (V T) H W -> V B C T H W", V=n_views)
        encoded_batches = []
        for start, end in view_batches(n_views, cp_size):
            active = end - start
            rank_inputs = torch.zeros(
                (cp_size, *views.shape[1:]),
                **self.tensor_kwargs,
            )
            rank_inputs[:active] = views[start:end]
            local_view = broadcast_split_tensor(
                rank_inputs,
                seq_dim=0,
                process_group=cp_group,
            )
            local_state = rearrange(local_view, "V B C T H W -> (B V) C T H W")
            local_encoded = super(model_class, self).encode(local_state)
            gathered = [torch.empty_like(local_encoded) for _ in range(cp_size)]
            dist.all_gather(gathered, local_encoded, group=cp_group)
            encoded_batches.append(torch.cat(gathered[:active], dim=2))
        return torch.cat(encoded_batches, dim=2)

    @torch.no_grad()
    def decode_cp(self, latent: torch.Tensor) -> torch.Tensor:
        cp_group = parallel_state.get_context_parallel_group()
        cp_size = len(get_process_group_ranks(cp_group))
        n_views = latent.shape[2] // self.state_t
        if n_views <= cp_size:
            return original_decode_cp(self, latent)

        views = rearrange(latent, "B C (V T) H W -> V B C T H W", V=n_views)
        decoded_batches = []
        for start, end in view_batches(n_views, cp_size):
            active = end - start
            rank_inputs = torch.zeros(
                (cp_size, *views.shape[1:]),
                **self.tensor_kwargs,
            )
            rank_inputs[:active] = views[start:end]
            local_view = broadcast_split_tensor(
                rank_inputs,
                seq_dim=0,
                process_group=cp_group,
            )
            local_latent = rearrange(local_view, "V B C T H W -> (B V) C T H W")
            local_decoded = super(model_class, self).decode(local_latent)
            gathered = [torch.empty_like(local_decoded) for _ in range(cp_size)]
            dist.all_gather(gathered, local_decoded, group=cp_group)
            decoded_batches.append(torch.cat(gathered[:active], dim=2))
        return torch.cat(decoded_batches, dim=2)

    model_class.encode_cp = encode_cp
    model_class.decode_cp = decode_cp
    model_class._trafficwm_batched_vae = True
    return {
        "enabled": True,
        "already_installed": False,
        "strategy": "one-view-per-rank-batched-vae",
    }
