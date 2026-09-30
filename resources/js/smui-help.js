/* ==========================================================================
   SMUI.HTML: THE HELP TAB AND THE (i) TOPICS OF THE FRAME

   Platforms bring their own topics (platform.topics); these are the ones
   of the page itself: the panels, the dialogs of the Rows and Cols menus,
   the engine. The Help tab lists every registered platform with the
   statsmodels functions behind it.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el } = SM.util;

  const topics = {
    'panel:table': {
      kicker: 'Panel', title: 'Table',
      lead: 'The open tables, and where the current one came from. Each table has its own tab; reports belong to the table they were launched from.',
      sections: [
        { heading: 'The red triangle', text: 'Rename the table, edit its notes, save it as this page\'s JSON (keeps modeling types, value orders, formulas and row states) or export CSV or Excel.' },
        { heading: 'Scripts', text: 'The table\'s scripts, as JMP keeps them with a data table: a report saved with Save ▾ > Save Script to Data Table, or the model a DOE design comes with. A click runs one (a report opens, or a launch dialog filled in); right click for Run Script, Rename… and Delete. They are saved with the table and in projects.' },
      ],
      more: { label: 'Data tables', id: 'help-tables' },
    },
    'panel:columns': {
      kicker: 'Panel', title: 'Columns',
      lead: 'Every column with its modeling type, which decides how an analysis treats it.',
      sections: [
        { heading: 'Modeling types', choices: [['Continuous (blue triangle)', 'Numbers on a scale: means, regression, histograms.'], ['Ordinal (green bars)', 'Ordered categories: levels in value order; an ordinal response gets an ordinal logistic fit.'], ['Nominal (red bars)', 'Unordered categories: frequencies, contingency tables, dummy coding in models.']] },
        { heading: 'Using the list', list: ['Click the icon to change the modeling type.', 'Click a name to select the column (shift and ctrl/⌘ add); a launch dialog starts with the selected columns in its first role.', 'Drag names to reorder the columns.', 'Double click for Column Info; right click for the column menu.', 'After a name, Y, X, W (Weight) or F (Freq) is the role Cols > Preselect Role gave it, and * says it has column properties (Value Labels, Missing Value Codes, a Profit Matrix, Spec Limits, a value order): click the * for Column Info.'] },
      ],
      more: { label: 'Modeling types', id: 'help-types' },
    },
    'panel:rows': {
      kicker: 'Panel', title: 'Rows',
      lead: 'The row states. Click a line to select those rows.',
      sections: [{ heading: 'Row states', choices: [['Selected', 'Highlighted in the grid and in every graph of the table.'], ['Excluded', 'Left out of analyses (a report redone, or at once with Automatic Recalc).'], ['Hidden', 'Not drawn in graphs, still used in calculations.'], ['Labeled', 'Shows its label (the label column, or the row number) next to its points.']] }],
      more: { label: 'Row states', id: 'help-rowstates' },
    },
    'file:datasets': {
      kicker: 'File', title: 'statsmodels Datasets',
      lead: 'The datasets that ship with the statsmodels package, read from it in the Python engine: Longley, Grunfeld, Star98, the Nile, sunspots and others. They are not part of this page; each shows its own source and copyright note, which travel with the table as its notes.',
    },
    'cols:new': { kicker: 'Cols', title: 'New Column', lead: 'A column of numbers or text, empty, constant, a sequence or random values; Number of columns to add makes up to 1000 alike at once (the names go on 2, 3, …). A formula column (when the formula editor is loaded) recalculates when the columns it uses change.', more: { label: 'Formulas', id: 'help-formulas' } },
    'cols:info': {
      kicker: 'Cols', title: 'Column Info',
      lead: 'Name, data type, modeling type, display format, value order, notes and the label role of one column, and its column properties: spec limits, missing value codes, value labels and a profit matrix.',
      sections: [
        { heading: 'Data type and modeling type', text: 'Numeric columns can be continuous, ordinal or nominal; character columns are ordinal or nominal. Changing numeric to character keeps the text of the numbers; character to numeric turns what is not a number into missing.' },
        { heading: 'Value order', text: 'The order of the levels in reports and graphs, and the order of an ordinal response. By default numbers ascending and text in natural order (A2 before A10).' },
        { heading: 'Format', text: 'How the grid shows the values. A date column holds milliseconds since 1970 and shows them as dates.' },
        { heading: 'Spec Limits', text: 'The lower and upper specification limits and the target of a numeric column. Capability analyses start from them; they are saved with the table.' },
        { heading: 'Fields', choices: [
          ['Column name', 'The heading, and the name in launch dialogs and formulas. Formulas that use the column follow the new name.'],
          ['Data type', 'Numeric or Character. Numeric to character keeps the text of the numbers; character to numeric makes what is not a number missing.'],
          ['Modeling type', 'Continuous, Ordinal or Nominal: how analyses treat the column. A character column cannot be continuous.'],
          ['Format', 'Best shows up to 10 significant digits; Fixed decimals a set number of decimals; Percent the value times 100 with a % sign; Date and Date and time show the number (milliseconds since 1970) as a date. The format changes what the grid shows, not the values.'],
          ['decimals', 'The number of decimals for Fixed decimals, 0 to 12.'],
          ['Label column', 'Its values label the rows in graphs: a labeled row (Rows > Label) shows its value by its points. A table has one label column: choosing this one clears the other.'],
          ['Value order', 'The order of the levels: select one and Move Up or Move Down, Reverse the list, or Sort it back to the natural order. Reports, graphs and an ordinal response follow it.'],
          ['Spec Limits', 'LSL, Target and USL: leave a box empty for no limit.'],
          ['Missing Value Codes', 'Stored values that every analysis treats as missing (999, -1), separated by commas; the cells keep them.'],
          ['Value Labels', 'Text shown in place of a value (1 as Male); the value is what is stored, sorted and analysed.'],
          ['Profit Matrix', 'For a categorical response: the profit or cost of each decision for each actual level, which the predictive platforms use.'],
          ['Notes', 'Free text about the column, kept with the table.'],
        ] },
      ],
    },
    'rows:selectwhere': { kicker: 'Rows', title: 'Select Where', lead: 'Select the rows where a column meets a condition. Extend adds them to the selection, Restrict keeps only the selected rows that also match.' },
    'rows:colorby': { kicker: 'Rows', title: 'Color or Mark by Column', lead: 'Give each level of a categorical column its colour or marker; a continuous column gets a blue-to-red ramp from its minimum to its maximum. The colours and markers show in every graph.' },
    engine: {
      kicker: 'Engine', title: 'The Python engine',
      lead: 'The analyses are statsmodels, scipy, pandas and numpy running in Pyodide, CPython compiled to WebAssembly, in a Web Worker so the page stays responsive.',
      facts: [['Download', 'about 40 MB on the first visit, from the jsDelivr CDN; cached by the browser'], ['Start', 'a few seconds'], ['Data', 'stay in the browser']],
      sections: [{ heading: 'Restart', text: 'Restart Engine stops a calculation that runs too long (the worker is terminated) and loads the engine again from the cache. Open reports keep their results; Redo runs them again.' }],
      more: { label: 'The engine', id: 'help-engine' },
    },
    'p:distribution': {
      kicker: 'Analyze', title: 'Distribution',
      lead: 'One column at a time. Continuous columns: histogram, outlier box plot, quantiles (the (n+1)p definition), summary statistics. Ordinal and nominal columns: bar chart and frequencies.',
      sections: [
        { heading: 'Roles', choices: [['Y, Columns', 'The columns to describe, one outline each.'], ['Weight', 'Case weights for the moments (DescrStatsW weights).'], ['Freq', 'A count per row: the row stands for that many observations.'], ['By', 'A separate report for each level of the By columns.']] },
        { heading: 'The red triangles', text: 'Each column\'s red triangle adds the normal quantile plot, CDF, stem and leaf, tests of the mean (t, z, Wilcoxon signed rank) and of the standard deviation (χ²), equivalence (TOST), confidence, prediction and tolerance intervals, capability, and continuous and discrete fits with standard errors from the likelihood\'s Hessian. The top red triangle sets uniform scaling and the layout for all columns.' },
        { heading: 'Graphs', text: 'The box shows the quartiles, whiskers to the furthest values within 1.5 IQR, the mean diamond (the mean and its confidence interval) and the shortest half (red bracket). Click a bar or drag over points to select rows.' },
      ],
      more: { label: 'Distribution', id: 'help-p-distribution' },
    },
    'rows:datafilter': {
      kicker: 'Rows', title: 'Data Filter',
      lead: 'Filters the whole table. The matching rows are selected; with Show the other rows are hidden in graphs, with Include they are excluded from analyses. Closing the filter clears the hiding and excluding it did.',
      sections: [
        { heading: 'Controls', choices: [
          ['Add Filter Columns', 'Adds a column to filter by: a nominal or ordinal column shows a button per level, a continuous one a from and to range. A row must match every filter column.'],
          ['Levels', 'Click a level to keep its rows; ctrl/⌘ adds or takes away one more, shift takes the range from the level clicked last (a row matches any of them). Click the only one again to let every level through.'],
          ['from, to', 'The range of a continuous column: type a lower and an upper limit; an empty box is no limit.'],
          ['Select', 'The matching rows are selected in the table, and so in every graph.'],
          ['Show', 'The other rows are hidden: graphs do not draw them.'],
          ['Include', 'The other rows are excluded: analyses leave them out.'],
          ['remove, Clear', 'remove takes one column out of the filter, Clear all of them.'],
        ] },
        { heading: 'Versus the Local Data Filter', text: 'The Local Data Filter (a report\'s red triangle) narrows one report and leaves the table alone; the Data Filter changes the table\'s row states, which every report sees.' },
      ],
      more: { label: 'Row states', id: 'help-rowstates' },
    },
    'report:switcher': {
      kicker: 'Report', title: 'Column Switcher',
      lead: 'Swaps one column of the analysis for another with a click, keeping every option of the report: look at each response in turn with the same fits and tests.',
    },
    'report:filter': {
      kicker: 'Report', title: 'Local Data Filter',
      lead: 'Narrows this report to the rows that match: pick levels of categorical columns, or a range of a continuous one. The other rows are left out of this report only; the table and other reports keep them. Rows excluded in the table stay excluded.',
      sections: [
        { heading: 'Controls', choices: [
          ['Add Filter Columns', 'Adds a column to filter by: a nominal or ordinal column shows a button per level, a continuous one a from and to range.'],
          ['Levels', 'Click a level to keep its rows; ctrl/⌘ adds or takes away one more, shift takes the range from the level clicked last. Click the only one again to let every level through.'],
          ['from, to', 'The range of a continuous column: type a lower and an upper limit; an empty box is no limit.'],
          ['remove, Clear', 'remove takes one column out of the filter, Clear all of them.'],
        ] },
        { heading: 'Several filters', text: 'A row must match every filter column. Within one categorical column, ctrl/⌘ adds levels and shift a range of them (a row matches any of them).' },
      ],
      more: { label: 'Reports', id: 'help-reports' },
    },
  };

  function h(tag, text, id) { return el(tag, { text, id: id ? `help-${id}` : null }); }
  function p(text) { return el('p', null, ...inline(text)); }
  function ul(items) { return el('ul', null, ...items.map((t) => el('li', null, ...inline(t)))); }
  function inline(text) {
    const out = [];
    const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
    let at = 0;
    for (let m = re.exec(text); m; m = re.exec(text)) {
      if (m.index > at) out.push(text.slice(at, m.index));
      out.push(m[1] ? el('code', { text: m[1] }) : el('strong', { text: m[2] }));
      at = m.index + m[0].length;
    }
    if (at < text.length) out.push(text.slice(at));
    return out;
  }

  function render(view, app) {
    const box = el('div', { class: 'sm-help-inner' });
    view.replaceChildren(box);
    box.append(
      h('h2', 'User Interface for statsmodels', 'top'),
      p('A statistics workbench in the browser, laid out the way JMP lays out its work: a data table whose columns carry a modeling type, analyses launched from the Analyze and Graph menus by casting columns into roles, and reports made of outline boxes with red-triangle menus, whose graphs are linked to the table. The calculations are **statsmodels**, with scipy, pandas and numpy, running in Python in the browser.'),
      p('JMP is a registered trademark of JMP Statistical Discovery LLC. This page is not JMP and is not affiliated with or endorsed by JMP; it borrows the working style of its user interface. The numbers are statsmodels\', which are not always computed the way JMP computes them; the Python under each result says exactly how they are.'),

      h('h2', 'Getting started', 'start'),
      ul([
        'Open a table: drop a CSV, tab-separated, Excel, Stata, SAS or JMP file on the page, use **File > Open**, pick one of the simulated examples, or load a statsmodels dataset (**File > statsmodels Datasets**).',
        'Check the modeling types in the Columns panel: a number that is really a category (a subgroup, a code) should be ordinal or nominal.',
        'Choose an analysis from **Analyze** or **Graph**, put columns into the roles and press OK. The report opens in its own tab.',
        'Open the red triangles (▼ in red) for more: tests, fits, saved columns. Click the grey triangles to close outlines you do not need.',
        'Select points or bars: the rows are selected in the table and in every other graph. Exclude them (**Rows > Exclude/Unexclude**) and press **Redo**, or turn on **Automatic Recalc**.',
        'Each result computed in Python has its **Python code** under it: what statsmodels was asked and how. The **Python code** button above the report shows or hides all of it. Every graph has code under it that draws it with matplotlib from the table, so an edited graph can be run again; only the interactive ones (the profilers) have none. **Save ▾ > Save Python Script** writes all of it as one script that runs on a CSV export of the table.',
        'The button with four corners at the right end of the menu bar gives the workbench the whole window, without the site\'s header and footer. There the kvot mark at the left of the menu bar goes to kvot\'s home page, and ☀️ or 🌙 beside the button changes between the light and the dark theme. The same button brings the header and footer back, and the page keeps the choice for the next visit.',
      ]),

      h('h2', 'Data tables', 'tables'),
      p('A table is columns of equal length. A column is **numeric** or **character** (its data type) and **continuous**, **ordinal** or **nominal** (its modeling type). Missing numbers show as a dot, missing text as an empty cell.'),
      ul([
        'Edit a cell by typing or double clicking; Enter moves down, Tab to the right, Escape cancels. Delete clears the cell.',
        'Click row numbers to select rows (shift for a range, ctrl/⌘ to add); drag down the row numbers to select a block. Click a column heading to select the column.',
        'ctrl/⌘+C copies the selected rows, or the cell, as tab-separated text; ctrl/⌘+V pastes at the cursor, adding rows as needed.',
        'Right click a heading for the column menu (Column Info, modeling type, sort), a row number for the row states.',
        'Right click a cell for **Fill**: to a row, to the end of the table, or the selected rows\' values repeated or continued as a sequence (1, 2 go on 3, 4). **Header Graphs** in the grid\'s bar puts a small histogram or bar chart under each heading.',
        '**Cols > Column Properties** (and Column Info) give a column **Value Labels**, **Missing Value Codes**, a **Profit Matrix** or **Spec Limits**; **Cols > Preselect Role** gives columns the role (Y, X, Weight, Freq) a launch dialog puts them in.',
        '**File > Import Multiple Files** reads many files, or a folder of them, into one table: a row per file with its name and text (for Text Explorer), or their tables stacked.',
        'File > Save Table keeps everything (types, formats, value order, formulas, column properties, row states) in a JSON file this page opens again. File > Save Project saves all tables with their reports.',
        'A JMP data table (.jmp) brings its columns and values, dates included. JMP\'s file format is not published, and what a reader has not found in it does not come: the modeling types (numbers come in continuous and text nominal, as from a CSV file: change them in the Columns panel), value orders and labels, formulas (their values come), column properties and scripts. The reader is a port of JMPReader.jl (MIT licence, Jaakko Ruohio).',
      ]),
      h('h3', 'Modeling types', 'types'),
      el('table', null, el('tbody', null,
        ...[['Continuous', 'numeric only', 'histogram and moments; a regressor or a response in least squares'], ['Ordinal', 'numeric or character', 'ordered levels: ordinal logistic response, levels in value order'], ['Nominal', 'numeric or character', 'unordered levels: frequencies, contingency, dummy (treatment) coding in models']].map((r) => el('tr', null, ...r.map((c) => el('td', { text: c }))))),
      ),
      h('h3', 'Row states', 'rowstates'),
      p('Rows can be selected, excluded, hidden and labeled, and can carry a colour and a marker. Excluded rows are left out of every analysis; hidden rows are not drawn; labeled rows show their label in graphs. The label is the value in the label column (Cols > Label) or the row number.'),
      h('h3', 'Formulas', 'formulas'),
      p('A formula column computes its values from other columns, for example `log(:height)` or `if(:age > 14, "older", "younger")`, and recalculates when they change (Cols > Formula, when the formula editor is loaded). A formula is text parsed by this page, never run as code, so a table from someone else cannot run anything.'),

      h('h2', 'Launching an analysis', 'launch'),
      ul([
        'The dialog lists the columns with their modeling types. Select some and press a role\'s button, drag them onto a role (or onto Fit Model\'s Construct Model Effects, as main effects), or double click a column for the first role that takes it.',
        '**Y** is the response, **X** the factor or regressor; **Weight** and **Freq** are numeric; **By** repeats the analysis for each level.',
        'A **Validation** column (Analyze > Predictive Modeling > Make Validation Column) splits the rows into training, validation and test sets; one with 4 to 50 values holds K folds (Make Validation Column\'s K Fold), and the platforms that crossvalidate use them.',
        'In the column list and the role lists, click to select one, ctrl/⌘ to add or take away one more, shift to select the range from the one clicked last. Remove takes the selected columns out of their roles; Recall fills in the last launch of the platform, matched by column name.',
        'Right click a column in the dialog to change its modeling type there.',
        'The (i) in a dialog\'s title bar explains the analysis and what each role, option and field is for. Drag the title bar to move the dialog.',
        'On a phone or a tablet, touch and hold a column for a moment, then drag it where it goes (a list scrolls when the finger nears its edge); a quick swipe scrolls as usual. On a phone a dialog, and the (i) panel, take the whole screen.',
      ]),

      h('h2', 'Reports', 'reports'),
      ul([
        'An outline box has a grey disclosure triangle (open or close it) and, where it has options, a red triangle.',
        'Report tables sort by a click on a heading; right click for **Copy Table** or **Make into Data Table**.',
        'p-values below 0.0001 show as <.0001; an asterisk and red marks those below α (0.05 unless set).',
        '**Redo ▾** runs the analysis again (after exclusions or edits), relaunches the dialog, or turns on Automatic Recalc.',
        '**Local Data Filter** (in the top red triangle) narrows one report to the rows that match chosen levels or ranges, without touching the table.',
        'Every two-level classifier has JMP\'s **Decision Threshold** (drag the cut, or set it by the best MCC or the most profit; with By, each group has its own, as in JMP) and, beyond JMP, **Group Metrics**: its error rates and selection rates compared across the levels of any column, a fairness audit.',
        '**Save ▾** writes the Python script, or the report as a standalone HTML file or a Word document with its graphs as images; **Print…** prints that document, without the page around it. The browser\'s own Print prints the report in view, graphs wider than the paper scaled to fit.',
        '**Save ▾ > Save Script to Data Table** keeps the report with its table, as a script in the Table panel: a click opens it again with the same columns and options, also after the table was saved and opened again, or in a project.',
        'Graphs: click a point or bar to select its rows (shift adds), drag a rectangle to select several; double click to clear. The toolbar above a graph zooms, pans and saves it as PNG.',
        'Double-click a numeric axis of any graph (its tick labels), or right-click it, for **Axis Settings**: log scale, minimum, maximum, increment, reverse order and reference lines; the red triangle\'s Axis Settings lists the report\'s axes. They are kept with the report (Redo, By groups, projects), and the graph\'s Python code draws them too.',
      ]),

      h('h2', 'Tabs side by side', 'groups'),
      p('Tables, reports and notebooks open in tabs, and the tabs can be put in groups side by side or one above the other, so that a table and its report, or two reports, are seen together.'),
      ul([
        'Drag a tab by its title to the edge of a group (left, right, top or bottom): it goes into a new group on that side, which splits the group in two. A box shows where it will go.',
        'Drag a tab onto another group\'s tabs, or onto the middle of it, to move it there; along its own row of tabs, to put the tabs in another order. A group whose last tab leaves goes.',
        'The group last clicked in is the one in use: an accent line marks its tab in front, its table is the current one (the panels and the menus work on it), and new tabs open in it.',
        'Drag the bar between two groups to share out the room; a double click makes the two equal.',
        'Right click a tab for **Split** (right, down, left or up), **Move to Group** and **Join All Groups**.',
        'A saved project keeps the groups. On a phone the groups stack one above the other, and a tab touched and held moves between them.',
      ]),

      h('h2', 'The Python notebook', 'notebook'),
      p('**Python > New Notebook** opens a tab of cells, as in Jupyter. Code cells run in the page\'s own Python, the engine the reports use; text cells are Markdown. Each notebook keeps its own variables.'),
      ul([
        '**Shift+Enter** runs a cell and moves to the next, **Ctrl/⌘+Enter** runs it and stays, **Alt+Enter** runs it and adds a cell below. **Run All** runs every cell from the top and stops at an error.',
        'What a cell prints and the value of its last line show under it: pandas tables, statsmodels summaries, and matplotlib figures (at `plt.show()`, or at the end of the cell). A trailing `;` keeps the last value quiet.',
        'The open tables are here as the CSV files the reports\' code reads (`pd.read_csv("<name>.csv")`), so a report\'s code runs as it is. `import smui` gives `smui.table_names()`, `smui.table("<name>")` (a DataFrame, its modeling types as dtypes: ordinal and nominal columns categorical, in the table\'s value order) and `smui.new_table(df, "<name>")`, which puts a DataFrame in the page as a new table.',
        'numpy, scipy, pandas and statsmodels are in; matplotlib, scikit-learn and the other packages that come with Pyodide load when a cell imports them. `%pip install <name>` fetches a pure-Python package from PyPI.',
        '**Restart** forgets the notebook\'s variables. A cell cannot be stopped in the middle: **Stop** restarts Python itself, which every notebook, and any report still calculating, feels.',
        '**Save ▾** writes the notebook as a Jupyter notebook (.ipynb, with its outputs) or as a Python script with `# %%` cells; **File > Open** reads both, and a saved project keeps its notebooks. A notebook opened from a file runs nothing until you run it.',
        'In a report, each **Python code** block has **Edit**: the code becomes editable, **Run** runs it on its own (the table read as the code reads it) and shows its output, figures too, under the block, and **Reset** puts the report\'s code back; an edit lasts until the report is drawn again. **Notebook** sends a block to a notebook as a cell, and **Save ▾ > Open Script in Notebook** the report\'s whole script, a cell per result.',
      ]),

      h('h2', 'JSL to Python', 'jsl'),
      p('**Python > JSL to Python** (or a .jsl file dropped on the page) turns a JSL script, JMP\'s scripting language, into a Python script: the language and the work on data tables in pandas and numpy, and each analysis as this page\'s own Python for it, run on the open table, so its numbers are the report\'s. The notes list what did not convert, line by line, and a comment marks the place in the Python.'),
      ul([
        'Open the table the script works on first (File > Open reads .jmp files): an analysis on a table that is not open, or on columns it lacks, is left as a note.',
        'JMP\'s windows, dialogs and display boxes, its report objects (SendToReport, Dispatch), and Eval or Parse of text have no Python counterpart and do not convert.',
        '**Open in Notebook** puts the Python into a new notebook, a cell for each analysis; **Open the Reports Here** opens the analyses as reports of this page.',
      ]),

      h('h2', 'Saving your work', 'saving'),
      ul([
        '**File > Save Table** writes one table as JSON, with its modeling types, formats, value orders, formulas, column properties, scripts and row states; File > Open reads it back.',
        '**File > Save Project** writes every open table, every report (roles, options, filters) and every notebook into one JSON file; opening it rebuilds the reports and reopens the notebooks, in the groups they were in.',
        'A notebook\'s **Save ▾** writes it as a Jupyter notebook (.ipynb) or a Python script (.py).',
        '**Export** writes CSV, tab-separated text or Excel for other programs; a report\'s **Save ▾** writes its Python script, a standalone HTML copy or a Word document (.docx), or prints it.',
        'Nothing is kept by the page itself between visits: save a project before closing the tab.',
        '**Edit > Undo** (ctrl/⌘+Z in the grid) takes back edits, deleted rows and columns, sorting and row states, thirty steps deep.',
      ]),

      h('h2', 'Keyboard', 'keyboard'),
      el('table', null, el('tbody', null, ...[
        ['Grid', 'arrows move; Enter or F2 edits; typing replaces the cell; Tab moves right; Delete clears; ctrl/⌘+C and V copy and paste; ctrl/⌘+Z undo, shift for redo; ctrl/⌘+A selects all rows'],
        ['Menus', 'arrows move and open submenus; Enter chooses; Escape closes'],
        ['Tabs', 'left and right arrows, Home and End, along a group\'s tabs; ctrl/⌘+shift+left or right moves the tab; on the bar between two groups the arrows move it'],
        ['Dialogs', 'Enter is OK, Escape cancels; in a launch dialog Enter puts the selected columns in the first role that takes them; drag the title bar to move a dialog. A click beside a dialog leaves it open.'],
        ['Code', 'Shift+Enter runs a cell (or a report\'s edited code) and moves on; Ctrl/⌘+Enter runs it; Alt+Enter runs it and adds a cell; Tab and Shift+Tab indent and outdent; Ctrl/⌘+/ comments lines out and in; Escape, then Tab, leaves the editor'],
      ].map((r) => el('tr', null, el('td', null, el('strong', { text: r[0] })), el('td', { text: r[1] }))))),

      h('h2', 'The platforms', 'platforms'),
      p('Every analysis in the menus, with the statsmodels (and scipy) functions it uses.'),
      platformTable(),

      h('h2', 'Menu commands', 'commands'),
      p('The items of the menus that change or make tables rather than open a report.'),
      commandTable(),

      h('h2', 'The Python engine', 'engine'),
      p('Pyodide is CPython compiled to WebAssembly. The page starts it in a Web Worker as soon as it loads, with numpy, scipy, pandas, patsy and statsmodels, and this page\'s analysis package (resources/py/smui, plain Python that also runs outside the browser). The first visit downloads about 40 MB from the jsDelivr CDN, which the browser then keeps. Most predictive platforms (Bootstrap Forest, Boosted Tree, Partition\'s CART method, K Nearest Neighbors and the others under Predictive Modeling, Text Explorer) use scikit-learn, which is loaded the first time one of them runs; Partition\'s own decision tree, Uplift and Neural are this page\'s numpy and scipy code, written from JMP\'s documented methods. Model Screening\'s XGBoost and LightGBM methods load Pyodide\'s xgboost and lightgbm the first time one is ticked, and Text Explorer\'s Sentiment Analysis fetches the vaderSentiment package (MIT) from PyPI the first time it runs: one wheel, checked against the SHA-256 this page pins before it is installed.'),
      p('A table goes to the engine when an analysis needs it, and again when it has changed. Nothing is sent anywhere else: the files you open, the tables and the reports stay in this browser tab.'),
      el('div', { class: 'sm-engine-versions' }),

      h('h2', 'Differences from JMP', 'differences'),
      ul([
        'The numbers come from statsmodels and scipy. Where JMP has its own method (for example its Lack of Fit or its exact tests) the report says what is computed instead, and the Python shows it.',
        'JMP\'s scripting language (JSL) does not run here: **Python > JSL to Python** turns a script into Python, which the notebook runs; the reports\' Python scripts take the place of JMP\'s saved scripts.',
        'Where statsmodels has nothing like a JMP platform, the platform uses scikit-learn (forests, boosted trees, Partition\'s CART method, text exploration, Gaussian processes, partial least squares, normal mixtures, the learners) or this page\'s own numpy and scipy code written from JMP\'s documented methods (Partition\'s decision tree, Uplift, Neural), and its (i) text says where the method differs from JMP\'s.',
        'Bootstrap (from any report table\'s right-click menu) and the profiler\'s desirability and variable importance are computed with scipy.',
      ]),
      el('p', { class: 'sm-build', text: `Page build ${document.documentElement.dataset.build || ''}` }),
    );
    const upd = () => {
      const v = box.querySelector('.sm-engine-versions');
      const e = SM.engine;
      if (!v) return;
      v.replaceChildren(e.versions ? SM.report.kv(Object.entries(e.versions).map(([k, x]) => [k, String(x), 'text'])) : el('p', { class: 'sm-ob-note', text: `Engine: ${e.text}` }));
    };
    upd();
    SM.engine.on('status', upd);
  }

  function platformTable() {
    const rows = [];
    const menus = ['Analyze', 'Graph', 'DOE', 'Tables', 'Cols', 'Rows'];
    const all = SM.platforms.all().filter((p) => p.menu && !p.hidden).sort((a, b) => {
      const ma = menus.indexOf(a.menu.split('/')[0]), mb = menus.indexOf(b.menu.split('/')[0]);
      return ma - mb || a.menu.localeCompare(b.menu) || (a.order ?? 500) - (b.order ?? 500);
    });
    for (const p0 of all) {
      rows.push(el('tr', { id: `help-p-${p0.id}` },
        el('td', null, el('strong', { text: p0.label }), el('br'), el('span', { class: 'sm-ob-note', text: p0.menu.replace(/\//g, ' > ') })),
        el('td', null, p0.about || ''),
        el('td', null, ...(p0.uses || []).flatMap((u, i) => [i ? el('br') : null, el('code', { text: u })]))));
    }
    return el('table', { class: 'sm-platforms' }, el('thead', null, el('tr', null, el('th', { text: 'Platform' }), el('th', { text: 'What it does' }), el('th', { text: 'Backend' }))), el('tbody', null, ...rows));
  }

  function commandTable() {
    const menus = ['File', 'Edit', 'Tables', 'Rows', 'Cols', 'DOE', 'Analyze', 'Graph', 'Help'];
    const list = SM.commands.all().slice().sort((a, b) => menus.indexOf(a.menu.split('/')[0]) - menus.indexOf(b.menu.split('/')[0]) || a.menu.localeCompare(b.menu) || (a.order ?? 500) - (b.order ?? 500));
    return el('table', { class: 'sm-platforms' }, el('thead', null, el('tr', null, el('th', { text: 'Menu item' }), el('th', { text: 'What it does' }))),
      el('tbody', null, ...list.map((c) => el('tr', null,
        el('td', null, el('strong', { text: c.label.replace(/…$/, '') }), el('br'), el('span', { class: 'sm-ob-note', text: c.menu.replace(/\//g, ' > ') })),
        el('td', { text: c.about || '' })))));
  }

  SM.help = Object.freeze({ topics, render });
}(typeof self !== 'undefined' ? self : this));
