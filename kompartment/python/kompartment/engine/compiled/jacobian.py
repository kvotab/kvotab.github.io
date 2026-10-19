"""df/dy, the analytic Jacobian, worked out where the compiled loop runs.

:mod:`kompartment.engine.analytic` reads df/dy off the statements the engine
runs: the forward-mode tangent of each statement that reads the state, the
gradients of the slots that do, and the direct and chain terms that put them
together on the pattern. The compiled loops called it back in Python for
every Jacobian they asked for. This module lays the same plan out in flat
arrays -- each statement's tree as a tape, its nodes children first, as the
Julia engine's ``TangentTape`` does -- and works it out in compiled code:
every node's value for one element at a time, then the tangent of each leaf
that reads the state carried up the one path from it to the root, with the
Python rules' arithmetic in their order. The values are the Python ones to
the last bit, numpy's short cuts in its powers and its signed zeros
included.

What it does not take stays with the callback, :func:`program` saying why: a
semi-analytical path's release, a far-field path whose settings move (its
refresh keeps a state of its own), the interpolation and transport
functions.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from numba import njit, types
from numba.experimental import structref

from ..functions import EPS
from . import guard_numba_cache
from .runtime import (RECW, _binomial1, _bq2mole1, _erf1, _erfc1, _factorial1, _fix1, _mod1, _mole2bq1,
                      _npmax, _npmin, _pow1, _ramp_down1, _ramp_up1, _rem1, _round1, _sign1, _smooth_down1,
                      _smooth_up1, _ulp1, _and_k, _or_k, _nand_k, _nor_k, _xor_k, _percentile_k, table_at)

guard_numba_cache()

_OPTS = dict(cache=True, nogil=True, error_model='numpy')

LN10 = math.log(10)
LN2 = math.log(2)
TWO_OVER_SQRT_PI = 1.1283791670955126

# What a plan is: a statement's tape, a slot with no gradient, a far-field
# path's release, the min/max and running means of a recorder.
P_STATEMENT, P_ZERO, P_FARFIELD, P_RECORDER = 0, 1, 2, 3
# A tape's nodes (``codegen``'s trees).
N_LEAF, N_NEG, N_BIN, N_COND, N_TAB, N_CALL = 0, 1, 2, 3, 4, 5
# What a leaf reads.
L_Y, L_X, L_P, L_K, L_T, L_T0, L_T1, L_DIS, L_NONE = range(9)
_LEAF_KINDS = {'y': L_Y, 'X': L_X, 'P': L_P, 'K': L_K, 'T': L_T, 'T0': L_T0, 'T1': L_T1, 'DIS': L_DIS}
# The binary operations.
B_ADD, B_SUB, B_MUL, B_DIV, B_POW, B_LT, B_LE, B_GT, B_GE, B_EQ, B_NE, B_AND, B_OR = range(13)
_BIN = {'+': B_ADD, '-': B_SUB, '*': B_MUL, '/': B_DIV, '^': B_POW, '<': B_LT, '<=': B_LE, '>': B_GT, '>=': B_GE,
        '==': B_EQ, '~=': B_NE, '&&': B_AND, '||': B_OR}
# The functions, by the canonical names of ``functions.FUNCTIONS``.
(C_ABS, C_SQRT, C_EXP, C_LOG, C_LOG10, C_LOG2, C_HYPOT, C_CEIL, C_FLOOR, C_ROUND, C_FIX, C_SIGN, C_EPS, C_ULP, C_PI,
 C_MOD, C_REM, C_FACTORIAL, C_BINOMIAL, C_ERF, C_ERFC, C_SIN, C_COS, C_TAN, C_ASIN, C_ACOS, C_ATAN, C_ATAN2, C_SINH,
 C_COSH, C_TANH, C_ASINH, C_ACOSH, C_ATANH, C_MIN, C_MAX, C_SUM, C_PROD, C_MEAN, C_IF, C_NOT, C_AND, C_OR, C_NAND,
 C_NOR, C_XOR, C_PERCENTILE, C_BQ2MOLE, C_MOLE2BQ, C_RAMPDOWN, C_RAMPUP, C_SMOOTHDOWN, C_SMOOTHUP, C_POWER) = range(54)
_CALLS = {'abs': C_ABS, 'sqrt': C_SQRT, 'exp': C_EXP, 'log': C_LOG, 'log10': C_LOG10, 'log2': C_LOG2,
          'hypot': C_HYPOT, 'ceil': C_CEIL, 'floor': C_FLOOR, 'round': C_ROUND, 'fix': C_FIX, 'sign': C_SIGN,
          'eps': C_EPS, 'ulp': C_ULP, 'pi': C_PI, 'mod': C_MOD, 'rem': C_REM, 'factorial': C_FACTORIAL,
          'binomial': C_BINOMIAL, 'erf': C_ERF, 'erfc': C_ERFC, 'sin': C_SIN, 'cos': C_COS, 'tan': C_TAN,
          'asin': C_ASIN, 'acos': C_ACOS, 'atan': C_ATAN, 'atan2': C_ATAN2, 'sinh': C_SINH, 'cosh': C_COSH,
          'tanh': C_TANH, 'asinh': C_ASINH, 'acosh': C_ACOSH, 'atanh': C_ATANH, 'min': C_MIN, 'max': C_MAX,
          'sum': C_SUM, 'prod': C_PROD, 'mean': C_MEAN, 'if': C_IF, 'not': C_NOT, 'and': C_AND, 'or': C_OR,
          'nand': C_NAND, 'nor': C_NOR, 'xor': C_XOR, 'percentile': C_PERCENTILE, 'bq2mole': C_BQ2MOLE,
          'mole2bq': C_MOLE2BQ, 'rampDown': C_RAMPDOWN, 'rampUp': C_RAMPUP, 'smoothDown': C_SMOOTHDOWN,
          'smoothUp': C_SMOOTHUP, 'power': C_POWER}
# The direct terms and the chain terms' coefficients (``analytic._plan_assembly``).
D_XSIGN, D_NEGXH, D_XH, D_NEGXX, D_XX, D_CONST, D_FARF = range(7)
_DIRECT = {'xsign': D_XSIGN, 'negxh': D_NEGXH, 'xh': D_XH, 'negxx': D_NEGXX, 'xx': D_XX, 'const': D_CONST,
           'farf': D_FARF}
K_SIGNDONOR, K_ONES, K_NEGY, K_Y, K_NEGONE, K_NEGXY, K_XY, K_RECORDING = range(8)
_CHAIN = {'signdonor': K_SIGNDONOR, 'ones': K_ONES, 'negy': K_NEGY, 'y': K_Y, 'negone': K_NEGONE,
          'negxy': K_NEGXY, 'xy': K_XY, 'recording': K_RECORDING}
# A recorder's part: a min/max, a running mean.
R_MIN_MAX, R_RUNNING_MEAN = 0, 1

_i = types.int64
_f = types.float64
_I = types.int64[::1]
_A = types.float64[::1]


@structref.register
class JacobianProgramType(types.StructRef):
    def preprocess_fields(self, fields: Any) -> Any:
        return tuple((name, types.unliteral(typ)) for name, typ in fields)


class JacobianProgram(structref.StructRefProxy):
    """A model's analytic Jacobian as compiled code reads it: see :func:`program`."""

    @property
    def nnz(self) -> int:
        """The pattern's number of entries."""
        return _nnz(self)


structref.define_boxing(JacobianProgramType, JacobianProgram)

#: The plans in order (``pl_``), the statements (``st_``) with their outputs,
#: own gradients and terms, the tapes' nodes (``nd_``) and leaves (``lf_``),
#: the far-field releases (``fa_``) and the recorders' parts (``rc_``); the
#: direct (``dr_``) and chain (``ch_``) terms; and the work arrays.
JP_T = JacobianProgramType(fields=(
    ('n', _i), ('nnz', _i), ('g_nnz', _i), ('td', _i), ('dis', _i), ('ro', _i), ('t0', _f), ('t1', _f),
    ('pl_kind', _I), ('pl_ref', _I), ('pl_n', _I),
    ('st_width', _I), ('st_mult', _I), ('st_node0', _I), ('st_nnodes', _I), ('st_leaf0', _I), ('st_nleaves', _I),
    ('st_out0', _I), ('st_own0', _I), ('st_nown', _I), ('st_yt0', _I), ('st_nyt', _I), ('st_xt0', _I),
    ('st_nxt', _I), ('outs', _I), ('own_i', _I), ('own_lo', _I), ('own_hi', _I),
    ('yt_p', _I), ('yt_dst0', _I), ('ydst', _I), ('xt_p', _I), ('xt_q0', _I), ('xt_nq', _I), ('xe', _I),
    ('xs', _I), ('xd', _I),
    ('nd_kind', _I), ('nd_op', _I), ('nd_parent', _I), ('nd_slot', _I), ('nd_arg0', _I), ('nd_nargs', _I),
    ('nd_leaf', _I), ('nd_exp_has', _I), ('nd_exp', _A), ('nd_args', _I),
    ('lf_kind', _I), ('lf_vec', _I), ('lf_off', _I), ('lf_node', _I), ('lf_idx', _I), ('lf_val', _A),
    ('fa_w', _I), ('fa_q0', _I), ('fa_n', _I), ('fa_dst', _I),
    ('rc_kind', _I), ('rc_out', _I), ('rc_tgt', _I), ('rc_copy', _I), ('rc_m', _I), ('rc_stpos', _I),
    ('rc_q0', _I), ('rc_n', _I), ('rc_src0', _I), ('rc_dst', _I),
    ('dr_kind', _I), ('dr_q0', _I), ('dr_nq', _I), ('dr_s1', _I), ('dr_s2', _I), ('dpos', _I), ('dslot', _I),
    ('dfac', _A),
    ('ch_kind', _I), ('ch_q0', _I), ('ch_nq', _I), ('ch_e0', _I), ('ch_s1', _I), ('celem', _I), ('csrc', _I),
    ('cdst', _I), ('cfac', _A), ('cst', _I),
    ('G', _A), ('w_nv', _A), ('w_vec', _I), ('w_lv', _A), ('w_args', _A), ('w_d', _A), ('w_live', _I),
    ('w_fac', _A), ('w_base', _A), ('w_prod', _A)))


@njit(**_OPTS)
def _new(n, nnz, g_nnz, td, dis, ro, t0, t1, ints, floats):
    """A program from its scalars and its arrays (``ints`` and ``floats`` in
    the order of the fields)."""
    jp = structref.new(JP_T)
    jp.n = n
    jp.nnz = nnz
    jp.g_nnz = g_nnz
    jp.td = td
    jp.dis = dis
    jp.ro = ro
    jp.t0 = t0
    jp.t1 = t1
    jp.pl_kind, jp.pl_ref, jp.pl_n = ints[0], ints[1], ints[2]
    jp.st_width, jp.st_mult, jp.st_node0, jp.st_nnodes = ints[3], ints[4], ints[5], ints[6]
    jp.st_leaf0, jp.st_nleaves, jp.st_out0, jp.st_own0 = ints[7], ints[8], ints[9], ints[10]
    jp.st_nown, jp.st_yt0, jp.st_nyt, jp.st_xt0, jp.st_nxt = ints[11], ints[12], ints[13], ints[14], ints[15]
    jp.outs, jp.own_i, jp.own_lo, jp.own_hi = ints[16], ints[17], ints[18], ints[19]
    jp.yt_p, jp.yt_dst0, jp.ydst = ints[20], ints[21], ints[22]
    jp.xt_p, jp.xt_q0, jp.xt_nq, jp.xe, jp.xs, jp.xd = ints[23], ints[24], ints[25], ints[26], ints[27], ints[28]
    jp.nd_kind, jp.nd_op, jp.nd_parent, jp.nd_slot = ints[29], ints[30], ints[31], ints[32]
    jp.nd_arg0, jp.nd_nargs, jp.nd_leaf, jp.nd_exp_has = ints[33], ints[34], ints[35], ints[36]
    jp.nd_exp = floats[0]
    jp.nd_args = ints[37]
    jp.lf_kind, jp.lf_vec, jp.lf_off, jp.lf_node, jp.lf_idx = ints[38], ints[39], ints[40], ints[41], ints[42]
    jp.lf_val = floats[1]
    jp.fa_w, jp.fa_q0, jp.fa_n, jp.fa_dst = ints[43], ints[44], ints[45], ints[46]
    jp.rc_kind, jp.rc_out, jp.rc_tgt, jp.rc_copy, jp.rc_m = ints[47], ints[48], ints[49], ints[50], ints[51]
    jp.rc_stpos, jp.rc_q0, jp.rc_n, jp.rc_src0, jp.rc_dst = ints[52], ints[53], ints[54], ints[55], ints[56]
    jp.dr_kind, jp.dr_q0, jp.dr_nq, jp.dr_s1, jp.dr_s2 = ints[57], ints[58], ints[59], ints[60], ints[61]
    jp.dpos, jp.dslot = ints[62], ints[63]
    jp.dfac = floats[2]
    jp.ch_kind, jp.ch_q0, jp.ch_nq, jp.ch_e0, jp.ch_s1 = ints[64], ints[65], ints[66], ints[67], ints[68]
    jp.celem, jp.csrc, jp.cdst = ints[69], ints[70], ints[71]
    jp.cfac = floats[3]
    jp.cst = ints[72]
    jp.G = floats[4]
    jp.w_nv = floats[5]
    jp.w_vec = ints[73]
    jp.w_lv, jp.w_args, jp.w_d = floats[6], floats[7], floats[8]
    jp.w_live = ints[74]
    jp.w_fac, jp.w_base, jp.w_prod = floats[9], floats[10], floats[11]
    return jp


@njit(**_OPTS)
def _nnz(jp):
    return jp.nnz


@njit(**_OPTS)
def _set_times(jp, t0, t1):
    jp.t0 = t0
    jp.t1 = t1


#: The order :func:`_new` takes the arrays in.
_INTS = ('pl_kind', 'pl_ref', 'pl_n', 'st_width', 'st_mult', 'st_node0', 'st_nnodes', 'st_leaf0', 'st_nleaves',
         'st_out0', 'st_own0', 'st_nown', 'st_yt0', 'st_nyt', 'st_xt0', 'st_nxt', 'outs', 'own_i', 'own_lo',
         'own_hi', 'yt_p', 'yt_dst0', 'ydst', 'xt_p', 'xt_q0', 'xt_nq', 'xe', 'xs', 'xd', 'nd_kind', 'nd_op',
         'nd_parent', 'nd_slot', 'nd_arg0', 'nd_nargs', 'nd_leaf', 'nd_exp_has', 'nd_args', 'lf_kind', 'lf_vec',
         'lf_off', 'lf_node', 'lf_idx', 'fa_w', 'fa_q0', 'fa_n', 'fa_dst', 'rc_kind', 'rc_out', 'rc_tgt', 'rc_copy',
         'rc_m', 'rc_stpos', 'rc_q0', 'rc_n', 'rc_src0', 'rc_dst', 'dr_kind', 'dr_q0', 'dr_nq', 'dr_s1', 'dr_s2',
         'dpos', 'dslot', 'ch_kind', 'ch_q0', 'ch_nq', 'ch_e0', 'ch_s1', 'celem', 'csrc', 'cdst', 'cst', 'w_vec',
         'w_live')
_FLOATS = ('nd_exp', 'lf_val', 'dfac', 'cfac', 'G', 'w_nv', 'w_lv', 'w_args', 'w_d', 'w_fac', 'w_base', 'w_prod')


# --- the numbers ----------------------------------------------------------------------------------------


@njit(**_OPTS)
def table_slope(W, IW, td, k, raw):
    """``Table.slope_scalar``: dy/dx of table ``k`` at ``raw`` (zero for the
    step rules, beyond the ends but for ``extrapolate``, and at a step)."""
    base = td + 5 * k
    xo = IW[base]
    yo = IW[base + 1]
    n = IW[base + 2]
    interp = IW[base + 3]
    if n == 1 or interp == 2 or interp == 3 or interp == 4:
        return 0.0
    first = W[xo]
    last = W[xo + n - 1]
    v = raw
    if IW[base + 4] != 0:
        span = last - first
        a = np.fmod(v - first, span)
        v = a + first if a >= 0 else a + span + first
    if v < first or v > last:
        if interp != 1:
            return 0.0
        i = 0 if v < first else n - 2
    elif v != v:
        i = 0
    else:
        lo = 0
        hi = n
        while lo < hi:
            mid = (lo + hi) // 2
            if v < W[xo + mid]:
                hi = mid
            else:
                lo = mid + 1
        i = min(max(lo - 1, 0), n - 2)
    dx = W[xo + i + 1] - W[xo + i]
    return 0.0 if dx == 0 else (W[yo + i + 1] - W[yo + i]) / dx


@njit(**_OPTS)
def _binary(op, a, b, one):
    """``codegen.apply_binary`` on one element; ``one``: the exponent of a
    power is one value for every element."""
    if op == B_ADD:
        return a + b
    if op == B_SUB:
        return a - b
    if op == B_MUL:
        return a * b
    if op == B_DIV:
        return a / b
    if op == B_POW:
        return _pow1(a, b, one)
    if op == B_LT:
        return 1.0 if a < b else 0.0
    if op == B_LE:
        return 1.0 if a <= b else 0.0
    if op == B_GT:
        return 1.0 if a > b else 0.0
    if op == B_GE:
        return 1.0 if a >= b else 0.0
    if op == B_EQ:
        return 1.0 if a == b else 0.0
    if op == B_NE:
        return 1.0 if a != b else 0.0
    if op == B_AND:
        return 1.0 if (a != 0 and b != 0) else 0.0
    return 1.0 if (a != 0 or b != 0) else 0.0


@njit(**_OPTS)
def _call(key, A, n, one):
    """``codegen.call_value`` on one element: the function ``key`` of
    A[0:n]; ``one``: the exponent of a power, or the steepness of a smooth
    step, is one value for every element."""
    a = A[0]
    if key == C_ABS:
        return abs(a)
    if key == C_SQRT:
        return np.sqrt(a)
    if key == C_EXP:
        return np.exp(a)
    if key == C_LOG:
        return np.log(a)
    if key == C_LOG10:
        return np.log10(a)
    if key == C_LOG2:
        return np.log2(a)
    if key == C_HYPOT:
        return np.hypot(a, A[1])
    if key == C_CEIL:
        return np.ceil(a)
    if key == C_FLOOR:
        return np.floor(a)
    if key == C_ROUND:
        return _round1(a)
    if key == C_FIX:
        return _fix1(a)
    if key == C_SIGN:
        return _sign1(a)
    if key == C_EPS:
        return EPS
    if key == C_ULP:
        return _ulp1(a)
    if key == C_PI:
        return math.pi
    if key == C_MOD:
        return _mod1(a, A[1])
    if key == C_REM:
        return _rem1(a, A[1])
    if key == C_FACTORIAL:
        return _factorial1(a)
    if key == C_BINOMIAL:
        return _binomial1(a, A[1])
    if key == C_ERF:
        return _erf1(a)
    if key == C_ERFC:
        return _erfc1(a)
    if key == C_SIN:
        return np.sin(a)
    if key == C_COS:
        return np.cos(a)
    if key == C_TAN:
        return np.tan(a)
    if key == C_ASIN:
        return np.arcsin(a)
    if key == C_ACOS:
        return np.arccos(a)
    if key == C_ATAN:
        return np.arctan(a)
    if key == C_ATAN2:
        return np.arctan2(a, A[1])
    if key == C_SINH:
        return np.sinh(a)
    if key == C_COSH:
        return np.cosh(a)
    if key == C_TANH:
        return math.tanh(a)
    if key == C_ASINH:
        return np.arcsinh(a)
    if key == C_ACOSH:
        return np.arccosh(a)
    if key == C_ATANH:
        return np.arctanh(a)
    if key == C_MIN or key == C_MAX:
        out = a
        for i in range(1, n):
            out = _npmin(out, A[i]) if key == C_MIN else _npmax(out, A[i])
        return out
    if key == C_SUM or key == C_MEAN:
        out = a
        for i in range(1, n):
            out = out + A[i]
        return out / n if key == C_MEAN else out
    if key == C_PROD:
        out = a
        for i in range(1, n):
            out = out * A[i]
        return out
    if key == C_IF:
        if a != 0:
            return A[1]
        return A[2] if n > 2 else 0.0
    if key == C_NOT:
        return 1.0 if a == 0 else 0.0
    if key == C_AND:
        return _and_k(A[:n])
    if key == C_OR:
        return _or_k(A[:n])
    if key == C_NAND:
        return _nand_k(A[:n])
    if key == C_NOR:
        return _nor_k(A[:n])
    if key == C_XOR:
        return _xor_k(A[:n])
    if key == C_PERCENTILE:
        return _percentile_k(A[:n])
    if key == C_BQ2MOLE:
        return _bq2mole1(a, A[1])
    if key == C_MOLE2BQ:
        return _mole2bq1(a, A[1])
    if key == C_RAMPDOWN:
        return _ramp_down1(a, A[1], A[2])
    if key == C_RAMPUP:
        return _ramp_up1(a, A[1], A[2])
    if key == C_SMOOTHDOWN:
        return _smooth_down1(a, A[1], A[2], one)
    if key == C_SMOOTHUP:
        return _smooth_up1(a, A[1], A[2], one)
    return _pow1(a, A[1], one)


@njit(**_OPTS)
def _power_rule(a, b, s, d, V, exp_has, exponent, one):
    """``analytic._power_rule`` with the tangent ``d`` along the base
    (``s`` 0) or the exponent (1): (whether there is one, its value)."""
    if s == 0:
        if exp_has:
            if exponent == 0:
                return False, 0.0
            if exponent == 1:
                return True, d
            if exponent == 2:
                return True, 2 * a * d
            if exponent == 0.5:
                return True, d / (2 * V)
            return True, exponent * _pow1(a, exponent - 1, True) * d
        return True, b * _pow1(a, b - 1, one) * d
    return True, (V * np.log(a) * d if a > 0 else 0.0)


@njit(**_OPTS)
def _call_tangent(key, A, n, s, d, V, exp_has, exponent, one):
    """``Tangent._call_tangent`` with the tangent ``d`` along argument ``s``
    alone: (whether there is one, its value)."""
    if key == C_POWER:
        has, r = _power_rule(A[0], A[1], s, d, V, exp_has, exponent, one)
        return has, (0.0 if (has and d == 0) else r)
    if key == C_MIN or key == C_MAX:
        out = np.nan
        for i in range(n - 1, -1, -1):
            if A[i] == V:
                out = d if i == s else 0.0
        return True, out
    if key == C_SUM:
        return True, d
    if key == C_MEAN:
        return True, d / n
    if key == C_PROD:
        p = A[0]
        dp = d
        for i in range(1, n):
            if i == s:
                dp = p * d
            elif i > s:
                dp = A[i] * dp
            p = p * A[i]
        return True, dp
    a = A[0]
    if key == C_ABS:
        r = _sign1(a) * d
    elif key == C_SQRT:
        r = d / (2 * V)
    elif key == C_EXP:
        r = V * d
    elif key == C_LOG:
        r = d / a
    elif key == C_LOG10:
        r = d / (a * LN10)
    elif key == C_LOG2:
        r = d / (a * LN2)
    elif key == C_HYPOT:
        r = (A[s] * d) / V
    elif key == C_SIN:
        r = np.cos(a) * d
    elif key == C_COS:
        r = (-np.sin(a)) * d
    elif key == C_TAN:
        r = (1 + V * V) * d
    elif key == C_ASIN:
        r = d / np.sqrt(1 - a * a)
    elif key == C_ACOS:
        r = (-d) / np.sqrt(1 - a * a)
    elif key == C_ATAN:
        r = d / (1 + a * a)
    elif key == C_SINH:
        r = np.cosh(a) * d
    elif key == C_COSH:
        r = np.sinh(a) * d
    elif key == C_TANH:
        r = (1 - V * V) * d
    elif key == C_ASINH:
        r = d / np.sqrt(a * a + 1)
    elif key == C_ACOSH:
        r = d / np.sqrt(a * a - 1)
    elif key == C_ATANH:
        r = d / (1 - a * a)
    elif key == C_ERF:
        r = TWO_OVER_SQRT_PI * np.exp(-a * a) * d
    elif key == C_ERFC:
        r = -TWO_OVER_SQRT_PI * np.exp(-a * a) * d
    elif key == C_ATAN2:
        b = A[1]
        r = (b * d if s == 0 else -(a * d)) / (a * a + b * b)
    elif key == C_MOD:
        if s == 0:
            r = d
        else:
            r = 0.0 if A[1] == 0 else 0.0 - np.floor(a / A[1]) * d
    elif key == C_REM:
        if s == 0:
            r = d
        else:
            r = np.nan if A[1] == 0 else 0.0 - np.trunc(a / A[1]) * d
    elif key == C_ULP:
        r = _sign1(a) * 2.220446049250313e-16 * d
    elif key == C_RAMPDOWN or key == C_RAMPUP:
        if s != 0:
            return False, 0.0
        lo = _npmin(A[1], A[2])
        hi = _npmax(A[1], A[2])
        sign = 1.0 if key == C_RAMPUP else -1.0
        r = sign * d / (hi - lo) if (a > lo and a < hi) else 0.0
    elif key == C_SMOOTHDOWN or key == C_SMOOTHUP:
        if s != 0:
            return False, 0.0
        sign = 1.0 if key == C_SMOOTHUP else -1.0
        r = (sign * 2 * A[2] / a) * V * (1 - V) * d if a > 0 else 0.0
    elif key == C_BQ2MOLE:
        r = _bq2mole1(d, A[1]) if s == 0 else _bq2mole1(a, d)
    elif key == C_MOLE2BQ:
        r = _mole2bq1(d, A[1]) if s == 0 else -V * d / A[1]
    else:
        # The staircases, and anything without a rule (refused as the plan was made).
        return False, 0.0
    return True, (0.0 if d == 0 else r)


@njit(**_OPTS)
def _leaf(jp, L, i, t, y, X, P, W):
    """The value of leaf L for element i (``_Analytic._leaf_value``)."""
    kind = jp.lf_kind[L]
    off = jp.lf_off[L] + (i if jp.lf_vec[L] else 0)
    if kind == L_Y:
        return y[jp.lf_idx[off]]
    if kind == L_X:
        return X[jp.lf_idx[off]]
    if kind == L_P:
        return P[jp.lf_idx[off]]
    if kind == L_K:
        return jp.lf_val[off]
    if kind == L_T:
        return t
    if kind == L_T0:
        return jp.t0
    if kind == L_T1:
        return jp.t1
    if kind == L_DIS:
        return W[jp.dis + jp.lf_idx[off]]
    return 0.0


@njit(**_OPTS)
def _values(jp, n0, m, l0, i, W, IW):
    """Every node's value for element i into ``w_nv``, and whether it is an
    array (one value per element, not one for all) into ``w_vec``, from the
    leaves' values in ``w_lv``."""
    nv = jp.w_nv
    vec = jp.w_vec
    lv = jp.w_lv
    A = jp.w_args
    for k in range(m):
        g = n0 + k
        kd = jp.nd_kind[g]
        a0 = jp.nd_arg0[g]
        if kd == N_LEAF:
            p = jp.nd_leaf[g]
            nv[k] = lv[p]
            vec[k] = jp.lf_vec[l0 + p]
        elif kd == N_NEG:
            c = jp.nd_args[a0]
            nv[k] = -nv[c]
            vec[k] = vec[c]
        elif kd == N_BIN:
            ca = jp.nd_args[a0]
            cb = jp.nd_args[a0 + 1]
            nv[k] = _binary(jp.nd_op[g], nv[ca], nv[cb], vec[cb] == 0)
            vec[k] = 1 if (vec[ca] or vec[cb]) else 0
        elif kd == N_COND:
            ct = jp.nd_args[a0]
            chosen = jp.nd_args[a0 + 1] if nv[ct] != 0 else jp.nd_args[a0 + 2]
            nv[k] = nv[chosen]
            # numpy's: np.where (an array) under a test of many values, else the branch taken itself.
            vec[k] = 1 if vec[ct] else vec[chosen]
        elif kd == N_TAB:
            L = l0 + jp.nd_leaf[g]
            which = jp.lf_idx[jp.lf_off[L] + (i if jp.lf_vec[L] else 0)]
            c = jp.nd_args[a0]
            nv[k] = table_at(W, IW, jp.td, which, nv[c])
            vec[k] = 1 if (jp.lf_vec[L] or vec[c]) else 0
        else:
            na = jp.nd_nargs[g]
            any_vec = 0
            for q in range(na):
                c = jp.nd_args[a0 + q]
                A[q] = nv[c]
                if vec[c]:
                    any_vec = 1
            key = jp.nd_op[g]
            one = True
            if key == C_POWER:
                one = vec[jp.nd_args[a0 + 1]] == 0
            elif key == C_SMOOTHDOWN or key == C_SMOOTHUP:
                one = vec[jp.nd_args[a0 + 2]] == 0
            nv[k] = _call(key, A, na, one)
            vec[k] = any_vec


@njit(**_OPTS)
def _tangent(jp, n0, l0, p, i, W, IW):
    """The tangent of the statement's root along its leaf at position p, for
    element i, from the values ``_values`` left: (whether there is one, its
    value) -- none where the Python walk finds none."""
    nv = jp.w_nv
    vec = jp.w_vec
    A = jp.w_args
    k = jp.lf_node[l0 + p]
    d = 1.0
    while True:
        par = jp.nd_parent[n0 + k]
        if par < 0:
            return True, d
        s = jp.nd_slot[n0 + k]
        g = n0 + par
        kd = jp.nd_kind[g]
        a0 = jp.nd_arg0[g]
        if kd == N_BIN:
            op = jp.nd_op[g]
            ca = jp.nd_args[a0]
            cb = jp.nd_args[a0 + 1]
            a = nv[ca]
            b = nv[cb]
            if op == B_ADD:
                r = d
            elif op == B_SUB:
                r = d if s == 0 else -d
            elif op == B_MUL:
                r = b * d if s == 0 else a * d
            elif op == B_DIV:
                r = d / b if s == 0 else (-(nv[par] * d)) / b
            elif op == B_POW:
                has, r = _power_rule(a, b, s, d, nv[par], jp.nd_exp_has[g] != 0, jp.nd_exp[g], vec[cb] == 0)
                if not has:
                    return False, 0.0
                if d == 0:
                    r = 0.0
            else:
                return False, 0.0
        elif kd == N_NEG:
            r = -d
        elif kd == N_COND:
            if s == 0:
                return False, 0.0
            chosen = nv[jp.nd_args[a0]] != 0
            if s == 1:
                r = d if chosen else 0.0
            else:
                r = 0.0 if chosen else d
        elif kd == N_TAB:
            L = l0 + jp.nd_leaf[g]
            which = jp.lf_idx[jp.lf_off[L] + (i if jp.lf_vec[L] else 0)]
            r = table_slope(W, IW, jp.td, which, nv[jp.nd_args[a0]]) * d
        else:
            na = jp.nd_nargs[g]
            for q in range(na):
                A[q] = nv[jp.nd_args[a0 + q]]
            key = jp.nd_op[g]
            one = True
            if key == C_POWER:
                one = vec[jp.nd_args[a0 + 1]] == 0
            has, r = _call_tangent(key, A, na, s, d, nv[par], jp.nd_exp_has[g] != 0, jp.nd_exp[g], one)
            if not has:
                return False, 0.0
        d = r
        k = par


@njit(**_OPTS)
def _statement(jp, s, t, y, X, P, W, IW, G):
    """One statement's part of the gradients (``_Analytic._gradients``)."""
    width = jp.st_width[s]
    n0 = jp.st_node0[s]
    m = jp.st_nnodes[s]
    l0 = jp.st_leaf0[s]
    nl = jp.st_nleaves[s]
    yt0 = jp.st_yt0[s]
    nyt = jp.st_nyt[s]
    xt0 = jp.st_xt0[s]
    nxt = jp.st_nxt[s]
    mult = jp.st_mult[s] != 0
    nterms = nyt + nxt
    D = jp.w_d
    live = jp.w_live
    fac = jp.w_fac
    for i in range(width):
        for p in range(nl):
            jp.w_lv[p] = _leaf(jp, l0 + p, i, t, y, X, P, W)
        _values(jp, n0, m, l0, i, W, IW)
        if mult:
            fac[i] = jp.w_nv[m - 1]
        for u in range(nterms):
            if i > 0 and not live[u]:
                continue
            p = jp.yt_p[yt0 + u] if u < nyt else jp.xt_p[xt0 + u - nyt]
            has, r = _tangent(jp, n0, l0, p, i, W, IW)
            if i == 0:
                live[u] = 1 if has else 0
            D[u * width + i] = r
    base = jp.w_base
    if mult:
        o0 = jp.st_own0[s]
        for q in range(o0, o0 + jp.st_nown[s]):
            f_i = fac[jp.own_i[q]]
            for g in range(jp.own_lo[q], jp.own_hi[q]):
                G[g] *= f_i
        # The rate as it stood before the availability multiplied it in.
        out0 = jp.st_out0[s]
        for i in range(width):
            base[i] = X[jp.outs[out0 + i]] / fac[i] if fac[i] != 0 else 0.0
    for u in range(nyt):
        if not live[u]:
            continue
        dst0 = jp.yt_dst0[yt0 + u]
        for i in range(width):
            d = D[u * width + i]
            if mult:
                d = d * base[i]
            G[jp.ydst[dst0 + i]] += d
    prod = jp.w_prod
    for v in range(nxt):
        u = nyt + v
        if not live[u]:
            continue
        if mult:
            for i in range(width):
                D[u * width + i] = D[u * width + i] * base[i]
        # np.add.at(G, dst, d[elem] * G[src]): every product first, then each added in turn.
        q0 = jp.xt_q0[xt0 + v]
        nq = jp.xt_nq[xt0 + v]
        for q in range(nq):
            prod[q] = D[u * width + jp.xe[q0 + q]] * G[jp.xs[q0 + q]]
        for q in range(nq):
            G[jp.xd[q0 + q]] += prod[q]


@njit(**_OPTS)
def _fancy_add(G, dst, src_g, src_w, W, n, prod):
    """``G[dst] += values`` as numpy does it -- every value read, then each
    written -- the values G[src_g + q], or W[src_w + q] where src_g < 0."""
    for q in range(n):
        v = W[src_w + q] if src_g < 0 else G[src_g + q]
        prod[q] = G[dst[q]] + v
    for q in range(n):
        G[dst[q]] = prod[q]


@njit(**_OPTS)
def _recorders(jp, r, t, X, W, G):
    """A recorder's part of the gradients: a min/max follows its target
    where they are equal, a running mean its sum over the time it has
    recorded for (``_Analytic._special_gradient``)."""
    q0 = jp.pl_ref[r]
    for e in range(q0, q0 + jp.pl_n[r]):
        out = jp.rc_out[e]
        copy = False
        if jp.rc_kind[e] == R_MIN_MAX:
            copy = X[out] == X[jp.rc_tgt[e]] and jp.rc_copy[e] != 0
        else:
            m = jp.rc_m[e]
            s = jp.ro + RECW * m
            el = W[s + 4] + t - W[s + 5] if W[s + 3] != 0.0 else W[s + 4]
            if el > 0:
                G[jp.rc_stpos[e]] += 1.0 / el
            else:
                copy = jp.rc_copy[e] != 0
        if copy:
            n = jp.rc_n[e]
            _fancy_add(G, jp.rc_dst[jp.rc_q0[e]:jp.rc_q0[e] + n], jp.rc_src0[e], 0, W, n, jp.w_prod)


@njit(**_OPTS)
def evaluate(jp, t, y, X, P, W, IW, J):
    """The analytic Jacobian at (t, y) -- X the slots the derivative reads
    there, W and IW the compiled model's -- into J, the pattern's values:
    1, or 0 where an entry is not finite (``_Analytic.evaluate`` declines)."""
    G = jp.G
    for q in range(G.size):
        G[q] = 0.0
    if jp.g_nnz > 0:
        for k in range(jp.pl_kind.size):
            kind = jp.pl_kind[k]
            if kind == P_STATEMENT:
                _statement(jp, jp.pl_ref[k], t, y, X, P, W, IW, G)
            elif kind == P_FARFIELD:
                f = jp.pl_ref[k]
                n = jp.fa_n[f]
                q0 = jp.fa_q0[f]
                _fancy_add(G, jp.fa_dst[q0:q0 + n], -1, jp.fa_w[f], W, n, jp.w_prod)
            elif kind == P_RECORDER:
                _recorders(jp, k, t, X, W, G)
    for q in range(J.size):
        J[q] = 0.0
    for e in range(jp.dr_kind.size):
        kind = jp.dr_kind[e]
        q0 = jp.dr_q0[e]
        q1 = q0 + jp.dr_nq[e]
        if kind == D_XSIGN:
            for q in range(q0, q1):
                J[jp.dpos[q]] += jp.dfac[q] * X[jp.dslot[q]]
        elif kind == D_CONST:
            for q in range(q0, q1):
                J[jp.dpos[q]] += jp.dfac[q]
        elif kind == D_FARF:
            for q in range(q0, q1):
                J[jp.dpos[q]] += W[jp.dslot[q]]
        else:
            s1 = jp.dr_s1[e]
            if kind == D_NEGXH:
                v = -X[s1]
            elif kind == D_XH:
                v = X[s1]
            elif kind == D_NEGXX:
                v = -(X[s1] * X[jp.dr_s2[e]])
            else:
                v = X[s1] * X[jp.dr_s2[e]]
            for q in range(q0, q1):
                J[jp.dpos[q]] += v
    for c in range(jp.ch_kind.size):
        kind = jp.ch_kind[c]
        q0 = jp.ch_q0[c]
        e0 = jp.ch_e0[c]
        s1 = jp.ch_s1[c]
        for q in range(q0, q0 + jp.ch_nq[c]):
            el = jp.celem[q]
            if kind == K_SIGNDONOR:
                st = jp.cst[e0 + el]
                coef = jp.cfac[e0 + el] * (y[st] if st >= 0 else 1.0)
            elif kind == K_ONES:
                coef = 1.0
            elif kind == K_NEGONE:
                coef = -1.0
            elif kind == K_NEGY:
                coef = -y[jp.cst[e0 + el]]
            elif kind == K_Y:
                coef = y[jp.cst[e0 + el]]
            elif kind == K_NEGXY:
                coef = -(X[s1] * y[jp.cst[e0 + el]])
            elif kind == K_XY:
                coef = X[s1] * y[jp.cst[e0 + el]]
            else:
                coef = 1.0 if W[jp.ro + RECW * (s1 + el) + 3] != 0.0 else 0.0
            J[jp.cdst[q]] += coef * G[jp.csrc[q]]
    for q in range(J.size):
        if not math.isfinite(J[q]):
            return 0
    return 1


# --- the program, from the analytic plan ----------------------------------------------------------------


class Unsupported(Exception):
    """What the compiled Jacobian does not take, said as the stats say it."""


class _Builder:
    """The program's arrays, filled plan by plan."""

    def __init__(self) -> None:
        self.ints: Dict[str, List[int]] = {name: [] for name in _INTS}
        self.floats: Dict[str, List[float]] = {name: [] for name in _FLOATS}
        self.max_nodes = 1
        self.max_leaves = 1
        self.max_args = 3
        self.max_terms = 1
        self.max_d = 1
        self.max_width = 1
        self.max_prod = 1

    def add(self, name: str, values: Any) -> int:
        """Appends to an array; where it starts."""
        arr = self.ints[name] if name in self.ints else self.floats[name]
        start = len(arr)
        arr.extend(int(v) for v in values) if name in self.ints else arr.extend(float(v) for v in values)
        return start


def _tape(tree: Any, nodes: List[List[Any]], leaf_node: List[int]) -> int:
    """Lays a statement's tree out children first (as ``TangentTape``):
    each node ``[kind, op, children, leaf position, has exponent, exponent]``;
    the node of each leaf position in ``leaf_node`` (-1 for a table's
    index). Its root's place."""
    from ..analytic import _const_exponent
    kind = tree[0]
    if kind == 'leaf':
        leaf_node.append(len(nodes))
        nodes.append([N_LEAF, 0, [], len(leaf_node) - 1, 0, 0.0])
        return len(nodes) - 1
    if kind == 'neg':
        c = _tape(tree[1], nodes, leaf_node)
        nodes.append([N_NEG, 0, [c], -1, 0, 0.0])
        return len(nodes) - 1
    if kind == 'bin':
        a = _tape(tree[2], nodes, leaf_node)
        b = _tape(tree[3], nodes, leaf_node)
        exponent = _const_exponent(tree[3]) if tree[1] == '^' else None
        nodes.append([N_BIN, _BIN[tree[1]], [a, b], -1, 0 if exponent is None else 1,
                      0.0 if exponent is None else exponent])
        return len(nodes) - 1
    if kind == 'cond':
        cs = [_tape(tree[k], nodes, leaf_node) for k in (1, 2, 3)]
        nodes.append([N_COND, 0, cs, -1, 0, 0.0])
        return len(nodes) - 1
    if kind == 'tab':
        leaf_node.append(-1)     # the table's index: never live
        p = len(leaf_node) - 1
        c = _tape(tree[2], nodes, leaf_node)
        nodes.append([N_TAB, 0, [c], p, 0, 0.0])
        return len(nodes) - 1
    if kind == 'call':
        key = tree[1]
        if key not in _CALLS:
            raise Unsupported(f'it calls {key}()')
        cs = [_tape(a, nodes, leaf_node) for a in tree[2]]
        exponent = _const_exponent(tree[2][1]) if key == 'power' else None
        nodes.append([N_CALL, _CALLS[key], cs, -1, 0 if exponent is None else 1,
                      0.0 if exponent is None else exponent])
        return len(nodes) - 1
    raise Unsupported(f'a {kind} node')


def _statement_plan(bd: _Builder, plan: Any) -> int:
    """A statement plan's tape, leaves, outputs and terms; its number."""
    width = int(plan.width)
    nodes: List[List[Any]] = []
    leaf_node: List[int] = []
    try:
        root = _tape(plan.tree, nodes, leaf_node)
    except RecursionError:
        raise Unsupported('an equation nested too deeply to lay out') from None
    if root != len(nodes) - 1 or len(leaf_node) != len(plan.leaves):
        raise Unsupported('a tree whose leaves are not where its tape has them')
    parent = [-1] * len(nodes)
    slot = [0] * len(nodes)
    for k, node in enumerate(nodes):
        for q, c in enumerate(node[2]):
            parent[c] = k
            slot[c] = q
    s = len(bd.ints['st_width'])
    n0 = bd.add('nd_kind', [nd[0] for nd in nodes])
    bd.add('nd_op', [nd[1] for nd in nodes])
    bd.add('nd_parent', parent)
    bd.add('nd_slot', slot)
    arg0 = []
    for nd in nodes:
        arg0.append(bd.add('nd_args', nd[2]))
    bd.add('nd_arg0', arg0)
    bd.add('nd_nargs', [len(nd[2]) for nd in nodes])
    bd.add('nd_leaf', [nd[3] for nd in nodes])
    bd.add('nd_exp_has', [nd[4] for nd in nodes])
    bd.add('nd_exp', [nd[5] for nd in nodes])
    l0 = len(bd.ints['lf_kind'])
    for p, leaf in enumerate(plan.leaves):
        kind = leaf.kind
        index = leaf.index
        vec = np.ndim(index) != 0
        if vec and np.size(index) != width:
            raise Unsupported('a leaf of another width than its statement')
        if kind == 'K':
            bd.ints['lf_kind'].append(L_K)
            off = bd.add('lf_val', np.ravel(np.asarray(index, dtype=float)))
        elif kind == 'TAB':
            bd.ints['lf_kind'].append(L_NONE)
            off = bd.add('lf_idx', np.ravel(np.asarray(index, dtype=np.int64)))
        elif kind in ('y', 'X', 'P', 'DIS'):
            bd.ints['lf_kind'].append(_LEAF_KINDS[kind])
            off = bd.add('lf_idx', np.ravel(np.asarray(index, dtype=np.int64)))
        else:
            bd.ints['lf_kind'].append(_LEAF_KINDS.get(kind, L_NONE))
            off = 0
            vec = False
        bd.ints['lf_vec'].append(1 if vec else 0)
        bd.ints['lf_off'].append(off)
        bd.ints['lf_node'].append(leaf_node[p])
    bd.ints['st_width'].append(width)
    bd.ints['st_mult'].append(1 if plan.multiply else 0)
    bd.ints['st_node0'].append(n0)
    bd.ints['st_nnodes'].append(len(nodes))
    bd.ints['st_leaf0'].append(l0)
    bd.ints['st_nleaves'].append(len(plan.leaves))
    bd.ints['st_out0'].append(bd.add('outs', np.asarray(plan.outs, dtype=np.int64)))
    own = getattr(plan, 'own', []) if plan.multiply else []
    bd.ints['st_own0'].append(bd.add('own_i', [i for i, _, _ in own]))
    bd.add('own_lo', [lo for _, lo, _ in own])
    bd.add('own_hi', [hi for _, _, hi in own])
    bd.ints['st_nown'].append(len(own))
    bd.ints['st_yt0'].append(len(bd.ints['yt_p']))
    bd.ints['st_nyt'].append(len(plan.y_terms))
    for p, dst in plan.y_terms:
        bd.ints['yt_p'].append(int(p))
        bd.ints['yt_dst0'].append(bd.add('ydst', np.asarray(dst, dtype=np.int64)))
    bd.ints['st_xt0'].append(len(bd.ints['xt_p']))
    bd.ints['st_nxt'].append(len(plan.x_terms))
    for p, elem, src, dst in plan.x_terms:
        bd.ints['xt_p'].append(int(p))
        bd.ints['xt_q0'].append(bd.add('xe', elem))
        bd.add('xs', src)
        bd.add('xd', dst)
        bd.ints['xt_nq'].append(len(elem))
        bd.max_prod = max(bd.max_prod, len(elem))
    nterms = len(plan.y_terms) + len(plan.x_terms)
    bd.max_nodes = max(bd.max_nodes, len(nodes))
    bd.max_leaves = max(bd.max_leaves, len(plan.leaves))
    bd.max_args = max([bd.max_args] + [len(nd[2]) for nd in nodes])
    bd.max_terms = max(bd.max_terms, nterms)
    bd.max_d = max(bd.max_d, nterms * width)
    bd.max_width = max(bd.max_width, width)
    return s


def analytic_program(system: Any, cm: Any, evaluate: Any) -> Tuple[Optional[Any], Optional[str]]:
    """:func:`program` for the analytic Jacobian a run is handed, where
    ``evaluate`` is the system's own (``_Analytic.evaluate``) -- not one of
    a set of equations the caller made up."""
    from ..analytic import _Analytic
    an = getattr(evaluate, '__self__', None)
    if not isinstance(an, _Analytic) or an.system is not system:
        return None, "the Jacobian handed to the solver is not the model's own"
    return program(an, cm)


def program(an: Any, cm: Any) -> Tuple[Optional[Any], Optional[str]]:
    """``(program, None)``: the analytic Jacobian ``an`` (an
    :class:`~kompartment.engine.analytic._Analytic`) as compiled code works
    it out, reading the compiled model ``cm``'s arrays; or ``(None, why
    not)``. Made once for each, and kept on ``an``."""
    cached = getattr(an, '_compiled_program', None)
    if cached is not None and cached[0] is cm:
        jp, why = cached[1], cached[2]
        if jp is not None:
            _set_times(jp, float(an.system.start_time), float(an.system.end_time))
        return jp, why
    try:
        jp, why = _build(an, cm), None
    except Unsupported as e:
        jp, why = None, str(e)
    an._compiled_program = (cm, jp, why)
    return jp, why


def _build(an: Any, cm: Any) -> Any:
    system = an.system
    L = cm.layout
    if L['semi']:
        raise Unsupported('a semi-analytical path, whose release the Python path works out')
    if L['farf_moving']:
        raise Unsupported('a far-field path whose settings move, whose refresh keeps a state of its own')
    bd = _Builder()
    farf_index = {id(F): k for k, F in enumerate(system.FARF)}
    for plan in an.plans:
        if not isinstance(plan, tuple):
            bd.ints['pl_kind'].append(P_STATEMENT)
            bd.ints['pl_ref'].append(_statement_plan(bd, plan))
            bd.ints['pl_n'].append(0)
            continue
        kind = plan[0]
        if kind == 'zero':
            bd.ints['pl_kind'].append(P_ZERO)
            bd.ints['pl_ref'].append(0)
            bd.ints['pl_n'].append(0)
        elif kind == 'farfield':
            F, dst = plan[1], np.asarray(plan[2], dtype=np.int64)
            k = farf_index[id(F)]
            if F.rel_w.size != dst.size:
                raise Unsupported('a far-field path whose release weights do not match their gradient')
            bd.ints['pl_kind'].append(P_FARFIELD)
            bd.ints['pl_ref'].append(len(bd.ints['fa_w']))
            bd.ints['pl_n'].append(0)
            bd.ints['fa_w'].append(int(L['farf_w'][k]))
            bd.ints['fa_q0'].append(bd.add('fa_dst', dst))
            bd.ints['fa_n'].append(dst.size)
            bd.max_prod = max(bd.max_prod, dst.size)
        elif kind == 'recorder':
            a, rec = plan[1], plan[2]
            bd.ints['pl_kind'].append(P_RECORDER)
            bd.ints['pl_ref'].append(len(bd.ints['rc_kind']))
            count = 0
            for off in range(a.width):
                out = a.base + off
                if out not in an.g_row_of or rec.kind not in ('min_max', 'running_mean'):
                    continue
                tgt = rec.aux['target'].base + off
                copy = tgt in an.g_row_of and an.moving[tgt] == 2
                bd.ints['rc_kind'].append(R_MIN_MAX if rec.kind == 'min_max' else R_RUNNING_MEAN)
                bd.ints['rc_out'].append(out)
                bd.ints['rc_tgt'].append(tgt)
                bd.ints['rc_copy'].append(1 if copy else 0)
                if rec.kind == 'running_mean':
                    bd.ints['rc_m'].append(rec.mem + off)
                    bd.ints['rc_stpos'].append(int(an.g_pos(out, np.array([rec.state.base + off]))[0]))
                else:
                    bd.ints['rc_m'].append(-1)
                    bd.ints['rc_stpos'].append(-1)
                if copy:
                    r = an.g_row_of[tgt]
                    cols = an.g_cols[r]
                    bd.ints['rc_q0'].append(bd.add('rc_dst', an.g_pos(out, cols)))
                    bd.ints['rc_n'].append(cols.size)
                    bd.ints['rc_src0'].append(int(an.g_ptr[r]))
                    bd.max_prod = max(bd.max_prod, cols.size)
                else:
                    bd.ints['rc_q0'].append(0)
                    bd.ints['rc_n'].append(0)
                    bd.ints['rc_src0'].append(0)
                count += 1
            bd.ints['pl_n'].append(count)
        elif kind == 'laplace':
            raise Unsupported('a semi-analytical path, whose release the Python path works out')
        else:
            raise Unsupported(f'a {kind} plan')
    for kind, pos, slots, factors, s1, s2 in an.direct_spec:
        bd.ints['dr_kind'].append(_DIRECT[kind])
        bd.ints['dr_q0'].append(bd.add('dpos', pos))
        bd.ints['dr_nq'].append(pos.size)
        bd.ints['dr_s1'].append(s1)
        bd.ints['dr_s2'].append(s2)
        if kind == 'xsign':
            bd.add('dslot', slots)
            bd.add('dfac', factors)
        elif kind == 'const':
            bd.add('dslot', np.zeros(pos.size, dtype=np.int64))
            bd.add('dfac', factors)
        elif kind == 'farf':
            # The path's cell rates, where the compiled model keeps them in the derivative's matrix.
            where = L['data'] + np.asarray(L['farf_pos'][s1], dtype=np.int64)
            if where.size != pos.size:
                raise Unsupported("a far-field path whose rates do not match their place in the pattern")
            bd.add('dslot', where)
            bd.add('dfac', np.zeros(pos.size))
        else:
            bd.add('dslot', np.zeros(pos.size, dtype=np.int64))
            bd.add('dfac', np.zeros(pos.size))
    for kind, elem, src, dst, factors, states, s1 in an.chain_spec:
        code = _CHAIN.get(kind)
        if code is None:
            raise Unsupported(f'a {kind or "chain"} term')
        bd.ints['ch_kind'].append(code)
        bd.ints['ch_q0'].append(bd.add('celem', elem))
        bd.add('csrc', src)
        bd.add('cdst', dst)
        bd.ints['ch_nq'].append(len(elem))
        width = int(np.max(elem)) + 1 if len(elem) else 0
        e0 = len(bd.floats['cfac'])
        bd.ints['ch_e0'].append(e0)
        bd.ints['ch_s1'].append(s1)
        f = np.zeros(width)
        st = np.full(width, -1, dtype=np.int64)
        if factors.size:
            f[:min(width, factors.size)] = factors[:width]
        if states.size:
            st[:min(width, states.size)] = states[:width]
        bd.add('cfac', f)
        bd.add('cst', st)
    ints = []
    for name in _INTS:
        if name == 'w_vec':
            ints.append(np.zeros(bd.max_nodes, dtype=np.int64))
        elif name == 'w_live':
            ints.append(np.zeros(bd.max_terms, dtype=np.int64))
        else:
            ints.append(np.ascontiguousarray(bd.ints[name], dtype=np.int64))
    sizes = {'G': max(an.g_nnz, 1), 'w_nv': bd.max_nodes, 'w_lv': bd.max_leaves, 'w_args': bd.max_args,
             'w_d': bd.max_d, 'w_fac': bd.max_width, 'w_base': bd.max_width, 'w_prod': bd.max_prod}
    floats = []
    for name in _FLOATS:
        if name in sizes:
            floats.append(np.zeros(sizes[name]))
        else:
            floats.append(np.ascontiguousarray(bd.floats[name], dtype=np.float64))
    from numba.typed import List as TypedList
    return _new(int(an.n), int(an.pattern.nnz), int(an.g_nnz), int(L['td']), int(L['dis']), int(L['ro']),
                float(system.start_time), float(system.end_time), TypedList(ints), TypedList(floats))


@njit(**_OPTS)
def _gradients_of(jp):
    return jp.G[:max(jp.g_nnz, 0)].copy()


def gradients(jp: Any) -> np.ndarray:
    """The gradients of the slots that read the state, as the latest
    evaluation left them (``_Analytic._gradients``): for the tests."""
    return _gradients_of(jp)


_NONE: List[Any] = []


def none() -> Any:
    """The program of no Jacobian: what the compiled loops are handed when
    they do not work the analytic one out themselves."""
    if not _NONE:
        from numba.typed import List as TypedList
        one = ('w_vec', 'w_live', 'G', 'w_nv', 'w_lv', 'w_args', 'w_d', 'w_fac', 'w_base', 'w_prod')
        ints = TypedList([np.zeros(1 if name in one else 0, dtype=np.int64) for name in _INTS])
        floats = TypedList([np.zeros(1 if name in one else 0) for name in _FLOATS])
        _NONE.append(_new(0, 0, 0, 0, 0, 0, 0.0, 0.0, ints, floats))
    return _NONE[0]


def jacobian(jp: Any, t: float, y: np.ndarray, X: np.ndarray, P: np.ndarray, W: np.ndarray,
             IW: np.ndarray) -> Optional[np.ndarray]:
    """The program's Jacobian at (t, y), from Python: the pattern's values,
    or None where one is not finite."""
    J = np.zeros(jp.nnz)
    ok = evaluate(jp, float(t), np.ascontiguousarray(y, dtype=float), X, P, W, IW, J)
    return J if ok else None


__all__ = ('JP_T', 'JacobianProgram', 'Unsupported', 'analytic_program', 'evaluate', 'gradients', 'jacobian', 'none',
           'program', 'table_slope')
