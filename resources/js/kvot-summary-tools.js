/* ==========================================================================
   BUTTONS ON A <summary>'S LINE, NOT IN IT  (shared by the tool pages)

   A button inside a <summary> is a control inside a control: keyboards and
   screen readers do not all reach it, and Chrome reports each one in the
   console ("An interactive element was found within a <summary> element";
   it counts any button, link, field or label, and anything with a tabindex).
   Nor can the buttons go after the <summary> inside the <details>, which
   shows nothing else while it is shut. So they go in a bar before the
   <details>, in a box holding the two, and the summary keeps an empty room
   where they were:

       <div class="kvot-summary-box">
         <span class="kvot-summary-tools"><button>…</button> …</span>
         <details>
           <summary>… <span class="kvot-summary-room" aria-hidden="true"></span> …</summary>
           …
         </details>
       </div>

   KvotSummaryTools.mount(root) gives each room the bar's size and draws the
   bar over it, and does so again whenever the bar or the summary changes
   size; while the summary is not shown, neither is the bar. The room stands
   where the buttons stood in the summary's own layout -- its float, margins
   and vertical alignment are the page's to give it, as they were the
   buttons' -- so the summary looks as it did. A box made in script before
   it is in the page can be mounted at once: it is fitted when it is laid out.
   (The (i) of a kvot-info.js section heading is the same idea, kept there.)
   ========================================================================== */
(function (root) {
  'use strict';

  const parts = new Map();       // box -> { bar, summary, room, seen }
  const resized = typeof ResizeObserver === 'function'
    ? new ResizeObserver((entries) => {
      for (const e of entries) {
        const box = e.target.closest('.kvot-summary-box');
        if (box) fit(box);
      }
    })
    : null;

  function partsOf(box) {
    const bar = box.querySelector(':scope > .kvot-summary-tools');
    const details = box.querySelector(':scope > details');
    const summary = details && details.querySelector(':scope > summary');
    const room = summary && summary.querySelector('.kvot-summary-room');
    return bar && room ? { bar, summary, room, seen: false } : null;
  }

  function fit(box) {
    const p = parts.get(box);
    if (!p) return;
    if (!box.isConnected) {
      // Taken out of the page after being in it: forget it. Not yet in it:
      // the observer calls again once it is laid out.
      if (p.seen) forget(box, p);
      return;
    }
    if (!p.seen) {
      // What the page's stylesheet leaves unsaid, read once it applies.
      if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
      if (getComputedStyle(p.room).display === 'inline') p.room.style.display = 'inline-block';
      p.seen = true;
    }
    const shown = p.summary.getClientRects().length > 0;
    p.bar.style.display = shown ? '' : 'none';
    if (!shown) return;
    // To the fraction of a pixel: offsetWidth rounds, and a room floated
    // right then starts half a pixel away from where the buttons did.
    const size = p.bar.getBoundingClientRect();
    p.room.style.width = `${size.width}px`;
    p.room.style.height = `${size.height}px`;
    const b = box.getBoundingClientRect();
    const r = p.room.getBoundingClientRect();
    p.bar.style.left = `${r.left - b.left - box.clientLeft}px`;
    p.bar.style.top = `${r.top - b.top - box.clientTop}px`;
  }

  function forget(box, p) {
    if (resized) { resized.unobserve(p.bar); resized.unobserve(p.summary); }
    parts.delete(box);
  }

  /* Every box under root (root included) that is not followed already. */
  function mount(rootEl = document) {
    const boxes = [];
    if (rootEl.matches && rootEl.matches('.kvot-summary-box')) boxes.push(rootEl);
    if (rootEl.querySelectorAll) boxes.push(...rootEl.querySelectorAll('.kvot-summary-box'));
    for (const box of boxes) {
      if (parts.has(box)) continue;
      const p = partsOf(box);
      if (!p) continue;
      p.bar.style.position = 'absolute';
      p.bar.style.zIndex = '1';
      parts.set(box, p);
      if (resized) { resized.observe(p.bar); resized.observe(p.summary); }
      fit(box);
    }
  }

  /* Fit every box again, for what moves a room without resizing anything
     the observer watches: a web font arriving, say. */
  function refit() { for (const box of [...parts.keys()]) fit(box); }

  if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) document.fonts.ready.then(refit);

  root.KvotSummaryTools = Object.freeze({ mount, refit });
}(typeof self !== 'undefined' ? self : this));
