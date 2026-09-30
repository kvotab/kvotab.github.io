/* ==========================================================================
   SMUI.HTML: THE PYTHON NOTEBOOK

   A tab of cells, as Jupyter has them. Code cells run in the page's Python
   engine (smui/notebook.py in the worker), each notebook in a namespace of
   its own; text cells are Markdown. A cell's outputs (what it prints, the
   value of its last line, tables, figures, errors) come back in order and
   are drawn under it. The open tables are in the engine already
   (smui.table("Name")), and each is written as the CSV file the reports'
   code reads, so a report's code runs here as it is.

   Notebooks open and save as Jupyter notebooks (.ipynb) and as Python
   scripts with # %% cells (.py), and a project keeps them. The reports'
   code blocks come here (Notebook, and Save > Open Script in Notebook) or
   run where they are (Edit): exec() and renderOutputs() are theirs too.

   Output HTML (pandas tables, statsmodels summaries), from a cell or from
   a file someone sent, goes through kvotSanitizeHtml; images are shown as
   <img> (an SVG in an <img> runs nothing).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, uid } = SM.util;

  const PLOTLY = 'application/vnd.plotly.v1+json';
  const notebooks = [];
  let lastUsed = null;          // the notebook code blocks are sent to
  let counter = 0;

  const lines = (s) => { const a = String(s).split('\n'); return a.map((l, i) => (i < a.length - 1 ? `${l}\n` : l)).filter((l) => l !== ''); };
  const joined = (v) => (Array.isArray(v) ? v.join('') : String(v ?? ''));

  /* ---- outputs --------------------------------------------------------------------- */
  function whenPlotly(fn) {
    if (typeof Plotly !== 'undefined') { fn(); return; }
    const tag = document.querySelector('script[src*="plotly"]');
    if (tag) tag.addEventListener('load', () => fn(), { once: true });
  }

  function plotlyEl(fig) {
    const box = el('div', { class: 'sm-nb-plotly' });
    const draw = () => {
      if (!box.isConnected) { requestAnimationFrame(draw); return; }
      try {
        Plotly.newPlot(box, fig.data || [], { autosize: true, ...(fig.layout || {}) }, { responsive: true, displaylogo: false, ...(fig.config || {}) });
      } catch (e) { box.replaceChildren(el('pre', { class: 'sm-nb-stream stderr', text: `The figure could not be drawn: ${e.message}` })); }
    };
    whenPlotly(() => requestAnimationFrame(draw));
    return box;
  }

  function imageEl(data, meta) {
    const alt = joined(data['text/plain'] || 'figure');
    if (data['image/svg+xml']) return el('img', { class: 'sm-nb-img', alt, src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(joined(data['image/svg+xml']))}` });
    const img = el('img', { class: 'sm-nb-img', alt, src: `data:image/png;base64,${joined(data['image/png']).replace(/\s+/g, '')}` });
    const w = meta && meta['image/png'] && meta['image/png'].width;
    if (w) img.width = w;
    return img;
  }

  function outputEl(o) {
    if (o.type === 'stream') return el('pre', { class: `sm-nb-stream ${o.name === 'stderr' ? 'stderr' : 'stdout'}`, text: o.text });
    if (o.type === 'error') {
      const text = (o.traceback && o.traceback.length ? o.traceback.join('\n') : `${o.ename}: ${o.evalue}`).replace(/\x1b\[[0-9;]*m/g, '');   // Jupyter's colour codes
      return el('pre', { class: 'sm-nb-error', role: 'alert', text });
    }
    const d = o.data || {};
    if (d[PLOTLY]) return plotlyEl(d[PLOTLY]);
    if (d['image/svg+xml'] || d['image/png']) return imageEl(d, o.metadata);
    if (d['text/html'] && typeof kvotSanitizeHtml === 'function') {
      const box = el('div', { class: 'sm-nb-html' });
      box.append(kvotSanitizeHtml(joined(d['text/html'])));
      return box;
    }
    if (d['text/markdown']) return el('div', { class: 'sm-nb-md' }, markdown(joined(d['text/markdown'])));
    return el('pre', { class: 'sm-nb-stream result', text: joined(d['text/plain']) });
  }

  function renderOutputs(box, outputs) {
    box.replaceChildren(...(outputs || []).map(outputEl));
    box.hidden = !box.childNodes.length;
  }

  /* ---- Markdown, for text cells --------------------------------------------------------
     Built as elements, not as HTML text: headings, paragraphs, lists,
     block quotes, code, rules, tables, **bold**, *italic*, `code` and
     links (http and https only). */
  function inline(text) {
    const out = [];
    const re = /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\s][^*]*)\*|\b_([^_]+)_\b|\[([^\]]+)\]\(([^)\s]+)\)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(document.createTextNode(text.slice(last, m.index)));
      if (m[1]) out.push(el('code', { text: m[1] }));
      else if (m[2] || m[3]) out.push(el('strong', null, ...inline(m[2] || m[3])));
      else if (m[4] || m[5]) out.push(el('em', null, ...inline(m[4] || m[5])));
      else {
        const href = typeof kvotSafeHttpUrl === 'function' ? kvotSafeHttpUrl(m[7]) : null;
        out.push(href ? el('a', { href, target: '_blank', rel: 'noopener noreferrer', text: m[6] }) : document.createTextNode(m[6]));
      }
      last = re.lastIndex;
    }
    if (last < text.length) out.push(document.createTextNode(text.slice(last)));
    return out;
  }

  function markdown(src) {
    const frag = document.createDocumentFragment();
    const ls = String(src).replace(/\r\n?/g, '\n').split('\n');
    const para = [];
    const flush = () => { if (para.length) { frag.append(el('p', null, ...inline(para.join(' ')))); para.length = 0; } };
    const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    for (let i = 0; i < ls.length; i++) {
      const l = ls[i];
      let m;
      if (/^\s*(```|~~~)/.test(l)) {
        flush();
        const fence = /^\s*(```|~~~)/.exec(l)[1], buf = [];
        for (i++; i < ls.length && !ls[i].trim().startsWith(fence); i++) buf.push(ls[i]);
        frag.append(el('pre', null, el('code', { text: buf.join('\n') })));
      } else if ((m = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(l))) {
        flush();
        frag.append(el(`h${m[1].length}`, null, ...inline(m[2])));
      } else if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(l)) {
        flush();
        frag.append(el('hr'));
      } else if (/^\s*>/.test(l)) {
        flush();
        const buf = [];
        for (; i < ls.length && /^\s*>/.test(ls[i]); i++) buf.push(ls[i].replace(/^\s*>\s?/, ''));
        i--;
        frag.append(el('blockquote', null, markdown(buf.join('\n'))));
      } else if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
        flush();
        const ordered = /^\s*\d/.test(l);
        const list = el(ordered ? 'ol' : 'ul');
        for (; i < ls.length && /^\s*([-*+]|\d+[.)])\s+/.test(ls[i]); i++) list.append(el('li', null, ...inline(ls[i].replace(/^\s*([-*+]|\d+[.)])\s+/, ''))));
        i--;
        frag.append(list);
      } else if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < ls.length && /^\s*\|?\s*:?-{3,}/.test(ls[i + 1])) {
        flush();
        const t = el('table');
        t.append(el('thead', null, el('tr', null, ...cells(l).map((c) => el('th', null, ...inline(c))))));
        const body = el('tbody');
        for (i += 2; i < ls.length && /^\s*\|.*\|\s*$/.test(ls[i]); i++) body.append(el('tr', null, ...cells(ls[i]).map((c) => el('td', null, ...inline(c)))));
        i--;
        t.append(body);
        frag.append(t);
      } else if (!l.trim()) flush();
      else para.push(l.trim());
    }
    flush();
    return frag;
  }

  /* ---- running code ------------------------------------------------------------------- */
  // A few IPython lines that notebooks carry: %pip install goes to micropip,
  // %matplotlib goes (figures show under the cell anyway); the other
  // magics are turned into comments. Each line stays a line, so a
  // traceback's line numbers still fit.
  const MAGIC = /^(\s*)(%%?|!)\s*(pip|matplotlib|time|timeit|load_ext|config|env|who|whos|reset|ls|cd|pwd|capture)\b(.*)$/;
  function magics(code) {
    return String(code).split('\n').map((line) => {
      const m = MAGIC.exec(line);
      if (!m) return line;
      const [, ind, , what, rest] = m;
      if (what === 'pip' && /^\s*install\b/.test(rest)) {
        const pkgs = rest.replace(/^\s*install\b/, '').split(/\s+/).filter((p) => p && !p.startsWith('-'));
        return `${ind}import micropip; await micropip.install(${JSON.stringify(pkgs)})`;
      }
      if (what === 'matplotlib') return `${ind}pass  # ${line.trim()}: figures show under the cell`;
      if (what === 'time' && m[2] === '%' && rest.trim()) return `${ind}${rest.trim()}  # %time: run, not timed, here`;
      return `${ind}pass  # ${line.trim()}: IPython's magics do not run here`;
    }).join('\n');
  }

  /* Run code in the namespace nb, with the page's tables. Tables the code
     sends back (smui.new_table) are added to the page. */
  async function exec(nb, code, { label = 'cell', fresh = false } = {}) {
    const app = SM.app;
    const res = await SM.engine.runCell(nb, magics(code), { tables: app ? app.tables : [], current: app ? app.current : null, label, fresh });
    addTables(res.tables, label);
    return res;
  }

  function addTables(list, from) {
    for (const tj of list || []) {
      const t = new SM.Table({ name: SM.app.uniqueTableName(tj.name), source: `made in ${from}`, columns: tj.columns.map((c) => ({ ...c, values: c.values.map((v) => (v == null && c.dataType === 'numeric' ? NaN : v)) })) });
      SM.app.addTable(t, { show: false });
      SM.ui.toast(`Made the table ${t.name}: ${t.nrows} rows × ${t.columns.length} columns (its tab is on the right)`);
    }
  }

  const stopped = (e) => /^stopped$/.test(e && e.message);
  const errorOutput = (e) => ({ type: 'error', ename: 'Error', evalue: e.message, traceback: [stopped(e) ? 'Stopped: Python was restarted.' : `The engine: ${e.message}`] });

  /* ---- a cell --------------------------------------------------------------------------- */
  class Cell {
    constructor(nb, { type = 'code', source = '', outputs = [], count = null } = {}) {
      this.nb = nb;
      this.id = uid('cell');
      this.type = type === 'markdown' ? 'markdown' : 'code';
      this.outputs = outputs || [];
      this.count = count;
      this.editing = this.type === 'code' || !source;
      this.editor = SM.editor.create({ value: source, language: this.type === 'code' ? 'python' : 'markdown', label: this.type === 'code' ? 'Python code' : 'Text (Markdown)', onKey: (ev) => this._key(ev) });
      this.editor.on('change', () => nb.touch());
      this.countEl = el('span', { class: 'sm-nb-count' });
      this.runBtn = el('button', { type: 'button', class: 'sm-nb-run', 'aria-label': 'Run this cell (Shift+Enter)', title: 'Run (Shift+Enter)', text: '▶' });
      this.runBtn.addEventListener('click', () => nb.run(this));
      this.md = el('div', { class: 'sm-nb-md', tabindex: '0', title: 'Double click to edit' });
      this.md.addEventListener('dblclick', () => this.edit());
      this.md.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); this.edit(); } });
      this.out = el('div', { class: 'sm-nb-out', 'aria-live': 'polite' });
      const tool = (text, label, fn) => { const b = el('button', { type: 'button', class: 'sm-nb-tool', 'aria-label': label, title: label, text }); b.addEventListener('click', fn); return b; };
      this.kindBtn = tool(this.type === 'code' ? 'Text' : 'Code', 'Make this a text cell or a code cell', () => nb.retype(this));
      this.tools = el('div', { class: 'sm-nb-tools' },
        tool('↑', 'Move up', () => nb.move(this, -1)), tool('↓', 'Move down', () => nb.move(this, 1)),
        this.kindBtn, tool('+', 'Add a code cell below', () => nb.add('code', nb.cells.indexOf(this) + 1).focus()),
        tool('✕', 'Delete this cell', () => nb.remove(this)));
      this.el = el('section', { class: `sm-nb-cell is-${this.type}`, dataset: { cell: this.id } },
        el('div', { class: 'sm-nb-gutter' }, this.runBtn, this.countEl),
        el('div', { class: 'sm-nb-main' }, this.editor.el, this.md, this.out),
        this.tools);
      this.el.addEventListener('focusin', () => nb.activate(this));
      this.draw();
    }

    get source() { return this.editor.value; }

    _key(ev) {
      if (ev.key !== 'Enter' || !(ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.altKey)) return false;
      const nb = this.nb;
      if (ev.altKey) { nb.run(this); nb.add('code', nb.cells.indexOf(this) + 1).focus(); return true; }
      nb.run(this);
      if (ev.shiftKey) nb.next(this);
      return true;
    }

    edit() { if (this.type !== 'markdown') return; this.editing = true; this.draw(); this.editor.focus(); }

    focus() { if (this.type === 'markdown' && !this.editing) this.md.focus(); else this.editor.focus(); }

    draw() {
      const md = this.type === 'markdown';
      this.el.classList.toggle('is-code', !md);
      this.el.classList.toggle('is-markdown', md);
      this.editor.el.hidden = md && !this.editing;
      this.md.hidden = !md || this.editing;
      if (md && !this.editing) {
        this.md.replaceChildren(this.source.trim() ? markdown(this.source) : el('p', { class: 'sm-nb-empty', text: 'Empty text: double click to write.' }));
      }
      this.runBtn.hidden = md && !this.editing;
      this.countEl.textContent = md ? '' : this.running ? '[*]' : `[${this.count ?? ' '}]`;
      renderOutputs(this.out, md ? [] : this.outputs);
      this.kindBtn.textContent = md ? 'Code' : 'Text';
    }

    toJSON() { return { type: this.type, source: this.source, outputs: this.type === 'code' ? this.outputs : [], count: this.count }; }
  }

  /* ---- a notebook ------------------------------------------------------------------------ */
  class Notebook {
    constructor(app, { name, cells } = {}) {
      this.app = app;
      this.id = uid('nb');
      this.name = name || `Notebook ${++counter}`;
      this.cells = [];
      this.chain = Promise.resolve();
      this.running = 0;
      this.dirty = false;
      this.restarts = SM.engine.restarts;
      this.active = null;
      this.statusEl = el('span', { class: 'sm-nb-status', role: 'status' });
      const btn = (text, title, fn, cls = '') => { const b = el('button', { type: 'button', class: `sm-btn small ${cls}`, text, title }); b.addEventListener('click', fn); return b; };
      this.stopBtn = btn('Stop', 'Stop the running cell: Python is restarted, and every notebook loses its variables', () => this.stop(), 'sm-nb-stop');
      this.stopBtn.hidden = true;
      const save = btn('Save ▾', 'Save the notebook', () => SM.ui.menu([
        { label: 'Save as Jupyter Notebook (.ipynb)', action: () => this.save('ipynb') },
        { label: 'Save as Python Script (.py)', action: () => this.save('py') },
        { separator: true },
        { label: 'Rename…', action: () => this.rename() },
        { label: 'Clear All Outputs', action: () => { for (const c of this.cells) { c.outputs = []; c.count = null; c.draw(); } this.touch(); } },
      ], save, { returnFocus: save }));
      save.setAttribute('aria-haspopup', 'menu');
      this.bar = el('div', { class: 'sm-nb-bar sm-reportbar' },
        btn('▶ Run', 'Run the cell you are in (Shift+Enter)', () => this.run(this.active || this.cells[0])),
        btn('Run All', 'Run every cell, from the top', () => this.runAll()),
        btn('+ Code', 'Add a code cell below the one you are in', () => this.add('code', this.active ? this.cells.indexOf(this.active) + 1 : this.cells.length).focus()),
        btn('+ Text', 'Add a text cell (Markdown) below the one you are in', () => this.add('markdown', this.active ? this.cells.indexOf(this.active) + 1 : this.cells.length).focus()),
        btn('Restart', 'Forget this notebook\'s variables (the outputs stay)', () => this.restart()),
        this.stopBtn, save, el('span', { class: 'sm-spacer' }), this.statusEl);
      if (typeof KvotInfo !== 'undefined') this.bar.append(KvotInfo.slot('nb:notebook'));
      this.list = el('div', { class: 'sm-nb-cells' });
      this.lead = el('p', { class: 'sm-nb-lead' });
      const addCode = btn('+ Code', 'Add a code cell at the end', () => this.add('code').focus());
      const addText = btn('+ Text', 'Add a text cell at the end', () => this.add('markdown').focus());
      this.body = el('div', { class: 'sm-nb-body', tabindex: '-1' }, this.lead, this.list, el('div', { class: 'sm-nb-end' }, addCode, addText));
      this.el = el('div', { class: 'sm-nb', dataset: { notebook: this.id } }, this.bar, this.body);
      this.el._notebook = this;
      for (const c of cells && cells.length ? cells : [{ type: 'code', source: '' }]) this.add(c.type, null, c, { quiet: true });
      this._offEngine = SM.engine.on('status', () => this.status());
      this._offTables = app.on ? app.on('table', () => this.leadText()) : null;
      this.leadText();
      this.status();
      if (typeof KvotInfo !== 'undefined') KvotInfo.mount(this.bar);
    }

    leadText() {
      const names = this.app.tables.map((t) => t.name);
      this.lead.replaceChildren(names.length
        ? el('span', null, 'Here the open tables are the files ', ...names.slice(0, 6).flatMap((n, i) => [i ? ', ' : '', el('code', { text: SM.engine.csvName(n) })]), names.length > 6 ? ', …' : '',
          ' (as the reports\' code reads them) and ', el('code', { text: 'smui.table("…")' }), '. Shift+Enter runs a cell.')
        : el('span', null, 'No table is open: open one and it is here as ', el('code', { text: '<name>.csv' }), ' and ', el('code', { text: 'smui.table("<name>")' }), '. Shift+Enter runs a cell.'));
    }

    status() {
      const e = SM.engine;
      let text = '';
      if (e.state === 'loading') text = 'Waiting for Python…';
      else if (e.state === 'error') text = 'Python did not start';
      else if (this.running) text = e.loading || `Running ${this.running === 1 ? 'a cell' : `${this.running} cells`}…`;
      else if (this.restarts !== e.restarts) text = 'Python was restarted: run the cells again';
      else text = e.state === 'ready' ? `Python ${e.versions ? e.versions.python : ''}` : '';
      this.statusEl.textContent = text;
      this.stopBtn.hidden = !this.running;
    }

    touch() { this.dirty = true; }

    activate(cell) {
      if (this.active === cell) return;
      if (this.active) this.active.el.classList.remove('is-active');
      this.active = cell;
      cell.el.classList.add('is-active');
      lastUsed = this;
    }

    add(type = 'code', at = null, init = null, { quiet = false } = {}) {
      const c = new Cell(this, { type, ...(init || {}) });
      const i = at == null ? this.cells.length : Math.max(0, Math.min(this.cells.length, at));
      const before = this.cells[i];
      this.cells.splice(i, 0, c);
      this.list.insertBefore(c.el, before ? before.el : null);
      if (!quiet) this.touch();
      return c;
    }

    remove(cell) {
      const i = this.cells.indexOf(cell);
      if (i < 0) return;
      this.cells.splice(i, 1);
      cell.el.remove();
      if (!this.cells.length) this.add('code');
      const next = this.cells[Math.min(i, this.cells.length - 1)];
      next.focus();
      this.touch();
    }

    move(cell, by) {
      const i = this.cells.indexOf(cell), j = i + by;
      if (i < 0 || j < 0 || j >= this.cells.length) return;
      this.cells.splice(i, 1);
      this.cells.splice(j, 0, cell);
      this.list.insertBefore(cell.el, j + 1 < this.cells.length ? this.cells[j + 1].el : null);
      cell.focus();
      this.touch();
    }

    retype(cell) {
      const i = this.cells.indexOf(cell);
      const c = new Cell(this, { type: cell.type === 'code' ? 'markdown' : 'code', source: cell.source });
      c.editing = true;
      c.draw();
      this.cells[i] = c;
      cell.el.replaceWith(c.el);
      c.focus();
      this.touch();
    }

    next(cell) {
      const i = this.cells.indexOf(cell);
      (this.cells[i + 1] || this.add('code')).focus();
    }

    /* Run one cell; cells run one after another, in the order asked. */
    run(cell) {
      if (!cell) return Promise.resolve(true);
      if (cell.type === 'markdown') { cell.editing = false; cell.draw(); return Promise.resolve(true); }
      cell.running = true;
      cell.draw();
      this.running++;
      this.status();
      const p = this.chain.then(async () => {
        let ok = true;
        this.restarts = SM.engine.restarts;
        try {
          const res = await exec(this.id, cell.source, { label: this.name });
          cell.outputs = res.outputs;
          cell.count = res.count;
          ok = !res.outputs.some((o) => o.type === 'error');
        } catch (e) {
          cell.outputs = [errorOutput(e)];
          ok = false;
        } finally {
          cell.running = false;
          this.running--;
          cell.draw();
          this.status();
          this.touch();
          lastUsed = this;
        }
        return ok;
      });
      this.chain = p.catch(() => false);
      return p;
    }

    async runAll() {
      for (const c of this.cells) {
        if (c.type !== 'code') { if (c.source.trim()) { c.editing = false; c.draw(); } continue; }
        if (!(await this.run(c))) break;          // an error stops the rest, as Jupyter's Run All does
      }
    }

    async restart() {
      try { await SM.engine.call('nb.reset', { nb: this.id }); } catch (e) { SM.ui.toast(e.message, { error: true }); return; }
      for (const c of this.cells) { c.count = null; c.draw(); }
      this.restarts = SM.engine.restarts;
      SM.ui.toast(`${this.name}: the variables are gone; the outputs stay until the cells run again`);
      this.status();
    }

    stop() {
      SM.ui.dialog({
        title: 'Stop the running cell',
        body: el('p', { text: 'Python cannot stop a cell in the middle: it is restarted instead. Every notebook loses its variables, and a report that is calculating stops (Redo runs it again). The outputs stay.' }),
        buttons: [{ label: 'Cancel' }, { label: 'Restart Python', primary: true, action: () => { SM.engine.restart(); return true; } }],
      });
    }

    rename() {
      SM.ui.form({ title: 'Rename the notebook', fields: [{ key: 'name', label: 'Name', type: 'text', value: this.name, help: 'The notebook\'s tab, the name its files get when saved, and what its tracebacks call its cells.' }] }).then((v) => {
        if (!v || !v.name || !v.name.trim()) return;
        this.name = v.name.trim();
        const tab = this.app.tabs.find((t) => t.notebook === this);
        if (tab) { tab.title = this.name; tab.titleEl.textContent = this.name; }
        this.touch();
      });
    }

    save(kind) {
      const base = this.name.replace(/[^\w.-]+/g, '_') || 'notebook';
      if (kind === 'py') SM.util.download(`${base}.py`, toPy(this), 'text/x-python');
      else SM.util.download(`${base}.ipynb`, JSON.stringify(toIpynb(this), null, 1), 'application/x-ipynb+json');
      this.dirty = false;
    }

    close() {
      if (this._offEngine) this._offEngine();
      if (this._offTables) this._offTables();
      const i = notebooks.indexOf(this);
      if (i >= 0) notebooks.splice(i, 1);
      if (lastUsed === this) lastUsed = notebooks[notebooks.length - 1] || null;
      SM.engine.call('nb.reset', { nb: this.id }).catch(() => {});
    }

    toJSON() { return { name: this.name, cells: this.cells.map((c) => c.toJSON()) }; }
  }

  /* ---- files -------------------------------------------------------------------------------- */
  function toJupyterOutput(o, count) {
    if (o.type === 'stream') return { output_type: 'stream', name: o.name, text: lines(o.text) };
    if (o.type === 'error') return { output_type: 'error', ename: o.ename, evalue: o.evalue, traceback: o.traceback || [] };
    const data = {};
    for (const [k, v] of Object.entries(o.data || {})) data[k] = k === PLOTLY || k === 'image/png' ? v : lines(v);
    return o.type === 'result'
      ? { output_type: 'execute_result', execution_count: count ?? null, data, metadata: o.metadata || {} }
      : { output_type: 'display_data', data, metadata: o.metadata || {} };
  }

  function fromJupyterOutput(o) {
    if (o.output_type === 'stream') return { type: 'stream', name: o.name === 'stderr' ? 'stderr' : 'stdout', text: joined(o.text) };
    if (o.output_type === 'error') return { type: 'error', ename: String(o.ename || 'Error'), evalue: String(o.evalue || ''), traceback: (o.traceback || []).map(String) };
    if (o.output_type === 'execute_result' || o.output_type === 'display_data') {
      const data = {};
      for (const [k, v] of Object.entries(o.data || {})) data[k] = k === PLOTLY ? v : joined(v);
      return { type: o.output_type === 'execute_result' ? 'result' : 'display', data, metadata: o.metadata || {} };
    }
    return null;
  }

  function toIpynb(nb) {
    const v = SM.engine.versions || {};
    return {
      nbformat: 4, nbformat_minor: 5,
      metadata: {
        kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' },
        language_info: { name: 'python', version: v.python || '' },
        smui: { name: nb.name, made: 'User Interface for statsmodels, kvotab.se/smui.html', pyodide: v.pyodide || '', statsmodels: v.statsmodels || '' },
      },
      cells: nb.cells.map((c, i) => (c.type === 'code'
        ? { cell_type: 'code', id: `cell-${i + 1}`, metadata: {}, execution_count: c.count ?? null, source: lines(c.source), outputs: c.outputs.map((o) => toJupyterOutput(o, c.count)) }
        : { cell_type: 'markdown', id: `cell-${i + 1}`, metadata: {}, source: lines(c.source) })),
    };
  }

  function fromIpynb(j, name) {
    if (!j || !Array.isArray(j.cells)) throw new Error('not a Jupyter notebook (no cells)');
    if (j.nbformat && j.nbformat < 4) throw new Error(`a notebook of format ${j.nbformat}: only format 4 (Jupyter since 2015) is read`);
    const lang = j.metadata && ((j.metadata.kernelspec && j.metadata.kernelspec.language) || (j.metadata.language_info && j.metadata.language_info.name));
    if (lang && !/python/i.test(lang)) SM.ui.toast(`The notebook was written for ${lang}; its cells run as Python here`, { error: true });
    return {
      name: (j.metadata && j.metadata.smui && j.metadata.smui.name) || name,
      cells: j.cells.map((c) => (c.cell_type === 'code'
        ? { type: 'code', source: joined(c.source), count: c.execution_count ?? null, outputs: (c.outputs || []).map(fromJupyterOutput).filter(Boolean) }
        : { type: 'markdown', source: joined(c.source) })),
    };
  }

  // Python with cells marked "# %%" (and "# %% [markdown]", its lines as comments), as Jupytext and editors write it.
  function toPy(nb) {
    const out = [`# ${SM.util.oneLine(nb.name)}: a notebook of the User Interface for statsmodels (kvotab.se/smui.html)`, ''];
    for (const c of nb.cells) {
      if (c.type === 'markdown') out.push('# %% [markdown]', ...c.source.split(/\r\n|\r|\n/).map((l) => (l ? `# ${SM.util.oneLine(l)}` : '#')), '');
      else out.push('# %%', c.source.replace(/\s+$/, ''), '');
    }
    return `${out.join('\n').replace(/\n+$/, '')}\n`;
  }

  function fromPy(text, name) {
    const src = String(text).replace(/\r\n?/g, '\n');
    if (!/^# %%/m.test(src)) return { name, cells: [{ type: 'code', source: src.replace(/\s+$/, '') }] };
    const cells = [];
    let cur = null;
    for (const l of src.split('\n')) {
      const m = /^# %%(.*)$/.exec(l);
      if (m) { cur = { type: /\[markdown\]|\[md\]/i.test(m[1]) ? 'markdown' : 'code', lines: [] }; cells.push(cur); continue; }
      if (!cur) { if (!l.trim() || /^#/.test(l)) continue; cur = { type: 'code', lines: [] }; cells.push(cur); }
      cur.lines.push(cur.type === 'markdown' ? l.replace(/^# ?/, '') : l);
    }
    return { name, cells: cells.map((c) => ({ type: c.type, source: c.lines.join('\n').replace(/^\n+|\s+$/g, '') })).filter((c) => c.source || c.type === 'code') };
  }

  /* ---- the app's side ----------------------------------------------------------------------- */
  function open(app, init = {}, { show = true } = {}) {
    const nb = new Notebook(app, init);
    notebooks.push(nb);
    lastUsed = nb;
    const tab = app._addTab({ kind: 'notebook', title: nb.name, view: nb.el });
    tab.notebook = nb;
    tab.btn.title = `${nb.name}: a Python notebook`;
    if (show) { app.showTab(tab); requestAnimationFrame(() => nb.cells[0] && nb.cells[0].focus()); }
    return nb;
  }

  function close(app, nb) {
    const tab = app.tabs.find((t) => t.notebook === nb);
    const done = () => { nb.close(); if (tab) app._removeTab(tab); };
    if (!nb.dirty) { done(); return; }
    SM.ui.dialog({
      title: `Close ${nb.name}`,
      body: el('p', { text: 'The notebook has changes that are not saved (Save ▾ writes an .ipynb or a .py file; Save Project keeps it with the tables). Close it anyway?' }),
      buttons: [{ label: 'Cancel' }, { label: 'Close without saving', primary: true, action: () => { done(); return true; } }],
    });
  }

  async function openFile(app, file) {
    const text = await file.text();
    const base = file.name.replace(/\.[^.]+$/, '');
    const init = /\.ipynb$/i.test(file.name) ? fromIpynb(JSON.parse(text), base) : fromPy(text, base);
    const nb = open(app, init);
    nb.dirty = false;
    SM.ui.toast(`Opened ${file.name}: ${nb.cells.length} cells. Nothing has run: Run All runs them.`);
    return nb;
  }

  /* Code from a report: a cell at the end of the notebook used last (a new
     notebook if none is open), with a line of text naming where it came from. */
  function collect(code, { title = 'a report', table = null } = {}) {
    const app = SM.app;
    let nb = lastUsed && notebooks.includes(lastUsed) ? lastUsed : null;
    if (!nb) nb = open(app, { cells: [] }, { show: false });
    // a notebook that is one empty cell takes the code in that cell
    const only = nb.cells.length === 1 && nb.cells[0].type === 'code' && !nb.cells[0].source.trim() && !nb.cells[0].outputs.length ? nb.cells[0] : null;
    nb.add('markdown', only ? 0 : null, { source: `From **${title}**${table ? ` (table ${table.name})` : ''}` }).draw();
    const c = only || nb.add('code');
    c.editor.value = code;
    nb.touch();
    const tab = app.tabs.find((t) => t.notebook === nb);
    if (tab) app.showTab(tab);
    requestAnimationFrame(() => { c.el.scrollIntoView({ block: 'nearest' }); c.focus(); });
    return nb;
  }

  // Every part of a report's script as cells of a new notebook.
  function fromReport(report) {
    const app = SM.app;
    const parts = [...new Set(report.pyCode || [])];
    const cells = [{ type: 'markdown', source: `# ${report.title}\nThe Python of the report${report.table ? ` on the table **${report.table.name}**` : ''}, a cell for each result. Run All runs them; each reads the table as the report's code does.` }];
    for (const p of parts) cells.push({ type: 'code', source: p });
    if (!parts.length) cells.push({ type: 'code', source: '# this report ran no Python' });
    return open(app, { name: report.title, cells });
  }

  const topics = {
    'nb:notebook': {
      kicker: 'Python', title: 'Notebook',
      lead: 'Python cells, run in this page by the same Python as the reports (Pyodide, with numpy, scipy, pandas, statsmodels; matplotlib, scikit-learn and the other packages of Pyodide load when a cell imports them). Each notebook has its own variables.',
      sections: [
        { heading: 'Running', list: ['Shift+Enter runs the cell and moves to the next; Ctrl/⌘+Enter runs it and stays; Alt+Enter runs it and adds a cell below.', 'What a cell prints, and the value of its last line, show under it; so do matplotlib figures (plt.show(), or at the end of the cell), pandas tables and statsmodels summaries. A trailing ; keeps the last value quiet.', 'Run All runs every cell from the top and stops at the first error. Restart forgets the notebook\'s variables; Stop restarts Python itself (a cell cannot be stopped in the middle).'] },
        { heading: 'The tables', list: ['Each open table is here as the CSV file the reports\' code reads: pd.read_csv("<name>.csv"), so a report\'s code runs as it is.', 'import smui, then smui.table_names() lists the tables and smui.table("<name>") gives one as a DataFrame, its modeling types as dtypes (ordinal and nominal columns categorical, in the table\'s value order).', 'smui.new_table(df, "<name>") puts a DataFrame in the page as a new table, to analyze from the menus.'] },
        { heading: 'Files', list: ['Save ▾ writes a Jupyter notebook (.ipynb, with the outputs) or a Python script with # %% cells (.py). File > Open reads both; a project (File > Save Project) keeps its notebooks.', 'Other packages: %pip install <name> (or await micropip.install(...)) fetches a pure-Python package from PyPI.'] },
      ],
      more: { label: 'The notebook', id: 'help-notebook' },
    },
  };
  if (SM.info) SM.info.add(topics);

  SM.whenApp((app) => {
    if (!SM.commands) return;
    SM.commands.register({ menu: 'Python', order: 10, label: 'New Notebook', about: 'A tab of Python cells, with the open tables', action: (a) => open(a) });
    SM.commands.register({ menu: 'Python', order: 20, label: 'Open Notebook…', key: '.ipynb, .py', about: 'A Jupyter notebook or a Python script', action: (a) => a.fileInput.click() });
    SM.commands.register({ menu: 'Python', order: 30, label: 'Report Script in Notebook', about: 'The Python of the report in front, as the cells of a new notebook', enabled: (a) => !!(a.activeTab && a.activeTab.report), action: (a) => a.activeTab && a.activeTab.report && fromReport(a.activeTab.report) });
  });

  SM.notebook = Object.freeze({
    open, close, openFile, collect, fromReport, exec, renderOutputs, markdown, magics,
    toIpynb, fromIpynb, toPy, fromPy, notebooks, Notebook, Cell,
    get lastUsed() { return lastUsed; },
  });
}(typeof self !== 'undefined' ? self : this));
