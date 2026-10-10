"""Reference runs for the Julia engine's tests, from the Python engine.

For every model given (the bundled examples by default) this runs the model
with the Python package -- whole, not split -- and writes, as JSON with every
float as its hex text, the solver's counts, the output times and every
series the run reports, by label, with the descriptors.

    python3 tools/run_fixtures.py OUT_DIR [model.json ...]

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'
COUNTS = ('nsteps', 'nfailed', 'nfevals', 'npds', 'ndecomps', 'nsolves', 'events', 'restarts', 'negative', 'jumps',
          'points', 'solver', 'sparse')


def hexes(v):
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


def plain(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def fixture(path: Path) -> dict:
    import kompartment as kp
    model = kp.Model.load(path)
    out = {'name': path.name}
    try:
        res = model.run(split='off')
    except Exception as e:  # noqa: BLE001 - the error is the fixture
        out['error'] = f'{type(e).__name__}: {e}'
        return out
    out['stats'] = {k: plain(res.stats.get(k)) for k in COUNTS if k in res.stats}
    held = res.stats.get('held')
    if held is not None:
        out['stats']['held'] = [int(v) for v in held]
    out['t'] = hexes(res.t)
    outs = res.outputs()
    cols = res.series_many(outs)
    out['outputs'] = [{k: plain(o.get(k)) for k in ('label', 'block', 'kind', 'nuclide', 'index', 'dims', 'unit',
                                                    'source', 'offset', 'timeDependent') if k in o} for o in outs]
    out['series'] = [hexes(c) for c in cols]
    out['csv'] = res.to_csv()
    return out


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in sys.argv[2:]] or sorted(EXAMPLES.glob('*.json'))
    for path in paths:
        data = fixture(path)
        (out_dir / (path.stem + '.json')).write_text(json.dumps(data))
        st = data.get('stats') or {}
        print(path.name, data.get('error') or f"{st.get('solver')} {st.get('nsteps')} steps, {len(data['t'])} times")


if __name__ == '__main__':
    main()
