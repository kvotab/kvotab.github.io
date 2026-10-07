/*
  dose_coefficients.html: the settings, the worker and what is shown.

  The calculations run in worker.js; this file asks it for the catalogue of
  each system (which nuclides and forms it covers) and for results, and draws
  the tables, the charts and the model. Everything that comes from data is
  put in the page as text nodes.
*/
import { drawModel, fillBoxes, fmtRate, laneOf, transferKey } from './diagram.js';
import { key as placeName } from './regions.js';
import { drawBody, partsOf, PARTS } from './body.js';
import { detriment103, detriment60, nominalDetriment, DOSE_LABEL, P103, P60 } from './risk.js';
import { radonDoses, radonAssemble, radonJobText, KINDS as RADON_KINDS, MODE_LABEL, PAE_PER_BQ, EEC_J_PER_BQ, MJ_PER_WLM } from './radon.js';
import { setupBatch } from './batch.js';
import { listFolders, removeFolder, MAKE_VERSION } from './decay-store.js';
import { GEOMETRY, externalForms } from './external.js';

const $ = (id) => document.getElementById(id);
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
};

export const AGE_LABEL = { 100: '3 months', 365: '1 year', 1825: '5 years', 3650: '10 years', 5475: '15 years', 7300: 'Adult', 9125: 'Adult' };
const SYSTEM_LABEL = { 60: 'ICRP 60 system (Publications 56–72)', 103: 'ICRP 103 system (Publication 158, Part 2 and 3 drafts)' };
const STORE = 'kvot.dose';

/* ---- decay data ---------------------------------------------------------- */
/* Each system calculates with its own decay data (ICRP 38 in the ICRP 60
   system, ICRP 107 in the ICRP 103 one), or with decay data made from a
   release of ENSDF: one made on this site (resources/data/dose/ensdf/, by
   scripts/gen-dose-ensdf.mjs), or one a visitor opens, made in this browser
   (ensdf-make-worker.js) and kept in it (decay-store.js). A choice is '' for
   the system's own, 'ensdf:' and a release's id, or 'open:' and the key
   under which ensdf-sources.js keeps the files opened -- the same key on
   the Chart of Nuclides and Radionuclide Decay Chains, which offer the
   release too. NNDC's archive is offered as well ('nndc:' and an id): its
   server lets no other site read its files, so choosing one says where to
   download it. */
const OWN_DECAY = { 60: 'ICRP 38', 103: 'ICRP 107' };
const DECAY = { releases: [], opened: [], made: new Map(), archive: null, making: new Map() };
const SRC = () => (typeof window !== 'undefined' && window.KVOT_ENSDF_SOURCES) || null;
async function loadDecayReleases() {
  try {
    const r = await fetch(new URL('../../data/dose/ensdf/index.json', import.meta.url));
    if (r.ok) DECAY.releases = (await r.json()).releases || [];
  } catch { /* the system's own decay data only */ }
  await refreshOpened();
  // NNDC's archive, for the menus' last group, when it comes.
  SRC()?.archive().then((a) => { DECAY.archive = a; refreshDecayMenus(); }, () => {});
}
/** The releases opened in this browser (on any of the ENSDF pages), and the decay data made of them here. */
async function refreshOpened() {
  const transient = DECAY.opened.filter((r) => r.transient);
  try { DECAY.opened = SRC() ? await SRC().IDB.list() : []; } catch { DECAY.opened = []; }
  for (const t of transient) if (!DECAY.opened.some((r) => r.key === t.key)) DECAY.opened.push(t);
  try { DECAY.made = new Map((await listFolders()).map((f) => [f.key, f])); } catch { DECAY.made = new Map(); }
}
const decayRelease = (decay) => { const m = /^ensdf:(\w+)$/.exec(decay || ''); return m ? DECAY.releases.find((r) => r.id === m[1]) || null : null; };
const openedOf = (decay) => { const m = /^open:([\s\S]+)$/.exec(decay || ''); return m ? DECAY.opened.find((r) => r.key === m[1]) || null : null; };
/** The decay data of a choice in words: 'ICRP 107', 'ENSDF 2026-09-01'. */
const decayLabel = (decay, system) => (!decay ? OWN_DECAY[system]
  : decayRelease(decay)?.label || openedOf(decay)?.label || decay.replace(/^open:/, '').split('|')[0]);
const decayValid = (decay) => !decay || !!decayRelease(decay) || !!openedOf(decay);
const openedDate = (r) => new Date(r.opened || Date.now()).toISOString().slice(0, 10);
/** A select's options: the system's own decay data, then the releases of ENSDF on this site, opened here, and at NNDC. */
function decayOptions(system, current) {
  const opt = (value, text) => h('option', { value, selected: value === (current || '') }, text);
  const group = (label, opts) => (opts.length ? h('optgroup', { label }, ...opts) : null);
  const opened = [...DECAY.opened].sort((p, q) => (q.opened || 0) - (p.opened || 0)).map((r) => opt(`open:${r.key}`, `${r.label} (opened ${openedDate(r)})`));
  const have = new Set([...DECAY.releases, ...DECAY.opened].map((r) => r.label));
  const nndc = (DECAY.archive?.releases || []).filter((r) => !have.has(r.label))
    .map((r) => opt(`nndc:${r.id}`, `${r.label}${r.missing ? ' (incomplete)' : r.files.length > 1 ? ` (${r.files.length} parts)` : ''}`));
  return [opt('', `${OWN_DECAY[system]}, the system’s own`),
    group('ENSDF on this site', DECAY.releases.map((r) => opt(`ensdf:${r.id}`, r.label))),
    group('ENSDF opened in this browser', opened),
    group('ENSDF at NNDC: download, then open', nndc)].filter(Boolean);
}
/* The three menus (the settings', the Batch tab's, Radon at home's) after the releases at hand change. */
function refreshDecayMenus() {
  populateDecay();
  populateRadonDecay();
  batch?.refreshDecay();
}

/* Decay data made in this browser from a release opened: in a worker of
   their own, once; kept for the next visit. */
let makeWorker = null, makeSeq = 0;
const makeJobs = new Map();
function makeDecay(files, key) {
  if (!makeWorker) {
    makeWorker = new Worker(new URL('./ensdf-make-worker.js', import.meta.url), { type: 'module' });
    makeWorker.onmessage = (ev) => {
      const m = ev.data || {}, job = makeJobs.get(m.id);
      if (!job) return;
      if (m.type === 'progress') { job.progress(m); return; }
      makeJobs.delete(m.id);
      if (m.type === 'made') job.resolve(m); else job.reject(new Error(m.message || 'the decay data could not be made'));
    };
    makeWorker.onerror = (ev) => {
      ev.preventDefault();
      for (const [id, job] of makeJobs) { makeJobs.delete(id); job.reject(new Error(ev.message || 'the worker that makes decay data failed to start')); }
      makeWorker = null;
    };
  }
  const names = files.map((f) => f.name).join(', ');
  const t0 = performance.now();
  return new Promise((resolve, reject) => {
    const id = ++makeSeq;
    makeJobs.set(id, {
      resolve: (m) => { progress(null); resolve({ ...m, s: (performance.now() - t0) / 1000 }); },
      reject: (err) => { progress(null); reject(err); },
      progress: (m) => {
        const what = m.stage === 'reading' ? `reading ${m.done} of ${m.total} files`
          : m.stage === 'sorting' ? `picking the decay data sets (${m.done} of ${m.total} files)` : 'computing the radiations';
        status(`Making decay data from ${names}: ${what}…`);
        progress(m.stage === 'reading' ? 0.45 * m.done / m.total : m.stage === 'sorting' ? 0.45 + 0.45 * m.done / m.total : 0.95);
      },
    });
    makeWorker.postMessage({ id, type: 'make', files, key });
  });
}
/** Make sure the decay data of a choice can be read by the calculation workers (made, and by this version). */
function ensureDecay(decay) {
  const rec = openedOf(decay);
  if (!rec) return Promise.resolve();
  const made = DECAY.made.get(rec.key);
  if (made && made.version === MAKE_VERSION) return Promise.resolve();
  if (!DECAY.making.has(rec.key)) {
    DECAY.making.set(rec.key, makeDecay(rec.files, rec.key)
      .then(async (m) => {
        await refreshOpened();
        status(`${rec.label}: decay data made in ${m.s.toFixed(0)} s, ${m.nuclides.toLocaleString('en')} radionuclides; kept in this browser.`, 'ok');
      })
      .finally(() => DECAY.making.delete(rec.key)));
  }
  return DECAY.making.get(rec.key);
}

/* Files a visitor opens: a release zip (or its parts) or ENSDF text. They are
   kept where the ENSDF pages keep theirs, and their decay data are made. */
async function openEnsdf(list) {
  const files = [...(list || [])].filter((f) => f && f.size);
  if (!files.length) return;
  closeGet();
  const total = files.reduce((t, f) => t + f.size, 0);
  const limit = typeof kvotFileTooLarge === 'function' ? kvotFileTooLarge({ name: files.length === 1 ? files[0].name : 'The selection', size: total }, 1024 ** 3) : null;
  if (limit?.tooLarge) { status(limit.reason, 'error'); return; }
  let m;
  try {
    m = await makeDecay(files, null);
  } catch (err) {
    status(`Could not make decay data from ${files.map((f) => f.name).join(', ')}: ${err.message}`, 'error');
    return;
  }
  const rec = { key: m.key, label: m.label, names: files.map((f) => f.name), size: total, opened: Date.now(), files };
  try { await SRC()?.IDB.put(rec); } catch { rec.transient = true; }
  if (!SRC()) rec.transient = true;
  if (rec.transient) DECAY.opened.push(rec);
  await refreshOpened();
  status(`${m.label}: decay data made in ${m.s.toFixed(0)} s, ${m.nuclides.toLocaleString('en')} radionuclides${rec.transient ? '; this browser keeps no files for the page, so open it again next time' : '; kept in this browser, here and on the ENSDF pages'}.`, 'ok');
  await chooseDecay(`open:${m.key}`);
}
/** The settings' decay data, chosen: made first where they must be, then the list of radionuclides. */
async function chooseDecay(decay) {
  state.decay = decayValid(decay) ? decay : '';
  refreshDecayMenus();
  markStale();
  refreshInfo();
  $('dcRun').disabled = true;
  try {
    await ensureDecay(state.decay);
    await loadCatalog(state.system);
  } catch (err) { status(`Could not load the decay data: ${err.message}`, 'error'); }
  save();
}
/* Forget a release opened: here, on the ENSDF pages, and its decay data. */
async function forgetDecay(decay) {
  const rec = openedOf(decay);
  if (!rec) return;
  try { if (!rec.transient) await SRC()?.IDB.remove(rec.key); } catch { /* gone already */ }
  try { await removeFolder(rec.key); } catch { /* none kept */ }
  DECAY.opened = DECAY.opened.filter((r) => r.key !== rec.key);
  await refreshOpened();
  if (RADON.decay === decay) RADON.decay = '';
  batch?.forgetDecay(decay);
  if (state.decay === decay) await chooseDecay('');
  else refreshDecayMenus();
  status(`${rec.label} is no longer kept in this browser.`, 'ok');
  save();
}

/* A release of NNDC's archive that is not to hand: where to download it, and
   how to open it once it is here. */
function showGet(id) {
  const a = DECAY.archive, rel = a?.releases.find((r) => r.id === id);
  if (!rel) return;
  const many = rel.files.length > 1;
  const dash = (range) => range.replace('-', '–');
  const link = (f, i) => [h('a', { href: a.base + f, target: '_blank', rel: 'noopener noreferrer', download: '' }, f.split('/').pop()),
    rel.parts ? h('span', { class: 'dc-get-dim' }, ` A = ${dash(rel.parts[i])}`) : null];
  $('dcGetTitle').textContent = `${rel.label} from NNDC`;
  $('dcGetBody').replaceChildren(
    h('p', {}, 'This release is not on this site. Download it from NNDC’s archive and open it here: the page reads it in your browser and makes its decay data, in some ten seconds, and uploads nothing. It cannot fetch the release for you, as NNDC’s server does not let other sites read its files.'),
    h('ol', {},
      h('li', {}, many ? `Download its ${rel.files.length} parts, one for each range of mass numbers:` : 'Download ', many ? h('ul', {}, rel.files.map((f, i) => h('li', {}, ...link(f, i)))) : link(rel.files[0], 0)),
      h('li', {}, 'Choose ', h('b', {}, `Open the downloaded ${many ? 'files' : 'file'}…`), many ? ' and pick the parts together' : '', `, or drop ${many ? 'them' : 'it'} on the page.`)),
    rel.missing ? h('p', { class: 'dc-get-warn' }, `NNDC lists no part of this release for A = ${rel.missing.map(dash).join(', ')}, so it will have no nuclides there.`) : '',
    h('p', { class: 'dc-get-dim' }, 'It is then kept in this browser, in the Decay data menus and on the Chart of Nuclides and Radionuclide Decay Chains, until you choose Forget.'));
  $('dcGetOpen').textContent = `Open the downloaded ${many ? 'files' : 'file'}…`;
  const dlg = $('dcGet');
  if (typeof dlg.showModal === 'function') { if (!dlg.open) dlg.showModal(); } else dlg.setAttribute('open', '');
}
function closeGet() {
  const dlg = $('dcGet');
  if (!dlg?.open) return;
  if (typeof dlg.close === 'function') dlg.close(); else dlg.removeAttribute('open');
}
/* ENSDF files dropped anywhere on the page are opened. */
function setupEnsdfDrop() {
  let depth = 0;
  const files = (ev) => [...(ev.dataTransfer?.types || [])].includes('Files');
  document.body.addEventListener('dragenter', (ev) => { if (!files(ev)) return; depth++; document.body.classList.add('dc-dropping'); ev.preventDefault(); });
  document.body.addEventListener('dragover', (ev) => { if (files(ev)) ev.preventDefault(); });
  document.body.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove('dc-dropping'); });
  document.body.addEventListener('drop', (ev) => {
    depth = 0;
    document.body.classList.remove('dc-dropping');
    if (!ev.dataTransfer?.files.length) return;
    ev.preventDefault();
    openEnsdf(ev.dataTransfer.files);
  });
}

let batch = null; // the Batch tab (batch.js), set up at the start
const state = {
  system: '103',
  decay: '',
  catalogs: {},
  entry: null,       // the catalogue entry of the chosen nuclide
  result: null,      // {system, spec, label, ages, out}
  running: false,
  tab: 'coef',
};

/* ---- the workers ------------------------------------------------------- */
/* The ages of a run are separate integrations, and so are the inhalations
   behind radon at home: they go to a pool of workers, one for each core the
   machine can spare and at most one per age, each of which loads the data
   once and keeps it. A worker does one request at a time; those waiting are
   taken by rank (what the settings show first, then runs, then radon, then
   batches) and in the order asked. */
const POOL_SIZE = Math.max(1, Math.min(6, (navigator.hardwareConcurrency || 2) - 1));
const RANK = { show: 0, run: 1, radon: 2, batch: 3 };
const pool = []; // {worker, job}
const queue = [];
let seq = 0;
function startWorker() {
  const slot = { worker: new Worker(new URL('./worker.js', import.meta.url), { type: 'module' }), job: null };
  slot.worker.onmessage = (ev) => {
    const job = slot.job;
    if (!job || ev.data.id !== job.id) return;
    if (ev.data.type === 'progress') { job.progress?.(ev.data); return; }
    slot.job = null;
    if (ev.data.type === 'result') job.resolve(ev.data.result);
    else job.reject(new Error(ev.data.message || 'calculation failed'));
    dispatch();
  };
  // A worker that fails outside a request -- that cannot start, say -- is
  // ended, and its request fails with the reason.
  slot.worker.onerror = (ev) => {
    ev.preventDefault();
    endWorker(slot, new Error(ev.message || 'the calculation worker failed to start'));
    dispatch();
  };
  pool.push(slot);
  return slot;
}
function endWorker(slot, err) {
  slot.worker.terminate();
  const i = pool.indexOf(slot);
  if (i >= 0) pool.splice(i, 1);
  slot.job?.reject(err);
  slot.job = null;
}
function dispatch() {
  while (queue.length) {
    const slot = pool.find((s) => !s.job) || (pool.length < POOL_SIZE ? startWorker() : null);
    if (!slot) return;
    slot.job = queue.shift();
    slot.worker.postMessage({ id: slot.job.id, ...slot.job.msg });
  }
}
function ask(msg, progress, rank = RANK.show) {
  return new Promise((resolve, reject) => {
    const job = { id: ++seq, msg, progress, rank, resolve, reject };
    let at = queue.length;
    while (at > 0 && queue[at - 1].rank > rank) at--;
    queue.splice(at, 0, job);
    dispatch();
  });
}
/** Stop the requests of a rank: those waiting fail, and the workers busy with one are ended. */
function stopRank(rank) {
  const err = new Error('stopped');
  for (const slot of pool.filter((s) => s.job?.rank === rank)) endWorker(slot, err);
  for (let k = queue.length - 1; k >= 0; k--) if (queue[k].rank === rank) queue.splice(k, 1)[0].reject(err);
  dispatch();
}

/* ---- settings ----------------------------------------------------------- */
function load() { try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch { return {}; } }
function save() {
  try {
    localStorage.setItem(STORE, JSON.stringify({
      system: state.system, decay: state.decay, radonDecay: RADON.decay, nuclide: $('dcNuclide').value.trim(), route: route(), form: $('dcForm').value,
      amad: $('dcAmad').value, ages: [...$('dcAges').querySelectorAll('input:checked')].map((i) => Number(i.value)), cutoff: $('dcCutoff').value, rtol: $('dcRtol').value, tab: state.tab,
      side: getComputedStyle($('dcRoot')).getPropertyValue('--dc-side-width').trim() || null,
      batch: batch?.settings() ?? load().batch ?? null,
      model: { show: VIEW.show, dose: VIEW.dose, from: VIEW.from }, shares: sharesOn(),
    }));
  } catch { /* storage unavailable */ }
}
const route = () => document.querySelector('input[name="dcRoute"]:checked')?.value || 'ingestion';
// The ages ticked that the route and system have (FGR 12: the adult only).
const ages = () => [...$('dcAges').querySelectorAll('input:checked:not(:disabled)')].map((i) => Number(i.value));
const external = (r) => r?.spec?.route === 'external';
/* An age's label: external exposure's youngest phantom is the newborn's. */
const ageLabel = (age, ext) => (ext && age === 100 ? 'Newborn' : AGE_LABEL[age]);
const digits = () => Number($('dcDigits').value) || 2;
const sexView = () => document.querySelector('input[name="dcSex"]:checked')?.value || 'avg';

function status(text, kind = '') {
  const s = $('dcStatus');
  s.className = `dc-status${kind ? ` ${kind}` : ''}`;
  s.textContent = text;
}
function progress(frac) {
  const s = $('dcStatus');
  let bar = s.querySelector('.dc-progress');
  if (frac == null) { bar?.remove(); return; }
  if (!bar) { bar = h('div', { class: 'dc-progress' }, h('div')); s.append(bar); }
  bar.firstChild.style.width = `${Math.round(100 * frac)}%`;
}

/* ---- formatting ---------------------------------------------------------- */
export function sci(x, d = 2) {
  if (x == null || !Number.isFinite(x)) return '–';
  if (x === 0) return '0';
  const [m, e] = x.toExponential(d - 1).split('e');
  const ex = Number(e);
  return `${m}E${ex < 0 ? '-' : '+'}${String(Math.abs(ex)).padStart(2, '0')}`;
}
export function halfLife(T) {
  if (!(T > 0)) return '';
  // Four figures; whole numbers up to a million, then powers of ten.
  const fmt = (v) => (v >= 1e6 ? v.toExponential(3).replace(/e\+?(-?\d+)$/, '·10^$1').replace(/\^(-?\d+)/, (_, e) => [...e].map((c) => '⁰¹²³⁴⁵⁶⁷⁸⁹'['0123456789'.indexOf(c)] ?? '⁻').join('')) : String(Number(v.toPrecision(4))));
  if (T < 1 / 86400) return `${fmt(T * 86400e3)} ms`;
  if (T < 1 / 1440) return `${fmt(T * 86400)} s`;
  if (T < 1 / 24) return `${fmt(T * 1440)} min`;
  if (T < 1) return `${fmt(T * 24)} h`;
  if (T < 365.25) return `${fmt(T)} d`;
  return `${fmt(T / 365.25)} y`;
}

/* ---- catalogue and choices ------------------------------------------------- */
/* Settings that apply to one system only. */
function systemSettings() {
  const row = $('dcCutoff').closest('.dc-row');
  if (row) row.hidden = state.system === '60';
  routeSettings();
}
/* Settings that follow the route: for external exposure the geometries in
   place of the forms, the ages of the reports' phantoms (FGR 12 has the
   adult's only), and nothing to set for the integration. */
function routeSettings() {
  const ext = route() === 'external';
  $('dcFormLabel').textContent = ext ? 'Geometry' : 'Chemical or physical form';
  $('dcAgesTitle').textContent = ext ? 'Ages' : 'Ages at intake';
  $('dcAgeFirst').textContent = ext ? 'Newborn' : '3 months';
  for (const i of $('dcAges').querySelectorAll('input')) {
    const off = ext && state.system === '60' && i.value !== '7300';
    i.disabled = off;
    const label = i.closest('label');
    if (off) label.setAttribute('data-tip', 'Federal Guidance Report 12, which the ICRP 60 system’s external exposure follows, gives the adult only');
    else label.removeAttribute('data-tip');
  }
  $('dcCalcSec').hidden = ext;
}

/** The catalogue of a system with some decay data, asked for once. */
const catKey = (system, decay = state.decay) => `${system}|${decay || ''}`;
const currentCatalog = () => state.catalogs[catKey(state.system)];
function catalogOf(system, decay = state.decay) {
  const k = catKey(system, decay);
  return (state.catalogP ||= {})[k] ||= ask({ type: 'catalog', system, decay }).then((c) => (state.catalogs[k] = c))
    .catch((err) => { delete state.catalogP[k]; throw err; });
}
async function loadCatalog(system) {
  systemSettings();
  const k = catKey(system);
  if (!state.catalogs[k]) {
    status('Loading the list of radionuclides…');
    await catalogOf(system);
  }
  const cat = state.catalogs[k];
  hideSuggest();
  $('dcNuclideCount').textContent = `${cat.nuclides.length} nuclides`;
  refreshInfo();
  const decay = state.decay ? ` Decay data: ${decayLabel(state.decay, system)}.` : '';
  status((system === '60'
    ? 'The ICRP 60 system: the ICRP 72 cases, every nuclide and form DCAL calculated them for.'
    : `The ICRP 103 system: ${cat.elements.length} elements of Publication 158 and the Part 2 and 3 drafts.`) + decay);
  nuclideChanged();
}

/* The decay-data select of the settings, for the system chosen, and its note. */
function populateDecay() {
  if (!decayValid(state.decay)) state.decay = '';
  $('dcDecay').replaceChildren(...decayOptions(state.system, state.decay));
  $('dcDecay').value = state.decay;
  const rel = decayRelease(state.decay), rec = openedOf(state.decay);
  $('dcDecayForget').hidden = !rec;
  $('dcDecayNote').textContent = rel
    ? `Made on this site from the decay data sets of ${rel.label}, the way ICRP 107 was made from those of 2004; the ICRP’s own coefficients are of ${OWN_DECAY[state.system]}.`
    : rec ? `Made in this browser from ${rec.names?.join(', ') || rec.label}, opened ${openedDate(rec)}, the way ICRP 107 was made from ENSDF in 2004; the ICRP’s own coefficients are of ${OWN_DECAY[state.system]}.`
      : '';
}

/* The nuclide field's suggestions, drawn by the page under the field. (A
   <datalist> popup is placed by the browser, and Safari put it in the middle
   of this page, whose panes scroll inside the window.) Typing filters the
   catalogue: the element's symbol first (i: iodine before indium), then
   other symbols it begins, mass numbers (137), anything containing it. */
const SUGGEST_MAX = 60;
const suggestKey = (s) => String(s).toLowerCase().replace(/[\s-]+/g, '');
function suggestions(q) {
  const cat = currentCatalog();
  const k = suggestKey(q);
  if (!cat) return [];
  if (!k) return cat.nuclides.slice(0, SUGGEST_MAX);
  const hits = [];
  for (const n of cat.nuclides) {
    const key = suggestKey(n.name), el = n.name.split('-')[0].toLowerCase();
    const rank = key.startsWith(k) ? (k.length >= el.length ? 0 : 1)
      : /^\d/.test(k) && key.slice(el.length).startsWith(k) ? 2
        : key.includes(k) ? 3 : -1;
    if (rank >= 0) hits.push([rank, n]);
  }
  return hits.sort((a, b) => a[0] - b[0]).slice(0, SUGGEST_MAX).map(([, n]) => n);
}
function showSuggest() {
  const input = $('dcNuclide'), list = $('dcNuclideList');
  const items = suggestions(input.value);
  // A name typed in full needs no list.
  if (items.length && suggestKey(items[0].name) === suggestKey(input.value) && items.length === 1) items.length = 0;
  state.suggest = { items, active: -1 };
  list.replaceChildren(...items.map((n, i) => h('li', { role: 'option', id: `dcSug${i}`, 'data-value': n.name, 'aria-selected': 'false' },
    h('span', {}, n.name), n.T ? h('span', { class: 'dc-sug-t' }, halfLife(n.T)) : null)));
  list.hidden = !items.length;
  list.scrollTop = 0;
  input.setAttribute('aria-expanded', String(!list.hidden));
  input.removeAttribute('aria-activedescendant');
}
function hideSuggest() {
  const list = $('dcNuclideList');
  if (!list || list.hidden) return;
  list.hidden = true;
  $('dcNuclide').setAttribute('aria-expanded', 'false');
  $('dcNuclide').removeAttribute('aria-activedescendant');
}
function moveSuggest(step) {
  const s = state.suggest, list = $('dcNuclideList');
  if (!s?.items.length) return;
  s.active = (s.active + step + s.items.length) % s.items.length;
  for (const li of list.children) li.setAttribute('aria-selected', String(li.id === `dcSug${s.active}`));
  const li = list.children[s.active];
  li.scrollIntoView({ block: 'nearest' });
  $('dcNuclide').setAttribute('aria-activedescendant', li.id);
}
function pickSuggest(name) {
  const input = $('dcNuclide');
  input.value = name;
  hideSuggest();
  input.dispatchEvent(new Event('change', { bubbles: true }));
}
function setupSuggest() {
  const input = $('dcNuclide'), list = $('dcNuclideList');
  input.addEventListener('keydown', (e) => {
    const open = !list.hidden;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!open) showSuggest(); else moveSuggest(e.key === 'ArrowDown' ? 1 : -1);
    } else if (e.key === 'Enter' && open && state.suggest?.active >= 0) {
      e.preventDefault();
      pickSuggest(state.suggest.items[state.suggest.active].name);
    } else if (e.key === 'Escape' && open) {
      e.preventDefault();
      hideSuggest();
    } else if (e.key === 'Tab' || e.key === 'Enter') hideSuggest();
  });
  input.addEventListener('blur', hideSuggest);
  // Back in the field (or clicked after Escape) with something typed: the list again.
  const reopen = () => { if (input.value.trim() && list.hidden) showSuggest(); };
  input.addEventListener('focus', reopen);
  input.addEventListener('click', reopen);
  // Keep the focus in the field while a suggestion is pressed.
  list.addEventListener('mousedown', (e) => e.preventDefault());
  list.addEventListener('click', (e) => { const li = e.target.closest('li[data-value]'); if (li) pickSuggest(li.dataset.value); });
}

function findEntry() {
  const cat = currentCatalog();
  if (!cat) return null;
  const v = $('dcNuclide').value.trim().replace(/\s+/g, '').replace(/^([a-z]{1,2})-?(\d+)([a-z]*)$/i, (_, s, a, m) => `${s[0].toUpperCase()}${s.slice(1).toLowerCase()}-${a}${m.toLowerCase()}`);
  return cat.nuclides.find((n) => n.name === v) || null;
}

function nuclideChanged() {
  const e = findEntry();
  state.entry = e;
  const note = $('dcNuclideNote');
  if (!e) {
    note.textContent = $('dcNuclide').value.trim() ? `Not a radionuclide of ${decayLabel(state.decay, state.system)}, the decay data chosen.` : '';
    $('dcForm').replaceChildren();
    $('dcRun').disabled = true;
    describeSoon();
    return;
  }
  const intakes = ['ingestion', 'inhalation', 'injection'].some((r) => e[r]?.length);
  note.textContent = `Half-life ${e.T ? halfLife(e.T) : e.t || '?'}.${intakes ? '' : state.system === '103'
    ? ' External exposure only: the ICRP 103 system has models of intakes for the elements of Publication 158 and the Part 2 and 3 drafts, and nuclides with half-lives of 10 minutes or more.'
    : ' External exposure only: it is not one of the nuclides of ICRP Publication 72.'}`;
  // Routes this nuclide has.
  for (const r of document.querySelectorAll('input[name="dcRoute"]')) {
    r.disabled = !e[r.value]?.length;
    const label = r.closest('label');
    if (r.disabled) label.setAttribute('data-tip', `Not available for ${e.name} in the ${state.system === '60' ? 'ICRP 60' : 'ICRP 103'} system: it has no model of the body there`);
    else label.removeAttribute('data-tip');
  }
  if (!e[route()]?.length) {
    const other = ['ingestion', 'inhalation', 'injection', 'external'].find((r) => e[r]?.length);
    if (other) document.querySelector(`input[name="dcRoute"][value="${other}"]`).checked = true;
  }
  routeSettings();
  populateForms();
}

function populateForms(keep) {
  const e = state.entry;
  const sel = $('dcForm');
  const prev = keep ?? sel.value;
  const forms = e ? e[route()] || [] : [];
  sel.replaceChildren(...forms.map((f) => h('option', { value: f.key }, f.label + (f.default ? ' (default)' : ''))));
  const def = forms.find((f) => f.key === prev) || forms.find((f) => f.default) || forms[0];
  if (def) sel.value = def.key;
  $('dcRun').disabled = !forms.length;
  formChanged();
}

function currentForm() {
  const e = state.entry;
  return e ? (e[route()] || []).find((f) => f.key === $('dcForm').value) || null : null;
}

function formChanged() {
  const f = currentForm();
  const aerosol = route() === 'inhalation' && f && (state.system === '103' ? f.aerosol !== false : /^[FMS]\|/.test(f.key));
  $('dcAmadRow').hidden = !aerosol;
  populateAmad();
  $('dcFormNote').textContent = route() === 'inhalation' && f && !aerosol
    ? 'A gas or vapour: its deposition in the respiratory tract and its absorption are given for the form, so there is no aerosol size.'
    : route() === 'external' && f ? GEOMETRY_NOTE[f.key]?.(state.system) || '' : '';
  describeSoon();
}

/* What each geometry of external exposure is, and per what its coefficients are. */
const GEOMETRY_NOTE = {
  air: () => 'Per Bq per m³ of air: a person standing on uncontaminated ground in a cloud of uniform concentration filling the half-space above it.',
  water: () => 'Per Bq per m³ of water: a person surrounded by water of uniform concentration, as when swimming.',
  surface: (sys) => (sys === '60'
    ? 'Per Bq per m² of ground: a person standing on a smooth plane of uniform activity at the ground’s surface.'
    : 'Per Bq per m² of ground: a person standing on it; the photons come from 3 mm deep (0.5 g/cm², for the ground’s roughness), the electrons from the surface.'),
  soil1: () => 'Per Bq per m³ of soil (1.6 g/cm³), uniform from the surface to 1 cm deep.',
  soil5: () => 'Per Bq per m³ of soil (1.6 g/cm³), uniform from the surface to 5 cm deep.',
  soil15: () => 'Per Bq per m³ of soil (1.6 g/cm³), uniform from the surface to 15 cm deep.',
  soilInf: () => 'Per Bq per m³ of soil (1.6 g/cm³), uniform from the surface down: deep enough that the deepest add nothing.',
};
// Units: PER_TEXT in text given to supText (the page's fonts have no
// superscript minus); rateText where it stays plain, in tips and notes.
const PER_TEXT = { m3: 'per Bq m⁻³', m2: 'per Bq m⁻²' };

/* ---- the chosen system, before any run ---------------------------------------- */
/* The chain, the models and the size of what Calculate would solve: a worker
   assembles the system each time the choice changes (milliseconds: nothing is
   integrated), the settings' foot sums it up, and the Model and Decay chain
   tabs show it until a run of the same choice brings its own. */
let describeTimer = 0;
function describeSoon() {
  markStale();
  refreshInfo();
  clearTimeout(describeTimer);
  describeTimer = setTimeout(describeNow, 50);
}

/* ---- results and the settings they were calculated with --------------------- */
/* A result stays on its tabs when the settings change, so that it can be
   compared with the next; until then it says which settings it is not of,
   and its numbers and charts are dimmed. */
const formOf = (spec) => JSON.stringify(Object.keys(spec).filter((k) => !['nuclide', 'route', 'cutoff', 'amad'].includes(k)).sort().map((k) => [k, spec[k]]));
const ROUTE_WORD = { ingestion: 'ingestion', inhalation: 'inhalation', injection: 'injection', external: 'external exposure' };
/** The settings changed since r was calculated, in words; none when it is of the current ones. */
function changesSince(r) {
  const out = [];
  const s = currentSpec();
  if (r.system !== state.system) out.push(`the system (now ${state.system === '60' ? 'ICRP 60' : 'ICRP 103'})`);
  if ((r.decay || '') !== state.decay) out.push(`the decay data (now ${decayLabel(state.decay, state.system)})`);
  if (!s) out.push('the radionuclide (none chosen now)');
  else {
    // The form, the aerosol and the cut-off only for the same nuclide by the same route.
    if (s.nuclide !== r.spec.nuclide) out.push(`the radionuclide (now ${s.nuclide})`);
    if (s.route !== r.spec.route) out.push(`the route (now ${ROUTE_WORD[s.route]})`);
    else if (r.system === state.system && s.nuclide === r.spec.nuclide) {
      if (formOf(s) !== formOf(r.spec)) out.push(`${s.route === 'external' ? 'the geometry' : 'the form'} (now ${currentForm()?.label || 'another'})`);
      if ((s.amad ?? null) !== (r.spec.amad ?? null)) out.push(`the aerosol size${s.amad != null ? ` (now ${s.amad} µm)` : ''}`);
      if (state.system === '103' && s.cutoff !== r.spec.cutoff) out.push('the decay chain cut-off');
    }
  }
  if (ages().join() !== r.ages.join()) out.push(external(r) ? 'the ages' : 'the ages at intake');
  if (!external(r) && Number($('dcRtol').value) !== r.rtol) out.push('the tolerance');
  return out;
}
const listText = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
/** The notice over a result's tab, or null when it is of the current settings. */
function staleNote(r) {
  const changed = r ? changesSince(r) : [];
  if (!changed.length) return null;
  return h('div', { class: 'dc-stale-note', role: 'status' },
    h('span', {}, h('b', {}, 'Not for the current settings. '),
      `These are the results for ${r.entry.name} (${ROUTE_WORD[r.spec.route]}, ${r.system === '60' ? 'ICRP 60' : 'ICRP 103'}${r.decay ? `, ${decayLabel(r.decay, r.system)}` : ''}); `,
      `since they were calculated, ${listText(changed)} ${changed.length === 1 ? 'has' : 'have'} changed.`),
    h('button', { type: 'button', class: 'dc-btn small', 'data-on-click': 'dc:run', disabled: state.running || !currentSpec() || !ages().length }, 'Calculate'));
}
function markStale() {
  const note = staleNote(state.result);
  for (const [slot, body] of [['dcCoefStale', 'dcCoef'], ['dcRetStale', 'dcRet']]) {
    $(slot).replaceChildren(...(note ? [note.cloneNode(true)] : []));
    $(slot).hidden = !note;
    $(body).classList.toggle('dc-stale', !!note);
  }
  if (state.tab === 'risk') renderRisk();
  if (state.tab === 'chain') renderChain();
}
async function describeNow() {
  const spec = currentSpec(), system = state.system;
  if (!spec) {
    state.described = null;
    renderSize();
    refreshShown();
    return;
  }
  const age = ages()[0] ?? 7300; // the intake differs with age: as a run's first age shows it
  const decay = state.decay;
  const key = choiceKey(system, spec, decay);
  if (state.described?.key === key && state.described.age === age) { renderSize(); return; }
  const d = { key, age, system, decay, spec, entry: state.entry, form: currentForm(), info: null, error: null };
  state.described = d;
  try {
    d.info = await ask({ type: 'describe', system, decay, spec, age }, null, RANK.show);
  } catch (err) {
    d.error = err.message;
  }
  if (state.described !== d) return; // the choice has moved on
  renderSize();
  refreshShown();
  refreshInfo(); // the cut-off's count of nuclides
}
function refreshShown() {
  if (state.tab === 'model') renderModel();
  if (state.tab === 'chain') renderChain();
}
/* What the Model and Decay chain tabs show: the run if it is of the current
   choice (it has the numbers of transformations too), else the current choice
   as described, else the last run. */
function shownSystem() {
  const r = state.result, d = state.described;
  const fromRun = r && { first: r.out[0], run: r, system: r.system, decay: r.decay, spec: r.spec, entry: r.entry, form: r.form, amad: r.amad, ages: r.ages };
  if (r && (!d || d.key === r.key)) return fromRun;
  if (d?.info) return { first: d.info, run: null, system: d.system, decay: d.decay, spec: d.spec, entry: d.entry, form: d.form, amad: d.spec.amad, ages: [d.age] };
  return fromRun || null;
}
function paneHead(id, s) {
  $(id).replaceChildren(headline(s), ...(s.run ? [] : [h('span', { class: 'dc-head-note' }, 'not calculated yet: the model Calculate will solve')]));
}

const count = (n, one, many = `${one}s`) => `${n.toLocaleString('en')} ${n === 1 ? one : many}`;
/* The size of the model in the settings' foot, and each cut-off's number of
   nuclides in its list. */
function renderSize() {
  const box = $('dcSize'), d = state.described;
  for (const o of $('dcCutoff').options) {
    o.dataset.text ??= o.textContent;
    const c = d?.info?.cutoffs?.find((x) => x.cutoff === Number(o.value));
    o.textContent = c ? `${o.dataset.text} (${count(c.nuclides, 'nuclide')})` : o.dataset.text;
  }
  if (!d) { box.hidden = true; return; }
  if (!d.info && !d.error) return; // the last one stays until this one is assembled
  box.hidden = false;
  if (d.error) {
    $('dcSizeSum').textContent = `The model could not be assembled: ${d.error}`;
    $('dcSizeBody').replaceChildren();
    return;
  }
  if (d.info.external) { renderSizeExternal(d); return; }
  const z = d.info.size, n = ages().length * z.perAge;
  $('dcSizeSum').textContent = `${count(z.nuclides, 'nuclide')} · ${count(z.compartments, 'compartment')} · ${count(z.equations, 'equation')}`;
  const dropped = d.info.dropped || [];
  const targets = z.sexes === 2 ? `the ${z.regions} target regions of each sex`
    : z.sexes === 1 ? `the ${z.regions} target regions of one sex` : `the ${z.regions} target regions and the remainder`;
  const rows = [
    ['Chain', `${d.info.members.map((m) => m.name).join(', ')}${dropped.length ? `; left out by the cut-off: ${dropped.join(', ')}` : ''}`],
    ['Transfers', `${count(z.transfers, 'transfer')} between compartments and ${count(z.decays, 'decay')} from one member to the next`],
    ['Equations', `${count(z.compartments, 'activity', 'activities')}, and ${z.perGroup} integrals of activity for each of the ${count(z.groups, 'group')} of compartments that share a source region (${(z.perGroup * z.groups).toLocaleString('en')}); the doses to ${targets} follow from these`],
    ['Matrix', `${count(z.coefficients, 'coefficient')}: the transfer and decay rates, and the weights of the integrals`],
    ['Runs', n ? `${count(n, 'integration')}${z.perAge > 1 ? ', one for each age and sex: the model differs between the sexes' : ', one for each age at intake'}; over 50 years for adults and to age 70 for children; ${Math.min(n, POOL_SIZE)} at a time on this device` : 'none: no age at intake is ticked'],
  ];
  $('dcSizeBody').replaceChildren(h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])));
}

/* External exposure: what Calculate adds up -- the members in equilibrium
   with the parent -- and from which report. */
function renderSizeExternal(d) {
  const chain = d.info.chain, inEq = chain.filter((m, j) => j > 0 && m.ratio > 0), out = chain.filter((m) => m.ratio == null);
  $('dcSizeSum').textContent = `${count(1 + inEq.length, 'nuclide')} with the progeny in equilibrium · ${d.system === '60' ? 'FGR 12' : 'FGR 15'}`;
  const rows = [
    ['Nuclide', `${chain[0].name}: its own photons and electrons, as the report gives a coefficient`],
    ['Progeny', inEq.length ? `${inEq.map((m) => `${m.name} ${sigText(m.ratio)}`).join(', ')} Bq per Bq of ${chain[0].name}, once in equilibrium${d.info.days > 0 ? ` (within 1 % after ${durationText(d.info.days)})` : ''}` : 'none in equilibrium with it'],
    out.length ? ['Not in equilibrium', `${out.map((m) => m.name).join(', ')}: as long-lived as ${chain[0].name} or longer, or formed from one that is`] : null,
    ['Data', d.system === '60' ? 'Federal Guidance Report 12: the adult hermaphrodite phantom, 12 photon energies, ICRP 38 decay data by default'
      : 'Federal Guidance Report 15 (2025): the six phantoms of its reference persons, 13 photon energies, ICRP 107 decay data by default'],
  ].filter(Boolean);
  $('dcSizeBody').replaceChildren(h('dl', {}, rows.flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])));
}
/* A ratio to four figures; a time in the unit that suits it. */
const sigText = (x) => String(Number(x.toPrecision(4)));
function durationText(days) {
  const g2 = (x) => Number(x.toPrecision(2)).toLocaleString('en');
  const y = days / 365.25;
  if (days < 1 / 24) return `${g2(days * 1440)} minutes`;
  if (days < 2) return `${g2(days * 24)} hours`;
  if (days < 730) return `${g2(days)} days`;
  if (y >= 1e9) return `${g2(y / 1e9)} billion years`;
  if (y >= 1e6) return `${g2(y / 1e6)} million years`;
  return `${g2(y)} years`;
}

const AMAD_SIZES = {
  103: [['0.001', '0.001 µm AMTD'], ['0.003', '0.003 µm AMTD'], ['0.01', '0.01 µm AMTD'], ['0.03', '0.03 µm AMTD'], ['0.1', '0.1 µm AMTD'],
    ['0.3', '0.3 µm AMAD'], ['1', '1 µm AMAD (members of the public)'], ['3', '3 µm AMAD'], ['5', '5 µm AMAD (workers)'], ['10', '10 µm AMAD'], ['20', '20 µm AMAD']],
  60: [['0.3', '0.3 µm AMAD'], ['0.5', '0.5 µm AMAD'], ['1', '1 µm AMAD (members of the public)'], ['2', '2 µm AMAD'], ['3', '3 µm AMAD'], ['5', '5 µm AMAD (workers)'], ['10', '10 µm AMAD']],
};
function populateAmad() {
  const sel = $('dcAmad');
  const prev = sel.value || load().amad || '1';
  const sizes = AMAD_SIZES[state.system];
  sel.replaceChildren(...sizes.map(([v, l]) => h('option', { value: v }, l)));
  sel.value = sizes.some(([v]) => v === prev) ? prev : '1';
}

/* ---- running ---------------------------------------------------------------- */
function outputTimes(intakeAges) {
  const tEnd = Math.max(...intakeAges.map((a) => (a < 7300 ? 25550 - a : 18250)));
  const out = [];
  for (let e = -3; ; e += 1 / 10) {
    const t = 10 ** e;
    if (t >= tEnd) break;
    out.push(+t.toPrecision(6));
  }
  return out;
}

/** The calculation the settings ask for, or null while they ask for none. */
function currentSpec() {
  const e = state.entry, f = currentForm();
  if (!e || !f) return null;
  const spec = { nuclide: e.name, route: route(), ...f.spec, cutoff: Number($('dcCutoff').value) };
  if (spec.route === 'external') delete spec.cutoff; // the whole chain, in equilibrium
  if (!$('dcAmadRow').hidden) spec.amad = Number($('dcAmad').value);
  return spec;
}
const choiceKey = (system, spec, decay = '') => JSON.stringify([system, spec, decay || '']);

async function run() {
  const e = state.entry, f = currentForm();
  if (!e || !f) { status('Choose a radionuclide and a form first.', 'error'); return; }
  const as = ages();
  if (!as.length) { status('Tick at least one age at intake.', 'error'); return; }
  const spec = currentSpec();
  const system = state.system, decay = state.decay;
  state.running = true;
  $('dcRun').disabled = true;
  $('dcStop').hidden = false;
  status(`Calculating ${e.name}…`);
  progress(0);
  const t0 = performance.now();
  try {
    // One request per age, to as many workers as there are; the first age's
    // result carries the chain and the models. External exposure takes
    // milliseconds an age: one request.
    const outputs = outputTimes(as), rtol = Number($('dcRtol').value);
    let done = 0;
    const out = spec.route === 'external'
      ? await ask({ type: 'run', system, decay, spec, ages: as }, null, RANK.run)
      : await Promise.all(as.map((age, k) => ask({ type: 'run', system, decay, spec, ages: [age], outputs, rtol, withSystem: k === 0 }, null, RANK.run)
        .then(([o]) => {
          done++;
          status(`Calculating ${e.name}: ${done} of ${as.length} ages done…`);
          progress(done / as.length);
          return o;
        })));
    state.result = { system, decay, spec, form: f, entry: e, ages: as, rtol, out, amad: spec.amad, key: choiceKey(system, spec, decay) };
    progress(null);
    const ms = performance.now() - t0;
    status(`${e.name}: done in ${ms < 100 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`}. ${SYSTEM_LABEL[system]}${spec.route === 'external' ? `, external exposure as ${system === '60' ? 'FGR 12' : 'FGR 15'}` : ''}${decay ? `, decay data ${decayLabel(decay, system)}` : ''}.`, 'ok');
    renderAll();
    writeHash();
    save();
  } catch (err) {
    progress(null);
    status(err.message === 'stopped' ? 'Stopped.' : `Could not calculate: ${err.message}`, err.message === 'stopped' ? '' : 'error');
  } finally {
    state.running = false;
    $('dcRun').disabled = false;
    $('dcStop').hidden = true;
  }
}

/* ---- the coefficients tab ---------------------------------------------------- */
const TISSUE_ORDER_103 = {
  weighted: [['Red marrow', 0.12], ['Colon', 0.12], ['Lung', 0.12], ['Stomach', 0.12], ['Breast', 0.12], ['Gonads', 0.08], ['Bladder', 0.04],
    ['Oesophagus', 0.04], ['Liver', 0.04], ['Thyroid', 0.04], ['Bone surface', 0.01], ['Brain', 0.01], ['Salivary glands', 0.01], ['Skin', 0.01]],
  remainder: ['Adrenals', 'Extrathoracic region', 'Gallbladder', 'Heart', 'Kidneys', 'Lymphatic nodes', 'Muscle', 'Oral mucosa', 'Pancreas',
    'Prostate/uterus', 'Small intestine', 'Spleen', 'Thymus'],
  other: ['Eye lens', 'Ureters'],
};
const TISSUE_ORDER_60 = {
  weighted: [['Gonads', 0.20], ['Red marrow', 0.12], ['Colon', 0.12], ['Lung', 0.12], ['Stomach', 0.12], ['Bladder', 0.05], ['Breast', 0.05],
    ['Liver', 0.05], ['Oesophagus', 0.05], ['Thyroid', 0.05], ['Skin', 0.01], ['Bone surface', 0.01]],
  remainder: ['Adrenals', 'Brain', 'ET', 'Small intestine', 'Kidneys', 'Muscle', 'Pancreas', 'Spleen', 'Thymus', 'Uterus'],
  other: ['Testes', 'Ovaries', 'Upper large intestine', 'Lower large intestine'],
};

/* External exposure's tissues: the reports' phantoms are hermaphrodite. FGR 15
   has the ICRP 103 tissues but the eye lens and ureters, and the testes,
   ovaries, prostate and uterus apart; FGR 12 the ICRP 60 ones but the
   extrathoracic airways, and the gallbladder and the heart besides. */
const TISSUE_ORDER_EXT = {
  103: { ...TISSUE_ORDER_103, other: ['Testes', 'Ovaries', 'Prostate', 'Uterus'] },
  60: { ...TISSUE_ORDER_60, remainder: TISSUE_ORDER_60.remainder.filter((t) => t !== 'ET'), other: [...TISSUE_ORDER_60.other, 'Gallbladder', 'Heart'] },
};
/* Dose rates per second (the reports'), hour or year. */
const RATE = { s: [1, 's'], h: [3600, 'h'], y: [365.25 * 86400, 'y'] };
const rateOf = () => RATE[$('dcRate').value] || RATE.s;
const rateUnit = (per) => `Sv ${rateOf()[1]}⁻¹ ${PER_TEXT[per] || ''}`;
const rateText = (per) => `Sv/${rateOf()[1]} per Bq/m${per === 'm2' ? '²' : '³'}`;
const progenyView = () => document.querySelector('input[name="dcProgeny"]:checked')?.value || 'alone';
const geometryLabel = (r) => r.form?.label || r.spec.geometry;

function headlineText(r) {
  if (external(r)) return `external exposure · ${geometryLabel(r)}`;
  const what = { ingestion: 'ingested', inhalation: 'inhaled', injection: 'taken into blood' }[r.spec.route];
  const amad = r.spec.route === 'inhalation' && r.amad ? `, ${r.amad} µm` : '';
  return `${what} · ${r.form.label}${amad}`;
}
function headline(r) {
  return h('div', { class: 'dc-headline' }, h('b', {}, r.entry.name), ` ${headlineText(r)}`,
    h('span', { class: 'dc-tag' }, r.system === '60' ? 'ICRP 60' : 'ICRP 103'),
    r.decay ? h('span', { class: 'dc-tag', 'data-decay': r.decay }, `decay data ${decayLabel(r.decay, r.system)}`) : null);
}

/* What each row of the tissue table adds to e, as a fraction of it: the
   weighted tissues and the remainder are its terms (solid bars, adding up to
   the whole); the remainder's tissues, and the testes and ovaries behind the
   gonads, the two halves of the colon and the prostate and uterus, are parts
   of a term (light bars). The remainder's tissues share it equally in the
   ICRP 103 system, by mass in the ICRP 60 system (the engines' shares, which
   follow the masses as a child grows and the splitting rule). In the ICRP 103
   system's Male and Female views each bar is that sex's half of the term, as
   e averages the sexes. Rows outside e (eye lens, ureters, gallbladder,
   heart) and the gonad not taken in the ICRP 60 system get none. */
function eSharesOf(r, o, view = 'avg', withProgeny = false) {
  const out = new Map();
  const ext = external(r), sixty = r.system === '60';
  const src = ext && withProgeny ? o.progeny : o;
  const E = src.E;
  if (!(E > 0)) return out;
  const order = ext ? TISSUE_ORDER_EXT[r.system] : sixty ? TISSUE_ORDER_60 : TISSUE_ORDER_103;
  const byView = !ext && !sixty;
  const H = byView ? o.H[view === 'avg' ? 'avg' : view] : src.H;
  const half = byView && view !== 'avg' ? 0.5 : 1;
  const set = (name, v, part = null) => { if (v > 0) out.set(name, { v: half * v / E, part }); };
  for (const [n, w] of order.weighted) set(n, w * H[n]);
  const wRem = sixty ? 0.05 : 0.12;
  set('Remainder', wRem * H.Remainder);
  for (const n of order.remainder) set(n, wRem * (sixty ? src.remainderShares?.[n] : H[n] / order.remainder.length), 'the remainder');
  if (sixty) {
    const g = src.gonads || (H.Testes >= H.Ovaries ? 'Testes' : 'Ovaries');
    set(g, 0.20 * H[g], 'the gonads');
    set('Upper large intestine', 0.12 * 0.57 * H['Upper large intestine'], 'the colon');
    set('Lower large intestine', 0.12 * 0.43 * H['Lower large intestine'], 'the colon');
  } else if (ext) {
    set('Testes', 0.04 * H.Testes, 'the gonads');
    set('Ovaries', 0.04 * H.Ovaries, 'the gonads');
    set('Prostate', 0.06 / 13 * H.Prostate, 'the remainder (prostate/uterus)');
    set('Uterus', 0.06 / 13 * H.Uterus, 'the remainder (prostate/uterus)');
  }
  return out;
}
/* The tissue table's shares at each age; a bar fills as much of its cell as
   its tissue's share of e, the whole cell being all of e. */
function tableShares(r, out, view, withProgeny) {
  if (!sharesOn()) return null;
  return { maps: out.map((o) => eSharesOf(r, o, view, withProgeny)) };
}
/* A cell of the tissue table, with its bar when the switch is on. */
function shareCell(td, shares, k, name) {
  const share = shares?.maps[k].get(name);
  if (!share) return td;
  td.classList.add('dc-share');
  if (share.part) td.classList.add('part');
  td.style.setProperty('--share', `${Math.min(100, 100 * share.v).toFixed(2)}%`);
  td.dataset.share = share.v.toPrecision(8);
  td.setAttribute('data-tip', `${percent(100 * share.v)} of e${share.part ? `, a part of ${share.part}` : ''}`);
  return td;
}
const sharesOn = () => !!$('dcShares')?.checked;
const sharesNote = () => 'Bars: each tissue’s share of e at that age, the cell’s width being all of e (pointing at a cell gives its share); solid for the terms of e (the weighted tissues and the remainder, which add up to the whole), light for their parts (the remainder’s tissues; the testes and ovaries of the gonads; the halves of the colon).';

function renderCoef() {
  const r = state.result;
  $('dcCoefEmpty').hidden = !!r;
  $('dcCoef').hidden = !r;
  if (!r) return;
  $('dcHeadline').replaceWith(Object.assign(headline(r), { id: 'dcHeadline' }));
  $('dcRateLabel').hidden = !external(r);
  $('dcProgenyBar').hidden = !external(r);
  if (external(r)) { renderCoefExternal(r); return; }
  $('dcHHead').replaceChildren('Committed equivalent dose ', h('span', { class: 'dc-unit' }, 'Sv per Bq'));
  const d = digits();
  const out = r.out;
  // Effective dose by age.
  const period = (o) => (o.intakeAge < 7300 ? `to age 70 (${+((25550 - o.intakeAge) / 365).toFixed(2)} y)` : '50 years');
  const et = $('dcETable');
  et.replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Age at intake'), h('th', {}, 'e(τ), Sv per Bq'), h('th', { class: 'text' }, 'Commitment period'),
      r.system === '60' ? h('th', { class: 'text' }, 'Remainder') : null, h('th', {}, 'Time'))),
    h('tbody', {}, out.map((o) => h('tr', {},
      h('td', {}, AGE_LABEL[o.age] + (o.intakeAge !== o.age ? ` (${o.intakeAge / 365} y)` : '')),
      h('td', { class: 'big' }, sci(o.E, d)),
      h('td', { class: 'text' }, period(o)),
      r.system === '60' ? h('td', { class: 'text dim' }, o.split ? `split: ${o.split} takes half` : 'mass-weighted') : null,
      h('td', { class: 'dim' }, `${(o.ms / 1000).toFixed(1)} s`)))));
  // Equivalent doses.
  const order = r.system === '60' ? TISSUE_ORDER_60 : TISSUE_ORDER_103;
  const sex = sexView();
  $('dcSexBar').hidden = r.system !== '103';
  const Hof = (o, name) => (r.system === '60' ? o.H[name] : o.H[sex === 'avg' ? 'avg' : sex][name]);
  const shares = tableShares(r, out, sex);
  const row = (name, w, cls) => h('tr', { class: cls }, h('td', {}, name, w != null ? h('span', { class: 'dc-w' }, `  wT ${w}`) : null),
    out.map((o, k) => shareCell(h('td', {}, sci(Hof(o, name), d)), shares, k, name)));
  const group = (text) => h('tr', { class: 'group' }, h('td', { colspan: out.length + 1 }, text));
  const ht = $('dcHTable');
  ht.replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Tissue'), out.map((o) => h('th', {}, AGE_LABEL[o.age])))),
    h('tbody', {},
      group(r.system === '60' ? 'Tissues with a weighting factor (ICRP 60)' : 'Tissues with a weighting factor (ICRP 103)'),
      order.weighted.map(([n, w]) => row(n, w)),
      group(r.system === '60' ? 'Remainder (wT 0.05: mass-weighted mean, or the splitting rule)' : 'Remainder (wT 0.12: arithmetic mean of the 13 tissues of each sex)'),
      order.remainder.map((n) => row(n === 'Prostate/uterus' && sex === 'M' ? 'Prostate/uterus' : n)),
      row('Remainder', r.system === '60' ? 0.05 : 0.12, 'sum'),
      group('Other tissues'),
      order.other.map((n) => row(n)),
      h('tr', { class: 'sum' }, h('td', {}, 'Effective dose'), out.map((o) => h('td', {}, sci(o.E, d))))));
  // Notes.
  const notes = new Set(out.flatMap((o) => o.notes || []));
  const items = [...notes].map((n) => h('li', {}, n));
  const share = out[0].progenyShare || 0;
  if (r.system === '103' && share >= 0.1) {
    // Progeny of another element whose model no OIR section here gives.
    const el0 = out[0].members?.[0]?.name.split('-')[0];
    const mem = out[0].members || [];
    const elOf = (m) => m.name.split('-')[0];
    const approx = mem.some((m, j) => j > 0 && elOf(m) !== el0 && (['independent', 'independent-fallback', 'gas-progeny-fallback'].includes(m.kind)
      || (m.kind === 'mirror' && m.of != null && elOf(mem[m.of]) !== elOf(m))));
    items.unshift(h('li', { class: 'dc-caution' }, approx
      ? `${Math.round(100 * share)} % of the energy this chain emits in 50 years comes from progeny of other elements, and the parent element’s section of the OIR series gives no model for some of them, so the page uses general rules (Help: “Progeny”). The result can differ from the ICRP’s by more than the rounding of its tables.`
      : `${Math.round(100 * share)} % of the energy this chain emits in 50 years comes from progeny of other elements. They follow the models of the parent element’s section of the OIR series (Help: “Progeny”), with which this page reproduces the ICRP’s coefficients for nearly every chain; the Help lists the few that still differ.`));
  }
  if (r.system === '103') items.push(h('li', {}, 'Effective dose: the average of the male and female equivalent doses, weighted by the tissue weighting factors of Publication 103. “Gonads” are the testes for males and the ovaries for females, “Prostate/uterus” the prostate for males and the uterus for females.'));
  else items.push(h('li', {}, 'Effective dose: the tissue weighting factors of Publication 60; gonads the higher of testes and ovaries; colon 0.57 upper + 0.43 lower large intestine; oesophagus the thymus dose, as in ICRP 72.'));
  if (shares) items.push(h('li', {}, `${sharesNote(shares)}${r.system === '103' && sex !== 'avg' ? ` In the ${sex === 'M' ? 'Male' : 'Female'} view each bar is that sex’s half of the term, as e averages the sexes.` : ''}${r.system === '60' ? ' The remainder’s tissues share it by their masses, which change as a child grows, or by the splitting rule.' : ''}`));
  $('dcNotes').replaceChildren(h('ul', {}, items));
}

/* External exposure: the effective dose rate at each age, of the nuclide alone
   and with its progeny in equilibrium (and in the ICRP 60 system FGR 12's
   H_E), what it comes from, and the tissues' equivalent dose rates. */
function renderCoefExternal(r) {
  const d = digits(), [f] = rateOf(), out = r.out, sixty = r.system === '60';
  const unit = rateUnit(out[0].per);
  const share = (x, tot) => (tot > 0 ? percent(100 * x / tot) : '–');
  $('dcETable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Age'), h('th', {}, ...supText(`e, ${unit}`)), h('th', {}, 'with its progeny'),
      sixty ? h('th', { 'data-tip': 'The effective dose equivalent of ICRP 26, which Federal Guidance Report 12 tabulates' }, 'H', h('sub', {}, 'E'), ', as FGR 12') : null,
      sixty ? h('th', {}, 'with its progeny') : null,
      h('th', {}, 'Skin'), h('th', { class: 'text' }, 'e from photons · bremsstrahlung · electrons'))),
    h('tbody', {}, out.map((o) => h('tr', {},
      h('td', {}, ageLabel(o.age, true)),
      h('td', { class: 'big' }, sci(o.E * f, d)),
      h('td', {}, sci(o.progeny.E * f, d)),
      sixty ? h('td', {}, sci(o.HE * f, d)) : null,
      sixty ? h('td', {}, sci(o.progeny.HE * f, d)) : null,
      h('td', {}, sci(o.H.Skin * f, d)),
      h('td', { class: 'text dim' }, `${share(o.parts.photon.E, o.E)} · ${share(o.parts.brems.E, o.E)} · ${share(o.parts.electron.E, o.E)}`)))));
  const order = TISSUE_ORDER_EXT[r.system];
  const withP = progenyView() === 'with';
  $('dcSexBar').hidden = true;
  $('dcHHead').replaceChildren(`Equivalent dose rate${withP ? ', with the progeny in equilibrium' : ''} `, h('span', { class: 'dc-unit' }, ...supText(unit)));
  const Hof = (o, name) => (withP ? o.progeny.H : o.H)[name];
  const shares = tableShares(r, out, 'avg', withP);
  const row = (name, w, cls) => h('tr', { class: cls }, h('td', {}, name, w != null ? h('span', { class: 'dc-w' }, `  wT ${w}`) : null),
    out.map((o, k) => shareCell(h('td', {}, sci(Hof(o, name) * f, d)), shares, k, name)));
  const group = (text) => h('tr', { class: 'group' }, h('td', { colspan: out.length + 1 }, text));
  $('dcHTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Tissue'), out.map((o) => h('th', {}, ageLabel(o.age, true))))),
    h('tbody', {},
      group(sixty ? 'Tissues with a weighting factor (ICRP 60)' : 'Tissues with a weighting factor (ICRP 103)'),
      order.weighted.map(([n, w]) => row(n, w)),
      group(sixty ? 'Remainder (wT 0.05: mass-weighted mean, or the splitting rule; no extrathoracic airways in the phantom)' : 'Remainder (wT 0.12: arithmetic mean of the 13 tissues)'),
      order.remainder.map((n) => row(n)),
      row('Remainder', sixty ? 0.05 : 0.12, 'sum'),
      group('Other tissues'),
      order.other.map((n) => row(n)),
      h('tr', { class: 'sum' }, h('td', {}, 'Effective dose rate'), out.map((o) => h('td', {}, sci((withP ? o.progeny.E : o.E) * f, d))))));
  // Notes: the method, the progeny, the units.
  const first = out[0], chain = first.chain || [];
  const inEq = (first.members || []).filter((m, j) => j > 0 && m.ratio > 0);
  const notIn = (first.members || []).filter((m) => m.ratio == null).map((m) => m.name);
  const items = [
    h('li', {}, ...supText(`Dose rate coefficients for external exposure: the equivalent dose rate to each tissue, and the effective dose rate, per unit concentration in ${GEOMETRY_PLACE[r.spec.geometry]}, ${unit}. They are calculated here from the decay data as ${sixty ? 'Federal Guidance Report 12 (1993)' : 'Federal Guidance Report 15 (2025 revision)'} calculates them: each photon’s dose from the report’s monoenergetic coefficients, the bremsstrahlung of the beta particles slowing down in ${r.spec.geometry === 'air' ? 'air' : r.spec.geometry === 'water' ? 'water' : 'soil'}, and the electrons’ dose to the skin (Help: “External exposure”).`)),
    h('li', {}, sixty
      ? 'Effective dose rate: the tissue weighting factors of Publication 60 with the remainder of Publication 72, mass-weighted with its splitting rule, without the extrathoracic airways that FGR 12’s phantom does not have; gonads the higher of testes and ovaries, colon 0.57 upper + 0.43 lower large intestine, the skin (wT 0.01) with its electrons. HE: the effective dose equivalent of ICRP 26 that FGR 12 gives (gonads 0.25, breast 0.15, red marrow and lung 0.12, thyroid and bone surface 0.03, the five highest of the other organs 0.06 each, the skin left out).'
      : 'Effective dose rate: the tissue weighting factors of Publication 103 on FGR 15’s hermaphrodite phantoms: gonads the mean of testes and ovaries, prostate/uterus the mean of the two, the remainder the mean of its 13 tissues, the skin (wT 0.01) with its electrons. The adult is FGR 15’s reference adult (the adult phantom for the male, the 15-year-old’s for the female).'),
    h('li', {}, inEq.length
      ? `With its progeny: ${inEq.map((m) => `${m.name} (${sigText(m.ratio)} Bq per Bq)`).join(', ')}, their activities once in equilibrium with ${r.entry.name}${first.days > 0 ? `, within 1 % after ${durationText(first.days)}` : ''}${notIn.length ? `; not ${notIn.join(', ')}, which never are` : ''}. The reports’ own coefficients are of the nuclide alone. The Decay chain tab has each member’s share.`
      : `${r.entry.name} has no progeny in equilibrium with it${notIn.length ? ` (${notIn.join(', ')} ${notIn.length === 1 ? 'lives' : 'live'} as long or longer, or ${notIn.length === 1 ? 'is' : 'are'} formed from one that does)` : ''}: with its progeny is the nuclide alone.`),
  ];
  if (chain.length === 0 && !first.members) items.pop();
  const splits = out.filter((o) => (withP ? o.progeny.split : o.split));
  if (sixty && splits.length) items.push(h('li', {}, `The remainder is split at ${splits.map((o) => ageLabel(o.age, true).toLowerCase()).join(', ')}: ${(withP ? splits[0].progeny.split : splits[0].split)} takes half of its weight.`));
  if (shares) items.push(h('li', {}, `${sharesNote(shares)}${sixty ? ' The remainder’s tissues share it by their adult masses, or by the splitting rule.' : ' The remainder’s tissues share it equally; the prostate and the uterus each half of their row’s share.'}`));
  $('dcNotes').replaceChildren(h('ul', {}, items));
}
const GEOMETRY_PLACE = { air: 'the air', water: 'the water', surface: 'the ground’s surface', soil1: 'the top 1 cm of soil', soil5: 'the top 5 cm of soil', soil15: 'the top 15 cm of soil', soilInf: 'soil, to any depth' };

function csv() {
  const r = state.result;
  if (!r) return;
  if (external(r)) { csvExternal(r); return; }
  const cell = (v) => (typeof kvotCsvCell === 'function' ? kvotCsvCell(v) : String(v));
  const lines = [];
  lines.push(['Nuclide', r.entry.name, 'Route', r.spec.route, 'Form', r.form.label, 'System', SYSTEM_LABEL[r.system], 'Decay data', decayLabel(r.decay, r.system)].map(cell).join(','));
  lines.push(['Quantity', ...r.out.map((o) => AGE_LABEL[o.age])].map(cell).join(','));
  lines.push(['Committed effective dose (Sv/Bq)', ...r.out.map((o) => o.E.toPrecision(6))].map(cell).join(','));
  const names = r.system === '60' ? Object.keys(r.out[0].H) : Object.keys(r.out[0].H.avg);
  for (const n of names) {
    if (r.system === '60') lines.push([`H ${n} (Sv/Bq)`, ...r.out.map((o) => o.H[n].toPrecision(6))].map(cell).join(','));
    else for (const s of ['avg', 'M', 'F']) lines.push([`H ${n}${s === 'avg' ? '' : s === 'M' ? ' male' : ' female'} (Sv/Bq)`, ...r.out.map((o) => o.H[s][n].toPrecision(6))].map(cell).join(','));
  }
  saveText(lines, `dose-${r.entry.name}-${r.spec.route}-${r.system}.csv`);
}
function saveText(lines, name) {
  const blob = new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv' });
  const a = h('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
/* External exposure: e and every tissue's dose rate at every age, alone and
   with the progeny, in the unit the tab shows. */
function csvExternal(r) {
  const cell = (v) => (typeof kvotCsvCell === 'function' ? kvotCsvCell(v) : String(v));
  const [f, per] = rateOf(), unit = `Sv/${per} per Bq/${r.out[0].per === 'm2' ? 'm2' : 'm3'}`;
  const line = (xs) => xs.map(cell).join(',');
  const lines = [
    line(['Nuclide', r.entry.name, 'Route', 'external exposure', 'Geometry', geometryLabel(r), 'System', SYSTEM_LABEL[r.system], 'Decay data', decayLabel(r.decay, r.system), 'Unit', unit]),
    line(['Quantity', ...r.out.map((o) => ageLabel(o.age, true))]),
  ];
  const num = (x) => (x * f).toPrecision(6);
  lines.push(line([`Effective dose rate e (${unit})`, ...r.out.map((o) => num(o.E))]));
  lines.push(line([`Effective dose rate e with the progeny in equilibrium (${unit})`, ...r.out.map((o) => num(o.progeny.E))]));
  if (r.system === '60') {
    lines.push(line([`Effective dose equivalent HE, ICRP 26 (${unit})`, ...r.out.map((o) => num(o.HE))]));
    lines.push(line([`Effective dose equivalent HE with the progeny (${unit})`, ...r.out.map((o) => num(o.progeny.HE))]));
  }
  for (const n of Object.keys(r.out[0].H)) {
    lines.push(line([`H ${n} (${unit})`, ...r.out.map((o) => num(o.H[n]))]));
    lines.push(line([`H ${n} with the progeny (${unit})`, ...r.out.map((o) => num(o.progeny.H[n]))]));
  }
  saveText(lines, `dose-${r.entry.name}-external-${r.spec.geometry}-${r.system}.csv`);
}

/* ---- charts ----------------------------------------------------------------- */
function plotTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (n, d) => css.getPropertyValue(n).trim() || d;
  return { text: v('--text-primary', '#352921'), muted: v('--text-muted', '#786b5d'), grid: v('--border-color', '#e0d7ce'), bg: v('--bg-primary', '#fff') };
}
/* The colours come from the theme when the chart is drawn, so a theme change
   redraws the charts (kvot-theme-change, at the end of this file). The
   backgrounds are the pane's colour, not transparent: Plotly lays a band of
   the background under the line that follows the pointer, and makes it white
   when the backgrounds are transparent, which shows in the dark theme. */
function layout(title, ytitle, xtitle = 'Time after intake (days)') {
  const t = plotTheme();
  return {
    title: { text: title, font: { size: 13, color: t.text } }, paper_bgcolor: t.bg, plot_bgcolor: t.bg,
    font: { family: 'verdana, sans-serif', size: 11, color: t.text },
    xaxis: { type: 'log', title: xtitle, gridcolor: t.grid, zerolinecolor: t.grid, linecolor: t.grid, exponentformat: 'power', spikecolor: t.muted, spikethickness: 1 },
    yaxis: { type: 'log', title: ytitle, gridcolor: t.grid, zerolinecolor: t.grid, linecolor: t.grid, exponentformat: 'power' },
    margin: { l: 70, r: 16, t: 36, b: 48 }, legend: { orientation: 'h', y: -0.22 }, hovermode: 'x unified',
    modebar: { bgcolor: 'rgba(0,0,0,0)', color: t.muted, activecolor: t.text },
  };
}
/* The values at the pointer, largest first. Plotly's own box for 'x unified'
   lists the traces in their order, always; so it is hidden (the stylesheet:
   with hoverinfo 'none' Plotly would leave out the line at the pointer too)
   and this box, in the page's tooltip style, takes its place. */
let plotTip = null;
function timeText(days) {
  const g3 = (x) => String(Number(x.toPrecision(3)));
  if (days < 1 / 24) return `${g3(days * 1440)} minutes`;
  if (days < 1) return `${g3(days * 24)} hours`;
  return days < 365 ? `${g3(days)} days` : `${g3(days)} days (${g3(days / 365.25)} years)`;
}
function showPlotTip(ev) {
  const near = (ev.points || []).filter((p) => Number.isFinite(p.y) && Number.isFinite(p.x));
  if (!near.length) { hidePlotTip(); return; }
  // A trace without a value at this time offers its nearest one: left out.
  const x = near[0].x;
  const rows = near.filter((p) => p.x === x).sort((a, b) => b.y - a.y || a.curveNumber - b.curveNumber);
  if (!plotTip) {
    plotTip = h('div', { class: 'dc-tip dc-plot-tip', role: 'tooltip' });
    document.body.append(plotTip);
    window.addEventListener('scroll', hidePlotTip, true);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hidePlotTip(); });
  }
  // A curve that is a part of a total carries its share of it, per point
  // (sharesOf): shown dimmed, in brackets.
  const shares = rows.some((p) => Number.isFinite(p.customdata));
  const table = h('table');
  for (const p of rows) {
    const key = h('span', { class: 'dc-plot-key' });
    key.style.background = p.fullData?.line?.color || '';
    table.append(h('tr', {}, h('td', {}, key), h('td', {}, p.data.name), h('td', { class: 'num' }, sci(p.y, 3)),
      shares ? h('td', { class: 'pct' }, Number.isFinite(p.customdata) ? `(${percent(p.customdata)})` : '') : null));
  }
  plotTip.replaceChildren(h('div', { class: 'dc-plot-tip-time' }, `${timeText(x)} after intake`), table);
  plotTip.classList.add('on');
  // Beside the pointer, on the side with room, and inside the window.
  const e = ev.event, r = plotTip.getBoundingClientRect();
  const box = e?.target?.closest?.('.js-plotly-plot')?.getBoundingClientRect();
  const cx = Number.isFinite(e?.clientX) ? e.clientX : (box ? box.left + box.width / 2 : 0);
  const cy = Number.isFinite(e?.clientY) ? e.clientY : (box ? box.top + box.height / 2 : 0);
  let left = cx + 16;
  if (left + r.width > innerWidth - 8) left = cx - 16 - r.width;
  const top = Math.min(cy - r.height / 2, innerHeight - r.height - 8);
  plotTip.style.left = `${Math.round(Math.max(8, left))}px`;
  plotTip.style.top = `${Math.round(Math.max(8, top))}px`;
}
function hidePlotTip() { plotTip?.classList.remove('on'); }
const percent = (v) => (v >= 99.95 ? '100 %' : v > 99 ? `${v.toFixed(1)} %` : v >= 10 ? `${v.toFixed(0)} %` : v >= 1 ? `${v.toFixed(1)} %` : v >= 0.01 ? `${v.toFixed(2)} %` : '< 0.01 %');
/** Each value of a part as a percentage of the total at the same time, for the hover box. */
const sharesOf = (ys, total) => ys.map((y, i) => (total[i] > 0 && y > 0 ? 100 * y / total[i] : null));
const hooked = new WeakSet();
function plotWithTip(id, traces, lay, cfg) {
  const el = $(id);
  Plotly.react(el, traces, lay, cfg);
  if (hooked.has(el)) return; // Plotly keeps an element's handlers from one react to the next
  hooked.add(el);
  el.on('plotly_hover', showPlotTip);
  el.on('plotly_unhover', hidePlotTip);
}
const positive = (ys) => ys.map((y) => (y > 1e-30 ? y : null));
/* A log axis from six decades under the highest value to just above it. */
function logRange(traces, decades = 6) {
  let top = 0;
  for (const t of traces) for (const y of t.y) if (y > top) top = y;
  if (!(top > 0)) return undefined;
  const hi = Math.log10(top) + 0.15;
  return [hi - decades - 0.15, hi];
}
const atAge = (age) => (age >= 7300 ? 'as an adult' : `at ${AGE_LABEL[age].toLowerCase()}`);
function renderRetention() {
  const r = state.result;
  const ext = external(r);
  $('dcRetEmpty').textContent = ext
    ? 'External exposure takes nothing into the body: its coefficients are dose rates per unit concentration outside it, with no retention, excretion or commitment period. The Model tab shows the dose per photon and electron that they are made of.'
    : 'Retention, excretion and how the dose builds up after the intake appear here once calculated.';
  $('dcRetEmpty').hidden = !!r && !ext;
  $('dcRet').hidden = !r || ext;
  if (!r || ext || typeof Plotly === 'undefined') return;
  const sel = $('dcRetAge');
  const prev = sel.value;
  sel.replaceChildren(...r.out.map((o, k) => h('option', { value: k }, AGE_LABEL[o.age])));
  sel.value = prev && prev < r.out.length ? prev : String(r.out.length - 1);
  const o = r.out[Number(sel.value)];
  const s = o.series;
  if (!s) return;
  // One nuclide at a time: activities of different nuclides are not added
  // up. All per Bq of the parent taken in.
  const nsel = $('dcRetNuclide');
  const prevN = nsel.value;
  nsel.replaceChildren(...s.members.map((m, k) => h('option', { value: k }, k === 0 ? `${m}, taken in` : m)));
  nsel.value = prevN && Number(prevN) < s.members.length ? prevN : '0';
  const m = Number(nsel.value), name = s.members[m], parent = r.entry.name;
  // A model that differs between the sexes (radon): the activities are the male model's.
  const when = `${atAge(o.age)}${s.model === 'male' ? ' (male model)' : ''}`;
  const what = $('dcRetWhat').value;
  const t = s.times;
  const shown = (entries) => entries.filter(([, ys]) => ys.some((y) => y > 1e-30));
  let traces, title;
  if (what === 'members') {
    traces = s.members.map((mm, k) => ({ x: t, y: positive(s.byMember[k]), name: mm, mode: 'lines' }));
    title = `Activity of each chain member in the body after an intake of 1 Bq of ${parent} ${when}`;
  } else if (what === 'regions') {
    // Shares of the nuclide's activity in the whole body, drawn or not.
    const top = shown(Object.entries(s.byRegion[m] || {})).sort((a, b) => Math.max(...b[1]) - Math.max(...a[1])).slice(0, 14);
    traces = top.map(([k, ys]) => ({ x: t, y: positive(ys), name: k, mode: 'lines', customdata: sharesOf(ys, s.byMember[m]) }));
    title = `Activity of ${name} in its source regions after an intake of 1 Bq of ${parent} ${when}`;
  } else {
    const g = s.byGroup[m] || {};
    const total = t.map((_, i) => Object.values(g).reduce((a, ys) => a + ys[i], 0));
    traces = shown(Object.entries(g)).map(([k, ys]) => ({ x: t, y: positive(ys), name: k, mode: 'lines', customdata: sharesOf(ys, total) }));
    traces.unshift({ x: t, y: positive(total), name: 'Whole body', mode: 'lines', line: { width: 3 } });
    title = `Activity of ${name} in the body after an intake of 1 Bq of ${parent} ${when}`;
  }
  const cfg = { responsive: true, displaylogo: false };
  const withRange = (lay, tr, dec) => { lay.yaxis.range = logRange(tr, dec); return lay; };
  plotWithTip('dcPlotRet', traces, withRange(layout(title, 'Bq per Bq taken in'), traces, 6), cfg);
  const excreted = t.map((_, i) => s.urine[m][i] + s.faeces[m][i]);
  const exc = [
    { x: t, y: positive(s.urine[m]), name: 'Urine', mode: 'lines', customdata: sharesOf(s.urine[m], excreted) },
    { x: t, y: positive(s.faeces[m]), name: 'Faeces', mode: 'lines', customdata: sharesOf(s.faeces[m], excreted) },
  ];
  plotWithTip('dcPlotExc', exc, withRange(layout(`Daily excretion of ${name} after an intake of 1 Bq of ${parent}`, 'Bq per day per Bq taken in'), exc, 7), cfg);
  // The effective dose and the curves it is the sum of: the twelve largest
  // (as committed) and the rest together.
  const split = $('dcRetSplit').value;
  const eT = [{ x: t, y: positive(s.E), name: 'e(t), all', mode: 'lines', line: { width: 3 } }];
  const parts = split === 'none' ? null : s.dose?.[split];
  if (parts) {
    const last = (ys) => ys[ys.length - 1];
    const ranked = shown(Object.entries(parts)).sort((a, b) => last(b[1]) - last(a[1]));
    for (const [k, ys] of ranked.slice(0, 12)) eT.push({ x: t, y: positive(ys), name: k, mode: 'lines', customdata: sharesOf(ys, s.E) });
    const rest = ranked.slice(12);
    if (rest.length) {
      const ys = t.map((_, i) => rest.reduce((a, [, v]) => a + v[i], 0));
      eT.push({ x: t, y: positive(ys), name: `${rest.length} more together`, mode: 'lines', line: { dash: 'dot' }, customdata: sharesOf(ys, s.E) });
    }
  }
  const by = { region: 'body region of the activity', source: 'source region of the activity', member: 'chain member', tissue: 'tissue receiving it' }[split];
  plotWithTip('dcPlotDose', eT, withRange(layout(`Committed effective dose received up to each time${parts ? `, and its parts by ${by}` : ''}`, 'Sv per Bq'), eT, 5), cfg);
}
function resizePlots() {
  if (typeof Plotly === 'undefined' || $('pane-retention').hidden) return;
  for (const id of ['dcPlotRet', 'dcPlotExc', 'dcPlotDose']) { const el = $(id); if (el?.data) Plotly.Plots.resize(el); }
}

/* ---- the model tab ------------------------------------------------------------ */
function rateAt(ages, rates, age) {
  if (!ages || ages.length !== rates.length || rates.length === 1) return rates[rates.length === 1 ? 0 : rates.length - 1];
  if (age <= ages[0]) return rates[0];
  if (age >= ages[ages.length - 1]) return rates[rates.length - 1];
  let i = 0;
  while (age > ages[i + 1]) i++;
  return rates[i] + (rates[i + 1] - rates[i]) * (age - ages[i]) / (ages[i + 1] - ages[i]);
}
function renderModel() {
  const r = shownSystem();
  $('dcModelEmpty').hidden = !!r;
  $('dcModel').hidden = !r;
  if (!r) return;
  paneHead('dcModelHead', r);
  const ext = !!r.first?.external;
  for (const id of ['dcModelMember', 'dcModelShow']) $(id).closest('label').hidden = ext;
  $('dcModelAge').closest('label').firstChild.textContent = ext ? 'Age ' : 'Age at intake ';
  $('dcModelDose').hidden ||= ext;
  $('dcModelFrom').hidden ||= ext;
  $('dcBuckets').hidden ||= ext;
  $('dcTransfers').closest('.dc-table-wrap').hidden = ext;
  $('dcTransfers').closest('.dc-table-wrap').previousElementSibling.hidden = ext;
  if (ext) { renderModelExternal(r); return; }
  const first = r.first;
  const msel = $('dcModelMember');
  const prevM = msel.value;
  msel.replaceChildren(...first.models.map((m, k) => h('option', { value: k }, `${m.member}${k === 0 ? ' (parent)' : ''}`)));
  msel.value = prevM && prevM < first.models.length ? prevM : '0';
  const model = first.models[Number(msel.value)];
  // What the drawing shows: the model, or after a calculation its boxes filled.
  const shown = viewShown(r, model);
  const ssel = $('dcModelShow');
  for (const o of ssel.options) {
    o.dataset.text ??= o.textContent;
    o.disabled = o.value !== 'model' && shown === 'model' && !(fillable(r) && model.compartments.length);
    o.textContent = o.disabled && !fillable(r) ? `${o.dataset.text} (after Calculate)` : o.dataset.text;
  }
  ssel.value = shown;
  $('dcModelDose').value = VIEW.dose;
  $('dcModelFrom').value = VIEW.from;
  $('dcModelDose').hidden = shown !== 'dose';
  $('dcModelFrom').hidden = shown !== 'dose' || first.models.length < 2;
  // The age of the rates on the arrows, and the age at intake of what fills
  // the boxes: then one of the ages the calculation has.
  const asel = $('dcModelAge');
  const done = shown === 'model' ? REF_AGES : r.run.ages;
  const near = (a) => done.reduce((b, x) => (Math.abs(REF_AGES.indexOf(x) - REF_AGES.indexOf(a)) < Math.abs(REF_AGES.indexOf(b) - REF_AGES.indexOf(a)) ? x : b), done[done.length - 1]);
  const chosen = near(VIEW.age ?? 7300); // the age last chosen, or adults
  asel.replaceChildren(...REF_AGES.map((a) => h('option', { value: a, disabled: !done.includes(a) }, `${AGE_LABEL[a]}${done.includes(a) ? '' : ' (not calculated)'}`)));
  asel.value = String(chosen);
  const age = chosen === 7300 ? (first.spec.adultAge || 7300) : chosen;
  const text = [];
  if (model.label) {
    const where = [model.table && !model.label.includes(model.table) ? model.table : null, model.source || null, model.file ? `DCAL file ${model.file}` : null].filter(Boolean).join(', ');
    text.push(h('p', {}, h('b', {}, model.label), where ? ` (${where})` : ''));
  }
  const kinds = {
    parent: 'The parent’s own systemic model.', independent: 'Independent kinetics: this progeny follows its own element’s model after it is produced in the body or absorbed to blood.',
    mirror: `Shared kinetics: it moves with ${model.of || 'the member it comes from'}, whose model this is.`, gas: 'A noble gas produced in the body.',
    shared: 'Shared kinetics: the parent’s model.', 'own model': 'Its own model, as DCAL’s batch files assign it for this chain.',
    spec: 'Independent kinetics, with the model that the parent element’s section of the OIR series (Publications 134, 137, 141, 151) gives this element as a progeny: where it is formed in a compartment this model has, it is in that compartment; elsewhere it moves to its blood at the rates that section gives.',
    decay: 'It decays where it is formed (OIR series).',
  };
  if (kinds[model.kind]) text.push(h('p', {}, kinds[model.kind]));
  if (model.entry) text.push(h('p', {}, `Activity absorbed to blood enters “${model.entry}”. Hover over an arrow for its transfer coefficient at ${AGE_LABEL[chosen] === 'Adult' ? 'adult age' : `the age of ${AGE_LABEL[chosen]}`}.`));
  if (model.onward?.length) text.push(h('p', {}, 'Dashed arrows: what the alimentary tract and urinary bladder models, which the calculation adds around every systemic model, do with the activity that reaches the gut or the bladder — swallowed, cleared from the airways or sent there by this model: down the tract to faeces, back to blood by absorption, out in urine.'));
  $('dcModelText').replaceChildren(...text);
  const diagram = $('dcDiagram'), body = $('dcBody');
  if (model.compartments.length) {
    // The systemic model, and after it the alimentary tract and the bladder (dashed).
    const onward = model.onward || [];
    const transfers = [
      ...model.transfers.map(([a, b, rates]) => ({ from: a, to: b, rate: rateAt(model.ages, rates, age) })),
      ...onward.map((t) => ({ from: t.from, to: t.to, rate: rateAt(model.ages, t.rates, age), model: t.model })),
    ].filter((t) => t.rate > 0);
    const known = new Set(model.compartments.map((c) => c.name));
    const added = [];
    const add = (name, region) => { if (!known.has(name) && laneOf(region, name) !== 'sink') { known.add(name); added.push({ name, region }); } };
    for (const t of onward) { add(t.from, t.fromRegion); add(t.to, t.toRegion); }
    for (const c of model.tract || []) add(c.name, c.region);
    const comps = [...model.compartments, ...added].filter((c) => laneOf(c.region, c.name) !== 'sink' || transfers.some((t) => t.to === c.name));
    // The part of the body each compartment stands for, numbered from head to feet.
    const partsBy = new Map(comps.map((c) => [c.name, partsOf(c.region)]));
    const usedIds = new Set([...partsBy.values()].flat());
    const used = new Map(PARTS.filter((p) => usedIds.has(p.id)).map((p, k) => [p.id, k + 1]));
    const namesOf = (id) => comps.filter((c) => partsBy.get(c.name).includes(id)).map((c) => c.name);
    const labelOf = (id) => PARTS.find((p) => p.id === id).label + (namesOf(id).length ? `: ${namesOf(id).join(', ')}` : '');
    diagram.replaceChildren(drawModel({
      compartments: comps.map((c) => ({ ...c, parts: partsBy.get(c.name), badge: partsBy.get(c.name).map((id) => used.get(id)).join(',') || null })),
      transfers, entry: model.entry,
    }));
    diagram.hidden = false;
    body.replaceChildren(
      drawBody(used, labelOf),
      h('figcaption', {},
        h('ol', { class: 'dc-body-key' }, [...used].map(([id, n]) => h('li', { 'data-part': id, tabindex: 0 },
          h('span', { class: 'num' }, String(n)),
          h('span', {}, PARTS.find((p) => p.id === id).label, h('span', { class: 'names' }, ` · ${namesOf(id).join(', ')}`))))),
        h('p', { class: 'dc-note' }, 'Schematic, not to scale. Point at a box, an organ or a line to see the others it goes with; at a box of the model to see the transfers into it (blue) and out of it (red).')));
    body.hidden = used.size === 0;
  } else { diagram.replaceChildren(); diagram.hidden = true; body.replaceChildren(); body.hidden = true; }
  // The transfer table, all ages.
  const tt = $('dcTransfers');
  const agesHead = (model.ages || []).map((a) => h('th', {}, AGE_LABEL[a] || `${a} d`));
  const onwardRows = (model.onward || []).length ? [
    h('tr', { class: 'group' }, h('td', { colspan: 2 + Math.max(1, agesHead.length) }, 'Around the systemic model: the alimentary tract and the urinary bladder, as the calculation adds them')),
    ...model.onward.map((t) => h('tr', { class: 'tract', 'data-t': transferKey(t.from, t.to) }, h('td', {}, t.from), h('td', { class: 'text' }, t.to), t.rates.map((x) => h('td', {}, fmtRate(x))))),
  ] : [];
  tt.replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'From'), h('th', { class: 'text' }, 'To'), agesHead)),
    h('tbody', {}, model.transfers.map(([a, b, rates]) => h('tr', { 'data-t': transferKey(a, b) }, h('td', {}, a), h('td', { class: 'text' }, b), rates.map((x) => h('td', {}, fmtRate(x))))), onwardRows));
  renderIntakeModel(r, first);
  renderView();
}

/* External exposure: the report's model is its dose per photon emitted at
   each energy (Monte Carlo in its phantoms) and per electron (to the skin):
   drawn for the age chosen, with the nuclide's photon lines that give the
   most after a calculation. */
function renderModelExternal(r) {
  const first = r.first, sixty = r.system === '60';
  const asel = $('dcModelAge');
  const have = first.mono.map((m) => m.age);
  const chosen = have.includes(VIEW.age) ? VIEW.age : have[have.length - 1];
  asel.replaceChildren(...have.map((a) => h('option', { value: a }, ageLabel(a, true))));
  asel.value = String(chosen);
  const mono = first.mono.find((m) => m.age === chosen);
  const per = GEOMETRY[r.spec.geometry]?.per || 'm3';
  const p = (...kids) => h('p', {}, ...kids.flatMap(supText));
  $('dcModelText').replaceChildren(
    p(h('b', {}, sixty ? 'Federal Guidance Report 12 (Eckerman and Ryman 1993)' : 'Federal Guidance Report 15 (Bellamy et al., revised 2025)'), ` · ${geometryLabel(r)}`),
    p(sixty
      ? 'Photons of 12 energies from 10 keV to 5 MeV, transported through the environment (discrete ordinates) and the Cristy–Eckerman adult hermaphrodite phantom (Monte Carlo, ALGAMP), give each organ’s dose rate per photon emitted.'
      : 'Photons of 13 energies from 10 keV to 5 MeV, transported by Monte Carlo (MCNP6) through the environment and the stylised phantoms of Han et al. (newborn, 1, 5, 10 and 15 years, adult), give each of 29 tissues’ dose rate per photon emitted; the reference adult takes the adult phantom for the male and the 15-year-old’s for the female.'),
    p('A nuclide’s coefficient adds up its photon lines of 10 keV or more, each at its yield, interpolated between those energies (a monotone cubic of the logarithms); the bremsstrahlung of its beta particles slowing down in the medium, folded with the same coefficients; and the dose its electrons give the skin, 70 µm deep, from the DOSFACTER calculations of FGR 12 (the lower curve). Electrons reach no other tissue.'),
  );
  // The chart: e and the skin's dose rate per photon, and the skin's per electron.
  const diagram = $('dcDiagram');
  $('dcBody').hidden = true;
  diagram.hidden = false;
  diagram.replaceChildren(h('div', { class: 'plot', id: 'dcPlotMono' }));
  const t = plotTheme();
  const x = mono.points.map((q) => q.E);
  const traces = [
    { x, y: mono.points.map((q) => q.e), name: 'e per photon', mode: 'lines+markers', line: { width: 3 } },
    { x, y: mono.points.map((q) => q.skin), name: 'skin per photon', mode: 'lines+markers' },
    { x: first.electronSkin.E, y: first.electronSkin.h, name: 'skin per electron', mode: 'lines', line: { dash: 'dot' } },
  ];
  const lines = r.run?.out.find((o) => o.age === chosen)?.lines || [];
  if (lines.length) traces.push({ x: lines.map((l) => l[0]), y: lines.map((l) => l[2] / l[1]), name: `${r.entry.name} photon lines`, mode: 'markers', marker: { size: 9, symbol: 'diamond' } });
  if (typeof Plotly !== 'undefined') {
    const lay = layout(`Dose rate per particle emitted, ${ageLabel(chosen, true).toLowerCase()}`, `Sv s<sup>−1</sup> per Bq m<sup>${per === 'm2' ? '−2' : '−3'}</sup>, per particle`, 'Energy (MeV)');
    lay.yaxis.range = logRange(traces, 8);
    lay.hovermode = 'closest';
    Plotly.react($('dcPlotMono'), traces, lay, { responsive: true, displaylogo: false });
  }
  // After a calculation: the lines that give the most of e.
  const box = $('dcIntakeModel');
  if (!lines.length) { box.replaceChildren(r.run ? h('p', { class: 'dc-muted' }, `${r.entry.name} emits no photons of 10 keV or more: its dose rate is its electrons’ and their bremsstrahlung.`) : h('p', { class: 'dc-muted' }, 'Calculate, and the photon lines that give the most appear here.')); return; }
  const o = r.run.out.find((x2) => x2.age === chosen);
  box.replaceChildren(
    h('h3', { class: 'dc-h3' }, `The photon lines of ${r.entry.name} that give the most of e`, h('span', { class: 'dc-unit' }, `${ageLabel(chosen, true).toLowerCase()}, the nuclide alone`)),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Energy, keV'), h('th', {}, 'Yield per decay'), h('th', {}, ...supText(`e, Sv s⁻¹ ${PER_TEXT[per]}`)), h('th', {}, 'Share of e'))),
      h('tbody', {}, lines.map(([E, y, e]) => h('tr', {}, h('td', {}, (1000 * E).toFixed(E < 0.1 ? 2 : 1)), h('td', {}, sci(y, 3)), h('td', {}, sci(e, 3)), h('td', {}, percent(100 * e / o.E))))))),
  );
}

/* Pointing at a box of the model, a part of the body or a line of the key
   lights the others that stand for the same organ or tissue. */
function linkParts(box) {
  const light = (ids) => {
    box.classList.toggle('dc-lit', !!ids);
    for (const e of box.querySelectorAll('[data-part]')) {
      e.classList.toggle('lit', !!ids && e.getAttribute('data-part').split(' ').some((x) => ids.includes(x)));
    }
  };
  const from = (ev) => { const t = ev.target.closest?.('[data-part]'); light(t ? t.getAttribute('data-part').split(' ') : null); };
  box.addEventListener('pointerover', from);
  box.addEventListener('focusin', from);
  box.addEventListener('pointerleave', () => light(null));
  box.addEventListener('focusout', () => light(null));
}

/* Pointing at an arrow of the model or a row of the transfer table lights
   the other, and the two boxes the transfer joins. Pointing at a box lights
   every transfer into it (blue) and out of it (red), arrows and rows, and
   the boxes at their other ends. */
function linkTransfers(box) {
  const clear = () => {
    box.classList.remove('dc-tlit', 'dc-nlit');
    for (const e of box.querySelectorAll('.tlit, .tin, .tout, .tend, .nend, .nsel')) e.classList.remove('tlit', 'tin', 'tout', 'tend', 'nend', 'nsel');
  };
  const nodes = () => box.querySelectorAll('.dc-diagram .node[data-names]');
  const namesOf = (n) => n.getAttribute('data-names').split('|');
  const lightTransfer = (key) => {
    box.classList.add('dc-tlit');
    const [a, b] = key.split('\u2192');
    for (const e of box.querySelectorAll('[data-t]')) e.classList.toggle('tlit', e.getAttribute('data-t') === key);
    for (const n of nodes()) n.classList.toggle('tend', namesOf(n).includes(a) || namesOf(n).includes(b));
  };
  const lightNode = (node) => {
    const mine = new Set(namesOf(node));
    const ends = new Set();
    box.classList.add('dc-nlit');
    node.classList.add('nsel');
    for (const e of box.querySelectorAll('[data-t]')) {
      const [a, b] = e.getAttribute('data-t').split('\u2192');
      const into = mine.has(b) && !mine.has(a), out = mine.has(a) && !mine.has(b);
      e.classList.toggle('tin', into);
      e.classList.toggle('tout', out);
      if (into) ends.add(a);
      if (out) ends.add(b);
    }
    for (const n of nodes()) if (n !== node && namesOf(n).some((x) => ends.has(x))) n.classList.add('nend');
  };
  box.addEventListener('pointerover', (ev) => {
    const t = ev.target.closest?.('[data-t]');
    const n = t ? null : ev.target.closest?.('.dc-diagram .node[data-names]');
    clear();
    if (t) lightTransfer(t.getAttribute('data-t'));
    else if (n) lightNode(n);
  });
  box.addEventListener('pointerleave', clear);
}

/* ---- what the drawing shows ------------------------------------------------------ */
/* Show: the model as it is, with the transfer coefficients on its arrows at
   the age chosen; or, after a calculation, its boxes as buckets, each filled
   from the bottom to its share, at one of the calculation's output times and
   for the age at intake chosen, of the member's activity in the body, or of
   the effective dose -- received up to then, or its rate there -- from the
   activity of the member or of the whole chain (each nuclide counted in the
   box of the same name, or, where formed in a compartment of another
   member's model, in that compartment's box). What the drawing has no box
   for (the respiratory tract, the mouth and the oesophagus, ...) is listed
   under the slider. Run through moves the time from the first output to the
   last in about seven seconds, as ensdf.html's Inventory does. The time is
   kept, not the slider's position: each age's outputs have the corners of
   its own rate tables, so another age shows its nearest time. */
const VIEW = { show: 'model', dose: 'received', from: 'member', time: 1, age: null, frame: 0 };
const REF_AGES = [100, 365, 1825, 3650, 5475, 7300];
const RUN_THROUGH_MS = 7000;
// Bq per Bq taken in: below it the integrator's absolute tolerance (1E-14 in
// each compartment) blurs the shares, and a negative round-off can show.
const BUCKET_FLOOR = 1e-10;
const bucketPct = (f) => (f > 0 ? percent(100 * f) : '0 %');
const bucketWhen = (days) => (days > 0 ? `${sinceText(days)} after intake` : 'At intake');
function nearestTime(times, t) {
  let best = 0, off = Infinity;
  times.forEach((x, i) => { const d = Math.abs(Math.log((x || 1e-9) / (t || 1e-9))); if (d < off) { off = d; best = i; } });
  return best;
}
function sinceText(days) {
  const g2 = (x) => String(Number(x.toPrecision(2)));
  const [v, unit] = days < 1 / 24 ? [g2(days * 1440), 'minute'] : days < 1 ? [g2(days * 24), 'hour'] : days < 365.25 ? [g2(days), 'day'] : [g2(days / 365.25), 'year'];
  return `${v} ${unit}${v === '1' ? '' : 's'}`;
}
/* A calculation shown whose series hold the activity and the dose by place. */
const fillable = (r) => !!(r?.run && r.run.out.every((o) => o.series?.places && o.series.dosePlaces));
/* What the drawing shows: the choice where the boxes can be filled, else the model. */
const viewShown = (r, model) => (fillable(r) && model?.compartments?.length ? VIEW.show : 'model');
/* The calculation's series for the age at intake chosen, or null. */
function viewSeries() {
  const r = shownSystem();
  if (!fillable(r)) return null;
  const k = r.run.ages.indexOf(Number($('dcModelAge').value));
  return k >= 0 ? { o: r.run.out[k], ser: r.run.out[k].series } : null;
}
/* The places (worker.js placeOf) a box holds: its compartments by name, and
   a box of the contents of the gut or the bladder its region; for the whole
   chain also the progeny formed in its compartments (f:). */
function nodePlaces(g, formed) {
  const names = (g.getAttribute('data-names') || '').split('|').filter(Boolean);
  const keys = names.map((n) => `n:${placeName(n)}`);
  if (formed) for (const n of names) keys.push(`f:${placeName(n)}`);
  if (g.classList.contains('content')) keys.push(`r:${String(g.getAttribute('data-region') || '').replace(/_/g, '-').toLowerCase()}`);
  return keys;
}
/* One output time of a view: what fills the boxes, as [the key a box
   claims, member, value], their total, the activity behind them, and
   whether there is too little to share out (the activity under the floor,
   or no dose yet). */
function viewAt(ser, ti, m, show, chain) {
  const pos = (y) => (y > 0 ? y : 0);
  const ms = chain ? ser.members.map((x, j) => j) : [m];
  const items = [];
  if (show === 'activity') {
    for (const [x, ys] of Object.entries(ser.places[m] || {})) items.push([x, m, pos(ys[ti])]);
  } else {
    const src = VIEW.dose === 'rate' ? ser.ratePlaces : ser.dosePlaces;
    for (const j of ms) for (const [x, ys] of Object.entries(src[j] || {})) items.push([chain ? x : (ser.placeKey[j]?.[x] ?? x), j, pos(ys[ti])]);
  }
  const total = items.reduce((a, it) => a + it[2], 0);
  const act = ms.reduce((a, j) => a + Object.values(ser.places[j] || {}).reduce((b, ys) => b + pos(ys[ti]), 0), 0);
  return { items, total, act, empty: show === 'dose' && VIEW.dose === 'received' ? !(total > 0) : !(act >= BUCKET_FLOOR) };
}
/* What a view has no box for at one time: by place (the airways, the parts
   of the tract not drawn, ...), and for the whole chain each member's other
   places together. */
function viewRest(ser, at, claim, chain) {
  const rest = new Map();
  for (const [x, j, y] of at.items) {
    if (!(y > 0) || claim.has(x)) continue;
    const apart = chain && !/^[lr]:/.test(x);
    const key = apart ? `m:${j}` : x;
    const c = rest.get(key) || { label: apart ? `${ser.members[j]}, not in this drawing` : ser.placeLabel?.[x] || x.slice(2), v: 0, at: new Map(), order: apart ? 1e6 + j : Object.keys(ser.placeLabel || {}).indexOf(x) };
    c.v += y;
    const where = ser.placeLabel?.[x] || x.slice(2);
    c.at.set(where, (c.at.get(where) || 0) + y);
    rest.set(key, c);
  }
  return rest;
}
/* The parts of a view that must not change size as the time moves, so that
   the drawing under them keeps its place: the list of what is not drawn
   (every place that holds a share at some time; elsewhere at 0 %) and the
   longest notes, which reserve the note's height. */
const VIEW_FRAME = new WeakMap();
function viewFrame(ser, key, make) {
  let f = VIEW_FRAME.get(ser);
  if (!f || f.key !== key) VIEW_FRAME.set(ser, f = { key, ...make() });
  return f;
}
function renderView() {
  const svg = $('dcDiagram').querySelector('svg');
  const r = shownSystem();
  const m = Number($('dcModelMember').value) || 0;
  const show = svg && !$('dcDiagram').hidden ? viewShown(r, r?.first?.models?.[m]) : 'model';
  const v = show === 'model' ? null : viewSeries();
  $('dcBuckets').hidden = !v;
  if (!v) { viewStop(); if (svg) fillBoxes(svg, null); return; }
  const { o, ser } = v;
  const ti = nearestTime(ser.times, VIEW.time);
  const when = bucketWhen(ser.times[ti]);
  const slider = $('dcBucketsT');
  slider.max = String(ser.times.length - 1);
  slider.value = String(ti);
  slider.setAttribute('aria-valuetext', when);
  $('dcBucketsTime').textContent = when;
  const age = Number($('dcModelAge').value);
  const intake = `for an intake at ${AGE_LABEL[age] === 'Adult' ? 'adult age' : `the age of ${AGE_LABEL[age]}`}`;
  const name = ser.members[m], per = m === 0 ? 'per Bq taken in' : `per Bq of ${ser.members[0]} taken in`;
  const chain = show === 'dose' && VIEW.from === 'chain' && ser.members.length > 1;
  const what = show === 'activity' ? `of the ${name} in the body` : VIEW.dose === 'rate' ? 'of the effective dose rate' : 'of the effective dose received so far';
  const unit = show === 'activity' ? 'Bq' : VIEW.dose === 'rate' ? 'Sv per day' : 'Sv';
  const from = chain ? 'the whole chain in the body' : `the ${name} in the body`;
  const noteOf = (at) => {
    if (at.empty) {
      if (show === 'dose' && VIEW.dose === 'received') return `No dose received yet, ${intake}.`;
      return at.act > 0 ? `Less than ${sci(BUCKET_FLOOR, 1)} Bq of ${chain ? 'the chain' : name} in the body ${per}, ${intake}: too little for the calculation to share out among the boxes.`
        : `No ${chain ? 'activity of the chain' : name} in the body, ${intake}.`;
    }
    return show === 'activity' ? `${sci(at.total)} Bq of ${name} in the body ${per}, ${intake}. Each box is filled to its share of it.`
      : VIEW.dose === 'rate' ? `${sci(at.total)} Sv per day ${per} from ${from}, ${intake}. Each box is filled to its share of it.`
        : `${sci(at.total)} Sv ${per} received from ${from} so far, of a committed effective dose of ${sci(o.E)} Sv ${m === 0 ? 'per Bq' : `per Bq of ${ser.members[0]}`}, ${intake}. Each box is filled to its share of it.`;
  };
  // Every key a box claims: the same at every time.
  const claim = new Set();
  for (const g of svg.querySelectorAll('.node:not(.sink)')) for (const x of nodePlaces(g, chain)) claim.add(x);
  const frame = viewFrame(ser, [m, show, VIEW.dose, chain, age].join('|'), () => {
    const list = new Map(), notes = new Set();
    ser.times.forEach((t, k) => {
      const at = viewAt(ser, k, m, show, chain);
      notes.add(noteOf(at));
      if (at.empty) return;
      for (const [key, c] of viewRest(ser, at, claim, chain)) if (c.v / at.total >= 5e-4 && !list.has(key)) list.set(key, { label: c.label, order: c.order });
    });
    return { list: [...list].sort((a, b) => a[1].order - b[1].order), notes: [...notes].sort((a, b) => b.length - a.length).slice(0, 3) };
  });
  const now = viewAt(ser, ti, m, show, chain);
  $('dcBucketsNote').replaceChildren(noteOf(now));
  $('dcBucketsSizer').replaceChildren(...frame.notes.map((t) => h('span', {}, t)));
  if (now.empty) fillBoxes(svg, () => ({ share: 0, text: '–' }));
  else {
    fillBoxes(svg, (g) => {
      const keys = new Set(nodePlaces(g, chain));
      let val = 0;
      const by = new Map();
      for (const [x, j, y] of now.items) if (y > 0 && keys.has(x)) { val += y; by.set(j, (by.get(j) || 0) + y); }
      const f = val / now.total;
      const mix = chain && by.size > 1 ? ` (${[...by].sort((a, b) => b[1] - a[1]).map(([j, y]) => `${ser.members[j]} ${bucketPct(y / val)}`).join(', ')})` : '';
      return { share: f, text: bucketPct(f), tip: `${when}: ${bucketPct(f)} ${what}, ${sci(val)} ${unit} ${per}${mix}` };
    });
  }
  const rest = now.empty ? new Map() : viewRest(ser, now, claim, chain);
  $('dcBucketsExtra').replaceChildren(...(frame.list.length ? [h('span', { class: 'dc-bucket-extra-head' }, show === 'activity' ? 'In the body, not in the drawing:' : 'From activity not in the drawing:'), ...frame.list.map(([key, { label }]) => {
    const c = rest.get(key);
    const f = c && now.total > 0 ? c.v / now.total : 0;
    const where = c && key.startsWith('m:') ? `: ${[...c.at].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([w, y]) => `${w} ${bucketPct(y / now.total)}`).join(', ')}` : '';
    const chip = h('span', { class: 'dc-chip', 'data-place': key, 'data-share': String(f), 'data-tip': `${label}, ${when}: ${now.empty ? 'too little to share out' : `${bucketPct(f)} ${what}, ${sci(c ? c.v : 0)} ${unit} ${per}${where}`}` },
      h('span', { class: 'dc-chip-level' }), h('span', { class: 'dc-chip-text' }, `${label} `, h('b', {}, now.empty ? '–' : bucketPct(f))));
    chip.style.setProperty('--level', f.toFixed(4));
    return chip;
  })] : []));
}
function viewPlay() {
  if (VIEW.frame) { viewStop(); return; }
  const v = viewSeries();
  const n = v ? v.ser.times.length : 0;
  if (n < 2 || $('dcBuckets').hidden) return;
  const times = v.ser.times;
  const at = nearestTime(times, VIEW.time);
  const from = at < n - 1 ? at : 0;
  VIEW.time = times[from];
  renderView();
  $('dcBucketsPlay').textContent = 'Stop';
  let start = null, shown = from;
  const step = (now) => {
    if (start === null) start = now - (from / (n - 1)) * RUN_THROUGH_MS;
    const i = Math.min(n - 1, Math.round(((now - start) / RUN_THROUGH_MS) * (n - 1)));
    if (i !== shown) { shown = i; VIEW.time = times[i]; renderView(); }
    if (i >= n - 1) { viewStop(); return; }
    VIEW.frame = requestAnimationFrame(step);
  };
  VIEW.frame = requestAnimationFrame(step);
}
function viewStop() {
  if (VIEW.frame) cancelAnimationFrame(VIEW.frame);
  VIEW.frame = 0;
  const b = $('dcBucketsPlay');
  if (b) b.textContent = 'Run through';
}

function kvTable(rows) {
  return h('table', { class: 'dc-kv' }, h('tbody', {}, rows.filter(Boolean).map(([k, v, num]) => h('tr', {}, h('th', {}, k), h('td', { class: num ? 'num' : '' }, ...supText(v))))));
}
function renderIntakeModel(r, first) {
  const box = $('dcIntakeModel');
  const it = first.intake || {};
  const parts = [];
  if (r.system === '103') {
    const f = it.form || {};
    parts.push(h('h3', { class: 'dc-h3' }, { inhalation: 'Respiratory tract', ingestion: 'Alimentary tract', injection: 'Direct uptake to blood' }[r.spec.route]));
    if (r.spec.route === 'injection') {
      parts.push(kvTable([['Intake', 'All of it enters blood at once: the systemic model’s entry compartment (where absorption from the respiratory tract enters, for polonium Plasma 2)']]));
    } else if (r.spec.route === 'inhalation') {
      const a = it.absorb;
      const rows = [['Form', f.label]];
      if (a) {
        if (a.sp != null) rows.push(['Dissolution (Fig. 2.5b)', `sp ${a.sp} d⁻¹, spt ${a.spt} d⁻¹, st ${a.st} d⁻¹`, true]);
        else rows.push(['Dissolution (Fig. 2.5a)', `fr ${a.fr}, sr ${a.sr} d⁻¹${a.ss != null ? `, ss ${a.ss} d⁻¹` : ''}`, true]);
        rows.push(['Bound state', a.fb ? `fb ${a.fb}, sb ${a.sb} d⁻¹, in ${(a.boundIn || ['AI']).join(', ')}` : 'none', !!a.fb]);
      } else rows.push(['Absorption', 'Type V: absorbed at once', false]);
      if (it.deposition) {
        const dpos = it.deposition;
        const tot = ['ET1', 'ET2', 'BB', 'bb', 'AI'].reduce((s, k) => s + (dpos[k] || 0), 0);
        rows.push(['Deposition', ['ET1', 'ET2', 'BB', 'bb', 'AI'].map((k) => `${k} ${(100 * (dpos[k] || 0)).toFixed(2)} %`).join(', ') + `; total ${(100 * tot).toFixed(1)} % (at the age of the first intake)`, true]);
      }
      parts.push(kvTable(rows));
      parts.push(h('p', { class: 'dc-model-text' }, ...supText('Particle transport (Publication 130, the same at every age): ET1 → environment 0.6, ET1 → ET2 1.5, ET2 → oesophagus 100, BB → ET2 10, bb → BB 0.2, ALV → bb 0.002, ALV → INT 0.001, INT → LN(TH) 0.00003, and from the sequestered compartments to the lymph nodes 0.001 d⁻¹; 0.2 % of the deposit in ET2, BB and bb is sequestered.')));
    } else parts.push(kvTable([['Form', f.label]]));
    const fa = it.fA || {};
    const ageHead = [100, 365, 1825, 3650, 5475, 7300].map((a) => h('th', {}, AGE_LABEL[a]));
    parts.push(h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Absorption from the alimentary tract'), ageHead)),
      h('tbody', {},
        fa.intake ? h('tr', {}, h('td', {}, r.spec.route === 'inhalation' ? 'fA of material cleared from the lungs' : 'fA of the intake'), fa.intake.map((x) => h('td', {}, fmtRate(x)))) : null,
        fa.secretions ? h('tr', {}, h('td', {}, 'fA of secreted activity (highest reference value)'), fa.secretions.map((x) => h('td', {}, fmtRate(x)))) : null))));
    parts.push(h('p', { class: 'dc-model-text' }, ...supText('Human Alimentary Tract Model (Publication 100), transit rates of Publication 158 Table 2.10; absorption from the small intestine to blood at fA/(1 − fA) times the small intestine’s emptying rate; urinary bladder emptied at 40, 32 and 12 d⁻¹ at 3 months, 1 year and from 5 years.')));
  } else {
    parts.push(h('h3', { class: 'dc-h3' }, r.spec.route === 'inhalation' ? 'Respiratory and gastrointestinal tracts' : 'Gastrointestinal tract'));
    const rows = [['Progeny kinetics', it.kinetics === 'I' ? 'independent (element-specific models)' : 'shared with the parent']];
    if (it.lung) rows.push(['Respiratory tract model', `${it.lung.name}: ${it.lung.title || ''}`]);
    if (it.deposition) rows.push(['Initial deposition', Object.entries(it.deposition).map(([k, v]) => `${k} ${(100 * v).toFixed(2)} %`).join(', '), true]);
    if (it.f1) rows.push(['f1', `${it.f1.values.map((v, k) => `${AGE_LABEL[it.f1.ages[k]] || it.f1.ages[k] + ' d'} ${fmtRate(v)}`).join(', ')} (${it.f1.file})`, true]);
    parts.push(kvTable(rows));
    parts.push(h('p', { class: 'dc-model-text' }, ...supText('ICRP 30 gastrointestinal tract: stomach → small intestine 24, small intestine → upper large intestine 6, → lower large intestine 1.8, → faeces 1 d⁻¹; absorption from the small intestine at f1/(1 − f1) × 6 d⁻¹ (f1 capped at 0.99). Urinary bladder emptied at 40, 32 and 12 d⁻¹ at 3 months, 1 year and from 5 years (Publication 67).')));
  }
  box.replaceChildren(...parts);
}

/* ---- the decay chain tab ---------------------------------------------------------- */
function renderChain() {
  const s = shownSystem();
  $('dcChainEmpty').hidden = !!s;
  $('dcChain').hidden = !s;
  if (!s) return;
  paneHead('dcChainHead', s);
  const ext = !!s.first?.external;
  $('dcUTable').closest('.dc-table-wrap').hidden = ext;
  $('dcUTable').closest('.dc-table-wrap').previousElementSibling.hidden = ext;
  if (ext) { renderChainExternal(s); return; }
  const r = s.run; // the numbers of transformations come with a run
  const note = staleNote(r);
  $('dcChainStale').replaceChildren(...(note ? [note] : []));
  $('dcChainStale').hidden = !note;
  $('dcChain').classList.toggle('dc-stale', !!note);
  const first = s.first;
  const members = first.members;
  const parentsOf = members.map(() => []);
  for (const b of first.branches) parentsOf[b.to].push([b.from, b.b]);
  const kindText = { parent: 'intake', independent: 'own model (independent kinetics)', spec: 'the model the parent element’s OIR section gives it', decay: 'decays where it is formed', mirror: 'shares the kinetics of the member it comes from', gas: 'noble gas', shared: 'parent’s model (shared kinetics)', 'own model': 'own model (independent kinetics)' };
  const sel = $('dcChainAge');
  sel.closest('label').hidden = !r;
  sel.closest('label').firstChild.textContent = 'Transformations at age ';
  let o0 = null;
  if (r) {
    const prev = sel.value;
    sel.replaceChildren(...r.out.map((o, k) => h('option', { value: k }, AGE_LABEL[o.age])));
    sel.value = prev && prev < r.out.length ? prev : String(r.out.length - 1);
    o0 = r.out[Number(sel.value)];
  }
  const perMember = new Map();
  for (const t of o0?.transformations || []) perMember.set(t.member, (perMember.get(t.member) || 0) + t.n);
  const mev = (x) => (x > 0 ? (x >= 0.001 ? x.toFixed(4) : x.toExponential(2)) : '–');
  $('dcChainTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Member'), h('th', {}, 'Half-life'), h('th', { class: 'text' }, 'Produced from'),
      h('th', {}, 'Alpha, MeV'), h('th', {}, 'Electron, MeV'), h('th', {}, 'Photon, MeV'), h('th', {}, 'Transformations per Bq'), h('th', { class: 'text' }, 'In the body'))),
    h('tbody', {}, members.map((m, j) => h('tr', {},
      h('td', {}, m.name, m.other ? h('span', { class: 'dc-other-name', 'data-tip': `${decayLabel(s.decay, s.system)} calls this state ${m.other}; the page keeps the ${s.system === '60' ? 'ICRP 38' : 'ICRP 107'} name (Help: “Decay data”)` }, ` (${m.other})`) : null),
      h('td', {}, halfLife(m.T)),
      h('td', { class: 'text' }, parentsOf[j].map(([i, b]) => `${members[i].name} (${b < 0.9999 ? `${+(100 * b).toPrecision(3)} %` : '100 %'})`).join(', ') || '—'),
      ...(m.E || [null, null, null]).map((x) => h('td', {}, mev(x))),
      h('td', {}, r ? sci(perMember.get(m.name) || 0, 3) : '–'),
      h('td', { class: 'text' }, kindText[m.kind] || m.kind || '')))));
  const dropped = first.dropped || [];
  $('dcChainNote').textContent = dropped.length
    ? `Left out by the cut-off: ${dropped.join(', ')}.`
    : 'The whole chain is followed.';
  // How decay data made from ENSDF were read for these members, where it took a rule of the page's.
  const decayNotes = members.filter((m) => m.decayNotes?.length);
  $('dcChainDecay').hidden = !s.decay;
  $('dcChainDecay').replaceChildren(...(s.decay ? [
    h('p', {}, `Decay data: ${decayLabel(s.decay, s.system)}, made ${s.decay.startsWith('open:') ? 'in this browser' : 'on this site'} from the release’s decay data sets (Help: “Decay data”). `,
      decayNotes.length ? 'Where a data set needed a rule of the page’s:' : 'None of these members needed a rule beyond reading their data sets.'),
    decayNotes.length ? h('ul', {}, decayNotes.map((m) => h('li', {}, h('b', {}, m.name), ': ', m.decayNotes.join('; ')))) : null,
  ].filter(Boolean) : []));
  if (!r) {
    $('dcUTable').replaceChildren(h('tbody', {}, h('tr', {}, h('td', { class: 'dim' }, 'Counted as the doses are calculated: press Calculate.'))));
    return;
  }
  const o = o0;
  const rows = (o.transformations || []).filter((t) => t.n > 0).sort((a, b) => b.n - a.n);
  const total = rows.reduce((a, t) => a + t.n, 0);
  $('dcUTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Member'), h('th', { class: 'text' }, 'Source region'), h('th', {}, 'Transformations per Bq'), h('th', {}, 'Share'))),
    h('tbody', {}, rows.slice(0, 80).map((t) => h('tr', {}, h('td', {}, t.member), h('td', { class: 'text' }, t.region), h('td', {}, sci(t.n, 3)), h('td', {}, `${(100 * t.n / total).toFixed(2)} %`))),
      rows.length > 80 ? h('tr', {}, h('td', { colspan: 4, class: 'dim' }, `and ${rows.length - 80} more, each under ${sci(rows[79].n, 2)}`)) : null));
}

/* External exposure: the whole chain, each member's activity per becquerel of
   the parent once in equilibrium with it, and after a calculation each
   member's own e and its share of e with the progeny. */
function renderChainExternal(s) {
  const r = s.run;
  const note = staleNote(r);
  $('dcChainStale').replaceChildren(...(note ? [note] : []));
  $('dcChainStale').hidden = !note;
  $('dcChain').classList.toggle('dc-stale', !!note);
  const first = s.first, chain = first.chain;
  const parentsOf = chain.map(() => []);
  for (const b of first.branches) parentsOf[b.to].push([b.from, b.b]);
  const sel = $('dcChainAge');
  sel.closest('label').hidden = !r;
  sel.closest('label').firstChild.textContent = 'Shares at age ';
  let o = null;
  if (r) {
    const prev = sel.value;
    sel.replaceChildren(...r.out.map((x, k) => h('option', { value: k }, ageLabel(x.age, true))));
    sel.value = prev && prev < r.out.length ? prev : String(r.out.length - 1);
    o = r.out[Number(sel.value)];
  }
  const d = digits(), [f] = rateOf();
  const mev = (x) => (x > 0 ? (x >= 0.001 ? x.toFixed(4) : x.toExponential(2)) : '–');
  const byName = new Map((o?.members || []).map((m) => [m.name, m]));
  // Alpha particles give no external dose: the electron and photon energies only.
  $('dcChainTable').replaceChildren(
    h('thead', {}, h('tr', {}, h('th', {}, 'Member'), h('th', {}, 'Half-life'), h('th', { class: 'text' }, 'Produced from'),
      h('th', {}, 'Electron, MeV'), h('th', {}, 'Photon, MeV'), h('th', { 'data-tip': 'Its activity per becquerel of the parent once in equilibrium with it' }, 'Bq per Bq'),
      h('th', { 'data-tip': o ? `Its own effective dose rate, ${rateText(o.per)}` : null }, 'e alone'), h('th', { 'data-tip': 'Its part of the effective dose rate with the progeny' }, 'Share'))),
    h('tbody', {}, chain.map((m, j) => {
      const x = byName.get(m.name);
      return h('tr', {},
        h('td', {}, m.name, m.other ? h('span', { class: 'dc-other-name', 'data-tip': `${decayLabel(s.decay, s.system)} calls this state ${m.other}; the page keeps the ${s.system === '60' ? 'ICRP 38' : 'ICRP 107'} name (Help: “Decay data”)` }, ` (${m.other})`) : null),
        h('td', {}, halfLife(m.T)),
        h('td', { class: 'text' }, parentsOf[j].map(([i, b]) => `${chain[i].name} (${b < 0.9999 ? `${+(100 * b).toPrecision(3)} %` : '100 %'})`).join(', ') || '—'),
        ...(m.E || [null, null, null]).slice(1).map((v) => h('td', {}, mev(v))),
        h('td', { class: m.ratio == null ? 'dim' : '' }, j === 0 ? '1' : m.ratio == null ? 'never' : sigText(m.ratio)),
        h('td', {}, x?.E != null ? sci(x.E * f, d) : '–'),
        h('td', {}, x?.share && o.progeny.E > 0 ? percent(100 * x.share.E / o.progeny.E) : '–'));
    })));
  const notIn = chain.filter((m) => m.ratio == null).map((m) => m.name);
  $('dcChainNote').textContent = `Bq per Bq: each member’s activity once in equilibrium with ${chain[0].name}, which a member shorter-lived than it and formed only from members that are reaches${first.days > 0 ? `, within 1 % after ${durationText(first.days)}` : ''}; ${notIn.length ? `never: ${notIn.join(', ')}` : 'the whole chain does'}.${o ? ` e alone in ${rateText(o.per)}; its share of e with the progeny.` : ''}`;
  const decayNotes = chain.filter((m) => m.decayNotes?.length);
  $('dcChainDecay').hidden = !s.decay;
  $('dcChainDecay').replaceChildren(...(s.decay ? [
    h('p', {}, `Decay data: ${decayLabel(s.decay, s.system)} (Help: “Decay data”). `, decayNotes.length ? 'Where a data set needed a rule of the page’s:' : 'None of these members needed a rule beyond reading their data sets.'),
    decayNotes.length ? h('ul', {}, decayNotes.map((m) => h('li', {}, h('b', {}, m.name), ': ', m.decayNotes.join('; ')))) : null,
  ].filter(Boolean) : []));
}

/* ---- the risk tab ------------------------------------------------------------------------ */
/* The detriment-adjusted nominal risk coefficients of the selected system,
   calculated from the ICRP's inputs step by step (risk.js), beside the
   values it printed. */
function renderRisk() {
  const pop = document.querySelector('input[name="dcRiskPop"]:checked')?.value || 'whole';
  const sixty = state.system === '60';
  const [summary, ...steps] = sixty ? risk60(pop) : risk103(pop);
  $('dcRisk').replaceChildren(...riskContext(sixty), summary, ...[].concat(steps.shift()), ...riskApplied(pop), ...steps, ...riskBases(sixty, pop));
}
/* What the coefficients are, and the steps that lead to them. */
function riskContext(sixty) {
  const p = (...kids) => h('p', { class: 'dc-formula' }, ...kids.flatMap(supText));
  const steps = sixty ? [
    'Fatal cancer per unit dose at high doses and dose rates, from the atomic bomb survivors (follow-up to 1985, DS86 doses), projected over a lifetime with multiplicative and additive models and carried to five national populations (Japan, United States, Puerto Rico, United Kingdom, China): about 10 × 10⁻² Sv⁻¹ for a population of all ages (paras B98–B113).',
    'Divided by a dose and dose-rate effectiveness factor (DDREF) of 2 for low doses and dose rates: 5 × 10⁻² Sv⁻¹, 4 × 10⁻² Sv⁻¹ for workers (para B113).',
    'Shared out over the organs by the average distribution of fatal cancers (Table B-15), with thyroid, bone surface, skin and liver from other studies (Table B-17).',
    'Non-fatal cancers added, weighted by the lethality k of each cancer: F (2 − k) (para B117, Table B-19).',
    'Weighted by the relative length of life lost, l / l̄ (Table B-18), with severe hereditary effects in all generations, 1 × 10⁻² Sv⁻¹, at 20 years lost (para B116).',
    'The relative contributions, rounded into four groups, are the tissue weighting factors (para B120).',
  ] : [
    'Lifetime risk of cancer incidence per unit dose from models fitted to the atomic bomb survivors (incidence 1958–1998, DS02 doses), excess relative and excess absolute risk, for 14 organs and tissues, averaged over the sexes (Box A.1 a).',
    'Divided by a dose and dose-rate effectiveness factor (DDREF) of 2 for low doses and dose rates, except for leukaemia, whose linear-quadratic model already allows for it (b).',
    'Carried to other populations by a weighted mix of the two models, chosen per cancer (c), and averaged over Asian (Shanghai, Osaka, Hiroshima, Nagasaki) and Euro-American (Sweden, United Kingdom, US SEER) populations: the nominal risks R (d).',
    'Adjusted for lethality k, from cancer survival statistics, and for the quality of life with a cancer that does not kill, q (e, f).',
    'Weighted by the relative cancer-free life lost l (g): the detriment, whose relative values (h) are, with judgement, the tissue weighting factors (i).',
  ];
  return [
    h('h3', { class: 'dc-h3' }, 'What these coefficients are'),
    p('A nominal risk coefficient is the ICRP’s estimate of the lifetime risk of radiation-induced cancer, or heritable disease, per sievert of effective dose, averaged over the sexes and over the ages at exposure of a representative population (all ages, or of working age), for low doses and low dose rates. It rests on the assumption that the risk is proportional to the dose there (the linear–non-threshold model) and on a factor of 2 by which the risk per sievert observed after high, brief doses is reduced.'),
    p('Detriment weights each harm for how serious it is: a cancer that kills counts fully, one that is cured counts by its lethality and the lasting effect on quality of life, and each kind of cancer by the years of life it takes compared with the average cancer. The sum over tissues, per sievert, is the detriment-adjusted nominal risk coefficient; the share of each tissue is the basis of the tissue weighting factors used for effective dose. ',
      sixty ? 'In Publication 60 it is built from fatal cancer: ' : 'In Publication 103 it is built from cancer incidence: '),
    h('ol', { class: 'dc-notes dc-steps' }, steps.map((x) => h('li', {}, ...supText(x)))),
  ];
}
/* The coefficients applied to the calculated intake: e times the total, and tissue by tissue. */
function riskApplied(pop) {
  const r = state.result;
  const ext = external(r);
  const per = ext ? `per s per Bq ${r.out[0].per === 'm2' ? 'm⁻²' : 'm⁻³'}` : 'per Bq taken in';
  const head = h('h3', { class: 'dc-h3' }, ext ? 'Applied to the calculated exposure' : 'Applied to the calculated intake', riskUnit(`nominal detriment ${per}`));
  if (!r) return [head, h('p', { class: 'dc-muted' }, 'Calculate a dose coefficient, and its nominal detriment per becquerel appears here.')];
  // External exposure: its dose rates, of the nuclide alone or with its
  // progeny as the Coefficients tab shows them; the hermaphrodite phantom's
  // ovaries for the female gonads.
  const withP = ext && progenyView() === 'with';
  const outs = !ext ? r.out : r.out.map((o) => {
    const H = withP ? o.progeny.H : o.H;
    return { age: o.age, E: withP ? o.progeny.E : o.E, H: r.system === '60' ? H : { avg: H, F: { Gonads: H.Ovaries } } };
  });
  const n = nominalDetriment(r.system, pop, outs);
  const d = digits();
  const coef = `${(100 * n.coefficient).toFixed(1)} × 10⁻² Sv⁻¹`;
  const sixty = r.system === '60';
  const sel = h('select', { id: 'dcRiskAge', 'data-on-change': 'dc:redraw' }, n.ages.map((a, k) => h('option', { value: k }, ageLabel(a.age, ext))));
  const k = Math.min(Number(state.riskAge ?? n.ages.length - 1), n.ages.length - 1);
  sel.value = String(k);
  sel.addEventListener('change', () => { state.riskAge = sel.value; });
  const a = n.ages[k];
  const labels = DOSE_LABEL[n.system];
  const note = staleNote(r);
  return [
    head,
    ...(note ? [note] : []),
    h('p', { class: 'dc-formula' }, ...supText(ext
      ? `${r.entry.name}, ${headlineText(r)}${withP ? ', with its progeny in equilibrium' : ', the nuclide alone'} (as the Coefficients tab shows it); coefficients for the ${pop === 'whole' ? 'whole population' : 'adult workers'} (the toggle above). Two ways: the effective dose rate e times the total coefficient, ${coef}; and tissue by tissue, each tissue’s detriment per sievert times its equivalent dose rate. Per second of exposure to a unit concentration.`
      : `${r.entry.name}, ${headlineText(r)}; coefficients for the ${pop === 'whole' ? 'whole population' : 'adult workers'} (the toggle above). Two ways: the committed effective dose e times the total coefficient, ${coef}; and tissue by tissue, each tissue’s detriment per sievert times its committed equivalent dose, which follows where the dose actually goes.`)),
    h('div', { class: note ? 'dc-table-wrap dc-dim' : 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, ext ? 'Age' : 'Age at intake'), h('th', {}, ...supText(ext ? `e, Sv s⁻¹ ${PER_TEXT[r.out[0].per]}` : 'e, Sv per Bq')), h('th', {}, ...supText(`e × ${coef}`)), h('th', {}, 'Tissue by tissue'),
        h('th', {}, sixty ? 'of which hereditary' : 'of which heritable'), h('th', {}, 'Ratio'), h('th', {}, sixty ? 'Fatal cancers, Σ H F' : 'Cancer cases, Σ H R'))),
      h('tbody', {}, n.ages.map((x) => h('tr', {}, h('td', {}, ageLabel(x.age, ext)), h('td', {}, sci(x.E, d)), h('td', {}, sci(x.fromE, d)), h('td', { class: 'big' }, sci(x.organ, d)),
        h('td', {}, sci(x.heritable, d)), h('td', {}, x.fromE > 0 ? (x.organ / x.fromE).toFixed(2) : '–'), h('td', {}, sci(x.risk, d))))))),
    h('h3', { class: 'dc-h3' }, 'Tissue by tissue at ', sel, riskUnit(per)),
    h('div', { class: note ? 'dc-table-wrap dc-dim' : 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, sixty ? 'Organ' : 'Tissue'), h('th', { class: 'text' }, ext ? 'Equivalent dose rate of' : 'Equivalent dose of'), h('th', {}, ...supText(ext ? `H, Sv s⁻¹ ${PER_TEXT[r.out[0].per]}` : 'H, Sv per Bq')), h('th', {}, ...supText('Detriment, 10⁻² Sv⁻¹')),
        h('th', {}, ext ? 'Detriment rate' : 'Detriment per Bq'), h('th', {}, 'Share'))),
      h('tbody', {}, a.parts.map((t) => h('tr', {}, h('td', {}, t.tissue), h('td', { class: 'text dim' }, labels[t.tissue] || t.tissue.toLowerCase()), h('td', {}, sci(t.H, d)),
        h('td', {}, (100 * t.D).toFixed(3)), h('td', { class: 'big' }, sci(t.detriment, d)), h('td', {}, `${(100 * t.share).toFixed(1)} %`))),
        h('tr', { class: 'sum' }, h('td', {}, 'Total'), h('td', {}), h('td', {}), h('td', {}, (100 * a.parts.reduce((s, t) => s + t.D, 0)).toFixed(3)), h('td', {}, sci(a.organ, d)), h('td', {}, '100 %'))))),
    riskNote([
      'The two ways agree for a dose spread evenly through the body (a ratio of 1, apart from the rounding of the printed coefficient); where the dose gathers in a few tissues they part, because the tissue weighting factors are rounded from the relative detriments and grouped (Publication 60 para 98 makes the same point for its coefficients).',
      `The doses: sex-averaged in the ICRP 103 system, except the ovaries (the female dose: ovarian cancer is averaged over both sexes in R) and heritable effects (the mean of testes and ovaries); other solid cancers take the remainder dose. ${sixty ? 'In the ICRP 60 system severe hereditary effects take the mean of testes and ovaries (its effective dose takes the higher), and the remainder its dose as in effective dose.' : ''}`,
      `The coefficients are averages over the ages and sexes of a population; the same per-sievert values are used here for every age at intake, although the risk per sievert is higher for those exposed young (${sixty ? 'Publication 60 Table B-13' : 'Publication 103 Tables A.4.18 and A.4.19 give sex-specific values'}). The results are nominal detriment for protection purposes, not the risk of a person: the ICRP does not recommend effective dose or these coefficients for estimating individual risk (Publication 103 paras 155–161, A 164).`,
    ]),
  ];
}
/* Where each tissue's input comes from, and the weighting factor that follows. */
function riskBases(sixty, pop) {
  const d = sixty ? detriment60(pop) : detriment103(pop);
  const rows = sixty
    ? [...d.rows.map((r, i) => [r.organ, P60.basis[i], r.rel, P60.wT[i]]), [d.gonads.organ, P60.hereditaryBasis, d.gonads.rel, P60.hereditaryWT]]
    : d.rows.map((r, i) => [r.tissue, P103.basis[i], r.rel, P103.wT[i]]);
  return [
    h('h3', { class: 'dc-h3' }, sixty ? 'Where each F comes from, and the weighting factor that follows' : 'Where each R comes from, and the weighting factor that follows'),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, sixty ? 'Organ' : 'Tissue'), h('th', { class: 'text' }, sixty ? 'Basis of F, per 10 000 per Sv' : 'Basis of R (excess relative : excess absolute risk model)'), h('th', {}, 'Relative detriment'), h('th', { class: 'text' }, ...supText('w_T')))),
      h('tbody', {}, rows.map(([t, b, rel, w]) => h('tr', {}, h('td', {}, t), h('td', { class: 'text' }, ...supText(b)), h('td', {}, rel.toFixed(3)), h('td', { class: 'text' }, w)))))),
    h('p', { class: 'dc-formula' }, ...supText(sixty
      ? 'The relative contributions were rounded into four groups, keeping each within about a factor of 2 of its weighting factor: 0.01 bone surface and skin, 0.05 bladder, breast, liver, oesophagus, thyroid and remainder, 0.12 bone marrow, colon, lung and stomach, 0.20 gonads (para B120).'
      : 'The relative detriments were grouped, keeping each within about a factor of 2 of its weighting factor, with three judgements: cancer and heritable effects in the gonads together (0.08); thyroid at 0.04 for the sensitivity of young children; brain and salivary glands 0.01 each, from the remainder, which keeps 0.12 for its 13 tissues (paras A 157–A 162).')),
  ];
}
/* A printed value, marked where the page's differs from it by more than the
   printing's rounding and by more than 1 % (the inputs are rounded too). */
function printed(mine, value, digits, scale = 1) {
  if (value == null) return h('td', { class: 'dim' }, '–');
  const x = mine * scale;
  const off = Math.abs(x - value) > 0.5 * 10 ** -digits + 1e-9 && Math.abs(x / value - 1) > 0.01;
  return h('td', { class: off ? 'dc-off' : 'dim', 'data-tip': off ? `calculated here: ${(mine * scale).toFixed(digits + 1)}` : null }, value.toFixed(digits));
}
/* Text with superscripts written as Unicode (10⁻² Sv⁻¹) as <sup> -- the
   page's fonts have no superscript minus -- and with subscripts written as
   _x (f_p, w_T) as <sub>. */
const SUP = { '⁻': '−', '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9' };
const supText = (s) => (typeof s !== 'string' ? [s] : s.split(/([⁻⁰¹²³⁴⁵⁶⁷⁸⁹]+|_[A-Za-z]+)/).map((part, i) => (i % 2 === 0 ? part
  : part[0] === '_' ? h('sub', {}, part.slice(1)) : h('sup', {}, [...part].map((c) => SUP[c]).join('')))));
const riskNote = (items) => h('ul', { class: 'dc-notes' }, items.map((x) => h('li', {}, ...[].concat(x).flatMap(supText))));
const riskUnit = (text) => h('span', { class: 'dc-unit' }, ...supText(text));
const kText = (k) => (k < 0.01 ? k.toFixed(3) : k.toFixed(2));
function risk103(pop) {
  const d = detriment103(pop);
  const both = { whole: pop === 'whole' ? d : detriment103('whole'), adult: pop === 'adult' ? d : detriment103('adult') };
  const sumRow = (label, r) => h('tr', {}, h('td', {}, label),
    ...['cancer', 'heritable', 'total'].flatMap((k) => [h('td', { class: 'big' }, r.table1[k].toFixed(2)), printed(r.table1[k], r.published.table1[k], 1), h('td', { class: 'dim' }, r.p60[k].toFixed(1))]));
  const sub = () => [h('th', {}, 'calculated'), h('th', {}, 'Publ. 103'), h('th', {}, 'Publ. 60')];
  const P = d.published.totals;
  return [
    h('h3', { class: 'dc-h3' }, 'Detriment-adjusted nominal risk coefficients', riskUnit('10⁻² Sv⁻¹ (per cent per Sv), Publication 103 Table 1')),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table dc-risk-sum' },
      h('thead', {},
        h('tr', {}, h('th', { rowspan: 2 }, 'Exposed population'), h('th', { colspan: 3 }, 'Cancer'), h('th', { colspan: 3 }, 'Heritable effects'), h('th', { colspan: 3 }, 'Total')),
        h('tr', {}, sub(), sub(), sub())),
      h('tbody', {}, sumRow('Whole population', both.whole), sumRow('Adults (18–64 years)', both.adult)))),
    h('p', { class: 'dc-formula' }, 'For each tissue: detriment D = R · (k + q (1 − k)) · l, with the non-fatal weight q = q', h('sub', {}, 'min'), ' + (1 − q', h('sub', {}, 'min'), ') k',
      ' (Publication 103 Annex A, paras A 141–A 147). Cancer = ΣD over the cancers; heritable effects = R · (k + q (1 − k)) of the gonads; total = ΣD.'),
    h('h3', { class: 'dc-h3' }, `Tissue by tissue: ${d.label}`, riskUnit('cases per 10 000 persons per Sv, Annex A Table A.4.1')),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table dc-risk-steps' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Tissue'), h('th', {}, 'Nominal risk R'), h('th', {}, 'Lethality k'), h('th', {}, 'Non-fatal weight q'),
        h('th', { class: 'nw' }, 'R · (k + q (1 − k))'), h('th', {}, 'Relative life lost l'), h('th', {}, 'Detriment D'), h('th', {}, 'Relative'), h('th', {}, 'Publ. 103 D'), h('th', {}, 'Publ. 103 relative'))),
      h('tbody', {},
        d.rows.map((r) => h('tr', {}, h('td', {}, r.tissue), h('td', {}, pop === 'whole' ? r.R.toFixed(1) : String(r.R)), h('td', { 'data-tip': `printed ${r.kPrinted}` }, r.k.toFixed(3)), h('td', {}, r.q.toFixed(3)),
          h('td', {}, r.adjusted.toFixed(1)), h('td', {}, r.l.toFixed(2)), h('td', { class: 'big' }, r.D.toFixed(1)), h('td', {}, r.rel.toFixed(3)),
          printed(r.D, r.published.D, 1), printed(r.rel, r.published.rel, 3))),
        h('tr', { class: 'sum' }, h('td', {}, 'Total'), h('td', {}, d.total.R.toFixed(pop === 'whole' ? 1 : 0)), h('td', {}), h('td', {}), h('td', {}, d.total.adjusted.toFixed(1)), h('td', {}),
          h('td', {}, d.total.D.toFixed(1)), h('td', {}, '1.000'), printed(d.total.D, P.D, 0), h('td', { class: 'dim' }, '1.000'))))),
    riskNote([
      ['The nominal risks R are lifetime risks of cancer incidence from models fitted to the atomic bomb survivors (excess relative and excess absolute risk), averaged over the sexes, divided by a dose and dose-rate effectiveness factor of 2 (leukaemia: its linear-quadratic model), weighted between the two models (breast and bone marrow absolute only, thyroid and skin relative only, lung 30:70, others 50:50) and averaged over Asian and Euro-American populations; bone and skin are taken from Publication 60, heritable effects are 20 cases per 10 000 per Sv over two generations, 60 % of that for adults (Box A.1, paras A 105–A 124). The life tables and age weights of those averages are not in Annex A, so the calculation here starts from R: ',
        pop === 'whole' ? 'the one-decimal values of Table A.4.2.' : 'Table A.4.1b gives them as whole numbers, which is why single tissues differ from the printed detriment by a few per cent.'],
      'Lethality k from the survival statistics of the US SEER programme (para A 122). Table A.4.5 prints q with a digit more than Table A.4.1 prints k, so k is taken as (q − qmin)/(1 − qmin); qmin is 0.1, 0.2 for thyroid and 0 for skin (para A 145). Pointing at k shows the printed value.',
      'Relative life lost l: the average years of life lost from the cancer, relative to the average over all cancers (para A 147).',
      'Table 1 lists for heritable effects the lethality-adjusted risk (0.2 and 0.1, para A 164), not its detriment (0.25 and 0.15), while its total includes the detriment. The relative detriments are the basis of the tissue weighting factors, grouped and adjusted by judgement (paras A 157–A 162).',
      'The ICRP intends these coefficients for populations, not for estimating the risk of an individual (para A 164).',
    ]),
  ];
}
function risk60(pop) {
  const d = detriment60(pop);
  const both = { whole: pop === 'whole' ? d : detriment60('whole'), adult: pop === 'adult' ? d : detriment60('adult') };
  const sumRow = (label, r) => h('tr', {}, h('td', {}, label),
    ...['fatal', 'nonfatal', 'hereditary', 'total'].flatMap((k) => [h('td', { class: 'big' }, r.table3[k].toFixed(2)), printed(r.table3[k], r.published.table3[k], 1)]));
  const sub = () => [h('th', {}, 'calculated'), h('th', {}, 'Publ. 60')];
  const whole = pop === 'whole';
  const g = d.gonads;
  return [
    h('h3', { class: 'dc-h3' }, 'Nominal probability coefficients for stochastic effects', riskUnit('10⁻² Sv⁻¹ (per cent per Sv), Publication 60 Table 3')),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table dc-risk-sum' },
      h('thead', {},
        h('tr', {}, h('th', { rowspan: 2 }, 'Exposed population'), h('th', { colspan: 2 }, 'Fatal cancer'), h('th', { colspan: 2 }, 'Non-fatal cancer'), h('th', { colspan: 2 }, 'Severe hereditary effects'), h('th', { colspan: 2 }, 'Total')),
        h('tr', {}, sub(), sub(), sub(), sub())),
      h('tbody', {}, sumRow('Adult workers', both.adult), sumRow('Whole population', both.whole)))),
    h('p', { class: 'dc-formula' }, 'For each organ: detriment D = F · (l / l̄) · (2 − k): the fatal cancers F, plus the non-fatal ones, (1 − k) F / k, weighted by the lethality k, both times the relative length of life lost l / l̄ with l̄ = 15.0 years (Publication 60 Annex B, paras B115–B119). Fatal = ΣF; non-fatal = Σ F (1 − k) l / l̄; hereditary = the severe hereditary effects times 20 / 15.'),
    h('h3', { class: 'dc-h3' }, `Organ by organ: ${d.label}`, riskUnit(`per 10 000 persons per Sv, Annex B Table B-20${whole ? '' : ' with 80 % of F; Table 4 in 10⁻² Sv⁻¹'}`)),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table dc-risk-steps' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Organ'), h('th', {}, 'Fatal cancer F'), h('th', {}, 'Life lost l, years'), h('th', {}, 'l / l̄'), h('th', {}, 'Lethality k'), h('th', {}, '2 − k'),
        h('th', {}, 'Detriment D'), h('th', {}, 'Relative'), ...(whole ? [h('th', {}, 'Publ. 60 D'), h('th', {}, 'Publ. 60 relative')] : []), h('th', {}, 'Publ. 60 Table 4'))),
      h('tbody', {},
        d.rows.map((r) => h('tr', {}, h('td', {}, r.organ), h('td', {}, String(+r.F.toFixed(2))), h('td', {}, r.lYears.toFixed(1)), h('td', {}, r.lRel.toFixed(3)), h('td', {}, kText(r.k)),
          h('td', {}, r.twoMinusK.toFixed(3)), h('td', { class: 'big' }, r.D.toFixed(1)), h('td', {}, r.rel.toFixed(3)),
          ...(whole ? [printed(r.D, r.published.product, 1), printed(r.rel, r.published.rel, 3)] : []), printed(r.D, r.published.table4, 2, 0.01))),
        h('tr', {}, h('td', {}, 'Gonads (severe hereditary)'), h('td', { 'data-tip': 'severe hereditary effects, not fatal cancer' }, `(${g.H})`), h('td', {}, g.lYears.toFixed(1)), h('td', {}, g.lRel.toFixed(3)), h('td', {}), h('td', {}),
          h('td', { class: 'big' }, g.D.toFixed(1)), h('td', {}, g.rel.toFixed(3)), ...(whole ? [printed(g.D, g.published.product, 1), printed(g.rel, g.published.rel, 3)] : []), printed(g.D, g.published.table4, 2, 0.01)),
        h('tr', { class: 'sum' }, h('td', {}, 'Total'), h('td', {}, String(+d.sumF.toFixed(2))), h('td', {}), h('td', {}), h('td', {}), h('td', {}), h('td', {}, d.total.toFixed(1)), h('td', {}, '1.000'),
          ...(whole ? [printed(d.total, d.published.total, 1), h('td', { class: 'dim' }, '1.000')] : []), printed(d.total, d.published.table4.total, 1, 0.01))))),
    riskNote([
      'F (Table B-17): the distribution of fatal cancers over the organs (Table B-15: five national populations, multiplicative and additive transfer) times 5 × 10⁻² Sv⁻¹, which is about 10 × 10⁻² Sv⁻¹ for high doses divided by a dose and dose-rate effectiveness factor of 2 (para B113); thyroid, bone surface, skin and liver come from other studies and are taken out of the remainder (paras B107–B114).',
      'Life lost l (Table B-18) relative to l̄ = 15.0 years, the average over all fatal cancers; bone surface, liver, skin and thyroid are set to l̄, severe hereditary effects to 20 years (para B116). Lethality k: Table B-19 (bone marrow as acute leukaemia, bone surface as bone); the remainder’s 0.71 as Table B-20 uses it.',
      'Adult workers: 80 % of F (para B119) and 0.6 × 10⁻² Sv⁻¹ of severe hereditary effects (para 89). Table 4 prints the workers’ bone surface as 0.06 where 80 % of 0.065 gives 0.05.',
      'Table 3 counts fatal cancer without the life-lost weight (its footnote: for fatal cancer the detriment is the probability), so its fatal and non-fatal parts sum to 5.97 and 4.78 where Table 4’s aggregated cancer detriment, weighted throughout, is 5.92 and 4.74; both round to the same totals, 7.3 and 5.6. The relative contributions are the basis of the tissue weighting factors, rounded into four groups (para B120).',
      'The ICRP gives these coefficients for populations of both sexes and a wide range of ages (Table 4, footnote 1).',
    ]),
  ];
}

/* ---- radon and thoron at home ------------------------------------------------------------ */
/* Effective dose per exposure to radon or thoron and their progeny in a home
   (radon.js, ICRP 103): the inhalations run once per gas in the worker; the
   aerosol, the equilibrium factor and the exposure only recombine them. */
const RADON = { co: {}, running: null, progress: null, error: {}, decay: '' };
const radonKind = () => document.querySelector('input[name="dcRadonKind"]:checked')?.value || 'radon';
// Results are kept per gas and decay data (the tab's own choice, ICRP 107 or a release of ENSDF).
const radonKey = (kind) => `${kind}|${RADON.decay}`;
function populateRadonDecay() {
  if (!decayValid(RADON.decay)) RADON.decay = '';
  $('dcRadonDecay').replaceChildren(...decayOptions('103', RADON.decay));
  $('dcRadonDecay').value = RADON.decay;
}
const AGES_TAB = [100, 365, 1825, 3650, 5475, 7300];
function radonDefaults(kind, force) {
  const co = RADON.co[radonKey(kind)];
  if (!co) return;
  const A = co.inputs.aerosol[kind];
  const set = (id, v) => { if (force || $(id).value === '') $(id).value = v ?? ''; };
  set('dcRadonFp', A.fp);
  set('dcRadonFpn', A.modes.find((m) => m.mode === 'n').fpi);
  set('dcRadonF', A.F ?? '');
  // Radon: the upper reference level for homes (Publication 158 para 536);
  // thoron: an example EEC.
  set('dcRadonC', kind === 'radon' ? 300 : 1);
  state.radonKindShown = radonKey(kind);
}
async function ensureRadon(kind) {
  // After a failure, only the Try again button starts it again.
  const key = radonKey(kind), decay = RADON.decay;
  if (RADON.co[key] || RADON.running || RADON.error[key]) return;
  RADON.running = key;
  try { await ensureDecay(decay); } catch (err) { RADON.running = null; RADON.error[key] = err.message; renderRadon(); return; }
  const name = kind === 'radon' ? 'radon' : 'thoron';
  status(`Calculating the doses per exposure to ${name} in a home…`);
  progress(0);
  try {
    // The plan from one worker, then its inhalations in the pool, in parallel.
    const plan = await ask({ type: 'radon-plan', kind, decay }, null, RANK.radon);
    let done = 0;
    const values = await Promise.all(plan.jobs.map((job) => ask({ type: 'radon-job', job, decay }, null, RANK.radon).then((v) => {
      RADON.progress = { done: ++done, total: plan.jobs.length, text: radonJobText(job, plan.ages) };
      status(`${name[0].toUpperCase()}${name.slice(1)} at home: ${done} of ${plan.jobs.length} inhalations…`);
      progress(done / plan.jobs.length);
      if (state.tab === 'radon' && !RADON.co[key]) renderRadon();
      return v;
    })));
    RADON.co[key] = { ...radonAssemble(plan, values), inputs: plan.inputs, decay };
    status(`${name[0].toUpperCase()}${name.slice(1)} at home: done. ICRP 103 system (Publication 158, Section 32), decay data ${decayLabel(decay, '103')}.`, 'ok');
  } catch (err) {
    RADON.error[key] = err.message;
    status(`Could not calculate ${name}: ${err.message}`, 'error');
  } finally {
    RADON.running = null;
    RADON.progress = null;
    progress(null);
    if (state.tab === 'radon') renderRadon();
  }
}
function renderRadon() {
  const kind = radonKind();
  const radon = kind === 'radon';
  $('dcRadonFLabel').hidden = !radon;
  $('dcRadonCLabel').replaceChildren(...supText(radon ? 'Radon concentration, Bq m⁻³' : 'Thoron progeny, EEC, Bq m⁻³'));
  const box = $('dcRadon');
  const key = radonKey(kind);
  const co = RADON.co[key];
  if (!co && RADON.error[key]) {
    box.replaceChildren(...radonContext(kind), h('p', { class: 'dc-muted' }, `The calculation failed: ${RADON.error[key]}`),
      h('button', { type: 'button', class: 'dc-btn secondary', 'data-on-click': 'dc:radonRetry' }, 'Try again'));
    return;
  }
  if (!co) {
    const p = RADON.running === key ? RADON.progress : null;
    box.replaceChildren(...radonContext(kind), h('p', { class: 'dc-muted' }, RADON.running && RADON.running !== key
      ? 'Waiting for the other calculation to finish…'
      : `Calculating the inhalations${p ? `: ${p.text} (${p.done} of ${p.total})` : '…'} This is done once, in parallel on the device’s cores: seconds on a desktop computer.`));
    ensureRadon(kind);
    return;
  }
  if (state.radonKindShown !== key) radonDefaults(kind, true);
  const num = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };
  const fp = Math.min(1, Math.max(0, num('dcRadonFp') ?? 0)), fpn = Math.min(1, Math.max(0, num('dcRadonFpn') ?? 0));
  const F = radon ? Math.min(1, Math.max(0.01, num('dcRadonF') ?? 0.4)) : null;
  const C = Math.max(0, num('dcRadonC') ?? 0), hours = Math.max(0, num('dcRadonHours') ?? 0);
  const r = radonDoses({ radon: co.inputs }, co, { fp, fpn, F });
  const g3 = (x) => (x >= 100 ? x.toFixed(0) : x >= 10 ? x.toFixed(1) : x.toFixed(2));
  const rec = co.inputs.recommended[kind];
  const eec = EEC_J_PER_BQ[kind];
  // Annual dose, mSv: exposure (Bq h m^-3 of gas, or of EEC for thoron) times the dose per exposure.
  const annual = radon ? r.total.map((x) => x * C * hours * 1e3) : r.perEEC.map((x) => x * C * hours * 1e3);
  const annualRec = radon ? rec * C * F * hours * eec * 1e3 : rec * C * hours * eec * 1e3;
  const head = radon
    ? ['Age', 'Progeny, mSv per mJ h m⁻³', 'Progeny, nSv per Bq h m⁻³ EEC', 'Progeny, mSv per WLM', 'Gas, mSv per Bq h m⁻³', `Gas and progeny at F = ${F}, mSv per Bq h m⁻³`, 'Gas and progeny, mSv per mJ h m⁻³', `Year at ${C} Bq m⁻³, ${hours} h: mSv`]
    : ['Age', 'Progeny, mSv per mJ h m⁻³', 'Progeny, nSv per Bq h m⁻³ EEC', 'Progeny, mSv per WLM', 'Thoron gas alone, mSv per Bq h m⁻³', `Year at ${C} Bq m⁻³ EEC, ${hours} h: mSv`];
  const rows = AGES_TAB.map((age, a) => (radon
    ? [AGE_LABEL[age], g3(r.progeny[a]), g3(r.perEEC[a] * 1e9), g3(r.perWLM[a]), sci(r.gas[a] * 1e3, 2), sci(r.total[a] * 1e3, 2), g3(r.totalPerPAE[a]), g3(annual[a])]
    : [AGE_LABEL[age], g3(r.progeny[a]), g3(r.perEEC[a] * 1e9), g3(r.perWLM[a]), sci(r.gas[a] * 1e3, 2), g3(annual[a])]));
  const weights = [fp, (1 - fp) * fpn, (1 - fp) * (1 - fpn)];
  const K = RADON_KINDS[kind];
  return box.replaceChildren(
    ...radonContext(kind),
    h('h3', { class: 'dc-h3' }, 'Effective dose per exposure', riskUnit(`f_p ${fp}, f_pn ${fpn}${radon ? `, F ${F}` : ''}; breathing at home, Table 32.3`)),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table dc-radon-main' },
      h('thead', {}, h('tr', {}, head.map((t, i) => h('th', { class: i ? '' : 'text' }, ...supText(t))))),
      h('tbody', {}, rows.map((cells) => h('tr', {}, cells.map((c, i) => h('td', { class: i === (radon ? 7 : 5) ? 'big' : '' }, ...supText(c))))),
        h('tr', { class: 'sum' }, h('td', {}, 'ICRP recommendation, all ages'), h('td', {}, String(rec)), h('td', {}, g3(rec * eec * 1e9)), h('td', {}, g3(rec * MJ_PER_WLM)),
          ...(radon ? [h('td', {}, '–'), h('td', {}, sci(rec * eec * F * 1e3, 2)), h('td', {}, String(rec))] : [h('td', {}, '–')]), h('td', { class: 'big' }, g3(annualRec)))))),
    h('h3', { class: 'dc-h3' }, 'By aerosol mode', riskUnit('mSv per mJ h m⁻³; E = f_p · unattached + (1 − f_p) [f_pn · nucleation + (1 − f_pn) · accumulation]')),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Age'), h('th', {}, `Unattached (weight ${+weights[0].toFixed(3)})`), h('th', {}, `Nucleation (${+weights[1].toFixed(3)})`),
        h('th', {}, `Accumulation (${+weights[2].toFixed(3)})`), h('th', {}, 'E, progeny'), h('th', {}, ...supText('Breathing rate, m³ h⁻¹')))),
      h('tbody', {}, AGES_TAB.map((age, a) => h('tr', {}, h('td', {}, AGE_LABEL[age]), h('td', {}, g3(r.D.u[a])), h('td', {}, g3(r.D.n[a])), h('td', {}, g3(r.D.a[a])),
        h('td', { class: 'big' }, g3(r.progeny[a])), h('td', {}, String(r.breathing[a]))))))),
    h('h3', { class: 'dc-h3' }, 'Each progeny nuclide in each mode', riskUnit('effective dose coefficient e, Sv per Bq inhaled (Annex C, Table C.8)')),
    h('div', { class: 'dc-table-wrap' }, h('table', { class: 'dc-table' },
      h('thead', {}, h('tr', {}, h('th', {}, 'Nuclide'), h('th', { class: 'text' }, 'Mode'), AGES_TAB.map((age) => h('th', {}, AGE_LABEL[age])))),
      h('tbody', {}, K.progeny.flatMap((nuc) => Object.entries(co.e[nuc] || {}).map(([mode, e]) => h('tr', {}, h('td', {}, nuc), h('td', { class: 'text' }, MODE_LABEL[mode]),
        e.map((x) => h('td', {}, sci(x, 2))))))))),
    riskNote(radonNotes(kind, co, r)),
  );
}
function radonContext(kind) {
  const p = (...kids) => h('p', { class: 'dc-formula' }, ...kids.flatMap(supText));
  return [
    h('h3', { class: 'dc-h3' }, kind === 'radon' ? 'Radon and its progeny in a home' : 'Thoron and its progeny in a home'),
    p(kind === 'radon'
      ? 'Radon (²²²Rn) seeps from the ground into houses. Breathing it, most of the dose comes not from the gas, which is mostly breathed out again, but from its short-lived progeny ²¹⁸Po, ²¹⁴Pb and ²¹⁴Bi (with ²¹⁴Po), which are metals: they stick to the aerosol in the air or stay as tiny unattached clusters, deposit in the airways, and irradiate the bronchial epithelium with alpha particles. Their dose is reckoned per exposure, the potential alpha energy concentration of the progeny (PAEC) times the time spent in it, in mJ h m⁻³; the working level month (WLM) is 3.54 mJ h m⁻³. A measured radon gas concentration gives the progeny’s equilibrium equivalent concentration (EEC) through the equilibrium factor F, typically 0.4 indoors.'
      : 'Thoron (²²⁰Rn) comes from building materials and soil; with a half-life of 56 s it hardly spreads from where it is released, so its gas concentration varies across a room and no reference equilibrium factor is used. The dose comes from its progeny ²¹²Pb (10.6 h) and ²¹²Bi, measured as their equilibrium equivalent concentration (EEC); 1 Bq m⁻³ of EEC is 7.56 × 10⁻⁵ mJ m⁻³ of potential alpha energy.'),
    h('p', { class: 'dc-muted' }, RADON.decay
      ? `Decay data: ${decayLabel(RADON.decay, '103')}, made on this site from ENSDF (Help: “Decay data”); Publication 158’s values are of ICRP 107.`
      : 'Decay data: ICRP 107, as Publication 158’s values.'),
    p('The calculation follows Publication 158 (Section 32, Annex C) with the method of Publication 137 (Annex A): each progeny nuclide inhaled in each mode of the home aerosol — unattached (1 nm), nucleation (', kind === 'radon' ? '30' : '40', ' nm) and accumulation (200 nm), the attached modes growing in the humid airways — is calculated here as an inhalation with the deposition of Table C.1, the absorption of Table 32.1 and its element’s systemic model; the modes are combined per unit potential alpha energy with the progeny’s activity ratios, and weighted by the unattached fraction f_p and the nucleation share f_pn of Table 32.2, which you can change above.'),
  ];
}
function radonNotes(kind, co, r) {
  const radon = kind === 'radon';
  const K = RADON_KINDS[kind];
  return [
    `Per mode, the dose per unit potential alpha energy exposure is B Σ r e / Σ r ε: the breathing rate B, and for each nuclide its activity ratio r (${radon ? 'unattached 1 : 0.1 : 0, attached 1 : 0.75 : 0.6 for ²¹⁸Po : ²¹⁴Pb : ²¹⁴Bi' : 'unattached 1 : 0, attached 1 : 0.25 for ²¹²Pb : ²¹²Bi'}, Publication 137 paras A80–A81), its dose coefficient e and its potential alpha energy per becquerel ε (${K.progeny.map((n) => `${n} ${sci(PAE_PER_BQ[n], 2)} J`).join(', ')}; Table A.1).`,
    `The gas: its dose coefficient per becquerel inhaled (${sci(co.gas[co.gas.length - 1], 2)} Sv for the adult, the radon model) times the rate at which lung air is breathed out, λ, and the volume of lung air, V, over 24 h (Annex C para C 18).${radon ? ` With the values above the gas gives ${(100 * r.gas[r.gas.length - 1] / r.total[r.total.length - 1]).toFixed(1)} % of the adult’s dose.` : ' Thoron gas varies across a room, so its dose is shown per unit gas concentration, apart from the progeny.'}`,
    'The dose per exposure hardly depends on age (Publication 158 para 528): children breathe less, which lowers the intake, but their smaller airways and lungs take more dose per unit deposited.',
    radon
      ? 'The ICRP recommends one rounded coefficient for every age, 3 mSv per mJ h m⁻³ (about 10 mSv per WLM; 6.7 × 10⁻⁶ mSv per Bq h m⁻³ of radon gas at F = 0.4), the value for workers, between the calculated 3–4 and the 2.5 that epidemiology of the general public gives (paras 532–536); 300 Bq m⁻³ for 7000 hours a year at F = 0.4 gives 14 mSv with it.'
      : 'The ICRP recommends 1 mSv per mJ h m⁻³ for thoron progeny at every age (about 4 mSv per WLM, about 80 nSv per Bq h m⁻³ of EEC; para 537).',
    radon
      ? 'More unattached progeny (a higher f_p, clean air with few particles) raise the dose per exposure; without a nucleation mode (f_pn = 0) it falls by about 20 % (Table C.9).'
      : 'Table C.1 gives the deposition of the 200 nm accumulation mode for the radon progeny’s spread (σg = 2.0), not for the narrower one of thoron progeny (σg = 1.8), and the page uses it: this mode comes out 3–11 % higher than in Table C.8, and the dose per exposure 2–5 % higher than in Table 32.8.',
    radon ? 'Each chain is followed to ²¹⁰Pb, which with its own progeny adds less than 0.01 %.' : 'The progeny of ²¹²Bi, ²¹²Po and ²⁰⁸Tl, decay where they are formed within minutes.',
  ];
}

/* ---- tooltips ------------------------------------------------------------------------------ */
/* The page's own tooltip for every [data-tip] (the boxes, arrows and body of
   the Model tab, marked values): shown after 80 ms, where the browser's
   native one waits about a second, and in the page's theme, where the native
   one follows the operating system's (dark on a light page when the system
   is dark). It follows the pointer and keeps inside the window. */
function setupTips(root) {
  const tip = h('div', { class: 'dc-tip', role: 'tooltip' });
  document.body.append(tip);
  let target = null, timer = 0, at = [0, 0];
  const place = () => {
    const r = tip.getBoundingClientRect();
    const [x, y] = at;
    const left = Math.min(x + 14, innerWidth - r.width - 8);
    const top = y + 20 + r.height > innerHeight - 8 ? y - r.height - 12 : y + 20;
    tip.style.left = `${Math.max(8, left)}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  };
  const show = () => {
    if (!target) return;
    tip.replaceChildren(...supText(target.getAttribute('data-tip')));
    tip.classList.add('on');
    place();
  };
  const hide = () => { clearTimeout(timer); target = null; tip.classList.remove('on'); };
  root.addEventListener('pointerover', (ev) => {
    const t = ev.target.closest?.('[data-tip]');
    at = [ev.clientX, ev.clientY];
    if (t === target) return;
    hide();
    if (!t?.getAttribute('data-tip')) return;
    target = t;
    timer = setTimeout(show, 80);
  });
  root.addEventListener('pointermove', (ev) => { at = [ev.clientX, ev.clientY]; if (tip.classList.contains('on')) place(); });
  root.addEventListener('pointerleave', hide);
  root.addEventListener('focusin', (ev) => {
    const t = ev.target.closest?.('[data-tip]');
    if (!t?.getAttribute('data-tip')) return;
    const r = t.getBoundingClientRect();
    target = t;
    at = [r.left, r.bottom - 12];
    show();
  });
  root.addEventListener('focusout', hide);
  window.addEventListener('scroll', hide, true);
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') hide(); });
}

/* ---- tabs, layout ----------------------------------------------------------------------- */
function renderAll() {
  renderCoef();
  if (state.tab === 'retention') renderRetention();
  if (state.tab === 'model') renderModel();
  if (state.tab === 'chain') renderChain();
  if (state.tab === 'risk') renderRisk();
  if (state.tab === 'radon') renderRadon();
  markStale();
}
function showTab(tab) {
  state.tab = tab;
  if (tab !== 'model') viewStop();
  for (const b of document.querySelectorAll('.dc-tabs button')) {
    const on = b.dataset.tab === tab;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  }
  for (const p of document.querySelectorAll('.dc-pane')) p.hidden = p.id !== `pane-${tab}`;
  // The Batch and Radon at home tabs have settings of their own: those of the side rest meanwhile.
  const own = { batch: 'The Batch tab', radon: 'Radon at home' }[tab];
  $('dcRoot').classList.toggle('dc-side-away', !!own);
  $('dcSideNote').hidden = !own;
  if (own) $('dcSideNote').textContent = `These settings are for a single calculation and its tabs. ${own} has its own, so they rest here while it is open; they still work.`;
  hidePlotTip();
  if (tab === 'retention') renderRetention();
  if (tab === 'model') renderModel();
  if (tab === 'chain') renderChain();
  if (tab === 'risk') renderRisk();
  if (tab === 'radon') renderRadon();
  if (tab === 'batch') batch?.render();
  save();
}

function setupResize() {
  const handle = $('dcResize');
  const root = $('dcRoot');
  let drag = false;
  const set = (px) => {
    const w = Math.max(240, Math.min(px, window.innerWidth * 0.6));
    root.style.setProperty('--dc-side-width', `${w}px`);
  };
  handle.addEventListener('pointerdown', (e) => { drag = true; handle.classList.add('active'); handle.setPointerCapture(e.pointerId); });
  handle.addEventListener('pointermove', (e) => { if (drag) set(e.clientX - root.getBoundingClientRect().left); });
  const end = () => { if (!drag) return; drag = false; handle.classList.remove('active'); save(); resizePlots(); };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
  handle.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    set($('dcSide').getBoundingClientRect().width + (e.key === 'ArrowRight' ? 20 : -20));
    save();
    resizePlots();
  });
}

/* ---- links --------------------------------------------------------------------------------- */
function writeHash() {
  const r = state.result;
  if (!r) return;
  const p = new URLSearchParams({ system: r.system, nuclide: r.entry.name, route: r.spec.route, form: r.form.key });
  if (r.decay) p.set('decay', r.decay);
  if (r.amad) p.set('amad', String(r.amad));
  history.replaceState(null, '', `#${p}`);
}
function readHash() {
  try {
    const p = new URLSearchParams(location.hash.slice(1));
    if (!p.get('nuclide')) return null;
    return { system: p.get('system'), decay: p.get('decay') || '', nuclide: p.get('nuclide'), route: p.get('route'), form: p.get('form'), amad: p.get('amad'), run: true };
  } catch { return null; }
}

/* ---- the (i) panels ------------------------------------------------------------------------ */
/* Each topic: what the setting or tab is, how it enters the calculation, how
   to choose, and where Help says more. A topic that is a function is read
   each time its panel opens, so that it can say what is chosen now. */
const SYSTEM_CHOICES = [
  ['ICRP 60', 'The models of Publications 56–71 and the dosimetry of the 1990 Recommendations: the coefficients of Publication 72, compiled in Publication 119 and used in the IAEA Basic Safety Standards. Calculated as DCAL, the ICRP’s software for them, does. External exposure as Federal Guidance Report 12 calculates it.', '60'],
  ['ICRP 103', 'The 2007 Recommendations: Publication 158 (Part 1: hydrogen to radium) and the consultation drafts of Part 2 (lanthanides and actinides) and Part 3 (35 more elements, beryllium to francium), with the respiratory tract of Publication 130, the alimentary tract of Publication 100 and the reference phantoms of Publications 110 and 143. External exposure as Federal Guidance Report 15 (2025) calculates it.', '103'],
];
const ROUTE_TEXT = { ingestion: 'ingestion', inhalation: 'inhalation', injection: 'injection (direct uptake to blood)', external: 'external exposure (dose rate per unit concentration)' };
const sysName = () => (state.system === '60' ? 'ICRP 60' : 'ICRP 103');
const TOPICS = {
  'sec:system': () => ({
    kicker: 'Section', title: 'System',
    lead: 'Which generation of the ICRP’s models and dosimetry to calculate with. The two give different numbers for the same intake or exposure, sometimes by a factor of several, so every result says which system it comes from.',
    sections: [
      { choices: SYSTEM_CHOICES.map(([a, b, k]) => [a, b, state.system === k]) },
      { heading: 'What differs between them', list: [
        'Tissue weighting factors: those of Publication 60 (twelve tissues and a remainder of ten, with its splitting rule), or of Publication 103 (fourteen tissues and a remainder of thirteen, on the average of the sexes).',
        'Phantoms: the Cristy–Eckerman stylised phantoms, one per age, or the voxel reference phantoms of Publications 110 and 143, male and female at each age.',
        'Respiratory tract: Publication 66, or its revision in Publication 130; alimentary tract: the ICRP 30 model, or the Human Alimentary Tract Model of Publication 100.',
        'Systemic models and decay data: those of Publications 56–71 with Publication 38, or the revised models of Publication 158 and the OIR series with Publication 107. The decay data can be ENSDF’s instead (the Decay data setting).',
        'External exposure: Federal Guidance Report 12 (the adult hermaphrodite phantom; e with the weighting factors of Publication 60, and the report’s own effective dose equivalent beside it), or Federal Guidance Report 15 (hermaphrodite phantoms of six ages; e with those of Publication 103).',
      ] },
      { heading: 'Which to use', text: 'The ICRP 60 system is still the basis of the IAEA Basic Safety Standards and of many national regulations; the ICRP 103 system is the current one, the one new assessments move to. Switching keeps the last results on their tabs, marked as of the other system until you calculate again.' },
    ],
    more: { label: 'The two systems', id: 'help-systems' },
  }),
  'set:decay': () => {
    const cat = currentCatalog();
    const own = state.system === '60'
      ? 'Publication 38 (1983), as DCAL distributes it: the decay data the ICRP 60 system’s coefficients were calculated with.'
      : 'Publication 107 (2008): the decay data of the ICRP 103 system, with which the ICRP calculates its coefficients.';
    return {
      kicker: 'Setting', title: 'Decay data',
      lead: 'Where the half-lives, the daughters and the radiations of each nuclide come from: the energies and yields per decay from which the doses to the tissues are built, after an intake and in external exposure alike. The models of the body, and the reports’ dose per photon and per electron, do not change with them.',
      facts: [['Chosen', decayLabel(state.decay, state.system)], ['Covered', cat ? `${cat.nuclides.length} radionuclides in the ${sysName()} system` : null]],
      sections: [
        { choices: [[OWN_DECAY[state.system], own, !state.decay],
          ...DECAY.releases.map((r) => [r.label, 'Made on this site from the decay data sets of this release of the Evaluated Nuclear Structure Data File, the way Publication 107 was made from those of 2004.', state.decay === `ensdf:${r.id}`]),
          ...DECAY.opened.map((r) => [`${r.label} (opened ${openedDate(r)})`, 'Opened in this browser and made here by the same program; kept until you choose Forget.', state.decay === `open:${r.key}`])] },
        { heading: 'How ENSDF becomes decay data here', list: [
          'Gamma rays, conversion electrons, alpha groups and beta and capture branches as each decay data set gives them, per decay as its normalisation says.',
          'Beta spectra from Fermi theory, X-rays and Auger electrons from the vacancies that capture and conversion leave, spontaneous fission from the formulas of Publication 107.',
          'Run on the data sets Publication 107 was made from, the same program reproduces its dose coefficients within 1 % for nearly every nuclide.',
        ] },
        { heading: 'Good to know', list: [
          'Nuclides keep the names their system gives them; where ENSDF names a state otherwise, the page pairs them by half-life, and the Decay chain tab gives ENSDF’s name beside.',
          'The ICRP’s published coefficients are of its own decay data, and so are the Federal Guidance Reports’ (Publication 38 for FGR 12, Publication 107 for FGR 15); with ENSDF the results differ from them where the evaluations have changed since.',
          'Open ENSDF… adds any release: a zip as NNDC publishes it, or ENSDF files, read and made into decay data in your browser in some ten seconds, nothing uploaded. It is kept in this browser, here and on the Chart of Nuclides, until Forget; the menus list NNDC’s archive with where to download each release.',
          'The choice is kept for the next visit and goes into the link of a result. The Batch and Radon at home tabs have the same choice of their own.',
        ] },
      ],
      more: { label: 'Decay data', id: 'help-decay' },
    };
  },
  'sec:nuclide': () => ({
    kicker: 'Section', title: 'Radionuclide',
    lead: 'The radionuclide taken into the body, or for external exposure the one in the air, water or soil around it. Taken in, its radioactive progeny formed in the body are followed too and count towards its dose coefficient, which is per becquerel of the parent taken in. Around the body, the coefficient is of the nuclide alone and, beside it, with its progeny in equilibrium, per unit concentration of the parent.',
    facts: [['Covered now', currentCatalog() ? `${currentCatalog().nuclides.length} radionuclides in the ${sysName()} system${state.decay ? ` with ${decayLabel(state.decay, state.system)}` : ''}` : null]],
    sections: [{ heading: 'Before you calculate', list: [
      'The foot of the settings sums up the model that Calculate will solve: the nuclides the decay chain cut-off keeps, the compartments, the transfers and the equations; for external exposure, the progeny in equilibrium and the report.',
      'The Model and Decay chain tabs show the chosen radionuclide’s models and chain at once, before any calculation; for external exposure, the report’s dose per photon and the chain’s activities in equilibrium.',
      'For many radionuclides at once, use the Batch tab.',
    ] }],
    more: route() === 'external' ? { label: 'External exposure', id: 'help-external' } : { label: 'Progeny', id: 'help-progeny' },
  }),
  'set:nuclide': () => ({
    kicker: 'Setting', title: 'Nuclide',
    lead: 'Type a name such as Cs-137, I-131 or Am-242m; the list under the field suggests what the chosen system covers.',
    facts: [['Chosen', state.entry ? `${state.entry.name}${state.entry.T ? `, half-life ${halfLife(state.entry.T)}` : ''}` : null]],
    sections: [
      { heading: 'What is covered', list: [
        'Intakes, ICRP 60: the nuclides of Publication 72, with its decay data (Publication 38).',
        'Intakes, ICRP 103: the nuclides of Publication 107 with half-lives of at least 10 minutes (Publication 158 section 1.4.1), of the elements whose models Publication 158 and the Part 2 and 3 drafts give. Shorter-lived ones are followed as progeny.',
        'External exposure: every radionuclide of the decay data, in both systems (838 of Publication 38, 1252 of Publication 107), noble gases and short-lived ones too; a nuclide with no model of the body has that route only.',
      ] },
      { heading: 'Typing', list: [
        'cs137, Cs-137 and Cs 137 all mean Cs-137; a metastable state ends in m: Tc-99m, Am-242m.',
        'The arrow keys move through the suggestions, Enter takes one, Escape closes the list.',
        'A name the decay data do not have is said so under the field, and a nuclide with external exposure only says why.',
      ] },
    ],
    more: { label: 'The two systems', id: 'help-systems' },
  }),
  'sec:intake': () => ({
    kicker: 'Section', title: 'Intake',
    lead: 'How the radionuclide enters the body and in what chemical or physical form. Together they decide where it deposits or is absorbed, how fast it reaches blood, and so where the dose goes. Or, for external exposure, where it is around the body.',
    sections: [{ heading: 'The routes', list: [
      '**Ingestion**: swallowed; absorbed to blood from the small intestine with the form’s fraction fA (f1 in the ICRP 60 system), the rest passes through the gut.',
      '**Inhalation**: deposited in the respiratory tract according to the aerosol size; absorbed from there at the form’s dissolution rates, or carried up the airways and swallowed.',
      '**Injection** (ICRP 103 system only): straight into blood, as from a wound or through skin that absorbs it at once.',
      '**External**: nothing taken in; the dose rate from the radionuclide in air, water or soil around the body, per unit concentration, as Federal Guidance Reports 12 (ICRP 60) and 15 (ICRP 103) give it. The form is then the geometry.',
    ] }],
    more: route() === 'external' ? { label: 'External exposure', id: 'help-external' } : { label: 'The ICRP 103 system as calculated here', id: 'help-103' },
  }),
  'set:route': () => ({
    kicker: 'Setting', title: 'Route',
    lead: 'Ingestion (swallowed in food or water), inhalation (breathed in as an aerosol, a gas or a vapour), injection (direct uptake to blood), or external exposure to the radionuclide in the air, water or soil around the body.',
    facts: [['Chosen', ROUTE_TEXT[route()]]],
    sections: [
      { heading: 'The models behind them', list: [
        'Ingestion: the Human Alimentary Tract Model of Publication 100 (ICRP 103), or the ICRP 30 gastrointestinal model (ICRP 60).',
        'Inhalation: the respiratory tract model of Publication 130 (ICRP 103) or Publication 66 (ICRP 60); what is cleared from the lungs is swallowed, so an inhalation also gives a dose by way of the gut.',
        'Injection: the activity starts in the systemic model’s blood (for polonium, Plasma 2).',
        'External: the dose per photon and per electron of Federal Guidance Report 15 (ICRP 103 system; the phantoms of six ages) or 12 (ICRP 60; the adult), added up over the nuclide’s radiations. The coefficient is a dose rate per Bq per m³ (per m² on the ground), not a dose per Bq taken in.',
      ] },
      { heading: 'Good to know', list: [
        'Injection is calculated in the ICRP 103 system only. The annex of Publication 158 gives it, for interpreting bioassay data; the ICRP 60 system’s publications give no coefficients for it for members of the public.',
        'External exposure covers every radionuclide of the decay data; the reports give the nuclide alone, and the page adds its progeny in equilibrium beside it.',
        'A route for which the radionuclide has no form is greyed out; pointing at it says why.',
      ] },
    ],
    more: route() === 'external' ? { label: 'External exposure', id: 'help-external' } : { label: 'The ICRP 103 system as calculated here', id: 'help-103' },
  }),
  'set:form': () => (route() === 'external' ? {
    kicker: 'Setting', title: 'Geometry',
    lead: 'Where the radionuclide is around the person: the air, water or ground, and how deep in the soil. The coefficients are dose rates per unit concentration there.',
    facts: [['Chosen', currentForm()?.label || null], ['Per', currentForm()?.key === 'surface' ? 'Bq per m² of ground' : currentForm() ? 'Bq per m³ of air, water or soil' : null]],
    sections: [
      { heading: 'The geometries', list: [
        'Submersion in air: a semi-infinite cloud over uncontaminated ground (FGR 15 takes half the dose of an infinite cloud).',
        'Immersion in water: an infinite volume of water around the body.',
        state.system === '60' ? 'Ground surface: a smooth plane at the air–ground interface (FGR 12).' : 'Ground surface: the photons from 3 mm deep (0.5 g/cm²) for the ground’s roughness, the electrons from the surface (FGR 15).',
        'Soil to 1, 5 or 15 cm, or infinitely deep: a uniform concentration from the surface down, soil of 1.6 g/cm³.',
      ] },
      { heading: 'Good to know', list: [
        'The person stands on the ground, the dose to the skin taken at 1 m for electrons from the ground; nothing is shielded by buildings or clothes, as in the reports.',
        'The electrons count for the skin only; bremsstrahlung from their slowing down reaches every tissue.',
      ] },
    ],
    more: { label: 'External exposure', id: 'help-external' },
  } : {
    kicker: 'Setting', title: 'Chemical or physical form',
    lead: 'The forms the publications list for the element by this route, each with its absorption. Where the form is unknown the publications recommend a default, marked “(default)”.',
    facts: [['Chosen', currentForm()?.label || null]],
    sections: [
      { heading: 'Inhaled', list: [
        'Type F (fast), M (moderate) or S (slow): the default dissolution rates of Publication 130 (ICRP 103) or 66 (ICRP 60), or the element’s material-specific values where its section gives them.',
        'Gases and vapours (tritiated water, carbon dioxide, elemental iodine, radon…) have their own deposition and absorption, and no aerosol size.',
        'The absorption also sets what material cleared from the lungs gives to blood from the gut: fr × fA in the ICRP 103 system.',
      ] },
      { heading: 'Ingested', list: [
        'fA (ICRP 103) or f1 (ICRP 60): the fraction absorbed to blood. It is often higher for infants; the label shows the adult’s value and the Model tab all ages’.',
      ] },
      { heading: 'Which to choose', text: 'The form of the material in question where it is known; otherwise the default, which the ICRP recommends for the element when the form is unknown. The Model tab lists the chosen form’s absorption parameters and its deposition in the airways.' },
    ],
    more: { label: 'The ICRP 103 system as calculated here', id: 'help-103' },
  }),
  'set:amad': () => ({
    kicker: 'Setting', title: 'Aerosol size',
    lead: 'The activity median aerodynamic diameter (AMAD) of the aerosol, or for the smallest particles the thermodynamic one (AMTD). It decides where in the respiratory tract the particles deposit.',
    facts: [
      ['Chosen', $('dcAmadRow').hidden ? null : $('dcAmad').selectedOptions[0]?.textContent],
      ['Default', '1 µm AMAD, the ICRP’s value for members of the public'],
      ['Workers', '5 µm AMAD, the value of the OIR series'],
      ['Sizes', state.system === '103' ? '0.001–20 µm (AMTD below 0.3 µm)' : '0.3–10 µm'],
    ],
    sections: [{ heading: 'What it changes', list: [
      'Particles of several micrometres deposit mostly in the nose and throat (ET1, ET2) and are swallowed or blown out; smaller ones reach the alveoli (AI), where insoluble material can stay for years.',
      'Nanometre particles deposit by diffusion, both high in the airways and in the alveoli.',
      'For a soluble (Type F) form the size matters less than for Type S, where the alveolar deposit decides the lung dose.',
      'The deposition at each age is listed on the Model tab, under Respiratory tract.',
    ] }],
    more: { label: 'The ICRP 103 system as calculated here', id: 'help-103' },
  }),
  'sec:ages': () => (route() === 'external' ? {
    kicker: 'Section', title: 'Ages',
    lead: 'The ages of the reports’ phantoms: for the ICRP 103 system Federal Guidance Report 15’s newborn, 1, 5, 10 and 15 years and reference adult; for the ICRP 60 system Federal Guidance Report 12’s adult only, the other ages greyed out. Each ticked age is a column of the results.',
    facts: [['Ticked', ages().map((a) => ageLabel(a, true)).join(', ') || 'none']],
    sections: [{ heading: 'How age enters', list: [
      'Each phantom has its own dose per photon: a smaller body shields its organs less, so a child’s dose rate is higher than an adult’s, most for low-energy photons.',
      'The skin’s dose from electrons is the same at every age (FGR 15 Appendix C).',
      'FGR 15’s reference adult takes the adult phantom for the male and the 15-year-old’s for the female.',
    ] }],
    more: { label: 'External exposure', id: 'help-external' },
  } : {
    kicker: 'Section', title: 'Ages at intake',
    lead: 'The six reference ages of the ICRP’s coefficients for members of the public. Each ticked age is a calculation of its own.',
    facts: [
      ['Ticked', ages().map((a) => AGE_LABEL[a]).join(', ') || 'none'],
      ['Commitment period', '50 years for adults; up to age 70 for children'],
      ['The adult', 'takes it in at 20 years; at 25 for the alkaline earths, lead and the actinides (in the ICRP 103 system also yttrium, zirconium, niobium, hafnium, tantalum and francium), whose models change with bone growth until then'],
    ],
    sections: [{ heading: 'How age enters', list: [
      'The models’ transfer rates change with age and are interpolated linearly between the reference ages, so a child’s model grows up during the commitment period.',
      'The dose per transformation changes as the body grows: in the ICRP 60 system by the weights DCAL gives the phantoms (following growth up to 5 years, linear in age after); in the ICRP 103 system by a monotone cubic spline, in the first year with a weighting that follows the growth curves of Publication 89.',
      'The ages run in parallel, as many at a time as the device has cores to spare; fewer ages finish sooner.',
    ] }],
    more: { label: 'How the calculation is done', id: 'help-numerics' },
  }),
  'sec:calc': {
    kicker: 'Section', title: 'Calculation',
    lead: 'How much of the decay chain to follow, and how precisely to integrate. The defaults reproduce the ICRP’s coefficients to well within their two significant figures; change them to check that a result does not depend on them.',
    facts: [['Decay chain cut-off', '0.01 % by default (ICRP 103 system)'], ['Relative tolerance', '1E-6 by default']],
    sections: [{ heading: 'When to change them', list: [
      'No cut-off, to follow the whole chain as the publications do; or a coarser one, for a quicker look at a long chain.',
      'A looser tolerance (1E-4) for a quicker run, a tighter one (1E-8) to see that a result does not change.',
      'The foot of the settings shows what the cut-off keeps; the Decay chain tab lists what it leaves out.',
    ] },
    { heading: 'External exposure', text: 'Nothing to integrate, and the whole chain taken as far as it is in equilibrium with the parent: the section is hidden while the route is External.' }],
    more: { label: 'How the calculation is done', id: 'help-numerics' },
  },
  'set:cutoff': () => {
    const c = state.described?.info?.cutoffs?.find((x) => String(x.cutoff) === String(Number($('dcCutoff').value)));
    return {
      kicker: 'Setting', title: 'Decay chain cut-off',
      lead: 'ICRP 103 system: progeny are followed down the chain until they carry less than this share of the energy that the chain emits over 100 years after 1 Bq of the parent (alpha energy weighted by 20). Those left out are listed on the Decay chain tab.',
      facts: [
        ['Chosen', `${$('dcCutoff').selectedOptions[0]?.dataset.text || $('dcCutoff').selectedOptions[0]?.textContent || ''}${c && state.entry ? `: ${c.nuclides} nuclides of the chain of ${state.entry.name}` : ''}`],
        ['Default', '0.01 %'],
      ],
      sections: [
        { heading: 'Choosing', list: [
          'none: every member of the chain, as the publications do; slowest for the long chains (Th-232, U-238, Ra-226).',
          '0.001 %, 0.01 % or 0.1 %: members that carry so little of the energy are left out, and the coefficient changes by about as much or less.',
          'Each option in the list says how many nuclides it keeps of the chosen radionuclide’s chain.',
        ] },
        { heading: 'ICRP 60 system', text: 'Chains are cut as DCAL cut them for Publication 72: where its batch files say, else at 0.1 %.' },
        { heading: 'External exposure', text: 'No cut-off: the nuclide alone, and with every member in equilibrium with it.' },
      ],
      more: { label: 'Progeny', id: 'help-progeny' },
    };
  },
  'set:rtol': () => ({
    kicker: 'Setting', title: 'Relative tolerance',
    lead: 'The relative error the integrator keeps each step to: a variable-order backward differentiation method (NDF) with the exact sparse Jacobian, restarted wherever a rate table has a corner.',
    facts: [
      ['Chosen', $('dcRtol').value.toUpperCase()],
      ['1E-6, the default', 'e within 3 parts in 10 million of its value at 1E-8'],
      ['1E-4', 'about 1.4 times faster; e within 0.001 % of its value at 1E-8'],
      ['1E-8', 'about 1.6 times slower than 1E-6; for checking that a result has converged'],
    ],
    sections: [{ heading: 'What it controls', text: 'Every compartment’s activity, and every integral of activity from which the doses are put together, is kept to this relative error at each step. Any of the three is far finer than the two significant figures of the ICRP’s tables: the models themselves are the uncertainty, not the arithmetic.' }],
    more: { label: 'How the calculation is done', id: 'help-numerics' },
  }),
  'tab:coef': () => (external(state.result) ? {
    kicker: 'Tab', title: 'Coefficients',
    lead: 'The effective dose rate per unit concentration, e, at each age: of the nuclide alone, as the Federal Guidance Reports give it, and with its progeny in equilibrium; and the equivalent dose rates of the tissues.',
    sections: [
      { heading: 'Reading the tables', list: [
        'Sv per second (as the reports give them), per hour or per year, per Bq/m³ of air, water or soil, or per Bq/m² of ground.',
        'e from photons · bremsstrahlung · electrons: the parts of the nuclide’s own e; the electrons count through the skin’s weight.',
        'In the ICRP 60 system HE beside e: the effective dose equivalent of ICRP 26 that Federal Guidance Report 12 tabulates.',
        'The switch above the tissues: the nuclide alone, or with its progeny in equilibrium (each member at its activity per Bq of the parent, listed on the Decay chain tab).',
        'Bars (the box above the tissues): each tissue’s share of e at that age, as a bar behind its number, the cell’s width being all of e. Solid for the terms of e, which add up to the whole: each weighted tissue (wT × its dose rate) and the remainder; light for their parts: the remainder’s tissues (equally in the ICRP 103 system, by mass or the splitting rule in the ICRP 60 system), the testes and ovaries of the gonads, the halves of the colon. Pointing at a cell gives its percentage.',
        'Digits: two by default (the reports print three); three or four for comparing.',
        'When a setting has changed since the calculation, a note says so and the numbers are dimmed until you calculate again.',
      ] },
      { heading: 'Saving', text: 'Save as CSV writes e, and every tissue’s dose rate, alone and with the progeny, at every age, in the unit chosen.' },
    ],
    more: { label: 'External exposure', id: 'help-external' },
  } : {
    kicker: 'Tab', title: 'Coefficients',
    lead: 'The committed effective dose per becquerel taken in, e(τ), at each age at intake, and the committed equivalent doses to the tissues that make it up.',
    sections: [
      { heading: 'Reading the tables', list: [
        'e(50) for adults is committed over 50 years; e(70) for children, up to age 70.',
        'The equivalent doses are of the tissues weighted in e, of the remainder’s tissues and of some others; in the ICRP 103 system the average of the sexes, or male or female (the switch above the table).',
        'Bars (the box above the table): each tissue’s share of e at that age, as a bar behind its number, the cell’s width being all of e. Solid for the terms of e, which add up to the whole: each weighted tissue (wT × its dose) and the remainder; light for their parts: each remainder tissue (equally in the ICRP 103 system; by mass, or the splitting rule, in the ICRP 60 system), the gonad taken (ICRP 60) and the halves of the colon. Pointing at a cell gives its percentage.',
        'Digits: two, as the ICRP prints them; three or four for comparing. The models are not that precise.',
        'When a setting has changed since the calculation, a note says so and the numbers are dimmed until you calculate again.',
      ] },
      { heading: 'Saving', text: 'Save as CSV writes the effective dose and every equivalent dose at every age, to six significant figures.' },
    ],
    more: { label: 'Checking it', id: 'help-checks' },
  }),
  'tab:retention': {
    kicker: 'Tab', title: 'Retention',
    lead: 'How 1 Bq of the parent behaves after the intake, at one age at intake: where the activity is, how it leaves the body, and how the dose builds up. All per Bq of the parent taken in, with radioactive decay.',
    sections: [
      { heading: 'Activity', list: [
        'Nuclide: the parent or one of its progeny; activities of different nuclides are never added up.',
        'In the body regions (respiratory tract, alimentary tract, urinary bladder, systemic tissues and blood) with their whole-body sum; in its source regions (the fourteen highest); or every member’s whole-body activity side by side.',
        'A model that differs between the sexes (radon) shows the male model’s activities.',
      ] },
      { heading: 'Excretion', text: 'The chosen nuclide’s daily excretion in urine and in faeces.' },
      { heading: 'Dose', list: [
        'The committed effective dose received up to each time (the thick line), and under Dose by the curves it is the sum of: by body region, source region or chain member of the activity the dose comes from, or by tissue that receives it (its weighted dose).',
        'The twelve largest are drawn and the rest added up in one more curve.',
      ] },
      { heading: 'Reading the charts', list: [
        'Pointing at a chart lists the values at that time, largest first, with each part’s share of its total in brackets.',
        'Drag to zoom, double-click to zoom out; the camera above a chart saves it as a picture.',
      ] },
      { heading: 'External exposure', text: 'Nothing is taken into the body, so there is nothing to retain or excrete and no commitment period: the coefficients are dose rates per unit concentration, and the dose of an exposure is the coefficient times the concentration integrated over the time exposed. The tab says so in place of its charts.' },
    ],
    more: { label: 'How the calculation is done', id: 'help-numerics' },
  },
  'tab:model': () => (shownSystem()?.first?.external || (!shownSystem() && route() === 'external') ? {
    kicker: 'Tab', title: 'Model',
    lead: 'For external exposure, the report’s own model: the dose rate per photon emitted at each of its energies, from Monte Carlo in its phantoms, and per electron, to the skin, drawn against energy at the age chosen.',
    sections: [
      { heading: 'The chart', list: [
        'e per photon and the skin’s dose per photon at the report’s energies (10 keV to 5 MeV), and the skin’s dose per electron from FGR 12’s DOSFACTER curves.',
        'After a calculation, the nuclide’s photon lines on the e curve: a line’s dose is its yield times the curve at its energy.',
        'Age: the phantom of the curves (FGR 15: newborn to adult; FGR 12: the adult).',
      ] },
      { heading: 'Below', text: 'After a calculation, the photon lines of the nuclide alone that give the most of e: energy, yield per decay, their e and its share. Bremsstrahlung and the electrons, which the lines do not show, make up the rest (the Coefficients tab gives their parts).' },
    ],
    more: { label: 'External exposure', id: 'help-external' },
  } : {
    kicker: 'Tab', title: 'Model',
    lead: 'The systemic model of the parent and of each progeny as the calculation uses it, drawn and tabulated, with the respiratory and alimentary tract parameters of the chosen form; after a calculation, the activity and the dose in its boxes over time.',
    sections: [
      { heading: 'Member and age at intake', list: [
        'Member: the parent or a progeny, each with the model the calculation gives it (which, and why, is in Progeny in Help).',
        'Age at intake: the age of the transfer coefficients on the arrows (the table lists them at every reference age) and, when the boxes are filled, the calculation’s age at intake; ages not calculated are then left out.',
      ] },
      { heading: 'Show', list: [
        'Model: the model as it is drawn.',
        'Activity in the body: each box filled from the bottom, as a bucket, to its share of the member’s activity in the whole body at the time on the slider, the share written in the box.',
        'Effective dose: each box filled to its share of the committed effective dose received up to that time, or of its rate then, from the activity in the box: of the member, or of the whole chain (each nuclide in the box of the same name; one formed in a compartment of another member’s model, in that compartment’s box).',
        'Activity and dose are offered after a calculation of the choice on the left; activities of different nuclides are never added up.',
      ] },
      { heading: 'Time', list: [
        'The slider: one of the calculation’s output times, ten to a decade from about a minute and a half after intake.',
        'Run through moves it to the last in about seven seconds; Stop halts it. Another age keeps the time.',
        'Pointing at a box gives its value per Bq taken in, and for the whole chain each nuclide’s share.',
      ] },
      { heading: 'Not in the drawing', text: 'The respiratory tract (by region: ET, BB, bb, AI and the lymph nodes), the mouth and the oesophagus, and the compartments a progeny is given where it is formed in a part of another member’s model that its own model lacks, are listed under the slider with their shares; with the whole chain, each nuclide’s other places together. With the boxes they make up the whole body.' },
      { heading: 'Pointing', text: 'Pointing at an arrow lights its row of the transfer table and the boxes at its ends, and the other way round; pointing at a box lights the transfers into it (blue) and out of it (red); pointing at a box or an organ lights the others that stand for it.' },
    ],
    more: { label: 'Progeny', id: 'help-progeny' },
  }),
  'tab:chain': () => (shownSystem()?.first?.external || (!shownSystem() && route() === 'external') ? {
    kicker: 'Tab', title: 'Decay chain',
    lead: 'For external exposure, the whole decay chain with each member’s activity once in equilibrium with the parent, which is how the coefficients with the progeny count them.',
    sections: [
      { heading: 'The columns', list: [
        'Produced from: the members it comes from, with the branching fraction.',
        'Electron and photon energy: the mean energy per transformation (Publication 107; Publication 38 in the ICRP 60 system); alpha particles give no external dose.',
        'Bq per Bq: its activity per becquerel of the parent once in equilibrium with it — the branching fraction in secular equilibrium, more where the parent’s half-life is not much longer (transient equilibrium, λi/(λi − λP) at each step); “never” for a member as long-lived as the parent or longer, or formed from one.',
        'After a calculation, e alone: the member’s own effective dose rate; Share: its part of e with the progeny, at the age chosen.',
      ] },
      { heading: 'Good to know', text: 'The note above the table says how long the chain takes to come within 1 % of equilibrium: minutes for Cs-137 and Ba-137m, 1.6 million years for the whole U-238 series. A member never in equilibrium has a dose rate that depends on how long the parent has been there; its own coefficient is the one to add.' },
    ],
    more: { label: 'External exposure', id: 'help-external' },
  } : {
    kicker: 'Tab', title: 'Decay chain',
    lead: 'The members of the decay chain that are followed, how each behaves in the body, and the number of nuclear transformations in each source region over the commitment period.',
    sections: [
      { heading: 'The columns', list: [
        'Produced from: the members it comes from, with the branching fraction.',
        'Alpha, electron and photon energy: the mean energy per transformation (Publication 107; Publication 38 in the ICRP 60 system).',
        'Transformations per Bq: over the commitment period, after a calculation.',
        'In the body: its own model, the parent’s, decays where it is formed, or a noble gas.',
      ] },
      { heading: 'Below', text: 'The number of nuclear transformations in each source region, largest first: where the energy is released, which the doses follow from.' },
    ],
    more: { label: 'Progeny', id: 'help-progeny' },
  }),
  'tab:batch': {
    kicker: 'Tab', title: 'Batch',
    lead: 'Many calculations in one go, for one system and one route, in one table.',
    sections: [
      { heading: 'What to calculate', list: [
        'Radionuclides: typed or pasted (an element’s symbol stands for all its nuclides), or chosen from the list, which a search, an element, a half-life range and a decay mode narrow down.',
        'All forms of each, or only the default one; for inhalation the aerosol sizes (a gas or vapour has none); the ages at intake; the decay chain cut-off and the tolerance of the tab itself.',
        'Route External: the geometries ticked in place of the forms, and the ages (FGR 12: the adult only); no cut-off or tolerance. Every age of a nuclide in a geometry is one request of milliseconds.',
        'The count above the button says how many calculations that is.',
      ] },
      { heading: 'Running', list: [
        'The calculations run in the page’s workers, as many at a time as the device has cores to spare, after any single calculation you start meanwhile.',
        'The bar shows how far it has come and about how long is left; Stop ends it, keeping what is done. A calculation that fails is noted in its row.',
      ] },
      { heading: 'The table', list: [
        'Under the bar: the effective dose, and the equivalent doses if ticked; ages as columns or a row for each age; the digits. Changing these calculates nothing again.',
        'External exposure: dose rates per Bq/m³ (per Bq/m² on the ground, as the Per column says), with FGR 12’s HE in the ICRP 60 system and every quantity with the progeny in equilibrium as well, if ticked.',
        'Save as CSV (six significant figures) or as Excel (the full values, with a sheet of the settings).',
      ] },
    ],
    more: { label: 'Batch calculations', id: 'help-batch' },
  },
  'tab:risk': {
    kicker: 'Tab', title: 'Risk',
    lead: 'The detriment-adjusted nominal risk coefficients of the selected system (Publication 103 Table 1, Publication 60 Table 3), calculated tissue by tissue from the nominal risks and the lethality, quality-of-life and life-lost factors of the publications’ annexes, beside the values the ICRP printed.',
    sections: [
      { heading: 'How it is calculated', list: [
        'ICRP 103 (Annex A): detriment = R (k + q (1 − k)) l per tissue, from the nominal risk R, the lethality k, the quality-of-life weight q = qmin + (1 − qmin) k and the relative life lost l; heritable effects apart.',
        'ICRP 60 (Annex B): detriment = F (l / l̄) (2 − k), with the mean life lost l̄ of 15 years, and severe hereditary effects.',
        'A printed value that differs from the calculated one by more than its rounding and 1 % is marked; pointing at it shows the calculated value.',
      ] },
      { heading: 'Applied to the calculated intake or exposure', text: 'Its nominal detriment per becquerel taken in, or for external exposure per second per unit concentration (of the nuclide alone or with its progeny, as the Coefficients tab shows it), two ways: e times the total coefficient, and tissue by tissue from the equivalent doses. Nominal detriment is for radiological protection, not the risk of a person.' },
    ],
    more: { label: 'Risk coefficients', id: 'help-risk' },
  },
  'tab:radon': {
    kicker: 'Tab', title: 'Radon at home',
    lead: 'Effective dose per exposure to radon (or thoron) and its short-lived progeny in a home, by age, as Publication 158 calculates it (Section 32 and Annex C): each progeny nuclide inhaled in each mode of the home aerosol, combined per unit potential alpha energy.',
    sections: [
      { heading: 'The inputs', list: [
        'Unattached fraction fp: the share of the potential alpha energy on clusters of about 1 nm; 0.1 for radon and 0.02 for thoron in homes (Table 32.2).',
        'Nucleation share fpn: the attached part in the nucleation mode (30 nm for radon, 40 nm for thoron; 0.2 and 0.14), the rest in the accumulation mode (200 nm).',
        'Equilibrium factor F (radon): the progeny’s potential alpha energy relative to equilibrium with the gas; 0.4 in homes.',
        'Concentration and hours a year, for an annual dose; 300 Bq per m³ is the upper reference level for homes (Publication 158 para 536).',
      ] },
      { heading: 'The results', text: 'mSv per mJ h per m³ of potential alpha energy exposure, per WLM, and per Bq h per m³ of the gas or of its equilibrium equivalent concentration; beside them the coefficient the ICRP recommends, 3 mSv per mJ h per m³ for radon and 1 for thoron. The inhalations are calculated once per gas, in parallel on the device’s cores.' },
    ],
    more: { label: 'Radon and thoron at home', id: 'help-radon' },
  },
};
/* An open panel that says what is chosen now follows a change of the settings
   (its scroll stays where it was). */
function refreshInfo() {
  if (typeof KvotInfo === 'undefined' || typeof TOPICS[KvotInfo.current()] !== 'function') return;
  const panel = document.getElementById('kvot-info-panel');
  const body = panel?.querySelector('.info-panel-body');
  const at = [panel?.scrollTop, body?.scrollTop];
  KvotInfo.refresh();
  if (panel) panel.scrollTop = at[0] || 0;
  if (body) body.scrollTop = at[1] || 0;
}
function topicsFor() {
  const out = {};
  for (const [k, v] of Object.entries(TOPICS)) out[k] = typeof v === 'function' ? v : () => v;
  return out;
}

/* ---- the full window -------------------------------------------------------------------------- */
/* The page without the site's header and footer (dose_coefficients.css :root.dc-full), by the
   button at the right end of the tab bar; kept for the next visit, which the page's head puts in
   it before the first paint. */
const FULL = 'kvot.dose.full';
function setFull(on) {
  document.documentElement.classList.toggle('dc-full', !!on);
  try { localStorage.setItem(FULL, on ? '1' : '0'); } catch { /* storage unavailable: for this visit only */ }
  fullState();
  resizePlots();
}
function fullState() {
  const on = document.documentElement.classList.contains('dc-full');
  const b = $('dcFull');
  b.setAttribute('aria-pressed', String(on));
  b.title = on ? 'Show the site’s header and footer again' : 'Full window: the page without the site’s header and footer';
}

/* ---- start ------------------------------------------------------------------------------------ */
registerActions({
  'dc:systemChanged': async (e, el) => {
    state.system = el.value;
    populateDecay();
    markStale();
    refreshInfo();
    $('dcRun').disabled = true;
    try { await loadCatalog(state.system); } catch (err) { status(`Could not load the data: ${err.message}`, 'error'); }
    save();
  },
  'dc:decayChanged': (e, el) => {
    if (el.value.startsWith('nndc:')) { const id = el.value.slice(5); el.value = state.decay; showGet(id); return; }
    chooseDecay(el.value);
  },
  'dc:decayOpen': () => $('dcDecayFile').click(),
  'dc:decayFile': (e, el) => { const f = [...(el.files || [])]; el.value = ''; openEnsdf(f); },
  'dc:decayForget': () => forgetDecay(state.decay),
  'dc:getClose': () => closeGet(),
  'dc:getOpen': () => { closeGet(); $('dcDecayFile').click(); },
  'dc:nuclideChanged': () => { nuclideChanged(); save(); },
  'dc:nuclideTyped': () => { showSuggest(); if (findEntry()) nuclideChanged(); },
  'dc:routeChanged': () => { routeSettings(); populateForms(); save(); },
  'dc:formChanged': () => { formChanged(); save(); },
  'dc:settingChanged': () => { describeSoon(); save(); },
  'dc:run': () => run(),
  'dc:stop': () => { stopRank(RANK.run); },
  'dc:tab': (e, el) => showTab(el.dataset.tab),
  'dc:full': () => setFull(!document.documentElement.classList.contains('dc-full')),
  'dc:shares': () => { renderCoef(); save(); },
  'dc:redraw': () => { if (state.tab === 'coef') renderCoef(); else if (state.tab === 'retention') renderRetention(); else if (state.tab === 'model') renderModel(); else if (state.tab === 'chain') renderChain(); else if (state.tab === 'risk') renderRisk(); else if (state.tab === 'radon') renderRadon(); },
  'dc:radonKind': () => renderRadon(),
  'dc:radonParams': () => renderRadon(),
  'dc:radonDefaults': () => { radonDefaults(radonKind(), true); renderRadon(); },
  'dc:radonRetry': () => { delete RADON.error[radonKey(radonKind())]; renderRadon(); },
  'dc:radonDecay': async (e, el) => {
    if (el.value.startsWith('nndc:')) { const id = el.value.slice(5); el.value = RADON.decay; showGet(id); return; }
    RADON.decay = decayValid(el.value) ? el.value : '';
    save();
    try { await ensureDecay(RADON.decay); } catch (err) { status(`Could not make the decay data: ${err.message}`, 'error'); }
    renderRadon();
  },
  'dc:modelAge': (e, el) => { VIEW.age = Number(el.value); renderModel(); },
  'dc:modelView': () => {
    Object.assign(VIEW, { show: $('dcModelShow').value, dose: $('dcModelDose').value, from: $('dcModelFrom').value });
    renderModel();
    save();
  },
  'dc:bucketsTime': (e, el) => {
    viewStop();
    const v = viewSeries();
    if (v) VIEW.time = v.ser.times[Math.min(Number(el.value), v.ser.times.length - 1)];
    renderView();
  },
  'dc:bucketsPlay': () => viewPlay(),
  'dc:csv': () => csv(),
  'dc:batchCsv': () => batch?.saveCsv(),
  'dc:batchExcel': () => batch?.saveExcel(),
});

/* Set the panel from a link's choices and calculate. */
async function applyChoices(c, runIt) {
  const decay = decayValid(c.decay) ? c.decay || '' : '';
  if (((c.system === '60' || c.system === '103') && c.system !== state.system) || decay !== state.decay) {
    if (c.system === '60' || c.system === '103') state.system = c.system;
    state.decay = decay;
    for (const r of document.querySelectorAll('input[name="dcSystem"]')) r.checked = r.value === state.system;
    populateDecay();
    state.result = null;
    renderAll();
    await ensureDecay(state.decay);
    await loadCatalog(state.system);
  }
  if (c.nuclide) { $('dcNuclide').value = c.nuclide; nuclideChanged(); }
  if (c.route) { const r = document.querySelector(`input[name="dcRoute"][value="${c.route}"]`); if (r && !r.disabled) r.checked = true; }
  populateForms(c.form || undefined);
  if (c.amad && [...$('dcAmad').options].some((o) => o.value === c.amad)) $('dcAmad').value = c.amad;
  if (runIt && state.entry) run();
}

async function start() {
  const saved = load();
  const fromHash = readHash();
  const s = { ...saved, ...(fromHash || {}) };
  if (s.system === '60' || s.system === '103') {
    state.system = s.system;
    for (const r of document.querySelectorAll('input[name="dcSystem"]')) r.checked = r.value === s.system;
  }
  await loadDecayReleases();
  // A link's decay data that this browser does not have (a release opened in another): not calculated with others.
  const lost = fromHash?.decay && !decayValid(fromHash.decay) ? decayLabel(fromHash.decay, state.system) : null;
  if (lost) fromHash.run = false;
  state.decay = decayValid(s.decay) ? s.decay || '' : '';
  populateDecay();
  RADON.decay = decayValid(saved.radonDecay) ? saved.radonDecay || '' : '';
  populateRadonDecay();
  if (s.side) $('dcRoot').style.setProperty('--dc-side-width', s.side);
  fullState();
  if (s.nuclide) $('dcNuclide').value = s.nuclide;
  if (s.route) { const r = document.querySelector(`input[name="dcRoute"][value="${s.route}"]`); if (r) r.checked = true; }
  if (Array.isArray(s.ages)) for (const i of $('dcAges').querySelectorAll('input')) i.checked = s.ages.includes(Number(i.value));
  if (s.cutoff) $('dcCutoff').value = s.cutoff;
  if (s.rtol) $('dcRtol').value = s.rtol;
  if (s.shares) $('dcShares').checked = true;
  if (['model', 'activity', 'dose'].includes(s.model?.show)) VIEW.show = s.model.show;
  if (['received', 'rate'].includes(s.model?.dose)) VIEW.dose = s.model.dose;
  if (['member', 'chain'].includes(s.model?.from)) VIEW.from = s.model.from;
  if (typeof KvotInfo !== 'undefined') KvotInfo.setup({ topics: topicsFor(), onMore: (more) => { showTab('help'); document.getElementById(more.id)?.scrollIntoView({ behavior: 'smooth' }); } });
  setupResize();
  setupSuggest();
  window.addEventListener('resize', resizePlots);
  linkParts($('dcModelFigs'));
  setupTips($('dcRoot'));
  linkTransfers($('dcModel'));
  // The charts hold the theme's colours (the other tabs follow the stylesheet).
  document.documentElement.addEventListener('kvot-theme-change', () => { if (state.tab === 'retention') renderRetention(); });
  // A link pasted into the open page changes only the hash.
  window.addEventListener('hashchange', () => { const h = readHash(); if (h) applyChoices(h, true); });
  batch = setupBatch({
    h, $, ask, stopRank, RANK, POOL_SIZE, sci, halfLife, AGE_LABEL,
    TISSUES: { 60: TISSUE_ORDER_60, 103: TISSUE_ORDER_103 }, TISSUES_EXT: TISSUE_ORDER_EXT, SIZES: AMAD_SIZES, externalForms,
    catalog: catalogOf, system: () => state.system, decay: () => state.decay, decayOptions, decayLabel, decayValid, ensureDecay, showGet, saved: s.batch || {},
    defaults: () => ({ cutoff: $('dcCutoff').value, rtol: $('dcRtol').value }),
    onSave: save,
    onProgress: (text) => { const b = document.querySelector('.dc-tabs button[data-tab="batch"]'); if (b) b.textContent = text ? `Batch · ${text}` : 'Batch'; },
    visible: () => state.tab === 'batch',
  });
  showTab(['coef', 'retention', 'model', 'chain', 'batch', 'risk', 'radon', 'help'].includes(s.tab) ? s.tab : 'coef');
  if (!$('dcNuclide').value) $('dcNuclide').value = 'Cs-137';
  setupEnsdfDrop();
  $('dcGet').addEventListener('click', (ev) => { if (ev.target === ev.currentTarget) closeGet(); });
  try {
    await ensureDecay(state.decay).catch((err) => { status(`Could not make the decay data: ${err.message}`, 'error'); state.decay = ''; populateDecay(); });
    await loadCatalog(state.system);
    if (lost) status(`The link names decay data this browser does not have (${lost}); open that release here to calculate with it.`, 'error');
    if (s.form) populateForms(s.form);
    if (s.amad) { $('dcAmad').value = s.amad; }
    if (fromHash?.run && state.entry) run();
  } catch (err) {
    status(`Could not load the data: ${err.message}`, 'error');
  }
}
start();
