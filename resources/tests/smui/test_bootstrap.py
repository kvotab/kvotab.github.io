#!/usr/bin/env python3
"""Bootstrap's backend (resources/py/smui/bootstrap.py): the percentile and
BCa limits against scipy.stats.bootstrap given the same resamples (with
scipy's linear quantiles), the bias-corrected limits as BCa with no
acceleration, Efron's acceleration by hand, the report of a Bootstrap
Results table through registry.dispatch (JMP's quantiles), the edge cases,
and the Python shown under the report run on a CSV export.

    python3 resources/tests/smui/test_bootstrap.py
"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from scipy import stats

from backend import FAILED, Checks, call, table

check = Checks()
check('bootstrap.py imports', 'bootstrap' in FAILED, False)
from smui import bootstrap as bs  # noqa: E402

rng = np.random.default_rng(20260927)
x = rng.lognormal(0.0, 0.8, 40)          # skewed: BCa differs from the percentile limits
B = 999


def resampled(stat, seed):
    """scipy.stats.bootstrap's resamples (one batch: rng.integers(0, n, (B, n)))."""
    idx = np.random.default_rng(seed).integers(0, len(x), (B, len(x)))
    return stat(x[idx], axis=-1)


def jack(stat):
    return np.array([stat(np.delete(x, i)) for i in range(len(x))])


for name, stat in [('mean', np.mean), ('standard deviation', lambda a, axis=None: np.std(a, ddof=1, axis=axis)), ('log of the mean', lambda a, axis=None: np.log(np.mean(a, axis=axis)))]:
    for c in (0.90, 0.95):
        th = resampled(stat, 11)
        mine = bs.intervals(stat(x), th, jack(stat), coverage=[c], quantile='linear')['limits'][0]
        ref = stats.bootstrap((x,), stat, n_resamples=B, confidence_level=c, method='BCa', rng=np.random.default_rng(11), vectorized=True).confidence_interval
        check.near(f'{name}, {c:.0%}: BCa lower as scipy.stats.bootstrap', mine['bca_lower'], float(ref.low), 1e-10)
        check.near(f'{name}, {c:.0%}: BCa upper as scipy.stats.bootstrap', mine['bca_upper'], float(ref.high), 1e-10)
        ref = stats.bootstrap((x,), stat, n_resamples=B, confidence_level=c, method='percentile', rng=np.random.default_rng(11), vectorized=True).confidence_interval
        check.near(f'{name}, {c:.0%}: percentile lower as scipy', mine['pct_lower'], float(ref.low), 1e-10)
        check.near(f'{name}, {c:.0%}: percentile upper as scipy', mine['pct_upper'], float(ref.high), 1e-10)
        res = stats.bootstrap((x,), stat, n_resamples=B, confidence_level=c, method='BCa', rng=np.random.default_rng(11), vectorized=True)
    check.near(f'{name}: the bootstrap standard error as scipy\'s', bs.intervals(stat(x), th)['std_error'], float(res.standard_error), 1e-10)

# the bias-corrected limits are BCa with no acceleration
th = resampled(np.mean, 5)
t0 = float(np.mean(x))
r = bs.intervals(t0, th, coverage=[0.9, 0.95])
p0 = (np.sum(th < t0) + 0.5 * np.sum(th == t0)) / B
z0 = stats.norm.ppf(p0)
for L in r['limits']:
    al = (1 - L['coverage']) / 2
    want = np.quantile(th, stats.norm.cdf(2 * z0 + stats.norm.ppf([al, 1 - al])), method='weibull')
    check.near(f'BC {L["coverage"]:.0%} lower by hand (JMP quantiles)', L['bc_lower'], float(want[0]), 1e-12)
    check.near(f'BC {L["coverage"]:.0%} upper by hand', L['bc_upper'], float(want[1]), 1e-12)
    pw = np.quantile(th, [al, 1 - al], method='weibull')
    check(f'percentile {L["coverage"]:.0%} with JMP\'s (n + 1)p quantiles', (L['pct_lower'], L['pct_upper']), (float(pw[0]), float(pw[1])))
    check(f'no BCa without the jackknife', 'bca_lower' in L, False)
flat = bs.intervals(t0, th, np.full(10, 2.0), coverage=[0.95])['limits'][0]
check.near('a flat jackknife: no acceleration, so BCa = BC', flat['bca_lower'], r['limits'][1]['bc_lower'], 1e-12)
jk = jack(np.mean)
d = jk.mean() - jk
check.near('Efron\'s acceleration by hand', bs.acceleration(jk), float(np.sum(d ** 3) / (6 * np.sum(d ** 2) ** 1.5)), 1e-12)
check.near('the summary: mean, bias', (r['mean'], r['bias'])[1], float(th.mean() - t0), 1e-12)

# edge cases
one = bs.intervals(1.0, [2.0, None, float('nan')])
check('fewer than two values: an error, the missing counted', ('error' in one, one['n_missing']), (True, 2))
out = bs.intervals(100.0, th, coverage=[0.95])
check('an original beyond every sample: no bias correction', ('bc_lower' in out['limits'][0], out['z0']), (False, None))

# ---- the report of a Bootstrap Results table ------------------------------------------------------
vals = {'BootID': [0.0] + [float(i) for i in range(1, B + 1)], 'Mean': [t0] + th.tolist(),
        'Std Dev': [float(np.std(x, ddof=1))] + resampled(lambda a, axis=None: np.std(a, ddof=1, axis=axis), 5).tolist()}
vals['Std Dev'][7] = None
T = table(vals)
jkd = {'Mean': jk.tolist()}
rep = call('bootstrap.report', table=T, columns=['Mean', 'Std Dev'], jackknife=jkd, table_name='boot')
s = {r['column']: r for r in rep['stats']}
check('a statistic per column', list(s), ['Mean', 'Std Dev'])
want = bs.intervals(t0, th, jk)
check('the report\'s limits are intervals() of BootID > 0 against BootID 0', s['Mean']['limits'], json.loads(json.dumps(want['limits'])))
check('the rows of the samples, for linking', s['Mean']['rows'][:3], [1, 2, 3])
check('a missing sample is counted and left out', (s['Std Dev']['n_samples'], s['Std Dev']['n_missing']), (B - 1, 1))
check('BCa only where the jackknife is', ('bca_lower' in s['Mean']['limits'][0], 'bca_lower' in s['Std Dev']['limits'][0]), (True, False))

with tempfile.TemporaryDirectory() as tmp:
    pd.DataFrame(vals).to_csv(os.path.join(tmp, 'boot.csv'), index=False)
    with open(os.path.join(tmp, 'code.py'), 'w') as fh:
        fh.write(rep['code'])
    run = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=120)
    if run.returncode:
        print(run.stderr[-1500:])
    lines = [ln for ln in run.stdout.strip().splitlines() if ln.strip()]
    check('the shown code runs', run.returncode == 0 and len(lines) >= 5, True)
    if run.returncode == 0:
        nums = [np.array(ln.replace('[', ' ').replace(']', ' ').split(), dtype=float) for ln in lines]
        M = s['Mean']
        check.near('the code\'s standard error', float(nums[0][1]), M['std_error'], 1e-12)
        check('the code\'s percentile limits (90, 95, 99%)', np.allclose(nums[1], [M['limits'][k]['pct_lower'] for k in range(3)] + [M['limits'][k]['pct_upper'] for k in range(3)]), True)
        check('the code\'s bias-corrected limits', np.allclose(nums[2], [M['limits'][k]['bc_lower'] for k in range(3)] + [M['limits'][k]['bc_upper'] for k in range(3)]), True)
        check('the code\'s BCa limits', np.allclose(np.r_[nums[3], nums[4]], [M['limits'][k]['bca_lower'] for k in range(3)] + [M['limits'][k]['bca_upper'] for k in range(3)]), True)

# ---- rows the report leaves out (excluded, or filtered out): the code leaves them out too -------------
kept = [i for i in range(B + 1) if i not in (3, 17, 250, 251)]
rep2 = call('bootstrap.report', table=T, columns=['Mean'], rows=kept, table_name='boot')
M2 = rep2['stats'][0]
check('rows left out: fewer samples in the report', M2['n_samples'], B - 4)
check('... and the code drops them', 'df = df.drop(index=[3, 17, 250, 251])   # the rows the report leaves out' in rep2['code'], True)
with tempfile.TemporaryDirectory() as tmp:
    pd.DataFrame(vals).to_csv(os.path.join(tmp, 'boot.csv'), index=False)
    with open(os.path.join(tmp, 'code.py'), 'w') as fh:
        fh.write(rep2['code'])
    run = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=120)
    lines = [ln for ln in run.stdout.strip().splitlines() if ln.strip()]
    ok = run.returncode == 0 and len(lines) >= 2
    check('the code on the whole table\'s CSV runs', ok, True)
    if ok:
        nums = [np.array(ln.replace('[', ' ').replace(']', ' ').split(), dtype=float) for ln in lines]
        check.near('... and gives the report\'s mean, standard error and bias on its rows', float(np.max(np.abs(nums[0] - [M2['mean'], M2['std_error'], M2['bias']]))), 0.0, abs_=1e-12)
        check('... and its percentile limits (as numpy prints them)', np.allclose(nums[1], [M2['limits'][k]['pct_lower'] for k in range(3)] + [M2['limits'][k]['pct_upper'] for k in range(3)]), True)

sys.exit(check.done())
