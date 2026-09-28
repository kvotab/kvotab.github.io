"""matplotlib in the notebook: drawn off screen (Agg), shown in the page.

The notebook points MPLBACKEND at this module ("module://smui.nb_backend").
Figures are drawn as with Agg; plt.show() hands the open ones to the cell's
outputs (as SVG, or PNG for a figure with many points), and a cell that
ends with figures still open shows them too. Not imported at start: it
needs matplotlib, which loads with the first cell that imports it.
"""
from matplotlib.backend_bases import FigureManagerBase as FigureManager  # noqa: F401 - the backend's interface
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas  # noqa: F401


def show(*args, **kwargs):
    from . import notebook
    notebook.flush_figures()
