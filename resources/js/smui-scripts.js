/* ==========================================================================
   SMUI.HTML: TABLE SCRIPTS (JMP's scripts saved with a data table)

   A table keeps scripts (t.scripts, smui-table.js, which checks them when a
   table comes from a file), listed in the Table panel with a run mark:

     kind 'launch'   { name, platform, kind, spec }, spec by column names as
                     Recall keeps a launch: { roles: { key: [names] },
                     options, extra }; a platform's own parts may also be
                     beside roles and options ({ roles, options, effects }, as
                     the DOE platforms write a design's model). Running it
                     opens the platform's launch dialog filled in (a design's
                     Model: its effects, a split plot's random whole plots).
     kind 'report'   { name, platform, kind, spec, idNames }: a report's spec
                     as the report keeps it (column ids in its roles, options,
                     filters and closed outlines) and the names of the ids it
                     uses. Running it opens the report itself, its ids mapped
                     by name to the table's columns now (as a project does),
                     so it comes back as it was saved, on this table or on the
                     same table opened again from a file.

   A column that is not in the table any more: a toast names it, and the
   launch dialog opens with the columns that are. Report > Save > Save
   Script to Data Table… stores a report as a script (a script of the same
   name is replaced). The Table panel's right click: Run Script, Rename…,
   Delete; each change is one Undo step. Renaming a column renames it in the
   scripts (smui-table.js).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el } = SM.util;
  const toast = (text, opts) => SM.ui.toast(text, opts);

  const nameList = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}` : xs[0] || '');

  /* A launch script's spec as Recall takes it: { roles, options, extra },
     the platform's own parts beside roles and options put into extra. */
  function launchRecall(spec) {
    const { roles, options, extra, roleNames, ...rest } = spec || {};
    return { roles: roles || {}, options: options || {}, extra: { ...rest, ...(extra && typeof extra === 'object' ? extra : {}) } };
  }

  /* The column names a script uses (roles, and names in a platform's part). */
  function namesOf(sc) {
    const out = new Set();
    if (sc.kind === 'report') {
      const idNames = sc.idNames || {};
      for (const ids of Object.values((sc.spec && sc.spec.roles) || {})) for (const id of ids || []) if (typeof id === 'string' && idNames[id]) out.add(idNames[id]);
      return [...out];
    }
    const sp = launchRecall(sc.spec);
    for (const names of Object.values(sp.roles)) for (const n of names || []) if (typeof n === 'string') out.add(n);
    const walk = (v, depth) => {
      if (!v || typeof v !== 'object' || depth > 12) return;
      if (Array.isArray(v)) { v.forEach((x) => walk(x, depth + 1)); return; }
      for (const k of Object.keys(v)) { if (/names$/i.test(k) && Array.isArray(v[k])) v[k].forEach((n) => { if (typeof n === 'string') out.add(n); }); else walk(v[k], depth + 1); }
    };
    walk(sp.extra, 0);
    return [...out];
  }

  /* A report script as a launch by names (for its dialog, when a column is
     missing): the roles by name, the options, the platform's own parts. */
  function asRecall(sc) {
    const sp = sc.spec || {};
    const idNames = sc.idNames || {};
    const roles = {};
    for (const [k, ids] of Object.entries(sp.roles || {})) roles[k] = (ids || []).map((id, i) => idNames[id] || ((sp.roleNames && sp.roleNames[k]) || [])[i] || null).filter(Boolean);
    const extra = {};
    for (const [k, v] of Object.entries(sp)) if (!['roles', 'roleNames', 'options', 'filter', 'switcher', 'closed', 'autoRecalc', 'showCode'].includes(k)) extra[k] = v;
    return { roles, options: sp.options || {}, extra };
  }

  /* Run a script of table t: its dialog filled in, or its report. */
  function run(t, sc) {
    const p = SM.platforms.get(sc.platform);
    if (!p) { toast(`${sc.name}: there is no platform ${sc.platform} here`, { error: true }); return null; }
    const missing = namesOf(sc).filter((n) => !t.col(n));
    if (missing.length) toast(`${sc.name}: ${nameList(missing)} ${missing.length > 1 ? 'are' : 'is'} not in ${t.name}; the dialog opens with the columns that are`, { error: true });
    const onOK = (sp) => SM.app.openReport(p, sp, t);
    if (sc.kind === 'report' && !missing.length) return SM.app.openReport(p, SM.specs.remap(sc.spec, t, sc.idNames), t);
    const recall = sc.kind === 'report' ? asRecall(sc) : launchRecall(sc.spec);
    if (!p.launch) {
      // a platform with no dialog (Tabulate): its report, with the columns there are
      if (sc.kind === 'report') return SM.app.openReport(p, SM.specs.remap(sc.spec, t, sc.idNames), t);
      const roles = {};
      for (const [k, names] of Object.entries(recall.roles || {})) roles[k] = (names || []).map((n) => t.col(n)).filter(Boolean).map((c) => c.id);
      return SM.app.openReport(p, { roles, options: recall.options || {} }, t);
    }
    return SM.launch.open({ platform: p, table: t, recall, onOK });
  }

  /* The ids a spec uses: every column id of the table found in its text. */
  function idsIn(spec, t) {
    const text = JSON.stringify(spec);
    const out = {};
    const esc = (x) => String(x).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    for (const c of t.columns) if (new RegExp(`(^|[^\\w-])${esc(c.id)}(?![\\w-])`).test(text)) out[c.id] = c.name;
    return out;
  }

  /* Report > Save > Save Script to Data Table…: the report as a script of
     its table, under a name (a script of that name is replaced). */
  async function saveFromReport(rep) {
    const t = rep && rep.table;
    if (!t) { toast('This report has no data table to keep its script'); return null; }
    const base = rep.platform.label;
    const v = await SM.ui.form({
      title: 'Save Script to Data Table', info: 'table:scripts',
      lead: `The report, as a script of ${t.name}: its name in the Table panel runs it again, with its columns, options and closed outlines.`,
      fields: [{ key: 'name', label: 'Script name', value: base, help: 'The name in the Table panel\'s list of scripts, one line, at most 200 characters (the platform\'s name at the start). A script of the same name is replaced.' }],
      validate: (x) => (!SM.table.cleanName(x.name) ? 'Give the script a name' : null),
    });
    if (!v) return null;
    const name = SM.table.cleanName(v.name).slice(0, 200).trim();
    const j = rep.toJSON();
    const script = { name, platform: j.platform, kind: 'report', spec: j.spec, idNames: idsIn(j.spec, t) };
    const had = (t.scripts || []).some((x) => x.name === name);
    if (SM.app && SM.app.record) SM.app.record(t, 'Save Script');
    t.setScripts([...(t.scripts || []).filter((x) => x.name !== name), script]);
    toast(`${had ? 'Replaced' : 'Saved'} the script ${name} in ${t.name}: the Table panel runs it`);
    return t.scripts.find((x) => x.name === name) || null;
  }

  async function rename(t, sc) {
    const v = await SM.ui.form({
      title: 'Rename Script', info: 'table:scripts',
      fields: [{ key: 'name', label: 'Script name', value: sc.name, help: 'The script\'s new name, one line, at most 200 characters; another script of the table cannot have it.' }],
      validate: (x) => { const n = SM.table.cleanName(x.name).slice(0, 200).trim(); return !n ? 'Give the script a name' : n !== sc.name && (t.scripts || []).some((y) => y.name === n) ? `${t.name} has a script ${n} already` : null; },
    });
    if (!v) return;
    const n = SM.table.cleanName(v.name).slice(0, 200).trim();
    if (n === sc.name) return;
    if (SM.app && SM.app.record) SM.app.record(t, 'Rename Script');
    t.setScripts((t.scripts || []).map((x) => (x.name === sc.name ? { ...x, name: n } : x)));
  }

  function remove(t, sc) {
    if (SM.app && SM.app.record) SM.app.record(t, 'Delete Script');
    t.setScripts((t.scripts || []).filter((x) => x.name !== sc.name));
    toast(`Deleted the script ${sc.name} (Edit > Undo brings it back)`);
  }

  function menuItems(t, sc) {
    return [
      { head: sc.name },
      { label: 'Run Script', action: () => run(t, sc) },
      { label: 'Rename…', action: () => rename(t, sc) },
      { label: 'Delete', action: () => remove(t, sc) },
    ];
  }

  // the run mark: JMP's green triangle
  function runMark() {
    return SM.util.svg('svg', { viewBox: '0 0 10 10', width: 10, height: 10, class: 'sm-scriptrun', 'aria-hidden': 'true' }, SM.util.svg('path', { d: 'M2 1.2 L8.6 5 L2 8.8 Z', fill: 'currentColor' }));
  }

  /* The Table panel's list of the table's scripts (smui-panels.js). */
  function list(t) {
    const scripts = (t && t.scripts) || [];
    if (!scripts.length) return null;
    const ul = el('ul', { class: 'sm-scripts', 'aria-label': `Scripts of ${t.name}` });
    for (const sc of scripts) {
      const kind = sc.kind === 'report' ? 'its report' : 'its launch dialog, filled in';
      const b = el('button', { type: 'button', class: 'sm-script', title: `${sc.name}: runs ${kind} (${(SM.platforms.get(sc.platform) || { label: sc.platform }).label}). Right click to rename or delete it.` }, runMark(), el('span', { class: 'sm-scriptname', text: sc.name }));
      b.addEventListener('click', () => run(t, sc));
      b.addEventListener('contextmenu', (ev) => { ev.preventDefault(); SM.ui.menu(menuItems(t, sc), { x: ev.clientX, y: ev.clientY }); });
      ul.append(el('li', null, b));
    }
    return el('div', { class: 'sm-scriptbox' }, el('div', { class: 'sm-scripthead' }, el('span', { text: 'Scripts' }), typeof KvotInfo !== 'undefined' ? KvotInfo.slot('table:scripts') : null), ul);
  }

  SM.info.add({
    'table:scripts': {
      kicker: 'Table', title: 'Table scripts',
      lead: 'Scripts kept with the data table, as JMP keeps them: a click on one runs it. A design keeps its Model; Save > Save Script to Data Table in a report keeps that report.',
      sections: [
        { heading: 'Running one', choices: [
          ['A design\'s Model', 'Opens the platform\'s launch dialog filled in: the Y columns, the model\'s effects (a split plot\'s whole plots as a random effect) and its options, for you to press OK.'],
          ['A saved report', 'Opens the report as it was saved: its columns, its options, its filter and its closed outlines. The columns are found by their names, so it runs on the same table opened again from a file or a project.'],
          ['A column that is not there', 'A message names it, and the launch dialog opens with the columns that are, for you to finish.'],
        ] },
        { heading: 'The right click', choices: [['Run Script', 'As a click.'], ['Rename…', 'A new name for the script, one line.'], ['Delete', 'Takes the script away. Edit > Undo brings it back, as it takes back a rename or a saved script.']] },
        { heading: 'Kept', text: 'Save Table and projects keep the scripts. Renaming a column renames it in the scripts too. A script from a file is checked: its name, its platform and its settings, and what is not right is left out. The page does not read the JSL scripts of .jmp files.' },
      ],
    },
  });

  SM.scripts = Object.freeze({ run, saveFromReport, rename, remove, list, menuItems, namesOf, asRecall, launchRecall, idsIn });
}(typeof self !== 'undefined' ? self : this));
