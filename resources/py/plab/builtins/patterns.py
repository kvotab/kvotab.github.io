"""Patterns for matching text: digitsPattern, lettersPattern,
alphanumericsPattern, whitespacePattern, wildcardPattern,
characterListPattern, optionalPattern, asManyOfPattern, asFewOfPattern,
the boundaries (letterBoundary, digitBoundary, alphanumericBoundary,
whitespaceBoundary, lineBoundary, textBoundary, lookAheadBoundary,
lookBehindBoundary), regexpPattern, caseInsensitivePattern,
caseSensitivePattern and namedPattern; patterns joined with + and offered
as alternatives with | (or an array of them); and extract.

A pattern is held as a Python regular expression. contains, startsWith,
endsWith, matches, count, strfind, replace, erase, split, extractBefore,
extractAfter, extractBetween, insertBefore and insertAfter take patterns
where they take text."""
import re

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Obj, Char, Cell, Str, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, re.error) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


class Pattern(Obj):
    cls = 'pattern'
    is_handle = False

    def __init__(self, rx, text, alts=None):
        self.rx = rx
        self.text = text
        self.alts = alts           # a pattern array: its elements

    def display_lines(self):
        return ['  pattern', '', '  Matching:', '', '    ' + self.text]

    def getprop(self, name):
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'pattern'.")


def _pat(v, fn='pattern'):
    """A pattern, or text as a pattern that matches it exactly."""
    if isinstance(v, Pattern):
        return v
    if isinstance(v, (Char, Str, Cell)):
        items = text_list(v) if not isinstance(v, Char) else [v.str()]
        if len(items) == 1:
            return Pattern(re.escape(items[0]), '"' + items[0] + '"')
        return Pattern('(?:' + '|'.join(re.escape(s) for s in items) + ')', ' | '.join('"' + s + '"' for s in items))
    raise err(f'MATLAB:{fn}:pattern', 'A pattern is built from patterns and text.', fn)


def _count(args, fn):
    """(min, max) from (), (n) or (min, max)."""
    nums = [a for a in args if not is_str(a)]
    if not nums:
        return None
    if len(nums) == 1:
        n = int(num(nums[0]))
        return n, n
    lo, hi = float(num(nums[0])), float(num(nums[1]))
    return int(lo), (None if np.isinf(hi) else int(hi))


def _rep(cls_rx, args, fn, label):
    c = _count(args, fn)
    if c is None:
        return Pattern(f'{cls_rx}+', f'{label}')
    lo, hi = c
    q = f'{{{lo}}}' if lo == hi else f'{{{lo},{"" if hi is None else hi}}}'
    return Pattern(f'{cls_rx}{q}', f'{label}({", ".join(str(int(num(a))) if np.isfinite(float(num(a))) else "Inf" for a in args if not is_str(a))})')


@bi('digitsPattern')
def digitsPattern(nargout, *args):
    """pat = digitsPattern, digitsPattern(n), digitsPattern(min, max): digits 0 to 9 (one or more unless counted)."""
    return _rep('[0-9]', args, 'digitsPattern', 'digitsPattern')


@bi('lettersPattern')
def lettersPattern(nargout, *args):
    """pat = lettersPattern, lettersPattern(n), lettersPattern(min, max): letters."""
    return _rep('[^\\W\\d_]', args, 'lettersPattern', 'lettersPattern')


@bi('alphanumericsPattern')
def alphanumericsPattern(nargout, *args):
    """pat = alphanumericsPattern, alphanumericsPattern(n), alphanumericsPattern(min, max): letters and digits."""
    return _rep('[^\\W_]', args, 'alphanumericsPattern', 'alphanumericsPattern')


@bi('whitespacePattern')
def whitespacePattern(nargout, *args):
    """pat = whitespacePattern, whitespacePattern(n), whitespacePattern(min, max): spaces, tabs and newlines."""
    return _rep('\\s', args, 'whitespacePattern', 'whitespacePattern')


@bi('wildcardPattern')
def wildcardPattern(nargout, *args):
    """pat = wildcardPattern, wildcardPattern(n), wildcardPattern(min, max), wildcardPattern(..., 'Except', chars): any characters, as few as possible (exactly n when counted)."""
    a = list(args)
    exc = None
    for i in range(len(a) - 1):
        if is_str(a[i]) and py_str(a[i]).lower() == 'except':
            exc = a[i + 1]
            a = a[:i] + a[i + 2:]
            break
    cls_rx = '[\\s\\S]'
    label = 'wildcardPattern'
    if exc is not None:
        if isinstance(exc, Pattern):
            cls_rx = f'(?:(?!{exc.rx})[\\s\\S])'
        else:
            chars = ''.join(text_list(exc) if not isinstance(exc, Char) else [exc.str()])
            cls_rx = '[^' + re.escape(chars) + ']'
    c = _count(a, 'wildcardPattern')
    if c is None:
        return Pattern(f'{cls_rx}+?', label + ('(Except=…)' if exc is not None else ''))
    lo, hi = c
    q = f'{{{lo}}}' if lo == hi else f'{{{lo},{"" if hi is None else hi}}}?'
    return Pattern(f'{cls_rx}{q}', f'{label}({lo}{"" if lo == hi else ", " + str(hi)})')


@bi('characterListPattern')
def characterListPattern(nargout, *args):
    """pat = characterListPattern(chars), characterListPattern(startChar, endChar): one of the characters (or of the range)."""
    nargchk(args, 1, 2, 'characterListPattern')
    if len(args) == 2:
        a, b = py_str(args[0]), py_str(args[1])
        return Pattern(f'[{re.escape(a)}-{re.escape(b)}]', f'characterListPattern("{a}", "{b}")')
    chars = py_str(args[0])
    return Pattern('[' + re.escape(chars) + ']', f'characterListPattern("{chars}")')


@bi('optionalPattern')
def optionalPattern(nargout, *args):
    """pat = optionalPattern(p): p, or nothing."""
    nargchk(args, 1, 1, 'optionalPattern')
    p = _pat(args[0], 'optionalPattern')
    return Pattern(f'(?:{p.rx})?', f'optionalPattern({p.text})')


def _many(args, fn, lazy):
    nargchk(args, 1, 3, fn)
    p = _pat(args[0], fn)
    lo = int(num(args[1])) if len(args) > 1 else 0
    hi = float(num(args[2])) if len(args) > 2 else np.inf
    q = f'{{{lo},{"" if np.isinf(hi) else int(hi)}}}' + ('?' if lazy else '')
    return Pattern(f'(?:{p.rx}){q}', f'{fn}({p.text}{", " + str(lo) if len(args) > 1 else ""}{", " + str(int(hi)) if len(args) > 2 and np.isfinite(hi) else ""})')


@bi('asManyOfPattern')
def asManyOfPattern(nargout, *args):
    """pat = asManyOfPattern(p, min, max): p repeated as many times as it can (min 0 and max Inf unless given)."""
    return _many(args, 'asManyOfPattern', False)


@bi('asFewOfPattern')
def asFewOfPattern(nargout, *args):
    """pat = asFewOfPattern(p, min, max): p repeated as few times as it can."""
    return _many(args, 'asFewOfPattern', True)


def _boundary(cls_rx, args, fn):
    kind = py_str(args[0]).lower() if args else 'either'
    start = f'(?<!{cls_rx})(?={cls_rx})'
    end = f'(?<={cls_rx})(?!{cls_rx})'
    rx = {'start': start, 'end': end, 'either': f'(?:{start}|{end})'}.get(kind)
    if rx is None:
        raise err(f'MATLAB:{fn}:type', "The boundary is 'start', 'end' or 'either'.", fn)
    return Pattern(rx, f'{fn}("{kind}")' if args else fn)


@bi('letterBoundary')
def letterBoundary(nargout, *args):
    """pat = letterBoundary(type): where letters start ('start'), end ('end') or either."""
    return _boundary('[^\\W\\d_]', args, 'letterBoundary')


@bi('digitBoundary')
def digitBoundary(nargout, *args):
    """pat = digitBoundary(type): where digits start, end or either."""
    return _boundary('[0-9]', args, 'digitBoundary')


@bi('alphanumericBoundary')
def alphanumericBoundary(nargout, *args):
    """pat = alphanumericBoundary(type): where letters and digits start, end or either."""
    return _boundary('[^\\W_]', args, 'alphanumericBoundary')


@bi('whitespaceBoundary')
def whitespaceBoundary(nargout, *args):
    """pat = whitespaceBoundary(type): where white space starts, ends or either."""
    return _boundary('\\s', args, 'whitespaceBoundary')


@bi('lineBoundary')
def lineBoundary(nargout, *args):
    """pat = lineBoundary(type): the start of a line ('start'), its end, or either."""
    kind = py_str(args[0]).lower() if args else 'either'
    start, end = '(?:(?<=\\n)|(?<![\\s\\S]))', '(?=\\n|(?![\\s\\S]))'
    rx = {'start': start, 'end': end, 'either': f'(?:{start}|{end})'}.get(kind)
    if rx is None:
        raise err('MATLAB:lineBoundary:type', "The boundary is 'start', 'end' or 'either'.", 'lineBoundary')
    return Pattern(rx, f'lineBoundary("{kind}")')


@bi('textBoundary')
def textBoundary(nargout, *args):
    """pat = textBoundary(type): the start of the text ('start'), its end, or either."""
    kind = py_str(args[0]).lower() if args else 'either'
    start, end = '(?<![\\s\\S])', '(?![\\s\\S])'
    rx = {'start': start, 'end': end, 'either': f'(?:{start}|{end})'}.get(kind)
    if rx is None:
        raise err('MATLAB:textBoundary:type', "The boundary is 'start', 'end' or 'either'.", 'textBoundary')
    return Pattern(rx, f'textBoundary("{kind}")')


@bi('lookAheadBoundary')
def lookAheadBoundary(nargout, *args):
    """pat = lookAheadBoundary(p): where p comes next (nothing taken)."""
    nargchk(args, 1, 1, 'lookAheadBoundary')
    p = _pat(args[0], 'lookAheadBoundary')
    return Pattern(f'(?={p.rx})', f'lookAheadBoundary({p.text})')


@bi('lookBehindBoundary')
def lookBehindBoundary(nargout, *args):
    """pat = lookBehindBoundary(p): where p comes just before (p of a fixed length here)."""
    nargchk(args, 1, 1, 'lookBehindBoundary')
    p = _pat(args[0], 'lookBehindBoundary')
    rx = f'(?<={p.rx})'
    try:
        re.compile(rx)
    except re.error:
        raise err('MATLAB:lookBehindBoundary:width', 'The pattern looked behind for has a fixed length here (digitsPattern(3), not digitsPattern).', 'lookBehindBoundary')
    return Pattern(rx, f'lookBehindBoundary({p.text})')


@bi('regexpPattern')
def regexpPattern(nargout, *args):
    """pat = regexpPattern(expr): a regular expression as regexp reads it."""
    nargchk(args, 1, 7, 'regexpPattern')
    from .strfun import _py_pattern
    expr = py_str(args[0])
    return Pattern(f'(?:{_py_pattern(expr)})', f'regexpPattern("{expr}")')


@bi('caseInsensitivePattern')
def caseInsensitivePattern(nargout, *args):
    """pat = caseInsensitivePattern(p): p matched whatever the case."""
    nargchk(args, 1, 1, 'caseInsensitivePattern')
    p = _pat(args[0], 'caseInsensitivePattern')
    return Pattern(f'(?i:{p.rx})', f'caseInsensitivePattern({p.text})')


@bi('caseSensitivePattern')
def caseSensitivePattern(nargout, *args):
    """pat = caseSensitivePattern(p): p matched in its own case."""
    nargchk(args, 1, 1, 'caseSensitivePattern')
    p = _pat(args[0], 'caseSensitivePattern')
    return Pattern(f'(?-i:{p.rx})', f'caseSensitivePattern({p.text})')


@bi('namedPattern')
def namedPattern(nargout, *args):
    """pat = namedPattern(p, name): p with a name (shown in the pattern; matched as p)."""
    nargchk(args, 1, 3, 'namedPattern')
    p = _pat(args[0], 'namedPattern')
    name = py_str(args[1]) if len(args) > 1 else 'pattern'
    return Pattern(p.rx, f'{name}')


@bi('pattern')
def pattern(nargout, *args):
    """pat = pattern(text): text as a pattern that matches it."""
    nargchk(args, 0, 1, 'pattern')
    return _pat(args[0] if args else Char.of(''), 'pattern')


# ---- operators ----------------------------------------------------------------------------------------------------------------

def _ops(op, *xs):
    if op == 'plus':
        a, b = _pat(xs[0]), _pat(xs[1])
        return Pattern(a.rx + b.rx, f'{a.text} + {b.text}')
    if op == 'or_':
        a, b = _pat(xs[0]), _pat(xs[1])
        return Pattern(f'(?:{a.rx}|{b.rx})', f'{a.text} | {b.text}')
    if op in ('hcat', 'vcat'):
        ps = [_pat(x) for x in xs if numel(x) or isinstance(x, Pattern)]
        return Pattern('(?:' + '|'.join(p.rx for p in ps) + ')', '[' + ' '.join(p.text for p in ps) + ']', alts=ps)
    raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for patterns: join them with + and offer alternatives with |.")


def _register_ops():
    from .. import ops
    ops.OBJ_OPS[Pattern] = _ops
    # "a" | "b": strings offered as alternatives make a pattern
    base = ops.or_

    def or_(a, b):
        if type(a) is Str or type(b) is Str:
            return _ops('or_', a, b)
        return base(a, b)
    ops.or_ = or_
    R.or_ = or_


_register_ops()


# ---- the text functions with patterns ---------------------------------------------------------------------------------------------

def _tin(v, fn):
    from .strfun import _TextIn
    return _TextIn(v, fn)


def _logical(tin, vals):
    from .strfun import _logical_result
    return _logical_result(tin, vals)


def _flags(rest):
    ic = False
    i = 0
    while i < len(rest) - 1:
        if is_str(rest[i]) and py_str(rest[i]).lower() == 'ignorecase':
            ic = bool(np.asarray(darr(rest[i + 1])).reshape(-1)[0])
        i += 2
    return re.IGNORECASE if ic else 0


def _rx(p, flags=0):
    return re.compile(p.rx, flags)


def _p_contains(nargout, *args):
    tin = _tin(args[0], 'contains')
    rx = _rx(_pat(args[1]), _flags(args[2:]))
    return _logical(tin, [s is not None and rx.search(s) is not None for s in tin.items])


def _p_starts(nargout, *args):
    tin = _tin(args[0], 'startsWith')
    rx = _rx(_pat(args[1]), _flags(args[2:]))
    return _logical(tin, [s is not None and rx.match(s) is not None for s in tin.items])


def _p_ends(nargout, *args):
    tin = _tin(args[0], 'endsWith')
    rx = re.compile(f'(?:{_pat(args[1]).rx})(?![\\s\\S])', _flags(args[2:]))
    return _logical(tin, [s is not None and any(True for _ in rx.finditer(s)) for s in tin.items])


def _p_matches(nargout, *args):
    tin = _tin(args[0], 'matches')
    rx = _rx(_pat(args[1]), _flags(args[2:]))
    return _logical(tin, [s is not None and rx.fullmatch(s) is not None for s in tin.items])


def _p_count(nargout, *args):
    tin = _tin(args[0], 'count')
    rx = _rx(_pat(args[1]), _flags(args[2:]))
    vals = [float(sum(1 for m in rx.finditer(s) if m.end() > m.start() or True)) if s is not None else np.nan for s in tin.items]
    if tin.kind == 'char':
        return vals[0]
    return np.array(vals, float).reshape(tin.shape, order='F')


def _p_strfind(nargout, *args):
    tin = _tin(args[0], 'strfind')
    rx = _rx(_pat(args[1]))
    res = [np.array([[m.start() + 1.0 for m in rx.finditer(s)]]).reshape(1, -1) if s is not None else EMPTY() for s in tin.items]
    for i, r in enumerate(res):
        if r.size == 0:
            res[i] = np.zeros((1, 0))
    if tin.kind == 'char' or (tin.kind == 'string' and len(res) == 1):
        return res[0]
    c = Cell.empty(tin.shape)
    for i, r in enumerate(res):
        c.a.reshape(-1, order='F')[i] = r
    return c


def _p_replace(nargout, *args):
    tin = _tin(args[0], 'replace')
    rx = _rx(_pat(args[1]))
    new = text_list(args[2]) if not isinstance(args[2], Char) else [args[2].str()]
    rep = new[0] if new else ''
    return tin.back([rx.sub(lambda m: rep, s) if s is not None else None for s in tin.items])


def _p_erase(nargout, *args):
    tin = _tin(args[0], 'erase')
    rx = _rx(_pat(args[1]))
    return tin.back([rx.sub('', s) if s is not None else None for s in tin.items])


def _p_split(nargout, *args):
    tin = _tin(args[0], 'split')
    if len(tin.items) != 1:
        raise err('MATLAB:split:pattern', 'split with a pattern takes one text here.', 'split')
    rx = _rx(_pat(args[1]))
    s = tin.items[0]
    parts = rx.split(s) if rx.groups == 0 else re.split('(?:' + rx.pattern + ')', s)
    seps = [m.group(0) for m in rx.finditer(s)]
    def col(items):
        if tin.kind in ('char', 'cell'):
            return Cell.of_list([Char.of(x) for x in items], (len(items), 1))
        return Str(np.array(items, object).reshape(-1, 1))
    return (col(parts), col(seps)) if nargout > 1 else col(parts)


def _first_match(s, rx):
    return rx.search(s) if s is not None else None


def _p_before(nargout, *args):
    tin = _tin(args[0], 'extractBefore')
    rx = _rx(_pat(args[1]))
    res = []
    for s in tin.items:
        m = _first_match(s, rx)
        res.append(s[:m.start()] if m else None)
    return tin.back(res)


def _p_after(nargout, *args):
    tin = _tin(args[0], 'extractAfter')
    rx = _rx(_pat(args[1]))
    res = []
    for s in tin.items:
        m = _first_match(s, rx)
        res.append(s[m.end():] if m else None)
    return tin.back(res)


def _p_between(nargout, *args):
    tin = _tin(args[0], 'extractBetween')
    a, b = _pat(args[1]), _pat(args[2])
    boundaries = 'exclusive'
    for i in range(3, len(args) - 1, 2):
        if is_str(args[i]) and py_str(args[i]).lower() == 'boundaries':
            boundaries = py_str(args[i + 1]).lower()
    rx = re.compile(f'({a.rx})([\\s\\S]*?)({b.rx})')
    found = []
    for s in tin.items:
        found.append([(m.group(0) if boundaries == 'inclusive' else m.group(2)) for m in rx.finditer(s or '')])
    if len(tin.items) == 1:
        items = found[0]
        if tin.kind in ('char', 'cell'):
            return Cell.of_list([Char.of(x) for x in items], (len(items), 1))
        return Str(np.array(items, object).reshape(-1, 1))
    return tin.back([f[0] if f else None for f in found])


def _p_insert(fn, before):
    def f(nargout, *args):
        tin = _tin(args[0], fn)
        rx = _rx(_pat(args[1]))
        new = py_str(args[2])
        res = []
        for s in tin.items:
            if s is None:
                res.append(None)
                continue
            res.append(rx.sub(lambda m: (new + m.group(0)) if before else (m.group(0) + new), s))
        return tin.back(res)
    return f


@bi('extract')
def extract(nargout, *args):
    """newStr = extract(str, pat), extract(str, pos): the parts of the text that match the pattern (a column of them for one text), or the characters at positions."""
    nargchk(args, 2, 2, 'extract')
    tin = _tin(args[0], 'extract')
    if not isinstance(args[1], Pattern) and not is_str(args[1]):
        pos = np.asarray(darr(args[1]), int).reshape(-1)
        res = [''.join(s[p - 1] for p in pos if 0 < p <= len(s)) if s is not None else None for s in tin.items]
        return tin.back(res)
    rx = _rx(_pat(args[1]))
    found = [[m.group(0) for m in rx.finditer(s)] if s is not None else [] for s in tin.items]
    if len(tin.items) == 1:
        items = found[0]
        if tin.kind in ('char', 'cell'):
            return Cell.of_list([Char.of(x) for x in items], (len(items), 1)) if len(items) != 1 or tin.kind == 'cell' else Char.of(items[0])
        return Str(np.array(items, object).reshape(-1, 1)) if items else Str(np.empty((0, 1), object))
    if all(len(f) == 1 for f in found):
        return tin.back([f[0] for f in found])
    c = Cell.empty(tin.shape)
    for i, f in enumerate(found):
        c.a.reshape(-1, order='F')[i] = Str(np.array(f, object).reshape(-1, 1)) if tin.kind == 'string' else Cell.of_list([Char.of(x) for x in f], (len(f), 1))
    return c


def _wrap(name, handler, positions=(1,)):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw

    def wants(args):
        return any(k < len(args) and isinstance(args[k], Pattern) for k in positions)
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if wants(args):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if wants(args):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


for _name, _h, _pos in (('contains', _p_contains, (1,)), ('startsWith', _p_starts, (1,)), ('endsWith', _p_ends, (1,)),
                        ('matches', _p_matches, (1,)), ('count', _p_count, (1,)), ('strfind', _p_strfind, (1,)),
                        ('replace', _p_replace, (1,)), ('erase', _p_erase, (1,)), ('split', _p_split, (1,)), ('strsplit', _p_split, (1,)),
                        ('extractBefore', _p_before, (1,)), ('extractAfter', _p_after, (1,)), ('extractBetween', _p_between, (1, 2)),
                        ('insertBefore', _p_insert('insertBefore', True), (1,)), ('insertAfter', _p_insert('insertAfter', False), (1,))):
    _wrap(_name, _h, _pos)
