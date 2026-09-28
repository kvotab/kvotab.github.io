"""JSL (the JMP Scripting Language) read into a syntax tree.

smui.html converts JSL scripts to Python in two halves: this module reads
a script into a tree of Node objects, and jsl_python.py translates the
tree. The lexical rules and the operators are those of the JSL Syntax
Reference (JMP 17):

- A name begins with a letter or an underscore and goes on with letters,
  digits, spaces and tabs, apostrophes, percent signs, periods,
  backslashes, underscores and other (non-ASCII) symbols. Case and
  whitespace do not matter: "N Rows", "NRows" and "nrows" are one name.
  Here a name ends at a line break (JMP joins the names of two lines when
  the ";" between them is missing; ending the name there lets the parser
  say so and go on). "any text"n and Name("any text") write any name.
- A name followed by "(" is a call. The arguments of a call, the items of
  a list and the rows of a matrix are separated by ","; ";" (Glue) joins
  expressions into one.
- Numbers (1, 1.5, .5, 1e-3); "." the missing value; dates such as
  01Jan2020 and 01Jan2020:12:30:00, in seconds since 1 January 1904;
  strings with the \\! escapes; raw strings "\\[ ... ]\\" with none;
  comments // to the end of the line and /* ... */.
- Lists {a, b}; matrices [1 2 3, 4 5 6] and []; associative arrays
  ["a" => 1, "b" => 2, => 0] (the last a default value) and [=>].
- The operators, from the loosest to the tightest:

      = += -= *= /= ||= |/=     assignments, right to left
      | :|                      Or, OrMZ
      & :&                      And, AndMZ
      == != < <= > >= >> >?     comparisons: a < b <= c is one range check
      <<                        Send, left to right: obj << A << B;
                                obj << {A, B} sends both
      ::                        Index (1::5); a prefix ::name is a global
      || |/                     Concat, V Concat
      + -                       Add, Subtract
      * / :* :/                 Multiply, Divide, E Mult, E Div
      - ! (prefix)              Minus, Not
      ^                         Power, right to left (2^-1 is 0.5)
      [ ] ` ++ -- :             subscripts (m[i, j]), transpose (A`),
                                post increment and decrement, the scope
                                dt:x; a prefix :x is a column

parse(text) returns a Program: its statements, the comments (kept so that
the Python can carry them), and the problems found, each with its line.
A statement that cannot be parsed is reported and skipped to the next ";"
at its level, so that one bad line does not lose the rest of the script.
"""
import calendar
import datetime

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

OPERATORS = sorted([
    '||=', '|/=', '<<', '>>', '>?', '::', ':*', ':/', ':&', ':|', '||', '|/', '==', '!=', '<=', '>=',
    '+=', '-=', '*=', '/=', '++', '--', '=>', '+', '-', '*', '/', '^', '!', '<', '>', '=', '&', '|',
    ':', '(', ')', '{', '}', '[', ']', ',', ';', '`',
], key=len, reverse=True)

# binding powers, loose to tight
ASSIGN, OR, AND, COMPARE, SEND, INDEX, CONCAT, ADD, MUL, UNARY, POWER, POSTFIX = 10, 20, 30, 40, 50, 55, 60, 70, 80, 90, 100, 110
ASSIGN_OPS = {'=', '+=', '-=', '*=', '/=', '||=', '|/='}
COMPARE_OPS = {'==', '!=', '<', '<=', '>', '>=', '>>', '>?'}
BINARY = {'|': OR, ':|': OR, '&': AND, ':&': AND, '<<': SEND, '::': INDEX, '||': CONCAT, '|/': CONCAT,
          '+': ADD, '-': ADD, '*': MUL, '/': MUL, ':*': MUL, ':/': MUL, '^': POWER}

# JMP's date-time origin
EPOCH = datetime.datetime(1904, 1, 1)


def name_key(name):
    """The canonical form of a JSL name: no whitespace, lower case."""
    return ''.join(name.split()).lower()


class Problem:
    """Something the reader could not take as it stands, at a 1-based line."""
    __slots__ = ('line', 'severity', 'text')

    def __init__(self, line, severity, text):
        self.line, self.severity, self.text = line, severity, text

    def __repr__(self):
        return f'Problem({self.line}, {self.severity!r}, {self.text!r})'


class Token:
    __slots__ = ('kind', 'value', 'line', 'start', 'end', 'nl', 'extra')

    def __init__(self, kind, value, line, start, end, nl, extra=None):
        self.kind, self.value, self.line, self.start, self.end, self.nl, self.extra = kind, value, line, start, end, nl, extra

    def is_op(self, *ops):
        return self.kind == 'op' and self.value in ops

    def __repr__(self):
        return f'Token({self.kind}, {self.value!r}, line {self.line})'


class Node:
    """A node of the tree.

    kind      value                     args
    num       the number                -
    str       the text                  -
    date      seconds since 1904        -            (extra: the date-time)
    missing   -                         -
    name      the name as written       -            (extra: key, quoted)
    call      the function's name       the arguments (extra: key)
    list      -                         the items
    matrix    rows of numbers (None: .) -
    assoc     -                         pairs        (extra: the default)
    pair      -                         key, value
    binop     the operator              left, right
    cmp       the operators             the operands
    unary     - ! +                     the operand
    postfix   ++ -- `                   the operand
    assign    = += -= ...               target, value
    glue      -                         the expressions
    subscript -                         base, subscripts
    col       the column's name         -            (extra: key, quoted)
    global    the name                  -            (extra: key)
    scope     the name after the ":"    the left side (extra: key, quoted)
    send      -                         object, message (object empty: a
                                        message given as an argument)
    empty     -                         -            (an empty argument)
    """
    __slots__ = ('kind', 'value', 'args', 'line', 'start', 'end', 'extra')

    def __init__(self, kind, value=None, args=None, line=0, start=0, end=0, extra=None):
        self.kind = kind
        self.value = value
        self.args = args if args is not None else []
        self.line, self.start, self.end = line, start, end
        self.extra = extra if extra is not None else {}

    @property
    def key(self):
        return self.extra.get('key')

    def is_call(self, *keys):
        return self.kind == 'call' and (not keys or self.extra.get('key') in keys)

    def is_name(self, *keys):
        return self.kind == 'name' and (not keys or self.extra.get('key') in keys)

    def walk(self):
        """This node and every node below it, depth first."""
        yield self
        for a in self.args:
            if isinstance(a, Node):
                yield from a.walk()
        d = self.extra.get('default')
        if isinstance(d, Node):
            yield from d.walk()

    def __repr__(self):
        return dump(self)


def dump(node):
    """A compact, readable form of a tree, for tests and debugging."""
    if node is None:
        return 'None'
    k = node.kind
    if k == 'num':
        return repr(node.value)
    if k == 'str':
        return repr(node.value)
    if k == 'missing':
        return '.'
    if k == 'date':
        return f'date({node.value!r})'
    if k == 'name':
        return node.value
    if k == 'col':
        return f':{node.value}'
    if k == 'global':
        return f'::{node.value}'
    if k == 'empty':
        return '<empty>'
    if k == 'error':
        return '<error>'
    if k == 'scope':
        return f'({dump(node.args[0])}:{node.value})'
    if k == 'call':
        return f'{node.value}({", ".join(dump(a) for a in node.args)})'
    if k == 'list':
        return '{' + ', '.join(dump(a) for a in node.args) + '}'
    if k == 'matrix':
        return '[' + ', '.join(' '.join('.' if v is None else repr(v) for v in row) for row in node.value) + ']'
    if k == 'assoc':
        items = [f'{dump(p.args[0])} => {dump(p.args[1])}' for p in node.args]
        if node.extra.get('default') is not None:
            items.append(f'=> {dump(node.extra["default"])}')
        return '[' + ', '.join(items) + (']' if items else '=>]')
    if k == 'binop':
        return f'({dump(node.args[0])} {node.value} {dump(node.args[1])})'
    if k == 'cmp':
        out = dump(node.args[0])
        for op, a in zip(node.value, node.args[1:]):
            out += f' {op} {dump(a)}'
        return f'({out})'
    if k == 'unary':
        return f'({node.value}{dump(node.args[0])})'
    if k == 'postfix':
        return f'({dump(node.args[0])}{node.value})'
    if k == 'assign':
        return f'({dump(node.args[0])} {node.value} {dump(node.args[1])})'
    if k == 'glue':
        return '(' + '; '.join(dump(a) for a in node.args) + ')'
    if k == 'subscript':
        return f'{dump(node.args[0])}[{", ".join(dump(a) for a in node.args[1:])}]'
    if k == 'send':
        return f'({dump(node.args[0])} << {dump(node.args[1])})'
    return f'<{k}>'


class Program:
    def __init__(self, text, statements, comments, problems, tokens):
        self.text = text
        self.statements = statements
        self.comments = comments      # [(line, text, alone on its line)]
        self.problems = problems
        self.tokens = tokens

    @property
    def ok(self):
        """False only when nothing could be read at all."""
        return bool(self.statements) or not any(p.severity == 'error' for p in self.problems)

    def source(self, node):
        """The JSL text of a node, as written."""
        return self.text[node.start:node.end]


# ---------------------------------------------------------------------------
# the lexer

def _is_name_start(c):
    return c.isalpha() or c == '_' or (ord(c) > 127 and not c.isspace())


def _is_name_char(c):
    return c.isalnum() or c in "_'%.\\" or (ord(c) > 127 and not c.isspace())


def _date_value(y, mo, d, hh=0, mi=0, ss=0.0):
    """Seconds since 1 January 1904, JMP's date-time value."""
    base = datetime.datetime(y, mo, 1)
    return (base - EPOCH).total_seconds() + (d - 1) * 86400 + hh * 3600 + mi * 60 + ss


ESCAPES = {'b': '\b', 't': '\t', 'r': '\r', 'n': '\n', 'N': '\n', 'f': '\f', '0': '\0', '\\': '\\', '"': '"'}


def tokenize(text):
    """The tokens of a script, its comments and the problems met."""
    toks, comments, problems = [], [], []
    i, n, line = 0, len(text), 1
    nl = True         # a line break since the last token
    line_has_token = False

    def add(kind, value, start, end, extra=None):
        nonlocal nl, line_has_token
        toks.append(Token(kind, value, tok_line, start, end, nl, extra))
        nl = False
        line_has_token = True

    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            nl = True
            line_has_token = False
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        tok_line = line
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            comments.append((line, text[i + 2:j].strip(), not line_has_token))
            i = j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            if j < 0:
                problems.append(Problem(line, 'error', 'a /* comment is not closed by */: the rest of the script is taken as the comment'))
                j = n
            body = text[i + 2:j]
            for k, part in enumerate(body.split('\n')):
                if part.strip() and not part.strip().startswith(('debug step', 'debug run')):
                    comments.append((line + k, part.strip(' *\t'), not line_has_token or k > 0))
            line += body.count('\n')
            if body.count('\n'):
                line_has_token = False
            i = min(n, j + 2)
            continue
        if c == '"':
            start = i
            if text.startswith('"\\[', i):
                j = text.find(']\\"', i + 3)
                if j < 0:
                    problems.append(Problem(line, 'error', 'a raw string "\\[ is not closed by ]\\"'))
                    j = n
                value = text[i + 3:j]
                line += value.count('\n')
                i = min(n, j + 3)
            else:
                i += 1
                parts = []
                closed = False
                while i < n:
                    ch = text[i]
                    if ch == '"':
                        closed = True
                        i += 1
                        break
                    if ch == '\\' and i + 1 < n and text[i + 1] == '!':
                        e = text[i + 2] if i + 2 < n else ''
                        if e in ESCAPES:
                            parts.append(ESCAPES[e])
                            i += 3
                            continue
                        if e in 'uU' and i + 6 < n + 1:
                            hexd = text[i + 3:i + 7]
                            try:
                                parts.append(chr(int(hexd, 16)))
                                i += 7
                                continue
                            except ValueError:
                                pass
                        parts.append('\\!')
                        i += 2
                        continue
                    if ch == '\n':
                        line += 1
                    parts.append(ch)
                    i += 1
                value = ''.join(parts)
                if not closed:
                    # taken to the end of its line, so that the lines after it are read
                    problems.append(Problem(tok_line, 'error', 'a string is not closed by "; it is taken to the end of its line'))
                    first = value.split('\n', 1)[0]
                    line = tok_line
                    i = start + 1 + len(first)
                    value = first
            # "text"n is a name
            if i < n and text[i] == 'n' and not (i + 1 < n and _is_name_char(text[i + 1])):
                i += 1
                add('name', value, start, i, {'quoted': True})
            else:
                add('str', value, start, i)
            continue
        if c.isdigit() or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            start = i
            j = i
            while j < n and text[j].isdigit():
                j += 1
            # a date: 1-2 digits, a month, 2 or 4 digits (01Jan2020), maybe :hh:mm(:ss)
            if c != '.' and j - i <= 2 and j + 3 <= n and text[j:j + 3].lower() in MONTHS:
                k = j + 3
                m = k
                while m < n and text[m].isdigit():
                    m += 1
                if m - k in (2, 4) and not (m < n and _is_name_char(text[m]) and not text[m] == '.'):
                    year = int(text[k:m])
                    if m - k == 2:
                        year += 2000 if year < 50 else 1900
                    day, month = int(text[i:j]), MONTHS[text[j:j + 3].lower()]
                    hh = mi = 0
                    ss = 0.0
                    q = m
                    tm = []
                    while q < n and text[q] == ':' and q + 1 < n and text[q + 1].isdigit() and len(tm) < 3:
                        r = q + 1
                        while r < n and (text[r].isdigit() or (text[r] == '.' and len(tm) == 2)):
                            r += 1
                        tm.append(text[q + 1:r])
                        q = r
                    if len(tm) >= 2:
                        hh, mi = int(tm[0]), int(tm[1])
                        ss = float(tm[2]) if len(tm) == 3 else 0.0
                        m = q
                    try:
                        value = _date_value(year, month, day, hh, mi, ss)
                        add('date', value, start, m, {'ymd': (year, month, day, hh, mi, ss)})
                    except (ValueError, OverflowError):
                        problems.append(Problem(line, 'error', f'{text[start:m]} is not a date'))
                        add('missing', None, start, m)
                    i = m
                    continue
            if j < n and text[j] == '.':
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            if j < n and text[j] in 'eE' and (j + 1 < n and (text[j + 1].isdigit() or (text[j + 1] in '+-' and j + 2 < n and text[j + 2].isdigit()))):
                j += 2
                while j < n and text[j].isdigit():
                    j += 1
            lit = text[i:j]
            value = int(lit) if lit.isdigit() else float(lit)
            add('num', value, start, j, {'text': lit})
            if j < n and _is_name_start(text[j]):
                problems.append(Problem(line, 'error', f'a number runs into a name: {text[start:j + 1]}'))
            i = j
            continue
        if c == '.' and not (i + 1 < n and _is_name_char(text[i + 1]) and not text[i + 1] == '.'):
            add('missing', None, i, i + 1)
            i += 1
            continue
        if _is_name_start(c):
            start = i
            j = i + 1
            last = j        # the end of the last word, so no trailing blanks
            while j < n:
                ch = text[j]
                if _is_name_char(ch):
                    j += 1
                    last = j
                    continue
                if ch in ' \t':
                    k = j
                    while k < n and text[k] in ' \t':
                        k += 1
                    if k < n and _is_name_char(text[k]) and not (text[k] == '.' and not (k + 1 < n and _is_name_char(text[k + 1]))):
                        j = k
                        continue
                break
            raw = text[start:last]
            add('name', ' '.join(raw.split()), start, last)
            i = last
            continue
        for op in OPERATORS:
            if text.startswith(op, i):
                # ":/*" is ":" and a comment, not E Div
                if op == ':/' and text.startswith(':/*', i):
                    op = ':'
                add('op', op, i, i + len(op))
                i += len(op)
                break
        else:
            problems.append(Problem(line, 'error', f'the character {c!r} has no meaning in JSL here'))
            i += 1
    toks.append(Token('eof', None, line, n, n, True))
    return toks, comments, problems


# ---------------------------------------------------------------------------
# the parser

class ParseError(Exception):
    def __init__(self, token, text):
        super().__init__(text)
        self.token = token
        self.text = text


class Parser:
    def __init__(self, text, tokens, problems):
        self.text = text
        self.toks = tokens
        self.i = 0
        self.problems = problems

    # ---- tokens
    def peek(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def expect(self, op, what):
        t = self.peek()
        if not t.is_op(op):
            raise ParseError(t, f'expected "{op}" {what}, found {describe(t)}')
        return self.next()

    def node(self, kind, first, last=None, **kw):
        last = last or self.toks[self.i - 1]
        return Node(kind, line=first.line, start=first.start, end=last.end, **kw)

    def warn(self, token, text, severity='warn'):
        self.problems.append(Problem(token.line, severity, text))

    # ---- the program
    def program(self):
        stmts = []
        while self.peek().kind != 'eof':
            if self.peek().is_op(';'):
                self.next()
                continue
            start = self.i
            try:
                e = self.expr(0)
                t = self.peek()
                if t.is_op(';'):
                    self.next()
                elif t.kind == 'eof':
                    pass
                elif t.nl and not t.is_op(')', '}', ']', ','):
                    self.warn(t, 'a ";" is missing at the end of the line before; the line is taken as a new statement')
                else:
                    raise ParseError(t, f'{describe(t)} cannot come here')
                stmts.append(e)
            except ParseError as err:
                # an error only found at the end of the script: say where its statement began
                line = self.toks[start].line if err.token.kind == 'eof' else err.token.line
                self.problems.append(Problem(line, 'error', f'syntax error: {err.text}; the statement is skipped'))
                self.recover(start, err.token)
        return stmts

    def recover(self, start, bad):
        """Skip the statement that failed: to the next ";" at its own level,
        or else to the first ";" at the end of a line after the error, or
        else to the next line."""
        bi = next((k for k, t in enumerate(self.toks) if t is bad), start)
        depth = 0
        for k in range(start, len(self.toks)):
            t = self.toks[k]
            if t.kind == 'eof':
                break
            if t.is_op('(', '{', '['):
                depth += 1
            elif t.is_op(')', '}', ']'):
                depth -= 1
            elif t.is_op(';') and depth <= 0 and k >= bi:
                self.i = k + 1
                return
        for k in range(start, len(self.toks) - 1):
            t = self.toks[k]
            if t.is_op(';') and (self.toks[k + 1].nl or self.toks[k + 1].kind == 'eof'):
                self.i = k + 1
                return
        for k in range(bi + 1, len(self.toks)):
            if self.toks[k].nl and self.toks[k].kind != 'eof':
                self.i = k
                return
        self.i = len(self.toks) - 1

    # ---- sequences: expressions joined by ";" up to a closing token
    def seq(self, stops):
        first = self.peek()
        items = []
        while True:
            t = self.peek()
            if t.kind == 'eof' or (t.kind == 'op' and t.value in stops):
                break
            if t.is_op(';'):
                self.next()
                continue
            items.append(self.expr(0))
            t = self.peek()
            if t.is_op(';'):
                self.next()
                continue
            break
        if not items:
            return Node('empty', line=first.line, start=first.start, end=first.start)
        if len(items) == 1:
            return items[0]
        return Node('glue', args=items, line=items[0].line, start=items[0].start, end=items[-1].end)

    def args(self, closer, what):
        """The items up to the closer, separated by ","."""
        out = []
        if self.peek().is_op(closer):
            self.next()
            return out
        while True:
            t = self.peek()
            if t.is_op(','):
                out.append(Node('empty', line=t.line, start=t.start, end=t.start))
                self.next()
                continue
            out.append(self.seq({',', closer}))
            t = self.peek()
            if t.is_op(','):
                self.next()
                if self.peek().is_op(closer):
                    self.next()
                    return out
                continue
            if t.is_op(closer):
                self.next()
                return out
            if t.kind != 'eof' and t.nl and not t.is_op(')', '}', ']'):
                self.warn(t, f'a "," is missing before {describe(t)} {what}; it is taken as the next item')
                continue
            raise ParseError(t, f'expected "," or "{closer}" {what}, found {describe(t)}')

    # ---- expressions (a Pratt parser)
    def expr(self, rbp):
        left = self.prefix()
        while True:
            t = self.peek()
            if t.kind != 'op':
                break
            op = t.value
            if op in ('[', '`', '++', '--') or (op == ':' and self._scope_follows()):
                left = self.postfix(left)
                continue
            if op in ASSIGN_OPS:
                if ASSIGN <= rbp:
                    break
                self.next()
                value = self.expr(ASSIGN - 1)
                left = Node('assign', op, [left, value], line=left.line, start=left.start, end=value.end)
                continue
            if op in COMPARE_OPS:
                if COMPARE <= rbp:
                    break
                ops, operands = [], [left]
                while self.peek().kind == 'op' and self.peek().value in COMPARE_OPS:
                    ops.append(self.next().value)
                    operands.append(self.expr(COMPARE))
                left = Node('cmp', ops, operands, line=left.line, start=left.start, end=operands[-1].end)
                continue
            bp = BINARY.get(op)
            if bp is None or bp <= rbp:
                break
            self.next()
            if op == '<<':
                right = self.message()
            elif op == '^':
                right = self.expr(POWER - 1)
            else:
                right = self.expr(bp)
            kind = 'send' if op == '<<' else 'binop'
            left = Node(kind, None if kind == 'send' else op, [left, right], line=left.line, start=left.start, end=right.end)
        return left

    def _scope_follows(self):
        return self.peek(1).kind == 'name'

    def message(self):
        """What follows <<: a name, a call, a list of messages or (expr)."""
        t = self.peek()
        if t.is_op('{'):
            return self.prefix()
        return self.expr(SEND)

    def postfix(self, left):
        t = self.next()
        op = t.value
        if op == '[':
            idx = self.args(']', 'in a subscript')
            return Node('subscript', args=[left] + idx, line=left.line, start=left.start, end=self.toks[self.i - 1].end)
        if op == ':':
            nt = self.next()
            name, key, quoted = self._name_of(nt)
            n = Node('scope', name, [left], line=left.line, start=left.start, end=nt.end, extra={'key': key, 'quoted': quoted})
            if self.peek().is_op('(') and not quoted:
                # ns:f(x), a function in a namespace: kept as a call on the scope
                self.next()
                a = self.args(')', f'in the call of {name}')
                n = Node('call', name, a, line=left.line, start=left.start, end=self.toks[self.i - 1].end, extra={'key': key, 'scope': left})
            return n
        return Node('postfix', op, [left], line=left.line, start=left.start, end=t.end)

    def _name_of(self, t):
        if t.kind == 'name':
            if t.extra and t.extra.get('quoted'):
                return t.value, name_key(t.value), True
            # Name("x") after a scope
            if self.peek().is_op('(') and name_key(t.value) == 'name' and self.peek(1).kind == 'str' and self.peek(2).is_op(')'):
                self.next()
                s = self.next()
                self.next()
                return s.value, name_key(s.value), True
            return t.value, name_key(t.value), False
        raise ParseError(t, f'expected a name after ":", found {describe(t)}')

    def prefix(self):
        t = self.next()
        k = t.kind
        if k == 'num':
            return Node('num', t.value, line=t.line, start=t.start, end=t.end, extra={'text': t.extra['text']})
        if k == 'str':
            return Node('str', t.value, line=t.line, start=t.start, end=t.end)
        if k == 'date':
            return Node('date', t.value, line=t.line, start=t.start, end=t.end, extra={'ymd': t.extra['ymd']})
        if k == 'missing':
            return Node('missing', line=t.line, start=t.start, end=t.end)
        if k == 'name':
            quoted = bool(t.extra and t.extra.get('quoted'))
            key = name_key(t.value)
            if self.peek().is_op('(') and not quoted:
                self.next()
                a = self.args(')', f'in the call of {t.value}')
                # Name("x") is the name x
                if key == 'name' and len(a) == 1 and a[0].kind == 'str':
                    return Node('name', a[0].value, line=t.line, start=t.start, end=self.toks[self.i - 1].end, extra={'key': name_key(a[0].value), 'quoted': True})
                return Node('call', t.value, a, line=t.line, start=t.start, end=self.toks[self.i - 1].end, extra={'key': key})
            return Node('name', t.value, line=t.line, start=t.start, end=t.end, extra={'key': key, 'quoted': quoted})
        if k == 'op':
            op = t.value
            if op == '(':
                inner = self.seq({')'})
                self.expect(')', 'to close "("')
                inner.start, inner.end = t.start, self.toks[self.i - 1].end
                if inner.kind == 'empty':
                    raise ParseError(t, 'empty parentheses')
                inner.extra['paren'] = True
                return inner
            if op == '{':
                items = self.args('}', 'in a list')
                return self.node('list', t, args=[a for a in items])
            if op == '[':
                return self.bracket(t)
            if op == '<<':
                # a message given as an argument: New Column("x", <<Set Each Value(1))
                msg = self.message()
                empty = Node('empty', line=t.line, start=t.start, end=t.start)
                return Node('send', args=[empty, msg], line=t.line, start=t.start, end=msg.end)
            if op in ('-', '!', '+'):
                operand = self.expr(UNARY)
                return Node('unary', op, [operand], line=t.line, start=t.start, end=operand.end)
            if op == '--':
                operand = self.expr(UNARY)
                inner = Node('unary', '-', [operand], line=t.line, start=t.start + 1, end=operand.end)
                return Node('unary', '-', [inner], line=t.line, start=t.start, end=operand.end)
            if op == ':':
                nt = self.next()
                name, key, quoted = self._name_of(nt)
                return Node('col', name, line=t.line, start=t.start, end=self.toks[self.i - 1].end, extra={'key': key, 'quoted': quoted})
            if op == '::':
                nt = self.next()
                name, key, quoted = self._name_of(nt)
                n = Node('global', name, line=t.line, start=t.start, end=self.toks[self.i - 1].end, extra={'key': key, 'quoted': quoted})
                if self.peek().is_op('(') and not quoted:
                    self.next()
                    a = self.args(')', f'in the call of {name}')
                    return Node('call', name, a, line=t.line, start=t.start, end=self.toks[self.i - 1].end, extra={'key': key, 'global': True})
                return n
        raise ParseError(t, f'{describe(t)} cannot come here')

    def bracket(self, first):
        """A matrix [1 2, 3 4], [] or an associative array ["a" => 1, => 0]."""
        # an associative array has => at its own level
        depth, j = 0, self.i
        is_aa = False
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == 'eof':
                break
            if t.is_op('(', '{', '['):
                depth += 1
            elif t.is_op(')', '}', ']'):
                if depth == 0:
                    break
                depth -= 1
            elif t.is_op('=>') and depth == 0:
                is_aa = True
                break
            j += 1
        if is_aa:
            pairs, default = [], None
            while True:
                t = self.peek()
                if t.is_op(']'):
                    self.next()
                    break
                if t.is_op('=>'):
                    self.next()
                    if self.peek().is_op(']', ','):
                        default = None
                    else:
                        default = self.expr(0)
                else:
                    kx = self.expr(ASSIGN)
                    self.expect('=>', 'between a key and its value')
                    vx = self.expr(ASSIGN)
                    pairs.append(Node('pair', args=[kx, vx], line=kx.line, start=kx.start, end=vx.end))
                t = self.peek()
                if t.is_op(','):
                    self.next()
                    continue
                if t.is_op(']'):
                    self.next()
                    break
                raise ParseError(t, f'expected "," or "]" in an associative array, found {describe(t)}')
            n = self.node('assoc', first, args=pairs)
            n.extra['default'] = default
            return n
        rows, row = [], []
        while True:
            t = self.next()
            if t.is_op(']'):
                break
            if t.is_op(','):
                rows.append(row)
                row = []
                continue
            sign = 1
            if t.is_op('-', '+'):
                sign = -1 if t.value == '-' else 1
                t = self.next()
            if t.kind == 'num':
                row.append(sign * t.value)
            elif t.kind == 'missing':
                row.append(None)
            elif t.kind == 'eof':
                raise ParseError(t, 'a matrix is not closed by "]"')
            else:
                raise ParseError(t, f'a matrix literal holds numbers only, found {describe(t)} (use Matrix({{...}}) for expressions)')
        if row or not rows:
            rows.append(row)
        rows = [r for r in rows if r] or ([] if not any(rows) else rows)
        widths = {len(r) for r in rows}
        if len(widths) > 1:
            self.warn(first, 'the rows of a matrix have different lengths')
        return self.node('matrix', first, value=rows)


def describe(t):
    if t.kind == 'eof':
        return 'the end of the script'
    if t.kind == 'op':
        return f'"{t.value}"'
    if t.kind == 'str':
        return 'a string'
    if t.kind == 'num':
        return f'the number {t.extra["text"] if t.extra else t.value}'
    if t.kind == 'name':
        return f'the name {t.value}'
    if t.kind == 'missing':
        return 'the missing value "."'
    return t.kind


def parse(text):
    """Read a JSL script: a Program with its statements and problems."""
    toks, comments, problems = tokenize(text)
    p = Parser(text, toks, problems)
    stmts = p.program()
    problems.sort(key=lambda q: q.line)
    return Program(text, stmts, comments, problems, toks)


def parse_expr(text):
    """One expression (for tests): its tree, or a ParseError."""
    prog = parse(text)
    errs = [q for q in prog.problems if q.severity == 'error']
    if errs:
        raise ValueError(errs[0].text)
    if len(prog.statements) != 1:
        return Node('glue', args=prog.statements)
    return prog.statements[0]
