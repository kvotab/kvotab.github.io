/* ==========================================================================
   SMUI.HTML: OPENING HDF5 FILES

   An HDF5 file (.h5, .hdf5, netCDF-4 .nc, MATLAB v7.3 .mat, …) is told by
   its first bytes, whatever its name. The HDF5 worker (smui-hdf5-worker.js)
   lists it; the Open HDF5 dialog shows its groups and datasets, each with
   what it would become, ticked as smui-hdf5-read.js's defaults() suggests;
   Open makes tables of what is ticked. A file that is one table and
   nothing else opens without asking.

     SM.hdf5.open(app, file, { state, ask })   the tables it added
       state: 'defaults', 'all' or { picked, transposed: [paths], together }
              opens those without the dialog (scripts and the tests)
       ask:   the dialog even for a file that is one table
     SM.hdf5.sniff(file)    'hdf5', 'netcdf3', 'mat5', 'hdf4' or null

   Every name and attribute shown comes from the file and is untrusted: the
   dialog puts them in as text only.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, svg } = SM.util;

  const EXT = /\.(h5|hdf5|he5|hdf|h5ad|hd5|nc|nc4|cdf|mat)$/i;
  const NOT_HDF5 = {
    netcdf3: 'a netCDF-3 (classic) file, which is not HDF5: save it as netCDF-4, or as CSV',
    mat5: 'a MATLAB 5 .mat file, which is not HDF5: save it with save(..., \'-v7.3\') or as CSV',
    hdf4: 'an HDF4 file, which is not HDF5: convert it (h4toh5) or save it as CSV',
  };
  const MAX_ROWS = 3000;     // tree lines drawn at once
  const fmtN = (n) => Number(n).toLocaleString('en-US');

  /* ---- the worker ----------------------------------------------------------- */
  let worker = null;
  let seq = 0;
  const pending = new Map();

  function getWorker() {
    if (worker) return worker;
    const v = document.documentElement.dataset.build || '';
    worker = new Worker(`./resources/js/smui-hdf5-worker.js?v=${encodeURIComponent(v)}`);
    worker.onmessage = (ev) => {
      const m = ev.data || {};
      const p = pending.get(m.id);
      if (!p) return;
      if (m.progress) { if (p.progress) p.progress(m.progress); return; }
      pending.delete(m.id);
      if ('err' in m) p.reject(new Error(m.err)); else p.resolve(m.ok);
    };
    worker.onerror = (ev) => { ev.preventDefault(); stop(new Error(ev.message || 'the HDF5 reader stopped')); };
    return worker;
  }

  /* Ends the worker (a Cancel, or a failure): what it was doing fails. */
  function stop(err) {
    const list = [...pending.values()];
    pending.clear();
    if (worker) worker.terminate();
    worker = null;
    for (const p of list) p.reject(err);
  }

  function call(cmd, args, progress = null) {
    return new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject, progress });
      getWorker().postMessage({ id, cmd, ...args });
    });
  }

  async function sniff(file) {
    return SM.h5.sniff(new Uint8Array(await file.slice(0, 65544).arrayBuffer()));
  }

  /* ---- opening ------------------------------------------------------------------ */
  async function open(app, file, opts = {}) {
    const kind = await sniff(file);
    if (kind !== 'hdf5') throw new Error(NOT_HDF5[kind] || 'not an HDF5 file: it does not start with the HDF5 signature');
    const ui = busy(file.name);
    let fid = null;
    try {
      const r = await call('open', { file }, ui.progress);
      fid = r.fid;
      ui.pause();
      let state = givenState(r.nodes, r.defaults, opts.state);
      if (!state) {
        if (r.defaults.direct && !opts.ask) state = fromDefaults(r.defaults);
        else {
          state = await chooser(file, r);
          if (!state) return [];
        }
      }
      const planned = SM.h5.plan(r.nodes, state, { fileName: file.name });
      if (planned.blocked) throw new Error(planned.blocked);
      if (!planned.tables.length) throw new Error('nothing in it to open as a table');
      ui.resume(`Reading ${file.name}…`);
      const res = await call('read', { fid, plan: planned, fileName: file.name }, ui.progress);
      const tables = res.tables.map((t) => tableOf(app, t));
      tables.forEach((t, i) => app.addTable(t, { show: i === 0 }));
      if (res.failed.length) SM.ui.toast(`${file.name}: ${res.failed.map((f) => `${f.name} could not be read (${f.why})`).join('; ')}`, { error: true });
      else if (tables.length === 1) SM.ui.toast(`Opened ${file.name}: ${fmtN(tables[0].nrows)} rows × ${fmtN(tables[0].columns.length)} columns`);
      else if (tables.length) SM.ui.toast(`Opened ${file.name}: ${tables.length} tables`);
      return tables;
    } catch (e) {
      if (e && e.cancelled) { SM.ui.toast(`${file.name}: cancelled`); return []; }
      throw e;
    } finally {
      ui.close();
      if (fid != null && worker) call('close', { fid }).catch(() => { /* the worker is gone: nothing to close */ });
    }
  }

  const fromDefaults = (d) => ({ picked: new Set(d.picked), transposed: new Set(d.transposed), together: d.together !== false });

  /* A state given by name or by paths (no dialog), or null. */
  function givenState(nodes, d, given) {
    if (!given) return null;
    if (given === 'defaults') return fromDefaults(d);
    const byPath = new Map(nodes.map((n) => [n.path, n.id]));
    const ids = (list) => new Set((list || []).map((p) => byPath.get(p)).filter((id) => id != null));
    if (given === 'all') return { picked: new Set(nodes.filter(tickable).map((n) => n.id)), transposed: new Set(d.transposed), together: true };
    return { picked: ids(given.picked), transposed: given.transposed ? ids(given.transposed) : new Set(d.transposed), together: given.together !== false };
  }

  /* A table from the worker's: plain arrays, as SM.Table keeps them. */
  function tableOf(app, t) {
    const columns = t.columns.map((c) => ({
      name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format || null, valueOrder: c.valueOrder || null,
      valueLabels: c.valueLabels || null, notes: c.notes || '',
      values: c.dataType === 'numeric' ? Array.from(c.values) : Array.from(c.values, (v) => (v == null ? null : String(v))),
    }));
    return new SM.Table({ name: app.uniqueTableName(t.name), source: t.source, notes: t.notes, columns });
  }

  /* What is happening, in a small dialog with Cancel when it takes a while
     (none for a quick file). */
  function busy(name) {
    let dlg = null, timer = null, done = false;
    const text = el('p', { class: 'sm-h5-busytext', text: `Opening ${name}…` });
    const bar = el('progress', { class: 'sm-h5-busybar', max: 1 });
    const show = () => {
      if (dlg || done) return;
      dlg = SM.ui.dialog({ title: `Opening ${name}`, narrow: true, body: el('div', { class: 'sm-h5-busy' }, text, bar),
        buttons: [{ label: 'Cancel', result: 'cancel' }],
        onClose: (r) => { dlg = null; if (!done && (r === 'cancel' || r === null)) stop(Object.assign(new Error('cancelled'), { cancelled: true })); } });
    };
    const arm = () => { clearTimeout(timer); timer = setTimeout(show, 400); };
    arm();
    return {
      progress(p) {
        text.textContent = p.text || text.textContent;
        if (p.total) { bar.max = p.total; bar.value = p.done; } else bar.removeAttribute('value');
      },
      pause() { clearTimeout(timer); if (dlg) { const d = dlg; dlg = null; d.close('done'); } },
      resume(t) { text.textContent = t; bar.removeAttribute('value'); arm(); },
      close() { done = true; clearTimeout(timer); if (dlg) dlg.close('done'); },
    };
  }

  /* ---- the Open HDF5 dialog ------------------------------------------------- */
  const tickable = (n) => !!(n.readable && !n.hidden && n.form);

  function chooser(file, r) {
    const nodes = r.nodes;
    const picked = new Set(r.defaults.picked);
    const transposed = new Set(r.defaults.transposed);
    const state = { picked, transposed, together: r.defaults.together !== false };
    const expanded = new Set();
    // the ids each group can tick: its descendants that make columns
    const under = new Map();
    const collect = (n) => {
      if (n.hidden && n.id !== 0) return [];
      const own = [];
      for (const c of n.children || []) {
        const k = nodes[c];
        if (tickable(k)) own.push(k.id);
        if (k.kind === 'group' && !k.form) own.push(...collect(k));
      }
      under.set(n.id, own);
      return own;
    };
    collect(nodes[0]);
    const all = under.get(0) || [];
    // open at the start: the top level, and every group when the file is small
    const groups = nodes.filter((n) => n.kind === 'group' && !n.hidden && !n.form);
    for (const g of groups) if (g.id === 0 || nodes.length <= 60 || g.depth <= 1) expanded.add(g.id);

    const find = el('input', { type: 'search', class: 'sm-h5-find', placeholder: 'Find by name', 'aria-label': 'Find a dataset or group by name', autocomplete: 'off', spellcheck: 'false' });
    const tickShown = el('button', { type: 'button', class: 'sm-btn small', text: 'Tick all' });
    const untick = el('button', { type: 'button', class: 'sm-btn small', text: 'Untick all' });
    const tree = el('div', { class: 'sm-h5-tree', role: 'tree', 'aria-label': `The groups and datasets of ${file.name}`, 'aria-multiselectable': 'true' });
    const summary = el('div', { class: 'sm-h5-summary', 'aria-live': 'polite' });
    const together = el('input', { type: 'checkbox', id: SM.util.uid('h5t') });
    together.checked = state.together;
    const counts = r.info || {};
    const lead = el('p', { class: 'sm-dialog-lead' },
      'Tick what to open. Vectors and matrices with the same number of rows open side by side, as the columns of one table; ⇄ swaps a matrix\'s rows and columns.',
      picked.size ? null : ` The file holds ${fmtN(all.length)} datasets that can be tables: tick the ones you want (Find narrows the list).`,
      counts.capped ? ` Only its first ${fmtN(counts.listed)} of ${fmtN(counts.objects)} objects are listed.` : null);
    const body = el('div', { class: 'sm-h5' }, lead,
      el('div', { class: 'sm-h5-bar' }, find, tickShown, untick), tree,
      el('label', { class: 'sm-h5-together', for: together.id }, together, 'Side by side: vectors and matrices with the same number of rows open as one table'),
      summary);

    const rows = new Map();     // id -> its line in the tree
    let query = '';
    const matches = (n) => !!query && n.name.toLowerCase().includes(query.toLowerCase());

    /* The lines in view: open groups' children, or, with a search, what
       matches and the groups above it. */
    function shown() {
      const out = [];
      if (query) {
        const q = query.toLowerCase();
        const hits = new Set();
        for (const n of nodes) {
          if (n.id === 0 || n.hidden || !n.name.toLowerCase().includes(q)) continue;
          for (let p = n.id; p > 0; p = nodes[p].parent) hits.add(p);
          if (hits.size > MAX_ROWS * 2) break;
        }
        const walk = (n) => { for (const c of n.children || []) { const k = nodes[c]; if (!hits.has(k.id)) continue; out.push(k); if (out.length >= MAX_ROWS) return; if (k.kind === 'group' && !k.form) walk(k); } };
        walk(nodes[0]);
        return out;
      }
      const walk = (n) => {
        for (const c of n.children || []) {
          const k = nodes[c];
          if (k.hidden) continue;
          out.push(k);
          if (out.length >= MAX_ROWS) return;
          if (k.kind === 'group' && !k.form && expanded.has(k.id)) walk(k);
        }
      };
      walk(nodes[0]);
      return out;
    }

    function line(n) {
      const isGroup = n.kind === 'group' && !n.form;
      const kids = isGroup ? (n.children || []).filter((c) => !nodes[c].hidden).length : 0;
      const row = el('div', { class: `sm-h5-row${tickable(n) || (isGroup && (under.get(n.id) || []).length) ? '' : ' is-off'}${n.meta ? ' is-meta' : ''}`, role: 'treeitem', 'aria-level': String(n.depth), dataset: { id: String(n.id) }, style: { '--d': String(n.depth - 1) } });
      if (isGroup && kids) {
        const open = query ? true : expanded.has(n.id);
        row.setAttribute('aria-expanded', String(open));
        const tog = el('button', { type: 'button', class: 'sm-h5-tog', 'aria-label': `${open ? 'Close' : 'Open'} ${n.name}`, 'aria-expanded': String(open) }, chevron(open));
        tog.disabled = !!query;
        tog.addEventListener('click', () => { if (expanded.has(n.id)) expanded.delete(n.id); else expanded.add(n.id); render(); rows.get(n.id)?.querySelector('.sm-h5-tog')?.focus(); });
        row.append(tog);
      } else row.append(el('span', { class: 'sm-h5-tog', 'aria-hidden': 'true' }));
      const can = isGroup ? (under.get(n.id) || []).length > 0 : tickable(n);
      const box = el('input', { type: 'checkbox', 'aria-label': n.name });
      box.disabled = !can;
      box.addEventListener('change', () => {
        const ids = isGroup ? under.get(n.id) || [] : [n.id];
        for (const id of ids) { if (box.checked) picked.add(id); else picked.delete(id); }
        refresh();
      });
      row.append(box, icon(n), el('span', { class: 'sm-h5-name', text: n.name, title: n.path }), el('span', { class: 'sm-h5-desc', text: describe(n) }));
      if (n.form === 'matrix') {
        const flip = el('button', { type: 'button', class: 'sm-h5-flip', 'aria-label': `Swap the rows and columns of ${n.name}`, text: '⇄' });
        flip.addEventListener('click', () => {
          if (transposed.has(n.id)) transposed.delete(n.id); else transposed.add(n.id);
          row.querySelector('.sm-h5-desc').textContent = describe(n);
          flip.setAttribute('aria-pressed', String(transposed.has(n.id)));
          refresh();
        });
        flip.setAttribute('aria-pressed', String(transposed.has(n.id)));
        row.append(flip);
      }
      return row;
    }

    function describe(n) {
      if (n.kind === 'link') return `link to ${n.target}`;
      if (n.kind === 'external') return `link to another file${n.target ? `: ${n.target}` : ''}`;
      if (n.kind === 'broken') return `link to ${n.target || '?'}, which is not there`;
      if (n.kind === 'datatype') return 'a named datatype';
      if (n.form === 'pandas') return n.readable ? `pandas ${/^series/.test(n.pandas.type) ? 'Series' : 'DataFrame'} · ${fmtN(n.rows)} rows × ${fmtN(n.cols)} columns` : n.why;
      if (n.kind === 'group') { const k = (n.children || []).filter((c) => !nodes[c].hidden).length; return k === 1 ? '1 item' : `${fmtN(k)} items`; }
      if (!n.readable) return n.why || 'not read';
      const unit = n.attrs && (n.attrs.unit || n.attrs.units || n.attrs.Unit || n.attrs.Units);
      const bits = [];
      if (n.form === 'vector') bits.push(`${fmtN(n.rows)} values`, n.typeText);
      else if (n.form === 'scalar') bits.push('a single value', n.typeText);
      else if (n.form === 'compound') bits.push(`${fmtN(n.rows)} rows`, n.typeText);
      else if (n.form === 'matrix') {
        const t = transposed.has(n.id);
        bits.push(`${n.dims.map(fmtN).join(' × ')} ${n.typeText}`, `${fmtN(t ? n.cols : n.rows)} rows × ${fmtN(t ? n.rows : n.cols)} columns${t ? ' (swapped)' : ''}`);
      } else if (n.form === 'cube') bits.push(`${n.dims.map(fmtN).join(' × ')} ${n.typeText}`, `stacked: ${fmtN(n.rows)} rows`);
      // (a CF time unit, "hours since 2000-01-01", makes dates)
      if (typeof unit === 'string' && unit.trim()) bits.push(/\ssince\s/.test(unit) ? `dates (${unit.trim().slice(0, 60)})` : unit.trim().slice(0, 40));
      if (n.key) bits.push('row key');
      if (n.meta) bits.push('an index list');
      return bits.join(' · ');
    }

    function render() {
      const list = shown();
      rows.clear();
      const frag = document.createDocumentFragment();
      for (const n of list) { const l = line(n); rows.set(n.id, l); frag.append(l); }
      if (!list.length) frag.append(el('p', { class: 'sm-h5-empty', text: query ? `Nothing named like “${query}”.` : 'The file holds no groups or datasets.' }));
      if (list.length >= MAX_ROWS) frag.append(el('p', { class: 'sm-h5-empty', text: `The first ${fmtN(MAX_ROWS)} lines; Find narrows the list.` }));
      tree.replaceChildren(frag);
      tickShown.textContent = query ? 'Tick shown' : 'Tick all';
      refresh();
    }

    function plan() { return SM.h5.plan(nodes, state, { fileName: file.name }); }

    /* The boxes after a tick, and what Open would make. */
    function refresh() {
      for (const [id, row] of rows) {
        const box = row.querySelector('input[type="checkbox"]');
        if (!box || box.disabled) continue;
        const n = nodes[id];
        if (n.kind === 'group' && !n.form) {
          const ids = under.get(id) || [];
          let k = 0;
          for (const x of ids) if (picked.has(x)) k++;
          box.checked = k > 0 && k === ids.length;
          box.indeterminate = k > 0 && k < ids.length;
        } else box.checked = picked.has(id);
      }
      const p = plan();
      const lines = [];
      if (!p.tables.length) lines.push(el('p', { class: 'sm-h5-none', text: 'Nothing is ticked.' }));
      else {
        lines.push(el('p', { class: 'sm-h5-opens', text: p.tables.length === 1 ? 'Opens one table:' : `Opens ${p.tables.length} tables:` }));
        // (a table named by its length says only its width)
        const count = (n, w) => `${fmtN(n)} ${w}${n === 1 ? '' : 's'}`;
        const size = (t) => (t.name.endsWith(` ${t.rows} rows`) ? count(t.cols, 'column') : `${count(t.rows, 'row')} × ${count(t.cols, 'column')}`);
        lines.push(el('ul', { class: 'sm-h5-tables' }, ...p.tables.slice(0, 30).map((t) => el('li', null, el('strong', { text: t.name }), ` — ${size(t)}${t.kind === 'stacked' ? ' (stacked)' : ''}`)),
          p.tables.length > 30 ? el('li', { text: `and ${p.tables.length - 30} more` }) : null));
      }
      for (const w of p.warnings) lines.push(el('p', { class: 'sm-h5-warn', text: w }));
      if (p.blocked) lines.push(el('p', { class: 'sm-h5-warn', text: p.blocked }));
      summary.replaceChildren(...lines);
      const ok = dlg && dlg.el.querySelector('.sm-dialog-foot .primary');
      if (ok) ok.disabled = !p.tables.length || !!p.blocked;
    }

    let timer = null;
    find.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { query = find.value.trim(); render(); }, 150); });
    // Escape in Find clears it before it closes the dialog; Enter finds (the
    // list follows the typing) rather than opening
    find.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && find.value) { ev.preventDefault(); find.value = ''; query = ''; render(); }
      if (ev.key === 'Enter') ev.preventDefault();
    });
    // with a Find, what matches: a dataset, or everything in a group whose
    // name matches (not the groups shown only because a match is in them)
    tickShown.addEventListener('click', () => {
      const ids = query ? [...rows.keys()].filter((id) => matches(nodes[id])).flatMap((id) => (nodes[id].kind === 'group' && !nodes[id].form ? under.get(id) || [] : tickable(nodes[id]) ? [id] : [])) : all;
      for (const id of ids) picked.add(id);
      refresh();
    });
    untick.addEventListener('click', () => { picked.clear(); refresh(); });
    together.addEventListener('change', () => { state.together = together.checked; refresh(); });

    let dlg = null;
    return new Promise((resolve) => {
      dlg = SM.ui.dialog({
        title: `Open HDF5: ${file.name}`, body, info: 'file:hdf5', className: 'sm-h5-dialog',
        buttons: [
          { label: 'Cancel', result: null },
          { label: 'Open', primary: true, action: () => { const p = plan(); if (!p.tables.length || p.blocked) return false; resolve(state); return true; } },
        ],
        onClose: (res) => { if (res === null) resolve(null); },
      });
      render();
    });
  }

  function chevron(open) {
    return svg('svg', { viewBox: '0 0 10 10', width: 10, height: 10, 'aria-hidden': 'true' },
      svg('path', { d: open ? 'M1.5 3 L5 6.5 L8.5 3' : 'M3 1.5 L6.5 5 L3 8.5', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
  }

  /* A folder for a group, a small grid for a dataset, a chain for a link:
     drawn, so they take the theme's colours. */
  function icon(n) {
    const s = svg('svg', { viewBox: '0 0 14 12', width: 14, height: 12, class: 'sm-h5-ico', 'aria-hidden': 'true' });
    if (n.kind === 'group' && !n.form) {
      s.classList.add('is-group');
      s.append(svg('path', { d: 'M1 2.5 Q1 1.5 2 1.5 H5 L6.3 3 H12 Q13 3 13 4 V9.5 Q13 10.5 12 10.5 H2 Q1 10.5 1 9.5 Z', fill: 'currentColor' }));
    } else if (n.kind === 'link' || n.kind === 'external' || n.kind === 'broken') {
      s.append(svg('path', { d: 'M5.5 7.5 L8.5 4.5 M6 3.5 L7.3 2.2 Q9 0.5 10.7 2.2 Q12.4 3.9 10.7 5.6 L9.4 6.9 M8 8.5 L6.7 9.8 Q5 11.5 3.3 9.8 Q1.6 8.1 3.3 6.4 L4.6 5.1', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.3, 'stroke-linecap': 'round' }));
    } else {
      s.classList.add(n.form === 'pandas' ? 'is-pandas' : 'is-data');
      s.append(svg('rect', { x: 1.5, y: 1.5, width: 11, height: 9, rx: 1, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.2 }),
        svg('path', { d: 'M1.5 4.5 H12.5 M1.5 7.5 H12.5 M5.2 1.5 V10.5 M8.8 1.5 V10.5', stroke: 'currentColor', 'stroke-width': 0.9 }));
    }
    return s;
  }

  SM.hdf5 = Object.freeze({ open, sniff, isHdf5Name: (name) => EXT.test(name || ''), NOT_HDF5, stop: () => stop(Object.assign(new Error('cancelled'), { cancelled: true })) });
}(typeof self !== 'undefined' ? self : this));
