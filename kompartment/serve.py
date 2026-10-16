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
a run -- Run, and a probabilistic run -- to the Python engine
(`python/kompartment`) or the Julia one (`julia/`), chosen in the page beside
Run; `--engine` says which the page starts on. Each engine is a process of its
own, started the first time it is asked for and kept: a line of JSON a message,
jobs in and progress out (see python/kompartment/service.py). A run comes back
as the archive *Save with results* writes, which the page reads the way it
reads a file somebody opened.

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
        self.current = None
        self.lock = threading.RLock()
        self.restarts = 0

    def info(self):
        with self.lock:
            if self.why:
                state = "unavailable"
            elif self.proc is None:
                state = "stopped"
            elif self.ready is None:
                state = "starting"
            else:
                state = "busy" if self.current else "idle"
            return {"available": self.why is None, "why": self.why, "state": state, "detail": self.ready,
                    "queued": len(self.queue)}

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
            job = self.current
            self.current = None
            if job is not None and job.state == "running":
                if job.stopping:
                    job.end("cancelled")
                else:
                    job.error = {"name": "EngineError", "message": f"The {self.name} engine stopped during the run.",
                                 "block": None, "hint": "Its console output, where the server runs, may say why."}
                    job.end("error")
            if self.queue:
                self.start()

    def _heard(self, proc, event):
        with self.lock:
            if self.proc is not proc:
                return
            if event.get("event") == "ready":
                self.ready = {k: v for k, v in event.items() if k != "event"}
                self._pump()
                return
            job = self.current
            if job is None or event.get("id") != job.id:
                return
            kind = event.get("event")
            if kind == "stage":
                job.stage = event.get("stage")
            elif kind == "progress":
                job.progress = {k: event[k] for k in ("fraction", "at", "done", "total") if k in event}
            elif kind in ("done", "error", "cancelled"):
                if kind == "error":
                    job.error = {k: event.get(k) for k in ("name", "message", "block", "hint")}
                job.ms = event.get("ms")
                job.end(kind)
                self.current = None
                self._pump()

    def _pump(self):
        """The next job, if the engine is free. Called with the lock held."""
        if self.current is not None or self.ready is None or self.proc is None:
            return
        while self.queue:
            job = self.queue.popleft()
            if job.state != "queued":
                continue
            job.state = "running"
            job.stage = "starting"
            self.current = job
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
                self.current = None
                continue
            job.model = None
            return

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
            if job.state != "running" or self.current is not job or self.proc is None:
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
            # job starts it again.
            with self.lock:
                if self.current is job and self.proc is proc:
                    self.restarts += 1
                    try:
                        proc.kill()
                    except OSError:
                        pass

        threading.Timer(GRACE, end_if_still).start()

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
        self.lock = threading.Lock()
        threading.Thread(target=self._sweep, daemon=True).start()

    def info(self):
        return {"default": self.default, "explicit": self.explicit,
                "engines": {n: e.info() for n, e in self.engines.items()}}

    def submit(self, kind, engine, client, model, options):
        if engine not in self.engines:
            raise ValueError(f"There is no engine called '{engine}' here.")
        if kind not in ("run", "probabilistic"):
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
        """The archive of a finished job, read once and then let go of."""
        try:
            with open(job.out, "rb") as f:
                data = f.read()
        finally:
            self.forget(job)
        return data

    def forget(self, job):
        with self.lock:
            self.jobs.pop(job.id, None)
        try:
            os.remove(job.out)
        except OSError:
            pass

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
        m = re.fullmatch(r"/engine/jobs/([0-9a-f]+)/cancel", path)
        job = ENGINES.get(m.group(1)) if m else None
        if job is None:
            self._json(404, {"error": "there is no such job"})
            return
        ENGINES.cancel(job)
        self._json(200, job.status())


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
