"""The statistics behind smui.html.

The page runs this package in Pyodide. It sends tables with
data.set_table() and calls analyses by name with registry.dispatch();
every analysis module registers its names with @api. The modules are
listed in manifest.json and imported one by one, so one that fails to
import does not take the others with it.
"""
from .registry import api, dispatch, names  # noqa: F401
from . import util, data  # noqa: F401
