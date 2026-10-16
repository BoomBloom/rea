"""Optional Numba JIT.

Kernels are written as plain Python over numpy arrays. When Numba is installed
(and ``ALPHAFORGE_DISABLE_JIT`` is not set) they are compiled; otherwise they run
as Python. Tests exercise both paths so the compiled and interpreted results
must agree exactly.
"""

from __future__ import annotations

import os

JIT_ENABLED = False

if os.environ.get("ALPHAFORGE_DISABLE_JIT", "") not in ("1", "true", "yes"):
    try:
        from numba import njit as _njit

        JIT_ENABLED = True
    except ImportError:  # pragma: no cover - depends on environment
        _njit = None
else:
    _njit = None


def jit(fn):
    if _njit is None:
        return fn
    return _njit(cache=True, nogil=True)(fn)
