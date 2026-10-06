/*
  dose_coefficients.html: decay data made from a release of ENSDF that a
  visitor opens -- a release zip as NNDC publishes it (or its parts), or the
  ensdf.001 ... ensdf.300 files out of one -- in a module worker of its own,
  by ensdf-make.js, the module scripts/gen-dose-ensdf.mjs builds the site's
  release with. What it makes is kept in IndexedDB (decay-store.js), where
  the calculation workers find it.

  main -> worker   {id, type: 'make', files: [File...], key}
                       key: the key the files are kept under in this browser
                       (ensdf-sources.js), or none: then the one it would have
  worker -> main   {id, type: 'progress', stage, done, total, name}
                   {id, type: 'made', key, label, nuclides, ms}
                   {id, type: 'error', message}

  Zip entries are inflated by the browser's DecompressionStream, one at a
  time; a release is read twice (ensdf-make.js) and never held whole.
*/
import '../ensdf-parse.js';   // self.KVOT_ENSDF
import '../ensdf-open.js';    // self.KVOT_ENSDF_OPEN: labelFor
import { makeDecayData } from './ensdf-make.js';
import { SYMBOL } from './ensdf-decay.js';
import { writeFolder, MAKE_VERSION } from './decay-store.js';

const DATA = new URL('../../data/dose/', import.meta.url);
async function fetchJSON(path) {
  const r = await fetch(new URL(path, DATA));
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

async function inflateRaw(bytes) {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('this browser cannot unpack zip files (no DecompressionStream); unzip the release and open the ensdf.* files instead');
  }
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}
const looksZip = (b) => b.length >= 4 && b[0] === 0x50 && b[1] === 0x4b && b[2] === 0x03 && b[3] === 0x04;

/* The ENSDF files among those opened -- zip entries or plain files -- in the
   order of their names, as scripts/gen-dose-ensdf.mjs reads a release. */
async function entriesOf(files) {
  const P = self.KVOT_ENSDF;
  const out = [];
  for (const f of files) {
    const head = new Uint8Array(await f.slice(0, 4).arrayBuffer());
    if (looksZip(head)) {
      const bytes = new Uint8Array(await f.arrayBuffer());
      for (const e of P.zipEntries(bytes).filter((x) => !x.name.endsWith('/') && P.isEnsdfName(x.name))) out.push({ name: e.name, file: f, entry: e });
    } else out.push({ name: f.name || 'file', file: f });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name));
}
async function* texts(entries) {
  const decoder = new TextDecoder('latin1');
  const zips = new Map(); // a zip's bytes, for one reading
  for (const job of entries) {
    let data;
    if (job.entry) {
      if (!zips.has(job.file)) zips.set(job.file, new Uint8Array(await job.file.arrayBuffer()));
      const bytes = zips.get(job.file);
      const raw = bytes.subarray(job.entry.offset, job.entry.offset + job.entry.csize);
      if (job.entry.method === 0) data = raw;
      else if (job.entry.method === 8) data = await inflateRaw(raw);
      else throw new Error(`${job.name}: compression method ${job.entry.method} is not supported`);
    } else data = new Uint8Array(await job.file.arrayBuffer());
    yield { name: job.name, text: decoder.decode(data) };
  }
}

self.onmessage = async (ev) => {
  const msg = ev.data || {};
  const reply = (o) => self.postMessage({ id: msg.id, ...o });
  if (msg.type !== 'make') { reply({ type: 'error', message: `unknown request ${msg.type}` }); return; }
  try {
    const files = msg.files || [];
    const names = files.map((f) => f.name || 'file');
    const lab = self.KVOT_ENSDF_OPEN.labelFor(names);
    const key = msg.key || `${lab.label}|${files.map((f) => `${f.name}:${f.size}`).join('|')}`;
    const entries = await entriesOf(files);
    if (!entries.length) throw new Error('no ENSDF files were found in what was opened');
    // The tables of the making: atomic data of every element, conversion, capture; the systems' own names.
    const [iccTable, captureTable, own103, own60, ...atomics] = await Promise.all([
      fetchJSON('icc/icc.json'), fetchJSON('capture.json'), fetchJSON('icrp103/decay/index.json'), fetchJSON('icrp60/decay/index.json'),
      ...SYMBOL.slice(1, 101).map((s) => fetchJSON(`atomic/${s}.json`).catch(() => null)),
    ]);
    const atomic = new Map(SYMBOL.slice(1, 101).map((s, i) => [s, atomics[i]]));
    const total = entries.length;
    const made = await makeDecayData({
      texts: () => texts(entries),
      ENSDF: self.KVOT_ENSDF,
      tables: { atomic: (s) => atomic.get(s) || null, icc: iccTable, capture: captureTable },
      own: { icrp103: own103.nuclides, icrp60: own60.nuclides },
      page: true,
      release: { id: lab.id || 'opened', label: lab.label, source: `${names.join(', ')}, made in a browser by resources/js/dose/ensdf-make.js` },
      progress: (p) => reply({ type: 'progress', ...p, total }),
    });
    if (!made.stats.kept) throw new Error('the files hold no radionuclide the page can calculate');
    const out = new Map([['decay/index.json', JSON.stringify(made.index)], ['notes.json', JSON.stringify(made.notes)]]);
    for (const [el, obj] of Object.entries(made.elements)) out.set(`decay/${el}.json`, JSON.stringify(obj));
    await writeFolder(key, { label: lab.label, version: MAKE_VERSION, nuclides: made.stats.kept, source: made.index.source }, out);
    reply({ type: 'made', key, label: lab.label, nuclides: made.stats.kept, ms: made.stats.ms });
  } catch (e) {
    reply({ type: 'error', message: (e && e.message) || String(e) });
  }
};
