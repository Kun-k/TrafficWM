"""Exact batched KNN with bounded temporary CUDA memory."""
from __future__ import annotations

import torch


def knn_batch_chunked(
    xyz: torch.Tensor,
    query_xyz: torch.Tensor,
    batch_idxs: torch.Tensor,
    query_batch_offsets: torch.Tensor,
    k: int,
    *,
    source_chunk_size: int = 128,
    query_chunk_size: int = 1024,
) -> torch.Tensor:
    if k <= 0:
        raise ValueError("k must be positive")
    source_chunk_size = max(1, int(source_chunk_size))
    query_chunk_size = max(1, int(query_chunk_size))
    result = torch.zeros((xyz.shape[0], k), dtype=torch.int32, device=xyz.device)

    for batch_index in range(query_batch_offsets.numel() - 1):
        source_rows = (batch_idxs == batch_index).nonzero(as_tuple=False).flatten()
        if source_rows.numel() == 0:
            continue
        query_start = int(query_batch_offsets[batch_index])
        query_end = int(query_batch_offsets[batch_index + 1])
        if query_end <= query_start:
            continue
        count = min(k, query_end - query_start)
        for source_start in range(0, source_rows.numel(), source_chunk_size):
            rows = source_rows[source_start : source_start + source_chunk_size]
            best_distances = torch.full(
                (rows.numel(), count),
                torch.inf,
                dtype=xyz.dtype,
                device=xyz.device,
            )
            best_indices = torch.full(
                (rows.numel(), count),
                query_start,
                dtype=torch.long,
                device=xyz.device,
            )
            for candidate_start in range(query_start, query_end, query_chunk_size):
                candidate_end = min(query_end, candidate_start + query_chunk_size)
                distances = torch.cdist(
                    xyz[rows],
                    query_xyz[candidate_start:candidate_end],
                    compute_mode="donot_use_mm_for_euclid_dist",
                )
                candidate_indices = torch.arange(
                    candidate_start,
                    candidate_end,
                    dtype=torch.long,
                    device=xyz.device,
                ).expand(rows.numel(), -1)
                merged_distances = torch.cat((best_distances, distances), dim=1)
                merged_indices = torch.cat((best_indices, candidate_indices), dim=1)
                best_distances, positions = merged_distances.topk(count, dim=1, largest=False)
                best_indices = torch.gather(merged_indices, 1, positions)

            result[rows, :count] = best_indices.to(torch.int32)
            if count < k:
                result[rows, count:] = best_indices[:, -1:].to(torch.int32)
    return result


knn_batch_mlogk_chunked = knn_batch_chunked
