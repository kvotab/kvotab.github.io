"""Every built-in called with inputs it may not take (none, too few, text,
a number, matrices, logical values, sparse matrices) ends in the
language's error, never in a Python exception. And the built-ins listed in
builtins/arity.py refuse a call with fewer inputs than their shortest form
with "Not enough input arguments."

    python3 test_inputs.py          (from any folder)

Functions that wait for a person, touch the file system outside a scratch
folder, or start the pool are left out.
"""
import asyncio
import inspect
import os
import signal
import sys
import tempfile
import traceback

import numpy as np
import scipy.sparse as sps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import sparsemat as SPM  # noqa: E402
from plab.values import MError, Char  # noqa: E402
from plab.builtins.arity import MIN_INPUTS  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-inputs-')
os.chdir(TMP)
R.STATE['cwd'] = TMP

SKIP = set('''input keyboard pause uiwait waitfor ginput inputdlg questdlg listdlg menu uigetfile uiputfile uigetdir uisetcolor
beep sound soundsc exit quit dbstop dbcont dbquit drawnow parpool delete rmdir mkdir movefile copyfile cd diary system unix
dos web webread webwrite websave sendmail ftp clc clear clearvars close shg print exportgraphics saveas savefig edit open
run load save tic toc timer start stop wait uiconfirm uialert rng perms nchoosek primes magic factorial appdesigner doc
help helpwin return gtext spinmap'''.split())

M = np.array([[2.0, 0, 1], [0, 0, 3], [4, 0, 0]])
V = np.array([[1.0, 0, 2]])
L = np.array([[True, False], [False, True]])
S = SPM.make(sps.csc_matrix(M))
SL = SPM.make(sps.csc_matrix(L), logical=True)
INPUTS = [(), (M,), (V,), (L,), (M, M), (M, 1.0), (1.0, M), (V, V), (M, 2.0, 1.0), (Char.of('abc'),), (2.5,),
          (S,), (SL,), (S, S), (S, 1.0), (1.0, S), (S, 2.0, 1.0)]


class Timeout(Exception):
    pass


def _alarm(*_):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def call(info, args):
    """None when the call ends in the language's error (or returns), else the
    Python exception."""
    try:
        signal.alarm(5)
        r = info.fn(*(((R.BASE,) if info.ws else ()) + (1,) + args))
        if inspect.isawaitable(r):
            asyncio.run(r)
        return None
    except (MError, Timeout):
        return None
    except Exception as e:  # noqa: BLE001 -- what the test is looking for
        return e
    finally:
        signal.alarm(0)
        R.take_output()


failed = []
calls = 0
for name in sorted(R.BUILTINS):
    if name in SKIP or name.startswith('ui') or name.startswith('plab'):
        continue
    info = R.BUILTINS[name]
    for args in INPUTS:
        calls += 1
        e = call(info, args)
        if e is not None:
            tb = [f for f in traceback.extract_tb(e.__traceback__) if '/plab/' in f.filename]
            where = f'{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}' if tb else '?'
            failed.append(f"{name}({', '.join(type(a).__name__ for a in args)}): {type(e).__name__}: {str(e)[:90]} at {where}")

checks = calls
for name, k in sorted(MIN_INPUTS.items()):
    info = R.BUILTINS.get(name)
    if info is None:
        failed.append(f'{name}: listed in arity.py but not a builtin')
        continue
    checks += 1
    try:
        r = info.fn(*(((R.BASE,) if info.ws else ()) + (1,) + (M,) * (k - 1)))
        if inspect.isawaitable(r):
            asyncio.run(r)
        failed.append(f'{name}: {k - 1} inputs did not give an error')
    except MError as e:
        if e.identifier != 'MATLAB:minrhs':
            failed.append(f'{name}: {k - 1} inputs gave {e.identifier}, not MATLAB:minrhs')
    finally:
        R.take_output()

for f in failed:
    print('FAIL ', f)
print(f'\n{checks - len(failed)} of {checks} checks passed')
sys.exit(1 if failed else 0)
