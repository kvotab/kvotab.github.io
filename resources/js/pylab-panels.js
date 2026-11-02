/* ==========================================================================
   PYLAB.HTML: THE PANELS

   PL.History          the commands run, by session (kept in localStorage)
   PL.HistoryPanel     Command History: double-click runs, Enter too
   PL.FolderPanel      Current Folder: double-click opens (programs in the
                       Editor, MAT-files into the workspace, folders as the
                       current folder); files dropped on it are uploaded
   PL.DetailsPanel     a program's help comment, a MAT-file's variables
   PL.WorkspacePanel   Name, Value, Size, Class; double-click opens the
                       variable; the selection feeds the PLOTS tab
   PL.VariableView     a variable as a grid (numbers editable)
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, Emitter, icon } = PL;
  const U = () => PL.util;

  /* ---- history ------------------------------------------------------------- */
  class History extends Emitter {
    constructor() {
      super();
      this.items = U().store.get('history', []);      // [{c, t, s (session start), e (error)}]
      this.session = Date.now();
      this.max = 5000;
    }

    commands() { return this.items.map((i) => i.c); }

    add(code, ok = true) {
      const c = code.replace(/\s+$/, '');
      if (!c.trim()) return;
      const last = this.items[this.items.length - 1];
      if (last && last.c === c && last.s === this.session) { last.e = !ok; this.save(); this.emit('change'); return; }
      this.items.push({ c, t: Date.now(), s: this.session, e: !ok });
      if (this.items.length > this.max) this.items.splice(0, this.items.length - this.max);
      this.save();
      this.emit('change');
    }

    markLast(ok) {
      const last = this.items[this.items.length - 1];
      if (last) { last.e = !ok; this.save(); this.emit('change'); }
    }

    remove(indices) {
      const set = new Set(indices);
      this.items = this.items.filter((_, i) => !set.has(i));
      this.save();
      this.emit('change');
    }

    clear() { this.items = []; this.save(); this.emit('change'); }
    save() { U().store.set('history', this.items); }
  }

  class HistoryPanel {
    constructor(history, app) {
      this.h = history;
      this.app = app;
      this.sel = new Set();
      this.el = el('div', { class: 'pl-hist', tabindex: '0', role: 'listbox', 'aria-label': 'Command history' });
      history.on('change', () => this.render());
      this.el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && this.sel.size) { ev.preventDefault(); this.runSelected(); }
        if ((ev.key === 'Delete' || ev.key === 'Backspace') && this.sel.size) { ev.preventDefault(); this.h.remove([...this.sel]); this.sel.clear(); }
      });
      this.render();
    }

    render() {
      const frag = document.createDocumentFragment();
      let session = null;
      this.h.items.forEach((it, i) => {
        if (it.s !== session) {
          session = it.s;
          const d = new Date(it.s);
          frag.append(el('div', { class: 'pl-hist-session' }, `%-- ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} --%`));
        }
        const row = el('div', { class: `pl-hist-item${this.sel.has(i) ? ' is-sel' : ''}${it.e ? ' is-err' : ''}`, role: 'option', title: it.c, draggable: 'true' }, it.c.split('\n')[0] + (it.c.includes('\n') ? ' …' : ''));
        row.addEventListener('click', (ev) => this.click(i, ev));
        row.addEventListener('dblclick', () => this.app.runCommand(it.c));
        row.addEventListener('dragstart', (ev) => ev.dataTransfer.setData('text/plain', it.c));
        row.addEventListener('contextmenu', (ev) => {
          ev.preventDefault();
          if (!this.sel.has(i)) { this.sel = new Set([i]); this.render(); }
          U().menu(ev.clientX, ev.clientY, [
            { label: 'Evaluate selection', action: () => this.runSelected() },
            { label: 'Copy', action: () => navigator.clipboard?.writeText(this.selectedText()) },
            { label: 'Put in the Command Window', action: () => this.app.cmd.setLine(this.selectedText()) },
            { label: 'Create script from selection', action: () => this.app.newScript(this.selectedText()) },
            '-',
            { label: 'Delete selection', action: () => { this.h.remove([...this.sel]); this.sel.clear(); } },
            { label: 'Clear Command History…', action: async () => { if (await U().confirm('Clear Command History', 'Remove every command from the history?', 'Clear')) this.h.clear(); } },
          ]);
        });
        frag.append(row);
      });
      if (!this.h.items.length) frag.append(el('div', { class: 'pl-empty' }, 'Commands you run appear here.'));
      this.el.replaceChildren(frag);
      this.el.scrollTop = this.el.scrollHeight;
    }

    click(i, ev) {
      if (ev.shiftKey && this.anchor != null) {
        const [a, b] = [Math.min(this.anchor, i), Math.max(this.anchor, i)];
        this.sel = new Set(Array.from({ length: b - a + 1 }, (_, k) => a + k));
      } else if (U().mod(ev)) {
        if (this.sel.has(i)) this.sel.delete(i); else this.sel.add(i);
        this.anchor = i;
      } else { this.sel = new Set([i]); this.anchor = i; }
      const top = this.el.scrollTop;
      this.render();
      this.el.scrollTop = top;
    }

    selectedText() { return [...this.sel].sort((a, b) => a - b).map((i) => this.h.items[i].c).join('\n'); }
    runSelected() { const t = this.selectedText(); if (t) this.app.runCommand(t); }
  }

  /* A modification time as short as the column: the time today, the day and
     month this year, the date before that. */
  function shortDate(d) {
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
    return d.toLocaleDateString([], { year: 'numeric', month: '2-digit', day: '2-digit' });
  }

  /* ---- class glyphs ------------------------------------------------------------- */
  const CLASS_TINT = {
    double: ['#2f6fb0', '#'], single: ['#3f7fc0', 's'], logical: ['#3a8a3a', '✓'], char: ['#8a4fb0', 'ch'], string: ['#8a4fb0', '"'],
    cell: ['#a0662a', '{}'], struct: ['#b0472f', 's'], function_handle: ['#5b5b5b', '@'],
  };

  function classGlyph(cls) {
    const [bg, t] = CLASS_TINT[cls] || (/int/.test(cls) ? ['#2f6f8a', 'i'] : ['#666', '·']);
    return el('span', { class: 'pl-cls', style: { background: bg }, 'aria-hidden': 'true' }, t);
  }

  /* ---- the workspace ---------------------------------------------------------- */
  class WorkspacePanel extends Emitter {
    constructor(app) {
      super();
      this.app = app;
      this.rows = [];
      this.sel = new Set();
      this.sort = U().store.get('wsSort', { key: 'name', dir: 1 });
      this.cols = [['name', 'Name'], ['value', 'Value'], ['size', 'Size'], ['class', 'Class']];
      this.table = el('table', { class: 'pl-table' });
      this.el = el('div', { class: 'pl-wspanel', tabindex: '0' }, this.table);
      this.el.addEventListener('keydown', (ev) => {
        if ((ev.key === 'Delete' || ev.key === 'Backspace') && this.sel.size) { ev.preventDefault(); this.app.runCommand(`clear ${[...this.sel].join(' ')}`, { silentEcho: false }); }
        if (ev.key === 'Enter' && this.sel.size === 1) { ev.preventDefault(); this.app.openVariable([...this.sel][0]); }
      });
      this.el.addEventListener('contextmenu', (ev) => {
        if (ev.target.closest('tr[data-name]')) return;
        ev.preventDefault();
        U().menu(ev.clientX, ev.clientY, [
          { label: 'New variable…', action: () => this.app.newVariable() },
          { label: 'Save workspace…', action: () => this.app.saveWorkspace() },
          { label: 'Clear workspace', action: () => this.app.runCommand('clear') },
        ]);
      });
      this.render();
    }

    update(rows) {
      const old = new Map(this.rows.map((r) => [r.name, r.value + r.size + r.class]));
      this.changed = new Set(rows.filter((r) => old.has(r.name) ? old.get(r.name) !== r.value + r.size + r.class : this.rows.length > 0).map((r) => r.name));
      this.rows = rows;
      for (const n of [...this.sel]) if (!rows.find((r) => r.name === n)) this.sel.delete(n);
      this.render();
      this.emit('selection', this.selected());
    }

    selected() { return this.rows.filter((r) => this.sel.has(r.name)); }

    render() {
      const head = el('tr', null, this.cols.map(([k, label]) => {
        const th = el('th', { scope: 'col', style: { width: k === 'name' ? '30%' : k === 'value' ? '34%' : '18%' } }, label,
          this.sort.key === k ? el('span', { class: 'pl-sortmark' }, this.sort.dir > 0 ? '▲' : '▼') : null);
        th.addEventListener('click', () => { this.sort = { key: k, dir: this.sort.key === k ? -this.sort.dir : 1 }; U().store.set('wsSort', this.sort); this.render(); });
        return th;
      }));
      const rows = [...this.rows].sort((a, b) => {
        const k = this.sort.key;
        const x = k === 'size' ? a.numel : String(a[k]).toLowerCase(), y = k === 'size' ? b.numel : String(b[k]).toLowerCase();
        return (x < y ? -1 : x > y ? 1 : 0) * this.sort.dir;
      });
      const body = el('tbody');
      for (const r of rows) {
        const tr = el('tr', { 'data-name': r.name, class: `${this.sel.has(r.name) ? 'is-sel' : ''}${this.changed && this.changed.has(r.name) ? ' is-new' : ''}`, draggable: 'true' },
          el('td', null, el('span', { class: 'pl-name' }, classGlyph(r.class), el('span', null, r.name + (r.global ? ' (global)' : '')))),
          el('td', { class: 'pl-mono', title: r.value }, r.value),
          el('td', { class: 'pl-mono' }, r.size),
          el('td', null, r.class + (r.complex ? ' (complex)' : '')));
        tr.addEventListener('click', (ev) => this.click(r.name, ev, rows));
        tr.addEventListener('dblclick', () => this.app.openVariable(r.name));
        tr.addEventListener('dragstart', (ev) => ev.dataTransfer.setData('text/plain', r.name));
        tr.addEventListener('contextmenu', (ev) => {
          ev.preventDefault();
          if (!this.sel.has(r.name)) { this.sel = new Set([r.name]); this.render(); this.emit('selection', this.selected()); }
          const names = [...this.sel];
          U().menu(ev.clientX, ev.clientY, [
            { label: 'Open selection', action: () => names.forEach((n) => this.app.openVariable(n)) },
            { label: 'Plot selection', disabled: !this.app.plotGallery.canPlot('plot'), action: () => this.app.plotGallery.plot('plot') },
            '-',
            { label: 'Rename…', disabled: names.length !== 1, action: () => this.app.renameVariable(names[0]) },
            { label: 'Duplicate', disabled: names.length !== 1, action: () => this.app.duplicateVariable(names[0]) },
            { label: 'Copy name', action: () => navigator.clipboard?.writeText(names.join(' ')) },
            { label: 'Save as MAT-file…', action: () => this.app.saveWorkspace(names) },
            '-',
            { label: 'Delete', kbd: 'Del', action: () => this.app.runCommand(`clear ${names.join(' ')}`) },
          ]);
        });
        body.append(tr);
      }
      this.table.replaceChildren(el('thead', null, head), body);
      if (!rows.length) this.table.append(el('caption', { class: 'pl-empty', style: { captionSide: 'bottom', textAlign: 'left' } }, 'The workspace is empty.'));
      this.changed = null;
    }

    click(name, ev, rows) {
      if (ev.shiftKey && this.anchor) {
        const names = rows.map((r) => r.name);
        const a = names.indexOf(this.anchor), b = names.indexOf(name);
        this.sel = new Set(names.slice(Math.min(a, b), Math.max(a, b) + 1));
      } else if (U().mod(ev)) {
        if (this.sel.has(name)) this.sel.delete(name); else this.sel.add(name);
        this.anchor = name;
      } else { this.sel = new Set([name]); this.anchor = name; }
      this.render();
      this.emit('selection', this.selected());
    }
  }

  /* ---- the current folder ---------------------------------------------------- */
  function fileIcon(kind) {
    return icon({ folder: 'folder', mfile: 'mfile', mat: 'matfile', fig: 'figure', text: 'textfile', image: 'image' }[kind] || 'file', 'pl-ficon');
  }

  class FolderPanel extends Emitter {
    constructor(app) {
      super();
      this.app = app;
      this.path = '';
      this.items = [];
      this.sel = null;
      this.sort = U().store.get('fileSort', { key: 'name', dir: 1 });
      this.table = el('table', { class: 'pl-table' });
      this.el = el('div', { class: 'pl-folder', tabindex: '0', style: { position: 'relative', minHeight: '100%' } }, this.table);
      this.el.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && this.sel) { ev.preventDefault(); this.open(this.sel); }
        if ((ev.key === 'Delete' || ev.key === 'Backspace') && this.sel) { ev.preventDefault(); this.remove(this.sel); }
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          const names = this.sorted().map((i) => i.name);
          const k = Math.max(-1, names.indexOf(this.sel?.name)) + (ev.key === 'ArrowDown' ? 1 : -1);
          const it = this.sorted()[Math.max(0, Math.min(names.length - 1, k))];
          if (it) this.select(it);
        }
      });
      this.el.addEventListener('contextmenu', (ev) => {
        if (ev.target.closest('tr[data-name]')) return;
        ev.preventDefault();
        this.folderMenu(ev.clientX, ev.clientY);
      });
      // files dropped from the computer are copied here, or into the folder under the pointer
      this.el.addEventListener('dragover', (ev) => {
        if (![...ev.dataTransfer.types].includes('Files')) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'copy';
        this.dropTarget(ev.target.closest?.('tr[data-name]'));
      });
      this.el.addEventListener('dragleave', (ev) => { if (!this.el.contains(ev.relatedTarget)) this.dropTarget(false); });
      this.el.addEventListener('drop', (ev) => {
        if (![...ev.dataTransfer.types].includes('Files')) return;
        ev.preventDefault();
        const into = this.dropInto || this.path;
        this.dropTarget(false);
        this.app.takeDrop(ev.dataTransfer, into, false);
      });
    }

    /* The zone and the folder row a drop would go into (a row that is no
       folder means this folder); false hides them. They hide by themselves
       when dragover stops coming (the drag left or was given up). */
    dropTarget(row) {
      clearTimeout(this.zoneTimer);
      const it = row && this.items.find((i) => i.dir && i.name === row.dataset.name);
      for (const tr of this.table.querySelectorAll('tr.is-droptarget')) if (!it || tr !== row) tr.classList.remove('is-droptarget');
      if (row === false) { this.zone?.remove(); this.zone = null; this.dropInto = null; return; }
      if (it) row.classList.add('is-droptarget');
      this.dropInto = it ? U().joinPath(this.path, it.name) : null;
      if (!this.zone) { this.zone = el('div', { class: 'pl-dropzone' }); this.el.append(this.zone); }
      this.zone.textContent = `Drop to upload into ${it ? it.name : U().basename(this.path) || '/'}`;
      this.zoneTimer = setTimeout(() => this.dropTarget(false), 250);
    }

    folderMenu(x, y) {
      U().menu(x, y, [
        { label: 'New script', action: () => this.app.newFile('script', this.path) },
        { label: 'New function', action: () => this.app.newFile('function', this.path) },
        { label: 'New folder…', action: () => this.app.newFolder(this.path) },
        '-',
        { label: 'Upload files…', action: () => this.app.pickUpload(this.path) },
        { label: 'Refresh', action: () => this.refresh() },
      ]);
    }

    async show(path) {
      this.path = path;
      await this.refresh();
    }

    async refresh() {
      let res;
      try { res = await PL.engine.call('list_dir', this.path); } catch (e) { return; }
      if (res.error) { this.items = []; this.render(res.error); return; }
      this.items = res.items;
      if (this.sel && !this.items.find((i) => i.name === this.sel.name)) this.sel = null;
      this.render();
    }

    sorted() {
      const k = this.sort.key;
      return [...this.items].sort((a, b) => {
        if (a.dir !== b.dir) return a.dir ? -1 : 1;
        const x = k === 'name' ? a.name.toLowerCase() : k === 'size' ? a.size : a.mtime;
        const y = k === 'name' ? b.name.toLowerCase() : k === 'size' ? b.size : b.mtime;
        return (x < y ? -1 : x > y ? 1 : 0) * this.sort.dir;
      });
    }

    render(error) {
      const head = el('tr', null, [['name', 'Name', '62%'], ['mtime', 'Date modified', '38%']].map(([k, label, w]) => {
        const th = el('th', { scope: 'col', style: { width: w } }, label, this.sort.key === k ? el('span', { class: 'pl-sortmark' }, this.sort.dir > 0 ? '▲' : '▼') : null);
        th.addEventListener('click', () => { this.sort = { key: k, dir: this.sort.key === k ? -this.sort.dir : 1 }; U().store.set('fileSort', this.sort); this.render(); });
        return th;
      }));
      const body = el('tbody');
      for (const it of this.sorted()) {
        const d = new Date(it.mtime * 1000);
        const tr = el('tr', { 'data-name': it.name, class: this.sel && this.sel.name === it.name ? 'is-sel' : '', draggable: 'true' },
          el('td', { title: it.dir ? it.name : `${it.name} (${U().fmtBytes(it.size)})` }, el('span', { class: 'pl-name' }, fileIcon(it.kind), el('span', null, it.name))),
          el('td', { class: 'pl-mono', style: { color: 'var(--pl-muted)' }, title: `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` }, shortDate(d)));
        tr.addEventListener('click', () => this.select(it));
        tr.addEventListener('dblclick', () => this.open(it));
        tr.addEventListener('dragstart', (ev) => ev.dataTransfer.setData('text/plain', it.kind === 'mfile' ? it.name.replace(/\.m$/, '') : `'${it.name}'`));
        tr.addEventListener('contextmenu', (ev) => {
          ev.preventDefault();
          this.select(it);
          const p = U().joinPath(this.path, it.name);
          U().menu(ev.clientX, ev.clientY, [
            { label: it.dir ? 'Open folder' : 'Open', action: () => this.open(it) },
            it.kind === 'mfile' ? { label: 'Run', kbd: 'F5', action: () => this.app.runFile(p) } : null,
            it.kind === 'mat' && U().mstr(p) ? { label: 'Load into the workspace', action: () => this.app.runCommand(`load(${U().mstr(p)})`) } : null,
            it.dir && U().mstr(p) ? { label: 'Add to path', action: () => this.app.runCommand(`addpath(${U().mstr(p)})`) } : null,
            '-',
            !it.dir ? { label: 'Download', action: () => this.app.downloadFile(p) } : null,
            { label: 'Rename…', action: () => this.rename(it) },
            { label: 'Duplicate', disabled: it.dir, action: () => this.app.duplicateFile(p) },
            { label: 'Delete', kbd: 'Del', action: () => this.remove(it) },
            '-',
            { label: 'New script', action: () => this.app.newFile('script', this.path) },
            { label: 'New function', action: () => this.app.newFile('function', this.path) },
            { label: 'New folder…', action: () => this.app.newFolder(this.path) },
            { label: 'Upload files…', action: () => this.app.pickUpload(this.path) },
            { label: 'Refresh', action: () => this.refresh() },
          ]);
        });
        body.append(tr);
      }
      this.table.replaceChildren(el('thead', null, head), body);
      if (error) this.table.append(el('caption', { class: 'pl-empty', style: { captionSide: 'bottom' } }, error));
      else if (!this.items.length) this.table.append(el('caption', { class: 'pl-empty', style: { captionSide: 'bottom', textAlign: 'left' } }, 'This folder is empty. Drop files here to upload them.'));
    }

    select(it) {
      this.sel = it;
      for (const tr of this.table.querySelectorAll('tr[data-name]')) tr.classList.toggle('is-sel', tr.dataset.name === it.name);
      this.emit('select', it.dir ? null : U().joinPath(this.path, it.name), it);
    }

    open(it) {
      const p = U().joinPath(this.path, it.name);
      if (it.dir) this.app.cd(p);
      else if (it.kind === 'mat') { if (U().mstr(p)) this.app.runCommand(`load(${U().mstr(p)})`); }
      else if (it.kind === 'fig') { if (U().mstr(p)) this.app.runCommand(`openfig(${U().mstr(p)})`); }
      else if (it.kind === 'image') this.app.previewImage(p);
      else this.app.openFile(p);
    }

    async rename(it) {
      const name = await U().prompt('Rename', 'New name', it.name);
      if (!name || name === it.name) return;
      if (/[\/\\]/.test(name)) { U().toast('A name cannot hold a slash.'); return; }
      const from = U().joinPath(this.path, it.name), to = U().joinPath(this.path, name);
      try {
        await PL.engine.fs('rename', { from, to });
        this.app.fileRenamed(from, to);
      } catch (e) { U().toast(`Could not rename: ${e.message}`); }
      this.refresh();
    }

    async remove(it) {
      const p = U().joinPath(this.path, it.name);
      if (!(await U().confirm('Delete', `Delete ${it.dir ? 'the folder' : ''} ${it.name}${it.dir ? ' and everything in it' : ''}? This cannot be undone.`, 'Delete'))) return;
      try { await PL.engine.fs('remove', { path: p }); } catch (e) { U().toast(`Could not delete: ${e.message}`); }
      this.app.fileRemoved(p);
      this.refresh();
    }
  }

  class DetailsPanel {
    constructor() {
      this.el = el('div', { class: 'pl-details' }, el('span', { class: 'pl-muted' }, 'Select a file to see its details.'));
    }

    async show(path) {
      if (!path) { this.el.replaceChildren(el('span', { class: 'pl-muted' }, 'Select a file to see its details.')); return; }
      const name = U().basename(path);
      if (!/\.(m|mat)$/i.test(name)) { this.el.replaceChildren(el('h4', null, name), el('span', { class: 'pl-muted' }, 'No preview for this kind of file.')); return; }
      let info;
      try { info = await PL.engine.call('file_info', path); } catch (e) { return; }
      const parts = [el('h4', null, name)];
      if (info.error) parts.push(el('span', { class: 'pl-muted' }, info.error));
      else if (info.vars) {
        const t = el('table', { class: 'pl-table' }, el('thead', null, el('tr', null, el('th', null, 'Name'), el('th', null, 'Size'), el('th', null, 'Class'))));
        const b = el('tbody');
        for (const v of info.vars) b.append(el('tr', null, el('td', null, v.name), el('td', { class: 'pl-mono' }, v.size), el('td', null, v.class)));
        t.append(b);
        parts.push(t);
      } else {
        parts.push(el('span', { class: 'pl-muted' }, info.kind === 'function' ? 'Function' : 'Script'));
        parts.push(el('pre', null, info.help || '(no help comment)'));
      }
      this.el.replaceChildren(...parts);
    }
  }

  /* ---- a variable as a grid ------------------------------------------------------- */
  class VariableView {
    constructor(app, name) {
      this.app = app;
      this.name = name;
      this.el = el('div', { class: 'pl-vargrid', tabindex: '0' });
      this.refresh();
    }

    async refresh() {
      let v;
      try { v = await PL.engine.call('var_view', this.name, 0, 0, 500, 100); } catch (e) { return; }
      this.data = v;
      if (v.error) { this.el.replaceChildren(el('div', { class: 'pl-varhead' }, `${this.name}: ${v.error}`)); return; }
      const head = el('div', { class: 'pl-varhead' }, `${v.name}  ·  ${v.size} ${v.class}`);
      if (v.kind === 'struct' || v.kind === 'object') {
        const t = el('table', null, el('thead', null, el('tr', null, el('th', null, 'Field'), el('th', null, 'Value'), el('th', null, 'Size'), el('th', null, 'Class'))));
        const b = el('tbody');
        for (const f of v.fields) {
          const name = el('td', { class: `txt${f.open ? ' open' : ''}` }, f.name);
          // a field opens by its name, or quoted (s.('…')) when that is no name: a field's name never becomes code
          const q = U().isName(f.name) ? f.name : U().mstr(f.name) && `(${U().mstr(f.name)})`;
          if (f.open && q) name.addEventListener('click', () => this.app.openVariable(`${this.name}.${q}`));
          b.append(el('tr', null, name, el('td', { class: 'txt' }, f.value), el('td', { class: 'txt' }, f.size || ''), el('td', { class: 'txt' }, f.class || '')));
        }
        t.append(b);
        this.el.replaceChildren(head, t);
        return;
      }
      if (v.kind === 'nd') { this.el.replaceChildren(head, el('div', { class: 'pl-varhead' }, v.note)); return; }
      if (v.kind === 'structarray') {
        const t = el('table', null, el('thead', null, el('tr', null, el('th', { class: 'rh' }, ''), v.fields.map((f) => el('th', null, f)))));
        const b = el('tbody');
        v.cells.forEach((row, i) => b.append(el('tr', null, el('td', { class: 'rh' }, String(i + 1)), row.map((c) => el('td', { class: 'txt' }, c)))));
        t.append(b);
        this.el.replaceChildren(head, t);
        return;
      }
      const cols = v.cells.length ? v.cells[0].length : 0;
      const t = el('table');
      t.append(el('thead', null, el('tr', null, el('th', { class: 'rh' }, ''), Array.from({ length: cols }, (_, j) => el('th', null, String(v.c0 + j + 1))))));
      const b = el('tbody');
      const isText = v.class === 'cell' || v.class === 'string' || v.class === 'char';
      v.cells.forEach((row, i) => {
        const tr = el('tr', null, el('td', { class: 'rh' }, String(v.r0 + i + 1)));
        row.forEach((c, j) => {
          const td = el('td', { class: isText ? 'txt' : '' }, c);
          if (v.editable) td.addEventListener('dblclick', () => this.edit(td, v.r0 + i + 1, v.c0 + j + 1, c));
          if (v.class === 'cell') td.addEventListener('dblclick', () => this.app.openVariable(`${this.name}{${v.r0 + i + 1},${v.c0 + j + 1}}`));
          tr.append(td);
        });
        b.append(tr);
      });
      t.append(b);
      const more = v.shape && (v.shape[0] > v.r0 + v.cells.length || v.shape[1] > v.c0 + cols) ? el('div', { class: 'pl-varhead' }, 'The first 500 rows and 100 columns are shown.') : null;
      this.el.replaceChildren(...[head, t, more].filter(Boolean));
    }

    edit(td, i, j, old) {
      const input = el('input', { type: 'text', value: old, spellcheck: 'false' });
      td.replaceChildren(input);
      input.focus();
      input.select();
      const done = async (save) => {
        if (save && input.value.trim() && input.value !== old) {
          await this.app.runCommand(`${this.name}(${i},${j}) = ${input.value};`, { silent: true, noHistory: true });
          this.refresh();
        } else td.textContent = old;
      };
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); done(true); }
        if (ev.key === 'Escape') { ev.preventDefault(); done(false); }
      });
      input.addEventListener('blur', () => done(true), { once: true });
    }
  }

  PL.History = History;
  PL.HistoryPanel = HistoryPanel;
  PL.WorkspacePanel = WorkspacePanel;
  PL.FolderPanel = FolderPanel;
  PL.DetailsPanel = DetailsPanel;
  PL.VariableView = VariableView;
})(window);
