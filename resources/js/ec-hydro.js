/* ==========================================================================
   EROSION_CORROSION.HTML: READING THE HYDRO DATA

   The model wants, for every deposition hole of a layout, ten numbers from
   the hydrogeological modelling (R-09-20, appendix B):

     ID       the position number             OKFLAG  0 when the particle reached the surface
     U0       Darcy flux, m/yr                QEQ     equivalent flow rate, m³/yr
     TW       advective travel time, yr       F       flow-related transport resistance, yr/m
     TRAPP    transport aperture, m           FPC     0, 1 (FPC fracture) or 2 (deformation zone)
     EFPC     number of adjacent holes cut by the same fracture
     FLEN     length of the largest intersecting fracture, m

   Those numbers arrive in four shapes, and this file turns each of them into
   one plain table:

     ConnectFlow CSV    *_pline_merged.csv and the like: a header
                        row (NPOINT or POINT, ..., U0, QEQ, TW, F, ..., TRAPP,
                        ..., FPC, EFPC, FLEN) and one row per hole. Also what
                        Excel writes from the workbook's hydro sheets.
     ConnectFlow PTB    the parameter-table file the CSVs were made from:
                        '#' comment lines, a '# POINT XS YS ...' header and
                        whitespace-separated rows.
     Excel              an .xlsx whose first fitting sheet is such a table
                        (the Corr/Uncorr workbooks).
                        Needs JSZip on the page.
     DarcyTools         the performance-measure tables of the Hydro-SÄK work
                        (Kemakta): a 'Name' column, ten particle rows per
                        hole, columns 'U [m/year]', 'Qeq (ECPM) [m3/year]',
                        'tw [year]', 'F [year/m]', 'iFPC', 'iEFPC', and either
                        'Aperture [m]' + 'Utot [m/year]' (.dtpm, with a
                        'Total DHs:' line above the header) or 'Porosity
                        (ECPM)' + 'Number of fractures in contact with
                        Deposition hole'. Read as the 2.0 and 2.4 Python
                        ports read them; see kemakta() below.

   The result is {name, format, n, id, okflag, u0, qeq, tw, f, trapp, fpc,
   efpc, flen, inflowReject, velocityIsDirect, warnings, meta}. Anything
   odd -- a missing column, a padded layout, a value that would not parse --
   is a warning on the table, not an exception, so the page can show the
   data and say what is doubtful about it.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ECHydro = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const COLUMNS = ['okflag', 'u0', 'qeq', 'tw', 'f', 'trapp', 'fpc', 'efpc', 'flen'];

  /** Column headers as they appear in ConnectFlow output, upper-cased, and what they mean here. */
  const CONNECTFLOW_NAMES = {
    id: ['POINT', 'NPOINT', 'ID', 'IDPROB', 'NAME', 'HOLE'],
    okflag: ['OKFLAG', 'OK_FLAG', 'OK'],
    u0: ['U0', 'U_0', 'U'],
    qeq: ['QEQ', 'Q_EQ'],
    tw: ['TW', 'T_W'],
    f: ['F'],
    trapp: ['TRAPP', 'TR_APP', 'APERTURE'],
    fpc: ['FPC'],
    efpc: ['EFPC'],
    flen: ['FLEN', 'L_FRAC', 'FRACLEN'],
  };

  function cleanHeader(h) {
    return String(h ?? '').replace(/^﻿/, '').replace(/^#/, '').trim();
  }

  function toNumber(tok) {
    if (typeof tok === 'number') return tok;
    let s = String(tok ?? '').trim();
    if (!s) return 0;
    if (s === 'T' || s === 'TRUE' || s === 'True' || s === 'true') return 1;
    if (s === 'F' || s === 'FALSE' || s === 'False' || s === 'false') return 0;
    // A decimal comma, when the token has no dot.
    if (!s.includes('.') && /^[-+]?\d+,\d+(?:[eEdD][-+]?\d+)?$/.test(s)) s = s.replace(',', '.');
    s = s.replace(/[dD](?=[-+]?\d+$)/, 'e');       // Fortran exponents
    const x = Number(s);
    return Number.isFinite(x) ? x : NaN;
  }

  /** Split one delimited line. Quotes are honoured only because Excel writes them. */
  function splitLine(line, delim) {
    if (delim === /\s+/) return line.trim().split(/\s+/);
    if (!line.includes('"')) return line.split(delim);
    const out = [];
    let cur = '';
    let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { q = !q; continue; }
      if (!q && ch === delim) { out.push(cur); cur = ''; continue; }
      cur += ch;
    }
    out.push(cur);
    return out;
  }

  /** The delimiter a header line uses: comma, semicolon, tab or whitespace. */
  function detectDelimiter(headerLine) {
    const counts = { ',': (headerLine.match(/,/g) || []).length, ';': (headerLine.match(/;/g) || []).length, '\t': (headerLine.match(/\t/g) || []).length };
    let best = ',';
    for (const d of [';', '\t']) if (counts[d] > counts[best]) best = d;
    if (counts[best] === 0) return /\s+/;
    return best;
  }

  /* ---------------------------------------------------------------------
     From a table of strings/numbers to the ten columns
     --------------------------------------------------------------------- */

  function emptyHydro(name, format, n) {
    const h = { name, format, n, id: new Array(n), warnings: [], meta: {}, velocityIsDirect: false };
    for (const c of COLUMNS) h[c] = new Float64Array(n);
    h.inflowReject = new Float64Array(n);
    return h;
  }

  /**
   * A header array and rows of tokens, ConnectFlow style: find each wanted
   * column by name and read it.
   */
  function fromConnectflowTable(header, rows, name, format) {
    const upper = header.map((h) => cleanHeader(h).toUpperCase());
    const find = (names) => { for (const nm of names) { const i = upper.indexOf(nm); if (i >= 0) return i; } return -1; };
    const idx = {};
    for (const [key, names] of Object.entries(CONNECTFLOW_NAMES)) idx[key] = find(names);
    const missing = COLUMNS.filter((c) => idx[c] < 0);
    const essential = ['u0', 'trapp'].filter((c) => idx[c] < 0);
    if (essential.length) {
      throw new Error(`Not a hydro table: no column called ${essential.map((c) => CONNECTFLOW_NAMES[c][0]).join(' or ')} in the header (${header.slice(0, 12).join(', ')}${header.length > 12 ? ', …' : ''}).`);
    }
    // Rows with an empty first token (trailing blanks) are dropped.
    const data = rows.filter((r) => r.length > 1 && String(r[Math.max(0, idx.id)] ?? '').trim() !== '');
    const n = data.length;
    const h = emptyHydro(name, format, n);
    let bad = 0;
    for (let i = 0; i < n; i++) {
      const r = data[i];
      h.id[i] = idx.id >= 0 ? idOf(r[idx.id], i) : i + 1;
      for (const c of COLUMNS) {
        if (idx[c] < 0) continue;
        const x = toNumber(r[idx[c]]);
        if (Number.isNaN(x)) { bad++; h[c][i] = 0; } else h[c][i] = x;
      }
    }
    if (missing.length) h.warnings.push(`Column${missing.length > 1 ? 's' : ''} ${missing.map((c) => c.toUpperCase()).join(', ')} not in the file; taken as zero.`);
    if (bad) h.warnings.push(`${bad} value${bad > 1 ? 's' : ''} could not be read as a number and were taken as zero.`);
    return h;
  }

  function idOf(tok, i) {
    if (typeof tok === 'number') return Number.isInteger(tok) ? tok : tok;
    const s = String(tok).trim();
    if (/^[-+]?\d+(?:\.0+)?(?:[eE]\+?\d+)?$/.test(s)) { const x = Number(s); if (Number.isFinite(x) && Math.abs(x) < 1e15) return Math.round(x); }
    return s || i + 1;
  }

  /* ---------------------------------------------------------------------
     DarcyTools / Kemakta performance-measure tables
     --------------------------------------------------------------------- */

  /**
   * Both variants have a 'Name' column with several particle rows per hole;
   * the first row of each name is taken, in file order (the 2.4 port). The
   * flag columns of the .dtpm variant are T/F strings where F means the hole
   * FAILS a qualification criterion:
   *
   *   Collected = F  ->  OKFLAG = 1       ZFMC = F  ->  FPC = 2
   *   FPC = F        ->  FPC = 1          EFPC-5 = F -> EFPC = 5
   *
   * The older CSV variant carries iFPC/iEFPC as (signed) fracture ids whose
   * absolute value is used, no aperture -- TRAPP = 8·porosity/(fractures in
   * contact) -- and 'U [m/year]' scaled by 8/w to match the Serco-style U0.
   * FLEN does not exist in either, so the fracture-length and T/L criteria
   * cannot apply, and the table is padded with empty holes to the size of
   * the layout when that is known (the 'Total DHs:' line of a .dtpm, or the
   * number given by the caller), because the normalisation counts them.
   */
  function fromKemaktaTable(header, rows, name, format, opts) {
    const hdr = header.map((h) => cleanHeader(h));
    const col = (label) => hdr.findIndex((h) => h.toLowerCase() === label.toLowerCase());
    const colStarts = (label) => hdr.findIndex((h) => h.toLowerCase().startsWith(label.toLowerCase()));
    const iName = col('Name');
    if (iName < 0) throw new Error('Not a DarcyTools table: no Name column.');
    const first = new Map();
    for (const r of rows) {
      const nm = String(r[iName] ?? '').trim();
      if (!nm || first.has(nm)) continue;
      first.set(nm, r);
    }
    const names = Array.from(first.keys());
    const nFound = names.length;
    const total = Math.max(nFound, Math.round(opts.totalHoles || 0) || 0);
    const h = emptyHydro(name, format, total);
    h.meta.holesInFile = nFound;
    h.meta.padded = total - nFound;

    const iU = col('U [m/year]'); const iUtot = col('Utot [m/year]');
    const iQ = colStarts('Qeq (ECPM)'); const iTw = col('tw [year]'); const iF = col('F [year/m]');
    const iAp = col('Aperture [m]'); const iPor = colStarts('Porosity (ECPM)');
    const iNfr = colStarts('Number of fractures in contact');
    const iCollected = col('Collected'); const iZfmc = col('ZFMC'); const iFpcTF = col('FPC'); const iEfpc5 = col('EFPC-5');
    const iFpc = col('iFPC'); const iEfpc = col('iEFPC');
    const dtpmStyle = iAp >= 0 && iUtot >= 0;
    h.velocityIsDirect = dtpmStyle;
    h.meta.variant = dtpmStyle ? 'dtpm' : 'csv';
    const w = opts.w || 5;
    const isF = (tok) => String(tok ?? '').trim().toUpperCase() === 'F';

    names.forEach((nm, i) => {
      const r = first.get(nm);
      h.id[i] = nm;
      if (iQ >= 0) h.qeq[i] = toNumber(r[iQ]) || 0;
      if (iTw >= 0) h.tw[i] = toNumber(r[iTw]) || 0;
      if (iF >= 0) h.f[i] = toNumber(r[iF]) || 0;
      if (dtpmStyle) {
        h.trapp[i] = toNumber(r[iAp]) || 0;
        h.u0[i] = toNumber(r[iUtot]) || 0;               // a velocity, m/yr
        if (iCollected >= 0) h.okflag[i] = isF(r[iCollected]) ? 1 : 0;
        let fpc = 0;
        if (iFpcTF >= 0 && isF(r[iFpcTF])) fpc = 1;
        if (iZfmc >= 0 && isF(r[iZfmc])) fpc = 2;
        h.fpc[i] = fpc;
        if (iEfpc5 >= 0) h.efpc[i] = isF(r[iEfpc5]) ? 5 : 0;
      } else {
        const por = iPor >= 0 ? toNumber(r[iPor]) || 0 : 0;
        const nfr = iNfr >= 0 ? toNumber(r[iNfr]) || 0 : 0;
        h.trapp[i] = nfr > 0 ? 8 * por / nfr : 0;
        h.u0[i] = (iU >= 0 ? toNumber(r[iU]) || 0 : 0) * 8 / w;
        h.fpc[i] = iFpc >= 0 ? Math.abs(toNumber(r[iFpc]) || 0) : 0;
        h.efpc[i] = iEfpc >= 0 ? Math.abs(toNumber(r[iEfpc]) || 0) : 0;
      }
    });
    for (let i = nFound; i < total; i++) h.id[i] = '';
    h.warnings.push('No fracture length (FLEN) in a DarcyTools table: the fracture-length and T/L criteria reject nothing.');
    if (!dtpmStyle) h.warnings.push(`Aperture taken as 8·porosity/(fractures in contact) and U0 as 8/w × U, w = ${w} m, as the 2.0 Python port does for this format.`);
    if (h.meta.padded > 0) h.warnings.push(`${nFound} holes in the file, padded with ${h.meta.padded} empty holes to the ${total} of the layout.`);
    else if (!opts.totalHoles && !opts.totalFromFile) h.warnings.push(`${nFound} holes in the file and no layout size given: the normalisation uses ${nFound}.`);
    return h;
  }

  /* ---------------------------------------------------------------------
     Text files
     --------------------------------------------------------------------- */

  function detectFormat(text) {
    const head = text.slice(0, 20000);
    if (/PARAMETER TABLE FILE FROM CONNECTFLOW/i.test(head)) return 'ptb';
    const lines = head.split(/\r?\n/);
    let i = 0;
    while (i < lines.length && !lines[i].trim()) i++;
    if (i < lines.length && lines[i].trim().startsWith('#')) {
      // Comment lines then data: a PTB without its banner, or a CSV export
      // whose header begins '# POINT'.
      const firstData = lines.slice(i).find((l) => l.trim() && !l.trim().startsWith('#'));
      if (firstData && !firstData.includes(',') && !firstData.includes(';')) return 'ptb';
    }
    for (const l of lines) {
      if (/^\s*Name\s*,/.test(l) && /F \[year\/m\]/.test(l)) return /Total DHs/i.test(head) ? 'dtpm' : 'kemakta-csv';
    }
    return 'csv';
  }

  function parsePtb(text, name) {
    const lines = text.split(/\r?\n/);
    let header = null;
    const rows = [];
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      if (line.startsWith('#')) {
        const toks = line.replace(/^#+/, '').trim().split(/\s+/);
        // The header is the last comment line that names the columns.
        if (toks.length >= 5 && toks.some((t) => /^(POINT|U0|TRAPP|QEQ)$/i.test(t))) header = toks;
        continue;
      }
      if (line.startsWith('@')) continue;
      if (!header) continue;                       // the counts above the table
      const toks = line.split(/\s+/);
      if (toks.length < header.length - 2) continue;
      rows.push(toks);
    }
    if (!header) throw new Error('No column header (a comment line naming POINT, U0, TRAPP, …) found in the PTB file.');
    return fromConnectflowTable(header, rows, name, 'ConnectFlow PTB');
  }

  function parseDelimited(text, name, format, opts) {
    const lines = text.split(/\r?\n/);
    let start = 0;
    const isKemakta = format === 'dtpm' || format === 'kemakta-csv';
    if (isKemakta) {
      start = lines.findIndex((l) => /^\s*Name\s*,/.test(l));
      if (start < 0) throw new Error('No "Name," header line in the DarcyTools table.');
      const m = lines.slice(0, start).join('\n').match(/Total DHs\s*[:=]\s*(\d+)/i);
      if (m) opts = { ...opts, totalHoles: opts.totalHoles || Number(m[1]), totalFromFile: true };
    } else {
      while (start < lines.length && !lines[start].trim()) start++;
    }
    const headerLine = lines[start];
    const delim = detectDelimiter(headerLine);
    const header = splitLine(headerLine, delim).map(cleanHeader);
    const rows = [];
    for (let i = start + 1; i < lines.length; i++) {
      const l = lines[i];
      if (!l.trim()) continue;
      rows.push(splitLine(l, delim));
    }
    if (isKemakta) {
      const h = fromKemaktaTable(header, rows, name, format === 'dtpm' ? 'DarcyTools dtpm' : 'DarcyTools CSV', opts);
      if (opts.totalFromFile) h.meta.totalFromFile = opts.totalHoles;
      return h;
    }
    return fromConnectflowTable(header, rows, name, 'ConnectFlow CSV');
  }

  /**
   * Parse the text of a hydro file.
   * @param {string} text
   * @param {string} name   for messages
   * @param {object} [opts] {totalHoles, w}
   */
  function parseText(text, name, opts = {}) {
    const format = detectFormat(text);
    const h = format === 'ptb' ? parsePtb(text, name) : parseDelimited(text, name, format, opts);
    finish(h);
    return h;
  }

  /** Checks common to every format, as warnings. */
  function finish(h) {
    if (h.n === 0) throw new Error(`${h.name}: no deposition holes were read.`);
    let neg = 0;
    for (let i = 0; i < h.n; i++) { if (h.u0[i] < 0 || h.trapp[i] < 0) neg++; }
    if (neg) h.warnings.push(`${neg} hole${neg > 1 ? 's have' : ' has'} a negative U0 or aperture.`);
    let flowing = 0;
    for (let i = 0; i < h.n; i++) if (h.trapp[i] > 0 && h.u0[i] > 0) flowing++;
    h.meta.flowing = flowing;
    // Duplicate ids make the failure table ambiguous; say so.
    const seen = new Set();
    let dup = 0;
    for (const id of h.id) { const k = String(id); if (k && seen.has(k)) dup++; seen.add(k); }
    if (dup) h.warnings.push(`${dup} duplicate hole ID${dup > 1 ? 's' : ''}.`);
  }

  /* ---------------------------------------------------------------------
     Excel workbooks (needs JSZip)
     --------------------------------------------------------------------- */

  const XML_ENTITIES = { '&lt;': '<', '&gt;': '>', '&amp;': '&', '&quot;': '"', '&apos;': "'" };
  function unxml(s) {
    return s.replace(/&(lt|gt|amp|quot|apos);/g, (m) => XML_ENTITIES[m]).replace(/&#(\d+);/g, (m, d) => String.fromCodePoint(Number(d)));
  }

  function attrs(tag) {
    const out = {};
    for (const m of tag.matchAll(/([\w:]+)="([^"]*)"/g)) out[m[1]] = m[2];
    return out;
  }

  function colIndex(ref) {
    const m = /^([A-Z]+)/.exec(ref);
    if (!m) return 0;
    let c = 0;
    for (const ch of m[1]) c = c * 26 + (ch.charCodeAt(0) - 64);
    return c - 1;
  }

  /** One worksheet's XML as rows of values (numbers, strings, booleans). */
  function sheetRows(xml, shared) {
    const rows = [];
    for (const rowM of xml.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
      const cells = [];
      for (const cM of rowM[1].matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
        const a = attrs(cM[1]);
        const inner = cM[2] || '';
        const ci = colIndex(a.r || '');
        let val = '';
        const vM = /<v>([\s\S]*?)<\/v>/.exec(inner);
        if (a.t === 's') val = shared[Number(vM ? vM[1] : -1)] ?? '';
        else if (a.t === 'inlineStr') val = unxml((inner.match(/<t[^>]*>([\s\S]*?)<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join(''));
        else if (a.t === 'b') val = vM && vM[1] === '1' ? 'TRUE' : 'FALSE';
        else if (a.t === 'str' || a.t === 'e') val = vM ? unxml(vM[1]) : '';
        else val = vM ? Number(vM[1]) : '';
        while (cells.length < ci) cells.push('');
        cells[ci] = val;
      }
      if (cells.some((c) => c !== '')) rows.push(cells);
    }
    return rows;
  }

  /**
   * Read a hydro table out of an .xlsx: the first sheet whose header row has
   * U0 and TRAPP (a ConnectFlow table) or Name and 'F [year/m]' (DarcyTools).
   * @param {ArrayBuffer} buf
   */
  async function parseXlsx(buf, name, opts = {}) {
    const JSZipRef = (typeof JSZip !== 'undefined') ? JSZip : (typeof require === 'function' ? tryRequire('jszip') : null);
    if (!JSZipRef) throw new Error('Reading an Excel file needs JSZip, which did not load. Save the sheet as CSV instead.');
    const zip = await JSZipRef.loadAsync(buf);
    const wbXml = await zip.file('xl/workbook.xml').async('string');
    const relXml = await zip.file('xl/_rels/workbook.xml.rels').async('string');
    const rels = {};
    for (const m of relXml.matchAll(/<Relationship\b([^>]*)\/?>/g)) { const a = attrs(m[1]); rels[a.Id] = a.Target; }
    const sheets = [];
    for (const m of wbXml.matchAll(/<sheet\b([^>]*)\/?>/g)) {
      const a = attrs(m[1]);
      let target = rels[a['r:id']] || '';
      target = target.replace(/^\/?(xl\/)?/, 'xl/');
      sheets.push({ name: a.name, path: target });
    }
    let shared = [];
    const ssFile = zip.file('xl/sharedStrings.xml');
    if (ssFile) {
      const ss = await ssFile.async('string');
      shared = Array.from(ss.matchAll(/<si>([\s\S]*?)<\/si>/g), (m) => unxml((m[1].match(/<t[^>]*>([\s\S]*?)<\/t>/g) || []).map((t) => t.replace(/<[^>]+>/g, '')).join('')));
    }
    const tried = [];
    for (const sh of sheets) {
      const f = zip.file(sh.path);
      if (!f) continue;
      const rows = sheetRows(await f.async('string'), shared);
      if (!rows.length) continue;
      const header = rows[0].map((h) => cleanHeader(h));
      const upper = header.map((h) => h.toUpperCase());
      const label = `${name} [${sh.name}]`;
      if (upper.includes('U0') && upper.includes('TRAPP')) {
        const h = fromConnectflowTable(header, rows.slice(1), label, 'ConnectFlow table (Excel)');
        finish(h);
        return h;
      }
      if (header.includes('Name') && header.includes('F [year/m]')) {
        const h = fromKemaktaTable(header, rows.slice(1), label, 'DarcyTools table (Excel)', opts);
        finish(h);
        return h;
      }
      tried.push(sh.name);
    }
    throw new Error(`No sheet of ${name} has a hydro header (U0 and TRAPP, or Name and F [year/m]). Sheets: ${tried.join(', ') || 'none'}.`);
  }

  function tryRequire(mod) { try { return require(mod); } catch (e) { return null; } }

  /**
   * In the browser: a File from an <input> or a drop. Decides on the
   * extension, then on the content.
   */
  async function load(file, opts = {}) {
    const name = file.name || 'hydro data';
    if (/\.xlsx$/i.test(name) || /\.xlsm$/i.test(name)) {
      return parseXlsx(await file.arrayBuffer(), name, opts);
    }
    const text = await file.text();
    return parseText(text, name, opts);
  }

  /**
   * An inflow-rejection list: hole IDs, one per line or separated by
   * commas/whitespace, optionally 'ID,flag' pairs where a flag of 0 clears
   * the rejection. Returns a Set of IDs (as strings).
   */
  function parseInflowList(text) {
    const set = new Set();
    for (const raw of String(text || '').split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const toks = line.split(/[\s;,]+/).filter(Boolean);
      if (toks.length >= 2 && /^\d+$/.test(toks[0]) && /^[01]$/.test(toks[1])) {
        if (toks[1] === '1') set.add(String(Math.round(Number(toks[0]))));
        continue;
      }
      for (const t of toks) set.add(/^\d+(\.0+)?$/.test(t) ? String(Math.round(Number(t))) : t);
    }
    return set;
  }

  /** Mark the holes of `hydro` whose ID is in `idSet`. Returns how many matched. */
  function applyInflowList(hydro, idSet) {
    let n = 0;
    hydro.inflowReject = new Float64Array(hydro.n);
    for (let i = 0; i < hydro.n; i++) {
      if (idSet.has(String(hydro.id[i]))) { hydro.inflowReject[i] = 1; n++; }
    }
    return n;
  }

  /** The table as CSV text (the ten columns), for saving what was read. */
  function toCsv(h) {
    const lines = ['POINT,OKFLAG,U0,QEQ,TW,F,TRAPP,FPC,EFPC,FLEN'];
    for (let i = 0; i < h.n; i++) {
      lines.push([h.id[i], h.okflag[i], h.u0[i], h.qeq[i], h.tw[i], h.f[i], h.trapp[i], h.fpc[i], h.efpc[i], h.flen[i]].join(','));
    }
    return lines.join('\n');
  }

  return { COLUMNS, detectFormat, parseText, parsePtb, parseXlsx, load, parseInflowList, applyInflowList, toCsv, toNumber };
}));
