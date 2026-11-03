/* ==========================================================================
   PYLAB.HTML: THE FIGURE'S PROPERTY EDITOR

   A window beside a figure: the figure's objects as a tree (axes with
   their title and labels, what is plotted, legend, colorbar, annotations,
   a program's controls) and the picked object's properties in groups,
   each with a field that suits it (a colour, on/off, a list of choices,
   numbers, text). A change goes to the engine (worker_api.inspect_change,
   which sets it as set(h, name, value) does) and the figure is redrawn.

   Opened by the figure toolbar's edit tool (pylab-figure.js picks what a
   click is on), and by inspect(h) and plotedit in a program.
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, icon } = PL.util;

  // the friendlier names of some choices
  const NAMES = {
    LineStyle: { '-': 'solid  -', '--': 'dashed  --', ':': 'dotted  :', '-.': 'dash-dot  -.', none: 'none' },
    Marker: {
      none: 'none', o: 'circle  o', '+': 'plus  +', '*': 'asterisk  *', '.': 'point  .', x: 'cross  x', s: 'square  s', d: 'diamond  d',
      '^': 'triangle up  ^', v: 'triangle down  v', '>': 'triangle right  >', '<': 'triangle left  <', p: 'pentagram  p', h: 'hexagram  h',
      _: 'horizontal line  _', '|': 'vertical line  |',
    },
  };
  NAMES.GridLineStyle = NAMES.LineStyle;
  NAMES.MinorGridLineStyle = NAMES.LineStyle;
  const COLORS = ['none', 'red', 'green', 'blue', 'cyan', 'magenta', 'yellow', 'black', 'white', 'auto', 'flat', 'interp'];
  const OPEN = new Set(['Common', 'Labels']);       // groups open until a person closes them

  const hex = (c) => '#' + c.map((v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0')).join('');
  const unhex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const rgbText = (c) => `[${c.map((v) => String(+v.toFixed(4))).join(' ')}]`;
  let uid = 0;

  class FigureInspector {
    constructor(mgr) {
      this.mgr = mgr;
      this.win = null;           // the FigureWindow it edits
      this.id = null;            // the object shown
      this.data = null;
      this.shape = '';           // the properties' names, to know when the fields must be made anew
      this.open = PL.util.store.get('inspgroups', null) || [...OPEN];
      this.title = el('span', { class: 't' }, 'Property Editor');
      const close = el('button', { class: 'pl-iconbtn', type: 'button', title: 'Close the property editor', 'aria-label': 'Close the property editor' }, icon('close'));
      close.addEventListener('click', () => this.close());
      this.titlebar = el('div', { class: 'pl-figtitle' }, icon('inspector', 'pl-ficon'), this.title, close);
      this.tree = el('div', { class: 'pl-insp-tree', role: 'listbox', 'aria-label': 'The figure\u2019s objects', tabindex: '-1' });
      this.find = el('input', { type: 'search', class: 'pl-insp-find', placeholder: 'Find a property', 'aria-label': 'Find a property', spellcheck: 'false' });
      this.find.addEventListener('input', () => this.filter());
      this.head = el('div', { class: 'pl-insp-head' });
      this.msg = el('div', { class: 'pl-insp-msg', role: 'alert', hidden: '' });
      this.props = el('div', { class: 'pl-insp-props' });
      this.grip = el('div', { class: 'pl-figgrip', title: 'Drag to resize' });
      this.el = el('div', { class: 'pl-figwin pl-inspector', role: 'dialog', 'aria-label': 'Property Editor', hidden: '' },
        this.titlebar, this.tree, this.head, this.find, this.msg, this.props, this.grip);
      this.el.addEventListener('pointerdown', () => this.raise(), true);
      this.el.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && ev.target === this.el) this.close(); });
      this.tree.addEventListener('keydown', (ev) => this.treeKeys(ev));
      mgr.layer.append(this.el);
      this._drag();
      this._resize();
    }

    isOpen(win) { return !this.el.hidden && (!win || this.win === win); }

    raise() { this.el.style.zIndex = String(++this.mgr.z); }

    /* Show object id of the figure in window win. */
    async show(win, id) {
      const first = this.el.hidden || this.win !== win;
      if (this.win && this.win !== win) { const old = this.win; this.win = win; old.redraw(); }
      this.win = win;
      if (first) {
        this.el.hidden = false;
        this.place();
      }
      this.raise();
      await this.load(id);
    }

    close() {
      if (this.el.hidden) return;
      this.el.hidden = true;
      const w = this.win;
      this.win = null;
      this.id = null;
      this.data = null;
      this.shape = '';
      if (w) {
        if (w.tool === 'edit') w.setTool('edit');
        w.redraw();
      }
    }

    /* Beside its figure, on the side with room (or over the figure's right edge). */
    place() {
      const L = this.mgr.layer.getBoundingClientRect();
      const f = this.win.el;
      const W = Math.min(320, Math.max(240, L.width - 16)), H = Math.min(560, Math.max(240, L.height - 16));
      this.el.style.width = `${W}px`;
      this.el.style.height = `${H}px`;
      let l = f.offsetLeft + f.offsetWidth + 8;
      if (f.classList.contains('is-docked') || l + W > L.width) l = f.offsetLeft - W - 8;
      if (l < 0) l = Math.max(0, L.width - W - 4);
      const t = Math.max(0, Math.min(f.classList.contains('is-docked') ? 8 : f.offsetTop, L.height - H - 4));
      this.el.style.left = `${l}px`;
      this.el.style.top = `${t}px`;
    }

    async call(fn, ...args) {
      if (!PL.engine || PL.engine.state !== 'ready') return null;
      try {
        const r = await PL.engine.call(fn, ...args);
        return typeof r === 'string' ? JSON.parse(r) : r;
      } catch (e) { return null; }
    }

    async load(id) {
      const seq = this.seq = (this.seq || 0) + 1;
      const d = await this.call('inspect_object', id);
      if (seq !== this.seq || this.el.hidden) return;
      if (!d || !d.ok) {
        // gone (deleted by the program): the figure instead, while it is there
        if (this.win && this.win.fig && id !== this.win.fig.id && this.mgr.wins.has(this.win.id)) { this.load(this.win.fig.id); return; }
        this.close();
        return;
      }
      this.render(d);
    }

    /* The figure changed (the program drew, or a change here): the values shown again. */
    figureChanged(figId) {
      if (this.el.hidden || !this.win || this.win.id !== figId || this.id == null) return;
      clearTimeout(this._again);
      this._again = setTimeout(() => this.load(this.id), 120);
    }

    figureClosed(figId) { if (this.win && this.win.id === figId) this.close(); }

    render(d) {
      const fresh = d.id !== this.id;
      this.data = d;
      this.id = d.id;
      this.win.selection = d.id;
      this.title.textContent = `Property Editor \u2014 ${d.figureLabel}`;
      this.renderTree(d.tree, d.id);
      this.head.textContent = d.label;
      const shape = d.id + ':' + d.groups.map((g) => g.name + '=' + g.props.map((p) => p.name + '/' + p.kind + '/' + (p.options || []).join(',')).join(',')).join(';');
      if (shape !== this.shape) {
        this.shape = shape;
        this.build(d);
        if (fresh) this.props.scrollTop = 0;
      } else this.refill(d);
      this.showError(d.error ? `${d.errorProp}: ${d.error}` : '');
      this.win.redraw();
    }

    renderTree(rows, id) {
      const key = rows.map((r) => `${r.id}:${r.depth}:${r.label}`).join('|');
      if (key !== this.treeKey) {
        this.treeKey = key;
        this.tree.replaceChildren(...rows.map((r) => {
          const b = el('div', { class: 'pl-insp-node', role: 'option', tabindex: '-1', 'data-id': String(r.id), title: r.label }, r.label);
          b.style.paddingLeft = `${6 + r.depth * 14}px`;
          b.addEventListener('click', () => this.load(r.id));
          return b;
        }));
      }
      let sel = null;
      for (const b of this.tree.children) {
        const on = Number(b.dataset.id) === id;
        b.setAttribute('aria-selected', String(on));
        b.tabIndex = on ? 0 : -1;
        if (on) sel = b;
      }
      if (sel) {
        const t = sel.offsetTop - this.tree.offsetTop, h = this.tree.clientHeight;
        if (t < this.tree.scrollTop || t + sel.offsetHeight > this.tree.scrollTop + h) this.tree.scrollTop = Math.max(0, t - h / 3);
      }
    }

    treeKeys(ev) {
      const rows = [...this.tree.children];
      const i = rows.findIndex((b) => b.getAttribute('aria-selected') === 'true');
      const go = ev.key === 'ArrowDown' ? i + 1 : ev.key === 'ArrowUp' ? i - 1 : ev.key === 'Home' ? 0 : ev.key === 'End' ? rows.length - 1 : null;
      if (go === null || !rows.length) return;
      ev.preventDefault();
      const b = rows[Math.max(0, Math.min(rows.length - 1, go))];
      b.focus();
      this.load(Number(b.dataset.id));
    }

    build(d) {
      this.fields = new Map();
      const groups = d.groups.map((g) => {
        const open = this.open.includes(g.name);
        const head = el('button', { type: 'button', class: 'pl-insp-ghead', 'aria-expanded': String(open) }, g.name);
        const body = el('div', { class: 'pl-insp-gbody' }, ...g.props.map((p) => this.row(p)));
        body.hidden = !open;
        head.addEventListener('click', () => {
          const now = body.hidden;
          body.hidden = !now;
          head.setAttribute('aria-expanded', String(now));
          this.open = this.open.filter((n) => n !== g.name);
          if (now) this.open.push(g.name);
          PL.util.store.set('inspgroups', this.open);
        });
        return el('section', { class: 'pl-insp-group', 'data-group': g.name }, head, body);
      });
      this.props.replaceChildren(...groups);
      this.filter();
    }

    /* One property: its name and the field that edits it. */
    row(p) {
      const id = `pl-insp-${++uid}`;
      const name = el('label', { for: id, title: p.name }, p.name);
      const r = el('div', { class: 'pl-insp-row', 'data-name': p.name }, name);
      const send = (payload) => this.change(p.name, Object.assign({ kind: p.kind }, payload));
      const f = { p, r };
      const text = (multi) => {
        const t = multi ? el('textarea', { id, rows: '1', spellcheck: 'false', title: 'Enter applies it; Shift+Enter starts a new line' })
          : el('input', { id, type: 'text', spellcheck: 'false', autocomplete: 'off' });
        t.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' && !(multi && ev.shiftKey)) { ev.preventDefault(); t.blur(); }
          if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); f.set(f.p); t.blur(); }
        });
        return t;
      };
      switch (p.kind) {
        case 'onoff': {
          const c = el('input', { id, type: 'checkbox' });
          c.addEventListener('change', () => send({ value: c.checked }));
          f.set = (q) => { c.checked = !!q.value; };
          f.input = c;
          r.append(el('div', { class: 'v' }, c));
          break;
        }
        case 'enum':
        case 'colormap': {
          const s = el('select', { id });
          f.set = (q) => {
            const names = NAMES[q.name] || {};
            const opts = q.kind === 'colormap' ? [`custom (${q.value.replace(/^\[|\]$/g, '')})`].concat(q.options) : q.options;
            s.replaceChildren(...opts.map((o, i) => el('option', { value: q.kind === 'colormap' && i === 0 ? '' : o }, names[o] || o)));
            s.value = q.kind === 'colormap' ? (q.current || '') : q.value;
          };
          s.addEventListener('change', () => { if (s.value) send({ value: s.value, rows: f.p.rows }); });
          f.input = s;
          r.append(el('div', { class: 'v' }, s));
          break;
        }
        case 'color': {
          const sw = el('input', { type: 'color', 'aria-label': `${p.name}: pick a colour` });
          const t = text(false);
          const list = el('datalist', { id: `${id}-list` });
          t.setAttribute('list', list.id);
          f.set = (q) => {
            const rgb = Array.isArray(q.value);
            sw.value = rgb ? hex(q.value) : '#ffffff';
            sw.classList.toggle('is-word', !rgb);
            t.value = rgb ? rgbText(q.value) : q.value;
            list.replaceChildren(...[...new Set(q.options.concat(COLORS.filter((c) => !['auto', 'flat', 'interp'].includes(c) || q.options.includes(c))))].map((o) => el('option', { value: o })));
          };
          sw.addEventListener('change', () => send({ value: unhex(sw.value) }));
          t.addEventListener('change', () => send({ value: t.value }));
          f.input = t;
          r.append(el('div', { class: 'v pl-insp-color' }, sw, t, list));
          break;
        }
        case 'lines': {
          const t = text(true);
          f.set = (q) => { t.value = (q.value || []).join('\n'); t.rows = Math.min(6, Math.max(1, (q.value || []).length)); };
          t.addEventListener('input', () => { t.rows = Math.min(6, Math.max(1, t.value.split('\n').length)); });
          t.addEventListener('change', () => send({ value: t.value.split('\n') }));
          f.input = t;
          r.append(el('div', { class: 'v' }, t));
          break;
        }
        case 'link': {
          const b = el('button', { type: 'button', class: 'pl-insp-link', id });
          f.set = (q) => { b.textContent = q.value; b.disabled = q.link == null; };
          b.addEventListener('click', () => { if (f.p.link != null) this.load(f.p.link); });
          r.append(el('div', { class: 'v' }, b));
          break;
        }
        case 'readonly': {
          const s = el('output', { class: 'pl-insp-ro', id });
          f.set = (q) => { s.textContent = q.note ? `${q.value} \u2014 ${q.note}` : q.value; s.title = s.textContent; };
          r.append(el('div', { class: 'v' }, s));
          break;
        }
        default: {           // text, number, array, callback
          const t = text(false);
          if (p.kind === 'number') t.inputMode = 'decimal';
          if (p.kind === 'callback') t.title = 'Code to run, or a function handle such as @myfunction or @(src, event) disp(1)';
          f.set = (q) => { t.value = q.value; };
          t.addEventListener('change', () => send({ value: t.value }));
          f.input = t;
          r.append(el('div', { class: 'v' }, t));
        }
      }
      f.set(p);
      this.fields.set(p.name, f);
      return r;
    }

    /* The same properties: new values into the fields, except the one being typed in. */
    refill(d) {
      for (const g of d.groups) {
        for (const p of g.props) {
          const f = this.fields.get(p.name);
          if (!f) continue;
          f.p = p;
          // never under the cursor of someone typing
          const a = document.activeElement;
          if (f.r.contains(a) && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && a.type === 'text'))) continue;
          f.set(p);
          f.r.classList.remove('is-error');
        }
      }
    }

    async change(name, payload) {
      if (this.id == null) return;
      const seq = this.seq = (this.seq || 0) + 1;
      const d = await this.call('inspect_change', this.id, name, JSON.stringify(payload));
      // another object picked meanwhile: that one is shown
      if (!d || seq !== this.seq || this.el.hidden) return;
      if (!d.ok) { this.load(this.win ? this.win.fig.id : this.id); return; }
      // the field just left takes the value set (or back its old one)
      const f = this.fields.get(name);
      this.render(d);
      if (f && d.error) {
        f.r.classList.add('is-error');
        const p = d.groups.flatMap((g) => g.props).find((q) => q.name === name);
        if (p && document.activeElement !== f.input) f.set(p);
      }
    }

    showError(text) {
      this.msg.textContent = text;
      this.msg.hidden = !text;
    }

    filter() {
      const q = this.find.value.trim().toLowerCase();
      for (const sec of this.props.children) {
        let any = false;
        for (const r of sec.querySelectorAll('.pl-insp-row')) {
          const on = !q || r.dataset.name.toLowerCase().includes(q);
          r.hidden = !on;
          any = any || on;
        }
        sec.hidden = !any;
        // a search shows what it finds in closed groups too
        const body = sec.querySelector('.pl-insp-gbody');
        if (q) body.hidden = false;
        else body.hidden = !this.open.includes(sec.dataset.group);
        sec.querySelector('.pl-insp-ghead').setAttribute('aria-expanded', String(!body.hidden));
      }
    }

    _drag() {
      let d = null;
      this.titlebar.addEventListener('pointerdown', (ev) => {
        if (ev.target.closest('button')) return;
        d = { x: ev.clientX, y: ev.clientY, l: this.el.offsetLeft, t: this.el.offsetTop };
        this.titlebar.setPointerCapture(ev.pointerId);
      });
      this.titlebar.addEventListener('pointermove', (ev) => {
        if (!d) return;
        const layer = this.mgr.layer;
        this.el.style.left = `${Math.max(-this.el.offsetWidth + 60, Math.min(layer.clientWidth - 60, d.l + ev.clientX - d.x))}px`;
        this.el.style.top = `${Math.max(0, Math.min(layer.clientHeight - 26, d.t + ev.clientY - d.y))}px`;
      });
      const up = () => { d = null; };
      this.titlebar.addEventListener('pointerup', up);
      this.titlebar.addEventListener('pointercancel', up);
    }

    _resize() {
      let d = null;
      this.grip.addEventListener('pointerdown', (ev) => {
        ev.preventDefault();
        d = { x: ev.clientX, y: ev.clientY, w: this.el.offsetWidth, h: this.el.offsetHeight };
        this.grip.setPointerCapture(ev.pointerId);
      });
      this.grip.addEventListener('pointermove', (ev) => {
        if (!d) return;
        this.el.style.width = `${Math.max(220, d.w + ev.clientX - d.x)}px`;
        this.el.style.height = `${Math.max(200, d.h + ev.clientY - d.y)}px`;
      });
      const up = () => { d = null; };
      this.grip.addEventListener('pointerup', up);
      this.grip.addEventListener('pointercancel', up);
    }
  }

  PL.FigureInspector = FigureInspector;
})(window);
