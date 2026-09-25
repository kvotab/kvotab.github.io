"""The simulation settings of a model: its ``simulation`` object.

A view over the model's own dictionary: reading a property reads the file's
value (or the default the application uses when the file leaves it out), and
setting one writes it -- checked against the rules Kompartment's loader applies,
so a setting the application would refuse is refused here, when it is made.

Anything without a property of its own is still reachable, as
``sim['max_step']`` or :meth:`Simulation.set`.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterator, List, Optional, Sequence

from .errors import EditError

SOLVERS = (
    'ndf', 'ros23', 'dp45', 'rodas5p', 'radau5', 'fbdf', 'qndf', 'kencarp4', 'trbdf2',
    'scipy_bdf', 'scipy_radau', 'scipy_lsoda',
)
DEFAULT_SOLVER = 'ndf'
SPACINGS = ('log', 'linear', 'series', 'solver', 'both')
SERIES_KINDS = ('log', 'linear', 'times')
TIME_UNITS = {
    'second': 1 / 31557600, 'minute': 60 / 31557600, 'hour': 3600 / 31557600,
    'day': 1 / 365.25, 'year': 1.0,
}
SAMPLINGS = ('latin', 'random')
SPLIT_MODES = ('auto', 'on', 'off')
MAX_OUTPUT_POINTS = 100000

#: What the application uses when a file leaves a setting out.
DEFAULTS: Dict[str, Any] = {
    'start_time': 0,
    'end_time': 1e5,
    'output_points': 250,
    'spacing': 'log',
    'solver': DEFAULT_SOLVER,
    'rtol': 1e-3,
    'abstol': 1e-6,
    'time_unit': 'year',
    'non_negative': True,
    'iterations': 1000,
    'seed': 1,
    'sampling': 'latin',
}

#: The solvers' own settings: kind, and the allowed range or choices.
SOLVER_SETTINGS: Dict[str, Any] = {
    'bdf': ('switch', None),
    'max_step': ('number', (0, math.inf)),
    'initial_step': ('number', (0, math.inf)),
    'max_steps': ('number', (1, math.inf)),
    'max_order': ('number', (1, 5)),
    'min_order': ('number', (1, 5)),
    'norm_control': ('switch', None),
    'error_norm': ('choice', ('rms', 'max')),
    'stagnation_tol': ('number', (0, 1)),
    'newton_kappa': ('number', (0, 1)),
    'max_jac_age': ('number', (1, math.inf)),
    'below_tol_run': ('number', (0, math.inf)),
    'matrix': ('choice', ('auto', 'refactor', 'sparse', 'dense')),
    'jacobian': ('choice', ('analytic', 'numeric')),
    'auto_abstol': ('switch', None),
}

#: Which of those each solver reads (the rest are kept, and ignored by it).
SOLVER_OPTIONS: Dict[str, Sequence[str]] = {
    'ndf': ('bdf', 'max_step', 'initial_step', 'max_steps', 'max_order', 'norm_control',
            'error_norm', 'stagnation_tol', 'below_tol_run', 'matrix', 'jacobian', 'auto_abstol'),
    'ros23': ('max_step', 'initial_step', 'max_steps', 'jacobian'),
    'dp45': ('max_step', 'initial_step', 'max_steps'),
    'rodas5p': ('max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'below_tol_run',
                'error_norm', 'auto_abstol'),
    'radau5': ('max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'max_jac_age',
               'below_tol_run', 'auto_abstol', 'newton_kappa'),
    'fbdf': ('max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'max_jac_age',
             'below_tol_run', 'error_norm', 'auto_abstol', 'newton_kappa', 'max_order', 'min_order'),
    'qndf': ('bdf', 'max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'max_jac_age',
             'below_tol_run', 'error_norm', 'auto_abstol', 'newton_kappa', 'max_order', 'min_order'),
    'kencarp4': ('max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'max_jac_age',
                 'below_tol_run', 'error_norm', 'auto_abstol', 'newton_kappa'),
    'trbdf2': ('max_step', 'initial_step', 'max_steps', 'matrix', 'jacobian', 'max_jac_age',
               'below_tol_run', 'error_norm', 'auto_abstol', 'newton_kappa'),
    'scipy_bdf': (), 'scipy_radau': (), 'scipy_lsoda': (),
}


def _number(key: str, value: Any, least: float = -math.inf, most: float = math.inf,
            above: Optional[float] = None) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise EditError(f"'{value}' is not a number, and {key.replace('_', ' ')} has to be one") from None
    if math.isnan(v) or (math.isinf(v) and most != math.inf):
        raise EditError(f"'{value}' is not a {key.replace('_', ' ')}")
    if above is not None and not v > above:
        raise EditError(f"{key.replace('_', ' ')} must be greater than {above:g} (got {value})")
    if v < least or v > most:
        rng = f'of at least {least:g}' if most == math.inf else f'between {least:g} and {most:g}'
        raise EditError(f"'{value}' is not a {key.replace('_', ' ')}: a number {rng}")
    return int(v) if v.is_integer() and not isinstance(value, float) else v


class OutputSeries:
    """One series of output times, in ``simulation.output_times``.

    ``kind`` is ``'log'``, ``'linear'`` or ``'times'``. A log or linear series
    has ``points`` (at least 2) between ``start`` and ``end`` -- ``None`` for
    either is the simulation's own start or end; a ``times`` series is an
    explicit list of ``times``.
    """

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw

    @property
    def kind(self) -> str:
        if isinstance(self._raw.get('times'), list):
            return 'times'
        k = str(self._raw.get('kind') or self._raw.get('spacing') or 'log')
        return k if k in SERIES_KINDS else 'log'

    @property
    def points(self) -> Optional[int]:
        return self._raw.get('points')

    @points.setter
    def points(self, value: int) -> None:
        n = round(_number('points', value))
        if n < 2:
            raise EditError('A series needs at least 2 points')
        self._raw['points'] = n

    @property
    def start(self) -> Optional[float]:
        """Where the series starts; ``None`` is the simulation's start."""
        return self._raw.get('from')

    @start.setter
    def start(self, value: Optional[float]) -> None:
        self._raw['from'] = None if value is None or value == '' else _number('from', value)

    @property
    def end(self) -> Optional[float]:
        """Where the series ends; ``None`` is the simulation's end."""
        return self._raw.get('to')

    @end.setter
    def end(self, value: Optional[float]) -> None:
        self._raw['to'] = None if value is None or value == '' else _number('to', value)

    @property
    def times(self) -> List[float]:
        return list(self._raw.get('times') or [])

    @times.setter
    def times(self, values: Sequence[float]) -> None:
        self._raw['times'] = sorted(_number('time', v) for v in values)

    def __repr__(self) -> str:
        if self.kind == 'times':
            return f'OutputSeries(times, {len(self.times)} times)'
        return f'OutputSeries({self.kind}, points={self.points}, start={self.start}, end={self.end})'


class Simulation:
    """The settings a model is run with. See the module documentation."""

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw

    # --- generic access -------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return self._raw.get(key, DEFAULTS.get(key))

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)

    def __contains__(self, key: str) -> bool:
        return key in self._raw

    def __iter__(self) -> Iterator[str]:
        return iter(self._raw)

    def get(self, key: str, default: Any = None) -> Any:
        """A setting as the file has it, or ``default``."""
        return self._raw.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Sets any setting by its key, checked where the key is known.

        ``None`` removes a setting, which returns it to the default.
        """
        if value is None:
            self._raw.pop(key, None)
            return
        prop = getattr(type(self), key, None)
        if isinstance(prop, property) and prop.fset is not None:
            prop.fset(self, value)
            return
        if key in SOLVER_SETTINGS:
            self._set_solver_setting(key, value)
            return
        self._raw[key] = value

    def update(self, **settings: Any) -> None:
        """Sets several settings at once: ``sim.update(end_time=1e6, rtol=1e-6)``."""
        for key, value in settings.items():
            self.set(key, value)

    def to_dict(self) -> Dict[str, Any]:
        """The settings as the file will have them."""
        return dict(self._raw)

    def _set_solver_setting(self, key: str, value: Any) -> None:
        kind, allowed = SOLVER_SETTINGS[key]
        if value is None or value == '':
            self._raw.pop(key, None)
            return
        if kind == 'switch':
            self._raw[key] = bool(value)
        elif kind == 'choice':
            if value not in allowed:
                raise EditError(f"'{value}' is not a {key.replace('_', ' ')} ({', '.join(allowed)})")
            self._raw[key] = value
        else:
            least, most = allowed
            self._raw[key] = _number(key, value, least, most)
        if key in ('min_order', 'max_order'):
            lo = self._raw.get('min_order', 1)
            hi = self._raw.get('max_order', 5)
            if lo > hi:
                raise EditError(f'The lowest order ({lo}) is above the highest ({hi})')

    # --- the span and the grid -------------------------------------------------

    @property
    def start_time(self) -> float:
        """When the run starts, in the model's time unit."""
        return self['start_time']

    @start_time.setter
    def start_time(self, value: float) -> None:
        self._raw['start_time'] = _number('start_time', value)

    @property
    def end_time(self) -> float:
        """When the run ends, in the model's time unit. Must be after the start."""
        return self['end_time']

    @end_time.setter
    def end_time(self, value: float) -> None:
        self._raw['end_time'] = _number('end_time', value)

    @property
    def time_unit(self) -> str:
        """``'year'``, ``'day'``, ``'hour'``, ``'minute'`` or ``'second'``."""
        return self['time_unit']

    @time_unit.setter
    def time_unit(self, value: str) -> None:
        if value not in TIME_UNITS:
            raise EditError(f"Unknown time unit '{value}' ({', '.join(TIME_UNITS)})")
        self._raw['time_unit'] = value

    @property
    def output_points(self) -> int:
        """How many output times a ``log`` or ``linear`` grid has (2 to 100000)."""
        return self['output_points']

    @output_points.setter
    def output_points(self, value: int) -> None:
        n = _number('output_points', value, 2, MAX_OUTPUT_POINTS)
        self._raw['output_points'] = int(round(n))

    @property
    def spacing(self) -> str:
        """How the output times are chosen.

        ``'log'`` or ``'linear'``: ``output_points`` over the whole run;
        ``'series'``: the list in :attr:`output_series`; ``'solver'``: the
        solver's own steps; ``'both'``: the series and the steps.
        """
        return self['spacing']

    @spacing.setter
    def spacing(self, value: str) -> None:
        if value not in SPACINGS:
            raise EditError(f"'{value}' is not a way of choosing output times ({', '.join(SPACINGS)})")
        if value in ('series', 'both') and not self._raw.get('output_times'):
            # Seeded from the grid that was in force, as the application does.
            self._raw['output_times'] = [{
                'kind': 'linear' if self._raw.get('spacing') == 'linear' else 'log',
                'points': max(2, round(float(self._raw.get('output_points', 250)))),
                'from': None, 'to': None,
            }]
        self._raw['spacing'] = value

    @property
    def output_series(self) -> List[OutputSeries]:
        """The series in ``output_times``, used with spacing ``series`` or ``both``."""
        return [OutputSeries(s) for s in self._raw.get('output_times') or [] if isinstance(s, dict)]

    def add_output_series(self, kind: str = 'log', points: Optional[int] = None,
                          start: Optional[float] = None, end: Optional[float] = None,
                          times: Optional[Sequence[float]] = None) -> OutputSeries:
        """Adds a series of output times.

        ``kind`` ``'log'`` or ``'linear'`` takes ``points`` between ``start``
        and ``end`` (``None`` for the run's own); ``'times'`` takes ``times``.
        Does not change :attr:`spacing` -- set it to ``'series'`` to use them.
        """
        if kind not in SERIES_KINDS:
            raise EditError(f"'{kind}' is not a kind of series ({', '.join(SERIES_KINDS)})")
        if kind == 'times':
            spec: Dict[str, Any] = {'kind': 'times', 'times': sorted(_number('time', t) for t in times or [])}
        else:
            n = round(_number('points', points if points is not None else (100 if kind == 'log' else 11)))
            if n < 2:
                raise EditError('A series needs at least 2 points')
            spec = {'kind': kind, 'points': n,
                    'from': None if start is None else _number('from', start),
                    'to': None if end is None else _number('to', end)}
        self._raw.setdefault('output_times', []).append(spec)
        return OutputSeries(spec)

    def remove_output_series(self, index: int) -> None:
        """Removes a series by its position; with none left, spacing goes back to ``log``."""
        series = self._raw.get('output_times') or []
        if not 0 <= index < len(series):
            raise EditError(f'No output series {index + 1}')
        del series[index]
        if not series and self._raw.get('spacing') in ('series', 'both'):
            self._raw['spacing'] = 'log'

    # --- the solver ----------------------------------------------------------------

    @property
    def solver(self) -> str:
        """The solver: ``ndf`` (the default), ``ros23``, ``dp45``, ``rodas5p``,
        ``radau5``, ``fbdf``, ``qndf``, ``kencarp4``, ``trbdf2``, or one of the
        SciPy solvers, which need a network connection to run."""
        return self['solver']

    @solver.setter
    def solver(self, value: str) -> None:
        if value not in SOLVERS:
            raise EditError(f"Unknown solver '{value}' ({', '.join(SOLVERS)})")
        self._raw['solver'] = value

    @property
    def rtol(self) -> float:
        """Relative tolerance; greater than zero."""
        return self['rtol']

    @rtol.setter
    def rtol(self, value: float) -> None:
        self._raw['rtol'] = _number('rtol', value, above=0)

    @property
    def abstol(self) -> float:
        """Absolute tolerance; greater than zero. A compartment may set its own."""
        return self['abstol']

    @abstol.setter
    def abstol(self, value: float) -> None:
        self._raw['abstol'] = _number('abstol', value, above=0)

    def solver_settings(self) -> Dict[str, Any]:
        """The solver-specific settings the chosen solver reads, as the file has them."""
        return {k: self._raw[k] for k in SOLVER_OPTIONS.get(self.solver, ()) if k in self._raw}

    @property
    def non_negative(self) -> bool:
        """The master switch over every compartment's *cannot go negative*."""
        v = self._raw.get('non_negative', True)
        return v is not False and v != 'false' and v != 0

    @non_negative.setter
    def non_negative(self, value: bool) -> None:
        self._raw['non_negative'] = bool(value)

    @property
    def mass_balance(self) -> bool:
        """Whether the run carries the mass-balance audit."""
        return self._raw.get('mass_balance') in (True, 'true', 1)

    @mass_balance.setter
    def mass_balance(self, value: bool) -> None:
        self._raw['mass_balance'] = bool(value)

    @property
    def split(self) -> str:
        """Whether a model that falls apart into independent parts is solved a
        part per core: ``'auto'``, ``'on'`` or ``'off'``."""
        return self._raw.get('split', 'auto')

    @split.setter
    def split(self, value: str) -> None:
        if value not in SPLIT_MODES:
            raise EditError(f"'{value}' is not a way of splitting ({', '.join(SPLIT_MODES)})")
        self._raw['split'] = value

    @property
    def decay_ceiling(self) -> Optional[float]:
        """Half-life in years above which an un-modelled daughter is a sink when
        the default decay chains are worked out; ``None`` for no ceiling."""
        return self._raw.get('decay_ceiling')

    @decay_ceiling.setter
    def decay_ceiling(self, value: Optional[float]) -> None:
        if value is None:
            self._raw.pop('decay_ceiling', None)
        else:
            self._raw['decay_ceiling'] = _number('decay_ceiling', value, above=0)

    @property
    def switch_times(self) -> List[Any]:
        """Times the solver is restarted at: numbers, or names of blocks whose
        value is a time."""
        return list(self._raw.get('switch_times') or [])

    @switch_times.setter
    def switch_times(self, values: Sequence[Any]) -> None:
        if values:
            self._raw['switch_times'] = list(values)
        else:
            self._raw.pop('switch_times', None)

    # --- probabilistic runs -----------------------------------------------------

    @property
    def iterations(self) -> int:
        """How many realisations a probabilistic run draws by default."""
        return self['iterations']

    @iterations.setter
    def iterations(self, value: int) -> None:
        n = round(_number('iterations', value))
        if n < 1:
            raise EditError('A probabilistic run needs at least one realisation')
        self._raw['iterations'] = n

    @property
    def seed(self) -> int:
        """The seed a probabilistic run draws from: the same seed, the same run."""
        return self['seed']

    @seed.setter
    def seed(self, value: int) -> None:
        self._raw['seed'] = round(_number('seed', value))

    @property
    def sampling(self) -> str:
        """``'latin'`` (Latin hypercube, the default) or ``'random'``."""
        return self['sampling']

    @sampling.setter
    def sampling(self, value: str) -> None:
        if value not in SAMPLINGS:
            raise EditError(f"'{value}' is not a way of sampling ({', '.join(SAMPLINGS)})")
        self._raw['sampling'] = value

    @property
    def endpoints(self) -> List[str]:
        """The blocks an export offers first: the model's endpoints.

        They decide nothing about the run. A parameter or a lookup table is not
        a result and is not kept by the application as one.
        """
        return list(self._raw.get('endpoints') or [])

    @endpoints.setter
    def endpoints(self, names: Sequence[str]) -> None:
        out: List[str] = []
        for n in names or []:
            s = str(n)
            if s and s not in out:
                out.append(s)
        if out:
            self._raw['endpoints'] = out
        else:
            self._raw.pop('endpoints', None)

    def __repr__(self) -> str:
        return (f'Simulation({self.start_time}..{self.end_time} {self.time_unit}, '
                f'{self.spacing}, solver={self.solver}, rtol={self.rtol}, abstol={self.abstol})')
