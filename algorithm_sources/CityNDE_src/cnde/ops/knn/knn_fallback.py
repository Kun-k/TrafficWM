"""Native PyTorch replacement for the legacy batched KNN CUDA extension."""

import torch


def knn_batch(
    xyz: torch.Tensor,
    query_xyz: torch.Tensor,
    batch_idxs: torch.Tensor,
    query_batch_offsets: torch.Tensor,
    k: int,
) -> torch.Tensor:
    if k <= 0:
        raise ValueError('k must be positive')

    result = torch.zeros((xyz.shape[0], k), dtype=torch.int32, device=xyz.device)
    for batch_index in range(query_batch_offsets.numel() - 1):
        source_rows = (batch_idxs == batch_index).nonzero(as_tuple=False).flatten()
        if source_rows.numel() == 0:
            continue
        start = int(query_batch_offsets[batch_index])
        end = int(query_batch_offsets[batch_index + 1])
        if end <= start:
            continue
        distances = torch.cdist(xyz[source_rows], query_xyz[start:end])
        count = min(k, end - start)
        indices = distances.topk(count, dim=1, largest=False).indices + start
        result[source_rows, :count] = indices.to(torch.int32)
        if count < k:
            result[source_rows, count:] = indices[:, -1:].to(torch.int32)
    return result


knn_batch_mlogk = knn_batch
