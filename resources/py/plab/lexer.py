"""The lexer: source text to tokens.

The language reads some characters by their neighbours:
  - a quote is a transpose right after a value (x', a(1)', x'') and starts
    a character vector anywhere else, including after a space inside [ ]
    or { };
  - inside [ ] and { }, a space can separate elements ([1 -2] is two, [1 - 2]
    is one), so every token records whether a space came before it, and a
    line end separates rows;
  - a statement that starts with a name followed by a space and a word
    (hold on, format long, clear x y) is command syntax: the words are
    passed as text. A name that is a variable is never a command.
Comments run from % to the line end; %{ and %} on lines of their own
bracket a block comment; ... continues a line.
"""
import re

from .values import MError

KEYWORDS = {'break', 'case', 'catch', 'classdef', 'continue', 'else', 'elseif', 'end', 'for',
            'function', 'global', 'if', 'otherwise', 'parfor', 'persistent', 'return', 'spmd',
            'switch', 'try', 'while'}

BLOCK_OPENERS = {'if', 'for', 'parfor', 'while', 'switch', 'try', 'function', 'spmd'}


class Tok:
    __slots__ = ('k', 'v', 'pos', 'line', 'sb', 'end')

    def __init__(self, k, v, pos, line, sb, end):
        self.k = k        # num str dstr id kw op nl cmd eof
        self.v = v
        self.pos = pos
        self.line = line
        self.sb = sb      # whitespace before
        self.end = end    # offset after the token

    def __repr__(self):
        return f'{self.k}:{self.v!r}@{self.line}'


class LexError(MError):
    def __init__(self, msg, line, pos):
        super().__init__('MATLAB:parse', msg)
        self.line = line
        self.pos = pos


_ID = re.compile(r'[A-Za-z][A-Za-z0-9_]*')
_NUM = re.compile(r'(?:0[xX]([0-9a-fA-F]+)((?:[us](?:8|16|32|64))?)|0[bB]([01]+)((?:[us](?:8|16|32|64))?)|'
                  r'((?:\d+(?:\.(?![*/\\^\'.])\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?))([ij](?![A-Za-z0-9_]))?')
_OPS3 = ('...',)
_OPS2 = ('.^', '.*', './', '.\\', ".'", '==', '~=', '!=', '<=', '>=', '&&', '||')
_OPS1 = set("+-*/\\^'<>&|~!=:,;()[]{}.@")
_BINOP_START = ('==', '~=', '<=', '>=', '&&', '||', '.^', '.*', './', '.\\', '+', '-', '*', '/', '\\', '^', '<', '>', '&', '|', ':')
_VALUE_END_KINDS = ('id', 'num', 'str', 'dstr')


def _ends_value(t):
    if t is None:
        return False
    if t.k in _VALUE_END_KINDS:
        return True
    if t.k == 'op' and t.v in (')', ']', '}', "'", ".'"):
        return True
    if t.k == 'kw' and t.v == 'end':
        return True
    return False


def _line_is(text, i, marker):
    """Whether the line starting at i holds only the marker (and spaces)."""
    j = i
    n = len(text)
    while j < n and text[j] in ' \t':
        j += 1
    if not text.startswith(marker, j):
        return False
    j += len(marker)
    while j < n and text[j] in ' \t\r':
        j += 1
    return j >= n or text[j] == '\n'


def _skip_line(text, i):
    j = text.find('\n', i)
    return len(text) if j < 0 else j


def tokenize(text, is_var=None, keep_comments=False):
    """The tokens of a program. is_var(name) says whether a name is a
    variable (for command syntax)."""
    if is_var is None:
        is_var = lambda name: False
    toks = []
    i = 0
    n = len(text)
    line = 1
    stack = []          # open brackets: ( [ {
    stmt_start = True
    sp = False
    prev = None         # the last token (not newline)
    line_start = True

    def add(k, v, pos, end):
        nonlocal prev, sp
        t = Tok(k, v, pos, line, sp, end)
        toks.append(t)
        if k != 'nl':
            prev = t
        sp = False
        return t

    while i < n:
        c = text[i]
        # block comments: %{ ... %} on lines of their own
        if line_start and c in ' \t%' and _line_is(text, i, '%{'):
            depth = 0
            while i < n:
                if _line_is(text, i, '%{'):
                    depth += 1
                elif _line_is(text, i, '%}'):
                    depth -= 1
                j = _skip_line(text, i)
                if depth == 0:
                    i = j
                    break
                if j >= n:
                    i = n
                    break
                i = j + 1
                line += 1
            line_start = False
            continue
        if c == ' ' or c == '\t' or c == '\r':
            sp = True
            i += 1
            continue
        line_start = False
        if c == '\n':
            if stack and stack[-1] == '(':
                raise LexError('Invalid expression. When calling a function or indexing a variable, use parentheses. Otherwise, check for mismatched delimiters.', line, i)
            if stack:
                # a row break inside [ ] or { }
                add('nl', '\n', i, i + 1)
            else:
                add('nl', '\n', i, i + 1)
                stmt_start = True
            line += 1
            i += 1
            line_start = True
            continue
        if c == '%':
            j = _skip_line(text, i)
            if keep_comments:
                add('comment', text[i:j], i, j)
            i = j
            continue
        if text.startswith('...', i):
            # continuation: the rest of the line is a comment, the next line goes on
            j = _skip_line(text, i)
            i = j + 1 if j < n else n
            line += 1
            sp = True
            line_start = False
            continue
        in_mat = bool(stack) and stack[-1] in '[{'
        # a quote: transpose or text
        if c == "'":
            if _ends_value(prev) and toks and toks[-1].k != 'nl' and not (sp and in_mat) and not (prev.k == 'kw' and prev.v != 'end'):
                add('op', "'", i, i + 1)
                i += 1
                stmt_start = False
                continue
            j = i + 1
            buf = []
            while True:
                if j >= n or text[j] == '\n':
                    raise LexError('Character vector is not terminated properly.', line, i)
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            add('str', ''.join(buf), i, j + 1)
            i = j + 1
            stmt_start = False
            continue
        if c == '"':
            j = i + 1
            buf = []
            while True:
                if j >= n or text[j] == '\n':
                    raise LexError('String is not terminated properly.', line, i)
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            add('dstr', ''.join(buf), i, j + 1)
            i = j + 1
            stmt_start = False
            continue
        if c.isdigit() or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            m = _NUM.match(text, i)
            if not m:
                raise LexError('Invalid number.', line, i)
            imag = bool(m.group(6))
            if m.group(1) is not None:
                v = ('hex', int(m.group(1), 16), m.group(2))
            elif m.group(3) is not None:
                v = ('bin', int(m.group(3), 2), m.group(4))
            else:
                s = m.group(5).replace('d', 'e').replace('D', 'e')
                v = float(s)
            if imag:
                v = complex(0, v if not isinstance(v, tuple) else v[1])
            add('num', v, i, m.end())
            i = m.end()
            stmt_start = False
            continue
        if c.isalpha() and c.isascii():
            m = _ID.match(text, i)
            w = m.group(0)
            j = m.end()
            if w in KEYWORDS and not (prev is not None and prev.k == 'op' and prev.v == '.' and not prev.sb and not sp):
                add('kw', w, i, j)
                i = j
                stmt_start = w in ('else', 'try', 'otherwise', 'end', 'break', 'continue', 'return') and not stack
                continue
            if stmt_start and not stack and not is_var(w):
                cmd = _command_args(text, j)
                if cmd is not None:
                    args, end = cmd
                    add('cmd', (w, args), i, end)
                    i = end
                    stmt_start = False
                    continue
            add('id', w, i, j)
            i = j
            stmt_start = False
            continue
        # operators
        three = text[i:i + 3]
        two = text[i:i + 2]
        if two in _OPS2:
            if two == ".'" and not _ends_value(prev):
                # a dot then a quote that is not a transpose (rare): the dot alone
                add('op', '.', i, i + 1)
                i += 1
                continue
            add('op', '~=' if two == '!=' else two, i, i + 2)
            i += 2
            stmt_start = False
            continue
        if c in _OPS1:
            if c == '!' and stmt_start and not stack:
                # a shell escape: not available here
                j = _skip_line(text, i)
                add('cmd', ('!', [text[i + 1:j]]), i, j)
                i = j
                continue
            if c in '([{':
                stack.append(c)
            elif c in ')]}':
                want = {')': '(', ']': '[', '}': '{'}[c]
                if not stack or stack[-1] != want:
                    raise LexError(_mismatch(c), line, i)
                stack.pop()
            add('op', '~' if c == '!' else c, i, i + 1)
            i += 1
            if c in ',;' and not stack:
                stmt_start = True
            else:
                stmt_start = False
            continue
        raise LexError(f"Invalid text character. Check for unsupported symbol, invisible character, or pasting of non-ASCII characters." if ord(c) > 127 else f"Invalid character '{c}'.", line, i)
    if stack:
        raise LexError({'(': "Invalid expression. When calling a function or indexing a variable, use parentheses. Otherwise, check for mismatched delimiters.",
                        '[': "Incorrect use of '[' or ']'. Check for mismatched delimiters.",
                        '{': "Incorrect use of '{' or '}'. Check for mismatched delimiters."}[stack[-1]] if True else '', line, n)
    toks.append(Tok('eof', None, n, line, sp, n))
    return toks


def _mismatch(c):
    return {')': "Invalid use of a closing parenthesis. Check for a missing opening parenthesis.",
            ']': "Incorrect use of '[' or ']'. Check for mismatched delimiters.",
            '}': "Incorrect use of '{' or '}'. Check for mismatched delimiters."}[c]


def _command_args(text, j):
    """If the text after a statement's first name (at j) makes it command
    syntax, its words and where the command ends; else None."""
    n = len(text)
    if j >= n or text[j] not in ' \t':
        return None
    k = j
    while k < n and text[k] in ' \t':
        k += 1
    if k >= n:
        return None
    c = text[k]
    if c in '\n\r;,%':
        return None
    if c == '(':
        return None
    if c == '=' and not text.startswith('==', k):
        return None
    if text.startswith('...', k):
        return None
    for op in _BINOP_START:
        if text.startswith(op, k):
            after = k + len(op)
            if after >= n or text[after] in ' \t\n\r':
                return None      # x - y : an expression
            if op in ('==', '~=', '<=', '>=', '&&', '||', '*', '/', '\\', '^', '<', '>', '&', '|', '.^', '.*', './', '.\\', ':') and False:
                return None
            break
    if c == "'" and False:
        return None
    # the words: separated by spaces, quotes group, ends at , ; newline or %
    args = []
    cur = []
    have = False
    i = k
    quote = False
    while i < n:
        ch = text[i]
        if quote:
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    cur.append("'")
                    i += 2
                    continue
                quote = False
                i += 1
                continue
            if ch == '\n':
                raise LexError('Character vector is not terminated properly.', 0, i)
            cur.append(ch)
            i += 1
            continue
        if ch == "'":
            quote = True
            have = True
            i += 1
            continue
        if ch in ' \t\r':
            if have:
                args.append(''.join(cur))
                cur = []
                have = False
            i += 1
            continue
        if ch in '\n,;' or ch == '%':
            break
        if text.startswith('...', i):
            break
        cur.append(ch)
        have = True
        i += 1
    if have:
        args.append(''.join(cur))
    return args, i


def block_balance(text):
    """How many blocks and brackets a piece of text leaves open, for the
    Command Window (Enter continues while something is open). Returns
    (open blocks, open brackets, error text or None)."""
    try:
        toks = tokenize(text, keep_comments=False)
    except LexError as e:
        msg = str(e)
        if 'mismatched delimiters' in msg and ('[' in msg or '{' in msg) and 'closing' not in msg:
            return 0, 1, None
        if 'not terminated' in msg:
            return 0, 0, msg
        return 0, 0, msg
    depth = 0
    paren = 0
    for t in toks:
        if t.k == 'kw':
            if t.v in BLOCK_OPENERS:
                depth += 1
            elif t.v == 'end' and paren == 0:
                depth -= 1
        elif t.k == 'op':
            if t.v in '([{':
                paren += 1
            elif t.v in ')]}':
                paren -= 1
    return depth, paren, None
