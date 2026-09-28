/* ==========================================================================
   SMUI.HTML: DRAG AND DROP BY TOUCH

   The page's drags (columns from a launch dialog's list onto a role or the
   model effects, Graph Builder's and Tabulate's columns onto their zones,
   the formula editor's columns into the formula, the Columns panel's
   order) are HTML drag and drop, which a phone does not start from a
   finger: the finger scrolls the page instead. Here a touch that is held
   still for a moment lifts the item, and moving it then sends the same
   drag events a mouse would (dragstart, dragenter, dragover, dragleave,
   drop, dragend), with a stand-in for the dataTransfer, so every drop
   target works as it is. A touch that moves at once scrolls as before; one
   held without moving still gets the context menu where the phone has one.
   A text field takes the dragged text at its cursor, as it would a drop.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  if (typeof document === 'undefined') return;

  const HOLD_MS = 320;        // held this long without moving: lifted
  const SLOP = 8;             // moved further first (px): a scroll, not a drag
  const EDGE = 44;            // this near a scrolling box's edge (px): it scrolls

  let press = null;           // a touch on a draggable item, not yet lifted
  let drag = null;            // the drag under way

  // What a drag carries, as the browser's DataTransfer offers it to the handlers.
  function transfer() {
    const data = new Map();
    return {
      dropEffect: 'none', effectAllowed: 'all', files: [], items: [],
      get types() { return [...data.keys()]; },
      setData(type, value) { data.set(String(type).toLowerCase(), String(value)); },
      getData(type) { return data.get(String(type).toLowerCase()) ?? ''; },
      clearData(type) { if (type) data.delete(String(type).toLowerCase()); else data.clear(); },
      setDragImage() {},
    };
  }

  function fire(target, type, dt, x, y, related = null) {
    const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, relatedTarget: related });
    Object.defineProperty(ev, 'dataTransfer', { value: dt });
    target.dispatchEvent(ev);
    return ev;
  }

  const isField = (e) => !!(e && (e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && /^(text|search|)$/.test(e.type || ''))));

  function sourceOf(t) {
    const src = t && t.closest && t.closest('[draggable="true"]');
    if (!src || isField(src) || !src.closest('.sm, .sm-dialog')) return null;
    return src;
  }

  function onStart(ev) {
    if (drag || ev.touches.length !== 1) { cancelPress(); return; }
    const src = sourceOf(ev.target);
    if (!src) return;
    const t = ev.touches[0];
    // the browser's own long-press drag and text selection stay out of it
    src.setAttribute('draggable', 'false');
    press = { src, x: t.clientX, y: t.clientY, lifted: false, timer: setTimeout(() => { if (press) { press.lifted = true; unselect(); src.classList.add('sm-touch-ready'); if (navigator.vibrate) navigator.vibrate(8); } }, HOLD_MS) };
  }

  // A text selection the browser began under the finger goes (an iPhone
  // starts one on a long press, and its handles then take the gesture).
  function unselect() {
    const s = typeof getSelection === 'function' ? getSelection() : null;
    if (s && s.rangeCount) s.removeAllRanges();
  }

  function cancelPress() {
    if (!press) return;
    clearTimeout(press.timer);
    press.src.setAttribute('draggable', 'true');
    press.src.classList.remove('sm-touch-ready');
    press = null;
  }

  function lift(x, y) {
    const src = press.src;
    clearTimeout(press.timer);
    press = null;
    const dt = transfer();
    const start = fire(src, 'dragstart', dt, x, y);
    src.setAttribute('draggable', 'true');
    src.classList.remove('sm-touch-ready');
    if (start.defaultPrevented) return;
    unselect();
    const lines = dt.getData('text/plain').split('\n').filter(Boolean);
    const label = (lines[0] || src.textContent || '').trim().slice(0, 40) + (lines.length > 1 ? ` +${lines.length - 1}` : '');
    // the column's type icon and its name, as the list shows it
    const icon = src.querySelector('.sm-type');
    const ghost = SM.util.el('div', { class: 'sm-touchghost', 'aria-hidden': 'true' }, icon ? icon.cloneNode(true) : null, SM.util.el('span', { text: label }));
    document.body.append(ghost);
    drag = { src, dt, ghost, over: null, accepted: false, x, y, raf: 0, box: scrollBoxOf(src) };
    src.classList.add('sm-touch-dragging');
    move(x, y);
    autoscroll();
  }

  function move(x, y) {
    drag.x = x; drag.y = y;
    drag.ghost.style.left = `${x}px`;
    drag.ghost.style.top = `${y}px`;
    const at = document.elementFromPoint(x, y);
    if (at !== drag.over) {
      if (drag.over) fire(drag.over, 'dragleave', drag.dt, x, y, at);
      if (at) fire(at, 'dragenter', drag.dt, x, y, drag.over);
      drag.over = at;
    }
    const over = at ? fire(at, 'dragover', drag.dt, x, y) : null;
    // a drop target says yes by preventing dragover's default; a text field takes text
    drag.accepted = !!(over && (over.defaultPrevented || isField(at)));
    drag.ghost.classList.toggle('is-yes', drag.accepted);
  }

  function scrollBoxOf(e) {
    for (; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (/auto|scroll/.test(cs.overflowY) && e.scrollHeight > e.clientHeight + 2) return e;
    }
    return null;
  }

  // Near the top or bottom of a box that scrolls (a list, a dialog's body, a
  // report), or past it (over the page's footer), it scrolls, faster the
  // further the finger goes.
  function autoscroll() {
    if (!drag) return;
    const e = scrollBoxOf(drag.over) || drag.box;
    if (e && e.isConnected) {
      drag.box = e;
      const r = e.getBoundingClientRect();
      const past = drag.y < r.top + EDGE ? drag.y - (r.top + EDGE) : drag.y > r.bottom - EDGE ? drag.y - (r.bottom - EDGE) : 0;
      const dy = Math.sign(past) * Math.min(28, Math.ceil(Math.abs(past) / 3));
      if (dy) { const was = e.scrollTop; e.scrollTop += dy; if (e.scrollTop !== was) move(drag.x, drag.y); }
    }
    drag.raf = requestAnimationFrame(autoscroll);
  }

  function end(x, y, cancelled) {
    const d = drag;
    drag = null;
    cancelAnimationFrame(d.raf);
    d.ghost.remove();
    d.src.classList.remove('sm-touch-dragging');
    const at = d.over;
    if (!cancelled && at && d.accepted) {
      const dropped = fire(at, 'drop', d.dt, x, y);
      if (!dropped.defaultPrevented && isField(at)) {
        // the text goes in at the field's cursor, as a drop would put it
        const text = d.dt.getData('text/plain');
        if (text) { at.focus(); at.setRangeText(text, at.selectionStart, at.selectionEnd, 'end'); at.dispatchEvent(new Event('input', { bubbles: true })); }
      }
    } else if (at) fire(at, 'dragleave', d.dt, x, y, null);
    fire(d.src, 'dragend', d.dt, x, y);
  }

  document.addEventListener('touchstart', onStart, { capture: true, passive: true });
  document.addEventListener('touchmove', (ev) => {
    const t = ev.touches[0];
    if (drag) { ev.preventDefault(); move(t.clientX, t.clientY); return; }
    if (!press) return;
    const far = Math.hypot(t.clientX - press.x, t.clientY - press.y) > SLOP;
    if (!press.lifted) { if (far) cancelPress(); return; }     // moved at once: a scroll
    ev.preventDefault();                                          // held, then moved: a drag
    lift(t.clientX, t.clientY);
  }, { capture: true, passive: false });
  document.addEventListener('touchend', (ev) => {
    if (drag) { ev.preventDefault(); const t = ev.changedTouches[0]; end(t.clientX, t.clientY, false); return; }
    cancelPress();
  }, { capture: true, passive: false });
  document.addEventListener('touchcancel', () => { if (drag) end(drag.x, drag.y, true); cancelPress(); }, { capture: true });
  // held still until the phone offers its menu: the menu, not a drag
  document.addEventListener('contextmenu', () => { if (press) cancelPress(); }, true);
  // no text selection while an item is held or dragged (the CSS says so too)
  document.addEventListener('selectstart', (ev) => { if (press || drag) ev.preventDefault(); }, true);

  // While a drag is under way, by mouse or by touch, the places that take a
  // drop are marked (smui.css :root.sm-dragging).
  const rootEl = document.documentElement;
  document.addEventListener('dragstart', () => rootEl.classList.add('sm-dragging'));
  for (const t of ['dragend', 'drop']) document.addEventListener(t, () => rootEl.classList.remove('sm-dragging'));

  SM.touchdrag = Object.freeze({ HOLD_MS, active: () => !!drag });
}(typeof self !== 'undefined' ? self : this));
