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
import time
import unittest
import urllib.error
import urllib.request
import zipfile

import numpy as np

from helpers import APP, EXAMPLES, HAVE_APP, NODE, SRC

from kompartment.engine.probabilistic import run_probabilistic
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


if __name__ == '__main__':
    unittest.main()
