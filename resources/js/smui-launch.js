/* ==========================================================================
   SMUI.HTML: LAUNCH DIALOGS

   JMP's launch dialog: the table's columns on the left, the roles in the
   middle, the actions on the right. Select columns and press a role's
   button, drag them onto a role, or double-click one to put it in the
   first role that takes it. A platform describes its dialog:

     launch: {
       lead: 'one line on what the platform does',
       roles: [{ key: 'y', label: 'Y, Columns', min: 1, max: Infinity,
                 types: ['continuous', 'ordinal', 'nominal'], numeric: false,
                 hint: 'required', info: 'topic key' }, ...],
       options: [{ key, label, type: 'check'|'number'|'select'|'text',
                   value, choices: [[value, label], ...], hint }],
       extra(api) -> { el, read() -> { roles?, options?, ... } }   (optional)
       validate(spec, table) -> an error message or null
     }

   Recall fills the dialog with the last launch of the platform, matched by
   column name, so it works across tables with the same columns.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, typeIcon, TYPE_LABEL } = SM.util;

  const last = new Map();   // platform id -> { roles: { key: [names] }, options }
  const MIME = 'application/x-smui-columns';

  function roleAccepts(role, c) {
    if (role.numeric && !c.isNumeric) return `${role.label} needs a numeric column; ${c.name} is character`;
    if (role.types && !role.types.includes(c.modelingType)) {
      return `${role.label} takes ${role.types.map((t) => TYPE_LABEL[t].toLowerCase()).join(' or ')} columns; ${c.name} is ${TYPE_LABEL[c.modelingType].toLowerCase()} (right click it to change)`;
    }
    return null;
  }

  function open({ platform, table, spec = null, onOK }) {
    const L = platform.launch || { roles: [] };
    const roles = L.roles || [];
    const state = {};
    for (const r of roles) state[r.key] = [];
    const selected = new Set();
    let anchor = null;

    // ---- the column list
    const filter = el('input', { type: 'search', placeholder: 'Filter columns', 'aria-label': 'Filter columns' });
    const count = el('span', { class: 'sm-count' });
    const list = el('ul', { class: 'sm-pick-list', role: 'listbox', 'aria-multiselectable': 'true', 'aria-label': 'Columns', tabindex: '0' });
    const msg = el('div', { class: 'sm-launch-msg', role: 'status' });

    const fillList = () => {
      list.replaceChildren();
      const f = filter.value.trim().toLowerCase();
      const cols = table.columns.filter((c) => !f || c.name.toLowerCase().includes(f));
      count.textContent = `${table.columns.length} columns`;
      for (const c of cols) {
        const li = el('li', { role: 'option', draggable: 'true', dataset: { id: c.id }, 'aria-selected': String(selected.has(c.id)) },
          typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }));
        if (selected.has(c.id)) li.classList.add('is-selected');
        li.title = `${c.name}: ${TYPE_LABEL[c.modelingType]}, ${c.dataType}`;
        list.append(li);
      }
    };

    const visibleIds = () => [...list.querySelectorAll('li')].map((li) => li.dataset.id);

    // Mark the selection on the items in place: rebuilding the list under the
    // pointer would cancel a drag that is about to start.
    const markList = () => {
      for (const li of list.querySelectorAll('li')) {
        const on = selected.has(li.dataset.id);
        li.classList.toggle('is-selected', on);
        li.setAttribute('aria-selected', String(on));
      }
    };

    list.addEventListener('mousedown', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      const id = li.dataset.id;
      if (ev.shiftKey && anchor) {
        const ids = visibleIds();
        const a = ids.indexOf(anchor), b = ids.indexOf(id);
        if (!(ev.metaKey || ev.ctrlKey)) selected.clear();
        for (let k = Math.min(a, b); k <= Math.max(a, b); k++) selected.add(ids[k]);
      } else if (ev.metaKey || ev.ctrlKey) {
        if (selected.has(id)) selected.delete(id); else selected.add(id);
        anchor = id;
      } else if (!selected.has(id)) {
        selected.clear();
        selected.add(id);
        anchor = id;
      }
      markList();
    });
    list.addEventListener('click', (ev) => {
      const li = ev.target.closest('li');
      if (!li || ev.shiftKey || ev.metaKey || ev.ctrlKey) return;
      selected.clear();
      selected.add(li.dataset.id);
      anchor = li.dataset.id;
      markList();
    });
    list.addEventListener('dblclick', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      const c = table.col(li.dataset.id);
      const role = roles.find((r) => !roleAccepts(r, c) && state[r.key].length < (r.max ?? Infinity)) || roles.find((r) => !roleAccepts(r, c));
      if (role) addTo(role, [c.id]);
      else msg.textContent = roles.length ? roleAccepts(roles[0], c) : '';
    });
    list.addEventListener('keydown', (ev) => {
      const ids = visibleIds();
      if (!ids.length) return;
      let i = anchor ? ids.indexOf(anchor) : -1;
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        ev.preventDefault();
        i = Math.max(0, Math.min(ids.length - 1, i + (ev.key === 'ArrowDown' ? 1 : -1)));
        if (!ev.shiftKey) selected.clear();
        selected.add(ids[i]);
        anchor = ids[i];
        markList();
        list.querySelector(`li[data-id="${ids[i]}"]`)?.scrollIntoView({ block: 'nearest' });
      } else if (ev.key === 'Enter' && selected.size && roles.length) {
        ev.preventDefault();
        ev.stopPropagation();
        const c = table.col([...selected][0]);
        const role = roles.find((r) => !roleAccepts(r, c)) || roles[0];
        addTo(role, [...selected]);
      }
    });
    list.addEventListener('dragstart', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      if (!selected.has(li.dataset.id)) { selected.clear(); selected.add(li.dataset.id); anchor = li.dataset.id; }
      ev.dataTransfer.setData(MIME, JSON.stringify([...selected]));
      ev.dataTransfer.setData('text/plain', [...selected].map((id) => table.col(id).name).join('\n'));
      ev.dataTransfer.effectAllowed = 'copy';
    });
    list.addEventListener('contextmenu', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      ev.preventDefault();
      const c = table.col(li.dataset.id);
      SM.ui.menu([
        { head: c.name },
        ...['continuous', 'ordinal', 'nominal'].map((t) => ({
          label: TYPE_LABEL[t], checked: c.modelingType === t, disabled: t === 'continuous' && !c.isNumeric,
          action: () => { table.setType(c.id, { modelingType: t }); fillList(); renderRoles(); },
        })),
      ], { x: ev.clientX, y: ev.clientY });
    });
    filter.addEventListener('input', fillList);

    // ---- the roles, their buttons as wide as the longest label
    const roleBox = el('div', { class: 'sm-roles' });
    const longest = Math.max(0, ...roles.map((r) => r.label.length));
    roleBox.style.setProperty('--sm-role-w', `${Math.max(104, Math.min(190, Math.round(22 + longest * 7.2)))}px`);
    const roleEls = {};
    const addTo = (role, ids) => {
      msg.textContent = '';
      msg.classList.remove('is-info');
      // Several columns go in in the table's order, as JMP casts them.
      const cols = ids.map((id) => table.col(id)).filter(Boolean).sort((a, b) => table.colIndex(a) - table.colIndex(b));
      const bad = cols.map((c) => roleAccepts(role, c)).filter(Boolean);
      const ok = cols.filter((c) => !roleAccepts(role, c));
      if (bad.length) msg.textContent = bad[0];
      if (!ok.length) return;
      const max = role.max ?? Infinity;
      let cur = state[role.key].filter((id) => !ok.some((c) => c.id === id));
      cur = cur.concat(ok.map((c) => c.id));
      if (cur.length > max) cur = cur.slice(cur.length - max);
      state[role.key] = cur;
      renderRoles();
    };
    const roleSel = {};
    const roleWatchers = [];
    const renderRoles = () => {
      renderRoleLists();
      for (const fn of roleWatchers) { try { fn(state); } catch (e) { console.error(e); } }
    };
    const renderRoleLists = () => {
      for (const r of roles) {
        const ul = roleEls[r.key].list;
        ul.replaceChildren();
        const ids = state[r.key];
        ul.classList.toggle('is-empty', !ids.length);
        roleEls[r.key].row.classList.remove('is-missing');
        for (const id of ids) {
          const c = table.col(id);
          if (!c) continue;
          const li = el('li', { dataset: { id }, role: 'option', 'aria-selected': String(roleSel[r.key]?.has(id) || false) }, typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }));
          if (roleSel[r.key]?.has(id)) li.classList.add('is-selected');
          ul.append(li);
        }
      }
    };
    for (const r of roles) {
      roleSel[r.key] = new Set();
      const btn = el('button', { type: 'button', class: `sm-btn${r.min ? ' required' : ''}`, text: r.label });
      btn.addEventListener('click', () => { if (selected.size) addTo(r, [...selected]); else msg.textContent = 'Select columns on the left first.'; });
      const ul = el('ul', { class: 'sm-role-list', role: 'listbox', 'aria-label': r.label, dataset: { hint: r.hint || (r.min ? 'required' : 'optional') } });
      ul.addEventListener('click', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        const s = roleSel[r.key];
        if (!(ev.metaKey || ev.ctrlKey)) { const had = s.has(li.dataset.id) && s.size === 1; s.clear(); if (had) { renderRoles(); return; } }
        if (s.has(li.dataset.id)) s.delete(li.dataset.id); else s.add(li.dataset.id);
        renderRoles();
      });
      ul.addEventListener('dblclick', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        state[r.key] = state[r.key].filter((id) => id !== li.dataset.id);
        roleSel[r.key].delete(li.dataset.id);
        renderRoles();
      });
      ul.addEventListener('dragover', (ev) => { if ([...ev.dataTransfer.types].includes(MIME)) { ev.preventDefault(); ul.classList.add('drop'); } });
      ul.addEventListener('dragleave', () => ul.classList.remove('drop'));
      ul.addEventListener('drop', (ev) => {
        ul.classList.remove('drop');
        const data = ev.dataTransfer.getData(MIME);
        if (!data) return;
        ev.preventDefault();
        addTo(r, JSON.parse(data));
      });
      const row = el('div', { class: 'sm-role' }, btn, ul, r.info ? KvotInfo.slot(r.info) : el('span'));
      roleEls[r.key] = { row, list: ul, btn };
      roleBox.append(row);
    }

    // ---- options
    const optEls = {};
    const opts = el('div', { class: 'sm-launch-opts' });
    for (const o of L.options || []) {
      let input;
      if (o.type === 'check') { input = el('input', { type: 'checkbox' }); input.checked = !!o.value; }
      else if (o.type === 'select') {
        input = el('select', null, ...o.choices.map((c) => { const [v, lab] = Array.isArray(c) ? c : [c, c]; return el('option', { value: v, text: lab }); }));
        input.value = o.value;
      } else { input = el('input', { type: 'text', inputmode: o.type === 'number' ? 'decimal' : null, size: o.size || (o.type === 'number' ? 6 : 14) }); input.value = o.value ?? ''; }
      optEls[o.key] = input;
      const lab = o.type === 'check' ? el('label', null, input, o.label) : el('label', null, o.label, input);
      if (o.hint) lab.title = o.hint;
      opts.append(lab);
    }

    // ---- a platform's own part
    // message(text, 'info') shows a neutral status line instead of an error;
    // onRolesChange(fn) is called after every change of the roles;
    // showRole(key, on) shows or hides a role (Offset only for a GLM).
    const api = {
      table, platform, state,
      selectedColumns: () => [...selected].map((id) => table.col(id)).filter(Boolean),
      render: () => renderRoles(),
      message: (t, kind) => { msg.textContent = t || ''; msg.classList.toggle('is-info', kind === 'info'); },
      onRolesChange: (fn) => { roleWatchers.push(fn); },
      showRole: (key, on) => { if (roleEls[key]) roleEls[key].row.hidden = !on; },
    };
    const extra = L.extra ? L.extra(api, spec) : null;

    // ---- actions
    const read = () => {
      const out = { roles: {}, options: {} };
      for (const r of roles) out.roles[r.key] = state[r.key].slice();
      for (const o of L.options || []) {
        const i = optEls[o.key];
        out.options[o.key] = o.type === 'check' ? i.checked : o.type === 'number' ? (i.value.trim() === '' ? null : Number(i.value.trim().replace(',', '.'))) : i.value;
      }
      if (extra && extra.read) {
        const x = extra.read();
        if (x) { if (x.roles) Object.assign(out.roles, x.roles); if (x.options) Object.assign(out.options, x.options); for (const [k, v] of Object.entries(x)) if (k !== 'roles' && k !== 'options') out[k] = v; }
      }
      return out;
    };
    const ok = el('button', { type: 'button', class: 'sm-btn primary', text: 'OK' });
    const cancel = el('button', { type: 'button', class: 'sm-btn', text: 'Cancel' });
    const remove = el('button', { type: 'button', class: 'sm-btn', text: 'Remove' });
    const recall = el('button', { type: 'button', class: 'sm-btn', text: 'Recall' });
    const help = el('button', { type: 'button', class: 'sm-btn', text: 'Help' });
    const actions = el('div', { class: 'sm-actions' }, el('h4', { text: 'Action' }), ok, cancel, el('div', { style: { height: '8px' } }), remove, recall, help);

    const body = el('div', null,
      L.lead ? el('p', { class: 'sm-dialog-lead', text: L.lead }) : null,
      el('div', { class: 'sm-launch' },
        el('div', { class: 'sm-pick' }, el('h4', null, 'Select Columns', el('span', { class: 'sm-grow' }), count), filter, list),
        el('div', null, el('h4', { text: roles.length ? 'Cast Selected Columns into Roles' : 'Settings' }), roleBox, extra ? extra.el : null),
        actions),
      (L.options || []).length ? opts : null, msg);

    const dlg = SM.ui.dialog({ title: platform.label, body, info: platform.info || null, className: 'sm-launch-dialog' });

    const validate = (s) => {
      for (const r of roles) {
        const n = s.roles[r.key].length;
        if (n < (r.min || 0)) { roleEls[r.key].row.classList.add('is-missing'); return `${r.label}: choose ${r.min === 1 ? 'a column' : `at least ${r.min} columns`}`; }
      }
      for (const o of L.options || []) if (o.type === 'number' && s.options[o.key] != null && !Number.isFinite(s.options[o.key])) return `${o.label}: not a number`;
      return L.validate ? L.validate(s, table) : null;
    };
    ok.addEventListener('click', () => {
      const s = read();
      const err = validate(s);
      if (err) { msg.textContent = err; return; }
      last.set(platform.id, { roles: Object.fromEntries(Object.entries(s.roles).map(([k, ids]) => [k, ids.map((id) => table.col(id).name)])), options: s.options, extra: Object.fromEntries(Object.entries(s).filter(([k]) => k !== 'roles' && k !== 'options')) });
      try { localStorage.setItem(`smui.recall.${platform.id}`, JSON.stringify(last.get(platform.id))); } catch (e) { /* private window */ }
      dlg.close(true);
      onOK(s);
    });
    cancel.addEventListener('click', () => dlg.close(null));
    remove.addEventListener('click', () => {
      for (const r of roles) { state[r.key] = state[r.key].filter((id) => !roleSel[r.key].has(id)); roleSel[r.key].clear(); }
      renderRoles();
    });
    const fillFrom = (s, byName) => {
      if (!s) return false;
      for (const r of roles) {
        const keys = (s.roles && s.roles[r.key]) || [];
        state[r.key] = keys.map((k) => (byName ? table.col(k) : table.col(k))).filter(Boolean).map((c) => c.id);
      }
      for (const o of L.options || []) {
        const v = s.options ? s.options[o.key] : undefined;
        if (v === undefined) continue;
        const i = optEls[o.key];
        if (o.type === 'check') i.checked = !!v; else i.value = v ?? '';
      }
      renderRoles();
      return true;
    };
    recall.addEventListener('click', () => {
      let s = last.get(platform.id);
      if (!s) { try { s = JSON.parse(localStorage.getItem(`smui.recall.${platform.id}`) || 'null'); } catch (e) { s = null; } }
      if (!fillFrom(s, true)) msg.textContent = 'Nothing to recall: this platform has not been launched yet.';
      else if (extra && extra.recall) extra.recall(s);
    });
    help.addEventListener('click', () => {
      if (platform.info && typeof KvotInfo !== 'undefined') KvotInfo.open(platform.info);
      else if (SM.app) { dlg.close(null); SM.app.showHelp(platform.helpId || `p-${platform.id}`); }
    });
    dlg.el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.defaultPrevented && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON' && ev.target !== list) { ev.preventDefault(); ok.click(); }
    });

    // Start from the report being relaunched, or from the columns selected in
    // the table (JMP puts them into the first role).
    if (spec) fillFrom(spec, false);
    else {
      const pre = SM.app && SM.app.grid ? SM.app.selectedColumns() : [];
      const r0 = roles[0];
      if (r0 && pre.length) addTo(r0, pre.map((c) => c.id));
      msg.textContent = '';
    }
    fillList();
    renderRoles();
    requestAnimationFrame(() => list.focus({ preventScroll: true }));
    return dlg;
  }

  SM.launch = Object.freeze({ open, roleAccepts, MIME, last });
}(typeof self !== 'undefined' ? self : this));
