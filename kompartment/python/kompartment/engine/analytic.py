"""df/dy read off the equations: exact, and assembled on the Jacobian's pattern.

The application differentiates its generated code in forward mode
(``src/sim/jacobian.js``); this does the same on the statements the engine
runs, with the same rules (``TANGENT_RULES`` in ``src/parser/compile.js``) --
the derivative of what is computed, which for the staircases (``floor``,
``round``, comparisons) is zero away from the jumps, for ``min``/``max`` the
tangent of the argument chosen, for a table the slope of its segment.

The derivative of the right-hand side has two parts. Most of it is direct: a
transfer that multiplies by its donor contributes its rate, decay its
constant, ingrowth its coefficient, a far-field path its cell matrix. The rest
comes through the algebraic slots that read the state -- a rate that depends
on a concentration, a solubility limit, a waste package's release -- and is
the chain rule: the contribution's derivative with respect to the slot, times
the slot's gradient. The gradients of those slots are sparse rows whose
structure is known once the model is built; only their values are worked out
at each evaluation, in dependency order.

A model whose derivative this cannot write -- a function with no rule applied
to the state, a delay whose lag moves with the state -- is left to the
finite differences the solvers fall back on, as in the application.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..names import resolve_reference
from . import codegen
from .codegen import Leaf, Tree, apply_binary, call_value
from .farfield import FARF_EQUATION_KEYS

LN10 = math.log(10)
LN2 = math.log(2)
TWO_OVER_SQRT_PI = 1.1283791670955126


class NoDerivative(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(f'No derivative rule for {what}')
        self.what = what


def _zero_seed_guard(dA: Sequence[Any], tangent: Any) -> Any:
    """Zero where every live argument tangent is zero: a column the expression
    does not reach gets 0, not the 0/0 some rules would compute there."""
    live = [d for d in dA if d is not None]
    if not live or tangent is None:
        return tangent
    zero = np.ones(np.shape(tangent), dtype=bool) if np.ndim(tangent) else True
    for d in live:
        zero = zero & (np.asarray(d) == 0)
    if np.ndim(zero) == 0:
        return 0.0 if zero else tangent
    return np.where(zero, 0.0, tangent)


def _mul(a: Any, d: Any) -> Any:
    return None if d is None else a * d


def _add(*parts: Any) -> Any:
    live = [p for p in parts if p is not None]
    if not live:
        return None
    out = live[0]
    for p in live[1:]:
        out = out + p
    return out


def _const_exponent(t: Tree) -> Optional[float]:
    if t[0] == 'leaf' and t[1].kind == 'K' and np.ndim(t[1].index) == 0:
        return float(t[1].index)
    return None


def _power_rule(a: Any, b: Any, da: Any, db: Any, V: Any, exponent: Optional[float]) -> Any:
    if db is None and exponent is not None:
        if exponent == 0:
            return None
        if exponent == 1:
            return da
        if exponent == 2:
            return 2 * a * da
        if exponent == 0.5:
            return da / (2 * V)
        return exponent * codegen.js_pow(a, exponent - 1) * da
    if db is None:
        return b * codegen.js_pow(a, b - 1) * da
    if da is None:
        return np.where(np.asarray(a) > 0, V * np.log(np.where(np.asarray(a) > 0, a, 1.0)) * db, 0.0)
    pos = np.asarray(a) > 0
    safe = np.where(pos, a, 1.0)
    return np.where(pos, V * ((b / safe) * da + np.log(safe) * db), b * codegen.js_pow(a, b - 1) * da)


class Tangent:
    """Forward-mode derivative of one statement along one leaf."""

    def __init__(self, tables: Sequence[Any]) -> None:
        self.tables = tables

    def run(self, tree: Tree, values: List[Any], seed: int) -> Tuple[Any, Any]:
        self._values = values
        self._seed = seed
        self._pos = 0
        return self._walk(tree)

    def _leaf(self) -> Tuple[Any, Any]:
        k = self._pos
        self._pos += 1
        return self._values[k], (1.0 if k == self._seed else None)

    def _walk(self, t: Tree) -> Tuple[Any, Any]:
        kind = t[0]
        if kind == 'leaf':
            return self._leaf()
        if kind == 'neg':
            v, d = self._walk(t[1])
            return -v, (None if d is None else -d)
        if kind == 'bin':
            op = t[1]
            a, da = self._walk(t[2])
            b, db = self._walk(t[3])
            value = apply_binary(op, a, b)
            if op == '+':
                return value, _add(da, db)
            if op == '-':
                if db is None:
                    return value, da
                return value, (-db if da is None else da - db)
            if op == '*':
                if da is None and db is None:
                    return value, None
                return value, _add(_mul(b, da), _mul(a, db))
            if op == '/':
                if da is None and db is None:
                    return value, None
                if db is None:
                    return value, da / b
                if da is None:
                    return value, (-(value * db)) / b
                return value, (da - value * db) / b
            if op == '^':
                if da is None and db is None:
                    return value, None
                return value, _zero_seed_guard([da, db], _power_rule(a, b, da, db, value, _const_exponent(t[3])))
            return value, None
        if kind == 'cond':
            test, _ = self._walk(t[1])
            a, da = self._walk(t[2])
            b, db = self._walk(t[3])
            chosen = np.asarray(test) != 0
            value = np.where(chosen, a, b) if np.ndim(chosen) else (a if chosen else b)
            if da is None and db is None:
                return value, None
            da = 0.0 if da is None else da
            db = 0.0 if db is None else db
            tangent = np.where(chosen, da, db) if np.ndim(chosen) else (da if chosen else db)
            return value, tangent
        if kind == 'tab':
            leaf_value, _ = self._leaf()  # the table's index is never live
            arg, darg = self._walk(t[2])
            index = t[1].index
            value = self._read_tables(index, arg, slope=False)
            if darg is None:
                return value, None
            return value, self._read_tables(index, arg, slope=True) * darg
        if kind == 'call':
            key = t[1]
            parts = [self._walk(a) for a in t[2]]
            A = [p[0] for p in parts]
            dA = [p[1] for p in parts]
            value = call_value(key, A)
            if all(d is None for d in dA):
                return value, None
            return value, self._call_tangent(key, A, dA, value, t)
        raise ValueError(kind)

    def _read_tables(self, index: Any, arg: Any, slope: bool) -> Any:
        if np.ndim(index) == 0:
            table = self.tables[int(index)]
            return table.slope_at(arg) if slope else table.at(arg)
        which = np.asarray(index)
        out = np.empty(which.shape)
        xs = np.broadcast_to(np.asarray(arg, dtype=float), which.shape)
        for k in np.unique(which):
            sel = which == k
            table = self.tables[int(k)]
            out[sel] = table.slope_at(xs[sel]) if slope else table.at(xs[sel])
        return out

    def _call_tangent(self, key: str, A: List[Any], dA: List[Any], V: Any, t: Tree) -> Any:
        if key == 'power':
            return _zero_seed_guard(dA, _power_rule(A[0], A[1], dA[0], dA[1], V, _const_exponent(t[2][1])))
        if key in ('min', 'max'):
            out: Any = np.nan
            for i in range(len(A) - 1, -1, -1):
                d = dA[i] if dA[i] is not None else 0.0
                out = np.where(np.asarray(A[i]) == V, d, out)
            return out
        if key == 'sum':
            return _add(*dA)
        if key == 'mean':
            return _add(*dA) / len(A)
        if key == 'prod':
            p, dp = A[0], dA[0]
            for i in range(1, len(A)):
                nxt = p * A[i]
                dp = _add(_mul(A[i], dp) if dp is not None else None, _mul(p, dA[i]))
                p = nxt
            return dp
        a = A[0] if A else None
        da = dA[0] if dA else None
        rule = _RULES.get(key)
        if rule is None:
            if key in _STAIRS:
                return None
            raise NoDerivative(f'{key}()')
        tangent = rule(A, dA, V)
        if tangent is None and any(d is not None for d in dA) and key in _LIVE_OR_REFUSE:
            raise NoDerivative(f'{key}() with a table that depends on the state')
        return _zero_seed_guard(dA, tangent)


def _ramp(sign: float) -> Any:
    def rule(A: List[Any], dA: List[Any], V: Any) -> Any:
        if dA[0] is None or dA[1] is not None or dA[2] is not None:
            return None
        lo = np.minimum(A[1], A[2])
        hi = np.maximum(A[1], A[2])
        inside = (np.asarray(A[0]) > lo) & (np.asarray(A[0]) < hi)
        with np.errstate(all='ignore'):
            return np.where(inside, sign * dA[0] / (hi - lo), 0.0)
    return rule


def _smooth(sign: float) -> Any:
    def rule(A: List[Any], dA: List[Any], V: Any) -> Any:
        if dA[0] is None or dA[1] is not None or dA[2] is not None:
            return None
        pos = np.asarray(A[0]) > 0
        with np.errstate(all='ignore'):
            return np.where(pos, (sign * 2 * A[2] / np.where(pos, A[0], 1.0)) * V * (1 - V) * dA[0], 0.0)
    return rule


def _interp(kind: str) -> Any:
    from .functions import FUNCTIONS

    def rule(A: List[Any], dA: List[Any], V: Any) -> Any:
        if any(d is not None for d in dA[1:]):
            return None
        return FUNCTIONS[kind]['slope'](*A) * dA[0]
    return rule


_RULES = {
    'abs': lambda A, dA, V: np.sign(A[0]) * dA[0],
    'sqrt': lambda A, dA, V: dA[0] / (2 * V),
    'exp': lambda A, dA, V: V * dA[0],
    'log': lambda A, dA, V: dA[0] / A[0],
    'log10': lambda A, dA, V: dA[0] / (A[0] * LN10),
    'log2': lambda A, dA, V: dA[0] / (A[0] * LN2),
    'hypot': lambda A, dA, V: _add(_mul(A[0], dA[0]), _mul(A[1], dA[1])) / V,
    'sin': lambda A, dA, V: np.cos(A[0]) * dA[0],
    'cos': lambda A, dA, V: (-np.sin(A[0])) * dA[0],
    'tan': lambda A, dA, V: (1 + V * V) * dA[0],
    'asin': lambda A, dA, V: dA[0] / np.sqrt(1 - A[0] * A[0]),
    'acos': lambda A, dA, V: (-dA[0]) / np.sqrt(1 - A[0] * A[0]),
    'atan': lambda A, dA, V: dA[0] / (1 + A[0] * A[0]),
    'sinh': lambda A, dA, V: np.cosh(A[0]) * dA[0],
    'cosh': lambda A, dA, V: np.sinh(A[0]) * dA[0],
    'tanh': lambda A, dA, V: (1 - V * V) * dA[0],
    'asinh': lambda A, dA, V: dA[0] / np.sqrt(A[0] * A[0] + 1),
    'acosh': lambda A, dA, V: dA[0] / np.sqrt(A[0] * A[0] - 1),
    'atanh': lambda A, dA, V: dA[0] / (1 - A[0] * A[0]),
    'erf': lambda A, dA, V: TWO_OVER_SQRT_PI * np.exp(-A[0] * A[0]) * dA[0],
    'erfc': lambda A, dA, V: -TWO_OVER_SQRT_PI * np.exp(-A[0] * A[0]) * dA[0],
    'atan2': lambda A, dA, V: (_add(_mul(A[1], dA[0]), (None if dA[1] is None else -(A[0] * dA[1])))
                               / (A[0] * A[0] + A[1] * A[1])),
    'mod': lambda A, dA, V: (dA[0] if dA[1] is None else np.where(
        np.asarray(A[1]) == 0, dA[0] if dA[0] is not None else 0.0,
        (dA[0] if dA[0] is not None else 0.0) - np.floor(A[0] / np.where(np.asarray(A[1]) == 0, 1.0, A[1])) * dA[1])),
    'rem': lambda A, dA, V: (dA[0] if dA[1] is None else np.where(
        np.asarray(A[1]) == 0, np.nan,
        (dA[0] if dA[0] is not None else 0.0) - np.trunc(A[0] / np.where(np.asarray(A[1]) == 0, 1.0, A[1])) * dA[1])),
    'ulp': lambda A, dA, V: np.sign(A[0]) * 2.220446049250313e-16 * dA[0],
    'rampDown': _ramp(-1.0),
    'rampUp': _ramp(1.0),
    'smoothDown': _smooth(-1.0),
    'smoothUp': _smooth(1.0),
    'interpolationUseEndValues': _interp('interpolationUseEndValues'),
    'interpolationExtrapolation': _interp('interpolationExtrapolation'),
    'bq2mole': lambda A, dA, V: _add(
        None if dA[0] is None else _call('bq2mole', dA[0], A[1]),
        None if dA[1] is None else _call('bq2mole', A[0], dA[1])),
    'mole2bq': lambda A, dA, V: _add(
        None if dA[0] is None else _call('mole2bq', dA[0], A[1]),
        None if dA[1] is None else (-V * dA[1] / A[1])),
}
_STAIRS = {'ceil', 'floor', 'round', 'fix', 'sign', 'not', 'and', 'or', 'nand', 'nor', 'xor', 'eps', 'pi'}
_LIVE_OR_REFUSE = {'interpolationUseEndValues', 'interpolationExtrapolation'}


_HANDLED = {'power', 'min', 'max', 'sum', 'mean', 'prod'}


def _check_differentiable(tree: Tree, live: set) -> None:
    """Refuses, before any evaluation, a statement whose derivative along a
    live leaf would need a rule nobody wrote."""
    pos = [0]

    def walk(t: Tree) -> bool:
        kind = t[0]
        if kind == 'leaf':
            k = pos[0]
            pos[0] += 1
            return k in live
        if kind == 'neg':
            return walk(t[1])
        if kind == 'bin':
            a = walk(t[2])
            b = walk(t[3])
            return a or b
        if kind == 'cond':
            a = walk(t[1])
            b = walk(t[2])
            c = walk(t[3])
            return b or c or a
        if kind == 'tab':
            pos[0] += 1
            return walk(t[2])
        if kind == 'call':
            flags = [walk(a) for a in t[2]]
            if not any(flags):
                return False
            key = t[1]
            if key in _HANDLED or key in _STAIRS:
                return True
            if key in _LIVE_OR_REFUSE and any(flags[1:]):
                raise NoDerivative(f'{key}() with a table that depends on the state')
            if key in ('rampDown', 'rampUp', 'smoothDown', 'smoothUp') and any(flags[1:]):
                raise NoDerivative(f'{key}() whose ends depend on the state')
            if key not in _RULES:
                raise NoDerivative(f'{key}()')
            return True
        return False

    walk(tree)


def _call(key: str, *args: Any) -> Any:
    from .functions import FUNCTIONS
    return FUNCTIONS[key]['fn'](*args)


# --- the plan -----------------------------------------------------------------------------

class _StatementPlan:
    __slots__ = ('tree', 'leaves', 'width', 'outs', 'y_terms', 'x_terms', 'multiply', 'block', 'own')


def _as_index(index: Any, width: int) -> np.ndarray:
    return np.full(width, int(index), dtype=np.int64) if np.ndim(index) == 0 else np.asarray(index, dtype=np.int64)


NON_FINITE_AT_START = ('the generated Jacobian has a non-finite entry at the starting state (an exact derivative '
                       'may be infinite where sqrt or log meets an empty compartment), and an infinite entry is '
                       'not a matrix a solver can factorise')


def analytic_jacobian(system: Any, pattern: Any) -> Optional[Dict[str, Any]]:
    """``{'available', 'constant', 'evaluate'}`` for the analytic Jacobian, or
    ``{'available': False, 'reason'}`` when the model has something it cannot
    differentiate -- or, as the application's ``refuseNonFinite`` has it, a
    derivative that is infinite at the state and time the run starts from,
    where the singularities live (the square root of an empty compartment)."""
    try:
        made = _Analytic(system, pattern)
    except NoDerivative as e:
        return {'available': False, 'reason': f'no derivative rule for {e.what}'}
    try:
        with np.errstate(all='ignore'):
            at_start = made.evaluate(system.start_time, system.initial_state())
    except Exception:  # noqa: BLE001 - as the application: the model's arithmetic at the start says nothing here
        at_start = ()
    finally:
        system._clock_at = math.nan
    if at_start is None:
        return {'available': False, 'reason': NON_FINITE_AT_START}
    return made.result()


class _Analytic:
    def __init__(self, system: Any, pattern: Any) -> None:
        from .jacobian import state_dependencies
        self.system = system
        self.b = b = system.builder
        self.pattern = pattern
        self.n = system.nstate
        self.moving = b.slot_class
        deps = state_dependencies(system)
        # The gradients' structure: one sparse row per slot that reads the state.
        self.g_rows = sorted(deps)
        self.g_row_of = {s: k for k, s in enumerate(self.g_rows)}
        self.g_cols = [np.asarray(deps[s], dtype=np.int64) for s in self.g_rows]
        lengths = np.array([c.size for c in self.g_cols], dtype=np.int64)
        self.g_ptr = np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64)
        self.g_nnz = int(self.g_ptr[-1])
        self.tangent = Tangent(system.TAB)
        self._position_cache: Dict[Tuple[int, int], int] = {}
        # Where each (row, column) sits among the pattern's values.
        self._pat_key = pattern.row_idx.astype(np.int64) * self.n + pattern.col_of
        order = np.argsort(self._pat_key, kind='stable')
        self._pat_sorted = self._pat_key[order]
        self._pat_order = order
        budget_rows = np.zeros(self.n, dtype=bool)
        if b.budget is not None:
            budget_rows[b.budget['base']:b.budget['base'] + len(b.budget['terms']) * b.budget['nfam']] = True
        self.budget_rows = budget_rows
        self.plans: List[Any] = []
        self._plan_statements()
        self._plan_assembly()
        self.constant = self._is_constant()

    # --- positions ------------------------------------------------------------------------

    def pat_pos(self, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
        key = rows.astype(np.int64) * self.n + cols.astype(np.int64)
        k = np.searchsorted(self._pat_sorted, key)
        k = np.minimum(k, self._pat_sorted.size - 1)
        if not np.all(self._pat_sorted[k] == key):
            raise NoDerivative('an entry outside the Jacobian pattern')
        return self._pat_order[k]

    def g_pos(self, slot: int, cols: np.ndarray) -> np.ndarray:
        r = self.g_row_of[slot]
        row_cols = self.g_cols[r]
        k = np.searchsorted(row_cols, cols)
        return self.g_ptr[r] + k

    # --- the gradients of the slots that read the state -----------------------------------

    def _plan_statements(self) -> None:
        b = self.b
        for a in b.algebraic:
            if a.cls != 2:
                continue
            for s in b.alg_stmts[a.name]:
                if s.code is not None:
                    self.plans.append(self._special_plan(a))
                    continue
                W = max(1, s.width)
                outs = _as_index(s.out, W)
                leaves = codegen.leaves(s.tree)
                y_terms = []
                x_terms = []
                for p, leaf in enumerate(leaves):
                    if leaf.kind == 'y':
                        idx = _as_index(leaf.index, W)
                        dst = np.array([self.g_pos(int(o), np.array([c]))[0] for o, c in zip(outs, idx)],
                                       dtype=np.int64)
                        y_terms.append((p, dst))
                    elif leaf.kind == 'X':
                        idx = _as_index(leaf.index, W)
                        if not np.any(self.moving[idx] == 2):
                            continue
                        elem, src, dst = [], [], []
                        for i, (o, x) in enumerate(zip(outs, idx)):
                            if self.moving[x] != 2 or x not in self.g_row_of:
                                continue
                            r = self.g_row_of[int(x)]
                            cols = self.g_cols[r]
                            if not cols.size:
                                continue
                            elem.append(np.full(cols.size, i, dtype=np.int64))
                            src.append(self.g_ptr[r] + np.arange(cols.size, dtype=np.int64))
                            dst.append(self.g_pos(int(o), cols))
                        if elem:
                            x_terms.append((p, np.concatenate(elem), np.concatenate(src), np.concatenate(dst)))
                live = {p for p, _ in y_terms} | {p for p, *_ in x_terms}
                if live:
                    _check_differentiable(s.tree, live)
                plan = _StatementPlan()
                plan.tree = s.tree
                plan.leaves = leaves
                plan.width = W
                plan.outs = outs
                plan.y_terms = y_terms
                plan.x_terms = x_terms
                plan.multiply = s.multiply
                plan.block = a
                if s.multiply:
                    # X[out] *= expr: the product rule, the slot's own gradient
                    # (from the rate statement before) scaled by expr, plus the
                    # rate's value times expr's gradient.
                    own = []
                    for i, o in enumerate(outs):
                        if int(o) not in self.g_row_of:
                            continue
                        r = self.g_row_of[int(o)]
                        own.append((i, self.g_ptr[r], self.g_ptr[r + 1]))
                    plan.own = own  # type: ignore[attr-defined]
                self.plans.append(plan)

    def _special_plan(self, a: Any) -> Any:
        b = self.b
        if a.kind == 'farfield' and getattr(b.FARF[a.farf_index], 'method', '') == 'semi-analytical':
            return ('laplace', b.FARF[a.farf_index])
        if a.kind == 'farfield':
            F = b.FARF[a.farf_index]
            for x in F.setting_idx.ravel():
                if self.moving[x] == 2:
                    raise NoDerivative('a far-field path whose settings depend on the state')
            dst = np.concatenate([self.g_pos(int(F.release_slots[s]), F.rel_idx[s]) for s in range(F.slots)])
            return ('farfield', F, dst)
        rec = a.get('recorder')
        if rec is None:
            raise NoDerivative(a.kind)
        if rec.kind == 'delay':
            for off in range(a.width):
                if self.moving[rec.aux['delay'].base + off] == 2:
                    raise NoDerivative('a delay whose lag depends on the state: its value slides along the recorded '
                                       'history as the state changes, and that derivative is not one to guess at')
            return ('zero', a)
        if rec.kind == 'snapshot':
            return ('zero', a)
        return ('recorder', a, rec)

    def _gradients(self, y: np.ndarray, X: np.ndarray, t: float) -> np.ndarray:
        G = np.zeros(self.g_nnz)
        P = self.system.P
        for plan in self.plans:
            if isinstance(plan, tuple):
                self._special_gradient(plan, G, y, X, t)
                continue
            values = [self._leaf_value(leaf, y, X, P, t) for leaf in plan.leaves]
            if plan.multiply:
                factor, _ = self.tangent.run(plan.tree, values, -1)
                for i, lo, hi in plan.own:  # type: ignore[attr-defined]
                    f_i = factor[i] if np.ndim(factor) else factor
                    G[lo:hi] *= f_i
                base = self._rate_before(plan, X, factor)
            for p, dst in plan.y_terms:
                _, d = self.tangent.run(plan.tree, values, p)
                if d is None:
                    continue
                d = np.broadcast_to(np.asarray(d, dtype=float), (plan.width,))
                if plan.multiply:
                    d = d * base
                np.add.at(G, dst, d)
            for p, elem, src, dst in plan.x_terms:
                _, d = self.tangent.run(plan.tree, values, p)
                if d is None:
                    continue
                d = np.broadcast_to(np.asarray(d, dtype=float), (plan.width,))
                if plan.multiply:
                    d = d * base
                np.add.at(G, dst, d[elem] * G[src])
        return G

    def _rate_before(self, plan: Any, X: np.ndarray, factor: Any) -> np.ndarray:
        # The rate as it stood before the availability multiplied it in: the
        # slot now holds rate * factor.
        f = np.broadcast_to(np.asarray(factor, dtype=float), (plan.width,))
        with np.errstate(all='ignore'):
            return np.where(f != 0, X[plan.outs] / np.where(f != 0, f, 1.0), 0.0)

    def _special_gradient(self, plan: tuple, G: np.ndarray, y: np.ndarray, X: np.ndarray, t: float) -> None:
        kind = plan[0]
        if kind == 'laplace':
            self._laplace_gradient(plan[1], G, y, X, t)
            return
        if kind == 'farfield':
            F, dst = plan[1], plan[2]
            F.refresh(X)
            G[dst] += F.rel_w.ravel()
            return
        if kind == 'zero':
            return
        a, rec = plan[1], plan[2]
        mem = self.system.MEM
        for off in range(a.width):
            out = a.base + off
            if out not in self.g_row_of:
                continue
            if rec.kind == 'min_max':
                tgt = rec.aux['target'].base + off
                if X[out] == X[tgt] and tgt in self.g_row_of and self.moving[tgt] == 2:
                    r = self.g_row_of[tgt]
                    cols = self.g_cols[r]
                    G[self.g_pos(out, cols)] += G[self.g_ptr[r]:self.g_ptr[r + 1]]
            elif rec.kind == 'running_mean':
                el = mem[rec.mem + off].elapsed_at(t)
                st = rec.state.base + off
                if el > 0:
                    G[self.g_pos(out, np.array([st]))] += 1.0 / el
                else:
                    tgt = rec.aux['target'].base + off
                    if tgt in self.g_row_of and self.moving[tgt] == 2:
                        r = self.g_row_of[tgt]
                        cols = self.g_cols[r]
                        G[self.g_pos(out, cols)] += G[self.g_ptr[r]:self.g_ptr[r + 1]]

    def _laplace_gradient(self, F: Any, G: np.ndarray, y: np.ndarray, X: np.ndarray, t: float) -> None:
        """The release of a semi-analytical path along the state
        (``releaseTangent``): the weight of each source's current inflow times
        that inflow's gradient -- zero while the step is shorter than the time
        anything takes to come through."""
        cur = F.current_weights(t)
        if not cur.any():
            return
        n = F.nnuc
        for slot in range(F.slots):
            out = int(F.release_slots[slot])
            if out not in self.g_row_of:
                continue
            r_out = self.g_row_of[out]
            row_cols = self.g_cols[r_out]
            if not row_cols.size:
                continue
            acc = np.zeros(row_cols.size)
            o = slot // n
            for j in range(n):
                w = cur[slot * n + j]
                if w == 0:
                    continue
                for x, d in F.terms_into[o * n + j]:
                    scale = w
                    if d >= 0:
                        acc[np.searchsorted(row_cols, d)] += w * X[x]
                        scale = w * y[d]
                    if x in self.g_row_of and self.moving[x] == 2:
                        r = self.g_row_of[x]
                        cols = self.g_cols[r]
                        if cols.size:
                            acc[np.searchsorted(row_cols, cols)] += scale * G[self.g_ptr[r]:self.g_ptr[r + 1]]
            G[self.g_ptr[r_out]:self.g_ptr[r_out + 1]] += acc

    @staticmethod
    def _leaf_value(leaf: Leaf, y: np.ndarray, X: np.ndarray, P: np.ndarray, t: float) -> Any:
        k = leaf.kind
        if k == 'y':
            return y[leaf.index]
        if k == 'X':
            return X[leaf.index]
        if k == 'P':
            return P[leaf.index]
        if k == 'K':
            return leaf.index
        if k == 'T':
            return np.float64(t)
        if k in ('T0', 'T1', 'DIS', 'TAB'):
            return 0.0
        return 0.0

    # --- the assembly ---------------------------------------------------------------------

    def _plan_assembly(self) -> None:
        """Direct terms (row, column, value source) and chain terms (row, slot,
        coefficient source), from the same phases the derivative is made of."""
        b = self.b
        n = self.n
        direct: List[Tuple[np.ndarray, Any]] = []   # (pattern positions, value fn(y, X))
        chain: List[Tuple[np.ndarray, np.ndarray, np.ndarray, Any]] = []  # (elements, G src, J dst, coef fn)
        br = self.budget_rows

        def add_chain(rows: np.ndarray, slots: np.ndarray, coef: Any) -> None:
            elems, srcs, dsts = [], [], []
            for i, (r, x) in enumerate(zip(rows, slots)):
                if br[r] or self.moving[x] != 2 or int(x) not in self.g_row_of:
                    continue
                g = self.g_row_of[int(x)]
                cols = self.g_cols[g]
                if not cols.size:
                    continue
                elems.append(np.full(cols.size, i, dtype=np.int64))
                srcs.append(self.g_ptr[g] + np.arange(cols.size, dtype=np.int64))
                dsts.append(self.pat_pos(np.full(cols.size, r, dtype=np.int64), cols))
            if elems:
                chain.append((np.concatenate(elems), np.concatenate(srcs), np.concatenate(dsts), coef))

        for ph in b.phases:
            kind = ph[0]
            if kind == 'transfers':
                _, tgt, flux, sign = ph
                src_of = np.full(b.nflux, -1, dtype=np.int64)
                src_of[b.flux_mbd] = b.flux_mbd_src
                src = src_of[flux]
                rate = b.flux_rate[flux]
                keep = (src >= 0) & ~br[tgt]
                if keep.any():
                    pos = self.pat_pos(tgt[keep], src[keep])
                    r_k, s_k = rate[keep], sign[keep]
                    direct.append((pos, lambda y, X, r=r_k, s=s_k: s * X[r]))
                # d/dX[rate] = sign * (y[src] if multiplying by the donor else 1)
                mbd = src >= 0
                src_safe = np.where(mbd, src, 0)
                add_chain(tgt, rate, lambda y, X, s=sign, m=mbd, ss=src_safe: s * np.where(m, y[ss], 1.0))
            elif kind == 'x':
                _, tgt, xs = ph
                add_chain(tgt, xs, lambda y, X, k=tgt.size: np.ones(k))
            elif kind == 'waste':
                _, p_idx, m_idx, h, r_idx, _budget = ph
                pos_p = self.pat_pos(p_idx, p_idx)
                pos_m = self.pat_pos(m_idx, p_idx)
                direct.append((pos_p, lambda y, X, h=h, k=p_idx.size: -np.full(k, X[h])))
                direct.append((pos_m, lambda y, X, h=h, k=p_idx.size: np.full(k, X[h])))
                hs = np.full(p_idx.size, h, dtype=np.int64)
                add_chain(p_idx, hs, lambda y, X, p=p_idx: -y[p])
                add_chain(m_idx, hs, lambda y, X, p=p_idx: y[p])
                add_chain(m_idx, r_idx, lambda y, X, k=p_idx.size: -np.ones(k))
            elif kind == 'move':
                _, a_idx, second, lam_slot, share_slot = ph
                pos_a = self.pat_pos(a_idx, a_idx)
                direct.append((pos_a, lambda y, X, l=lam_slot, s=share_slot, k=a_idx.size:
                               -np.full(k, X[l] * X[s])))
                if second is not None and not br[second].all():
                    keep = ~br[second]
                    pos_b = self.pat_pos(second[keep], a_idx[keep])
                    direct.append((pos_b, lambda y, X, l=lam_slot, s=share_slot, k=int(keep.sum()):
                                   np.full(k, X[l] * X[s])))
                ls = np.full(a_idx.size, lam_slot, dtype=np.int64)
                ss = np.full(a_idx.size, share_slot, dtype=np.int64)
                add_chain(a_idx, ls, lambda y, X, s=share_slot, a=a_idx: -(X[s] * y[a]))
                add_chain(a_idx, ss, lambda y, X, l=lam_slot, a=a_idx: -(X[l] * y[a]))
                if second is not None:
                    add_chain(second, ls, lambda y, X, s=share_slot, a=a_idx: X[s] * y[a])
                    add_chain(second, ss, lambda y, X, l=lam_slot, a=a_idx: X[l] * y[a])
            elif kind == 'mean':
                _, s_idx, t_idx, mem = ph
                add_chain(s_idx, t_idx, lambda y, X, m=mem, k=s_idx.size: np.array(
                    [1.0 if self.system.MEM[j].recording else 0.0 for j in range(m, m + k)]))
            elif kind == 'coef':
                _, tgt, coef, src = ph
                keep = ~br[tgt]
                if keep.any():
                    pos = self.pat_pos(tgt[keep], src[keep])
                    c = coef[keep]
                    direct.append((pos, lambda y, X, c=c: c))
            elif kind == 'farf':
                F = self.system.FARF[ph[1]]
                pos = self.pat_pos(F.row_flat, F.col_flat)
                direct.append((pos, lambda y, X, F=F: (F.refresh(X), F.vals.ravel())[1]))
        self.direct = direct
        self.chain = chain

    def _is_constant(self) -> bool:
        """True when df/dy moves with neither the clock nor the state, so it can
        be factorised once and reused (``isConstant`` in src/sim/jacobian.js):
        structural and deliberately conservative. A rate -- of a transfer, a
        source, a dy/dt term, a far-field path's setting, a waste package's
        hazard and settings, an event's rate and shares -- that follows the
        clock or the state moves the matrix; so does any block that
        remembers. The one rate that reads the state and still has a constant
        derivative is a release out of a far-field path, or out of waste
        packages whose release does not follow the clock, written as a bare
        reference with ``multiply_by_donor`` off: a fixed weighted sum of the
        path's own cells, whose tangent is those weights."""
        b = self.b
        if any(r.mem >= 0 for r in b.recorders):
            return False
        # A semi-analytical path's release carries the inflow of the step
        # being taken with a weight that changes from step to step.
        if any(p.farf.laplace for p in b.farf_layout):
            return False
        moves = lambda a: a.name in b.on_state or a.name in b.on_clock  # noqa: E731
        paths = {p.name for p in b.farf_layout if not p.farf.laplace}
        paths |= {W.q for W in b.waste_layout if W.release_slot.name not in b.on_clock}

        def bare_release(a: Any) -> bool:
            if not paths or not a.get('asts'):
                return False
            if (a.block or {}).get('multiply_by_donor') is not False:
                return False
            for ast in a.asts:
                if getattr(ast, 'type', None) != 'ref' or (ast.indices or []):
                    return False
                q = resolve_reference(ast.name, a.system or '', lambda n: n in paths)
                if not q or q not in paths:
                    return False
            return True

        rates: List[Any] = []
        for blk in list(b.project.transfers) + list(b.project.inflows):
            a = b.alg_by_name.get(blk.get('qname') or blk.get('name'))
            if a is not None and not bare_release(a):
                rates.append(a)
        rates.extend(b.dydt_slots)
        for p in b.farf_layout:
            for key in FARF_EQUATION_KEYS:
                a = b.alg_by_name.get(f'{p.name}#{key}')
                if a is not None:
                    rates.append(a)
        for W in b.waste_layout:
            rates.extend([W.hazard_slot, W.setting['irf'], W.setting['degradation_rate']])
        for D in b.disruption_layout:
            rates.append(D.lambda_slot)
            rates.extend(D.shares)
        return not any(a is not None and moves(a) for a in rates)

    def evaluate(self, t: float, y: np.ndarray) -> np.ndarray:
        system = self.system
        X = system.evaluate_algebraic(t, y)
        with np.errstate(all='ignore'):
            G = self._gradients(y, X, t) if self.g_nnz else np.zeros(0)
            J = np.zeros(self.pattern.nnz)
            for pos, fn in self.direct:
                np.add.at(J, pos, fn(y, X))
            for elem, src, dst, coef in self.chain:
                c = np.asarray(coef(y, X), dtype=float)
                np.add.at(J, dst, c[elem] * G[src])
        if not np.all(np.isfinite(J)):
            return None  # type: ignore[return-value]
        return J

    def result(self) -> Dict[str, Any]:
        return {'available': True, 'reason': None, 'constant': self.constant, 'evaluate': self.evaluate}
