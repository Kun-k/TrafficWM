"""Named OmniDreams runtime profiles with explicit quality tradeoffs."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OmniDreamsProfile:
    name: str
    pipeline_config: str
    gpus: tuple[str, ...]
    jpeg_quality: int
    live_preview_fps: int
    return_hdmap_frames: bool
    traffic_prefetch_seconds: float
    encoder_preset: str
    encoder_crf: int
    disable_vae_compile: bool
    disable_vae_cuda_graph: bool
    temporal_window_size_t: int
    temporal_sink_size_t: int

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["gpus"] = list(self.gpus)
        return payload


OMNIDREAMS_PROFILES = {
    "quality": OmniDreamsProfile(
        name="quality",
        pipeline_config="omnidreams-sv-2steps-chunk2-loc6-vae-vae",
        gpus=("7",),
        jpeg_quality=95,
        live_preview_fps=10,
        return_hdmap_frames=True,
        traffic_prefetch_seconds=0.0,
        encoder_preset="medium",
        encoder_crf=18,
        disable_vae_compile=True,
        disable_vae_cuda_graph=True,
        temporal_window_size_t=6,
        temporal_sink_size_t=0,
    ),
    "realtime": OmniDreamsProfile(
        name="realtime",
        pipeline_config="omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf",
        gpus=("4", "5", "6", "7"),
        jpeg_quality=95,
        # The final MP4 remains 30 fps. A 15 fps MJPEG preview halves browser
        # decode and file-I/O load while preserving the model timeline.
        live_preview_fps=15,
        return_hdmap_frames=False,
        traffic_prefetch_seconds=2.0,
        encoder_preset="veryfast",
        encoder_crf=18,
        disable_vae_compile=True,
        disable_vae_cuda_graph=True,
        temporal_window_size_t=6,
        temporal_sink_size_t=0,
    ),
    "realtime_fast": OmniDreamsProfile(
        name="realtime_fast",
        pipeline_config="omnidreams-sv-2steps-chunk2-loc6-lightvae-lighttae-perf",
        gpus=("0", "1", "2", "3"),
        jpeg_quality=95,
        live_preview_fps=15,
        return_hdmap_frames=False,
        traffic_prefetch_seconds=2.0,
        encoder_preset="veryfast",
        encoder_crf=18,
        # Streaming changes causal-cache shapes during the opening chunks.
        # Compiling those shapes stalls each chunk and a captured VAE graph can
        # remain invalid after a cuDNN workspace allocation failure. The
        # diffusion backbone remains on the 2-step performance recipe.
        disable_vae_compile=True,
        disable_vae_cuda_graph=True,
        temporal_window_size_t=6,
        temporal_sink_size_t=0,
    ),
}


def resolve_omnidreams_profile(name: str | None) -> OmniDreamsProfile:
    normalized = str(name or "quality").strip().lower()
    try:
        return OMNIDREAMS_PROFILES[normalized]
    except KeyError as exc:
        choices = ", ".join(sorted(OMNIDREAMS_PROFILES))
        raise ValueError(
            f"Unknown OmniDreams profile {name!r}; expected one of: {choices}"
        ) from exc
