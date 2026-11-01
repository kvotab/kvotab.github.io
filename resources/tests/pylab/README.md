# pylab.html: tests

pylab.html is a desktop for programs in the MATLAB language: a Command
Window, an Editor with breakpoints, the Workspace, the Current Folder, the
Command History and figure windows. What is typed or run is compiled to
Python by `resources/py/plab` and run on NumPy and SciPy in Pyodide, in a
module worker (`resources/js/pylab-worker.mjs`).

## Where things are

| Path | What |
|---|---|
| `resources/py/plab/lexer.py`, `parser.py` | the language: tokens (command syntax, transpose against quotes, `end` in indices) and the syntax tree |
| `resources/py/plab/compiler.py` | the tree as async Python: functions become `async def LF_name(nargout, *args)`, anonymous functions module-level `_A<n>`, a debugger hook before each statement |
| `resources/py/plab/runtime.py` | workspaces, calls by name, function files and the path, errors and their stacks, output |
| `resources/py/plab/values.py`, `ops.py`, `index.py`, `display.py` | values (copy-on-write), operators and class rules, indexing and assignment, the Command Window's number formats |
| `resources/py/plab/builtins/` | the functions, one module per area; `helptext.py` holds each one's help |
| `resources/py/plab/graphics_base.py`, `glayout.py`, `colormaps.py` | graphics objects and their properties, sent to the page as JSON |
| `resources/py/plab/matfile.py` | MAT-files read into values: Level 4 and 5 here, version 7.3 through h5py (loaded when the first such file is read) |
| `resources/py/plab/worker_api.py` | what the page calls: run, workspace, completion, files, the debugger |
| `resources/js/pylab-*.js`, `resources/css/pylab.css` | the desktop; `pylab-figure.js` draws the figures on canvases |
| `resources/py/plab/examples/` | the example files a new home folder starts with |

Help texts and examples are written anew for this page: nothing is copied
from MathWorks documentation or software.

## Running the tests

The language and MAT-file suites run the package natively, with no
browser. They need a Python with numpy and scipy (Pyodide 314.0.7 has NumPy
2.4.6 and SciPy 1.18.0), and the MAT-file suite h5py:

    python3 resources/tests/pylab/test_lang.py
    python3 resources/tests/pylab/test_matfile.py

No MAT-file in the tests was written by MATLAB: they come from SciPy, from
h5py and from the data elements test_matfile.py writes out itself.

The browser test drives headless Chrome over the DevTools protocol
(`cdp.py`, needs the `websockets` package). Start a server on the
repository root and Chrome on the ports in `PYLAB_HTTP_PORT` and
`PYLAB_CDP_PORT` (defaults 8811 and 9311), then run it:

    python3 -m http.server 8811 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --remote-debugging-port=9311 --no-first-run \
      --user-data-dir=/tmp/pylab-chrome --disable-gpu about:blank
    python3 resources/tests/pylab/test-ui.py

With `PYLAB_SHOTS=<folder>` it saves screenshots. Pyodide, NumPy and SciPy
come from cdn.jsdelivr.net, so the browser test needs the network.

| Suite | Checks (2026-11-01) | What |
|---|---|---|
| `test_lang.py` | 521 | arithmetic and the class rules (integers saturate, single wins, implicit expansion), indexing and assignment (growth, deletion, logical and linear indices, `end`), copy-on-write, cells, structs and struct arrays, text and strings, control flow, functions and handles (nargin, varargin and varargout, local functions, nested functions sharing their parent's variables, anonymous functions and the values they capture), function files and scripts, the workspace, display formats, numerics against known values, ODEs (ode15i, odextend), MAT and text files, graphics state, errors in anonymous functions, fields of variables made while a line runs (by eval or load), field names that are no names refused, and that every function and keyword has its help |
| `test-ui.py` | 90 | the desktop in Chrome: typed commands, the Workspace and Command History, errors, completion and help, the debugger (breakpoint, K>>, Step, Continue), input(), Ctrl+C, the Variable editor, the Current Folder, the figure tools (zoom box, pan, data tips, grid, 3-D turning, Restore, saving a picture), files dropped from the computer (opened in the Editor, MAT-files of versions 7 and 7.3 loaded, Replace and Keep both, the Current Folder and its folder rows, folders, text drags, dialogs, a file whose name is no name run through `run`), the dark theme, the full window, the phone layout |
| `test_matfile.py` | 235 | MAT-files read by `load`: Level 4 and 5 from SciPy, version 7.3 from h5py, and data elements written out (text in UTF-8, UTF-16 and UTF-32, big-endian, small elements, logical sparse, empty structs, objects, function handles); damaged, cut and hostile files (a variable that cannot be read is left out with a warning, as is a variable or field whose name is no name, and a function handle's text must be one anonymous function); the Details panel's list; `save` and `load` back and forth, `save -append` |

The page's icon is drawn by `scripts/gen-pylab-icon.py`;
`resources/tests/site/test-page-icons.py` checks it with the other pages'.
