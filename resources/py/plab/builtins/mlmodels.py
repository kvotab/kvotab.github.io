"""Statistics and machine learning with a response: classification
(fitctree, fitcknn, fitcdiscr, fitcnb, fitcsvm, fitcecoc, fitcensemble,
fitclinear, fitcnet, fitckernel, TreeBagger) and regression (fitrtree,
fitrsvm, fitrensemble, fitrlinear, fitrnet, fitrgp, fitrkernel), their
templates, and what is done with a model (predict, loss, resubLoss,
resubPredict, crossval, kfoldLoss, kfoldPredict, oobLoss, compact, view);
cvpartition and crossval of a function, confusionmat, confusionchart,
perfcurve.

The learning itself is in learners.py. A model keeps its training data;
its scores are posterior probabilities (trees, kNN, discriminant, naive
Bayes, bagged ensembles, neural networks) or signed margins (SVM, linear,
boosted ensembles, ECOC)."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, Obj, FH, Char, Cell, Struct, Str, EMPTY, numel, py_str, text_list, class_of
from .. import runtime as R
from . import learners as LN


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, np.linalg.LinAlgError) as e:
                raise err(f'stats:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _rs():
    from .elmat import RNG
    return RNG.rs


def _flag(v):
    if is_str(v):
        return py_str(v).lower() in ('on', 'true', 'yes')
    return bool(np.all(darr(v)))


def _int(v):
    return int(round(float(num(v))))


# ---- labels ------------------------------------------------------------------------------------------------------------------------------

class Labels:
    """A classification response: its kind, its classes in order, and each observation's class number (-1 missing)."""

    def __init__(self, y, fn, order=None):
        from .categoricals import Categorical
        self.kind = 'numeric'
        if isinstance(y, Categorical):
            self.kind = 'categorical'
            self.cats = list(y.cats)
            codes = np.asarray(y.a, float).reshape(-1).astype(int) - 1
            present = sorted(set(codes[codes >= 0]))
            self.classes = [self.cats[c] for c in present]
            pos = {c: i for i, c in enumerate(present)}
            self.idx = np.array([pos.get(c, -1) for c in codes])
            self.ordinal = y.ordinal
        elif isinstance(y, (Cell, Str)) or (isinstance(y, Char) and y.a.shape[0] > 1):
            self.kind = 'string' if isinstance(y, Str) else 'cellstr'
            vals = [s.rstrip() for s in y.row_strs()] if isinstance(y, Char) else [('' if s is None else str(s)) for s in text_list(y)]
            if isinstance(y, Char):
                self.kind = 'char'
            self.classes = sorted(set(v for v in vals if v != ''))
            pos = {c: i for i, c in enumerate(self.classes)}
            self.idx = np.array([pos.get(v, -1) for v in vals])
        else:
            a = np.asarray(darr(y), float).reshape(-1)
            self.kind = 'logical' if class_of(y) == 'logical' else 'numeric'
            self.numclass = class_of(y)
            self.classes = [float(v) for v in np.unique(a[~np.isnan(a)])]
            pos = {c: i for i, c in enumerate(self.classes)}
            self.idx = np.array([pos.get(float(v), -1) if not np.isnan(v) else -1 for v in a])
        if order is not None:
            # ClassNames given: those classes, in that order (the others left out)
            base = list(self.classes)
            self.classes = self._ordered(order)
            pos = {c: i for i, c in enumerate(self.classes)}
            self.idx = np.array([pos.get(base[i], -1) if i >= 0 else -1 for i in self.idx])

    def _ordered(self, order, want=None):
        """ClassNames given: their order as written."""
        if isinstance(order, (Cell, Str)):
            return [str(s) for s in text_list(order)]
        if isinstance(order, Char):
            return [s.rstrip() for s in order.row_strs()] if order.a.shape[0] > 1 else [order.str()]
        from .categoricals import Categorical
        if isinstance(order, Categorical):
            return [order.cats[int(c) - 1] for c in np.asarray(order.a).reshape(-1)]
        return [float(v) for v in np.asarray(darr(order), float).reshape(-1)]

    @property
    def K(self):
        return len(self.classes)

    def value(self, idx):
        """Class numbers as the response's kind of value, a column."""
        idx = np.asarray(idx, int).reshape(-1)
        n = idx.size
        if self.kind == 'categorical':
            from .categoricals import Categorical
            codes = np.array([self.cats.index(self.classes[i]) + 1 if i >= 0 else 0 for i in idx], float)
            return Categorical(codes.reshape(-1, 1), self.cats, self.ordinal)
        if self.kind in ('cellstr', 'char'):
            return Cell.of_list([Char.of(self.classes[i] if i >= 0 else '') for i in idx], (n, 1))
        if self.kind == 'string':
            return Str.from_list([self.classes[i] if i >= 0 else None for i in idx], (n, 1))
        vals = np.array([self.classes[i] if i >= 0 else np.nan for i in idx], float).reshape(-1, 1)
        if self.kind == 'logical':
            return out(vals.astype(bool))
        return out(vals) if self.numclass == 'double' else out(vals, self.numclass)

    def names_value(self):
        return self.value(np.arange(self.K))

    def text(self, i):
        c = self.classes[i]
        return f'{c:g}' if isinstance(c, float) else str(c)


# ---- data ----------------------------------------------------------------------------------------------------------------------------------

def _table_cols(T, names, fn):
    from .categoricals import Categorical
    cols = []
    for nm in names:
        v = T.vars[T.names.index(nm)]
        if isinstance(v, Categorical):
            cols.append(np.asarray(v.a, float).reshape(-1, 1))
        elif isinstance(v, (Cell, Str)):
            raise err(f'stats:{fn}:predictor', f"The predictor '{nm}' is text: make it categorical first.", fn)
        else:
            a = np.asarray(darr(v), float)
            cols.append(a.reshape(a.shape[0], -1))
    return np.column_stack(cols) if cols else np.zeros((T.n, 0))


OPT_NAMES = ('predictornames', 'responsename', 'classnames', 'prior', 'weights', 'crossval', 'kfold', 'holdout', 'leaveout', 'cvpartition',
             'standardize', 'cost', 'scoretransform', 'optimizehyperparameters', 'hyperparameteroptimizationoptions', 'categoricalpredictors',
             'verbose', 'options')


def parse_data(args, fn, own, regression=False):
    """(X, Y or Labels, predictor names, response name, options) from (X, Y, ...), (Tbl, 'y', ...), (Tbl, 'y ~ x1 + x2', ...),
    (Tbl, Y, ...)."""
    from .tables import Table
    a = list(args)
    if not a:
        raise MError('MATLAB:minrhs', 'Not enough input arguments.')
    resp_name = 'Y'
    if isinstance(a[0], Table):
        T = a.pop(0)
        if a and is_str(a[0]) and '~' in py_str(a[0]):
            lhs, rhs = py_str(a.pop(0)).split('~', 1)
            resp_name = lhs.strip()
            preds = [t.strip() for t in rhs.split('+') if t.strip()]
            if preds == ['.'] or not preds:
                preds = [nm for nm in T.names if nm != resp_name]
            Y = T.vars[T.names.index(resp_name)]
        elif a and is_str(a[0]) and py_str(a[0]) in T.names and (len(a) % 2 == 1):
            resp_name = py_str(a.pop(0))
            Y = T.vars[T.names.index(resp_name)]
            preds = [nm for nm in T.names if nm != resp_name]
        elif a and not is_str(a[0]):
            Y = a.pop(0)
            preds = list(T.names)
        else:
            raise err(f'stats:{fn}:response', 'Name the response: the table and its response variable, a formula, or the response itself.', fn)
        X = _table_cols(T, preds, fn)
    else:
        if len(a) < 2:
            raise MError('MATLAB:minrhs', 'Not enough input arguments.')
        X = np.asarray(darr(a.pop(0)), float)
        if X.ndim != 2:
            raise err(f'stats:{fn}:X', 'X is a matrix, a row for each observation.', fn)
        Y = a.pop(0)
        preds = [f'x{j + 1}' for j in range(X.shape[1])]
    if len(a) % 2:
        raise err(f'stats:{fn}:pairs', f'The options of {fn} come as names and values.', fn)
    o = {}
    for i in range(0, len(a), 2):
        k = py_str(a[i]).lower()
        if k not in OPT_NAMES and k not in own:
            raise err(f'stats:{fn}:option', f"'{py_str(a[i])}' is not an option of {fn}.", fn)
        o[k] = a[i + 1]
    if 'predictornames' in o:
        preds = [str(s) for s in text_list(o['predictornames'])]
    if 'responsename' in o:
        resp_name = py_str(o['responsename'])
    if regression:
        y = np.asarray(darr(Y), float).reshape(-1)
        if y.size != X.shape[0]:
            raise err(f'stats:{fn}:size', 'X and Y have as many rows.', fn)
        keep = np.isfinite(y) & ~np.any(np.isnan(X), axis=1)
        return X[keep], y[keep], preds, resp_name, o, keep
    labs = Labels(Y, fn, o.get('classnames'))
    if labs.idx.size != X.shape[0]:
        raise err(f'stats:{fn}:size', 'X and Y have as many rows.', fn)
    keep = (labs.idx >= 0) & ~np.any(np.isnan(X), axis=1)
    return X[keep], labs, preds, resp_name, o, keep


def _prior(o, labs, y):
    K = labs.K
    if 'prior' not in o:
        return None
    pv = o['prior']
    if is_str(pv):
        if py_str(pv).lower() == 'uniform':
            return np.full(K, 1 / K)
        return None
    p = np.asarray(darr(pv), float).reshape(-1)
    return p / p.sum()


def _weights(o, keep):
    if 'weights' not in o:
        return None
    return np.asarray(darr(o['weights']), float).reshape(-1)[keep]


# ---- templates ----------------------------------------------------------------------------------------------------------------------------

class Template(Obj):
    """A learner's options, to be fitted later (ECOC's and ensembles' learners)."""
    cls = 'classreg.learning.FitTemplate'

    def __init__(self, kind, opts):
        self.kind = kind
        self.opts = opts

    def display_lines(self):
        names = {'tree': 'Tree', 'svm': 'SVM', 'knn': 'KNN', 'discriminant': 'Discriminant', 'naivebayes': 'NaiveBayes', 'linear': 'Linear',
                 'ensemble': 'Ensemble', 'gp': 'GP', 'kernel': 'Kernel'}
        return [f'  Fit template for {names.get(self.kind, self.kind)}.'] + [f'    {k}: {_short(v)}' for k, v in self.opts.items()]


def _short(v):
    from ..display import summary
    try:
        return summary(v)
    except Exception:
        return str(v)


def _template(kind):
    def f(nargout, *args):
        if len(args) % 2:
            raise err(f'stats:template:{kind}', 'A template takes names and values.', 'template')
        return Template(kind, {py_str(args[i]).lower(): args[i + 1] for i in range(0, len(args), 2)})
    return f


for _k, _n in (('tree', 'templateTree'), ('svm', 'templateSVM'), ('knn', 'templateKNN'), ('discriminant', 'templateDiscriminant'),
               ('naivebayes', 'templateNaiveBayes'), ('linear', 'templateLinear'), ('kernel', 'templateKernel'), ('gp', 'templateGP')):
    _f = _template(_k)
    _f.__doc__ = f't = {_n}(Name, Value, ...): the options of a learner, for fitcecoc and the ensembles.'
    bi(_n)(_f)


# ---- the model objects -------------------------------------------------------------------------------------------------------------------

class Model(Obj):
    """A fitted classification or regression model."""
    is_handle = False

    def __init__(self, cls, regression, X, y, preds, resp, learner, info=None, w=None):
        self._cls = cls
        self.regression = regression
        self.X, self.y = X, y              # y: numbers (regression) or Labels
        self.preds, self.resp = preds, resp
        self.learner = learner
        self.info = info or {}
        self.w = w

    @property
    def cls(self):
        return self._cls

    def value_copy(self):
        return self

    # ---- predictions ----
    def scores(self, X):
        """Class scores (n, K), or predictions (n,)."""
        L = self.learner
        if self.regression:
            return np.asarray(L(X), float).reshape(-1)
        return L(X)

    def predict(self, X, nargout=1):
        if X.ndim != 2 or X.shape[1] != self.X.shape[1]:
            raise err('stats:predict:size', f'X has {self.X.shape[1]} columns, as the data the model was fitted to.', 'predict')
        S = self.scores(X)
        if self.regression:
            return (out(S.reshape(-1, 1)),)
        lab = np.argmax(S, axis=1)
        res = (self.y.value(lab), out(S))
        if nargout > 2 and 'cost' in self.info:
            res = res + (out(S @ self.info['cost']),)
        return res

    def labels_of(self, Y):
        labs = Labels(Y, 'loss', self.y.names_value())
        return labs.idx

    def loss(self, X, Y, lossfun='default', w=None):
        S = self.scores(X)
        w = np.ones(X.shape[0]) if w is None else w
        w = w / w.sum()
        if self.regression:
            y = np.asarray(darr(Y), float).reshape(-1)
            if lossfun in ('default', 'mse'):
                return float(np.sum(w * (S - y) ** 2))
            if lossfun == 'epsiloninsensitive':
                eps = self.info.get('epsilon', 0.1)
                return float(np.sum(w * np.maximum(np.abs(S - y) - eps, 0)))
            raise err('stats:loss:LossFun', f"'{lossfun}' is not a loss for regression: 'mse' or 'epsiloninsensitive'.", 'loss')
        yi = self.labels_of(Y)
        K = S.shape[1]
        if lossfun in ('default', 'classiferror'):
            return float(np.sum(w * (np.argmax(S, axis=1) != yi)))
        m = S[np.arange(S.shape[0]), yi] - np.max(np.where(np.eye(K, dtype=bool)[yi], -np.inf, S), axis=1)
        if lossfun == 'hinge':
            return float(np.sum(w * np.maximum(0, 1 - m)))
        if lossfun == 'logit':
            return float(np.sum(w * np.log1p(np.exp(-m))))
        if lossfun == 'exponential':
            return float(np.sum(w * np.exp(-m)))
        if lossfun == 'binodeviance':
            return float(np.sum(w * np.log1p(np.exp(-2 * m))))
        if lossfun == 'quadratic':
            return float(np.sum(w * (1 - m) ** 2))
        if lossfun in ('mincost', 'crossentropy'):
            P = np.clip(S[np.arange(S.shape[0]), yi], 1e-300, None)
            return float(np.sum(w * (1 - P))) if lossfun == 'mincost' else float(-np.sum(w * np.log(P)))
        raise err('stats:loss:LossFun', f"'{lossfun}' is not a loss: 'classiferror', 'hinge', 'logit', 'exponential', 'binodeviance', 'quadratic', 'mincost', 'crossentropy'.", 'loss')

    # ---- properties ----
    def common(self):
        d = {'PredictorNames': Cell.of_list([Char.of(s) for s in self.preds]), 'ResponseName': Char.of(self.resp),
             'NumObservations': float(self.X.shape[0]), 'X': out(self.X)}
        if self.regression:
            d['Y'] = out(self.y.reshape(-1, 1))
        else:
            d['Y'] = self.y.value(self.y.idx)
            d['ClassNames'] = self.y.names_value()
            pr = self.info.get('prior')
            d['Prior'] = out(np.asarray(pr if pr is not None else np.bincount(self.y.idx, minlength=self.y.K) / self.y.idx.size, float).reshape(1, -1))
        return d

    def props(self):
        d = self.common()
        d.update(self.info.get('props', {}))
        return d

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v() if callable(v) and not isinstance(v, (Obj, FH)) else v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls}'.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        from ..display import summary
        keys = ['ResponseName', 'ClassNames', 'NumObservations'] if not self.regression else ['ResponseName', 'NumObservations']
        keys += [k for k in self.info.get('show', [])]
        P = self.props()
        w = max(len(k) for k in keys)
        lines = [f'  {self.cls}', '']
        for k in keys:
            v = P[k]
            v = v() if callable(v) and not isinstance(v, (Obj, FH)) else v
            lines.append(f'    {k.rjust(w)}: {summary(v)}')
        return lines


class Partitioned(Obj):
    """A cross-validated model: one model for each training set of a partition."""
    is_handle = False

    def __init__(self, base, cvp, models, regression):
        self.base, self.cvp, self.models, self.regression = base, cvp, models, regression

    @property
    def cls(self):
        return 'RegressionPartitionedModel' if self.regression else 'ClassificationPartitionedModel'

    def getprop(self, name):
        k = name.lower()
        if k == 'trained':
            return Cell.of_list(self.models, (len(self.models), 1))
        if k == 'kfold':
            return float(len(self.models))
        if k == 'partition':
            return self.cvp
        if k in ('crossvalidatedmodel', 'modeltype'):
            return Char.of(self.base.cls.replace('Classification', '').replace('Regression', ''))
        return self.base.getprop(name)

    def propnames(self):
        return ['CrossValidatedModel', 'PredictorNames', 'ResponseName', 'NumObservations', 'KFold', 'Partition', 'Trained']

    def display_lines(self):
        return [f'  {self.cls}', '', f'    CrossValidatedModel: {self.base.cls}', f'          KFold: {len(self.models)}',
                f'    NumObservations: {self.base.X.shape[0]}']

    def fold_predictions(self):
        n = self.base.X.shape[0]
        K = 0 if self.regression else self.base.y.K
        S = np.full((n,) if self.regression else (n, K), np.nan)
        for i, m in enumerate(self.models):
            te = self.cvp.test_idx(i)
            if te.size:
                S[te] = m.scores(self.base.X[te])
        return S


def _model(v, fn):
    if not isinstance(v, Model):
        raise err(f'stats:{fn}:model', f'{fn} takes a classification or regression model.', fn)
    return v


# ---- partitions ------------------------------------------------------------------------------------------------------------------------------

class CVPartition(Obj):
    cls = 'cvpartition'

    def __init__(self, n, kind, k=None, p=None, group=None, stratify=True):
        self.n, self.kind, self.k, self.p, self.group, self.stratify = n, kind, k, p, group, stratify
        self.make()

    def make(self):
        rs = _rs()
        n = self.n
        if self.kind == 'kfold':
            fold = np.empty(n, int)
            if self.group is not None and self.stratify:
                for g in np.unique(self.group):
                    idx = np.flatnonzero(self.group == g)
                    perm = idx[rs.permutation(idx.size)]
                    start = rs.randint(self.k)
                    fold[perm] = (np.arange(idx.size) + start) % self.k
            else:
                perm = rs.permutation(n)
                fold[perm] = np.arange(n) % self.k
            self.fold = fold
            self.nsets = self.k
        elif self.kind == 'holdout':
            ntest = int(round(self.p * n)) if self.p < 1 else int(self.p)
            test = np.zeros(n, bool)
            if self.group is not None and self.stratify:
                for g in np.unique(self.group):
                    idx = np.flatnonzero(self.group == g)
                    m = int(round(ntest * idx.size / n))
                    test[idx[rs.permutation(idx.size)[:m]]] = True
            else:
                test[rs.permutation(n)[:ntest]] = True
            self.fold = np.where(test, 0, -1)
            self.nsets = 1
        elif self.kind == 'leaveout':
            self.fold = np.arange(n)
            self.nsets = n
        else:
            self.fold = None
            self.nsets = 1

    def test_mask(self, i):
        if self.kind == 'resubstitution':
            return np.ones(self.n, bool)
        return self.fold == i

    def train_mask(self, i):
        if self.kind == 'resubstitution':
            return np.ones(self.n, bool)
        return ~self.test_mask(i)

    def test_idx(self, i):
        return np.flatnonzero(self.test_mask(i))

    def getprop(self, name):
        k = name.lower()
        names = {'kfold': 'kfold', 'holdout': 'holdout', 'leaveout': 'leaveout', 'resubstitution': 'resubstitution'}
        if k == 'numobservations':
            return float(self.n)
        if k == 'numtestsets':
            return float(self.nsets)
        if k == 'trainsize':
            return out(np.array([[self.train_mask(i).sum() for i in range(self.nsets)]], float))
        if k == 'testsize':
            return out(np.array([[self.test_mask(i).sum() for i in range(self.nsets)]], float))
        if k == 'type':
            return Char.of(names[self.kind])
        if k == 'isstratified':
            return bool(self.group is not None and self.stratify)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'cvpartition'.")

    def propnames(self):
        return ['NumObservations', 'NumTestSets', 'TrainSize', 'TestSize', 'Type', 'IsStratified']

    def display_lines(self):
        title = {'kfold': 'K-fold cross validation partition', 'holdout': 'Hold-out cross validation partition',
                 'leaveout': 'Leave-one-out cross validation partition', 'resubstitution': 'Resubstitution (no partition of data)'}[self.kind]
        tr = ' '.join(str(int(self.train_mask(i).sum())) for i in range(min(self.nsets, 10)))
        te = ' '.join(str(int(self.test_mask(i).sum())) for i in range(min(self.nsets, 10)))
        return [title, f'   NumObservations: {self.n}', f'       NumTestSets: {self.nsets}', f'         TrainSize: {tr}', f'          TestSize: {te}']


@bi('cvpartition')
def cvpartition(nargout, *args):
    """c = cvpartition(n, 'KFold', k), cvpartition(group, 'KFold', k), cvpartition(n, 'HoldOut', p), cvpartition(n, 'Leaveout'), cvpartition(n, 'Resubstitution'), cvpartition(group, ..., 'Stratify', tf): a partition of observations into training and test sets (by group in proportion, when a grouping is given)."""
    nargchk(args, 1, 5, 'cvpartition')
    first = args[0]
    group = None
    if (isinstance(first, (float, int)) or (isinstance(first, np.ndarray) and first.size == 1)) and not isinstance(first, bool):
        n = _int(first)
    else:
        labs = Labels(first, 'cvpartition')
        group = labs.idx
        n = group.size
    kind = py_str(args[1]).lower() if len(args) > 1 else 'kfold'
    rest = list(args[2:])
    strat = True
    if len(rest) >= 2 and is_str(rest[-2]) and py_str(rest[-2]).lower() == 'stratify':
        strat = _flag(rest[-1])
        rest = rest[:-2]
    if kind == 'kfold':
        k = _int(rest[0]) if rest else 10
        if k > n:
            raise err('stats:cvpartition:KTooLarge', 'k is at most the number of observations.', 'cvpartition')
        return CVPartition(n, 'kfold', k=k, group=group, stratify=strat)
    if kind == 'holdout':
        p = float(num(rest[0])) if rest else 0.1
        return CVPartition(n, 'holdout', p=p, group=group, stratify=strat)
    if kind == 'leaveout':
        return CVPartition(n, 'leaveout')
    if kind == 'resubstitution':
        return CVPartition(n, 'resubstitution')
    raise err('stats:cvpartition:type', "The partition is 'KFold', 'HoldOut', 'Leaveout' or 'Resubstitution'.", 'cvpartition')


def _cvp(v, fn):
    if not isinstance(v, CVPartition):
        raise err(f'stats:{fn}:cvpartition', f'{fn} takes a cvpartition.', fn)
    return v


@bi('training')
def training(nargout, *args):
    """idx = training(c), training(c, i): which observations are in training set i of a partition (a logical column)."""
    nargchk(args, 1, 2, 'training')
    c = _cvp(args[0], 'training')
    i = _int(args[1]) - 1 if len(args) > 1 else 0
    if not 0 <= i < c.nsets:
        raise err('stats:cvpartition:index', f'The partition has {c.nsets} sets.', 'training')
    return out(c.train_mask(i).reshape(-1, 1))


@bi('test')
def test(nargout, *args):
    """idx = test(c), test(c, i): which observations are in test set i of a partition (a logical column)."""
    nargchk(args, 1, 2, 'test')
    c = _cvp(args[0], 'test')
    i = _int(args[1]) - 1 if len(args) > 1 else 0
    if not 0 <= i < c.nsets:
        raise err('stats:cvpartition:index', f'The partition has {c.nsets} sets.', 'test')
    return out(c.test_mask(i).reshape(-1, 1))


@bi('repartition')
def repartition(nargout, *args):
    """cnew = repartition(c): a new random partition of the same kind."""
    nargchk(args, 1, 1, 'repartition')
    c = _cvp(args[0], 'repartition')
    return CVPartition(c.n, c.kind, c.k, c.p, c.group, c.stratify)


# ---- fitting each kind of model ---------------------------------------------------------------------------------------------------------

TREE_OPTS = ('maxnumsplits', 'minleafsize', 'minparentsize', 'splitcriterion', 'numvariablestosample', 'prune', 'mergeleaves', 'surrogate',
             'predictorselection', 'reproducible', 'quadraticerrortolerance', 'maxdepth')


def _tree_learner(o, K, n, regression, defaults=None):
    d = defaults or {}
    ms = _int(o['maxnumsplits']) if 'maxnumsplits' in o else d.get('maxnumsplits', n - 1)
    ml = _int(o['minleafsize']) if 'minleafsize' in o else d.get('minleafsize', 1)
    mp = _int(o['minparentsize']) if 'minparentsize' in o else d.get('minparentsize', 10)
    crit = py_str(o.get('splitcriterion', Char.of('gdi'))).lower()
    if crit not in ('gdi', 'deviance', 'mse'):
        raise err('stats:fitctree:SplitCriterion', "SplitCriterion is 'gdi' or 'deviance' ('mse' for regression).", 'fitctree')
    nv = o.get('numvariablestosample', d.get('nvars'))
    nv = None if nv is None or (is_str(nv) and py_str(nv).lower() == 'all') else _int(nv)
    return dict(K=0 if regression else K, max_splits=ms, min_leaf=ml, min_parent=max(mp, 2 * ml), criterion=crit, nvars=nv, rs=_rs())


def _tree_props(t, labs, preds, regression):
    m = t.cut_var.size
    props = {'NumNodes': float(m), 'CutPredictor': Cell.of_list([Char.of(preds[j] if j >= 0 else '') for j in t.cut_var], (m, 1)),
             'CutPoint': out(t.cut_pt.reshape(-1, 1)), 'Children': out(np.where(t.children >= 0, t.children + 1.0, 0.0)),
             'IsBranchNode': out((t.cut_var >= 0).reshape(-1, 1)), 'Parent': out((t.parent + 1.0).reshape(-1, 1)),
             'NodeSize': out(t.size.reshape(-1, 1).astype(float)), 'NodeRisk': out(t.risk.reshape(-1, 1) / max(t.size[0], 1))}
    if regression:
        props['NodeMean'] = out(t.value.reshape(-1, 1))
    else:
        props['NodeClass'] = labs.value(np.argmax(t.value, axis=1))
        props['ClassProbability'] = out(t.value)
    return props


def _fit_tree(X, y, w, o, labs, regression):
    K = 0 if regression else labs.K
    t = LN.Tree(**_tree_learner(o, K, X.shape[0], regression)).fit(X, y if regression else labs.idx, w)
    return t


@bi('fitctree')
def fitctree(nargout, *args):
    """Mdl = fitctree(X, Y), fitctree(Tbl, ResponseVarName), fitctree(Tbl, formula), fitctree(..., 'MaxNumSplits', n, 'MinLeafSize', m, 'MinParentSize', p, 'SplitCriterion', 'gdi'|'deviance', 'NumVariablesToSample', k, 'CrossVal', 'on', 'KFold', k): a classification tree (CART)."""
    return _fit('tree', False, args, 'fitctree')


@bi('fitrtree')
def fitrtree(nargout, *args):
    """Mdl = fitrtree(X, Y), fitrtree(Tbl, ...), fitrtree(..., 'MaxNumSplits', n, 'MinLeafSize', m, 'MinParentSize', p): a regression tree (CART, by the squared error)."""
    return _fit('tree', True, args, 'fitrtree')


KNN_OPTS = ('numneighbors', 'distance', 'distanceweight', 'exponent', 'cov', 'scale', 'breakties', 'nsmethod', 'bucketsize', 'includeties')
DISC_OPTS = ('discrimtype', 'gamma', 'delta', 'fillcoeffs', 'savememory')
NB_OPTS = ('distributionnames', 'kernel', 'width', 'support')
SVM_OPTS = ('kernelfunction', 'boxconstraint', 'kernelscale', 'polynomialorder', 'epsilon', 'deltagradienttolerance', 'iterationlimit',
            'solver', 'outlierfraction', 'nu', 'kernelscale', 'cachesize', 'shrinkageperiod', 'kernelOffset'.lower(), 'gaptolerance', 'kkttolerance')
LIN_OPTS = ('learner', 'lambda', 'regularization', 'solver', 'iterationlimit', 'epsilon', 'betatolerance', 'gradienttolerance', 'fitbias', 'beta', 'bias', 'observationsin')
NET_OPTS = ('layersizes', 'activations', 'lambda', 'iterationlimit', 'layerweightsinitializer', 'layerbiasesinitializer', 'validationdata',
            'losstolerance', 'gradienttolerance', 'steptolerance', 'outputlayeractivation')
GP_OPTS = ('kernelfunction', 'basisfunction', 'sigma', 'kernelparameters', 'fitmethod', 'predictmethod', 'constantsigma', 'sigmalowerbound',
           'activesetsize', 'beta', 'optimizer')
KERN_OPTS = ('learner', 'numexpansiondimensions', 'kernelscale', 'lambda', 'iterationlimit', 'epsilon', 'boxconstraint')
ENS_OPTS = ('method', 'numlearningcycles', 'learners', 'learnrate', 'nprint', 'resample', 'replace', 'fresample', 'numbins')
ECOC_OPTS = ('learners', 'coding', 'fitposterior', 'binaryloss')


def _svm_learner(X, y01, o, regression, yr=None):
    kind = py_str(o.get('kernelfunction', Char.of('linear'))).lower()
    kind = {'rbf': 'gaussian'}.get(kind, kind)
    if kind not in ('linear', 'gaussian', 'polynomial'):
        raise err('stats:fitcsvm:KernelFunction', "KernelFunction is 'linear', 'gaussian' (or 'rbf') or 'polynomial'.", 'fitcsvm')
    std = _flag(o['standardize']) if 'standardize' in o else False
    if regression:
        q = np.subtract(*np.percentile(yr, [75, 25]))
        C = float(num(o['boxconstraint'])) if 'boxconstraint' in o else (q / 1.349 if q > 0 else 1.0)
        eps = float(num(o['epsilon'])) if 'epsilon' in o else (q / 13.49 if q > 0 else 0.1)
    else:
        C = float(num(o.get('boxconstraint', 1.0)))
        eps = 0.1
    sc = o.get('kernelscale', 1.0)
    if is_str(sc):
        Z = (X - X.mean(0)) / np.where(X.std(0, ddof=1) > 0, X.std(0, ddof=1), 1) if std else X
        from scipy.spatial.distance import pdist as sp_pdist
        sub = Z[_rs().choice(Z.shape[0], min(Z.shape[0], 200), replace=False)]
        scale = float(np.median(sp_pdist(sub))) or 1.0
    else:
        scale = float(num(sc))
    tol = float(num(o.get('deltagradienttolerance', 1e-3)))
    svm = LN.SVM(regression, kind, C, scale, _int(o.get('polynomialorder', 3.0)), eps, std, tol)
    svm.fit(X, yr if regression else y01)
    return svm, kind, C, scale, eps


def _ecoc_fit(X, labs, o, w):
    K = labs.K
    coding = py_str(o.get('coding', Char.of('onevsone'))).lower()
    if coding == 'onevsone':
        cols = [(i, j) for i in range(K) for j in range(i + 1, K)]
        M = np.zeros((K, len(cols)))
        for c, (i, j) in enumerate(cols):
            M[i, c], M[j, c] = 1, -1
    elif coding in ('onevsall', 'binarycomplete', 'ordinal'):
        if coding == 'onevsall':
            M = -np.ones((K, K)) + 2 * np.eye(K)
        elif coding == 'ordinal':
            M = np.array([[1 if r > c else -1 for c in range(K - 1)] for r in range(K)], float)
        else:
            cols_ = []
            for code in range(1, 2 ** (K - 1)):
                bits = [(code >> b) & 1 for b in range(K - 1)]
                cols_.append([1] + [1 if b else -1 for b in bits])
            M = np.array(cols_, float).T
    else:
        raise err('stats:fitcecoc:Coding', "Coding is 'onevsone', 'onevsall', 'binarycomplete' or 'ordinal'.", 'fitcecoc')
    lrn = o.get('learners', Char.of('svm'))
    tmpl = lrn if isinstance(lrn, Template) else Template(py_str(lrn).lower(), {})
    binaries = []
    for c in range(M.shape[1]):
        pos, neg = M[:, c] > 0, M[:, c] < 0
        use = pos[labs.idx] | neg[labs.idx]
        yb = np.where(pos[labs.idx[use]], 1, 0)
        binaries.append(_binary_learner(tmpl, X[use], yb, None if w is None else w[use]))
    return M, binaries, tmpl.kind


def _binary_learner(tmpl, X, yb, w):
    """A two-class learner from a template: its signed score function (positive for class 1)."""
    o = tmpl.opts
    k = tmpl.kind
    if k == 'svm':
        svm = _svm_learner(X, yb, o, False)[0]
        return ('margin', svm.decision)
    if k == 'linear':
        lin = _linear_learner(X, yb, o, False, None)
        return ('margin', lin.decision)
    if k == 'tree':
        t = LN.Tree(**_tree_learner(o, 2, X.shape[0], False, {'maxnumsplits': X.shape[0] - 1})).fit(X, yb, w)
        return ('prob', lambda Z: t.predict(Z)[:, 1])
    if k == 'knn':
        m = LN.KNN(2, _int(o.get('numneighbors', 1.0)), py_str(o.get('distance', Char.of('euclidean'))).lower(), None,
                   py_str(o.get('distanceweight', Char.of('equal'))).lower(), _flag(o['standardize']) if 'standardize' in o else False).fit(X, yb)
        return ('prob', lambda Z: m.predict(Z)[:, 1])
    if k == 'discriminant':
        d = LN.Discriminant(2, py_str(o.get('discrimtype', Char.of('linear')))).fit(X, yb)
        return ('prob', lambda Z: d.predict(Z)[:, 1])
    if k == 'naivebayes':
        nb = LN.NaiveBayes(2, ['normal'] * X.shape[1]).fit(X, yb)
        return ('prob', lambda Z: nb.predict(Z)[:, 1])
    raise err('stats:fitcecoc:Learners', "The learners are 'svm', 'linear', 'tree', 'knn', 'discriminant', 'naivebayes', or a template.", 'fitcecoc')


def _ecoc_scores(M, binaries, X):
    """Loss-weighted decoding: the negated mean binary loss (hinge on margins, quadratic on probabilities turned to [-1, 1])."""
    S = np.column_stack([fn(X) if kind == 'margin' else 2 * fn(X) - 1 for kind, fn in binaries])
    K = M.shape[0]
    scores = np.empty((X.shape[0], K))
    for k in range(K):
        m = M[k]
        used = m != 0
        if binaries and binaries[0][0] == 'margin':
            loss = np.maximum(0, 1 - m[used][None, :] * S[:, used]) / 2
        else:
            loss = (1 - m[used][None, :] * S[:, used]) ** 2 / 2
        scores[:, k] = -loss.mean(1)
    return scores


def _linear_learner(X, y, o, regression, yr):
    n = X.shape[0]
    learner = py_str(o.get('learner', Char.of('svm'))).lower()
    lam = o.get('lambda', 1.0 / n)
    lam = float(num(lam)) if not is_str(lam) else 1.0 / n
    reg = py_str(o.get('regularization', Char.of('ridge'))).lower()
    if regression:
        if learner not in ('svm', 'leastsquares'):
            raise err('stats:fitrlinear:Learner', "The learner is 'svm' or 'leastsquares'.", 'fitrlinear')
        q = np.subtract(*np.percentile(yr, [75, 25]))
        eps = float(num(o['epsilon'])) if 'epsilon' in o else (q / 13.49 if q > 0 else 0.1)
        return LN.Linear(True, learner, lam, reg, eps, _int(o.get('iterationlimit', 1000.0))).fit(X, yr)
    if learner not in ('svm', 'logistic'):
        raise err('stats:fitclinear:Learner', "The learner is 'svm' or 'logistic'.", 'fitclinear')
    return LN.Linear(False, learner, lam, reg, maxit=_int(o.get('iterationlimit', 1000.0))).fit(X, y)


def _ensemble(X, y, labs, o, regression, w):
    """(score function, method, learners list, info): bagged trees or boosting."""
    K = 0 if regression else labs.K
    n, p = X.shape
    method = py_str(o.get('method', Char.of('LSBoost' if regression else ('AdaBoostM1' if K == 2 else 'AdaBoostM2')))).lower()
    T = _int(o.get('numlearningcycles', 100.0))
    lr = float(num(o.get('learnrate', 1.0)))
    tmpl = o.get('learners', Char.of('tree'))
    topts = tmpl.opts if isinstance(tmpl, Template) else {}
    rs = _rs()
    yi = y if regression else labs.idx
    if method == 'bag':
        nv = topts.get('numvariablestosample')
        nvars = max(1, int(round(p / 3))) if regression else max(1, int(math.floor(math.sqrt(p))))
        if nv is not None:
            nvars = p if is_str(nv) else _int(nv)
        trees, oob = [], []
        for _ in range(T):
            boot = rs.randint(0, n, n)
            inbag = np.zeros(n, bool)
            inbag[boot] = True
            t = LN.Tree(**_tree_learner(topts, K, n, regression, {'minleafsize': 5 if regression else 1, 'minparentsize': 10 if regression else 2, 'nvars': nvars})).fit(X[boot], yi[boot])
            trees.append(t)
            oob.append(~inbag)

        def score(Z):
            v = np.mean([t.predict(Z) for t in trees], axis=0)
            return v
        return score, 'Bag', trees, {'oob': np.array(oob), 'trees': trees}
    weak = {'maxnumsplits': 10, 'minleafsize': 1 if not regression else 5, 'minparentsize': 2 if not regression else 10}
    trees, alphas = [], []
    if regression:
        if method != 'lsboost':
            raise err('stats:fitrensemble:Method', "For regression the method is 'LSBoost' or 'Bag'.", 'fitrensemble')
        F0 = float(np.mean(y))
        F = np.full(n, F0)
        for _ in range(T):
            t = LN.Tree(**_tree_learner(topts, 0, n, True, weak)).fit(X, y - F)
            F += lr * t.predict(X)
            trees.append(t)

        def score(Z):
            return F0 + lr * np.sum([t.predict(Z) for t in trees], axis=0)
        return score, 'LSBoost', trees, {}
    if method in ('adaboostm1', 'gentleboost', 'logitboost') and K != 2:
        raise err('stats:fitcensemble:Method', f"{method} takes two classes: for more, 'AdaBoostM2' or 'Bag'.", 'fitcensemble')
    wts = np.full(n, 1 / n) if w is None else np.asarray(w, float) / np.sum(w)
    if method == 'adaboostm1':
        ys = np.where(yi == 1, 1.0, -1.0)
        for _ in range(T):
            t = LN.Tree(**_tree_learner(topts, 2, n, False, weak)).fit(X, yi, wts * n)
            h = np.where(np.argmax(t.predict(X), 1) == 1, 1.0, -1.0)
            e = float(np.sum(wts[h != ys]))
            if e >= 0.5:
                break
            e = max(e, 1e-10)
            a = lr * 0.5 * math.log((1 - e) / e)
            wts = wts * np.exp(-a * ys * h)
            wts /= wts.sum()
            trees.append(t)
            alphas.append(a)
            if e <= 1e-10:
                break

        def score(Z):
            f = sum(a * np.where(np.argmax(t.predict(Z), 1) == 1, 1.0, -1.0) for t, a in zip(trees, alphas)) if trees else np.zeros(Z.shape[0])
            return np.column_stack([-f, f])
        return score, 'AdaBoostM1', trees, {}
    if method == 'adaboostm2':
        # multiclass AdaBoost by SAMME (Zhu, Zou, Rosset and Hastie)
        for _ in range(T):
            t = LN.Tree(**_tree_learner(topts, K, n, False, weak)).fit(X, yi, wts * n)
            h = np.argmax(t.predict(X), 1)
            e = float(np.sum(wts[h != yi]))
            if e >= 1 - 1 / K:
                break
            e = max(e, 1e-10)
            a = lr * (math.log((1 - e) / e) + math.log(K - 1))
            wts = wts * np.exp(a * (h != yi))
            wts /= wts.sum()
            trees.append(t)
            alphas.append(a)
            if e <= 1e-10:
                break

        def score(Z):
            S = np.zeros((Z.shape[0], K))
            for t, a in zip(trees, alphas):
                S[np.arange(Z.shape[0]), np.argmax(t.predict(Z), 1)] += a
            return S / max(sum(alphas), 1e-300)
        return score, 'AdaBoostM2', trees, {}
    if method in ('gentleboost', 'logitboost'):
        ys = np.where(yi == 1, 1.0, -1.0)
        F = np.zeros(n)
        for _ in range(T):
            if method == 'gentleboost':
                ww = np.exp(-ys * F)
                ww /= ww.sum()
                t = LN.Tree(**_tree_learner(topts, 0, n, True, weak)).fit(X, ys, ww * n)
            else:
                pr = 1 / (1 + np.exp(-2 * F))
                ww = np.maximum(pr * (1 - pr), 1e-10)
                z = np.clip(((ys + 1) / 2 - pr) / ww, -4, 4)
                t = LN.Tree(**_tree_learner(topts, 0, n, True, weak)).fit(X, z, ww * n / ww.sum())
            step = t.predict(X) * (1 if method == 'gentleboost' else 0.5)
            F += lr * step
            trees.append(t)
        half = 1 if method == 'gentleboost' else 0.5

        def score(Z):
            f = lr * half * np.sum([t.predict(Z) for t in trees], axis=0)
            return np.column_stack([-f, f])
        return score, 'GentleBoost' if method == 'gentleboost' else 'LogitBoost', trees, {}
    raise err('stats:fitcensemble:Method', "The method is 'AdaBoostM1', 'AdaBoostM2', 'GentleBoost', 'LogitBoost' or 'Bag'.", 'fitcensemble')


NAMES = {('tree', False): 'ClassificationTree', ('tree', True): 'RegressionTree', ('knn', False): 'ClassificationKNN',
         ('discriminant', False): 'ClassificationDiscriminant', ('naivebayes', False): 'ClassificationNaiveBayes', ('svm', False): 'ClassificationSVM',
         ('svm', True): 'RegressionSVM', ('ecoc', False): 'ClassificationECOC', ('ensemble', False): 'ClassificationEnsemble',
         ('ensemble', True): 'RegressionEnsemble', ('linear', False): 'ClassificationLinear', ('linear', True): 'RegressionLinear',
         ('net', False): 'ClassificationNeuralNetwork', ('net', True): 'RegressionNeuralNetwork', ('gp', True): 'RegressionGP',
         ('kernel', False): 'ClassificationKernel', ('kernel', True): 'RegressionKernel'}
OWN = {'tree': TREE_OPTS, 'knn': KNN_OPTS, 'discriminant': DISC_OPTS, 'naivebayes': NB_OPTS, 'svm': SVM_OPTS, 'ecoc': ECOC_OPTS,
       'ensemble': ENS_OPTS + TREE_OPTS, 'linear': LIN_OPTS, 'net': NET_OPTS, 'gp': GP_OPTS, 'kernel': KERN_OPTS}


def _train(kind, regression, X, y, labs, o, w, preds):
    """(score function, information about the fit) for one kind of model."""
    n, p = X.shape
    info = {'show': []}
    if kind == 'tree':
        t = _fit_tree(X, y, w, o, labs, regression)
        info['props'] = _tree_props(t, labs, preds, regression)
        info['tree'] = t
        info['show'] = ['NumNodes']
        return (t.predict if not regression else t.predict), info
    if kind == 'knn':
        k = _int(o.get('numneighbors', 1.0))
        dist = py_str(o.get('distance', Char.of('euclidean'))).lower() if not isinstance(o.get('distance'), FH) else 'euclidean'
        kw = {}
        if dist == 'minkowski':
            kw['p'] = float(num(o.get('exponent', 2.0)))
        m = LN.KNN(labs.K, k, dist, kw, py_str(o.get('distanceweight', Char.of('equal'))).lower(),
                   _flag(o['standardize']) if 'standardize' in o else False, _prior(o, labs, labs.idx)).fit(X, labs.idx, w)
        info['props'] = {'NumNeighbors': float(k), 'Distance': Char.of(dist), 'DistanceWeight': Char.of(m.weight), 'Mu': out(m.mu.reshape(1, -1)), 'Sigma': out(m.sd.reshape(1, -1))}
        info['show'] = ['NumNeighbors', 'Distance']
        return m.predict, info
    if kind == 'discriminant':
        dt = py_str(o.get('discrimtype', Char.of('linear')))
        if dt.lower() not in ('linear', 'quadratic', 'diaglinear', 'diagquadratic', 'pseudolinear', 'pseudoquadratic'):
            raise err('stats:fitcdiscr:DiscrimType', "DiscrimType is 'linear', 'quadratic', 'diagLinear', 'diagQuadratic', 'pseudoLinear' or 'pseudoQuadratic'.", 'fitcdiscr')
        d = LN.Discriminant(labs.K, dt.lower().replace('pseudo', ''), _prior(o, labs, labs.idx), float(num(o.get('gamma', 0.0)))).fit(X, labs.idx)
        Sg = d.Sigma[0] if dt.lower() in ('linear', 'diaglinear', 'pseudolinear') else np.transpose(d.Sigma, (1, 2, 0))
        info['props'] = {'DiscrimType': Char.of(dt), 'Mu': out(d.mu), 'Sigma': out(Sg), 'Gamma': float(num(o.get('gamma', 0.0)))}
        info['prior'] = d.prior
        info['show'] = ['DiscrimType']
        return d.predict, info
    if kind == 'naivebayes':
        dn = o.get('distributionnames', Char.of('normal'))
        names = [py_str(dn).lower()] * p if is_str(dn) else [str(s).lower() for s in text_list(dn)]
        for nm in names:
            if nm not in ('normal', 'kernel', 'mvmn', 'mn'):
                raise err('stats:fitcnb:DistributionNames', "DistributionNames are 'normal', 'kernel', 'mvmn' or 'mn'.", 'fitcnb')
        width = float(num(o['width'])) if 'width' in o else None
        nb = LN.NaiveBayes(labs.K, names, _prior(o, labs, labs.idx), width).fit(X, labs.idx)
        params = Cell.empty((labs.K, p))
        for j in range(p):
            for c in range(labs.K):
                prm = nb.params[j][c]
                if names[j] == 'normal':
                    params.a[c, j] = out(np.array([[prm[0]], [prm[1]]]))
                elif names[j] == 'mvmn':
                    params.a[c, j] = out(prm[1].reshape(-1, 1))
                else:
                    params.a[c, j] = EMPTY()
        info['props'] = {'DistributionNames': Cell.of_list([Char.of(s) for s in names]), 'DistributionParameters': params}
        info['prior'] = nb.prior
        info['show'] = ['DistributionNames']
        return nb.predict, info
    if kind == 'svm':
        if regression:
            svm, kf, C, scale, eps = _svm_learner(X, None, o, True, y)
            info['epsilon'] = eps
            sc = svm.decision
        else:
            if labs.K != 2:
                raise err('stats:fitcsvm:NotBinary', f'fitcsvm takes two classes ({labs.K} here): fitcecoc takes more.', 'fitcsvm')
            svm, kf, C, scale, eps = _svm_learner(X, labs.idx, o, False)

            def sc(Z, svm=svm):
                f = svm.decision(Z)
                return np.column_stack([-f, f])
        sv = svm.is_sv
        info['props'] = {'Alpha': out(np.abs(svm.alpha).reshape(-1, 1)) if not regression else out(svm.alpha.reshape(-1, 1)),
                         'Bias': float(svm.bias), 'SupportVectors': out(svm.sv * svm.sd + svm.mu), 'IsSupportVector': out(sv.reshape(-1, 1)),
                         'KernelParameters': Struct.scalar({'Function': Char.of(kf), 'Scale': float(scale)}), 'BoxConstraints': out(np.full((n, 1), C)),
                         'NumIterations': float(svm.iters), 'Beta': out(svm.beta.reshape(-1, 1) / svm.sd.reshape(-1, 1)) if kf == 'linear' else EMPTY()}
        if regression:
            info['props']['Epsilon'] = eps
        info['show'] = ['Alpha', 'Bias', 'KernelParameters']
        return sc, info
    if kind == 'ecoc':
        M, binaries, lk = _ecoc_fit(X, labs, o, w)
        info['props'] = {'CodingMatrix': out(M), 'NumBinaryLearners': float(M.shape[1]), 'BinaryLearnerType': Char.of(lk)}
        info['show'] = ['CodingMatrix']
        return (lambda Z: _ecoc_scores(M, binaries, Z)), info
    if kind == 'ensemble':
        score, method, trees, extra = _ensemble(X, y if regression else None, labs, o, regression, w)
        info['props'] = {'Method': Char.of(method), 'NumTrained': float(len(trees)),
                         'Trained': Cell.of_list([_tree_model(t, X, y, labs, preds) for t in trees], (len(trees), 1)) if len(trees) <= 500 else EMPTY()}
        info.update(extra)
        info['show'] = ['Method', 'NumTrained']
        return score, info
    if kind == 'linear':
        lin = _linear_learner(X, labs.idx if not regression else None, o, regression, y)
        info['props'] = {'Beta': out(lin.beta.reshape(-1, 1)), 'Bias': float(lin.bias), 'Lambda': float(lin.lam),
                         'Learner': Char.of(lin.learner), 'Regularization': Char.of(lin.reg)}
        info['show'] = ['Beta', 'Bias', 'Lambda', 'Learner']
        if regression:
            info['epsilon'] = lin.epsilon
            return lin.decision, info

        def sc(Z, lin=lin):
            f = lin.decision(Z)
            return np.column_stack([-f, f])
        if labs.K != 2:
            raise err('stats:fitclinear:NotBinary', 'fitclinear takes two classes: fitcecoc with templateLinear takes more.', 'fitclinear')
        return sc, info
    if kind == 'net':
        ls = np.asarray(darr(o.get('layersizes', 10.0)), float).reshape(-1).astype(int)
        act = py_str(o.get('activations', Char.of('relu'))).lower()
        if act not in ('relu', 'tanh', 'sigmoid', 'none'):
            raise err('stats:fitcnet:Activations', "Activations is 'relu', 'tanh', 'sigmoid' or 'none'.", 'fitcnet')
        net = LN.MLP(0 if regression else labs.K, tuple(ls), act, float(num(o.get('lambda', 0.0))), _int(o.get('iterationlimit', 1000.0)),
                     _flag(o['standardize']) if 'standardize' in o else False, _rs()).fit(X, y if regression else labs.idx, w)
        Ws, bs = net._unpack(net.z)
        info['props'] = {'LayerSizes': out(ls.reshape(1, -1).astype(float)), 'Activations': Char.of(act),
                         'LayerWeights': Cell.of_list([out(W.T) for W in Ws], (1, len(Ws))), 'LayerBiases': Cell.of_list([out(b.reshape(-1, 1)) for b in bs], (1, len(bs))),
                         'TrainingHistory': Struct.scalar({'Loss': float(net.loss), 'Iterations': float(net.iters)})}
        info['show'] = ['LayerSizes', 'Activations']
        return net.predict, info
    if kind == 'gp':
        kf = py_str(o.get('kernelfunction', Char.of('squaredexponential'))).lower()
        if kf not in ('squaredexponential', 'exponential', 'matern32', 'matern52', 'rationalquadratic', 'ardsquaredexponential'):
            raise err('stats:fitrgp:KernelFunction', "KernelFunction is 'squaredexponential', 'exponential', 'matern32', 'matern52', 'rationalquadratic' or 'ardsquaredexponential'.", 'fitrgp')
        basis = py_str(o.get('basisfunction', Char.of('constant'))).lower()
        fit_m = py_str(o.get('fitmethod', Char.of('exact'))).lower()
        th0 = np.asarray(darr(o['kernelparameters']), float).reshape(-1) if 'kernelparameters' in o else None
        gp = LN.GP(kf, basis, float(num(o['sigma'])) if 'sigma' in o else None, th0, fit_m != 'none',
                   _flag(o['standardize']) if 'standardize' in o else False).fit(X, y)
        kp = np.exp(gp.params[:-1])
        info['props'] = {'KernelFunction': Char.of(kf), 'KernelInformation': Struct.scalar({'Name': Char.of(kf), 'KernelParameters': out(kp.reshape(-1, 1))}),
                         'Sigma': float(gp.sigma), 'Beta': out(gp.beta.reshape(-1, 1)), 'LogLikelihood': -float(gp.nll), 'BasisFunction': Char.of(basis)}
        info['gp'] = gp
        info['show'] = ['KernelFunction', 'Sigma', 'LogLikelihood']
        return gp.predict, info
    if kind == 'kernel':
        m_ = o.get('numexpansiondimensions', Char.of('auto'))
        m = int(2 ** math.ceil(min(math.log2(max(p, 1)) + 5, 15))) if is_str(m_) else _int(m_)
        sc_ = o.get('kernelscale', 1.0)
        scale = float(np.median(np.std(X, axis=0, ddof=1))) if is_str(sc_) else float(num(sc_))
        feats = LN.Features(m, scale, _rs()).fit(p)
        Phi = feats(X)
        lo = dict(o)
        lo.setdefault('learner', Char.of('svm'))
        lin = _linear_learner(Phi, labs.idx if not regression else None, lo, regression, y)
        info['props'] = {'NumExpansionDimensions': float(m), 'KernelScale': float(scale), 'Lambda': float(lin.lam), 'Learner': Char.of(lin.learner)}
        info['show'] = ['NumExpansionDimensions', 'KernelScale', 'Lambda', 'Learner']
        if regression:
            info['epsilon'] = lin.epsilon
            return (lambda Z: lin.decision(feats(Z))), info
        if labs.K != 2:
            raise err('stats:fitckernel:NotBinary', 'fitckernel takes two classes.', 'fitckernel')
        return (lambda Z: np.column_stack([-lin.decision(feats(Z)), lin.decision(feats(Z))])), info
    raise ValueError(kind)


def _tree_model(t, X, y, labs, preds):
    """One tree of an ensemble as a model of its own (boosted classifiers grow regression trees)."""
    reg = t.K == 0
    yy = (y if y is not None else labs.idx.astype(float)) if reg else labs
    return Model(NAMES[('tree', reg)], reg, X, yy, preds, 'Y', (lambda Z, t=t: t.predict(Z)), {'props': _tree_props(t, labs, preds, reg), 'tree': t})


def _crossval_opts(o):
    for k in ('crossval', 'kfold', 'holdout', 'leaveout', 'cvpartition'):
        if k in o:
            if k == 'crossval' and not _flag(o[k]):
                continue
            return k
    return None


def _make_partition(o, n, labs, regression):
    k = _crossval_opts(o)
    group = None if regression else labs.idx
    if k == 'cvpartition':
        c = _cvp(o['cvpartition'], 'crossval')
        if c.n != n:
            raise err('stats:crossval:size', 'The partition is of as many observations as the data.', 'crossval')
        return c
    if k == 'holdout':
        return CVPartition(n, 'holdout', p=float(num(o['holdout'])), group=group)
    if k == 'leaveout':
        return CVPartition(n, 'leaveout')
    kk = _int(o['kfold']) if 'kfold' in o else 10
    return CVPartition(n, 'kfold', k=kk, group=group)


def _fit(kind, regression, args, fn):
    X, y, preds, resp, o, keep = parse_data(args, fn, OWN[kind], regression)
    labs = None if regression else y
    w = _weights(o, keep)
    if not regression and labs.K < 1:
        raise err(f'stats:{fn}:NoClasses', 'Y has no classes.', fn)
    score, info = _train(kind, regression, X, y if regression else None, labs, o, w, preds)
    if not regression:
        info.setdefault('prior', _prior(o, labs, labs.idx))
    mdl = Model(NAMES[(kind, regression)], regression, X, y if regression else labs, preds, resp, score, info, w)
    mdl.kind = kind
    mdl.opts = o
    if _crossval_opts(o):
        c = _make_partition(o, X.shape[0], labs, regression)
        return _crossvalidate(mdl, c)
    return mdl


def _refit(mdl, X, y):
    """The same kind of model with the same options, on other data."""
    o = {k: v for k, v in mdl.opts.items() if k not in ('crossval', 'kfold', 'holdout', 'leaveout', 'cvpartition', 'weights')}
    labs = None
    if not mdl.regression:
        labs = mdl.y.__class__.__new__(mdl.y.__class__)
        labs.__dict__.update(mdl.y.__dict__)
        labs.idx = y
    score, info = _train(mdl.kind, mdl.regression, X, y if mdl.regression else None, labs, o, None, mdl.preds)
    m = Model(mdl.cls, mdl.regression, X, y if mdl.regression else labs, mdl.preds, mdl.resp, score, info)
    m.kind, m.opts = mdl.kind, mdl.opts
    return m


def _crossvalidate(mdl, c):
    models = []
    for i in range(c.nsets):
        tr = c.train_mask(i)
        yy = mdl.y[tr] if mdl.regression else mdl.y.idx[tr]
        models.append(_refit(mdl, mdl.X[tr], yy))
    return Partitioned(mdl, c, models, mdl.regression)


for _kind, _reg, _name, _doc in (
        ('knn', False, 'fitcknn', "Mdl = fitcknn(X, Y), fitcknn(..., 'NumNeighbors', k, 'Distance', d, 'DistanceWeight', 'equal'|'inverse'|'squaredinverse', 'Standardize', tf): a k-nearest-neighbour classifier."),
        ('discriminant', False, 'fitcdiscr', "Mdl = fitcdiscr(X, Y), fitcdiscr(..., 'DiscrimType', 'linear'|'quadratic'|'diagLinear'|'diagQuadratic'|'pseudoLinear', 'Gamma', g, 'Prior', p): discriminant analysis with normal classes."),
        ('naivebayes', False, 'fitcnb', "Mdl = fitcnb(X, Y), fitcnb(..., 'DistributionNames', 'normal'|'kernel'|'mvmn'|'mn', 'Width', w, 'Prior', p): a naive Bayes classifier."),
        ('svm', False, 'fitcsvm', "Mdl = fitcsvm(X, Y), fitcsvm(..., 'KernelFunction', 'linear'|'gaussian'|'polynomial', 'BoxConstraint', C, 'KernelScale', s|'auto', 'PolynomialOrder', q, 'Standardize', tf): a support vector machine for two classes."),
        ('svm', True, 'fitrsvm', "Mdl = fitrsvm(X, Y), fitrsvm(..., 'KernelFunction', k, 'BoxConstraint', C, 'Epsilon', e, 'KernelScale', s, 'Standardize', tf): support vector regression."),
        ('ecoc', False, 'fitcecoc', "Mdl = fitcecoc(X, Y), fitcecoc(..., 'Learners', t, 'Coding', 'onevsone'|'onevsall'|'binarycomplete'|'ordinal'): many classes by binary learners and an error-correcting output code."),
        ('ensemble', False, 'fitcensemble', "Mdl = fitcensemble(X, Y), fitcensemble(..., 'Method', 'AdaBoostM1'|'AdaBoostM2'|'GentleBoost'|'LogitBoost'|'Bag', 'NumLearningCycles', n, 'Learners', templateTree(...), 'LearnRate', r): an ensemble of classification trees."),
        ('ensemble', True, 'fitrensemble', "Mdl = fitrensemble(X, Y), fitrensemble(..., 'Method', 'LSBoost'|'Bag', 'NumLearningCycles', n, 'Learners', templateTree(...), 'LearnRate', r): an ensemble of regression trees."),
        ('linear', False, 'fitclinear', "Mdl = fitclinear(X, Y), fitclinear(..., 'Learner', 'svm'|'logistic', 'Lambda', l, 'Regularization', 'ridge'|'lasso'): a linear classifier for two classes."),
        ('linear', True, 'fitrlinear', "Mdl = fitrlinear(X, Y), fitrlinear(..., 'Learner', 'svm'|'leastsquares', 'Lambda', l, 'Regularization', 'ridge'|'lasso', 'Epsilon', e): a linear regression model with a penalty."),
        ('net', False, 'fitcnet', "Mdl = fitcnet(X, Y), fitcnet(..., 'LayerSizes', sizes, 'Activations', 'relu'|'tanh'|'sigmoid'|'none', 'Lambda', l, 'IterationLimit', n, 'Standardize', tf): a feedforward neural network classifier."),
        ('net', True, 'fitrnet', "Mdl = fitrnet(X, Y), fitrnet(..., 'LayerSizes', sizes, 'Activations', a, 'Lambda', l, 'IterationLimit', n, 'Standardize', tf): a feedforward neural network for regression."),
        ('gp', True, 'fitrgp', "Mdl = fitrgp(X, Y), fitrgp(..., 'KernelFunction', k, 'BasisFunction', 'constant'|'none'|'linear', 'Sigma', s, 'KernelParameters', theta, 'FitMethod', 'exact'|'none', 'Standardize', tf): Gaussian process regression."),
        ('kernel', False, 'fitckernel', "Mdl = fitckernel(X, Y), fitckernel(..., 'Learner', 'svm'|'logistic', 'NumExpansionDimensions', m, 'KernelScale', s, 'Lambda', l): a Gaussian-kernel classifier by random features."),
        ('kernel', True, 'fitrkernel', "Mdl = fitrkernel(X, Y), fitrkernel(..., 'Learner', 'svm'|'leastsquares', 'NumExpansionDimensions', m, 'KernelScale', s, 'Lambda', l): Gaussian-kernel regression by random features.")):
    def _mk(kind, reg, name):
        def f(nargout, *args):
            return _fit(kind, reg, args, name)
        return f
    _f = _mk(_kind, _reg, _name)
    _f.__doc__ = _doc
    bi(_name)(_f)


@bi('TreeBagger')
def TreeBagger(nargout, *args):
    """B = TreeBagger(n, X, Y, 'Method', 'classification'|'regression', 'NumPredictorsToSample', k, 'MinLeafSize', m): n trees grown on bootstrap samples, each split among k variables picked at random (a random forest)."""
    nargchk(args, 3, 30, 'TreeBagger')
    n = _int(args[0])
    a = list(args[1:])
    base, opts = a[:2], a[2:]
    if len(opts) % 2:
        raise err('stats:TreeBagger:pairs', 'The options of TreeBagger come as names and values.', 'TreeBagger')
    method = 'classification'
    tree_opts = {}
    for i in range(0, len(opts), 2):
        k = py_str(opts[i]).lower()
        if k == 'method':
            method = py_str(opts[i + 1]).lower()
        elif k == 'numpredictorstosample':
            tree_opts['numvariablestosample'] = opts[i + 1]
        elif k == 'minleafsize':
            tree_opts['minleafsize'] = opts[i + 1]
        elif k not in ('oobprediction', 'oobpredictorimportance', 'options', 'prior', 'samplewithreplacement', 'infraction'):
            raise err('stats:TreeBagger:option', f"'{py_str(opts[i])}' is not an option of TreeBagger.", 'TreeBagger')
    reg = method.startswith('r')
    m = _fit('ensemble', reg, tuple(base) + (Char.of('Method'), Char.of('Bag'), Char.of('NumLearningCycles'), float(n), Char.of('Learners'), Template('tree', tree_opts)), 'TreeBagger')
    m._cls = 'TreeBagger'
    m.info['treebagger'] = True
    return m


# ---- what is done with a model -----------------------------------------------------------------------------------------------------------

def _xmat(m, v, fn):
    from .tables import Table
    if isinstance(v, Table):
        return _table_cols(v, m.preds, fn)
    return np.asarray(darr(v), float)


def _predict(nargout, m, *rest):
    if not rest:
        raise MError('MATLAB:minrhs', 'Not enough input arguments.')
    X = _xmat(m, rest[0], 'predict')
    if m.cls == 'RegressionGP':
        gp = m.info['gp']
        mean, var = gp.predict(X, var=True)
        sd = np.sqrt(var + gp.sigma ** 2)
        alpha = 0.05
        o = {py_str(rest[i]).lower(): rest[i + 1] for i in range(1, len(rest) - 1, 2)}
        if 'alpha' in o:
            alpha = float(num(o['alpha']))
        from scipy.stats import norm
        z = norm.ppf(1 - alpha / 2)
        res = (out(mean.reshape(-1, 1)), out(sd.reshape(-1, 1)), out(np.column_stack([mean - z * sd, mean + z * sd])))
        return res[:nargout] if nargout > 1 else res[0]
    res = m.predict(X, nargout)
    if m.info.get('treebagger') and not m.regression:
        labs = res[0]
        names = [m.y.text(i) for i in np.argmax(np.asarray(darr(res[1])), 1)] if not isinstance(labs, Cell) else None
        if names is not None:
            res = (Cell.of_list([Char.of(s) for s in names], (len(names), 1)),) + res[1:]
    if m.regression and nargout > 1:
        return res + (EMPTY(),) * (nargout - 1)
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


@bi('loss')
def loss(nargout, *args):
    """L = loss(Mdl, X, Y), loss(Mdl, Tbl, ResponseVarName), loss(..., 'LossFun', f, 'Weights', w): the loss of a model on data (the classification error, or the mean squared error, unless given)."""
    nargchk(args, 2, 7, 'loss')
    m = _model(args[0], 'loss')
    from .tables import Table
    a = list(args[1:])
    if isinstance(a[0], Table):
        T = a.pop(0)
        X = _table_cols(T, m.preds, 'loss')
        Y = T.vars[T.names.index(py_str(a.pop(0)))] if a and is_str(a[0]) and py_str(a[0]) in T.names else (a.pop(0) if a and not is_str(a[0]) else T.vars[T.names.index(m.resp)])
    else:
        X = np.asarray(darr(a.pop(0)), float)
        Y = a.pop(0)
    o = {py_str(a[i]).lower(): a[i + 1] for i in range(0, len(a) - 1, 2)}
    lf = py_str(o.get('lossfun', Char.of('default'))).lower()
    w = np.asarray(darr(o['weights']), float).reshape(-1) if 'weights' in o else None
    return m.loss(X, Y, lf, w)


@bi('resubLoss')
def resubLoss(nargout, *args):
    """L = resubLoss(Mdl), resubLoss(Mdl, 'LossFun', f): the loss on the data the model was fitted to."""
    nargchk(args, 1, 3, 'resubLoss')
    m = _model(args[0], 'resubLoss')
    lf = py_str(args[2]).lower() if len(args) > 2 else 'default'
    Y = out(m.y.reshape(-1, 1)) if m.regression else m.y.value(m.y.idx)
    return m.loss(m.X, Y, lf, m.w)


@bi('resubPredict', nout=3)
def resubPredict(nargout, *args):
    """[label, score] = resubPredict(Mdl): the model's predictions for the data it was fitted to."""
    nargchk(args, 1, 1, 'resubPredict')
    m = _model(args[0], 'resubPredict')
    return _predict(nargout, m, out(m.X))


def _crossval_model(nargout, m, *rest):
    o = {py_str(rest[i]).lower(): rest[i + 1] for i in range(0, len(rest) - 1, 2)}
    if not o:
        o = {'kfold': 10.0}
    c = _make_partition(o, m.X.shape[0], None if m.regression else m.y, m.regression)
    return _crossvalidate(m, c)


def _part(v, fn):
    if not isinstance(v, Partitioned):
        raise err(f'stats:{fn}:model', f'{fn} takes a cross-validated model (crossval, or a fit with \'CrossVal\', \'on\').', fn)
    return v


@bi('kfoldLoss')
def kfoldLoss(nargout, *args):
    """L = kfoldLoss(CVMdl), kfoldLoss(..., 'Mode', 'average'|'individual', 'LossFun', f): the loss of each fold's model on the observations it was not fitted to."""
    nargchk(args, 1, 5, 'kfoldLoss')
    cv = _part(args[0], 'kfoldLoss')
    o = {py_str(args[i]).lower(): args[i + 1] for i in range(1, len(args) - 1, 2)}
    mode = py_str(o.get('mode', Char.of('average'))).lower()
    lf = py_str(o.get('lossfun', Char.of('default'))).lower()
    base = cv.base
    losses, sizes = [], []
    for i, m in enumerate(cv.models):
        te = cv.cvp.test_idx(i)
        if te.size == 0:
            continue
        Yte = out(base.y[te].reshape(-1, 1)) if base.regression else base.y.value(base.y.idx[te])
        losses.append(m.loss(base.X[te], Yte, lf))
        sizes.append(te.size)
    losses = np.array(losses)
    if mode == 'individual':
        return out(losses.reshape(-1, 1))
    return float(np.sum(losses * np.array(sizes)) / np.sum(sizes))


@bi('kfoldPredict', nout=2)
def kfoldPredict(nargout, *args):
    """[label, score] = kfoldPredict(CVMdl): for each observation, the prediction of the model not fitted to it."""
    nargchk(args, 1, 1, 'kfoldPredict')
    cv = _part(args[0], 'kfoldPredict')
    S = cv.fold_predictions()
    if cv.regression:
        return out(S.reshape(-1, 1))
    lab = np.argmax(np.nan_to_num(S, nan=-np.inf), axis=1)
    res = (cv.base.y.value(lab), out(S))
    return res if nargout > 1 else res[0]


@bi('oobLoss')
def oobLoss(nargout, *args):
    """L = oobLoss(Mdl): the loss of a bagged ensemble on each observation, by the trees whose bootstrap sample left it out."""
    nargchk(args, 1, 3, 'oobLoss')
    m = _model(args[0], 'oobLoss')
    if 'oob' not in m.info:
        raise err('stats:oobLoss:NotBagged', 'oobLoss takes a bagged ensemble (Method Bag, or TreeBagger).', 'oobLoss')
    S = _oob_scores(m)
    ok = ~np.any(np.isnan(np.atleast_2d(S.T).T), axis=1) if S.ndim > 1 else ~np.isnan(S)
    if m.regression:
        return float(np.mean((S[ok] - m.y[ok]) ** 2))
    return float(np.mean(np.argmax(S[ok], 1) != m.y.idx[ok]))


def _oob_scores(m):
    trees, oob = m.info['trees'], m.info['oob']
    n = m.X.shape[0]
    acc = None
    cnt = np.zeros(n)
    for t, o_ in zip(trees, oob):
        idx = np.flatnonzero(o_)
        if not idx.size:
            continue
        v = t.predict(m.X[idx])
        if acc is None:
            acc = np.zeros((n,) + v.shape[1:])
        acc[idx] += v
        cnt[idx] += 1
    if acc is None:
        return np.full(n, np.nan)
    with np.errstate(invalid='ignore', divide='ignore'):
        return acc / (cnt.reshape((n,) + (1,) * (acc.ndim - 1)))


@bi('oobPredict', nout=2)
def oobPredict(nargout, *args):
    """[label, score] = oobPredict(Mdl): each observation predicted by the trees of a bagged ensemble that did not see it."""
    nargchk(args, 1, 1, 'oobPredict')
    m = _model(args[0], 'oobPredict')
    if 'oob' not in m.info:
        raise err('stats:oobPredict:NotBagged', 'oobPredict takes a bagged ensemble.', 'oobPredict')
    S = _oob_scores(m)
    if m.regression:
        return out(S.reshape(-1, 1))
    lab = np.argmax(np.nan_to_num(S, nan=-np.inf), 1)
    res = (m.y.value(lab), out(S))
    return res if nargout > 1 else res[0]


@bi('compact')
def compact(nargout, *args):
    """CMdl = compact(Mdl): the model for predicting (here the model itself: it keeps its data)."""
    nargchk(args, 1, 1, 'compact')
    return _model(args[0], 'compact')


def _view_tree(nargout, m, *rest):
    t = m.info.get('tree')
    if t is None:
        raise err('stats:view:NotTree', 'view takes a classification or regression tree.', 'view')
    lines = [f"Decision tree for {'regression' if m.regression else 'classification'}"]
    for i in range(t.cut_var.size):
        if t.cut_var[i] >= 0:
            nm = m.preds[t.cut_var[i]]
            l_, r_ = t.children[i] + 1
            lines.append(f'{i + 1:>3}  if {nm}<{t.cut_pt[i]:g} then node {l_} elseif {nm}>={t.cut_pt[i]:g} then node {r_} else '
                         + (f'{t.value[i]:g}' if m.regression else m.y.text(int(np.argmax(t.value[i])))))
        else:
            lines.append(f'{i + 1:>3}  ' + (f'fit = {t.value[i]:g}' if m.regression else f'class = {m.y.text(int(np.argmax(t.value[i])))}'))
    R.write('\n' + '\n'.join(lines) + '\n\n')
    return None


# ---- crossval of a function ------------------------------------------------------------------------------------------------------------

@bi('crossval', aw=True, nout=2)
async def crossval(nargout, *args):
    """vals = crossval(fun, X, Y, 'KFold', k, 'Partition', c, 'Holdout', p, 'Leaveout', 1, 'Stratify', g, 'MCReps', r): fun(XTRAIN, YTRAIN, XTEST, YTEST) for each fold; mse = crossval('mse', X, y, 'Predfun', f), mcr = crossval('mcr', ...): the estimate; CVMdl = crossval(Mdl, ...)."""
    nargchk(args, 1, 30, 'crossval')
    if isinstance(args[0], Model):
        return _crossval_model(nargout, *args)
    fun = args[0]
    if not isinstance(fun, FH) and not (is_str(fun) and py_str(fun).lower() in ('mse', 'mcr')):
        raise err('stats:crossval:fun', "crossval takes a model, a function handle, or 'mse' or 'mcr'.", 'crossval')
    datas = []
    a = list(args[1:])
    while a and not is_str(a[0]):
        datas.append(a.pop(0))
    if not datas:
        raise err('stats:crossval:data', 'crossval takes the data after the function.', 'crossval')
    if is_str(fun) and len(datas) != 2:
        raise err('stats:crossval:data', f"crossval('{py_str(fun)}', X, y, ...) takes X and y.", 'crossval')
    o = {py_str(a[i]).lower(): a[i + 1] for i in range(0, len(a) - 1, 2)}
    n = np.asarray(darr(datas[0])).shape[0] if not isinstance(datas[0], (Cell, Str)) else numel(datas[0])
    group = None
    if 'stratify' in o:
        group = Labels(o['stratify'], 'crossval').idx
    if 'partition' in o:
        c = _cvp(o['partition'], 'crossval')
    elif 'holdout' in o:
        c = CVPartition(n, 'holdout', p=float(num(o['holdout'])), group=group)
    elif 'leaveout' in o:
        c = CVPartition(n, 'leaveout')
    else:
        c = CVPartition(n, 'kfold', k=_int(o.get('kfold', 10.0)), group=group)
    reps = _int(o.get('mcreps', 1.0))
    from ..index import idx as take
    vals = []
    for r in range(reps):
        cc = c if r == 0 else CVPartition(c.n, c.kind, c.k, c.p, c.group, c.stratify)
        for i in range(cc.nsets):
            tr = out(cc.train_mask(i).reshape(-1, 1))
            te = out(cc.test_mask(i).reshape(-1, 1))
            parts = []
            for d in datas:
                parts.append((take(d, (tr, Char.of(':'))) if np.ndim(darr(d)) == 2 and not isinstance(d, (Cell, Str)) else take(d, (tr,)),
                              take(d, (te, Char.of(':'))) if np.ndim(darr(d)) == 2 and not isinstance(d, (Cell, Str)) else take(d, (te,))))
            if is_str(fun):
                which = py_str(fun).lower()
                pf = o.get('predfun')
                if pf is None:
                    raise err('stats:crossval:Predfun', f"crossval('{which}', ...) takes 'Predfun', @(XTRAIN, YTRAIN, XTEST) ...", 'crossval')
                (Xtr, Xte), (ytr, yte) = parts[0], parts[1]
                yhat = await pf.acall(1, Xtr, ytr, Xte)
                if which == 'mse':
                    vals.append(np.array([np.sum((np.asarray(darr(yhat), float).reshape(-1) - np.asarray(darr(yte), float).reshape(-1)) ** 2)]))
                else:
                    a1, a2 = Labels(yte, 'crossval'), Labels(yhat, 'crossval')
                    t1 = [a1.text(i) for i in a1.idx]
                    t2 = [a2.text(i) for i in a2.idx]
                    vals.append(np.array([float(sum(x != y for x, y in zip(t1, t2)))]))
            else:
                args_ = [p[0] for p in parts] + [p[1] for p in parts] if len(parts) != 2 else [parts[0][0], parts[1][0], parts[0][1], parts[1][1]]
                v = await fun.acall(1, *args_)
                vals.append(np.asarray(darr(v), float).reshape(-1))
    V = np.array(vals)
    if is_str(fun):
        tot = float(V.sum() / (reps * n))
        return tot
    return out(V)


# ---- evaluating classifiers ---------------------------------------------------------------------------------------------------------------

def _label_texts(v):
    L = Labels(v, 'confusionmat')
    return L, [L.classes[i] if i >= 0 else None for i in L.idx]


@bi('confusionmat', nout=2)
def confusionmat(nargout, *args):
    """[C, order] = confusionmat(group, grouphat), confusionmat(..., 'Order', order): counts of each known class (row) predicted as each class (column)."""
    nargchk(args, 2, 4, 'confusionmat')
    L1, a = _label_texts(args[0])
    L2, b = _label_texts(args[1])
    if len(a) != len(b):
        raise err('stats:confusionmat:size', 'group and grouphat have as many elements.', 'confusionmat')
    if len(args) > 3:
        ordL = Labels(args[3], 'confusionmat')
        order = ordL._ordered(args[3], ordL)
        ref = L1
        ref.classes = order
    else:
        order = sorted(set(x for x in a + b if x is not None), key=lambda v: (isinstance(v, str), v))
        ref = L1
        ref.classes = order
    pos = {c: i for i, c in enumerate(order)}
    C = np.zeros((len(order), len(order)))
    for x, y in zip(a, b):
        if x is not None and y is not None and x in pos and y in pos:
            C[pos[x], pos[y]] += 1
    return (out(C), ref.names_value()) if nargout > 1 else out(C)


class ConfusionChart(Obj):
    """confusionchart: the counts drawn as a grid, the diagonal blue, the rest red, shaded by their share."""
    cls = 'mlearnlib.graphics.chart.ConfusionMatrixChart'
    is_handle = True

    def __init__(self, ax, C, labels):
        self.ax, self.C, self.labels = ax, C, labels
        self.p = {'Title': '', 'XLabel': 'Predicted Class', 'YLabel': 'True Class', 'Normalization': 'absolute', 'RowSummary': 'off',
                  'ColumnSummary': 'off'}
        self.parts = []

    def getprop(self, name):
        k = name.lower()
        if k == 'normalizedvalues':
            return out(self._values())
        if k == 'classlabels':
            return Cell.of_list([Char.of(s) for s in self.labels], (len(self.labels), 1))
        for kk, v in self.p.items():
            if kk.lower() == k:
                return Char.of(v)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'ConfusionMatrixChart'.")

    def setprop(self, name, value):
        for kk in self.p:
            if kk.lower() == name.lower():
                self.p[kk] = py_str(value)
                self.draw()
                return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class 'ConfusionMatrixChart'.")

    def propnames(self):
        return ['NormalizedValues', 'ClassLabels'] + list(self.p)

    def _values(self):
        C = self.C
        nz = self.p['Normalization'].lower()
        with np.errstate(invalid='ignore', divide='ignore'):
            if nz == 'row-normalized':
                return C / C.sum(1, keepdims=True)
            if nz == 'column-normalized':
                return C / C.sum(0, keepdims=True)
            if nz == 'total-normalized':
                return C / C.sum()
        return C

    def draw(self):
        from ..graphics_base import Patch, Text
        ax = self.ax
        for h in self.parts:
            if h.valid:
                h.delete_handle()
        self.parts = []
        V = self._values()
        k = V.shape[0]
        rowsum = self.p['RowSummary'].lower() != 'off'
        colsum = self.p['ColumnSummary'].lower() != 'off'
        verts, faces, cols = [], [], []
        texts = []

        def cell(r, c, color, txt, light):
            n0 = len(verts)
            verts.extend([[c + 0.5, r + 0.5], [c + 1.5, r + 0.5], [c + 1.5, r + 1.5], [c + 0.5, r + 1.5]])
            faces.append([n0 + 1, n0 + 2, n0 + 3, n0 + 4])
            cols.append(color)
            texts.append((c + 1, r + 1, txt, light))
        mx = max(self.C.max(), 1)
        for r in range(k):
            for c in range(k):
                share = self.C[r, c] / mx
                base = np.array([0.0, 0.447, 0.741]) if r == c else np.array([0.85, 0.325, 0.098])
                color = 1 - share * (1 - base) if self.C[r, c] else np.array([1.0, 1.0, 1.0])
                v = V[r, c]
                txt = (f'{v:g}' if self.p['Normalization'] == 'absolute' else f'{v:.3g}') if self.C[r, c] else ''
                cell(r, c, color, txt, share > 0.55)
        if rowsum:
            for r in range(k):
                n_r = self.C[r].sum()
                good = self.C[r, r] / n_r if n_r else 0
                cell(r, k + 0.2, np.array([0.0, 0.447, 0.741]) * good + (1 - good), f'{100 * good:.1f}%', good > 0.55)
        if colsum:
            for c in range(k):
                n_c = self.C[:, c].sum()
                good = self.C[c, c] / n_c if n_c else 0
                cell(k + 0.2, c, np.array([0.0, 0.447, 0.741]) * good + (1 - good), f'{100 * good:.1f}%', good > 0.55)
        P = Patch(ax)
        P.props['Vertices'] = np.array(verts, float)
        P.props['Faces'] = np.array(faces, float)
        P.props['FaceVertexCData'] = np.array(cols, float)
        P.props['FaceColor'] = 'flat'
        P.props['EdgeColor'] = (0.85, 0.85, 0.85)
        self.parts.append(P)
        for x, y, s, light in texts:
            if s:
                T = Text(ax)
                T.props['String'] = s
                T.props['Position'] = np.array([[x, y, 0.0]])
                T.props['HorizontalAlignment'] = 'center'
                T.props['Color'] = (1.0, 1.0, 1.0) if light else (0.1, 0.1, 0.1)
                self.parts.append(T)
        ax.set_value('XLim', np.array([[0.5, k + 0.5 + (1.2 if rowsum else 0)]]))
        ax.set_value('YLim', np.array([[0.5, k + 0.5 + (1.2 if colsum else 0)]]))
        ax.set_value('YDir', Char.of('reverse'))
        ax.set_value('XTick', np.arange(1, k + 1, dtype=float).reshape(1, -1))
        ax.set_value('YTick', np.arange(1, k + 1, dtype=float).reshape(1, -1))
        ax.set_value('XTickLabel', Cell.of_list([Char.of(s) for s in self.labels]))
        ax.set_value('YTickLabel', Cell.of_list([Char.of(s) for s in self.labels]))
        ax.set_value('DataAspectRatio', np.array([[1.0, 1.0, 1.0]]))
        R._builtin('xlabel', ax, Char.of(self.p['XLabel']))
        R._builtin('ylabel', ax, Char.of(self.p['YLabel']))
        R._builtin('title', ax, Char.of(self.p['Title']))
        ax.touch()


@bi('confusionchart')
def confusionchart(nargout, *args):
    """cm = confusionchart(trueLabels, predictedLabels), confusionchart(C), confusionchart(C, classLabels), confusionchart(..., 'Normalization', n, 'RowSummary', r, 'ColumnSummary', c, 'Title', t): a confusion matrix drawn."""
    nargchk(args, 1, 14, 'confusionchart')
    from .graphics import newplot
    a = list(args)
    opt_names = ('normalization', 'rowsummary', 'columnsummary', 'title', 'xlabel', 'ylabel')
    second = a[1] if len(a) > 1 and not (is_str(a[1]) and py_str(a[1]).lower() in opt_names) else None
    if second is not None and numel(second) == numel(a[0]):
        Cv, order = confusionmat(2, a.pop(0), a.pop(0))
        C = np.asarray(darr(Cv), float)
        L = Labels(order, 'confusionchart')
        labels = [L.text(i) for i in L.idx]
    else:
        C = np.asarray(darr(a.pop(0)), float)
        if second is not None:
            L = Labels(a.pop(0), 'confusionchart')
            labels = [L.text(i) for i in L.idx]
        else:
            labels = [str(i + 1) for i in range(C.shape[0])]
    ax = newplot(None)
    cm = ConfusionChart(ax, C, labels)
    for i in range(0, len(a) - 1, 2):
        k = py_str(a[i])
        for kk in cm.p:
            if kk.lower() == k.lower():
                cm.p[kk] = py_str(a[i + 1])
    cm.draw()
    return cm


@bi('perfcurve', nout=6)
def perfcurve(nargout, *args):
    """[X, Y, T, AUC, OPTROCPT] = perfcurve(labels, scores, posclass), perfcurve(..., 'XCrit', c, 'YCrit', c): a classifier's performance as its threshold moves (the ROC curve unless other criteria are named) and the area under it."""
    nargchk(args, 3, 13, 'perfcurve')
    L = Labels(args[0], 'perfcurve')
    s = np.asarray(darr(args[1]), float).reshape(-1)
    pc = args[2]
    pos_text = Labels(pc, 'perfcurve').classes[0] if not isinstance(pc, (Cell,)) or numel(pc) == 1 else None
    if pos_text not in L.classes:
        raise err('stats:perfcurve:posclass', 'posclass is one of the classes of labels.', 'perfcurve')
    pos = np.array([L.classes[i] == pos_text if i >= 0 else False for i in L.idx])
    keep = (L.idx >= 0) & np.isfinite(s)
    pos, s = pos[keep], s[keep]
    o = {py_str(args[i]).lower(): args[i + 1] for i in range(3, len(args) - 1, 2)}
    xc = py_str(o.get('xcrit', Char.of('fpr'))).lower()
    yc = py_str(o.get('ycrit', Char.of('tpr'))).lower()
    P, N = pos.sum(), (~pos).sum()
    thr = np.unique(s)[::-1]
    tp = np.array([np.sum(pos & (s >= t)) for t in thr], float)
    fp = np.array([np.sum(~pos & (s >= t)) for t in thr], float)
    tp = np.concatenate([[0], tp])
    fp = np.concatenate([[0], fp])
    T = np.concatenate([[thr[0]], thr]) if thr.size else np.zeros(1)
    fn_ = P - tp
    tn = N - fp

    def crit(c):
        with np.errstate(invalid='ignore', divide='ignore'):
            table = {'tp': tp, 'fn': fn_, 'fp': fp, 'tn': tn, 'tpr': tp / P, 'sens': tp / P, 'reca': tp / P, 'fnr': fn_ / P, 'miss': fn_ / P,
                     'fpr': fp / N, 'fall': fp / N, 'tnr': tn / N, 'spec': tn / N, 'ppv': np.where(tp + fp > 0, tp / (tp + fp), np.nan),
                     'prec': np.where(tp + fp > 0, tp / (tp + fp), np.nan), 'npv': np.where(tn + fn_ > 0, tn / (tn + fn_), np.nan),
                     'accu': (tp + tn) / (P + N), 'rpp': (tp + fp) / (P + N), 'rnp': (tn + fn_) / (P + N)}
        if c not in table:
            raise err('stats:perfcurve:crit', f"'{c}' is not a criterion of perfcurve.", 'perfcurve')
        return table[c]
    Xv, Yv = crit(xc), crit(yc)
    if xc in ('prec', 'ppv') or yc in ('prec', 'ppv'):
        Xv = np.where(np.isnan(Xv), 1.0, Xv) if xc in ('prec', 'ppv') else Xv
        Yv = np.where(np.isnan(Yv), 1.0, Yv) if yc in ('prec', 'ppv') else Yv
    ok = np.isfinite(Xv) & np.isfinite(Yv)
    order = np.argsort(Xv[ok], kind='stable')
    xs_, ys_ = Xv[ok][order], Yv[ok][order]
    auc = float(np.sum(np.diff(xs_) * (ys_[1:] + ys_[:-1]) / 2)) if ok.sum() > 1 else 0.0
    fpr, tpr = fp / max(N, 1), tp / max(P, 1)
    m = N / max(P, 1)
    k = int(np.argmax(tpr - m * fpr))
    opt = out(np.array([[fpr[k], tpr[k]]]))
    res = (out(Xv.reshape(-1, 1)), out(Yv.reshape(-1, 1)), out(T.reshape(-1, 1)), auc, opt, EMPTY())
    return res[:nargout] if nargout > 1 else res[0]


# ---- the builtins that take models too ---------------------------------------------------------------------------------------------------

def _wrap(name, handler, test, nout=None):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f
    if nout is not None:
        info.nout = max(info.nout, nout)


_wrap('predict', _predict, lambda v: isinstance(v, Model), 3)
_wrap('view', _view_tree, lambda v: isinstance(v, Model))
