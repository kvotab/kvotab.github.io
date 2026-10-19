"""The engine behind the application's local server, and the archives it hands the page.

``serve.py`` hands a run to this package's engine (``kompartment.service``)
and gives the page back what it wrote: the archive *Save with results* writes,
or the model with a probabilistic run's sample. These hold the service to its
protocol, the sample to the layout the page reads (read here by the page's own
code), and the server to answering only the page it served.
"""

import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from helpers import APP, EXAMPLES, HAVE_APP, NODE, SRC

from kompartment.engine.probabilistic import run_probabilistic
from kompartment.engine.runner import run
from kompartment.io.dataset import sample_archive, sample_entries
from kompartment.service import serve


def _job(job_id, kind, model, out, **options):
    return json.dumps({'op': 'job', 'id': job_id, 'kind': kind, 'model': model, 'options': options, 'out': out})


class Protocol(unittest.TestCase):
    def test_jobs_in_and_what_became_of_each_out(self):
        four = (EXAMPLES / 'four-compartment.json').read_text()
        bio = (EXAMPLES / 'biosphere.json').read_text()
        with tempfile.TemporaryDirectory() as d:
            lines = [
                # Stopped before it was started: it says so, and is not run.
                json.dumps({'op': 'cancel', 'id': 'c1'}),
                _job('r1', 'run', four, f'{d}/r1.zip'),
                _job('p1', 'probabilistic', bio, f'{d}/p1.zip', iterations=10, seed=4),
                _job('c1', 'run', four, f'{d}/c1.zip'),
                _job('x1', 'draw', four, f'{d}/x1.zip'),
            ]
            out = io.StringIO()
            serve(stdin=io.StringIO('\n'.join(lines) + '\n'), stdout=out)
            events = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(events[0]['event'], 'ready')
            self.assertEqual(events[0]['engine'], 'python')
            ends = {e['id']: e['event'] for e in events if e.get('event') in ('done', 'error', 'cancelled')}
            self.assertEqual(ends, {'r1': 'done', 'p1': 'done', 'c1': 'cancelled', 'x1': 'error'})
            # A run is the archive Save with results writes; a sample the model and results/sample/.
            with zipfile.ZipFile(f'{d}/r1.zip') as z:
                self.assertIn('results/meta.json', z.namelist())
                log = json.loads(z.read('results/meta.json'))['log']
                self.assertTrue(any('Python' in line for line in log[:2]), log[:2])
            with zipfile.ZipFile(f'{d}/p1.zip') as z:
                names = set(z.namelist())
            self.assertTrue({'results/sample/meta.json', 'results/sample/t.f64', 'results/sample/series.f64',
                             'results/sample/draws.f64', 'results/sample/ran.u8'} <= names, names)
            self.assertFalse(os.path.exists(f'{d}/c1.zip'))
            stages = [e['stage'] for e in events if e.get('id') == 'r1' and e.get('event') == 'stage']
            self.assertEqual(stages, ['building', 'solving', 'writing'])
            problem = next(e for e in events if e.get('id') == 'x1' and e.get('event') == 'error')
            self.assertIn("'draw' is not a kind of job", problem['message'])


class _Said(io.StringIO):
    """Standard output that says when a job has ended."""

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id
        self.ended = threading.Event()

    def write(self, s: str) -> int:
        for line in s.splitlines():
            if line.strip():
                e = json.loads(line)
                if e.get('id') == self.job_id and e.get('event') in ('done', 'error', 'cancelled'):
                    self.ended.set()
        return super().write(s)


class Kept(unittest.TestCase):
    def test_a_kept_run_is_sent_without_its_states_and_answers_for_its_series(self):
        four = (EXAMPLES / 'four-compartment.json').read_text()
        made = run(json.loads(four))
        labels = [o['label'] for o in made.outputs()]
        with tempfile.TemporaryDirectory() as d:
            out = _Said('r1')

            def lines():
                yield _job('r1', 'run', four, f'{d}/r1.zip', keep=True)
                out.ended.wait(120)
                # Asked about once it is done, as the server asks.
                for q in ({'op': 'series', 'id': 'q1', 'run': 'r1', 'labels': labels, 'out': f'{d}/q1.f64'},
                          {'op': 'series', 'id': 'q2', 'run': 'r1', 'labels': ['Nowhere [Xx-0]'], 'out': f'{d}/q2'},
                          {'op': 'archive', 'id': 'q3', 'run': 'r1', 'out': f'{d}/q3.zip'},
                          {'op': 'forget', 'id': 'q4', 'run': 'r1'},
                          {'op': 'series', 'id': 'q5', 'run': 'r1', 'labels': labels, 'out': f'{d}/q5.f64'}):
                    yield json.dumps(q)

            serve(stdin=lines(), stdout=out)
            ends = {e['id']: e for e in (json.loads(x) for x in out.getvalue().splitlines()) if 'id' in e
                    and e.get('event') in ('done', 'error')}
            self.assertEqual({k: e['event'] for k, e in ends.items()},
                             {'r1': 'done', 'q1': 'done', 'q2': 'error', 'q3': 'done', 'q4': 'done', 'q5': 'error'})
            # Without its states, saying so, with the run's audit.
            with zipfile.ZipFile(f'{d}/r1.zip') as z:
                names = set(z.namelist())
                meta = json.loads(z.read('results/meta.json'))
            self.assertNotIn('results/y.f64', names)
            self.assertTrue(meta['onEngine'])
            self.assertIn('massBalance', meta)
            # What the page reads of the run besides its series.
            page = meta['page']
            self.assertEqual([o['label'] for o in page['outputs']], labels)
            self.assertEqual((page['stateCount'], page['nuclides']), (len(made.y[0]), list(made.nuclides)))
            self.assertTrue(set(page) >= {'jacobian', 'heldAtZero'})
            self.assertEqual((meta['times'], meta['states']), (len(made.t), len(made.y[0])))
            # Every series, by label, as a run here works them out.
            got = np.fromfile(f'{d}/q1.f64', '<f8').reshape(len(labels), -1)
            want = np.array(made.series_many(made.outputs()))
            self.assertTrue(np.array_equal(got.view(np.int64), want.view(np.int64)))
            self.assertIn("no series called 'Nowhere [Xx-0]'", ends['q2']['message'])
            # The whole run, states and all, as Save with results writes it.
            with zipfile.ZipFile(f'{d}/q3.zip') as z:
                self.assertIn('results/y.f64', z.namelist())
            # Let go of, and then said to be gone.
            self.assertIn('no longer holds that run', ends['q5']['message'])


class KeptSample(unittest.TestCase):
    def test_a_kept_sample_is_sent_without_its_series_and_answers_for_them(self):
        from kompartment.engine.analysis import bands, with_inputs
        bio = (EXAMPLES / 'biosphere.json').read_text()
        prob = with_inputs(run_probabilistic(json.loads(bio), iterations=10, seed=4))
        n, times, count = prob.iterations, prob.t.size, len(prob.values)
        kept = [k for k in range(count) if not prob.flat[k]]
        varied = [k for k in range(count) if prob.flat[k]]
        mask = [1, 1, 0, 1, 0, 1, 1, 1, 0, 1]
        with tempfile.TemporaryDirectory() as d:
            out = _Said('p1')

            def lines():
                yield _job('p1', 'probabilistic', bio, f'{d}/p1.zip', iterations=10, seed=4, keep=True)
                out.ended.wait(300)
                for q in ({'op': 'bands', 'id': 'q1', 'run': 'p1', 'percentiles': [0.05, 0.5, 0.95], 'mask': None,
                           'out': f'{d}/q1'},
                          {'op': 'bands', 'id': 'q2', 'run': 'p1', 'percentiles': [0.25, 0.75], 'mask': mask,
                           'out': f'{d}/q2'},
                          {'op': 'realisations', 'id': 'q3', 'run': 'p1', 'series': [kept[1], varied[0]],
                           'out': f'{d}/q3'},
                          {'op': 'column', 'id': 'q4', 'run': 'p1', 'series': [kept[0], varied[0]], 'at': 7,
                           'out': f'{d}/q4'},
                          {'op': 'realisation', 'id': 'q5', 'run': 'p1', 'series': [kept[2], varied[1]], 'index': 3,
                           'out': f'{d}/q5'},
                          {'op': 'column', 'id': 'q6', 'run': 'p1', 'series': [count], 'at': 0, 'out': f'{d}/q6'},
                          {'op': 'bands', 'id': 'q7', 'run': 'p1', 'percentiles': [0.5], 'mask': [1, 0],
                           'out': f'{d}/q7'},
                          {'op': 'series', 'id': 'q8', 'run': 'p1', 'labels': ['A'], 'out': f'{d}/q8'},
                          {'op': 'archive', 'id': 'q9', 'run': 'p1', 'out': f'{d}/q9.zip'},
                          {'op': 'forget', 'id': 'q10', 'run': 'p1'},
                          {'op': 'column', 'id': 'q11', 'run': 'p1', 'series': [0], 'at': 0, 'out': f'{d}/q11'}):
                    yield json.dumps(q)

            serve(stdin=lines(), stdout=out)
            ends = {e['id']: e for e in (json.loads(x) for x in out.getvalue().splitlines()) if 'id' in e
                    and e.get('event') in ('done', 'error')}
            self.assertEqual({k: e['event'] for k, e in ends.items()},
                             {'p1': 'done', **{f'q{i}': 'done' for i in (1, 2, 3, 4, 5, 9, 10)},
                              **{f'q{i}': 'error' for i in (6, 7, 8, 11)}})
            # Without its series, saying so; the draws, the times and which ran are there.
            with zipfile.ZipFile(f'{d}/p1.zip') as z:
                names = set(z.namelist())
                meta = json.loads(z.read('results/sample/meta.json'))
            self.assertFalse(any('series.' in x for x in names))
            self.assertTrue({'results/sample/draws.f64', 'results/sample/t.f64', 'results/sample/ran.u8'} <= names)
            self.assertTrue(meta['onEngine'])
            self.assertEqual((meta['iterations'], meta['times'], len(meta['outputs'])), (n, times, count))

            def doubles(name):
                return np.fromfile(f'{d}/{name}', '<f8')

            def laid_out(bs):
                # Per series: a run per percentile, the mean, the deviation and its
                # count, and the median's two intervals.
                return np.concatenate([np.concatenate([*b['q'], b['mean'], b['sd']['sd'], b['sd']['n'],
                                                       b['med']['errLo'], b['med']['errHi'], b['med']['bodyLo'],
                                                       b['med']['bodyHi']]) for b in bs])

            def same(a, b):
                return a.shape == b.shape and np.array_equal(a.view(np.int64), b.view(np.int64))

            self.assertTrue(same(doubles('q1'), laid_out(bands(prob, [0.05, 0.5, 0.95], None))))
            # The median always among the percentiles, and the mask leaving realisations out.
            self.assertTrue(same(doubles('q2'), laid_out(bands(prob, [0.25, 0.5, 0.75], np.array(mask, bool)))))
            self.assertEqual(doubles('q2').size, sum((3 + 7) * (1 if prob.flat[k] else times) for k in range(count)))
            got = doubles('q3')
            self.assertTrue(same(got[:n * times], np.asarray(prob.values[kept[1]], '<f8').ravel()))
            self.assertTrue(same(got[n * times:], np.asarray(prob.values[varied[0]], '<f8').ravel()))
            got = doubles('q4')
            self.assertTrue(same(got, np.concatenate([np.asarray(prob.values[kept[0]])[:, 7],
                                                      np.asarray(prob.values[varied[0]])[:, 0]])))
            got = doubles('q5')
            self.assertTrue(same(got, np.concatenate([np.asarray(prob.values[kept[2]])[3],
                                                      np.asarray(prob.values[varied[1]])[3]])))
            self.assertIn(f'no series {count}', ends['q6']['message'])
            self.assertIn('2 entries for 10 realisations', ends['q7']['message'])
            self.assertIn("'series' is not something", ends['q8']['message'])
            # The whole sample, series and all, as a probabilistic job writes it otherwise.
            with zipfile.ZipFile(f'{d}/q9.zip') as z:
                self.assertIn('results/sample/series.f64', z.namelist())
            self.assertIn('no longer holds that run', ends['q11']['message'])

    def test_a_kept_sample_may_come_to_what_the_page_says_this_machine_holds(self):
        # The page's limits for a sample the engine holds (`engineLimits`): taken for a
        # kept sample, and not for one that goes back whole, which a tab must hold.
        bio = (EXAMPLES / 'biosphere.json').read_text()
        held = run_probabilistic(json.loads(bio), iterations=6, seed=4)
        kept = sum(1 for _ in held.outputs)
        size = 6 * kept * held.t.size * 8
        with tempfile.TemporaryDirectory() as d:
            lines = [_job('k1', 'probabilistic', bio, f'{d}/k1.zip', iterations=6, seed=4, keep=True, most=size - 1,
                          asked=size),
                     _job('k2', 'probabilistic', bio, f'{d}/k2.zip', iterations=6, seed=4, keep=True, most=size // 4,
                          asked=size),
                     _job('w1', 'probabilistic', bio, f'{d}/w1.zip', iterations=6, seed=4, most=size - 1,
                          asked=size)]
            out = io.StringIO()
            serve(stdin=io.StringIO('\n'.join(lines) + '\n'), stdout=out)
            ends = {e['id']: e for e in (json.loads(x) for x in out.getvalue().splitlines())
                    if e.get('event') in ('done', 'error')}
            self.assertEqual({k: e['event'] for k, e in ends.items()}, {'k1': 'done', 'k2': 'error', 'w1': 'done'})
            self.assertIn('pass large=True', ends['k2']['message'])

            def precision(name):
                with zipfile.ZipFile(f'{d}/{name}.zip') as z:
                    return json.loads(z.read('results/sample/meta.json'))['precision']

            self.assertEqual((precision('k1'), precision('w1')), ('float32', 'double'))


CAL = {
    'name': 'cal',
    'simulation': {'start_time': 0, 'end_time': 100, 'output_points': 101, 'spacing': 'linear', 'solver': 'ndf',
                   'rtol': 1e-8, 'abstol': 1e-12, 'time_unit': 'year'},
    'parameters': [{'name': 'k', 'value': '0.05', 'unit': '1/year'}, {'name': 'A0', 'value': '1', 'unit': 'Bq'}],
    'compartments': [{'name': 'A', 'initial': 'A0', 'unit': 'Bq', 'dydt': '-k*A'}],
}


class Analyses(unittest.TestCase):
    def test_designs_replays_calibrations_and_dydp_are_run_and_written(self):
        bio = (EXAMPLES / 'biosphere.json').read_text()
        targets = [{'output': 'A', 'when': 'at', 'time': t, 'scale': 'log', 'weight': 1,
                    'value': 5 * 2.718281828459045 ** (-0.03 * t)} for t in (20, 80)]
        variables = [{'key': 'k', 'lower': 1e-3, 'upper': 1, 'space': 'log'},
                     {'key': 'A0', 'lower': 0.1, 'upper': 100, 'space': 'log'}]
        with tempfile.TemporaryDirectory() as d:
            lines = [
                _job('t1', 'probabilistic', bio, f'{d}/t1.zip', seed=3, tornado={'low': 0.05, 'high': 0.95}),
                _job('g1', 'probabilistic', bio, f'{d}/g1.zip', seed=7,
                     gsa={'method': 'morris', 'options': {'trajectories': 6, 'levels': 4}}),
                _job('r1', 'replay', bio, f'{d}/r1.zip', index=5, seed=11, iterations=20),
                _job('c1', 'calibrate', json.dumps(CAL), f'{d}/c1.json', targets=targets, variables=variables,
                     method='nelder', maxEvals=400, seed=1),
                _job('s1', 'local-sensitivity', bio, f'{d}/s1.json', parameters=['leachRate[I-129]', 'leachRate[Cl-36]']),
            ]
            out = io.StringIO()
            serve(stdin=io.StringIO('\n'.join(lines) + '\n'), stdout=out)
            events = [json.loads(line) for line in out.getvalue().splitlines()]
            ends = {e['id']: e['event'] for e in events if e.get('event') in ('done', 'error', 'cancelled')}
            self.assertEqual(ends, {'t1': 'done', 'g1': 'done', 'r1': 'done', 'c1': 'done', 's1': 'done'},
                             [e for e in events if e.get('event') == 'error'])

            def sample_meta(path):
                with zipfile.ZipFile(path) as z:
                    return json.loads(z.read('results/sample/meta.json'))

            # Every input swung alone, counted from 0 as the page counts them.
            tornado = sample_meta(f'{d}/t1.zip')
            self.assertEqual(tornado['iterations'], 31)
            self.assertEqual(tornado['stats']['tornado']['swung'], list(range(15)))
            self.assertEqual(sample_meta(f'{d}/g1.zip')['stats']['gsa']['method'], 'morris')
            # A realisation replayed: an ordinary run, saying which.
            with zipfile.ZipFile(f'{d}/r1.zip') as z:
                self.assertIn('results/y.f64', z.namelist())
                replayed = json.loads(z.read('results/meta.json'))['replayed']
            self.assertEqual((replayed['index'], replayed['iterations'], len(replayed['values'])), (5, 20, 15))
            # A calibration, its best so far said on the way.
            result = json.loads(Path(f'{d}/c1.json').read_text())
            self.assertTrue(result['ok'] and result['matched'], result)
            got = {v['key']: v['value'] for v in result['values']}
            self.assertAlmostEqual(got['k'], 0.03, delta=1e-5)
            steps = [e['detail'] for e in events if e.get('id') == 'c1' and 'detail' in e]
            self.assertTrue(steps and all(set(x) == {'evals', 'fx', 'best', 'values'} for x in steps), steps[:2])
            # dy/dp: every state the page shows, with a derivative per parameter.
            dydp = json.loads(Path(f'{d}/s1.json').read_text())
            self.assertEqual([c['label'] for c in dydp['chosen']], ['leachRate[I-129]', 'leachRate[Cl-36]'])
            self.assertTrue(dydp['states'] and all(len(s['y']) == len(dydp['t']) and len(s['sens']) == 2
                                                   for s in dydp['states']))


class Sample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads((EXAMPLES / 'biosphere.json').read_text())
        cls.prob = run_probabilistic(cls.raw, iterations=9, seed=11)

    def test_laid_out_as_the_page_lays_it_out(self):
        entries = {e['name']: e['bytes'] for e in sample_entries(self.prob, stamp='then')}
        meta = json.loads(entries['results/sample/meta.json'])
        n, times = self.prob.iterations, len(self.prob.t)
        flat = meta['flat']
        kept = [k for k, f in enumerate(flat) if not f]
        self.assertEqual((meta['format'], meta['kind'], meta['iterations'], meta['times']),
                         (1, 'kompartment-sample', n, times))
        self.assertEqual(meta['kept'], len(kept))
        series = np.frombuffer(entries['results/sample/series.f64'], '<f8')
        self.assertEqual(series.size, len(kept) * n * times)
        # Realisation after realisation, each one's times together.
        np.testing.assert_array_equal(series[:times], self.prob.values[kept[0]][0])
        np.testing.assert_array_equal(series[times:2 * times], self.prob.values[kept[0]][1])
        draws = np.frombuffer(entries['results/sample/draws.f64'], '<f8')
        np.testing.assert_array_equal(draws[:n], self.prob.samples[0])
        varied = [k for k, f in enumerate(flat) if f]
        self.assertTrue(varied and all(meta['drawnFrom'][k] >= 0 for k in varied))
        self.assertTrue(all(meta['drawnFrom'][k] == -1 for k in kept))

    @unittest.skipUnless(HAVE_APP, 'needs Node and the application')
    def test_the_page_reads_it_back_as_the_run_it_was(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sample.zip')
            with open(path, 'wb') as f:
                f.write(sample_archive(self.prob, project=self.raw))
            script = os.path.join(d, 'read.mjs')
            with open(script, 'w') as f:
                f.write(
                    "import { readFileSync } from 'node:fs';\n"
                    f"const {{ unzip }} = await import({json.dumps((SRC / 'io' / 'zip.js').as_uri())});\n"
                    f"const ds = await import({json.dumps((SRC / 'io' / 'dataset.js').as_uri())});\n"
                    "const entries = await unzip(new Uint8Array(readFileSync(process.argv[2])).buffer);\n"
                    "const r = ds.sampleResult(ds.readSample(entries));\n"
                    "process.stdout.write(JSON.stringify({ n: r.iterations, labels: r.outputs.map((o) => o.label),"
                    " flat: Array.from(r.flat), first: Array.from(r.values[0]), drawn: Array.from(r.samples[0]) }));\n")
            got = json.loads(subprocess.run([NODE, script, path], capture_output=True, text=True,
                                            check=True).stdout)
        self.assertEqual(got['n'], self.prob.iterations)
        self.assertEqual(got['labels'][:len(self.prob.outputs)], [o['label'] for o in self.prob.outputs])
        self.assertEqual(got['first'], self.prob.values[0].ravel().tolist())
        self.assertEqual(got['drawn'], np.asarray(self.prob.samples[0]).tolist())


FAKE_ENGINE = """
import json, sys, threading, time
lock = threading.Lock()

def say(event):
    with lock:
        print(json.dumps(event), flush=True)

def job(m):
    time.sleep(float(m['options'].get('takes', 0.6)))
    with open(m['out'], 'wb') as f:
        f.write(b'x')
    say({'id': m['id'], 'event': 'done', 'ms': 1})

say({'event': 'ready', 'engine': 'fake', 'concurrent': 2})
for line in sys.stdin:
    m = json.loads(line)
    if m.get('op') == 'job':
        threading.Thread(target=job, args=(m,), daemon=True).start()
"""


class ManyAtOnce(unittest.TestCase):
    """serve.py's engines take as many jobs at once as they say they do; one stopped among
    others is let go of for its page rather than the process ended under the rest."""

    def test_jobs_side_by_side_and_one_stopped_among_them(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('kompartment_serve', APP / 'serve.py')
        server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server)
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / 'fake_engine.py'
            fake.write_text(FAKE_ENGINE)
            engine = server.Engine('fake', [sys.executable, str(fake)], dict(os.environ))
            engines = server.Engines({'fake': engine}, 'fake', tempfile.mkdtemp(dir=d))
            try:
                def settle(jobs, most=0, timeout=30.0):
                    t0 = time.time()
                    while any(j.state in ('queued', 'running') for j in jobs) and time.time() - t0 < timeout:
                        most = max(most, len(engine.running))
                        time.sleep(0.02)
                    return most

                started = time.time()
                jobs = [engines.submit('run', 'fake', f'c{k}', '{}', {'takes': 0.6}) for k in range(3)]
                most = settle(jobs)
                took = time.time() - started
                self.assertEqual([j.state for j in jobs], ['done'] * 3)
                # Two at once, the third after: neither one at a time nor all three at once.
                self.assertEqual(most, 2)
                self.assertTrue(1.1 < took < 1.7, took)
                self.assertEqual(engines.info()['engines']['fake']['concurrent'], 2)
                # One stopped among others: let go of for its page after the grace,
                # the other carried on, and the process not ended.
                slow = engines.submit('run', 'fake', 's1', '{}', {'takes': 10})
                other = engines.submit('run', 'fake', 's2', '{}', {'takes': 5})
                time.sleep(0.5)
                self.assertEqual((slow.state, other.state), ('running', 'running'))
                engines.cancel(slow)
                time.sleep(server.GRACE + 0.6)
                self.assertEqual((slow.state, other.state, engine.restarts), ('cancelled', 'running', 0))
                settle([other])
                self.assertEqual(other.state, 'done')
            finally:
                engines.close()


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Server(unittest.TestCase):
    """serve.py: the page with its token, the refusals, and a run on the Python engine."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen([sys.executable, str(APP / 'serve.py'), str(cls.port), '--engine', 'python',
                                     '--no-julia'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.base = f'http://127.0.0.1:{cls.port}'
        page = None
        for _ in range(200):
            try:
                page = urllib.request.urlopen(f'{cls.base}/').read().decode()
                break
            except OSError:
                time.sleep(0.1)
        cls.token = re.search(r'<meta name="kompartment-engines" content="([^"]+)">', page or '').group(1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def call(self, path, body=None, **headers):
        req = urllib.request.Request(f'{self.base}{path}', data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', **headers})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_only_the_page_it_served_is_answered(self):
        ok = {'X-Kompartment-Token': self.token}
        self.assertEqual(self.call('/engine/info')[0], 403)
        self.assertEqual(self.call('/engine/info', **{'X-Kompartment-Token': 'not it'})[0], 403)
        # Another page in the same browser, and a name pointed at this machine.
        self.assertEqual(self.call('/engine/info', **ok, Origin='http://elsewhere.example')[0], 403)
        self.assertEqual(self.call('/engine/info', **ok, Host=f'elsewhere.example:{self.port}')[0], 403)
        code, body = self.call('/engine/info', **ok)
        info = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(info['default'], 'python')
        self.assertTrue(info['explicit'])
        self.assertTrue(info['engines']['python']['available'])
        self.assertEqual(info['engines']['julia']['why'], 'is switched off (--no-julia)')

    def test_a_run_comes_back_as_an_archive(self):
        ok = {'X-Kompartment-Token': self.token}
        model = json.loads((EXAMPLES / 'four-compartment.json').read_text())
        code, body = self.call('/engine/jobs', {'kind': 'run', 'engine': 'python', 'client': 't', 'model': model}, **ok)
        self.assertEqual(code, 202, body)
        job = json.loads(body)['id']
        for _ in range(600):
            state = json.loads(self.call(f'/engine/jobs/{job}', **ok)[1])
            if state['state'] not in ('queued', 'running'):
                break
            time.sleep(0.1)
        self.assertEqual(state['state'], 'done', state)
        code, data = self.call(f'/engine/jobs/{job}/archive', **ok)
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('results/meta.json', z.namelist())
        # Handed over once, then let go of.
        self.assertEqual(self.call(f'/engine/jobs/{job}/archive', **ok)[0], 404)
        # A kind the engines do not run, refused before anything is started.
        self.assertEqual(self.call('/engine/jobs', {'kind': 'draw', 'engine': 'python', 'model': model}, **ok)[0], 400)

    def finished(self, model, client, kind='run', **options):
        """A run kept by its engine for this client: its job id and the archive it sent."""
        ok = {'X-Kompartment-Token': self.token}
        code, body = self.call('/engine/jobs', {'kind': kind, 'engine': 'python', 'client': client, 'model': model,
                                                'options': {'keep': True, **options}}, **ok)
        self.assertEqual(code, 202, body)
        job = json.loads(body)['id']
        for _ in range(600):
            state = json.loads(self.call(f'/engine/jobs/{job}', **ok)[1])
            if state['state'] not in ('queued', 'running'):
                break
            time.sleep(0.1)
        self.assertEqual(state['state'], 'done', state)
        code, data = self.call(f'/engine/jobs/{job}/archive', **ok)
        self.assertEqual(code, 200)
        return job, data

    @unittest.skipUnless(HAVE_APP, 'needs Node and the application')
    def test_the_page_hands_the_engine_its_work_and_gets_back_what_it_works_out_itself(self):
        # The page's own worker, sent what the page sends it -- a run, a tornado, a
        # sensitivity design, a replayed realisation, a calibration, dy/dp -- once
        # with the engine and once without: the same answers.
        script = Path(__file__).parent / 'node' / 'worker_engine.mjs'
        done = subprocess.run([NODE, str(script), str(SRC), self.base, self.token, 'python', str(EXAMPLES)],
                              capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        got = json.loads(done.stdout)
        # What the page reads of the run besides its series, from the engine
        # without a build of the model in the page: as the page's own run says it.
        self.assertEqual(got['summary'], {'differ': [], 'code': True})
        self.assertEqual((got['run']['engine'], got['run']['saved']), ('python', True))
        self.assertLessEqual(got['run']['worst'], 1e-12)
        self.assertTrue(got['tornado']['onEngine'] and got['tornado']['same'], got['tornado'])
        self.assertEqual(got['tornado']['points'], 31)
        self.assertTrue(got['gsa']['onEngine'] and got['gsa']['same'], got['gsa'])
        self.assertTrue(got['replay']['inputs'] and got['replay']['index'] == 5, got['replay'])
        self.assertLessEqual(got['replay']['worst'], 1e-9)
        self.assertTrue(got['calibrate']['onEngine'] and got['calibrate']['matched'] and got['calibrate']['same'],
                        got['calibrate'])
        self.assertTrue(got['sensitivity']['onEngine'] and got['sensitivity']['same'], got['sensitivity'])
        self.assertLessEqual(got['sensitivity']['worst'], 1e-9)
        # A sample the engine holds: its bands the page's own formulas over its
        # realisations, to the last bit, screened or not; and every question asked
        # of it answered as the same sample held in the page answers it.
        sample = got['sample']
        self.assertEqual((sample['engine'], sample['error']), ('python', None), sample)
        self.assertTrue(sample['bands'] and sample['screenedBands'] and sample['payload'], sample)
        self.assertLess(sample['kept'], sample['iterations'])
        self.assertEqual(sample['differ'], [])

    def test_a_sample_its_engine_holds_is_asked_about_beside_the_run_and_let_go_of(self):
        ok = {'X-Kompartment-Token': self.token}
        model = json.loads((EXAMPLES / 'biosphere.json').read_text())
        run_job, _ = self.finished(json.loads((EXAMPLES / 'four-compartment.json').read_text()), 's')
        job, data = self.finished(model, 's', kind='probabilistic', iterations=8, seed=2)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertFalse(any('series.' in x for x in z.namelist()))
            meta = json.loads(z.read('results/sample/meta.json'))
        n, times = meta['iterations'], meta['times']
        # Only for the page the server served.
        self.assertEqual(self.call(f'/engine/runs/{job}/column', {'series': [0], 'at': 2})[0], 403)
        code, body = self.call(f'/engine/runs/{job}/column', {'series': [0, 1], 'at': 2}, **ok)
        self.assertEqual((code, len(body)), (200, 2 * n * 8), body[:200])
        code, body = self.call(f'/engine/runs/{job}/realisations', {'series': [0]}, **ok)
        self.assertEqual((code, len(body)), (200, n * times * 8))
        code, body = self.call(f'/engine/runs/{job}/realisation', {'series': [0], 'index': 3}, **ok)
        self.assertEqual((code, len(body)), (200, times * 8))
        code, body = self.call(f'/engine/runs/{job}/bands', {'percentiles': [0.05, 0.5, 0.95], 'mask': None}, **ok)
        self.assertEqual(code, 200)
        strides = [1 if f else times for f in meta['flat']]
        self.assertEqual(len(body), sum(10 * s for s in strides) * 8)
        # Asked wrongly: said so before the engine is asked.
        for path, ask in (('column', {'series': [0]}), ('column', {'series': ['0'], 'at': 1}),
                          ('bands', {'percentiles': 'all', 'mask': None}),
                          ('bands', {'percentiles': [0.5], 'mask': [2]}),
                          ('realisation', {'series': [0], 'index': -1})):
            self.assertEqual(self.call(f'/engine/runs/{job}/{path}', ask, **ok)[0], 400, (path, ask))
        code, body = self.call(f'/engine/runs/{job}/column', {'series': [10 ** 6], 'at': 0}, **ok)
        self.assertEqual(code, 502)
        self.assertIn('no series', json.loads(body)['error'])
        code, whole = self.call(f'/engine/runs/{job}/archive', **ok)
        with zipfile.ZipFile(io.BytesIO(whole)) as z:
            self.assertIn('results/sample/series.f64', z.namelist())
        # Beside the page's run, which it does not replace; the page's next sample replaces it.
        self.assertEqual(self.call(f'/engine/runs/{run_job}/archive', **ok)[0], 200)
        newer, _ = self.finished(model, 's', kind='probabilistic', iterations=4, seed=2)
        self.assertEqual(self.call(f'/engine/runs/{job}/column', {'series': [0], 'at': 0}, **ok)[0], 404)
        self.assertEqual(self.call(f'/engine/runs/{run_job}/archive', **ok)[0], 200)
        self.assertEqual(self.call(f'/engine/runs/{newer}/forget', {}, **ok)[0], 200)
        self.assertEqual(self.call(f'/engine/runs/{newer}/column', {'series': [0], 'at': 0}, **ok)[0], 404)
        # A tornado is never held: it is read in the page as soon as it is run.
        torn, data = self.finished(model, 's', kind='probabilistic', tornado={'low': 0.05, 'high': 0.95})
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('results/sample/series.f64', z.namelist())
        self.assertEqual(self.call(f'/engine/runs/{torn}/column', {'series': [0], 'at': 0}, **ok)[0], 404)
        # A page that goes lets go of its run, its sample and its scenarios' runs; another page's stay.
        four = json.loads((EXAMPLES / 'four-compartment.json').read_text())
        mine = [self.finished(four, 'gone')[0], self.finished(four, 'gone#Scenario 2')[0],
                self.finished(model, 'gone', kind='probabilistic', iterations=4, seed=2)[0]]
        theirs, _ = self.finished(model, 'gonero', kind='probabilistic', iterations=4, seed=2)
        self.assertEqual(self.call('/engine/clients/gone/forget', {})[0], 403)
        code, body = self.call('/engine/clients/gone/forget', {}, **ok)
        self.assertEqual((code, json.loads(body)), (200, {'forgotten': 3}))
        for k in mine:
            self.assertEqual(self.call(f'/engine/runs/{k}/archive', **ok)[0], 404)
        self.assertEqual(self.call(f'/engine/runs/{theirs}/column', {'series': [0], 'at': 0}, **ok)[0], 200)

    def test_a_run_its_engine_holds_is_asked_about_and_let_go_of(self):
        ok = {'X-Kompartment-Token': self.token}
        model = json.loads((EXAMPLES / 'four-compartment.json').read_text())
        made = run(model)
        labels = [o['label'] for o in made.outputs()]
        job, data = self.finished(model, 'k')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertNotIn('results/y.f64', z.namelist())
        # Only for the page the server served.
        self.assertEqual(self.call(f'/engine/runs/{job}/series', {'labels': labels[:2]})[0], 403)
        code, body = self.call(f'/engine/runs/{job}/series', {'labels': labels[:2]}, **ok)
        self.assertEqual(code, 200, body)
        got = np.frombuffer(body, '<f8').reshape(2, -1)
        self.assertTrue(np.array_equal(got, np.array(made.series_many(made.outputs()[:2]))))
        self.assertEqual(self.call(f'/engine/runs/{job}/series', {'labels': 'not a list'}, **ok)[0], 400)
        code, body = self.call(f'/engine/runs/{job}/series', {'labels': ['Nowhere']}, **ok)
        self.assertEqual(code, 502)
        self.assertIn('no series called', json.loads(body)['error'])
        code, whole = self.call(f'/engine/runs/{job}/archive', **ok)
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(whole)) as z:
            self.assertIn('results/y.f64', z.namelist())
        # The page's next run takes the place of its last one; another page's stays.
        other, _ = self.finished(model, 'other page')
        newer, _ = self.finished(model, 'k')
        self.assertEqual(self.call(f'/engine/runs/{job}/series', {'labels': labels[:1]}, **ok)[0], 404)
        self.assertEqual(self.call(f'/engine/runs/{other}/series', {'labels': labels[:1]}, **ok)[0], 200)
        self.assertEqual(self.call(f'/engine/runs/{newer}/series', {'labels': labels[:1]}, **ok)[0], 200)
        # And a run let go of is gone.
        self.assertEqual(self.call(f'/engine/runs/{newer}/forget', {}, **ok)[0], 200)
        self.assertEqual(self.call(f'/engine/runs/{newer}/series', {'labels': labels[:1]}, **ok)[0], 404)



def _enginesetup():
    """serve.py's enginesetup module, loaded from beside it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('enginesetup', APP / 'enginesetup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WhatTheEnginesNeed(unittest.TestCase):
    """What the engines need is checked as serve.py starts, said with how to get it,
    and set up when asked (enginesetup.py)."""

    def test_a_python_is_read_for_what_it_has(self):
        E = _enginesetup()
        state = E.python_state(sys.executable)
        self.assertTrue(state['numpy'] and state['scipy'], state)
        self.assertIsNone(E.python_lacks(state))
        self.assertEqual(E.python_lacks({'version': [3, 12], 'numpy': True, 'scipy': False}), 'needs SciPy')
        self.assertEqual(E.python_lacks({'version': [3, 12], 'numpy': False, 'scipy': False}),
                         'needs NumPy and SciPy')
        self.assertEqual(E.python_lacks({'version': [3, 8], 'numpy': True, 'scipy': True}),
                         'needs Python 3.9 or newer, and this is 3.8')
        gone = E.python_state('/nowhere/python')
        self.assertIn('could not be started with /nowhere/python', E.python_lacks(gone))
        with tempfile.TemporaryDirectory() as d:
            # A Python with nothing in it: what a Python the engine cannot run on looks like.
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', d], check=True)
            bare = E.python_state(E.venv_python(d))
            self.assertEqual(E.python_lacks(bare), 'needs NumPy and SciPy')

    def test_a_julia_is_asked_which_of_its_packages_it_lacks_without_installing_them(self):
        E = _enginesetup()
        julia = E.find_julia('julia')
        if julia is None:
            self.skipTest('needs Julia')
        self.assertIsNone(E.find_julia('/nowhere/julia'))
        self.assertEqual(E.find_julia(julia), julia)
        with tempfile.TemporaryDirectory() as d:
            # A fresh checkout on a fresh machine: the project without its manifest, and no depot.
            project = os.path.join(d, 'project')
            os.makedirs(project)
            with open(APP / 'julia' / 'Project.toml', encoding='utf-8') as f, \
                    open(os.path.join(project, 'Project.toml'), 'w', encoding='utf-8') as g:
                g.write(f.read())
            depot = os.path.join(d, 'depot')
            os.makedirs(depot)
            state = E.julia_state(julia, project, env={**os.environ, 'JULIA_DEPOT_PATH': depot})
            self.assertEqual(state['missing'], ['FunctionWrappers', 'OrderedCollections', 'PrecompileTools'], state)
            self.assertIn('needs its packages, which are not installed (FunctionWrappers,', E.julia_lacks(state))
            # Julia may keep a compiled standard library there; no package, registry or artifact.
            self.assertFalse(set(os.listdir(depot)) & {'packages', 'registries', 'artifacts'}, os.listdir(depot))
        self.assertEqual(E.julia_lacks({'version': '1.9.4', 'missing': []}),
                         'needs Julia 1.10 or newer, and this is 1.9.4')
        self.assertIsNone(E.julia_lacks({'version': '1.13.1-DEV', 'missing': []}))

    def test_a_julia_that_never_installed_a_package_gets_a_registry_first(self):
        # Julia's resolve does not fetch a registry, as instantiate would: on a machine
        # that never installed a package it failed with "no registries have been installed".
        E = _enginesetup()
        code = E.JULIA_PACKAGES
        self.assertLess(code.index('Pkg.Registry.add()'), code.index('Pkg.resolve()'))
        self.assertIn('isempty(Pkg.Registry.reachable_registries())', code)
        self.assertLess(code.index('Pkg.resolve()'), code.index('Pkg.instantiate()'))
        self.assertLess(code.index('Pkg.instantiate()'), code.index('Pkg.precompile()'))

    @unittest.skipUnless(os.environ.get('KOMPARTMENT_NETWORK_TESTS') == '1',
                         'downloads Julia\'s registry and packages: KOMPARTMENT_NETWORK_TESTS=1')
    def test_the_julia_engine_s_packages_install_on_a_fresh_machine(self):
        # A fresh checkout (no manifest) on a Julia with an empty depot, installed for real.
        import shutil as sh
        E = _enginesetup()
        julia = E.find_julia('julia')
        if julia is None:
            self.skipTest('needs Julia')
        with tempfile.TemporaryDirectory() as d:
            project = os.path.join(d, 'project')
            sh.copytree(APP / 'julia', project, ignore=sh.ignore_patterns('Manifest.toml', 'test'))
            env = {**os.environ, 'JULIA_DEPOT_PATH': os.path.join(d, 'depot')}
            self.assertTrue(E.julia_state(julia, project, env)['missing'])
            self.assertTrue(E.install_julia_packages(julia, project, env))
            self.assertEqual(E.julia_state(julia, project, env)['missing'], [])

    def test_numba_is_offered_as_julia_s_packages_are(self):
        # Where the engine runs without numba: into its own Python where it has one,
        # else by making it one -- never into the reader's own Python. Probes and
        # installers stood in for, so that nothing is downloaded.
        E = _enginesetup()
        with tempfile.TemporaryDirectory() as d:
            E.HOME, E.VENV = d, os.path.join(d, 'python')
            own = E.venv_python(E.VENV)
            states = {'/my/python': {'version': [3, 12], 'numpy': True, 'scipy': True, 'numba': False},
                      '/old/python': {'version': [3, 9], 'numpy': True, 'scipy': True, 'numba': False}}
            E.python_state = lambda python, env=None: dict(states.get(python, {'error': f'no {python}'}))
            E.interactive = lambda: True
            replies = []
            E.ask = lambda question: replies.pop(0)  # an unexpected question fails the test
            made, installed = [], []

            def set_up(base):
                made.append(base)
                os.makedirs(os.path.dirname(own), exist_ok=True)
                open(own, 'w').close()
                states[own] = {'version': [3, 12], 'numpy': True, 'scipy': True, 'numba': True}
                return own

            def numba(python):
                installed.append(python)
                states[python]['numba'] = True
                return True

            E.set_up_python, E.install_numba = set_up, numba
            project = str(APP / 'julia')
            run = lambda python, asked=False, **kw: E.prepare(python, asked, 'julia', True, False, project, **kw)  # noqa: E731
            # Asked, and told no: nothing made, the no kept, how to get it said -- and not asked again.
            replies[:] = [False]
            python, why, _, _, notes = run('/my/python')
            self.assertEqual((python, why, made, replies), ('/my/python', None, [], []))
            self.assertIn('numba', E.declined())
            self.assertIn('Python engine without numba, which makes it several times quicker: /my/python -m pip '
                          'install numba, or python3 serve.py --setup', notes)
            run('/my/python')
            # --setup: the engine's own Python made, from the reader's, and run on.
            python, why, _, _, notes = run('/my/python', setup=True)
            self.assertEqual((python, why, made), (own, None, ['/my/python']))
            self.assertNotIn('numba', E.declined())
            self.assertIn(f'Python engine on its own Python, {E.VENV}', notes)
            # The engine's own Python without numba: numba installed into it, at a yes.
            states[own]['numba'] = False
            replies[:] = [True]
            python, _, _, _, notes = run('/my/python')
            self.assertEqual((python, installed, replies), (own, [own], []))
            self.assertFalse(any('without numba' in n for n in notes), notes)
            # Not offered on a Python numba does not install on, nor for one named with --python.
            os.remove(own)
            _, _, _, _, notes = run('/old/python')
            self.assertIn('Python engine without numba, which makes it several times quicker and needs Python '
                          '3.10 or newer: pass one with --python', notes)
            python, _, _, _, notes = run('/my/python', asked=True)
            self.assertEqual(python, '/my/python')
            self.assertEqual(made, ['/my/python'])

    def test_a_no_is_remembered_and_nothing_is_asked_without_a_terminal(self):
        E = _enginesetup()
        with tempfile.TemporaryDirectory() as d:
            E.HOME = d
            E.VENV = os.path.join(d, 'python')
            self.assertEqual(E.declined(), set())
            E.remember_declined({'julia'})
            self.assertEqual(E.declined(), {'julia'})
            with open(os.path.join(d, 'serve.json'), 'w', encoding='utf-8') as f:
                f.write('not json')
            self.assertEqual(E.declined(), set())
            # Not at a terminal: what is missing is said, and nothing is offered or installed.
            with tempfile.TemporaryDirectory() as bare:
                subprocess.run([sys.executable, '-m', 'venv', '--without-pip', bare], check=True)
                python, py_why, julia, jl_why, _ = E.prepare(E.venv_python(bare), True, '/nowhere/julia', True,
                                                             True, str(APP / 'julia'))
            self.assertEqual(py_why, 'needs NumPy and SciPy (python3 serve.py --setup sets it up)')
            self.assertEqual(jl_why, 'has no Julia at /nowhere/julia')
            self.assertFalse(os.path.exists(E.VENV))
            # The engine's own Python, where there is one, unless another is asked for.
            python, py_why, _, _, notes = E.prepare(sys.executable, False, 'julia', True, False, str(APP / 'julia'))
            self.assertEqual((python, py_why), (sys.executable, None))
            os.makedirs(os.path.dirname(E.venv_python(E.VENV)))
            os.symlink(sys.executable, E.venv_python(E.VENV))
            python, py_why, _, jl_why, notes = E.prepare(sys.executable, False, 'julia', True, False,
                                                         str(APP / 'julia'))
            self.assertEqual((python, py_why, jl_why), (E.venv_python(E.VENV), None, 'is switched off (--no-julia)'))
            self.assertIn(f'Python engine on its own Python, {E.VENV}', notes)
            python, _, _, _, _ = E.prepare(sys.executable, True, 'julia', True, False, str(APP / 'julia'))
            self.assertEqual(python, sys.executable)

    def test_the_server_says_what_an_engine_lacks_and_how_to_get_it(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, '-m', 'venv', '--without-pip', os.path.join(d, 'bare')], check=True)
            bare = os.path.join(d, 'bare', 'Scripts' if os.name == 'nt' else 'bin',
                                'python.exe' if os.name == 'nt' else 'python')
            port = _free_port()
            proc = subprocess.Popen([sys.executable, str(APP / 'serve.py'), str(port), '--python', bare, '--julia',
                                     '/nowhere/julia'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    env={**os.environ, 'KOMPARTMENT_HOME': os.path.join(d, 'home')})
            said = []
            try:
                for line in proc.stdout:
                    said.append(line.rstrip())
                    if 'Ctrl+C to stop' in line:
                        break
            finally:
                proc.terminate()
                proc.wait(timeout=10)
            text = '\n'.join(said)
            self.assertIn('python engine not available: needs NumPy and SciPy (python3 serve.py --setup sets it up)',
                          text)
            self.assertIn('julia engine not available: has no Julia at /nowhere/julia', text)
            self.assertFalse(os.path.exists(os.path.join(d, 'home')), 'a server not at a terminal set something up')

if __name__ == '__main__':
    unittest.main()
