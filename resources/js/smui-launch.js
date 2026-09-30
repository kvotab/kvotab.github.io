/* ==========================================================================
   SMUI.HTML: LAUNCH DIALOGS

   JMP's launch dialog: the table's columns on the left, the roles in the
   middle, the actions on the right. Select columns and press a role's
   button, drag them onto a role, or double-click one to put it in the
   first role that takes it. A column in a role can be dragged again: to
   another role, onto a column of one (to take its place), along its own
   role (to change the order) or anywhere else in the dialog (to take it
   out); see "Places" below. A platform describes its dialog:

     launch: {
       lead: 'one line on what the platform does',
       roles: [{ key: 'y', label: 'Y, Columns', min: 1, max: Infinity,
                 types: ['continuous', 'ordinal', 'nominal'], numeric: false,
                 hint: 'required', help: 'what the role is for', info: 'topic key' }, ...],
       options: [{ key, label, type: 'check'|'number'|'select'|'text',
                   value, choices: [[value, label], ...], hint, help }],
       extra(api, spec) -> { el, read() -> { roles?, options?, ... }, recall(saved),
                             position: 'top' | undefined,
                             help: [[field label, what it is for], ...] or () => that }   (optional)

   The dialog's (i) shows the platform's topic and, after it, what every
   role, option and field of the platform's own part is for: each one's
   help (or its hint), with what a role takes.
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
  const keepOpen = new Map();   // platform id -> Keep dialog open, for this visit

  /* Whether a role is the one a preselected role names (Cols > Preselect
     Role): Y a role keyed y or labelled Y…, X likewise, Weight and Freq by
     their keys or labels. */
  function roleIs(r, name) {
    const key = String(r.key || '').toLowerCase(), label = String(r.label || '');
    if (name === 'Y') return key === 'y' || /^Y\b/.test(label);
    if (name === 'X') return key === 'x' || /^X\b/.test(label);
    if (name === 'Weight') return key === 'weight' || /^Weight\b/.test(label);
    if (name === 'Freq') return key === 'freq' || /^Freq\b/.test(label);
    return false;
  }
  const MIME = 'application/x-smui-columns';

  /* ---- Places: a column dragged out of where it was dropped -----------------
     A place takes columns dropped on it: a launch dialog's role list, Fit
     Model's and Multiple Imputation's model effects, Graph Builder's and
     Tabulate's zones. Its items can be dragged again, within the dialog or
     builder the place belongs to (its scope, marked by dropArea()):

       onto another place          it moves there, by that place's own rules
                                   (a role that does not take its modeling
                                   type refuses it and shows no drop; one that
                                   takes one column puts it in place of the
                                   one it holds)
       onto an item of another     it takes that item's place
       place
       onto an item of its own     it moves to that item's position (the order
       place, or beside them       of a role's or a zone's columns matters);
                                   beside the items, to the end
       anywhere else in the scope  it is taken out of its place

     Only a drop does anything: a drag cancelled with Escape, or let go
     outside the window, ends with no drop and leaves everything as it was.
     The drag carries the column as a drag from a column list does (MIME:
     only an item that is one column; a crossed effect has none) and PLACE,
     which a drag from a column list has not. While it is under way the
     item is dimmed, the places of the scope that refuse it are too, and the
     page shows where it goes: the place's own drop highlight, the item it
     would replace or the side of the item it would land on, and over the
     rest of the scope a label by the pointer that says it would be taken
     out (the item is struck through). One cue is on show at a time: each
     dragover says which it asks for (pending), and a listener on the
     document puts that one up once the event has been through every
     handler. */
  const PLACE = 'application/x-smui-place';
  const PLACES = new WeakMap();     // place element -> its description (see place())
  let moving = null;                // the drag out of a place under way
  let pending = null;               // the cue the dragover under way asks for
  let shown = null;                 // the cue on show
  let badge = null;                 // the "Remove ..." label by the pointer

  const scopeOf = (e) => (e && e.closest ? e.closest('[data-sm-scope]') : null);
  const inPlace = (ev) => !!(ev.target && ev.target.closest && ev.target.closest('[data-sm-place]'));

  /* Whether a drag comes out of a place (it carries PLACE), wherever it is
     and whether or not a handler has already dealt with its drop: the
     handlers of drops from a column list leave these alone. */
  function fromPlace(ev) {
    const dt = ev && ev.dataTransfer;
    return !!(dt && [...dt.types].includes(PLACE));
  }

  /* The drag out of a place that an event belongs to while it is under way,
     or null: a drag from a column list, or from outside the page (and a
     drag whose drop has been dealt with). */
  function movingOf(ev) {
    return moving && fromPlace(ev) ? moving : null;
  }

  /* A dialog or a builder whose places' items are taken out when they are
     dropped anywhere else in it. */
  function dropArea(scope) {
    if (!scope || scope.dataset.smScope != null) return scope;
    scope.dataset.smScope = '';
    scope.addEventListener('dragover', (ev) => {
      const m = movingOf(ev);
      // a place answers for itself: one that refuses the item shows no drop
      if (!m || m.scope !== scope || ev.defaultPrevented || inPlace(ev)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      pending = { m, remove: true, x: ev.clientX, y: ev.clientY };
    });
    scope.addEventListener('drop', (ev) => {
      const m = movingOf(ev);
      if (!m || m.scope !== scope || ev.defaultPrevented || inPlace(ev)) return;
      ev.preventDefault();
      finish();
      m.remove();
    });
    return scope;
  }

  /* Make el a place whose items can be dragged out of it (and that takes
     the items of the other places of its scope). cfg:
       label           the place's name, for the remove label ('Y, Response')
       item(node)      the item element a node is in, or null
       key(item)       the item's key within the place
       take(item)      at dragstart, what the item is: { cols, text, remove() }
                       and anything the place's own drop wants to know (cols:
                       the one column it is, or [] for an effect that is not
                       one column; remove() takes it out of this place)
       refuses(m, at)  for an item of another place of the scope: why this
                       place does not take it (a sentence), or null; at is the
                       key of the item under the pointer, or null
       drop({ m, at, same, side, ev })
                       what a drop does. same: m is this place's own item,
                       moved to the position of the item at (side 'before' or
                       'after' it: where it lands) or, at null, to the end.
                       Otherwise m comes from another place: take it (in place
                       of the item at, when there is one) and call m.remove(),
                       unless the place moves it in one step itself
       said(reason)    optional: show why a drag is refused here, or with null
                       take that away again
       dropClass       the place's class while it takes a drop (default 'drop')
       area            optional: a larger element around el that takes the drop
                       as el does (a role's row: its button is the role too) */
  function place(el, cfg) {
    const area = cfg.area || el;
    area.dataset.smPlace = '';
    PLACES.set(area, { cfg, el });
    const itemIn = (node) => { const it = node && node.closest ? cfg.item(node) : null; return it && el.contains(it) ? it : null; };
    el.addEventListener('dragstart', (ev) => {
      const item = itemIn(ev.target);
      const scope = scopeOf(el);
      if (!item || !scope || !ev.dataTransfer) return;
      const what = cfg.take(item);
      if (what) begin(ev, item, el, cfg, scope, what);
    });
    area.addEventListener('dragover', (ev) => {
      const m = movingOf(ev);
      if (!m) return;
      const j = judge(m, el, cfg, itemIn(ev.target));
      if (!j) return;
      if (j.reason) { pending = { place: el, cfg, reason: j.reason }; return; }
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      pending = { place: el, cfg, item: j.atEl, cls: j.cls };
    });
    area.addEventListener('drop', (ev) => {
      const m = movingOf(ev);
      if (!m) return;
      const j = judge(m, el, cfg, itemIn(ev.target));
      if (!j || j.reason) return;
      ev.preventDefault();
      finish();
      if (!j.noop) cfg.drop({ m, at: j.at, same: j.same, side: j.side, ev });
    });
  }

  /* What a drop of m on the place el (over its item atEl) would do. */
  function judge(m, el, cfg, atEl) {
    if (m.scope !== scopeOf(el)) return null;        // another dialog or builder: not here
    const at = atEl ? cfg.key(atEl) : null;
    if (m.from === el) {
      if (atEl === m.item) return { same: true, noop: true };
      if (!atEl) return { same: true, at: null, atEl: null, cls: null };
      // it lands after the item when it comes from before it, else before it
      const side = m.item.compareDocumentPosition(atEl) & Node.DOCUMENT_POSITION_FOLLOWING ? 'after' : 'before';
      return { same: true, at, atEl, side, cls: `sm-drop-${side}` };
    }
    const reason = cfg.refuses(m, at);
    if (reason) return { reason };
    return { same: false, at, atEl, cls: atEl ? 'sm-drop-replace' : null };
  }

  function begin(ev, item, el, cfg, scope, what) {
    finish();                // a drag left over (its dragend never came) goes
    const dt = ev.dataTransfer;
    const label = typeof cfg.label === 'function' ? cfg.label() : cfg.label;
    const m = { ...what, key: cfg.key(item), item, from: el, cfg, scope, label };
    moving = m;
    if (m.cols.length) dt.setData(MIME, JSON.stringify(m.cols.map((c) => c.id)));
    dt.setData(PLACE, String(m.key));
    dt.setData('text/plain', m.text);
    dt.effectAllowed = 'copyMove';
    // dimmed once the browser has taken its picture of the item
    setTimeout(() => { if (moving === m) item.classList.add('sm-dragged'); }, 0);
    // the places that would not take it
    for (const p of scope.querySelectorAll('[data-sm-place]')) {
      const P = PLACES.get(p);
      if (P && P.el !== el && P.cfg.refuses(m, null)) P.el.classList.add('sm-refusing');
    }
    if (m.started) m.started();
    // on the item itself: a place may draw its items again before the drag ends
    item.addEventListener('dragend', () => { if (moving === m) finish(); }, { once: true });
  }

  function finish() {
    const m = moving;
    moving = null;
    pending = null;
    cue(null);
    if (!m) return;
    m.item.classList.remove('sm-dragged', 'sm-removing');
    for (const p of m.scope.querySelectorAll('.sm-refusing')) p.classList.remove('sm-refusing');
    if (m.done) m.done();
  }

  /* Put up the cue a dragover asked for (null: none), taking down the one
     on show when it is another. */
  function cue(next) {
    const same = shown && next && shown.place === next.place && shown.item === next.item && shown.cls === next.cls && shown.reason === next.reason && !!shown.remove === !!next.remove;
    if (shown && !same) {
      if (shown.place) shown.place.classList.remove(shown.cfg.dropClass || 'drop');
      if (shown.item && shown.cls) shown.item.classList.remove(shown.cls);
      if (shown.reason && shown.cfg.said) shown.cfg.said(null, shown.reason);
      if (shown.remove) {
        if (badge) badge.hidden = true;
        document.documentElement.classList.remove('sm-drop-remove');
        shown.m.item.classList.remove('sm-removing');
      }
    }
    const was = shown;
    shown = next;
    if (!next) return;
    if (next.reason) { if (!same && next.cfg.said) next.cfg.said(next.reason); return; }
    // (again each time: a place's own dragleave may have taken its highlight away)
    if (next.place) next.place.classList.add(next.cfg.dropClass || 'drop');
    if (next.item && next.cls) next.item.classList.add(next.cls);
    if (next.remove) showBadge(next, !(was && same));
  }

  function showBadge(c, fresh) {
    if (!badge) {
      badge = el('div', { class: 'sm-dropcue', 'aria-hidden': 'true' });
      document.body.append(badge);
    }
    if (fresh) {
      badge.replaceChildren(el('span', { class: 'sm-dropcue-x', text: '×' }), el('span', { text: `Remove ${c.m.text}${c.m.label ? ` from ${c.m.label}` : ''}` }));
      badge.hidden = false;
      document.documentElement.classList.add('sm-drop-remove');
      c.m.item.classList.add('sm-removing');
    }
    // by the pointer; by a finger, above the item the finger carries
    const touch = !!(SM.touchdrag && SM.touchdrag.active());
    badge.classList.toggle('is-touch', touch);
    const w = badge.offsetWidth, h = badge.offsetHeight;
    let x = touch ? c.x - w / 2 : c.x + 14, y = touch ? c.y - 80 - h : c.y + 18;
    x = Math.max(4, Math.min(x, innerWidth - w - 4));
    y = Math.max(4, Math.min(y, innerHeight - h - 4));
    badge.style.left = `${Math.round(x)}px`;
    badge.style.top = `${Math.round(y)}px`;
  }

  if (typeof document !== 'undefined') {
    // each dragover asks afresh; once it has been through every handler, its cue goes up
    document.addEventListener('dragover', () => { pending = null; }, true);
    document.addEventListener('dragover', () => { if (moving) cue(pending); });
    // out of the window: nothing is where it would go
    document.addEventListener('dragleave', (ev) => { if (moving && !ev.relatedTarget) cue(null); });
    // a new drag: what an old one left (its dragend never came) goes
    document.addEventListener('dragstart', () => { if (moving) finish(); }, true);
  }

  function roleAccepts(role, c) {
    if (role.numeric && !c.isNumeric) return `${role.label} needs a numeric column; ${c.name} is character`;
    if (role.types && !role.types.includes(c.modelingType)) {
      return `${role.label} takes ${role.types.map((t) => TYPE_LABEL[t].toLowerCase()).join(' or ')} columns; ${c.name} is ${TYPE_LABEL[c.modelingType].toLowerCase()} (right click it to change)`;
    }
    return null;
  }

  /* How columns get into the roles and out of them again, for the (i). */
  const ROLES_HELP = [
    'Select columns in the list on the left and press a role\'s button, drag them onto the role (its list or its button), or double-click one to put it in the first role that takes it.',
    'A column in a role can be dragged again: onto another role to move it there (a role that does not take its modeling type refuses it and says why; one that takes a single column puts it in place of the one it holds), onto a column of another role to take that column\'s place, along its own role to change the order, and anywhere else in the dialog, such as the list on the left, to take it out. A drag cancelled with Escape leaves it where it was. A double click, or Remove with it selected, takes it out too.',
  ];

  /* What a role takes, in words: 'required: one column, continuous'. */
  function takes(r) {
    const need = r.min ? (r.min > 1 ? `required: ${r.min} or more columns` : 'required') : 'optional';
    const count = r.max === 1 ? 'one column' : (r.min > 1 ? '' : 'one or more columns');
    const kinds = r.types ? r.types.map((k) => TYPE_LABEL[k].toLowerCase()).join(' or ') : '';
    return [need, count, kinds, r.numeric ? 'numeric' : ''].filter(Boolean).join(', ');
  }

  /* The launch dialog's (i) topic: the platform's own, and the roles, options
     and fields of the dialog, each with what it is for. shown(role): whether
     the dialog shows the role now (a layout can hide some). */
  function dialogTopic(platform, L, roles, extra, shown = () => true) {
    if (typeof KvotInfo === 'undefined') return platform.info || null;
    // A field's help, or its hint when the hint says more than what the role
    // takes ('required: continuous', 'one or more', 'optional numeric' do not).
    const say = (f) => {
      if (f.help) return f.help;
      const h = (f.hint || '').trim();
      const rest = h.replace(/\b(required|optional|numeric|continuous|nominal|ordinal|character|categorical|one|two|or|and|more|columns?|a|an|any)\b|[:;,.()]/gi, '').trim();
      return rest ? h.replace(/^(required|optional):\s*/i, '') : '';
    };
    // Built when the (i) is clicked, so fields the extra part shows only in
    // some states are explained as they are.
    const topic = () => {
      const base = (platform.info && SM.info && SM.info.get(platform.info)) || null;
      // A Roles or Options section of the platform's topic gives way to the
      // generated one, its words kept for a field that has no help.
      const own = (heading) => { const s = ((base && base.sections) || []).find((x) => x.heading === heading && x.choices); return new Map(s ? s.choices : []); };
      const ownRoles = own('Roles'), ownOpts = own('Options');
      const sections = ((base && base.sections) || []).filter((s) => !(s.choices && (s.heading === 'Roles' || s.heading === 'Options')));
      const now = roles.filter((r) => shown(r));
      if (now.length) sections.push({ heading: 'Roles', text: ROLES_HELP, choices: now.map((r) => [r.label, [say(r) || ownRoles.get(r.label), `(${takes(r)})`].filter(Boolean).join(' ')]) });
      const opts = (L.options || []).map((o) => [o.label, say(o) || ownOpts.get(o.label) || (o.type === 'check' ? 'on or off' : '')]);
      if (opts.length) sections.push({ heading: 'Options', choices: opts });
      let xh = null;
      try { xh = extra && (typeof extra.help === 'function' ? extra.help() : extra.help); } catch (e) { xh = null; }
      if (xh && xh.length) sections.push({ heading: extra.helpHeading || 'Settings', choices: xh });
      sections.push({ heading: 'The dialog', choices: [
        ['A column\'s right click', 'Its modeling type (Continuous, Ordinal, Nominal), and Transform, Distributional and Date Time: a transform of the column (Log, Square Root, Standardize, Rank, Year, Month Abbr. …) made as a formula column of the table, next to it, and put in the list selected, so that a role\'s button or a drag casts it. Edit > Undo takes it away.'],
        ['Keep dialog open', 'On: OK runs the analysis and leaves the dialog as it is, for another run with other roles or options (JMP\'s Keep dialog open); Cancel closes it. The box is remembered for the platform until the page is left.'],
        ['Preselected roles', 'A column given a role with Cols > Preselect Role (Y, X, Weight, Freq) starts in that role when the dialog opens, when the role takes it.'],
      ] });
      return { kicker: (base && base.kicker) || 'Launch', title: (base && base.title) || platform.label, lead: (base && base.lead) || L.lead || platform.about || '', sections, more: base ? base.more : undefined };
    };
    const key = `launch:${platform.id}`;
    (SM.info ? SM.info.add : KvotInfo.add)({ [key]: topic });
    return key;
  }

  /* spec: a report's spec (column ids), to relaunch it; recall: a launch by
     column names, the shape Recall keeps (SM.launch.last: { roles: { key:
     [names] }, options, extra }): a table script (smui-scripts.js). */
  function open({ platform, table, spec = null, recall: recalled = null, onOK }) {
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
      const shown = roles.filter((r) => !roleEls[r.key].row.hidden);
      const role = shown.find((r) => !roleAccepts(r, c) && state[r.key].length < (r.max ?? Infinity)) || shown.find((r) => !roleAccepts(r, c));
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
        const shown = roles.filter((r) => !roleEls[r.key].row.hidden);
        const role = shown.find((r) => !roleAccepts(r, c)) || shown[0];
        if (!role) return;
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
    // A transform column made from the list (smui-p-tables.js): in the table
    // and in the list, selected, so a role's button (or a drag) casts it.
    const madeColumn = (nc) => {
      if (!table.col(nc.id)) return;
      if (filter.value.trim() && !nc.name.toLowerCase().includes(filter.value.trim().toLowerCase())) filter.value = '';
      selected.clear();
      selected.add(nc.id);
      anchor = nc.id;
      fillList();
      renderRoles();
      const li = [...list.querySelectorAll('li')].find((x) => x.dataset.id === nc.id);
      if (li) li.scrollIntoView({ block: 'nearest' });
      msg.textContent = `${nc.name} is a new formula column: press a role's button, or drag it onto one`;
      msg.classList.add('is-info');
      list.focus({ preventScroll: true });
    };
    list.addEventListener('contextmenu', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      ev.preventDefault();
      const c = table.col(li.dataset.id);
      const transforms = SM.tables && SM.tables.transformMenu ? SM.tables.transformMenu(table, c, madeColumn) : [];
      SM.ui.menu([
        { head: c.name },
        ...['continuous', 'ordinal', 'nominal'].map((t) => ({
          label: TYPE_LABEL[t], checked: c.modelingType === t, disabled: t === 'continuous' && !c.isNumeric,
          action: () => { table.setType(c.id, { modelingType: t }); fillList(); renderRoles(); },
        })),
        ...(transforms.length ? [{ separator: true }, ...transforms] : []),
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
    // A column dragged out of a role (dropped elsewhere in the dialog, or moved).
    const takeOut = (role, id) => {
      state[role.key] = state[role.key].filter((x) => x !== id);
      roleSel[role.key].delete(id);
      renderRoles();
    };
    // A column of a place of this dialog dropped on a role: along the role
    // (same), it goes to the position of the column at (the end without
    // one); from another role or the model effects, it leaves that place and
    // takes the place of the column at, or comes in as a drop from the list
    // does (after the others; in a role of one column, instead of it).
    const dropOn = (role, m, at, same) => {
      msg.textContent = '';
      msg.classList.remove('is-info');
      const c = m.cols[0];
      const ids = state[role.key].slice();
      if (same) {
        const from = ids.indexOf(c.id), to = at == null ? ids.length - 1 : ids.indexOf(at);
        if (from < 0 || to < 0 || from === to) return;
        ids.splice(from, 1);
        ids.splice(to, 0, c.id);
        state[role.key] = ids;
        renderRoles();
        return;
      }
      m.remove();
      if (at === c.id && state[role.key].includes(c.id)) { renderRoles(); return; }     // it is in this role already, there
      if (at != null && state[role.key].includes(at)) {
        const rest = state[role.key].filter((id) => id !== c.id);
        rest.splice(rest.indexOf(at), 1, c.id);
        state[role.key] = rest;
        roleSel[role.key].delete(at);
        renderRoles();
      } else addTo(role, [c.id]);
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
          // draggable: to another role, onto a column of one, along this one, or out
          const li = el('li', { dataset: { id }, role: 'option', draggable: 'true', 'aria-selected': String(roleSel[r.key]?.has(id) || false) }, typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }));
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
      const mark = { anchor: null };
      ul.addEventListener('click', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        // a click, ctrl/⌘ for one more, shift for a sweep
        SM.util.listClick(ev, li.dataset.id, state[r.key], roleSel[r.key], mark);
        renderRoles();
      });
      ul.addEventListener('dblclick', (ev) => {
        const li = ev.target.closest('li');
        if (!li) return;
        state[r.key] = state[r.key].filter((id) => id !== li.dataset.id);
        roleSel[r.key].delete(li.dataset.id);
        renderRoles();
      });
      const row = el('div', { class: 'sm-role' }, btn, ul, r.info ? KvotInfo.slot(r.info) : el('span'));
      // columns from the column list, dropped on the role's list or its button
      // (a column dragged out of a place is place()'s, whose area is the row too)
      row.addEventListener('dragover', (ev) => { if (!fromPlace(ev) && [...ev.dataTransfer.types].includes(MIME)) { ev.preventDefault(); ul.classList.add('drop'); } });
      row.addEventListener('dragleave', () => ul.classList.remove('drop'));
      row.addEventListener('drop', (ev) => {
        ul.classList.remove('drop');
        if (fromPlace(ev)) return;
        const data = ev.dataTransfer.getData(MIME);
        if (!data) return;
        ev.preventDefault();
        addTo(r, JSON.parse(data));
      });
      place(ul, {
        area: row,
        label: r.label,
        item: (n) => n.closest('li[data-id]'),
        key: (li) => li.dataset.id,
        take: (li) => { const c = table.col(li.dataset.id); return c ? { cols: [c], text: c.name, remove: () => takeOut(r, c.id) } : null; },
        refuses: (m) => (m.cols.length !== 1 ? `${r.label} takes columns; ${m.text} is an effect` : roleAccepts(r, m.cols[0])),
        // why a role refuses the column, while it is over it (as a drop from the list would say after it)
        said: (why, was) => {
          if (why) { msg.textContent = why; msg.classList.remove('is-info'); } else if (msg.textContent === was) msg.textContent = '';
        },
        drop: ({ m, at, same }) => dropOn(r, m, at, same),
      });
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
      // setRequired(key, on): the role needs a column (or not) in the layout
      // chosen now; OK checks it, and its empty box says so.
      setRequired: (key, on) => {
        const r = roles.find((x) => x.key === key);
        if (!r) return;
        r.min = on ? Math.max(1, r.min || 0) : 0;
        const ul = roleEls[key].list;
        ul.dataset.hint = r.hint && !/^(required|optional)/.test(r.hint) ? r.hint : (on ? 'required' : 'optional');
        roleEls[key].btn.classList.toggle('required', !!on);
      },
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
    // JMP's Keep dialog open: OK runs the analysis and leaves the dialog as it is, for another
    const keepBox = el('input', { type: 'checkbox', class: 'sm-keepopen' });
    keepBox.checked = !!keepOpen.get(platform.id);
    keepBox.addEventListener('change', () => keepOpen.set(platform.id, keepBox.checked));
    const keep = el('label', { class: 'sm-keep', title: 'OK runs the analysis and leaves this dialog open, with its roles and options, for another run' }, keepBox, 'Keep dialog open');
    const actions = el('div', { class: 'sm-actions' }, el('h4', { text: 'Action' }), ok, cancel, el('div', { style: { height: '8px' } }), remove, recall, help, keep);

    const body = el('div', null,
      L.lead ? el('p', { class: 'sm-dialog-lead', text: L.lead }) : null,
      el('div', { class: 'sm-launch' },
        el('div', { class: 'sm-pick' }, el('h4', null, 'Select Columns', el('span', { class: 'sm-grow' }), count), filter, list),
        el('div', null, el('h4', { text: roles.length ? 'Cast Selected Columns into Roles' : 'Settings' }),
          extra && extra.position === 'top' ? extra.el : null, roleBox, extra && extra.position !== 'top' ? extra.el : null),
        actions),
      (L.options || []).length ? opts : null, msg);

    const topicKey = dialogTopic(platform, L, roles, extra, (r) => !(roleEls[r.key] && roleEls[r.key].row.hidden));
    const dlg = SM.ui.dialog({ title: platform.label, body, info: topicKey, className: 'sm-launch-dialog' });
    // a column dragged out of a role (or the model effects) and let go anywhere else in the dialog is taken out
    dropArea(dlg.el);

    const validate = (s) => {
      for (const r of roles) {
        if (roleEls[r.key].row.hidden) continue;
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
      if (keepBox.checked) {
        // the analysis runs; the dialog stays, as it was, for the next one
        msg.textContent = `${platform.label} launched; the dialog stays open (Keep dialog open): change the roles or options and press OK again, or Cancel.`;
        msg.classList.add('is-info');
        onOK(JSON.parse(JSON.stringify(s)));
        return;
      }
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
      if (!s) { msg.textContent = 'Nothing to recall: this platform has not been launched yet.'; return; }
      // The platform's own part first: which roles it shows may depend on it.
      if (extra && extra.recall) extra.recall(s);
      fillFrom(s, true);
    });
    help.addEventListener('click', () => {
      // the same as the (i): the platform, and what each role, option and field is for
      if ((topicKey || platform.info) && typeof KvotInfo !== 'undefined') KvotInfo.open(topicKey || platform.info);
      else if (SM.app) { dlg.close(null); SM.app.showHelp(platform.helpId || `p-${platform.id}`); }
    });
    dlg.el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.defaultPrevented && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON' && ev.target !== list) { ev.preventDefault(); ok.click(); }
    });

    // Start from the report being relaunched, or from the columns with a
    // preselected role (Cols > Preselect Role) in that role and the columns
    // selected in the table in the first role (as JMP does).
    if (spec) fillFrom(spec, false);
    else if (recalled) {
      // as Recall does: the platform's own part first (which roles it shows may depend on it)
      if (extra && extra.recall) extra.recall(recalled);
      fillFrom(recalled, true);
      msg.textContent = '';
    } else {
      const placed = new Set();
      for (const c of table.columns) {
        if (!c.preselectRole) continue;
        const role = roles.find((r) => roleIs(r, c.preselectRole) && !roleEls[r.key].row.hidden && !roleAccepts(r, c) && state[r.key].length < (r.max ?? Infinity));
        if (role) { state[role.key].push(c.id); placed.add(c.id); }
      }
      const pre = (SM.app && SM.app.grid && SM.app.current === table ? SM.app.selectedColumns() : []).filter((c) => !placed.has(c.id));
      const r0 = roles[0];
      if (r0 && pre.length) addTo(r0, pre.map((c) => c.id));
      msg.textContent = '';
    }
    fillList();
    renderRoles();
    requestAnimationFrame(() => list.focus({ preventScroll: true }));
    return dlg;
  }

  /* Let an element take columns dragged from a launch dialog's column
     list, as the role lists do (a platform's own list, such as Fit Model's
     Construct Model Effects): onDrop(columns) gets them in the table's
     order. A column dragged out of a place is not one of these: a list
     that takes those too is a place() as well. */
  function acceptColumns(target, table, onDrop) {
    target.addEventListener('dragover', (ev) => {
      if (fromPlace(ev) || ![...ev.dataTransfer.types].includes(MIME)) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'copy';
      target.classList.add('drop');
    });
    target.addEventListener('dragleave', (ev) => { if (!target.contains(ev.relatedTarget)) target.classList.remove('drop'); });
    target.addEventListener('drop', (ev) => {
      target.classList.remove('drop');
      if (fromPlace(ev)) return;
      const data = ev.dataTransfer.getData(MIME);
      if (!data) return;
      ev.preventDefault();
      let ids;
      try { ids = JSON.parse(data); } catch (e) { return; }
      const cols = (Array.isArray(ids) ? ids : []).map((id) => table.col(id)).filter(Boolean).sort((a, b) => table.colIndex(a) - table.colIndex(b));
      if (cols.length) onDrop(cols);
    });
  }

  SM.launch = Object.freeze({ open, roleAccepts, MIME, last, acceptColumns, PLACE, place, dropArea, fromPlace, moving: movingOf });
}(typeof self !== 'undefined' ? self : this));
