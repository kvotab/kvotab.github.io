"""The model: read a Kompartment project file, edit it, write it back.

::

    import kompartment as kp

    m = kp.Model.new('Two boxes')
    m.add_nuclides(['Cs-137'])
    m.add_compartment('Soil', initial='1e10')
    m.add_compartment('Well')
    m.add_parameter('k', 0.05, unit='1/year')
    m.add_transfer('Soil', 'Well', rate='k')
    m.save('two-boxes.json')

A :class:`Model` holds the project exactly as the file does -- a dictionary,
reachable as :attr:`Model.raw` -- and every block, index list and setting is a
view onto it. Reading a file brings it into the shape Kompartment itself works
on, as the application does when it opens one: older keys renamed, the two
built-in material lists present, every block's dimensions written down,
transfer ends written as qualified names, and the units that follow from the
model filled in. Nothing else about the model changes.

The edits that reach across the model -- renaming or moving a block, deleting
one, renaming an index or a sub-system -- follow the change through every
reference the way the application's own editor (``src/domain/edit.js``) does,
and refuse the ones it refuses.

**What follows from the model** -- a transfer's unit, which follows from its
donor and the time unit; its dimensions, which follow from its two ends; a
transport's dimensions, which follow from what it is connected to -- is brought
up to date by :meth:`Model.settle`, which the application runs after every
edit. Here it runs whenever the model is written out or checked, and the edits
that depend on it run the part they need on the spot.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple, Union

from . import decay as _decay
from .blocks import (
    AGGREGATE_OPERATIONS, DIRECTIONS, EVENT_DEFAULTS, EVENT_EQUATION_KEYS, EXTREMES, FARF_DEFAULTS,
    FARF_EQUATION_KEYS, FARF_NUCLIDE_KEYS, INTERPOLATIONS, KINDS, OPERATIONS, SINGULAR,
    TRANSPORT_ARGUMENTS, TRANSPORT_OPERATIONS, WASTE_DEFAULTS, WASTE_EQUATION_KEYS, WASTE_NUCLIDE_KEYS,
    Block, BlockReduction, Compartment, Delay, Event, Expression, Farfield, Function, IndexReduction,
    Inflow, Lookup, MinMax, Parameter, RunningMean, Snapshot, Transfer, Trigger, WastePackage,
    equation_text,
)
from .blocks import view as _view_of
from .equations import references_in, rewrite_references, rewrite_written_indices
from .errors import EditError, KompartmentError
from .indexlists import (
    COMPARTMENT_LIST, ELEMENT_LIST, MATERIAL_LIST, NUCLIDE_LIST, TRANSFER_LIST, clashing_dimensions,
    clashing_dimensions_why, derive_elements, find_list, index_name, is_decay_dim, lineage,
    list_applies, list_applies_why, normalise_indices, shared_dims, split_material_roles,
)
from .jsonio import PathLike, dumps, js_number, js_text, read_model_file, write_model_file
from .keys import COLLECTIONS, migrate_keys
from .names import (
    NAME_RE, RESERVED, base_name, is_valid_path, is_within, name_problem, parent_of, parts,
    qualified_name, qualify, reference_from, reparent, resolve_reference, system_of, system_paths,
)
from .simulation import DEFAULTS as SIM_DEFAULTS
from .simulation import Simulation

Index = Union[None, str, Sequence[str], Mapping[str, str]]
XY = Tuple[float, float]

#: The kinds whose blocks hold an inventory: what a flux may run between.
HOLDS_INVENTORY = frozenset({'compartment', 'farfield', 'waste_package'})
#: The kinds whose value is a release a transfer drawn out of them carries.
RELEASING = frozenset({'farfield', 'waste_package'})
#: The equations each block that remembers writes, and the triggers it names.
RECORDER_EQUATIONS = {
    'min_max': ('target',), 'running_mean': ('target',), 'snapshot': ('target', 'initial'),
    'delay': ('target', 'delay'), 'trigger': ('first', 'second'),
}
RECORDER_TRIGGERS = {
    'min_max': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_mean': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshot': ('trigger',), 'delay': (), 'trigger': (),
}
RECORDER_COLLECTION = {
    'min_max': 'min_maxes', 'running_mean': 'running_means', 'snapshot': 'snapshots',
    'delay': 'delays', 'trigger': 'triggers',
}
#: The value key each kind stores per index (``ENTRY_KEY`` in edit.js).
ENTRY_KEY = {
    'compartment': 'initial', 'transfer': 'rate', 'expression': 'equation', 'parameter': 'value',
    'inflow': 'rate', 'lookup': 'points', 'index_reduction': 'target', 'block_reduction': 'targets',
    'function': 'equation', 'farfield': 'kd_f', 'waste_package': 'inventory', 'event': 'at',
}
#: The name each kind is given when none is.
DEFAULT_NAME = {
    'compartment': 'C', 'expression': 'E', 'parameter': 'p', 'lookup': 'L',
    'index_reduction': 'Total', 'block_reduction': 'Sum', 'function': 'Func', 'min_max': 'Peak',
    'running_mean': 'Mean', 'snapshot': 'Snapshot', 'delay': 'Delayed', 'trigger': 'Trigger',
    'inflow': 'In', 'farfield': 'Farfield', 'waste_package': 'Packages', 'event': 'Event',
}
DECAY_UNITS = ('Bq', 'mol')
CONNECTION_LABELS = ('name', 'rate', 'none')
INFLUENCE_MODES = ('none', 'all', 'selected')
DERIVED_KINDS = ('max', 'min', 'time_of_max', 'at_time', 'integral', 'period_mean',
                 'period_sum', 'period_change', 'period_rate')
PERIOD_KINDS = ('period_mean', 'period_sum', 'period_change', 'period_rate')
SHAPE_COLORS = ('slate', 'blue', 'teal', 'green', 'olive', 'amber', 'orange', 'red', 'purple', 'brown')
SHAPE_DASHES = ('solid', 'dashed', 'dotted')
SHAPE_TEXT_FONTS = ('sans', 'scribble', 'serif', 'mono')
SHAPE_TEXT_ALIGNS = ('left', 'center', 'right')
NOT_REVIEWED = frozenset({'x', 'y', 'w', 'h', 'shape', 'colour', 'color', 'label', 'collapsed',
                          'comment', 'note', 'notes', 'qa'})
EDGE_PREFIX = 'edge:'

#: What the diagram shows when a model says nothing.
DEFAULT_VIEW: Dict[str, Any] = {
    'show_expressions': True, 'show_parameters': False, 'show_lookups': True,
    'show_reductions': True, 'show_functions': True, 'show_warning_list': True,
    'show_recorders': True, 'show_influences': False, 'show_sinks': True, 'show_sources': True,
    'show_help': False, 'show_grid': True, 'snap_to_grid': True, 'connection_label': 'name',
}


def _blank(name: str) -> Dict[str, Any]:
    """A new model, as the application's *New* makes one."""
    return {
        'name': name,
        'description': '',
        'simulation': dict(SIM_DEFAULTS, end_time=1000),
        'parameters': [], 'compartments': [], 'transfers': [], 'expressions': [], 'inflows': [],
    }


def _js_string(v: Any) -> str:
    """``String(v ?? '')``, as the application reads a unit."""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return js_number(v)
    return str(v)


def _js_number(v: Any) -> float:
    """``Number(v)``: NaN where JavaScript would give NaN."""
    if v is None:
        return math.nan
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return math.nan


def _js_round(v: float) -> int:
    """``Math.round``: halves go up, towards positive infinity."""
    return int(math.floor(float(v) + 0.5))


def _per(quantity: str, time: str) -> str:
    """``Bq/m3`` over a year is ``(Bq/m3)/year``, not ``Bq/m3/year``."""
    return f'({quantity})/{time}' if any(c in quantity for c in '/ \t\n\r\f\v') else f'{quantity}/{time}'


def _parse_edge_key(key: str) -> Optional[Tuple[str, Optional[str]]]:
    if not str(key).startswith(EDGE_PREFIX):
        return None
    rest = key[len(EDGE_PREFIX):]
    at = rest.find('@')
    return (rest, None) if at < 0 else (rest[:at], rest[at + 1:])


def _edge_key(name: str, view: Optional[str] = None) -> str:
    return EDGE_PREFIX + name if view is None else f'{EDGE_PREFIX}{name}@{view}'


def _prune_entries(block: Dict[str, Any], dims: Sequence[str]) -> None:
    if block.get('entries'):
        block['entries'] = [e for e in block['entries']
                            if all(k in dims for k in (e.get('index') or {}))]


def _position_of(xy: Any) -> XY:
    if isinstance(xy, Mapping):
        return (float(xy['x']), float(xy['y']))
    x, y = xy
    return (float(x), float(y))


class _BlockList(dict):
    """``Compartments`` or ``Transfers``: one index per block, derived from the
    model. Its indices are only worked out when something reads them, so a
    model with thousands of blocks does not rebuild the list on every edit."""

    def __init__(self, model: Dict[str, Any], name: str, collection: str, what: str) -> None:
        super().__init__(name=name, derived=True, auto=collection,
                         note=(f'One index per {what} in the model \u2014 the {what}s are the '
                               f'indices, so there is nothing to edit here. Add a {what} and '
                               'this list gains an index; rename one and the index follows.'))
        self._model = model
        self._collection = collection

    def _fill(self) -> None:
        if dict.__contains__(self, 'indices'):
            return
        names = []
        for b in self._model.get(self._collection) or []:
            if not isinstance(b, dict) or b.get('hidden'):
                continue
            n = f"{b['system']}.{b.get('name')}" if b.get('system') else b.get('name')
            if isinstance(n, str) and n:
                names.append(n)
        dict.__setitem__(self, 'indices', [{'name': n, 'enabled': True} for n in names])

    def get(self, key: Any, default: Any = None) -> Any:
        if key == 'indices':
            self._fill()
        return dict.get(self, key, default)

    def __getitem__(self, key: Any) -> Any:
        if key == 'indices':
            self._fill()
        return dict.__getitem__(self, key)

    def __contains__(self, key: object) -> bool:
        return key == 'indices' or dict.__contains__(self, key)


class View:
    """What the diagram shows: the model's ``view`` settings, defaults filled in.

    Every setting is an attribute -- ``show_parameters``, ``show_influences``
    (``'none'``, ``'all'`` or ``'selected'``), ``connection_label`` (``'name'``,
    ``'rate'`` or ``'none'``) and the rest of :data:`DEFAULT_VIEW`.
    """

    def __init__(self, model: 'Model') -> None:
        object.__setattr__(self, '_model', model)

    def __getattr__(self, key: str) -> Any:
        if key not in DEFAULT_VIEW:
            raise AttributeError(key)
        return (self._model._raw.get('view') or {}).get(key, DEFAULT_VIEW[key])

    def __setattr__(self, key: str, value: Any) -> None:
        if key not in DEFAULT_VIEW:
            raise AttributeError(f"The view has no setting '{key}'")
        self.set(**{key: value})

    def set(self, **settings: Any) -> None:
        """Sets several view settings at once."""
        label = settings.get('connection_label')
        if label is not None and label not in CONNECTION_LABELS:
            raise EditError(f"'{label}' is not a label mode ({', '.join(CONNECTION_LABELS)})")
        inf = settings.get('show_influences')
        if inf is not None and not isinstance(inf, bool) and inf not in INFLUENCE_MODES:
            raise EditError(f"'{inf}' is not a way of showing influences ({', '.join(INFLUENCE_MODES)})")
        merged = dict(DEFAULT_VIEW)
        merged.update(self._model._raw.get('view') or {})
        merged.update(settings)
        self._model._raw['view'] = merged

    def to_dict(self) -> Dict[str, Any]:
        out = dict(DEFAULT_VIEW)
        out.update(self._model._raw.get('view') or {})
        return out

    def __repr__(self) -> str:
        return f'View({self.to_dict()})'


class IndexList:
    """One index list of the model, as a view onto its dictionary.

    Edits go through the model, which carries a renamed or removed index into
    every per-index value, sub-set, mapping and equation that names it.
    """

    def __init__(self, model: 'Model', raw: Dict[str, Any]) -> None:
        self._model = model
        self._raw = raw

    @property
    def raw(self) -> Dict[str, Any]:
        """The list's own dictionary, live."""
        return self._raw

    @property
    def name(self) -> str:
        return self._raw.get('name', '')

    @property
    def indices(self) -> List[str]:
        """Every index, switched on or not, in order."""
        return [index_name(i) for i in self._raw.get('indices') or []]

    @property
    def enabled_indices(self) -> List[str]:
        """The indices that take part in the run, in order."""
        return [index_name(i) for i in self._raw.get('indices') or []
                if not (isinstance(i, dict) and i.get('enabled') is False)]

    @property
    def is_materials(self) -> bool:
        """Whether this is the built-in material catalogue."""
        return bool(self._raw.get('for_contaminants'))

    @property
    def is_nuclides(self) -> bool:
        """Whether this is the built-in radionuclide list."""
        return bool(self._raw.get('for_nuclides'))

    @property
    def is_scenarios(self) -> bool:
        """Whether this list holds the model's scenarios."""
        return bool(self._raw.get('for_scenarios'))

    @property
    def is_derived(self) -> bool:
        """Whether the list is worked out from the model rather than stored."""
        return bool(self._raw.get('derived'))

    @property
    def subset_of(self) -> Optional[str]:
        """The list this is a sub-set of, or ``None``."""
        return self._raw.get('sub_set_of')

    @property
    def mapping(self) -> Optional[Dict[str, Any]]:
        """``{'to': list, 'pairs': [{'from': own index, 'to': parent index}]}``, or ``None``."""
        return self._raw.get('mapping')

    @property
    def comment(self) -> str:
        """Free text about the list."""
        return self._raw.get('comment', '')

    @comment.setter
    def comment(self, text: Optional[str]) -> None:
        if text:
            self._raw['comment'] = str(text)
        else:
            self._raw.pop('comment', None)

    def add_index(self, name: str) -> None:
        """Adds an index. A radionuclide goes into the catalogue as well, and is
        made stable if ICRP 107 does not know its half-life."""
        self._model.add_index(self.name, name)

    def add_indices(self, names: Iterable[str]) -> None:
        for n in names:
            self.add_index(n)

    def remove_index(self, name: str) -> None:
        """Removes an index, and every per-index value keyed by it."""
        self._model.remove_index(self.name, name)

    def rename_index(self, old: str, new: str) -> None:
        """Renames an index everywhere it is written."""
        self._model.rename_index(self.name, old, new)

    def set_enabled(self, name: str, on: bool) -> None:
        """Takes an index out of the run (``False``) or back in; its values stay."""
        self._model.set_index_enabled(self.name, name, on)

    def map_index(self, parent_index: str, own_index: Optional[str]) -> None:
        """For a mapping: which of this list's indices ``parent_index`` belongs to."""
        self._model.map_index(self.name, parent_index, own_index)

    def rename(self, new_name: str) -> None:
        """Renames the list, and every block dimension and per-index value keyed by it."""
        self._model.rename_index_list(self.name, new_name)

    def delete(self) -> None:
        """Deletes the list; refused while anything is indexed by it."""
        self._model.delete_index_list(self.name)

    def users(self) -> List[str]:
        """The lists defined from this one, and the blocks indexed by it."""
        return self._model.index_list_users(self.name)

    def __repr__(self) -> str:
        shown = self.indices
        more = '...' if len(shown) > 6 else ''
        return f'<IndexList {self.name}: {", ".join(shown[:6])}{more}>'


class Shape:
    """An annotation drawn on a sub-system's canvas: a box, an arrow, a figure,
    a sticky note. Nothing in the model reads it."""

    ALLOWED = ('figure', 'x', 'y', 'w', 'h', 'fill', 'line', 'line_width', 'dash', 'text',
               'text_size', 'text_font', 'text_align', 'text_bold', 'text_italic', 'flip_x', 'flip_y')

    def __init__(self, model: 'Model', raw: Dict[str, Any]) -> None:
        self._model = model
        self._raw = raw

    @property
    def raw(self) -> Dict[str, Any]:
        return self._raw

    @property
    def id(self) -> str:
        return self._raw.get('id', '')

    @property
    def system(self) -> str:
        """The sub-system whose canvas it is drawn on; ``''`` is the top level."""
        return self._raw.get('system') or ''

    def __getattr__(self, key: str) -> Any:
        if key in Shape.ALLOWED:
            return self._raw.get(key)
        raise AttributeError(key)

    def update(self, **patch: Any) -> 'Shape':
        """Changes the shape's properties, checked as the application checks
        them: ``fill`` and ``line`` one of :data:`SHAPE_COLORS` or ``'none'``;
        ``dash``, ``text_font`` and ``text_align`` from their lists."""
        for key, value in patch.items():
            if key not in Shape.ALLOWED:
                raise EditError(f"A shape has no '{key}'")
            if key in ('fill', 'line'):
                v = _js_string(value).strip()
                if v != 'none' and v not in SHAPE_COLORS:
                    raise EditError(f"'{value}' is not a shape colour ({', '.join(SHAPE_COLORS)}, none)")
                self._raw[key] = v
                continue
            if key == 'dash' and value not in SHAPE_DASHES:
                raise EditError(f"'{value}' is not a line style")
            if key == 'text_font' and value not in SHAPE_TEXT_FONTS:
                raise EditError(f"'{value}' is not a hand to write in ({', '.join(SHAPE_TEXT_FONTS)})")
            if key == 'text_align' and value not in SHAPE_TEXT_ALIGNS:
                raise EditError(f"'{value}' is not an alignment ({', '.join(SHAPE_TEXT_ALIGNS)})")
            if key in ('text_bold', 'text_italic', 'flip_x', 'flip_y'):
                if value:
                    self._raw[key] = True
                else:
                    self._raw.pop(key, None)
                continue
            if key == 'text':
                text = _js_string(value)
                if text.strip():
                    self._raw['text'] = text
                else:
                    self._raw.pop('text', None)
                continue
            self._raw[key] = value
        return self

    def move_to(self, system: str) -> None:
        """Moves the shape onto another sub-system's canvas."""
        if system and system not in self._model.systems:
            raise EditError(f"No sub-system named '{system}'")
        if system:
            self._raw['system'] = system
        else:
            self._raw.pop('system', None)

    def delete(self) -> None:
        self._model.remove_shape(self.id)

    def __repr__(self) -> str:
        return f"<Shape {self.id} {self._raw.get('figure')} on '{self.system}'>"


class Model:
    """A Kompartment model. See the module documentation."""

    # --- making one ---------------------------------------------------------------

    def __init__(self, data: Optional[Mapping[str, Any]] = None, *, normalise: bool = True) -> None:
        """A model from a project dictionary (which is copied), or a new empty
        model.

        ``normalise`` brings it into the shape Kompartment works on, as the
        application does when it opens a file; leave it on unless you mean to
        edit the dictionary exactly as it is.
        """
        raw = copy.deepcopy(dict(data)) if data is not None else _blank('New model')
        self._raw: Dict[str, Any] = migrate_keys(raw) if normalise else raw
        self._index: Optional[Dict[str, Tuple[str, Dict[str, Any]]]] = None
        self._index_fp: Any = None
        self._systems: Optional[List[str]] = None
        self._systems_fp: Any = None
        self._system_lookup: Set[str] = set()
        #: What an import from another tool reported (see :meth:`from_eco`).
        self.import_report: Any = None
        #: What the last export to another tool reported (see :meth:`to_eco`).
        self.export_report: Any = None
        if normalise:
            self._normalise()
            self._sync_derived_units()

    @classmethod
    def new(cls, name: str = 'New model', description: str = '') -> 'Model':
        """A new, empty model, as the application's *New* makes one: 0 to 1000
        years on a log grid, the default solver and tolerances, and the two
        material lists, empty."""
        raw = _blank(name)
        raw['description'] = description
        return cls(raw)

    @classmethod
    def load(cls, path: PathLike, *, normalise: bool = True) -> 'Model':
        """Reads a model file: ``.json``, ``.json.gz`` or ``.zip``."""
        return cls(read_model_file(path), normalise=normalise)

    @classmethod
    def from_json(cls, text: str, *, normalise: bool = True) -> 'Model':
        """A model from the text of a project file."""
        data = json.loads(text)
        if not isinstance(data, dict):
            raise EditError('A model is one JSON object')
        return cls(data, normalise=normalise)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, normalise: bool = True) -> 'Model':
        """A model from a project dictionary, which is copied."""
        return cls(data, normalise=normalise)

    @classmethod
    def from_eco(cls, source: Any, *, file_name: Optional[str] = None, version: Optional[str] = None) -> 'Model':
        """A model imported from an Ecolego project (``.eco``), assessment
        (``.eas``) or bare ``model.xml``, as the application's *Import* reads
        it: ``source`` is a path or the file's bytes.

        What the import left out, renamed or switched off is in
        ``model.import_report`` (``skipped``, ``renamed``, ``disabled``,
        ``warnings``, ``counts``); read it before trusting the numbers.
        Raises :class:`kompartment.importers.eco.EcoImportError` for a file
        that cannot be read.
        """
        from .importers.eco import import_eco_file
        project, report = import_eco_file(source, file_name=file_name, version=version)
        m = cls(project)
        m.import_report = report
        return m

    def copy(self) -> 'Model':
        """An independent copy."""
        return Model(self._raw, normalise=False)

    # --- writing it ---------------------------------------------------------------------

    @property
    def raw(self) -> Dict[str, Any]:
        """The project dictionary itself, live. Editing it directly bypasses
        every check: a block renamed or moved this way leaves its references
        behind."""
        return self._raw

    def to_dict(self) -> Dict[str, Any]:
        """The project dictionary, settled (see :meth:`settle`), as a deep copy."""
        self.settle()
        return copy.deepcopy(self._raw)

    def to_json(self, indent: int = 2) -> str:
        """The project file's text, settled and formatted as the application
        writes it: a model saved by the application round-trips byte for byte."""
        self.settle()
        return dumps(self._raw, indent)

    def save(self, path: PathLike, indent: int = 2) -> Path:
        """Writes the model: ``.json``, ``.json.gz`` or ``.zip`` by the ending --
        or ``.eco``, an Ecolego 6 project, as :meth:`to_eco` makes it; what that
        left out is then in ``model.export_report``."""
        if str(path).lower().endswith('.eco'):
            p = Path(path)
            p.write_bytes(self.to_eco().bytes)
            return p
        self.settle()
        return write_model_file(path, self._raw, indent)

    def to_eco(self, *, modified: Any = None) -> Any:
        """The model as an Ecolego 6 project (``.eco``), as the application's
        *Save* writes one: ``(bytes, xml, report)``, the archive, its
        ``model.xml`` and what the export did.

        The report says what an Ecolego project has no place for and was left
        out (``skipped``), what was written as an equivalent Ecolego construct
        (``rewritten``), what was renamed and what else is worth knowing; it is
        also kept as ``model.export_report``. The same model gives the same
        bytes as the application's export. ``modified`` (a datetime) is written
        as the project's modification date and on the archive's entries. See
        :mod:`kompartment.io.ecoexport`.
        """
        from .io.ecoexport import export_eco
        out = export_eco(self, modified=modified)
        self.export_report = out.report
        return out

    def __repr__(self) -> str:
        counts = ', '.join(f'{len(self._raw.get(c) or [])} {c}' for c in COLLECTIONS if self._raw.get(c))
        return f"<Model {self.name!r}: {counts or 'empty'}>"

    # --- the shape Kompartment works on (materialiseShorthand) ------------------------------

    def _normalise(self) -> None:
        raw = self._raw
        if raw.get('nuclides') and not any(
                isinstance(l, dict) and (l.get('for_contaminants') or l.get('for_nuclides'))
                for l in raw.get('index_lists') or []):
            indices = [{'name': n, 'enabled': True} for n in raw['nuclides']]
            raw['index_lists'] = [
                {'name': MATERIAL_LIST, 'for_contaminants': True, 'indices': [dict(i) for i in indices]},
                {'name': NUCLIDE_LIST, 'for_nuclides': True, 'sub_set_of': MATERIAL_LIST, 'indices': indices},
                *(raw.get('index_lists') or []),
            ]
        self._materialise_legacy_entries()
        self._ensure_material_lists()
        self._qualify_endpoints()
        self._make_dimensions_explicit()

    def _materialise_legacy_entries(self) -> None:
        for collection in COLLECTIONS:
            key = ENTRY_KEY.get(SINGULAR[collection])
            if key is None:
                continue
            for b in self._raw.get(collection) or []:
                if not isinstance(b, dict) or 'default' not in b:
                    continue
                if key not in b:
                    b[key] = b['default']
                del b['default']
        material = self.material_dimension()
        if not material:
            return

        def add(block: Dict[str, Any], index: Dict[str, str], key: str, value: Any) -> None:
            if not isinstance(block.get('entries'), list):
                block['entries'] = []
            for e in block['entries']:
                if (e.get('index') or {}) == index:
                    if key not in e:
                        e[key] = value
                    return
            block['entries'].append({'index': index, key: value})

        for p in self._raw.get('parameters') or []:
            vmap = p.get('values_by_nuclide')
            if not vmap or not isinstance(vmap, dict):
                continue
            if material not in self._effective_dims(p):
                continue
            for nuc, v in vmap.items():
                add(p, {material: nuc}, 'value', _js_number(v))
            del p['values_by_nuclide']
        for c in self._raw.get('compartments') or []:
            imap = c.get('initial')
            if not imap or not isinstance(imap, dict):
                continue
            if material not in self._effective_dims(c):
                continue
            for nuc, v in imap.items():
                add(c, {material: nuc}, 'initial', _js_string(v))
            c['initial'] = '0'

    def _ensure_material_lists(self) -> None:
        split = split_material_roles(self._raw)
        if split is not self._raw and isinstance(split.get('index_lists'), list):
            self._raw['index_lists'] = split['index_lists']
        materials = self._material_list_raw()
        nuclides = next((l for l in self._stored_lists() if l.get('for_nuclides')), None)
        if materials is not None and nuclides is not None:
            return
        self._make_dimensions_explicit()
        if not isinstance(self._raw.get('index_lists'), list):
            self._raw['index_lists'] = []
        lists = self._raw['index_lists']
        if materials is None:
            materials = {
                'name': self._unique_list_name(MATERIAL_LIST),
                'for_contaminants': True,
                'comment': 'Every material the model knows.',
                'indices': [{'name': i, 'enabled': True} if isinstance(i, str) else dict(i)
                            for i in (nuclides or {}).get('indices') or []],
            }
            lists.insert(0, materials)
        if nuclides is None:
            nuclides = {
                'name': self._unique_list_name(NUCLIDE_LIST),
                'for_nuclides': True,
                'sub_set_of': materials['name'],
                'comment': 'The materials that have a half-life.',
                'indices': [],
            }
            at = next(k for k, l in enumerate(lists) if l is materials)
            lists.insert(at + 1, nuclides)
        self._sync_nuclides()

    def _unique_list_name(self, base: str) -> str:
        if not self._list_any(base):
            return base
        for i in range(1, 1000):
            if not self._list_any(f'{base}{i}'):
                return f'{base}{i}'
        raise EditError(f"Could not find a free name based on '{base}'")

    def _qualify_endpoints(self) -> None:
        ends = {qualified_name(c) for c in self._raw.get('compartments') or [] if isinstance(c, dict)}
        known = ends.__contains__
        for conn in (self._raw.get('transfers') or []) + (self._raw.get('inflows') or []):
            if not isinstance(conn, dict):
                continue
            for end in ('from', 'to'):
                ref = conn.get(end)
                if ref is None:
                    continue
                if not known(ref):
                    conn[end] = resolve_reference(ref, system_of(conn), known) or ref

    def _make_dimensions_explicit(self) -> None:
        for collection in COLLECTIONS:
            for b in self._raw.get(collection) or []:
                if isinstance(b, dict):
                    b['index_lists'] = self._effective_dims(b)
                    b.pop('per_nuclide', None)

    def _sync_nuclides(self) -> None:
        lst = self._nuclide_list_raw()
        if lst is None:
            self._raw.pop('nuclides', None)
            return
        self._raw['nuclides'] = [index_name(i) for i in lst.get('indices') or []
                                 if not (isinstance(i, dict) and i.get('enabled') is False)]

    # --- what follows from the model (syncDerivedUnits, pruneLayout) --------------------------

    def settle(self) -> List[str]:
        """Brings what follows from the model up to date, as the application
        does after every edit: every flux's dimensions from its two ends (and
        every transport's from what it is connected to), a blank compartment
        unit on a material dimension from the materials, every transfer's and
        inflow's unit from its donor and the time unit, and the diagram
        entries of blocks that no longer exist dropped.

        Runs by itself whenever the model is written out or checked. Returns
        the names of the blocks it changed.
        """
        self._prune_layout()
        return self._sync_derived_units()

    def _prune_layout(self) -> None:
        layout = self._raw.get('layout')
        if not layout or not isinstance(layout, dict):
            return
        names = set(self.systems) | set(self._idx())
        for k in list(layout):
            edge = _parse_edge_key(k)
            owner = edge[0] if edge else k
            canvas_gone = edge is not None and edge[1] not in (None, '') and edge[1] not in names
            if owner not in names or canvas_gone:
                del layout[k]

    def _sync_derived_units(self) -> List[str]:
        changed = self._sync_transfer_dimensions()
        changed += self._sync_inventory_units()
        changed += self._sync_flux_units()
        return changed

    def _sync_transfer_dimensions(self) -> List[str]:
        lists = self._lists()
        changed = self._sync_transport_inheritance(lists)
        for collection in ('transfers', 'inflows'):
            for b in self._raw.get(collection) or []:
                if not isinstance(b, dict):
                    continue
                shared = self._transfer_dims(b, lists)
                if shared is None or not isinstance(b.get('index_lists'), list):
                    continue
                if self._narrows(b['index_lists'], shared['dims'], lists):
                    continue
                b['index_lists'] = list(shared['dims'])
                changed.append(b.get('name'))
        return changed

    def _material_dimension_names(self) -> List[str]:
        lists = self._lists()
        root = next((l['name'] for l in lists if l.get('for_contaminants')), None)
        if not root:
            name = self.material_dimension()
            return [name] if name else []
        return [l['name'] for l in lists if is_decay_dim(lists, l['name'], root) and l.get('indices')]

    def _sync_inventory_units(self) -> List[str]:
        names = self._material_dimension_names()
        if not names:
            return []
        want = {n: self._dimension_unit(n) for n in names}
        filled = []
        for c in self._raw.get('compartments') or []:
            if not isinstance(c, dict):
                continue
            on = next((d for d in self._effective_dims(c) if d in want), None)
            if on is None or _js_string(c.get('unit')).strip():
                continue
            u = want[on]
            if not u:
                continue
            c['unit'] = u
            filled.append(c.get('name'))
        return filled

    def _material_unit(self, name: str) -> str:
        lists = self._stored_lists()
        catalogue = next((l for l in lists if l.get('for_contaminants')), None)
        own = next((i for i in (catalogue or {}).get('indices') or []
                    if isinstance(i, dict) and i.get('name') == name), None)
        stated = _js_string((own or {}).get('unit')).strip()
        if stated:
            return stated
        nuclides = next((l for l in lists if l.get('for_nuclides')), None) or catalogue
        if nuclides is not None:
            is_nuclide = any(index_name(i) == name for i in nuclides.get('indices') or [])
        else:
            is_nuclide = name in (self._raw.get('nuclides') or [])
        return self.decay_unit if is_nuclide else ''

    def _dimension_unit(self, list_name: str) -> str:
        lists = self._stored_lists()
        lst = find_list(lists, list_name)
        if lst is None:
            return '' if any(l.get('for_contaminants') or l.get('for_nuclides') for l in lists) \
                else self.decay_unit
        one = None
        for i in lst.get('indices') or []:
            if isinstance(i, dict) and i.get('enabled') is False:
                continue
            u = self._material_unit(index_name(i))
            if not u:
                return ''
            if one is None:
                one = u
            elif one != u:
                return ''
        return one or ''

    def _time_unit(self) -> str:
        sim = self._raw.get('simulation') or {}
        return sim.get('time_unit') if sim.get('time_unit') is not None else 'year'

    def _unit_of_compartment(self, name: Optional[str]) -> str:
        if name is None:
            return ''
        cs = [c for c in self._raw.get('compartments') or [] if isinstance(c, dict)]
        c = next((x for x in cs if qualified_name(x) == name), None) \
            or next((x for x in cs if x.get('name') == name), None)
        return _js_string(c.get('unit')).strip() if c else ''

    def _transfer_unit(self, raw: Dict[str, Any]) -> str:
        t = self._time_unit()
        if raw.get('multiply_by_donor') is not False:
            return f'1/{t}'
        paths = [f for f in self._raw.get('farfields') or [] if isinstance(f, dict)]
        path = next((f for f in paths if qualified_name(f) == raw.get('from')), None) \
            or next((f for f in paths if f.get('name') == raw.get('from')), None)
        if path is not None:
            return _js_string(path.get('unit')).strip()
        u = self._unit_of_compartment(raw.get('from') if raw.get('from') is not None else raw.get('to'))
        return _per(u, t) if u else ''

    def _inflow_unit(self, raw: Dict[str, Any]) -> str:
        u = self._unit_of_compartment(raw.get('to'))
        return _per(u, self._time_unit()) if u else ''

    def derived_unit(self, block: Union[str, Block]) -> str:
        """The unit a transfer or an inflow carries, worked out from the model:
        ``1/<time>`` for a rate coefficient, the donor's unit per time for an
        absolute flux, the receiver's per time for an inflow; ``''`` when it
        cannot be known."""
        b = self.block(block) if isinstance(block, str) else block
        if b.kind == 'inflow':
            return self._inflow_unit(b.raw)
        if b.kind == 'transfer':
            return self._transfer_unit(b.raw)
        raise EditError(f"A {b.kind.replace('_', ' ')}'s unit is its own, not worked out")

    def _sync_flux_units(self) -> List[str]:
        changed = []
        for collection, unit_of in (('transfers', self._transfer_unit), ('inflows', self._inflow_unit)):
            for b in self._raw.get(collection) or []:
                if not isinstance(b, dict):
                    continue
                want = unit_of(b)
                if _js_string(b.get('unit')) == want:
                    continue
                if want:
                    b['unit'] = want
                else:
                    b.pop('unit', None)
                changed.append(b.get('name'))
        return changed

    # --- blocks by name -------------------------------------------------------------------

    def _fingerprint(self) -> Tuple[Any, ...]:
        r = self._raw
        return tuple((id(r.get(c)), len(r.get(c) or ())) for c in COLLECTIONS)

    def _rebuild_index(self) -> None:
        index: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        for collection in COLLECTIONS:
            for b in self._raw.get(collection) or []:
                if isinstance(b, dict):
                    index.setdefault(qualified_name(b), (collection, b))
        self._index = index
        self._index_fp = self._fingerprint()

    def _idx(self) -> Dict[str, Tuple[str, Dict[str, Any]]]:
        if self._index is None or self._index_fp != self._fingerprint():
            self._rebuild_index()
        assert self._index is not None
        return self._index

    def _invalidate(self) -> None:
        """Forgets what is cached about the model's names and sub-systems."""
        self._index = None
        self._systems = None

    def _register(self, collection: str, raw: Dict[str, Any]) -> None:
        """Adds a block that has just been appended to the name index."""
        if self._index is not None:
            self._index.setdefault(qualified_name(raw), (collection, raw))
            self._index_fp = self._fingerprint()

    def _find(self, name: Optional[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
        if name is None:
            return None
        hit = self._idx().get(name)
        if hit is not None and qualified_name(hit[1]) != name:
            self._rebuild_index()
            hit = self._idx().get(name)
        return hit

    def _names(self) -> Set[str]:
        return set(self._idx())

    def _known(self, extra: Iterable[str] = ()) -> Callable[[str], bool]:
        idx = self._idx()
        more = set(extra)
        if more:
            return lambda n: n in idx or n in more
        return idx.__contains__

    def _kind_of(self, name: Optional[str]) -> Optional[str]:
        hit = self._find(name)
        return SINGULAR[hit[0]] if hit else None

    def get(self, name: str) -> Optional[Block]:
        """The block of that qualified name, or ``None``."""
        hit = self._find(name)
        return _view_of(self, hit[0], hit[1]) if hit else None

    def block(self, name: str) -> Block:
        """The block of that qualified name; :class:`EditError` if there is none."""
        b = self.get(name)
        if b is None:
            raise EditError(f"No block named '{name}'")
        return b

    def __getitem__(self, name: str) -> Block:
        return self.block(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self._find(name) is not None

    def blocks(self, kind: Optional[str] = None, system: Optional[str] = None,
               deep: bool = True) -> List[Block]:
        """Every block, or those of one ``kind`` (``'compartment'``,
        ``'transfer'``, ...), or those in one sub-system (``deep``: and in the
        sub-systems inside it)."""
        if kind is not None and kind not in KINDS:
            raise EditError(f"'{kind}' is not a kind of block ({', '.join(KINDS)})")
        out = []
        for collection in COLLECTIONS:
            if kind is not None and SINGULAR[collection] != kind:
                continue
            for b in self._raw.get(collection) or []:
                if not isinstance(b, dict):
                    continue
                if system is not None:
                    home = system_of(b)
                    if not (is_within(home, system) if deep else home == system):
                        continue
                out.append(_view_of(self, collection, b))
        return out

    def __iter__(self) -> Iterator[Block]:
        return iter(self.blocks())

    def names(self, kind: Optional[str] = None) -> List[str]:
        """The qualified names of every block, or of one kind."""
        return [b.qualified_name for b in self.blocks(kind)]

    def _collection_views(self, collection: str) -> List[Any]:
        return [_view_of(self, collection, b) for b in self._raw.get(collection) or [] if isinstance(b, dict)]

    @property
    def compartments(self) -> List[Compartment]:
        """Every compartment."""
        return self._collection_views('compartments')

    @property
    def transfers(self) -> List[Transfer]:
        """Every transfer."""
        return self._collection_views('transfers')

    @property
    def inflows(self) -> List[Inflow]:
        """Every inflow (source term)."""
        return self._collection_views('inflows')

    @property
    def parameters(self) -> List[Parameter]:
        """Every parameter."""
        return self._collection_views('parameters')

    @property
    def expressions(self) -> List[Expression]:
        """Every expression."""
        return self._collection_views('expressions')

    @property
    def lookups(self) -> List[Lookup]:
        """Every lookup table."""
        return self._collection_views('lookups')

    @property
    def index_reductions(self) -> List[IndexReduction]:
        """Every index reduction."""
        return self._collection_views('index_reductions')

    @property
    def block_reductions(self) -> List[BlockReduction]:
        """Every block reduction (aggregate)."""
        return self._collection_views('block_reductions')

    @property
    def functions(self) -> List[Function]:
        """Every function."""
        return self._collection_views('functions')

    @property
    def min_maxes(self) -> List[MinMax]:
        """Every min/max."""
        return self._collection_views('min_maxes')

    @property
    def running_means(self) -> List[RunningMean]:
        """Every running mean."""
        return self._collection_views('running_means')

    @property
    def snapshots(self) -> List[Snapshot]:
        """Every snapshot."""
        return self._collection_views('snapshots')

    @property
    def delays(self) -> List[Delay]:
        """Every delay."""
        return self._collection_views('delays')

    @property
    def triggers(self) -> List[Trigger]:
        """Every trigger."""
        return self._collection_views('triggers')

    @property
    def farfields(self) -> List[Farfield]:
        """Every far-field path."""
        return self._collection_views('farfields')

    @property
    def waste_packages(self) -> List[WastePackage]:
        """Every set of waste packages."""
        return self._collection_views('waste_packages')

    @property
    def events(self) -> List[Event]:
        """Every disruptive event."""
        return self._collection_views('events')

    # --- the model's own name, description and settings ---------------------------------

    @property
    def name(self) -> str:
        """The model's name: shown in the header and used for the file name."""
        return str(self._raw.get('name') or '').strip() or 'Untitled model'

    @name.setter
    def name(self, value: str) -> None:
        self._raw['name'] = str(value or '').strip()

    @property
    def description(self) -> str:
        """Free text: what the model is and where it came from."""
        return str(self._raw.get('description') or '')

    @description.setter
    def description(self, value: str) -> None:
        self._raw['description'] = str(value or '')

    @property
    def simulation(self) -> Simulation:
        """The simulation settings."""
        if not isinstance(self._raw.get('simulation'), dict):
            self._raw['simulation'] = {}
        return Simulation(self._raw['simulation'])

    @property
    def view(self) -> View:
        """What the diagram shows."""
        return View(self)

    @property
    def layout(self) -> Dict[str, Any]:
        """Diagram geometry, keyed by qualified name (blocks and sub-systems),
        live. Presentation only: nothing in a run reads it."""
        if not isinstance(self._raw.get('layout'), dict):
            self._raw['layout'] = {}
        return self._raw['layout']

    # --- index lists ----------------------------------------------------------------------

    def _stored_lists(self) -> List[Dict[str, Any]]:
        return [l for l in self._raw.get('index_lists') or [] if isinstance(l, dict)]

    def _stored_list(self, name: Optional[str]) -> Optional[Dict[str, Any]]:
        return find_list(self._stored_lists(), name)

    def _lists(self) -> List[Dict[str, Any]]:
        """Every list, the derived ones (Elements, Compartments, Transfers) included."""
        out = derive_elements(self._stored_lists())
        for name, collection, what in ((COMPARTMENT_LIST, 'compartments', 'compartment'),
                                       (TRANSFER_LIST, 'transfers', 'transfer')):
            if any(l.get('name') == name for l in out):
                continue
            if not any(isinstance(b, dict) and not b.get('hidden') and isinstance(b.get('name'), str)
                       and b.get('name') for b in self._raw.get(collection) or []):
                continue
            out.append(_BlockList(self._raw, name, collection, what))
        return out

    def _list_any(self, name: Optional[str]) -> Optional[Dict[str, Any]]:
        return find_list(self._lists(), name)

    @property
    def index_lists(self) -> List[IndexList]:
        """The index lists the model stores (the derived ones are not stored)."""
        return [IndexList(self, l) for l in self._stored_lists()]

    def all_index_lists(self) -> List[IndexList]:
        """Every index list, including the derived ``Elements``,
        ``Compartments`` and ``Transfers``."""
        return [IndexList(self, l) for l in self._lists()]

    def index_list(self, name: str) -> IndexList:
        """The index list of that name (derived ones included)."""
        lst = self._list_any(name)
        if lst is None:
            raise EditError(f"No index list named '{name}'")
        return IndexList(self, lst)

    def _material_list_raw(self) -> Optional[Dict[str, Any]]:
        return next((l for l in self._stored_lists() if l.get('for_contaminants')), None)

    def _nuclide_list_raw(self) -> Optional[Dict[str, Any]]:
        lists = self._stored_lists()
        return (next((l for l in lists if l.get('for_nuclides')), None)
                or next((l for l in lists if l.get('for_contaminants')), None))

    def material_dimension(self) -> Optional[str]:
        """What a new block is indexed by when nothing says otherwise: the
        radionuclides, or the catalogue when there are none, or nothing when
        the model has no materials at all."""
        nuc = next((l for l in self._stored_lists() if l.get('for_nuclides')), None)
        explicit = nuc if nuc is not None and nuc.get('indices') else self._material_list_raw()
        if explicit is not None:
            return explicit['name'] if explicit.get('indices') else None
        if self._raw.get('nuclides'):
            return NUCLIDE_LIST
        return None

    def _editable(self, name: str) -> Dict[str, Any]:
        lst = self._list_any(name)
        if lst is not None and lst.get('derived'):
            follows = ("the model's compartments" if lst.get('auto') == 'compartments'
                       else "the model's transfers" if lst.get('auto') == 'transfers' else 'the nuclide list')
            raise EditError(f"'{name}' follows {follows}, so it cannot be edited on its own. "
                            f"Change {'the model' if lst.get('auto') else 'the nuclides'} and it changes with it.")
        if lst is None:
            raise EditError(f"No index list named '{name}'")
        lst['indices'] = normalise_indices(lst.get('indices') or [])
        return lst

    def add_index_list(self, name: str, indices: Sequence[str] = (), *,
                       subset_of: Optional[str] = None, mapping_to: Optional[str] = None,
                       pairs: Optional[Mapping[str, str]] = None, comment: Optional[str] = None,
                       scenarios: bool = False) -> IndexList:
        """Adds an index list.

        ``subset_of`` makes it a sub-set of another list, whose indices it has
        to be taken from; ``mapping_to`` a grouping of one, with ``pairs``
        saying which of this list's indices each of the other's belongs to
        (``{parent_index: own_index}``). ``scenarios`` makes it the model's
        scenario list, its first index the live scenario.

        Every block's current dimensions are written down first, as the
        application does, so adding a list changes what nothing is indexed by.
        """
        self._make_dimensions_explicit()
        if not NAME_RE.fullmatch(str(name)):
            raise EditError(f"'{name}' is not a valid index list name (letters, digits and "
                            'underscore; must not start with a digit)')
        if name in RESERVED:
            raise EditError(f"'{name}' is a reserved name.")
        if self._list_any(name):
            raise EditError(f"An index list named '{name}' already exists")
        if subset_of and mapping_to:
            raise EditError('A list is a sub-set of one list or a mapping onto one, not both')
        seen: Set[str] = set()
        for i in indices:
            self._check_index_name(i, name)
            if i in seen:
                raise EditError(f"'{i}' appears twice in index list '{name}'")
            seen.add(i)
        if subset_of:
            parent = self._list_any(subset_of)
            if parent is None:
                raise EditError(f"No index list named '{subset_of}'")
            have = {index_name(i) for i in parent.get('indices') or []}
            missing = [i for i in indices if i not in have]
            if missing:
                raise EditError(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not in "
                                f"'{subset_of}', so a sub-set of it cannot hold them")
        lst: Dict[str, Any] = {'name': name, 'indices': [{'name': i, 'enabled': True} for i in indices]}
        if comment:
            lst['comment'] = comment
        if not isinstance(self._raw.get('index_lists'), list):
            self._raw['index_lists'] = []
        self._raw['index_lists'].append(lst)
        try:
            if subset_of:
                self.set_list_role(name, 'sub_set', subset_of)
            elif mapping_to:
                self.set_list_role(name, 'mapping', mapping_to)
                for parent_index, own in (pairs or {}).items():
                    self.map_index(name, parent_index, own)
            if scenarios:
                self.set_scenario_list(name, True)
        except EditError:
            self._raw['index_lists'] = [l for l in self._raw['index_lists'] if l is not lst]
            raise
        return IndexList(self, lst)

    @staticmethod
    def _check_index_name(name: Any, list_name: str) -> None:
        text = str(name if name is not None else '')
        if not text.strip():
            raise EditError(f"An index of '{list_name}' has no name")
        if any(c in text for c in '\r\n  <>'):
            raise EditError(f"'{text}' is not a usable index name: an index may not contain a line "
                            'break or angle brackets')

    def set_list_role(self, name: str, role: str, target: Optional[str] = None) -> None:
        """Defines a list against another: ``role`` ``'plain'``, ``'sub_set'``
        (of ``target``) or ``'mapping'`` (onto ``target``)."""
        lst = self._editable(name)
        if lst.get('for_contaminants') or lst.get('for_nuclides') or lst.get('derived'):
            raise EditError(f"'{name}' is built in, so it cannot be defined from another list")
        if role == 'plain':
            lst.pop('sub_set_of', None)
            lst.pop('mapping', None)
            return
        parent = self._list_any(target) if target else None
        if parent is None:
            raise EditError(f"No index list named '{target}'")
        if parent.get('name') == name:
            raise EditError('A list cannot be defined from itself')
        if parent.get('sub_set_of') or parent.get('mapping'):
            raise EditError(f"'{parent['name']}' is itself defined from another list. A sub-set or a "
                            'mapping has to be taken from a root list.')
        if role == 'sub_set':
            lst.pop('mapping', None)
            lst['sub_set_of'] = parent['name']
            have = {index_name(i) for i in parent.get('indices') or []}
            lst['indices'] = [i for i in lst['indices'] if i['name'] in have]
            return
        if role == 'mapping':
            lst.pop('sub_set_of', None)
            m = lst.get('mapping')
            keep = (m.get('pairs') or []) if isinstance(m, dict) and m.get('to') == parent['name'] else []
            lst['mapping'] = {'to': parent['name'], 'pairs': keep}
            return
        raise EditError(f"'{role}' is not a way to define an index list (plain, sub_set, mapping)")

    def map_index(self, name: str, parent_index: str, own_index: Optional[str]) -> None:
        """In a mapped list: which of its indices ``parent_index`` belongs to
        (``None`` unassigns it)."""
        lst = self._editable(name)
        m = lst.get('mapping')
        if not isinstance(m, dict):
            raise EditError(f"'{name}' is not a mapped index list")
        parent = self._list_any(m.get('to'))
        if parent is None:
            raise EditError(f"No index list named '{m.get('to')}'")
        if parent_index not in [index_name(i) for i in parent.get('indices') or []]:
            raise EditError(f"'{parent_index}' is not an index of '{parent['name']}'")
        if own_index is not None and own_index not in [i['name'] for i in lst['indices']]:
            raise EditError(f"'{own_index}' is not an index of '{name}'")
        pairs = [p for p in m.get('pairs') or [] if p.get('to') != parent_index]
        if own_index is not None:
            pairs.append({'from': own_index, 'to': parent_index})
        m['pairs'] = pairs

    def set_scenario_list(self, name: str, on: bool = True) -> None:
        """Makes a list the model's scenarios (one list at most), or stops it being them."""
        lst = self._list_any(name)
        if lst is None:
            raise EditError(f"No index list named '{name}'")
        if on and (lst.get('for_contaminants') or lst.get('for_nuclides') or lst.get('derived')):
            raise EditError(f"'{name}' is built in, so it cannot be the scenarios")
        for other in self._stored_lists():
            if other is not lst:
                other.pop('for_scenarios', None)
        if on:
            lst['for_scenarios'] = True
        else:
            lst.pop('for_scenarios', None)
        names = self.scenarios
        if self._raw.get('scenario') not in names:
            if names:
                self._raw['scenario'] = names[0]
            else:
                self._raw.pop('scenario', None)

    @property
    def scenarios(self) -> List[str]:
        """The scenarios, when the model has a scenario list; the ones switched off do not run."""
        lst = next((l for l in self._stored_lists() if l.get('for_scenarios')), None)
        return IndexList(self, lst).enabled_indices if lst else []

    @property
    def scenario(self) -> Optional[str]:
        """Which scenario is live: the one chosen, or the first."""
        names = self.scenarios
        s = self._raw.get('scenario')
        return s if s in names else (names[0] if names else None)

    @scenario.setter
    def scenario(self, name: Optional[str]) -> None:
        if name is None:
            self._raw.pop('scenario', None)
            return
        if name not in self.scenarios:
            raise EditError(f"'{name}' is not a scenario in this model"
                            + (f" ({', '.join(self.scenarios)})" if self.scenarios else ''))
        self._raw['scenario'] = name

    def add_scenarios(self, names: Sequence[str], list_name: str = 'Scenarios') -> IndexList:
        """Gives the model a scenario list with these scenarios, the first live."""
        return self.add_index_list(list_name, names, scenarios=True)

    def rename_index_list(self, old: str, new: str) -> None:
        """Renames a list and follows it into every dimension, per-index value,
        sub-set and mapping."""
        self._editable(old)
        if old == new:
            return
        if not NAME_RE.fullmatch(str(new)):
            raise EditError('An index list name uses letters, digits and underscore, and may not '
                            'start with a digit.')
        if new in RESERVED:
            raise EditError(f"'{new}' is a reserved name.")
        lst = self._list_any(old)
        assert lst is not None
        if lst.get('for_contaminants') or lst.get('for_nuclides'):
            what = 'the material catalogue' if lst.get('for_contaminants') else 'the radionuclide dimension'
            raise EditError(f"'{old}' is {what} and keeps its name.")
        if self._list_any(new):
            raise EditError(f"An index list named '{new}' already exists")
        lst['name'] = new
        for other in self._lists():
            if other.get('sub_set_of') == old:
                other['sub_set_of'] = new
            if isinstance(other.get('mapping'), dict) and other['mapping'].get('to') == old:
                other['mapping']['to'] = new
        for b in self._all_raw():
            if isinstance(b.get('index_lists'), list):
                b['index_lists'] = [new if d == old else d for d in b['index_lists']]
            for e in b.get('entries') or []:
                ix = e.get('index')
                if isinstance(ix, dict) and old in ix:
                    ix[new] = ix.pop(old)

    def index_list_users(self, name: str) -> List[str]:
        """The lists defined from ``name`` and the blocks indexed by it."""
        users: List[str] = []
        for other in self._lists():
            m = other.get('mapping')
            if other.get('sub_set_of') == name or (isinstance(m, dict) and m.get('to') == name):
                users.append(other['name'])
        for b in self._all_raw():
            if name in (b.get('index_lists') or []):
                users.append(qualified_name(b))
        return list(dict.fromkeys(users))

    def delete_index_list(self, name: str) -> None:
        """Deletes a list; refused while anything is defined from it or indexed by it."""
        lst = self._editable(name)
        if lst.get('for_contaminants') or lst.get('for_nuclides'):
            what = 'the material catalogue' if lst.get('for_contaminants') else 'the radionuclide dimension'
            raise EditError(f"'{name}' is {what}, which every model has. Remove its "
                            f"{'materials' if lst.get('for_contaminants') else 'nuclides'} instead.")
        users = self.index_list_users(name)
        if users:
            raise EditError(f"'{name}' is still used by {', '.join(users)}. Remove it from those first.", users)
        self._raw['index_lists'] = [l for l in self._raw['index_lists'] if l is not lst]

    def add_index(self, list_name: str, index: str) -> None:
        """Adds an index to a list. A radionuclide goes into the catalogue too,
        and one ICRP 107 has no half-life for is made stable."""
        lst = self._editable(list_name)
        self._check_index_name(index, list_name)
        if index in [i['name'] for i in lst['indices']]:
            raise EditError(f"'{index}' is already in '{list_name}'")
        as_nuclide = self._is_nuclide_role(lst)
        if as_nuclide:
            root = self._material_list_raw()
            if root is not None and root is not lst:
                root['indices'] = normalise_indices(root.get('indices') or [])
                if index not in [i['name'] for i in root['indices']]:
                    root['indices'].append({'name': index, 'enabled': True})
        lst['indices'].append({'name': index, 'enabled': True})
        if lst.get('for_nuclides') or lst.get('for_contaminants'):
            self._sync_nuclides()
            self._add_element_for(index)
        if as_nuclide and self.half_life(index) is None:
            self.set_half_life(index, _decay.STABLE)

    def _is_nuclide_role(self, lst: Dict[str, Any]) -> bool:
        if lst.get('for_nuclides'):
            return True
        return bool(lst.get('for_contaminants')) and not any(
            l.get('for_nuclides') for l in self._stored_lists())

    def _stored_elements(self) -> Optional[Dict[str, Any]]:
        root = self._material_list_raw()
        if root is None:
            return None
        return next((l for l in self._stored_lists()
                     if not l.get('derived') and isinstance(l.get('mapping'), dict)
                     and l['mapping'].get('to') == root['name']
                     and (l.get('for_elements') or l.get('name') == ELEMENT_LIST)), None)

    def _add_element_for(self, material: str) -> None:
        elements = self._stored_elements()
        if elements is None:
            return
        name = _decay.element_of(material) or material
        if not name:
            return
        if not isinstance(elements.get('indices'), list):
            elements['indices'] = []
        if name not in [index_name(i) for i in elements['indices']]:
            elements['indices'].append({'name': name, 'enabled': True})
        pairs = elements['mapping'].setdefault('pairs', [])
        if not any(p.get('to') == material for p in pairs):
            pairs.append({'from': name, 'to': material})

    def remove_index(self, list_name: str, index: str) -> None:
        """Removes an index, and every per-index value keyed by it. Removing a
        radionuclide removes the material: the two lists hold one material."""
        lst = self._editable(list_name)
        names = [i['name'] for i in lst['indices']]
        if index not in names:
            raise EditError(f"'{index}' is not in '{list_name}'")
        if self._is_nuclide_role(lst):
            root = self._material_list_raw()
            if root is not None and root is not lst and index in [index_name(i) for i in root.get('indices') or []]:
                self.remove_index(root['name'], index)
                return
        del lst['indices'][names.index(index)]
        for b in self._all_raw():
            if b.get('entries'):
                b['entries'] = [e for e in b['entries'] if (e.get('index') or {}).get(list_name) != index]
        for other in self._stored_lists():
            other['indices'] = normalise_indices(other.get('indices') or [])
            if other.get('sub_set_of') == list_name:
                other['indices'] = [i for i in other['indices'] if i['name'] != index]
            m = other.get('mapping')
            if isinstance(m, dict) and m.get('to') == list_name:
                m['pairs'] = [p for p in m.get('pairs') or [] if p.get('to') != index]
        if lst.get('for_contaminants') or lst.get('for_nuclides'):
            self._sync_nuclides()
            if lst.get('for_contaminants') and isinstance(self._raw.get('half_lives'), dict):
                self._raw['half_lives'].pop(index, None)
            if lst.get('for_contaminants'):
                self._drop_empty_element(index)

    def _drop_empty_element(self, material: str) -> None:
        elements = self._stored_elements()
        if elements is None:
            return
        name = _decay.element_of(material) or material
        if name not in [index_name(i) for i in elements.get('indices') or []]:
            return
        if any(p.get('from') == name for p in elements['mapping'].get('pairs') or []):
            return
        self.remove_index(elements['name'], name)

    def rename_index(self, list_name: str, old: str, new: str) -> None:
        """Renames an index everywhere it is written: per-index values, sub-sets,
        mappings, the live scenario, half-lives, decay pairs and ``X[old]`` in
        equations (unless another list has an index of that name)."""
        lst = self._editable(list_name)
        if old not in [i['name'] for i in lst['indices']]:
            raise EditError(f"'{old}' is not in '{list_name}'")
        to = str(new if new is not None else '').strip()
        if not to:
            raise EditError('An index needs a name')
        if to == old:
            return
        self._check_index_name(to, list_name)
        material_roles = bool(lst.get('for_contaminants') or lst.get('for_nuclides'))
        kin = ([l for l in self._stored_lists() if l.get('for_contaminants') or l.get('for_nuclides')]
               if material_roles else [lst])
        kin_names = {l['name'] for l in kin}
        for l in kin:
            if l is not lst and to in [index_name(i) for i in l.get('indices') or []]:
                raise EditError(f"'{l['name']}' already has an index called '{to}'")
        if to in [i['name'] for i in lst['indices']]:
            raise EditError(f"'{list_name}' already has an index called '{to}'")
        for l in kin:
            l['indices'] = [({**i, 'name': to} if i.get('name') == old else i) if isinstance(i, dict)
                            else (to if i == old else i) for i in l.get('indices') or []]
        elsewhere = any(l['name'] not in kin_names and any(index_name(i) in (old, to) for i in l.get('indices') or [])
                        for l in self._lists())
        if not elsewhere:
            self._each_equation(lambda text, system, block, locals_: rewrite_written_indices(
                text, lambda n: to if n == old else None))
        for b in self._all_raw():
            for e in b.get('entries') or []:
                ix = e.get('index')
                if isinstance(ix, dict):
                    for n in kin_names:
                        if ix.get(n) == old:
                            ix[n] = to
        for other in self._stored_lists():
            if other['name'] in kin_names:
                continue
            if other.get('sub_set_of') in kin_names:
                for i in other.get('indices') or []:
                    if isinstance(i, dict) and i.get('name') == old:
                        i['name'] = to
            m = other.get('mapping')
            if isinstance(m, dict) and m.get('to') in kin_names:
                for p in m.get('pairs') or []:
                    if p.get('to') == old:
                        p['to'] = to
        m = lst.get('mapping')
        if isinstance(m, dict):
            for p in m.get('pairs') or []:
                if p.get('from') == old:
                    p['from'] = to
        if lst.get('for_scenarios') and self._raw.get('scenario') == old:
            self._raw['scenario'] = to
        if material_roles:
            self._sync_nuclides()
            hl = self._raw.get('half_lives')
            if isinstance(hl, dict) and old in hl:
                hl[to] = hl.pop(old)
            for pair in self._raw.get('chains') or []:
                if pair[0] == old:
                    pair[0] = to
                if pair[1] == old:
                    pair[1] = to

    def set_index_enabled(self, list_name: str, index: str, on: bool) -> None:
        """Takes an index out of the run or back in. For a material, in both
        material lists: switching is a property of the material."""
        lst = self._editable(list_name)
        idx = next((i for i in lst['indices'] if i['name'] == index), None)
        if idx is None:
            raise EditError(f"'{index}' is not in '{list_name}'")
        idx['enabled'] = bool(on)
        if lst.get('for_contaminants') or lst.get('for_nuclides'):
            for other in self._stored_lists():
                if other is lst or not (other.get('for_contaminants') or other.get('for_nuclides')):
                    continue
                twin = next((i for i in other.get('indices') or []
                             if isinstance(i, dict) and i.get('name') == index), None)
                if twin is not None:
                    twin['enabled'] = bool(on)
            self._sync_nuclides()

    def index_combinations(self, dims: Sequence[str]) -> List[Dict[str, str]]:
        """Every combination of the enabled indices of ``dims``, the last varying
        fastest -- the order the solver lays out a block's values in."""
        if not dims:
            return []
        rows: List[Dict[str, str]] = [{}]
        for d in dims:
            rows = [dict(r, **{d: n}) for r in rows for n in self._enabled_of(d)]
        return rows

    def _enabled_of(self, dim: str) -> List[str]:
        lst = self._list_any(dim)
        if lst is None:
            return list(self._raw.get('nuclides') or []) if dim == NUCLIDE_LIST else []
        return IndexList(self, lst).enabled_indices

    def combination_count(self, dims: Sequence[str]) -> int:
        """How many values a block indexed by ``dims`` holds (1 for none)."""
        n = 1
        for d in dims:
            n *= len(self._enabled_of(d))
        return n

    # --- materials, radionuclides and decay ----------------------------------------------

    @property
    def materials(self) -> List[str]:
        """Every material in the catalogue, radionuclides included."""
        lst = self._material_list_raw()
        return [index_name(i) for i in lst.get('indices') or []] if lst else list(self._raw.get('nuclides') or [])

    @property
    def nuclides(self) -> List[str]:
        """The radionuclides: the materials that have a half-life."""
        lst = next((l for l in self._stored_lists() if l.get('for_nuclides')), None)
        return [index_name(i) for i in lst.get('indices') or []] if lst else []

    def add_nuclides(self, names: Iterable[str], half_lives: Optional[Mapping[str, Any]] = None,
                     pairs: Optional[Iterable[Sequence[Any]]] = None) -> List[str]:
        """Adds radionuclides, to the radionuclide list and the catalogue.

        A name ICRP 107 knows arrives with its half-life; one it does not is
        made stable until told otherwise. ``half_lives`` sets overrides, in
        years (or ``'stable'``), for names in this call. ``pairs`` --
        ``[(parent, daughter, branching), ...]`` -- replaces every decay pair
        out of these nuclides, as the application's nuclide picker does; a pair
        that would close a loop is skipped. Returns the names that were added.
        """
        wanted = list(dict.fromkeys(names))
        lst = next((l for l in self._stored_lists() if l.get('for_nuclides')), None)
        if lst is None:
            self._ensure_material_lists()
            lst = next(l for l in self._stored_lists() if l.get('for_nuclides'))
        have = set(self.nuclides)
        added = []
        for n in wanted:
            if n in have:
                continue
            self.add_index(lst['name'], n)
            added.append(n)
        for n, years in (half_lives or {}).items():
            if n in wanted:
                self.set_half_life(n, years)
        pairs = list(pairs or [])
        if pairs:
            chains = self._own_chains()
            mine = set(wanted)
            chains[:] = [c for c in chains if c[0] not in mine]
            for p in pairs:
                parent, daughter = p[0], p[1]
                ratio = p[2] if len(p) > 2 else 1
                if parent == daughter or self._reaches(chains, daughter, parent):
                    continue
                chains.append([parent, daughter, _js_number(ratio)])
        return added

    def add_material(self, name: str, unit: Optional[str] = None) -> None:
        """Adds a material that does not decay -- stable carbon, water, a
        population -- to the catalogue, with its own unit."""
        root = self._material_list_raw()
        if root is None:
            self._ensure_material_lists()
            root = self._material_list_raw()
        assert root is not None
        self.add_index(root['name'], name)
        if unit:
            self.set_material_unit(name, unit)

    def remove_material(self, name: str) -> None:
        """Removes a material (or a radionuclide) and everything keyed by it."""
        root = self._material_list_raw()
        if root is None or name not in self.materials:
            raise EditError(f"'{name}' is not a material of this model")
        self.remove_index(root['name'], name)

    remove_nuclide = remove_material

    def set_material_unit(self, name: str, unit: Optional[str]) -> None:
        """The unit of a material that does not decay. A radionuclide's is the
        model's :attr:`decay_unit`."""
        root = self._material_list_raw()
        if root is None:
            raise EditError('This model has no materials')
        root['indices'] = normalise_indices(root.get('indices') or [])
        idx = next((i for i in root['indices'] if i['name'] == name), None)
        if idx is None:
            raise EditError(f"'{name}' is not a material of this model")
        nuc = next((l for l in self._stored_lists() if l.get('for_nuclides')), None)
        if nuc is not None and nuc is not root and name in [index_name(i) for i in nuc.get('indices') or []]:
            raise EditError(f"'{name}' is a radionuclide, and an inventory of one is measured in "
                            f"{' or '.join(DECAY_UNITS)} for the whole model -- set decay_unit instead. "
                            'A material with a unit of its own is one that does not decay.')
        u = str(unit or '').strip()
        if u:
            idx['unit'] = u
        else:
            idx.pop('unit', None)
        self._sync_derived_units()

    def material_unit(self, name: str) -> str:
        """The unit one material is measured in: its own, or the decay unit for
        a radionuclide; ``''`` when it has none."""
        return self._material_unit(name)

    @property
    def decay_unit(self) -> str:
        """What a radionuclide inventory is measured in: ``'Bq'`` or ``'mol'``.

        Changing it relabels the compartments that carried the other unit, as
        the application does; no number is converted.
        """
        u = _js_string(self._raw.get('decay_unit')).strip()
        return u if u in DECAY_UNITS else 'Bq'

    @decay_unit.setter
    def decay_unit(self, unit: str) -> None:
        want = _js_string(unit).strip()
        if want not in DECAY_UNITS:
            raise EditError(f"'{unit}' is not a unit an inventory can be held in ({' or '.join(DECAY_UNITS)})")
        was = self.decay_unit
        self._raw['decay_unit'] = want
        if was != want:
            for c in self._raw.get('compartments') or []:
                if _js_string(c.get('unit')).strip() == was:
                    c['unit'] = want
        self._sync_derived_units()

    def half_life(self, nuclide: str) -> Optional[float]:
        """The half-life the model gives a nuclide, in years: its own override
        or ICRP 107's; ``math.inf`` when stable, ``None`` when nothing knows it."""
        own = (self._raw.get('half_lives') or {}).get(nuclide)
        if own is not None:
            return math.inf if _decay.means_stable(own) else _js_number(own)
        return _decay.half_life(nuclide)

    def set_half_life(self, nuclide: str, years: Any) -> None:
        """Overrides a half-life, in years; ``'stable'`` (or ``math.inf``) for a
        nuclide that does not decay; ``None`` drops the override."""
        if years is None:
            if isinstance(self._raw.get('half_lives'), dict):
                self._raw['half_lives'].pop(nuclide, None)
            return
        if not isinstance(self._raw.get('half_lives'), dict):
            self._raw['half_lives'] = {}
        hl = self._raw['half_lives']
        if _decay.means_stable(years):
            hl[nuclide] = _decay.STABLE
            return
        v = _js_number(years)
        if not v > 0:
            raise EditError('A half-life must be greater than zero')
        hl[nuclide] = v

    @property
    def decay_chains(self) -> List[Tuple[str, str, float]]:
        """The decay pairs in force, ``(parent, daughter, branching)``: the
        model's own when it states them, otherwise the ones ICRP 107 gives the
        materials it carries (:func:`kompartment.decay.default_chains`)."""
        own = self._raw.get('chains')
        if own:
            return [(p[0], p[1], p[2] if len(p) > 2 else 1) for p in own]
        return _decay.default_chains(self.materials)

    @property
    def has_own_chains(self) -> bool:
        """Whether the model states its decay pairs rather than following its nuclides."""
        return bool(self._raw.get('chains'))

    def _own_chains(self) -> List[List[Any]]:
        if not self._raw.get('chains'):
            self._raw['chains'] = [list(p) for p in self.decay_chains]
        return self._raw['chains']

    def set_decay_chains(self, pairs: Iterable[Sequence[Any]]) -> None:
        """States the decay pairs outright, ``[(parent, daughter, branching), ...]``.
        From then on the chains no longer follow the nuclides."""
        chains: List[List[Any]] = []
        for p in pairs:
            parent, daughter = p[0], p[1]
            ratio = p[2] if len(p) > 2 else 1
            self._check_pair(parent, daughter, ratio)
            if self._reaches(chains, daughter, parent):
                raise EditError(f'That would make a loop: {parent} is already reachable from {daughter}.')
            chains.append([parent, daughter, _js_number(ratio)])
        self._raw['chains'] = chains

    def reset_decay_chains(self) -> None:
        """Forgets the model's own pairs: the chains follow the nuclides again."""
        self._raw.pop('chains', None)

    @staticmethod
    def _check_pair(parent: str, daughter: str, ratio: Any) -> None:
        if not parent or not daughter:
            raise EditError('A decay pair needs both nuclides')
        if parent == daughter:
            raise EditError('A nuclide cannot decay into itself')
        r = _js_number(ratio)
        if not (r > 0) or r > 1:
            raise EditError('A branching ratio must be greater than 0 and at most 1')

    def add_decay_pair(self, parent: str, daughter: str, ratio: float = 1) -> None:
        """Adds a decay pair. The first edit writes the chains in force into the model."""
        self._check_pair(parent, daughter, ratio)
        chains = self._own_chains()
        if any(c[0] == parent and c[1] == daughter for c in chains):
            raise EditError(f'{parent} to {daughter} is already in the chain list')
        if self._reaches(chains, daughter, parent):
            raise EditError(f'That would make a loop: {parent} is already reachable from {daughter}.')
        chains.append([parent, daughter, _js_number(ratio)])

    def remove_decay_pair(self, parent: str, daughter: str) -> None:
        chains = self._own_chains()
        for k, c in enumerate(chains):
            if c[0] == parent and c[1] == daughter:
                del chains[k]
                return
        raise EditError(f'{parent} to {daughter} is not in the chain list')

    def set_decay_ratio(self, parent: str, daughter: str, ratio: float) -> None:
        r = _js_number(ratio)
        if not (r > 0) or r > 1:
            raise EditError('A branching ratio must be greater than 0 and at most 1')
        for c in self._own_chains():
            if c[0] == parent and c[1] == daughter:
                c[2] = r
                return
        raise EditError(f'{parent} to {daughter} is not in the chain list')

    @staticmethod
    def _reaches(chains: Sequence[Sequence[Any]], start: str, goal: str) -> bool:
        seen: Set[str] = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n == goal:
                return True
            if n in seen:
                continue
            seen.add(n)
            stack.extend(c[1] for c in chains if c[0] == n)
        return False

    # --- dimensions and entries --------------------------------------------------------------

    def _effective_dims(self, b: Dict[str, Any]) -> List[str]:
        if isinstance(b.get('index_lists'), list):
            return list(b['index_lists'])
        if 'actions' in b or 'timing' in b:
            return []
        if 'from' in b or 'to' in b:
            shared = self._transfer_dims(b)
            if shared is not None:
                return list(shared['dims'])
        name = self.material_dimension()
        if name and b.get('per_nuclide') is not False:
            return [name]
        return []

    def _end_dims(self, name: Optional[str]) -> Optional[List[str]]:
        if name is None:
            return None
        hit = self._find(name)
        if hit is None or SINGULAR[hit[0]] not in HOLDS_INVENTORY:
            return None
        b = hit[1]
        if isinstance(b.get('index_lists'), list):
            return list(b['index_lists'])
        material = self.material_dimension()
        return [material] if material and b.get('per_nuclide') is not False else []

    def _transfer_dims(self, b: Dict[str, Any], lists: Optional[List[Dict[str, Any]]] = None
                       ) -> Optional[Dict[str, Any]]:
        return shared_dims(lists if lists is not None else self._lists(),
                           self._end_dims(b.get('from')), self._end_dims(b.get('to')))

    def default_dimensions(self, kind: str) -> List[str]:
        """What a new block of ``kind`` is indexed by: the radionuclides (or the
        catalogue) for most kinds, nothing for a parameter or a lookup table."""
        if kind in ('parameter', 'lookup'):
            return []
        name = self.material_dimension()
        return [name] if name else []

    def _check_dims(self, kind: str, dims: Sequence[str]) -> List[str]:
        lists = self._lists()
        out: List[str] = []
        for d in dims:
            lst = find_list(lists, d)
            if lst is None:
                raise EditError(f"No index list named '{d}'")
            if not list_applies(lst, kind):
                raise EditError(list_applies_why(lst, kind))
            out.append(d)
        clash = clashing_dimensions(lists, out)
        if clash:
            raise EditError(clashing_dimensions_why(clash))
        if kind in ('farfield', 'waste_package'):
            root = next((l['name'] for l in lists if l.get('for_contaminants')), None) or self.material_dimension()
            decaying = [d for d in out if root and is_decay_dim(lists, d, root)]
            if len(decaying) > 1:
                raise EditError(f"{'A far-field path runs' if kind == 'farfield' else 'Waste packages run'} one "
                                f"decay chain, and '{decaying[0]}' and '{decaying[1]}' are two radionuclide "
                                'dimensions. Index it by one of them.')
        return out

    def set_dimensions(self, block: Union[str, Block], dims: Sequence[str]) -> List[str]:
        """Sets which index lists a block is indexed by, dropping the per-index
        values keyed by a list it no longer has. Returns the names of the
        connections, transport parts and reductions whose dimensions followed."""
        b = self.block(block) if isinstance(block, str) else block
        if b.kind in ('function', 'event'):
            if dims:
                raise EditError(f"A {b.kind} is not indexed")
            return []
        dims = self._check_dims(b.kind, list(dims))
        raw = b.raw
        raw['index_lists'] = list(dims)
        _prune_entries(raw, dims)
        followed: List[str] = []
        if b.kind == 'compartment':
            followed += self._sync_connection_dims(b.qualified_name)
        followed += self._sync_transport_dims(raw, dims)
        followed += self._sync_reduction_dims(b.qualified_name)
        return followed

    def _narrows(self, dims: Sequence[str], derived: Sequence[str],
                 lists: Optional[List[Dict[str, Any]]] = None) -> bool:
        if len(dims) != len(derived):
            return False
        lists = lists if lists is not None else self._lists()
        return all(any(d == w or (find_list(lists, d) or {}).get('sub_set_of') == w for w in derived)
                   for d in dims)

    def _sync_connection_dims(self, name: Optional[str] = None) -> List[str]:
        lists = self._lists()

        def dims_of(n: Optional[str]) -> List[str]:
            hit = self._find(n)
            return self._effective_dims(hit[1]) if hit else []

        def wanted(t: Dict[str, Any]) -> List[str]:
            shared = self._transfer_dims(t, lists)
            if shared is not None:
                return list(shared['dims'])
            union: List[str] = []
            for d in dims_of(t.get('from')) + dims_of(t.get('to')):
                if d not in union:
                    union.append(d)
            return union

        touched = []
        for collection in ('transfers', 'inflows'):
            for t in self._raw.get(collection) or []:
                if name is not None and t.get('to') != name and (collection == 'inflows' or t.get('from') != name):
                    continue
                want = wanted(t)
                if self._narrows(t.get('index_lists') or [], want, lists):
                    continue
                if (t.get('index_lists') or []) != want:
                    t['index_lists'] = want
                    _prune_entries(t, want)
                    touched.append(t.get('name'))
        return touched

    def _transport_parts(self, path: str) -> Dict[str, Any]:
        found: Dict[str, Any] = {'begin': None, 'end': None, 'number': None, 'counter': None, 'operations': []}
        for collection, roles in (('compartments', ('begin', 'end')),
                                  ('expressions', ('number', 'counter', 'operation'))):
            for b in self._raw.get(collection) or []:
                if system_of(b) != path:
                    continue
                role = b.get('transport')
                if role not in roles:
                    continue
                if role == 'operation':
                    found['operations'].append(b)
                elif found[role] is None:
                    found[role] = b
        return found

    def _transport_of(self, raw: Dict[str, Any]) -> Optional[str]:
        if not raw.get('transport'):
            return None
        path = system_of(raw)
        return path if path and path in self.transports else None

    def _sync_transport_dims(self, raw: Dict[str, Any], dims: Sequence[str]) -> List[str]:
        if raw.get('transport') not in ('begin', 'end'):
            return []
        path = self._transport_of(raw)
        if not path:
            return []
        p = self._transport_parts(path)
        followed = []
        for other in [p['begin'], p['end'], *p['operations']]:
            if other is None or other is raw:
                continue
            if sorted(other.get('index_lists') or []) == sorted(dims):
                continue
            other['index_lists'] = list(dims)
            _prune_entries(other, dims)
            q = qualified_name(other)
            followed.append(q)
            if other.get('transport') != 'operation':
                followed += self._sync_connection_dims(q)
        return followed

    def _transport_ends(self, path: str) -> Tuple[List[str], List[str]]:
        p = self._transport_parts(path)

        def inside(n: Optional[str]) -> bool:
            hit = self._find(n)
            return hit is not None and system_of(hit[1]) == path

        heads = {qualified_name(b) for b in (p['begin'], p['end']) if b is not None}
        frm: List[str] = []
        to: List[str] = []
        for t in self._raw.get('transfers') or []:
            if t.get('to') is not None and t['to'] in heads and t.get('from') is not None and not inside(t['from']):
                frm.append(t['from'])
            if t.get('from') is not None and t['from'] in heads and t.get('to') is not None and not inside(t['to']):
                to.append(t['to'])
        return list(dict.fromkeys(frm)), list(dict.fromkeys(to))

    def _transport_dims(self, path: str, lists: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        frm, to = self._transport_ends(path)
        names = frm + to
        if not names:
            return None

        def plain(dims: Sequence[str]) -> List[str]:
            return [d for d in dims or [] if not (find_list(lists, d) or {}).get('for_scenarios')]

        def root(n: str) -> str:
            return lineage(lists, n)['root']

        acc: Optional[List[str]] = None
        for n in names:
            hit = self._find(n)
            if hit is None or SINGULAR[hit[0]] not in HOLDS_INVENTORY:
                return None
            d = self._effective_dims(hit[1])
            if acc is None:
                acc = d
                continue
            dims: List[str] = []
            rest = plain(d)
            for s in plain(acc):
                at = next((k for k, t in enumerate(rest) if root(t) == root(s)), -1)
                if at < 0:
                    continue
                t = rest.pop(at)
                if s == t:
                    dims.append(s)
                    continue
                ls, lt = find_list(lists, s) or {}, find_list(lists, t) or {}
                narrower = s if ls.get('sub_set_of') == t else (t if lt.get('sub_set_of') == s else None)
                if narrower is None:
                    return None
                dims.append(narrower)
            acc = dims
        return {'dims': acc or []}

    def _sync_transport_inheritance(self, lists: List[Dict[str, Any]]) -> List[str]:
        changed: List[str] = []
        for path in self.transports:
            p = self._transport_parts(path)
            if p['begin'] is None:
                continue
            inherited = self._transport_dims(path, lists)
            if inherited is None:
                continue
            have = self._effective_dims(p['begin'])
            if have == inherited['dims'] or self._narrows(have, inherited['dims'], lists):
                continue
            p['begin']['index_lists'] = list(inherited['dims'])
            _prune_entries(p['begin'], inherited['dims'])
            changed.append(qualified_name(p['begin']))
            changed += self._sync_transport_dims(p['begin'], inherited['dims'])
        return changed

    @staticmethod
    def _reduced_of(own: Sequence[str], dims: Sequence[str]) -> Optional[str]:
        have = set(own)
        missing = [d for d in dims if d not in have]
        return missing[0] if len(missing) == 1 else None

    def _reduced_list(self, block: Block) -> Optional[str]:
        target = block.raw.get('target')
        if not target:
            return None
        q = resolve_reference(str(target), block.system, self._known())
        hit = self._find(q)
        if hit is None:
            return None
        return self._reduced_of(block.raw.get('index_lists') or [], self._effective_dims(hit[1]))

    def _sync_reduction_dims(self, name: Optional[str] = None) -> List[str]:
        known = self._known()
        touched = []
        for o in self._raw.get('index_reductions') or []:
            if not o.get('target'):
                continue
            q = resolve_reference(_js_string(o['target']), system_of(o), known)
            if q is None or (name is not None and q != name):
                continue
            hit = self._find(q)
            if hit is None:
                continue
            dims = self._effective_dims(hit[1])
            keep = self._reduced_of(o.get('index_lists') or [], dims)
            reduced = keep if keep in dims else (dims[0] if dims else None)
            nxt = [d for d in dims if d != reduced]
            if (o.get('index_lists') or []) == nxt:
                continue
            o['index_lists'] = nxt
            _prune_entries(o, nxt)
            touched.append(o.get('name'))
        for g in self._raw.get('block_reductions') or []:
            reads = name is None
            union: List[str] = []
            for ref in g.get('targets') or []:
                q = resolve_reference(_js_string(ref), system_of(g), known)
                if q is None:
                    continue
                if q == name:
                    reads = True
                hit = self._find(q)
                for d in (self._effective_dims(hit[1]) if hit else []):
                    if d not in union:
                        union.append(d)
            if not reads or (g.get('index_lists') or []) == union:
                continue
            g['index_lists'] = union
            _prune_entries(g, union)
            touched.append(g.get('name'))
        return touched

    def _index_of(self, block: Block, at: Index) -> Dict[str, str]:
        dims = block.index_lists
        if at is None:
            return {}
        if isinstance(at, str):
            if len(dims) == 1:
                index = {dims[0]: at}
            else:
                matches = [d for d in dims if at in self.index_list(d).indices]
                if len(matches) != 1:
                    raise EditError(f"'{at}' is ambiguous for {block.name}, which is indexed by "
                                    f"{', '.join(dims) or 'nothing'}: give the index as {{list: index}}")
                index = {matches[0]: at}
        elif isinstance(at, Mapping):
            index = {str(k): str(v) for k, v in at.items()}
        else:
            seq = list(at)
            if len(seq) != len(dims):
                raise EditError(f'{block.name} has {len(dims)} dimension(s) and the index gives {len(seq)}')
            index = {d: str(i) for d, i in zip(dims, seq) if i is not None}
        for lst_name, idx in index.items():
            if lst_name not in dims:
                raise EditError(f"'{block.qualified_name}' is not indexed by '{lst_name}'")
            lst = self._list_any(lst_name)
            if lst is None or idx not in [index_name(i) for i in lst.get('indices') or []]:
                raise EditError(f"'{idx}' is not an index of '{lst_name}'")
        return index

    def _set_entry(self, block: Block, index: Dict[str, str], values: Dict[str, Any]) -> Dict[str, Any]:
        raw = block.raw
        if block.kind in ('farfield', 'waste_package'):
            nuclide_keys = FARF_NUCLIDE_KEYS if block.kind == 'farfield' else WASTE_NUCLIDE_KEYS
            material = self.material_dimension()
            if material in index:
                wrong = [k for k in values if k not in nuclide_keys]
                if wrong:
                    raise EditError(f"{block.name}: {', '.join(wrong)} hold one value whatever the nuclide; "
                                    f"only {', '.join(nuclide_keys)} are per nuclide")
        if not isinstance(raw.get('entries'), list):
            raw['entries'] = []
        entry = next((e for e in raw['entries'] if (e.get('index') or {}) == index), None)
        if entry is None:
            entry = {'index': dict(index)}
            raw['entries'].append(entry)
        entry.update(values)
        return entry

    # --- adding blocks ------------------------------------------------------------------------

    def _check_new_name(self, name: str, system: str, allow: Optional[str] = None) -> None:
        problem = name_problem(name)
        if problem:
            raise EditError(problem)
        target = qualify(system, name)
        if target != allow and self._find(target) is not None:
            raise EditError(f"'{name}' is already used by another block"
                            + (f" in '{system}'." if system else '.'))
        if target != allow and target in self._system_set():
            raise EditError(f"'{name}' is already used by a sub-system.")

    def _id_taken(self, qname: str) -> bool:
        return self._find(qname) is not None or qname in self._system_set()

    def unique_name(self, base: str, system: str = '') -> str:
        """``base``, or ``base1``, ``base2``, ... -- the first name free in
        ``system`` (among its blocks and sub-systems)."""
        if not self._id_taken(qualify(system, base)):
            return base
        for i in range(1, 100000):
            if not self._id_taken(qualify(system, f'{base}{i}')):
                return f'{base}{i}'
        raise EditError(f"Could not find a free name based on '{base}'")

    def _name_for(self, kind: str, name: Optional[str], system: str) -> str:
        return name if name is not None else self.unique_name(DEFAULT_NAME[kind], system)

    def _check_system(self, system: str) -> None:
        if system and system not in self._system_set():
            raise EditError(f"No sub-system named '{system}'")

    def _append(self, collection: str, raw: Dict[str, Any], system: str,
                position: Optional[Any] = None, system_first: bool = False) -> Block:
        """Checks a new block's name and puts it in the model, its sub-system
        written where the application writes it."""
        self._check_system(system)
        self._check_new_name(raw['name'], system)
        if system:
            raw = {'system': system, **raw} if system_first else {**raw, 'system': system}
        if not isinstance(self._raw.get(collection), list):
            self._raw[collection] = []
        self._raw[collection].append(raw)
        self._register(collection, raw)
        b = _view_of(self, collection, raw)
        if position is not None:
            self._set_position(b.qualified_name, _position_of(position))
        return b

    @staticmethod
    def _extras(raw: Dict[str, Any], comment: Optional[str], symbol: Optional[str]) -> None:
        if comment:
            raw['comment'] = comment
        if symbol:
            raw['symbol'] = symbol

    def _dims_for(self, kind: str, index_lists: Optional[Sequence[str]]) -> List[str]:
        return self._check_dims(kind, list(index_lists)) if index_lists is not None \
            else self.default_dimensions(kind)

    def add_compartment(self, name: Optional[str] = None, initial: Any = '0', *,
                        unit: Optional[str] = None, index_lists: Optional[Sequence[str]] = None,
                        system: str = '', dydt: Any = None, non_negative: bool = True,
                        handle_decay: bool = True, abstol: Optional[float] = None,
                        comment: Optional[str] = None, symbol: Optional[str] = None,
                        position: Optional[XY] = None) -> Compartment:
        """Adds a compartment: a state variable holding an inventory.

        ``initial`` is the initial inventory (a number or a constant equation);
        set it per index with :meth:`Block.set_value`. ``index_lists`` defaults
        to the radionuclides when the model has any, and ``unit`` to the
        model's decay unit. ``dydt`` is an optional extra term in the rate of
        change; ``non_negative`` keeps the inventory from going below zero;
        ``handle_decay`` applies decay and ingrowth along its radionuclides;
        ``abstol`` is its own absolute tolerance. ``position`` is where it is
        drawn, ``(x, y)``; the application places what has none.
        """
        n = self._name_for('compartment', name, system)
        raw: Dict[str, Any] = {'name': n, 'initial': equation_text(initial),
                               'unit': unit if unit is not None else self.decay_unit,
                               'handle_decay': bool(handle_decay),
                               'index_lists': self._dims_for('compartment', index_lists)}
        if dydt is not None:
            raw['dydt'] = equation_text(dydt)
        if not non_negative:
            raw['non_negative'] = False
        if abstol is not None:
            v = Compartment.abstol.coerce(abstol)
            if not v > 0:
                raise EditError(f'{n}: an absolute tolerance has to be greater than zero')
            raw['abstol'] = v
        self._extras(raw, comment, symbol)
        return self._append('compartments', raw, system, position)  # type: ignore[return-value]

    def add_parameter(self, name: Optional[str] = None, value: Any = 0, *, unit: str = '',
                      index_lists: Optional[Sequence[str]] = None, system: str = '',
                      distribution: Optional[Dict[str, Any]] = None, comment: Optional[str] = None,
                      symbol: Optional[str] = None, position: Optional[XY] = None) -> Parameter:
        """Adds a parameter: a constant, one per index when indexed.

        ``distribution`` is what a probabilistic run draws it from (a dict from
        :mod:`kompartment.distributions`). Not indexed unless ``index_lists`` says so.
        """
        n = self._name_for('parameter', name, system)
        raw: Dict[str, Any] = {'name': n, 'value': 0, 'unit': unit,
                               'index_lists': self._dims_for('parameter', index_lists)}
        self._extras(raw, comment, symbol)
        draft = Parameter(self, raw)
        draft.value = value
        if distribution is not None:
            draft.distribution = distribution
        return self._append('parameters', raw, system, position)  # type: ignore[return-value]

    def add_expression(self, name: Optional[str] = None, equation: Any = '0', *, unit: str = '',
                       index_lists: Optional[Sequence[str]] = None, system: str = '',
                       comment: Optional[str] = None, symbol: Optional[str] = None,
                       position: Optional[XY] = None) -> Expression:
        """Adds an expression: an algebraic quantity worked out from the state.

        Indexed by the radionuclides by default when the model has any; pass
        ``index_lists=[]`` for a single value.
        """
        n = self._name_for('expression', name, system)
        raw: Dict[str, Any] = {'name': n, 'equation': equation_text(equation), 'unit': unit,
                               'index_lists': self._dims_for('expression', index_lists)}
        self._extras(raw, comment, symbol)
        return self._append('expressions', raw, system, position)  # type: ignore[return-value]

    def _endpoint(self, name: Optional[str], end: str) -> Optional[str]:
        """A connection end as the application stores it: qualified, a
        transport meaning its End as a donor and its Begin as a receiver."""
        if name is None:
            return None
        q = name
        if q in self.transports:
            p = self._transport_parts(q)
            part = p['end'] if end == 'from' else p['begin']
            if part is None:
                raise EditError(f"'{name}' has no {'End' if end == 'from' else 'Begin'} compartment, so there "
                                f"is nothing in it to connect {'from' if end == 'from' else 'to'}.")
            q = qualified_name(part)
        kind = self._kind_of(q)
        if kind is None:
            raise EditError(f"'{name}' is not a block in this model")
        if kind in ('compartment', 'farfield'):
            return q
        if kind == 'waste_package':
            if end == 'from':
                return q
            raise EditError(f"'{name}' is a set of waste packages: nothing flows into them, "
                            'their release comes out')
        raise EditError(f"'{name}' is not a compartment")

    def _release_taken(self, path: str, allow: Optional[str] = None) -> str:
        held = [t for t in self._raw.get('transfers') or [] if t.get('from') == path and qualified_name(t) != allow]
        if not held:
            return ''
        to = held[0].get('to') or 'outside the model'
        return (f"{path} already delivers its release to {to}, as '{held[0].get('name')}'. A block has "
                'one release, and a second line carrying it would deliver the whole of it again.')

    def add_transfer(self, source: Optional[str], target: Optional[str], rate: Any = '0', *,
                     name: Optional[str] = None, multiply_by_donor: Optional[bool] = None,
                     index_lists: Optional[Sequence[str]] = None, system: Optional[str] = None,
                     sum_extra_indices: bool = False, comment: Optional[str] = None,
                     symbol: Optional[str] = None) -> Transfer:
        """Adds a transfer from ``source`` to ``target`` -- either may be
        ``None``, for outside the model -- by qualified names.

        ``rate`` is a rate coefficient, multiplied by the donor's inventory,
        unless ``multiply_by_donor`` is off (an absolute flux); it is on by
        default when there is a donor. The name defaults to ``Source_Target``.
        The transfer lives in its donor's sub-system (its receiver's when there
        is no donor), and is indexed by what its two ends share. Its unit
        follows from the donor and the time unit. A transfer out of a far-field
        path or waste packages carries their release: its rate is their name,
        and a block has one release.
        """
        src = self._endpoint(source, 'from')
        tgt = self._endpoint(target, 'to')
        if src is None and tgt is None:
            raise EditError('A transfer needs a source, a target, or both')
        if src is not None and src == tgt:
            raise EditError('A transfer cannot start and end at the same compartment')
        release = src is not None and self._kind_of(src) in RELEASING
        if release:
            taken = self._release_taken(src)  # type: ignore[arg-type]
            if taken:
                raise EditError(taken)
        home = system if system is not None else parent_of(src if src is not None else tgt)
        base = f'{base_name(src)}_{base_name(tgt)}' if src and tgt else 'T'
        n = name if name is not None else self.unique_name(base, home)
        if index_lists is not None:
            dims = self._check_dims('transfer', list(index_lists))
        else:
            shared = self._transfer_dims({'from': src, 'to': tgt})
            dims = list(shared['dims']) if shared is not None else []
            if shared is None:
                for end in (src, tgt):
                    if end is None:
                        continue
                    hit = self._find(end)
                    for d in self._effective_dims(hit[1]) if hit else []:
                        if d not in dims:
                            dims.append(d)
        raw: Dict[str, Any] = {
            'name': n, 'from': src, 'to': tgt,
            'rate': src if release else equation_text(rate),
            'multiply_by_donor': False if release else (
                bool(multiply_by_donor) if multiply_by_donor is not None else src is not None),
            'index_lists': dims,
        }
        unit = self._transfer_unit(raw)
        if unit:
            raw['unit'] = unit
        if sum_extra_indices:
            raw['sum_extra_indices'] = True
        self._extras(raw, comment, symbol)
        return self._append('transfers', raw, home, system_first=True)  # type: ignore[return-value]

    def add_inflow(self, target: str, rate: Any = '0', *, name: Optional[str] = None,
                   index_lists: Optional[Sequence[str]] = None, system: Optional[str] = None,
                   sum_extra_indices: bool = False, comment: Optional[str] = None,
                   symbol: Optional[str] = None) -> Inflow:
        """Adds an inflow (source term): an absolute flux into ``target`` -- a
        compartment or a far-field path -- from outside the model. It lives in
        its target's sub-system and is indexed as its target is."""
        if not target:
            raise EditError('A source needs a target compartment')
        tgt = self._endpoint(target, 'to')
        assert tgt is not None
        home = system if system is not None else parent_of(tgt)
        n = self._name_for('inflow', name, home)
        if index_lists is not None:
            dims = self._check_dims('inflow', list(index_lists))
        else:
            shared = self._transfer_dims({'from': None, 'to': tgt})
            dims = list(shared['dims']) if shared is not None else self.default_dimensions('inflow')
        raw: Dict[str, Any] = {'name': n, 'to': tgt, 'rate': equation_text(rate)}
        unit = self._inflow_unit(raw)
        if unit:
            raw['unit'] = unit
        raw['index_lists'] = dims
        if sum_extra_indices:
            raw['sum_extra_indices'] = True
        self._extras(raw, comment, symbol)
        return self._append('inflows', raw, home)  # type: ignore[return-value]

    add_source = add_inflow

    def add_lookup(self, name: Optional[str] = None, points: Optional[Sequence[Sequence[Any]]] = None, *,
                   interpolation: str = 'linear', cyclic: bool = False, argument: Optional[str] = None,
                   unit: str = '', index_lists: Optional[Sequence[str]] = None, system: str = '',
                   comment: Optional[str] = None, symbol: Optional[str] = None,
                   position: Optional[XY] = None) -> Lookup:
        """Adds a lookup table: a value following ``points`` ``[(x, y), ...]``.

        Read at the simulation clock, or -- with an ``argument`` -- called from
        equations as ``Name(x)``. ``interpolation`` is one of ``linear`` (end
        values held beyond the points), ``extrapolate``, ``below``, ``above``,
        ``nearest``. Without points it is a flat line at zero over the run.
        """
        if interpolation not in INTERPOLATIONS:
            raise EditError(f"'{interpolation}' is not an interpolation rule ({', '.join(INTERPOLATIONS)})")
        n = self._name_for('lookup', name, system)
        if points is None:
            sim = self._raw.get('simulation') or {}
            start = _js_number(sim.get('start_time') if sim.get('start_time') is not None else 0)
            end = _js_number(sim.get('end_time') if sim.get('end_time') is not None else 1)
            start = start if math.isfinite(start) else 0
            points = [[start, 0], [end if math.isfinite(end) and end > start else start + 1, 0]]
        raw: Dict[str, Any] = {'name': n, 'unit': unit, 'interpolation': interpolation,
                               'cyclic': bool(cyclic), 'points': [],
                               'index_lists': self._dims_for('lookup', index_lists)}
        self._extras(raw, comment, symbol)
        draft = Lookup(self, raw)
        draft.points = points  # type: ignore[assignment]
        if argument:
            draft.argument = argument
        return self._append('lookups', raw, system, position)  # type: ignore[return-value]

    def add_index_reduction(self, name: Optional[str] = None, target: Optional[str] = None, *,
                            over: Optional[str] = None, operation: str = 'sum',
                            percentile: Optional[float] = None, unit: str = '', system: str = '',
                            comment: Optional[str] = None, symbol: Optional[str] = None,
                            position: Optional[XY] = None) -> IndexReduction:
        """Adds an index reduction: ``target`` reduced along one of its index
        lists (``over``; its first by default) -- ``sum``, ``product``, ``min``,
        ``max``, ``mean`` or ``percentile`` (with ``percentile``, 0 to 100).
        ``target`` is written as an equation would write it from ``system``."""
        if operation not in OPERATIONS:
            raise EditError(f"'{operation}' is not a reduction ({', '.join(OPERATIONS)})")
        if operation == 'percentile' and not (percentile is not None and 0 <= float(percentile) <= 100):
            raise EditError('A percentile reduction needs a percentile between 0 and 100')
        n = self._name_for('index_reduction', name, system)
        raw: Dict[str, Any] = {'name': n, 'target': None, 'operation': operation, 'unit': unit,
                               'index_lists': []}
        if percentile is not None:
            raw['percentile'] = percentile
        self._extras(raw, comment, symbol)
        if target:
            raw['target'], raw['index_lists'] = target, self._reduction_dims(system, target, over, [])
        return self._append('index_reductions', raw, system, position)  # type: ignore[return-value]

    def set_reduction_target(self, name: str, target: Optional[str], *, over: Optional[str] = None) -> None:
        """Points an index reduction at a block and re-derives its dimensions:
        the target's, less the one it reduces over (``over``; else the one it
        reduced before, when the new target has it; else the first)."""
        b = self.block(name)
        if b.kind != 'index_reduction':
            raise EditError(f"'{name}' is not an index operation")
        if not target:
            b.raw['target'] = None
            return
        b.raw['index_lists'] = self._reduction_dims(b.system, target, over, b.raw.get('index_lists') or [])
        b.raw['target'] = target
        b.raw.pop('per_nuclide', None)

    def _reduction_dims(self, system: str, target: str, over: Optional[str], own: Sequence[str]) -> List[str]:
        q = resolve_reference(target, system, self._known())
        hit = self._find(q)
        if hit is None:
            raise EditError(f"No block named '{target}'")
        dims = self._effective_dims(hit[1])
        if over is not None and over not in dims:
            raise EditError(f"'{qualified_name(hit[1])}' is not indexed by '{over}'")
        keep = over if over is not None else self._reduced_of(own, dims)
        reduced = keep if keep in dims else (dims[0] if dims else None)
        return [d for d in dims if d != reduced]

    def add_block_reduction(self, name: Optional[str] = None, targets: Sequence[str] = (), *,
                            operation: str = 'sum', unit: str = '', system: str = '',
                            comment: Optional[str] = None, symbol: Optional[str] = None,
                            position: Optional[XY] = None) -> BlockReduction:
        """Adds a block reduction (aggregate): several blocks combined
        element-wise -- ``sum``, ``product``, ``min``, ``max`` or ``mean`` --
        indexed by the union of their dimensions."""
        if operation not in AGGREGATE_OPERATIONS:
            raise EditError(f"'{operation}' is not a reduction an aggregate can do "
                            f"({', '.join(AGGREGATE_OPERATIONS)})")
        n = self._name_for('block_reduction', name, system)
        raw: Dict[str, Any] = {'name': n, 'targets': [], 'operation': operation, 'unit': unit,
                               'index_lists': []}
        self._extras(raw, comment, symbol)
        raw['targets'], raw['index_lists'] = list(targets), self._aggregate_dims(system, targets)
        return self._append('block_reductions', raw, system, position)  # type: ignore[return-value]

    def set_aggregate_targets(self, name: str, targets: Sequence[str]) -> None:
        """Sets what a block reduction combines, and re-derives its dimensions."""
        b = self.block(name)
        if b.kind != 'block_reduction':
            raise EditError(f"'{name}' is not an aggregate")
        b.raw['index_lists'] = self._aggregate_dims(b.system, targets)
        b.raw['targets'] = list(targets)

    def _aggregate_dims(self, system: str, targets: Sequence[str]) -> List[str]:
        known = self._known()
        union: List[str] = []
        for ref in targets:
            q = resolve_reference(ref, system, known)
            hit = self._find(q)
            if hit is None:
                raise EditError(f"No block named '{ref}'")
            for d in self._effective_dims(hit[1]):
                if d not in union:
                    union.append(d)
        return union

    def add_function(self, name: Optional[str] = None, parameters: Sequence[str] = ('x',),
                     equation: Any = '', *, unit: str = '', system: str = '',
                     comment: Optional[str] = None) -> Function:
        """Adds a function: a body (``equation``) in terms of its ``parameters``,
        callable from any equation as ``name(a, b)``."""
        n = self._name_for('function', name, system)
        raw: Dict[str, Any] = {'name': n, 'parameters': [], 'equation': equation_text(equation), 'unit': unit}
        if comment:
            raw['comment'] = comment
        raw['parameters'] = self._function_parameters(parameters)
        return self._append('functions', raw, system, system_first=True)  # type: ignore[return-value]

    def set_function_parameters(self, name: str, parameters: Sequence[str]) -> None:
        """Sets a function's parameters: names, not repeated, not reserved, not a block's."""
        b = self.block(name)
        if b.kind != 'function':
            raise EditError(f"No function named '{name}'")
        b.raw['parameters'] = self._function_parameters(parameters)

    def _function_parameters(self, parameters: Sequence[str]) -> List[str]:
        taken = self._idx()
        out: List[str] = []
        for p in parameters:
            p = str(p if p is not None else '').strip()
            if not p:
                continue
            if not NAME_RE.fullmatch(p):
                raise EditError(f"'{p}' is not a valid parameter name: letters, digits and underscore, "
                                'not starting with a digit.')
            if p in RESERVED:
                raise EditError(f"'{p}' is the name of a built-in function.")
            if p in out:
                raise EditError(f"'{p}' is named twice.")
            if p in taken:
                raise EditError(f"'{p}' is already a block in this model, so the body would have no way to "
                                'mean the block. Choose another name for the parameter.')
            out.append(p)
        return out

    def _recorder(self, kind: str, name: Optional[str], watched: Any, fields: Dict[str, Any], unit: str,
                  system: str, comment: Optional[str], index_lists: Optional[Sequence[str]],
                  position: Optional[XY]) -> Block:
        n = self._name_for(kind, name, system)
        if index_lists is not None:
            dims = self._check_dims(kind, list(index_lists))
        else:
            dims = []
            if watched is not None and str(watched).strip():
                q = resolve_reference(str(watched).strip(), system, self._known()) or str(watched)
                hit = self._find(q)
                dims = self._effective_dims(hit[1]) if hit else []
        raw: Dict[str, Any] = {'name': n, 'index_lists': dims, 'unit': unit, **fields}
        if comment:
            raw['comment'] = comment
        return self._append(RECORDER_COLLECTION[kind], raw, system, position)

    def add_min_max(self, name: Optional[str] = None, target: Any = '0', *, operation: str = 'max',
                    reset_trigger: Optional[str] = None, start_trigger: Optional[str] = None,
                    stop_trigger: Optional[str] = None, unit: str = '', system: str = '',
                    index_lists: Optional[Sequence[str]] = None, comment: Optional[str] = None,
                    position: Optional[XY] = None) -> MinMax:
        """Adds a min/max: the largest (or smallest) value ``target`` has taken,
        indexed as the block it watches. The triggers name trigger blocks that
        restart, start or stop it."""
        if operation not in EXTREMES:
            raise EditError(f"'{operation}' is not a min/max operation ({', '.join(EXTREMES)})")
        return self._recorder('min_max', name, target, {
            'target': equation_text(target), 'operation': operation, 'reset_trigger': reset_trigger,
            'start_trigger': start_trigger, 'stop_trigger': stop_trigger,
        }, unit, system, comment, index_lists, position)  # type: ignore[return-value]

    def add_running_mean(self, name: Optional[str] = None, target: Any = '0', *,
                         reset_trigger: Optional[str] = None, start_trigger: Optional[str] = None,
                         stop_trigger: Optional[str] = None, unit: str = '', system: str = '',
                         index_lists: Optional[Sequence[str]] = None, comment: Optional[str] = None,
                         position: Optional[XY] = None) -> RunningMean:
        """Adds a running mean: the mean of ``target`` over the time it has recorded."""
        return self._recorder('running_mean', name, target, {
            'target': equation_text(target), 'reset_trigger': reset_trigger,
            'start_trigger': start_trigger, 'stop_trigger': stop_trigger,
        }, unit, system, comment, index_lists, position)  # type: ignore[return-value]

    def add_snapshot(self, name: Optional[str] = None, target: Any = '0', trigger: Optional[str] = None, *,
                     initial: Any = '0', unit: str = '', system: str = '',
                     index_lists: Optional[Sequence[str]] = None, comment: Optional[str] = None,
                     position: Optional[XY] = None) -> Snapshot:
        """Adds a snapshot: ``target`` as it was when ``trigger`` last fired,
        ``initial`` until then."""
        return self._recorder('snapshot', name, target, {
            'target': equation_text(target), 'trigger': trigger, 'initial': equation_text(initial),
        }, unit, system, comment, index_lists, position)  # type: ignore[return-value]

    def add_delay(self, name: Optional[str] = None, target: Any = '0', delay: Any = '0', *, unit: str = '',
                  system: str = '', index_lists: Optional[Sequence[str]] = None,
                  comment: Optional[str] = None, position: Optional[XY] = None) -> Delay:
        """Adds a delay: ``target`` as it was ``delay`` ago."""
        return self._recorder('delay', name, target, {
            'target': equation_text(target), 'delay': equation_text(delay),
        }, unit, system, comment, index_lists, position)  # type: ignore[return-value]

    def add_trigger(self, name: Optional[str] = None, first: Any = '0', second: Any = '0', *,
                    direction: str = 'rising', unit: str = '', system: str = '',
                    index_lists: Optional[Sequence[str]] = None, comment: Optional[str] = None,
                    position: Optional[XY] = None) -> Trigger:
        """Adds a trigger: the instant ``first`` crosses ``second`` (``rising``,
        ``falling`` or ``both``). The solver stops there, and recorders and
        snapshots can be driven by it."""
        if direction not in DIRECTIONS:
            raise EditError(f"'{direction}' is not a crossing direction ({', '.join(DIRECTIONS)})")
        return self._recorder('trigger', name, first, {
            'first': equation_text(first), 'second': equation_text(second), 'direction': direction,
        }, unit, system, comment, index_lists, position)  # type: ignore[return-value]

    def add_farfield(self, name: Optional[str] = None, *, index_lists: Optional[Sequence[str]] = None,
                     system: str = '', comment: Optional[str] = None, position: Optional[XY] = None,
                     **settings: Any) -> Farfield:
        """Adds a far-field path (FARFCOMP), indexed by the radionuclides, with
        the reference implementation's defaults for every setting not given
        (``tw``, ``f``, ``kd_f``, ``kd_m``, ``de_m``, ``eps_m``, ``rho_m``,
        ``pe``, ``pen_dep``, ``pen_dep_0``, ``n_f``, ``n_m``, ``o_b``, ``n_b``,
        ``handle_decay``, ``report_cells`` -- see :class:`Farfield`)."""
        material = self.material_dimension()
        if index_lists is None and not material:
            raise EditError('A far-field path needs the model to have radionuclides: it holds one path per '
                            'nuclide and lets them grow into one another.')
        unknown = [k for k in settings if k not in FARF_DEFAULTS]
        if unknown:
            raise EditError(f"A far-field path has no setting {', '.join(map(repr, unknown))}")
        n = self._name_for('farfield', name, system)
        raw: Dict[str, Any] = {'name': n, **copy.deepcopy(FARF_DEFAULTS),
                               'unit': f"{self.decay_unit}/{self._time_unit()}",
                               'index_lists': self._check_dims('farfield', list(index_lists))
                               if index_lists is not None else [material]}
        if comment:
            raw['comment'] = comment
        draft = Farfield(self, raw)
        for k, v in settings.items():
            setattr(draft, k, v)
        return self._append('farfields', raw, system, position)  # type: ignore[return-value]

    def add_waste_package(self, name: Optional[str] = None, *, failure: str = 'never',
                          index_lists: Optional[Sequence[str]] = None, system: str = '',
                          comment: Optional[str] = None, position: Optional[XY] = None,
                          **settings: Any) -> WastePackage:
        """Adds a set of waste packages, indexed by the radionuclides when the
        model has any. ``failure`` and the settings its law reads (``fail_at``,
        ``fail_from``, ``fail_to``, ``fail_start``, ``fail_rate``, ``fail_scale``,
        ``fail_shape``), and ``inventory``, ``irf``, ``degradation_rate``,
        ``packages``, ``handle_decay`` may be given."""
        unknown = [k for k in settings if k not in WASTE_DEFAULTS or k == 'failure']
        if unknown:
            raise EditError(f"Waste packages have no setting {', '.join(map(repr, unknown))} here")
        material = self.material_dimension()
        n = self._name_for('waste_package', name, system)
        raw: Dict[str, Any] = {'name': n, **copy.deepcopy(WASTE_DEFAULTS),
                               'unit': f"{self.decay_unit}/{self._time_unit()}",
                               'index_lists': self._check_dims('waste_package', list(index_lists))
                               if index_lists is not None else ([material] if material else [])}
        if comment:
            raw['comment'] = comment
        draft = WastePackage(self, raw)
        for k, v in settings.items():
            setattr(draft, k, v)
        if failure != 'never':
            draft.set_failure(failure)
        return self._append('waste_packages', raw, system, position)  # type: ignore[return-value]

    def add_event(self, name: Optional[str] = None, *, timing: str = 'at', at: Any = '', rate: Any = '',
                  start: Any = '', until: Any = '', sampled: bool = True, system: str = '',
                  comment: Optional[str] = None, position: Optional[XY] = None) -> Event:
        """Adds a disruptive event: once ``at`` a time (``timing='at'``), or at
        random at ``rate`` per unit time between ``start`` and ``until``
        (``timing='poisson'``; blank is the run's start and end). Give it
        actions with :meth:`Event.add_fail_action` and :meth:`Event.add_move_action`."""
        n = self._name_for('event', name, system)
        raw: Dict[str, Any] = {'name': n, **copy.deepcopy(EVENT_DEFAULTS), 'unit': '', 'index_lists': []}
        if comment:
            raw['comment'] = comment
        draft = Event(self, raw)
        draft.timing = timing
        draft.at, draft.rate, draft.start, draft.until = at, rate, start, until
        draft.sampled = sampled
        return self._append('events', raw, system, position)  # type: ignore[return-value]

    # --- connections and releases ---------------------------------------------------------------

    def set_connection_end(self, name: str, end: str, target: Optional[str]) -> Block:
        """Re-attaches one end (``'from'`` or ``'to'``) of a transfer or inflow;
        ``None`` is outside the model. A transfer moves with its donor."""
        b = self.block(name)
        if end not in ('from', 'to'):
            raise EditError(f"'{end}' is not an end of a connection (from, to)")
        if b.kind == 'inflow':
            if end == 'from':
                raise EditError('A source always comes from outside the model')
            if target is None:
                raise EditError('A source needs a target compartment')
            b.raw['to'] = self._endpoint(target, 'to')
            self._sync_transfer_dimensions()
            return self._rehome(b)
        if b.kind != 'transfer':
            raise EditError(f"'{name}' is not a connection")
        new = self._endpoint(target, end)
        other = b.raw.get('to') if end == 'from' else b.raw.get('from')
        if new is not None and new == other:
            raise EditError('A transfer cannot start and end at the same compartment')
        if new is None and other is None:
            raise EditError('A transfer needs a compartment at one end at least')
        if end == 'from' and new is not None and self._kind_of(new) in RELEASING:
            taken = self._release_taken(new, allow=b.qualified_name)
            if taken:
                raise EditError(taken)
        b.raw[end] = new
        if b.raw.get('from') is None:
            b.raw['multiply_by_donor'] = False
        if b.raw.get('from') is not None and self._kind_of(b.raw['from']) in RELEASING:
            b.raw['rate'] = b.raw['from']
            b.raw['multiply_by_donor'] = False
        self._sync_transfer_dimensions()
        return self._rehome(b)

    def _rehome(self, b: Block) -> Block:
        home = parent_of(b.raw.get('from') if b.raw.get('from') is not None else b.raw.get('to'))
        if b.system == home:
            return b
        return self.block(self.move_block(b.qualified_name, home))

    def set_release(self, path: str, to: Optional[str]) -> Optional[Transfer]:
        """Sends a far-field path's or waste packages' release to a compartment,
        or nowhere (``None``: the release is only read, by name). A block has
        one release, so pointing it somewhere new moves the one there is."""
        b = self.block(path)
        if b.kind not in RELEASING:
            raise EditError(f"'{path}' has no release to send anywhere")
        held = [t for t in self._raw.get('transfers') or [] if t.get('from') == b.qualified_name]
        if to is None or to == '':
            for t in held:
                self.delete_block(qualified_name(t))
            return None
        target = self._endpoint(to, 'to')
        if len(held) == 1 and held[0].get('to') == target:
            return self.block(qualified_name(held[0]))  # type: ignore[return-value]
        if held:
            for t in held[1:]:
                self.delete_block(qualified_name(t))
            return self.set_connection_end(qualified_name(held[0]), 'to', target)  # type: ignore[return-value]
        return self.add_transfer(b.qualified_name, target)

    # --- the equations of the model, walked ---------------------------------------------------

    def _all_raw(self) -> Iterator[Dict[str, Any]]:
        for collection in COLLECTIONS:
            for b in self._raw.get(collection) or []:
                if isinstance(b, dict):
                    yield b

    def _each_equation(self, fn: Callable[[str, str, Dict[str, Any], Optional[Set[str]]], Optional[str]]) -> None:
        """Calls ``fn(text, system, block, locals)`` on every equation in the
        model; a string returned replaces the text. Per-index equations are
        visited as their block's, and so are a transfer's availability
        operands and an event's action shares."""

        def visit(holder: Dict[str, Any], key: str, system: str, block: Dict[str, Any],
                  locals_: Optional[Set[str]] = None) -> None:
            v = holder.get(key)
            if isinstance(v, str):
                nxt = fn(v, system, block, locals_)
                if nxt is not None:
                    holder[key] = nxt

        def both(block: Dict[str, Any], key: str, locals_: Optional[Set[str]] = None) -> None:
            system = system_of(block)
            visit(block, key, system, block, locals_)
            for e in block.get('entries') or []:
                visit(e, key, system, block, locals_)

        for t in self._raw.get('transfers') or []:
            both(t, 'rate')
            a = t.get('availability')
            if isinstance(a, dict):
                for key in ('limit', 'top', 'bottom'):
                    visit(a, key, system_of(t), t)
        for s in self._raw.get('inflows') or []:
            both(s, 'rate')
        for e in self._raw.get('expressions') or []:
            both(e, 'equation')
        for kind, collection in RECORDER_COLLECTION.items():
            for b in self._raw.get(collection) or []:
                for key in RECORDER_EQUATIONS[kind] + RECORDER_TRIGGERS[kind]:
                    both(b, key)
        for f in self._raw.get('functions') or []:
            both(f, 'equation', set(map(str, f.get('parameters') or [])))
        for c in self._raw.get('compartments') or []:
            both(c, 'initial')
            both(c, 'dydt')
        for f in self._raw.get('farfields') or []:
            for key in FARF_EQUATION_KEYS:
                both(f, key)
        for w in self._raw.get('waste_packages') or []:
            for key in WASTE_EQUATION_KEYS:
                both(w, key)
        for d in self._raw.get('events') or []:
            for key in EVENT_EQUATION_KEYS:
                both(d, key)
            for a in d.get('actions') or []:
                visit(a, 'fraction', system_of(d), d)

    def _each_target(self, fn: Callable[[str, str, Dict[str, Any]], str]) -> None:
        """Calls ``fn(name, system, block)`` on every block name a reduction
        reduces; what it returns replaces the name."""
        for o in self._raw.get('index_reductions') or []:
            system = system_of(o)
            if isinstance(o.get('target'), str) and o['target']:
                o['target'] = fn(o['target'], system, o)
            for e in o.get('entries') or []:
                if isinstance(e.get('target'), str) and e['target']:
                    e['target'] = fn(e['target'], system, o)
        for g in self._raw.get('block_reductions') or []:
            system = system_of(g)
            if isinstance(g.get('targets'), list):
                g['targets'] = [fn(t, system, g) for t in g['targets']]
            for e in g.get('entries') or []:
                if isinstance(e.get('targets'), list):
                    e['targets'] = [fn(t, system, g) for t in e['targets']]

    def references_graph(self) -> Dict[str, List[str]]:
        """Every block's qualified name -> the blocks it reads: in its
        equations, as its targets, at its ends, in its actions."""
        known = self._known()
        reads: Dict[str, List[str]] = {q: [] for q in self._idx()}

        def note(referrer: str, target: Optional[str]) -> None:
            if target is None or target == referrer or target not in reads:
                return
            lst = reads.setdefault(referrer, [])
            if target not in lst:
                lst.append(target)

        def equation(text: str, system: str, block: Dict[str, Any], locals_: Optional[Set[str]]) -> None:
            for q in references_in(text, system, known, locals_):
                note(qualified_name(block), q)

        self._each_equation(equation)  # type: ignore[arg-type]

        def target(ref: str, system: str, block: Dict[str, Any]) -> str:
            note(qualified_name(block), resolve_reference(ref.strip(), system, known))
            return ref

        self._each_target(target)
        for t in self._raw.get('transfers') or []:
            note(qualified_name(t), t.get('from'))
            note(qualified_name(t), t.get('to'))
        for s in self._raw.get('inflows') or []:
            note(qualified_name(s), s.get('to'))
        for d in self._raw.get('events') or []:
            for a in d.get('actions') or []:
                for end in ('block', 'from', 'to'):
                    v = a.get(end)
                    if isinstance(v, str) and v.strip():
                        note(qualified_name(d), resolve_reference(v.strip(), system_of(d), known))
        return reads

    def reads(self, name: str) -> List[str]:
        """The blocks ``name`` reads: in its equations, as its targets, at its ends."""
        self.block(name)
        return self.references_graph().get(name, [])

    def references_to(self, name: str) -> List[str]:
        """The blocks that read ``name``: in an equation, as a reduction target,
        as a transfer end or in an event's action."""
        self.block(name)
        return [q for q, targets in self.references_graph().items() if name in targets]

    # --- renaming, moving, deleting ---------------------------------------------------------------

    def _refuse_shadowed(self, known: Callable[[str], bool],
                         retarget: Callable[[str, str, Dict[str, Any]], Optional[Tuple[str, str]]]) -> None:
        shadowed: List[Tuple[str, str, str, str]] = []

        def check(text: str, system: str, block: Dict[str, Any], locals_: Optional[Set[str]]) -> None:
            def replace(q: str, _system: str) -> None:
                r = retarget(q, system, block)
                if r is None:
                    return None
                to, where = r
                spelled = reference_from(to, where, known)
                found = resolve_reference(spelled, where, known)
                if found and found != to:
                    shadowed.append((qualified_name(block), spelled, to, where))
                return None
            rewrite_references(text, system, known, replace, locals_)
            return None

        self._each_equation(check)
        if shadowed:
            block, spelled, to, where = shadowed[0]
            more = f' (and {len(shadowed) - 1} more)' if len(shadowed) > 1 else ''
            raise EditError(
                f"'{block}' reads '{to}', which from inside '{where or 'the top level'}' would have to be "
                f"written '{spelled}' -- and there that name means a different block. Rename or move one "
                f'of the two first.{more}', [s[0] for s in shadowed])

    def _retarget_all(self, new_name_of: Callable[[str], Optional[str]],
                      new_system_of: Callable[[str, Dict[str, Any]], str],
                      also_known: Iterable[str] = ()) -> None:
        known = self._known(also_known)

        def moved(q: str, system: str, block: Dict[str, Any]) -> Optional[Tuple[str, str]]:
            to = new_name_of(q) or q
            where = new_system_of(system, block)
            return None if to == q and where == system else (to, where)

        self._refuse_shadowed(known, moved)
        for conn in (self._raw.get('transfers') or []) + (self._raw.get('inflows') or []):
            for end in ('from', 'to'):
                if conn.get(end) is not None:
                    conn[end] = new_name_of(conn[end]) or conn[end]
        for d in self._raw.get('events') or []:
            for a in d.get('actions') or []:
                for end in ('block', 'from', 'to'):
                    if isinstance(a.get(end), str) and a[end]:
                        a[end] = new_name_of(a[end]) or a[end]

        def rewrite(text: str, system: str, block: Dict[str, Any], locals_: Optional[Set[str]]) -> str:
            def replace(q: str, _system: str) -> Optional[str]:
                r = moved(q, system, block)
                return None if r is None else reference_from(r[0], r[1], known)
            return rewrite_references(text, system, known, replace, locals_)

        self._each_equation(rewrite)

        def target(ref: str, system: str, block: Dict[str, Any]) -> str:
            q = resolve_reference(ref, system, known)
            if q is None:
                return ref
            r = moved(q, system, block)
            return ref if r is None else reference_from(r[0], r[1], known)

        self._each_target(target)
        moves: Dict[str, Dict[str, str]] = {}
        for collection, list_name in (('compartments', COMPARTMENT_LIST), ('transfers', TRANSFER_LIST)):
            m = {}
            for b in self._raw.get(collection) or []:
                was = qualified_name(b)
                to = new_name_of(was)
                if to and to != was:
                    m[was] = to
            if m:
                moves[list_name] = m
        self._retarget_block_indexes(moves)

    def _retarget_block_indexes(self, moves: Dict[str, Dict[str, str]]) -> None:
        if not any(moves.values()):
            return
        lists = self._lists()
        written: Dict[str, Optional[str]] = {}
        for list_name, m in moves.items():
            for frm, to in m.items():
                ambiguous = any(l.get('name') != list_name
                                and frm in [index_name(i) for i in l.get('indices') or []]
                                for l in lists)
                written[frm] = None if (ambiguous or frm in written) else to
        for b in self._all_raw():
            for e in b.get('entries') or []:
                ix = e.get('index')
                if not isinstance(ix, dict):
                    continue
                for list_name, m in moves.items():
                    was = ix.get(list_name)
                    if was is not None and was in m:
                        ix[list_name] = m[was]
        if not any(written.values()):
            return
        mapping = written.get
        self._each_equation(lambda text, system, block, locals_: rewrite_written_indices(text, mapping))
        self._each_target(lambda ref, system, block: rewrite_written_indices(ref, mapping))

    def _retarget_layout(self, new_name_of: Callable[[str], Optional[str]],
                         canvas_of: Optional[Callable[[str], str]] = None) -> None:
        layout = self._raw.get('layout')
        if not isinstance(layout, dict) or not layout:
            return
        nxt: Dict[str, Any] = {}
        for key, value in layout.items():
            edge = _parse_edge_key(key)
            if edge is not None:
                name, canvas = edge
                if canvas not in (None, ''):
                    canvas = canvas_of(canvas) if canvas_of else (new_name_of(canvas) or canvas)
                nxt[_edge_key(new_name_of(name) or name, canvas)] = value
                continue
            nxt[new_name_of(key) or key] = value
        self._raw['layout'] = nxt

    def rename_block(self, name: str, new_name: str) -> str:
        """Renames a block -- a local name; use :meth:`move_block` to change its
        sub-system -- and follows the change through every reference:
        equations, transfer ends, reduction targets, event actions, per-index
        values keyed by it, its place on the diagram. Returns the new
        qualified name."""
        b = self.block(name)
        if base_name(new_name) != new_name:
            raise EditError(f"'{new_name}' is a path, not a name. Use move_block() to put a block in "
                            'another sub-system.')
        target = qualify(b.system, new_name)
        if target == name:
            return name
        self._check_new_name(new_name, b.system, allow=name)
        self._retarget_all(lambda q: target if q == name else None, lambda s, blk: s, [target])
        b.raw['name'] = new_name
        layout = self._raw.get('layout')
        if isinstance(layout, dict) and layout:
            # One name moves, and its entries move to the end, as the application's do.
            keys = [name] + [k for k in layout if (_parse_edge_key(k) or ('',))[0] == name]
            for key in keys:
                if key not in layout:
                    continue
                edge = _parse_edge_key(key)
                to = _edge_key(target, edge[1]) if edge else target
                layout[to] = layout.pop(key)
        self._invalidate()
        return target

    def move_block(self, name: str, system: str = '') -> str:
        """Moves a block into another sub-system (``''``: the top level),
        numbering its name if it is taken there, and rewrites every reference.
        A compartment takes its outgoing transfers and its inflows with it.
        Returns the new qualified name."""
        b = self.block(name)
        self._check_system(system)
        if b.system == system:
            return name
        role = b.raw.get('transport')
        home = self._transport_of(b.raw)
        if home:
            raise EditError(f"'{b.name}' is the transport {role} of '{home}' and stays in it.")
        if role:
            b.raw.pop('transport', None)
        local = b.name
        k = 1
        while self._find(qualify(system, local)) is not None:
            local = f'{b.name}{k}'
            k += 1
        target = qualify(system, local)
        raw = b.raw
        self._retarget_all(lambda q: target if q == name else None,
                           lambda s, blk: system if blk is raw else s, [target])
        self._retarget_layout(lambda q: target if q == name else None)
        raw['name'] = local
        if system:
            raw['system'] = system
        else:
            raw.pop('system', None)
        self._invalidate()
        if b.kind == 'compartment':
            attached = [t for t in self._raw.get('transfers') or [] if t.get('from') == target] + \
                       [s for s in self._raw.get('inflows') or [] if s.get('to') == target]
            for conn in attached:
                if system_of(conn) != system:
                    self.move_block(qualified_name(conn), system)
        return target

    def move_blocks(self, names: Iterable[str], system: str = '') -> Dict[str, str]:
        """Moves several blocks into one sub-system as one edit: all of them or
        none. Returns ``{old name: new name}``."""
        wanted = list(dict.fromkeys(names))
        self._check_system(system)
        for n in wanted:
            self.block(n)
        before = copy.deepcopy(self._raw)
        moved: Dict[str, str] = {}
        try:
            for n in wanted:
                if n in moved:
                    continue
                moved[n] = self.move_block(n, system)
        except EditError:
            self._raw.clear()
            self._raw.update(before)
            self._invalidate()
            raise
        return moved

    def _guard_transport_parts(self, going: Set[str]) -> None:
        for name in going:
            hit = self._find(name)
            if hit is None:
                continue
            raw = hit[1]
            role = raw.get('transport')
            if role not in ('begin', 'end', 'number'):
                continue
            path = self._transport_of(raw)
            if not path:
                continue
            if all(qualified_name(b) in going for b in self._all_raw() if system_of(b) == path):
                continue
            raise EditError(f"'{raw.get('name')}' is the transport {role} of '{path}', and a transport is a "
                            'chain from its Begin to its End. Delete the transport instead, with '
                            'delete_system(path, contents="delete").')

    def delete_blocks(self, names: Iterable[str]) -> List[str]:
        """Deletes several blocks as one edit. The transfers and inflows of a
        compartment (or a path, or waste packages) go with it. Anything outside
        the set still reading one of them refuses the delete, naming what reads
        it -- two blocks reading each other can go together. Returns what was
        removed."""
        wanted = list(dict.fromkeys(names))
        for n in wanted:
            self.block(n)
        going: Dict[str, None] = dict.fromkeys(wanted)
        for n in wanted:
            if self._kind_of(n) not in HOLDS_INVENTORY:
                continue
            for t in self._raw.get('transfers') or []:
                if t.get('from') == n or t.get('to') == n:
                    going.setdefault(qualified_name(t))
            for s in self._raw.get('inflows') or []:
                if s.get('to') == n:
                    going.setdefault(qualified_name(s))
        gone = set(going)
        self._guard_transport_parts(gone)
        graph = self.references_graph()
        blocked: Dict[str, List[str]] = {}
        for referrer, targets in graph.items():
            if referrer in gone:
                continue
            for t in targets:
                if t in gone:
                    blocked.setdefault(t, []).append(referrer)
        if blocked:
            order = [n for n in going if n in blocked]
            first = order[0]
            rest = len(blocked) - 1
            raise EditError(f"'{first}' is still used by {', '.join(blocked[first])}."
                            + (f" {rest} more of the selection {'is' if rest == 1 else 'are'} too." if rest else '')
                            + ' Change those equations first.',
                            list(dict.fromkeys(u for n in order for u in blocked[n])))
        removed = []
        for q in going:
            hit = self._find(q)
            if hit is None:
                continue
            collection, raw = hit
            self._raw[collection] = [b for b in self._raw[collection] if b is not raw]
            self._invalidate()
            layout = self._raw.get('layout')
            if isinstance(layout, dict):
                layout.pop(q, None)
            removed.append(q)
            list_name = COMPARTMENT_LIST if collection == 'compartments' else (
                TRANSFER_LIST if collection == 'transfers' else None)
            if list_name:
                for b in self._all_raw():
                    if isinstance(b.get('entries'), list):
                        b['entries'] = [e for e in b['entries'] if (e.get('index') or {}).get(list_name) != q]
        return removed

    def delete_block(self, name: str) -> List[str]:
        """Deletes a block. A compartment's (or path's, or packages') transfers
        and inflows go with it; anything else still reading it refuses the
        delete. Returns the qualified names removed."""
        return self.delete_blocks([name])

    # --- sub-systems and transports ---------------------------------------------------------------

    def _system_set(self) -> Set[str]:
        fp = (id(self._raw.get('systems')), len(self._raw.get('systems') or ()),
              id(self._raw.get('transports')), len(self._raw.get('transports') or ()))
        if self._systems is None or self._systems_fp != fp:
            self._systems = system_paths(self._raw.get('systems') or [], self._raw.get('transports') or [],
                                         (system_of(b) for b in self._all_raw()))
            self._systems_fp = fp
            self._system_lookup = set(self._systems)
        return self._system_lookup

    @property
    def systems(self) -> List[str]:
        """Every sub-system, as a dotted path, shallowest first."""
        self._system_set()
        return list(self._systems or [])

    @property
    def transports(self) -> List[str]:
        """The sub-systems that are transports: a chain of N compartments drawn as two."""
        out = []
        for p in self._raw.get('transports') or []:
            path = p if isinstance(p, str) else (p or {}).get('name') if isinstance(p, dict) else None
            if path:
                out.append(path)
        return out

    def _next_system_name(self, parent: str, base: str, allow: Optional[str] = None) -> str:
        existing = self._system_set() | set(self._idx())
        if allow:
            existing = existing - {allow}
        local = base
        i = 1
        while qualify(parent, local) in existing:
            local = f'{base}{i}'
            i += 1
        return local

    def add_system(self, name: Optional[str] = None, parent: str = '') -> str:
        """Creates a sub-system inside ``parent`` (``''``: the top level) and
        returns its path. A name another sub-system already has there is
        numbered (``Sub`` becomes ``Sub1``); one a block has is refused."""
        self._check_system(parent)
        if parent and parent in self.transports:
            raise EditError(f"'{parent}' is a transport, which is a chain of compartments and holds no "
                            'sub-system of its own.')
        if name is not None:
            problem = name_problem(name)
            if problem:
                raise EditError(problem)
            if self._find(qualify(parent, name)) is not None:
                raise EditError(f"'{name}' is already used by a block in {repr(parent) if parent else 'this model'}. "
                                'A sub-system and a block cannot share a name.')
        path = qualify(parent, self._next_system_name(parent, name if name is not None else 'Sub'))
        if not isinstance(self._raw.get('systems'), list):
            self._raw['systems'] = self.systems
        self._raw['systems'].append(path)
        self._systems = None
        return path

    def rename_system(self, path: str, new_name: str) -> str:
        """Renames a sub-system -- and so every block inside it -- following
        every reference. Returns the new path."""
        if not path:
            raise EditError('The model itself has no name to change')
        self._check_system(path)
        if not new_name or base_name(new_name) != new_name or not is_valid_path(new_name):
            raise EditError(f"'{new_name}' is not a valid name for a sub-system (letters, digits and "
                            'underscore; must not start with a digit)')
        parent = parent_of(path)
        target = qualify(parent, new_name)
        if target == path:
            return path
        if target in self._system_set():
            raise EditError(f"'{new_name}' is already a sub-system of {repr(parent) if parent else 'this model'}")
        if self._find(target) is not None:
            raise EditError(f"'{new_name}' is already used by a block in {repr(parent) if parent else 'this model'}. "
                            'A sub-system and a block cannot share a name.')
        if new_name in RESERVED:
            raise EditError(f"'{new_name}' is a reserved name.")
        return self._relocate_system(path, target)

    def move_system(self, path: str, parent: str = '') -> str:
        """Moves a sub-system into another (``''``: the top level), numbering
        its name if taken there. Returns its new path."""
        if not path:
            raise EditError('The model itself cannot be moved')
        self._check_system(path)
        self._check_system(parent)
        if parent and is_within(parent, path):
            raise EditError(f"'{base_name(path)}' cannot be moved into itself" if parent == path
                            else f"'{base_name(path)}' cannot be moved into '{parent}', which is inside it")
        if parent and parent in self.transports:
            raise EditError(f"'{parent}' is a transport, which is a chain of compartments and holds no "
                            'sub-system of its own.')
        if parent_of(path) == parent:
            return path
        taken = self._system_set() | set(self._idx())
        local = base_name(path)
        k = 1
        while qualify(parent, local) in taken:
            local = f'{base_name(path)}{k}'
            k += 1
        return self._relocate_system(path, qualify(parent, local))

    def _relocate_system(self, path: str, target: str) -> str:
        moved: Dict[str, str] = {}
        for b in self._all_raw():
            if is_within(system_of(b), path):
                moved[qualified_name(b)] = qualify(reparent(system_of(b), path, target), b.get('name', ''))
        self._retarget_all(moved.get, lambda s, blk: reparent(s, path, target), moved.values())
        self._retarget_layout(moved.get,
                              lambda canvas: reparent(canvas, path, target) if is_within(canvas, path) else canvas)
        systems_before = self.systems
        for b in self._all_raw():
            if is_within(system_of(b), path):
                b['system'] = reparent(system_of(b), path, target)
        self._raw['systems'] = list(dict.fromkeys(reparent(p, path, target) for p in systems_before))
        if self.transports:
            self._raw['transports'] = [reparent(p, path, target) for p in self.transports]
        if self._disabled_systems():
            self._raw['disabled_systems'] = [reparent(p, path, target) for p in self._disabled_systems()]
        layout = self._raw.get('layout')
        if isinstance(layout, dict) and layout.get(path) is not None:
            layout[target] = layout.pop(path)
        for sh in self._raw.get('shapes') or []:
            if isinstance(sh, dict) and is_within(sh.get('system') or '', path):
                to = reparent(sh.get('system') or '', path, target)
                if to:
                    sh['system'] = to
                else:
                    sh.pop('system', None)
        self._invalidate()
        return target

    def delete_system(self, path: str, contents: str = 'move') -> str:
        """Removes a sub-system. Its contents move out to the sub-system around
        it (numbered where names collide), or are deleted with
        ``contents='delete'`` -- which a transport always needs. Returns the
        parent's path."""
        if not path:
            raise EditError('The model itself cannot be removed')
        self._check_system(path)
        if contents not in ('move', 'delete'):
            raise EditError("contents is 'move' or 'delete'")
        parent = parent_of(path)
        systems_before = self.systems
        systems_out: Dict[str, str] = {}
        if contents == 'delete':
            self.delete_blocks([qualified_name(b) for b in self._all_raw() if is_within(system_of(b), path)])
            shapes = self._raw.get('shapes')
            if isinstance(shapes, list):
                self._raw['shapes'] = [sh for sh in shapes
                                       if not (isinstance(sh, dict) and is_within(sh.get('system') or '', path))]
        else:
            if path in self.transports:
                raise EditError(f"'{path}' is a transport, and a transport is a chain from its Begin to its End "
                                'rather than a place blocks are kept: its parts cannot be let out as ordinary '
                                'blocks. Delete it, with everything in it (contents="delete").')
            taken_systems = {p for p in systems_before if not is_within(p, path)}
            nested = sorted((p for p in systems_before if is_within(p, path) and p != path),
                            key=lambda p: len(parts(p)))
            for p in nested:
                frm = parent_of(p)
                home = parent if frm == path else systems_out.get(frm, frm)
                local = base_name(p)
                k = 1
                while qualify(home, local) in taken_systems:
                    local = f'{base_name(p)}{k}'
                    k += 1
                to = qualify(home, local)
                taken_systems.add(to)
                systems_out[p] = to

            def home_of(system: str) -> str:
                return parent if system == path else systems_out.get(system, reparent(system, path, parent))

            moved: Dict[str, str] = {}
            taken = self._names()
            for b in self._all_raw():
                if not is_within(system_of(b), path):
                    continue
                to_sys = home_of(system_of(b))
                local = b.get('name', '')
                k = 1
                while qualify(to_sys, local) in taken:
                    local = f"{b.get('name', '')}{k}"
                    k += 1
                taken.add(qualify(to_sys, local))
                moved[qualified_name(b)] = qualify(to_sys, local)
            self._retarget_all(moved.get, lambda s, blk: home_of(s) if is_within(s, path) else s, moved.values())
            self._retarget_layout(moved.get)
            for b in self._all_raw():
                was = qualified_name(b)
                if was not in moved:
                    continue
                now = moved[was]
                b['system'] = parent_of(now)
                b['name'] = base_name(now)
                if not b['system']:
                    del b['system']
            layout = self._raw.get('layout')
            for was, now in systems_out.items():
                if isinstance(layout, dict) and layout.get(was) is not None:
                    layout[now] = layout.pop(was)
            for sh in self._raw.get('shapes') or []:
                if isinstance(sh, dict) and is_within(sh.get('system') or '', path):
                    to = reparent(sh.get('system') or '', path, parent)
                    if to:
                        sh['system'] = to
                    else:
                        sh.pop('system', None)

        def keep(p: str) -> Optional[str]:
            if p == path:
                return None
            if is_within(p, path):
                return systems_out.get(p)
            return p

        self._invalidate()
        self._raw['systems'] = list(dict.fromkeys(q for q in (keep(p) for p in self.systems) if q))
        if self._disabled_systems():
            ds = [q for q in (keep(p) for p in self._disabled_systems()) if q]
            if ds:
                self._raw['disabled_systems'] = ds
            else:
                self._raw.pop('disabled_systems', None)
        if self.transports:
            self._raw['transports'] = [q for q in (keep(p) for p in self.transports) if q]
        layout = self._raw.get('layout')
        if isinstance(layout, dict):
            layout.pop(path, None)
        self._invalidate()
        return parent

    def _disabled_systems(self) -> List[str]:
        return [str(p).strip() for p in self._raw.get('disabled_systems') or [] if p is not None and str(p).strip()]

    def system_enabled(self, path: str) -> bool:
        """Whether a sub-system takes part in the run: neither it nor any
        sub-system around it is switched off."""
        if not path:
            return True
        return not any(is_within(path, p) for p in self._disabled_systems())

    def set_system_enabled(self, path: str, on: bool) -> None:
        """Switches a whole sub-system on or off; its blocks keep their own switches."""
        if not path or path not in self._system_set():
            raise EditError(f"No sub-system named '{path}'")
        off = [p for p in self._disabled_systems() if p != path]
        if not on:
            off.append(path)
        if off:
            self._raw['disabled_systems'] = off
        else:
            self._raw.pop('disabled_systems', None)

    def add_transport(self, name: Optional[str] = 'Transport', parent: str = '', *, number: Any = '5',
                      position: Optional[XY] = None) -> str:
        """Makes a transport: a sub-system standing for a chain of ``number``
        identical compartments, with the four blocks the application puts in
        one -- the Begin and End compartments, N and the element counter i.
        Returns its path."""
        path = self.add_system(name if name is not None else 'Transport', parent)
        if not isinstance(self._raw.get('transports'), list):
            self._raw['transports'] = self.transports
        self._raw['transports'].append(path)
        self._systems = None
        if position is not None:
            self._set_position(path, _position_of(position))
        begin = self.add_compartment(self.unique_name('Begin', path), system=path, position=(80, 90))
        begin.raw['transport'] = 'begin'
        end = self.add_compartment(self.unique_name('End', path), system=path, position=(420, 90))
        end.raw['transport'] = 'end'
        n = self.add_expression(self.unique_name('N', path), number, system=path)
        n.raw['transport'] = 'number'
        n.raw['index_lists'] = []
        self._set_position(n.qualified_name, (80, 210))
        i = self.add_expression(self.unique_name('i', path), '1', system=path)
        i.raw['transport'] = 'counter'
        i.raw['index_lists'] = []
        self._set_position(i.qualified_name, (420, 210))
        return path

    def add_transport_operation(self, system: str, name: Optional[str] = None, *,
                                operation: str = 'mean', argument: str = 'all',
                                position: Optional[XY] = None) -> Expression:
        """Adds an operation over a transport's chain: the ``sum`` or ``mean`` of
        its compartments, read as a value (``argument='all'``) or called with a
        position along it (``'point'``) or two (``'range'``)."""
        if system not in self.transports:
            raise EditError(f"'{system or 'The top level'}' is not a transport, so an operation over its "
                            'chain has nothing to work on.')
        if operation not in TRANSPORT_OPERATIONS:
            raise EditError(f"'{operation}' is not a transport operation ({', '.join(TRANSPORT_OPERATIONS)})")
        if argument not in TRANSPORT_ARGUMENTS:
            raise EditError(f"'{argument}' is not a way of reading one ({', '.join(TRANSPORT_ARGUMENTS)})")
        begin = self._transport_parts(system)['begin'] or {}
        n = name if name is not None else self.unique_name('TransportOp', system)
        raw: Dict[str, Any] = {'name': n, 'equation': '0', 'unit': begin.get('unit', ''),
                               'index_lists': list(begin.get('index_lists') or []),
                               'transport': 'operation', 'operation': operation, 'argument': argument}
        return self._append('expressions', raw, system, position)  # type: ignore[return-value]

    # --- layout, shapes, derived outputs -------------------------------------------------------

    def _set_position(self, name: str, xy: Optional[XY]) -> None:
        layout = self.layout
        entry = layout.get(name)
        if xy is None:
            if isinstance(entry, dict):
                entry.pop('x', None)
                entry.pop('y', None)
                if not entry:
                    layout.pop(name)
            return
        if not isinstance(entry, dict):
            entry = {}
        entry['x'] = _js_round(xy[0])
        entry['y'] = _js_round(xy[1])
        layout[name] = entry

    def _set_size(self, name: str, wh: Optional[XY]) -> None:
        layout = self.layout
        entry = layout.get(name)
        if wh is None:
            if isinstance(entry, dict):
                entry.pop('w', None)
                entry.pop('h', None)
            return
        if not isinstance(entry, dict):
            entry = {'x': 0, 'y': 0}
        entry['w'] = _js_round(min(520, max(60, wh[0])))
        entry['h'] = _js_round(min(320, max(32, wh[1])))
        layout[name] = entry

    def system_position(self, path: str) -> Optional[XY]:
        """Where a sub-system's node is drawn on its parent's canvas."""
        entry = self.layout.get(path)
        return (entry['x'], entry['y']) if isinstance(entry, dict) and 'x' in entry and 'y' in entry else None

    def set_system_position(self, path: str, xy: Optional[XY]) -> None:
        self._check_system(path)
        self._set_position(path, _position_of(xy) if xy is not None else None)

    @property
    def shapes(self) -> List[Shape]:
        """The annotations drawn on the canvases, in drawing order."""
        return [Shape(self, s) for s in self._raw.get('shapes') or [] if isinstance(s, dict)]

    def add_shape(self, figure: str, x: float = 0, y: float = 0, w: float = 180, h: float = 120, *,
                  system: str = '', **style: Any) -> Shape:
        """Draws a shape on a sub-system's canvas: ``figure`` is ``rect``,
        ``ellipse``, ``arrow``, ``line``, ``sticky`` or another of the
        application's figures, ``(x, y)`` its top-left corner. ``style`` sets
        ``fill``, ``line``, ``line_width``, ``dash``, ``text`` and the rest of
        :attr:`Shape.ALLOWED`."""
        name = str(figure or '').strip()
        if not name:
            raise EditError('A shape needs a figure to draw')
        self._check_system(system)
        taken = {s.get('id') for s in self._raw.get('shapes') or [] if isinstance(s, dict)}
        k = 1
        while f'sh{k}' in taken:
            k += 1
        raw: Dict[str, Any] = {'id': f'sh{k}', 'figure': name}
        if system:
            raw['system'] = system
        raw.update({'x': _js_round(x), 'y': _js_round(y), 'w': _js_round(w), 'h': _js_round(h),
                    'fill': 'slate', 'line': 'slate', 'line_width': 2, 'dash': 'solid'})
        if name == 'sticky':
            raw.update({'fill': 'amber', 'line': 'none', 'text_font': 'scribble', 'text_align': 'left',
                        'text_size': 18})
        if not isinstance(self._raw.get('shapes'), list):
            self._raw['shapes'] = []
        self._raw['shapes'].append(raw)
        shape = Shape(self, raw)
        try:
            shape.update(**style)
        except EditError:
            self._raw['shapes'] = [s for s in self._raw['shapes'] if s is not raw]
            raise
        return shape

    def remove_shape(self, shape_id: str) -> None:
        """Removes a shape by its id."""
        shapes = self._raw.get('shapes') or []
        for k, s in enumerate(shapes):
            if isinstance(s, dict) and s.get('id') == shape_id:
                del shapes[k]
                return
        raise EditError(f"No shape '{shape_id}'")

    @property
    def derived(self) -> List[Dict[str, Any]]:
        """Numbers read off the finished curves -- a peak, when it peaked, a
        total -- live: each ``{name, kind, of, at?, period?}``."""
        if not isinstance(self._raw.get('derived'), list):
            self._raw['derived'] = []
        return self._raw['derived']

    def add_derived(self, name: str, kind: str, of: str, *, at: Optional[float] = None,
                    period: Optional[float] = None) -> Dict[str, Any]:
        """Adds a number read off a finished curve: ``kind`` is one of
        :data:`DERIVED_KINDS`, ``of`` the series' label as the chart spells it
        (``'Soil [Cs-137]'``); ``at`` for ``at_time``, ``period`` for the
        period kinds (in the run's time unit)."""
        if not str(name or '').strip():
            raise EditError('A derived output needs a name')
        if kind not in DERIVED_KINDS:
            raise EditError(f"'{kind}' is not one of {', '.join(DERIVED_KINDS)}.")
        if not str(of or '').strip():
            raise EditError('It does not say which series it is of.')
        d: Dict[str, Any] = {'name': name, 'kind': kind, 'of': of}
        if kind == 'at_time':
            if at is None or not math.isfinite(_js_number(at)):
                raise EditError(f"'{at}' is not a time. It has to be a number of the run's time unit.")
            d['at'] = at
        if kind in PERIOD_KINDS:
            if period is None or not _js_number(period) > 0:
                raise EditError(f"'{period}' is not a period. It has to be a length of time greater than zero.")
            d['period'] = period
        self.derived.append(d)
        return d

    def remove_derived(self, name: str) -> None:
        """Removes a derived output by its name."""
        before = len(self.derived)
        self._raw['derived'] = [d for d in self.derived if d.get('name') != name]
        if len(self._raw['derived']) == before:
            raise EditError(f"No derived output named '{name}'")

    # --- review tracking -------------------------------------------------------------------------

    @property
    def review_tracking(self) -> bool:
        """Whether the model tracks which definitions have been reviewed."""
        return (self._raw.get('simulation') or {}).get('qa') is True

    @review_tracking.setter
    def review_tracking(self, on: bool) -> None:
        self.simulation  # makes sure the settings exist
        sim = self._raw['simulation']
        if on:
            sim['qa'] = True
        else:
            sim.pop('qa', None)

    @staticmethod
    def review_stamp(block: Union[Block, Dict[str, Any]]) -> str:
        """What a review of the block covers, as the application stamps it:
        everything but where and how it is drawn, its comment and the record."""
        raw = block.raw if isinstance(block, Block) else block
        keep = {k: v for k, v in raw.items() if k not in NOT_REVIEWED}
        if isinstance(raw.get('entries'), list):
            keep['entries'] = [{k: v for k, v in e.items() if k not in NOT_REVIEWED}
                               if isinstance(e, dict) else e for e in raw['entries']]
        return _stringify_allowed(keep, sorted(keep))

    def record_review(self, name: str, status: str = 'approved', *, by: str = '', reviewer: str = '',
                      comment: str = '', locked: bool = False, at: Optional[str] = None) -> Dict[str, Any]:
        """Records an approval (``status='approved'``) or a request for review
        (``'review'``) on a block, stamped as the application stamps it.
        ``locked`` (approvals only) makes the application refuse edits to it."""
        b = self.block(name)
        qa = b.raw.get('qa')
        if not isinstance(qa, dict):
            qa = b.raw['qa'] = {'history': []}
        entry = {
            'status': 'approved' if status == 'approved' else 'review',
            'by': str(by or '').strip(), 'reviewer': str(reviewer or '').strip(),
            'comment': str(comment or '').strip(),
            'at': at or _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
        }
        qa['status'] = entry['status']
        qa['stamp'] = self.review_stamp(b)
        qa['locked'] = entry['status'] == 'approved' and bool(locked)
        qa['history'] = (list(qa.get('history') or []) + [entry])[-50:]
        return qa

    def clear_review(self, name: str) -> None:
        """Forgets a block's review record entirely."""
        self.block(name).raw.pop('qa', None)

    def review_status(self) -> Dict[str, str]:
        """Every block's review state: ``approved``; ``stale`` (changed since it
        was approved); ``review`` (marked so, or reads something that is not
        approved); ``none``."""
        out: Dict[str, str] = {}
        for q, (_collection, raw) in self._idx().items():
            qa = raw.get('qa')
            if not isinstance(qa, dict) or not qa.get('status'):
                out[q] = 'none'
            elif qa['status'] != 'approved':
                out[q] = 'review'
            elif qa.get('stamp') != self.review_stamp(raw):
                out[q] = 'stale'
            else:
                out[q] = 'approved'
        graph = self.references_graph()
        for _ in range(len(out) + 1):
            moved = False
            for q, state in out.items():
                if state != 'approved':
                    continue
                if any(out.get(d, 'approved') != 'approved' for d in graph.get(q, [])):
                    out[q] = 'review'
                    moved = True
            if not moved:
                break
        return out

    # --- size, checks and validation ---------------------------------------------------------------

    def state_count(self) -> int:
        """How many state variables the solver will integrate, as the
        application counts them."""
        n = 0
        for collection in ('compartments', 'running_means'):
            for b in self._raw.get(collection) or []:
                n += self.combination_count(self._effective_dims(b))
        for f in self._raw.get('farfields') or []:
            cells = (int(f.get('n_f', 20)) + int(f.get('n_b', 0) or 0)) * (int(f.get('n_m', 20)) + 1)
            n += cells * self.combination_count(self._effective_dims(f))
        for w in self._raw.get('waste_packages') or []:
            n += 2 * self.combination_count(self._effective_dims(w))
        n += len(self._raw.get('events') or [])
        if (self._raw.get('simulation') or {}).get('mass_balance'):
            m = self.material_dimension()
            n += 6 * ((self.combination_count([m]) if m else 0) + 1)
        return n

    def check(self) -> List[str]:
        """What is wrong with the model that this package can see, in words:
        names, transfer ends, references to nothing, index lists, per-index
        values, settings. Empty when nothing is.

        Not the whole of what the application checks -- unit consistency and
        whether the model builds are its alone: see :meth:`validate`.
        """
        from .check import check_model
        self.settle()
        return check_model(self)

    # --- running ---------------------------------------------------------------

    def _engine_dict(self, simulation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.settle()
        data = copy.deepcopy(self._raw)
        if simulation:
            data['simulation'] = {**(data.get('simulation') or {}), **simulation}
        return data

    def project(self, **simulation: Any) -> Any:
        """The model loaded as the engine loads it (a
        :class:`kompartment.engine.Project`): every block with its defaults
        and dimensions, checked as the application checks a model it opens.
        Keyword arguments override simulation settings for this load only.
        Raises :class:`kompartment.engine.ValidationError` with the
        application's message when the model would be refused."""
        from .engine.project import Project
        return Project(self._engine_dict(simulation))

    def build(self, *, jacobian: bool = True, **simulation: Any) -> Any:
        """The model built into equations (a :class:`kompartment.engine.System`):
        the derivative, the algebraic values, the initial state and the
        Jacobian, for work below the level of a run. Raises
        :class:`kompartment.engine.BuildError` for a model that cannot be."""
        from .engine.builder import build_system
        return build_system(self.project(**simulation), jacobian=jacobian)

    def run(self, *, on_progress: Any = None, workers: Optional[int] = None, compiled: Any = 'auto',
            **simulation: Any) -> Any:
        """Runs the model and returns its :class:`kompartment.engine.Results`.

        Keyword arguments override simulation settings for this run only --
        ``m.run(end_time=1e6, solver='ros23', rtol=1e-8)`` -- without changing
        the model. ``on_progress(fraction, t)`` is called as the run goes.
        ``workers`` caps the processes of a run solved in parts
        (``split='on'``; every core by default). ``compiled`` -- 'auto', True
        or False -- is whether the solve runs compiled with numba (see
        :func:`kompartment.engine.runner.run`): the same answer to the last
        bit, several times sooner on a small model.
        """
        from .engine.runner import run
        return run(self.project(**simulation), on_progress=on_progress, workers=workers, compiled=compiled)

    def values_at_start(self, name: Optional[str] = None, **simulation: Any) -> Any:
        """What the equations work out to at the first instant of a run: for
        one block (``{'kind', 'dims', 'own': [{index, label, unit, value}],
        'fields': {setting: [...]}}``), or an object answering ``of(name)``
        for every block when no name is given."""
        from .engine.atstart import values_at_start
        v = values_at_start(self.project(**simulation))
        return v.of(name) if name is not None else v

    def run_scenarios(self, scenarios: Optional[Sequence[str]] = None, *, workers: int = 1,
                      **simulation: Any) -> Dict[str, Any]:
        """Runs the model once per scenario and returns ``{scenario: Results}``."""
        from .engine.atstart import run_scenarios
        return run_scenarios(self, scenarios, workers=workers, **simulation)

    def run_probabilistic(self, iterations: int = 100, *, seed: int = 1, **opts: Any) -> Any:
        """A probabilistic run over the model's distributions (see
        :func:`kompartment.engine.probabilistic.run_probabilistic`): keep=,
        latin=, varied=, workers=, tornado=, gsa=."""
        from .engine.probabilistic import run_probabilistic
        return run_probabilistic(self.project(), iterations=iterations, seed=seed, **opts)

    def local_sensitivity(self, parameters: Sequence[str], *, most: Optional[int] = None,
                          differenced: bool = False) -> Dict[str, Any]:
        """How every state moves with each parameter named: ``dy/dp`` integrated
        with the model (see :func:`kompartment.engine.localsens.run_sensitivity`).
        ``parameters`` are slot labels, ``'k'`` or ``'Kd[I-129]'``. Returns
        ``{'t', 'y', 'sens', 'chosen', 'states', 'stats'}``."""
        from .engine.localsens import run_sensitivity
        return run_sensitivity(self, parameters, most=most, differenced=differenced)

    def calibrate(self, targets: Sequence[Mapping[str, Any]], variables: Sequence[Mapping[str, Any]], *,
                  method: Optional[str] = None, max_evals: Optional[int] = None, seed: Optional[int] = None,
                  on_progress: Optional[Callable[[Dict[str, Any]], Any]] = None,
                  apply: bool = False) -> Dict[str, Any]:
        """Searches for the parameter values that put endpoints where they are
        asked to be (see :func:`kompartment.engine.calibrate.calibrate`).

        ``targets``: ``{'output': label, 'when': 'end'|'max'|'time'|..., 'time',
        'value', 'scale', 'weight'}``; ``variables``: ``{'key': slot label,
        'lower', 'upper', 'space': 'linear'|'log', 'start'}``; ``method``
        'nelder' (the default), 'lm' or 'de'. ``apply=True`` writes the values
        found into this model, as :meth:`put_values` does. Returns the search's
        result, ``result['values']`` holding each variable's ``was`` and
        ``value`` and ``result['matched']`` whether every target was met.
        """
        from .engine.calibrate import calibrate
        result = calibrate(self, targets=targets, variables=variables, method=method, max_evals=max_evals,
                           seed=seed, on_progress=on_progress)
        if apply:
            self.put_values(result.get('values') or [])
        return result

    def data_rows(self, blocks: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """The model's data as rows, as *Save data* collects them: every
        parameter and lookup table (or those of ``blocks``, by qualified
        name), one row per value -- ``{'id', 'unit', 'time', 'value', 'pdf',
        'note', 'kind', ...}``. See :func:`kompartment.datatable.collect`."""
        from .datatable import collect
        rows = collect(self._raw)
        if blocks is None:
            return rows
        want = set(blocks)

        def name_of(row: Mapping[str, Any]) -> str:
            b = row.get('block')
            if not b:
                return str(row.get('id'))
            return f"{b['system']}.{b['name']}" if b.get('system') else str(b.get('name'))

        return [r for r in rows if name_of(r) in want]

    def export_data(self, path: PathLike, blocks: Optional[Iterable[str]] = None) -> bytes:
        """Writes the model's parameters and lookup tables to a spreadsheet
        (``.xlsx``) or an HDF5 file (``.h5``, ``.hdf5``), as *Save data*
        does; returns the bytes. The file can be edited and read back with
        :meth:`import_data`, here or in the application."""
        from .io.datafile import write_data_hdf5, write_data_workbook
        from .jsonio import slug
        rows = self.data_rows(blocks)
        if not rows:
            raise EditError('This model has no parameters or lookup tables to write out.')
        suffix = Path(path).suffix.lower()
        if suffix == '.xlsx':
            data = write_data_workbook(rows, slug(self._raw.get('name'))[:31] or 'data')
        elif suffix in ('.h5', '.hdf5'):
            data = write_data_hdf5(rows, self._raw.get('name') or 'model')
        else:
            raise EditError(f"'{path}': data is written as .xlsx or .h5")
        Path(path).write_bytes(data)
        return data

    def import_data(self, source: Any, *, create: bool = False) -> Any:
        """Reads values, distributions and lookup tables from a spreadsheet
        or an HDF5 data file into the model, as *Open data* does, and returns
        the report (``values``, ``tables``, ``pdfs``, ``created``,
        ``unmatched``, ``problems``...; ``str(report)`` says it in a
        paragraph). An id nothing in the model matches is reported, or with
        ``create=True`` becomes a new parameter or lookup table. ``source`` is
        a path or the file's bytes (a spreadsheet or HDF5, told by its
        content)."""
        from .datatable import apply
        from .io.datafile import read_data_hdf5, read_data_workbook
        data = source if isinstance(source, (bytes, bytearray, memoryview)) else Path(source).read_bytes()
        got = read_data_hdf5(data) if bytes(data[:8]) == b'\x89HDF\r\n\x1a\n' else read_data_workbook(data)
        report = apply(self._raw, got['rows'], create=create)
        report.problems[:0] = list(got.get('problems') or [])
        self._invalidate()
        self.settle()
        return report

    def put_values(self, values: Iterable[Mapping[str, Any]]) -> int:
        """Writes ``{'key', 'value'}`` pairs into the model, ``key`` a slot
        label as the sampler, the sensitivity and the optimiser spell it
        (``'k'``, ``'Kd[I-129]'``): the block's own value, or its value at the
        index the label names. Returns how many were written; a key naming no
        block, a value that is not a finite number and a value the block
        refuses are passed over (the application's *Update the parameters*)."""
        n = 0
        for v in values:
            value = v.get('value')
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                continue
            m = re.match(r'^([^[]+)((?:\[[^\]]*\])*)$', str(v.get('key') if v.get('key') is not None else ''))
            if not m:
                continue
            block = self.get(m.group(1))
            if block is None:
                continue
            lists = list(block.raw.get('index_lists') or [])
            parts = re.findall(r'\[([^\]]*)\]', m.group(2))
            at = {lists[i]: part for i, part in enumerate(parts) if i < len(lists)}
            try:
                if at:
                    block.set_value(js_text(value), at=at, key='value')
                else:
                    block.set_value(js_text(value), key='value')
            except (KompartmentError, ValueError, KeyError, TypeError):
                continue
            n += 1
        return n

    def validate(self, *, node: str = 'node', timeout: float = 300) -> List[str]:
        """Runs Kompartment's own checks on the model, through Node.js.

        Loads the model as the application does, checks every equation, and
        builds it as a run would. Returns the warnings; raises
        :class:`kompartment.ValidationError` with every error when there are
        any. Needs ``node`` on the path and the Kompartment sources: this
        package's own repository, or the ``src`` directory named by the
        ``KOMPARTMENT_SRC`` environment variable.
        """
        from .check import validate_with_node
        self.settle()
        return validate_with_node(self, node=node, timeout=timeout)


def _stringify_allowed(value: Any, allow: Sequence[str]) -> str:
    """``JSON.stringify(value, allow)``: the property list applies at every depth."""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + _stringify_allowed(value[k], allow)
                              for k in allow if k in value) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(_stringify_allowed(v, allow) for v in value) + ']'
    return 'null'
