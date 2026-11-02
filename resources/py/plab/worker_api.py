"""What the page's worker calls: run commands, answer questions, describe
the workspace and the files, and drive the debugger.

Everything the page is told goes through post(json text), a JavaScript
function the worker registers as the module `plabjs`.
"""
import asyncio
import json
import math
import os
import sys
import time

import numpy as np

from . import runtime as R
from . import display as D
from .values import (MError, Interrupt, Char, Cell, Struct, Str, FH, Obj, NOVAL, class_of, shape_of, numel, size_str)

_post = None
_futures = {}
_seq = [0]
HOME = '/home/user'


def post(msg):
    if _post is not None:
        _post(json.dumps(msg, allow_nan=True, default=_json_default))


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def setup(post_fn, home=HOME):
    """Start the session: the builtins, the hooks, the home folder."""
    global _post
    _post = post_fn
    R.setup()
    R.OUT_HOOK[0] = lambda text, kind: post({'type': 'out', 'text': text, 'kind': kind})
    R.EVENT_HOOK[0] = _event
    R.INPUT_HOOK[0] = _ask_input
    R.PAGE_HOOK[0] = _ask_page
    R.DEBUGGER = Debugger()
    os.makedirs(home, exist_ok=True)
    R.STATE['cwd'] = home
    R.STATE['home'] = home
    from .builtins.uifun import write_icons
    write_icons()
    names = sorted(n for n in R.BUILTINS if n.replace('.', '').replace('_', '').isalnum() and n[0].isalpha())
    return json.dumps({'builtins': names, 'cwd': home})


def _event(e):
    t = e.get('type')
    if t == 'drawnow':
        R.flush()
        R.flush_figures()
        return
    post(e)


def _future():
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    _seq[0] += 1
    _futures[_seq[0]] = fut
    return _seq[0], fut


async def _ask_input(prompt, kind):
    R.flush()
    R.flush_figures()
    i, fut = _future()
    post({'type': 'input', 'id': i, 'prompt': prompt, 'kind': kind})
    try:
        return await fut
    finally:
        _futures.pop(i, None)


async def _ask_page(request):
    R.flush()
    i, fut = _future()
    request = dict(request)
    request['id'] = i
    post({'type': 'request', 'request': request})
    try:
        return await fut
    finally:
        _futures.pop(i, None)


def reply(i, value_json):
    """The page answered a question (input, a picture, clicks)."""
    fut = _futures.get(int(i))
    if fut is not None and not fut.done():
        v = json.loads(value_json)
        if isinstance(v, dict) and v.get('interrupt'):
            fut.set_exception(Interrupt())
        else:
            fut.set_result(v)


def interrupt():
    R.INTERRUPT[0] = True
    # a question waiting for an answer gives up at once
    for fut in list(_futures.values()):
        if not fut.done():
            fut.set_exception(Interrupt())


# ---- running ---------------------------------------------------------------------------

async def run(code, opts_json='{}'):
    """A command line (or a section, or a selection): output streams as it
    comes; the workspace and figures follow at the end."""
    opts = json.loads(opts_json)
    R.INTERRUPT[0] = False
    R._TICK[1] = time.perf_counter()
    silent = opts.get('silent', False)
    saved_hook = R.OUT_HOOK[0]
    if silent:
        R.OUT_HOOK[0] = lambda text, kind: (post({'type': 'out', 'text': text, 'kind': kind}) if kind in ('err', 'internal') else None)
    ok = False
    try:
        if opts.get('callbacks'):
            from . import uievents
            ok = await uievents.run_queued()
        else:
            ok = await R.execute(code, R.BASE)
    finally:
        R.flush()
        R.OUT_HOOK[0] = saved_hook
        try:
            R.flush_figures()
        except Exception as e:
            post({'type': 'out', 'text': f'Warning: figures could not be sent: {e}\n', 'kind': 'warn'})
        R.DEBUGGER.end_run()
    from .uievents import QUEUE
    return json.dumps({'ok': ok, 'ws': workspace(R.BASE), 'cwd': R.STATE['cwd'], 'format': dict(D.FMT), 'pending': len(QUEUE)})


def workspace(W=None):
    """The rows of the Workspace browser."""
    W = W if W is not None else R.BASE
    rows = []
    for name in sorted(W.keys(), key=lambda s: (s.lower(), s)):
        v = W[name]
        try:
            preview = D.value_preview(v)
        except Exception:
            preview = '?'
        sh = shape_of(v)
        rows.append({'name': name, 'value': preview, 'size': size_str(sh), 'class': class_of(v),
                     'complex': bool(type(v) is complex or (type(v) is np.ndarray and v.dtype.kind == 'c')),
                     'numel': int(numel(v)), 'global': name in getattr(W, 'gnames', ()),
                     'minmax': _minmax(v)})
    for name in sorted(getattr(W, 'gnames', ())):
        if name in R.GLOBALS and name not in W:
            v = R.GLOBALS[name]
            rows.append({'name': name, 'value': D.value_preview(v), 'size': size_str(shape_of(v)), 'class': class_of(v),
                         'complex': False, 'numel': int(numel(v)), 'global': True, 'minmax': _minmax(v)})
    return rows


def _minmax(v):
    try:
        if type(v) is np.ndarray and v.size and v.dtype.kind in 'fiub':
            a = v.astype(float)
            a = a[np.isfinite(a)]
            if a.size:
                return [float(a.min()), float(a.max())]
        if type(v) is float:
            return [v, v]
    except Exception:
        pass
    return None


def workspace_json():
    return json.dumps(workspace(R.DEBUGGER.paused_ws() or R.BASE))


# ---- completion ------------------------------------------------------------------------------

def complete(text, pos):
    """Names that complete the word before pos: variables, functions, files,
    fields after a dot."""
    import re
    before = text[:pos]
    m = re.search(r'([A-Za-z][\w]*(?:\.[A-Za-z]\w*)*\.?)$', before)
    if not m:
        # a file name in a quoted argument
        q = re.search(r"'([^']*)$", before)
        if q:
            return json.dumps({'start': pos - len(q.group(1)), 'items': _file_items(q.group(1))})
        return json.dumps({'start': pos, 'items': []})
    word = m.group(1)
    start = pos - len(word)
    W = R.DEBUGGER.paused_ws() or R.BASE
    items = []
    if '.' in word:
        base, _, part = word.rpartition('.')
        try:
            v = W
            parts = base.split('.')
            v = W[parts[0]] if parts[0] in W else None
            for p in parts[1:]:
                v = R.fld1(v, p) if v is not None else None
            if type(v) is Struct:
                names = list(v.f)
            elif isinstance(v, Obj):
                names = v.propnames()
            else:
                names = []
        except Exception:
            names = []
        items = [{'label': n, 'kind': 'field'} for n in names if n.startswith(part)]
        return json.dumps({'start': pos - len(part), 'items': items[:200]})
    for n in sorted(W.keys()):
        if n.startswith(word):
            items.append({'label': n, 'kind': 'variable'})
    seen = set(i['label'] for i in items)
    try:
        for d in R.search_dirs():
            for f in sorted(os.listdir(d)):
                if f.endswith('.m') and f[:-2].startswith(word) and f[:-2] not in seen:
                    items.append({'label': f[:-2], 'kind': 'file'})
                    seen.add(f[:-2])
    except OSError:
        pass
    from .lexer import KEYWORDS
    for k in sorted(KEYWORDS):
        if k.startswith(word) and k not in seen:
            items.append({'label': k, 'kind': 'keyword'})
            seen.add(k)
    for n in sorted(R.BUILTINS):
        if n.startswith(word) and n not in seen and n[0].isalpha() and not n.endswith('_'):
            items.append({'label': n, 'kind': 'function'})
            seen.add(n)
    return json.dumps({'start': start, 'items': items[:300]})


def _file_items(prefix):
    d, _, part = prefix.rpartition('/')
    folder = os.path.join(R.STATE['cwd'], d) if not d.startswith('/') else (d or '/')
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for n in names:
        if n.startswith(part) and not n.startswith('.'):
            full = os.path.join(folder, n)
            out.append({'label': n + ('/' if os.path.isdir(full) else ''), 'kind': 'folder' if os.path.isdir(full) else 'file'})
    return out[:200]


# ---- the variable editor --------------------------------------------------------------------------

def _cell_text(x):
    t = type(x)
    if t is float:
        if x != x:
            return 'NaN'
        if x in (math.inf, -math.inf):
            return 'Inf' if x > 0 else '-Inf'
        if x == int(x) and abs(x) < 1e10:
            return str(int(x))
        s = f'{x:.5g}' if 1e-4 <= abs(x) < 1e5 else f'{x:.4e}'
        return s
    if t is bool:
        return '1' if x else '0'
    if t is complex:
        return D._inline_complex(x)
    return D.summary(x, '{}')


def var_view(name, r0=0, c0=0, nr=200, nc=60):
    """A block of a variable for the variable editor."""
    W = R.DEBUGGER.paused_ws() or R.BASE
    path = name
    try:
        if name in W:
            v = W[name]
        else:
            fn, mod = R.compile_command('plabTmpView = ' + name + ';', W)
            ws = R.Workspace('view')
            ws.update(W)
            R.run_sync(fn(ws))
            v = ws['plabTmpView']
    except Exception as e:
        return json.dumps({'error': str(e)})
    sh = shape_of(v)
    t = type(v)
    res = {'name': path, 'size': size_str(sh), 'class': class_of(v), 'shape': list(sh)}
    if t is Struct and v.size == 1:
        res['kind'] = 'struct'
        res['fields'] = [{'name': k, 'value': D.summary(v.get1(k)), 'size': size_str(shape_of(v.get1(k))), 'class': class_of(v.get1(k)),
                          'open': type(v.get1(k)) in (Struct, Cell, np.ndarray, Char) and numel(v.get1(k)) > 1} for k in v.f]
        return json.dumps(res)
    if isinstance(v, Obj) and not hasattr(v, 'a'):
        res['kind'] = 'object'
        rows = []
        for k in v.propnames()[:200]:
            try:
                rows.append({'name': k, 'value': D.summary(v.getprop(k)), 'class': class_of(v.getprop(k))})
            except Exception:
                pass
        res['fields'] = rows
        return json.dumps(res)
    if len(sh) > 2:
        res['kind'] = 'nd'
        res['note'] = 'Arrays of more than two dimensions are shown one page at a time: index a page, e.g. ' + name + '(:,:,1).'
        return json.dumps(res)
    rows, cols = sh
    res['kind'] = 'grid'
    res['r0'] = r0
    res['c0'] = c0
    cells = []
    if t in (float, bool, complex):
        get = lambda i, j: v
    elif t is np.ndarray:
        get = lambda i, j: (v.item(i, j) if v.dtype.kind in 'fbc' and v.dtype.itemsize in (1, 8, 16) else v[i:i + 1, j:j + 1])
    elif t is Char:
        get = lambda i, j: Char(v.a[i:i + 1, j:j + 1])
        res['kind'] = 'grid'
    elif t is Cell:
        get = lambda i, j: v.a[i, j]
    elif t is Struct:
        res['kind'] = 'structarray'
        res['fields'] = list(v.f)
        for i in range(r0, min(rows * cols, r0 + nr)):
            cells.append([D.summary(v.f[k].reshape(-1, order='F')[i]) for k in v.f])
        res['cells'] = cells
        return json.dumps(res)
    elif t is Str:
        get = lambda i, j: Str.of(v.a[i, j])
    else:
        get = lambda i, j: v
    for i in range(r0, min(rows, r0 + nr)):
        row = []
        for j in range(c0, min(cols, c0 + nc)):
            x = get(i, j)
            if t is Char:
                row.append(chr(int(v.a[i, j])))
            elif t is np.ndarray and v.dtype.kind in 'iu':
                row.append(str(int(v[i, j])))
            elif t is np.ndarray and v.dtype == np.float32:
                row.append(_cell_text(float(v[i, j])))
            else:
                row.append(_cell_text(x))
        cells.append(row)
    res['cells'] = cells
    res['editable'] = t in (float, bool, np.ndarray) and (t is not np.ndarray or v.dtype.kind in 'fbiu')
    return json.dumps(res)


# ---- files -----------------------------------------------------------------------------------

def list_dir(path):
    try:
        names = os.listdir(path)
    except OSError as e:
        return json.dumps({'error': str(e), 'path': path})
    items = []
    for n in names:
        if n.startswith('.'):
            continue
        p = os.path.join(path, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        isdir = os.path.isdir(p)
        items.append({'name': n, 'dir': isdir, 'size': 0 if isdir else st.st_size, 'mtime': st.st_mtime,
                      'kind': 'folder' if isdir else _file_kind(n)})
    items.sort(key=lambda d: (not d['dir'], d['name'].lower()))
    return json.dumps({'path': path, 'items': items})


def _file_kind(n):
    ext = os.path.splitext(n)[1].lower()
    if ext == '.m':
        return 'mfile'
    if ext == '.mat':
        return 'mat'
    if ext == '.fig':
        return 'fig'
    if ext in ('.png', '.jpg', '.jpeg', '.svg', '.gif'):
        return 'image'
    if ext in ('.txt', '.csv', '.dat', '.json', '.md', '.tsv'):
        return 'text'
    return 'other'


def file_info(path):
    """What the Details panel shows for a file: a program's help comment, a
    MAT-file's variables."""
    info = {'path': path}
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == '.m':
            with open(path, encoding='utf-8', errors='replace') as f:
                text = f.read(20000)
            info['help'] = help_comment(text)
            info['kind'] = 'function' if text.lstrip().startswith('function') else 'script'
        elif ext == '.mat':
            from . import matfile
            if matfile.kind(path) == 'v73':
                try:
                    import h5py  # noqa: F401
                except ImportError:
                    # the worker loads it and asks again
                    return json.dumps({'path': path, 'need': 'h5py'})
            info['vars'] = [{'name': matfile.shown(k), 'size': size_str(sz) if sz else '', 'class': matfile.shown(c)} for k, sz, c in matfile.variables(path)]
    except Exception as e:
        info['error'] = str(e)
    return json.dumps(info)


def help_comment(text):
    lines = text.split('\n')
    out = []
    started = False
    for line in lines:
        s = line.strip()
        if not started:
            if s.startswith('function') or not s:
                continue
            if s.startswith('%'):
                started = True
            else:
                break
        if started:
            if s.startswith('%'):
                out.append(s[1:].rstrip()[1:] if s.startswith('% ') or s.startswith('%') and len(s) > 1 and s[1] == ' ' else s[1:])
            else:
                break
    return '\n'.join(out)


def files_changed():
    R.bump_epoch()


def set_cwd(path):
    if os.path.isdir(path):
        R.STATE['cwd'] = path
        R.bump_epoch()
        return True
    return False


# ---- code checks and the compiled Python -------------------------------------------------------------

def lint(text):
    from .parser import parse, assigned_names
    from .lexer import LexError
    names = assigned_names(text)
    try:
        parse(text, lambda n: n in names, 'file')
        return json.dumps([])
    except MError as e:
        return json.dumps([{'line': getattr(e, 'line', 1) or 1, 'pos': getattr(e, 'pos', None), 'message': e.message}])


def python_of(path, text):
    """The Python a file compiles to (as this session would run it)."""
    from .compiler import compile_source
    try:
        src, linemap, prog = compile_source(text, R.BUILTINS, kind='file', user_funcs=R._user_file,
                                            modname=os.path.splitext(os.path.basename(path or 'untitled.m'))[0], path=path or '',
                                            debug=False)
        return json.dumps({'ok': True, 'python': src, 'map': linemap})
    except MError as e:
        return json.dumps({'ok': False, 'message': e.message, 'line': getattr(e, 'line', None)})


def set_format(fmt_json):
    D.FMT.update(json.loads(fmt_json))


def help_text(name):
    from .help import help_for
    return json.dumps(help_for(name))


# ---- figures ------------------------------------------------------------------------------------

def figure_event(ev_json):
    """Something happened to a figure window on the page."""
    from .graphics_base import STORE, Figure, Axes
    ev = json.loads(ev_json)
    t = ev.get('type')
    obj = STORE.objects.get(ev.get('id'))
    if t == 'close':
        if obj is not None and obj.valid:
            obj.delete_handle()
            STORE.closed.clear()
    elif t == 'current':
        if isinstance(obj, Figure) and obj.valid and obj.props['HandleVisibility'] == 'on':
            STORE.current = obj
    elif t == 'resize':
        if isinstance(obj, Figure) and obj.valid:
            pos = obj.props['Position'].reshape(-1).copy()
            pos[2], pos[3] = float(ev['width']), float(ev['height'])
            obj.props['Position'] = pos.reshape(1, 4)
    elif t == 'limits':
        if isinstance(obj, Axes) and obj.valid:
            for k in ('XLim', 'YLim', 'ZLim'):
                v = ev.get(k.lower())
                if v is not None:
                    obj.props[k] = np.array([v], float)
                    obj.props[k + 'Mode'] = 'manual'
            if ev.get('reset'):
                for k in ('XLim', 'YLim', 'ZLim'):
                    obj.props[k + 'Mode'] = 'auto'
    elif t == 'view':
        if isinstance(obj, Axes) and obj.valid:
            obj.props['View'] = np.array([ev['view']], float)
    elif t == 'currentaxes':
        if isinstance(obj, Axes) and obj.valid:
            f = obj.figure()
            f.props['CurrentAxes'] = obj if obj.yy_owner is None else obj.yy_owner
    return True


def ui_event(ev_json):
    """Something a person did in a figure: what it sets is set at once (and
    the page told); the callbacks it queues run when the page asks for
    them, or sooner, at a running program's drawnow or pause."""
    from . import uievents
    n = uievents.handle(json.loads(ev_json))
    try:
        R.flush_figures()
    except Exception:
        pass
    return json.dumps({'queued': n})


def all_figures():
    """Every open figure, for a page that (re)starts."""
    from .graphics_base import STORE, serialize_figure
    return json.dumps([serialize_figure(f) for f in sorted(STORE.figures.values(), key=lambda f: f.order) if f.valid])


# ---- the debugger --------------------------------------------------------------------------------------

class DebugQuit(BaseException):
    pass


class Debugger:
    """Breakpoints by file and line; stepping over, in and out; a K>> prompt
    that runs commands in the paused function's workspace."""

    def __init__(self):
        self.breakpoints = {}       # path -> set of lines
        self.stepping = None        # None, 'over', 'in', 'out'
        self.step_depth = 0
        self.pause_requested = False
        self.paused = None          # (W, path, line) while paused
        self.stop_on_error = False

    @property
    def active(self):
        return bool(self.breakpoints) or self.stepping is not None or self.pause_requested

    def wants(self, path):
        return path in self.breakpoints or self.stepping is not None or self.pause_requested

    def refresh_modules(self):
        on_all = self.stepping is not None or self.pause_requested
        for mod in list(R.MODULES.values()):
            ns = getattr(mod, 'ns', None)
            if ns is not None:
                ns['T_'] = on_all or (mod.path in self.breakpoints)
            for v in (getattr(mod, 'variants', None) or {}).values():
                v[1].ns['T_'] = on_all or (mod.path in self.breakpoints)

    def set_breakpoints(self, path, lines):
        if lines:
            self.breakpoints[path] = set(int(x) for x in lines)
        else:
            self.breakpoints.pop(path, None)
        self.refresh_modules()

    def depth(self):
        f = sys._getframe(1)
        n = 0
        while f is not None:
            if f.f_code.co_filename.startswith('<plab:') and (f.f_code.co_name.startswith('LF_') or f.f_code.co_name == 'SCRIPT'):
                n += 1
            f = f.f_back
        return n

    def paused_ws(self):
        return self.paused[0] if self.paused else None

    def end_run(self):
        self.stepping = None
        self.pause_requested = False
        self.paused = None
        self.refresh_modules()

    async def hook(self, W, line, mod):
        stop = False
        if self.pause_requested:
            stop = True
            self.pause_requested = False
        elif mod in self.breakpoints and line in self.breakpoints[mod]:
            stop = True
        elif self.stepping is not None:
            d = self.depth()
            if self.stepping == 'in':
                stop = True
            elif self.stepping == 'over':
                stop = d <= self.step_depth
            elif self.stepping == 'out':
                stop = d < self.step_depth
        if not stop or mod == 'command':
            return
        await self.pause(W, line, mod)

    async def keyboard(self, W):
        f = sys._getframe(1)
        line, mod = 0, 'command'
        while f is not None:
            fn = f.f_code.co_filename
            if fn.startswith('<plab:') and fn in R.MODULES:
                m = R.MODULES[fn]
                line = m.linemap[f.f_lineno - 1] if 0 < f.f_lineno <= len(m.linemap) else 0
                mod = m.path
                break
            f = f.f_back
        await self.pause(W, line, mod)

    async def pause(self, W, line, mod):
        R.flush()
        R.flush_figures()
        self.paused = (W, mod, line)
        depth = self.depth()
        stack = R.stack_of_frames()
        post({'type': 'dbg', 'state': 'paused', 'file': mod, 'line': line, 'stack': stack, 'ws': workspace(W)})
        try:
            while True:
                i, fut = _future()
                post({'type': 'dbgwait', 'id': i})
                try:
                    cmd = await fut
                finally:
                    _futures.pop(i, None)
                kind = cmd.get('cmd')
                if kind == 'eval':
                    text = cmd.get('text', '')
                    try:
                        await R.execute(text, W)
                    except Interrupt:
                        R.write('Operation terminated by user.\n', 'err')
                    R.flush()
                    R.flush_figures()
                    post({'type': 'dbg', 'state': 'evaluated', 'ws': workspace(W)})
                    continue
                if kind == 'continue':
                    self.stepping = None
                elif kind == 'step':
                    self.stepping = 'over'
                    self.step_depth = depth
                elif kind == 'stepin':
                    self.stepping = 'in'
                    self.step_depth = depth
                elif kind == 'stepout':
                    self.stepping = 'out'
                    self.step_depth = depth
                elif kind == 'quit':
                    self.stepping = None
                    raise Interrupt()
                break
        finally:
            self.paused = None
            self.refresh_modules()
            post({'type': 'dbg', 'state': 'running'})


def debug_command(cmd_json):
    """continue / step / stepin / stepout / quit / eval while paused, or
    pause a running program."""
    cmd = json.loads(cmd_json)
    if cmd.get('cmd') == 'pause':
        R.DEBUGGER.pause_requested = True
        R.DEBUGGER.refresh_modules()
        return True
    return False


def set_breakpoints(path, lines_json):
    R.DEBUGGER.set_breakpoints(path, json.loads(lines_json))
    return True


# ---- a worker of the parallel pool --------------------------------------------------------------

_JOB = {}


def pool_setup(post_fn, home=HOME, index=1):
    """A worker of the parallel pool: what its passes print goes to the
    Command Window; figures, input() and the debugger stay with the client."""
    global _post
    _post = post_fn
    R.setup()
    R.OUT_HOOK[0] = lambda text, kind: post({'type': 'out', 'text': text, 'kind': kind})
    R.EVENT_HOOK[0] = None
    R.INPUT_HOOK[0] = None
    R.PAGE_HOOK[0] = None
    os.makedirs(home, exist_ok=True)
    R.STATE['cwd'] = home
    R.STATE['home'] = home
    R.STATE['pool_index'] = int(index)
    return json.dumps({'index': int(index)})


def _to_bytes(x):
    if isinstance(x, (bytes, bytearray, memoryview)):
        return bytes(x)
    return x.to_bytes()          # a JavaScript Uint8Array


def pool_job(meta_json, ins, files, remove):
    """A parfor loop's job: the files that changed, the loop's module, and the
    values of its variables, kept for its blocks of passes."""
    from .builtins.parallel import loads, POOL
    meta = json.loads(meta_json)
    for p in remove:
        try:
            os.remove(str(p))
        except OSError:
            pass
    for item in files:
        path, data = str(item[0]), _to_bytes(item[1])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)
    R.STATE['cwd'] = meta['cwd'] if os.path.isdir(meta['cwd']) else R.STATE['home']
    R.STATE['path'] = [p for p in meta['path'] if os.path.isdir(p)]
    R.bump_epoch()
    m = meta['module']
    mod = R.MODULES.get(m['pyfile'])
    if mod is None or mod.src != m['src']:
        ns = R.make_ns(m['path'])
        exec(compile(m['src'], m['pyfile'], 'exec'), ns)
        mod = R.CompiledModule(m['path'], m['name'], m['text'], m['src'], m['linemap'], m['kind'], ns)
        R.MODULES[m['pyfile']] = mod
    from .builtins.elmat import RNG
    RNG.seed((int(meta['seed']) + 7919 * int(R.STATE.get('pool_index') or 1)) % (2 ** 31 - 1) or 1)
    _JOB.clear()
    _JOB.update(id=int(meta['job']), fn=mod.ns[meta['fn']], ins=loads(_to_bytes(ins)), files=POOL.scan())


async def pool_chunk(job, first, count):
    """A block of passes: the bytes of what it sends back, or the error as
    JSON text ({identifier, message} or {interrupted})."""
    from .builtins.parallel import dumps
    if _JOB.get('id') != int(job):
        return json.dumps({'identifier': 'parallel:pool:NoJob', 'message': 'The worker does not have that loop.'})
    R.INTERRUPT[0] = False
    R._TICK[1] = time.perf_counter()
    try:
        res = await _JOB['fn'](0, R.LoopRange(int(first), 1, int(count)), _JOB['ins'])
        R.flush()
        return dumps(res)
    except Interrupt:
        R.flush()
        return json.dumps({'interrupted': True})
    except MError as e:
        R.flush()
        return json.dumps({'identifier': e.identifier, 'message': e.message})
    except Exception as e:  # noqa: BLE001 -- any failure of a pass is the loop's error
        m = R.as_merror(e)
        R.flush()
        return json.dumps({'identifier': m.identifier, 'message': m.message})


def pool_written(job):
    """The files the job's passes wrote or changed: [(path, bytes)]."""
    from .builtins.parallel import POOL, FILE_MAX
    before = _JOB.get('files', {}) if _JOB.get('id') == int(job) else {}
    out = []
    for p, stamp in sorted(POOL.scan().items()):
        if before.get(p) != stamp and stamp[1] <= FILE_MAX:
            try:
                with open(p, 'rb') as f:
                    out.append((p, f.read()))
            except OSError:
                pass
    return out
