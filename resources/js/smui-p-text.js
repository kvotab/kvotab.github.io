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
     Word Cloud               the most frequent terms sized by count, in lines
                              (Ordered, JMP's default; Alphabetical) or in a
                              spiral (Centered);
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
  const STEMMERS = [['snowball', 'Snowball (Porter2)'], ['porter', 'Porter (1980)']];
  const TOKENIZING = [['regex', 'Regex'], ['basic', 'Basic Words']];
  const WEIGHTINGS = [['binary', 'Binary'], ['ternary', 'Ternary'], ['frequency', 'Frequency'], ['logfreq', 'Log Freq'], ['tfidf', 'TF IDF']];
  const CENTERING = [['uncentered', 'Uncentered'], ['centered', 'Centered'], ['scaled', 'Centered and Scaled']];
  const METHODS = [['varimax', 'Rotated SVD (varimax)'], ['nmf', 'Non-negative Matrix Factorization'], ['lda', 'Latent Dirichlet Allocation']];
  // JMP's word cloud layouts (its help): Ordered, the default, lines from the most frequent; Alphabetical; Centered
  const LAYOUTS = [['ordered', 'Ordered'], ['alphabetical', 'Alphabetical'], ['centered', 'Centered']];
  const LAYOUT_NOTE = { ordered: 'Ordered: in lines, the most frequent first', alphabetical: 'Alphabetical: alphabetically, in lines', centered: 'Centered: the largest in the middle, each next word along a spiral where it overlaps none' };
  const COLORINGS = [['uniform', 'Uniform'], ['grays', 'Arbitrary Grays'], ['colors', 'Arbitrary Colors'], ['column', 'By Column…']];
  const labelOf = (list, key) => (list.find((x) => x[0] === key) || [key, key])[1];
  // JMP's defaults of the SVD: TF IDF, Centered and Scaled (its help), 100 vectors; the terms' limits are chosen here
  const LSA_DEFAULT = { weighting: 'tfidf', centering: 'scaled', minFreq: 4, maxTerms: 1000, k: 100 };
  const TOPIC_DEFAULT = { method: 'varimax', k: 10, weighting: 'tfidf', centering: 'scaled', minFreq: 4, maxTerms: 1000 };
  const LCA_DEFAULT = { k: 5, minFreq: 4, maxTerms: 1000 };
  // JMP's Term Selection: Elastic Net (alpha 0.99), AICc, early stopping; terms seen 10 or more times
  const TS_DEFAULT = { response: null, target: null, weighting: 'binary', minFreq: 10, maxTerms: 1000, early: true };

  /* The word cloud's colours for text, 4.5:1 or more on the report in each
     theme (checked with the data-viz palette validator; the words are their
     own labels, so no colour carries a meaning of its own). */
  const INK = {
    light: { colors: ['#1c5cab', '#b4501f', '#0f7a55', '#4a3aa7', '#6a6a00', '#b8336a'], grays: ['#352921', '#5a4d42', '#6b5d4f', '#786b5d'], low: '#1f5fa8', mid: '#6b6259', high: '#b23a2e' },
    dark: { colors: ['#6da7ec', '#f08a5d', '#3cc494', '#a99ff0', '#d0b24a', '#ee86ad'], grays: ['#e8ddd0', '#cfc2b3', '#b8a898', '#9f9182'], low: '#7fb0ff', mid: '#b8a898', high: '#ff8a7a' },
  };
  const ink = () => (SM.util.themeColors().dark ? INK.dark : INK.light);

  /* What each field of the forms is for: the (i). */
  const HELP = {
    maxTerms: 'The columns of the document term matrix: at most this many terms, the most frequent first (ties alphabetically), from 1 to 100 000.',
    minFreq: 'Only terms seen at least this many times in all become columns; rarer ones are left out.',
    manage: {
      stopAdd: 'One word per line (lowercase): each is left out of the terms, and no phrase begins or ends with one. scikit-learn\'s English stop words are left out anyway.',
      recodes: 'One recode per line, old -> new (=, => and → work too): the old term is counted as the new one, an existing term to combine the two; nothing after the arrow drops the term.',
      phrasesAdd: 'One phrase of two or more words per line: where its words follow each other in a text they count as one term, and the single words lose those occurrences.',
    },
  };

  const wide = (tbl) => el('div', { class: 'sm-tx-scroll' }, tbl);

  /* ---- the graphs as matplotlib code -----------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table, as the notebook runs it. The singular values' bars and the topic
     scores come whole from the backend (plot_code); the word cloud and the SVD
     plots start with the backend's lines (cloud_head: the texts read as the
     report reads them, the terms and their counts; svd_head: the SVD) and end
     with the page's choices: the cloud's layout (each word where the page put
     it, the font sizes from the room it had), the terms named on the plot. The
     light theme's colours, the graph's size at 100 pixels an inch. */
  const J = JSON.stringify;
  const pyList = (a) => `[${a.map((v) => J(v)).join(', ')}]`;
  const area = (px) => Math.round(100 * (px * 0.72) ** 2) / 100;   // a marker's diameter in pixels as matplotlib's area in points²
  const BASE = '#2f6690', INK_TEXT = '#352921', ZERO = '#e0d7ce', INK_MUTED = '#786b5d';
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-tx-plotcode' }, graph, code) : graph);
  const zeroLines = [`ax.axhline(0, color="${ZERO}", linewidth=0.72, zorder=0)`, `ax.axvline(0, color="${ZERO}", linewidth=0.72, zorder=0)`];

  function cloudCode(S, { words, box, layout, coloring, byCol, minF, maxF }) {
    const L = [S.res.cloud_head, '',
      `n, min_size, max_size = ${words.length}, ${minF}, ${+maxF.toFixed(3)}   # the most frequent terms shown; the page's font sizes in pixels (the largest from the room it had)`,
      'words = term_list.head(n)   # the most frequent first, ties alphabetically',
      'c0, c1 = words["Count"].iloc[-1], words["Count"].iloc[0]',
      'size = (min_size + (max_size - min_size) * np.sqrt((words["Count"] - c0) / (c1 - c0))) if c1 > c0 else np.full(n, (min_size + max_size) / 2)   # the font grows with the square root of the count',
      `place = {   # each word's centre where the page put it, in its pixels (${LAYOUT_NOTE[layout] || LAYOUT_NOTE.centered})`,
      ...words.map((w) => `    ${J(w.term)}: (${w.cx.toFixed(1)}, ${w.cy.toFixed(1)}),`), '}'];
    const inkLight = INK.light;
    if (byCol) {
      const every = S.res.id ? 'every' : 'df';
      L.push(`v = pd.to_numeric(${every}[${J(byCol.name)}], errors="coerce")   # By Column: ${byCol.name}, a number`,
        'centre = v.mean() if v.notna().any() else 0.0   # its mean over the report\'s rows',
        'holds = {}   # the rows that hold each term', 'for r, ts in zip(df.index, terms):', '    for t in set(ts):', '        holds.setdefault(t, []).append(r)',
        'means = np.array([v.loc[holds.get(t, [])].mean() for t in words["Term"]])   # each word\'s mean over the rows that hold it',
        'dev = np.nanmax(np.abs(means - centre)) if np.isfinite(means).any() else 0.0',
        `low, mid, high = "${inkLight.low}", "${inkLight.mid}", "${inkLight.high}"   # blue below the mean, red above`, '', '',
        'def mix(a, b, t):', '    """The colour t of the way from a to b, as the page mixes them."""',
        '    x, y = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]',
        '    return "#" + "".join(f"{int(np.floor(p + t * (q - p) + 0.5)):02x}" for p, q in zip(x, y))', '', '',
        'color = [(mix(mid, low, min(1, -(m - centre) / dev)) if m < centre else mix(mid, high, min(1, (m - centre) / dev))) if np.isfinite(m) and dev > 0 else mid for m in means]');
    } else if (coloring === 'colors' || coloring === 'grays') {
      L.push(`palette = ${pyList(coloring === 'colors' ? inkLight.colors : inkLight.grays)}   # Arbitrary ${coloring === 'colors' ? 'Colors' : 'Grays'}: by each word's place in the list`,
        'color = [palette[i % len(palette)] for i in range(n)]');
    } else L.push(`color = ["${INK_TEXT}"] * n   # Uniform: the text colour`);
    L.push(`x0, y0, w, h = ${box.x0.toFixed(1)}, ${box.y0.toFixed(1)}, ${box.w.toFixed(1)}, ${box.h.toFixed(1)}   # the page's view of the cloud`);
    if (byCol) {
      L.push('from matplotlib.cm import ScalarMappable', 'from matplotlib.colors import LinearSegmentedColormap',
        'H = h / 100 + 0.5   # room under the cloud for the colour legend',
        'fig = plt.figure(figsize=(w / 100, H))', 'ax = fig.add_axes([0, 0.5 / H, 1, (h / 100) / H])',
        'cax = fig.add_axes([0.3, 0.2 / H, 0.4, 0.1 / H])',
        `fig.colorbar(ScalarMappable(norm=plt.Normalize(centre - dev, centre + dev), cmap=LinearSegmentedColormap.from_list("mean", [low, mid, high])), cax=cax, orientation="horizontal", label=${J(`Mean ${byCol.name}`)})`);
    } else L.push('fig = plt.figure(figsize=(w / 100, h / 100))', 'ax = fig.add_axes([0, 0, 1, 1])');
    L.push('ax.set_xlim(x0, x0 + w)', 'ax.set_ylim(y0 + h, y0)   # y down, as the page draws', 'ax.set_axis_off()',
      'for term, s_, c_ in zip(words["Term"], size, color):',
      '    ax.text(*place[term], term, fontsize=0.72 * s_, ha="center", va="center", color=c_)   # the size in points: 0.72 a pixel',
      'plt.show()');
    return L.join('\n');
  }

  function svdCode(r, kind, named, cl) {
    // coloured by the clusters: the clustering's lines (the same SVD, then Ward) instead of the SVD's alone
    const L = [cl ? cl.dendro_head : r.svd_head, '', ...(cl ? [`palette = ${pyList(PAL)}`, 'color = [palette[c % len(palette)] for c in cluster]   # each one\'s cluster\'s colour'] : []),
      'fig, ax = plt.subplots(figsize=(4, 3.6), layout="constrained")', ...zeroLines];
    const colour = cl ? 'c=color' : `color="${BASE}"`;
    if (kind === 'docs') {
      L.push(`ax.scatter(docs[:, 0], docs[:, 1], s=${area(r.doc_rows.length > 2000 ? 4 : 6)}, ${colour}, linewidths=0)   # each document: U S on the first two vectors`,
        'ax.set_xlabel("Doc Vec1")', 'ax.set_ylabel("Doc Vec2")', 'ax.set_title("Documents")');
    } else {
      L.push(`named = ${pyList(named)}   # the terms the page names: the furthest out, where their labels meet none named before`,
        `ax.scatter(terms[:, 0], terms[:, 1], s=${area(6)}, ${colour}, linewidths=0)   # each term: V S on the first two vectors`,
        'for j, t in enumerate(chosen):', '    if t in named:',
        `        ax.annotate(t, (terms[j, 0], terms[j, 1]), textcoords="offset points", xytext=(0, 4), ha="center", va="bottom", fontsize=7.56, color="${INK_TEXT}")`,
        'ax.set_xlabel("Term Vec1")', 'ax.set_ylabel("Term Vec2")', 'ax.set_title("Terms")');
    }
    L.push('plt.show()');
    return L.join('\n');
  }
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
      max_words: num('maxWords', 4), max_phrases: num('maxPhrases', 5000), min_chars: num('minChars', 1), max_chars: num('maxChars', 50),
      stemming: o('stemming', 'none'), stemmer: o('stemmer', 'snowball'), tokenizing: o('tokenizing', 'regex'),
      regex: o('customRegex', false) ? (String(o('regex', '') || '').trim() || null) : null,
      stop_add: listOpt(ctx, 'stopAdd', sc, []), recodes: listOpt(ctx, 'recodes', sc, {}), phrases: listOpt(ctx, 'phrasesAdd', sc, []),
      where: ctx.where || [],
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
    const lc = o('lca', null);
    if (lc && res.terms.length) await lcaOutline(ctx, S, parent, { ...LCA_DEFAULT, ...lc });
    const ts = o('termsel', null);
    if (ts && res.terms.length) await termselOutline(ctx, S, parent, { ...TS_DEFAULT, ...ts });
    if (o('sentiment', false)) await sentimentOutline(ctx, S, parent);
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
      { label: 'Containing Phrases', disabled: !terms.length, action: () => containingPhrases(ctx, S, terms) },
      { label: 'Select Contains', disabled: !phrases.length, action: () => selectContains(ctx, S, phrases) },
      { label: 'Select Contained', disabled: !phrases.length, action: () => selectContained(ctx, S, phrases) },
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
          ? [{ label: 'Containing Phrases', action: () => containingPhrases(ctx, S, items) }, { separator: true }, { label: 'Add Stop Word', action: () => addStop(ctx, S, items) }, { label: 'Recode…', action: () => recodeDialog(ctx, S, items) }]
          : [{ label: 'Select Contains', action: () => selectContains(ctx, S, items) }, { label: 'Select Contained', action: () => selectContained(ctx, S, items) }, { separator: true }, { label: 'Add Phrase', action: () => addPhrases(ctx, S, items) }]),
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
      fields: [{ key: 'to', label: 'New value', type: 'text', value: terms[0], help: 'The term to count the chosen term or terms as (lowercase): an existing term combines them with it, a new one renames them; empty drops them from the terms. The recode is kept with the report (Manage Recodes lists it).' }],
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
     none before it; Ordered: in lines, the most frequent first (JMP's
     default); Alphabetical: alphabetically, in lines. */
  function cloudLayout(words, mode, width) {
    const pad = 3;
    for (const w of words) { w.w = textWidth(w.term, w.size) + 2 * pad; w.h = w.size * 1.18 + pad; }
    if (mode === 'ordered' || mode === 'alphabetical') {
      const lines = [];
      let line = [], lw = 0;
      for (const w of (mode === 'alphabetical' ? words.slice().sort((a, b) => SM.table.collator.compare(a.term, b.term)) : words)) {
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
    const layout = o('cloudLayout', 'ordered');
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
    // the cloud and its legend, then its code
    const cbox = el('div', { class: 'sm-tx-cloudbox' }, cloud);
    if (byCol) {
      const lo = center - dev, hi = center + dev;
      cbox.append(el('div', { class: 'sm-tx-legend' },
        el('span', { text: `Mean ${byCol.name}` }), el('span', { text: fmt(lo, { sig: 4 }) }),
        el('span', { class: 'sm-tx-ramp', style: { background: `linear-gradient(90deg, ${P.low}, ${P.mid}, ${P.high})` } }),
        el('span', { text: fmt(hi, { sig: 4 }) })));
    }
    ob.add(cbox, ctx.code(cloudCode(S, { words, box, layout, coloring, byCol, minF, maxF })));
    ob.add(ctx.note(`The ${words.length} most frequent terms, each sized by its count (font size ∝ √count); ${layout === 'ordered' ? 'in lines, the most frequent first' : layout === 'alphabetical' ? 'alphabetically, in lines' : 'the most frequent in the middle'}.${byCol ? ` Coloured by the mean of ${byCol.name} over the rows that hold each term, around its mean over all the rows (${fmt(center, { sig: 4 })}).` : ''} Click a word to select its rows.`));
  }

  function cloudMenu(ctx, S) {
    const sc = S.col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    return [
      { label: 'Layout', submenu: () => LAYOUTS.map(([v, l]) => ({ label: l, checked: o('cloudLayout', 'ordered') === v, action: () => ctx.set('cloudLayout', v, sc) })) },
      { label: 'Coloring', submenu: () => COLORINGS.map(([v, l]) => ({ label: l, checked: o('cloudColor', 'uniform') === v, action: () => (v === 'column' ? cloudByDialog(ctx, S) : ctx.set('cloudColor', v, sc)) })) },
      { label: 'Number of Terms…', action: async () => { const v = await SM.ui.form({ title: 'Word Cloud: Number of Terms', fields: [{ key: 'n', label: 'The most frequent terms to show', type: 'number', value: o('cloudN', 100), help: 'How many of the most frequent terms the cloud shows, from 1 to 500 (100); each word\'s font grows with the square root of its count, so that its area follows the count.' }], validate: (x) => (Number.isInteger(x.n) && x.n >= 1 && x.n <= 500 ? null : 'A whole number from 1 to 500') }); if (v) ctx.set('cloudN', v.n, sc); } },
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
      fields: [{ key: 'col', label: 'Column', type: 'select', value: cur && nums.some((c) => c.id === cur) ? cur : nums[0].id, choices: nums.map((c) => [c.id, c.name]),
        help: 'The numeric column (a rating, say) whose mean over the rows that hold each word colours the word: blue below the column\'s mean over all the rows, red above, a neutral colour near it. A legend under the cloud gives the range.' }] });
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
    const o = (k, d) => ctx.opt(k, d, sc);
    // JMP's title: SVD, the centering, the weighting (SVD Centered and Scaled TF IDF)
    const ob = ctx.outline(`SVD ${labelOf(CENTERING, spec.centering)} ${labelOf(WEIGHTINGS, spec.weighting)}`, { parent, key: K(S, 'lsa'), info: 'p:text:lsa', menu: () => [
      { label: 'Specifications…', action: () => lsaDialog(ctx, S.col) },
      { label: 'SVD Scatterplot Matrix…', checked: !!o('spm', null), action: () => spmDialog(ctx, S.col, spec.k) },
      ctx.check('Cluster Terms', 'clusterTerms', sc, false),
      ctx.check('Cluster Documents', 'clusterDocs', sc, false),
      { separator: true },
      { label: 'Save Document Singular Vectors…', action: () => saveVectors(ctx, S, 'svd', spec) },
      { label: 'Save Term Singular Vectors', action: () => saveTermVectors(ctx, S, spec) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('lsa', null, sc) },
    ] });
    const m = o('spm', null);
    const r = await ctx.call('text.lsa', { ...lsaArgs(ctx, S, spec), show: Math.max(2, Number(m) || 2) });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    // the clusters first: they colour the SVD plots
    const clusters = {};
    for (const [opt, kind, nkey] of [['clusterTerms', 'terms', 'termClusters'], ['clusterDocs', 'docs', 'docClusters']]) {
      if (!o(opt, false) || r.k < 1) continue;
      const cr = await ctx.call('text.cluster', { ...lsaArgs(ctx, S, spec), kind, n_clusters: o(nkey, null) });
      clusters[kind] = cr;
    }
    if (r.k >= 2 && !ctx.headless) svdPlots(ctx, S, ob, r, clusters);
    else if (r.k < 2) ob.add(ctx.note('One singular vector: no plots.'));
    const sv = ctx.outline('Singular Values', { parent: ob, key: K(S, 'singular') });
    const rows = r.singular;
    const top = rows.slice(0, 30);
    const bars = ctx.plot([{ type: 'bar', orientation: 'h', y: top.map((x) => x.number), x: top.map((x) => x.percent), marker: { color: SM.report.BAR }, hovertemplate: '%{y}: %{x:.2f}%<extra></extra>' }],
      { margin: { l: 36, r: 12, t: 6, b: 34 }, xaxis: { title: { text: 'Percent' }, rangemode: 'tozero' }, yaxis: { autorange: 'reversed', dtick: top.length > 15 ? 5 : 1 }, bargap: 0.2 },
      { width: 280, height: Math.max(140, 13 * top.length + 50), title: 'Singular values, percent', select: false });
    sv.add(ctx.row(el('div', { class: 'sm-tx-list' }, ctx.rt({ columns: [{ key: 'number', label: 'Number', fmt: 'int' }, { key: 'value', label: 'Singular Value' }, { key: 'eigen', label: 'Eigenvalue' }, { key: 'percent', label: 'Percent', digits: 4 }, { key: 'cum', label: 'Cum Percent', digits: 4 }], rows }, { key: K(S, 'singular'), sortable: false })),
      withCode(bars, ctx.code((r.plot_code || {}).singular))),
      ctx.note(`${fmt(r.n_docs)} documents by ${fmt(r.n_terms)} terms (those seen ${r.min_freq} or more times, at most ${fmt(r.max_terms)}), ${labelOf(WEIGHTINGS, r.weighting)} weighting, ${labelOf(CENTERING, r.centering).toLowerCase()}; ${r.k} singular vectors by scikit-learn's ${r.solver}. Eigenvalue: the equivalent principal components' (s² / (n − 1)${r.centering === 'uncentered' ? ', uncentered s² / n' : ''}${r.centering === 'scaled' ? ': of the correlation matrix, summing to the number of terms' : r.centering === 'centered' ? ': of the covariance matrix' : ''}). Percent: each singular value's share of the matrix's sum of squares (s² over the total).`));
    if (m && r.k >= 2 && !ctx.headless) spmOutline(ctx, S, ob, r, Math.max(2, Math.min(Number(m), r.k)));
    for (const kind of ['terms', 'docs']) {
      const cr = clusters[kind];
      if (!cr) continue;
      if (cr.error) { ob.add(ctx.warn(`${kind === 'terms' ? 'Cluster Terms' : 'Cluster Documents'}: ${cr.error}`)); continue; }
      clusterOutline(ctx, S, ob, spec, cr);
    }
    ob.add(ctx.code(r.code));
  }

  function svdPlots(ctx, S, ob, r, clusters = {}) {
    const po = ctx.outline('SVD Plots', { parent: ob, key: K(S, 'svdplots') });
    const labels = labelsFor(ctx, S, r);
    const dc = clusters.docs && !clusters.docs.error ? clusters.docs : null, tcl = clusters.terms && !clusters.terms.error ? clusters.terms : null;
    const docTrace = { type: scatterType(r.doc_rows.length), mode: 'markers', x: r.docs[0], y: r.docs[1], marker: { size: r.doc_rows.length > 2000 ? 4 : 6, ...(dc ? { color: dc.labels.map(pal) } : {}) }, hovertext: dc ? labels.map((h, d) => `${h} (cluster ${dc.labels[d] + 1})`) : labels, hovertemplate: '%{hovertext}<extra></extra>', name: 'Documents' };
    docTrace.rows = S.res.id ? r.doc_rows : r.doc_rows.map((d) => d[0]);
    const tv = r.term_vectors;
    const lab = labelled(r.terms, tv[0], tv[1], { width: 330, height: 290, most: 14 });
    const c = SM.util.themeColors();
    const termTrace = {
      type: 'scatter', mode: 'markers+text', x: tv[0], y: tv[1], rows: r.terms.map((t) => termRows(S, t)),
      text: r.terms.map((t, j) => (lab.has(j) ? T(t) : '')), textposition: 'top center', textfont: { size: 10.5, color: c.text }, cliponaxis: false,
      hovertext: r.terms.map((t, j) => `${T(t)}: ${fmt(r.term_counts[j])}${tcl ? ` (cluster ${tcl.labels[j] + 1})` : ''}`), hovertemplate: '%{hovertext}<br>(%{x:.4g}, %{y:.4g})<extra></extra>', marker: { size: 6, color: tcl ? tcl.labels.map(pal) : SM.report.BASE }, name: 'Terms',
    };
    const ax = (t) => ({ title: { text: t }, zeroline: true });
    const named = r.terms.filter((_, j) => lab.has(j));
    po.add(ctx.row(
      withCode(ctx.plot([docTrace], { xaxis: ax('Doc Vec1'), yaxis: ax('Doc Vec2'), margin: { l: 56, r: 10, t: 24, b: 44 }, title: { text: 'Documents', font: { size: 12 } } }, { width: 400, height: 360, title: `Document singular vectors of ${S.col.name}`, ...(dc ? { rowColors: false } : {}) }),
        ctx.code(svdCode(r, 'docs', null, dc))),
      withCode(ctx.plot([termTrace], { xaxis: ax('Term Vec1'), yaxis: ax('Term Vec2'), margin: { l: 56, r: 16, t: 24, b: 44 }, title: { text: 'Terms', font: { size: 12 } } }, { width: 400, height: 360, title: `Term singular vectors of ${S.col.name}` }),
        ctx.code(svdCode(r, 'terms', named, tcl)))),
    ctx.note(`Each point on the left is a document (U S: its weighted terms projected on the first two singular vectors), on the right a term (V S), as latent semantic analysis compares them; the terms furthest out are named.${dc ? ` The documents are coloured by their cluster (Cluster Documents, ${dc.n_clusters} clusters).` : ''}${tcl ? ` The terms are coloured by their cluster (Cluster Terms, ${tcl.n_clusters} clusters).` : ''} Documents near each other use the same terms; a term point stands for the rows that hold it. Click or drag to select rows.`));
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
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms, help: `${HELP.maxTerms} 1000 by default.` },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq, help: `${HELP.minFreq} 4 by default.` },
        { key: 'weighting', label: 'Weighting', type: 'select', value: cur.weighting, choices: WEIGHTINGS, help: 'How each count is weighted before the decomposition (the choices above); TF IDF, the default, weighs a term down the more documents hold it.' },
        { key: 'k', label: 'Number of Singular Vectors', type: 'number', value: cur.k, help: 'How many singular vectors to compute, from 1 (100 by default), cut to the documents and the terms less one; the plots show the first two, and the Save commands take the first ones.' },
        { key: 'centering', label: 'Centering and Scaling', type: 'select', value: cur.centering, choices: CENTERING, help: 'Uncentered, Centered (the default) or Centered and Scaled: whether each term\'s mean is taken away, and each term also divided by its standard deviation, before the decomposition (the choices above).' },
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
      so.add(ctx.row(withCode(ctx.plot([tr], { xaxis: { title: { text: `Topic 1 (${T(tops(0))})` } }, yaxis: { title: { text: `Topic 2 (${T(tops(1))})` } }, margin: { l: 60, r: 10, t: 8, b: 48 } }, { width: 440, height: 360, title: `Topic scores of ${S.col.name}` }),
        ctx.code((r.plot_code || {}).scores))),
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
        { key: 'n', label: 'Number of Topics', type: 'number', value: cur.k, help: 'How many topics, from 1 to 1000 (10), cut to the documents and the terms less one.' },
        { key: 'method', label: 'Method', type: 'select', value: cur.method, choices: METHODS, help: 'Rotated SVD (varimax), JMP\'s: the first singular vectors rotated so that each topic has a few terms with large loadings. Non-negative Matrix Factorization and Latent Dirichlet Allocation are scikit-learn\'s (the choices above); they start from the report\'s seed.' },
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms, help: `${HELP.maxTerms} 1000 by default.` },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq, help: `${HELP.minFreq} 4 by default.` },
        { key: 'weighting', label: 'Weighting (LDA takes the counts)', type: 'select', value: cur.weighting, choices: WEIGHTINGS, help: 'How each count is weighted, as for Latent Semantic Analysis (TF IDF by default); Latent Dirichlet Allocation always takes the plain counts.' },
        { key: 'centering', label: 'Centering and Scaling (rotated SVD)', type: 'select', value: cur.centering, choices: CENTERING, help: 'For the rotated SVD only: Uncentered, Centered (the default) or Centered and Scaled, as for Latent Semantic Analysis. NMF and LDA take the weighted matrix as it is.' },
      ],
      validate: specError,
    });
    if (v) ctx.set('topics', { k: v.n, method: v.method, maxTerms: v.maxTerms, minFreq: v.minFreq, weighting: v.weighting, centering: v.centering }, sc);
  }

  /* ---- shared by the new analyses ------------------------------------------------------------------------------------ */
  const PAL = SM.util.PALETTE;
  const pal = (k) => PAL[((k % PAL.length) + PAL.length) % PAL.length];
  /* The rows of a term of the Term List (the rows whose own text holds it). */
  const termRows = (S, t) => { const i = S.index.get(t); return i == null ? [] : S.res.term_rows[i]; };
  /* A document as the hover and the tables name it: its ID, or its row. */
  const docName = (S, r, d) => (S.res.id ? String(r.doc_labels ? r.doc_labels[d] : d + 1) : `row ${r.doc_rows[d][0] + 1}`);
  const selectRows = (ctx, rows, ev) => { if (ctx.table) ctx.table.select([...new Set(rows)].sort((a, b) => a - b), ev && (ev.shiftKey || ev.metaKey || ev.ctrlKey) ? 'add' : 'replace'); };
  const button = (label, onClick, title) => { const b = el('button', { type: 'button', class: 'sm-btn', text: label, title: title || null }); b.addEventListener('click', onClick); return b; };

  /* The texts of some rows, the given terms' words marked: Show Text of a cluster, of a sentiment term. */
  function showRows(ctx, S, rows, title, lead, terms = []) {
    const col = S.col;
    const forms = [];
    for (const t of terms) forms.push(...(S.res.forms[t] ? S.res.forms[t].map((f) => f[0]) : [t.replace(DOT, '')]));
    const re = highlighter(forms);
    const shown = rows.slice(0, 500);
    SM.ui.dialog({
      title, className: 'sm-tx-dialog', info: 'p:text:lists',
      body: el('div', null, el('p', { class: 'sm-dialog-lead', text: `${lead}${rows.length > shown.length ? ` The first ${shown.length} are shown.` : ''}` }),
        el('ol', { class: 'sm-tx-texts' }, ...shown.map((r) => el('li', null, el('span', { class: 'sm-tx-rownum', text: `Row ${r + 1}` }), el('span', { class: 'sm-tx-text' }, ...marked(col.values[r], re)))))),
      buttons: [{ label: 'Select These Rows', action: () => { ctx.table.select(rows); } }, { label: 'Close', primary: true }],
    });
  }

  /* ---- Latent Class Analysis ---------------------------------------------------------------------------------------- */
  const lcaArgs = (ctx, S, spec) => ({ ...S.args, n_clusters: spec.k, min_freq: spec.minFreq, max_terms: spec.maxTerms, seed: SM.predict.seed(ctx) });

  async function lcaOutline(ctx, S, parent, spec) {
    const sc = S.col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    let r = null;
    const members = () => { const m = Array.from({ length: r.k }, () => []); r.likely.forEach((c, d) => m[c - 1].push(...r.doc_rows[d])); return m.map((x) => x.sort((a, b) => a - b)); };
    const ob = ctx.outline(`Latent Class Analysis for ${spec.k} Clusters`, { parent, key: K(S, 'lca'), info: 'p:text:lca', menu: () => [
      { label: 'Specifications…', action: () => lcaDialog(ctx, S.col) },
      { label: 'Display Options', submenu: () => [
        ctx.check('Cluster Mixture Probabilities', 'lcaMix', sc, true), ctx.check('Term Probabilities by Cluster', 'lcaTerms', sc, true),
        ctx.check('Top Terms by Cluster', 'lcaTop', sc, true), ctx.check('MDS Plot', 'lcaMds', sc, true), ctx.check('Cluster Probabilities by Row', 'lcaRows', sc, false)] },
      { label: 'Show Text', disabled: !r, submenu: () => (r ? members().map((rows, c) => ({ label: `Cluster ${c + 1} (${fmt(rows.length)} rows)`, action: () => showRows(ctx, S, rows, `Show Text: cluster ${c + 1}`, `The ${fmt(rows.length)} rows of the documents most likely in cluster ${c + 1}; its top terms marked.`, r.top[c].slice(0, 10).map((x) => x.term)) })) : []) },
      { label: 'Color by Cluster', disabled: !r, action: () => { members().forEach((rows, c) => ctx.table.setColor(rows, c % 12)); SM.ui.toast(`Coloured the rows by their most likely cluster (${r.k} colours)`); } },
      { label: 'Save Probabilities', action: () => lcaSave(ctx, S, spec, 'probs') },
      { label: 'Save Cluster', action: () => lcaSave(ctx, S, spec, 'cluster') },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('lca', null, sc) },
    ] });
    let off = null;
    if (!ctx.headless) {
      const note = el('p', { class: 'sm-ob-note', role: 'status', text: 'Latent class analysis: fitting…' });
      ob.add(note);
      const h = SM.engine.on('progress', (p) => { if (p.what === 'lca') { note.textContent = `Latent class analysis: start ${p.done} of ${p.total}…`; ctx.report.noteEl.textContent = note.textContent; } });
      off = () => { h(); note.remove(); };
    }
    try { r = await ctx.call('text.lca', lcaArgs(ctx, S, spec)); } finally { if (off) off(); }
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const kk = r.k;
    ob.add(wide(ctx.kv([['Number of Clusters', kk], ['Documents', r.n_docs], ['Terms', r.n_terms], ['BIC', fmt(r.bic, { sig: 7 })], ['−LogLikelihood', fmt(-r.loglik, { sig: 7 })], ['Iterations', r.iterations]])),
      ctx.note(`A Bernoulli mixture of the binary document term matrix (${fmt(r.n_docs)} documents by the ${fmt(r.n_terms)} terms seen ${r.min_freq} or more times), fitted by EM from the best of ${r.starts} random starts (seed ${r.seed}); BIC = −2 log L + ${fmt(r.params)} log n. Click a cluster, a term or a point to select rows.`));
    const byCl = members();
    if (o('lcaMix', true)) {
      const mo = ctx.outline('Cluster Mixture Probabilities', { parent: ob, key: K(S, 'lcamix') });
      mo.add(wide(ctx.rt({ columns: [{ key: 'c', label: 'Cluster', fmt: 'int' }, { key: 'p', label: 'Probability', digits: 4 }, { key: 'n', label: 'Documents', fmt: 'int', title: 'the documents most likely in the cluster' }],
        rows: r.pi.map((p, c) => ({ c: c + 1, p, n: r.docs_in[c] })) }, { key: K(S, 'lcamix'), sortable: false, onRow: (row, ev) => selectRows(ctx, byCl[row.c - 1], ev) })),
      ctx.note('Each cluster\'s mixing probability: the share of the documents it holds (the model\'s). Click a cluster to select the rows of the documents most likely in it (shift adds); Show Text (red triangle) lists them.'));
    }
    if (o('lcaTerms', true)) {
      const to = ctx.outline('Term Probabilities by Cluster', { parent: ob, key: K(S, 'lcaterms') });
      const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'count', label: 'Count', fmt: 'int' }, ...r.pi.map((_, c) => ({ key: `c${c}`, label: `Cluster ${c + 1}`, digits: 4 })),
        { key: 'most', label: 'Cluster Most Characteristic', fmt: 'int' }, { key: 'prob', label: 'Cluster Most Probable', fmt: 'int' }];
      const rows = r.terms.map((term, j) => ({ term, count: r.term_counts[j], ...Object.fromEntries(r.P.map((pc, c) => [`c${c}`, pc[j]])), most: r.characteristic[j], prob: r.probable[j] }));
      to.add(el('div', { class: 'sm-tx-list sm-tx-wide' }, ctx.rt({ columns: cols, rows }, { key: K(S, 'lcaterms'), maxRows: 1000, onRow: (row, ev) => pick(ctx, S, 'term', row.term, ev) })),
        ctx.note('The probability that a document of the cluster holds the term, the most frequent terms first. Cluster Most Characteristic: where the term occurs at the highest rate; Cluster Most Probable: where a document that holds the term most likely comes from. Click a heading to sort by a cluster.'));
    }
    if (o('lcaTop', true)) {
      const tt = ctx.outline('Top Terms by Cluster', { parent: ob, key: K(S, 'lcatop') });
      tt.add(el('div', { class: 'sm-tx-topics' }, ...r.top.map((tp, c) => ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'score', label: 'Score', digits: 3 }], rows: tp },
        { caption: `Cluster ${c + 1}`, key: K(S, `lcatop-${c + 1}`), sortable: false, onRow: (row, ev) => pick(ctx, S, 'term', row.term, ev) }))),
      ctx.note('The ten terms with the highest scores in each cluster, as JMP scores them: 100 · mean(p) · log10(p_c / mean(p)), p_c the term\'s probability in the cluster and mean(p) its mean over the clusters. A negative score: rarer in the cluster than on average.'));
    }
    if (o('lcaMds', true) && !ctx.headless) {
      const md = ctx.outline('MDS Plot', { parent: ob, key: K(S, 'lcamds') });
      const pmax = Math.max(...r.pi);
      const c = SM.util.themeColors();
      const trace = { type: 'scatter', mode: 'markers+text', x: r.coords.map((p) => p[0]), y: r.coords.map((p) => p[1]), rows: byCl,
        marker: { size: r.pi.map((p) => 10 + 30 * Math.sqrt(p / pmax)), color: r.pi.map((_, k) => pal(k)), opacity: 0.6, line: { width: 0 } },
        text: r.pi.map((_, k) => `Cluster ${k + 1}`), textfont: { size: 10.5, color: c.text }, cliponaxis: false,
        hovertext: r.pi.map((p, k) => `Cluster ${k + 1}: probability ${fmt(p, { digits: 3 })}; ${T(r.top[k].slice(0, 3).map((x) => x.term).join(', '))}`), hovertemplate: '%{hovertext}<extra></extra>' };
      md.add(withCode(ctx.plot([trace], { xaxis: { title: { text: 'MDS1' }, zeroline: true }, yaxis: { title: { text: 'MDS2' }, zeroline: true }, margin: { l: 56, r: 16, t: 10, b: 44 } },
        { width: 400, height: 360, title: 'MDS Plot', rowColors: false }), ctx.code((r.plot_code || {}).mds)),
      ctx.note('The clusters mapped by classical (Torgerson) multidimensional scaling of the symmetric Kullback–Leibler distances between their term distributions: clusters near each other use the terms alike. Each marker\'s area follows its mixing probability; click one to select the rows of its documents.'));
    }
    if (o('lcaRows', false)) {
      const ro = ctx.outline('Cluster Probabilities by Row', { parent: ob, key: K(S, 'lcarows') });
      const cols = [{ key: 'doc', label: S.res.id || 'Row', fmt: 'text' }, { key: 'likely', label: 'Most Likely Cluster', fmt: 'int' }, ...r.pi.map((_, c) => ({ key: `p${c}`, label: `Prob Cluster ${c + 1}`, digits: 4 }))];
      const rows = r.R.map((pr, d) => ({ doc: docName(S, r, d), likely: r.likely[d], d, ...Object.fromEntries(pr.map((p, c) => [`p${c}`, p])) }));
      ro.add(el('div', { class: 'sm-tx-list sm-tx-wide' }, ctx.rt({ columns: cols, rows }, { key: K(S, 'lcarows'), maxRows: 1000, onRow: (row, ev) => selectRows(ctx, r.doc_rows[row.d], ev) })));
    }
    ob.add(ctx.code(r.code));
  }

  async function lcaDialog(ctx, col) {
    const sc = col.id;
    const cur = { ...LCA_DEFAULT, ...(ctx.opt('lca', null, sc) || {}) };
    const v = await SM.ui.form({
      title: 'Latent Class Analysis', info: 'p:text:lca',
      lead: 'Clusters the documents by a mixture model of the binary document term matrix (which terms each document holds).',
      fields: [
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms, help: `${HELP.maxTerms} 1000 by default.` },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq, help: `${HELP.minFreq} 4 by default.` },
        { key: 'k', label: 'Number of Clusters', type: 'number', value: cur.k, help: 'How many clusters (latent classes), from 2 to 100 (5 by default): compare the BIC of a few numbers, the smaller the better.' },
      ],
      validate: (x) => specError(x) || (Number.isInteger(x.k) && x.k >= 2 && x.k <= 100 ? null : 'Number of Clusters: a whole number from 2 to 100'),
    });
    if (v) ctx.set('lca', { k: v.k, minFreq: v.minFreq, maxTerms: v.maxTerms }, sc);
  }

  async function lcaSave(ctx, S, spec, what) {
    try {
      const r = await ctx.call('text.lca_save', lcaArgs(ctx, S, spec));
      if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
      if (what === 'cluster') ctx.saveColumn('Most Likely Cluster', { rows: r.rows, values: r.likely }, { modelingType: 'nominal', notes: fromNote(ctx, `the most likely of ${r.k} latent classes of ${S.col.name}`) });
      else r.probs.forEach((vals, c) => ctx.saveColumn(`Prob Cluster ${c + 1}`, { rows: r.rows, values: vals }, { notes: fromNote(ctx, `the probability of latent class ${c + 1} of ${r.k} of ${S.col.name}`) }));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* ---- Cluster Terms and Cluster Documents: the dendrogram --------------------------------------------------------- */
  function leavesUnder(merges, n, node) {
    const out = [], stack = [node];
    while (stack.length) { const v = stack.pop(); if (v < n) out.push(v); else { const [a, b] = merges[v - n]; stack.push(a, b); } }
    return out;
  }

  /* The dendrogram's geometry: each leaf's place and each join's height and cluster (below the cut). */
  function dendroShape(res) {
    const n = res.n, k = res.n_clusters;
    const pos = new Float64Array(2 * n - 1), hh = new Float64Array(2 * n - 1), node = new Int32Array(2 * n - 1);
    res.order.forEach((leaf, q) => { pos[leaf] = q; });
    for (let i = 0; i < n; i++) node[i] = res.labels[i];
    res.merges.forEach(([a, b], s) => { pos[n + s] = (pos[a] + pos[b]) / 2; hh[n + s] = res.heights[s]; node[n + s] = node[a]; });
    const cut = k >= n ? 0 : k <= 1 ? res.heights[n - 2] * 1.04 : (res.heights[n - k - 1] + res.heights[n - k]) / 2;
    return { n, k, pos, hh, node, cut };
  }

  function dendroCode(res, title, w, h, names) {
    const L = [res.dendro_head, '',
      'pos, hh, node = np.zeros(2 * n - 1), np.zeros(2 * n - 1), np.zeros(2 * n - 1, dtype=int)',
      'pos[order] = np.arange(n)   # each leaf\'s place, from the top',
      'node[:n] = cluster',
      'for s, (a, b) in enumerate(Z[:, :2].astype(int)):',
      '    pos[n + s], hh[n + s], node[n + s] = (pos[a] + pos[b]) / 2, heights[s], node[a]   # a join: between its two, at its distance',
      'cut = 0 if k >= n else heights[n - 2] * 1.04 if k <= 1 else (heights[n - k - 1] + heights[n - k]) / 2   # between the joins the clusters stop at',
      `palette = ${pyList(PAL)}`,
      `fig, ax = plt.subplots(figsize=(${w / 100}, ${h / 100}), layout="constrained")`,
      'for s, (a, b) in enumerate(Z[:, :2].astype(int)):',
      `    color = palette[node[n + s] % len(palette)] if s < n - k else "${INK_MUTED}"   # a cluster's joins in its colour, those above the cut grey`,
      '    ax.plot([hh[a], heights[s], heights[s], hh[b]], [pos[a], pos[a], pos[b], pos[b]], color=color, linewidth=1.3)',
      `ax.scatter(np.zeros(n), pos[:n], s=${area(res.n > 400 ? 3 : 5)}, c=[palette[c % len(palette)] for c in cluster], linewidths=0, zorder=3)`,
      'ax.axvline(cut, color="#b0413e", linestyle="--", linewidth=1.2)',
      'ax.set_ylim(n - 0.5, -0.5)'];
    if (names) L.push(`ax.set_yticks(pos[:n], ${names})`, 'ax.tick_params(axis="y", labelsize=6.8)');
    else L.push('ax.set_yticks([])');
    L.push('ax.set_xlim(left=0)', 'ax.set_xlabel("Distance")', `ax.set_title(${J(title)})`, 'plt.show()');
    return L.join('\n');
  }

  function clusterOutline(ctx, S, parent, spec, res) {
    const sc = S.col.id;
    const terms = res.kind === 'terms';
    const nkey = terms ? 'termClusters' : 'docClusters';
    const title = terms ? 'Cluster Terms' : 'Cluster Documents';
    const leafRows = (i) => (terms ? termRows(S, res.names[i]) : res.doc_rows[i]);
    const members = Array.from({ length: res.n_clusters }, () => []);
    res.labels.forEach((c, i) => members[c].push(i));
    const rowsOf = (c) => [...new Set(members[c].flatMap(leafRows))].sort((a, b) => a - b);
    const setK = (k) => ctx.set(nkey, Math.max(1, Math.min(res.n, k)), sc);
    const ob = ctx.outline(title, { parent, key: K(S, terms ? 'clterms' : 'cldocs'), info: 'p:text:cluster', menu: () => [
      { label: 'Number of Clusters…', action: async () => { const v = await SM.ui.form({ title: `${title}: Number of Clusters`, info: 'p:text:cluster', fields: [{ key: 'k', label: 'Number of clusters', type: 'number', value: res.n_clusters, help: `How many clusters to cut the tree into, from 1 to ${fmt(res.n)}; by default where the joining distance jumps most (${res.default_k} here). The clusters colour the ${terms ? 'terms' : 'documents'} of the SVD plots.` }], validate: (x) => (Number.isInteger(x.k) && x.k >= 1 && x.k <= res.n ? null : `A whole number from 1 to ${res.n}`) }); if (v) setK(v.k); } },
      { label: terms ? 'Save Term Clusters' : 'Save Document Clusters', action: () => saveClusters(ctx, S, res) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set(terms ? 'clusterTerms' : 'clusterDocs', false, sc) },
    ] });
    const sizes = members.map((m, c) => ({ c: c + 1, n: m.length, first: m.slice(0, 6).map((i) => res.names[i]).join(', ') }));
    ob.add(ctx.note(`Ward's hierarchical clustering of the ${terms ? 'terms\' coordinates (V S)' : 'documents\' coordinates (U S)'} on the ${res.k_vectors} singular vectors of the SVD, ${fmt(res.n)} ${terms ? 'terms' : 'documents'}; ${res.n_clusters} cluster${res.n_clusters > 1 ? 's' : ''}${ctx.opt(nkey, null, sc) == null ? ' (where the joining distance jumps most)' : ''}. The clusters colour the ${terms ? 'term' : 'document'} SVD plot.`));
    if (ctx.headless) {
      ob.add(ctx.rt({ columns: [{ key: 'c', label: 'Cluster', fmt: 'int' }, { key: 'n', label: terms ? 'Terms' : 'Documents', fmt: 'int' }], rows: sizes }, { key: K(S, `${nkey}-sizes`), sortable: false }));
      return;
    }
    const D = dendroShape(res);
    const tc = SM.util.themeColors();
    const groups = new Map();
    res.merges.forEach(([a, b], s) => {
      const key = s < D.n - D.k ? `c${D.node[D.n + s]}` : 'above';
      if (!groups.has(key)) groups.set(key, { color: key === 'above' ? tc.muted : pal(D.node[D.n + s]), x: [], y: [], c: [] });
      const g = groups.get(key);
      g.x.push(D.hh[a], res.heights[s], res.heights[s], D.hh[b], null);
      g.y.push(D.pos[a], D.pos[a], D.pos[b], D.pos[b], null);
      g.c.push(s, s, s, s, null);
    });
    const traces = [...groups.values()].map((g) => ({ type: 'scatter', mode: 'lines', x: g.x, y: g.y, customdata: g.c, line: { color: g.color, width: 1.3 }, hovertemplate: 'join at %{x:.4g}<extra>click: select</extra>' }));
    traces.push({ type: 'scatter', mode: 'markers', x: res.order.map(() => 0), y: res.order.map((leaf) => D.pos[leaf]), rows: res.order.map(leafRows),
      marker: { size: D.n > 400 ? 3 : 5, color: res.order.map((leaf) => pal(res.labels[leaf])) }, hovertext: res.order.map((leaf) => T(res.names[leaf])), hovertemplate: '%{hovertext}<extra></extra>' });
    const showLabels = D.n <= 150;
    const H = showLabels ? Math.max(240, 13 * D.n + 60) : 620;
    const plot = ctx.plot(traces, {
      xaxis: { title: { text: 'Distance' }, rangemode: 'tozero', zeroline: false },
      yaxis: { range: [D.n - 0.5, -0.5], autorange: false, showgrid: false, zeroline: false, tickvals: showLabels ? res.order.map((leaf) => D.pos[leaf]) : [], ticktext: showLabels ? res.order.map((leaf) => T(res.names[leaf])) : [], tickfont: { size: 9.5 }, ticks: '' },
      shapes: [{ type: 'line', x0: D.cut, x1: D.cut, yref: 'paper', y0: 0, y1: 1, line: { color: '#b0413e', width: 1.2, dash: 'dash' } }],
      margin: { l: showLabels ? 96 : 20, r: 16, t: 10, b: 40 },
    }, {
      width: 560, height: H, title: `${title} of ${S.col.name}`, rowColors: false,
      onDraw: (gd) => gd.on('plotly_click', (ev) => {
        const pt = ev && ev.points && ev.points[0];
        if (!pt || !Number.isInteger(pt.customdata)) return;
        selectRows(ctx, leavesUnder(res.merges, D.n, D.n + pt.customdata).flatMap(leafRows), ev.event);
      }),
    });
    const names = showLabels ? (terms ? 'chosen' : (S.res.id ? 'list(docs)' : '[str(i + 1) for i in df.index]')) : null;
    ob.add(el('div', { class: 'sm-tx-controls', 'data-noexport': '' }, el('span', { class: 'sm-tx-hint', text: `${res.n_clusters} cluster${res.n_clusters > 1 ? 's' : ''}` }),
      button('−', () => setK(res.n_clusters - 1), 'One cluster fewer'), button('+', () => setK(res.n_clusters + 1), 'One cluster more')),
    withCode(plot, ctx.code(dendroCode(res, `${title} of ${S.col.name}`, 560, H, names))),
    el('div', { class: 'sm-tx-legend sm-tx-clusters' }, ...sizes.map((z) => {
      const b = el('button', { type: 'button', title: `Select the rows of cluster ${z.c}: ${z.first}${z.n > 6 ? ', …' : ''}` }, el('span', { class: 'sm-tx-swatch', style: { background: pal(z.c - 1) } }), `${z.c}: ${fmt(z.n)}`);
      b.addEventListener('click', (ev) => selectRows(ctx, rowsOf(z.c - 1), ev));
      return b;
    })),
    ctx.note(`Click a cluster below the dendrogram, or a join, to select the rows ${terms ? 'that hold its terms' : 'of its documents'}; − and + change the number of clusters.`), ctx.code(res.code));
  }

  function saveClusters(ctx, S, res) {
    if (res.kind === 'docs') {
      const rows = [], vals = [];
      res.doc_rows.forEach((rs, d) => { for (const r of rs) { rows.push(r); vals.push(res.labels[d] + 1); } });
      ctx.saveColumn('Document Cluster', { rows, values: vals }, { modelingType: 'nominal', notes: fromNote(ctx, `the document's cluster of ${res.n_clusters} (Ward, on the SVD of ${S.col.name})`) });
      return;
    }
    const cnt = new Map(S.res.terms.map((t) => [t.term, t]));
    const t = new SM.Table({
      name: SM.app.uniqueTableName(`${S.col.name} term clusters`), source: `saved from ${ctx.report.title}`,
      notes: `The terms of the SVD of ${S.col.name} and their cluster of ${res.n_clusters} (Ward's method on the terms' singular vectors).`,
      columns: [{ name: 'Term', dataType: 'character', values: res.names }, { name: 'Count', dataType: 'numeric', values: res.names.map((x) => (cnt.get(x) || {}).count ?? NaN) },
        { name: 'Cases', dataType: 'numeric', values: res.names.map((x) => (cnt.get(x) || {}).cases ?? NaN) },
        { name: 'Cluster', dataType: 'numeric', modelingType: 'nominal', values: res.labels.map((c) => c + 1) }],
    });
    SM.app.addTable(t);
    SM.ui.toast(`Made the table ${t.name}`);
  }

  /* ---- SVD Scatterplot Matrix: documents below the diagonal, terms above (as JMP draws it) ------------------------- */
  function spmOutline(ctx, S, ob, r, m) {
    const sc = S.col.id;
    const so = ctx.outline('SVD Scatterplots of Document and Term Spaces', { parent: ob, key: K(S, 'spm'), info: 'p:text:spm', menu: () => [
      { label: 'Size…', action: () => spmDialog(ctx, S.col, r.k) },
      { label: 'Remove', action: () => ctx.set('spm', null, sc) },
    ] });
    const R = m, Cn = m - 1, gap = 0.035;
    const dom = (i, n) => { const w = (1 - gap * (n - 1)) / n; return [i * (w + gap), i * (w + gap) + w]; };
    const layout = { margin: { l: 58, r: 58, t: 44, b: 48 }, showlegend: false, shapes: [], annotations: [] };
    const traces = [];
    const tc = SM.util.themeColors();
    const labels = labelsFor(ctx, S, r);
    const dRows = S.res.id ? r.doc_rows : r.doc_rows.map((d) => d[0]);
    const tRows = r.terms.map((t) => termRows(S, t));
    const tHover = r.terms.map((t, j) => `${T(t)}: ${fmt(r.term_counts[j])}`);
    for (let i = 0; i < R; i++) {
      for (let j = 0; j < Cn; j++) {
        const q = i * Cn + j + 1;
        const xa = `xaxis${q === 1 ? '' : q}`, ya = `yaxis${q === 1 ? '' : q}`;
        const docs = j < i;   // below the diagonal: documents, Doc Vec j+1 across and Doc Vec i+1 up; above: terms, Term Vec j+2 across and Term Vec i+1 up
        const [x0, x1] = dom(j, Cn), [y1b, y0b] = dom(R - 1 - i, R);
        layout[xa] = { domain: [x0, x1], anchor: `y${q === 1 ? '' : q}`, zeroline: true, showgrid: false, tickfont: { size: 9 }, side: i === 0 && !docs ? 'top' : 'bottom', showticklabels: (i === R - 1) || (i === 0 && !docs) };
        layout[ya] = { domain: [y1b, y0b], anchor: `x${q === 1 ? '' : q}`, zeroline: true, showgrid: false, tickfont: { size: 9 }, side: j === Cn - 1 && !docs ? 'right' : 'left', showticklabels: (j === 0 && docs) || (j === Cn - 1 && !docs) };
        if (i === R - 1) layout[xa].title = { text: `Doc Vec${j + 1}`, font: { size: 11 } };
        if (i === 0 && !docs) layout[xa].title = { text: `Term Vec${j + 2}`, font: { size: 11 } };
        if (j === 0 && docs) layout[ya].title = { text: `Doc Vec${i + 1}`, font: { size: 11 } };
        if (j === Cn - 1 && !docs) layout[ya].title = { text: `Term Vec${i + 1}`, font: { size: 11 } };
        layout.shapes.push({ type: 'rect', xref: `x${q === 1 ? '' : q} domain`, yref: `y${q === 1 ? '' : q} domain`, x0: 0, x1: 1, y0: 0, y1: 1, layer: 'below', line: { width: 0 },
          fillcolor: docs ? 'rgba(217, 130, 43, 0.08)' : 'rgba(47, 102, 144, 0.08)' });
        const t = docs
          ? { type: scatterType(r.doc_rows.length), mode: 'markers', x: r.docs[j], y: r.docs[i], rows: dRows, marker: { size: r.doc_rows.length > 2000 ? 3 : 4 }, hovertext: labels, hovertemplate: '%{hovertext}<extra></extra>', name: 'Documents' }
          : { type: 'scatter', mode: 'markers', x: r.term_vectors[j + 1], y: r.term_vectors[i], rows: tRows, marker: { size: 4, color: SM.report.BASE }, hovertext: tHover, hovertemplate: '%{hovertext}<extra></extra>', name: 'Terms' };
        t.xaxis = `x${q === 1 ? '' : q}`;
        t.yaxis = `y${q === 1 ? '' : q}`;
        traces.push(t);
      }
    }
    const side = Math.max(120, Math.min(170, Math.floor(620 / Cn)));
    const W = 58 + 58 + side * Cn, H = 44 + 48 + side * R;
    so.add(withCode(ctx.plot(traces, layout, { width: W, height: H, title: `SVD scatterplot matrix of ${S.col.name}` }), ctx.code(spmCode(r, m, W, H))),
      ctx.note(`The first ${m} singular vectors: below the diagonal (shaded orange) the documents' coordinates U S, one pair of vectors in each panel; above it (shaded blue) the terms' V S, the pair shifted by one, as JMP arranges it. Click or drag in any panel to select rows: a document's rows, or the rows that hold a term.`),
);
  }

  function spmCode(r, m, W, H) {
    return [r.svd_head, '',
      `m = ${m}   # the size: the first m singular vectors`,
      `fig, axes = plt.subplots(m, m - 1, figsize=(${W / 100}, ${H / 100}), squeeze=False, layout="constrained")`,
      'for i in range(m):',
      '    for j in range(m - 1):',
      '        ax = axes[i, j]',
      '        if j < i:   # below the diagonal: the documents, Doc Vec j+1 across, Doc Vec i+1 up',
      `            ax.scatter(docs[:, j], docs[:, i], s=${area(r.doc_rows.length > 2000 ? 3 : 4)}, color="${BASE}", linewidths=0)`,
      '            ax.set_facecolor("#fbf1e6")',
      '        else:   # above: the terms, Term Vec j+2 across, Term Vec i+1 up',
      `            ax.scatter(terms[:, j + 1], terms[:, i], s=${area(4)}, color="${BASE}", linewidths=0)`,
      '            ax.set_facecolor("#edf1f5")',
      `        ax.axhline(0, color="${ZERO}", linewidth=0.72, zorder=0)`, `        ax.axvline(0, color="${ZERO}", linewidth=0.72, zorder=0)`,
      '        ax.tick_params(labelsize=6.5)',
      '        if i == m - 1: ax.set_xlabel(f"Doc Vec{j + 1}")',
      '        if j == 0 and i > 0: ax.set_ylabel(f"Doc Vec{i + 1}")',
      '        if i == 0: ax.set_title(f"Term Vec{j + 2}", fontsize=8)',
      '        if j == m - 2 and i < m - 1: ax.yaxis.set_label_position("right"); ax.set_ylabel(f"Term Vec{i + 1}")',
      'fig.suptitle("SVD Scatterplots of Document and Term Spaces", fontsize=9)',
      'plt.show()'].join('\n');
  }

  async function spmDialog(ctx, col, kmax) {
    const sc = col.id;
    const most = Math.max(2, Math.min(kmax || 8, 8));
    const v = await SM.ui.form({ title: 'SVD Scatterplot Matrix', info: 'p:text:spm', fields: [{ key: 'm', label: 'Number of singular vectors', type: 'number', value: Math.min(4, most),
      help: `The size of the matrix: the first this many singular vectors, from 2 to ${most} (4 by default). Documents are plotted below the diagonal, terms above it.` }],
      validate: (x) => (Number.isInteger(x.m) && x.m >= 2 && x.m <= most ? null : `A whole number from 2 to ${most}`) });
    if (v) ctx.set('spm', v.m, sc);
  }

  /* ---- Term Selection (JMP Pro) -------------------------------------------------------------------------------------- */
  const tsArgs = (ctx, S, spec) => ({ ...S.args, response: (ctx.col(spec.response) || {}).name || null, target: spec.target, weighting: spec.weighting, min_freq: spec.minFreq,
    max_terms: spec.maxTerms, early: spec.early, seed: SM.predict.seed(ctx) });

  async function termselOutline(ctx, S, parent, spec) {
    const sc = S.col.id;
    const ycol = ctx.col(spec.response);
    let r = null;
    const ob = ctx.outline('Term Selection', { parent, key: K(S, 'termsel'), info: 'p:text:termsel', menu: () => [
      { label: 'Specifications…', action: () => termselDialog(ctx, S) },
      { label: 'Target Level', disabled: !r || r.family !== 'binomial', submenu: () => (r && r.levels ? r.levels.map((l) => ({ label: l, checked: l === r.target, action: () => ctx.set('termsel', { ...spec, target: l }, sc) })) : []) },
      { label: 'Save Document Scores', disabled: !r || !!r.error, action: () => saveTermScores(ctx, S, r) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('termsel', null, sc) },
    ] });
    if (!ycol) { ob.add(ctx.warn('The response column of Term Selection is not in the table: choose one (Specifications).')); return; }
    r = await ctx.call('text.termsel', tsArgs(ctx, S, spec));
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const bin = r.family === 'binomial';
    ob.add(wide(ctx.kv([['Response', bin ? `${r.response} = ${r.target}` : r.response], ['Distribution', bin ? 'Binomial' : 'Normal'], ['Estimation Method', `Elastic Net (α ${r.alpha})`],
      ['Validation Method', `AICc${r.early ? ', early stopping' : ''}`], ['Documents', r.n_docs], ['Terms in the DTM', r.n_terms], ['Terms Selected', r.terms.length], ['AICc', fmt(r.aicc, { sig: 7 })],
      ['Tuning Parameter λ', fmt(r.lambda, { sig: 5 })]])),
    ctx.note(`An elastic net of ${bin ? `the log-odds of ${r.response} = ${r.target} against the rest` : r.response} on the ${labelOf(WEIGHTINGS, r.weighting)} document term matrix (the terms seen ${r.min_freq} or more times, at most ${fmt(r.max_terms)}), each term scaled by its standard deviation: ${r.steps} of 150 penalties from ${fmt(r.lam_max, { sig: 4 })} down${r.early ? ' (stopped when ten in a row did not improve the AICc)' : ''}, the smallest AICc kept.`));
    const to = ctx.outline('Term Scores', { parent: ob, key: K(S, 'tsterms') });
    if (!r.terms.length) to.add(ctx.note('No term enters the model with the smallest AICc: the terms do not explain the response.'));
    else {
      to.add(el('div', { class: 'sm-tx-list' }, ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'coef', label: 'Coefficient', digits: 4 }, { key: 'logworth', label: 'LogWorth', digits: 3 },
        { key: 'count', label: 'Count', fmt: 'int' }, { key: 'cases', label: 'Cases', fmt: 'int', hidden: true, title: 'the documents that hold the term' }], rows: r.terms },
      { key: K(S, 'tsterms'), maxRows: 1000, onRow: (row, ev) => pick(ctx, S, 'term', row.term, ev) })));
      if (!ctx.headless) {
        const top = r.terms.slice().sort((a, b) => Math.abs(b.coef) - Math.abs(a.coef)).slice(0, 30).reverse();
        const H = Math.max(160, 16 * top.length + 60);
        to.add(withCode(ctx.plot([{ type: 'bar', orientation: 'h', x: top.map((x) => x.coef), y: top.map((x) => T(x.term)), rows: top.map((x) => termRows(S, x.term)),
          marker: { color: top.map((x) => (x.coef > 0 ? SM.report.BASE : '#b0413e')) }, hovertemplate: '%{y}: %{x:.4g}<extra></extra>' }],
        { margin: { l: 110, r: 14, t: 8, b: 40 }, xaxis: { title: { text: 'Coefficient' }, zeroline: true }, yaxis: { automargin: true, tickfont: { size: 10 } }, bargap: 0.25 },
        { width: 440, height: H, title: `Term coefficients${bin ? ` (${r.response} = ${r.target})` : ` (${r.response})`}`, rowColors: false }), ctx.code((r.plot_code || {}).bars)));
      }
      to.add(ctx.note(`The terms the model keeps, the largest coefficient first: its change in ${bin ? 'the log-odds' : r.response} for one unit of the term's ${labelOf(WEIGHTINGS, r.weighting)} value (1: the document holds it, with Binary). LogWorth: −log10 of the term's Wald p-value, its standard error from the Hessian of the penalized likelihood on the kept terms; it does not allow for the selection (optimistic).${r.note ? ` ${r.note}` : ''} Click a term to select its rows.`));
    }
    const dso = ctx.outline('Document Scores', { parent: ob, key: K(S, 'tsdocs'), closed: true });
    const D = r.docs;
    const rows = D.rows.map((rs, d) => ({ doc: S.res.id ? String(r.doc_labels[d]) : `row ${rs[0] + 1}`, pos: D.positive[d], neg: D.negative[d], pred: D.predicted[d], act: D.actual[d], rs }));
    dso.add(el('div', { class: 'sm-tx-list sm-tx-wide' }, ctx.rt({ columns: [{ key: 'doc', label: S.res.id || 'Row', fmt: 'text' }, { key: 'pos', label: 'Positive Contribution', digits: 4 }, { key: 'neg', label: 'Negative Contribution', digits: 4 },
      { key: 'pred', label: bin ? `Prob(${r.target})` : 'Predicted', digits: 4 }, { key: 'act', label: bin ? `Is ${r.target}` : 'Actual', digits: bin ? 0 : 4 }], rows }, { key: K(S, 'tsdocs'), maxRows: 1000, onRow: (row, ev) => selectRows(ctx, row.rs, ev) })),
    ctx.note(`Each document's sum of its terms' positive and negative contributions (coefficient × value), and the model's ${bin ? 'probability of the target level' : 'prediction'}; the intercept is ${fmt(r.intercept, { sig: 5 })}.`));
    ob.add(ctx.code(r.code));
  }

  async function termselDialog(ctx, S) {
    const sc = S.col.id;
    const cur = { ...TS_DEFAULT, ...(ctx.opt('termsel', null, sc) || {}) };
    const idc = ctx.role('id');
    const cols = ctx.table.columns.filter((c) => c.id !== S.col.id && (!idc || c.id !== idc.id) && !(c.dataType === 'character' && c.modelingType === 'ordinal'));
    if (!cols.length) { SM.ui.toast('The table has no other column to explain', { error: true }); return; }
    const v = await SM.ui.form({
      title: 'Term Selection', info: 'p:text:termsel',
      lead: 'Which terms explain a response: a penalized regression (elastic net) of the response on the document term matrix, as JMP Pro\'s Term Selection runs Generalized Regression.',
      fields: [
        { key: 'response', label: 'Response', type: 'select', value: cur.response && cols.some((c) => c.id === cur.response) ? cur.response : cols[0].id, choices: cols.map((c) => [c.id, c.name]),
          help: 'The column to explain. A nominal one: a logistic model of one level (the Target Level, the first by default; the red triangle changes it) against the rest. A continuous one, or an ordinal numeric one: a normal model of its values. With an ID, a document takes the value of its first row that has one.' },
        { key: 'weighting', label: 'Weighting', type: 'select', value: cur.weighting, choices: WEIGHTINGS, help: 'The value of each term in each document (Binary by default: 1 when it holds the term), as the document term matrix weighs it.' },
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: cur.maxTerms, help: `${HELP.maxTerms} 1000 by default.` },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: cur.minFreq, help: 'Only terms seen at least this many times become predictors (10 by default, as JMP: rarer terms are left out).' },
        { key: 'early', label: 'Early Stopping', type: 'check', value: cur.early, help: 'On (the default, as JMP): the path stops once ten penalties in a row fail to improve the AICc (not before four terms are in). Off: all 150 penalties are fitted.' },
      ],
      validate: specError,
    });
    if (!v) return;
    const y = ctx.col(v.response);
    let target = cur.response === v.response ? cur.target : null;
    if (y && y.modelingType === 'nominal') {
      const lv = ctx.table.levels(y).map((l) => String(l));   // as the engine names a level: 2 for 2.0, the text as it is
      if (!lv.includes(target)) target = lv[0] ?? null;
    } else target = null;
    ctx.set('termsel', { response: v.response, target, weighting: v.weighting, maxTerms: v.maxTerms, minFreq: v.minFreq, early: !!v.early }, sc);
  }

  function saveTermScores(ctx, S, r) {
    if (!r || r.error) return;
    const D = r.docs;
    const rows = [], out = { pos: [], neg: [], pred: [] };
    D.rows.forEach((rs, d) => { for (const x of rs) { rows.push(x); out.pos.push(D.positive[d]); out.neg.push(D.negative[d]); out.pred.push(D.predicted[d]); } });
    const what = r.family === 'binomial' ? `${r.response} = ${r.target}` : r.response;
    ctx.saveColumn('Positive Contribution', { rows, values: out.pos }, { notes: fromNote(ctx, `Term Selection of ${what} on ${S.col.name}: the positive terms' contribution`) });
    ctx.saveColumn('Negative Contribution', { rows, values: out.neg }, { notes: fromNote(ctx, `Term Selection of ${what} on ${S.col.name}: the negative terms' contribution`) });
    ctx.saveColumn(r.family === 'binomial' ? `Prob[${r.target}]` : `Predicted ${r.response}`, { rows, values: out.pred }, { notes: fromNote(ctx, `Term Selection of ${what} on ${S.col.name}: the prediction`) });
  }

  /* ---- Sentiment Analysis: VADER (vaderSentiment, MIT), fetched from PyPI when first used -------------------------- */
  // Code fetched at run time is pinned by hash: the one wheel of release
  // 3.3.2 (pure Python, uploaded 2020-05-22), checked against the sha256
  // PyPI gives for it before micropip installs it from the worker's files.
  const VADER_WHEEL = {
    url: 'https://files.pythonhosted.org/packages/76/fc/310e16254683c1ed35eeb97386986d6c00bc29df17ce280aed64d55537e9/vaderSentiment-3.3.2-py2.py3-none-any.whl',
    sha256: '3bf1d243b98b1afad575b9f22bc2cb1e212b94ff89ca74f8a23a588d024ea311',
  };
  let vaderReady = null;
  function installVader() {
    if (!vaderReady) {
      const file = `/tmp/${VADER_WHEEL.url.split('/').pop()}`;
      const code = ['import hashlib, micropip', 'from pyodide.http import pyfetch',
        `_r = await pyfetch(${JSON.stringify(VADER_WHEEL.url)})`,
        'if not _r.ok: raise OSError(f"HTTP {_r.status}")',
        '_b = await _r.bytes()',
        `if hashlib.sha256(_b).hexdigest() != ${JSON.stringify(VADER_WHEEL.sha256)}: raise ValueError("the file is not the wheel whose sha256 this page pins")`,
        `with open(${JSON.stringify(file)}, "wb") as _f: _f.write(_b)`,
        `await micropip.install(${JSON.stringify(`emfs:${file}`)}, deps=False)`,
        'import vaderSentiment.vaderSentiment'].join('\n');
      vaderReady = SM.engine.runCell('smui-sentiment', code, { label: 'sentiment', fresh: true })
        .then((res) => { const err = (res.outputs || []).find((x) => x.type === 'error'); if (err) throw new Error(`${err.ename}: ${err.evalue}`); return true; })
        .catch((e) => { vaderReady = null; throw e; });
    }
    return vaderReady;
  }

  async function sentimentOutline(ctx, S, parent) {
    const sc = S.col.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    let r = null;
    const ob = ctx.outline('Sentiment Analysis', { parent, key: K(S, 'sentiment'), info: 'p:text:sentiment', menu: () => [
      { label: 'Display Options', submenu: () => [ctx.check('Sentiment Terms', 'seTerms', sc, true), ctx.check('Negation Terms', 'seNeg', sc, false), ctx.check('Intensifier Terms', 'seInt', sc, false), ctx.check('Document Scores', 'seDocs', sc, false)] },
      { label: 'Save Document Scores', disabled: !r || !!r.error, action: () => saveSentiment(ctx, S, r) },
      { separator: true },
      { label: 'Remove', action: () => ctx.set('sentiment', false, sc) },
    ] });
    r = await ctx.call('text.sentiment', { ...S.args });
    if (r.missing && !ctx.headless) {
      const note = el('p', { class: 'sm-ob-note', role: 'status', text: 'Fetching vaderSentiment (MIT) from PyPI: its lexicon comes with it and is not part of this site…' });
      ob.add(note);
      try { await installVader(); } catch (e) { note.remove(); ob.add(ctx.warn(`vaderSentiment could not be installed from PyPI (${e.message}): Sentiment Analysis needs it, and the network.`)); return; }
      note.remove();
      r = await ctx.call('text.sentiment', { ...S.args, fetched: 1 });
    }
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const D = r.docs;
    const sm = r.summary;
    const cls = (v) => (v >= 0.05 ? 0 : v <= -0.05 ? 2 : 1);
    const byClass = [[], [], []];
    D.compound.forEach((v, d) => byClass[cls(v)].push(...D.rows[d]));
    ob.add(wide(ctx.rt({ columns: [{ key: 'k', label: 'Documents', fmt: 'text' }, { key: 'n', label: 'Count', fmt: 'int' }, { key: 'p', label: 'Portion', digits: 4 }, { key: 'm', label: 'Mean Compound', digits: 4 }],
      rows: [{ k: 'Positive (compound ≥ 0.05)', n: sm.positive, p: sm.positive / r.n_docs, m: sm.mean_pos, c: 0 }, { k: 'Neutral', n: sm.neutral, p: sm.neutral / r.n_docs, m: null, c: 1 },
        { k: 'Negative (compound ≤ −0.05)', n: sm.negative, p: sm.negative / r.n_docs, m: sm.mean_neg, c: 2 }, { k: 'All', n: r.n_docs, p: 1, m: sm.mean, c: 3 }] },
    { key: K(S, 'sesummary'), sortable: false, caption: 'Summary', onRow: (row, ev) => selectRows(ctx, row.c === 3 ? D.rows.flat() : byClass[row.c], ev) })));
    if (!ctx.headless) {
      const edges = Array.from({ length: 21 }, (_, i) => -1 + 0.1 * i);
      const bins = Array.from({ length: 20 }, () => []), counts = Array.from({ length: 20 }, () => 0);
      D.bin.forEach((b, d) => { bins[b].push(...D.rows[d]); counts[b]++; });   // the engine's bins, as the code's np.histogram
      ob.add(withCode(ctx.plot([{ type: 'bar', x: edges.slice(0, 20).map((e) => e + 0.05), y: counts, width: 0.094, rows: bins, marker: { color: SM.report.BAR },
        hovertemplate: '%{x:.2f}: %{y} documents<extra></extra>' }], { xaxis: { title: { text: 'Compound score' }, range: [-1, 1] }, yaxis: { title: { text: 'Documents' } }, margin: { l: 50, r: 10, t: 8, b: 44 } },
      { width: 440, height: 280, title: 'Sentiment of the documents' }), ctx.code((r.plot_code || {}).hist)));
    }
    ob.add(ctx.note(`VADER (Hutto and Gilbert 2014; vaderSentiment ${r.version || ''}, ${fmt(r.lexicon_size)} lexicon terms) scores each of the ${fmt(r.n_docs)} documents${S.res.id ? ` (the texts of the rows with the same ${S.res.id})` : ''}: every word of its lexicon adds its valence, reversed and weakened after a negation (not, never, n't), raised or lowered by an intensifier (very, slightly), by capitals and by '!', and the clause after 'but' weighs more; compound is the sum scaled to −1 to 1. Positive from 0.05, negative from −0.05 (VADER's thresholds). English only. Click a class or a bar to select its rows.`));
    const termTable = (list, key, title, extra, open) => {
      const to = ctx.outline(title, { parent: ob, key: K(S, key), closed: !open });
      if (!list.length) { to.add(ctx.note('None in these texts.')); return; }
      to.add(el('div', { class: 'sm-tx-list' }, ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, ...extra, { key: 'count', label: 'Count', fmt: 'int' }, { key: 'docs', label: 'Documents', fmt: 'int' }], rows: list },
        { key: K(S, key), maxRows: 1000, onRow: (row, ev) => selectRows(ctx, row.d.flatMap((d) => D.rows[d]), ev) })));
    };
    if (o('seTerms', true)) termTable(r.lexicon, 'seterms', 'Sentiment Terms', [{ key: 'score', label: 'Score', digits: 2, title: 'VADER\'s valence, from −4 (most negative) to 4' }], true);
    if (o('seNeg', false)) termTable(r.negations, 'seneg', 'Negation Terms', [], true);
    if (o('seInt', false)) termTable(r.intensifiers, 'seint', 'Intensifier Terms', [{ key: 'multiplier', label: 'Boost', digits: 3, title: 'what VADER adds to (or takes from) the size of the next sentiment word\'s valence' }], true);
    if (o('seDocs', false)) {
      const dso = ctx.outline('Document Scores', { parent: ob, key: K(S, 'sedocs') });
      const rows = D.rows.map((rs, d) => ({ doc: S.res.id ? String(r.doc_labels[d]) : `row ${rs[0] + 1}`, pos: D.pos[d], neu: D.neu[d], neg: D.neg[d], comp: D.compound[d], rs }));
      dso.add(el('div', { class: 'sm-tx-list sm-tx-wide' }, ctx.rt({ columns: [{ key: 'doc', label: S.res.id || 'Row', fmt: 'text' }, { key: 'pos', label: 'Positive', digits: 3 }, { key: 'neu', label: 'Neutral', digits: 3 }, { key: 'neg', label: 'Negative', digits: 3 }, { key: 'comp', label: 'Compound', digits: 4 }], rows },
        { key: K(S, 'sedocs'), maxRows: 1000, onRow: (row, ev) => selectRows(ctx, row.rs, ev) })));
    }
    ob.add(ctx.code(r.code));
  }

  function saveSentiment(ctx, S, r) {
    if (!r || r.error) return;
    const D = r.docs;
    for (const [key, name] of [['pos', 'Positive'], ['neu', 'Neutral'], ['neg', 'Negative'], ['compound', 'Compound']]) {
      const rows = [], vals = [];
      D.rows.forEach((rs, d) => { for (const x of rs) { rows.push(x); vals.push(D[key][d]); } });
      ctx.saveColumn(`Sentiment ${name}`, { rows, values: vals }, { notes: fromNote(ctx, `VADER's ${name.toLowerCase()} ${key === 'compound' ? 'score (−1 to 1)' : 'share of the text'} of ${S.col.name}`) });
    }
  }

  /* ---- Save Stacked DTM for Association: a row per document and term ------------------------------------------------ */
  function saveStacked(ctx, col) {
    const S = peek(ctx, col);
    if (!S || !S.res) { SM.ui.toast('The report is not drawn yet', { error: true }); return; }
    const idc = ctx.role('id');
    const ids = [], terms = [];
    const missing = (v) => v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
    S.res.terms.forEach((t, i) => {
      const seen = new Set();
      for (const r of S.res.term_rows[i]) {
        const d = idc ? idc.values[r] : r + 1;
        if (missing(d) || seen.has(d)) continue;
        seen.add(d);
        ids.push(d);
        terms.push(t.term);
      }
    });
    const num = !idc || idc.isNumeric;
    const order = ids.map((_, k) => k).sort((a, b) => (num ? ids[a] - ids[b] : SM.table.collator.compare(String(ids[a]), String(ids[b]))) || a - b);
    const idName = idc ? idc.name : 'Row';
    const t = new SM.Table({
      name: SM.app.uniqueTableName(`${col.name} stacked DTM`), source: `saved from ${ctx.report.title}`,
      notes: `A row for each document of ${col.name} and each term it holds (${idc ? `the documents of ${idc.name}` : 'each row a document'}): the stacked document term matrix, for Association Analysis (Analyze > Screening; Item: Term, ID: ${idName}).`,
      columns: [{ name: idName, dataType: num ? 'numeric' : 'character', modelingType: 'nominal', values: order.map((k) => ids[k]) }, { name: 'Term', dataType: 'character', values: order.map((k) => terms[k]) }],
    });
    SM.app.addTable(t);
    SM.ui.toast(`Made the table ${t.name}: ${fmt(t.nrows)} rows, for Association Analysis`);
  }

  /* ---- Select Contains, Select Contained, Containing Phrases ----------------------------------------------------------- */
  const wordsOf = (p) => p.split(' ');
  const inside = (small, big) => { const a = wordsOf(small), b = wordsOf(big); for (let i = 0; i + a.length <= b.length; i++) if (a.every((w, k) => b[i + k] === w)) return true; return false; };
  /* A term's words: the term itself and the words behind it (a stem's, a recode's). */
  const termWords = (S, t) => new Set([t, ...((S.res.forms[t] || []).map((f) => f[0]))]);
  function selectContains(ctx, S, phrases) {
    const out = S.res.phrases.map((x) => x.phrase).filter((p) => phrases.some((q) => q !== p && inside(q, p)));
    S.chosenPhrases = new Set(out);
    S.chosen.clear();
    markChosen(S);
    ctx.table.select(rowsFor(S));
    SM.ui.toast(`${out.length} longer phrase${out.length === 1 ? '' : 's'} contain${out.length === 1 ? 's' : ''} ${phrases.length === 1 ? `"${phrases[0]}"` : 'them'}`);
  }
  function selectContained(ctx, S, phrases) {
    const sub = S.res.phrases.map((x) => x.phrase).filter((p) => phrases.some((q) => q !== p && inside(p, q)));
    const words = new Set(phrases.flatMap(wordsOf));
    const terms = S.res.terms.map((x) => x.term).filter((t) => [...termWords(S, t)].some((w) => words.has(w)));
    S.chosenPhrases = new Set(sub);
    S.chosen = new Set(terms);
    markChosen(S);
    ctx.table.select(rowsFor(S));
    SM.ui.toast(`${sub.length} shorter phrase${sub.length === 1 ? '' : 's'} and ${terms.length} term${terms.length === 1 ? '' : 's'} inside ${phrases.length === 1 ? `"${phrases[0]}"` : 'them'}`);
  }
  function containingPhrases(ctx, S, terms) {
    const words = new Set(terms.flatMap((t) => [...termWords(S, t)]));
    const out = S.res.phrases.map((x) => x.phrase).filter((p) => wordsOf(p).some((w) => words.has(w)));
    S.chosenPhrases = new Set(out);
    markChosen(S);
    ctx.table.select(rowsFor(S));
    SM.ui.toast(`${out.length} phrase${out.length === 1 ? '' : 's'} contain${out.length === 1 ? 's' : ''} ${terms.length === 1 ? `"${terms[0]}"` : 'the terms'}`);
  }

  /* ---- Save ------------------------------------------------------------------------------------------------------------- */
  const fromNote = (ctx, what) => `${what}, from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`;

  async function saveVectors(ctx, S, kind, spec) {
    let count = kind === 'svd' ? Math.min(spec.k, 10) : spec.k;
    if (kind === 'svd') {
      const v = await SM.ui.form({ title: 'Save Document Singular Vectors', info: 'p:text:lsa', fields: [{ key: 'n', label: 'Number of singular vectors to save', type: 'number', value: count, help: 'How many of the documents\' singular vectors (U S), the first ones, to add to the table as columns Doc Vec1, Doc Vec2, …, from 1 up to the number computed; every row of a document gets its value.' }], validate: (x) => (Number.isInteger(x.n) && x.n >= 1 && x.n <= 1000 ? null : 'A whole number from 1 to 1000') });
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
        { key: 'which', label: 'Terms', type: 'select', value: chosen.length ? 'chosen' : 'top', choices: [...(chosen.length ? [['chosen', `The ${chosen.length} terms chosen in the Term List`]] : []), ['top', 'The most frequent terms']],
          help: 'The terms chosen in the Term List (when some are; the two fields below are then not used), or the most frequent terms, as many as the two fields below allow.' },
        { key: 'maxTerms', label: 'Maximum Number of Terms', type: 'number', value: 100, help: 'With the most frequent terms: at most this many columns, from 1 to 100 000 (100).' },
        { key: 'minFreq', label: 'Minimum Term Frequency', type: 'number', value: 1, help: 'With the most frequent terms: only terms seen at least this many times (1: every term).' },
        { key: 'weighting', label: 'Weighting', type: 'select', value: 'binary', choices: WEIGHTINGS, help: 'The value of each cell: Binary (the default: 1 when the document holds the term, a 0/1 indicator for modeling), Ternary, Frequency, Log Freq or TF IDF, as Latent Semantic Analysis weighs them.' },
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
    const v = await SM.ui.form({ title: `${cfg.title}: ${col.name}`, info: 'p:text:manage', lead: cfg.lead, fields: [{ key: 'text', label: cfg.title.replace('Manage ', ''), type: 'textarea', value: cfg.value, help: HELP.manage[key] }] });
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
        { label: 'Stemmer', submenu: () => STEMMERS.map(([v, l]) => ({ label: l, checked: o('stemmer', 'snowball') === v, action: () => ctx.set('stemmer', v, sc) })) },
      ] },
      { label: 'Display Options', submenu: () => [
        ctx.check('Summary Counts Table', 'summary', sc, true),
        ctx.check('Term and Phrase Lists', 'lists', sc, true),
        ctx.check('Show Word Cloud', 'cloud', sc, false),
        ctx.check('Show Stem Report', 'stemReport', sc, false, { disabled: o('stemming', 'none') === 'none' }),
        ctx.check('Show Stop Words, Recodes and Phrases', 'stopList', sc, false),
      ] },
      { separator: true },
      { label: 'Latent Class Analysis…', checked: !!o('lca', null), action: () => lcaDialog(ctx, col) },
      { label: 'Latent Semantic Analysis, SVD…', checked: !!o('lsa', null), action: () => lsaDialog(ctx, col) },
      { label: 'Topic Analysis, Rotated SVD…', checked: !!o('topics', null), action: () => topicDialog(ctx, col) },
      { label: 'Term Selection…', checked: !!o('termsel', null), action: () => { const S = peek(ctx, col); if (S && S.res) termselDialog(ctx, S); } },
      ctx.check('Sentiment Analysis', 'sentiment', sc, false),
      { separator: true },
      { label: 'Save Document Term Matrix…', action: () => saveDtm(ctx, col) },
      { label: 'Save Stacked DTM for Association', action: () => saveStacked(ctx, col) },
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
      helpHeading: 'Customize Regex',
      help: [
        ['Customize Regex', 'Tokenize with your own regular expression instead of the built-in patterns. It is for the Regex tokenizer: with Basic Words it is ignored.'],
        ['Regular expression', 'A Python regular expression (the re module\'s syntax): every match in the lowercase text is a token. [a-z]+ takes letters only, \\S+ everything between spaces. It must compile; the built-in patterns\' clean-up (a possessive \'s dropped, a URL\'s last full stop) is not applied to its matches.'],
      ],
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
     THE LAUNCH'S ROLES AND OPTIONS, with what each is for (the (i))
     ====================================================================== */
  const ROLES = [
    { key: 'text', label: 'Text Columns', min: 1, types: ['nominal', 'ordinal'], hint: 'required: character columns', info: 'p:text',
      help: 'One or more character columns of text: each gets an explorer of its own (with several, an outline each). A numeric column cannot be one (right click it to make it character).' },
    { key: 'id', label: 'ID', max: 1, hint: 'optional: the rows of an ID are one document',
      help: 'Optional: the rows that share an ID are one document (a case), their texts taken together, and rows with no ID are left out. Without it every row is a document of its own.' },
    { key: 'by', label: 'By', hint: 'optional', help: 'A separate analysis for each level of the By column (each combination of levels, with several). Rows with a missing By value are left out.' },
  ];
  const OPTIONS = [
    { key: 'language', label: 'Language', type: 'select', value: 'english', choices: [['english', 'English']],
      help: 'English, the one language here: the stop words (scikit-learn\'s ENGLISH_STOP_WORDS), the stemmers and the sentiment lexicon are English.' },
    { key: 'maxWords', label: 'Maximum Words per Phrase', type: 'number', value: 4,
      help: 'The longest phrase the Phrase List counts, from 1 to 12 words (4): a phrase is a run of 2 up to this many tokens of one text, seen at least twice, that neither begins nor ends with a stop word. 1 makes no phrases.' },
    { key: 'maxPhrases', label: 'Maximum Number of Phrases', type: 'number', value: 5000,
      help: 'How many phrases the Phrase List keeps, the most frequent first, from 0 to 100 000 (5000, JMP\'s default); 0 keeps none.' },
    { key: 'minChars', label: 'Minimum Characters per Word', type: 'number', value: 1,
      help: 'Tokens shorter than this are left out, from 1 to 1000 (1): 2 drops one-letter words and single digits.' },
    { key: 'maxChars', label: 'Maximum Characters per Word', type: 'number', value: 50,
      help: 'Tokens longer than this are left out, from 1 to 100 000 (50, JMP\'s default), which drops long strings such as codes; at least the minimum.' },
    { key: 'stemming', label: 'Stemming', type: 'select', value: 'none', choices: STEMMING,
      help: 'No Stemming (the default): every word its own term. Stem for Combining: the words that share a stem with another word become one term, marked with a dot (return·), and a word alone keeps its form. Stem All Terms: every word of three or more letters a to z becomes its stem. The Stem Report (Display Options) shows the words behind each stem.' },
    { key: 'stemmer', label: 'Stemmer', type: 'select', value: 'snowball', choices: STEMMERS,
      help: 'The stemming algorithm when Stemming is on: Snowball\'s English stemmer (Porter2, the default: the one JMP uses) or Porter\'s original 1980 algorithm, which stems a little more (it also shortens -ly and some -er words differently). Both are written here.' },
    { key: 'tokenizing', label: 'Tokenizing', type: 'select', value: 'regex', choices: TOKENIZING,
      help: 'How the lowercase text is cut into tokens. Regex (the default): built-in patterns for URLs, e-mail addresses, numbers such as 3.5 or 25%, and words with inner apostrophes and hyphens such as don\'t and well-known, a possessive \'s dropped; or your own pattern (Customize Regex). Basic Words: runs of letters and digits.' },
  ];

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:text': {
      kicker: 'Analyze', title: 'Text Explorer',
      lead: 'The words of a column of text: each text is split into tokens, the tokens that are not stop words become terms (stemmed and recoded as you choose), and the terms are counted, listed, drawn as a word cloud, reduced by a singular value decomposition into latent dimensions and topics, clustered, related to a response and scored for sentiment. The counting is scikit-learn\'s CountVectorizer; its English stop words; the SVD TruncatedSVD or PCA; the stemmer Snowball\'s English (Porter2) algorithm, as JMP\'s, or Porter\'s of 1980, both written here.',
      sections: [
        { heading: 'Roles', choices: [['Text Columns', 'One or more character columns; each gets an analysis of its own.'], ['ID', 'Optional: the rows that share an ID are one document (a case), their texts together.'], ['By', 'A separate analysis for each level.']] },
        // the launch's options (Stemming is in the red triangle too)
        { heading: 'Options', choices: OPTIONS.map((o) => [o.label, o.help]) },
        { heading: 'Differences from JMP', text: 'JMP\'s stop word list and its built-in regular expressions are its own; here the stop words are scikit-learn\'s ENGLISH_STOP_WORDS and the patterns are the ones above. The Word Cloud starts hidden, as in JMP (Display Options). The stemmer is Snowball\'s English (Porter2) as Snowball 1 and 2 define it, JMP\'s choice; Porter\'s 1980 algorithm is offered too (Stemmer). Recodes apply after stemming here, before it in JMP. Latent Class Analysis is a Bernoulli mixture fitted here by EM from five random starts, so its clusters differ from JMP\'s own sparse algorithm\'s; Term Selection is an elastic net chosen by AICc along 150 penalties, as JMP\'s Generalized Regression defaults, its degrees of freedom the number of kept terms and its LogWorths Wald tests on the kept terms; Sentiment Analysis is VADER (its lexicon and rules), not JMP\'s own lexicon, scored from −1 to 1.' },
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
        { heading: 'Show Text', choices: [['Select These Rows', 'Selects every row the dialog lists, the ones beyond the first 500 shown too.'], ['Close', 'Closes the dialog; the selection stays as it is.']] },
        { heading: 'Selecting by containment', choices: [['Containing Phrases (a term)', 'Selects the phrases of the Phrase List that hold the term (one of its words, or of the words behind a stem).'], ['Select Contains (a phrase)', 'Selects the longer phrases that hold the phrase.'], ['Select Contained (a phrase)', 'Selects the shorter phrases inside the phrase and the terms of its words.']] },
      ],
      more: MORE,
    },
    'p:text:cloud': {
      kicker: 'Text Explorer', title: 'Word Cloud',
      lead: 'The most frequent terms, each sized by its count (the font size grows with the square root of the count, so that a word\'s area follows its count). The layouts are JMP\'s: Ordered (the default) sets them in lines from the most frequent, Alphabetical in lines alphabetically, and Centered puts the largest in the middle and each next word on a spiral where it overlaps none. Click a word to select its rows.',
      sections: [{ heading: 'Coloring', choices: [['Uniform', 'The text colour.'], ['Arbitrary Grays, Arbitrary Colors', 'Colours that mean nothing, to tell neighbouring words apart.'], ['By Column', 'The mean of a numeric column (a rating) over the rows that hold each word: blue below the column\'s mean, red above.']] }],
      more: MORE,
    },
    'p:text:stems': {
      kicker: 'Text Explorer', title: 'Stem Report',
      lead: 'Each stemmed term and the words it stands for, with their counts. The stems are Snowball\'s English stemmer (Porter2, JMP\'s): suffixes taken off in steps within the regions R1 and R2 of the word, with its exceptional forms (sky, news, dying → die); or, with Stemmer: Porter (1980), Porter\'s algorithm as published. A word of one or two letters, or with characters other than a to z, is not stemmed.',
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
        { heading: 'Weighting (as JMP documents it)', choices: [['Binary', '1 when the term is in the document, else 0.'], ['Ternary', '2 when it is there more than once, 1 once, 0 not.'], ['Frequency', 'Its count.'], ['Log Freq', 'log10(1 + count).'], ['TF IDF', 'count × log10(documents / documents with the term), the default: the term frequency times the inverse document frequency, with the base-10 logarithm JMP\'s help gives.']] },
        { heading: 'Centering and Scaling', choices: [['Uncentered', 'scikit-learn\'s TruncatedSVD of the weighted matrix (arpack).'], ['Centered', 'Each term\'s mean taken away: scikit-learn\'s PCA, the SVD of the centered matrix computed without making the sparse matrix dense (the default here).'], ['Centered and Scaled', 'Each term also divided by its standard deviation.']] },
        { heading: 'What is shown', text: 'The report is titled as JMP titles it (SVD Centered and Scaled TF IDF). The documents\' coordinates U S and the terms\' V S on the first two vectors (as Deerwester et al. 1990 compare them), signed so that each vector\'s largest term coordinate is positive; then the singular values with the equivalent principal components\' eigenvalues (s² / (n − 1), uncentered s² / n) and each one\'s share of the matrix\'s sum of squares. Save Document Singular Vectors saves U S; Save Term Singular Vectors makes a table of V S.' },
        { heading: 'Its red triangle', choices: [['SVD Scatterplot Matrix', 'The first few vectors in pairs: documents below the diagonal, terms above.'], ['Cluster Terms, Cluster Documents', 'Ward\'s hierarchical clustering of the terms\' or the documents\' coordinates on the singular vectors; the clusters colour the SVD plots.']] },
        { heading: 'Defaults', text: 'TF IDF and Centered and Scaled (a PCA of the correlation matrix), as JMP\'s help gives them, and 100 singular vectors (cut to the matrix); terms seen 4 or more times, at most 1000, are chosen here.' },
        { heading: 'Differences from JMP', text: 'JMP\'s help says the matrix is also divided by nDoc − 1 (uncentered: nDoc) before the decomposition; the singular values here are those of the centered (and scaled) matrix itself, and the Eigenvalue column gives what that division makes of them. The percents do not depend on it.' },
      ],
      more: MORE,
    },
    'p:text:topics': {
      kicker: 'Text Explorer', title: 'Topic Analysis',
      lead: 'Topics as JMP makes them: the first k term coordinates of the SVD (V S) rotated by varimax (Kaiser 1958, with Kaiser\'s normalization, R\'s algorithm), so that each topic has a few terms with large loadings. The loadings are V S R/√(n − 1) (with centering, the covariances of the terms with the topics); the scores √(n − 1) U R, so that scores times loadings give the SVD\'s rank-k fit.',
      sections: [
        { heading: 'Other methods (scikit-learn)', choices: [['Non-negative Matrix Factorization', 'NMF: the weighted matrix as documents × topics times topics × terms, all non-negative (init nndsvda).'], ['Latent Dirichlet Allocation', 'LDA: a probability model of the counts; each topic a distribution over the terms, each document a mix of topics.']] },
        { heading: 'Seeds', text: 'NMF and LDA start from the report\'s random seed, kept with the report, so a redraw, a project and the Python code give the same topics.' },
        { heading: 'Clicking', choices: [['A term in Top Loadings by Topic', 'Selects the rows that hold it, as a click in the Term List does (shift adds, ctrl/⌘ toggles).'], ['The Topic Scores plot', 'Click or drag over documents to select their rows.']] },
      ],
      more: MORE,
    },
    'p:text:dtm': {
      kicker: 'Text Explorer', title: 'Save Document Term Matrix',
      lead: 'A new column for each term (the terms chosen in the Term List, or the most frequent), named by the term: its weighted count in each row\'s document (every row of an ID gets its document\'s value). Binary gives 0/1 indicator columns for modeling. Save Stacked DTM for Association makes a new table instead, a row for each document and term it holds, for Association Analysis (Item: Term, ID: the document).',
      more: MORE,
    },
    'p:text:lca': {
      kicker: 'Text Explorer', title: 'Latent Class Analysis',
      lead: 'Clusters the documents by which terms they hold: a mixture of classes in which a document of class c holds term t with probability p(t, c), each term independently (a Bernoulli mixture of the binary document term matrix), fitted by EM from five random starts drawn from the report\'s seed (the best kept). Each probability has a weak Beta prior (0.01 of a document either way), so none is 0 or 1. BIC = −2 log L + (k − 1 + k × terms) log n: the smaller, the better, to compare numbers of clusters.',
      sections: [
        { heading: 'The report', choices: [['Cluster Mixture Probabilities', 'Each cluster\'s share of the documents; click one to select its documents\' rows.'], ['Term Probabilities by Cluster', 'p(t, c) for each term, with the cluster where it occurs most (Most Characteristic) and where a document that holds it most likely belongs (Most Probable).'], ['Top Terms by Cluster', 'The ten terms of highest score 100 · mean(p) · log10(p(t, c) / mean(p)), as JMP scores them.'], ['MDS Plot', 'The clusters mapped by classical scaling of the symmetric Kullback–Leibler distances between their term distributions.'], ['Cluster Probabilities by Row', 'Each document\'s probability of each cluster and its most likely one (Display Options).']] },
        { heading: 'Its red triangle', choices: [['Color by Cluster', 'Colours each row by its document\'s most likely cluster (the SVD plots follow).'], ['Show Text', 'The texts of a cluster\'s documents, its top terms marked.'], ['Save Probabilities, Save Cluster', 'Columns Prob Cluster 1, 2, … and Most Likely Cluster; each row of an ID gets its document\'s values.']] },
        { heading: 'Defaults', text: 'Five clusters, the terms seen 4 or more times, at most 1000: chosen here.' },
      ],
      more: MORE,
    },
    'p:text:cluster': {
      kicker: 'Text Explorer', title: 'Cluster Terms and Cluster Documents',
      lead: 'Ward\'s hierarchical clustering (scipy\'s linkage, each join at the increase in the within-cluster sum of squares, as JMP\'s Hierarchical Cluster reports it) of the terms\' coordinates V S, or the documents\' U S, on all the singular vectors of the SVD. The tree is cut where the joining distance jumps most (2 to 10 clusters), or into the number you set; the clusters colour the SVD plots. Cluster Documents takes at most 4000 documents here.',
      sections: [{ heading: 'Choosing and saving', choices: [['− and +', 'One cluster fewer or more.'], ['A cluster below the dendrogram', 'Selects the rows that hold its terms, or its documents\' rows (shift adds).'], ['A join', 'Selects the rows under it.'], ['Save Term Clusters', 'A new table: each term, its count, its cases and its cluster.'], ['Save Document Clusters', 'A column: each row its document\'s cluster.']] }],
      more: MORE,
    },
    'p:text:spm': {
      kicker: 'Text Explorer', title: 'SVD Scatterplot Matrix',
      lead: 'The first few singular vectors in pairs, as JMP arranges them: below the diagonal (shaded orange) the documents, Doc Vec j across and Doc Vec i up; above it (shaded blue) the terms, the pair shifted by one (Term Vec j + 1 across, Term Vec i up), so that more than the first two dimensions can be seen. Click or drag in a panel to select rows.',
      more: MORE,
    },
    'p:text:termsel': {
      kicker: 'Text Explorer', title: 'Term Selection',
      lead: 'Which terms explain a response, as JMP Pro\'s Term Selection finds them with Generalized Regression: an elastic net (the lasso\'s share 0.99) of the response on the document term matrix, each term scaled by its standard deviation, along 150 penalties from the one that keeps no term down to 1/10 000 of it; the fit with the smallest AICc is kept, and with early stopping the path ends once ten penalties in a row fail to improve it (not before four terms are in). A nominal response is a logistic model of its target level against the rest (glmnet\'s Newton steps, each a weighted scikit-learn ElasticNet); a continuous or ordinal numeric one a normal model (ElasticNet).',
      sections: [
        { heading: 'The report', choices: [['Term Scores', 'The kept terms, largest coefficient first, with their LogWorth (−log10 of a Wald p-value, the standard error from the penalized likelihood\'s Hessian on the kept terms; optimistic, as it ignores the selection) and their count.'], ['Term coefficients', 'The 30 largest coefficients in size, positive in blue and negative in red.'], ['Document Scores', 'Each document\'s positive and negative contributions and prediction; Save Document Scores saves them.']] },
        { heading: 'Defaults', text: 'Binary weighting, terms seen 10 or more times (JMP leaves rarer ones out), at most 1000, Early Stopping on.' },
      ],
      more: MORE,
    },
    'p:text:sentiment': {
      kicker: 'Text Explorer', title: 'Sentiment Analysis',
      lead: 'Scores each document by VADER (Hutto and Gilbert 2014), the vaderSentiment package (MIT), fetched from PyPI the first time it is used: its lexicon and rules are not part of this site. Each word of its lexicon adds its valence (−4 to 4); a negation before it (not, never, n\'t) reverses and weakens it, an intensifier (very, slightly) raises or lowers it, as do capitals and exclamation marks, and the clause after "but" counts more. The compound score scales the sum to −1 to 1; positive from 0.05, negative from −0.05. English only.',
      sections: [{ heading: 'The report', choices: [['Summary', 'The positive, neutral and negative documents, their counts and mean compound scores; click a class to select its rows.'], ['The histogram', 'The documents\' compound scores in bins of 0.1; click a bar to select its rows.'], ['Sentiment, Negation and Intensifier Terms', 'The words of each kind the texts hold, with their counts; click one to select its rows.'], ['Document Scores', 'Each document\'s positive, neutral and negative shares and compound score; Save Document Scores saves them.']] }],
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'text', label: 'Text Explorer', menu: 'Analyze', order: 40, info: 'p:text', topics: TOPICS,
    about: 'The words of a column of text, as JMP\'s Text Explorer counts them: tokenizing by built-in patterns, basic words or your own regular expression; scikit-learn\'s English stop words; Snowball\'s English (Porter2) stemmer, as JMP\'s, or Porter\'s (for combining or for all terms); Summary Counts, the Term and Phrase Lists (linked to the rows, with Select Contains, Select Contained and Containing Phrases), a word cloud, stop words, recodes and phrases of your own, Show Text; latent class analysis (a Bernoulli mixture of the binary document term matrix by EM, with its term probabilities, top terms, an MDS map of the clusters and saved clusters); latent semantic analysis (the SVD of the document term matrix with JMP\'s weightings, Centered and Scaled by default, documents and terms linked to the rows, a scatterplot matrix, the terms and documents clustered by Ward\'s method); topic analysis by varimax-rotated SVD, NMF or LDA; term selection (an elastic net of a response on the terms, chosen by AICc); sentiment analysis by VADER; and the document term matrix (also stacked, for Association Analysis), singular vectors and topic scores saved.',
    uses: ['sklearn.feature_extraction.text (CountVectorizer, ENGLISH_STOP_WORDS)', 'sklearn.decomposition (TruncatedSVD, PCA, NMF, LatentDirichletAllocation)', 'sklearn.linear_model.ElasticNet (Term Selection)', 'scipy.sparse', 'scipy.cluster.hierarchy.linkage (Ward)', 'vaderSentiment (MIT, from PyPI when used)', 'the Snowball and Porter stemmers, the latent class EM and the varimax rotation, written here'],
    launch: {
      lead: 'Choose one or more character columns. Each text is split into words; the words that are not stop words are counted as terms.',
      roles: ROLES,
      options: OPTIONS,
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
