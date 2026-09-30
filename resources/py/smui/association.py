"""Analyze > Screening > Association Analysis: the backend.

JMP Pro's Association Analysis (market basket analysis): which items go
together in transactions. The data come in one of JMP's three formats:

  stacked         one Item column and an ID: each row one item, the rows
                  with the same ID one transaction (Freq is not used)
  several columns two or more Item columns: each row a transaction, its
                  items the values in those columns
  delimited       an Item column whose cells hold several items between a
                  delimiter (JMP's Multiple Response): each row a transaction

With an ID in the last two, the rows that share it make one transaction;
Freq counts a transaction that many times. The transactions become a
boolean matrix (transactions by items); the frequent item sets are found
by Agrawal and Srikant's (1994) Apriori or by Han, Pei and Yin's (2000)
FP-growth, both written here in numpy and plain Python, and every rule
X => Y of a frequent item set is measured:

  support     P(X and Y)               confidence  P(Y | X)
  lift        P(X and Y) / (P(X) P(Y))
  coverage    P(X)                     leverage    P(X and Y) - P(X) P(Y)
  conviction  (1 - P(Y)) / (1 - confidence)
  Fisher p    the one-sided Fisher exact test of X and Y occurring together
              more often than by chance (the hypergeometric upper tail),
              with Benjamini and Hochberg's false discovery rate over every
              rule the frequent item sets make

JMP reports support, confidence and lift; the rest are beyond it.

The functions between the '>>>' and '<<<' markers need only the standard
library, numpy and scipy: the code under the report copies them from this
file, so that it computes the report's numbers exactly.
"""
import json
import math
import os
from itertools import combinations

import numpy as np

from . import data
from .registry import api

BASE = '#2f6690'   # the points' colour, light theme
ALGORITHMS = {'apriori': 'Apriori', 'fpgrowth': 'FP-growth'}
MAX_SETS = 200000   # frequent item sets at most: beyond that, a higher Minimum Support


# >>> the transactions
def label(v):
    """An item or an ID as the report shows it: 2.0 as 2, text as it is;
    None when it is missing (None, NaN or empty text)."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        f = float(v)
        if math.isnan(f):
            return None
        return str(int(f)) if f.is_integer() else f'{f:.6g}'
    s = str(v)
    return s if s != '' else None


def item_key(s):
    """The order of items in an item set: alphabetical, case aside."""
    return (s.casefold(), s)


def baskets(frame, items, id_col=None, freq=None, delimiter=None, labels=None):
    """The transactions of a table (a DataFrame whose index is the rows):
    lists of their keys, rows, item sets and counts, and notes.

    One Item column without a delimiter is stacked data: the rows with the
    same ID are one transaction, each row one item, and Freq is not used
    (as in JMP). Otherwise each row is a transaction, or the rows that
    share an ID one together; its items are the values of the Item columns,
    each cell cut at the delimiter when there is one, and shown by their
    Value Labels ({column: {value: label}}) when they have them. Its count
    is the Freq of its first row, truncated to a whole number as JMP's Freq
    is; a transaction with no count, or no items, is left out."""
    stacked = len(items) == 1 and not delimiter
    notes = []
    if stacked and not id_col:
        raise ValueError('one Item column is stacked data: give the ID of the transactions, or the delimiter of '
                         'its items (Multiple Response), or two or more Item columns')
    order, rows, sets, counts = [], {}, {}, {}
    no_id = no_count = 0
    ids = frame[id_col].tolist() if id_col else None
    fr = frame[freq].tolist() if freq and not stacked else None
    cells = [frame[c].tolist() for c in items]
    for k, r in enumerate(frame.index.tolist()):
        key = label(ids[k]) if id_col else r
        if key is None:
            no_id += 1
            continue
        if key not in sets:
            c = 1
            if fr is not None:
                f = fr[k]
                c = math.floor(float(f)) if f is not None and not (isinstance(f, float) and math.isnan(f)) else 0
            order.append(key)
            rows[key], sets[key], counts[key] = [], set(), c
        rows[key].append(int(r))
        for name, col in zip(items, cells):
            v = label(col[k])
            if v is None:
                continue
            shown = (labels or {}).get(name) or {}
            if delimiter:
                sets[key].update(shown.get(p.strip(), p.strip()) for p in v.split(delimiter) if p.strip())
            else:
                sets[key].add(shown.get(v, v))
    if no_id:
        notes.append(f'{no_id} row{"" if no_id == 1 else "s"} with no {id_col} left out.')
    if freq and stacked:
        notes.append(f'Freq ({freq}) is not used with stacked data (one Item column and an ID), as in JMP.')
    keep = []
    for key in order:
        if counts[key] < 1:
            no_count += 1
        elif sets[key]:
            keep.append(key)
    empty = len(order) - len(keep) - no_count
    if no_count:
        notes.append(f'{no_count} transaction{"" if no_count == 1 else "s"} with a Freq that is missing or below 1 left out.')
    if empty:
        notes.append(f'{empty} transaction{"" if empty == 1 else "s"} with no items left out.')
    return keep, [rows[k] for k in keep], [sets[k] for k in keep], [counts[k] for k in keep], notes


def incidence(sets):
    """The item names (in item order) and the boolean matrix of the
    transactions (rows) by the items (columns)."""
    names = sorted({i for s in sets for i in s}, key=item_key)
    index = {v: j for j, v in enumerate(names)}
    M = np.zeros((len(sets), len(names)), dtype=bool)
    for t, s in enumerate(sets):
        M[t, [index[i] for i in s]] = True
    return names, M
# <<< the transactions


# >>> Apriori
def apriori(M, w, min_count, max_size):
    """The frequent item sets of the transactions M (boolean, transactions
    by items), each transaction counted w times: {item indices (a tuple,
    ascending): weighted count} for the sets counted min_count times or
    more, of at most max_size items. Agrawal and Srikant's (1994) level-
    wise search: a set of k items is a candidate only when it joins two
    frequent sets of k - 1 items that share their first k - 2 and every
    other subset of k - 1 items is frequent too (no superset of a rare set
    can be frequent); each candidate is counted with the transactions of
    its first parent."""
    M = np.asarray(M, dtype=bool)
    w = np.asarray(w, dtype=float)
    single = w @ M
    level = {(j,): M[:, j] for j in range(M.shape[1]) if single[j] >= min_count}
    out = {k: float(single[k[0]]) for k in level}
    size = 1
    while level and size < max_size:
        keys = sorted(level)
        frequent = set(keys)
        nxt = {}
        for a, A in enumerate(keys):
            for B in keys[a + 1:]:
                if A[:-1] != B[:-1]:
                    break          # sorted: the sets that share A's first k - 2 items come together
                cand = A + (B[-1],)
                if any(cand[:i] + cand[i + 1:] not in frequent for i in range(len(cand) - 2)):
                    continue
                mask = level[A] & M[:, B[-1]]
                c = float(w @ mask)
                if c >= min_count:
                    nxt[cand] = mask
                    out[cand] = c
        level = nxt
        size += 1
    return out
# <<< Apriori


# >>> FP-growth
class FPNode:
    """A node of an FP-tree: an item, the weighted count of the
    transactions whose frequent items run through it, its parent and
    children."""
    __slots__ = ('item', 'count', 'parent', 'children')

    def __init__(self, item, parent):
        self.item, self.count, self.parent, self.children = item, 0.0, parent, {}


def fp_tree(transactions, min_count):
    """The FP-tree of weighted transactions [(items, count)]: each
    transaction's frequent items, the most frequent first, as a path from
    the root; the frequent items (most frequent first), their counts, and
    for each the list of its nodes (the header table)."""
    counts = {}
    for items, c in transactions:
        for j in items:
            counts[j] = counts.get(j, 0.0) + c
    freq = {j: c for j, c in counts.items() if c >= min_count}
    order = sorted(freq, key=lambda j: (-freq[j], j))
    rank = {j: r for r, j in enumerate(order)}
    root, header = FPNode(None, None), {j: [] for j in order}
    for items, c in transactions:
        node = root
        for j in sorted((j for j in items if j in rank), key=rank.get):
            child = node.children.get(j)
            if child is None:
                child = node.children[j] = FPNode(j, node)
                header[j].append(child)
            child.count += c
            node = child
    return order, freq, header


def fpgrowth(M, w, min_count, max_size):
    """The same frequent item sets as apriori() by Han, Pei and Yin's
    (2000) FP-growth: the transactions in an FP-tree; for each frequent
    item, least frequent first, the prefix paths that lead to its nodes
    (its conditional pattern base, each path counted as its node) make a
    tree of their own, mined the same way for the sets that end with it.
    No candidate sets are made."""
    M = np.asarray(M, dtype=bool)
    out = {}

    def grow(transactions, suffix):
        order, freq, header = fp_tree(transactions, min_count)
        for j in reversed(order):
            s = tuple(sorted(suffix + (j,)))
            out[s] = freq[j]
            if len(s) < max_size:
                base = []
                for node in header[j]:
                    path, p = [], node.parent
                    while p.item is not None:
                        path.append(p.item)
                        p = p.parent
                    if path:
                        base.append((path, node.count))
                if base:
                    grow(base, s)
    grow([(np.flatnonzero(M[t]).tolist(), float(w[t])) for t in range(M.shape[0])], ())
    return out
# <<< FP-growth


# >>> the rules
def bh(p):
    """Benjamini and Hochberg's false discovery rate p-values (q-values)."""
    p = np.asarray(p, dtype=float)
    n = len(p)
    if not n:
        return p
    o = np.argsort(p, kind='stable')
    q = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1.0)
    return out


def rules(freq, total, max_antecedents, min_confidence, min_lift):
    """Every rule X => Y of the frequent item sets freq ({items: weighted
    count}; X and Y not empty, together a frequent set, X of at most
    max_antecedents items), measured: support P(X and Y), confidence
    P(Y | X), lift P(X and Y) / (P(X) P(Y)), coverage P(X), leverage
    P(X and Y) - P(X) P(Y), conviction (1 - P(Y)) / (1 - confidence),
    and the one-sided Fisher exact p-value of X and Y together more often
    than by chance: P(A >= count of X and Y) for A hypergeometric (total
    transactions, those with Y, drawn: those with X). The false discovery
    rate (Benjamini and Hochberg) is over every rule made; those with
    confidence and lift at least the minimums are returned, highest
    confidence first (then lift, then support)."""
    from scipy.stats import hypergeom
    made = []
    for Z, cz in freq.items():
        for r in range(1, min(len(Z) - 1, max_antecedents) + 1):
            for X in combinations(Z, r):
                Y = tuple(j for j in Z if j not in X)
                made.append((X, Y, cz, freq[X], freq[Y]))
    if not made:
        return []
    cz, cx, cy = (np.array([m[k] for m in made], dtype=float) for k in (2, 3, 4))
    N = int(round(total))
    p = hypergeom.sf(np.rint(cz) - 1, N, np.rint(cy), np.rint(cx))
    q = bh(p)
    conf = cz / cx
    lift = cz * total / (cx * cy)
    out = []
    for k, (X, Y, *_) in enumerate(made):
        if conf[k] >= min_confidence - 1e-12 and lift[k] >= min_lift - 1e-12:
            sy = cy[k] / total
            out.append({'x': X, 'y': Y, 'support': cz[k] / total, 'confidence': conf[k], 'lift': lift[k], 'coverage': cx[k] / total,
                        'leverage': cz[k] / total - (cx[k] / total) * sy,
                        'conviction': (1 - sy) / (1 - conf[k]) if conf[k] < 1 - 1e-12 else math.inf,
                        'p': float(p[k]), 'fdr': float(q[k]), 'count': cz[k]})
    out.sort(key=lambda d: (-d['confidence'], -d['lift'], -d['support'], len(d['x']), d['x'], d['y']))
    return out
# <<< the rules


# ---------------------------------------------------------------------------
# the report's settings
# ---------------------------------------------------------------------------

def _num(v, name, lo, hi, whole=False, lo_open=False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{name} is a number, not {v!r}')
    if not math.isfinite(x) or (whole and x != int(x)) or x > hi or x < lo or (lo_open and x <= lo):
        what = 'a whole number' if whole else 'a number'
        raise ValueError(f'{name} is {what} {"above" if lo_open else "from"} {lo:g}{" and at most" if lo_open else " to"} {hi:g}')
    return int(x) if whole else x


def _settings(min_support, min_confidence, min_lift, max_antecedents, max_rule_size, algorithm):
    s = {'min_support': _num(min_support, 'Minimum Support', 0, 1, lo_open=True),
         'min_confidence': _num(min_confidence, 'Minimum Confidence', 0, 1),
         'min_lift': _num(min_lift, 'Minimum Lift', 0, 1e12),
         'max_antecedents': _num(max_antecedents, 'Maximum Antecedents', 1, 100, whole=True),
         'max_rule_size': _num(max_rule_size, 'Maximum Rule Size', 2, 100, whole=True),
         'algorithm': algorithm if algorithm in ALGORITHMS else None}
    if s['algorithm'] is None:
        raise ValueError(f'the algorithm is apriori or fpgrowth, not {algorithm!r}')
    return s


def _frame(table, items, id_col, freq, rows):
    """The columns the transactions need, as the CSV code reads them: text
    as text (None missing), numbers as floats (NaN missing); the index is
    the page's rows."""
    import pandas as pd
    idx = np.arange(data.TABLES[table]['n']) if rows is None else np.asarray(rows, dtype=int)
    cols = list(dict.fromkeys([*items, *([id_col] if id_col else []), *([freq] if freq else [])]))
    return pd.DataFrame({c: list(data.raw(table, c, idx)) for c in cols}, index=idx)


def _labels(table, items):
    """The Value Labels of the Item columns, keyed by the value as label()
    writes it: {column: {value: label}}, only the columns that have some."""
    out = {}
    for c in items:
        vl = data.value_labels(table, c) if hasattr(data, 'value_labels') else {}
        if vl:
            out[c] = {label(v): lab for v, lab in vl.items() if label(v) is not None}
    return out


def _mined(table, rows, items, id_col, freq, delimiter, S):
    """The transactions, the matrix and the frequent item sets, remembered
    for the table's version, the rows and the settings (a redraw, a By
    group seen again and the linked selections reuse them)."""
    from . import predictive

    def build():
        keys, trows, sets, counts, notes = baskets(_frame(table, items, id_col, freq, rows), items, id_col, freq, delimiter, _labels(table, items))
        if not keys:
            raise ValueError('no transactions with items in these rows')
        names, M = incidence(sets)
        w = np.asarray(counts, dtype=float)
        W = float(w.sum())
        min_count = S['min_support'] * W - 1e-9 * max(1.0, W)
        # a quick bound before the search: the sets of two frequent items at most
        f1 = int(np.sum(w @ M >= min_count))
        if f1 * (f1 - 1) / 2 > 50 * MAX_SETS and S['max_rule_size'] > 2:
            raise ValueError(f'{f1} items have the Minimum Support: too many sets to search; raise the Minimum Support or lower the Maximum Rule Size')
        found = (apriori if S['algorithm'] == 'apriori' else fpgrowth)(M, w, min_count, S['max_rule_size'])
        if len(found) > MAX_SETS:
            raise ValueError(f'{len(found)} frequent item sets: raise the Minimum Support')
        return {'keys': keys, 'rows': trows, 'sets': sets, 'counts': counts, 'notes': notes, 'names': names, 'M': M, 'w': w, 'W': W, 'freq': found}
    spec = {'items': list(items), 'id': id_col, 'freq': freq, 'delimiter': delimiter, 'min_support': S['min_support'],
            'max_rule_size': S['max_rule_size'], 'algorithm': S['algorithm'], 'labels': _labels(table, items)}
    return predictive.cached('association.mined', table, rows, spec, build)


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

_SOURCE = None


def _block(name):
    """The lines between '# >>> name' and '# <<< name' in this file."""
    global _SOURCE
    if _SOURCE is None:
        with open(os.path.abspath(__file__), encoding='utf-8') as f:
            _SOURCE = f.read()
    a = _SOURCE.index(f'# >>> {name}\n') + len(f'# >>> {name}\n')
    return _SOURCE[a:_SOURCE.index(f'# <<< {name}\n')].rstrip()


def _py(v):
    return json.dumps(v, ensure_ascii=False)


def _code_head(table, table_name, items, id_col, freq, rows, where, extra_imports=()):
    """Read the exported table (the text columns as text), keep the
    report's rows, and make the transactions as the report does."""
    from .text import _keep_lines
    dtypes = {c: 'str' for c in dict.fromkeys([*items, *([id_col] if id_col else [])]) if data.meta(table, c).get('dataType') != 'numeric'}
    for w in where or []:
        if data.meta(table, w['column']).get('dataType') != 'numeric':
            dtypes[w['column']] = 'str'
    L = ['import math', 'from itertools import combinations', '', 'import numpy as np', 'import pandas as pd', *extra_imports, '',
         '# the table, as File > Export CSV writes it (an empty field is missing); the item and ID columns as text',
         f'df = pd.read_csv({_py(table_name + ".csv")}, dtype={_py(dtypes)}, keep_default_na=False, na_values=[""])']
    L += _keep_lines(table, rows, where)
    return L


def _code_mine(items, id_col, freq, delimiter, S, labels=None):
    """The lines from the transactions to the frequent item sets."""
    args = [_py(list(items))]
    if id_col:
        args.append(f'id_col={_py(id_col)}')
    if freq:
        args.append(f'freq={_py(freq)}')
    if delimiter:
        args.append(f'delimiter={_py(delimiter)}')
    if labels:
        args.append('labels=labels')
    algo = S['algorithm']
    return ['', _block('the transactions'), '', _block('Apriori' if algo == 'apriori' else 'FP-growth'), '', _block('the rules'), '',
            *([f'labels = {_py(labels)}   # the Value Labels of the Item columns: the items are shown by them'] if labels else []),
            f'keys, rows, sets, counts, notes = baskets(df, {", ".join(args)})',
            'names, M = incidence(sets)   # the items; transactions by items',
            'w = np.asarray(counts, dtype=float)   # each transaction\'s count (Freq)',
            'W = w.sum()',
            f'found = {"apriori" if algo == "apriori" else "fpgrowth"}(M, w, min_count={S["min_support"]!r} * W - 1e-9 * max(1.0, W), max_size={S["max_rule_size"]})   # Minimum Support, Maximum Rule Size',
            'shown = sorted(found, key=lambda s: (-found[s], len(s), [item_key(names[j]) for j in s]))   # the highest support first',
            'item_sets = pd.DataFrame({"Item Set": ["{" + ", ".join(names[j] for j in s) + "}" for s in shown],',
            '                          "Support": [found[s] / W for s in shown], "N Items": [len(s) for s in shown]})',
            f'rules_found = rules(found, W, max_antecedents={S["max_antecedents"]}, min_confidence={S["min_confidence"]!r}, min_lift={S["min_lift"]!r})',
            'rule_table = pd.DataFrame([{"Condition": ", ".join(names[j] for j in r["x"]), "Consequent": ", ".join(names[j] for j in r["y"]),',
            '                            "Confidence": r["confidence"], "Lift": r["lift"], "Support": r["support"], "Coverage": r["coverage"],',
            '                            "Conviction": r["conviction"], "Leverage": r["leverage"], "Fisher p": r["p"], "FDR p": r["fdr"]} for r in rules_found])']


# ---------------------------------------------------------------------------
# the entry point
# ---------------------------------------------------------------------------

@api('association.fit')
def fit(table, items, rows=None, id_col=None, freq=None, delimiter=None, min_support=0.1, min_confidence=0.4, min_lift=1.2,
        max_antecedents=3, max_rule_size=4, algorithm='apriori', where=None, table_name='data'):
    """Frequent Item Sets and Rules, with the transactions (their rows and
    items, for linking and the Transaction Listing); the code, and the
    bubble plot's code."""
    items = [c for c in (items or []) if c]
    delimiter = delimiter if isinstance(delimiter, str) and delimiter != '' else None
    try:
        if not items:
            raise ValueError('choose one or more Item columns')
        if id_col and id_col in items:
            raise ValueError('the ID column is an Item column too')
        S = _settings(min_support, min_confidence, min_lift, max_antecedents, max_rule_size, algorithm)
        if freq and data.meta(table, freq).get('dataType') != 'numeric':
            raise ValueError(f'Freq takes a numeric column; {freq} is character')
        D = _mined(table, rows, items, id_col, freq, delimiter, S)
    except ValueError as e:
        return {'error': str(e)}
    names, W, found = D['names'], D['W'], D['freq']
    key = {s: (-c, len(s), [item_key(names[j]) for j in s]) for s, c in found.items()}
    sets_out = [{'set': '{' + ', '.join(names[j] for j in s) + '}', 'items': list(s), 'support': found[s] / W, 'n': len(s), 'count': found[s]}
                for s in sorted(found, key=key.get)]
    R = rules(found, W, S['max_antecedents'], S['min_confidence'], S['min_lift'])
    made = sum(sum(math.comb(len(s), r) for r in range(1, min(len(s) - 1, S['max_antecedents']) + 1)) for s in found if len(s) > 1)
    rules_out = []
    for r in R:
        cond, cons = ', '.join(names[j] for j in r['x']), ', '.join(names[j] for j in r['y'])
        rules_out.append({'rule': f'{cond} ⇒ {cons}', 'condition': cond, 'consequent': cons, 'x': list(r['x']), 'y': list(r['y']),
                          'support': r['support'], 'confidence': r['confidence'], 'lift': r['lift'], 'coverage': r['coverage'],
                          'leverage': r['leverage'], 'conviction': r['conviction'], 'p': r['p'], 'fdr': r['fdr'], 'count': r['count']})
    head = _code_head(table, table_name, items, id_col, freq, rows, where)
    mine = _code_mine(items, id_col, freq, delimiter, S, _labels(table, items))
    code = head + mine + [
        'print(f"{len(keys)} transactions, {len(names)} items")',
        'print(item_sets.to_string())   # Frequent Item Sets, the highest support first',
        'print(rule_table.to_string())   # Rules, the highest confidence first']
    bubbles = None
    if rules_out:
        bubbles = '\n'.join(_code_head(table, table_name, items, id_col, freq, rows, where, ['import matplotlib.pyplot as plt']) + mine + [
            'smax = rule_table["Support"].max()',
            'd = np.maximum(5, 28 * np.sqrt(rule_table["Support"] / smax))   # each rule\'s bubble across, in pixels: its area follows the support',
            'fig, ax = plt.subplots(figsize=(5.2, 4), layout="constrained")',
            f'ax.scatter(rule_table["Confidence"], rule_table["Lift"], s=(0.72 * d) ** 2, color="{BASE}", alpha=0.55, edgecolors="{BASE}", linewidths=0.7)',
            'ax.axhline(1, color="#e0d7ce", linewidth=0.72, zorder=0)   # lift 1: no association',
            'ax.set_xlabel("Confidence")', 'ax.set_ylabel("Lift")', 'ax.set_title("Rules: confidence, lift and support")', 'plt.show()'])
    counts = np.asarray(D['counts'], dtype=float)
    return {'n_transactions': len(D['keys']), 'total': W, 'weighted': bool(np.any(counts != 1)), 'n_items': len(names), 'items': names,
            'item_support': (D['w'] @ D['M'] / W).tolist(),
            'transactions': {'keys': [str(k) if id_col else int(k) + 1 for k in D['keys']], 'rows': D['rows'],
                             'items': [np.flatnonzero(D['M'][t]).tolist() for t in range(D['M'].shape[0])], 'counts': D['counts']},
            'item_sets': sets_out, 'rules': rules_out, 'n_rules_made': made, 'settings': S, 'algorithm': ALGORITHMS[S['algorithm']],
            'format': 'stacked' if len(items) == 1 and not delimiter else ('delimited' if delimiter else 'columns'),
            'id': id_col, 'notes': D['notes'], 'code': '\n'.join(code), 'plot_code': {'bubbles': bubbles} if bubbles else {}}
