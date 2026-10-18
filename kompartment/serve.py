#!/usr/bin/env python3
"""
Development server for Kompartment -- and the way to run a model on an engine
on this machine rather than in the browser.

`python3 -m http.server` sends only Last-Modified, with no Cache-Control and no
ETag. Browsers are then free to reuse JavaScript modules they already hold --
and a Worker keeps its own module cache on top of the page's, so edited code can
keep running for a surprisingly long time. That produces confusing failures
where the page reports something the source on disk no longer says.

This server sends `Cache-Control: no-store` for everything, so a plain refresh
always picks up the current files.

    python3 serve.py [port] [--engine browser|python|julia] [--python PATH] [--julia PATH]
                     [--no-python] [--no-julia]

Defaults to port 8080. Serves the directory the script lives in, to this
machine only.

## Engines

The page solves its models in the browser. Served from here, it can also hand
a run -- Run, a probabilistic run, and the analyses that solve the model: a
tornado, a sensitivity design, a replayed realisation, a calibration, dy/dp --
to the Python engine (`python/kompartment`) or the Julia one (`julia/`), chosen
in the page beside Run; `--engine` says which the page starts on. What an engine
does not do, it refuses at once, and the page does it itself. Each engine is a process of its
own, started the first time it is asked for and kept: a line of JSON a message,
jobs in and progress out (see python/kompartment/service.py) -- as many jobs at
once as the engine says it takes, the rest queued (Julia takes one a thread, so
scenarios run beside each other there; Python one at a time). A run comes back
as the archive *Save with results* writes, which the page reads the way it
reads a file somebody opened.

A run the page asks to be kept (`"keep": true`) comes back without its states:
the engine holds it, and the page asks for the series it shows as it shows them
(`/engine/runs/<id>/series`), and for the whole run only to save it, keep it
beside or work an edit out over it (`/engine/runs/<id>/archive`). A probabilistic
run kept the same way comes back without its realisations: the page asks for
its bands, for every realisation of a series, for one time across them all and
for one realisation (`/engine/runs/<id>/bands`, `realisations`, `column` and
`realisation`), and for the whole sample only to save it. An engine holds one
run and one sample a page -- a scenario run beside the chosen one asks as a page
of its own -- the page's next of each replaces it, and one let go of by the
page, left unasked about for two hours, or held by an engine since restarted,
is gone: the page then says to run it again. A page that goes lets go of all it
had held (`/engine/clients/<client>/forget`).

The engines answer only the page this server served. Every request under
`/engine/` carries a token the server writes into that page, and must come from
this machine under this server's own name: a model is code to an engine, and
any other web page open in the same browser could otherwise send it one.
"""

import collections
import http.server
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

# A few types the stdlib guesses wrongly or not at all on some systems.
EXTRA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".eco": "application/zip",
}

ROOT = os.path.dirname(os.path.abspath(__file__))

#: How large a model a page may send: the largest assessment as JSON is a few
#: tens of megabytes.
MOST_BODY = 512 * 1024 * 1024

#: A job nobody has asked about for this long is one whose page has gone: it is
#: stopped, so that a closed tab does not leave an engine solving for nobody.
UNWATCHED = 30.0

#: How long a finished job's archive is kept for its page to fetch.
KEPT_FOR = 600.0

#: How long a stopped job has to stop before its engine is ended and started again.
GRACE = 2.0

#: A run an engine holds for its page is let go of once nobody has asked about it for this long.
KEPT_RUN_FOR = 7200.0

#: How long an engine has to answer a question about a run it holds: the whole of
#: the largest assessment's run, written out, takes a while.
ASK_TIMEOUT = 900.0

#: What a page asks about a held probabilistic run, besides its archive: the
#: fields each question takes, and what each must be.
SAMPLE_QUESTIONS = {
    "bands": ("percentiles", "mask"),
    "realisations": ("series",),
    "column": ("series", "at"),
    "realisation": ("series", "index"),
}

#: The questions a page asks as it draws, which the console is not told about.
ASKED_OFTEN = ("/series", *(f"/{q}" for q in SAMPLE_QUESTIONS))


class Job:
    """One run asked of an engine, and what has been heard of it."""

    def __init__(self, kind, engine, client, model, options, out):
        self.id = secrets.token_hex(8)
        self.kind = kind
        self.engine = engine
        self.client = client
        self.model = model
        self.options = options
        self.out = out
        # A run whose engine holds it for its page, its archive without the states
        # -- or a sample, without its realisations (never a tornado's or a design's).
        asked = isinstance(options, dict) and options.get("keep") is True
        self.keep = asked and (kind in ("run", "replay") or kind == "probabilistic"
                               and not options.get("tornado") and not options.get("gsa"))
        # Which of the two a page's held run is: its next of the same kind replaces it.
        self.slot = "sample" if kind == "probabilistic" else "run"
        # The engine's process it ran in: a held run lasts as long as that does.
        self.generation = None
        self.state = "queued"
        self.stage = None
        self.progress = {}
        self.error = None
        self.ms = None
        self.seen = time.time()
        self.finished = None
        # Asked to stop, so that an engine ended for it was ended on purpose.
        self.stopping = False

    def status(self):
        return {
            "id": self.id, "kind": self.kind, "engine": self.engine, "state": self.state,
            "stage": self.stage, **self.progress, "error": self.error, "ms": self.ms,
        }

    def end(self, state):
        self.state = state
        self.finished = time.time()
        # The model is a model's worth of text, and nothing needs it once run.
        self.model = None


class Engine:
    """A long-lived engine process, its queue, and the job it is on."""

    def __init__(self, name, argv, env, why=None):
        self.name = name
        self.argv = argv
        self.env = env
        # Why it cannot be used, where it cannot; None while it may be.
        self.why = why
        self.proc = None
        self.ready = None
        self.queue = collections.deque()
        # The jobs it is on, by id: as many at once as it says it takes.
        self.running = {}
        self.lock = threading.RLock()
        self.restarts = 0
        # Bumped at every start: what a process held, a later one does not.
        self.generation = 0
        # Questions asked of it and not yet answered, by id: what each waits on.
        self.questions = {}

    def info(self):
        with self.lock:
            if self.why:
                state = "unavailable"
            elif self.proc is None:
                state = "stopped"
            elif self.ready is None:
                state = "starting"
            else:
                state = "busy" if self.running else "idle"
            return {"available": self.why is None, "why": self.why, "state": state, "detail": self.ready,
                    "queued": len(self.queue), "running": len(self.running), "concurrent": self.capacity()}

    def capacity(self):
        """How many jobs the engine takes at once: what it said when it was ready, one if nothing."""
        try:
            return max(1, int((self.ready or {}).get("concurrent") or 1))
        except (TypeError, ValueError):
            return 1

    def start(self):
        """Starts the process if it is not running. Called with the lock held."""
        if self.proc is not None or self.why:
            return
        try:
            proc = subprocess.Popen(
                self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self.env, cwd=ROOT, text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as e:
            self.why = f"could not be started: {e}"
            return
        self.proc = proc
        self.ready = None
        self.generation += 1
        threading.Thread(target=self._read, args=(proc,), daemon=True).start()
        threading.Thread(target=self._relay, args=(proc,), daemon=True).start()

    def _relay(self, proc):
        """What the engine prints: to this server's console, labelled."""
        for line in proc.stderr:
            sys.stderr.write(f"  [{self.name}] {line}")

    def _read(self, proc):
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                sys.stderr.write(f"  [{self.name}] {line}")
                continue
            self._heard(proc, event)
        # The process has gone: whatever it was on is lost, and the next job
        # starts it again.
        with self.lock:
            if self.proc is not proc:
                return
            self.proc = None
            self.ready = None
            jobs = list(self.running.values())
            self.running.clear()
            for job in jobs:
                if job.state != "running":
                    continue
                if job.stopping:
                    job.end("cancelled")
                else:
                    job.error = {"name": "EngineError", "message": f"The {self.name} engine stopped during the run.",
                                 "block": None, "hint": "Its console output, where the server runs, may say why."}
                    job.end("error")
            asked = list(self.questions.values())
            self.questions.clear()
            if self.queue:
                self.start()
        for waiter in asked:
            waiter["reply"] = {"event": "error", "name": "EngineError",
                               "message": f"The {self.name} engine stopped before it answered."}
            waiter["done"].set()

    def _heard(self, proc, event):
        with self.lock:
            if self.proc is not proc:
                return
            if event.get("event") == "ready":
                self.ready = {k: v for k, v in event.items() if k != "event"}
                self._pump()
                return
            waiter = self.questions.get(event.get("id"))
            if waiter is not None:
                if event.get("event") in ("done", "error"):
                    del self.questions[event["id"]]
                    waiter["reply"] = event
                    waiter["done"].set()
                return
            job = self.running.get(event.get("id"))
            if job is None:
                return
            kind = event.get("event")
            if kind == "stage":
                job.stage = event.get("stage")
            elif kind == "progress":
                job.progress = {k: event[k] for k in ("fraction", "at", "done", "total", "detail") if k in event}
            elif kind in ("done", "error", "cancelled"):
                del self.running[job.id]
                if job.state == "running":
                    if kind == "error":
                        job.error = {k: event.get(k) for k in ("name", "message", "block", "hint")}
                    job.ms = event.get("ms")
                    job.end(kind)
                elif kind == "done" and job.keep:
                    # Let go of for its page while the engine finished it (see
                    # `cancel`): a run the engine kept for nobody.
                    self.tell("forget", job.generation, run=job.id)
                self._pump()

    def _pump(self):
        """The next jobs, as many as the engine takes at once. Called with the lock held."""
        if self.ready is None or self.proc is None:
            return
        while self.queue and len(self.running) < self.capacity():
            job = self.queue.popleft()
            if job.state != "queued":
                continue
            job.state = "running"
            job.stage = "starting"
            job.generation = self.generation
            self.running[job.id] = job
            try:
                self.proc.stdin.write(json.dumps({
                    "op": "job", "id": job.id, "kind": job.kind, "model": job.model,
                    "options": job.options, "out": job.out,
                }) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                job.error = {"name": "EngineError", "message": f"The {self.name} engine could not be reached: {e}",
                             "block": None, "hint": None}
                job.end("error")
                self.running.pop(job.id, None)
                continue
            job.model = None

    def submit(self, job):
        with self.lock:
            if self.why:
                job.error = {"name": "EngineError", "message": f"The {self.name} engine {self.why}.",
                             "block": None, "hint": None}
                job.end("error")
                return
            self.queue.append(job)
            if self.proc is None:
                self.start()
            self._pump()

    def cancel(self, job):
        with self.lock:
            if job.state == "queued":
                job.end("cancelled")
                return
            if job.state != "running" or self.running.get(job.id) is not job or self.proc is None:
                return
            job.stopping = True
            proc = self.proc
            try:
                proc.stdin.write(json.dumps({"op": "cancel", "id": job.id}) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                pass

        def end_if_still():
            # A probabilistic run stops between realisations, and a long one may
            # not reach the next soon: then the process is ended, and the next
            # job starts it again -- where every job it is on is being stopped.
            # Where others are not, this one is let go of for its page, and the
            # engine finishes it in its own time.
            with self.lock:
                if self.running.get(job.id) is not job or self.proc is not proc:
                    return
                if all(j.stopping for j in self.running.values()):
                    self.restarts += 1
                    try:
                        proc.kill()
                    except OSError:
                        pass
                else:
                    job.end("cancelled")

        threading.Timer(GRACE, end_if_still).start()

    def ask(self, op, generation, timeout=ASK_TIMEOUT, **fields):
        """A question about a run this engine holds, and its answer: the engine's
        ``done`` or ``error``, or an ``error`` of this server's when the engine that
        held it is gone or does not answer."""
        qid = secrets.token_hex(8)
        waiter = {"done": threading.Event(), "reply": None}
        with self.lock:
            if self.proc is None or self.ready is None or self.generation != generation:
                return {"event": "error", "name": "Gone", "gone": True,
                        "message": f"The {self.name} engine has been restarted since the run and no longer "
                                   "holds it. Run it again."}
            self.questions[qid] = waiter
            try:
                self.proc.stdin.write(json.dumps({"op": op, "id": qid, **fields}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                self.questions.pop(qid, None)
                return {"event": "error", "name": "EngineError",
                        "message": f"The {self.name} engine could not be reached: {e}"}
        if not waiter["done"].wait(timeout):
            with self.lock:
                self.questions.pop(qid, None)
            return {"event": "error", "name": "EngineError",
                    "message": f"The {self.name} engine did not answer within {timeout:.0f} s."}
        return waiter["reply"]

    def tell(self, op, generation, **fields):
        """A word to the engine that needs no answer, if the process it is for still runs."""
        with self.lock:
            if self.proc is None or self.generation != generation:
                return
            try:
                self.proc.stdin.write(json.dumps({"op": op, "id": secrets.token_hex(8), **fields}) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def stop(self):
        with self.lock:
            proc = self.proc
            self.proc = None
        if proc is not None:
            try:
                proc.stdin.close()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                proc.kill()


class Engines:
    """Every engine there is, and every job asked of one."""

    def __init__(self, engines, default, folder, explicit=False):
        self.engines = engines
        self.default = default
        # Whether --engine said it: then the page starts on it whatever it
        # remembered choosing last time.
        self.explicit = explicit
        self.folder = folder
        self.jobs = {}
        # The runs engines hold for their pages, by job id.
        self.kept = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._sweep, daemon=True).start()

    def info(self):
        with self.lock:
            held = len(self.kept)
        return {"default": self.default, "explicit": self.explicit, "held": held,
                "engines": {n: e.info() for n, e in self.engines.items()}}

    def submit(self, kind, engine, client, model, options):
        if engine not in self.engines:
            raise ValueError(f"There is no engine called '{engine}' here.")
        if kind not in ("run", "probabilistic", "replay", "calibrate", "local-sensitivity"):
            raise ValueError(f"'{kind}' is not a kind of job the engines run.")
        job = Job(kind, engine, client, model, options, None)
        job.out = os.path.join(self.folder, f"{job.id}.zip")
        # A page asks for one run of a kind at a time: a new one replaces the
        # one it was waiting for, as it does in the browser.
        with self.lock:
            older = [j for j in self.jobs.values()
                     if j.client == client and j.kind == kind and j.state in ("queued", "running")]
            self.jobs[job.id] = job
        for j in older:
            self.engines[j.engine].cancel(j)
        self.engines[engine].submit(job)
        return job

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is not None:
            job.seen = time.time()
        return job

    def cancel(self, job):
        self.engines[job.engine].cancel(job)

    def take(self, job):
        """The archive of a finished job, read once and then let go of. A run its
        engine holds is the page's from now on, in place of the page's last one
        of the same kind: a sample does not replace the run it is drawn over."""
        try:
            with open(job.out, "rb") as f:
                data = f.read()
        except OSError:
            # Its engine lets go of a run whose page cannot have it.
            self.forget(job)
            raise
        self.forget(job, taken=True)
        if job.keep:
            with self.lock:
                older = [k for k, r in self.kept.items() if r["client"] == job.client and r["slot"] == job.slot]
                self.kept[job.id] = {"engine": job.engine, "client": job.client, "generation": job.generation,
                                     "slot": job.slot, "seen": time.time()}
            for k in older:
                self.let_go(k)
        return data

    def forget(self, job, taken=False):
        with self.lock:
            self.jobs.pop(job.id, None)
        try:
            os.remove(job.out)
        except OSError:
            pass
        # Held by its engine for a page that never came for it.
        if job.keep and not taken and job.state == "done":
            self.engines[job.engine].tell("forget", job.generation, run=job.id)

    def held(self, run_id):
        """The run an engine holds under this id, if one does: its record, marked as asked about."""
        with self.lock:
            r = self.kept.get(run_id)
            if r is not None:
                r["seen"] = time.time()
            return r

    def let_go(self, run_id):
        with self.lock:
            r = self.kept.pop(run_id, None)
        if r is not None:
            self.engines[r["engine"]].tell("forget", r["generation"], run=run_id)

    def let_go_of_client(self, client):
        """Every run and sample held for a page that has gone, and for the
        scenarios it ran beside (`<client>#<scenario>`): how many there were."""
        with self.lock:
            gone = [k for k, r in self.kept.items() if r["client"] == client or r["client"].startswith(f"{client}#")]
        for k in gone:
            self.let_go(k)
        return len(gone)

    def ask(self, run_id, op, **fields):
        """A question about a held run: ``(answer, path)``, the engine's answer and
        where it wrote what it was asked for. None when no engine holds the run."""
        r = self.held(run_id)
        if r is None:
            return None
        path = os.path.join(self.folder, secrets.token_hex(8))
        reply = self.engines[r["engine"]].ask(op, r["generation"], run=run_id, out=path, **fields)
        if reply.get("gone"):
            self.let_go(run_id)
        return reply, path

    def _sweep(self):
        while True:
            time.sleep(5)
            now = time.time()
            with self.lock:
                jobs = list(self.jobs.values())
            for job in jobs:
                if job.state in ("queued", "running") and now - job.seen > UNWATCHED:
                    self.cancel(job)
                elif job.finished is not None and now - job.finished > KEPT_FOR:
                    self.forget(job)
            with self.lock:
                idle = [k for k, r in self.kept.items() if now - r["seen"] > KEPT_RUN_FOR]
            for k in idle:
                self.let_go(k)

    def close(self):
        for e in self.engines.values():
            e.stop()
        shutil.rmtree(self.folder, ignore_errors=True)


# The engines and the page's token, made in `main` and read by every request.
ENGINES = None
TOKEN = None
PORT = None


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        **EXTRA_TYPES,
    }
    # Keep-alive. The page and its worker load some 270 modules, and under the
    # stdlib's HTTP/1.0 each was a connection of its own -- enough of them at
    # once that some were never accepted, a module failed to load with
    # ERR_CONNECTION_TIMED_OUT, and the worker reported only that it had
    # failed. Every response here carries a Content-Length, which is what
    # HTTP/1.1 needs to reuse a connection.
    protocol_version = "HTTP/1.1"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # The two headers a <meta> tag cannot carry. index.html holds the rest
        # of the policy, where it is next to the reasons for each entry;
        # anything serving this in earnest should send that one as a header
        # too, and these with it.
        # 'self', not 'none': the page next to this one (kompartment.html on
        # the site) frames the tool, and that is same-origin.
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        # One line per request, without the noisy timestamp prefix -- and none
        # for a page asking how its run is going five times a second.
        if self.path.startswith("/engine/jobs/") and "GET" in (self.requestline or "") \
                and not self.path.endswith("/archive"):
            return
        if self.path.startswith("/engine/runs/") and self.path.endswith(ASKED_OFTEN):
            return
        sys.stderr.write("  %s\n" % (fmt % args))

    # --- the page, with the engines' token in it ---------------------------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/engine/"):
            self._engine_get(path)
            return
        if path in ("/", "/index.html") and ENGINES is not None:
            self._page()
            return
        super().do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/engine/"):
            self._engine_post(path)
            return
        self.send_error(405)

    def _page(self):
        """index.html, telling the page the engines are here and how to ask them."""
        with open(os.path.join(ROOT, "index.html"), "rb") as f:
            html = f.read()
        tag = f'<meta name="kompartment-engines" content="{TOKEN}">'.encode()
        html = html.replace(b"<head>", b"<head>\n" + tag, 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    # --- the engines ---------------------------------------------------------

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        """From this machine, under this server's own name, with the page's token.

        The name matters as much as the token: a page elsewhere can point a
        name of its own at 127.0.0.1 and then ask as if it were this one.
        """
        names = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        if self.headers.get("Host") not in names:
            return "this server answers only to its own name"
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{n}" for n in names}:
            return "the request came from another page"
        if not TOKEN or not secrets.compare_digest(self.headers.get("X-Kompartment-Token", ""), TOKEN):
            return "the request does not carry this server's token"
        return None

    def _refuse(self, why):
        self._json(403, {"error": why})

    def _engine_get(self, path):
        why = self._allowed()
        if why:
            self._refuse(why)
            return
        if path == "/engine/info":
            self._json(200, ENGINES.info())
            return
        m = re.fullmatch(r"/engine/runs/([0-9a-f]+)/archive", path)
        if m:
            self._held_answer(ENGINES.ask(m.group(1), "archive"), "application/zip")
            return
        m = re.fullmatch(r"/engine/jobs/([0-9a-f]+)(/archive)?", path)
        job = ENGINES.get(m.group(1)) if m else None
        if job is None:
            self._json(404, {"error": "there is no such job — it may have finished long ago"})
            return
        if not m.group(2):
            # With the engine's own state, so that a job waiting for an engine
            # still loading says so rather than that it is queued.
            self._json(200, {**job.status(), "engineState": ENGINES.engines[job.engine].info()["state"]})
            return
        if job.state != "done":
            self._json(409, {"error": f"the job is {job.state}, not done"})
            return
        try:
            data = ENGINES.take(job)
        except OSError as e:
            self._json(410, {"error": f"the archive is gone: {e}"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _engine_post(self, path):
        why = self._allowed()
        if why:
            self._refuse(why)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MOST_BODY:
            self._json(413, {"error": "the model is larger than this server takes"})
            return
        body = self.rfile.read(length) if length else b""
        if path == "/engine/jobs":
            try:
                ask = json.loads(body or b"{}")
                model = ask.get("model")
                text = model if isinstance(model, str) else json.dumps(model)
                job = ENGINES.submit(ask.get("kind"), ask.get("engine"), str(ask.get("client") or ""),
                                     text, ask.get("options") or {})
            except (ValueError, TypeError) as e:
                self._json(400, {"error": str(e)})
                return
            self._json(202, job.status())
            return
        m = re.fullmatch(r"/engine/runs/([0-9a-f]+)/(series|forget|bands|realisations|column|realisation)", path)
        if m and m.group(2) == "forget":
            ENGINES.let_go(m.group(1))
            self._json(200, {"forgotten": m.group(1)})
            return
        if m and m.group(2) in SAMPLE_QUESTIONS:
            try:
                fields = sample_question(m.group(2), json.loads(body or b"{}"))
            except (ValueError, AttributeError, TypeError) as e:
                self._json(400, {"error": str(e)})
                return
            self._held_answer(ENGINES.ask(m.group(1), m.group(2), **fields), "application/octet-stream")
            return
        if m:
            try:
                labels = json.loads(body or b"{}").get("labels")
                if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
                    raise ValueError("ask for the series by their labels, a list of text")
            except (ValueError, AttributeError) as e:
                self._json(400, {"error": str(e)})
                return
            self._held_answer(ENGINES.ask(m.group(1), "series", labels=labels), "application/octet-stream")
            return
        m = re.fullmatch(r"/engine/clients/([0-9A-Za-z_-]+)/forget", path)
        if m:
            self._json(200, {"forgotten": ENGINES.let_go_of_client(m.group(1))})
            return
        m = re.fullmatch(r"/engine/jobs/([0-9a-f]+)/cancel", path)
        job = ENGINES.get(m.group(1)) if m else None
        if job is None:
            self._json(404, {"error": "there is no such job"})
            return
        ENGINES.cancel(job)
        self._json(200, job.status())


    def _held_answer(self, asked, kind):
        """What an engine wrote for a question about a run it holds, sent and then let go of."""
        if asked is None:
            self._json(404, {"error": "No engine holds that run any more: it was left unasked about for two hours, "
                                      "or the page has had a newer one since. Run it again."})
            return
        reply, path = asked
        try:
            if reply.get("event") != "done":
                self._json(410 if reply.get("gone") else 502,
                           {"error": reply.get("message") or "the engine could not answer", "name": reply.get("name")})
                return
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self._json(502, {"error": f"the engine's answer could not be read: {e}"})
            return
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def sample_question(op, asked):
    """The fields of a question about a held sample, checked: a series is a whole
    number, a time or a realisation one too, the percentiles numbers, and a mask
    0 or 1 for each realisation (or null, for all of them)."""
    def whole(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0

    fields = {k: asked.get(k) for k in SAMPLE_QUESTIONS[op]}
    if "series" in fields and not (isinstance(fields["series"], list) and all(whole(k) for k in fields["series"])):
        raise ValueError("ask for the series by their numbers, a list of whole numbers from 0")
    for k in ("at", "index"):
        if k in fields and not whole(fields[k]):
            raise ValueError(f"'{k}' is a whole number from 0")
    if op == "bands":
        p = fields["percentiles"]
        if not (isinstance(p, list) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)):
            raise ValueError("the percentiles are a list of numbers")
        mask = fields["mask"]
        if mask is not None and not (isinstance(mask, list) and all(v in (0, 1) for v in mask)):
            raise ValueError("the mask is 0 or 1 for each realisation, or null")
    return fields


class Server(socketserver.ThreadingTCPServer):
    # Restarting the server should not fail because the port is in TIME_WAIT.
    allow_reuse_address = True
    daemon_threads = True
    # The connections waiting to be accepted. The stdlib's 5 is overrun by a
    # browser opening a page's modules in parallel, and on macOS a connection
    # past the backlog is dropped without a word and times out.
    request_queue_size = 128


def python_engine(python, enabled):
    """The Python engine: this folder's package, run by `python`, which needs NumPy and SciPy."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        p for p in (os.path.join(ROOT, "python"), os.environ.get("PYTHONPATH")) if p)}
    why = None if enabled else "is switched off (--no-python)"
    if why is None:
        try:
            check = subprocess.run([python, "-c", "import numpy, scipy"], env=env, capture_output=True,
                                   timeout=120)
            if check.returncode:
                why = f"needs NumPy and SciPy, which {python} does not have"
        except (OSError, subprocess.TimeoutExpired) as e:
            why = f"could not be started with {python}: {e}"
    return Engine("python", [python, "-u", "-m", "kompartment.service"], env, why)


def julia_engine(julia, enabled):
    """The Julia engine: this folder's package, run by `julia` with every core and one more for listening."""
    project = os.path.join(ROOT, "julia")
    found = julia if os.path.sep in julia else shutil.which(julia)
    why = None
    if not enabled:
        why = "is switched off (--no-julia)"
    elif not found or not os.path.exists(found):
        why = "needs Julia, which is not installed here (or pass --julia PATH)"
    elif not os.path.exists(os.path.join(project, "Project.toml")):
        why = f"needs its package in {project}"
    return Engine("julia", [found or julia, f"--project={project}", "--threads=auto,1", "-e",
                            "using Kompartment; Kompartment.serve_stdio()"], dict(os.environ), why)


def arguments(argv):
    opts = {"port": 8080, "engine": "browser", "explicit": False, "python": sys.executable, "julia": "julia",
            "use_python": True, "use_julia": True}
    it = iter(argv)
    for a in it:
        if a == "--engine":
            opts["engine"] = next(it, "browser")
            opts["explicit"] = True
        elif a == "--python":
            opts["python"] = next(it, sys.executable)
        elif a == "--julia":
            opts["julia"] = next(it, "julia")
        elif a == "--no-python":
            opts["use_python"] = False
        elif a == "--no-julia":
            opts["use_julia"] = False
        elif a.isdigit():
            opts["port"] = int(a)
        else:
            raise SystemExit(f"serve.py: what is '{a}'? See the notes at the top of serve.py.")
    if opts["engine"] not in ("browser", "python", "julia"):
        raise SystemExit("serve.py: --engine is browser, python or julia")
    return opts


def main():
    global ENGINES, TOKEN, PORT
    opts = arguments(sys.argv[1:])
    port = PORT = opts["port"]
    os.chdir(ROOT)
    TOKEN = secrets.token_urlsafe(24)
    engines = {
        "python": python_engine(opts["python"], opts["use_python"]),
        "julia": julia_engine(opts["julia"], opts["use_julia"]),
    }
    ENGINES = Engines(engines, opts["engine"], tempfile.mkdtemp(prefix="kompartment-engines-"), opts["explicit"])
    # The engine the page starts on is started now, so its first run does not
    # wait for it to load.
    first = engines.get(opts["engine"])
    if first is not None:
        with first.lock:
            first.start()

    # Loopback only. `("", port)` binds every interface, and this server hands
    # out the whole project directory with listings on -- so on any shared
    # network (an office, a hotel, a conference) it published these files to
    # every host on the subnet. There is no reason a development server for a
    # single-user editor should be reachable from another machine.
    try:
        with Server(("127.0.0.1", port), NoCacheHandler) as httpd:
            print(f"Kompartment on http://localhost:{port}/")
            print(f"  serving {ROOT} (to this machine only)")
            print("  caching disabled, so a plain refresh picks up edits")
            for name, e in engines.items():
                said = "available" if e.why is None else f"not available: {e.why}"
                print(f"  {name} engine {said}{' (the page starts on it)' if name == opts['engine'] else ''}")
            print("  Ctrl+C to stop")
            httpd.serve_forever()
    except OSError as e:
        print(f"Could not listen on port {port}: {e}")
        print(f"Another server may already be running. Try: python3 serve.py {port + 1}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        ENGINES.close()


if __name__ == "__main__":
    main()
