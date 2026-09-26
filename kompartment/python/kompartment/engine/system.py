"""A built model, ready to run: the derivative, the algebraic values and the hooks.

What ``buildSystem`` returns in the application, as an object. The equations
are compiled into four Python functions over numpy -- the slots that never
change (worked out once), those that change with the clock alone (once per
instant), those that read the state (on every call), and the assembly of the
derivative -- plus the initial state and the jumps.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from .builder import Entry, Stmt, _Builder, merge_statements, write_statements
from .codegen import read_tables


class Layout:
    """Where everything is: the application's ``layout``, as attributes."""

    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    def __getitem__(self, key: str) -> Any:
        return self.__dict__[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.__dict__.get(key, default)


class Events:
    """The discrete events the solver must stop at: their functions and what
    firing one does."""

    def __init__(self, system: 'System', slots: List[Dict[str, Any]], direction: np.ndarray,
                 handlers: Dict[int, List[Dict[str, Any]]]) -> None:
        self.system = system
        self.n = len(slots)
        self.slots = slots
        self.direction = direction
        self._idx = np.array([s['slot'] for s in slots], dtype=np.int64)
        self.handlers = handlers

    def fun(self, t: float, y: np.ndarray, out: Optional[np.ndarray] = None) -> np.ndarray:
        values = self.system.evaluate_algebraic(t, y)
        v = values[self._idx]
        if out is not None:
            out[:] = v
            return out
        return v.copy()

    def fire(self, which: Sequence[int], t: float, y: np.ndarray) -> None:
        values = self.system.evaluate_algebraic(t, y)
        mem = self.system.MEM
        for i in which:
            for h in self.handlers.get(i, []):
                rec = h['rec']
                off = h['off']
                summed = float(y[rec.state.base + off]) if rec.state is not None else 0.0
                mem[rec.mem + off].fire(h['action'], t, float(values[rec.aux['target'].base + off]), summed)


class Jump:
    """A jump in the state at a time: packages failing at once, an event."""

    def __init__(self, name: str, apply: Callable[[np.ndarray], None], slot: Optional[int] = None,
                 text: str = '', times: Optional[Callable[[], List[float]]] = None) -> None:
        self.name = name
        self.apply = apply
        self.slot = slot
        self.text = text
        self.times = times


class System:
    """A model built into equations (see :func:`kompartment.engine.builder.build_system`)."""

    def __init__(self, b: _Builder, jacobian: bool = True) -> None:
        project = b.project
        self.project = project
        self.builder = b
        self.nstate = b.nstate
        self.nalg = b.nalg
        self.nparam = b.nparam
        self.P = b.P
        self.X = np.zeros(max(1, b.nalg))
        self.TAB = b.TAB
        self.MEM = b.MEM
        self.FARF = b.FARF
        self.DEC = b.DEC
        self.start_time = float(project.simulation['start_time'])
        self.end_time = float(project.simulation['end_time'])
        self.DIS = np.ones(max(1, len(b.disruption_layout)))
        self.decay = b.decay
        w = b.writer
        ns = w.ns
        ns.update(P=self.P, TAB=self.TAB, MEM=self.MEM, FARF=self.FARF, DIS=self.DIS, T0=np.float64(self.start_time),
                  T1=np.float64(self.end_time), _tabs=read_tables, _f64=np.float64, float=float, np=np)
        self._ns = ns
        self.source: Dict[str, str] = {}
        self._once = self._compile('invariant', merge_statements(b.pass_stmts[0]))
        self._clock = self._compile('at_instant', merge_statements(b.pass_stmts[1]))
        self._step = self._compile('moving', merge_statements(b.pass_stmts[2]))
        self._invariant_version = 0
        self._clock_at = math.nan
        from .assembly import Assembler
        self._assemble = Assembler(self)
        self._initial = self._compile_initial()
        self.slot_class = b.slot_class
        self.clock_idx = np.nonzero(b.slot_class[:b.nalg] == 1)[0].astype(np.int64)
        self._lo_x = np.zeros(self.clock_idx.size)
        self._hi_x = np.zeros(self.clock_idx.size)
        self._min_change = 0.0
        self._origin = self.start_time
        self._lo_t = math.nan
        self._hi_t = math.nan
        self._clock_at = math.nan
        self.jumps = self._compile_jumps()
        self.remembering = [r for r in b.recorders if r.mem >= 0]
        self.recorders = b.recorders
        # The far-field paths worked out semi-analytically: they keep the
        # history of what flowed into them, as the recorders keep theirs.
        self.laplace = [F for F in self.FARF if getattr(F, 'method', '') == 'semi-analytical']
        self.events = Events(self, b.event_slots, b.event_direction, b.event_handlers) if b.event_slots else None
        self.layout = self._layout()
        self.evaluate_invariant()
        if self.laplace:
            b.semi_refusals(self.X)
        self.jacobian: Dict[str, Any]
        if not jacobian:
            self.jacobian = {'available': False, 'reason': 'not asked for'}
        elif not self.nstate:
            self.jacobian = {'available': False, 'reason': 'the model has no compartments to differentiate'}
        else:
            from .jacobian import build_jacobian
            self.jacobian = build_jacobian(self)

    # --- compiling ------------------------------------------------------------------------

    def _exec(self, name: str, src: str) -> Callable[..., Any]:
        code = compile(src, f'<kompartment {name}>', 'exec')
        exec(code, self._ns)  # noqa: S102 - generated from the model by this package
        return self._ns[f'_{name}']

    def _compile(self, name: str, stmts: List[Stmt]) -> Callable[..., Any]:
        lines = write_statements(self.builder.writer, stmts)
        src = '\n'.join([f'def _{name}(t, y, X):', '    T = _f64(t)', *lines, '    return X', ''])
        self.source[name] = src
        return self._exec(name, src)

    def _compile_assembly(self) -> Callable[..., Any]:
        b, w = self.builder, self.builder.writer
        lines = ['def _dydt_assemble(t, y, X):', '    parts = []']
        targets: List[np.ndarray] = []
        for ph in b.phases:
            kind = ph[0]
            if kind == 'transfers':
                _, tgt, flux, sign = ph
                lines.append(f'    F = X[{w.bind(b.flux_rate)}]')
                if b.flux_mbd.size:
                    lines.append(f'    F[{w.bind(b.flux_mbd)}] *= y[{w.bind(b.flux_mbd_src)}]')
                lines.append(f'    parts.append(F[{w.bind(flux)}] * {w.bind(sign)})')
                targets.append(tgt)
            elif kind == 'x':
                _, tgt, xs = ph
                lines.append(f'    parts.append(X[{w.bind(xs)}])')
                targets.append(tgt)
            elif kind == 'waste':
                _, p_idx, m_idx, h, r_idx, budget = ph
                lines.append(f'    fail = X[{h}] * y[{w.index(p_idx)}]')
                lines.append(f'    rel = X[{w.index(r_idx)}]')
                if budget is None:
                    lines.append('    parts.append(np.column_stack((-fail, fail - rel)).ravel())')
                    targets.append(np.column_stack((p_idx, m_idx)).ravel())
                else:
                    lines.append('    parts.append(np.column_stack((-fail, fail - rel, rel)).ravel())')
                    targets.append(np.column_stack((p_idx, m_idx, budget)).ravel())
            elif kind == 'move':
                _, a_idx, second, lam_slot, share_slot = ph
                lines.append(f'    m = X[{lam_slot}] * X[{share_slot}] * y[{w.index(a_idx)}]')
                if second is None:
                    lines.append('    parts.append(-m)')
                    targets.append(a_idx)
                else:
                    lines.append('    parts.append(np.column_stack((-m, m)).ravel())')
                    targets.append(np.column_stack((a_idx, second)).ravel())
            elif kind == 'mean':
                _, s_idx, t_idx, mem = ph
                n = s_idx.size
                lines.append(f'    rec = np.array([MEM[k].recording for k in range({mem}, {mem + n})])')
                lines.append(f'    parts.append(np.where(rec, X[{w.index(t_idx)}], 0.0))')
                targets.append(s_idx)
            elif kind == 'coef':
                _, tgt, coef, src = ph
                lines.append(f'    parts.append({w.bind(coef)} * y[{w.bind(src)}])')
                targets.append(tgt)
            elif kind == 'farf':
                k = ph[1]
                F = self.FARF[k]
                lines.append(f'    FARF[{k}].refresh(X)')
                lines.append(f'    parts.append((FARF[{k}].vals * y[{w.bind(F.col_idx)}]).ravel())')
                targets.append(F.row_flat)
        all_targets = np.concatenate(targets) if targets else np.zeros(0, dtype=np.int64)
        self._targets = all_targets.astype(np.int64)
        lines.append(f'    if not parts:')
        lines.append(f'        return np.zeros({self.nstate})')
        lines.append(f'    return np.bincount({w.bind(self._targets)}, weights=np.concatenate(parts), '
                     f'minlength={self.nstate})')
        src = '\n'.join(lines) + '\n'
        self.source['assembly'] = src
        return self._exec('dydt_assemble', src)

    def _compile_initial(self) -> Callable[..., Any]:
        b = self.builder
        before = write_statements(b.writer, merge_statements([Stmt(s.out, s.tree, s.width, s.block, s.level,
                                                                   s.mergeable, s.code, s.array, s.multiply)
                                                              for s in b.initial_before]))
        body = write_statements(b.writer, merge_statements(b.initial_stmts))
        src = '\n'.join(['def _initial(t, y, X, y0):', '    T = _f64(t)', *before, *body, '    return y0', ''])
        self.source['initial'] = src
        return self._exec('initial', src)

    def _compile_jumps(self) -> List[Jump]:
        out = []
        b = self.builder
        for k, spec in enumerate(b.jump_specs):
            name = f'jump{k}'
            src = '\n'.join([f'def _{name}(y, X):', *('    ' + line for line in spec['code']), '    return y', ''])
            self.source[name] = src
            fn = self._exec(name, src)

            def apply(y: np.ndarray, _fn: Callable[..., Any] = fn) -> None:
                with np.errstate(all='ignore'):
                    _fn(y, self.X)

            if spec.get('slot') is not None:
                out.append(Jump(spec['name'], apply, slot=spec['slot'], text=spec.get('text', '')))
            else:
                D = b.disruption_layout[spec['index']]
                out.append(Jump(spec['name'], apply, times=lambda D=D: D.sampled_times))
        return out

    # --- evaluating -----------------------------------------------------------------------------

    def refresh_tables(self) -> None:
        """The distributed points of the lookup tables back into their tables."""
        for pt in self.builder.point_layout:
            if pt.tab < 0 or pt.row < 0:
                continue
            table = self.TAB[pt.tab]
            if pt.row < table.n:
                table.set_y(pt.row, float(self.P[pt.slot]))

    def restart_paths(self) -> None:
        """Starts a run for the far-field paths: their matched layers are laid
        out again at its first instant and held to its end (``restartPaths``)."""
        for F in self.FARF:
            F.restart()

    def evaluate_invariant(self, t: Optional[float] = None, y: Optional[np.ndarray] = None) -> np.ndarray:
        """Works out the slots that never move (after a parameter has changed)."""
        self.refresh_tables()
        tt = self.start_time if t is None else float(t)
        yy = np.zeros(self.nstate) if y is None else y
        with np.errstate(all='ignore'):
            self._once(tt, yy, self.X)
        self._clock_at = math.nan
        self._invariant_version += 1
        return self.X

    def use_clock_interpolation(self, interval: float, frm: Optional[float] = None) -> None:
        """Works the clock-only slots out every ``interval`` and interpolates
        between (``min_change_time``); 0 is off."""
        self._min_change = interval if math.isfinite(interval) and interval > 0 else 0.0
        self._origin = frm if frm is not None and math.isfinite(frm) else self.start_time
        self._lo_t = math.nan
        self._hi_t = math.nan
        self._clock_at = math.nan

    def _clock_into(self, t: float, y: np.ndarray, into: np.ndarray) -> None:
        self._clock(t, y, self.X)
        into[:] = self.X[self.clock_idx]

    def at_instant(self, t: float, y: np.ndarray) -> None:
        """Brings the clock-only slots up to ``t``, if they are not there already."""
        if t == self._clock_at:
            return
        if self._min_change > 0 and self.clock_idx.size:
            k = math.floor((t - self._origin) / self._min_change)
            a = self._origin + k * self._min_change
            b = a + self._min_change
            if a != self._lo_t:
                if a == self._hi_t:
                    self._lo_x[:] = self._hi_x
                else:
                    self._clock_into(a, y, self._lo_x)
                self._lo_t = a
            if b != self._hi_t:
                self._clock_into(b, y, self._hi_x)
                self._hi_t = b
            wgt = (t - a) / self._min_change
            self.X[self.clock_idx] = self._lo_x + wgt * (self._hi_x - self._lo_x)
            self._clock_at = t
            return
        self._clock(t, y, self.X)
        self._clock_at = t

    def evaluate_at_instant(self, t: float, y: np.ndarray) -> None:
        with np.errstate(all='ignore'):
            self.at_instant(t, y)

    def evaluate_algebraic(self, t: float, y: np.ndarray) -> np.ndarray:
        """Every algebraic slot at ``(t, y)``, in ``X`` (the array is reused)."""
        with np.errstate(all='ignore'):
            self.at_instant(t, y)
            self._step(t, y, self.X)
        return self.X

    def dydt(self, t: float, y: np.ndarray, out: Optional[np.ndarray] = None) -> np.ndarray:
        """The derivative at ``(t, y)``."""
        with np.errstate(all='ignore'):
            self.at_instant(t, y)
            self._step(t, y, self.X)
            d = self._assemble(t, y, self.X)
        if out is not None:
            out[:] = d
            return out
        return d

    def rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        """The derivative at ``(t, y)``, for a solver: a fresh array each call,
        and no floating-point error state of its own -- the runner holds one
        (everything ignored) around the whole solve, which on a small model
        costs less than setting it on every call."""
        self.at_instant(t, y)
        self._step(t, y, self.X)
        return self._assemble(t, y, self.X)

    def initial_state(self) -> np.ndarray:
        y0 = np.zeros(self.nstate)
        with np.errstate(all='ignore'):
            self._initial(self.start_time, y0, self.X, y0)
        return y0

    # --- recorders and events -------------------------------------------------------------------

    def prime_recorders(self, t0: float, y0: np.ndarray) -> None:
        """Puts every history back to the start of a run."""
        if not self.remembering and not self.laplace:
            return
        for r in self.MEM:
            r.prime(t0, 0.0)
        values = self.evaluate_algebraic(t0, y0)
        for rec in self.remembering:
            seed = rec.aux['initial'] if rec.kind == 'snapshot' else rec.aux['target']
            for off in range(rec.width):
                self.MEM[rec.mem + off].prime(t0, float(values[seed.base + off]))
        # A semi-analytical path starts its history with the inflow at t0.
        for F in self.laplace:
            F.prime(t0, y0, values)

    def store_step(self, t: float, y: np.ndarray) -> None:
        """Records a step the solver accepted (the accepted-step callback)."""
        if not self.remembering and not self.laplace:
            return
        values = self.evaluate_algebraic(t, y)
        for rec in self.remembering:
            frm = rec.aux['target'] if rec.kind == 'delay' else rec.entry
            for off in range(rec.width):
                self.MEM[rec.mem + off].store(t, float(values[frm.base + off]))
        for F in self.laplace:
            F.store(t, y, values)

    def start_segment(self, t: float, y: np.ndarray) -> None:
        """A segment starts at ``t`` from ``y`` (``startSegment``): after a
        switch time the inflow into a semi-analytical path may have stepped,
        and after a jump what it holds may have, which is an amount delivered
        at once. Only those paths are told."""
        if not self.laplace:
            return
        values = self.evaluate_algebraic(t, y)
        for F in self.laplace:
            F.store(t, y, values)

    @property
    def has_store_step(self) -> bool:
        return bool(self.remembering or self.laplace)

    def set_disruption(self, index: int, sampled: bool, times: Sequence[float] = ()) -> None:
        """Whether an event's occurrences are drawn for this run, and which."""
        layout = self.builder.disruption_layout
        if not (0 <= index < len(layout)):
            return
        D = layout[index]
        self.DIS[index] = 0.0 if sampled else 1.0
        D.sampled_times = sorted(times) if sampled else []
        self._clock_at = math.nan

    def run_state(self) -> Dict[str, Any]:
        """What a run leaves on the system that reading its results depends
        on -- the recorders' histories, the events drawn, the clock
        interpolation it ended with -- in a form that can travel between
        processes. See :meth:`restore_run_state`."""
        return {'mem': list(self.MEM), 'dis': self.DIS.copy(),
                'sampled': [list(getattr(D, 'sampled_times', []) or []) for D in self.builder.disruption_layout],
                'clock': (self._min_change, self._origin),
                'laplace': [F.run_state() for F in self.laplace]}

    def restore_run_state(self, state: Dict[str, Any]) -> None:
        """Puts a run's state (from :meth:`run_state`, perhaps of the same
        model built in another process) on this system."""
        # The compiled passes hold these very containers, so they are filled
        # in place, never replaced.
        self.MEM[:] = state['mem']
        self.DIS[:] = state['dis']
        for F, kept in zip(self.laplace, state.get('laplace') or []):
            F.restore_run_state(kept)
        for D, times in zip(self.builder.disruption_layout, state['sampled']):
            D.sampled_times = list(times)
        self.use_clock_interpolation(*state['clock'])

    def slot_value(self, i: int) -> float:
        return float(self.X[i])

    def span_start(self) -> float:
        return self.start_time

    def span_end(self) -> float:
        return self.end_time

    # --- layout -----------------------------------------------------------------------------

    def _layout(self) -> Layout:
        b = self.builder
        from ..indexlists import NUCLIDE_LIST  # noqa: F401 - kept for symmetry with the application
        return Layout(
            nstate=b.nstate, nalg=b.nalg, nparam=b.nparam, slot_class=b.slot_class,
            invariant_slots=(b.slot_class == 0).astype(np.uint8), ninvariant=int(np.sum(b.slot_class[:b.nalg] == 0)),
            nclock=int(np.sum(b.slot_class[:b.nalg] == 1)), states=b.states, mean_states=b.mean_states,
            farfields=b.farf_layout,
            wastes=[{'name': W.q, 'intact': W.intact.base, 'exposed': W.exposed.base, 'width': W.width,
                     'release': W.release_slot.base, 'failure': W.failure} for W in b.waste_layout],
            budget=b.budget,
            lookup_points=[{'name': pt.name, 'index': pt.index, 'at': pt.at, 'slot': pt.slot, 'spec': pt.spec,
                            'dims': pt.dims, 'unit': pt.block.get('unit') or ''} for pt in b.point_layout],
            events=[{'name': D.q, 'index': D.index, 'timing': D.timing, 'sampled': D.block.get('sampled') is not False,
                     'state': D.entry.base,
                     'rate_slot': D.setting['rate'].base if 'rate' in D.setting else None,
                     'from_slot': D.setting['from'].base if 'from' in D.setting else None,
                     'until_slot': D.setting['until'].base if 'until' in D.setting else None}
                    for D in b.disruption_layout],
            algebraic=b.algebraic, parameters=b.param_layout, lookups=b.lookup_layout, index_space=b.space,
            material_list=b.material_list, nuclides=self.project.material_names,
            has_nuclides=bool(b.material_list),
            material_units={n: self.project.material_unit(n) for n in self.project.material_names},
        )
