"""``df/dp``, differentiated rather than differenced.

A port of ``buildParamTangent`` in the application's ``src/sim/jacobian.js``:
the driving term of the forward sensitivity equations ``S' = J·S + df/dp``,
taken by the same forward-mode rules the analytic Jacobian uses
(:class:`~kompartment.engine.analytic.Tangent`), seeded on the parameters
instead of on the state. :mod:`kompartment.engine.localsens` uses it where it
is available, as the application does, and differences ``df/dp`` otherwise.

``pvp(t, y, w)`` is ``(df/dp)·w`` at ``(t, y)`` with the state held fixed: the
directional derivative along ``w``, a vector over the parameter slots. Every
algebraic slot's tangent is carried through all three passes -- the slots
worked out once for the run, those that move with the clock and those that read
the state -- in the builder's dependency order, and the derivative's assembly
is differentiated along it:

* a transfer's flux ``donor × rate`` loses its first term (the donor is held
  fixed), so it contributes ``donor × d(rate)``, or ``d(rate)`` where it does not
  multiply by the donor;
* a source, a compartment's dy/dt term and a running mean's integral contribute
  their slot's tangent;
* decay and ingrowth have coefficients from the half-lives and drop out;
* the mass-balance budget's rows get nothing, as in the application, whose
  parameter tangent writes them only along the state.

The blocks that remember: a min/max follows its target's tangent where the
target is the extreme, a running mean its target's only before any time has
passed, a snapshot and a delay nothing (a delay whose lag moves with a parameter
is refused). A lookup table read at the clock has no tangent, as there.

Refused, with the application's reasons, where it refuses: a model with no
parameters, a far-field path, a waste package or a disruptive event (each has
runtime pieces that differentiate along the state and not along a parameter), a
function with no derivative rule applied to something a parameter reaches, and
a derivative that is not a number at the start of the run.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from . import codegen
from .analytic import NoDerivative, Tangent, _check_differentiable

__all__ = ['build_param_tangent', 'param_tangent']


class _Refused(Exception):
    pass


def _leaf_value(system: Any, leaf: Any, y: np.ndarray, X: np.ndarray, t: float) -> Any:
    k = leaf.kind
    if k == 'y':
        return y[leaf.index]
    if k == 'X':
        return X[leaf.index]
    if k == 'P':
        return system.P[leaf.index]
    if k == 'K':
        return leaf.index
    if k == 'T':
        return np.float64(t)
    if k == 'T0':
        return np.float64(system.start_time)
    if k == 'T1':
        return np.float64(system.end_time)
    if k == 'DIS':
        return system.DIS[leaf.index]
    return 0.0  # a table's index: read by the 'tab' node, never as a value


def _as_index(index: Any, width: int) -> np.ndarray:
    return np.full(width, int(index), dtype=np.int64) if np.ndim(index) == 0 else np.asarray(index, dtype=np.int64)


class _Plan:
    """The statements in dependency order, what each reads that a parameter
    can move, and the assembly's terms."""

    def __init__(self, system: Any) -> None:
        self.system = system
        b = system.builder
        self.b = b
        self.n = system.nstate
        self.nalg = system.nalg
        self.tangent = Tangent(system.TAB)
        moves = np.zeros(max(1, self.nalg), dtype=bool)  # structurally reached by a parameter
        self.items: List[Any] = []
        for a in b.algebraic:
            for s in b.alg_stmts[a.name]:
                if s.code is not None:
                    self.items.append(self._special(a, moves))
                    continue
                W = max(1, s.width)
                outs = _as_index(s.out, W)
                leaves = codegen.leaves(s.tree)
                p_terms, x_terms = [], []
                for pos, leaf in enumerate(leaves):
                    if leaf.kind == 'P':
                        p_terms.append((pos, _as_index(leaf.index, W)))
                    elif leaf.kind == 'X':
                        idx = _as_index(leaf.index, W)
                        if np.any(moves[idx]):
                            x_terms.append((pos, idx))
                live = {pos for pos, _ in p_terms} | {pos for pos, _ in x_terms}
                if live:
                    _check_differentiable(s.tree, live)
                reached = np.zeros(W, dtype=bool)
                for _, idx in p_terms:
                    reached |= True
                for _, idx in x_terms:
                    reached |= moves[idx]
                if s.multiply:
                    reached |= moves[outs]
                moves[outs] = reached
                self.items.append(('tree', s, leaves, outs, W, p_terms, x_terms, bool(s.multiply)))
        self._plan_assembly()

    def _special(self, a: Any, moves: np.ndarray) -> Any:
        rec = a.get('recorder')
        if a.kind == 'farfield' or rec is None:
            raise _Refused('a far-field path, whose derivative along a parameter is not generated')
        for off in range(a.width):
            i = a.base + off
            if rec.kind in ('min_max', 'running_mean'):
                moves[i] = moves[rec.aux['target'].base + off]
            elif rec.kind == 'delay':
                if moves[rec.aux['delay'].base + off]:
                    raise _Refused('a delay whose lag depends on a parameter: its value slides along the '
                                   'recorded history, and that derivative is not one to guess at')
                moves[i] = False
            else:
                moves[i] = False
        return ('recorder', a, rec)

    def _plan_assembly(self) -> None:
        b, n = self.b, self.n
        budget = np.zeros(n, dtype=bool)
        if b.budget is not None:
            budget[b.budget['base']:b.budget['base'] + len(b.budget['terms']) * b.budget['nfam']] = True
        self.transfers = None
        self.xs: List[Any] = []
        self.means: List[Any] = []
        for ph in b.phases:
            kind = ph[0]
            if kind == 'transfers':
                _, tgt, flux, sign = ph
                keep = ~budget[tgt]
                src_of = np.full(b.nflux, -1, dtype=np.int64)
                src_of[b.flux_mbd] = b.flux_mbd_src
                self.transfers = (tgt[keep], flux[keep], sign[keep], b.flux_rate, src_of)
            elif kind == 'x':
                _, tgt, xs = ph
                keep = ~budget[tgt]
                self.xs.append((tgt[keep], xs[keep]))
            elif kind == 'mean':
                _, s_idx, t_idx, mem = ph
                self.means.append((s_idx, t_idx, mem))
            elif kind in ('waste', 'move', 'farf'):
                raise _Refused('a block whose derivative along a parameter is not generated')
            # 'coef': decay and ingrowth, whose coefficients are not parameters.

    # --- evaluation ---------------------------------------------------------------------

    def pvp(self, t: float, y: np.ndarray, w: np.ndarray) -> np.ndarray:
        system = self.system
        y = np.asarray(y, dtype=float)
        w = np.asarray(w, dtype=float)
        with np.errstate(all='ignore'):
            X = system.evaluate_algebraic(t, y)
            dX = np.zeros(max(1, self.nalg))
            for item in self.items:
                if item[0] == 'recorder':
                    self._recorder(item[1], item[2], X, dX, t)
                    continue
                _, s, leaves, outs, W, p_terms, x_terms, multiply = item
                terms = []
                for pos, idx in p_terms:
                    weight = w[idx]
                    if np.any(weight != 0):
                        terms.append((pos, weight))
                for pos, idx in x_terms:
                    weight = dX[idx]
                    if np.any(weight != 0):
                        terms.append((pos, weight))
                before = dX[outs] if multiply else None
                if not terms and (before is None or not np.any(before != 0)):
                    if multiply:
                        dX[outs] = 0.0
                    continue
                values = [_leaf_value(system, leaf, y, X, t) for leaf in leaves]
                d = np.zeros(W)
                for pos, weight in terms:
                    _, tangent = self.tangent.run(s.tree, values, pos)
                    if tangent is None:
                        continue
                    d = d + np.broadcast_to(np.asarray(tangent, dtype=float), (W,)) * weight
                if multiply:
                    # X[out] *= factor: the rate's own tangent scaled by the
                    # factor, plus the rate times the factor's tangent. The
                    # slot holds rate * factor, so the rate is read back out.
                    factor, _ = self.tangent.run(s.tree, values, -1)
                    f = np.broadcast_to(np.asarray(factor, dtype=float), (W,))
                    rate = np.where(f != 0, X[outs] / np.where(f != 0, f, 1.0), 0.0)
                    dX[outs] = before * f + rate * d
                else:
                    dX[outs] = d
            out = np.zeros(self.n)
            if self.transfers is not None:
                tgt, flux, sign, rate_slots, src_of = self.transfers
                donor = np.where(src_of >= 0, y[np.where(src_of >= 0, src_of, 0)], 1.0)
                dflux = dX[rate_slots] * donor
                out += np.bincount(tgt, weights=sign * dflux[flux], minlength=self.n)
            for tgt, xs in self.xs:
                out += np.bincount(tgt, weights=dX[xs], minlength=self.n)
            for s_idx, t_idx, mem in self.means:
                recording = np.array([1.0 if system.MEM[k].recording else 0.0
                                      for k in range(mem, mem + s_idx.size)])
                out[s_idx] += recording * dX[t_idx]
        return out

    def _recorder(self, a: Any, rec: Any, X: np.ndarray, dX: np.ndarray, t: float) -> None:
        for off in range(a.width):
            i = a.base + off
            if rec.kind == 'min_max':
                tgt = rec.aux['target'].base + off
                dX[i] = dX[tgt] if X[i] == X[tgt] else 0.0
            elif rec.kind == 'running_mean':
                tgt = rec.aux['target'].base + off
                el = self.system.MEM[rec.mem + off].elapsed_at(t)
                dX[i] = 0.0 if el > 0 else dX[tgt]
            else:
                dX[i] = 0.0


def build_param_tangent(system: Any) -> Dict[str, Any]:
    """``{'available': True, 'pvp', 'nparam'}``, or ``{'available': False,
    'reason'}`` where the model has something this does not differentiate
    (``buildParamTangent``)."""
    b = system.builder
    jac = system.jacobian or {}
    if not jac.get('available'):
        return {'available': False, 'reason': f"there is no analytic Jacobian: {jac.get('reason')}"}
    nparam = int(system.nparam)
    if not (nparam > 0):
        return {'available': False, 'reason': 'the model holds no parameters'}
    for what, layout in (('far-field path', b.farf_layout), ('waste package', b.waste_layout),
                         ('disruptive event', b.disruption_layout)):
        if len(layout or []):
            return {'available': False,
                    'reason': f'the model has a {what}, whose derivative along a parameter is not generated'}
    try:
        plan = _Plan(system)
    except NoDerivative as e:
        return {'available': False, 'reason': f'no derivative rule for {e.what}'}
    except _Refused as e:
        return {'available': False, 'reason': str(e)}
    # The same question the Jacobian's own tangent answers at build: whether
    # what it gives at the start of the run is a number. A seed of ones
    # exercises every parameter at once.
    try:
        probe = plan.pvp(system.start_time, system.initial_state(), np.ones(nparam))
    except Exception:  # noqa: BLE001 - the model's own arithmetic at the start says nothing about usability
        probe = None
    if probe is not None and not np.all(np.isfinite(probe)):
        return {'available': False, 'reason': 'df/dp has a non-finite entry at the starting state, and a driving '
                                              'term that is not a number is not one to integrate'}
    return {'available': True, 'pvp': plan.pvp, 'nparam': nparam}


def param_tangent(system: Any) -> Dict[str, Any]:
    """:func:`build_param_tangent`, built on first ask and kept on the system,
    as the application keeps it (``system.paramTangent()``)."""
    got: Optional[Dict[str, Any]] = getattr(system, '_param_tangent', None)
    if got is None:
        got = build_param_tangent(system)
        system._param_tangent = got
    return got
