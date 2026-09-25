"""The equation language against the application's: parser, functions, tables."""

from __future__ import annotations

import json
import math
import random
import subprocess
import unittest
from typing import Any, Dict, List

from helpers import EXAMPLES, HERE, NODE, SRC, needs_app

from kompartment import jsmath
from kompartment.engine.functions import FUNCTIONS
from kompartment.engine.lang import Binary, Call, Cond, Num, ParseError, Ref, Unary, parse
from kompartment.engine.lookup import Table
from kompartment.engine.reduce import percentile


def engine(task: str, **request: Any) -> Dict[str, Any]:
    """Asks the application's engine (see tests/node/engine.mjs)."""
    def enc(x: Any) -> Any:
        if isinstance(x, float) and not math.isfinite(x):
            return 'NaN' if x != x else ('Infinity' if x > 0 else '-Infinity')
        if isinstance(x, dict):
            return {k: enc(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [enc(v) for v in x]
        return x
    proc = subprocess.run([NODE, str(HERE / 'node' / 'engine.mjs'), str(SRC)],
                          input=json.dumps(enc({'task': task, **request})), capture_output=True, text=True,
                          timeout=900, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout, parse_constant=float)


def number(v: Any) -> float:
    if isinstance(v, str):
        return {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf}[v]
    return float(v)


def decode(x: Any) -> Any:
    """The app's JSON with its non-finite numbers put back."""
    if isinstance(x, dict):
        return {k: (number(v) if k == 'value' and isinstance(v, str) else decode(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [decode(v) for v in x]
    return x


def as_json(node: Any) -> Dict[str, Any]:
    if isinstance(node, Num):
        out: Dict[str, Any] = {'type': 'num', 'value': node.value}
        if node.unit is not None:
            out['unit'] = node.unit
        return out
    if isinstance(node, Ref):
        return {'type': 'ref', 'name': node.name, 'indices': list(node.indices)}
    if isinstance(node, Call):
        return {'type': 'call', 'name': node.name, 'args': [as_json(a) for a in node.args]}
    if isinstance(node, Unary):
        return {'type': 'unary', 'op': node.op, 'operand': as_json(node.operand)}
    if isinstance(node, Binary):
        return {'type': 'binary', 'op': node.op, 'left': as_json(node.left), 'right': as_json(node.right)}
    if isinstance(node, Cond):
        return {'type': 'cond', 'test': as_json(node.test), 'then': as_json(node.then),
                'otherwise': as_json(node.otherwise)}
    raise TypeError(node)


def example_equations() -> List[str]:
    out = []
    keys = ('equation', 'rate', 'initial', 'dydt', 'target', 'first', 'second', 'delay')
    for path in sorted(EXAMPLES.glob('*.json')):
        model = json.loads(path.read_text('utf-8'))
        for coll, blocks in model.items():
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                for holder in [b, *(b.get('entries') or [])]:
                    for k in keys:
                        if isinstance(holder.get(k), str):
                            out.append(holder[k])
    return out


TRICKY = [
    '', '0', '1e-3', '.5', '2^3^2', '-a^2', '2^-1', '-2^-2', 'a ? b : c ? d : e', '(a ? b : c) + 1',
    'a && b || c', 'a || b && c', 'a == b ~= c', 'a != b', 'a .* b ./ c .^ d', 'max(a, b, c)', 'min(1)',
    'if(a > 0, b)', 'if(a, b, c)', 'pi', 'pi()', 'time', 'time()', 'eps + ulp(x)', 'M[Cs-137][]', 'M[][Lake]',
    'M[ 11 ][Lake]', 'k[_source_] * C1', '0.01[m] + x', '5[ mm ]', '3[]', 'sum(a,b)', 'sgn(x)', 'ln(x)',
    'pow(a, b)', 'fabs(-1)', 'product(a, b)', 'a -- b', 'a - -b', '+a', '-(-a)', 'a+', '(a', 'a)', 'f(x)',
    'max()', 'if(a)', 'Table(x)', 'a ? b', '1 2', 'a[', 'exp(1, 2)', 'x <= y >= z < w > v',
    'mod(a, b) + rem(-a, b)', 'interpolationUseEndValues(t, 0, 1, 10, 2)', '!a', 'a ! b',
    '1e309', '-1e309 * 0', 'a^b^c^d', '((((((a))))))', 'not(a)', 'xor(a, b, c)',
]


@needs_app
class ParserParity(unittest.TestCase):
    def test_equations_parse_as_the_app_parses_them(self) -> None:
        equations = sorted(set(example_equations())) + TRICKY
        js = engine('parse', equations=equations, calls=['Table'])['results']
        for eq, want in zip(equations, js):
            with self.subTest(equation=eq):
                try:
                    got = {'ast': as_json(parse(eq, calls=lambda n: n == 'Table'))}
                except ParseError as e:
                    got = {'error': str(e), 'position': e.position}
                if 'ast' in want:
                    self.assertEqual(json.loads(json.dumps(got), parse_constant=float), decode(want))
                else:
                    self.assertEqual(got.get('error'), want['error'])
                    self.assertEqual(got.get('position'), want.get('position'))


SPECIAL = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.5, -2.5, 1e-300, 1e300, math.inf, -math.inf, math.nan, 3.0, 170.0,
           171.0, 0.49999999999999994, 1e16 + 1]


def draw(rng: random.Random) -> float:
    r = rng.random()
    if r < 0.25:
        return rng.choice(SPECIAL)
    if r < 0.5:
        return rng.uniform(-3, 3)
    if r < 0.75:
        return rng.uniform(0, 1)
    return rng.uniform(-50, 50)


def argcount(spec: Dict[str, Any], rng: random.Random) -> int:
    lo = spec['arity']
    hi = spec.get('maxArity')
    if hi is None:
        hi = lo + 4 if spec.get('varargs') else lo
    return rng.randint(lo, hi)


def close(a: float, b: float) -> bool:
    if a != a or b != b:
        return a != a and b != b
    if a == b:
        return True
    if math.isinf(a) or math.isinf(b):
        return False
    return abs(a - b) <= 4e-15 * max(abs(a), abs(b)) or abs(a - b) < 1e-300


@needs_app
class FunctionParity(unittest.TestCase):
    def test_every_function_answers_as_the_app_does(self) -> None:
        rng = random.Random(11)
        calls = []
        for name, spec in FUNCTIONS.items():
            for _ in range(60):
                n = argcount(spec, rng)
                args = [draw(rng) for _ in range(n)]
                if name.startswith('transport_'):
                    # the position arguments are fractions of the chain
                    k = 1 if name == 'transport_point' else 2
                    args[-k:] = [rng.choice([rng.random(), 0.0, 1.0, rng.uniform(-0.2, 1.2)]) for _ in range(k)]
                if name == 'percentile':
                    args[0] = rng.choice([0, 25, 50, 75, 100, rng.uniform(-10, 110)])
                calls.append([name, *args])
        js = engine('functions', calls=calls)['results']

        class Ctx:
            t, start_time, end_time = 12.5, 0.0, 1000.0

        bad = []
        for call, want in zip(calls, js):
            name, args = call[0], [number(a) if isinstance(a, str) else a for a in call[1:]]
            spec = FUNCTIONS[name]
            try:
                got = spec['fn'](Ctx, *args) if spec.get('needsContext') else spec['fn'](*args)
                got = float(got)
            except Exception as e:  # noqa: BLE001 - compared with the app's error below
                got = e
            if 'error' in want:
                if not isinstance(got, Exception):
                    bad.append(f'{name}{tuple(args)}: {got} but the app raised {want["error"]}')
                continue
            w = number(want['value'])
            if isinstance(got, Exception) or not close(got, w):
                bad.append(f'{name}{tuple(args)}: {got!r} != {w!r}')
        self.assertEqual(bad, [])


@needs_app
class TableParity(unittest.TestCase):
    def test_tables_read_as_the_app_reads_them(self) -> None:
        rng = random.Random(5)
        cases = []
        for interp in ('linear', 'extrapolate', 'below', 'above', 'nearest'):
            for cyclic in (False, True):
                for n in (1, 2, 5):
                    xs = sorted(rng.choice([0.0, 1.0, 2.0, 2.0, 5.0, rng.uniform(-3, 8)]) for _ in range(n))
                    pts = [[x, rng.uniform(-5, 5)] for x in xs]
                    rng.shuffle(pts)
                    keys = [rng.uniform(-10, 15) for _ in range(20)] + xs + [math.nan]
                    cases.append({'points': pts, 'interpolation': interp, 'cyclic': cyclic, 'keys': keys})
        script = """
            import { makeTable } from %s;
            const cases = JSON.parse(require_stdin());
        """
        del script
        src = (
            "const src = process.argv[1];\n"
            "import(require('url').pathToFileURL(src + '/domain/lookup.js').href).then(({ makeTable }) => {\n"
            "  const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'), (k, v) => v === 'NaN' ? NaN : v);\n"
            "  const out = cases.map((c) => { const t = makeTable(c.points, c); return {\n"
            "    at: c.keys.map((k) => { const v = t.at(k); return Number.isFinite(v) ? v : String(v); }),\n"
            "    slope: c.keys.map((k) => { const v = t.slopeAt(k); return Number.isFinite(v) ? v : String(v); }) }; });\n"
            "  process.stdout.write(JSON.stringify(out));\n"
            "});\n"
        )
        enc = json.dumps(cases).replace('NaN', '"NaN"')
        proc = subprocess.run([NODE, '-e', src, str(SRC)], input=enc, capture_output=True, text=True, check=True)
        js = json.loads(proc.stdout)
        for case, want in zip(cases, js):
            t = Table(case['points'], case['interpolation'], case['cyclic'])
            import numpy as np
            vec = t.at(np.array(case['keys']))
            for k, w, s, v in zip(case['keys'], want['at'], want['slope'], vec):
                with self.subTest(case=case['interpolation'], cyclic=case['cyclic'], key=k):
                    self.assertTrue(close(t.at(k), number(w)), (t.at(k), w))
                    self.assertTrue(close(float(v), number(w)), (v, w))
                    self.assertTrue(close(t.slope_at(k), number(s)), (t.slope_at(k), s))


class Percentile(unittest.TestCase):
    def test_the_standard_definition(self) -> None:
        self.assertEqual(percentile(50, [3, 1, 2]), 2)
        self.assertEqual(percentile(50, [4, 1, 2, 3]), 2.5)
        self.assertEqual(percentile(0, [4, 1, 2, 3]), 1)
        self.assertEqual(percentile(100, [4, 1, 2, 3]), 4)
        self.assertTrue(math.isnan(percentile(101, [1])))
        self.assertAlmostEqual(percentile(25, [1, 2, 3, 4]), 1.5)


class V8Math(unittest.TestCase):
    def test_grid_functions_match_known_v8_values(self) -> None:
        # Values V8 gives, where the platform's libm may not.
        self.assertEqual(jsmath.log(1e5), 11.512925464970229)
        self.assertEqual(jsmath.exp(1.0), 2.718281828459045)
        self.assertEqual(jsmath.log10(1000.0), 3.0)


if __name__ == '__main__':
    unittest.main()
