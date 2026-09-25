"""The simulation engine: a model built into equations, solved, and reported.

A port of the parts of Kompartment that are not its interface -- the project
loader, the builder, the solvers, the runner and the results -- to Python,
with numpy doing the arithmetic and SciPy the linear algebra::

    import kompartment as kp

    res = kp.load('biosphere.json').run()
    res['Dose [Cs-137]']          # a series, by the label the application gives it
    res.to_csv('biosphere.csv')   # the application's CSV export

:func:`run` takes a model (a :class:`kompartment.Model`, a project dict or a
path); :class:`Project`, :func:`build_system` and :class:`System` are the
layers below it. The other kinds of run are :func:`run_probabilistic` (with
:func:`run_tornado` and :func:`run_gsa`), :func:`run_scenarios`,
:func:`run_sensitivity` and :func:`calibrate`; :func:`values_at_start` is what
the equations come to before any of them. :class:`kompartment.Model` has a
method for each.
"""

from .atstart import run_scenarios, values_at_start
from .builder import BuildError, build_system
from .calibrate import calibrate
from .localsens import run_sensitivity
from .probabilistic import ProbabilisticResults, run_gsa, run_probabilistic, run_tornado
from .project import Project, ValidationError
from .runner import Results, run as _run
from .solvers import SolverError
from .system import System

__all__ = ['run', 'Project', 'ValidationError', 'build_system', 'BuildError', 'System', 'Results', 'SolverError',
           'run_probabilistic', 'run_tornado', 'run_gsa', 'ProbabilisticResults', 'run_scenarios', 'values_at_start',
           'run_sensitivity', 'calibrate']


def run(model, *, on_progress=None, **simulation):
    """Runs a model -- a :class:`kompartment.Model`, a project dict, or the path
    of a model file -- and returns its :class:`Results`. Keyword arguments
    override simulation settings for this run."""
    from pathlib import Path
    from ..model import Model
    if isinstance(model, (str, Path)):
        model = Model.load(model)
    if isinstance(model, Model):
        return model.run(on_progress=on_progress, **simulation)
    if isinstance(model, Project):
        if simulation:
            raise TypeError('simulation overrides need a model, not a loaded Project')
        return _run(model, on_progress=on_progress)
    data = dict(model)
    if simulation:
        data['simulation'] = {**(data.get('simulation') or {}), **simulation}
    return _run(Project(data), on_progress=on_progress)
