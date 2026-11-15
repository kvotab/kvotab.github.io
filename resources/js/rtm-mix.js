/*
  WATERS REBUILT FROM REFERENCE WATERS (rtm.html's Batch tab).

  A table of waters, each with a few constituents -- chloride, sodium, calcium, sulphate, carbonate -- and a table
  of reference waters, each with all it has: each water taken as a mixture of the reference waters, its shares
  non-negative and summing to one, fitted to the constituents both tables have; then the reference waters mixed in
  those shares in PHREEQC, each mixture brought to the minerals asked for at the temperature asked for, and the
  water as PHREEQC leaves it written as a table again -- with the columns the Simple Functions read, the shares and
  how far off the fit is -- for the batch to run on.

  The fit: each share of n reference waters at most 8, every subset of them tried free, the least squares of the
  weighted relative misfit with the shares summing to one, the best of those with none below nought (exact: the
  least-squares problem is convex and its solution has some subset of shares free). What is fitted on, and how much
  each counts, is said as "Cl, Na, Ca, SO4, HCO3 0.3": a constituent and its weight, 1 unless given.

  No data of anyone's is built in: the example's waters are made up, round numbers.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.RtmMix = api;
}(typeof self !== 'undefined' ? self : this, () => {
  'use strict';

  /** The most reference waters a fit takes: every subset of them is tried, 2^n - 1. */
  const MOST = 8;
  /** mV a pe at T kelvin: 1000 ln(10) R T / F. */
  const EH_PER_PE = (tk) => (1000 * Math.LN10 * 8.314462618 * tk) / 96485.33212;

  /** An element symbol, from rtm-model.js's atomic weights where loaded. */
  function isElement(sym) {
    const W = (typeof RtmModel !== 'undefined' && RtmModel.ATOMIC_WEIGHTS)
      || (typeof self !== 'undefined' && self.RtmModel && self.RtmModel.ATOMIC_WEIGHTS)
      || (typeof globalThis !== 'undefined' && globalThis.RtmModel && globalThis.RtmModel.ATOMIC_WEIGHTS);
    return W ? !!W[sym] : /^[A-Z][a-z]?$/.test(sym);
  }

  /**
    What a column is of, as PHREEQC names it: an element or one of its valence states -- Ca, S(6), C(+4) -- from its
    name plainly, or from the bracket of "[Ca]tot (m)"; sulphate and bicarbonate, "[SO4-2]tot (m)" and
    "[HCO3-] (m)", as S(6) and C(4). Null for anything else.
  */
  function constituentOf(header) {
    const h = String(header).trim();
    const plain = /^([A-Z][a-z]?)(\([+-]?\d+\))?$/.exec(h);
    if (plain && isElement(plain[1])) return h;
    const br = /^\[([^\]]+)\]/.exec(h);
    if (!br) return null;
    const inner = br[1].trim();
    if (/^SO4(-2|2-)?$/i.test(inner)) return 'S(6)';
    if (/^HCO3-?$/i.test(inner)) return 'C(4)';
    const el = /^([A-Z][a-z]?)(\([+-]?\d+\))?$/.exec(inner);
    return el && isElement(el[1]) ? inner : null;
  }
  /** The element of a label: S of S(6). */
  const elementOf = (label) => label.replace(/\(.*\)$/, '');
  /** The same constituent, however a database writes its valence: C(4) and C(+4). */
  const sameLabel = (a, b) => a.replace('(+', '(') === b.replace('(+', '(');

  /** A number from a cell: a number, or text with a decimal point or comma; null for nothing. */
  function numberOf(v) {
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    const t = String(v === null || v === undefined ? '' : v).trim().replace(/^([-+]?\d+),(\d+)/, '$1.$2');
    if (!t) return null;
    const x = Number(t);
    return Number.isFinite(x) ? x : null;
  }

  /**
    The reference waters from a table: a row each. Its name from a column so called (name, water) or the first whose
    values are not numbers; pH, pe and temp (C, 25 unless given); every column that is a constituent (constituentOf)
    its total in mol/kgw, nothing where empty. -> { waters: [{ name, pH, pe, temp, comps: [[label, value]] }],
    labels, unread: [columns not read], error }
  */
  function readReference(columns, rows) {
    const cols = columns.map(String);
    const low = cols.map((c) => c.trim().toLowerCase());
    const find = (re) => low.findIndex((c) => re.test(c));
    let iName = find(/^(name|water|reference water|reference)$/);
    if (iName < 0) iName = cols.findIndex((c, k) => rows.some((r) => numberOf(r[k]) === null && String(r[k] ?? '').trim() !== ''));
    const iPH = find(/^ph$/);
    const iPe = find(/^pe$/);
    const iT = find(/^(temp|temperature|t)( ?\(?(°c|c|degc)\)?)?$/);
    const labels = [];
    const at = [];
    const unread = [];
    cols.forEach((c, k) => {
      if ([iName, iPH, iPe, iT].includes(k)) return;
      const lb = constituentOf(c);
      if (!lb) { unread.push(c); return; }
      if (labels.includes(lb)) { unread.push(c); return; }
      labels.push(lb);
      at.push(k);
    });
    const waters = rows.filter((r) => r.some((v) => String(v ?? '').trim() !== '')).map((r, n) => ({
      name: (iName >= 0 ? String(r[iName] ?? '').trim() : '') || `water ${n + 1}`,
      pH: iPH >= 0 ? numberOf(r[iPH]) : null,
      pe: iPe >= 0 ? numberOf(r[iPe]) : null,
      temp: iT >= 0 && numberOf(r[iT]) !== null ? numberOf(r[iT]) : 25,
      comps: labels.map((lb, j) => [lb, numberOf(r[at[j]]) || 0]),
    }));
    let error = null;
    if (waters.length < 2) error = 'two reference waters at least, a row each';
    else if (waters.length > MOST) error = `${MOST} reference waters at most: every subset of them is tried`;
    else if (!labels.length) error = 'no column of the reference waters is a constituent: name them as PHREEQC does, Ca, Cl, S(6), C(4)';
    else {
      const noPH = waters.find((w) => w.pH === null);
      if (noPH) error = `the reference water ${noPH.name} has no pH`;
      const twice = waters.find((w, i) => waters.findIndex((x) => x.name === w.name) !== i);
      if (!error && twice) error = `two reference waters are named ${twice.name}`;
      const brace = waters.find((w) => /[{}]/.test(w.name));
      if (!error && brace) error = `a reference water's name may not have { or } in it: ${brace.name}`;
    }
    return { waters, labels, unread, error };
  }

  /** The names a fit may give a constituent by, beside its label: SO4 for S(6), HCO3 for C(4). */
  const ALIASES = { so4: ['S(6)', 'S'], sulphate: ['S(6)', 'S'], sulfate: ['S(6)', 'S'], hco3: ['C(4)', 'C(+4)', 'C'], carbonate: ['C(4)', 'C(+4)', 'C'] };
  /** What a table's columns give of a constituent: the column whose constituentOf is it. */
  function columnFor(columns, label) {
    const sulph = /^S(\(6\)|\(\+6\))?$/.test(label);
    const carb = /^C(\(4\)|\(\+4\))?$/.test(label);
    return columns.find((c) => {
      const lb = constituentOf(c);
      if (!lb) return false;
      if (sameLabel(lb, label)) return true;
      if (sulph) return /^S(\(6\)|\(\+6\))?$/.test(lb);
      if (carb) return /^C(\(4\)|\(\+4\))?$/.test(lb);
      return false;
    }) || null;
  }
  /** The reference waters' label for a name in a fit: itself, or SO4 and HCO3 as their labels. */
  function labelFor(labels, name) {
    const direct = labels.find((lb) => sameLabel(lb, name));
    if (direct) return direct;
    const al = ALIASES[name.toLowerCase()];
    if (al) return labels.find((lb) => al.some((a) => sameLabel(lb, a))) || null;
    return labels.find((lb) => lb === name) || null;
  }

  /** What to fit on unless said: of Cl, Br, Na, K, Ca, Mg, SO4 and HCO3 (0.3), those both tables have. */
  function defaultFit(columns, labels) {
    const terms = [['Cl', 1], ['Br', 1], ['Na', 1], ['K', 1], ['Ca', 1], ['Mg', 1], ['SO4', 1], ['HCO3', 0.3]];
    return terms.filter(([n]) => { const lb = labelFor(labels, n); return lb && columnFor(columns, lb); })
      .map(([n, w]) => (w === 1 ? n : `${n} ${w}`)).join(', ');
  }

  /**
    A fit as said, "Cl, Na, Ca, SO4, HCO3 0.3", against the table's columns and the reference waters' labels.
    -> { terms: [{ name, label, weight, column }], error }
  */
  function readFit(spec, columns, labels) {
    const parts = String(spec || '').split(/[,;]/).map((p) => p.trim()).filter(Boolean);
    if (!parts.length) return { terms: [], error: 'say what to fit the shares on: Cl, Na, Ca, SO4, HCO3 0.3' };
    const terms = [];
    for (const p of parts) {
      const m = /^(\S+)(?:\s+(\S+))?$/.exec(p);
      if (!m) return { terms, error: `"${p}" is not a constituent and its weight, as HCO3 0.3` };
      const weight = m[2] === undefined ? 1 : Number(m[2]);
      if (!(weight > 0)) return { terms, error: `"${p}": the weight is a number above nought` };
      const label = labelFor(labels, m[1]);
      if (!label) return { terms, error: `${m[1]}: the reference waters have no column for it` };
      const column = columnFor(columns, label);
      if (!column) return { terms, error: `${m[1]}: the table has no column for it` };
      if (terms.some((t) => t.label === label)) return { terms, error: `${m[1]} is said twice` };
      terms.push({ name: m[1], label, weight, column });
    }
    return { terms, error: null };
  }

  /**
    One water's shares: min sum_r (w_r (sum_i f_i R_ir / o_r - 1))^2 with f >= 0 and sum f = 1, every subset of the
    reference waters tried free (the equality-constrained least squares on it, by its KKT system), the best of those
    whose shares are all >= 0. Terms the water has nothing of are left out. -> { f, misfit (rms log10 of mixture
    over water on the terms), used } or null where the water has none of any term.
  */
  function sharesOf(R, obs, weights) {
    const n = R.length;
    const rowsUsed = obs.map((o, r) => r).filter((r) => obs[r] > 0 && weights[r] > 0);
    if (!rowsUsed.length) return null;
    const A = rowsUsed.map((r) => R.map((ref) => (weights[r] * ref[r]) / obs[r]));
    const b = rowsUsed.map((r) => weights[r]);
    let best = null;
    for (let mask = 1; mask < (1 << n); mask++) {
      const S = [];
      for (let i = 0; i < n; i++) if (mask & (1 << i)) S.push(i);
      const k = S.length;
      const N = k + 1;
      const M = Array.from({ length: N }, () => new Float64Array(N + 1));
      for (let i = 0; i < k; i++) {
        for (let j = 0; j < k; j++) {
          let s = 0;
          for (let r = 0; r < A.length; r++) s += A[r][S[i]] * A[r][S[j]];
          M[i][j] = 2 * s;
        }
        let s = 0;
        for (let r = 0; r < A.length; r++) s += A[r][S[i]] * b[r];
        M[i][N] = 2 * s;
        M[i][k] = 1;
        M[k][i] = 1;
      }
      M[k][N] = 1;
      let ok = true;
      for (let c = 0; c < N; c++) {
        let p = c;
        for (let r = c + 1; r < N; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
        if (!(Math.abs(M[p][c]) > 1e-300)) { ok = false; break; }
        if (p !== c) { const tmp = M[c]; M[c] = M[p]; M[p] = tmp; }
        for (let r = 0; r < N; r++) {
          if (r === c || M[r][c] === 0) continue;
          const f = M[r][c] / M[c][c];
          for (let j = c; j <= N; j++) M[r][j] -= f * M[c][j];
        }
      }
      if (!ok) continue;
      const fS = S.map((_, i) => M[i][N] / M[i][i]);
      if (fS.some((x) => !(x >= -1e-12))) continue;
      const f = new Array(n).fill(0);
      S.forEach((i, j) => { f[i] = Math.max(0, fS[j]); });
      let r2 = 0;
      for (let r = 0; r < A.length; r++) {
        let s = 0;
        for (let i = 0; i < n; i++) s += A[r][i] * f[i];
        r2 += (s - b[r]) ** 2;
      }
      if (!best || r2 < best.r2 - 1e-15 * Math.max(1, best.r2)) best = { f, r2 };
    }
    if (!best) return null;
    const sum = best.f.reduce((a, x) => a + x, 0);
    const f = best.f.map((x) => x / sum);
    let ss = 0;
    for (const r of rowsUsed) {
      const mix = R.reduce((a, ref, i) => a + f[i] * ref[r], 0);
      ss += mix > 0 ? Math.log10(mix / obs[r]) ** 2 : Infinity;
    }
    return { f, misfit: Math.sqrt(ss / rowsUsed.length), used: rowsUsed.length };
  }

  /** Every row's shares: [{ f, misfit } or null where a row has nothing to fit on]. */
  function fitAll(waters, terms, columns, rows) {
    const R = waters.map((w) => terms.map((t) => { const c = w.comps.find(([lb]) => lb === t.label); return c ? c[1] : 0; }));
    const at = terms.map((t) => columns.indexOf(t.column));
    const weights = terms.map((t) => t.weight);
    return rows.map((row) => sharesOf(R, at.map((k) => numberOf(row[k]) || 0), weights));
  }

  /** The phases to bring each mixture to: "Calcite, Quartz -0.2", a name and its saturation index, 0 unless given. */
  function readPhases(spec) {
    const out = [];
    for (const p of String(spec || '').split(/[,;]/).map((x) => x.trim()).filter(Boolean)) {
      const m = /^(\S+)(?:\s+(\S+))?$/.exec(p);
      const si = m && m[2] !== undefined ? Number(m[2]) : 0;
      if (!m || !Number.isFinite(si)) return { phases: out, error: `"${p}" is not a phase and its saturation index, as Calcite 0` };
      out.push({ name: m[1], si });
    }
    return { phases: out, error: null };
  }

  /** The column a share goes under in the batch's rows. */
  const shareColumn = (name) => `share ${name}`;

  /**
    The batch's input: the reference waters, each as its own SOLUTION; their MIX in the row's shares; the mixture
    at the temperature asked for, brought to the phases; and what the rebuilt table needs of it, in USER_PUNCH 1
    under headings h0, h1, ... (what each is: `punched`).
  */
  function template(waters, labels, { phases = [], temp = null } = {}) {
    const n = waters.length;
    const g = (x) => String(x);
    const lines = [`# The waters rebuilt from ${n} reference waters: their MIX in each row's shares,`,
      `# then ${phases.length ? phases.map((p) => p.name).join(', ') : 'nothing more'}${temp !== null ? ` at ${g(temp)} C` : ''}.`];
    waters.forEach((w, i) => {
      lines.push(`SOLUTION ${i + 1}  ${w.name}`, ` temp ${g(w.temp)}`, ' units mol/kgw', ` pH ${g(w.pH)}`);
      if (w.pe !== null) lines.push(` pe ${g(w.pe)}`);
      for (const [lb, v] of w.comps) if (v > 0) lines.push(` ${lb} ${g(v)}`);
    });
    lines.push('END', 'MIX 1', ...waters.map((w, i) => ` ${i + 1} {${shareColumn(w.name)}}`), `SAVE solution ${n + 1}`, 'END',
      `USE solution ${n + 1}`);
    if (temp !== null) lines.push('REACTION_TEMPERATURE 1', ` ${g(temp)}`);
    if (phases.length) lines.push('EQUILIBRIUM_PHASES 1', ...phases.map((p) => ` ${p.name} ${g(p.si)} 10`));
    // What the table needs: the pH and pe, the ionic strength, the free HCO3- where there is carbon, each element's
    // total and each valence state's the reference waters give, each phase's saturation index.
    const elements = [...new Set(labels.map(elementOf))];
    const states = labels.filter((lb) => lb !== elementOf(lb));
    const punched = [['pH', '-LA("H+")'], ['pe', '-LA("e-")'], ['I', 'MU'], ['TK', 'TK']];
    if (elements.includes('C')) punched.push(['HCO3-', 'MOL("HCO3-")']);
    for (const el of elements) punched.push([`tot ${el}`, `TOT("${el}")`]);
    for (const lb of states) punched.push([`tot ${lb}`, `TOT("${lb}")`]);
    for (const p of phases) punched.push([`SI ${p.name}`, `SI("${p.name}")`]);
    lines.push('SELECTED_OUTPUT 1', ' -reset false', 'USER_PUNCH 1', ` -headings ${punched.map((_, i) => `h${i}`).join(' ')}`,
      ` 10 PUNCH ${punched.map(([, x]) => x).join(', ')}`, 'END');
    return { text: lines.join('\n'), punched: punched.map(([what]) => what), shareColumns: waters.map((w) => shareColumn(w.name)) };
  }

  /** The order the Simple Functions' columns go in, and their names, by constituent. */
  const SF_COLUMNS = [['Cl', '[Cl]tot (m)'], ['Ca', '[Ca]tot (m)'], ['Mg', '[Mg]tot (m)'], ['Na', '[Na]tot (m)'], ['K', '[K]tot (m)'],
    ['Fe', '[Fe]tot (m)'], ['Si', '[Si]tot (m)']];

  /**
    The rebuilt table: the table's own columns that are no constituent nor the water's pH, pe, Eh or ionic strength
    (X, Y, a name...), then the rebuilt water with the Simple Functions' columns first -- pH, Eh (mV), I (m),
    [HCO3-] (m), [SO4-2]tot (m), [Cl]tot (m), [Ca]tot (m) and on -- then every other element's total, each valence
    state's, the pe, the shares, the misfit and each phase's saturation index. A row whose run PHREEQC refused, or
    that had nothing to fit on, keeps its own columns and nothing else.
    run: { head: [h0, ...], rows: [values or null] } in the order of the rows.
  */
  function rebuiltTable(table, waters, labels, fits, tmpl, run, phases) {
    const own = table.columns.map((c, k) => [c, k]).filter(([c]) => !constituentOf(c)
      && !/^(ph|pe|eh|is|i|ionic strength|eh \(mv\)|i \(m\))(\b|$)/i.test(String(c).trim()));
    const elements = [...new Set(labels.map(elementOf))];
    const states = labels.filter((lb) => lb !== elementOf(lb));
    const has = (el) => elements.includes(el);
    const sulphate = states.find((lb) => /^S\(\+?6\)$/.test(lb)) || (has('S') && !states.some((lb) => elementOf(lb) === 'S') ? 'S' : null);
    const cols = [];
    cols.push(['pH', (v) => v.pH], ['Eh (mV)', (v) => v.pe * EH_PER_PE(v.TK)], ['I (m)', (v) => v.I]);
    if (has('C')) cols.push(['[HCO3-] (m)', (v) => v['HCO3-']]);
    if (sulphate) cols.push(['[SO4-2]tot (m)', (v) => v[`tot ${sulphate}`]]);
    for (const [el, name] of SF_COLUMNS) if (has(el)) cols.push([name, (v) => v[`tot ${el}`]]);
    const listed = new Set(['S', 'C', ...SF_COLUMNS.map(([el]) => el)]);
    for (const el of elements.filter((e) => !listed.has(e)).sort()) cols.push([`[${el}]tot (m)`, (v) => v[`tot ${el}`]]);
    if (has('S') && sulphate !== 'S') cols.push(['[S]tot (m)', (v) => v['tot S']]);
    if (has('C')) cols.push(['[C]tot (m)', (v) => v['tot C']]);
    for (const lb of states.filter((s) => s !== sulphate)) cols.push([`[${lb}]tot (m)`, (v) => v[`tot ${lb}`]]);
    cols.push(['pe', (v) => v.pe]);
    const shareCols = waters.map((w, i) => [shareColumn(w.name), i]);
    const columns = [...own.map(([c]) => c), ...cols.map(([c]) => c), ...shareCols.map(([c]) => c), 'misfit (log)',
      ...phases.map((p) => `SI ${p.name}`)];
    const g = (x) => (Number.isFinite(x) ? Number(x.toPrecision(10)) : null);
    const rows = table.rows.map((row, k) => {
      const mine = own.map(([, j]) => row[j]);
      const fit = fits[k];
      const got = run.rows[k];
      if (!fit || !got) return [...mine, ...cols.map(() => null), ...shareCols.map(() => null), null, ...phases.map(() => null)];
      const v = {};
      tmpl.punched.forEach((what, i) => { v[what] = Number(got[run.head.indexOf(`h${i}`)]); });
      return [...mine, ...cols.map(([, f]) => g(f(v))), ...shareCols.map(([, i]) => g(fit.f[i])), g(fit.misfit),
        ...phases.map((p) => g(v[`SI ${p.name}`]))];
    });
    return { columns, rows };
  }

  /*
    THE EXAMPLE: three made-up reference waters, round numbers, nobody's -- a brine, a sea water and a fresh water --
    and twelve waters mixed from them in shares said below, their chloride, sodium, calcium, sulphate, silica and
    carbonate the mixtures' own: a table of a few numbers a water, as such tables often are.
  */
  const EXAMPLE_REFERENCE = [
    'name, pH, pe, temp, Na, K, Ca, Mg, Sr, Cl, Br, S(6), S(-2), C(4), Si, Fe(2)',
    'Brine, 7.5, -4, 15, 0.5, 0.001, 0.3, 0.0005, 0.003, 1.1, 0.004, 0.0002, 0.000001, 0.0001, 0.0001, 0.000005',
    'Sea, 7.9, -3, 15, 0.15, 0.003, 0.004, 0.017, 0.00008, 0.18, 0.0003, 0.009, 0.00001, 0.0015, 0.0001, 0.00001',
    'Fresh, 8.5, -4.5, 15, 0.002, 0.0001, 0.0006, 0.0002, 0.000002, 0.0005, 0.000001, 0.0002, 0.0000001, 0.003, 0.0002, 0.000001',
  ].join('\n');
  const EXAMPLE_SHARES = [[0.02, 0.1, 0.88], [0.05, 0.3, 0.65], [0.1, 0.5, 0.4], [0.01, 0.02, 0.97], [0.2, 0.2, 0.6],
    [0.3, 0.6, 0.1], [0, 0.4, 0.6], [0.15, 0, 0.85], [0.03, 0.75, 0.22], [0.4, 0.1, 0.5], [0.08, 0.15, 0.77], [0.5, 0.45, 0.05]];
  /** The example's table of waters: a water a row, its shares made up and its constituents the mixtures' own. */
  function exampleTable() {
    const ref = readReference(...csvTable(EXAMPLE_REFERENCE));
    const tot = (w, lb) => (w.comps.find(([l]) => l === lb) || [0, 0])[1];
    const cols = [['[Cl]tot (m)', 'Cl'], ['[Na]tot (m)', 'Na'], ['[Ca]tot (m)', 'Ca'], ['[SO4-2]tot (m)', 'S(6)'], ['[Si]tot (m)', 'Si'],
      ['[HCO3-] (m)', 'C(4)']];
    const rows = EXAMPLE_SHARES.map((f, k) => [`water ${k + 1}`,
      ...cols.map(([, lb]) => Number(f.reduce((a, x, i) => a + x * tot(ref.waters[i], lb), 0).toPrecision(8)))]);
    return { columns: ['water', ...cols.map(([c]) => c)], rows };
  }
  /** A small CSV table: its names and its rows, split at commas. */
  function csvTable(text) {
    const lines = String(text).split(/\r?\n/).filter((l) => l.trim());
    const cells = (l) => l.split(',').map((x) => x.trim());
    return [cells(lines[0]), lines.slice(1).map(cells)];
  }

  return { MOST, EH_PER_PE, constituentOf, numberOf, readReference, defaultFit, readFit, sharesOf, fitAll, readPhases, shareColumn,
    template, rebuiltTable, EXAMPLE_REFERENCE, EXAMPLE_SHARES, exampleTable, csvTable, columnFor, labelFor };
}));
