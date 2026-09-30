/* ==========================================================================
   SMUI.HTML: JSL TO PYTHON

   A JSL script (JMP's scripting language) in, a runnable Python script out.
   The Python engine translates the language and the data-table work
   (smui/jsl.py, smui/jsl_python.py: jsl.convert). Each platform launch it
   maps to one of this page's analyses is then run here, out of sight, on
   the open table, and that report's own Python goes where the launch was:
   the same code the report shows, so the numbers are the report's. Its
   `df = pd.read_csv(...)` becomes the script's own table variable, so the
   analysis sees what the script did to the table before it.

   What did not convert is said in the notes, line by line (a click on the
   line number shows it in the JSL), and in a comment where it was. Open
   the Reports Here opens the analyses as reports of this page.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el } = SM.util;

  // A sample of our own, for the Students example (File > Examples).
  const SAMPLE = `// A JSL sample for the Students example table (File > Examples > Students).
Names Default To Here( 1 );
dt = Data Table( "Students" );
dt << New Column( "BMI", Numeric, "Continuous",
	Formula( :Name( "weight (kg)" ) / (:Name( "height (cm)" ) / 100) ^ 2 )
);
Distribution(
	Continuous Distribution( Column( :Name( "height (cm)" ) ) ),
	Nominal Distribution( Column( :sex ) )
);
Bivariate( Y( :Name( "weight (kg)" ) ), X( :Name( "height (cm)" ) ), Fit Line );
Oneway( Y( :Name( "height (cm)" ) ), X( :sex ), Means( 1 ), t Test( 1 ) );
Fit Model(
	Y( :Name( "weight (kg)" ) ),
	Effects( :Name( "height (cm)" ), :sex ),
	Personality( "Standard Least Squares" ),
	Run
);
tall = dt << Get Rows Where( :Name( "height (cm)" ) > 170 );
Show( N Items( tall ) );
New Window( "Notes", Text Box( "A window of JMP's own: not converted" ) );
`;

  const SEVERITY = { info: 'ℹ', warn: '⚠', error: '✖' };
  const short = (s, n = 70) => { const t = String(s).replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
  // An import line alone (a line that goes on after a ';' stays where it is: its code needs the lines above it).
  const IMPORT = /^(?:import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*|from\s+[\w.]+\s+import\s+(?:\([^)]*\)|[\w*]+(?:\s+as\s+\w+)?(?:\s*,\s*\w+(?:\s+as\s+\w+)?)*))\s*(?:#.*)?$/;

  /* A converted launch's spec on table t. The converter names the columns
     (roles, option scopes such as "height|qq", Fit Model's effects, the
     filter): the page's ids go in, as a project's are mapped. */
  function stepSpec(step, t) {
    const raw = { roles: step.roles || {}, options: { ...(step.options || {}) }, ...(step.extra || {}) };
    if (step.filter) raw.filter = step.filter;
    delete raw.options.__colNames;               // Fit Y by X records its columns itself
    const spec = t ? SM.specs.remap(raw, t, Object.fromEntries(t.columns.map((c) => [c.name, c.name]))) : raw;
    // entries that carry a column's id and its name (Graph Builder's zones): the name back
    const names = (v) => {
      if (Array.isArray(v)) v.forEach(names);
      else if (v && typeof v === 'object') {
        if (typeof v.id === 'string' && 'name' in v && t) { const c = t.col(v.id); if (c) v.name = c.name; }
        Object.values(v).forEach(names);
      }
    };
    names(spec.options);
    return spec;
  }

  /* The page's own Python for one launch: a report of it, run out of sight
     on the table, closed again. { imports, lines } or a reason it has none.
     The converter's specs name their columns (roles, option scopes such as
     "height|qq", Fit Model's effects, the filter): the page's ids go in. */
  async function analysisCode(app, step, script = '') {
    const P = SM.platforms.get(step.platform);
    if (!P) return { why: `this page has no analysis ${step.platform}` };
    const want = step.table ? String(step.table).toLowerCase() : null;
    let t = want ? app.tables.find((x) => x.name.toLowerCase() === want) : null;
    const used = [...new Set(Object.values(step.roles || {}).flat().filter(Boolean))];
    const has = (tab) => tab && used.every((n) => tab.col(n));
    let stand = null;
    if (!t && !want) {
      // a file the script opens that is not open here (the translation reads its CSV)
      const esc = (x) => String(x).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const before = script.slice(0, Math.max(0, script.indexOf(step.marker)));
      const reads = [...before.matchAll(new RegExp(`^[ \\t]*${esc(step.frame)}\\s*=\\s*pd\\.read_(?:csv|excel)\\("([^"]+?)\\.(?:csv|txt|xlsx?)"`, 'gm'))];
      if (reads.length) return { why: `it runs on the table "${reads[reads.length - 1][1]}", which is not open here: open it (File > Open reads .jmp files) and convert again`, warn: true };
      // a table the script makes (a subset, a new table): the page's code for the same columns of the current table
      if (has(app.current)) { t = app.current; stand = `${step.frame} is made by the script, so the code is this page's for the same columns of ${t.name}; choices it takes from the data (the bins of a histogram) come from ${t.name}` }
      else return { why: `it runs on ${step.frame}, a table the script makes${used.length ? `, and no open table has its columns (${used.map((n) => `"${n}"`).join(', ')})` : ''}`, warn: true };
    }
    if (!t && P.needsTable !== false) return { why: `it runs on the table "${step.table}", which is not open here: open it (File > Open reads .jmp files) and convert again`, warn: true };
    const missing = t ? used.filter((n) => !t.col(n)) : [];
    if (missing.length) {
      const made = (step.new_columns || []).filter((n) => missing.includes(n));
      const list = missing.map((m) => `"${m}"`).join(', ');
      return { why: made.length
        ? `it uses ${list}, which the script makes before this line: run the lines above in a notebook and send the table to the page (smui.new_table), or add the column${missing.length > 1 ? 's' : ''} to ${t.name}, then convert again`
        : `the table ${t.name} has no column ${list}`, warn: true };
    }
    const spec = stepSpec(step, t);
    const rep = new SM.report.Report(app, P, spec, t);
    let parts = [];
    let errors = [];
    try {
      await rep.run();
      parts = [...new Set(rep.pyCode)];
      errors = [...rep.body.querySelectorAll('.sm-ob-error')].map((e) => short(e.textContent, 160));
    } finally {
      rep.close();
    }
    if (errors.length && !parts.length) return { why: `the analysis stopped here: ${errors[0]}`, warn: true };
    if (!parts.length) return { why: `${P.label} ran no Python here (a graph the page draws itself)`, info: true };
    const imports = [];
    const lines = [];
    const frame = step.frame || 'df';
    for (const part of parts) {
      for (const line of part.split('\n')) {
        if (IMPORT.test(line)) { if (!imports.includes(line)) imports.push(line); continue; }
        // the head's comment on the CSV goes with the read line it names
        if (line.trim() === '# the table, as File > Export CSV writes it (an empty field is missing)') continue;
        // the rows the page's report left out (its row states, its filter) are not the script's: it picks its own rows
        if (/^\s*df = df\.drop\(index=\[[^\]]*\]\)\s*# the rows the report leaves out/.test(line)) continue;
        // a copy: the analysis's own changes to df (a date column made a number again) stay out of the script's table
        if (/^df = pd\.read_csv\(/.test(line)) { lines.push(step.where ? `df = ${frame}.loc[${step.where}].copy()` : `df = ${frame}.copy()`); continue; }
        lines.push(line);
      }
      lines.push('');
    }
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    const excluded = t && t.counts ? t.counts().excluded : 0;
    if (excluded && !stand) stand = `${t.name} has ${excluded} excluded row${excluded > 1 ? 's' : ''} in the page: the Python leaves out only the rows the script itself excludes`;
    return { imports, lines, label: P.label, table: t, spec, errors, stand };
  }

  /* The converter's script with each marker replaced by its analysis's code
     (indented as the marker is) and those analyses' imports moved up. */
  async function assemble(app, res, notes, onStep) {
    let py = res.python;
    const extra = [];
    const opened = [];
    for (const step of res.steps || []) {
      if (onStep) onStep(step);
      let got;
      try { got = await analysisCode(app, step, res.python); } catch (e) { got = { why: `the analysis failed: ${e.message}`, warn: true }; }
      const re = new RegExp(`^([ \\t]*)${step.marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[ \\t]*$`, 'm');
      const m = re.exec(py);
      const ind = m ? m[1] : '';
      let block;
      if (got.lines) {
        for (const i of got.imports) if (!extra.includes(i)) extra.push(i);
        block = [`# ---- ${short(step.jsl, 90)}   (line ${step.line}: ${got.label}, this page's code for it)`, ...got.lines];
        opened.push({ step, platform: SM.platforms.get(step.platform), table: got.table, spec: got.spec });
        if (got.stand) notes.push({ line: step.line, severity: 'info', text: `${short(step.jsl, 60)}: ${got.stand}.` });
        for (const e of got.errors || []) notes.push({ line: step.line, severity: 'warn', text: `${got.label}: ${e}` });
      } else {
        block = [`# NOT CONVERTED (line ${step.line}): ${short(step.jsl, 90)}`, `# ${SM.util.oneLine(got.why)}`];
        notes.push({ line: step.line, severity: got.info ? 'info' : 'warn', text: `${short(step.jsl, 60)}: ${got.why}.` });
      }
      const text = block.map((l) => (l ? ind + l : l)).join('\n');
      py = m ? py.slice(0, m.index) + text + py.slice(m.index + m[0].length) : `${py}\n${text}\n`;
    }
    if (extra.length) {
      // after the script's own imports (at its top), those it lacks
      const lines = py.split('\n');
      const have = new Set(lines.filter((l) => IMPORT.test(l)).map((l) => l.trim()));
      const add = extra.filter((i) => !have.has(i));
      if (add.length) {
        let at = 0;
        for (let i = 0; i < lines.length; i++) { if (IMPORT.test(lines[i])) at = i + 1; else if (lines[i].trim() && !lines[i].startsWith('#') && at) break; }
        lines.splice(at, 0, ...add);
        py = lines.join('\n');
      }
    }
    return { python: py, opened };
  }

  /* ---- the tab ----------------------------------------------------------------------------- */
  class Converter {
    constructor(app, { text = '', name = 'JSL to Python' } = {}) {
      this.app = app;
      this.name = name;
      this.opened = [];
      this.python = '';
      const btn = (text, title, fn, cls = '') => { const b = el('button', { type: 'button', class: `sm-btn small ${cls}`, text, title }); b.addEventListener('click', fn); return b; };
      this.statusEl = el('span', { class: 'sm-nb-status', role: 'status' });
      this.convertBtn = btn('▶ Convert', 'Convert the JSL to Python (Ctrl/⌘+Enter)', () => this.convert(), 'primary');
      this.fileInput = el('input', { type: 'file', accept: '.jsl,.txt', hidden: true });
      this.fileInput.addEventListener('change', async () => { const f = this.fileInput.files[0]; this.fileInput.value = ''; if (f) { this.jsl.value = await f.text(); this.convert(); } });
      this.nbBtn = btn('Open in Notebook', 'The Python as the cells of a new notebook, to run and change', () => this.toNotebook());
      this.reportsBtn = btn('Open the Reports Here', 'Open each converted analysis as a report of this page', () => this.openReports());
      const copy = btn('Copy Python', 'Copy the Python script', () => SM.report.copyText(this.out.value));
      const save = btn('Save .py', 'Save the Python script', () => SM.util.download(`${(this.name.replace(/[^\w.-]+/g, '_') || 'converted')}.py`, this.out.value, 'text/x-python'));
      this.nbBtn.disabled = this.reportsBtn.disabled = true;
      this.bar = el('div', { class: 'sm-nb-bar sm-reportbar' }, this.convertBtn, btn('Open .jsl…', 'Read a JSL script from a file', () => this.fileInput.click()),
        btn('Sample', 'A sample script of this page\'s, for the Students example table', () => this.sample()),
        el('span', { class: 'sm-jsl-sep', 'aria-hidden': 'true' }), this.nbBtn, copy, save, this.reportsBtn, el('span', { class: 'sm-spacer' }), this.statusEl, this.fileInput);
      if (typeof KvotInfo !== 'undefined') this.bar.append(KvotInfo.slot('nb:jsl'));
      this.jsl = SM.editor.create({ value: text, language: 'jsl', label: 'The JSL script', placeholder: 'Paste a JSL script here, open a .jsl file, or take the Sample. Then Convert.',
        onKey: (ev) => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey || ev.shiftKey)) { this.convert(); return true; } return false; } });
      this.out = SM.editor.create({ value: '', language: 'python', label: 'The Python script', placeholder: 'The Python comes here.' });
      this.notesEl = el('ol', { class: 'sm-jsl-notes' });
      this.notesHead = el('h3', { class: 'sm-jsl-h', text: 'Notes' });
      const col = (title, ...kids) => el('section', { class: 'sm-jsl-col' }, el('h3', { class: 'sm-jsl-h', text: title }), ...kids);
      // the notes under the JSL, beside the lines they name (the Python is long)
      this.body = el('div', { class: 'sm-jsl-body' },
        col('JSL', this.jsl.el, this.notesHead, this.notesEl),
        col('Python', this.out.el));
      this.el = el('div', { class: 'sm-nb sm-jsl' }, this.bar, el('div', { class: 'sm-nb-body' }, el('p', { class: 'sm-nb-lead sm-jsl-lead', text: 'The language and the data-table work become pandas and numpy; each analysis becomes this page\'s own Python for it, run on the open table, so its numbers are the report\'s. The notes say what did not convert.' }), this.body));
      this.notesHead.hidden = true;
      if (typeof KvotInfo !== 'undefined') KvotInfo.mount(this.bar);
    }

    sample() {
      this.jsl.value = SAMPLE;
      if (!this.app.tables.some((t) => t.name === 'Students')) this.app.openExample('students');
      const tab = this.app.tabs.find((t) => t.converter === this);
      if (tab) this.app.showTab(tab);
      this.convert();
    }

    status(text) { this.statusEl.textContent = text; }

    async convert() {
      const app = this.app;
      const text = this.jsl.value;
      if (!text.trim()) { this.status('Nothing to convert: paste a JSL script first.'); return null; }
      this.convertBtn.disabled = true;
      this.status('Converting…');
      try {
        const tables = app.tables.map((t) => ({ name: t.name, columns: t.columns.map((c) => ({ name: c.name, dataType: c.dataType, modelingType: c.modelingType })) }));
        let res;
        try {
          res = await SM.engine.call('jsl.convert', { text, tables, current: app.current ? app.current.name : null });
        } catch (e) {
          this.status('');
          this.showNotes([{ line: 0, severity: 'error', text: `The converter: ${e.message}` }]);
          return null;
        }
        const notes = [...(res.notes || [])];
        const done = await assemble(app, res, notes, (step) => this.status(`Line ${step.line}: running ${(SM.platforms.get(step.platform) || {}).label || step.platform} for its code…`));
        this.python = done.python;
        this.opened = done.opened;
        this.out.value = done.python;
        this.showNotes(notes.sort((a, b) => (a.line || 0) - (b.line || 0)));
        this.nbBtn.disabled = !done.python.trim();
        this.reportsBtn.disabled = !done.opened.length;
        const n = notes.filter((x) => x.severity !== 'info').length;
        this.status(res.ok === false ? 'The script could not be read: see the notes' : `Converted${n ? `, with ${n} note${n > 1 ? 's' : ''} on what did not convert` : ''}${done.opened.length ? `; ${done.opened.length} analys${done.opened.length > 1 ? 'es' : 'is'} with this page's code` : ''}`);
        return { python: done.python, notes, steps: res.steps || [] };
      } finally {
        this.convertBtn.disabled = false;
      }
    }

    showNotes(notes) {
      this.notesHead.hidden = !notes.length;
      this.notesHead.textContent = `Notes (${notes.length})`;
      this.notesEl.replaceChildren(...notes.map((n) => {
        const li = el('li', { class: `sm-jsl-note is-${n.severity || 'info'}` }, el('span', { class: 'sm-jsl-sev', 'aria-label': n.severity || 'info', text: SEVERITY[n.severity] || SEVERITY.info }));
        if (n.line) {
          const b = el('button', { type: 'button', class: 'sm-jsl-line', text: `line ${n.line}`, title: 'Show the line in the JSL' });
          b.addEventListener('click', () => this.showLine(n.line));
          li.append(b);
        }
        li.append(el('span', { class: 'sm-jsl-text', text: n.text }));
        return li;
      }));
    }

    showLine(line) {
      const ta = this.jsl.ta, v = ta.value;
      let start = 0;
      for (let i = 1; i < line && start >= 0; i++) start = v.indexOf('\n', start) + 1 || -1;
      if (start < 0) return;
      let end = v.indexOf('\n', start);
      if (end < 0) end = v.length;
      ta.focus();
      ta.setSelectionRange(start, end);
      const ln = this.jsl.hl.querySelectorAll('.ln')[line - 1];
      if (ln) ln.scrollIntoView({ block: 'center' });
    }

    // cells: what comes before each analysis, and each analysis
    toNotebook() {
      const py = this.out.value;
      const cells = [{ type: 'markdown', source: `# ${this.name}\nConverted from JSL. The notes on what did not convert are in the converter's tab, and as comments in the code.` }];
      let cur = [];
      for (const line of py.split('\n')) {
        if (/^# ---- .*\(line \d+: /.test(line) && cur.some((l) => l.trim())) { cells.push({ type: 'code', source: cur.join('\n').trim() }); cur = []; }
        cur.push(line);
      }
      if (cur.some((l) => l.trim())) cells.push({ type: 'code', source: cur.join('\n').trim() });
      SM.notebook.open(this.app, { name: this.name === 'JSL to Python' ? 'From JSL' : this.name, cells });
    }

    openReports() {
      for (const o of this.opened) this.app.openReport(o.platform, o.spec, o.table);
    }
  }

  function open(app, init = {}) {
    const existing = !init.text && app.tabs.find((t) => t.converter);
    if (existing) { app.showTab(existing); return existing.converter; }
    const c = new Converter(app, init);
    const tab = app._addTab({ kind: 'jsl', title: init.name || 'JSL to Python', view: c.el });
    tab.converter = c;
    app.showTab(tab);
    requestAnimationFrame(() => c.jsl.focus());
    if (init.text) c.convert();
    return c;
  }

  async function openFile(app, file) {
    return open(app, { text: await file.text(), name: file.name.replace(/\.[^.]+$/, '') });
  }

  const topics = {
    'nb:jsl': {
      kicker: 'Python', title: 'JSL to Python',
      lead: 'A JSL script (JMP\'s scripting language) in, a Python script out: pandas and numpy for the language and the work on data tables, and for each analysis this page\'s own Python for it, run on the open table.',
      sections: [
        { heading: 'What converts', list: ['Variables, arithmetic, strings, lists, associative arrays and matrices; If, For, While, For Each, Match, Try; functions. JSL counts from 1 and Python from 0: the subscripts are turned.', 'Data tables: Open, New Table, New Column with values or a formula (made vectorised: If becomes np.where, Col Mean a group transform), row selections, Subset, Sort, Summary, Stack, Split, Join, Concatenate, Save.', 'The analyses this page has (Distribution, Fit Y by X, Fit Model, Multivariate, Principal Components and others): each becomes the code its report shows, run here on the table the script names, so the numbers match the report. Open the Reports Here opens them as reports.'] },
        { heading: 'What does not', list: ['Windows, dialogs and display boxes (New Window, Outline Box, Button Box), report objects and SendToReport, Eval and Parse of text, Include: JMP\'s own; each is a note and a comment where it was.', 'An analysis on a table that is not open here, or on columns the table lacks (made by the script before that line): open the table, or add the columns, and convert again.'] },
        { heading: 'Line numbers', text: 'Each note names its line in the JSL; a click on it shows the line. Comments in the Python name the JSL lines they came from.' },
      ],
      more: { label: 'JSL to Python', id: 'help-jsl' },
    },
  };
  if (SM.info) SM.info.add(topics);

  SM.whenApp(() => {
    if (!SM.commands) return;
    SM.commands.register({ menu: 'Python', order: 110, label: 'JSL to Python…', key: '.jsl', about: 'A JSL script as a Python script: the language, the data-table work, and the analyses as this page\'s code', action: (a) => open(a) });
  });

  SM.jsl = Object.freeze({ open, openFile, assemble, analysisCode, stepSpec, Converter, SAMPLE });
}(typeof self !== 'undefined' ? self : this));
