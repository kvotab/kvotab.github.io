"""The blocks a model is made of, one class per kind.

Every block object is a *view* onto the model's own dictionary for that block:
reading a property reads the file's value, setting one writes it. Nothing is
copied, so a block object stays right however the model is changed, and
:meth:`kompartment.Model.save` writes exactly what the objects show.

Properties validate what they are given the way Kompartment does -- an
interpolation it does not know, a failure law it cannot run, an index list the
block cannot carry -- and raise :class:`kompartment.EditError` on the spot.
Anything a property does not cover is still there: ``block['some_key']``
reads and writes the raw value, and :attr:`Block.raw` is the dictionary itself.

Two things are not set through properties, because they reach beyond the block:
its **name** (:meth:`Block.rename` rewrites every equation that reads it) and
its **sub-system** (:meth:`Block.move_to`).

**Equations** are strings -- ``'k * Soil'``, ``'1e10'``. A number given where an
equation is expected is written as the equation of that number.

**Per-index values.** A block indexed by one or more index lists holds one value
per combination of their indices: the block-level value is the default, and
``entries`` override it for particular combinations, the most specific match
winning. An index is given as ``at``: a dict ``{'Radionuclides': 'Cs-137'}``, a
tuple with one index per dimension in order, or -- for a block with one
dimension -- the index name alone::

    soil.set_value('5e9', at='Cs-137')
    kd.set_value(0.03, at={'Radionuclides': 'Cs-137', 'Object': 'Lake'})
    soil.value_at('Cs-137')          # '5e9'
"""

from __future__ import annotations

from typing import (TYPE_CHECKING, Any, ClassVar, Dict, Iterator, List, Mapping, Optional,
                    Sequence, Tuple, Union)

from .distributions import make_pdf, pdf_problems
from .errors import EditError
from .jsonio import js_number
from .names import NAME_RE, qualify

if TYPE_CHECKING:  # pragma: no cover
    from .model import Model

Index = Union[None, str, Sequence[str], Mapping[str, str]]

#: The shapes a block can be drawn as on the diagram.
SHAPES = ('rounded', 'rect', 'ellipse', 'hexagon', 'cylinder', 'diamond')
#: The shape each kind has when it has none of its own.
DEFAULT_SHAPE = {
    'compartment': 'rounded', 'expression': 'rounded', 'parameter': 'hexagon', 'lookup': 'rect',
    'index_reduction': 'rounded', 'block_reduction': 'rounded', 'function': 'rounded',
    'min_max': 'rect', 'running_mean': 'rect', 'snapshot': 'rect', 'delay': 'cylinder',
    'trigger': 'diamond', 'farfield': 'rect', 'waste_package': 'rect', 'event': 'diamond',
    'inflow': 'rounded', 'transfer': 'rounded',
}
#: Default box size per kind, in diagram units.
DEFAULT_SIZE = {
    'compartment': (136, 54), 'farfield': (152, 58), 'waste_package': (152, 58),
    'event': (140, 56), 'expression': (136, 54), 'parameter': (120, 44), 'lookup': (132, 54),
    'index_reduction': (136, 54), 'block_reduction': (136, 54), 'function': (148, 54),
    'min_max': (136, 54), 'running_mean': (136, 54), 'snapshot': (136, 54), 'delay': (128, 54),
    'trigger': (130, 54), 'inflow': (120, 44), 'transfer': (120, 44), 'system': (168, 62),
}
MIN_SIZE = (60, 32)
MAX_SIZE = (520, 320)
LINE_DASHES = ('solid', 'dashed', 'dotted')

INTERPOLATIONS = ('linear', 'extrapolate', 'below', 'above', 'nearest')
OPERATIONS = ('sum', 'product', 'min', 'max', 'mean', 'percentile')
AGGREGATE_OPERATIONS = ('sum', 'product', 'min', 'max', 'mean')
EXTREMES = ('max', 'min')
DIRECTIONS = ('rising', 'falling', 'both')
FAILURES = ('never', 'at', 'uniform', 'exponential', 'weibull')
FAILURE_KEYS = {
    'never': (), 'at': ('fail_at',), 'uniform': ('fail_from', 'fail_to'),
    'exponential': ('fail_start', 'fail_rate'), 'weibull': ('fail_start', 'fail_scale', 'fail_shape'),
}
TIMINGS = ('at', 'poisson')
ACTIONS = ('fail', 'move')
OUTFLOWS = (0, 1, 2, 3, 4)
#: How a far-field path gives its flow-wetted surface, and lays its matrix out.
SURFACES = ('f', 'aw', 'aperture')
GRIDS = ('matched', 'reference')
#: How a far-field path is worked out: on cells, or semi-analytically.
FARF_METHODS = ('discretized', 'semi-analytical')
AVAILABILITY_SCHEMES = ('limit', 'shared_limit', 'langmuir', 'shared_langmuir')
AVAILABILITY_BASES = ('amount', 'moles')
TRANSPORT_OPERATIONS = ('sum', 'mean')
TRANSPORT_ARGUMENTS = ('all', 'point', 'range')

FARF_EQUATION_KEYS = ('tw', 'f', 'aw', 'aperture', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m', 'pe', 'pen_dep',
                      'pen_dep_0')
FARF_NUCLIDE_KEYS = ('kd_f', 'eps_m', 'kd_m', 'de_m')
FARF_STRUCTURE_KEYS = ('n_f', 'n_m', 'o_b', 'n_b')
#: What a new path starts with: the reference implementation's physics, the
#: semi-infinite outlet (4) with its extra cells worked out ('') and matched
#: matrix layers. A saved path that does not mention the last three meant the
#: reference implementation's: see ``FARF_LEGACY`` in :mod:`kompartment.keys`.
FARF_DEFAULTS: Dict[str, Any] = {
    'method': 'discretized',
    'tw': '100', 'surface': 'f', 'f': '1e5', 'kd_f': '0', 'kd_m': '0', 'de_m': '1e-4', 'eps_m': '0.0018',
    'rho_m': '2700', 'pe': '10', 'pen_dep': '12.5', 'pen_dep_0': '', 'n_f': 20, 'n_m': 20,
    'o_b': 4, 'n_b': '', 'grid': 'matched', 'handle_decay': True, 'report_cells': False,
}
#: The optional settings a path may also be given (the other ways of giving
#: its wetted surface).
FARF_OPTIONAL_KEYS = ('aw', 'aperture')


def _count_number(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')


def farfield_extra_cells(block: Dict[str, Any]) -> int:
    """How many cells a path has past its release point (``extraCells``): the
    count it gives, or, left empty, none -- unless its outlet is the rock going
    on (4), which works the count out as the fewest cells that bring
    ((2 NF - Pe)/(2 NF + Pe))**NB under a tenth, a Peclet number that is not a
    number being taken as 10."""
    nb = block.get('n_b')
    if nb is None or (isinstance(nb, str) and not nb.strip()):
        if _count_number(block.get('o_b')) != 4:
            return 0
        n = _count_number(block.get('n_f'))
        p = _count_number(block.get('pe'))
        if not (n == n and n.is_integer()) or n < 1:
            return 0
        if not (p > 0) or p == float('inf'):
            p = 10.0
        rho = (2 * n - p) / (2 * n + p)
        if not (rho > 0):
            return 0
        k, left = 0, 1.0
        while left > 0.1 and k < 10000:
            left *= rho
            k += 1
        return k
    return int(_count_number(nb))


def farfield_cells(block: Dict[str, Any]) -> int:
    """How many cells one nuclide's path has (``cellCount``): one for a path
    worked out semi-analytically (what it holds), none for any other way than
    cells."""
    if block.get('method') == 'semi-analytical':
        return 1
    if block.get('method') not in (None, '', 'discretized'):
        return 0
    nf = int(_count_number(block.get('n_f', 20)))
    nm = int(_count_number(block.get('n_m', 20)))
    return (nf + farfield_extra_cells(block)) * (nm + 1)
WASTE_NUCLIDE_KEYS = ('inventory', 'irf', 'degradation_rate')
WASTE_SINGLE_KEYS = ('fail_at', 'fail_from', 'fail_to', 'fail_start', 'fail_rate', 'fail_scale', 'fail_shape')
WASTE_EQUATION_KEYS = WASTE_NUCLIDE_KEYS + WASTE_SINGLE_KEYS
WASTE_DEFAULTS: Dict[str, Any] = {
    'failure': 'never', 'packages': 1, 'inventory': '0', 'irf': '0', 'degradation_rate': '0',
    'fail_at': '', 'fail_from': '', 'fail_to': '', 'fail_start': '0', 'fail_rate': '',
    'fail_scale': '', 'fail_shape': '1', 'handle_decay': True,
}
EVENT_EQUATION_KEYS = ('at', 'rate', 'from', 'until')
EVENT_DEFAULTS: Dict[str, Any] = {
    'timing': 'at', 'at': '', 'rate': '', 'from': '', 'until': '', 'sampled': True, 'actions': [],
}


def equation_text(value: Any) -> str:
    """An equation as the file stores it: a string, a number written as one."""
    if isinstance(value, bool):
        raise EditError(f'{value!r} is not an equation')
    if isinstance(value, (int, float)):
        return js_number(value)
    if value is None:
        return ''
    return str(value)


def _truthy(value: Any, default: bool) -> bool:
    """A switch as the application reads one from a file."""
    if value is None:
        return default
    if default:
        return value is not False and value != 'false' and value != 0
    return value is True or value == 'true' or value == 1


class Field:
    """A documented property of a block, stored under ``key`` in its dictionary.

    ``kind`` says how a value is read and written: ``'equation'`` (a string;
    numbers are written as equations), ``'text'``, ``'bool'``, ``'int'``,
    ``'count'`` (a whole number, or ``''`` to have it worked out), ``'number'``
    or ``'choice'`` (one of ``choices``). Setting ``None`` removes the key,
    which returns the field to its default.
    """

    def __init__(self, key: str, kind: str = 'equation', default: Any = None,
                 choices: Optional[Sequence[Any]] = None, doc: str = '',
                 entries: bool = False) -> None:
        self.key = key
        self.kind = kind
        self.default = default
        self.choices = tuple(choices) if choices else None
        self.entries = entries
        self.__doc__ = doc
        self.name = key

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, block: Optional['Block'], owner: type) -> Any:
        if block is None:
            return self
        raw = block._raw.get(self.key)
        if self.kind == 'bool':
            return _truthy(raw, bool(self.default))
        return self.default if raw is None and self.key not in block._raw else raw

    def __set__(self, block: 'Block', value: Any) -> None:
        if value is None:
            block._raw.pop(self.key, None)
            return
        block._raw[self.key] = self.coerce(value, block)

    def coerce(self, value: Any, block: Optional['Block'] = None) -> Any:
        """``value`` as this field stores it, or :class:`EditError`."""
        where = f"{block.name}: " if block is not None else ''
        if self.kind == 'equation':
            return equation_text(value)
        if self.kind == 'text':
            return str(value)
        if self.kind == 'bool':
            return bool(value)
        if self.kind == 'count' and (value == '' or (isinstance(value, str) and not value.strip())):
            return ''
        if self.kind in ('int', 'number', 'count'):
            try:
                v = float(value)
            except (TypeError, ValueError):
                raise EditError(f"{where}'{value}' is not a number, and {self.name} has to be one") from None
            if self.kind in ('int', 'count'):
                if not v.is_integer():
                    raise EditError(f'{where}{self.name} has to be a whole number (got {value})')
                return int(v)
            return int(v) if v.is_integer() and isinstance(value, int) else v
        if self.kind == 'choice':
            if value not in (self.choices or ()):
                raise EditError(f"{where}'{value}' is not a {self.name.replace('_', ' ')} "
                                f"({', '.join(map(str, self.choices or ()))})")
            return value
        return value


class Block:
    """One block of a model. See the module documentation.

    Subclasses add the properties of each kind; this class has what every
    block shares: its name and place, its unit, comment and symbol, its
    dimensions and per-index values, its appearance on the diagram, and the
    edits that reach beyond it (rename, move, delete).
    """

    kind: ClassVar[str] = ''
    collection: ClassVar[str] = ''
    #: The key a block's own value is stored under -- what it *is* at an index.
    value_key: ClassVar[str] = ''
    #: Every key a per-index entry of this kind may carry.
    entry_keys: ClassVar[Tuple[str, ...]] = ()
    #: The fields that hold equations, block-level and per entry.
    equation_keys: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, model: 'Model', raw: Dict[str, Any]) -> None:
        self._model = model
        self._raw = raw

    # --- identity -------------------------------------------------------------

    @property
    def model(self) -> 'Model':
        """The model the block belongs to."""
        return self._model

    @property
    def raw(self) -> Dict[str, Any]:
        """The block's own dictionary in the model, live."""
        return self._raw

    @property
    def name(self) -> str:
        """The block's local name. Change it with :meth:`rename`."""
        return self._raw.get('name', '')

    @property
    def system(self) -> str:
        """The sub-system the block lives in; ``''`` is the top level.
        Change it with :meth:`move_to`."""
        return self._raw.get('system') or ''

    @property
    def qualified_name(self) -> str:
        """The name that identifies the block: ``system.name``."""
        return qualify(self.system, self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Block) and other._raw is self._raw

    def __hash__(self) -> int:
        return id(self._raw)

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.qualified_name}>'

    # --- raw access -------------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in ('name', 'system'):
            raise EditError(f"'{key}' is not changed this way: use "
                            f"{'rename()' if key == 'name' else 'move_to()'}, which follows the "
                            'change through every reference.')
        prop = getattr(type(self), key, None)
        if isinstance(prop, (Field, property)) and getattr(prop, 'fset', True) is not None:
            setattr(self, key, value)
        else:
            self._raw[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._raw

    def get(self, key: str, default: Any = None) -> Any:
        """A raw value, or ``default``."""
        return self._raw.get(key, default)

    def keys(self) -> List[str]:
        """The keys the block's dictionary holds."""
        return list(self._raw)

    def to_dict(self) -> Dict[str, Any]:
        """A deep copy of the block's dictionary."""
        import copy
        return copy.deepcopy(self._raw)

    # --- what every block has ------------------------------------------------------

    unit = Field('unit', 'text', '', doc='The unit the block\'s value is in, as text (``Bq``, ``1/year``). '
                 "A transfer's and an inflow's follow from the donor and the time unit, and are "
                 'worked out by :meth:`kompartment.Model.settle`; they need not be set.')
    comment = Field('comment', 'text', '', doc='Free text about the block.')
    symbol = Field('symbol', 'text', None, doc='What the block is shown as instead of its name: text with '
                   '``<sub>``, ``<sup>``, ``<b>`` and ``<i>`` tags, such as ``C<sub>w</sub>``.')

    @property
    def enabled(self) -> bool:
        """Whether the block takes part in the run. A disabled block keeps its
        equations and values and is left out when the model is built."""
        return self._raw.get('enabled') is not False

    @enabled.setter
    def enabled(self, on: bool) -> None:
        if on:
            self._raw.pop('enabled', None)
        else:
            self._raw['enabled'] = False

    @property
    def effectively_enabled(self) -> bool:
        """Whether the block runs, counting the sub-systems around it."""
        return self.enabled and self._model.system_enabled(self.system)

    # --- dimensions and per-index values ---------------------------------------------

    @property
    def index_lists(self) -> List[str]:
        """The index lists the block is indexed by, in order: its dimensions.

        Setting them checks that each list exists and may index this kind of
        block, drops the per-index values keyed by a list it no longer has,
        and brings along what has to follow -- the transfers attached to a
        compartment, the reductions that read the block.
        """
        return list(self._model._effective_dims(self._raw))

    @index_lists.setter
    def index_lists(self, dims: Sequence[str]) -> None:
        self._model.set_dimensions(self, dims)

    @property
    def entries(self) -> List[Dict[str, Any]]:
        """The per-index values, live: each ``{'index': {list: index}, key: value, ...}``."""
        return self._raw.setdefault('entries', [])

    @property
    def value(self) -> Any:
        """The block's own value -- its initial condition, rate, equation or number."""
        return self._raw.get(self.value_key)

    @value.setter
    def value(self, v: Any) -> None:
        self.set_value(v)

    def _check_key(self, key: str) -> None:
        if key not in self.entry_keys:
            raise EditError(f"A {self.kind.replace('_', ' ')} holds no per-index '{key}' "
                            f"(it may hold {', '.join(self.entry_keys) or 'none'})")

    def _coerce_value(self, key: str, value: Any) -> Any:
        prop = getattr(type(self), key, None)
        if isinstance(prop, Field):
            return prop.coerce(value, self)
        if key in self.equation_keys:
            return equation_text(value)
        return value

    def index(self, at: Index) -> Dict[str, str]:
        """``at`` as ``{list: index}``, checked against the block's dimensions."""
        return self._model._index_of(self, at)

    def set_value(self, value: Any, at: Index = None, key: Optional[str] = None) -> None:
        """Sets the block's value, or its value at one index combination.

        ``key`` picks another per-index property than the value itself -- a
        compartment's ``abstol`` or ``dydt``, a parameter's ``pdf`` -- where the
        kind has one (see :attr:`entry_keys`).
        """
        key = key or self.value_key
        if at is None:
            setattr(self, key, value) if isinstance(getattr(type(self), key, None), (Field, property)) \
                else self._raw.__setitem__(key, self._coerce_value(key, value))
            return
        self._check_key(key)
        self._model._set_entry(self, self.index(at), {key: self._coerce_value(key, value)})

    def set_entry(self, at: Index, **values: Any) -> Dict[str, Any]:
        """Sets several per-index properties at one index combination at once:
        ``soil.set_entry('Cs-137', initial='5e9', abstol=1e-3)``."""
        index = self.index(at)
        coerced = {}
        for key, value in values.items():
            self._check_key(key)
            coerced[key] = self._coerce_value(key, value)
        return self._model._set_entry(self, index, coerced)

    def value_at(self, at: Index = None, key: Optional[str] = None) -> Any:
        """The value that applies at an index combination: the most specific
        entry that matches, else the block-level value."""
        key = key or self.value_key
        if at is None:
            return self._raw.get(key)
        index = self.index(at)
        best, score = None, -1
        for e in self._raw.get('entries') or []:
            if key not in e:
                continue
            ix = e.get('index') or {}
            if all(index.get(k) == v for k, v in ix.items()) and len(ix) > score:
                best, score = e[key], len(ix)
        return best if score >= 0 else self._raw.get(key)

    def clear_value(self, at: Index, key: Optional[str] = None) -> None:
        """Removes the value set at one index combination, so the block's own
        applies again. An entry left carrying nothing is removed."""
        key = key or self.value_key
        index = self.index(at)
        entries = self._raw.get('entries') or []
        for e in list(entries):
            if (e.get('index') or {}) == index and key in e:
                del e[key]
                if not [k for k in e if k != 'index']:
                    entries.remove(e)

    def overrides(self, key: Optional[str] = None) -> List[Tuple[Dict[str, str], Any]]:
        """Every ``(index, value)`` set for ``key`` (the value by default)."""
        key = key or self.value_key
        return [(dict(e.get('index') or {}), e[key])
                for e in self._raw.get('entries') or [] if key in e]

    def combinations(self) -> List[Dict[str, str]]:
        """Every index combination the block holds a value at, in the order the
        application lays them out (the last dimension varying fastest)."""
        return self._model.index_combinations(self.index_lists)

    # --- appearance -------------------------------------------------------------------

    @property
    def color(self) -> Optional[str]:
        """The colour the block is drawn in (a CSS colour), or ``None`` for its kind's."""
        return self._raw.get('color')

    @color.setter
    def color(self, value: Optional[str]) -> None:
        if value is None or value == '':
            self._raw.pop('color', None)
        else:
            self._raw['color'] = str(value)

    @property
    def shape(self) -> str:
        """The shape the block is drawn as: one of :data:`SHAPES`."""
        return self._raw.get('shape') or DEFAULT_SHAPE.get(self.kind, 'rounded')

    @shape.setter
    def shape(self, value: Optional[str]) -> None:
        if value is None or value == '':
            self._raw.pop('shape', None)
            return
        if value not in SHAPES:
            raise EditError(f"'{value}' is not a shape ({', '.join(SHAPES)})")
        if value == DEFAULT_SHAPE.get(self.kind):
            self._raw.pop('shape', None)
        else:
            self._raw['shape'] = value

    @property
    def position(self) -> Optional[Tuple[float, float]]:
        """Where the block is drawn, ``(x, y)``, or ``None`` when nothing has
        placed it -- the application then places it when the model is opened."""
        entry = self._model.layout.get(self.qualified_name)
        if not isinstance(entry, dict) or entry.get('x') is None or entry.get('y') is None:
            return None
        return (entry['x'], entry['y'])

    @position.setter
    def position(self, xy: Optional[Tuple[float, float]]) -> None:
        self._model._set_position(self.qualified_name, xy)

    @property
    def size(self) -> Tuple[float, float]:
        """The box's ``(width, height)`` on the diagram."""
        entry = self._model.layout.get(self.qualified_name) or {}
        w, h = DEFAULT_SIZE.get(self.kind, DEFAULT_SIZE['compartment'])
        return (entry.get('w', w), entry.get('h', h))

    @size.setter
    def size(self, wh: Optional[Tuple[float, float]]) -> None:
        self._model._set_size(self.qualified_name, wh)

    # --- review ------------------------------------------------------------------------

    @property
    def review(self) -> Optional[Dict[str, Any]]:
        """The block's review record, when review tracking has one: ``status``
        (``'approved'`` or ``'review'``), ``stamp``, ``locked`` and ``history``."""
        return self._raw.get('qa')

    # --- edits that reach beyond the block ------------------------------------------------

    def rename(self, new_name: str) -> 'Block':
        """Renames the block and every reference to it -- equations, transfer
        ends, reduction targets, per-index values keyed by it, its position."""
        self._model.rename_block(self.qualified_name, new_name)
        return self

    def move_to(self, system: str) -> 'Block':
        """Moves the block into another sub-system (``''`` is the top level),
        numbering its name if it is taken there, and rewrites the references."""
        self._model.move_block(self.qualified_name, system)
        return self

    def delete(self) -> List[str]:
        """Deletes the block; see :meth:`kompartment.Model.delete_block`."""
        return self._model.delete_block(self.qualified_name)

    def references(self) -> List[str]:
        """The qualified names of the blocks that read this one."""
        return self._model.references_to(self.qualified_name)

    def reads(self) -> List[str]:
        """The qualified names of the blocks this one reads."""
        return self._model.reads(self.qualified_name)


# --- the kinds ------------------------------------------------------------------------------

class Compartment(Block):
    """A state variable: an inventory, integrated by the solver.

    Its rate of change is what its transfers bring in and take out, decay and
    ingrowth along the radionuclides (``handle_decay``), and an optional
    explicit term, ``dydt``.
    """

    kind = 'compartment'
    collection = 'compartments'
    value_key = 'initial'
    entry_keys = ('initial', 'abstol', 'non_negative', 'dydt')
    equation_keys = ('initial', 'dydt')

    initial = Field('initial', 'equation', '0', doc='The initial inventory: a number or an equation '
                    'that is constant over the run.')
    dydt = Field('dydt', 'equation', None, doc='An extra term in the rate of change, added to what the '
                 'transfers and decay give; may read the compartment itself. ``None`` for none.')
    abstol = Field('abstol', 'number', None, doc="The compartment's own absolute tolerance (greater "
                   "than zero), or ``None`` for the simulation's.")
    non_negative = Field('non_negative', 'bool', True, doc='Whether the solver may not carry the '
                         'inventory below zero. On by default.')
    handle_decay = Field('handle_decay', 'bool', True, doc='Whether decay and ingrowth act on the '
                         'inventory along its radionuclide dimension. On by default.')

    @property
    def transport_role(self) -> Optional[str]:
        """``'begin'`` or ``'end'`` for the two ends of a transport chain, else ``None``."""
        return self._raw.get('transport')

    def outflows(self) -> List['Transfer']:
        """The transfers out of the compartment."""
        return [t for t in self._model.transfers if t.source == self.qualified_name]

    def inflows(self) -> List[Block]:
        """The transfers and inflows into the compartment."""
        q = self.qualified_name
        return ([t for t in self._model.transfers if t.target == q]
                + [s for s in self._model.inflows if s.target == q])


class _Connection(Block):
    """What transfers and inflows share: a rate, and how the line is drawn."""

    rate = Field('rate', 'equation', '0', doc='The rate: a rate coefficient multiplied by the donor, '
                 'or an absolute flux when ``multiply_by_donor`` is off.')

    @property
    def sum_extra_indices(self) -> bool:
        """Whether a flux indexed by a dimension one of its ends has not got is
        added up there on purpose. Off unless asked for."""
        return _truthy(self._raw.get('sum_extra_indices'), False)

    @sum_extra_indices.setter
    def sum_extra_indices(self, on: bool) -> None:
        if on:
            self._raw['sum_extra_indices'] = True
        else:
            self._raw.pop('sum_extra_indices', None)

    @property
    def line_color(self) -> Optional[str]:
        """The line's own colour, or ``None`` for the theme's."""
        return self._raw.get('color')

    @line_color.setter
    def line_color(self, value: Optional[str]) -> None:
        self.color = value

    @property
    def line_width(self) -> Optional[float]:
        """The line's width in diagram units (0.25 to 12), or ``None`` for the default."""
        return self._raw.get('line_width')

    @line_width.setter
    def line_width(self, value: Optional[float]) -> None:
        if value is None or value == '':
            self._raw.pop('line_width', None)
            return
        try:
            w = float(value)
        except (TypeError, ValueError):
            raise EditError(f"'{value}' is not a line width") from None
        if not w > 0:
            raise EditError(f"'{value}' is not a line width")
        self._raw['line_width'] = min(12.0, max(0.25, w))

    @property
    def dash(self) -> str:
        """``'solid'``, ``'dashed'`` or ``'dotted'``."""
        return self._raw.get('dash') or 'solid'

    @dash.setter
    def dash(self, value: Optional[str]) -> None:
        if value in (None, '', 'solid'):
            self._raw.pop('dash', None)
            return
        if value not in LINE_DASHES:
            raise EditError(f"'{value}' is not a line style ({', '.join(LINE_DASHES)})")
        self._raw['dash'] = value


class Transfer(_Connection):
    """A flux from one compartment to another, or into or out of the model.

    ``source`` and ``target`` are qualified names; ``None`` is outside the
    model. A transfer drawn out of a far-field path or a set of waste packages
    carries its release, and its rate is the block's own name.
    """

    kind = 'transfer'
    collection = 'transfers'
    value_key = 'rate'
    entry_keys = ('rate', 'multiply_by_donor')
    equation_keys = ('rate',)

    multiply_by_donor = Field('multiply_by_donor', 'bool', True, doc='Whether the rate is multiplied by '
                              'the donor\'s inventory (a rate coefficient). Off makes it an absolute flux.')

    @property
    def source(self) -> Optional[str]:
        """The donor, by qualified name; ``None`` for outside the model."""
        return self._raw.get('from')

    @source.setter
    def source(self, name: Optional[str]) -> None:
        self._model.set_connection_end(self.qualified_name, 'from', name)

    @property
    def target(self) -> Optional[str]:
        """The receiver, by qualified name; ``None`` for outside the model."""
        return self._raw.get('to')

    @target.setter
    def target(self, name: Optional[str]) -> None:
        self._model.set_connection_end(self.qualified_name, 'to', name)

    @property
    def is_release(self) -> bool:
        """Whether the transfer carries a far-field path's or waste packages' release."""
        src = self.source
        found = self._model.get(src) if src else None
        return found is not None and found.kind in ('farfield', 'waste_package')

    @property
    def availability(self) -> Optional[Dict[str, Any]]:
        """How much of the donor is available to move, when that is limited: a
        solubility limit or a sorption isotherm. See :meth:`set_availability`."""
        return self._raw.get('availability')

    def set_availability(self, scheme: Optional[str], *, limit: Any = None, top: Any = None,
                         bottom: Any = None, over: Optional[str] = None,
                         basis: Optional[str] = None, unavailable: bool = False) -> None:
        """Limits the flux to what is available of the donor.

        ``scheme``: ``'limit'`` (availability ``min(limit / amount, 1)``),
        ``'langmuir'`` (``(amount + top) / (amount + bottom)``), or their
        ``shared_`` forms, which sum the amount over a group given by ``over``
        (an index list the donor's dimensions reach, such as ``Elements``) --
        ``basis`` ``'moles'`` sums moles rather than the amounts as held.
        ``unavailable`` takes one minus the availability instead: the transfer
        that carries what the other leaves behind. ``None`` removes it.
        """
        if scheme is None:
            self._raw.pop('availability', None)
            return
        if scheme not in AVAILABILITY_SCHEMES:
            raise EditError(f"'{scheme}' is not an availability scheme ({', '.join(AVAILABILITY_SCHEMES)})")
        a: Dict[str, Any] = {'scheme': scheme}
        if scheme in ('limit', 'shared_limit'):
            if limit is None:
                raise EditError('A solubility limit needs its limit')
            a['limit'] = equation_text(limit)
        else:
            if top is None or bottom is None:
                raise EditError('A Langmuir scheme needs top and bottom')
            a['top'] = equation_text(top)
            a['bottom'] = equation_text(bottom)
        if scheme.startswith('shared_'):
            if over:
                a['over'] = over
            if basis is not None:
                if basis not in AVAILABILITY_BASES:
                    raise EditError(f"'{basis}' is not a basis ({', '.join(AVAILABILITY_BASES)})")
                a['basis'] = basis
        if unavailable:
            a['unavailable'] = True
        self._raw['availability'] = a


class Inflow(_Connection):
    """A source term: a flux into a compartment from outside the model."""

    kind = 'inflow'
    collection = 'inflows'
    value_key = 'rate'
    entry_keys = ('rate',)
    equation_keys = ('rate',)

    source = None  # an inflow always comes from outside

    @property
    def target(self) -> Optional[str]:
        """The compartment the inflow feeds, by qualified name."""
        return self._raw.get('to')

    @target.setter
    def target(self, name: str) -> None:
        self._model.set_connection_end(self.qualified_name, 'to', name)


class Parameter(Block):
    """A constant: one number, or one per index -- and, for a probabilistic
    run, the distribution each is drawn from."""

    kind = 'parameter'
    collection = 'parameters'
    value_key = 'value'
    entry_keys = ('value', 'pdf')
    equation_keys = ()

    @property
    def value(self) -> Any:
        """The parameter's number."""
        return self._raw.get('value', 0)

    @value.setter
    def value(self, v: Any) -> None:
        self._raw['value'] = self._coerce_value('value', v)

    def _coerce_value(self, key: str, value: Any) -> Any:
        if key == 'value':
            if isinstance(value, bool):
                raise EditError(f'{self.name}: {value!r} is not a number')
            if isinstance(value, (int, float)):
                return value
            try:
                v = float(value)
            except (TypeError, ValueError):
                raise EditError(f"{self.name}: '{value}' is not a number, and a parameter's value "
                                'is one') from None
            return int(v) if v.is_integer() and 'e' not in str(value).lower() and '.' not in str(value) else v
        if key == 'pdf':
            if value is None:
                return None
            if not isinstance(value, dict) or 'kind' not in value:
                raise EditError(f'{self.name}: a distribution is a dict made by kompartment.distributions')
            problems = pdf_problems(value)
            if problems:
                raise EditError(f"{self.name}: {' '.join(problems)}")
            return value
        return super()._coerce_value(key, value)

    @property
    def distribution(self) -> Optional[Dict[str, Any]]:
        """The distribution the value is drawn from in a probabilistic run, or
        ``None``. Set it to a dict from :mod:`kompartment.distributions`."""
        return self._raw.get('pdf')

    @distribution.setter
    def distribution(self, spec: Optional[Dict[str, Any]]) -> None:
        if spec is None:
            self._raw.pop('pdf', None)
        else:
            self._raw['pdf'] = self._coerce_value('pdf', spec)

    def set_distribution(self, kind: Optional[str], at: Index = None, **params: Any) -> None:
        """Sets the distribution, for the block or for one index combination:
        ``kd.set_distribution('logt', min=1e-4, max=1e-2, mode=1e-3, at='Cs-137')``.

        ``kind`` ``None`` removes it. Truncation (``trmin``, ``trmax``,
        ``pmin``, ``pmax``) and a correlation ``group`` go with the params.
        """
        if kind is None:
            if at is None:
                self._raw.pop('pdf', None)
            else:
                self.clear_value(at, 'pdf')
            return
        spec = make_pdf(kind, **params)
        if at is None:
            self._raw['pdf'] = spec
        else:
            self.set_value(spec, at=at, key='pdf')

    def distribution_at(self, at: Index = None) -> Optional[Dict[str, Any]]:
        """The distribution that applies at an index combination."""
        return self.value_at(at, 'pdf')


class Expression(Block):
    """An algebraic quantity, worked out from the state at every step."""

    kind = 'expression'
    collection = 'expressions'
    value_key = 'equation'
    entry_keys = ('equation',)
    equation_keys = ('equation',)

    equation = Field('equation', 'equation', '0', doc='The equation.')

    @property
    def transport_role(self) -> Optional[str]:
        """``'number'``, ``'counter'`` or ``'operation'`` for the parts of a
        transport sub-system, else ``None``."""
        return self._raw.get('transport')

    operation = Field('operation', 'choice', None, TRANSPORT_OPERATIONS,
                      doc="A transport operation's ``'sum'`` or ``'mean'`` over its chain.")
    argument = Field('argument', 'choice', None, TRANSPORT_ARGUMENTS,
                     doc="How a transport operation is read: ``'all'`` (a value), ``'point'`` "
                         '(called with a position along the chain) or ``range`` (with two).')


class Lookup(Block):
    """A value that follows a series of points -- at the simulation clock, or
    at whatever it is called with when it declares an ``argument``."""

    kind = 'lookup'
    collection = 'lookups'
    value_key = 'points'
    entry_keys = ('points',)
    equation_keys = ()

    interpolation = Field('interpolation', 'choice', 'linear', INTERPOLATIONS,
                          doc="How it is read between and beyond the points: ``'linear'`` (end "
                              "values held), ``'extrapolate'``, ``'below'``, ``'above'``, ``'nearest'``.")
    cyclic = Field('cyclic', 'bool', False, doc='Whether the table repeats over its span.')

    @property
    def argument(self) -> Optional[str]:
        """The name of the table's argument, when it is called as ``Table(x)``
        rather than read at the clock; ``None`` otherwise."""
        return self._raw.get('argument')

    @argument.setter
    def argument(self, name: Optional[str]) -> None:
        if name in (None, ''):
            self._raw.pop('argument', None)
            return
        if not NAME_RE.fullmatch(str(name)):
            raise EditError(f"'{name}' is not a valid argument name")
        self._raw['argument'] = str(name)

    @property
    def points(self) -> List[List[Any]]:
        """The points, ``[[x, y], ...]``; a point may carry a distribution as a
        third element, ``[x, y, pdf]``."""
        return self._raw.setdefault('points', [])

    @points.setter
    def points(self, pts: Sequence[Sequence[Any]]) -> None:
        self._raw['points'] = _points(pts, self.name)

    def _coerce_value(self, key: str, value: Any) -> Any:
        if key == 'points':
            return _points(value, self.name)
        return super()._coerce_value(key, value)

    def set_point_distribution(self, i: int, kind: Optional[str], **params: Any) -> None:
        """Gives point ``i`` a distribution (``None`` removes it)."""
        pts = self.points
        if not 0 <= i < len(pts):
            raise EditError(f'{self.name} has no point {i}')
        x, y = pts[i][0], pts[i][1]
        pts[i] = [x, y] if kind is None else [x, y, make_pdf(kind, **params)]


def _points(pts: Any, name: str) -> List[List[Any]]:
    out = []
    for i, p in enumerate(pts or []):
        if isinstance(p, dict):
            p = [p.get('x'), p.get('y')] + ([p['pdf']] if p.get('pdf') else [])
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            raise EditError(f'{name}: lookup point {i + 1} is {p!r}; both parts must be numbers') from None
        x = int(x) if x.is_integer() and isinstance(p[0], int) else x
        y = int(y) if y.is_integer() and isinstance(p[1], int) else y
        out.append([x, y] + ([p[2]] if len(p) > 2 and p[2] else []))
    return out


class IndexReduction(Block):
    """One block reduced along one of its index lists: a sum over the
    nuclides, a maximum over the objects. Its dimensions are its target's less
    the one it reduces over, and follow the target."""

    kind = 'index_reduction'
    collection = 'index_reductions'
    value_key = 'target'
    entry_keys = ('target',)
    equation_keys = ()

    operation = Field('operation', 'choice', 'sum', OPERATIONS,
                      doc="``'sum'``, ``'product'``, ``'min'``, ``'max'``, ``'mean'`` or "
                          "``'percentile'`` (with :attr:`percentile`).")
    percentile = Field('percentile', 'number', None, doc='For ``operation`` ``percentile``: '
                       'which, from 0 to 100.')

    @property
    def target(self) -> Optional[str]:
        """The block it reduces, by name as written from its sub-system."""
        return self._raw.get('target')

    @target.setter
    def target(self, name: Optional[str]) -> None:
        self._model.set_reduction_target(self.qualified_name, name)

    @property
    def over(self) -> Optional[str]:
        """The index list it reduces over: the one its target has and it has not."""
        return self._model._reduced_list(self)

    def reduce_over(self, list_name: str) -> None:
        """Reduces over another of the target's index lists."""
        self._model.set_reduction_target(self.qualified_name, self.target, over=list_name)


class BlockReduction(Block):
    """Several blocks combined element-wise at each index: their sum, product,
    minimum, maximum or mean. Indexed by the union of their dimensions."""

    kind = 'block_reduction'
    collection = 'block_reductions'
    value_key = 'targets'
    entry_keys = ('targets',)
    equation_keys = ()

    operation = Field('operation', 'choice', 'sum', AGGREGATE_OPERATIONS,
                      doc="``'sum'``, ``'product'``, ``'min'``, ``'max'`` or ``'mean'``.")

    @property
    def targets(self) -> List[str]:
        """The blocks it combines, by name as written from its sub-system."""
        return list(self._raw.get('targets') or [])

    @targets.setter
    def targets(self, names: Sequence[str]) -> None:
        self._model.set_aggregate_targets(self.qualified_name, names)


class Function(Block):
    """Arithmetic written once and called from any equation: ``Dose(x, k)``.
    ``parameters`` names the values passed in; ``equation`` is the body."""

    kind = 'function'
    collection = 'functions'
    value_key = 'equation'
    entry_keys = ()
    equation_keys = ('equation',)

    equation = Field('equation', 'equation', '', doc='The body, in terms of its parameters and the model.')

    @property
    def parameters(self) -> List[str]:
        """The names the body calls the values passed in, in order."""
        return list(self._raw.get('parameters') or [])

    @parameters.setter
    def parameters(self, names: Sequence[str]) -> None:
        self._model.set_function_parameters(self.qualified_name, names)

    @property
    def index_lists(self) -> List[str]:
        """A function is not indexed: it is worked out at its caller's index."""
        return []

    @index_lists.setter
    def index_lists(self, dims: Sequence[str]) -> None:
        if dims:
            raise EditError('A function is not indexed: it is worked out at the index it is called at')


class _Recorder(Block):
    """What the blocks that remember share."""

    target = Field('target', 'equation', '0', doc='The equation it watches.')


class MinMax(_Recorder):
    """The largest or smallest value its target has taken."""

    kind = 'min_max'
    collection = 'min_maxes'
    value_key = 'target'
    entry_keys = ('target', 'reset_trigger', 'start_trigger', 'stop_trigger')
    equation_keys = ('target',)

    operation = Field('operation', 'choice', 'max', EXTREMES, doc="``'max'`` or ``'min'``.")
    reset_trigger = Field('reset_trigger', 'text', None, doc='A trigger that starts it again.')
    start_trigger = Field('start_trigger', 'text', None, doc='A trigger that starts it recording.')
    stop_trigger = Field('stop_trigger', 'text', None, doc='A trigger that stops it recording.')


class RunningMean(_Recorder):
    """The mean of its target over the time it has been recording."""

    kind = 'running_mean'
    collection = 'running_means'
    value_key = 'target'
    entry_keys = ('target', 'reset_trigger', 'start_trigger', 'stop_trigger')
    equation_keys = ('target',)

    reset_trigger = Field('reset_trigger', 'text', None, doc='A trigger that starts it again.')
    start_trigger = Field('start_trigger', 'text', None, doc='A trigger that starts it recording.')
    stop_trigger = Field('stop_trigger', 'text', None, doc='A trigger that stops it recording.')


class Snapshot(_Recorder):
    """Its target as it was when a trigger last fired; ``initial`` until then."""

    kind = 'snapshot'
    collection = 'snapshots'
    value_key = 'target'
    entry_keys = ('target', 'trigger', 'initial')
    equation_keys = ('target', 'initial')

    trigger = Field('trigger', 'text', None, doc='The trigger that takes the snapshot.')
    initial = Field('initial', 'equation', '0', doc='Its value before the trigger first fires.')


class Delay(_Recorder):
    """Its target as it was ``delay`` ago."""

    kind = 'delay'
    collection = 'delays'
    value_key = 'target'
    entry_keys = ('target', 'delay')
    equation_keys = ('target', 'delay')

    delay = Field('delay', 'equation', '0', doc='How long ago, in the model\'s time unit.')


class Trigger(Block):
    """The instant ``first`` crosses ``second``. The solver stops there."""

    kind = 'trigger'
    collection = 'triggers'
    value_key = 'first'
    entry_keys = ('first', 'second', 'direction')
    equation_keys = ('first', 'second')

    first = Field('first', 'equation', '0', doc='The equation that crosses.')
    second = Field('second', 'equation', '0', doc='What it crosses.')
    direction = Field('direction', 'choice', 'rising', DIRECTIONS,
                      doc="``'rising'``, ``'falling'`` or ``'both'``.")


class Farfield(Block):
    """A far-field pathway (FARFCOMP): a dual-porosity transport model behind
    one block -- advection and dispersion along a fracture, diffusion into the
    rock matrix, sorption, decay and ingrowth -- with hundreds of states.

    Its own value is the release out of the far end; a transfer drawn out of
    it carries the release on (:meth:`set_release`).
    """

    kind = 'farfield'
    collection = 'farfields'
    value_key = 'kd_f'
    entry_keys = FARF_EQUATION_KEYS
    equation_keys = FARF_EQUATION_KEYS

    method = Field('method', 'choice', 'discretized', FARF_METHODS,
                   doc="How the path is worked out: ``'discretized'``, on cells with the rest of the model, or "
                       "``'semi-analytical'``, exactly from its transfer function -- one state per nuclide for "
                       'what it holds, its settings constant through a run, the rock going on past the release '
                       'point.')
    tw = Field('tw', 'equation', '100', doc='T_w: water travel time along the path.')
    surface = Field('surface', 'choice', 'f', SURFACES,
                    doc="How the flow-wetted surface is given: ``'f'`` (F), ``'aw'`` (a_w) or ``'aperture'``.")
    f = Field('f', 'equation', '1e5', doc='F: flow-related transport resistance, [time]·m²/m³ (surface f).')
    aw = Field('aw', 'equation', '1000', doc='a_w: flow-wetted surface per unit volume of water, m²/m³ (surface aw).')
    aperture = Field('aperture', 'equation', '0.002',
                     doc='δ: the fracture aperture, m; a_w = 2/δ (surface aperture).')
    kd_f = Field('kd_f', 'equation', '0', doc='K_d,f: sorption on the fracture coating, m³/m² (per nuclide).')
    kd_m = Field('kd_m', 'equation', '0', doc='K_d,m: partition coefficient in the rock matrix, m³/kg (per nuclide).')
    de_m = Field('de_m', 'equation', '1e-4', doc='D_e,m: effective diffusivity in the matrix, m²/[time] (per nuclide).')
    eps_m = Field('eps_m', 'equation', '0.0018', doc='ε_m: porosity of the rock matrix (per nuclide).')
    rho_m = Field('rho_m', 'equation', '2700', doc='ρ_m: dry bulk density of the rock matrix, kg/m³.')
    pe = Field('pe', 'equation', '10', doc='P_e: Peclet number; the dispersion is the travel time over it.')
    pen_dep = Field('pen_dep', 'equation', '12.5', doc='PENDEP: the greatest depth into the matrix modelled, m.')
    pen_dep_0 = Field('pen_dep_0', 'equation', '', doc="PENDEP0: the first matrix layer's thickness, m; "
                      "'' for automatic.")
    n_f = Field('n_f', 'int', 20, doc='NF: cells along the fracture (at least 1).')
    n_m = Field('n_m', 'int', 20, doc='NM: layers into the matrix (at least 2).')
    o_b = Field('o_b', 'choice', 1, OUTFLOWS, doc='OB: the water downstream: 4 the rock goes on (semi-infinite, '
                'as in FARF31; new paths), 0 infinite dilution, 1 as the last cell, 2 linear, 3 quadratic '
                'extrapolation.')
    n_b = Field('n_b', 'count', 0, doc="NB: extra cells past the point the release is measured at; '' to have "
                'them worked out (the semi-infinite outlet needs some).')
    grid = Field('grid', 'choice', 'reference', GRIDS,
                 doc="How the matrix layers are laid out: ``'matched'`` to diffusion into the rock (new paths), or "
                     "``'reference'``, as in SKB's reference implementation.")
    handle_decay = Field('handle_decay', 'bool', True, doc='Decay and ingrowth in every cell.')
    report_cells = Field('report_cells', 'bool', False, doc='Report every cell, not only the total.')

    def set_release(self, to: Optional[str]) -> Optional['Transfer']:
        """Sends the release to a compartment (``None``: nowhere, only read)."""
        return self._model.set_release(self.qualified_name, to)

    @property
    def release(self) -> Optional['Transfer']:
        """The transfer carrying the release, if it goes anywhere."""
        return next((t for t in self._model.transfers if t.source == self.qualified_name), None)


class WastePackage(Block):
    """Waste packages: an inventory inside containers that fail, then release
    it -- an instant fraction at failure and the rest as the waste form
    degrades. Two inventories per index (intact and exposed); the release
    leaves through a transfer drawn out of the block (:meth:`set_release`)."""

    kind = 'waste_package'
    collection = 'waste_packages'
    value_key = 'inventory'
    entry_keys = WASTE_EQUATION_KEYS
    equation_keys = WASTE_EQUATION_KEYS

    failure = Field('failure', 'choice', 'never', FAILURES,
                    doc="How the packages fail: ``'never'``, ``'at'`` (``fail_at``), ``'uniform'`` "
                        "(``fail_from`` to ``fail_to``), ``'exponential'`` (``fail_start``, "
                        "``fail_rate``) or ``'weibull'`` (``fail_start``, ``fail_scale``, ``fail_shape``).")
    packages = Field('packages', 'int', 1, doc='How many packages: a count for the reader.')
    inventory = Field('inventory', 'equation', '0', doc='What they hold at the start, in total (per index).')
    irf = Field('irf', 'equation', '0', doc='The instant-release fraction, 0 to 1 (per index).')
    degradation_rate = Field('degradation_rate', 'equation', '0',
                             doc='The fraction of the exposed waste form dissolving per unit time (per index).')
    fail_at = Field('fail_at', 'equation', '', doc="For ``'at'``: when every package fails.")
    fail_from = Field('fail_from', 'equation', '', doc="For ``'uniform'``: the start of the window.")
    fail_to = Field('fail_to', 'equation', '', doc="For ``'uniform'``: the end of the window.")
    fail_start = Field('fail_start', 'equation', '0', doc="For ``'exponential'`` and ``'weibull'``: "
                       'when failures may begin.')
    fail_rate = Field('fail_rate', 'equation', '', doc="For ``'exponential'``: failures per unit time.")
    fail_scale = Field('fail_scale', 'equation', '', doc="For ``'weibull'``: the scale.")
    fail_shape = Field('fail_shape', 'equation', '1', doc="For ``'weibull'``: the shape.")
    handle_decay = Field('handle_decay', 'bool', True, doc='Decay and ingrowth in both inventories.')

    def set_failure(self, failure: str, **settings: Any) -> None:
        """Sets how the packages fail, with the settings that law reads:
        ``pkgs.set_failure('weibull', fail_start=1000, fail_scale=1e5, fail_shape=2)``."""
        if failure not in FAILURES:
            raise EditError(f"'{failure}' is not a way of failing ({', '.join(FAILURES)})")
        unknown = [k for k in settings if k not in WASTE_SINGLE_KEYS]
        if unknown:
            raise EditError(f"A failure law has no {', '.join(map(repr, unknown))}")
        self.failure = failure
        for k, v in settings.items():
            setattr(self, k, v)
        missing = [k for k in FAILURE_KEYS[failure] if str(self._raw.get(k, WASTE_DEFAULTS[k])).strip() == '']
        if missing:
            raise EditError(f"'{failure}' needs {', '.join(missing)}")

    def set_release(self, to: Optional[str]) -> Optional['Transfer']:
        """Sends the release to a compartment (``None``: nowhere, only read)."""
        return self._model.set_release(self.qualified_name, to)

    @property
    def release(self) -> Optional['Transfer']:
        """The transfer carrying the release, if it goes anywhere."""
        return next((t for t in self._model.transfers if t.source == self.qualified_name), None)


class Event(Block):
    """A disruptive event: something that happens at an instant -- once, at a
    time, or at random as a Poisson process -- and does something: fails a
    share of a set of waste packages, or moves a share of one compartment's
    inventory to another (or out of the model). Its value is its count."""

    kind = 'event'
    collection = 'events'
    value_key = 'at'
    entry_keys = ()
    equation_keys = EVENT_EQUATION_KEYS

    timing = Field('timing', 'choice', 'at', TIMINGS,
                   doc="``'at'`` (once, at :attr:`at`) or ``'poisson'`` (at :attr:`rate` "
                       'between :attr:`start` and :attr:`until`).')
    at = Field('at', 'equation', '', doc="For ``'at'``: when it happens.")
    rate = Field('rate', 'equation', '', doc="For ``'poisson'``: occurrences per unit time.")
    start = Field('from', 'equation', '', doc="For ``'poisson'``: when it may begin; '' is the run's start.")
    until = Field('until', 'equation', '', doc="For ``'poisson'``: when it stops; '' is the run's end.")
    sampled = Field('sampled', 'bool', True, doc='Whether a probabilistic run draws the occurrences '
                    '(otherwise the expected-value form is kept).')

    @property
    def index_lists(self) -> List[str]:
        """An event is not indexed: it acts on whole blocks."""
        return []

    @index_lists.setter
    def index_lists(self, dims: Sequence[str]) -> None:
        if dims:
            raise EditError('An event is not indexed: it acts on whole blocks')

    @property
    def actions(self) -> List[Dict[str, Any]]:
        """What it does, live: ``{'kind': 'fail', 'block', 'fraction'}`` or
        ``{'kind': 'move', 'from', 'to', 'fraction'}``."""
        return self._raw.setdefault('actions', [])

    def add_fail_action(self, packages: str, fraction: Any = '1') -> Dict[str, Any]:
        """Fails ``fraction`` of the intact packages of a waste-package block."""
        found = self._model.get(packages)
        if found is None or found.kind != 'waste_package':
            raise EditError(f"'{packages}' is not a set of waste packages")
        a = {'kind': 'fail', 'fraction': equation_text(fraction), 'block': found.qualified_name}
        self.actions.append(a)
        return a

    def add_move_action(self, source: str, target: Optional[str] = None,
                        fraction: Any = '1') -> Dict[str, Any]:
        """Moves ``fraction`` of ``source``'s inventory to ``target`` (``None``:
        out of the model)."""
        found = self._model.get(source)
        if found is None or found.kind != 'compartment':
            raise EditError(f"'{source}' is not a compartment")
        to = None
        if target is not None:
            t = self._model.get(target)
            if t is None or t.kind != 'compartment':
                raise EditError(f"'{target}' is not a compartment")
            if t == found:
                raise EditError('An event cannot move an inventory onto itself')
            to = t.qualified_name
        a = {'kind': 'move', 'fraction': equation_text(fraction), 'from': found.qualified_name, 'to': to}
        self.actions.append(a)
        return a

    def clear_actions(self) -> None:
        """Removes every action."""
        self._raw['actions'] = []


#: Every kind, by its name in the file.
KINDS: Dict[str, type] = {
    cls.kind: cls for cls in (
        Compartment, Transfer, Inflow, Parameter, Expression, Lookup, IndexReduction,
        BlockReduction, Function, MinMax, RunningMean, Snapshot, Delay, Trigger, Farfield,
        WastePackage, Event,
    )
}
#: Collection name -> kind.
SINGULAR: Dict[str, str] = {cls.collection: kind for kind, cls in KINDS.items()}


def view(model: 'Model', collection: str, raw: Dict[str, Any]) -> Block:
    """The block object for a raw block of ``collection``."""
    return KINDS[SINGULAR[collection]](model, raw)


def iter_kinds() -> Iterator[Tuple[str, type]]:
    return iter(KINDS.items())
