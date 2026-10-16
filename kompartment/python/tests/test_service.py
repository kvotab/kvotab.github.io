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

    def finished(self, model, client):
        """A run kept by its engine for this client: its job id and the archive it sent."""
        ok = {'X-Kompartment-Token': self.token}
        code, body = self.call('/engine/jobs', {'kind': 'run', 'engine': 'python', 'client': client, 'model': model,
                                                'options': {'keep': True}}, **ok)
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


if __name__ == '__main__':
    unittest.main()
