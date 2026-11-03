"""The compiler: a syntax tree to Python source.

Every program becomes async Python. A function becomes

    async def F_name(nargout, *args):
        W = R.Workspace('name', PARAMS)      # the function's variables
        ...
        return R.fout(W, OUTPUTS, nargout, 'name')

and a script or a command line `async def SCRIPT(W)` run in the caller's
workspace. Calls to other compiled functions are awaited, so a running
program gives the page a moment between loop iterations: Ctrl+C, input()
and the debugger's breakpoints work without threads.

Names are settled when the code is compiled, as the language does for
functions: a name assigned anywhere in a function is a variable there, and
any other name is a function. A script or command line is compiled against
the workspace it runs in, so the names already there count as variables;
a name that is neither is looked up when it runs.

Values are shared, not copied, when they are assigned: R.share marks a value
held in two places, and the next change in place copies it (see values.py).
"""
import keyword
import re

from . import parser as P
from .values import MError

PYKW = set(keyword.kwlist) | {'print', 'exec', 'match', 'case', 'type'}


def pyname(name):
    """A builtin's attribute name in B."""
    return name + '_' if name in PYKW else name


def pytuple(parts):
    """A Python tuple of the parts. One part takes a comma: without it, (x)
    is x and (*c) is no Python at all."""
    return '(' + ', '.join(parts) + (',)' if len(parts) == 1 else ')')



def _flit(v):
    """A float as Python source: inf, -inf and NaN by their names in runtime.py."""
    r = repr(float(v))
    return {'inf': 'R.INF', '-inf': 'R.NINF', 'nan': 'R.NAN'}.get(r, r)

class CompileError(MError):
    def __init__(self, msg, line):
        super().__init__('MATLAB:compile', msg)
        self.line = line


# ---- analysis ---------------------------------------------------------------------

def _walk_expr(e, fn):
    """Call fn on every expression node (not into anonymous functions'
    bodies)."""
    fn(e)
    t = type(e)
    if t is P.Bin:
        _walk_expr(e.a, fn)
        _walk_expr(e.b, fn)
    elif t is P.Un or t is P.Post:
        _walk_expr(e.a, fn)
    elif t is P.Paren:
        _walk_expr(e.e, fn)
    elif t is P.Range:
        _walk_expr(e.a, fn)
        if e.s is not None:
            _walk_expr(e.s, fn)
        _walk_expr(e.b, fn)
    elif t is P.Mat or t is P.CellLit:
        for r in e.rows:
            for x in r:
                _walk_expr(x, fn)
    elif t is P.Index:
        _walk_expr(e.base, fn)
        for a in e.args:
            _walk_expr(a, fn)
    elif t is P.Field:
        _walk_expr(e.base, fn)
        if not isinstance(e.name, str):
            _walk_expr(e.name, fn)


def _stmts(body):
    for s in body:
        yield s
        t = type(s)
        if t is P.If:
            for c, b in s.clauses:
                yield from _stmts(b)
            if s.els:
                yield from _stmts(s.els)
        elif t is P.For or t is P.While:
            yield from _stmts(s.body)
        elif t is P.Switch:
            for c, b in s.cases:
                yield from _stmts(b)
            if s.other:
                yield from _stmts(s.other)
        elif t is P.Try:
            yield from _stmts(s.body)
            yield from _stmts(s.cbody)


def _root(e):
    while isinstance(e, (P.Index, P.Field)):
        e = e.base
    return e.name if isinstance(e, P.Id) else None


def assigned(body):
    """Names assigned in a body: targets, for variables, catch variables,
    globals and persistents."""
    names = set()
    for s in _stmts(body):
        t = type(s)
        if t is P.Assign:
            for x in s.lhs:
                if x is not None:
                    r = _root(x)
                    if r:
                        names.add(r)
        elif t is P.For:
            r = _root(s.var)
            if r:
                names.add(r)
        elif t is P.Try and s.var:
            names.add(s.var)
        elif t is P.Global:
            names.update(s.names)
    return names


def _nested_assigned(f):
    """The names the nested functions of f (at any depth) assign, but for
    their own inputs and outputs."""
    names = set()
    for s in f.subs:
        names |= (assigned(s.body) - set(s.params) - set(s.outs)) | _nested_assigned(s)
    return names


def globals_of(body):
    g, p = set(), set()
    for s in _stmts(body):
        if type(s) is P.Global:
            (p if s.persistent else g).update(s.names)
    return g, p


_DYNAMIC_CALLS = {'eval', 'evalin', 'assignin', 'load', 'evalc', 'run', 'importdata', 'exist', 'who', 'whos', 'clear', 'clearvars'}


def uses_names(body):
    """Every identifier read in a body (outside anonymous functions' own
    parameters), and the command-syntax names."""
    out = set()

    def visit(e):
        if type(e) is P.Id:
            out.add(e.name)
        elif type(e) is P.Anon:
            inner = set()
            _walk_expr(e.body, lambda x: inner.add(x.name) if type(x) is P.Id else visit_anon(x))
            out.update(inner - set(e.params))

    def visit_anon(x):
        if type(x) is P.Anon:
            visit(x)

    for s in _stmts(body):
        for e in _exprs_of(s):
            _walk_expr(e, visit)
        if type(s) is P.Cmd:
            out.add(s.name)
    return out


def _exprs_of(s):
    t = type(s)
    if t is P.ExprS:
        return [s.e]
    if t is P.Assign:
        return [s.rhs] + [x for x in s.lhs if x is not None]
    if t is P.If:
        return [c for c, b in s.clauses]
    if t is P.For:
        return [s.it, s.var]
    if t is P.While:
        return [s.cond]
    if t is P.Switch:
        return [s.e] + [c for c, b in s.cases]
    return []


# ---- the code writer -------------------------------------------------------------

class Emitter:
    def __init__(self):
        self.lines = []
        self.map = []         # M line for each Python line (0 when none)
        self.ind = 0

    def emit(self, text, mline=0):
        self.lines.append('    ' * self.ind + text)
        self.map.append(mline)


class Scope:
    """What one compiled body knows about its names."""

    def __init__(self, kind, name, variables, params=(), outs=(), gnames=(), pnames=(),
                 dynamic=False, local_funcs=None, fh_vars=None, nested_parent=None):
        self.kind = kind              # 'function', 'script', 'anon'
        self.name = name
        self.vars = set(variables)
        self.params = list(params)
        self.outs = list(outs)
        self.gnames = set(gnames)
        self.pnames = set(pnames)
        self.dynamic = dynamic        # unknown names are looked up when the code runs
        self.local_funcs = local_funcs or {}
        self.fh_vars = fh_vars if fh_vars is not None else set(variables)
        self.loop_depth = 0
        self.nested = False           # a nested function, or one that has some (its workspace is shared)
        self.in_parfor = False        # the body of a parfor's chunk function (a parfor there runs as for)
        self.reductions = None        # id(statement) -> how the chunk function reduces it


class Compiler:
    def __init__(self, builtins, user_funcs=None, modname='<command>', path=''):
        """builtins: name -> info (attributes ws, aw, nout, arr); user_funcs:
        a function telling whether a name is a file on the path (which then
        shadows a builtin of the same name)."""
        self.builtins = builtins
        self.user_funcs = user_funcs or (lambda name: False)
        self.modname = modname
        self.path = path
        self.consts = []
        self.const_keys = {}
        self.out = Emitter()
        self.anon_n = 0
        self.anon_texts = {}          # _A<n> -> its text, for the names of frames in errors
        self.tmp_n = 0
        self.top = []                 # module-level definitions (anonymous functions)
        self.scope = None
        self.debug = True
        self.local = {}               # the file's local functions: name -> Python name
        self.extra = []               # parfor chunk functions: (lines, line map), at the module's end
        self.parfor_n = 0

    # ---- helpers ---------------------------------------------------------------
    def tmp(self):
        self.tmp_n += 1
        return f'_t{self.tmp_n}'

    def const(self, kind, value):
        key = (kind, value if not isinstance(value, list) else tuple(map(tuple, value)))
        if key in self.const_keys:
            return self.const_keys[key]
        name = f'K{len(self.consts)}'
        self.consts.append((name, kind, value))
        self.const_keys[key] = name
        return name

    def is_builtin(self, name):
        return name in self.builtins and not self.user_funcs(name)

    def var(self, name, sc=None):
        sc = sc or self.scope
        if name in sc.gnames:
            return f"G[{name!r}]"
        if name in sc.pnames:
            return f"PV[{name!r}]"
        return f"W[{name!r}]"

    def var_get(self, name, sc=None):
        """The value of a variable that may not have one yet (for an indexed
        assignment)."""
        sc = sc or self.scope
        if name in sc.gnames:
            return f"G.get({name!r}, NOVAL)"
        if name in sc.pnames:
            return f"PV.get({name!r}, NOVAL)"
        return f"W.get({name!r}, NOVAL)"

    def is_var(self, name):
        return name in self.scope.vars

    # ---- module ------------------------------------------------------------------
    def module_source(self, body_lines, body_map):
        """The whole module: constants, anonymous functions, then the body."""
        head = []
        for name, kind, value in self.consts:
            if kind == 'char':
                head.append(f"{name} = R.share(R.Char.of({value!r}))")
            elif kind == 'str':
                head.append(f"{name} = R.share(R.Str.of({value!r}))")
            elif kind == 'row':
                rows_ = '[' + ', '.join('[' + ', '.join(_flit(v) for v in row) + ']' for row in value) + ']'
                head.append(f"{name} = R.share(R.np.array({rows_}, dtype=float))")
            elif kind == 'int':
                cls, v = value
                head.append(f"{name} = R.share(R.np.array([[{v!r}]], dtype=R.np.{cls}))")
        if self.anon_texts:
            head.append(f'_ANON_TEXT = {self.anon_texts!r}')
        lines = head + [''] + self.top_lines + [''] + body_lines
        mapping = [0] * len(head) + [0] + self.top_map + [0] + body_map
        return '\n'.join(lines) + '\n', mapping

    # ---- programs ------------------------------------------------------------------
    def compile_program(self, prog, kind, ws_names=(), ws_fh=(), ws_globals=()):
        """A command line or script: `async def SCRIPT(W)` plus the file's
        local functions. ws_names are the variables of the workspace it will
        run in."""
        self.top_lines, self.top_map = [], []
        local = self.local = {f.name: f'LF_{f.name}' for f in prog.funcs}
        variables = assigned(prog.body) | set(ws_names)
        g, p = globals_of(prog.body)
        g |= set(ws_globals)
        fh_vars = self._fh_vars(prog.body, set(ws_fh), variables, local)
        dyn = True
        sc = Scope('script', '', variables, gnames=g, dynamic=dyn, local_funcs=local, fh_vars=fh_vars)
        out = Emitter()
        self.out = out
        self.scope = sc
        out.emit('async def SCRIPT(W):')
        out.ind += 1
        if g:
            out.emit('G = R.GLOBALS')
        out.emit('_na = -1; _no = -1')
        self.block(prog.body)
        out.emit('return None')
        out.ind -= 1
        body_lines, body_map = out.lines, out.map
        for f in prog.funcs:
            fl, fm = self.compile_function(f, local)
            body_lines += [''] + fl
            body_map += [0] + fm
        for fl, fm in self.extra:
            body_lines += [''] + fl
            body_map += [0] + fm
        return self.module_source(body_lines, body_map)

    def compile_file_functions(self, prog):
        """A function file: its functions, the first is the file's own."""
        self.top_lines, self.top_map = [], []
        local = self.local = {}

        def register(funcs):
            for f in funcs:
                local[f.name] = f'LF_{f.name}'
                register(f.subs)
        register(prog.funcs)
        body_lines, body_map = [], []
        for f in prog.funcs:
            fl, fm = self.compile_function(f, local)
            body_lines += fl + ['']
            body_map += fm + [0]
        for fl, fm in self.extra:
            body_lines += fl + ['']
            body_map += fm + [0]
        return self.module_source(body_lines, body_map)

    def compile_function(self, f, local, outer=()):
        """A function; `outer` lists the functions it is nested in, the
        nearest first, as (the Python name of their workspace, their
        variables). Its nested functions are defined inside it, so that a
        call or a handle reaches the workspace of this call of it."""
        body = f.body
        params = [p for p in f.params]
        own = set(p for p in params if p != '~') | set(f.outs)
        names_used = uses_names(body)
        # a name read here and assigned in a nested function is a variable here
        variables = assigned(body) | own | (names_used & _nested_assigned(f))
        if 'varargin' in params:
            variables.add('varargin')
        g, pn = globals_of(body)
        # the names shared with the nearest enclosing function that has them
        shared = {}
        for n in sorted((names_used | variables) - own - g - pn):
            for ws, outer_vars in outer:
                if n in outer_vars:
                    shared[n] = ws
                    break
        variables |= set(shared)
        dynamic = bool(names_used & _DYNAMIC_CALLS)
        fh_vars = self._fh_vars(body, set(p for p in params) | set(shared), variables, local)
        sc = Scope('function', f.name, variables, params, f.outs, g, pn, dynamic, local, fh_vars)
        sc.nested = bool(f.subs or outer)
        save_out, save_scope = self.out, self.scope
        out = Emitter()
        self.out = out
        self.scope = sc
        pyfn = local.get(f.name, f'LF_{f.name}')
        out.emit(f'async def {pyfn}(nargout, *args):', f.line)
        out.ind += 1
        nreq = len(params) - (1 if params and params[-1] == 'varargin' else 0)
        pnames = tuple(p for p in params if p not in ("~", "varargin"))
        if shared:
            links = ', '.join(f'{n!r}: {ws}' for n, ws in shared.items())
            out.emit(f'W = R.NestedWorkspace({f.name!r}, {pnames!r}, {{{links}}})', f.line)
        else:
            out.emit(f'W = R.Workspace({f.name!r}, {pnames!r})', f.line)
        out.emit('_na = len(args); _no = nargout; W.nargs = (_na, _no)', f.line)
        if not (params and params[-1] == 'varargin'):
            out.emit(f'if _na > {len(params)}: raise R.too_many_inputs({f.name!r})', f.line)
        if len(f.outs) and f.outs[-1] != 'varargout':
            out.emit(f'if nargout > {len(f.outs)}: raise R.too_many_outputs({f.name!r})', f.line)
        elif not f.outs:
            out.emit(f'if nargout > 0: raise R.too_many_outputs({f.name!r})', f.line)
        for i, pnm in enumerate(params[:nreq]):
            if pnm == '~':
                continue
            out.emit(f'if _na > {i}: W[{pnm!r}] = R.share(args[{i}])', f.line)
        if params and params[-1] == 'varargin':
            out.emit(f'W["varargin"] = R.varargin(args[{nreq}:])', f.line)
        if g:
            out.emit('G = R.GLOBALS', f.line)
        if pn:
            out.emit(f'PV = R.persistent_store({self.path!r}, {f.name!r})', f.line)
        for pnm, dexpr in (f.defaults or {}).items():
            if pnm in params:
                k = params.index(pnm)
                code, fresh = self.expr(dexpr)
                out.emit(f'if _na <= {k}: W[{pnm!r}] = {code}', f.line)
        if f.subs:
            ws = f'_W{len(outer)}'
            out.emit(f'{ws} = W', f.line)
            inner = ((ws, variables),) + tuple(outer)
            for s in f.subs:
                sl, sm = self.compile_function(s, local, inner)
                out.lines += ['    ' * out.ind + x if x else x for x in sl]
                out.map += sm
        self.block(body)
        out.emit(f'return R.fout(W, {tuple(f.outs)!r}, nargout, {f.name!r})', f.endline or f.line)
        out.ind -= 1
        lines, mp = out.lines, out.map
        self.out, self.scope = save_out, save_scope
        return lines, mp

    def _fh_vars(self, body, initial, variables, local):
        """The variables that may hold a function handle (so that x(...) may
        be a call): any assigned from something that is not obviously an
        array."""
        maybe = set(initial)
        assigns = []
        for s in _stmts(body):
            if type(s) is P.Assign:
                if s.multi:
                    for x in s.lhs:
                        r = _root(x) if x is not None else None
                        if r and type(x) is P.Id:
                            maybe.add(r)
                else:
                    x = s.lhs[0]
                    if type(x) is P.Id:
                        assigns.append((x.name, s.rhs))
            elif type(s) is P.Try and s.var:
                pass
        changed = True
        while changed:
            changed = False
            for name, rhs in assigns:
                if name in maybe:
                    continue
                if self._may_be_fh(rhs, maybe, variables, local):
                    maybe.add(name)
                    changed = True
        return maybe

    def _may_be_fh(self, e, maybe, variables, local):
        t = type(e)
        if t in (P.Num, P.Chr, P.DStr, P.Bin, P.Un, P.Post, P.Range, P.CellLit):
            return False
        if t is P.Paren:
            return self._may_be_fh(e.e, maybe, variables, local)
        if t is P.Mat:
            n = sum(len(r) for r in e.rows)
            if n != 1:
                return False
            return self._may_be_fh(e.rows[0][0], maybe, variables, local)
        if t is P.Anon or t is P.FHandle:
            return True
        if t is P.Id:
            if e.name in variables:
                return e.name in maybe
            info = self.builtins.get(e.name)
            return not (info is not None and info.arr and not self.user_funcs(e.name))
        if t is P.Index and not e.brace:
            b = e.base
            if type(b) is P.Id:
                if b.name in variables:
                    return b.name in maybe
                info = self.builtins.get(b.name)
                if info is not None and info.arr and not self.user_funcs(b.name):
                    return False
            return True
        return True

    # ---- statements ------------------------------------------------------------
    def block(self, body):
        if not body:
            self.out.emit('pass')
            return
        for s in body:
            self.stmt(s)

    def hook(self, line):
        if self.debug:
            self.out.emit(f'if T_: await R.H(W, {line}, M_)', line)

    def stmt(self, s):
        t = type(s)
        line = s.line
        self.hook(line)
        e = self.out.emit
        if t is P.Assign:
            if s.multi:
                return self.multi_assign(s)
            return self.assign(s)
        if t is P.ExprS:
            return self.expr_stmt(s)
        if t is P.If:
            first = True
            for cond, body in s.clauses:
                code = self.cond(cond)
                e(f'{"if" if first else "elif"} {code}:', cond.line)
                first = False
                self.out.ind += 1
                self.block(body)
                self.out.ind -= 1
            if s.els is not None:
                e('else:', line)
                self.out.ind += 1
                self.block(s.els)
                self.out.ind -= 1
            return
        if t is P.For:
            return self.for_stmt(s)
        if t is P.While:
            code = self.cond(s.cond)
            e(f'while {code}:', line)
            self.out.ind += 1
            e(f'if T_ or R.tk(): await R.H(W, {line}, M_)', line)
            self.scope.loop_depth += 1
            self.block(s.body)
            self.scope.loop_depth -= 1
            self.out.ind -= 1
            return
        if t is P.Switch:
            v = self.tmp()
            code, _ = self.expr(s.e)
            e(f'{v} = {code}', line)
            first = True
            for ce, body in s.cases:
                cc, _ = self.expr(ce)
                e(f'{"if" if first else "elif"} R.swmatch({v}, {cc}):', ce.line)
                first = False
                self.out.ind += 1
                self.block(body)
                self.out.ind -= 1
            if s.other is not None:
                if first:
                    e('if True:', line)
                else:
                    e('else:', line)
                self.out.ind += 1
                self.block(s.other)
                self.out.ind -= 1
            return
        if t is P.Try:
            e('try:', line)
            self.out.ind += 1
            self.block(s.body)
            self.out.ind -= 1
            ev = self.tmp()
            e(f'except Exception as {ev}:', line)
            self.out.ind += 1
            e(f'{ev} = R.caught({ev})', line)
            if s.var:
                e(f"{self.var(s.var)} = R.mexc({ev})", line)
            self.block(s.cbody)
            self.out.ind -= 1
            return
        if t is P.Break:
            if not self.scope.loop_depth:
                e('pass', line)
                return
            e('break', line)
            return
        if t is P.Continue:
            if not self.scope.loop_depth:
                e('pass', line)
                return
            e('continue', line)
            return
        if t is P.Return:
            if self.scope.kind == 'function':
                e(f'return R.fout(W, {tuple(self.scope.outs)!r}, nargout, {self.scope.name!r})', line)
            else:
                e('return None', line)
            return
        if t is P.Global:
            for n in s.names:
                if s.persistent:
                    e(f'if {n!r} not in PV: PV[{n!r}] = R.EMPTY()', line)
                else:
                    e(f'R.declare_global(W, {n!r})', line)
            return
        if t is P.Cmd:
            if s.name == '!':
                e(f"R.shell_escape({s.args[0]!r})", line)
                return
            if s.name in self.scope.vars:
                pass
            args = ', '.join(self.const('char', a) for a in s.args)
            call = self.call_code(s.name, [args] if args else [], '0', line)
            r = self.tmp()
            e(f'{r} = {call}', line)
            e(f'if {r} is not None: W["ans"] = {r}' + ('; R.show(W, "ans")' if s.show else ''), line)
            if s.name in ('clear', 'clearvars', 'load'):
                pass
            return
        raise CompileError(f'Unsupported statement {t.__name__}', line)

    def cond(self, c):
        """The condition of if/while; & and | short-circuit here."""
        t = type(c)
        if t is P.Bin and c.op in ('&&', '||', '&', '|'):
            if c.op in ('&&', '||'):
                a = self.cond_operand(c.a, c.op)
                b = self.cond_operand(c.b, c.op)
                return f'({a} {"and" if c.op == "&&" else "or"} {b})'
            a, _ = self.expr(c.a)
            b, _ = self.expr(c.b)
            tv = self.tmp()
            if c.op == '&':
                return f'(False if R.is_false1({tv} := {a}) else R.truth(R.and_({tv}, {b})))'
            return f'(True if R.is_true1({tv} := {a}) else R.truth(R.or_({tv}, {b})))'
        code, _ = self.expr(c)
        return f'R.truth({code})'

    def cond_operand(self, e, op):
        if type(e) is P.Bin and e.op in ('&&', '||'):
            return self.cond(e)
        code, _ = self.expr(e)
        return f'R.sc_truth({code}, {op!r})'

    def for_stmt(self, s):
        if s.par and not self.scope.in_parfor:
            return self.parfor_stmt(s)
        self.loop_over(s, self.loop_values(s.it, 'R.forrange'))

    def loop_values(self, it, fn):
        """The code of a for loop's values: fn(a, b[, s]) over a range, else R.forit(value)."""
        if type(it) is P.Range:
            a, _ = self.expr(it.a)
            b, _ = self.expr(it.b)
            if it.s is None:
                return f'{fn}({a}, {b})'
            st, _ = self.expr(it.s)
            return f'{fn}({a}, {b}, {st})'
        code, _ = self.expr(it)
        return f'R.forit({code})'

    def loop_over(self, s, src):
        e = self.out.emit
        line = s.line
        v = self.tmp()
        var = s.var
        e(f'for {v} in {src}:', line)
        self.out.ind += 1
        if type(var) is P.Id:
            e(f'{self.var(var.name)} = {v}', line)
        else:
            self.store(var, v, line, fresh=False)
        e(f'if T_ or R.tk(): await R.H(W, {line}, M_)', line)
        self.scope.loop_depth += 1
        self.block(s.body)
        self.scope.loop_depth -= 1
        self.out.ind -= 1

    def parfor_stmt(self, s):
        """parfor: its passes on the pool's workers when the body allows (see parfor.py),
        else, or when there is no pool, one at a time as a for loop."""
        from . import parfor as PF
        e = self.out.emit
        line = s.line
        if self.scope.nested:
            plan = 'it is in a function that has nested functions, or is one'
        elif self.scope.kind not in ('function', 'script'):
            plan = 'it is not in a function or a script'
        else:
            plan = PF.plan(s, self.is_var, self.scope.dynamic)
        vals = self.tmp()
        e(f'{vals} = {self.loop_values(s.it, "R.parfor_values")}', line)
        if isinstance(plan, str):
            e(f'R.parfor_note({plan!r}, {line}, M_, _PF_NOTED)', line)
            self.loop_over(s, vals)
            return
        fn = self.parfor_chunk(s, plan)
        mw = self.expr(s.workers)[0] if s.workers is not None else 'None'
        e(f'if not await R.parfor(W, {fn}, {plan.literal()!r}, {vals}, {mw}):', line)
        self.out.ind += 1
        self.loop_over(s, vals)
        self.out.ind -= 1

    def parfor_chunk(self, s, plan):
        """The parfor's body as a module-level function the pool's workers call with
        a block of passes: PF<n>(nargout, ks, ins) -> R.parfor_collect(...). ins holds
        the broadcast and sliced variables' values; reductions start unset."""
        self.parfor_n += 1
        pyfn = f'PF{self.parfor_n}'
        k = plan.var
        sliced = [n for n, _, _ in plan.sliced]
        reds = [n for n, _, _ in plan.reductions]
        variables = assigned(s.body) | set(plan.broadcast) | set(sliced) | set(reds) | {k}
        fh_vars = self._fh_vars(s.body, set(plan.broadcast) | set(sliced), variables, self.local)
        # in a script, names made while it runs (load) are looked up then, as where the loop is
        sc = Scope('function', 'parfor', variables, (), (), (), (), self.scope.dynamic, self.local, fh_vars)
        sc.in_parfor = True
        sc.reductions = plan.red_stmts
        save_out, save_scope = self.out, self.scope
        out = Emitter()
        self.out, self.scope = out, sc
        e = out.emit
        line = s.line
        e(f'async def {pyfn}(nargout, ks, ins):', line)
        out.ind += 1
        e("W = R.Workspace('parfor', ())", line)
        e('_na = 0; _no = 0', line)
        e('for _n, _v in ins.items(): W[_n] = R.share(_v)', line)
        for n in reds:
            e(f'W[{n!r}] = R.RED_UNSET', line)
        v = self.tmp()
        e(f'for {v} in ks:', line)
        out.ind += 1
        e(f'W[{k!r}] = {v}', line)
        e(f'if T_ or R.tk(): await R.H(W, {line}, M_)', line)
        sc.loop_depth += 1
        self.block(s.body)
        sc.loop_depth -= 1
        out.ind -= 1
        e(f'return R.parfor_collect(W, ks, {plan.sliced!r}, {reds!r})', line)
        out.ind -= 1
        self.out, self.scope = save_out, save_scope
        self.extra.append((out.lines, out.map))
        return pyfn

    def expr_stmt(self, s):
        e = self.out.emit
        x = s.e
        line = s.line
        t = type(x)
        if t is P.Id:
            name = x.name
            if self.is_var(name) or (name in self.scope.gnames or name in self.scope.pnames):
                if s.show:
                    e(f'R.show_value({name!r}, {self.var(name)})', line)
                else:
                    e(f'{self.var(name)}', line)
                return
            if self.scope.dynamic and name not in self.scope.local_funcs:
                # a variable made while the line runs (by load or eval) shows by its name and leaves ans alone
                e(f'if {name!r} in W:', line)
                self.out.ind += 1
                e(f'R.show_value({name!r}, W[{name!r}])' if s.show else 'pass', line)
                self.out.ind -= 1
                e('else:', line)
                self.out.ind += 1
                r = self.tmp()
                e(f'{r} = {self.call_expr(x, "0")}', line)
                e(f'if {r} is not None: W["ans"] = {r}' + ('; R.show(W, "ans")' if s.show else ''), line)
                self.out.ind -= 1
                return
        # a call at statement level asks for no output; its first, if any, is ans
        if self.is_call(x):
            code = self.call_expr(x, '0')
            r = self.tmp()
            e(f'{r} = {code}', line)
            e(f'if {r} is not None: W["ans"] = {r}' + ('; R.show(W, "ans")' if s.show else ''), line)
            return
        if self.is_cslist(x):
            code = self.list_expr(x)
            e(f'R.ans_list(W, {code}, {s.show})', line)
            return
        code, fresh = self.expr(x)
        e(f'W["ans"] = {code if fresh else f"R.share({code})"}', line)
        if s.show:
            e('R.show(W, "ans")', line)

    def dotted(self, x):
        """pkg.name for a field chain on a name that is not a variable
        (containers.Map, matlab.lang.makeValidName), else None."""
        parts = []
        n = x
        while type(n) is P.Field and isinstance(n.name, str):
            parts.append(n.name)
            n = n.base
        if type(n) is not P.Id or not parts:
            return None
        if self.is_var(n.name) or n.name in self.scope.gnames or n.name in self.scope.pnames:
            return None
        parts.append(n.name)
        return '.'.join(reversed(parts))

    def is_call(self, x):
        """A call to a function (not indexing a variable) at the top of an
        expression."""
        t = type(x)
        if t is P.Id:
            n = x.name
            return not self.is_var(n) and n not in ('nargin', 'nargout') or n in ('nargin', 'nargout') and False
        if t is P.Index and not x.brace and type(x.base) is P.Id:
            n = x.base.name
            if self.is_var(n):
                return n in self.scope.fh_vars
            return True
        if t is P.Index and not x.brace and self.dotted(x.base):
            return True
        if t is P.Field and self.dotted(x):
            return True
        return False

    def is_cslist(self, x):
        t = type(x)
        if t is P.Index and x.brace:
            return True
        if t is P.Field:
            return not self.dotted(x)
        return False

    # ---- assignment ---------------------------------------------------------------
    def assign(self, s):
        lhs = s.lhs[0]
        line = s.line
        rhs = s.rhs
        red = self.scope.reductions.get(id(s)) if self.scope.reductions else None
        if red is not None:
            name, op, prefix, other = red
            code, _ = self.expr(other)
            self.out.emit(f'W[{name!r}] = R.red_step({op!r}, {prefix}, W[{name!r}], {code})', line)
            return
        if self.is_cslist(rhs) and not (type(lhs) is P.Id):
            code = f'R.one({self.list_expr(rhs)})'
            fresh = False
        elif self.is_cslist(rhs):
            code = f'R.one({self.list_expr(rhs)})'
            fresh = False
        else:
            code, fresh = self.expr(rhs)
        self.store(lhs, code, line, fresh)
        if s.show:
            root = _root(lhs)
            self.out.emit(f'R.show_value({root!r}, {self.var(root)})', line)

    def store(self, lhs, code, line, fresh):
        """Write a value into an assignment target."""
        e = self.out.emit
        t = type(lhs)
        if t is P.Id:
            name = lhs.name
            if name in ('nargin', 'nargout') and name not in self.scope.vars:
                self.scope.vars.add(name)
            e(f'{self.var(name)} = {code if fresh else f"R.share({code})"}', line)
            return
        root = _root(lhs)
        if root is None:
            raise CompileError('Invalid assignment target.', line)
        if root not in self.scope.vars:
            self.scope.vars.add(root)
        steps = []
        n = lhs
        while type(n) in (P.Index, P.Field):
            steps.append(n)
            n = n.base
        steps.reverse()
        target = self.var(root)
        cur = self.var_get(root)
        if len(steps) == 1:
            st = steps[0]
            if type(st) is P.Field:
                key = repr(st.name) if isinstance(st.name, str) else f'R.dyn_name({self.expr(st.name)[0]})'
                e(f'{target} = R.fasgn({cur}, {key}, {code if fresh else f"R.share({code})"})', line)
                return
            tv = self.tmp()
            args = self.index_args(st.args, tv)
            if st.brace:
                e(f'{target} = R.casgn(({tv} := {cur}), {args}, {code if fresh else f"R.share({code})"})', line)
            else:
                e(f'{target} = R.asgn(({tv} := {cur}), {args}, {code})', line)
            return
        parts = []
        for st in steps:
            if type(st) is P.Field:
                key = repr(st.name) if isinstance(st.name, str) else f'R.dyn_name({self.expr(st.name)[0]})'
                parts.append(f"('.', {key})")
            else:
                kind = '{}' if st.brace else '()'
                if any(self.has_end(a) for a in st.args):
                    tv = self.tmp()
                    args = self.index_args(st.args, tv)
                    parts.append(f"('{kind}', lambda {tv}: {args})")
                else:
                    args = self.index_args(st.args, None)
                    parts.append(f"('{kind}', {args})")
        e(f'{target} = R.asgn_chain({cur}, ({", ".join(parts)},), {code if fresh else f"R.share({code})"})', line)

    def multi_assign(self, s):
        e = self.out.emit
        line = s.line
        n = len(s.lhs)
        rhs = s.rhs
        r = self.tmp()
        if self.is_cslist(rhs):
            e(f'{r} = R.need({self.list_expr(rhs)}, {n})', line)
        elif self.is_call(rhs) or type(rhs) is P.Index:
            code = self.call_expr(rhs, str(n), multi=True)
            e(f'{r} = R.outs({code}, {n})', line)
        else:
            raise CompileError('Too many output arguments.' if True else '', line)
        for i, x in enumerate(s.lhs):
            if x is None:
                continue
            self.store(x, f'{r}[{i}]', line, fresh=False)
        if s.show:
            for x in s.lhs:
                if x is None:
                    continue
                root = _root(x)
                e(f'R.show_value({root!r}, {self.var(root)})', line)

    # ---- expressions ---------------------------------------------------------
    def has_end(self, e):
        """Whether an index argument uses `end` for the indexed value (not
        inside a nested index of a variable)."""
        found = [False]

        def visit(x):
            t = type(x)
            if t is P.End:
                found[0] = True
                return
            if t is P.Bin:
                visit(x.a)
                visit(x.b)
            elif t in (P.Un, P.Post):
                visit(x.a)
            elif t is P.Paren:
                visit(x.e)
            elif t is P.Range:
                visit(x.a)
                if x.s is not None:
                    visit(x.s)
                visit(x.b)
            elif t in (P.Mat, P.CellLit):
                for r in x.rows:
                    for y in r:
                        visit(y)
            elif t is P.Index:
                b = x.base
                if type(b) is P.Id and self.is_var(b.name):
                    visit(b)
                    return   # its own end
                visit(b)
                for a in x.args:
                    visit(a)
            elif t is P.Field:
                visit(x.base)
        visit(e)
        return found[0]

    def index_args(self, args, tv, endctx=None):
        """The tuple of index values; `end` measures tv."""
        save = getattr(self, '_end', None)
        self._end = (tv, len(args))
        parts = []
        for k, a in enumerate(args):
            self._endpos = k
            self._end = (tv, len(args), k)
            if type(a) is P.Colon:
                parts.append('COLON')
            elif self.is_cslist(a):
                parts.append('*' + self.list_expr(a))
            else:
                parts.append(self.expr(a)[0])
        self._end = save
        return pytuple(parts)

    def call_args(self, args, tv=None):
        """A function's arguments, cs-lists spread out. When the call may
        be indexing a variable instead (tv holds it), `end` measures tv."""
        if tv is not None:
            save = getattr(self, '_end', None)
            parts = []
            for k, a in enumerate(args):
                self._end = (tv, len(args), k)
                if type(a) is P.Colon:
                    parts.append(self.const('char', ':'))
                elif self.is_cslist(a):
                    parts.append('*' + self.list_expr(a))
                else:
                    parts.append(self.expr(a)[0])
            self._end = save
            return parts
        parts = []
        for a in args:
            if type(a) is P.Colon:
                parts.append(self.const('char', ':'))
            elif self.is_cslist(a):
                parts.append('*' + self.list_expr(a))
            else:
                parts.append(self.expr(a)[0])
        return parts

    def call_code(self, name, argparts, nargout, line=0):
        """A call to a named function."""
        a = ', '.join(argparts)
        lf = self.scope.local_funcs.get(name)
        if lf:
            return f'(await {lf}({nargout}{", " if a else ""}{a}))'
        if self.is_builtin(name):
            info = self.builtins[name]
            attr = 'B.' + pyname(name) if '.' not in name else f'R.BI[{name!r}]'
            pre = 'W, ' if info.ws else ''
            call = f'{attr}({pre}{nargout}{", " if a else ""}{a})'
            return f'(await {call})' if info.aw else call
        return f'(await R.call(W, {name!r}, {nargout}, ({a}{"," if a and len(argparts) == 1 else ""})))'

    def call_expr(self, x, nargout, multi=False):
        """An expression that is a call (or may be): f, f(args), v(args) with
        v a function handle."""
        t = type(x)
        if t is P.Id:
            if x.name in ('nargin', 'nargout') and not self.is_var(x.name):
                return self.expr(x)[0]
            return self.call_code(x.name, [], nargout, x.line)
        if t is P.Index and not x.brace and type(x.base) is P.Id:
            n = x.base.name
            if self.is_var(n):
                v = self.var(n)
                tv = self.tmp()
                args = self.index_args(x.args, tv)
                if n in self.scope.fh_vars:
                    cargs = pytuple(self.call_args(x.args, tv))
                    return f'((await R.fcall({tv}, {nargout}, {cargs})) if isinstance({tv} := {v}, FH) else R.idx_n({tv}, {args}, {nargout}))'
                return f'R.idx_n(({tv} := {v}), {args}, {nargout})'
            if n in ('nargin', 'nargout') and n not in self.scope.local_funcs and not self.user_funcs(n):
                return self.call_code(n, self.call_args(x.args), nargout, x.line)
            if n in ('table', 'timetable', 'innerjoin', 'outerjoin', 'synchronize') and not self.scope.local_funcs.get(n) and self.is_builtin(n) and not any(self.is_cslist(a) for a in x.args):
                # the names of the variables given (as inputname would tell): the table's variable names
                names = [a.name if type(a) is P.Id and self.is_var(a.name) else None for a in x.args]
                return self.call_code(n, self.call_args(x.args) + [f'R.ArgNames({names!r})'], nargout, x.line)
            return self.call_code(n, self.call_args(x.args), nargout, x.line)
        if t is P.Index and not x.brace and self.dotted(x.base):
            return self.call_code(self.dotted(x.base), self.call_args(x.args), nargout, x.line)
        if t is P.Field and self.dotted(x):
            return self.call_code(self.dotted(x), [], nargout, x.line)
        if t is P.Index and not x.brace:
            tv = self.tmp()
            base, _ = self.expr(x.base)
            args = self.index_args(x.args, tv)
            cargs = pytuple(self.call_args(x.args, tv))
            return f'((await R.fcall({tv}, {nargout}, {cargs})) if isinstance({tv} := {base}, FH) else R.idx_n({tv}, {args}, {nargout}))'
        code, _ = self.expr(x)
        if multi:
            return f'R.single_out({code}, {nargout})'
        return code

    def list_expr(self, x):
        """A cs-list expression as a Python list."""
        t = type(x)
        if t is P.Index and x.brace:
            tv = self.tmp()
            base, _ = self.expr(x.base)
            args = self.index_args(x.args, tv)
            return f'R.cidx(({tv} := {base}), {args})'
        if t is P.Field:
            base, _ = self.expr(x.base)
            if isinstance(x.name, str):
                return f'R.fld({base}, {x.name!r})'
            return f'R.fld({base}, R.dyn_name({self.expr(x.name)[0]}))'
        code, _ = self.expr(x)
        return f'[{code}]'

    def expr(self, x):
        """(code, fresh): the Python expression for one value, and whether it
        is a new value nobody else holds."""
        t = type(x)
        if t is P.Num:
            v = x.v
            if isinstance(x.cls, tuple):
                kind, suffix = x.cls
                cls = {'u8': 'uint8', 'u16': 'uint16', 'u32': 'uint32', 'u64': 'uint64',
                       's8': 'int8', 's16': 'int16', 's32': 'int32', 's64': 'int64'}.get(suffix)
                if cls is None:
                    iv = int(v.real if isinstance(v, complex) else v)
                    cls = 'uint8' if iv < 2 ** 8 else 'uint16' if iv < 2 ** 16 else 'uint32' if iv < 2 ** 32 else 'uint64'
                return self.const('int', (cls, int(v.real if isinstance(v, complex) else v))), False
            if isinstance(v, complex):
                return f'complex({_flit(v.real)}, {_flit(v.imag)})', True
            return _flit(v), True
        if t is P.Chr:
            return self.const('char', x.v), False
        if t is P.DStr:
            return self.const('str', x.v), False
        if t is P.Id:
            return self.name_expr(x)
        if t is P.Paren:
            if self.is_cslist(x.e):
                return f'R.one({self.list_expr(x.e)})', False
            return self.expr(x.e)
        if t is P.Bin:
            return self.binary(x)
        if t is P.Un:
            a, _ = self.expr(x.a)
            fn = {'-': 'R.uminus', '+': 'R.uplus', '~': 'R.not_'}[x.op]
            return f'{fn}({a})', True
        if t is P.Post:
            a, _ = self.expr(x.a)
            fn = 'R.ctranspose' if x.op == "'" else 'R.transpose'
            return f'{fn}({a})', True
        if t is P.Range:
            a, _ = self.expr(x.a)
            b, _ = self.expr(x.b)
            if x.s is None:
                return f'R.colon({a}, {b})', True
            s, _ = self.expr(x.s)
            return f'R.colon({a}, {s}, {b})', True
        if t is P.Mat:
            return self.matrix(x)
        if t is P.CellLit:
            rows = []
            for r in x.rows:
                parts = []
                for el in r:
                    if self.is_cslist(el):
                        parts.append('*' + self.list_expr(el))
                    else:
                        parts.append(self.expr(el)[0])
                rows.append('[' + ', '.join(parts) + ']')
            return f'R.cellmat([{", ".join(rows)}])', True
        if t is P.Colon:
            return self.const('char', ':'), False
        if t is P.End:
            ctx = getattr(self, '_end', None)
            if not ctx or ctx[0] is None:
                raise CompileError("'end' is used outside of an index of a variable.", x.line)
            tv, n, k = ctx
            return f'R.endv({tv}, {k}, {n})', True
        if t is P.Index:
            if x.brace:
                return f'R.one({self.list_expr(x)})', False
            b = x.base
            if type(b) is P.Id and not self.is_var(b.name) and not b.name in self.scope.gnames:
                if b.name in ('nargin', 'nargout') and not x.args:
                    return self.name_expr(b)
                return self.call_expr(x, '1'), False
            if type(b) is P.Id and (self.is_var(b.name) or b.name in self.scope.gnames):
                n = b.name
                v = self.var(n)
                tv = self.tmp()
                args = self.index_args(x.args, tv)
                if n in self.scope.fh_vars:
                    cargs = pytuple(self.call_args(x.args, tv))
                    return f'((await R.fcall({tv}, 1, {cargs})) if isinstance({tv} := {v}, FH) else R.idx({tv}, {args}))', False
                if any(self.has_end(a) for a in x.args):
                    return f'R.idx(({tv} := {v}), {args})', True
                return f'R.idx({v}, {args})', True
            return self.call_expr(x, '1'), False
        if t is P.Field:
            d = self.dotted(x)
            if d:
                return self.call_code(d, [], '1', x.line), False
            base, _ = self.expr(x.base)
            if isinstance(x.name, str):
                return f'R.fld1({base}, {x.name!r})', False
            return f'R.fld1({base}, R.dyn_name({self.expr(x.name)[0]}))', False
        if t is P.Anon:
            return self.anon(x), True
        if t is P.FHandle:
            name = x.name
            lf = self.scope.local_funcs.get(name)
            if lf:
                return f'R.LocalFH({name!r}, {lf})', True
            return f'R.fh({name!r})', True
        raise CompileError(f'Unsupported expression {t.__name__}', getattr(x, 'line', 0))

    _BINOPS = {'+': 'R.plus', '-': 'R.minus', '.*': 'R.times', './': 'R.rdivide', '.\\': 'R.ldivide',
               '*': 'R.mtimes', '/': 'R.mrdivide', '\\': 'R.mldivide', '.^': 'R.power', '^': 'R.mpower',
               '==': 'R.eq', '~=': 'R.ne', '<': 'R.lt', '<=': 'R.le', '>': 'R.gt', '>=': 'R.ge',
               '&': 'R.and_', '|': 'R.or_'}

    def binary(self, x):
        op = x.op
        if op in ('&&', '||'):
            a = self.cond_operand(x.a, op)
            b = self.cond_operand(x.b, op)
            return f'({a} {"and" if op == "&&" else "or"} {b})', True
        a, _ = self.expr(x.a)
        b, _ = self.expr(x.b)
        return f'{self._BINOPS[op]}({a}, {b})', True

    def matrix(self, x):
        rows = x.rows
        # a literal of numbers is a constant
        if rows and all(type(el) is P.Num and not isinstance(el.v, complex) and not isinstance(el.cls, tuple) for r in rows for el in r):
            vals = [[float(el.v) for el in r] for r in rows]
            if len(set(len(r) for r in vals)) == 1:
                if len(vals) == 1 and len(vals[0]) == 1:
                    return _flit(vals[0][0]), True
                return self.const('row', vals), False
        if not rows:
            return 'R.EMPTY()', True
        out = []
        any_list = False
        for r in rows:
            parts = []
            for el in r:
                if self.is_cslist(el):
                    parts.append('*' + self.list_expr(el))
                    any_list = True
                else:
                    parts.append(self.expr(el)[0])
            out.append('[' + ', '.join(parts) + ']')
        if len(out) == 1:
            if len(rows[0]) == 1 and not any_list:
                # [x] is x
                return f'R.hcat({out[0]})', False
            return f'R.hcat({out[0]})', True
        return f'R.vcat([R.hcat({r}) for r in [{", ".join(out)}]])' if False else f'R.matrix([{", ".join(out)}])', True

    def name_expr(self, x):
        """A bare name: a variable's value, or a call with no arguments."""
        name = x.name
        sc = self.scope
        if name in sc.gnames:
            return f"G[{name!r}]", False
        if name in sc.pnames:
            return f"PV[{name!r}]", False
        if name in sc.vars:
            return f"W[{name!r}]", False
        if name == 'nargin' and sc.kind == 'function':
            return 'float(_na)', True
        if name == 'nargout' and sc.kind == 'function':
            return 'float(_no)', True
        if name == 'end':
            raise CompileError("'end' outside an index.", x.line)
        if sc.dynamic and not self.is_builtin(name) and name not in sc.local_funcs:
            return f'(await R.vget(W, {name!r}))', False
        return self.call_code(name, [], '1', x.line), False

    # ---- anonymous functions --------------------------------------------------------
    def anon(self, x):
        """@(params) body: a module-level async function, given the values it
        captured when it is made."""
        self.anon_n += 1
        fname = f'_A{self.anon_n}'
        self.anon_texts[fname] = x.text
        params = [p for p in x.params]
        free = set()

        def visit(e):
            if type(e) is P.Id:
                free.add(e.name)
            elif type(e) is P.Anon:
                inner = set()
                _walk_expr(e.body, lambda y: inner.add(y.name) if type(y) is P.Id else (visit(y) if type(y) is P.Anon else None))
                free.update(inner - set(e.params))
        _walk_expr(x.body, visit)
        free -= set(params)
        outer = self.scope
        captured = sorted(n for n in free if n in outer.vars or n in outer.gnames or n in outer.pnames)
        variables = set(p for p in params if p not in ('~', 'varargin')) | set(captured)
        if 'varargin' in params:
            variables.add('varargin')
        fh = set(variables)
        sc = Scope('anon', '@', variables, params, (), (), (), outer.dynamic and False, outer.local_funcs, fh)
        save_out, save_scope, save_end = self.out, self.scope, getattr(self, '_end', None)
        self.out = Emitter()
        self.scope = sc
        self._end = None
        e = self.out.emit
        e(f'async def {fname}(_no, _C, args):', x.line)
        self.out.ind += 1
        e(f'W = R.anon_ws(_C, {tuple(params)!r}, args)', x.line)
        e('_na = len(args)', x.line)
        body = x.body
        if self.is_call(body) and not self.is_cslist(body):
            code = self.call_expr(body, '_no')
            e(f'return {code}', x.line)
        elif self.is_cslist(body):
            e(f'return R.anon_list({self.list_expr(body)}, _no)', x.line)
        else:
            code, _ = self.expr(body)
            e(f'return R.anon_one({code}, _no)', x.line)
        self.out.ind -= 1
        lines, mp = self.out.lines, self.out.map
        self.top_lines += lines + ['']
        self.top_map += mp + [0]
        self.out, self.scope, self._end = save_out, save_scope, save_end
        cap = ', '.join(f'{n!r}: R.share({self.var(n, outer)})' for n in captured)
        nparams = len([p for p in params if p != 'varargin'])
        return f'R.Anon({fname}, {x.text!r}, {{{cap}}}, {nparams}, {"varargin" in params})'


def compile_source(text, builtins, kind='command', user_funcs=None, ws_names=(), ws_fh=(), ws_globals=(),
                   modname='<command>', path='', debug=True, is_var=None):
    """Parse and compile; returns (python source, line map, program)."""
    if is_var is None:
        if kind == 'command':
            names = set(ws_names)
            is_var = lambda n: n in names
        else:
            names = P.assigned_names(text) | set(ws_names)
            is_var = lambda n: n in names
    prog = P.parse(text, is_var, 'file' if kind != 'command' else 'command')
    if kind == 'command' and prog.kind == 'function':
        # a function's text typed, run as a section or given to eval
        f = prog.funcs[0]
        raise CompileError(f'Functions are defined in program files: save {f.name} as {f.name}.m, then call it by that name.', f.line)
    c = Compiler(builtins, user_funcs, modname, path)
    c.debug = debug
    if prog.kind == 'function':
        src, mp = c.compile_file_functions(prog)
    else:
        src, mp = c.compile_program(prog, prog.kind, ws_names, ws_fh, ws_globals)
    return src, mp, prog
