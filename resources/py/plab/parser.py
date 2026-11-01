"""The parser: tokens to a syntax tree.

Precedence, lowest first: || then && then | then & then comparisons, the
colon, + and -, the multiplications and divisions, the unary operators, and
last the powers and transposes (left to right: 2^3^2 is 64, -2^2 is -4,
and 2^-1 is allowed).
"""
import re

from .lexer import tokenize, Tok, LexError, KEYWORDS, BLOCK_OPENERS
from .values import MError


class ParseError(MError):
    def __init__(self, msg, line, pos=None):
        super().__init__('MATLAB:parse', msg)
        self.line = line
        self.pos = pos


# ---- nodes ------------------------------------------------------------------------

class Node:
    __slots__ = ('line',)


class Num(Node):
    __slots__ = ('v', 'cls')

    def __init__(self, v, line, cls=None):
        self.v = v
        self.line = line
        self.cls = cls


class Chr(Node):
    __slots__ = ('v',)

    def __init__(self, v, line):
        self.v = v
        self.line = line


class DStr(Node):
    __slots__ = ('v',)

    def __init__(self, v, line):
        self.v = v
        self.line = line


class Id(Node):
    __slots__ = ('name',)

    def __init__(self, name, line):
        self.name = name
        self.line = line


class Colon(Node):
    __slots__ = ()

    def __init__(self, line):
        self.line = line


class End(Node):
    __slots__ = ()

    def __init__(self, line):
        self.line = line


class Bin(Node):
    __slots__ = ('op', 'a', 'b')

    def __init__(self, op, a, b, line):
        self.op = op
        self.a = a
        self.b = b
        self.line = line


class Un(Node):
    __slots__ = ('op', 'a')

    def __init__(self, op, a, line):
        self.op = op
        self.a = a
        self.line = line


class Post(Node):
    __slots__ = ('op', 'a')

    def __init__(self, op, a, line):
        self.op = op
        self.a = a
        self.line = line


class Range(Node):
    __slots__ = ('a', 's', 'b')

    def __init__(self, a, s, b, line):
        self.a = a
        self.s = s
        self.b = b
        self.line = line


class Mat(Node):
    __slots__ = ('rows',)

    def __init__(self, rows, line):
        self.rows = rows
        self.line = line


class CellLit(Node):
    __slots__ = ('rows',)

    def __init__(self, rows, line):
        self.rows = rows
        self.line = line


class Index(Node):
    """base(args) when brace is False, base{args} when True."""
    __slots__ = ('base', 'args', 'brace')

    def __init__(self, base, args, brace, line):
        self.base = base
        self.args = args
        self.brace = brace
        self.line = line


class Field(Node):
    """base.name, or base.(expr) when name is a node."""
    __slots__ = ('base', 'name')

    def __init__(self, base, name, line):
        self.base = base
        self.name = name
        self.line = line


class Anon(Node):
    __slots__ = ('params', 'body', 'text')

    def __init__(self, params, body, text, line):
        self.params = params
        self.body = body
        self.text = text
        self.line = line


class FHandle(Node):
    __slots__ = ('name',)

    def __init__(self, name, line):
        self.name = name
        self.line = line


class Tilde(Node):
    """~ as an output placeholder or an ignored input."""
    __slots__ = ()

    def __init__(self, line):
        self.line = line


# statements

class Stmt:
    __slots__ = ('line',)


class ExprS(Stmt):
    __slots__ = ('e', 'show')

    def __init__(self, e, show, line):
        self.e = e
        self.show = show
        self.line = line


class Assign(Stmt):
    __slots__ = ('lhs', 'rhs', 'show', 'multi')

    def __init__(self, lhs, rhs, show, multi, line):
        self.lhs = lhs
        self.rhs = rhs
        self.show = show
        self.multi = multi
        self.line = line


class If(Stmt):
    __slots__ = ('clauses', 'els')

    def __init__(self, clauses, els, line):
        self.clauses = clauses
        self.els = els
        self.line = line


class For(Stmt):
    """for var = it ... end; par for parfor, workers its (parfor (k = 1:n, M)) limit or None."""
    __slots__ = ('var', 'it', 'body', 'par', 'workers')

    def __init__(self, var, it, body, line, par=False, workers=None):
        self.var = var
        self.it = it
        self.body = body
        self.line = line
        self.par = par
        self.workers = workers


class While(Stmt):
    __slots__ = ('cond', 'body')

    def __init__(self, cond, body, line):
        self.cond = cond
        self.body = body
        self.line = line


class Switch(Stmt):
    __slots__ = ('e', 'cases', 'other')

    def __init__(self, e, cases, other, line):
        self.e = e
        self.cases = cases
        self.other = other
        self.line = line


class Try(Stmt):
    __slots__ = ('body', 'var', 'cbody')

    def __init__(self, body, var, cbody, line):
        self.body = body
        self.var = var
        self.cbody = cbody
        self.line = line


class Break(Stmt):
    __slots__ = ()

    def __init__(self, line):
        self.line = line


class Continue(Stmt):
    __slots__ = ()

    def __init__(self, line):
        self.line = line


class Return(Stmt):
    __slots__ = ()

    def __init__(self, line):
        self.line = line


class Global(Stmt):
    __slots__ = ('names', 'persistent')

    def __init__(self, names, persistent, line):
        self.names = names
        self.persistent = persistent
        self.line = line


class Cmd(Stmt):
    __slots__ = ('name', 'args', 'show')

    def __init__(self, name, args, show, line):
        self.name = name
        self.args = args
        self.show = show
        self.line = line


class Func:
    __slots__ = ('name', 'params', 'outs', 'body', 'line', 'endline', 'subs', 'defaults', 'parent')

    def __init__(self, name, params, outs, body, line, endline, subs, defaults=None):
        self.name = name
        self.params = params
        self.outs = outs
        self.body = body
        self.line = line
        self.endline = endline
        self.subs = subs          # nested functions
        self.defaults = defaults or {}
        self.parent = None


class Program:
    __slots__ = ('body', 'funcs', 'kind', 'text')

    def __init__(self, body, funcs, kind, text=''):
        self.body = body
        self.funcs = funcs
        self.kind = kind          # 'script', 'function', 'command'
        self.text = text


# ---- parser -----------------------------------------------------------------------

_CMP = ('==', '~=', '<', '<=', '>', '>=')
_MUL = ('*', '/', '\\', '.*', './', '.\\')
_STOP_KW = {'end', 'else', 'elseif', 'case', 'otherwise', 'catch', 'function'}


def _value_start(t, in_index):
    if t.k in ('num', 'str', 'dstr', 'id'):
        return True
    if t.k == 'op' and t.v in ('(', '[', '{', '@', '-', '+', '~'):
        return True
    if t.k == 'kw' and t.v == 'end' and in_index:
        return True
    return False


class Parser:
    def __init__(self, text, is_var=None, kind='command'):
        self.text = text
        self.toks = tokenize(text, is_var)
        self.i = 0
        self.mat = [False]       # inside [ ] or { } (whitespace separates)
        self.in_index = 0
        self.kind = kind
        self.end_funcs = None

    # tokens
    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def at(self, k, v=None):
        t = self.toks[self.i]
        return t.k == k and (v is None or t.v == v)

    def at_op(self, v):
        t = self.toks[self.i]
        return t.k == 'op' and t.v == v

    def expect_op(self, v, msg=None):
        t = self.toks[self.i]
        if t.k == 'op' and t.v == v:
            self.i += 1
            return t
        raise self.err(msg or f"Invalid expression. Check for missing or extra characters.", t)

    def err(self, msg, t=None):
        t = t or self.peek()
        return ParseError(msg, t.line, t.pos)

    # ---- program -------------------------------------------------------------
    def program(self):
        toks = self.toks
        # are functions closed by end? count block openers and ends outside brackets
        depth = 0
        opens = ends = nfun = 0
        for ti, t in enumerate(toks):
            if t.k == 'id' and t.v == 'arguments' and depth == 0 and (ti == 0 or toks[ti - 1].k == 'nl') and \
                    toks[ti + 1].k in ('nl',) or (t.k == 'id' and t.v == 'arguments' and depth == 0 and toks[ti + 1].k == 'op' and toks[ti + 1].v == '(' and (ti == 0 or toks[ti - 1].k == 'nl')):
                opens += 1
                continue
            if t.k == 'op':
                if t.v in '([{':
                    depth += 1
                elif t.v in ')]}':
                    depth -= 1
            elif t.k == 'kw' and depth == 0:
                if t.v in BLOCK_OPENERS:
                    opens += 1
                    if t.v == 'function':
                        nfun += 1
                elif t.v == 'end':
                    ends += 1
                elif t.v == 'classdef':
                    raise ParseError('classdef files are not supported here: write functions and scripts.', t.line, t.pos)
        if nfun:
            if ends == opens:
                self.end_funcs = True
            elif ends == opens - nfun:
                self.end_funcs = False
            elif ends > opens:
                raise self.err_unbalanced(True)
            else:
                self.end_funcs = ends >= opens - nfun + 1
        else:
            if ends > opens:
                raise self.err_unbalanced(True)
            if ends < opens:
                raise self.err_unbalanced(False)
        self.skip_seps()
        if self.at('kw', 'function'):
            kind = 'function'
            body = []
        else:
            kind = 'script' if self.kind == 'file' else self.kind
            body = self.block(top=True)
        funcs = []
        while True:
            self.skip_seps()
            if self.at('eof'):
                break
            if self.at('kw', 'function'):
                funcs.append(self.function())
                continue
            t = self.peek()
            if kind == 'function':
                raise self.err('Function definitions in a file must all be closed with end, or none of them.' if self.end_funcs else 'This statement is not inside any function.\n (It follows the END that terminates the definition of the function.)', t)
            raise self.err(f"Illegal use of reserved keyword \"{t.v}\"." if t.k == 'kw' else 'Invalid expression. Check for missing or extra characters.', t)
        return Program(body, funcs, kind, self.text)

    def err_unbalanced(self, too_many):
        t = self.toks[-1]
        if too_many:
            for tk in self.toks:
                pass
            return ParseError("Illegal use of reserved keyword \"end\".", t.line, t.pos)
        return ParseError("At least one END is missing. The statement beginning here does not have a matching end.", t.line, t.pos)

    def skip_seps(self):
        while True:
            t = self.peek()
            if t.k == 'nl' or (t.k == 'op' and t.v in ',;'):
                self.i += 1
            else:
                return

    def block(self, top=False, stop=_STOP_KW):
        out = []
        while True:
            t = self.peek()
            if t.k == 'eof':
                return out
            if t.k == 'nl' or (t.k == 'op' and t.v in ',;'):
                self.i += 1
                continue
            if t.k == 'kw' and t.v in stop:
                if top and t.v == 'function':
                    return out
                if top:
                    raise self.err(f'Illegal use of reserved keyword "{t.v}".', t)
                return out
            s = self.statement()
            if s is not None:
                out.append(s)

    def end_stmt(self):
        """The statement's end: True when its result is shown."""
        t = self.peek()
        if t.k == 'op' and t.v == ';':
            self.i += 1
            if self.at_op(','):
                pass
            return False
        if t.k == 'op' and t.v == ',':
            self.i += 1
            return True
        if t.k in ('nl', 'eof'):
            return True
        if t.k == 'kw' and t.v in _STOP_KW:
            return True
        raise self.err('Invalid expression. Check for missing multiplication operator, missing or unbalanced delimiters, or other syntax error. To construct matrices, use brackets instead of parentheses.' if t.k == 'op' and t.v == '(' else 'Invalid expression. Check for missing or extra characters.', t)

    def statement(self):
        t = self.peek()
        line = t.line
        if t.k == 'kw':
            kw = t.v
            if kw == 'if':
                return self.if_stmt()
            if kw in ('for', 'parfor'):
                return self.for_stmt()
            if kw == 'while':
                self.next()
                cond = self.expr()
                body = self.block()
                self.expect_kw('end', t)
                return While(cond, body, line)
            if kw == 'switch':
                return self.switch_stmt()
            if kw == 'try':
                return self.try_stmt()
            if kw in ('break', 'continue', 'return'):
                self.next()
                self.end_stmt()
                return {'break': Break, 'continue': Continue, 'return': Return}[kw](line)
            if kw in ('global', 'persistent'):
                self.next()
                names = []
                while self.at('id'):
                    names.append(self.next().v)
                if self.at('cmd'):
                    # `global a b` lexed as command syntax after a name
                    pass
                self.end_stmt()
                return Global(names, kw == 'persistent', line)
            if kw == 'spmd':
                self.next()
                body = self.block()
                self.expect_kw('end', t)
                return If([(Num(1.0, line), body)], None, line)
            if kw == 'function':
                raise self.err('Function definitions are not supported in this context. Functions can only be created as local or nested functions in code files.', t)
            raise self.err(f'Illegal use of reserved keyword "{kw}".', t)
        if t.k == 'cmd':
            self.next()
            name, args = t.v
            show = self.end_stmt()
            return Cmd(name, args, show, line)
        if t.k == 'op' and t.v == '[':
            j = self.match_close(self.i)
            if j is not None:
                nt = self.toks[j + 1]
                if nt.k == 'op' and nt.v == '=':
                    return self.multi_assign()
        e = self.expr()
        if self.at_op('='):
            self.check_lvalue(e)
            self.next()
            rhs = self.expr()
            show = self.end_stmt()
            return Assign([e], rhs, show, False, line)
        show = self.end_stmt()
        return ExprS(e, show, line)

    def expect_kw(self, v, opener):
        t = self.peek()
        if t.k == 'kw' and t.v == v:
            self.i += 1
            return t
        raise ParseError(f'At least one END is missing: the statement that begins on line {opener.line} has no matching end.' if v == 'end'
                         else f'Expected "{v}".', t.line, t.pos)

    def match_close(self, i):
        depth = 0
        for j in range(i, len(self.toks)):
            t = self.toks[j]
            if t.k == 'op':
                if t.v in '([{':
                    depth += 1
                elif t.v in ')]}':
                    depth -= 1
                    if depth == 0:
                        return j
            elif t.k == 'eof':
                return None
        return None

    def check_lvalue(self, e):
        n = e
        while True:
            if isinstance(n, Id):
                return
            if isinstance(n, Index) or isinstance(n, Field):
                n = n.base
                continue
            raise self.err('Invalid use of operator.' if not isinstance(n, (Num, Chr)) else 'Incorrect use of \'=\' operator. To assign a value to a variable, use \'=\'. To compare values for equality, use \'==\'.')

    def multi_assign(self):
        t0 = self.next()   # [
        line = t0.line
        self.mat.append(True)
        targets = []
        while True:
            t = self.peek()
            if t.k == 'op' and t.v == ']':
                self.next()
                break
            if t.k == 'op' and t.v == ',':
                self.next()
                continue
            if t.k == 'op' and t.v == '~':
                nt = self.peek(1)
                if nt.k == 'op' and nt.v in (',', ']') or nt.sb:
                    self.next()
                    targets.append(None)
                    continue
            e = self.postfix()
            self.check_lvalue(e)
            targets.append(e)
        self.mat.pop()
        self.expect_op('=')
        rhs = self.expr()
        show = self.end_stmt()
        return Assign(targets, rhs, show, True, line)

    def if_stmt(self):
        t0 = self.next()
        clauses = []
        cond = self.expr()
        body = self.block()
        clauses.append((cond, body))
        els = None
        while True:
            t = self.peek()
            if t.k == 'kw' and t.v == 'elseif':
                self.next()
                c = self.expr()
                b = self.block()
                clauses.append((c, b))
                continue
            if t.k == 'kw' and t.v == 'else':
                self.next()
                els = self.block()
                continue
            break
        self.expect_kw('end', t0)
        return If(clauses, els, t0.line)

    def for_stmt(self):
        t0 = self.next()
        paren = False
        if self.at_op('('):
            # for (k = 1:n)  or parfor (k = 1:n, workers)
            j = self.match_close(self.i)
            paren = True
            self.next()
        tv = self.peek()
        if tv.k != 'id':
            raise self.err('Invalid expression: a for loop needs a variable.', tv)
        var = self.postfix()
        self.expect_op('=')
        it = self.expr()
        workers = None
        if paren:
            if self.at_op(','):
                self.next()
                workers = self.expr()
            self.expect_op(')')
        body = self.block()
        self.expect_kw('end', t0)
        return For(var, it, body, t0.line, t0.v == 'parfor', workers)

    def switch_stmt(self):
        t0 = self.next()
        e = self.expr()
        cases = []
        other = None
        self.skip_seps()
        while True:
            t = self.peek()
            if t.k == 'kw' and t.v == 'case':
                self.next()
                ce = self.expr()
                body = self.block()
                cases.append((ce, body))
                continue
            if t.k == 'kw' and t.v == 'otherwise':
                self.next()
                other = self.block()
                continue
            break
        self.expect_kw('end', t0)
        return Switch(e, cases, other, t0.line)

    def try_stmt(self):
        t0 = self.next()
        body = self.block()
        var = None
        cbody = []
        if self.at('kw', 'catch'):
            tc = self.next()
            t = self.peek()
            if t.k == 'id' and t.line == tc.line:
                nt = self.peek(1)
                if nt.k in ('nl', 'eof') or (nt.k == 'op' and nt.v in (',', ';')) or (nt.k == 'kw' and nt.v == 'end'):
                    var = self.next().v
            elif t.k == 'cmd' and t.line == tc.line:
                # `catch err` lexed as a command with no words cannot happen; `catch ME disp(x)` is rare
                pass
            cbody = self.block()
        self.expect_kw('end', t0)
        return Try(body, var, cbody, t0.line)

    def function(self):
        t0 = self.next()     # function
        line = t0.line
        outs = []
        # outputs: function [a, b] = f(...)  or  function a = f(...)
        if self.at_op('['):
            j = self.match_close(self.i)
            if j is not None and self.toks[j + 1].k == 'op' and self.toks[j + 1].v == '=':
                self.next()
                while not self.at_op(']'):
                    t = self.next()
                    if t.k == 'id':
                        outs.append(t.v)
                    elif t.k == 'op' and t.v == ',':
                        continue
                    else:
                        raise self.err('Invalid function output list.', t)
                self.next()
                self.expect_op('=')
        elif self.at('id') and self.peek(1).k == 'op' and self.peek(1).v == '=':
            outs.append(self.next().v)
            self.next()
        elif self.at('cmd'):
            # `function name arg` never happens; a name followed by words
            t = self.next()
            name = t.v[0]
            return self._func_rest(name, [], outs, line)
        t = self.peek()
        if t.k != 'id':
            raise self.err('Invalid function name.', t)
        name = self.next().v
        while self.at_op('.'):
            # set.Prop / get.Prop (classdef) or dotted names
            self.next()
            name += '.' + self.next().v
        params = []
        if self.at_op('('):
            self.next()
            while not self.at_op(')'):
                t = self.next()
                if t.k == 'id':
                    params.append(t.v)
                elif t.k == 'op' and t.v == '~':
                    params.append('~')
                elif t.k == 'op' and t.v == ',':
                    continue
                else:
                    raise self.err('Invalid function parameter list.', t)
            self.next()
        return self._func_rest(name, params, outs, line)

    def _func_rest(self, name, params, outs, line):
        defaults = self.arguments_block()
        body = []
        subs = []
        while True:
            body += self.block(stop={'end', 'function'} | ({'else', 'elseif', 'case', 'otherwise', 'catch'}))
            t = self.peek()
            if t.k == 'kw' and t.v == 'function':
                if self.end_funcs:
                    subs.append(self.function())
                    continue
                break
            if t.k == 'kw' and t.v == 'end':
                if self.end_funcs:
                    self.next()
                    break
                raise self.err('Illegal use of reserved keyword "end".', t)
            if t.k == 'eof':
                if self.end_funcs:
                    raise ParseError(f'The function "{name}" has no matching end.', line)
                break
            raise self.err(f'Illegal use of reserved keyword "{t.v}".', t)
        endline = self.peek().line
        f = Func(name, params, outs, body, line, endline, subs, defaults)
        for s in subs:
            s.parent = f
        return f

    def arguments_block(self):
        """An `arguments ... end` block at the top of a function: the
        declarations are skipped, their default values kept."""
        defaults = {}
        while True:
            self.skip_seps()
            t = self.peek()
            if not (t.k == 'id' and t.v == 'arguments') and not (t.k == 'cmd' and t.v[0] == 'arguments'):
                return defaults
            nt = self.peek(1)
            if t.k == 'id' and not (nt.k in ('nl',) or (nt.k == 'op' and nt.v == '(')):
                return defaults
            self.next()
            if self.at_op('('):
                j = self.match_close(self.i)
                self.i = j + 1
            # declarations until `end`
            while True:
                self.skip_seps()
                t = self.peek()
                if t.k == 'eof':
                    raise self.err('The arguments block has no matching end.', t)
                if t.k == 'kw' and t.v == 'end':
                    self.next()
                    break
                start = self.i
                name = None
                if t.k in ('id', 'cmd'):
                    name = t.v if t.k == 'id' else t.v[0]
                # to the line end; a default after the last '=' at bracket depth 0
                depth = 0
                eq = None
                while True:
                    tk = self.peek()
                    if tk.k in ('nl', 'eof') and depth == 0:
                        break
                    if tk.k == 'op':
                        if tk.v in '([{':
                            depth += 1
                        elif tk.v in ')]}':
                            depth -= 1
                        elif tk.v == '=' and depth == 0:
                            eq = self.i
                    self.i += 1
                    if tk.k == 'cmd':
                        break
                if eq is not None and name and '.' not in name:
                    end = self.i
                    save = self.i
                    self.i = eq + 1
                    try:
                        e = self.expr()
                        defaults[name] = e
                    except ParseError:
                        pass
                    self.i = save

    # ---- expressions ---------------------------------------------------------
    def expr(self):
        return self.oror()

    def oror(self):
        a = self.andand()
        while self.at_op('||'):
            t = self.next()
            b = self.andand()
            a = Bin('||', a, b, t.line)
        return a

    def andand(self):
        a = self.or_()
        while self.at_op('&&'):
            t = self.next()
            b = self.or_()
            a = Bin('&&', a, b, t.line)
        return a

    def or_(self):
        a = self.and_()
        while self.at_op('|'):
            t = self.next()
            b = self.and_()
            a = Bin('|', a, b, t.line)
        return a

    def and_(self):
        a = self.cmp()
        while self.at_op('&'):
            t = self.next()
            b = self.cmp()
            a = Bin('&', a, b, t.line)
        return a

    def cmp(self):
        a = self.range_()
        while True:
            t = self.peek()
            if t.k == 'op' and t.v in _CMP:
                self.next()
                b = self.range_()
                a = Bin(t.v, a, b, t.line)
                continue
            return a

    def range_(self):
        if self.at_op(':') and self.in_index:
            nt = self.peek(1)
            if nt.k == 'op' and nt.v in (',', ')', '}'):
                t = self.next()
                return Colon(t.line)
        a = self.add()
        if self.at_op(':') and not self._mat_break(self.peek()):
            t = self.next()
            b = self.add()
            if self.at_op(':'):
                self.next()
                c = self.add()
                return Range(a, b, c, t.line)
            return Range(a, None, b, t.line)
        return a

    def _mat_break(self, t):
        """In [ ] or { }: an operator with a space before and none after
        starts the next element ([1 -2] is two numbers)."""
        if not self.mat[-1]:
            return False
        if t.v in ('+', '-') and t.sb:
            nt = self.toks[self.i + 1]
            return not nt.sb
        return False

    def add(self):
        a = self.mul()
        while True:
            t = self.peek()
            if t.k == 'op' and t.v in ('+', '-'):
                if self._mat_break(t):
                    return a
                self.next()
                b = self.mul()
                a = Bin(t.v, a, b, t.line)
                continue
            return a

    def mul(self):
        a = self.unary()
        while True:
            t = self.peek()
            if t.k == 'op' and t.v in _MUL:
                self.next()
                b = self.unary()
                a = Bin(t.v, a, b, t.line)
                continue
            return a

    def unary(self):
        t = self.peek()
        if t.k == 'op' and t.v in ('-', '+', '~'):
            self.next()
            a = self.unary()
            if t.v == '-' and isinstance(a, Num) and not isinstance(a.v, tuple):
                return Num(-a.v, t.line, a.cls)
            return Un(t.v, a, t.line)
        return self.power()

    def power(self):
        a = self.postfix()
        while True:
            t = self.peek()
            if t.k == 'op' and t.v in ("'", ".'"):
                self.next()
                a = Post(t.v, a, t.line)
                continue
            if t.k == 'op' and t.v in ('^', '.^'):
                self.next()
                b = self.pow_operand()
                a = Bin(t.v, a, b, t.line)
                continue
            return a

    def pow_operand(self):
        t = self.peek()
        if t.k == 'op' and t.v in ('-', '+', '~'):
            self.next()
            a = self.pow_operand()
            return Un(t.v, a, t.line)
        return self.postfix()

    def postfix(self):
        a = self.primary()
        while True:
            t = self.peek()
            if t.k != 'op':
                return a
            if t.v == '(' or t.v == '{':
                if self.mat[-1] and t.sb:
                    return a
                if isinstance(a, (Num, Chr, DStr, Mat, CellLit, Anon)) and t.v == '(' and not isinstance(a, Anon):
                    # 3(1) is not allowed; a literal is never indexed
                    raise self.err('Invalid expression. Check for missing multiplication operator, missing or unbalanced delimiters, or other syntax error. To construct matrices, use brackets instead of parentheses.', t)
                self.next()
                close = ')' if t.v == '(' else '}'
                args = self.args(close)
                a = Index(a, args, t.v == '{', t.line)
                continue
            if t.v == '.':
                if self.mat[-1] and t.sb:
                    return a
                nt = self.peek(1)
                if nt.k == 'id' or nt.k == 'kw':
                    self.next()
                    self.next()
                    a = Field(a, nt.v, t.line)
                    continue
                if nt.k == 'op' and nt.v == '(':
                    self.next()
                    self.next()
                    self.mat.append(False)
                    self.in_index_save = self.in_index
                    e = self.expr()
                    self.mat.pop()
                    self.expect_op(')')
                    a = Field(a, e, t.line)
                    continue
                if nt.k == 'cmd':
                    raise self.err('Invalid expression.', nt)
                return a
            return a

    def args(self, close):
        self.mat.append(False)
        self.in_index += 1
        out = []
        if self.at_op(close):
            self.next()
            self.mat.pop()
            self.in_index -= 1
            return out
        while True:
            t = self.peek()
            if t.k == 'op' and t.v == ':':
                nt = self.peek(1)
                if nt.k == 'op' and nt.v in (',', close):
                    self.next()
                    out.append(Colon(t.line))
                else:
                    out.append(self.expr())
            else:
                out.append(self.expr())
            t = self.peek()
            if t.k == 'op' and t.v == ',':
                self.next()
                continue
            if t.k == 'op' and t.v == close:
                self.next()
                break
            raise self.err('Invalid expression. When calling a function or indexing a variable, use parentheses. Otherwise, check for mismatched delimiters.', t)
        self.mat.pop()
        self.in_index -= 1
        return out

    def primary(self):
        t = self.peek()
        k = t.k
        if k == 'num':
            self.next()
            v = t.v
            if isinstance(v, tuple):
                return Num(v[1], t.line, ('hex', v[2]))
            return Num(v, t.line)
        if k == 'str':
            self.next()
            return Chr(t.v, t.line)
        if k == 'dstr':
            self.next()
            return DStr(t.v, t.line)
        if k == 'id':
            self.next()
            return Id(t.v, t.line)
        if k == 'kw' and t.v == 'end' and self.in_index:
            self.next()
            return End(t.line)
        if k == 'op':
            v = t.v
            if v == '(':
                self.next()
                self.mat.append(False)
                save = self.in_index
                e = self.expr()
                self.mat.pop()
                self.expect_op(')', 'Invalid expression. When calling a function or indexing a variable, use parentheses. Otherwise, check for mismatched delimiters.')
                return Paren(e, t.line)
            if v == '[':
                self.next()
                return Mat(self.rows(']'), t.line)
            if v == '{':
                self.next()
                return CellLit(self.rows('}'), t.line)
            if v == '@':
                return self.handle()
            if v == ':' and self.in_index:
                self.next()
                return Colon(t.line)
        if k == 'kw':
            raise self.err(f'Illegal use of reserved keyword "{t.v}".', t)
        if k == 'cmd':
            raise self.err('Invalid expression. Check for missing or extra characters.', t)
        if k in ('nl', 'eof'):
            raise self.err('Invalid expression. Check for missing or extra characters.' if k == 'eof' or True else '', t)
        raise self.err(f"Invalid use of operator." if k == 'op' else 'Invalid expression.', t)

    def rows(self, close):
        self.mat.append(True)
        rows = [[]]
        while True:
            t = self.peek()
            if t.k == 'op' and t.v == close:
                self.next()
                break
            if t.k == 'nl' or (t.k == 'op' and t.v == ';'):
                self.next()
                if rows[-1]:
                    rows.append([])
                continue
            if t.k == 'op' and t.v == ',':
                self.next()
                continue
            if t.k == 'eof':
                raise self.err(f"Incorrect use of '{'[' if close == ']' else '{'}' or '{close}'. Check for mismatched delimiters.", t)
            e = self.expr()
            rows[-1].append(e)
            t = self.peek()
            if t.k == 'op' and t.v in (',', ';', close):
                continue
            if t.k == 'nl':
                continue
            if t.sb and _value_start(t, self.in_index):
                continue
            raise self.err('Invalid expression. Check for missing multiplication operator, missing or unbalanced delimiters, or other syntax error.', t)
        self.mat.pop()
        if rows and not rows[-1]:
            rows.pop()
        return rows

    def handle(self):
        t0 = self.next()    # @
        if self.at_op('('):
            start = self.peek().pos
            self.next()
            params = []
            while not self.at_op(')'):
                t = self.next()
                if t.k == 'id':
                    params.append(t.v)
                elif t.k == 'op' and t.v == '~':
                    params.append('~')
                elif t.k == 'op' and t.v == ',':
                    continue
                else:
                    raise self.err('Invalid anonymous function parameter list.', t)
            self.next()
            self.mat.append(False)
            save_idx = self.in_index
            self.in_index = 0
            body = self.expr()
            self.in_index = save_idx
            self.mat.pop()
            text = '@(' + ','.join(params) + ')' + unparse(body)
            return Anon(params, body, text, t0.line)
        t = self.peek()
        if t.k != 'id':
            raise self.err('Invalid function handle: @ must be followed by a function name or a parameter list.', t)
        self.next()
        name = t.v
        while self.at_op('.') and self.peek(1).k == 'id' and not self.peek().sb:
            self.next()
            name += '.' + self.next().v
        return FHandle(name, t0.line)


class Paren(Node):
    """(e): kept so that (c{:}) and (f(x)) count as one value."""
    __slots__ = ('e',)

    def __init__(self, e, line):
        self.e = e
        self.line = line


# ---- back to text (anonymous functions show themselves this way) ------------------

_PREC = {'||': 1, '&&': 2, '|': 3, '&': 4, '==': 5, '~=': 5, '<': 5, '<=': 5, '>': 5, '>=': 5,
         ':': 6, '+': 7, '-': 7, '*': 8, '/': 8, '\\': 8, '.*': 8, './': 8, '.\\': 8, '^': 10, '.^': 10}


def _num_text(v):
    if isinstance(v, complex):
        x = v.imag
        return (_num_text(x) if x != 1 or True else '') + 'i'
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    r = repr(v)
    if 'e' in r:
        m, e = r.split('e')
        return f'{m}e{int(e):+03d}'.replace('+', '+') if False else r
    return r


def unparse(n):
    if isinstance(n, Num):
        if isinstance(n.cls, tuple):
            return hex(int(n.v)) if n.cls[0] == 'hex' else str(int(n.v))
        return _num_text(n.v)
    if isinstance(n, Chr):
        return "'" + n.v.replace("'", "''") + "'"
    if isinstance(n, DStr):
        return '"' + n.v.replace('"', '""') + '"'
    if isinstance(n, Id):
        return n.name
    if isinstance(n, Colon):
        return ':'
    if isinstance(n, End):
        return 'end'
    if isinstance(n, Paren):
        return '(' + unparse(n.e) + ')'
    if isinstance(n, Bin):
        return unparse(n.a) + n.op + unparse(n.b)
    if isinstance(n, Un):
        return n.op + unparse(n.a)
    if isinstance(n, Post):
        return unparse(n.a) + n.op
    if isinstance(n, Range):
        if n.s is None:
            return unparse(n.a) + ':' + unparse(n.b)
        return unparse(n.a) + ':' + unparse(n.s) + ':' + unparse(n.b)
    if isinstance(n, Mat):
        return '[' + ';'.join(','.join(unparse(e) for e in r) for r in n.rows) + ']'
    if isinstance(n, CellLit):
        return '{' + ';'.join(','.join(unparse(e) for e in r) for r in n.rows) + '}'
    if isinstance(n, Index):
        o, c = ('{', '}') if n.brace else ('(', ')')
        return unparse(n.base) + o + ','.join(unparse(a) for a in n.args) + c
    if isinstance(n, Field):
        if isinstance(n.name, str):
            return unparse(n.base) + '.' + n.name
        return unparse(n.base) + '.(' + unparse(n.name) + ')'
    if isinstance(n, Anon):
        return n.text
    if isinstance(n, FHandle):
        return '@' + n.name
    if isinstance(n, Tilde):
        return '~'
    return '?'


def parse(text, is_var=None, kind='command'):
    p = Parser(text, is_var, kind)
    return p.program()


_ASSIGN_RE = re.compile(r'(?m)^[ \t]*(?:([A-Za-z]\w*)\s*(?:[({.][^\n=]*)?=(?!=))')
_MULTI_RE = re.compile(r'(?m)^[ \t]*\[([^\]\n]*)\]\s*=(?!=)')
_FOR_RE = re.compile(r'\b(?:for|parfor)\s*\(?\s*([A-Za-z]\w*)\s*=')
_FUNC_RE = re.compile(r'(?m)^[ \t]*function\b([^\n%]*)')
_GLOBAL_RE = re.compile(r'(?m)^[ \t]*(?:global|persistent)\b([^\n;%]*)')
_CATCH_RE = re.compile(r'(?m)\bcatch[ \t]+([A-Za-z]\w*)[ \t]*(?:$|[,;%])')


def assigned_names(text):
    """The names a file assigns, found before parsing so that command
    syntax can tell variables from commands."""
    names = set(m.group(1) for m in _ASSIGN_RE.finditer(text))
    for m in _MULTI_RE.finditer(text):
        for w in re.split(r'[\s,]+', m.group(1)):
            w = re.match(r'[A-Za-z]\w*', w or '')
            if w:
                names.add(w.group(0))
    names.update(m.group(1) for m in _FOR_RE.finditer(text))
    names.update(m.group(1) for m in _CATCH_RE.finditer(text))
    for m in _FUNC_RE.finditer(text):
        sig = m.group(1)
        names.update(re.findall(r'[A-Za-z]\w*', sig.split('(', 1)[1] if '(' in sig else ''))
        if '=' in sig:
            names.update(re.findall(r'[A-Za-z]\w*', sig.split('=', 1)[0]))
    for m in _GLOBAL_RE.finditer(text):
        names.update(re.findall(r'[A-Za-z]\w*', m.group(1)))
    return names
