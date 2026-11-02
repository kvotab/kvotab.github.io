/* ==========================================================================
   PYLAB.HTML: USER INTERFACES IN FIGURES

   What a program makes with uicontrol, uipanel, uibuttongroup, uitable,
   uitabgroup, uimenu, uicontextmenu and uitoolbar, built as HTML in a
   figure window from the description the engine sends
   (uiobjects.serialize_ui): a menu bar, rows of tool icons, and controls
   over the canvas, each placed in its Units from the lower left of its
   container. Panels and tabs are painted on the canvas (axes may sit in
   them); their titles, borders and controls are HTML.

   What people do goes back as events (uievents.handle in the engine),
   which set what the program reads and queue its callbacks:
     control  click, toggle, radio, edit, slider, list, popup, tab, and a
              table's edit and select
     menu     a menu item chosen; menuopen when a menu with a Callback opens
     tool     a toolbar tool pressed
     key      a key in the figure or a control (with the program's names)
   The figure window (pylab-figure.js) adds the mouse, close and resize.
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el } = PL;

  const UNIT_PX = { pixels: [1, 1], points: [4 / 3, 4 / 3], inches: [96, 96], centimeters: [96 / 2.54, 96 / 2.54], characters: [5, 13] };
  const MONO = 'ui-monospace, "IBM Plex Mono", Menlo, Consolas, monospace';
  const SANS = '"Helvetica Neue", Helvetica, Arial, sans-serif';

  function color(c, fallback = '') {
    if (!Array.isArray(c)) return fallback;
    return `rgb(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)})`;
  }

  /* MATLAB's FixedWidth (and the usual monospaced names) is a monospaced face. */
  function family(name) {
    const n = String(name || '').toLowerCase();
    if (n === 'fixedwidth' || /courier|mono|consol|menlo/.test(n)) return MONO;
    return SANS;
  }

  function fontPx(c, boxH) {
    const s = c.fontSize || 8;
    switch (c.fontUnits) {
      case 'pixels': return s;
      case 'normalized': return s * (boxH || 20);
      case 'inches': return s * 96;
      case 'centimeters': return s * 96 / 2.54;
      default: return s * 4 / 3;
    }
  }

  /* '&File' is File (the letter after & is a menu's mnemonic); '&&' is &. */
  function label(s) { return String(s || '').replace(/&&|&/g, (m) => (m === '&&' ? '&' : '')); }

  function accelText(a) { return a ? (PL.util.isMac ? `⌘${a.toUpperCase()}` : `Ctrl+${a.toUpperCase()}`) : ''; }

  const iconCache = new Map();
  /* A tool's or a button's picture: RGBA bytes as a data URL. */
  function iconURL(cd) {
    if (!cd || !cd.rgba) return null;
    const key = cd.rgba;
    if (iconCache.has(key)) return iconCache.get(key);
    const bin = atob(cd.rgba);
    const c = document.createElement('canvas');
    c.width = cd.w;
    c.height = cd.h;
    const ctx = c.getContext('2d');
    const img = ctx.createImageData(cd.w, cd.h);
    for (let i = 0; i < bin.length; i++) img.data[i] = bin.charCodeAt(i);
    ctx.putImageData(img, 0, 0);
    const url = c.toDataURL('image/png');
    if (iconCache.size > 400) iconCache.clear();
    iconCache.set(key, url);
    return url;
  }

  function place(elm, c) {
    const [x, y, w, h] = c.pos;
    const s = elm.style;
    if (c.units === 'normalized') {
      s.left = `${x * 100}%`; s.bottom = `${y * 100}%`; s.width = `${Math.max(0, w) * 100}%`; s.height = `${Math.max(0, h) * 100}%`;
    } else {
      const [sx, sy] = UNIT_PX[c.units] || [1, 1];
      s.left = `${x * sx}px`; s.bottom = `${y * sy}px`; s.width = `${Math.max(0, w * sx)}px`; s.height = `${Math.max(0, h * sy)}px`;
    }
  }

  function findMenu(list, id) {
    for (const m of list || []) {
      if (m.id === id) return m;
      const f = findMenu(m.items, id);
      if (f) return f;
    }
    return null;
  }

  /* ---- keys, as programs name them ------------------------------------------------------------- */
  const KEYS = {
    ArrowLeft: ['leftarrow', '\x1c'], ArrowRight: ['rightarrow', '\x1d'], ArrowUp: ['uparrow', '\x1e'], ArrowDown: ['downarrow', '\x1f'],
    Enter: ['return', '\r'], Escape: ['escape', '\x1b'], Backspace: ['backspace', '\b'], Delete: ['delete', '\x7f'], Tab: ['tab', '\t'],
    ' ': ['space', ' '], Shift: ['shift', ''], Control: ['control', ''], Alt: ['alt', ''], Meta: ['command', ''], CapsLock: ['capslock', ''],
    Home: ['home', ''], End: ['end', ''], PageUp: ['pageup', ''], PageDown: ['pagedown', ''], Insert: ['insert', ''],
  };
  const CODES = {
    Comma: 'comma', Period: 'period', Slash: 'slash', Semicolon: 'semicolon', Quote: 'quote', BracketLeft: 'leftbracket',
    BracketRight: 'rightbracket', Backslash: 'backslash', Minus: 'hyphen', Equal: 'equal', Backquote: 'backquote',
    NumpadAdd: 'add', NumpadSubtract: 'subtract', NumpadMultiply: 'multiply', NumpadDivide: 'divide', NumpadDecimal: 'decimal',
  };

  /* The keys held down, as Modifier names (for keys and clicks alike). */
  function modsOf(ev) {
    const mods = [];
    if (ev.shiftKey) mods.push('shift');
    if (ev.ctrlKey) mods.push('control');
    if (ev.altKey) mods.push('alt');
    if (ev.metaKey) mods.push('command');
    return mods;
  }

  /* A keyboard event as Key, Character and Modifier. */
  function keyInfo(ev) {
    const mods = modsOf(ev);
    let key;
    let ch;
    if (KEYS[ev.key]) [key, ch] = KEYS[ev.key];
    else if (/^F\d{1,2}$/.test(ev.key)) { key = ev.key.toLowerCase(); ch = ''; }
    else if (/^Numpad\d$/.test(ev.code)) { key = `numpad${ev.code.slice(6)}`; ch = ev.key.length === 1 ? ev.key : ''; }
    else if (CODES[ev.code]) { key = CODES[ev.code]; ch = ev.key.length === 1 ? ev.key : ''; }
    else if (ev.key.length === 1) {
      key = ev.key.toLowerCase();
      ch = ev.key;
      // Ctrl and a letter types a control character
      if (ev.ctrlKey && /^[a-z]$/i.test(ev.key)) ch = String.fromCharCode(ev.key.toLowerCase().charCodeAt(0) - 96);
    } else { key = ev.key.toLowerCase(); ch = ''; }
    return { key, character: ch, modifiers: mods };
  }

  /* ---- menus that drop down, and context menus ---------------------------------------------------- */
  /* One stack of open menus on the page: a menu bar's or a context menu,
     each level a popup; the owner is told what was picked and which menus
     with a Callback opened. */
  const menus = {
    stack: [],          // { el, of } from the first level down
    owner: null,

    open(items, x, y, owner, of) {
      this.close();
      this.owner = owner;
      this.push(items, x, y, 0, of);
      document.addEventListener('pointerdown', this.away, true);
      document.addEventListener('keydown', this.key, true);
      this.stack[0]?.el.querySelector('button:not(:disabled)')?.focus({ preventScroll: true });
    },

    push(items, x, y, level, of) {
      this.trim(level);
      const m = el('div', { class: 'pl-menu pl-figpopup', role: 'menu' });
      this.fill(m, items, level);
      document.body.append(m);
      const r = m.getBoundingClientRect();
      m.style.left = `${Math.max(4, Math.min(x, window.innerWidth - r.width - 4))}px`;
      m.style.top = `${Math.max(4, Math.min(y, window.innerHeight - r.height - 4))}px`;
      this.stack.push({ el: m, of, items });
      return m;
    },

    fill(m, items, level) {
      m.replaceChildren();
      for (const it of items || []) {
        if (!it.visible) continue;
        if (it.sep && m.childElementCount) m.append(el('hr'));
        const kids = (it.items || []).some((k) => k.visible);
        const b = el('button', { type: 'button', role: 'menuitem', disabled: !it.enable, 'aria-haspopup': kids ? 'menu' : null, 'aria-checked': it.checked ? 'true' : null },
          el('span', { class: 'chk' }, it.checked ? '✓' : ''), el('span', { class: 'lbl' }, label(it.label)),
          it.accel ? el('span', { class: 'kbd' }, accelText(it.accel)) : null, kids ? el('span', { class: 'sub', 'aria-hidden': 'true' }, '›') : null);
        b.dataset.id = String(it.id);
        b.addEventListener('pointerenter', () => { if (kids) this.sub(it, b, level, false); else this.trim(level + 1); });
        b.addEventListener('click', () => {
          if (kids) { this.sub(it, b, level, true); return; }
          const owner = this.owner;
          this.close();
          if (owner) owner.pick(it);
        });
        m.append(b);
      }
      if (!m.childElementCount) m.append(el('div', { class: 'pl-menu-label' }, '(empty)'));
    },

    sub(it, b, level, focus) {
      const next = this.stack[level + 1];
      if (next && next.of === it.id) { if (focus) next.el.querySelector('button:not(:disabled)')?.focus(); return; }
      if (it.cb && this.owner) this.owner.opened(it);
      const r = b.getBoundingClientRect();
      const m = this.push(it.items, r.right - 3, r.top - 5, level + 1, it.id);
      if (focus) m.querySelector('button:not(:disabled)')?.focus();
    },

    trim(level) {
      while (this.stack.length > level) this.stack.pop().el.remove();
    },

    close() {
      const owner = this.owner;
      this.trim(0);
      this.owner = null;
      document.removeEventListener('pointerdown', this.away, true);
      document.removeEventListener('keydown', this.key, true);
      if (owner && owner.closed) owner.closed();
    },

    /* The owner's menus changed while open (a Callback set Checked, say): the
       open levels show the new items. */
    refresh(find) {
      for (const s of this.stack) {
        const items = find(s.of);
        if (items) { s.items = items; this.fill(s.el, items, this.stack.indexOf(s)); }
      }
    },

    away: (ev) => {
      if (!menus.stack.some((s) => s.el.contains(ev.target)) && !(menus.owner && menus.owner.holds && menus.owner.holds(ev.target))) menus.close();
    },

    key: (ev) => {
      const st = menus.stack;
      if (!st.length) return;
      const level = Math.max(0, st.findIndex((s) => s.el.contains(document.activeElement)));
      const items = [...st[level].el.querySelectorAll('button:not(:disabled)')];
      const i = items.indexOf(document.activeElement);
      const stop = () => { ev.preventDefault(); ev.stopPropagation(); };
      if (ev.key === 'Escape' && level > 0) {
        stop();
        const of = st[level].of;
        menus.trim(level);
        st[level - 1].el.querySelector(`button[data-id="${of}"]`)?.focus();
      } else if (ev.key === 'Escape') { stop(); menus.close(); }
      else if (ev.key === 'ArrowDown') { stop(); (items[i + 1] || items[0])?.focus(); }
      else if (ev.key === 'ArrowUp') { stop(); (items[i - 1] || items[items.length - 1])?.focus(); }
      else if (ev.key === 'ArrowRight') {
        stop();
        if (document.activeElement?.getAttribute('aria-haspopup')) document.activeElement.click();
        else if (menus.owner && menus.owner.step) menus.owner.step(1);
      } else if (ev.key === 'ArrowLeft') {
        stop();
        if (level > 0) { const of = st[level].of; menus.trim(level); st[level - 1].el.querySelector(`button[data-id="${of}"]`)?.focus(); }
        else if (menus.owner && menus.owner.step) menus.owner.step(-1);
      } else if (ev.key === 'Tab') { stop(); menus.close(); }
    },
  };

  /* ---- a figure window's user interface ----------------------------------------------------------- */
  class FigureUI {
    constructor(win) {
      this.win = win;
      this.menubar = el('div', { class: 'pl-figmenubar', role: 'menubar', hidden: true });
      this.toolbars = el('div', { class: 'pl-uitoolbars', hidden: true });
      this.layer = el('div', { class: 'pl-uilayer' });
      this.ctl = new Map();          // control id -> { el, kind, c, body?, tabs? }
      this.topOpen = null;
      this._mbKey = '';
      this._tbKey = '';
    }

    ui(ev) { this.win.mgr.ui(ev); }

    update(fig) {
      this.fig = fig;
      this.buildMenubar(fig);
      this.buildToolbars(fig);
      this.seen = new Set();
      this.syncList(fig.controls || [], this.layer);
      for (const [id, rec] of [...this.ctl]) if (!this.seen.has(id)) { rec.el.remove(); this.ctl.delete(id); }
      if (menus.owner && menus.owner.fig === this) {
        menus.refresh((id) => {
          const m = findMenu(fig.menus, id) || (fig.cmenus || []).find((x) => x.id === id);
          return m ? m.items : null;
        });
      }
      if (fig.dialog && !this.focusedOnce) {
        // a dialog's first button takes the keys (Enter is OK)
        this.focusedOnce = true;
        requestAnimationFrame(() => this.layer.querySelector('button.pl-uibtn:not(:disabled)')?.focus({ preventScroll: true }));
      }
    }

    /* ---- the menu bar ---- */
    buildMenubar(fig) {
      const vis = (fig.menus || []).filter((m) => m.visible);
      this.menubar.hidden = !vis.length;
      const key = JSON.stringify(vis.map((m) => [m.id, m.label, m.enable]));
      if (key === this._mbKey) return;
      this._mbKey = key;
      this.menubar.replaceChildren(...vis.map((m) => {
        const b = el('button', { type: 'button', class: 'pl-figmenu-top', role: 'menuitem', disabled: !m.enable, 'aria-haspopup': 'menu' }, label(m.label));
        b.dataset.id = String(m.id);
        b.addEventListener('click', () => this.openTop(m.id));
        b.addEventListener('pointerenter', () => { if (menus.owner && menus.owner.fig === this && menus.owner.bar && this.topOpen !== m.id) this.openTop(m.id); });
        return b;
      }));
    }

    menuOwner(bar) {
      return {
        fig: this,
        bar,
        pick: (it) => { this.win.el.focus({ preventScroll: true }); this.ui({ type: 'menu', id: it.id }); },
        opened: (it) => this.ui({ type: 'menuopen', id: it.id }),
        closed: () => { this.topOpen = null; for (const b of this.menubar.children) b.classList.remove('is-open'); },
        holds: (t) => bar && this.menubar.contains(t),
        step: bar ? (d) => {
          const tops = [...this.menubar.querySelectorAll('button:not(:disabled)')];
          const i = tops.findIndex((b) => Number(b.dataset.id) === this.topOpen);
          const n = tops[(i + d + tops.length) % tops.length];
          if (n) this.openTop(Number(n.dataset.id));
        } : null,
      };
    }

    openTop(id) {
      const m = findMenu(this.fig.menus, id);
      const b = this.menubar.querySelector(`button[data-id="${id}"]`);
      if (!m || !b) return;
      if (this.topOpen === id && menus.owner && menus.owner.fig === this) { menus.close(); return; }
      const kids = (m.items || []).some((k) => k.visible);
      if (!kids) { menus.close(); this.ui({ type: 'menu', id }); return; }
      if (m.cb) this.ui({ type: 'menuopen', id });
      const r = b.getBoundingClientRect();
      menus.open(m.items, r.left, r.bottom + 1, this.menuOwner(true), id);
      this.topOpen = id;
      for (const x of this.menubar.children) x.classList.toggle('is-open', x === b);
    }

    showCmenu(id, x, y) {
      const cm = (this.fig.cmenus || []).find((m) => m.id === id);
      if (!cm) return false;
      if (cm.cb) this.ui({ type: 'menuopen', id });
      menus.open(cm.items, x, y, this.menuOwner(false), id);
      return true;
    }

    /* Ctrl (⌘ on a Mac) and a menu's Accelerator chooses it. */
    accelerator(ev) {
      if (!(PL.util.isMac ? ev.metaKey : ev.ctrlKey) || ev.altKey || ev.key.length !== 1) return false;
      const want = ev.key.toLowerCase();
      const find = (list, ok) => {
        for (const m of list || []) {
          if (!m.visible) continue;
          const on = ok && m.enable;
          if (m.accel && m.accel.toLowerCase() === want && !(m.items || []).some((k) => k.visible)) return on ? m : null;
          const f = find(m.items, on);
          if (f) return f;
        }
        return null;
      };
      const m = find(this.fig.menus, true);
      if (!m) return false;
      ev.preventDefault();
      ev.stopPropagation();
      this.ui({ type: 'menu', id: m.id });
      return true;
    }

    /* ---- toolbars ---- */
    buildToolbars(fig) {
      const bars = (fig.toolbars || []).filter((t) => t.visible && t.tools.some((x) => x.visible));
      this.toolbars.hidden = !bars.length;
      const key = JSON.stringify(bars);
      if (key === this._tbKey) return;
      this._tbKey = key;
      this.toolbars.replaceChildren(...bars.map((tb) => {
        const row = el('div', { class: 'pl-uitoolbar', role: 'toolbar', 'aria-label': 'Program tools' });
        for (const t of tb.tools) {
          if (!t.visible) continue;
          if (t.sep && row.childElementCount) row.append(el('span', { class: 'sep', 'aria-hidden': 'true' }));
          const url = iconURL(t.cdata);
          const b = el('button', { type: 'button', class: 'pl-uitool', title: t.tip || null, 'aria-label': t.tip || t.tag || 'Tool', disabled: !t.enable,
            'aria-pressed': t.kind === 'toggle' ? String(!!t.state) : null },
          url ? el('img', { src: url, alt: '', width: t.cdata.w, height: t.cdata.h, draggable: 'false' }) : el('span', { class: 'noicon' }));
          b.addEventListener('click', () => {
            if (t.kind === 'toggle') {
              const on = b.getAttribute('aria-pressed') !== 'true';
              b.setAttribute('aria-pressed', String(on));
              this.ui({ type: 'tool', id: t.id, on });
            } else this.ui({ type: 'tool', id: t.id });
          });
          row.append(b);
        }
        return row;
      }));
    }

    /* ---- controls ---- */
    syncList(list, host) {
      let prev = null;
      for (const c of list) {
        const kind = c.type === 'uicontrol' ? `uicontrol:${c.style}:${c.style === 'edit' && c.max - c.min > 1 ? 'multi' : ''}:${c.style === 'listbox' && c.max - c.min > 1 ? 'multi' : ''}` : c.type;
        let rec = this.ctl.get(c.id);
        if (!rec || rec.kind !== kind) {
          if (rec) rec.el.remove();
          rec = this.make(c, kind);
          this.ctl.set(c.id, rec);
        }
        this.seen.add(c.id);
        this.apply(rec, c);
        const want = prev ? prev.nextSibling : host.firstChild;
        if (rec.el.parentNode !== host || rec.el !== want) host.insertBefore(rec.el, want);
        prev = rec.el;
        if (rec.body) this.syncList(c.children || [], rec.body);
        if (c.type === 'uitabgroup') for (const t of c.tabs) this.syncList(t.children || [], rec.tabBody(t.id));
      }
    }

    make(c, kind) {
      const rec = { kind, c };
      const send = (ev) => this.ui(Object.assign({ type: 'control', id: rec.c.id }, ev));
      const ctx = (e) => {
        const cc = rec.c;
        if (cc.bdf) send({ action: 'down', button: 3 });
        if (cc.cmenu && this.showCmenu(cc.cmenu, e.clientX, e.clientY)) e.preventDefault();
        else if (cc.bdf) e.preventDefault();
      };
      let e;
      switch (c.type === 'uicontrol' ? c.style : c.type) {
        case 'pushbutton':
        case 'togglebutton':
          e = el('button', { type: 'button', class: 'pl-uictl pl-uibtn' });
          rec.img = el('img', { alt: '', draggable: 'false', hidden: true });
          rec.text = el('span');
          e.append(rec.img, rec.text);
          e.addEventListener('click', () => {
            if (rec.c.style === 'togglebutton') {
              const on = e.getAttribute('aria-pressed') !== 'true';
              e.setAttribute('aria-pressed', String(on));
              send({ action: 'toggle', on });
            } else send({ action: 'click' });
          });
          break;
        case 'checkbox':
        case 'radiobutton': {
          rec.input = el('input', { type: c.style === 'checkbox' ? 'checkbox' : 'radio' });
          rec.text = el('span');
          e = el('label', { class: `pl-uictl pl-ui${c.style === 'checkbox' ? 'check' : 'radio'}` }, rec.input, rec.text);
          rec.input.addEventListener('click', (ev) => {
            if (rec.c.style === 'radiobutton') {
              const grouped = this.ctl.get(rec.c.id)?.el.parentNode?.closest?.('.pl-uigroup');
              if (grouped) {
                for (const r of grouped.querySelectorAll(':scope > .pl-uibody > .pl-uiradio > input')) r.checked = r === rec.input;
                ev.target.checked = true;
              }
              send({ action: 'radio' });
            } else send({ action: 'toggle', on: rec.input.checked });
          });
          break;
        }
        case 'edit': {
          const multi = c.max - c.min > 1;
          rec.input = multi ? el('textarea', { spellcheck: 'false' }) : el('input', { type: 'text', spellcheck: 'false', autocomplete: 'off' });
          e = el('div', { class: 'pl-uictl pl-uiedit' }, rec.input);
          const commit = () => {
            const v = rec.input.value;
            if (v === rec.start) return;
            rec.start = v;
            send({ action: 'edit', string: multi ? v.split('\n') : v });
          };
          rec.input.addEventListener('focus', () => { rec.start = rec.input.value; });
          rec.input.addEventListener('blur', commit);
          rec.input.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter' && (!multi || PL.util.mod(ev))) { ev.preventDefault(); commit(); }
          });
          break;
        }
        case 'text':
          e = el('div', { class: 'pl-uictl pl-uitext' });
          rec.img = el('img', { alt: '', draggable: 'false', hidden: true });
          rec.text = el('div', { class: 'lines' });
          e.append(rec.img, rec.text);
          break;
        case 'frame':
          e = el('div', { class: 'pl-uictl pl-uiframe' });
          break;
        case 'slider':
          rec.input = el('input', { type: 'range' });
          e = el('div', { class: 'pl-uictl pl-uislider' }, rec.input);
          rec.input.addEventListener('pointerdown', () => { rec.dragging = true; });
          rec.input.addEventListener('pointerup', () => { rec.dragging = false; });
          rec.input.addEventListener('change', () => { rec.dragging = false; send({ action: 'slider', value: Number(rec.input.value) }); });
          break;
        case 'listbox':
        case 'popupmenu': {
          const list = c.style === 'listbox';
          rec.input = el('select', { multiple: list && c.max - c.min > 1 });
          e = el('div', { class: `pl-uictl ${list ? 'pl-uilist' : 'pl-uipopup'}` }, rec.input);
          const chosen = () => [...rec.input.options].filter((o) => o.selected).map((o) => Number(o.value) + 1);
          rec.input.addEventListener('change', () => send({ action: list ? 'list' : 'popup', value: chosen() }));
          if (list) rec.input.addEventListener('dblclick', () => send({ action: 'list', value: chosen(), open: true }));
          break;
        }
        case 'uipanel':
        case 'uibuttongroup':
          rec.title = el('span', { class: 'title' });
          rec.body = el('div', { class: 'pl-uibody' });
          e = el('div', { class: `pl-uictl pl-uipanel${c.type === 'uibuttongroup' ? ' pl-uigroup' : ''}`, role: 'group' }, rec.title, rec.body);
          break;
        case 'uitabgroup': {
          rec.strip = el('div', { class: 'strip', role: 'tablist' });
          rec.bodies = el('div', { class: 'bodies' });
          rec.tabs = new Map();
          rec.tabBody = (id) => {
            let t = rec.tabs.get(id);
            if (!t) {
              t = { body: el('div', { class: 'pl-uibody pl-uitabbody', role: 'tabpanel' }) };
              rec.tabs.set(id, t);
              rec.bodies.append(t.body);
            }
            return t.body;
          };
          e = el('div', { class: 'pl-uictl pl-uitabs' }, rec.strip, rec.bodies);
          break;
        }
        case 'uitable':
          e = el('div', { class: 'pl-uictl pl-uitable', tabindex: '-1' });
          break;
        default:
          e = el('div', { class: 'pl-uictl' });
      }
      e.dataset.id = String(c.id);
      e.addEventListener('contextmenu', ctx);
      rec.el = e;
      return rec;
    }

    apply(rec, c) {
      rec.c = c;
      const e = rec.el;
      place(e, c);
      e.hidden = !c.visible;
      e.title = c.tip || '';
      const style = c.type === 'uicontrol' ? c.style : c.type;
      if (c.type === 'uicontrol') {
        const box = c.units === 'normalized' ? null : c.pos[3] * (UNIT_PX[c.units] || [1, 1])[1];
        const s = e.style;
        s.fontSize = `${fontPx(c, box || e.getBoundingClientRect().height)}px`;
        s.fontFamily = family(c.fontName);
        s.fontWeight = c.fontWeight === 'bold' ? '600' : '400';
        s.fontStyle = c.fontAngle === 'italic' ? 'italic' : 'normal';
        s.color = color(c.fg, '#000');
        s.backgroundColor = ['slider', 'checkbox', 'radiobutton', 'text', 'frame', 'listbox', 'popupmenu', 'edit'].includes(style) ? color(c.bg, '') : '';
        if (style === 'pushbutton' || style === 'togglebutton') s.setProperty('--ui-bg', color(c.bg, '#f0f0f0'));
        e.style.textAlign = c.halign === 'left' ? 'left' : c.halign === 'right' ? 'right' : 'center';
        e.classList.toggle('is-off', c.enable === 'off');
        e.classList.toggle('is-inactive', c.enable === 'inactive');
      }
      const lines = c.string || [];
      switch (style) {
        case 'pushbutton':
        case 'togglebutton': {
          e.disabled = c.enable !== 'on';
          rec.text.textContent = lines[0] ?? '';
          const url = iconURL(c.cdata);
          rec.img.hidden = !url;
          if (url) { rec.img.src = url; rec.img.width = c.cdata.w; rec.img.height = c.cdata.h; }
          if (style === 'togglebutton') e.setAttribute('aria-pressed', String((c.value || [])[0] === c.max));
          break;
        }
        case 'checkbox':
        case 'radiobutton':
          rec.text.textContent = lines[0] ?? '';
          rec.input.checked = (c.value || [])[0] === c.max;
          rec.input.disabled = c.enable !== 'on';
          break;
        case 'edit': {
          const v = c.max - c.min > 1 ? lines.join('\n') : (lines[0] ?? '');
          // what the program set shows; what someone is typing stays
          if (document.activeElement !== rec.input || v !== rec.server) rec.input.value = v;
          rec.server = v;
          rec.input.disabled = c.enable === 'off';
          rec.input.readOnly = c.enable === 'inactive';
          rec.input.style.textAlign = e.style.textAlign;
          break;
        }
        case 'text': {
          rec.text.replaceChildren(...lines.map((l) => el('div', null, l || ' ')));
          const url = iconURL(c.cdata);
          rec.img.hidden = !url;
          if (url) { rec.img.src = url; rec.img.width = c.cdata.w; rec.img.height = c.cdata.h; }
          break;
        }
        case 'slider': {
          const i = rec.input;
          const span = c.max - c.min;
          i.min = String(c.min);
          i.max = String(c.max);
          i.step = span > 0 ? String((c.step && c.step[0] ? c.step[0] : 0.01) * span) : 'any';
          if (!rec.dragging) i.value = String((c.value || [])[0] ?? c.min);
          i.disabled = c.enable !== 'on';
          const [, , w, h] = c.pos;
          e.classList.toggle('is-vertical', h > w);
          break;
        }
        case 'listbox':
        case 'popupmenu': {
          const sel = rec.input;
          const key = JSON.stringify(lines);
          if (key !== rec.optKey) {
            rec.optKey = key;
            sel.replaceChildren(...lines.map((l, i) => el('option', { value: String(i) }, l)));
          }
          if (style === 'listbox') sel.size = Math.max(2, lines.length);
          const want = new Set((c.value || []).map((v) => Number(v) - 1));
          [...sel.options].forEach((o, i) => { o.selected = want.has(i); });
          if (style === 'popupmenu' && !want.size && sel.options.length) sel.selectedIndex = -1;
          sel.disabled = c.enable !== 'on';
          break;
        }
        case 'uipanel':
        case 'uibuttongroup': {
          rec.title.textContent = c.title || '';
          rec.title.hidden = !c.title;
          rec.title.style.color = color(c.fg, '#000');
          rec.title.style.background = color(c.bg, '#f0f0f0');      // the title cuts the border line
          e.style.fontSize = `${fontPx(c)}px`;
          e.style.fontFamily = family(c.fontName);
          rec.title.style.fontWeight = c.fontWeight === 'bold' ? '600' : '400';
          e.dataset.border = c.border;
          e.dataset.titlePos = c.titlePos || 'lefttop';
          e.classList.toggle('has-title', !!c.title);
          break;
        }
        case 'uitabgroup': {
          const key = JSON.stringify(c.tabs.map((t) => [t.id, t.title, t.tip]));
          if (key !== rec.stripKey) {
            rec.stripKey = key;
            rec.strip.replaceChildren(...c.tabs.map((t) => {
              const b = el('button', { type: 'button', role: 'tab', title: t.tip || null }, t.title);
              b.dataset.tab = String(t.id);
              b.addEventListener('click', () => {
                if (rec.selected === t.id) return;
                this.showTab(rec, t.id);
                this.ui({ type: 'control', id: rec.c.id, action: 'tab', tab: t.id });
              });
              return b;
            }));
          }
          for (const [id, t] of [...rec.tabs]) if (!c.tabs.some((x) => x.id === id)) { t.body.remove(); rec.tabs.delete(id); }
          for (const t of c.tabs) rec.tabBody(t.id);
          this.showTab(rec, c.selected);
          e.classList.toggle('is-bottom', c.location === 'bottom');
          break;
        }
        case 'uitable':
          this.table(rec, c);
          break;
        default:
          break;
      }
    }

    showTab(rec, id) {
      rec.selected = id;
      for (const b of rec.strip.children) b.setAttribute('aria-selected', String(Number(b.dataset.tab) === id));
      for (const [tid, t] of rec.tabs) t.body.hidden = tid !== id;
      // the canvas paints the shown tab (and draws its axes) again
      if (this.win.redrawSoon) this.win.redrawSoon();
    }

    table(rec, c) {
      if (rec.el.contains(document.activeElement) && document.activeElement.tagName === 'INPUT' && rec.key) return;
      const key = JSON.stringify([c.data, c.columnName, c.rowName, c.columnWidth, c.editable, c.bg, c.fg, c.striping, c.enable, c.fontSize]);
      if (key === rec.key) return;
      rec.key = key;
      const ncol = Math.max(0, ...c.data.map((r) => r.length), Array.isArray(c.columnName) ? c.columnName.length : 0);
      const colName = (j) => (c.columnName === 'numbered' ? String(j + 1) : (c.columnName[j] ?? ''));
      const rowName = (i) => (c.rowName === 'numbered' ? String(i + 1) : (c.rowName[i] ?? ''));
      const showRows = c.rowName === 'numbered' || (Array.isArray(c.rowName) && c.rowName.length);
      const showCols = c.columnName === 'numbered' || (Array.isArray(c.columnName) && c.columnName.length);
      const fmt = (v) => (typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(+v.toFixed(4))) : String(v ?? ''));
      const t = el('table');
      if (showCols) t.append(el('thead', null, el('tr', null, showRows ? el('th') : null, ...Array.from({ length: ncol }, (_, j) => el('th', { scope: 'col' }, colName(j))))));
      const body = el('tbody');
      c.data.forEach((row, i) => {
        const tr = el('tr');
        if (c.striping && c.bg.length > 1) tr.style.background = color(c.bg[i % c.bg.length]);
        else if (c.bg.length) tr.style.background = color(c.bg[0]);
        if (showRows) tr.append(el('th', { scope: 'row' }, rowName(i)));
        for (let j = 0; j < ncol; j++) {
          const v = row[j];
          const td = el('td');
          const editable = c.enable === 'on' && c.editable[j];
          if (typeof v === 'boolean') {
            const box = el('input', { type: 'checkbox', disabled: !editable });
            box.checked = v;
            box.addEventListener('change', () => this.ui({ type: 'control', id: c.id, action: 'edit', row: i + 1, col: j + 1, text: box.checked ? 'true' : 'false', checked: box.checked }));
            td.append(box);
            td.className = 'is-bool';
          } else if (editable) {
            const inp = el('input', { type: 'text', value: fmt(v), spellcheck: 'false', autocomplete: 'off' });
            let start = inp.value;
            const commit = () => { if (inp.value === start) return; start = inp.value; this.ui({ type: 'control', id: c.id, action: 'edit', row: i + 1, col: j + 1, text: inp.value }); };
            inp.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); commit(); } });
            inp.addEventListener('blur', commit);
            td.append(inp);
            td.className = typeof v === 'number' ? 'is-num' : '';
          } else {
            td.textContent = fmt(v);
            td.className = typeof v === 'number' ? 'is-num' : '';
          }
          if (c.select) td.addEventListener('click', () => this.ui({ type: 'control', id: c.id, action: 'select', cells: [[i + 1, j + 1]] }));
          tr.append(td);
        }
        body.append(tr);
      });
      t.append(body);
      t.style.color = color(c.fg, '#000');
      t.style.fontSize = `${fontPx(c)}px`;
      t.style.fontFamily = family(c.fontName);
      rec.el.replaceChildren(t);
    }

    /* Where the containers are on the canvas (in its pixels), for the axes
       in them and for their colour, which the canvas paints. */
    prepare(fig) {
      const fills = [];
      const boxes = new Map();
      const base = this.win.canvas.getBoundingClientRect();
      const rel = (r) => ({ x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height });
      for (const [id, rec] of this.ctl) {
        if (!rec.el.isConnected || !rec.el.offsetParent && rec.el.hidden) continue;
        const c = rec.c;
        if (c.type === 'uipanel' || c.type === 'uibuttongroup') {
          const r = rec.el.getBoundingClientRect();
          if (!r.width || !r.height) continue;
          fills.push(Object.assign(rel(r), { color: c.bg }));
          boxes.set(id, rel(rec.body.getBoundingClientRect()));
        } else if (c.type === 'uitabgroup') {
          for (const t of c.tabs) {
            const b = rec.tabs.get(t.id)?.body;
            if (!b || b.hidden) continue;
            const r = b.getBoundingClientRect();
            if (!r.width || !r.height) continue;
            fills.push(Object.assign(rel(r), { color: t.bg }));
            boxes.set(t.id, rel(r));
          }
        }
      }
      fig._fills = fills;
      for (const ax of fig.axes || []) {
        ax._box = ax.parent ? (boxes.get(ax.parent) || null) : null;
        ax._skip = !!ax.parent && !ax._box;
      }
    }

    focusControl(id) {
      const rec = this.ctl.get(id);
      if (!rec) return;
      (rec.input || rec.el).focus?.({ preventScroll: true });
    }

    /* The control a key event came from, if any. */
    controlOf(target) {
      const e = target && target.closest && target.closest('.pl-uictl');
      return e ? this.ctl.get(Number(e.dataset.id))?.c || null : null;
    }
  }

  /* ---- the dialogs a program asks the page for -------------------------------------------------- */
  const U = () => PL.util;

  /* '*.m;*.mat' as a test of a file's name. */
  function globTest(patterns) {
    const res = String(patterns || '*.*').split(';').map((p) => p.trim()).filter(Boolean)
      .map((p) => (p === '*.*' || p === '*' ? null : new RegExp(`^${p.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`, 'i')));
    if (res.some((r) => r === null)) return () => true;
    return (name) => res.some((r) => r.test(name));
  }

  /* uigetfile, uiputfile and uigetdir: the folders of the page's files. */
  async function pickFile(app, req) {
    let dir = req.start;
    let chosen = [];
    const save = req.mode === 'save';
    const dirOnly = req.mode === 'dir';
    const pathEl = el('div', { class: 'pl-pick-path pl-mono' });
    const list = el('div', { class: 'pl-pick-list', role: 'listbox', 'aria-multiselectable': req.multi ? 'true' : null });
    const nameIn = save ? el('input', { type: 'text', value: req.name || '', spellcheck: 'false', autocomplete: 'off' }) : null;
    const filterSel = !dirOnly && req.filters.length ? el('select', null, ...req.filters.map(([pat, desc], i) => el('option', { value: String(i) }, desc && desc !== pat ? desc : pat))) : null;
    let finish = null;
    const show = async (d) => {
      const res = await PL.engine.call('list_dir', d).catch(() => null);
      if (!res || res.error) return;
      dir = d;
      chosen = [];
      pathEl.textContent = d;
      const test = globTest(filterSel ? req.filters[Number(filterSel.value)][0] : '*.*');
      const rows = [];
      if (d !== '/') rows.push({ name: '..', dir: true, up: true });
      for (const it of res.items || []) if (it.dir || (!dirOnly && test(it.name))) rows.push(it);
      list.replaceChildren(...rows.map((it) => {
        const row = el('div', { class: `pl-pick-row${it.dir ? ' is-dir' : ''}`, role: 'option', tabindex: '-1' }, el('span', { class: 'ic', 'aria-hidden': 'true' }, it.dir ? '▸' : ''), el('span', null, it.name));
        const path = it.up ? d.replace(/\/[^/]*$/, '') || '/' : `${d.replace(/\/$/, '')}/${it.name}`;
        row.addEventListener('click', (ev) => {
          if (it.dir) return;
          if (req.multi && (ev.metaKey || ev.ctrlKey)) { row.classList.toggle('is-sel'); }
          else { for (const r of list.children) r.classList.toggle('is-sel', r === row); }
          chosen = [...list.querySelectorAll('.is-sel')].map((r) => r.lastChild.textContent);
          if (nameIn) nameIn.value = it.name;
        });
        row.addEventListener('dblclick', () => { if (it.dir) show(path); else if (finish) { chosen = [it.name]; if (nameIn) nameIn.value = it.name; finish(); } });
        return row;
      }));
    };
    if (filterSel) filterSel.addEventListener('change', () => show(dir));
    const body = [pathEl, list, nameIn ? el('label', null, 'File name', nameIn) : null, filterSel ? el('label', null, 'Files of type', filterSel) : null];
    const result = await U().dialog({
      title: req.title || (save ? 'Save as' : dirOnly ? 'Select a folder' : 'Open'),
      body,
      width: 520,
      buttons: [{ label: 'Cancel', value: null }, {
        label: save ? 'Save' : dirOnly ? 'Select folder' : 'Open',
        primary: true,
        value: () => {
          const filter = filterSel ? Number(filterSel.value) : 0;
          if (dirOnly) return { path: dir };
          if (save) {
            let name = nameIn.value.trim();
            if (!name) return null;
            const pat = req.filters[filter] ? req.filters[filter][0].split(';')[0].trim() : '';
            if (!/\.[^./]+$/.test(name) && /^\*\.[^*?]+$/.test(pat)) name += pat.slice(1);
            return { path: dir, names: [name], filter };
          }
          return chosen.length ? { path: dir, names: chosen, filter } : null;
        },
      }],
      onOpen: (b) => {
        b.closest('.pl-dialog').classList.add('is-picker');
        finish = () => b.closest('.pl-dialog').querySelector('.pl-dfoot .is-primary').click();
        show(dir);
      },
    });
    if (result && save) {
      const full = `${result.path.replace(/\/$/, '')}/${result.names[0]}`;
      const there = await PL.engine.fs('exists', { path: full }).catch(() => false);
      if (there && !(await U().confirm('Replace file', `${result.names[0]} is already in ${result.path}. Replace it?`, 'Replace'))) return null;
    }
    return result;
  }

  function hex(rgb) { return `#${rgb.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('')}`; }

  PL.asks = {
    questdlg: (app, req) => U().dialog({
      title: req.title || 'Question',
      body: el('div', { class: 'pl-ask' }, ...req.question.map((l) => el('p', null, l || ' '))),
      buttons: req.buttons.map((b) => ({ label: b, value: b, primary: b === req.default })),
    }).then((r) => r ?? ''),

    inputdlg: (app, req) => U().dialog({
      title: req.title || 'Input',
      body: req.prompts.map((p, i) => {
        const rows = req.rows[i] || 1;
        const input = rows > 1 ? el('textarea', { rows: String(rows), spellcheck: 'false' }) : el('input', { type: 'text', spellcheck: 'false', autocomplete: 'off' });
        input.value = req.defaults[i] || '';
        return el('label', null, p, input);
      }),
      buttons: [{ label: 'Cancel', value: null }, { label: 'OK', primary: true, value: (b) => [...b.querySelectorAll('input, textarea')].map((x) => x.value) }],
    }),

    listdlg: (app, req) => {
      const sel = el('select', { multiple: req.multiple, size: String(Math.min(14, Math.max(4, req.items.length))), class: 'pl-ask-list' },
        ...req.items.map((t, i) => el('option', { value: String(i) }, t)));
      for (const i of req.initial || []) if (sel.options[i]) sel.options[i].selected = true;
      const all = req.multiple ? el('button', { type: 'button', class: 'pl-btn' }, 'Select all') : null;
      if (all) all.addEventListener('click', () => { for (const o of sel.options) o.selected = true; });
      return U().dialog({
        title: req.title || 'Select',
        body: [...(req.prompt || []).map((l) => el('p', { class: 'pl-ask' }, l)), sel, all],
        buttons: [{ label: req.cancel || 'Cancel', value: null }, { label: req.ok || 'OK', primary: true, value: () => [...sel.selectedOptions].map((o) => Number(o.value)) }],
        onOpen: (b) => sel.addEventListener('dblclick', () => { if (!req.multiple) b.closest('.pl-dialog').querySelector('.pl-dfoot .is-primary').click(); }),
      });
    },

    pickfile: pickFile,

    color: (app, req) => {
      const inp = el('input', { type: 'color', value: hex(req.value || [1, 1, 1]), class: 'pl-ask-color' });
      return U().dialog({
        title: req.title || 'Color',
        body: el('label', null, 'Colour', inp),
        buttons: [{ label: 'Cancel', value: null }, { label: 'OK', primary: true, value: () => [1, 3, 5].map((k) => parseInt(inp.value.slice(k, k + 2), 16) / 255) }],
      });
    },

    menu: (app, req) => U().dialog({
      title: req.title || 'Menu',
      body: el('div'),
      buttons: [...req.items.map((t, i) => ({ label: t, value: i, primary: i === 0 })), { label: 'Cancel', value: null }],
      onOpen: (b) => b.closest('.pl-dialog').classList.add('is-menu'),
    }).then((r) => (r === null ? -1 : r)),

    /* printdlg and printpreview: the figure as a picture, to the browser's printing. */
    print: (app, req) => {
      const w = app.figures.wins.get(req.figure);
      if (!w) return false;
      const url = w.renderTo(2);
      const f = el('iframe', { title: 'Print', style: { position: 'fixed', right: '0', bottom: '0', width: '0', height: '0', border: '0' } });
      document.body.append(f);
      const doc = f.contentDocument;
      doc.open();
      doc.write('<!doctype html><title>Figure</title><style>@page{margin:12mm}html,body{margin:0}img{max-width:100%}</style><img alt="">');
      doc.close();
      const img = doc.querySelector('img');
      img.onload = () => { try { f.contentWindow.print(); } catch (e) { /* none here */ } setTimeout(() => f.remove(), 60000); };
      img.src = url;
      return true;
    },

    /* print -dmeta or -dbitmap with no file: the figure to the clipboard. */
    copyfig: async (app, req) => {
      const w = app.figures.wins.get(req.figure);
      if (!w || !navigator.clipboard || !window.ClipboardItem) return false;
      const blob = await (await fetch(w.renderTo(2))).blob();
      try { await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]); return true; } catch (e) { return false; }
    },
  };

  PL.FigureUI = FigureUI;
  PL.uiKeys = keyInfo;
  PL.uiMods = modsOf;
  PL.uiMenus = menus;
  PL.uiUnits = UNIT_PX;
})(window);
