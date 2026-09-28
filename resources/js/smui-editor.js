/* ==========================================================================
   SMUI.HTML: THE CODE EDITOR

   A textarea over a <pre> that shows the same text in colour: Python for
   the notebook and the reports' code, JSL for the converter. The textarea
   keeps the browser's own editing, selection, undo and on-screen keyboard;
   the <pre> under it is drawn again from the text on each change, line by
   line with its number. Both wrap long lines the same way, so the colours
   stay under the letters.

       const ed = SM.editor.create({ value, language: 'python', label, onKey });
       ed.el              the element to place
       ed.value           the text (can be set)
       ed.focus()
       ed.on('change', fn)

   Keys: Tab and Shift+Tab indent and outdent (the selected lines, or at the
   cursor), Enter keeps the indent (one level more after a colon in Python,
   an open bracket in JSL), Backspace in an indent goes back a level, and
   Ctrl/⌘+/ comments the lines out or in. Escape and then Tab leave the
   editor, for the keyboard. onKey(ev) sees a key first and takes it by
   returning true (the notebook's Shift+Enter).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, Emitter } = SM.util;

  const INDENT = '    ';
  const PLAIN_ABOVE = 150000;     // characters: longer text is shown without colours

  const esc = (s) => s.replace(/[&<>]/g, (c) => (c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'));

  /* ---- Python ----------------------------------------------------------------- */
  const PY_KEYWORDS = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield']);
  const PY_BUILTINS = new Set(('abs all any ascii bin bool breakpoint bytearray bytes callable chr classmethod compile complex delattr dict dir divmod '
    + 'enumerate eval exec filter float format frozenset getattr globals hasattr hash help hex id input int isinstance issubclass iter len list '
    + 'locals map max memoryview min next object oct open ord pow print property range repr reversed round set setattr slice sorted staticmethod '
    + 'str sum super tuple type vars zip self cls display __name__ Exception BaseException ValueError TypeError KeyError IndexError AttributeError '
    + 'RuntimeError ZeroDivisionError NotImplementedError StopIteration ImportError ModuleNotFoundError FileNotFoundError OSError NameError '
    + 'AssertionError ArithmeticError LookupError Warning UserWarning RuntimeWarning DeprecationWarning').split(' '));
  // comment | string (with its prefix; triple-quoted strings span lines) | number | decorator | name | space | anything else
  const PY_RE = /(#[^\n]*)|((?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\[\s\S]|[^"\\\n])*(?:"|$)|'(?:\\[\s\S]|[^'\\\n])*(?:'|$)))|((?:\b0[xX][\da-fA-F_]+|\b0[oO][0-7_]+|\b0[bB][01_]+|(?:\b\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?[jJ]?)\b)|(@[A-Za-z_][\w.]*)|([A-Za-z_]\w*)|(\s+)|([\s\S])/y;

  function pythonTokens(src) {
    const out = [];
    PY_RE.lastIndex = 0;
    let m, prev = '';
    while (PY_RE.lastIndex < src.length && (m = PY_RE.exec(src))) {
      if (m[1]) out.push(['c', m[1]]);
      else if (m[2]) out.push(['s', m[2]]);
      else if (m[3]) out.push(['n', m[3]]);
      else if (m[4]) out.push(['d', m[4]]);
      else if (m[5]) {
        const w = m[5];
        if (prev === 'def' || prev === 'class') out.push(['f', w]);
        else if (PY_KEYWORDS.has(w)) out.push(['k', w]);
        else if ((w === 'match' || w === 'case') && /(^|\n)[ \t]*$/.test(src.slice(Math.max(0, m.index - 80), m.index)) && /^[ \t]+[^=\s]/.test(src.slice(PY_RE.lastIndex, PY_RE.lastIndex + 3))) out.push(['k', w]);
        else if (PY_BUILTINS.has(w)) out.push(['b', w]);
        else out.push([null, w]);
        prev = w;
        continue;
      } else out.push([null, m[6] || m[7]]);
      if (!m[6]) prev = '';
    }
    return out;
  }

  /* ---- JSL ------------------------------------------------------------------------ */
  const JSL_CONTROL = new Set(['if', 'for', 'while', 'foreach', 'foreachrow', 'function', 'return', 'break', 'continue', 'match', 'choose', 'try', 'throw', 'local', 'here', 'namesdefaulttohere', 'expr', 'eval', 'evalexpr', 'parse', 'include', 'wait']);
  // comment | raw string "\[ … ]\" | string with \! escapes | number | :column or ::name | a name (its words may have spaces) called with ( | name | << | space | other
  const JSL_RE = /(\/\/[^\n]*|\/\*[\s\S]*?(?:\*\/|$))|("\\\[[\s\S]*?(?:\]\\"|$)|"(?:\\!.|\\(?!!)|[^"\\])*(?:"|$))|((?:\b\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\b)|(:{1,2}[A-Za-z_]\w*)|([A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*(?=\s*\())|([A-Za-z_]\w*)|(<<)|(\s+)|([\s\S])/y;

  function jslTokens(src) {
    const out = [];
    JSL_RE.lastIndex = 0;
    let m;
    while (JSL_RE.lastIndex < src.length && (m = JSL_RE.exec(src))) {
      if (m[1]) out.push(['c', m[1]]);
      else if (m[2]) out.push(['s', m[2]]);
      else if (m[3]) out.push(['n', m[3]]);
      else if (m[4]) out.push(['v', m[4]]);
      else if (m[5]) out.push([JSL_CONTROL.has(m[5].replace(/\s+/g, '').toLowerCase()) ? 'k' : 'f', m[5]]);
      else if (m[7]) out.push(['o', m[7]]);
      else out.push([null, m[6] || m[8] || m[9]]);
    }
    return out;
  }

  const TOKENIZERS = { python: pythonTokens, jsl: jslTokens };

  /* The coloured lines: one block per line (its number drawn by CSS), the
     tokens split where they cross a line end. */
  function highlight(src, language) {
    const tokens = (TOKENIZERS[language] || ((s) => [[null, s]]))(src);
    let html = '<span class="ln">';
    for (const [cls, text] of tokens) {
      const parts = text.split('\n');
      for (let i = 0; i < parts.length; i++) {
        if (i > 0) html += '</span><span class="ln">';
        if (parts[i]) html += cls ? `<span class="t-${cls}">${esc(parts[i])}</span>` : esc(parts[i]);
      }
    }
    return `${html}</span>`;
  }

  function plainLines(src) {
    return src.split('\n').map((l) => `<span class="ln">${esc(l)}</span>`).join('');
  }

  /* ---- the editor ----------------------------------------------------------------- */
  class Editor extends Emitter {
    constructor({ value = '', language = 'python', label = 'Code', readOnly = false, onKey = null, placeholder = '' } = {}) {
      super();
      this.language = language;
      this.onKey = onKey;
      this.hl = el('pre', { class: 'sm-ed-hl', 'aria-hidden': 'true' });
      this.ta = el('textarea', { class: 'sm-ed-ta', spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', autocorrect: 'off', wrap: 'soft', 'aria-label': label, placeholder });
      this.ta.setAttribute('data-gramm', 'false');       // no grammar helpers on code
      this.el = el('div', { class: `sm-ed lang-${language}` }, this.hl, this.ta);
      this.el._editor = this;
      this.ta.value = value;
      this.readOnly = readOnly;
      this._escaped = false;
      this._raf = 0;
      this.ta.addEventListener('input', () => { this._draw(); this.emit('change', this.value); });
      this.ta.addEventListener('keydown', (ev) => this._key(ev));
      this.ta.addEventListener('focus', () => { this._escaped = false; this.el.classList.add('is-focus'); });
      this.ta.addEventListener('blur', () => this.el.classList.remove('is-focus'));
      this._draw(true);
    }

    get value() { return this.ta.value; }
    set value(v) { this.ta.value = String(v ?? ''); this._draw(true); }
    get readOnly() { return this.ta.readOnly; }
    set readOnly(on) { this.ta.readOnly = !!on; this.el.classList.toggle('is-readonly', !!on); }
    focus(opts) { this.ta.focus(opts); }

    _draw(now = false) {
      const paint = () => {
        this._raf = 0;
        const v = this.ta.value;
        const plain = v.length > PLAIN_ABOVE;
        this.el.classList.toggle('is-plain', plain);
        this.hl.innerHTML = plain ? plainLines(v) : highlight(v, this.language);
      };
      if (now) { if (this._raf) cancelAnimationFrame(this._raf); paint(); return; }
      // Typing draws at once (the letters are only visible in the <pre>);
      // a long text waits for the next frame, so keys do not queue up.
      if (this.ta.value.length < 20000) paint();
      else if (!this._raf) this._raf = requestAnimationFrame(paint);
    }

    /* Insert text in place of the selection, through the browser's editing so
       that Undo takes it back. */
    _insert(text, selectFrom = null, selectTo = null) {
      const ta = this.ta;
      if (!(document.execCommand && document.execCommand('insertText', false, text))) {
        ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, 'end');
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (selectFrom != null) ta.setSelectionRange(selectFrom, selectTo ?? selectFrom);
    }

    _lineStart(pos) { return this.ta.value.lastIndexOf('\n', pos - 1) + 1; }

    // the whole lines the selection touches, as [start, end)
    _lines() {
      const v = this.ta.value, a = this.ta.selectionStart;
      let b = this.ta.selectionEnd;
      if (b > a && v[b - 1] === '\n') b--;
      const start = this._lineStart(a);
      let end = v.indexOf('\n', b);
      if (end < 0) end = v.length;
      return [start, end];
    }

    _mapLines(fn) {
      const ta = this.ta;
      const [start, end] = this._lines();
      const block = ta.value.slice(start, end);
      const out = block.split('\n').map(fn).join('\n');
      ta.setSelectionRange(start, end);
      this._insert(out, start, start + out.length);
    }

    _key(ev) {
      if (this.onKey && this.onKey(ev, this)) { ev.preventDefault(); return; }
      if (this.ta.readOnly) return;
      const ta = this.ta, v = ta.value;
      const a = ta.selectionStart, b = ta.selectionEnd;
      if (ev.key === 'Escape') { this._escaped = true; return; }
      if (ev.key === 'Tab' && !ev.altKey && !ev.ctrlKey && !ev.metaKey) {
        if (this._escaped) { this._escaped = false; return; }        // Escape, then Tab: out of the editor
        ev.preventDefault();
        const multi = v.slice(a, b).includes('\n');
        if (ev.shiftKey) this._mapLines((l) => l.replace(/^( {1,4}|\t)/, ''));
        else if (multi) this._mapLines((l) => (l ? INDENT + l : l));
        else {
          const col = a - this._lineStart(a);
          this._insert(' '.repeat(INDENT.length - (col % INDENT.length)));
        }
        return;
      }
      this._escaped = false;
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey && !ev.isComposing) {
        ev.preventDefault();
        const start = this._lineStart(a);
        const line = v.slice(start, a);
        let indent = /^[ \t]*/.exec(line)[0];
        const before = line.replace(/#.*$/, '').trimEnd();
        if (this.language === 'python' && before.endsWith(':')) indent += INDENT;
        else if (/[([{]$/.test(before)) indent += INDENT;
        else if (this.language === 'python' && /^\s*(return|pass|break|continue|raise)\b/.test(line) && indent.length >= INDENT.length) indent = indent.slice(INDENT.length);
        this._insert(`\n${indent}`);
        return;
      }
      if (ev.key === 'Backspace' && a === b && a > 0) {
        const start = this._lineStart(a);
        const head = v.slice(start, a);
        if (head.length && /^ +$/.test(head)) {
          ev.preventDefault();
          const n = head.length % INDENT.length || INDENT.length;
          ta.setSelectionRange(a - n, a);
          this._insert('');
        }
        return;
      }
      if (ev.key === '/' && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        const mark = this.language === 'jsl' ? '//' : '#';
        const [start, end] = this._lines();
        const lines = v.slice(start, end).split('\n');
        const used = lines.filter((l) => l.trim());
        const off = used.every((l) => l.trimStart().startsWith(mark));
        // the mark goes at the indent the lines have in common, as editors put it
        const at = Math.min(...used.map((l) => /^[ \t]*/.exec(l)[0].length));
        this._mapLines((l) => {
          if (!l.trim()) return l;
          if (off) return l.replace(new RegExp(`^(\\s*)${mark.replace(/\//g, '\\/')} ?`), '$1');
          return `${l.slice(0, at)}${mark} ${l.slice(at)}`;
        });
      }
    }
  }

  function create(opts) { return new Editor(opts); }

  SM.editor = Object.freeze({ create, Editor, highlight, pythonTokens, jslTokens });
}(typeof self !== 'undefined' ? self : this));
