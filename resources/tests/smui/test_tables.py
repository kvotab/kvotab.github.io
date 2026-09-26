#!/usr/bin/env python3
"""The backend of the Tables menu, Tabulate, the Columns Viewer, Explore
Missing Values and the Python Script window (resources/py/smui/tables.py),
checked against pandas and numpy called directly: group statistics and
JMP's quantiles (numpy's method='weibull') by group, in the page's level
order with missing groups last; Freq and Weight; stack, split and transpose
against melt, pivot and .T; joins against DataFrame.merge; update; missing
value patterns; the EM estimate of a multivariate normal against its closed
form for a monotone pattern; Tabulate against groupby; the script runner.

    python3 resources/tests/smui/test_tables.py
"""
import math
import sys

import numpy as np
import pandas as pd
from statsmodels.stats.weightstats import DescrStatsW

from backend import Checks, call, table

check = Checks()
rng = np.random.default_rng(20260926)
N = 300


def arr(v):
    return np.array([np.nan if x is None else x for x in v], dtype=float)


def close(label, got, want, rel=1e-9):
    got, want = arr(got), arr(want)
    ok = got.shape == want.shape and np.all((np.isnan(got) & np.isnan(want)) | (np.abs(got - want) <= rel * np.maximum(1, np.abs(want))))
    check(label, bool(ok), True)
    if not ok:
        print('   got ', got[:8], '\n   want', want[:8])


# ---- the data: groups in a value order of their own, missing values everywhere
g1 = rng.choice(['a', 'b', 'c'], N).astype(object)
g1[rng.random(N) < 0.06] = None
g2 = rng.choice([1.0, 2.0, 3.0], N)
x = rng.normal(50, 8, N)
x[rng.random(N) < 0.1] = np.nan
y = rng.exponential(3, N) + 0.1
f = rng.integers(0, 4, N).astype(float)
w = rng.uniform(0.5, 2.0, N)
s = rng.choice(['p', 'q', 'r', 's'], N).astype(object)
s[rng.random(N) < 0.08] = None
tid = table({'g1': list(g1), 'g2': g2, 'x': x, 'y': y, 'f': f, 'w': w, 's': list(s)},
            types={'g2': 'nominal'}, levels={'g1': ['c', 'a', 'b'], 'g2': [3.0, 1.0, 2.0]})
df = pd.DataFrame({'g1': g1, 'g2': g2, 'x': x, 'y': y, 'f': f, 'w': w, 's': s})

# ---- Tables > Summary --------------------------------------------------------------
ALL = ['N', 'Mean', 'Std Dev', 'Min', 'Max', 'Range', 'Sum', 'Median', 'Quantiles', 'N Missing', 'N Categories', '% of Total', 'CV', 'Std Err', 'Variance', 'Geometric Mean', 'Interquartile Range', 'Mode']
r = call('tables.summary', table=tid, group=['g1', 'g2'], columns=['x', 'y', 's'], stats=ALL, quantiles=[10, 25, 50, 90])
cols = {c['name']: c for c in r['columns']}
# the groups, in the page's order: g1 c, a, b then missing; g2 3, 1, 2
order = []
for a in ['c', 'a', 'b', None]:
    for b in [3.0, 1.0, 2.0]:
        m = ((df.g1 == a) if a is not None else df.g1.isna()) & (df.g2 == b)
        if m.any():
            order.append((a, b, m.to_numpy()))
check('summary groups in value order, missing last', [(c, b) for c, b in zip(cols['g1']['values'], cols['g2']['values'])], [(a, b) for a, b, _ in order])
check('N Rows', cols['N Rows']['values'], [float(m.sum()) for _, _, m in order])


def per_group(fn, v):
    return [fn(v[m]) for _, _, m in order]


def fin(v):
    return v[~np.isnan(v)]


def weib(p):
    return lambda v: float(np.quantile(fin(v), p, method='weibull')) if len(fin(v)) else np.nan


for name, fn in [('N(x)', lambda v: float(len(fin(v)))), ('Mean(x)', lambda v: np.mean(fin(v))), ('Std Dev(x)', lambda v: np.std(fin(v), ddof=1) if len(fin(v)) > 1 else np.nan),
                 ('Min(x)', lambda v: np.min(fin(v))), ('Max(x)', lambda v: np.max(fin(v))), ('Range(x)', lambda v: np.ptp(fin(v))), ('Sum(x)', lambda v: np.sum(fin(v))),
                 ('Median(x)', lambda v: np.median(fin(v))), ('N Missing(x)', lambda v: float(np.isnan(v).sum())), ('N Categories(x)', lambda v: float(len(np.unique(fin(v))))),
                 ('CV(x)', lambda v: 100 * np.std(fin(v), ddof=1) / np.mean(fin(v))), ('Std Err(x)', lambda v: np.std(fin(v), ddof=1) / math.sqrt(len(fin(v)))),
                 ('Variance(x)', lambda v: np.var(fin(v), ddof=1)), ('Interquartile Range(x)', lambda v: weib(0.75)(v) - weib(0.25)(v))]:
    close(f'summary {name} by group, against numpy', cols[name]['values'], per_group(fn, x))
for p in [10, 25, 50, 90]:
    close(f'summary Quantiles{p}(x) is numpy\'s weibull by group', cols[f'Quantiles{p}(x)']['values'], per_group(weib(p / 100), x))
close('summary Geometric Mean(y)', cols['Geometric Mean(y)']['values'], per_group(lambda v: math.exp(np.mean(np.log(v))), y))
tot = np.nansum(x)
close('summary % of Total(x): the group\'s share of the sum', cols['% of Total(x)']['values'], per_group(lambda v: 100 * np.nansum(v) / tot, x))


def mode_of(v):
    vals, cnt = np.unique(fin(v), return_counts=True)
    return vals[np.argmax(cnt)]


close('summary Mode(y)', cols['Mode(y)']['values'], per_group(mode_of, y))
check('a character column gets N, N Missing, N Categories, % of Total and Mode only', sorted(k for k in cols if k.endswith('(s)')), sorted(['N(s)', 'N Missing(s)', 'N Categories(s)', '% of Total(s)', 'Mode(s)']))
sv = pd.Series(s)
close('summary N(s)', cols['N(s)']['values'], [float(sv[m].notna().sum()) for _, _, m in order])
close('summary N Categories(s)', cols['N Categories(s)']['values'], [float(sv[m].nunique()) for _, _, m in order])
check('summary Mode(s): the commonest, the first in order of equals', cols['Mode(s)']['values'], [sorted(vc[vc == vc.max()].index)[0] if len(vc := sv[m].value_counts()) else None for _, _, m in order])

# the same against pandas groupby, with pandas' own sort of the group keys
g = df.groupby(['g1', 'g2'], dropna=False, sort=False)
pmean = {k: v for k, v in g['x'].mean().items()}
got = {(a, b): v for a, b, v in zip(cols['g1']['values'], cols['g2']['values'], cols['Mean(x)']['values'])}
key = lambda k: (k[0] if isinstance(k[0], str) else None, float(k[1]))  # noqa: E731
check('summary means equal pandas groupby(dropna=False).mean()', all(abs(got[key(k)] - v) < 1e-9 for k, v in pmean.items() if not np.isnan(v)), True)

# Freq: rows repeated; Weight: DescrStatsW
rf = call('tables.summary', table=tid, group=['g1'], columns=['x'], stats=['N', 'Mean', 'Std Dev', 'Median', 'Quantiles'], quantiles=[25], freq='f')
cf = {c['name']: c for c in rf['columns']}
ok = f > 0
grp = [(a, ((df.g1 == a) if a is not None else df.g1.isna()).to_numpy() & ok) for a in ['c', 'a', 'b', None]]
rep = lambda m: np.repeat(x[m & ~np.isnan(x)], f[m & ~np.isnan(x)].astype(int))  # noqa: E731
close('Freq: N is the sum of frequencies', cf['N(x)']['values'], [float(f[m & ~np.isnan(x)].sum()) for _, m in grp])
close('Freq: the mean of the repeated values', cf['Mean(x)']['values'], [np.mean(rep(m)) for _, m in grp])
close('Freq: the std dev of the repeated values', cf['Std Dev(x)']['values'], [np.std(rep(m), ddof=1) for _, m in grp])
close('Freq: the weibull quantile of the repeated values', cf['Quantiles25(x)']['values'], [np.quantile(rep(m), 0.25, method='weibull') for _, m in grp])
check('Freq: N Rows leaves out the rows with a zero frequency', cf['N Rows']['values'], [float(m.sum()) for _, m in grp])
rw = call('tables.summary', table=tid, group=['g1'], columns=['x'], stats=['Mean', 'Std Dev', 'Std Err', 'Sum'], weight='w')
cw = {c['name']: c for c in rw['columns']}
gw = [((df.g1 == a) if a is not None else df.g1.isna()).to_numpy() & ~np.isnan(x) for a in ['c', 'a', 'b', None]]
close('Weight: the weighted mean (DescrStatsW)', cw['Mean(x)']['values'], [DescrStatsW(x[m], weights=w[m]).mean for m in gw])
close('Weight: the std dev, as DescrStatsW(ddof=1)', cw['Std Dev(x)']['values'], [DescrStatsW(x[m], weights=w[m], ddof=1).std for m in gw])
close('Weight: the std err, as DescrStatsW(ddof=1)', cw['Std Err(x)']['values'], [DescrStatsW(x[m], weights=w[m], ddof=1).std_mean for m in gw])
close('Weight: the weighted sum', cw['Sum(x)']['values'], [np.sum(w[m] * x[m]) for m in gw])
# Subgroup and the names
rs = call('tables.summary', table=tid, group=['g1'], subgroup=['g2'], columns=['x'], stats=['Mean'], name_format='stat(column)')
check('Subgroup columns side by side, in the subgroup\'s order', [c['name'] for c in rs['columns']], ['g1', 'N Rows', 'Mean(x, 3)', 'Mean(x, 1)', 'Mean(x, 2)'])
close('Subgroup means', [v for v in rs['columns'][3]['values']], [np.nanmean(x[((df.g1 == a) if a is not None else df.g1.isna()).to_numpy() & (g2 == 1.0)]) for a in ['c', 'a', 'b', None]])
for fmt, want in [('column', 'x'), ('stat of column', 'Mean of x'), ('column stat', 'x Mean')]:
    check(f'statistics column names: {fmt}', call('tables.summary', table=tid, group=['g1'], columns=['x'], stats=['Mean'], name_format=fmt)['columns'][2]['name'], want)
r0 = call('tables.summary', table=tid, columns=['x'], stats=['Mean', 'N'])
check('without Group: one row of every row', (r0['nrows'], r0['columns'][0]['values']), (1, [float(N)]))
close('without Group: the mean of the column', r0['columns'][1]['values'], [np.nanmean(x)])
rr = call('tables.summary', table=tid, group=['g1'], columns=['x'], stats=['N'], rows=list(range(0, N, 2)))
close('rows: only the rows asked for', rr['columns'][2]['values'], [float(np.sum(((df.g1 == a) if a is not None else df.g1.isna()).to_numpy()[::2] & ~np.isnan(x[::2]))) for a in ['c', 'a', 'b', None]])
check('the summary has its Python code', 'groupby' in r['code'] and 'weibull' in r['code'], True)

# ---- Tables > Stack -------------------------------------------------------------------
ts = table({'id': [1.0, 2.0, 3.0], 'a': [1.0, None, 3.0], 'b': [4.0, 5.0, 6.0], 't': ['x', 'y', None]})
st = call('tables.stack', table=ts, columns=['a', 'b'], keep=['id'], data_name='Data', label_name='Label')
long = pd.DataFrame({'id': [1.0, 2.0, 3.0], 'a': [1.0, np.nan, 3.0], 'b': [4.0, 5.0, 6.0]}).melt(id_vars=['id'], value_vars=['a', 'b'], var_name='Label', value_name='Data', ignore_index=False).sort_index(kind='stable')
cst = {c['name']: c for c in st['columns']}
check('stack by row: as melt, row by row', (cst['id']['values'], cst['Label']['values']), (long['id'].tolist(), long['Label'].tolist()))
close('stack by row: the values', cst['Data']['values'], long['Data'].tolist())
st2 = call('tables.stack', table=ts, columns=['a', 'b'], by_row=False, drop_missing=True, id_name='ID')
long2 = pd.DataFrame({'a': [1.0, np.nan, 3.0], 'b': [4.0, 5.0, 6.0]}).melt(value_vars=['a', 'b'], var_name='Label', value_name='Data').dropna()
c2 = {c['name']: c for c in st2['columns']}
close('stack by column, missing rows out: as melt().dropna()', c2['Data']['values'], long2['Data'].tolist())
check('the ID column numbers the source rows', c2['ID']['values'], [1.0, 3.0, 1.0, 2.0, 3.0])
check('stacked columns of numbers and text give text', {c['name']: c['dataType'] for c in call('tables.stack', table=ts, columns=['b', 't'])['columns']}['Data'], 'character')
check('the Label column keeps the stacked columns\' order', st['columns'][1].get('levels'), ['a', 'b'])

# ---- Tables > Split -------------------------------------------------------------------
tsp = table({'subject': ['s1', 's1', 's2', 's2', 's3'], 'time': ['t2', 't1', 't1', 't2', 't1'], 'v': [2.0, 1.0, 3.0, 4.0, 5.0]}, levels={'time': ['t1', 't2']})
sp = call('tables.split', table=tsp, split_by='time', columns=['v'], group=['subject'])
wide = pd.DataFrame({'subject': ['s1', 's1', 's2', 's2', 's3'], 'time': ['t2', 't1', 't1', 't2', 't1'], 'v': [2.0, 1.0, 3.0, 4.0, 5.0]}).pivot(index='subject', columns='time', values='v')
csp = {c['name']: c for c in sp['columns']}
check('split: a row per group', csp['subject']['values'], wide.index.tolist())
close('split t1 as pivot', csp['t1']['values'], wide['t1'].tolist())
close('split t2 as pivot', csp['t2']['values'], wide['t2'].tolist())
sp2 = call('tables.split', table=tsp, split_by='time', columns=['v'])
close('split without Group: matched by order of appearance', {c['name']: c for c in sp2['columns']}['t1']['values'], [1.0, 3.0, 5.0])
tdup = table({'g': ['a', 'a', 'a'], 'k': ['u', 'u', 'v'], 'v': [1.0, 2.0, 3.0]})
sd = call('tables.split', table=tdup, split_by='k', columns=['v'], group=['g'])
check('a level repeated in a group starts another row', ({c['name']: c['values'] for c in sd['columns']}['u'], {c['name']: c['values'] for c in sd['columns']}['v']), ([1.0, 2.0], [3.0, None]))

# ---- Tables > Transpose -----------------------------------------------------------------
tt = table({'name': ['r1', 'r2', 'r3'], 'a': [1.0, 2.0, 3.0], 'b': [4.0, 5.0, None]})
tr = call('tables.transpose', table=tt, columns=['a', 'b'], label='name')
T = pd.DataFrame({'a': [1.0, 2.0, 3.0], 'b': [4.0, 5.0, np.nan]}, index=['r1', 'r2', 'r3']).T
ctr = {c['name']: c for c in tr['columns']}
check('transpose: the Label column holds the column names', ctr['Label']['values'], ['a', 'b'])
for k in ['r1', 'r2', 'r3']:
    close(f'transpose column {k} as DataFrame.T', ctr[k]['values'], T[k].tolist())
tr2 = call('tables.transpose', table=tt, columns=['a'])
check('transpose without a Label column: Row 1, Row 2, …', [c['name'] for c in tr2['columns']], ['Label', 'Row 1', 'Row 2', 'Row 3'])

# ---- Tables > Join ---------------------------------------------------------------------------
LK, RK = ['a', 'b', 'b', 'c', None, 'e'], ['b', 'c', 'c', 'd', None]
L = pd.DataFrame({'k': pd.Series(LK, dtype=object), 'lv': [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
R = pd.DataFrame({'k': pd.Series(RK, dtype=object), 'rv': [10.0, 20.0, 30.0, 40.0, 50.0]})
tl = table({'k': LK, 'lv': L.lv.tolist()})    # from the lists: pandas 3 would make None a NaN
tr_ = table({'k': RK, 'rv': R.rv.tolist()})


def pairs_of(res):
    c = {x['name']: x['values'] for x in res['columns']}
    return sorted(((a if a is not None else -1), (b if b is not None else -1)) for a, b in zip(c['lv'], c['rv']))


Lk, Rk = L.dropna(subset=['k']), R.dropna(subset=['k'])   # a missing key matches nothing here
for how in ['inner', 'left', 'right', 'outer']:
    res = call('tables.join', table=tl, with_table=tr_, match=[['k', 'k']], how=how, match_flag=True)
    m = Lk.merge(Rk, on='k', how=how)
    if how in ('left', 'outer'):
        m = pd.concat([m, L[L.k.isna()]], ignore_index=True)
    if how in ('right', 'outer'):
        m = pd.concat([m, R[R.k.isna()]], ignore_index=True)
    want = sorted(((a if not np.isnan(a) else -1), (b if not np.isnan(b) else -1)) for a, b in zip(m.lv, m.rv))
    check(f'{how} join: the same pairs as DataFrame.merge', pairs_of(res), want)
res = call('tables.join', table=tl, with_table=tr_, match=[['k', 'k']], how='outer', match_flag=True)
c = {x['name']: x['values'] for x in res['columns']}
flag = pd.Series(Lk.merge(Rk, on='k', how='outer', indicator=True)['_merge'].map({'left_only': 1.0, 'right_only': 2.0, 'both': 3.0}))
check('the match flag counts as pandas\' indicator', sorted(x for x, k in zip(c['Match Flag'], c['k']) if k is not None), sorted(flag.tolist()))
check('outer join: the merged key column takes the other table\'s key where the main has none', 'd' in c['k'], True)
res = call('tables.join', table=tl, with_table=tr_, match=[['k', 'k']], how='inner', drop_right=True)
check('drop multiples in the with table: as drop_duplicates', pairs_of(res), sorted(zip(Lk.merge(Rk.drop_duplicates('k'), on='k').lv, Lk.merge(Rk.drop_duplicates('k'), on='k').rv)))
res = call('tables.join', table=tl, with_table=tr_, match=[['k', 'k']], how='inner', drop_left=True)
check('drop multiples in the main table: as drop_duplicates', pairs_of(res), sorted(zip(Lk.drop_duplicates('k').merge(Rk, on='k').lv, Lk.drop_duplicates('k').merge(Rk, on='k').rv)))
res = call('tables.join', table=tl, with_table=tr_, by_row=True, how='outer')
check('join by row number: row 1 with row 1', {x['name']: x['values'] for x in res['columns']}['rv'], R.rv.tolist() + [None])
res = call('tables.join', table=tl, with_table=tr_, cartesian=True)
check('Cartesian join: every row with every row', res['nrows'], len(L) * len(R))
tn = table({'k': [1.0, 2.0, 3.0], 'v': [7.0, 8.0, 9.0]})
tc = table({'k': ['2', '3', '4'], 'u': [1.0, 2.0, 3.0]})
res = call('tables.join', table=tn, with_table=tc, match=[['k', 'k']], how='inner')
check('a numeric key matches a text key by its text', {x['name']: x['values'] for x in res['columns']}['u'], [1.0, 2.0])
check('the same column name in both tables: of main, of with', [x['name'] for x in call('tables.join', table=tl, with_table=table({'k': ['a'], 'lv': [9.0]}), match=[['k', 'k']], left_name='L', right_name='R')['columns']], ['k', 'lv of L', 'lv of R'])

# ---- Tables > Update -----------------------------------------------------------------------------
tm = table({'id': [1.0, 2.0, 3.0, 4.0], 'v': [10.0, 20.0, 30.0, 40.0], 'name': ['a', 'b', 'c', 'd']})
tw = table({'id': [2.0, 4.0, 4.0, 5.0], 'v': [200.0, None, 400.0, 500.0], 'extra': ['x', 'y', 'z', 'w']})
up = call('tables.update', table=tm, with_table=tw, match=[['id', 'id']], ignore_missing=True)
check('update: the first match replaces, a missing value does not', up['update'][0]['values'], [10.0, 200.0, 30.0, 40.0])
check('update: added columns', up['add'][0]['values'], [None, 'x', None, 'y'])
up = call('tables.update', table=tm, with_table=tw, match=[['id', 'id']], ignore_missing=False)
check('update without Ignore missing', up['update'][0]['values'], [10.0, 200.0, 30.0, None])
first = pd.DataFrame({'id': [2.0, 4.0, 4.0, 5.0], 'v': [200.0, np.nan, 400.0, 500.0]}).drop_duplicates('id')
mm = pd.DataFrame({'id': [1.0, 2.0, 3.0, 4.0], 'v': [10.0, 20.0, 30.0, 40.0]}).merge(first, on='id', how='left', suffixes=('', '_new'))
close('update as a left merge on the first match with combine_first', up['update'][0]['values'][:3], mm['v_new'].combine_first(mm['v']).tolist()[:3])
check('update: the number of matched rows', up['matched'], 2)

# ---- Missing Data Pattern and Explore Missing Values ---------------------------------------------------
mp = call('tables.missing_pattern', table=tid, columns=['g1', 'x', 's'])
pat = df[['g1', 'x', 's']].isna().astype(int).astype(str).agg(''.join, axis=1).value_counts().sort_index()
cmp_ = {c['name']: c['values'] for c in mp['columns']}
check('missing data patterns, sorted, as pandas value_counts', cmp_['Patterns'], pat.index.tolist())
check('their counts', cmp_['Count'], [float(v) for v in pat.values])
check('number of columns missing', cmp_['Number of columns missing'], [float(p.count('1')) for p in pat.index])
check('the indicator of x', cmp_['x'], [float(p[1]) for p in pat.index])
rep_ = call('tables.missing_report', table=tid, columns=['g1', 'x', 's'])
check('missing columns report', [(c['column'], c['n_missing']) for c in rep_['columns']], [(k, int(df[k].isna().sum())) for k in ['g1', 'x', 's']])
check('rows with a missing value', rep_['rows_with_missing'], int(df[['g1', 'x', 's']].isna().any(axis=1).sum()))
check('patterns in the report add up to the rows', sum(p['count'] for p in rep_['patterns']), N)

# imputation
Xm = np.column_stack([x, y])
im = call('tables.impute', table=tid, columns=['x', 'y'], method='mean')
close('mean imputation is fillna(mean)', im['columns'][0]['values'], df.x.fillna(df.x.mean()).tolist())
im = call('tables.impute', table=tid, columns=['x'], method='median')
close('median imputation is fillna(median)', im['columns'][0]['values'], df.x.fillna(df.x.median()).tolist())
# EM against the closed form of a monotone pattern (Anderson 1957): u complete, v missing in some rows
n2 = 400
u = rng.normal(0, 1, n2)
v = 2 + 0.8 * u + rng.normal(0, 0.5, n2)
vm = v.copy()
vm[rng.random(n2) < 0.3] = np.nan
te = table({'u': u, 'v': vm})
cc = ~np.isnan(vm)
beta = np.cov(u[cc], vm[cc], bias=True)[0, 1] / np.var(u[cc])
alpha = vm[cc].mean() - beta * u[cc].mean()
em = call('tables.impute', table=te, columns=['u', 'v'], method='mvn')
check('EM converged', em['info']['iterations'] < 500, True)
check.near('EM mean of v is the regression estimate', em['info']['mean'][1], float(alpha + beta * u.mean()), rel=1e-6)
resid = vm[cc] - alpha - beta * u[cc]
check.near('EM variance of v', em['info']['cov'][1][1], float(np.mean(resid ** 2) + beta ** 2 * np.var(u)), rel=1e-6)
check.near('EM covariance', em['info']['cov'][0][1], float(beta * np.var(u)), rel=1e-6)
close('MVN imputation: the conditional mean alpha + beta u', np.array(em['columns'][1]['values'])[~cc], (alpha + beta * u)[~cc], rel=1e-6)
close('MVN imputation keeps the observed values', np.array(em['columns'][1]['values'])[cc], vm[cc])
mi = call('tables.impute', table=tid, columns=['x', 'y', 'w'], method='mice', seed=7, n_iter=5)
mi2 = call('tables.impute', table=tid, columns=['x', 'y', 'w'], method='mice', seed=7, n_iter=5)
check('MICE fills every missing value', bool(np.all(np.isfinite(mi['columns'][0]['values']))), True)
check('MICE keeps the observed values', bool(np.allclose(np.array(mi['columns'][0]['values'])[~np.isnan(x)], x[~np.isnan(x)])), True)
check('MICE repeats with the same seed', mi['columns'][0]['values'], mi2['columns'][0]['values'])
check('MICE draws imputed values from the observed ones (predictive mean matching)', bool(set(np.round(np.array(mi['columns'][0]['values'])[np.isnan(x)], 9)) <= set(np.round(x[~np.isnan(x)], 9))), True)

# ---- Columns Viewer -----------------------------------------------------------------------------------------
cv = call('tables.colviewer', table=tid, columns=['x', 'g1', 'g2'])
rx = cv['rows'][0]
check('columns viewer N, N Missing', (rx['n'], rx['n_missing']), (int(np.sum(~np.isnan(x))), int(np.isnan(x).sum())))
close('columns viewer mean, std dev, min, max', [rx['mean'], rx['sd'], rx['min'], rx['max']], [np.nanmean(x), np.nanstd(x, ddof=1), np.nanmin(x), np.nanmax(x)])
close('columns viewer median and quartiles (weibull)', [rx['lq'], rx['median'], rx['uq']], np.quantile(fin(x), [0.25, 0.5, 0.75], method='weibull'))
check('columns viewer: categories of a nominal column, no mean', (cv['rows'][1]['n_categories'], 'mean' in cv['rows'][1], cv['rows'][2]['n_categories']), (3, False, 3))

# ---- Tabulate ----------------------------------------------------------------------------------------------
tb = call('tables.tabulate', table=tid, row_chains=[['g1', 'g2']], col_chains=[['s']], analysis=['x'], stats=['N', 'Mean', 'Quantiles', '% of Total', 'Column %', 'Row %'], quantiles=[25], all_rows=True, all_cols=True)
d = df.dropna(subset=['g1', 'g2', 's'])   # a missing grouping value leaves the table
check('tabulate uses the rows without a missing grouping value', tb['n'], len(d))
heads = [(tuple(tuple(l) for l in h['levels']), h['all'], h['stat']) for h in tb['cols']]
rows_ = [(tuple(tuple(l) for l in r_['levels']), r_['all']) for r_ in tb['rows']]
check('tabulate rows: nested g1 then g2 in value order, then All', [r_[0] for r_ in rows_[:3]], [(('g1', 'c'), ('g2', 3.0)), (('g1', 'c'), ('g2', 1.0)), (('g1', 'c'), ('g2', 2.0))])
check('the last row is All', rows_[-1], ((), True))
vals = tb['values']


def cell(ri, level, stat):
    ci = [k for k, h in enumerate(heads) if h[2] == stat and (h[0] == level if level else h[1])][0]
    return vals[ri][ci]


def sel(a, b, sv_):
    m = pd.Series(True, index=d.index)
    if a is not None:
        m &= d.g1 == a
    if b is not None:
        m &= d.g2 == b
    if sv_ is not None:
        m &= d.s == sv_
    return d.x[m].dropna()


ok = True
for ri, (lev, is_all) in enumerate(rows_):
    a = dict(lev).get('g1')
    b = dict(lev).get('g2')
    for sv_ in ['p', 'q', 'r', 's', None]:
        level = (('s', sv_),) if sv_ is not None else None
        xs = sel(a, b, sv_)
        n_ = cell(ri, level, 'N')
        mean_ = cell(ri, level, 'Mean')
        q_ = cell(ri, level, 'Quantiles')
        if n_ != len(xs) or (len(xs) and abs(mean_ - xs.mean()) > 1e-9) or (len(xs) and abs(q_ - np.quantile(xs, 0.25, method='weibull')) > 1e-9):
            ok = False
            print('   cell', lev, sv_, n_, len(xs), mean_, q_)
check('tabulate N, Mean and weibull quantiles in every cell, All included, against pandas', ok, True)
total = d.x.sum()
ri = rows_.index(((('g1', 'a'), ('g2', 1.0)), False))
check.near('tabulate % of Total: of the whole table\'s sum', cell(ri, (('s', 'p'),), '% of Total'), float(100 * sel('a', 1.0, 'p').sum() / total))
check.near('tabulate Column %: of its column\'s sum', cell(ri, (('s', 'p'),), 'Column %'), float(100 * sel('a', 1.0, 'p').sum() / sel(None, None, 'p').sum()))
check.near('tabulate Row %: of its row\'s sum', cell(ri, (('s', 'p'),), 'Row %'), float(100 * sel('a', 1.0, 'p').sum() / sel('a', 1.0, None).sum()))
ct = call('tables.tabulate', table=tid, row_chains=[['g1']], col_chains=[['s']], stats=['N', '% of Total'])
dd = df.dropna(subset=['g1', 's'])
xt = pd.crosstab(dd.g1, dd.s)
check('tabulate counts without an analysis column are pd.crosstab', [[ct['values'][i][2 * j] for j in range(4)] for i in range(3)], [[float(xt.loc[a, b]) for b in ['p', 'q', 'r', 's']] for a in ['c', 'a', 'b']])
cm = call('tables.tabulate', table=tid, row_chains=[['g1']], stats=['N'], include_missing=True)
check('include missing: a level for the missing group', [r_['levels'][0][1] for r_ in cm['rows']], ['c', 'a', 'b', None])
check('include missing: its count', cm['values'][-1][0], float(df.g1.isna().sum()))
cr = call('tables.tabulate', table=tid, row_chains=[['g1'], ['s']], stats=['N'])
check('two row chains side by side (crossing): the blocks one after another', [r_['block'] for r_ in cr['rows']], [0, 0, 0, 1, 1, 1, 1])
cf2 = call('tables.tabulate', table=tid, row_chains=[['g1']], analysis=['x'], stats=['N', 'Mean'], freq='f')
dfreq = df.dropna(subset=['g1'])
dfreq = dfreq[dfreq.f > 0]
check.near('tabulate with Freq: the weighted mean', cf2['values'][0][1], float(np.average(dfreq[dfreq.g1 == 'c'].x.dropna(), weights=dfreq[dfreq.g1 == 'c'].dropna(subset=['x']).f)))

# ---- File > Python Script ---------------------------------------------------------------------------------------
rs_ = call('tables.run_script', table=tid, code='print(df.shape)\nprint(df["g1"].dtype)\nresult = df.groupby("g1", observed=True)["x"].mean().reset_index()')
check('the script prints', rs_['stdout'].splitlines()[:2], [str((N, 7)), 'category'])
check('no error', rs_['error'], None)
rc = {c['name']: c for c in rs_['result']['columns']}
check('result as a table: a categorical column keeps its levels', (rc['g1']['modelingType'], rc['g1']['levels']), ('nominal', ['c', 'a', 'b']))
close('result as a table: the means', rc['x']['values'], [np.nanmean(x[df.g1 == a]) for a in ['c', 'a', 'b']])
re_ = call('tables.run_script', table=tid, code='a = 1\nb = [1, 2]\nprint("before")\nc = b[5]\n')
check('an error says what and where', re_['error'], 'IndexError: list index out of range (line 4)')
check('output before the error is kept', re_['stdout'], 'before\n')
check('the traceback shows the line', re_['traceback'], '  line 4: c = b[5]')
rsx = call('tables.run_script', table=tid, code='def f(:\n    pass\n')
check('a syntax error with its line', rsx['error'].startswith('SyntaxError') and '(line 1' in rsx['error'], True)
call('tables.run_script', table=tid, code='secret = 42')
check('each run has a fresh namespace', call('tables.run_script', table=tid, code='print("secret" in dir())')['stdout'], 'False\n')
check('rows: the script sees the rows asked for', call('tables.run_script', table=tid, code='print(len(df), list(df.index[:3]))', rows=[5, 7, 9])['stdout'], '3 [5, 7, 9]\n')
check('np, pd, sm, smf and stats are there', call('tables.run_script', table=tid, code='print(all(m is not None for m in (np, pd, sm, smf, stats)), stats.norm.cdf(0))')['stdout'], 'True 0.5\n')
rv = call('tables.run_script', table=tid, code='result = 3.5')
check('a result that is not a DataFrame is shown, not made a table', (rv['result'], rv['result_type'], rv['result_repr']), (None, 'float', '3.5'))
rser = call('tables.run_script', table=tid, code='result = df["x"].describe()')
check('a Series result becomes a table with its index', [c['name'] for c in rser['result']['columns']], ['index', 'x'])
rdt = call('tables.run_script', table=tid, code='result = pd.DataFrame({"when": pd.to_datetime(["2024-02-29", None]), "ok": [True, False]})')
check('datetimes become milliseconds with a date format, booleans 0/1', (rdt['result']['columns'][0]['values'][0], rdt['result']['columns'][0].get('format'), rdt['result']['columns'][1]['values']), (1709164800000.0, {'kind': 'datetime'}, [1.0, 0.0]))
rwarn = call('tables.run_script', table=tid, code='import warnings\nwarnings.warn("careful")')
check('warnings come back', any('careful' in w for w in rwarn.get('warnings', [])), True)

sys.exit(check.done())
