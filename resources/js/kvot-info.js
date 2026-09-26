/* ==========================================================================
   THE (i) AND ITS PANEL  (shared by the tool pages)

   A small (i) next to a setting, a section heading or a tab's toolbar opens a
   panel over the right-hand side of the window with what the thing is, what
   its choices do and where the Help says more. It replaces hover tooltips,
   which cannot be read while editing, hold little text and do not work on
   touch or from the keyboard. The behaviour is Kompartment's
   (src/ui/infopanel.js) and SimpleFunctions.html's: one panel at a time,
   closed by its ×, by the same (i) or by Escape, built from text nodes only.

   The markup holds empty slots; mount() fills them:

       <span class="kvot-info-slot" data-info-key="set:seed"></span>

   and a page registers its topics once:

       KvotInfo.setup({
         topics: { 'set:seed': { kicker, title, lead, facts, sections, more }, ... },
         onMore: (more) => { showTab('help'); ... },   // "Read more in Help"
       });

   A topic may be a function, called each time the panel opens, so that it
   can mark the current choice. Its parts, all optional but the title:

       kicker    the small line above the title ('Section', 'Solver', ...)
       title     the heading
       lead      a paragraph, or an array of them
       facts     [[label, value], ...] as a two-column list
       sections  [{ heading, text, list, choices }, ...]; choices are
                 [[name, what it does, is it the current one], ...]
       more      { label, id }: a link to the Help heading with that id

   Inline markup in any text is `code` and **bold**, nothing else.

   setup() also takes morePrefix, the words before the link's label
   ('Read more in Help: ' unless the page has no Help to point to). While a
   panel is open the root element carries the class kvot-info-open, and every
   open and close sends a 'kvot-info-change' event to the document with the
   key in its detail (null on close), for a page that has to make room.
   ========================================================================== */
(function (root) {
  'use strict';

  const state = { topics: Object.create(null), onMore: null, panel: null, key: null, panelId: 'kvot-info-panel', morePrefix: 'Read more in Help: ' };
  const bound = new WeakSet();   // the buttons made here, so that copies can be told apart

  function glyph() {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 16 16');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('aria-hidden', 'true');
    const c = document.createElementNS(ns, 'circle');
    c.setAttribute('cx', '8'); c.setAttribute('cy', '8'); c.setAttribute('r', '6.9');
    c.setAttribute('fill', 'none'); c.setAttribute('stroke', 'currentColor'); c.setAttribute('stroke-width', '1.3');
    const dot = document.createElementNS(ns, 'circle');
    dot.setAttribute('cx', '8'); dot.setAttribute('cy', '4.7'); dot.setAttribute('r', '1'); dot.setAttribute('fill', 'currentColor');
    const bar = document.createElementNS(ns, 'rect');
    bar.setAttribute('x', '7.25'); bar.setAttribute('y', '6.8'); bar.setAttribute('width', '1.5'); bar.setAttribute('height', '5.2');
    bar.setAttribute('rx', '0.75'); bar.setAttribute('fill', 'currentColor');
    svg.append(c, dot, bar);
    return svg;
  }

  function mk(tag, cls, ...children) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    for (const child of children) if (child != null) el.append(child);
    return el;
  }

  function inline(text) {
    const nodes = [];
    const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
    const s = String(text ?? '');
    let at = 0;
    for (let m = re.exec(s); m; m = re.exec(s)) {
      if (m.index > at) nodes.push(document.createTextNode(s.slice(at, m.index)));
      nodes.push(mk(m[1] != null ? 'code' : 'b', '', m[1] != null ? m[1] : m[2]));
      at = re.lastIndex;
    }
    if (at < s.length) nodes.push(document.createTextNode(s.slice(at)));
    return nodes;
  }

  function resolve(key) {
    const t = state.topics[key];
    try { return typeof t === 'function' ? t() : (t || null); } catch (e) { return null; }
  }

  function button(key) {
    const t = resolve(key);
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `info-btn${state.key === key ? ' is-open' : ''}`;
    b.dataset.info = key;
    b.setAttribute('aria-label', `About ${t && t.title ? t.title : 'this setting'}`);
    b.setAttribute('aria-expanded', String(state.key === key));
    b.setAttribute('aria-controls', state.panelId);
    b.append(glyph());
    b.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (state.key === key) close(); else open(key);
    });
    bound.add(b);
    return b;
  }

  /* Fill every slot under root whose key has a topic. Safe to call again
     after a part of the page is rebuilt; a slot copied with cloneNode, whose
     button has lost its handler, gets a new one. */
  function mount(rootEl = document) {
    rootEl.querySelectorAll('.kvot-info-slot[data-info-key]').forEach((slot) => {
      const key = slot.dataset.infoKey;
      if (!state.topics[key]) return;
      const have = slot.querySelector('.info-btn');
      if (have && bound.has(have) && have.dataset.info === key) return;
      slot.replaceChildren(button(key));
    });
  }

  /* A filled slot, for rows that are built in script. */
  function slot(key) {
    const s = mk('span', 'kvot-info-slot');
    s.dataset.infoKey = key;
    if (state.topics[key]) s.append(button(key));
    return s;
  }

  function place() {
    if (!state.panel) return;
    const header = document.querySelector('body > header, header.site-header, header');
    const footer = document.querySelector('body > footer, footer');
    const top = header ? header.getBoundingClientRect().bottom : 0;
    const foot = footer ? footer.getBoundingClientRect().top : window.innerHeight;
    state.panel.style.top = `${Math.max(0, Math.round(top))}px`;
    state.panel.style.bottom = `${Math.max(0, Math.round(window.innerHeight - Math.min(foot, window.innerHeight)))}px`;
  }

  function render(t) {
    const p = state.panel;
    p.querySelector('.info-panel-kicker').textContent = t.kicker || '';
    p.querySelector('.info-panel-title').textContent = t.title || '';
    const out = [];
    for (const para of [].concat(t.lead || [])) out.push(mk('p', 'info-lead', ...inline(para)));
    if (t.facts && t.facts.length) {
      const dl = mk('dl', 'info-facts');
      for (const [label, value] of t.facts) {
        if (value == null || value === '') continue;
        dl.append(mk('dt', '', ...inline(label)), mk('dd', '', ...inline(String(value))));
      }
      out.push(dl);
    }
    for (const s of t.sections || []) {
      if (s.heading) out.push(mk('h3', '', s.heading));
      for (const para of [].concat(s.text || [])) out.push(mk('p', '', ...inline(para)));
      if (s.list) out.push(mk('ul', '', ...s.list.map((li) => mk('li', '', ...inline(li)))));
      if (s.choices) {
        const dl = mk('dl', 'info-choices');
        for (const [name, what, on] of s.choices) dl.append(mk('dt', on ? 'is-current' : '', ...inline(name)), mk('dd', '', ...inline(what || '')));
        out.push(dl);
      }
    }
    if (t.more) {
      const b = mk('button', 'info-panel-more', t.more.prefix ?? state.morePrefix, mk('b', '', t.more.label), ' →');
      b.type = 'button';
      b.addEventListener('click', () => {
        const more = t.more;
        close();
        if (typeof state.onMore === 'function') state.onMore(more);
        const h = document.getElementById(more.id);
        if (h) h.scrollIntoView({ block: 'start' });
      });
      out.push(mk('p', 'info-panel-more-line', b));
    }
    const body = p.querySelector('.info-panel-body');
    body.replaceChildren(...out);
    return body;
  }

  function open(key) {
    const t = resolve(key);
    if (!t) return;
    state.key = key;
    if (!state.panel || !state.panel.isConnected) {
      const x = mk('button', 'info-panel-close', '×');
      x.type = 'button';
      x.setAttribute('aria-label', 'Close');
      x.addEventListener('click', close);
      const panel = mk('aside', 'info-panel',
        mk('div', 'info-panel-head', mk('div', 'info-panel-heading', mk('div', 'info-panel-kicker'), mk('h2', 'info-panel-title')), x),
        mk('div', 'info-panel-body'));
      panel.id = state.panelId;
      panel.setAttribute('role', 'complementary');
      panel.querySelector('.info-panel-body').tabIndex = -1;
      panel.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); close(); }
      });
      document.body.append(panel);
      state.panel = panel;
    }
    const body = render(t);
    body.scrollTop = 0;
    place();
    mark();
    announce();
    body.focus({ preventScroll: true });
  }

  function announce() {
    document.documentElement.classList.toggle('kvot-info-open', !!state.key);
    document.dispatchEvent(new CustomEvent('kvot-info-change', { detail: { key: state.key } }));
  }

  function close() {
    const key = state.key;
    state.key = null;
    const wasOpen = !!state.panel;
    if (state.panel) state.panel.remove();
    state.panel = null;
    mark();
    if (wasOpen) announce();
    const back = key ? document.querySelector(`[data-info="${CSS.escape(key)}"]`) : null;
    if (back) back.focus({ preventScroll: true });
  }

  /* Re-render the open topic, e.g. after a setting changed which one of its
     choices is current. */
  function refresh() {
    if (!state.key || !state.panel) return;
    const t = resolve(state.key);
    if (t) render(t);
  }

  function mark() {
    document.querySelectorAll('[data-info]').forEach((b) => {
      const on = state.key === b.dataset.info;
      b.classList.toggle('is-open', on);
      b.setAttribute('aria-expanded', String(on));
    });
  }

  function setup(opts = {}) {
    if (opts.topics) state.topics = Object.assign(Object.create(null), opts.topics);
    if (typeof opts.onMore === 'function') state.onMore = opts.onMore;
    if (opts.panelId) state.panelId = opts.panelId;
    if (typeof opts.morePrefix === 'string') state.morePrefix = opts.morePrefix;
    mount(document);
  }

  window.addEventListener('resize', place);
  // Escape closes the panel also when the focus is on nothing in particular
  // or on an (i), not only inside the panel; a field keeps its own Escape.
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || ev.defaultPrevented || !state.key) return;
    const at = document.activeElement;
    if (!at || at === document.body || (state.panel && state.panel.contains(at)) || (at.closest && at.closest('[data-info]'))) close();
  });

  /* For the tests: slots without a topic, and topics whose Help link has no
     target in the page. */
  function audit() {
    const keys = Object.keys(state.topics);
    const slots = Array.from(document.querySelectorAll('.kvot-info-slot[data-info-key]')).map((s) => s.dataset.infoKey);
    const noTopic = slots.filter((k) => !state.topics[k]);
    const brokenMore = keys.filter((k) => {
      const t = resolve(k);
      return !t || !t.title || (t.more && !document.getElementById(t.more.id));
    });
    return { topics: keys.length, slots: slots.length, buttons: document.querySelectorAll('.kvot-info-slot .info-btn').length, noTopic, brokenMore };
  }

  root.KvotInfo = Object.freeze({ setup, mount, slot, open, close, refresh, audit, current: () => state.key });
}(typeof self !== 'undefined' ? self : this));
