"""Fuzzy logic: Mamdani and Sugeno inference systems (mamfis, sugfis, and
the older newfis), their variables, membership functions and rules
(addInput, addOutput, addMF, addRule, removeMF, removeInput, removeOutput;
addvar, addmf, addrule), evaluation (evalfis), the membership functions
themselves (trimf, trapmf, gaussmf, gauss2mf, gbellmf, sigmf, dsigmf,
psigmf, pimf, smf, zmf, linsmf, linzmf, evalmf), defuzz, showrule, plotmf,
gensurf, and .fis files (readfis, writefis).

The systems are value objects: fis = addMF(fis, ...) gives a new system, and
fis.Inputs(1).MembershipFunctions(2).Parameters = p changes a copy.
"""
import math
import os
import re

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, darr, out, opt_str, is_str, sval, num
from ..values import MError, Obj, Char, Cell, Struct, Str, EMPTY, numel, py_str, class_of
from .. import runtime as R


def bi(*names, **kw):
    """Registered as builtins are, with what NumPy refuses told as the function's own error."""
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, KeyError, ZeroDivisionError) as e:
                raise err(f'fuzzy:{names[0]}:invalidInput', f'{names[0]} cannot take these inputs: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


# ---- membership functions --------------------------------------------------------------------------------------------------

def _smf(x, a, b):
    y = np.zeros_like(x)
    if a >= b:
        return (x >= (a + b) / 2).astype(float)
    m = (a + b) / 2
    y = np.where(x <= a, 0.0, y)
    y = np.where((x > a) & (x <= m), 2 * ((x - a) / (b - a)) ** 2, y)
    y = np.where((x > m) & (x < b), 1 - 2 * ((x - b) / (b - a)) ** 2, y)
    return np.where(x >= b, 1.0, y)


def _tri(x, a, b, c):
    with np.errstate(divide='ignore', invalid='ignore'):
        left = np.where(b > a, (x - a) / (b - a), (x >= b).astype(float))
        right = np.where(c > b, (c - x) / (c - b), (x <= b).astype(float))
    return np.clip(np.minimum(left, right), 0, 1)


def _trap(x, a, b, c, d):
    with np.errstate(divide='ignore', invalid='ignore'):
        left = np.where(b > a, (x - a) / (b - a), (x >= b).astype(float))
        right = np.where(d > c, (d - x) / (d - c), (x <= c).astype(float))
    return np.clip(np.minimum(np.minimum(left, 1.0), right), 0, 1)


def _sig(x, a, c):
    return 1 / (1 + np.exp(-a * (x - c)))


def _gauss(x, s, c):
    return np.exp(-((x - c) ** 2) / (2 * s * s))


MF_PARAMS = {'trimf': 3, 'trapmf': 4, 'gaussmf': 2, 'gauss2mf': 4, 'gbellmf': 3, 'sigmf': 2, 'dsigmf': 4, 'psigmf': 4, 'pimf': 4, 'smf': 2, 'zmf': 2,
             'linsmf': 2, 'linzmf': 2}


def mf_eval(kind, p, x):
    """A membership function's values at x."""
    x = np.asarray(x, float)
    p = [float(v) for v in np.asarray(p, float).reshape(-1)]
    need = MF_PARAMS.get(kind)
    if need is None:
        raise err('fuzzy:evalmf:UnknownType', f"'{kind}' is no membership function type here ({', '.join(MF_PARAMS)}).", 'evalmf')
    if len(p) != need:
        raise err('fuzzy:evalmf:InvalidParameters', f'{kind} takes {need} parameters.', 'evalmf')
    if kind == 'trimf':
        return _tri(x, *p)
    if kind == 'trapmf':
        return _trap(x, *p)
    if kind == 'gaussmf':
        return _gauss(x, *p)
    if kind == 'gauss2mf':
        s1, c1, s2, c2 = p
        left = np.where(x <= c1, _gauss(x, s1, c1), 1.0)
        right = np.where(x >= c2, _gauss(x, s2, c2), 1.0)
        return left * right
    if kind == 'gbellmf':
        a, b, c = p
        return 1 / (1 + np.abs((x - c) / a) ** (2 * b))
    if kind == 'sigmf':
        return _sig(x, *p)
    if kind == 'dsigmf':
        return np.abs(_sig(x, p[0], p[1]) - _sig(x, p[2], p[3]))
    if kind == 'psigmf':
        return _sig(x, p[0], p[1]) * _sig(x, p[2], p[3])
    if kind == 'smf':
        return _smf(x, *p)
    if kind == 'zmf':
        return 1 - _smf(x, *p)
    if kind == 'pimf':
        return _smf(x, p[0], p[1]) * (1 - _smf(x, p[2], p[3]))
    if kind == 'linsmf':
        a, b = p
        return np.clip((x - a) / (b - a), 0, 1) if b > a else (x >= a).astype(float)
    a, b = p
    return np.clip((b - x) / (b - a), 0, 1) if b > a else (x < a).astype(float)


def _mf_builtin(kind):
    def f(nargout, *args):
        nargchk(args, 2, 2, kind)
        x = np.asarray(darr(args[0]), float)
        return out(mf_eval(kind, darr(args[1]), x))
    f.__name__ = kind
    f.__doc__ = f'y = {kind}(x, params): the {kind} membership function at x.'
    return f


for _k in MF_PARAMS:
    bi(_k)(_mf_builtin(_k))


# ---- the objects ----------------------------------------------------------------------------------------------------------------

def _txt(v):
    return Str(np.array([[v]], object))


class FisMF(Obj):
    cls = 'fismf'
    is_handle = False

    def __init__(self, name, kind, params):
        self.name, self.kind, self.params = name, kind, np.asarray(params, float).reshape(-1)

    def value_copy(self):
        return FisMF(self.name, self.kind, self.params.copy())

    def getprop(self, name):
        k = name.lower()
        if k == 'name':
            return _txt(self.name)
        if k == 'type':
            return _txt(self.kind)
        if k == 'parameters':
            return out(self.params.reshape(1, -1))
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fismf'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'name':
            self.name = sval(value, 'Name', 'fismf')
        elif k == 'type':
            self.kind = sval(value, 'Type', 'fismf')
        elif k == 'parameters':
            self.params = np.asarray(darr(value), float).reshape(-1)
        else:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fismf'.")

    def propnames(self):
        return ['Name', 'Type', 'Parameters']

    def display_lines(self):
        return ['  fismf with properties:', '', f'          Type: "{self.kind}"', f'    Parameters: [{" ".join(f"{v:g}" for v in self.params)}]', f'          Name: "{self.name}"']

    def values(self, x, inputs=None):
        if self.kind == 'constant':
            return float(self.params[0])
        if self.kind == 'linear':
            return float(self.params[:-1] @ np.asarray(inputs, float) + self.params[-1])
        return mf_eval(self.kind, self.params, x)


class FisVar(Obj):
    cls = 'fisvar'
    is_handle = False

    def __init__(self, name, rng, mfs=None):
        self.name, self.range, self.mfs = name, np.asarray(rng, float).reshape(-1), list(mfs or [])

    def value_copy(self):
        return FisVar(self.name, self.range.copy(), list(self.mfs))

    def getprop(self, name):
        k = name.lower()
        if k == 'name':
            return _txt(self.name)
        if k == 'range':
            return out(self.range.reshape(1, -1))
        if k == 'membershipfunctions':
            return FisArray(self.mfs, 'fismf')
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fisvar'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'name':
            self.name = sval(value, 'Name', 'fisvar')
        elif k == 'range':
            r = np.asarray(darr(value), float).reshape(-1)
            if r.size != 2 or not r[0] < r[1]:
                raise err('fuzzy:fisvar:InvalidRange', 'Range is [min max] with min below max.', 'fisvar')
            self.range = r
        elif k == 'membershipfunctions':
            self.mfs = list(value.items) if isinstance(value, FisArray) else [value] if isinstance(value, FisMF) else []
        else:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fisvar'.")

    def propnames(self):
        return ['Name', 'Range', 'MembershipFunctions']

    def display_lines(self):
        return ['  fisvar with properties:', '', f'                   Name: "{self.name}"', f'                  Range: [{self.range[0]:g} {self.range[1]:g}]',
                f'    MembershipFunctions: [1×{len(self.mfs)} fismf]']

    def mf_index(self, name, fn):
        for k, m in enumerate(self.mfs):
            if m.name == name:
                return k
        raise err(f'fuzzy:{fn}:UnknownMF', f"The variable '{self.name}' has no membership function '{name}'.", fn)


class FisRule(Obj):
    cls = 'fisrule'
    is_handle = False

    def __init__(self, ante, cons, weight=1.0, conn=1, text=None):
        self.ante, self.cons = [int(v) for v in ante], [int(v) for v in cons]
        self.weight, self.conn = float(weight), int(conn)
        self.text = text

    def value_copy(self):
        return FisRule(list(self.ante), list(self.cons), self.weight, self.conn, self.text)

    def getprop(self, name):
        k = name.lower()
        if k == 'description':
            return _txt(self.text or '')
        if k == 'antecedent':
            return out(np.array([self.ante], float))
        if k == 'consequent':
            return out(np.array([self.cons], float))
        if k == 'weight':
            return self.weight
        if k == 'connection':
            return float(self.conn)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fisrule'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'antecedent':
            self.ante = [int(v) for v in np.asarray(darr(value)).reshape(-1)]
        elif k == 'consequent':
            self.cons = [int(v) for v in np.asarray(darr(value)).reshape(-1)]
        elif k == 'weight':
            w = float(num(value))
            if not 0 <= w <= 1:
                raise err('fuzzy:fisrule:InvalidWeight', 'A rule weight is from 0 to 1.', 'fisrule')
            self.weight = w
        elif k == 'connection':
            c = int(num(value))
            if c not in (1, 2):
                raise err('fuzzy:fisrule:InvalidConnection', 'Connection is 1 (and) or 2 (or).', 'fisrule')
            self.conn = c
        elif k == 'description':
            self.text = sval(value, 'Description', 'fisrule')
        else:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'fisrule'.")

    def propnames(self):
        return ['Description', 'Antecedent', 'Consequent', 'Weight', 'Connection']

    def display_lines(self):
        return ['  fisrule with properties:', '', f'    Description: "{self.text or ""}"', f'     Antecedent: [{" ".join(str(v) for v in self.ante)}]',
                f'     Consequent: [{" ".join(str(v) for v in self.cons)}]', f'         Weight: {self.weight:g}', f'     Connection: {self.conn}']


class FisArray(Obj):
    """A row of fisvar, fismf or fisrule objects."""
    is_handle = False

    def __init__(self, items, kind):
        self.items, self.kind = list(items), kind

    @property
    def cls(self):
        return self.kind

    @property
    def shape(self):
        return (1, len(self.items))

    def value_copy(self):
        return FisArray(list(self.items), self.kind)

    def _sel(self, args):
        from ..index import idx
        pos = np.asarray(darr(idx(out(np.arange(1, len(self.items) + 1, dtype=float).reshape(1, -1)), tuple(args))), float).reshape(-1).astype(int) - 1
        return list(pos)

    def index(self, args):
        sel = self._sel(args)
        if len(sel) == 1:
            return self.items[sel[0]]
        return FisArray([self.items[k] for k in sel], self.kind)

    def index_assign(self, args, V):
        sel = self._sel(args) if not (len(args) == 1 and numel(args[0]) == 1 and float(num(args[0])) == len(self.items) + 1) else [len(self.items)]
        items = list(self.items)
        vals = V.items if isinstance(V, FisArray) else [V]
        if len(vals) == 1:
            vals = vals * len(sel)
        if len(vals) != len(sel):
            raise MError('MATLAB:subsassignnumelmismatch', 'Unable to perform assignment: the left and right sides have different numbers of elements.')
        for k, v in zip(sel, vals):
            if k == len(items):
                items.append(v)
            else:
                items[k] = v
        return FisArray(items, self.kind)

    def getprop(self, name):
        if len(self.items) == 1:
            return self.items[0].getprop(name)
        raise MError('MATLAB:index:expected_one_output', f'Pick one {self.kind} first, as x(k).{name}.')

    def setprop(self, name, value):
        if len(self.items) == 1:
            it = self.items[0].value_copy()
            it.setprop(name, value)
            self.items = [it]
            return
        raise MError('MATLAB:index:expected_one_output', f'Pick one {self.kind} first, as x(k).{name} = value.')

    def propnames(self):
        return self.items[0].propnames() if self.items else []

    def display_lines(self):
        if not self.items:
            return [f'  1×0 {self.kind} array with no elements.']
        head = [f'  1×{len(self.items)} {self.kind} array with properties:', '']
        if self.kind == 'fisrule':
            return head + [f'    {k + 1}: "{_rule_text_of(r)}"' for k, r in enumerate(self.items)]
        if self.kind == 'fismf':
            return head + [f'    {k + 1}: "{m.name}" {m.kind} [{" ".join(f"{v:g}" for v in m.params)}]' for k, m in enumerate(self.items)]
        return head + [f'    {k + 1}: "{v.name}" [{v.range[0]:g} {v.range[1]:g}], {len(v.mfs)} membership functions' for k, v in enumerate(self.items)]


def _rule_text_of(r):
    return r.text or ''


class Fis(Obj):
    is_handle = False
    METHODS = ('and', 'or', 'implication', 'aggregation', 'defuzzification')

    def __init__(self, kind, name='fis'):
        self.kind = kind                       # 'mamdani' or 'sugeno'
        self.name = name
        self.andm, self.orm = 'min', 'max'
        self.imp = 'min' if kind == 'mamdani' else 'prod'
        self.agg = 'max' if kind == 'mamdani' else 'sum'
        self.defuzz = 'centroid' if kind == 'mamdani' else 'wtaver'
        if kind == 'sugeno':
            self.andm = 'prod'
            self.orm = 'probor'
        self.inputs, self.outputs, self.rules = [], [], []

    @property
    def cls(self):
        return 'mamfis' if self.kind == 'mamdani' else 'sugfis'

    def value_copy(self):
        import copy
        o = copy.copy(self)
        o.inputs, o.outputs, o.rules = list(self.inputs), list(self.outputs), list(self.rules)
        return o

    PROPS = ['Name', 'AndMethod', 'OrMethod', 'ImplicationMethod', 'AggregationMethod', 'DefuzzificationMethod', 'Inputs', 'Outputs', 'Rules', 'Type']

    def getprop(self, name):
        k = name.lower()
        if k == 'name':
            return _txt(self.name)
        if k == 'type':
            return _txt(self.kind)
        if k == 'andmethod':
            return _txt(self.andm)
        if k == 'ormethod':
            return _txt(self.orm)
        if k == 'implicationmethod':
            return _txt(self.imp)
        if k == 'aggregationmethod':
            return _txt(self.agg)
        if k == 'defuzzificationmethod':
            return _txt(self.defuzz)
        if k == 'inputs':
            return FisArray(self.inputs, 'fisvar')
        if k == 'outputs':
            return FisArray(self.outputs, 'fisvar')
        if k == 'rules':
            return FisArray(self.rules, 'fisrule')
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def setprop(self, name, value):
        k = name.lower()
        allowed = {'andmethod': ('min', 'prod'), 'ormethod': ('max', 'probor'), 'implicationmethod': ('min', 'prod'),
                   'aggregationmethod': ('max', 'sum', 'probor'),
                   'defuzzificationmethod': ('centroid', 'bisector', 'mom', 'lom', 'som') if self.kind == 'mamdani' else ('wtaver', 'wtsum')}
        if k == 'name':
            self.name = sval(value, 'Name', self.cls)
        elif k in allowed:
            v = sval(value, name, self.cls).lower()
            if v not in allowed[k]:
                raise err(f'fuzzy:{self.cls}:InvalidMethod', f"{name} is {', '.join(repr(x) for x in allowed[k])}.", self.cls)
            attr = {'andmethod': 'andm', 'ormethod': 'orm', 'implicationmethod': 'imp', 'aggregationmethod': 'agg', 'defuzzificationmethod': 'defuzz'}[k]
            setattr(self, attr, v)
        elif k in ('inputs', 'outputs'):
            items = list(value.items) if isinstance(value, FisArray) else [value] if isinstance(value, FisVar) else []
            setattr(self, k, items)
        elif k == 'rules':
            items = list(value.items) if isinstance(value, FisArray) else [value] if isinstance(value, FisRule) else []
            self.rules = [self._described(r) for r in items]
        else:
            raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of {self.cls}.")

    def propnames(self):
        return list(self.PROPS)

    def display_lines(self):
        lines = [f'  {self.cls} with properties:', '', f'                     Name: "{self.name}"', f'                AndMethod: "{self.andm}"',
                 f'                 OrMethod: "{self.orm}"', f'        ImplicationMethod: "{self.imp}"', f'        AggregationMethod: "{self.agg}"',
                 f'    DefuzzificationMethod: "{self.defuzz}"', f'                   Inputs: [1×{len(self.inputs)} fisvar]',
                 f'                  Outputs: [1×{len(self.outputs)} fisvar]', f'                    Rules: [1×{len(self.rules)} fisrule]']
        if self.rules:
            lines += ['', '  Rules:'] + [f'    {k + 1}. {self.rule_text(r)}' for k, r in enumerate(self.rules)]
        return lines

    def var(self, which, name, fn):
        vs = self.inputs if which == 'input' else self.outputs
        for k, v in enumerate(vs):
            if v.name == name:
                return k
        raise err(f'fuzzy:{fn}:UnknownVariable', f"The system has no {which} named '{name}'.", fn)

    def find_var(self, name, fn):
        for which in ('input', 'output'):
            vs = self.inputs if which == 'input' else self.outputs
            for k, v in enumerate(vs):
                if v.name == name:
                    return which, k
        raise err(f'fuzzy:{fn}:UnknownVariable', f"The system has no variable named '{name}'.", fn)

    def rule_text(self, r):
        conn = ' and ' if r.conn == 1 else ' or '
        parts = []
        for k, m in enumerate(r.ante):
            if m == 0 or k >= len(self.inputs):
                continue
            v = self.inputs[k]
            mf = v.mfs[abs(m) - 1].name if abs(m) <= len(v.mfs) else '?'
            parts.append(f'{v.name} is {"not " if m < 0 else ""}{mf}')
        outs = []
        for k, m in enumerate(r.cons):
            if m == 0 or k >= len(self.outputs):
                continue
            v = self.outputs[k]
            mf = v.mfs[abs(m) - 1].name if abs(m) <= len(v.mfs) else '?'
            outs.append(f'{v.name} is {"not " if m < 0 else ""}{mf}')
        return f'If {conn.join(parts)} then {", ".join(outs)} ({r.weight:g})'

    def _described(self, r):
        r = r.value_copy()
        r.text = self.rule_text(r)
        return r


def _fis(v, fn):
    if not isinstance(v, Fis):
        raise err(f'fuzzy:{fn}:NotFis', f'{fn} takes a fuzzy inference system (mamfis or sugfis).', fn)
    return v.value_copy()


def _named_opts(args, fn, names):
    opts = {}
    k = 0
    while k < len(args):
        o = opt_str(args[k])
        if o is None or o.lower() not in names or k + 1 >= len(args):
            raise err(f'fuzzy:{fn}:InvalidOption', f"The options are {', '.join(names)}.", fn)
        opts[o.lower()] = args[k + 1]
        k += 2
    return opts


def _default_mfs(rng, n, kind, sugeno_out=False):
    lo, hi = rng
    if sugeno_out:
        return [FisMF(f'mf{k + 1}', 'constant', [lo + (hi - lo) * k / max(n - 1, 1)]) for k in range(n)]
    if n == 1:
        return [FisMF('mf1', 'trimf' if kind == 'trimf' else kind, [lo - (hi - lo), (lo + hi) / 2, hi + (hi - lo)])]
    step = (hi - lo) / (n - 1)
    mfs = []
    for k in range(n):
        c = lo + k * step
        if kind == 'gaussmf':
            mfs.append(FisMF(f'mf{k + 1}', 'gaussmf', [step / (2 * math.sqrt(2 * math.log(2))) * 2, c]))
        else:
            mfs.append(FisMF(f'mf{k + 1}', 'trimf', [c - step, c, c + step]))
    return mfs


def _new_fis(kind, args, fn):
    names = ('name', 'numinputs', 'numinputmfs', 'numoutputs', 'numoutputmfs', 'addrules', 'mftype', 'andmethod', 'ormethod', 'implicationmethod',
             'aggregationmethod', 'defuzzificationmethod')
    o = _named_opts(args, fn, names)
    F = Fis(kind, sval(o['name'], 'Name', fn) if 'name' in o else ('mamdani' if kind == 'mamdani' else 'sugeno') + 'fis')
    ni = int(num(o['numinputs'])) if 'numinputs' in o else 0
    no = int(num(o['numoutputs'])) if 'numoutputs' in o else 0
    nim = int(num(o['numinputmfs'])) if 'numinputmfs' in o else 3
    nom = int(num(o['numoutputmfs'])) if 'numoutputmfs' in o else 3
    mft = (opt_str(o['mftype']) or 'trimf').lower() if 'mftype' in o else 'trimf'
    F.inputs = [FisVar(f'input{k + 1}', [0, 1], _default_mfs((0.0, 1.0), nim, mft)) for k in range(ni)]
    F.outputs = [FisVar(f'output{k + 1}', [0, 1], _default_mfs((0.0, 1.0), nom, mft, kind == 'sugeno')) for k in range(no)]
    for key, prop in (('andmethod', 'AndMethod'), ('ormethod', 'OrMethod'), ('implicationmethod', 'ImplicationMethod'),
                      ('aggregationmethod', 'AggregationMethod'), ('defuzzificationmethod', 'DefuzzificationMethod')):
        if key in o:
            F.setprop(prop, o[key])
    rules = (opt_str(o['addrules']) or 'allcombinations').lower() if 'addrules' in o else ('allcombinations' if ni and no else 'none')
    if rules == 'allcombinations' and ni and no:
        import itertools
        for combo in itertools.product(*[range(1, nim + 1)] * ni):
            F.rules.append(F._described(FisRule(combo, [1] * no)))
    elif rules not in ('none', 'allcombinations'):
        raise err(f'fuzzy:{fn}:InvalidAddRules', "AddRules is 'allcombinations' or 'none'.", fn)
    return F


@bi('mamfis', arr=False)
def mamfis(nargout, *args):
    """fis = mamfis('Name', name, 'NumInputs', n, 'NumInputMFs', m, 'NumOutputs', k, 'NumOutputMFs', j, 'AddRules', r, ...): a Mamdani fuzzy inference system."""
    return _new_fis('mamdani', args, 'mamfis')


@bi('sugfis', arr=False)
def sugfis(nargout, *args):
    """fis = sugfis(...): a Sugeno fuzzy inference system (constant or linear outputs)."""
    return _new_fis('sugeno', args, 'sugfis')


@bi('newfis', arr=False)
def newfis(nargout, *args):
    """fis = newfis(name, type): an empty system (older; mamfis and sugfis are preferred)."""
    nargchk(args, 1, 12, 'newfis')
    name = sval(args[0], 'name', 'newfis')
    kind = py_str(args[1]).lower() if len(args) > 1 else 'mamdani'
    if kind not in ('mamdani', 'sugeno'):
        raise err('fuzzy:newfis:InvalidType', "The type is 'mamdani' or 'sugeno'.", 'newfis')
    F = Fis(kind, name)
    for k, prop in zip(range(2, 7), ('AndMethod', 'OrMethod', 'ImplicationMethod', 'AggregationMethod', 'DefuzzificationMethod')):
        if len(args) > k and is_str(args[k]):
            F.setprop(prop, args[k])
    return F


def _add_var(nargout, args, which, fn):
    nargchk(args, 1, 10, fn)
    F = _fis(args[0], fn)
    rest = list(args[1:])
    rng = np.array([0.0, 1.0])
    if rest and not is_str(rest[0]):
        rng = np.asarray(darr(rest.pop(0)), float).reshape(-1)
    o = _named_opts(rest, fn, ('name', 'nummfs', 'mftype'))
    if rng.size != 2 or not rng[0] < rng[1]:
        raise err(f'fuzzy:{fn}:InvalidRange', 'The range is [min max] with min below max.', fn)
    vs = F.inputs if which == 'input' else F.outputs
    name = sval(o['name'], 'Name', fn) if 'name' in o else f'{which}{len(vs) + 1}'
    if any(v.name == name for v in F.inputs + F.outputs):
        raise err(f'fuzzy:{fn}:DuplicateName', f"The system has a variable named '{name}' already.", fn)
    n = int(num(o['nummfs'])) if 'nummfs' in o else (0 if 'nummfs' not in o and 'mftype' not in o else 3)
    mft = (opt_str(o['mftype']) or 'trimf').lower() if 'mftype' in o else 'trimf'
    mfs = _default_mfs(tuple(rng), n, mft, which == 'output' and F.kind == 'sugeno') if n else []
    vs.append(FisVar(name, rng, mfs))
    # the rules gain a place for the new variable
    for k, r in enumerate(F.rules):
        r = r.value_copy()
        (r.ante if which == 'input' else r.cons).append(0)
        F.rules[k] = F._described(r)
    return F


@bi('addInput', arr=False)
def addInput(nargout, *args):
    """fis = addInput(fis, range, 'Name', name, 'NumMFs', n, 'MFType', type): an input variable added."""
    return _add_var(nargout, args, 'input', 'addInput')


@bi('addOutput', arr=False)
def addOutput(nargout, *args):
    """fis = addOutput(fis, range, 'Name', name, 'NumMFs', n, 'MFType', type): an output variable added."""
    return _add_var(nargout, args, 'output', 'addOutput')


@bi('addvar', arr=False)
def addvar(nargout, *args):
    """fis = addvar(fis, 'input' or 'output', name, range): a variable added (older; addInput and addOutput are preferred)."""
    nargchk(args, 4, 4, 'addvar')
    which = py_str(args[1]).lower()
    if which not in ('input', 'output'):
        raise err('fuzzy:addvar:InvalidType', "The variable type is 'input' or 'output'.", 'addvar')
    return _add_var(nargout, [args[0], args[3], Char.of('Name'), args[2]], which, 'addvar')


def _check_mf(kind, params, F, which, fn):
    if which == 'output' and F.kind == 'sugeno':
        if kind == 'constant':
            if params.size != 1:
                raise err(f'fuzzy:{fn}:InvalidParameters', 'A constant output takes one parameter.', fn)
            return
        if kind == 'linear':
            if params.size != len(F.inputs) + 1:
                raise err(f'fuzzy:{fn}:InvalidParameters', f'A linear output takes {len(F.inputs) + 1} parameters (one for each input and a constant).', fn)
            return
        raise err(f'fuzzy:{fn}:InvalidType', "A Sugeno output's membership functions are 'constant' or 'linear'.", fn)
    need = MF_PARAMS.get(kind)
    if need is None:
        raise err(f'fuzzy:{fn}:InvalidType', f"'{kind}' is no membership function type here ({', '.join(MF_PARAMS)}).", fn)
    if params.size != need:
        raise err(f'fuzzy:{fn}:InvalidParameters', f'{kind} takes {need} parameters.', fn)


@bi('addMF', arr=False)
def addMF(nargout, *args):
    """fis = addMF(fis, varName, type, params, 'Name', mfName, 'VariableType', 'input' or 'output'): a membership function added to a variable."""
    nargchk(args, 4, 10, 'addMF')
    F = _fis(args[0], 'addMF')
    vname = sval(args[1], 'variable name', 'addMF')
    kind = sval(args[2], 'type', 'addMF').lower()
    params = np.asarray(darr(args[3]), float).reshape(-1)
    o = _named_opts(args[4:], 'addMF', ('name', 'variabletype', 'variableindex'))
    if 'variabletype' in o:
        which = py_str(o['variabletype']).lower()
        k = F.var(which, vname, 'addMF')
    else:
        which, k = F.find_var(vname, 'addMF')
    _check_mf(kind, params, F, which, 'addMF')
    vs = F.inputs if which == 'input' else F.outputs
    v = vs[k].value_copy()
    name = sval(o['name'], 'Name', 'addMF') if 'name' in o else f'mf{len(v.mfs) + 1}'
    v.mfs = list(v.mfs) + [FisMF(name, kind, params)]
    vs[k] = v
    return F


@bi('addmf', arr=False)
def addmf(nargout, *args):
    """fis = addmf(fis, 'input' or 'output', varIndex, mfName, type, params): a membership function added (older; addMF is preferred)."""
    nargchk(args, 6, 6, 'addmf')
    F = _fis(args[0], 'addmf')
    which = py_str(args[1]).lower()
    vs = F.inputs if which == 'input' else F.outputs
    k = int(num(args[2])) - 1
    if not 0 <= k < len(vs):
        raise err('fuzzy:addmf:InvalidIndex', f'The system has {len(vs)} {which}s.', 'addmf')
    return addMF(nargout, F, Char.of(vs[k].name), args[4], args[5], Char.of('Name'), args[3], Char.of('VariableType'), Char.of(which))


@bi('removeMF', arr=False)
def removeMF(nargout, *args):
    """fis = removeMF(fis, varName, mfName): a membership function taken out (rules that use it lose that clause)."""
    nargchk(args, 3, 5, 'removeMF')
    F = _fis(args[0], 'removeMF')
    which, k = F.find_var(sval(args[1], 'variable name', 'removeMF'), 'removeMF')
    vs = F.inputs if which == 'input' else F.outputs
    v = vs[k].value_copy()
    j = v.mf_index(sval(args[2], 'membership function name', 'removeMF'), 'removeMF')
    v.mfs = [m for i, m in enumerate(v.mfs) if i != j]
    vs[k] = v
    for i, r in enumerate(F.rules):
        r = r.value_copy()
        lst = r.ante if which == 'input' else r.cons
        m = lst[k]
        if abs(m) == j + 1:
            lst[k] = 0
        elif abs(m) > j + 1:
            lst[k] = int(math.copysign(abs(m) - 1, m))
        F.rules[i] = F._described(r)
    return F


def _remove_var(args, which, fn):
    nargchk(args, 2, 2, fn)
    F = _fis(args[0], fn)
    k = F.var(which, sval(args[1], 'variable name', fn), fn)
    if which == 'input':
        F.inputs = [v for i, v in enumerate(F.inputs) if i != k]
    else:
        F.outputs = [v for i, v in enumerate(F.outputs) if i != k]
    rules = []
    for r in F.rules:
        r = r.value_copy()
        lst = r.ante if which == 'input' else r.cons
        del lst[k]
        rules.append(F._described(r))
    F.rules = rules
    return F


@bi('removeInput', arr=False)
def removeInput(nargout, *args):
    """fis = removeInput(fis, name): an input taken out, with its place in the rules."""
    return _remove_var(args, 'input', 'removeInput')


@bi('removeOutput', arr=False)
def removeOutput(nargout, *args):
    """fis = removeOutput(fis, name): an output taken out, with its place in the rules."""
    return _remove_var(args, 'output', 'removeOutput')


def _parse_rule(F, text, fn):
    """A rule from text: 'If service is poor or food is rancid then tip is cheap (1)', or the symbolic form
    'service==poor | food==rancid => tip=cheap (1)'."""
    s = text.strip()
    w = 1.0
    m = re.search(r'\(\s*([0-9.eE+-]+)\s*\)\s*$', s)
    if m:
        w = float(m.group(1))
        s = s[:m.start()].strip()
    if '=>' in s:
        lhs, rhs = s.split('=>', 1)
        conn = 2 if '|' in lhs else 1
        clauses = [c.strip() for c in re.split(r'[&|]', lhs) if c.strip()]
        cons_cl = [c.strip() for c in re.split(r'[,&]', rhs) if c.strip()]
        def parse_sym(c):
            neg = '~=' in c
            a, b = re.split(r'~=|==|=', c, maxsplit=1)
            return a.strip(), b.strip(), neg
        ante_items = [parse_sym(c) for c in clauses]
        cons_items = [parse_sym(c) for c in cons_cl]
    else:
        mm = re.match(r'(?is)^\s*if\s+(.*?)\s+then\s+(.*)$', s)
        if not mm:
            raise err(f'fuzzy:{fn}:InvalidRule', f"A rule reads 'If x is a and y is b then z is c (1)': '{text}'.", fn)
        lhs, rhs = mm.group(1), mm.group(2)
        has_and = re.search(r'(?i)\band\b', lhs) is not None
        has_or = re.search(r'(?i)\bor\b', lhs) is not None
        if has_and and has_or:
            raise err(f'fuzzy:{fn}:InvalidRule', 'A rule joins its clauses all by and or all by or.', fn)
        conn = 2 if has_or else 1
        clauses = re.split(r'(?i)\s+(?:and|or)\s+', lhs)
        cons_cl = re.split(r'(?i)\s*,\s*|\s+and\s+', rhs)

        def parse_is(c):
            m2 = re.match(r'(?is)^\s*(.+?)\s+is\s+(not\s+)?(.+?)\s*$', c)
            if not m2:
                raise err(f'fuzzy:{fn}:InvalidRule', f"A clause reads 'x is a' or 'x is not a': '{c}'.", fn)
            return m2.group(1).strip(), m2.group(3).strip(), bool(m2.group(2))
        ante_items = [parse_is(c) for c in clauses]
        cons_items = [parse_is(c) for c in cons_cl if c.strip()]
    ante = [0] * len(F.inputs)
    cons = [0] * len(F.outputs)
    for var, mf, neg in ante_items:
        k = F.var('input', var, fn)
        j = F.inputs[k].mf_index(mf, fn) + 1
        ante[k] = -j if neg else j
    for var, mf, neg in cons_items:
        k = F.var('output', var, fn)
        j = F.outputs[k].mf_index(mf, fn) + 1
        cons[k] = -j if neg else j
    return FisRule(ante, cons, w, conn)


@bi('addRule', 'addrule', arr=False)
def addRule(nargout, *args):
    """fis = addRule(fis, rules): rules added: text ('If x is a and y is
    not b then z is c (0.5)', or 'x==a & y~=b => z=c (0.5)') in a string
    array or cell, or a matrix with a row [input MFs, output MFs, weight,
    connection] for each rule (0 for none, negative for not; connection 1
    and, 2 or)."""
    nargchk(args, 2, 2, 'addRule')
    F = _fis(args[0], 'addRule')
    v = args[1]
    ni, no = len(F.inputs), len(F.outputs)
    if is_str(v) or type(v) in (Str, Cell):
        texts = [py_str(v)] if type(v) is Char else ([x for x in v.a.reshape(-1, order='F')] if type(v) is Str else [py_str(c) for c in v.a.reshape(-1, order='F')])
        new = [_parse_rule(F, t, 'addRule') for t in texts]
    else:
        M = np.atleast_2d(np.asarray(darr(v), float))
        if M.shape[1] not in (ni + no, ni + no + 1, ni + no + 2):
            raise err('fuzzy:addRule:InvalidRuleMatrix', f'A rule row has {ni} input entries, {no} output entries, then the weight and the connection.', 'addRule')
        new = []
        for row in M:
            ante, cons = row[:ni], row[ni:ni + no]
            w = row[ni + no] if M.shape[1] > ni + no else 1.0
            c = int(row[ni + no + 1]) if M.shape[1] > ni + no + 1 else 1
            for k, mI in enumerate(ante):
                if abs(mI) > len(F.inputs[k].mfs):
                    raise err('fuzzy:addRule:InvalidIndex', f"The input '{F.inputs[k].name}' has {len(F.inputs[k].mfs)} membership functions.", 'addRule')
            for k, mI in enumerate(cons):
                if abs(mI) > len(F.outputs[k].mfs):
                    raise err('fuzzy:addRule:InvalidIndex', f"The output '{F.outputs[k].name}' has {len(F.outputs[k].mfs)} membership functions.", 'addRule')
            new.append(FisRule(ante, cons, w, c))
    for r in new:
        if not 0 <= r.weight <= 1:
            raise err('fuzzy:addRule:InvalidWeight', 'A rule weight is from 0 to 1.', 'addRule')
        if r.conn not in (1, 2):
            raise err('fuzzy:addRule:InvalidConnection', 'The connection is 1 (and) or 2 (or).', 'addRule')
    F.rules = F.rules + [F._described(r) for r in new]
    return F


# ---- evaluation -----------------------------------------------------------------------------------------------------------------

def _and(a, b, how):
    return np.minimum(a, b) if how == 'min' else a * b


def _or(a, b, how):
    return np.maximum(a, b) if how == 'max' else a + b - a * b


def defuzzify(x, mu, how):
    tot = mu.sum()
    if tot <= 0:
        return np.nan
    if how == 'centroid':
        return float(x @ mu / tot)
    if how == 'bisector':
        c = np.cumsum(mu)
        k = int(np.searchsorted(c, tot / 2))
        return float(x[min(k, x.size - 1)])
    top = mu.max()
    at = x[np.isclose(mu, top, rtol=0, atol=1e-12 * max(top, 1.0))]
    if how == 'mom':
        return float(at.mean())
    # the largest and smallest of the maximizing points, by magnitude
    if how == 'lom':
        return float(at[np.argmax(np.abs(at))])
    if how == 'som':
        return float(at[np.argmin(np.abs(at))])
    raise err('fuzzy:defuzz:InvalidMethod', "The method is 'centroid', 'bisector', 'mom', 'lom' or 'som'.", 'defuzz')


def evaluate(F, xin, npts=101):
    """Outputs, fuzzified inputs (rules x inputs), rule outputs, aggregated outputs and firing strengths for one input row."""
    ni, no, nr = len(F.inputs), len(F.outputs), len(F.rules)
    x = np.array(xin, float).reshape(-1)       # a copy: inputs outside their ranges are held at the ends
    clipped = False
    for k, v in enumerate(F.inputs):
        lo, hi = v.range
        if x[k] < lo or x[k] > hi:
            clipped = True
            x[k] = min(max(x[k], lo), hi)
    fz = np.zeros((nr, ni))
    fire = np.zeros(nr)
    for i, r in enumerate(F.rules):
        degs = []
        for k, m in enumerate(r.ante):
            if m == 0:
                continue
            mf = F.inputs[k].mfs[abs(m) - 1]
            d = float(mf.values(x[k]))
            if m < 0:
                d = 1 - d
            fz[i, k] = d
            degs.append(d)
        if not degs:
            w = 0.0
        else:
            w = degs[0]
            for d in degs[1:]:
                w = float(_and(w, d, F.andm) if r.conn == 1 else _or(w, d, F.orm))
        fire[i] = w * r.weight
    outs = np.zeros(no)
    agg = []
    rule_out = []
    for j, v in enumerate(F.outputs):
        if F.kind == 'mamdani':
            xs = np.linspace(v.range[0], v.range[1], npts)
            A = np.zeros(npts)
            per = np.zeros((npts, nr))
            first = True
            for i, r in enumerate(F.rules):
                m = r.cons[j]
                if m == 0:
                    continue
                mu = v.mfs[abs(m) - 1].values(xs)
                if m < 0:
                    mu = 1 - mu
                imp = np.minimum(mu, fire[i]) if F.imp == 'min' else mu * fire[i]
                per[:, i] = imp
                if F.agg == 'max':
                    A = np.maximum(A, imp)
                elif F.agg == 'sum':
                    A = A + imp
                else:
                    A = A + imp - A * imp
            agg.append(A)
            rule_out.append(per)
            val = defuzzify(xs, A, F.defuzz)
            if np.isnan(val):
                R.warn('fuzzy:evalfis:NoRuleFired', f"No rule fired for output {j + 1}: it is the middle of its range.")
                val = float(v.range.mean())
            outs[j] = val
        else:
            zs = np.zeros(nr)
            ws = np.zeros(nr)
            for i, r in enumerate(F.rules):
                m = r.cons[j]
                if m == 0:
                    continue
                zs[i] = v.mfs[abs(m) - 1].values(None, x)
                ws[i] = fire[i]
            rule_out.append(zs.reshape(-1, 1))
            agg.append(np.zeros(0))
            tot = ws.sum()
            if F.defuzz == 'wtsum':
                outs[j] = float(ws @ zs)
            elif tot > 0:
                outs[j] = float(ws @ zs / tot)
            else:
                R.warn('fuzzy:evalfis:NoRuleFired', f"No rule fired for output {j + 1}: it is the middle of its range.")
                outs[j] = float(v.range.mean())
    return outs, fz, rule_out, agg, fire, clipped


@bi('evalfis', nout=5, arr=False)
def evalfis(nargout, *args):
    """[output, fuzzifiedIn, ruleOut, aggregatedOut, ruleFiring] =
    evalfis(fis, input, options): the system's outputs for each row of
    inputs (inputs outside their ranges held at the ends, with a warning);
    options from evalfisOptions('NumSamplePoints', n) (101)."""
    nargchk(args, 2, 3, 'evalfis')
    if isinstance(args[1], Fis) and not isinstance(args[0], Fis):
        args = (args[1], args[0]) + tuple(args[2:])           # the older order: evalfis(input, fis)
    F = args[0]
    if not isinstance(F, Fis):
        raise err('fuzzy:evalfis:NotFis', 'evalfis takes a fuzzy inference system and inputs.', 'evalfis')
    if not F.rules:
        raise err('fuzzy:evalfis:NoRules', 'The system has no rules.', 'evalfis')
    X = np.atleast_2d(np.asarray(darr(args[1]), float))
    ni = len(F.inputs)
    if X.shape[1] != ni:
        if X.shape[0] == ni and X.shape[1] != ni:
            X = X.T
        else:
            raise err('fuzzy:evalfis:InputSize', f'The input has a column for each of the {ni} inputs.', 'evalfis')
    npts = 101
    if len(args) > 2:
        o = args[2]
        npts = int(num(o.get1('NumSamplePoints'))) if type(o) is Struct and 'NumSamplePoints' in o.f else int(num(o))
    res = [evaluate(F, row, npts) for row in X]
    if any(r[5] for r in res):
        R.warn('fuzzy:evalfis:InputOutOfRange', 'An input is outside its range: the value at the end of the range is used.')
    out_ = out(np.array([r[0] for r in res]))
    if nargout <= 1:
        return out_
    last = res[-1]
    rule_out = out(np.hstack(last[2])) if last[2] else EMPTY()
    agg = out(np.column_stack(last[3])) if last[3] and last[3][0].size else EMPTY()
    vals = (out_, out(last[1]), rule_out, agg, out(last[4].reshape(-1, 1)))
    return vals[:nargout]


@bi('evalfisOptions', arr=False)
def evalfisOptions(nargout, *args):
    """opt = evalfisOptions('NumSamplePoints', n): options for evalfis."""
    o = _named_opts(args, 'evalfisOptions', ('numsamplepoints', 'outofrangeinputvaluemessage', 'norulefiredmessage', 'emptyoutputfuzzysetmessage'))
    n = float(num(o['numsamplepoints'])) if 'numsamplepoints' in o else 101.0
    if n < 2:
        raise err('fuzzy:evalfisOptions:InvalidPoints', 'NumSamplePoints is at least 2.', 'evalfisOptions')
    return Struct.scalar({'NumSamplePoints': n})


@bi('evalmf', arr=False)
def evalmf(nargout, *args):
    """y = evalmf(mf, x) or evalmf(x, params, type): a membership function's values."""
    nargchk(args, 2, 3, 'evalmf')
    if isinstance(args[0], FisMF):
        return out(np.asarray(args[0].values(np.asarray(darr(args[1]), float)), float))
    if len(args) != 3:
        raise err('fuzzy:evalmf:InvalidInput', 'evalmf(mf, x) or evalmf(x, params, type).', 'evalmf')
    return out(mf_eval(sval(args[2], 'type', 'evalmf').lower(), darr(args[1]), np.asarray(darr(args[0]), float)))


@bi('fismf', arr=False)
def fismf(nargout, *args):
    """mf = fismf(type, params, 'Name', name): a membership function object (trimf over [0 1] unless given)."""
    kind = sval(args[0], 'type', 'fismf').lower() if args else 'trimf'
    params = np.asarray(darr(args[1]), float).reshape(-1) if len(args) > 1 else np.array([-0.5, 0, 0.5])
    o = _named_opts(args[2:], 'fismf', ('name',))
    if kind not in ('constant', 'linear'):
        need = MF_PARAMS.get(kind)
        if need is None or params.size != need:
            raise err('fuzzy:fismf:InvalidParameters', f"'{kind}' takes {need} parameters." if need else f"'{kind}' is no membership function type.", 'fismf')
    return FisMF(sval(o['name'], 'Name', 'fismf') if 'name' in o else 'mf', kind, params)


@bi('defuzz')
def defuzz(nargout, *args):
    """out = defuzz(x, mf, type): a crisp value of a fuzzy set over x: 'centroid', 'bisector', 'mom', 'lom' or 'som'."""
    nargchk(args, 3, 3, 'defuzz')
    x = np.asarray(darr(args[0]), float).reshape(-1)
    mu = np.asarray(darr(args[1]), float).reshape(-1)
    if x.size != mu.size:
        raise err('fuzzy:defuzz:SizeMismatch', 'x and mf have the same number of values.', 'defuzz')
    v = defuzzify(x, mu, sval(args[2], 'type', 'defuzz').lower())
    return v


@bi('showrule', arr=False)
def showrule(nargout, *args):
    """showrule(fis), rules = showrule(fis, indices, format): the rules as
    text: 'verbose' (the default), 'symbolic' or 'indexed'."""
    nargchk(args, 1, 3, 'showrule')
    F = args[0]
    if not isinstance(F, Fis):
        raise err('fuzzy:showrule:NotFis', 'showrule takes a fuzzy inference system.', 'showrule')
    idx = [int(v) - 1 for v in np.asarray(darr(args[1])).reshape(-1)] if len(args) > 1 and numel(args[1]) else list(range(len(F.rules)))
    fmt = py_str(args[2]).lower() if len(args) > 2 else 'verbose'
    lines = []
    for k in idx:
        r = F.rules[k]
        if fmt == 'verbose':
            lines.append(f'{k + 1}. {F.rule_text(r)}')
        elif fmt == 'symbolic':
            cl = []
            for i, m in enumerate(r.ante):
                if m:
                    cl.append(f'({F.inputs[i].name}{"~=" if m < 0 else "=="}{F.inputs[i].mfs[abs(m) - 1].name})')
            co = [f'({F.outputs[i].name}={F.outputs[i].mfs[abs(m) - 1].name})' for i, m in enumerate(r.cons) if m]
            lines.append(f'{k + 1}. {(" & " if r.conn == 1 else " | ").join(cl)} => {", ".join(co)} ({r.weight:g})')
        elif fmt == 'indexed':
            lines.append(f'{" ".join(str(v) for v in r.ante)}, {" ".join(str(v) for v in r.cons)} ({r.weight:g}) : {r.conn}')
        else:
            raise err('fuzzy:showrule:InvalidFormat', "The format is 'verbose', 'symbolic' or 'indexed'.", 'showrule')
    if nargout:
        return Cell.of_list([Char.of(l) for l in lines], (len(lines), 1))
    R.write('\n'.join(lines) + '\n')
    return None


@bi('plotmf', nout=2, arr=False)
def plotmf(nargout, *args):
    """plotmf(fis, 'input' or 'output', k), [x, y] = plotmf(...): a variable's membership functions drawn (or their values)."""
    nargchk(args, 3, 4, 'plotmf')
    F = args[0]
    if not isinstance(F, Fis):
        raise err('fuzzy:plotmf:NotFis', 'plotmf takes a fuzzy inference system.', 'plotmf')
    which = py_str(args[1]).lower()
    vs = F.inputs if which == 'input' else F.outputs
    k = int(num(args[2])) - 1
    if not 0 <= k < len(vs):
        raise err('fuzzy:plotmf:InvalidIndex', f'The system has {len(vs)} {which}s.', 'plotmf')
    v = vs[k]
    n = int(num(args[3])) if len(args) > 3 else 181
    xs = np.linspace(v.range[0], v.range[1], n)
    if which == 'output' and F.kind == 'sugeno':
        raise err('fuzzy:plotmf:Sugeno', "A Sugeno output's membership functions are constants or linear functions: there is nothing to draw.", 'plotmf')
    Y = np.column_stack([np.asarray(m.values(xs), float) for m in v.mfs]) if v.mfs else np.zeros((n, 0))
    if nargout:
        return (out(np.repeat(xs.reshape(-1, 1), max(Y.shape[1], 1), axis=1)), out(Y)) if nargout > 1 else out(np.repeat(xs.reshape(-1, 1), max(Y.shape[1], 1), axis=1))
    b = lambda name, *a: R._builtin(name, *a)
    b('plot', out(xs.reshape(-1, 1)), out(Y))
    for j, m in enumerate(v.mfs):
        top = int(np.argmax(Y[:, j]))
        b('text', float(xs[top]), 1.03, Char.of(m.name), Char.of('HorizontalAlignment'), Char.of('center'))
    b('ylim', out(np.array([[0.0, 1.1]])))
    b('xlabel', Char.of(v.name))
    b('ylabel', Char.of('Degree of membership'))
    return None


@bi('gensurf', nout=3, arr=False)
def gensurf(nargout, *args):
    """gensurf(fis), [X, Y, Z] = gensurf(fis, inputs, output, n): the output
    over a grid of two inputs (15 by 15 unless n), the others at the middles
    of their ranges; with one input a curve."""
    nargchk(args, 1, 4, 'gensurf')
    F = args[0]
    if not isinstance(F, Fis):
        raise err('fuzzy:gensurf:NotFis', 'gensurf takes a fuzzy inference system.', 'gensurf')
    ni = len(F.inputs)
    ins = [int(v) - 1 for v in np.asarray(darr(args[1])).reshape(-1)] if len(args) > 1 and numel(args[1]) else list(range(min(ni, 2)))
    oi = int(num(args[2])) - 1 if len(args) > 2 and numel(args[2]) else 0
    n = int(num(args[3])) if len(args) > 3 else (15 if len(ins) > 1 else 101)
    mids = np.array([v.range.mean() for v in F.inputs])
    b = lambda name, *a: R._builtin(name, *a)
    if len(ins) == 1:
        xs = np.linspace(*F.inputs[ins[0]].range, n)
        rows = np.tile(mids, (n, 1))
        rows[:, ins[0]] = xs
        Z = np.array([evaluate(F, r)[0][oi] for r in rows])
        if nargout:
            return (out(xs.reshape(-1, 1)), out(Z.reshape(-1, 1))) if nargout > 1 else out(xs.reshape(-1, 1))
        b('plot', out(xs.reshape(-1, 1)), out(Z.reshape(-1, 1)))
        b('xlabel', Char.of(F.inputs[ins[0]].name))
        b('ylabel', Char.of(F.outputs[oi].name))
        return None
    xa = np.linspace(*F.inputs[ins[0]].range, n)
    ya = np.linspace(*F.inputs[ins[1]].range, n)
    X, Y = np.meshgrid(xa, ya)
    Z = np.zeros_like(X)
    for i in range(n):
        for j in range(n):
            r = mids.copy()
            r[ins[0]], r[ins[1]] = X[i, j], Y[i, j]
            Z[i, j] = evaluate(F, r)[0][oi]
    if nargout:
        vals = (out(X), out(Y), out(Z))
        return vals[:nargout] if nargout > 1 else vals[0]
    b('surf', out(X), out(Y), out(Z))
    b('xlabel', Char.of(F.inputs[ins[0]].name))
    b('ylabel', Char.of(F.inputs[ins[1]].name))
    b('zlabel', Char.of(F.outputs[oi].name))
    return None


# ---- .fis files ------------------------------------------------------------------------------------------------------------------

def _fmt_vec(v):
    return '[' + ' '.join(repr(float(x)).rstrip('0').rstrip('.') if float(x) != int(float(x)) else str(int(float(x))) for x in v) + ']'


@bi('writefis')
def writefis(nargout, *args):
    """writefis(fis, filename): the system written as a .fis text file."""
    nargchk(args, 1, 3, 'writefis')
    F = args[0]
    if not isinstance(F, Fis):
        raise err('fuzzy:writefis:NotFis', 'writefis takes a fuzzy inference system.', 'writefis')
    name = sval(args[1], 'file name', 'writefis') if len(args) > 1 else F.name
    from .iofun import abspath, files_changed
    p = abspath(name if name.endswith('.fis') else name + '.fis')
    L = ['[System]', f"Name='{F.name}'", f"Type='{F.kind}'", 'Version=2.0', f'NumInputs={len(F.inputs)}', f'NumOutputs={len(F.outputs)}',
         f'NumRules={len(F.rules)}', f"AndMethod='{F.andm}'", f"OrMethod='{F.orm}'", f"ImpMethod='{F.imp}'", f"AggMethod='{F.agg}'",
         f"DefuzzMethod='{F.defuzz}'"]
    for title, vs in (('Input', F.inputs), ('Output', F.outputs)):
        for k, v in enumerate(vs):
            L += ['', f'[{title}{k + 1}]', f"Name='{v.name}'", f'Range={_fmt_vec(v.range)}', f'NumMFs={len(v.mfs)}']
            L += [f"MF{j + 1}='{m.name}':'{m.kind}',{_fmt_vec(m.params)}" for j, m in enumerate(v.mfs)]
    L += ['', '[Rules]']
    for r in F.rules:
        L.append(f'{" ".join(str(v) for v in r.ante)}, {" ".join(str(v) for v in r.cons)} ({r.weight:g}) : {r.conn}')
    try:
        with open(p, 'w', encoding='utf-8') as f:
            f.write('\n'.join(L) + '\n')
    except OSError as e:
        raise err('fuzzy:writefis:WriteError', f'Unable to write {name}: {e.strerror or e}.', 'writefis')
    files_changed(os.path.dirname(p))
    return None


@bi('readfis', arr=False)
def readfis(nargout, *args):
    """fis = readfis(filename): a system from a .fis text file."""
    nargchk(args, 1, 1, 'readfis')
    from .iofun import abspath
    name = sval(args[0], 'file name', 'readfis')
    p = abspath(name)
    if not os.path.isfile(p) and os.path.isfile(p + '.fis'):
        p += '.fis'
    if not os.path.isfile(p):
        raise err('fuzzy:readfis:FileNotFound', f"Unable to find '{name}'.", 'readfis')
    with open(p, encoding='utf-8', errors='replace') as f:
        text = f.read()
    sections = {}
    cur = None
    for line in text.splitlines():
        t = line.strip()
        if not t or t.startswith('%') or t.startswith('#'):
            continue
        m = re.match(r'^\[(\w+)\]$', t)
        if m:
            cur = m.group(1)
            sections[cur] = []
            continue
        if cur is not None:
            sections[cur].append(t)

    def kv(lines):
        d = {}
        for l in lines:
            if '=' in l:
                k, v = l.split('=', 1)
                d[k.strip()] = v.strip()
        return d

    def unq(s):
        s = s.strip()
        return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == "'" else s

    def vec(s):
        return np.array([float(x) for x in s.strip().strip('[]').replace(',', ' ').split()], float)
    if 'System' not in sections:
        raise err('fuzzy:readfis:InvalidFile', f"'{name}' has no [System] section.", 'readfis')
    S = kv(sections['System'])
    kind = unq(S.get('Type', "'mamdani'")).lower()
    if kind not in ('mamdani', 'sugeno'):
        raise err('fuzzy:readfis:InvalidType', f"The system type '{kind}' is not read here.", 'readfis')
    F = Fis(kind, unq(S.get('Name', "'fis'")))
    F.andm = unq(S.get('AndMethod', repr(F.andm)))
    F.orm = unq(S.get('OrMethod', repr(F.orm)))
    F.imp = unq(S.get('ImpMethod', repr(F.imp)))
    F.agg = unq(S.get('AggMethod', repr(F.agg)))
    F.defuzz = unq(S.get('DefuzzMethod', repr(F.defuzz)))
    for title, store in (('Input', F.inputs), ('Output', F.outputs)):
        k = 1
        while f'{title}{k}' in sections:
            d = kv(sections[f'{title}{k}'])
            mfs = []
            j = 1
            while f'MF{j}' in d:
                m = re.match(r"^'([^']*)'\s*:\s*'([^']*)'\s*,\s*(\[.*\])\s*$", d[f'MF{j}'])
                if not m:
                    raise err('fuzzy:readfis:InvalidMF', f"MF{j} of {title}{k} cannot be read.", 'readfis')
                mfs.append(FisMF(m.group(1), m.group(2), vec(m.group(3))))
                j += 1
            store.append(FisVar(unq(d.get('Name', f"'{title.lower()}{k}'")), vec(d.get('Range', '[0 1]')), mfs))
            k += 1
    for l in sections.get('Rules', []):
        m = re.match(r'^(.*?),(.*?)\(([^)]*)\)\s*:\s*(\d+)\s*$', l)
        if not m:
            raise err('fuzzy:readfis:InvalidRule', f"The rule line '{l}' cannot be read.", 'readfis')
        ante = [int(float(x)) for x in m.group(1).split()]
        cons = [int(float(x)) for x in m.group(2).split()]
        F.rules.append(F._described(FisRule(ante, cons, float(m.group(3)), int(m.group(4)))))
    return F


def classes():
    return (Fis, FisVar, FisMF, FisRule, FisArray)
