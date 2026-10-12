"""Native PyTorch fallback for legacy local-attention CUDA extensions."""

import torch


def _global_key_indices(
    key_batch_cnt: torch.Tensor,
    index_pair_batch: torch.Tensor,
    index_pair: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    del key_batch_cnt, index_pair_batch
    valid = index_pair >= 0
    return index_pair.clamp_min(0).long(), valid


def attention_weight_computation(
    query_batch_cnt: torch.Tensor,
    key_batch_cnt: torch.Tensor,
    index_pair_batch: torch.Tensor,
    index_pair: torch.Tensor,
    query_features: torch.Tensor,
    key_features: torch.Tensor,
) -> torch.Tensor:
    del query_batch_cnt
    global_indices, valid = _global_key_indices(key_batch_cnt, index_pair_batch, index_pair)
    selected_keys = key_features[global_indices]
    weights = (query_features.unsqueeze(1) * selected_keys).sum(dim=-1)
    return weights.masked_fill(~valid.unsqueeze(-1), 0)


def attention_value_computation(
    query_batch_cnt: torch.Tensor,
    key_batch_cnt: torch.Tensor,
    index_pair_batch: torch.Tensor,
    index_pair: torch.Tensor,
    attention_weights: torch.Tensor,
    value_features: torch.Tensor,
) -> torch.Tensor:
    del query_batch_cnt
    global_indices, valid = _global_key_indices(key_batch_cnt, index_pair_batch, index_pair)
    selected_values = value_features[global_indices]
    weights = attention_weights.masked_fill(~valid.unsqueeze(-1), 0)
    return (weights.unsqueeze(-1) * selected_values).sum(dim=1)
