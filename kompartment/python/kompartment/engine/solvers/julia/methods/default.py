"""DefaultODEAlgorithm: what DifferentialEquations.jl runs when it is given no
algorithm (OrdinaryDiffEqDefault), and the switching under it -- OrdinaryDiffEqCore's
CompositeAlgorithm, AutoSwitch and their caches (``solvers/default.js``).

It starts on an explicit method and watches every step for stiffness. Six
methods, of which a run uses at most two, one of each kind, both fixed by the
tolerance and the size of the system before it starts:

    non-stiff   Tsit5          reltol >= 1e-6
                Vern7          reltol < 1e-6
    stiff       Rosenbrock23   up to 50 states, reltol >= 1e-6
                Rodas5P        up to 50 states, reltol < 1e-6
                FBDF           51 to 500 states
                KrylovFBDF     over 500 states: FBDF by GMRES

After every attempted step, accepted or not, the explicit method's estimate of
the largest eigenvalue (:func:`.tsit5.explicit_stiffness`), or ||J||_inf
whenever a stiff method has formed J, becomes |lambda| dt / S, S the width of
the non-stiff method's stability region (3.5068 Tsit5, 4.64 Vern7), and the
step counts as stiff above 9/10. Eleven stiff verdicts in a row on the
explicit method switch to the stiff one and double dt; four non-stiff ones in
a row on the stiff method switch back and halve it. While the explicit method
is being found stiff the integrator's error checks are waived
(OrdinaryDiffEq's do_error_check).

Each method keeps its own step controller; the two share the integrator's
Jacobian, W and Newton iteration, which only one of them uses. A method
switched to starts as OrdinaryDiffEq's initialize! starts it: FBDF from order
1 and the Rosenbrock methods as they always start.

A fault in Julia, not reproduced: inside OrdinaryDiffEq's composite the BDF
controller decides acceptance from an error estimate in its own cache that
only ever holds its starting 1, so no FBDF step is ever rejected there. Here
the error test stands, and two things follow from keeping it: no verdict is
counted on an FBDF attempt it rejects, which in Julia never exists, and FBDF's
first step after a switch is predicted by an Euler step rather than from the
last value, whose first estimate is h f and was rejected over and over at
tight tolerances.

And a state that has not moved at all is passed over in the stiffness
estimate instead of making it NaN (``still_is_stiff=True`` gives
OrdinaryDiffEq's reading). The package's README, "The automatic algorithm",
says what else is deliberately different.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from ..controller import PIController
from ..integrator import algorithm, hermite
from .fbdf import FBDF
from .rosenbrock import Rodas5P
from .rosenbrock23 import Rosenbrock23
from .tsit5 import Tsit5
from .vern7 import Vern7

# OrdinaryDiffEqDefault/src/default_alg.jl
LOW_TOL = 1e-6
SMALLSIZE = 50
MEDIUMSIZE = 500
#: DefaultSolverChoice, numbered from 0 here (1 there).
DEFAULT_CHOICES = ('Tsit5', 'Vern7', 'Rosenbrock23', 'Rodas5P', 'FBDF', 'KrylovFBDF')
TSIT5_CHOICE, VERN7_CHOICE, ROSENBROCK23_CHOICE, RODAS5P_CHOICE, FBDF_CHOICE, KRYLOV_FBDF_CHOICE = range(6)
# alg_stability_size of the two non-stiff methods.
STABILITY_SIZES = (3.5068, 4.64)


def _nonstiff_choice(reltol: float) -> int:
    return VERN7_CHOICE if reltol < LOW_TOL else TSIT5_CHOICE


def _stiff_choice(reltol: float, n: int) -> int:
    if n > MEDIUMSIZE:
        return KRYLOV_FBDF_CHOICE
    if n > SMALLSIZE:
        return FBDF_CHOICE
    return RODAS5P_CHOICE if reltol < LOW_TOL else ROSENBROCK23_CHOICE


def _given(options: Dict[str, Any], key: str, default: Any) -> Any:
    """``options.key ?? default``."""
    v = options.get(key)
    return default if v is None else v


class SwitchState:
    """OrdinaryDiffEq's AutoSwitchCache: the verdict counter and the
    thresholds (``switchState``). ``count`` runs positive for consecutive
    stiff verdicts and negative for consecutive non-stiff ones."""

    def __init__(self, o: Dict[str, Any]) -> None:
        self.count = 0
        self.successive_switches = 0
        self.is_stiff_alg = bool(o.get('stiffalgfirst'))
        self.maxstiffstep = _given(o, 'maxstiffstep', 10)
        self.maxnonstiffstep = _given(o, 'maxnonstiffstep', 3)
        self.nonstifftol = _given(o, 'nonstifftol', 9 / 10)
        self.stifftol = _given(o, 'stifftol', 9 / 10)
        self.dtfac = _given(o, 'dtfac', 2)
        self.stiffalgfirst = bool(o.get('stiffalgfirst'))
        self.switch_max = _given(o, 'switch_max', 5)
        self.current = -1           # none chosen yet (0 in Julia, which counts from 1)


def _is_stiff(integ: Any, AS: SwitchState, stability_size: float) -> bool:
    """is_stiff: the verdict on the last attempt, with its side effect on the
    waiver of error checks -- default_alg.jl's version, whose S is always the
    non-stiff method's own for the tolerance in force (``isStiff``)."""
    stiffness = abs(integ.eigen_est * integ.dt / stability_size)
    tol = AS.stifftol if AS.is_stiff_alg else AS.nonstifftol
    # NaN-safe as OrdinaryDiffEq writes it: a NaN estimate counts as stiff.
    stiff = not (stiffness <= tol)
    if not stiff:
        AS.successive_switches += 1
    else:
        AS.successive_switches = 0
    integ.do_error_check = (AS.successive_switches > AS.switch_max or not stiff) or AS.is_stiff_alg
    return stiff


def _count_verdict(AS: SwitchState, stiff: bool) -> None:
    """A verdict into AS.count, Julia's way round (``countVerdict``)."""
    if stiff:
        AS.count = 1 if AS.count < 0 else AS.count + 1
    else:
        AS.count = -1 if AS.count > 0 else AS.count - 1


def default_autoswitch(AS: SwitchState, integ: Any, cache: Any) -> int:
    """default_autoswitch: which of the six takes the next step (``defaultAutoswitch``)."""
    n = integ.n
    reltol = integ.reltol
    if AS.current < 0:
        AS.current = _stiff_choice(reltol, n) if AS.stiffalgfirst else _nonstiff_choice(reltol)
        return AS.current
    dt = integ.dt
    _count_verdict(AS, _is_stiff(integ, AS, STABILITY_SIZES[_nonstiff_choice(reltol)]))
    if not AS.is_stiff_alg and AS.count > AS.maxstiffstep:
        integ.dt = dt * AS.dtfac
        AS.is_stiff_alg = True
        AS.current = _stiff_choice(reltol, n)
    elif AS.is_stiff_alg and AS.count < -AS.maxnonstiffstep:
        integ.dt = dt / AS.dtfac
        AS.is_stiff_alg = False
        AS.current = _nonstiff_choice(reltol)
    return AS.current


def generic_autoswitch(AS: SwitchState, integ: Any, cache: Any) -> int:
    """The generic AutoSwitch of two methods, (nonstiff, stiff) at 0 and 1:
    OrdinaryDiffEqCore's AutoSwitchCache call, used by :func:`AutoAlgSwitch`
    (``genericAutoswitch``)."""
    if AS.current < 0:
        AS.current = 1 if AS.stiffalgfirst else 0
        return AS.current
    dt = integ.dt
    _count_verdict(AS, _is_stiff(integ, AS, cache.stability_size_of(0)))
    if not AS.is_stiff_alg and AS.count > AS.maxstiffstep:
        integ.dt = dt * AS.dtfac
        AS.is_stiff_alg = True
    elif AS.is_stiff_alg and AS.count < -AS.maxnonstiffstep:
        integ.dt = dt / AS.dtfac
        AS.is_stiff_alg = False
    AS.current = 1 if AS.is_stiff_alg else 0
    return AS.current


class CompositeCache:
    """The cache of a composite method (``CompositeCache``): its methods' own
    caches, made the first time each is chosen, as DefaultCache makes them,
    and a controller for each. To the integrator it is one method, whichever
    is in charge."""

    def __init__(self, n: int, integ: Any, opts: Dict[str, Any], algs: Sequence[Any],
                 choose: Callable[[SwitchState, Any, Any], int], options: Dict[str, Any]) -> None:
        self.n = n
        self.opts = opts
        self.algs = list(algs)
        self.choose_fn = choose
        self.state = SwitchState(options)
        self.caches: List[Any] = [None] * len(self.algs)
        self.controllers: List[Optional[PIController]] = [None] * len(self.algs)
        self.current = -1
        self.sub: Any = None
        self.steps_by = [0] * len(self.algs)
        self.attempts_by = [0] * len(self.algs)
        self.switch_log: List[Dict[str, Any]] = []
        self.nswitches = 0
        self.fsal_step = -1
        integ.still_is_stiff = bool(options.get('still_is_stiff'))
        self.skip_next = False
        # (info) -> None after every verdict: for tests and for looking.
        trace = options.get('trace')
        self.trace = trace if callable(trace) else None

    def stability_size_of(self, i: int) -> float:
        s = getattr(self.algs[i], 'stability_size', None)
        if not (s is not None and s > 0):
            raise ValueError(f'{self.algs[i].name} has no stability size to test stiffness against')
        return s

    def ensure(self, i: int, integ: Any) -> Any:
        """Method i's cache and controller, made if it has none yet."""
        if self.caches[i] is None:
            alg = self.algs[i]
            cache = alg.build(self.n, integ, self.opts)
            self.caches[i] = cache
            order = getattr(cache, 'error_order', None)
            self.controllers[i] = PIController(order if order is not None else cache.order, **(alg.controller or {}))
            cache.composite_fresh = True
        return self.caches[i]

    def activate(self, i: int, integ: Any) -> None:
        """Puts method i in charge: its controller becomes the integrator's,
        and it starts as OrdinaryDiffEq's initialize! starts a method switched
        to -- its own init the first time, its restart after that (FBDF's
        history begins again at order 1; the one-step methods have none)."""
        cache = self.ensure(i, integ)
        self.current = i
        self.sub = cache
        integ.controller = self.controllers[i]
        restart = getattr(cache, 'restart', None)
        if cache.composite_fresh:
            cache.composite_fresh = False
            init = getattr(cache, 'init', None)
            if init is not None:
                init(integ)
            if integ.t != integ.prob.tspan[0] and restart is not None:
                restart(integ)
        elif restart is not None:
            restart(integ)

    def init(self, integ: Any) -> None:
        self.activate(self.choose_fn(self.state, integ, self), integ)

    def choose(self, integ: Any) -> None:
        """choose_algorithm!, at the top of every pass of the integrator's loop."""
        dt_before = integ.dt
        # No verdict on an FBDF attempt the error test turned down: inside
        # OrdinaryDiffEq's composite no such attempt exists (its BDF controller
        # never rejects there), so its switch never counts one. Counted, each
        # rejection after a switch was a "not stiff" at a step shrunk tenfold,
        # and four of them sent the run back to Tsit5 before FBDF had taken a
        # step.
        if self.skip_next:
            self.skip_next = False
            return
        nxt = self.choose_fn(self.state, integ, self)
        if self.trace is not None:
            self.trace({'t': integ.t, 'dt': dt_before, 'eigen_est': integ.eigen_est, 'count': self.state.count,
                        'from': self.algs[self.current].name, 'to': self.algs[nxt].name, 'nsteps': integ.nsteps,
                        'njacs': integ._jac_cache.njac if integ._jac_cache is not None else 0, 'eest': integ.eest})
        if nxt == self.current:
            return
        frm = self.current
        self.activate(nxt, integ)
        self.nswitches += 1
        if len(self.switch_log) < 1000:
            self.switch_log.append({'t': integ.t, 'from': self.algs[frm].name, 'to': self.algs[nxt].name})

    # --- the integrator's interface, delegated to the method in charge ------------------------

    @property
    def order(self) -> Any:
        return self.sub.order

    @property
    def explicit(self) -> bool:
        return bool(getattr(self.sub, 'explicit', False))

    @property
    def error_order(self) -> Any:
        return self.sub.error_order

    @property
    def has_fsal_last(self) -> bool:
        return bool(self.sub.has_fsal_last)

    @property
    def refresh_fsal_on_clamp(self) -> bool:
        return bool(getattr(self.sub, 'refresh_fsal_on_clamp', False))

    @property
    def dtpropose(self) -> Any:
        return getattr(self.sub, 'dtpropose', None) if self.sub is not None else None

    @dtpropose.setter
    def dtpropose(self, v: Any) -> None:
        if self.sub is not None:
            self.sub.dtpropose = v

    def step(self, integ: Any) -> bool:
        self.attempts_by[self.current] += 1
        return self.sub.step(integ)

    def accepted(self, integ: Any, dtjust: float) -> None:
        self.steps_by[self.current] += 1
        hook = getattr(self.sub, 'accepted', None)
        if hook is not None:
            hook(integ, dtjust)

    def rejected(self, integ: Any) -> bool:
        # Called for the error test's rejections only: a Newton iteration
        # that failed is still a verdict, as in Julia.
        if getattr(self.sub, 'family', None) == 'fbdf':
            self.skip_next = True
        hook = getattr(self.sub, 'rejected', None)
        return hook(integ) is True if hook is not None else False

    def restart(self, integ: Any) -> None:
        hook = getattr(self.sub, 'restart', None)
        if hook is not None:
            hook(integ)

    def interpolate(self, integ: Any, theta: float) -> np.ndarray:
        interp = getattr(self.sub, 'interpolate', None)
        if interp is not None:
            return interp(integ, theta)
        # A method without an interpolant of its own is read by the cubic
        # Hermite, which needs f at the step's end: taken here, once a step.
        if not self.sub.has_fsal_last and self.fsal_step != integ.nsteps:
            integ.fsallast[:] = integ.f(integ.t + integ.dt, integ.u)
            self.fsal_step = integ.nsteps
        return hermite(theta, integ.dt, integ.uprev, integ.u, integ.fsalfirst, integ.fsallast)

    @property
    def krylov_solves(self) -> int:
        return sum(getattr(c, 'krylov_solves', 0) or 0 for c in self.caches if c is not None)

    def krylov_report(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for c in self.caches:
            report = getattr(c, 'krylov_report', None) if c is not None else None
            if report is not None:
                out.update(report())
        return out

    def report(self, integ: Any = None) -> Dict[str, Any]:
        """What the run did, for its statistics, under the package's names."""
        steps_by = {a.name: self.steps_by[i] for i, a in enumerate(self.algs) if self.caches[i] is not None}
        return {
            'algorithms': [a.name for a in self.algs],
            'stepsBy': steps_by,
            'switches': self.nswitches,
            'switchLog': list(self.switch_log),
            'lastAlg': self.algs[self.current].name,
        }


def composite_algorithm(name: str, algs: Sequence[Any], choose: Callable[[SwitchState, Any, Any], int],
                        options: Optional[Dict[str, Any]] = None) -> Any:
    """A composite method from a list of methods and a choice function, as
    OrdinaryDiffEqCore's CompositeAlgorithm (``compositeAlgorithm``)."""
    o = dict(options or {})
    order = max((a.order or 1) for a in algs)
    return algorithm(name, order, lambda n, integ, opts: CompositeCache(n, integ, opts, algs, choose, o), None,
                     composite=True, algs=list(algs), initdt='sciml')


def DefaultODEAlgorithm(**options: Any) -> Any:
    """DifferentialEquations.jl's automatic choice (``DefaultODEAlgorithm``).

    ``stiffalgfirst`` starts on the stiff side; ``still_is_stiff`` reads a
    state at rest as Julia does; ``maxstiffstep`` (10), ``maxnonstiffstep``
    (3), ``nonstifftol`` and ``stifftol`` (0.9) and ``dtfac`` (2) are
    AutoSwitch's thresholds; ``first_predictor='julia'`` has the two FBDFs
    predict their first step as OrdinaryDiffEq's does; ``stiff`` holds options
    for them, as kwargs... are there."""
    # The stiff methods as OrdinaryDiffEq has them, with one exception: FBDF
    # predicts its first step after a switch by an Euler step, as it does
    # after any restart, not from the last value as OrdinaryDiffEq's does.
    # Inside OrdinaryDiffEq's composite that first step is never rejected
    # however wrong; here the error test is kept, and with OrdinaryDiffEq's
    # predictor diffusion on 600 points at reltol 1e-6 took 26 516 steps and
    # 3147 switches (OrdinaryDiffEq: 87 and one; with this one, 88 and one).
    # And Rodas5P with its PI gains from its order, 5 -- the standalone port's
    # come from its error estimate's, 4, and are kept as they were checked.
    predictor = options.get('first_predictor')
    stiff = {'first_predictor': predictor if predictor is not None else 'euler'}
    stiff.update(options.get('stiff') or {})
    algs = [
        Tsit5(), Vern7(),
        Rosenbrock23(),
        Rodas5P(controller={'beta1': 7 / 50, 'beta2': 2 / 25, 'qmax_first_step': 10000}),
        FBDF(**stiff), FBDF(**{**stiff, 'linsolve': 'gmres'}),
    ]
    return composite_algorithm('DefaultODEAlgorithm', algs, default_autoswitch, options)


def DefaultImplicitODEAlgorithm(**options: Any) -> Any:
    """The same, started on the stiff side and with the stiffness tolerances
    OrdinaryDiffEqDefault gives it (stol = 0, ntol = Inf)."""
    o = dict(options)
    o.update(stiffalgfirst=True, stifftol=_given(options, 'stol', 0), nonstifftol=_given(options, 'ntol', math.inf))
    alg = DefaultODEAlgorithm(**o)
    alg.name = 'DefaultImplicitODEAlgorithm'
    return alg


def AutoAlgSwitch(nonstiff: Any, stiff: Any, **options: Any) -> Any:
    """Two methods and the generic switch between them -- AutoTsit5(Rosenbrock23())
    and its kind. The non-stiff method must know the width of its stability
    region (``stability_size``)."""
    return composite_algorithm(f'AutoSwitch({nonstiff.name}, {stiff.name})', [nonstiff, stiff], generic_autoswitch,
                               options)
