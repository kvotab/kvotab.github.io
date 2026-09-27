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
      sections: [{ heading: 'The red triangle', text: 'Rename the table, edit its notes, save it as this page\'s JSON (keeps modeling types, value orders, formulas and row states) or export CSV or Excel.' }],
      more: { label: 'Data tables', id: 'help-tables' },
    },
    'panel:columns': {
      kicker: 'Panel', title: 'Columns',
      lead: 'Every column with its modeling type, which decides how an analysis treats it.',
      sections: [
        { heading: 'Modeling types', choices: [['Continuous (blue triangle)', 'Numbers on a scale: means, regression, histograms.'], ['Ordinal (green bars)', 'Ordered categories: levels in value order; an ordinal response gets an ordinal logistic fit.'], ['Nominal (red bars)', 'Unordered categories: frequencies, contingency tables, dummy coding in models.']] },
        { heading: 'Using the list', list: ['Click the icon to change the modeling type.', 'Click a name to select the column (shift and ctrl/⌘ add); a launch dialog starts with the selected columns in its first role.', 'Drag names to reorder the columns.', 'Double click for Column Info; right click for the column menu.'] },
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
    'cols:new': { kicker: 'Cols', title: 'New Column', lead: 'A column of numbers or text, empty, constant, a sequence or random values. A formula column (when the formula editor is loaded) recalculates when the columns it uses change.', more: { label: 'Formulas', id: 'help-formulas' } },
    'cols:info': {
      kicker: 'Cols', title: 'Column Info',
      lead: 'Name, data type, modeling type, display format, value order, notes and the label role of one column.',
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
          ['Levels', 'Click a level to keep its rows; ctrl/⌘ or shift adds more levels (a row matches any of them). Click it again to let every level through.'],
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
          ['Levels', 'Click a level to keep its rows; ctrl/⌘ or shift adds more levels. Click it again to let every level through.'],
          ['from, to', 'The range of a continuous column: type a lower and an upper limit; an empty box is no limit.'],
          ['remove, Clear', 'remove takes one column out of the filter, Clear all of them.'],
        ] },
        { heading: 'Several filters', text: 'A row must match every filter column. Within one categorical column, ctrl/⌘ or shift adds levels (a row matches any of them).' },
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
        'Open a table: drop a CSV, tab-separated or Excel file on the page, use **File > Open**, pick one of the simulated examples, or load a statsmodels dataset (**File > statsmodels Datasets**).',
        'Check the modeling types in the Columns panel: a number that is really a category (a subgroup, a code) should be ordinal or nominal.',
        'Choose an analysis from **Analyze** or **Graph**, put columns into the roles and press OK. The report opens in its own tab.',
        'Open the red triangles (▼ in red) for more: tests, fits, saved columns. Click the grey triangles to close outlines you do not need.',
        'Select points or bars: the rows are selected in the table and in every other graph. Exclude them (**Rows > Exclude/Unexclude**) and press **Redo**, or turn on **Automatic Recalc**.',
        'Each result has its **Python code**: what statsmodels was asked and how. **Save ▾ > Save Python Script** writes all of it as one script that runs on a CSV export of the table.',
      ]),

      h('h2', 'Data tables', 'tables'),
      p('A table is columns of equal length. A column is **numeric** or **character** (its data type) and **continuous**, **ordinal** or **nominal** (its modeling type). Missing numbers show as a dot, missing text as an empty cell.'),
      ul([
        'Edit a cell by typing or double clicking; Enter moves down, Tab to the right, Escape cancels. Delete clears the cell.',
        'Click row numbers to select rows (shift for a range, ctrl/⌘ to add); drag down the row numbers to select a block. Click a column heading to select the column.',
        'ctrl/⌘+C copies the selected rows, or the cell, as tab-separated text; ctrl/⌘+V pastes at the cursor, adding rows as needed.',
        'Right click a heading for the column menu (Column Info, modeling type, sort), a row number for the row states.',
        'File > Save Table keeps everything (types, formats, value order, formulas, row states) in a JSON file this page opens again. File > Save Project saves all tables with their reports.',
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
        'The dialog lists the columns with their modeling types. Select some and press a role\'s button, drag them onto a role, or double click a column for the first role that takes it.',
        '**Y** is the response, **X** the factor or regressor; **Weight** and **Freq** are numeric; **By** repeats the analysis for each level.',
        'Remove takes the selected columns out of their roles; Recall fills in the last launch of the platform, matched by column name.',
        'Right click a column in the dialog to change its modeling type there.',
        'The (i) in a dialog\'s title bar explains the analysis and what each role, option and field is for. Drag the title bar to move the dialog.',
      ]),

      h('h2', 'Reports', 'reports'),
      ul([
        'An outline box has a grey disclosure triangle (open or close it) and, where it has options, a red triangle.',
        'Report tables sort by a click on a heading; right click for **Copy Table** or **Make into Data Table**.',
        'p-values below 0.0001 show as <.0001; an asterisk and red marks those below α (0.05 unless set).',
        '**Redo ▾** runs the analysis again (after exclusions or edits), relaunches the dialog, or turns on Automatic Recalc.',
        '**Local Data Filter** (in the top red triangle) narrows one report to the rows that match chosen levels or ranges, without touching the table.',
        '**Save ▾** writes the Python script, or the report as a standalone HTML file or a Word document with its graphs as images; **Print…** prints that document, without the page around it. The browser\'s own Print prints the report in view, graphs wider than the paper scaled to fit.',
        'Graphs: click a point or bar to select its rows (shift adds), drag a rectangle to select several; double click to clear. The toolbar above a graph zooms, pans and saves it as PNG.',
      ]),

      h('h2', 'Saving your work', 'saving'),
      ul([
        '**File > Save Table** writes one table as JSON, with its modeling types, formats, value orders, formulas, spec limits and row states; File > Open reads it back.',
        '**File > Save Project** writes every open table and every report (roles, options, filters) into one JSON file; opening it rebuilds the reports.',
        '**Export** writes CSV, tab-separated text or Excel for other programs; a report\'s **Save ▾** writes its Python script, a standalone HTML copy or a Word document (.docx), or prints it.',
        'Nothing is kept by the page itself between visits: save a project before closing the tab.',
        '**Edit > Undo** (ctrl/⌘+Z in the grid) takes back edits, deleted rows and columns, sorting and row states, thirty steps deep.',
      ]),

      h('h2', 'Keyboard', 'keyboard'),
      el('table', null, el('tbody', null, ...[
        ['Grid', 'arrows move; Enter or F2 edits; typing replaces the cell; Tab moves right; Delete clears; ctrl/⌘+C and V copy and paste; ctrl/⌘+Z undo, shift for redo; ctrl/⌘+A selects all rows'],
        ['Menus', 'arrows move and open submenus; Enter chooses; Escape closes'],
        ['Tabs', 'left and right arrows, Home and End'],
        ['Dialogs', 'Enter is OK, Escape cancels; in a launch dialog Enter puts the selected columns in the first role that takes them; drag the title bar to move a dialog'],
      ].map((r) => el('tr', null, el('td', null, el('strong', { text: r[0] })), el('td', { text: r[1] }))))),

      h('h2', 'The platforms', 'platforms'),
      p('Every analysis in the menus, with the statsmodels (and scipy) functions it uses.'),
      platformTable(),

      h('h2', 'Menu commands', 'commands'),
      p('The items of the menus that change or make tables rather than open a report.'),
      commandTable(),

      h('h2', 'The Python engine', 'engine'),
      p('Pyodide is CPython compiled to WebAssembly. The page starts it in a Web Worker as soon as it loads, with numpy, scipy, pandas, patsy and statsmodels, and this page\'s analysis package (resources/py/smui, plain Python that also runs outside the browser). The first visit downloads about 40 MB from the jsDelivr CDN, which the browser then keeps. The predictive platforms (Partition, Bootstrap Forest, Neural and the others under Predictive Modeling, Text Explorer) use scikit-learn, which is loaded the first time one of them runs.'),
      p('A table goes to the engine when an analysis needs it, and again when it has changed. Nothing is sent anywhere else: the files you open, the tables and the reports stay in this browser tab.'),
      el('div', { class: 'sm-engine-versions' }),

      h('h2', 'Differences from JMP', 'differences'),
      ul([
        'The numbers come from statsmodels and scipy. Where JMP has its own method (for example its Lack of Fit or its exact tests) the report says what is computed instead, and the Python shows it.',
        'JMP\'s scripting language (JSL) has no counterpart; the Python scripts take its place.',
        'Where statsmodels has nothing like a JMP platform (partition trees, forests, boosted trees, neural networks, text exploration, Gaussian processes, partial least squares, normal mixtures), the platform uses scikit-learn, and its (i) text says where scikit-learn\'s method differs from JMP\'s.',
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
