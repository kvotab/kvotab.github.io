/* ==========================================================================
   ENSDF.HTML: OPENING AN ENSDF FILE OF YOUR OWN

   Reads what a visitor drops or picks -- a release zip as NNDC publishes it
   (ensdf_YYMMDD.zip), the ensdf.001 ... ensdf.300 files out of one, or any
   ENSDF text -- through ensdf-parse.js, and answers with the same summary
   and per-mass details the built-in release is made of.

   Zip entries are inflated by the browser's own DecompressionStream, so no
   zip library is fetched. Files are read one at a time and each is dropped
   once it has been parsed; a whole release is 265 MB of text and never has
   to be in memory at once.

   Runs in the page's worker (ensdf-worker.js) and, where a worker cannot be
   started -- a page opened from the file system -- on the page itself.

   One global: KVOT_ENSDF_OPEN.
   ========================================================================== */
/* global KVOT_ENSDF */
(function (root) {
  'use strict';

  const P = root.KVOT_ENSDF;

  async function inflateRaw(bytes) {
    if (typeof DecompressionStream === 'undefined') {
      throw new Error('this browser cannot unpack zip files (no DecompressionStream); unzip the release and open the ensdf.* files instead');
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  const looksZip = (b) => b.length >= 4 && b[0] === 0x50 && b[1] === 0x4b && b[2] === 0x03 && b[3] === 0x04;
  const decoder = new TextDecoder('latin1');

  /** A release label from a file name: ensdf_250101.zip -> ENSDF 2025-01-01. */
  function labelFor(names) {
    for (const n of names) {
      const m = /(?:^|[^\d])(\d{2})(\d{2})(\d{2})(?:[^\d]|$)/.exec(n);
      if (/ensdf/i.test(n) && m && +m[2] >= 1 && +m[2] <= 12) return { id: `${m[1]}${m[2]}${m[3]}`, label: `ENSDF 20${m[1]}-${m[2]}-${m[3]}` };
    }
    return { id: '', label: names.length === 1 ? names[0] : `${names.length} ENSDF files` };
  }

  /**
   * @param {Array<File|Blob>} files
   * @param {function({done: number, total: number, name: string})} [progress]
   * @returns {Promise<{summary: Object, details: Map<number, Object>}>}
   */
  async function readFiles(files, progress) {
    const builder = P.createBuilder();
    const names = files.map((f) => f.name || 'file');
    /* First pass: what is there to read, so progress can count it. */
    const jobs = [];
    for (const f of files) {
      /* Only a zip is read whole up front; plain files wait their turn. */
      const head = new Uint8Array(await f.slice(0, 4).arrayBuffer());
      if (looksZip(head)) {
        const bytes = new Uint8Array(await f.arrayBuffer());
        let entries = P.zipEntries(bytes).filter((e) => !e.name.endsWith('/'));
        const ens = entries.filter((e) => P.isEnsdfName(e.name));
        if (ens.length) entries = ens;
        entries.sort((p, q) => p.name.localeCompare(q.name, 'en', { numeric: true }));
        for (const e of entries) jobs.push({ name: e.name, zip: bytes, entry: e });
      } else {
        jobs.push({ name: f.name || 'file', file: f });
      }
    }
    let done = 0;
    for (const job of jobs) {
      let data;
      if (job.entry) {
        const raw = job.zip.subarray(job.entry.offset, job.entry.offset + job.entry.csize);
        if (job.entry.method === 0) data = raw;
        else if (job.entry.method === 8) data = await inflateRaw(raw);
        else throw new Error(`${job.name}: compression method ${job.entry.method} is not supported`);
      } else data = new Uint8Array(await job.file.arrayBuffer());
      builder.addText(decoder.decode(data));
      job.zip = null; job.file = null;
      done++;
      if (progress) progress({ done, total: jobs.length, name: job.name });
    }
    const id = labelFor(names);
    const result = builder.finish({ id: id.id || 'opened', label: id.label, source: names.join(', '), opened: true });
    if (!result.summary.release.nuclides) {
      throw new Error('no adopted ENSDF data sets were found; is this an ENSDF file?');
    }
    return result;
  }

  root.KVOT_ENSDF_OPEN = { readFiles, labelFor };
})(typeof self !== 'undefined' ? self : this);
