"""The statistics behind smui.html.

The page runs this package in Pyodide. It sends tables with
data.set_table() and calls analyses by name with registry.dispatch();
every analysis module registers its names with @api. The modules are
listed in manifest.json and imported one by one, so one that fails to
import does not take the others with it.

The notebook's cells run here too (notebook.py), and reach the page's
tables through smui.table_names(), smui.table(name) and smui.new_table(df).
"""
from .registry import api, dispatch, names  # noqa: F401
from . import util, data  # noqa: F401
# In a notebook cell: import smui; smui.table('Students'), smui.new_table(df), ...
try:
    from .notebook import display, new_table, table, table_names  # noqa: F401
except ImportError:  # the notebook's file did not load: the analyses still run
    pass
