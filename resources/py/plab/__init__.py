"""plab: a MATLAB-language interpreter for pylab.html.

The language's programs are compiled to Python (compiler.py) and run on
numpy and scipy (runtime.py and builtins/). The page's worker loads this
package into Pyodide; the native tests import it directly.
"""
