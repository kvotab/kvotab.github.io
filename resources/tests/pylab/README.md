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
| `resources/py/plab/parfor.py`, `builtins/parallel.py` | parfor: which loops run on the pool's workers and how their variables travel; the pool (parpool, gcp) and the loop's run there; the workers' side is in `worker_api.py`, the pool's JavaScript in `pylab-worker.mjs` |
| `resources/py/plab/builtins/distributions.py`, `statdesc.py`, `stattests.py`, `statplots.py` | statistics: each distribution's functions in the language's parameters (on scipy.stats), fits and distribution objects; descriptive statistics and groups; hypothesis tests; the statistical plots, made of the ordinary graphics objects |
| `resources/py/plab/figfile.py` | figure files (.fig): the MAT-file tree of structs (hgS_070000) read into figures by openfig, hgload and open, and written by savefig, hgsave and saveas |
| `resources/py/plab/matfile.py` | MAT-files read into values: Level 4 and 5 here, version 7.3 through h5py (loaded when the first such file is read) |
| `resources/py/plab/uiobjects.py`, `uievents.py`, `builtins/uifun.py` | programs' user interfaces: controls, panels, tables, tabs, menus, context menus and toolbars as graphics objects; what people do with them (the page's events) and the callbacks that answer, run when the engine is idle or at a running program's drawnow, pause, uiwait and waitfor; the dialogs and timers |
| `resources/py/plab/worker_api.py` | what the page calls: run, workspace, completion, files, the debugger, a figure's events |
| `resources/js/pylab-*.js`, `resources/css/pylab.css` | the desktop; `pylab-figure.js` draws the figures on canvases (and sends their clicks, keys and wheel to the program); `pylab-ui.js` builds a program's menus, toolbars and controls over them, and shows the dialogs it asks for |
| `resources/py/plab/examples/` | the example files a new home folder starts with |

Help texts and examples are written anew for this page: nothing is copied
from MathWorks documentation or software.

## Running the tests

The language and MAT-file suites run the package natively, with no
browser. They need a Python with numpy and scipy (Pyodide 314.0.7 has NumPy
2.4.6 and SciPy 1.18.0), and the MAT-file suite h5py:

    python3 resources/tests/pylab/test_lang.py
    python3 resources/tests/pylab/test_matfile.py
    python3 resources/tests/pylab/test_parfor.py
    python3 resources/tests/pylab/test_stats.py
    python3 resources/tests/pylab/test_gui.py

No MAT-file in the tests was written by MATLAB: they come from SciPy, from
h5py and from data elements written out in `matfixtures.py` (string arrays
too, in the layout the open-source mat-io reader documents).

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
| `test_lang.py` | 591 | arithmetic and the class rules (integers saturate, single wins, implicit expansion), indexing and assignment (growth, deletion, logical and linear indices, `end`), copy-on-write, cells, structs and struct arrays, text and strings, control flow, functions and handles (nargin, varargin and varargout, local functions, nested functions sharing their parent's variables, anonymous functions and the values they capture), function files and scripts, the workspace, display formats, numerics against known values, ODEs (ode15i, odextend), MAT and text files, graphics state, errors in anonymous functions, variables made while a line runs (by eval or load: their fields, and shown by their names), field names that are no names refused, ismissing, one cs-list as a whole index, mfilename, a function's text typed or given to eval refused with a message, a program not found named where its file is (a folder not searched, or a file of another name), arrayfun and cellfun asked for no output asking the function for none (disp, plot) and over matrices with UniformOutput false, num2cell of a struct matrix, the bit functions (uint64 to its last bit, signed shifts, whole doubles only), integers converted exactly and saturated, etime's sign, help with an output, and that every function and keyword has its help |
| `test-ui.py` | 163 | the desktop in Chrome: typed commands, the Workspace and Command History, errors, completion and help, the debugger (breakpoint, K>>, Step, Continue), input(), Ctrl+C, the Variable editor, the Current Folder, the figure tools (zoom box, pan, data tips, grid, 3-D turning, Restore, saving a picture), the Editor's view (the caret centred on the letters of its line, line numbers on the code's baseline and at their lines 500 lines down, typing that never widens the code, the line numbers kept at the left edge when the code scrolls sideways and the caret kept clear of them, the caret in view after a long paste; the Command Window's caret centred too, and the window fitting its panel), files dropped from the computer (opened in the Editor, MAT-files of versions 7 and 7.3 loaded, string arrays too, Replace and Keep both, the Current Folder and its folder rows, folders, text drags, dialogs, a file whose name is no name run through `run`, a program dropped on a folder row not found from the current folder with the error saying where it is, then run from its folder with Windows line ends), parfor on a pool of two workers (passes at the same time, results in order, files there and back, errors, Ctrl+C, delete(gcp)), statistics on the page's SciPy (tests, a fitted distribution, anova1's table and box plots; boxplot, scatterhist, gplotmatrix, histfit, normplot, qqplot and gscatter drawn), a program's own windows (the wavelab example's popup, slider, field, radio buttons and check box; a click in its axes, a key, a menu accelerator, a toggle tool's timer, a context menu, an error dialog closed by Enter, a close that runs CloseRequestFcn; tabs with axes, a table typed in, a list double-clicked; questdlg, inputdlg, listdlg and uigetfile as the page shows them; a message box and a wait bar never current; uiwait until a callback's uiresume; a message box kept over the figure drawn in after it, text above the axes' box drawn, sound through the page's audio, a window taking the size its program sets, text placed in pixels, a .fig opened from the Current Folder), the dark theme, the full window, the phone layout |
| `test_parfor.py` | 127 | parfor on a pool whose workers run in this process, in a shuffled order: sliced variables (vectors, columns, rows, cells, in and out), broadcast values (numbers, structs, cells, function handles, strings, maps), reductions (+ - .* * & |, rows and columns in order, min, max), temporaries, inner loops and inner parfor, local functions and files on the path, output, errors, random numbers, files written; the loops that run one pass at a time and the reason given once; parpool, gcp, getCurrentTask, the worker limit |
| `test_stats.py` | 354 | the statistics functions against what is computed here independently: each distribution's density in closed form, its cdf summed or integrated, quantiles that invert it, means and variances, the far tail ('upper'), invalid parameters, random numbers from rng; fits whose likelihood is largest at the estimates, exact intervals, likelihoods; distribution objects (parameters, truncation, kernels, 'By'); the multivariate normal and t, sampling; descriptive statistics and groups; the tests against SciPy and against their exact distributions counted out (signed rank, rank sum, runs), the rates at which they reject samples that meet their hypothesis; the plots' objects (box plot parts and Tags, groups' lines, the matrix of axes, the margins of scatterhist, histfit's curve, probability axes, steps, least-squares lines); help for every function |
| `test_gui.py` | 213 | user interfaces without a browser: the controls, panels, button groups, tables, tabs, menus and toolbars and their properties (Units converted in place, the other names some properties go by, the first radio button of a group chosen); the description the page builds from (menus in order, tools as RGBA, the axes of the shown tab only); the page's events and the callbacks they queue, as text, function handles and cells, with gcbo, gcbf and gco; check boxes, fields, sliders, lists, popups, radio groups, table cells and tabs; menus and their opening, context menus, toggle and push tools; keys (WindowKeyPressFcn first, a field keeps its keys); clicks (CurrentPoint, SelectionType, HitTest), motion that came while one waited run once, the wheel, a resize, the close button and close with CloseRequestFcn, close force, DeleteFcn; uiwait and uiresume, waitfor, callbacks during pause and drawnow (not drawnow nocallbacks); msgbox and its kin as figures of no number and never current, a picture of its own stretched over the sign's square, text wrapped at 75 letters, waitbar and its Cancel; questdlg, inputdlg, listdlg, uigetfile, uiputfile, uigetdir, menu and uisetcolor with the page's answers stood in for; timers (StartFcn, ticks, TasksToExecute, StopFcn, BusyMode drop, singleShot, timerfind, wait, delete); findobj and findall (HandleVisibility, callbacks and ShowHiddenHandles; -regexp, -property, -function, -and, -or, -xor, -not, flat and -depth); Clipping in the description (text not clipped); programs of older releases (DoubleBuffer, DrawMode, EraseMode kept; handle numbers in numeric arrays, never whole; FontUnits and a text's Units converting the size and place; a text box's margin and line width; Position the program set; patch adding to the axes, fill not); sound, soundsc and beep as the page is sent them; figure files (a round trip through savefig and openfig keeping axes, labels, lines, patches, text, series, legends, menus, controls, callbacks, CreateFcn, appdata and FileName; a file in the older layout built by the test with lineseries, a group and labels named by handle number; compact-only and non-figure files refused; open and saveas; function handle callbacks left out with a warning; 'reuse'); appdata and guidata; strmatch (a cell matrix down its columns) and textread; the toolbar pictures for programs that load them from matlabroot |
| `test_matfile.py` | 318 | MAT-files read by `load`: Level 4 and 5 from SciPy, version 7.3 from h5py, string arrays (objects in the file's subsystem: Level 5 in both byte orders, compressed, in cells, and 7.3), and data elements written out (text in UTF-8, UTF-16 and UTF-32, big-endian, small elements, logical sparse, empty structs, objects, function handles); damaged, cut and hostile files (a variable that cannot be read is left out with a warning, as is a variable or field whose name is no name, and a function handle's text must be one anonymous function); the Details panel's list; `save` and `load` back and forth, `save -append` |

The page's icon is drawn by `scripts/gen-pylab-icon.py`;
`resources/tests/site/test-page-icons.py` checks it with the other pages'.
