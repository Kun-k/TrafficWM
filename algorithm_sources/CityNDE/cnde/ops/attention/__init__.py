"""
Mostly copy-paste from https://github.com/dvlab-research/DeepVision3D/blob/master/EQNet/eqnet/ops/attention
"""

import torch

if torch._C._GLIBCXX_USE_CXX11_ABI:
    from . import attention_fallback

    __all__ = {'v1': attention_fallback, 'v2': attention_fallback}
else:
    from . import attention_utils
    from . import attention_utils_v2

    __all__ = {'v1': attention_utils, 'v2': attention_utils_v2}
