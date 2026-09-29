/* ==========================================================================
   SMUI.HTML: THE WORK AREA'S TAB GROUPS

   The work area is a tree of splits whose leaves are groups, as VS Code's
   editor groups are: each group has its own tab strip and shows one of its
   tabs, and the group last clicked or typed in is the one in use (its table
   is the current one, and new tabs open in it). A tab dragged by its title
   goes

       onto a tab strip          into that group, where it is let go (a
                                 drag along its own strip orders the tabs)
       onto a group's middle     into that group
       onto a group's edge       into a new group on that side (left,
                                 right, above or below), splitting it

   and a bar or a translucent box shows where. A group left without tabs
   goes, and a split left with one part becomes that part. The bars between
   the parts resize them: dragged, with the arrow keys, or a double click to
   make the two sides equal. A tab's context menu has Split, Move to Group
   and Join All Groups. At phone width the groups stack, one above the other;
   a tab moves between them there but makes no new ones.

   The app keeps its tabs ({ btn, view, title, ... }), and Dock places them:
   add, show, remove, move, split, join. A saved project keeps the layout
   (layout() and arrange()). A touch held on a tab lifts it (smui-touchdrag.js
   drives the same drag events), so tabs move by touch too.

   Chrome forgets where a box was scrolled to when the box moves in the page,
   and a hidden one's cannot be read, so a view's scroll positions are kept
   when it is hidden or about to move, and put back when it is shown again.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el } = SM.util;

  const MIME = 'application/x-smui-tab';
  const EDGE = 0.26;            // the part of a group's width or height, at an edge, that splits it
  const MIN = 150;              // the smallest a bar makes a part (px)
  const phone = () => typeof matchMedia === 'function' && matchMedia('(max-width: 760px)').matches;
  const hasTab = (ev) => !!(ev.dataTransfer && [...ev.dataTransfer.types].includes(MIME));
  const inside = (e, ev) => { const r = e.getBoundingClientRect(); return ev.clientX > r.left && ev.clientX < r.right && ev.clientY > r.top && ev.clientY < r.bottom; };
  const unmark = (strip) => strip.querySelectorAll('.drop-before, .drop-after').forEach((b) => b.classList.remove('drop-before', 'drop-after'));

  // where a view and the boxes in it are scrolled to (graphs' insides aside)
  function saveScroll(v) {
    const out = [];
    for (const e of [v, ...v.querySelectorAll(':not(svg, svg *)')]) if (e.scrollTop || e.scrollLeft) out.push([e, e.scrollTop, e.scrollLeft]);
    v._scroll = out;
  }
  function putScroll(v) {
    for (const [e, top, left] of v._scroll || []) if (v.contains(e)) { e.scrollTop = top; e.scrollLeft = left; }
  }

  class Group {
    constructor(dock) {
      this.dock = dock;
      this.id = SM.util.uid('grp');
      this.tabs = [];
      this.active = null;          // the tab it shows
      this.parent = null;
      this.strip = el('div', { class: 'sm-tabs', role: 'tablist', 'aria-label': 'Tables and reports' });
      this.overlay = el('div', { class: 'sm-dropzone', hidden: true, 'aria-hidden': 'true' });
      this.views = el('div', { class: 'sm-views' }, this.overlay);
      this.el = el('div', { class: 'sm-group', dataset: { group: this.id } }, this.strip, this.views);
      this.el._group = this;
      // a click or focus anywhere in a group makes it the one in use
      this.el.addEventListener('pointerdown', () => dock.focus(this), true);
      this.el.addEventListener('focusin', () => dock.focus(this));
    }
  }

  const firstGroup = (n) => (n instanceof Group ? n : firstGroup(n.children[0]));

  class Split {
    constructor(dock, dir) {
      this.dock = dock;
      this.dir = dir;               // 'row': side by side; 'col': one above the other
      this.children = [];
      this.sizes = [];              // the parts' shares of the room, summing to 1
      this.parent = null;
      this.el = el('div', { class: `sm-split is-${dir}` });
    }

    // The parts in order with a bar between each two; a part already in its
    // place is not moved (a move loses scroll positions).
    render() {
      const sum = this.sizes.reduce((a, b) => a + b, 0) || 1;
      this.sizes = this.sizes.map((s) => s / sum);
      // the bars, and parts that have left, go first: the others keep their places
      const parts = new Set(this.children.map((c) => c.el));
      for (const e of [...this.el.children]) if (!parts.has(e)) e.remove();
      let prev = null;
      this.children.forEach((c, i) => {
        c.el.style.flex = `${this.sizes[i]} 1 0`;
        const at = prev ? prev.nextSibling : this.el.firstChild;
        if (c.el !== at) this.el.insertBefore(c.el, at);
        prev = c.el;
      });
      this.children.forEach((c, i) => { if (i) this.el.insertBefore(this.dock._sash(this, i), c.el); });
    }
  }

  class Dock {
    constructor(app, host) {
      this.app = app;
      this.host = host;
      // views kept in the page without a group (the Help text, its tab closed)
      this.shelf = el('div', { class: 'sm-shelf', hidden: true });
      const g = this._group();
      this.root = g;
      this.active = g;
      g.el.classList.add('is-focused');
      host.append(g.el, this.shelf);
      this.dragging = null;
      document.addEventListener('dragend', () => this._clear());
      document.addEventListener('drop', () => this._clear());
      // a tab let go over a text field does not type its name there
      document.addEventListener('drop', (ev) => { if (hasTab(ev)) ev.preventDefault(); }, true);
    }

    get groups() {
      const out = [];
      const walk = (n) => { if (n instanceof Group) out.push(n); else n.children.forEach(walk); };
      walk(this.root);
      return out;
    }

    _group() {
      const g = new Group(this);
      this._wire(g);
      return g;
    }

    // "Tables and reports", then "…, group 2" and so on, in the order they sit
    _label() {
      this.groups.forEach((g, i) => g.strip.setAttribute('aria-label', i ? `Tables and reports, group ${i + 1}` : 'Tables and reports'));
    }

    // The group in use (a click or focus in it): the app follows its tab.
    focus(g) {
      if (!g || this.active === g) return;
      if (this.active) this.active.el.classList.remove('is-focused');
      this.active = g;
      g.el.classList.add('is-focused');
      if (g.active) this.app._activate(g.active);
    }

    /* A view kept in the page but in no group. */
    park(view) {
      view.hidden = true;
      this.shelf.append(view);
    }

    /* A tab into a group (the one in use), at a place in its strip (the end). */
    add(tab, { group = this.active, at = null } = {}) {
      const g = group;
      const i = at == null ? g.tabs.length : Math.max(0, Math.min(at, g.tabs.length));
      tab.group = g;
      g.tabs.splice(i, 0, tab);
      g.strip.insertBefore(tab.btn, g.tabs[i + 1] ? g.tabs[i + 1].btn : null);
      g.views.insertBefore(tab.view, g.overlay);
      tab.view._moved = true;
      tab.btn.draggable = true;
      this._wireTab(tab);
    }

    /* The tab shown in its group; focus: that group becomes the one in use
       (the app's showTab, which draws the view; here it is drawn when the
       view comes into view in a group not in use). */
    show(tab, { focus = true } = {}) {
      const g = tab.group;
      if (!g) return;
      const was = tab.view.hidden;
      g.active = tab;
      for (const t of g.tabs) {
        const on = t === tab;
        if (!on && !t.view.hidden && !this._keeping) saveScroll(t.view);
        t.btn.classList.toggle('is-active', on);
        t.btn.setAttribute('aria-selected', String(on));
        t.btn.tabIndex = on ? 0 : -1;
        t.view.hidden = !on;
      }
      if (tab.view._moved) { tab.view._moved = false; putScroll(tab.view); }
      if (focus && this.active !== g) {
        if (this.active) this.active.el.classList.remove('is-focused');
        this.active = g;
        g.el.classList.add('is-focused');
      }
      if (!focus && was) this.app._shown(tab);
    }

    /* A tab out of its group (closed); an empty group goes. */
    remove(tab) {
      const g = tab.group;
      if (!g) return;
      const i = g.tabs.indexOf(tab);
      if (i >= 0) g.tabs.splice(i, 1);
      if (g.active === tab) g.active = null;
      tab.group = null;
      if (!g.tabs.length) this._keepScroll(() => this._drop(g));
    }

    /* A tab to a group, at an index of its strip (the end), and shown
       there; within its own group this orders the strip. The group it
       leaves shows its next tab, or goes. */
    move(tab, g, at = null) {
      if (!tab.group || !g) return;
      this._keepScroll(() => this._move(tab, g, at));
    }

    _move(tab, g, at) {
      const from = tab.group;
      const i = from.tabs.indexOf(tab);
      let j = at == null ? g.tabs.length : at;
      if (from === g) {
        if (j > i) j--;
        if (j === i) return;
        g.tabs.splice(i, 1);
        g.tabs.splice(j, 0, tab);
        g.strip.insertBefore(tab.btn, g.tabs[j + 1] ? g.tabs[j + 1].btn : null);
        return;
      }
      from.tabs.splice(i, 1);
      if (from.active === tab) from.active = null;
      tab.group = g;
      j = Math.max(0, Math.min(j, g.tabs.length));
      g.tabs.splice(j, 0, tab);
      g.strip.insertBefore(tab.btn, g.tabs[j + 1] ? g.tabs[j + 1].btn : null);
      g.views.insertBefore(tab.view, g.overlay);
      this.show(tab, { focus: false });
      if (!from.tabs.length) this._drop(from);
      else if (!from.active) this.show(from.tabs[Math.min(i, from.tabs.length - 1)], { focus: false });
    }

    /* A new group beside `target` (side: left, right, top or bottom), with
       the tab in it and shown. Not at phone width, nor for the only tab of
       the group it would split. */
    split(tab, target, side) {
      if (phone() || !target || !tab.group) return false;
      if (tab.group === target && target.tabs.length === 1) return false;
      const dir = side === 'left' || side === 'right' ? 'row' : 'col';
      const before = side === 'left' || side === 'top';
      this._keepScroll(() => {
        const g = this._group();
        const p = target.parent;
        if (p && p.dir === dir) {
          const k = p.children.indexOf(target);
          const half = p.sizes[k] / 2;
          p.sizes[k] = half;
          const at = before ? k : k + 1;
          p.children.splice(at, 0, g);
          p.sizes.splice(at, 0, half);
          g.parent = p;
          p.render();
        } else {
          const s = new Split(this, dir);
          this._replace(target, s);
          s.children = before ? [g, target] : [target, g];
          s.sizes = [0.5, 0.5];
          g.parent = s;
          target.parent = s;
          s.render();
        }
        this._move(tab, g, 0);
      });
      this._label();
      this.app.showTab(tab);
      return true;
    }

    /* Every tab into the first group, the others gone. */
    join() {
      const [first, ...rest] = this.groups;
      if (!rest.length) return;
      const keep = this.app.activeTab;
      this._keepScroll(() => { for (const g of rest) for (const t of g.tabs.slice()) this._move(t, first); });
      this._label();
      if (keep) this.app.showTab(keep);
    }

    // node's place in the tree (or the root) given to other
    _replace(node, other) {
      const p = node.parent;
      if (!p) {
        this.root = other;
        other.parent = null;
        other.el.style.flex = '';
        node.el.replaceWith(other.el);
      } else {
        const k = p.children.indexOf(node);
        p.children[k] = other;
        other.parent = p;
        p.render();
      }
    }

    // An empty group goes (not the last one); its room goes to the parts
    // beside it, and the group next to it is in use if it was.
    _drop(g) {
      if (this.groups.length === 1) return;
      const p = g.parent;
      const k = p.children.indexOf(g);
      p.children.splice(k, 1);
      const share = p.sizes.splice(k, 1)[0];
      p.sizes = p.sizes.map((s) => s + share / p.sizes.length);
      const near = p.children[Math.min(k, p.children.length - 1)];
      g.el.remove();
      if (p.children.length === 1) {
        const only = p.children[0];
        this._replace(p, only);
        // a split in a split of the same way becomes one split
        if (only instanceof Split && only.parent && only.parent.dir === only.dir) {
          const pp = only.parent;
          const at = pp.children.indexOf(only);
          const w = pp.sizes[at];
          pp.children.splice(at, 1, ...only.children);
          pp.sizes.splice(at, 1, ...only.sizes.map((s) => s * w));
          only.children.forEach((c) => { c.parent = pp; });
          pp.render();
        }
      } else p.render();
      if (this.active === g) {
        this.active = null;
        this.focus(firstGroup(near));
      }
      this._label();
    }

    // A change of layout moves views in the page: those shown after it are
    // put back where they were scrolled to (as they were shown, or as they
    // were when last hidden: a hidden view does not scroll), the others when
    // they are next shown.
    _keepScroll(fn) {
      for (const g of this.groups) for (const t of g.tabs) if (!t.view.hidden) saveScroll(t.view);
      // (a view moved and then hidden within the change keeps the place saved here)
      this._keeping = (this._keeping || 0) + 1;
      try { fn(); } finally { this._keeping--; }
      for (const g of this.groups) {
        for (const t of g.tabs) {
          if (t.view.hidden) t.view._moved = true;
          else { t.view._moved = false; putScroll(t.view); }
        }
      }
    }

    /* The bar between parts i - 1 and i of a split. At phone width every
       split is a column, so the bar reads its way from the page. */
    _sash(split, i) {
      const s = el('div', { class: `sm-sash is-${split.dir}`, role: 'separator', tabindex: '0', 'aria-orientation': split.dir === 'row' ? 'vertical' : 'horizontal', 'aria-label': 'Resize the groups (a double click makes them equal)' });
      const across = () => getComputedStyle(split.el).flexDirection.startsWith('row');
      const px = (n, row) => { const r = n.el.getBoundingClientRect(); return row ? r.width : r.height; };
      const set = (wa, wb) => {
        split.sizes[i - 1] = wa;
        split.sizes[i] = wb;
        split.children[i - 1].el.style.flex = `${wa} 1 0`;
        split.children[i].el.style.flex = `${wb} 1 0`;
      };
      // part i - 1 made d px bigger (part i smaller), neither below MIN
      const resize = (row, pa, pb, d) => {
        const w = split.sizes[i - 1] + split.sizes[i], room = pa + pb;
        if (room <= 0) return;
        const na = Math.max(Math.min(MIN, room / 2), Math.min(room - Math.min(MIN, room / 2), pa + d));
        set((w * na) / room, w - (w * na) / room);
      };
      s.addEventListener('pointerdown', (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        const row = across();
        const a = split.children[i - 1], b = split.children[i];
        const pa = px(a, row), pb = px(b, row), w0 = [split.sizes[i - 1], split.sizes[i]];
        const start = row ? ev.clientX : ev.clientY;
        s.classList.add('is-moving');
        this.host.classList.add('is-resizing', row ? 'is-row' : 'is-col');
        try { s.setPointerCapture(ev.pointerId); } catch (e) { /* a synthetic event has no pointer to capture */ }
        const moveTo = (e) => {
          split.sizes[i - 1] = w0[0];
          split.sizes[i] = w0[1];
          resize(row, pa, pb, (row ? e.clientX : e.clientY) - start);
        };
        const up = () => {
          s.classList.remove('is-moving');
          this.host.classList.remove('is-resizing', 'is-row', 'is-col');
          s.removeEventListener('pointermove', moveTo);
          s.removeEventListener('pointerup', up);
          s.removeEventListener('pointercancel', up);
        };
        s.addEventListener('pointermove', moveTo);
        s.addEventListener('pointerup', up);
        s.addEventListener('pointercancel', up);
      });
      s.addEventListener('dblclick', () => {
        const w = (split.sizes[i - 1] + split.sizes[i]) / 2;
        set(w, w);
      });
      s.addEventListener('keydown', (ev) => {
        const row = across();
        const back = row ? 'ArrowLeft' : 'ArrowUp', fwd = row ? 'ArrowRight' : 'ArrowDown';
        if (ev.key !== back && ev.key !== fwd) return;
        ev.preventDefault();
        resize(row, px(split.children[i - 1], row), px(split.children[i], row), ev.key === fwd ? 32 : -32);
      });
      return s;
    }

    /* The tab's part of its context menu. */
    menuFor(tab) {
      const groups = this.groups, g = tab.group;
      if (!g) return [];
      const small = phone(), alone = g.tabs.length === 1;
      const why = small ? 'Not at phone width, where the groups stack' : alone ? 'The only tab of its group: drag another tab beside it instead' : null;
      const side = (label, where) => ({ label, action: () => this.split(tab, g, where) });
      const items = [{ label: 'Split', disabled: small || alone, title: why, submenu: [side('Right', 'right'), side('Down', 'bottom'), side('Left', 'left'), side('Up', 'top')] }];
      if (groups.length > 1) {
        items.push(
          { label: 'Move to Group', submenu: () => groups.map((o, k) => ({ label: `Group ${k + 1}${o.active ? ` (${o.active.title})` : ''}`, disabled: o === g, action: () => { this.move(tab, o); this.app.showTab(tab); } })) },
          { label: 'Join All Groups', action: () => this.join() },
        );
      }
      return items;
    }

    /* ---- a project's layout ---- */

    /* The tree for a project file: each group's tabs as refOf names them
       (those it does not name are left out), the tab it shows, and the
       group in use. */
    layout(refOf) {
      const node = (n) => (n instanceof Group
        ? { tabs: n.tabs.map(refOf).filter(Boolean), shown: n.active ? refOf(n.active) : null }
        : { split: n.dir, sizes: n.sizes.map((s) => Math.round(s * 1e4) / 1e4), parts: n.children.map(node) });
      return { root: node(this.root), active: Math.max(0, this.groups.indexOf(this.active)) };
    }

    /* The tabs into a saved layout (find turns a saved name into a tab, or
       null). Tabs it does not name stay in the first group, after its own;
       a group none of whose tabs came back is left out. Returns the tab of
       the group that was in use, for the app to show. */
    arrange(saved, find) {
      if (!saved || typeof saved !== 'object' || !saved.root) return null;
      const placed = new Set();
      let leafNo = 0;               // the groups in the file's order, for the one in use
      const plan = (n, depth) => {
        if (!n || typeof n !== 'object' || depth > 16) return null;
        if (Array.isArray(n.parts)) {
          const dir = n.split === 'col' ? 'col' : 'row';
          const parts = [], sizes = [];
          n.parts.forEach((q, k) => {
            const p = plan(q, depth + 1);
            if (!p) return;
            const w = Number(n.sizes && n.sizes[k]) > 0 ? Number(n.sizes[k]) : 1;
            if (p.dir === dir) { const sum = p.sizes.reduce((a, b) => a + b, 0); p.parts.forEach((c, m) => { parts.push(c); sizes.push((w * p.sizes[m]) / sum); }); }
            else { parts.push(p); sizes.push(w); }
          });
          if (!parts.length) return null;
          return parts.length === 1 ? parts[0] : { dir, parts, sizes };
        }
        const no = leafNo++;
        const tabs = [];
        for (const r of Array.isArray(n.tabs) ? n.tabs : []) { const t = find(r); if (t && t.group && !placed.has(t)) { placed.add(t); tabs.push(t); } }
        return tabs.length ? { tabs, shown: n.shown ? find(n.shown) : null, no } : null;
      };
      const top = plan(saved.root, 0);
      if (!top) return null;
      const leaves = [];
      this._keepScroll(() => {
        const [first, ...rest] = this.groups;
        for (const g of rest) for (const t of g.tabs.slice()) this._move(t, first);
        let used = false;
        const build = (q) => {
          if (q.tabs) { const g = used ? this._group() : first; used = true; leaves.push([g, q]); return g; }
          const s = new Split(this, q.dir);
          s.children = q.parts.map(build);
          s.children.forEach((c) => { c.parent = s; });
          s.sizes = q.sizes.slice();
          s.render();
          return s;
        };
        const tree = build(top);
        if (tree !== first) {
          this.root = tree;
          tree.parent = null;
          tree.el.style.flex = '';
          this.host.insertBefore(tree.el, this.shelf);
        }
        for (const [g, q] of leaves) q.tabs.forEach((t, k) => this._move(t, g, k));
        for (const [g, q] of leaves) this.show(q.shown && q.shown.group === g ? q.shown : g.tabs[0], { focus: false });
      });
      this._label();
      const act = leaves.find(([, q]) => q.no === Number(saved.active));
      return (act ? act[0] : this.groups[0]).active;
    }

    /* ---- dragging tabs ---- */
    _wireTab(tab) {
      if (tab._docked) return;
      tab._docked = true;
      tab.btn.addEventListener('dragstart', (ev) => {
        this.dragging = tab;
        ev.dataTransfer.setData(MIME, tab.id);
        ev.dataTransfer.setData('text/plain', tab.title);
        ev.dataTransfer.effectAllowed = 'move';
        this.host.classList.add('is-dragging-tab');
        tab.btn.classList.add('is-dragged');
      });
      tab.btn.addEventListener('dragend', () => { tab.btn.classList.remove('is-dragged'); this._clear(); });
    }

    // the tab being dragged, if the drag began in this page (the same page
    // open in another window has tabs of the same names)
    _tabOf(ev) {
      const t = this.dragging;
      const id = ev.dataTransfer && ev.dataTransfer.getData(MIME);
      return t && (!id || id === t.id) ? t : null;
    }

    _clear() {
      this.dragging = null;
      this.host.classList.remove('is-dragging-tab');
      for (const g of this.groups) {
        g.overlay.hidden = true;
        g.overlay.className = 'sm-dropzone';
        g.strip.classList.remove('is-dropping');
        unmark(g.strip);
      }
    }

    // where on a strip a tab let go at x goes: the index of the tab it goes before
    _stripIndex(g, x) {
      const tabs = g.tabs;
      for (let k = 0; k < tabs.length; k++) {
        const r = tabs[k].btn.getBoundingClientRect();
        if (x < r.left + r.width / 2) return k;
      }
      return tabs.length;
    }

    // what a tab let go over a group's views does: 'center' (into the
    // group), an edge (a new group there), or 'none'
    _zone(g, ev, tab) {
      let z = 'center';
      if (!phone()) {
        const r = g.views.getBoundingClientRect();
        const fx = (ev.clientX - r.left) / r.width, fy = (ev.clientY - r.top) / r.height;
        const [side, v] = Object.entries({ left: fx, right: 1 - fx, top: fy, bottom: 1 - fy }).sort((a, b) => a[1] - b[1])[0];
        if (v < EDGE) z = side;
      }
      if (tab && tab.group === g && (z === 'center' || g.tabs.length === 1)) return 'none';
      return z;
    }

    _wire(g) {
      const strip = g.strip;
      strip.addEventListener('dragover', (ev) => {
        if (!hasTab(ev) || !this.dragging) return;
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        g.overlay.hidden = true;
        strip.classList.add('is-dropping');
        unmark(strip);
        const k = this._stripIndex(g, ev.clientX);
        if (g.tabs[k]) g.tabs[k].btn.classList.add('drop-before');
        else if (g.tabs.length) g.tabs[g.tabs.length - 1].btn.classList.add('drop-after');
        // near an end of a strip that scrolls, it scrolls
        const r = strip.getBoundingClientRect();
        if (ev.clientX < r.left + 28) strip.scrollLeft -= 14;
        else if (ev.clientX > r.right - 28) strip.scrollLeft += 14;
      });
      strip.addEventListener('dragleave', (ev) => {
        if (strip.contains(ev.relatedTarget) || inside(strip, ev)) return;
        strip.classList.remove('is-dropping');
        unmark(strip);
      });
      strip.addEventListener('drop', (ev) => {
        if (!hasTab(ev)) return;
        ev.preventDefault();
        const tab = this._tabOf(ev);
        const k = this._stripIndex(g, ev.clientX);
        this._clear();
        if (!tab || !tab.group) return;
        this.move(tab, g, k);
        this.app.showTab(tab);
      });
      g.views.addEventListener('dragover', (ev) => {
        if (!hasTab(ev) || !this.dragging) return;
        const z = this._zone(g, ev, this.dragging);
        g.overlay.hidden = z === 'none';
        if (z === 'none') { ev.dataTransfer.dropEffect = 'none'; return; }
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';
        g.overlay.className = `sm-dropzone is-${z}`;
      });
      g.views.addEventListener('dragleave', (ev) => { if (!g.views.contains(ev.relatedTarget) && !inside(g.views, ev)) g.overlay.hidden = true; });
      g.views.addEventListener('drop', (ev) => {
        if (!hasTab(ev)) return;
        ev.preventDefault();
        const tab = this._tabOf(ev);
        const z = this._zone(g, ev, tab);
        this._clear();
        if (!tab || !tab.group || z === 'none') return;
        if (z === 'center') { this.move(tab, g); this.app.showTab(tab); }
        else this.split(tab, g, z);
      });
    }
  }

  SM.dock = Object.freeze({ Dock, Group, Split, MIME });
}(typeof self !== 'undefined' ? self : this));
