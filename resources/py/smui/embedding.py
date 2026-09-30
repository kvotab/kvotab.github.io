"""Analyze > Multivariate Methods > Multivariate Embedding.

t-SNE (scikit-learn's TSNE, the Barnes-Hut method) of continuous columns:
every row a point in two or three dimensions, placed near the rows it is
near in all the columns. The neighbourhoods come from Gaussian kernels
whose widths give each row the same perplexity (about how many neighbours
it has); the map is fitted by gradient descent on the Kullback-Leibler
divergence between those neighbourhoods and Student t ones in the map.

UMAP, JMP's other method, is not here: umap-learn needs numba, which
Pyodide does not have.

The fit prints 'smui:progress tsne <iteration> <iterations>' lines while it
runs (scikit-learn's own progress lines, read as they come).
"""
import contextlib
import io
import json
import re
import sys
import time

import numpy as np

from . import data, predictive
from .registry import api
from .util import code_head, one_line

SK = predictive.SK
J = json.dumps


def _dated(obj, table):
    """Code that reads the table's CSV (a string, or the strings of a list
    or dict) with the line that turns each date column it names back into
    the page's number, as dispatch does for the keys code and *_code."""
    from .util import date_columns, dated_code
    cols = date_columns(table)
    if not cols:
        return obj
    if isinstance(obj, str):
        return dated_code(obj, cols)
    if isinstance(obj, list):
        return [_dated(v, table) for v in obj]
    if isinstance(obj, dict):
        return {k: _dated(v, table) for k, v in obj.items()}
    return obj
MAX_ROWS = 10000          # beyond this the page refuses (many minutes in the browser)


class _Progress(io.TextIOBase):
    """Stands in for stdout while TSNE runs: its '[t-SNE] Iteration n' lines
    become the page's progress lines; the rest is dropped."""

    def __init__(self, total, out):
        super().__init__()
        self.total, self.out, self.buf = int(total), out, ''

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            m = re.match(r'\[t-SNE\] Iteration (\d+):', line)
            if m:
                print(f'smui:progress tsne {m.group(1)} {self.total}', file=self.out, flush=True)
        return len(s)

    def flush(self):
        pass


def _lit(v):
    """A value as a Python literal: 12.0 as 12, text quoted."""
    if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
        f = float(v)
        return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(f)
    return J(str(v))


def _keep_lines(table, rows, where=None):
    """After the code's head: the By group's rows (its where lines) and, of
    those, the ones the report uses (excluded and filtered rows dropped)."""
    L = []
    n = data.TABLES[table]['n'] if table in data.TABLES else 0
    match = np.ones(n, dtype=bool)
    for w in where or []:
        v = data.raw(table, w['column'])
        num = data.meta(table, w['column']).get('dataType') == 'numeric'
        match &= (np.asarray(v, dtype=float) == float(w['value'])) if num else np.array([x == w['value'] for x in v], dtype=bool)
        shown = w['value'] if isinstance(w['value'], str) else _lit(w['value'])
        L.append(f'df = df[df[{J(w["column"])}] == {_lit(w["value"])}]   # only the rows where {one_line(w["column"])} is {one_line(shown)}')
    if rows is not None and n:
        keep = np.zeros(n, dtype=bool)
        keep[np.asarray(rows, dtype=int)] = True
        drop = np.flatnonzero(match & ~keep).tolist()
        if drop and not where and keep.sum() <= n / 2:
            return [f'df = df.loc[{np.flatnonzero(keep).tolist()}]   # the rows of the report']
        if drop:
            L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
    return L


def _learning_rate(v):
    if v is None or v == '' or (isinstance(v, str) and v.strip().lower() == 'auto'):
        return 'auto'
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'the learning rate is a positive number or auto, not {v!r}')
    if not x > 0:
        raise ValueError('the learning rate is a positive number or auto')
    return x


def quiet_threadpoolctl():
    """Pyodide 314's threadpoolctl calls a deprecated JsProxy method the
    first time scikit-learn asks for its thread pools; its RuntimeWarning
    says nothing about the analysis, so the controller is made once
    without it (scikit-learn keeps it)."""
    import warnings
    try:
        from sklearn.utils import parallel
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message=r'JsProxy\.as_object_map', category=RuntimeWarning)
            parallel._get_threadpool_controller()
    except Exception:   # another scikit-learn: nothing to quiet
        pass


@api('embedding.fit', packages=SK)
def fit(table, columns, rows=None, dimension=2, perplexity=30.0, max_iter=1000, learning_rate='auto', init='pca',
        standardize=True, seed=None, early_exaggeration=12.0, where=None, table_name='data'):
    """t-SNE of the rows over the columns: the map's coordinates of every row
    with a value in every column, the final Kullback-Leibler divergence, the
    iterations run and the learning rate used; the code, and the lines the
    map's code starts with (map_head: the page adds the drawing)."""
    from sklearn.manifold import TSNE
    quiet_threadpoolctl()
    cols = [c for c in dict.fromkeys(columns or []) if c]
    if not cols:
        return {'error': 'choose two or more Y, Columns'}
    dim = int(dimension or 2)
    if dim not in (2, 3):
        return {'error': 'the dimension of the map is 2 or 3'}
    try:
        perplexity = float(perplexity)
        max_iter = int(max_iter or 1000)
        lr = _learning_rate(learning_rate)
        early = float(early_exaggeration or 12.0)
    except (TypeError, ValueError) as e:
        return {'error': str(e)}
    if not perplexity > 0:
        return {'error': 'the perplexity is a positive number'}
    if max_iter < 250:
        return {'error': 'Iterations: at least 250 (the first 250 are the early exaggeration)'}
    if not early >= 1:
        return {'error': 'the early exaggeration is 1 or more'}
    if init not in ('pca', 'random'):
        return {'error': 'the initialization is pca or random'}
    seed = predictive.seed_of(seed)
    seed = 0 if seed is None else seed
    df = data.frame(table, cols, rows, dropna=False, as_category=False)
    for c in cols:
        if df[c].dtype == object:
            return {'error': f'{c} is not numeric'}
    notes = []
    ok = np.isfinite(df[cols].to_numpy(float)).all(axis=1)
    if (~ok).sum():
        notes.append(f'{int((~ok).sum())} row{"s" if (~ok).sum() != 1 else ""} with a missing value left out.')
    df = df[ok]
    n = len(df)
    const = [c for c in cols if n and not np.ptp(df[c].to_numpy(float)) > 0]
    used = [c for c in cols if c not in const]
    if const:
        notes.append(f'{", ".join(const)} {"has" if len(const) == 1 else "have"} a single value in these rows and {"is" if len(const) == 1 else "are"} left out.')
    if not used:
        return {'error': 'no column varies in these rows'}
    if n < 4:
        return {'error': f'{n} rows with every column: too few for a map'}
    if n > MAX_ROWS:
        return {'error': f'{n} rows: t-SNE here takes at most {MAX_ROWS} (it would take many minutes and much memory in the browser); '
                         'use a Local Data Filter or a subset'}
    asked = perplexity
    if perplexity >= n:
        perplexity = max(1.0, (n - 1) / 3.0)
        notes.append(f'The perplexity {asked:g} is not below the number of rows ({n}): {perplexity:g} is used.')
    X = df[used].to_numpy(float)
    if standardize:
        X = (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)
    tsne = TSNE(n_components=dim, perplexity=perplexity, early_exaggeration=early, learning_rate=lr, max_iter=max_iter,
                init=init, random_state=seed, method='barnes_hut', angle=0.5, verbose=2)
    t0 = time.time()
    print(f'smui:progress tsne 0 {max_iter}', flush=True)
    with contextlib.redirect_stdout(_Progress(max_iter, sys.stdout)):
        E = tsne.fit_transform(X)
    seconds = time.time() - t0
    names = [f't-SNE {j + 1}' for j in range(dim)]
    out = {'rows': df.index.tolist(), 'coords': np.asarray(E, float).tolist(), 'names': names, 'columns': used, 'dropped': const,
           'n': n, 'n_left': int((~ok).sum()), 'dimension': dim, 'kl': float(tsne.kl_divergence_), 'iterations': int(tsne.n_iter_) + 1,
           'learning_rate': float(np.asarray(tsne.learning_rate_)), 'learning_rate_asked': lr, 'perplexity': float(perplexity),
           'perplexity_asked': float(asked), 'max_iter': max_iter, 'early_exaggeration': early, 'init': init, 'standardize': bool(standardize),
           'seed': seed, 'seconds': seconds, 'notes': notes}
    def head(extra=()):
        L = [code_head(table_name, ['from sklearn.manifold import TSNE', *extra])] + _keep_lines(table, rows, where)
        L.append(f'd = df[{J(cols)}].dropna()   # the rows with every column')
        if const:
            L.append(f'X = d[{J(used)}].to_numpy(float)   # without {", ".join(const)}: a single value in these rows')
        else:
            L.append('X = d.to_numpy(float)')
        if standardize:
            L.append('X = (X - X.mean(axis=0)) / X.std(axis=0, ddof=1)   # standardized')
        lr_text = J('auto') if lr == 'auto' else repr(lr)
        L.append(f'tsne = TSNE(n_components={dim}, perplexity={perplexity!r}, early_exaggeration={early!r}, learning_rate={lr_text}, '
                 f'max_iter={max_iter}, init={J(init)}, random_state={seed}, method="barnes_hut", angle=0.5)')
        L.append('E = tsne.fit_transform(X)   # the map: a row per row of d')
        return L
    L = head()
    L.append('print("kl", tsne.kl_divergence_, tsne.n_iter_ + 1, tsne.learning_rate_)   # the final KL divergence, iterations, learning rate')
    L.append(f'print(pd.DataFrame(E, index=d.index, columns={J(names)}).head())')
    out['code'] = '\n'.join(L)
    out['map_head'] = _dated('\n'.join(head(['import matplotlib.pyplot as plt'])), table)
    return out

