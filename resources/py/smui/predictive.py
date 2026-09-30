"""What the predictive-modeling platforms share.

Partition, Bootstrap Forest, Boosted Tree, Neural, K Nearest Neighbors,
Naive Bayes, Support Vector Machines, Gaussian Process and Model Screening
learn from some rows and are judged on others, as JMP's platforms are:

  a Validation column   0 or "Training": the rows a model learns from;
                        1 or "Validation": the rows that choose among
                        models (the size of a tree, the number of trees);
                        2 or "Test": rows kept out of both;
  a validation portion  a random share of the rows held back for
                        validation, drawn from a seed;
  neither               every row trains the model.

prepare() turns a table into what scikit-learn takes: the predictor matrix
(continuous columns as they are, one 0/1 column per level of a nominal or
ordinal one, or its level number), the response (a number, or the index
of a categorical level), the case weights and the set of every row. The
Measures of Fit, confusion matrices and ROC and lift curves are computed
here once, the same way for every platform, and P.code() writes the Python
that builds the same matrices from a CSV export of the table.

A module that uses scikit-learn registers its functions with
@api(name, packages=SK) and imports sklearn inside them: the page loads the
package on the first call, not at the start.
"""
import hashlib
import json
import math

import numpy as np
import pandas as pd

from . import data, models
from .registry import api
from .util import code_head

SETS = ('Training', 'Validation', 'Test')
SK = ('scikit-learn',)
_SET_NAMES = {'training': 0, 'train': 0, 'validation': 1, 'valid': 1, 'test': 2}


def level_label(v):
    """A level as the page shows it (2.0 as '2')."""
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return str(int(f)) if f.is_integer() else f'{f:.6g}'
    return str(v)


def rows_sig(rows):
    if rows is None:
        return 'all'
    a = np.asarray(rows, dtype=np.int64)
    return f'{len(a)}:{hashlib.blake2b(a.tobytes(), digest_size=10).hexdigest()}'


def cached(kind, table, rows, spec, build, keep=24):
    """build(), remembered for this table version, these rows and this spec
    (a fitted model: the profiler and the Save commands reuse it)."""
    key = models.model_key(kind, table, data.version(table), rows_sig(rows), spec)
    m = models.recall(key)
    if m is None:
        m = build()
        models.remember(key, m, keep=keep)
    return m


_KEPT = {}


def keep(key, obj, most=24):
    """A report's fitted model kept under the page's key (the report and its By group), so that rows added to the
    table later, or another open table, can be scored with the model as the report fitted it (the model cache
    above is keyed by the table's version, which new rows change). The oldest go past most."""
    if not key:
        return
    _KEPT.pop(key, None)
    _KEPT[key] = obj
    while len(_KEPT) > most:
        _KEPT.pop(next(iter(_KEPT)))


def kept(key):
    """The model keep() kept under key, or None."""
    return _KEPT.get(key) if key else None


def score_frame(P, table, rows=None):
    """The x columns of some rows of a table (another open table, or rows added later), as P encodes them, and the
    row numbers the model can take: every row whose factors the coding takes (with Informative Missing off, the
    rows with every factor). A missing column is an error that names it."""
    have = set(data.TABLES[table]['meta'])
    lack = [c for c in P.x if c not in have]
    if lack:
        raise ValueError(f'the table has no column {", ".join(lack)}: a model scores the columns it was fitted to, by name')
    frame = data.frame(table, P.x, rows, dropna=False)
    X, ok = P.encode(frame)
    return X[ok], np.asarray(frame.index, dtype=int)[ok]


def _pylit(v):
    return json.dumps(float(v)) if isinstance(v, (float, int, np.floating, np.integer)) and not isinstance(v, bool) else json.dumps(str(v))


class Prepared:
    """The data of one predictive model; see prepare()."""

    def __init__(self):
        self.table = None
        self.y = None
        self.x = []
        self.kind = None          # 'continuous' or 'categorical'
        self.index = None         # the table's row numbers, aligned with everything below
        self.X = None             # the predictor matrix (float)
        self.features = []        # the names of X's columns
        self.groups = {}          # x column name -> indices of its columns in X
        self.target = None        # float, or the level index
        self.levels = []          # the response's levels (values), in the table's order
        self.labels = []          # ... as text
        self.w = None             # weight x frequency, or None when every row counts once
        self.freq = None          # the frequencies alone (counts in confusion matrices), or None
        self.sets = None          # 0 Training, 1 Validation, 2 Test
        self.folds = None         # a K-fold Validation column: each row's fold, 0 to k - 1 (every row trains)
        self.k = 0                # ... and the number of folds (0: no folds)
        self.fold_values = []     # ... the column's value of each fold, in order
        self.coding = 'onehot'
        self.missing = 'informative'
        self.enc = []             # how each x column became columns of X
        self.notes = []           # what was left out, for the report
        self.spec = {}

    # ---- the sets
    def mask(self, k):
        return self.sets == k

    def has(self, k):
        return bool(np.any(self.sets == k))

    def train(self):
        return self.sets == 0

    def weights(self, m=None):
        w = np.ones(len(self.index)) if self.w is None else self.w
        return w if m is None else w[m]

    def counts(self, m=None):
        f = np.ones(len(self.index)) if self.freq is None else self.freq
        return f if m is None else f[m]

    # ---- encoding new rows (a whole table, or the profiler's settings)
    def encode(self, frame):
        """X for a DataFrame with the x columns (categorical ones as values
        of the table). Returns (X, ok): rows with a missing value that the
        coding cannot take (missing='drop') are not ok and get zeros."""
        n = len(frame)
        cols = []
        ok = np.ones(n, dtype=bool)
        for e in self.enc:
            s = frame[e['name']]
            if e['type'] == 'continuous':
                v = pd.to_numeric(s, errors='coerce').to_numpy(float)
                miss = ~np.isfinite(v)
                if self.missing == 'informative':
                    cols.append(np.where(miss, e['fill'], v))
                    if e['indicator']:
                        cols.append(miss.astype(float))
                else:
                    ok &= ~miss
                    cols.append(np.where(miss, 0.0, v))
            else:
                vals = list(s.astype(object))
                idx = np.array([_level_at(e['levels'], v) for v in vals], dtype=int)
                miss = idx == -1
                unknown = idx == -2
                if self.missing != 'informative':
                    ok &= ~miss
                if self.coding == 'ordinal':
                    col = idx.astype(float)
                    col[unknown] = -1.0
                    cols.append(col)
                else:
                    for j in range(len(e['levels'])):
                        cols.append((idx == j).astype(float))
                    if e['indicator']:
                        cols.append(miss.astype(float))
        X = np.column_stack(cols) if cols else np.zeros((n, 0))
        return X, ok

    def frame_of(self, settings):
        """The profiler's settings ({x name: value}) as a DataFrame."""
        return pd.DataFrame({e['name']: [s.get(e['name']) for s in settings] for e in self.enc})

    def encode_settings(self, settings):
        return self.encode(self.frame_of(settings))[0]

    def factors(self):
        """The factors of the Prediction Profiler: each x column's range and
        mean, or its levels."""
        out = []
        for e in self.enc:
            if e['type'] == 'continuous':
                out.append({'name': e['name'], 'type': 'continuous', 'min': e['min'], 'max': e['max'], 'mean': e['mean']})
            else:
                out.append({'name': e['name'], 'type': 'categorical', 'levels': list(e['levels']), 'labels': [level_label(v) for v in e['levels']]})
        return out

    def proba(self, model, X):
        """predict_proba for every level of the response, in the table's
        order: a level the training rows lack gets probability 0."""
        p = np.asarray(model.predict_proba(X), dtype=float)
        out = np.zeros((p.shape[0], len(self.levels)))
        for j, c in enumerate(model.classes_):
            out[:, int(c)] = p[:, j]
        return out

    # ---- the whole table (Save Predicteds, Save Probabilities)
    def all_rows(self):
        """X for every row of the table (excluded rows too, as a formula
        column would compute them), and the row numbers that are ok."""
        frame = data.frame(self.table, self.x, None, dropna=False)
        X, ok = self.encode(frame)
        return X[ok], np.asarray(frame.index, dtype=int)[ok]

    # ---- the code under the report
    def code(self, table_name, rows=None, extra_imports=()):
        """Lines that read the exported table and build d, X, y, w and sets
        exactly as the report does. The table is read with an empty field as
        its only missing value: File > Export CSV writes a missing value so,
        and pandas' default would take a level named None, NA or null for
        missing too (the Churn example's internet has the level None)."""
        L = [code_head(table_name, list(extra_imports))]
        L[0] = L[0].replace('float_precision="round_trip")   # the table, as File > Export CSV writes it',
                            'float_precision="round_trip", keep_default_na=False, na_values=[""])   # the table, as File > Export CSV writes it (an empty field is missing)')
        n_all = data.TABLES[self.table]['n'] if self.table in data.TABLES else None
        if rows is not None:
            keep = [int(r) for r in rows]
            if n_all is not None and len(keep) > n_all / 2:
                drop = sorted(set(range(n_all)) - set(keep))
                if drop:
                    L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
            else:
                L.append(f'df = df.loc[{keep}]   # the rows of the report')
        sp = self.spec
        cols = list(dict.fromkeys([self.y] + list(self.x) + [c for c in (sp.get('weight'), sp.get('freq'), sp.get('validation')) if c]))
        L.append(f'd = df[{json.dumps(cols)}]')
        L.append(f'd = d[d[{json.dumps(self.y)}].notna()]   # rows with a response')
        for c in (sp.get('weight'), sp.get('freq')):
            if c:
                L.append(f'd = d[d[{json.dumps(c)}] > 0]   # a missing or non-positive {"weight" if c == sp.get("weight") else "frequency"} leaves the row out')
        v = sp.get('validation')
        if v:
            L.append(f'd = d[d[{json.dumps(v)}].notna()]   # rows with a validation value')
        if self.missing != 'informative':
            L.append(f'd = d.dropna(subset={json.dumps(list(self.x))})   # rows with every predictor')
        if v and self.folds is not None:
            numeric = data.meta(self.table, v).get('dataType') == 'numeric'
            L.append(f'fold_values = {json.dumps(self.fold_values)}   # the folds of the Validation column, in order')
            src = f'pd.to_numeric(d[{json.dumps(v)}], errors="coerce")' if numeric else f'd[{json.dumps(v)}].astype(str)'
            L.append(f'folds = pd.Categorical({src}, categories=fold_values).codes   # each row\'s fold, 0 to {self.k - 1}')
            L.append('sets = np.zeros(len(d), dtype=int)   # every row trains; the folds crossvalidate')
        elif v:
            if data.meta(self.table, v).get('dataType') == 'numeric':
                L.append(f'sets = d[{json.dumps(v)}].to_numpy(int)   # 0 training, 1 validation, 2 test')
            else:
                L.append(f'names = {json.dumps(_SET_NAMES)}')
                L.append(f'sets = d[{json.dumps(v)}].str.strip().str.lower().map(names).to_numpy(int)   # 0 training, 1 validation, 2 test')
        else:
            por = sp.get('portion') or 0
            if por:
                L.append(f'rng = np.random.default_rng({int(sp["seed"])})   # the validation portion')
                L.append(f'sets = np.zeros(len(d), dtype=int); sets[rng.permutation(len(d))[:{int(round(por * len(self.index)))}]] = 1')
            else:
                L.append('sets = np.zeros(len(d), dtype=int)   # every row trains the model')
        # the predictors
        L.append('')
        L.append('def encode(d):')
        L.append(f'    """The predictors as the report codes them: {self._coding_words()}."""')
        L.append('    cols = []')
        for e in self.enc:
            nm = json.dumps(e['name'])
            if e['type'] == 'continuous':
                if self.missing == 'informative':
                    L.append(f'    cols.append(pd.to_numeric(d[{nm}], errors="coerce").fillna({e["fill"]!r}).to_numpy(float))')
                    if e['indicator']:
                        L.append(f'    cols.append(pd.to_numeric(d[{nm}], errors="coerce").isna().to_numpy(float))   # {e["name"]} Missing')
                else:
                    L.append(f'    cols.append(d[{nm}].to_numpy(float))')
            else:
                lv = '[' + ', '.join(_pylit(v) for v in e['levels']) + ']'
                numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in e['levels'])
                src = f'pd.to_numeric(d[{nm}], errors="coerce")' if numeric else f'd[{nm}].astype(object)'
                if self.coding == 'ordinal':
                    L.append(f'    cols.append(pd.Categorical({src}, categories={lv}).codes.astype(float))   # the level number, -1 when missing')
                else:
                    L.append(f'    cols += [({src} == v).to_numpy(float) for v in {lv}]   # one column per level')
                    if e['indicator']:
                        L.append(f'    cols.append(d[{nm}].isna().to_numpy(float))   # {e["name"]} Missing')
        L.append('    return np.column_stack(cols)')
        L.append('')
        L.append('X = encode(d)')
        if self.kind == 'categorical':
            lv = '[' + ', '.join(_pylit(v) for v in self.levels) + ']'
            numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in self.levels)
            src = f'pd.to_numeric(d[{json.dumps(self.y)}], errors="coerce")' if numeric else f'd[{json.dumps(self.y)}].astype(object)'
            L.append(f'levels = {lv}')
            L.append(f'y = pd.Categorical({src}, categories=levels).codes   # the index of the level')
        else:
            L.append(f'y = d[{json.dumps(self.y)}].to_numpy(float)')
        wparts = [f'd[{json.dumps(c)}].to_numpy(float)' for c in (sp.get('weight'), sp.get('freq')) if c]
        L.append(f'w = {" * ".join(wparts)}' if wparts else 'w = None   # every row counts once')
        L.append('train = sets == 0')
        return L

    def _coding_words(self):
        parts = []
        if any(e['type'] == 'continuous' for e in self.enc):
            parts.append('continuous as they are' + (', a missing value as the training mean with a 0/1 Missing column' if self.missing == 'informative' else ''))
        if any(e['type'] != 'continuous' for e in self.enc):
            parts.append('a categorical one as its level number' if self.coding == 'ordinal' else 'a 0/1 column per level of a categorical one')
        return '; '.join(parts) or 'none'


def _level_at(levels, v):
    """The index of v among the levels; -1 when missing, -2 when unknown."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return -1
    for j, lv in enumerate(levels):
        if lv == v:
            return j
        if isinstance(lv, (float, np.floating)) and isinstance(v, (int, float, np.integer, np.floating)) and float(lv) == float(v):
            return j
        if isinstance(lv, (float, np.floating)) and isinstance(v, str):
            try:
                if float(v) == float(lv):
                    return j
            except ValueError:
                pass
    return -2


MAX_FOLDS = 50


def validation_codes(table, validation, raw):
    """A Validation column's rows as ('sets', each row's set: 0 training, 1 validation, 2 test, -1 none, []) or,
    when it holds more than three distinct values (Make Validation Column's K Fold), as ('folds', each row's fold
    from 0, -1 none, the fold values in order): whole numbers for a numeric column, the levels in the column's
    order for a character one."""
    m = data.meta(table, validation)
    if m.get('dataType') == 'numeric':
        v = pd.to_numeric(raw.astype(object), errors='coerce').to_numpy(float)
        ok = np.isfinite(v)
        distinct = np.unique(v[ok])
        if 3 < len(distinct) <= MAX_FOLDS and np.all(distinct == np.round(distinct)):
            fold = np.full(len(v), -1)
            fold[ok] = np.searchsorted(distinct, v[ok])
            return 'folds', fold, [float(x) for x in distinct]
        bad = sorted(set(distinct.tolist()) - {0.0, 1.0, 2.0})
        if bad:
            raise ValueError(f'{validation}: a Validation column holds 0 (training), 1 (validation) and 2 (test), or 4 to {MAX_FOLDS} whole numbers, one per fold; '
                             f'it has {", ".join(level_label(b) for b in bad[:5])}')
        return 'sets', np.where(ok, v, -1).astype(int), []
    vals = raw.astype(object).tolist()
    miss = [vv is None or (isinstance(vv, float) and math.isnan(vv)) for vv in vals]
    names = [None if mm else str(vv) for vv, mm in zip(vals, miss)]
    distinct = list(dict.fromkeys(nm for nm in names if nm is not None))
    named = any(nm.strip().lower() in _SET_NAMES for nm in distinct)     # Training, Validation or Test among them: sets
    if not named and 3 < len(distinct) <= MAX_FOLDS:
        order = [str(c) for c in raw.cat.categories if str(c) in distinct] if isinstance(raw.dtype, pd.CategoricalDtype) else sorted(distinct)
        at = {v_: i for i, v_ in enumerate(order)}
        return 'folds', np.array([-1 if nm is None else at[nm] for nm in names], dtype=int), order
    s = np.array([-1 if nm is None else _SET_NAMES.get(nm.strip().lower(), -9) for nm in names], dtype=int)
    if (s == -9).any():
        odd = sorted({nm for nm, k in zip(names, s) if k == -9})[:5]
        raise ValueError(f'{validation}: a Validation column holds Training, Validation and Test (or 0, 1, 2), or 4 to {MAX_FOLDS} values, one per fold; it has {", ".join(odd)}')
    return 'sets', s, []


def fold_masks(P):
    """K-fold crossvalidation by a K-fold Validation column (P.folds): [(fit rows, held-out rows), ...], one
    pair of boolean masks over P's rows per fold, in the folds' order. [] without folds. The helper the
    platforms that crossvalidate (Partition, Neural, Generalized Regression, Model Screening, K Nearest
    Neighbors, Support Vector Machines, Naive Bayes) use when a Validation column gives the folds."""
    if P.folds is None:
        return []
    return [(P.folds != j, P.folds == j) for j in range(P.k)]


def crossvalidate(P, fit_predict, folds=None):
    """Out-of-fold predictions and measures: fit_predict(fit_rows) fits the model to the rows of the boolean mask
    fit_rows and returns its prediction of every row of P (a vector, or an n x levels probability matrix); each fold
    is held out once (folds: [(fit rows, held rows)], P's own folds by default). Returns {'oof': each row predicted
    by the model fitted without its fold, 'folds': the Measures of Fit of each held-out fold, 'measures': their
    weighted mean (the rows of every fold together: measures() of the oof predictions)}."""
    folds = fold_masks(P) if folds is None else folds
    if not folds:
        raise ValueError('no folds: a Validation column with more than three values gives them')
    oof = None
    per = []
    import copy as _copy
    for j, (fit_rows, held) in enumerate(folds):
        f = np.asarray(fit_predict(fit_rows), dtype=float)
        if oof is None:
            oof = np.zeros_like(f)
        oof[held] = f[held]
        Q = _copy.copy(P)
        Q.sets = np.where(held, 1, np.where(fit_rows, 0, -1))
        per.append({'fold': j, **{k: v for k, v in (next((r for r in measures(Q, f) if r['set'] == 'Validation'), None) or {}).items() if k != 'set'}})
    Q = _copy.copy(P)
    Q.sets = np.zeros(len(P.index), dtype=int)
    Q.sets[~np.any([h for _, h in folds], axis=0)] = -1
    whole = next((r for r in measures(Q, oof)), None)
    if whole:
        whole = {**whole, 'set': 'Crossvalidation'}
    return {'oof': oof, 'folds': per, 'measures': whole}


def prepare(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
            missing='informative', coding='onehot', categorical_y=None):
    """The response, predictors, weights and sets of a predictive model.

    y: the response column (continuous, or nominal/ordinal for a
    classification); x: the predictor columns; weight, freq: optional case
    weight and frequency columns; validation: an optional Validation column
    (0/1/2 or Training/Validation/Test; with more than three distinct values
    it holds K folds: P.folds, P.k, fold_masks(P), crossvalidate(P, ...), and
    every row trains), or portion (0 to 1): a random share of rows for
    validation, drawn with seed; missing: 'informative' (a missing continuous value is the
    training mean plus a 0/1 Missing column; a missing level is a level of
    its own) or 'drop' (rows missing a predictor are left out); coding:
    'onehot' or 'ordinal' for categorical predictors. categorical_y: force
    the response's kind (None: its modeling type decides).
    """
    if not y:
        raise ValueError('choose a Y, Response')
    x = [c for c in dict.fromkeys(x or []) if c and c != y]
    if not x:
        raise ValueError('choose at least one X, Factor')
    for c in (weight, freq, validation):
        if c and (c == y or c in x):
            raise ValueError(f'{c} cannot be both a role column and a response or factor')
    P = Prepared()
    P.table, P.y, P.x = table, y, list(x)
    P.coding, P.missing = coding, missing
    P.spec = {'weight': weight, 'freq': freq, 'validation': validation, 'portion': float(portion or 0), 'seed': seed}
    cat_y = data.is_categorical(table, y) if categorical_y is None else bool(categorical_y)
    P.kind = 'categorical' if cat_y else 'continuous'
    names = list(dict.fromkeys([y] + P.x + [c for c in (weight, freq, validation) if c]))
    df = data.frame(table, names, rows, dropna=False)
    n0 = len(df)
    # (1) a response
    ys = df[y]
    keep = np.array(ys.notna(), dtype=bool)
    if not cat_y:
        yv = pd.to_numeric(ys, errors='coerce').to_numpy(float)
        keep &= np.isfinite(yv)
    if (~keep).sum():
        P.notes.append(f'{int((~keep).sum())} rows with no {y} are left out.')
    df = df[keep]
    # (2) weights and frequencies
    w = None
    f = None
    for c, kind in ((weight, 'weight'), (freq, 'freq')):
        if not c:
            continue
        v = pd.to_numeric(df[c], errors='coerce').to_numpy(float)
        ok = np.isfinite(v) & (v > 0)
        if (~ok).sum():
            P.notes.append(f'{int((~ok).sum())} rows with a missing or non-positive {c} are left out.')
        df = df[ok]
        v = v[ok]
        if w is not None:
            w = w[ok]
        if f is not None:
            f = f[ok]
        w = v if w is None else w * v
        if kind == 'freq':
            f = v
    # (3) the validation column: sets, or K folds (more than three distinct values)
    sets = None
    folds = None
    if validation:
        kind, s, fvals = validation_codes(table, validation, df[validation])
        if (s < 0).sum():
            P.notes.append(f'{int((s < 0).sum())} rows with no {validation} value are left out.')
        ok = s >= 0
        df, s = df[ok], s[ok]
        w = None if w is None else w[ok]
        f = None if f is None else f[ok]
        if kind == 'folds':
            folds, sets = s, np.zeros(len(s), dtype=int)
            P.fold_values = fvals
            P.notes.append(f'{validation} holds {len(fvals)} folds: every row trains, and crossvalidation holds out one fold at a time.')
        else:
            sets = s
            if not np.any(sets == 0):
                raise ValueError(f'{validation} leaves no training rows (value 0 or Training)')
    # (4) rows missing a predictor, when they are left out
    if missing != 'informative':
        ok = np.array(df[P.x].notna().all(axis=1), dtype=bool)
        for c in P.x:
            if not data.is_categorical(table, c):
                ok &= np.isfinite(pd.to_numeric(df[c], errors='coerce').to_numpy(float))
        if (~ok).sum():
            P.notes.append(f'{int((~ok).sum())} rows missing a factor are left out (Informative Missing is off).')
        df = df[ok]
        w = None if w is None else w[ok]
        f = None if f is None else f[ok]
        sets = None if sets is None else sets[ok]
        folds = None if folds is None else folds[ok]
    n = len(df)
    if n == 0:
        raise ValueError('no rows to fit: every row misses the response, a weight or a factor')
    # (5) the validation portion (not with a Validation column's sets or folds)
    if sets is None:
        por = float(portion or 0)
        sets = np.zeros(n, dtype=int)
        if por > 0:
            if not 0 < por < 1:
                raise ValueError('the Validation Portion is a share between 0 and 1')
            if seed is None:
                raise ValueError('a validation portion needs a random seed')
            k = int(round(por * n))
            if k >= n:
                raise ValueError('the Validation Portion leaves no training rows')
            sets[np.random.default_rng(int(seed)).permutation(n)[:k]] = 1
    P.sets = sets.astype(int)
    if folds is not None:
        P.folds = folds.astype(int)
        P.k = len(P.fold_values)
    P.index = np.asarray(df.index, dtype=int)
    P.w = w
    P.freq = f
    tr = P.sets == 0
    # the response
    if cat_y:
        s = df[y]
        cats = list(s.cat.categories) if isinstance(s.dtype, pd.CategoricalDtype) else sorted({v for v in s if v is not None})
        codes = s.cat.codes.to_numpy() if isinstance(s.dtype, pd.CategoricalDtype) else np.array([cats.index(v) for v in s])
        present = [j for j in range(len(cats)) if np.any(codes == j)]
        remap = {j: i for i, j in enumerate(present)}
        P.levels = [cats[j].item() if hasattr(cats[j], 'item') else cats[j] for j in present]
        P.labels = [level_label(v) for v in P.levels]
        P.target = np.array([remap[c] for c in codes], dtype=int)
        if len(P.levels) < 2:
            raise ValueError(f'{y} has one level in these rows: nothing to classify')
    else:
        P.target = pd.to_numeric(df[y], errors='coerce').to_numpy(float)
    # the predictors
    for c in P.x:
        s = df[c]
        if data.is_categorical(table, c):
            cats = list(s.cat.categories) if isinstance(s.dtype, pd.CategoricalDtype) else sorted({v for v in s if v is not None})
            codes = s.cat.codes.to_numpy() if isinstance(s.dtype, pd.CategoricalDtype) else None
            present = [cats[j] for j in range(len(cats)) if codes is None or np.any(codes == j)]
            levels = [v.item() if hasattr(v, 'item') else v for v in present]
            indicator = missing == 'informative' and bool(s.isna().any())
            P.enc.append({'name': c, 'type': 'categorical', 'levels': levels, 'indicator': indicator})
        else:
            v = pd.to_numeric(s, errors='coerce').to_numpy(float)
            fin = np.isfinite(v)
            if not fin.any():
                raise ValueError(f'{c} has no values in these rows')
            trv = v[tr & fin]
            fill = float(np.mean(trv)) if len(trv) else float(np.mean(v[fin]))
            indicator = missing == 'informative' and bool((~fin).any())
            P.enc.append({'name': c, 'type': 'continuous', 'fill': fill, 'indicator': indicator,
                          'min': float(np.min(v[fin])), 'max': float(np.max(v[fin])), 'mean': float(np.mean(v[fin]))})
    P.X, _ = P.encode(df[P.x])
    # the names of X's columns and the x column each came from
    j = 0
    for e in P.enc:
        idx = []
        if e['type'] == 'continuous':
            P.features.append(e['name']); idx.append(j); j += 1
            if e['indicator'] and missing == 'informative':
                P.features.append(f'{e["name"]} Missing'); idx.append(j); j += 1
        elif coding == 'ordinal':
            P.features.append(e['name']); idx.append(j); j += 1
        else:
            for lv in e['levels']:
                P.features.append(f'{e["name"]}[{level_label(lv)}]'); idx.append(j); j += 1
            if e['indicator']:
                P.features.append(f'{e["name"]}[Missing]'); idx.append(j); j += 1
        P.groups[e['name']] = idx
    if n0 and not tr.any():
        raise ValueError('no training rows')
    return P


# ---------------------------------------------------------------------------
# how well a model predicts, per set
# ---------------------------------------------------------------------------

def _clip(p):
    return np.clip(np.asarray(p, dtype=float), 1e-15, 1.0)


def measures(P, fitted, decided=None):
    """The Measures of Fit of each set present. decided: each row's called level when it is not simply the most
    probable one (K Nearest Neighbors breaks a tied vote at random), for the misclassification rate.

    fitted: the prediction of every row of P (a vector for a continuous
    response, an n x levels probability matrix for a categorical one).
    Continuous: RSquare (1 - SSE/SST about the set's own mean), RASE (root
    average squared error), Mean Abs Dev, -LogLikelihood (normal, with the
    variance SSE/N), SSE and N (the sum of the weights). Categorical:
    Entropy RSquare (1 - LL/LL0, LL0 the training shares of the levels),
    Generalized RSquare (Nagelkerke's), Mean -Log p, RASE and Mean Abs Dev
    of 1 - p(actual level), the Misclassification Rate (most likely level
    not the actual one), -LogLikelihood and N; AUC for two levels.
    """
    out = []
    fitted = np.asarray(fitted, dtype=float)
    if P.kind == 'categorical':
        wt = P.weights(P.train())
        share = np.array([wt[P.target[P.train()] == j].sum() for j in range(len(P.levels))]) / wt.sum()
    for k in range(3):
        m = P.mask(k)
        if not m.any():
            continue
        w = P.weights(m)
        N = float(w.sum())
        row = {'set': SETS[k], 'n': N}
        if P.kind == 'continuous':
            y, f = P.target[m], fitted[m]
            r = y - f
            sse = float(np.sum(w * r * r))
            yb = float(np.sum(w * y) / N)
            sst = float(np.sum(w * (y - yb) ** 2))
            row.update({'rsquare': 1 - sse / sst if sst > 0 else None, 'rase': math.sqrt(sse / N), 'mad': float(np.sum(w * np.abs(r)) / N),
                        'neg_loglik': 0.5 * N * (math.log(2 * math.pi * sse / N) + 1) if sse > 0 else None, 'sse': sse})
            row.update(error_measures(y, f, w))
        else:
            y = P.target[m]
            p = fitted[m]
            pt = _clip(p[np.arange(len(y)), y])
            ll = float(np.sum(w * np.log(pt)))
            ll0 = float(np.sum(w * np.log(_clip(share[y]))))
            er2 = 1 - ll / ll0 if ll0 < 0 else None
            den = 1 - math.exp(2 * ll0 / N)
            gr2 = (1 - math.exp(2 * (ll0 - ll) / N)) / den if den > 0 else None
            miss = (np.argmax(p, axis=1) if decided is None else np.asarray(decided, dtype=int)[m]) != y
            row.update({'entropy_rsquare': er2, 'generalized_rsquare': gr2, 'mean_neg_log_p': -ll / N,
                        'rase': math.sqrt(float(np.sum(w * (1 - pt) ** 2)) / N), 'mad': float(np.sum(w * (1 - pt)) / N),
                        'misclassification': float(np.sum(w * miss) / N), 'neg_loglik': -ll})
            if len(P.levels) == 2:
                row['auc'] = _auc(p[:, 1], y == 1, w)
        out.append(row)
    return out


def weighted_median(v, w=None):
    """The median of v with case weights w: the value where the cumulative weight of the sorted values reaches half
    the total, the mean of the two values beside it when it reaches half exactly (as the median of the rows
    repeated Freq times)."""
    v = np.asarray(v, dtype=float)
    w = np.ones(len(v)) if w is None else np.asarray(w, dtype=float)
    if not len(v):
        return None
    o = np.argsort(v, kind='mergesort')
    v, c = v[o], np.cumsum(w[o])
    half = c[-1] / 2
    i = int(np.searchsorted(c, half))
    if c[i] == half and i + 1 < len(v):
        return float((v[i] + v[i + 1]) / 2)
    return float(v[i])


def error_measures(y, f, w=None):
    """The more measures of a continuous prediction, beyond JMP's (optional columns of Measures of Fit): the Mean
    Error (actual less predicted: a bias), MAPE and MPE (the mean absolute and the mean percentage error, 100
    (actual - predicted) / actual, over the rows whose actual value is not 0) and the Median Absolute Error; each
    row weighted by its Weight x Freq."""
    y, f = np.asarray(y, dtype=float), np.asarray(f, dtype=float)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    r = y - f
    N = float(w.sum())
    nz = y != 0
    wz = float(w[nz].sum())
    return {'me': float(np.sum(w * r) / N) if N > 0 else None,
            'mape': float(100 * np.sum(w[nz] * np.abs(r[nz] / y[nz])) / wz) if wz > 0 else None,
            'mpe': float(100 * np.sum(w[nz] * (r[nz] / y[nz])) / wz) if wz > 0 else None,
            'medae': weighted_median(np.abs(r), w)}


def naive_fitted(P):
    """The Naive model's prediction of every row: the training rows' (weighted) mean, or their shares of the levels
    (the most likely level is then the majority's)."""
    tr = P.train()
    wt = P.weights(tr)
    if P.kind == 'continuous':
        return np.full(len(P.index), float(np.sum(wt * P.target[tr]) / wt.sum()))
    share = np.array([wt[P.target[tr] == j].sum() for j in range(len(P.levels))]) / wt.sum()
    return np.tile(share, (len(P.index), 1))


def measure_columns(kind):
    """The report table's columns for measures()."""
    if kind == 'continuous':
        return [{'key': 'set', 'label': 'Set', 'fmt': 'text'}, {'key': 'rsquare', 'label': 'RSquare'}, {'key': 'rase', 'label': 'RASE'},
                {'key': 'mad', 'label': 'Mean Abs Dev'}, {'key': 'neg_loglik', 'label': '-LogLikelihood'}, {'key': 'sse', 'label': 'SSE'},
                {'key': 'n', 'label': 'N'},
                {'key': 'me', 'label': 'Mean Error', 'hidden': True}, {'key': 'mape', 'label': 'MAPE', 'hidden': True},
                {'key': 'mpe', 'label': 'MPE', 'hidden': True}, {'key': 'medae', 'label': 'Median Abs Error', 'hidden': True}]
    return [{'key': 'set', 'label': 'Set', 'fmt': 'text'}, {'key': 'entropy_rsquare', 'label': 'Entropy RSquare'},
            {'key': 'generalized_rsquare', 'label': 'Generalized RSquare'}, {'key': 'mean_neg_log_p', 'label': 'Mean -Log p'},
            {'key': 'rase', 'label': 'RASE'}, {'key': 'mad', 'label': 'Mean Abs Dev'}, {'key': 'misclassification', 'label': 'Misclassification Rate'},
            {'key': 'auc', 'label': 'AUC'}, {'key': 'n', 'label': 'N'}]


def _auc(score, pos, w):
    """The area under the ROC curve (ties count half), weighted."""
    score = np.asarray(score, dtype=float)
    pos = np.asarray(pos, dtype=bool)
    w = np.asarray(w, dtype=float)
    P_, N_ = w[pos].sum(), w[~pos].sum()
    if P_ <= 0 or N_ <= 0:
        return None
    # each positive row beats the negative rows scored below it, and half
    # of those scored the same
    u, inv = np.unique(score, return_inverse=True)
    pw = np.bincount(inv, weights=np.where(pos, w, 0.0), minlength=len(u))
    nw = np.bincount(inv, weights=np.where(pos, 0.0, w), minlength=len(u))
    below = np.cumsum(nw) - nw
    return float(np.sum(pw * (below + 0.5 * nw)) / (P_ * N_))


def confusion(P, fitted, decided=None):
    """Per set: counts of actual (rows) by most likely level (columns; decided when given),
    each row counted by its Weight x Freq (as JMP counts them: a weight
    that undoes oversampling undoes it here too)."""
    out = []
    fitted = np.asarray(fitted, dtype=float)
    L = len(P.levels)
    for k in range(3):
        m = P.mask(k)
        if not m.any():
            continue
        y, f = P.target[m], P.weights(m)
        pred = np.argmax(fitted[m], axis=1) if decided is None else np.asarray(decided, dtype=int)[m]
        mat = np.zeros((L, L))
        np.add.at(mat, (y, pred), f)
        out.append({'set': SETS[k], 'levels': list(P.labels), 'matrix': mat.tolist()})
    return out


def _thin(n, most):
    if n <= most:
        return np.arange(n)
    return np.unique(np.round(np.linspace(0, n - 1, most)).astype(int))


def roc(P, fitted, most=400):
    """Per set and level: the ROC curve of the level against the others by
    its probability (1 - specificity, sensitivity), its AUC, and the point
    where Sensitivity - (1 - Specificity), Youden's J, is largest (JMP's
    ROC Table stars it; its cut, 'best_cut', is the probability there).
    Each row counts by its Weight x Freq."""
    out = []
    fitted = np.asarray(fitted, dtype=float)
    for k in range(3):
        m = P.mask(k)
        if not m.any():
            continue
        y, p, w = P.target[m], fitted[m], P.weights(m)
        for j, lab in enumerate(P.labels):
            pos = y == j
            Pw, Nw = w[pos].sum(), w[~pos].sum()
            if Pw <= 0 or Nw <= 0:
                continue
            order = np.argsort(-p[:, j], kind='mergesort')
            s = p[order, j]
            tp = np.cumsum(np.where(pos[order], w[order], 0.0))
            fp = np.cumsum(np.where(pos[order], 0.0, w[order]))
            last = np.r_[s[1:] != s[:-1], True]           # the end of each run of equal scores
            fpr = np.r_[0.0, fp[last] / Nw]
            tpr = np.r_[0.0, tp[last] / Pw]
            keep = _thin(len(fpr), most)
            b = youden(cut_table(p[:, j], pos, w))
            out.append({'set': SETS[k], 'level': lab, 'fpr': fpr[keep].tolist(), 'tpr': tpr[keep].tolist(),
                        'auc': _auc(p[:, j], pos, w), 'best': b})
    return out


def lift(P, fitted, most=300):
    """Per set and level: the lift curve (the share of rows taken, highest
    probability first, and the rate of the level among them over its rate
    in the set) and the cumulative gains (the share of the level's rows
    among those taken), each row counted by its Weight x Freq."""
    out = []
    fitted = np.asarray(fitted, dtype=float)
    for k in range(3):
        m = P.mask(k)
        if not m.any():
            continue
        y, p, w = P.target[m], fitted[m], P.weights(m)
        tot = w.sum()
        for j, lab in enumerate(P.labels):
            pos = y == j
            base = w[pos].sum() / tot
            if base <= 0:
                continue
            order = np.argsort(-p[:, j], kind='mergesort')
            cw = np.cumsum(w[order])
            hits = np.cumsum(np.where(pos[order], w[order], 0.0))
            portion = cw / tot
            lift_ = (hits / cw) / base
            keep = _thin(len(portion), most)
            out.append({'set': SETS[k], 'level': lab, 'portion': portion[keep].tolist(), 'lift': lift_[keep].tolist(),
                        'gains': (hits / hits[-1])[keep].tolist(), 'base': float(base),
                        'deciles': lift_table(p[:, j], pos, w)})
    return out


def lift_table(p, pos, w=None, bins=10):
    """The decile lift table of one level: the rows taken highest probability
    first (equal ones in the table's order, as the lift curve takes them)
    and cut into bins of equal weight, each row in the bin its middle falls
    in; per bin its weight, the level's weight in it, the level's rate, the
    lift (that rate over the level's rate in the set), and cumulatively the
    rate, the lift and the gains (the share of the level's rows taken)."""
    p = np.asarray(p, dtype=float)
    pos = np.asarray(pos, dtype=bool)
    w = np.ones(len(p)) if w is None else np.asarray(w, dtype=float)
    o = np.argsort(-p, kind='mergesort')
    wo, ho = w[o], np.where(pos[o], w[o], 0.0)
    cw = np.cumsum(wo)
    tot = float(cw[-1]) if len(cw) else 0.0
    hit_tot = float(ho.sum())
    if not (tot > 0 and hit_tot > 0):
        return []
    base = hit_tot / tot
    b = np.minimum(bins - 1, np.floor(bins * (cw - wo / 2) / tot).astype(int))   # the bin each row's middle falls in
    rows, c_n, c_hit = [], 0.0, 0.0
    for k in range(bins):
        mk = b == k
        n_k, hit_k = float(wo[mk].sum()), float(ho[mk].sum())
        c_n += n_k
        c_hit += hit_k
        rate = hit_k / n_k if n_k > 0 else None
        crate = c_hit / c_n if c_n > 0 else None
        rows.append({'bin': k + 1, 'n': n_k, 'hits': hit_k, 'rate': rate, 'lift': rate / base if rate is not None else None,
                     'cum_rate': crate, 'cum_lift': crate / base if crate is not None else None, 'gains': c_hit / hit_tot,
                     'p_max': float(p[o][mk].max()) if mk.any() else None, 'p_min': float(p[o][mk].min()) if mk.any() else None})
    return rows


# ---------------------------------------------------------------------------
# every cut on a level's probability: the Decision Threshold, the ROC Table,
# the best point of the ROC curve and the profit of a threshold
# ---------------------------------------------------------------------------
# A cut table holds, for one level and one set, every distinct probability of
# the level (highest first) and the weight of the level's rows (tp) and of the
# other rows (fp) whose probability is at least it: the counts at any
# threshold t come from it (counts_at), and every rate from the counts
# (rates_at). smui-predict.js computes the same from the same table, so a
# threshold typed or dragged in the page needs no call to the engine; the code
# under the Decision Threshold report defines these three functions (their
# source travels in the report's data) and gives the same digits.

def cut_table(p, pos, w=None):
    """The weighted counts at every cut on p, one level's probability: a row is called the level when its p is at
    least the cut. p: the distinct values of p, highest first; tp, fp: the weight of the level's rows and of the
    other rows at or above each; pos, neg: the weight of each in all. w: each row's Weight x Freq (None: 1).
    Rows with no probability (not finite) are left out."""
    p = np.asarray(p, dtype=float)
    pos = np.asarray(pos, dtype=bool)
    w = np.ones(len(p)) if w is None else np.asarray(w, dtype=float)
    ok = np.isfinite(p)
    p, pos, w = p[ok], pos[ok], w[ok]
    o = np.argsort(-p, kind='mergesort')
    s = p[o]
    tp = np.cumsum(np.where(pos[o], w[o], 0.0))
    fp = np.cumsum(np.where(pos[o], 0.0, w[o]))
    last = np.r_[s[1:] != s[:-1], True] if len(s) else np.zeros(0, dtype=bool)
    return {'p': s[last].tolist(), 'tp': tp[last].tolist(), 'fp': fp[last].tolist(),
            'pos': float(tp[-1]) if len(s) else 0.0, 'neg': float(fp[-1]) if len(s) else 0.0}


def counts_at(cut, t):
    """(tp, fp, fn, tn) of a cut table at the threshold t: the rows whose probability is at least t are called the
    level; tp and fp of them are the level's rows and the others', fn and tn of the rest."""
    k = int(np.searchsorted(-np.asarray(cut['p'], dtype=float), -float(t), side='right'))   # how many values are >= t
    tp = cut['tp'][k - 1] if k else 0.0
    fp = cut['fp'][k - 1] if k else 0.0
    return tp, fp, cut['pos'] - tp, cut['neg'] - fp


def rates_at(tp, fp, fn, tn):
    """The Decision Threshold's measures of the counts at a threshold (None where a share has nothing to divide):
    Accuracy, the Misclassification Rate, Sensitivity (the true positive rate, recall), Specificity (the true
    negative rate), the False Positive Rate (1 - Specificity) and False Negative Rate (1 - Sensitivity), Precision
    (the positive predictive value), the Negative Predictive Value, F1 (2 Precision Sensitivity / (Precision +
    Sensitivity)), MCC (Matthews' correlation of actual and called) and the Portion called the level."""
    n = tp + fp + fn + tn

    def div(a, b):
        return a / b if b > 0 else None
    den = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'n': n, 'accuracy': div(tp + tn, n), 'misclassification': div(fp + fn, n),
            'sensitivity': div(tp, tp + fn), 'specificity': div(tn, tn + fp), 'fpr': div(fp, fp + tn), 'fnr': div(fn, fn + tp),
            'precision': div(tp, tp + fp), 'npv': div(tn, tn + fn), 'f1': div(2 * tp, 2 * tp + fp + fn),
            'mcc': (tp * tn - fp * fn) / math.sqrt(den) if den > 0 else None, 'portion': div(tp + fp, n)}


def youden(cut):
    """The cut with the largest Sensitivity - (1 - Specificity) (Youden's J; of equal ones the highest cut), as a
    point of the ROC curve: {'cut', 'fpr', 'tpr', 'j'}, or None when the set lacks the level or the others."""
    if not (cut['pos'] > 0 and cut['neg'] > 0) or not cut['p']:
        return None
    tpr = np.asarray(cut['tp']) / cut['pos']
    fpr = np.asarray(cut['fp']) / cut['neg']
    j = tpr - fpr
    i = int(np.argmax(j))
    return {'cut': float(cut['p'][i]), 'fpr': float(fpr[i]), 'tpr': float(tpr[i]), 'j': float(j[i])}


def roc_table(cut):
    """JMP's ROC Table of one level: a line per cut (Prob, the level's probability at or above which a row is called
    it), 1-Specificity, Sensitivity, Sens-(1-Spec) and the counts True Pos, True Neg, False Pos, False Neg; 'best'
    marks the line with the largest Sens-(1-Spec) (JMP stars it)."""
    b = youden(cut)
    out = []
    for p, tp, fp in zip(cut['p'], cut['tp'], cut['fp']):
        sens = tp / cut['pos'] if cut['pos'] > 0 else None
        fpr = fp / cut['neg'] if cut['neg'] > 0 else None
        out.append({'prob': p, 'fpr': fpr, 'sens': sens, 'j': None if sens is None or fpr is None else sens - fpr,
                    'tp': tp, 'tn': cut['neg'] - fp, 'fp': fp, 'fn': cut['pos'] - tp, 'best': bool(b and p == b['cut'])})
    return out


def _source(*fns):
    import inspect
    return '\n\n\n'.join(inspect.getsource(f).rstrip() for f in fns)


def threshold_lib():
    """The source of cut_table, counts_at, rates_at, youden and roc_table: the code under a Decision Threshold report
    (and the ROC Table) defines them, so that its numbers are the report's, digit for digit."""
    return 'import math\n\nimport numpy as np\n\n\n' + _source(cut_table, counts_at, rates_at, youden, roc_table)


GROUP_METRICS = ('n', 'base_rate', 'selection_rate', 'accuracy', 'auc', 'fpr', 'fnr', 'precision', 'tpr')


def group_rates(y, p, w, cut):
    """One group's measures at the threshold cut (a row is called the target level when p >= cut): its weight n, the
    base rate (the target level's share), the selection rate (the share called it), accuracy, AUC, the false
    positive and false negative rates, precision and the true positive rate; each row by its Weight x Freq."""
    y, p = np.asarray(y, dtype=bool), np.asarray(p, dtype=float)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    called = p >= cut
    n, pos, neg = float(w.sum()), float(w[y].sum()), float(w[~y].sum())
    tp, fp = float(w[called & y].sum()), float(w[called & ~y].sum())

    def div(a, b):
        return a / b if b > 0 else None
    return {'n': n, 'base_rate': div(pos, n), 'selection_rate': div(tp + fp, n), 'accuracy': div(tp + (neg - fp), n), 'auc': _auc(p, y, w) if len(y) else None,
            'fpr': div(fp, neg), 'fnr': div(pos - tp, pos), 'precision': div(tp, tp + fp), 'tpr': div(tp, pos), 'cut': float(cut)}


def equal_fpr_cut(y, p, w, target):
    """The threshold of a group whose false positive rate is nearest target: one of its probabilities, or above them
    all (calling none); of equally near ones the highest."""
    c = cut_table(p, np.asarray(y, dtype=bool), w)
    if not c['neg'] > 0:
        return None
    cands = [(abs(0.0 - target), float('inf'))] + [(abs(fp / c['neg'] - target), q) for q, fp in zip(c['p'], c['fp'])]
    best = min(cands, key=lambda z: (round(z[0], 12), -z[1]))
    return best[1]


@api('predict.groups')
def group_metrics(table, group, at, actual, prob=None, sets=None, w=None, cut=0.5, cuts=None, equal='none', reference=None, set_name=None,
                  levels=None, target=1, adjust=None, head=None, models=None, table_name='data'):
    """Group Metrics (beyond JMP; a fairness audit, as Shmueli et al. show one): a two-level classifier's measures
    within each group of a column that need not be a factor, on the rows of one set, and each measure's difference
    and ratio to a reference group.

      group     the column; at: each row's table row number (the group is read from the table);
      actual    each row's level (1 the target), prob its probability of the target level, sets its set, w its
                Weight x Freq;
      cut       the common threshold; cuts: {group: threshold} typed per group; equal 'fpr': each group's threshold
                solved so that its false positive rate is nearest the reference group's at the common threshold;
      adjust    {'a', 'b'}: the probabilities rescaled to a true event rate, p a / (p a + (1 - p) b);
      head      the code of the model (as predictive.threshold's), for the code of the result;
      models    several models audited alike in place of prob (Model Screening's selected methods): [{'label',
                'prob', 'prob_cv', 'expr', 'expr_cv'}], each one's probabilities of the target level (prob_cv: out of
                fold, a Crossvalidation set of every row) and the head's names of its n x 2 probabilities
                (fitted["label"], oof["label"]). The groups, the set and the reference group are the same for all;
                out['models'] has each one's rows, thresholds and target false positive rate."""
    at = np.asarray(at, dtype=int)
    y = np.asarray(actual, dtype=int) == int(target)
    st = np.zeros(len(at), dtype=int) if sets is None else np.asarray(sets, dtype=int)
    wt = np.ones(len(at)) if w is None else np.asarray(w, dtype=float)
    many = bool(models)
    cv_ok = many and all(q.get('prob_cv') is not None for q in models)
    present = [SETS[k] for k in range(3) if np.any(st == k)] + (['Crossvalidation'] if cv_ok else [])
    sname = set_name if set_name in present else ('Validation' if 'Validation' in present else present[0])
    m = np.ones(len(at), dtype=bool) if sname == 'Crossvalidation' else st == SETS.index(sname)
    gv = data.raw(table, group, at)
    meta_ = data.meta(table, group)
    numeric = meta_.get('dataType') == 'numeric'

    def key_of(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return float(v) if numeric else str(v)
    keys = [key_of(v) for v in gv]
    order = [float(v) if numeric else str(v) for v in (meta_.get('levels') or [])]
    seen = [k for k in dict.fromkeys(k for k, mm in zip(keys, m) if mm)]
    names = [k for k in order if k in seen] + [k for k in seen if k not in order and k is not None] + ([None] if None in seen else [])
    labels = {k: ('(missing)' if k is None else data.level_label(table, group, k)) for k in names}
    idx = {k: np.array([kk == k for kk in keys]) & m for k in names}
    if not names:
        raise ValueError(f'no rows of the {sname.lower()} set have a value of {group}')
    size = {k: float(wt[idx[k]].sum()) for k in names}
    ref = next((k for k in names if labels[k] == reference), None) if reference is not None else None
    if ref is None:
        ref = max(names, key=lambda k: size[k])       # the largest group
    start = {}
    for k in names:
        typed = (cuts or {}).get(labels[k])
        start[k] = float(typed) if equal == 'typed' and typed is not None else float(cut)

    def adjusted(pr):
        p = np.asarray(pr, dtype=float)
        if adjust:
            a, b = float(adjust['a']), float(adjust['b'])
            p = p * a / (p * a + (1 - p) * b)
        return p

    def audit(p):
        """One model's rows: each group's measures at its threshold, and the differences and ratios to the reference."""
        thr = dict(start)
        target_fpr = None
        if equal == 'fpr':
            target_fpr = group_rates(y[idx[ref]], p[idx[ref]], wt[idx[ref]], cut)['fpr']
            if target_fpr is not None:
                for k in names:
                    if k != ref:
                        c_ = equal_fpr_cut(y[idx[k]], p[idx[k]], wt[idx[k]], target_fpr)
                        if c_ is not None:
                            thr[k] = c_
        rows = []
        for k in names:
            r = group_rates(y[idx[k]], p[idx[k]], wt[idx[k]], thr[k])
            rows.append({'group': labels[k], 'reference': k == ref, **r})
        base = next(r for r in rows if r['reference'])
        for r in rows:
            for q in ('base_rate', 'selection_rate', 'accuracy', 'auc', 'fpr', 'fnr', 'precision', 'tpr'):
                r[f'd_{q}'] = None if r[q] is None or base[q] is None else r[q] - base[q]
                r[f'r_{q}'] = None if r[q] is None or not base[q] else r[q] / base[q]
        return rows, thr, target_fpr

    def shown(thr):
        return {labels[k]: (None if thr[k] == float('inf') else thr[k]) for k in names}

    out = {'group': group, 'set': sname, 'sets': present, 'reference': labels[ref], 'equal': equal, 'labels': [labels[k] for k in names],
           'values': [None if k is None else k for k in names]}
    if many:
        out['models'] = []
        for q in models:
            rows, thr, tfpr = audit(adjusted(q['prob_cv'] if sname == 'Crossvalidation' else q['prob']))
            out['models'].append({'label': q.get('label'), 'rows': rows, 'thresholds': shown(thr), 'target_fpr': tfpr})
        if head:
            out['code'] = head + SEP + '\n'.join(group_lines_many(group, names, labels, start, sname, target, adjust, equal, ref, models))
        return out
    rows, thr, target_fpr = audit(adjusted(prob))
    out.update({'rows': rows, 'target_fpr': target_fpr, 'thresholds': shown(thr)})
    if head:
        out['code'] = head + SEP + '\n'.join(group_lines(group, names, labels, thr, sname, target, adjust, equal, ref, cut, target_fpr))
    return out


def _group_head(target, equal):
    """The lines every Group Metrics code starts with, after the model's head: the functions and each row's weight."""
    L = ['import json', 'import numpy as np', 'import pandas as pd', 'import math', '',
         _source(_auc, cut_table, group_rates) + ('\n\n\n' + _source(equal_fpr_cut) if equal == 'fpr' else ''), '', '',
         f'target = {int(target)}   # the target level (the Decision Threshold\'s)',
         'wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)']
    return L


def _group_keys(group, names, labels, sname):
    """The rows of the set, each row's group and the groups' names and values, in the code."""
    keys = ['None' if k is None else _pylit(k) for k in names]
    return [('m = np.ones(len(y), dtype=bool)   # every row, each predicted by the model fitted without its fold' if sname == 'Crossvalidation'
             else f'm = sets == {SETS.index(sname)}   # the {sname.lower()} rows'),
            f'g = df.loc[d.index, {json.dumps(group)}]   # the group of each row (it need not be a factor of the model)',
            'names = ' + json.dumps([labels[k] for k in names]) + '   # the groups, in the column\'s order',
            'keys = [' + ', '.join(keys) + ']   # the values that make them']


def group_lines(group, names, labels, thr, sname, target, adjust, equal, ref, cut, target_fpr):
    """The code of Group Metrics, after the head of the model (d, y, fitted, sets, w)."""
    L = _group_head(target, equal) + ['p = fitted[:, target]   # each row\'s probability of the target level']
    if adjust:
        L.append(f'a, b = {float(adjust["a"])!r}, {float(adjust["b"])!r}   # the true event rate (True Event Rate in the Decision Threshold)')
        L.append('p = p * a / (p * a + (1 - p) * b)')
    L += _group_keys(group, names, labels, sname)
    L.append('cuts = ' + json.dumps([None if thr[k] == float('inf') else thr[k] for k in names]) + '   # each group\'s threshold' + (' (the equal-FPR ones are solved below)' if equal == 'fpr' else ''))
    L += ['rows = []',
          'for name, key, c in zip(names, keys, cuts):',
          '    r = m & (g.isna().to_numpy() if key is None else (g == key).to_numpy())']
    if equal == 'fpr' and target_fpr is not None:
        L += [f'    if name != {json.dumps(labels[ref])}:',
              f'        c2 = equal_fpr_cut(y[r] == target, p[r], wt[r], {target_fpr!r})   # the false positive rate nearest the reference group\'s',
              '        c = c if c2 is None else c2']
    L += ['    c = float("inf") if c is None else c',
          '    rows.append({"group": name, **group_rates(y[r] == target, p[r], wt[r], c)})',
          'print(pd.DataFrame(rows).to_string(index=False))']
    return L


def group_lines_many(group, names, labels, start, sname, target, adjust, equal, ref, models):
    """The code of Group Metrics of several models (Model Screening's methods), after the head that names each one's
    probabilities: every model audited alike, a row per model and group."""
    cv = sname == 'Crossvalidation'
    exprs = ', '.join(f'{json.dumps(q.get("label"))}: {q.get("expr_cv" if cv else "expr") or ("oof" if cv else "fitted")}' for q in models)
    L = _group_head(target, equal)
    L.append('models = {' + exprs + '}   # each method\'s probabilities of the two levels' + (', each row predicted without its fold' if cv else ''))
    if adjust:
        L.append(f'a, b = {float(adjust["a"])!r}, {float(adjust["b"])!r}   # the true event rate (True Event Rate in the Decision Threshold)')
    L += _group_keys(group, names, labels, sname)
    L.append('cuts = ' + json.dumps([start[k] for k in names]) + '   # each group\'s threshold' + (' (the others\' are solved for each method below)' if equal == 'fpr' else ''))
    if equal == 'fpr':
        L.append(f'ref = {names.index(ref)}   # the reference group, {labels[ref]}: the others\' thresholds give its false positive rate')
    L += ['rows = []',
          'for method, fitted_ in models.items():',
          '    p = fitted_[:, target]   # each row\'s probability of the target level']
    if adjust:
        L.append('    p = p * a / (p * a + (1 - p) * b)')
    L.append('    groups = [m & (g.isna().to_numpy() if key is None else (g == key).to_numpy()) for key in keys]')
    if equal == 'fpr':
        L.append('    target_fpr = group_rates(y[groups[ref]] == target, p[groups[ref]], wt[groups[ref]], cuts[ref])["fpr"]')
    L.append('    for i, (name, r, c) in enumerate(zip(names, groups, cuts)):')
    if equal == 'fpr':
        L += ['        if i != ref and target_fpr is not None:',
              '            c2 = equal_fpr_cut(y[r] == target, p[r], wt[r], target_fpr)   # the false positive rate nearest the reference group\'s',
              '            c = c if c2 is None else c2']
    L += ['        c = float("inf") if c is None else c',
          '        rows.append({"method": method, "group": name, **group_rates(y[r] == target, p[r], wt[r], c)})',
          'print(pd.DataFrame(rows).to_string(index=False))']
    return L


def threshold(y, prob, levels, sets=None, w=None, rows=None, head=None, select=(), code=None, cv=None, values=None):
    """What the Decision Threshold report (SM.predict.threshold in smui-predict.js) needs of a response of two
    levels: each row's level, set, weight and probabilities. The page makes the cut tables from them (cutTable, as
    cut_table here) and the counts and rates at any threshold typed or dragged (countsAt, ratesAt), so a new
    threshold needs no call; the code under the report does the same with the functions of threshold_lib().

      y       each row's level: its index in levels, 0 or 1
      prob    each row's probability of both levels (n x 2, in the order of levels), or of the second (a vector);
              or several models, {key: (label, probabilities)}, in the order the report shows them
      levels  the two levels as the report names them (the second is the target level at first, as JMP has it)
      sets    each row's set, 0 Training, 1 Validation, 2 Test (None: every row trains)
      w       each row's Weight x Freq (None: every row counts once)
      rows    the table's row number of each row: the plot's points are linked to the rows
      head    the code of the model for the code blocks: lines that end having made d (the rows, indexed by the
              table's row numbers), y, fitted (the n x 2 probabilities; of several models, fitted[label]), sets and w
              (None: every row counts once), as P.code() and the platforms' graph heads do; None: no code
      select  lines after the head that pick this response's y and fitted (Neural's several responses)
      code    {key: Python expression of the model's n x 2 probabilities} when the head names them otherwise
      cv      {key: n x 2 out-of-fold probabilities}: a 'Crossvalidation' set of every row (Model Screening's K Fold);
              code then names them too, as {key: (fitted expression, crossvalidated expression)}
      values  the two levels as the table holds them (numbers for a numeric column), for Save Threshold Formula;
              None: levels
    """
    y = np.asarray(y, dtype=int)
    n = len(y)
    st = np.zeros(n, dtype=int) if sets is None else np.asarray(sets, dtype=int)
    models = prob if isinstance(prob, dict) else {'model': (None, prob)}
    present = [k for k in range(3) if np.any(st == k)]
    names = [SETS[k] for k in present] + (['Crossvalidation'] if cv else [])

    def both(pr):
        pr = np.asarray(pr, dtype=float)
        return np.column_stack([1 - pr, pr]) if pr.ndim == 1 else pr

    def put(entry, pr, suffix=''):
        entry['p' + suffix] = pr[:, 1].tolist()
        # the first level's own probabilities when they are not exactly 1 - the second's (the page's default)
        if not np.array_equal(pr[:, 0], 1 - pr[:, 1]):
            entry['p0' + suffix] = pr[:, 0].tolist()
    out_models = []
    for key, (label, pr) in models.items():
        entry = {'key': key, 'label': label}
        put(entry, both(pr))
        if cv and key in cv:
            put(entry, both(cv[key]), '_cv')
        c = (code or {}).get(key)
        if c is not None:
            entry['code'] = list(c) if isinstance(c, (list, tuple)) else [c]
        out_models.append(entry)
    vals = list(levels if values is None else values)
    out = {'levels': [str(v) for v in levels], 'values': [v.item() if hasattr(v, 'item') else v for v in vals], 'target': 1, 'sets': names,
           'weighted': w is not None, 'models': out_models,
           'points': {'rows': (np.arange(n) if rows is None else np.asarray(rows, dtype=int)).tolist(), 'set': st.tolist(), 'actual': y.tolist(),
                      'w': None if w is None else np.asarray(w, dtype=float).tolist()}}
    if head is not None:
        out['plots'] = {'head_code': head, 'select': '\n'.join(select or []), 'lib': threshold_lib()}
    return out


def threshold_of(P, fitted, head=None, select=()):
    """threshold() of a predictive platform's two-level response (P from prepare())."""
    return threshold(P.target, fitted, P.labels, P.sets, P.w, P.index, head=head, select=select, values=P.levels)


def residuals(P, fitted):
    """Actual by predicted, for a continuous response: per row, with its set."""
    return {'rows': P.index.tolist(), 'actual': P.target.tolist(), 'predicted': np.asarray(fitted, dtype=float).tolist(),
            'set': P.sets.tolist()}


def contributions(P, values, label='Contribution', extra=None, code=None, title='Column Contributions'):
    """A per-feature quantity (an importance) summed back to the x columns:
    [{'column', 'value', 'portion'}], largest first. extra: more columns
    for the table, {label: {x column: value}} (JMP's Number of Splits).
    code: the lines (after a graph's head) that make `contrib`, each x
    column's value, from the model; the bars' code is then 'plot_code'
    (graph_code in smui-predict.js puts the head before it)."""
    values = np.asarray(values, dtype=float)
    rows = []
    for c in P.x:
        v = float(np.sum(values[P.groups[c]]))
        rows.append({'column': c, 'value': v})
    tot = sum(max(r['value'], 0.0) for r in rows)
    for r in rows:
        r['portion'] = r['value'] / tot if tot > 0 else None
        for j, (lab, by) in enumerate((extra or {}).items()):
            r[f'extra{j}'] = by.get(r['column'])
    rows.sort(key=lambda r: -(r['value'] if r['value'] is not None else -math.inf))
    out = {'rows': rows, 'label': label, 'extra': list((extra or {}).keys())}
    if code is not None:
        out['plot_code'] = '\n'.join(list(code) + contribution_lines(len(P.x), title))
    return out


def saved(P, predict, proba=None):
    """What Save Predicteds / Save Probabilities put in the table: for every
    row whose factors the model can take. predict(X) gives the prediction
    (continuous); proba(X) the level probabilities (categorical)."""
    X, rows = P.all_rows()
    if P.kind == 'continuous':
        pred = np.asarray(predict(X), dtype=float)
        yv = pd.to_numeric(pd.Series(data.raw(P.table, P.y, rows)), errors='coerce').to_numpy(float)
        return {'rows': rows.tolist(), 'values': pred.tolist(), 'residuals': (yv - pred).tolist(), 'name': f'Predicted {P.y}'}
    pr = np.asarray(proba(X), dtype=float)
    most = [P.labels[int(j)] for j in np.argmax(pr, axis=1)]
    return {'rows': rows.tolist(), 'prob': pr.tolist(), 'levels': list(P.labels), 'most_likely': most,
            'names': [f'Prob[{lab}]' for lab in P.labels], 'most_name': f'Most Likely {P.y}',
            'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}


def report(P, fitted, roc_curves=True, head=None, select=(), decided=None):
    """The pieces every platform shows: the Measures of Fit (and 'naive',
    those of the Naive model: the training mean or shares), and for a
    categorical response the confusion matrices and the ROC and lift
    curves, and for two levels 'threshold' (threshold_of: the Decision
    Threshold's cut tables and each row's probability); for a continuous
    one actual by predicted. head: the code of the platform's model
    (graph_codes), which adds 'plots', the code of those graphs; select:
    lines that pick this response's y and fitted from what the head makes
    (a network of several responses); decided: each row's called level
    when it is not the most probable one (a tie broken at random)."""
    out = {'kind': P.kind, 'measures': measures(P, fitted, decided), 'measure_columns': measure_columns(P.kind), 'sets': [SETS[k] for k in range(3) if P.has(k)],
           'n': {SETS[k]: int(P.mask(k).sum()) for k in range(3)}, 'notes': list(P.notes), 'features': list(P.features),
           'naive': measures(P, naive_fitted(P))}
    if P.kind == 'categorical':
        out['levels'] = list(P.labels)
        out['values'] = [v.item() if hasattr(v, 'item') else v for v in P.levels]   # the levels as the table holds them
        out['confusion'] = confusion(P, fitted, decided)
        if roc_curves:
            out['roc'] = roc(P, fitted)
            out['lift'] = lift(P, fitted)
        if len(P.levels) == 2:
            out['threshold'] = threshold_of(P, fitted, head=head, select=select)
    else:
        out['residuals'] = residuals(P, fitted)
    if head is not None:
        out['plots'] = graph_codes(P, head, select, roc_curves)
    return out


def seed_of(seed):
    """A seed from the page (a number, or text holding one), or None."""
    if seed is None or seed == '':
        return None
    try:
        return int(float(seed))
    except (TypeError, ValueError):
        raise ValueError(f'the random seed is a whole number, not {seed!r}')


def predictor(P, model, predict=None, proba=None):
    """The Prediction Profiler's view of a fitted model (see profile.py):
    the prediction of a continuous response, or the probability of each
    level of a categorical one. predict / proba default to the model's own
    (a function of X may be given, a pipeline's for example)."""
    from .profile import Predictor
    predict = predict or model.predict
    proba = proba or (lambda X: P.proba(model, X))

    def run(settings):
        X = P.encode_settings(settings)
        if P.kind == 'continuous':
            return [{'name': P.y, 'pred': np.asarray(predict(X), dtype=float), 'lower': None, 'upper': None, 'bounded': False}]
        pr = np.asarray(proba(X), dtype=float)
        return [{'name': f'Prob[{lab}]', 'pred': pr[:, j], 'lower': None, 'upper': None, 'bounded': True} for j, lab in enumerate(P.labels)]
    frame = data.frame(P.table, P.x, P.index[P.train()], dropna=False)
    observed = {c: [None if (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in frame[c].astype(object)] for c in P.x}
    return Predictor(P.factors(), run, observed)


# ---------------------------------------------------------------------------
# the graphs as matplotlib code
# ---------------------------------------------------------------------------
# Under each graph the report shows Python that draws it with matplotlib from
# a CSV export of the table, as the notebook runs it. A graph's code is a
# head and a tail joined by SEP (graph_code in smui-predict.js joins them):
# the head reads the table, keeps the report's rows, makes the sets and fits
# the model as the platform's own code fits it (with the same seed), and ends
# with `fitted`, every row's prediction or its probability of each level; the
# tail computes the graph's numbers from the model and draws them in the
# light theme's colours at the graph's size (100 pixels an inch). The head
# names d (the rows), y (a number, or the level's index), sets (0 training,
# 1 validation, 2 test) and fitted.

PLT = 'import matplotlib.pyplot as plt'
SEP = '\n\n# ----\n'
BASE, BAR, TEXT, MUTED, FIT, SURFACE = '#2f6690', '#8fa9c2', '#352921', '#786b5d', '#c0392b', '#fcf7f2'
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']


def figure(w, h, names='fig, ax', extra=''):
    """The line that makes a figure of the page's graph's size, w x h pixels at 100 an inch."""
    return f'{names} = plt.subplots(figsize=({w / 100:g}, {h / 100:g}), layout="constrained"{extra})'


def freq_line(P):
    """f: each row's Weight x Freq, which the confusion matrices and the ROC and lift curves count the rows by (as
    JMP counts them)."""
    parts = [f'd[{json.dumps(c)}].to_numpy(float)' for c in (P.spec.get('weight'), P.spec.get('freq')) if c]
    return (f'f = {" * ".join(parts)}   # each row\'s Weight x Freq: the curves count the rows by it' if parts
            else 'f = np.ones(len(d))   # every row counts once')


def names_line(P):
    return f'names = {json.dumps(list(P.labels))}   # the levels, as the report names them'


def roc_lines(P, k):
    """The ROC curves of one set (predictive.roc), every level against the others."""
    s = SETS[k]
    return [f'# ROC curves of the {s.lower()} rows: each level against the others, as the cut on its probability falls',
            'def roc(p, pos, f):',
            '    """1 - specificity and sensitivity at each cut on p, highest first; tied values move together; f counts the rows."""',
            '    o = np.argsort(-p, kind="mergesort")',
            '    s, tp, fp = p[o], np.cumsum(np.where(pos[o], f[o], 0.0)), np.cumsum(np.where(pos[o], 0.0, f[o]))',
            '    last = np.r_[s[1:] != s[:-1], True]   # the end of each run of equal values',
            '    return np.r_[0.0, fp[last] / fp[-1]], np.r_[0.0, tp[last] / tp[-1]]',
            '',
            '',
            freq_line(P), names_line(P), f'colors = {json.dumps(PALETTE)}',
            f'm = sets == {k}   # the {s.lower()} rows',
            figure(330, 320),
            'i = 0',
            'for j, name in enumerate(names):',
            '    pos = y[m] == j',
            '    if not (f[m][pos].sum() > 0 and f[m][~pos].sum() > 0):',
            '        continue   # a level with no rows here, or with every row: no curve',
            '    fpr, tpr = roc(fitted[m][:, j], pos, f[m])',
            '    auc = np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2)   # the area under the curve',
            '    ax.plot(fpr, tpr, color=colors[i % len(colors)], linewidth=1.8, label=f"{name} ({auc:.4f})")',
            '    b = int(np.argmax(tpr[1:] - fpr[1:])) + 1   # the best cut: the largest Sensitivity - (1 - Specificity)',
            f'    ax.scatter([fpr[b]], [tpr[b]], s=36, color=colors[i % len(colors)], edgecolors="{SURFACE}", zorder=3)',
            '    i += 1',
            f'ax.plot([0, 1], [0, 1], color="{MUTED}", linewidth=1, linestyle=":")',
            'ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1.01)',
            'ax.set_xlabel("1 - Specificity")', 'ax.set_ylabel("Sensitivity")',
            f'ax.set_title({json.dumps(f"ROC {s}")})',
            'ax.legend(loc="lower right", frameon=False, fontsize=8)',
            'plt.show()']


def lift_lines(P, k):
    """The lift curves of one set (predictive.lift)."""
    s = SETS[k]
    return [f'# lift curves of the {s.lower()} rows: the rows taken by the probability of each level, highest first',
            freq_line(P), names_line(P), f'colors = {json.dumps(PALETTE)}',
            f'm = sets == {k}   # the {s.lower()} rows',
            'tot = f[m].sum()',
            figure(330, 300),
            'i = 0',
            'for j, name in enumerate(names):',
            '    pos = y[m] == j',
            '    base = f[m][pos].sum() / tot   # the level\'s rate in the set',
            '    if not base > 0:',
            '        continue',
            '    o = np.argsort(-fitted[m][:, j], kind="mergesort")',
            '    cw, hits = np.cumsum(f[m][o]), np.cumsum(np.where(pos[o], f[m][o], 0.0))',
            '    ax.plot(cw / tot, hits / cw / base, color=colors[i % len(colors)], linewidth=1.8, label=name)   # its rate among the rows taken over its rate in the set',
            '    i += 1',
            f'ax.plot([0, 1], [1, 1], color="{MUTED}", linewidth=1, linestyle=":")',
            'ax.set_xlim(0, 1)', 'ax.set_xlabel("Portion")', 'ax.set_ylabel("Lift")',
            f'ax.set_title({json.dumps(f"Lift {s}")})',
            'ax.legend(frameon=False, fontsize=8)',
            'plt.show()']


def gains_lines(P, k):
    """The cumulative gains curves of one set (predictive.lift's gains)."""
    s = SETS[k]
    return [f'# cumulative gains of the {s.lower()} rows: the share of each level\'s rows among the rows taken, highest probability first',
            freq_line(P), names_line(P), f'colors = {json.dumps(PALETTE)}',
            f'm = sets == {k}   # the {s.lower()} rows',
            'tot = f[m].sum()',
            figure(330, 300),
            'i = 0',
            'for j, name in enumerate(names):',
            '    pos = y[m] == j',
            '    if not f[m][pos].sum() > 0:',
            '        continue',
            '    o = np.argsort(-fitted[m][:, j], kind="mergesort")',
            '    cw, hits = np.cumsum(f[m][o]), np.cumsum(np.where(pos[o], f[m][o], 0.0))',
            '    ax.plot(cw / tot, hits / hits[-1], color=colors[i % len(colors)], linewidth=1.8, label=name)   # the share of the level\'s rows found',
            '    i += 1',
            f'ax.plot([0, 1], [0, 1], color="{MUTED}", linewidth=1, linestyle=":")   # a random order',
            'ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1.01)', 'ax.set_xlabel("Portion")', 'ax.set_ylabel("Gains")',
            f'ax.set_title({json.dumps(f"Gains {s}")})',
            'ax.legend(loc="lower right", frameon=False, fontsize=8)',
            'plt.show()']


def decile_lines(P):
    """The decile lift tables of every set (predictive.lift_table), for the level lv (the page sets it)."""
    lv = 1 if len(P.levels) == 2 else 0
    sets = [[k, SETS[k]] for k in range(3) if P.has(k)]
    return [f'lv = {lv}   # the level of the table (Table Level in the red triangle)',
            _source(lift_table), '', '',
            freq_line(P), names_line(P),
            'deciles = {}',
            f'for k, set_name in {json.dumps(sets)}:',
            '    m = sets == k',
            '    deciles[set_name] = pd.DataFrame(lift_table(fitted[m][:, lv], y[m] == lv, f[m]))   # the rows in ten parts of equal weight, highest probability first',
            '    print(set_name, names[lv])',
            '    print(deciles[set_name].to_string(index=False))']


def abp_lines(k, title=None, residual=False):
    """Actual (or the residual) by predicted of one set: every row's y against its fitted value."""
    s = SETS[k]
    if residual:
        return [f'm = sets == {k}   # the {s.lower()} rows', figure(320, 280),
                f'ax.scatter(fitted[m], y[m] - fitted[m], s=14, color="{BASE}")   # the actual value less the prediction',
                'v = fitted[m][np.isfinite(fitted[m])]',
                f'ax.plot([v.min(), v.max()], [0, 0], color="{MUTED}", linewidth=1, linestyle=":")',
                'ax.set_xlabel("Predicted")', 'ax.set_ylabel("Residual")', f'ax.set_title({json.dumps(title or f"Residual by predicted {s}")}, wrap=True)', 'plt.show()']
    return [f'm = sets == {k}   # the {s.lower()} rows', figure(320, 300),
            f'ax.scatter(fitted[m], y[m], s=14, color="{BASE}")',
            'v = np.r_[fitted[m], y[m]]',
            'v = v[np.isfinite(v)]',
            f'ax.plot([v.min(), v.max()], [v.min(), v.max()], color="{MUTED}", linewidth=1, linestyle=":")   # actual = predicted',
            'ax.set_xlabel("Predicted")', 'ax.set_ylabel("Actual")', f'ax.set_title({json.dumps(title or f"Actual by predicted {s}")}, wrap=True)', 'plt.show()']


def contribution_lines(n, title='Column Contributions'):
    """Column Contributions' bars from contrib, each x column's value (in the columns' order)."""
    return ['cols = sorted(contrib, key=lambda c: -contrib[c])   # the largest first (a tie keeps the columns\' order)',
            'tot = sum(max(v, 0.0) for v in contrib.values())',
            'portion = [contrib[c] / tot if tot > 0 else 0.0 for c in cols]   # each column\'s share of the total',
            figure(340, max(120, 24 * n + 50)),
            f'ax.barh(cols, portion, color="{BAR}")',
            'ax.invert_yaxis()   # the largest at the top',
            'ax.set_xlim(0, 1)', 'ax.set_xlabel("Portion")', f'ax.set_title({json.dumps(title)})', 'plt.show()']


def graph_codes(P, head, select=(), curves=True):
    """The code of the graphs every predictive platform shows, per set: the
    ROC and lift curves (a categorical response) or actual by predicted,
    each the lines after the head (with select before them)."""
    pre = list(select or [])
    out = {'head_code': head}
    sets = [k for k in range(3) if P.has(k)]
    if P.kind == 'categorical':
        if curves:
            out['roc'] = {SETS[k]: '\n'.join(pre + roc_lines(P, k)) for k in sets}
            out['lift'] = {SETS[k]: '\n'.join(pre + lift_lines(P, k)) for k in sets}
            out['gains'] = {SETS[k]: '\n'.join(pre + gains_lines(P, k)) for k in sets}
            out['deciles'] = '\n'.join(pre + decile_lines(P))
    else:
        out['abp'] = {SETS[k]: '\n'.join(pre + abp_lines(k)) for k in sets}
    return out


def fitted_line(P, var='model'):
    """fitted from a scikit-learn model of X (every level's probability in the table's order: a level the
    training rows lack gets 0, as P.proba does)."""
    if P.kind == 'categorical':
        return [f'fitted = np.zeros((len(X), len(levels)))',
                f'fitted[:, {var}.classes_] = {var}.predict_proba(X)   # each row\'s probability of every level (0 for a level the model never saw)']
    return [f'fitted = {var}.predict(X)   # each row\'s prediction']
