"""A built model's derivative compiled with numba.

The Python engine already writes each model's algebra as numpy source (the
``at_instant`` and ``moving`` passes of :class:`~kompartment.engine.system.System`).
This module takes that source, rewrites the few calls into Python objects it
contains -- lookup tables, the functions of the language not written inline,
a min/max's history, a far-field path's release, the disruptive events' flags
-- into calls of :mod:`.runtime`, adds the assembly of the derivative as
loops over the same sparse structure :class:`~kompartment.engine.assembly.Assembler`
uses, and compiles the lot into two functions of fixed signature:

    rhs(t, y, out, P, X, W, IW)          the derivative, into ``out``
    store(t, y, P, X, W, IW) -> int      a step accepted: the min/max histories

and a third for the results: ``algebraic_rows``, the slots asked for at every
output time.

``P`` and ``X`` are the system's own parameter and algebraic arrays; ``W``
(float64) and ``IW`` (int64) hold everything else a run reads or keeps. The
same arithmetic in the same order as the Python passes and assembler, so the
compiled derivative is the Python one to the last bit.

The source is written to a cache directory under a hash of its contents
(``KOMPARTMENT_CACHE``, else the user's cache directory), and numba caches
the compiled code beside it: the same model structure compiles once per
machine, and the worker processes of a probabilistic run load it from there.

What is not compiled keeps the model on the Python path, and :func:`compile_model`
says why: discrete events, the blocks that remember other than a min/max, a
far-field path whose settings move during a run, a function of the language
with no compiled version.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .. import functions as _functions
from . import NotCompiled
from .runtime import FUNCTION_NAMES, INTERPOLATION_CODES

RHS_SIG = 'void(float64, float64[::1], float64[::1], float64[::1], float64[::1], float64[::1], int64[::1])'
STORE_SIG = 'int64(float64, float64[::1], float64[::1], float64[::1], float64[::1], int64[::1])'
#: Each min/max's history starts with room for this many entries; a run that
#: needs more is run again with twice the room.
HISTORY_CAPACITY = 65536
_ALLOWED_NP = {
    'np.abs', 'np.sqrt', 'np.exp', 'np.log', 'np.log10', 'np.log2', 'np.sin', 'np.cos', 'np.tan', 'np.sinh',
    'np.cosh', 'np.tanh', 'np.arcsin', 'np.arccos', 'np.arctan', 'np.ceil', 'np.floor', 'np.sign',
    'np.arctan2', 'np.hypot', 'np.power', 'np.where', 'np.minimum', 'np.maximum',
}
_CACHE: Dict[str, Any] = {}


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


class CompiledModel:
    """A system's compiled derivative and the arrays a run of it reads."""

    def __init__(self, system: Any, module: Any, layout: Dict[str, Any]) -> None:
        self.system = system
        self.module = module
        self.rhs = module.rhs
        self.store = module.store
        self.algebraic_rows = module.algebraic_rows
        self.layout = layout
        self.has_store = bool(layout['mems'])
        self.capacity = layout['capacity']
        self.W = np.zeros(layout['nw'])
        self.IW = np.zeros(layout['niw'], dtype=np.int64)
        # How many entries of each min/max history the system's own lists hold.
        self._synced: Dict[int, int] = {}

    def _size_w(self) -> None:
        L = self.layout
        need = L['hb'] + 2 * self.capacity * L['nmem']
        if self.W.size < max(need, 1):
            self.W = np.zeros(max(need, 1))

    def load(self) -> None:
        """Brings ``W`` and ``IW`` up to date with the system: its tables (a
        parameter may have moved a point), its far-field weights and the
        constant part of the derivative's matrix, the events' flags, and the
        min/max histories as a run starts them (after ``prime_recorders``)."""
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
        for k, F in enumerate(s.FARF):
            F.refresh(s.X)
            wo = L['farf_w'][k]
            W[wo:wo + F.rel_w.size] = F.rel_w.ravel()
        A = s._assemble
        A._key = None
        A.refresh(s.X)
        W[L['data']:L['data'] + L['nnz']] = A._A.data
        cap = self.capacity
        for m in L['mems']:
            rec = s.MEM[m]
            h = rec.history
            n = len(h.t)
            if n > cap:
                raise NotCompiled('a min/max history longer than the room kept for it')
            to = L['hb'] + 2 * cap * m
            W[to:to + n] = h.t
            W[to + cap:to + cap + n] = h.v
            IW[L['hc'] + m] = n
            self._synced[m] = n
            base = L['ro'] + 4 * m
            W[base] = h.last_time
            W[base + 1] = h.last_value
            W[base + 2] = float(rec.sign)
            W[base + 3] = 1.0 if rec.recording else 0.0

    def sync_histories(self) -> None:
        """The min/max histories as the compiled run has them, onto the
        system's own lists -- only what changed: a history is only ever
        added to or has its last entry rewritten, so the entries before the
        last one handed over last time are as they were."""
        s = self.system
        L = self.layout
        cap = self.capacity
        W = self.W
        for m in L['mems']:
            n = int(self.IW[L['hc'] + m])
            to = L['hb'] + 2 * cap * m
            h = s.MEM[m].history
            frm = max(0, min(self._synced.get(m, 0), len(h.t), n) - 1)
            h.t[frm:] = W[to + frm:to + n].tolist()
            h.v[frm:] = W[to + cap + frm:to + cap + n].tolist()
            self._synced[m] = n

    def write_back(self) -> None:
        """Puts what a compiled run kept -- the min/max histories -- on the
        system, where its results are read from, and tells the system that
        ``X`` no longer holds the instant its cache thinks it does."""
        self.sync_histories()
        self.system._clock_at = math.nan

    def grow(self) -> None:
        """Twice the room for the histories, for a run that ran out of it."""
        self.capacity *= 2
        self._size_w()


def _why_not(system: Any) -> Optional[str]:
    if system.events is not None:
        return 'it has discrete events'
    for r in system.recorders:
        if r.mem >= 0 and r.kind != 'min_max':
            return f"it has a {r.kind.replace('_', ' ')}, which keeps a history the compiled path does not"
    for kind, data, _ in system._assemble._aff:
        if kind == 'mean':
            return 'it has a running mean'
    classes = system.slot_class
    for F in system.FARF:
        if np.any(classes[F.setting_idx.ravel()] != 0):
            return 'a far-field path has a setting that moves during the run'
    return None


def _rewrite(src: str, ns: Dict[str, Any], consts: Dict[str, np.ndarray], L: Dict[str, Any]) -> str:
    """One generated pass, as numba code over ``(t, y, X, P, W, IW)``."""
    out = src
    out = re.sub(r'^def (\w+)\(t, y, X\):', r'def \1(t, y, X, P, W, IW):', out, flags=re.M)
    out = out.replace('T = _f64(t)', 'T = t')
    out = out.replace('_tabs(TAB, ', 'tabs(W, IW, TD, ')
    out = re.sub(r'TAB\[(\d+)\]\.at\(', r'tab1(W, IW, TD, \1, ', out)
    out = re.sub(r'MEM\[(\d+)\]\.extreme\(t, ', r'extreme(W, IW, RO, HB, HC, IW[0], \1, t, ', out)
    out = re.sub(r'FARF\[(\d+)\]\.release\(y, X\)', r'release(y, X, W, FW\1, FREL\1, FSLOT\1)', out)

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

    def func(m: 're.Match[str]') -> str:
        name = m.group(1)
        fn = ns.get(name)
        key = next((k for k, spec in _functions.FUNCTIONS.items() if spec.get('fn') is fn), None)
        if key is None or key not in FUNCTION_NAMES:
            raise NotCompiled(f"it calls {key or name}(), which has no compiled version")
        return FUNCTION_NAMES[key] + '('
    out = re.sub(r'\b(_f\d+)\(', func, out)
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
    nw += 4 * nmem
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
    L['farf_w'] = []
    for F in system.FARF:
        L['farf_w'].append(nw)
        nw += F.rel_w.size
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

    # --- the passes ----------------------------------------------------------------------------
    consts: Dict[str, np.ndarray] = {}
    clock_src = _rewrite(system.source['at_instant'], ns, consts, L)
    moving_src = _rewrite(system.source['moving'], ns, consts, L)

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
    })
    for k, F in enumerate(system.FARF):
        consts[f'FREL{k}'] = np.ascontiguousarray(F.rel_idx, dtype=I64)
        consts[f'FSLOT{k}'] = np.ascontiguousarray(F.release_slots, dtype=I64)
    store_slots = np.zeros(nmem, dtype=I64)
    for r in system.recorders:
        if r.mem >= 0:
            for off in range(r.width):
                store_slots[r.mem + off] = r.entry.base + off
    consts['_store_mems'] = np.asarray(mems, dtype=I64)
    consts['_store_slots'] = store_slots

    scalars = {'TD': L['td'], 'RO': L['ro'], 'HB': L['hb'], 'HC': L['hc'],
               'DISO': L['dis'], 'DATA': L['data'], 'NNZ': L['nnz'], 'N': n,
               'T0': float(system.start_time), 'T1': float(system.end_time)}
    for k in range(len(system.FARF)):
        scalars[f'FW{k}'] = L['farf_w'][k]

    source = _module_source(clock_src, moving_src, scalars)
    buf = io.BytesIO()
    np.savez(buf, **consts)
    data_bytes = buf.getvalue()
    key = hashlib.sha256(source.encode() + data_bytes).hexdigest()[:24]
    module = _load_module(key, source, data_bytes)
    return CompiledModel(system, module, L)


def _module_source(clock_src: str, moving_src: str, scalars: Dict[str, Any]) -> str:
    header = [
        '# Generated by kompartment.engine.compiled.model -- a model\'s derivative, compiled.',
        'import numpy as np',
        'from numba import njit',
        'from pathlib import Path',
        'from kompartment.engine.compiled.runtime import (js_pow, js_round, js_mod, js_rem, js_fix, js_ulp,',
        '    js_erfc, js_erf, tab1, tabs, extreme, history_add, release)',
        '_d = np.load(str(Path(__file__).with_suffix(".npz")))',
        'globals().update({k: np.ascontiguousarray(_d[k]) for k in _d.files})',
        'del _d',
    ]
    for name, value in scalars.items():
        header.append(f'{name} = {value!r}')
    body = []
    for src, name in ((clock_src, '_clock'), (moving_src, '_moving')):
        src = re.sub(r'^def \w+\(', f'def {name}(', src, flags=re.M)
        body.append('@njit(cache=True, inline="always", error_model="numpy")')
        body.append(src)
    body.append('''
@njit(cache=True, inline="always", error_model="numpy")
def _assemble(y, X, W, out):
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
    for i in range(N):
        acc = 0.0
        for jj in range(_indptr[i], _indptr[i + 1]):
            c = _indices[jj]
            acc += data[jj] * (y[c] if c < N else 1.0)
        out[i] = acc


@njit("''' + RHS_SIG + '''", cache=True, error_model="numpy")
def rhs(t, y, out, P, X, W, IW):
    if t != W[0]:
        _clock(t, y, X, P, W, IW)
        W[0] = t
    _moving(t, y, X, P, W, IW)
    _assemble(y, X, W, out)


@njit("''' + STORE_SIG + '''", cache=True, error_model="numpy")
def store(t, y, P, X, W, IW):
    if t != W[0]:
        _clock(t, y, X, P, W, IW)
        W[0] = t
    _moving(t, y, X, P, W, IW)
    full = 0
    for q in range(_store_mems.size):
        m = _store_mems[q]
        current = X[_store_slots[m]]
        if current != W[RO + 4 * m + 1]:
            if not history_add(W, IW, RO, HB, HC, IW[0], m, t, current):
                full = 1
    return full


@njit(cache=True, error_model="numpy")
def algebraic_rows(ts, Y, need, out, P, X, W, IW):
    for i in range(ts.size):
        t = ts[i]
        y = Y[i]
        if t != W[0]:
            _clock(t, y, X, P, W, IW)
            W[0] = t
        _moving(t, y, X, P, W, IW)
        for j in range(need.size):
            out[i, j] = X[need[j]]
''')
    return '\n'.join(header) + '\n\n' + '\n\n'.join(body) + '\n'


def _replace(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.part', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_module(key: str, source: str, data_bytes: bytes) -> Any:
    if key in _CACHE:
        return _CACHE[key]
    d = cache_dir()
    path = d / f'km_{key}.py'
    npz = d / f'km_{key}.npz'
    # Written under a name of this process's own and moved into place, so that
    # processes compiling the same model at once never read a half-written file.
    if not path.exists() or path.read_text() != source:
        _replace(path, source.encode())
    if not npz.exists() or npz.read_bytes() != data_bytes:
        _replace(npz, data_bytes)
    spec = importlib.util.spec_from_file_location(f'kompartment_compiled_{key}', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    _CACHE[key] = module
    return module
