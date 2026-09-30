/* ==========================================================================
   SMUI.HTML: ANALYZE > SCREENING > ASSOCIATION ANALYSIS

   JMP Pro's Association Analysis (market basket analysis), with the
   frequent item sets found by Apriori or FP-growth, written here in numpy
   and plain Python (resources/py/smui/association.py):

     Frequent Item Sets     each set's support and number of items, the
                            highest support first; a click selects the rows
                            of the transactions that hold the set
     Rules                  condition => consequent with JMP's confidence and
                            lift, and beyond JMP support, coverage,
                            conviction, leverage and a one-sided Fisher exact
                            p-value with the false discovery rate; a click
                            selects the rows of the transactions that hold
                            the rule's items
     Rule Bubble Plot       confidence by lift, each rule's bubble sized by
                            its support, linked to the rows
     Transaction Listing    each transaction's items (hidden at first, as
                            in JMP)

   The data are JMP's three formats: stacked (one Item column and an ID),
   several Item columns, or items between a delimiter in one column (JMP's
   Multiple Response). Every table the report shows comes from its call, so
   that Bootstrap can run it again on resampled rows (ctx.headless).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Association Analysis', id: 'help-p-association' };
  const ALGORITHMS = [['apriori', 'Apriori'], ['fpgrowth', 'FP-growth']];
  const DEFAULTS = { minSupport: 0.1, minConfidence: 0.4, minLift: 1.2, maxAntecedents: 3, maxRuleSize: 4 };
  const labelOf = (list, key) => (list.find((x) => x[0] === key) || [key, key])[1];
  const pct = (x) => fmt(100 * x, { sig: 4 }) + '%';

  /* ---- the transactions that hold an item set: one bit per transaction and item --------------- */
  function holder(res) {
    const tx = res.transactions;
    const n = tx.rows.length, words = Math.ceil(n / 32) || 1;
    const bits = res.items.map(() => new Uint32Array(words));
    tx.items.forEach((its, t) => { for (const j of its) bits[j][t >>> 5] |= (1 << (t & 31)); });
    const cache = new Map();
    /* The rows of the transactions that hold every item of the list. */
    return (items) => {
      const key = items.join(',');
      if (cache.has(key)) return cache.get(key);
      const acc = Uint32Array.from(bits[items[0]]);
      for (const j of items.slice(1)) { const b = bits[j]; for (let k = 0; k < words; k++) acc[k] &= b[k]; }
      const out = [];
      for (let k = 0; k < words; k++) {
        let v = acc[k];
        while (v) { const b = 31 - Math.clz32(v & -v); for (const r of tx.rows[32 * k + b]) out.push(r); v &= v - 1; }
      }
      out.sort((a, b) => a - b);
      if (cache.size > 2000) cache.delete(cache.keys().next().value);
      cache.set(key, out);
      return out;
    };
  }

  const finite = (v) => (v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v);

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const payload = {
      items: ctx.names('item'), id_col: ctx.name('id'), freq: ctx.name('freq'), delimiter: String(o('delimiter', '') || '') || null,
      min_support: o('minSupport', DEFAULTS.minSupport), min_confidence: o('minConfidence', DEFAULTS.minConfidence), min_lift: o('minLift', DEFAULTS.minLift),
      max_antecedents: o('maxAntecedents', DEFAULTS.maxAntecedents), max_rule_size: o('maxRuleSize', DEFAULTS.maxRuleSize), algorithm: o('algorithm', 'apriori'),
      where: ctx.where || [],
    };
    const res = await ctx.call('association.fit', payload);
    const box = ctx.container;
    if (res.error) { box.append(ctx.warn(res.error)); return; }
    const rowsOf = ctx.headless ? () => [] : holder(res);
    const S = res.settings;
    const form = { stacked: `stacked: one Item column (${payload.items[0]}), the rows with the same ${res.id} one transaction`, columns: `each row a transaction, its items the values of ${payload.items.join(', ')}${res.id ? `, the rows with the same ${res.id} together` : ''}`,
      delimited: `each row a transaction, its items the parts of ${payload.items.join(', ')} between "${payload.delimiter}"${res.id ? `, the rows with the same ${res.id} together` : ''}` }[res.format];
    box.append(ctx.note(`${fmt(res.n_transactions)} transactions${res.weighted ? ` (${fmt(res.total)} counted with ${payload.freq})` : ''} of ${fmt(res.n_items)} items; ${form}. ${res.algorithm}: Minimum Support ${fmt(S.min_support)}, Minimum Confidence ${fmt(S.min_confidence)}, Minimum Lift ${fmt(S.min_lift)}, at most ${S.max_antecedents} antecedent${S.max_antecedents === 1 ? '' : 's'} and ${S.max_rule_size} items in a rule.${res.notes.length ? ` ${res.notes.join(' ')}` : ''}`));
    const select = (rows, ev) => { if (ctx.table) ctx.table.select(rows, ev && (ev.shiftKey || ev.metaKey || ev.ctrlKey) ? 'add' : 'replace'); };
    if (o('listing', false)) listingOutline(ctx, res, select);
    if (o('sets', true)) setsOutline(ctx, res, rowsOf, select);
    if (o('rules', true)) rulesOutline(ctx, res, rowsOf, select);
    if (o('bubbles', true) && res.rules.length && !ctx.headless) bubbleOutline(ctx, res, rowsOf);
    box.append(ctx.code(res.code));
  }

  const wide = (tbl) => el('div', { class: 'sm-as-scroll' }, tbl);

  function setsOutline(ctx, res, rowsOf, select) {
    const ob = ctx.outline('Frequent Item Sets', { key: 'sets', info: 'p:assoc:sets', closed: true });
    ob.add(wide(ctx.rt({
      columns: [{ key: 'set', label: 'Item Set', fmt: 'text' }, { key: 'support', label: 'Support', fmt: 'pct', digits: 1 }, { key: 'n', label: 'N Items', fmt: 'int' },
        { key: 'count', label: 'Transactions', fmt: 'int', hidden: true, title: 'the transactions that hold the set (counted with Freq)' }],
      rows: res.item_sets,
    }, { key: 'sets', name: 'Frequent Item Sets', maxRows: 1000, onRow: (r, ev) => select(rowsOf(r.items), ev) })),
    ctx.note(`${fmt(res.item_sets.length)} item sets with support ${fmt(res.settings.min_support)} or more (at most ${res.settings.max_rule_size} items), the highest support first. Click a set to select the rows of the transactions that hold it (shift adds); click a heading to sort; right click to make a data table.`));
  }

  function rulesOutline(ctx, res, rowsOf, select) {
    const ob = ctx.outline('Rules', { key: 'rules', info: 'p:assoc:rules' });
    if (!res.rules.length) { ob.add(ctx.note('No rule meets the Minimum Confidence and the Minimum Lift: lower them (Redo > Relaunch Analysis) or lower the Minimum Support.')); return; }
    const rows = res.rules.map((r) => ({ ...r, conviction: finite(r.conviction) }));
    ob.add(wide(ctx.rt({
      columns: [{ key: 'condition', label: 'Condition', fmt: 'text' }, { key: 'consequent', label: 'Consequent', fmt: 'text' },
        { key: 'confidence', label: 'Confidence', fmt: 'pct', digits: 1 }, { key: 'lift', label: 'Lift', sig: 4 },
        { key: 'support', label: 'Support', fmt: 'pct', digits: 1 }, { key: 'coverage', label: 'Coverage', fmt: 'pct', digits: 1, hidden: true, title: 'the support of the condition' },
        { key: 'conviction', label: 'Conviction', sig: 4 }, { key: 'leverage', label: 'Leverage', digits: 4 },
        { key: 'p', label: 'Fisher p', fmt: 'p', hidden: true, title: 'the one-sided Fisher exact test: the condition and the consequent together more often than by chance' },
        { key: 'fdr', label: 'FDR p', fmt: 'p', title: 'the Fisher p-value adjusted for the false discovery rate (Benjamini and Hochberg) over every rule the frequent item sets make' },
        { key: 'count', label: 'Transactions', fmt: 'int', hidden: true, title: 'the transactions that hold the condition and the consequent (counted with Freq)' }],
      rows,
    }, { key: 'rules', name: 'Rules', maxRows: 1000, onRow: (r, ev) => select(rowsOf([...r.x, ...r.y]), ev) })),
    ctx.note(`${fmt(res.rules.length)} rules, the highest confidence first (as JMP sorts them). Confidence is P(consequent | condition), lift the confidence over the consequent's support (1: no association). Beyond JMP: conviction (1 − support of the consequent)/(1 − confidence), leverage P(both) − P(condition) P(consequent), and FDR p, the one-sided Fisher exact p-value adjusted by Benjamini and Hochberg over all ${fmt(res.n_rules_made)} rules of the frequent item sets (right click, Columns: coverage, Fisher p and the transactions). Click a rule to select the rows of the transactions that hold all its items.`));
  }

  /* Each rule's bubble: at its confidence and lift, its area following its support. */
  function bubbleOutline(ctx, res, rowsOf) {
    const ob = ctx.outline('Rule Bubble Plot', { key: 'bubbles', info: 'p:assoc:bubbles' });
    const R = res.rules;
    const smax = Math.max(...R.map((r) => r.support));
    const d = R.map((r) => Math.max(5, 28 * Math.sqrt(r.support / smax)));
    const c = SM.util.themeColors();
    const trace = {
      type: 'scatter', mode: 'markers', x: R.map((r) => r.confidence), y: R.map((r) => r.lift), rows: R.map((r) => rowsOf([...r.x, ...r.y])),
      marker: { size: d, sizemode: 'diameter', color: SM.report.BASE, opacity: 0.55, line: { color: SM.report.BASE, width: 0.7 } },
      hovertext: R.map((r) => `${T(r.rule)}<br>confidence ${pct(r.confidence)}, lift ${fmt(r.lift, { sig: 4 })}, support ${pct(r.support)}`),
      hovertemplate: '%{hovertext}<extra></extra>', name: 'Rules',
    };
    ob.add(el('div', { class: 'sm-as-plotcode' },
      ctx.plot([trace], {
        xaxis: { title: { text: 'Confidence' }, tickformat: '.0%' }, yaxis: { title: { text: 'Lift' } },
        shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 1, y1: 1, line: { color: c.muted, width: 1, dash: 'dot' }, layer: 'below' }],
        margin: { l: 56, r: 14, t: 10, b: 46 },
      }, { width: 520, height: 400, title: 'Rules: confidence, lift and support', rowColors: false }),
      ctx.code((res.plot_code || {}).bubbles)),
    ctx.note('Each bubble is a rule at its confidence and lift, its area following its support (the dotted line is lift 1: no association). The rules worth a look lie up and to the right with a large bubble. Click or drag to select the rows of the transactions that hold the rules\' items; rows selected elsewhere mark the rules they hold.'));
  }

  function listingOutline(ctx, res, select) {
    const ob = ctx.outline('Transaction Listing', { key: 'listing', info: 'p:assoc:listing' });
    const tx = res.transactions;
    const byId = !!res.id;
    const rows = tx.rows.map((rs, t) => ({ t: byId ? tx.keys[t] : tx.keys[t], items: tx.items[t].map((j) => res.items[j]).join(', '), n: tx.items[t].length, count: tx.counts[t], rs }));
    if (byId) {
      const num = rows.every((r) => Number.isFinite(Number(r.t)));
      rows.sort((a, b) => (num ? Number(a.t) - Number(b.t) : SM.table.collator.compare(String(a.t), String(b.t))));
    }
    const columns = [{ key: 't', label: byId ? res.id : 'Row', fmt: byId ? 'text' : 'int' }, { key: 'items', label: 'Items', fmt: 'text' }, { key: 'n', label: 'N Items', fmt: 'int' }];
    if (res.weighted) columns.push({ key: 'count', label: 'Freq', fmt: 'int' });
    ob.add(wide(ctx.rt({ columns, rows }, { key: 'listing', name: 'Transaction Listing', maxRows: 1000, onRow: (r, ev) => select(r.rs, ev) })),
      ctx.note(`Each transaction and its items${byId ? `, sorted by ${res.id}` : ''}. Click one to select its rows.`));
  }

  /* ======================================================================
     THE LAUNCH: roles and options, with what each is for (the (i))
     ====================================================================== */
  const ROLES = [
    { key: 'item', label: 'Item', min: 1, types: ['nominal', 'ordinal'], hint: 'required', info: 'p:assoc',
      help: 'The items: one column with an ID (stacked data, one item a row), two or more columns (each row a transaction, its items their values), or one column whose cells hold several items between the Multiple Response Delimiter.' },
    { key: 'id', label: 'ID', max: 1, hint: 'optional', help: 'The transaction each row belongs to: the rows with the same ID are one transaction (a basket). Needed with one Item column unless its items are delimited; rows with no ID are left out.' },
    { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
      help: 'How many times each transaction counts (its first row\'s value, truncated to a whole number, as JMP\'s Freq). Not used with stacked data (one Item column and an ID), as in JMP.' },
    { key: 'by', label: 'By', hint: 'optional', help: 'A separate analysis for each level of the By column (each combination of levels, with several). Rows with a missing By value are left out.' },
  ];
  const OPTIONS = [
    { key: 'minSupport', label: 'Minimum Support', type: 'number', value: DEFAULTS.minSupport,
      help: 'The share of the transactions an item set must be in to count as frequent, above 0 and at most 1 (0.1: in one transaction in ten). Only frequent sets make rules; a lower value finds rarer sets and takes longer.' },
    { key: 'minConfidence', label: 'Minimum Confidence', type: 'number', value: DEFAULTS.minConfidence,
      help: 'The rules shown have at least this confidence, from 0 to 1 (0.4): the share of the transactions with the condition that also hold the consequent.' },
    { key: 'minLift', label: 'Minimum Lift', type: 'number', value: DEFAULTS.minLift,
      help: 'The rules shown have at least this lift, 0 or more (1.2): the confidence over the consequent\'s own support. 1 means no association; above 1, the items go together more often than by chance.' },
    { key: 'maxAntecedents', label: 'Maximum Antecedents', type: 'number', value: DEFAULTS.maxAntecedents,
      help: 'The most items in a rule\'s condition, a whole number from 1 (3).' },
    { key: 'maxRuleSize', label: 'Maximum Rule Size', type: 'number', value: DEFAULTS.maxRuleSize,
      help: 'The most items in a rule, condition and consequent together, a whole number from 2 (4); no larger item set is searched for, which keeps large data quick.' },
    { key: 'delimiter', label: 'Multiple Response Delimiter', type: 'text', value: '', size: 4,
      help: 'Empty (the default): each Item cell is one item. A delimiter (a comma, say) cuts each cell into several items, as JMP\'s Multiple Response columns hold them; each row is then a transaction.' },
    { key: 'algorithm', label: 'Algorithm', type: 'select', value: 'apriori', choices: ALGORITHMS,
      help: 'How the frequent item sets are found: Apriori (JMP\'s, level by level from the frequent single items) or FP-growth (a prefix tree of the transactions, mined without candidate sets). Both find the same sets.' },
  ];

  function validate(spec, table) {
    const r = spec.roles || {};
    const items = r.item || [];
    const idc = (r.id || [])[0];
    if (idc && items.includes(idc)) return 'The ID column cannot be an Item column too';
    const o = spec.options || {};
    if (items.length === 1 && !idc && !String(o.delimiter || '')) return 'One Item column is stacked data: give an ID, a Multiple Response Delimiter, or two or more Item columns';
    const num = (v, lo, hi, openLo) => v == null || (Number.isFinite(v) && v <= hi && (openLo ? v > lo : v >= lo));
    const whole = (v, lo) => v == null || (Number.isInteger(v) && v >= lo && v <= 100);
    if (!num(o.minSupport, 0, 1, true)) return 'Minimum Support: a number above 0 and at most 1';
    if (!num(o.minConfidence, 0, 1)) return 'Minimum Confidence: a number from 0 to 1';
    if (!num(o.minLift, 0, 1e12)) return 'Minimum Lift: 0 or more';
    if (!whole(o.maxAntecedents, 1)) return 'Maximum Antecedents: a whole number from 1 to 100';
    if (!whole(o.maxRuleSize, 2)) return 'Maximum Rule Size: a whole number from 2 to 100';
    return null;
  }

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const MEASURES = [
    ['Support', 'The share of the transactions that hold an item set (of a rule: its condition and consequent together), P(X and Y).'],
    ['Confidence', 'P(Y | X): the share of the transactions with the condition that also hold the consequent. Not a confidence interval.'],
    ['Lift', 'The confidence over the consequent\'s support, P(X and Y)/(P(X) P(Y)): 1 when the two occur independently, above 1 when they go together, below 1 when they repel. The same for X ⇒ Y and Y ⇒ X.'],
    ['Coverage', 'The condition\'s support, P(X): how often the rule applies. Beyond JMP.'],
    ['Conviction', '(1 − P(Y))/(1 − confidence) (Brin et al. 1997): how much more often the condition would occur without the consequent if they were unrelated; 1 for independence, ∞ for a rule that always holds. Beyond JMP.'],
    ['Leverage', 'P(X and Y) − P(X) P(Y) (Piatetsky-Shapiro): the share of the transactions the pair adds over independence. Beyond JMP.'],
    ['Fisher p, FDR p', 'The one-sided Fisher exact test of the condition and the consequent occurring together more often than by chance (the hypergeometric upper tail of the 2 × 2 table of the transactions), and that p-value adjusted for the false discovery rate by Benjamini and Hochberg over every rule the frequent item sets make, before the confidence and lift filters. Beyond JMP.'],
  ];
  const TOPICS = {
    'p:assoc': {
      kicker: 'Analyze > Screening', title: 'Association Analysis',
      lead: 'Which items go together in transactions (market baskets): the item sets that occur in at least a Minimum Support share of the transactions, and the rules condition ⇒ consequent they make, with how often the rule holds (confidence) and how much more often than by chance (lift). The frequent item sets are found by Agrawal and Srikant\'s Apriori (JMP\'s method) or Han, Pei and Yin\'s FP-growth, both written here in numpy and plain Python on a boolean matrix of the transactions by the items.',
      sections: [
        { heading: 'Data formats', choices: [['Stacked', 'One Item column and an ID: each row one item, the rows with the same ID one transaction.'], ['Several columns', 'Two or more Item columns: each row a transaction (the rows with the same ID together, with an ID).'], ['Delimited', 'One Item column whose cells hold several items between the Multiple Response Delimiter: each row a transaction.']] },
        { heading: 'Roles', choices: ROLES.map((r) => [r.label, r.help]) },
        { heading: 'Options', choices: OPTIONS.map((x) => [x.label, x.help]) },
        { heading: 'Measures', choices: MEASURES },
        { heading: 'Differences from JMP', text: 'JMP\'s Multiple Response modeling type is here the Multiple Response Delimiter option on a character column. The Rules table adds support, coverage, conviction, leverage and the Fisher exact p-values with their false discovery rate to JMP\'s confidence and lift, and percentages show one decimal. The Frequent Item Sets and the rules follow JMP\'s documented Maximum Rule Size (the items of a rule, condition and consequent together) and Maximum Antecedents. FP-growth and the Rule Bubble Plot are beyond JMP; JMP\'s SVD and Topic Analysis of the items are not here.' },
      ],
      more: MORE,
    },
    'p:assoc:sets': {
      kicker: 'Association Analysis', title: 'Frequent Item Sets',
      lead: 'The item sets whose support (the share of the transactions that hold every item of the set) is at least the Minimum Support, the highest first (then the smaller sets); N Items is the size of the set. Each set is a candidate condition and consequent of the rules. Click a set to select the rows of its transactions (shift adds); right click, Columns, shows the number of transactions.',
      more: MORE,
    },
    'p:assoc:rules': {
      kicker: 'Association Analysis', title: 'Rules',
      lead: 'Every rule condition ⇒ consequent of the frequent item sets (the two sets apart and not empty) that meets the Minimum Confidence and the Minimum Lift, with at most Maximum Antecedents items in the condition and Maximum Rule Size items in all; the highest confidence first. Click a heading to sort; click a rule to select the rows of the transactions that hold all its items.',
      sections: [{ heading: 'The columns', choices: MEASURES }],
      more: MORE,
    },
    'p:assoc:bubbles': {
      kicker: 'Association Analysis', title: 'Rule Bubble Plot',
      lead: 'Each rule at its confidence (across) and lift (up), its bubble\'s area following its support (the largest 28 pixels across); the dotted line is lift 1. Useful rules lie up and to the right, and a large bubble applies to many transactions. Beyond JMP, which makes this graph from the Rules table in Graph Builder.',
      sections: [{ heading: 'Clicking', choices: [['A bubble', 'Selects the rows of the transactions that hold the rule\'s items (drag a box for several).'], ['Rows selected elsewhere', 'Mark the rules whose transactions hold them.']] }],
      more: MORE,
    },
    'p:assoc:listing': {
      kicker: 'Association Analysis', title: 'Transaction Listing',
      lead: 'Each transaction (an ID, or a row) and its items, sorted by the ID, with its Freq when there is one. Click a transaction to select its rows.',
      more: MORE,
    },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'association', label: 'Association Analysis', menu: 'Analyze/Screening', order: 40, info: 'p:assoc', topics: TOPICS,
    about: 'JMP Pro\'s Association Analysis (market basket analysis) of stacked transactions (Item and ID), several Item columns or delimited items: the frequent item sets by Apriori or FP-growth (written here in numpy), the rules with JMP\'s confidence and lift and, beyond JMP, support, coverage, conviction, leverage and one-sided Fisher exact p-values with their false discovery rate; both tables sortable, linked to the transactions\' rows and made into data tables; a bubble plot of the rules by confidence and lift, sized by support; the transaction listing.',
    uses: ['numpy (the item matrix, Apriori)', 'FP-growth, written here', 'scipy.stats.hypergeom (Fisher\'s exact test)', 'Benjamini and Hochberg\'s false discovery rate, written here'],
    launch: {
      lead: 'Choose the items: one column with the ID of the transactions, several columns, or one column of delimited items.',
      roles: ROLES,
      options: OPTIONS,
      validate,
    },
    title: () => 'Association Analysis',
    triangle: (ctx) => [
      ctx.check('Transaction Listing', 'listing', null, false),
      ctx.check('Frequent Item Sets', 'sets', null, true),
      ctx.check('Rules', 'rules', null, true),
      ctx.check('Rule Bubble Plot', 'bubbles', null, true),
      { separator: true },
      { label: 'Algorithm', submenu: () => ALGORITHMS.map(([v, l]) => ({ label: l, checked: ctx.opt('algorithm', 'apriori') === v, action: () => ctx.set('algorithm', v) })) },
    ],
    render,
  });

  /* ======================================================================
     THE EXAMPLE: simulated grocery baskets, stacked
     ====================================================================== */
  SM.io.addExample('market-baskets', {
    label: 'Market baskets (1,200 baskets): products bought together',
    about: 'Simulated: 1,200 shopping baskets from two stores, stacked one product a row (Basket ID and Product, for Association Analysis in Analyze > Screening). Planted associations: bread with butter and then jam, pasta with tomato sauce and parmesan, tortilla chips with salsa and cola, coffee with milk, burgers with buns and ketchup, and in the North store wine with cheese; tea goes with lemon and rarely with coffee; the rest (apples, bananas, eggs, yogurt, rice, soap) at random. Store is a By column; Quantity is the units of the product.',
    make() {
      const r = SM.util.rng('association-market-baskets');
      const c = { basket: [], store: [], product: [], quantity: [] };
      for (let b = 1; b <= 1200; b++) {
        const north = r.u() < 0.5;
        const items = new Set();
        const add = (name, p) => { if (r.u() < p) { items.add(name); return true; } return false; };
        if (add('bread', 0.42)) { if (add('butter', 0.65)) add('jam', 0.45); } else add('butter', 0.12);
        if (add('pasta', 0.28)) { add('tomato sauce', 0.7); add('parmesan', 0.4); } else add('tomato sauce', 0.06);
        if (add('tortilla chips', 0.2)) { add('salsa', 0.6); add('cola', 0.55); } else add('cola', 0.15);
        if (add('coffee', 0.35)) add('milk', 0.6); else { add('milk', 0.3); if (add('tea', 0.3)) add('lemon', 0.45); }
        if (add('burgers', 0.15)) { add('buns', 0.8); add('ketchup', 0.55); }
        if (north && add('wine', 0.25)) add('cheese', 0.65); else add('cheese', 0.12);
        for (const [name, p] of [['apples', 0.3], ['bananas', 0.35], ['eggs', 0.3], ['yogurt', 0.22], ['rice', 0.12], ['soap', 0.08]]) add(name, p);
        if (!items.size) items.add('bananas');
        const list = [...items];
        for (let i = list.length - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [list[i], list[j]] = [list[j], list[i]]; }   // the order they were scanned in
        for (const name of list) {
          c.basket.push(b); c.store.push(north ? 'North' : 'South'); c.product.push(name); c.quantity.push(1 + (r.u() < 0.25 ? r.int(1, 3) : 0));
        }
      }
      return new SM.Table({ name: 'Market baskets', source: 'simulated', columns: [
        { name: 'Basket ID', dataType: 'numeric', modelingType: 'nominal', values: c.basket },
        { name: 'Store', dataType: 'character', values: c.store },
        { name: 'Product', dataType: 'character', values: c.product },
        { name: 'Quantity', dataType: 'numeric', values: c.quantity },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
