"""Kompartment models from Python.

Read a Kompartment project file into a :class:`Model`, or start a new one, edit
it through documented methods -- :meth:`Model.add_compartment`,
:meth:`Model.add_transfer`, :meth:`Model.rename_block`, ... -- and write it back
as a project file the application opens::

    import kompartment as kp

    m = kp.Model.load('biosphere.json')
    m['Soil'].set_value('5e9', at='Cs-137')
    m.rename_block('Soil', 'Topsoil')
    m.save('biosphere-edited.json')

    res = m.run()                  # solve it: see kompartment.engine
    res.to_csv('biosphere.csv')
    res.to_hdf5('biosphere.h5')    # or res.save('biosphere.zip'), the model and its run

    p = m.run_probabilistic(1000, workers=8)

Every block is a view onto the model's own dictionary (:attr:`Model.raw`), so
nothing is copied and what the objects show is what is saved. Edits that reach
across the model follow the change through every reference, as the
application's editor does, and refuse what it refuses with an
:class:`EditError`.
"""

from . import decay, distributions
from .blocks import (
    Block, BlockReduction, Compartment, Delay, Event, Expression, Farfield, Function, IndexReduction,
    Inflow, Lookup, MinMax, Parameter, RunningMean, Snapshot, Transfer, Trigger, WastePackage,
)
from .distributions import make_pdf
from .equations import EquationSyntaxError
from .errors import EditError, KompartmentError, ValidationError
from .jsonio import dumps, read_model_file, write_model_file
from .model import IndexList, Model, Shape, View
from .simulation import OutputSeries, Simulation

__version__ = '0.1.0'

__all__ = [
    'Model', 'IndexList', 'Shape', 'View', 'Simulation', 'OutputSeries',
    'Block', 'Compartment', 'Transfer', 'Inflow', 'Parameter', 'Expression', 'Lookup',
    'IndexReduction', 'BlockReduction', 'Function', 'MinMax', 'RunningMean', 'Snapshot',
    'Delay', 'Trigger', 'Farfield', 'WastePackage', 'Event',
    'KompartmentError', 'EditError', 'ValidationError', 'EquationSyntaxError',
    'decay', 'distributions', 'make_pdf', 'dumps', 'read_model_file', 'write_model_file',
    'load', 'new', 'run', 'load_results',
]


def load(path: 'str') -> Model:
    """Reads a model file: ``.json``, ``.json.gz`` or ``.zip``. Same as :meth:`Model.load`."""
    return Model.load(path)


def run(model, *, on_progress=None, workers=None, compiled='auto', **simulation):
    """Runs a model -- a :class:`Model`, a project dict, or a model file's path --
    and returns its :class:`kompartment.engine.Results`. Keyword arguments
    override simulation settings for this run: ``kp.run('m.json', solver='ros23')``.
    ``workers`` caps the processes a run solved in parts takes (every core by
    default); ``compiled`` -- 'auto', True or False -- is whether it runs
    compiled with numba.
    """
    from .engine import run as _run
    return _run(model, on_progress=on_progress, workers=workers, compiled=compiled, **simulation)


def load_results(source, *, project=None):
    """The run in a model archive -- :meth:`Results.save`'s, or the application's
    *Save with results* -- as :class:`kompartment.engine.Results`, the model in
    the archive built and the stored run put back on it. ``source`` is a path or
    the archive's bytes; ``project`` a model to use instead of the archive's,
    which must lay its states out the same way."""
    from .io.dataset import load_results as _load
    return _load(source, project=project)


def new(name: str = 'New model', description: str = '') -> Model:
    """A new, empty model. Same as :meth:`Model.new`."""
    return Model.new(name, description)
