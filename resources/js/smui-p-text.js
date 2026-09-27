/* ==========================================================================
   SMUI.HTML: ANALYZE > TEXT EXPLORER

   JMP's Text Explorer for one or more character columns, with
   scikit-learn's text features (resources/py/smui/text.py):

     Summary Counts           terms, cases (documents), tokens, tokens per
                              case, the portion of cases with a term
     Term and Phrase Lists    the terms and phrases with their counts,
                              sortable; a click selects the rows that hold
                              them, a right click adds a stop word, recodes,
                              adds a phrase or shows the texts
     Word Cloud               the most frequent terms sized by count, in a
                              spiral (Centered) or alphabetically (Ordered);
                              a click selects a word's rows
     Stem Report, Stop Words  the words behind each stem; the stop words,
                              recodes and phrases in use
     Latent Semantic Analysis the truncated SVD of the weighted document term
                              matrix: singular values, the documents' and the
                              terms' coordinates (points linked to the rows)
     Topic Analysis           the SVD rotated by varimax (JMP's), or NMF or
                              LDA: the top terms, the loadings, the documents'
                              topic scores
     Save                     the document term matrix, the singular vectors,
                              the topic scores, the term table

   Every table the report shows comes from its calls and options, so that
   Bootstrap can run it again on resampled rows (ctx.headless); the term
   list's selection and the word cloud are the page's own and skipped there.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, svg, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Text Explorer', id: 'help-p-text' };
  const DOT = '·';

  const STEMMING = [['none', 'No Stemming'], ['combine', 'Stem for Combining'], ['all', 'Stem All Terms']];
  const TOKENIZING = [['regex', 'Regex'], ['basic', 'Basic Words']];
  const WEIGHTINGS = [['binary', 'Binary'], ['ternary', 'Ternary'], ['frequency', 'Frequency'], ['logfreq', 'Log Freq'], ['tfidf', 'TF IDF']];
  const CENTERING = [['uncentered', 'Uncentered'], ['centered', 'Centered'], ['scaled', 'Centered and Scaled']];
  const METHODS = [['varimax', 'Rotated SVD (varimax)'], ['nmf', 'Non-negative Matrix Factorization'], ['lda', 'Latent Dirichlet Allocation']];
  const LAYOUTS = [['centered', 'Centered'], ['ordered', 'Ordered']];
  const COLORINGS = [['uniform', 'Uniform'], ['grays', 'Arbitrary Grays'], ['colors', 'Arbitrary Colors'], ['column', 'By Column…']];
  const labelOf = (list, key) => (list.find((x) => x[0] === key) || [key, key])[1];
  const LSA_DEFAULT = { weighting: 'tfidf', centering: 'centered', minFreq: 4, maxTerms: 1000, k: 100 };
  const TOPIC_DEFAULT = { method: 'varimax', k: 10, weighting: 'tfidf', centering: 'centered', minFreq: 4, maxTerms: 1000 };

  /* The word cloud's colours for text, 4.5:1 or more on the report in each
     theme (checked with the data-viz palette validator; the words are their
     own labels, so no colour carries a meaning of its own). */
  const INK = {
    light: { colors: ['#1c5cab', '#b4501f', '#0f7a55', '#4a3aa7', '#6a6a00', '#b8336a'], grays: ['#352921', '#5a4d42', '#6b5d4f', '#786b5d'], low: '#1f5fa8', mid: '#6b6259', high: '#b23a2e' },
    dark: { colors: ['#6da7ec', '#f08a5d', '#3cc494', '#a99ff0', '#d0b24a', '#ee86ad'], grays: ['#e8ddd0', '#cfc2b3', '#b8a898', '#9f9182'], low: '#7fb0ff', mid: '#b8a898', high: '#ff8a7a' },
  };
  const ink = () => (SM.util.themeColors().dark ? INK.dark : INK.light);

  const wide = (tbl) => el('div', { class: 'sm-tx-scroll' }, tbl);
  const snippet = (s, n = 90) => { const t = String(s ?? '').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
  const scatterType = (n) => (n > 4000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter');

  /* The user's stop words, recodes and phrases are kept as JSON text: a
     project opened again maps the column ids in a report's options, and a
     word that happened to look like one ("c12") must not be taken for it. */
  function listOpt(ctx, key, sc, dflt) {
    const v = ctx.opt(key, null, sc);
    if (v == null || v === '') return dflt;
    try { const x = typeof v === 'string' ? JSON.parse(v) : v; return x == null ? dflt : x; } catch (e) { return dflt; }
  }
  const setList = (ctx, key, sc, v) => ctx.set(key, JSON.stringify(v), sc);

  /* What the backend needs to read a column as the report reads it. */
  function parseArgs(ctx, col) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const num = (k, d) => { const v = o(k, d); return v == null || v === '' || !Number.isFinite(Number(v)) ? d : Number(v); };
    return {
      column: col.name, id_col: ctx.name('id'), language: o('language', 'english'),
      max_words: num('maxWords', 4), max_phrases: num('maxPhrases', 1000), min_chars: num('minChars', 1), max_chars: num('maxChars', 100),
      stemming: o('stemming', 'none'), tokenizing: o('tokenizing', 'regex'),
      regex: o('customRegex', false) ? (String(o('regex', '') || '').trim() || null) : null,
      stop_add: listOpt(ctx, 'stopAdd', sc, []), recodes: listOpt(ctx, 'recodes', sc, {}), phrases: listOpt(ctx, 'phrasesAdd', sc, []),
    };
  }

  /* The page's own state of a column's explorer (the terms chosen in the
     lists), kept per report, By group and column across redraws. A headless
     run (Bootstrap) gets a state of its own and leaves the report's alone. */
  const STATE = new WeakMap();
  function stateOf(ctx, col) {
    if (ctx.headless) return { chosen: new Set(), chosenPhrases: new Set(), headless: true };
    let m = STATE.get(ctx.report);
    if (!m) STATE.set(ctx.report, (m = new Map()));
    const key = `${ctx.path}\u0001${col.id}`;
    if (!m.has(key)) m.set(key, { chosen: new Set(), chosenPhrases: new Set() });
    return m.get(key);
  }
  const peek = (ctx, col) => { const m = STATE.get(ctx.report); return m ? m.get(`${ctx.path}\u0001${col.id}`) || null : null; };
  // Outline and table keys: with several text columns each column's are its own.
  const K = (S, name) => (S.multi ? `${name}:${S.col.id}` : name);

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const cols = ctx.roles('text');
    if (!cols.length) { ctx.container.append(ctx.warn('Choose a text column.')); return; }
    for (const col of cols) {
      const holder = cols.length === 1 ? null : ctx.outline(`Text Explorer for ${col.name}`, { key: `col:${col.id}`, info: 'p:text', menu: () => columnMenu(ctx, col) });
      await explorer(ctx, col, holder);
    }
  }

  async function explorer(ctx, col, holder) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const box = holder ? holder.body : ctx.container;
    if (col.dataType !== 'character') { box.append(ctx.warn(`${col.name} is numeric: Text Explorer reads character columns (right click the column to change its data type).`)); return; }
    const args = parseArgs(ctx, col);
    const res = await ctx.call('text.explore', args);
    if (res.error) { box.append(ctx.warn(`${col.name}: ${res.error}`)); return; }
    const S = stateOf(ctx, col);
    Object.assign(S, { res, args, col, multi: ctx.roles('text').length > 1 });
    S.index = new Map(res.terms.map((t, i) => [t.term, i]));
    S.pindex = new Map(res.phrases.map((p, i) => [p.phrase, i]));
    S.chosen = new Set([...S.chosen].filter((t) => S.index.has(t)));
    S.chosenPhrases = new Set([...S.chosenPhrases].filter((p) => S.pindex.has(p)));
    S.termTable = S.phraseTable = null;
    S.words = [];
    const parent = holder || undefined;
    if (!res.terms.length) box.append(ctx.warn(`${col.name} has no terms in these rows: every text is empty, or holds stop words only.`));
    let codeShown = false;
    const code = () => { if (codeShown) return null; codeShown = true; return ctx.code(res.code); };
    if (o('summary', true)) summaryOutline(ctx, S, parent, code);
    if (o('lists', true)) listsOutline(ctx, S, parent, code);
    if (o('cloud', false)) cloudOutline(ctx, S, parent);
    if (o('stemReport', false) && args.stemming !== 'none') stemOutline(ctx, S, parent);
    if (o('stopList', false)) stopOutline(ctx, S, parent);
    if (!codeShown && !ctx.headless) box.append(code());
    const lsa = o('lsa', null);
    if (lsa && res.terms.length) await lsaOutline(ctx, S, parent, { ...LSA_DEFAULT, ...lsa });
    const tp = o('topics', null);
    if (tp && res.terms.length) await topicOutline(ctx, S, parent, { ...TOPIC_DEFAULT, ...tp });
  }

  /* ---- Summary Counts ------------------------------------------------------------------------ */
  function summaryOutline(ctx, S, parent, code) {
    const { res } = S;
    const s = res.summary;
    const ob = ctx.outline('Summary Counts', { parent, key: K(S, 'summary'), info: 'p:text:summary' });
    ob.add(wide(ctx.rt({
      columns: [{ key: 'terms', label: 'Number of Terms', fmt: 'int' }, { key: 'cases', label: 'Number of Cases', fmt: 'int' }, { key: 'tokens', label: 'Total Tokens', fmt: 'int' },
        { key: 'tpc', label: 'Tokens per Case' }, { key: 'nonempty', label: 'Number of Non-empty Cases', fmt: 'int', hidden: true }, { key: 'pne', label: 'Portion Non-empty' }],
      rows: [{ terms: s.terms, cases: s.cases, tokens: s.tokens, tpc: s.tokens_per_case, nonempty: s.nonempty, pne: s.portion_nonempty }],
    }, { key: K(S, 'summary'), sortable: false })));
    const bits = [];
    if (res.id) bits.push(`A case is a document: the rows with the same ${res.id}.`);
    bits.push(...(res.notes || []));
    if (bits.length) ob.add(ctx.note(bits.join(' ')));
    ob.add(code());
  }

  /* ---- Term and Phrase Lists --------------------------------------------------------------------- */
  function listsOutline(ctx, S, parent, code) {
    const { res } = S;
    const ob = ctx.outline('Term and Phrase Lists', { parent, key: K(S, 'lists'), info: 'p:text:lists', menu: () => listsMenu(ctx, S) });
    const terms = ctx.rt({
      columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'cases', label: 'Cases', fmt: 'int', hidden: true, title: 'the documents that hold the term' }],
      rows: res.terms,
    }, { caption: 'Term List', key: K(S, 'terms'), name: 'Term List', maxRows: 1000, onRow: (r, ev) => pick(ctx, S, 'term', r.term, ev), cellClass: (r) => (S.chosen.has(r.term) ? 'sm-tx-chosen' : '') });
    const phrases = ctx.rt({
      columns: [{ key: 'phrase', label: 'Phrase', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'n', label: 'N', fmt: 'int', title: 'the words in the phrase' }],
      rows: res.phrases,
    }, { caption: 'Phrase List', key: K(S, 'phrases'), name: 'Phrase List', maxRows: 1000, onRow: (r, ev) => pick(ctx, S, 'phrase', r.phrase, ev), cellClass: (r) => (S.chosenPhrases.has(r.phrase) ? 'sm-tx-chosen' : '') });
    S.termTable = terms;
    S.phraseTable = phrases;
    if (!ctx.headless) { listContext(ctx, S, 'term', terms); listContext(ctx, S, 'phrase', phrases); }
    ob.add(ctx.row(el('div', { class: 'sm-tx-list' }, terms), el('div', { class: 'sm-tx-list' }, phrases)));
    const lines = [`${fmt(res.terms.length)} terms and ${fmt(res.phrases.length)} phrases${res.phrases.length >= S.args.max_phrases && S.args.max_phrases > 0 ? ` (Maximum Number of Phrases: ${fmt(S.args.max_phrases)})` : ''}.`,
      'Click a term or phrase to select the rows that hold it (shift adds, ctrl/⌘ toggles); right click for Show Text, Add Stop Word, Recode and Add Phrase.'];
    if (res.terms.length > 1000 || res.phrases.length > 1000) lines.push('The lists show the first 1000; sorting sorts them all, and Make into Data Table (right click on a heading) takes them all.');
    if (S.args.stemming !== 'none') lines.push(`A term ending in ${DOT} is a stem: the words that share it (Stem Report, in Display Options).`);
    ob.add(ctx.note(lines.join(' ')), code());
  }

  function listsMenu(ctx, S) {
    const terms = [...S.chosen], phrases = [...S.chosenPhrases];
    return [
      { label: 'Select Rows', disabled: !terms.length && !phrases.length, action: () => ctx.table.select(rowsFor(S)) },
      { label: 'Show Text…', disabled: !terms.length && !phrases.length, action: () => showText(ctx, S, terms, phrases) },
      { separator: true },
      { label: 'Add Stop Word', disabled: !terms.length, action: () => addStop(ctx, S, terms) },
      { label: 'Recode…', disabled: !terms.length, action: () => recodeDialog(ctx, S, terms) },
      { label: 'Add Phrase', disabled: !phrases.length, action: () => addPhrases(ctx, S, phrases) },
      { separator: true },
      { label: 'Clear Selection', disabled: !terms.length && !phrases.length, action: () => { S.chosen.clear(); S.chosenPhrases.clear(); markChosen(S); ctx.table.select([]); } },
    ];
  }

  /* The rows that hold the chosen terms and phrases. */
  function rowsFor(S, terms = S.chosen, phrases = S.chosenPhrases) {
    const set = new Set();
    for (const t of terms) { const i = S.index.get(t); if (i != null) for (const r of S.res.term_rows[i]) set.add(r); }
    for (const p of phrases) { const i = S.pindex.get(p); if (i != null) for (const r of S.res.phrase_rows[i]) set.add(r); }
    return [...set].sort((a, b) => a - b);
  }

  /* A click in a list or on a word: choose it (shift adds, ctrl/⌘ toggles)
     and select the rows that hold the chosen terms and phrases. */
  function pick(ctx, S, kind, value, ev) {
    const set = kind === 'term' ? S.chosen : S.chosenPhrases;
    const other = kind === 'term' ? S.chosenPhrases : S.chosen;
    if (ev && (ev.metaKey || ev.ctrlKey)) { if (set.has(value)) set.delete(value); else set.add(value); }
    else if (ev && ev.shiftKey) set.add(value);
    else { set.clear(); other.clear(); set.add(value); }
    markChosen(S);
    if (ctx.table) ctx.table.select(rowsFor(S));
  }

  /* Mark the chosen terms in the lists and the word cloud, in place. */
  function markChosen(S) {
    const mark = (tbl, set) => {
      if (!tbl || !tbl.tBodies[0]) return;
      for (const tr of tbl.tBodies[0].rows) {
        if (tr.cells.length < 2) continue;
        const on = set.has(tr.cells[0].textContent);
        for (const c of tr.cells) c.classList.toggle('sm-tx-chosen', on);
      }
    };
    mark(S.termTable, S.chosen);
    mark(S.phraseTable, S.chosenPhrases);
    for (const w of S.words || []) w.el.classList.toggle('is-chosen', S.chosen.has(w.term));
  }

  /* Right click on a term or phrase: its own menu (the heading keeps the
     table's: Columns, Sort, Copy, Make into Data Table). */
  function listContext(ctx, S, kind, tbl) {
    tbl.tBodies[0].addEventListener('contextmenu', (ev) => {
      const tr = ev.target.closest('tr');
      if (!tr || tr.cells.length < 2) return;
      ev.preventDefault();
      ev.stopPropagation();
      const value = tr.cells[0].textContent;
      const set = kind === 'term' ? S.chosen : S.chosenPhrases;
      if (!set.has(value)) pick(ctx, S, kind, value, null);
      const items = kind === 'term' ? [...S.chosen] : [...S.chosenPhrases];
      const head = items.length === 1 ? items[0] : `${items.length} ${kind === 'term' ? 'terms' : 'phrases'}`;
      SM.ui.menu([
        { head },
        { label: 'Select Rows', action: () => ctx.table.select(kind === 'term' ? rowsFor(S, items, []) : rowsFor(S, [], items)) },
        { label: 'Show Text…', action: () => (kind === 'term' ? showText(ctx, S, items, []) : showText(ctx, S, [], items)) },
        { separator: true },
        ...(kind === 'term'
          ? [{ label: 'Add Stop Word', action: () => addStop(ctx, S, items) }, { label: 'Recode…', action: () => recodeDialog(ctx, S, items) }]
          : [{ label: 'Add Phrase', action: () => addPhrases(ctx, S, items) }]),
        { separator: true },
        { label: 'Copy Table', action: () => SM.report.copyText(SM.report.rtText({ columns: tbl._rt.columns, rows: tbl._rt.rows })) },
        { label: 'Make into Data Table', disabled: !SM.app, action: () => SM.app.addTable(SM.report.tableFromRT({ columns: tbl._rt.columns, rows: tbl._rt.rows }, `${S.col.name} ${kind === 'term' ? 'Term List' : 'Phrase List'}`)) },
      ], { x: ev.clientX, y: ev.clientY });
    });
  }

  function addStop(ctx, S, terms) {
    const sc = S.col.id;
    setList(ctx, 'stopAdd', sc, [...new Set([...listOpt(ctx, 'stopAdd', sc, []), ...terms])]);
    SM.ui.toast(`${terms.length === 1 ? `"${terms[0]}" is now a stop word` : `${terms.length} terms are now stop words`} (Term Options ▸ Manage Stop Words)`);
  }

  function addPhrases(ctx, S, phrases) {
    const sc = S.col.id;
    setList(ctx, 'phrasesAdd', sc, [...new Set([...listOpt(ctx, 'phrasesAdd', sc, []), ...phrases])]);
  }

  async function recodeDialog(ctx, S, terms) {
    const sc = S.col.id;
    const v = await SM.ui.form({
      title: 'Recode', info: 'p:text:manage',
      lead: terms.length === 1 ? `The term "${terms[0]}" is counted as the term you give (an existing one, to combine them). An empty value drops it.` : `The ${terms.length} terms (${terms.slice(0, 6).join(', ')}${terms.length > 6 ? ', …' : ''}) are counted as the one term you give.`,
      fields: [{ key: 'to', label: 'New value', type: 'text', value: terms[0] }],
    });
    if (!v) return;
    const cur = listOpt(ctx, 'recodes', sc, {});
    const to = String(v.to || '').trim().toLowerCase().replace(/\s+/g, ' ');
    const next = { ...cur };
    for (const t of terms) if (t !== to) next[t] = to;
    setList(ctx, 'recodes', sc, next);
  }

  /* Show Text: the texts of the rows that hold the terms, their words marked. */
  function showText(ctx, S, terms, phrases) {
    const col = S.col;
    const rows = rowsFor(S, terms, phrases);
    const forms = [];
    for (const t of terms) forms.push(...(S.res.forms[t] ? S.res.forms[t].map((f) => f[0]) : [t]));
    forms.push(...phrases);
    const re = highlighter(forms);
    const shown = rows.slice(0, 500);
    const what = [...terms, ...phrases];
    const list = el('ol', { class: 'sm-tx-texts' }, ...shown.map((r) => el('li', null, el('span', { class: 'sm-tx-rownum', text: `Row ${r + 1}` }), el('span', { class: 'sm-tx-text' }, ...marked(col.values[r], re)))));
    SM.ui.dialog({
      title: `Show Text: ${what.length === 1 ? what[0] : `${what.length} terms`}`, className: 'sm-tx-dialog', info: 'p:text:lists',
      body: el('div', null, el('p', { class: 'sm-dialog-lead', text: `${fmt(rows.length)} row${rows.length === 1 ? '' : 's'} of ${col.name} hold${rows.length === 1 ? 's' : ''} ${what.length === 1 ? `"${what[0]}"` : 'one of them'}${rows.length > shown.length ? `; the first ${shown.length} are shown` : ''}.` }), list),
      buttons: [{ label: 'Select These Rows', action: () => { ctx.table.select(rows); } }, { label: 'Close', primary: true }],
    });
  }

  /* A pattern that finds the words of a term in the raw text: any case,
     whole words, a phrase's words with anything but letters between. */
  function highlighter(forms) {
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const parts = [...new Set(forms.filter(Boolean))].sort((a, b) => b.length - a.length).map((f) => f.split(/\s+/).map(esc).join('[\\W_]+'));
    if (!parts.length) return null;
    try { return new RegExp(`(?<![\\p{L}\\p{N}])(?:${parts.join('|')})(?![\\p{L}\\p{N}])`, 'giu'); } catch (e) { return null; }
  }

  function marked(text, re) {
    const s = String(text ?? '');
    if (!re) return [s];
    const out = [];
    let last = 0;
    re.lastIndex = 0;
    for (let m = re.exec(s); m; m = re.exec(s)) {
      if (!m[0]) { re.lastIndex++; continue; }
      if (m.index > last) out.push(s.slice(last, m.index));
      out.push(el('mark', { text: m[0] }));
      last = m.index + m[0].length;
    }
    if (last < s.length) out.push(s.slice(last));
    return out;
  }

  /* ---- Word Cloud ------------------------------------------------------------------------------------------ */
  let measurer;
  function textWidth(text, px) {
    if (measurer === undefined) { try { measurer = document.createElement('canvas').getContext('2d'); } catch (e) { measurer = null; } }
    if (!measurer) return text.length * px * 0.62;
    measurer.font = `${px}px verdana, sans-serif`;
    return measurer.measureText(text).width;
  }

  /* Boxes for the words, largest first. Centered: along an elliptical
     spiral from the middle, each word in the first place where it overlaps
     none before it; Ordered: alphabetically, in lines. */
  function cloudLayout(words, mode, width) {
    const pad = 3;
    for (const w of words) { w.w = textWidth(w.term, w.size) + 2 * pad; w.h = w.size * 1.18 + pad; }
    if (mode === 'ordered') {
      const lines = [];
      let line = [], lw = 0;
      for (const w of words.slice().sort((a, b) => SM.table.collator.compare(a.term, b.term))) {
        if (line.length && lw + w.w > width) { lines.push({ line, lw }); line = []; lw = 0; }
        line.push(w);
        lw += w.w;
      }
      if (line.length) lines.push({ line, lw });
      let y = 0;
      for (const { line: ln, lw: lwid } of lines) {
        const h = Math.max(...ln.map((w) => w.h));
        let x = (width - lwid) / 2;
        for (const w of ln) { w.cx = x + w.w / 2; w.cy = y + h / 2; x += w.w; }
        y += h;
      }
      return { x0: 0, y0: 0, w: width, h: Math.max(y, 10) };
    }
    // the boxes placed so far, in a grid of cells for the overlap test
    const placed = [], grid = new Map(), cell = 40;
    const overlaps = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
    const cells = (b, fn) => {
      for (let gx = Math.floor(b.x0 / cell); gx <= Math.floor(b.x1 / cell); gx++) for (let gy = Math.floor(b.y0 / cell); gy <= Math.floor(b.y1 / cell); gy++) { const out = fn(`${gx},${gy}`); if (out) return out; }
      return null;
    };
    const hit = (a) => cells(a, (k) => { const list = grid.get(k); if (list) for (const b of list) if (overlaps(a, b)) return b; return null; });
    const ratio = Math.max(0.9, Math.min(1.8, width / 380));   // wide on a screen, about square on a phone
    let last = null;
    for (const w of words) {
      let box = null;
      for (let t = 0, n = 0; n < 60000; n++) {
        const r = 1.6 * t;
        const cx = r * Math.cos(t) * ratio, cy = r * Math.sin(t);
        t += Math.min(0.25, 4 / (1 + r));                     // about 4 px along the spiral
        const b = { x0: cx - w.w / 2, x1: cx + w.w / 2, y0: cy - w.h / 2, y1: cy + w.h / 2 };
        if (last && overlaps(b, last)) continue;
        const h = hit(b);
        if (!h) { box = b; break; }
        last = h;
      }
      if (!box) { const y = placed.length ? Math.max(...placed.map((p) => p.y1)) : 0; box = { x0: -w.w / 2, x1: w.w / 2, y0: y, y1: y + w.h }; }
      placed.push(box);
      cells(box, (k) => { if (!grid.has(k)) grid.set(k, []); grid.get(k).push(box); return null; });
      w.cx = (box.x0 + box.x1) / 2;
      w.cy = (box.y0 + box.y1) / 2;
    }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const b of placed) { x0 = Math.min(x0, b.x0); y0 = Math.min(y0, b.y0); x1 = Math.max(x1, b.x1); y1 = Math.max(y1, b.y1); }
    return placed.length ? { x0: x0 - 4, y0: y0 - 4, w: x1 - x0 + 8, h: y1 - y0 + 8 } : { x0: 0, y0: 0, w: width, h: 10 };
  }

  const hexRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const mixHex = (a, b, t) => { const x = hexRgb(a), y = hexRgb(b); return `rgb(${x.map((v, i) => Math.round(v + t * (y[i] - v))).join(', ')})`; };
  function diverging(t, P) {   // t in [-1, 1]
    return t < 0 ? mixHex(P.mid, P.low, Math.min(1, -t)) : mixHex(P.mid, P.high, Math.min(1, t));
  }

  function cloudOutline(ctx, S, parent) {
    const sc = S.col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const ob = ctx.outline('Word Cloud', { parent, key: K(S, 'cloud'), info: 'p:text:cloud', menu: () => cloudMenu(ctx, S) });
    if (ctx.headless) return;
    const { res } = S;
    const n = Math.max(1, Math.min(500, Math.round(Number(o('cloudN', 100)) || 100)));
    const layout = o('cloudLayout', 'centered');
    const coloring = o('cloudColor', 'uniform');
    const terms = res.terms.slice(0, n);
    if (!terms.length) { ob.add(ctx.note('No terms.')); return; }
    const room = Math.max(280, Math.min(760, ((ctx.report.body && ctx.report.body.clientWidth) || 800) - 70));
    const maxF = Math.max(22, Math.min(48, room / 15)), minF = 10.5;
    const c0 = terms[terms.length - 1].count, c1 = terms[0].count;
    const words = terms.map((t, i) => ({ term: t.term, count: t.count, i, size: c1 > c0 ? minF + (maxF - minF) * Math.sqrt((t.count - c0) / (c1 - c0)) : (minF + maxF) / 2 }));
    const box = cloudLayout(words, layout, room);
    const P = ink();
    // By Column: each word coloured by the mean of a numeric column over the rows that hold it
    let byCol = null, means = null, center = 0, dev = 0;
    if (coloring === 'column') {
      byCol = ctx.col(o('cloudBy', null));
      if (byCol && byCol.isNumeric) {
        const v = byCol.values;
        let s = 0, k = 0;
        for (const r of ctx.rows) if (Number.isFinite(v[r])) { s += v[r]; k++; }
        center = k ? s / k : 0;
        means = words.map((w) => { let a = 0, m = 0; for (const r of res.term_rows[w.i]) if (Number.isFinite(v[r])) { a += v[r]; m++; } return m ? a / m : NaN; });
        for (const m of means) if (Number.isFinite(m)) dev = Math.max(dev, Math.abs(m - center));
      } else byCol = null;
    }
    const cloud = svg('svg', { class: `sm-tx-cloud${coloring === 'uniform' || (coloring === 'column' && !byCol) ? ' is-uniform' : ''}`, viewBox: `${box.x0.toFixed(1)} ${box.y0.toFixed(1)} ${box.w.toFixed(1)} ${box.h.toFixed(1)}`, role: 'group', 'aria-label': `Word cloud of the ${words.length} most frequent terms of ${S.col.name}` });
    cloud.style.maxWidth = `${Math.ceil(box.w)}px`;
    S.words = [];
    words.forEach((w, k) => {
      let fill = null;
      if (coloring === 'colors') fill = P.colors[w.i % P.colors.length];
      else if (coloring === 'grays') fill = P.grays[w.i % P.grays.length];
      else if (byCol) fill = Number.isFinite(means[k]) && dev > 0 ? diverging((means[k] - center) / dev, P) : P.mid;
      const tip = byCol ? `${w.term}: ${fmt(w.count)}; mean ${byCol.name} ${Number.isFinite(means[k]) ? fmt(means[k], { sig: 4 }) : '.'}` : `${w.term}: ${fmt(w.count)}`;
      const t = svg('text', { x: w.cx.toFixed(1), y: w.cy.toFixed(1), 'font-size': w.size.toFixed(1), fill, class: 'sm-tx-word', 'text-anchor': 'middle', 'dominant-baseline': 'central' }, svg('title', null, tip), w.term);
      if (S.chosen.has(w.term)) t.classList.add('is-chosen');
      t.addEventListener('click', (ev) => pick(ctx, S, 'term', w.term, ev));
      cloud.append(t);
      S.words.push({ term: w.term, el: t });
    });
    ob.add(el('div', { class: 'sm-tx-cloudbox' }, cloud));
    if (byCol) {
      const lo = center - dev, hi = center + dev;
      ob.add(el('div', { class: 'sm-tx-legend' },
        el('span', { text: `Mean ${byCol.name}` }), el('span', { text: fmt(lo, { sig: 4 }) }),
        el('span', { class: 'sm-tx-ramp', style: { background: `linear-gradient(90deg, ${P.low}, ${P.mid}, ${P.high})` } }),
        el('span', { text: fmt(hi, { sig: 4 }) })));
    }
    ob.add(ctx.note(`The ${words.length} most frequent terms, each sized by its count (font size ∝ √count); ${layout === 'ordered' ? 'alphabetically' : 'the most frequent in the middle'}.${byCol ? ` Coloured by the mean of ${byCol.name} over the rows that hold each term, around its mean over all the rows (${fmt(center, { sig: 4 })}).` : ''} Click a word to select its rows.`));
  }

  function cloudMenu(ctx, S) {
    const sc = S.col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    return [
      { label: 'Layout', submenu: () => LAYOUTS.map(([v, l]) => ({ label: l, checked: o('cloudLayout', 'centered') === v, action: () => ctx.set('cloudLayout', v, sc) })) },
      { label: 'Coloring', submenu: () => COLORINGS.map(([v, l]) => ({ label: l, checked: o('cloudColor', 'uniform') === v, action: () => (v === 'column' ? cloudByDialog(ctx, S) : ctx.set('cloudColor', v, sc)) })) },
      { label: 'Number of Terms…', action: async () => { const v = await SM.ui.form({ title: 'Word Cloud: Number of Terms', fields: [{ key: 'n', label: 'The most frequent terms to show', type: 'number', value: o('cloudN', 100) }], validate: (x) => (Number.isInteger(x.n) && x.n >= 1 && x.n <= 500 ? null : 'A whole number from 1 to 500') }); if (v) ctx.set('cloudN', v.n, sc); } },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('cloud', false, sc) },
    ];
  }

  async function cloudByDialog(ctx, S) {
    const sc = S.col.id;
    const nums = ctx.table.columns.filter((c) => c.isNumeric);
    if (!nums.length) { SM.ui.toast('The table has no numeric column to colour by', { error: true }); return; }
    const cur = ctx.opt('cloudBy', null, sc);
    const v = await SM.ui.form({ title: 'Word Cloud: Color by Column', info: 'p:text:cloud', lead: 'Each word takes the mean of a numeric column over the rows that hold it: blue below the column\'s mean, red above.',
      fields: [{ key: 'col', label: 'Column', type: 'select', value: cur && nums.some((c) => c.id === cur) ? cur : nums[0].id, choices: nums.map((c) => [c.id, c.name]) }] });
    if (!v) return;
    ctx.set('cloudBy', v.col, sc, { rerun: false });
    ctx.set('cloudColor', 'column', sc);
  }

  /* ---- Stem Report and the term options in use ------------------------------------------------------------------ */
  function stemOutline(ctx, S, parent) {
    const ob = ctx.outline('Stem Report', { parent, key: K(S, 'stems'), info: 'p:text:stems', menu: () => [{ label: 'Remove', action: () => ctx.set('stemReport', false, S.col.id) }] });
    const rows = S.res.stems.map((s) => ({ stem: s.stem, count: s.count, n: s.forms.length, forms: s.forms.map(([w, c]) => `${w} (${c})`).join(', ') }));
    if (!rows.length) { ob.add(ctx.note('No word has a stem it shares with another.')); return; }
    ob.add(el('div', { class: 'sm-tx-list' }, ctx.rt({ columns: [{ key: 'stem', label: 'Stem', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'n', label: 'Terms', fmt: 'int' }, { key: 'forms', label: 'Words (count)', fmt: 'text' }], rows }, { key: K(S, 'stems'), maxRows: 1000 })),
      ctx.note(S.args.stemming === 'combine' ? 'Stem for Combining: only the words that share their Porter stem with another word are stemmed.' : 'Stem All Terms: every word of three or more letters a to z is stemmed, alone or not.'));
  }

  function stopOutline(ctx, S, parent) {
    const { res } = S;
    const sc = S.col.id;
    const ob = ctx.outline('Stop Words, Recodes and Phrases', { parent, key: K(S, 'stops'), info: 'p:text:manage', menu: () => manageItems(ctx, S.col).concat([{ separator: true }, { label: 'Remove', action: () => ctx.set('stopList', false, sc) }]) });
    const rec = Object.entries(res.recodes || {});
    const parts = [];
    if (res.user_stop.length) parts.push(ctx.rt({ columns: [{ key: 'w', label: 'Added Stop Word', fmt: 'text' }], rows: res.user_stop.map((w) => ({ w })) }, { key: 'userstop', sortable: false }));
    if (rec.length) parts.push(ctx.rt({ columns: [{ key: 'a', label: 'Old Value', fmt: 'text' }, { key: 'b', label: 'New Value', fmt: 'text' }], rows: rec.map(([a, b]) => ({ a, b })) }, { key: 'recodes', sortable: false }));
    if (res.added_phrases.length) parts.push(ctx.rt({ columns: [{ key: 'p', label: 'Added Phrase', fmt: 'text' }], rows: res.added_phrases.map((p) => ({ p })) }, { key: 'addedphrases', sortable: false }));
    if (parts.length) ob.add(ctx.row(...parts));
    else ob.add(ctx.note('No stop words, recodes or phrases added: right click a term or phrase, or Term Options (red triangle) to manage them.'));
    const d = el('details', { class: 'sm-tx-stoplist' }, el('summary', { text: `The ${res.stop_words.length} English stop words (scikit-learn's ENGLISH_STOP_WORDS)` }), el('p', { text: res.stop_words.join(', ') }));
    ob.add(d);
  }

  /* ---- Latent Semantic Analysis ------------------------------------------------------------------------------------ */
  const lsaArgs = (ctx, S, spec) => ({ ...S.args, weighting: spec.weighting, centering: spec.centering, min_freq: spec.minFreq, max_terms: spec.maxTerms, k: spec.k, seed: SM.predict.seed(ctx) });

  async function lsaOutline(ctx, S, parent, spec) {
    const sc = S.col.id;
    const ob = ctx.outline('Latent Semantic Analysis (SVD)', { parent, key: K(S, 'lsa'), info: 'p:text:lsa', menu: () => [
      { label: 'Specifications…', action: () => lsaDialog(ctx, S.col) },
      { label: 'Save Document Singular Vectors…', action: () => saveVectors(ctx, S, 'svd', spec) },
      { label: 'Save Term Singular Vectors', action: () => saveTermVectors(ctx, S, spec) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('lsa', null, sc) },
    ] });
    const r = await ctx.call('text.lsa', { ...lsaArgs(ctx, S, spec), show: 2 });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const sv = ctx.outline('Singular Values', { parent: ob, key: K(S, 'singular') });
    const rows = r.singular;
    const top = rows.slice(0, 30);
    const bars = ctx.plot([{ type: 'bar', orientation: 'h', y: top.map((x) => x.number), x: top.map((x) => x.percent), marker: { color: SM.report.BAR }, hovertemplate: '%{y}: %{x:.2f}%<extra></extra>' }],
      { margin: { l: 36, r: 12, t: 6, b: 34 }, xaxis: { title: { text: 'Percent' }, rangemode: 'tozero' }, yaxis: { autorange: 'reversed', dtick: top.length > 15 ? 5 : 1 }, bargap: 0.2 },
      { width: 280, height: Math.max(140, 13 * top.length + 50), title: 'Singular values, percent', select: false });
    sv.add(ctx.row(el('div', { class: 'sm-tx-list' }, ctx.rt({ columns: [{ key: 'number', label: 'Number', fmt: 'int' }, { key: 'value', label: 'Singular Value' }, { key: 'percent', label: 'Percent', digits: 4 }, { key: 'cum', label: 'Cum Percent', digits: 4 }], rows }, { key: K(S, 'singular'), sortable: false })), bars),
      ctx.note(`${fmt(r.n_docs)} documents by ${fmt(r.n_terms)} terms (those seen ${r.min_freq} or more times, at most ${fmt(r.max_terms)}), ${labelOf(WEIGHTINGS, r.weighting)} weighting, ${labelOf(CENTERING, r.centering).toLowerCase()}; ${r.k} singular vectors by scikit-learn's ${r.solver}. Percent: each singular value's share of the matrix's sum of squares (s² over the total).`));
    if (r.k >= 2 && !ctx.headless) svdPlots(ctx, S, ob, r);
    else if (r.k < 2) ob.add(ctx.note('One singular vector: no plots.'));
    ob.add(ctx.code(r.code));
  }

  function svdPlots(ctx, S, ob, r) {
    const po = ctx.outline('SVD Plots', { parent: ob, key: K(S, 'svdplots') });
    const labels = labelsFor(ctx, S, r);
    const docTrace = { type: scatterType(r.doc_rows.length), mode: 'markers', x: r.docs[0], y: r.docs[1], marker: { size: r.doc_rows.length > 2000 ? 4 : 6 }, hovertext: labels, hovertemplate: '%{hovertext}<extra></extra>', name: 'Documents' };
    docTrace.rows = S.res.id ? r.doc_rows : r.doc_rows.map((d) => d[0]);
    const tv = r.term_vectors;
    const lab = labelled(r.terms, tv[0], tv[1], { width: 330, height: 290, most: 14 });
    const c = SM.util.themeColors();
    const termTrace = {
      type: 'scatter', mode: 'markers+text', x: tv[0], y: tv[1], rows: r.terms.map((t) => { const i = S.index.get(t); return i == null ? [] : S.res.term_rows[i]; }),
      text: r.terms.map((t, j) => (lab.has(j) ? T(t) : '')), textposition: 'top center', textfont: { size: 10.5, color: c.text }, cliponaxis: false,
      hovertext: r.terms.map((t, j) => `${T(t)}: ${fmt(r.term_counts[j])}`), hovertemplate: '%{hovertext}<br>(%{x:.4g}, %{y:.4g})<extra></extra>', marker: { size: 6, color: SM.report.BASE }, name: 'Terms',
    };
    const ax = (t) => ({ title: { text: t }, zeroline: true });
    po.add(ctx.row(
      ctx.plot([docTrace], { xaxis: ax('Doc Vec1'), yaxis: ax('Doc Vec2'), margin: { l: 56, r: 10, t: 24, b: 44 }, title: { text: 'Documents', font: { size: 12 } } }, { width: 400, height: 360, title: `Document singular vectors of ${S.col.name}` }),
      ctx.plot([termTrace], { xaxis: ax('Term Vec1'), yaxis: ax('Term Vec2'), margin: { l: 56, r: 16, t: 24, b: 44 }, title: { text: 'Terms', font: { size: 12 } } }, { width: 400, height: 360, title: `Term singular vectors of ${S.col.name}` })),
    ctx.note('Each point on the left is a document (U S: its weighted terms projected on the first two singular vectors), on the right a term (V S), as latent semantic analysis compares them; the terms furthest out are named. Documents near each other use the same terms; a term point stands for the rows that hold it. Click or drag to select rows.'));
  }

  /* The terms to name on a plot: the furthest out first, each only where its
     label (above the point, as wide as its text) meets no label named
     before it, on the plot's approximate pixel scale. */
  function labelled(terms, xs, ys, { width, height, most }) {
    const span = (v) => { let lo = Infinity, hi = -Infinity; for (const x of v) { if (x < lo) lo = x; if (x > hi) hi = x; } const pad = 0.05 * (hi - lo || 1); return [lo - pad, hi + pad]; };
    const [x0, x1] = span(xs), [y0, y1] = span(ys);
    const px = (x) => ((x - x0) / (x1 - x0)) * width, py = (y) => height - ((y - y0) / (y1 - y0)) * height;
    const order = terms.map((_, j) => j).sort((a, b) => (xs[b] ** 2 + ys[b] ** 2) - (xs[a] ** 2 + ys[a] ** 2));
    const boxes = [], out = new Set();
    for (const j of order) {
      if (out.size >= most) break;
      const w = 6.4 * terms[j].length + 4, cx = px(xs[j]), top = py(ys[j]) - 20;
      const b = { x0: cx - w / 2, x1: cx + w / 2, y0: top, y1: top + 14 };
      if (boxes.some((o) => b.x0 < o.x1 && o.x0 < b.x1 && b.y0 < o.y1 && o.y0 < b.y1)) continue;
      boxes.push(b);
      out.add(j);
    }
    return out;
  }

  /* Hover text for the documents: the start of the first row's text. */
  function labelsFor(ctx, S, r) {
    const v = S.col.values;
    return r.doc_rows.map((rows, d) => {
      const head = S.res.id ? `${S.res.id} ${r.doc_labels ? r.doc_labels[d] : d + 1} (${rows.length} row${rows.length === 1 ? '' : 's'})` : `row ${rows[0] + 1}`;
      return `${T(head)}: ${T(snippet(v[rows[0]]))}`;
    });
  }

  async function lsaDialog(ctx, col) {
    const sc = col.id;
    const cur = { ...LSA_DEFAULT, ...(ctx.opt('lsa', null, sc) || {}) };
    const v = await SM.ui.form({
      title: 'Latent Semantic Analysis, SVD', info: 'p:text:lsa',
      lead: 'The document term matrix is weighted, centered as chosen, and reduced by a truncated singular value decomposition.',
      fields: [
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq },
        { key: 'weighting', label: 'Weighting', type: 'select', value: cur.weighting, choices: WEIGHTINGS },
        { key: 'k', label: 'Number of Singular Vectors', type: 'number', value: cur.k },
        { key: 'centering', label: 'Centering and Scaling', type: 'select', value: cur.centering, choices: CENTERING },
      ],
      validate: specError,
    });
    if (v) ctx.set('lsa', { maxTerms: v.maxTerms, minFreq: v.minFreq, weighting: v.weighting, k: v.k, centering: v.centering }, sc);
  }

  function specError(x) {
    for (const [k, label, hi] of [['maxTerms', 'Maximum Number of Terms', 100000], ['minFreq', 'Minimum Term Frequency', 1e9], ['k', 'Number of Singular Vectors', 100000], ['n', 'Number of Topics', 1000]]) {
      if (!(k in x)) continue;
      if (!(Number.isInteger(x[k]) && x[k] >= 1 && x[k] <= hi)) return `${label}: a whole number from 1 to ${fmt(hi)}`;
    }
    return null;
  }

  /* ---- Topic Analysis ------------------------------------------------------------------------------------------------- */
  const topicArgs = (ctx, S, spec) => ({ ...S.args, method: spec.method, n_topics: spec.k, weighting: spec.weighting, centering: spec.centering, min_freq: spec.minFreq, max_terms: spec.maxTerms, seed: SM.predict.seed(ctx) });

  async function topicOutline(ctx, S, parent, spec) {
    const sc = S.col.id;
    const title = spec.method === 'varimax' ? 'Topic Analysis, Rotated SVD' : `Topic Analysis, ${labelOf(METHODS, spec.method)}`;
    const ob = ctx.outline(title, { parent, key: K(S, 'topics'), info: 'p:text:topics', menu: () => [
      { label: 'Specifications…', action: () => topicDialog(ctx, S.col) },
      { label: 'Save Topic Scores', action: () => saveVectors(ctx, S, 'topics', spec) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('topics', null, sc) },
    ] });
    // LDA takes a while: its iterations, as the engine reports them
    let off = null;
    if (spec.method === 'lda' && !ctx.headless) {
      const note = el('p', { class: 'sm-ob-note', role: 'status', text: 'Latent Dirichlet allocation: fitting…' });
      ob.add(note);
      const h = SM.engine.on('progress', (p) => { if (p.what === 'lda') { note.textContent = `Latent Dirichlet allocation: iteration ${p.done} of ${p.total}…`; ctx.report.noteEl.textContent = note.textContent; } });
      off = () => { h(); note.remove(); };
    }
    let r;
    try { r = await ctx.call('text.topics', { ...topicArgs(ctx, S, spec), top: 10, scores: 2 }); } finally { if (off) off(); }
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const varimax = r.method === 'varimax';
    const tl = ctx.outline('Top Loadings by Topic', { parent: ob, key: K(S, 'toploadings') });
    const grid = el('div', { class: 'sm-tx-topics' }, ...r.top.map((tp, t) => ctx.rt({
      columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'loading', label: varimax ? 'Loading' : r.method === 'lda' ? 'Probability' : 'Weight', digits: 4 }], rows: tp,
    }, { caption: `Topic ${t + 1}`, key: K(S, `topic-${t + 1}`), sortable: false, onRow: (row, ev) => pick(ctx, S, 'term', row.term, ev) })));
    tl.add(grid, ctx.note(varimax
      ? 'The terms with the largest loadings on each topic, after the varimax rotation of the first singular vectors: a topic is a group of terms that go together. Click a term to select its rows.'
      : `The terms with the largest ${r.method === 'lda' ? 'probabilities in each topic' : 'weights in each topic'}. Click a term to select its rows.`));
    const vo = ctx.outline(varimax ? 'Variance Explained' : 'Topic Sizes', { parent: ob, key: K(S, 'topicvar') });
    vo.add(wide(ctx.rt({ columns: [{ key: 'topic', label: 'Topic', fmt: 'int' }, { key: 'variance', label: varimax ? 'Variance' : 'Size' }, { key: 'percent', label: 'Percent', digits: 4 }, { key: 'cum', label: 'Cum Percent', digits: 4 }], rows: r.variance }, { key: K(S, 'topicvar'), sortable: false })),
      ctx.note(varimax ? 'The sum of squares of each rotated topic\'s share of the matrix: the rotation spreads the first singular vectors\' total over the topics, largest first. Percent is of the whole matrix\'s sum of squares.'
        : r.method === 'nmf' ? 'Each topic\'s size: the sum of its document weights times the sum of its term weights; largest first.' : 'Each topic\'s size: the sum of its shares over the documents; largest first.'));
    const lo = ctx.outline('Topic Loadings', { parent: ob, key: K(S, 'topicloadings'), closed: true });
    const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, ...r.loadings.map((_, t) => ({ key: `t${t}`, label: `Topic ${t + 1}`, digits: 4 }))];
    const lrows = r.terms.map((term, j) => ({ term, ...Object.fromEntries(r.loadings.map((l, t) => [`t${t}`, l[j]])) }));
    lo.add(el('div', { class: 'sm-tx-list sm-tx-wide' }, ctx.rt({ columns: cols, rows: lrows }, { key: K(S, 'topicloadings'), maxRows: 1000 })));
    if (r.k >= 2 && !ctx.headless) {
      const so = ctx.outline('Topic Scores', { parent: ob, key: K(S, 'topicscores') });
      const tr = { type: scatterType(r.doc_rows.length), mode: 'markers', x: r.scores[0], y: r.scores[1], marker: { size: r.doc_rows.length > 2000 ? 4 : 6 }, hovertext: labelsFor(ctx, S, r), hovertemplate: '%{hovertext}<extra></extra>', name: 'Documents' };
      tr.rows = S.res.id ? r.doc_rows : r.doc_rows.map((d) => d[0]);
      const tops = (t) => r.top[t].slice(0, 3).map((x) => x.term).join(', ');
      so.add(ctx.row(ctx.plot([tr], { xaxis: { title: { text: `Topic 1 (${T(tops(0))})` } }, yaxis: { title: { text: `Topic 2 (${T(tops(1))})` } }, margin: { l: 60, r: 10, t: 8, b: 48 } }, { width: 440, height: 360, title: `Topic scores of ${S.col.name}` })),
        ctx.note(varimax ? 'Each document\'s scores on the first two topics (standardized: mean 0 and variance 1 when centered). Click or drag to select rows.' : `Each document's ${r.method === 'lda' ? 'share of' : 'weight on'} the first two topics. Click or drag to select rows.`));
    }
    ob.add(ctx.note(`${labelOf(METHODS, r.method)}: ${r.k} topics from ${fmt(r.n_docs)} documents and ${fmt(r.terms.length)} terms (seen ${r.min_freq} or more times), ${labelOf(WEIGHTINGS, r.weighting)} weighting${varimax ? `, ${labelOf(CENTERING, r.centering).toLowerCase()}` : ''}${r.method === 'lda' ? ' (LDA takes the counts)' : ''}.${varimax ? '' : ` Seed ${r.seed}.`}`), ctx.code(r.code));
  }

  async function topicDialog(ctx, col) {
    const sc = col.id;
    const cur = { ...TOPIC_DEFAULT, ...(ctx.opt('topics', null, sc) || {}) };
    const v = await SM.ui.form({
      title: 'Topic Analysis, Rotated SVD', info: 'p:text:topics',
      lead: 'JMP\'s topics are the first singular vectors rotated by varimax; scikit-learn\'s non-negative matrix factorization and latent Dirichlet allocation are offered too.',
      fields: [
        { key: 'n', label: 'Number of Topics', type: 'number', value: cur.k },
        { key: 'method', label: 'Method', type: 'select', value: cur.method, choices: METHODS },
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq },
        { key: 'weighting', label: 'Weighting (LDA takes the counts)', type: 'select', value: cur.weighting, choices: WEIGHTINGS },
        { key: 'centering', label: 'Centering and Scaling (rotated SVD)', type: 'select', value: cur.centering, choices: CENTERING },
      ],
      validate: specError,
    });
    if (v) ctx.set('topics', { k: v.n, method: v.method, maxTerms: v.maxTerms, minFreq: v.minFreq, weighting: v.weighting, centering: v.centering }, sc);
  }

  /* ---- Save ------------------------------------------------------------------------------------------------------------- */
  const fromNote = (ctx, what) => `${what}, from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;

  async function saveVectors(ctx, S, kind, spec) {
    let count = kind === 'svd' ? Math.min(spec.k, 10) : spec.k;
    if (kind === 'svd') {
      const v = await SM.ui.form({ title: 'Save Document Singular Vectors', info: 'p:text:lsa', fields: [{ key: 'n', label: 'Number of singular vectors to save', type: 'number', value: count }], validate: (x) => (Number.isInteger(x.n) && x.n >= 1 && x.n <= 1000 ? null : 'A whole number from 1 to 1000') });
      if (!v) return;
      count = v.n;
    }
    try {
      const base = kind === 'svd' ? lsaArgs(ctx, S, spec) : topicArgs(ctx, S, spec);
      const r = await ctx.call('text.vectors', { ...base, kind, count, n_topics: spec.k, k: spec.k });
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      r.values.forEach((vals, c) => ctx.saveColumn(kind === 'svd' ? `Doc Vec${c + 1}` : `Topic Score ${c + 1}`, { rows: r.rows, values: vals },
        { notes: fromNote(ctx, kind === 'svd' ? `document singular vector ${c + 1} (U S) of ${S.col.name}, ${labelOf(WEIGHTINGS, spec.weighting)}, ${labelOf(CENTERING, spec.centering).toLowerCase()}` : `score on topic ${c + 1} of ${S.col.name}, ${labelOf(METHODS, spec.method)}`) }));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function saveTermVectors(ctx, S, spec) {
    try {
      const r = await ctx.call('text.lsa', { ...lsaArgs(ctx, S, spec), show: Math.min(spec.k, 10) });
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      const t = new SM.Table({
        name: SM.app.uniqueTableName(`${S.col.name} term vectors`), source: `saved from ${ctx.report.title}`,
        notes: `The terms' singular vectors (V S) of ${S.col.name}: ${labelOf(WEIGHTINGS, r.weighting)} weighting, ${labelOf(CENTERING, r.centering).toLowerCase()}, terms seen ${r.min_freq} or more times.`,
        columns: [{ name: 'Term', dataType: 'character', values: r.terms }, { name: 'Count', dataType: 'numeric', values: r.term_counts },
          ...r.term_vectors.map((v, c) => ({ name: `Term Vec${c + 1}`, dataType: 'numeric', values: v }))],
      });
      SM.app.addTable(t);
      SM.ui.toast(`Made the table ${t.name}`);
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function saveDtm(ctx, col) {
    const S = peek(ctx, col);
    const chosen = S ? [...S.chosen] : [];
    const v = await SM.ui.form({
      title: 'Save Document Term Matrix', info: 'p:text:dtm',
      lead: 'A column for each term: its weighted count in each row\'s document.',
      fields: [
        { key: 'which', label: 'Terms', type: 'select', value: chosen.length ? 'chosen' : 'top', choices: [...(chosen.length ? [['chosen', `The ${chosen.length} terms chosen in the Term List`]] : []), ['top', 'The most frequent terms']] },
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: 100 },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: 1 },
        { key: 'weighting', label: 'Weighting', type: 'select', value: 'binary', choices: WEIGHTINGS },
      ],
      validate: specError,
    });
    if (!v) return;
    try {
      const args = S ? S.args : parseArgs(ctx, col);
      const r = await ctx.call('text.dtm', { ...args, weighting: v.weighting, min_freq: v.minFreq, max_terms: v.maxTerms, terms: v.which === 'chosen' ? chosen : null });
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      r.terms.forEach((term, c) => ctx.saveColumn(term, { rows: r.rows, values: r.values[c] }, { notes: fromNote(ctx, `${labelOf(WEIGHTINGS, r.weighting)} document term matrix of ${col.name}: the term "${term}"`) }));
      if (r.terms.length > 1) SM.ui.toast(`Saved ${r.terms.length} columns of the document term matrix to ${ctx.table.name}`);
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  function saveTermTable(ctx, col) {
    const S = peek(ctx, col);
    if (!S || !S.res) { SM.ui.toast('The report is not drawn yet', { error: true }); return; }
    const t = new SM.Table({
      name: SM.app.uniqueTableName(`${col.name} terms`), source: `saved from ${ctx.report.title}`,
      notes: `The Term List of ${col.name}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: each term, its count and the cases (documents) that hold it.`,
      columns: [{ name: 'Term', dataType: 'character', values: S.res.terms.map((x) => x.term) }, { name: 'Count', dataType: 'numeric', values: S.res.terms.map((x) => x.count) },
        { name: 'Cases', dataType: 'numeric', values: S.res.terms.map((x) => x.cases) }],
    });
    SM.app.addTable(t);
    SM.ui.toast(`Made the table ${t.name}`);
  }

  /* ---- Term Options: the lists the user keeps ---------------------------------------------------------------------- */
  function manageItems(ctx, col) {
    return [
      { label: 'Manage Stop Words…', action: () => manageDialog(ctx, col, 'stopAdd') },
      { label: 'Manage Recodes…', action: () => manageDialog(ctx, col, 'recodes') },
      { label: 'Manage Phrases…', action: () => manageDialog(ctx, col, 'phrasesAdd') },
    ];
  }

  async function manageDialog(ctx, col, key) {
    const sc = col.id;
    const cfg = {
      stopAdd: { title: 'Manage Stop Words', lead: 'Your stop words, one per line: they are left out of the terms and no phrase begins or ends with one. scikit-learn\'s 318 English stop words are always left out.', value: listOpt(ctx, 'stopAdd', sc, []).join('\n') },
      recodes: { title: 'Manage Recodes', lead: 'One recode per line: old value -> new value. The old term is counted as the new one (an existing term, to combine them); nothing after the arrow drops the term.', value: Object.entries(listOpt(ctx, 'recodes', sc, {})).map(([a, b]) => `${a} -> ${b}`).join('\n') },
      phrasesAdd: { title: 'Manage Phrases', lead: 'Your phrases, one per line (two or more words): each is counted as one term where its words follow each other, and its words lose those occurrences.', value: listOpt(ctx, 'phrasesAdd', sc, []).join('\n') },
    }[key];
    const v = await SM.ui.form({ title: `${cfg.title}: ${col.name}`, info: 'p:text:manage', lead: cfg.lead, fields: [{ key: 'text', label: cfg.title.replace('Manage ', ''), type: 'textarea', value: cfg.value }] });
    if (!v) return;
    const lines = String(v.text || '').split(/\r?\n/).map((s) => s.trim().toLowerCase().replace(/\s+/g, ' ')).filter(Boolean);
    if (key === 'recodes') {
      const out = {};
      for (const ln of lines) {
        const m = /^(.*?)\s*(?:->|→|=>|=)\s*(.*)$/.exec(ln);
        if (m && m[1]) out[m[1]] = m[2];
      }
      setList(ctx, 'recodes', sc, out);
    } else setList(ctx, key, sc, [...new Set(lines)]);
  }

  /* ======================================================================
     THE RED TRIANGLE OF A COLUMN'S EXPLORER
     ====================================================================== */
  function columnMenu(ctx, col) {
    const sc = col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    return [
      { label: 'Term Options', submenu: () => [
        ...manageItems(ctx, col),
        { separator: true },
        { label: 'Stemming', submenu: () => STEMMING.map(([v, l]) => ({ label: l, checked: o('stemming', 'none') === v, action: () => ctx.set('stemming', v, sc) })) },
      ] },
      { label: 'Display Options', submenu: () => [
        ctx.check('Summary Counts Table', 'summary', sc, true),
        ctx.check('Term and Phrase Lists', 'lists', sc, true),
        ctx.check('Show Word Cloud', 'cloud', sc, false),
        ctx.check('Show Stem Report', 'stemReport', sc, false, { disabled: o('stemming', 'none') === 'none' }),
        ctx.check('Show Stop Words, Recodes and Phrases', 'stopList', sc, false),
      ] },
      { separator: true },
      { label: 'Latent Semantic Analysis, SVD…', checked: !!o('lsa', null), action: () => lsaDialog(ctx, col) },
      { label: 'Topic Analysis, Rotated SVD…', checked: !!o('topics', null), action: () => topicDialog(ctx, col) },
      { separator: true },
      { label: 'Save Document Term Matrix…', action: () => saveDtm(ctx, col) },
      { label: 'Save Term Table', action: () => saveTermTable(ctx, col) },
    ];
  }

  /* ======================================================================
     THE LAUNCH DIALOG'S OWN PART: Customize Regex
     ====================================================================== */
  function launchExtra(api, spec) {
    const o = (spec && spec.options) || {};
    const chk = el('input', { type: 'checkbox' });
    chk.checked = !!o.customRegex;
    const pat = el('input', { type: 'text', class: 'sm-tx-regex', spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Regular expression', placeholder: "a Python regular expression, e.g. [a-z]+(?:'[a-z]+)?" });
    pat.value = o.regex || '';
    const row = el('div', { class: 'sm-tx-regexrow' }, pat, el('p', { class: 'sm-tx-hint', text: 'Each match is a token (lowercase). For the Regex tokenizer; Python\'s re syntax.' }));
    const sync = () => { row.hidden = !chk.checked; };
    chk.addEventListener('change', sync);
    sync();
    const box = el('div', { class: 'sm-tx-launch' },
      el('label', { class: 'sm-tx-check' }, chk, el('span', { text: 'Customize Regex' }), typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:text:regex') : null), row);
    return {
      el: box,
      read: () => ({ options: { customRegex: chk.checked, regex: pat.value.trim() } }),
      recall: (saved) => {
        const so = (saved && saved.options) || {};
        if (so.customRegex != null) chk.checked = !!so.customRegex;
        if (so.regex != null) pat.value = so.regex;
        sync();
      },
    };
  }

  function validate(spec, table) {
    for (const id of (spec.roles && spec.roles.text) || []) {
      const c = table.col(id);
      if (c && c.dataType !== 'character') return `Text Columns takes character columns; ${c.name} is numeric`;
    }
    const idc = ((spec.roles && spec.roles.id) || [])[0];
    if (idc && ((spec.roles.text || []).includes(idc))) return 'The ID column cannot be a text column too';
    const o = spec.options || {};
    const whole = (v, lo, hi) => v == null || (Number.isInteger(v) && v >= lo && v <= hi);
    if (!whole(o.maxWords, 1, 12)) return 'Maximum Words per Phrase: a whole number from 1 to 12';
    if (!whole(o.maxPhrases, 0, 100000)) return 'Maximum Number of Phrases: a whole number from 0 to 100 000';
    if (!whole(o.minChars, 1, 1000)) return 'Minimum Characters per Word: a whole number from 1 to 1000';
    if (!whole(o.maxChars, 1, 100000)) return 'Maximum Characters per Word: a whole number from 1 to 100 000';
    if (o.minChars != null && o.maxChars != null && o.maxChars < o.minChars) return 'Maximum Characters per Word is less than the minimum';
    if (o.customRegex && !o.regex) return 'Customize Regex: give a regular expression, or untick it';
    return null;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:text': {
      kicker: 'Analyze', title: 'Text Explorer',
      lead: 'The words of a column of text: each text is split into tokens, the tokens that are not stop words become terms (stemmed and recoded as you choose), and the terms are counted, listed, drawn as a word cloud and reduced by a singular value decomposition into latent dimensions and topics. The counting is scikit-learn\'s CountVectorizer; its English stop words; the SVD TruncatedSVD or PCA; the stemmer is Porter\'s (1980) algorithm, written here.',
      sections: [
        { heading: 'Roles', choices: [['Text Columns', 'One or more character columns; each gets an analysis of its own.'], ['ID', 'Optional: the rows that share an ID are one document (a case), their texts together.'], ['By', 'A separate analysis for each level.']] },
        { heading: 'Options', choices: [
          ['Language', 'English: the stop words and the stemmer are English.'],
          ['Maximum Words per Phrase', 'The longest phrase in the Phrase List (4).'],
          ['Maximum Number of Phrases', 'How many phrases the Phrase List keeps, the most frequent (1000).'],
          ['Minimum and Maximum Characters per Word', 'Shorter and longer tokens are left out (1 and 100).'],
          ['Stemming', 'No Stemming; Stem for Combining (the words that share a Porter stem with another word become one term, marked with a dot: return·); Stem All Terms (every word).'],
          ['Tokenizing', 'Regex (built-in patterns: URLs, e-mail addresses, numbers such as 3.5 or 25%, words with inner apostrophes and hyphens such as don\'t and well-known, a possessive \'s dropped) or Basic Words (runs of letters and digits). Customize Regex: your own pattern.'],
        ] },
        { heading: 'Differences from JMP', text: 'JMP\'s stop word list and its built-in regular expressions are its own; here the stop words are scikit-learn\'s ENGLISH_STOP_WORDS and the patterns are the ones above. The Word Cloud starts hidden, as in JMP (Display Options).' },
      ],
      more: MORE,
    },
    'p:text:regex': {
      kicker: 'Text Explorer', title: 'Customize Regex',
      lead: 'Your own regular expression (Python\'s re syntax) instead of the built-in patterns: every match in the lowercase text is a token. For example [a-z]+ takes letters only, and \\S+ everything between spaces. JMP opens a Regex Editor instead; the pattern here is typed in the launch dialog.',
      more: MORE,
    },
    'p:text:summary': {
      kicker: 'Text Explorer', title: 'Summary Counts',
      lead: 'Number of Terms: the distinct terms. Number of Cases: the documents (rows, or IDs), empty ones too. Total Tokens: the terms counted every time they occur. Tokens per Case: Total Tokens over Number of Cases. Portion Non-empty: the share of cases with at least one term (right click, Columns, shows their number).',
      more: MORE,
    },
    'p:text:lists': {
      kicker: 'Text Explorer', title: 'Term and Phrase Lists',
      lead: 'Every term with its count (the number of times it occurs; the Cases column, from the right-click Columns menu, counts the documents that hold it), and the phrases: runs of two to Maximum Words per Phrase tokens that occur at least twice and neither begin nor end with a stop word. Most frequent first; click a heading to sort.',
      sections: [
        { heading: 'Selecting', text: 'A click on a term or phrase selects the rows that hold it; shift adds, ctrl/⌘ toggles. The chosen terms are what Show Text and Save Document Term Matrix take.' },
        { heading: 'Right click', choices: [['Show Text', 'The texts of the rows, with the words marked (every word of a stem).'], ['Add Stop Word', 'Leaves the term out from now on.'], ['Recode', 'Counts the term as another (to combine spellings).'], ['Add Phrase', 'Counts a phrase as one term; its words lose those occurrences.']] },
      ],
      more: MORE,
    },
    'p:text:cloud': {
      kicker: 'Text Explorer', title: 'Word Cloud',
      lead: 'The most frequent terms, each sized by its count (the font size grows with the square root of the count, so that a word\'s area follows its count). Centered puts the largest in the middle and each next word on a spiral where it overlaps none; Ordered sets them alphabetically in lines. Click a word to select its rows.',
      sections: [{ heading: 'Coloring', choices: [['Uniform', 'The text colour.'], ['Arbitrary Grays, Arbitrary Colors', 'Colours that mean nothing, to tell neighbouring words apart.'], ['By Column', 'The mean of a numeric column (a rating) over the rows that hold each word: blue below the column\'s mean, red above.']] }],
      more: MORE,
    },
    'p:text:stems': {
      kicker: 'Text Explorer', title: 'Stem Report',
      lead: 'Each stemmed term and the words it stands for, with their counts. The stems are Porter\'s (1980) algorithm as published: five steps of suffix rules, each applied when the stem left is long enough (its measure m); a word of one or two letters, or with characters other than a to z, is not stemmed.',
      more: MORE,
    },
    'p:text:manage': {
      kicker: 'Text Explorer', title: 'Stop Words, Recodes and Phrases',
      lead: 'The lists you add to, kept with the report (and its project): stop words to leave out, recodes that count one term as another, and phrases counted as one term. scikit-learn\'s 318 English stop words are always left out; JMP\'s own list differs.',
      more: MORE,
    },
    'p:text:lsa': {
      kicker: 'Text Explorer', title: 'Latent Semantic Analysis',
      lead: 'The document term matrix (a row per document, a column per term seen Minimum Term Frequency times or more, the Maximum Number of Terms most frequent) is weighted and reduced by a truncated singular value decomposition, X ≈ U S Vᵀ: documents that use the same terms lie together, and so do terms used in the same documents.',
      sections: [
        { heading: 'Weighting (as JMP documents it)', choices: [['Binary', '1 when the term is in the document, else 0.'], ['Ternary', '2 when it is there more than once, 1 once, 0 not.'], ['Frequency', 'Its count.'], ['Log Freq', 'log10(1 + count).'], ['TF IDF', 'count × ln(documents / documents with the term) (the default; JMP\'s documentation writes log, taken here as the natural log).']] },
        { heading: 'Centering and Scaling', choices: [['Uncentered', 'scikit-learn\'s TruncatedSVD of the weighted matrix (arpack).'], ['Centered', 'Each term\'s mean taken away: scikit-learn\'s PCA, the SVD of the centered matrix computed without making the sparse matrix dense (the default here).'], ['Centered and Scaled', 'Each term also divided by its standard deviation.']] },
        { heading: 'What is shown', text: 'The singular values with each one\'s share of the matrix\'s sum of squares; the documents\' coordinates U S and the terms\' V S on the first two vectors (as Deerwester et al. 1990 compare them), signed so that each vector\'s largest term coordinate is positive. Save Document Singular Vectors saves U S; Save Term Singular Vectors makes a table of V S.' },
        { heading: 'Defaults', text: 'TF IDF, Centered, terms seen 4 or more times, at most 1000, 100 singular vectors (cut to the matrix): chosen here; JMP\'s own defaults may differ.' },
      ],
      more: MORE,
    },
    'p:text:topics': {
      kicker: 'Text Explorer', title: 'Topic Analysis',
      lead: 'Topics as JMP makes them: the first k term coordinates of the SVD (V S) rotated by varimax (Kaiser 1958, with Kaiser\'s normalization, R\'s algorithm), so that each topic has a few terms with large loadings. The loadings are V S R/√(n − 1) (with centering, the covariances of the terms with the topics); the scores √(n − 1) U R, so that scores times loadings give the SVD\'s rank-k fit.',
      sections: [
        { heading: 'Other methods (scikit-learn)', choices: [['Non-negative Matrix Factorization', 'NMF: the weighted matrix as documents × topics times topics × terms, all non-negative (init nndsvda).'], ['Latent Dirichlet Allocation', 'LDA: a probability model of the counts; each topic a distribution over the terms, each document a mix of topics.']] },
        { heading: 'Seeds', text: 'NMF and LDA start from the report\'s random seed, kept with the report, so a redraw, a project and the Python code give the same topics.' },
      ],
      more: MORE,
    },
    'p:text:dtm': {
      kicker: 'Text Explorer', title: 'Save Document Term Matrix',
      lead: 'A new column for each term (the terms chosen in the Term List, or the most frequent), named by the term: its weighted count in each row\'s document (every row of an ID gets its document\'s value). Binary gives 0/1 indicator columns for modeling.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'text', label: 'Text Explorer', menu: 'Analyze', order: 40, info: 'p:text', topics: TOPICS,
    about: 'The words of a column of text, as JMP\'s Text Explorer counts them: tokenizing by built-in patterns, basic words or your own regular expression; scikit-learn\'s English stop words; Porter\'s stemmer (for combining or for all terms); Summary Counts, the Term and Phrase Lists (linked to the rows), a word cloud, stop words, recodes and phrases of your own, Show Text; latent semantic analysis (the truncated SVD of the document term matrix with JMP\'s weightings, documents and terms linked to the rows), topic analysis by varimax-rotated SVD, NMF or LDA, and the document term matrix, singular vectors and topic scores saved as columns.',
    uses: ['sklearn.feature_extraction.text (CountVectorizer, ENGLISH_STOP_WORDS)', 'sklearn.decomposition (TruncatedSVD, PCA, NMF, LatentDirichletAllocation)', 'scipy.sparse', 'Porter\'s stemmer and the varimax rotation, written here'],
    launch: {
      lead: 'Choose one or more character columns. Each text is split into words; the words that are not stop words are counted as terms.',
      roles: [
        { key: 'text', label: 'Text Columns', min: 1, types: ['nominal', 'ordinal'], hint: 'required: character columns', info: 'p:text' },
        { key: 'id', label: 'ID', max: 1, hint: 'optional: the rows of an ID are one document' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      options: [
        { key: 'language', label: 'Language', type: 'select', value: 'english', choices: [['english', 'English']] },
        { key: 'maxWords', label: 'Maximum Words per Phrase', type: 'number', value: 4 },
        { key: 'maxPhrases', label: 'Maximum Number of Phrases', type: 'number', value: 1000 },
        { key: 'minChars', label: 'Minimum Characters per Word', type: 'number', value: 1 },
        { key: 'maxChars', label: 'Maximum Characters per Word', type: 'number', value: 100 },
        { key: 'stemming', label: 'Stemming', type: 'select', value: 'none', choices: STEMMING },
        { key: 'tokenizing', label: 'Tokenizing', type: 'select', value: 'regex', choices: TOKENIZING },
      ],
      extra: launchExtra,
      validate,
    },
    title: (spec, table) => {
      const names = ((spec.roles && spec.roles.text) || []).map((id) => (table && table.col(id) ? table.col(id).name : null)).filter(Boolean);
      return names.length === 1 ? `Text Explorer for ${names[0]}` : 'Text Explorer';
    },
    triangle: (ctx) => { const cols = ctx.roles('text'); return cols.length === 1 ? columnMenu(ctx, cols[0]) : []; },
    render,
  });

  /* ======================================================================
     THE EXAMPLE: simulated comments, with their themes in the notes
     ====================================================================== */
  const THEMES = {
    delivery: {
      good: ['Delivery was {fast|quick|super fast} and the parcel arrived {the next day|on time|two days early}', '{Fast|Quick} delivery, {well packed|tracking was easy to follow}',
        'The courier was {friendly|polite} and delivered {on time|early}', 'Arrived {the next day|on time|a day early}, {great|good} delivery'],
      bad: ['Delivery was {late|very late|slow} and the parcel arrived {a week late|three days late|after two weeks}', '{Still waiting|Waiting} for my delivery, the tracking {has not updated|says delivered}',
        'The courier {never came|left the parcel in the rain|lost my package}', 'Late delivery {again|twice in a row}'],
    },
    quality: {
      good: ['{Great|Excellent|Good} quality, {sturdy|solid|well made}', 'The {jacket|lamp|chair|kettle} {fits|works} {perfectly|well} and feels {sturdy|solid}', '{Really|Very} happy with the quality of the {jacket|lamp|chair|kettle}'],
      bad: ['The {lamp|chair|kettle|jacket} arrived {damaged|broken|cracked}', '{Poor|Bad} quality, it {broke|cracked|stopped working} after {a week|two days|a month}',
        'I returned the {lamp|chair|kettle|jacket} and I am still waiting for a refund', '{Damaged|Broken} item, I had to return it'],
    },
    service: {
      good: ['Customer service was {very helpful|friendly|quick to help}', 'The support agent {solved|resolved|fixed} my problem {quickly|in minutes}', '{Helpful|Friendly} staff on the phone'],
      bad: ['Customer service was {rude|unhelpful|useless}', 'I waited {an hour|forty minutes|ages} on hold', 'Nobody answered my {emails|calls}, {terrible|poor} customer service', 'The agent hung up on me'],
    },
    price: {
      good: ['{Great|Good|Fair} price and {good|great} value for money', '{Cheap|Cheaper than elsewhere} and {good|decent} value', 'The discount made it {worth it|a bargain}'],
      bad: ['{Too expensive|Overpriced|Expensive} for what it is', 'Prices went up {again|twice this year}', '{No|Not much} value for money, {too expensive|overpriced}', 'The discount code did not work'],
    },
    app: {
      good: ['The app is {easy to use|quick|great}', 'Checkout was {quick|easy|simple} on the website', 'The new app update is {great|much better}'],
      bad: ['The app {keeps crashing|crashed} at checkout', 'The website is {slow|so slow|down again}', 'I could not {log in|sign in} to my account', 'Payment failed {twice|three times} on the website'],
    },
  };
  const THEME_WEIGHTS = [['delivery', 0.3], ['quality', 0.2], ['service', 0.18], ['price', 0.17], ['app', 0.15]];

  SM.io.addExample('service-comments', {
    label: 'Service comments (1,000 rows): delivery, quality, service, price, app',
    about: 'Simulated: 1,000 short comments on an online shop, each about one theme (60%) or two of five: delivery (fast, late, parcel, courier, tracking), product quality (damaged, broken, sturdy, returned, refund), customer service (helpful, rude, waited on hold, support agent), price (value for money, expensive, discount) and the app and website (crashing at checkout, slow, log in). Each theme is praised or criticised half the time (the app 40% praised); the rating (1 to 5) is 3, plus 1.1 for each praise and less 1.3 for each complaint, plus noise. customer: about one comment in four comes from a customer who wrote before (an ID for Text Explorer); channel (web, app, phone) is at random. For Text Explorer (Analyze).',
    make() {
      const r = SM.util.rng('text-service-comments');
      const fill = (s) => s.replace(/\{([^}]*)\}/g, (_, alts) => r.pick(alts.split('|')));
      const pickTheme = (not) => {
        const pool = THEME_WEIGHTS.filter(([k]) => k !== not);
        const tot = pool.reduce((a, [, w]) => a + w, 0);
        let u = r.u() * tot;
        for (const [k, w] of pool) { u -= w; if (u < 0) return k; }
        return pool[pool.length - 1][0];
      };
      const n = 1000, c = { id: [], customer: [], channel: [], rating: [], comment: [] };
      const customers = [];
      for (let i = 0; i < n; i++) {
        const first = pickTheme(null);
        const themes = r.u() < 0.6 ? [first] : [first, pickTheme(first)];
        let score = 3;
        const parts = themes.map((th) => {
          const good = r.u() < (th === 'app' ? 0.4 : 0.5);
          score += good ? 1.1 : -1.3;
          return fill(r.pick(THEMES[th][good ? 'good' : 'bad']));
        });
        if (r.u() < 0.2) parts.push(score >= 3 ? r.pick(['Will order again', 'Thank you', 'Highly recommended']) : r.pick(['Never again', 'Very disappointed', 'Not happy']));
        let cust;
        if (customers.length && r.u() < 0.25) cust = r.pick(customers);
        else { cust = `C${String(customers.length + 1).padStart(4, '0')}`; customers.push(cust); }
        c.id.push(i + 1);
        c.customer.push(cust);
        c.channel.push(r.pick(['web', 'app', 'phone']));
        c.rating.push(Math.max(1, Math.min(5, Math.round(score + r.normal(0, 0.6)))));
        c.comment.push(`${parts.join('. ')}${r.u() < 0.3 ? '!' : '.'}`);
      }
      return new SM.Table({ name: 'Service comments', source: 'simulated', columns: [
        { name: 'comment id', dataType: 'numeric', modelingType: 'ordinal', values: c.id },
        { name: 'customer', dataType: 'character', values: c.customer },
        { name: 'channel', dataType: 'character', values: c.channel },
        { name: 'rating', dataType: 'numeric', modelingType: 'ordinal', values: c.rating },
        { name: 'comment', dataType: 'character', values: c.comment },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
