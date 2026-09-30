#!/usr/bin/env python3
"""Analyze > Screening > Association Analysis's backend
(resources/py/smui/association.py), checked on simulated baskets against
counts made here by brute force (every item set of up to four items, its
support counted row by row), the rules' measures by their definitions,
scipy's fisher_exact (one-sided) for each rule's p-value, statsmodels'
multipletests (Benjamini and Hochberg) for the false discovery rate,
Apriori against FP-growth, JMP's three data formats and Freq against the
same transactions written out, and the Python shown under the report run
on a CSV export of the table (the tables and the bubble plot).

    python3 resources/tests/smui/test_association.py
"""
import itertools
import json
import math
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

from backend import FAILED, Checks, call, table

check = Checks()
check('association.py imports', 'association' in FAILED, False)
from smui import association as AS  # noqa: E402


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float)))) if np.size(a) else 0.0


# ---- simulated baskets: planted associations -------------------------------------------------------------------------------------
# bread -> butter -> jam, pasta <-> sauce, tea with sugar, coffee without tea; the rest at random
ITEMS = ['apples', 'bread', 'butter', 'cheese', 'coffee', 'eggs', 'jam', 'milk', 'pasta', 'sauce', 'sugar', 'tea']
rng = np.random.default_rng(20260929)


def basket(r):
    b = set()
    if r.random() < 0.45:
        b.add('bread')
        if r.random() < 0.7:
            b.add('butter')
            if r.random() < 0.5:
                b.add('jam')
    elif r.random() < 0.15:
        b.add('butter')
    if r.random() < 0.3:
        b.add('pasta')
        if r.random() < 0.75:
            b.add('sauce')
    elif r.random() < 0.08:
        b.add('sauce')
    if r.random() < 0.3:
        b.add('tea')
        if r.random() < 0.6:
            b.add('sugar')
    elif r.random() < 0.4:
        b.add('coffee')
        if r.random() < 0.3:
            b.add('sugar')
    for it, p in (('apples', 0.25), ('cheese', 0.2), ('eggs', 0.3), ('milk', 0.35)):
        if r.random() < p:
            b.add(it)
    if not b:
        b.add('milk')
    return b


B = [basket(rng) for _ in range(500)]
NT = len(B)
# stacked: one row per item, the basket's number as the ID (the items of a basket in a shuffled order)
st_id, st_item = [], []
for t, b in enumerate(B):
    for it in rng.permutation(sorted(b)):
        st_id.append(t + 1)
        st_item.append(str(it))
t_st = table({'basket': st_id, 'item': st_item}, types={'basket': 'nominal'})
# several columns: Item 1 to Item 7, missing when the basket is smaller
width = max(len(b) for b in B)
cols = {f'Item {k + 1}': [sorted(b)[k] if k < len(b) else None for b in B] for k in range(width)}
t_cols = table(cols)
# delimited: one text per basket
t_del = table({'items': [';'.join(sorted(b)) for b in B]})


def brute(baskets, weights, max_size):
    """Every item set of up to max_size items, and its weighted count, counted basket by basket."""
    items = sorted({i for b in baskets for i in b}, key=AS.item_key)
    out = {}
    for k in range(1, max_size + 1):
        for s in itertools.combinations(items, k):
            c = sum(w for b, w in zip(baskets, weights) if set(s) <= b)
            if c:
                out[tuple(sorted(s, key=AS.item_key))] = c
    return out


BR = brute(B, [1] * NT, 4)
single = {s[0]: c for s, c in BR.items() if len(s) == 1}


def sets_of(r):
    return {tuple(r['items_'][j] for j in s['items']): s['support'] for s in r['item_sets']}


def fit(tid, **kw):
    r = call('association.fit', table=tid, **kw)
    if 'error' not in r:
        r['items_'] = r['items']
    return r


for tag, tid, kw in (('stacked', t_st, {'items': ['item'], 'id_col': 'basket'}), ('several columns', t_cols, {'items': list(cols)}),
                     ('delimited', t_del, {'items': ['items'], 'delimiter': ';'})):
    for algo in ('apriori', 'fpgrowth'):
        r = fit(tid, min_support=0.05, min_confidence=0.3, min_lift=0, algorithm=algo, **kw)
        if not check(f'{tag}, {AS.ALGORITHMS[algo]}: no error', r.get('error'), None):
            continue
        got = sets_of(r)
        want = {s: c / NT for s, c in BR.items() if c / NT >= 0.05}
        check(f'{tag}, {AS.ALGORITHMS[algo]}: the frequent item sets are those counted here (support 5% or more, up to four items)', sorted(got), sorted(want))
        check.near(f'{tag}, {AS.ALGORITHMS[algo]}: and their supports', mx([got[s] for s in want], [want[s] for s in want]), 0.0, abs_=1e-12)
        check(f'{tag}: {NT} transactions of {len(ITEMS)} items', (r['n_transactions'], r['n_items'], r['items']), (NT, len(ITEMS), ITEMS))

# ---- the rules by their definitions -------------------------------------------------------------------------------------------------------------
r = fit(t_st, items=['item'], id_col='basket', min_support=0.05, min_confidence=0.3, min_lift=0)
fam = []
for Z, cz in BR.items():
    if len(Z) < 2 or cz / NT < 0.05 - 1e-12:
        continue
    for k in range(1, min(len(Z) - 1, 3) + 1):
        for X in itertools.combinations(Z, k):
            Y = tuple(i for i in Z if i not in X)
            fam.append((X, Y, cz, BR[X], BR[Y]))
p_ref = [fisher_exact([[cz, cx - cz], [cy - cz, NT - cx - cy + cz]], alternative='greater')[1] for X, Y, cz, cx, cy in fam]
q_ref = multipletests(p_ref, method='fdr_bh')[1]
ref = {}
for (X, Y, cz, cx, cy), p, q in zip(fam, p_ref, q_ref):
    conf = cz / cx
    if conf >= 0.3:
        sy = cy / NT
        ref[(', '.join(X), ', '.join(Y))] = {'support': cz / NT, 'confidence': conf, 'lift': conf / sy, 'coverage': cx / NT, 'leverage': cz / NT - cx / NT * sy,
                                             'conviction': (1 - sy) / (1 - conf) if conf < 1 else math.inf, 'p': p, 'fdr': q}
got = {(x['condition'], x['consequent']): x for x in r['rules']}
check('the rules: every X => Y of the frequent sets with confidence 30% or more (at most three antecedents), as found here', sorted(got), sorted(ref))
check('the family of rules the false discovery rate is over: every rule of the frequent sets', r['n_rules_made'], len(fam))
for m in ('support', 'confidence', 'lift', 'coverage', 'leverage', 'p', 'fdr'):
    check.near(f'each rule\'s {m}, by its definition' + (' (scipy\'s fisher_exact, one-sided)' if m == 'p' else ' (statsmodels\' multipletests, fdr_bh)' if m == 'fdr' else ''),
               mx([got[k][m] for k in ref], [ref[k][m] for k in ref]), 0.0, abs_=1e-12)
fin = [k for k in ref if math.isfinite(ref[k]['conviction'])]
check.near('conviction (1 - P(Y)) / (1 - confidence)', mx([got[k]['conviction'] for k in fin], [ref[k]['conviction'] for k in fin]), 0.0, abs_=1e-9)
conf = [x['confidence'] for x in r['rules']]
check('the Rules: the highest confidence first (as JMP sorts them)', conf == sorted(conf, reverse=True), True)
check('the rule text: condition ⇒ consequent', r['rules'][0]['rule'], f"{r['rules'][0]['condition']} ⇒ {r['rules'][0]['consequent']}")
lift = {k: v['lift'] for k, v in got.items()}
check('the planted associations have the highest lifts: jam with bread and butter, sauce with pasta', (lift[('bread, butter', 'jam')] > 2, lift[('pasta', 'sauce')] > 2.2, lift[('sauce', 'pasta')] == lift[('pasta', 'sauce')]), (True, True, True))
check('and their Fisher p-values are tiny, the independent items\' are not', (got[('pasta', 'sauce')]['fdr'] < 1e-20, got.get(('apples', 'milk'), {'fdr': 1})['fdr'] > 0.01), (True, True))
check('lift below 1: coffee and tea exclude each other', ('coffee', 'tea') not in {tuple(s.split(', ')) for s in [x['set'][1:-1] for x in r['item_sets']]} or got.get(('coffee', 'tea'), {'lift': 0})['lift'] < 1, True)
fs = r['item_sets']
check('the Frequent Item Sets: the highest support first, then fewer items', all((a['support'] > b['support']) or (a['support'] == b['support'] and a['n'] <= b['n']) for a, b in zip(fs, fs[1:])), True)
check('the item set text: {a, b}, alphabetically (case aside)', fs[[x['n'] for x in fs].index(2)]['set'], '{' + ', '.join(r['items'][j] for j in fs[[x['n'] for x in fs].index(2)]['items']) + '}')
r2 = fit(t_st, items=['item'], id_col='basket', min_support=0.05, min_confidence=0.5, min_lift=1.5, max_antecedents=1, max_rule_size=3)
want = {k for k, v in ref.items() if v['confidence'] >= 0.5 and v['lift'] >= 1.5 and len(k[0].split(', ')) == 1 and len(k[0].split(', ')) + len(k[1].split(', ')) <= 3}
check('Minimum Confidence, Minimum Lift, Maximum Antecedents and Maximum Rule Size filter the rules', {(x['condition'], x['consequent']) for x in r2['rules']}, want)
check('Maximum Rule Size: no item set larger', max(x['n'] for x in r2['item_sets']), 3)
d = fit(t_st, items=['item'], id_col='basket')
check('JMP\'s defaults: Minimum Support 0.1, Confidence 0.4, Lift 1.2, 3 antecedents, rule size 4, Apriori',
      d['settings'], {'min_support': 0.1, 'min_confidence': 0.4, 'min_lift': 1.2, 'max_antecedents': 3, 'max_rule_size': 4, 'algorithm': 'apriori'})
check('... every rule shown meets them', all(x['support'] >= 0.1 - 1e-12 and x['confidence'] >= 0.4 - 1e-12 and x['lift'] >= 1.2 - 1e-12 for x in d['rules']), True)

# ---- the three formats, IDs and Freq ----------------------------------------------------------------------------------------------------------
a = fit(t_st, items=['item'], id_col='basket', min_support=0.04)
b = fit(t_cols, items=list(cols), min_support=0.04)
c = fit(t_del, items=['items'], delimiter=';', min_support=0.04)
strip = lambda r: ([(x['set'], round(x['support'], 12)) for x in r['item_sets']], [(x['rule'], round(x['lift'], 12), round(x['fdr'], 12)) for x in r['rules']])  # noqa: E731
check('stacked, several columns and delimited give the same item sets and rules', (strip(a) == strip(b), strip(b) == strip(c)), (True, True))
check('stacked: each transaction\'s rows are its item rows', a['transactions']['rows'][0], [i for i, v in enumerate(st_id) if v == 1])
check('... several columns: each row one transaction', (b['transactions']['rows'][:3], b['transactions']['keys'][:3]), ([[0], [1], [2]], [1, 2, 3]))
# an ID in the several-columns format joins rows; Freq counts a transaction that many times
split_rows = {'cust': [], 'i1': [], 'i2': [], 'i3': []}
for t, bb in enumerate(B):
    items = sorted(bb)
    for a0 in range(0, len(items), 3):   # a basket written three items to a row
        part = items[a0:a0 + 3]
        split_rows['cust'].append(f'c{t:03d}')
        for k in range(3):
            split_rows[f'i{k + 1}'].append(part[k] if k < len(part) else None)
t_split = table(split_rows)
e = fit(t_split, items=['i1', 'i2', 'i3'], id_col='cust', min_support=0.04)
check('several columns with an ID: the rows that share it are one transaction', strip(e) == strip(a), True)
uniq = {}
for bb in B:
    uniq[tuple(sorted(bb))] = uniq.get(tuple(sorted(bb)), 0) + 1
t_freq = table({'items': [';'.join(k) for k in uniq], 'n': list(uniq.values())})
f = fit(t_freq, items=['items'], delimiter=';', freq='n', min_support=0.04)
check(f'Freq: {len(uniq)} distinct baskets with their counts give the {NT} baskets\' item sets and rules', (strip(f) == strip(a), f['total'], f['n_transactions']), (True, NT, len(uniq)))
t_frac = table({'items': [';'.join(k) for k in uniq], 'n': [v + 0.7 for v in uniq.values()]})
check('Freq is truncated to a whole number, as JMP\'s', strip(fit(t_frac, items=['items'], delimiter=';', freq='n', min_support=0.04)) == strip(a), True)
g = fit(t_st, items=['item'], id_col='basket', freq='basket', min_support=0.04)
check('stacked data: Freq is not used, and the report says so', (strip(g) == strip(a), any('not used' in n for n in g['notes'])), (True, True))
tmiss = table({'id': [1, 1, None, 2, 2, 3], 'item': ['a', 'b', 'a', 'a', None, None]})
m = fit(tmiss, items=['item'], id_col='id', min_support=0.1, min_confidence=0, min_lift=0)
check('rows with no ID and transactions with no items are left out, and said so', (m['n_transactions'], m['notes']), (2, ['1 row with no id left out.', '1 transaction with no items left out.']))
from smui import data as _data  # noqa: E402
t_vl = table({'basket': st_id, 'item': st_item, 'code': [ITEMS.index(v) + 1 for v in st_item]}, types={'basket': 'nominal', 'code': 'nominal'})
_data.TABLES[t_vl]['meta']['item']['valueLabels'] = [['bread', 'Bread (white)'], ['jam', 'Jam']]
_data.TABLES[t_vl]['meta']['code']['valueLabels'] = [[float(k + 1), v.title()] for k, v in enumerate(ITEMS)]
vl = fit(t_vl, items=['item'], id_col='basket', min_support=0.04)
check('Value Labels: the items are shown by them (and sorted by them)', vl['items'], sorted(['Bread (white)', 'Jam'] + [i for i in ITEMS if i not in ('bread', 'jam')], key=AS.item_key))
check('... in the item sets, which are otherwise the same', sorted((x['set'].replace('Bread (white)', 'bread').replace('Jam', 'jam'), round(x['support'], 12)) for x in vl['item_sets']), sorted(strip(a)[0]))
vn = fit(t_vl, items=['code'], id_col='basket', min_support=0.04)
check('... a numeric item column\'s labels too', vn['items'], sorted([i.title() for i in ITEMS], key=AS.item_key))
check('numeric items and IDs read as their labels (2.0 as 2)',fit(table({'id': [1, 1, 2], 'item': [1.0, 2.0, 2.0]}, types={'item': 'nominal'}), items=['item'], id_col='id', min_support=0.1)['items'], ['1', '2'])
check('one Item column without an ID or a delimiter: an error that says what to do', 'give the ID' in fit(t_del, items=['items'])['error'], True)
check('bad settings: errors that name them', ['Minimum Support' in fit(t_st, items=['item'], id_col='basket', min_support=0)['error'],
      'Minimum Confidence' in fit(t_st, items=['item'], id_col='basket', min_confidence=1.5)['error'],
      'Maximum Rule Size' in fit(t_st, items=['item'], id_col='basket', max_rule_size=1)['error'],
      'Maximum Antecedents' in fit(t_st, items=['item'], id_col='basket', max_antecedents=0.5)['error'],
      'the ID column is an Item column' in fit(t_st, items=['item'], id_col='item')['error']], [True] * 5)
rs = fit(t_st, items=['item'], id_col='basket', rows=[i for i, v in enumerate(st_id) if v <= 250], min_support=0.05)
check('a row list (a By group, exclusions) limits the transactions', (rs['n_transactions'], sorted(sets_of(rs)) == sorted(s for s, cc in brute(B[:250], [1] * 250, 4).items() if cc / 250 >= 0.05)), (250, True))

# ---- Apriori and FP-growth on their own: random sets, weights, the same answers ------------------------------------------------------------
for seed in (1, 2, 3):
    rr = np.random.default_rng(seed)
    M = rr.random((300, 14)) < rr.uniform(0.05, 0.6, 14)
    M[:, 3] |= M[:, 2] & (rr.random(300) < 0.8)
    w = rr.integers(1, 5, 300).astype(float)
    A1 = AS.apriori(M, w, 0.08 * w.sum(), 5)
    F1 = AS.fpgrowth(M, w, 0.08 * w.sum(), 5)
    bf = {}
    for k in range(1, 6):
        for s in itertools.combinations(range(14), k):
            cnt = float(w[np.all(M[:, list(s)], axis=1)].sum())
            if cnt >= 0.08 * w.sum():
                bf[s] = cnt
    check(f'random set {seed}: Apriori = FP-growth = brute force, weighted ({len(bf)} sets up to five items)', (A1 == bf, F1 == bf), (True, True))
check.near('Benjamini-Hochberg against statsmodels on random p-values', mx(AS.bh(np.random.default_rng(5).random(40)), multipletests(np.random.default_rng(5).random(40), method='fdr_bh')[1]), 0.0, abs_=1e-15)

# ---- the Python shown runs on a CSV export and gives the report's numbers ------------------------------------------------------------------
work = tempfile.mkdtemp()
DUMP = '''
import json as _j
_o = {}
for _k in ("item_sets", "rule_table", "keys", "names"):
    if _k in globals():
        _v = globals()[_k]
        _o[_k] = _v.to_dict("split") if hasattr(_v, "to_dict") else _v
print("@@" + _j.dumps(_o, default=str))
'''


def run(code, name, frame):
    frame.to_csv(os.path.join(work, f'{name}.csv'), index=False)
    p_ = subprocess.run([sys.executable, '-c', code + DUMP], cwd=work, capture_output=True, text=True, timeout=600)
    if p_.returncode:
        print(p_.stderr[-3000:])
        return None
    return json.loads(next(ln for ln in p_.stdout.splitlines() if ln.startswith('@@'))[2:])


frames = {'stacked': ('Baskets', pd.DataFrame({'basket': st_id, 'item': st_item}), t_st, {'items': ['item'], 'id_col': 'basket'}),
          'several columns': ('Wide', pd.DataFrame(cols), t_cols, {'items': list(cols)}),
          'delimited, Freq': ('Counted', pd.DataFrame({'items': [';'.join(k) for k in uniq], 'n': list(uniq.values())}), t_freq, {'items': ['items'], 'delimiter': ';', 'freq': 'n'}),
          'with an ID': ('Split', pd.DataFrame(split_rows), t_split, {'items': ['i1', 'i2', 'i3'], 'id_col': 'cust'}),
          'Value Labels': ('Labelled', pd.DataFrame({'basket': st_id, 'item': st_item, 'code': [ITEMS.index(v) + 1 for v in st_item]}), t_vl, {'items': ['code'], 'id_col': 'basket'})}
for tag, (name, frame, tid, kw) in frames.items():
    for algo in ('apriori', 'fpgrowth'):
        r = call('association.fit', table=tid, table_name=name, min_support=0.05, min_confidence=0.35, algorithm=algo, **kw)
        o = run(r['code'], name, frame)
        if not check(f'the code runs ({tag}, {AS.ALGORITHMS[algo]})', o is not None, True):
            continue
        s_ = o['item_sets']['data']
        check(f'... and gives the Frequent Item Sets ({tag}, {AS.ALGORITHMS[algo]})', ([x[0] for x in s_], mx([x[1] for x in s_], [x['support'] for x in r['item_sets']])), ([x['set'] for x in r['item_sets']], 0.0))
        rt_ = o['rule_table']
        cix = {c: k for k, c in enumerate(rt_['columns'])}
        check(f'... and the Rules ({tag}, {AS.ALGORITHMS[algo]})', ([f'{x[cix["Condition"]]} ⇒ {x[cix["Consequent"]]}' for x in rt_['data']], mx([[x[cix[c]] for c in ('Confidence', 'Lift', 'Support', 'Fisher p', 'FDR p')] for x in rt_['data']],
              [[x[m] for m in ('confidence', 'lift', 'support', 'p', 'fdr')] for x in r['rules']])), ([x['rule'] for x in r['rules']], 0.0))
# a By group with rows left out
grp = [i for i, v in enumerate(st_id) if v % 2 == 0]
t_g = table({'basket': st_id, 'item': st_item, 'half': ['even' if v % 2 == 0 else 'odd' for v in st_id]}, types={'basket': 'nominal'})
drop = [grp[0], grp[1]]
rows = [i for i in grp if i not in drop]
r = call('association.fit', table=t_g, items=['item'], id_col='basket', rows=rows, where=[{'column': 'half', 'value': 'even'}], min_support=0.05, table_name='Halves')
check('a By group: the code keeps the group and drops the rows left out', ('df = df[df["half"] == "even"]' in r['code'], f'df = df.drop(index={drop})' in r['code']), (True, True))
o = run(r['code'], 'Halves', pd.DataFrame({'basket': st_id, 'item': st_item, 'half': ['even' if v % 2 == 0 else 'odd' for v in st_id]}))
if check('... and runs', o is not None, True):
    check('... giving the group\'s item sets', [x[0] for x in o['item_sets']['data']], [x['set'] for x in r['item_sets']])

# ---- the bubble plot's code ------------------------------------------------------------------------------------------------------------------------------
from test_charts import run_snippet  # noqa: E402

r = call('association.fit', table=t_st, items=['item'], id_col='basket', min_support=0.05, min_confidence=0.35, table_name='Baskets')
figs, err = run_snippet(r['plot_code']['bubbles'], pd.DataFrame({'basket': st_id, 'item': st_item}), 'Baskets', work)
check('the bubble plot\'s code runs and ends with plt.show()', (err, r['plot_code']['bubbles'].rstrip().split('\n')[-1]), (None, 'plt.show()'))
if figs:
    ax = figs[0]['axes'][0]
    pts = ax['scatter'][0]['xy']
    check.near('... a bubble per rule at its confidence and lift', mx(pts, [[x['confidence'], x['lift']] for x in r['rules']]), 0.0, abs_=1e-12)
    smax = max(x['support'] for x in r['rules'])
    check.near('... its area following the support (28 px across for the largest, at least 5)', mx(ax['scatter'][0]['sizes'], [(0.72 * max(5, 28 * math.sqrt(x['support'] / smax))) ** 2 for x in r['rules']]), 0.0, abs_=1e-9)
    check('... the axes and the title', (ax['xlabel'], ax['ylabel'], ax['title'], figs[0]['size']), ('Confidence', 'Lift', 'Rules: confidence, lift and support', [5.2, 4.0]))
check('no rules: no bubble plot', call('association.fit', table=t_st, items=['item'], id_col='basket', min_confidence=1.0, min_lift=100)['plot_code'], {})

# ---- 20,000 transactions of 60 items --------------------------------------------------------------------------------------------------------------------
rr = np.random.default_rng(9)
Mb = rr.random((20000, 60)) < rr.uniform(0.02, 0.4, 60)
Mb[:, 1] |= Mb[:, 0] & (rr.random(20000) < 0.7)
names60 = [f'item{j:02d}' for j in range(60)]
tb = table({'items': [','.join(names60[j] for j in np.flatnonzero(row)) or 'item00' for row in Mb]})
for algo in ('apriori', 'fpgrowth'):
    t0 = time.time()
    rb = call('association.fit', table=tb, items=['items'], delimiter=',', min_support=0.05, algorithm=algo)
    dt = time.time() - t0
    print(f'      20,000 transactions, 60 items, {AS.ALGORITHMS[algo]}: {dt:.2f} s natively, {len(rb["item_sets"])} item sets, {len(rb["rules"])} rules; the result {len(json.dumps(rb)) / 1e6:.2f} MB')
    check(f'20,000 transactions: {AS.ALGORITHMS[algo]} in under 10 s natively', dt < 10, True)

sys.exit(check.done())
