"""The Python engine behind the application's local server.

``serve.py`` in the application's folder serves the page, and can hand its
runs to an engine on the same machine instead of solving them in the browser:
this module is the Python one. The server starts it once and keeps it::

    python3 -m kompartment.service

and talks to it in lines of JSON, one message a line. In, on standard input::

    {"op": "job", "id": "j1", "kind": "run", "model": "<the model as JSON text>",
     "options": {...}, "out": "/path/to/j1.zip"}
    {"op": "cancel", "id": "j1"}

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

Jobs run one at a time, in the order they came. A cancel stops a run at its
next progress report; a probabilistic run stops at the next realisation to
finish, and the server ends the process if it has not stopped soon after.
"""

from __future__ import annotations

import json
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


def run_job(job: Dict[str, Any], say: Callable[..., None], stopped: Callable[[], bool]) -> None:
    """One job, said as it goes; the last thing said is ``done``, ``error`` or
    ``cancelled``."""
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
            write_dataset(res, job['out'], project=raw)
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
    cancelled = set()

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
            if msg.get('op') == 'cancel':
                cancelled.add(str(msg.get('id')))
            elif msg.get('op') == 'job':
                jobs.put(msg)
        jobs.put(None)

    threading.Thread(target=read, daemon=True).start()
    say(**_engine_detail())
    while True:
        job = jobs.get()
        if job is None:
            return
        job_id = str(job.get('id'))
        if job_id in cancelled:
            say(id=job_id, event='cancelled')
            continue
        run_job(job, say, lambda: job_id in cancelled)


if __name__ == '__main__':
    serve()
