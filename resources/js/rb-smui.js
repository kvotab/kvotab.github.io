/* ==========================================================================
   17. THE TREE'S MENU: THE SELECTION TO STATISTICS, OR TO A FILE

   Right-click a row of the tree for what can be done with the selection:
   send it to the User Interface for statsmodels (smui.html) for analysis,
   or save it as an HDF5 file. A row outside the selection is selected
   first, as a click would select it.

   Both package the selection as one HDF5 file, written with h5wasm:
     * each selected dataset at its own path, a group's datasets beneath
       it, with their attributes and those of the groups above them; under
       a group per file when the selection spans files
     * the file's /time, made the dimension scale of every series of the
       selection (one /time when the files share their times), which is
       what makes it a series' first column in smui
     * values drawn from each distribution of the selection (a pdf
       attribute) under /samples, by the dataset's name (as much of its
       path as tells two apart, and its file when two files give the same:
       kd (run 2)): n values for a parameter, n rows with a column per
       point for a lookup table. 1000, the number the histogram draws, are
       the values the histogram shows when it shows them; any other number
       is drawn anew. A distribution of type raw is its dataset's values,
       which go as they are.
     * a lookup table (a pdf per point, and an index) says lookup_table,
       which makes its index the times beside it in smui
   The file is named after the row right-clicked (run kd.h5), or is the
   selection (run selection.h5); smui names its tables after it.
   smui opens it as it opens any HDF5 file (smui-hdf5-read.js): the series
   with their times, a probabilistic run's realisations a row each, the
   samples side by side in one table.

   Sending is rb-handoff.js's handoff the other way round. smui.html is
   opened with #handoff=<this origin>, says 'smui-ready' when it is
   listening, and the file goes across as a transferred ArrayBuffer. The
   tab is opened in the click (a pop-up needs the gesture) under a name,
   so the next send goes to the same tab while it is open, and the tables
   of two sends meet there. In VS Code there is no smui to send to: the
   menu saves.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/** The workbench, beside this page on the site. */
const RB_SMUI_PAGE = 'smui.html';
/** The tab's name: a second send finds the first one's tab by it. */
const RB_SMUI_WINDOW = 'kvot-smui';
/** How long the tab may take to say it is listening (smui opens a file without its Python engine). */
const RB_SMUI_READY_MS = 45000;
/** Values drawn from a distribution: as many as the histogram draws, and the most offered. */
const RB_SAMPLE_DEFAULT = 1000;
const RB_SAMPLE_MAX = 1000000;
/** One package holds at most this many datasets, and this many values in all. */
const RB_PACKAGE_MAX_DATASETS = 50000;
const RB_PACKAGE_MAX_VALUES = 250e6;
/** Attributes that are a dimension scale's own bookkeeping: the package makes its own. */
const RB_PACKAGE_SKIP_ATTRS = new Set(['DIMENSION_LIST', 'REFERENCE_LIST', 'CLASS', 'NAME', '_Netcdf4Dimid', '_Netcdf4Coordinates']);

/** Whether the page runs in the VS Code extension, where there is no smui.html to send to. */
function rbInVsCode() {
  return typeof window.KvotVscodeHost !== 'undefined';
}

/* ── what is selected ───────────────────────────────────────────────────── */

/**
 * The selection as a 'selection:changed' payload, or null when there is
 * none. A group is told by what its path is: rb keeps its group flag
 * (selectedIsRadionuclidesGroup) only for a group that draws a chart.
 */
function rbSelectionPayload() {
  if (multiSelectMode && selectedDatasets.length) return { mode: 'multi', items: selectedDatasets.slice() };
  if (selectedGroups.length > 1) return { mode: 'groups', items: selectedGroups.slice() };
  if (!selectedDatasetPath) return null;
  const files = getEffectiveFiles();
  const node = files.length ? FileService.get(loadedFiles[files[0]], selectedDatasetPath) : null;
  const isGroup = node ? node.type === 'Group' : (selectedIsRadionuclidesGroup || !selectedDatasets.length);
  return { mode: isGroup ? 'group' : 'single', path: selectedDatasetPath };
}

/** Whether a tree row is part of the selection. */
function rbRowIsSelected(row) {
  const path = row.getAttribute('data-path');
  const fileKey = row.getAttribute('data-file') || null;
  if (row.classList.contains('group')) {
    if (selectedGroups.length > 1) return selectedGroups.some(g => g.path === path && (g.fileKey || null) === fileKey);
    // (a group click leaves no dataset selected)
    return !multiSelectMode && !selectedDatasets.length && selectedDatasetPath === path && (selectedFileKey || null) === fileKey;
  }
  return selectedDatasets.some(d => d.path === path && (d.fileKey || null) === fileKey);
}

/** Select a row as a plain click selects it. */
function rbSelectRow(row) {
  const click = { target: row, currentTarget: row, ctrlKey: false, metaKey: false, stopPropagation() {} };
  if (row.classList.contains('group')) toggleGroup(click, row);
  else selectDataset(row.getAttribute('data-path'), click);
}

/** What the menu's first line says: the selection in a few words. */
function rbSelectionLabel(payload) {
  const last = (p) => (p === '/' ? 'the whole file' : String(p).split('/').pop());
  if (payload.mode === 'multi') return `${payload.items.length} datasets`;
  if (payload.mode === 'groups') return `${payload.items.length} groups`;
  if (payload.mode === 'group') return payload.path === '/' ? 'the whole file' : `${last(payload.path)} (a group)`;
  return last(payload.path);
}

/* ── the menu ───────────────────────────────────────────────────────────── */

let _rbTreeMenu = null;

function closeTreeMenu(returnFocus = false) {
  const open = _rbTreeMenu;
  if (!open) return;
  _rbTreeMenu = null;
  open.cleanup();
  open.menu.remove();
  if (returnFocus && open.row && open.row.isConnected && typeof open.row.focus === 'function') open.row.focus();
}

/**
 * The menu at a point, for a selection: a line naming it, then what can
 * be done with it. Arrow keys move, Enter chooses, Escape closes.
 */
function openTreeMenu(payload, x, y, row) {
  closeTreeMenu();
  const menu = document.createElement('div');
  menu.className = 'rb-tree-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', `The selection: ${rbSelectionLabel(payload)}`);
  const head = document.createElement('div');
  head.className = 'rb-tree-menu-head';
  head.textContent = rbSelectionLabel(payload);
  menu.appendChild(head);
  const items = [];
  const item = (text, title, action) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'rb-tree-menu-item';
    b.setAttribute('role', 'menuitem');
    b.textContent = text;
    b.title = title;
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      closeTreeMenu();
      action();
    });
    menu.appendChild(b);
    items.push(b);
  };
  if (!rbInVsCode()) {
    item('Send to User Interface for statsmodels', 'Open the selection in smui.html as tables, for statistics',
      () => rbChooseSend(payload, 'smui'));
  }
  item('Save as HDF5…', 'Save the selection as an HDF5 file, with values drawn from its distributions',
    () => rbChooseSend(payload, 'save'));
  document.body.appendChild(menu);

  const r = menu.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - r.width - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - r.height - 4))}px`;

  const onKey = (e) => {
    const at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeTreeMenu(true); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      items[(at + step + items.length) % items.length].focus();
    } else if (e.key === 'Home' || e.key === 'End') { e.preventDefault(); items[e.key === 'Home' ? 0 : items.length - 1].focus(); }
    else if (e.key === 'Tab') closeTreeMenu();
  };
  const onDown = (e) => { if (!menu.contains(e.target)) closeTreeMenu(); };
  const onAway = () => closeTreeMenu();
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('pointerdown', onDown, true);
  window.addEventListener('resize', onAway);
  window.addEventListener('blur', onAway);
  const tree = document.getElementById('tree');
  if (tree) tree.addEventListener('scroll', onAway, { passive: true });
  _rbTreeMenu = {
    menu, row,
    cleanup() {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('resize', onAway);
      window.removeEventListener('blur', onAway);
      if (tree) tree.removeEventListener('scroll', onAway);
    },
  };
  items[0].focus();
}

(function installTreeContextMenu() {
  const tree = document.getElementById('tree');
  if (!tree) return;
  tree.addEventListener('contextmenu', (event) => {
    const row = event.target.closest('.tree-item');
    if (!row || !tree.contains(row) || !row.getAttribute('data-path')) return;
    if (!row.classList.contains('group') && !row.classList.contains('dataset')) return;
    event.preventDefault();
    if (!rbRowIsSelected(row)) rbSelectRow(row);
    const payload = rbSelectionPayload();
    if (!payload) return;
    let x = event.clientX, y = event.clientY;
    // (from the keyboard there is no pointer: under the row)
    if (!x && !y) { const r = row.getBoundingClientRect(); x = r.left + 24; y = r.bottom; }
    openTreeMenu(payload, x, y, row);
  });
})();

/* ── what a send holds ──────────────────────────────────────────────────── */

/**
 * The datasets of a selection, file by file, and what of them is not here
 * yet (a lazy file's groups). A group stands for every dataset beneath it.
 *
 * @returns {{items: Array, fetch: Array, draws: number, shown: number, values: number, skipped: string[], label: string}}
 */
function rbPlanPackage(payload) {
  const items = [];
  const seen = new Set();
  const fetch = [];
  const skipped = [];
  for (const { fileKey, path, isGroup } of rbSelectionTargets(payload)) {
    const file = loadedFiles[fileKey];
    if (!file || !path) continue;
    const lazy = lazyStateOf(file);
    let paths;
    if (lazy) {
      const prefix = path === '/' ? '/' : `${path}/`;
      paths = isGroup ? lazy.paths.filter(p => p.startsWith(prefix)) : [path];
      const missing = [...new Set(paths.map(rbLazyDirname))].filter(g => !lazy.groups.has(g) && !lazy.notGroups.has(g));
      if (missing.length) { fetch.push({ lazy, groups: missing }); continue; }
    } else {
      paths = isGroup ? rbDatasetsUnder(file, path) : [path];
    }
    for (const p of paths) {
      const key = `${fileKey}\u0000${p}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const node = FileService.get(file, p);
      if (!node || node.type !== 'Dataset') continue;
      items.push({ fileKey, path: p, node });
    }
  }
  let draws = 0, shown = 0, values = 0;
  for (const it of items) {
    const shape = Array.isArray(it.node.shape) ? it.node.shape.map(Number) : [];
    values += shape.reduce((a, d) => a * d, 1);
    const specs = rbPdfSpecs(it.node);
    if (!specs) continue;
    specs.list.forEach((spec, i) => {
      if (!spec || rbIsRaw(spec)) return;
      draws++;
      if (rbShownSamples(it.path, it.fileKey, specs.lookup ? i : null)) shown++;
    });
  }
  // what the package is called after: the dataset or group right-clicked
  const one = (payload.mode === 'single' || payload.mode === 'group') && payload.path !== '/';
  const label = one ? String(payload.path).split('/').pop().replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, ' ').trim().slice(0, 60) : '';
  return { items, fetch, draws, shown, values, skipped, label: label || 'selection' };
}

/** Every dataset beneath a group of a file in memory, in the file's order. */
function rbDatasetsUnder(file, path) {
  const out = [];
  const walk = (p, depth) => {
    if (depth > 64 || out.length > RB_PACKAGE_MAX_DATASETS) return;
    const node = FileService.get(file, p);
    if (!node) return;
    if (node.type === 'Dataset') { out.push(p); return; }
    if (node.type !== 'Group') return;
    let keys = [];
    try { keys = Array.from(node.keys()); } catch (_) { return; }
    for (const k of keys) walk(p === '/' ? `/${k}` : `${p}/${k}`, depth + 1);
  };
  walk(path, 0);
  return out;
}

/** A lazy file's groups a plan needs, fetched. */
async function rbFetchPlan(plan) {
  for (const { lazy, groups } of plan.fetch) {
    for (const g of groups) await lazy.ensureGroup(g);
  }
}

/** A dataset's distributions: { list, lookup }, a spec per point of a lookup table; null without one. */
function rbPdfSpecs(node) {
  let pdf = getAttr(node, 'pdf');
  if (pdf == null) return null;
  if (typeof pdf === 'string') {
    try { pdf = JSON.parse(pdf); } catch (_) { return { list: [], lookup: false, unread: true }; }
  }
  if (Array.isArray(pdf)) return { list: pdf.map(s => (s && typeof s === 'object' && s.type ? s : null)), lookup: true };
  if (pdf && typeof pdf === 'object' && pdf.type) return { list: [pdf], lookup: false };
  return { list: [], lookup: false, unread: true };
}

const rbIsRaw = (spec) => String(spec.type).toLowerCase() === 'raw';

/**
 * The values the histogram shows for a dataset's distribution (a lookup
 * table's point), when it shows them: the histogram draws 1000.
 */
function rbShownSamples(path, fileKey, point) {
  const data = currentPdfHistogram ? currentPdfHistogramData : null;
  if (!data) return null;
  const entries = data.type === 'single' ? [data] : (data.entries || []);
  const files = getEnabledFiles();
  for (const e of entries) {
    const s = e.source;
    if (!s || s.path !== path) continue;
    if ((s.point ?? null) !== point) continue;
    if ((s.fileKey || null) !== (fileKey || null) && !(files.length === 1 && (!s.fileKey || !fileKey))) continue;
    if (!e.spec || rbIsRaw(e.spec) || !e.samples || e.samples.length !== RB_SAMPLE_DEFAULT) continue;
    return Float64Array.from(e.samples, PDFSampler.toNumber);
  }
  return null;
}

/* ── asking how many values ─────────────────────────────────────────────── */

/**
 * Before a send: how many values to draw from each distribution of the
 * selection (only when it has any), or, for a lazy file, that it is to go.
 * onOk(n) runs in the OK button's click, which is the gesture the new tab
 * needs.
 */
function rbAskSampleSize(plan, how, onOk) {
  const overlay = document.createElement('div');
  overlay.className = 'url-dialog-overlay rb-ask rb-sample-ask';
  const dialog = document.createElement('div');
  dialog.className = 'url-dialog';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  const heading = document.createElement('h3');
  const verb = how === 'smui' ? 'Send' : 'Save';
  heading.textContent = plan.draws ? 'Values from the distributions' : `${verb} the selection`;
  dialog.setAttribute('aria-label', heading.textContent);
  dialog.appendChild(heading);
  const p = document.createElement('p');
  const n = plan.items.length;
  const d = plan.draws;
  const what = n === 1 ? 'One dataset' : `${n.toLocaleString('en-US')} datasets`;
  const has = d === 1 ? (n === 1 ? ' with a distribution' : ', one with a distribution') : ` with ${d.toLocaleString('en-US')} distributions`;
  p.textContent = d
    ? `${what}${has}. How many values should be drawn from ${d === 1 ? 'it' : 'each'}? Each distribution's values become a column, a row per value.`
    : `${what}, ${verb === 'Send' ? 'to the User Interface for statsmodels' : 'as an HDF5 file'}.`;
  dialog.appendChild(p);

  let radios = [];
  let other = null;
  if (plan.draws) {
    const list = document.createElement('div');
    list.className = 'sample-data-list rb-ask-choices rb-sample-choices';
    list.setAttribute('role', 'radiogroup');
    list.setAttribute('aria-label', 'Values from each distribution');
    const shownText = plan.shown === plan.draws ? 'the values the histogram shows'
      : plan.shown ? `the histogram's where it shows them, the rest drawn anew` : 'drawn anew, as many as the histogram draws';
    const row = (value, text, detail) => {
      const label = document.createElement('label');
      label.className = 'sample-data-item';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'rb-sample-size';
      radio.value = String(value);
      const words = document.createElement('span');
      words.className = 'rb-ask-choice';
      words.textContent = text;
      if (detail) {
        const small = document.createElement('span');
        small.className = 'rb-ask-detail';
        small.textContent = detail;
        words.appendChild(small);
      }
      label.append(radio, words);
      list.appendChild(label);
      radios.push(radio);
      return label;
    };
    row(RB_SAMPLE_DEFAULT, '1,000', shownText);
    for (const k of [10000, 100000, 1000000]) row(k, k.toLocaleString('en-US'), 'drawn anew');
    const otherRow = row('other', 'Another number', `from 2 to ${RB_SAMPLE_MAX.toLocaleString('en-US')}, drawn anew`);
    other = document.createElement('input');
    other.type = 'text';
    other.inputMode = 'numeric';
    other.className = 'url-input rb-sample-other';
    other.setAttribute('aria-label', 'Another number of values');
    other.placeholder = '25000';
    otherRow.querySelector('.rb-ask-choice').appendChild(other);
    other.addEventListener('focus', () => { radios[radios.length - 1].checked = true; });
    radios[0].checked = true;
    dialog.appendChild(list);
  }
  const error = document.createElement('div');
  error.className = 'url-error';
  error.setAttribute('role', 'alert');
  dialog.appendChild(error);
  const buttons = document.createElement('div');
  buttons.className = 'url-dialog-buttons';
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'url-btn url-btn-cancel';
  cancel.textContent = 'Cancel';
  const ok = document.createElement('button');
  ok.type = 'button';
  ok.className = 'url-btn url-btn-load';
  ok.textContent = verb;
  buttons.append(cancel, ok);
  dialog.appendChild(buttons);
  overlay.appendChild(dialog);

  const before = document.activeElement;
  const finish = () => {
    document.removeEventListener('keydown', onKey, true);
    overlay.remove();
    if (before && before.isConnected && typeof before.focus === 'function') before.focus();
  };
  const go = () => {
    let count = RB_SAMPLE_DEFAULT;
    if (plan.draws) {
      const picked = radios.find(r => r.checked);
      if (picked && picked.value === 'other') {
        const t = other.value.replace(/[\s,_]/g, '');
        count = /^\d+$/.test(t) ? Number(t) : NaN;
        if (!(count >= 2 && count <= RB_SAMPLE_MAX)) {
          error.textContent = `A whole number from 2 to ${RB_SAMPLE_MAX.toLocaleString('en-US')}.`;
          other.focus();
          return;
        }
      } else if (picked) count = Number(picked.value);
    }
    finish();
    onOk(count);
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(); }
    else if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); e.stopPropagation(); go(); }
  };
  cancel.addEventListener('click', finish);
  ok.addEventListener('click', go);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(overlay);
  (radios[0] || ok).focus();
}

/**
 * A menu choice: Send or Save. A selection with distributions asks how
 * many values first; one in a lazy file fetches what it needs, and a send
 * then asks to go on (the new tab needs a click). Anything else goes at
 * once: the tab opens in this very click.
 */
function rbChooseSend(payload, how) {
  const plan = rbPlanPackage(payload);
  if (plan.fetch.length) {
    setFileLoadProgress(null, 'Reading the selection…');
    rbFetchPlan(plan).then(() => {
      hideFileLoadTicker();
      const again = rbPlanPackage(payload);
      if (rbRefused(again)) return;
      if (again.draws || how === 'smui') rbAskSampleSize(again, how, (n) => rbSend(again, how, n));
      else rbSend(again, how, RB_SAMPLE_DEFAULT);
    }, (e) => {
      hideFileLoadTicker();
      reportFailure('rbChooseSend', e, { userMessage: `The selection could not be read: ${e.message || e}` });
    });
    return;
  }
  if (rbRefused(plan)) return;
  if (plan.draws) rbAskSampleSize(plan, how, (n) => rbSend(plan, how, n));
  else rbSend(plan, how, RB_SAMPLE_DEFAULT);
}

/** Whether a plan has nothing to send, or too much; said if so. */
function rbRefused(plan) {
  if (!plan.items.length) { notifyUser('There is no dataset in the selection to send.'); return true; }
  if (plan.items.length > RB_PACKAGE_MAX_DATASETS || plan.values > RB_PACKAGE_MAX_VALUES) {
    notifyUser(`The selection is too large to send: ${plan.items.length.toLocaleString('en-US')} datasets, ${Math.round(plan.values).toLocaleString('en-US')} values. Select less of it.`);
    return true;
  }
  return false;
}

/**
 * Package the selection and send it to smui (the tab opened now, in the
 * click) or save it.
 */
function rbSend(plan, how, n) {
  const tab = how === 'smui' ? rbOpenSmuiTab() : null;
  if (how === 'smui' && !tab) {
    notifyUser('The browser did not let this page open a new tab: allow pop-ups for this site, then send again.');
    return;
  }
  (async () => {
    try {
      setFileLoadProgress(0, 'Packaging the selection…');
      const pack = await rbBuildPackage(plan, n, (done, total) => {
        setFileLoadProgress(total ? done / total : null, `Packaging the selection: ${done.toLocaleString('en-US')} of ${total.toLocaleString('en-US')} datasets`);
        if (tab) tab.progress(`The HDF5 Browser is packaging its selection: ${done} of ${total} datasets`);
      });
      if (how === 'save') {
        hideFileLoadTicker();
        rbDownload(pack.buffer, pack.name);
        return;
      }
      setFileLoadProgress(null, 'Sending to the User Interface for statsmodels…');
      const tables = await tab.send(pack.name, pack.buffer);
      hideFileLoadTicker();
      notifyUser(tables.length && tables.length <= 3
        ? `Sent to the User Interface for statsmodels: ${tables.join(', ')}.`
        : `Sent to the User Interface for statsmodels${tables.length ? `: ${tables.length} tables` : ''}.`, { tone: 'success' });
    } catch (e) {
      hideFileLoadTicker();
      if (tab) tab.close();
      reportFailure('rbSend', e, { userMessage: `${how === 'smui' ? 'Sending' : 'Saving'} the selection failed: ${e.message || e}` });
    }
  })();
}

function rbDownload(buffer, name) {
  const url = URL.createObjectURL(new Blob([buffer], { type: 'application/x-hdf5' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ── the package ────────────────────────────────────────────────────────── */

/** An attribute's value as the package keeps it: text, a number, or a list of either. */
function rbPlainAttr(v) {
  if (v == null) return null;
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string') return v.length > 100000 ? v.slice(0, 100000) : v;
  if (ArrayBuffer.isView(v)) return Array.from(v, PDFSampler.toNumber).filter(x => typeof x === 'number');
  if (Array.isArray(v)) {
    const out = v.map(x => (typeof x === 'bigint' ? Number(x) : x));
    return out.every(x => typeof x === 'number' || typeof x === 'string') ? out : null;
  }
  return null;
}

function rbAttrsOf(node) {
  const out = {};
  const all = FileService.attrs(node);
  for (const [k, v] of Object.entries(all)) {
    if (RB_PACKAGE_SKIP_ATTRS.has(k)) continue;
    const p = rbPlainAttr(v);
    if (p != null && !(Array.isArray(p) && !p.length)) out[k] = p;
  }
  return out;
}

/** Attributes onto an h5wasm object: text, numbers, lists of either. */
function rbSetAttrs(obj, attrs) {
  for (const [name, v] of Object.entries(attrs || {})) {
    try {
      if (typeof v === 'string') obj.create_attribute(name, v);
      else if (typeof v === 'number') obj.create_attribute(name, v, [], Number.isInteger(v) && Math.abs(v) < 2 ** 31 ? '<i' : '<d');
      else if (Array.isArray(v) && v.length) {
        if (v.every(x => typeof x === 'number')) obj.create_attribute(name, Float64Array.from(v), [v.length], '<d');
        else obj.create_attribute(name, v.map(x => (x == null ? '' : String(x))));
      }
    } catch (e) { ignoreFailure('rbSetAttrs', e); }
  }
}

/** A dataset's values as the package writes them: doubles, or texts. */
function rbValuesOf(node) {
  let v;
  try { v = node.value; } catch (e) { return { why: String(e && e.message || e).split('\n').filter(Boolean).pop() }; }
  const shape = Array.isArray(node.shape) ? node.shape.map(Number) : [];
  if (v === undefined || v === null) return { why: 'no values' };
  if (typeof v === 'number' || typeof v === 'bigint') return { data: Float64Array.of(Number(v)), shape };
  if (typeof v === 'string') return { data: [v], shape };
  if (ArrayBuffer.isView(v)) return { data: v instanceof Float64Array ? v : Float64Array.from(v, Number), shape };
  if (Array.isArray(v) && v.every(x => x == null || typeof x === 'string')) return { data: v.map(x => (x == null ? '' : x)), shape };
  return { why: 'a compound or nested type, which is not sent' };
}

/** A lookup table's point as a column name: a time is t=…, a name is itself. */
function rbPointName(name, label) {
  const s = String(label ?? '').trim();
  return /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s) ? `${name} t=${s}` : `${name} ${s}`;
}

/**
 * The values drawn for a dataset's distributions: { data, shape, attrs } for
 * /samples, or null (no distribution, or one rb does not draw from).
 */
function rbSamplesOf(item, n, notes) {
  const specs = rbPdfSpecs(item.node);
  if (!specs) return null;
  const name = item.path.split('/').pop();
  if (specs.unread || !specs.list.length) {
    notes.push(`${item.path}: its distribution is not one this page draws from`);
    return null;
  }
  const values = rbValuesOf(item.node);
  const flat = values.data && !Array.isArray(values.data) ? values.data : null;
  const attrs = { probabilistic: 'TRUE', time_dependent: 'FALSE' };
  const unit = getAttr(item.node, 'unit');
  if (unit != null) attrs.unit = String(unit);
  const pdf = getAttr(item.node, 'pdf');
  if (typeof pdf === 'string') attrs.pdf = pdf;
  let drawn = 0, shown = 0;
  // a raw distribution is its dataset's values, which go as they are
  if (!specs.lookup && rbIsRaw(specs.list[0])) return null;
  if (specs.lookup && specs.list.every(sp => !sp || rbIsRaw(sp))) return null;
  const draw = (spec, point) => {
    if (n === RB_SAMPLE_DEFAULT) {
      const seen = rbShownSamples(item.path, item.fileKey, point);
      if (seen) { shown++; return seen; }
    }
    const s = generatePdfSamples(spec, n);
    if (s) drawn++;
    return s ? Float64Array.from(s) : null;
  };
  if (!specs.lookup) {
    const spec = specs.list[0];
    const data = draw(spec, null);
    if (!data) { notes.push(`${item.path}: no values could be drawn from its distribution (${spec.type})`); return null; }
    attrs.drawn = shown ? 'the 1000 values the histogram shows' : `${n} values drawn from the distribution`;
    return { data, shape: [data.length], attrs };
  }
  // a lookup table: a column per point, a row per value drawn
  const labels = pdfIndexLabels(getAttr(item.node, 'index'));
  const k = specs.list.length;
  const columns = [];
  for (let i = 0; i < k; i++) {
    const spec = specs.list[i];
    let col;
    if (!spec) col = flat && i < flat.length ? Float64Array.of(flat[i]) : Float64Array.of(NaN);
    else if (rbIsRaw(spec)) {
      // its rows are the realisations, a column per point
      const rows = flat ? Math.floor(flat.length / k) : 0;
      const from = spec.include_deterministic ? 1 : 0;
      col = new Float64Array(Math.max(0, rows - from));
      for (let r = from; r < rows; r++) col[r - from] = flat[r * k + i];
    } else col = draw(spec, i) || Float64Array.of(NaN);
    columns.push(col);
  }
  const rows = Math.max(...columns.map(c => c.length));
  const data = new Float64Array(rows * k);
  for (let i = 0; i < k; i++) {
    const c = columns[i];
    // a point without a distribution is its value in every row
    for (let r = 0; r < rows; r++) data[r * k + i] = c.length === 1 && rows > 1 && !specs.list[i] ? c[0] : (r < c.length ? c[r] : NaN);
  }
  const points = columns.map((_, i) => labels[i] ?? i + 1);
  attrs.columns = points.map(l => rbPointName(name, l));
  attrs.drawn = shown && !drawn ? 'the 1000 values the histogram shows, per point' : `${n} values drawn per point`;
  return { data, shape: [rows, k], attrs, points };
}

/** The package's tree: groups by name, datasets with a load() of their values. */
function rbTreeGroup(attrs = {}) {
  return { kind: 'group', attrs, children: new Map() };
}

function rbTreeAt(root, parts, attrsAt) {
  let at = root;
  let path = '';
  for (const part of parts) {
    path += `/${part}`;
    let next = at.children.get(part);
    if (!next || next.kind !== 'group') {
      next = rbTreeGroup(attrsAt ? attrsAt(path) : {});
      at.children.set(part, next);
    }
    at = next;
  }
  return at;
}

const rbLinkName = (s) => {
  const out = String(s ?? '').replace(/\//g, '⁄').trim();
  return out === '' || out === '.' || out === '..' ? '_' : out;
};

/**
 * The selection written as an HDF5 file: { buffer, name }.
 *
 * @param {Object} plan - From rbPlanPackage
 * @param {number} n - Values to draw from each distribution
 * @param {function(number, number): void} [onProgress]
 */
async function rbBuildPackage(plan, n, onProgress) {
  const files = [...new Set(plan.items.map(it => it.fileKey))];
  const several = files.length > 1;
  const notes = [];
  const root = rbTreeGroup();
  const timeOf = new Map();          // fileKey -> its /time's path in the package, or null
  const samples = [];                // [{ it, s }]: the values drawn

  // each file's /time, once; files whose times are the same share one
  const times = [];
  for (const fk of files) {
    const file = loadedFiles[fk];
    const anySeries = plan.items.some(it => it.fileKey === fk && rbIsSeries(file, it));
    const t = anySeries ? FileService.get(file, '/time') : null;
    if (!t || t.type !== 'Dataset' || !Array.isArray(t.shape) || t.shape.length !== 1) { timeOf.set(fk, null); continue; }
    const v = rbValuesOf(t);
    if (!v.data || Array.isArray(v.data)) { timeOf.set(fk, null); continue; }
    const same = times.find(x => x.data.length === v.data.length && x.data.every((y, i) => y === v.data[i]));
    if (same) { timeOf.set(fk, same.path); continue; }
    const parts = several && times.length ? [rbLinkName(fk), 'time'] : ['time'];
    const path = `/${parts.join('/')}`;
    times.push({ data: v.data, path });
    timeOf.set(fk, path);
    const at = rbTreeAt(root, parts.slice(0, -1));
    at.children.set('time', { kind: 'dataset', attrs: rbAttrsOf(t), shape: v.shape, load: async () => v.data, scale: 'time' });
  }

  for (const it of plan.items) {
    const file = loadedFiles[it.fileKey];
    if (it.path === '/time' && timeOf.get(it.fileKey)) continue;          // written above
    const prefix = several ? [rbLinkName(it.fileKey)] : [];
    const parts = it.path.split('/').filter(Boolean).map(rbLinkName);
    const groupAttrs = (p) => {
      const sourcePath = several ? p.slice(prefix[0].length + 1) || '/' : p;
      const g = sourcePath && sourcePath !== '/' ? FileService.get(file, sourcePath) : null;
      return g && g.type === 'Group' ? rbAttrsOf(g) : {};
    };
    const at = rbTreeAt(root, [...prefix, ...parts.slice(0, -1)], several ? (p) => (p === `/${prefix[0]}` ? { file: it.fileKey } : groupAttrs(p)) : groupAttrs);
    const leaf = parts[parts.length - 1];
    const series = rbIsSeries(file, it);
    const attrs = rbAttrsOf(it.node);
    const specs = rbPdfSpecs(it.node);
    // a lookup table: a pdf per point and an index
    if (specs && specs.lookup && attrs.index != null && attrs.lookup_table == null) attrs.lookup_table = 'true';
    const node = {
      kind: 'dataset', attrs, shape: Array.isArray(it.node.shape) ? it.node.shape.map(Number) : [],
      item: it,
      scaleOf: series && timeOf.get(it.fileKey) ? timeOf.get(it.fileKey) : null,
    };
    at.children.set(leaf, node);
    // (a lookup table's samples read its values: here first, a lazy file's fetched)
    if (rbPdfSpecs(it.node)) {
      const lazy = lazyStateOf(file);
      if (lazy) await lazy.ensureValues([it.path]);
      else await rbEnsurePlugins(it.node);
    }
    const s = rbSamplesOf(it, n, notes);
    if (s) samples.push({ it, s });
  }
  const names = files.map(fk => String(fk).replace(/\.(h5|hdf5|he5|eas)$/i, ''));
  // the values drawn, side by side under /samples, each by its name, or by
  // as much of its path as tells it apart (a.b), and its file's when the
  // same comes from two files: kd (run 2)
  let samplesAt = 'samples';
  for (let k = 2; root.children.has(samplesAt); k++) samplesAt = `samples ${k}`;     // (the file's own samples kept)
  if (samples.length) {
    const sat = rbTreeAt(root, [samplesAt]);
    const tail = (x, k) => x.words.slice(-k).join('.');
    for (const x of samples) x.words = x.it.path.split('/').filter(Boolean);
    for (const x of samples) {
      let k = 1;
      while (k < x.words.length && samples.some(y => y !== x && y.it.fileKey === x.it.fileKey && tail(y, k) === tail(x, k))) k++;
      x.name = tail(x, k);
    }
    for (const x of samples) {
      const twice = samples.some(y => y.it.fileKey !== x.it.fileKey && y.name === x.name);
      let name = rbLinkName(twice ? `${x.name} (${names[files.indexOf(x.it.fileKey)]})` : x.name);
      for (let k = 2, base = name; sat.children.has(name); k++) name = `${base} ${k}`;
      if (x.s.points) x.s.attrs.columns = x.s.points.map(l => rbPointName(name, l));
      x.s.attrs.source_path = x.it.path;
      if (several) x.s.attrs.source_file = x.it.fileKey;
      sat.children.set(name, { kind: 'dataset', attrs: x.s.attrs, shape: x.s.shape, load: async () => x.s.data });
    }
  }

  const drawnNote = plan.draws
    ? ` Values from the distributions (under /${samplesAt}): ${n === RB_SAMPLE_DEFAULT && plan.shown ? 'the 1000 the histogram shows where it shows them, the rest' : `${n.toLocaleString('en-US')} per distribution,`} independent random draws (Monte Carlo) from each one's pdf attribute, not the realisations of a run.`
    : '';
  // (said once everything is written, with what could not be)
  const rootAttrs = () => ({
    source: `the HDF5 Browser (rb.html): ${files.join(', ')}`,
    created_time: rbStamp(new Date()),
    description: `${plan.items.length === 1 ? 'One dataset' : `${plan.items.length} datasets`} sent from the HDF5 Browser.${drawnNote}${notes.length ? ` Left out: ${notes.slice(0, 8).join('; ')}${notes.length > 8 ? `; and ${notes.length - 8} more` : ''}.` : ''}`,
  });
  const buffer = await rbWritePackage(root, plan.items.length, onProgress, notes, rootAttrs);
  const name = (files.length > 1 ? `${plan.label} (${names[0]} and ${files.length - 1} more).h5` : `${names[0]} ${plan.label}.h5`).replace(/[\\/]/g, '_');
  return { buffer, name, notes };
}

/** A local date and time as result files write it: 2026-10-11 10:30:00. */
function rbStamp(d) {
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Whether a dataset is a series over its file's /time: time_dependent said by it or its group. */
function rbIsSeries(file, it) {
  let td = getAttr(it.node, 'time_dependent');
  if (td == null) {
    const parent = it.path.slice(0, it.path.lastIndexOf('/')) || '/';
    const g = parent !== '/' ? FileService.get(file, parent) : null;
    td = g ? getAttr(g, 'time_dependent') : null;
  }
  return td != null && isTruthyAttribute(td);
}

/**
 * The tree written with h5wasm in memory, as an assessment's run is
 * (easWriteHdf5): stopping now and then to let the page draw, a lazy
 * file's values fetched a few at a time. Scales are made, and attached to
 * the first dimension of their series, once everything is written.
 */
async function rbWritePackage(root, total, onProgress, notes, rootAttrs) {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = `/rb_smui_${Date.now()}_${Math.random().toString(36).slice(2, 11)}.h5`;
  const breathe = () => Promise.race([new Promise(requestAnimationFrame), new Promise(resolve => setTimeout(resolve, 50))]);
  let done = 0;
  let paused = performance.now();
  const scales = [];
  const attach = [];
  try {
    const f = new File(path, 'w');
    try {
      const walk = async (into, node, at) => {
        for (const [name, child] of node.children) {
          const here = at === '/' ? `/${name}` : `${at}/${name}`;
          if (child.kind === 'group') {
            const g = into.create_group(name);
            rbSetAttrs(g, child.attrs);
            await walk(g, child, here);
            continue;
          }
          let v;
          if (child.load) v = { data: await child.load(), shape: child.shape };
          else {
            const lazy = lazyStateOf(loadedFiles[child.item.fileKey]);
            if (lazy) await lazy.ensureValues([child.item.path]);
            else await rbEnsurePlugins(child.item.node);
            v = rbValuesOf(child.item.node);
          }
          if (!v.data) { notes.push(`${child.item.path}: ${v.why}`); continue; }
          const ds = Array.isArray(v.data)
            ? into.create_dataset({ name, data: v.data, shape: v.shape.length ? v.shape : undefined })
            : into.create_dataset({ name, data: v.data, shape: v.shape, dtype: '<d' });
          rbSetAttrs(ds, child.attrs);
          if (child.scale) scales.push({ path: here, name: child.scale });
          if (child.scaleOf && v.shape.length) attach.push({ path: here, scale: child.scaleOf });
          if (!child.load) done++;
          if (performance.now() - paused > 150) {
            if (onProgress) onProgress(done, total);
            await breathe();
            paused = performance.now();
          }
        }
      };
      await walk(f, root, '/');
      for (const s of scales) {
        try { f.get(s.path).make_scale(s.name); } catch (e) { ignoreFailure('rbWritePackage', e); }
      }
      for (const a of attach) {
        try { f.get(a.path).attach_scale(0, a.scale); } catch (e) { ignoreFailure('rbWritePackage', e); }
      }
      rbSetAttrs(f, rootAttrs ? rootAttrs() : root.attrs);
    } finally {
      f.close();
    }
    const bytes = FS.readFile(path);
    return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? bytes.buffer : bytes.slice().buffer;
  } finally {
    try { FS.unlink(path); } catch (e) { ignoreFailure('rbWritePackage', e); }
  }
}

/** The decompressors a dataset of a file in memory needs, installed before it is read. */
async function rbEnsurePlugins(node) {
  let filters = [];
  try { filters = node.filters || []; } catch (_) { return; }
  const wanted = filters.map(f => RB_PLUGIN_BY_FILTER[f.id]).filter(p => p && !_rbPluginsInstalled.has(p));
  if (wanted.length) await Promise.all(wanted.map(rbInstallPlugin));
}

/* ── the tab in smui.html ───────────────────────────────────────────────── */

/**
 * The smui tab to send to: the one sent to before when it is still open,
 * else a new one. Opened here, in the click; null when the browser
 * refused (a pop-up blocker).
 */
function rbOpenSmuiTab() {
  const url = new URL(RB_SMUI_PAGE, window.location.href);
  url.hash = `handoff=${encodeURIComponent(window.location.origin)}`;
  let win = null;
  try { win = window.open('', RB_SMUI_WINDOW); } catch (_) { win = null; }
  if (!win) return null;
  let open = false;
  try { open = /\/smui\.html$/.test(win.location.pathname) && !!win.SM; } catch (_) { open = false; }
  if (!open) {
    try { win.location.replace(url.href); } catch (_) { win.location.href = url.href; }
  }
  try { win.focus(); } catch (_) { /* the browser decides */ }
  return rbSmuiChannel(win, url.origin);
}

/**
 * Talking to the tab: asks it whether it is listening until it says so
 * ('smui-ready'; a new tab also says it unasked once it is), then sends.
 */
function rbSmuiChannel(win, origin) {
  let ready = false;
  let onReady = null;
  let settle = null;
  const listen = (ev) => {
    if (ev.source !== win || ev.origin !== origin || !ev.data || typeof ev.data !== 'object') return;
    const kind = ev.data.kvot;
    if (kind === 'smui-ready') { ready = true; if (onReady) onReady(); }
    else if (kind === 'smui-opened' && settle) settle({ ok: true, tables: Array.isArray(ev.data.tables) ? ev.data.tables.map(String) : [] });
    else if (kind === 'smui-error' && settle) settle({ ok: false, message: String(ev.data.message || '') });
  };
  window.addEventListener('message', listen);
  const ask = () => { try { win.postMessage({ kvot: 'smui-ping' }, origin); } catch (_) { /* not there yet */ } };
  const pinger = setInterval(() => { if (ready || win.closed) clearInterval(pinger); else ask(); }, 1000);
  ask();
  const close = () => { clearInterval(pinger); window.removeEventListener('message', listen); };
  return {
    close,
    progress(text) { if (ready) { try { win.postMessage({ kvot: 'smui-progress', text }, origin); } catch (_) { /* gone */ } } },
    async send(name, buffer) {
      if (!ready) {
        const came = await new Promise((resolve) => {
          const timer = setTimeout(() => { onReady = null; resolve(false); }, RB_SMUI_READY_MS);
          onReady = () => { clearTimeout(timer); onReady = null; resolve(true); };
        });
        if (!came) {
          close();
          throw new Error(win.closed ? 'the User Interface for statsmodels tab was closed' : `the User Interface for statsmodels did not answer from ${origin} (it may still be loading, or not take files from ${window.location.origin})`);
        }
      }
      // (no time limit on the answer: smui may ask its reader what to open)
      const answer = new Promise((resolve) => {
        settle = (r) => { settle = null; clearInterval(watch); resolve(r); };
        const watch = setInterval(() => { if (win.closed && settle) settle({ ok: false, message: 'the tab was closed' }); }, 1000);
      });
      win.postMessage({ kvot: 'smui-open', name, buffer }, origin, [buffer]);
      const r = await answer;
      close();
      if (!r.ok) throw new Error(r.message || 'the User Interface for statsmodels refused the file');
      return r.tables;
    },
  };
}
