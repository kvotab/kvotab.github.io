"""Reference numbers for the Julia engine's tests, from the Python engine.

For every model given (the bundled examples by default) this builds the model
with the Python package's engine and writes, as JSON with every float as its
hex text (``float.hex``), what the Julia engine must reproduce bit for bit:
the layout (states, algebraic slots, parameters), the parameter vector, the
algebraic slots that never change, the initial state, and the derivative and
every algebraic slot at the start and at a few random states and times.

    python3 tools/engine_fixtures.py OUT_DIR [model.json ...]

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent.parent / 'examples'


def hexes(v):
    return [float(x).hex() for x in np.asarray(v, dtype=float).ravel()]


def fixture(path: Path) -> dict:
    import kompartment as kp
    from kompartment.engine import Project, build_system
    model = kp.Model.load(path)
    out = {'name': path.name}
    try:
        project = Project(model.to_dict())
        system = build_system(project)
    except Exception as e:  # noqa: BLE001 - the error is the fixture
        out['error'] = f'{type(e).__name__}: {e}'
        return out
    b = system.builder
    out['nstate'] = system.nstate
    out['nalg'] = system.nalg
    out['nparam'] = system.nparam
    out['states'] = [{'name': s.name, 'kind': s.kind, 'base': s.base, 'width': s.width, 'dims': list(s.dims or [])}
                     for s in b.states]
    out['algebraic'] = [{'name': a.name, 'kind': a.kind, 'base': a.base, 'width': a.width, 'cls': int(a.cls)}
                        for a in b.algebraic]
    out['P'] = hexes(system.P[:max(1, system.nparam)])
    X0 = np.array(system.X, dtype=float)
    out['X_invariant'] = hexes(X0)
    with np.errstate(all='ignore'):
        y0 = system.initial_state()
    out['y0'] = hexes(y0)
    out['grid'] = hexes(project.time_grid())
    rng = np.random.default_rng(12345)
    probes = []
    t0, t1 = system.start_time, system.end_time
    states = [y0]
    for _ in range(4):
        scale = np.where(np.abs(y0) > 0, np.abs(y0), 1.0)
        states.append(y0 + scale * rng.uniform(-0.5, 1.5, size=y0.size))
    times = [t0, t0 + 0.37 * (t1 - t0), t0 + 0.81 * (t1 - t0), t1, t0 + 1e-3 * (t1 - t0)]
    for y, t in zip(states, times):
        with np.errstate(all='ignore'):
            dy = system.dydt(t, y)
            X = np.array(system.evaluate_algebraic(t, y), dtype=float)
        probes.append({'t': float(t).hex(), 'y': hexes(y), 'dydt': hexes(dy), 'X': hexes(X)})
    out['probes'] = probes
    out['derivative_blocks'] = sorted(b.derivative_blocks) if b.derivative_blocks is not None else None
    return out


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in sys.argv[2:]] or sorted(EXAMPLES.glob('*.json'))
    for path in paths:
        data = fixture(path)
        (out_dir / (path.stem + '.json')).write_text(json.dumps(data))
        print(path.name, data.get('error') or f"{data['nstate']} states")


if __name__ == '__main__':
    main()
