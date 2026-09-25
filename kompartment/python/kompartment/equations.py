"""Reading and rewriting the equations a model is written in.

Kompartment's equations are plain text -- ``k * Soil``, ``Kd[Cs-137] * rho``,
``NearField.Water / 2`` -- and a block is referred to by writing its name. So a
rename or a move has to find every place a name is *written* and change it
there, without touching anything else: ``C1`` inside ``C10``, a function called
``exp``, or an index in brackets that happens to share a block's name.

That is done on tokens, exactly as the application does it. The tokenizer here
is a port of ``tokenize`` in ``src/parser/parser.js`` and splits text the same
way, character for character:

* a number, including ``1e-5`` and ``1.0E10``;
* a name, where a dotted path such as ``NearField.Water`` is **one** name
  (the dot is taken only when a letter follows it);
* the text inside ``[...]``, raw, as one *index* token -- an index is read
  exactly as written (``Cs-137``, ``B.04:00_205``), never as names;
* brackets, parentheses, commas and the operators.

Rewriting works token by token and copies everything between the tokens it
changes, so an equation comes back exactly as it was typed apart from the
names that moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Set

from .names import RESERVED, resolve_reference


class EquationSyntaxError(ValueError):
    """An equation holds a character the language has no use for."""

    def __init__(self, message: str, position: int, source: str) -> None:
        super().__init__(message)
        self.position = position
        self.source = source


@dataclass(frozen=True)
class Token:
    """One token of an equation: its kind, its text and where it starts."""

    type: str  # 'number', 'ident', 'op', 'lparen', 'rparen', 'comma',
    #            'lbracket', 'rbracket', 'index', 'eof'
    text: str
    pos: int

    @property
    def value(self) -> str:
        """The text of a name or an index -- what it says."""
        return self.text


# Multi-character operators are tried before single-character ones, in this
# order, as the tokenizer in the application does.
OPERATORS = (
    '<=', '>=', '==', '~=', '!=', '&&', '||', '.*', './', '.^',
    '+', '-', '*', '/', '^', '<', '>', '?', ':',
)


def _is_digit(c: str) -> bool:
    return '0' <= c <= '9'


def _is_ident_start(c: str) -> bool:
    return ('a' <= c <= 'z') or ('A' <= c <= 'Z') or c == '_'


def _is_ident_part(c: str) -> bool:
    return _is_ident_start(c) or _is_digit(c)


def tokenize(src: str) -> List[Token]:
    """Splits an equation into tokens, as the application does.

    Raises :class:`EquationSyntaxError` on a character the language does not
    use, which is also what the application does with it.
    """
    src = str(src)
    tokens: List[Token] = []
    i = 0
    n = len(src)
    at = lambda k: src[k] if k < n else ''  # noqa: E731 -- a bounds-safe index
    while i < n:
        c = src[i]
        if c in ' \t\n\r':
            i += 1
            continue
        # Numbers, including 1e-5 and 1.0E10.
        if _is_digit(c) or (c == '.' and _is_digit(at(i + 1))):
            start = i
            while i < n and _is_digit(src[i]):
                i += 1
            if at(i) == '.':
                i += 1
                while i < n and _is_digit(src[i]):
                    i += 1
            if at(i) in ('e', 'E'):
                save = i
                i += 1
                if at(i) in ('+', '-'):
                    i += 1
                if _is_digit(at(i)):
                    while i < n and _is_digit(src[i]):
                        i += 1
                else:
                    i = save  # "2e" in "2*ex" is not an exponent
            tokens.append(Token('number', src[start:i], start))
            continue
        if _is_ident_start(c):
            start = i
            while i < n and _is_ident_part(src[i]):
                i += 1
            # A dotted path is one name: the dot is swallowed only when a
            # letter follows it, so `a .* b` is three tokens.
            while at(i) == '.' and _is_ident_start(at(i + 1)):
                i += 1
                while i < n and _is_ident_part(src[i]):
                    i += 1
            tokens.append(Token('ident', src[start:i], start))
            continue
        if c == '(':
            tokens.append(Token('lparen', c, i))
            i += 1
            continue
        if c == ')':
            tokens.append(Token('rparen', c, i))
            i += 1
            continue
        if c == ',':
            tokens.append(Token('comma', c, i))
            i += 1
            continue
        if c == '[':
            tokens.append(Token('lbracket', c, i))
            i += 1
            start = i
            while i < n and src[i] != ']':
                i += 1
            if i > start:
                tokens.append(Token('index', src[start:i], start))
            continue
        if c == ']':
            tokens.append(Token('rbracket', c, i))
            i += 1
            continue
        op = next((o for o in OPERATORS if src.startswith(o, i)), None)
        if op:
            tokens.append(Token('op', op, i))
            i += len(op)
            continue
        raise EquationSyntaxError(f"Unexpected character '{c}'", i, src)
    tokens.append(Token('eof', '<end>', n))
    return tokens


def _reference_tokens(tokens: List[Token], skip: Optional[Set[str]]) -> Iterable[Token]:
    """The name tokens that may be references to blocks.

    A built-in function call -- ``exp(``, ``min(`` -- is not, and neither is a
    name local to the equation (a user-defined function's parameters).
    Anything else in front of a ``(`` may be a lookup table read with an
    argument, which *is* a reference, so only the reserved names are skipped.
    """
    for k, tok in enumerate(tokens):
        if tok.type != 'ident':
            continue
        if tokens[k + 1].type == 'lparen' and tok.text in RESERVED:
            continue
        if skip and tok.text in skip:
            continue
        yield tok


def names_in(equation: object) -> List[str]:
    """Every name written in an equation, as written, in order.

    Built-in function names are left out; so is ``time``. An equation that
    will not tokenize names nothing.
    """
    text = '' if equation is None else str(equation)
    if not text:
        return []
    try:
        tokens = tokenize(text)
    except EquationSyntaxError:
        return []
    return [t.text for t in _reference_tokens(tokens, None) if t.text != 'time']


def references_in(equation: object, system: str, known: Callable[[str], bool],
                  skip: Optional[Set[str]] = None) -> List[str]:
    """The blocks an equation refers to, as qualified names.

    Each name is resolved from ``system`` -- the sub-system the equation is
    written in -- the way the application resolves it, against ``known``, a
    predicate saying whether a qualified name is a block.
    """
    text = '' if equation is None else str(equation)
    if not text:
        return []
    try:
        tokens = tokenize(text)
    except EquationSyntaxError:
        return []
    out: List[str] = []
    for tok in _reference_tokens(tokens, skip):
        q = resolve_reference(tok.text, system, known)
        if q is not None:
            out.append(q)
    return out


def rewrite_references(equation: object, system: str, known: Callable[[str], bool],
                       replace: Callable[[str, str], Optional[str]],
                       skip: Optional[Set[str]] = None) -> str:
    """Rewrites the block references in one equation.

    ``replace(qualified_name, system)`` answers with the text a reference to
    that block should now be written as, or ``None`` to leave it. Text that
    will not tokenize is returned unchanged, for its author to put right.
    """
    src = '' if equation is None else str(equation)
    if not src:
        return src
    try:
        tokens = tokenize(src)
    except EquationSyntaxError:
        return src
    out: List[str] = []
    cursor = 0
    for tok in _reference_tokens(tokens, skip):
        q = resolve_reference(tok.text, system, known)
        if q is None:
            continue
        to = replace(q, system)
        if to is None or to == tok.text:
            continue
        out.append(src[cursor:tok.pos])
        out.append(to)
        cursor = tok.pos + len(tok.text)
    out.append(src[cursor:])
    return ''.join(out)


def rewrite_written_indices(equation: object,
                            mapping: Callable[[str], Optional[str]]) -> str:
    """Rewrites index names written in brackets, and nothing else.

    ``mapping(name)`` answers with the name it should become, or ``None``. Used
    when an index is renamed: ``K[Lake]`` becomes ``K[Pond]``.
    """
    src = '' if equation is None else str(equation)
    if '[' not in src:
        return src
    try:
        tokens = tokenize(src)
    except EquationSyntaxError:
        return src
    out: List[str] = []
    cursor = 0
    for tok in tokens:
        if tok.type != 'index':
            continue
        was = tok.text.strip()
        to = mapping(was)
        if to is None or to == was:
            continue
        out.append(src[cursor:tok.pos])
        out.append(tok.text.replace(was, to, 1))
        cursor = tok.pos + len(tok.text)
    out.append(src[cursor:])
    return ''.join(out)


def reads_clock(equation: object) -> bool:
    """Whether an equation reads the simulation clock, ``time``."""
    try:
        return any(t.type == 'ident' and t.text == 'time' for t in tokenize(str(equation or '')))
    except EquationSyntaxError:
        return False


def check_syntax(equation: object) -> Optional[str]:
    """What is wrong with an equation's characters, or ``None``.

    Only the tokenizer's check: whether every character belongs to the
    language. Unknown names, arity and units are checked by the application,
    which :meth:`kompartment.Model.validate` can run.
    """
    try:
        tokenize(str(equation or ''))
    except EquationSyntaxError as e:
        return f'{e} at position {e.position + 1}'
    return None
