"""Tools of the desktop: the diary of the Command Window, the profiler,
breakpoints and the call stack from commands (dbstop, dbclear, dbstatus,
dbstack), the code checker (checkcode, mlint), the clipboard, lookfor,
and dates as tick labels (datetick)."""
import math
import os
import re

import numpy as np

from . import bi
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def _words(args, fn):
    return [py_str(a) if is_str(a) else (str(int(num(a))) if numel(a) == 1 and float(num(a)).is_integer() else str(num(a))) for a in args]


# ---- diary --------------------------------------------------------------------------------------------------------------------------

@bi('diary', arr=False)
def diary(nargout, *args):
    """diary, diary on, diary off, diary filename: the Command Window's commands and output copied to a file ('diary' in the current folder unless named)."""
    nargchk(args, 0, 1, 'diary')
    from .iofun import abspath, files_changed
    D = R.DIARY
    if not args:
        state = not D['on']
    else:
        w = py_str(args[0])
        if w.lower() == 'on':
            state = True
        elif w.lower() == 'off':
            state = False
        else:
            R.diary_flush()
            D['path'] = abspath(w)
            state = True
    if state and not D['path']:
        D['path'] = abspath('diary')
    if not state:
        R.diary_flush()
    D['on'] = state
    if D['path']:
        try:
            if state and not os.path.exists(D['path']):
                open(D['path'], 'a').close()
            files_changed(os.path.dirname(D['path']))
        except OSError as e:
            D['on'] = False
            raise err('MATLAB:diary:open', f'The diary file cannot be written: {e}.', 'diary')
    return None


# ---- the profiler -------------------------------------------------------------------------------------------------------------------

def _func_rows():
    P = R.PROFILER
    rows = []
    for (path, name), rec in P.funcs.items():
        lines = sorted((ln, c, t) for (pp, nn, ln), (c, t) in P.lines.items() if pp == path and nn == name)
        self_t = sum(t for _, _, t in lines)
        rows.append({'path': path, 'name': name, 'calls': rec['calls'], 'total': rec['total'], 'self': self_t, 'lines': lines})
    rows.sort(key=lambda r: -r['total'])
    return rows


def _report():
    P = R.PROFILER
    rows = _func_rows()
    if not rows:
        R.write('The profiler has nothing to show: run a program with profile on.\n')
        return
    out_ = [f'Profile summary: {P.wall:.4f} s in the functions of programs (built-ins are counted in the lines that call them).', '']
    w = max(max(len(r['name']) for r in rows), 8)
    out_.append(f"{'Function'.ljust(w)}   {'Calls':>7}   {'Total time (s)':>14}   {'Self time (s)':>13}")
    for r in rows:
        out_.append(f"{R.link(r['path'], r['lines'][0][0] if r['lines'] else 1, r['name'])}{' ' * (w - len(r['name']))}   {r['calls']:>7}   {r['total']:>14.4f}   {r['self']:>13.4f}")
    out_.append('')
    for r in rows[:10]:
        top = sorted(r['lines'], key=lambda x: -x[2])[:5]
        if not top:
            continue
        out_.append(f"{r['name']}: the lines that took the most time")
        for ln, c, t in top:
            src = R.source_line(r['path'], ln).strip()
            out_.append(f"   {R.link(r['path'], ln, f'line {ln}')}  {t:9.4f} s  {c:>8} times   {src[:60]}")
        out_.append('')
    R.write('\n'.join(out_) + '\n')


def _info():
    rows = _func_rows()
    keys = ('CompleteName', 'FunctionName', 'FileName', 'Type', 'NumCalls', 'TotalTime', 'SelfTime', 'ExecutedLines')
    ft = Struct.empty((len(rows), 1), keys)
    for i, r in enumerate(rows):
        vals = {'CompleteName': Char.of(f"{r['path']}>{r['name']}"), 'FunctionName': Char.of(r['name']), 'FileName': Char.of(r['path']),
                'Type': Char.of('M-function' if r['path'].endswith('.m') else 'M-script'), 'NumCalls': float(r['calls']),
                'TotalTime': r['total'], 'SelfTime': r['self'],
                'ExecutedLines': np.array([[float(ln), float(c), t] for ln, c, t in r['lines']]).reshape(-1, 3)}
        for k in keys:
            ft.f[k][i, 0] = vals[k]
    return Struct.scalar({'FunctionTable': ft, 'FunctionHistory': np.zeros((2, 0)), 'ClockPrecision': 1e-9, 'ClockSpeed': 0.0,
                          'Name': Char.of('PyLAB'), 'Overhead': 0.0})


@bi('profile', arr=False)
def profile(nargout, *args):
    """profile on, profile off, profile resume, profile clear, profile viewer (or report), p = profile('info'), s = profile('status'): the time spent in each function and line of programs."""
    nargchk(args, 1, 4, 'profile')
    w = py_str(args[0]).lower()
    P = R.PROFILER
    if w in ('on', 'resume'):
        if w == 'on':
            P.clear()
        P.on = True
        P.prev = None
        R.refresh_hooks()
        if hasattr(R.DEBUGGER, 'refresh_modules'):
            R.DEBUGGER.refresh_modules()
        return None
    if w == 'off':
        P.settle()
        P.on = False
        R.refresh_hooks()
        if hasattr(R.DEBUGGER, 'refresh_modules'):
            R.DEBUGGER.refresh_modules()
        return None
    if w == 'clear':
        P.clear()
        return None
    if w in ('viewer', 'report'):
        if P.on:
            P.settle()
            P.on = False
            R.refresh_hooks()
        _report()
        return None
    if w == 'info':
        if P.on:
            P.settle()
        return _info()
    if w == 'status':
        return Struct.scalar({'ProfilerStatus': Char.of('on' if P.on else 'off'), 'DetailLevel': Char.of('mmex'), 'Timer': Char.of('performance'),
                              'HistoryTracking': Char.of('off'), 'HistorySize': 1000000.0})
    raise err('MATLAB:profile:option', "profile on, off, resume, clear, viewer, report, info or status.", 'profile')


# ---- breakpoints ---------------------------------------------------------------------------------------------------------------------

def _debugger(fn):
    D = R.DEBUGGER
    if not hasattr(D, 'breakpoints'):
        raise err(f'MATLAB:{fn}:noDebugger', 'Breakpoints are kept by the page\'s debugger: run this in the Command Window.', fn)
    return D


def _program(name, fn):
    """The path of the program file a name or path stands for (a local function's file for file>sub)."""
    from .iofun import abspath
    name = name.split('>')[0]
    if name.endswith('.m') or '/' in name:
        p = abspath(name if name.endswith('.m') else name + '.m')
        if os.path.isfile(p):
            return p
    else:
        p = R.find_file(name)
        if p:
            return p
    raise err(f'MATLAB:{fn}:fileNotFound', f"'{name}' is not a program file on the path.", fn)


def _statement_lines(path):
    """The lines where statements begin (where a program can stop)."""
    with open(path, encoding='utf-8', errors='replace') as f:
        return statement_lines(f.read())


def statement_lines(text):
    """The lines of a program's text where statements begin: not its comments, blank lines, ends or the lines a
    statement continues on."""
    from ..parser import parse, assigned_names, Stmt
    from .. import classdef as CD
    if CD.is_classdef(text):
        sp = CD.parse(text)
        text, _ = CD.methods_text(sp, sp.name)
    names = assigned_names(text)
    prog = parse(text, lambda n: n in names, 'file')
    lines = set()
    for node in _walk(prog):
        if isinstance(node, Stmt) and getattr(node, 'line', None):
            lines.add(int(node.line))
    return sorted(lines)


def _walk(x, seen=None):
    """Every node and statement under x (the parser's objects, lists and tuples)."""
    from ..parser import Node, Stmt, Func, Program, ArgDecl
    stack = [x]
    while stack:
        o = stack.pop()
        if isinstance(o, (list, tuple)):
            stack.extend(reversed(o))
            continue
        if isinstance(o, dict):
            stack.extend(o.values())
            continue
        if not isinstance(o, (Node, Stmt, Func, Program, ArgDecl)):
            continue
        yield o
        for cls in type(o).__mro__:
            for k in getattr(cls, '__slots__', ()):
                if k in ('line', 'parent'):
                    continue
                v = getattr(o, k, None)
                if isinstance(v, (Node, Stmt, Func, Program, ArgDecl, list, tuple, dict)):
                    stack.append(v)


def _publish(path, lines):
    """The page's Editor shows the file's breakpoints as the engine now has them (their conditions, those turned off)."""
    return R.ask_page({'type': 'breakpoints', 'path': path, 'lines': sorted(lines), 'info': R.DEBUGGER.info_json(path)})


def _expression(info):
    """A breakpoint's expression as dbstatus gives it: its condition, and one turned off as false&&(condition), which
    dbstop reads back as turned off."""
    if info is None:
        return ''
    if info['on']:
        return info['cond']
    return f"false&&({info['cond']})" if info['cond'] else 'false'


def _from_expression(expr):
    """dbstop's reading of an expression: (condition, on)."""
    e = expr.strip()
    m = re.fullmatch(r'false\s*&&\s*\((.*)\)', e, re.S)
    if m:
        return m.group(1).strip(), False
    if e == 'false':
        return '', False
    return e, True


@bi('dbstop', aw=True, arr=False)
async def dbstop(nargout, *args):
    """dbstop in file at line, dbstop in file, dbstop at line in file, dbstop if error, dbstop(s): a breakpoint set from a command."""
    nargchk(args, 1, 8, 'dbstop')
    D = _debugger('dbstop')
    if len(args) == 1 and isinstance(args[0], Struct):
        s = args[0]
        for i in range(s.size):
            e = s.elem(i)
            path = py_str(e['file']) if 'file' in e else _program(py_str(e['name']), 'dbstop')
            lines = [int(x) for x in darr(e['line']).reshape(-1)] if 'line' in e and numel(e['line']) else []
            if lines:
                # the expressions dbstatus gave: conditions, and false&&(...) for one turned off
                exprs = [py_str(x) for x in e['expression'].a.reshape(-1, order='F')] if 'expression' in e and isinstance(e['expression'], Cell) else []
                info = dict(D.info_json(path))
                for ln, ex in zip(lines, exprs):
                    cond, on = _from_expression(ex)
                    info[str(ln)] = {'cond': cond, 'on': on}
                D.set_breakpoints(path, sorted(set(D.breakpoints.get(path, set())) | set(lines)), info)
                await _publish(path, D.breakpoints.get(path, ()))
        return None
    w = _words(args, 'dbstop')
    low = [x.lower() for x in w]
    if low[0] == 'if':
        cond = ' '.join(low[1:])
        if cond in ('error', 'caught error'):
            D.stop_on_error = True
            return None
        raise err('MATLAB:dbstop:condition', "PyLAB stops 'if error'; conditions on warnings and naninf are not watched.", 'dbstop')
    name = line = None
    cond = ''
    k = 0
    while k < len(low):
        if low[k] == 'in' and k + 1 < len(w):
            name = w[k + 1]
            k += 2
        elif low[k] == 'at' and k + 1 < len(w):
            line = w[k + 1]
            k += 2
        elif low[k] == 'if':
            # dbstop in file at line if expression: the rest is the condition
            cond = ' '.join(w[k + 1:]).strip()
            if not cond:
                raise err('MATLAB:dbstop:condition', 'dbstop ... if expression: give the condition.', 'dbstop')
            break
        elif name is None:
            name = w[k]
            k += 1
        elif line is None:
            line = w[k]
            k += 1
        else:
            raise err('MATLAB:dbstop:syntax', 'dbstop in file at line, dbstop in file, or dbstop if error.', 'dbstop')
    if name is None:
        raise err('MATLAB:dbstop:syntax', 'dbstop in file at line, dbstop in file, or dbstop if error.', 'dbstop')
    path = _program(name, 'dbstop')
    stmts = _statement_lines(path)
    if not stmts:
        raise err('MATLAB:dbstop:noStatements', f'{os.path.basename(path)} has no statement to stop at.', 'dbstop')
    want = []
    for part in (line.split(',') if line else [None]):
        if part is None:
            want.append(stmts[0])
            continue
        try:
            n = int(part.split('@')[0])
        except ValueError:
            raise err('MATLAB:dbstop:line', f"'{part}' is not a line number.", 'dbstop')
        nxt = next((x for x in stmts if x >= n), None)
        if nxt is None:
            raise err('MATLAB:dbstop:line', f'Line {n} of {os.path.basename(path)} is after its last statement.', 'dbstop')
        want.append(nxt)
    lines = sorted(set(D.breakpoints.get(path, set())) | set(want))
    # a breakpoint set again takes the condition given (or none), and is on
    info = dict(D.info_json(path))
    for ln in want:
        info[str(ln)] = {'cond': cond, 'on': True}
    D.set_breakpoints(path, lines, info)
    await _publish(path, lines)
    return None


@bi('dbclear', aw=True, arr=False)
async def dbclear(nargout, *args):
    """dbclear all, dbclear in file, dbclear in file at line, dbclear if error: breakpoints taken away."""
    nargchk(args, 1, 6, 'dbclear')
    D = _debugger('dbclear')
    w = _words(args, 'dbclear')
    low = [x.lower() for x in w]
    if low[0] == 'all':
        for path in list(D.breakpoints):
            D.set_breakpoints(path, [])
            await _publish(path, [])
        D.stop_on_error = False
        return None
    if low[0] == 'if':
        D.stop_on_error = False
        return None
    name = line = None
    k = 0
    while k < len(low):
        if low[k] == 'in' and k + 1 < len(w):
            name, k = w[k + 1], k + 2
        elif low[k] == 'at' and k + 1 < len(w):
            line, k = w[k + 1], k + 2
        elif name is None:
            name, k = w[k], k + 1
        else:
            line, k = w[k], k + 1
    path = _program(name, 'dbclear')
    if line is None:
        lines = []
    else:
        drop = {int(x) for x in line.split(',')}
        lines = sorted(set(D.breakpoints.get(path, set())) - drop)
    D.set_breakpoints(path, lines)
    await _publish(path, lines)
    return None


@bi('dbstatus', arr=False)
def dbstatus(nargout, *args):
    """dbstatus, dbstatus file, s = dbstatus: the breakpoints set, and whether programs stop at errors."""
    nargchk(args, 0, 2, 'dbstatus')
    D = R.DEBUGGER
    bps = dict(getattr(D, 'breakpoints', {}))
    if args and not py_str(args[0]).startswith('-'):
        p = _program(py_str(args[0]), 'dbstatus')
        bps = {p: bps.get(p, set())} if p in bps else {}
    stop = bool(getattr(D, 'stop_on_error', False))
    info = {p: getattr(D, 'bp_info', {}).get(p, {}) for p in bps}
    if nargout:
        keys = ('name', 'file', 'line', 'anonymous', 'expression', 'cond', 'identifier')
        recs = [{'name': Char.of(os.path.splitext(os.path.basename(p))[0]), 'file': Char.of(p),
                 'line': np.array([[float(x) for x in sorted(ls)]]), 'anonymous': np.zeros((1, len(ls))),
                 'expression': Cell.of_list([Char.of(_expression(info[p].get(x))) for x in sorted(ls)]), 'cond': Char.of(''), 'identifier': Cell.empty((0, 0))}
                for p, ls in sorted(bps.items()) if ls]
        if stop:
            recs.append({'name': Char.of(''), 'file': Char.of(''), 'line': EMPTY(), 'anonymous': EMPTY(), 'expression': Cell.empty((1, 0)),
                         'cond': Char.of('error'), 'identifier': Cell.of_list([Char.of('all')])})
        s = Struct.empty((len(recs), 1), keys)
        for i, rc in enumerate(recs):
            for k in keys:
                s.f[k][i, 0] = rc[k]
        return s
    lines = []
    for p, ls in sorted(bps.items()):
        if not ls:
            continue
        nm = os.path.splitext(os.path.basename(p))[0]
        ls = sorted(ls)

        def say(x):
            # a line, with its condition and whether it is turned off
            i = info[p].get(x)
            if i is None:
                return str(x)
            notes = ([f"if {i['cond']}"] if i['cond'] else []) + ([] if i['on'] else ['turned off'])
            return f"{x} ({', '.join(notes)})"
        if len(ls) == 1:
            lines.append(f'Breakpoint for {R.link(p, ls[0], nm)} is on line {say(ls[0])}.')
        else:
            lines.append(f"Breakpoints for {R.link(p, ls[0], nm)} are on lines {', '.join(say(x) for x in ls[:-1])} and {say(ls[-1])}.")
    if stop:
        lines.append('Stop if error.')
    if lines:
        R.write('\n'.join(lines) + '\n')
    return None


@bi('dbstack', nout=2, arr=False)
def dbstack(nargout, *args):
    """dbstack, [ST, I] = dbstack, dbstack('-completenames'): the functions running now, the innermost first, and their lines."""
    nargchk(args, 0, 2, 'dbstack')
    complete = any(is_str(a) and py_str(a) == '-completenames' for a in args)
    skip = int(num(next(a for a in args if not is_str(a)))) if any(not is_str(a) for a in args) else 0
    frames = R.stack_of_frames()[skip:]
    if nargout:
        keys = ('file', 'name', 'line')
        s = Struct.empty((len(frames), 1), keys)
        for i, fr in enumerate(frames):
            s.f['file'][i, 0] = Char.of(fr['file'] if complete else os.path.basename(fr['file']))
            s.f['name'][i, 0] = Char.of(fr['name'])
            s.f['line'][i, 0] = float(fr['line'])
        return (s, 1.0) if nargout > 1 else s
    if frames:
        R.write(''.join(f"> In {R.link(fr['file'], fr['line'], fr['name'])} (line {fr['line']})\n" for fr in frames))
    return None


# ---- the code checker ---------------------------------------------------------------------------------------------------------------

_QUIET = frozenset('disp display fprintf printf error warning assert plot hold figure close clc clear title xlabel ylabel zlabel legend axis grid drawnow pause print fclose set subplot'.split())


def _col(text_lines, line, name):
    if 0 < line <= len(text_lines) and name:
        m = re.search(r'(?<![\w.])' + re.escape(name) + r'(?!\w)', text_lines[line - 1])
        if m:
            return [m.start() + 1, m.end()]
    return [1, 1]


def _check_text(text, fname):
    """(line, [col0, col1], id, message) for each thing found: syntax errors, and in functions values never used, inputs
    unused, outputs not set, output not suppressed, and a function's name unlike its file's."""
    from ..parser import parse, assigned_names, Assign, ExprS, Id, Index, Field, For, Global, Func, Anon, Cmd
    from .. import classdef as CD
    msgs = []
    lines = text.split('\n')
    src = text
    try:
        if CD.is_classdef(text):
            sp = CD.parse(text)
            src, _ = CD.methods_text(sp, sp.name)
        names = assigned_names(src)
        prog = parse(src, lambda n: n in names, 'file')
    except MError as e:
        line = getattr(e, 'line', 1) or 1
        pos = getattr(e, 'pos', None)
        col = [1, 1]
        if pos is not None:
            start = sum(len(x) + 1 for x in src.split('\n')[:line - 1])
            c = max(pos - start, 0) + 1
            col = [c, c]
        return [(line, col, 'SYNTAX', 'Parse error: ' + e.message)]
    funcs = []
    stack = list(prog.funcs)
    while stack:
        f = stack.pop()
        funcs.append(f)
        stack.extend(f.subs or [])
    if prog.kind == 'function' and prog.funcs and fname and prog.funcs[0].name != fname and not CD.is_classdef(text):
        f0 = prog.funcs[0]
        msgs.append((f0.line, _col(lines, f0.line, f0.name), 'FNDEF', f"The function name '{f0.name}' should match the file name '{fname}'."))
    for f in funcs:
        assigned = {}      # name -> first line assigned
        reads = set()
        sets = set()
        nested = set()
        for sub in f.subs or []:
            for node in _walk(sub):
                if isinstance(node, Id):
                    nested.add(node.name)
        body_nodes = list(_walk(f.body))
        for node in body_nodes:
            if isinstance(node, Assign):
                for t in node.lhs:
                    if isinstance(t, Id):
                        assigned.setdefault(t.name, node.line)
                        sets.add(t.name)
                    else:
                        base = t
                        while isinstance(base, (Index, Field)):
                            base = base.base
                        if isinstance(base, Id):
                            sets.add(base.name)
                            reads.add(base.name)    # an element changed keeps the rest
            elif isinstance(node, For) and isinstance(node.var, Id):
                sets.add(node.var.name)
            elif isinstance(node, Global):
                reads.update(node.names)
                sets.update(node.names)
            elif isinstance(node, Cmd):
                reads.add(node.name)
                for a in node.args or []:
                    reads.update(re.findall(r'[A-Za-z]\w*', str(a)))
        lhs_ids = set()
        for node in body_nodes:
            if isinstance(node, Assign):
                for t in node.lhs:
                    if isinstance(t, Id):
                        lhs_ids.add(id(t))
        for node in body_nodes:
            if isinstance(node, Id) and id(node) not in lhs_ids:
                reads.add(node.name)
            elif isinstance(node, Anon):
                reads.update(re.findall(r'[A-Za-z]\w*', node.text or ''))
        uses_eval = any(isinstance(n, Id) and n.name in ('eval', 'evalin', 'assignin', 'who', 'whos', 'save', 'exist') for n in body_nodes)
        outs = [o for o in (f.outs or []) if o not in ('varargout',)]
        if not uses_eval:
            for name, ln in sorted(assigned.items(), key=lambda x: x[1]):
                if name not in reads and name not in outs and name not in nested and name != 'ans':
                    msgs.append((ln, _col(lines, ln, name), 'NASGU', f"The value assigned to variable '{name}' might be unused."))
            for p in f.params or []:
                if p not in ('~', 'varargin') and p not in reads and p not in nested:
                    msgs.append((f.line, _col(lines, f.line, p), 'INUSD', f"Input argument '{p}' might be unused."))
        for o in outs:
            if o not in sets:
                msgs.append((f.line, _col(lines, f.line, o), 'STOUT', f"Output argument '{o}' might not be set."))
        for node in _top_statements(f.body or []):
            if isinstance(node, Assign) and node.show:
                t = node.lhs[0]
                nm = t.name if isinstance(t, Id) else ''
                msgs.append((node.line, _col(lines, node.line, nm), 'NOPRT', 'Terminate statement with semicolon to suppress output (in functions).'))
            elif isinstance(node, ExprS) and node.show and not _call_like(node.e, _QUIET):
                msgs.append((node.line, [1, 1], 'NOPRT', 'Terminate statement with semicolon to suppress output (in functions).'))
    msgs.sort(key=lambda m: (m[0], m[1][0]))
    return msgs


def _top_statements(body):
    """The statements of a body and of the blocks in it (not of nested functions)."""
    from ..parser import If, For, While, Switch, Try
    out_ = []
    stack = list(reversed(body))
    while stack:
        s = stack.pop()
        out_.append(s)
        if isinstance(s, If):
            for c in s.clauses:
                stack.extend(reversed(c[1] if isinstance(c, (tuple, list)) else []))
            stack.extend(reversed(s.els or []))
        elif isinstance(s, (For, While)):
            stack.extend(reversed(s.body))
        elif isinstance(s, Switch):
            for c in s.cases:
                stack.extend(reversed(c[1] if isinstance(c, (tuple, list)) else []))
            stack.extend(reversed(s.other or []))
        elif isinstance(s, Try):
            stack.extend(reversed(s.body))
            stack.extend(reversed(s.cbody or []))
    return out_


def _call_like(e, quiet):
    """An expression statement that is a call (which may print nothing): a name, or name(...) of a function."""
    from ..parser import Id, Index
    if isinstance(e, Id):
        return True
    if isinstance(e, Index) and isinstance(e.base, Id):
        return True
    return False


@bi('checkcode', 'mlint', nout=2, arr=False)
def checkcode(nargout, *args):
    """checkcode(filename), info = checkcode(filename, '-struct'), checkcode(..., '-id'), s = checkcode(..., '-string'): what the code checker finds in program files."""
    nargchk(args, 1, 10, 'checkcode')
    from .iofun import abspath
    files, flags = [], set()
    for a in args:
        if type(a) is Cell:
            files += [py_str(x) for x in a.a.reshape(-1, order='F')]
        elif is_str(a) and py_str(a).startswith('-'):
            flags.add(py_str(a).lower())
        else:
            files.append(py_str(a))
    results = []
    for name in files:
        p = abspath(name if name.endswith('.m') else name + '.m')
        if not os.path.isfile(p):
            p2 = R.find_file(name) if not name.endswith('.m') else None
            if not p2:
                raise err('MATLAB:checkcode:fileNotFound', f"'{name}' is not a file here.", 'checkcode')
            p = p2
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read()
        results.append((p, _check_text(text, os.path.splitext(os.path.basename(p))[0])))
    with_id = '-id' in flags

    def text_of(m):
        return f"L {m[0]} (C {m[1][0]}{'-' + str(m[1][1]) if m[1][1] != m[1][0] else ''}): {(m[2] + ': ') if with_id else ''}{m[3]}"
    if '-string' in flags:
        parts = []
        for p, ms in results:
            if len(results) > 1:
                parts.append(f'========== {p} ==========')
            parts += [text_of(m) for m in ms]
        return Char.of('\n'.join(parts) + ('\n' if parts else ''))
    if nargout:
        keys = ('message', 'fix', 'line', 'column') + (('id',) if with_id else ())

        def st(ms):
            s = Struct.empty((len(ms), 1), keys)
            for i, m in enumerate(ms):
                s.f['message'][i, 0] = Char.of(m[3])
                s.f['fix'][i, 0] = 0.0
                s.f['line'][i, 0] = float(m[0])
                s.f['column'][i, 0] = np.array([[float(m[1][0]), float(m[1][1])]])
                if with_id:
                    s.f['id'][i, 0] = Char.of(m[2])
            return s
        if len(results) == 1:
            return st(results[0][1])
        c = Cell.empty((len(results), 1))
        for i, (_, ms) in enumerate(results):
            c.a[i, 0] = st(ms)
        return c
    for p, ms in results:
        if len(results) > 1:
            R.write(f'========== {p} ==========\n')
        for m in ms:
            R.write(R.link(p, m[0], text_of(m)) + '\n')
    return None


# ---- the clipboard -------------------------------------------------------------------------------------------------------------------

_CLIP = ['']


@bi('clipboard', aw=True, arr=False)
async def clipboard(nargout, *args):
    """clipboard('copy', data), str = clipboard('paste'): text to and from the system's clipboard (data not text as mat2str writes it)."""
    nargchk(args, 1, 2, 'clipboard')
    op = py_str(args[0]).lower()
    if op == 'copy':
        if len(args) < 2:
            raise err('MATLAB:clipboard:data', "clipboard('copy', data) copies data.", 'clipboard')
        d = args[1]
        text = d.str() if isinstance(d, Char) and d.a.shape[0] <= 1 else ('\n'.join(d.row_strs()) if isinstance(d, Char) else py_str(R._builtin('mat2str', d)) if not is_str(d) else py_str(d))
        _CLIP[0] = text
        res = await R.ask_page({'type': 'clipboard', 'op': 'copy', 'text': text})
        if isinstance(res, dict) and res.get('error'):
            raise err('MATLAB:clipboard:denied', f"The browser did not let the page write to the clipboard: {res['error']}", 'clipboard')
        return None
    if op in ('paste', 'pastespecial'):
        if op == 'pastespecial':
            raise err('MATLAB:clipboard:pastespecial', "clipboard('pastespecial') is not made here: clipboard('paste') gives the text.", 'clipboard')
        res = await R.ask_page({'type': 'clipboard', 'op': 'paste'})
        if isinstance(res, dict):
            if res.get('error'):
                raise err('MATLAB:clipboard:denied', f"The browser did not let the page read the clipboard: {res['error']}", 'clipboard')
            return Char.of(res.get('text', ''))
        return Char.of(_CLIP[0])
    raise err('MATLAB:clipboard:op', "clipboard('copy', data) or clipboard('paste').", 'clipboard')


# ---- lookfor --------------------------------------------------------------------------------------------------------------------------

def _h1(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s.startswith('%'):
                    return s.lstrip('%').strip()
                if s and not s.startswith('function') and not s.startswith('classdef'):
                    return ''
    except OSError:
        pass
    return ''


@bi('lookfor', arr=False)
def lookfor(nargout, *args):
    """lookfor topic, lookfor topic -all: the functions whose first line of help (or, with -all, any of it) has the topic in it."""
    nargchk(args, 1, 2, 'lookfor')
    from ..helptext import HELP
    topic = py_str(args[0]).lower()
    whole = len(args) > 1 and py_str(args[1]).lower() == '-all'
    hits = []
    for d in R.search_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in names:
            if fn.endswith('.m'):
                p = os.path.join(d, fn)
                h1 = _h1(p)
                text = h1
                if whole:
                    try:
                        with open(p, encoding='utf-8', errors='replace') as f:
                            text = f.read()
                    except OSError:
                        pass
                if topic in fn[:-2].lower() or topic in text.lower():
                    hits.append((fn[:-2], h1, R.link(p, 1, fn[:-2])))
    for name in sorted(HELP, key=str.lower):
        entry = HELP[name]
        first = entry[0] if isinstance(entry, tuple) else str(entry).split('\n')[0]
        text = first if not whole else ' '.join([first] + list(entry[1] if isinstance(entry, tuple) else []) + [entry[2] if isinstance(entry, tuple) and len(entry) > 2 else ''])
        if topic in name.lower() or topic in text.lower():
            hits.append((name, first, f'\x01help:{name}\x02{name}\x03'))
    if nargout:
        return Cell.of_list([Char.of(h[0]) for h in hits], (len(hits), 1))
    if not hits:
        R.write(f"Nothing has '{py_str(args[0])}' in its first line of help.\n")
        return None
    w = max(len(h[0]) for h in hits)
    R.write(''.join(f"{h[2]}{' ' * (w - len(h[0]))} - {h[1]}\n" for h in hits))
    return None


# ---- dates as tick labels ------------------------------------------------------------------------------------------------------------

_STEPS_DAYS = [1 / 1440, 2 / 1440, 5 / 1440, 10 / 1440, 15 / 1440, 30 / 1440, 1 / 24, 2 / 24, 3 / 24, 6 / 24, 12 / 24, 1, 2, 7, 14]


def _date_ticks(lo, hi):
    """Ticks (datenums) between lo and hi at a step of time (minutes to years) giving about 4 to 8, and a format for them."""
    from datetime import datetime, timedelta
    span = hi - lo
    base = datetime(1, 1, 1)

    def to_dt(dn):
        return base + timedelta(days=dn - 367)

    def to_dn(dt):
        return (dt - base).total_seconds() / 86400 + 367
    if span > 3 * 365:
        y0, y1 = to_dt(lo).year, to_dt(hi).year + 1
        step = max(1, int(math.ceil((y1 - y0) / 7)))
        for nice in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000):
            if nice >= step:
                step = nice
                break
        ys = [y for y in range((y0 // step) * step, y1 + 1, step)]
        return [to_dn(datetime(y, 1, 1)) for y in ys if lo - 1e-9 <= to_dn(datetime(y, 1, 1)) <= hi + 1e-9] or [lo, hi], 'yyyy'
    if span > 45:
        d0, d1 = to_dt(lo), to_dt(hi)
        months = (d1.year - d0.year) * 12 + d1.month - d0.month + 1
        step = next(s for s in (1, 2, 3, 4, 6, 12) if months / s <= 8)
        ticks = []
        y, m = d0.year, d0.month
        while True:
            dn = to_dn(datetime(y, m, 1))
            if dn > hi + 1e-9:
                break
            if dn >= lo - 1e-9 and ((y * 12 + m - 1) % step == 0):
                ticks.append(dn)
            m += 1
            if m > 12:
                y, m = y + 1, 1
        return ticks or [lo, hi], ('mmmyy' if span > 300 else 'mmm')
    step = next((s for s in _STEPS_DAYS if span / s <= 8), 14)
    first = math.ceil(lo / step - 1e-9) * step
    ticks = list(np.arange(first, hi + step * 1e-9, step))
    fmt = 'HH:MM' if span <= 1.5 else ('dd-mmm HH:MM' if step < 1 else 'dd-mmm')
    return ticks or [lo, hi], fmt


@bi('datetick', arr=False)
def datetick(nargout, *args):
    """datetick, datetick(axis), datetick(axis, fmt), datetick(..., 'keepticks', 'keeplimits'), datetick(ax, ...): an axis's tick labels as dates, its values taken as datenums."""
    from .graphics import gcf_, gca_, split_axes_arg
    nargchk(args, 0, 5, 'datetick')
    ax, rest = split_axes_arg(args)
    ax = ax if ax is not None else gca_(gcf_())
    which = 'x'
    fmt = None
    keepticks = keeplimits = False
    for a in rest:
        if is_str(a):
            w = py_str(a)
            if w.lower() in ('x', 'y', 'z'):
                which = w.lower()
            elif w.lower() == 'keepticks':
                keepticks = True
            elif w.lower() == 'keeplimits':
                keeplimits = True
            else:
                fmt = w
        else:
            fmt = float(num(a))
    A = which.upper()
    lim = np.asarray(darr(ax.getprop(f'{A}Lim')), float).reshape(-1)
    if keepticks:
        ticks = list(np.asarray(darr(ax.getprop(f'{A}Tick')), float).reshape(-1))
        auto_fmt = 'dd-mmm'
    else:
        lo, hi = lim[0], lim[1]
        data = []
        for c in ax.children:
            p = getattr(c, 'props', {})
            if f'{A}Data' in p and numel(p[f'{A}Data']):
                data.append(np.asarray(p[f'{A}Data'], float).reshape(-1))
        if data and not keeplimits:
            allv = np.concatenate(data)
            allv = allv[np.isfinite(allv)]
            if allv.size:
                lo, hi = float(allv.min()), float(allv.max())
        if hi <= lo:
            hi = lo + 1
        ticks, auto_fmt = _date_ticks(lo, hi)
        if not keeplimits:
            R._builtin(f'{which}lim', ax, np.array([[min(lo, ticks[0]), max(hi, ticks[-1])]]))
    labels = R._builtin('datestr', np.asarray(ticks, float).reshape(-1, 1), Char.of(auto_fmt) if fmt is None else (fmt if isinstance(fmt, float) else Char.of(fmt)))
    rows = labels.row_strs() if isinstance(labels, Char) else [py_str(labels)]
    R._builtin(f'{which}ticks', ax, np.asarray(ticks, float).reshape(1, -1))
    R._builtin(f'{which}ticklabels', ax, Cell.of_list([Char.of(r.rstrip()) for r in rows]))
    return None
