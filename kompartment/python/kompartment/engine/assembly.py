"""The derivative, assembled as one sparse matrix product in the application's order.

Every term of a compartment model's right-hand side is either linear in the
state -- a flux ``rate * donor``, decay ``-lambda * y``, ingrowth, what fails
out of waste packages, an event's move, a far-field path's cell matrix -- or
does not multiply the state at all: an absolute flux, an inflow, a dy/dt term,
a release. So the derivative is one product

    dy/dt = A(X) [y; 1]

of a sparse matrix with the state and a one: the linear terms' coefficients in
the columns of the states they read, every other term in the last column.

``A`` has one entry per term, in the order the application adds the terms to
each state (its generated derivative adds them in the builder's phase order),
duplicates kept. The product is formed as the terms -- ``data * x[column]``,
each rounded on its own -- summed row by row in that order, by a compiled
kernel when numba is installed and by a weighted ``bincount`` otherwise; both
add sequentially from zero exactly as the generated code's ``out[i] += ...``
does. (A compiled sparse product would fuse the
multiply and the add and round once, which is more accurate and not the
application's number.) So the derivative is the application's to the last
bit, and a solver takes the application's steps.

The linear coefficients are rebuilt only when the slots they read can have
moved: never for constant rates, once per instant for rates read from a table
at the clock, on every call only for a rate that reads the state. The last
column is written on every call, from a handful of gathers.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp

#: The compiled row sums are used from this many terms up (always, since the
#: kernel is compiled once and cached on disk: one call is quicker than the
#: three numpy calls of the ordered ``bincount`` even on a small model).
KERNEL_TERMS = 0


def _rows_summed(indptr: np.ndarray, cols: np.ndarray, data: np.ndarray, y: np.ndarray, n: int,
                 out: np.ndarray) -> np.ndarray:  # pragma: no cover - compiled
    for i in range(n):
        acc = 0.0
        for jj in range(indptr[i], indptr[i + 1]):
            c = cols[jj]
            # Column n is the one of [y; 1]: data * 1.0 is data, exactly.
            acc += data[jj] * (y[c] if c < n else 1.0)
        out[i] = acc
    return out


_KERNEL: Any = None


def _kernel() -> Optional[Callable[..., np.ndarray]]:
    """The row sums compiled with numba when it is installed: the same
    arithmetic as the ordered ``bincount`` -- each product rounded, then added
    in order, never fused -- at the speed of a compiled sparse product."""
    global _KERNEL
    if _KERNEL is None:
        from ._numba import jit
        k = jit(_rows_summed)
        try:
            if k is not None:
                k(np.array([0, 1], dtype=np.int32), np.array([1], dtype=np.int32), np.ones(1), np.ones(1), 1,
                  np.empty(1))
        except Exception:  # noqa: BLE001 - numba present but refusing: go without
            k = None
        _KERNEL = k if k is not None else False
    return _KERNEL or None


class Assembler:
    """``assembler(t, y, X)`` -> the derivative. Built from a builder's phases."""

    def __init__(self, system: Any) -> None:
        b = system.builder
        self.system = system
        self.n = n = system.nstate
        rows: List[np.ndarray] = []
        cols: List[np.ndarray] = []
        seq: List[np.ndarray] = []           # the order the application adds the terms in
        lin: List[Tuple[str, Any, np.ndarray]] = []   # (kind, data, entry ids)
        aff: List[Tuple[str, Any, np.ndarray]] = []
        coef_slots: List[np.ndarray] = []
        moving = b.slot_class
        counter = [0]

        def entries(r: np.ndarray, c: Optional[np.ndarray], order: np.ndarray) -> np.ndarray:
            r = np.asarray(r, dtype=np.int64)
            ids = np.arange(counter[0], counter[0] + r.size, dtype=np.int64)
            counter[0] += r.size
            rows.append(r)
            cols.append(np.full(r.size, n, dtype=np.int64) if c is None else np.asarray(c, dtype=np.int64))
            seq.append(np.asarray(order, dtype=np.float64))
            return ids

        def linear(r: np.ndarray, c: np.ndarray, order: np.ndarray, kind: str, data: Any,
                   slots: Optional[np.ndarray] = None) -> None:
            if not np.asarray(r).size:
                return
            lin.append((kind, data, entries(r, c, order)))
            if slots is not None:
                coef_slots.append(np.asarray(slots, dtype=np.int64).ravel())

        def affine(r: np.ndarray, order: np.ndarray, kind: str, data: Any) -> None:
            if not np.asarray(r).size:
                return
            aff.append((kind, data, entries(r, None, order)))

        base = 0.0
        for ph in b.phases:
            kind = ph[0]
            if kind == 'transfers':
                _, tgt, flux, sign = ph
                src_of = np.full(b.nflux, -1, dtype=np.int64)
                src_of[b.flux_mbd] = b.flux_mbd_src
                src = src_of[flux]
                rate = b.flux_rate[flux]
                order = base + np.arange(tgt.size)
                mbd = src >= 0
                if mbd.any():
                    linear(tgt[mbd], src[mbd], order[mbd], 'xsign', (rate[mbd], sign[mbd]), rate[mbd])
                if (~mbd).any():
                    affine(tgt[~mbd], order[~mbd], 'xsign', (rate[~mbd], sign[~mbd]))
                base += tgt.size
            elif kind == 'x':
                _, tgt, xs = ph
                affine(tgt, base + np.arange(tgt.size), 'x', xs)
                base += tgt.size
            elif kind == 'waste':
                _, p_idx, m_idx, h, r_idx, budget = ph
                k = p_idx.size
                width = 3 if budget is not None else 2
                o = base + np.arange(k) * width
                hs = np.full(k, h, dtype=np.int64)
                # -fail into the intact inventory; fail - release into the
                # exposed one, as one term, as the application adds it.
                linear(p_idx, p_idx, o, 'xsign', (hs, -np.ones(k)), hs)
                affine(m_idx, o + 1, 'fail-rel', (h, p_idx, r_idx))
                if budget is not None:
                    affine(np.asarray(budget), o + 2, 'x', r_idx)
                base += k * width
            elif kind == 'move':
                _, a_idx, second, lam_slot, share_slot = ph
                k = a_idx.size
                width = 2 if second is not None else 1
                o = base + np.arange(k) * width
                ls = np.full(k, lam_slot, dtype=np.int64)
                ss = np.full(k, share_slot, dtype=np.int64)
                linear(a_idx, a_idx, o, 'xx', (ls, ss, -np.ones(k)), np.concatenate([ls, ss]))
                if second is not None:
                    linear(np.asarray(second), a_idx, o + 1, 'xx', (ls, ss, np.ones(k)), np.concatenate([ls, ss]))
                base += k * width
            elif kind == 'mean':
                _, s_idx, t_idx, mem = ph
                affine(s_idx, base + np.arange(s_idx.size), 'mean', (t_idx, mem))
                base += s_idx.size
            elif kind == 'coef':
                _, tgt, coef, src = ph
                linear(tgt, src, base + np.arange(tgt.size), 'const', coef)
                base += tgt.size
            elif kind == 'farf':
                F = system.FARF[ph[1]]
                linear(F.row_flat, F.col_flat, base + np.arange(F.row_flat.size), 'farf', F, F.setting_idx.ravel())
                base += F.row_flat.size
        all_rows = np.concatenate(rows) if rows else np.zeros(0, dtype=np.int64)
        all_cols = np.concatenate(cols) if cols else np.zeros(0, dtype=np.int64)
        all_seq = np.concatenate(seq) if seq else np.zeros(0)
        # CSR: rows in order, and within a row the terms in the order they are
        # added -- the phase order, then the entry's place in its phase.
        order = np.lexsort((all_seq, all_rows))
        self._pos = np.empty(order.size, dtype=np.int64)
        self._pos[order] = np.arange(order.size)
        self._indices = all_cols[order].astype(np.int32)
        self._indptr = np.concatenate([[0], np.cumsum(np.bincount(all_rows, minlength=n))]).astype(np.int32)
        self._rows = all_rows[order]
        self._cols = all_cols[order]
        self._data = np.zeros(order.size)
        self._lin = [(kind, data, self._pos[ids]) for kind, data, ids in lin]
        self._aff = [(kind, data, self._pos[ids]) for kind, data, ids in aff]
        self._x = np.zeros(n + 1)
        self._x[n] = 1.0
        self._A = sp.csr_matrix((self._data, self._indices, self._indptr), shape=(n, n + 1))
        slots = np.unique(np.concatenate(coef_slots)) if coef_slots else np.zeros(0, dtype=np.int64)
        classes = moving[slots] if slots.size else np.zeros(0)
        self._moves = 2 if (classes == 2).any() else (1 if (classes == 1).any() else 0)
        self._key: Any = None
        self._empty = order.size == 0
        self._sum = _kernel() if order.size >= KERNEL_TERMS else None
        self._out = np.zeros(n)

    def _set_linear(self, X: np.ndarray) -> None:
        data = self._A.data
        for kind, d, pos in self._lin:
            if kind == 'xsign':
                slots, sign = d
                data[pos] = X[slots] * sign
            elif kind == 'xx':
                a, bb, sign = d
                data[pos] = X[a] * X[bb] * sign
            elif kind == 'const':
                data[pos] = d
            elif kind == 'farf':
                d.refresh(X)
                data[pos] = d.vals.ravel()

    def _set_affine(self, y: np.ndarray, X: np.ndarray) -> None:
        data = self._A.data
        mem = self.system.MEM
        for kind, d, pos in self._aff:
            if kind == 'xsign':
                slots, sign = d
                data[pos] = X[slots] * sign
            elif kind == 'x':
                data[pos] = X[d]
            elif kind == 'fail-rel':
                h, p_idx, r_idx = d
                data[pos] = X[h] * y[p_idx] - X[r_idx]
            elif kind == 'mean':
                t_idx, m0 = d
                rec = np.array([mem[k].recording for k in range(m0, m0 + t_idx.size)])
                data[pos] = np.where(rec, X[t_idx], 0.0)

    def refresh(self, X: np.ndarray) -> None:
        """Brings the linear coefficients up to date, if they can have moved."""
        system = self.system
        if self._moves == 0:
            key: Any = system._invariant_version
        elif self._moves == 1:
            key = (system._invariant_version, system._clock_at)
        else:
            key = None
        if key is not None and key == self._key:
            return
        self._set_linear(X)
        self._key = key

    def matrix(self, X: np.ndarray) -> sp.csr_matrix:
        """The linear part, A without its last column (duplicates summed)."""
        self.refresh(X)
        A = self._A[:, :self.n].tocsr()
        A.sum_duplicates()
        return A

    def __call__(self, t: float, y: np.ndarray, X: np.ndarray) -> np.ndarray:
        if self._empty:
            return np.zeros(self.n)
        self.refresh(X)
        self._set_affine(y, X)
        if self._sum is not None:
            return self._sum(self._indptr, self._indices, self._A.data, y, self.n, np.empty(self.n))
        x = self._x
        x[:self.n] = y
        return np.bincount(self._rows, weights=self._A.data * x[self._cols], minlength=self.n)
