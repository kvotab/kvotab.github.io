/* ==========================================================================
   SMUI.HTML: COLUMN PROPERTIES (Column Info, Cols > Column Properties,
   Cols > Preselect Role)

   The editors of JMP's column properties that smui-table.js keeps:

     Missing Value Codes   stored values every analysis treats as missing
     Value Labels          text shown in place of a value
     Profit Matrix         the profit of each decision for each actual level
                           of a categorical response (and Undecided)

   SM.colprops.editors(table, column) gives them for Column Info (smui-app.js):
   { nodes, check(), apply() } -- nodes for its form grid, check() an error
   message or null, apply() writes what changed (after Column Info has
   recorded the table for Undo and changed the types). The same editors open
   one at a time from Cols > Column Properties. Cols > Preselect Role gives
   the selected columns the role a launch dialog puts them in.

   Everything is built with SM.util.el: text nodes only (a value label from
   a file is text, never markup).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el } = SM.util;
  const { isMissing } = SM.table;

  const infoSlot = (key) => (typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null);
  const labelEl = (text, info) => el('label', { class: 'smc-label' }, text, info ? infoSlot(info) : null);
  const toast = (text, opts) => SM.ui.toast(text, opts);
  const valueText = (c, v) => (SM.grid.valueText ? SM.grid.valueText(c, v) : String(v));
  const num = (s) => SM.table.toNumber(String(s).trim().replace(/^−/, '-').replace(',', '.'));

  /* ---- Missing Value Codes ------------------------------------------------ */
  // "999, -1" for a numeric column; "refused, n/a" (or quoted, "a, b") for a character one.
  function parseCodes(text, numeric) {
    const s = String(text || '').trim();
    if (!s) return { codes: [], bad: null };
    const parts = [];
    const re = /"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([^,;]+)/g;
    let m;
    while ((m = re.exec(s))) {
      const part = m[1] != null ? m[1].replace(/\\(.)/g, '$1') : m[2] != null ? m[2].replace(/\\(.)/g, '$1') : m[3].trim();
      if (m[3] != null && !part) continue;
      if (numeric && m[3] != null) parts.push(...part.split(/\s+/).filter(Boolean)); else parts.push(part);
    }
    const codes = [];
    for (const p of parts) {
      if (numeric) { const x = num(p); if (Number.isNaN(x)) return { codes, bad: p }; if (!codes.includes(x)) codes.push(x); }
      else if (p !== '' && !codes.includes(p)) codes.push(p);
    }
    return { codes, bad: null };
  }

  const codesText = (c) => (c.missingCodes || []).map((v) => (typeof v === 'number' ? valueText({ isNumeric: true, format: null }, v).replace(/^−/, '-') : (/[,;"]/.test(v) || v !== v.trim() ? JSON.stringify(v) : v))).join(', ');

  function missingEditor(t, c) {
    const input = el('input', { type: 'text', class: 'smc-codes', value: codesText(c), placeholder: c.isNumeric ? 'e.g. 999, -1' : 'e.g. refused, n/a', 'aria-label': `Missing value codes of ${c.name}`, spellcheck: 'false' });
    const note = el('span', { class: 'sm-ob-note smc-note' });
    const count = () => {
      const { codes, bad } = parseCodes(input.value, c.isNumeric);
      if (bad != null) { note.textContent = `“${bad}” is not a number`; return; }
      if (!codes.length) { note.textContent = 'none: every stored value is a value'; return; }
      const set = new Set(codes);
      let n = 0;
      for (let r = 0; r < t.nrows; r++) { const v = SM.table.storedOf(c, r); if (v != null && set.has(v)) n++; }
      note.textContent = `${n} cell${n === 1 ? '' : 's'} hold${n === 1 ? 's' : ''} ${codes.length > 1 ? 'these codes' : 'this code'}: missing to every analysis`;
    };
    input.addEventListener('input', count);
    count();
    const read = () => parseCodes(input.value, c.isNumeric);
    return {
      key: 'missing',
      nodes: [labelEl('Missing Value Codes', 'cols:missingcodes'), el('div', { class: 'smc-field' }, input, note)],
      check: () => { const { bad } = read(); return bad != null ? `Missing Value Codes: “${bad}” is not a number (separate the codes with commas)` : null; },
      apply: () => {
        // (the data type may have changed in Column Info: read the text again for the type it has now)
        const { codes } = parseCodes(input.value, c.isNumeric);
        const next = SM.table.normCodes(codes, c.isNumeric);
        const cur = c.missingCodes;
        if (JSON.stringify(next) === JSON.stringify(cur)) return false;
        t.setMissingCodes(c.id, next);
        return true;
      },
      focus: () => input.focus(),
    };
  }

  /* ---- Value Labels --------------------------------------------------------- */
  function labelsEditor(t, c) {
    const rows = [];         // { value, label } as typed
    const order = new Map(t.levels(c).map((v, i) => [String(v), i]));
    const start = SM.table.labelPairs(c).sort((a, b) => (order.get(String(a[0])) ?? 1e9) - (order.get(String(b[0])) ?? 1e9) || (c.isNumeric ? a[0] - b[0] : SM.table.collator.compare(String(a[0]), String(b[0]))));
    for (const [v, lab] of start) rows.push({ value: valueText(c, v).replace(/^−/, '-'), label: lab });
    const body = el('tbody');
    const count = el('span', { class: 'sm-ob-note' });
    const draw = (focusLast = false) => {
      body.replaceChildren(...rows.map((r, i) => {
        const vi = el('input', { type: 'text', class: 'smc-lv', value: r.value, 'aria-label': `Value ${i + 1}`, spellcheck: 'false' });
        const li = el('input', { type: 'text', class: 'smc-ll', value: r.label, 'aria-label': `Label of value ${i + 1}` });
        vi.addEventListener('input', () => { r.value = vi.value; });
        li.addEventListener('input', () => { r.label = li.value; const lab = rows.filter((x) => String(x.label).trim() && String(x.value).trim()).length; count.textContent = `${rows.length} value${rows.length === 1 ? '' : 's'}, ${lab ? `${lab} with a label` : 'none with a label yet'}`; });
        const x = el('button', { type: 'button', class: 'smt-x', 'aria-label': `Remove the label of ${r.value || `value ${i + 1}`}`, text: '×' });
        x.addEventListener('click', () => { rows.splice(i, 1); draw(); });
        return el('tr', null, el('td', null, vi), el('td', null, li), el('td', null, x));
      }));
      if (!rows.length) body.append(el('tr', null, el('td', { colspan: '3', class: 'sm-ob-note', text: 'No value labels: Add one, or Add Levels for a row per level.' })));
      const lab = rows.filter((r) => String(r.label).trim() && String(r.value).trim()).length;
      count.textContent = rows.length ? `${rows.length} value${rows.length === 1 ? '' : 's'}, ${lab ? `${lab} with a label` : 'none with a label yet'}` : '';
      if (focusLast) { const ins = body.querySelectorAll('input.smc-lv'); if (ins.length) ins[ins.length - 1].focus(); }
    };
    const btn = (label, fn) => { const b = el('button', { type: 'button', class: 'sm-btn small', text: label }); b.addEventListener('click', fn); return b; };
    const add = btn('Add', () => { rows.push({ value: '', label: '' }); draw(true); });
    const addLevels = btn('Add Levels', () => {
      const have = new Set(rows.map((r) => (c.isNumeric ? String(num(r.value)) : r.value)));
      let n = 0;
      for (const v of t.levels(c)) {
        if (have.has(String(v))) continue;
        if (n >= 500) break;
        rows.push({ value: valueText(c, v).replace(/^−/, '-'), label: '' });
        n++;
      }
      draw();
      if (!n) toast('Every level has a row already');
    });
    const clear = btn('Clear', () => { rows.length = 0; draw(); });
    const table = el('table', { class: 'sm-rt smc-labels' }, el('thead', null, el('tr', null, el('th', { class: 'sm-l', text: 'Value' }), el('th', { class: 'sm-l', text: 'Label' }), el('th', { text: '' }))), body);
    draw();
    // the labels as pairs of the column's type now, or an error
    const read = (numeric) => {
      const pairs = [];
      const seen = new Map();
      for (const r of rows) {
        const vt = String(r.value).trim(), lab = String(r.label);
        if (!vt && !lab.trim()) continue;
        if (!vt) return { error: `Value Labels: the label “${lab}” has no value` };
        if (!lab.trim()) continue;       // a value without a label: no label
        const v = numeric ? num(vt) : vt;
        if (numeric && Number.isNaN(v)) return { error: `Value Labels: “${vt}” is not a number` };
        const k = String(v);
        if (seen.has(k) && seen.get(k) !== lab) return { error: `Value Labels: ${vt} has two labels, “${seen.get(k)}” and “${lab}”` };
        seen.set(k, lab);
        pairs.push([v, lab]);
      }
      return { pairs };
    };
    return {
      key: 'labels',
      nodes: [labelEl('Value Labels', 'cols:valuelabels'), el('div', { class: 'smc-field smc-labelbox' }, el('div', { class: 'smc-scroll' }, table), el('div', { class: 'smc-bar' }, add, addLevels, clear, count))],
      check: () => read(c.isNumeric).error || null,
      apply: () => {
        const r = read(c.isNumeric);
        if (r.error) return false;
        const next = SM.table.normLabels(r.pairs, c.isNumeric);
        const same = JSON.stringify(SM.table.labelPairs({ valueLabels: next, isNumeric: c.isNumeric })) === JSON.stringify(SM.table.labelPairs(c));
        if (same) return false;
        t.setValueLabels(c.id, next);
        return true;
      },
      focus: () => { const i = body.querySelector('input'); if (i) i.focus(); else add.focus(); },
    };
  }

  /* ---- Profit Matrix ------------------------------------------------------------ */
  const MAX_LEVELS = 30;

  function profitEditor(t, c) {
    const levels = t.levels(c);
    const on = el('input', { type: 'checkbox' });
    on.checked = !!c.profitMatrix;
    const und = el('input', { type: 'checkbox' });
    und.checked = !!(c.profitMatrix && c.profitMatrix.decisions.length > c.profitMatrix.levels.length);
    const box = el('div', { class: 'smc-profit' });
    const note = el('span', { class: 'sm-ob-note' });
    let pm = SM.table.profitFor(levels, c.profitMatrix, und.checked);
    const inputs = [];          // [i][j]
    const lvText = (v) => (SM.grid.cellText ? SM.grid.cellText(c, v) : String(v));
    // the matrix as typed (what is not a number counts as 0), or the one kept
    const typed = () => (inputs.length ? { levels, decisions: inputs[0].length > levels.length ? levels.concat([SM.table.UNDECIDED]) : levels.slice(), matrix: inputs.map((r) => r.map((i) => { const x = num(i.value); return Number.isFinite(x) ? x : 0; })) } : pm);
    const draw = () => {
      // what was typed stays where it was, with Undecided on or off
      pm = SM.table.profitFor(levels, typed(), und.checked);
      inputs.length = 0;
      box.replaceChildren();
      if (!on.checked) return;
      const head = el('tr', null, el('th', { class: 'sm-l smc-corner', scope: 'col', text: 'Actual \\ Decision' }), ...pm.decisions.map((d, j) => el('th', { scope: 'col', text: j < levels.length ? lvText(d) : 'Undecided' })));
      const body = el('tbody');
      pm.levels.forEach((a, i) => {
        const row = [];
        const tr = el('tr', null, el('th', { class: 'sm-l', scope: 'row', text: lvText(a) }));
        pm.decisions.forEach((d, j) => {
          const inp = el('input', { type: 'text', inputmode: 'decimal', class: `smc-pv${i === j ? ' is-diag' : ''}`, value: String(pm.matrix[i][j]), 'aria-label': `Profit of deciding ${j < levels.length ? lvText(d) : 'Undecided'} when the actual level is ${lvText(a)}` });
          row.push(inp);
          tr.append(el('td', null, inp));
        });
        inputs.push(row);
        body.append(tr);
      });
      box.append(el('div', { class: 'smc-scroll' }, el('table', { class: 'sm-rt smc-matrix' }, el('thead', null, head), body)));
    };
    const avail = c.isCategorical && levels.length >= 2 && levels.length <= MAX_LEVELS;
    if (!avail) {
      on.disabled = true; und.disabled = true;
      note.textContent = !c.isCategorical ? 'for a nominal or ordinal response (make the column nominal or ordinal first)' : levels.length < 2 ? 'needs two or more levels' : `${levels.length} levels: a profit matrix takes at most ${MAX_LEVELS}`;
    }
    on.addEventListener('change', () => { draw(); });
    und.addEventListener('change', () => { draw(); });
    draw();
    const reset = el('button', { type: 'button', class: 'sm-btn small', text: 'Defaults' });
    reset.addEventListener('click', () => { inputs.length = 0; pm = SM.table.profitFor(levels, null, und.checked); draw(); });
    const read = () => {
      if (!on.checked || !avail) return { pm: null };
      const matrix = [];
      for (let i = 0; i < inputs.length; i++) {
        const r = [];
        for (let j = 0; j < inputs[i].length; j++) {
          const s = inputs[i][j].value.trim();
          const x = s === '' ? 0 : num(s);
          if (!Number.isFinite(x)) return { error: `Profit Matrix: “${s}” is not a number` };
          r.push(x);
        }
        matrix.push(r);
      }
      return { pm: { levels: levels.slice(), decisions: und.checked ? levels.concat([SM.table.UNDECIDED]) : levels.slice(), matrix } };
    };
    return {
      key: 'profit',
      nodes: [labelEl('Profit Matrix', 'cols:profitmatrix'), el('div', { class: 'smc-field' },
        el('div', { class: 'sm-inline smc-bar' }, el('label', { class: 'smt-check' }, on, 'Use a profit matrix'), el('label', { class: 'smt-check' }, und, 'Undecided decision'), avail ? reset : null, note), box)],
      check: () => read().error || null,
      apply: () => {
        const r = read();
        if (r.error) return false;
        const next = r.pm ? SM.table.normProfit(r.pm) : null;
        if (JSON.stringify(next) === JSON.stringify(c.profitMatrix)) return false;
        t.setProfitMatrix(c.id, next);
        return true;
      },
      focus: () => on.focus(),
    };
  }

  const EDITORS = { missing: missingEditor, labels: labelsEditor, profit: profitEditor };

  /* Column Info's part: all three. */
  function editors(t, c, which = ['missing', 'labels', 'profit']) {
    const list = which.map((k) => EDITORS[k](t, c));
    return {
      nodes: list.flatMap((e) => e.nodes),
      check: () => { for (const e of list) { const m = e.check(); if (m) return m; } return null; },
      apply: () => { let any = false; for (const e of list) if (e.apply()) any = true; return any; },
      list,
    };
  }

  /* Cols > Column Properties > one of them, in a dialog of its own. */
  const TITLES = { missing: 'Missing Value Codes', labels: 'Value Labels', profit: 'Profit Matrix' };
  const INFO = { missing: 'cols:missingcodes', labels: 'cols:valuelabels', profit: 'cols:profitmatrix' };
  function openOne(app, which, col) {
    const t = app.requireTable();
    if (!t) return null;
    const c = col || (app.selectedColumns().length === 1 ? app.selectedColumns()[0] : null);
    if (!c) { toast('Select one column (click its heading) for its column properties'); return null; }
    const ed = editors(t, c, [which]);
    const msg = el('div', { class: 'sm-launch-msg' });
    const dlg = SM.ui.dialog({
      title: `${TITLES[which]}: ${c.name}`, info: INFO[which], className: 'smc-dialog',
      body: el('div', null, el('div', { class: 'sm-form smc-form' }, ...ed.nodes), msg),
      buttons: [{ label: 'Cancel' }, { label: 'OK', primary: true, action: () => {
        const err = ed.check();
        if (err) { msg.textContent = err; return false; }
        if (app.record) app.record(t, TITLES[which]);
        if (!ed.apply() && app.undoStack && app.undoStack.length && app.undoStack[app.undoStack.length - 1].label === TITLES[which]) app.undoStack.pop();
        return true;
      } }],
    });
    requestAnimationFrame(() => ed.list[0].focus());
    return dlg;
  }

  /* ---- Cols > Preselect Role --------------------------------------------------- */
  function preselect(app, role) {
    const t = app.requireTable();
    if (!t) return;
    const cols = app.selectedColumns();
    if (!cols.length) { toast('Select the columns first (click their headings), then choose their role'); return; }
    if (app.record) app.record(t, 'Preselect Role');
    for (const c of cols) t.setPreselectRole(c.id, role);
    toast(role ? `${cols.map((c) => c.name).join(', ')}: preselected as ${role}; a launch dialog puts ${cols.length > 1 ? 'them' : 'it'} there` : `${cols.map((c) => c.name).join(', ')}: no preselected role`);
  }

  function preselectItems(app) {
    const sel = app.selectedColumns();
    const all = (r) => sel.length > 0 && sel.every((c) => (c.preselectRole || null) === r);
    return [...SM.table.ROLES.map((r) => ({ label: r, checked: all(r), disabled: !sel.length, action: () => preselect(app, r) })),
      { separator: true }, { label: 'None', checked: all(null), disabled: !sel.length, action: () => preselect(app, null) }];
  }

  /* ---- the menus -------------------------------------------------------------- */
  const hasTable = (app) => !!app.current;
  SM.commands.register({
    menu: 'Cols', label: 'Column Properties', order: 25, context: 'column', enabled: hasTable,
    about: 'Missing Value Codes, Value Labels and Profit Matrix of the selected column (also in Column Info)',
    submenu: (app, col) => ['missing', 'labels', 'profit'].map((k) => ({ label: `${TITLES[k]}…`, action: () => openOne(app, k, col) })),
  });
  SM.commands.register({
    menu: 'Cols', label: 'Preselect Role', order: 35, enabled: hasTable, submenu: (app) => preselectItems(app),
    about: 'The role (Y, X, Weight, Freq) the selected columns go into when a launch dialog opens',
  });

  /* ---- the (i) topics ------------------------------------------------------------ */
  SM.info.add({
    'cols:missingcodes': {
      kicker: 'Column Info', title: 'Missing Value Codes',
      lead: 'Stored values that every analysis treats as missing, such as 999 for "not answered". The cells keep their value: the grid shows it, greyed as a missing value, and the files keep it.',
      sections: [
        { heading: 'Typing them', list: ['Several codes are separated by commas: `999, -1`. A numeric column takes numbers; a character column takes texts, in quotes when a text has a comma in it: `"n/a", refused`.', 'Empty: no codes.'] },
        { heading: 'Where they are missing', text: 'Everywhere the table is used: the analyses and what goes to the Python engine, the graphs, formulas (`Col Stored Value(:x)` gives the stored value), the levels of a nominal column, Distribution, filters and By groups. Save Table, projects, Export CSV and Excel keep the codes as they are stored, and the Python code of a report, which reads the CSV, has a line that makes them missing again (`df["x"] = df["x"].mask(df["x"].isin([999]))`), so that it gives the report\'s numbers.' },
        { heading: 'Typing a code into a cell', text: 'A cell given a code keeps the code and is missing; the grid shows it greyed, and its heading line says it is a missing value code.' },
      ],
    },
    'cols:valuelabels': {
      kicker: 'Column Info', title: 'Value Labels',
      lead: 'Text shown in place of a value: 1 shown as Male, 2 as Female. The value is what is stored, compared, sorted and sent to the engine; the label is how the grid and the reports write it.',
      sections: [
        { heading: 'The editor', choices: [['Value', 'The stored value, as typed in the grid (a number for a numeric column).'], ['Label', 'The text shown for it; a row without a label is left out.'], ['Add', 'A new row.'], ['Add Levels', 'A row for each distinct value that has no label yet.'], ['Clear', 'Every row taken away: no labels.'], ['×', 'Takes that row away.']] },
        { heading: 'Where they show', text: 'In the grid (the value itself when you edit the cell, and in the cell\'s tooltip), and wherever the page writes a level: the levels of Distribution, Fit Y by X, Graph Builder\'s legends and axes, Tabulate, filters, By group titles and the like. The engine gets the values, so a level chosen in a dialog still matches; a level a report writes in Python (a model\'s term name, sex[1]) shows the value.' },
        { heading: 'Files', text: 'Save Table and projects keep them; CSV and Excel keep the values. A Stata file\'s value labels come in as this property, the column keeping its codes.' },
      ],
    },
    'cols:profitmatrix': {
      kicker: 'Column Info', title: 'Profit Matrix',
      lead: 'For a nominal or ordinal response: the profit (or, negative, the cost) of each decision for each actual level. Rows are the actual levels, columns the decisions; the diagonal holds the correct decisions.',
      sections: [
        { heading: 'The editor', choices: [['Use a profit matrix', 'On: the column has the property, with the values in the matrix. Off: it has none.'], ['Undecided decision', 'Adds a column for deciding nothing, with its own profit (or cost) for each actual level.'], ['Defaults', 'Puts back 1 for a correct decision, −1 for a wrong one and 0 for Undecided, which the matrix starts with.'], ['The cells', 'The profit of deciding the column\'s level when the actual level is the row\'s; an empty cell is 0.']] },
        { heading: 'Who uses it', text: 'The predictive platforms: with a profit matrix, their saved probabilities come with the expected profit of each decision and the most profitable one. A level added to the column later gets the defaults.' },
      ],
    },
    'cols:preselect': {
      kicker: 'Cols', title: 'Preselect Role',
      lead: 'Gives the selected columns a role, Y, X, Weight or Freq, that every launch dialog puts them in when it opens (when the role takes their modeling type). None takes it away. The Columns panel marks such a column with its role.',
    },
  });

  SM.colprops = Object.freeze({ editors, openOne, parseCodes, preselect });
}(typeof self !== 'undefined' ? self : this));
