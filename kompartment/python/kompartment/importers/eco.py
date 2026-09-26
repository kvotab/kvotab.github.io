"""Importing Ecolego projects (``.eco``) and assessments (``.eas``).

A port of the application's importer, ``src/io/eco.js``: the same file gives
the same model -- a project dictionary in Kompartment's own format -- and the
same report of what was renamed, skipped, switched off or could not come
across::

    from kompartment.importers.eco import import_eco_file

    project, report = import_eco_file('Vault_assessment.eas')
    print(report.summary())
    m = kompartment.Model(project)

A ``.eco`` file is a ZIP of the Ecolego project folder, and the model is its
``model.xml``. An ``.eas`` assessment is the same archive with a run stored in
it -- a ``simulation/`` folder of results -- and is read exactly as a project
is: the model comes across, the results do not. The older Ecolego 4/5 format, a
bare XML file (usually UTF-16), is accepted too when it holds a ``<data-model>``
and refused with an explanation when it is a ``<sheet>``.

The mapping is deliberately lossy and says so. Ecolego has around thirty block
types and a great deal of presentation state; what has no equivalent here is
skipped and listed in the report, so the result is usable or explicitly
incomplete -- never silently wrong. Where a file and Ecolego's documentation
disagree, the file wins: block type names and their defaults are read off real
project files.

See the application's INTERNALS.md, *Importing .eco projects*, for what the
real files turned out to contain, and GUIDE.md, *Importing Ecolego projects*,
for Ecolego's names and defaults beside this tool's.
"""

from __future__ import annotations

import io
import math
import os
import re
import zipfile
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, Union

from ..blocks import SINGULAR
from ..decay import STABLE
from ..errors import KompartmentError
from ..keys import COLLECTIONS
from ..names import RESERVED, resolve_reference
from ..simulation import DEFAULT_SOLVER
from ..simulation import DEFAULTS as DEFAULT_SIMULATION
from ._eco_maps import (
    EQUATION_FIELDS, EVENT_FIELDS, JS_DOT, JS_SPACE_CLASS, KIND_FROM_ECO, KIND_LABEL, SECONDS_PER_YEAR,
    collation_key, direction_from_eco, extreme_from_eco, interpolation_from_eco, is_finite, iso_date,
    js_floor, js_identifier, js_len, js_object_order, js_round, js_string, js_trim, json_ready,
    operation_from_eco, round_significant, solver_name, to_exponential, to_number,
)
from ._xml import Node, XMLError, child, child_bool, child_number, child_text, children, find, parse_xml

__all__ = ['EcoImportError', 'ImportReport', 'ImportResult', 'import_eco_file', 'import_model_xml',
           'decode_xml_bytes']

#: The collections a project's blocks live in, in the order the panels list
#: them. ``KINDS`` in ``src/domain/blocks.js``.
KINDS = COLLECTIONS

_S = JS_SPACE_CLASS


class EcoImportError(KompartmentError, ValueError):
    """A file the importer cannot read: not an Ecolego model, an Ecolego 4/5
    ``<sheet>``, an archive with no model in it, XML that does not parse, or a
    name no model can hold. ``ImportError`` in ``src/io/eco.js``; renamed here
    so as not to hide Python's own ``ImportError``."""


class ImportResult(NamedTuple):
    """What an import gives: the project and the report on it."""

    project: Dict[str, Any]
    report: 'ImportReport'


# --- what the file's block types become ------------------------------------------------

#: Block types that become blocks in this tool.
SUPPORTED = frozenset([
    'compartment', 'expression', 'parameter',
    # The file format treats these as expressions with an evaluation mode.
    'post-processing', 'constant',
    # Time-dependent data.
    'lookup-table',
    # Reductions: over one of a block's index lists, and over several blocks.
    'index-operation', 'aggregate',
    # The blocks that depend on what has already happened, and the events
    # that drive them.
    'min-max', 'running-mean', 'snapshot', 'delay', 'discrete-event',
    # Connections.
    'transfer', 'transfer-coefficient',
    # The parts of a transport sub-system.
    'transport-begin', 'transport-end', 'transport-number',
    'transport-element-counter', 'transport-operation',
])

#: The part each transport block type plays.
TRANSPORT_ROLE = {
    'transport-begin': 'begin',
    'transport-end': 'end',
    'transport-number': 'number',
    'transport-element-counter': 'counter',
    'transport-operation': 'operation',
}

#: Ecolego's model boundary. Transfers attach to these; this tool writes the
#: boundary as a transfer's open end instead, so they are folded into the
#: transfers that touch them rather than lost.
BOUNDARY = frozenset(['source', 'sink'])

#: Connections that carry no mass and so do not change the numbers. An
#: influence declares an evaluation order, which this tool derives from the
#: equations themselves.
NON_NUMERIC = frozenset(['influence'])

#: Ecolego's sub-system interface: a way to route a value across a sub-system
#: boundary, and nothing else. Read for its wiring, which is then written
#: straight into the blocks at each end (see :func:`_connect_interfaces`), and
#: dropped.
INTERFACE = frozenset(['model-input', 'model-output', 'connector'])

#: How several outputs into one input are combined; this tool's functions are
#: spelled the same way.
INTERFACE_OPERATION = {'ADD': 'sum', 'MAX': 'max', 'MIN': 'min', 'MEAN': 'mean', 'PRODUCT': 'prod'}

#: multiply-with-donor defaults: a plain ``transfer`` is an absolute flux, the
#: legacy ``transfer-coefficient`` a rate multiplied by its donor. An explicit
#: ``<multiply-with-donor>`` in an entry overrides both.
DONOR_DEFAULT = {'transfer': False, 'transfer-coefficient': True}

_SHEET = re.compile('<sheet[' + _S + '>]')
_DATA_MODEL = re.compile('<data-model[' + _S + '>]')
_VERSION = re.compile('(^|[' + _S + '])version[' + _S + ']*=[' + _S + ']*([A-Za-z0-9_.-]+)')
_PATH_SEPARATOR = re.compile(r'[/\\]')


def _last_part(name: str) -> str:
    return _PATH_SEPARATOR.split(name)[-1]


# --- the entry points -------------------------------------------------------------------

def import_eco_file(data: Union[bytes, bytearray, memoryview, str, 'os.PathLike[str]'], *,
                    file_name: Optional[str] = None, version: Optional[str] = None) -> ImportResult:
    """Reads an Ecolego project (``.eco``), assessment (``.eas``) or bare
    ``model.xml``. ``importEcoFile`` in ``src/io/eco.js``.

    ``data`` is the file's bytes, or a path to read them from. ``file_name`` is
    what the bytes do not know -- which file this is -- and goes into the
    model's name and description; a path supplies its own. ``version`` is the
    Ecolego version, for a bare XML file; an archive says which Ecolego wrote
    it in its ``.version`` file, and that is used instead.

    Returns ``(project, report)``. Raises :class:`EcoImportError` for a file
    it cannot read.
    """
    if isinstance(data, (str, os.PathLike)):
        path = Path(data)
        if file_name is None:
            file_name = path.name
        data = path.read_bytes()
    raw = bytes(data)

    # Ecolego 4/5 wrote the model as a bare XML file, usually UTF-16 with a
    # BOM; Ecolego 6 zips the project folder. Both carry the .eco extension.
    if not _looks_like_zip(raw):
        text = decode_xml_bytes(raw)
        if _SHEET.search(text):
            raise EcoImportError(
                'This is an Ecolego 4/5 model: a <sheet> document with a different data '
                'model from Ecolego 6 (compartments live in spreadsheet cells rather '
                'than a block model). This importer reads the Ecolego 6 format. Open '
                'the file in Ecolego and save it again to convert it.')
        if not _DATA_MODEL.search(text):
            raise EcoImportError(
                'This file is neither a ZIP archive nor an Ecolego model XML. '
                'If it is a project folder, zip it or open its model.xml directly.')
        return import_model_xml(text, file_name=file_name, version=version)

    entries = _unzip(raw)

    # model.xml sits at the archive root in practice, but it is looked for by
    # name anywhere -- and these archives are written on Windows, so a name may
    # use backslashes. By name first, and the bytes only of the one wanted: an
    # assessment's results are never decompressed.
    model_xml = None
    for name in entries.names():
        if _last_part(name) == 'model.xml':
            model_xml = decode_xml_bytes(entries.get(name))
            break
    if model_xml is None:
        for name in entries.names():
            if not name.lower().endswith('.xml'):
                continue
            text = decode_xml_bytes(entries.get(name))
            if _DATA_MODEL.search(text):
                model_xml = text
                break
    if model_xml is None:
        held = ', '.join(entries.names()) or 'nothing'
        raise EcoImportError(
            f'No model.xml in the archive (it holds: {held}). '
            'This may be a library or workspace archive rather than a project.')

    return import_model_xml(model_xml, file_name=file_name, version=_ecolego_version(entries))


def _ecolego_version(entries: '_Archive') -> Optional[str]:
    """Which Ecolego wrote the archive: ``.version`` at its root is a
    properties file, ``version=6.5 track-changes=false ...``."""
    for name in entries.names():
        if _last_part(name) != '.version':
            continue
        try:
            found = _VERSION.search(decode_xml_bytes(entries.get(name)))
        except EcoImportError:
            return None
        return found.group(2) if found else None
    return None


def _looks_like_zip(data: bytes) -> bool:
    return len(data) >= 4 and data[0] == 0x50 and data[1] == 0x4B and data[2] in (0x03, 0x05, 0x07)


def decode_xml_bytes(data: Union[bytes, bytearray, memoryview]) -> str:
    """XML bytes as text, honouring a byte-order mark: UTF-16 big-endian (as
    Ecolego 5 wrote it) or little-endian, or UTF-8 with or without one.
    ``decodeXmlBytes`` in ``src/io/eco.js``.

    Undecodable bytes become U+FFFD, and one further byte-order mark after the
    first is dropped too, as the browser's ``TextDecoder`` does both.
    """
    b = bytes(data)
    if len(b) >= 2:
        if b[0] == 0xFE and b[1] == 0xFF:
            return _without_bom(b[2:].decode('utf-16-be', 'replace'))
        if b[0] == 0xFF and b[1] == 0xFE:
            return _without_bom(b[2:].decode('utf-16-le', 'replace'))
    if len(b) >= 3 and b[0] == 0xEF and b[1] == 0xBB and b[2] == 0xBF:
        return _without_bom(b[3:].decode('utf-8', 'replace'))
    return _without_bom(b.decode('utf-8', 'replace'))


def _without_bom(text: str) -> str:
    return text[1:] if text.startswith('\ufeff') else text


def import_model_xml(text: str, *, file_name: Optional[str] = None,
                     version: Optional[str] = None) -> ImportResult:
    """Reads a bare ``model.xml``. ``importModelXML`` in ``src/io/eco.js``.

    ``file_name`` and ``version`` are what the file around the XML knows and
    the XML does not: which file this is and which Ecolego wrote it. Both go
    into the description, and the file's name is the model's when the XML
    calls it by Ecolego's default, ``model``.

    Returns ``(project, report)``. Raises :class:`EcoImportError` for XML that
    does not parse, a document with no ``<data-model>``, or a nuclide, material
    or index called ``__proto__``, ``constructor`` or ``prototype``.
    """
    meta = {'fileName': file_name, 'version': version}
    try:
        root = parse_xml(text)
    except XMLError as e:
        raise EcoImportError(f'model.xml is not valid XML: {e}') from e

    data_model = root if root.name == 'data-model' else find(root, 'data-model')
    if data_model is None:
        raise EcoImportError('The XML has no <data-model> element')

    report = ImportReport()
    names = _NameMapper(report)

    project: Dict[str, Any] = {
        'name': 'Imported project',
        'description': '',
        'simulation': {},
        'index_lists': [],
        'parameters': [],
        'compartments': [],
        'expressions': [],
        'transfers': [],
        'inflows': [],
        'lookups': [],
        'index_reductions': [],
        'block_reductions': [],
        'min_maxes': [],
        'running_means': [],
        'snapshots': [],
        'delays': [],
        'triggers': [],
        'functions': [],
    }

    provenance = _read_project_properties(data_model, project, meta)
    _read_functions(data_model, project, names, report)
    materials = _read_materials(data_model, project, report)
    index_ids = _read_index_lists(data_model, project, names, report, materials)
    _read_decay_chains(data_model, project, report)
    hierarchy = _read_hierarchy(data_model, project, names, report)
    block_name_by_id, wiring = _read_blocks(data_model, project, names, index_ids, report, hierarchy)
    _read_simulation_settings(data_model, project, report)

    # Two rewrites, both textual and both necessary: Ecolego names may hold
    # spaces and punctuation this tool's identifiers cannot, so those blocks
    # were renamed above; and equations may use sub-system-qualified
    # references, which are the block ids.
    _rewrite_renamed_references(project, names, report, block_name_by_id)
    _drop_unreachable_targets(project, report)

    # What Ecolego's sub-system inputs and outputs connected, connected
    # directly. Last, so the references it writes are the names the model
    # ended up with.
    _connect_interfaces(project, wiring, block_name_by_id, report)
    _rewrite_endpoint_ids(project, block_name_by_id, report)

    duplicated = names.duplicated()
    if duplicated:
        more = '…' if len(duplicated) > 6 else ''
        report.warn(
            f'{len(duplicated)} name(s) had to be spelled differently in different '
            f"sub-systems ({', '.join(duplicated[:6])}{more}), because the original is not a valid "
            'identifier and the tidied form was already taken. A bare reference to one '
            'of those was left as written -- check those equations.')

    report.finish(project)
    # Last, so the counts are of the model as it ended up rather than as the
    # file spelled it.
    described = dict(provenance)
    described.update(meta)
    project['description'] = _describe_model(project, described)
    # Who wrote it, as the file says -- beside the name and the description,
    # where a model of this tool's own keeps it.
    if provenance.get('author'):
        head = {'name': project['name'], 'description': project['description'], 'author': provenance['author']}
        head.update((k, v) for k, v in project.items() if k not in head)
        project = head
    json_ready(project)
    return ImportResult(project, report)


# --- sub-system interfaces ------------------------------------------------------------

def _connect_interfaces(project: Dict[str, Any], wiring: Dict[str, Any],
                        block_name_by_id: Dict[str, str], report: 'ImportReport') -> None:
    """Wires up what a sub-system interface connected, and drops the interface.

    A model input replaces the fed block's whole calculation with a reference
    to the block feeding it; several feeding one are combined with the
    operation the input names (``sum`` when it names none). A fed parameter
    becomes an expression, since what feeds it is not a number, and the fed
    block's per-index values go, since the connection replaces the calculation
    at every index. An input connected to nothing is left exactly as it is.
    ``connectInterfaces`` in ``src/io/eco.js``.
    """
    links = wiring['links']
    operations = wiring['operations']
    id_by_guid = wiring['id_by_guid']
    exposed = wiring['exposed']
    if not links:
        if exposed:
            one = len(exposed) == 1
            report.warn(
                f"{len(exposed)} sub-system input/output{' was' if one else 's were'} declared "
                'but connected to nothing, so nothing was routed: the '
                f"{'block behind it keeps the value' if one else 'blocks behind them keep the values'} "
                f"the file gives {'it' if one else 'them'}.")
        return

    by_name: Dict[str, Dict[str, Any]] = {}
    holders = [
        ('parameters', 'parameter'), ('compartments', 'compartment'),
        ('expressions', 'expression'), ('transfers', 'transfer'),
        ('inflows', 'inflow'), ('lookups', 'lookup'),
        ('index_reductions', 'index_reduction'), ('block_reductions', 'block_reduction'),
        ('min_maxes', 'min_max'), ('running_means', 'running_mean'),
        ('snapshots', 'snapshot'), ('delays', 'delay'),
        ('triggers', 'trigger'),
    ]
    for collection, kind in holders:
        for block in project.get(collection) or []:
            qname = _qualified(block)
            by_name[qname] = {'collection': collection, 'kind': kind, 'block': block, 'qname': qname}

    def found(guid: str) -> Optional[Dict[str, Any]]:
        bid = id_by_guid.get(guid)
        qname = None if bid is None else block_name_by_id.get(bid)
        return None if qname is None else by_name.get(qname)

    by_target: Dict[str, List[Dict[str, str]]] = {}
    for link in links:
        by_target.setdefault(link['target'], []).append(link)

    joined = 0
    lost: List[str] = []
    converted: List[str] = []
    for target_guid, incoming in by_target.items():
        target = found(target_guid)
        if not target:
            lost.append(incoming[0]['via'])
            continue
        sources = [s for s in (found(l['source']) for l in incoming) if s]
        if len(sources) != len(incoming):
            lost.append(incoming[0]['via'])
        if not sources:
            continue

        refs = [s['qname'] for s in sources]
        op = operations.get(target_guid)
        fn = INTERFACE_OPERATION.get('ADD' if op is None else op) or 'sum'
        equation = refs[0] if len(refs) == 1 else f"{fn}({', '.join(refs)})"

        rewritten = _wire_into(project, target, equation)
        if not rewritten:
            report.warn(
                f"'{target['qname']}' is fed by a sub-system interface, and a "
                f"{js_string(target['kind']).replace('_', ' ')} cannot be: its value was "
                'left as the file gives it.')
            continue
        if rewritten == 'converted':
            converted.append(target['qname'])
        joined += 1

    if joined:
        tail = ''
        if converted:
            others = ' and others' if len(converted) > 4 else ''
            tail = (f" {', '.join(converted[:4])}{others} "
                    f"{'was a parameter and is' if len(converted) == 1 else 'were parameters and are'} "
                    f"now expressions, since what feeds {'it' if len(converted) == 1 else 'them'} "
                    'is not a number.')
        report.warn(
            f"{joined} sub-system input{'' if joined == 1 else 's'} {'was' if joined == 1 else 'were'} "
            f"connected straight to what feeds {'it' if joined == 1 else 'them'}. Ecolego routes "
            'those through model input and output blocks, which are a way to wire a '
            'ready-made sub-system into a project; this tool has no such library, so the '
            'two ends are joined directly and the interface blocks are left out.' + tail)
    if lost:
        shown = ', '.join(list(dict.fromkeys(lost))[:4])
        report.warn(
            f"{len(lost)} sub-system connection{'' if len(lost) == 1 else 's'} "
            f'({shown}) named a block this tool did '
            f"not import, so {'it' if len(lost) == 1 else 'they'} could not be joined up.")


def _wire_into(project: Dict[str, Any], target: Dict[str, Any], equation: str) -> Optional[str]:
    """Puts one equation where a block's own value was: ``'rewritten'``,
    ``'converted'`` for a parameter that became an expression, or ``None`` for
    a kind that cannot be fed at all."""
    block = target['block']
    kind = target['kind']

    def clear(key: str) -> None:
        kept = []
        for e in block.get('entries') or []:
            rest = {k: v for k, v in e.items() if k != key}
            if any(k != 'index' for k in rest):
                kept.append(rest)
        block['entries'] = kept
        if not kept:
            del block['entries']

    if kind == 'expression':
        block['equation'] = equation
        clear('equation')
        return 'rewritten'
    if kind == 'transfer':
        block['rate'] = equation
        clear('rate')
        return 'rewritten'
    if kind == 'parameter':
        params = project['parameters']
        at = next((k for k, b in enumerate(params) if b is block), -1)
        if at >= 0:
            del params[at]
        block.pop('value', None)
        clear('value')
        block.pop('entries', None)
        block['equation'] = equation
        project.setdefault('expressions', []).append(block)
        return 'converted'
    return None


# --- the textual rewrite ----------------------------------------------------------------

#: One character a name has to contain before a match can be a reference.
IDENT_CHAR = re.compile('[A-Za-z0-9_]')
#: The characters that make a name readable as an expression in its own right.
OPERATOR_CHAR = re.compile(r'[+\-*/^()\[\],]')
_NAME_PART = re.compile('[A-Za-z0-9_.]')


def _rewrite_renamed_references(project: Dict[str, Any], names: '_NameMapper', report: 'ImportReport',
                                block_name_by_id: Optional[Dict[str, str]] = None) -> None:
    """Substitutes renamed blocks throughout every equation.

    Textual rather than token-based, because the original names are exactly
    the ones the tokenizer cannot handle -- ``Deep soil`` is three tokens.
    Qualified ids first and longest names first, so ``Soil`` never eats part of
    ``Deep soil``, and a match only counts when it is not butted up against
    another name character (``.`` included, so the bare ``thickness`` never
    eats the tail of ``Overpack.thickness``). A bare name that mapped two ways
    in different sub-systems is left alone. ``rewriteRenamedReferences`` in
    ``src/io/eco.js``.
    """
    block_name_by_id = block_name_by_id or {}
    qualified = [(bid, to) for bid, to in block_name_by_id.items() if bid != to]
    ambiguous = set(names.duplicated())
    bare = [(frm, to) for frm, to in names.by_original.items() if frm != to and frm not in ambiguous]

    seen: Set[Tuple[str, str]] = set()
    pairs: List[Tuple[str, str]] = []
    for frm, to in qualified + bare:
        # An empty `from` is found at every position, and one with no name
        # character in it is not a name anything could have referred to.
        if frm == '' or frm == to or not IDENT_CHAR.search(frm):
            continue
        if (frm, to) in seen:
            continue
        seen.add((frm, to))
        pairs.append((frm, to))
    pairs.sort(key=lambda p: -js_len(p[0]))
    if not pairs:
        return

    touched = 0
    fired: Dict[str, str] = {}
    candidates = _Candidates(pairs)

    def boundary(c: Optional[str]) -> bool:
        return c is None or not _NAME_PART.fullmatch(c)

    def rewrite(text: Any) -> Any:
        nonlocal touched
        if isinstance(text, list):
            return [rewrite(t) for t in text]
        if not isinstance(text, str) or text == '':
            return text
        out = text
        # Every pair in order, as the application goes through them -- less
        # the ones that cannot match anywhere in this text, which it would
        # search for and not find.
        for j in candidates.of(text):
            frm, to = pairs[j]
            at = 0
            while True:
                i = out.find(frm, at)
                if i == -1:
                    break
                end = i + len(frm)
                before = out[i - 1] if i > 0 else None
                after = out[end] if end < len(out) else None
                if boundary(before) and boundary(after):
                    out = out[:i] + to + out[end:]
                    at = i + len(to)
                    fired[frm] = to
                else:
                    at = end
        if out != text:
            touched += 1
        return out

    collections = [
        ('compartments', ['initial']),
        ('transfers', ['rate']),
        ('inflows', ['rate']),
        ('expressions', ['equation']),
        # A function's body is an equation, and a call of one is a reference.
        ('functions', ['equation']),
        # A reducing block names its targets rather than writing an equation,
        # but they are references like any other.
        ('index_reductions', ['target']),
        ('block_reductions', ['targets']),
        # A block that remembers names its target, and its event fields name
        # a discrete event.
        ('min_maxes', ['target', 'reset_trigger', 'start_trigger', 'stop_trigger']),
        ('running_means', ['target', 'reset_trigger', 'start_trigger', 'stop_trigger']),
        ('snapshots', ['target', 'trigger', 'initial']),
        ('delays', ['target', 'delay']),
        ('triggers', ['first', 'second']),
    ]
    for collection, keys in collections:
        for block in project.get(collection) or []:
            for k in keys:
                # The application writes `undefined` back where the key was
                # absent, which JSON leaves out; here it is simply not written.
                if k in block:
                    block[k] = rewrite(block[k])
            for entry in block.get('entries') or []:
                for k in keys:
                    if k in entry:
                        entry[k] = rewrite(entry[k])

    if touched:
        report.warn(
            f"Rewrote {touched} equation(s) to use this tool's block names, including "
            'sub-system-qualified references. The substitution is textual, because the '
            'original names are not valid identifiers -- check the results.')
        # A name with an operator in it is also an expression: `A-B` turned
        # every `A - B` in the model into a reference to `A_B`.
        risky = [(frm, to) for frm, to in fired.items() if OPERATOR_CHAR.search(frm)]
        if risky:
            shown = ', '.join(f"'{frm}' → '{to}'" for frm, to in risky[:6])
            report.warn(
                f"{len(risky)} of those names contain{'s' if len(risky) == 1 else ''} "
                'operator or bracket characters '
                f"({shown}{', …' if len(risky) > 6 else ''}). Every occurrence of the text "
                'in an equation was read as the block -- including where it was written '
                'as arithmetic between two other blocks. Check those equations by hand.')


_RUN = re.compile('[A-Za-z0-9_]+')
_NAME_RUN = re.compile('[A-Za-z0-9_.]+')


class _Candidates:
    """Which of the rewrite's pairs can change a given text, found without
    searching the text for every one of them.

    The application searches every text for every pair, which is quick enough
    in JavaScript and not in Python: 12,000 equations and as many renamed
    blocks are 144 million searches. The answer is the same when the pairs that
    cannot match are left out, and two facts say which those are.

    A match only counts with something other than ``[A-Za-z0-9_.]`` (or the
    end of the text) on either side of it, so every run of ``[A-Za-z0-9_]`` in
    the name is a whole run of the text where it matches: ``Deep soil`` can
    only match a text whose runs include ``Deep`` and ``soil``.

    A substitution can also make a match that was not there: ``k-1`` becomes
    ``k_1``, and the pair ``k_1`` -> ``k_1_1`` after it then matches that. What
    was put in is itself a whole run of ``[A-Za-z0-9_.]`` with a boundary on
    either side, so a later pair can only match across it if its own name has
    it as one of its runs; the few pairs where that can happen are always
    searched for.
    """

    def __init__(self, pairs: List[Tuple[str, str]]) -> None:
        self.runs = [frozenset(_RUN.findall(frm)) for frm, _ in pairs]
        self.index: Dict[str, List[int]] = {}
        for j, runs in enumerate(self.runs):
            key = min(runs, key=lambda r: (-len(r), r))  # the longest is the rarest
            self.index.setdefault(key, []).append(j)
        self.always: Set[int] = set()
        put_in: Set[str] = set()
        for j, (frm, to) in enumerate(pairs):
            if put_in.intersection(_NAME_RUN.findall(frm)):
                self.always.add(j)
            put_in.add(to)

    def of(self, text: str) -> List[int]:
        """The pairs to try on ``text``, in their order."""
        runs = set(_RUN.findall(text))
        found = set(self.always)
        for run in runs:
            for j in self.index.get(run, ()):
                if self.runs[j] <= runs:
                    found.add(j)
        return sorted(found)


def _drop_unreachable_targets(project: Dict[str, Any], report: 'ImportReport') -> None:
    """Drops a reduction whose target was never imported, and lists it in the
    report; an aggregate that lost only some of its targets keeps the rest,
    with a warning. ``dropUnreachableTargets`` in ``src/io/eco.js``."""
    known: Set[str] = set()
    for kind in ('parameters', 'compartments', 'expressions', 'transfers',
                 'inflows', 'lookups', 'index_reductions', 'block_reductions', 'functions',
                 'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers'):
        for b in project.get(kind) or []:
            known.add(_qualified(b))

    def resolve(ref: str, system: Optional[str]) -> Optional[str]:
        return resolve_reference(ref, system or '', known.__contains__)

    kept_reductions = []
    for o in project.get('index_reductions') or []:
        if o.get('target') and resolve(o['target'], o.get('system')):
            kept_reductions.append(o)
            continue
        target = o.get('target')
        report.skip('index-operation', o.get('name'),
                    f"it reduces '{'(nothing)' if target is None else js_string(target)}', "
                    'which is not in this model')
        known.discard(_qualified(o))
    project['index_reductions'] = kept_reductions

    kept_aggregates = []
    for g in project.get('block_reductions') or []:
        targets = g.get('targets') or []
        kept = [t for t in targets if resolve(t, g.get('system'))]
        if len(kept) == len(targets):
            kept_aggregates.append(g)
            continue
        lost = [t for t in targets if not resolve(t, g.get('system'))]
        if not kept:
            report.skip('aggregate', g.get('name'),
                        f"none of the blocks it reduces ({', '.join(lost)}) is in this model")
            known.discard(_qualified(g))
            continue
        g['targets'] = kept
        more = '…' if len(lost) > 4 else ''
        report.warn(
            f"'{g.get('name')}' reduces {len(lost)} block(s) this tool did not import "
            f"({', '.join(lost[:4])}{more}); "
            'they were left out of the total.')
        kept_aggregates.append(g)
    project['block_reductions'] = kept_aggregates


def _qualified(block: Dict[str, Any]) -> str:
    # `block.system ? `${block.system}.${block.name}` : block.name`
    system = block.get('system')
    return f"{system}.{block.get('name')}" if system else block.get('name')


# --- the report -------------------------------------------------------------------------

class ImportReport:
    """What an import did: what came across, what was renamed, and above all
    what could not come across. ``ImportReport`` in ``src/io/eco.js``.

    ``skipped``   ``{'type', 'name', 'why'}`` per block that has no equivalent here
    ``notes``     ``{'type', 'name'}`` per block present but numerically inert
    ``renamed``   ``{'from', 'to'}`` per name tidied into an identifier
    ``disabled``  qualified names of blocks imported switched off, as in Ecolego
    ``disabled_systems``  sub-system path -> blocks inside it, for each
                  sub-system the file switches off as a whole (``None`` when none)
    ``warnings``  what else is worth reading, each said once
    ``counts``    how many of each kind came across (see :meth:`finish`)
    """

    def __init__(self) -> None:
        self.skipped: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []
        self.renamed: List[Dict[str, Any]] = []
        self.disabled: List[str] = []
        self.disabled_systems: Optional[Dict[str, int]] = None
        self.warnings: List[str] = []
        self.counts: Dict[str, int] = {}

    def skip(self, type_: Any, name: Any, why: str) -> None:
        """A block this tool has no equivalent for, left out."""
        self.skipped.append({'type': type_, 'name': name, 'why': why})

    def disable(self, name: str) -> None:
        """A block imported whole and left out of the run, as the file says."""
        self.disabled.append(name)

    def in_disabled_system(self, path: str) -> None:
        """A block inside a sub-system the file switches off as a whole."""
        if self.disabled_systems is None:
            self.disabled_systems = {}
        self.disabled_systems[path] = self.disabled_systems.get(path, 0) + 1

    def note(self, type_: Any, name: Any) -> None:
        """Recorded but harmless: carries no mass, so the numbers are unaffected."""
        self.notes.append({'type': type_, 'name': name})

    def warn(self, message: str) -> None:
        """A warning, said once however often it is raised."""
        if message not in self.warnings:
            self.warnings.append(message)

    def rename(self, frm: str, to: str) -> None:
        """A name tidied into an identifier."""
        self.renamed.append({'from': frm, 'to': to})

    def finish(self, project: Dict[str, Any]) -> None:
        """Counts what came across, from the finished project."""
        self.counts = {
            'index_lists': len(project['index_lists']),
            'compartments': len(project['compartments']),
            'transfers': len(project['transfers']),
            'parameters': len(project['parameters']),
            'expressions': len(project['expressions']),
            'inflows': len(project['inflows']),
            'lookups': len(project.get('lookups') or []),
            'index_reductions': len(project.get('index_reductions') or []),
            'block_reductions': len(project.get('block_reductions') or []),
            'min_maxes': len(project.get('min_maxes') or []),
            'running_means': len(project.get('running_means') or []),
            'snapshots': len(project.get('snapshots') or []),
            'delays': len(project.get('delays') or []),
            'triggers': len(project.get('triggers') or []),
            'nuclides': len(project.get('nuclides') or []),
        }

    @property
    def ok(self) -> bool:
        """Whether every block came across."""
        return not self.skipped

    def summary(self) -> str:
        """A short account in words, one line per kind of thing to say."""
        c = self.counts
        lines = [
            f"Imported {c['compartments']} compartment(s), {c['transfers']} transfer(s), "
            f"{c['parameters']} parameter(s), {c['expressions']} expression(s), "
            + (f"{c['lookups']} lookup table(s), " if c['lookups'] else '')
            + (f"{c['index_reductions']} index operation(s), " if c['index_reductions'] else '')
            + (f"{c['block_reductions']} aggregate(s), " if c['block_reductions'] else '')
            + f"{c['index_lists']} index list(s), {c['nuclides']} nuclide(s).",
        ]
        if self.skipped:
            by_type: Dict[Any, int] = {}
            for s in self.skipped:
                by_type[s['type']] = by_type.get(s['type'], 0) + 1
            lines.append(
                f'Skipped {len(self.skipped)} block(s) this tool cannot represent: '
                + ', '.join(f'{n} {js_string(t)}' for t, n in by_type.items()) + '.')
        if self.notes:
            by_type = {}
            for s in self.notes:
                by_type[s['type']] = by_type.get(s['type'], 0) + 1
            lines.append(
                f"Ignored {', '.join(f'{n} {js_string(t)}' for t, n in by_type.items())}: these carry "
                'no mass, so the results are unaffected.')
        if self.renamed:
            lines.append(f'Renamed {len(self.renamed)} block(s) to valid identifiers.')
        if self.disabled:
            lines.append(f'{len(self.disabled)} block(s) are disabled, as they were in '
                         'Ecolego, and take no part in the run.')
        if self.disabled_systems:
            lines.append(' '.join(
                f"Sub-system '{p}' is switched off as a whole, as it was in Ecolego, "
                f"with {n} block{'' if n == 1 else 's'} in it; "
                'they keep their own switches and come back with it.'
                for p, n in self.disabled_systems.items()))
        lines.extend(self.warnings)
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """The report as plain data: every list above, ``ok`` and the
        ``summary``."""
        return {
            'skipped': [dict(s) for s in self.skipped],
            'notes': [dict(s) for s in self.notes],
            'renamed': [dict(s) for s in self.renamed],
            'disabled': list(self.disabled),
            'disabled_systems': None if self.disabled_systems is None else dict(self.disabled_systems),
            'warnings': list(self.warnings),
            'counts': dict(self.counts),
            'ok': self.ok,
            'summary': self.summary(),
        }

    def __repr__(self) -> str:
        return (f'<ImportReport {len(self.skipped)} skipped, {len(self.renamed)} renamed, '
                f'{len(self.warnings)} warnings>')


# --- names ------------------------------------------------------------------------------

class _NameMapper:
    """Maps Ecolego's names onto identifiers, and remembers the mapping so the
    equations can follow it. ``NameMapper`` in ``src/io/eco.js``.

    Unique per sub-system, as Ecolego's own names are: two ``Water`` in two
    sub-systems both keep the name, and only a clash inside one is numbered.
    Keyed by block id rather than by name, so the same name in two places maps
    independently.
    """

    def __init__(self, report: ImportReport) -> None:
        self.report = report
        self.by_key: Dict[str, str] = {}
        self.by_original: Dict[str, str] = {}
        self.used: Dict[str, Set[str]] = {}
        self.ambiguous: Dict[str, None] = {}

    def map(self, original: Optional[str], key: Optional[str] = None, system: str = '',
            fallback: Optional[str] = 'block') -> str:
        """One name as an identifier this tool can parse.

        ``key`` identifies the thing named (its id; the name itself when
        ``None``); ``fallback`` is what to call it when the name is missing or
        blank -- its id, usually. A reserved word is taken before the file
        says anything, so ``min`` is numbered like a clash: ``min_1``.
        """
        if key is None:
            key = original
        if key in self.by_key:
            return self.by_key[key]

        given = js_trim('' if original is None else str(original))
        absent = given == ''
        clean = js_identifier(('' if fallback is None else str(fallback)) if absent else given)
        if clean[:1].isascii() and clean[:1].isdigit():
            clean = '_' + clean
        if clean == '':
            clean = 'block'

        taken = self.used.setdefault(system, set())
        candidate = clean
        n = 1
        while candidate in taken or candidate in RESERVED:
            candidate = f'{clean}_{n}'
            n += 1

        # A bare reference is rewritten by name, so a name that maps two ways
        # cannot be rewritten safely. A block with no name has nothing an
        # equation could have referred to it by.
        if not absent:
            seen = self.by_original.get(given)
            if seen is None:
                self.by_original[given] = candidate
            elif seen != candidate:
                self.ambiguous[given] = None

        taken.add(candidate)
        self.by_key[key] = candidate
        if candidate != given:
            self.report.rename('(unnamed)' if absent else given, candidate)
        return candidate

    def duplicated(self) -> List[str]:
        """Original names that mapped to more than one identifier."""
        return list(self.ambiguous)


# The three words that pass every other test without being names: in the
# application each is a key into every object's prototype.
_PROTOTYPE_KEYS = frozenset(['__proto__', 'constructor', 'prototype'])
_VOWEL = re.compile('[aeiou]', re.I | re.A)


def _key_name(raw: Optional[str], what: str, report: ImportReport) -> Optional[str]:
    """A nuclide's, material's, index's or decay pair's name, as the file gives
    it, trimmed; ``None`` (and a warning) for a blank one. A prototype key is
    refused outright with :class:`EcoImportError`."""
    name = js_trim('' if raw is None else str(raw))
    an = 'An' if _VOWEL.match(what) else 'A'
    if name == '':
        report.warn(f'{an} {what} with no name was left out.')
        return None
    if name in _PROTOTYPE_KEYS:
        raise EcoImportError(
            f"{an} {what} in this file is called '{name}', which is not a name but a key "
            'into every object\'s prototype; this tool keys its tables by these names '
            f'and cannot hold one. Ecolego never writes it -- rename the {what} in '
            'Ecolego, or check that the file has not been tampered with.')
    return name


# --- sections ---------------------------------------------------------------------------

def _read_hierarchy(data_model: Node, project: Dict[str, Any], names: _NameMapper,
                    report: ImportReport) -> Dict[str, Any]:
    """``<hierarchy-model>``: every sub-system, parents before children.

    A sub-system is a namespace and gives its blocks a path; a *group* is only
    a visual grouping and is flattened away; a *transport* is marked; one the
    file switches off is carried as switched off. ``readHierarchy`` in
    ``src/io/eco.js``.
    """
    model = child(data_model, 'hierarchy-model')
    path_by_id: Dict[str, str] = {}
    systems: List[str] = []
    disabled_paths: List[str] = []
    transports: List[str] = []
    out = {'path_by_id': path_by_id, 'systems': systems, 'disabled_paths': disabled_paths,
           'transports': transports}
    if model is None:
        return out

    groups = 0
    for el in children(model, 'sub-system-block'):
        sid = child_text(el, 'id')
        original = el.attrs.get('name')
        # The root carries neither, and is not a level of anything.
        if not sid or not original:
            continue

        parent_id = child_text(el, 'sub-system')
        parent_path = path_by_id.get(parent_id, '') if parent_id else ''
        kind = el.attrs.get('type', '')

        if kind == 'group':
            groups += 1
            path_by_id[sid] = parent_path
            continue
        if kind == 'external':
            report.warn(
                f"Sub-system '{original}' is an external sub-system; this tool reads it "
                'as an ordinary one, so its linked library is not applied.')

        local = names.map(original, f'subsystem:{sid}', parent_path, 'subsystem')
        path = f'{parent_path}.{local}' if parent_path else local
        path_by_id[sid] = path
        systems.append(path)
        if kind == 'transport':
            transports.append(path)
        if not child_bool(el, 'enabled', True):
            disabled_paths.append(path)

    if groups:
        report.warn(
            f"{groups} group{' was' if groups == 1 else 's were'} flattened: a group is a "
            'visual grouping in Ecolego and does not scope names, so its blocks belong '
            'to the sub-system around it.')
    if systems:
        project['systems'] = systems
    if transports:
        project['transports'] = transports
    if disabled_paths:
        project['disabled_systems'] = disabled_paths
    return out


def _read_project_properties(data_model: Node, project: Dict[str, Any],
                             meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``<project-properties>``: the model's name, and who wrote it, when.

    The author and the comment are ``<property name="...">`` elements. Every
    real file calls itself ``model``, Ecolego's default, so the file's own name
    is used instead when there is one. ``readProjectProperties`` in
    ``src/io/eco.js``; returns ``{'author', 'comment', 'modified'}``, the last
    as milliseconds since 1970.
    """
    meta = meta or {}
    props = child(data_model, 'project-properties')
    from_file = _base_name(meta.get('fileName'))
    if props is None:
        project['name'] = from_file if from_file is not None else 'Imported project'
        return {'author': None, 'comment': None, 'modified': None}
    declared = props.attrs.get('name')
    if declared is None:
        declared = child_text(props, 'name')
    if declared is None:
        declared = child_text(props, 'full-name')
    chosen = from_file if (not declared or declared == 'model') else None
    if chosen is None:
        chosen = declared if declared is not None else 'Imported project'
    project['name'] = chosen
    stamp = to_number(child_text(props, 'modification-date'))
    return {
        'author': _property_text(props, 'author') or None,
        'comment': _property_text(props, 'comment') or child_text(props, 'comment') or None,
        'modified': stamp if math.isfinite(stamp) and stamp > 0 else None,
    }


_EXTENSION = re.compile(r'\.(eco|eas|xml)\Z', re.I | re.A)


def _base_name(path: Optional[str]) -> Optional[str]:
    """``…/model C.eco`` -> ``model C``."""
    if not path:
        return None
    last = _last_part(str(path))
    return js_trim(_EXTENSION.sub('', last, count=1)) or None


_CREATED = re.compile('Created at[' + _S + ']+(' + JS_DOT + '+)', re.I | re.A)


def _describe_model(project: Dict[str, Any], facts: Optional[Dict[str, Any]] = None) -> str:
    """What the model is, in up to five lines, for its description.

    Where it came from (the file, the Ecolego that wrote it, the author, the
    date), then what is in it (how many of each kind of block, in how many
    sub-systems, how many states), what it is indexed by (the lists blocks
    actually carry, most used first) and what a run of it does. The author's
    own comment leads when there is one; Ecolego's default ``Created at
    <date>`` is read as the date it is. ``describeModel`` in ``src/io/eco.js``.

    ``facts`` holds ``author``, ``comment``, ``modified`` (milliseconds since
    1970), ``fileName`` and ``version``.
    """
    facts = facts or {}
    author = facts.get('author')
    comment = facts.get('comment')
    modified = facts.get('modified')
    file_name = facts.get('fileName')
    version = facts.get('version')

    lines: List[str] = []
    created = _CREATED.fullmatch(js_trim('' if comment is None else str(comment)))
    if comment and not created:
        lines.append(js_trim(comment))

    # Where it came from.
    parts: List[str] = []
    file = _last_part('' if file_name is None else str(file_name))
    parts.append(f'Imported from {file}' if file else 'Imported from Ecolego')
    if version:
        parts.append(f'written by Ecolego {version}')
    if author:
        parts.append(f'by {author}')
    if created:
        parts.append(f'created {js_trim(created.group(1))}')
    elif modified is not None:
        parts.append(f'last changed {iso_date(modified)}')
    lines.append(f"{', '.join(parts)}.")

    # What is in it, in the order the panels list the kinds.
    counts: List[str] = []
    for collection in KINDS:
        n = len(project.get(collection) or [])
        if not n:
            continue
        label = (KIND_LABEL.get(SINGULAR.get(collection)) or collection).lower()
        counts.append(f'{n} {_singularise(label) if n == 1 else label}')
    if counts:
        systems = len(project.get('systems') or [])
        states = _state_count(project)
        lines.append(
            f'Holds {_list_of(counts)}'
            + (f", in {systems} sub-system{'' if systems == 1 else 's'}" if systems else '')
            + (f"; {states} state{'' if states == 1 else 's'} to integrate" if states else '')
            + '.')

    # What it is indexed by: the lists blocks actually carry, most used first.
    used: Dict[str, int] = {}
    for collection in KINDS:
        for block in project.get(collection) or []:
            for dim in (block.get('index_lists') if isinstance(block, dict) else None) or []:
                used[dim] = used.get(dim, 0) + 1
    ranked = sorted(used.items(), key=lambda item: (-item[1], collation_key(item[0])))
    dims = []
    for name, _count in ranked:
        lst = next((l for l in project.get('index_lists') or [] if l.get('name') == name), None)
        n = len([i for i in (lst or {}).get('indices') or [] if i.get('enabled') is not False])
        dims.append(f'{name} ({n})' if n else name)
    if dims:
        most = 6
        shown = dims[:most]
        if len(dims) > most:
            shown.append(f'{len(dims) - most} more')
        lines.append(f'Indexed by {_list_of(shown)}.')

    # What a run of it does.
    sim = project.get('simulation') or {}
    if sim.get('end_time') is not None:
        unit = sim.get('time_unit')
        unit = 'year' if unit is None else unit
        start = sim.get('start_time')
        solver = sim.get('solver')
        lines.append(f"Runs {_fmt_count(0 if start is None else start)} to {_fmt_count(sim['end_time'])} "
                     f"{unit}s with {DEFAULT_SOLVER if solver is None else solver}.")
    return '\n'.join(lines)


#: What of a block the state count reads: its dimensions, and the keys that
#: say what shape of block it is.
_COUNTED_KEYS = ('name', 'system', 'hidden', 'index_lists', 'per_nuclide', 'from', 'to', 'actions', 'timing')


def _state_count(project: Dict[str, Any]) -> int:
    # `stateCount` in edit.js, which is `Model.state_count` here, on the
    # project as it stands (normalise=False, so nothing is changed on the way).
    # The Model copies what it is given, so it is given only what the count
    # reads rather than every entry of every block.
    from ..model import Model
    skeleton: Dict[str, Any] = {
        k: project[k] for k in ('index_lists', 'nuclides', 'simulation', 'farfields', 'waste_packages', 'events')
        if k in project
    }
    for collection in ('compartments', 'running_means', 'transfers'):
        skeleton[collection] = [{k: b[k] for k in _COUNTED_KEYS if k in b}
                                for b in project.get(collection) or []]
    return Model(skeleton, normalise=False).state_count()


def _singularise(label: str) -> str:
    """``compartments`` -> ``compartment``, for the one-of case."""
    if label.endswith('ies'):
        return f'{label[:-3]}y'
    if label.endswith('es') and not label.endswith('ses'):
        return label[:-2]
    return label[:-1] if label.endswith('s') else label


def _list_of(parts: List[str]) -> str:
    """``a, b and c``."""
    if len(parts) <= 1:
        return ''.join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _fmt_count(v: Any) -> str:
    """A number short enough for a sentence: 1e5 rather than 100000."""
    n = to_number(v)
    if not math.isfinite(n):
        return js_string(v)
    if n != 0 and (abs(n) >= 1e6 or abs(n) < 1e-3):
        return to_exponential(round_significant(n, 4)).replace('e+', 'e', 1)
    return js_string(round_significant(n, 6))


_INFINITE = re.compile('inf', re.I | re.A)


def _read_materials(data_model: Node, project: Dict[str, Any], report: ImportReport) -> Dict[str, Any]:
    """``<material-model>``: the nuclides with their half-lives (in seconds in
    the file, in years here; a missing or infinite one is stable), the plain
    materials with their units, and the unit the inventories are in.
    ``readMaterials`` in ``src/io/eco.js``; returns ``{'by_id', 'by_name',
    'nuclide_names', 'units'}``."""
    model = child(data_model, 'material-model')
    by_id: Dict[str, str] = {}
    by_name: Dict[str, Dict[str, Any]] = {}
    nuclide_names: Set[str] = set()
    units: Dict[str, str] = {}
    out = {'by_id': by_id, 'by_name': by_name, 'nuclide_names': nuclide_names, 'units': units}
    if model is None:
        return out

    half_lives: Dict[str, Any] = {}
    decay_unit: Optional[str] = None
    for nuc in children(model, 'nuclide'):
        name = _key_name(nuc.attrs.get('name'), 'nuclide', report)
        if not name:
            continue
        nid = child_text(nuc, 'id')
        unit = _normalise_decay_unit(child_text(nuc, 'unit'))
        if unit:
            if decay_unit and decay_unit != unit:
                report.warn(
                    f'The nuclides disagree about their unit ({decay_unit} and {unit}); '
                    f'the model is read as {decay_unit}.')
            elif not decay_unit:
                decay_unit = unit
        raw_half_life = child_text(nuc, 'half-life')
        seconds = to_number(raw_half_life)
        if math.isfinite(seconds) and seconds > 0:
            half_lives[name] = seconds / SECONDS_PER_YEAR
        else:
            # Stable isotopes are written with an infinite (or absent)
            # half-life. The word, not infinity, which JSON cannot hold.
            half_lives[name] = STABLE
            if raw_half_life and not _INFINITE.search(raw_half_life):
                report.warn(f"'{name}' has no usable half-life; it is treated as stable.")
        if nid:
            by_id[nid] = name
        by_name[name] = {'id': nid, 'name': name}
        nuclide_names.add(name)

    # Plain materials carry no decay and a unit of their own. A radionuclide's
    # unit is the model's decay unit, read above.
    for mat in children(model, 'material'):
        name = _key_name(mat.attrs.get('name'), 'material', report)
        if not name:
            continue
        mid = child_text(mat, 'id')
        if mid:
            by_id[mid] = name
        by_name[name] = {'id': mid, 'name': name}
        unit = js_trim(child_text(mat, 'unit') or '')
        if unit:
            units[name] = unit

    if half_lives:
        project['half_lives'] = js_object_order(half_lives)
    # Written whichever it is, so a round trip cannot turn an amount model
    # into an activity one by saying nothing.
    project['decay_unit'] = decay_unit if decay_unit is not None else 'Bq'
    return out


_MOLES = re.compile('mol|mole|moles', re.I | re.A)
_BECQUERELS = re.compile('bq|becquerel|bequerel', re.I | re.A)


def _normalise_decay_unit(raw: Optional[str]) -> Optional[str]:
    """A nuclide's ``<unit>`` as one of the two an inventory can be held in,
    or ``None``."""
    given = js_trim('' if raw is None else str(raw))
    if _MOLES.fullmatch(given):
        return 'mol'
    if _BECQUERELS.fullmatch(given):
        return 'Bq'
    return None


def _read_index_lists(data_model: Node, project: Dict[str, Any], names: _NameMapper, report: ImportReport,
                      materials: Dict[str, Any]) -> Dict[str, Any]:
    """``<index-list-model>``: the index lists, their sub-sets and mappings
    (resolved by id), and which of them are the material catalogue, the
    radionuclides, the scenarios and the elements -- by Ecolego's
    ``predefined-type`` where the file writes one, then by name, then by shape.
    ``readIndexLists`` in ``src/io/eco.js``.

    Index ids are scoped to their list, so each list keeps its own map; returns
    ``{'list_by_id', 'index_by_id'}``.
    """
    model = child(data_model, 'index-list-model')
    list_by_id: Dict[str, Dict[str, Any]] = {}
    index_by_id: Dict[str, Dict[str, str]] = {}  # only for resolving mapping pairs
    if model is None:
        return {'list_by_id': list_by_id, 'index_by_id': index_by_id}

    raw: List[Dict[str, Any]] = []
    for list_el in children(model, 'index-list'):
        raw_name = list_el.attrs.get('name')
        list_id = child_text(list_el, 'id')
        key = list_id if list_id is not None else (raw_name if raw_name is not None else '')
        name = names.map(raw_name, f'indexlist:{key}', '', 'IndexList')
        original_name = js_trim('' if raw_name is None else str(raw_name)) or name

        indices: List[Dict[str, Any]] = []
        own_index_by_id: Dict[str, str] = {}
        for idx_el in children(list_el, 'index'):
            idx_name = _key_name(idx_el.attrs.get('name'), f"index of '{original_name}'", report)
            if not idx_name:
                continue
            idx_id = child_text(idx_el, 'id')
            enabled_attr = idx_el.attrs.get('enabled')
            enabled = True if enabled_attr is None else enabled_attr.lower() == 'true'
            indices.append({'name': idx_name, 'enabled': enabled})
            if idx_id:
                own_index_by_id[idx_id] = idx_name
                if idx_id not in index_by_id:
                    index_by_id[idx_id] = {'name': idx_name, 'list_name': name}

        predefined = _predefined_type(list_el)
        entry: Dict[str, Any] = {
            'name': name, 'indices': indices, 'index_by_id': own_index_by_id, '_id': list_id,
            '_original': original_name,
            'for_scenarios': predefined == 'SCENARIOS',
            'for_elements': predefined == 'ELEMENTS',
            '_predefined': predefined,
        }
        sub_set = child(list_el, 'sub-set')
        if sub_set is not None and sub_set.attrs.get('of'):
            entry['_sub_set_of_id'] = sub_set.attrs['of']
        mapping = child(list_el, 'mapping')
        if mapping is not None and mapping.attrs.get('to'):
            entry['_mapping_to_id'] = mapping.attrs['to']
            entry['_mapping_pairs'] = [{'from_id': m.attrs.get('from'), 'to_id': m.attrs.get('to')}
                                       for m in children(mapping, 'map')]
        raw.append(entry)
        if list_id:
            list_by_id[list_id] = entry

    # Resolve id references now that every list is known.
    for entry in raw:
        if entry.get('_sub_set_of_id'):
            root = list_by_id.get(entry['_sub_set_of_id'])
            if root is not None:
                entry['sub_set_of'] = root['name']
            else:
                report.warn(f"Index list '{entry['_original']}' is a sub-set of a list that is not in the file.")
        if entry.get('_mapping_to_id'):
            target = list_by_id.get(entry['_mapping_to_id'])
            if target is not None:
                pairs = []
                for p in entry['_mapping_pairs']:
                    frm = entry['index_by_id'].get(p['from_id'])
                    if frm is None:
                        frm = (index_by_id.get(p['from_id']) or {}).get('name')
                    to = target['index_by_id'].get(p['to_id'])
                    if to is None:
                        to = (index_by_id.get(p['to_id']) or {}).get('name')
                    if frm and to:
                        pairs.append({'from': frm, 'to': to})
                entry['mapping'] = {'to': target['name'], 'pairs': pairs}
            else:
                report.warn(f"Index list '{entry['_original']}' maps to a list that is not in the file.")

    # The material dimensions: by predefined type, then by name, then by shape.
    known = set(materials['by_name'])
    candidates = [e for e in raw if e['indices'] and all(i['name'] in known for i in e['indices'])]

    def list_named(want: str) -> Optional[Dict[str, Any]]:
        return next((e for e in raw if js_trim(e['name']).lower() == want), None)

    def usable(e: Optional[Dict[str, Any]]) -> bool:
        return bool(e) and (not e['indices'] or any(c is e for c in candidates))

    catalogue = next((e for e in raw if e['_predefined'] == 'MATERIALS'), None)
    nuclides = next((e for e in raw if e['_predefined'] == 'RADIONUCLIDES'), None)
    if catalogue is None and usable(list_named('materials')):
        catalogue = list_named('materials')
    if nuclides is None and usable(list_named('radionuclides')):
        nuclides = list_named('radionuclides')
    # The shape: a sub-set of the materials is the radionuclides, and the list
    # a radionuclide sub-set is taken from is the materials.
    if catalogue is None and nuclides is not None and nuclides.get('sub_set_of'):
        catalogue = next((e for e in raw if e['name'] == nuclides['sub_set_of']), None)
    if catalogue is None:
        catalogue = next((e for e in candidates if not e.get('sub_set_of') and not e.get('mapping')), None)
        if catalogue is None and candidates:
            catalogue = sorted(candidates, key=lambda e: -len(e['indices']))[0]
    if nuclides is None and catalogue is not None:
        nuclides = next((e for e in candidates
                         if e is not catalogue and e.get('sub_set_of') == catalogue['name']), None)

    if catalogue is not None:
        catalogue['for_contaminants'] = True
        # A material that is not a radionuclide is measured in its own unit.
        for i in catalogue['indices']:
            unit = materials['units'].get(i['name'])
            if unit:
                i['unit'] = unit
    if nuclides is not None and nuclides is not catalogue:
        nuclides['for_nuclides'] = True
        if not nuclides.get('sub_set_of') and catalogue is not None:
            nuclides['sub_set_of'] = catalogue['name']
        # A file may carry the list without its contents; Ecolego decays what
        # the material model says, so that is what goes here.
        have = {i['name'] for i in nuclides['indices']}
        added = []
        for i in (catalogue['indices'] if catalogue is not None else []):
            if i['name'] in have or i['name'] not in materials['nuclide_names']:
                continue
            nuclides['indices'].append({'name': i['name'], 'enabled': i['enabled']})
            added.append(i['name'])
        if added and not have:
            report.warn(
                f"'{nuclides['name']}' is empty in this file; its {len(added)} "
                f"radionuclide{'' if len(added) == 1 else 's'} were read from the "
                'material model, which is what Ecolego decays them from.')
    decaying = nuclides if nuclides is not None else catalogue
    if decaying is not None:
        project['nuclides'] = [i['name'] for i in decaying['indices'] if i['enabled']]

    # A file that says nothing about its lists still names them: `Scenarios`
    # and `Elements` are Ecolego's own names for its own.
    if not any(e['for_scenarios'] for e in raw):
        found = list_named('scenarios')
        if found is not None:
            found['for_scenarios'] = True
    if not any(e['for_elements'] for e in raw):
        found = list_named('elements')
        if found is not None and not found.get('for_contaminants') and not found.get('for_nuclides'):
            found['for_elements'] = True

    scenarios = [e for e in raw if e['for_scenarios']]
    named = [i for e in scenarios for i in e['indices'] if i['enabled']]
    if len(named) > 1:
        report.warn(
            f"This model has {len(named)} scenarios ({scenarios[0]['name']}). Ecolego "
            'runs one simulation per scenario; this tool runs one at a time -- pick '
            'which under Simulation, and every block indexed by that list is read at '
            f"the one selected. It opened on '{named[0]['name']}'.")

    lists = []
    for e in raw:
        out: Dict[str, Any] = {'name': e['name'], 'indices': e['indices']}
        if e.get('for_contaminants'):
            out['for_contaminants'] = True
        if e.get('for_nuclides'):
            out['for_nuclides'] = True
        if e['for_scenarios']:
            out['for_scenarios'] = True
        if e['for_elements']:
            out['for_elements'] = True
        if e.get('sub_set_of'):
            out['sub_set_of'] = e['sub_set_of']
        if e.get('mapping'):
            out['mapping'] = e['mapping']
        lists.append(out)
    project['index_lists'] = lists
    return {'list_by_id': list_by_id, 'index_by_id': index_by_id}


def _read_decay_chains(data_model: Node, project: Dict[str, Any], report: ImportReport) -> None:
    """``<nuclide-decay-model>``: the decay pairs, with their branching ratios
    (1 where the file's is not a number). ``readDecayChains`` in
    ``src/io/eco.js``."""
    model = child(data_model, 'nuclide-decay-model')
    if model is None:
        return
    chains = []
    for pair in children(model, 'decay-pair'):
        rate = pair.attrs.get('rate')
        parent = _key_name(pair.attrs.get('parent'), 'decay pair parent', report)
        daughter = _key_name(pair.attrs.get('daughter'), 'decay pair daughter', report)
        if not parent or not daughter:
            continue
        # A missing attribute is `undefined`, which is NaN.
        ratio = math.nan if rate is None else to_number(rate)
        chains.append([parent, daughter, ratio if math.isfinite(ratio) else 1])
    if chains:
        project['chains'] = chains


def _read_blocks(data_model: Node, project: Dict[str, Any], names: _NameMapper, index_ids: Dict[str, Any],
                 report: ImportReport,
                 hierarchy: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """``<block-model>``: every component and connection, as blocks of this
    tool's kinds or as entries in the report. ``readBlocks`` in
    ``src/io/eco.js``.

    Returns the map from block id to qualified name, which the rewrites use,
    and the sub-system wiring for :func:`_connect_interfaces`.
    """
    model = child(data_model, 'block-model')
    if model is None:
        report.warn('The file has no <block-model>; nothing to import.')
        return {}, {'links': [], 'operations': {}, 'exposed': {}, 'id_by_guid': {}}

    elements = children(model, 'component') + children(model, 'connection')

    # What the sub-system interfaces say, applied once every block exists.
    wiring: Dict[str, Any] = {'links': [], 'operations': {}, 'exposed': {}, 'id_by_guid': None}

    block_name_by_id: Dict[str, str] = {}
    path_by_id = hierarchy['path_by_id'] if hierarchy is not None else {}
    declared = set(hierarchy['systems'] if hierarchy is not None else [])

    def system_of_element(el: Node) -> str:
        # A file that declares no hierarchy still says where its blocks live,
        # so an undeclared parent is taken at its word.
        parent_id = child_text(el, 'sub-system')
        if not parent_id:
            return ''
        if parent_id in path_by_id:
            return path_by_id[parent_id]
        all_parts = parent_id.split('.')
        path = '.'.join(
            names.map(part, f"subsystem:{'.'.join(all_parts[:i + 1])}", '.'.join(all_parts[:i]), 'subsystem')
            for i, part in enumerate(all_parts))
        path_by_id[parent_id] = path
        if path not in declared:
            declared.add(path)
            project.setdefault('systems', []).append(path)
        return path

    def dim_ids_of(el: Node) -> List[str]:
        return [s for s in (js_trim(p) for p in el.attrs.get('index-lists', '').split(',')) if s]

    def dim_lists_of(el: Node) -> List[Dict[str, Any]]:
        return [l for l in (index_ids['list_by_id'].get(i) for i in dim_ids_of(el)) if l]

    dims_by_id: Dict[str, List[Dict[str, Any]]] = {}
    boundary_ids: Set[str] = set()
    system_by_id: Dict[str, str] = {}
    disabled_ids: Dict[str, None] = {}
    id_by_guid: Dict[str, str] = {}

    # Pass one: block id -> qualified name, so connections can resolve their
    # ends and equations their qualified references.
    for el in elements:
        bid = child_text(el, 'id')
        type_ = el.attrs.get('type')
        if not bid:
            continue
        guid = child_text(el, 'guid')
        if guid:
            id_by_guid[js_trim(guid)] = bid
        if not child_bool(el, 'enabled', True):
            disabled_ids[bid] = None
        if type_ in BOUNDARY:
            boundary_ids.add(bid)
            continue
        if type_ not in SUPPORTED:
            continue
        dims_by_id[bid] = dim_lists_of(el)
        system = system_of_element(el)
        system_by_id[bid] = system
        local = names.map(el.attrs.get('name'), bid, system, bid)
        block_name_by_id[bid] = f'{system}.{local}' if system else local

    transports = hierarchy['transports'] if hierarchy is not None else []
    for el in elements:
        type_ = el.attrs.get('type')
        original = el.attrs.get('name', '(unnamed)')

        if type_ in BOUNDARY:
            continue  # folded into the transfers that attach to it
        if type_ in INTERFACE:
            # Read for its wiring, then dropped. A disabled one routes nothing.
            if child_text(el, 'id') in disabled_ids:
                continue
            if type_ == 'connector':
                for link in children(el, 'model-connection'):
                    source = js_trim(link.attrs.get('source', ''))
                    target = js_trim(link.attrs.get('target', ''))
                    if source and target:
                        wiring['links'].append({'source': source, 'target': target, 'via': original})
            else:
                for obj in children(el, 'interface-object'):
                    guid = js_trim(obj.attrs.get('guid', ''))
                    if not guid:
                        continue
                    wiring['exposed'][guid] = None
                    op = js_trim(obj.attrs.get('operation', '')).upper()
                    if op:
                        wiring['operations'][guid] = op
            continue
        if type_ in NON_NUMERIC:
            report.note(type_, original)
            continue
        if type_ not in SUPPORTED:
            report.skip('unknown' if type_ is None else type_, original,
                        'this tool has no equivalent block type')
            continue

        bid = child_text(el, 'id')
        system = system_by_id.get(bid) if bid is not None else None
        if system is None:
            system = system_of_element(el)
        qualified = block_name_by_id.get(bid) if bid is not None else None
        if qualified is None:
            qualified = names.map(original, bid if bid is not None else original, system)
        # Blocks carry their own local name and the sub-system holding them.
        name = qualified[len(system) + 1:] if system and qualified.startswith(f'{system}.') else qualified
        # Dimension lists in declared order, for resolving entry ids -- and,
        # where the file names none but says there is one, the list that
        # stands for the intersection of a transfer's two ends.
        dim_lists = dim_lists_of(el) or _intersection_dims(el, original, dims_by_id, report)
        dims = [l['name'] for l in dim_lists if l['name']]
        # A block with no index lists is scalar and says so.
        dim_spec = {'index_lists': dims} if dims else {'per_nuclide': False}

        unit = child_text(el, 'unit') or ''
        comment = child_text(el, 'comment') or ''
        entries = _read_entries(el, dim_lists, report, original)

        is_expression = type_ in ('expression', 'post-processing', 'constant', 'transport-number')
        role = TRANSPORT_ROLE.get(type_)
        role_patch = {'transport': role} if role else {}
        # A part of a transport outside a transport sub-system is a part of
        # nothing: a file edited by hand.
        if role and system not in transports:
            report.skip(type_, original, 'it is a part of a transport, and is not inside one')
            continue

        if type_ == 'compartment' or role in ('begin', 'end'):
            _readable_tolerances(entries, original, report)
            block = {
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment, **role_patch,
                'handle_decay': child_bool(el, 'handle-decay', True),
                'initial': _or(_pick_default(entries, 'initial'), '0'),
                'abstol': _pick_default(entries, 'abstol'),
                'dydt': _pick_default(entries, 'dydt'),
            }
            block['non_negative'] = _read_non_negative(entries, original, report)
            block['entries'] = _keep_indexed(entries, ['initial', 'abstol', 'dydt'])
            project['compartments'].append(_trim_empty(block))
        elif role == 'counter':
            project['expressions'].append(_trim_empty({
                'name': name, 'system': system, **dim_spec, 'unit': '', 'comment': comment,
                'transport': 'counter', 'equation': '1',
            }))
        elif role == 'operation':
            # How it is read follows from how many arguments it declares.
            args = len(children(el, 'argument'))
            operation = child_text(el, 'operation')
            project['expressions'].append(_trim_empty({
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment,
                'transport': 'operation',
                'operation': 'MEAN' if operation is None else operation,
                'argument': 'range' if args >= 2 else 'point' if args == 1 else 'all',
            }))
        elif is_expression:
            if type_ not in ('expression', 'transport-number'):
                report.warn(
                    f"'{original}' is a {type_} expression; this tool evaluates every "
                    'expression at each step, which is equivalent unless it depended on '
                    'the evaluation order.')
            # An expression with `<argument>` elements is a function: called
            # with those values rather than read.
            arg_names = [a for a in (_or(child_text(x, 'argument-key'), child_text(x, 'argument-name'))
                                     for x in children(el, 'argument')) if a]
            if arg_names and not role:
                parameters: List[str] = []
                for a in arg_names:
                    parameters.append(_safe_parameter(a, parameters))
                per_index = _keep_indexed(entries, ['equation'])
                if per_index:
                    report.warn(
                        f"'{original}' is a function of {', '.join(parameters)} with "
                        f'{len(per_index)} equation(s) set per index. A function is '
                        "worked out where it is called, at the caller's index, so only "
                        'its default equation came across.')
                project['functions'].append(_trim_empty({
                    'name': name, 'system': system, 'unit': unit, 'comment': comment,
                    'parameters': parameters,
                    'equation': _or(_pick_default(entries, 'equation'), ''),
                }))
                continue
            project['expressions'].append(_trim_empty({
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment, **role_patch,
                'equation': _or(_pick_default(entries, 'equation'), '0'),
                'entries': _keep_indexed(entries, ['equation']),
            }))
        elif type_ == 'lookup-table':
            # An <argument> makes the table a function of what the caller
            # passes, instead of a series read at the clock.
            arg_el = child(el, 'argument')
            argument = ((child_text(arg_el, 'argument-key') or child_text(arg_el, 'argument-name') or 'X')
                        if arg_el is not None else None)
            option = child_text(el, 'lookup-option')
            interpolation = interpolation_from_eco(option)
            if option and not interpolation:
                report.warn(
                    f"'{original}' uses the interpolation rule '{option}', which this "
                    'tool does not know; straight lines between the points were used.')
            block = {
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment,
                'interpolation': _or(interpolation, 'linear'),
                'cyclic': child_bool(el, 'lookup-cyclic', False),
            }
            if argument:
                block['argument'] = argument
            block['points'] = _or(_pick_default(entries, 'points'), [])
            block['entries'] = _keep_indexed(entries, ['points'])
            project['lookups'].append(_trim_empty(block))
        elif type_ in ('index-operation', 'aggregate'):
            # The target is the block's own equation: one id for an index
            # operation, ids joined with `+` for an aggregate.
            spec = _or(_pick_default(entries, 'equation'), '')
            raw_op = child_text(el, 'operation')
            operation = operation_from_eco(raw_op)
            if raw_op and not operation:
                report.warn(
                    f"'{original}' reduces with '{raw_op}', which this tool does not know; "
                    'it was summed instead.')
            common = {
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment,
                'operation': _or(operation, 'sum'),
            }
            if type_ == 'index-operation':
                # Only when it is actually there: Number(null) is 0, which
                # would look like a stated percentile of zero.
                stated = _property_text(el, 'percentile')
                pct = child_number(el, 'percentile')
                if pct is None:
                    pct = None if stated is None or stated == '' else to_number(stated)
                block = {**common, 'target': js_trim(spec) or None}
                if is_finite(pct):
                    block['percentile'] = pct
                block['entries'] = [{'index': e['index'], 'target': js_trim(js_string(e['equation']))}
                                    for e in _keep_indexed(entries, ['equation'])]
                project['index_reductions'].append(_trim_empty(block))
            else:
                project['block_reductions'].append(_trim_empty({
                    **common,
                    'targets': _split_targets(spec),
                    'entries': [{'index': e['index'], 'targets': _split_targets(e['equation'])}
                                for e in _keep_indexed(entries, ['equation'])],
                }))
        elif type_ in KIND_FROM_ECO:
            # The blocks that remember, and the events that drive them.
            kind = KIND_FROM_ECO[type_]
            keys = EQUATION_FIELDS[kind] + EVENT_FIELDS[kind]
            common = {'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment}

            def pick(key: str, fallback: Any) -> Any:
                return _or(_pick_default(entries, key), fallback)

            per_index = _keep_indexed(entries, keys)
            if kind == 'min_max':
                raw_op = child_text(el, 'operation')
                op = extreme_from_eco(raw_op)
                if raw_op and not op:
                    report.warn(
                        f"'{original}' records '{raw_op}', which this tool does not know; "
                        'its maximum was recorded instead.')
                project['min_maxes'].append(_trim_empty({
                    **common, 'operation': _or(op, 'max'),
                    'target': pick('target', '0'),
                    'reset_trigger': pick('reset_trigger', None),
                    'start_trigger': pick('start_trigger', None),
                    'stop_trigger': pick('stop_trigger', None),
                    'entries': per_index,
                }))
            elif kind == 'running_mean':
                project['running_means'].append(_trim_empty({
                    **common,
                    'target': pick('target', '0'),
                    'reset_trigger': pick('reset_trigger', None),
                    'start_trigger': pick('start_trigger', None),
                    'stop_trigger': pick('stop_trigger', None),
                    'entries': per_index,
                }))
            elif kind == 'snapshot':
                project['snapshots'].append(_trim_empty({
                    **common,
                    'target': pick('target', '0'),
                    'trigger': pick('trigger', None),
                    'initial': pick('initial', '0'),
                    'entries': per_index,
                }))
            elif kind == 'delay':
                project['delays'].append(_trim_empty({
                    **common,
                    'target': pick('target', '0'),
                    'delay': pick('delay', '0'),
                    'entries': per_index,
                }))
            else:
                project['triggers'].append(_trim_empty({
                    **common,
                    'first': pick('first', '0'),
                    'second': pick('second', '0'),
                    'direction': pick('direction', 'rising'),
                    'entries': per_index,
                }))
        elif type_ == 'parameter':
            # Only what could not be read is worth saying; a distribution that
            # arrived intact is on the parameter.
            unread = len([e for e in entries if e.get('pdf_unread')])
            if unread:
                what = 'a probability distribution' if unread == 1 else f'{unread} probability distributions'
                report.warn(
                    f"'{original}' has {what} "
                    'this tool could not read; the constant value is used for '
                    f"{'it' if unread == 1 else 'them'}.")
            project['parameters'].append(_trim_empty({
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment,
                'value': _or(_pick_default(entries, 'value'), 0),
                'pdf': _pick_default(entries, 'pdf'),
                'entries': _keep_indexed(entries, ['value', 'pdf']),
            }))
        elif type_ in ('transfer', 'transfer-coefficient'):
            def resolve_end(id_attr: Optional[str], which: str) -> Tuple[Optional[str], bool]:
                if not id_attr:
                    return None, True
                if id_attr in boundary_ids:
                    return None, True
                end = block_name_by_id.get(id_attr)
                if not end:
                    report.warn(
                        f"Transfer '{original}' {which} a block that was not imported; "
                        'that end was left open.')
                    return None, False
                return end, True

            frm, _ = resolve_end(el.attrs.get('source'), 'starts at')
            to, _ = resolve_end(el.attrs.get('target'), 'ends at')
            if frm is None and to is None:
                report.skip(type_, original, 'neither endpoint is a compartment in this model')
                continue

            donor = _or(_pick_default(entries, 'multiply_by_donor'), DONOR_DEFAULT.get(type_, False))
            project['transfers'].append(_trim_empty({
                'name': name, 'system': system, **dim_spec, 'unit': unit, 'comment': comment,
                'from': frm, 'to': to,
                'rate': _or(_pick_default(entries, 'rate'), '0'),
                # A transfer with no donor cannot be multiplied by one.
                'multiply_by_donor': False if frm is None else donor,
                'entries': _keep_indexed(entries, ['rate', 'multiply_by_donor']),
            }))

    # The blocks the file switches off, now that they exist. A block inside a
    # sub-system the file switches off keeps its own switch; the report counts
    # what each such sub-system holds.
    off_names = {block_name_by_id[i] for i in disabled_ids if block_name_by_id.get(i)}
    off_paths = hierarchy['disabled_paths'] if hierarchy is not None else []

    def in_off_system(system: str) -> Optional[str]:
        return next((p for p in off_paths if system == p or system.startswith(f'{p}.')), None)

    if off_names or off_paths:
        for collection in ('compartments', 'expressions', 'transfers', 'parameters', 'inflows',
                           'lookups', 'index_reductions', 'block_reductions',
                           'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers'):
            for block in project.get(collection) or []:
                qname = _qualified(block)
                via = in_off_system(block['system']) if block.get('system') else None
                if via:
                    report.in_disabled_system(via)
                if qname not in off_names:
                    continue
                block['enabled'] = False
                report.disable(qname)

    wiring['id_by_guid'] = id_by_guid
    return block_name_by_id, wiring


def _or(value: Any, fallback: Any) -> Any:
    # JavaScript's `value ?? fallback`: only a missing value falls back.
    return fallback if value is None else value


def _intersection_dims(el: Node, original: str, dims_by_id: Dict[str, List[Dict[str, Any]]],
                       report: ImportReport) -> List[Dict[str, Any]]:
    """The list a transfer written over the intersection of its two ends
    stands on: Ecolego writes that list as ``index-lists=""`` with
    ``dimension="1"``. When one end's list is a sub-set of the other's it *is*
    the intersection; two lists that merely overlap have none this tool can
    name, and that is said. ``intersectionDims`` in ``src/io/eco.js``."""
    dimension = el.attrs.get('dimension')
    width = to_number(0 if dimension is None else dimension)
    if not math.isfinite(width) or width < 1:
        return []
    frm = dims_by_id.get(el.attrs.get('source')) or []
    to = dims_by_id.get(el.attrs.get('target')) or []
    # One end outside the model has nothing to intersect with.
    if not frm or not to:
        only = frm if frm else to
        return only if len(only) == width else []

    picks: List[Dict[str, Any]] = []
    for a in frm:
        for b in to:
            if a['name'] == b['name']:
                narrower = a
            elif a.get('sub_set_of') == b['name']:
                narrower = a
            elif b.get('sub_set_of') == a['name']:
                narrower = b
            else:
                narrower = None
            if narrower is not None and not any(p is narrower for p in picks):
                picks.append(narrower)
    if len(picks) == width:
        return picks

    report.warn(
        f"'{original}' is written over the indices its two ends have in common "
        f"({' × '.join(l['name'] for l in frm) or 'none'} and "
        f"{' × '.join(l['name'] for l in to) or 'none'}), which is a list "
        'Ecolego works out and does not write down. Neither end\'s dimension is '
        'a sub-set of the other\'s, so there is no list here that holds exactly '
        f"those indices: '{original}' was read as the file spells it, and will "
        'need a dimension chosen by hand.')
    return []


def _read_entries(el: Node, dim_lists: List[Dict[str, Any]], report: ImportReport,
                  block_label: str) -> List[Dict[str, Any]]:
    """A block's ``<entry>`` elements, each as ``{'index': {list: index},
    ...values}``. An entry whose index cannot be resolved against the block's
    own lists is dropped rather than applied to the wrong cells."""
    out: List[Dict[str, Any]] = []
    for entry_el in children(el, 'entry'):
        index: Dict[str, str] = {}
        ids = [s for s in (js_trim(p) for p in entry_el.attrs.get('index', '').split(',')) if s]

        for position, idx_id in enumerate(ids):
            # The ids are written in the order the block declares its lists,
            # so position i belongs to dimension i; a search where it does not.
            positional = dim_lists[position] if position < len(dim_lists) else None
            if positional is not None and idx_id in positional['index_by_id']:
                index[positional['name']] = positional['index_by_id'][idx_id]
                continue
            owner = next((l for l in dim_lists if idx_id in l['index_by_id']), None)
            if owner is not None:
                index[owner['name']] = owner['index_by_id'][idx_id]
                continue
            report.warn(
                f"An entry of '{block_label}' is keyed by an index ('{idx_id}') that none "
                'of its index lists contains; that entry was dropped.')

        rec: Dict[str, Any] = {'index': index}
        type_ = entry_el.attrs.get('type')

        if type_ == 'compartment':
            _assign_if(rec, 'initial', child_text(entry_el, 'initial-condition'))
            _assign_number_if(rec, 'lower', child_text(entry_el, 'lower-saturation'))
            _assign_number_if(rec, 'upper', child_text(entry_el, 'upper-saturation'))
            # This compartment's own absolute tolerance, at this index.
            _assign_number_if(rec, 'abstol', child_text(entry_el, 'abs-tol'))
            # The extra term in the compartment's rate of change.
            _assign_if(rec, 'dydt', child_text(entry_el, 'differential-equation'))
        elif type_ == 'transfer':
            _assign_if(rec, 'rate', child_text(entry_el, 'transfer-equation'))
            mult = child_text(entry_el, 'multiply-with-donor')
            if mult is not None and mult != '':
                rec['multiply_by_donor'] = mult.lower() == 'true'
            if child_text(entry_el, 'transfer-event'):
                report.warn(
                    f"'{block_label}' has a transfer event (a discrete transfer), which "
                    'this tool does not support.')
        elif type_ == 'expression':
            _assign_if(rec, 'equation', child_text(entry_el, 'equation'))
        elif type_ == 'parameter':
            _assign_number_if(rec, 'value', child_text(entry_el, 'value'))
            # The distribution, kept: `function=` names the kind and the
            # expression the family, and the parser needs both.
            pdf_el = child(entry_el, 'pdf')
            if pdf_el is not None:
                from ..stats.pdf import parse_pdf
                spec = parse_pdf(_or(child_text(pdf_el, 'pdf-value'), ''),
                                 _or(pdf_el.attrs.get('function'), ''))
                if spec:
                    rec['pdf'] = spec
                else:
                    rec['pdf_unread'] = _or(child_text(pdf_el, 'pdf-value'), '')
        elif type_ in ('min-max', 'running-mean'):
            _assign_if(rec, 'target', child_text(entry_el, 'target-expression'))
            _assign_if(rec, 'reset_trigger', child_text(entry_el, 'reset-event'))
            _assign_if(rec, 'start_trigger', child_text(entry_el, 'start-recording-event'))
            _assign_if(rec, 'stop_trigger', child_text(entry_el, 'stop-recording-event'))
        elif type_ == 'snapshot':
            _assign_if(rec, 'target', child_text(entry_el, 'snapshot-target'))
            _assign_if(rec, 'trigger', child_text(entry_el, 'snapshot-event'))
            _assign_if(rec, 'initial', child_text(entry_el, 'snapshot-initial-value'))
        elif type_ == 'delay':
            _assign_if(rec, 'target', child_text(entry_el, 'delay-target'))
            _assign_if(rec, 'delay', child_text(entry_el, 'delay-time'))
        elif type_ == 'discrete-event':
            _assign_if(rec, 'first', child_text(entry_el, 'first-expression'))
            _assign_if(rec, 'second', child_text(entry_el, 'second-expression'))
            direction = direction_from_eco(child_text(entry_el, 'direction'))
            if direction:
                rec['direction'] = direction
        elif type_ == 'lookup-table':
            xs = _number_list(child_text(entry_el, 'lookup-table-time-points'))
            ys = _number_list(child_text(entry_el, 'lookup-table-values'))
            # Walked to the shorter of the two, so a truncated file loses the
            # tail rather than the whole table.
            n = min(len(xs), len(ys))
            if n < len(xs) or n < len(ys):
                report.warn(
                    f"'{block_label}' has {len(xs)} time point(s) but {len(ys)} "
                    'value(s); the extra ones were dropped.')
            points = [[xs[k], ys[k]] for k in range(n)]
            if points:
                rec['points'] = points
            if child(entry_el, 'link') is not None:
                report.warn(
                    f"'{block_label}' takes its table from a linked result, which this "
                    'tool cannot follow; the stored points were used.')

        entry_unit = child_text(entry_el, 'entry-unit')
        if entry_unit:
            rec['unit'] = entry_unit

        if len(index) != len(ids):
            continue
        out.append(rec)
    return out


def _split_targets(text: Any) -> List[str]:
    """An aggregate's targets, as the format joins them: ``a+b``."""
    return [t for t in (js_trim(p) for p in ('' if text is None else js_string(text)).split('+')) if t]


def _predefined_type(el: Node) -> Optional[str]:
    """The ``predefined-type`` an index list declares, upper-cased: one file
    writes ``SCENARIOS``, an older one ``Scenarios``."""
    text = _property_text(el, 'predefined-type')
    return js_trim(text).upper() if text else None


def _property_text(el: Node, name: str) -> Optional[str]:
    """The text of a ``<property name="...">``, trimmed, or ``None``."""
    for p in children(el, 'property'):
        if p.attrs.get('name') == name:
            return js_trim(p.text or '')
    return None


def _number_list(text: Optional[str]) -> List[float]:
    """An array as the format writes it, ``[1.0, 2.5, 3.0]``; what is not a
    number is dropped. An empty element reads as 0, as ``Number('')`` does."""
    if text is None:
        return []
    inner = js_trim(str(text))
    if inner.startswith('['):
        inner = inner[1:]
    if inner.endswith(']'):
        inner = inner[:-1]
    if not js_trim(inner):
        return []
    out = []
    for part in inner.split(','):
        n = to_number(js_trim(part))
        if math.isfinite(n):
            out.append(n)
    return out


def _assign_if(rec: Dict[str, Any], key: str, value: Optional[str]) -> None:
    if value is not None and value != '':
        rec[key] = value


def _assign_number_if(rec: Dict[str, Any], key: str, value: Optional[str]) -> None:
    if value is None or value == '':
        return
    n = to_number(value)
    if math.isfinite(n):
        rec[key] = n
    elif value.lower() == 'infinity':
        rec[key] = math.inf


def _readable_tolerances(entries: List[Dict[str, Any]], block_label: str, report: ImportReport) -> None:
    """Drops an absolute tolerance this tool cannot carry -- infinite, zero or
    negative -- and says so."""
    dropped = 0
    for e in entries:
        if 'abstol' not in e:
            continue
        if is_finite(e['abstol']) and e['abstol'] > 0:
            continue
        del e['abstol']
        dropped += 1
    if dropped:
        report.warn(
            f"'{block_label}' sets an absolute tolerance this tool cannot carry "
            f'({dropped} of them -- infinite, zero or negative). The '
            "simulation's own absolute tolerance applies to those states.")


def _read_non_negative(entries: List[Dict[str, Any]], block_label: str, report: ImportReport) -> bool:
    """Ecolego's saturation band, read as the one constraint this tool keeps:
    a floor of zero is *cannot go negative*, a negative floor is its opposite,
    and a positive floor or a finite ceiling is dropped with a warning."""
    bounded = False
    negative_floor = False
    for e in entries:
        lo = e.get('lower')
        hi = e.get('upper')
        if lo is not None and math.isfinite(to_number(lo)):
            if to_number(lo) < 0:
                negative_floor = True
            elif to_number(lo) > 0:
                bounded = True
        if hi is not None and math.isfinite(to_number(hi)):
            bounded = True
    if bounded:
        report.warn(
            f"'{block_label}' has a saturation band. This tool keeps only the "
            '"cannot go negative" part of it, so the '
            'floor and ceiling were dropped -- express a cap as a rate term '
            'instead, or the model will not be the one in the file.')
    return not negative_floor


def _pick_default(entries: List[Dict[str, Any]], key: str) -> Any:
    """The value of the entry with no index -- Ecolego's default -- or ``None``."""
    for e in entries:
        if not e['index'] and key in e:
            return e[key]
    return None


def _keep_indexed(entries: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    """The entries that carry an index, with only ``keys``."""
    out = []
    for e in entries:
        if not e['index']:
            continue
        rec: Dict[str, Any] = {'index': e['index']}
        found = False
        for k in keys:
            if k in e:
                rec[k] = e[k]
                found = True
        if found:
            out.append(rec)
    return out


def _trim_empty(obj: Dict[str, Any]) -> Dict[str, Any]:
    """``obj`` without its empty strings, missing values and empty lists."""
    return {k: v for k, v in obj.items()
            if not (v is None or (isinstance(v, str) and v == '') or (isinstance(v, list) and not v))}


# --- simulation settings ------------------------------------------------------------------

#: The solver each Ecolego solver name becomes: three are the same method, the
#: rest the nearest there is.
SOLVER_MAP = {
    'ODE45': 'dp45', 'ODE23': 'dp45', 'ODE113': 'dp45', 'ODE853': 'dp45',
    'ODE15S': 'ndf',
    'ODE23S': 'ros23', 'ODE23T': 'ros23', 'ODE23TB': 'ros23',
    'RADAU5': 'ndf', 'KRYLOV': 'ndf', 'PADE': 'ndf', 'TAYLOR': 'ndf',
}

#: The names above that arrive at the same method rather than a substitute.
SOLVER_EXACT = frozenset(['ODE15S', 'ODE23S', 'ODE45'])

#: Ecolego's "not set": one magic double written wherever a number was left
#: alone -- as a time series' first or last time among other places.
D_AUTO = -792842341234.23404823434


def _auto_number(el: Node, tag: str) -> Optional[float]:
    """One number from the file, with Ecolego's "not set" read as absent."""
    v = child_number(el, tag)
    if v is None or not math.isfinite(v):
        return None
    return None if abs(v - D_AUTO) <= abs(D_AUTO) * 1e-9 else v


_OUTPUT_MODES = {
    'produce no additional output': 'solver',
    'produce additional output': 'both',
    'produce specified output only': 'series',
    '0': 'solver',
    '1': 'both',
    '2': 'series',
}


def _read_output_times(s: Node, sim: Dict[str, Any], report: ImportReport) -> None:
    """When Ecolego saves results and on what times: ``<output-options>`` (in
    words, or as the index 0/1/2 older files write), overridden by
    ``<batch-mode>``, and the series in ``<time-series-list>`` and
    ``<discrete-times>``.

    As in the application, the index is read through ``Number()``, so a file
    with no ``<output-options>`` at all reads as ``Number('')``, 0: the
    solver's own points, which is Ecolego's default.
    """
    written = js_trim(child_text(s, 'output-options') or '')
    mode = _OUTPUT_MODES.get(written.lower())
    if mode is None:
        mode = _OUTPUT_MODES.get(js_string(to_number(written)))

    series = (_read_time_series(child(s, 'time-series-list'), sim, report)
              + _read_time_series(child(s, 'discrete-times'), sim, report))
    if series:
        sim['output_times'] = series

    # Batch mode reports on the specified times whatever the option says.
    batch = js_trim(child_text(s, 'batch-mode') or '').lower() == 'true'
    wanted = 'series' if batch else mode
    if not wanted:
        return
    if wanted == 'solver':
        sim['spacing'] = 'solver'
        return
    if not series:
        report.warn(
            'The file asks for output on specified times but lists none; '
            f"{js_string(sim['output_points'])} logarithmic points were used instead.")
        return
    sim['spacing'] = wanted


_TIMES_SPLIT = re.compile('[' + _S + ',;]+')
_BRACKETS = re.compile(r'[\[\]]')


def _read_time_series(host: Optional[Node], sim: Dict[str, Any], report: ImportReport) -> List[Dict[str, Any]]:
    """The ``<time-series>`` children of one list, as this tool's own series."""
    if host is None:
        return []
    out: List[Dict[str, Any]] = []
    for el in children(host, 'time-series'):
        type_ = el.attrs.get('type', '').lower()
        if type_ == 'custom':
            # `[1000.0, 2000.0]`; the empty tokens go before they are read as
            # numbers, or `[]` would be the single time zero.
            text = _BRACKETS.sub('', child_text(el, 'values') or '')
            times = [v for v in (to_number(t) for t in _TIMES_SPLIT.split(text) if t != '')
                     if math.isfinite(v)]
            if times:
                out.append({'kind': 'times', 'times': sorted(times)})
            continue
        # Either end may be Ecolego's AUTO, "follow the simulation", which is
        # what this tool's series mean by an empty end.
        frm = _auto_number(el, 'time-series-start-time')
        to = _auto_number(el, 'time-series-end-time')
        kind = 'log' if type_ == 'geometric' else 'linear'
        points: Any = child_number(el, 'n')
        if points is None:
            # An incrementing series says how far apart its points are.
            step = child_number(el, 'increment')
            a = sim['start_time'] if frm is None else frm
            b = sim['end_time'] if to is None else to
            if step is not None and step > 0 and b > a:
                points = js_floor((b - a) / step) + 1
                if abs((b - a) / step - js_round((b - a) / step)) > 1e-9:
                    report.warn(
                        f'An output series steps by {js_string(step)} from {js_string(a)} '
                        f'to {js_string(b)}, which '
                        f'does not divide evenly; {js_string(points)} points were used.')
        if points is None or not points >= 2:
            report.warn('An output series had no usable number of points and was dropped.')
            continue
        out.append({'kind': kind, 'points': js_round(float(points)), 'from': frm, 'to': to})
    return out


_SATURATION_OFF = re.compile('[' + _S + ']*false[' + _S + ']*', re.I | re.A)
_TIME_UNITS = {
    'second': 'second', 'seconds': 'second', 's': 'second',
    'minute': 'minute', 'minutes': 'minute',
    'hour': 'hour', 'hours': 'hour', 'h': 'hour',
    'day': 'day', 'days': 'day', 'd': 'day',
    'year': 'year', 'years': 'year', 'y': 'year', 'a': 'year',
}
_NOT_SOLVER_CHAR = re.compile('[^A-Z0-9]')


def _read_simulation_settings(data_model: Node, project: Dict[str, Any], report: ImportReport) -> None:
    """``<simulation-settings>`` and ``<probabilistic-settings>``: the time
    span and unit, the solver and tolerances, the saturation switch, the
    output times, the endpoints, and what a probabilistic run would do (read
    and kept; they do not make a run probabilistic). A file with none takes
    this tool's defaults. ``readSimulationSettings`` in ``src/io/eco.js``."""
    s = child(data_model, 'simulation-settings')
    sim = dict(DEFAULT_SIMULATION)
    if s is None:
        project['simulation'] = sim
        report.warn('No simulation settings in the file; defaults were used.')
        return

    start = child_number(s, 'start-time')
    end = child_number(s, 'end-time')
    if start is not None:
        sim['start_time'] = start
    if end is not None:
        sim['end_time'] = end
    if not sim['end_time'] > sim['start_time']:
        sim['start_time'] = 0
        sim['end_time'] = max(1, 1e5 if end is None else end)
        report.warn('The stored time span was not usable; it was reset.')

    # Ecolego's master switch over every compartment's bounds, mapped onto
    # the floor, which is the part of it there is.
    saturation = child_text(s, 'saturation-enabled')
    if saturation is not None and _SATURATION_OFF.fullmatch(saturation):
        sim['non_negative'] = False
        report.warn(
            'Saturation is switched off in this model, so no compartment is held at '
            'zero -- which is how Ecolego runs it. Each compartment keeps its own '
            '*cannot go negative* setting; none of them is consulted while the '
            'switch is off. Turn it back on under Simulation if you want the floor.')

    prob = child(data_model, 'probabilistic-settings')
    if prob is not None:
        n = to_number(child_text(prob, 'no-simulations'))
        if math.isfinite(n) and n > 0:
            sim['iterations'] = js_round(n)
        # As in the application: with no <seed>, `Number(null)` is 0, a seed.
        seed = to_number(child_text(prob, 'seed'))
        if math.isfinite(seed):
            sim['seed'] = js_round(seed)
        how = (child_text(prob, 'sampling') or '').lower()
        if how:
            sim['sampling'] = 'latin' if 'latin' in how else 'random'
        chosen = [t for t in (js_trim(n2.text or '')
                              for n2 in children(child(prob, 'probabilistic-parameters'), 'selected-parameter'))
                  if t]
        if chosen:
            sim['varied'] = chosen
        pairs = len(children(child(prob, 'correlation-matrix'), 'correlation-pair'))
        if pairs and child_text(prob, 'correlation-enabled') != 'false':
            report.warn(
                f'The model correlates {pairs} pair(s) of parameters when it samples '
                'them. This tool samples each one independently, so a probabilistic '
                "run here spreads wider than Ecolego's would.")

    unit = (child_text(s, 'time-unit') or '').lower()
    if _TIME_UNITS.get(unit):
        sim['time_unit'] = _TIME_UNITS[unit]
    elif unit:
        report.warn(f"Unrecognised time unit '{unit}'; years were assumed.")

    solver = _NOT_SOLVER_CHAR.sub('', (child_text(s, 'java-solver') or '').upper())
    if SOLVER_MAP.get(solver):
        sim['solver'] = SOLVER_MAP[solver]
        if solver not in SOLVER_EXACT:
            report.warn(
                f'The model used the {solver} solver, which this tool does not have; '
                f"{solver_name(sim['solver'])} was chosen as the closest.")

    rtol = child_number(s, 'rel-error-tolerance')
    atol = child_number(s, 'abs-error-tolerance')
    if rtol is not None and rtol > 0:
        sim['rtol'] = rtol
    if atol is not None and atol > 0:
        sim['abstol'] = atol

    if sim['start_time'] < 0:
        sim['spacing'] = 'linear'
        report.warn(
            'The simulation starts before zero, so linear output spacing was used '
            '(logarithmic time needs a non-negative start).')

    _read_output_times(s, sim, report)
    _read_endpoints(s, sim)

    type_ = (child_text(s, 'simulation-type') or '').upper()
    if type_ and type_ != 'DETERMINISTIC':
        report.warn(
            f'The model is set up for a {type_.lower()} simulation; this tool '
            'runs the deterministic case only.')

    project['simulation'] = sim


def _read_functions(data_model: Node, project: Dict[str, Any], names: _NameMapper, report: ImportReport) -> None:
    """``<function-model>``: the project's compiled user-defined functions.
    Their names and parameters come across; their bodies, compiled code in the
    archive, cannot, and the report says so. ``readFunctions`` in
    ``src/io/eco.js``."""
    model = find(data_model, 'function-model')
    if model is None:
        return
    for el in children(model, 'function'):
        original = el.attrs.get('name')
        if original is None:
            original = el.attrs.get('source-file-name')
        if original is None:
            original = 'function'
        name = names.map(original, f'fn:{original}', '', original)
        meta = child(el, 'function-metadata')
        parameters: List[str] = []
        for p in children(meta, 'parameter-metadata') if meta is not None else []:
            # The key is the identifier; the name is what the dialog showed.
            raw = p.attrs.get('key')
            if raw is None:
                raw = p.attrs.get('name')
            if raw is None:
                raw = f'p{len(parameters) + 1}'
            parameters.append(_safe_parameter(raw, parameters))
        project['functions'].append(_trim_empty({
            'name': name,
            'parameters': parameters,
            'equation': '',
            'unit': '',
            'comment': child_text(meta if meta is not None else el, 'function-description') or '',
        }))
        source = el.attrs.get('source-file-name')
        report.warn(
            f"'{original}' is a user-defined function, whose body is compiled code in the project "
            f"archive ({'a compiled source file' if source is None else source}). This tool keeps "
            f'its name and its {len(parameters)} parameter(s); write what it works out '
            'to as an equation before the model will run.')


def _rewrite_endpoint_ids(project: Dict[str, Any], block_name_by_id: Dict[str, str],
                          report: ImportReport) -> None:
    """The endpoints by the names the blocks ended up with; a repeat is not a
    fault (Ecolego writes one per index), and an id with no block behind it is
    left out, with one warning for all of them. ``rewriteEndpointIds`` in
    ``src/io/eco.js``."""
    ids = (project.get('simulation') or {}).get('endpoints')
    if not isinstance(ids, list) or not ids:
        return
    known: Set[str] = set()
    for collection in KINDS:
        for b in project.get(collection) or []:
            known.add(_qualified(b))
    out: List[str] = []
    seen: Set[str] = set()
    unresolved = 0
    for eid in ids:
        # The id first: in these files an id *is* the qualified name.
        name = eid if eid in known else _or(block_name_by_id.get(eid), eid)
        if name in seen:
            continue
        if name not in known:
            unresolved += 1
            continue
        seen.add(name)
        out.append(name)
    if out:
        project['simulation']['endpoints'] = out
    else:
        del project['simulation']['endpoints']
    if unresolved:
        report.warn(
            f"{unresolved} of the model's saved endpoints name blocks that are not in "
            'the imported model; they were left out of the endpoint list.')


def _read_endpoints(s: Node, sim: Dict[str, Any]) -> None:
    """Which blocks the model is set up to save: ``<outputs><output id>``, as
    block ids until :func:`_rewrite_endpoint_ids` names them."""
    lst = child(s, 'outputs')
    if lst is None:
        return
    ids = [i for i in (o.attrs.get('id') for o in children(lst, 'output')) if isinstance(i, str) and i]
    if ids:
        sim['endpoints'] = ids


_NON_IDENTIFIER_RUN = re.compile('[^A-Za-z0-9_]+')


def _safe_parameter(raw: Any, taken: List[str]) -> str:
    """A parameter name this tool's parser can read, kept clear of its siblings."""
    name = _NON_IDENTIFIER_RUN.sub('_', js_trim('' if raw is None else str(raw)))
    if name[:1].isascii() and name[:1].isdigit():
        name = 'p' + name
    if not name or name in RESERVED:
        name = f'p{len(taken) + 1}'
    while name in taken:
        name = f'{name}_'
    return name


# --- the archive --------------------------------------------------------------------------

#: The most one entry, and the whole archive, may expand to.
MAX_INFLATED = 256 * 1024 * 1024


class _Archive:
    """The entries of a ZIP archive, by name, most of them decompressed only
    when asked for.

    The central directory is read with :mod:`zipfile`; the data is read here,
    through each entry's local header, and inflated with :mod:`zlib`, so that
    the archive is read as the application reads it: stored and deflated
    entries only, no CRC check, a deflated ``.xml`` entry inflated up front and
    everything else on first access (an assessment's results never are), one
    decompression allowance for the whole archive, and the application's
    messages for an encrypted entry, an unsupported method and an entry that
    does not fit the archive. A name repeated in the directory keeps its first
    place and its last entry, as a JavaScript ``Map`` does.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, Any] = {}
        self.spent = 0

    def names(self) -> List[str]:
        return list(self._entries)

    def get(self, name: str) -> bytes:
        held = self._entries[name]
        if callable(held):
            held = held()
            self._entries[name] = held
        return held

    # The decompression allowance, shared by every entry.
    def check(self, name: str, size: int) -> None:
        left = MAX_INFLATED - self.spent
        if size <= left:
            return

        def mb(x: float) -> str:
            return js_string(js_round(x / 1048576))
        raise EcoImportError(
            f"'{name}' takes this archive past the {mb(MAX_INFLATED)} MB this reader "
            f'will decompress in total: {mb(self.spent)} MB have come out already and '
            f'this entry adds {mb(size)} more. No real project expands that far, so '
            'the archive is either damaged or built to exhaust memory.')

    def inflate(self, name: str, raw: bytes, expected: int) -> bytes:
        """One deflated entry, within what is left of the allowance, checked
        against the size the directory claims."""
        if expected > MAX_INFLATED:
            raise EcoImportError(
                f"'{name}' says it expands to {js_string(js_round(expected / 1048576))} MB, "
                f'past the {js_string(js_round(MAX_INFLATED / 1048576))} MB this reader will '
                'decompress. No real model is that large.')
        self.check(name, expected)
        limit = min(MAX_INFLATED, MAX_INFLATED - self.spent)
        d = zlib.decompressobj(-15)
        try:
            buf = d.decompress(raw, limit + 1)
        except zlib.error as e:
            why = str(e).split(': ', 1)[-1]
            raise EcoImportError(f"Could not decompress '{name}': {_INFLATE_MESSAGES.get(why, why)}") from e
        if len(buf) > limit:
            raise EcoImportError(
                f"Could not decompress '{name}': the entry expands to more than "
                f'{js_string(js_round(limit / 1048576))} MB, which is far larger than any real model '
                '-- the archive is either damaged or built to exhaust memory')
        if not d.eof:
            raise EcoImportError(f"Could not decompress '{name}': Compressed data ended unexpectedly")
        self.check(name, len(buf))
        self.spent += len(buf)
        if expected and len(buf) != expected:
            raise EcoImportError(
                f"'{name}' inflated to {len(buf)} bytes but the directory says "
                f'{expected}; the archive looks damaged.')
        return buf


# zlib's words for the damage the application's own inflater (src/io/inflate.js,
# which is what Node reads archives with) names the same way. Anything else in
# a damaged entry is said in zlib's words: the two decoders do not notice every
# fault at the same point, so no table could make them agree on all of them.
_INFLATE_MESSAGES = {
    'invalid block type': 'Invalid block type',
    'invalid stored block lengths': 'Stored block length check failed',
    'invalid distance too far back': 'Back-reference points before the output',
}


def _entry_name(info: zipfile.ZipInfo) -> str:
    # The application decodes every name as UTF-8, flag or no flag, and its
    # decoder drops a leading byte-order mark; zipfile reads an unflagged name
    # as CP437, which gives back the bytes it came from.
    if info.flag_bits & 0x800:
        name = info.orig_filename
    else:
        name = info.orig_filename.encode('cp437').decode('utf-8', 'replace')
    return _without_bom(name)


def _unzip(data: bytes) -> _Archive:
    """The entries of a ZIP archive; :class:`EcoImportError` for one that
    cannot be read."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except zipfile.BadZipFile as e:
        if str(e) == 'File is not a zip file':
            raise EcoImportError(
                'This does not look like a ZIP archive. An Ecolego project (.eco) is a '
                'zipped project folder; a bare model.xml should be opened directly instead.') from e
        if str(e) in ('Bad magic number for central directory', 'Truncated central directory'):
            raise EcoImportError('The central directory is damaged') from e
        raise EcoImportError(f'The archive is damaged: {e}') from e
    except (zipfile.LargeZipFile, ValueError, EOFError, OSError, UnicodeDecodeError) as e:
        raise EcoImportError(f'The archive is damaged: {e}') from e

    archive = _Archive()
    size = len(data)
    for info in infos:
        name = _entry_name(info)
        if info.flag_bits & 0x1:
            raise EcoImportError(
                f"'{name}' is encrypted. Ecolego can obfuscate a project on save; "
                're-save it without that option, or export the model, before importing.')
        if name.endswith('/'):
            continue  # a directory
        offset = info.header_offset
        if offset < 0 or offset + 30 > size:
            raise EcoImportError(
                f"'{name}' says its data begins at byte {offset}, which is "
                f'outside this {size}-byte archive.')
        if data[offset:offset + 4] != b'PK\x03\x04':
            raise EcoImportError(f"The local header for '{name}' is damaged")
        name_len = int.from_bytes(data[offset + 26:offset + 28], 'little')
        extra_len = int.from_bytes(data[offset + 28:offset + 30], 'little')
        start = offset + 30 + name_len + extra_len
        compressed = info.compress_size
        if start > size or start + compressed > size:
            raise EcoImportError(
                f"'{name}' claims {compressed} bytes from {start}, which "
                f'runs past the end of this {size}-byte archive.')
        raw = data[start:start + compressed]
        method = info.compress_type
        if method == 0:
            archive._entries[name] = _stored(raw)
        elif method == 8:
            if name.lower().endswith('.xml'):
                archive._entries[name] = archive.inflate(name, raw, info.file_size)
            else:
                archive._entries[name] = _deferred(archive, name, raw, info.file_size)
        else:
            raise EcoImportError(
                f"'{name}' uses compression method {method}, which is not supported "
                '(only stored and deflate are).')
    return archive


def _stored(raw: bytes) -> Callable[[], bytes]:
    return lambda: bytes(raw)


def _deferred(archive: _Archive, name: str, raw: bytes, expected: int) -> Callable[[], bytes]:
    return lambda: archive.inflate(name, raw, expected)
