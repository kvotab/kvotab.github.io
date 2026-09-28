/* ==========================================================================
   SMUI.HTML: MENUS, DIALOGS, FORMS, TOASTS

   Menus are one list of items:

       { label, action, checked, disabled, key, submenu: [...] }
       { separator: true }      { head: 'A heading' }

   used by the menu bar, the red triangles and the right-click menus.
   Dialogs are plain elements over a dimmed page (not <dialog>): Escape,
   the × and Cancel close them. form() asks for a few values and resolves
   to them, or to null when cancelled.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el } = SM.util;

  let openMenus = [];

  function closeMenus(from = 0) {
    for (const m of openMenus.splice(from)) { m.el.remove(); if (m.onClose) m.onClose(); }
  }

  /* Open a menu at an anchor element (below it) or at a point {x, y}. */
  function menu(items, at, opts = {}) {
    const level = opts.level || 0;
    closeMenus(level);
    const box = el('div', { class: 'sm-menu', role: 'menu' });
    const buttons = [];
    for (const it of items) {
      if (!it) continue;
      if (it.separator) { box.append(el('hr')); continue; }
      if (it.head) { box.append(el('div', { class: 'sm-menu-head', text: it.head })); continue; }
      const b = el('button', { type: 'button', role: it.checked != null ? 'menuitemcheckbox' : 'menuitem', disabled: !!it.disabled, 'aria-checked': it.checked != null ? String(!!it.checked) : null },
        it.swatch ? el('span', { class: 'sm-mark' }, el('span', { class: 'sm-swatch', style: { background: it.swatch } })) : el('span', { class: 'sm-mark', text: it.checked ? '✓' : (it.mark || '') }),
        el('span', { class: 'sm-label', text: it.label }),
        it.key ? el('span', { class: 'sm-key', text: it.key }) : null);
      if (it.submenu) {
        b.classList.add('sm-sub');
        const openSub = () => {
          // A disabled item's submenu stays shut; hovering it closes any other.
          if (it.disabled) { closeMenus(level + 1); buttons.forEach((x) => x.classList.remove('is-open')); return; }
          buttons.forEach((x) => x.classList.remove('is-open'));
          b.classList.add('is-open');
          const r = b.getBoundingClientRect();
          menu(typeof it.submenu === 'function' ? it.submenu() : it.submenu, { x: r.right - 2, y: r.top - 4, sub: true }, { level: level + 1 });
        };
        b.addEventListener('mouseenter', openSub);
        b.addEventListener('click', (ev) => { ev.stopPropagation(); openSub(); });
        b.addEventListener('keydown', (ev) => { if (ev.key === 'ArrowRight') { ev.preventDefault(); openSub(); const sub = openMenus[level + 1]; if (sub) sub.el.querySelector('button:not([disabled])')?.focus(); } });
      } else {
        b.addEventListener('mouseenter', () => { closeMenus(level + 1); buttons.forEach((x) => x.classList.remove('is-open')); });
        b.addEventListener('click', (ev) => {
          ev.stopPropagation();
          if (it.disabled) return;
          closeMenus(0);
          if (it.action) Promise.resolve().then(() => it.action()).catch((e) => SM.ui.toast(e.message || String(e), { error: true }));
        });
      }
      if (it.title) b.setAttribute('aria-description', it.title);
      buttons.push(b);
      box.append(b);
    }
    box.addEventListener('keydown', (ev) => {
      const list = buttons.filter((x) => !x.disabled);
      const i = list.indexOf(document.activeElement);
      if (ev.key === 'ArrowDown') { ev.preventDefault(); (list[i + 1] || list[0])?.focus(); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); (list[i - 1] || list[list.length - 1])?.focus(); }
      else if (ev.key === 'ArrowLeft' && level > 0) { ev.preventDefault(); closeMenus(level); openMenus[level - 1]?.el.querySelector('.is-open')?.focus(); }
      else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeMenus(0); if (opts.returnFocus) opts.returnFocus.focus(); }
    });
    document.body.append(box);
    // Place it: under an element, or at a point, kept inside the window.
    let x, y;
    if (at instanceof Element) { const r = at.getBoundingClientRect(); x = r.left; y = r.bottom + 1; }
    else { x = at.x; y = at.y; }
    const w = box.offsetWidth, h = box.offsetHeight;
    if (x + w > innerWidth - 4) x = at && at.sub ? Math.max(4, x - w - 180) : Math.max(4, innerWidth - w - 4);
    if (y + h > innerHeight - 4) y = Math.max(4, innerHeight - h - 4);
    box.style.left = `${Math.round(x)}px`;
    box.style.top = `${Math.round(y)}px`;
    openMenus[level] = { el: box, onClose: opts.onClose };
    if (opts.focus !== false) requestAnimationFrame(() => box.querySelector('button:not([disabled])')?.focus({ preventScroll: true }));
    return box;
  }

  document.addEventListener('mousedown', (ev) => {
    if (!openMenus.length) return;
    if (openMenus.some((m) => m.el.contains(ev.target))) return;
    closeMenus(0);
  }, true);
  window.addEventListener('blur', () => closeMenus(0));
  window.addEventListener('resize', () => closeMenus(0));

  /* ---- dialogs ------------------------------------------------------------ */
  const dialogs = [];

  /* A dialog moves when its title bar is dragged (mouse, pen or touch), and
     its title bar stays inside the window. */
  function makeMovable(box, head) {
    let dx = 0, dy = 0;
    head.classList.add('sm-dialog-grip');
    head.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0 || ev.target.closest('button, a, input, select, textarea, .kvot-info-slot')) return;
      ev.preventDefault();
      const r = box.getBoundingClientRect();
      const left0 = r.left - dx, top0 = r.top - dy;      // where it sits unmoved
      const hh = head.getBoundingClientRect().height;
      const sx = ev.clientX - dx, sy = ev.clientY - dy;
      const move = (e) => {
        dx = Math.min(innerWidth - left0 - 60, Math.max(60 - left0 - r.width, e.clientX - sx));
        dy = Math.min(innerHeight - top0 - hh, Math.max(-top0, e.clientY - sy));
        box.style.transform = `translate(${Math.round(dx)}px, ${Math.round(dy)}px)`;
      };
      const up = () => { head.removeEventListener('pointermove', move); head.removeEventListener('pointerup', up); head.removeEventListener('pointercancel', up); head.classList.remove('is-moving'); };
      try { head.setPointerCapture(ev.pointerId); } catch (e) { /* synthetic events */ }
      head.classList.add('is-moving');
      head.addEventListener('pointermove', move);
      head.addEventListener('pointerup', up);
      head.addEventListener('pointercancel', up);
    });
  }

  function dialog({ title, body, buttons = [], narrow = false, info = null, onClose = null, className = '' }) {
    const back = el('div', { class: 'sm-modal-back' });
    const x = el('button', { type: 'button', class: 'sm-dialog-x', 'aria-label': 'Close', text: '×' });
    const head = el('div', { class: 'sm-dialog-head' }, el('h2', { text: title }));
    if (info && typeof KvotInfo !== 'undefined') head.append(KvotInfo.slot(info));
    head.append(x);
    const foot = el('div', { class: 'sm-dialog-foot' });
    const box = el('div', { class: `sm-dialog${narrow ? ' narrow' : ''} ${className}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      head, el('div', { class: 'sm-dialog-body' }, body), foot);
    back.append(box);
    makeMovable(box, head);
    let closed = false;
    const api = {
      el: box,
      close(result) {
        if (closed) return;
        closed = true;
        back.remove();
        dialogs.splice(dialogs.indexOf(api), 1);
        if (onClose) onClose(result);
      },
    };
    for (const b of buttons) {
      const btn = el('button', { type: 'button', class: `sm-btn${b.primary ? ' primary' : ''}`, text: b.label });
      btn.addEventListener('click', async () => {
        if (b.action) { const keep = await b.action(api); if (keep === false) return; }
        api.close(b.result);
      });
      foot.append(btn);
    }
    if (!buttons.length) foot.remove();
    x.addEventListener('click', () => api.close(null));
    // A click on the dimmed page closes nothing (it lost the work in the
    // dialog too easily): the dialog flashes, as a modal window does.
    back.addEventListener('mousedown', (ev) => {
      if (ev.target !== back) return;
      ev.preventDefault();
      box.classList.remove('is-attention');
      void box.offsetWidth;          // restart the flash
      box.classList.add('is-attention');
    });
    box.addEventListener('animationend', () => box.classList.remove('is-attention'));
    box.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && !ev.defaultPrevented) { ev.preventDefault(); ev.stopPropagation(); api.close(null); }
      if (ev.key === 'Enter' && !ev.defaultPrevented && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON') {
        const primary = buttons.find((b) => b.primary);
        if (primary) { ev.preventDefault(); foot.querySelector('.primary')?.click(); }
      }
    });
    document.body.append(back);
    dialogs.push(api);
    if (typeof KvotInfo !== 'undefined') KvotInfo.mount(box);
    requestAnimationFrame(() => (box.querySelector('input, select, textarea, .sm-pick-list li, button.primary') || x).focus({ preventScroll: true }));
    return api;
  }

  /* Ask for a few values: fields [{ key, label, type, value, choices,
     step, min, max, placeholder, full, hint, help, helpLabel }]. Resolves
     to { key: value } or null. The dialog's (i) shows its info topic and,
     after it, what each field is for (its help, or its hint), under
     helpLabel when the label is one of many alike ('Y1: Goal'); an
     explanation is given once. */
  function form({ title, lead, fields, okLabel = 'OK', info = null, validate = null }) {
    const seen = new Set();
    const described = [];
    for (const f of fields) {
      const text = f.help || f.hint;
      const label = f.helpLabel || f.label;
      if (!text || seen.has(`${label}\u0001${text}`)) continue;
      seen.add(`${label}\u0001${text}`);
      described.push([label, text]);
    }
    if (described.length && typeof KvotInfo !== 'undefined') {
      const base = (info && SM.info && SM.info.get(info)) || null;
      const key = `form:${info || title}`;
      (SM.info ? SM.info.add : KvotInfo.add)({ [key]: { kicker: (base && base.kicker) || 'Dialog', title: (base && base.title) || title, lead: (base && base.lead) || lead || '',
        sections: [...((base && base.sections) || []), { heading: 'Fields', choices: described }], more: base ? base.more : undefined } });
      info = key;
    }
    return new Promise((resolve) => {
      const inputs = {};
      const grid = el('div', { class: 'sm-form' });
      for (const f of fields) {
        let input;
        if (f.type === 'select') {
          input = el('select', { id: SM.util.uid('f') }, ...f.choices.map((c) => {
            const [v, lab] = Array.isArray(c) ? c : [c, c];
            return el('option', { value: v, selected: String(v) === String(f.value) ? true : null, text: lab });
          }));
        } else if (f.type === 'check') {
          input = el('input', { type: 'checkbox', id: SM.util.uid('f') });
          input.checked = !!f.value;
        } else if (f.type === 'textarea') {
          input = el('textarea', { id: SM.util.uid('f'), placeholder: f.placeholder || null });
          input.value = f.value == null ? '' : String(f.value);
        } else {
          input = el('input', { type: f.type === 'number' ? 'text' : 'text', inputmode: f.type === 'number' ? 'decimal' : null, id: SM.util.uid('f'), placeholder: f.placeholder || null });
          input.value = f.value == null ? '' : String(f.value);
        }
        inputs[f.key] = input;
        const label = el('label', { for: input.id, text: f.label });
        if (f.full || f.type === 'textarea') { grid.append(el('div', { class: 'full' }, label), el('div', { class: 'full' }, input)); }
        else grid.append(label, input);
        if (f.hint) grid.append(el('div', { class: 'full sm-dialog-lead', text: f.hint }));
      }
      const msg = el('div', { class: 'sm-launch-msg' });
      const body = el('div', null, lead ? el('p', { class: 'sm-dialog-lead', text: lead }) : null, grid, msg);
      const read = () => {
        const out = {};
        for (const f of fields) {
          const i = inputs[f.key];
          if (f.type === 'check') out[f.key] = i.checked;
          else if (f.type === 'number') { const t = i.value.trim().replace(',', '.'); out[f.key] = t === '' ? null : Number(t); }
          else out[f.key] = i.value;
        }
        return out;
      };
      dialog({
        title, body, narrow: true, info,
        buttons: [
          { label: 'Cancel', result: null },
          { label: okLabel, primary: true, action: () => {
            const v = read();
            for (const f of fields) if (f.type === 'number' && v[f.key] != null && !Number.isFinite(v[f.key])) { msg.textContent = `${f.label}: not a number`; return false; }
            const err = validate ? validate(v) : null;
            if (err) { msg.textContent = err; return false; }
            resolve(v);
            return true;
          } },
        ],
        onClose: (r) => { if (r === null) resolve(null); },
      });
    });
  }

  let toastTimer = null;
  function toast(text, { error = false, ms = 3800 } = {}) {
    document.querySelectorAll('.sm-toast').forEach((t) => t.remove());
    const t = el('div', { class: `sm-toast${error ? ' error' : ''}`, role: error ? 'alert' : 'status', text });
    document.body.append(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), error ? ms * 1.6 : ms);
  }

  SM.ui = Object.freeze({ menu, closeMenus, dialog, form, toast, dialogs });
}(typeof self !== 'undefined' ? self : this));
