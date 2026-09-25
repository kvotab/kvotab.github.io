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
    'load', 'new',
]


def load(path: 'str') -> Model:
    """Reads a model file: ``.json``, ``.json.gz`` or ``.zip``. Same as :meth:`Model.load`."""
    return Model.load(path)


def new(name: str = 'New model', description: str = '') -> Model:
    """A new, empty model. Same as :meth:`Model.new`."""
    return Model.new(name, description)
