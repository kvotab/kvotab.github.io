"""numba, when it is installed: compiled kernels for the inner loops.

numba is optional. Every kernel compiled here has a plain Python or numpy
path beside it, and the engine takes that path when numba is missing or a
kernel will not compile -- slower, never different in what it can run.

The kernels do the arithmetic the application does, in its order, one
rounding per operation: numba does not fuse a multiply and an add unless it is
asked to (``fastmath``), and it is never asked to here.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

_NUMBA: Any = None


def numba_module() -> Any:
    """The numba module, or None when it cannot be imported."""
    global _NUMBA
    if _NUMBA is None:
        try:
            import numba
            _NUMBA = numba
        except Exception:  # noqa: BLE001 - optional; any failure means go without
            _NUMBA = False
    return _NUMBA or None


def jit(fn: Callable[..., Any]) -> Optional[Callable[..., Any]]:
    """``fn`` compiled with numba (cached on disk when the package directory
    allows it), or None when numba is not there."""
    numba = numba_module()
    if numba is None:
        return None
    for opts in ({'cache': True, 'nogil': True}, {'nogil': True}):
        try:
            return numba.njit(**opts)(fn)
        except Exception:  # noqa: BLE001 - a read-only cache directory refuses at decoration; retry without
            continue
    return None
