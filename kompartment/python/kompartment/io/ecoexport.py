"""A model as an Ecolego 6 project file (``.eco``), as the application writes one.

A port of the application's ``src/io/ecoexport.js``, which is the other
direction of its Ecolego importer (``src/io/eco.js``, ported as
:mod:`kompartment.importers.eco`)::

    from kompartment.io import ecoexport

    out = ecoexport.export_eco(model)       # a Model, a project dict, or a model file's path
    out.bytes                               # the .eco archive
    out.xml                                 # model.xml
    print(out.report.summary())             # what went out, and what could not

or :meth:`kompartment.Model.to_eco` and ``Model.save('x.eco')``.

**The importer is the specification.** Everything is written the way that
reader reads it -- the archive's layout, the element and attribute names, the
block types, the spelling of every enumeration -- so a model exported and read
back is the model that went out, apart from what the report names. What
Kompartment has and an Ecolego project has no place for is left out and said
so (waste packages, events, a far-field path that is switched off, a flux summed
into an end of fewer dimensions, a block indexed by the model's own compartments
or transfers, the distributions Ecolego lacks, ...), never written in a form
Ecolego would read as something else. Where an exact translation into Ecolego's
own constructs exists it is written, and the report says which: an inflow is a
transfer from a source, a flux narrowed onto a sub-set is written over its ends'
lists with a zero rate outside it, an availability is folded into the rate, a
truncation at percentiles becomes the values they fall at, a logarithmic output
grid its list of times, and a far-field path a sub-system of its cells and the
transfers between them -- its layers laid out by the package's engine
(:mod:`kompartment.engine.pathlayout`), as a run lays them out at its start.

**The same bytes as the application.** The archive is laid out as the
application lays it out -- ``.version``, ``model.xml`` and ``views.xml`` at the
root, every entry stored, dated 1980-01-01 at midnight unless a date is given
-- and the text is built by the same rules, number for number: a double is
written as Java writes it (``1000.0``, ``1.0E-4``), with the shortest digits
that read back as it, which JavaScript and Python agree on. So for the same
model the two give the same file, byte for byte; ``tests/test_eco_export.py``
checks that through Node.
"""

from __future__ import annotations

import datetime as _dt
import math
import os
import re
import struct
import zlib
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple, Union

from ..decay import default_chains, half_life
from ..equations import EquationSyntaxError, tokenize
from ..errors import KompartmentError
from ..importers._eco_maps import (
    JS_DOT, JS_SPACE_CLASS, direction_from_eco, extreme_from_eco, interpolation_from_eco, js_round, js_trim,
    operation_from_eco, to_number,
)
from ..indexlists import (
    COMPARTMENT_LIST, SOURCE_INDEX, TARGET_INDEX, TRANSFER_LIST, derive_elements, lineage, shared_dims,
    summed_dims,
)
from ..jsmath import exp as _js_exp, log as _js_log
from ..jsonio import js_number
from ..names import RESERVED, base_name, parent_of, resolve_reference
from ..stats.pdf import PDF_KINDS, complete, quantile
from .xlsx import _utf8, _zip

__all__ = ['ExportError', 'ExportReport', 'EcoExport', 'ECOLEGO_VERSION', 'VIEWS_XML', 'export_eco',
           'export_model_xml', 'java_double', 'seconds_for', 'guid_for']


class ExportError(KompartmentError, ValueError):
    """Something that is not a model was handed to the exporter."""


#: The Ecolego format this writes: what ``.version`` says and the importer reads.
ECOLEGO_VERSION = '6.5'

#: views.xml: Ecolego's diagram, empty, since this tool's layout is not Ecolego's.
VIEWS_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<presentation-model>\n</presentation-model>\n'

#: The type each collection's blocks are written as (``SUPPORTED`` in the importer).
ECO_TYPE = {
    'parameters': 'parameter', 'compartments': 'compartment', 'expressions': 'expression',
    'functions': 'expression', 'lookups': 'lookup-table', 'index_reductions': 'index-operation',
    'block_reductions': 'aggregate', 'min_maxes': 'min-max', 'running_means': 'running-mean',
    'snapshots': 'snapshot', 'delays': 'delay', 'triggers': 'discrete-event',
}

#: The order components are written in: each collection in the model's own order.
COMPONENT_COLLECTIONS = (
    'parameters', 'compartments', 'expressions', 'functions', 'lookups',
    'index_reductions', 'block_reductions',
    'min_maxes', 'running_means', 'snapshots', 'delays', 'triggers',
)

#: Every collection of blocks, for resolving references.
ALL_COLLECTIONS = COMPONENT_COLLECTIONS + ('transfers', 'inflows', 'farfields', 'waste_packages', 'events')

#: What each collection is called in the report.
KIND_WORD = {
    'parameters': 'parameter', 'compartments': 'compartment', 'expressions': 'expression',
    'functions': 'function', 'lookups': 'lookup table', 'index_reductions': 'index operation',
    'block_reductions': 'aggregate', 'min_maxes': 'min/max', 'running_means': 'running mean',
    'snapshots': 'snapshot', 'delays': 'delay', 'triggers': 'trigger', 'transfers': 'transfer',
    'inflows': 'inflow', 'farfields': 'far-field pathway', 'waste_packages': 'waste package',
    'events': 'event',
}

#: A lookup table's interpolation rule as Ecolego spells it.
INTERPOLATION_TO_ECO = {
    'linear': 'Interpolation-Use End Values',
    'extrapolate': 'Interpolation-Extrapolation',
    'below': 'Use Input Below',
    'above': 'Use Input Above',
    'nearest': 'Use Input Nearest',
}

#: A reduction as Ecolego's enumeration spells it.
OPERATION_TO_ECO = {
    'sum': 'SUM', 'product': 'PRODUCT', 'min': 'MIN', 'max': 'MAX', 'mean': 'MEAN',
    'percentile': 'PERCENTILE',
}

#: An event's direction as Ecolego spells it.
DIRECTION_TO_ECO = {'rising': 'RIGHT', 'falling': 'LEFT', 'both': 'BOTH'}

#: The solver each of this tool's is written as.
SOLVER_TO_ECO = {
    'ndf': 'ODE15S', 'ros23': 'ODE23S', 'dp45': 'ODE45', 'qndf': 'ODE15S', 'fbdf': 'ODE15S',
    'radau5': 'RADAU5', 'trbdf2': 'ODE23TB', 'rodas5p': 'ODE23S', 'kencarp4': 'ODE15S',
    'scipy_bdf': 'ODE15S', 'scipy_radau': 'RADAU5', 'scipy_lsoda': 'ODE15S',
}

#: The three that go out and come back as themselves.
SOLVER_EXACT = frozenset(['ndf', 'ros23', 'dp45'])

#: Why each of the others is written as it is.
SOLVER_WHY = {
    'qndf': 'the same numerical differentiation formulas, which this tool reads back as ndf',
    'radau5': 'Ecolego’s Radau IIA of order 5, which this tool reads back as ndf',
    'trbdf2': 'Ecolego’s TR-BDF2, which this tool reads back as ros23',
    'fbdf': 'the nearest Ecolego has: another BDF formulation',
    'rodas5p': 'the nearest Ecolego has: its Rosenbrock solver, of lower order',
    'kencarp4': 'the nearest Ecolego has for a stiff model',
    'scipy_bdf': 'the nearest Ecolego has: the same family, a different implementation',
    'scipy_radau': 'Ecolego’s Radau IIA of order 5, which this tool reads back as ndf',
    'scipy_lsoda': 'the nearest Ecolego has for a stiff model',
}

#: How results are saved, as ``<output-options>`` spells it.
OUTPUT_OPTION = {
    'solver': 'Produce no additional output',
    'both': 'Produce additional output',
    'series': 'Produce specified output only',
}

#: Ecolego's "not set" for a time series' end: the simulation's own start or end.
D_AUTO_TEXT = '-7.92842341234234E11'

#: A floor far enough below any inventory to be none.
NO_FLOOR = '-1.0E300'

#: What Kompartment writes on the lists it makes itself: not somebody's comment, so not one left out.
BUILT_IN_COMMENT = re.compile(
    f'Every material the model knows\\.( The radionuclides among them are in {JS_DOT}+\\.)?'
    f'|The materials that have a half-life\\.|One index per element of {JS_DOT}+, kept in step with it\\.')

#: The property type an index list's predefined role is written with.
PREDEFINED_TYPE = 'se.facilia.ecolego.domain.EcolegoIndexList$PredefinedType'

#: The chemical elements in order of atomic number, for a nuclide's ``<z>``.
ELEMENT_SYMBOLS = (
    'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
    'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce '
    'Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn '
    'Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl '
    'Mc Lv Ts Og'
).split(' ')

#: The settings a model may carry that an Ecolego project has no field for.
UNCARRIED_SETTINGS = (
    'bdf', 'max_step', 'initial_step', 'max_steps', 'max_order', 'min_order', 'newton_kappa',
    'max_jac_age', 'below_tol_run', 'stagnation_tol', 'error_norm', 'matrix', 'jacobian',
    'norm_control', 'auto_abstol', 'mass_balance', 'split', 'switch_times', 'min_change_time',
    'partial', 'percentiles', 'categories', 'gsa', 'tornado_low', 'tornado_high', 'qa', 'show_mean',
)

#: Which of a block's values are equations, for finding what it reads.
EQUATION_KEYS = {
    'compartments': ('initial', 'dydt'), 'transfers': ('rate',), 'inflows': ('rate',),
    'expressions': ('equation',), 'functions': ('equation',), 'index_reductions': ('target',),
    'block_reductions': ('targets',),
    'min_maxes': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_means': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshots': ('target', 'trigger', 'initial'), 'delays': ('target', 'delay'),
    'triggers': ('first', 'second'),
}

#: The values each kind of block holds per index (``VALUE_KEYS`` in project.js).
VALUE_KEYS = {
    'compartments': ('initial', 'abstol', 'non_negative', 'dydt'),
    'transfers': ('rate', 'multiply_by_donor'), 'inflows': ('rate',),
    'expressions': ('equation',), 'parameters': ('value', 'pdf'), 'lookups': ('points',),
    'index_reductions': ('target',), 'block_reductions': ('targets',),
    'min_maxes': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_means': ('target', 'reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshots': ('target', 'trigger', 'initial'), 'delays': ('target', 'delay'),
    'triggers': ('first', 'second', 'direction'),
}

#: What each kind holds when it says nothing (``DEFAULTS`` in project.js).
VALUE_DEFAULTS = {
    'compartments': {'initial': '0', 'non_negative': True},
    'transfers': {'rate': '0', 'multiply_by_donor': True},
    'inflows': {'rate': '0'},
    'expressions': {'equation': '0'},
    'parameters': {'value': 0},
    'lookups': {'points': []},
    'index_reductions': {'target': None},
    'block_reductions': {'targets': []},
    'min_maxes': {'target': '0'},
    'running_means': {'target': '0'},
    'snapshots': {'target': '0', 'initial': '0'},
    'delays': {'target': '0', 'delay': '0'},
    'triggers': {'first': '0', 'second': '0', 'direction': 'rising'},
}

_IDENTIFIER_PATH = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*')
_SPACED_PATH = re.compile(f'[{JS_SPACE_CLASS}]*[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)*[{JS_SPACE_CLASS}]*')
_INFINITY_WORD = re.compile(f'[{JS_SPACE_CLASS}]*[+-]?infinity[{JS_SPACE_CLASS}]*', re.I)
_NUCLIDE = re.compile(r'([A-Za-z]{1,3})-?([0-9]+)')
_XML_BAD = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]')


# --- JavaScript, where the answer depends on it ---------------------------------------

class _Undefined:
    """A property that is not there: ``undefined``, which is not ``null``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return 'undefined'


_UNDEF = _Undefined()


def _get(obj: Any, key: str) -> Any:
    """``obj?.[key]``: the value, or ``undefined`` for a key or an object that is not there."""
    if isinstance(obj, Mapping):
        return obj.get(key, _UNDEF)
    return _UNDEF


def _nullish(v: Any) -> bool:
    """``v == null``."""
    return v is None or v is _UNDEF


def _or(v: Any, fallback: Any) -> Any:
    """``v ?? fallback``."""
    return fallback if _nullish(v) else v


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _truthy(v: Any) -> bool:
    """JavaScript's ToBoolean: an empty object or list is true; 0, NaN and '' are not."""
    if _nullish(v):
        return False
    if isinstance(v, bool):
        return v
    if _is_number(v):
        return not (v == 0 or v != v)
    if isinstance(v, str):
        return len(v) > 0
    return True


def _str(v: Any) -> str:
    """``String(v)``, and what a template literal makes of ``v``."""
    if v is _UNDEF:
        return 'undefined'
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, str):
        return v
    if _is_number(v):
        f = float(v)
        if f != f:
            return 'NaN'
        if math.isinf(f):
            return 'Infinity' if f > 0 else '-Infinity'
        return js_number(v)
    if isinstance(v, (list, tuple)):
        return ','.join('' if _nullish(x) else _str(x) for x in v)
    if isinstance(v, Mapping):
        return '[object Object]'
    return str(v)


def _num(v: Any) -> float:
    """``Number(v)``: ``undefined`` is NaN, ``null`` 0."""
    if v is _UNDEF:
        return math.nan
    return to_number(v)


def _js_max(a: float, b: float) -> float:
    """``Math.max(a, b)``: NaN wins, and +0 is above -0."""
    if a != a or b != b:
        return math.nan
    if a == b == 0:
        return 0.0 if (math.copysign(1, a) > 0 or math.copysign(1, b) > 0) else -0.0
    return a if a > b else b


def _js_min(a: float, b: float) -> float:
    """``Math.min(a, b)``: NaN wins, and -0 is below +0."""
    if a != a or b != b:
        return math.nan
    if a == b == 0:
        return -0.0 if (math.copysign(1, a) < 0 or math.copysign(1, b) < 0) else 0.0
    return a if a < b else b


def _index_name(i: Any) -> Any:
    """An index name, whichever of its two shapes a list holds it in (``None`` for neither)."""
    if isinstance(i, str):
        return i
    v = _get(i, 'name')
    return None if _nullish(v) else v


def _index_on(i: Any) -> bool:
    return isinstance(i, str) or _get(i, 'enabled') is not False


def _qname_of(b: Any) -> str:
    """A block's qualified name, as ``qnameOf`` writes it."""
    if _truthy(_get(b, 'system')):
        return f"{_str(_get(b, 'system'))}.{_str(_get(b, 'name'))}"
    return _str(_or(_get(b, 'name'), ''))


def _trim(v: Any) -> str:
    return js_trim(_str(v))


def _list(v: Any) -> list:
    return v if isinstance(v, list) else []


# --- the report ------------------------------------------------------------------------

class ExportReport:
    """What an export did: what was left out and why, what was written in another
    form, what was renamed, what else is worth knowing, and how many of each kind
    of thing went out. ``skipped``, ``rewritten``, ``renamed``, ``warnings`` and
    ``counts``, as the application's report has them."""

    def __init__(self) -> None:
        self.skipped: List[Dict[str, str]] = []
        self.rewritten: List[Dict[str, str]] = []
        self.renamed: List[Dict[str, str]] = []
        self.warnings: List[str] = []
        self.counts: Dict[str, int] = {}

    def skip(self, type_: str, name: str, why: str) -> None:
        entry = {'type': type_, 'name': name, 'why': why}
        if entry not in self.skipped:
            self.skipped.append(entry)

    def rewrite(self, type_: str, name: str, how: str, into: Optional[str] = None) -> None:
        """``into``, where it is given, is the sub-system the thing was written as."""
        if not any(s['type'] == type_ and s['name'] == name and s['how'] == how for s in self.rewritten):
            entry = {'type': type_, 'name': name, 'how': how}
            if into is not None:
                entry['into'] = into
            self.rewritten.append(entry)

    def rename(self, old: str, new: str) -> None:
        self.renamed.append({'from': old, 'to': new})

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    @property
    def ok(self) -> bool:
        """Nothing was left out."""
        return not self.skipped

    def summary(self) -> str:
        """A short human summary, as the application writes it."""
        c = self.counts
        parts = [f"{c['compartments']} compartment(s)", f"{c['transfers']} transfer(s)",
                 f"{c['parameters']} parameter(s)", f"{c['expressions']} expression(s)"]
        for key, word in (('functions', 'function(s)'), ('lookups', 'lookup table(s)'),
                          ('index_reductions', 'index operation(s)'), ('block_reductions', 'aggregate(s)'),
                          ('min_maxes', 'min/max block(s)'), ('running_means', 'running mean(s)'),
                          ('snapshots', 'snapshot(s)'), ('delays', 'delay(s)'),
                          ('triggers', 'discrete event(s)'), ('systems', 'sub-system(s)')):
            if c.get(key):
                parts.append(f'{c[key]} {word}')
        lines = [f"Exported {', '.join(parts)}, {c['index_lists']} index list(s), {c['nuclides']} nuclide(s)."]
        if self.skipped:
            by_type: Dict[str, int] = {}
            for s in self.skipped:
                by_type[s['type']] = by_type.get(s['type'], 0) + 1
            lines.append(f'Left out {len(self.skipped)} thing(s) an Ecolego project has no place for: '
                         + ', '.join(f'{n} {t}' for t, n in by_type.items()) + '.')
        if self.rewritten:
            lines.append(f'Wrote {len(self.rewritten)} thing(s) in the equivalent Ecolego form.')
        if self.renamed:
            lines.append('Renamed ' + ', '.join(f"{r['from']} → {r['to']}" for r in self.renamed) + '.')
        lines.extend(self.warnings)
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """The report as plain data: its lists, its counts, ``ok`` and ``summary``."""
        return {
            'skipped': [dict(s) for s in self.skipped],
            'rewritten': [dict(s) for s in self.rewritten],
            'renamed': [dict(s) for s in self.renamed],
            'warnings': list(self.warnings),
            'counts': dict(self.counts),
            'ok': self.ok,
            'summary': self.summary(),
        }

    def __repr__(self) -> str:
        return f'<ExportReport: {len(self.skipped)} left out, {len(self.rewritten)} rewritten>'


class EcoExport(NamedTuple):
    """What an export gives back: the archive, its model.xml, and the report."""

    bytes: bytes
    xml: str
    report: ExportReport


# --- the entry points -------------------------------------------------------------------

DateLike = Union[None, _dt.datetime, _dt.date, int, float]


def export_eco(model: Any, *, modified: DateLike = None) -> EcoExport:
    """A model as an Ecolego 6 project archive.

    ``model`` is a :class:`kompartment.Model`, a project dictionary, or the path
    of a model file. ``modified`` is written as the project's modification date
    and on the archive's entries; left out, the entries are dated 1980-01-01 --
    local midnight, so every time zone writes the same bytes -- and no date is
    written into the model, so the same model gives the same file.
    """
    xml, report, facts = _build_model_xml(model, modified)
    version = '\n'.join([
        f'version={ECOLEGO_VERSION}',
        'track-changes=false',
        f"ode-required={'true' if facts['states'] else 'false'}",
        f"nuclidedb-required={'true' if facts['nuclides'] else 'false'}",
        '',
    ])
    data = _zip([('.version', _utf8(version)), ('model.xml', _utf8(xml)), ('views.xml', _utf8(VIEWS_XML))],
                modified=_dt.datetime(1980, 1, 1) if modified is None else modified, compress=False)
    return EcoExport(data, xml, report)


def export_model_xml(model: Any, *, modified: DateLike = None) -> Tuple[str, ExportReport]:
    """model.xml alone, and what the export did."""
    xml, report, _ = _build_model_xml(model, modified)
    return xml, report


def _raw_of(model: Any) -> Dict[str, Any]:
    """The project dictionary as the application holds it once opened -- keys in
    today's spelling, shorthands made explicit, derived units worked out -- as a
    copy, so what was handed in is not touched."""
    from ..model import Model
    if isinstance(model, Model):
        model.settle()
        return Model(model.raw).raw
    if isinstance(model, (str, os.PathLike)):
        return Model.load(model).raw
    if not isinstance(model, Mapping):
        raise ExportError('A model is one JSON object.')
    return Model(dict(model)).raw


def _build_model_xml(model: Any, modified: DateLike) -> Tuple[str, ExportReport, Dict[str, Any]]:
    raw = _raw_of(model)
    report = ExportReport()
    ctx = _Context(raw, report)
    ctx.decide_lists()
    ctx.decide_materials()
    ctx.decide_blocks()
    ctx.check_names()

    w = _XmlWriter()
    w.open('data-model')
    _write_project_properties(w, raw, ctx, modified)
    _write_materials(w, ctx)
    _write_index_lists(w, ctx)
    _write_decay_chains(w, ctx)
    _write_hierarchy(w, ctx)
    _write_blocks(w, ctx)
    _write_simulation(w, raw, ctx)
    _write_probabilistic(w, raw, ctx)
    w.close('data-model')

    report.counts = ctx.counts()
    return w.document(), report, {'states': ctx.has_states(), 'nuclides': len(ctx.nuclide_names)}


# --- what the model holds, worked out once -----------------------------------------------

class _Context:
    def __init__(self, raw: Dict[str, Any], report: ExportReport) -> None:
        self.raw = raw
        self.report = report
        self.project_name = _trim(_or(raw.get('name'), '')) or 'model'
        self.lists: List[Any] = _list(raw.get('index_lists'))
        self.blocks: Dict[str, Dict[str, Any]] = {}
        for collection in ALL_COLLECTIONS:
            for block in _list(raw.get(collection)):
                if not isinstance(block, dict):
                    continue
                q = _qname_of(block)
                if q not in self.blocks:
                    self.blocks[q] = {'collection': collection, 'block': block}
        self.skipped_blocks: Dict[str, str] = {}
        self.flux_plans: Dict[str, Dict[str, Any]] = {}
        self.boundaries: List[Dict[str, str]] = []
        self.paths: Optional[List[str]] = None
        #: Far-field paths that go out as cells, what they are written as, and the
        #: plans of the transfers between their cells (``farPaths`` and the rest).
        self.far_paths: Dict[str, Dict[str, str]] = {}
        self.generated: Dict[str, List[Dict[str, Any]]] = {
            'parameters': [], 'compartments': [], 'expressions': [], 'block_reductions': [], 'transfers': []}
        self.generated_plans: Dict[str, Dict[str, Any]] = {}
        self.generated_systems: List[str] = []
        self.layouts: Optional[Dict[str, Dict[str, Any]]] = None
        self.used_names: Dict[str, set] = {}
        self.expanded_entries = 0
        self.dropped_entries = 0
        self.list_comments = 0

    def known(self, name: Any) -> bool:
        return isinstance(name, str) and name in self.blocks

    # --- index lists ---------------------------------------------------------------

    def decide_lists(self) -> None:
        report = self.report
        self.material = next((l for l in self.lists if _truthy(_get(l, 'for_contaminants'))), None)
        self.nuclide_list = next((l for l in self.lists if _truthy(_get(l, 'for_nuclides'))), None)
        self.nuclide_list_name = _or(_get(self.nuclide_list, 'name'), _or(_get(self.material, 'name'), None))

        self.auto_lists: set = set()
        out: List[Dict[str, Any]] = []
        for lst in self.lists:
            if not isinstance(lst, dict):
                continue
            if _truthy(lst.get('auto')) or (_truthy(lst.get('derived'))
                                           and lst.get('name') in (COMPARTMENT_LIST, TRANSFER_LIST)):
                self.auto_lists.add(lst.get('name'))
                continue
            out.append(lst)
        for name in (COMPARTMENT_LIST, TRANSFER_LIST):
            if not any(l.get('name') == name for l in out):
                self.auto_lists.add(name)
        elements = next((l for l in out if _truthy(l.get('for_elements'))), None)
        self.all_lists: List[Any] = self.lists
        if elements is None:
            derived = next((l for l in derive_elements(self.lists)
                            if _truthy(l.get('derived')) and _truthy(l.get('for_elements'))), None)
            if derived is not None:
                elements = derived
                out.append(derived)
                self.all_lists = [*self.lists, derived]
        self.element_list = elements
        self.export_lists = out

        self.list_ids: Dict[Any, str] = {}
        taken = {l.get('name') for l in out}
        for lst in out:
            name = lst.get('name')
            lid = name
            if lst is self.material and name != 'Materials' and 'Materials' not in taken:
                lid = 'Materials'
                report.rename(_str(name), 'Materials')
            self.list_ids[name] = lid

        self.index_ids: Dict[Any, Dict[Any, str]] = {}
        for lst in out:
            ids: Dict[Any, str] = {}
            used: set = set()
            for raw_index in _list(lst.get('indices')):
                name = _index_name(raw_index)
                if name is None or _hashable(name) in ids:
                    continue
                base = js_trim(_str(name)).replace(',', '_')
                if base == '':
                    base = 'index'
                iid = base
                n = 2
                while iid in used:
                    iid = f'{base}_{n}'
                    n += 1
                used.add(iid)
                ids[_hashable(name)] = iid
                if _str(name) != js_trim(_str(name)):
                    report.warn(f"The index '{_str(name)}' of '{_str(lst.get('name', _UNDEF))}' begins or ends "
                                'with a space, which an .eco file does not keep: it is read back without it.')
            self.index_ids[lst.get('name')] = ids

        for flag, word in (('for_scenarios', 'scenarios'), ('for_elements', 'elements')):
            if any(_truthy(l.get(flag)) for l in out):
                continue
            named = next((l for l in out if js_trim(_str(l.get('name', _UNDEF))).lower() == word
                          and not _truthy(l.get('for_contaminants')) and not _truthy(l.get('for_nuclides'))), None)
            if named is not None:
                report.warn(f"'{_str(named.get('name', _UNDEF))}' is not this model's {word[:-1]} dimension, but a "
                            'list of that name with no other list marked as one is read as it when the file is '
                            'imported. Rename it if that is not what it is.')

    def indices_of(self, list_name: Any) -> List[Any]:
        lst = next((l for l in self.export_lists if l.get('name') == list_name), None)
        return [n for n in (_index_name(i) for i in _list(_get(lst, 'indices'))) if n is not None]

    def auto_dim_of(self, dims: Sequence[Any]) -> Any:
        return next((d for d in dims if _hashable(d) in self.auto_lists), None)

    def list_id(self, name: Any) -> str:
        return self.list_ids.get(name, _str(name)) if _hashable(name) is name else _str(name)

    def index_id(self, list_name: Any, name: Any) -> str:
        ids = self.index_ids.get(list_name) if _hashable(list_name) is list_name else None
        if ids is not None and _hashable(name) in ids:
            return ids[_hashable(name)]
        return _str(name)

    # --- materials -------------------------------------------------------------------

    def decide_materials(self) -> None:
        raw, report = self.raw, self.report
        overrides = raw.get('half_lives') if isinstance(raw.get('half_lives'), dict) else {}
        in_nuclides = {_hashable(_index_name(i)) for i in _list(_get(self.nuclide_list, 'indices'))}

        def half(name: str) -> Optional[float]:
            if name in overrides and overrides[name] is not None:
                v = overrides[name]
                if (isinstance(v, float) and math.isinf(v) and v > 0) or \
                        js_trim(_str(v)).lower() in ('stable', 'inf', 'infinity'):
                    return math.inf
                n = _num(v)
                if math.isfinite(n) and n > 0:
                    return n
            db = half_life(name)
            return db

        self.materials: List[Dict[str, Any]] = []
        catalogue = [n for n in (_index_name(i) for i in _list(_get(self.material, 'indices'))) if n is not None]
        units: Dict[Any, str] = {}
        for i in _list(_get(self.material, 'indices')):
            if isinstance(i, dict) and js_trim(_str(_or(i.get('unit', _UNDEF), ''))):
                units[_hashable(i.get('name', _UNDEF))] = js_trim(_str(i.get('unit')))
        for name in catalogue:
            years = half(name) if isinstance(name, str) else None
            nuclide = _hashable(name) in in_nuclides or (years is not None and math.isfinite(years))
            self.materials.append({'name': name, 'nuclide': nuclide, 'years': years if nuclide else None,
                                   'unit': units.get(_hashable(name), '')})
        self.nuclide_names = [m['name'] for m in self.materials if m['nuclide']]
        listed = [n for n in (_index_name(i) for i in _list(_get(self.nuclide_list, 'indices'))) if n is not None]
        listed = list(dict.fromkeys(_hashable(n) for n in listed))
        added = [n for n in self.nuclide_names if _hashable(n) not in in_nuclides]
        if added and self.nuclide_list is not None:
            one = len(added) == 1
            report.warn(f"{', '.join(_str(n) for n in added)} {'decays' if one else 'decay'} and "
                        f"{'is' if one else 'are'} not in '{_str(self.nuclide_list.get('name', _UNDEF))}'. Ecolego's "
                        "radionuclide list holds every material that decays, so the file's does.")
        catalogue_keys = [_hashable(n) for n in catalogue]
        outside = [n for n in listed if n not in catalogue_keys]
        if outside:
            one = len(outside) == 1
            report.warn(f"'{_str(self.nuclide_list.get('name', _UNDEF))}' names {', '.join(_str(n) for n in outside)}, "
                        f"which {'is' if one else 'are'} not in the catalogue of materials; "
                        f"{'it was' if one else 'they were'} left out of it.")

        nuclides = {_hashable(n) for n in self.nuclide_names}
        ceiling = _num(_get(raw.get('simulation'), 'decay_ceiling'))
        stated = raw.get('chains') if isinstance(raw.get('chains'), list) else None
        if stated is not None:
            pairs = [[_str(_get_index(p, 0)), _str(_get_index(p, 1)),
                      1 if _get_index(p, 2) is _UNDEF else _num(_get_index(p, 2))]
                     for p in stated if isinstance(p, list)]
        else:
            names = [n for n in catalogue if isinstance(n, str)]
            pairs = [list(p) for p in default_chains(names, ceiling if math.isfinite(ceiling) and ceiling > 0
                                                     else math.inf)]
        self.chains = [p for p in pairs if p[0] in nuclides and p[1] in nuclides]
        dropped = len(pairs) - len(self.chains)
        if stated is not None and dropped:
            report.rewrite('decay chain', f'{dropped} pair(s)', 'name nuclides the model does not '
                           'carry, so they took no part in its run and were not written')

    # --- blocks ----------------------------------------------------------------------

    def decide_blocks(self) -> None:
        raw, report = self.raw, self.report

        def skip(q: str, why: str) -> None:
            if q not in self.skipped_blocks:
                self.skipped_blocks[q] = why

        for b in _list(raw.get('farfields')):
            if isinstance(b, dict):
                why = self.path_problem(b)
                if why:
                    skip(_qname_of(b), why)
        for b in _list(raw.get('waste_packages')):
            if isinstance(b, dict):
                skip(_qname_of(b), 'waste packages and their barriers have no Ecolego block')
        for b in _list(raw.get('events')):
            if isinstance(b, dict):
                skip(_qname_of(b), 'a disruptive event and what it does to the model have no Ecolego equivalent')
        for collection in COMPONENT_COLLECTIONS:
            for b in _list(raw.get(collection)):
                if not isinstance(b, dict):
                    continue
                q = _qname_of(b)
                dims = _list(b.get('index_lists'))
                auto = self.auto_dim_of(dims)
                if auto is not None:
                    skip(q, f"it is indexed by '{_str(auto)}', a list made of the model's own blocks, which "
                            'Ecolego has no equivalent for')
                    continue
                if collection == 'functions' and not (isinstance(b.get('parameters'), list)
                                                      and any(js_trim(_str(_or(p, ''))) for p in b['parameters'])):
                    skip(q, 'a function with no parameters would be read as an expression, and its calls would '
                            'not parse')
                    continue
                if collection == 'lookups':
                    if _interpolation_to_eco(_lookup_rule(b.get('interpolation', _UNDEF))) is None:
                        skip(q, f"its interpolation rule '{_str(b.get('interpolation', _UNDEF))}' is not one "
                                'Ecolego has')
                        continue
                if self.uses_ends(b, collection):
                    skip(q, f"it reads '{SOURCE_INDEX}' or '{TARGET_INDEX}', which only a transfer here can")
        compartment_names = {_qname_of(c) for c in _list(raw.get('compartments'))}
        for collection in ('transfers', 'inflows'):
            for t in _list(raw.get(collection)):
                if not isinstance(t, dict):
                    continue
                q = _qname_of(t)
                why = self.flux_problem(t, collection, compartment_names)
                if why:
                    skip(q, why)
        self.fall(skip)

        # A far-field path's layers are laid out by a run, of the model as it
        # goes out -- so after everything else that is left out has fallen.
        if any(isinstance(b, dict) and _qname_of(b) not in self.skipped_blocks for b in _list(raw.get('farfields'))):
            from ..engine.pathlayout import path_layouts
            self.layouts = path_layouts(self.going_out())
            fell = False
            for b in _list(raw.get('farfields')):
                if not isinstance(b, dict):
                    continue
                q = _qname_of(b)
                if q in self.skipped_blocks:
                    continue
                layout = self.layouts.get(q)
                why = ('it takes no part in a run -- its sub-system is switched off -- so it has no layers to lay out'
                       if layout is None else f"its matrix layers cannot be laid out: {layout['error']}"
                       if 'error' in layout else None)
                if why:
                    skip(q, why)
                    fell = True
            if fell:
                self.fall(skip)

        for q, why in self.skipped_blocks.items():
            found = self.blocks.get(q)
            report.skip(KIND_WORD.get(found['collection']) if found else 'block', q, why)
        # The paths first: the transfers into and out of one are written to what it became.
        self.plan_paths()
        self.plan_fluxes()

    def fall(self, skip: Any) -> None:
        """Everything that reads what is left out, until nothing more falls."""
        while True:
            fell = False
            for q, found in list(self.blocks.items()):
                if q in self.skipped_blocks:
                    continue
                collection, block = found['collection'], found['block']
                if collection in ('waste_packages', 'events'):
                    continue
                lost = self.reads_skipped(block, collection)
                if lost:
                    skip(q, f"it reads '{lost}', which is left out")
                    fell = True
                    continue
                if collection in ('transfers', 'inflows'):
                    end = next((e for e in (block.get('from', _UNDEF), block.get('to', _UNDEF))
                                if not _nullish(e) and self.resolve_end(e, block) in self.skipped_blocks), _UNDEF)
                    if not _nullish(end):
                        skip(q, f"it connects to '{_str(end)}', which is left out")
                        fell = True
            if not fell:
                break

    def going_out(self) -> Dict[str, Any]:
        """The model as it goes out: what is left out taken away, and the endpoints that named it."""
        out = dict(self.raw)
        for collection in ALL_COLLECTIONS:
            if isinstance(out.get(collection), list):
                out[collection] = [b for b in out[collection]
                                   if not (isinstance(b, dict) and _qname_of(b) in self.skipped_blocks)]
        sim = out.get('simulation')
        if isinstance(sim, dict) and isinstance(sim.get('endpoints'), list):
            out['simulation'] = {**sim, 'endpoints': [n for n in sim['endpoints'] if _str(n) not in self.skipped_blocks]}
        return out

    # --- far-field paths -------------------------------------------------------------------

    def path_problem(self, b: Dict[str, Any]) -> Optional[str]:
        """Why a far-field path cannot go out as cells, as far as the path itself says (``pathProblem``)."""
        from ..engine.farfield import FARF_METHODS, is_semi_analytic, structure_problem, uses_cells
        from ..engine.pathlayout import cell_equivalent
        dims = _list(b.get('index_lists'))
        auto = self.auto_dim_of(dims)
        if auto is not None:
            return (f"it is indexed by '{_str(auto)}', a list made of the model's own blocks, which Ecolego has "
                    'no equivalent for')
        if not uses_cells(b) and not is_semi_analytic(b):
            return f"'{_str(b.get('method', _UNDEF))}' is not a way this tool works a path out ({', '.join(FARF_METHODS)})"
        bad = structure_problem(cell_equivalent(b))
        if bad:
            return f'its cells cannot be laid out: {bad}'
        if b.get('enabled') is False:
            return ('it is switched off, and a path that takes no part in a run has no layers to lay out; switch it '
                    'on to have it written')
        return None

    def names_in(self, system: str) -> set:
        """Names taken in a sub-system: its blocks, its own sub-systems, and what has been added to it."""
        if system not in self.used_names:
            names = set()
            for q in self.blocks:
                if parent_of(q) == system:
                    names.add(base_name(q))
            for path in self.system_paths_list():
                if parent_of(path) == system:
                    names.add(base_name(path))
            self.used_names[system] = names
        return self.used_names[system]

    def claim_name(self, system: str, base: str, avoid: Optional[set] = None) -> str:
        """A name not yet taken in ``system``, as close to ``base`` as can be, and taken now."""
        names = self.names_in(system)

        def free(n: str) -> bool:
            return n not in names and not (avoid is not None and n in avoid) and n not in RESERVED

        name = base
        k = 2
        while not free(name):
            name = f'{base}_{k}'
            k += 1
        names.add(name)
        return name

    def respell(self, text: Any, source: str, target: str) -> str:
        """An equation written in ``source``, spelled so that it means the same from ``target``."""
        src = _str(_or(text, ''))
        try:
            toks = tokenize(src)
        except EquationSyntaxError:
            return src
        out = ''
        at = 0
        for k, t in enumerate(toks):
            if t.type != 'ident':
                continue
            if k + 1 < len(toks) and toks[k + 1].type == 'lparen' and t.text in RESERVED:
                continue
            q = resolve_reference(t.text, source, self.known)
            if q is None:
                continue
            spelled = self.reference_from(q, target)
            if spelled == t.text:
                continue
            out += src[at:t.pos] + spelled
            at = t.pos + len(t.text)
        return out + src[at:]

    def generate(self, collection: str, block: Dict[str, Any]) -> str:
        """Adds a block that stands for part of a path, where every reference can find it."""
        self.generated[collection].append(block)
        q = _qname_of(block)
        if q not in self.blocks:
            self.blocks[q] = {'collection': collection, 'block': block, 'generated': True}
        return q

    def plan_paths(self) -> None:
        for b in _list(self.raw.get('farfields')):
            if not isinstance(b, dict) or _qname_of(b) in self.skipped_blocks:
                continue
            self.plan_path(b)
        self.paths = None

    def plan_path(self, b: Dict[str, Any]) -> None:
        """One path, as what it is on the grid (``planPath``)."""
        from ..engine.farfield import FARF_DEFAULTS, FARF_NUCLIDE_KEYS, FARF_SURFACE_DEFAULTS, effective_structure, \
            is_semi_analytic, surface_of
        from ..engine.pathlayout import cell_equivalent
        q = _qname_of(b)
        system = _str(_or(b.get('system', _UNDEF), ''))
        layout = self.layouts[q]
        cells = cell_equivalent(b)
        g = effective_structure(cells)
        nf, nm = g['n_f'], g['n_m']
        NF = nf + g['n_b']
        dims = list(_list(b.get('index_lists')))
        other_dims = list(layout['other_dims'])
        nuclide = next((d for d in dims if d not in other_dims), None)
        matched = layout['grid'] == 'matched'
        sim = self.raw.get('simulation') if isinstance(self.raw.get('simulation'), dict) else {}
        time = sim.get('time_unit') if sim.get('time_unit') in ('second', 'minute', 'hour', 'day', 'year') else 'year'
        per_time = f'1/{time}'

        name = _str(b.get('name', _UNDEF))
        sub = f"{system}.{self.claim_name(system, f'{name}_cells')}" if system else self.claim_name('', f'{name}_cells')
        self.generated_systems.append(sub)
        self.paths = None
        self.used_names[sub] = set()
        settings = _written_settings(b)
        avoid: set = set()

        def read(text: Any) -> None:
            try:
                toks = tokenize(_str(_or(text, '')))
            except EquationSyntaxError:
                return
            for t in toks:
                if t.type == 'ident':
                    avoid.add(t.text)

        for key in settings:
            read(b.get(key, _UNDEF))
            for e in _list(b.get('entries')):
                if isinstance(e, dict) and key in e:
                    read(e[key])

        def local(base: str) -> str:
            return self.claim_name(sub, base, avoid)

        def at(n: str) -> str:
            return f'{sub}.{n}'

        surface = surface_of(b)
        N: Dict[str, str] = {}
        for key in settings:
            N[key] = local(_SETTING_NAME[key])
            given = b.get(key, _UNDEF)
            default = given if not _nullish(given) else FARF_SURFACE_DEFAULTS.get(key, FARF_DEFAULTS.get(key, '0'))
            entries = []
            for e in _list(b.get('entries')):
                if not isinstance(e, dict) or key not in e:
                    continue
                index = _entry_index(e.get('index', _UNDEF), dims, self.nuclide_list_name)
                if index is None:
                    continue
                entries.append({'index': index, 'equation': self.respell(e[key], system, sub)})
            block = {'name': N[key], 'system': sub,
                     'index_lists': list(dims) if key in FARF_NUCLIDE_KEYS else list(other_dims),
                     'equation': self.respell(default, system, sub)}
            if entries:
                block['entries'] = entries
            block['comment'] = f"{_SETTING_COMMENT[key].replace('[time]', time)}. {q}'s own setting."
            self.generate('expressions', block)

        def expr(n: str, equation: str, over: Sequence[Any], **extra: Any) -> str:
            return self.generate('expressions', {'name': n, 'system': sub, 'index_lists': list(over),
                                                 'equation': equation, **extra})

        aw = N['aw'] if surface == 'aw' else local('a_w')
        if surface != 'aw':
            expr(aw, f"2 / {N['aperture']}" if surface == 'aperture' else f"{N['f']} / {N['tw']}", other_dims,
                 unit='m2/m3', comment='The flow-wetted surface per unit volume of flowing water.')
        fdf = local('f_df')
        expr(fdf, f"1 / (1 + {N['kd_f']} * {aw})", dims,
             comment='The fraction dissolved in the fracture water rather than sorbed on its coating.')
        rm = local('R_m')
        expr(rm, f"{N['eps_m']} + {N['rho_m']} * {N['kd_m']}", dims,
             comment='The matrix’s capacity for the nuclide: its porosity, and what sorbs.')
        adv = local('adv')
        expr(adv, f"{fdf} * {nf} / {N['tw']}", dims, unit=per_time,
             comment=f'Advection from one fracture cell to the next: {nf} cells along the travel time.')
        disp = local('disp')
        expr(disp, f"max(0, {adv} * ({nf} / {N['pe']} - 0.5))", dims, unit=per_time,
             comment=(f'Dispersion between neighbouring fracture cells. {nf} cells already disperse as a Peclet '
                      f'number of {2 * nf} would, so this is what is added to that, and never less than nothing.'))

        def geometry(prefix: str, pick: Any, what: str) -> List[str]:
            names = []
            for j in range(nm):
                n = local(f'{prefix}_{j + 1}')
                value = pick(layout['combos'][0])[j]
                entries = [{'index': dict(c['index']), 'value': pick(c)[j]}
                           for c in layout['combos'][1:] if pick(c)[j] != value]
                block = {'name': n, 'system': sub, 'index_lists': list(other_dims), 'value': value, 'unit': 'm'}
                if entries:
                    block['entries'] = entries
                if j == 0:
                    block['comment'] = what
                self.generate('parameters', block)
                names.append(n)
            return names

        d = geometry('d', lambda c: c['d'], 'The matrix layers’ thicknesses, from the fracture wall inwards, as a '
                     'run here lays them out at its start' + (', matched to diffusion into the rock' if matched else '')
                     + '.')
        h = geometry('h', lambda c: c['h'], 'The node spacings the matched layers exchange over: the wall to the '
                     'first layer’s node, then node to node.') if matched else []
        symbol_names = [adv, disp, local('k_fm'), local('k_mf')]
        symbol_names += [local(f'k_{j + 1}_{j + 2}') for j in range(nm - 1)]
        symbol_names += [local(f'k_{j + 2}_{j + 1}') for j in range(nm - 1)]
        kfm, kmf = symbol_names[2], symbol_names[3]
        de = N['de_m']

        def layer_note(j: int) -> Dict[str, str]:
            return ({'comment': 'Diffusion through the rock: from one matrix layer into the next one in, and, below, '
                                'back out.'} if j == 0 else {})

        if matched:
            expr(kfm, f'{fdf} * {aw} * {de} / {h[0]}', dims, unit=per_time,
                 comment='From a fracture cell into its first matrix layer.')
            expr(kmf, f'{de} / ({rm} * {d[0]} * {h[0]})', dims, unit=per_time,
                 comment='From the first matrix layer back into its fracture cell.')
            for j in range(nm - 1):
                expr(symbol_names[4 + j], f'{de} / ({rm} * {d[j]} * {h[j + 1]})', dims, unit=per_time, **layer_note(j))
            for j in range(nm - 1):
                expr(symbol_names[4 + nm - 1 + j], f'{de} / ({rm} * {d[j + 1]} * {h[j + 1]})', dims, unit=per_time)
        else:
            expr(kfm, f'{fdf} * 2 * {aw} * {de} / {d[0]}', dims, unit=per_time,
                 comment='From a fracture cell into its first matrix layer.')
            expr(kmf, f'2 * {de} / ({rm} * {d[0]} * {d[0]})', dims, unit=per_time,
                 comment='From the first matrix layer back into its fracture cell.')
            for j in range(nm - 1):
                expr(symbol_names[4 + j], f'2 * {de} / ({rm} * {d[j]} * ({d[j]} + {d[j + 1]}))', dims, unit=per_time,
                     **layer_note(j))
            for j in range(nm - 1):
                expr(symbol_names[4 + nm - 1 + j], f'2 * {de} / ({rm} * {d[j + 1]} * ({d[j + 1]} + {d[j]}))', dims,
                     unit=per_time)

        # The cells, in the path's own order: each fracture cell, then its layers.
        decays = b.get('handle_decay') is not False and nuclide is not None
        inventory = _inventory_unit(b.get('unit', _UNDEF), time) or (
            ('mol' if self.raw.get('decay_unit') == 'mol' else 'Bq') if nuclide is not None else '')
        cell_name: List[str] = [''] * (NF * (nm + 1))
        for k in range(NF):
            past = bool(g['downstream']) and k == nf
            cell_name[k * (nm + 1)] = local(f'F{k + 1}')
            block = {'name': cell_name[k * (nm + 1)], 'system': sub, 'index_lists': list(dims),
                     'initial': '0', 'non_negative': False, 'handle_decay': decays}
            if inventory:
                block['unit'] = inventory
            if k == 0:
                block['comment'] = f'The first fracture cell of {q}: what flows into the path arrives here.'
            elif past:
                block['comment'] = (f"The first of the {g['n_b']} cells past the release point, which stand for the "
                                    'rock downstream: what they hold has been released already.')
            self.generate('compartments', block)
            for j in range(1, nm + 1):
                cell_name[k * (nm + 1) + j] = local(f'M{k + 1}_{j}')
                block = {'name': cell_name[k * (nm + 1) + j], 'system': sub, 'index_lists': list(dims),
                         'initial': '0', 'non_negative': False, 'handle_decay': decays}
                if inventory:
                    block['unit'] = inventory
                self.generate('compartments', block)

        # The rates between them, and out of the far end.
        net = _path_network(cells)
        outflow = local('Outflow')
        outflow_id = at(outflow)
        self.boundaries.append({'name': outflow, 'id': outflow_id, 'system': sub, 'type': 'sink'})
        count = 0
        for tr in net['transfers']:
            source = cell_name[tr['from']]
            target = outflow if tr['to'] is None else cell_name[tr['to']]
            tname = local(f'{source}_to_{target}')
            tq = self.generate('transfers', {
                'name': tname, 'system': sub, 'from': at(source), 'to': None if tr['to'] is None else at(target),
                'index_lists': list(dims), 'rate': _terms_text(tr['terms'], symbol_names), 'multiply_by_donor': True,
                'unit': per_time})
            plan = {'collection': 'transfers', 'from': at(source), 'to': None if tr['to'] is None else at(target),
                    'dims': list(dims), 'file_dims': list(dims), 'intersection': False, 'narrowed': None,
                    'availability': None}
            if tr['to'] is None:
                plan['sink'] = outflow_id
            self.generated_plans[tq] = plan
            count += 1

        # The release, which is what the rest of the model reads the path as.
        release = local('release')
        unit = js_trim(_str(_or(b.get('unit', _UNDEF), '')))
        rel = net['release']
        extra: Dict[str, Any] = {'unit': unit} if unit else {}
        extra['comment'] = (f"The flux across the release point, between {cell_name[rel[0]['cell']]} and "
                            f"{cell_name[rel[1]['cell']]}." if g['n_b'] > 0
                            else 'The flux out of the far end of the path, as its outflow condition reads it.')
        expr(release, ''.join(_weighted(r['terms'], symbol_names, cell_name[r['cell']], i == 0)
                              for i, r in enumerate(rel)), dims, **extra)
        # What the path holds -- the other half of a mass balance with its release.
        held = local('held')
        block = {'name': held, 'system': sub, 'index_lists': list(dims), 'operation': 'sum',
                 'targets': cell_name[:(nf if g['downstream'] else NF) * (nm + 1)]}
        if inventory:
            block['unit'] = inventory
        block['comment'] = (f"What {q} holds: every cell{' up to the release point' if g['downstream'] and g['n_b'] else ''}"
                            ', fracture and rock.')
        self.generate('block_reductions', block)
        block = {'name': name, 'system': system, 'index_lists': list(dims),
                 'equation': self.reference_from(at(release), system)}
        if unit:
            block['unit'] = unit
        comment = js_trim(_str(_or(b.get('comment', _UNDEF), '')))
        if comment:
            block['comment'] = comment
        self.generate('expressions', block)

        inlet = at(cell_name[0])
        self.far_paths[q] = {'q': q, 'sub': sub, 'inlet': inlet}
        ncells = NF * (nm + 1)
        past = f" and {g['n_b']} past the release point" if g['n_b'] else ''
        per = f', per {nuclide}' if nuclide is not None else ''
        spacings = f', and the node spacings {h[0]} … {h[nm - 1]}' if matched else ''
        downstream = (f". The {g['n_b']} cells past the release point stand for the rock downstream: what they hold "
                      'has been released already, so a total over the sub-system counts it twice'
                      if g['downstream'] and g['n_b'] else '')
        self.report.rewrite(KIND_WORD['farfields'], q, (
            f'written as the sub-system {sub}: {ncells} compartments -- {nf} fracture cells{past}, each with {nm} '
            f'matrix layers behind it -- and the {count} transfers between them{per}. Its settings and the rates '
            f'worked out from them are expressions there; its release is the expression {q}, and what it holds the '
            f'aggregate {at(held)}. The layers are written as the thicknesses a run here lays out at its start '
            f'({d[0]} … {d[nm - 1]}{spacings}, in m), which Ecolego keeps whatever the settings do during a run or '
            f'from one realisation to the next{downstream}'), sub)
        if is_semi_analytic(b):
            self.report.warn(f"'{q}' is worked out semi-analytically here, from its transfer function, which Ecolego "
                             f'has nothing like. It is written as the same path on cells -- {nf} × {nm}, with the rock '
                             'going on past the release point -- which agrees with the exact answer only as closely '
                             'as those cells do.')

    def resolve_end(self, ref: Any, conn: Any) -> Any:
        if _nullish(ref):
            return None
        if self.known(ref):
            return ref
        system = _or(_get(conn, 'system'), '')
        found = resolve_reference(_str(ref), _str(system), self.known) if isinstance(ref, str) else None
        return ref if found is None else found

    def uses_ends(self, block: Dict[str, Any], collection: str) -> bool:
        for text in self.equations_of(block, collection):
            try:
                toks = tokenize(text)
            except EquationSyntaxError:
                continue
            for t in toks:
                if t.type == 'index' and js_trim(t.text) in (SOURCE_INDEX, TARGET_INDEX):
                    return True
        return False

    def equations_of(self, block: Dict[str, Any], collection: str) -> List[str]:
        # A path's are the settings that go into the file as equations.
        keys = _written_settings(block) if collection == 'farfields' else EQUATION_KEYS.get(collection, ())
        out: List[str] = []

        def take(holder: Any) -> None:
            for k in keys:
                v = _get(holder, k)
                if isinstance(v, list):
                    out.extend(x for x in v if isinstance(x, str))
                elif isinstance(v, str):
                    out.append(v)

        take(block)
        for e in _list(block.get('entries')):
            take(e)
        a = block.get('availability')
        if isinstance(a, dict):
            for k in ('limit', 'top', 'bottom'):
                if isinstance(a.get(k), str):
                    out.append(a[k])
        return out

    def reads_skipped(self, block: Dict[str, Any], collection: str) -> Optional[str]:
        system = _str(_or(block.get('system', _UNDEF), ''))
        params = block.get('parameters')
        locals_ = ({js_trim(_str(_or(p, ''))) for p in params}
                   if collection == 'functions' and isinstance(params, list) else None)
        for text in self.equations_of(block, collection):
            try:
                toks = tokenize(text)
            except EquationSyntaxError:
                continue
            for k, t in enumerate(toks):
                if t.type != 'ident':
                    continue
                if k + 1 < len(toks) and toks[k + 1].type == 'lparen' and t.text in RESERVED:
                    continue
                if locals_ is not None and t.text in locals_:
                    continue
                q = resolve_reference(t.text, system, self.known)
                if q is not None and q in self.skipped_blocks:
                    return q
        return None

    def end_dims(self, ref: Any, conn: Any) -> Optional[List[Any]]:
        if _nullish(ref):
            return None
        q = self.resolve_end(ref, conn)
        found = self.blocks.get(q) if isinstance(q, str) else None
        if not found:
            return None
        return _list(found['block'].get('index_lists'))

    def is_path_end(self, ref: Any, conn: Any) -> bool:
        """Whether a connection's end is a far-field path."""
        if _nullish(ref):
            return False
        q = self.resolve_end(ref, conn)
        found = self.blocks.get(q) if isinstance(q, str) else None
        return bool(found) and found['collection'] == 'farfields'

    def flux_problem(self, t: Dict[str, Any], collection: str, compartments: set) -> Optional[str]:
        ends = ([None, t.get('to', _UNDEF)] if collection == 'inflows'
                else [_or(t.get('from', _UNDEF), None), _or(t.get('to', _UNDEF), None)])
        for ref, what in ((ends[0], 'donor'), (ends[1], 'receiver')):
            if _nullish(ref):
                continue
            q = self.resolve_end(ref, t)
            if q in compartments:
                continue
            found = self.blocks.get(q) if isinstance(q, str) else None
            if found and found['collection'] == 'farfields':
                # Written as its cells, and so an end like any other.
                if q not in self.skipped_blocks:
                    continue
                return f"its {what} is the far-field pathway '{_str(q)}', which is left out"
            if found and found['collection'] == 'waste_packages':
                return f"its {what} is the waste package '{_str(q)}', which is left out"
            return f"its {what} '{_str(ref)}' is not a compartment of this model"
        # What a transfer out of a path carries is its release, which takes
        # nothing from the path: a flux from outside.
        if self.is_path_end(ends[0], t):
            ends = [None, ends[1]]
        if _nullish(ends[0]) and _nullish(ends[1]):
            return 'it has neither a donor nor a receiver'
        dims = _list(t.get('index_lists'))
        auto = self.auto_dim_of(dims)
        if auto is not None:
            return (f"it is indexed by '{_str(auto)}', a list made of the model's own blocks, which Ecolego "
                    'has no equivalent for')
        source = self.end_dims(ends[0], t)
        target = self.end_dims(ends[1], t)
        if t.get('sum_extra_indices') is True or t.get('sum_extra_indices') == 'true':
            extra = ((summed_dims(self.all_lists, dims, source) if source is not None else [])
                     + (summed_dims(self.all_lists, dims, target) if target is not None else []))
            if extra:
                return (f"it adds its flux up over {', '.join(_str(d) for d in dict.fromkeys(extra))} on the way "
                        'into or out of an end that is not indexed by it, which an Ecolego transfer cannot do')
        shared = shared_dims(self.all_lists, source, target)
        if not shared:
            return 'its two ends are not indexed alike, so an Ecolego transfer could not be drawn between them'
        narrowed = None if _same_list(shared['dims'], dims) else self.narrowing(dims, shared['dims'])
        if not _same_list(shared['dims'], dims) and not narrowed:
            return (f"it is indexed by {' × '.join(_str(d) for d in dims) or 'nothing'}, which is neither "
                    f"what its two ends share ({' × '.join(_str(d) for d in shared['dims']) or 'nothing'}) "
                    'nor a sub-set of it')
        a = t.get('availability')
        if collection == 'transfers' and isinstance(a, dict) and _truthy(a.get('scheme')):
            scheme = a.get('scheme')
            if scheme in ('shared_limit', 'shared_langmuir'):
                over = _str(_or(a.get('over', _UNDEF), 'a group'))
                return f'its availability is shared over {over}, which has no Ecolego equivalent'
            if scheme not in ('limit', 'langmuir'):
                return f"its availability scheme '{_str(scheme)}' is not one this tool knows"
            blank = [k for k in (('limit',) if scheme == 'limit' else ('top', 'bottom'))
                     if js_trim(_str(_or(a.get(k, _UNDEF), ''))) == '']
            if blank:
                return f"its availability has no {' or '.join(blank)} to write into its rate"
            if narrowed:
                return ('it is both narrowed and limited by an availability, which cannot be written as one '
                        'Ecolego transfer')
        return None

    def plan_fluxes(self) -> None:
        raw, report = self.raw, self.report

        def boundary(name: Any, system: str, type_: str) -> str:
            names = self.names_in(system)
            local = f'{_str(name)}_{type_}'
            n = 2
            while local in names:
                local = f'{_str(name)}_{type_}_{n}'
                n += 1
            names.add(local)
            bid = f'{system}.{local}' if system else local
            self.boundaries.append({'name': local, 'id': bid, 'system': system, 'type': type_})
            return bid

        for collection in ('transfers', 'inflows'):
            for t in _list(raw.get(collection)):
                if not isinstance(t, dict):
                    continue
                q = _qname_of(t)
                if q in self.skipped_blocks:
                    continue
                inflow = collection == 'inflows'
                from_ref = None if inflow else _or(t.get('from', _UNDEF), None)
                to_ref = _or(t.get('to', _UNDEF), None)
                source = None if from_ref is None else self.resolve_end(from_ref, t)
                target = None if to_ref is None else self.resolve_end(to_ref, t)
                # A far-field path at either end: what flows into one arrives in
                # its first fracture cell; what a transfer out of one carries is
                # its release, which takes nothing from the path.
                into = self.far_paths.get(target) if isinstance(target, str) else None
                out_of = self.far_paths.get(source) if isinstance(source, str) else None
                if into:
                    report.rewrite(KIND_WORD[collection], q, f"it delivers into the far-field pathway '{_str(target)}', "
                                   f"so it is written into that path's first fracture cell, {into['inlet']}")
                    target = into['inlet']
                if out_of:
                    report.rewrite(KIND_WORD[collection], q, f"it carries the release of the far-field pathway "
                                   f"'{_str(source)}', which takes nothing from the path: written as a transfer from "
                                   'a source, at the same rate')
                    from_ref = None
                    source = None
                dims = list(_list(t.get('index_lists')))
                from_dims = self.end_dims(from_ref, t)
                to_dims = self.end_dims(to_ref, t)
                shared = shared_dims(self.all_lists, from_dims, to_dims)
                plan: Dict[str, Any] = {
                    'collection': collection, 'from': source, 'to': target, 'dims': dims, 'file_dims': dims,
                    'intersection': False, 'narrowed': None, 'availability': None,
                }
                if shared and not _same_list(shared['dims'], dims):
                    narrowed = self.narrowing(dims, shared['dims'])
                    plan['file_dims'] = list(shared['dims'])
                    plan['narrowed'] = narrowed
                    onto = [n['list'] for n in narrowed if not n['same']]
                    report.rewrite(KIND_WORD[collection], q, f"it is narrowed onto {', '.join(_str(o) for o in onto)}; "
                                   'written over what its two ends share, with a zero rate outside '
                                   + ('that sub-set' if len(onto) == 1 else 'those sub-sets'))
                if from_dims is not None and to_dims is not None and not _same_list(from_dims, to_dims) \
                        and not plan['narrowed']:
                    plan['intersection'] = True
                a = t.get('availability')
                if not inflow and isinstance(a, dict) and a.get('scheme') in ('limit', 'langmuir'):
                    home = _str(_or(t.get('system', _UNDEF), ''))
                    plan['availability'] = {**a, 'donor': self.reference_from(source, home)}
                    what = 'a solubility limit' if a.get('scheme') == 'limit' else 'Langmuir sorption'
                    report.rewrite(KIND_WORD[collection], q,
                                   f"its availability ({'held back, ' if _truthy(a.get('unavailable')) else ''}{what}) "
                                   'is written into its rate, which then gives the same flux')
                if inflow:
                    report.rewrite('inflow', q, 'written as a transfer from a source, which is how Ecolego feeds a '
                                   'compartment from outside; it comes back as a transfer')
                system = _str(_or(t.get('system', _UNDEF), ''))
                if source is None:
                    plan['source'] = boundary(t.get('name', _UNDEF), system, 'source')
                if target is None:
                    plan['sink'] = boundary(t.get('name', _UNDEF), system, 'sink')
                if source is None and not inflow and t.get('multiply_by_donor') is True:
                    report.warn(f"'{q}' has no donor and says it multiplies by one; it is written as the absolute "
                                'flux it is.')
                self.flux_plans[q] = plan

    def narrowing(self, dims: Sequence[Any], shared: Sequence[Any]) -> Optional[List[Dict[str, Any]]]:
        if len(dims) != len(shared):
            return None

        def root(n: Any) -> Any:
            return lineage(self.all_lists, n)['root']

        rest = list(dims)
        out: List[Dict[str, Any]] = []
        for d in shared:
            at = next((k for k, x in enumerate(rest) if root(x) == root(d)), -1)
            if at < 0:
                return None
            own = rest.pop(at)
            if own == d:
                out.append({'list': own, 'of': d, 'same': True})
                continue
            above = lineage(self.all_lists, own)['above']
            at2 = next((k for k, s in enumerate(above) if s['name'] == d), -1)
            if at2 < 0 or any(s['mapped'] for s in above[:at2 + 1]):
                return None
            out.append({'list': own, 'of': d, 'same': False})
        return out if any(not n['same'] for n in out) else None

    def reference_from(self, target: Any, system: str) -> Any:
        if target is None:
            return None
        home = parent_of(target)
        if not home or home == system:
            local = base_name(target)
            if resolve_reference(local, system, self.known) == target:
                return local
        return target

    def id_of(self, ref: Any, system: Any) -> Any:
        if _nullish(ref):
            return None
        text = js_trim(_str(ref))
        if not _IDENTIFIER_PATH.fullmatch(text):
            return _str(ref)
        found = resolve_reference(text, _str(_or(system, '')), self.known)
        return text if found is None else found

    def system_paths_list(self) -> List[str]:
        if self.paths is not None:
            return self.paths
        raw = self.raw
        seen: set = set()
        out: List[str] = []

        def add(path: Any) -> None:
            p = [x for x in _str(_or(path, '')).split('.') if x]
            for k in range(1, len(p) + 1):
                at = '.'.join(p[:k])
                if at not in seen:
                    seen.add(at)
                    out.append(at)

        for s in _list(raw.get('systems')):
            add(s if isinstance(s, str) else _get(s, 'name'))
        for s in _list(raw.get('transports')):
            add(s if isinstance(s, str) else _get(s, 'name'))
        for collection in ALL_COLLECTIONS:
            for b in _list(raw.get(collection)):
                if _qname_of(b) in self.skipped_blocks:
                    continue
                add(_get(b, 'system'))
        # The sub-systems the far-field paths are written as.
        for path in self.generated_systems:
            add(path)
        self.paths = out
        return out

    def check_names(self) -> None:
        """Names this package's importer would read back differently (``checkNames``)."""
        top: Dict[str, str] = {}
        clashes: List[str] = []

        def claim(name: str, what: str) -> None:
            had = top.get(name)
            if had is not None:
                clashes.append(f"'{name}' ({had}, {what})")
            else:
                top[name] = what

        for lst in self.export_lists:
            claim(self.list_id(lst.get('name')), 'index list')
        reserved: List[str] = []
        for path in self.system_paths_list():
            if base_name(path) in RESERVED:
                reserved.append(f"'{path}'")
            if '.' not in path:
                claim(path, 'sub-system')
        for collection in COMPONENT_COLLECTIONS + ('transfers', 'inflows'):
            for b in _list(self.raw.get(collection)):
                if not self.goes_out(b) or _truthy(b.get('system')):
                    continue
                claim(_str(b.get('name', _UNDEF)), KIND_WORD[collection])
            # A far-field path's release goes out as an expression of its name.
            for b in self.generated.get(collection, []):
                if _truthy(b.get('system')):
                    continue
                claim(_str(b.get('name', _UNDEF)), KIND_WORD[collection])
        if clashes:
            self.report.warn(f"{', '.join(clashes)}: an index list and something at the top of the model share a "
                             'name. This tool’s importer reads the two by one set of names, so reading the file back '
                             'here numbers the second of them and rewrites what refers to it.')
        if reserved:
            one = len(reserved) == 1
            self.report.warn(f"{', '.join(reserved)} {'is a sub-system' if one else 'are sub-systems'} named after a "
                             'function, which this tool’s importer numbers when it reads the file back.')

    def goes_out(self, b: Any) -> bool:
        return isinstance(b, dict) and _qname_of(b) not in self.skipped_blocks

    def has_states(self) -> bool:
        return (any(self.goes_out(c) for c in _list(self.raw.get('compartments')))
                or any(self.goes_out(c) for c in _list(self.raw.get('running_means')))
                or bool(self.generated['compartments']))

    def counts(self) -> Dict[str, int]:
        # What went out: the model's own blocks, and what its far-field paths were written as.
        def n(collection: str) -> int:
            return (sum(1 for b in _list(self.raw.get(collection)) if self.goes_out(b))
                    + len(self.generated.get(collection, [])))
        return {
            'index_lists': len(self.export_lists),
            'compartments': n('compartments'),
            'transfers': n('transfers') + n('inflows'),
            'parameters': n('parameters'),
            'expressions': n('expressions'),
            'functions': n('functions'),
            'lookups': n('lookups'),
            'index_reductions': n('index_reductions'),
            'block_reductions': n('block_reductions'),
            'min_maxes': n('min_maxes'),
            'running_means': n('running_means'),
            'snapshots': n('snapshots'),
            'delays': n('delays'),
            'triggers': n('triggers'),
            'systems': len(self.system_paths_list()),
            'nuclides': len(self.nuclide_names),
        }


# --- a far-field path on the grid --------------------------------------------------------

#: What each setting of a path is called in the file (``SETTING_NAME``).
_SETTING_NAME = {
    'tw': 'TW', 'f': 'F', 'aw': 'a_w', 'aperture': 'delta', 'kd_f': 'Kd_f', 'kd_m': 'Kd_m', 'de_m': 'De_m',
    'eps_m': 'eps_m', 'rho_m': 'rho_m', 'pe': 'Pe',
}

#: What each is, for its comment in the file (``SETTING_COMMENT``).
_SETTING_COMMENT = {
    'tw': 'The water travel time along the path, in [time]',
    'f': 'The flow-related transport resistance, in [time]·m²/m³',
    'aw': 'The flow-wetted surface per unit volume of flowing water, in m²/m³',
    'aperture': 'The fracture aperture, in m: two walls, so the wetted surface is 2/δ per m³ of water',
    'kd_f': 'Sorption on the fracture coating, in m³/m² (0 for none)',
    'kd_m': 'The partition coefficient in the rock matrix, in m³/kg',
    'de_m': 'The effective diffusivity in the rock matrix, in m²/[time]',
    'eps_m': 'The porosity of the rock matrix',
    'rho_m': 'The dry bulk density of the rock matrix, in kg/m³',
    'pe': 'The Peclet number; dispersion is the travel time over it',
}


def _written_settings(b: Dict[str, Any]) -> List[str]:
    """The settings of a path that go into the file as equations (``writtenSettings``)."""
    from ..engine.farfield import active_equation_keys
    return [k for k in active_equation_keys(b) if k not in ('pen_dep', 'pen_dep_0')]


def _path_network(block: Dict[str, Any]) -> Dict[str, Any]:
    """The transport matrix of a path, as transfers (``pathNetwork``): read off
    the path's own ``cell_values`` and ``release_weights``, one rate at a time."""
    import numpy as np
    from ..engine.farfield import cell_structure, cell_values, effective_structure, release_cells, release_weights
    g = effective_structure(block)
    nm = g['n_m']
    st = cell_structure(g)
    rows, cols, nnz = [int(v) for v in st['rows']], [int(v) for v in st['cols']], st['nnz']
    nsym = 4 + 2 * (nm - 1)

    def unit(k: int) -> Dict[str, Any]:
        c = {'advF': 0.0, 'dF': 0.0, 'diffFM1': 0.0, 'diffM1F': 0.0,
             'diffMMF': np.zeros(nm - 1), 'diffMMB': np.zeros(nm - 1)}
        if k == 0:
            c['advF'] = 1.0
        elif k == 1:
            c['dF'] = 1.0
        elif k == 2:
            c['diffFM1'] = 1.0
        elif k == 3:
            c['diffM1F'] = 1.0
        elif k < 4 + nm - 1:
            c['diffMMF'][k - 4] = 1.0
        else:
            c['diffMMB'][k - 4 - (nm - 1)] = 1.0
        return c

    ncells = (g['n_f'] + g['n_b']) * (nm + 1)
    entries: Dict[Tuple[int, int], Dict[str, Any]] = {}
    diag = [[0.0] * nsym for _ in range(ncells)]
    out = np.zeros(nnz)
    rel = release_cells(g)
    w = np.zeros(len(rel))
    release = [{'cell': cell, 'share': [0.0] * nsym} for cell in rel]
    for k in range(nsym):
        c = unit(k)
        cell_values(g, c, out)
        for e in range(nnz):
            v = float(out[e])
            if v == 0:
                continue
            if rows[e] == cols[e]:
                diag[cols[e]][k] += v
                continue
            key = (cols[e], rows[e])
            if key not in entries:
                entries[key] = {'from': cols[e], 'to': rows[e], 'share': [0.0] * nsym}
            entries[key]['share'][k] += v
        w[:] = 0.0
        release_weights(g, c, w)
        for i in range(len(rel)):
            release[i]['share'][k] += float(w[i])

    def terms(share: Sequence[float]) -> List[Tuple[int, float]]:
        return [(k, v) for k, v in enumerate(share) if v != 0]

    transfers: List[Dict[str, Any]] = []
    seen: set = set()
    for e in range(nnz):
        if rows[e] == cols[e]:
            continue
        key = (cols[e], rows[e])
        if key in seen:
            continue
        seen.add(key)
        x = entries.get(key)
        if x and any(v != 0 for v in x['share']):
            transfers.append({'from': x['from'], 'to': x['to'], 'terms': terms(x['share'])})
    handed = [[0.0] * nsym for _ in range(ncells)]
    for x in entries.values():
        for k in range(nsym):
            handed[x['from']][k] += x['share'][k]
    for cell in range(ncells):
        lost = [-diag[cell][k] - handed[cell][k] for k in range(nsym)]
        if any(v != 0 for v in lost):
            transfers.append({'from': cell, 'to': None, 'terms': terms(lost)})
    return {'transfers': transfers, 'release': [{'cell': r['cell'], 'terms': terms(r['share'])} for r in release]}


def _coef(a: float) -> str:
    """A whole number as a template literal writes it: ``3``, not ``3.0``."""
    return js_number(a)


def _terms_text(terms: Sequence[Tuple[int, float]], names: Sequence[str]) -> str:
    """A sum of rates as an equation (``termsText``)."""
    out = ''
    for i, (k, v) in enumerate(terms):
        a = abs(v)
        body = names[k] if a == 1 else f'{_coef(a)} * {names[k]}'
        if i == 0:
            out += f'-{body}' if v < 0 else body
        else:
            out += f' - {body}' if v < 0 else f' + {body}'
    return out


def _weighted(terms: Sequence[Tuple[int, float]], names: Sequence[str], cell: str, first: bool) -> str:
    """One cell's share of the release, as a term of a sum (``weighted``)."""
    if len(terms) == 1:
        k, v = terms[0]
        a = abs(v)
        body = f"{'' if a == 1 else f'{_coef(a)} * '}{names[k]} * {cell}"
        if first:
            return f'-{body}' if v < 0 else body
        return f' - {body}' if v < 0 else f' + {body}'
    return f"{'' if first else ' + '}({_terms_text(terms, names)}) * {cell}"


def _inventory_unit(unit: Any, time: str) -> str:
    """What a path's cells hold, from the unit of what it releases (``inventoryUnit``)."""
    u = js_trim(_str(_or(unit, '')))
    suffix = f'/{time}'
    return js_trim(u[:-len(suffix)]) if u.endswith(suffix) else ''


def _hashable(v: Any) -> Any:
    """``v`` itself where it can key a dictionary; a key no name can equal otherwise.

    Names out of a model are strings, but a hand-edited file may put anything
    where one goes, and JavaScript's ``Set`` takes it where a Python ``set``
    would not.
    """
    try:
        hash(v)
        return v
    except TypeError:
        return ('unhashable', id(v))


def _get_index(p: list, k: int) -> Any:
    return p[k] if k < len(p) else _UNDEF


def _same_list(a: Sequence[Any], b: Sequence[Any]) -> bool:
    return len(a) == len(b) and all(x == y for x, y in zip(a, b))


def _interpolation_to_eco(rule: Any) -> Optional[str]:
    """A rule's Ecolego spelling, or ``None`` for anything that is not one of the five."""
    return INTERPOLATION_TO_ECO.get(rule) if isinstance(rule, str) else None


def _lookup_rule(interpolation: Any) -> Any:
    """The rule a lookup table names, by this tool's name or Ecolego's."""
    if _nullish(interpolation) or interpolation == '':
        return 'linear'
    found = interpolation_from_eco(interpolation) if isinstance(interpolation, str) else \
        interpolation_from_eco(_str(interpolation))
    return interpolation if found is None else found


# --- the table of a block ---------------------------------------------------------------

def _table_of(block: Dict[str, Any], collection: str, dims: Sequence[Any], ctx: _Context) -> Dict[str, Any]:
    """A block's values as Ecolego's table holds them (``tableOf``)."""
    keys = VALUE_KEYS[collection]
    index_sets = [list(dict.fromkeys(_hashable(x) for x in ctx.indices_of(d))) for d in dims]
    index_lookup = [set(s) for s in index_sets]
    defaults: Dict[str, Any] = {}
    for k in keys:
        defaults[k] = block[k] if k in block else VALUE_DEFAULTS[collection].get(k, _UNDEF)
    valid: List[Dict[str, Any]] = []
    dropped = 0
    for e in _list(block.get('entries')):
        if not isinstance(e, dict):
            continue
        index = _entry_index(e.get('index', _UNDEF), dims, ctx.nuclide_list_name)
        if index is None:
            dropped += 1
            continue
        names = list(index)
        if any(l not in dims or _hashable(index[l]) not in index_lookup[list(dims).index(l)] for l in names):
            dropped += 1
            continue
        if not any(k in e for k in keys):
            continue
        valid.append({'index': index, 'entry': e, 'score': len(names)})
    for k in keys:
        wide = next((v for v in valid if v['score'] == 0 and k in v['entry']), None)
        if wide is not None:
            defaults[k] = wide['entry'][k]
    full: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    partial: List[Dict[str, Any]] = []
    for v in valid:
        if v['score'] == 0:
            continue
        if v['score'] == len(dims):
            at = tuple(_hashable(v['index'][d]) for d in dims)
            full.setdefault(at, []).append(v)
        else:
            partial.append(v)
    combos: List[List[Any]] = []
    seen: set = set()
    for v in valid:
        if v['score'] == 0:
            continue
        choices = [[v['index'][d]] if d in v['index'] else list(index_sets[i]) for i, d in enumerate(dims)]
        for combo in _product(choices):
            at = tuple(_hashable(c) for c in combo)
            if at in seen:
                continue
            seen.add(at)
            combos.append(combo)
    rows = []
    for combo in combos:
        values: Dict[str, Any] = {}
        exact = full.get(tuple(_hashable(c) for c in combo), [])
        for k in keys:
            own = next((v for v in exact if k in v['entry']), None)
            if own is not None:
                values[k] = own['entry'][k]
                continue
            best = None
            for v in partial:
                if k not in v['entry']:
                    continue
                if not all(d not in v['index'] or v['index'][d] == combo[i] for i, d in enumerate(dims)):
                    continue
                if best is None or v['score'] > best['score']:
                    best = v
            values[k] = best['entry'][k] if best is not None else defaults[k]
        rows.append({'combo': combo, 'values': values})
    return {'defaults': defaults, 'rows': rows, 'dropped': dropped, 'expanded': bool(partial)}


def _product(choices: Sequence[Sequence[Any]]) -> List[List[Any]]:
    out: List[List[Any]] = [[]]
    for options in choices:
        out = [[*head, o] for head in out for o in options]
    return out


def _entry_index(index: Any, dims: Sequence[Any], nuclide_list_name: Any) -> Optional[Dict[Any, Any]]:
    """An entry's index as a dictionary keyed by list (``normaliseEntryIndex``)."""
    if _nullish(index):
        return {}
    if isinstance(index, str):
        lst = dims[0] if len(dims) == 1 else nuclide_list_name
        return {lst: index} if _truthy(lst) else None
    if isinstance(index, list):
        if len(index) != len(dims):
            return None
        return {dims[k]: v for k, v in enumerate(index) if v is not None}
    if not isinstance(index, dict):
        return None
    return dict(index)


# --- numbers and text ---------------------------------------------------------------------

def java_double(x: Any) -> str:
    """A number as Java's ``Double.toString`` writes it -- which is how an Ecolego
    file writes every number: the shortest digits that read back as the same
    double, plain between 10^-3 and 10^7 with at least one digit after the point
    (``1000.0``, ``0.001``), and ``1.0E-4`` beyond."""
    v = _num(x)
    if v != v:
        return 'NaN'
    if math.isinf(v):
        return 'Infinity' if v > 0 else '-Infinity'
    if v == 0:
        return '-0.0' if math.copysign(1, v) < 0 else '0.0'
    sign = '-' if v < 0 else ''
    a = abs(v)
    t = Decimal(repr(a)).normalize().as_tuple()
    digits = ''.join(map(str, t.digits))
    e = len(digits) - 1 + int(t.exponent)
    if 1e-3 <= a < 1e7:
        if e >= 0:
            whole = digits[:e + 1].ljust(e + 1, '0')
            return f'{sign}{whole}.{digits[e + 1:] or "0"}'
        return f"{sign}0.{'0' * (-e - 1)}{digits}"
    return f'{sign}{digits[0]}.{digits[1:] or "0"}E{e}'


def _java_array(values: Iterable[float]) -> str:
    return '[' + ', '.join(java_double(v) for v in values) + ']'


def _ulp_step(x: float, n: int) -> float:
    (bits,) = struct.unpack('<q', struct.pack('<d', x))
    return struct.unpack('<d', struct.pack('<q', bits + n))[0]


#: Seconds in a Julian year, which Ecolego's half-lives are divided by.
SECONDS_PER_YEAR = 365.25 * 24 * 3600


def seconds_for(years: float) -> float:
    """A half-life in seconds that the importer's division reads back as exactly
    the years it was: ``years × SECONDS_PER_YEAR`` where that is so, and
    otherwise the nearest double within a few steps of it that is."""
    s = years * SECONDS_PER_YEAR
    if not math.isfinite(s) or s <= 0 or s / SECONDS_PER_YEAR == years:
        return s
    for k in range(1, 5):
        for c in (_ulp_step(s, k), _ulp_step(s, -k)):
            if c / SECONDS_PER_YEAR == years:
                return c
    return s


def guid_for(project: str, key: str) -> str:
    """A GUID for one thing in the file: four CRC-32s of its key and the
    project's name, laid out as a UUID with the version nibble of a
    vendor-defined one -- deterministic, so the same model gives the same bytes."""
    def hexed(salt: str) -> str:
        return format(zlib.crc32(_utf8(f'{salt}\x00{project}\x00{key}')) & 0xFFFFFFFF, '08X')
    a, b, c, d = hexed('a'), hexed('b'), hexed('c'), hexed('d')
    variant = format((int(c[0], 16) & 0x3) | 0x8, 'X')
    return f'{a}-{b[:4]}-8{b[5:8]}-{variant}{c[1:4]}-{c[4:8]}{d}'


def _xml_safe(text: Any) -> str:
    return _XML_BAD.sub('\ufffd', _str(text))


def _escape_attr(text: Any) -> str:
    return (_xml_safe(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace('\t', '&#9;').replace('\n', '&#10;').replace('\r', '&#13;'))


def _escape_text(text: Any) -> str:
    return _xml_safe(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\r', '&#13;')


def _cdata(text: Any) -> str:
    return '<![CDATA[' + ']]]]><![CDATA[>'.join(_xml_safe(text).replace('\r', '\n').split(']]>')) + ']]>'


class _XmlWriter:
    """Indented XML, one element per line, as the application lays it out."""

    def __init__(self) -> None:
        self.lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        self.depth = 0

    @staticmethod
    def attrs(pairs: Optional[Sequence[Tuple[str, Any]]]) -> str:
        return ''.join(f' {k}="{_escape_attr(v)}"' for k, v in (pairs or []) if not _nullish(v))

    def line(self, text: str) -> None:
        self.lines.append('\t' * self.depth + text)

    def open(self, name: str, attrs: Optional[Sequence[Tuple[str, Any]]] = None) -> None:
        self.line(f'<{name}{self.attrs(attrs)}>')
        self.depth += 1

    def close(self, name: str) -> None:
        self.depth -= 1
        self.line(f'</{name}>')

    def empty(self, name: str, attrs: Optional[Sequence[Tuple[str, Any]]] = None) -> None:
        self.line(f'<{name}{self.attrs(attrs)}/>')

    def text(self, name: str, value: Any, attrs: Optional[Sequence[Tuple[str, Any]]] = None) -> None:
        self.line(f"<{name}{self.attrs(attrs)}>{_escape_text(_or(value, ''))}</{name}>")

    def cdata(self, name: str, value: Any, attrs: Optional[Sequence[Tuple[str, Any]]] = None) -> None:
        v = '' if _nullish(value) else _str(value)
        self.line(f"<{name}{self.attrs(attrs)}>{'' if v == '' else _cdata(v)}</{name}>")

    def document(self) -> str:
        return '\n'.join(self.lines) + '\n'


# --- the sections ---------------------------------------------------------------------------

def _epoch_ms(modified: DateLike) -> Optional[int]:
    """What ``Date.getTime()`` gives for the date asked for: milliseconds since
    the epoch, a date without a time read at local midnight."""
    if modified is None:
        return None
    if isinstance(modified, _dt.datetime):
        return int(round(modified.timestamp() * 1000))
    if isinstance(modified, _dt.date):
        return int(round(_dt.datetime(modified.year, modified.month, modified.day).timestamp() * 1000))
    return int(round(float(modified) * 1000))


def _write_project_properties(w: _XmlWriter, raw: Dict[str, Any], ctx: _Context, modified: DateLike) -> None:
    name = ctx.project_name
    w.open('project-properties', [('name', name)])
    w.cdata('guid', guid_for(name, 'project'))
    stamp = _epoch_ms(modified)
    if stamp is not None:
        w.text('modification-date', str(stamp))
    # Who wrote it, as Ecolego keeps an author: a property beside the comment,
    # and before it, as the files it writes have them.
    author = _trim(_or(raw.get('author', _UNDEF), ''))
    if author:
        w.cdata('property', author, [('name', 'author'), ('type', 'string')])
    description = _trim(_or(raw.get('description', _UNDEF), ''))
    if description:
        w.cdata('property', description, [('name', 'comment'), ('type', 'string')])
    w.close('project-properties')


def _nuclide_numbers(name: Any) -> Optional[Tuple[int, int]]:
    m = _NUCLIDE.match(js_trim(_str(_or(name, ''))))
    if not m:
        return None
    symbol = m.group(1)[0].upper() + m.group(1)[1:].lower()
    z = ELEMENT_SYMBOLS.index(symbol) + 1 if symbol in ELEMENT_SYMBOLS else 0
    return (z, int(m.group(2))) if z > 0 else None


def _write_materials(w: _XmlWriter, ctx: _Context) -> None:
    unit = 'mol' if js_trim(_str(_or(ctx.raw.get('decay_unit', _UNDEF), 'Bq'))) == 'mol' else 'Bq'
    w.open('material-model')
    for m in ctx.materials:
        mid = ctx.index_id(ctx.material.get('name'), m['name'])
        if m['nuclide']:
            w.open('nuclide', [('name', m['name'])])
            w.text('id', mid)
            w.text('unit', unit)
            years = m['years']
            w.text('half-life', java_double(seconds_for(years)) if years is not None and math.isfinite(years)
                   else 'Infinity')
            za = _nuclide_numbers(m['name'])
            if za:
                w.text('z', str(za[0]))
                w.text('a', str(za[1]))
            w.close('nuclide')
        else:
            w.open('material', [('name', m['name'])])
            w.text('id', mid)
            if m['unit']:
                w.text('unit', m['unit'])
            w.close('material')
    w.close('material-model')


def _write_index_lists(w: _XmlWriter, ctx: _Context) -> None:
    report = ctx.report
    w.open('index-list-model')
    for lst in ctx.export_lists:
        name = lst.get('name')
        lid = ctx.list_id(name)
        w.open('index-list', [('name', lid)])
        w.text('id', lid)
        flags = [t for on, t in ((lst is ctx.material, 'MATERIALS'), (lst is ctx.nuclide_list, 'RADIONUCLIDES'),
                                 (_truthy(lst.get('for_scenarios')), 'SCENARIOS'),
                                 (lst is ctx.element_list, 'ELEMENTS')) if on]
        if flags:
            w.text('property', flags[0], [('name', 'predefined-type'), ('type', PREDEFINED_TYPE)])
            if len(flags) > 1:
                report.warn(f"'{_str(lst.get('name', _UNDEF))}' is marked as more than one of Ecolego's own lists "
                            f"({', '.join(flags)}); it is written as {flags[0]}.")
        indices = _nuclide_indices(ctx) if lst is ctx.nuclide_list else _list(lst.get('indices'))
        own_names = [_index_name(x) for x in _list(lst.get('indices'))]
        for i in indices:
            iname = _index_name(i)
            if iname is None:
                continue
            outside_own = lst is ctx.nuclide_list and iname not in own_names
            iid = ctx.index_id(ctx.material.get('name'), iname) if outside_own else ctx.index_id(name, iname)
            w.open('index', [('name', js_trim(_str(iname))), ('enabled', 'true' if _index_on(i) else 'false')])
            w.text('id', iid)
            w.close('index')
        sub = lst.get('sub_set_of')
        if _truthy(sub) and _hashable(sub) in ctx.list_ids:
            w.empty('sub-set', [('of', ctx.list_id(sub))])
        elif _truthy(sub):
            report.warn(f"'{_str(lst.get('name', _UNDEF))}' is a sub-set of '{_str(sub)}', which is not written; "
                        'it goes out as a list of its own.')
        mapping = lst.get('mapping') if isinstance(lst.get('mapping'), dict) else None
        if mapping is not None and _truthy(mapping.get('to')) and _hashable(mapping.get('to')) in ctx.list_ids:
            w.open('mapping', [('to', ctx.list_id(mapping['to']))])
            for pair in _list(mapping.get('pairs')):
                if _nullish(_get(pair, 'from')) or _nullish(_get(pair, 'to')):
                    continue
                w.empty('map', [('from', ctx.index_id(name, pair['from'])),
                                ('to', ctx.index_id(mapping['to'], pair['to']))])
            w.close('mapping')
        elif _truthy(lst.get('mapping')):
            report.warn(f"'{_str(lst.get('name', _UNDEF))}' maps onto a list that is not written; it goes out as a "
                        'list of its own.')
        comment = js_trim(_str(_or(lst.get('comment', _UNDEF), '')))
        if comment and lst is not ctx.element_list and not BUILT_IN_COMMENT.fullmatch(comment):
            ctx.list_comments += 1
        w.close('index-list')
    w.close('index-list-model')
    if ctx.list_comments:
        report.warn(f'{ctx.list_comments} index list comment(s) were left out: an Ecolego index list has no comment.')


def _nuclide_indices(ctx: _Context) -> List[Any]:
    own = _list(ctx.nuclide_list.get('indices'))
    names = {_hashable(_index_name(i)) for i in own}
    catalogue = {_hashable(m['name']) for m in ctx.materials}
    out = [i for i in own if _hashable(_index_name(i)) in catalogue]
    for m in ctx.materials:
        if m['nuclide'] and _hashable(m['name']) not in names:
            out.append({'name': m['name'], 'enabled': True})
    return out


def _write_decay_chains(w: _XmlWriter, ctx: _Context) -> None:
    w.open('nuclide-decay-model')
    for parent, daughter, ratio in ctx.chains:
        w.empty('decay-pair', [('parent', parent), ('daughter', daughter), ('rate', java_double(ratio))])
    w.close('nuclide-decay-model')


def _write_hierarchy(w: _XmlWriter, ctx: _Context) -> None:
    raw = ctx.raw
    transports = {_hashable(s if isinstance(s, str) else _get(s, 'name')) for s in _list(raw.get('transports'))}
    off = ({js_trim(_str(_or(p, ''))) for p in raw['disabled_systems']}
           if isinstance(raw.get('disabled_systems'), list) else set())
    w.open('hierarchy-model')
    w.open('sub-system-block')
    w.cdata('guid', guid_for(ctx.project_name, 'root'))
    w.close('sub-system-block')
    for path in ctx.system_paths_list():
        w.open('sub-system-block', [('name', base_name(path)), ('type', 'transport' if path in transports else None)])
        w.text('id', path)
        w.cdata('guid', guid_for(ctx.project_name, f'system:{path}'))
        if parent_of(path):
            w.text('sub-system', parent_of(path))
        w.text('enabled', 'false' if path in off else 'true')
        w.close('sub-system-block')
    w.close('hierarchy-model')


# --- blocks --------------------------------------------------------------------------------

def _write_blocks(w: _XmlWriter, ctx: _Context) -> None:
    raw = ctx.raw
    w.open('block-model')
    for collection in COMPONENT_COLLECTIONS:
        for block in _list(raw.get(collection)):
            if not isinstance(block, dict) or _qname_of(block) in ctx.skipped_blocks:
                continue
            _write_component(w, ctx, block, collection)
        # After the model's own: a path's cells follow the compartments, as its
        # states follow theirs in a run.
        for block in ctx.generated.get(collection, []):
            _write_component(w, ctx, block, collection)
    for b in ctx.boundaries:
        w.open('component', [('name', b['name']), ('type', b['type']), ('dimension', '0'), ('index-lists', '')])
        w.text('id', b['id'])
        w.cdata('guid', guid_for(ctx.project_name, f"block:{b['id']}"))
        if b['system']:
            w.text('sub-system', b['system'])
        w.text('enabled', 'true')
        w.close('component')
    for collection in ('transfers', 'inflows'):
        for t in _list(raw.get(collection)):
            if not isinstance(t, dict):
                continue
            plan = ctx.flux_plans.get(_qname_of(t))
            if plan:
                _write_connection(w, ctx, t, plan)
    for t in ctx.generated['transfers']:
        _write_connection(w, ctx, t, ctx.generated_plans[_qname_of(t)])
    w.close('block-model')
    if ctx.expanded_entries:
        ctx.report.rewrite('values per index', f'{ctx.expanded_entries} block(s)', 'an entry that names only '
                           'some of a block’s index lists is written as one row per index combination it covers, '
                           'which is how an Ecolego table holds it')
    if ctx.dropped_entries:
        one = ctx.dropped_entries == 1
        ctx.report.warn(f"{ctx.dropped_entries} entr{'y was' if one else 'ies were'} "
                        'keyed by an index list or index the block is not indexed by, and took no part in the run; '
                        f"{'it was' if one else 'they were'} not written.")


def _dim_attrs(ctx: _Context, dims: Sequence[Any], intersection: bool = False) -> List[Tuple[str, Any]]:
    ids = '' if intersection else ','.join(ctx.list_id(d) for d in dims)
    return [('dimension', str(len(dims))), ('index-lists', ids)]


def _write_common(w: _XmlWriter, ctx: _Context, block: Dict[str, Any], q: str) -> None:
    w.text('id', q)
    w.cdata('guid', guid_for(ctx.project_name, f'block:{q}'))
    if _truthy(block.get('system')):
        w.text('sub-system', block['system'])
    w.text('enabled', 'false' if block.get('enabled') is False else 'true')
    unit = _trim(_or(block.get('unit', _UNDEF), ''))
    if unit:
        w.text('unit', unit)
    comment = _trim(_or(block.get('comment', _UNDEF), ''))
    if comment:
        w.cdata('comment', comment)


def _row_key(ctx: _Context, dims: Sequence[Any], combo: Sequence[Any]) -> str:
    return ','.join(ctx.index_id(dims[k], name) for k, name in enumerate(combo))


def _write_component(w: _XmlWriter, ctx: _Context, block: Dict[str, Any], collection: str) -> None:
    q = _qname_of(block)
    transports = {_hashable(s if isinstance(s, str) else _get(s, 'name')) for s in _list(ctx.raw.get('transports'))}
    in_transport = _hashable(_or(block.get('system', _UNDEF), '')) in transports
    transport = block.get('transport', _UNDEF)
    role = (transport if collection == 'compartments' and transport in ('begin', 'end')
            else transport if collection == 'expressions' and transport in ('number', 'counter', 'operation')
            else None)
    if role and not in_transport:
        ctx.report.warn(f"'{q}' is marked as the {role} of a transport but is not inside one; it is written as a "
                        f'plain {KIND_WORD[collection]}.')
        role = None
    type_ = {'begin': 'transport-begin', 'end': 'transport-end', 'number': 'transport-number',
             'counter': 'transport-element-counter',
             'operation': 'transport-operation'}.get(role or '', ECO_TYPE[collection])
    dims = [] if collection == 'functions' else _list(block.get('index_lists'))
    w.open('component', [('name', block.get('name')), ('type', type_), *_dim_attrs(ctx, dims)])
    _write_common(w, ctx, block, q)

    if role == 'counter':
        w.close('component')
        return
    if role == 'operation':
        op = js_trim(_str(_or(block.get('operation', _UNDEF), ''))).lower()
        w.cdata('operation', 'SUM' if op in ('sum', 'point') else 'MEAN')
        arg = js_trim(_str(_or(block.get('argument', _UNDEF), ''))).lower()
        args = [('from', 'From'), ('to', 'To')] if arg == 'range' else [('point', 'Point')] if arg == 'point' else []
        for key, label in args:
            w.open('argument')
            w.text('argument-key', key)
            w.text('argument-name', label)
            w.close('argument')
        w.close('component')
        return
    if role == 'number':
        w.text('evaluation-mode', 'SIMULATION')

    table = None if collection == 'functions' else _table_of(block, collection, dims, ctx)
    if table is not None and table['expanded']:
        ctx.expanded_entries += 1
    if table is not None and table['dropped']:
        ctx.dropped_entries += table['dropped']
    system = _or(block.get('system', _UNDEF), '')

    if collection == 'parameters':
        _write_parameter_rows(w, ctx, q, dims, table)
    elif collection == 'compartments':
        w.text('handle-decay', 'false' if block.get('handle_decay') is False else 'true')
        _write_compartment_rows(w, ctx, q, dims, table)
    elif collection == 'expressions':
        _write_rows(w, ctx, dims, table, 'expression',
                    lambda values: w.cdata('equation', _equation_text(values['equation'], '0')))
    elif collection == 'functions':
        for p in _list(block.get('parameters')):
            name = js_trim(_str(_or(p, '')))
            if not name:
                continue
            w.open('argument')
            w.text('argument-key', name)
            w.text('argument-name', name)
            w.close('argument')
        w.open('entry', [('type', 'expression')])
        w.cdata('equation', _equation_text(block.get('equation', _UNDEF), ''))
        w.close('entry')
    elif collection == 'lookups':
        w.cdata('lookup-option', _interpolation_to_eco(_lookup_rule(block.get('interpolation', _UNDEF))))
        cyclic = block.get('cyclic')
        w.text('lookup-cyclic', 'true' if cyclic is True or cyclic == 'true' else 'false')
        argument = '' if _nullish(block.get('argument', _UNDEF)) else js_trim(_str(block['argument']))
        if argument:
            w.open('argument')
            w.text('argument-key', argument)
            w.text('argument-name', argument)
            w.close('argument')

        def lookup_body(values: Dict[str, Any]) -> None:
            pts = _lookup_points(values['points'], ctx, q)
            w.cdata('lookup-table-time-points', _java_array(p[0] for p in pts))
            w.cdata('lookup-table-values', _java_array(p[1] for p in pts))
        _write_rows(w, ctx, dims, table, 'lookup-table', lookup_body)
    elif collection == 'index_reductions':
        op = _operation_of(block.get('operation', _UNDEF))
        w.cdata('operation', OPERATION_TO_ECO.get(op, 'SUM'))
        pct = block.get('percentile', _UNDEF)
        if not _nullish(pct) and pct != '' and math.isfinite(_num(pct)):
            w.text('percentile', java_double(_num(pct)))
        _write_rows(w, ctx, dims, table, 'expression', lambda values: w.cdata(
            'equation', '' if _nullish(values['target']) else ctx.id_of(values['target'], system)))
    elif collection == 'block_reductions':
        op = _operation_of(block.get('operation', _UNDEF))
        w.cdata('operation', OPERATION_TO_ECO.get('sum' if op == 'percentile' else op, 'SUM'))
        _write_rows(w, ctx, dims, table, 'expression', lambda values: w.cdata(
            'equation', '+'.join(_str(ctx.id_of(t, system)) for t in _targets_of(values['targets']))))
    elif collection in ('min_maxes', 'running_means'):
        if collection == 'min_maxes':
            op = block.get('operation', _UNDEF)
            w.cdata('operation', 'MIN' if extreme_from_eco(None if _nullish(op) else _str(op)) == 'min' else 'MAX')

        def recorder_body(values: Dict[str, Any]) -> None:
            w.cdata('target-expression', _target_text(ctx, values['target'], system))
            for key, tag in (('reset_trigger', 'reset-event'), ('start_trigger', 'start-recording-event'),
                             ('stop_trigger', 'stop-recording-event')):
                v = values[key]
                if not _nullish(v) and js_trim(_str(v)) != '':
                    w.cdata(tag, ctx.id_of(v, system))
        _write_rows(w, ctx, dims, table, 'min-max' if collection == 'min_maxes' else 'running-mean', recorder_body)
    elif collection == 'snapshots':
        def snapshot_body(values: Dict[str, Any]) -> None:
            w.cdata('snapshot-target', _target_text(ctx, values['target'], system))
            v = values['trigger']
            if not _nullish(v) and js_trim(_str(v)) != '':
                w.cdata('snapshot-event', ctx.id_of(v, system))
            w.cdata('snapshot-initial-value', _equation_text(values['initial'], '0'))
        _write_rows(w, ctx, dims, table, 'snapshot', snapshot_body)
    elif collection == 'delays':
        def delay_body(values: Dict[str, Any]) -> None:
            w.cdata('delay-target', _target_text(ctx, values['target'], system))
            w.cdata('delay-time', _equation_text(values['delay'], '0'))
        _write_rows(w, ctx, dims, table, 'delay', delay_body)
    elif collection == 'triggers':
        directions: List[str] = []

        def trigger_body(values: Dict[str, Any]) -> None:
            w.cdata('first-expression', _equation_text(values['first'], '0'))
            w.cdata('second-expression', _equation_text(values['second'], '0'))
            raw_dir = values['direction']
            if _nullish(raw_dir) or raw_dir == '':
                d = 'rising'
            else:
                found = direction_from_eco(_str(raw_dir))
                d = raw_dir if found is None else found
            spelled = (DIRECTION_TO_ECO.get(d) if _hashable(d) is d else None) or 'RIGHT'
            if spelled not in directions:
                directions.append(spelled)
            w.cdata('direction', spelled)
        _write_rows(w, ctx, dims, table, 'discrete-event', trigger_body)
        if len(directions) > 1:
            ctx.report.warn(f"'{q}' fires in a different direction at some indices. The file says so index "
                            'by index; this tool reads back only the block’s own direction.')
    w.close('component')


def _equation_text(value: Any, fallback: str) -> str:
    return fallback if _nullish(value) else _str(value)


def _target_text(ctx: _Context, value: Any, system: Any) -> str:
    text = _equation_text(value, '0')
    return _str(ctx.id_of(text, system)) if _SPACED_PATH.fullmatch(text) else text


def _operation_of(raw: Any) -> str:
    if _nullish(raw) or raw == '':
        return 'sum'
    found = operation_from_eco(_str(raw))
    return _str(raw) if found is None else found


def _targets_of(targets: Any) -> List[str]:
    if _nullish(targets):
        return []
    items = targets.split('+') if isinstance(targets, str) else targets if isinstance(targets, list) else []
    return [x for x in (js_trim(_str(t)) for t in items) if x != '']


def _lookup_points(points: Any, ctx: _Context, q: str) -> List[List[float]]:
    pairs = points if isinstance(points, list) else []
    flat = (lambda a: isinstance(a, list) and all(isinstance(v, str) or _is_number(v) for v in a))
    if (len(pairs) == 2 and isinstance(pairs[0], list) and isinstance(pairs[1], list)
            and len(pairs[0]) == len(pairs[1]) and flat(pairs[0]) and len(pairs[0]) != 2):
        pairs = [[x, pairs[1][k]] for k, x in enumerate(pairs[0])]
    out: List[List[float]] = []
    for p in pairs:
        if isinstance(p, list):
            x, y, pdf = _get_index(p, 0), _get_index(p, 1), _get_index(p, 2)
        else:
            x, y, pdf = _get(p, 'x'), _get(p, 'y'), _get(p, 'pdf')
        if _truthy(pdf):
            ctx.report.skip('distribution', q, 'a distribution on a point of a lookup table has no Ecolego '
                            'equivalent; the points keep their values')
        out.append([_num(x), _num(y)])
    ordered = [p for _, p in sorted(((k, p) for k, p in enumerate(out)), key=lambda kp: (kp[1][0], kp[0]))]
    if any(p is not out[k] for k, p in enumerate(ordered)):
        ctx.report.rewrite('lookup table', q, 'its points are written in order of time, as Ecolego keeps a table')
    return ordered


def _write_rows(w: _XmlWriter, ctx: _Context, dims: Sequence[Any], table: Dict[str, Any], type_: str, body) -> None:
    w.open('entry', [('type', type_)])
    body(table['defaults'])
    w.close('entry')
    for row in table['rows']:
        w.open('entry', [('type', type_), ('index', _row_key(ctx, dims, row['combo']))])
        body(row['values'])
        w.close('entry')


def _write_parameter_rows(w: _XmlWriter, ctx: _Context, q: str, dims: Sequence[Any], table: Dict[str, Any]) -> None:
    shared = _pdf_for(table['defaults']['pdf'], ctx, q) is not None
    inherits = [False]

    def body(values: Dict[str, Any]) -> None:
        v = values['value']
        n = _num(v)
        if isinstance(v, str) and js_trim(v) != '' and not math.isfinite(n) and not _INFINITY_WORD.fullmatch(v):
            ctx.report.warn(f"'{q}' holds '{v}', which is not a number; it was written as it is.")
            w.cdata('value', v)
        else:
            w.cdata('value', java_double(0 if _nullish(v) or v == '' else n))
        pdf = _pdf_for(values['pdf'], ctx, q)
        if pdf is not None:
            w.open('pdf', [('function', pdf[0])])
            w.cdata('pdf-value', pdf[1])
            w.close('pdf')
        elif values is not table['defaults'] and shared:
            inherits[0] = True

    _write_rows(w, ctx, dims, table, 'parameter', body)
    if inherits[0]:
        ctx.report.warn(f"'{q}' has an index with no distribution in the file beside a block that has one; "
                        'this tool reads that index back with the block’s distribution.')


def _write_compartment_rows(w: _XmlWriter, ctx: _Context, q: str, dims: Sequence[Any], table: Dict[str, Any]) -> None:
    floors: List[bool] = []

    def body(values: Dict[str, Any]) -> None:
        w.cdata('initial-condition', _equation_text(values['initial'], '0'))
        v = values['non_negative']
        on = v is not False and v != 'false' and not (_is_number(v) and v == 0)
        if on not in floors:
            floors.append(on)
        w.text('lower-saturation', '0.0' if on else NO_FLOOR)
        w.text('upper-saturation', '')
        tol = values['abstol']
        t = None if _nullish(tol) or tol == '' else _num(tol)
        w.text('abs-tol', java_double(t) if t is not None and math.isfinite(t) and t > 0 else '')
        w.cdata('differential-equation', '' if _nullish(values['dydt']) else js_trim(_str(values['dydt'])))

    _write_rows(w, ctx, dims, table, 'compartment', body)
    if len(floors) > 1:
        ctx.report.warn(f"'{q}' may go negative at some indices and not at others. The file says so index "
                        'by index; this tool reads it back as one setting for the whole block, which may go negative.')


def _pdf_for(spec: Any, ctx: _Context, q: str) -> Optional[Tuple[str, str]]:
    """A distribution in Ecolego's spelling -- ``(function, expression)`` -- or
    ``None`` for one that has none (``pdfFor``)."""
    if not isinstance(spec, dict):
        return None
    kind = spec.get('kind', _UNDEF)
    meta = PDF_KINDS.get(kind) if isinstance(kind, str) else None
    if meta is None:
        return None
    if kind in ('dtriang', 'logdt'):
        ctx.report.skip('distribution', q, f"'{meta['label']}' is not a shape Ecolego has; the value is kept")
        return None
    parts: List[str] = []
    if kind == 'pg':
        values = [x for x in (_num(v) for v in _list(spec.get('values'))) if math.isfinite(x)]
        parts.append('values=' + ';'.join(java_double(v) for v in values))
    else:
        params = spec.get('params')
        for p in meta['params']:
            v = _get(params, p['key'])
            parts.append(p['key'] if _nullish(v) or v == '' else f"{p['key']}={java_double(_num(v))}")

    def number_or_none(key: str) -> Optional[float]:
        v = spec.get(key, _UNDEF)
        return None if _nullish(v) or v == '' else _num(v)

    trmin, trmax = number_or_none('trmin'), number_or_none('trmax')
    pmin, pmax = number_or_none('pmin'), number_or_none('pmax')
    if pmin is not None or pmax is not None:
        if kind != 'pg' and complete(spec):
            if pmin is not None:
                at = quantile(spec, pmin)
                trmin = at if trmin is None else _js_max(trmin, at)
            if pmax is not None:
                at = quantile(spec, pmax)
                trmax = at if trmax is None else _js_min(trmax, at)
            ctx.report.rewrite('distribution', q, 'its truncation at percentiles of the curve is written as the '
                               'values those percentiles fall at, which cut it in the same place')
        else:
            ctx.report.skip('truncation', q, 'a truncation at percentiles of a distribution that is not filled in, '
                            'or of a list, has no value to be written as')
    if trmin is not None and trmin == trmin:
        parts.append(f'trmin={java_double(trmin)}')
    if trmax is not None and trmax == trmax:
        parts.append(f'trmax={java_double(trmax)}')
    group = spec.get('group', _UNDEF)
    if not _nullish(group) and js_trim(_str(group)) != '':
        ctx.report.skip('correlation group', q, f"the group '{js_trim(_str(group))}' has no Ecolego spelling; "
                        'its members are sampled independently there')
    if kind == 'pg':
        parts.append('inorder=' + ('false' if spec.get('inorder') is False else 'true'))
        pos = _num(_or(spec.get('pos', _UNDEF), 0))
        parts.append('pos=' + (_str(js_round(pos)) if math.isfinite(pos) else '0'))
    return kind, f"{meta['expr']}({','.join(parts)})"


def _write_connection(w: _XmlWriter, ctx: _Context, t: Dict[str, Any], plan: Dict[str, Any]) -> None:
    q = _qname_of(t)
    w.open('connection', [
        ('name', t.get('name')), ('type', 'transfer'),
        ('source', _or(plan['from'], plan.get('source'))), ('target', _or(plan['to'], plan.get('sink'))),
        *_dim_attrs(ctx, plan['file_dims'], plan['intersection']),
    ])
    _write_common(w, ctx, t, q)
    collection = 'inflows' if plan['collection'] == 'inflows' else 'transfers'
    absolute = plan['from'] is None

    def rate(text: Any) -> str:
        return _availability_rate(_equation_text(text, '0'), plan['availability'])

    def donor(values: Dict[str, Any]) -> bool:
        if absolute:
            return False
        v = values.get('multiply_by_donor', _UNDEF)
        return v is not False and v != 'false' and not (_is_number(v) and v == 0)

    def body(values: Dict[str, Any]) -> None:
        w.cdata('transfer-equation', rate(values['rate']))
        w.text('multiply-with-donor', 'true' if donor(values) else 'false')

    if plan['narrowed']:
        narrowed = plan['narrowed']
        table = _table_of(t, collection, plan['dims'], ctx)
        inside = [set(_hashable(x) for x in ctx.indices_of(n['list'])) for n in narrowed]
        w.open('entry', [('type', 'transfer')])
        w.cdata('transfer-equation', '0')
        w.text('multiply-with-donor', 'true' if donor(table['defaults']) else 'false')
        w.close('entry')
        shared = [ctx.indices_of(n['of']) for n in narrowed]
        for combo in _product(shared):
            if not all(_hashable(name) in inside[k] for k, name in enumerate(combo)):
                continue
            tuple_ = {n['list']: combo[k] for k, n in enumerate(narrowed)}
            values = _value_at_row(table, plan['dims'], tuple_)
            w.open('entry', [('type', 'transfer'), ('index', _row_key(ctx, [n['of'] for n in narrowed], combo))])
            body(values)
            w.close('entry')
        w.close('connection')
        return
    table = _table_of(t, collection, plan['dims'], ctx)
    if table['expanded']:
        ctx.expanded_entries += 1
    if table['dropped']:
        ctx.dropped_entries += table['dropped']
    _write_rows(w, ctx, plan['dims'], table, 'transfer', body)
    w.close('connection')


def _value_at_row(table: Dict[str, Any], dims: Sequence[Any], tuple_: Dict[Any, Any]) -> Dict[str, Any]:
    combo = [tuple_.get(d, _UNDEF) for d in dims]
    for r in table['rows']:
        if all(c == combo[k] for k, c in enumerate(r['combo'])):
            return r['values']
    return table['defaults']


def _availability_rate(rate: str, a: Optional[Dict[str, Any]]) -> str:
    if not a:
        return rate
    d = _str(a['donor'])
    limit, top, bottom = (js_trim(_str(_or(a.get(k, _UNDEF), ''))) for k in ('limit', 'top', 'bottom'))
    if a.get('scheme') == 'limit':
        body = f'if({d} > 0, min(({limit}) / {d}, 1), 1)'
    else:
        body = f'if(({d} + ({bottom})) == 0, 1, ({d} + ({top})) / ({d} + ({bottom})))'
    if _truthy(a.get('unavailable')):
        body = f'(1 - {body})'
    return f'({rate}) * {body}'


# --- simulation ------------------------------------------------------------------------------

def _log_grid(start: float, end: float, n: int) -> List[float]:
    """The times a logarithmic grid holds: ``Project.timeGrid``, to the last bit."""
    t = [0.0] * n
    lo = start if start > 0 else max(end, 1) * 1e-6
    a = _js_log(lo)
    b = _js_log(end)
    t[0] = start
    for k in range(1, n):
        t[k] = _js_exp(a + ((b - a) * k) / (n - 1))
    t[n - 1] = end
    return t


def _write_simulation(w: _XmlWriter, raw: Dict[str, Any], ctx: _Context) -> None:
    report = ctx.report
    sim = raw.get('simulation') if isinstance(raw.get('simulation'), dict) else {}

    def num(v: Any, fallback: float) -> float:
        n = math.nan if _nullish(v) or v == '' else _num(v)
        return n if math.isfinite(n) else fallback

    start = num(sim.get('start_time', _UNDEF), 0)
    end = num(sim.get('end_time', _UNDEF), 1e5)
    w.open('simulation-settings')
    w.text('start-time', java_double(start))
    w.text('end-time', java_double(end))
    time_unit = sim.get('time_unit', _UNDEF)
    w.text('time-unit', time_unit if time_unit in ('second', 'minute', 'hour', 'day', 'year') else 'year')

    solver = _str(_or(sim.get('solver', _UNDEF), 'ndf'))
    eco = SOLVER_TO_ECO.get(solver, 'ODE15S')
    w.text('java-solver', eco)
    if solver not in SOLVER_EXACT:
        report.rewrite('solver', solver, f"written as {eco}: {SOLVER_WHY.get(solver, 'the nearest Ecolego has')}")
    elif solver == 'ndf' and (sim.get('bdf') is True or sim.get('bdf') == 'true'):
        report.warn('The model runs the plain BDF formulas; the file asks for ODE15S, whose formulas are the '
                    'numerical differentiation ones.')
    w.text('rel-error-tolerance', java_double(num(sim.get('rtol', _UNDEF), 1e-3)))
    w.text('abs-error-tolerance', java_double(num(sim.get('abstol', _UNDEF), 1e-6)))
    nn = sim.get('non_negative', _UNDEF)
    floor = not (nn is False or nn == 'false' or (_is_number(nn) and nn == 0))
    w.text('saturation-enabled', 'true' if floor else 'false')
    w.text('simulation-type', 'DETERMINISTIC')

    spacing = sim.get('spacing', _UNDEF)
    spacing = spacing if spacing in ('log', 'linear', 'series', 'solver', 'both') else 'log'
    points = _js_max(2, js_round(num(sim.get('output_points', _UNDEF), 250)))
    points = int(points) if float(points).is_integer() else points
    series = _normalise_series(sim.get('output_times', _UNDEF))
    written: List[Dict[str, Any]] = []
    if spacing == 'solver':
        mode = 'solver'
    elif spacing == 'series' or (spacing == 'both' and series):
        mode = 'both' if spacing == 'both' else 'series'
        written = series
        if not series:
            report.warn('The model asks for its output on a list of series and lists none; the file says so too.')
    elif spacing == 'linear':
        mode = 'series'
        written = [{'kind': 'linear', 'points': points, 'from': None, 'to': None}]
        report.rewrite('output times', f'{_str(points)} even points', 'written as one linear time series over the run')
    else:
        mode = 'both' if spacing == 'both' else 'series'
        written = [{'kind': 'times', 'times': _log_grid(start, end, int(points))}]
        report.rewrite('output times', f'{_str(points)} logarithmic points', 'written as the list of those times, '
                       'since a geometric series in the file would begin at 1 rather than where this grid begins')
    w.text('output-options', OUTPUT_OPTION[mode])
    if written:
        w.open('time-series-list')
        for s in written:
            if s['kind'] == 'times':
                w.open('time-series', [('type', 'custom')])
                w.cdata('values', _java_array(s['times']))
                w.close('time-series')
            else:
                w.open('time-series', [('type', 'geometric' if s['kind'] == 'log' else 'linear')])
                w.text('time-series-start-time', D_AUTO_TEXT if s['from'] is None else java_double(s['from']))
                w.text('time-series-end-time', D_AUTO_TEXT if s['to'] is None else java_double(s['to']))
                w.text('n', _str(s['points']))
                w.close('time-series')
        w.close('time-series-list')
    if spacing == 'solver' and not _nullish(sim.get('output_points', _UNDEF)) and points != 250:
        report.warn(f"The model's {_str(points)} output points are not written: with the solver's own steps as the "
                    'output, an Ecolego file has no count of points.')

    endpoints: List[str] = []
    lost: List[str] = []
    for name in _list(sim.get('endpoints')):
        text = _str(name)
        q = text if ctx.known(text) else None
        if q and q not in ctx.skipped_blocks and q not in endpoints:
            endpoints.append(q)
        elif not q or q in ctx.skipped_blocks:
            lost.append(text)
    if endpoints:
        w.open('outputs')
        for q in endpoints:
            w.empty('output', [('id', q)])
        w.close('outputs')
    if lost:
        report.warn(f"{len(lost)} endpoint(s) ({', '.join(lost[:4])}{', …' if len(lost) > 4 else ''}) "
                    'name a block or a series that is not in the file, and were left off its list of outputs.')
    w.close('simulation-settings')

    carried = []
    for k in UNCARRIED_SETTINGS:
        v = sim.get(k, _UNDEF)
        if _nullish(v) or v == '' or v is False or v == 'false':
            continue
        if k in ('max_step', 'initial_step') and _num(v) == 0:
            continue
        if k == 'split' and v == 'auto':
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, dict) and not v:
            continue
        carried.append(k)
    if carried:
        report.warn(f"Settings an Ecolego project has no field for were left out: {', '.join(carried)}.")
    scenario = raw.get('scenario', _UNDEF)
    if not _nullish(scenario):
        scenarios = [_index_name(i) for l in ctx.export_lists if _truthy(l.get('for_scenarios'))
                     for i in _list(l.get('indices')) if _index_on(i)]
        if scenarios and scenarios[0] != scenario and scenario in scenarios:
            report.warn(f"The scenario the model has chosen, '{_str(scenario)}', is not written: Ecolego runs every "
                        f"scenario, and this tool opens an imported model on the first, '{_str(scenarios[0])}'.")
    derived = raw.get('derived')
    if isinstance(derived, list) and derived:
        report.skip('derived numbers', f'{len(derived)} number(s)', 'numbers read off finished curves have no '
                    'Ecolego equivalent')

    def drawn(v: Any) -> bool:
        return isinstance(v, (dict, list)) and len(v) > 0

    colours = sum(1 for c in _list(raw.get('compartments'))
                  if isinstance(c, dict) and _truthy(c.get('color')) and _qname_of(c) not in ctx.skipped_blocks)
    diagram = [part for part in (
        'its layout' if drawn(raw.get('layout')) else None,
        'the shapes drawn on it' if drawn(raw.get('shapes')) else None,
        'what it shows' if drawn(raw.get('view')) else None,
        f"{colours} compartment colour{'' if colours == 1 else 's'}" if colours else None,
    ) if part]
    if diagram:
        report.warn(f"The diagram is this tool’s own and is not written ({', '.join(diagram)}): Ecolego lays a "
                    'model out itself.')


def _normalise_series(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spec in _list(raw):
        if not isinstance(spec, dict):
            continue
        if isinstance(spec.get('times'), list):
            times = sorted(x for x in (_num(v) for v in spec['times']) if math.isfinite(x))
            if times:
                out.append({'kind': 'times', 'times': times})
            continue
        named = _str(_or(spec.get('kind', _UNDEF), _or(spec.get('spacing', _UNDEF), 'log')))
        kind = 'linear' if named == 'linear' else 'times' if named == 'times' else 'log'
        if kind == 'times':
            continue
        points = js_round(_num(_or(spec.get('points', _UNDEF), 0)))
        if not (points >= 2):
            continue

        def n(v: Any) -> Optional[float]:
            return None if _nullish(v) or v == '' else _num(v)

        start, stop = n(spec.get('from', _UNDEF)), n(spec.get('to', _UNDEF))
        out.append({'kind': kind, 'points': points,
                    'from': start if start is not None and math.isfinite(start) else None,
                    'to': stop if stop is not None and math.isfinite(stop) else None})
    return out


def _write_probabilistic(w: _XmlWriter, raw: Dict[str, Any], ctx: _Context) -> None:
    report = ctx.report
    sim = raw.get('simulation') if isinstance(raw.get('simulation'), dict) else {}
    n = js_round(_num(sim.get('iterations', _UNDEF)))
    s = js_round(_num(sim.get('seed', _UNDEF)))
    w.open('probabilistic-settings')
    w.text('no-simulations', _str(n if math.isfinite(n) and n > 0 else 1000))
    w.text('seed', _str(s if math.isfinite(s) else 1))
    w.text('sampling', 'Random' if sim.get('sampling') == 'random' else 'Latin Hypercube')
    varied: List[str] = []
    for name in _list(sim.get('varied')):
        text = _str(name)
        found = ctx.blocks.get(text)
        if found and found['collection'] == 'parameters' and text not in ctx.skipped_blocks:
            varied.append(text)
    if varied:
        w.open('probabilistic-parameters')
        for q in varied:
            w.text('selected-parameter', q)
        w.close('probabilistic-parameters')
    kept = len(_list(sim.get('varied'))) - len(varied) if isinstance(sim.get('varied'), list) else 0
    if kept > 0:
        report.warn(f'{kept} of the inputs the model varies are not parameters in the file (a lookup point, or a '
                    'block that is left out) and were left off its list.')
    w.close('probabilistic-settings')
    correlations = sim.get('correlations')
    if isinstance(correlations, list) and correlations:
        report.skip('correlation', f'{len(correlations)} pair(s)', 'this tool’s correlations are not written: '
                    'the form an Ecolego file keeps them in is not one this tool reads')
