/* ==========================================================================
   PYLAB.HTML: THE DESKTOP

   Puts the parts together: the toolstrip (HOME, PLOTS, EDITOR), the
   address bar of the current folder, the Current Folder and Details, the
   Editor over the Command Window, the Workspace over the Command History,
   the status bar, and the figure windows over all of it.

   It runs what is typed and what the Editor asks for through the engine,
   keeps the panels up to date after each run, and drives the debugger:
   breakpoints set in the Editor's margin, the stop at one (the arrow, the
   K>> prompt in the paused function's workspace), and the steps. Files
   dropped from the computer are copied in and opened (wireDrops).
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, icon, Emitter } = PL;
  const U = PL.util;

  const HOME = '/home/user';
  const SCRIPT_TEMPLATE = '';
  const FUNCTION_TEMPLATE = (name) => `function output = ${name}(input)\n%${name.toUpperCase()}  One line about what ${name} does.\n%   output = ${name}(input) says more.\n\noutput = input;\nend\n`;

  /* ---- the plot gallery (PLOTS tab) ------------------------------------------------- */
  class PlotGallery {
    constructor(app) {
      this.app = app;
      this.sel = [];
      this.kinds = [
        ['plot', 'plot', 'g_plot', 1, 9], ['scatter', 'scatter', 'g_scatter', 2, 2], ['bar', 'bar', 'g_bar', 1, 2],
        ['histogram', 'histogram', 'g_hist', 1, 1], ['area', 'area', 'g_area', 1, 2], ['stairs', 'stairs', 'g_stairs', 1, 2],
        ['stem', 'stem', 'g_stem', 1, 2], ['plot3', 'plot3', 'g_plot3', 3, 3], ['surf', 'surf', 'g_surf', 1, 3],
        ['mesh', 'mesh', 'g_mesh', 1, 3], ['contour', 'contour', 'g_contour', 1, 3], ['imagesc', 'imagesc', 'g_image', 1, 1],
        ['pie', 'pie', 'g_pie', 1, 1], ['semilogy', 'semilogy', 'g_plot', 1, 2],
      ];
      this.buttons = new Map();
      this.newFigure = false;
    }

    build() {
      const grid = el('div', { class: 'pl-gallery' });
      for (const [fn, label, ic] of this.kinds) {
        const b = el('button', { type: 'button', title: `${fn}(…) of the selected variables`, disabled: true }, icon(ic), label);
        b.addEventListener('click', () => this.plot(fn));
        this.buttons.set(fn, b);
        grid.append(b);
      }
      this.note = el('div', { class: 'pl-gallery-note' }, 'Select variables in the Workspace (Ctrl or ⌘ for several), then pick a chart.');
      const nf = el('label', { class: 'pl-small' }, el('input', { type: 'checkbox' }), 'In a new figure');
      nf.querySelector('input').addEventListener('change', (ev) => { this.newFigure = ev.target.checked; });
      return [grid, el('div', { class: 'pl-col', style: { justifyContent: 'center' } }, this.note, nf)];
    }

    update(sel) {
      this.sel = sel.filter((r) => ['double', 'single', 'logical'].includes(r.class) || /int/.test(r.class));
      const n = this.sel.length;
      for (const [fn, , , lo, hi] of this.kinds) {
        const b = this.buttons.get(fn);
        if (b) b.disabled = !(n >= lo && n <= hi);
      }
      this.note.textContent = n ? `Selected: ${this.sel.map((r) => r.name).join(', ')}` : 'Select variables in the Workspace (Ctrl or ⌘ for several), then pick a chart.';
    }

    canPlot(fn) { const k = this.kinds.find((x) => x[0] === fn); return k && this.sel.length >= k[3] && this.sel.length <= k[4]; }

    plot(fn) {
      const names = this.sel.map((r) => r.name);
      if (!names.length) return;
      const pre = this.newFigure ? 'figure; ' : '';
      this.app.runCommand(`${pre}${fn}(${names.join(',')})`);
    }
  }

  /* ---- an open document in the editor area ----------------------------------------------- */
  class Doc {
    constructor(app, kind, key, title) {
      this.app = app;
      this.kind = kind;      // 'file', 'var', 'python', 'help', 'image'
      this.key = key;
      this.title = title;
      this.view = el('div', { class: 'pl-edview' });
      this.tab = el('div', { class: `pl-edtab${kind === 'var' ? ' is-var' : ''}`, role: 'tab', tabindex: '0', title: key, draggable: 'false' },
        el('span', { class: 't' }, title));
      const x = el('button', { class: 'x', type: 'button', title: 'Close', 'aria-label': `Close ${title}` }, '×');
      x.addEventListener('click', (ev) => { ev.stopPropagation(); app.closeDoc(this); });
      this.tab.append(x);
      this.tab.addEventListener('click', () => app.showDoc(this));
      this.tab.addEventListener('auxclick', (ev) => { if (ev.button === 1) app.closeDoc(this); });
      this.tab.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();
        U.menu(ev.clientX, ev.clientY, [
          { label: 'Close', action: () => app.closeDoc(this) },
          { label: 'Close the others', action: () => app.docs.filter((d) => d !== this).forEach((d) => app.closeDoc(d)) },
          kind === 'file' ? '-' : null,
          kind === 'file' ? { label: 'Save', action: () => app.save(this) } : null,
          kind === 'file' ? { label: 'Run', action: () => { app.showDoc(this); app.runCurrent(); } } : null,
          kind === 'file' ? { label: 'Show in the Current Folder', action: () => app.cd(U.dirname(this.key)) } : null,
          kind === 'file' ? { label: 'Copy the path', action: () => navigator.clipboard?.writeText(this.key) } : null,
        ]);
      });
      this.dirty = false;
    }

    setTitle(t) { this.title = t; this.tab.querySelector('.t').textContent = t; }
    setDirty(d) { this.dirty = d; this.tab.classList.toggle('is-dirty', d); }
  }

  /* ---- the desktop ------------------------------------------------------------------------ */
  class App extends Emitter {
    constructor(root) {
      super();
      this.root = root;
      this.history = new PL.History();
      this.docs = [];
      this.current = null;
      this.cwd = HOME;
      this.back = [];
      this.fwd = [];
      this.breakpoints = U.store.get('breakpoints', {});
      this.debug = null;          // {file, line, waitId} while paused
      this.inputId = null;
      this.state = 'loading';
      this.lintTimers = new Map();
      this.plotGallery = new PlotGallery(this);
    }

    start({ version }) {
      this.version = version;
      this.build();
      this.wire();
      PL.engine.start(version);
      this.setState('loading', 'Starting…');
    }

    /* ---- building ----------------------------------------------------------------- */
    build() {
      const r = this.root;
      // toolstrip
      this.tabsEl = el('div', { class: 'pl-tabs', role: 'tablist', 'aria-label': 'Toolstrip' });
      this.stripEl = el('div', { class: 'pl-strip', role: 'toolbar' });
      this.stripTabs = {};
      const homeLink = el('a', { class: 'pl-homelink pl-fullonly', href: './index.html', title: 'kvot ab: home' }, el('img', { src: './resources/images/kvot-logotype.svg', alt: 'kvot ab' }));
      this.tabsEl.append(homeLink);
      for (const [key, label] of [['home', 'HOME'], ['plots', 'PLOTS'], ['editor', 'EDITOR']]) {
        const t = el('button', { class: 'pl-tab', role: 'tab', type: 'button', 'aria-selected': 'false' }, label);
        t.addEventListener('click', () => this.showStrip(key));
        this.stripTabs[key] = t;
        this.tabsEl.append(t);
      }
      const themeBtn = el('button', { class: 'pl-iconbtn theme-toggle pl-fullonly', type: 'button', 'data-on-click': 'kvot:toggleTheme', title: 'Switch theme' }, document.documentElement.dataset.theme === 'dark' ? '☀️' : '🌙');
      this.fullBtn = el('button', { class: 'pl-iconbtn', type: 'button', title: 'Full window (no site header and footer)', 'aria-pressed': String(document.documentElement.classList.contains('pl-full')) }, icon('full'));
      this.fullBtn.addEventListener('click', () => this.toggleFull());
      this.tabsEl.append(el('div', { class: 'pl-tabs-end' }, themeBtn, this.fullBtn));
      this.strips = { home: this.buildHome(), plots: this.buildPlots(), editor: this.buildEditorStrip() };

      // address bar
      this.btnBack = this.iconBtn('back', 'Back', () => this.goBack());
      this.btnFwd = this.iconBtn('fwd', 'Forward', () => this.goFwd());
      this.btnUp = this.iconBtn('up', 'Up one folder', () => this.cd(U.dirname(this.cwd)));
      this.crumbs = el('div', { class: 'pl-crumbs', title: 'The current folder (click to type a path)' });
      this.crumbs.addEventListener('dblclick', () => this.editPath());
      this.crumbs.addEventListener('click', (ev) => { if (ev.target === this.crumbs) this.editPath(); });
      const browse = this.iconBtn('browse', 'Browse for a folder', () => this.editPath());
      this.address = el('div', { class: 'pl-address' }, this.btnBack, this.btnFwd, this.btnUp, browse, this.crumbs,
        this.iconBtn('refresh', 'Refresh the Current Folder', () => this.folder.refresh()));

      // panels
      this.folder = new PL.FolderPanel(this);
      this.details = new PL.DetailsPanel();
      this.ws = new PL.WorkspacePanel(this);
      this.histPanel = new PL.HistoryPanel(this.history, this);
      this.cmd = new PL.CommandWindow({ history: this.history });
      this.edTabs = el('div', { class: 'pl-edtabs', role: 'tablist', 'aria-label': 'Open files' });
      this.edBody = el('div', { class: 'pl-edbody' });

      const panel = (key, title, body, menu) => {
        const head = el('div', { class: 'pl-panel-head' }, el('span', { class: 'pl-ptitle' }, title));
        if (menu) head.append(this.iconBtn('more', `${title} actions`, (b, ev) => menu(ev)));
        const p = el('section', { class: `pl-panel pl-p-${key}`, 'aria-label': title }, head, el('div', { class: 'pl-panel-body' }, body));
        p.addEventListener('pointerdown', () => this.activePanel(p), true);
        return p;
      };
      this.pFolder = panel('folder', 'Current Folder', this.folder.el, (ev) => this.folder.folderMenu(ev.clientX, ev.clientY));
      this.pDetails = panel('details', 'Details', this.details.el);
      this.pEditor = el('section', { class: 'pl-panel pl-p-editor', 'aria-label': 'Editor' },
        el('div', { style: { display: 'contents' } }, this.edTabs), this.edBody);
      this.pEditor.style.gridTemplateRows = 'auto minmax(0, 1fr)';
      this.pEditor.addEventListener('pointerdown', () => { this.activePanel(this.pEditor); if (this.current && this.current.kind === 'file') this.showStrip('editor'); }, true);
      this.pCmd = panel('cmd', 'Command Window', this.cmd.el, (ev) => U.menu(ev.clientX, ev.clientY, [
        { label: 'Clear Command Window', kbd: 'clc', action: () => this.cmd.clear() },
        { label: 'Copy all', action: () => navigator.clipboard?.writeText(this.cmd.out.textContent) },
        { label: 'Stop the program', kbd: 'Ctrl+C', disabled: !PL.engine.busy, action: () => this.interrupt() },
        { label: 'Restart Python…', action: () => this.restartEngine() },
        ...(this.isPhone() ? ['-',
          { label: 'Current Folder', checked: this.main.classList.contains('show-files'), action: () => this.togglePanel('left') },
          { label: 'Workspace and Command History', checked: this.main.classList.contains('show-vars'), action: () => this.togglePanel('right') }] : []),
      ]));
      this.pCmd.querySelector('.pl-panel-body').style.overflow = 'hidden';
      this.pWs = panel('ws', 'Workspace', this.ws.el, (ev) => U.menu(ev.clientX, ev.clientY, [
        { label: 'New variable…', action: () => this.newVariable() },
        { label: 'Save workspace…', action: () => this.saveWorkspace() },
        { label: 'Load MAT-file…', action: () => this.importData() },
        { label: 'Clear workspace', action: () => this.runCommand('clear') },
      ]));
      this.pHist = panel('hist', 'Command History', this.histPanel.el, (ev) => U.menu(ev.clientX, ev.clientY, [
        { label: 'Clear Command History…', action: async () => { if (await U.confirm('Clear Command History', 'Remove every command from the history?', 'Clear')) this.history.clear(); } },
      ]));

      const sash = (dir, onDrag, onEnd) => {
        const s = el('div', { class: `pl-sash ${dir}`, role: 'separator', tabindex: '0', 'aria-orientation': dir === 'v' ? 'vertical' : 'horizontal' });
        this.sashDrag(s, dir, onDrag, onEnd);
        return s;
      };
      this.left = el('div', { class: 'pl-colstack pl-left' }, this.pFolder, sash('h', (d, st) => this.splitRows('left', st, d)), this.pDetails);
      this.center = el('div', { class: 'pl-colstack pl-center no-editor' }, this.pEditor, sash('h', (d, st) => this.splitRows('center', st, d)), this.pCmd);
      this.right = el('div', { class: 'pl-colstack pl-right' }, this.pWs, sash('h', (d, st) => this.splitRows('right', st, d)), this.pHist);
      this.main = el('div', { class: 'pl-main' }, this.left, sash('v', (d, st) => this.setCol('side', st, d)), this.center, sash('v', (d, st) => this.setCol('right', st, -d)), this.right);

      // status bar
      this.stateEl = el('span', { class: 'pl-state is-busy' }, el('span', { class: 'pl-dot' }), el('span', { class: 'txt' }, 'Starting'));
      this.statusText = el('span', { class: 'pl-grow' });
      this.caretEl = el('span');
      this.versionEl = el('span');
      this.stopBtn = el('button', { type: 'button', hidden: true, title: 'Stop the running program (Ctrl+C)' }, 'Stop');
      this.stopBtn.addEventListener('click', () => this.interrupt());
      this.restartBtn = el('button', { type: 'button', hidden: true, title: 'Start Python again (the workspace is lost)' }, 'Restart Python');
      this.restartBtn.addEventListener('click', () => this.restartEngine());
      this.status = el('div', { class: 'pl-status', role: 'status' }, this.stateEl, this.stopBtn, this.restartBtn, this.statusText, this.caretEl, this.versionEl);

      this.figLayer = el('div', { class: 'pl-figlayer' });
      this.figures = new PL.Figures(this.figLayer);
      r.replaceChildren(this.tabsEl, this.stripEl, this.address, this.main, this.status, this.figLayer);
      this.wireDrops();
      this.figLayer.style.top = '0';
      this.restoreLayout();
      window.matchMedia('(max-width: 760px)').addEventListener('change', (ev) => {
        if (ev.matches) return;
        this.main.classList.remove('show-files', 'show-vars');
        this.left.hidden = this.main.classList.contains('no-left');
        this.right.hidden = this.main.classList.contains('no-right');
      });
      this.showStrip('home');
      this.renderCrumbs();
      this.renderEdTabs();
      this.cmd.write('PyLAB: programs in the MATLAB language, compiled to Python and run in this tab.\nType help for an overview, or open the examples folder.\n\n', 'info');
    }

    iconBtn(name, title, fn) {
      const b = el('button', { class: 'pl-iconbtn', type: 'button', title, 'aria-label': title }, icon(name));
      b.addEventListener('click', (ev) => fn(b, ev));
      return b;
    }

    big(name, label, title, fn, cls) {
      const b = el('button', { class: 'pl-big', type: 'button', title: title || label }, icon(name, cls), el('span', null, label));
      b.addEventListener('click', (ev) => fn(b, ev));
      return b;
    }

    small(name, label, title, fn, cls) {
      const b = el('button', { class: 'pl-small', type: 'button', title: title || label }, icon(name, cls), el('span', null, label));
      b.addEventListener('click', (ev) => fn(b, ev));
      return b;
    }

    group(label, ...items) {
      return el('div', { class: 'pl-group', role: 'group', 'aria-label': label }, el('div', { class: 'pl-group-items' }, ...items), el('div', { class: 'pl-group-label' }, label));
    }

    buildHome() {
      const k = U.modName;
      return [
        this.group('File',
          this.big('newscript', 'New Script', `A new script (${k}N)`, () => this.newFile('script')),
          el('div', { class: 'pl-col' },
            this.small('newfunc', 'New Function', 'A new function file', () => this.newFile('function')),
            this.small('open', 'Open…', `Open a file (${k}O)`, () => this.openDialog()),
            this.small('upload', 'Upload Files…', 'Copy files from your computer into the current folder', () => this.pickUpload(this.cwd)))),
        this.group('Variable',
          el('div', { class: 'pl-col' },
            this.small('import', 'Load MAT-File…', 'Load the variables of a MAT-file (from your computer)', () => this.importData()),
            this.small('savews', 'Save Workspace…', 'Save the workspace as a MAT-file', () => this.saveWorkspace()),
            this.small('variable', 'Open Variable…', 'Open a variable as a table', () => this.openVariableAsk())),
          el('div', { class: 'pl-col' },
            this.small('clearws', 'Clear Workspace', 'Remove every variable (clear)', () => this.runCommand('clear')),
            this.small('clear', 'Clear Commands', 'Empty the Command Window (clc)', () => this.cmd.clear()))),
        this.group('Environment',
          this.big('layout', 'Layout', 'Show or hide panels', (b) => this.layoutMenu(b)),
          this.big('prefs', 'Preferences', 'Number format and fonts', () => this.preferences())),
        this.group('Resources',
          this.big('help', 'Help', 'How the desktop works, and every function', () => this.openHelp()),
          el('div', { class: 'pl-col' },
            this.small('examples', 'Examples', 'Go to the examples folder', () => this.cd(`${HOME}/examples`)),
            this.small('python', 'Python Engine', 'What runs the programs', () => this.engineInfo()))),
      ];
    }

    buildPlots() {
      return [this.group('Plots', ...this.plotGallery.build())];
    }

    buildEditorStrip() {
      const k = U.modName;
      this.runBtn = this.big('run', 'Run', 'Run the file (F5)', () => this.runCurrent(), 'pl-ic-run');
      this.runSecBtn = this.big('runsec', 'Run Section', `Run the section under the cursor (${k}Enter)`, () => this.runSection(false), 'pl-ic-run');
      this.runAdvBtn = this.small('runadv', 'Run and Advance', 'Run the section, then go to the next', () => this.runSection(true), 'pl-ic-run');
      this.runSelBtn = this.small('runsel', 'Run Selection', 'Run the selected lines (F9)', () => this.runSelection(), 'pl-ic-run');
      this.pauseBtn = this.small('pause', 'Pause', 'Stop at the next line and debug', () => this.pauseRun());
      this.stepBtn = this.big('step', 'Step', 'Run the next line (F10)', () => this.dbg('step'));
      this.stepInBtn = this.small('stepin', 'Step In', 'Into the function on this line (F11)', () => this.dbg('stepin'));
      this.stepOutBtn = this.small('stepout', 'Step Out', 'Run to the end of this function (Shift+F11)', () => this.dbg('stepout'));
      this.contBtn = this.big('cont', 'Continue', 'Run to the next breakpoint (F5)', () => this.dbg('continue'), 'pl-ic-run');
      this.quitBtn = this.big('quitdbg', 'Quit Debugging', 'Stop the program (Shift+F5)', () => this.dbg('quit'), 'pl-ic-stop');
      this.runGroup = this.group('Run', this.runBtn, this.runSecBtn, el('div', { class: 'pl-col' }, this.runAdvBtn, this.runSelBtn, this.pauseBtn));
      this.debugGroup = this.group('Debug', this.stepBtn, el('div', { class: 'pl-col' }, this.stepInBtn, this.stepOutBtn), this.contBtn, this.quitBtn);
      return [
        this.group('File',
          this.big('save', 'Save', `Save (${k}S)`, () => this.save()),
          el('div', { class: 'pl-col' },
            this.small('saveas', 'Save As…', 'Save under another name', () => this.saveAs()),
            this.small('download', 'Download', 'Download the file to your computer', () => this.current && this.current.kind === 'file' && this.downloadFile(this.current.key)),
            this.small('newscript', 'New', 'A new script', () => this.newFile('script')))),
        this.group('Navigate',
          el('div', { class: 'pl-col' },
            this.small('find', 'Find', `Find and replace (${k}F)`, () => this.withEditor((e) => e.find())),
            this.small('goto', 'Go To…', `Go to a line (${k}G)`, () => this.withEditor((e) => e.askLine())))),
        this.group('Edit',
          el('div', { class: 'pl-col' },
            this.small('comment', 'Comment', `Comment the lines out (${k}/)`, () => this.withEditor((e) => e.commentLines(true))),
            this.small('comment', 'Uncomment', 'Take the comment marks away', () => this.withEditor((e) => e.commentLines(false))),
            this.small('indent', 'Smart Indent', `Indent by the blocks (${k}I)`, () => this.withEditor((e) => e.smartIndent())))),
        this.group('Breakpoints',
          el('div', { class: 'pl-col' },
            this.small('bp', 'Set/Clear', 'A breakpoint on the cursor line (F12)', () => this.toggleBreakpointHere()),
            this.small('bpclear', 'Clear All', 'Remove every breakpoint', () => this.clearAllBreakpoints()))),
        this.runGroup,
        this.debugGroup,
        this.group('Python',
          this.big('python', 'View Python', 'The Python this file compiles to', () => this.viewPython())),
      ];
    }

    showStrip(key) {
      this.stripKey = key;
      for (const [k, t] of Object.entries(this.stripTabs)) t.setAttribute('aria-selected', String(k === key));
      this.stripEl.replaceChildren(...this.strips[key]);
      this.updateRunButtons();
    }

    /* ---- layout --------------------------------------------------------------------- */
    sashDrag(s, dir, onDrag, onEnd) {
      let st = null;
      s.addEventListener('pointerdown', (ev) => {
        ev.preventDefault();
        s.setPointerCapture(ev.pointerId);
        s.classList.add('is-drag');
        st = { x: ev.clientX, y: ev.clientY, base: this.layoutState() };
      });
      s.addEventListener('pointermove', (ev) => {
        if (!st) return;
        onDrag(dir === 'v' ? ev.clientX - st.x : ev.clientY - st.y, st.base);
      });
      const end = () => { if (!st) return; st = null; s.classList.remove('is-drag'); this.saveLayout(); this.figures.redrawAll(); };
      s.addEventListener('pointerup', end);
      s.addEventListener('pointercancel', end);
      s.addEventListener('keydown', (ev) => {
        const d = { ArrowLeft: -16, ArrowRight: 16, ArrowUp: -16, ArrowDown: 16 }[ev.key];
        if (d === undefined) return;
        ev.preventDefault();
        onDrag(d, this.layoutState());
        this.saveLayout();
      });
    }

    layoutState() {
      const cs = getComputedStyle(this.root);
      const px = (v, d) => parseFloat(cs.getPropertyValue(v)) || d;
      return {
        side: this.left.getBoundingClientRect().width || px('--pl-side-w', 230),
        right: this.right.getBoundingClientRect().width || px('--pl-right-w', 300),
        left: [this.pFolder.getBoundingClientRect().height, this.pDetails.getBoundingClientRect().height],
        center: [this.pEditor.getBoundingClientRect().height, this.pCmd.getBoundingClientRect().height],
        rightRows: [this.pWs.getBoundingClientRect().height, this.pHist.getBoundingClientRect().height],
      };
    }

    setCol(which, base, d) {
      const w = Math.max(120, Math.min(window.innerWidth * 0.45, (which === 'side' ? base.side : base.right) + d));
      this.root.style.setProperty(which === 'side' ? '--pl-side-w' : '--pl-right-w', `${Math.round(w)}px`);
    }

    splitRows(col, base, d) {
      const [a, b] = col === 'left' ? base.left : col === 'center' ? base.center : base.rightRows;
      const total = a + b;
      const na = Math.max(40, Math.min(total - 40, a + d));
      const names = { left: ['--pl-left-top', '--pl-left-bot'], center: ['--pl-center-top', '--pl-center-bot'], right: ['--pl-right-top', '--pl-right-bot'] }[col];
      this.root.style.setProperty(names[0], `${na}fr`);
      this.root.style.setProperty(names[1], `${total - na}fr`);
    }

    saveLayout() {
      const s = this.root.style;
      const keep = {};
      for (const v of ['--pl-side-w', '--pl-right-w', '--pl-left-top', '--pl-left-bot', '--pl-center-top', '--pl-center-bot', '--pl-right-top', '--pl-right-bot']) {
        const x = s.getPropertyValue(v);
        if (x) keep[v] = x;
      }
      keep.hide = { left: this.main.classList.contains('no-left'), right: this.main.classList.contains('no-right') };
      U.store.set('layout', keep);
    }

    restoreLayout() {
      const keep = U.store.get('layout', {});
      for (const [k, v] of Object.entries(keep)) if (k.startsWith('--')) this.root.style.setProperty(k, v);
      if (keep.hide) {
        this.main.classList.toggle('no-left', !!keep.hide.left);
        this.main.classList.toggle('no-right', !!keep.hide.right);
        this.left.hidden = !!keep.hide.left;
        this.right.hidden = !!keep.hide.right;
      }
    }

    layoutMenu(b) {
      const r = b.getBoundingClientRect();
      const phone = this.isPhone();
      const hasLeft = phone ? this.main.classList.contains('show-files') : !this.main.classList.contains('no-left');
      const hasRight = phone ? this.main.classList.contains('show-vars') : !this.main.classList.contains('no-right');
      U.menu(r.left, r.bottom + 2, [
        { heading: 'Show' },
        { label: 'Current Folder and Details', checked: hasLeft, action: () => this.togglePanel('left') },
        { label: 'Workspace and Command History', checked: hasRight, action: () => this.togglePanel('right') },
        '-',
        { label: 'Default layout', action: () => this.resetLayout() },
        { label: 'Command Window only', action: () => { this.setPanels(false, false); } },
      ]);
    }

    /* At phone width the columns stack and the side panels are hidden until
       asked for (show-files, show-vars); the wide layout's choice is kept. */
    isPhone() { return window.matchMedia('(max-width: 760px)').matches; }

    togglePanel(which) {
      const side = which === 'left' ? this.left : this.right;
      if (this.isPhone()) {
        const on = this.main.classList.toggle(which === 'left' ? 'show-files' : 'show-vars');
        side.hidden = on ? false : this.main.classList.contains(which === 'left' ? 'no-left' : 'no-right');
        if (on) side.scrollIntoView({ block: 'start' });
        return;
      }
      const on = this.main.classList.toggle(which === 'left' ? 'no-left' : 'no-right');
      side.hidden = on;
      this.saveLayout();
      this.figures.redrawAll();
    }

    setPanels(left, right) {
      this.main.classList.toggle('no-left', !left);
      this.main.classList.toggle('no-right', !right);
      this.left.hidden = !left;
      this.right.hidden = !right;
      this.saveLayout();
    }

    resetLayout() {
      for (const v of ['--pl-side-w', '--pl-right-w', '--pl-left-top', '--pl-left-bot', '--pl-center-top', '--pl-center-bot', '--pl-right-top', '--pl-right-bot']) this.root.style.removeProperty(v);
      this.setPanels(true, true);
      U.store.set('figplaces', {});
      this.figures.places = {};
    }

    toggleFull() {
      const on = !document.documentElement.classList.contains('pl-full');
      document.documentElement.classList.toggle('pl-full', on);
      this.fullBtn.setAttribute('aria-pressed', String(on));
      try { localStorage.setItem('pylab.full', on ? '1' : '0'); } catch (e) { /* ignore */ }
      setTimeout(() => this.figures.redrawAll(), 50);
    }

    activePanel(p) {
      for (const x of this.root.querySelectorAll('.pl-panel')) x.classList.toggle('is-active', x === p);
    }

    /* ---- the engine ------------------------------------------------------------------- */
    wire() {
      const E = PL.engine;
      E.on('status', (t) => this.setState('loading', t));
      E.on('slow', () => this.statusText.textContent = 'Loading is slow: Python and its packages (about 30 MB) come from cdn.jsdelivr.net, which a firewall or a blocker may be holding back.');
      E.on('fatal', (m) => { this.setState('error', 'Python could not start'); this.cmd.write(`The Python engine could not start: ${m}\n`, 'err'); this.restartBtn.hidden = false; });
      E.on('ready', (info, versions) => this.ready(info, versions));
      E.on('busy', (b) => { this.cmd.setBusy(b); if (!this.debug) this.setState(b ? 'busy' : 'ready'); this.stopBtn.hidden = !b; this.updateRunButtons(); });
      E.on('out', (m) => this.cmd.write(m.text, m.kind));
      E.on('figures', (m) => this.figures.apply(m));
      E.on('raise', (m) => this.figures.raise(m.figure));
      E.on('clc', () => this.cmd.clear());
      E.on('cwd', (m) => this.setCwd(m.path, true));
      E.on('files', (m) => { if (!m.path || m.path === this.cwd || m.path.startsWith(this.cwd)) this.folder.refresh(); });
      E.on('edit', (m) => (m.path ? this.openFile(m.path) : this.newFile('script')));
      E.on('web', (m) => window.open(m.url, '_blank', 'noopener'));
      E.on('input', (m) => this.askInput(m));
      E.on('request', (m) => this.pageRequest(m.request));
      E.on('dbg', (m) => this.onDebug(m));
      E.on('dbgwait', (m) => { if (this.debug) this.debug.waitId = m.id; this.flushDebugQueue(); });
      E.on('restart', () => { this.figures.clear(); this.stopTimers(); this.cmd.write('\nPython was restarted: the workspace is empty and the figures are closed.\n\n', 'warn'); });
      E.on('pool', (m) => this.poolProgress(m));
      E.on('timer', (m) => this.timer(m));
      E.on('movegui', (m) => this.figures.move(m.figure, m.where));
      E.on('focus', (m) => this.figures.focusControl(m.id));
      E.on('help', (m) => this.openHelp(m.name || undefined));
      E.on('sound', (m) => this.playSound(m));

      this.cmd.on('submit', (code) => this.submit(code));
      this.cmd.on('interrupt', () => this.interrupt());
      this.cmd.on('reply', (text) => this.answerInput(text));
      this.cmd.on('link', (path, line) => this.openFile(path, line));
      this.ws.on('selection', (sel) => this.plotGallery.update(sel));
      this.folder.on('select', (p) => this.details.show(p));
      this.figures.on('event', (ev) => PL.engine.call('figure_event', JSON.stringify(ev)).catch(() => {}));
      this.figures.on('run', (code) => this.runCommand(code, { silent: true, noHistory: true }));
      this.figures.on('ui', (ev) => this.uiEvent(ev));
      document.documentElement.addEventListener('kvot-theme-change', () => this.figures.redrawAll());
      window.addEventListener('keydown', (ev) => this.globalKey(ev));
      window.addEventListener('beforeunload', (ev) => {
        if (this.docs.some((d) => d.dirty)) { ev.preventDefault(); ev.returnValue = ''; }
      });
      new ResizeObserver(() => { cancelAnimationFrame(this._swf); this._swf = requestAnimationFrame(() => this.sendWidth()); }).observe(this.cmd.el);
    }

    /* A parfor loop's passes on the pool's workers, in the status bar while they run. */
    poolProgress(m) {
      this.statusText.textContent = m.end ? '' : `parfor: ${m.done} of ${m.total} passes done, on ${m.workers} worker${m.workers === 1 ? '' : 's'}`;
    }

    async ready(info, versions) {
      this.versions = versions;
      this.builtins = info.builtins;
      this.versionEl.textContent = `Python ${versions.python} · NumPy ${versions.numpy} · SciPy ${versions.scipy}`;
      this.setState('ready');
      this.restartBtn.hidden = true;
      const fmt = U.store.get('format', null);
      if (fmt) PL.engine.call('set_format', JSON.stringify(fmt)).catch(() => {});
      this.sendWidth();
      const startDir = U.store.get('cwd', info.cwd || HOME);
      try {
        const ok = await PL.engine.call('set_cwd', startDir);
        this.setCwd(ok ? startDir : HOME, false);
        if (!ok) await PL.engine.call('set_cwd', HOME);
      } catch (e) { this.setCwd(HOME, false); }
      for (const [path, lines] of Object.entries(this.breakpoints)) PL.engine.call('set_breakpoints', path, JSON.stringify(lines)).catch(() => {});
      if (!info.persistent) this.cmd.write('This browser keeps no files between visits here: download what you want to keep.\n', 'warn');
      if (info.fresh) this.cmd.write('The examples are in the examples folder: double-click one in the Current Folder.\n\n', 'info');
      this.restoreDocs();
      this.cmd.focus();
    }

    setState(kind, text) {
      this.state = kind;
      this.stateEl.className = `pl-state is-${kind}`;
      this.stateEl.querySelector('.txt').textContent = text || { ready: 'Ready', busy: 'Busy', debug: 'Paused in the debugger', error: 'Error', loading: 'Starting' }[kind] || kind;
    }

    sendWidth() {
      const w = this.cmd.el.clientWidth;
      if (!w || PL.engine.state !== 'ready') return;
      const probe = el('span', { style: { position: 'absolute', visibility: 'hidden', fontFamily: 'var(--font-mono)', fontSize: 'var(--pl-mono-size)' } }, 'x'.repeat(50));
      this.cmd.el.append(probe);
      const cw = probe.getBoundingClientRect().width / 50 || 7.8;
      probe.remove();
      const cols = Math.max(40, Math.floor((w - 24) / cw));
      if (cols !== this.lastCols) {
        this.lastCols = cols;
        PL.engine.call('set_format', JSON.stringify({ width: cols })).catch(() => {});
      }
    }

    /* ---- running ---------------------------------------------------------------------- */
    submit(code) {
      if (this.debug) {
        this.cmd.echo(code, 'K>> ');
        const t = code.trim();
        const map = { dbcont: 'continue', dbstep: 'step', 'dbstep in': 'stepin', 'dbstep out': 'stepout', dbquit: 'quit' };
        if (map[t]) { this.dbg(map[t]); return; }
        if (t) this.history.add(code);
        this.sendDebug({ cmd: 'eval', text: code });
        return;
      }
      this.cmd.echo(code);
      if (!code.trim()) return;
      this.runCommand(code, { echoed: true });
    }

    /* Run code as a command line. opts: silent (no output but errors),
       noHistory, echoed (already shown). */
    async runCommand(code, opts = {}) {
      if (PL.engine.state !== 'ready') { this.cmd.write('Python is still starting: the command will run when it is ready.\n', 'info'); await new Promise((r) => PL.engine.on('ready', r)); }
      if (!opts.echoed && !opts.silent) this.cmd.echo(code);
      if (!opts.noHistory && !opts.silent) this.history.add(code);
      const t = code.trim();
      if (/^(doc|helpwin)(\s|$)/.test(t)) { this.openHelp(t.split(/\s+/)[1]); return null; }
      if (/^help(\s|$)/.test(t)) {
        const name = t.split(/\s+/)[1] || '';
        const h = await PL.engine.call('help_text', name).catch(() => null);
        if (h) this.cmd.write(`${h.text}\n`, 'out');
        return null;
      }
      let res = null;
      try {
        res = await PL.engine.run(code, { silent: !!opts.silent });
      } catch (e) {
        this.cmd.write(`${e.message}\n`, 'err');
        return null;
      }
      if (res) {
        if (!opts.noHistory && !opts.silent) this.history.markLast(res.ok);
        this.ws.update(res.ws);
        if (res.cwd !== this.cwd) this.setCwd(res.cwd, true);
        this.refreshVariableViews();
        // callbacks the run left waiting (a window's SizeChangedFcn when it is first shown) run now
        if (res.pending) this.runCallbacks();
      }
      return res;
    }

    interrupt() {
      if (this.inputId != null) { PL.engine.reply(this.inputId, { interrupt: true }); this.inputId = null; this.cmd.setMode('normal'); }
      PL.engine.interrupt();
      clearTimeout(this.stuckTimer);
      this.stuckTimer = setTimeout(() => {
        if (PL.engine.busy) {
          this.cmd.write('The program does not stop (it is inside a long calculation). Restart Python to stop it; the workspace will be lost.\n', 'warn');
          this.restartBtn.hidden = false;
        }
      }, 3000);
    }

    async restartEngine() {
      if (PL.engine.state === 'ready' && !(await U.confirm('Restart Python', 'Start Python again? The workspace is cleared and the figures close; your files stay.', 'Restart'))) return;
      this.restartBtn.hidden = true;
      this.debugEnd();
      PL.engine.restart();
    }

    askInput(m) {
      this.inputId = m.id;
      if (m.kind === 'key') {
        this.cmd.setMode('input', '');
        this.statusText.textContent = 'Paused: press Enter in the Command Window to go on.';
      } else this.cmd.setMode('input', m.prompt);
      this.cmd.focus();
    }

    answerInput(text) {
      const id = this.inputId;
      this.inputId = null;
      this.statusText.textContent = '';
      this.cmd.setMode(this.debug ? 'debug' : 'normal');
      if (id != null) PL.engine.reply(id, text);
    }

    async pageRequest(req) {
      if (req.type === 'render') {
        await new Promise((r) => requestAnimationFrame(r));
        const data = this.figures.render(req.figure, req.format);
        PL.engine.reply(req.id, data);
      } else if (req.type === 'ginput') {
        this.statusText.textContent = 'Click points in the figure; Enter ends.';
        this.figures.startGinput(req.figure, req.n, (pts) => { this.statusText.textContent = ''; PL.engine.reply(req.id, pts); });
      } else if (PL.asks && PL.asks[req.type]) {
        let answer = null;
        try { answer = await PL.asks[req.type](this, req); } catch (e) { console.error(e); }
        PL.engine.reply(req.id, answer === undefined ? null : answer);
      } else PL.engine.reply(req.id, null);
    }

    /* ---- programs' user interfaces ------------------------------------------------------------ */
    /* Something a person did in a figure: the engine sets what it sets at
       once, and when it queued callbacks they run, as a run of their own (or
       sooner, at a running program's drawnow or pause). */
    async uiEvent(ev) {
      if (PL.engine.state !== 'ready') return;
      let r = null;
      try { r = await PL.engine.call('ui_event', JSON.stringify(ev)); } catch (e) { return; }
      if (r && r.queued > 0) this.runCallbacks();
    }

    runCallbacks() {
      if (this._callbacks) { this._callbacksAgain = true; return; }
      this._callbacks = true;
      PL.engine.run('', { callbacks: true }).then((res) => {
        this._callbacks = false;
        if (res) {
          this.ws.update(res.ws);
          if (res.cwd !== this.cwd) this.setCwd(res.cwd, true);
          this.refreshVariableViews();
        }
        // what came in while they ran
        if (this._callbacksAgain || (res && res.pending)) { this._callbacksAgain = false; this.runCallbacks(); }
      }).catch(() => { this._callbacks = false; });
    }

    /* timer objects: the page keeps their time; each tick is an event. */
    timer(m) {
      const T = this.timers || (this.timers = new Map());
      const old = T.get(m.id);
      if (old) { clearTimeout(old.t); clearInterval(old.i); T.delete(m.id); }
      if (m.op !== 'start') return;
      const rec = {};
      const tick = () => this.uiEvent({ type: 'timer', id: m.id });
      rec.t = setTimeout(() => {
        tick();
        if (m.mode !== 'singleShot') rec.i = setInterval(tick, Math.max(1, m.period * 1000));
      }, Math.max(0, m.delay * 1000));
      T.set(m.id, rec);
    }

    stopTimers() {
      for (const r of (this.timers || new Map()).values()) { clearTimeout(r.t); clearInterval(r.i); }
      if (this.timers) this.timers.clear();
    }

    /* sound, soundsc and beep: float32 samples, a channel after the other, played at
       once through the page's audio. The samples are brought to the audio's own rate
       here, so any rate plays (browsers refuse buffers of rates below 3000 or 8000). */
    playSound(m) {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        const ctx = this.audio || (this.audio = new AC());
        if (ctx.state === 'suspended') ctx.resume();
        const bin = atob(m.data);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const all = new Float32Array(bytes.buffer);
        const n = all.length / m.channels;
        const len = Math.max(1, Math.round(n * ctx.sampleRate / m.rate));
        const buf = ctx.createBuffer(m.channels, len, ctx.sampleRate);
        for (let c = 0; c < m.channels; c++) {
          const src = all.subarray(c * n, (c + 1) * n);
          const dst = buf.getChannelData(c);
          for (let i = 0; i < len; i++) {
            const x = i * m.rate / ctx.sampleRate;
            const k = Math.min(Math.floor(x), n - 1);
            dst[i] = src[k] + (src[Math.min(k + 1, n - 1)] - src[k]) * (x - k);
          }
        }
        const node = ctx.createBufferSource();
        node.buffer = buf;
        node.connect(ctx.destination);
        node.start();
        this.lastSound = { rate: m.rate, channels: m.channels, samples: n, seconds: len / ctx.sampleRate };
      } catch (e) { /* a page with no audio plays nothing */ }
    }

    /* ---- the debugger --------------------------------------------------------------------- */
    onDebug(m) {
      if (m.state === 'paused') {
        this.debug = { file: m.file, line: m.line, waitId: null, stack: m.stack, queue: [] };
        this.setState('debug');
        this.cmd.setMode('debug');
        this.ws.update(m.ws);
        this.openFile(m.file, null).then((doc) => {
          if (doc && doc.editor) { doc.editor.setArrow(m.line); }
        });
        this.updateRunButtons();
        this.showStrip('editor');
      } else if (m.state === 'evaluated') {
        this.ws.update(m.ws);
        this.refreshVariableViews();
      } else if (m.state === 'running') {
        this.clearArrows();
        if (this.debug) this.debug.waitId = null;
        this.cmd.setMode('normal');
        if (PL.engine.busy) this.setState('busy');
        this.debugPausedEnd();
      }
    }

    debugPausedEnd() {
      this.debug = null;
      this.updateRunButtons();
    }

    debugEnd() {
      this.debug = null;
      this.clearArrows();
      this.cmd.setMode('normal');
      this.updateRunButtons();
    }

    clearArrows() {
      for (const d of this.docs) if (d.editor) d.editor.setArrow(0);
    }

    sendDebug(cmd) {
      if (!this.debug) return;
      this.debug.queue.push(cmd);
      this.flushDebugQueue();
    }

    flushDebugQueue() {
      const d = this.debug;
      if (!d || d.waitId == null || !d.queue.length) return;
      const cmd = d.queue.shift();
      const id = d.waitId;
      d.waitId = null;
      PL.engine.reply(id, cmd);
    }

    dbg(kind) {
      if (!this.debug) {
        if (kind === 'continue') this.runCurrent();
        return;
      }
      if (kind !== 'eval') this.clearArrows();
      this.sendDebug({ cmd: kind });
    }

    pauseRun() {
      if (PL.engine.busy) PL.engine.call('debug_command', JSON.stringify({ cmd: 'pause' })).catch(() => {});
    }

    updateRunButtons() {
      const paused = !!this.debug;
      const busy = PL.engine.busy;
      if (!this.runGroup) return;
      this.debugGroup.hidden = !paused;
      for (const b of [this.stepBtn, this.stepInBtn, this.stepOutBtn, this.contBtn, this.quitBtn]) b.disabled = !paused;
      const file = this.current && this.current.kind === 'file';
      this.runBtn.disabled = !file || paused;
      this.runSecBtn.disabled = !file || paused;
      this.runAdvBtn.disabled = !file || paused;
      this.runSelBtn.disabled = !file;
      this.pauseBtn.disabled = !busy || paused;
    }

    /* Breakpoints: kept per file, in the page and in the engine. */
    toggleBreakpoint(doc, line) {
      const path = doc.key;
      const set = new Set(this.breakpoints[path] || []);
      if (set.has(line)) set.delete(line); else set.add(line);
      const lines = [...set].sort((a, b) => a - b);
      if (lines.length) this.breakpoints[path] = lines; else delete this.breakpoints[path];
      U.store.set('breakpoints', this.breakpoints);
      doc.editor.setBreakpoints(lines);
      PL.engine.call('set_breakpoints', path, JSON.stringify(lines)).catch(() => {});
    }

    toggleBreakpointHere() {
      const d = this.current;
      if (d && d.kind === 'file') this.toggleBreakpoint(d, d.editor.cursorLine());
    }

    clearAllBreakpoints() {
      for (const path of Object.keys(this.breakpoints)) PL.engine.call('set_breakpoints', path, '[]').catch(() => {});
      this.breakpoints = {};
      U.store.set('breakpoints', {});
      for (const d of this.docs) if (d.editor && d.kind === 'file') d.editor.setBreakpoints([]);
    }

    /* ---- the current folder ----------------------------------------------------------------- */
    setCwd(path, fromEngine) {
      if (path !== this.cwd) {
        this.back.push(this.cwd);
        if (this.back.length > 50) this.back.shift();
        this.fwd = [];
      }
      this.cwd = path;
      U.store.set('cwd', path);
      this.renderCrumbs();
      this.folder.show(path);
    }

    async cd(path, record = true) {
      if (!path) return;
      const p = path.startsWith('/') ? path : U.joinPath(this.cwd, path);
      let ok = false;
      try { ok = await PL.engine.call('set_cwd', p); } catch (e) { ok = false; }
      if (!ok) { U.toast(`There is no folder ${p}`); return; }
      if (record) this.setCwd(p, false);
      else { this.cwd = p; U.store.set('cwd', p); this.renderCrumbs(); this.folder.show(p); }
    }

    goBack() { const p = this.back.pop(); if (p) { this.fwd.push(this.cwd); this.cd(p, false); } }
    goFwd() { const p = this.fwd.pop(); if (p) { this.back.push(this.cwd); this.cd(p, false); } }

    renderCrumbs() {
      const parts = this.cwd.split('/').filter(Boolean);
      const frag = [];
      let acc = '';
      frag.push(this.crumbBtn('/', '/'));
      parts.forEach((p, i) => {
        acc += `/${p}`;
        frag.push(this.crumbBtn(p, acc));
        if (i < parts.length - 1) frag.push(el('span', { class: 'pl-sep' }, '›'));
      });
      this.crumbs.replaceChildren(...frag);
      this.btnBack.disabled = !this.back.length;
      this.btnFwd.disabled = !this.fwd.length;
      this.btnUp.disabled = this.cwd === '/';
    }

    crumbBtn(label, path) {
      const b = el('button', { type: 'button' }, label);
      b.addEventListener('click', (ev) => { ev.stopPropagation(); this.cd(path); });
      return b;
    }

    editPath() {
      const input = el('input', { type: 'text', value: this.cwd, spellcheck: 'false', 'aria-label': 'Current folder' });
      this.crumbs.replaceChildren(input);
      input.focus();
      input.select();
      const done = (go) => { if (go && input.value.trim() && input.value.trim() !== this.cwd) this.cd(input.value.trim()); else this.renderCrumbs(); };
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); done(true); }
        if (ev.key === 'Escape') { ev.preventDefault(); done(false); }
      });
      input.addEventListener('blur', () => done(false), { once: true });
    }

    /* ---- files --------------------------------------------------------------------- */
    async newFile(kind, folder) {
      const dir = folder || this.cwd;
      let name = kind === 'function' ? 'untitled_function' : 'untitled';
      let n = 1;
      const exists = async (nm) => !!(await PL.engine.fs('exists', { path: U.joinPath(dir, `${nm}.m`) }).catch(() => false));
      let candidate = name;
      while (await exists(candidate)) { n += 1; candidate = `${name}${n}`; }
      const path = U.joinPath(dir, `${candidate}.m`);
      const text = kind === 'function' ? FUNCTION_TEMPLATE(candidate) : SCRIPT_TEMPLATE;
      await PL.engine.fs('write', { path, data: text });
      this.folder.refresh();
      const doc = await this.openFile(path);
      if (doc) doc.isNew = true;
      return doc;
    }

    async newScript(text) {
      const doc = await this.newFile('script');
      if (doc && text) { doc.editor.value = text; doc.setDirty(true); }
    }

    async newFolder(dir) {
      const name = await U.prompt('New folder', 'Name', 'New Folder');
      if (!name) return;
      await PL.engine.fs('mkdir', { path: U.joinPath(dir || this.cwd, name) }).catch((e) => U.toast(e.message));
      this.folder.refresh();
    }

    async openDialog() {
      let dir = this.cwd;
      const list = el('div', { style: { maxHeight: '320px', overflow: 'auto', border: '1px solid var(--pl-border)', borderRadius: '3px' } });
      const pathEl = el('div', { class: 'pl-mono', style: { fontSize: '12px' } });
      let chosen = null;
      const show = async (d) => {
        dir = d;
        pathEl.textContent = d;
        const res = await PL.engine.call('list_dir', d);
        const t = el('table', { class: 'pl-table' });
        const b = el('tbody');
        if (d !== '/') {
          const tr = el('tr', null, el('td', null, el('span', { class: 'pl-name' }, icon('up', 'pl-ficon'), el('span', null, '..'))));
          tr.addEventListener('dblclick', () => show(U.dirname(d)));
          b.append(tr);
        }
        for (const it of res.items || []) {
          const tr = el('tr', null, el('td', null, el('span', { class: 'pl-name' }, icon(it.dir ? 'folder' : it.kind === 'mfile' ? 'mfile' : it.kind === 'fig' ? 'figure' : it.kind === 'mat' ? 'matfile' : 'file', 'pl-ficon'), el('span', null, it.name))));
          tr.addEventListener('click', () => { for (const x of b.children) x.classList.remove('is-sel'); tr.classList.add('is-sel'); chosen = it.dir ? null : U.joinPath(d, it.name); });
          tr.addEventListener('dblclick', () => { if (it.dir) show(U.joinPath(d, it.name)); else { chosen = U.joinPath(d, it.name); close?.(); } });
          b.append(tr);
        }
        t.append(b);
        list.replaceChildren(t);
      };
      let close = null;
      await show(dir);
      const p = U.dialog({
        title: 'Open',
        body: [pathEl, list],
        width: 520,
        buttons: [{ label: 'Cancel', value: null }, { label: 'Open', primary: true, value: () => chosen }],
        onOpen: (body) => { close = () => body.closest('.pl-dialog').querySelector('.is-primary').click(); },
      });
      const r = await p;
      if (!r) return;
      // a figure opens as a figure, a MAT-file loads, a picture shows; the rest goes to the Editor
      const how = this.opens(r);
      const q = U.mstr(r);
      if ((how === 'openfig' || how === 'load') && q) this.runCommand(`${how}(${q})`);
      else if (how === 'image') this.previewImage(r);
      else this.openFile(r);
    }

    async openFile(path, line) {
      if (!path) return null;
      let doc = this.docs.find((d) => d.kind === 'file' && d.key === path);
      if (!doc) {
        let text;
        try { text = await PL.engine.fs('read', { path }); } catch (e) { U.toast(`Could not open ${path}: ${e.message}`); return null; }
        if (/\.(png|jpe?g|gif|svg)$/i.test(path)) { this.previewImage(path); return null; }
        doc = new Doc(this, 'file', path, U.basename(path));
        const ed = new PL.Editor({ value: text, label: `Editor: ${U.basename(path)}`, language: /\.m$/i.test(path) ? 'matlab' : 'text' });
        doc.editor = ed;
        doc.saved = text;
        ed.setBreakpoints(this.breakpoints[path] || []);
        ed.on('change', (v) => { doc.setDirty(v !== doc.saved); this.scheduleLint(doc); this.saveDocs(); });
        ed.on('gutter', (ln) => this.toggleBreakpoint(doc, ln));
        ed.on('cursor', (ln, col) => { this.caretEl.textContent = `Ln ${ln}, Col ${col}`; });
        ed.on('key', (ev) => this.editorKey(ev, doc));
        doc.view.append(ed.el);
        this.addDoc(doc);
        this.scheduleLint(doc);
      }
      this.showDoc(doc);
      if (line) doc.editor.gotoLine(line);
      return doc;
    }

    addDoc(doc) {
      this.docs.push(doc);
      this.edTabs.append(doc.tab);
      this.edBody.append(doc.view);
      this.renderEdTabs();
      this.saveDocs();
    }

    showDoc(doc) {
      this.current = doc;
      for (const d of this.docs) {
        d.view.classList.toggle('is-shown', d === doc);
        d.tab.setAttribute('aria-selected', String(d === doc));
      }
      doc.tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      if (doc.editor) { requestAnimationFrame(() => { doc.editor._gutterDraw(); doc.editor.focus(); }); }
      if (doc.kind === 'var' && doc.vv) doc.vv.refresh();
      if (doc.kind === 'file') this.showStrip('editor');
      this.renderEdTabs();
      this.updateRunButtons();
      this.saveDocs();
    }

    async closeDoc(doc) {
      if (doc.dirty) {
        const r = await U.dialog({
          title: 'Save changes',
          body: el('p', { style: { margin: 0 } }, `Save the changes to ${doc.title}?`),
          buttons: [{ label: 'Cancel', value: null }, { label: 'Don’t save', value: 'no' }, { label: 'Save', primary: true, value: 'yes' }],
        });
        if (!r) return;
        if (r === 'yes' && !(await this.save(doc))) return;
      }
      const i = this.docs.indexOf(doc);
      this.docs.splice(i, 1);
      doc.tab.remove();
      doc.view.remove();
      if (this.current === doc) {
        this.current = null;
        const next = this.docs[Math.min(i, this.docs.length - 1)];
        if (next) this.showDoc(next);
      }
      this.renderEdTabs();
      this.saveDocs();
      this.updateRunButtons();
    }

    renderEdTabs() {
      const empty = !this.docs.length;
      this.center.classList.toggle('no-editor', empty);
      this.pEditor.hidden = empty;
    }

    withEditor(fn) {
      const d = this.current;
      if (d && d.editor && !d.editor.readOnly) fn(d.editor);
      else if (d && d.editor && d.kind === 'python') fn(d.editor);
    }

    async save(doc = this.current) {
      if (!doc || doc.kind !== 'file') return false;
      const text = doc.editor.value;
      try {
        await PL.engine.fs('write', { path: doc.key, data: text });
      } catch (e) { U.toast(`Could not save: ${e.message}`); return false; }
      doc.saved = text;
      doc.setDirty(false);
      if (U.dirname(doc.key) === this.cwd) this.folder.refresh();
      this.saveDocs();
      return true;
    }

    async saveAs(doc = this.current) {
      if (!doc || doc.kind !== 'file') return;
      const name = await U.prompt('Save As', 'File name (in the folder of the file)', U.basename(doc.key));
      if (!name) return;
      const path = name.startsWith('/') ? name : U.joinPath(U.dirname(doc.key), /\.\w+$/.test(name) ? name : `${name}.m`);
      try { await PL.engine.fs('write', { path, data: doc.editor.value }); } catch (e) { U.toast(e.message); return; }
      const old = doc.key;
      doc.key = path;
      doc.setTitle(U.basename(path));
      doc.tab.title = path;
      doc.saved = doc.editor.value;
      doc.setDirty(false);
      this.folder.refresh();
      this.saveDocs();
      return old;
    }

    fileRenamed(from, to) {
      for (const d of this.docs) {
        if (d.kind === 'file' && (d.key === from || d.key.startsWith(`${from}/`))) {
          d.key = to + d.key.slice(from.length);
          d.setTitle(U.basename(d.key));
          d.tab.title = d.key;
        }
      }
      if (this.breakpoints[from]) { this.breakpoints[to] = this.breakpoints[from]; delete this.breakpoints[from]; U.store.set('breakpoints', this.breakpoints); }
      this.saveDocs();
    }

    fileRemoved(path) {
      for (const d of [...this.docs]) if (d.kind === 'file' && (d.key === path || d.key.startsWith(`${path}/`))) { d.setDirty(false); this.closeDoc(d); }
    }

    async duplicateFile(path) {
      const dir = U.dirname(path);
      const base = U.basename(path).replace(/(\.\w+)?$/, '');
      const ext = (/\.\w+$/.exec(path) || [''])[0];
      let n = 1;
      let to;
      do { to = U.joinPath(dir, `${base}_copy${n > 1 ? n : ''}${ext}`); n += 1; } while (await PL.engine.fs('exists', { path: to }));
      const data = await PL.engine.fs('read', { path, binary: true });
      await PL.engine.fs('write', { path: to, data, binary: true }, [data]);
      this.folder.refresh();
    }

    async downloadFile(path) {
      try {
        const data = await PL.engine.fs('read', { path, binary: true });
        U.download(U.basename(path), new Blob([data]));
      } catch (e) { U.toast(`Could not download: ${e.message}`); }
    }

    pickUpload(dir) {
      const input = el('input', { type: 'file', multiple: true, style: { display: 'none' } });
      input.addEventListener('change', () => { this.upload([...input.files], dir); input.remove(); });
      document.body.append(input);
      input.click();
    }

    upload(files, dir) {
      return this.copyIn(files.map((file) => ({ entry: null, file })), dir || this.cwd, false);
    }

    /* ---- files dropped from the computer -------------------------------------------- */
    /* Dropped anywhere on the page, files are copied into the current folder
       and opened as a double-click in the Current Folder opens them: programs
       and text in the Editor, MAT-files loaded into the workspace (the load
       shows in the Command Window, as if typed), pictures shown; other files
       are only copied. The Current Folder only copies what is dropped on it,
       into the folder under the pointer. A dropped folder is copied with what
       it holds. */
    wireDrops() {
      const hasFiles = (ev) => [...(ev.dataTransfer?.types || [])].includes('Files');
      this.deskZone = el('div', { class: 'pl-dropzone is-desk', hidden: true }, el('strong', null, 'Drop to open'), el('span'));
      this.root.append(this.deskZone);
      window.addEventListener('dragover', (ev) => {
        if (!hasFiles(ev)) return;
        ev.preventDefault();      // a file dropped anywhere is the page's, never the browser's to open
        const modal = !!document.querySelector('.pl-modal-back');
        ev.dataTransfer.dropEffect = modal ? 'none' : 'copy';
        this.showDeskZone(!modal && !ev.target.closest?.('.pl-p-folder'));
      });
      window.addEventListener('drop', (ev) => {
        if (!hasFiles(ev)) return;
        const taken = ev.defaultPrevented;    // the Current Folder copied it
        ev.preventDefault();
        this.showDeskZone(false);
        if (taken || document.querySelector('.pl-modal-back')) return;
        this.takeDrop(ev.dataTransfer, this.cwd, true);
      });
    }

    /* The zone is hidden again when dragover stops coming: the drag left the
       window or was given up (neither tells the page reliably). */
    showDeskZone(on) {
      clearTimeout(this._zoneTimer);
      if (on) {
        if (this.deskZone.hidden) this.deskZone.lastChild.textContent = `They are copied into ${U.basename(this.cwd) || '/'}: programs open in the Editor, MAT-files load into the workspace.`;
        this._zoneTimer = setTimeout(() => { this.deskZone.hidden = true; }, 250);
      }
      this.deskZone.hidden = !on;
    }

    /* What a drop holds must be taken while its event lasts. */
    takeDrop(dt, into, open) {
      const items = [];
      for (const it of dt.items || []) {
        if (it.kind !== 'file') continue;
        items.push({ entry: it.webkitGetAsEntry ? it.webkitGetAsEntry() : null, file: it.getAsFile() });
      }
      if (!items.length) for (const file of dt.files || []) items.push({ entry: null, file });
      if (items.length) return this.copyIn(items, into, open);
      return null;
    }

    /* True once Python is ready (at once if it is), false if it is not running. */
    whenReady() {
      if (PL.engine.state === 'ready') return Promise.resolve(true);
      if (PL.engine.state !== 'loading') return Promise.resolve(false);
      this.cmd.write('Python is still starting: the files will be copied when it is ready.\n', 'info');
      return new Promise((resolve) => { const off = PL.engine.on('ready', () => { off(); resolve(true); }); });
    }

    /* Files (and folders, as entries) copied into a folder; with open, each
       file is then opened. A name already there asks first. Gives the names
       the files got in the folder, or null when nothing was copied. */
    async copyIn(items, into, open) {
      const MAX_FILE = 200 * 1024 * 1024, MAX_ALL = 1024 * 1024 * 1024, MAX_COUNT = 5000;
      const files = [];      // { rel: 'top/sub/name', file }
      const dirs = [];
      const tops = [];       // { name, dir }
      try {
        const walk = async (entry, rel) => {
          if (files.length > MAX_COUNT) throw new Error(`there are more than ${MAX_COUNT} files`);
          if (entry.isFile) files.push({ rel, file: await new Promise((res, rej) => entry.file(res, rej)) });
          else if (entry.isDirectory) {
            dirs.push(rel);
            const reader = entry.createReader();
            for (;;) {
              const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
              if (!batch.length) break;
              for (const e of batch) if (!e.name.startsWith('.')) await walk(e, `${rel}/${e.name}`);
            }
          }
        };
        for (const { entry, file } of items) {
          if (entry && entry.isDirectory) { tops.push({ name: entry.name, dir: true }); await walk(entry, entry.name); }
          else if (file) { tops.push({ name: file.name, dir: false }); files.push({ rel: file.name, file }); }
        }
      } catch (e) { U.toast(`The dropped files could not be read: ${e.message || e}.`, 5000); return null; }
      if (!tops.length) return null;
      const big = files.filter((f) => f.file.size > MAX_FILE);
      const total = files.reduce((s, f) => s + f.file.size, 0);
      if (files.length > MAX_COUNT || total - big.reduce((s, f) => s + f.file.size, 0) > MAX_ALL) {
        U.toast(`Not copied: at most ${MAX_COUNT} files and 1 GB at a time (these are ${files.length} files, ${U.fmtBytes(total)}).`, 6000);
        return null;
      }
      if (!(await this.whenReady())) { U.toast('Python is not running: restart it, then copy the files again.', 5000); return null; }
      const exists = (p) => PL.engine.fs('exists', { path: p }).catch(() => false);
      const rename = new Map();
      const clash = [];
      for (const t of tops) if (await exists(U.joinPath(into, t.name))) clash.push(t);
      if (clash.length) {
        const names = clash.map((t) => t.name);
        const list = names.length > 4 ? `${names.slice(0, 3).join(', ')} and ${names.length - 3} more` : names.join(', ').replace(/, ([^,]*)$/, ' and $1');
        const folders = clash.some((t) => t.dir);
        const r = await U.dialog({
          title: 'Replace files',
          body: el('p', { style: { margin: 0 } }, `${list} ${names.length > 1 ? 'are' : 'is'} already in ${U.basename(into) || '/'}. Replace ${names.length > 1 ? 'them' : 'it'}, or keep both (what you dropped gets a new name)?`
            + (folders ? ' A folder replaced keeps the files that the dropped one does not have.' : '')),
          buttons: [{ label: 'Cancel', value: null }, { label: 'Keep both', value: 'both' }, { label: 'Replace', primary: true, value: 'replace' }],
        });
        if (!r) return null;
        if (r === 'both') {
          for (const t of clash) {
            const dot = t.dir ? -1 : t.name.lastIndexOf('.');
            const [base, ext] = dot > 0 ? [t.name.slice(0, dot), t.name.slice(dot)] : [t.name, ''];
            let n = 2;
            while (await exists(U.joinPath(into, `${base}_${n}${ext}`))) n += 1;
            rename.set(t.name, `${base}_${n}${ext}`);
          }
        }
      }
      const target = (rel) => {
        const i = rel.indexOf('/');
        const top = i < 0 ? rel : rel.slice(0, i);
        return U.joinPath(into, (rename.get(top) || top) + (i < 0 ? '' : rel.slice(i)));
      };
      const failed = [];
      let copied = 0;
      try {
        for (const d of dirs) await PL.engine.fs('mkdir', { path: target(d) });
        for (const f of files) {
          if (f.file.size > MAX_FILE) { failed.push(`${f.rel} (larger than 200 MB)`); continue; }
          if (files.length > 5) this.statusText.textContent = `Copying ${copied + 1} of ${files.length}: ${f.rel}`;
          try {
            const data = await f.file.arrayBuffer();
            await PL.engine.fs('write', { path: target(f.rel), data, binary: true }, [data]);
            copied += 1;
            this.reloadDoc(target(f.rel));
          } catch (e) { failed.push(`${f.rel} (${e.message || e})`); }
        }
      } finally {
        this.statusText.textContent = '';
        this.folder.refresh();
      }
      const where = U.basename(into) || '/';
      if (failed.length) U.toast(`${copied ? `${copied} of ${files.length} files copied into ${where}. ` : ''}Not copied: ${failed.slice(0, 3).join('; ')}${failed.length > 3 ? ` and ${failed.length - 3} more` : ''}.`, 7000);
      else if (!open || tops.some((t) => t.dir || !this.opens(t.name))) {
        const what = tops.length === 1 && tops[0].dir ? `The folder ${rename.get(tops[0].name) || tops[0].name} (${copied} file${copied === 1 ? '' : 's'}) was` : `${copied} file${copied === 1 ? ' was' : 's were'}`;
        U.toast(`${what} copied into ${where}.`);
      }
      const named = tops.filter((t) => !failed.some((x) => x.startsWith(`${t.name} (`))).map((t) => ({ name: rename.get(t.name) || t.name, dir: t.dir }));
      if (open) await this.openDropped(named, into);
      return named;
    }

    /* How a dropped file is opened, by its extension (as the Current Folder sorts them). */
    opens(name) {
      const ext = (/\.[^./]+$/.exec(name.toLowerCase()) || [''])[0];
      if (ext === '.m') return 'editor';
      if (ext === '.mat') return 'load';
      if (ext === '.fig') return 'openfig';
      if (['.png', '.jpg', '.jpeg', '.svg', '.gif'].includes(ext)) return 'image';
      if (['.txt', '.csv', '.dat', '.json', '.md', '.tsv'].includes(ext)) return 'editor';
      return null;
    }

    async openDropped(tops, into) {
      for (const t of tops) {
        if (t.dir) continue;
        const path = U.joinPath(into, t.name);
        const how = this.opens(t.name);
        if (how === 'editor') await this.openFile(path);
        else if (how === 'image') await this.previewImage(path);
      }
      for (const t of tops) {
        const how = t.dir ? null : this.opens(t.name);
        if (how !== 'load' && how !== 'openfig') continue;
        const q = U.mstr(into === this.cwd ? t.name : U.joinPath(into, t.name));
        if (q) this.cmd.enter(`${how}(${q})`);
        else U.toast(`${t.name.replace(/[\u0000-\u001f\u007f]/g, '?')} was copied but not ${how === 'load' ? 'loaded' : 'opened'}: its name holds a control character.`, 5000);
      }
    }

    /* A file written over while it is open in the Editor: the Editor shows
       the new text, unless it holds changes not saved (they stay, as changes
       to the new file). */
    async reloadDoc(path) {
      const doc = this.docs.find((d) => d.kind === 'file' && d.key === path);
      if (!doc) return;
      let text;
      try { text = await PL.engine.fs('read', { path }); } catch (e) { return; }
      if (doc.dirty) { doc.saved = text; doc.setDirty(doc.editor.value !== text); return; }
      doc.saved = text;
      doc.editor.value = text;
      doc.setDirty(false);
      this.scheduleLint(doc);
    }

    async previewImage(path) {
      const data = await PL.engine.fs('read', { path, binary: true });
      const url = URL.createObjectURL(new Blob([data], { type: path.endsWith('.svg') ? 'image/svg+xml' : 'image/png' }));
      let doc = this.docs.find((d) => d.kind === 'image' && d.key === path);
      if (!doc) {
        doc = new Doc(this, 'image', path, U.basename(path));
        doc.view.append(el('div', { style: { position: 'absolute', inset: '0', overflow: 'auto', display: 'grid', placeItems: 'center', padding: '12px' } }, el('img', { src: url, alt: U.basename(path), style: { maxWidth: '100%' } })));
        this.addDoc(doc);
      }
      this.showDoc(doc);
    }

    /* Open files are remembered (not their unsaved text: the files are). */
    saveDocs() {
      const files = this.docs.filter((d) => d.kind === 'file').map((d) => d.key);
      U.store.set('open', { files, current: this.current && this.current.kind === 'file' ? this.current.key : null });
    }

    async restoreDocs() {
      const o = U.store.get('open', null);
      if (!o) return;
      for (const p of o.files || []) {
        const exists = await PL.engine.fs('exists', { path: p }).catch(() => false);
        if (exists === 'file') await this.openFile(p);
      }
      const cur = this.docs.find((d) => d.key === o.current);
      if (cur) this.showDoc(cur);
      this.cmd.focus();
    }

    scheduleLint(doc) {
      if (!/\.m$/i.test(doc.key)) return;
      clearTimeout(this.lintTimers.get(doc));
      this.lintTimers.set(doc, setTimeout(async () => {
        if (PL.engine.state !== 'ready') return;
        try {
          const items = await PL.engine.call('lint', doc.editor.value);
          doc.editor.setLint(items);
          if (this.current === doc) this.statusText.textContent = items.length ? `Line ${items[0].line}: ${items[0].message}` : '';
        } catch (e) { /* ignore */ }
      }, 600));
    }

    /* ---- running files ------------------------------------------------------------------- */
    async runCurrent() {
      const d = this.current;
      if (!d || d.kind !== 'file') return;
      if (this.debug) { this.dbg('continue'); return; }
      if (d.dirty && !(await this.save(d))) return;
      const path = d.key;
      if (!/\.m$/i.test(path)) { U.toast('Only program files (.m) run.'); return; }
      this.runFile(path);
    }

    /* A program in the current folder runs by its name, as typed; any other
       (or one whose name is no name) through run. */
    runFile(path) {
      const name = U.basename(path).replace(/\.m$/i, '');
      if (U.dirname(path) === this.cwd && U.isName(name)) { this.runCommand(name); return; }
      const q = U.mstr(path);
      if (q) this.runCommand(`run(${q})`);
      else U.toast('A file whose name holds a control character cannot be run: rename it first.', 5000);
    }

    runSection(advance) {
      const d = this.current;
      if (!d || !d.editor) return;
      const text = d.editor.value;
      const line = d.editor.cursorLine() - 1;
      const secs = PL.lang.sections(text);
      const s = secs.find((x) => line >= x.start && line <= x.end) || secs[0];
      if (!s) return;
      const code = text.split('\n').slice(s.start, s.end + 1).join('\n');
      this.runCommand(code, { noHistory: false });
      if (advance) {
        const next = secs[secs.indexOf(s) + 1];
        if (next) d.editor.gotoLine(next.start + 1);
      }
    }

    runSelection() {
      const d = this.current;
      if (!d || !d.editor) return;
      const sel = d.editor.selectedText() || d.editor.value.split('\n')[d.editor.cursorLine() - 1];
      if (sel.trim()) this.runCommand(sel);
    }

    async viewPython() {
      const d = this.current;
      if (!d || d.kind !== 'file') { U.toast('Open a program file first.'); return; }
      const res = await PL.engine.call('python_of', d.key, d.editor.value);
      const key = `python:${d.key}`;
      let doc = this.docs.find((x) => x.key === key);
      if (!doc) {
        doc = new Doc(this, 'python', key, `${U.basename(d.key)} (Python)`);
        doc.editor = new PL.Editor({ value: '', readOnly: true, language: 'python', label: 'Compiled Python' });
        doc.view.append(doc.editor.el);
        this.addDoc(doc);
      }
      doc.editor.value = res.ok ? res.python : `# The file does not compile:\n# line ${res.line}: ${res.message}\n`;
      this.showDoc(doc);
    }

    editorKey(ev, doc) {
      const mod = U.mod(ev);
      if (ev.key === 'F5' && !ev.shiftKey) { ev.preventDefault(); this.runCurrent(); return; }
      if (ev.key === 'F5' && ev.shiftKey) { ev.preventDefault(); this.dbg('quit'); return; }
      if (ev.key === 'F9') { ev.preventDefault(); this.runSelection(); return; }
      if (ev.key === 'F10') { ev.preventDefault(); this.dbg('step'); return; }
      if (ev.key === 'F11' && !ev.shiftKey) { ev.preventDefault(); this.dbg('stepin'); return; }
      if (ev.key === 'F11' && ev.shiftKey) { ev.preventDefault(); this.dbg('stepout'); return; }
      if (ev.key === 'F12') { ev.preventDefault(); this.toggleBreakpoint(doc, doc.editor.cursorLine()); return; }
      if (mod && ev.key === 'Enter') { ev.preventDefault(); this.runSection(ev.shiftKey); return; }
      if (mod && (ev.key === 's' || ev.key === 'S')) { ev.preventDefault(); if (ev.shiftKey) this.saveAs(doc); else this.save(doc); }
    }

    globalKey(ev) {
      const mod = U.mod(ev);
      if (document.querySelector('.pl-modal-back')) return;
      if (mod && (ev.key === 'n' || ev.key === 'N') && !ev.shiftKey && !ev.altKey) { ev.preventDefault(); this.newFile('script'); return; }
      if (mod && (ev.key === 'o' || ev.key === 'O') && !ev.shiftKey) { ev.preventDefault(); this.openDialog(); return; }
      if (mod && ev.key === '0' && !ev.shiftKey) { ev.preventDefault(); this.cmd.focus(); return; }
      if (mod && (ev.key === ')' || (ev.key === '0' && ev.shiftKey))) { ev.preventDefault(); if (this.current && this.current.editor) this.current.editor.focus(); return; }
      if (mod && (ev.key === 's' || ev.key === 'S')) { ev.preventDefault(); this.save(); return; }
      if (ev.key === 'F5' && this.debug) { ev.preventDefault(); this.dbg('continue'); return; }
      if (ev.key === 'F10' && this.debug) { ev.preventDefault(); this.dbg('step'); }
    }

    /* ---- variables ---------------------------------------------------------------------- */
    openVariable(name) {
      const key = `var:${name}`;
      let doc = this.docs.find((d) => d.key === key);
      if (!doc) {
        doc = new Doc(this, 'var', key, name);
        doc.vv = new PL.VariableView(this, name);
        doc.view.append(doc.vv.el);
        this.addDoc(doc);
      }
      this.showDoc(doc);
    }

    refreshVariableViews() {
      for (const d of this.docs) if (d.kind === 'var' && d.vv && d.view.classList.contains('is-shown')) d.vv.refresh();
    }

    async openVariableAsk() {
      const name = await U.prompt('Open Variable', 'Name (or an expression such as s.data)', this.ws.selected()[0]?.name || '');
      if (name) this.openVariable(name);
    }

    async newVariable() {
      const name = await U.prompt('New variable', 'Name', 'unnamed');
      if (!name) return;
      await this.runCommand(`${name} = 0;`, { silent: true });
      this.openVariable(name);
    }

    async renameVariable(name) {
      const nn = await U.prompt('Rename variable', 'New name', name);
      if (nn && nn !== name) this.runCommand(`${nn} = ${name}; clear ${name}`, { silent: true });
    }

    duplicateVariable(name) {
      this.runCommand(`${name}Copy = ${name};`, { silent: true });
    }

    async saveWorkspace(names) {
      const fname = await U.prompt('Save workspace', 'MAT-file name (in the current folder)', 'workspace.mat');
      if (!fname) return;
      const q = U.mstr(fname);
      if (!q) { U.toast('A file name cannot hold a control character.'); return; }
      const list = (names || []).filter(U.isName).map((n) => `,'${n}'`).join('');
      const r = await this.runCommand(`save(${q}${list})`, { silent: true });
      if (r && r.ok) U.toast(`Saved ${fname}.`);
    }

    importData() {
      const input = el('input', { type: 'file', accept: '.mat,.csv,.txt,.dat', style: { display: 'none' } });
      input.addEventListener('change', async () => {
        const f = input.files[0];
        input.remove();
        if (!f) return;
        const got = await this.upload([f], this.cwd);
        if (!got || !got.length) return;
        const name = got[0].name;
        const q = U.mstr(name);
        if (!q) return;
        if (/\.mat$/i.test(name)) this.runCommand(`load(${q})`);
        else {
          const v = name.replace(/\.\w+$/, '').replace(/\W/g, '_').replace(/^[^A-Za-z]/, 'x$&');
          this.runCommand(`${U.isName(v) ? v : 'data'} = readmatrix(${q})`);
        }
      });
      document.body.append(input);
      input.click();
    }

    complete(text, pos) {
      return PL.engine.call('complete', text, pos);
    }

    /* ---- help, preferences, info ------------------------------------------------------------- */
    openHelp(name) {
      let doc = this.docs.find((d) => d.kind === 'help');
      if (!doc) {
        doc = new Doc(this, 'help', 'help', 'Help');
        doc.help = new PL.HelpView(this);
        doc.view.append(doc.help.el);
        this.addDoc(doc);
      }
      this.showDoc(doc);
      if (name) doc.help.show(name); else doc.help.home();
    }

    async preferences() {
      const cur = U.store.get('format', { mode: 'short', spacing: 'loose' });
      const fontSize = U.store.get('fontSize', 13);
      const modes = ['short', 'long', 'shortE', 'longE', 'shortG', 'longG', 'bank', 'rat', 'hex'];
      const body = el('div', { style: { display: 'grid', gap: '10px' } },
        el('label', null, 'Numeric format (format …)', el('select', { name: 'mode' }, modes.map((m) => el('option', { value: m, selected: m === cur.mode }, m)))),
        el('label', null, 'Line spacing', el('select', { name: 'spacing' }, ['loose', 'compact'].map((m) => el('option', { value: m, selected: m === cur.spacing }, m)))),
        el('label', null, 'Font size of code (px)', el('select', { name: 'font' }, [11, 12, 13, 14, 15, 16, 18].map((s) => el('option', { value: s, selected: s === fontSize }, String(s))))));
      const r = await U.dialog({ title: 'Preferences', body, buttons: [{ label: 'Cancel', value: null }, { label: 'OK', primary: true, value: (b) => ({ mode: b.querySelector('[name=mode]').value, spacing: b.querySelector('[name=spacing]').value, font: Number(b.querySelector('[name=font]').value) }) }] });
      if (!r) return;
      U.store.set('format', { mode: r.mode, spacing: r.spacing });
      U.store.set('fontSize', r.font);
      this.root.style.setProperty('--pl-mono-size', `${r.font}px`);
      await PL.engine.call('set_format', JSON.stringify({ mode: r.mode, spacing: r.spacing }));
      for (const d of this.docs) if (d.editor) d.editor._draw(true);
    }

    engineInfo() {
      const v = this.versions || {};
      U.dialog({
        title: 'The Python engine',
        body: el('div', null,
          el('p', { style: { marginTop: 0 } }, 'Programs are compiled to Python and run in a worker of this tab, on Pyodide (CPython compiled to WebAssembly).'),
          el('table', { class: 'pl-table' }, el('tbody', null, Object.entries(v).map(([k, x]) => el('tr', null, el('td', null, k), el('td', { class: 'pl-mono' }, x))))),
          el('p', null, 'Your files live in this browser (IndexedDB), in /home/user.')),
        buttons: [{ label: 'Restart Python…', value: 'restart' }, { label: 'Close', primary: true, value: null }],
      }).then((r) => { if (r === 'restart') this.restartEngine(); });
    }
  }

  PL.App = App;
})(window);
