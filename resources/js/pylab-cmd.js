/* ==========================================================================
   PYLAB.HTML: THE COMMAND WINDOW

   Output, then the prompt and the line being typed, in one scrolling
   frame. Enter runs the command when it is complete; an open block (for,
   if, function...) or an open [ or { takes another line instead, as does
   Shift+Enter. Up and Down step through earlier commands that start with
   what is typed; Tab completes names. While a program runs, what is typed
   and entered waits its turn; Ctrl+C stops the program.

   Modes: 'normal' (>>), 'debug' (K>>, the paused function's workspace) and
   'input' (the program's input() prompt; Enter answers it).

   Events: 'submit' (code), 'interrupt', 'reply' (text, for input), 'link'
   (path, line), 'complete' (request {text, pos} -> promise of items).
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, Emitter } = PL;
  const MAX_CHARS = 400000;

  class CommandWindow extends Emitter {
    constructor({ history }) {
      super();
      this.history = history;          // a PL.History
      this.out = el('div', { class: 'pl-cmd-out', 'aria-live': 'polite' });
      this.prompt = el('span', { class: 'pl-prompt' }, '>> ');
      this.ta = el('textarea', { class: 'pl-cmd-ta', rows: '1', spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', autocorrect: 'off', 'aria-label': 'Command' });
      this.ta.setAttribute('data-gramm', 'false');
      this.inrow = el('div', { class: 'pl-cmd-in' }, this.prompt, this.ta);
      this.queuedEl = el('div', { class: 'pl-queued', hidden: true });
      this.el = el('div', { class: 'pl-cmd', tabindex: '-1' }, this.out, this.inrow, this.queuedEl);
      this.mode = 'normal';
      this.busy = false;
      this.queue = [];
      this.histPos = -1;
      this.histPrefix = '';
      this.draft = '';
      this.chars = 0;
      this.pendingText = '';
      this._raf = 0;
      this.ta.addEventListener('keydown', (ev) => this._key(ev));
      this.ta.addEventListener('input', () => { this._fit(); this.histPos = -1; this._closeComplete(); });
      this.el.addEventListener('mouseup', () => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) this.focus();
      });
      this.out.addEventListener('click', (ev) => {
        const a = ev.target.closest('[data-path]');
        if (a) { ev.preventDefault(); this.emit('link', a.dataset.path, Number(a.dataset.line) || 0); }
        const h = ev.target.closest('[data-run]');
        if (h) { ev.preventDefault(); this.emit('submit', h.dataset.run); }
      });
    }

    focus() { this.ta.focus({ preventScroll: true }); }

    _fit() {
      this.ta.style.height = 'auto';
      this.ta.style.height = `${this.ta.scrollHeight}px`;
    }

    scrollEnd() {
      cancelAnimationFrame(this._sraf);
      this._sraf = requestAnimationFrame(() => { this.el.scrollTop = this.el.scrollHeight; });
    }

    /* Output arrives in pieces; it is drawn once per frame. */
    write(text, kind = 'out') {
      if (!text) return;
      this.pendingRuns = this.pendingRuns || [];
      this.pendingRuns.push([text, kind]);
      if (!this._raf) this._raf = requestAnimationFrame(() => this._flush());
    }

    _flush() {
      this._raf = 0;
      const runs = this.pendingRuns || [];
      this.pendingRuns = [];
      const atEnd = this.el.scrollTop + this.el.clientHeight >= this.el.scrollHeight - 30;
      const frag = document.createDocumentFragment();
      for (const [text, kind] of runs) {
        const span = el('span', { class: `o-${kind}` });
        appendLinked(span, text);
        frag.append(span);
        this.chars += text.length;
      }
      this.out.append(frag);
      this._trim();
      if (atEnd || true) this.scrollEnd();
    }

    _trim() {
      while (this.chars > MAX_CHARS && this.out.firstChild) {
        this.chars -= this.out.firstChild.textContent.length;
        this.out.firstChild.remove();
      }
    }

    echo(code, prompt) {
      const p = prompt ?? (this.mode === 'debug' ? 'K>> ' : '>> ');
      const lines = code.split('\n');
      const span = el('span', { class: 'o-echo' });
      lines.forEach((l, i) => {
        span.append(el('span', { class: 'pl-prompt-echo' }, i === 0 ? p : ' '.repeat(p.length)), l, '\n');
      });
      this._flushNow();
      this.out.append(span);
      this.chars += code.length + p.length;
      this.scrollEnd();
    }

    _flushNow() { if (this._raf) { cancelAnimationFrame(this._raf); this._flush(); } }

    clear() {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
      this.pendingRuns = [];
      this.out.replaceChildren();
      this.chars = 0;
    }

    setBusy(on) {
      this.busy = on;
      this.el.classList.toggle('is-busy', on);
      if (!on) this._next();
    }

    setMode(mode, promptText) {
      this.mode = mode;
      this.prompt.classList.toggle('is-debug', mode === 'debug');
      this.prompt.classList.toggle('is-input', mode === 'input');
      this.prompt.textContent = mode === 'debug' ? 'K>> ' : mode === 'input' ? (promptText ?? '') : '>> ';
      if (mode === 'input' || mode === 'debug') {
        this.el.classList.remove('is-busy');
        this.focus();
      } else if (this.busy) this.el.classList.add('is-busy');
      this.scrollEnd();
    }

    /* Put text in the line (from the history, a drop, Run Section's echo). */
    setLine(text) {
      this.ta.value = text;
      this._fit();
      this.focus();
      this.ta.setSelectionRange(text.length, text.length);
    }

    insert(text) {
      const s = this.ta.selectionStart, e = this.ta.selectionEnd;
      this.ta.setRangeText(text, s, e, 'end');
      this._fit();
      this.focus();
    }

    _submit() {
      const code = this.ta.value;
      if (this.mode === 'input') {
        this.ta.value = '';
        this._fit();
        const p = this.prompt.textContent;
        this._flushNow();
        this.out.append(el('span', { class: 'o-echo' }, p, code, '\n'));
        this.emit('reply', code);
        return;
      }
      this.ta.value = '';
      this._fit();
      this.histPos = -1;
      this.enter(code);
    }

    /* A command entered as if typed (also a dropped MAT-file's load): it
       runs now, or waits its turn while a program runs. */
    enter(code) {
      if (this.busy && this.mode !== 'debug') {
        this.queue.push(code);
        this._showQueue();
        return;
      }
      this.emit('submit', code);
    }

    _showQueue() {
      this.queuedEl.hidden = !this.queue.length;
      this.queuedEl.textContent = this.queue.map((c) => `>> ${c}`).join('\n');
      this.scrollEnd();
    }

    _next() {
      if (!this.queue.length) { this._showQueue(); return; }
      const code = this.queue.shift();
      this._showQueue();
      this.emit('submit', code);
    }

    _history(dir) {
      const items = this.history.commands();
      if (this.histPos === -1) { this.histPrefix = this.ta.value; this.draft = this.ta.value; }
      let i = this.histPos === -1 ? items.length : this.histPos;
      for (;;) {
        i += dir;
        if (i < 0) return;
        if (i >= items.length) {
          this.histPos = -1;
          this.ta.value = this.draft;
          this._fit();
          return;
        }
        if (items[i].startsWith(this.histPrefix)) break;
      }
      this.histPos = i;
      this.ta.value = items[i];
      this._fit();
      const n = this.ta.value.length;
      this.ta.setSelectionRange(n, n);
    }

    _key(ev) {
      const ta = this.ta;
      if (this.completeBox) {
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); this._moveComplete(ev.key === 'ArrowDown' ? 1 : -1); return; }
        if (ev.key === 'Enter' || ev.key === 'Tab') { ev.preventDefault(); this._acceptComplete(); return; }
        if (ev.key === 'Escape') { ev.preventDefault(); this._closeComplete(); return; }
      }
      if ((ev.key === 'c' || ev.key === 'C') && ev.ctrlKey && !ev.shiftKey && !ev.altKey) {
        if (ta.selectionStart === ta.selectionEnd && !String(window.getSelection())) {
          ev.preventDefault();
          if (this.busy || this.mode === 'input') this.emit('interrupt');
          else {
            this._flushNow();
            this.out.append(el('span', { class: 'o-echo' }, this.prompt.textContent, ta.value, '\n'));
            ta.value = '';
            this._fit();
          }
          return;
        }
      }
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.altKey) {
        if (this.mode === 'input' || PL.lang.complete(ta.value) || ev.ctrlKey || ev.metaKey) {
          ev.preventDefault();
          this._submit();
          return;
        }
        // an open block: another line, indented by the blocks
        ev.preventDefault();
        const line = ta.value.slice(ta.value.lastIndexOf('\n', ta.selectionStart - 1) + 1, ta.selectionStart);
        const ind = PL.lang.nextIndent(line);
        ta.setRangeText(`\n${ind}`, ta.selectionStart, ta.selectionEnd, 'end');
        this._fit();
        this.scrollEnd();
        return;
      }
      if (ev.key === 'ArrowUp' && !ev.shiftKey && this.mode !== 'input') {
        if (!ta.value.slice(0, ta.selectionStart).includes('\n')) { ev.preventDefault(); this._history(-1); }
        return;
      }
      if (ev.key === 'ArrowDown' && !ev.shiftKey && this.mode !== 'input') {
        if (!ta.value.slice(ta.selectionEnd).includes('\n')) { ev.preventDefault(); this._history(1); }
        return;
      }
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ta.value = '';
        this._fit();
        this.histPos = -1;
        return;
      }
      if (ev.key === 'Tab' && !ev.shiftKey && this.mode !== 'input') {
        ev.preventDefault();
        this._complete();
      }
    }

    /* ---- completion --------------------------------------------------------- */
    async _complete() {
      const text = this.ta.value;
      const pos = this.ta.selectionStart;
      let res;
      try { res = await PL.app.complete(text, pos); } catch (e) { return; }
      if (!res || !res.items.length) return;
      const word = text.slice(res.start, pos);
      if (res.items.length === 1) { this._applyComplete(res.start, pos, res.items[0].label); return; }
      // the longest common start first
      const labels = res.items.map((i) => i.label);
      let common = labels[0];
      for (const l of labels) { while (!l.startsWith(common)) common = common.slice(0, -1); }
      if (common.length > word.length) { this._applyComplete(res.start, pos, common); return; }
      this._openComplete(res.start, pos, res.items);
    }

    _applyComplete(start, end, label) {
      this.ta.setRangeText(label, start, end, 'end');
      this._fit();
      this._closeComplete();
    }

    _openComplete(start, end, items) {
      this._closeComplete();
      const box = el('div', { class: 'pl-complete', role: 'listbox' });
      items.slice(0, 200).forEach((it, i) => {
        const row = el('div', { role: 'option', class: i === 0 ? 'is-sel' : '' }, el('span', { class: 'k' }, it.kind), el('span', null, it.label));
        row.addEventListener('mousedown', (ev) => { ev.preventDefault(); this._applyComplete(start, end, it.label); });
        box.append(row);
      });
      document.body.append(box);
      const r = this.ta.getBoundingClientRect();
      const lineH = parseFloat(getComputedStyle(this.ta).lineHeight) || 18;
      const lines = this.ta.value.slice(0, end).split('\n');
      const top = r.top + (lines.length) * lineH + 2;
      box.style.left = `${Math.min(r.left + 8 * (lines[lines.length - 1].length), window.innerWidth - 260)}px`;
      box.style.top = `${Math.min(top, window.innerHeight - 230)}px`;
      this.completeBox = box;
      this.completeAt = { start, end, items, sel: 0 };
    }

    _moveComplete(d) {
      const c = this.completeAt;
      const rows = this.completeBox.children;
      rows[c.sel].classList.remove('is-sel');
      c.sel = (c.sel + d + rows.length) % rows.length;
      rows[c.sel].classList.add('is-sel');
      rows[c.sel].scrollIntoView({ block: 'nearest' });
    }

    _acceptComplete() {
      const c = this.completeAt;
      this._applyComplete(c.start, c.end, c.items[c.sel].label);
    }

    _closeComplete() {
      if (this.completeBox) { this.completeBox.remove(); this.completeBox = null; }
    }
  }

  /* Text with the engine's link marks (\x01path:line\x02text\x03) as links. */
  function appendLinked(parent, text) {
    let i = 0;
    while (i < text.length) {
      const a = text.indexOf('\x01', i);
      if (a < 0) { parent.append(text.slice(i)); break; }
      parent.append(text.slice(i, a));
      const b = text.indexOf('\x02', a);
      const c = text.indexOf('\x03', b);
      if (b < 0 || c < 0) { parent.append(text.slice(a)); break; }
      const target = text.slice(a + 1, b);
      const k = target.lastIndexOf(':');
      const path = target.slice(0, k), line = target.slice(k + 1);
      const link = el('a', { href: '#', 'data-path': path, 'data-line': line }, text.slice(b + 1, c));
      if (path === 'command' || !path.startsWith('/')) parent.append(text.slice(b + 1, c));
      else parent.append(link);
      i = c + 1;
    }
  }

  PL.CommandWindow = CommandWindow;
  PL.appendLinked = appendLinked;
})(window);
