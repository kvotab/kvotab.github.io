/* ==========================================================================
   PYLAB.HTML: SMALL HELPERS

   PL.el(tag, attrs, ...children)   an element (attrs: class, style, on*, data)
   PL.Emitter                        on / off / emit
   PL.icon(name)                     an inline SVG icon (currentColor strokes)
   PL.menu(x, y, items)              a context menu; items {label, kbd, action,
                                     disabled, checked} or '-' or {heading}
   PL.dialog({title, body, buttons}) a modal; resolves with the button's value
   PL.toast(text)                    a short note at the bottom
   PL.store.get/set(key, value)      localStorage with JSON, never throwing
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === 'class') n.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
        else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
        else if (k === 'dataset') Object.assign(n.dataset, v);
        else if (k === 'html') n.innerHTML = v;
        else if (k === 'text') n.textContent = v;
        else if (v === true) n.setAttribute(k, '');
        else n.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return n;
  }

  class Emitter {
    constructor() { this._h = new Map(); }
    on(ev, fn) { if (!this._h.has(ev)) this._h.set(ev, new Set()); this._h.get(ev).add(fn); return () => this.off(ev, fn); }
    off(ev, fn) { const s = this._h.get(ev); if (s) s.delete(fn); }
    emit(ev, ...args) {
      const s = this._h.get(ev);
      if (!s) return;
      for (const fn of [...s]) {
        try { fn(...args); } catch (e) { console.error(e); }
      }
    }
  }

  /* Icons: 24-unit boxes, drawn in the current colour. */
  const P = {
    newscript: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M12 11v6M9 14h6"/>',
    newfunc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M13.5 10.5c-1.6-.4-2.3.6-2.5 2l-.8 5.5c-.2 1.3-1 1.8-2.2 1.5M9 13.5h4"/>',
    open: '<path d="M3 6h6l2 2h10v11H3z"/><path d="M3 10h18"/>',
    save: '<path d="M5 3h12l3 3v15H5z"/><path d="M8 3v5h8V3M8 21v-7h9v7"/>',
    saveas: '<path d="M5 3h12l3 3v8M5 3v18h8"/><path d="M8 3v5h8V3"/><path d="M15 21l1-3 5-5 2 2-5 5z"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 16v4h16v-4"/>',
    run: '<path d="M7 4l13 8-13 8z" fill="currentColor" stroke="none"/>',
    runsec: '<path d="M4 5h9M4 9h6M4 13h9"/><path d="M13 12l8 5-8 5z" fill="currentColor" stroke="none"/>',
    runadv: '<path d="M4 5h16M4 9h10"/><path d="M8 13l7 4.5L8 22z" fill="currentColor" stroke="none"/><path d="M17 14v7"/>',
    runsel: '<path d="M3 6h7M3 10h5"/><rect x="2" y="13" width="9" height="6" rx="1"/><path d="M14 9l8 5-8 5z" fill="currentColor" stroke="none"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" stroke="none"/>',
    pause: '<rect x="6" y="5" width="4" height="14" fill="currentColor" stroke="none"/><rect x="14" y="5" width="4" height="14" fill="currentColor" stroke="none"/>',
    step: '<path d="M4 15a8 8 0 0 1 15-4"/><path d="M20 6v5h-5"/><circle cx="12" cy="20" r="1.6" fill="currentColor"/>',
    stepin: '<path d="M12 3v11M7 9l5 5 5-5"/><circle cx="12" cy="20" r="1.8" fill="currentColor"/>',
    stepout: '<path d="M12 15V4M7 9l5-5 5 5"/><circle cx="12" cy="20" r="1.8" fill="currentColor"/>',
    cont: '<path d="M5 4l10 8-10 8z" fill="currentColor" stroke="none"/><path d="M19 4v16"/>',
    quitdbg: '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9l6 6M15 9l-6 6"/>',
    bp: '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>',
    bpclear: '<circle cx="12" cy="12" r="6"/><path d="M6 18L18 6"/>',
    comment: '<path d="M7 8h2M7 12h2M7 16h2"/><path d="M12 8h6M12 12h5M12 16h6"/><path d="M4 4l2 16" />',
    indent: '<path d="M4 6h16M10 10h10M10 14h10M4 18h16"/><path d="M4 9l3 3-3 3"/>',
    find: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    goto: '<path d="M4 6h10M4 12h7M4 18h10"/><path d="M15 9l5 3-5 3z" fill="currentColor"/>',
    clear: '<path d="M4 20h16"/><path d="M7 16l9-12 4 3-9 12H7z"/>',
    clearws: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9l6 6M15 9l-6 6"/>',
    variable: '<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="M3 10h18M9 5v14M15 5v14"/>',
    import: '<path d="M4 4h10l4 4v12H4z"/><path d="M12 10v7M9 14l3 3 3-3"/>',
    savews: '<path d="M5 3h12l3 3v15H5z"/><path d="M8 13h8M8 17h8M8 3v5h8V3"/>',
    layout: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M9 4v16M9 12h12"/>',
    prefs: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7V14"/><circle cx="12" cy="17.2" r="0.6" fill="currentColor"/>',
    examples: '<path d="M4 5h7v14H4zM13 5h7v14h-7z"/><path d="M6 8h3M6 11h3M15 8h3M15 11h3"/>',
    python: '<path d="M12 3c-4 0-4 1.5-4 3v2h5v1H6c-2 0-3 1.5-3 4s1 4 3 4h2v-2.5c0-1.5 1-2.5 2.5-2.5h4c1.5 0 2.5-1 2.5-2.5V6c0-1.5-1-3-5-3z"/><circle cx="10" cy="5.5" r="0.7" fill="currentColor"/>',
    back: '<path d="M15 5l-7 7 7 7"/>',
    fwd: '<path d="M9 5l7 7-7 7"/>',
    up: '<path d="M12 19V6M6 11l6-6 6 6"/>',
    browse: '<path d="M3 6h6l2 2h10v11H3z"/><path d="M12 12v4M10 14h4"/>',
    refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
    more: '<circle cx="12" cy="5.5" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="18.5" r="1.4" fill="currentColor"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    minimize: '<path d="M5 12h14"/>',
    zoomin: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.5h5M10.5 8v5"/>',
    zoomout: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5M8 10.5h5"/>',
    pan: '<path d="M12 3v18M3 12h18"/><path d="M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5"/>',
    rotate: '<path d="M4 12a8 4 0 1 0 8-4"/><path d="M12 4v8M9 6l3-2 3 2"/>',
    datatip: '<path d="M4 4h12v9H9l-3 3v-3H4z"/><circle cx="19" cy="19" r="2" fill="currentColor"/>',
    home: '<path d="M4 11l8-7 8 7"/><path d="M6 10v10h12V10"/>',
    image: '<rect x="3" y="5" width="18" height="14" rx="1.5"/><circle cx="9" cy="10" r="1.8"/><path d="M3 17l6-5 4 3 3-2 5 4"/>',
    dock: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 9h18"/><rect x="6" y="12" width="8" height="5" fill="currentColor" stroke="none"/>',
    undock: '<rect x="3" y="7" width="13" height="13" rx="1.5"/><path d="M8 3h13v13"/>',
    legend: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M6 9h4M6 14h4"/><path d="M12 9h6M12 14h6" stroke-width="1"/>',
    grid: '<rect x="3" y="3" width="18" height="18"/><path d="M9 3v18M15 3v18M3 9h18M3 15h18" stroke-width="1"/>',
    colorbar: '<rect x="14" y="3" width="5" height="18"/><path d="M4 20l4-8 3 4"/>',
    full: '<path class="pl-full-on" d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    folder: '<path d="M3 6h6l2 2h10v11H3z" fill="currentColor" fill-opacity="0.15"/>',
    mfile: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M8.5 16v-5l2.5 3 2.5-3v5" stroke-width="1.4"/>',
    matfile: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><rect x="8.5" y="11" width="7" height="6" stroke-width="1.3"/><path d="M8.5 14h7M12 11v6" stroke-width="1.1"/>',
    textfile: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 15h6M9 18h4" stroke-width="1.3"/>',
    file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    figure: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M6 16l4-5 3 3 5-6"/>',
    // plot gallery
    g_plot: '<path d="M3 20h18M3 20V4"/><path d="M4 16c3-9 5-9 8-2s5 7 8-6" />',
    g_scatter: '<path d="M3 20h18M3 20V4"/><circle cx="7" cy="14" r="1.3" fill="currentColor"/><circle cx="10" cy="9" r="1.3" fill="currentColor"/><circle cx="14" cy="12" r="1.3" fill="currentColor"/><circle cx="17" cy="6" r="1.3" fill="currentColor"/><circle cx="12" cy="16" r="1.3" fill="currentColor"/>',
    g_bar: '<path d="M3 20h18"/><rect x="5" y="11" width="3" height="9" fill="currentColor" fill-opacity="0.35"/><rect x="10" y="6" width="3" height="14" fill="currentColor" fill-opacity="0.35"/><rect x="15" y="13" width="3" height="7" fill="currentColor" fill-opacity="0.35"/>',
    g_hist: '<path d="M3 20h18"/><path d="M4 20v-4h3v-6h3V5h3v4h3v6h3v5" fill="currentColor" fill-opacity="0.25"/>',
    g_area: '<path d="M3 20h18M3 20V4"/><path d="M4 18l4-6 4 2 4-7 4 3v10H4z" fill="currentColor" fill-opacity="0.3"/>',
    g_stairs: '<path d="M3 20h18M3 20V4"/><path d="M4 17h4v-4h4v3h4V8h4"/>',
    g_stem: '<path d="M3 20h18"/><path d="M6 20v-8M10 20V7M14 20v-5M18 20V9"/><circle cx="6" cy="12" r="1.4"/><circle cx="10" cy="7" r="1.4"/><circle cx="14" cy="15" r="1.4"/><circle cx="18" cy="9" r="1.4"/>',
    g_surf: '<path d="M3 15l6-4 6 3 6-4M3 15l4 4 6-3 8 2M9 11l4 5M15 14l6 4" />',
    g_mesh: '<path d="M3 14l6-4 6 3 6-4M3 14l5 5 6-3 7 2M9 10l5 6M15 13l6 5M6 12l5 5M12 11.5l5 5.5" stroke-width="1"/>',
    g_contour: '<ellipse cx="12" cy="12" rx="9" ry="7"/><ellipse cx="12" cy="12" rx="5.5" ry="4"/><ellipse cx="12" cy="12" rx="2" ry="1.4"/>',
    g_image: '<rect x="3" y="3" width="6" height="6" fill="currentColor" fill-opacity="0.2"/><rect x="9" y="3" width="6" height="6" fill="currentColor" fill-opacity="0.6"/><rect x="15" y="3" width="6" height="6" fill="currentColor" fill-opacity="0.35"/><rect x="3" y="9" width="6" height="6" fill="currentColor" fill-opacity="0.7"/><rect x="9" y="9" width="6" height="6" fill="currentColor" fill-opacity="0.1"/><rect x="15" y="9" width="6" height="6" fill="currentColor" fill-opacity="0.5"/><rect x="3" y="15" width="6" height="6" fill="currentColor" fill-opacity="0.4"/><rect x="9" y="15" width="6" height="6" fill="currentColor" fill-opacity="0.8"/><rect x="15" y="15" width="6" height="6" fill="currentColor" fill-opacity="0.25"/>',
    g_pie: '<circle cx="12" cy="12" r="8"/><path d="M12 12V4M12 12l7 4"/><path d="M12 12V4a8 8 0 0 1 7 12z" fill="currentColor" fill-opacity="0.3"/>',
    g_plot3: '<path d="M4 18l6-3V5M10 15l10 3"/><path d="M6 14c4-6 7 4 12-4" />',
  };

  function icon(name, cls) {
    const ns = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(ns, 'svg');
    s.setAttribute('viewBox', '0 0 24 24');
    s.setAttribute('fill', 'none');
    s.setAttribute('stroke', 'currentColor');
    s.setAttribute('stroke-width', '1.6');
    s.setAttribute('stroke-linecap', 'round');
    s.setAttribute('stroke-linejoin', 'round');
    s.setAttribute('aria-hidden', 'true');
    if (cls) s.setAttribute('class', cls);
    s.innerHTML = P[name] || '';
    return s;
  }

  /* ---- menus ----------------------------------------------------------------- */
  let openMenu = null;

  function closeMenu() {
    if (openMenu) {
      openMenu.remove();
      openMenu = null;
      document.removeEventListener('pointerdown', onAway, true);
      document.removeEventListener('keydown', onMenuKey, true);
    }
  }

  function onAway(ev) {
    if (openMenu && !openMenu.contains(ev.target)) closeMenu();
  }

  function onMenuKey(ev) {
    if (!openMenu) return;
    const items = [...openMenu.querySelectorAll('button:not(:disabled)')];
    const i = items.indexOf(document.activeElement);
    if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeMenu(); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); (items[i + 1] || items[0])?.focus(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); (items[i - 1] || items[items.length - 1])?.focus(); }
  }

  function menu(x, y, items) {
    closeMenu();
    const m = el('div', { class: 'pl-menu', role: 'menu' });
    for (const it of items) {
      if (!it) continue;
      if (it === '-') { m.append(el('hr')); continue; }
      if (it.heading) { m.append(el('div', { class: 'pl-menu-label' }, it.heading)); continue; }
      const b = el('button', { role: 'menuitem', disabled: !!it.disabled, type: 'button' },
        it.checked !== undefined ? el('span', { class: 'chk' }, it.checked ? '✓' : '') : null,
        el('span', null, it.label), it.kbd ? el('span', { class: 'kbd' }, it.kbd) : null);
      b.addEventListener('click', () => { closeMenu(); if (it.action) it.action(); });
      m.append(b);
    }
    document.body.append(m);
    const r = m.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    m.style.left = `${Math.max(4, Math.min(x, vw - r.width - 4))}px`;
    m.style.top = `${Math.max(4, Math.min(y, vh - r.height - 4))}px`;
    openMenu = m;
    setTimeout(() => {
      document.addEventListener('pointerdown', onAway, true);
      document.addEventListener('keydown', onMenuKey, true);
    }, 0);
    m.querySelector('button:not(:disabled)')?.focus({ preventScroll: true });
    return m;
  }

  /* ---- dialogs ---------------------------------------------------------------------- */
  function dialog({ title, body, buttons = [{ label: 'OK', value: true, primary: true }], onOpen, width }) {
    return new Promise((resolve) => {
      const back = el('div', { class: 'pl-modal-back' });
      const box = el('div', { class: 'pl-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
      if (width) box.style.width = `min(${width}px, calc(100vw - 32px))`;
      const bodyEl = el('div', { class: 'pl-dbody' }, body);
      const foot = el('div', { class: 'pl-dfoot' });
      const done = (v) => { back.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
      for (const b of buttons) {
        const btn = el('button', { class: `pl-btn${b.primary ? ' is-primary' : ''}`, type: 'button' }, b.label);
        btn.addEventListener('click', () => done(typeof b.value === 'function' ? b.value(bodyEl) : b.value));
        foot.append(btn);
      }
      const onKey = (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); done(null); }
        if (ev.key === 'Enter' && ev.target.tagName !== 'TEXTAREA' && ev.target.tagName !== 'BUTTON') {
          const p = buttons.find((b) => b.primary);
          if (p) { ev.preventDefault(); done(typeof p.value === 'function' ? p.value(bodyEl) : p.value); }
        }
      };
      document.addEventListener('keydown', onKey, true);
      box.append(el('header', null, el('span', null, title)), bodyEl, foot);
      back.append(box);
      document.body.append(back);
      if (onOpen) onOpen(bodyEl);
      const f = bodyEl.querySelector('input, select, textarea') || foot.querySelector('.is-primary');
      if (f) setTimeout(() => { f.focus(); if (f.select) f.select(); }, 0);
    });
  }

  async function prompt(title, label, value = '') {
    const r = await dialog({
      title,
      body: el('label', null, label, el('input', { type: 'text', value, spellcheck: 'false', autocomplete: 'off' })),
      buttons: [{ label: 'Cancel', value: null }, { label: 'OK', primary: true, value: (b) => b.querySelector('input').value }],
    });
    return r;
  }

  async function confirm(title, text, ok = 'OK') {
    return dialog({ title, body: el('p', { style: { margin: 0 } }, text), buttons: [{ label: 'Cancel', value: false }, { label: ok, primary: true, value: true }] });
  }

  let toastTimer = 0;
  function toast(text, ms = 2600) {
    document.querySelector('.pl-toast')?.remove();
    const t = el('div', { class: 'pl-toast', role: 'status' }, text);
    document.body.append(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), ms);
  }

  const store = {
    get(key, dflt) {
      try {
        const v = localStorage.getItem(`pylab.${key}`);
        return v === null ? dflt : JSON.parse(v);
      } catch (e) { return dflt; }
    },
    set(key, value) {
      try { localStorage.setItem(`pylab.${key}`, JSON.stringify(value)); } catch (e) { /* full or blocked */ }
    },
  };

  function download(name, data, type = 'application/octet-stream') {
    const blob = data instanceof Blob ? data : new Blob([data], { type });
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const mod = (ev) => (isMac ? ev.metaKey : ev.ctrlKey);
  const modName = isMac ? '⌘' : 'Ctrl+';

  function basename(p) { return p.slice(p.lastIndexOf('/') + 1); }
  function dirname(p) { const i = p.lastIndexOf('/'); return i <= 0 ? '/' : p.slice(0, i); }
  function joinPath(a, b) { if (b.startsWith('/')) return b; return `${a.replace(/\/+$/, '')}/${b}`; }

  /* A text as a char vector of the language ('it''s'), for a command the
     page writes; null when it holds a control character, which a char
     vector cannot hold. File names and paths go into commands only this way,
     and as a bare name only when isName: what comes from a file never
     becomes code. */
  function mstr(s) {
    return /[\u0000-\u001f\u007f]/.test(s) ? null : `'${s.replace(/'/g, "''")}'`;
  }
  const isName = (s) => /^[A-Za-z][A-Za-z0-9_]*$/.test(s);

  function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }

  PL.util = { el, Emitter, icon, menu, closeMenu, dialog, prompt, confirm, toast, store, download, isMac, mod, modName, basename, dirname, joinPath, mstr, isName, fmtBytes };
  PL.el = el;
  PL.Emitter = Emitter;
  PL.icon = icon;
})(window);
