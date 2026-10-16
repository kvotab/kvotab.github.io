"""The Python engine behind the application's local server.

``serve.py`` in the application's folder serves the page, and can hand its
runs to an engine on the same machine instead of solving them in the browser:
this module is the Python one. The server starts it once and keeps it::

    python3 -m kompartment.service

and talks to it in lines of JSON, one message a line. In, on standard input::

    {"op": "job", "id": "j1", "kind": "run", "model": "<the model as JSON text>",
     "options": {...}, "out": "/path/to/j1.zip"}
    {"op": "cancel", "id": "j1"}
    {"op": "series", "id": "q1", "run": "j1", "labels": ["Soil [Cs-137]", ...], "out": "/path/to/q1.f64"}
    {"op": "archive", "id": "q2", "run": "j1", "out": "/path/to/q2.zip"}
    {"op": "forget", "id": "q3", "run": "j1"}

Out, on standard output -- the protocol's own, and nothing else: anything the
engine prints goes to standard error::

    {"event": "ready", "engine": "python", "version": "...", ...}
    {"id": "j1", "event": "stage", "stage": "building" | "solving" | "writing"}
    {"id": "j1", "event": "progress", "fraction": 0.4, "at": 1200.0}
    {"id": "j1", "event": "progress", "done": 12, "total": 100}
    {"id": "j1", "event": "done", "out": "/path/to/j1.zip"}
    {"id": "j1", "event": "error", "name": "...", "message": "...", "block": null, "hint": null}
    {"id": "j1", "event": "cancelled"}

A ``run`` job writes the model and its run as the archive *Save with results*
writes (:func:`kompartment.io.dataset.write_dataset`); a ``probabilistic`` one
writes the model and the sample (:func:`kompartment.io.dataset.write_sample_archive`).
The page reads either the way it reads a file somebody opened.

A ``replay`` job runs one realisation of a probabilistic run (``index``, from
0, with the run's ``seed``, ``iterations``, ``latin``, ``varied`` and ``tornado``)
as an ordinary run, written as a ``run`` job's is, with ``replayed`` in its
meta: which realisation, of how many, and what each input was.

A ``calibrate`` job searches for the values that meet its ``targets``
(:func:`kompartment.engine.calibrate.calibrate`, with ``variables``, ``method``,
``maxEvals`` and ``seed``), saying each step's best as a progress ``detail``; a
``local-sensitivity`` one integrates dy/dp for its ``parameters``
(:func:`kompartment.engine.localsens.run_sensitivity`). Each writes its answer
as JSON: the calibration's result, or the times, the parameters, the run's
statistics and every state the page shows with its derivatives.

A ``probabilistic`` job with ``tornado`` or ``gsa`` among its options runs that
design in place of a sample: every input swung alone, or a sensitivity
design's points (:func:`kompartment.engine.probabilistic.run_probabilistic`).

A ``run`` job with ``"keep": true`` among its options is kept here instead, and
its archive leaves the states out (``onEngine`` in its meta, with the run's
mass-balance audit and ``page``, what the page reads of a run besides its series,
so that it need not build the model): the page asks for the series it shows as it shows them --
``series``, the labels' values at the run's times, one series after another as
little-endian doubles -- and for the whole run only when it needs it, to save it
or to work an edit out over its states (``archive``). ``forget`` lets it go.
These are answered beside the jobs, in the order they came, so that a page
reading one run is not kept waiting by the next one solving; each ends with
``done`` or ``error`` under its own id.

Jobs run one at a time, in the order they came -- ``ready`` says so
(``concurrent``: 1), and the server sends one at a time. A cancel stops a run at
its next progress report; a probabilistic run stops at the next realisation to
finish, and the server ends the process if it has not stopped soon after.
"""

from __future__ import annotations

import json
import math
import os
import queue
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, TextIO

#: Progress is said at most this often: the page polls, and a line per step
#: of a fast model would be most of the work.
PROGRESS_EVERY = 0.1


class _Stopped(Exception):
    """A run the page has stopped -- raised out of a progress report."""


def _protocol_stream() -> TextIO:
    """Standard output for the protocol alone. What anything else writes to
    file descriptor 1 -- a library's print, a warning -- goes to standard
    error, where the server shows it, rather than into the middle of a line."""
    out = os.fdopen(os.dup(1), 'w', encoding='utf-8', buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def _engine_detail() -> Dict[str, Any]:
    from . import __version__
    detail: Dict[str, Any] = {
        'event': 'ready', 'engine': 'python', 'version': __version__,
        'python': sys.version.split()[0], 'cores': os.cpu_count() or 1,
        # Jobs at once: one, since a run holds the interpreter while it solves.
        'concurrent': 1,
    }
    try:
        import numba  # noqa: F401
        detail['numba'] = numba.__version__
    except Exception:
        detail['numba'] = None
    return detail


def _error_event(job_id: str, e: BaseException) -> Dict[str, Any]:
    return {
        'id': job_id, 'event': 'error', 'name': type(e).__name__, 'message': str(e) or type(e).__name__,
        'block': getattr(e, 'block_name', None), 'hint': getattr(e, 'hint', None),
    }


def run_job(job: Dict[str, Any], say: Callable[..., None], stopped: Callable[[], bool],
            kept: Optional[Dict[str, Any]] = None) -> None:
    """One job, said as it goes; the last thing said is ``done``, ``error`` or
    ``cancelled``. A run asked to be kept goes into ``kept`` under its id, with
    the model it was made from."""
    job_id = str(job.get('id'))
    kind = job.get('kind')
    options = job.get('options') or {}
    started = time.perf_counter()
    last = [0.0]

    def throttled(**fields: Any) -> None:
        now = time.perf_counter()
        if now - last[0] >= PROGRESS_EVERY:
            last[0] = now
            say(id=job_id, event='progress', **fields)

    try:
        raw = json.loads(job['model']) if isinstance(job.get('model'), str) else job.get('model')
        if kind == 'run':
            from .engine.builder import build_system
            from .engine.project import Project
            from .engine.runner import run
            from .io.dataset import write_dataset
            say(id=job_id, event='stage', stage='building')
            project = Project(raw)
            built = time.perf_counter()
            system = build_system(project)
            build_ms = (time.perf_counter() - built) * 1000

            def progress(fraction: float, at: float) -> None:
                throttled(fraction=float(fraction), at=float(at))

            say(id=job_id, event='stage', stage='solving')
            res = run(project, system=system, on_progress=progress, signal=stopped)
            if stopped():
                raise _Stopped()
            res.timing = {**(res.timing or {}), 'build_ms': build_ms}
            say(id=job_id, event='stage', stage='writing')
            _write_run(res, raw, job, options, kept)
        elif kind == 'replay':
            from .engine.probabilistic import run_realization
            say(id=job_id, event='stage', stage='building')
            design = {k: options[k] for k in ('seed', 'iterations', 'latin', 'varied', 'tornado')
                      if options.get(k) is not None}
            say(id=job_id, event='stage', stage='solving')
            r = run_realization(raw, int(options.get('index') or 0), **design)
            say(id=job_id, event='stage', stage='writing')
            _write_run(r['results'], raw, job, options, kept, replayed={
                'index': int(r['index']), 'iterations': int(r['iterations']),
                'values': [{'name': v['name'], 'value': float(v['value']), 'held': bool(v['held'])}
                           for v in r['values']]})
        elif kind == 'calibrate':
            from .engine.calibrate import calibrate
            say(id=job_id, event='stage', stage='solving')

            def step(p: Dict[str, Any]) -> None:
                # As JSON carries it to the page: a misfit that is not a number is null.
                throttled(detail=_plain({k: p.get(k) for k in ('evals', 'fx', 'best', 'values')}))

            result = calibrate(raw, targets=options.get('targets'), variables=options.get('variables'),
                               method=options.get('method'), max_evals=options.get('maxEvals'),
                               seed=options.get('seed'), on_progress=step, signal=stopped)
            if stopped():
                raise _Stopped()
            _write_json(job['out'], result)
        elif kind == 'local-sensitivity':
            from .engine.localsens import run_sensitivity
            say(id=job_id, event='stage', stage='solving')

            def moved(fraction: float, at: float) -> None:
                throttled(fraction=float(fraction), at=float(at))

            r = run_sensitivity(raw, options.get('parameters'), on_progress=moved, signal=stopped)
            if stopped():
                raise _Stopped()
            say(id=job_id, event='stage', stage='writing')
            # Every state the page shows, by its name, with its derivatives.
            _write_json(job['out'], {
                't': r['t'], 'chosen': r['chosen'], 'stats': r['stats'],
                'states': [{'name': s['label'], 'y': r['y'][s['offset']],
                            'sens': [block[s['offset']] for block in r['sens']]}
                           for s in r['series'] if not s.get('hidden')],
            })
        elif kind == 'probabilistic':
            from .engine.probabilistic import run_probabilistic
            from .io.dataset import write_sample_archive
            say(id=job_id, event='stage', stage='building')

            def tick(done: int, total: int) -> None:
                if stopped():
                    raise _Stopped()
                throttled(done=int(done), total=int(total))

            blocks = options.get('blocks')
            prob = run_probabilistic(
                raw,
                iterations=int(options.get('iterations', 100)),
                seed=int(options.get('seed', 1)),
                latin=options.get('latin', True) is not False,
                varied=options.get('varied'),
                keep=list(blocks) if blocks else None,
                workers=max(1, int(options.get('workers') or 1)),
                on_progress=tick,
                large=options.get('large') is True,
                # A tornado, or a sensitivity design, in place of a sample.
                tornado=options.get('tornado') or None,
                gsa=options.get('gsa') or None,
            )
            say(id=job_id, event='stage', stage='writing')
            write_sample_archive(prob, job['out'], project=raw)
        else:
            raise ValueError(f"'{kind}' is not a kind of job this engine runs")
    except _Stopped:
        say(id=job_id, event='cancelled')
        return
    except Exception as e:  # noqa: BLE001 - every failure is the page's to show
        if stopped() or getattr(e, 'code', None) == 'aborted':
            say(id=job_id, event='cancelled')
            return
        say(**_error_event(job_id, e))
        return
    say(id=job_id, event='done', out=job['out'], ms=round((time.perf_counter() - started) * 1000))


def _plain(v: Any) -> Any:
    """A value as JSON holds it: arrays as lists, and a number that is not finite
    as null, as the page's JSON.stringify writes one."""
    import numpy as np
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return [_plain(x) for x in v.tolist()]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v) if math.isfinite(v) else None
    return v


def _write_json(path: str, value: Any) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(_plain(value), f, allow_nan=False)


def _page(res: Any) -> Dict[str, Any]:
    """What the page reads of a run besides its series (the worker's ``donePayload``):
    the outputs as it lists them, each parameter's one value with it, the nuclides,
    the size of the state vector, how df/dy was had and what the zero floor held --
    so that it holds a run the engine holds without building the model itself."""
    from .engine.runlog import jacobian_of
    outputs = []
    for o in res.outputs():
        d = {'kind': o.get('kind'), 'block': o.get('block'), 'nuclide': o.get('nuclide'), 'dims': o.get('dims') or [],
             'index': o.get('index'), 'label': o['label'], 'unit': o.get('unit'), 'constant': res.constant_of(o)}
        if o.get('timeDependent') is False:
            d['timeDependent'] = False
        outputs.append(d)
    return _plain({'outputs': outputs, 'nuclides': list(res.nuclides), 'stateCount': res.system.layout.nstate,
                   'jacobian': jacobian_of(res), 'heldAtZero': res.held_at_zero()})


def _write_run(res: Any, raw: Any, job: Dict[str, Any], options: Dict[str, Any], kept: Optional[Dict[str, Any]],
               replayed: Optional[Dict[str, Any]] = None) -> None:
    """A run's archive -- without its states, and the run kept, when the page asked
    for that -- with which realisation it replays, if it replays one."""
    from .io.dataset import write_dataset
    extra = {'replayed': replayed} if replayed is not None else {}
    if options.get('keep') is True and kept is not None:
        write_dataset(res, job['out'], project=raw, states=False,
                      extra={**extra, 'massBalance': _plain(res.mass_balance()), 'page': _page(res)})
        kept[str(job.get('id'))] = {'results': res, 'model': raw, 'by_label': None}
    else:
        write_dataset(res, job['out'], project=raw, extra=extra or None)


def answer_query(query: Dict[str, Any], kept: Dict[str, Any], say: Callable[..., None]) -> None:
    """A question about a kept run, answered with ``done`` or ``error`` under the
    question's own id."""
    query_id = str(query.get('id'))
    op = query.get('op')
    run_id = str(query.get('run'))
    try:
        if op == 'forget':
            kept.pop(run_id, None)
            say(id=query_id, event='done')
            return
        held = kept.get(run_id)
        if held is None:
            raise LookupError('This engine no longer holds that run: it may have been restarted since, '
                              'or the run let go of. Run it again.')
        res, raw = held['results'], held['model']
        if op == 'series':
            import numpy as np
            labels = [str(x) for x in (query.get('labels') or [])]
            by_label = held['by_label']
            if by_label is None:
                by_label = held['by_label'] = {o['label']: o for o in res.outputs()}
            missing = [x for x in labels if x not in by_label]
            if missing:
                raise LookupError(f"The engine's run has no series called {missing[0]!r}"
                                  + (f' (nor {len(missing) - 1} more)' if len(missing) > 1 else '') + '.')
            columns = res.series_many([by_label[x] for x in labels]) if labels else []
            data = (np.concatenate([np.asarray(c, dtype='<f8').reshape(-1) for c in columns])
                    if columns else np.zeros(0, dtype='<f8'))
            with open(query['out'], 'wb') as f:
                f.write(data.astype('<f8').tobytes())
        elif op == 'archive':
            from .io.dataset import write_dataset
            write_dataset(res, query['out'], project=raw)
        else:
            raise ValueError(f"'{op}' is not something this engine is asked")
    except Exception as e:  # noqa: BLE001 - the page's to show
        say(**_error_event(query_id, e))
        return
    say(id=query_id, event='done', out=query.get('out'))


def serve(stdin: Optional[TextIO] = None, stdout: Optional[TextIO] = None) -> None:
    """Reads jobs until standard input closes. See the module's notes."""
    out = stdout if stdout is not None else _protocol_stream()
    source = stdin if stdin is not None else sys.stdin
    lock = threading.Lock()

    def say(**event: Any) -> None:
        with lock:
            out.write(json.dumps(event) + '\n')
            out.flush()

    jobs: 'queue.Queue[Optional[Dict[str, Any]]]' = queue.Queue()
    queries: 'queue.Queue[Optional[Dict[str, Any]]]' = queue.Queue()
    cancelled = set()
    # The runs kept for their pages to ask about, by job id: the results, the
    # model they were made from, and their series by label once asked for.
    kept: Dict[str, Any] = {}

    def read() -> None:
        # On a thread of its own, so a cancel is heard while a job runs.
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            op = msg.get('op')
            if op == 'cancel':
                cancelled.add(str(msg.get('id')))
            elif op == 'job':
                jobs.put(msg)
            elif op in ('series', 'archive', 'forget'):
                queries.put(msg)
        jobs.put(None)
        queries.put(None)

    def answer() -> None:
        # Beside the jobs: a page reading one run while the next one solves.
        while True:
            query = queries.get()
            if query is None:
                return
            answer_query(query, kept, say)

    threading.Thread(target=read, daemon=True).start()
    answering = threading.Thread(target=answer, daemon=True)
    answering.start()
    say(**_engine_detail())
    while True:
        job = jobs.get()
        if job is None:
            # What was asked before standard input closed is answered first.
            answering.join()
            return
        job_id = str(job.get('id'))
        if job_id in cancelled:
            say(id=job_id, event='cancelled')
            continue
        run_job(job, say, lambda: job_id in cancelled, kept)


if __name__ == '__main__':
    serve()
