"""K-nearest-neighbor operators with a native fallback for new PyTorch ABIs."""

import torch

if torch._C._GLIBCXX_USE_CXX11_ABI:
    from . import knn_fallback as knn_utils
else:
    from . import knn_utils

__all__ = ['knn_utils']
