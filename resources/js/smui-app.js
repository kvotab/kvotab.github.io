/* ==========================================================================
   SMUI.HTML: THE PAGE

   The menu bar (File, Edit, Tables, Rows, Cols, DOE, Analyze, Graph, Help),
   the side panels, and the tabs: Home, one per open table, one per report,
   and Help while it is open. The platforms and commands register themselves:

     SM.platforms.register({
       id: 'distribution', label: 'Distribution', menu: 'Analyze', order: 10,
       launch: { roles, options },          see smui-launch.js
       title(spec, table) -> 'Distributions',
       async render(ctx) { ... },           see smui-report.js
       triangle(ctx) -> the items of the top outline's red triangle,
       info: 'topic key', topics: { key: topic, ... },
       about: 'one paragraph for the Help tab',
       uses: ['statsmodels.stats.weightstats.DescrStatsW', ...],
     });

     SM.commands.register({
       menu: 'Tables', label: 'Sort…', order: 30,
       action(app, column) { ... }, enabled(app) -> bool, context: 'column',
       submenu(app, column) -> items   (instead of action, for a submenu)
     });

   The app emits 'table' (the current table changed), 'tableadded',
   'tableremoved' and 'columnselection'.

   A menu path may name a submenu, 'Analyze/Multivariate Methods'. Items
   are sorted by order; a separator goes between hundreds (10-99, 100-199,
   ...), which is how JMP groups its menus.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, typeIcon, TYPE_LABEL, Emitter } = SM.util;

  /* ---- registries --------------------------------------------------------- */
  const platforms = new Map();
  const commands = [];
  let topicsReady = false;
  const pendingTopics = {};
  const allTopics = {};      // every topic added here, for the dialogs that build on one

  function addTopics(t) {
    if (!t || typeof KvotInfo === 'undefined') return;
    Object.assign(allTopics, t);
    if (topicsReady) KvotInfo.add(t); else Object.assign(pendingTopics, t);
  }

  SM.platforms = Object.freeze({
    register(def) {
      if (!def || !def.id || !def.label || typeof def.render !== 'function') throw new Error('a platform needs an id, a label and render(ctx)');
      platforms.set(def.id, def);
      addTopics(def.topics);
    },
    get: (id) => platforms.get(id),
    all: () => [...platforms.values()],
  });

  SM.commands = Object.freeze({
    register(def) {
      if (!def || !def.label || !def.menu || (typeof def.action !== 'function' && typeof def.submenu !== 'function')) throw new Error('a command needs a menu, a label and action(app) or submenu(app)');
      commands.push(def);
      addTopics(def.topics);
    },
    all: () => commands.slice(),
  });

  /* fn(app) once the page's app has started: now, if it has. The page's
     scripts are deferred and the app is made when they have all run, so a
     module that works on the app (smui-formula.js) waits for it here. */
  const appHooks = [];
  SM.whenApp = (fn) => { if (SM.app && SM.app.started) fn(SM.app); else appHooks.push(fn); };

  // get() gives a topic as shown: a topic may be a function of the state.
  SM.info = Object.freeze({
    add: addTopics,
    get(key) {
      const t = allTopics[key];
      try { return typeof t === 'function' ? t() : (t || null); } catch (e) { return null; }
    },
  });

  // 75 -> '1 min 15 s'
  const duration = (s) => (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`);

  // Where submenus go among the items of their menu.
  const SUBMENU_ORDER = {
    'Analyze/Predictive Modeling': 120, 'Analyze/Specialized Modeling': 130, 'Analyze/Screening': 140,
    'Analyze/Multivariate Methods': 210, 'Analyze/Clustering': 220,
    'Analyze/Quality and Process': 310, 'Analyze/Reliability and Survival': 320, 'Analyze/Consumer Research': 330,
    'DOE/Classical': 110, 'DOE/Special Purpose': 120, 'DOE/Design Diagnostics': 210, 'DOE/Sample Size Explorers': 220,
    'Graph/Legacy': 310, 'Cols/Utilities': 310, 'Cols/Modeling Utilities': 320, 'Tables/Utilities': 310, 'Rows/Row Selection': 10,
  };

  const MENUS = ['File', 'Edit', 'Tables', 'Rows', 'Cols', 'DOE', 'Analyze', 'Graph', 'Python', 'Help'];

  /* ---- the app -------------------------------------------------------------- */
  class App extends Emitter {
    constructor(host) {
      super();
      this.host = host;
      this.tables = [];
      this.reports = [];
      this.grids = new Map();
      this.current = null;       // the current table
      this.activeTab = null;
      this.log = [];
      this.undoStack = [];
      this.redoStack = [];
      this._build();
    }

    // every tab, group by group in the order they sit
    get tabs() { return this.dock ? this.dock.groups.flatMap((g) => g.tabs) : []; }

    /* ---- undo ---------------------------------------------------------------
       Before a change, record(table, label) keeps a copy of the table (or
       recordCells() the old values of a few cells); Edit > Undo puts it
       back. Thirty steps, tables of up to four million cells. */
    record(t, label) {
      if (!t || t.nrows * Math.max(1, t.columns.length) > 4e6) return;
      this.undoStack.push({ table: t, label, snap: t.snapshot() });
      if (this.undoStack.length > 30) this.undoStack.shift();
      this.redoStack = [];
    }

    recordCells(t, label, cells) {
      if (!t || !cells.length) return;
      this.undoStack.push({ table: t, label, cells: cells.map(([r, id]) => [r, id, t.col(id) ? t.col(id).values[r] : undefined]) });
      if (this.undoStack.length > 30) this.undoStack.shift();
      this.redoStack = [];
    }

    _flip(from, to) {
      const e = from.pop();
      if (!e) return;
      const t = e.table;
      if (!this.tables.includes(t)) { SM.ui.toast(`${e.label}: its table is closed`); return; }
      if (e.snap) {
        to.push({ table: t, label: e.label, snap: t.snapshot() });
        t.restore(e.snap);
      } else {
        to.push({ table: t, label: e.label, cells: e.cells.map(([r, id]) => [r, id, t.col(id) ? t.col(id).values[r] : undefined]) });
        for (const [r, id, v] of e.cells) if (t.col(id) && r < t.nrows) t.setCell(r, id, v, { silent: true });
        t._changed('data', { undo: true });
      }
      const g = this.grids.get(t.id);
      if (g) g.refresh();
      SM.ui.toast(`${from === this.undoStack ? 'Undid' : 'Redid'}: ${e.label}`);
    }

    undo() { this._flip(this.undoStack, this.redoStack); }
    redo() { this._flip(this.redoStack, this.undoStack); }

    get grid() { return this.current ? this.grids.get(this.current.id) || null : null; }

    selectedColumns() { const g = this.grid; return g ? g.selectedColumns() : []; }

    /* ---- layout ---------------------------------------------------------- */
    _build() {
      const h = this.host;
      h.querySelector(':scope > .sm-boot')?.remove();     // the page's stand-in while its scripts load
      h.classList.add('sm');
      this.menubar = el('nav', { class: 'sm-menubar', 'aria-label': 'Menus' });
      // in the full window, where the site's header is not shown, the kvot mark goes to the home page
      const home = el('a', { class: 'sm-homelink sm-fullonly', href: './index.html', title: 'kvot ab: the home page' },
        el('img', { src: './resources/images/kvot-logotype.svg', alt: 'kvot ab: the home page', width: '20', height: '20' }));
      const sideBtn = el('button', { type: 'button', class: 'sm-sidetoggle', 'aria-label': 'Show or hide the table panels', text: '☰' });
      sideBtn.addEventListener('click', () => h.classList.toggle('side-open'));
      this.menubar.append(home, sideBtn);
      for (const name of MENUS) {
        const b = el('button', { type: 'button', text: name, 'aria-haspopup': 'menu', dataset: { menu: name } });
        const openIt = () => {
          this.menubar.querySelectorAll('button.is-open').forEach((x) => x.classList.remove('is-open'));
          b.classList.add('is-open');
          SM.ui.menu(this.menuItems(name), b, { returnFocus: b, onClose: () => b.classList.remove('is-open') });
        };
        b.addEventListener('click', (ev) => { ev.stopPropagation(); if (b.classList.contains('is-open')) SM.ui.closeMenus(0); else openIt(); });
        b.addEventListener('mouseenter', () => { if (this.menubar.querySelector('button.is-open') && !b.classList.contains('is-open')) openIt(); });
        b.addEventListener('keydown', (ev) => {
          if (ev.key === 'ArrowDown') { ev.preventDefault(); openIt(); }
          else if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
            ev.preventDefault();
            const all = [...this.menubar.querySelectorAll('button[data-menu]')];
            const i = all.indexOf(b);
            all[(i + (ev.key === 'ArrowRight' ? 1 : all.length - 1)) % all.length].focus();
          }
        });
        this.menubar.append(b);
      }
      this.engineEl = el('button', { type: 'button', class: 'sm-engine', dataset: { state: 'off' }, 'aria-live': 'polite' });
      this.engineEl.addEventListener('click', () => this.engineDialog());
      // in the full window, the site's own theme switch (site.js keeps its icon and title)
      const dark = document.documentElement.getAttribute('data-theme') === 'dark';
      const theme = el('button', { type: 'button', class: 'theme-toggle sm-fullonly', 'data-on-click': 'kvot:toggleTheme', title: dark ? 'Switch to light mode' : 'Switch to dark mode', text: dark ? '☀️' : '🌙' });
      this.fullBtn = el('button', { type: 'button', class: 'sm-fullbtn', 'aria-label': 'Full window' });
      this.fullBtn.addEventListener('click', () => this.setFull(!document.documentElement.classList.contains('sm-full')));
      // (the two at the end stay in sight at phone width, where the menu bar scrolls)
      this.menubar.append(el('span', { class: 'sm-spacer' }), this.engineEl, el('span', { class: 'sm-menuend' }, theme, this.fullBtn));
      this._fullState();

      this.side = el('aside', { class: 'sm-side', 'aria-label': 'Table, columns and rows' });
      this.handle = el('div', { class: 'sm-handle', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize the panels', tabindex: '0' });
      this.main = el('main', { class: 'sm-main' });
      h.append(this.menubar, el('div', { class: 'sm-body' }, this.side, this.handle, this.main));
      // the tab groups: one to start with, more when a tab is dragged aside
      this.dock = new SM.dock.Dock(this, this.main);
      this.panels = new SM.panels.Panels(this.side, this);
      this._wireHandle();

      this.fileInput = el('input', { type: 'file', accept: '.csv,.tsv,.txt,.dat,.tab,.xlsx,.xlsm,.json,.dta,.sas7bdat,.xpt,.jmp,.ipynb,.py,.jsl', multiple: true, hidden: true });
      this.fileInput.addEventListener('change', () => { const f = [...this.fileInput.files]; this.fileInput.value = ''; this.openFiles(f); });
      h.append(this.fileInput);
      this._wireDrop();

      this.homeTab = this._addTab({ kind: 'home', title: 'Home', closable: false, view: this._homeView() });
      this.helpTab = null;
    }

    /* The full window: the workbench without the site's header and footer
       (smui.css :root.sm-full), kept for the next visit. */
    setFull(on) {
      document.documentElement.classList.toggle('sm-full', !!on);
      try { localStorage.setItem('smui.full', on ? '1' : '0'); } catch (e) { /* storage unavailable: for this visit only */ }
      this._fullState();
    }

    _fullState() {
      const on = document.documentElement.classList.contains('sm-full');
      const b = this.fullBtn;
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Show the site\'s header and footer again' : 'Full window: the workbench without the site\'s header and footer';
      // four corners: out to the full window, or in again
      b.replaceChildren(SM.util.svg('svg', { viewBox: '0 0 16 16', width: 15, height: 15, 'aria-hidden': 'true', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' },
        SM.util.svg('path', { d: on ? 'M6 2v4H2M10 2v4h4M14 10h-4v4M2 10h4v4' : 'M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4' })));
    }

    _wireHandle() {
      const hd = this.handle;
      let x0 = 0, w0 = 0;
      const move = (ev) => { const w = Math.max(170, Math.min(520, w0 + ev.clientX - x0)); this.host.style.setProperty('--sm-side-w', `${w}px`); };
      const up = () => { hd.classList.remove('active'); removeEventListener('mousemove', move); removeEventListener('mouseup', up); try { localStorage.setItem('smui.sideW', this.host.style.getPropertyValue('--sm-side-w')); } catch (e) { /* ignore */ } };
      hd.addEventListener('mousedown', (ev) => { ev.preventDefault(); x0 = ev.clientX; w0 = this.side.getBoundingClientRect().width; hd.classList.add('active'); addEventListener('mousemove', move); addEventListener('mouseup', up); });
      hd.addEventListener('keydown', (ev) => {
        if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
        ev.preventDefault();
        const w = Math.max(170, Math.min(520, this.side.getBoundingClientRect().width + (ev.key === 'ArrowRight' ? 16 : -16)));
        this.host.style.setProperty('--sm-side-w', `${w}px`);
      });
      try { const w = localStorage.getItem('smui.sideW'); if (w) this.host.style.setProperty('--sm-side-w', w); } catch (e) { /* ignore */ }
    }

    _wireDrop() {
      const h = this.host;
      const hasFiles = (ev) => ev.dataTransfer && [...ev.dataTransfer.types].includes('Files');
      h.addEventListener('dragover', (ev) => { if (hasFiles(ev)) { ev.preventDefault(); h.classList.add('is-dropping'); } });
      h.addEventListener('dragleave', (ev) => { if (ev.target === h || !h.contains(ev.relatedTarget)) h.classList.remove('is-dropping'); });
      h.addEventListener('drop', (ev) => {
        h.classList.remove('is-dropping');
        if (!hasFiles(ev)) return;
        ev.preventDefault();
        this.openFiles([...ev.dataTransfer.files]);
      });
    }

    /* ---- tabs -------------------------------------------------------------
       Each tab is in one of the work area's groups (smui-dock.js). A new one
       opens in the group in use, before its Help tab. */
    _addTab({ kind, title, closable = true, view, table = null, report = null, at = null }) {
      const id = SM.util.uid('tab');
      const titleEl = el('span', { class: 'sm-tabtitle', text: title });
      const btn = el('button', { type: 'button', class: 'sm-tab', role: 'tab', 'aria-selected': 'false', id, dataset: { kind } },
        kind === 'table' ? tableGlyph() : kind === 'report' ? reportGlyph() : kind === 'notebook' || kind === 'jsl' ? notebookGlyph() : null, titleEl);
      const tab = { id, kind, title, btn, titleEl, view, table, report, closable, group: null };
      if (closable) {
        const x = el('span', { class: 'sm-tabclose', role: 'button', 'aria-label': `Close ${title}`, text: '×' });
        x.addEventListener('click', (ev) => { ev.stopPropagation(); this.closeTab(tab); });
        btn.append(x);
      }
      btn.addEventListener('click', () => this.showTab(tab));
      // the arrow keys, Home and End go along the tab's own strip;
      // ctrl/⌘+shift+left/right moves the tab along it
      btn.addEventListener('keydown', (ev) => {
        const list = tab.group ? tab.group.tabs : [tab];
        const i = list.indexOf(tab);
        if ((ev.ctrlKey || ev.metaKey) && ev.shiftKey && (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft')) {
          ev.preventDefault();
          const to = ev.key === 'ArrowRight' ? i + 2 : i - 1;
          if (to >= 0 && to <= list.length) { this.dock.move(tab, tab.group, to); btn.focus(); }
          return;
        }
        let j = null;
        if (ev.key === 'ArrowRight') j = (i + 1) % list.length;
        else if (ev.key === 'ArrowLeft') j = (i - 1 + list.length) % list.length;
        else if (ev.key === 'Home') j = 0;
        else if (ev.key === 'End') j = list.length - 1;
        if (j == null) return;
        ev.preventDefault();
        const to = list[j];
        this.showTab(to);
        to.btn.focus();
      });
      btn.addEventListener('auxclick', (ev) => { if (ev.button === 1 && closable) this.closeTab(tab); });
      btn.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        const items = [];
        if (tab.report) items.push(...tab.report.redoMenu());
        else if (tab.table) items.push(...this.tableMenu());
        const place = this.dock.menuFor(tab);
        if (items.length && place.length) items.push({ separator: true });
        items.push(...place);
        if (items.length) SM.ui.menu(items, { x: ev.clientX, y: ev.clientY });
      });
      view.classList.add('sm-view');
      view.setAttribute('role', 'tabpanel');
      view.setAttribute('aria-labelledby', id);
      view.hidden = true;
      const g = this.dock.active;
      const help = this.helpTab && kind !== 'help' && this.helpTab.group === g ? g.tabs.indexOf(this.helpTab) : null;
      this.dock.add(tab, { group: g, at: at != null ? at : help });
      return tab;
    }

    /* The tab in front of its group, and that group the one in use. */
    showTab(tab) {
      if (!tab || !tab.group) return;
      this.dock.show(tab);
      this._activate(tab);
      this._shown(tab);
      tab.btn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      this.host.classList.remove('side-open');
    }

    // The tab in front of the group in use: the page's title and the current table.
    _activate(tab) {
      this.activeTab = tab;
      if (!this.baseTitle) this.baseTitle = document.title;
      document.title = tab.kind === 'home' ? this.baseTitle : `${tab.title} — ${this.baseTitle}`;
      const table = tab.table || (tab.report && tab.report.table) || null;
      if (table && table !== this.current) this._setCurrent(table);
    }

    // A tab's view has come into view: what it shows is drawn for its room.
    _shown(tab) {
      if (tab.kind === 'home') this._renderHome();
      if (tab.kind === 'table') { const g = this.grids.get(tab.table.id); if (g) requestAnimationFrame(() => g.refresh()); }
      if (tab.report) requestAnimationFrame(() => SM.report.kickPlots(tab.report.body));
    }

    closeTab(tab) {
      if (tab.kind === 'table') return this.closeTable(tab.table);
      if (tab.kind === 'report') return this.closeReport(tab.report);
      if (tab.kind === 'notebook' && SM.notebook) return SM.notebook.close(this, tab.notebook);
      if (tab.onClose) tab.onClose();
      this._removeTab(tab);
    }

    // A tab out of its group (which goes if it is left empty); the group
    // shows the tab beside it, and if the tab was in front, that one is.
    _removeTab(tab) {
      const g = tab.group;
      if (!g) return;
      const k = g.tabs.indexOf(tab), shown = g.active === tab, front = this.activeTab === tab;
      tab.btn.remove();
      this.dock.remove(tab);
      // The Help text stays in the page, hidden, for the (i)s' Read more links.
      if (tab === this.helpTab) { this.helpTab = null; tab.view.removeAttribute('aria-labelledby'); this.dock.park(tab.view); }
      else tab.view.remove();
      const next = shown && this.dock.groups.includes(g) ? g.tabs[Math.min(k, g.tabs.length - 1)] : null;
      const inUse = this.dock.active;
      if (front) this.showTab(next || inUse.active || inUse.tabs[0] || this.homeTab);
      else if (next) this.dock.show(next, { focus: false });
    }

    _setCurrent(t) {
      this.current = t;
      this.panels.setTable(t);
      this.emit('table', t);
    }

    /* ---- tables ----------------------------------------------------------- */
    addTable(t, { show = true } = {}) {
      this.tables.push(t);
      const view = el('div', { class: 'sm-tableview' });
      const grid = new SM.grid.Grid(view, this);
      this.grids.set(t.id, grid);
      grid.setTable(t);
      const tab = this._addTab({ kind: 'table', title: t.name, view, table: t });
      t.on('schema', () => { tab.titleEl.textContent = t.name; tab.title = t.name; this.panels.renderTable(); });
      if (show) this.showTab(tab); else this.panels.renderTable();
      this._renderHome();
      this.emit('tableadded', t);
      return t;
    }

    tabOf(obj) { return this.tabs.find((x) => x.table === obj || x.report === obj) || null; }

    showTable(id) {
      const t = this.tables.find((x) => x.id === id);
      if (t) this.showTab(this.tabOf(t));
    }

    closeTable(t) {
      const reps = this.reports.filter((r) => r.table === t);
      const go = () => {
        for (const r of reps) this.closeReport(r);
        const tab = this.tabOf(t);
        this.tables.splice(this.tables.indexOf(t), 1);
        this.grids.get(t.id)?.setTable(null);
        this.grids.delete(t.id);
        if (tab) this._removeTab(tab);
        if (this.current === t) this._setCurrent(this.tables[this.tables.length - 1] || null);
        this._renderHome();
        this.undoStack = this.undoStack.filter((e) => e.table !== t);
        this.redoStack = this.redoStack.filter((e) => e.table !== t);
        this.emit('tableremoved', t);
      };
      if (reps.length) {
        SM.ui.dialog({
          title: `Close ${t.name}`, narrow: true,
          body: el('p', { class: 'sm-dialog-lead', text: `Closing the table closes its ${reps.length} report${reps.length > 1 ? 's' : ''} too. Nothing is saved unless you save it first (File > Save Table).` }),
          buttons: [{ label: 'Cancel' }, { label: 'Close', primary: true, action: () => { go(); } }],
        });
      } else go();
    }

    renameTable(t, name) {
      if (!name || name === t.name) return;
      t.name = name;
      t.version++;
      t.emit('schema', { renamed: 'table' });
      t.emit('data', { renamed: 'table' });
      for (const r of this.reports) if (r.table === t) this.retitle(r);
    }

    requireTable() {
      if (this.current) return this.current;
      SM.ui.toast('Open a table first: File > Open, or an example from File > Examples.');
      return null;
    }

    async openFiles(files) {
      for (const f of files) {
        try {
          // a notebook, or a JSL script to convert
          if (/\.(ipynb|py)$/i.test(f.name) && SM.notebook) { await SM.notebook.openFile(this, f); continue; }
          if (/\.jsl$/i.test(f.name) && SM.jsl) { await SM.jsl.openFile(this, f); continue; }
          if (/\.(dta|sas7bdat|xpt|jmp)$/i.test(f.name)) {
            SM.ui.toast(`Reading ${f.name} in the Python engine…`);
            const r = await SM.engine.callBytes('datasets.read_file', { name: f.name }, await f.arrayBuffer());
            // a JMP table's scripts come as their JSL text (the table checks them)
            const scripts = (r.scripts || []).map((x) => ({ name: x.name, kind: 'jsl', jsl: x.jsl }));
            const t = new SM.Table({ name: r.name, source: `from ${f.name}`, notes: r.note || '', scripts, columns: r.columns.map((c) => ({ ...c, values: c.values.map((v) => (v == null && c.dataType === 'numeric' ? NaN : v)) })) });
            this.addTable(t);
            SM.ui.toast(`Opened ${f.name}: ${t.nrows} rows × ${t.columns.length} columns`);
            continue;
          }
          if (/\.json$/i.test(f.name)) {
            const j = JSON.parse(await f.text());
            if (j && j.format === 'smui-project') { this.loadProject(j); continue; }
            this.addTable(SM.Table.fromJSON(j));
            continue;
          }
          const tables = await SM.io.readFile(f);
          for (const t of tables) { t.source = t.source || `from ${f.name}`; this.addTable(t); }
          SM.ui.toast(`Opened ${f.name}: ${tables.map((t) => `${t.nrows} rows × ${t.columns.length} columns`).join('; ')}`);
        } catch (e) {
          SM.ui.toast(`${f.name}: ${e.message || e}`, { error: true });
        }
      }
    }

    openExample(key) {
      const t = SM.io.example(key);
      this.addTable(t);
      return t;
    }

    newTable() {
      const t = new SM.Table({ name: this.uniqueTableName('Untitled'), columns: [{ name: 'Column 1', dataType: 'numeric', values: new Array(20).fill(NaN) }] });
      this.addTable(t);
      return t;
    }

    uniqueTableName(base) {
      const names = new Set(this.tables.map((t) => t.name));
      if (!names.has(base)) return base;
      for (let i = 2; ; i++) if (!names.has(`${base} ${i}`)) return `${base} ${i}`;
    }

    async datasetsDialog() {
      const box = el('div', null, el('p', { class: 'sm-dialog-lead', text: 'The example datasets that come with statsmodels, loaded from the statsmodels package in the Python engine. Each one names its source and its terms; they are not part of this page.' }));
      const list = el('div', { class: 'sm-dslist' }, el('p', { class: 'sm-ob-note', text: 'Waiting for the Python engine…' }));
      box.append(list);
      const dlg = SM.ui.dialog({ title: 'statsmodels Datasets', body: box, buttons: [{ label: 'Close' }], info: 'file:datasets' });
      let items;
      try { items = await SM.engine.call('datasets.list', {}); } catch (e) { list.replaceChildren(SM.report.error(e)); return; }
      list.replaceChildren();
      for (const d of items) {
        const b = el('button', { type: 'button', class: 'sm-dsitem' }, el('strong', { text: d.title || d.name }), el('span', { text: d.short || '' }), d.copyright ? el('em', { text: d.copyright }) : null);
        b.addEventListener('click', async () => {
          b.disabled = true;
          try {
            const r = await SM.engine.call('datasets.load', { name: d.name });
            const t = new SM.Table({ name: r.title || r.name, source: `statsmodels.datasets.${r.name}${r.source ? `. Source: ${r.source}` : ''}`, notes: [r.note, r.copyright ? `Copyright: ${r.copyright}` : ''].filter(Boolean).join(' '), columns: r.columns.map((c) => ({ ...c, values: c.values.map((v) => (v == null && c.dataType === 'numeric' ? NaN : v)) })) });
            dlg.close();
            this.addTable(t);
          } catch (e) { b.disabled = false; SM.ui.toast(e.message, { error: true }); }
        });
        list.append(b);
      }
    }

    exportTable(kind) {
      const t = this.requireTable();
      if (!t) return;
      const base = t.name.replace(/[^\w.-]+/g, '_') || 'table';
      if (kind === 'csv') SM.util.download(`${base}.csv`, SM.io.toCsv(t, ','), 'text/csv');
      else if (kind === 'tsv') SM.util.download(`${base}.tsv`, SM.io.toCsv(t, '\t'), 'text/tab-separated-values');
      else if (kind === 'xlsx') SM.io.toXlsxBlob(t).then((b) => SM.util.download(`${base}.xlsx`, b)).catch((e) => SM.ui.toast(e.message, { error: true }));
      else if (kind === 'json') SM.util.download(`${base}.json`, JSON.stringify(t.toJSON()), 'application/json');
    }

    saveProject() {
      const nbs = SM.notebook ? SM.notebook.notebooks : [];
      // the tab groups, a tab by what it shows: "table:2" is the third table
      const refOf = (tab) => (tab === this.homeTab ? 'home' : tab === this.helpTab ? 'help'
        : tab.kind === 'table' ? `table:${this.tables.indexOf(tab.table)}`
          : tab.kind === 'report' ? `report:${this.reports.indexOf(tab.report)}`
            : tab.notebook ? `notebook:${nbs.indexOf(tab.notebook)}` : null);
      const j = { format: 'smui-project', version: 1, saved: new Date().toISOString(), tables: this.tables.map((t) => ({ id: t.id, ...t.toJSON() })), reports: this.reports.map((r) => r.toJSON()),
        notebooks: nbs.map((n) => n.toJSON()), layout: this.dock.layout(refOf) };
      if (SM.notebook) for (const n of SM.notebook.notebooks) n.dirty = false;
      SM.util.download('smui-project.json', JSON.stringify(j), 'application/json');
    }

    loadProject(j) {
      const ids = new Map();
      const made = { table: [], report: [], notebook: [] };      // by their place in the file
      for (const tj of j.tables || []) { const t = SM.Table.fromJSON(tj); ids.set(tj.id, t); this.addTable(t, { show: false }); made.table.push(t); }
      for (const rj of j.reports || []) {
        const p = platforms.get(rj.platform);
        const t = rj.table ? ids.get(rj.table) : null;
        if (!p || (!t && p.needsTable !== false)) { made.report.push(null); continue; }
        if (!t) { made.report.push(this.openReport(p, rj.spec, null, { show: false })); continue; }
        // Column ids change on loading: map them through the column names saved with the report.
        const spec = remapSpec(rj.spec, t, rj.idNames);
        made.report.push(this.openReport(p, spec, t, { show: false }));
      }
      if (SM.notebook) for (const nj of j.notebooks || []) { const nb = SM.notebook.open(this, nj, { show: false }); nb.dirty = false; made.notebook.push(nb); }
      // the tab groups as they were saved (a file from before there were groups has none)
      const find = (ref) => {
        if (ref === 'home') return this.homeTab;
        if (ref === 'help') return this._helpTab();
        const m = /^(table|report|notebook):(\d+)$/.exec(String(ref || ''));
        const obj = m ? made[m[1]][Number(m[2])] : null;
        if (!obj) return null;
        return m[1] === 'notebook' ? this.tabs.find((x) => x.notebook === obj) || null : this.tabOf(obj);
      };
      const front = j.layout ? this.dock.arrange(j.layout, find) : null;
      const first = front || this.tabs.find((x) => x.kind === 'table');
      if (first) this.showTab(first);
      const nbs = (j.notebooks || []).length;
      SM.ui.toast(`Opened the project: ${(j.tables || []).length} tables, ${(j.reports || []).length} reports${nbs ? `, ${nbs} notebook${nbs > 1 ? 's' : ''}` : ''}`);
    }

    /* ---- reports ------------------------------------------------------------ */
    launch(id) {
      const p = platforms.get(id);
      if (!p) { SM.ui.toast(`No platform ${id}`, { error: true }); return; }
      const t = p.needsTable === false ? this.current : this.requireTable();
      if (!t && p.needsTable !== false) return;
      if (!p.launch || (p.needsTable === false && !(p.launch.roles || []).length)) { this.openReport(p, { roles: {}, options: {} }, t); return; }
      if (!t) { SM.ui.toast('This analysis needs a table: open one first.'); return; }
      SM.launch.open({ platform: p, table: t, onOK: (spec) => this.openReport(p, spec, t) });
    }

    openReport(platform, spec, table, { show = true } = {}) {
      if (platform.needsTable === false && !(spec && Object.values(spec.roles || {}).some((v) => v && v.length))) table = null;
      const r = new SM.report.Report(this, platform, table ? withNames(spec, table) : JSON.parse(JSON.stringify(spec || {})), table);
      this.reports.push(r);
      const tab = this._addTab({ kind: 'report', title: r.title, view: r.el, report: r });
      tab.btn.title = table ? `${table.name} – ${r.title}` : r.title;
      if (show) this.showTab(tab);
      r.run();
      this._renderHome();
      return r;
    }

    retitle(r) {
      const tab = this.tabOf(r);
      if (tab) { tab.titleEl.textContent = r.title; tab.title = r.title; }
    }

    closeReport(r) {
      const tab = this.tabOf(r);
      r.close();
      this.reports.splice(this.reports.indexOf(r), 1);
      if (tab) this._removeTab(tab);
      this._renderHome();
    }

    /* ---- menus ---------------------------------------------------------------- */
    menuItems(name) {
      const core = (this[`menu${name}`] ? this[`menu${name}`]() : []);
      const reg = [];
      for (const p of platforms.values()) {
        if (!p.menu || p.hidden) continue;
        reg.push({ path: p.menu, order: p.order ?? 500, item: { label: `${p.label}${p.launch ? '…' : ''}`, action: () => this.launch(p.id), title: p.about || null } });
      }
      for (const c of commands) {
        const item = { label: c.label, disabled: c.enabled ? !c.enabled(this) : false, key: c.key || null, title: c.about || null };
        if (c.submenu) item.submenu = () => c.submenu(this, null); else item.action = () => c.action(this);
        reg.push({ path: c.menu, order: c.order ?? 500, item });
      }
      return buildMenu(name, core, reg);
    }

    menuFile() {
      const ex = Object.entries(SM.io.EXAMPLES).map(([k, v]) => ({ label: v.label, action: () => this.openExample(k), title: v.about }));
      return [
        { order: 10, label: 'New Data Table', action: () => this.newTable() },
        { order: 20, label: 'Open…', key: 'CSV, Excel, Stata, SAS, JMP', action: () => this.fileInput.click(), title: 'A table (CSV, text, Excel, Stata, SAS, JMP), a project, a notebook (.ipynb, .py) or a JSL script to convert (.jsl)' },
        { order: 30, label: 'Examples', submenu: ex },
        { order: 40, label: 'statsmodels Datasets…', action: () => this.datasetsDialog() },
        { order: 110, label: 'Save Table (.json)', action: () => this.exportTable('json'), disabled: !this.current },
        { order: 120, label: 'Export', disabled: !this.current, submenu: [
          { label: 'CSV (comma separated)', action: () => this.exportTable('csv') },
          { label: 'Tab separated text', action: () => this.exportTable('tsv') },
          { label: 'Excel workbook (.xlsx)', action: () => this.exportTable('xlsx') },
        ] },
        { order: 130, label: 'Save Project (tables, reports, notebooks)', action: () => this.saveProject(), disabled: !this.tables.length && !(SM.notebook && SM.notebook.notebooks.length) },
        { order: 140, label: 'Open Project…', action: () => this.fileInput.click() },
        { order: 210, label: 'Close Table', action: () => this.current && this.closeTable(this.current), disabled: !this.current },
        { order: 220, label: 'Close All Reports', action: () => { for (const r of this.reports.slice()) this.closeReport(r); }, disabled: !this.reports.length },
      ];
    }

    menuEdit() {
      const t = this.current;
      const g = this.grid;
      const u = this.undoStack[this.undoStack.length - 1], r = this.redoStack[this.redoStack.length - 1];
      return [
        { order: 1, label: u ? `Undo ${u.label}` : 'Undo', key: 'ctrl Z', disabled: !u, action: () => this.undo() },
        { order: 2, label: r ? `Redo ${r.label}` : 'Redo', key: 'ctrl shift Z', disabled: !r, action: () => this.redo() },
        { order: 10, label: 'Copy', key: 'ctrl C', disabled: !t, action: () => { this.showTab(this.tabOf(t)); SM.ui.toast('In the grid: ctrl/⌘+C copies the selected rows or the cell'); } },
        { order: 20, label: 'Paste', key: 'ctrl V', disabled: !t, action: () => { this.showTab(this.tabOf(t)); SM.ui.toast('In the grid: click the cell to paste at, then ctrl/⌘+V'); } },
        { order: 110, label: 'Select All Rows', disabled: !t, action: () => t.select(Array.from({ length: t.nrows }, (_, i) => i)) },
        { order: 120, label: 'Deselect All', disabled: !t, action: () => { t.select([]); if (g) { g.colSel.clear(); g.refresh(); this.panels.renderColumns(); } } },
        { order: 130, label: 'Go to Row…', disabled: !t, action: () => this.goToRow() },
      ];
    }

    menuTables() { return []; }

    menuRows() { return this.rowsMenuItems().map((it, i) => (it ? { order: it.order ?? (i + 1) * 10, ...it } : it)); }

    menuCols() { return this.colsMenuItems(); }

    menuDOE() { return []; }
    menuAnalyze() { return []; }
    menuGraph() { return []; }

    menuHelp() {
      return [
        { order: 10, label: 'Help for This Page', action: () => this.showHelp() },
        { order: 20, label: 'Python Engine…', action: () => this.engineDialog() },
        { order: 110, label: 'statsmodels Documentation (new tab)', action: () => window.open('https://www.statsmodels.org/stable/index.html', '_blank', 'noopener') },
      ];
    }

    /* The Rows menu, also the Rows panel's red triangle and a row's right
       click. Acts on the selected rows. */
    rowsMenuItems() {
      const t = this.current;
      const sel = t ? t.selectedRows() : [];
      const none = !t || !sel.length;
      const all = t ? Array.from({ length: t.nrows }, (_, i) => i) : [];
      const toggleOn = (flag) => { const on = !sel.every((r) => t.has(r, flag)); this.record(t, `${on ? '' : 'un'}${flag === 'excluded' ? 'exclude' : flag === 'hidden' ? 'hide' : 'label'} rows`.replace(/^./, (x) => x.toUpperCase())); t.setState(sel, flag, on); };
      const colors = SM.util.PALETTE.map((c, i) => ({ label: ['Blue', 'Orange', 'Green', 'Red', 'Purple', 'Teal', 'Gold', 'Brown', 'Pink', 'Grey', 'Cyan', 'Violet'][i], swatch: c, action: () => { this.record(t, 'Colors'); t.setColor(sel, i); } }));
      colors.unshift({ label: 'No Color', action: () => { this.record(t, 'Colors'); t.setColor(sel, -1); } });
      const markers = SM.report.SYMBOLS.map((s, i) => ({ label: s.replace('-', ' '), action: () => { this.record(t, 'Markers'); t.setMarker(sel, i); } }));
      markers.unshift({ label: 'Default Marker', action: () => { this.record(t, 'Markers'); t.setMarker(sel, -1); } });
      return [
        { order: 10, label: 'Row Selection', disabled: !t, submenu: () => [
          { label: 'Select All Rows', action: () => t.select(all) },
          { label: 'Invert Row Selection', action: () => t.toggleState(all, 'selected') },
          { label: 'Select Where…', action: () => this.selectWhere() },
          { label: 'Select Randomly…', action: () => this.selectRandomly() },
          { separator: true },
          { label: 'Select Excluded', action: () => t.select(t.rowsWith('excluded')) },
          { label: 'Select Hidden', action: () => t.select(t.rowsWith('hidden')) },
          { label: 'Select Labeled', action: () => t.select(t.rowsWith('labeled')) },
          { separator: true },
          { label: 'Clear Row Selection', action: () => t.select([]) },
          { label: 'Name Selection in Column…', action: () => this.nameSelection() },
          { label: 'Go to Row…', action: () => this.goToRow() },
        ] },
        { order: 20, label: 'Clear Row States', disabled: !t, action: () => { this.record(t, 'Clear Row States'); t.clearRowStates(); } },
        { order: 110, label: 'Exclude/Unexclude', disabled: none, action: () => toggleOn('excluded') },
        { order: 120, label: 'Hide/Unhide', disabled: none, action: () => toggleOn('hidden') },
        { order: 130, label: 'Label/Unlabel', disabled: none, action: () => toggleOn('labeled') },
        { order: 140, label: 'Hide and Exclude', disabled: none, action: () => { this.record(t, 'Hide and Exclude'); t.setState(sel, 'hidden', true); t.setState(sel, 'excluded', true); } },
        { order: 150, label: 'Colors', disabled: none, submenu: colors },
        { order: 160, label: 'Markers', disabled: none, submenu: markers },
        { order: 170, label: 'Color or Mark by Column…', disabled: !t, action: () => this.colorByColumn() },
        { order: 180, label: 'Data Filter', checked: !!(t && t.dataFilter), disabled: !t, action: () => this.toggleDataFilter() },
        { order: 210, label: 'Add Rows…', disabled: !t, action: () => this.addRowsDialog() },
        { order: 220, label: `Delete ${sel.length || ''} Selected Rows`.replace('  ', ' '), disabled: none, action: () => this.deleteRows() },
        { order: 230, label: 'Move Selected Rows to Top', disabled: none, action: () => { this.record(t, 'Move Rows'); const set = new Set(sel); t._reorder([...sel, ...all.filter((r) => !set.has(r))]); t._changed('data', { moved: true }); } },
        { order: 240, label: 'Subset of Selected Rows', disabled: none, action: () => this.addTable(t.subset(sel, null, `${t.name} subset`)) },
      ];
    }

    rowMenu() { return this.rowsMenuItems().filter((it) => it.order >= 100 && it.order !== 180); }

    /* Rows > Data Filter: a filter of the whole table, docked in the side
       panels; it selects the matching rows (and can hide and exclude the rest). */
    toggleDataFilter(on) {
      const t = this.requireTable();
      if (!t) return;
      const want = on != null ? on : !t.dataFilter;
      if (want && !t.dataFilter) t.dataFilter = { entries: [], select: true, show: false, include: false };
      if (!want && t.dataFilter) {
        const df = t.dataFilter;
        const all = Array.from({ length: t.nrows }, (_, i) => i);
        if (SM.report.filterActive(df.entries)) {
          if (df.show) t.setState(all, 'hidden', false);
          if (df.include) t.setState(all, 'excluded', false);
        }
        t.dataFilter = null;
      }
      this.panels.renderDataFilter();
      this.host.classList.add('side-open');
    }

    /* The Cols menu, also the Columns panel's red triangle. */
    colsMenuItems() {
      const t = this.current;
      const sel = this.selectedColumns();
      const one = sel.length === 1 ? sel[0] : null;
      const types = ['continuous', 'ordinal', 'nominal'].map((m) => ({
        label: TYPE_LABEL[m], checked: sel.length > 0 && sel.every((c) => c.modelingType === m), disabled: !sel.length || (m === 'continuous' && sel.some((c) => !c.isNumeric)),
        action: () => { this.record(t, 'Modeling Type'); sel.forEach((c) => t.setType(c.id, { modelingType: m })); },
      }));
      const items = [
        { order: 10, label: 'New Column…', disabled: !t, action: () => this.newColumn() },
        { order: 20, label: 'Column Info…', disabled: !one, action: () => this.columnInfo(one) },
        { order: 30, label: 'Modeling Type', disabled: !sel.length, submenu: types },
        { order: 40, label: one && one.role === 'label' ? 'Unlabel' : 'Label', disabled: !one, action: () => { const on = one.role !== 'label'; for (const c of t.columns) if (c.role === 'label') c.role = null; if (on) one.role = 'label'; t._changed('schema', { label: one.id }); } },
        { order: 50, label: 'Reorder Columns', disabled: !t, submenu: () => [
          { label: 'Move Selected to First', disabled: !sel.length, action: () => sel.slice().reverse().forEach((c) => t.moveColumn(c.id, 0)) },
          { label: 'Move Selected to Last', disabled: !sel.length, action: () => sel.forEach((c) => t.moveColumn(c.id, t.columns.length)) },
          { label: 'Reverse Order', action: () => { t.columns.reverse(); t._changed('schema', { reordered: true }); } },
          { label: 'Sort by Name', action: () => { t.columns.sort((a, b) => SM.table.collator.compare(a.name, b.name)); t._changed('schema', { reordered: true }); } },
          { label: 'Sort by Modeling Type', action: () => { const o = { continuous: 0, ordinal: 1, nominal: 2 }; t.columns.sort((a, b) => o[a.modelingType] - o[b.modelingType]); t._changed('schema', { reordered: true }); } },
        ] },
        { order: 60, label: `Delete ${sel.length > 1 ? `${sel.length} Columns` : 'Column'}`, disabled: !sel.length, action: () => this.deleteColumns(sel) },
      ];
      return items;
    }

    columnMenu(c) {
      const t = this.current;
      const sorts = [{ label: 'Ascending', action: () => { this.record(t, `Sort by ${c.name}`); t.sortBy([{ col: c.id }]); } }, { label: 'Descending', action: () => { this.record(t, `Sort by ${c.name}`); t.sortBy([{ col: c.id, desc: true }]); } }];
      const extra = commands.filter((x) => x.context === 'column').map((x) => (x.submenu
        ? { label: x.label, submenu: () => x.submenu(this, c), disabled: x.enabled ? !x.enabled(this, c) : false }
        : { label: x.label, action: () => x.action(this, c), disabled: x.enabled ? !x.enabled(this, c) : false }));
      return [
        { head: c.name },
        { label: 'Column Info…', action: () => this.columnInfo(c) },
        { label: 'Modeling Type', submenu: () => ['continuous', 'ordinal', 'nominal'].map((m) => ({ label: TYPE_LABEL[m], checked: c.modelingType === m, disabled: m === 'continuous' && !c.isNumeric, action: () => { this.record(t, 'Modeling Type'); t.setType(c.id, { modelingType: m }); } })) },
        { label: 'Sort', submenu: sorts },
        ...extra,
        { separator: true },
        { label: 'Insert Column Before', action: () => this.newColumn(t.colIndex(c)) },
        { label: 'Delete Column', action: () => this.deleteColumns(this.selectedColumns().length ? this.selectedColumns() : [c]) },
      ];
    }

    tableMenu() {
      const t = this.current;
      return [
        { label: 'Rename Table…', disabled: !t, action: async () => { const v = await SM.ui.form({ title: 'Rename Table', fields: [{ key: 'name', label: 'Name', value: t.name, help: 'The name on the table\'s tab, in the Table panel and in the titles of its reports, which are renamed with it. Saved files are named after it.' }] }); if (v && v.name.trim()) this.renameTable(t, v.name.trim()); } },
        { label: 'Table Notes…', disabled: !t, action: async () => { const v = await SM.ui.form({ title: 'Table Notes', fields: [{ key: 'notes', label: 'Notes', type: 'textarea', value: t.notes, help: 'Free text kept with the table, such as what the rows are and what the columns mean. The Table panel shows its beginning; Save Table and Save Project keep it.' }, { key: 'source', label: 'Source', value: t.source, full: true, help: 'Where the table came from: the file it was read from, or a dataset\'s origin and copyright note. Shown in the Table panel and kept with the table.' }] }); if (v) { t.notes = v.notes; t.source = v.source; this.panels.renderTable(); } } },
        { separator: true },
        { label: 'Save Table (.json)', disabled: !t, action: () => this.exportTable('json') },
        { label: 'Export CSV', disabled: !t, action: () => this.exportTable('csv') },
        { label: 'Export Excel', disabled: !t, action: () => this.exportTable('xlsx') },
        { separator: true },
        { label: 'Close Table', disabled: !t, action: () => this.closeTable(t) },
      ];
    }

    /* ---- rows and columns: the dialogs ---------------------------------------- */
    async newColumn(at = null) {
      const t = this.requireTable();
      if (!t) return;
      const v = await SM.ui.form({
        title: 'New Column', info: 'cols:new',
        fields: [
          { key: 'name', label: 'Column name', value: t.uniqueName('Column'), help: 'The heading of the column and its name in launch dialogs and formulas. A name the table already has gets a number added.' },
          { key: 'dataType', label: 'Data type', type: 'select', value: 'numeric', choices: [['numeric', 'Numeric'], ['character', 'Character']], help: 'What the cells hold: Numeric for numbers (and dates, which are numbers underneath), Character for text. A character column is ordinal or nominal.' },
          { key: 'modelingType', label: 'Modeling type', type: 'select', value: 'continuous', choices: [['continuous', 'Continuous'], ['ordinal', 'Ordinal'], ['nominal', 'Nominal']], help: 'How analyses treat the values: Continuous as numbers on a scale, Ordinal as ordered categories, Nominal as unordered categories. Click the icon in the Columns panel to change it later.' },
          { key: 'init', label: 'Initial values', type: 'select', value: 'missing', choices: [['missing', 'Missing'], ['constant', 'Constant'], ['sequence', 'Sequence 1, 2, 3…'], ['random', 'Random normal (0, 1)'], ['uniform', 'Random uniform (0, 1)']], help: 'What the rows start with: missing values, the same value in every row (the Constant below), the row numbers, or random draws, normal with mean 0 and standard deviation 1, or uniform between 0 and 1 (a new draw each time).' },
          { key: 'constant', label: 'Constant', value: '', help: 'The value of every row when Initial values is Constant: a number for a numeric column, any text for a character one. Not used otherwise.' },
          SM.formula ? { key: 'formula', label: 'Formula', value: '', placeholder: 'e.g. log(:height) or :weight / (:height/100)^2', full: true, hint: 'Optional. A formula column recalculates when the columns it uses change.', help: 'Optional. A formula computes the column from other columns, row by row, in place of the initial values, and computes it again when they change. Columns are written `:name`; Cols > Formula edits it later, with the list of functions.' } : null,
          { key: 'count', label: 'Number of columns to add', type: 'number', value: 1, help: 'How many columns to add, 1 to 1000, all alike; the names get 2, 3, … after the first.' },
        ].filter(Boolean),
        validate: (x) => (x.dataType === 'character' && x.modelingType === 'continuous' ? 'A character column is nominal or ordinal.' : null),
      });
      if (!v) return;
      const n = t.nrows;
      // (random draws are new for each column)
      const initial = (k) => {
        if (v.init === 'constant') return new Array(n).fill(v.dataType === 'numeric' ? SM.table.toNumber(v.constant) : v.constant);
        if (v.init === 'sequence') return Array.from({ length: n }, (_, i) => (v.dataType === 'numeric' ? i + 1 : String(i + 1)));
        if (v.init === 'random' || v.init === 'uniform') { const r = SM.util.rng(`${v.name}${k}${Date.now()}`); return Array.from({ length: n }, () => (v.init === 'random' ? r.normal() : r.u())); }
        return new Array(n).fill(v.dataType === 'numeric' ? NaN : null);
      };
      const count = Math.max(1, Math.min(1000, Math.round(Number(v.count) || 1)));
      this.record(t, count > 1 ? 'New Columns' : 'New Column');
      let first = null;
      for (let k = 0; k < count; k++) {
        const c = t.addColumn({ name: v.name.trim() || 'Column', dataType: v.dataType, modelingType: v.modelingType, values: initial(k) }, at == null ? null : at + k);
        if (v.formula && SM.formula) {
          try { SM.formula.apply(t, c, v.formula); } catch (e) { SM.ui.toast(`Formula: ${e.message}`, { error: true }); break; }
        }
        first = first || c;
      }
      this.showTab(this.tabOf(t));
      return first;
    }

    deleteColumns(cols) {
      const t = this.current;
      if (!t || !cols.length) return;
      const used = this.reports.filter((r) => r.table === t && Object.values(r.spec.roles || {}).flat().some((id) => cols.some((c) => c.id === id)));
      const go = () => { this.record(t, `Delete ${cols.length > 1 ? 'Columns' : 'Column'}`); for (const c of cols) t.removeColumn(c.id); const g = this.grid; if (g) { g.colSel.clear(); g.refresh(); } };
      if (used.length) {
        SM.ui.dialog({ title: 'Delete columns', narrow: true, body: el('p', { class: 'sm-dialog-lead', text: `${cols.map((c) => c.name).join(', ')} ${cols.length > 1 ? 'are' : 'is'} used by ${used.length} report${used.length > 1 ? 's' : ''}, which will show an error when redone.` }), buttons: [{ label: 'Cancel' }, { label: 'Delete', primary: true, action: go }] });
      } else go();
    }

    columnInfo(c) {
      const t = this.current;
      if (!t || !c) return;
      const name = el('input', { type: 'text', value: c.name, id: SM.util.uid('ci') });
      const dtype = el('select', null, el('option', { value: 'numeric', text: 'Numeric' }), el('option', { value: 'character', text: 'Character' }));
      dtype.value = c.dataType;
      const mtype = el('select', null, ...['continuous', 'ordinal', 'nominal'].map((m) => el('option', { value: m, text: TYPE_LABEL[m] })));
      mtype.value = c.modelingType;
      const fkind = el('select', null, ...[['best', 'Best'], ['fixed', 'Fixed decimals'], ['percent', 'Percent'], ['date', 'Date (yyyy-mm-dd)'], ['datetime', 'Date and time']].map(([v, l]) => el('option', { value: v, text: l })));
      fkind.value = (c.format && c.format.kind) || 'best';
      const digits = el('input', { type: 'text', inputmode: 'numeric', size: 4, value: c.format && c.format.digits != null ? String(c.format.digits) : '2' });
      const notes = el('textarea', { rows: 3 });
      notes.value = c.notes || '';
      const isLabel = el('input', { type: 'checkbox' });
      isLabel.checked = c.role === 'label';
      const sl = c.specLimits || {};
      const specIn = (key, label) => { const i = el('input', { type: 'text', inputmode: 'decimal', size: 8, 'aria-label': label, placeholder: label }); if (sl[key] != null) i.value = String(sl[key]); return i; };
      const lsl = specIn('lsl', 'LSL'), target = specIn('target', 'Target'), usl = specIn('usl', 'USL');
      // Value order, for categorical columns
      let order = t.levels(c).slice();
      const orderList = el('ul', { class: 'sm-role-list sm-orderlist', role: 'listbox', 'aria-label': 'Value order' });
      let orderSel = -1;
      const renderOrder = () => {
        orderList.replaceChildren(...order.slice(0, 200).map((v, i) => { const li = el('li', { role: 'option', text: SM.grid.cellText(c, v), 'aria-selected': String(i === orderSel) }); if (i === orderSel) li.classList.add('is-selected'); li.addEventListener('click', () => { orderSel = i; renderOrder(); }); return li; }));
        if (order.length > 200) orderList.append(el('li', { text: `… ${order.length - 200} more` }));
      };
      renderOrder();
      const mv = (d) => { if (orderSel < 0) return; const j = orderSel + d; if (j < 0 || j >= order.length) return; [order[orderSel], order[j]] = [order[j], order[orderSel]]; orderSel = j; renderOrder(); };
      const ob = (label, fn) => { const b = el('button', { type: 'button', class: 'sm-btn small', text: label }); b.addEventListener('click', fn); return b; };
      const orderBox = el('div', { class: 'sm-orderbox' }, orderList, el('div', { class: 'sm-orderbtns' },
        ob('Move Up', () => mv(-1)), ob('Move Down', () => mv(1)), ob('Reverse', () => { order.reverse(); renderOrder(); }), ob('Sort', () => { order = SM.table.sortLevels(order, c.isNumeric); renderOrder(); })));
      const formulaRow = c.formula ? el('div', { class: 'full sm-dialog-lead' }, 'Formula: ', el('code', { text: c.formula.expr || '' }), SM.formula ? ob('Edit Formula…', () => { dlg.close(); SM.formula.edit(t, c); }) : null) : null;
      const summary = columnSummary(t, c);
      // the column properties (Missing Value Codes, Value Labels, Profit Matrix), SM.colprops
      const props = SM.colprops ? SM.colprops.editors(t, c) : null;
      const grid = el('div', { class: 'sm-form' },
        el('label', { for: name.id, text: 'Column name' }), name,
        el('label', { text: 'Data type' }), dtype,
        el('label', { text: 'Modeling type' }), mtype,
        el('label', { text: 'Format' }), el('div', { class: 'sm-inline' }, fkind, el('span', { text: 'decimals' }), digits),
        el('label', { text: 'Label column' }), el('label', { class: 'sm-inline' }, isLabel, 'Use the values as row labels in graphs'),
        el('label', { text: 'Value order' }), c.isCategorical || order.length <= 60 ? orderBox : el('span', { class: 'sm-ob-note', text: `${order.length} distinct values; the order applies to ordinal and nominal columns` }),
        c.isNumeric ? el('label', { text: 'Spec Limits' }) : null, c.isNumeric ? el('div', { class: 'sm-inline' }, lsl, target, usl) : null,
        ...(props ? props.nodes : []),
        el('label', { text: 'Notes' }), notes,
        formulaRow,
        el('div', { class: 'full sm-ob-note', text: summary }));
      const msg = el('div', { class: 'sm-launch-msg' });
      const dlg = SM.ui.dialog({
        title: `Column Info: ${c.name}`, body: el('div', null, grid, msg), info: 'cols:info',
        buttons: [
          { label: 'Cancel' },
          { label: 'OK', primary: true, action: () => {
            const perr = props ? props.check() : null;
            if (perr) { msg.textContent = perr; return false; }
            if (dtype.value === 'character' && mtype.value === 'continuous') { msg.textContent = 'A character column is nominal or ordinal.'; return false; }
            this.record(t, 'Column Info');
            if (dtype.value !== c.dataType) t.setType(c.id, { dataType: dtype.value, modelingType: mtype.value });
            else if (mtype.value !== c.modelingType) t.setType(c.id, { modelingType: mtype.value });
            if (props) props.apply();
            const d = Number(digits.value);
            c.format = fkind.value === 'best' ? null : { kind: fkind.value, digits: Number.isFinite(d) ? Math.max(0, Math.min(12, d)) : 2 };
            c.notes = notes.value;
            if (c.isNumeric) {
              const num = (i) => { const x = i.value.trim() === '' ? null : SM.table.toNumber(i.value.replace(',', '.')); return Number.isFinite(x) ? x : null; };
              const lim = { lsl: num(lsl), target: num(target), usl: num(usl) };
              c.specLimits = lim.lsl == null && lim.usl == null && lim.target == null ? null : lim;
            }
            if (isLabel.checked && c.role !== 'label') { for (const x of t.columns) if (x.role === 'label') x.role = null; c.role = 'label'; }
            else if (!isLabel.checked && c.role === 'label') c.role = null;
            const lv = t.levels(c);
            if (order.length && order.join('\u0001') !== lv.join('\u0001')) c.valueOrder = order.slice();
            if (name.value.trim() && name.value.trim() !== c.name) t.renameColumn(c.id, name.value.trim());
            else t._changed('schema', { info: c.id });
            return true;
          } },
        ],
      });
    }

    async selectWhere() {
      const t = this.requireTable();
      if (!t) return;
      const ops = [['eq', 'equals'], ['ne', 'does not equal'], ['gt', 'is greater than'], ['ge', 'is greater than or equal to'], ['lt', 'is less than'], ['le', 'is less than or equal to'],
        ['contains', 'contains'], ['ncontains', 'does not contain'], ['starts', 'starts with'], ['missing', 'is missing'], ['nmissing', 'is not missing']];
      const pre = this.selectedColumns()[0];
      const v = await SM.ui.form({
        title: 'Select Where', info: 'rows:selectwhere',
        fields: [
          { key: 'col', label: 'Column', type: 'select', value: pre ? pre.id : t.columns[0]?.id, choices: t.columns.map((c) => [c.id, c.name]), help: 'The column whose values are tested; it starts at the selected column.' },
          { key: 'op', label: 'Condition', type: 'select', value: 'eq', choices: ops, help: 'How each value is compared with Value. On a numeric column, equals and the greater and less conditions compare numbers (a date column reads Value as a date); on a character column they compare the text, numbers within it in natural order. contains, does not contain and starts with look at the text as the grid shows it, ignoring case. is missing and is not missing need no Value.' },
          { key: 'value', label: 'Value', value: '', help: 'What the values are compared with: a number or a date (yyyy-mm-dd) for a numeric column, text for a character one. A missing value matches no condition but is missing.' },
          { key: 'mode', label: 'Current selection', type: 'select', value: 'replace', choices: [['replace', 'Clear it'], ['add', 'Extend it'], ['restrict', 'Restrict it']], help: 'Clear it: only the matching rows are selected. Extend it: the matching rows are added to the selection. Restrict it: of the rows selected now, only those that match stay selected.' },
        ],
      });
      if (!v) return;
      const c = t.col(v.col);
      const num = c.isNumeric;
      const target = num ? (c.format && /date/.test(c.format.kind || '') ? SM.io.parseDate(v.value) : SM.table.toNumber(v.value)) : v.value;
      const txt = String(v.value).toLowerCase();
      const test = (x) => {
        const miss = SM.table.isMissing(x);
        if (v.op === 'missing') return miss;
        if (v.op === 'nmissing') return !miss;
        if (miss) return false;
        const s = SM.grid.cellText(c, x).toLowerCase();
        switch (v.op) {
          case 'eq': return num ? x === target : String(x) === v.value;
          case 'ne': return num ? x !== target : String(x) !== v.value;
          case 'gt': return num ? x > target : SM.table.collator.compare(String(x), v.value) > 0;
          case 'ge': return num ? x >= target : SM.table.collator.compare(String(x), v.value) >= 0;
          case 'lt': return num ? x < target : SM.table.collator.compare(String(x), v.value) < 0;
          case 'le': return num ? x <= target : SM.table.collator.compare(String(x), v.value) <= 0;
          case 'contains': return s.includes(txt);
          case 'ncontains': return !s.includes(txt);
          case 'starts': return s.startsWith(txt);
          default: return false;
        }
      };
      const hits = [];
      for (let i = 0; i < t.nrows; i++) if (test(c.values[i])) hits.push(i);
      if (v.mode === 'restrict') { const cur = new Set(t.selectedRows()); t.select(hits.filter((r) => cur.has(r))); }
      else t.select(hits, v.mode === 'add' ? 'add' : 'replace');
      SM.ui.toast(`${hits.length} rows match; ${t.counts().selected} selected`);
    }

    async selectRandomly() {
      const t = this.requireTable();
      if (!t) return;
      const v = await SM.ui.form({ title: 'Select Randomly', lead: 'Select rows at random, without replacement, in place of the current selection.', fields: [{ key: 'n', label: 'Sampling rate (below 1) or number of rows', type: 'number', value: 0.1, helpLabel: 'Sampling rate or number of rows', help: 'Below 1: that share of the table\'s rows, rounded to whole rows (0.1 selects a tenth). 1 or more: that many rows, at most all of them. Excluded and hidden rows can be drawn too.' }, { key: 'seed', label: 'Seed (empty: a new draw)', value: '', helpLabel: 'Seed', help: 'Any text or number. The same seed with the same number of rows selects the same rows again, so a sample can be repeated; empty draws new rows each time.' }] });
      if (!v || !(v.n > 0)) return;
      const k = v.n < 1 ? Math.round(v.n * t.nrows) : Math.min(t.nrows, Math.round(v.n));
      const r = SM.util.rng(v.seed || String(Date.now()));
      const idx = Array.from({ length: t.nrows }, (_, i) => i);
      for (let i = idx.length - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [idx[i], idx[j]] = [idx[j], idx[i]]; }
      t.select(idx.slice(0, k).sort((a, b) => a - b));
    }

    /* A column that marks the selected rows, as JMP's Name Selection in Column. */
    async nameSelection() {
      const t = this.requireTable();
      if (!t) return;
      const v = await SM.ui.form({ title: 'Name Selection in Column', fields: [
        { key: 'name', label: 'Column name', value: t.uniqueName('Selected'), help: 'The new column, nominal, that records which rows are selected now. It does not follow later changes of the selection.' },
        { key: 'yes', label: 'Selected', value: '1', help: 'The value in the rows selected now.' }, { key: 'no', label: 'Unselected', value: '0', help: 'The value in the other rows. When both values are numbers the column is numeric, otherwise character.' },
      ] });
      if (!v) return;
      const numeric = [v.yes, v.no].every((x) => Number.isFinite(SM.table.toNumber(x)));
      const vals = Array.from({ length: t.nrows }, (_, i) => (t.has(i, 'selected') ? v.yes : v.no));
      this.record(t, 'Name Selection in Column');
      t.addColumn({ name: v.name || 'Selected', dataType: numeric ? 'numeric' : 'character', modelingType: 'nominal', values: numeric ? vals.map(Number) : vals });
    }

    async goToRow() {
      const t = this.requireTable();
      if (!t) return;
      const v = await SM.ui.form({ title: 'Go to Row', fields: [{ key: 'row', label: 'Row number', type: 'number', value: 1, help: 'The row to show: the grid scrolls to it, puts the cursor on it and selects it. A number past the end goes to the last row.' }] });
      if (!v || !(v.row >= 1)) return;
      const r = Math.min(t.nrows, Math.round(v.row)) - 1;
      this.showTab(this.tabOf(t));
      const g = this.grid;
      g.cursor.row = r;
      g._reveal();
      g.refresh();
      t.select([r]);
    }

    async addRowsDialog() {
      const t = this.requireTable();
      if (!t) return;
      const v = await SM.ui.form({ title: 'Add Rows', fields: [{ key: 'n', label: 'How many rows', type: 'number', value: 1, help: 'How many empty rows to insert, at most 100,000 at a time. Their cells are missing until values are typed or pasted in; formula columns fill theirs.' }, { key: 'where', label: 'Where', type: 'select', value: 'end', choices: [['end', 'At the end'], ['start', 'At the start'], ['after', 'After the first selected row']], help: 'At the end of the table, before the first row, or after the first selected row (at the end when no row is selected).' }] });
      if (!v || !(v.n >= 1)) return;
      const sel = t.selectedRows();
      const at = v.where === 'start' ? 0 : v.where === 'after' && sel.length ? sel[0] + 1 : t.nrows;
      this.record(t, 'Add Rows');
      t.addRows(Math.min(100000, Math.round(v.n)), at);
    }

    deleteRows() {
      const t = this.current;
      const sel = t ? t.selectedRows() : [];
      if (!sel.length) return;
      SM.ui.dialog({ title: 'Delete rows', narrow: true, body: el('p', { class: 'sm-dialog-lead', text: `Delete ${sel.length} selected row${sel.length > 1 ? 's' : ''} from ${t.name}? Edit > Undo brings them back; Rows > Exclude/Unexclude leaves rows out of analyses without deleting them.` }), buttons: [{ label: 'Cancel' }, { label: 'Delete', primary: true, action: () => { this.record(t, 'Delete Rows'); t.deleteRows(sel); } }] });
    }

    async colorByColumn() {
      const t = this.requireTable();
      if (!t) return;
      const pre = this.selectedColumns()[0];
      const v = await SM.ui.form({
        title: 'Color or Mark by Column', info: 'rows:colorby',
        fields: [
          { key: 'col', label: 'Column', type: 'select', value: pre ? pre.id : t.columns[0]?.id, choices: t.columns.map((c) => [c.id, `${c.name} (${TYPE_LABEL[c.modelingType].toLowerCase()})`]), help: 'A nominal or ordinal column gives each level a colour and a marker of its own, in value order. A continuous column gives a colour ramp from its smallest value (blue) to its largest (red), and five markers from low to high. Rows with a missing value lose their colour or marker.' },
          { key: 'color', label: 'Set colours', type: 'check', value: true, help: 'Colour every row by the column. The colours show in every graph of the table, and as a dot by the row number in the grid.' },
          { key: 'marker', label: 'Set markers', type: 'check', value: false, help: 'Give every row a marker (the shape of its points in graphs) by the column.' },
        ],
      });
      if (!v) return;
      this.record(t, 'Color or Mark by Column');
      const c = t.col(v.col);
      const all = Array.from({ length: t.nrows }, (_, i) => i);
      if (c.isCategorical || !c.isNumeric) {
        const lv = t.levels(c);
        const m = new Map(lv.map((x, i) => [x, i]));
        for (const r of all) {
          const k = m.get(c.values[r]);
          if (v.color) t.color[r] = k == null ? -1 : k % SM.util.PALETTE.length;
          if (v.marker) t.marker[r] = k == null ? -1 : k % SM.report.SYMBOLS.length;
        }
      } else {
        let lo = Infinity, hi = -Infinity;
        for (const x of c.values) if (Number.isFinite(x)) { if (x < lo) lo = x; if (x > hi) hi = x; }
        for (const r of all) {
          const x = c.values[r];
          if (v.color) t.color[r] = Number.isFinite(x) ? 100 + Math.round(63 * (hi > lo ? (x - lo) / (hi - lo) : 0.5)) : -1;
          if (v.marker) t.marker[r] = Number.isFinite(x) ? Math.min(4, Math.floor(5 * (hi > lo ? (x - lo) / (hi - lo) : 0))) : -1;
        }
      }
      t.emit('rowstate', { kind: 'color' });
    }

    /* ---- the engine ---------------------------------------------------------------- */
    engineDialog() {
      const e = SM.engine;
      const lines = [['State', e.state], ['Status', e.text]];
      if (e.state === 'loading') lines.push(['Loading for', duration(e.elapsed || 0)], ['Last news from the engine', `${duration(e.quiet || 0)} ago`]);
      if (e.versions) for (const [k, v] of Object.entries(e.versions)) lines.push([k, v]);
      if (e.loadSeconds) lines.push(['Loaded in', `${e.loadSeconds.toFixed(1)} s`]);
      const body = el('div', null,
        el('p', { class: 'sm-dialog-lead', text: 'The statistics run in Python in this browser: Pyodide (CPython compiled to WebAssembly) with numpy, scipy, pandas and statsmodels, in a background worker. The first visit downloads about 40 MB from the jsDelivr CDN; the browser keeps it afterwards. The data never leave the browser.' }),
        SM.report.kv(lines.map(([k, v]) => [k, String(v), 'text'])));
      if (e.failed && e.failed.length) body.append(el('p', { class: 'sm-ob-warn', text: `Analysis modules that did not load: ${e.failed.map((f) => `${f.module} (${f.error})`).join('; ')}` }));
      const log = el('pre', { class: 'sm-log', text: this.log.slice(-200).join('\n') || '(no output yet)' });
      body.append(el('details', { class: 'sm-code' }, el('summary', { text: 'Python output' }), log));
      if (e.traceback) body.append(el('details', { class: 'sm-code' }, el('summary', { text: 'Error details' }), el('pre', { text: e.traceback })));
      SM.ui.dialog({ title: 'Python Engine', body, narrow: true, info: 'engine', buttons: [{ label: 'Restart Engine', action: () => { e.restart(); } }, { label: 'Close', primary: true }] });
    }

    _engineStatus() {
      const e = SM.engine;
      this.engineEl.dataset.state = e.state;
      // while loading, how long it has taken: a slow download is then told from a stuck one
      const took = e.state === 'loading' && e.elapsed >= 5 ? ` (${duration(e.elapsed)})` : '';
      this.engineEl.textContent = e.state === 'ready' ? (e.loading || `Python · statsmodels ${e.versions.statsmodels}`) : `${e.text}${took}`;
      this.engineEl.title = e.loading || (e.slow && e.state === 'loading' ? `${e.text}${took}. Still loading: click for what it is doing.` : e.text);
      this.engineEl.dataset.loading = e.loading ? '1' : '0';
      this.engineEl.dataset.slow = e.slow && e.state === 'loading' ? '1' : '0';
      // past SLOW_AFTER (smui-engine.js) the home page says what may be wrong, once
      if (e.slow && e.state === 'loading' && !this._slowShown) { this._slowShown = true; this._renderHome(); }
      if (e.state !== 'loading') this._slowShown = false;
    }

    /* ---- home and help --------------------------------------------------------------- */
    _homeView() {
      this.homeEl = el('div', { class: 'sm-home-inner' });
      return el('div', { class: 'sm-home' }, this.homeEl);
    }

    _renderHome() {
      const h = this.homeEl;
      if (!h) return;
      h.replaceChildren();
      const openBtn = el('button', { type: 'button', class: 'sm-btn primary', text: 'Open a file…' });
      openBtn.addEventListener('click', () => this.fileInput.click());
      const dsBtn = el('button', { type: 'button', class: 'sm-btn', text: 'statsmodels datasets…' });
      dsBtn.addEventListener('click', () => this.datasetsDialog());
      const newBtn = el('button', { type: 'button', class: 'sm-btn', text: 'New empty table' });
      newBtn.addEventListener('click', () => this.newTable());
      const nbBtn = SM.notebook ? el('button', { type: 'button', class: 'sm-btn', text: 'New notebook' }) : null;
      if (nbBtn) nbBtn.addEventListener('click', () => SM.notebook.open(this));
      const jslBtn = SM.jsl ? el('button', { type: 'button', class: 'sm-btn', text: 'JSL to Python…' }) : null;
      if (jslBtn) jslBtn.addEventListener('click', () => SM.jsl.open(this));
      h.append(
        el('h2', { text: 'Statistics in the browser, with statsmodels' }),
        el('p', { text: 'Open a table, choose an analysis from the Analyze or Graph menu, cast columns into roles, and read the report. Each report is live: select points and the rows light up everywhere; exclude rows and redo; open the red triangles for more. Under every result is the Python that computes it: edit it and run it where it is, or take it to a notebook (Python > New Notebook), where the open tables are at hand. Python > JSL to Python turns a JMP script into Python.' }),
        el('div', { class: 'sm-homebtns' }, openBtn, dsBtn, newBtn, nbBtn, jslBtn),
        el('p', { class: 'sm-ob-note', text: 'CSV, tab-separated text, Excel (.xlsx), Stata (.dta), SAS (.sas7bdat, .xpt), JMP (.jmp) and this page\'s JSON tables open by drop or by File > Open, and so do notebooks (.ipynb, .py) and JSL scripts (.jsl). Nothing is uploaded: the data stay in this browser.' }),
        el('h3', { text: 'Examples (simulated for this page)' }));
      const exBox = el('div', { class: 'sm-examples' });
      for (const [k, v] of Object.entries(SM.io.EXAMPLES)) {
        const b = el('button', { type: 'button', class: 'sm-exitem' }, el('strong', { text: v.label }), el('span', { text: v.about }));
        b.addEventListener('click', () => this.openExample(k));
        exBox.append(b);
      }
      h.append(exBox);
      if (this.tables.length) {
        h.append(el('h3', { text: 'Open tables and reports' }));
        const ul = el('ul', { class: 'sm-homelist' });
        for (const t of this.tables) {
          const a = el('button', { type: 'button', class: 'sm-linkbtn', text: `${t.name} (${t.nrows} × ${t.columns.length})` });
          a.addEventListener('click', () => this.showTab(this.tabOf(t)));
          const sub = el('ul');
          for (const r of this.reports.filter((x) => x.table === t)) {
            const b = el('button', { type: 'button', class: 'sm-linkbtn', text: r.title });
            b.addEventListener('click', () => this.showTab(this.tabOf(r)));
            sub.append(el('li', null, b));
          }
          ul.append(el('li', null, tableGlyph(), a, sub.children.length ? sub : null));
        }
        h.append(ul);
      }
      const e = SM.engine;
      if (e.state === 'loading' && e.slow) {
        const restart = el('button', { type: 'button', class: 'sm-btn', text: 'Restart the engine' });
        restart.addEventListener('click', () => { e.restart(); this._renderHome(); });
        const what = el('button', { type: 'button', class: 'sm-btn', text: 'What it is doing' });
        what.addEventListener('click', () => this.engineDialog());
        // at the top, under the heading, where it is seen
        h.insertBefore(el('div', { class: 'sm-ob-warn sm-home-slow', role: 'status' },
          el('p', null, el('strong', { text: 'The Python engine is taking long to load. ' }), 'The first visit downloads about 40 MB from cdn.jsdelivr.net (the browser keeps it for the next time), which on a slow line takes a few minutes. If it does not end:'),
          el('ul', null,
            el('li', { text: 'A firewall, a company proxy or a browser extension (an ad or script blocker) may be holding the download: allow cdn.jsdelivr.net, or try another network.' }),
            el('li', { text: 'An old browser, or one short of memory, may not run it: a current Chrome, Edge, Firefox or Safari does. Other tabs closed free memory.' })),
          el('div', { class: 'sm-homebtns' }, restart, what)), h.children[1] || null);
      }
      if (e.state === 'error') {
        h.insertBefore(el('div', { class: 'sm-ob-warn sm-home-slow', role: 'status' },
          el('p', null, el('strong', { text: 'The Python engine did not start. ' }), e.text || ''),
          el('p', { text: 'Its files come from cdn.jsdelivr.net: a firewall, a company proxy or a blocker may stop them, and an old browser may lack WebAssembly or module workers. Python Engine (in the Help menu, or the status line at the top right) shows the details and can restart it.' })), h.children[1] || null);
      }
      h.append(el('p', { class: 'sm-ob-note sm-home-engine', text: e.state === 'ready' ? `Python engine ready: statsmodels ${e.versions.statsmodels}, scipy ${e.versions.scipy}, pandas ${e.versions.pandas}, numpy ${e.versions.numpy} on Python ${e.versions.python} (Pyodide ${e.versions.pyodide}), loaded in ${e.loadSeconds.toFixed(1)} s.` : `Python engine: ${e.text || 'not started'}` }));
    }

    /* The Help text is made at the start but kept hidden, so that every
       (i)'s Read more link has its target. Its tab appears when asked for
       (Help > Help for This Page, a Read more link, a dialog's Help button)
       and closes with its ×. */
    _makeHelp() {
      const view = el('div', { class: 'sm-help sm-view', role: 'tabpanel', hidden: true });
      this.helpView = view;
      this.dock.park(view);
      if (SM.help) SM.help.render(view, this); else view.append(el('div', { class: 'sm-help-inner', text: 'Help did not load.' }));
    }

    // the Help tab, opened (in the group in use) if it is not open
    _helpTab() {
      if (!this.helpView) this._makeHelp();
      if (!this.helpTab) this.helpTab = this._addTab({ kind: 'help', title: 'Help', view: this.helpView, closable: true });
      return this.helpTab;
    }

    showHelp(anchor) {
      this.showTab(this._helpTab());
      if (anchor) {
        const target = this.helpView.querySelector(`#help-${CSS.escape(anchor)}`);
        if (target) target.scrollIntoView({ block: 'start' });
      } else this.helpView.scrollTop = 0;
    }

    /* ---- start ------------------------------------------------------------------------ */
    start({ version = '', topics = {} } = {}) {
      this._makeHelp();
      if (typeof KvotInfo !== 'undefined') {
        // the frame's topics (smui-help.js) are there for SM.info.get too; a
        // platform's own topic of the same name wins, as in the panel
        for (const [k, v] of Object.entries({ ...(SM.help ? SM.help.topics : {}), ...topics })) if (!(k in allTopics)) allTopics[k] = v;
        KvotInfo.setup({ topics: { ...(SM.help ? SM.help.topics : {}), ...topics, ...pendingTopics }, morePrefix: 'Read more in Help: ', onMore: (more) => this.showHelp(more && more.id ? more.id.replace(/^help-/, '') : null) });
        topicsReady = true;
      }
      this.on('columnselection', () => this.panels.renderColumns());
      SM.engine.on('status', () => { this._engineStatus(); if (SM.engine.state === 'ready' || SM.engine.state === 'error') this._renderHome(); });
      SM.engine.on('busy', (n) => { this.engineEl.dataset.busy = n > 0 ? '1' : '0'; });
      SM.engine.on('log', (m) => { this.log.push(m.text); if (this.log.length > 2000) this.log.splice(0, 1000); });
      this._engineStatus();
      SM.engine.start(version);
      this.showTab(this.homeTab);
      const want = new URLSearchParams(location.search).get('example');
      if (want && SM.io.EXAMPLES[want]) this.openExample(want);
      this.started = true;
      for (const fn of appHooks.splice(0)) { try { fn(this); } catch (e) { console.error('SM: an app hook failed', e); } }
      return this;
    }
  }

  /* ---- helpers --------------------------------------------------------------------------- */
  function buildMenu(top, core, reg) {
    const entries = core.filter(Boolean).map((it) => ({ order: it.order ?? 500, item: it }));
    const subs = new Map();
    for (const r of reg) {
      const parts = r.path.split('/');
      if (parts[0] !== top) continue;
      if (parts.length === 1) entries.push({ order: r.order, item: r.item });
      else {
        const key = parts.slice(0, 2).join('/');
        if (!subs.has(key)) subs.set(key, []);
        subs.get(key).push({ order: r.order, item: r.item, rest: parts.slice(2) });
      }
    }
    for (const [key, list] of subs) {
      const label = key.split('/')[1];
      const existing = entries.find((e) => e.item.label === label && e.item.submenu);
      const items = list.sort((a, b) => a.order - b.order);
      const make = () => withSeparators(items.map((x) => ({ order: x.order, item: x.item })));
      if (existing) {
        const base = existing.item.submenu;
        existing.item.submenu = () => withSeparators([...(typeof base === 'function' ? base() : base).map((it, i) => ({ order: it.order ?? i, item: it })), ...items]);
      } else entries.push({ order: SUBMENU_ORDER[key] ?? 900, item: { label, submenu: make } });
    }
    const out = withSeparators(entries.sort((a, b) => a.order - b.order));
    if (!out.length) out.push({ label: '(nothing here yet)', disabled: true });
    return out;
  }

  function withSeparators(entries) {
    const out = [];
    let group = null;
    for (const e of entries) {
      if (e.item && e.item.separator) { out.push(e.item); group = null; continue; }
      const g = Math.floor((e.order ?? 0) / 100);
      if (group != null && g !== group && out.length && !out[out.length - 1].separator) out.push({ separator: true });
      group = g;
      out.push(e.item);
    }
    return out;
  }

  // Specs keep column ids, and the names beside them, so that a saved
  // project finds its columns again.
  function withNames(spec, table) {
    const s = JSON.parse(JSON.stringify(spec || {}));
    s.roleNames = {};
    for (const [k, ids] of Object.entries(s.roles || {})) s.roleNames[k] = (ids || []).map((id) => (table.col(id) || {}).name || null);
    return s;
  }

  /* A saved report's spec with the column ids of the table as opened now.
     idNames (old id -> name) covers every column; older files have only the
     role names. Ids are rewritten wherever they appear: roles, option keys
     scoped by columns ('c12|qq', 'c3~c7|fit'), option values, the filter,
     the column switcher and the keys of closed outlines. */
  function remapSpec(spec, table, idNames) {
    const s = JSON.parse(JSON.stringify(spec || {}));
    const map = new Map();
    for (const [old, name] of Object.entries(idNames || {})) { const c = table.col(name); if (c) map.set(old, c.id); }
    const names = s.roleNames || {};
    for (const [k, ids] of Object.entries(s.roles || {})) {
      s.roles[k] = (ids || []).map((id, i) => {
        const c = (map.has(id) && table.col(map.get(id))) || table.col(names[k] && names[k][i]) || table.col(id);
        if (c && id !== c.id) map.set(id, c.id);
        return c ? c.id : id;
      });
    }
    if (!map.size) return s;
    const id = (x) => (map.has(x) ? map.get(x) : x);
    const scope = (key) => { const i = key.indexOf('|'); return i < 0 ? key : `${key.slice(0, i).split('~').map(id).join('~')}${key.slice(i)}`; };
    const deep = (v) => {
      if (typeof v === 'string') return id(v);
      if (Array.isArray(v)) return v.map(deep);
      if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [id(k), deep(x)]));
      return v;
    };
    if (s.options) s.options = Object.fromEntries(Object.entries(s.options).map(([k, v]) => [scope(k), deep(v)]));
    // A platform's own parts of the spec (Fit Model's effects) hold ids too.
    for (const k of Object.keys(s)) if (!['roles', 'roleNames', 'options', 'filter', 'switcher', 'closed', 'platform'].includes(k)) s[k] = deep(s[k]);
    if (Array.isArray(s.filter)) s.filter = s.filter.map((e) => ({ ...e, col: id(e.col) }));
    if (s.switcher) s.switcher = { ...s.switcher, list: (s.switcher.list || []).map(id) };
    if (s.closed) s.closed = Object.fromEntries(Object.entries(s.closed).map(([k, v]) => [k.replace(/\bc\d+\b/g, id), v]));
    return s;
  }

  function columnSummary(t, c) {
    let n = 0, miss = 0;
    for (const v of c.values) { if (SM.table.isMissing(v)) miss++; else n++; }
    const lv = c.isCategorical ? t.levels(c).length : null;
    return `${n} values, ${miss} missing${lv != null ? `, ${lv} levels` : ''}.`;
  }

  function tableGlyph() {
    return SM.util.svg('svg', { viewBox: '0 0 12 12', width: 11, height: 11, 'aria-hidden': 'true', class: 'sm-tabicon' },
      SM.util.svg('rect', { x: 1, y: 1.5, width: 10, height: 9, rx: 1, fill: 'none', stroke: 'currentColor', 'stroke-width': 1 }),
      SM.util.svg('path', { d: 'M1 4.5 H11 M4.5 1.5 V10.5', stroke: 'currentColor', 'stroke-width': 1 }));
  }

  function reportGlyph() {
    return SM.util.svg('svg', { viewBox: '0 0 12 12', width: 11, height: 11, 'aria-hidden': 'true', class: 'sm-tabicon' },
      SM.util.svg('path', { d: 'M1.5 10.5 V6 M4.5 10.5 V3 M7.5 10.5 V5 M10.5 10.5 V1.5', stroke: 'currentColor', 'stroke-width': 1.6 }));
  }

  // a notebook (and the JSL converter): a page of code, its lines ragged
  function notebookGlyph() {
    return SM.util.svg('svg', { viewBox: '0 0 12 12', width: 11, height: 11, 'aria-hidden': 'true', class: 'sm-tabicon' },
      SM.util.svg('path', { d: 'M4 3 L1.5 6 L4 9 M8 3 L10.5 6 L8 9', stroke: 'currentColor', 'stroke-width': 1.5, fill: 'none', 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  }

  SM.App = App;
  // For JSL to Python, whose specs name their columns: ids put in wherever a spec holds them.
  SM.specs = Object.freeze({ remap: remapSpec, withNames });
}(typeof self !== 'undefined' ? self : this));
