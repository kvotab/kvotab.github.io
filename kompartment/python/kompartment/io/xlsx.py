"""Excel workbooks, read and written, as Kompartment reads and writes them.

A port of the application's ``src/io/xlsx.js``: a sheet in, a sheet out, in
as little of the format as a table of values needs. There are no formulas,
no styles beyond a bold first row, no merged cells and no charts; what crosses
is a grid of values::

    from kompartment.io import xlsx

    data = xlsx.write_workbook({'sheets': [{'name': 'data', 'rows': [['ID', 'Value'], ['k', 0.05]]}]})
    book = xlsx.read_workbook(data)          # {'sheets': [{'name': 'data', 'rows': [...]}]}

**Reading.** The parts that matter are four: ``xl/workbook.xml`` (the sheet
names, in order, each naming a relationship id), ``xl/_rels/workbook.xml.rels``
(that id's target), ``xl/sharedStrings.xml`` (the string table) and the
worksheets. A cell carries its address rather than its position and a row
omits every empty cell, so the grid is rebuilt from the addresses, the gaps
filled with ``None``, and every row made as wide as the widest. ``t="s"`` is an
index into the shared strings, ``t="b"`` a boolean, ``t="inlineStr"`` its own
text, and anything else a number where it reads as one -- a float, as in the
application, whose numbers are all doubles. **A date is a number here**: Excel
says a number is a date only in the cell's style, which is not followed.

**Writing.** The five parts Excel needs and nothing else, text as inline
strings, the header row in bold. The workbook is a ZIP laid out exactly as
the application lays it out -- the same entries in the same order, the same
headers, the same timestamp (the epoch by default, so the same model gives the
same file) -- with each entry deflated where that makes it smaller. Deflate is
zlib's, at its default level, which is also what the application asks its
platform for; but platforms' deflate encoders differ in the bytes they choose
(Node's zlib is Chromium's), so a compressed entry is the same data rather
than the same bytes. With ``compress=False`` every entry is stored, which is
what the application writes where the platform cannot compress, and then the
file is the application's to the byte.

The XML reader is a port of the application's own small parser
(``src/io/xml.js``): elements, attributes, text, CDATA, comments and the five
predefined entities, with names kept as written (``r:id``, not a namespace URI).
"""

from __future__ import annotations

import datetime as _dt
import io
import math
import numbers
import os
import re
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from ..errors import KompartmentError
from .csv import JS_WHITESPACE, is_js_boolean, js_string, js_to_number

__all__ = ['XLSXError', 'XMLError', 'xml_escape', 'column_of', 'column_name', 'read_workbook',
           'write_workbook']

#: The most a whole archive may expand to, as the application's reader allows.
MAX_INFLATED = 256 * 1024 * 1024


class XLSXError(KompartmentError, ValueError):
    """A workbook that cannot be read or written: not a ZIP, no workbook part,
    no readable sheet, or nothing to write."""


class XMLError(XLSXError):
    """A part of the workbook that is not the XML it should be.

    The application raises its parser's own ``XMLError`` here rather than an
    ``XLSXError``; here it is both, so one ``except XLSXError`` catches every
    reason a workbook would not open. ``position`` is the character at which
    the parser stopped.
    """

    def __init__(self, message: str, position: Optional[int] = None) -> None:
        super().__init__(f'{message} (at character {position})' if position is not None else message)
        self.position = position


def _utf8(s: str) -> bytes:
    """``TextEncoder``: UTF-8, a lone surrogate written as U+FFFD."""
    try:
        return s.encode('utf-8')
    except UnicodeEncodeError:
        return s.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')


def _text(b: bytes) -> str:
    """``TextDecoder``: invalid bytes as U+FFFD, a leading BOM dropped."""
    return b.decode('utf-8-sig', 'replace')


_CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')


def xml_escape(s: Any, attr: bool = False) -> str:
    """``&``, ``<`` and ``>`` escaped for content; the double quote too in an
    attribute (``xmlEscape``).

    A control character is not valid XML at all, and a spreadsheet that came
    from a database can contain one: it is dropped rather than escaped,
    because there is no escape for it that a reader will accept. A value that
    is not a string is first written as JavaScript's ``String()`` writes it.
    """
    out = js_string(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if attr:
        out = out.replace('"', '&quot;')
    return _CONTROL.sub('', out)


def column_of(ref: str) -> int:
    """``B7`` -> 1, the zero-based column of a cell reference (``columnOf``).

    Letters are base 26 with no zero, read up to the first character that is
    not a capital letter; a reference with none is -1.
    """
    n = 0
    for ch in ref:
        c = ord(ch)
        if c < 65 or c > 90:
            break
        n = n * 26 + (c - 64)
    return n - 1


def column_name(i: Union[int, float]) -> str:
    """0 -> ``A``, 26 -> ``AA``: a zero-based column as its letters (``columnName``)."""
    if isinstance(i, float):
        if math.isnan(i):
            return ''  # Math.max(0, NaN) is NaN, and the loop never starts
        if math.isinf(i):
            if i < 0:
                return 'A'
            # The JavaScript never returns from this one.
            raise ValueError('A column number has to be finite')
    n = max(0, math.trunc(i)) + 1
    out = ''
    while n > 0:
        r = (n - 1) % 26
        out = chr(65 + r) + out
        n = (n - 1) // 26
    return out


# --- the XML reader (src/io/xml.js) -------------------------------------------

class _Node:
    __slots__ = ('name', 'attrs', 'children', 'text', 'self_closing')

    def __init__(self, name: str) -> None:
        self.name = name
        self.attrs: Dict[str, str] = {}
        self.children: List['_Node'] = []
        self.text = ''
        self.self_closing = False


_ENTITIES = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
_ENTITY = re.compile(r'&(#x?[0-9a-fA-F]+|[a-zA-Z]+);')
_LEADING_DIGITS = re.compile(r'[0-9]+')
# What ends a tag or attribute name: JavaScript's \s, then / > =.
_NAME_END = re.compile('[' + re.escape(JS_WHITESPACE) + '/>=]')


def _decode_entities(s: str) -> str:
    """The five predefined entities and numeric character references, resolved;
    anything else -- an unknown name, a number that is not a code point -- left
    as written."""
    if '&' not in s:
        return s

    def resolve(m: 're.Match[str]') -> str:
        whole, body = m.group(0), m.group(1)
        if body[0] == '#':
            if body[1:2] in ('x', 'X'):
                code: Optional[int] = int(body[2:], 16)
            else:
                # parseInt(..., 10): the leading digits, or NaN.
                digits = _LEADING_DIGITS.match(body, 1)
                code = int(digits.group(0)) if digits else None
            if code is None or code < 0 or code > 0x10FFFF:
                return whole
            if 0xD800 <= code <= 0xDFFF:
                return whole
            return chr(code)
        return _ENTITIES.get(body, whole)

    return _ENTITY.sub(resolve, s)


def _parse_xml(src: str) -> _Node:
    """The root element of a document, as the application's parser builds it."""
    i = 0
    n = len(src)
    stack: List[_Node] = []
    root: Optional[_Node] = None

    def fail(message: str) -> None:
        raise XMLError(message, i)

    def skip_space() -> None:
        nonlocal i
        while i < n and src[i] in ' \t\n\r':
            i += 1

    def read_name() -> str:
        nonlocal i
        start = i
        m = _NAME_END.search(src, i)
        i = m.start() if m else n
        if i == start:
            fail('Expected a name')
        return src[start:i]

    def add_text(raw: str) -> None:
        if stack:
            stack[-1].text += raw

    while i < n:
        lt = src.find('<', i)
        if lt == -1:
            add_text(_decode_entities(src[i:]))
            break
        if lt > i:
            add_text(_decode_entities(src[i:lt]))
        i = lt

        if src.startswith('<!--', i):  # a comment
            end = src.find('-->', i + 4)
            if end == -1:
                fail('Unterminated comment')
            i = end + 3
            continue
        if src.startswith('<![CDATA[', i):  # verbatim, no entity decoding
            end = src.find(']]>', i + 9)
            if end == -1:
                fail('Unterminated CDATA section')
            add_text(src[i + 9:end])
            i = end + 3
            continue
        if src.startswith('<?', i):  # <?xml ... ?>
            end = src.find('?>', i + 2)
            if end == -1:
                fail('Unterminated processing instruction')
            i = end + 2
            continue
        if src.startswith('<!', i):  # <!DOCTYPE ...>
            end = src.find('>', i + 2)
            if end == -1:
                fail('Unterminated declaration')
            i = end + 1
            continue
        if src.startswith('</', i):  # </name>
            i += 2
            name = read_name()
            skip_space()
            if i >= n or src[i] != '>':
                fail(f"Expected '>' closing </{name}")
            i += 1
            opened = stack.pop() if stack else None
            if opened is None:
                fail(f'Unexpected closing tag </{name}>')
            elif opened.name != name:
                raise XMLError(f'Closing tag </{name}> does not match <{opened.name}>', i)
            continue

        # <name attr="value" ...> or <name .../>
        i += 1
        name = read_name()
        node = _Node(name)
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
            attr_name = read_name()
            skip_space()
            if i >= n or src[i] != '=':
                fail(f"Expected '=' after attribute '{attr_name}'")
            i += 1
            skip_space()
            quote = src[i] if i < n else ''
            if quote not in ('"', "'"):
                fail(f"Expected a quoted value for attribute '{attr_name}'")
            i += 1
            end = src.find(quote, i)
            if end == -1:
                fail(f"Unterminated value for attribute '{attr_name}'")
            node.attrs[attr_name] = _decode_entities(src[i:end])
            i = end + 1

        if stack:
            stack[-1].children.append(node)
        elif root is not None:
            fail('More than one root element')
        else:
            root = node
        if not node.self_closing:
            stack.append(node)

    if stack:
        raise XMLError(f'Unclosed element <{stack[-1].name}>')
    if root is None:
        raise XMLError('The document has no elements')
    return root


def _children(node: Optional[_Node], name: str) -> List[_Node]:
    """All direct children with the given name."""
    if node is None:
        return []
    return [c for c in node.children if c.name == name]


def _deep_text(node: Optional[_Node]) -> str:
    """The text of a node and everything under it, entities resolved: its own
    text first, then each child's, depth first."""
    if node is None:
        return ''
    parts: List[str] = []
    stack = [node]
    while stack:
        el = stack.pop()
        parts.append(el.text)
        stack.extend(reversed(el.children))
    return ''.join(parts)


# --- reading ------------------------------------------------------------------

def _is_integer(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x)) and x == math.floor(x)


def _shared_strings(xml: Optional[str]) -> List[str]:
    """The shared string table: each ``<si>`` as its text, a run of ``<r>``
    elements (two type faces in one cell) as their text together."""
    if not xml:
        return []
    return [_deep_text(si) for si in _children(_parse_xml(xml), 'si')]


def _cell_value(c: _Node, strings: List[str]) -> Any:
    kind = c.attrs.get('t', 'n')
    if kind == 'inlineStr':
        found = _children(c, 'is')
        return _deep_text(found[0] if found else None)
    vs = _children(c, 'v')
    raw = _deep_text(vs[0]) if vs else ''
    if kind == 's':
        k = js_to_number(raw)
        return strings[int(k)] if _is_integer(k) and 0 <= k < len(strings) else ''
    if kind in ('str', 'e'):
        # Decoded a second time, as the application does: the parser has
        # already resolved the entities once.
        return _decode_entities(raw)
    if kind == 'b':
        return raw == '1'
    if raw == '':
        return None
    x = js_to_number(raw)
    return x if not (math.isnan(x) or math.isinf(x)) else raw


_MAX_INDEX = 4294967294  # the largest index a JavaScript array has


def _sheet_grid(xml: str, strings: List[str]) -> List[List[Any]]:
    """One worksheet as a grid: rectangular, and with no holes."""
    root = _parse_xml(xml)
    rows: List[Optional[List[Any]]] = []
    widest = 0
    for sheet_data in _children(root, 'sheetData'):
        for row in _children(sheet_data, 'row'):
            # The row's own number where it has one, so a sheet with a gap in
            # it comes back with the gap.
            r_attr = row.attrs.get('r')
            at = math.nan if r_attr is None else js_to_number(r_attr)
            out: List[Any] = []
            for c in _children(row, 'c'):
                col = column_of(c.attrs.get('r', ''))
                if col < 0 or col > _MAX_INDEX:
                    continue
                if col >= len(out):
                    out.extend([None] * (col + 1 - len(out)))
                out[col] = _cell_value(c, strings)
            widest = max(widest, len(out))
            index = at - 1 if not (math.isnan(at) or math.isinf(at)) and at >= 1 else len(rows)
            # A row number that is not a whole number (or past the largest
            # array index) is a property of the JavaScript's array, not an
            # element of it, and the row is not in the grid.
            if not _is_integer(index) or index > _MAX_INDEX:
                continue
            index = int(index)
            if index >= len(rows):
                rows.extend([None] * (index + 1 - len(rows)))
            rows[index] = out
    grid: List[List[Any]] = []
    for r in rows:
        r = [] if r is None else r
        if len(r) < widest:
            r.extend([None] * (widest - len(r)))
        grid.append(r)
    return grid


class _Entries:
    """The entries of an archive, read when asked for, as the application's
    ``unzip`` hands them over: names as UTF-8, directories left out, and what
    comes out of the archive held to one allowance for the whole of it."""

    def __init__(self, data: bytes) -> None:
        try:
            self.zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            if str(e) != 'File is not a zip file':
                raise
            # No end record: the application's own sentence for it.
            raise XLSXError(
                'This is not a readable .xlsx file: This does not look like a ZIP archive. An '
                'Ecolego project (.eco) is a zipped project folder; a bare model.xml should be '
                'opened directly instead.') from None
        self.infos: Dict[str, zipfile.ZipInfo] = {}
        self.spent = 0
        for info in self.zf.infolist():
            name = info.orig_filename
            if not info.flag_bits & 0x800:
                name = name.encode('cp437').decode('utf-8', 'replace')
            if info.flag_bits & 0x01:
                raise ValueError(f"'{name}' is encrypted. Ecolego can obfuscate a project on save; "
                                 're-save it without that option, or export the model, before importing.')
            if name.endswith('/'):
                continue
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise ValueError(f"'{name}' uses compression method {info.compress_type}, which is not "
                                 'supported (only stored and deflate are).')
            # The XML is inflated on the way past in the application, and so
            # spends its allowance first.
            if info.compress_type == zipfile.ZIP_DEFLATED and name.lower().endswith('.xml'):
                self._spend(name, info.file_size)
            self.infos[name] = info

    def _spend(self, name: str, size: int) -> None:
        def mb(x: float) -> int:
            return math.floor(x / 1048576 + 0.5)
        if size > MAX_INFLATED:
            raise ValueError(f"'{name}' says it expands to {mb(size)} MB, past the {mb(MAX_INFLATED)} MB "
                             'this reader will decompress. No real model is that large.')
        if size > MAX_INFLATED - self.spent:
            raise ValueError(
                f"'{name}' takes this archive past the {mb(MAX_INFLATED)} MB this reader will decompress "
                f'in total: {mb(self.spent)} MB have come out already and this entry adds {mb(size)} '
                'more. No real project expands that far, so the archive is either damaged or built to '
                'exhaust memory.')
        self.spent += size

    def get(self, name: str) -> Optional[bytes]:
        info = self.infos.get(name)
        if info is None:
            return None
        if info.compress_type == zipfile.ZIP_DEFLATED and not name.lower().endswith('.xml'):
            self._spend(name, info.file_size)
        try:
            return self.zf.read(info)
        except Exception as e:  # noqa: BLE001 -- a damaged entry, whatever zipfile calls it
            raise XLSXError(f'This is not a readable .xlsx file: {e}') from None


def read_workbook(data: Union[bytes, bytearray, memoryview, str, 'os.PathLike[str]']) -> Dict[str, Any]:
    """Every sheet of a workbook, in the order the workbook lists them (``readWorkbook``).

    ``data`` is the ``.xlsx`` file's bytes, or a path to read them from.
    Returns ``{'sheets': [{'name': ..., 'rows': [[...], ...]}, ...]}``: each
    row a list as long as the sheet's widest, holding ``str``, ``float``,
    ``bool`` or ``None``. A sheet the workbook lists but the archive does not
    hold is left out. The JavaScript is ``async``; this is not.

    Raises :class:`XLSXError` for a file that is not a ZIP, has no
    ``xl/workbook.xml`` or no readable sheet, and :class:`XMLError` (an
    ``XLSXError`` too) for a part that is not XML.
    """
    if isinstance(data, (str, os.PathLike)):
        data = Path(data).read_bytes()
    try:
        entries = _Entries(bytes(data))
    except XLSXError:
        raise
    except Exception as e:  # noqa: BLE001 -- as the JavaScript wraps whatever unzip threw
        raise XLSXError(f'This is not a readable .xlsx file: {e}') from None
    try:
        return _read_parts(entries)
    finally:
        entries.zf.close()


def _read_parts(entries: _Entries) -> Dict[str, Any]:
    """The sheets, from an archive already opened."""

    def part(name: str) -> Optional[str]:
        raw = entries.get(name)
        return None if raw is None else _text(raw)

    book = part('xl/workbook.xml')
    if not book:
        raise XLSXError('No xl/workbook.xml — this is not an Excel workbook.')

    # The relationship table, which is what turns `rId3` into a path. Written
    # relative to `xl/`, and occasionally with a leading slash meaning the
    # archive root.
    rels: Dict[str, str] = {}
    rel_xml = part('xl/_rels/workbook.xml.rels')
    if rel_xml:
        for r in _children(_parse_xml(rel_xml), 'Relationship'):
            target = r.attrs.get('Target', '')
            rels[r.attrs.get('Id', '')] = target[1:] if target.startswith('/') else 'xl/' + (
                target[2:] if target.startswith('./') else target)
    strings = _shared_strings(part('xl/sharedStrings.xml'))

    root = _parse_xml(book)
    found = _children(root, 'sheets')
    listed = _children(found[0] if found else None, 'sheet')
    sheets: List[Dict[str, Any]] = []
    for i, s in enumerate(listed):
        # Decoded a second time, as the application does.
        name = _decode_entities(s.attrs.get('name', f'Sheet{i + 1}'))
        rid = s.attrs.get('r:id')
        if rid is None:
            rid = s.attrs.get('relationship:id')
        if rid is None:
            rid = s.attrs.get('id')
        # By relationship where there is one, by position where the file does
        # not say -- some writers number the sheet parts and nothing else.
        path = rels.get('undefined' if rid is None else rid)
        if path is None:
            path = f'xl/worksheets/sheet{i + 1}.xml'
        xml = part(path)
        if xml is None:
            continue
        sheets.append({'name': name, 'rows': _sheet_grid(xml, strings)})
    if not sheets:
        raise XLSXError('The workbook has no readable sheets.')
    return {'sheets': sheets}


# --- writing ------------------------------------------------------------------

def _is_number(value: Any) -> bool:
    """``typeof value === 'number'``: an int or a float, numpy's included, not a boolean."""
    return isinstance(value, numbers.Real) and not is_js_boolean(value)


def _cell_xml(value: Any, ref: str, style: int) -> str:
    """A cell, typed by what it holds."""
    s = f' s="{style}"' if style else ''
    if value is None or (isinstance(value, str) and value == ''):
        return ''
    if _is_number(value):
        x = js_to_number(value)
        # NaN and the infinities have no representation in a cell, and #NUM!
        # is what a spreadsheet shows for them anyway.
        if math.isnan(x) or math.isinf(x):
            return f'<c r="{ref}"{s} t="e"><v>#NUM!</v></c>'
        return f'<c r="{ref}"{s}><v>{js_string(x)}</v></c>'
    if is_js_boolean(value):
        return f'<c r="{ref}"{s} t="b"><v>{1 if value else 0}</v></c>'
    # `xml:space` because a value may begin or end with a space, and without it
    # a reader is free to trim.
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{xml_escape(value)}</t></is></c>'


def _sheet_xml(rows: Sequence[Any], header: bool = True) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        '<sheetData>',
    ]
    for i, row in enumerate(rows):
        if isinstance(row, (str, bytes)) or row is None:
            raise TypeError(f'row {i + 1} is not a list of cells')
        style = 1 if header and i == 0 else 0
        cells = ''.join(_cell_xml(v, f'{column_name(j)}{i + 1}', style) for j, v in enumerate(row))
        # An empty row still gets its element, so the row numbers a reader sees
        # match the ones this wrote.
        out.append(f'<row r="{i + 1}">{cells}</row>')
    out.append('</sheetData></worksheet>')
    return ''.join(out)


#: One bold face and nothing else, for the header row.
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
          '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
          '<borders count="1"><border/></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="2">'
          '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
          '</cellXfs></styleSheet>')


def _utf16_prefix(s: str, units: int) -> str:
    """``s.slice(0, units)``: the first ``units`` UTF-16 code units, which can
    split a character outside the Basic Multilingual Plane as JavaScript does."""
    if units <= 0:
        return ''
    if all(ord(c) < 0x10000 for c in s):
        return s[:units]
    return s.encode('utf-16-le', 'surrogatepass')[:2 * units].decode('utf-16-le', 'surrogatepass')


_SHEET_NAME_FORBIDDEN = re.compile(r'[\[\]:*?/\\]')

DateLike = Union[None, _dt.datetime, _dt.date, int, float]


def write_workbook(book: Mapping[str, Any], *, modified: DateLike = None, compress: bool = True) -> bytes:
    """A workbook of plain grids, as bytes (``writeWorkbook``).

    ``book`` is ``{'sheets': [{'name': ..., 'rows': [[...], ...], 'header': True}, ...]}``;
    a sheet whose ``rows`` is not a list is skipped. A cell holding a number
    is written as the number JavaScript would write, NaN and the infinities as
    ``#NUM!``, a boolean as one, ``None`` and ``''`` as no cell at all, and
    anything else as text. The first row is bold unless ``header`` is
    ``False``.

    Sheet names are made legal as Excel wants them -- at most 31 characters,
    none of ``[]:*?/\\``, no two alike -- rather than refused.

    ``modified`` is the time every entry is stamped with, local time as the
    application takes it: a ``datetime`` (an aware one is converted to local
    time), a ``date``, or seconds since the epoch. Left out, it is the epoch,
    so writing the same grids twice gives the same bytes. ``compress=False``
    stores every entry uncompressed (see the module's notes on byte identity).
    Raises :class:`XLSXError` when there is no sheet to write.
    """
    listed = book.get('sheets') if isinstance(book, Mapping) else None
    sheets = [s for s in (listed or []) if isinstance(s, Mapping) and isinstance(s.get('rows'), (list, tuple))]
    if not sheets:
        raise XLSXError('A workbook needs at least one sheet.')

    # Excel's own rules: at most 31 characters, none of `[]:*?/\`, and no two
    # sheets alike. A name that breaks one of them opens as a repair dialog.
    used = set()
    named: List[Dict[str, Any]] = []
    for i, s in enumerate(sheets):
        raw = s.get('name')
        name = _SHEET_NAME_FORBIDDEN.sub(' ', '' if raw is None else js_string(raw))
        name = _utf16_prefix(name.strip(JS_WHITESPACE), 31)
        if not name:
            name = f'Sheet{i + 1}'
        n = 1
        unique = name
        while unique.lower() in used:
            n += 1
            tag = f' ({n})'
            unique = _utf16_prefix(name, 31 - len(tag)) + tag
        used.add(unique.lower())
        named.append({'name': unique, 'rows': s['rows'], 'header': s.get('header') is not False})

    parts = [(f'xl/worksheets/sheet{i + 1}.xml', _utf8(_sheet_xml(s['rows'], s['header'])))
             for i, s in enumerate(named)]

    types = ''.join([
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        *[f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
          'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          for i in range(len(named))],
        '</Types>'])

    workbook = ''.join([
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ',
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>',
        *[f'<sheet name="{xml_escape(s["name"], True)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
          for i, s in enumerate(named)],
        '</sheets></workbook>'])

    book_rels = ''.join([
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
        *[f'<Relationship Id="rId{i + 1}" '
          'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
          f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(named))],
        f'<Relationship Id="rId{len(named) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>',
        '</Relationships>'])

    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" '
                 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                 'Target="xl/workbook.xml"/></Relationships>')

    # `[Content_Types].xml` first, which the specification asks for and some
    # readers insist on.
    return _zip([
        ('[Content_Types].xml', _utf8(types)),
        ('_rels/.rels', _utf8(root_rels)),
        ('xl/workbook.xml', _utf8(workbook)),
        ('xl/_rels/workbook.xml.rels', _utf8(book_rels)),
        ('xl/styles.xml', _utf8(STYLES)),
        *parts,
    ], modified=modified, compress=compress)


# --- the ZIP container (the writing half of src/io/zip.js) --------------------

def _dos_time(modified: DateLike) -> Tuple[int, int]:
    """A date and time as a ZIP entry carries them: MS-DOS, two seconds of
    resolution, no year before 1980 -- ``(date, time)``.

    Local time, as the JavaScript's ``getFullYear()`` and ``getHours()`` read a
    date, and the epoch by default: in a zone east of Greenwich that lands on
    1980-01-01 at the zone's offset in hours, in one west of it on
    1980-12-31, since only the year is held back to 1980.
    """
    if modified is None:
        d = _dt.datetime.fromtimestamp(0)
    elif isinstance(modified, _dt.datetime):
        d = modified.astimezone() if modified.tzinfo is not None else modified
    elif isinstance(modified, _dt.date):
        d = _dt.datetime(modified.year, modified.month, modified.day)
    else:
        d = _dt.datetime.fromtimestamp(float(modified))
    year = max(1980, d.year)
    date = ((year - 1980) << 9) | (d.month << 5) | max(1, d.day)
    time = (d.hour << 11) | (d.minute << 5) | (d.second >> 1)
    return date & 0xFFFF, time & 0xFFFF


def _deflate_raw(raw: bytes) -> bytes:
    """Deflate at zlib's default level, raw, as a ZIP entry holds it."""
    c = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15, 8, zlib.Z_DEFAULT_STRATEGY)
    return c.compress(raw) + c.flush()


def _zip(entries: Iterable[Tuple[str, bytes]], modified: DateLike = None, compress: bool = True,
         inflate_limit: int = MAX_INFLATED) -> bytes:
    """Entries as a ZIP archive, laid out as the application's ``zip`` lays one out.

    Local headers, deflate or stored data, a central directory and an end
    record, sizes known before anything is written so there are no data
    descriptors; the name flagged as UTF-8, version 2.0 made and needed, no
    extra fields, no comments and no ZIP64. An entry is stored when deflate
    does not make it smaller, which is always so for an empty one -- and when
    it would take the deflated total past ``inflate_limit``, the most the
    application's reader inflates of one archive, so that every archive written
    is one it opens: stored data is outside that allowance.
    """
    date, time = _dos_time(modified)
    local: List[bytes] = []
    central: List[bytes] = []
    offset = 0
    count = 0
    inflated = 0
    for name, raw in entries:
        name_bytes = _utf8(name)
        if len(raw) > 0xFFFFFFFF:
            raise XLSXError(f"'{name}' is {len(raw)} bytes, which needs ZIP64 and is more than this "
                            'writer will produce.')
        fits = inflated + len(raw) <= inflate_limit
        packed = _deflate_raw(raw) if compress and fits else None
        use_deflate = packed is not None and len(packed) < len(raw)
        if use_deflate:
            inflated += len(raw)
        data = packed if use_deflate else raw
        method = 8 if use_deflate else 0
        crc = zlib.crc32(raw) & 0xFFFFFFFF
        lfh = struct.pack('<IHHHHHIIIHH', 0x04034B50, 20, 0x0800, method, time, date, crc,
                          len(data) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF, len(name_bytes) & 0xFFFF, 0)
        cdh = struct.pack('<IHHHHHHIIIHHHHHII', 0x02014B50, 20, 20, 0x0800, method, time, date, crc,
                          len(data) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF, len(name_bytes) & 0xFFFF,
                          0, 0, 0, 0, 0, offset & 0xFFFFFFFF)
        local.extend([lfh + name_bytes, data])
        central.append(cdh + name_bytes)
        offset += len(lfh) + len(name_bytes) + len(data)
        count += 1
    cd_size = sum(len(c) for c in central)
    eocd = struct.pack('<IHHHHIIH', 0x06054B50, 0, 0, count & 0xFFFF, count & 0xFFFF,
                       cd_size & 0xFFFFFFFF, offset & 0xFFFFFFFF, 0)
    return b''.join(local + central + [eocd])
