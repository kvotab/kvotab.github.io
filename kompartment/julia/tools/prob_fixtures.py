"""Reference probabilistic runs for the Julia port's tests, from the Python package.

Writes, as JSON with every float as its hex text (``float.hex``), what the
Julia port of ``kompartment/engine/probabilistic.py`` and ``kompartment/stats``
must reproduce bit for bit:

- ``units.json``: the pieces -- named streams, columns of uniforms (Latin
  hypercube and random), a value drawn from every kind of distribution with and
  without truncation at many probabilities, the normal CDF and quantile, the
  correlation pairs a model's settings give and Iman-Conover's permutations;
- ``runs/<case>.json``: probabilistic runs -- the sampling plan, the design (every
  value drawn), and every realisation of the series kept, with the statistics,
  the inputs and which realisations ran -- of the bundled examples that have
  distributions or random events and of made-up models covering every kind,
  truncation, correlation groups and pairs, lookup points with spreads, Poisson
  events, failed realisations and a tornado;
- ``models/<name>.json``: each model run, as the Python package's ``Model``
  settles it (``to_dict``), which is the dictionary both sides build from.

    python3 tools/prob_fixtures.py OUT_DIR [case ...]

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``). Nothing is written in the repository.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'


def hexes(v):
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


def hexf(x):
    return float(x).hex()


def drawn(v):
    """A value drawn, as JSON: hex for a number, null for none, {'$b': x} for a boolean."""
    if v is None:
        return None
    if isinstance(v, bool):
        return {'$b': v}
    return hexf(v)


def plain(v):
    """Something JSON can hold, floats as hex text."""
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return [plain(x) for x in v.tolist()]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return {'$f': hexf(v)}
    return v


# --- made-up models ----------------------------------------------------------------------

def pdf(kind, *, trmin=None, trmax=None, pmin=None, pmax=None, group=None, values=None, inorder=True, pos=0,
        **params):
    return {'kind': kind, 'params': params, 'values': values, 'trmin': trmin, 'trmax': trmax, 'pmin': pmin,
            'pmax': pmax, 'group': group, 'inorder': inorder, 'pos': pos}


SIM = {'start_time': 0, 'end_time': 1000, 'output_points': 25, 'spacing': 'linear', 'solver': 'ndf', 'rtol': 1e-6,
       'abstol': 1e-9, 'time_unit': 'year'}


def scalar(name, value, spec, **kw):
    return {'name': name, 'value': value, 'per_nuclide': False, 'unit': '', 'pdf': spec, **kw}


def model_kinds():
    """Every kind of distribution, with and without truncation, on scalar and indexed parameters."""
    params = [
        scalar('a_unif', 0.5, pdf('unif', min=0.1, max=0.9)),
        scalar('a_unif_cut', 0.5, pdf('unif', min=0.1, max=0.9, trmin=0.2, trmax=0.7)),
        scalar('a_unif_rev', 0.5, pdf('unif', min=0.0, max=6.5, trmin=6.5, trmax=0.0)),
        scalar('b_triang', 0.3, pdf('triang', min=0.1, max=0.9, mode=0.3)),
        scalar('b_triang_p', 0.3, pdf('triang', min=0.1, max=0.9, mode=0.3, pmin=0.1, pmax=0.8)),
        scalar('c_dtriang', 3, pdf('dtriang', min=1, max=9, mode=3)),
        scalar('c_dtriang_cut', 3, pdf('dtriang', min=1, max=9, mode=3, trmin=2, trmax=8)),
        scalar('d_norm', 5, pdf('norm', mean=5, sd=2)),
        scalar('d_norm_cut', 5, pdf('norm', mean=5, sd=2, trmin=3, pmax=0.9)),
        scalar('e_logu', 1, pdf('logu', min=1e-3, max=1e2)),
        scalar('e_logu_cut', 1, pdf('logu', min=1e-3, max=1e2, trmax=10)),
        scalar('f_logt', 1e-11, pdf('logt', min=7e-12, max=5e-11, mode=1e-11)),
        scalar('f_logt_p', 1e-11, pdf('logt', min=7e-12, max=5e-11, mode=1e-11, pmin=0.05, pmax=0.95)),
        scalar('g_logdt', 3, pdf('logdt', min=0.7, max=20, mode=3)),
        scalar('g_logdt_p', 3, pdf('logdt', min=0.7, max=20, mode=3, pmin=0.05, pmax=0.95)),
        scalar('h_logn4', 1e-3, pdf('Logn4', gm=1e-3, gsd=3)),
        scalar('h_logn4_cut', 1e-3, pdf('Logn4', gm=1e-3, gsd=3, trmin=1e-4, trmax=1e-2)),
        scalar('i_logn', 2, pdf('logn', mean=2, sd=1)),
        scalar('i_logn_cut', 2, pdf('logn', mean=2, sd=1, trmax=5)),
        scalar('j_logn5', 10, pdf('logn5', p1=0.05, x1=1, p2=0.95, x2=100)),
        scalar('k_pg', 3, pdf('pg', values=[1, 2, 3, 4, 5])),
        scalar('k_pg_pos', 20, pdf('pg', values=[10, 20, 30], pos=2)),
        scalar('k_pg_rand', 0.2, pdf('pg', values=[0.1, 0.2, 0.4, 0.8], inorder=False)),
        {'name': 'kd', 'value': 1.0, 'unit': '',
         'entries': [{'index': {'Radionuclides': 'I-129'}, 'pdf': pdf('logt', min=0.5, max=5, mode=1)},
                     {'index': {'Radionuclides': 'Cs-135'}, 'pdf': pdf('norm', mean=2, sd=0.5, trmin=0.5)}]},
    ]
    every = ' + '.join(p['name'] for p in params if p['name'] not in ('kd', 'f_logt', 'f_logt_p'))
    return {
        'name': 'Every kind', 'nuclides': ['I-129', 'Cs-135'], 'simulation': dict(SIM),
        'parameters': params,
        'compartments': [{'name': 'Source', 'initial': '1e6', 'unit': 'Bq'}, {'name': 'Sink', 'initial': '0', 'unit': 'Bq'}],
        'transfers': [{'name': 'Out', 'from': 'Source', 'to': 'Sink', 'rate': '1e-3 * a_unif * kd'}],
        'expressions': [{'name': 'Mix', 'equation': every + ' + (f_logt + f_logt_p) * 1e10', 'unit': ''},
                        {'name': 'Held', 'equation': 'Sink * b_triang / (1 + d_norm * d_norm)', 'unit': 'Bq'}],
    }


def model_correlations():
    """Correlation groups and pairs, the problems a list of them can have, and a target that is no correlation matrix."""
    kd = {'name': 'Kd', 'value': 1.0, 'unit': 'm3/kg',
          'entries': [{'index': {'Radionuclides': 'I-129'}, 'pdf': pdf('logt', min=1e-4, max=1e-2, mode=1e-3)},
                      {'index': {'Radionuclides': 'Cs-135'}, 'pdf': pdf('logt', min=1e-2, max=1, mode=0.1)},
                      {'index': {'Radionuclides': 'Tc-99'}, 'pdf': pdf('logu', min=1e-4, max=1e-1)}]}
    params = [
        kd,
        scalar('q1', 0.5, pdf('unif', min=0, max=1, group='G')),
        scalar('q2', 2, pdf('logu', min=1, max=10, group=' G ')),
        scalar('r1', 0, pdf('norm', mean=0, sd=1)),
        scalar('r2', 0, pdf('norm', mean=0, sd=1)),
        scalar('r3', 0, pdf('norm', mean=0, sd=1)),
        scalar('s1', 0.5, pdf('triang', min=0, max=1, mode=0.5)),
    ]
    sim = dict(SIM)
    sim['correlations'] = [
        {'a': 'r1', 'b': 'r2', 'r': 0.9},
        {'a': 'r2', 'b': 'r3', 'r': 0.9},
        {'a': 'r1', 'b': 'r3', 'r': -0.9},
        {'group': 'Kd', 'r': 0.7},
        {'a': 'Kd[I-129]', 'b': 'Kd[Tc-99]', 'r': 0.5},
        {'a': 'q1', 'b': 's1', 'r': 0.4},
        {'a': 'nope', 'b': 'r1', 'r': 0.3},
        {'a': 'r1', 'b': 'r1', 'r': 0.2},
        {'a': 'r1', 'b': 's1', 'r': 1.5},
        {'group': 's1', 'r': 0.5},
        {'group': 'zz', 'r': 0.5},
        {'a': 's1', 'b': 'r2', 'r': '-0.3'},
    ]
    return {
        'name': 'Correlated', 'nuclides': ['I-129', 'Cs-135', 'Tc-99'], 'simulation': sim, 'parameters': params,
        'compartments': [{'name': 'Water', 'initial': '1e8', 'unit': 'Bq'}, {'name': 'Rock', 'initial': '0', 'unit': 'Bq'}],
        'transfers': [{'name': 'Sorb', 'from': 'Water', 'to': 'Rock', 'rate': '1e-2 * Kd * (1 + q1) * q2'},
                      {'name': 'Back', 'from': 'Rock', 'to': 'Water', 'rate': '1e-3 * (2 + s1)'}],
        'expressions': [{'name': 'Signal', 'equation': 'Water * (3 + r1 + r2 + r3)', 'unit': 'Bq'}],
    }


def model_lookup():
    """Lookup tables whose points carry spreads, one of them indexed with an entry of its own."""
    return {
        'name': 'Spread tables', 'nuclides': ['I-129', 'Cs-135'],
        'simulation': {**SIM, 'output_points': 30},
        'parameters': [scalar('scale', 1.0, pdf('unif', min=0.5, max=1.5))],
        'lookups': [
            {'name': 'Q', 'unit': '', 'interpolation': 'linear', 'index_lists': [],
             'points': [[0, 1.0], [250, 2.0, pdf('unif', min=1.5, max=2.5)],
                        [500, 1.5, pdf('logn', mean=1.5, sd=0.3)], [1000, 1.0]]},
            {'name': 'R', 'unit': '', 'interpolation': 'linear', 'index_lists': ['Radionuclides'],
             'points': [[0, 1.0], [1000, 2.0, pdf('triang', min=1.5, max=3, mode=2)]],
             'entries': [{'index': {'Radionuclides': 'Cs-135'},
                          'points': [[0, 3.0, pdf('norm', mean=3, sd=0.2)], [1000, 4.0]]}]},
        ],
        'compartments': [{'name': 'Up', 'initial': '1e5', 'unit': 'Bq'}, {'name': 'Down', 'initial': '0', 'unit': 'Bq'}],
        'transfers': [{'name': 'Flow', 'from': 'Up', 'to': 'Down', 'rate': '1e-3 * Q * R * scale'}],
        'expressions': [{'name': 'Read', 'equation': 'Q * R', 'unit': ''}],
    }


def model_events():
    """Poisson events: drawn with a sampled rate and a window, drawn at a fixed rate, and one not drawn."""
    return {
        'name': 'Random events', 'nuclides': ['I-129', 'Cs-135'],
        'simulation': {**SIM, 'output_points': 40},
        'parameters': [scalar('slip_rate', 5e-3, pdf('logu', min=1e-3, max=1e-2)),
                       scalar('leak', 1e-3, pdf('triang', min=5e-4, max=2e-3, mode=1e-3))],
        'compartments': [{'name': 'Store', 'initial': '1e6', 'unit': 'Bq'}, {'name': 'Out', 'initial': '0', 'unit': 'Bq'},
                         {'name': 'Lost', 'initial': '0', 'unit': 'Bq'}],
        'transfers': [{'name': 'Leak', 'from': 'Store', 'to': 'Out', 'rate': 'leak'}],
        'events': [
            {'name': 'Slip', 'timing': 'poisson', 'rate': 'slip_rate', 'from': '100', 'until': '900', 'sampled': True,
             'unit': '', 'index_lists': [], 'actions': [{'kind': 'move', 'from': 'Store', 'to': 'Out', 'fraction': '0.3'}]},
            {'name': 'Shock', 'timing': 'poisson', 'rate': '2e-3', 'from': '', 'until': '', 'sampled': True, 'unit': '',
             'index_lists': [], 'actions': [{'kind': 'move', 'from': 'Out', 'to': None, 'fraction': '0.5'}]},
            {'name': 'Quiet', 'timing': 'poisson', 'rate': '1e-2', 'from': '', 'until': '', 'sampled': False, 'unit': '',
             'index_lists': [], 'actions': [{'kind': 'move', 'from': 'Store', 'to': 'Lost', 'fraction': '0.1'}]},
        ],
    }


def model_failing():
    """Realisations that cannot start (an initial inventory divided by a zero drawn from a list)."""
    return {
        'name': 'Some fail', 'simulation': {**SIM, 'output_points': 15},
        'parameters': [scalar('k', 1, pdf('pg', values=[1, 0, 2, 0, 3, 4, 0])),
                       scalar('m', 1, pdf('unif', min=0.5, max=1.5))],
        'compartments': [{'name': 'A', 'initial': '1e3 / k', 'unit': 'Bq'}, {'name': 'B', 'initial': '0', 'unit': 'Bq'}],
        'transfers': [{'name': 'AB', 'from': 'A', 'to': 'B', 'rate': 'm * 1e-3'}],
    }


def model_carry():
    """Draws that are not numbers: a list with gaps and a log-triangular below zero."""
    return {
        'name': 'Gaps', 'simulation': {**SIM, 'output_points': 12},
        'parameters': [scalar('p', 1.0, pdf('pg', values=[0.5, None, 2.0, None, None, 4.0])),
                       scalar('p_rand', 1.0, pdf('pg', values=[None, 0.3, None, 0.9], inorder=False)),
                       scalar('q_bad', 1.0, pdf('logt', min=-1, max=10, mode=1)),
                       scalar('w', 1.0, pdf('logu', min=0.1, max=10))],
        'compartments': [{'name': 'C', 'initial': '100', 'unit': 'Bq'}],
        'transfers': [{'name': 'Loss', 'from': 'C', 'to': None, 'rate': '1e-3 * p * p_rand * q_bad * w'}],
        'expressions': [{'name': 'Seen', 'equation': 'p + 10 * p_rand + 100 * q_bad + 1000 * w', 'unit': ''}],
    }


def model_varied():
    """`simulation.varied` naming some of the inputs (and one that is not there)."""
    m = model_kinds()
    m['name'] = 'Some varied'
    m['simulation'] = {**m['simulation'], 'varied': ['a_unif', 'kd[I-129]', 'k_pg', 'nonexistent']}
    return m


def with_spread(stem: str):
    """A bundled example with a spread of ten per cent either way on every parameter that is a number, and
    on the second point of every lookup table: what makes any model a probabilistic one."""
    def make():
        m = json.loads((EXAMPLES / (stem + '.json')).read_text())
        m['name'] = f"{m.get('name', stem)} (spread)"
        for p in m.get('parameters') or []:
            v = p.get('value')
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v == 0:
                continue
            lo, hi = sorted((0.9 * v, 1.1 * v))
            p['pdf'] = pdf('unif', min=lo, max=hi)
        for lk in m.get('lookups') or []:
            pts = lk.get('points')
            if isinstance(pts, list) and len(pts) >= 2 and isinstance(pts[1], list) and len(pts[1]) >= 2:
                y = pts[1][1]
                if isinstance(y, (int, float)) and not isinstance(y, bool) and y != 0:
                    lo, hi = sorted((0.9 * y, 1.1 * y))
                    pts[1] = [pts[1][0], y, pdf('triang', min=lo, max=hi, mode=y)]
        return m
    return make


SPREAD = ['bouncing-ball', 'brusselator', 'decay-chain', 'exponential-decay', 'farfield', 'four-compartment',
          'harmonic-oscillator', 'landscape', 'lookup-driver', 'lorenz', 'lotka-volterra', 'michaelis-menten',
          'oregonator', 'post-processing', 'recorders', 'robertson', 'scenarios', 'sir-epidemic', 'thermostat',
          'van-der-pol-stiff', 'van-der-pol', 'waste-packages']

MADE_UP = {
    'kinds': model_kinds, 'correlations': model_correlations, 'lookup': model_lookup, 'events': model_events,
    'failing': model_failing, 'carry': model_carry, 'varied': model_varied,
    **{f'{stem}_spread': with_spread(stem) for stem in SPREAD},
}

# (case, model, options): a model is a bundled example's file name or a made-up model's key.
CASES = [
    ('biosphere_latin', 'biosphere.json', {'iterations': 50, 'seed': 1}),
    ('biosphere_random', 'biosphere.json', {'iterations': 20, 'seed': 7, 'latin': False, 'keep': ['Dose']}),
    ('biosphere_range', 'biosphere.json', {'iterations': 30, 'seed': 3, 'range_': [5, 17], 'keep': ['Dose', 'Well']}),
    ('biosphere_tornado', 'biosphere.json', {'tornado': {'low': 0.05, 'high': 0.95}, 'keep': ['Dose']}),
    ('biosphere_varied', 'biosphere.json', {'iterations': 20, 'seed': 9, 'varied': ['Kd[I-129]', 'soilLeach'],
                                            'keep': ['Dose', 'Soil [I-129]']}),
    ('waste_quake', 'waste-packages.json', {'iterations': 20, 'seed': 5, 'keep': ['Biosphere', 'NearField']}),
    ('kinds_latin', 'kinds', {'iterations': 40, 'seed': 11}),
    ('kinds_random', 'kinds', {'iterations': 25, 'seed': -5, 'latin': False}),
    ('kinds_bigseed', 'kinds', {'iterations': 12, 'seed': 4294967297}),
    ('kinds_tornado', 'kinds', {'tornado': {'low': 0.1, 'high': 0.9}, 'keep': ['Mix']}),
    ('correlations', 'correlations', {'iterations': 40, 'seed': 2}),
    ('correlations_random', 'correlations', {'iterations': 9, 'seed': 31, 'latin': False}),
    ('lookup', 'lookup', {'iterations': 30, 'seed': 4}),
    ('events', 'events', {'iterations': 30, 'seed': 6}),
    ('failing', 'failing', {'iterations': 14, 'seed': 8}),
    ('carry', 'carry', {'iterations': 12, 'seed': 12}),
    ('varied', 'varied', {'iterations': 15, 'seed': 13, 'keep': ['Mix']}),
    *[(f'{stem}_spread', f'{stem}_spread', {'iterations': 12, 'seed': 21, 'keep': 'small'}) for stem in SPREAD],
]


def small_keep(m) -> list:
    """Every endpoint of a small model; a few blocks of a large one, so a fixture stays small."""
    d = m.to_dict()
    names = [b['name'] for c in ('compartments', 'expressions', 'transfers', 'index_reductions', 'block_reductions',
                                 'min_maxes', 'snapshots', 'running_means', 'delays', 'triggers', 'farfields',
                                 'waste_packages', 'events') for b in d.get(c) or []]
    return names[:6]


def load_model(key: str, out_dir: Path):
    import kompartment as kp
    if key in MADE_UP:
        m = kp.Model.from_dict(MADE_UP[key]())
        stem = key
    else:
        m = kp.Model.load(EXAMPLES / key)
        stem = Path(key).stem
    path = out_dir / 'models' / (stem + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m.to_dict()))
    return m, path.name


# The cases whose result files are written too, and the time they say they were made.
H5_CASES = {'biosphere_latin', 'failing', 'kinds_latin', 'events', 'carry'}
H5_NOW = 1700000000

# The cases whose analysis is written too: bands, quantiles, summaries, what drove it, a tornado's table.
ANALYSE = {'biosphere_latin', 'kinds_latin', 'failing', 'correlations', 'biosphere_tornado', 'kinds_tornado',
           'carry', 'biosphere_varied'}


def analysis_fixture(prob) -> dict:
    """What the analysis says about a run, as the Julia port must say it (times and series from 0 here)."""
    labels = list(prob.labels)
    inputs = [i['output']['label'] for i in prob.inputs]
    n = prob.iterations
    mask = [i % 3 != 1 for i in range(n)]
    out: dict = {'labels': labels, 'inputs': inputs, 'mask': mask}

    def band(b):
        return {'q': [hexes(y) for y in b['q']], 'quantiles': [float(q) for q in b['quantiles']],
                'mean': hexes(b['mean']), 'sd': hexes(b['sd']['sd']), 'n': [int(x) for x in b['sd']['n']],
                'med': {k: hexes(v) for k, v in b['med'].items()}, 'flat': bool(b.get('flat', False))}

    first = labels[0]
    out['quantiles'] = {'label': first, 'q': {str(q): hexes(y) for q, y in prob.quantiles(first).items()},
                        'mean': hexes(prob.mean(first)),
                        'med': {k: hexes(v) for k, v in prob.median_spread(first).items()}}
    if prob.stats.get('tornado'):
        tables = []
        for label in labels[:2]:
            for stat, at in (('max', 0), ('final', 0), ('at', 5), ('min', 0)):
                t = prob.tornado_table(label, stat, at)
                tables.append({'label': label, 'stat': stat, 'at': at, 'index': t['index'], 'central': hexf(t['central']),
                               'rows': [[r['k'], r['name'], list(r['where']), hexf(r['low']), hexf(r['high']),
                                         hexf(r['lowInput']), hexf(r['highInput']), hexf(r['swing'])]
                                        for r in t['rows']]})
        out['tornado'] = tables
        return out
    picks = [labels[0], labels[-1]] + inputs[:1]
    summaries = []
    for label in picks:
        for at in (None, 10, 'peak', 'max'):
            for m in (None, mask):
                r = prob.summary(label, at, None if m is None else np.array(m))
                sm = r['summary']
                summaries.append({'label': label, 'at': at, 'masked': m is not None, 'where': r['at'],
                                  'peaks': None if r['peaks'] is None else {k: (hexf(v) if k != 'n' else v)
                                                                           for k, v in r['peaks'].items()},
                                  'column': hexes(r['column']), 'n': sm['n'],
                                  'numbers': [hexf(sm[k]) for k in ('mean', 'sd', 'skewness', 'kurtosis', 'min',
                                                                     'max', 'dkw')],
                                  'bounds': hexes(sm['meanBounds']),
                                  'percentiles': [hexf(p['value']) for p in sm['percentiles']]})
    out['summary'] = summaries
    drove = []
    for label in picks:
        for at in (None, 7, 'peak', 'max'):
            for translate in ('none', 'rank', 'log'):
                for m in ((None, mask) if translate == 'none' else (None,)):
                    r = prob.what_drove(label, at, translate=translate, mask=None if m is None else np.array(m))
                    meas = r['measures']
                    drove.append({
                        'label': label, 'at': at, 'translate': translate, 'masked': m is not None, 'where': r['at'],
                        'index': r['index'], 'kept': r['kept'], 'using': r['using'],
                        'rows': [[row['k'], hexf(row['pearson']), hexf(row['spearman']), row['name'],
                                  list(row['where'])] for row in r['rows']],
                        'curves': [[c['k'], hexes(c['y'])] for c in r['curves']],
                        'measures': None if meas is None else {
                            'ok': bool(meas['ok']), 'used': int(meas['used']), 'r2': hexf(meas['r2']),
                            'dropped': int(meas['dropped']), 'src': hexes(meas['src']), 'b': hexes(meas['b']),
                            'pcc': hexes(meas['pcc']), 's1': hexes(meas['s1'])}})
    out['what_drove'] = drove
    # Last: bands put the varied parameters among the series, on the Python side for good.
    out['bands'] = [band(b) for b in prob.bands()]
    out['bands_masked'] = [band(b) for b in prob.bands([0.1, 0.9], np.array(mask))]
    return out


def run_case(name: str, key: str, options: dict, out_dir: Path) -> dict:
    m, model_file = load_model(key, out_dir)
    opts = dict(options)
    if opts.get('keep') == 'small':
        opts['keep'] = small_keep(m)
    options = dict(opts)
    iterations = opts.pop('iterations', 100)
    seed = opts.pop('seed', 1)
    started = time.perf_counter()
    try:
        prob = m.run_probabilistic(iterations, seed=seed, workers=1, **opts)
    except Exception as e:  # noqa: BLE001 - the refusal is the fixture
        return {'name': name, 'model': model_file, 'options': {'iterations': iterations, 'seed': seed, **options},
                'error': f'{type(e).__name__}: {e}'}
    took = time.perf_counter() - started
    out = {'name': name, 'model': model_file, 'options': {'iterations': iterations, 'seed': seed, **options},
           'iterations': prob.iterations, 'from': prob.data['from'], 'to': prob.data['to'],
           'precision': prob.data['precision'], 'names': list(prob.names),
           'plan': [{'slot': int(e['slot']), 'name': e['name'], 'index': dict(e.get('index') or {}),
                     'spec': e['spec']} for e in prob.plan],
           'samples': [hexes(row) for row in prob.samples],
           't': hexes(prob.t),
           'outputs': [{k: plain(o.get(k)) for k in ('label', 'block', 'kind', 'source', 'offset') if k in o}
                       for o in prob.outputs],
           'values': [hexes(v) for v in prob.values],
           'inputs': [{'label': i['output']['label'], 'offset': int(i['output']['offset']), 'k': int(i['k'])}
                      for i in prob.inputs],
           'ran': [int(x) for x in prob.ran],
           'stats': plain({k: v for k, v in prob.stats.items() if k not in ('ms',)}),
           'python_seconds': took}
    if name in H5_CASES:
        # The result file the user's script writes (`probabilistic_tree(prob, 'all', project=...)`), and the
        # mean and one realisation, at a fixed time stamp. The model is given as its dictionary: given as a
        # Model, the Python package writes only the index lists the model stores.
        from kompartment.io.hdf5 import write_hdf5
        from kompartment.io.resultfile import probabilistic_tree
        (out_dir / 'h5').mkdir(parents=True, exist_ok=True)
        files = []
        for want in ('all', 'mean', 3):
            path = out_dir / 'h5' / f'{name}_{want}.h5'
            path.write_bytes(write_hdf5(probabilistic_tree(prob, want, project=m.to_dict(), now=H5_NOW)))
            files.append([want, path.name])
        out['h5'] = {'now': H5_NOW, 'files': files}
    if name in ANALYSE:
        out['analysis'] = analysis_fixture(prob)
    return out


# --- the pieces ----------------------------------------------------------------------------

UNIT_SPECS = [
    pdf('unif', min=1, max=3),
    pdf('unif', min=1, max=3, trmin=1.5, trmax=2.5),
    pdf('unif', min=0.0, max=6.5, trmin=6.5, trmax=0.0),
    pdf('unif', min='1', max=' 3 '),
    pdf('unif', min=1, max=3, trmin='1.5'),
    pdf('triang', min=0.1, max=0.9, mode=0.3),
    pdf('triang', min=0.1, max=0.9, mode=0.1),
    pdf('triang', min=0.1, max=0.9, mode=0.3, pmin=0.1, pmax=0.8),
    pdf('dtriang', min=1, max=9, mode=3),
    pdf('dtriang', min=1, max=9, mode=3, trmin=2, trmax=8),
    pdf('dtriang', min=1, max=9, mode=9),
    pdf('norm', mean=5, sd=2),
    pdf('norm', mean=5, sd=2, trmin=0),
    pdf('norm', mean=5, sd=2, pmin=0.05, pmax=0.95),
    pdf('norm', mean=5, sd=0),
    pdf('norm', mean=-1e-3, sd=1e-4, trmax=-1e-3),
    pdf('logu', min=1e-3, max=1e2),
    pdf('logu', min=1e-3, max=1e2, trmax=10),
    pdf('logt', min=7e-12, max=5e-11, mode=1e-11),
    pdf('logt', min=7e-12, max=5e-11, mode=1e-11, pmin=0.05, pmax=0.95),
    pdf('logt', min=-1, max=10, mode=1),
    pdf('logt', min=0, max=10, mode=1),
    pdf('logdt', min=0.7, max=20, mode=3),
    pdf('logdt', min=0.7, max=20, mode=3, pmin=0.05, pmax=0.95),
    pdf('Logn4', gm=1e-3, gsd=3),
    pdf('Logn4', gm=1e-3, gsd=3, trmin=1e-4, trmax=1e-2),
    pdf('logn', mean=2, sd=1),
    pdf('logn', mean=2, sd=1, trmax=5),
    pdf('logn5', p1=0.05, x1=1, p2=0.95, x2=100),
    pdf('logn5', p1='0.05', x1=1, p2=0.95, x2=100),
    pdf('logn5', p1=0.95, x1=1, p2=0.05, x2=100),
    pdf('logn5', p1=0.5, x1=1, p2=0.5, x2=100),
    pdf('pg', values=[1, 2, 3, 4, 5]),
    pdf('pg', values=[1, 2, 3, 4, 5], pos=3),
    pdf('pg', values=[1, 2, 3, 4, 5], pos='2'),
    pdf('pg', values=[1, 2, 3, 4, 5], pos=-1),
    pdf('pg', values=[1, 2, 3, 4, 5], pos=1.5),
    pdf('pg', values=[1, 2, 3, 4, 5], inorder=False),
    pdf('pg', values=[1, None, 3, True], inorder=True),
    pdf('pg', values=[1, None, 3, False], inorder=False),
    pdf('pg', values=[]),
    pdf('logt', min=1, max=None, mode=2),
    {'kind': 'foo', 'params': {}},
    {'kind': 'constructor', 'params': {}},
    {},
    {'kind': 'unif', 'params': None},
    {'kind': 'unif', 'params': {'min': 1, 'max': 2}},
    {'kind': 'norm', 'params': {'mean': 0, 'sd': 1}, 'pmin': 0.999999999, 'pmax': 1},
    {'kind': 'unif', 'params': {'min': 1, 'max': 2}, 'pmin': '0.25', 'pmax': [0.75]},
]


def unit_fixtures() -> dict:
    from kompartment.stats import _normal
    from kompartment.stats.correlate import correlation_pairs, iman_conover
    from kompartment.stats.pdf import cdf_at, probability_cuts, quantile
    from kompartment.stats.sample import stream_for, uniforms, value_at_probability
    out: dict = {}
    seeds = [1, 0, -5, 4294967297, 12345.7, '17', None, 2 ** 40 + 3, -2 ** 33 - 1, 'x']
    names = ['Kd[I-129]', '', 'ö', 'Grå \U0001F600 emoji', 'correlation:x', 'Quake#occurrences#3', 'G', 7]
    streams = []
    for s in seeds:
        for n in names:
            g = stream_for(s, n)
            streams.append({'seed': s, 'name': n, 'state': g.state, 'draws': [hexf(g()) for _ in range(5)]})
    out['streams'] = streams
    cols = []
    for n in (0, 1, 2, 3, 10, 100):
        for latin in (True, False):
            cols.append({'n': n, 'latin': latin, 'seed': 3, 'name': f'col{n}',
                         'u': hexes(uniforms(n, stream_for(3, f'col{n}'), latin=latin))})
    out['uniforms'] = cols
    us = list(uniforms(64, stream_for(5, 'u'))) + [0.0, 1.0, 1e-15, 0.5, 0.02425, 0.97575, 1 - 1e-12, 0.25, 0.75]
    draws = []
    for spec in UNIT_SPECS:
        # A list's value is handed out as it is: None for a gap (NaN in Julia), a boolean as one.
        vals = [drawn(value_at_probability(spec, u, k % 11)) for k, u in enumerate(us)]
        entry = {'spec': spec, 'value': vals}
        try:
            entry['quantile'] = [hexf(quantile(spec, u)) for u in us]
            xs = [quantile(spec, u) for u in us[:20]] + [0.0, -1.0, 1.0, 2.0, 1e-3]
            entry['x'] = [hexf(x) for x in xs]
            entry['cdf'] = [hexf(cdf_at(spec, x)) for x in xs]
            c = probability_cuts(spec)
            entry['cuts'] = [hexf(c['lo']), hexf(c['hi']), bool(c['cut']), bool(c['reversed'])]
        except Exception as e:  # noqa: BLE001 - a spec the application refuses too
            entry['error'] = f'{type(e).__name__}'
        draws.append(entry)
    out['us'] = [hexf(u) for u in us]
    out['draws'] = draws
    zs = [-40.0, -8.0, -3.0, -1.0, -0.5, -0.46875, -0.3, -1e-20, 0.0, 1e-20, 0.2, 0.46875, 0.47, 1.0, 2.5, 6.0, 30.0]
    ps = [1e-300, 1e-12, 1e-5, 0.01, 0.02425, 0.024251, 0.3, 0.5, 0.7, 0.97575, 0.975751, 0.99, 1 - 1e-12, 0.0, 1.0, -1.0,
          2.0]
    out['normal'] = {'z': [hexf(z) for z in zs], 'phi': [hexf(_normal.phi(z)) for z in zs],
                     'erfc': [hexf(_normal.erfc(z)) for z in zs], 'erf': [hexf(_normal.erf(z)) for z in zs],
                     'p': [hexf(p) for p in ps],
                     'probit': [None if _normal.probit(p) is None else hexf(_normal.probit(p)) for p in ps],
                     'quantile': [hexf(_normal.normal_quantile(p)) for p in ps]}
    names_c = ['Kd[I-129]', 'Kd[Cs-135]', 'Kd[Tc-99]', 'r1', 'r2', 'r3', 's1', 'Kd']
    proj = {'simulation': {'correlations': model_correlations()['simulation']['correlations'] + [
        {'group': 'Kd', 'r': 0.2}, {'a': None, 'b': 'r1', 'r': 0.1}, {'r': 0.1}, {'a': 'r2', 'b': 'r3'},
        {'a': 'r2', 'b': 'r3', 'r': None}, 'not a correlation', {'group': '', 'r': 0.3}, {'group': 0, 'r': 0.3}]}}
    cp = correlation_pairs(proj, names_c)
    out['pairs'] = {'names': names_c, 'project': proj, 'pairs': [[p['a'], p['b'], hexf(p['r'])] for p in cp['pairs']],
                    'problems': cp['problems']}
    ic = []
    for label, n, k, pairs in (
            ('two', 50, 2, [(0, 1, 0.8)]),
            ('notpd', 30, 3, [(0, 1, 0.9), (1, 2, 0.9), (0, 2, -0.9)]),
            ('four', 7, 4, [(0, 3, -0.6), (1, 2, 0.4), (0, 1, 0.3)]),
            ('three', 3, 2, [(0, 1, 0.5)]),
            ('two_rows', 2, 2, [(0, 1, 0.5)]),
            ('wide', 200, 6, [(0, 1, 0.95), (2, 3, -0.95), (4, 5, 0.1), (1, 4, 0.5), (0, 5, -0.2)])):
        names_i = [f'v{j}' for j in range(k)]
        columns = [uniforms(n, stream_for(21, nm)) for nm in names_i]
        before = [hexes(c) for c in columns]
        res = iman_conover(columns, [{'a': a, 'b': b, 'r': r} for a, b, r in pairs], names_i, 21)
        ic.append({'label': label, 'n': n, 'names': names_i, 'pairs': [[a, b, r] for a, b, r in pairs],
                   'before': before, 'after': [hexes(c) for c in columns], 'moved': list(res['columns']),
                   'adjusted': hexf(res['adjusted'])})
    out['iman_conover'] = ic
    from kompartment.engine.probabilistic import estimate, hold_precision
    shapes = [(1, 1, 1), (40, 400, 1000), (2, 101, 1000), (330000, 101, 10), (1000, 1000, 135), (1000, 1000, 134),
              (3, 7, 11), (64, 1024, 2048), (500, 2000, 1000)]
    out['estimates'] = [{'shape': list(sh), 'double': estimate(*sh, 'double'), 'float32': estimate(*sh, 'float32'),
                         'hold': hold_precision(*sh)} for sh in shapes]
    return out


def main() -> None:
    out_dir = Path(sys.argv[1])
    wanted = set(sys.argv[2:])
    (out_dir / 'runs').mkdir(parents=True, exist_ok=True)
    if not wanted or 'units' in wanted:
        (out_dir / 'units.json').write_text(json.dumps(unit_fixtures()))
        print('units')
    for name, key, options in CASES:
        if wanted and name not in wanted:
            continue
        data = run_case(name, key, options, out_dir)
        (out_dir / 'runs' / (name + '.json')).write_text(json.dumps(data))
        if 'error' in data:
            print(f"{name}: {data['error']}")
            continue
        st = data['stats']
        print(f"{name}: {data['iterations']} runs, {len(data['outputs'])} series, {len(data['plan'])} inputs, "
              f"{st.get('failed')} failed, {data['python_seconds']:.1f} s")


if __name__ == '__main__':
    main()
