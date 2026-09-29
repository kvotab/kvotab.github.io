#!/usr/bin/env python3
"""Analyze > Multivariate Methods > Multivariate Embedding's backend
(resources/py/smui/embedding.py), checked against scikit-learn's TSNE called
directly with the same settings (the map, the final KL divergence, the
iterations and the learning rate; standardized and raw columns, two and
three dimensions, PCA and random starts, a given learning rate), against
the definitions (the "auto" learning rate, the KL divergence of the final
map computed here from its neighbourhoods), on simulated clusters (the map
keeps them: each row's nearest neighbour in the map is of its own cluster),
the progress lines it prints, and by running the Python shown on a CSV
export of the table.

Pyodide runs one thread; so does this test (OMP_NUM_THREADS=1), which makes
scikit-learn's Barnes-Hut sums come out the same in every run.

    python3 resources/tests/smui/test_embedding.py
"""
import os

os.environ['OMP_NUM_THREADS'] = '1'

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.spatial.distance import pdist, squareform  # noqa: E402
from sklearn.manifold import TSNE  # noqa: E402
from sklearn.manifold._t_sne import _joint_probabilities_nn  # noqa: E402
from sklearn.neighbors import NearestNeighbors  # noqa: E402

from backend import FAILED, Checks, table  # noqa: E402
from backend import call as _call  # noqa: E402

check = Checks()
check('embedding.py imports', 'embedding' in FAILED, False)
from smui import embedding as EM  # noqa: E402
from smui import registry  # noqa: E402


def call(fn, **kw):
    """backend.call without the progress lines t-SNE prints."""
    with contextlib.redirect_stdout(io.StringIO()):
        return _call(fn, **kw)


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def sk(X, dim=2, perplexity=30.0, lr='auto', max_iter=1000, init='pca', seed=0, early=12.0):
    t = TSNE(n_components=dim, perplexity=perplexity, early_exaggeration=early, learning_rate=lr, max_iter=max_iter, init=init,
             random_state=seed, method='barnes_hut', angle=0.5)
    E = t.fit_transform(X)
    return t, E


def std(X):
    return (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)


check('embedding.fit needs scikit-learn', json.loads(registry.packages_for('embedding.fit')), ['scikit-learn'])

# ---- four clusters in eight columns of different scales ---------------------------------------------------------------
r0 = np.random.default_rng(12)
G = 4
lab = np.repeat(np.arange(G), [150, 120, 90, 60])
centres = r0.normal(0, 4, (G, 8))
X = centres[lab] + r0.normal(0, 1, (len(lab), 8))
X[:, 0] *= 100            # one column in large units: standardizing matters
X[:, 3] = X[:, 3] * 0.01 + 5
cols = [f'x{j}' for j in range(8)]
tX = table({c: X[:, j] for j, c in enumerate(cols)})
n = len(X)

res = call('embedding.fit', table=tX, columns=cols, seed=7)
t, E = sk(std(X), seed=7)
check('the map: TSNE on the standardized columns, the same seed', mx(res['coords'], E), 0.0)
check('the final KL divergence is TSNE\'s kl_divergence_', res['kl'], float(t.kl_divergence_))
check('the iterations are n_iter_ + 1', (res['iterations'], int(t.n_iter_) + 1), (1000, 1000))
check.near('the "auto" learning rate is max(N / early exaggeration / 4, 50)', res['learning_rate'], max(n / 12 / 4, 50), rel=1e-12)
check('one point per row, two coordinates, the rows the table\'s', (len(res['coords']), len(res['coords'][0]), res['rows'][:3], res['n']), (n, 2, [0, 1, 2], n))
check('the columns\' names and the saved names', (res['columns'], res['names']), (cols, ['t-SNE 1', 't-SNE 2']))
Ec = np.array(res['coords'])
nn = NearestNeighbors(n_neighbors=2).fit(Ec)
near = nn.kneighbors(Ec, return_distance=False)[:, 1]
agree = float(np.mean(lab[near] == lab))
check(f'the map keeps the clusters: each row\'s nearest neighbour in the map is of its own cluster ({agree:.3f})', agree > 0.97, True)
raw = call('embedding.fit', table=tX, columns=cols, seed=7, standardize=False)
t_raw, E_raw = sk(X, seed=7)
check('Standardize off: TSNE on the columns as they are', mx(raw['coords'], E_raw), 0.0)
Er = np.array(raw['coords'])
agree_raw = float(np.mean(lab[NearestNeighbors(n_neighbors=2).fit(Er).kneighbors(Er, return_distance=False)[:, 1]] == lab))
check(f'... where the large column dominates and the clusters blur ({agree_raw:.3f} < {agree:.3f})', agree_raw < agree, True)

# ---- the KL divergence of the final map, from its definition ---------------------------------------------------------------
# P: scikit-learn's Barnes-Hut neighbourhoods (the 3 × perplexity nearest neighbours, each row's Gaussian at its
# perplexity, symmetrized); Q: Student t (one degree of freedom) over all pairs of the map. KL(P‖Q) = Σ P log(P/Q).
Z = std(X)
k_nn = min(n - 1, int(3 * 30 + 1))
D = NearestNeighbors(n_neighbors=k_nn).fit(Z).kneighbors_graph(mode='distance')
D.data **= 2
P = _joint_probabilities_nn(D, 30.0, 0).toarray()
q = 1 / (1 + squareform(pdist(Ec, 'sqeuclidean')))
np.fill_diagonal(q, 0)
Q = q / q.sum()
mask = P > 0
kl_here = float(np.sum(P[mask] * np.log(np.maximum(P[mask], 1e-300) / np.maximum(Q[mask], 1e-300))))
check.near(f'the final KL divergence is KL(P‖Q) of the final map, computed here exactly ({kl_here:.4f}); Barnes-Hut\'s estimate within 3%', res['kl'], kl_here, rel=0.03)

# ---- settings ---------------------------------------------------------------------------------------------------------
r3 = call('embedding.fit', table=tX, columns=cols, seed=3, dimension=3, max_iter=400)
t3, E3 = sk(std(X), dim=3, seed=3, max_iter=400)
check('three dimensions: TSNE with n_components=3', (mx(r3['coords'], E3), len(r3['coords'][0]), r3['names']), (0.0, 3, ['t-SNE 1', 't-SNE 2', 't-SNE 3']))
check('... and its KL divergence and iterations', (r3['kl'], r3['iterations']), (float(t3.kl_divergence_), int(t3.n_iter_) + 1))
rr = call('embedding.fit', table=tX, columns=cols, seed=5, init='random', perplexity=12, learning_rate='200', max_iter=300, early_exaggeration=8)
tr_, Er_ = sk(std(X), seed=5, init='random', perplexity=12, lr=200.0, max_iter=300, early=8.0)
check('a random start, perplexity 12, learning rate 200, early exaggeration 8, 300 iterations: TSNE with the same', mx(rr['coords'], Er_), 0.0)
check('... the learning rate as given', (rr['learning_rate'], rr['learning_rate_asked'], rr['perplexity'], rr['early_exaggeration']), (200.0, 200.0, 12.0, 8.0))
check('scikit-learn: with the PCA start the seed does not change the map (the start and the descent are deterministic)', mx(call('embedding.fit', table=tX, columns=cols, seed=8, max_iter=300)['coords'], call('embedding.fit', table=tX, columns=cols, seed=9, max_iter=300)['coords']), 0.0)
check('... with the random start another seed gives another map', mx(call('embedding.fit', table=tX, columns=cols, seed=8, max_iter=300, init='random')['coords'], call('embedding.fit', table=tX, columns=cols, seed=9, max_iter=300, init='random')['coords']) > 0.1, True)
again = call('embedding.fit', table=table({c: X[:, j] for j, c in enumerate(cols)}), columns=cols, seed=7)
check('the same seed gives the same map (a new table, no cache)', (mx(again['coords'], res['coords']), again['kl'] == res['kl']), (0.0, True))

# ---- rows, missing values, errors -------------------------------------------------------------------------------------
sub = list(range(0, n, 3))
rs = call('embedding.fit', table=tX, columns=cols, rows=sub, seed=4, max_iter=300)
ts_, Es_ = sk(std(X[sub]), seed=4, max_iter=300)
check('a row list (a By group, exclusions): the map of those rows', (rs['rows'], mx(rs['coords'], Es_)), (sub, 0.0))
XM = X.copy()
XM[[4, 9], 2] = np.nan
tM = table({c: XM[:, j] for j, c in enumerate(cols)})
rm = call('embedding.fit', table=tM, columns=cols, seed=4, max_iter=300)
ok = np.isfinite(XM).all(axis=1)
tm_, Em_ = sk(std(XM[ok]), seed=4, max_iter=300)
check('rows with a missing value are left out, and said so', (rm['n'], 4 in rm['rows'], rm['notes'], mx(rm['coords'], Em_)), (n - 2, False, ['2 rows with a missing value left out.'], 0.0))
tK = table({'a': X[:, 0], 'b': X[:, 1], 'k': np.full(n, 3.0)})
rk = call('embedding.fit', table=tK, columns=['a', 'b', 'k'], seed=4, max_iter=300)
check('a column with one value is left out, and said so', (rk['columns'], rk['dropped'], rk['notes']), (['a', 'b'], ['k'], ['k has a single value in these rows and is left out.']))
small = table({'a': X[:20, 0], 'b': X[:20, 1]})
rsm = call('embedding.fit', table=small, columns=['a', 'b'], seed=1, max_iter=300)
ts2, Es2 = sk(std(X[:20, :2]), perplexity=19 / 3, seed=1, max_iter=300)
check('a perplexity not below the number of rows is lowered to (n − 1)/3, and said so', (rsm['perplexity'], rsm['perplexity_asked'], 'is not below the number of rows' in rsm['notes'][0], mx(rsm['coords'], Es2)), (19 / 3, 30.0, True, 0.0))
check('no column: an error', call('embedding.fit', table=tX, columns=[])['error'], 'choose two or more Y, Columns')
check('fewer than 250 iterations: an error', 'at least 250' in call('embedding.fit', table=tX, columns=cols, max_iter=100)['error'], True)
check('dimension 4: an error', call('embedding.fit', table=tX, columns=cols, dimension=4)['error'], 'the dimension of the map is 2 or 3')
check('a learning rate that is not a number: an error', 'learning rate' in call('embedding.fit', table=tX, columns=cols, learning_rate='fast')['error'], True)
check('three rows: an error', 'too few' in call('embedding.fit', table=tX, columns=cols, rows=[0, 1, 2])['error'], True)
big = table({'a': np.arange(EM.MAX_ROWS + 1.0), 'b': np.arange(EM.MAX_ROWS + 1.0) % 7})
check(f'more than {EM.MAX_ROWS} rows: refused before any work', 'at most' in call('embedding.fit', table=big, columns=['a', 'b'])['error'], True)
tchar = table({'a': X[:, 0], 's': ['u'] * n})
check('a character column: an error', call('embedding.fit', table=tchar, columns=['a', 's'])['error'], 's is not numeric')

# ---- progress lines ---------------------------------------------------------------------------------------------------
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    _call('embedding.fit', table=tX, columns=cols, seed=2, max_iter=400)
out = buf.getvalue().splitlines()
prog = [ln for ln in out if ln.startswith('smui:progress')]
steps = [int(ln.split()[2]) for ln in prog]
check('progress: a line at the start and every 50 iterations, to the last', steps, [0] + list(range(50, 401, 50)))
check('... each "smui:progress tsne <iteration> <iterations>"', all(ln.split()[1] == 'tsne' and ln.split()[3] == '400' for ln in prog), True)
check('scikit-learn\'s own lines do not reach the page', [ln for ln in out if '[t-SNE]' in ln], [])

# ---- the Python shown runs on a CSV export and gives the report's map ------------------------------------------------------
work = tempfile.mkdtemp()
pd.DataFrame({c: XM[:, j] for j, c in enumerate(cols)}).to_csv(os.path.join(work, 'data.csv'), index=False)
tC = table({c: XM[:, j] for j, c in enumerate(cols)})


def run(code):
    with open(os.path.join(work, 'code.py'), 'w') as fh:
        fh.write(code + '\nimport json\nprint("JSON", json.dumps({"E": np.asarray(E, float).tolist(), "index": d.index.tolist()}))\n')
    p_ = subprocess.run([sys.executable, 'code.py'], cwd=work, capture_output=True, text=True, timeout=900, env={**os.environ, 'OMP_NUM_THREADS': '1'})
    if p_.returncode:
        print(p_.stderr[-3000:])
    return p_


for label, kw in (('standardized, two dimensions', {}), ('raw columns, three dimensions, a random start', {'standardize': False, 'dimension': 3, 'init': 'random', 'max_iter': 500}),
                  ('a row list, a learning rate, perplexity 20', {'rows': list(range(5, n, 2)), 'learning_rate': '150', 'perplexity': 20, 'max_iter': 400})):
    r = call('embedding.fit', table=tC, columns=cols, seed=13, table_name='data', **kw)
    p_ = run(r['code'])
    if not check(f'the code runs ({label})', p_.returncode, 0):
        continue
    kl_line = next(ln for ln in p_.stdout.splitlines() if ln.startswith('kl '))
    got = json.loads(next(ln for ln in p_.stdout.splitlines() if ln.startswith('JSON '))[5:])
    kl, iters, lr = (float(v) for v in kl_line.split()[1:4])
    check(f'... and gives the report\'s map, KL divergence, iterations and learning rate ({label})',
          (mx(got['E'], r['coords']), got['index'] == r['rows'], kl == r['kl'], int(iters) == r['iterations'], lr == r['learning_rate']), (0.0, True, True, True, True))

# ---- the map's code starts with the fit's own lines (map_head; the page adds the drawing, which
# test-ui-embedding.py runs in the page): a date column (text in the CSV), a column with a single
# value and a gap (its row left out, as the report leaves it out), a By group with rows left out
import datetime as _dt  # noqa: E402

from smui import data as _data  # noqa: E402

day0 = _dt.datetime(2024, 1, 1)
when = np.array([(day0 + _dt.timedelta(days=int(3 * i + (i % 5))) - _dt.datetime(1970, 1, 1)).total_seconds() * 1000 for i in range(n)])
flat = np.full(n, 4.0)
flat[9] = np.nan
grpE = ['u' if i % 4 else 'v' for i in range(n)]
colsE = {**{c: XM[:, j] for j, c in enumerate(cols)}, 'when': when, 'flat': flat, 'grp': grpE}
tE = table(colsE)
_data.TABLES[tE]['meta']['when']['format'] = {'kind': 'date'}
pd.DataFrame({**{c: XM[:, j] for j, c in enumerate(cols)}, 'when': [(_dt.datetime(1970, 1, 1) + _dt.timedelta(milliseconds=float(v))).strftime('%Y-%m-%d') for v in when],
              'flat': flat, 'grp': grpE}).to_csv(os.path.join(work, 'dated.csv'), index=False)
rows_u = [i for i in range(n) if grpE[i] == 'u' and i not in (5, 6)]
for label, kw in (('a date column, a constant column with a gap', {'columns': cols[:3] + ['when', 'flat']}),
                  ('a By group with rows left out', {'columns': cols[:3] + ['when'], 'rows': rows_u, 'where': [{'column': 'grp', 'value': 'u'}]})):
    r = call('embedding.fit', table=tE, seed=21, max_iter=300, table_name='dated', **kw)
    head = r['map_head']   # the backend dates it (and the page's datedCode then leaves it as it is)
    check(f'the map\'s lines turn the date back into milliseconds ({label})', head.count('pd.to_datetime(df["when"])'), 1)
    if 'where' in kw:
        check(f'... keep the By group and drop the rows left out ({label})', ('df = df[df["grp"] == "u"]' in head, 'df = df.drop(index=[5, 6])' in head), (True, True))
    else:
        want_n = int(np.sum(np.isfinite(XM[:, :3]).all(axis=1) & np.isfinite(flat)))
        check(f'... and leave out the row whose constant column has a gap, as the report does ({label})', (r['n'], 'without flat' in head, r['dropped']), (want_n, True, ['flat']))
    p_ = run(head.replace('import matplotlib.pyplot as plt\n', ''))
    if not check(f'the map\'s lines run ({label})', p_.returncode, 0):
        continue
    got = json.loads(next(ln for ln in p_.stdout.splitlines() if ln.startswith('JSON '))[5:])
    check(f'... and give the report\'s map ({label})', (mx(got['E'], r['coords']), got['index'] == r['rows']), (0.0, True))

sys.exit(check.done())
