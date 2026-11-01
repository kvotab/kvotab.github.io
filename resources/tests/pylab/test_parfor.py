"""parfor loops on a parallel pool, run natively: the loop's analysis (which
variables are broadcast, sliced, reductions or temporaries, and why a loop
must run one pass at a time), the values sent to the workers and back, and
the results put together in the order of the passes.

    python3 test_parfor.py      (from any folder; needs numpy and scipy)

The pool here runs its workers in this process: each block of passes goes
through the same Python the page's workers run (pool_job, pool_chunk,
pool_written), in a shuffled order, so that the results must not depend on
which block finishes first. test-ui.py runs a real pool in Chrome.
"""
import asyncio
import json
import math
import os
import random
import shutil
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import worker_api  # noqa: E402
from plab.values import Char, Cell, Struct, Str  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-parfor-')
R.STATE['cwd'] = TMP
R.STATE['home'] = TMP
from plab.builtins.parallel import POOL  # noqa: E402

failed = []
checks = [0]


def check(label, ok, detail=''):
    checks[0] += 1
    if not ok:
        failed.append(label)
        print(f'FAIL  {label}  {detail}')


class InProcessPool:
    """A pool whose workers run here: each block of passes goes through the
    workers' Python, in a shuffled order. Counts the blocks it ran."""

    def __init__(self, cores=4):
        self.n = 0
        self.ncores = cores
        self.rand = random.Random(7)
        self.blocks = 0
        self.jobs = 0

    def unavailable(self):
        return None

    def cores(self):
        return self.ncores

    async def start(self, n):
        self.n = n
        return n

    def stop(self):
        self.n = 0

    def size(self):
        return self.n

    async def run(self, meta, ins, files, remove, use):
        from plab.builtins.elmat import RNG
        m = json.loads(meta)
        self.jobs += 1
        order = list(range(len(m['blocks'])))
        self.rand.shuffle(order)
        chunks = [None] * len(order)
        streams = {}                 # each worker keeps its own random numbers from block to block
        try:
            for i in order:
                w = 1 + i % use
                R.STATE['pool_index'] = w
                if w not in streams:
                    worker_api.pool_job(meta, ins, files, remove)
                else:
                    RNG.rs.set_state(streams[w])
                r = await worker_api.pool_chunk(m['job'], *m['blocks'][i])
                streams[w] = RNG.rs.get_state()
                if isinstance(r, str):
                    e = json.loads(r)
                    if e.get('interrupted'):
                        return {'interrupted': True, 'error': None, 'chunks': [], 'files': []}
                    return {'interrupted': False, 'error': e, 'chunks': [], 'files': []}
                chunks[i] = r
                self.blocks += 1
            files = worker_api.pool_written(m['job'])
        finally:
            R.STATE['pool_index'] = None
        return {'interrupted': False, 'error': None, 'chunks': chunks, 'files': files}


POOLB = InProcessPool()
POOL.set_backend(POOLB)


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return R.BASE, R.take_output()


def val(v):
    t = type(v)
    if t is float or t is bool or t is complex:
        return v
    if t is np.ndarray:
        if v.size == 1 and v.ndim == 2:
            return v.reshape(-1)[0].item()
        return v.tolist()
    if t is Char:
        return v.str() if v.a.shape[0] <= 1 else v.row_strs()
    if t is Str:
        return [s for s in v.a.reshape(-1, order='F')] if v.a.size != 1 else v.a.flat[0]
    if t is Cell:
        return [val(x) for x in v.a.reshape(-1, order='F')]
    if t is Struct:
        if v.size == 1:
            return {k: val(v.get1(k)) for k in v.f}
        return [{k: val(a.reshape(-1, order='F')[i]) for k, a in v.f.items()} for i in range(v.size)]
    return v


def same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12) or (math.isnan(a) and math.isnan(b))
    return a == b


def case(label, code, want=None, shows=(), hides=(), error=None, parallel=True, absent=()):
    """Run code; parallel says whether its parfor must have run on the pool."""
    blocks = POOLB.blocks
    try:
        W, out = run(code)
    except Exception as e:  # noqa: BLE001
        check(label, False, f'raised {type(e).__name__}: {e}')
        return None
    if error is not None:
        check(f'{label}: error', error in out, repr(out))
    elif 'Error' in out or 'Unrecognized' in out:
        check(f'{label}: no error', False, repr(out))
    for name, w in (want or {}).items():
        got = val(W[name]) if name in W else '(none)'
        check(f'{label}: {name}', same(got, w), f'got {got!r}, want {w!r}; output {out[-300:]!r}')
    for s in shows:
        check(f'{label}: shows {s[:60]!r}', s in out, repr(out))
    for s in hides:
        check(f'{label}: does not show {s[:60]!r}', s not in out, repr(out))
    for n in absent:
        check(f'{label}: no {n}', n not in W)
    if parallel is not None:
        check(f'{label}: {"on the pool" if parallel else "one pass at a time"}', (POOLB.blocks > blocks) == parallel,
              f'{POOLB.blocks - blocks} blocks ran on the pool; output {out[-300:]!r}')
    return W


# ---- the pool ----------------------------------------------------------------------------------
case('gcp nocreate before any pool', "p = gcp('nocreate'); e = isempty(p);", want={'e': True}, parallel=None)
case('parpool', 'p = parpool(3); n = p.NumWorkers;', want={'n': 3.0}, shows=['Starting a parallel pool of 3 workers', 'The pool has 3 workers.'],
     parallel=None)
case('a second parpool is refused', 'parpool(2)', error='A parallel pool is running already', parallel=None)
case('delete(gcp) stops it', "delete(gcp); p = gcp('nocreate'); e = isempty(p);", want={'e': True}, parallel=None)
case('the first parfor starts a pool', 'parfor k = 1:4, y(k) = k; end', want={'y': [[1, 2, 3, 4]]}, shows=['Starting a parallel pool of 3 workers'])
case('getCurrentTask: here none, on the workers their number', "t = getCurrentTask(); here = isempty(t); parfor k = 1:12, t = getCurrentTask(); w(k) = t.ID; end; n = numel(unique(w));",
     want={'here': True, 'n': 3.0})

# ---- sliced variables ----------------------------------------------------------------------------
case('a vector made by the loop', 'parfor k = 1:10, y(k) = k^2; end', want={'y': [[k * k for k in range(1, 11)]]})
case('a vector made before', 'y = zeros(1, 5); parfor k = 1:5, y(k) = 10 * k; end', want={'y': [[10, 20, 30, 40, 50]]})
case('columns of a matrix', 'A = zeros(2, 3); parfor k = 1:3, A(:, k) = [k; 2 * k]; end', want={'A': [[1, 2, 3], [2, 4, 6]]})
case('rows of a matrix made by the loop', 'parfor k = 1:3, A(k, :) = [k, k]; end', want={'A': [[1, 1], [2, 2], [3, 3]]})
case('a cell array', "parfor k = 1:3, c{k} = sprintf('n%d', k); end", want={'c': ['n1', 'n2', 'n3']})
case('read and written in its own slice', 'x = 1:6; parfor k = 1:6, x(k) = x(k) * 2; end', want={'x': [[2, 4, 6, 8, 10, 12]]})
case('a pass that sets no slice keeps the old value', 'y = [9 9 9 9]; parfor k = 1:4, if mod(k, 2) == 0, y(k) = k; end, end',
     want={'y': [[9, 2, 9, 4]]})
case('a slice in a fixed column', 'B = ones(3, 2); parfor k = 1:3, B(k, 2) = -k; end', want={'B': [[1, -1], [1, -2], [1, -3]]})
case('values that do not start at 1', 'y = zeros(1, 8); parfor k = 4:8, y(k) = k; end', want={'y': [[0, 0, 0, 4, 5, 6, 7, 8]]})

# ---- broadcast values ----------------------------------------------------------------------------
case('a number, an array, a struct and a cell', "a = 3; v = [10 20 30]; s.m = 2; c = {'x', 'yy', 'zzz'}; "
     'parfor k = 1:3, y(k) = a * v(k) * s.m + numel(c{k}); end', want={'y': [[61, 122, 183]]})
case('function handles: anonymous, named, captured', "f = @(x) x.^2 + 1; g = @sqrt; b = 5; h = @(x) x + b; "
     'parfor k = 1:3, y(k) = f(k) + g(k^2) + h(k); end', want={'y': [[9, 14, 21]]})
case('an anonymous function made in the pass', 'parfor k = 1:3, f = @(x) x * k; y(k) = f(2); end', want={'y': [[2, 4, 6]]})
case('a string array and containers.Map', "names = [\"a\", \"bb\"]; m = containers.Map({'a', 'bb'}, {1, 2}); "
     'parfor k = 1:2, y(k) = m(char(names(k))) * strlength(names(k)); end', want={'y': [[1, 4]]})

# ---- reductions ----------------------------------------------------------------------------------
case('a sum', 's = 0; parfor k = 1:100, s = s + k; end', want={'s': 5050.0})
case('a sum with the operand first', 's = 0; parfor k = 1:10, s = k + s; end', want={'s': 55.0})
case('a difference', 's = 100; parfor k = 1:10, s = s - k; end', want={'s': 45.0})
case('a product', 'p = 1; parfor k = 1:10, p = p * k; end', want={'p': 3628800.0})
case('a matrix product keeps its order', 'M = eye(2); parfor k = 1:6, M = M * [1 k; 0 1]; end', want={'M': [[1, 21], [0, 1]]})
case('a matrix product from the left', 'M = eye(2); parfor k = 1:4, M = [1 0; k 1] * M; end', want={'M': [[1, 0], [10, 1]]})
case('and, or', 'a = true; o = false; parfor k = 1:5, a = a & k > 0; o = o | k == 3; end', want={'a': True, 'o': True})
case('a row in order', 'r = []; parfor k = 1:7, r = [r, k]; end', want={'r': [[1, 2, 3, 4, 5, 6, 7]]})
case('a row backwards', 'r = []; parfor k = 1:5, r = [k, r]; end', want={'r': [[5, 4, 3, 2, 1]]})
case('a column in order', 'c = zeros(0, 1); parfor k = 1:4, c = [c; k * 10]; end', want={'c': [[10], [20], [30], [40]]})
case('min and max', 'lo = Inf; hi = -Inf; parfor k = 1:9, lo = min(lo, mod(k * 7, 11)); hi = max(mod(k * 7, 11), hi); end',
     want={'lo': 1.0, 'hi': 10.0})
case('a reduction in an if', 's = 0; parfor k = 1:10, if mod(k, 3) == 0, s = s + k; end, end', want={'s': 18.0})
case('several at once', 's = 0; n = 0; parfor k = 1:20, s = s + k^2; n = n + 1; y(k) = k; end', want={'s': 2870.0, 'n': 20.0})

# ---- temporaries and inner loops ------------------------------------------------------------------
case('a temporary', 'parfor k = 1:4, t = k * 3; y(k) = t + 1; end', want={'y': [[4, 7, 10, 13]]})
case('set in both branches', 'parfor k = 1:4, if k > 2, t = 1; else, t = 2; end, y(k) = t; end', want={'y': [[2, 2, 1, 1]]})
case('an inner loop', 'parfor k = 1:3, acc = 0; for j = 1:k, acc = acc + j; end, y(k) = acc; end', want={'y': [[1, 3, 6]]})
case('an inner parfor runs on the worker', 'parfor k = 1:3, z = zeros(1, 2); parfor j = 1:2, z(j) = k * j; end, y(k) = sum(z); end',
     want={'y': [[3, 6, 9]]})
case('continue', 'y = zeros(1, 5); parfor k = 1:5, if k == 3, continue, end, y(k) = k; end', want={'y': [[1, 2, 0, 4, 5]]})
case('the loop variable afterwards', 'parfor k = 1:5, y(k) = k; end', want={'k': 5.0})

# ---- functions on the path and local functions -----------------------------------------------------
with open(os.path.join(TMP, 'pfhelper.m'), 'w') as f:
    f.write('function y = pfhelper(x)\ny = 2 * x + local1(x);\nend\nfunction z = local1(x)\nz = x / 2;\nend\n')
with open(os.path.join(TMP, 'pffun.m'), 'w') as f:
    f.write('function y = pffun(n)\nparfor k = 1:n\n  y(k) = sq(k) + pfhelper(k);\nend\nend\nfunction s = sq(x)\ns = x * x;\nend\n')
with open(os.path.join(TMP, 'pfscript.m'), 'w') as f:
    f.write('total = 0;\nparfor k = 1:4\n  total = total + twice(k);\nend\nfunction t = twice(x)\nt = 2 * x;\nend\n')
R.bump_epoch()
case('a function file: local functions and a file on the path', 'y = pffun(4);', want={'y': [[3.5, 9, 16.5, 26]]})
case('a script with a local function', 'pfscript', want={'total': 20.0})

# ---- what the passes print, errors, files ------------------------------------------------------------
case('output of the passes', "parfor k = 1:3, fprintf('pass %d\\n', k); end", shows=['pass 1\n', 'pass 2\n', 'pass 3\n'])
W = case('an error in a pass', "parfor k = 1:6, if k == 4, error('my:id', 'boom %d', k); end, y(k) = k; end",
         error='boom 4')
case('the error is caught by try', "try, parfor k = 1:3, error('my:id', 'boom'); end, catch e, id = e.identifier; m = e.message; end",
     want={'id': 'my:id', 'm': 'boom'}, parallel=None)
case('random numbers differ from pass to pass', 'parfor k = 1:8, r(k) = rand; end; n = numel(unique(r));', want={'n': 8.0})
case('files the passes write', "parfor k = 1:3, fid = fopen(sprintf('pf%d.txt', k), 'w'); fprintf(fid, '%d', k * 7); fclose(fid); end; "
     "t = fileread('pf3.txt');", want={'t': '21'})

# ---- one pass at a time, and why ---------------------------------------------------------------------
case('a pass that reads the one before', 'x = 1:5; parfor k = 2:5, x(k) = x(k - 1) + 1; end',
     want={'x': [[1, 2, 3, 4, 5]]}, shows=['Warning: The parfor loop at line 1 runs one pass at a time: x is used in a pass before the pass sets it'],
     parallel=False)
case('a value carried from pass to pass', 't = 0; parfor k = 1:3, y(k) = t; t = k; end', want={'y': [[0, 1, 2]]},
     shows=['runs one pass at a time: t is used in a pass before the pass sets it'], parallel=False)
case('break', 'parfor k = 1:5, if k == 3, break, end, y(k) = k; end', want={'y': [[1, 2]]},
     shows=['runs one pass at a time: it has break'], parallel=False)
case('eval', "parfor k = 1:2, eval('q = k;'); end", shows=['runs one pass at a time: it calls eval'], parallel=False)
case('load without an output', "TMP_X = 1; save('pfv.mat', 'TMP_X'); parfor k = 1:2, load pfv.mat; end",
     shows=['runs one pass at a time: it calls load without an output'], parallel=False)
W, out = run('for r = 1:3, parfor k = 1:2, if k == 2, break, end, end, end')
check('the note is said once', out.count('it has break') == 1, repr(out))
W = case('values that do not go up by one', 'parfor k = [3 1 2], y(k) = k; end', want={'y': [[1, 2, 3]]},
         shows=['runs one pass at a time: its values are not whole numbers going up by one'], parallel=False)
case('no workers: parfor (k = 1:n, 0)', 'parfor (k = 1:4, 0), y(k) = k; end', want={'y': [[1, 2, 3, 4]]}, hides=['Warning'], parallel=False)
case('at most two workers', "parfor (k = 1:8, 2), t = getCurrentTask(); w(k) = t.ID; end; n = max(w);", want={'n': 2.0})
run("TMP_Q = 4; save('pfq.mat', 'TMP_Q');")
case('a variable made by load before the loop goes as broadcast', "load pfq.mat; parfor k = 1:2, y(k) = TMP_Q * k; end",
     want={'y': [[4, 8]]}, hides=['Warning'])
with open(os.path.join(TMP, 'pfload.m'), 'w') as f:
    f.write("load pfq.mat\nparfor k = 1:3\n  z(k) = TMP_Q + k;\nend\n")
R.bump_epoch()
case('and in a script', 'pfload', want={'z': [[5, 6, 7]]}, hides=['Warning'])
case('a graphics handle cannot go', 'h = figure; parfor k = 1:2, y(k) = h.Number + k; end; close all;',
     shows=['runs one pass at a time: a value cannot be sent to the workers'], parallel=False)
case('an empty loop', 'y = 5; parfor k = 1:0, y = 7; end', want={'y': 5.0}, parallel=False)

shutil.rmtree(TMP, ignore_errors=True)
print(f'\n{checks[0] - len(failed)} of {checks[0]} checks passed')
sys.exit(1 if failed else 0)
