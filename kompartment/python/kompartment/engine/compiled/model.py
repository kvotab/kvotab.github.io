"""A built model compiled with numba.

The Python engine already writes each model's algebra as numpy source (the
``at_instant`` and ``moving`` passes of :class:`~kompartment.engine.system.System`).
This module takes that source, rewrites the calls into Python objects it
contains -- lookup tables, the functions of the language not written inline,
what the recorders keep, a far-field path's release, the disruptive events'
flags -- into calls of :mod:`.runtime`, adds the assembly of the derivative as
loops over the same sparse structure :class:`~kompartment.engine.assembly.Assembler`
uses, and compiles the lot into functions of fixed signature:

    rhs(t, y, out, P, X, W, IW, cb)          the derivative, into ``out``
    store(t, y, P, X, W, IW, cb) -> int      a step accepted: what the recorders keep
    event_values(t, y, out, P, X, W, IW, cb) the discrete events' functions
    fire(t, y, which, P, X, W, IW, cb) -> int  what firing events does to the recorders

and one for the results: ``algebraic_rows``, the slots asked for at every
output time. The clock-only slots are worked out every ``min_change_time``
and interpolated between when the model asks for it, as ``at_instant`` does.

``P`` and ``X`` are the system's own parameter and algebraic arrays; ``W``
(float64) and ``IW`` (int64) hold everything else a run reads or keeps --
the arrays the generated code indexes with among them, so that no array is
frozen into the compiled code, and what a far-field path on cells whose
settings move keeps for the compiled refresh of its rates (:mod:`.farfield`).
``cb`` is the callback into Python for what is worked out there (``HOOK_``):
a semi-analytical far-field path; and a path whose settings move, when its
refresh hands it over -- to hold the matched layers just laid out, or to
raise what the Python refresh raises. The same arithmetic in the same order
as the Python passes and assembler, so the compiled model is the Python one
to the last bit.

The source is written to a cache directory under a hash of its contents
(``KOMPARTMENT_CACHE``, else the user's cache directory), and numba caches
the compiled code beside it: the same code compiles once per machine, and
the worker processes of a probabilistic or a split run load it from there.
Every model compiles; :func:`compile_model` raises :class:`NotCompiled` only
without numba, or for generated code it does not recognise.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from numba import types

from .. import functions as _functions
from . import NotCompiled
from . import farfield as _farf
from .runtime import (FIRE_CODES, FUNCTION_NAMES, INTERPOLATION_CODES, RECORDER_CODES, RECW, RUNTIME_IMPORTS,
                      TUPLE_FUNCTIONS)

#: What the callback into Python is asked to do for far-field path k: the
#: code is ``HOOKS * k`` plus one of these.
HOOK_RELEASE = 0     # a semi-analytical path's release, into X
HOOK_REFRESH = 1     # a path whose settings move, handed over by its compiled refresh: refreshed in Python
HOOK_STORE = 2       # a semi-analytical path told of a step accepted
HOOKS = 4
#: Each min/max's history starts with room for this many entries; a run that
#: needs more is run again with twice the room.
HISTORY_CAPACITY = 65536
_ALLOWED_NP = {
    'np.abs', 'np.sqrt', 'np.exp', 'np.log', 'np.log10', 'np.log2', 'np.sin', 'np.cos', 'np.tan', 'np.sinh',
    'np.cosh', 'np.tanh', 'np.arcsin', 'np.arccos', 'np.arctan', 'np.ceil', 'np.floor', 'np.sign',
    'np.arctan2', 'np.hypot', 'np.power', 'np.where', 'np.minimum', 'np.maximum',
    'np.arcsinh', 'np.arccosh', 'np.arctanh',
}
_CACHE: Dict[str, Any] = {}


def _compiler_stamp() -> str:
    """A hash of the code a generated module is compiled against -- this
    module, the runtime it calls and the far-field refresh that calls, the
    solvers whose signatures it takes. numba checks a cached function
    against its own file alone, so a model whose generated code is unchanged
    would otherwise load machine code compiled against an older runtime;
    with this in the generated code, a change to any of them compiles every
    model afresh."""
    here = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in ('model.py', 'runtime.py', 'farfield.py', 'solvers.py', '__init__.py'):
        try:
            h.update((here / name).read_bytes())
        except OSError:
            h.update(name.encode())
    return h.hexdigest()[:16]


COMPILER_STAMP = _compiler_stamp()


def cache_dir() -> Path:
    base = os.environ.get('KOMPARTMENT_CACHE')
    if base:
        root = Path(base)
    elif sys.platform == 'darwin':
        root = Path.home() / 'Library' / 'Caches' / 'kompartment'
    else:
        root = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'kompartment'
    d = root / 'compiled'
    d.mkdir(parents=True, exist_ok=True)
    return d


class HistoryFull(Exception):
    """A recorder's history ran out of room: the run is made again with more."""


class Callback(types.WrapperAddressProtocol):
    """A Python function as the ``int64(float64, float64)`` the compiled code
    calls. An exception it raises is kept in ``error``, and the call answers
    -1, which ends the solve."""

    _PROTO = ctypes.CFUNCTYPE(ctypes.c_int64, ctypes.c_double, ctypes.c_double)

    def __init__(self, fn: Any) -> None:
        self.error: Optional[BaseException] = None

        def call(a: float, b: float) -> int:
            try:
                return int(fn(a, b))
            except BaseException as e:  # noqa: BLE001 - handed back to the caller of the solve
                self.error = e
                return -1

        self._c = self._PROTO(call)

    def __wrapper_address__(self) -> int:
        return ctypes.cast(self._c, ctypes.c_void_p).value

    def signature(self) -> Any:
        from .solvers import CB_SIG
        return CB_SIG


class CompiledModel:
    """A system's compiled derivative and the arrays a run of it reads."""

    def __init__(self, system: Any, module: Any, layout: Dict[str, Any], int_consts: np.ndarray,
                 float_consts: np.ndarray) -> None:
        self.system = system
        self.module = module
        self.int_consts = int_consts
        self.float_consts = float_consts
        self.rhs = module.rhs
        self.store = module.store
        self.algebraic_rows = module.algebraic_rows
        self.layout = layout
        # Called from Python by their compiled entry points, past numba's
        # dispatcher, which on a small model costs more than the call.
        self._rhs = _entry_point(module.rhs)
        self._store = _entry_point(module.store)
        self._event_values = _entry_point(module.event_values)
        self.has_store = bool(layout['mems'] or layout['semi'])
        # The callback the compiled code makes into Python for the blocks
        # worked out there -- or none to make.
        from .solvers import no_callback
        self.py_callback: Any = Callback(self._hook) if (layout['semi'] or layout['farf_moving']) else no_callback
        self.capacity = layout['capacity']
        self.W = np.zeros(layout['nw'])
        self.IW = np.zeros(layout['niw'], dtype=np.int64)
        a, b = layout['ic']
        self.IW[a:b] = int_consts
        self._put_floats()
        # How many entries of each min/max history the system's own lists hold.
        self._synced: Dict[int, int] = {}

    def _put_floats(self) -> None:
        a, b = self.layout['fc']
        self.W[a:b] = self.float_consts

    def _size_w(self) -> None:
        L = self.layout
        need = L['hb'] + 2 * self.capacity * L['nmem']
        if self.W.size < max(need, 1):
            self.W = np.zeros(max(need, 1))
            self._put_floats()

    def load(self) -> None:
        """Brings ``W`` and ``IW`` up to date with the system: its tables (a
        parameter may have moved a point), its far-field weights and the
        constant part of the derivative's matrix, the events' flags, the
        far-field paths whose settings move as the Python path holds them,
        and the recorders as a run starts them (after ``prime_recorders``)."""
        self.load_invariants()
        self.load_recorders()

    def load_invariants(self) -> None:
        """What :meth:`load` brings up to date but the recorders: all that
        follows from the parameters, after the system's invariant pass, and
        the far-field paths whose settings move."""
        s = self.system
        L = self.layout
        self._size_w()
        W, IW = self.W, self.IW
        W[0] = math.nan
        IW[0] = self.capacity
        for k, tab in enumerate(s.TAB):
            if tab.n != L['tab_n'][k]:
                raise NotCompiled('a lookup table has changed its number of points since the model was compiled')
            xo, yo = L['tab_x'][k], L['tab_y'][k]
            W[xo:xo + tab.n] = tab.xa
            W[yo:yo + tab.n] = tab.ya
            base = L['td'] + 5 * k
            IW[base:base + 5] = (xo, yo, tab.n, INTERPOLATION_CODES.get(tab.interpolation, 0),
                                 1 if tab._wraps else 0)
        if L['ndis']:
            W[L['dis']:L['dis'] + L['ndis']] = s.DIS[:L['ndis']]
        self.load_clock()
        for k, F in enumerate(s.FARF):
            if k in L['semi'] or k in L['farf_moving']:
                continue
            F.refresh(s.X)
            wo = L['farf_w'][k]
            W[wo:wo + F.rel_w.size] = F.rel_w.ravel()
        # The derivative's matrix where the compiled assembly does not write
        # it on every call -- the constant terms, the rates read from slots
        # that never move, the far-field paths' cell rates -- as the Python
        # assembler sets it (``Assembler._set_linear``), but for a path whose
        # settings move: that one keeps the state a run starts it with, from
        # the Python path (``restart``, or what the Python passes left there).
        # Refreshed here, from whatever X holds, it would lay its matched
        # layers out at an instant not the run's, or raise for one long gone.
        X = s.X
        data = W[L['data']:L['data'] + L['nnz']]
        for kind, d, pos in s._assemble._lin:
            if kind == 'xsign':
                slots, sign = d
                data[pos] = X[slots] * sign
            elif kind == 'xx':
                a, b, sign = d
                data[pos] = X[a] * X[b] * sign
            elif kind == 'const':
                data[pos] = d
            elif kind == 'farf' and s.FARF.index(d) not in L['farf_moving']:
                data[pos] = d.vals.ravel()   # refreshed above
        for k in L['farf_moving']:
            self._take_path(k)

    def load_clock(self) -> None:
        """The clock interpolation the system is set to (``min_change_time``
        and where it counts from), with nothing worked out yet: what
        ``use_clock_interpolation`` leaves, which the runner calls before
        every span."""
        s = self.system
        ci = self.layout['ci']
        self.W[0] = math.nan
        self.W[ci] = s._min_change
        self.W[ci + 1] = s._origin
        self.W[ci + 2] = math.nan
        self.W[ci + 3] = math.nan

    def load_recorders(self) -> None:
        """Every recorder's state, history and all, from the system's own
        (after ``prime_recorders``, or what a run left there)."""
        s = self.system
        L = self.layout
        longest = max((len(s.MEM[m].history.t) for m in L['mems']), default=0)
        while longest > self.capacity:
            self.capacity *= 2
        self._size_w()
        W, IW = self.W, self.IW
        IW[0] = self.capacity
        cap = self.capacity
        for m in L['mems']:
            rec = s.MEM[m]
            h = rec.history
            n = len(h.t)
            to = L['hb'] + 2 * cap * m
            W[to:to + n] = h.t
            W[to + cap:to + cap + n] = h.v
            IW[L['hc'] + m] = n
            self._synced[m] = n
            base = L['ro'] + RECW * m
            W[base] = h.last_time
            W[base + 1] = h.last_value
            W[base + 2] = float(rec.sign)
            W[base + 3] = 1.0 if rec.recording else 0.0
            W[base + 4] = rec.total_time
            W[base + 5] = rec.last_time
            W[base + 6] = rec.reset_sum
            W[base + 7] = float(RECORDER_CODES[rec.kind])

    def sync_histories(self) -> None:
        """The recorders as the compiled run has them, onto the system's own:
        their histories -- only what changed, since a history is only ever
        added to or has its last entry rewritten, so the entries before the
        last one handed over last time are as they were -- and whether each
        records, for how long, since when and from what sum. And the
        far-field paths whose settings move, as their compiled refresh left
        them: what Python code reading the system mid-run refreshes from."""
        s = self.system
        L = self.layout
        cap = self.capacity
        W = self.W
        for m in L['mems']:
            n = int(self.IW[L['hc'] + m])
            to = L['hb'] + 2 * cap * m
            rec = s.MEM[m]
            h = rec.history
            frm = max(0, min(self._synced.get(m, 0), len(h.t), n) - 1)
            h.t[frm:] = W[to + frm:to + n].tolist()
            h.v[frm:] = W[to + cap + frm:to + cap + n].tolist()
            self._synced[m] = n
            base = L['ro'] + RECW * m
            rec.recording = bool(W[base + 3] != 0.0)
            rec.total_time = float(W[base + 4])
            rec.last_time = float(W[base + 5])
            rec.reset_sum = float(W[base + 6])
        for k in L['farf_moving']:
            self._hand_path(k)

    def write_back(self) -> None:
        """Puts what a compiled run kept -- the recorders, the far-field paths
        whose settings move -- on the system, where its results are read
        from, and tells the system that ``X`` no longer holds the instant its
        cache thinks it does."""
        self.sync_histories()
        self.system._clock_at = math.nan

    def _take_path(self, k: int) -> None:
        """Far-field path k (its settings move) as the Python path's object
        holds it, into W: its rates into the derivative's matrix data."""
        L = self.layout
        _farf.take(self.system.FARF[k], self.W, L['data'], L['farf_state'][k], L['farf_pos'][k])

    def _hand_path(self, k: int) -> None:
        """Far-field path k (its settings move) as the compiled run holds it
        in W, onto the Python path's object."""
        L = self.layout
        _farf.hand(self.system.FARF[k], self.W, L['data'], L['farf_state'][k], L['farf_pos'][k])

    def _hook(self, t: float, code: float) -> int:
        """What the compiled code asks Python for (``HOOK_``): the state is at
        W[yb:], X is the system's own."""
        s = self.system
        k, kind = divmod(int(code), HOOKS)
        F = s.FARF[k]
        yb = self.layout['yb']
        y = self.W[yb:yb + s.nstate]
        if kind == HOOK_RELEASE:
            F.release(y, s.X, t)
        elif kind == HOOK_STORE:
            F.store(t, y, s.X)
        elif kind == HOOK_REFRESH:
            # The compiled refresh laid matched layers out, or came to a
            # setting the Python refresh raises on: the path handed to the
            # Python one, which holds the layers from now on, or raises --
            # and handed back as far as it got.
            self._hand_path(k)
            try:
                F.refresh(s.X)
            finally:
                self._take_path(k)
        return 0

    def python_error(self) -> Optional[BaseException]:
        """What the callback into Python raised, if it raised."""
        return getattr(self.py_callback, 'error', None)

    def _make_room(self) -> None:
        """More room before a step or an event is recorded, where a history
        might run out of it: each adds at most one entry to each. Made
        beforehand, since recording again after a history ran out would work
        a running mean out from a clock it had already moved on."""
        L = self.layout
        if L['nmem'] and int(self.IW[L['hc']:L['hc'] + L['nmem']].max()) >= self.capacity:
            self.grow_in_place()

    def store_step(self, t: float, y: np.ndarray, grow: bool = False) -> None:
        """``System.store_step`` on the compiled arrays. A history that runs
        out of room raises :class:`HistoryFull` -- or, with ``grow``, is
        given more first."""
        if not self.has_store:
            return
        if grow:
            self._make_room()
        yy = _floats(y)
        while self._raising(self._store, float(t), yy, self.system.P, self.system.X, self.W, self.IW,
                            self.py_callback) != 0:
            if not grow:
                raise HistoryFull()
            self.grow_in_place()

    def fire(self, which: Sequence[int], t: float, y: np.ndarray, grow: bool = False) -> None:
        """``Events.fire`` on the compiled arrays; ``grow`` as for :meth:`store_step`."""
        mask = np.zeros(max(1, self.layout['nev']), dtype=np.int64)
        for i in which:
            mask[int(i)] = 1
        if grow:
            self._make_room()
        yy = np.ascontiguousarray(y, dtype=float)
        while self._raising(self.module.fire, float(t), yy, mask, self.system.P, self.system.X, self.W, self.IW,
                            self.py_callback) != 0:
            if not grow:
                raise HistoryFull()
            self.grow_in_place()

    def derivative(self, t: float, y: np.ndarray) -> np.ndarray:
        """The derivative at (t, y), a fresh array -- ``System.rhs``, compiled."""
        out = np.empty(self.system.nstate)
        try:
            self._rhs(float(t), _floats(y), out, self.system.P, self.system.X, self.W, self.IW, self.py_callback)
        except Exception as e:  # noqa: BLE001 - what the Python path raises, see _raising
            raise self._python_error(e) from None
        return out

    def event_values(self, t: float, y: np.ndarray) -> np.ndarray:
        """``Events.fun``, compiled."""
        n = self.layout['nev']
        out = np.zeros(max(n, 1))
        self._raising(self._event_values, float(t), _floats(y), out, self.system.P, self.system.X, self.W, self.IW,
                      self.py_callback)
        return out[:n]

    def _raising(self, fn: Any, *args: Any) -> Any:
        """A call of the compiled code from Python, raising what the Python
        path would raise where the model's equations do."""
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001 - see _python_error
            raise self._python_error(e) from None

    def _python_error(self, e: BaseException) -> BaseException:
        """What the Python path raises for an exception out of the compiled
        code: the model's own error for a :class:`CompiledFailure` (what the
        callback into Python raised, for one that did), anything else as it is."""
        from . import FAIL_PYTHON, CompiledFailure, python_error
        if not isinstance(e, CompiledFailure):
            return e
        raised = self.python_error() if e.args and int(e.args[0]) == FAIL_PYTHON else None
        if raised is not None:
            self.py_callback.error = None
            return raised
        return python_error(e)

    def grow_in_place(self) -> None:
        """Twice the room for the histories, keeping everything a run holds:
        what precedes the histories in ``W`` is where it was, and the
        histories are written into their new room from the recorders."""
        self.sync_histories()
        old = self.W
        self.capacity *= 2
        L = self.layout
        self.W = np.zeros(max(L['hb'] + 2 * self.capacity * L['nmem'], 1))
        self.W[:L['hb']] = old[:L['hb']]
        self.load_recorders()

    def grow(self) -> None:
        """Twice the room for the histories, for a run that ran out of it."""
        self.capacity *= 2
        self._size_w()


def _entry_point(fn: Any) -> Any:
    """A compiled function's entry point for its one signature, which skips
    the dispatcher's type resolution -- the caller hands it exactly the types
    it was compiled for -- or the function itself."""
    try:
        return fn.overloads[fn.signatures[0]].entry_point
    except Exception:  # noqa: BLE001 - numba's internals moved: the dispatcher does the same
        return fn


def _floats(y: Any) -> np.ndarray:
    """``y`` as the contiguous float64 array the compiled code takes."""
    if isinstance(y, np.ndarray) and y.dtype == np.float64 and y.ndim == 1 and y.flags.c_contiguous:
        return y
    return np.ascontiguousarray(y, dtype=float)


def _why_not(system: Any) -> Optional[str]:
    """Why a model's derivative cannot be compiled: since every block has a
    compiled version or a callback into Python, nothing -- what is left are
    the checks :func:`_rewrite` makes on the generated code."""
    return None


_CALL = re.compile(r'\b(_f\d+)\(')


def _rewrite_calls(src: str, translate: Any) -> str:
    """``src`` with every call of a bound function (``_f12(a, b)``) replaced
    by ``translate(name, [arguments])``, the arguments rewritten first. The
    generated code holds no strings, so its brackets alone say where an
    argument ends."""
    out: List[str] = []
    pos = 0
    while True:
        m = _CALL.search(src, pos)
        if m is None:
            out.append(src[pos:])
            return ''.join(out)
        out.append(src[pos:m.start()])
        depth = 1
        j = m.end()
        cuts = [m.end()]
        while depth:
            c = src[j]
            if c in '([':
                depth += 1
            elif c in ')]':
                depth -= 1
            elif c == ',' and depth == 1:
                cuts.append(j + 1)
            j += 1
        bounds = [*cuts, j]
        args = [src[a:b - 1].strip() for a, b in zip(bounds, bounds[1:])]
        out.append(translate(m.group(1), [_rewrite_calls(a, translate) for a in args if a]))
        pos = j


def _rewrite(src: str, ns: Dict[str, Any], consts: Dict[str, np.ndarray], L: Dict[str, Any]) -> str:
    """One generated pass, as numba code over ``(t, y, X, P, W, IW)``."""
    out = src
    out = re.sub(r'^def (\w+)\(t, y, X\):', r'def \1(t, y, X, P, W, IW, cb):', out, flags=re.M)
    out = out.replace('T = _f64(t)', 'T = t')
    # The pass writes X in place; the compiled one returns nothing.
    out = re.sub(r'^    return X$', '    return', out, flags=re.M)
    out = out.replace('_tabs(TAB, ', 'tabs(W, IW, TD, ')
    out = re.sub(r'TAB\[(\d+)\]\.at\(', r'tab1(W, IW, TD, \1, ', out)
    out = re.sub(r'MEM\[(\d+)\]\.extreme\(t, ', r'extreme(W, IW, RO, HB, HC, IW[0], \1, t, ', out)
    out = re.sub(r'MEM\[(\d+)\]\.mean\(t, ', r'running_mean(W, IW, RO, HB, HC, IW[0], \1, t, ', out)
    out = re.sub(r'MEM\[(\d+)\]\.held\(t\)', r'snapshot(W, IW, HB, HC, IW[0], \1, t)', out)
    out = re.sub(r'MEM\[(\d+)\]\.delayed\(t, ', r'delayed(W, IW, HB, HC, IW[0], \1, t, ', out)

    def farf(m: 're.Match[str]') -> str:
        k = int(m.group(1))
        if k in L['semi']:
            # Worked out in Python, where the path keeps its history.
            return f'_py(cb, W, y, t, YB, {float(HOOKS * k + HOOK_RELEASE)!r})'
        call = f'release(y, X, W, FW{k}, FREL{k}, {L["farf_nrel"][k]}, FSLOT{k})'
        if k in L['farf_moving']:
            # Its rates and weights worked out again first, as
            # ``FarfPath.release`` refreshes them: compiled, the path handed
            # to Python only when the refresh asks for it.
            return f'farf_refresh(cb, y, t, X, W, FDIR{k}, YB, {float(HOOKS * k + HOOK_REFRESH)!r}); {call}'
        return call
    out = re.sub(r'FARF\[(\d+)\]\.release\(y, X(?:, t)?\)', farf, out)

    def dis(m: 're.Match[str]') -> str:
        idx = m.group(1)
        if re.fullmatch(r'\d+', idx):
            return f'W[DISO + {idx}]'
        sl = re.fullmatch(r'(\d+):(\d+)', idx)
        if sl:
            return f'W[DISO + {sl.group(1)}:DISO + {sl.group(2)}]'
        return f'W[DISO + {idx}]'
    out = re.sub(r'DIS\[([^\]]+)\]', dis, out)
    out = out.replace('_pow(', 'js_pow(').replace('_round(', 'js_round(')

    def func(name: str, args: List[str]) -> str:
        fn = ns.get(name)
        key = next((k for k, spec in _functions.FUNCTIONS.items() if spec.get('fn') is fn), None)
        if key is None or key not in FUNCTION_NAMES:
            raise NotCompiled(f"it calls {key or name}(), which has no compiled version")
        if key in TUPLE_FUNCTIONS:
            return f'{FUNCTION_NAMES[key]}(({", ".join(args)},))'
        return f'{FUNCTION_NAMES[key]}({", ".join(args)})'
    out = _rewrite_calls(out, func)
    # What is left may only be the arrays and numbers the code writer bound,
    # numpy's functions that numba compiles, and the helpers above.
    for m in re.finditer(r'\b(np\.\w+)\(', out):
        if m.group(1) not in _ALLOWED_NP:
            raise NotCompiled(f'it calls {m.group(1)}, which the compiled path does not take')
    for name in re.findall(r'\b(_[ak]\d+)\b', out):
        if name not in consts:
            value = ns.get(name)
            if not isinstance(value, np.ndarray):
                raise NotCompiled(f'the generated code names {name}, which is not an array')
            consts[name] = value
    if re.search(r'\b(TAB|MEM|FARF|DIS|_tabs|_f64)\b', out):
        raise NotCompiled('the generated code reaches for an object the compiled path does not replace')
    return out


def compile_model(system: Any) -> CompiledModel:
    """The system's derivative compiled, or :class:`NotCompiled` saying why not."""
    try:
        import numba  # noqa: F401
    except Exception:  # noqa: BLE001 - optional
        raise NotCompiled('numba is not installed') from None
    why = _why_not(system)
    if why:
        raise NotCompiled(f'the model is not one the compiled path takes: {why}')
    ns = system._ns
    n = system.nstate
    A = system._assemble
    classes = system.slot_class

    # --- the layout of W and IW ------------------------------------------------------------
    L: Dict[str, Any] = {}
    nw = 1                                   # W[0]: the instant the clock slots were worked out for
    mems = sorted({r.mem + off for r in system.recorders if r.mem >= 0 for off in range(r.width)})
    L['mems'] = mems
    nmem = (max(mems) + 1) if mems else 0
    L['ro'] = nw
    nw += RECW * nmem
    # The clock-only slots worked out every min_change_time: the interval,
    # its origin, the two instants held and their values (``at_instant``).
    nclock = int(system.clock_idx.size)
    L['nclock'] = nclock
    L['ci'] = nw
    nw += 4 + 2 * nclock
    L['tab_x'], L['tab_y'], L['tab_n'] = [], [], []
    for tab in system.TAB:
        L['tab_n'].append(tab.n)
        L['tab_x'].append(nw)
        nw += tab.n
        L['tab_y'].append(nw)
        nw += tab.n
    L['ndis'] = int(len(system.builder.disruption_layout))
    L['dis'] = nw
    nw += L['ndis']
    # The far-field paths on cells keep their release weights here, and a
    # path whose settings move, after them, the rest of what its compiled
    # refresh works with (``farfield.state_layout``). The semi-analytical
    # ones are worked out in Python, through the callback, from the state
    # copied to YB -- as a path whose settings move is when its refresh
    # hands it over.
    L['semi'] = {k for k, F in enumerate(system.FARF) if getattr(F, 'method', '') == 'semi-analytical'}
    L['farf_moving'] = {k for k, F in enumerate(system.FARF) if k not in L['semi']
                        and np.any(classes[F.setting_idx.ravel()] != 0)}
    L['farf_w'] = []
    L['farf_nrel'] = {}
    L['farf_state'] = {}
    for k, F in enumerate(system.FARF):
        L['farf_w'].append(nw)
        if k in L['semi']:
            continue
        L['farf_nrel'][k] = int(F.rel_idx.shape[1])
        if k in L['farf_moving']:
            L['farf_state'][k] = _farf.state_layout(F, nw)
            nw = L['farf_state'][k]['end']
        else:
            nw += F.rel_w.size
    L['yb'] = nw
    nw += n if (L['semi'] or L['farf_moving']) else 0
    L['nnz'] = int(A._A.data.size)
    L['data'] = nw
    nw += L['nnz']
    L['capacity'] = HISTORY_CAPACITY
    L['nmem'] = nmem
    L['hb'] = nw
    nw += 2 * HISTORY_CAPACITY * nmem
    L['nw'] = max(nw, 1)
    niw = 1                                  # IW[0]: the room each min/max history has
    L['td'] = niw
    niw += 5 * len(system.TAB)
    L['hc'] = niw
    niw += nmem
    L['niw'] = max(niw, 1)
    events = system.events
    L['nev'] = events.n if events is not None else 0

    # --- the passes ----------------------------------------------------------------------------
    consts: Dict[str, np.ndarray] = {}
    clock_src = _rewrite(system.source['at_instant'], ns, consts, L)
    moving_src = _rewrite(system.source['moving'], ns, consts, L)
    # The derivative's own moving pass, where it leaves out blocks only
    # results, recorders and events read (`_Builder._derivative_reads`):
    # `rhs` runs it, and everything that reads every slot runs `_moving`.
    deriv = system.source.get('moving_derivative')
    moving_d_src = _rewrite(deriv, ns, consts, L) if deriv else None

    # --- the derivative's matrix: which entries move, and how -----------------------------------
    lx_p, lx_s, lx_g, lq_p, lq_a, lq_b, lq_g = [], [], [], [], [], [], []
    for kind, data, pos in A._lin:
        if kind == 'xsign':
            slots, sign = data
            moving = classes[np.asarray(slots)] != 0
            lx_p.append(pos[moving])
            lx_s.append(np.asarray(slots)[moving])
            lx_g.append(np.asarray(sign, dtype=float)[moving])
        elif kind == 'xx':
            a, b, sign = data
            moving = (classes[np.asarray(a)] != 0) | (classes[np.asarray(b)] != 0)
            lq_p.append(pos[moving])
            lq_a.append(np.asarray(a)[moving])
            lq_b.append(np.asarray(b)[moving])
            lq_g.append(np.asarray(sign, dtype=float)[moving])
        # 'const' and 'farf' (settings that do not move) are loaded once per run.
    ax_p, ax_s, ax_g, ai_p, ai_s, af_p, af_h, af_y, af_r = [], [], [], [], [], [], [], [], []
    am_p, am_t, am_m = [], [], []
    for kind, data, pos in A._aff:
        if kind == 'xsign':
            slots, sign = data
            ax_p.append(pos)
            ax_s.append(np.asarray(slots))
            ax_g.append(np.asarray(sign, dtype=float))
        elif kind == 'x':
            ai_p.append(pos)
            ai_s.append(np.broadcast_to(np.asarray(data), pos.shape))
        elif kind == 'fail-rel':
            h, p_idx, r_idx = data
            af_p.append(pos)
            af_h.append(np.full(pos.size, int(h)))
            af_y.append(np.asarray(p_idx))
            af_r.append(np.asarray(r_idx))
        elif kind == 'mean':
            t_idx, m0 = data
            am_p.append(pos)
            am_t.append(np.asarray(t_idx))
            am_m.append(np.arange(m0, m0 + np.asarray(t_idx).size))

    def cat(parts: List[np.ndarray], dtype: Any) -> np.ndarray:
        return np.ascontiguousarray(np.concatenate(parts) if parts else np.zeros(0), dtype=dtype)

    I64, F64 = np.int64, np.float64
    consts.update({
        '_indptr': np.ascontiguousarray(A._indptr, dtype=I64), '_indices': np.ascontiguousarray(A._indices, dtype=I64),
        '_lxp': cat(lx_p, I64), '_lxs': cat(lx_s, I64), '_lxg': cat(lx_g, F64),
        '_lqp': cat(lq_p, I64), '_lqa': cat(lq_a, I64), '_lqb': cat(lq_b, I64), '_lqg': cat(lq_g, F64),
        '_axp': cat(ax_p, I64), '_axs': cat(ax_s, I64), '_axg': cat(ax_g, F64),
        '_aip': cat(ai_p, I64), '_ais': cat(ai_s, I64),
        '_afp': cat(af_p, I64), '_afh': cat(af_h, I64), '_afy': cat(af_y, I64), '_afr': cat(af_r, I64),
        '_amp': cat(am_p, I64), '_amt': cat(am_t, I64), '_amm': cat(am_m, I64),
        '_clock_idx': np.ascontiguousarray(system.clock_idx, dtype=I64),
    })
    for k, F in enumerate(system.FARF):
        if k in L['semi']:
            continue
        consts[f'FREL{k}'] = np.ascontiguousarray(F.rel_idx, dtype=I64)
        consts[f'FSLOT{k}'] = np.ascontiguousarray(F.release_slots, dtype=I64)
    consts['_semi_codes'] = np.array([float(HOOKS * k + HOOK_STORE) for k in sorted(L['semi'])])
    # Where each path's cell rates sit in the derivative's matrix; and, for
    # a path whose settings move, all its compiled refresh reads of it.
    L['farf_pos'] = {system.FARF.index(d): np.asarray(pos, dtype=np.int64)
                     for kind, d, pos in A._lin if kind == 'farf'}
    for k in sorted(L['farf_moving']):
        consts[f'FDIR{k}'] = _farf.directory(system.FARF[k], L['data'], L['farf_state'][k], L['farf_pos'][k])
    # What each recorder stores at a step (``System.store_step``): a delay
    # the value it delays, the others their own.
    store_slots = np.zeros(nmem, dtype=I64)
    for r in system.recorders:
        if r.mem >= 0:
            frm = r.aux['target'] if r.kind == 'delay' else r.entry
            for off in range(r.width):
                store_slots[r.mem + off] = frm.base + off
    consts['_store_mems'] = np.asarray(mems, dtype=I64)
    consts['_store_slots'] = store_slots
    # The discrete events: the slots their functions are read from, and what
    # firing each does (``Events.fire``), event by event in handler order.
    ev_slots = np.zeros(0, dtype=I64)
    fh_ptr, fh_mem, fh_what, fh_target, fh_summed = [0], [], [], [], []
    if events is not None:
        ev_slots = np.asarray(events._idx, dtype=I64)
        for i in range(events.n):
            for h in events.handlers.get(i, []):
                rec, off = h['rec'], h['off']
                fh_mem.append(rec.mem + off)
                fh_what.append(FIRE_CODES[h['action']])
                fh_target.append(rec.aux['target'].base + off)
                fh_summed.append(rec.state.base + off if rec.state is not None else -1)
            fh_ptr.append(len(fh_mem))
    consts.update({'_ev_slots': ev_slots, '_fh_ptr': np.asarray(fh_ptr, dtype=I64),
                   '_fh_mem': np.asarray(fh_mem, dtype=I64), '_fh_what': np.asarray(fh_what, dtype=I64),
                   '_fh_target': np.asarray(fh_target, dtype=I64), '_fh_summed': np.asarray(fh_summed, dtype=I64)})

    # --- the constants: read at run time from IW (integers) and W (floats,
    # ahead of the histories), never written into the compiled code -- numba
    # would freeze a global array into it, which makes a large model slow to
    # compile and impossible to cache.
    L['nw_fixed'] = L['hb']
    ints: List[np.ndarray] = []
    floats: List[np.ndarray] = []
    where: Dict[str, str] = {}
    ic = L['niw']
    fc = L['hb']
    for name, value in consts.items():
        arr = np.ascontiguousarray(value).ravel()
        if arr.dtype.kind in 'iub':
            arr = arr.astype(np.int64)
            where[name] = f'IW[{ic}:{ic + arr.size}]'
            ints.append(arr)
            ic += arr.size
        else:
            arr = arr.astype(np.float64)
            where[name] = f'W[{fc}:{fc + arr.size}]'
            floats.append(arr)
            fc += arr.size
    L['ic'] = (L['niw'], ic)
    L['fc'] = (L['hb'], fc)
    L['niw'] = max(ic, 1)
    L['hb'] = fc
    L['nw'] = max(fc + 2 * HISTORY_CAPACITY * nmem, 1)
    int_consts = np.concatenate(ints) if ints else np.zeros(0, dtype=np.int64)
    float_consts = np.concatenate(floats) if floats else np.zeros(0)

    scalars = {'TD': L['td'], 'RO': L['ro'], 'HB': L['hb'], 'HC': L['hc'],
               'DISO': L['dis'], 'DATA': L['data'], 'NNZ': L['nnz'], 'N': n, 'CI': L['ci'], 'NCLOCK': nclock,
               'RECW': RECW,
               'T0': float(system.start_time), 'T1': float(system.end_time)}
    for k in range(len(system.FARF)):
        scalars[f'FW{k}'] = L['farf_w'][k]
    scalars['YB'] = L['yb']

    source = _module_source(clock_src, moving_src, moving_d_src, scalars, where)
    key = hashlib.sha256(source.encode()).hexdigest()[:24]
    module = _load_module(key, source)
    return CompiledModel(system, module, L, int_consts, float_consts)


_NAME = re.compile(r'\b(_[A-Za-z][A-Za-z0-9_]*|FREL\d+|FSLOT\d+|FDIR\d+)\b')


def _with_constants(src: str, where: Dict[str, str]) -> str:
    """Every function in ``src`` with the constants it names sliced out of
    IW and W as it starts."""
    out: List[str] = []
    lines = src.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        if line.startswith('def '):
            # The body: every line up to the next one that is not indented.
            j = i + 1
            while j < len(lines) and (lines[j].startswith(' ') or not lines[j].strip()):
                j += 1
            body = '\n'.join(lines[i + 1:j])
            names = []
            for m in _NAME.finditer(body):
                name = m.group(1)
                if name in where and name not in names:
                    names.append(name)
            out.extend(f'    {name} = {where[name]}' for name in names)
            out.extend(lines[i + 1:j])
            i = j
            continue
        i += 1
    return '\n'.join(out)


def _module_source(clock_src: str, moving_src: str, moving_d_src: Optional[str], scalars: Dict[str, Any],
                   where: Dict[str, str]) -> str:
    header = [
        '# Generated by kompartment.engine.compiled.model -- a model\'s derivative, compiled.',
        f'# Compiled against {COMPILER_STAMP}.',
        'import numpy as np',
        'from numba import njit',
        'from pathlib import Path',
        'from kompartment.engine.compiled.solvers import PASS_SIG, RHS_SIG, STORE_SIG',
        f'from kompartment.engine.compiled.runtime import ({", ".join(RUNTIME_IMPORTS)}, pyhook as _py)',
    ]
    for name, value in scalars.items():
        header.append(f'{name} = {value!r}')
    body = []
    passes = [(clock_src, '_clock'), (moving_src, '_moving')]
    if moving_d_src:
        passes.append((moving_d_src, '_moving_d'))
    for src, name in passes:
        src = re.sub(r'^def \w+\(', f'def {name}(', src, flags=re.M)
        # Compiled once each, and called: a large model's passes inlined into
        # every function that runs them take many times longer to compile.
        body.append('@njit(PASS_SIG, cache=True, error_model="numpy")')
        body.append(src)
    body.append('''
@njit(cache=True, inline="always", error_model="numpy")
def _at_instant(t, y, X, P, W, IW, cb):
    # System.at_instant: the clock-only slots brought up to t, if they are
    # not there already -- worked out every min_change_time and interpolated
    # between when that is set.
    if t == W[0]:
        return
    mc = W[CI]
    if mc > 0 and NCLOCK > 0:
        origin = W[CI + 1]
        k = np.floor((t - origin) / mc)
        a = origin + k * mc
        b = a + mc
        if a != W[CI + 2]:
            if a == W[CI + 3]:
                for q in range(NCLOCK):
                    W[CI + 4 + q] = W[CI + 4 + NCLOCK + q]
            else:
                _clock(a, y, X, P, W, IW, cb)
                for q in range(NCLOCK):
                    W[CI + 4 + q] = X[_clock_idx[q]]
            W[CI + 2] = a
        if b != W[CI + 3]:
            _clock(b, y, X, P, W, IW, cb)
            for q in range(NCLOCK):
                W[CI + 4 + NCLOCK + q] = X[_clock_idx[q]]
            W[CI + 3] = b
        wgt = (t - a) / mc
        for q in range(NCLOCK):
            lo = W[CI + 4 + q]
            X[_clock_idx[q]] = lo + wgt * (W[CI + 4 + NCLOCK + q] - lo)
        W[0] = t
        return
    _clock(t, y, X, P, W, IW, cb)
    W[0] = t


@njit(cache=True, inline="always", error_model="numpy")
def _assemble(y, X, W, IW, out):
    data = W[DATA:DATA + NNZ]
    for k in range(_lxp.size):
        data[_lxp[k]] = X[_lxs[k]] * _lxg[k]
    for k in range(_lqp.size):
        data[_lqp[k]] = X[_lqa[k]] * X[_lqb[k]] * _lqg[k]
    for k in range(_axp.size):
        data[_axp[k]] = X[_axs[k]] * _axg[k]
    for k in range(_aip.size):
        data[_aip[k]] = X[_ais[k]]
    for k in range(_afp.size):
        data[_afp[k]] = X[_afh[k]] * y[_afy[k]] - X[_afr[k]]
    for k in range(_amp.size):
        data[_amp[k]] = X[_amt[k]] if W[RO + RECW * _amm[k] + 3] != 0.0 else 0.0
    for i in range(N):
        acc = 0.0
        for jj in range(_indptr[i], _indptr[i + 1]):
            c = _indices[jj]
            acc += data[jj] * (y[c] if c < N else 1.0)
        out[i] = acc


@njit(RHS_SIG, cache=True, error_model="numpy")
def rhs(t, y, out, P, X, W, IW, cb):
    _at_instant(t, y, X, P, W, IW, cb)
    _MOVING_D(t, y, X, P, W, IW, cb)
    _assemble(y, X, W, IW, out)


@njit(STORE_SIG, cache=True, error_model="numpy")
def store(t, y, P, X, W, IW, cb):
    _at_instant(t, y, X, P, W, IW, cb)
    _moving(t, y, X, P, W, IW, cb)
    full = 0
    for q in range(_store_mems.size):
        m = _store_mems[q]
        if not recorder_store(W, IW, RO, HB, HC, IW[0], m, t, X[_store_slots[m]]):
            full = 1
    # The semi-analytical paths record the instant too, after the recorders.
    for q in range(_semi_codes.size):
        _py(cb, W, y, t, YB, _semi_codes[q])
    return full


@njit(RHS_SIG, cache=True, error_model="numpy")
def event_values(t, y, out, P, X, W, IW, cb):
    # Events.fun: the discrete events' functions at (t, y).
    _at_instant(t, y, X, P, W, IW, cb)
    _moving(t, y, X, P, W, IW, cb)
    for i in range(_ev_slots.size):
        out[i] = X[_ev_slots[i]]


@njit(cache=True, error_model="numpy")
def fire(t, y, which, P, X, W, IW, cb):
    # Events.fire: what the events marked in which do to the recorders.
    _at_instant(t, y, X, P, W, IW, cb)
    _moving(t, y, X, P, W, IW, cb)
    full = 0
    for i in range(which.size):
        if which[i] == 0:
            continue
        for h in range(_fh_ptr[i], _fh_ptr[i + 1]):
            summed = y[_fh_summed[h]] if _fh_summed[h] >= 0 else 0.0
            if not recorder_fire(W, IW, RO, HB, HC, IW[0], _fh_mem[h], _fh_what[h], t, X[_fh_target[h]], summed):
                full = 1
    return full


@njit(cache=True, error_model="numpy")
def algebraic_rows(ts, Y, need, out, P, X, W, IW, cb):
    for i in range(ts.size):
        t = ts[i]
        y = Y[i]
        _at_instant(t, y, X, P, W, IW, cb)
        _moving(t, y, X, P, W, IW, cb)
        for j in range(need.size):
            out[i, j] = X[need[j]]
''')
    text = '\n\n'.join(body).replace('_MOVING_D(', '_moving_d(' if moving_d_src else '_moving(')
    return '\n'.join(header) + '\n\n' + _with_constants(text, where) + '\n'


def _write(path: Path, data: bytes) -> None:
    """``data`` as ``path``, written under a name of this process's own and
    put in place whole, so that a process reading it never reads half. A
    file another process has put there first is kept, as long as it says
    the same: older numba versions (0.60) file what they compile of a module
    by the time its source was written (0.68 by what it says), and writing
    it again would set aside what the first process compiled from it."""
    fd, made = tempfile.mkstemp(prefix=path.name + '.', suffix='.part', dir=str(path.parent))
    tmp: Optional[str] = made
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != data:
                os.replace(tmp, path)
                tmp = None
        except OSError:
            # A file system without links.
            os.replace(tmp, path)
            tmp = None
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _load_module(key: str, source: str) -> Any:
    if key in _CACHE:
        return _CACHE[key]
    d = cache_dir()
    path = d / f'km_{key}.py'
    if not path.exists() or path.read_text() != source:
        _write(path, source.encode())
    spec = importlib.util.spec_from_file_location(f'kompartment_compiled_{key}', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    _CACHE[key] = module
    return module
