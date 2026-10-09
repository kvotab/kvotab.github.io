/* ==========================================================================
   SMUI.HTML: SEARCH (Help > Search…, ctrl/⌘+K, the magnifier in the menu bar)

   A word or two finds a feature, as JMP's Search JMP does, and choosing it
   takes the user there. What is searched:

     Menu           the commands of the menu bar's menus and submenus, as
                    they are now (one that is greyed out says why)
     Red triangle   every platform's own red-triangle items, read from a
                    stand-in report that is never run: no action is called
                    and nothing is computed. With them the red triangles of
                    the outlines a platform makes before its first call to
                    the engine (a Distribution column's), read the same way
                    with the engine never asked; a level named after a
                    stand-in column shows as ‹column›. The items every
                    report has after the platform's own (Set α Level, Redo,
                    Save Script…) are indexed once, under ‹report›.
     Open report    the red triangles of the open reports' outlines, the
                    report in front first
     Help           the (i) topics and the Help tab's sections

   A platform's item applies to the report in front when that report is of
   the platform; otherwise the platform is launched, and the item applied to
   its report once it has run (a cancelled launch does nothing). A ‹column›
   level goes to the report's matching column, the first of several (the
   message says so). The platforms' items and the help are read once, when
   the search first opens; the menus and the open reports each time it does.

   Text from tables and reports is data: everything here is text nodes, and
   a path is kept as its list of levels, never made into a string and parsed
   again (a column may be named "a ▸ b").
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  if (!SM || !SM.util || !SM.report) return;
  const { el, svg } = SM.util;

  const COL = '‹column›';         // a level named after a column of the report
  const REP = '‹report›';         // the top red triangle every report has
  const MAX = 50;                 // results shown
  const RECENT = 'smui.search.recent';
  const MAC = /mac|iphone|ipad|ipod/i.test((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '');
  const SHORTCUT = MAC ? '⌘K' : 'Ctrl+K';
  const TRY = ['word cloud', 'stack', 'johnson su', 'normal quantile plot', 'missing values', 'local data filter', 'row states'];

  /* ---- words -------------------------------------------------------------
     Lower case, without accents, split at anything but letters and digits;
     a light stem so that a plural finds the singular (clouds, boxes,
     series) and fitted or binning find fit and bin. */
  const fold = (s) => String(s).toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const WORD = /[\p{L}\p{N}]+/gu;
  const words = (s) => [...fold(String(s == null ? '' : s).split(COL).join(' ').split(REP).join(' ')).matchAll(WORD)].map((m) => m[0]);
  const undouble = (b) => (/([b-df-hj-np-tv-z])\1$/.test(b) && !/(ll|ss|zz)$/.test(b) ? b.slice(0, -1) : b);
  function stem(w) {
    if (w.length < 4) return w;
    if (w.endsWith('ies') && w.length > 4) return `${w.slice(0, -3)}y`;
    if (/(ches|shes|sses|xes|zes)$/.test(w)) return w.slice(0, -2);
    if (w.endsWith('s') && !/(ss|us|is)$/.test(w)) return w.slice(0, -1);
    if (w.length > 5 && w.endsWith('ing')) { const b = undouble(w.slice(0, -3)); if (b.length >= 3 && /[aeiouy]/.test(b)) return b; }
    if (w.length > 4 && w.endsWith('ed') && !w.endsWith('eed')) { const b = undouble(w.slice(0, -2)); if (b.length >= 3 && /[aeiouy]/.test(b)) return b; }
    return w;
  }
  const plain = (s) => String(s == null ? '' : s).replace(/\*\*([^*]+)\*\*/g, '$1').replace(/`([^`]+)`/g, '$1');
  // a label compared loosely: case, an ellipsis and spaces aside
  const loose = (s) => fold(s).replace(/…|\.\.\./g, '').replace(/\s+/g, ' ').trim();
  const last = (a) => a[a.length - 1];
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  // The words of an entry, for matching: its label (or e.match), its path, its text.
  function prep(e) {
    e._l = words(e.match != null ? e.match : e.label);
    e._ls = e._l.map(stem);
    e._p = words(e.path.join(' '));
    e._ps = e._p.map(stem);
    e._t = words(e.text || '');
    e._ts = e._t.map(stem);
    return e;
  }

  /* ---- menus, read without running them ------------------------------------
     fn(item, labels, off) for every item, depth first; off when it or a
     menu above it is greyed out (its submenu does not open then). */
  function walkMenu(items, labels, off, fn, stats = null, depth = 0) {
    for (const it of items || []) {
      if (!it || it.separator || it.head || it.label == null || it.label === '') continue;
      const here = [...labels, String(it.label)];
      const dis = off || !!it.disabled;
      if (stats) stats.items++;
      fn(it, here, dis);
      if (!it.submenu || depth >= 6) continue;
      let sub = null;
      try { sub = typeof it.submenu === 'function' ? it.submenu() : it.submenu; } catch (e) { if (stats) stats.errors.push(`${here.join(' ▸ ')}: ${e && e.message ? e.message : e}`); }
      if (Array.isArray(sub)) walkMenu(sub, here, dis, fn, stats, depth + 1);
    }
  }
  // An item that does something (a submenu's own name is found in its items' paths).
  const leaf = (it) => !it.submenu || typeof it.action === 'function';

  /* ---- the stand-in a platform's red triangle is read with -----------------
     Column names no label has, so that a level named after one can be told:
     it is shown as ‹column› and matched to a column of a live report. */
  const STAND = { cont: ['Xq7stand', 'Yq7stand', 'Zq7stand'], cat: ['Gq7stand', 'Hq7stand', 'Kq7stand'], text: 'Tq7stand' };
  const STAND_RE = new RegExp([...STAND.cont, ...STAND.cat, STAND.text].join('|'), 'g');
  const generic = (s) => String(s).replace(STAND_RE, COL);

  function standIn() {
    const n = 40;
    const num = (k) => Array.from({ length: n }, (_, i) => ((i * (7 + 6 * k)) % (11 + k)) + i * (0.5 + k) + 0.5);
    const lev = (k) => Array.from({ length: n }, (_, i) => ['a', 'b', 'c', 'd'][(i + k * (i >> 2)) % (3 + (k % 2))]);
    return new SM.Table({ name: 'search stand-in', columns: [
      ...STAND.cont.map((name, k) => ({ name, dataType: 'numeric', values: num(k) })),
      ...STAND.cat.map((name, k) => ({ name, dataType: 'character', values: lev(k) })),
      { name: STAND.text, dataType: 'character', values: Array.from({ length: n }, (_, i) => `word${i % 5} other${i % 3} text`) },
    ] });
  }

  /* The roles a platform's red triangle is read with: a column for each role
     it must have (and X and Y always), different columns for different
     roles. A role that takes both kinds gets a continuous column in one
     reading and a categorical one in another, for the first two such roles
     (Bivariate Analysis: Bivariate, Oneway, Logistic and Contingency; a
     Distribution column's continuous and its categorical red triangle). */
  const filled = (p) => ((p.launch && p.launch.roles) || []).filter((r) => (r.min || 0) >= 1 || ['x', 'y'].includes(r.key));
  const either = (r) => r.key !== 'text' && (!r.types || (r.types.includes('continuous') && (r.types.includes('nominal') || r.types.includes('ordinal'))));
  const flexRoles = (p) => filled(p).filter(either).slice(0, 2);
  function variantsOf(p, t) {
    const roles = filled(p);
    const flex = flexRoles(p);
    const out = [], seen = new Set();
    for (let mask = 0; mask < (1 << flex.length); mask++) {
      const used = { cont: 0, cat: 0 };
      const map = {};
      for (const r of roles) {
        const k = flex.indexOf(r);
        let kind;
        if (r.key === 'text') kind = 'text';
        else if (k >= 0) kind = mask & (1 << k) ? 'cat' : 'cont';
        else kind = r.types && !r.types.includes('continuous') && !r.numeric ? 'cat' : 'cont';
        if (kind === 'text') { map[r.key] = [t.col(STAND.text).id]; continue; }
        const want = (r.min || 0) >= 2 ? 2 : 1;
        const names = [];
        for (let i = 0; i < want; i++) names.push(STAND[kind][Math.min(used[kind]++, STAND[kind].length - 1)]);
        map[r.key] = [...new Set(names)].map((nm) => t.col(nm).id);
      }
      const sig = JSON.stringify(map);
      if (!seen.has(sig)) { seen.add(sig); out.push(map); }
    }
    return out;
  }

  const groupOf = (t) => ({ rows: t ? t.includedRows() : [], label: null, where: [] });
  /* When an item is there, from the readings it came from (got: their
     indices): the kind of one role that tells them from the others ("when X
     is continuous"), or else each reading in turn. */
  function whenText(p, readings, got, t) {
    const flex = flexRoles(p);
    const kindOf = (roles, r) => (roles[r.key] && t.col(roles[r.key][0]).isCategorical ? 'categorical' : 'continuous');
    const name = (r) => String(r.label || r.key).split(',')[0].trim();
    for (const r of flex) {
      for (const k of ['continuous', 'categorical']) {
        const those = readings.map((roles, i) => (kindOf(roles, r) === k ? i : -1)).filter((i) => i >= 0);
        if (those.length === got.size && those.every((i) => got.has(i))) return `when ${name(r)} is ${k}`;
      }
    }
    return [...got].map((i) => `when ${flex.map((r, j) => `${name(r)}${j ? '' : ' is'} ${kindOf(readings[i], r)}`).join(' and ')}`).join(', or ');
  }
  // A reading's roles in words, for a message: "y: continuous, x: nominal".
  const describeRoles = (roles, t) => Object.entries(roles).map(([k, ids]) => `${k}: ${ids.map((id) => (t.col(id).isCategorical ? 'categorical' : 'continuous')).join(', ')}`).join('; ') || 'no roles';

  // The items every report's top red triangle has after the platform's own
  // (Ctx.topMenu), from a report of no platform and no table.
  function commonItems(app) {
    const rep = new SM.report.Report(app, { id: 'search-stand-in', label: 'Report', render() {} }, { roles: {}, options: {} }, null);
    try { return new SM.report.Ctx(rep, groupOf(null), el('div'), '').topMenu().filter((it) => it && !it.separator); } finally { rep.close(); }
  }

  /* ---- what an item is for: its own title, or its line in a topic --------
     The platform's (i) topics have choices [name, what it does]; an item
     takes the text of the choice of its name, or of the nearest submenu
     above it that has one. */
  const choiceCache = new Map();
  function choicesOf(keys) {
    const out = [];
    for (const key of keys) {
      if (!key) continue;
      if (!choiceCache.has(key)) {
        const list = [];
        const tp = SM.info.get(key);
        for (const s of (tp && tp.sections) || []) for (const c of s.choices || []) if (c && c[0] && c[1]) list.push([loose(plain(c[0])), plain(c[1])]);
        choiceCache.set(key, list);
      }
      out.push(...choiceCache.get(key));
    }
    return out;
  }
  function choiceFor(list, labels) {
    for (let i = labels.length - 1; i >= 0; i--) {
      const l = loose(generic(labels[i]).split(COL).join(''));
      if (!l) continue;
      const hit = list.find(([n]) => n === l) || (l.length >= 5 ? list.find(([n]) => n.length >= 5 && (n.startsWith(l) || l.startsWith(n))) : null);
      if (hit) return hit[1];
    }
    return '';
  }
  const platformTopics = (p) => [p.info, ...Object.keys(p.topics || {})];
  function itemText(it, list, labels) {
    const parts = [];
    if (it.title && !it.disabled) parts.push(String(it.title));
    const c = choiceFor(list, labels);
    if (c && !parts.includes(c)) parts.push(c);
    return parts.join(' ');
  }

  /* ---- the index read once: the platforms' red triangles and the help ---------------- */
  let built = null;      // its promise
  let index = null;      // { entries, keys, commonLabels, stats }

  function ready(app = SM.app) {
    if (!built) {
      built = crawl(app).then((r) => { index = r; return r; }, (e) => {
        console.error('SM search: the index could not be read', e);
        index = { entries: [], keys: new Set(), commonLabels: new Set(), stats: { platforms: 0, items: 0, errors: [String(e)], outlines: 0, columnErrors: [], entries: {} } };
        return index;
      });
    }
    return built;
  }

  const keyOf = (e) => (e.kind === 'help' ? `help|${e.topic || ''}|${e.anchor || ''}` : `${e.kind}|${e.platform ? e.platform.id : ''}|${e.outline || ''}|${e.steps.join('\u0001')}`);

  async function crawl(app) {
    const t0 = performance.now();
    const stats = { platforms: 0, readings: 0, items: 0, errors: [], outlines: 0, columnItems: 0, columnErrors: [], entries: {}, ms: 0 };
    const entries = [];
    const keys = new Set();
    const byKey = new Map();
    // an entry once; a platform's item also notes the reading it came from (v)
    const add = (e, v = null) => {
      const k = keyOf(e);
      const had = byKey.get(k);
      if (had) { if (had._v && v != null) had._v.add(v); return; }
      if (v != null) e._v = new Set([v]);
      byKey.set(k, e);
      keys.add(k);
      entries.push(prep(e));
    };
    // the items every report has: once
    const common = commonItems(app);
    const commonLabels = new Set(common.map((it) => String(it.label)));
    walkMenu(common, [], false, (it, labels) => {
      if (leaf(it)) add({ kind: 'common', label: last(labels), path: [REP, ...labels.slice(0, -1)], steps: labels, text: itemText(it, [], labels) });
    });
    const t = standIn();
    for (const p of SM.platforms.all()) {
      if (!p.menu || p.hidden) continue;           // the ones launched from the menu bar
      stats.platforms++;
      const where = [...p.menu.split('/'), `${p.label}${p.launch ? '…' : ''}`];
      const list = choicesOf(platformTopics(p));
      const readings = variantsOf(p, t);
      let v = 0;
      const platformItem = (outline) => (it, labels) => {
        if (!leaf(it)) return;
        const steps = labels.map(generic);
        add({ kind: 'triangle', platform: p, where, outline, steps, label: last(steps), path: [...where, ...(outline ? [outline] : []), ...steps.slice(0, -1)], text: itemText(it, list, labels) }, v);
      };
      const first = entries.length;
      for (; v < readings.length; v++) {
        const roles = readings[v];
        let rep = null;
        try {
          rep = new SM.report.Report(app, p, { roles, options: {} }, t);
          const ctx = new SM.report.Ctx(rep, { rows: [], label: null, where: [] }, el('div'), '');
          const own = p.triangle ? (p.triangle(ctx) || []) : [];
          const all = ctx.topMenu();
          walkMenu(all.slice(0, own.length), [], false, platformItem(null), stats);
          walkMenu(all.slice(own.length), [], false, () => {}, stats);       // read (and counted) for every platform; indexed once above
          stats.readings++;
        } catch (e) { stats.errors.push(`${p.label} (${describeRoles(roles, t)}): ${e && e.message ? e.message : e}`); }
        if (rep) rep.close();
        await columnOutlines(app, p, t, roles, platformItem, stats);
      }
      // an item that only some readings have: when (with which columns) it is there
      if (readings.length > 1) for (const e of entries.slice(first)) if (e._v && e._v.size < readings.length) e.when = whenText(p, readings, e._v, t);
    }
    for (const e of helpEntries(app)) add(e);
    for (const e of entries) stats.entries[e.kind] = (stats.entries[e.kind] || 0) + 1;
    stats.ms = Math.round(performance.now() - t0);
    return { entries, keys, commonLabels, stats };
  }

  /* The outlines a platform makes before its first call to the engine (a
     Distribution column's, a Contour Plot's), with their red triangles: its
     render on the stand-in, headless (no graphs, no saved columns, no options
     set) and with the engine never asked, so that the render stops, for
     good, at its first call. A stand-in a platform cannot draw gives none. */
  async function columnOutlines(app, p, t, roles, platformItem, stats) {
    if (p.needsTable === false || typeof p.render !== 'function') return;
    const made = [];
    let rep = null;
    try {
      rep = new SM.report.Report(app, p, { roles, options: {} }, t);
      const ctx = new SM.report.Ctx(rep, groupOf(t), el('div'), '');
      ctx.headless = true;
      ctx.call = () => new Promise(() => {});
      const outline = ctx.outline.bind(ctx);
      ctx.outline = (title, opts = {}) => { const o = outline(title, opts); if (opts.menu) made.push({ title: String(title), menu: opts.menu }); return o; };
      const top = outline(p.label, { level: 0 });
      ctx.container = top.body;
      ctx.top = top;
      const run = p.render(ctx);
      if (run && typeof run.then === 'function') run.then(null, () => {});
      for (let i = 0; i < 8; i++) await null;      // the awaits before its first call
    } catch (e) { /* a stand-in it cannot draw */ }
    for (const m of made) {
      let items = null;
      try { items = typeof m.menu === 'function' ? m.menu() : m.menu; } catch (e) { stats.columnErrors.push(`${p.label} ▸ ${generic(m.title)}: ${e && e.message ? e.message : e}`); }
      if (!Array.isArray(items)) continue;
      stats.outlines++;
      const counted = { items: 0, errors: stats.columnErrors };
      walkMenu(items, [], false, platformItem(generic(m.title)), counted);
      stats.columnItems += counted.items;
    }
    if (rep) rep.close();
  }

  // The (i) topics and the Help tab's sections.
  function topicText(tp) {
    const parts = [];
    const put = (s) => { const x = plain(s).trim(); if (x) parts.push(/[.!?;]$/.test(x) ? x : `${x}.`); };
    for (const x of [].concat(tp.lead || [])) put(x);
    for (const f of tp.facts || []) if (f && f[1] != null && f[1] !== '') put(`${f[0]}: ${f[1]}`);
    for (const s of tp.sections || []) {
      if (s.heading) put(s.heading);
      for (const x of [].concat(s.text || [])) put(x);
      for (const x of s.list || []) put(x);
      for (const c of s.choices || []) if (c && c[0]) put(`${c[0]} — ${c[1] || ''}`);
    }
    return parts.join(' ');
  }

  function helpEntries(app) {
    const out = [];
    const keys = new Set();
    const from = (o) => { for (const k of Object.keys(o || {})) keys.add(k); };
    from(SM.help && SM.help.topics);
    for (const p of SM.platforms.all()) from(p.topics);
    for (const c of SM.commands.all()) from(c.topics);
    if (typeof SM.info.keys === 'function') for (const k of SM.info.keys()) keys.add(k);
    from(OWN_TOPICS);
    const seen = new Set();
    for (const key of keys) {
      if (key.startsWith('form:')) continue;     // a dialog's fields, made when it opens
      const tp = SM.info.get(key);
      if (!tp || !tp.title) continue;
      const text = key === 'help:search' ? '' : topicText(tp);
      const sig = `${tp.title}\u0001${text.slice(0, 160)}`;
      if (seen.has(sig)) continue;
      seen.add(sig);
      out.push({ kind: 'help', label: String(tp.title), path: String(tp.kicker || 'Help').split(/\s+>\s+/), text, topic: key });
    }
    const view = app && app.helpView;
    if (view) {
      for (const h of view.querySelectorAll('h2[id^="help-"], h3[id^="help-"]')) {
        const parts = [];
        for (let n = h.nextElementSibling; n && !/^H[23]$/.test(n.tagName); n = n.nextElementSibling) if (!n.matches('table.sm-platforms, .sm-engine-versions, .sm-build')) parts.push(n.textContent);
        out.push({ kind: 'help', label: h.textContent, path: ['Help tab'], text: parts.join(' '), anchor: h.id.replace(/^help-/, '') });
      }
    }
    return out;
  }

  /* ---- read each time: the menu bar's menus and the open reports ------------------------ */
  function menuEntries(app) {
    const out = [];
    const names = app.menubar ? [...app.menubar.querySelectorAll('button[data-menu]')].map((b) => b.dataset.menu) : [];
    for (const name of names) {
      let items;
      try { items = app.menuItems(name); } catch (e) { continue; }
      walkMenu(items, [name], false, (it, labels, off) => {
        if (!leaf(it) || typeof it.action !== 'function') return;
        if (name === 'Help' && labels.length === 2 && it.label === 'Search…') return;     // this
        // Edit > Undo and Redo name the step they take back ("Undo Show Word
        // Cloud"): found by their own word, the step being their text, so that
        // they do not come before the feature itself
        const step = name === 'Edit' && labels.length === 2 ? /^(Undo|Redo)\s+(.+)$/.exec(String(it.label)) : null;
        out.push(prep({ kind: 'menu', label: last(labels), match: step ? step[1] : null, path: labels.slice(0, -1), text: [step ? step[2] : '', it.title ? String(it.title) : ''].filter(Boolean).join(' '), item: it, off, key: it.key || null }));
      });
    }
    return out;
  }

  const activeReport = (app) => (app && app.activeTab && app.activeTab.report) || null;
  const titleOf = (sec) => sec._outline.titleEl.textContent;
  const columnNames = (rep) => (rep && rep.table ? rep.table.columns.map((c) => c.name) : []);

  // An outline's red-triangle items as its button opens them: the outline's
  // own accessor, or, without it, for a top outline the report's top menu.
  function menuOf(sec, rep) {
    const o = sec._outline;
    try {
      if (typeof o.menuItems === 'function') return o.menuItems();
      if (sec.classList.contains('level-0')) {
        const g = rep.groups().find((x) => sec.querySelector(':scope > .sm-ob-head h2') && titleOf(sec) === (x.label ? `${rep.title} ${x.label}` : rep.title)) || groupOf(rep.table);
        return new SM.report.Ctx(rep, g, el('div'), g.label || '').topMenu();
      }
    } catch (e) { /* a menu that cannot be read now */ }
    return null;
  }

  // The titles of an outline and the outlines it is in, the top one first.
  function titleChain(sec, rep) {
    const out = [];
    for (let s = sec; s && rep.content.contains(s); s = s.parentElement ? s.parentElement.closest('.sm-ob') : null) if (s._outline) out.unshift(titleOf(s));
    return out;
  }

  // A report's text with its columns' names as ‹column›: the key that tells
  // an open report's item from the same item of its platform.
  function genericBy(names) {
    const list = names.filter((n) => n && n.length >= 2).sort((a, b) => b.length - a.length);
    const re = list.length ? new RegExp(`(^|[^\\p{L}\\p{N}])(${list.map(esc).join('|')})(?=$|[^\\p{L}\\p{N}])`, 'gu') : null;
    const set = new Set(names);
    return (s) => (set.has(s) ? COL : re ? String(s).replace(re, (m, a) => `${a}${COL}`) : String(s));
  }

  function liveEntries(app, commonLabels) {
    const out = [];
    const front = activeReport(app);
    const reps = (app.reports || []).slice().sort((a, b) => (b === front) - (a === front));
    let budget = 8000;
    for (const rep of reps) {
      if (!rep || !rep.content || !rep.platform) continue;
      const gen = genericBy(columnNames(rep));
      const list = choicesOf(platformTopics(rep.platform));
      for (const sec of rep.content.querySelectorAll('.sm-ob')) {
        const o = sec._outline;
        if (!o || !o.menuBtn || budget <= 0) continue;
        const top = sec.classList.contains('level-0');
        let items = menuOf(sec, rep);
        if (!Array.isArray(items)) continue;
        if (top) {
          // the report's own part: without the items every report has (indexed under ‹report›)
          items = items.slice();
          while (items.length && (!items[items.length - 1] || items[items.length - 1].separator || commonLabels.has(String(items[items.length - 1].label)))) items.pop();
        }
        const titles = titleChain(sec, rep);
        const slot = o.head.querySelector(':scope > .kvot-info-slot');
        const own = slot && slot.dataset.infoKey ? choicesOf([slot.dataset.infoKey]) : [];
        const outlineKey = top ? '' : gen(titleOf(sec));
        walkMenu(items, [], false, (it, labels, off) => {
          if (!leaf(it) || budget <= 0) return;
          budget--;
          out.push(prep({ kind: 'live', report: rep, front: rep === front, sec, titles, steps: labels, label: last(labels), path: [...titles, ...labels.slice(0, -1)],
            text: itemText(it, [...own, ...list], labels), item: it, off, tkey: `triangle|${rep.platform.id}|${outlineKey}|${labels.map(gen).join('\u0001')}` }));
        });
      }
    }
    return out;
  }

  /* ---- matching and ranking ----------------------------------------------------
     Every word must match: a whole word (or the same stem), the start of one,
     or (four letters or more) a part of one. A word in the label counts more
     than one in the path, and that more than one in the text; the results
     go by the weakest field any word needed (all in the label first), then
     by score. At an equal match the commands and red-triangle items come
     before help. */
  function fit(list, stems, w, ws) {
    let best = 0;
    for (let i = 0; i < list.length; i++) {
      const t = list[i];
      if (t === w || stems[i] === ws) return 3;
      if (best < 2 && w.length >= 2 && (t.startsWith(w) || (ws.length >= 3 && stems[i].length - ws.length <= 2 && stems[i].startsWith(ws)))) best = 2;
      else if (best < 1 && w.length >= 4 && t.includes(w)) best = 1;
    }
    return best;
  }
  const POINTS = { 3: [0, 30, 70, 100], 2: [0, 12, 28, 40], 1: [0, 3, 8, 12] };
  const KIND = { menu: 0, triangle: 0, live: 0, common: 1, help: 2 };

  function grade(e, q) {
    let tier = 3, score = 0;
    for (const { w, ws } of q) {
      const l = fit(e._l, e._ls, w, ws);
      if (l) { score += POINTS[3][l]; continue; }
      const p = fit(e._p, e._ps, w, ws);
      if (p) { score += POINTS[2][p]; tier = Math.min(tier, 2); continue; }
      const t = fit(e._t, e._ts, w, ws);
      if (t) { score += POINTS[1][t]; tier = 1; continue; }
      return null;
    }
    // the words one after another in the label: the phrase itself
    if (q.length > 1) {
      for (let i = 0; i + q.length <= e._l.length; i++) {
        if (q.every(({ w, ws }, k) => fit([e._l[i + k]], [e._ls[i + k]], w, ws) >= 2)) { score += 50; break; }
      }
    }
    if (e._l.length && fit([e._l[0]], [e._ls[0]], q[0].w, q[0].ws) >= 2) score += 10;
    score -= Math.max(0, e._l.length - q.length);       // of two labels, the shorter
    score -= 2 * e.path.length;                         // nearer the top of its menu
    if (e.kind === 'help') score -= 25;
    else if (e.kind === 'live') score += e.front ? 8 : -4;
    if (e.off) score -= 5;
    return { tier, score };
  }

  function rank(pool, text) {
    const q = words(text).map((w) => ({ w, ws: stem(w) }));
    if (!q.length) return [];
    const out = [];
    for (const e of pool) {
      const g = grade(e, q);
      if (g) out.push({ e, tier: g.tier, score: g.score });
    }
    out.sort((a, b) => b.tier - a.tier || b.score - a.score || KIND[a.e.kind] - KIND[b.e.kind] || a.e.path.length - b.e.path.length || a.e.label.localeCompare(b.e.label));
    return out;
  }

  // Everything that can be found now: the index, the menus, the open reports
  // (an item of the report in front that its platform's entry stands for
  // already is left out, unless it names one of several columns).
  function pool(S) {
    const out = index ? index.entries.slice() : [];
    out.push(...S.menu);
    for (const e of S.live) if (!(e.front && index && !e.tkey.includes(COL) && index.keys.has(e.tkey))) out.push(e);
    return out;
  }

  /* ---- an item found again in a live report -----------------------------------------
     fits(template, label, names): the columns a label names where the
     template has ‹column› (an empty list when it has none and the label is
     the same), or null. */
  function fits(tpl, label, names) {
    const l = String(label);
    if (!tpl.includes(COL)) return loose(tpl) === loose(l) ? [] : null;
    const m = new RegExp(`^${tpl.split(COL).map(esc).join('(.+?)')}$`, 's').exec(l);
    if (!m) return null;
    const cols = m.slice(1);
    return cols.every((c) => names.has(c)) ? cols : null;
  }

  // Down a menu by its labels: every item that fits, with its labels and columns.
  function follow(items, steps, names, labels = [], cols = []) {
    const out = [];
    const [first, ...rest] = steps;
    for (const it of items || []) {
      if (!it || it.separator || it.head || it.label == null) continue;
      const got = fits(first, it.label, names);
      if (!got) continue;
      const here = { labels: [...labels, String(it.label)], cols: [...cols, ...got] };
      if (!rest.length) { out.push({ item: it, ...here }); continue; }
      if (!it.submenu) continue;
      let sub = null;
      try { sub = typeof it.submenu === 'function' ? it.submenu() : it.submenu; } catch (e) { continue; }
      out.push(...follow(sub, rest, names, here.labels, here.cols));
    }
    return out;
  }

  // A platform's item (or one every report has: outline null) in a live report.
  function resolveIn(rep, outline, steps) {
    if (!rep || !rep.content) return [];
    const names = new Set(columnNames(rep));
    const out = [];
    for (const sec of rep.content.querySelectorAll('.sm-ob')) {
      if (!sec._outline || !sec._outline.menuBtn) continue;
      const top = sec.classList.contains('level-0');
      let cols = [];
      if (outline == null) { if (!top) continue; } else {
        if (top) continue;
        cols = fits(outline, titleOf(sec), names);
        if (!cols) continue;
      }
      const items = menuOf(sec, rep);
      for (const h of follow(items, steps, names)) out.push({ ...h, sec, cols: [...cols, ...h.cols] });
    }
    return out;
  }

  // An open report's item found again (the report may have been drawn anew since).
  function again(e) {
    const rep = e.report;
    if (!rep || !rep.content || !(SM.app.reports || []).includes(rep)) return [];
    const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);
    let sec = e.sec && rep.content.contains(e.sec) ? e.sec : null;
    if (!sec) sec = [...rep.content.querySelectorAll('.sm-ob')].find((s) => s._outline && s._outline.menuBtn && same(titleChain(s, rep), e.titles)) || null;
    if (!sec) return [];
    return follow(menuOf(sec, rep), e.steps, new Set()).map((h) => ({ ...h, sec, cols: [] }));
  }

  /* ---- why a menu command is greyed out ------------------------------------------------ */
  function whyOff(app, e) {
    const top = e.path[0], label = e.label;
    const t = app.current;
    if (/^Undo\b/.test(label)) return 'there is nothing to undo';
    if (/^Redo\b/.test(label)) return 'there is nothing to redo';
    if (label === 'Close All Reports') return 'no report is open';
    if (/^Save Project/.test(label)) return 'there is nothing to save yet: no table or notebook is open';
    if (top === 'Python' && /Report Script/.test(label)) return 'it takes the report in front: bring a report to the front first';
    if (!t) return 'no table is open: open one with File > Open, or one of File > Examples';
    if (top === 'Tables' && /^(Concatenate|Join|Update)/.test(label) && app.tables.length < 2) return 'it needs two open tables';
    if (top === 'Rows' && !t.selectedRows().length) return 'it works on the selected rows: select some rows first';
    if (top === 'Cols') {
      const sel = app.selectedColumns();
      if (!sel.length) return 'it works on the selected columns: click a column\'s heading first';
      if (label === 'Column Info…' && sel.length !== 1) return 'it shows one column: select just one';
      if (label === 'Continuous' && sel.some((c) => !c.isNumeric)) return 'a character column cannot be continuous';
    }
    return 'the menu has it greyed out now';
  }

  /* ---- what a result shows, and whether it can be chosen now ------------------------------- */
  function decorate(r, app) {
    const e = r.e;
    const front = activeReport(app);
    r.off = false;
    r.why = '';
    r.checked = null;
    r.hint = '';
    const state = (it) => { r.checked = it.checked != null ? !!it.checked : null; if (it.disabled) { r.off = true; r.why = it.title ? String(it.title) : 'the red triangle has it greyed out now'; } };
    if (e.kind === 'menu') {
      r.badge = 'Menu';
      if (e.off) { r.off = true; r.why = whyOff(app, e); }
      if (e.item.checked != null) r.checked = !!e.item.checked;
    } else if (e.kind === 'triangle') {
      r.badge = `Red triangle · ${e.platform.label}`;
      if (front && front.platform.id === e.platform.id) {
        const hits = resolveIn(front, e.outline, e.steps);
        r.hint = hits.length ? `applies to ${front.title}` : `says it is not in the red triangle of ${front.title}${e.when ? ` (it is there ${e.when})` : ''}`;
        if (hits.length) state(hits[0].item);
      } else if (!app.current && e.platform.needsTable !== false) {
        r.off = true;
        r.why = `${e.platform.label} needs a table: open one with File > Open, or one of File > Examples`;
      } else r.hint = `opens ${e.platform.label}${e.platform.launch ? '…' : ''} first${e.when ? `; it is there ${e.when}` : ''}`;
    } else if (e.kind === 'common') {
      r.badge = 'Red triangle · every report';
      if (!front) { r.off = true; r.why = 'it is in every report\'s red triangle: bring a report to the front first'; } else {
        r.hint = `applies to ${front.title}`;
        const hits = resolveIn(front, null, e.steps);
        if (hits.length) state(hits[0].item);
      }
    } else if (e.kind === 'live') {
      r.badge = e.front ? 'Report in front' : 'Open report';
      state(e.item);
    } else r.badge = e.topic ? 'Help' : 'Help tab';
    return r;
  }

  /* ---- the dialog ---------------------------------------------------------------------------- */
  let current = null;        // the search open now

  function glyph(cls) {
    return svg('svg', { viewBox: '0 0 16 16', width: 14, height: 14, 'aria-hidden': 'true', class: cls, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.7, 'stroke-linecap': 'round' },
      svg('circle', { cx: 6.7, cy: 6.7, r: 4.6 }), svg('path', { d: 'M10.2 10.2 L14.2 14.2' }));
  }

  function recent() {
    try {
      const v = JSON.parse(localStorage.getItem(RECENT) || '[]');
      return Array.isArray(v) ? v.filter((x) => typeof x === 'string' && x.trim()).slice(0, 6) : [];
    } catch (e) { return []; }
  }
  function remember(q) {
    const s = String(q || '').replace(/\s+/g, ' ').trim().slice(0, 80);
    if (!s) return;
    try { localStorage.setItem(RECENT, JSON.stringify([s, ...recent().filter((x) => x.toLowerCase() !== s.toLowerCase())].slice(0, 6))); } catch (e) { /* storage unavailable: not kept */ }
  }

  function open(app = SM.app, query = '') {
    if (!app) return null;
    if (current) { if (query) { current.input.value = query; refresh(current); } current.input.focus(); current.input.select(); return current; }
    SM.ui.closeMenus(0);
    const id = SM.util.uid('srch');
    const input = el('input', { type: 'text', class: 'sm-search-input', role: 'combobox', 'aria-autocomplete': 'list', 'aria-expanded': 'false', 'aria-controls': `${id}-list`,
      'aria-label': 'Search for a command, a red-triangle item or a help topic', placeholder: 'A command, a red-triangle item, a help topic…', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', enterkeyhint: 'go' });
    const status = el('p', { class: 'sm-search-status', role: 'status', 'aria-live': 'polite' });
    const list = el('ul', { class: 'sm-search-list', id: `${id}-list`, role: 'listbox', 'aria-label': 'What was found' });
    const extra = el('div', { class: 'sm-search-extra' });
    const S = { app, id, input, status, list, extra, results: [], active: -1, menu: [], live: [], back: document.activeElement, total: 0 };
    const body = el('div', { class: 'sm-search' }, el('div', { class: 'sm-search-field' }, glyph('sm-search-glyph'), input), status, list, extra);
    S.dlg = SM.ui.dialog({
      title: 'Search', body, info: 'help:search', className: 'sm-search-dialog',
      onClose: () => {
        if (current === S) current = null;
        const b = S.back;
        if (b && b.isConnected && typeof b.focus === 'function' && !document.querySelector('.sm-dialog')) b.focus({ preventScroll: true });
      },
    });
    current = S;
    input.value = query;
    input.addEventListener('input', () => refresh(S));
    input.addEventListener('keydown', (ev) => keys(S, ev));
    list.addEventListener('mousedown', (ev) => ev.preventDefault());      // the field keeps the focus
    S.menu = menuEntries(app);
    if (!index) {
      status.textContent = 'Reading the platforms\' red triangles…';
      ready(app).then(() => { if (current === S) { S.live = liveEntries(app, index.commonLabels); refresh(S); } });
    } else S.live = liveEntries(app, index.commonLabels);
    refresh(S);
    return S;
  }

  function close(S) { if (S && S.dlg) S.dlg.close(); }

  function refresh(S) {
    const text = S.input.value;
    S.words = words(text);
    S.told = null;
    if (!S.words.length) { S.results = []; S.total = 0; render(S); return; }
    const ranked = rank(pool(S), text);
    S.total = ranked.length;
    S.results = ranked.slice(0, MAX).map((r) => decorate(r, S.app));
    render(S);
  }

  function render(S) {
    const { list, extra, status, input, results } = S;
    list.replaceChildren(...results.map((r, i) => option(S, r, i)));
    list.hidden = !results.length;
    input.setAttribute('aria-expanded', String(results.length > 0));
    extra.replaceChildren();
    if (!S.words.length) {
      status.textContent = index ? '' : 'Reading the platforms\' red triangles…';
      extra.append(startView(S));
    } else if (!results.length) {
      status.textContent = index ? 'Nothing found.' : 'Nothing found yet: the platforms\' red triangles are still being read.';
      const help = el('button', { type: 'button', class: 'sm-btn small', text: 'Open the Help tab' });
      help.addEventListener('click', () => { close(S); S.app.showHelp(); });
      extra.append(el('div', { class: 'sm-search-none' },
        el('p', { text: `No command, red-triangle item or help text matches “${S.input.value.trim()}”.` }),
        el('p', null, 'Try fewer or shorter words, or look in the Help: ', help)));
    } else {
      status.textContent = S.total > results.length ? `The best ${results.length} of ${S.total} found` : `${S.total} found`;
    }
    setActive(S, results.length ? 0 : -1);
  }

  function startView(S) {
    const chips = (label, items) => {
      if (!items.length) return null;
      const row = el('div', { class: 'sm-search-chips' }, el('span', { class: 'sm-search-chiplabel', text: label }));
      for (const q of items) {
        const b = el('button', { type: 'button', class: 'sm-search-chip', text: q });
        b.addEventListener('click', () => { S.input.value = q; refresh(S); S.input.focus(); });
        row.append(b);
      }
      return row;
    };
    const was = recent();
    return el('div', { class: 'sm-search-start' },
      el('p', { text: 'Type a word or two: a command (stack), a red-triangle item (word cloud) or a help topic (row states). ↑ and ↓ move, Enter goes there, Escape closes.' }),
      chips('Recent', was), chips('Try', TRY.filter((q) => !was.some((x) => x.toLowerCase() === q))));
  }

  // A label, a level or a snippet with the words found marked, and ‹column›
  // and ‹report› set apart: text nodes and <mark>s only.
  function marked(text, ws) {
    const s = String(text);
    const out = [];
    let at = 0;
    const q = ws.map((w) => ({ w, ws: stem(w) }));
    for (const m of s.matchAll(WORD)) {
      const tok = fold(m[0]);
      let a = -1, b = -1;
      for (const { w, ws: st } of q) {
        let x = -1, y = -1;
        if (tok === w || stem(tok) === st) { x = 0; y = m[0].length; } else if (w.length >= 2 && tok.startsWith(w)) { x = 0; y = w.length; } else if (st.length >= 3 && stem(tok).length - st.length <= 2 && stem(tok).startsWith(st)) { x = 0; y = st.length; } else if (w.length >= 4 && tok.includes(w)) { x = tok.indexOf(w); y = x + w.length; }
        if (x >= 0 && y - x > b - a) { a = x; b = y; }
      }
      if (a < 0) continue;
      const from = m.index + Math.min(a, m[0].length), to = m.index + Math.min(b, m[0].length);
      if (from > at) out.push(s.slice(at, from));
      out.push(el('mark', { text: s.slice(from, to) }));
      at = to;
    }
    if (at < s.length) out.push(s.slice(at));
    return out;
  }
  function levelNodes(text, ws) {
    const out = [];
    String(text).split(/(‹column›|‹report›)/).forEach((part) => {
      if (!part) return;
      if (part === COL || part === REP) out.push(el('span', { class: 'sm-search-gen', text: part }));
      else out.push(...marked(part, ws));
    });
    return out;
  }

  // One line of the help or about text: the sentence with the most words found.
  function snippet(e, ws) {
    const text = String(e.text || '').trim();
    if (!text) return '';
    const parts = text.split(/(?<=[.!?;])\s+/);
    const q = ws.map((w) => ({ w, ws: stem(w) }));
    let best = parts[0], most = -1;
    for (const p of parts) {
      const tw = words(p), ts = tw.map(stem);
      const n = q.reduce((k, { w, ws: st }) => k + (fit(tw, ts, w, st) ? 1 : 0), 0);
      if (n > most) { best = p; most = n; }
    }
    return best.length > 220 ? `${best.slice(0, 217).replace(/\s+\S*$/, '')}…` : best;
  }

  function option(S, r, i) {
    const e = r.e;
    const li = el('li', { id: `${S.id}-${i}`, class: `sm-search-opt${r.off ? ' is-off' : ''}`, role: 'option', 'aria-selected': 'false', 'aria-disabled': r.off ? 'true' : null, dataset: { kind: e.kind } });
    const top = el('div', { class: 'sm-search-top' }, el('span', { class: 'sm-search-label' }, ...levelNodes(e.label, S.words)));
    if (r.checked != null) top.append(el('span', { class: `sm-search-state${r.checked ? ' is-on' : ''}`, text: r.checked ? '✓ on' : 'off' }));
    if (e.key) top.append(el('span', { class: 'sm-search-key', text: e.key }));
    top.append(el('span', { class: 'sm-search-badge', text: r.badge }));
    li.append(top);
    if (e.path.length) {
      const path = el('div', { class: 'sm-search-path' });
      e.path.forEach((lv, k) => {
        if (k) path.append(el('span', { class: 'sm-search-sep', 'aria-hidden': 'true', text: ' ▸ ' }));
        path.append(el('span', { class: 'sm-search-lv' }, ...levelNodes(lv, S.words)));
      });
      li.append(path);
    }
    const sn = snippet(e, S.words);
    if (r.off) li.append(el('div', { class: 'sm-search-why', text: `Not available: ${r.why}.` }));
    else if (sn || r.hint) li.append(el('div', { class: 'sm-search-snip' }, ...(sn ? marked(sn, S.words) : []), r.hint ? el('span', { class: 'sm-search-hint', text: `${sn ? ' · ' : ''}Enter ${r.hint}` }) : null));
    li.addEventListener('mousemove', () => { if (S.active !== i) setActive(S, i, false); });
    li.addEventListener('click', () => choose(S, i));
    return li;
  }

  function setActive(S, i, scroll = true) {
    const opts = S.list.children;
    if (S.active >= 0 && opts[S.active]) opts[S.active].setAttribute('aria-selected', 'false');
    S.active = i;
    const o = i >= 0 ? opts[i] : null;
    if (o) {
      o.setAttribute('aria-selected', 'true');
      S.input.setAttribute('aria-activedescendant', o.id);
      if (scroll) o.scrollIntoView({ block: 'nearest' });
    } else S.input.removeAttribute('aria-activedescendant');
  }

  function keys(S, ev) {
    if (ev.isComposing) return;
    const n = S.results.length;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      if (!n) return;
      const d = ev.key === 'ArrowDown' ? 1 : -1;
      setActive(S, S.active < 0 ? (d > 0 ? 0 : n - 1) : (S.active + d + n) % n);
    } else if (ev.key === 'PageDown' || ev.key === 'PageUp') {
      if (!n) return;
      ev.preventDefault();
      setActive(S, Math.max(0, Math.min(n - 1, (S.active < 0 ? 0 : S.active) + (ev.key === 'PageDown' ? 6 : -6))));
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (S.active >= 0) choose(S, S.active);
    }
  }

  // A greyed-out result says why, and the search stays open.
  function tell(S, i, text) {
    S.status.textContent = text;
    const o = S.list.children[i];
    if (o) { o.classList.remove('is-told'); void o.offsetWidth; o.classList.add('is-told'); }
  }

  /* ---- choosing ----------------------------------------------------------------------------- */
  // An item's action as its menu runs it.
  function run(it) {
    Promise.resolve().then(() => it.action()).catch((err) => SM.ui.toast(err && err.message ? err.message : String(err), { error: true }));
  }

  function choose(S, i) {
    const r = S.results[i];
    if (!r) return;
    const e = r.e, app = S.app;
    if (r.off) { tell(S, i, `${e.label}: not available — ${r.why}.`); return; }
    remember(S.input.value);
    if (e.kind === 'menu') { close(S); run(e.item); return; }
    if (e.kind === 'help') {
      close(S);
      if (e.topic && typeof KvotInfo !== 'undefined' && SM.info.get(e.topic)) KvotInfo.open(e.topic); else app.showHelp(e.anchor || null);
      return;
    }
    if (e.kind === 'live') {
      const hits = again(e);
      if (!hits.length) { tell(S, i, `${e.label} is no longer in that report's red triangle.`); return; }
      close(S);
      const tab = app.tabOf(e.report);
      if (tab) app.showTab(tab);
      apply(e.report, hits);
      return;
    }
    const front = activeReport(app);
    if (e.kind === 'common') {
      const hits = resolveIn(front, null, e.steps);
      if (!hits.length) { tell(S, i, `${e.label} is not in the red triangle of ${front ? front.title : 'the report in front'} now.`); return; }
      close(S);
      apply(front, hits);
      return;
    }
    // a platform's item: in the report in front, or in a new one
    if (front && front.platform.id === e.platform.id) {
      const hits = resolveIn(front, e.outline, e.steps);
      if (!hits.length) { tell(S, i, `${e.label} is not in the red triangle of ${front.title}${e.when ? `: it is there ${e.when}` : ': its columns may not have it'}.`); return; }
      close(S);
      apply(front, hits);
      return;
    }
    close(S);
    launch(app, e.platform).then((rep) => {
      if (!rep) return;      // cancelled
      const hits = resolveIn(rep, e.outline, e.steps);
      if (!hits.length) { SM.ui.toast(`${rep.title}: ${e.label} is not in its red triangle${e.when ? ` (it is there ${e.when})` : ' (its columns may not have it)'}`, { ms: 7000 }); return; }
      apply(rep, hits, { launched: true });
    });
  }

  /* The platform launched as its menu item launches it, and the report it
     makes once its first run is done; null when the launch is cancelled. */
  function launch(app, p) {
    const before = new Set(app.reports);
    const had = new Set(SM.ui.dialogs);
    app.launch(p.id);
    const made = () => app.reports.find((r) => !before.has(r) && r.platform && r.platform.id === p.id) || null;
    const now = made();
    if (now) return drawn(now);
    const dlg = SM.ui.dialogs.find((d) => !had.has(d));
    if (!dlg) return Promise.resolve(null);       // no launch dialog (no table: the launch said so)
    return new Promise((resolve) => {
      // the report's tab comes when OK is pressed; the dialog goes when it closes
      const mo = new MutationObserver(() => {
        const r = made();
        if (r) { mo.disconnect(); resolve(drawn(r)); } else if (!SM.ui.dialogs.includes(dlg)) { mo.disconnect(); resolve(null); }
      });
      mo.observe(document.body, { childList: true, subtree: true });
    });
  }

  // A report once it has been drawn: now, or at the end of its run.
  function drawn(r) {
    return new Promise((resolve) => {
      if (!r.body.classList.contains('is-running') && r.content.firstChild && !r.content.querySelector('.sm-waiting')) { resolve(r); return; }
      const off = r.on('done', () => { off(); resolve(r); });
    });
  }

  /* Run a found item in its report, as its red triangle would, and say what
     was done. hits: the places it was found (the first is used; several
     columns are said). After a launch an item already on is left on. */
  function apply(rep, hits, { launched = false } = {}) {
    const hit = hits[0];
    const it = hit.item;
    const name = hit.labels.length > 1 ? `${last(hit.labels)} (${hit.labels.slice(0, -1).join(' ▸ ')})` : last(hit.labels);
    if (it.submenu && typeof it.action !== 'function') { reveal(hit); return; }
    if (it.disabled) { SM.ui.toast(`${name}: not available in ${rep.title} now${it.title ? `: ${it.title}` : ''}`, { ms: 6000 }); return; }
    const on = it.checked != null ? !!it.checked : null;
    const tuples = [...new Map(hits.map((h) => [h.cols.join('\u0001'), h.cols])).values()].filter((c) => c.length);
    let where = '';
    if (hit.cols.length) {
      where = ` for ${hit.cols.join(', ')}`;
      if (tuples.length > 1) where += `, the first of ${tuples.length} (the others: ${tuples.slice(1).map((c) => c.join(', ')).join('; ')}; Search lists each under Report in front)`;
    }
    if (launched && on === true) { SM.ui.toast(`${name} is on in ${rep.title}${where}`, { ms: 6000 }); return; }
    const verb = on == null ? 'Applied' : on ? 'Turned off' : 'Turned on';
    // (an item that opens a dialog says nothing unless a column is to be told: the dialog shows)
    if (!/…$/.test(String(it.label)) || where) SM.ui.toast(`${verb} ${name} in ${rep.title}${where}`, { ms: tuples.length > 1 ? 9000 : 5000 });
    run(it);
  }

  // A found item that opens a submenu: the outline's red triangle opened down to it.
  function reveal(hit) {
    const o = hit.sec._outline;
    if (!o.menuBtn) return;
    o.menuBtn.scrollIntoView({ block: 'nearest' });
    o.menuBtn.click();
    for (const label of hit.labels) {
      const menus = document.querySelectorAll('.sm-menu');
      const m = menus[menus.length - 1];
      const b = m && [...m.querySelectorAll('button')].find((x) => x.querySelector('.sm-label') && x.querySelector('.sm-label').textContent === label);
      if (!b) break;
      b.click();
    }
  }

  /* ---- ways in: the menu bar's button, Help > Search…, ctrl/⌘+K ---------------------------- */
  const OWN_TOPICS = {
    'help:search': {
      kicker: 'Help', title: 'Search',
      lead: 'Finds a feature by a word or two and takes you to it: a command of the menu bar, an item of a platform\'s red triangle, an item of an open report\'s red triangle, or a help text. Every word must be found; the start of a word is enough (`clou` finds Show Word Cloud), and a plural finds the singular.',
      sections: [
        { heading: 'What it finds', choices: [
          ['Menu', 'A command of the menu bar, in its submenu. One that is greyed out now says why (no table open, no column or row selected) and does nothing.'],
          ['Red triangle', 'An item of a platform\'s red triangle. With a report of that platform in front it applies to that report; otherwise the platform\'s launch dialog opens, and the item is applied once the report has run (an item that is on by itself is left on). Cancel the launch and nothing happens.'],
          ['‹column›', 'A level named after a column: the red triangle of a column\'s outline (Distribution\'s), or a submenu of columns. The item goes to the report\'s first such column, and the message says so when it has several.'],
          ['Red triangle · every report', 'Set α Level, Local Data Filter, Column Switcher, Redo, Save Script, Show Python Code and Axis Settings, which every report\'s top red triangle has: for the report in front.'],
          ['Report in front, Open report', 'An item of the red triangle of an outline of an open report, its columns by name: the report comes to the front and the item applies to it.'],
          ['Help, Help tab', 'An (i) topic opens in this panel; a section of the Help tab opens there.'],
        ] },
        { heading: 'Order', text: 'A word in an item\'s name counts more than one in its path, and that more than one in its help text; at an equal match, commands and red-triangle items come before help. ✓ on marks an item that is on in the report it applies to: choosing it turns it off, as the red triangle would.' },
        { heading: 'Keys', choices: [
          ['ctrl/⌘+K', 'Opens the search from anywhere, a text field too (on a Mac ⌘K; there ctrl+K in a text field is the field\'s own).'],
          ['↑ ↓, Page Up, Page Down', 'Move through what was found.'],
          ['Enter', 'Goes to the result marked, as a click does.'],
          ['Escape', 'Closes the search.'],
        ] },
        { heading: 'Recent', text: 'With nothing typed it shows your last searches (kept in this browser only) and a few to try.' },
      ],
    },
  };
  SM.info.add(OWN_TOPICS);

  SM.commands.register({ menu: 'Help', label: 'Search…', order: 15, key: 'ctrl K', about: 'Find a command, a red-triangle item or a help topic by a word or two, and go to it', action: (app) => { open(app); } });

  // A field the keys type into (where ctrl+K on a Mac deletes to the end of the line).
  function typing(t) {
    if (!t || !t.tagName) return false;
    if (t.isContentEditable || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return true;
    return t.tagName === 'INPUT' && !/^(button|checkbox|radio|range|color|file|submit|reset|image)$/i.test(t.type || 'text');
  }

  function onKey(ev) {
    if (ev.defaultPrevented || ev.isComposing || ev.altKey || ev.shiftKey || !ev.key || ev.key.toLowerCase() !== 'k') return;
    const meta = ev.metaKey && !ev.ctrlKey, ctrl = ev.ctrlKey && !ev.metaKey;
    if (!meta && !ctrl) return;
    // the page's shortcut (⌘K on a Mac, ctrl+K elsewhere) works in a text field too; the other is the field's
    if (typing(ev.target) && (MAC ? !meta : !ctrl)) return;
    if (current) { ev.preventDefault(); current.input.focus(); current.input.select(); return; }
    if (SM.ui.dialogs.length) return;       // another dialog is in front: its keys are its own
    ev.preventDefault();
    open(SM.app);
  }

  SM.whenApp((app) => {
    const end = app.menubar && app.menubar.querySelector('.sm-menuend');
    if (end && !end.querySelector('.sm-searchbtn')) {
      const b = el('button', { type: 'button', class: 'sm-searchbtn', 'aria-label': `Search for a feature (${SHORTCUT})`, 'aria-haspopup': 'dialog', 'aria-keyshortcuts': MAC ? 'Meta+K' : 'Control+K' },
        glyph('sm-searchbtn-glyph'), el('span', { class: 'sm-searchbtn-text', text: 'Search' }), el('kbd', { class: 'sm-searchbtn-key', text: SHORTCUT }));
      b.addEventListener('click', () => open(app));
      end.prepend(b);
    }
    document.addEventListener('keydown', onKey, true);
  });

  /* For the tests: the results as plain data (as the dialog would show them
     now), the crawl's counts, and the index once it is read. */
  function query(text, n = MAX) {
    const app = SM.app;
    const S = { menu: menuEntries(app), live: index ? liveEntries(app, index.commonLabels) : [] };
    return rank(pool(S), text).slice(0, n).map((r) => {
      decorate(r, app);
      const e = r.e;
      return { kind: e.kind, label: e.label, path: e.path.slice(), where: [...e.path, e.label], badge: r.badge, off: r.off, why: r.why, checked: r.checked, hint: r.hint, when: e.when || null, tier: r.tier, score: r.score,
        platform: e.platform ? e.platform.id : e.report ? e.report.platform.id : null, topic: e.topic || null, anchor: e.anchor || null };
    });
  }

  SM.search = Object.freeze({
    open: (q) => open(SM.app, q || ''),
    ready: () => ready(SM.app),
    query,
    stats: () => (index ? JSON.parse(JSON.stringify(index.stats)) : null),
    current: () => current,
    isMac: MAC,
  });
}(typeof self !== 'undefined' ? self : this));
