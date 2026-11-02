#!/usr/bin/env python3
"""Emit resources/py/plab/vernertab.py: Verner's 8(7) and 9(8) pairs with
their extra stages and interpolants, for PyLAB's ode78 and ode89.

The coefficients are read from the exact (generic-type) methods of
OrdinaryDiffEq.jl's verner_tableaus.jl -- rationals, 40-digit decimals and
sums with 6^(1 // 2) -- with 80-digit decimals, and each is written as the
double nearest it. The file is only pattern-matched, never evaluated.
Nothing is written unless the tables satisfy the identities they must: the
rows of `a` sum to the nodes, `b` sums to one and `btilde` to zero, b c^q
sums to 1/(q + 1) up to the order, and each interpolant gives the step's
own result at theta = 1.

    python3 scripts/gen-vernertab.py [verner_tableaus.jl]

With no argument the file is downloaded from the SciML repository.
"""
import re
import subprocess
import sys
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 80
URL = 'https://raw.githubusercontent.com/SciML/OrdinaryDiffEq.jl/master/lib/OrdinaryDiffEqVerner/src/verner_tableaus.jl'
OUT = Path(__file__).resolve().parent.parent / 'resources/py/plab/vernertab.py'
if len(sys.argv) > 1:
    text = Path(sys.argv[1]).read_text(encoding='utf-8')
else:
    text = subprocess.run(['curl', '-sSf', URL], capture_output=True, text=True, check=True).stdout


def body(head):
    """The text of the function whose first line starts with head."""
    i = text.index(head)
    j = text.index('\nend\n', i)
    return text[i:j]


SQRT6 = Decimal(6).sqrt()


def value(expr):
    """A coefficient as an 80-digit Decimal: big"...", or a sum of terms
    +-p // q, each perhaps times 6^(1 // 2)."""
    e = ' '.join(expr.split())
    m = re.fullmatch(r'big"\s*([-+]?[0-9.]+(?:[eE][-+]?\d+)?)\s*"', e)
    if m:
        return Decimal(m.group(1))
    e = re.sub(r'BigInt\((-?\d+)\)', r'\1', e).replace('6^(1 // 2)', 'S6')
    e = re.sub(r'-\s*-', '+', re.sub(r'\+\s*-', '-', e))
    total = Decimal(0)
    pos = 0
    term = re.compile(r'\s*([-+]?)\s*(\d+)(?:\s*//\s*(\d+))?(\s*\*\s*S6)?\s*')
    while pos < len(e):
        m = term.match(e, pos)
        if not m or m.end() == pos:
            raise ValueError(f'unread coefficient: {expr!r}')
        v = Decimal(int(m.group(2))) / Decimal(int(m.group(3) or 1))
        if m.group(4):
            v *= SQRT6
        total += -v if m.group(1) == '-' else v
        pos = m.end()
    return total


def assignments(src):
    """name -> Fraction for every `name = convert(T or T2, expr)`."""
    out = {}
    for m in re.finditer(r'^\s*(\w+)\s*=\s*convert\(\s*T2?\s*,', src, re.M):
        i = m.end()
        depth = 1
        j = i
        while depth:
            ch = src[j]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            j += 1
        out[m.group(1)] = value(src[i:j - 1])
    return out


def build(name, n_main, sol_order):
    tab = assignments(body(f'function {name}Tableau(::Type{{T}}, ::Type{{T2}}) where {{T, T2}}'))
    extra_head = (f'@fold function {name}ExtraStages(::Type{{T}}, ::Type{{T2}}) where {{T, T2}}'
                  if f'@fold function {name}ExtraStages(::Type{{T}}' in text else
                  f'function {name}ExtraStages(::Type{{T}}, ::Type{{T2}}) where {{T, T2}}')
    extra = assignments(body(extra_head))
    interp_head = f'function {name}InterpolationCoefficients(::Type{{T}}) where {{T}}'
    interp = assignments(body(interp_head))
    A = {}
    b, bt, rr = {}, {}, {}
    for k, v in list(tab.items()) + list(extra.items()):
        m = re.fullmatch(r'a(\d\d)(\d\d)', k)
        if m:
            A[(int(m.group(1)), int(m.group(2)))] = v
            continue
        m = re.fullmatch(r'btilde(\d+)', k)
        if m:
            bt[int(m.group(1))] = v
            continue
        m = re.fullmatch(r'b(\d+)', k)
        if m:
            b[int(m.group(1))] = v
    for k, v in interp.items():
        m = re.fullmatch(r'r(\d\d)(\d)', k)
        if not m:
            raise ValueError(f'unread interpolation name {k}')
        rr.setdefault(int(m.group(1)), {})[int(m.group(2))] = v
    stages = max(i for i, _ in A)
    c = {1: Decimal(0)}
    for i in range(2, stages + 1):
        c[i] = sum((v for (r, _), v in A.items() if r == i), Decimal(0))
    # the named nodes agree with the row sums (Vern9 names a stage's node one lower)
    named = sorted(v for k, v in list(tab.items()) + list(extra.items()) if re.fullmatch(r'c\d+', k))
    for v in named:
        assert any(abs(v - c[i]) < Decimal('1e-35') for i in c), (name, float(v))
    # checks: weights, error weights, bushy order conditions, the interpolant at 1
    assert abs(sum(b.values()) - 1) < Decimal('1e-30'), name
    assert abs(sum(bt.values())) < Decimal('1e-30'), (name, float(sum(bt.values())))
    for q in range(sol_order):
        s = sum(b[i] * (c[i] ** q if q else Decimal(1)) for i in b)
        assert abs(s - (Decimal(1) / (q + 1))) < Decimal('1e-30'), (name, q, float(s - (Decimal(1) / (q + 1))))
    deg = max(p for d in rr.values() for p in d)
    for i in range(1, stages + 1):
        at1 = sum(rr.get(i, {}).values(), Decimal(0))
        assert abs(at1 - b.get(i, 0)) < Decimal('1e-30'), (name, i, float(at1), float(b.get(i, 0)))
    print(f'{name}: {stages} stages ({n_main} for the step), interpolant of degree {deg}; checks pass')
    return dict(stages=stages, n_main=n_main, A=A, c=c, b=b, bt=bt, rr=rr, deg=deg)


def f17(x):
    return repr(float(x))


def emit(name, t):
    s, nm = t['stages'], t['n_main']
    lines = [f'{name}_STAGES = {nm}', f'{name}_ALL = {s}']
    lines.append(f'{name}_C = [' + ', '.join(f17(t["c"][i]) for i in range(1, s + 1)) + ']')
    lines.append(f'{name}_A = {{  # (row, column) -> a, rows and columns from 1')
    for (i, j) in sorted(t['A']):
        lines.append(f'    ({i}, {j}): {f17(t["A"][(i, j)])},')
    lines.append('}')
    lines.append(f'{name}_B = {{' + ', '.join(f'{i}: {f17(v)}' for i, v in sorted(t['b'].items())) + '}')
    lines.append(f'{name}_E = {{' + ', '.join(f'{i}: {f17(v)}' for i, v in sorted(t['bt'].items())) + '}')
    lines.append(f'{name}_R = {{  # stage -> {{power of theta: coefficient}}')
    for i in sorted(t['rr']):
        lines.append(f'    {i}: {{' + ', '.join(f'{p}: {f17(v)}' for p, v in sorted(t['rr'][i].items())) + '},')
    lines.append('}')
    return '\n'.join(lines)


v8 = build('Vern8', 13, 8)
v9 = build('Vern9', 16, 9)
header = '''"""Coefficients of J. H. Verner's "most efficient" Runge-Kutta pairs of
orders 8(7) and 9(8), with the extra stages and the polynomial weights of
their interpolants (orders 7 and 8): ode78 and ode89.

Generated by scripts/gen-vernertab.py from the exact (rational and
40-digit) values in OrdinaryDiffEq.jl's verner_tableaus.jl, after checking
that the weights sum to 1, the error weights to 0, every node is its row's
sum, the quadrature conditions hold to the method's order and the
interpolant gives the step's result at its end. Each value is the double
nearest the exact one.

OrdinaryDiffEq.jl is under the MIT "Expat" license:
Copyright (c) 2016-2020: ChrisRackauckas, Yingbo Ma, Julia Computing Inc,
and other contributors. Permission is hereby granted, free of charge, to
any person obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the
following conditions: The above copyright notice and this permission notice
shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED.

J. H. Verner, "Numerically optimal Runge-Kutta pairs with interpolants",
Numerical Algorithms 53 (2010) 383-396.
"""
'''
OUT.write_text(header + '\n' + emit('VERN8', v8) + '\n\n' + emit('VERN9', v9) + '\n', encoding='utf-8')
print('written', OUT)
