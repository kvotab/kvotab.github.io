/* ==========================================================================
   SMUI.HTML: FILES IN AND OUT, AND THE EXAMPLE TABLES

   In:  CSV, TSV and other delimited text (the separator and a decimal comma
        are detected), Excel .xlsx (the first sheet, or one chosen), this
        page's own .smui.json (columns, types, row states), and text pasted
        from a spreadsheet.
   Out: CSV, Excel .xlsx and .smui.json.

   Every column's data type is read off its values: numeric when every
   non-missing value is a number, a date when every one is an ISO date,
   character otherwise. Numeric columns start continuous and character
   columns nominal, as in JMP; the Columns panel changes that.

   The example tables are simulated here, from a fixed seed: they are this
   page's own and the same in every browser.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { rng } = SM.util;
  const { isMissing } = SM.table;

  /* ---- delimited text ------------------------------------------------------ */
  function detectDelimiter(text) {
    const lines = text.split(/\r\n|\n|\r/).filter((l) => l.trim()).slice(0, 20);
    let best = ',', score = -1;
    for (const d of ['\t', ';', ',', '|']) {
      const counts = lines.map((l) => splitLine(l, d).length);
      if (!counts.length || counts[0] < 2) continue;
      const same = counts.filter((c) => c === counts[0]).length;
      const s = same * 10 + counts[0];
      if (s > score) { score = s; best = d; }
    }
    return best;
  }

  function splitLine(line, d) {
    const out = [];
    let cur = '', inQ = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (inQ) {
        if (ch === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += ch;
      } else if (ch === '"' && cur === '') inQ = true;
      else if (ch === d) { out.push(cur); cur = ''; }
      else cur += ch;
    }
    out.push(cur);
    return out;
  }

  /* Parse the whole text; quoted fields may span lines. */
  function parseRows(text, d) {
    const rows = [];
    let row = [], cur = '', inQ = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inQ) {
        if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else inQ = false; }
        else cur += ch;
      } else if (ch === '"' && cur === '') inQ = true;
      else if (ch === d) { row.push(cur); cur = ''; }
      else if (ch === '\n' || ch === '\r') {
        if (ch === '\r' && text[i + 1] === '\n') i++;
        row.push(cur); cur = '';
        if (row.length > 1 || row[0] !== '') rows.push(row);
        row = [];
      } else cur += ch;
    }
    if (cur !== '' || row.length) { row.push(cur); if (row.length > 1 || row[0] !== '') rows.push(row); }
    return rows;
  }

  const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(Z|[+-]\d{2}:?\d{2})?$/;

  function parseDate(s) {
    const m = ISO_DATE.exec(s);
    if (!m) return NaN;
    const t = Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
    return Number.isFinite(t) ? t : NaN;
  }

  /* Columns from rows of strings: the first row is the header. */
  function columnsFromRows(rows, { decimalComma = null } = {}) {
    if (!rows.length) throw new Error('the file is empty');
    // (a header on one line: a quoted "a\nb" is a b, SM.table.cleanName)
    const header = rows[0].map((h, i) => (SM.table.cleanName(h) || `Column ${i + 1}`));
    const body = rows.slice(1);
    const ncol = Math.max(header.length, ...body.map((r) => r.length));
    while (header.length < ncol) header.push(`Column ${header.length + 1}`);
    if (decimalComma == null) {
      // A decimal comma: numbers like 1,5 and none like 1.5 in the body.
      let comma = 0, point = 0;
      for (const r of body.slice(0, 200)) for (const v of r) {
        if (/^\s*[-+]?\d+,\d+(e[-+]?\d+)?\s*$/i.test(v)) comma++;
        else if (/^\s*[-+]?\d*\.\d+(e[-+]?\d+)?\s*$/i.test(v)) point++;
      }
      decimalComma = comma > 0 && point === 0;
    }
    const seen = new Set();
    const cols = [];
    for (let j = 0; j < ncol; j++) {
      let name = header[j];
      while (seen.has(name)) name = `${name}_`;
      seen.add(name);
      const raw = body.map((r) => (r[j] == null ? '' : String(r[j]).trim()));
      cols.push(inferColumn(name, raw, decimalComma));
    }
    return cols;
  }

  function inferColumn(name, raw, decimalComma) {
    const miss = (s) => s === '' || s === '.' || /^(na|nan|null|n\/a|missing)$/i.test(s);
    const num = (s) => {
      if (miss(s)) return NaN;
      const t = decimalComma ? s.replace(/\s/g, '').replace(',', '.') : s.replace(/\s/g, '');
      if (!/^[-+−]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t) && !/^[-+]?inf(inity)?$/i.test(t)) return null;
      return SM.table.toNumber(t);
    };
    let numeric = true, dates = true, any = false;
    for (const s of raw) {
      if (miss(s)) continue;
      any = true;
      if (numeric && num(s) === null) numeric = false;
      if (dates && Number.isNaN(parseDate(s))) dates = false;
      if (!numeric && !dates) break;
    }
    if (any && numeric) return { name, dataType: 'numeric', values: raw.map((s) => { const x = num(s); return x == null ? NaN : x; }) };
    if (any && dates) {
      const withTime = raw.some((s) => /[T ]\d{2}:/.test(s));
      return { name, dataType: 'numeric', modelingType: 'continuous', format: { kind: withTime ? 'datetime' : 'date' }, values: raw.map((s) => (miss(s) ? NaN : parseDate(s))) };
    }
    return { name, dataType: 'character', values: raw.map((s) => (miss(s) ? null : s)) };
  }

  function tableFromText(text, name) {
    const clean = text.replace(/^﻿/, '');
    const d = detectDelimiter(clean);
    const rows = parseRows(clean, d);
    return new SM.Table({ name, columns: columnsFromRows(rows), source: `${name} (${d === '\t' ? 'tab' : d === ',' ? 'comma' : d}-separated)` });
  }

  /* ---- Excel ----------------------------------------------------------------- */
  async function readXlsx(buf, name) {
    if (typeof JSZip === 'undefined') throw new Error('the Excel reader (JSZip) did not load; save the sheet as CSV instead');
    const zip = await JSZip.loadAsync(buf);
    const text = async (p) => { const f = zip.file(p); return f ? f.async('string') : null; };
    const parser = new DOMParser();
    const xml = (s) => parser.parseFromString(s, 'application/xml');
    const wb = xml(await text('xl/workbook.xml') || '');
    const rels = xml(await text('xl/_rels/workbook.xml.rels') || '');
    const relTarget = new Map(Array.from(rels.getElementsByTagName('Relationship')).map((r) => [r.getAttribute('Id'), r.getAttribute('Target')]));
    const sheets = Array.from(wb.getElementsByTagName('sheet')).map((s) => ({
      name: s.getAttribute('name'),
      path: 'xl/' + String(relTarget.get(s.getAttribute('r:id')) || relTarget.get(s.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id')) || '').replace(/^\/?xl\//, ''),
    }));
    const shared = [];
    const ss = await text('xl/sharedStrings.xml');
    if (ss) for (const si of Array.from(xml(ss).getElementsByTagName('si'))) shared.push(Array.from(si.getElementsByTagName('t')).map((t) => t.textContent).join(''));
    // Which cell styles are dates.
    const dateStyles = new Set();
    const st = await text('xl/styles.xml');
    if (st) {
      const sx = xml(st);
      const custom = new Map(Array.from(sx.getElementsByTagName('numFmt')).map((f) => [f.getAttribute('numFmtId'), f.getAttribute('formatCode') || '']));
      const xfs = sx.getElementsByTagName('cellXfs')[0];
      if (xfs) Array.from(xfs.getElementsByTagName('xf')).forEach((xf, i) => {
        const id = +xf.getAttribute('numFmtId');
        const code = custom.get(String(id)) || '';
        if ((id >= 14 && id <= 22) || (id >= 45 && id <= 47) || /(^|[^\\"])[dmyhs]{1,4}/i.test(code.replace(/"[^"]*"/g, '').replace(/\[[^\]]*\]/g, ''))) dateStyles.add(i);
      });
    }
    const out = [];
    for (const sh of sheets) {
      const s = await text(sh.path);
      if (!s) continue;
      const doc = xml(s);
      const grid = [];
      const isDate = [];
      for (const row of Array.from(doc.getElementsByTagName('row'))) {
        const r = +row.getAttribute('r') - 1;
        for (const c of Array.from(row.getElementsByTagName('c'))) {
          const ref = c.getAttribute('r');
          const col = colIndex(ref.replace(/\d+$/, ''));
          const t = c.getAttribute('t');
          const v = c.getElementsByTagName('v')[0];
          let val = '';
          if (t === 's') val = v ? shared[+v.textContent] : '';
          else if (t === 'inlineStr') val = Array.from(c.getElementsByTagName('t')).map((x) => x.textContent).join('');
          else if (t === 'b') val = v ? (v.textContent === '1' ? 'TRUE' : 'FALSE') : '';
          else if (v) {
            val = v.textContent;
            if (dateStyles.has(+(c.getAttribute('s') || 0)) && t !== 'str') { (isDate[col] = isDate[col] || []).push(r); }
          }
          (grid[r] = grid[r] || [])[col] = val;
        }
      }
      out.push({ name: sh.name, grid, isDate });
    }
    return out.filter((s) => s.grid.length).map((s) => {
      const rows = Array.from({ length: s.grid.length }, (_, i) => Array.from(s.grid[i] || [], (v) => (v == null ? '' : v)));
      const cols = columnsFromRows(rows, { decimalComma: false });
      s.isDate.forEach((list, j) => {
        const c = cols[j];
        if (!c || c.dataType !== 'numeric' || !list || list.length < (c.values.filter((x) => !Number.isNaN(x)).length)) return;
        // Excel serial days since 1899-12-30 to epoch milliseconds.
        c.values = c.values.map((x) => (Number.isNaN(x) ? NaN : Math.round((x - 25569) * 86400000)));
        c.format = { kind: c.values.some((x) => !Number.isNaN(x) && x % 86400000 !== 0) ? 'datetime' : 'date' };
      });
      return { sheet: s.name, table: new SM.Table({ name: `${name.replace(/\.xlsx?$/i, '')}${out.length > 1 ? ` — ${s.name}` : ''}`, columns: cols, source: `${name}, sheet ${s.name}` }) };
    });
  }

  function colIndex(letters) {
    let n = 0;
    for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  }

  /* ---- reading any supported file ------------------------------------------ */
  async function readFile(file) {
    const name = file.name || 'table';
    const lower = name.toLowerCase();
    if (/\.xlsx?$|\.xlsm$/.test(lower)) {
      if (/\.xls$/.test(lower)) throw new Error('old .xls files cannot be read; save as .xlsx or CSV');
      const sheets = await readXlsx(await file.arrayBuffer(), name);
      if (!sheets.length) throw new Error('the workbook has no data');
      return sheets.map((s) => s.table);
    }
    const text = await file.text();
    if (/\.json$/.test(lower)) return [SM.Table.fromJSON(JSON.parse(text))];
    return [tableFromText(text, name.replace(/\.(csv|tsv|txt|dat|tab)$/i, ''))];
  }

  /* ---- File > Import Multiple Files: a row per file ------------------------
     The files' names (their paths inside a folder that was picked) and
     their text, for Text Explorer; with sizes and dates when asked. A file
     whose text has NUL characters is not text and is left out, and one
     larger than MAX_TEXT_FILE is cut there (the notes say which). */
  const MAX_TEXT_FILE = 8 * 1024 * 1024;
  const MAX_TEXT_TOTAL = 200 * 1024 * 1024;

  function globMatcher(pattern) {
    const parts = String(pattern || '').split(/[;,]/).map((p) => p.trim()).filter(Boolean);
    if (!parts.length || parts.includes('*') || parts.includes('*.*')) return () => true;
    const res = parts.map((p) => new RegExp(`^${p.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`, 'i'));
    return (name) => res.some((re) => re.test(name));
  }

  async function filesTable(files, { name = 'Imported files', filter = '*', sizes = false, dates = false } = {}) {
    const match = globMatcher(filter);
    const coll = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
    const pathOf = (f) => f.webkitRelativePath || f.name;
    const list = [...files].filter((f) => match(f.name)).sort((a, b) => coll.compare(pathOf(a), pathOf(b)));
    const skipped = [], cut = [];
    const names = [], paths = [], texts = [], size = [], date = [];
    let total = 0;
    for (const f of list) {
      if (total >= MAX_TEXT_TOTAL) { skipped.push(`${pathOf(f)} (past ${MAX_TEXT_TOTAL / 1048576} MB in all)`); continue; }
      const blob = f.size > MAX_TEXT_FILE ? f.slice(0, MAX_TEXT_FILE) : f;
      let text = await blob.text();
      if (text.includes('\u0000')) { skipped.push(`${pathOf(f)} (not text)`); continue; }
      if (f.size > MAX_TEXT_FILE) cut.push(pathOf(f));
      text = text.replace(/^﻿/, '');
      total += text.length;
      names.push(f.name); paths.push(pathOf(f)); texts.push(text); size.push(f.size);
      date.push(Number.isFinite(f.lastModified) ? f.lastModified : NaN);
    }
    const anyFolder = paths.some((p, i) => p !== names[i]);
    const columns = [{ name: 'File Name', dataType: 'character', values: names }];
    if (anyFolder) columns.push({ name: 'Path', dataType: 'character', values: paths });
    columns.push({ name: 'Text', dataType: 'character', values: texts, notes: 'the text of each file, for Analyze > Text Explorer' });
    if (sizes) columns.push({ name: 'Size (bytes)', dataType: 'numeric', values: size });
    if (dates) columns.push({ name: 'Date Modified', dataType: 'numeric', format: { kind: 'datetime' }, values: date });
    const t = new SM.Table({ name, columns, source: `File > Import Multiple Files: ${names.length} file${names.length === 1 ? '' : 's'}` });
    const notes = [];
    if (skipped.length) notes.push(`Left out: ${skipped.slice(0, 20).join(', ')}${skipped.length > 20 ? ` and ${skipped.length - 20} more` : ''}.`);
    if (cut.length) notes.push(`Cut at ${MAX_TEXT_FILE / 1048576} MB: ${cut.join(', ')}.`);
    t.notes = notes.join(' ');
    return { table: t, skipped, cut, matched: list.length };
  }

  /* ---- writing -------------------------------------------------------------- */
  /* The files keep the stored values: a missing value code as the code
     (999, as JMP writes it; the reports' code turns it into a missing value
     after reading, SM.table.codedCode), a labelled value as the value. */
  function cellText(c, v) {
    if (isMissing(v)) return '';
    if (c.isNumeric && c.format && (c.format.kind === 'date' || c.format.kind === 'datetime')) return formatDate(v, c.format.kind);
    return String(v);
  }

  const stored = (c, i) => (c.coded && c.coded[i] !== undefined ? c.coded[i] : c.values[i]);

  function toCsv(table, sep = ',') {
    const esc = (s) => (/[",\n\r;\t]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
    const lines = [table.columns.map((c) => esc(c.name)).join(sep)];
    for (let i = 0; i < table.nrows; i++) lines.push(table.columns.map((c) => esc(cellText(c, stored(c, i)))).join(sep));
    return lines.join('\r\n') + '\r\n';
  }

  async function toXlsxBlob(table) {
    if (typeof XlsxWriter === 'undefined') throw new Error('the Excel writer did not load');
    const rows = [table.columns.map((c) => c.name)];
    for (let i = 0; i < table.nrows; i++) rows.push(table.columns.map((c) => { const v = stored(c, i); if (isMissing(v)) return ''; return c.isNumeric && !(c.format && /date/.test(c.format.kind)) ? v : cellText(c, v); }));
    const w = new XlsxWriter(`${table.name}.xlsx`);
    w.writeData(rows, (table.name || 'Data').replace(/[\\/?*[\]:]/g, ' ').slice(0, 31) || 'Data');
    const content = await w.save();
    return content instanceof Blob ? content : new Blob([content], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }

  function formatDate(ms, kind = 'date') {
    if (Number.isNaN(ms)) return '';
    const d = new Date(ms);
    const pad = (n) => String(n).padStart(2, '0');
    const day = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
    return kind === 'datetime' ? `${day} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}` : day;
  }

  /* ---- the example tables, simulated here --------------------------------- */
  const EXAMPLES = {
    students: {
      label: 'Students (60 rows): age, sex, height, weight',
      about: 'Simulated: height grows with age and differs by sex; weight follows height. For Distribution, Fit Y by X and Fit Model.',
      make() {
        const r = rng('students');
        const n = 60, age = [], sex = [], height = [], weight = [], id = [];
        for (let i = 0; i < n; i++) {
          const a = r.int(12, 17), s = r.u() < 0.5 ? 'F' : 'M';
          const h = 118 + 2.6 * a + (s === 'M' ? -1 + 2.8 * (a - 12) : 0) + r.normal(0, 5.5);
          const w = -58 + 0.72 * h + (s === 'M' ? 2.5 : 0) + r.normal(0, 5);
          id.push(`S${String(i + 1).padStart(2, '0')}`); age.push(a); sex.push(s); height.push(+h.toFixed(1)); weight.push(+w.toFixed(1));
        }
        return new SM.Table({ name: 'Students', source: 'simulated', columns: [
          { name: 'id', dataType: 'character', values: id, role: 'label' },
          { name: 'age', dataType: 'numeric', modelingType: 'ordinal', values: age },
          { name: 'sex', dataType: 'character', values: sex },
          { name: 'height (cm)', dataType: 'numeric', values: height },
          { name: 'weight (kg)', dataType: 'numeric', values: weight },
        ] });
      },
    },
    plants: {
      label: 'Plant trial (72 rows): fertilizer × water, light, yield',
      about: 'Simulated two-factor experiment with a covariate and an interaction. For Oneway, Fit Model (least squares, profiler) and Tabulate.',
      make() {
        const r = rng('plants');
        const fert = ['A', 'B', 'C'], water = ['low', 'high'];
        const rows = { plot: [], fertilizer: [], water: [], light: [], yield: [] };
        let k = 0;
        for (const f of fert) for (const w of water) for (let rep = 0; rep < 12; rep++) {
          const light = +(r.normal(6, 1.5)).toFixed(2);
          const y = 20 + (f === 'B' ? 3 : f === 'C' ? 5.5 : 0) + (w === 'high' ? 4 : 0) + (f === 'C' && w === 'high' ? 2.5 : 0) + 1.2 * light + r.normal(0, 2.2);
          rows.plot.push(++k); rows.fertilizer.push(f); rows.water.push(w); rows.light.push(light); rows.yield.push(+y.toFixed(2));
        }
        return new SM.Table({ name: 'Plant trial', source: 'simulated', columns: [
          { name: 'plot', dataType: 'numeric', modelingType: 'nominal', values: rows.plot },
          { name: 'fertilizer', dataType: 'character', values: rows.fertilizer },
          { name: 'water', dataType: 'character', values: rows.water, valueOrder: ['low', 'high'], modelingType: 'ordinal' },
          { name: 'light (h)', dataType: 'numeric', values: rows.light },
          { name: 'yield (g)', dataType: 'numeric', values: rows.yield },
        ] });
      },
    },
    clinical: {
      label: 'Clinical study (200 rows): dose, age, response, survival',
      about: 'Simulated: a yes/no response that rises with dose, and a survival time with censoring that depends on treatment. For Logistic, Contingency, Survival and GLM.',
      make() {
        const r = rng('clinical');
        const n = 200, c = { patient: [], treatment: [], dose: [], age: [], sex: [], response: [], months: [], censored: [], events: [] };
        for (let i = 0; i < n; i++) {
          const trt = r.u() < 0.5 ? 'placebo' : 'drug';
          const dose = trt === 'placebo' ? 0 : r.pick([10, 20, 40, 80]);
          const age = Math.round(r.normal(58, 11));
          const sex = r.u() < 0.46 ? 'F' : 'M';
          const eta = -1.6 + 0.028 * dose + 0.02 * (age - 58);
          const resp = r.u() < 1 / (1 + Math.exp(-eta)) ? 'yes' : 'no';
          const rate = 0.045 * Math.exp((trt === 'drug' ? -0.55 : 0) + 0.025 * (age - 58));
          const t = -Math.log(1 - r.u()) / rate;
          const follow = 12 + 36 * r.u();
          const cens = t > follow;
          const lambda = Math.exp(0.4 + 0.012 * dose - 0.3 * (sex === 'F'));
          let k = 0, p = Math.exp(-lambda), s = p; const u = r.u(); while (u > s && k < 60) { k++; p *= lambda / k; s += p; }
          c.patient.push(`P${String(i + 1).padStart(3, '0')}`); c.treatment.push(trt); c.dose.push(dose); c.age.push(age); c.sex.push(sex);
          c.response.push(resp); c.months.push(+(Math.min(t, follow)).toFixed(1)); c.censored.push(cens ? 1 : 0); c.events.push(k);
        }
        return new SM.Table({ name: 'Clinical study', source: 'simulated', columns: [
          { name: 'patient', dataType: 'character', values: c.patient, role: 'label' },
          { name: 'treatment', dataType: 'character', values: c.treatment, valueOrder: ['placebo', 'drug'] },
          { name: 'dose (mg)', dataType: 'numeric', values: c.dose },
          { name: 'age', dataType: 'numeric', values: c.age },
          { name: 'sex', dataType: 'character', values: c.sex },
          { name: 'response', dataType: 'character', values: c.response, valueOrder: ['no', 'yes'] },
          { name: 'months', dataType: 'numeric', values: c.months },
          { name: 'censored', dataType: 'numeric', modelingType: 'nominal', values: c.censored },
          { name: 'adverse events', dataType: 'numeric', values: c.events },
        ] });
      },
    },
    sales: {
      label: 'Monthly sales (120 months): trend and season',
      about: 'Simulated monthly series with a trend, a yearly season and autocorrelated noise, and a promotion flag. For Time Series and forecasting.',
      make() {
        const r = rng('sales');
        const n = 120, month = [], sales = [], promo = [], temp = [];
        let e = 0;
        for (let i = 0; i < n; i++) {
          const t = Date.UTC(2016, i, 1);
          const season = 12 * Math.sin((2 * Math.PI * (i % 12)) / 12) + 5 * Math.cos((4 * Math.PI * (i % 12)) / 12);
          const p = r.u() < 0.15 ? 1 : 0;
          e = 0.6 * e + r.normal(0, 4);
          month.push(t); promo.push(p);
          temp.push(+(8 + 10 * Math.sin((2 * Math.PI * ((i % 12) - 3)) / 12) + r.normal(0, 1.5)).toFixed(1));
          sales.push(+(100 + 0.6 * i + season + 9 * p + e).toFixed(1));
        }
        return new SM.Table({ name: 'Monthly sales', source: 'simulated', columns: [
          { name: 'month', dataType: 'numeric', format: { kind: 'date' }, values: month },
          { name: 'sales', dataType: 'numeric', values: sales },
          { name: 'promotion', dataType: 'numeric', modelingType: 'nominal', values: promo },
          { name: 'temperature', dataType: 'numeric', values: temp },
        ] });
      },
    },
    process: {
      label: 'Process (25 subgroups × 5): a shift after subgroup 18',
      about: 'Simulated measurements from a process whose mean shifts late on, with specification limits 9.4 and 10.6. For Control Charts and Process Capability.',
      make() {
        const r = rng('process');
        const sub = [], x = [], op = [];
        for (let g = 1; g <= 25; g++) for (let k = 0; k < 5; k++) {
          sub.push(g); op.push(r.pick(['Ann', 'Bo', 'Cy']));
          x.push(+(10 + (g > 18 ? 0.25 : 0) + r.normal(0, 0.14)).toFixed(3));
        }
        return new SM.Table({ name: 'Process', source: 'simulated', columns: [
          { name: 'subgroup', dataType: 'numeric', modelingType: 'ordinal', values: sub },
          { name: 'operator', dataType: 'character', values: op },
          { name: 'diameter (mm)', dataType: 'numeric', values: x, specLimits: { lsl: 9.4, target: 10, usl: 10.6 } },
        ] });
      },
    },
  };

  /* A platform may bring an example table of its own, simulated like these
     (seeded; nothing that is not ours): { label, about, make() -> SM.Table }.
     It appears in File > Examples and on the Home tab. */
  function addExample(key, def) {
    if (!key || !def || typeof def.make !== 'function') throw new Error('an example needs a key and make()');
    EXAMPLES[key] = def;
  }

  function example(key) {
    const ex = EXAMPLES[key];
    if (!ex) throw new Error(`no example ${key}`);
    const t = ex.make();
    t.notes = ex.about;
    return t;
  }

  SM.io = Object.freeze({
    detectDelimiter, parseRows, columnsFromRows, tableFromText, readXlsx, readFile, toCsv, toXlsxBlob, formatDate, parseDate,
    cellText, EXAMPLES, example, addExample, filesTable, globMatcher,
  });
}(typeof self !== 'undefined' ? self : this));
