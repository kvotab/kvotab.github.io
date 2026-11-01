/* ==========================================================================
   PYLAB.HTML: THE CODE EDITOR

   A textarea over a <pre> that shows the same text in colour, beside a
   gutter of line numbers. The textarea keeps the browser's own editing,
   selection and undo (changes made by keys go through insertText, so undo
   still takes them back). Lines never wrap; the frame scrolls both ways, the
   gutter staying at its left edge, and the coloured text sets its size.

       const ed = new PL.Editor({ value, readOnly, language });
       ed.el                 the element to place
       ed.value              the text (setting it resets the undo history)
       ed.on('change' | 'cursor' | 'gutter' | 'key', fn)
       ed.setBreakpoints(lines) / ed.setArrow(line) / ed.setLint(items)
       ed.revealLine(n, select) / ed.cursorLine() / ed.selectedText()

   Keys: Tab and Shift+Tab indent and outdent; Enter keeps the indent and
   follows the blocks (one level in after if, for, function...); typing the
   end of a block on a line of its own moves it back. Ctrl/⌘+/ (and Ctrl+R,
   Ctrl+T) comment lines out and in, Ctrl/⌘+I indents the selection by its
   blocks, Ctrl/⌘+F finds, Ctrl/⌘+G goes to a line. Other keys go first to
   the 'key' listeners (the desktop's Run, Save, breakpoints).
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, Emitter, icon } = PL;
  const L = () => PL.lang;

  const UNIT = '    ';

  class Editor extends Emitter {
    constructor({ value = '', readOnly = false, language = 'matlab', label = 'Code' } = {}) {
      super();
      this.language = language;
      this.breakpoints = new Set();
      this.arrow = 0;
      this.lint = [];
      this.hl = el('pre', { class: 'ple-hl', 'aria-hidden': 'true' });
      this.ta = el('textarea', { class: 'ple-ta', spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', autocorrect: 'off', wrap: 'off', 'aria-label': label });
      this.ta.setAttribute('data-gramm', 'false');
      this.gutter = el('div', { class: 'ple-gutter' });
      this.sectionBg = el('div', { class: 'ple-sectionbg', hidden: true });
      this.curline = el('div', { class: 'ple-curline', hidden: true });
      this.code = el('div', { class: 'ple-code' }, this.sectionBg, this.curline, this.hl, this.ta);
      this.inner = el('div', { class: 'ple-inner' }, this.gutter, this.code);
      this.el = el('div', { class: `ple lang-${language}` }, this.inner);
      this.el._editor = this;
      this.ta.value = value;
      this.readOnly = readOnly;
      this._raf = 0;
      this._lines = 1;
      this.ta.addEventListener('input', () => { this._draw(); this.emit('change', this.value); });
      this.ta.addEventListener('keydown', (ev) => this._key(ev));
      this.ta.addEventListener('keyup', () => this._cursor());
      this.ta.addEventListener('click', () => this._cursor());
      this.ta.addEventListener('select', () => this._cursor());
      this.el.addEventListener('scroll', () => this._gutterDraw());
      this.gutter.addEventListener('pointerdown', (ev) => {
        const r = this.gutter.getBoundingClientRect();
        const line = Math.floor((ev.clientY - r.top - this._pad()) / this._lh()) + 1;
        if (line >= 1 && line <= this._lines) { ev.preventDefault(); this.emit('gutter', line); }
      });
      // numbers for the lines a taller frame shows, drawn in the next frame:
      // changing the content inside the observed box at once makes the browser
      // report a ResizeObserver loop
      new ResizeObserver(() => { cancelAnimationFrame(this._rzf); this._rzf = requestAnimationFrame(() => this._gutterDraw()); }).observe(this.el);
      this._draw(true);
    }

    get value() { return this.ta.value; }
    set value(v) { this.ta.value = String(v ?? ''); this._draw(true); }
    get readOnly() { return this.ta.readOnly; }
    set readOnly(on) { this.ta.readOnly = !!on; this.el.classList.toggle('is-readonly', !!on); }
    focus() { this.ta.focus({ preventScroll: true }); }

    _lh() {
      const px = parseFloat(getComputedStyle(this.hl).lineHeight);
      return Number.isFinite(px) && px > 0 ? px : 19;
    }

    _pad() { return parseFloat(getComputedStyle(this.hl).paddingTop) || 4; }

    _draw(now = false) {
      const paint = () => {
        this._raf = 0;
        // text pasted past the end of the textarea made it scroll its own text
        // to show the caret; grown with the coloured text it scrolls back, so
        // the frame takes that scroll over and the caret stays where it was
        const sx = this.ta.scrollLeft;
        const sy = this.ta.scrollTop;
        const text = this.ta.value;
        this._lines = text.split('\n').length;
        if (this.language === 'python') this.hl.innerHTML = L().highlightPython(text);
        else if (text.length > 400000) this.hl.textContent = text;
        else this.hl.innerHTML = L().highlight(text);
        if ((sx || sy) && document.activeElement === this.ta) {
          this.ta.scrollLeft = 0;
          this.ta.scrollTop = 0;
          this.el.scrollLeft += sx;
          this.el.scrollTop += sy;
        }
        this._sections();
        this._gutterDraw();
      };
      if (now) { cancelAnimationFrame(this._raf); paint(); return; }
      if (!this._raf) this._raf = requestAnimationFrame(paint);
    }

    _gutterDraw() {
      const lh = this._lh();
      const pad = this._pad();
      const top = this.el.scrollTop;
      const vis = this.el.clientHeight;
      const first = Math.max(1, Math.floor((top - pad) / lh));
      const last = Math.min(this._lines, Math.ceil((top + vis) / lh) + 1);
      const frag = document.createDocumentFragment();
      const lintLines = new Set(this.lint.map((x) => x.line));
      for (let i = first; i <= last; i++) {
        const d = el('div', { class: 'ple-gl', style: { top: `${pad + (i - 1) * lh}px` } }, el('span', { class: 'n' }, String(i)));
        if (this.breakpoints.has(i)) d.append(el('span', { class: 'bp' }));
        if (this.arrow === i) d.append(el('span', { class: 'arrow' }));
        if (lintLines.has(i)) {
          const item = this.lint.find((x) => x.line === i);
          d.append(el('span', { class: 'lint', title: item.message }));
        }
        frag.append(d);
      }
      this.gutter.replaceChildren(frag);
      if (this.arrow) {
        this.curline.hidden = false;
        this.curline.style.top = `${pad + (this.arrow - 1) * lh}px`;
      } else this.curline.hidden = true;
    }

    _sections() {
      if (this.language !== 'matlab') { this.sectionBg.hidden = true; return; }
      const text = this.ta.value;
      if (!/^\s*%%(\s|$)/m.test(text)) { this.sectionBg.hidden = true; return; }
      const line = this.cursorLine() - 1;
      const secs = L().sections(text);
      const s = secs.find((x) => line >= x.start && line <= x.end);
      if (!s) { this.sectionBg.hidden = true; return; }
      const lh = this._lh();
      const pad = this._pad();
      this.sectionBg.hidden = false;
      this.sectionBg.style.top = `${pad + s.start * lh}px`;
      this.sectionBg.style.height = `${(s.end - s.start + 1) * lh}px`;
    }

    _cursor() {
      this._sections();
      this.emit('cursor', this.cursorLine(), this.cursorCol());
    }

    setBreakpoints(lines) { this.breakpoints = new Set(lines); this._gutterDraw(); }
    setArrow(line) { this.arrow = line || 0; this._gutterDraw(); if (line) this.revealLine(line, false); }
    setLint(items) { this.lint = items || []; this._gutterDraw(); }

    cursorLine() { return this.ta.value.slice(0, this.ta.selectionStart).split('\n').length; }
    cursorCol() { const v = this.ta.value; const s = this.ta.selectionStart; return s - (v.lastIndexOf('\n', s - 1) + 1) + 1; }
    selectedText() { return this.ta.value.slice(this.ta.selectionStart, this.ta.selectionEnd); }

    lineStart(n) {
      const v = this.ta.value;
      let pos = 0;
      for (let i = 1; i < n; i++) {
        const j = v.indexOf('\n', pos);
        if (j < 0) return v.length;
        pos = j + 1;
      }
      return pos;
    }

    revealLine(n, select = true) {
      const lh = this._lh();
      const pad = this._pad();
      const y = pad + (n - 1) * lh;
      if (y < this.el.scrollTop + lh || y > this.el.scrollTop + this.el.clientHeight - 2 * lh) {
        this.el.scrollTop = Math.max(0, y - this.el.clientHeight / 3);
      }
      if (select) {
        const s = this.lineStart(n);
        const v = this.ta.value;
        const e = v.indexOf('\n', s);
        this.ta.focus({ preventScroll: true });
        this.ta.setSelectionRange(s, e < 0 ? v.length : e);
        this._cursor();
      }
    }

    gotoLine(n) {
      const s = this.lineStart(n);
      this.ta.focus({ preventScroll: true });
      this.ta.setSelectionRange(s, s);
      this.revealLine(n, false);
      this._cursor();
    }

    /* Replace a range by text the way typing would (undo keeps it). */
    replaceRange(start, end, text) {
      const ta = this.ta;
      ta.focus({ preventScroll: true });
      ta.setSelectionRange(start, end);
      let ok = false;
      try { ok = document.execCommand('insertText', false, text); } catch (e) { ok = false; }
      if (!ok) {
        ta.setRangeText(text, start, end, 'end');
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }

    /* The lines the selection touches: [first, last] 0-based and their offsets. */
    _selLines() {
      const v = this.ta.value;
      const s = this.ta.selectionStart;
      let e = this.ta.selectionEnd;
      if (e > s && v[e - 1] === '\n') e -= 1;
      const a = v.lastIndexOf('\n', s - 1) + 1;
      let b = v.indexOf('\n', e);
      if (b < 0) b = v.length;
      return { a, b, text: v.slice(a, b) };
    }

    _mapLines(fn, keepSel = true) {
      const { a, b, text } = this._selLines();
      const lines = text.split('\n');
      const out = fn(lines);
      const joined = out.join('\n');
      if (joined === text) return;
      this.replaceRange(a, b, joined);
      if (keepSel) this.ta.setSelectionRange(a, a + joined.length);
    }

    commentLines(on) {
      this._mapLines((lines) => {
        const doOn = on === undefined ? !lines.filter((l) => l.trim()).every((l) => /^\s*%/.test(l)) : on;
        if (doOn) {
          const lead = Math.min(...lines.filter((l) => l.trim()).map((l) => /^\s*/.exec(l)[0].length).concat([1e9]));
          return lines.map((l) => (l.trim() ? l.slice(0, lead === 1e9 ? 0 : lead) + '% ' + l.slice(lead === 1e9 ? 0 : lead) : l));
        }
        return lines.map((l) => l.replace(/^(\s*)% ?/, '$1'));
      });
    }

    indentLines(dir) {
      this._mapLines((lines) => lines.map((l) => {
        if (dir > 0) return l.trim() ? UNIT + l : l;
        if (l.startsWith(UNIT)) return l.slice(UNIT.length);
        return l.replace(/^[ \t]{1,4}/, '');
      }));
    }

    smartIndent() {
      const v = this.ta.value;
      const all = L().indent(v, UNIT).split('\n');
      const { a, b } = this._selLines();
      const first = v.slice(0, a).split('\n').length - 1;
      const count = v.slice(a, b).split('\n').length;
      this._mapLines(() => all.slice(first, first + count));
    }

    _key(ev) {
      if (this.emit('key', ev), ev.defaultPrevented) return;
      if (this.readOnly) return;
      const mod = PL.util.mod(ev);
      const ta = this.ta;
      if (ev.key === 'Tab' && !mod && !ev.altKey) {
        ev.preventDefault();
        const s = ta.selectionStart;
        const e = ta.selectionEnd;
        const multi = ta.value.slice(s, e).includes('\n');
        if (ev.shiftKey || multi) this.indentLines(ev.shiftKey ? -1 : 1);
        else this.replaceRange(s, e, UNIT);
        return;
      }
      if (ev.key === 'Enter' && !mod && !ev.altKey && !ev.shiftKey) {
        ev.preventDefault();
        const v = ta.value;
        const s = ta.selectionStart;
        const ls = v.lastIndexOf('\n', s - 1) + 1;
        let line = v.slice(ls, s);
        // a block's end or middle typed on its own line moves back to its block
        const first = /^\s*([a-z]+)\b/.exec(line);
        if (first && ['end', 'else', 'elseif', 'case', 'otherwise', 'catch'].includes(first[1])) {
          const upto = v.slice(0, ls);
          const levels = L().indentLevels(upto + line.trim());
          const want = UNIT.repeat(levels[levels.length - 1]);
          const cur = /^\s*/.exec(line)[0];
          if (cur !== want) {
            this.replaceRange(ls, ls + cur.length, want);
            line = want + line.trimStart();
          }
        }
        const ind = L().nextIndent(line, UNIT);
        const s2 = ta.selectionStart;
        this.replaceRange(s2, ta.selectionEnd, `\n${ind}`);
        return;
      }
      if (ev.key === 'Backspace' && !mod && ta.selectionStart === ta.selectionEnd) {
        const v = ta.value;
        const s = ta.selectionStart;
        const ls = v.lastIndexOf('\n', s - 1) + 1;
        const before = v.slice(ls, s);
        if (before.length && /^ +$/.test(before) && before.length % UNIT.length === 0) {
          ev.preventDefault();
          this.replaceRange(s - UNIT.length, s, '');
          return;
        }
      }
      if (mod && (ev.key === '/' || ev.code === 'Slash')) { ev.preventDefault(); this.commentLines(); return; }
      if (ev.ctrlKey && !ev.metaKey && (ev.key === 'r' || ev.key === 'R') && !ev.shiftKey) { ev.preventDefault(); this.commentLines(true); return; }
      if (ev.ctrlKey && !ev.metaKey && (ev.key === 't' || ev.key === 'T') && !ev.shiftKey) { ev.preventDefault(); this.commentLines(false); return; }
      if (mod && (ev.key === 'i' || ev.key === 'I')) { ev.preventDefault(); this.smartIndent(); return; }
      if (mod && (ev.key === ']')) { ev.preventDefault(); this.indentLines(1); return; }
      if (mod && (ev.key === '[')) { ev.preventDefault(); this.indentLines(-1); return; }
      if (mod && (ev.key === 'f' || ev.key === 'F')) { ev.preventDefault(); this.find(); return; }
      if (mod && (ev.key === 'g' || ev.key === 'G')) { ev.preventDefault(); this.askLine(); return; }
    }

    async askLine() {
      const r = await PL.util.prompt('Go to line', `Line (1–${this._lines})`, String(this.cursorLine()));
      const n = parseInt(r, 10);
      if (Number.isFinite(n)) this.gotoLine(Math.max(1, Math.min(this._lines, n)));
    }

    /* The find bar: Enter for the next match, Shift+Enter the previous,
       Escape to close; Replace replaces the current match. */
    find() {
      if (this.findbar) { this.findbar.querySelector('input').select(); return; }
      const input = el('input', { type: 'text', placeholder: 'Find', spellcheck: 'false', 'aria-label': 'Find' });
      const rep = el('input', { type: 'text', placeholder: 'Replace with', spellcheck: 'false', 'aria-label': 'Replace with' });
      const count = el('span', { class: 'count' });
      const go = (dir) => {
        const q = input.value;
        if (!q) { count.textContent = ''; return; }
        const v = this.ta.value;
        const hits = [];
        let i = v.indexOf(q);
        while (i >= 0) { hits.push(i); i = v.indexOf(q, i + 1); }
        if (!hits.length) { count.textContent = 'no match'; return; }
        const from = dir > 0 ? this.ta.selectionEnd : this.ta.selectionStart - 1;
        let k = dir > 0 ? hits.findIndex((h) => h >= from) : hits.length - 1 - [...hits].reverse().findIndex((h) => h <= from);
        if (k < 0 || k >= hits.length) k = dir > 0 ? 0 : hits.length - 1;
        const at = hits[k];
        this.ta.focus({ preventScroll: true });
        this.ta.setSelectionRange(at, at + q.length);
        this.revealLine(v.slice(0, at).split('\n').length, false);
        input.focus();
        count.textContent = `${k + 1} of ${hits.length}`;
      };
      const replace = () => {
        const q = input.value;
        if (!q) return;
        if (this.selectedText() !== q) { go(1); return; }
        this.replaceRange(this.ta.selectionStart, this.ta.selectionEnd, rep.value);
        go(1);
      };
      const replaceAll = () => {
        const q = input.value;
        if (!q) return;
        const v = this.ta.value;
        const n = v.split(q).length - 1;
        if (!n) return;
        this.replaceRange(0, v.length, v.split(q).join(rep.value));
        count.textContent = `${n} replaced`;
      };
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); go(ev.shiftKey ? -1 : 1); }
        if (ev.key === 'Escape') { ev.preventDefault(); close(); }
      });
      rep.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); replace(); }
        if (ev.key === 'Escape') { ev.preventDefault(); close(); }
      });
      const close = () => { this.findbar.remove(); this.findbar = null; this.focus(); };
      const btn = (name, title, fn) => { const b = el('button', { class: 'pl-iconbtn', type: 'button', title, 'aria-label': title }, icon(name)); b.addEventListener('click', fn); return b; };
      this.findbar = el('div', { class: 'pl-findbar' }, input, count, btn('back', 'Previous match', () => go(-1)), btn('fwd', 'Next match', () => go(1)),
        this.readOnly ? null : rep, this.readOnly ? null : el('button', { class: 'pl-btn', type: 'button', onclick: replace, style: { padding: '1px 8px', fontSize: '12px' } }, 'Replace'),
        this.readOnly ? null : el('button', { class: 'pl-btn', type: 'button', onclick: replaceAll, style: { padding: '1px 8px', fontSize: '12px' } }, 'All'),
        btn('close', 'Close', close));
      this.el.parentElement.append(this.findbar);
      const sel = this.selectedText();
      if (sel && !sel.includes('\n')) input.value = sel;
      input.focus();
      input.select();
    }
  }

  PL.Editor = Editor;
})(window);
