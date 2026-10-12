# Motion Transformer (MTR): https://arxiv.org/abs/2209.13508
# Published at NeurIPS 2022
# Written by Shaoshuai Shi 
# All Rights Reserved


from .base_encoder import BaseEncoder
from .routebased_encoder import RouteEnhancedEncoder
from .trafficlightbased_encoder import TLEnhancedEncoder
from .route_tl_smooth_encoder import RouteTLEnhancedEncoder
# from .mamba_encoder import MambaEncoder

__all__ = {
    'BaseEncoder': BaseEncoder,
    'RouteEnhancedEncoder': RouteEnhancedEncoder,
    'TLEnhancedEncoder': TLEnhancedEncoder,
    'RouteTLEnhancedEncoder': RouteTLEnhancedEncoder,
    # 'MambaEncoder': MambaEncoder
}


def build_context_encoder(config):
    model = __all__[config.NAME](
        config=config
    )

    return model
