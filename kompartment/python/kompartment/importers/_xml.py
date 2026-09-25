"""A small XML reader, the one the Ecolego importer reads model.xml with.

A port of ``src/io/xml.js``, kept rather than replaced by the standard
library's parsers so that a file is read the same way here as in the
application: the same subset of XML is accepted -- elements, attributes, text,
CDATA, comments, the XML declaration and the five predefined entities, and
nothing else (no namespaces, no DTDs, no entity declarations) -- the same
malformed files are refused with the same message, and the text of an element
is exactly what the application sees. ``xml.etree`` would read a namespace
prefix, a DTD entity or a stray ``&nbsp;`` differently, and refuse files this
reads.

An element is a :class:`Node`: its ``name``, its ``attrs``, its ``children``
and its ``text`` -- every piece of text directly inside it, concatenated.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterator, List, Optional

from ._eco_maps import JS_SPACE_CLASS, js_trim, to_number, utf16_index


class XMLError(ValueError):
    """A document this reader cannot read. ``position`` is where it gave up,
    counted in UTF-16 code units as the application counts, or ``None``."""

    def __init__(self, message: str, position: Optional[int] = None) -> None:
        super().__init__(f'{message} (at character {position})' if position is not None else message)
        self.position = position


class Node:
    """One element: ``name``, ``attrs`` (in the order written; a repeated
    attribute keeps its first place and its last value), ``children`` and
    ``text``."""

    __slots__ = ('name', 'attrs', 'children', 'text', 'self_closing')

    def __init__(self, name: str) -> None:
        self.name = name
        self.attrs: Dict[str, str] = {}
        self.children: List['Node'] = []
        self.text = ''
        self.self_closing = False

    def __repr__(self) -> str:
        return f'<Node {self.name} {len(self.children)} children>'


ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}

_ENTITY = re.compile(r'&(#x?[0-9a-fA-F]+|[a-zA-Z]+);')
# What ends a tag or attribute name: JavaScript's white space, `/`, `>` or `=`.
_NAME = re.compile('[^' + JS_SPACE_CLASS + '/>=]*')
_SPACE = re.compile('[ \t\n\r]*')
_DIGITS = {10: re.compile('[0-9]*'), 16: re.compile('[0-9a-fA-F]*')}


def _parse_int(text: str, radix: int) -> Optional[int]:
    # `parseInt`: the longest run of digits at the start, or NaN (None).
    run = _DIGITS[radix].match(text).group(0)
    return int(run, radix) if run else None


def _entity(m: 're.Match[str]') -> str:
    whole, body = m.group(0), m.group(1)
    if body[0] == '#':
        code = _parse_int(body[2:], 16) if body[1:2] in ('x', 'X') else _parse_int(body[1:], 10)
        # Not a code point, or half of a surrogate pair: left as written, as a
        # comment that reads oddly rather than an import that fails.
        if code is None or code < 0 or code > 0x10FFFF:
            return whole
        if 0xD800 <= code <= 0xDFFF:
            return whole
        return chr(code)
    return ENTITIES.get(body, whole)


def decode_entities(text: str) -> str:
    """The five predefined entities and numeric character references decoded;
    anything else (``&nbsp;``, ``&#1114112;``) left as written."""
    if '&' not in text:
        return text
    return _ENTITY.sub(_entity, text)


def parse_xml(src: str) -> Node:
    """Reads a document; returns its root element. Raises :class:`XMLError`
    for what it cannot read, with the application's message."""
    i = 0
    n = len(src)
    stack: List[Node] = []
    parts: List[List[str]] = []  # the text of each open element, in pieces
    root: Optional[Node] = None

    def fail(message: str) -> None:
        raise XMLError(message, utf16_index(src, i))

    def read_name() -> str:
        nonlocal i
        start = i
        i = _NAME.match(src, i).end()
        if i == start:
            fail('Expected a name')
        return src[start:i]

    def skip_space() -> None:
        nonlocal i
        i = _SPACE.match(src, i).end()

    def add_text(raw: str) -> None:
        if parts:
            parts[-1].append(raw)

    while i < n:
        lt = src.find('<', i)
        if lt == -1:
            add_text(decode_entities(src[i:]))
            break
        if lt > i:
            add_text(decode_entities(src[i:lt]))
        i = lt

        if src.startswith('<!--', i):
            end = src.find('-->', i + 4)
            if end == -1:
                fail('Unterminated comment')
            i = end + 3
            continue
        # CDATA is verbatim: no entity decoding.
        if src.startswith('<![CDATA[', i):
            end = src.find(']]>', i + 9)
            if end == -1:
                fail('Unterminated CDATA section')
            add_text(src[i + 9:end])
            i = end + 3
            continue
        if src.startswith('<?', i):
            end = src.find('?>', i + 2)
            if end == -1:
                fail('Unterminated processing instruction')
            i = end + 2
            continue
        if src.startswith('<!', i):
            end = src.find('>', i + 2)
            if end == -1:
                fail('Unterminated declaration')
            i = end + 1
            continue

        if src.startswith('</', i):
            i += 2
            name = read_name()
            skip_space()
            if i >= n or src[i] != '>':
                fail(f"Expected '>' closing </{name}")
            i += 1
            if not stack:
                fail(f'Unexpected closing tag </{name}>')
            open_ = stack.pop()
            open_.text = ''.join(parts.pop())
            if open_.name != name:
                raise XMLError(f'Closing tag </{name}> does not match <{open_.name}>',
                               utf16_index(src, i))
            continue

        i += 1
        name = read_name()
        node = Node(name)
        while True:
            skip_space()
            if i >= n:
                fail('Unterminated tag')
            if src[i] == '>':
                i += 1
                break
            if src.startswith('/>', i):
                i += 2
                node.self_closing = True
                break
            attr = read_name()
            skip_space()
            if i >= n or src[i] != '=':
                fail(f"Expected '=' after attribute '{attr}'")
            i += 1
            skip_space()
            quote = src[i] if i < n else ''
            if quote not in ('"', "'"):
                fail(f"Expected a quoted value for attribute '{attr}'")
            i += 1
            end = src.find(quote, i)
            if end == -1:
                fail(f"Unterminated value for attribute '{attr}'")
            node.attrs[attr] = decode_entities(src[i:end])
            i = end + 1

        if stack:
            stack[-1].children.append(node)
        elif root is not None:
            fail('More than one root element')
        else:
            root = node
        if not node.self_closing:
            stack.append(node)
            parts.append([])

    if stack:
        raise XMLError(f'Unclosed element <{stack[-1].name}>')
    if root is None:
        raise XMLError('The document has no elements')
    return root


# --- convenience accessors ----------------------------------------------------------

def child(node: Optional[Node], name: str) -> Optional[Node]:
    """The first direct child called ``name``, or ``None``."""
    if node is None:
        return None
    for c in node.children:
        if c.name == name:
            return c
    return None


def children(node: Optional[Node], name: str) -> List[Node]:
    """Every direct child called ``name``."""
    if node is None:
        return []
    return [c for c in node.children if c.name == name]


def child_text(node: Optional[Node], name: str, fallback: Optional[str] = None) -> Optional[str]:
    """The text of the first child called ``name``, trimmed, or ``fallback``
    when there is no such child or its text is blank."""
    c = child(node, name)
    if c is None:
        return fallback
    t = js_trim(c.text)
    return fallback if t == '' else t


def child_number(node: Optional[Node], name: str, fallback: Optional[float] = None) -> Optional[float]:
    """A child's text as a finite number, or ``fallback``."""
    t = child_text(node, name)
    if t is None:
        return fallback
    v = to_number(t)
    return v if math.isfinite(v) else fallback


def child_bool(node: Optional[Node], name: str, fallback: Optional[bool] = None) -> Optional[bool]:
    """Whether a child's text is ``true`` (in any case); ``fallback`` when
    there is none."""
    t = child_text(node, name)
    if t is None:
        return fallback
    return t.lower() == 'true'


def walk(node: Node) -> Iterator[Node]:
    """Every element under ``node``, ``node`` first, depth first in document
    order. Iterative, so nesting depth is no limit."""
    stack = [node]
    while stack:
        el = stack.pop()
        yield el
        stack.extend(reversed(el.children))


def find(node: Node, name: str) -> Optional[Node]:
    """The first element anywhere under ``node`` (``node`` included) called
    ``name``, or ``None``."""
    for el in walk(node):
        if el.name == name:
            return el
    return None
