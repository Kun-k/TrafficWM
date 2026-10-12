# Motion Transformer (MTR): https://arxiv.org/abs/2209.13508
# Published at NeurIPS 2022
# Written by Shaoshuai Shi 
# All Rights Reserved


from .base_decoder import BaseDecoder
from .routebased_decoder import RouteEnhancedDecoder
from .action_decoder import ActionDecoder
from .trafficlightbased_decoder import TLEnhancedDecoder
from .ode_decoder import ODEEnhancedDecoder
from .route_tl_smooth_decoder import RouteTLSmoothEnhancedDecoder

__all__ = {
    'BaseDecoder': BaseDecoder,
    'RouteEnhancedDecoder': RouteEnhancedDecoder,
    'ActionDecoder': ActionDecoder,
    'TLEnhancedDecoder': TLEnhancedDecoder,
    'ODEEnhancedDecoder': ODEEnhancedDecoder,
    'RouteTLSmoothEnhancedDecoder': RouteTLSmoothEnhancedDecoder
}


def build_motion_decoder(in_channels, config):
    model = __all__[config.NAME](
        in_channels=in_channels,
        config=config
    )

    return model
