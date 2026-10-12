"""Launch the upstream OmniDreams gRPC server with local checkpoint overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_DISTRIBUTED_TIMEOUT_SECONDS = 7 * 24 * 60 * 60


class _SnapshotKeysDict(dict):
    """Return stable key snapshots for upstream cleanup loops that mutate the dict."""

    def keys(self):
        return tuple(super().keys())


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def configure_vae_runtime_stability() -> None:
    """Optionally remove per-shape VAE compilation and CUDA graph capture.

    Long-running streams reuse changing causal-cache shapes. The upstream
    ``perf`` recipe captures those shapes independently and can retain enough
    cuDNN workspace to invalidate a later capture. The diffusion transformer
    remains compiled and CUDA-graphed; only image/VAE components are affected.
    """
    disable_compile = _env_enabled("OMNIDREAMS_DISABLE_VAE_COMPILE")
    disable_cuda_graph = _env_enabled("OMNIDREAMS_DISABLE_VAE_CUDA_GRAPH")
    if not disable_compile and not disable_cuda_graph:
        return

    pipeline_name = os.environ.get("OMNIDREAMS_PIPELINE_CONFIG", "").strip()
    if not pipeline_name:
        raise RuntimeError(
            "OMNIDREAMS_PIPELINE_CONFIG is required for VAE runtime overrides"
        )

    from flashdreams.infra.config import derive_config
    from omnidreams.config import OMNIDREAMS_CONFIGS

    if pipeline_name not in OMNIDREAMS_CONFIGS:
        raise KeyError(f"Unknown OmniDreams pipeline config: {pipeline_name}")
    component_override: dict[str, bool] = {}
    if disable_compile:
        component_override["use_compile"] = False
    if disable_cuda_graph:
        component_override["use_cuda_graph"] = False
    OMNIDREAMS_CONFIGS[pipeline_name] = derive_config(
        OMNIDREAMS_CONFIGS[pipeline_name],
        image_encoder=component_override,
        encoder=component_override,
        decoder=component_override,
    )


def configure_temporal_context() -> None:
    """Optionally retain early-frame tokens in the streaming KV cache.

    A static sink keeps the opening appearance anchor available after the
    moving context window advances. Keeping ``window + sink`` unchanged avoids
    increasing the resident cache and preserves the checkpoint's loc6 context
    budget. Both values remain environment overrides so the upstream 6/0
    layout can be restored without changing code.
    """
    window_value = os.environ.get("OMNIDREAMS_WINDOW_SIZE_T", "").strip()
    sink_value = os.environ.get("OMNIDREAMS_SINK_SIZE_T", "").strip()
    if not window_value and not sink_value:
        return
    if not window_value or not sink_value:
        raise RuntimeError(
            "OMNIDREAMS_WINDOW_SIZE_T and OMNIDREAMS_SINK_SIZE_T must be set together"
        )

    window_size_t = int(window_value)
    sink_size_t = int(sink_value)
    if window_size_t <= 0 or sink_size_t < 0:
        raise ValueError("OmniDreams temporal window must be positive and sink non-negative")

    pipeline_name = os.environ.get("OMNIDREAMS_PIPELINE_CONFIG", "").strip()
    if not pipeline_name:
        raise RuntimeError(
            "OMNIDREAMS_PIPELINE_CONFIG is required for temporal context overrides"
        )

    from flashdreams.infra.config import derive_config
    from omnidreams.config import OMNIDREAMS_CONFIGS

    if pipeline_name not in OMNIDREAMS_CONFIGS:
        raise KeyError(f"Unknown OmniDreams pipeline config: {pipeline_name}")
    transformer = OMNIDREAMS_CONFIGS[pipeline_name].diffusion_model.transformer
    len_t = int(transformer.len_t)
    if (window_size_t + sink_size_t) % len_t:
        raise ValueError(
            "OmniDreams temporal window + sink must be divisible by the AR chunk length "
            f"({len_t})"
        )
    OMNIDREAMS_CONFIGS[pipeline_name] = derive_config(
        OMNIDREAMS_CONFIGS[pipeline_name],
        diffusion_model={
            "transformer": {
                "window_size_t": window_size_t,
                "sink_size_t": sink_size_t,
            }
        },
    )


def training_checkpoint_transform(state_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert released training checkpoints to the runtime network key layout."""
    transformed: dict[str, Any] = {}
    for key, value in state_dict.items():
        normalized = key[4:] if key.startswith("net.") else key
        if (
            normalized.startswith("accum_")
            or normalized.startswith("pos_embedder.")
            or normalized.endswith("._extra_state")
        ):
            continue
        transformed[normalized] = value
    return transformed


def configure_checkpoint_override() -> None:
    checkpoint_value = os.environ.get("OMNIDREAMS_CHECKPOINT_PATH", "").strip()
    if not checkpoint_value:
        return

    # Preserve a Hugging Face cache symlink's .pt suffix. Resolving it exposes
    # the extensionless blob name, which the upstream loader mistakes for DCP.
    checkpoint = Path(os.path.abspath(os.path.expanduser(checkpoint_value)))
    if not checkpoint.is_file():
        raise FileNotFoundError(f"OmniDreams checkpoint not found: {checkpoint}")

    pipeline_name = os.environ.get("OMNIDREAMS_PIPELINE_CONFIG", "").strip()
    if not pipeline_name:
        raise RuntimeError(
            "OMNIDREAMS_PIPELINE_CONFIG is required when overriding the checkpoint"
        )

    from omnidreams.config import OMNIDREAMS_CONFIGS
    from flashdreams.infra.config import derive_config

    if pipeline_name not in OMNIDREAMS_CONFIGS:
        raise KeyError(f"Unknown OmniDreams pipeline config: {pipeline_name}")
    OMNIDREAMS_CONFIGS[pipeline_name] = derive_config(
        OMNIDREAMS_CONFIGS[pipeline_name],
        diffusion_model={
            "transformer": {
                "checkpoint_path": str(checkpoint),
                "state_dict_transform": training_checkpoint_transform,
            }
        },
    )


def configure_synchronous_kv_finalization() -> None:
    """Keep CUDA graph and cuBLAS work on the initialized model thread.

    Upstream overlaps KV-cache finalization on a fresh host thread. On the
    resident single-GPU service that thread can fail to create its own cuBLAS
    handle during CUDA graph capture, leaving the autoregressive cache between
    ``before_update`` and ``after_update``. The next chunk then fails even
    though the gRPC process remains alive. Upstream already provides the same
    overlap interface with synchronous execution, so use it for correctness.
    """
    from flashdreams.infra.acceleration.overlap import SynchronousOverlap
    from omnidreams.grpc import server as grpc_server

    grpc_server.HostThreadOverlap = SynchronousOverlap


def configure_session_cleanup_stability() -> None:
    """Prevent the upstream recorder cleanup loop from mutating its iterator.

    OmniDreams 1.2 iterates ``recorders.keys()`` and removes stale recorders
    inside that same loop when a new session starts. A resident service can
    therefore fail its next session with ``dictionary changed size during
    iteration``. Keep the upstream behavior but make the key view a snapshot.
    """
    from omnidreams.grpc import server as grpc_server

    service_class = grpc_server.WorldModelService
    if getattr(service_class, "_trafficwm_snapshot_recorders", False):
        return
    original_init = service_class.__init__

    def stable_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.recorders = _SnapshotKeysDict(self.recorders)

    service_class.__init__ = stable_init
    service_class._trafficwm_snapshot_recorders = True


def configure_distributed_timeout() -> int:
    """Keep resident multi-GPU workers alive while rank zero waits for RPC work."""
    configured = os.environ.get("OMNIDREAMS_DISTRIBUTED_TIMEOUT_SECONDS", "").strip()
    timeout_seconds = int(configured or DEFAULT_DISTRIBUTED_TIMEOUT_SECONDS)
    if timeout_seconds <= 0:
        raise ValueError("OMNIDREAMS_DISTRIBUTED_TIMEOUT_SECONDS must be positive")
    os.environ.setdefault("TORCH_NCCL_HEARTBEAT_TIMEOUT_SEC", str(timeout_seconds))
    return int(os.environ["TORCH_NCCL_HEARTBEAT_TIMEOUT_SEC"])


def main() -> None:
    configure_distributed_timeout()
    configure_checkpoint_override()
    configure_vae_runtime_stability()
    configure_temporal_context()
    configure_synchronous_kv_finalization()
    configure_session_cleanup_stability()
    from omnidreams.grpc.server import main as upstream_main

    upstream_main()


if __name__ == "__main__":
    main()
