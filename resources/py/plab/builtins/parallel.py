"""Parallel pools: parpool, gcp, getCurrentTask, and parfor loops run on
the pool's workers.

The workers are Python engines of their own (in the page, Web Workers next
to the one that runs the Command Window). For a parfor loop each worker
gets the loop's compiled module, the values of its broadcast and sliced
variables, and the files of the current folder and the path that changed
since the last loop; then blocks of passes as the workers come free. The
slices and the reductions' parts come back and are put together here in the
order of the passes, so the result is the one the loop gives run one pass
at a time; the files the passes wrote come back too.

The pool is a backend: the page's (the JavaScript module plabpool of the
engine's worker) or, in tests, one set with POOL.set_backend.
"""
import io
import json
import os
import pickle

import numpy as np

from . import bi
from ._util import err, nargchk, num, sval, is_str
from ..values import MError, Interrupt, NOVAL, COLON, Obj, FH, Struct, EMPTY, class_of
from .. import runtime as R

FILE_MAX = 32 << 20        # a file larger than this is not copied to the workers
FILES_MAX = 128 << 20      # nor more than this in all, before one loop
WORKERS_MAX = 8            # the default pool's size at most (one core stays with the Command Window)
CHUNKS_PER_WORKER = 4      # blocks of passes per worker: enough to even out passes of unequal length


# ---- values sent to the workers and back -------------------------------------------------

def _anon(pyfile, name, src, cap, nparams, vararg):
    """An anonymous function again: its compiled body when its module is here, else its text."""
    mod = R.MODULES.get(pyfile)
    fn = mod.ns.get(name) if mod is not None and mod.ns else None
    if fn is not None:
        return R.Anon(fn, src, cap, nparams, vararg)
    from .core import anon_from_text
    return anon_from_text(src, cap)


def _local(pyfile, name, fname):
    mod = R.MODULES.get(pyfile)
    fn = mod.ns.get(name) if mod is not None and mod.ns else None
    return R.NamedFH(fname, fn)


def _named(fname):
    return R.NamedFH(fname)


class _Pickler(pickle.Pickler):
    def reducer_override(self, obj):
        if isinstance(obj, R.Anon):
            fn = obj.fn
            return _anon, (fn.__code__.co_filename, fn.__name__, obj.src, obj.cap, obj.nparams, obj.vararg)
        if isinstance(obj, R.NamedFH):
            if obj.target is not None:
                t = obj.target
                return _local, (t.__code__.co_filename, t.__name__, obj.fname)
            return _named, (obj.fname,)
        if isinstance(obj, FH):
            raise TypeError(f'a function handle {obj.text()} cannot be sent to the workers')
        if isinstance(obj, Obj) and type(obj).__module__.endswith('graphics_base'):
            raise TypeError('graphics objects cannot be sent to the workers')
        return NotImplemented


def dumps(v):
    b = io.BytesIO()
    _Pickler(b, protocol=pickle.HIGHEST_PROTOCOL).dump(v)
    return b.getvalue()


def loads(b):
    return pickle.loads(b)


# ---- the pool --------------------------------------------------------------------------------

class _PagePool:
    """The page's pool: the engine's worker starts Web Workers (plabpool)."""

    def __init__(self, js):
        self.js = js

    def unavailable(self):
        return self.js.unavailable() or None

    def cores(self):
        return int(self.js.cores())

    async def start(self, n):
        return int(await self.js.start(n))

    def stop(self):
        self.js.stop()

    def size(self):
        return int(self.js.size())

    async def run(self, meta, ins, files, remove, use):
        from pyodide.ffi import to_js
        res = await self.js.run(meta, to_js(ins), to_js([[p, d] for p, d in files]), to_js(remove), use)

        def nothing(x):      # JavaScript's undefined comes as None, its null as JsNull
            return x is None or type(x).__name__ == 'JsNull'
        error = res.error
        return {'interrupted': bool(res.interrupted),
                'error': None if nothing(error) else {'identifier': str(error.identifier or ''), 'message': str(error.message or '')},
                'chunks': [None if nothing(c) else c.to_bytes() for c in res.chunks],
                'files': [(str(f[0]), f[1].to_bytes()) for f in res.files]}


class _Pool:
    def __init__(self):
        self._backend = None
        self._looked = False
        self.synced = {}           # path -> (mtime, size) the workers have
        self.warned = set()
        self.jobs = 0

    def set_backend(self, b):
        self._backend = b
        self._looked = True
        self.synced = {}

    def backend(self):
        if not self._looked:
            self._looked = True
            try:
                import plabpool
                self._backend = _PagePool(plabpool)
            except ImportError:
                self._backend = None
        return self._backend

    def default_size(self):
        b = self.backend()
        return max(1, min(b.cores() - 1, WORKERS_MAX)) if b else 0

    async def start(self, n):
        b = self.backend()
        why = b.unavailable() if b else 'there are no workers here'
        if why:
            raise err('parallel:pool:NotAvailable', f'A parallel pool cannot start: {why}.')
        R.write(f'Starting a parallel pool of {n} worker{"s" if n != 1 else ""}…\n', 'info')
        R.flush()
        got = await b.start(n)
        self.synced = {}
        if not got:
            raise err('parallel:pool:NotAvailable', 'The parallel pool did not start.')
        R.write(f'The pool has {got} worker{"s" if got != 1 else ""}.\n', 'info')
        return got

    def stop(self):
        b = self.backend()
        if b and b.size():
            b.stop()
        self.synced = {}

    def size(self):
        b = self.backend()
        return b.size() if b else 0

    def scan(self):
        """The files the workers get: the current folder's (and its folders', three levels
        down) and the program files of the path's folders, by path: (mtime, size)."""
        out = {}

        def walk(d, depth, programs_only):
            try:
                entries = list(os.scandir(d))
            except OSError:
                return
            for e in entries:
                if e.name.startswith('.'):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth < 3 and not programs_only:
                            walk(e.path, depth + 1, programs_only)
                    elif e.is_file(follow_symlinks=False) and (not programs_only or e.name.endswith('.m')):
                        st = e.stat()
                        out[e.path] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue
        walk(R.STATE['cwd'], 0, False)
        for d in R.STATE['path']:
            walk(d, 0, True)
        return out

    def files_to_send(self):
        now = self.scan()
        send, skipped, total = [], [], 0
        for p, stamp in sorted(now.items()):
            if self.synced.get(p) == stamp:
                continue
            size = stamp[1]
            if size > FILE_MAX or total + size > FILES_MAX:
                skipped.append(p)
                continue
            try:
                with open(p, 'rb') as f:
                    data = f.read()
            except OSError:
                continue
            send.append((p, data))
            total += size
            self.synced[p] = stamp
        remove = [p for p in self.synced if p not in now]
        for p in remove:
            del self.synced[p]
        fresh = [p for p in skipped if p not in self.warned]
        if fresh:
            self.warned.update(fresh)
            R.warn('parallel:files:NotCopied', f'{len(fresh)} file{"s" if len(fresh) != 1 else ""} over 32 MB (or past 128 MB in all) '
                   f'{"were" if len(fresh) != 1 else "was"} not copied to the workers, so the passes cannot read '
                   f'{"them" if len(fresh) != 1 else "it"}: {", ".join(os.path.basename(p) for p in fresh[:3])}'
                   f'{" and more" if len(fresh) > 3 else ""}.')
        return send, remove


POOL = _Pool()


# ---- parfor ----------------------------------------------------------------------------------

def _passes(vals):
    """(first, count) when the loop's values are whole numbers going up by one, else None."""
    if isinstance(vals, R.LoopRange):
        return (vals.first, vals.count) if vals.step == 1 or vals.count <= 1 else None
    ks = list(vals)
    if not all(type(k) is float and k == int(k) for k in ks):
        return None
    if any(ks[i + 1] != ks[i] + 1 for i in range(len(ks) - 1)):
        return None
    return (int(ks[0]), len(ks)) if ks else (0, 0)


def _blocks(first, count, workers):
    size = max(1, -(-count // (workers * CHUNKS_PER_WORKER)))
    return [[first + i, min(size, count - i)] for i in range(0, count, size)]


async def run_parfor(W, fn, plan, vals, maxw):
    b = POOL.backend()
    if b is None:
        return False
    mod = R.MODULES.get(fn.__code__.co_filename)
    if mod is None:
        return False
    limit = None
    if maxw is not None:
        limit = int(num(maxw))
        if limit <= 0:
            return False             # parfor (k = 1:n, 0): here, one pass at a time
    where = mod.path
    noted = fn.__globals__['_PF_NOTED']
    first_py = fn.__code__.co_firstlineno       # the chunk function's def carries the loop's line
    line = mod.linemap[first_py - 1] if 0 < first_py <= len(mod.linemap) else 0
    passes = _passes(vals)
    if passes is None:
        R.parfor_note('its values are not whole numbers going up by one', line, where, noted)
        return False
    first, count = passes
    if count == 0:
        return False
    why = b.unavailable()
    if why:
        R.parfor_note(why, line, where, noted)
        return False
    ins = {}
    # names that were no variables when the loop was compiled, but are now (made by load), go as broadcast
    for n in list(plan['broadcast']) + [s[0] for s in plan['sliced']] + list(plan['dyn']):
        v = W.get(n, NOVAL)
        if v is not NOVAL:
            ins[n] = v
    reds = plan['reductions']
    if any(n not in W for n, _, _ in reds):
        return False                 # one pass at a time says what is missing
    try:
        blob = dumps(ins)
    except (TypeError, AttributeError, pickle.PicklingError, RecursionError) as e:
        R.parfor_note(f'a value cannot be sent to the workers ({e})', line, where, noted)
        return False
    try:
        workers = POOL.size() or await POOL.start(POOL.default_size())
    except MError as e:
        R.parfor_note(f'the parallel pool did not start ({e.message})', line, where, noted)
        return False
    use = min(workers, limit) if limit else workers
    blocks = _blocks(first, count, use)
    files, remove = POOL.files_to_send()
    POOL.jobs += 1
    meta = json.dumps({
        'job': POOL.jobs, 'fn': fn.__name__, 'blocks': blocks, 'total': count,
        'module': {'pyfile': fn.__code__.co_filename, 'path': mod.path, 'name': mod.name, 'kind': mod.kind,
                   'text': mod.text, 'src': mod.src, 'linemap': list(mod.linemap)},
        'cwd': R.STATE['cwd'], 'path': list(R.STATE['path']), 'seed': int.from_bytes(os.urandom(4), 'little') >> 1,
    })
    R.flush()
    res = await b.run(meta, blob, files, remove, use)
    if res['interrupted']:
        raise Interrupt()
    if res['error']:
        e = res['error']
        raise MError(e.get('identifier') or '', e.get('message') or 'A pass of the parfor loop failed.')
    _write_back(res['files'])
    k = plan['var']
    for block, data in zip(blocks, res['chunks']):
        part = loads(data)
        ks = [float(x) for x in range(block[0], block[0] + block[1])]
        for name, brace, pattern in plan['sliced']:
            for kk, v in zip(ks, part['slices'][name]):
                if v is None:
                    continue
                args = tuple(kk if p == 'k' else COLON if p == ':' else float(p) for p in pattern)
                cur = W.get(name, NOVAL)
                W[name] = R.casgn(cur, args, v) if brace else R.asgn(cur, args, v)
        for name, op, prefix in reds:
            p = part['reds'][name]
            if p is not None:
                W[name] = R.red_join('+' if op == '-' else op, prefix, W[name], p)
    W[k] = float(first + count - 1)
    return True


def _write_back(files):
    """The files the passes wrote, into this file system (they go to the workers again
    before the next loop)."""
    home = R.STATE.get('home', '/home/user')
    wrote = set()
    for path, data in files:
        p = os.path.normpath(path)
        if not (p == home or p.startswith(home.rstrip('/') + '/')):
            continue
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(data)
            wrote.add(os.path.dirname(p))
        except OSError:
            continue
    if wrote:
        from .iofun import files_changed
        files_changed(R.STATE['cwd'])


# ---- the pool as a value ---------------------------------------------------------------------

class PoolObj(Obj):
    """What parpool and gcp give: the running pool."""
    __slots__ = ()
    cls = 'parallel.Pool'
    is_handle = True

    def getprop(self, name):
        if name == 'NumWorkers':
            return float(POOL.size())
        if name == 'Connected':
            return POOL.size() > 0
        return super().getprop(name)

    def propnames(self):
        return ['NumWorkers', 'Connected']

    def display_lines(self):
        return ['  parallel.Pool with properties:', '', f'    NumWorkers: {POOL.size()}',
                f'     Connected: {"true" if POOL.size() else "false"}']

    def delete_handle(self):
        POOL.stop()


@bi('parpool', aw=True, arr=False)
async def parpool(nargout, *args):
    nargchk(args, 0, 2, 'parpool')
    n = None
    for a in args:
        if is_str(a):
            continue                 # a cluster profile: there is one kind of pool here
        n = int(num(a))
        if n < 1:
            raise err('parallel:pool:InvalidNumWorkers', 'The number of workers must be a whole number of at least 1.', 'parpool')
    if POOL.size():
        raise err('parallel:convenience:ConnectionOpen', 'A parallel pool is running already: delete(gcp) stops it.', 'parpool')
    await POOL.start(min(n, 32) if n else POOL.default_size())
    return PoolObj()


@bi('gcp', aw=True, arr=False)
async def gcp(nargout, *args):
    nargchk(args, 0, 1, 'gcp')
    nocreate = bool(args) and sval(args[0], 'option', 'gcp').lower() == 'nocreate'
    if POOL.size():
        return PoolObj()
    if nocreate or POOL.backend() is None:
        return EMPTY()
    await POOL.start(POOL.default_size())
    return PoolObj()


@bi('getCurrentTask')
def getCurrentTask(nargout, *args):
    nargchk(args, 0, 0, 'getCurrentTask')
    i = R.STATE.get('pool_index')
    return Struct.scalar({'ID': float(i)}) if i else EMPTY()
