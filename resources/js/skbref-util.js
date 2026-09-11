/* ==========================================================================
   SKB REFERENCE CHECKER — util

   Small shared helpers: section shells, escaping and bold-run rendering.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function section(title,count,body,open=false){const good=!count||count==='unavailable';return `<details class="result-section" ${open?'open':''}><summary>${title}<span class="section-badge ${good?'good':'warn'}">${count===0?'✓ none':count}</span></summary><div class="section-body">${body}</div></details>`;}
    function setSummary(name,value,state){$(`cnt-${name}`).textContent=value;const card=$(`card-${name}`);card.classList.remove('warn','ok');if(state)card.classList.add(state);}
    /* One implementation, in resources/js/kvot-safe.js. The local copy escaped
       everything but the apostrophe, which is the same gap in an attribute
       written with single quotes as a missing &quot; is in one with double. */
    function escHtml(value){return kvotEscapeHtml(value);}

    /*
      Text with its bold runs kept, everything else escaped. The ranges are
      merged first: an entry assembled from several runs and several paragraphs
      can produce adjacent or overlapping ones, and emitting a <strong> per run
      would nest and leave the markup unbalanced where two overlap.
    */
    function renderTextWithBold(text, ranges) {
      const value = String(text ?? '');
      const merged = (ranges || [])
        .map(range => ({ start: Math.max(0, range.start), end: Math.min(value.length, range.end) }))
        .filter(range => range.end > range.start)
        .sort((first, second) => first.start - second.start)
        .reduce((out, range) => {
          const last = out[out.length - 1];
          if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
          else out.push(range);
          return out;
        }, []);
      if (!merged.length) return escHtml(value);
      let html = '';
      let cursor = 0;
      for (const range of merged) {
        html += escHtml(value.slice(cursor, range.start))
          + `<strong>${escHtml(value.slice(range.start, range.end))}</strong>`;
        cursor = range.end;
      }
      return html + escHtml(value.slice(cursor));
    }
    function truncate(value,length){return value.length>length?`${value.slice(0,length)}…`:value;}
