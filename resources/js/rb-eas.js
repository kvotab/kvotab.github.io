/* ==========================================================================
   4c. ECOLEGO ASSESSMENTS (.eas)

   An Ecolego assessment keeps the runs made with its model beside the model.
   It is a ZIP archive: simulation.xml lists every run kept -- what it saved,
   in which units, indexed by which lists -- and simulation/results/ holds each
   run's numbers, a file per run. Ecolego 5 kept one run, in results.dta;
   Ecolego 6 keeps the current run and any it was asked to archive, each in a
   file named by the run's GUID.

   Each run opens as an HDF5 file of its own: written here, in memory, with
   h5wasm, in the shape this page reads results in, and then registered like
   any file read from disk. So a run is browsed as a file is -- the tree, the
   charts of a group's members, two runs compared in one tree, the exports.

       /time                         the output times, with their unit
       /IndexLists/Radionuclides     the members of each index list, in order
       /Nearfield/Conc_SWW/          a block indexed by one list: a group,
            @IndexLists = ['Materials']   which draws its members together
            Ac-227, Am-241, ...      one series per member
       /Biosphere/Dose_Crops/Cereals/Ac-227
                                     indexed by two: the nuclide is the leaf
       /Nearfield/Q_BF_SWW           a block that is not indexed

   The format is read as Kompartment reads it (kompartment/src/io/ecoruns.js),
   whose reading was checked against Ecolego's own runs of the same models.
   Two things differ, because this page shows the file rather than a model's
   run beside it. Every output the run saved comes in, named by the path
   Ecolego gives it. And a transfer is shown as Ecolego stored it: Ecolego 6
   stores a transfer's flux, Bq per year, and Ecolego 5 its rate; the unit
   each was saved with says which.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* The ZIP records read here, by their signatures. */
const EAS_ZIP_END = 0x06054b50;
const EAS_ZIP_END64_LOCATOR = 0x07064b50;
const EAS_ZIP_END64 = 0x06064b50;
const EAS_ZIP_CENTRAL = 0x02014b50;
const EAS_ZIP_LOCAL = 0x04034b50;

/* A result file's header, and the header in front of each output's numbers. */
const EAS_DTA_HEADER = 1024;
const EAS_DTA_BLOCK_HEADER = 64;

/* Attributes written as integers; every other number is written as a double. */
const EAS_INTEGER_ATTRIBUTES = new Set(['n_iter', 'outputs', 'series', 'not read', 'members']);

/**
 * The runs opened from assessments, by the name each was registered under:
 * which assessment and run it is, and the name it is saved under as HDF5.
 * See pythonFileName.
 */
const easOpenedRuns = new Map();

/**
 * Whether bytes handed over are an Ecolego assessment rather than HDF5.
 *
 * By name, or for bytes that arrive under another name -- a link that does
 * not end in .eas, a handoff named .h5 -- by being a ZIP archive and not HDF5.
 * The second test matters: an HDF5 file may start with a user block, and that
 * can begin with anything.
 *
 * @param {string} fileName
 * @param {ArrayBuffer|null} buffer - null to decide by the name alone
 * @returns {boolean}
 */
function isEcolegoAssessment(fileName, buffer) {
  if (/\.eas$/i.test(String(fileName || ''))) return true;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 4) return false;
  const head = new Uint8Array(buffer, 0, 4);
  return head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04
    && !validateHdf5Buffer(buffer).ok;
}

/**
 * Open a file handed over by any transport, whatever it is: HDF5 as itself,
 * an Ecolego assessment as a file for each run it keeps. Does not refresh the
 * tree.
 *
 * @param {string} fileName - Display name
 * @param {ArrayBuffer} buffer - The file's bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string[]>} The names registered; none when the reader
 *   chose no run
 */
async function ingestFileBuffer(fileName, buffer, context = 'ingestFileBuffer') {
  if (isEcolegoAssessment(fileName, buffer)) return ingestEcolegoAssessment(fileName, buffer, context);
  return [await ingestHdf5Buffer(fileName, buffer, context)];
}

/* ── the archive ─────────────────────────────────────────────────────── */

/**
 * The entries of a ZIP archive, by name, with forward slashes: Ecolego 5
 * wrote its archives on Windows with backslashes. Nothing is unpacked here.
 *
 * Every number used comes out of the file, and a file may lie, so each is
 * checked against the archive before anything is read where it points.
 *
 * @param {Uint8Array} bytes
 * @returns {Map<string, {name: string, flags: number, method: number,
 *   packed: number, size: number, local: number}>}
 */
function easZipEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const damaged = (why) => new Error(`it is not a ZIP archive this page can read: ${why}`);

  // The end record sits in the last 64 KB, after a comment of its own.
  let end = -1;
  for (let p = bytes.length - 22, stop = Math.max(0, bytes.length - 22 - 0xffff); p >= stop; p--) {
    if (view.getUint32(p, true) === EAS_ZIP_END) { end = p; break; }
  }
  if (end < 0) throw damaged('it has no directory');
  let count = view.getUint16(end + 10, true);
  let at = view.getUint32(end + 16, true);
  // ZIP64, for an archive past 4 GB or 65,535 entries.
  if (count === 0xffff || at === 0xffffffff) {
    const locator = end - 20;
    if (locator >= 0 && view.getUint32(locator, true) === EAS_ZIP_END64_LOCATOR) {
      const record = Number(view.getBigUint64(locator + 8, true));
      if (!Number.isSafeInteger(record) || record < 0 || record + 56 > bytes.length
          || view.getUint32(record, true) !== EAS_ZIP_END64) {
        throw damaged('its ZIP64 directory is damaged');
      }
      count = Number(view.getBigUint64(record + 32, true));
      at = Number(view.getBigUint64(record + 48, true));
    }
  }

  const decoder = new TextDecoder('utf-8');
  const entries = new Map();
  for (let i = 0; i < count; i++) {
    if (!Number.isSafeInteger(at) || at < 0 || at + 46 > bytes.length
        || view.getUint32(at, true) !== EAS_ZIP_CENTRAL) {
      throw damaged('its directory is damaged');
    }
    const flags = view.getUint16(at + 8, true);
    const method = view.getUint16(at + 10, true);
    let packed = view.getUint32(at + 20, true);
    let size = view.getUint32(at + 24, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    let local = view.getUint32(at + 42, true);
    const next = at + 46 + nameLength + extraLength + commentLength;
    if (next > bytes.length) throw damaged('its directory runs past the end of the file');
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength)).replace(/\\/g, '/');

    // ZIP64 sizes, where the 32-bit ones are saturated: in this order, and
    // only those that are.
    if (packed === 0xffffffff || size === 0xffffffff || local === 0xffffffff) {
      for (let p = at + 46 + nameLength, stop = p + extraLength; p + 4 <= stop;) {
        const id = view.getUint16(p, true);
        const length = view.getUint16(p + 2, true);
        if (id === 0x0001) {
          let q = p + 4;
          const last = Math.min(p + 4 + length, stop);
          const take = () => {
            if (q + 8 > last) throw damaged(`the sizes of ${name} are damaged`);
            const v = Number(view.getBigUint64(q, true));
            q += 8;
            return v;
          };
          if (size === 0xffffffff) size = take();
          if (packed === 0xffffffff) packed = take();
          if (local === 0xffffffff) local = take();
          break;
        }
        p += 4 + length;
      }
    }
    at = next;
    if (!name.endsWith('/')) entries.set(name, { name, flags, method, packed, size, local });
  }
  return entries;
}

/**
 * One entry's bytes, unpacked by the browser's own inflater.
 *
 * Unpacked into exactly the size the directory gives, and refused the moment
 * it would run past it: a small archive can claim little and unpack to
 * gigabytes, and nothing on the packed side says so.
 *
 * @param {Uint8Array} bytes - The archive
 * @param {Object} entry - From easZipEntries
 * @returns {Promise<Uint8Array>}
 */
async function easZipRead(bytes, entry) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const { name, flags, method, packed, size, local } = entry;
  const damaged = () => new Error(`${name} in the archive is damaged`);
  if (flags & 0x01) {
    throw new Error(`${name} is encrypted: Ecolego can protect a file as it saves it. Save it again without that.`);
  }
  if (size > KVOT_FILE_SIZE_LIMITS.dataset) {
    throw new Error(`${name} unpacks to ${kvotFormatBytes(size)}, more than the `
                    + `${kvotFormatBytes(KVOT_FILE_SIZE_LIMITS.dataset)} this page reads.`);
  }
  if (!Number.isSafeInteger(local) || local < 0 || local + 30 > bytes.length
      || view.getUint32(local, true) !== EAS_ZIP_LOCAL) {
    throw damaged();
  }
  // The local header repeats the name and has an extra field of its own.
  const start = local + 30 + view.getUint16(local + 26, true) + view.getUint16(local + 28, true);
  if (start + packed > bytes.length) throw damaged();
  const raw = bytes.subarray(start, start + packed);
  // Stored: read in place. Nothing here writes to an entry.
  if (method === 0) {
    if (packed !== size) throw damaged();
    return raw;
  }
  if (method !== 8) throw new Error(`${name} is packed by a method this page does not read (${method}).`);

  let inflater;
  try {
    inflater = new DecompressionStream('deflate-raw');
  } catch (_) {
    throw new Error('this browser cannot unpack a ZIP archive. A current Chrome, Edge, Firefox or Safari can.');
  }
  const out = new Uint8Array(size);
  let filled = 0;
  const reader = new Blob([raw]).stream().pipeThrough(inflater).getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (filled + value.byteLength > size) throw damaged();
      out.set(value, filled);
      filled += value.byteLength;
    }
  } catch (e) {
    reader.cancel().catch(() => {});
    if (e && /damaged/.test(e.message)) throw e;
    throw damaged();
  }
  if (filled !== size) throw damaged();
  return out;
}

/* ── the XML ─────────────────────────────────────────────────────────── */

/** An entry parsed as XML: its root element. */
function easXml(bytes, name) {
  const doc = new DOMParser().parseFromString(new TextDecoder('utf-8').decode(bytes), 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error(`its ${name} is not readable XML.`);
  return doc.documentElement;
}

/** The child elements named `tag`. */
function easKids(el, tag) {
  const out = [];
  if (el) for (const c of el.children) if (c.localName === tag) out.push(c);
  return out;
}

/** The first child element named `tag`, or null. */
function easKid(el, tag) {
  if (el) for (const c of el.children) if (c.localName === tag) return c;
  return null;
}

/** The trimmed text of the first child named `tag`, or null. */
function easText(el, tag) {
  const k = easKid(el, tag);
  return k ? k.textContent.trim() : null;
}

/** A comma-separated list of names. */
const easNames = (text) => String(text ?? '').split(',').map(s => s.trim()).filter(Boolean);

/**
 * What an Ecolego 5 model says about its blocks' indices.
 *
 * Ecolego 5 writes an output's index names into simulation.xml without naming
 * the lists they belong to, and the name of a list is what makes a group of
 * radionuclides chart as one. The model has them: each block names its lists,
 * and the index-list model holds every list. Ecolego 6 names the lists in
 * simulation.xml itself, so its model is not read at all.
 *
 * @param {Element} model - model.xml's root
 * @returns {{lists: Map<string, string[]>, blocks: Map<string, {lists: string[], type: string}>}}
 */
function easModelIndices(model) {
  const lists = new Map();
  for (const l of easKids(easKid(model, 'index-list-model'), 'index-list')) {
    const name = (l.getAttribute('name') || '').trim();
    if (name) lists.set(name, easKids(l, 'index').map(i => (i.getAttribute('name') ?? i.textContent).trim()));
  }
  const blocks = new Map();
  for (const el of model.querySelectorAll('component, connection')) {
    const id = easText(el, 'id');
    if (id) blocks.set(id, { lists: easNames(el.getAttribute('index-lists')), type: el.getAttribute('type') || '' });
  }
  return { lists, blocks };
}

/* ── the runs ────────────────────────────────────────────────────────── */

/**
 * An assessment: the runs it keeps, ready to be converted one at a time.
 *
 * @param {string} fileName
 * @param {Uint8Array} bytes
 * @returns {Promise<{version: string, runs: Object[], model: Object|null}>}
 */
async function readEcolegoAssessment(fileName, bytes) {
  const entries = easZipEntries(bytes);
  const simEntry = entries.get('simulation.xml');
  const results = new Map();
  for (const [name, entry] of entries) {
    const m = /^simulation\/results\/([^/]+)\.dta$/i.exec(name);
    if (m) results.set(m[1].toUpperCase(), entry);
  }
  const noResults = () => new Error('it keeps no results. An Ecolego assessment (.eas) holds them when it '
                                    + 'is saved after a run; a project (.eco) never does.');
  if (!simEntry || !results.size) throw noResults();
  const sim = easXml(await easZipRead(bytes, simEntry), 'simulation.xml');
  if (sim.localName !== 'simulation-model') throw new Error('its simulation.xml is not one Ecolego wrote.');

  let version = '';
  const versionEntry = entries.get('.version');
  if (versionEntry) {
    const text = new TextDecoder('utf-8').decode(await easZipRead(bytes, versionEntry));
    version = (/^\s*version\s*=\s*([^\r\n]*)/m.exec(text) || [])[1]?.trim() || '';
  }

  const runs = [];
  for (const ctx of easKids(sim, 'simulation-context')) {
    const info = easKid(ctx, 'simulation-info');
    const guid = (ctx.getAttribute('guid') || '').trim().toUpperCase();
    const entry = results.get(guid || 'RESULTS');
    // A run listed whose numbers were not kept, or kept as a header alone.
    if (!entry || entry.size <= EAS_DTA_HEADER) continue;
    const kind = (easText(info, 'simulation-info-type') || '').toUpperCase();
    const date = Number(easText(info, 'date'));
    runs.push({
      ctx,
      info,
      entry,
      // Ecolego 6 names every run by a GUID, Ecolego 5 kept one, unnamed.
      // Two of the file's conventions follow which it was: see easRunTree.
      six: !!guid,
      name: easText(info, 'simulation-name') || '',
      date: Number.isFinite(date) && date > 0 ? date : null,
      archived: ctx.getAttribute('archive') === 'true',
      probabilistic: !!kind && kind !== 'DETERMINISTIC',
      outputs: easKids(easKid(ctx, 'simulation-outputs'), 'output-info')
        .filter(o => o.getAttribute('id') && o.getAttribute('id') !== 'time' && easText(o, 'sub-system') !== 'true').length
    });
  }
  if (!runs.length) throw noResults();

  // Ecolego 5 names an output's index lists only in its model.
  let model = null;
  const modelEntry = entries.get('model.xml');
  if (runs.some(run => !run.six) && modelEntry) {
    try {
      model = easModelIndices(easXml(await easZipRead(bytes, modelEntry), 'model.xml'));
    } catch (e) {
      // The lists are then named by their members, or numbered: see easRunTree.
      kvotWarn(`[eas] ${fileName}: the model's index lists could not be read:`, e.message);
    }
  }

  runs.forEach((run) => { run.label = easRunLabel(run); });
  return { version, runs, model };
}

/** What a run is called: its name, or which run it is when it has none. */
function easRunLabel(run) {
  if (run.name) return run.name;
  if (!run.archived) return 'current run';
  return run.date ? `archived ${easStamp(run.date).slice(0, 16)}` : 'archived run';
}

/** A time as result files write `created_time`: 2017-02-14 11:22:37, local time. */
function easStamp(ms) {
  const d = new Date(ms);
  const two = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} `
    + `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}

/* ── a run's numbers ─────────────────────────────────────────────────── */

/** The GUID text a block header's first sixteen bytes stand for. */
function easGuidAt(bytes, at) {
  // The low half comes first in the file, and a GUID's text reads from the high half.
  let s = '';
  for (const from of [at + 8, at]) {
    for (let i = from; i < from + 8; i++) s += bytes[i].toString(16).padStart(2, '0');
  }
  s = s.toUpperCase();
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

/**
 * A result file: how many simulations and output times it holds, and where
 * each output's numbers are -- big-endian doubles, simulation by simulation,
 * then time by time, then through the output's own indices. Nothing is
 * decoded here.
 *
 *     0      int32   simulations (one for a single run, one per realisation)
 *     4      int32   output times
 *     1024   a block per output: the GUID's low and high halves, the size
 *            in bytes of the numbers, padding to 64 bytes, the numbers
 *
 * @param {Uint8Array} bytes
 */
function easResultFile(bytes) {
  if (bytes.length < EAS_DTA_HEADER) throw new Error('its result file is shorter than the header it starts with.');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const simulations = view.getInt32(0, false);
  const times = view.getInt32(4, false);
  const blocks = new Map();
  for (let at = EAS_DTA_HEADER; at < bytes.length;) {
    if (at + EAS_DTA_BLOCK_HEADER > bytes.length) throw new Error('its result file ends inside a block header.');
    const size = Number(view.getBigInt64(at + 16, false));
    const start = at + EAS_DTA_BLOCK_HEADER;
    if (!(size >= 0) || start + size > bytes.length) throw new Error('a block of its result file runs past the end.');
    blocks.set(easGuidAt(bytes, at), { start, size });
    at = start + size;
  }
  return { simulations, times, blocks, view };
}

/** What a name has to be before it can be an HDF5 link: `/` is HDF5's own. */
function easLinkName(s) {
  const out = String(s ?? '').replace(/\//g, '⁄').trim();
  return out === '' || out === '.' || out === '..' ? '_' : out;
}

function easGroup(attrs = {}) {
  return { kind: 'group', attrs, children: new Map() };
}

/**
 * The group called `name` in `parent`, made if there is none. A dataset
 * already there keeps its name, and the group goes beside it, numbered: a
 * result that is in the file under an awkward name is better than one that
 * is not in it at all.
 */
function easChildGroup(parent, name) {
  for (let n = 1; ; n++) {
    const key = n === 1 ? name : `${name} (${n})`;
    const found = parent.children.get(key);
    if (!found) {
      const made = easGroup();
      parent.children.set(key, made);
      return made;
    }
    if (found.kind === 'group') return found;
  }
}

/** Puts a dataset at `path`, numbered when the name is taken. */
function easPlace(root, path, node) {
  let at = root;
  for (const part of path.slice(0, -1)) at = easChildGroup(at, part);
  const last = path[path.length - 1];
  let key = last;
  for (let n = 2; at.children.has(key); n++) key = `${last} (${n})`;
  at.children.set(key, node);
  return at;
}

/**
 * The unit of each cell of an output. Ecolego 6 gives one for the output;
 * Ecolego 5 one per cell, keyed by the cell's position in each list.
 *
 * @returns {(position: number[]) => string}
 */
function easUnitsOf(o) {
  let common = null;
  const keyed = new Map();
  for (const u of easKids(easKid(o, 'output-units'), 'output-unit')) {
    const text = u.textContent.trim();
    const position = [];
    for (let k = 1; u.hasAttribute(`index-${k}`); k++) position.push(Number(u.getAttribute(`index-${k}`)));
    const listed = (u.getAttribute('indices') || '').trim();
    if (listed) position.push(...listed.split(',').map(Number));
    if (position.length) keyed.set(position.join(','), text);
    else if (common === null) common = text;
  }
  const fallback = common ?? (keyed.size ? keyed.values().next().value : '');
  return (position) => keyed.get(position.join(',')) ?? fallback;
}

/**
 * One run as the tree of an HDF5 result file (see the top of this section),
 * with the numbers left in the result file until each series is written.
 *
 * @param {Object} assessment - From readEcolegoAssessment
 * @param {Object} run - One of its runs
 * @param {Uint8Array} dta - The run's result file
 * @param {string} fileName - The assessment's name
 * @returns {{tree: Object, series: number, notRead: number}}
 */
function easRunTree(assessment, run, dta, fileName) {
  const file = easResultFile(dta);
  const S = file.simulations;
  const nt = file.times;
  if (!(S >= 1) || !(nt >= 1)) throw new Error('its result file holds no simulation.');
  if (!run.probabilistic && S !== 1) throw new Error(`it holds ${S} simulations where a single run holds one.`);
  // A run of one realisation is drawn as a single run: there is no spread to show.
  const sampled = S > 1;
  const { ctx, info } = run;

  // The lists the outputs are indexed by: Ecolego 6 names them once for the
  // run, Ecolego 5 writes each output's own, unnamed, and its model names them.
  const runLists = new Map();
  for (const l of easKids(easKid(ctx, 'index-lists'), 'index-list')) {
    const name = (l.getAttribute('name') || '').trim();
    if (name) runLists.set(name, easKids(l, 'index').map(i => i.textContent.trim()));
  }
  const model = assessment.model;
  const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
  const unnamed = [];          // lists named here for want of a name: [members, name]
  const nameOf = (members, given) => {
    if (given) return given;
    // Named by the model's list with exactly these members, when one has them.
    const matches = model ? [...model.lists].filter(([, m]) => same(m, members)).map(([n]) => n) : [];
    if (matches.length === 1) return matches[0];
    const seen = unnamed.find(([m]) => same(m, members));
    if (seen) return seen[1];
    const made = `Index list ${unnamed.length + 1}`;
    unnamed.push([members, made]);
    return made;
  };
  const used = new Map();      // list name -> members, for /IndexLists

  const outputs = easKids(easKid(ctx, 'simulation-outputs'), 'output-info');
  const timeInfo = outputs.find(o => o.getAttribute('id') === 'time');
  const timeBlock = timeInfo ? file.blocks.get((timeInfo.getAttribute('guid') || '').trim().toUpperCase()) : null;
  if (!timeBlock || timeBlock.size < nt * 8) throw new Error('its result file has no output times.');
  // The first row: Ecolego 5 writes the times only into the first
  // realisation's, Ecolego 6 into every one.
  const t = new Float64Array(nt);
  for (let i = 0; i < nt; i++) t[i] = file.view.getFloat64(timeBlock.start + i * 8, false);

  // Ecolego 6 says it for the run; Ecolego 5 only as the unit of `time`.
  const timeUnit = easText(info, 'time-unit')
    ?? easText(easKid(timeInfo, 'output-units'), 'output-unit') ?? '';

  const created = run.date ? easStamp(run.date) : null;
  const root = easGroup();
  const timeNode = {
    kind: 'dataset', shape: [nt], make: () => t,
    attrs: { unit: timeUnit, name: 'time', probabilistic: 'FALSE', created_time: created }
  };
  root.children.set('time', timeNode);
  const lists = easGroup();
  root.children.set('IndexLists', lists);

  let series = 0;
  let notRead = 0;
  let written = 0;
  for (const o of outputs) {
    const id = (o.getAttribute('id') || '').trim();
    if (!id || id === 'time' || easText(o, 'sub-system') === 'true') continue;
    const block = file.blocks.get((o.getAttribute('guid') || '').trim().toUpperCase());
    // Listed but not kept: an output the run was not asked to save.
    if (!block) continue;

    // Which index names each dimension holds, in the output's own order.
    const named = easNames(o.getAttribute('index-lists'));
    let dims;
    if (named.length) {
      dims = named.map(n => (runLists.has(n) ? { name: n, members: runLists.get(n) } : null));
    } else {
      const inline = easKids(easKid(o, 'index-lists'), 'index-list')
        .map(l => easKids(l, 'index').map(i => i.textContent.trim()));
      const given = model?.blocks.get(id)?.lists ?? [];
      dims = inline.map((members, k) => ({
        name: nameOf(members, given.length === inline.length ? given[k] : null),
        members
      }));
    }
    if (dims.some(d => !d || !d.members.length)) { notRead++; continue; }
    const cells = dims.reduce((n, d) => n * d.members.length, 1);
    const timeDependent = easText(o, 'time-dependent') === 'true';
    const per = timeDependent ? nt : 1;
    if (block.size !== S * per * cells * 8) { notRead++; continue; }
    for (const d of dims) used.set(d.name, d.members);

    const unitOf = easUnitsOf(o);
    const kind = easText(o, 'block-type') ?? model?.blocks.get(id)?.type ?? '';
    // The leaf is the dimension a result is read along: a list this page
    // charts as one, when the output has one, or else the last.
    let leaf = dims.length - 1;
    const charted = RB_CHART_INDEX_LISTS.find(n => dims.some(d => d.name === n));
    if (charted) leaf = dims.findIndex(d => d.name === charted);
    // Which index runs fastest depends on which Ecolego wrote the file: the
    // first in Ecolego 6's, the last in Ecolego 5's. Read the other way
    // round, two assessments of one model, one saved by each, put 203 of 255
    // inventory cells under the wrong source.
    const lastFastest = !run.six;
    const blockPath = id.split('.').map(easLinkName);
    const shape = sampled ? (timeDependent ? [nt, S] : [S]) : [per];
    const common = {
      time_dependent: timeDependent ? 'TRUE' : 'FALSE',
      probabilistic: sampled ? 'TRUE' : 'FALSE',
      n_iter: sampled ? S : null,
      block: id,
      kind,
      created_time: created
    };
    // The groups that hold this output's members -- one, or one per index
    // of the other lists -- and the units of what each holds.
    const holders = new Map();

    for (let c = 0; c < cells; c++) {
      const position = new Array(dims.length);
      let rest = c;
      for (let k = 0; k < dims.length; k++) {
        const j = lastFastest ? dims.length - 1 - k : k;
        position[j] = rest % dims[j].members.length;
        rest = Math.floor(rest / dims[j].members.length);
      }
      const names = position.map((p, k) => dims[k].members[p]);
      const label = names.length ? `${id} [${names.join(', ')}]` : id;
      const unit = unitOf(position);
      const path = names.length
        ? [...blockPath, ...names.filter((_, k) => k !== leaf).map(easLinkName), easLinkName(names[leaf])]
        : blockPath;
      const at = block.start;
      // Realisation by realisation, each its times -- or its one value, for
      // what cannot change over the run: cell c of row (sim, ti) is number
      // (sim * per + ti) * cells + c. A probabilistic series is written as
      // this page reads one, time by time with a column per realisation.
      const make = () => {
        const out = new Float64Array(S * per);
        for (let sim = 0; sim < S; sim++) {
          for (let ti = 0; ti < per; ti++) {
            out[ti * S + sim] = file.view.getFloat64(at + ((sim * per + ti) * cells + c) * 8, false);
          }
        }
        return out;
      };
      const holder = easPlace(root, path, {
        kind: 'dataset', shape, make,
        attrs: { unit, ...common, name: label, index: [label] }
      });
      if (names.length) {
        if (!holders.has(holder)) holders.set(holder, new Set());
        holders.get(holder).add(unit);
      }
      series++;
    }
    written++;
    // Said once, on each group that holds members: what makes this page draw
    // them together, when they are of a list it charts as one.
    for (const [holder, units] of holders) {
      holder.attrs = {
        IndexLists: [dims[leaf].name],
        unit: units.size === 1 ? [...units][0] : '',
        ...common
      };
    }
  }

  for (const [name, members] of used) {
    easPlace(lists, [easLinkName(name)], {
      kind: 'dataset', shape: [members.length], make: () => members, attrs: { name, members: members.length }
    });
  }

  const start = Number(easText(info, 'start-time'));
  const end = Number(easText(info, 'end-time'));
  const inputs = easKids(easKid(info, 'simulation-inputs'), 'simulation-input').map(i => i.textContent.trim());
  root.attrs = {
    source: assessment.version ? `Ecolego ${assessment.version}` : 'Ecolego',
    assessment: fileName,
    run: run.label,
    archived: run.archived ? 'TRUE' : 'FALSE',
    created_time: created,
    'simulation type': run.probabilistic ? 'PROBABILISTIC' : 'DETERMINISTIC',
    n_iter: sampled ? S : null,
    time_unit: timeUnit,
    start_time: Number.isFinite(start) ? start : null,
    end_time: Number.isFinite(end) ? end : null,
    solver: easText(info, 'java-solver'),
    'abs-error-tolerance': Number(easText(info, 'abs-error-tolerance') ?? NaN),
    'rel-error-tolerance': Number(easText(info, 'rel-error-tolerance') ?? NaN),
    'simulation inputs': inputs.length ? inputs : null,
    outputs: written,
    series,
    'not read': notRead || null,
    Information: easInformation(fileName, assessment, run, { S, sampled, start, end, timeUnit, written, series, notRead })
  };
  return { tree: root, series, notRead };
}

/**
 * The root's Information, which the page shows when the pointer is over the
 * file's tab: which run this is, as markup with every name escaped.
 */
function easInformation(fileName, assessment, run, s) {
  const e = escapeHtml;
  const which = run.name ? `the run “${e(run.name)}”` : `the ${run.archived ? 'archived run' : 'current run'}`;
  const saved = run.date ? `, saved ${e(easStamp(run.date).slice(0, 16))}` : '';
  const kind = s.sampled ? `Probabilistic, ${s.S.toLocaleString('en-US')} realisations` : 'Deterministic';
  const span = Number.isFinite(s.start) && Number.isFinite(s.end)
    ? `, ${e(String(s.start))} to ${e(String(s.end))} ${e(s.timeUnit)}` : '';
  const notRead = s.notRead ? `; ${s.notRead} could not be read` : '';
  return `<p>${e(fileName)}: ${which}${saved}, from ${e(assessment.version ? `Ecolego ${assessment.version}` : 'Ecolego')}.</p>`
    + `<p>${kind}${span}. ${s.written.toLocaleString('en-US')} outputs, `
    + `${s.series.toLocaleString('en-US')} series${notRead}.</p>`;
}

/* ── writing it ──────────────────────────────────────────────────────── */

/** Attributes onto an h5wasm object: strings, lists of strings and numbers. */
function easSetAttributes(obj, attrs) {
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null) continue;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) continue;
      obj.create_attribute(name, value, [],
        Number.isInteger(value) && EAS_INTEGER_ATTRIBUTES.has(name) ? '<i' : '<d');
    } else if (Array.isArray(value)) {
      if (value.length) obj.create_attribute(name, value.map(String));
    } else {
      obj.create_attribute(name, String(value));
    }
  }
}

/**
 * A tree written as an HDF5 file in h5wasm's memory, and its bytes.
 *
 * Writing holds the page about a tenth of a millisecond per series, so it
 * stops to let the page draw now and then and says how far it has come.
 *
 * @param {Object} tree - From easRunTree
 * @param {function(number): void} [onProgress] - Series written so far
 * @returns {Promise<ArrayBuffer>}
 */
async function easWriteHdf5(tree, onProgress) {
  await waitForH5Wasm();
  const { FS, File } = window.h5wasm;
  const path = `/eas_${Date.now()}_${Math.random().toString(36).slice(2, 11)}.h5`;
  let written = 0;
  let paused = performance.now();
  // A frame when the page is in view; a timer when it is not, which gets none.
  const breathe = () => Promise.race([new Promise(requestAnimationFrame),
                                      new Promise(resolve => setTimeout(resolve, 50))]);
  try {
    const f = new File(path, 'w');
    try {
      easSetAttributes(f, tree.attrs);
      const walk = async (into, node) => {
        for (const [name, child] of node.children) {
          if (child.kind === 'group') {
            const g = into.create_group(name);
            easSetAttributes(g, child.attrs);
            await walk(g, child);
            continue;
          }
          const data = child.make();
          const ds = Array.isArray(data)
            ? into.create_dataset({ name, data })
            : into.create_dataset({ name, data, shape: child.shape, dtype: '<d' });
          easSetAttributes(ds, child.attrs);
          written++;
          if (performance.now() - paused > 150) {
            if (onProgress) onProgress(written);
            await breathe();
            paused = performance.now();
          }
        }
      };
      await walk(f, tree);
    } finally {
      f.close();
    }
    const bytes = FS.readFile(path);
    return bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength
      ? bytes.buffer : bytes.slice().buffer;
  } finally {
    try { FS.unlink(path); } catch (e) { ignoreFailure('easWriteHdf5', e); }
  }
}

/* ── opening one ─────────────────────────────────────────────────────── */

/**
 * Open an Ecolego assessment: each run it keeps that the reader picks, as a
 * file of its own. One run opens straight away; for several the reader is
 * asked which, all of them ticked. Does not refresh the tree.
 *
 * A run that cannot be read is reported and the others still open.
 *
 * @param {string} fileName - The assessment's display name
 * @param {ArrayBuffer} buffer - Its bytes
 * @param {string} [context] - Label for failure reporting
 * @returns {Promise<string[]>} The names the runs were registered under
 */
async function ingestEcolegoAssessment(fileName, buffer, context = 'ingestEcolegoAssessment') {
  if (!buffer || typeof buffer.byteLength !== 'number' || buffer.byteLength === 0) {
    throw new Error(`${fileName} is empty.`);
  }
  if (buffer.byteLength > KVOT_FILE_SIZE_LIMITS.dataset) {
    throw new Error(kvotFileTooLarge({ name: fileName, size: buffer.byteLength },
                                     KVOT_FILE_SIZE_LIMITS.dataset).reason);
  }
  setFileLoadProgress(null, `${fileName} — reading the runs it keeps…`);
  const bytes = new Uint8Array(buffer);
  const assessment = await readEcolegoAssessment(fileName, bytes);
  const { runs } = assessment;

  let picked = runs.map((_, i) => i);
  if (runs.length > 1) {
    setFileLoadProgress(null, `${fileName} — which runs to open?`);
    picked = await rbAskChoices({
      title: `Runs in ${fileName}`,
      message: `This assessment keeps ${runs.length} runs. Each one you pick opens as a file of its own.`,
      okLabel: 'Open',
      allLabel: 'All runs',
      choices: runs.map(run => ({
        label: run.label,
        detail: [run.probabilistic ? 'probabilistic' : 'deterministic',
                 run.archived ? 'archived' : 'current',
                 run.date && run.name ? easStamp(run.date).slice(0, 16) : null,
                 `${run.outputs.toLocaleString('en-US')} outputs`].filter(Boolean).join(' · '),
        checked: true
      }))
    });
    if (!picked || !picked.length) return [];
  }

  // A tab for each run: the assessment's name alone when it keeps one run,
  // with the run's label after it when it keeps several, whichever are opened.
  const base = fileName.replace(/\.eas$/i, '');
  const taken = new Set();
  const names = runs.map((run) => {
    let name = runs.length === 1 ? fileName : `${fileName} · ${run.label}`;
    for (let n = 2; taken.has(name); n++) name = `${fileName} · ${run.label} (${n})`;
    taken.add(name);
    return name;
  });
  const saveName = (i) => `${base}${runs.length === 1 ? '' : ` - ${names[i].slice(fileName.length + 3)}`}.h5`
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');

  const opened = [];
  for (const [k, i] of picked.entries()) {
    const run = runs[i];
    const step = picked.length > 1 ? `${fileName} — run ${k + 1} of ${picked.length}, ${run.label}` : fileName;
    try {
      setFileLoadProgress(null, `${step}: unpacking…`);
      const dta = await easZipRead(bytes, run.entry);
      const { tree, series } = easRunTree(assessment, run, dta, fileName);
      setFileLoadProgress(null, `${step}: writing ${series.toLocaleString('en-US')} series…`);
      await yieldForPaint();
      const h5 = await easWriteHdf5(tree, (done) => setFileLoadProgress(series ? done / series : null,
        `${step}: ${done.toLocaleString('en-US')} of ${series.toLocaleString('en-US')} series written…`));
      const name = await ingestHdf5Buffer(names[i], h5, context);
      easOpenedRuns.set(name, { assessment: fileName, run: run.label, saveAs: saveName(i) });
      opened.push(name);
    } catch (err) {
      if (picked.length === 1) throw err;
      reportFailure(context, err, { userMessage: `Could not open the run “${run.label}” of ${fileName}.` });
    }
  }
  return opened;
}

/* ── the run as a file elsewhere ─────────────────────────────────────── */

/**
 * The name a file is known by outside this page. A run opened from an
 * assessment exists only here until it is saved, and is saved as HDF5 under
 * this name (saveOpenedRun); a Python script that reads it names that file.
 *
 * @param {string} fileKey - The name a file was registered under
 * @returns {string}
 */
function pythonFileName(fileKey) {
  const opened = easOpenedRuns.get(fileKey);
  return opened && loadedFiles[fileKey] ? opened.saveAs : fileKey;
}

/**
 * The open runs among a script's files: for each name a script reads, the
 * run it is, when it is one.
 *
 * @param {string[]} names - Names as pythonFileName gives them
 * @returns {Array<{name: string, fileKey: string, assessment: string}>}
 */
function openedRunsNamed(names) {
  const out = [];
  for (const [fileKey, opened] of easOpenedRuns) {
    if (loadedFiles[fileKey] && names.includes(opened.saveAs)) {
      out.push({ name: opened.saveAs, fileKey, assessment: opened.assessment });
    }
  }
  return out;
}

/**
 * Save a run opened from an assessment as the HDF5 file it was opened as.
 *
 * @param {string} fileKey - The name it was registered under
 */
function saveOpenedRun(fileKey) {
  const opened = easOpenedRuns.get(fileKey);
  const buffer = loadedFileBuffers[fileKey];
  if (!opened || !(buffer instanceof ArrayBuffer)) {
    notifyUser(`${fileKey} is no longer open.`);
    return;
  }
  const url = URL.createObjectURL(new Blob([buffer], { type: 'application/x-hdf5' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = opened.saveAs;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
