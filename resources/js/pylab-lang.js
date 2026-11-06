/* ==========================================================================
   PYLAB.HTML: THE LANGUAGE ON THE PAGE'S SIDE

   PL.lang.tokens(text)      [[class, text], ...] per line (class: k keyword,
                             s string, c comment, sc section title, w command
                             word, x shell, e unfinished string, null plain)
   PL.lang.highlight(text)   HTML of the coloured lines (one .ln per line)
   PL.lang.complete(text)    whether a command can run as typed, or Enter
                             should open another line (an open block or
                             bracket)
   PL.lang.sections(text)    the line ranges of the %% sections
   PL.lang.indent(text)      the text indented by its blocks (smart indent)
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});

  const KEYWORDS = new Set(['break', 'case', 'catch', 'classdef', 'continue', 'else', 'elseif', 'end', 'for', 'function',
    'global', 'if', 'otherwise', 'parfor', 'persistent', 'return', 'spmd', 'switch', 'try', 'while']);
  const OPENERS = new Set(['if', 'for', 'parfor', 'while', 'switch', 'try', 'function', 'spmd', 'classdef']);
  const MIDDLES = new Set(['else', 'elseif', 'case', 'otherwise', 'catch']);

  const esc = (s) => s.replace(/[&<>]/g, (c) => (c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'));

  /* Whether the line's first word starts command syntax (hold on, format
     long g): a name, a space, then a word that is not an operator followed
     by a space, an = or a (. */
  function commandWords(line) {
    const m = /^(\s*)([A-Za-z]\w*)([ \t]+)(?=\S)/.exec(line);
    if (!m) return -1;
    if (KEYWORDS.has(m[2])) return -1;
    const rest = line.slice(m[0].length);
    if (/^[=(]/.test(rest) && !/^==/.test(rest)) return -1;
    if (/^[;,%]/.test(rest) || rest.startsWith('...')) return -1;
    if (/^(==|~=|<=|>=|&&|\|\||\.\^|\.\*|\.\/|\.\\|[-+*\/\\^<>&|:])(\s|$)/.test(rest)) return -1;
    if (/^'/.test(rest)) return m[0].length;
    return m[0].length;
  }

  /* The tokens of one line, given whether a block comment is open. */
  function lineTokens(line, state) {
    const out = [];
    const t = line.trim();
    if (state.block > 0 || t === '%{') {
      if (t === '%{') state.block += 1;
      else if (t === '%}') state.block -= 1;
      out.push(['c', line]);
      return out;
    }
    if (/^\s*%%(\s|$)/.test(line)) {
      out.push(['sc', line]);
      return out;
    }
    let i = 0;
    const n = line.length;
    let prevValue = false;   // the last token ends a value (a quote after it is a transpose)
    let depth = state.depth || 0;
    const cmdAt = depth === 0 ? commandWords(line) : -1;
    if (cmdAt > 0) {
      const head = line.slice(0, cmdAt);
      const word = /\S+/.exec(head);
      out.push([null, head]);
      // the words up to a comment, a ; or a , outside quotes
      let j = cmdAt;
      let q = false;
      while (j < n) {
        const ch = line[j];
        if (q) { if (ch === "'") { if (line[j + 1] === "'") { j += 2; continue; } q = false; } j++; continue; }
        if (ch === "'") { q = true; j++; continue; }
        if (ch === '%' || ch === ';' || ch === ',') break;
        j++;
      }
      out.push(['w', line.slice(cmdAt, j)]);
      i = j;
      if (word) { /* the command's own name stays plain */ }
    }
    while (i < n) {
      const c = line[i];
      if (c === '%') { out.push(['c', line.slice(i)]); break; }
      if (line.startsWith('...', i)) { out.push(['c', line.slice(i)]); break; }
      if (c === '!' && line.slice(0, i).trim() === '') { out.push(['x', line.slice(i)]); break; }
      if (c === "'" && !prevValue) {
        let j = i + 1;
        while (j < n) {
          if (line[j] === "'") { if (line[j + 1] === "'") { j += 2; continue; } break; }
          j++;
        }
        if (j >= n) { out.push(['e', line.slice(i)]); i = n; break; }
        out.push(['s', line.slice(i, j + 1)]);
        i = j + 1;
        prevValue = true;
        continue;
      }
      if (c === '"') {
        let j = i + 1;
        while (j < n) {
          if (line[j] === '"') { if (line[j + 1] === '"') { j += 2; continue; } break; }
          j++;
        }
        if (j >= n) { out.push(['e', line.slice(i)]); i = n; break; }
        out.push(['s', line.slice(i, j + 1)]);
        i = j + 1;
        prevValue = true;
        continue;
      }
      if (/[A-Za-z]/.test(c)) {
        const m = /^[A-Za-z]\w*/.exec(line.slice(i));
        const w = m[0];
        const afterDot = i > 0 && line[i - 1] === '.';
        if (KEYWORDS.has(w) && !afterDot) {
          // `end` inside brackets is an index, not a block's end
          out.push([depth > 0 && w === 'end' ? null : 'k', w]);
          prevValue = w === 'end';
        } else {
          out.push([null, w]);
          prevValue = true;
        }
        i += w.length;
        continue;
      }
      if (/[0-9.]/.test(c) && (c !== '.' || /[0-9]/.test(line[i + 1] || ''))) {
        const m = /^(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?[ij]?/.exec(line.slice(i));
        if (m && m[0]) {
          out.push([null, m[0]]);
          i += m[0].length;
          prevValue = true;
          continue;
        }
      }
      if (c === ' ' || c === '\t') {
        let j = i;
        while (j < n && (line[j] === ' ' || line[j] === '\t')) j++;
        out.push([null, line.slice(i, j)]);
        // inside [ ] or { }, a space ends a value: a quote after it starts text
        if (depth > 0) prevValue = false;
        i = j;
        continue;
      }
      if ('([{'.includes(c)) depth += 1;
      if (')]}'.includes(c)) depth = Math.max(0, depth - 1);
      if (c === '.' && line[i + 1] === "'") { out.push([null, ".'"]); i += 2; prevValue = true; continue; }
      prevValue = ')]}'.includes(c) || (c === "'" && prevValue);
      out.push([null, c]);
      i += 1;
    }
    state.depth = depth;
    return out;
  }

  function tokens(text) {
    const state = { block: 0, depth: 0 };
    return text.split('\n').map((line) => {
      const t = lineTokens(line, state);
      // a line inside brackets goes on; outside, the depth ends with the line
      if (state.depth < 0) state.depth = 0;
      return t;
    });
  }

  function lineHtml(toks) {
    let h = '';
    for (const [cls, s] of toks) {
      if (!s) continue;
      h += cls ? `<span class="t-${cls}">${esc(s)}</span>` : esc(s);
    }
    return h;
  }

  function highlight(text) {
    const lines = tokens(text);
    return lines.map((toks) => `<span class="ln">${lineHtml(toks) || ''}</span>`).join('');
  }

  /* Whether a command is complete: no block left open and no [ or {
     open. An unclosed ( is complete (the engine reports it). */
  function complete(text) {
    const state = { block: 0, depth: 0 };
    let blocks = 0;
    let brackets = 0;
    let continued = false;
    const lines = text.split('\n');
    for (let li = 0; li < lines.length; li++) {
      const line = lines[li];
      const toks = lineTokens(line, state);
      continued = false;
      for (const [cls, s] of toks) {
        if (cls === 'k') {
          if (OPENERS.has(s)) blocks += 1;
          else if (s === 'end') blocks -= 1;
        } else if (cls === null) {
          for (const ch of s) {
            if (ch === '[' || ch === '{') brackets += 1;
            else if (ch === ']' || ch === '}') brackets -= 1;
          }
        } else if (cls === 'c' && s.startsWith('...')) {
          continued = true;
        }
      }
    }
    if (state.block > 0) return false;
    if (continued) return false;
    return blocks <= 0 && brackets <= 0;
  }

  /* Sections: [{start, end, title}] in 0-based line numbers. */
  function sections(text) {
    const lines = text.split('\n');
    const out = [];
    let start = 0;
    let title = '';
    for (let i = 0; i < lines.length; i++) {
      if (/^\s*%%(\s|$)/.test(lines[i])) {
        if (i > start || out.length) out.push({ start, end: i - 1, title });
        start = i;
        title = lines[i].replace(/^\s*%%\s?/, '');
      }
    }
    out.push({ start, end: lines.length - 1, title });
    return out.filter((s) => s.end >= s.start);
  }

  /* The indentation each line should have, from the blocks around it. */
  function indentLevels(text, unit = '    ') {
    const state = { block: 0, depth: 0 };
    const lines = text.split('\n');
    let level = 0;
    const out = [];
    const stack = [];
    for (const line of lines) {
      const toks = lineTokens(line, state);
      const words = toks.filter(([c]) => c === 'k').map(([, s]) => s);
      const first = words.length && line.trim().startsWith(words[0]) ? words[0] : null;
      let my = level;
      if (first === 'end') my = Math.max(0, level - 1);
      else if (first && MIDDLES.has(first)) my = Math.max(0, level - 1);
      if (first === 'case' || first === 'otherwise') {
        // cases sit one level inside the switch
        my = Math.max(0, level - 1);
      }
      out.push(my);
      for (const w of words) {
        if (OPENERS.has(w)) { level += 1; stack.push(w); if (w === 'switch') { level += 1; } }
        else if (w === 'end') {
          const opened = stack.pop();
          level = Math.max(0, level - 1 - (opened === 'switch' ? 1 : 0));
        }
      }
    }
    return out;
  }

  function indent(text, unit = '    ', functionsIndented = false) {
    const lines = text.split('\n');
    const levels = indentLevels(text, unit);
    const fileHasEnd = /^\s*function\b/m.test(text);
    return lines.map((l, i) => {
      const t = l.replace(/^\s+/, '');
      if (!t) return '';
      let lv = levels[i];
      return unit.repeat(lv) + t;
    }).join('\n');
  }

  /* Where a line starting with end or a block's middle (else, elseif, catch, case, otherwise) belongs, from the text
     before it: the indentation of the line that opened its block, as the file has it (a function's body indented or
     not); a case or otherwise that of the switch's first case, or one unit inside the switch. null when no block is
     open. A class's properties, methods, events and enumeration blocks and a function's arguments block count when
     they head their line. */
  function blockIndent(before, word, unit = '    ') {
    const state = { block: 0, depth: 0 };
    const stack = [];
    for (const line of before.split('\n')) {
      const inComment = state.block > 0;
      const toks = lineTokens(line, state);
      const words = toks.filter(([c]) => c === 'k').map(([, s]) => s);
      const lead = /^\s*/.exec(line)[0];
      const first = words.length && line.trim().startsWith(words[0]) ? words[0] : null;
      const top = stack[stack.length - 1];
      if ((first === 'case' || first === 'otherwise') && top && top.w === 'switch' && top.cases == null) top.cases = lead;
      if (!inComment && /^\s*(properties|methods|events|enumeration|arguments)\b\s*(\([^)]*\))?\s*(%.*)?$/.test(line)) stack.push({ w: 'section', lead });
      for (const w of words) {
        if (OPENERS.has(w)) stack.push({ w, lead });
        else if (w === 'end') stack.pop();
      }
    }
    const top = stack[stack.length - 1];
    if (!top) return null;
    if (word === 'case' || word === 'otherwise') return top.w === 'switch' ? (top.cases != null ? top.cases : top.lead + unit) : null;
    return top.lead;
  }

  /* The indentation to give a new line after `line` (Enter in the Editor). */
  function nextIndent(prevLine, unit = '    ') {
    const lead = /^\s*/.exec(prevLine)[0];
    const state = { block: 0, depth: 0 };
    const toks = lineTokens(prevLine, state);
    const words = toks.filter(([c]) => c === 'k').map(([, s]) => s);
    let delta = 0;
    for (const w of words) {
      if (OPENERS.has(w)) delta += 1;
      else if (w === 'end') delta -= 1;
    }
    const first = words.length && prevLine.trim().startsWith(words[0]) ? words[0] : null;
    if (first && MIDDLES.has(first)) delta += 1;
    if (first === 'function' && delta > 0) delta = 0;
    if (delta > 0) return lead + unit;
    if (delta < 0 && first !== 'end') return lead.slice(0, Math.max(0, lead.length - unit.length));
    return lead;
  }

  /* Python, for the compiled code view. */
  const PY_RE = /(#[^\n]*)|((?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\[\s\S]|[^"\\\n])*(?:"|$)|'(?:\\[\s\S]|[^'\\\n])*(?:'|$)))|([A-Za-z_]\w*)|(\s+)|([\s\S])/y;
  const PY_KW = new Set(['False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del',
    'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass',
    'raise', 'return', 'try', 'while', 'with', 'yield']);

  function highlightPython(src) {
    PY_RE.lastIndex = 0;
    let html = '<span class="ln">';
    let m;
    const add = (cls, text) => {
      const parts = text.split('\n');
      parts.forEach((p, i) => {
        if (i > 0) html += '</span><span class="ln">';
        if (p) html += cls ? `<span class="${cls}">${esc(p)}</span>` : esc(p);
      });
    };
    while (PY_RE.lastIndex < src.length && (m = PY_RE.exec(src))) {
      if (m[1]) add('t-py-c', m[1]);
      else if (m[2]) add('t-py-s', m[2]);
      else if (m[3]) add(PY_KW.has(m[3]) ? 't-py-k' : null, m[3]);
      else add(null, m[4] || m[5]);
    }
    return `${html}</span>`;
  }

  PL.lang = { tokens, lineTokens, highlight, lineHtml, complete, sections, indent, indentLevels, blockIndent, nextIndent, highlightPython, KEYWORDS, esc };
})(window);
