"""What a probabilistic run says: bands, summaries, and what drove the spread.

Ports of the analysis the application's simulation worker does on a sample
(``src/worker/sim-worker.js``): the bands and their spreads, one output at one
time as a distribution, a tornado's table, a sensitivity design's table and
its indices over time, and the *What drove it* table -- correlations, the
regression family, the first-order index, and the measures that read any
sample (EASI, Borgonovo's delta, mutual information, RSA, PAWN, discrepancy).

Every function takes a :class:`~kompartment.engine.probabilistic.ProbabilisticResults`.
A varied parameter is a series here too, one value per realisation, after the
kept ones (``with_inputs``), so a table can rank a parameter as well as an
output.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..stats.categories import categories_of, classify, include_mask, statistic_of
from ..stats.distribution import describe_sample, histogram, sorted_column
from ..stats.gsa import average_ranks, delta_moment, easi, gsa_main, gsa_table, mutual_information, normal_scores, rsa
from ..stats.salib import discrepancy_shares, pawn, rank_probabilities
from ..stats.sample import stream_for, uniforms
from ..stats.sensitivity import first_order_index, over_time, ranked, regression_measures
from .probabilistic import mean_of, median_spread, quantiles

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
TRANSLATIONS = ('none', 'rank', 'log')


def with_inputs(result: Any) -> Any:
    """The varied parameters, put back beside the kept series as one value per
    realisation (``withInputs``). Idempotent."""
    if getattr(result, 'flat', None) is not None:
        return result
    flat = [0] * len(result.outputs)
    drawn_from = [-1] * len(result.outputs)
    failed = bool(np.any(result.ran == 0))
    outputs = list(result.outputs)
    values = list(result.values)
    for item in result.inputs or []:
        drawn = np.array(result.samples[item['k']], dtype=float)
        if failed:
            drawn[result.ran == 0] = np.nan
        outputs.append(item['output'])
        values.append(drawn.reshape(-1, 1))
        flat.append(1)
        drawn_from.append(item['k'])
    result.outputs = outputs
    result.values = values
    result.flat = np.array(flat, dtype=np.uint8)
    result.drawn_from = np.array(drawn_from, dtype=np.int64)
    return result


def _flat_values(result: Any, k: int) -> np.ndarray:
    """Series ``k`` realisation-major and flat: ``[i * stride + j]``."""
    return np.asarray(result.values[k], dtype=np.float64).ravel()


def stride_of(result: Any, k: int) -> int:
    return 1 if getattr(result, 'flat', None) is not None and result.flat[k] else result.t.size


def time_in(result: Any, k: int, at: int) -> int:
    return 0 if getattr(result, 'flat', None) is not None and result.flat[k] else at


def spread(v: np.ndarray, times: int) -> np.ndarray:
    return v if v.size == times else np.full(times, v[0])


def percentiles_for(lst: Optional[Sequence[float]]) -> List[float]:
    want = {0.5}
    for p in lst if isinstance(lst, (list, tuple)) else QUANTILES:
        try:
            v = float(p)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and 0 < v < 1:
            want.add(v)
    return sorted(want)


def sd_of(values: np.ndarray, times: int, iterations: int, mean: np.ndarray,
          mask: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    V = values.reshape(iterations, times)
    out = np.zeros(times)
    n = np.zeros(times, dtype=np.int64)
    for i in range(iterations):
        if mask is not None and not mask[i]:
            continue
        row = V[i]
        ok = np.isfinite(row)
        d = np.where(ok, row - mean, 0.0)
        out += d * d
        n += ok
    with np.errstate(all='ignore'):
        sd = np.where(n > 1, np.sqrt(out / np.maximum(n - 1, 1)), np.nan)
    return {'sd': sd, 'n': n}


def bands(result: Any, percentiles: Optional[Sequence[float]] = None,
          mask: Optional[np.ndarray] = None) -> List[Dict[str, Any]]:
    """Per series: the quantiles, the mean, the standard deviation and the
    median's two intervals, over the realisations in ``mask``."""
    result = with_inputs(result)
    qs = percentiles_for(percentiles)
    out = []
    for k in range(len(result.values)):
        v = _flat_values(result, k)
        times = stride_of(result, k)
        q = quantiles(v, times, result.iterations, qs, mask)
        mean = mean_of(v, times, result.iterations, mask)
        band = {'q': [b['y'] for b in q], 'quantiles': qs, 'mean': mean,
                'sd': sd_of(v, times, result.iterations, mean, mask),
                'med': median_spread(v, times, result.iterations, 1.959964, mask)}
        if result.flat[k]:
            band['flat'] = True
        out.append(band)
    return out


def peak_time(values: np.ndarray, times: int, iterations: int, mask: Optional[np.ndarray] = None) -> int:
    """The output time where a series is largest on average."""
    V = values.reshape(iterations, times)
    best, most = 0, -math.inf
    for j in range(times):
        total, n = 0.0, 0
        for i in range(iterations):
            if mask is not None and not mask[i]:
                continue
            v = V[i, j]
            if not math.isfinite(v):
                continue
            total += v
            n += 1
        if not n:
            continue
        mean = total / n
        if mean > most:
            most, best = mean, j
    return best


def own_peaks(values: np.ndarray, times: int, iterations: int, mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Each realisation's own peak and the output time it first reaches it."""
    V = values.reshape(iterations, times)
    mx = np.full(iterations, np.nan)
    when = np.full(iterations, -1, dtype=np.int64)
    for i in range(iterations):
        if mask is not None and not mask[i]:
            continue
        best, at = -math.inf, -1
        for j in range(times):
            v = V[i, j]
            if v > best:
                best, at = v, j
        if at >= 0:
            mx[i], when[i] = best, at
    return {'max': mx, 'when': when}


def peak_times(t: np.ndarray, when: np.ndarray) -> Optional[Dict[str, Any]]:
    at = sorted(float(t[j]) for j in when if j >= 0)
    if not at:
        return None

    def q(p: float) -> float:
        return at[min(len(at) - 1, max(0, int(math.floor(p * (len(at) - 1) + 0.5))))]

    return {'median': q(0.5), 'low': q(0.05), 'high': q(0.95), 'n': len(at)}


def kept(mask: Optional[np.ndarray], iterations: int) -> int:
    return iterations if mask is None else int(np.count_nonzero(mask))


def chosen_inputs(asked: Optional[Sequence[int]], count: int) -> List[int]:
    if not isinstance(asked, (list, tuple)):
        return list(range(count))
    return sorted({c for c in asked if isinstance(c, int) and 0 <= c < count})


def _series_index(result: Any, label: Any) -> int:
    if isinstance(label, (int, np.integer)):
        return int(label)
    for k, o in enumerate(result.outputs):
        if o['label'] == label:
            return k
    raise KeyError(f"No series labelled '{label}'")


def categories_mask(result: Any, categories: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The realisations sorted into categories, and which of them are kept
    (``prob-categories``)."""
    result = with_inputs(result)
    cats = categories_of({'simulation': {'categories': list(categories)}})
    if not cats:
        return {'mask': None, 'member': None, 'counts': None, 'missing': None}
    run = {'outputs': result.outputs, 'values': [_flat_values(result, k) for k in range(len(result.values))],
           'iterations': result.iterations, 't': result.t, 'flat': result.flat}
    sorted_ = classify(cats, run)
    mask = include_mask(cats, sorted_['member'])
    return {'mask': mask, 'member': sorted_['member'], 'counts': sorted_['counts'], 'missing': sorted_['missing'],
            'kept': kept(mask, result.iterations)}


def summary(result: Any, label: Any, at: Any = None, mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """One output at one time as a distribution: the sorted column and its
    statistics. ``at`` is an output-time index, ``'peak'`` (where the mean
    peaks), ``'max'`` (each realisation's own peak) or None (the last time)."""
    result = with_inputs(result)
    k = _series_index(result, label)
    values = _flat_values(result, k)
    times = result.t.size
    stride = stride_of(result, k)
    peaks = None
    if at == 'max':
        found = own_peaks(values, stride, result.iterations, mask)
        s = sorted_column(found['max'], 1, result.iterations, 0)
        if stride > 1:
            peaks = peak_times(result.t, found['when'])
        where = None
    else:
        where = (peak_time(values, stride, result.iterations, mask) if at == 'peak'
                 else min(times - 1, max(0, int(at if at is not None else times - 1))))
        s = sorted_column(values, stride, result.iterations, time_in(result, k, where), mask)
    frm = int(result.drawn_from[k])
    return {'index': k, 'at': where, 'peaks': peaks, 'summary': describe_sample(s), 'column': np.asarray(s),
            'of': result.iterations, 'spec': result.plan[frm]['spec'] if frm >= 0 else None,
            'screened': mask is not None}


def hist(result: Any, labels: Sequence[Any], at: Any = None, bins: Any = None, scale: str = 'auto',
         mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Several outputs at one time, each as a histogram."""
    result = with_inputs(result)
    times = result.t.size
    idx = [_series_index(result, lab) for lab in labels]
    curve = next((k for k in idx if not result.flat[k]), None)
    if at == 'peak':
        where = times - 1 if curve is None else peak_time(_flat_values(result, curve), times, result.iterations, mask)
    else:
        where = min(times - 1, max(0, int(at if at is not None else times - 1)))
    items = []
    for k in idx:
        s = sorted_column(_flat_values(result, k), stride_of(result, k), result.iterations,
                          time_in(result, k, where), mask)
        items.append({'index': k, 'summary': describe_sample(s), 'histogram': histogram(s, bins, scale)})
    return {'at': where, 't': result.t, 'items': items, 'of': result.iterations}


def tornado_table(result: Any, label: Any, stat: str = 'max', at: Any = 0) -> Dict[str, Any]:
    """What each swung input did to one output (``tornadoTable``)."""
    result = with_inputs(result)
    k = min(len(result.values) - 1, max(0, _series_index(result, label)))
    values = _flat_values(result, k)
    times = result.t.size
    central = statistic_of(values, times, 0, stat, at)
    swung = (result.stats.get('tornado') or {}).get('swung') or []
    rows = []
    for s2, p in enumerate(swung):
        e = result.plan[p]
        low = statistic_of(values, times, 2 * s2 + 1, stat, at)
        high = statistic_of(values, times, 2 * s2 + 2, stat, at)
        rows.append({'k': p, 'name': e['name'], 'where': list((e.get('index') or {}).values()), 'low': low,
                     'high': high, 'lowInput': float(result.samples[p][2 * s2 + 1]),
                     'highInput': float(result.samples[p][2 * s2 + 2]),
                     'swing': abs(high - low) if math.isfinite(low) and math.isfinite(high) else math.nan})

    def key(r: Dict[str, Any]) -> float:
        return -1.0 if math.isnan(r['swing']) else r['swing']

    rows.sort(key=key, reverse=True)
    return {'index': k, 'stat': stat, 'at': at, 'central': central, 'rows': rows}


def gsa_answer(result: Any, label: Any, stat: str = 'max', at: Any = 0) -> Dict[str, Any]:
    """One sensitivity method's table for one output, and the leading inputs'
    indices over time (``gsaAnswer``)."""
    result = with_inputs(result)
    k = min(len(result.values) - 1, max(0, _series_index(result, label)))
    values = _flat_values(result, k)
    times = result.t.size
    n = result.iterations
    design = result.data['gsa_design']
    y = np.array([statistic_of(values, times, i, stat, at) for i in range(n)])
    table = gsa_table(design, y, next=stream_for(result.stats.get('seed', 1), '#gsa#bootstrap'))
    factors = (result.stats.get('gsa') or {}).get('factors') or []

    def name(f: int) -> Dict[str, Any]:
        fac = factors[f] if f < len(factors) else None
        members = (fac or {}).get('members') or []
        e = result.plan[members[0]] if members else None
        group = (fac or {}).get('group')
        if group:
            return {'name': group, 'where': [], 'members': [result.plan[m]['name'] for m in members]}
        return {'name': e['name'] if e else f'input {f + 1}', 'where': list(((e or {}).get('index') or {}).values())}

    rows = [{**r, **name(r['k'])} for r in table['rows']]
    lead = [r['k'] for r in rows if math.isfinite(r['values'].get(table['rank'], math.nan))][:6]
    curves = []
    if not table['failed'] and not table['flat'] and lead:
        V = values.reshape(n, times)
        series = [np.full(times, np.nan) for _ in lead]
        for j in range(times):
            yt = V[:, j]
            if not np.any(yt[1:] != yt[0]):
                continue
            main = gsa_main(design, yt)
            for s, f in enumerate(lead):
                series[s][j] = main[f]
        curves = [{'k': f, 'y': series[s]} for s, f in enumerate(lead)]
    pairs = None
    if table.get('pairs'):
        pairs = [{**p, 'a': name(p['a']), 'b': name(p['b'])} for p in table['pairs'][:20]]
    return {'index': k, 'stat': stat, 'at': at, 'method': table['method'], 'columns': table['columns'],
            'rank': table['rank'], 'rows': rows, 'pairs': pairs, 'failed': table['failed'], 'flat': table['flat'],
            'curves': curves}


def what_drove(result: Any, label: Any, at: Any = None, inputs: Optional[Sequence[int]] = None, most: int = 20,
               translate: str = 'none', family: Optional[str] = None,
               mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """The *What drove it* table for one output at one time (``sensitivity``).

    ``at``: an output-time index, ``'peak'`` or ``'max'`` (each realisation's
    own peak). ``family='distribution'`` adds the measures that read any sample.
    """
    result = with_inputs(result)
    k = _series_index(result, label)
    values = _flat_values(result, k)
    times = result.t.size
    stride = stride_of(result, k)
    own = at == 'max'
    if own:
        where = None
    elif at == 'peak':
        where = peak_time(values, stride, result.iterations, mask)
    else:
        where = min(times - 1, max(0, int(at if at is not None else times - 1)))
    read, across, a, peaks = values, stride, (0 if own else time_in(result, k, where)), None
    if own:
        found = own_peaks(values, stride, result.iterations, mask)
        read, across, a = found['max'], 1, 0
        if stride > 1:
            peaks = peak_times(result.t, found['when'])
    use = chosen_inputs(inputs, len(result.samples))
    pool = [result.samples[c] for c in use]
    rows = [{**row, 'k': use[row['k']]} for row in ranked(pool, read, across, result.iterations, a, most=most,
                                                         mask=mask)]
    pos_of = {c: j for j, c in enumerate(use)}
    curves = [{'k': row['k'], 'y': spread(np.asarray(over_time(result.samples[row['k']], values, stride,
                                                                result.iterations, mask=mask)), times)}
              for row in rows[:6]]
    measures = None
    tr = translate if translate in TRANSLATIONS else 'none'
    if pool and len(pool) <= 3000:
        y = np.array([read[i * across + a] for i in range(result.iterations)])
        reg = regression_measures(pool, y, translate=tr, mask=mask)
        measures = {'ok': reg['ok'], 'used': reg['used'], 'r2': reg['r2'], 'translate': tr,
                    'dropped': reg.get('dropped') or 0,
                    'src': [reg['src'][pos_of[row['k']]] for row in rows],
                    'b': [reg['b'][pos_of[row['k']]] for row in rows],
                    'pcc': [reg['pcc'][pos_of[row['k']]] for row in rows],
                    's1': [first_order_index(result.samples[row['k']], y, mask=mask) for row in rows]}
    distribution = (distribution_measures(result, read, across, a, rows, mask, translate=tr, use=use)
                    if family == 'distribution' else None)
    return {'index': k, 'at': where, 'peaks': peaks, 't': result.t,
            'rows': [{**row, 'name': result.plan[row['k']]['name'],
                      'where': list((result.plan[row['k']].get('index') or {}).values())} for row in rows],
            'curves': curves, 'measures': measures, 'distribution': distribution, 'kept': kept(mask, result.iterations),
            'sampled': [{'k': c, 'name': e['name'], 'where': list((e.get('index') or {}).values())}
                        for c, e in enumerate(result.plan)],
            'using': len(use)}


def distribution_measures(result: Any, values: np.ndarray, times: int, at: int, rows: List[Dict[str, Any]],
                          mask: Optional[np.ndarray], translate: str = 'none',
                          use: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """EASI, delta, mutual information, RSA, PAWN and discrepancy, for the listed inputs."""
    import numpy as _np
    chosen_rows = [i for i in range(result.iterations) if (mask is None or mask[i])
                   and math.isfinite(values[i * times + at])]
    dropped = 0
    if translate == 'log':
        before = len(chosen_rows)
        chosen_rows = [i for i in chosen_rows if values[i * times + at] > 0]
        dropped = before - len(chosen_rows)
    raw = _np.array([values[i * times + at] for i in chosen_rows], dtype=float)
    if translate == 'log':
        from .. import jsmath
        y = _np.array([jsmath.log(v) for v in raw])
    elif translate == 'rank':
        y = _np.asarray(average_ranks(raw), dtype=float)
    else:
        y = raw
    n = y.size
    if n < 20:
        return {'ok': False, 'used': n, 'dropped': dropped, 'translate': translate, 'rows': []}
    if not _np.any(y[1:] != y[0]):
        return {'ok': False, 'used': n, 'flat': True, 'rows': []}
    seed = result.stats.get('seed', 1)
    dummies = [uniforms(n, stream_for(seed, f'#rsa#dummy#{d}')) for d in range(10)]
    columns = [_np.array([result.samples[row['k']][i] for i in chosen_rows], dtype=float) for row in rows]
    split = rsa(columns, y, dummies=dummies)
    scores = normal_scores(y)
    y_ranks = average_ranks(y)

    def varying(col: _np.ndarray) -> bool:
        return bool(_np.any(col[1:] != col[0]))

    chosen = list(use) if use is not None else list(range(len(result.samples)))
    every = len(chosen) * n * n <= 4e8
    if every:
        pool = [{'k': k, 'x': _np.array([result.samples[k][i] for i in chosen_rows], dtype=float)} for k in chosen]
    else:
        pool = [{'k': row['k'], 'x': columns[j]} for j, row in enumerate(rows)]
    spread_ = [c for c in pool if varying(c['x'])]
    shares = (discrepancy_shares([rank_probabilities(c['x']) for c in spread_], rank_probabilities(y), 'WD')['shares']
              if spread_ else [])
    share_of = {c['k']: shares[j] for j, c in enumerate(spread_)}
    out: List[Optional[Dict[str, Any]]] = []
    for j, row in enumerate(rows):
        x = columns[j]
        if not varying(x):
            out.append(None)
            continue
        name = f"{result.plan[row['k']]['name']}#{row['k']}" if row['k'] < len(result.plan) else str(row['k'])
        d = delta_moment(x, scores, boots=100, next=stream_for(seed, f'{name}#delta'))
        m = mutual_information(average_ranks(x), y_ranks, boots=100, next=stream_for(seed, f'{name}#mi'))
        pw = pawn(x, y, slides=10)
        out.append({'easi': easi(x, y)['s1c'], 'delta': d['adjusted'], 'deltaLow': d['low'], 'deltaHigh': d['high'],
                    'mi': m['mi'], 'miBound': m['bound'], 'miS': m['s'], 'ks': split['scores'][j],
                    'pawn': pw['median'], 'pawnMax': pw['maximum'], 'discrepancy': share_of.get(row['k'], math.nan)})
    s = _np.sort(raw)
    if translate == 'log':
        from .. import jsmath
        threshold = jsmath.exp(split['threshold'])
    elif translate == 'rank':
        threshold = (s[(n - 1) >> 1] + s[n >> 1]) / 2
    else:
        threshold = split['threshold']
    return {'ok': True, 'used': n, 'rows': out, 'translate': translate, 'dropped': dropped,
            'splitAt': 'geometric mean' if translate == 'log' else ('median' if translate == 'rank' else 'mean'),
            'threshold': threshold, 'behavioural': split['behavioural'], 'ksDummyMean': split['dummyMean'],
            'ksDummySd': split['dummySd'], 'discrepancyOver': 'all' if every else 'listed'}
