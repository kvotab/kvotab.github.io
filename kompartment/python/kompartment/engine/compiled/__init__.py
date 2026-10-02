"""The compiled path: a model's derivative and the solver's loop compiled
with numba, so that a run returns to Python only when it ends.

* :mod:`.model` compiles a built model -- its derivative, what its recorders
  and discrete events do at each step, its algebra for the results -- into
  functions of fixed signature, cached on disk by their code;
* :mod:`.runtime` holds what that code calls: every function of the
  language, the lookup tables, the recorders' histories; :mod:`.farfield`
  the rates of a far-field path whose settings move, worked out again as
  they move;
* :mod:`.solvers` holds the NDF, Rosenbrock (2,3) and Dormand-Prince loops,
  and :mod:`.julia` the six Julia-derived methods', ports of
  ``engine/solvers`` with the same arithmetic, events located as they locate
  them, compiled once for every model;
* :mod:`.run` and :mod:`.julia_run` drive a run on those loops -- or, for
  SciPy's solvers, which keep their own loop in Python, on that loop, given
  the compiled model.

Every model takes the path, and a compiled run takes the same steps as the
Python path, to the last bit. A few things are worked out in Python and
called back from the compiled code: SuperLU, an analytic Jacobian, progress,
and a far-field path worked out semi-analytically (its history is the
Python path's). numba is optional; without it there is only the Python path.

What numba compiles is cached on disk by every process that compiles it,
under a lock (:func:`guard_numba_cache`).
"""


import contextlib
import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterator, List


def cache_root() -> Path:
    """The directory this package keeps what it works out for later runs in:
    ``KOMPARTMENT_CACHE``, else the user's cache directory (compiled models
    in ``compiled/`` under it)."""
    base = os.environ.get('KOMPARTMENT_CACHE')
    if base:
        return Path(base)
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'kompartment'
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'kompartment'


# --- numba's cache, shared by processes ---------------------------------------------------------
# numba keeps a function's compiled versions in one index file and numbered
# data files beside it, and adds one by reading the index, taking the first
# free number, and writing the index and then the data -- with no lock. Two
# processes adding versions of one function at once (a split run's workers
# compiling their parts) can both take a number, and the index then files one
# version's types against the other's code. A process that loads it gets code
# for other types and fails to compile its caller (a TypingError, which sent
# the part to the Python path), as does one that reads an index entry before
# its data is written. So this package's functions read and write their cache
# under a file lock: shared to read, sole to write.
#
# And numba files a function's code by its own module's source alone, while
# building into it the code of what it calls in other modules and the
# constants it imports from them: runtime's far-field refresh carries
# farfield.py's code, and every generated module runtime's. A change to
# farfield.py alone left the old code in both. So this package's functions
# are filed by their engine's sources as well (:func:`sources_stamp`).

#: The lock's file, in each cache directory it guards.
CACHE_LOCK_NAME = '.kompartment.lock'
_GUARDED = [False]
_HELD = threading.local()
_STAMP: List[str] = []


def sources_stamp() -> str:
    """A hash of every source the compiled code is built from: the engine's
    modules (this package among them, and the functions and settings whose
    constants it imports) and the statistics' (the error function's
    coefficients)."""
    if not _STAMP:
        engine = Path(__file__).resolve().parent.parent
        h = hashlib.sha256()
        for root in (engine, engine.parent / 'stats'):
            for path in sorted(root.rglob('*.py')):
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                h.update(path.relative_to(engine.parent).as_posix().encode())
                h.update(data)
        _STAMP.append(h.hexdigest()[:16])
    return _STAMP[0]


def guard_numba_cache() -> None:
    """Files every numba cache this package's code makes (its modules and the
    generated ones) by :func:`sources_stamp` as well as by numba's own stamp,
    and puts their reads and writes under :func:`cache_lock`. Called by each
    module that compiles, before its first function; does nothing a second
    time, without numba, or with a numba whose cache is not the one this
    knows. Without ``fcntl`` (Windows) the files are not locked."""
    if _GUARDED[0]:
        return
    _GUARDED[0] = True
    try:
        from numba.core import caching
    except ImportError:
        return
    try:
        import fcntl  # noqa: F401 - the lock this uses
        lock = True
    except ImportError:
        lock = False
    plain = getattr(caching, 'IndexDataCacheFile', None)
    cache = getattr(caching, 'Cache', None)
    if plain is None or cache is None or not all(callable(getattr(plain, n, None)) for n in ('load', 'save')):
        return

    class Locked(plain):  # type: ignore[misc, valid-type]
        def load(self, key: Any) -> Any:
            with cache_lock(self._cache_path, shared=True):
                return super().load(key)

        def save(self, key: Any, data: Any) -> Any:
            with cache_lock(self._cache_path, shared=False):
                return super().save(key, data)

    made = cache.__init__

    def __init__(self: Any, py_func: Any, *args: Any, **kwargs: Any) -> None:
        made(self, py_func, *args, **kwargs)
        module = getattr(py_func, '__module__', None) or ''
        own = module == 'kompartment' or module.startswith(('kompartment.', 'kompartment_compiled_'))
        f = getattr(self, '_cache_file', None)
        if own and type(f) is plain and hasattr(f, '_source_stamp'):
            f._source_stamp = (f._source_stamp, sources_stamp())
            if lock:
                f.__class__ = Locked

    cache.__init__ = __init__


@contextlib.contextmanager
def cache_lock(directory: str, shared: bool) -> Iterator[None]:
    """A cache directory's lock while the block runs: ``shared`` to read,
    sole to write. Taken once by a thread, which a load can come back to (it
    can import a module that compiles); not taken where it cannot be (a
    directory not yet made, which has nothing to read, or one that is not
    writable)."""
    import fcntl
    held = getattr(_HELD, 'dirs', None)
    if held is None:
        held = _HELD.dirs = set()
    if directory in held:
        yield
        return
    try:
        fd = os.open(os.path.join(directory, CACHE_LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        fd = -1
    if fd < 0:
        yield
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        except OSError:
            pass
        held.add(directory)
        try:
            yield
        finally:
            held.discard(directory)
    finally:
        os.close(fd)


class NotCompiled(Exception):
    """This model, or this run of it, is not one the compiled path takes.

    Here rather than beside the compiler so that the runner can catch it on
    a Python without numba, where the rest of this package cannot be imported.
    """


class CompiledFailure(Exception):
    """What compiled code raises where the Python code raises: ``args`` are a
    code (one of the ``FAIL_`` numbers below) and the numbers its message
    needs. :func:`python_error` turns it into the exception the Python path
    raises at the same point, with the same message."""


FAIL_TRANSPORT_BELOW = 1      # the position
FAIL_TRANSPORT_ABOVE = 2      # the position
FAIL_RANGE_START = 3          # where the range starts
FAIL_RANGE_END = 4            # where the range ends
FAIL_INTERPOLATION_ARGS = 5   # how many values follow the lookup value
FAIL_LOOKUP_NO_X = 6
FAIL_PYTHON = 7               # the callback into Python raised; the model's callback holds the exception


def python_error(e: CompiledFailure) -> Exception:
    """The Python path's exception for a :class:`CompiledFailure`."""
    code = int(e.args[0]) if e.args else 0
    a = float(e.args[1]) if len(e.args) > 1 else 0.0
    if code == FAIL_TRANSPORT_BELOW:
        from ..functions import TransportRangeError
        return TransportRangeError(f'transport operation: the position {a} is lower than zero')
    if code == FAIL_TRANSPORT_ABOVE:
        from ..functions import TransportRangeError
        return TransportRangeError(f'transport operation: the position {a} is higher than one')
    if code == FAIL_RANGE_START:
        from ..functions import TransportRangeError
        return TransportRangeError(f'transport operation: the range starts at {a}, which is lower than zero')
    if code == FAIL_RANGE_END:
        from ..functions import TransportRangeError
        return TransportRangeError(f'transport operation: the range ends at {a}, which is higher than one')
    if code == FAIL_INTERPOLATION_ARGS:
        from ..lookup import LookupError_
        return LookupError_(f'interpolation needs a lookup value and then x, y pairs; got {int(a)} value(s) '
                            'after it')
    if code == FAIL_LOOKUP_NO_X:
        from ..lookup import LookupError_
        return LookupError_('A lookup point has no x value')
    return RuntimeError(f'compiled code failed with code {code} {e.args[1:]}')
