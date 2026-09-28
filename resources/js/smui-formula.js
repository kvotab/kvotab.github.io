/* ==========================================================================
   SMUI.HTML: FORMULAS (Cols > Formula)

   The formula language of formula columns, JMP's in its names and in how
   it treats missing values. A formula is made of

     column references   :height   :"weight (kg)"   :Name("weight (kg)")
                         or a bare name that is a column (height)
     values              3.5   1e-3   "text"   . (a missing number)
     operators, loosest first
         |              or
         &              and
         == != < <= > >=   comparisons; chained, 1 < :x <= 3
         ||             joins text
         + -
         * /            (division by zero is missing)
         - !            negation, not
         ^              power, right to left (-2^2 is -4, as in JMP)
         :x[i]          the value of :x in row i
     functions           by their JMP names, in any case, with or without
                         the spaces: If, Match, Is Missing, Sum, Mean,
                         Col Mean(:x, :group), Lag, Row, Char, Word, Year,
                         Date MDY, Random Normal ... (SM.formula.functions)

   Missing values as in JMP: arithmetic with a missing value is missing, a
   comparison with a missing number is missing, If with a missing condition
   is missing, & and | use three-valued logic (0 & . is 0, 1 & . is
   missing, 1 | . is 1), and Sum, Mean, Min, Max and Std Dev of their
   arguments skip the missing ones. Text has no missing value other than
   the empty text.

   A formula is text read by the tokenizer and recursive-descent parser
   below and run as a tree of closures, compiled once and then looped over
   the rows: never eval, never new Function, and no name reaches anything
   of JavaScript's. A formula from someone else's file cannot run code.

   Formula columns keep themselves current. column.formula is
   { expr, refs, seed }: the text, the ids of the columns it uses and the
   seed of its random numbers (so a formula of Random Normal() gives the
   same column every time). When cells of a used column change, the formula
   columns that depend on them are computed again, in dependency order;
   row order matters to Row(), Lag() and the like, so sorting recomputes
   those; a renamed column is renamed in the formulas that use it; a
   formula that would use itself, directly or through others, is refused.

     SM.formula.parse(expr)                  the syntax tree, or a FormulaError
     SM.formula.compile(ast, table)          { f(row), type, refs, ... }
     SM.formula.evaluate(table, expr, rows)  the values (with .dataType)
     SM.formula.apply(table, column, expr)   make a column a formula column
     SM.formula.edit(table, column)          the formula editor
     SM.formula.recalc(table)                compute every formula column
     SM.formula.functions                    the functions, for the palette
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});

  const MAX_LEN = 50000;      // characters in a formula
  const MAX_DEPTH = 160;      // nesting of parentheses and calls
  const MAX_TEXT = 1000000;   // characters in one computed text value
  const DAY = 86400000;

  class FormulaError extends Error {
    constructor(reason, pos = null, end = null) {
      super(pos == null ? reason : `${reason} (at character ${pos + 1})`);
      this.name = 'FormulaError';
      this.reason = reason;
      this.pos = pos;
      this.end = end == null ? (pos == null ? null : pos + 1) : end;
    }
  }

  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const isStart = (ch) => ch != null && /[\p{L}_]/u.test(ch);
  const isWord = (ch) => ch != null && /[\p{L}\p{N}_]/u.test(ch);
  const fnKey = (name) => String(name).toLowerCase().replace(/[\s_]+/g, '');

  /* ---- tokens ---------------------------------------------------------------- */
  const OPS = ['<<', '<=', '>=', '==', '!=', '&&', '||', '**', '<', '>', '=', '&', '|', '!', '+', '-', '*', '/', '^', '(', ')', ',', '[', ']', ';',
    '−', '–', '×', '·', '÷', '≤', '≥', '≠'];
  const OP_ALIAS = { '=': '==', '&&': '&', '**': '^', '−': '-', '–': '-', '×': '*', '·': '*', '÷': '/', '≤': '<=', '≥': '>=', '≠': '!=' };
  const ESC = { '"': '"', '\'': '\'', '\\': '\\', n: '\n', t: '\t', r: '\r' };
  const JMP_ESC = { '"': '"', '\\': '\\', t: '\t', n: '\n', N: '\n', r: '\r', b: ' ', f: '\f', 0: '' };

  function readString(src, i) {
    const q = src[i];
    let s = '';
    let j = i + 1;
    while (j < src.length) {
      const c = src[j];
      if (c === q) return [s, j + 1];
      if (c === '\\') {
        const d = src[j + 1];
        if (d === '!' && hasOwn(JMP_ESC, src[j + 2])) { s += JMP_ESC[src[j + 2]]; j += 3; continue; }
        if (d != null && hasOwn(ESC, d)) { s += ESC[d]; j += 2; continue; }
      }
      s += c;
      j++;
    }
    throw new FormulaError('a text in quotes is not closed', i, src.length);
  }

  // Words joined by spaces make one name: JMP ignores the spaces in names
  // (Col Mean is ColMean), and a column name may have spaces.
  function readWords(src, i) {
    const n = src.length;
    const words = [];
    let j = i;
    for (;;) {
      let w = j;
      while (w < n && isWord(src[w])) w++;
      words.push(src.slice(j, w));
      let s = w;
      while (s < n && (src[s] === ' ' || src[s] === '\t')) s++;
      if (s > w && s < n && isStart(src[s])) { j = s; continue; }
      return [words.join(' '), w];
    }
  }

  function tokenize(src) {
    const toks = [];
    const n = src.length;
    const push = (type, value, pos, end) => toks.push({ type, value, pos, end });
    let i = 0;
    while (i < n) {
      const ch = src[i];
      if (/\s/.test(ch)) { i++; continue; }
      if (ch === '/' && src[i + 1] === '/') { while (i < n && src[i] !== '\n') i++; continue; }
      if (ch === '/' && src[i + 1] === '*') {
        const j = src.indexOf('*/', i + 2);
        if (j < 0) throw new FormulaError('a comment is not closed', i, n);
        i = j + 2;
        continue;
      }
      const start = i;
      if (/[0-9]/.test(ch) || (ch === '.' && /[0-9]/.test(src[i + 1] || ''))) {
        const m = /^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?/.exec(src.slice(i, i + 400));
        i += m[0].length;
        if (i < n && isWord(src[i])) {
          let j = i;
          while (j < n && isWord(src[j])) j++;
          throw new FormulaError(`“${src.slice(start, j)}” is neither a number nor a name`, start, j);
        }
        push('num', Number(m[0]), start, i);
        continue;
      }
      if (ch === '.') { push('miss', null, start, i + 1); i++; continue; }
      if (ch === '"' || ch === '\'') {
        const [s, j] = readString(src, i);
        push('str', s, start, j);
        i = j;
        continue;
      }
      if (ch === ':') {
        if (src[i + 1] === ':') throw new FormulaError('“::” is not part of a formula; a column is :name', i, i + 2);
        let j = i + 1;
        while (j < n && (src[j] === ' ' || src[j] === '\t')) j++;
        if (src[j] === '"' || src[j] === '\'') {
          const [s, e] = readString(src, j);
          let end = e;
          if (src[end] === 'n' && !isWord(src[end + 1])) end++;   // JMP's :"name"n
          push('col', s, start, end);
          i = end;
          continue;
        }
        if (isStart(src[j])) {
          const [name, e] = readWords(src, j);
          // JMP's older :Name("weight (kg)")
          if (/^name$/i.test(name)) {
            let k = e;
            while (k < n && /\s/.test(src[k])) k++;
            if (src[k] === '(') {
              k++;
              while (k < n && /\s/.test(src[k])) k++;
              if (src[k] === '"' || src[k] === '\'') {
                const [s, e2] = readString(src, k);
                let k2 = e2;
                while (k2 < n && /\s/.test(src[k2])) k2++;
                if (src[k2] === ')') { push('col', s, start, k2 + 1); i = k2 + 1; continue; }
              }
              throw new FormulaError(':Name( ) takes a column name in quotes', start, k);
            }
          }
          push('col', name, start, e);
          i = e;
          continue;
        }
        throw new FormulaError('a column name must follow the colon, like :height or :"weight (kg)"', i, i + 1);
      }
      if (isStart(ch)) {
        const [name, e] = readWords(src, i);
        push('name', name, start, e);
        i = e;
        continue;
      }
      const op = OPS.find((o) => src.startsWith(o, i));
      if (op) {
        push('op', OP_ALIAS[op] || op, start, i + op.length);
        i += op.length;
        continue;
      }
      throw new FormulaError(`“${ch}” is not part of a formula`, i, i + 1);
    }
    push('eof', null, n, n);
    return toks;
  }

  /* ---- the parser ------------------------------------------------------------ */
  const CMP = new Set(['==', '!=', '<', '<=', '>', '>=']);

  function parse(src) {
    if (typeof src !== 'string') throw new FormulaError('a formula is text');
    if (src.length > MAX_LEN) throw new FormulaError(`the formula is too long: ${src.length} characters, at most ${MAX_LEN}`);
    if (!src.trim()) throw new FormulaError('the formula is empty');
    const toks = tokenize(src);
    let k = 0;
    let depth = 0;
    const peek = () => toks[k];
    const take = () => toks[k++];
    const at = (v) => toks[k].type === 'op' && toks[k].value === v;
    const fail = (msg, t) => new FormulaError(msg, t.pos, Math.max(t.end, t.pos + 1));
    const what = (t) => {
      if (t.type === 'eof') return 'the end of the formula';
      if (t.type === 'num') return `the number ${src.slice(t.pos, t.end)}`;
      if (t.type === 'str') return 'a text in quotes';
      if (t.type === 'name') return `“${t.value}”`;
      if (t.type === 'col') return `the column ${src.slice(t.pos, t.end)}`;
      if (t.type === 'miss') return 'a missing value (.)';
      return `“${t.value}”`;
    };
    const enter = (t) => { if (++depth > MAX_DEPTH) throw fail('the formula is nested too deeply', t); };
    const leave = () => { depth--; };

    const expr = () => or();
    const binary = (next, ops) => () => {
      let a = next();
      while (toks[k].type === 'op' && ops.includes(toks[k].value)) {
        const t = take();
        enter(t);
        const b = next();
        leave();
        a = { k: 'bin', op: t.value, a, b, pos: a.pos, end: b.end, opPos: t.pos, opEnd: t.end };
      }
      return a;
    };
    function cmp() {
      const first = concat();
      if (!(toks[k].type === 'op' && CMP.has(toks[k].value))) return first;
      const args = [first], ops = [];
      while (toks[k].type === 'op' && CMP.has(toks[k].value)) {
        const t = take();
        ops.push({ op: t.value, pos: t.pos, end: t.end });
        args.push(concat());
      }
      return { k: 'cmp', ops, args, pos: first.pos, end: args[args.length - 1].end };
    }
    function unary() {
      const t = peek();
      if (t.type === 'op' && (t.value === '-' || t.value === '+' || t.value === '!')) {
        take();
        enter(t);
        const a = unary();
        leave();
        if (t.value === '+') return a;
        if (t.value === '-' && a.k === 'num') return { k: 'num', v: -a.v, pos: t.pos, end: a.end };
        return { k: 'un', op: t.value, a, pos: t.pos, end: a.end };
      }
      return power();
    }
    function power() {
      const a = postfix();
      if (at('^')) {
        const t = take();
        enter(t);
        const b = unary();
        leave();
        return { k: 'bin', op: '^', a, b, pos: a.pos, end: b.end, opPos: t.pos, opEnd: t.end };
      }
      return a;
    }
    function postfix() {
      let a = primary();
      while (at('[')) {
        const t = take();
        if (a.k !== 'col') throw fail('only a column takes a row subscript, like :x[Row() - 1]', t);
        enter(t);
        const i = expr();
        leave();
        if (!at(']')) throw fail(`expected “]” to close the row subscript, found ${what(peek())}`, peek());
        const e = take();
        a = { k: 'idx', a, i, pos: a.pos, end: e.end };
      }
      return a;
    }
    function primary() {
      const t = peek();
      if (t.type === 'num') { take(); return { k: 'num', v: t.value, pos: t.pos, end: t.end }; }
      if (t.type === 'str') { take(); return { k: 'str', v: t.value, pos: t.pos, end: t.end }; }
      if (t.type === 'miss') { take(); return { k: 'miss', pos: t.pos, end: t.end }; }
      if (t.type === 'col') { take(); return { k: 'col', name: t.value, bare: false, pos: t.pos, end: t.end }; }
      if (t.type === 'name') {
        take();
        if (at('(')) return call(t);
        return { k: 'col', name: t.value, bare: true, pos: t.pos, end: t.end };
      }
      if (t.type === 'op' && t.value === '(') {
        take();
        enter(t);
        const e = expr();
        leave();
        if (!at(')')) throw fail(`expected “)” to close the “(” at character ${t.pos + 1}, found ${what(peek())}`, peek());
        take();
        return e;
      }
      throw fail(`expected a value, a column or a function, found ${what(t)}`, t);
    }
    function argList(open, label) {
      const args = [], named = new Map();
      if (!at(')')) {
        for (;;) {
          if (at('<<')) {
            const lt = take();
            const nm = peek();
            if (nm.type !== 'name') throw fail('an option name must follow “<<”', nm);
            take();
            let nargs = [];
            let end = nm.end;
            if (at('(')) {
              const o2 = take();
              enter(o2);
              nargs = argList(o2, nm.value).args;
              leave();
              end = toks[k - 1].end;
            }
            named.set(fnKey(nm.value), { name: nm.value, args: nargs, pos: lt.pos, end });
          } else args.push(expr());
          if (at(',')) { take(); continue; }
          break;
        }
      }
      if (!at(')')) throw fail(`expected “,” or “)” in ${label}( ), found ${what(peek())}`, peek());
      take();
      return { args, named };
    }
    function call(nameTok) {
      const open = take();
      enter(open);
      const key = fnKey(nameTok.value);
      if (key === 'column' || key === 'ascolumn') {
        const { args } = argList(open, nameTok.value);
        leave();
        const end = toks[k - 1].end;
        if (args.length !== 1 || args[0].k !== 'str') throw new FormulaError(`${nameTok.value}( ) takes a column name in quotes`, nameTok.pos, end);
        return { k: 'col', name: args[0].v, bare: false, pos: nameTok.pos, end };
      }
      const def = FN.get(key);
      if (!def) throw new FormulaError(`there is no function “${nameTok.value}”`, nameTok.pos, nameTok.end);
      const { args, named } = argList(open, def.name);
      leave();
      const end = toks[k - 1].end;
      if (args.length < def.min) throw new FormulaError(`${def.name} needs ${def.max === def.min ? '' : 'at least '}${def.min} argument${def.min === 1 ? '' : 's'}`, nameTok.pos, end);
      if (def.max != null && args.length > def.max) throw new FormulaError(`${def.name} takes ${def.max === 0 ? 'no arguments' : `at most ${def.max} argument${def.max === 1 ? '' : 's'}`}`, nameTok.pos, end);
      for (const [nk, nv] of named) if (!(def.named || []).includes(nk)) throw new FormulaError(`${def.name} has no option ${nv.name}`, nv.pos, nv.end);
      return { k: 'call', fn: key, name: def.name, args, named, pos: nameTok.pos, end };
    }

    const or = binary(() => and(), ['|']);
    const and = binary(() => cmp(), ['&']);
    const concat = binary(() => add(), ['||']);
    const add = binary(() => mul(), ['+', '-']);
    const mul = binary(() => unary(), ['*', '/']);

    const ast = expr();
    while (at(';')) take();
    if (peek().type !== 'eof') {
      const t = peek();
      const hint = t.type === 'name' || t.type === 'col' ? ' (is an operator or a comma missing?)' : '';
      throw fail(`did not expect ${what(t)} here${hint}`, t);
    }
    return ast;
  }

  /* ---- values -------------------------------------------------------------------- */
  const isMiss = (v) => v == null || v === '' || v !== v;

  /* A number as JMP's Char() writes it: integers as integers, others to 15
     significant digits without trailing zeros. */
  function charOf(v) {
    if (typeof v !== 'number') return v == null ? '' : String(v);
    if (v !== v) return '.';
    if (Number.isInteger(v) && Math.abs(v) < 1e21) return String(v);
    return String(Number(v.toPrecision(15)));
  }

  const toStr = (v) => (typeof v === 'string' ? v : v == null ? '' : typeof v === 'number' ? (v !== v ? '' : charOf(v)) : String(v));
  const toNum = (v) => (typeof v === 'number' ? v : NaN);
  const fin = (x) => (Number.isFinite(x) ? x : NaN);
  const cap = (s) => { if (s.length > MAX_TEXT) throw new FormulaError(`a computed text is longer than ${MAX_TEXT} characters`); return s; };

  function roundTo(x, n) {
    if (x !== x || n !== n) return NaN;
    n = Math.trunc(n);
    if (!Number.isFinite(x) || n > 20) return x;
    const a = Math.abs(x);
    const m = 10 ** Math.abs(n);
    const y = n >= 0 ? a * m : a / m;
    const fl = Math.floor(y);
    let r;
    if (Math.abs(y - fl - 0.5) > 1e-6) r = y - fl < 0.5 ? fl : fl + 1;
    else {
      // Near a half: round the decimal digits, not the binary value, so that
      // Round(3.555, 2) is 3.56 as in JMP.
      const s = String(a);
      r = s.includes('e') ? Math.round(y) : Math.round(Number(`${s}e${n}`));
    }
    r = n >= 0 ? r / m : r * m;
    return x < 0 ? -r : r;
  }

  /* The normal distribution: Marsaglia's series in the middle, the Laplace
     continued fraction in the tails; about 15 correct digits. */
  const LN_SQRT_2PI = 0.91893853320467274178;
  function pnorm(z) {
    if (z !== z) return NaN;
    if (z === Infinity) return 1;
    if (z === -Infinity) return 0;
    const a = Math.abs(z);
    if (a < 5) {
      let s = z, t = 0, b = z, i = 1;
      const q = z * z;
      while (s !== t) { t = s; i += 2; b *= q / i; s = t + b; }
      return 0.5 + s * Math.exp(-0.5 * q - LN_SQRT_2PI);
    }
    let cf = a;
    for (let j = 80; j >= 1; j--) cf = a + j / cf;
    const tail = Math.exp(-0.5 * a * a - LN_SQRT_2PI) / cf;
    return z > 0 ? 1 - tail : tail;
  }
  const dnorm = (z) => Math.exp(-0.5 * z * z - LN_SQRT_2PI);
  function qnorm(p) {
    if (!(p > 0 && p < 1)) return p === 0 ? -Infinity : p === 1 ? Infinity : NaN;
    let x = SM.util && SM.util.qnorm ? SM.util.qnorm(p) : 0;
    // one Halley step on the accurate distribution function
    const e = pnorm(x) - p;
    const u = e / dnorm(x);
    x -= u / (1 + x * u / 2);
    return x;
  }

  /* JMP's quantiles (numpy's 'weibull'): the (n+1)p-th order statistic. */
  function quantileSorted(s, p) {
    const n = s.length;
    if (!n || p !== p) return NaN;
    const h = (n + 1) * p;
    if (h <= 1) return s[0];
    if (h >= n) return s[n - 1];
    const lo = Math.floor(h);
    return s[lo - 1] + (h - lo) * (s[lo] - s[lo - 1]);
  }

  /* ---- compiling -------------------------------------------------------------------- */
  function describe(node) {
    if (node.k === 'col') return `:${node.name}`;
    if (node.k === 'str') return `"${node.v.length > 20 ? `${node.v.slice(0, 20)}…` : node.v}"`;
    if (node.k === 'call') return `${node.name}( )`;
    return 'this';
  }

  function needNum(c, node, what) {
    if (c.t === 'str') throw new FormulaError(`${what} needs a number, and ${describe(node)} is text`, node.pos, node.end);
  }

  const numF = (c) => (c.t === 'num' ? c.f : ((f) => (r) => toNum(f(r)))(c.f));
  const strF = (c) => ((f) => (c.t === 'str' ? (r) => { const v = f(r); return v == null ? '' : v; } : (r) => toStr(f(r))))(c.f);

  // true, false, or null for missing
  function truthF(c, node, what) {
    if (c.t === 'str') throw new FormulaError(`${what} needs a number (nonzero is true), and ${describe(node)} is text`, node.pos, node.end);
    const f = c.f;
    if (c.t === 'num') return (r) => { const v = f(r); return v !== v ? null : v !== 0; };
    return (r) => { const v = f(r); if (typeof v === 'number') return v !== v ? null : v !== 0; return v == null || v === '' ? null : true; };
  }

  function unify(list) {
    const ts = list.filter((x) => !x.miss).map((x) => x.t);
    if (!ts.length) return 'num';
    if (ts.every((t) => t === 'num')) return 'num';
    if (ts.every((t) => t === 'str')) return 'str';
    return 'any';
  }
  // A missing literal among text results is the empty text.
  const resultF = (x, t) => (x.miss && t === 'str' ? () => null : x.f);
  const missOf = (t) => (t === 'str' ? null : NaN);

  function resolveColumn(table, name, bare) {
    const cols = table.columns;
    let c = cols.find((x) => x.name === name);
    if (c) return c;
    const norm = (s) => String(s).toLowerCase().replace(/\s+/g, ' ').trim();
    const want = norm(name);
    c = cols.find((x) => norm(x.name) === want);
    if (c) return c;
    if (bare) {
      const tight = want.replace(/ /g, '');
      c = cols.find((x) => norm(x.name).replace(/ /g, '') === tight);
    }
    return c || null;
  }

  function comp(node, env) {
    switch (node.k) {
      case 'num': { const v = node.v; return { f: () => v, t: 'num', konst: true, v }; }
      case 'str': { const v = node.v; return { f: () => v, t: 'str', konst: true, v }; }
      case 'miss': return { f: () => NaN, t: 'num', miss: true, konst: true, v: NaN };
      case 'col': {
        const col = resolveColumn(env.table, node.name, node.bare);
        if (!col) {
          throw new FormulaError(node.bare ? `there is no column or name “${node.name}” (a column is written :name, a function Name( ))` : `there is no column “${node.name}”`, node.pos, node.end);
        }
        if (env.self && col === env.self) throw new FormulaError(`a formula cannot use its own column, ${col.name}`, node.pos, node.end);
        env.refs.add(col.id);
        env.nodes.push({ pos: node.pos, end: node.end, id: col.id });
        const date = col.isNumeric && !!(col.format && /date/.test(col.format.kind || ''));
        return { f: (r) => col.values[r], t: col.isNumeric ? 'num' : 'str', date, col };
      }
      case 'idx': {
        const c = comp(node.a, env);
        const i = comp(node.i, env);
        needNum(i, node.i, 'A row subscript');
        env.rowDep = true;
        const col = c.col;
        const fi = numF(i);
        const miss = col.isNumeric ? NaN : null;
        return { f: (r) => { const j = Math.round(fi(r)); return j >= 1 && j <= env.table.nrows ? col.values[j - 1] : miss; }, t: c.t, date: c.date };
      }
      case 'un': {
        const a = comp(node.a, env);
        if (node.op === '-') {
          needNum(a, node.a, 'Negation');
          const f = numF(a);
          return { f: (r) => -f(r), t: 'num' };
        }
        const tf = truthF(a, node.a, 'Not (!)');
        return { f: (r) => { const x = tf(r); return x === null ? NaN : x ? 0 : 1; }, t: 'num' };
      }
      case 'bin': return binaryOp(node, env);
      case 'cmp': return compare(node, env);
      case 'call': return FN.get(node.fn).build(node, env);
      default: throw new FormulaError('an unknown part of a formula', node.pos, node.end);
    }
  }

  const OPNAME = { '+': 'Addition (+)', '-': 'Subtraction (−)', '*': 'Multiplication (*)', '/': 'Division (/)', '^': 'Power (^)' };

  function binaryOp(node, env) {
    const { op } = node;
    const a = comp(node.a, env), b = comp(node.b, env);
    if (op === '||') {
      const fa = strF(a), fb = strF(b);
      return { f: (r) => cap(fa(r) + fb(r)), t: 'str' };
    }
    if (op === '&' || op === '|') {
      const ta = truthF(a, node.a, op === '&' ? 'And (&)' : 'Or (|)'), tb = truthF(b, node.b, op === '&' ? 'And (&)' : 'Or (|)');
      if (op === '&') return { f: (r) => { const x = ta(r); if (x === false) return 0; const y = tb(r); if (y === false) return 0; return x === null || y === null ? NaN : 1; }, t: 'num' };
      return { f: (r) => { const x = ta(r); if (x === true) return 1; const y = tb(r); if (y === true) return 1; return x === null || y === null ? NaN : 0; }, t: 'num' };
    }
    needNum(a, node.a, OPNAME[op]);
    needNum(b, node.b, OPNAME[op]);
    const fa = numF(a), fb = numF(b);
    let f;
    let date = false;
    if (op === '+') { f = (r) => fa(r) + fb(r); date = !!a.date !== !!b.date; }
    else if (op === '-') { f = (r) => fa(r) - fb(r); date = !!a.date && !b.date; }
    else if (op === '*') f = (r) => fa(r) * fb(r);
    else if (op === '/') f = (r) => { const x = fa(r), y = fb(r); return y === 0 ? NaN : x / y; };
    else f = (r) => { const x = fa(r), y = fb(r); return x !== x || y !== y ? NaN : fin(Math.pow(x, y)); };
    if (a.konst && b.konst) { const v = f(0); return { f: () => v, t: 'num', konst: true, v, date }; }
    return { f, t: 'num', date };
  }

  function cmpVal(op, x, y) {
    const nx = typeof x === 'number', ny = typeof y === 'number';
    if (nx && ny) {
      if (x !== x || y !== y) return NaN;
    } else if (nx || ny) {
      // a number against text: only possible when a type is known at run time
      if ((nx && x !== x) || (ny && y !== y)) return NaN;
      return op === '==' ? 0 : op === '!=' ? 1 : NaN;
    } else {
      x = x == null ? '' : x;
      y = y == null ? '' : y;
    }
    switch (op) {
      case '==': return x === y ? 1 : 0;
      case '!=': return x !== y ? 1 : 0;
      case '<': return x < y ? 1 : 0;
      case '<=': return x <= y ? 1 : 0;
      case '>': return x > y ? 1 : 0;
      default: return x >= y ? 1 : 0;
    }
  }

  function compare(node, env) {
    const parts = node.args.map((x) => comp(x, env));
    for (let i = 0; i < node.ops.length; i++) {
      const a = parts[i], b = parts[i + 1];
      if (a.miss || b.miss) continue;
      if (a.t !== 'any' && b.t !== 'any' && a.t !== b.t) {
        const o = node.ops[i];
        throw new FormulaError(`“${o.op}” compares a number with text: ${describe(a.t === 'str' ? node.args[i] : node.args[i + 1])} is text`, o.pos, o.end);
      }
    }
    const fs = parts.map((p) => p.f);
    const ops = node.ops.map((o) => o.op);
    if (fs.length === 2) {
      const [fa, fb] = fs;
      const o = ops[0];
      return { f: (r) => cmpVal(o, fa(r), fb(r)), t: 'num' };
    }
    return {
      f: (r) => {
        let prev = fs[0](r);
        let res = 1;
        for (let i = 0; i < ops.length; i++) {
          const cur = fs[i + 1](r);
          const v = cmpVal(ops[i], prev, cur);
          if (v === 0) return 0;
          if (v !== v) res = NaN;
          prev = cur;
        }
        return res;
      },
      t: 'num',
    };
  }

  /* ---- the functions ---------------------------------------------------------------- */
  const FN = new Map();
  const DOCS = [];

  /* Register a function under its names: the first is the one shown. */
  function def(names, cat, args, about, min, max, build, extra = {}) {
    const list = Array.isArray(names) ? names : [names];
    const d = { name: list[0], cat, args, about, min, max, build, aliases: list.slice(1), ...extra };
    for (const n of list) FN.set(fnKey(n), d);
    DOCS.push(d);
  }

  const compArgs = (node, env) => node.args.map((a) => comp(a, env));
  const optNum = (c, dflt) => (c ? numF(c) : () => dflt);

  function math1(fn) {
    return (node, env) => {
      const [a] = compArgs(node, env);
      needNum(a, node.args[0], node.name);
      const f = numF(a);
      if (a.konst) { const v = fin(fn(f(0))); return { f: () => v, t: 'num', konst: true, v }; }
      return { f: (r) => fin(fn(f(r))), t: 'num' };
    };
  }

  function rowwise(kind) {
    return (node, env) => {
      const cs = compArgs(node, env);
      const counting = kind === 'number' || kind === 'nmissing';
      if (!counting) cs.forEach((c, i) => needNum(c, node.args[i], node.name));
      const fs = counting ? cs.map((c) => c.f) : cs.map(numF);
      const m = fs.length;
      let f;
      if (kind === 'number') f = (r) => { let k = 0; for (let i = 0; i < m; i++) if (!isMiss(fs[i](r))) k++; return k; };
      else if (kind === 'nmissing') f = (r) => { let k = 0; for (let i = 0; i < m; i++) if (isMiss(fs[i](r))) k++; return k; };
      else if (kind === 'sum') f = (r) => { let s = 0, k = 0; for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) { s += v; k++; } } return k ? s : NaN; };
      else if (kind === 'mean') f = (r) => { let s = 0, k = 0; for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) { s += v; k++; } } return k ? s / k : NaN; };
      else if (kind === 'min') f = (r) => { let s = Infinity, k = 0; for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) { if (v < s) s = v; k++; } } return k ? s : NaN; };
      else if (kind === 'max') f = (r) => { let s = -Infinity, k = 0; for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) { if (v > s) s = v; k++; } } return k ? s : NaN; };
      else if (kind === 'sd') {
        f = (r) => {
          let s = 0, k = 0;
          const vals = [];
          for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) { s += v; k++; vals.push(v); } }
          if (k < 2) return NaN;
          const mean = s / k;
          let ss = 0;
          for (const v of vals) ss += (v - mean) * (v - mean);
          return Math.sqrt(ss / (k - 1));
        };
      } else {
        f = (r) => { const vals = []; for (let i = 0; i < m; i++) { const v = fs[i](r); if (v === v) vals.push(v); } vals.sort((x, y) => x - y); return quantileSorted(vals, 0.5); };
      }
      const date = kind === 'min' || kind === 'max' || kind === 'mean' || kind === 'median' ? cs.every((c) => c.date) : false;
      return { f, t: 'num', date };
    };
  }

  /* Groups for the Col functions' By arguments: a group number per row. */
  function grouping(by, env) {
    const n = env.table.nrows;
    const g = new Int32Array(n);
    if (!by.length) return { g, ng: 1 };
    const map = new Map();
    if (by.length === 1) {
      const f = by[0].f;
      for (let r = 0; r < n; r++) {
        let v = f(r);
        if (v == null) v = '';
        let id = map.get(v);
        if (id === undefined) { id = map.size; map.set(v, id); }
        g[r] = id;
      }
    } else {
      const fs = by.map((c) => c.f);
      for (let r = 0; r < n; r++) {
        let key = '';
        for (const f of fs) { const v = f(r); key += `${typeof v === 'number' ? 'n' : 's'}${v == null ? '' : v}\u0001`; }
        let id = map.get(key);
        if (id === undefined) { id = map.size; map.set(key, id); }
        g[r] = id;
      }
    }
    return { g, ng: map.size };
  }

  const less = (x, y) => (x < y ? -1 : x > y ? 1 : 0);

  /* The Col functions: a statistic of the whole column (or of the rows in
     the current row's By group), computed once per evaluation. Every row is
     used, as in JMP; missing values are skipped. */
  function colStat(kind) {
    const textOk = kind === 'number' || kind === 'nmissing' || kind === 'mode' || kind === 'rank';
    const perRow = kind === 'rank' || kind === 'cumsum' || kind === 'standardize';
    return (node, env) => {
      const a = comp(node.args[0], env);
      if (!textOk) needNum(a, node.args[0], node.name);
      let pC = null, byFrom = 1;
      if (kind === 'quantile') { pC = comp(node.args[1], env); needNum(pC, node.args[1], `${node.name}'s probability`); byFrom = 2; }
      const by = node.args.slice(byFrom).map((x) => comp(x, env));
      let tie = 'arbitrary';
      if (kind === 'rank' && node.named.has('tie')) {
        const t = node.named.get('tie');
        const arg = t.args[0];
        if (!arg || arg.k !== 'str' || !['average', 'arbitrary', 'row', 'minimum', 'maximum'].includes(arg.v.toLowerCase())) throw new FormulaError('<<Tie takes "average", "arbitrary", "row", "minimum" or "maximum"', t.pos, t.end);
        tie = arg.v.toLowerCase();
      }
      env.agg = true;
      if (kind === 'rank' || kind === 'cumsum') env.rowDep = true;
      const fa = textOk ? a.f : numF(a);
      const fp = pC ? numF(pC) : null;
      let cache = null;
      const prepare = () => {
        const n = env.table.nrows;
        const { g, ng } = grouping(by, env);
        const x = new Array(n);
        for (let r = 0; r < n; r++) x[r] = fa(r);
        if (perRow) {
          const out = new Array(n).fill(NaN);
          if (kind === 'cumsum') {
            const acc = new Float64Array(ng);
            for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { acc[g[r]] += v; out[r] = acc[g[r]]; } }
          } else if (kind === 'standardize') {
            const s = new Float64Array(ng), k = new Float64Array(ng), ss = new Float64Array(ng);
            for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { s[g[r]] += v; k[g[r]]++; } }
            for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { const d = v - s[g[r]] / k[g[r]]; ss[g[r]] += d * d; } }
            for (let r = 0; r < n; r++) {
              const v = x[r], j = g[r];
              if (v !== v || k[j] < 2) continue;
              const sd = Math.sqrt(ss[j] / (k[j] - 1));
              out[r] = sd > 0 ? (v - s[j] / k[j]) / sd : NaN;
            }
          } else {
            const members = Array.from({ length: ng }, () => []);
            for (let r = 0; r < n; r++) if (!isMiss(x[r])) members[g[r]].push(r);
            for (const rows of members) {
              rows.sort((p, q) => less(x[p], x[q]) || p - q);
              for (let i = 0; i < rows.length;) {
                let j = i;
                while (j + 1 < rows.length && x[rows[j + 1]] === x[rows[i]]) j++;
                for (let m = i; m <= j; m++) {
                  out[rows[m]] = tie === 'average' ? (i + j) / 2 + 1 : tie === 'minimum' ? i + 1 : tie === 'maximum' ? j + 1 : m + 1;
                }
                i = j + 1;
              }
            }
          }
          cache = { perRow: out };
          return;
        }
        const res = new Array(ng).fill(NaN);
        if (kind === 'number' || kind === 'nmissing') {
          const k = new Float64Array(ng);
          for (let r = 0; r < n; r++) if (isMiss(x[r]) === (kind === 'nmissing')) k[g[r]]++;
          for (let j = 0; j < ng; j++) res[j] = k[j];
        } else if (kind === 'sum' || kind === 'mean') {
          const s = new Float64Array(ng), k = new Float64Array(ng);
          for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { s[g[r]] += v; k[g[r]]++; } }
          for (let j = 0; j < ng; j++) res[j] = k[j] ? (kind === 'sum' ? s[j] : s[j] / k[j]) : NaN;
        } else if (kind === 'sd') {
          const s = new Float64Array(ng), k = new Float64Array(ng), ss = new Float64Array(ng);
          for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { s[g[r]] += v; k[g[r]]++; } }
          for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) { const d = v - s[g[r]] / k[g[r]]; ss[g[r]] += d * d; } }
          for (let j = 0; j < ng; j++) res[j] = k[j] > 1 ? Math.sqrt(ss[j] / (k[j] - 1)) : NaN;
        } else if (kind === 'min' || kind === 'max') {
          const big = kind === 'max';
          for (let r = 0; r < n; r++) { const v = x[r], j = g[r]; if (v === v && (res[j] !== res[j] || (big ? v > res[j] : v < res[j]))) res[j] = v; }
        } else if (kind === 'mode') {
          const counts = Array.from({ length: ng }, () => new Map());
          for (let r = 0; r < n; r++) { const v = x[r]; if (!isMiss(v)) { const m = counts[g[r]]; m.set(v, (m.get(v) || 0) + 1); } }
          for (let j = 0; j < ng; j++) {
            let best = null, bc = 0;
            for (const [v, c] of counts[j]) if (c > bc || (c === bc && less(v, best) < 0)) { best = v; bc = c; }
            res[j] = best == null ? missOf(a.t) : best;
          }
        } else {
          const vals = Array.from({ length: ng }, () => []);
          for (let r = 0; r < n; r++) { const v = x[r]; if (v === v) vals[g[r]].push(v); }
          for (const v of vals) v.sort((p, q) => p - q);
          cache = { g, sorted: vals };
          return;
        }
        cache = { g, res };
      };
      let f;
      if (perRow) f = (r) => { if (!cache) prepare(); return cache.perRow[r]; };
      else if (kind === 'quantile') f = (r) => { if (!cache) prepare(); return quantileSorted(cache.sorted[cache.g[r]], fp(r)); };
      else if (kind === 'median') f = (r) => { if (!cache) prepare(); return quantileSorted(cache.sorted[cache.g[r]], 0.5); };
      else f = (r) => { if (!cache) prepare(); return cache.res[cache.g[r]]; };
      const t = kind === 'mode' ? a.t : 'num';
      const date = ['min', 'max', 'mean', 'median', 'quantile', 'mode'].includes(kind) && !!a.date;
      return { f, t, date };
    };
  }

  function dateF(fn) {
    return (node, env) => {
      const [a] = compArgs(node, env);
      needNum(a, node.args[0], node.name);
      const f = numF(a);
      return { f: (r) => { const v = f(r); if (v !== v || !Number.isFinite(v)) return NaN; return fn(new Date(v)); }, t: 'num' };
    };
  }

  function strFn(fn, t = 'str') {
    return (node, env) => {
      const cs = compArgs(node, env);
      const fs = cs.map((c, i) => (i === 0 ? strF(c) : c));
      return { f: fn(fs, cs, node), t };
    };
  }

  function randomFn(draw) {
    return (node, env) => {
      const cs = compArgs(node, env);
      cs.forEach((c, i) => needNum(c, node.args[i], node.name));
      env.random = true;
      env.rowDep = true;
      const fs = cs.map(numF);
      return { f: (r) => draw(env.rng, fs.map((fn) => fn(r))), t: 'num' };
    };
  }

  function logicFn(kind, mz) {
    return (node, env) => {
      const cs = compArgs(node, env);
      const ts = cs.map((c, i) => truthF(c, node.args[i], node.name));
      if (kind === 'not') return { f: (r) => { const x = ts[0](r); return x === null ? (mz ? 1 : NaN) : x ? 0 : 1; }, t: 'num' };
      const want = kind === 'and' ? false : true;
      return {
        f: (r) => {
          let miss = false;
          for (const tf of ts) {
            const x = tf(r);
            if (x === want) return want ? 1 : 0;
            if (x === null) { if (mz) { if (kind === 'and') return 0; } else miss = true; }
          }
          return miss ? NaN : want ? 0 : 1;
        },
        t: 'num',
      };
    };
  }

  function ifFn(mz) {
    return (node, env) => {
      const cs = compArgs(node, env);
      const conds = [], results = [];
      for (let i = 0; i + 1 < cs.length; i += 2) { conds.push(truthF(cs[i], node.args[i], 'A condition of If')); results.push(cs[i + 1]); }
      const els = cs.length % 2 === 1 ? cs[cs.length - 1] : null;
      const all = els ? results.concat([els]) : results;
      const t = unify(all);
      const miss = missOf(t);
      const rs = results.map((x) => resultF(x, t));
      const fe = els ? resultF(els, t) : null;
      const m = conds.length;
      const f = (r) => {
        for (let i = 0; i < m; i++) {
          const c = conds[i](r);
          if (c === null) { if (mz) continue; return miss; }
          if (c) return rs[i](r);
        }
        return fe ? fe(r) : miss;
      };
      const real = all.filter((x) => !x.miss);
      return { f, t, date: real.length > 0 && real.every((x) => x.date) };
    };
  }

  function matchFn(node, env) {
    const cs = compArgs(node, env);
    const x = cs[0];
    const vals = [], results = [];
    for (let i = 1; i + 1 < cs.length; i += 2) {
      const v = cs[i];
      if (!v.miss && x.t !== 'any' && v.t !== 'any' && v.t !== x.t) throw new FormulaError(`Match compares ${x.t === 'num' ? 'a number' : 'text'} with ${v.t === 'num' ? 'a number' : 'text'}`, node.args[i].pos, node.args[i].end);
      vals.push(v);
      results.push(cs[i + 1]);
    }
    const els = (cs.length - 1) % 2 === 1 ? cs[cs.length - 1] : null;
    const all = els ? results.concat([els]) : results;
    const t = unify(all);
    const miss = missOf(t);
    const rs = results.map((y) => resultF(y, t));
    const fe = els ? resultF(els, t) : null;
    const fx = x.f;
    const norm = (v) => (v == null ? '' : v);
    let f;
    if (vals.every((v) => v.konst)) {
      const map = new Map();
      let missAt = -1;
      vals.forEach((v, i) => {
        if (v.miss || (typeof v.v === 'number' && v.v !== v.v)) { if (missAt < 0) missAt = i; return; }
        const key = norm(v.v);
        if (!map.has(key)) map.set(key, i);
      });
      f = (r) => {
        const v = fx(r);
        if (typeof v === 'number' && v !== v) return missAt >= 0 ? rs[missAt](r) : miss;
        const i = map.get(norm(v));
        if (i !== undefined) return rs[i](r);
        if ((v == null || v === '') && missAt >= 0) return rs[missAt](r);
        return fe ? fe(r) : miss;
      };
    } else {
      const fv = vals.map((v) => v.f);
      f = (r) => {
        const v = fx(r);
        const vm = isMiss(v);
        for (let i = 0; i < fv.length; i++) {
          const w = fv[i](r);
          if (vm ? isMiss(w) : norm(w) === norm(v)) return rs[i](r);
        }
        if (vm && typeof v === 'number') return miss;
        return fe ? fe(r) : miss;
      };
    }
    const real = all.filter((y) => !y.miss);
    return { f, t, date: real.length > 0 && real.every((y) => y.date) };
  }

  function chooseFn(node, env) {
    const cs = compArgs(node, env);
    needNum(cs[0], node.args[0], 'Choose');
    const fi = numF(cs[0]);
    const results = cs.slice(1);
    const t = unify(results);
    const miss = missOf(t);
    const rs = results.map((x) => resultF(x, t));
    return { f: (r) => { const k = Math.floor(fi(r)); return k >= 1 && k <= rs.length ? rs[k - 1](r) : miss; }, t };
  }

  function lagFn(dif) {
    return (node, env) => {
      const cs = compArgs(node, env);
      const a = cs[0];
      if (dif) needNum(a, node.args[0], 'Dif');
      if (cs[1]) needNum(cs[1], node.args[1], `${node.name}'s number of rows`);
      env.rowDep = true;
      const fa = dif ? numF(a) : a.f;
      const fn = optNum(cs[1], 1);
      const miss = a.t === 'str' ? null : NaN;
      if (dif) return { f: (r) => { const k = Math.trunc(fn(r)); const j = r - k; if (k !== k || j < 0 || j >= env.table.nrows) return NaN; return fa(r) - fa(j); }, t: 'num' };
      return { f: (r) => { const k = Math.trunc(fn(r)); const j = r - k; if (k !== k || j < 0 || j >= env.table.nrows) return miss; return fa(j); }, t: a.t, date: a.date };
    };
  }

  function words(s, delims, collapse) {
    const set = new Set(Array.from(delims));
    const out = [];
    let cur = '';
    for (const ch of s) {
      if (set.has(ch)) { if (!collapse || cur) out.push(cur); cur = ''; } else cur += ch;
    }
    if (!collapse || cur) out.push(cur);
    return out;
  }

  function pick(list, n) {
    if (n !== n) return '';
    n = Math.trunc(n);
    if (n > 0) return list[n - 1] ?? '';
    if (n < 0) return list[list.length + n] ?? '';
    return '';
  }

  /* ---- the catalogue, in the categories of JMP's formula editor ------------------------- */
  // Row
  def('Row', 'Row', '', 'The number of the current row, 1 to N Row().', 0, 0, (node, env) => { env.rowDep = true; return { f: (r) => r + 1, t: 'num' }; });
  def(['N Row', 'N Rows'], 'Row', '', 'The number of rows of the table.', 0, 0, (node, env) => ({ f: () => env.table.nrows, t: 'num' }));
  def('Lag', 'Row', 'x, n = 1', 'The value of x n rows before the current row; missing in the first n rows. A negative n looks ahead.', 1, 2, lagFn(false));
  def('Dif', 'Row', 'x, n = 1', 'x minus its value n rows before.', 1, 2, lagFn(true));
  def('Sequence', 'Row', 'from, to, step = 1, repeat = 1', 'Counts from from to to by step down the rows, each value repeat times, and starts again.', 2, 4, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Sequence'));
    env.rowDep = true;
    const [fa, fb] = cs.map(numF);
    const fs = optNum(cs[2], 1), fr = optNum(cs[3], 1);
    return {
      f: (r) => {
        const a = fa(r), b = fb(r), s = fs(r), rep = Math.max(1, Math.trunc(fr(r)));
        if (a !== a || b !== b || s !== s || s === 0 || rep !== rep) return NaN;
        const count = Math.floor((b - a) / s + 1e-9) + 1;
        if (count <= 0) return NaN;
        return a + (Math.floor(r / rep) % count) * s;
      },
      t: 'num',
    };
  });

  // Numeric
  def('Abs', 'Numeric', 'x', 'The absolute value.', 1, 1, math1(Math.abs));
  def('Ceiling', 'Numeric', 'x', 'The smallest integer at or above x.', 1, 1, math1(Math.ceil));
  def('Floor', 'Numeric', 'x', 'The largest integer at or below x.', 1, 1, math1(Math.floor));
  def('Round', 'Numeric', 'x, decimals = 0', 'x rounded to the decimals, halves away from zero, in decimal digits: Round(3.555, 2) is 3.56.', 1, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Round'));
    const fx = numF(cs[0]), fd = optNum(cs[1], 0);
    return { f: (r) => roundTo(fx(r), fd(r)), t: 'num' };
  });
  def(['Modulo', 'Mod'], 'Numeric', 'x, divisor', 'The remainder of x divided by the divisor, with the sign of x; missing when the divisor is 0.', 2, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Modulo'));
    const [fx, fd] = cs.map(numF);
    return { f: (r) => { const d = fd(r); return d === 0 ? NaN : fx(r) % d; }, t: 'num' };
  });
  def('Sign', 'Numeric', 'x', '1 for positive x, −1 for negative, 0 for 0.', 1, 1, math1(Math.sign));
  def('Power', 'Numeric', 'x, p = 2', 'x to the power p.', 1, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Power'));
    const fx = numF(cs[0]), fp = optNum(cs[1], 2);
    return { f: (r) => { const x = fx(r), p = fp(r); return x !== x || p !== p ? NaN : fin(Math.pow(x, p)); }, t: 'num' };
  });
  def('Root', 'Numeric', 'x, n = 2', 'The n-th root; odd roots of negative numbers are negative.', 1, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Root'));
    const fx = numF(cs[0]), fn = optNum(cs[1], 2);
    return { f: (r) => { const x = fx(r), n = fn(r); if (x !== x || n !== n || n === 0) return NaN; if (x < 0 && Number.isInteger(n) && n % 2) return -fin(Math.pow(-x, 1 / n)); return fin(Math.pow(x, 1 / n)); }, t: 'num' };
  });
  def('Sqrt', 'Numeric', 'x', 'The square root; missing for negative x.', 1, 1, math1(Math.sqrt));
  def('Empty', 'Numeric', '', 'A missing value, the same as a dot.', 0, 0, () => ({ f: () => NaN, t: 'num', miss: true, konst: true, v: NaN }));

  // Transcendental
  def('Exp', 'Transcendental', 'x', 'e to the power x.', 1, 1, math1(Math.exp));
  def('Log', 'Transcendental', 'x, base = e', 'The natural logarithm, or the logarithm to the base; missing for x ≤ 0.', 1, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Log'));
    const fx = numF(cs[0]);
    if (!cs[1]) return { f: (r) => fin(Math.log(fx(r))), t: 'num' };
    const fb = numF(cs[1]);
    return { f: (r) => { const b = fb(r); return b > 0 && b !== 1 ? fin(Math.log(fx(r)) / Math.log(b)) : NaN; }, t: 'num' };
  });
  def('Log10', 'Transcendental', 'x', 'The logarithm to base 10.', 1, 1, math1(Math.log10));
  def('Log2', 'Transcendental', 'x', 'The logarithm to base 2.', 1, 1, math1(Math.log2));
  def('Log1P', 'Transcendental', 'x', 'log(1 + x), accurate for small x.', 1, 1, math1(Math.log1p));
  def('Squash', 'Transcendental', 'x', 'The logistic function 1/(1 + e^−x).', 1, 1, math1((x) => 1 / (1 + Math.exp(-x))));
  def('Logit', 'Transcendental', 'p', 'log(p/(1 − p)).', 1, 1, math1((p) => Math.log(p / (1 - p))));

  // Trigonometric
  def(['Sine', 'Sin'], 'Trigonometric', 'x', 'The sine of x in radians.', 1, 1, math1(Math.sin));
  def(['Cosine', 'Cos'], 'Trigonometric', 'x', 'The cosine of x in radians.', 1, 1, math1(Math.cos));
  def(['Tangent', 'Tan'], 'Trigonometric', 'x', 'The tangent of x in radians.', 1, 1, math1(Math.tan));
  def(['ArcSine', 'ArcSin', 'ASin'], 'Trigonometric', 'x', 'The inverse sine, in radians.', 1, 1, math1(Math.asin));
  def(['ArcCosine', 'ArcCos', 'ACos'], 'Trigonometric', 'x', 'The inverse cosine, in radians.', 1, 1, math1(Math.acos));
  def(['ArcTangent', 'ArcTan', 'ATan'], 'Trigonometric', 'y, x', 'The inverse tangent of y, or of y/x in the right quadrant, in radians.', 1, 2, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'ArcTangent'));
    const fy = numF(cs[0]);
    if (!cs[1]) return { f: (r) => Math.atan(fy(r)), t: 'num' };
    const fx = numF(cs[1]);
    return { f: (r) => { const y = fy(r), x = fx(r); return y !== y || x !== x ? NaN : Math.atan2(y, x); }, t: 'num' };
  });
  def('Pi', 'Trigonometric', '', 'π, 3.14159…', 0, 0, () => ({ f: () => Math.PI, t: 'num', konst: true, v: Math.PI }));
  def('e', 'Transcendental', '', 'e, 2.71828…', 0, 0, () => ({ f: () => Math.E, t: 'num', konst: true, v: Math.E }));

  // Character
  def('Char', 'Character', 'x, width, decimals', 'A number as text, "." when missing; with decimals, that many decimals.', 1, 3, (node, env) => {
    const cs = compArgs(node, env);
    const a = cs[0];
    if (a.t === 'str') return { f: strF(a), t: 'str' };
    const fx = numF(a);
    if (!cs[2]) return { f: (r) => charOf(fx(r)), t: 'str' };
    const fd = numF(cs[2]);
    return { f: (r) => { const x = fx(r), d = fd(r); if (x !== x) return '.'; return d === d ? x.toFixed(Math.max(0, Math.min(20, Math.trunc(d)))) : charOf(x); }, t: 'str' };
  });
  def('Num', 'Character', 'text', 'The number written in the text, missing if it is not one.', 1, 1, (node, env) => {
    const [a] = compArgs(node, env);
    if (a.t === 'num') return { f: a.f, t: 'num' };
    const fs = strF(a);
    const toNumber = SM.table && SM.table.toNumber ? SM.table.toNumber : (s) => Number(s);
    return { f: (r) => toNumber(fs(r)), t: 'num' };
  });
  def('Concat', 'Character', 'a, b, …', 'The texts joined; numbers are written as Char writes them. The same as a || b.', 1, null, (node, env) => {
    const fs = compArgs(node, env).map(strF);
    return { f: (r) => { let s = ''; for (const f of fs) s += f(r); return cap(s); }, t: 'str' };
  });
  def('Substr', 'Character', 'text, start, length', 'The part of the text from start (1 is the first character; negative counts from the end), length characters or to the end.', 2, 3, strFn(([fs, st, ln]) => {
    const fst = numF(st), fln = ln ? numF(ln) : () => Infinity;
    return (r) => {
      const s = fs(r);
      let a = Math.trunc(fst(r));
      const L = fln(r);
      if (a !== a || L !== L) return '';
      if (a < 0) a = s.length + a + 1;
      if (a < 1) a = 1;
      return L === Infinity ? s.slice(a - 1) : s.slice(a - 1, a - 1 + Math.max(0, Math.trunc(L)));
    };
  }));
  def('Left', 'Character', 'text, n', 'The first n characters.', 2, 2, strFn(([fs, n]) => { const fn = numF(n); return (r) => { const k = fn(r); return k === k ? fs(r).slice(0, Math.max(0, Math.trunc(k))) : ''; }; }));
  def('Right', 'Character', 'text, n', 'The last n characters.', 2, 2, strFn(([fs, n]) => { const fn = numF(n); return (r) => { const k = Math.max(0, Math.trunc(fn(r))); if (k !== k) return ''; const s = fs(r); return k ? s.slice(Math.max(0, s.length - k)) : ''; }; }));
  def(['Uppercase', 'Upper'], 'Character', 'text', 'The text in capitals.', 1, 1, strFn(([fs]) => (r) => fs(r).toUpperCase()));
  def(['Lowercase', 'Lower'], 'Character', 'text', 'The text in small letters.', 1, 1, strFn(([fs]) => (r) => fs(r).toLowerCase()));
  def('Titlecase', 'Character', 'text', 'Each word with a capital first letter and the rest small.', 1, 1, strFn(([fs]) => (r) => fs(r).toLowerCase().replace(/(^|[^\p{L}\p{N}'’])(\p{L})/gu, (m, a, b) => a + b.toUpperCase())));
  def(['Trim', 'Trim Whitespace'], 'Character', 'text, "both" | "left" | "right"', 'The text without the spaces at its ends.', 1, 2, strFn(([fs, side]) => {
    const fside = side ? strF(side) : () => 'both';
    return (r) => { const s = fs(r), w = fside(r).toLowerCase(); return w === 'left' ? s.replace(/^\s+/, '') : w === 'right' ? s.replace(/\s+$/, '') : s.trim(); };
  }));
  def('Collapse Whitespace', 'Character', 'text', 'The text trimmed, with each run of spaces made one space.', 1, 1, strFn(([fs]) => (r) => fs(r).trim().replace(/\s+/g, ' ')));
  def('Contains', 'Character', 'text, part, start = 1', 'Where the part first occurs in the text (1 is the first character), 0 if it does not; a negative start searches backwards from the end.', 2, 3, strFn(([fs, part, start]) => {
    const fp = strF(part), fst = start ? numF(start) : () => 1;
    return (r) => {
      const s = fs(r), p = fp(r);
      let a = Math.trunc(fst(r));
      if (a !== a) return NaN;
      if (a < 0) return s.lastIndexOf(p, s.length + a) + 1;
      if (a < 1) a = 1;
      return s.indexOf(p, a - 1) + 1;
    };
  }, 'num'));
  def('Starts With', 'Character', 'text, prefix', '1 if the text begins with the prefix, else 0.', 2, 2, strFn(([fs, p]) => { const fp = strF(p); return (r) => (fs(r).startsWith(fp(r)) ? 1 : 0); }, 'num'));
  def('Ends With', 'Character', 'text, suffix', '1 if the text ends with the suffix, else 0.', 2, 2, strFn(([fs, p]) => { const fp = strF(p); return (r) => (fs(r).endsWith(fp(r)) ? 1 : 0); }, 'num'));
  def('Word', 'Character', 'n, text, delimiters = " "', 'The n-th word (negative n counts from the end); runs of delimiters count as one.', 2, 3, (node, env) => {
    const cs = compArgs(node, env);
    needNum(cs[0], node.args[0], 'Word');
    const fn = numF(cs[0]), fs = strF(cs[1]), fd = cs[2] ? strF(cs[2]) : () => ' \t\r\n';
    return { f: (r) => pick(words(fs(r), fd(r) || ' ', true), fn(r)), t: 'str' };
  });
  def('Item', 'Character', 'n, text, delimiters = " "', 'The n-th item between delimiters; two delimiters in a row make an empty item.', 2, 3, (node, env) => {
    const cs = compArgs(node, env);
    needNum(cs[0], node.args[0], 'Item');
    const fn = numF(cs[0]), fs = strF(cs[1]), fd = cs[2] ? strF(cs[2]) : () => ' ';
    return { f: (r) => pick(words(fs(r), fd(r) || ' ', false), fn(r)), t: 'str' };
  });
  def('Length', 'Character', 'text', 'The number of characters.', 1, 1, strFn(([fs]) => (r) => fs(r).length, 'num'));
  def('Substitute', 'Character', 'text, find, replace, …', 'The text with every occurrence of find replaced (more pairs may follow).', 3, null, (node, env) => {
    const fs = compArgs(node, env).map(strF);
    return {
      f: (r) => {
        let s = fs[0](r);
        for (let i = 1; i + 1 < fs.length; i += 2) { const a = fs[i](r); if (a) s = cap(s.split(a).join(fs[i + 1](r))); }
        return s;
      },
      t: 'str',
    };
  });
  def('Repeat', 'Character', 'text, n', 'The text n times.', 2, 2, strFn(([fs, n]) => { const fn = numF(n); return (r) => { const k = Math.trunc(fn(r)); const s = fs(r); if (!(k > 0)) return ''; if (s.length * k > MAX_TEXT) throw new FormulaError(`a computed text is longer than ${MAX_TEXT} characters`); return s.repeat(k); }; }));
  def('Reverse', 'Character', 'text', 'The characters in the opposite order.', 1, 1, strFn(([fs]) => (r) => Array.from(fs(r)).reverse().join('')));

  // Comparison
  def('Is Missing', 'Comparison', 'x', '1 if x is missing (or empty text), else 0.', 1, 1, (node, env) => { const [a] = compArgs(node, env); const f = a.f; return { f: (r) => (isMiss(f(r)) ? 1 : 0), t: 'num' }; });
  def('Zero Or Missing', 'Comparison', 'x', '1 if x is 0 or missing, else 0.', 1, 1, (node, env) => { const [a] = compArgs(node, env); needNum(a, node.args[0], 'Zero Or Missing'); const f = numF(a); return { f: (r) => { const v = f(r); return v !== v || v === 0 ? 1 : 0; }, t: 'num' }; });

  // Conditional
  def('If', 'Conditional', 'condition, then, …, else', 'The result after the first true condition; the else result if none is true; missing if a condition is missing.', 2, null, ifFn(false));
  def('IfMZ', 'Conditional', 'condition, then, …, else', 'If, with a missing condition counted as false.', 2, null, ifFn(true));
  def('Match', 'Conditional', 'x, value, result, …, else', 'The result after the value that equals x; the else result if none does. A . among the values matches a missing x.', 3, null, matchFn);
  def('Choose', 'Conditional', 'k, result1, result2, …', 'The k-th result.', 2, null, chooseFn);
  def('And', 'Conditional', 'a, b, …', '1 if every argument is true; 0 if one is false; else missing. The same as a & b.', 1, null, logicFn('and', false));
  def('Or', 'Conditional', 'a, b, …', '1 if an argument is true; 0 if all are false; else missing. The same as a | b.', 1, null, logicFn('or', false));
  def('Not', 'Conditional', 'a', '1 if a is false, 0 if true, missing if missing. The same as !a.', 1, 1, logicFn('not', false));
  def('AndMZ', 'Conditional', 'a, b, …', 'And, with missing counted as false.', 1, null, logicFn('and', true));
  def('OrMZ', 'Conditional', 'a, b, …', 'Or, with missing counted as false.', 1, null, logicFn('or', true));

  // Statistical, across the arguments of a row
  def('Sum', 'Statistical', 'a, b, …', 'The sum of the arguments that are not missing; missing if all are.', 1, null, rowwise('sum'));
  def('Mean', 'Statistical', 'a, b, …', 'The mean of the arguments that are not missing.', 1, null, rowwise('mean'));
  def(['Minimum', 'Min'], 'Statistical', 'a, b, …', 'The smallest argument that is not missing.', 1, null, rowwise('min'));
  def(['Maximum', 'Max'], 'Statistical', 'a, b, …', 'The largest argument that is not missing.', 1, null, rowwise('max'));
  def('Std Dev', 'Statistical', 'a, b, …', 'The standard deviation (n − 1) of the arguments that are not missing.', 1, null, rowwise('sd'));
  def('Median', 'Statistical', 'a, b, …', 'The median of the arguments that are not missing.', 1, null, rowwise('median'));
  def('Number', 'Statistical', 'a, b, …', 'How many arguments are not missing.', 1, null, rowwise('number'));
  def('N Missing', 'Statistical', 'a, b, …', 'How many arguments are missing.', 1, null, rowwise('nmissing'));

  // Statistical, down a column
  const BY = ', <By columns…>';
  def('Col Sum', 'Statistical', `x${BY}`, 'The sum of x over every row (or over the rows of the By group).', 1, null, colStat('sum'));
  def('Col Mean', 'Statistical', `x${BY}`, 'The mean of x over the rows (of the By group).', 1, null, colStat('mean'));
  def('Col Std Dev', 'Statistical', `x${BY}`, 'The standard deviation (n − 1) of x over the rows.', 1, null, colStat('sd'));
  def(['Col Minimum', 'Col Min'], 'Statistical', `x${BY}`, 'The smallest value of x.', 1, null, colStat('min'));
  def(['Col Maximum', 'Col Max'], 'Statistical', `x${BY}`, 'The largest value of x.', 1, null, colStat('max'));
  def('Col Median', 'Statistical', `x${BY}`, 'The median of x.', 1, null, colStat('median'));
  def('Col Quantile', 'Statistical', `x, p${BY}`, 'The p quantile of x (p from 0 to 1), JMP\'s definition: the (n + 1)p-th value in order, interpolated.', 2, null, colStat('quantile'));
  def('Col Number', 'Statistical', `x${BY}`, 'How many values of x are not missing.', 1, null, colStat('number'));
  def('Col N Missing', 'Statistical', `x${BY}`, 'How many values of x are missing.', 1, null, colStat('nmissing'));
  def('Col Mode', 'Statistical', `x${BY}`, 'The most frequent value of x (the smallest if several are).', 1, null, colStat('mode'));
  def(['Col Rank', 'Rank'], 'Statistical', `x${BY}, <<Tie("average")`, 'The rank of x among the values that are not missing, 1 for the smallest. Ties in row order unless <<Tie("average"), <<Tie("minimum") or <<Tie("maximum").', 1, null, colStat('rank'), { named: ['tie'] });
  def(['Col Cumulative Sum', 'Cumulative Sum'], 'Statistical', `x${BY}`, 'The sum of x from the first row to this one (missing values are skipped and stay missing).', 1, null, colStat('cumsum'));
  def('Col Standardize', 'Statistical', `x${BY}`, '(x − mean)/standard deviation over the rows.', 1, null, colStat('standardize'));

  // Probability
  const normalArgs = (node, env) => { const cs = compArgs(node, env); cs.forEach((c, i) => needNum(c, node.args[i], node.name)); return [numF(cs[0]), optNum(cs[1], 0), optNum(cs[2], 1)]; };
  def('Normal Distribution', 'Probability', 'x, mean = 0, sd = 1', 'The probability that a normal value is at most x.', 1, 3, (node, env) => { const [fx, fm, fs] = normalArgs(node, env); return { f: (r) => { const s = fs(r); return s > 0 ? pnorm((fx(r) - fm(r)) / s) : NaN; }, t: 'num' }; });
  def('Normal Density', 'Probability', 'x, mean = 0, sd = 1', 'The normal density at x.', 1, 3, (node, env) => { const [fx, fm, fs] = normalArgs(node, env); return { f: (r) => { const s = fs(r); return s > 0 ? dnorm((fx(r) - fm(r)) / s) / s : NaN; }, t: 'num' }; });
  def('Normal Quantile', 'Probability', 'p, mean = 0, sd = 1', 'The value a normal variable is below with probability p.', 1, 3, (node, env) => { const [fp, fm, fs] = normalArgs(node, env); return { f: (r) => { const s = fs(r); return s > 0 ? fin(fm(r) + s * qnorm(fp(r))) : NaN; }, t: 'num' }; });

  // Random: one stream per evaluation, from the column's seed
  def('Random Normal', 'Random', 'mean = 0, sd = 1', 'A normal random number.', 0, 2, randomFn((rng, [m = 0, s = 1]) => m + s * rng.normal()));
  def('Random Uniform', 'Random', 'min = 0, max = 1', 'A uniform random number between min and max (with one argument, between 0 and it).', 0, 2, randomFn((rng, a) => { const u = rng.u(); if (a.length === 0) return u; if (a.length === 1) return a[0] * u; return a[0] + (a[1] - a[0]) * u; }));
  def('Random Integer', 'Random', 'low, high', 'A random integer from low to high (with one argument, from 1 to it).', 1, 2, randomFn((rng, a) => { const lo = a.length > 1 ? Math.ceil(a[0]) : 1, hi = Math.floor(a.length > 1 ? a[1] : a[0]); if (lo !== lo || hi !== hi || hi < lo) return NaN; return lo + Math.floor(rng.u() * (hi - lo + 1)); }));
  def('Random Exp', 'Random', '', 'An exponential random number with mean 1.', 0, 0, randomFn((rng) => -Math.log(1 - rng.u())));

  // Date Time: dates are milliseconds since 1970 (UTC), as the table keeps them
  def('Today', 'Date Time', '', 'The date and time now.', 0, 0, (node, env) => ({ f: () => env.now, t: 'num', date: true }));
  def('Date MDY', 'Date Time', 'month, day, year', 'The date of the month, day and year.', 3, 3, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Date MDY'));
    const [fm, fd, fy] = cs.map(numF);
    return { f: (r) => { const m = fm(r), d = fd(r), y = fy(r); return m !== m || d !== d || y !== y ? NaN : Date.UTC(y, m - 1, d); }, t: 'num', date: true };
  });
  def('Date DMY', 'Date Time', 'day, month, year', 'The date of the day, month and year.', 3, 3, (node, env) => {
    const cs = compArgs(node, env);
    cs.forEach((c, i) => needNum(c, node.args[i], 'Date DMY'));
    const [fd, fm, fy] = cs.map(numF);
    return { f: (r) => { const m = fm(r), d = fd(r), y = fy(r); return m !== m || d !== d || y !== y ? NaN : Date.UTC(y, m - 1, d); }, t: 'num', date: true };
  });
  def('Year', 'Date Time', 'date', 'The year of a date.', 1, 1, dateF((d) => d.getUTCFullYear()));
  def('Month', 'Date Time', 'date', 'The month, 1 to 12.', 1, 1, dateF((d) => d.getUTCMonth() + 1));
  def('Day', 'Date Time', 'date', 'The day of the month.', 1, 1, dateF((d) => d.getUTCDate()));
  def('Hour', 'Date Time', 'date', 'The hour, 0 to 23.', 1, 1, dateF((d) => d.getUTCHours()));
  def('Minute', 'Date Time', 'date', 'The minute, 0 to 59.', 1, 1, dateF((d) => d.getUTCMinutes()));
  def('Second', 'Date Time', 'date', 'The second, with its fraction.', 1, 1, dateF((d) => d.getUTCSeconds() + d.getUTCMilliseconds() / 1000));
  def('Day Of Week', 'Date Time', 'date', 'The day of the week, 1 for Sunday to 7 for Saturday.', 1, 1, dateF((d) => d.getUTCDay() + 1));
  def('Day Of Year', 'Date Time', 'date', 'The day of the year, 1 for 1 January.', 1, 1, dateF((d) => Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 1)) / DAY) + 1));
  def('Week Of Year', 'Date Time', 'date', 'The week of the year: weeks start on Sunday and week 1 holds 1 January.', 1, 1, dateF((d) => {
    const y = d.getUTCFullYear();
    const jan1 = Date.UTC(y, 0, 1);
    const doy = Math.floor((Date.UTC(y, d.getUTCMonth(), d.getUTCDate()) - jan1) / DAY);
    return Math.floor((doy + new Date(jan1).getUTCDay()) / 7) + 1;
  }));
  def('Quarter', 'Date Time', 'date', 'The quarter of the year, 1 to 4.', 1, 1, dateF((d) => Math.floor(d.getUTCMonth() / 3) + 1));
  for (const [name, ms, what] of [['In Minutes', 60000, 'minutes'], ['In Hours', 3600000, 'hours'], ['In Days', DAY, 'days'], ['In Weeks', 7 * DAY, 'weeks'], ['In Years', 365.25 * DAY, 'years of 365.25 days']]) {
    def(name, 'Date Time', 'n = 1', `The length of n ${what} in the table's time unit (milliseconds): :date + ${name}(2), or (:end − :start)/${name}(1).`, 0, 1, (node, env) => {
      const cs = compArgs(node, env);
      if (cs[0]) needNum(cs[0], node.args[0], name);
      const fn = optNum(cs[0], 1);
      return { f: (r) => fn(r) * ms, t: 'num' };
    });
  }

  /* ---- compile and evaluate ---------------------------------------------------------- */
  function compile(ast, table, opts = {}) {
    if (typeof ast === 'string') ast = parse(ast);
    if (!table || !Array.isArray(table.columns)) throw new FormulaError('a formula needs a table');
    const env = { table, refs: new Set(), nodes: [], rowDep: false, agg: false, random: false, self: opts.self || null, rng: null, now: Date.now() };
    const c = comp(ast, env);
    return { f: c.f, type: c.t, date: !!c.date, refs: env.refs, nodes: env.nodes, rowDep: env.rowDep, agg: env.agg, random: env.random, env, ast };
  }

  function run(prog, table, rows = null, seed = 'formula') {
    const env = prog.env;
    env.rng = SM.util.rng(String(seed == null ? 'formula' : seed));
    env.now = Date.now();
    const f = prog.f;
    const m = rows == null ? table.nrows : rows.length;
    const out = new Array(m);
    if (rows == null) for (let r = 0; r < m; r++) out[r] = f(r);
    else for (let k = 0; k < m; k++) out[k] = f(rows[k]);
    let t = prog.type;
    if (t === 'any') t = out.some((v) => typeof v === 'string' && v !== '') ? 'str' : 'num';
    if (t === 'num') {
      for (let k = 0; k < m; k++) { const v = out[k]; if (typeof v !== 'number') out[k] = NaN; }
    } else {
      for (let k = 0; k < m; k++) { const v = out[k]; out[k] = typeof v === 'string' ? (v === '' ? null : v) : typeof v === 'number' && v === v ? charOf(v) : null; }
    }
    const date = prog.date && t === 'num';
    let hasTime = false;
    if (date) for (let k = 0; k < m; k++) { const v = out[k]; if (v === v && v % DAY !== 0) { hasTime = true; break; } }
    return { values: out, dataType: t === 'str' ? 'character' : 'numeric', date, hasTime };
  }

  /* The values of an expression for the rows (all when rows is null); the
     array carries .dataType ('numeric' or 'character'). */
  function evaluate(table, expr, rows = null, opts = {}) {
    const prog = compile(typeof expr === 'string' ? parse(expr) : expr, table, opts);
    const res = run(prog, table, rows, opts.seed);
    const out = res.values;
    out.dataType = res.dataType;
    out.date = res.date;
    return out;
  }

  /* ---- formula columns ----------------------------------------------------------------- */
  const META = new WeakMap();      // Column -> what its formula uses
  const WATCHED = new WeakSet();   // tables with listeners
  const RUNNING = new WeakMap();   // table -> changes that came in during a recalculation
  const SUPPRESS = new WeakSet();  // tables whose formulas are not evaluated when they open

  const colById = (table, id) => table.columns.find((c) => c.id === id) || null;

  function sync(table, c) {
    const f = c.formula;
    if (!f || typeof f.expr !== 'string') { META.delete(c); return null; }
    const old = META.get(c);
    const m = { expr: f.expr, ast: null, nodes: [], refs: (Array.isArray(f.refs) ? f.refs : []).filter((id) => colById(table, id)), rowDep: false, agg: false, random: false, error: null, told: old ? old.told : null };
    try {
      m.ast = parse(f.expr);
      const prog = compile(m.ast, table, { self: c });
      Object.assign(m, { nodes: prog.nodes, refs: [...prog.refs], rowDep: prog.rowDep, agg: prog.agg, random: prog.random });
    } catch (e) {
      m.error = e;
    }
    f.refs = m.refs.slice();
    META.set(c, m);
    return m;
  }

  function metaOf(table, c) {
    const m = META.get(c);
    return m && m.expr === c.formula.expr ? m : sync(table, c);
  }

  function seedOf(c) { return (c.formula && c.formula.seed != null) ? c.formula.seed : c.id; }

  /* The formula columns of the set in the order they must be computed, and
     the cycles among them. */
  function ordered(table, set) {
    const out = [], state = new Map(), cycles = [];
    const visit = (c, stack) => {
      const s = state.get(c);
      if (s === 2) return;
      if (s === 1) { cycles.push(stack.slice(stack.indexOf(c))); return; }
      state.set(c, 1);
      stack.push(c);
      for (const id of metaOf(table, c).refs) { const d = colById(table, id); if (d && d.formula && set.has(d)) visit(d, stack); }
      stack.pop();
      state.set(c, 2);
      out.push(c);
    };
    for (const c of set) visit(c, []);
    return { list: out, cycles };
  }

  /* Would column c, using refs, depend on itself? The chain, or null. */
  function cycleThrough(table, c, refs) {
    const seen = new Set();
    const walk = (ids, path) => {
      for (const id of ids) {
        if (id === c.id) return path;
        const d = colById(table, id);
        if (!d || !d.formula || seen.has(d)) continue;
        seen.add(d);
        const m = metaOf(table, d);
        const p = walk(m.refs, path.concat([d]));
        if (p) return p;
      }
      return null;
    };
    return walk([...refs], []);
  }

  function write(table, c, res) {
    let schema = false;
    const wantChar = res.dataType === 'character';
    if (wantChar === c.isNumeric) {
      c.dataType = wantChar ? 'character' : 'numeric';
      if (wantChar) { if (c.modelingType === 'continuous') c.modelingType = 'nominal'; c.format = null; } else c.modelingType = 'continuous';
      c.valueOrder = null;
      schema = true;
    }
    c.values = res.values;
    if (res.date && c.isNumeric && !(c.format && /date/.test(c.format.kind || ''))) { c.format = { kind: res.hasTime ? 'datetime' : 'date' }; schema = true; }
    return schema;
  }

  /* Compute the formula columns that depend on the changed columns (all
     when changed is null; with rowOrder also those that depend on the order
     of the rows). */
  function recompute(table, changed = null, { rowOrder = false, exclude = null } = {}) {
    const fcols = table.columns.filter((c) => c.formula && typeof c.formula.expr === 'string');
    const out = { updated: [], errors: [], schema: false };
    if (!fcols.length) return out;
    for (const c of fcols) metaOf(table, c);
    let affected;
    if (changed == null) affected = new Set(fcols);
    else {
      affected = new Set();
      const ids = new Set(changed);
      for (let grew = true; grew;) {
        grew = false;
        for (const c of fcols) {
          if (affected.has(c)) continue;
          const m = META.get(c);
          if ((ids.has(c.id) && !(exclude && exclude.has(c))) || (rowOrder && m.rowDep) || m.refs.some((id) => ids.has(id))) { affected.add(c); ids.add(c.id); grew = true; }
        }
      }
    }
    if (exclude) for (const c of exclude) affected.delete(c);
    if (!affected.size) return out;
    const { list, cycles } = ordered(table, affected);
    const inCycle = new Set(cycles.flat());
    for (const c of list) {
      const m = META.get(c);
      if (inCycle.has(c)) {
        const cyc = cycles.find((x) => x.includes(c));
        m.error = new FormulaError(`the formulas go round in a circle: ${cyc.map((x) => x.name).concat([cyc[0].name]).join(' uses ')}`);
        out.errors.push({ column: c, error: m.error });
        continue;
      }
      if (!m.ast) { out.errors.push({ column: c, error: m.error }); continue; }
      try {
        // Compiled again each time: a column it uses may have changed its type.
        const prog = compile(m.ast, table, { self: c });
        if (write(table, c, run(prog, table, null, seedOf(c)))) out.schema = true;
        Object.assign(m, { nodes: prog.nodes, refs: [...prog.refs], rowDep: prog.rowDep, agg: prog.agg, random: prog.random, error: null, told: null });
        out.updated.push(c.id);
      } catch (e) {
        m.error = e;
        out.errors.push({ column: c, error: e });
      }
    }
    return out;
  }

  function announce(table, res) {
    if (!res.updated.length && !res.schema) return;
    table.version++;
    if (res.schema) table.emit('schema', { formula: res.updated });
    table.emit('data', { formula: res.updated });
  }

  /* Say what went wrong, once for each new error. */
  function complain(res) {
    const fresh = res.errors.filter((e) => { const m = META.get(e.column); if (!m || !e.error || m.told === e.error.message) return false; m.told = e.error.message; return true; });
    if (!fresh.length || !SM.ui || !SM.ui.toast) return;
    const e = fresh[0];
    SM.ui.toast(`Formula of ${e.column.name}: ${e.error.message}${fresh.length > 1 ? ` (and ${fresh.length - 1} more)` : ''}. The column keeps its values.`, { error: true });
  }

  /* Recalculate after a change; changes that arrive while a recalculation
     runs (a listener that edits the table) are done after it, a few rounds
     at most, so that no chain of events can loop for ever. */
  function schedule(table, changed, rowOrder = false) {
    if (RUNNING.has(table)) {
      const q = RUNNING.get(table);
      if (!q) RUNNING.set(table, { changed: changed == null ? null : new Set(changed), rowOrder });
      else { if (changed == null || q.changed == null) q.changed = null; else for (const id of changed) q.changed.add(id); q.rowOrder = q.rowOrder || rowOrder; }
      return null;
    }
    RUNNING.set(table, null);
    let last = null;
    try {
      let job = { changed, rowOrder };
      for (let round = 0; job && round < 6; round++) {
        last = recompute(table, job.changed, { rowOrder: job.rowOrder });
        announce(table, last);
        complain(last);
        job = RUNNING.get(table);
        RUNNING.set(table, null);
      }
    } finally {
      RUNNING.delete(table);
    }
    return last;
  }

  function onData(table, d) {
    if (d && (d.formula || d.schema || d.renamed === 'table')) return;
    let changed = null, rowOrder = false;
    if (d && Array.isArray(d.cells)) changed = new Set(d.cells.map((x) => x[1]));
    else if (d && d.column) changed = new Set([d.column]);
    else if (d && (d.sorted || d.moved)) { changed = new Set(); rowOrder = true; }
    schedule(table, changed, rowOrder);
  }

  const REF_OK = /^[\p{L}_][\p{L}\p{N}_]*$/u;
  function refText(name) {
    return REF_OK.test(name) ? `:${name}` : `:"${String(name).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
  }

  function renameRefs(table, id) {
    const col = colById(table, id);
    if (!col) return;
    for (const c of table.columns) {
      if (!c.formula || typeof c.formula.expr !== 'string') continue;
      const m = META.get(c);
      if (!m || m.error || m.expr !== c.formula.expr) continue;
      const spans = m.nodes.filter((n) => n.id === id).sort((a, b) => b.pos - a.pos);
      if (!spans.length) continue;
      let s = m.expr;
      for (const sp of spans) s = s.slice(0, sp.pos) + refText(col.name) + s.slice(sp.end);
      c.formula.expr = s;
      sync(table, c);
    }
  }

  function dropRefs(table, id) {
    const lost = [];
    for (const c of table.columns) {
      if (!c.formula) continue;
      const m = META.get(c);
      const refs = m ? m.refs : (c.formula.refs || []);
      if (refs.includes(id)) lost.push(c);
    }
    for (const c of lost) { c.formula = null; META.delete(c); }
    if (lost.length) {
      table.version++;
      table.emit('schema', { formula: lost.map((c) => c.id) });
      table.emit('data', { formula: lost.map((c) => c.id) });
      if (SM.ui && SM.ui.toast) SM.ui.toast(`${lost.map((c) => c.name).join(', ')} lost ${lost.length > 1 ? 'their formulas' : 'its formula'}: a column it used was deleted. The values stay; Edit > Undo brings the column back.`);
    }
  }

  function onSchema(table, d) {
    if (!d || d.formula) return;
    if (d.renamed && d.renamed !== 'table') renameRefs(table, d.renamed);
    else if (d.removed) dropRefs(table, d.removed);
    else if (d.retyped) schedule(table, new Set([d.retyped]));
    else if (d.restored) { for (const c of table.columns) { if (c.formula) sync(table, c); else META.delete(c); } }
    else if (d.added) { const c = colById(table, d.added); if (c && c.formula && typeof c.formula.expr === 'string') { sync(table, c); schedule(table, new Set([c.id])); } }
  }

  function watch(table) {
    if (!table || WATCHED.has(table)) return;
    WATCHED.add(table);
    table.on('data', (d) => onData(table, d));
    table.on('schema', (d) => onSchema(table, d));
  }

  /* A table that has just opened: read its formulas and, unless told not
     to, compute them. */
  function adopt(table) {
    watch(table);
    const has = table.columns.some((c) => c.formula && typeof c.formula.expr === 'string');
    if (!has) return;
    for (const c of table.columns) if (c.formula) sync(table, c);
    if (SUPPRESS.has(table)) { SUPPRESS.delete(table); return; }
    schedule(table, null);
  }

  /* Make a column a formula column: parse, check, compute, keep current.
     Throws a FormulaError (with .pos) when the formula is wrong. */
  function apply(table, column, expr, opts = {}) {
    const c = column && table.columns.includes(column) ? column : table.col(column);
    if (!c) throw new FormulaError('there is no such column');
    const text = String(expr == null ? '' : expr).replace(/\s+$/, '');
    if (!text.trim()) { removeFormula(table, c); return c; }
    const ast = parse(text);
    const prog = compile(ast, table, { self: c });
    const loop = cycleThrough(table, c, prog.refs);
    if (loop) throw new FormulaError(`the formula would go round in a circle: ${[c].concat(loop).map((x) => x.name).concat([c.name]).join(' uses ')}`);
    const seed = c.formula && c.formula.seed != null ? c.formula.seed : (opts.seed != null ? opts.seed : c.id);
    const res = run(prog, table, null, seed);
    watch(table);
    c.formula = { expr: text, refs: [...prog.refs], seed };
    META.set(c, { expr: text, ast, nodes: prog.nodes, refs: [...prog.refs], rowDep: prog.rowDep, agg: prog.agg, random: prog.random, error: null });
    write(table, c, res);
    const dep = recompute(table, new Set([c.id]), { exclude: new Set([c]) });
    announce(table, { updated: [c.id, ...dep.updated], schema: true });
    complain(dep);
    return c;
  }

  function removeFormula(table, c) {
    if (!c.formula) return;
    c.formula = null;
    META.delete(c);
    table.version++;
    table.emit('schema', { formula: [c.id] });
    table.emit('data', { formula: [c.id] });
  }

  /* Compute every formula column of the table now. */
  function recalc(table) {
    watch(table);
    const res = schedule(table, null) || { updated: [], errors: [] };
    return { updated: res.updated, errors: res.errors.map((e) => ({ column: e.column.name, message: e.error.message })) };
  }

  /* What the formula of a column refers to, and its error if it has one. */
  function info(table, c) {
    if (!c || !c.formula) return null;
    const m = metaOf(table, c);
    return { expr: m.expr, refs: m.refs.map((id) => (colById(table, id) || {}).name).filter(Boolean), error: m.error ? m.error.message : null, rowDep: m.rowDep, random: m.random };
  }

  /* ---- the formula editor ------------------------------------------------------------------- */
  const CATEGORIES = ['Row', 'Numeric', 'Transcendental', 'Trigonometric', 'Character', 'Comparison', 'Conditional', 'Statistical', 'Probability', 'Random', 'Date Time'];

  function edit(table, column = null, opts = {}) {
    const { el } = SM.util;
    const t = table || (SM.app && SM.app.current);
    if (!t) { if (SM.ui) SM.ui.toast('Open a table first'); return Promise.resolve(null); }
    let cur = column ? t.col(column) : null;   // the column being edited; set once a new one is made
    return new Promise((resolve) => {
      let done = false;
      const finish = (v) => { if (!done) { done = true; resolve(v); } };
      const nameIn = el('input', { type: 'text', class: 'smf-name', 'aria-label': 'Column name', value: cur ? cur.name : t.uniqueName(opts.name || 'Formula') });
      const ta = el('textarea', { class: 'smf-expr', rows: 5, spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', 'aria-label': 'Formula', placeholder: 'for example  :weight / (:height / 100)^2   or   If(:age >= 15, "older", "younger")' });
      ta.value = cur && cur.formula ? cur.formula.expr : (opts.expr || '');
      const msg = el('div', { class: 'sm-launch-msg smf-msg', role: 'status' });
      const preview = el('div', { class: 'smf-preview', 'aria-live': 'polite' });
      const help = el('div', { class: 'smf-help' });
      const circle = (c, refs) => { const loop = cycleThrough(t, c, refs); return loop ? new FormulaError(`the formula would go round in a circle: ${[c].concat(loop).map((x) => x.name).concat([c.name]).join(' uses ')}`) : null; };

      const insert = (text, { wrap = false, caret = null } = {}) => {
        const s = ta.selectionStart, e = ta.selectionEnd;
        const sel = ta.value.slice(s, e);
        let ins = text, pos = null;
        if (wrap) { ins = `${text}(${sel})`; pos = sel ? s + ins.length : s + text.length + 1; }
        ta.setRangeText(ins, s, e, 'end');
        if (pos != null) ta.setSelectionRange(pos, pos);
        else if (caret != null) ta.setSelectionRange(s + caret, s + caret);
        ta.focus();
        refresh();
      };

      // Columns
      const colFilter = el('input', { type: 'search', placeholder: 'Filter columns', 'aria-label': 'Filter columns' });
      const colList = el('div', { class: 'smf-list', role: 'list', 'aria-label': 'Columns' });
      const fillCols = () => {
        const f = colFilter.value.trim().toLowerCase();
        colList.replaceChildren(...t.columns.filter((x) => x !== cur && (!f || x.name.toLowerCase().includes(f))).map((x) => {
          const b = el('button', { type: 'button', class: 'smf-item', role: 'listitem', draggable: 'true', title: `Insert ${refText(x.name)} (click, or drag it into the formula)` }, SM.util.typeIcon(x.modelingType), el('span', { text: x.name }));
          b.addEventListener('click', () => insert(refText(x.name)));
          // dragged into the formula box, the column's reference lands where
          // it is let go (the box takes the text as any text field does)
          b.addEventListener('dragstart', (ev) => {
            ev.dataTransfer.setData('text/plain', refText(x.name));
            if (SM.launch) ev.dataTransfer.setData(SM.launch.MIME, JSON.stringify([x.id]));
            ev.dataTransfer.effectAllowed = 'copy';
          });
          return b;
        }));
      };
      colFilter.addEventListener('input', fillCols);
      fillCols();

      // Functions
      const catSel = el('select', { 'aria-label': 'Function group' }, el('option', { value: '', text: 'All functions' }), ...CATEGORIES.map((k) => el('option', { value: k, text: k })));
      const fnFilter = el('input', { type: 'search', placeholder: 'Filter functions', 'aria-label': 'Filter functions' });
      const fnList = el('div', { class: 'smf-list', role: 'list', 'aria-label': 'Functions' });
      const showHelp = (d) => help.replaceChildren(el('code', { text: `${d.name}(${d.args})` }), el('span', { text: ` ${d.about}` }), d.aliases.length ? el('span', { class: 'smf-alias', text: ` Also: ${d.aliases.join(', ')}.` }) : null);
      const fillFns = () => {
        const k = catSel.value, f = fnFilter.value.trim().toLowerCase();
        const list = DOCS.filter((d) => (!k || d.cat === k) && (!f || d.name.toLowerCase().includes(f) || d.aliases.some((x) => x.toLowerCase().includes(f))));
        fnList.replaceChildren(...list.map((d) => {
          const b = el('button', { type: 'button', class: 'smf-item', role: 'listitem', title: d.about, dataset: { fn: d.name } }, el('span', { text: d.name }));
          b.addEventListener('click', () => { showHelp(d); insert(d.name, { wrap: true }); });
          b.addEventListener('mouseenter', () => showHelp(d));
          b.addEventListener('focus', () => showHelp(d));
          return b;
        }));
      };
      catSel.addEventListener('change', fillFns);
      fnFilter.addEventListener('input', fillFns);
      fillFns();

      // The keypad
      const keys = [['+', ' + '], ['−', ' - '], ['×', ' * '], ['÷', ' / '], ['^', '^'], ['( )', '()'], ['==', ' == '], ['!=', ' != '], ['<', ' < '], ['<=', ' <= '], ['>', ' > '], ['>=', ' >= '], ['&', ' & '], ['|', ' | '], ['!', '!'], ['||', ' || '], [',', ', '], ['.', '.']];
      const pad = el('div', { class: 'smf-pad', role: 'group', 'aria-label': 'Operators' }, ...keys.map(([label, text]) => {
        const b = el('button', { type: 'button', class: 'sm-btn small', text: label, 'aria-label': `Insert ${text.trim() || label}` });
        b.addEventListener('click', () => (text === '()' ? insert('()', { caret: 1 }) : insert(text)));
        return b;
      }));

      // Preview: the first rows, or the error with its place marked
      const refresh = SM.util.debounce(() => {
        const text = ta.value;
        preview.replaceChildren();
        if (!text.trim()) { preview.append(el('p', { class: 'sm-ob-note', text: cur && cur.formula ? 'An empty formula removes the formula; the values stay.' : 'Type a formula, or build one from the columns and functions.' })); return; }
        try {
          const rows = [];
          for (let r = 0; r < Math.min(t.nrows, 8); r++) rows.push(r);
          const prog = compile(parse(text), t, { self: cur });
          const loop = cur ? circle(cur, prog.refs) : null;
          if (loop) throw loop;
          const res = run(prog, t, rows, cur ? seedOf(cur) : 'preview');
          const fake = { isNumeric: res.dataType === 'numeric', format: res.date ? { kind: res.hasTime ? 'datetime' : 'date' } : (cur && cur.isNumeric === (res.dataType === 'numeric') ? cur.format : null) };
          const tbl = el('table', { class: 'sm-rt smf-rows' }, el('thead', null, el('tr', null, el('th', { text: 'Row' }), el('th', { text: res.dataType === 'numeric' ? 'Value (numeric)' : 'Value (character)' }))));
          const body = el('tbody');
          res.values.forEach((v, i) => body.append(el('tr', null, el('td', { text: String(rows[i] + 1) }), el('td', { class: fake.isNumeric ? '' : 'sm-l', text: SM.table.isMissing(v) ? (fake.isNumeric ? '•' : '') : (SM.grid ? SM.grid.cellText(fake, v) : String(v)) }))));
          tbl.append(body);
          preview.append(tbl);
          if (t.nrows > rows.length) preview.append(el('p', { class: 'sm-ob-note', text: `The first ${rows.length} of ${t.nrows} rows.` }));
        } catch (e) {
          const box = el('div', { class: 'smf-error', role: 'alert' });
          box.append(el('strong', { text: 'Not a formula yet: ' }), document.createTextNode(e.reason || e.message));
          if (e.pos != null) {
            const a = Math.max(0, Math.min(text.length, e.pos)), b = Math.max(a, Math.min(text.length, e.end || a + 1));
            box.append(el('pre', { class: 'smf-where' }, text.slice(Math.max(0, a - 60), a), el('mark', { text: text.slice(a, b) || ' ' }), text.slice(b, b + 60)));
          }
          preview.append(box);
        }
      }, 140);
      ta.addEventListener('input', () => { msg.textContent = ''; refresh(); });
      ta.addEventListener('drop', () => requestAnimationFrame(() => ta.focus()));

      // OK and Apply: check first, keep a copy for Undo, then change the table.
      const commit = () => {
        const text = ta.value;
        const name = nameIn.value.trim();
        msg.textContent = '';
        try {
          if (cur) {
            if (!text.trim()) {
              if (cur.formula) { if (SM.app && SM.app.record) SM.app.record(t, 'Remove Formula'); removeFormula(t, cur); }
              if (name && name !== cur.name) t.renameColumn(cur.id, name);
              return cur;
            }
            const prog = compile(parse(text), t, { self: cur });
            const loop = circle(cur, prog.refs);
            if (loop) throw loop;
            if (SM.app && SM.app.record) SM.app.record(t, 'Formula');
            apply(t, cur, text);
            if (name && name !== cur.name) t.renameColumn(cur.id, name);
            return cur;
          }
          if (!name) { msg.textContent = 'Give the new column a name.'; return null; }
          if (!text.trim()) { msg.textContent = 'Type a formula first.'; return null; }
          compile(parse(text), t);
          if (SM.app && SM.app.record) SM.app.record(t, 'New Formula Column');
          const nc = t.addColumn({ name, dataType: 'numeric', values: [] }, opts.at);
          try { apply(t, nc, text); } catch (e) { t.removeColumn(nc.id); throw e; }
          cur = nc;
          fillCols();
          return nc;
        } catch (e) {
          msg.textContent = e.message;
          return null;
        }
      };
      let dlg = null;
      ta.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); const r = commit(); if (r) { finish(r); dlg.close(true); } }
      });

      const left = el('div', { class: 'smf-side' },
        el('h4', { text: 'Columns' }), colFilter, colList,
        el('h4', { text: 'Functions (grouped)' }), el('div', { class: 'smf-fnhead' }, catSel, fnFilter), fnList);
      const right = el('div', { class: 'smf-main' },
        el('label', { class: 'smf-namerow' }, el('span', { text: 'Column name' }), nameIn),
        el('h4', { text: 'Formula' }), ta, pad, help, el('h4', { text: 'Preview' }), preview, msg);
      const body = el('div', { class: 'smf-editor' }, left, right);
      const buttons = [];
      if (cur && cur.formula) buttons.push({ label: 'Remove Formula', action: () => { if (SM.app && SM.app.record) SM.app.record(t, 'Remove Formula'); removeFormula(t, cur); finish(cur); return true; } });
      buttons.push({ label: 'Cancel', action: () => { finish(cur && !column ? cur : null); return true; } });
      buttons.push({ label: 'Apply', action: () => { const r = commit(); if (r) msg.textContent = `Applied to ${r.name}.`; return false; } });
      buttons.push({ label: 'OK', primary: true, action: () => { const r = commit(); if (r) { finish(r); return true; } return false; } });
      dlg = SM.ui.dialog({ title: cur ? `Formula: ${cur.name}` : 'New Formula Column', body, buttons, info: 'cmd:formula', className: 'smf-dialog', onClose: () => finish(cur && !column ? cur : null) });
      refresh();
      requestAnimationFrame(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
    });
  }

  /* ---- hooking into the page ------------------------------------------------------------------ */
  function hook() {
    const app = SM.app;
    if (!app || WATCHED.has(app)) return;
    WATCHED.add(app);
    for (const t of app.tables || []) adopt(t);
    app.on('tableadded', (t) => adopt(t));
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', hook);
    else setTimeout(hook, 0);
  }

  if (SM.info && SM.info.add) {
    SM.info.add({
      'cmd:formula': {
        kicker: 'Cols', title: 'Formula',
        lead: 'A formula computes a column from others, row by row, and keeps it current: when the values it uses change, it is computed again.',
        sections: [
          { heading: 'Writing one', list: ['Columns are `:name`, or `:"weight (kg)"` when the name has spaces or signs; a bare name that is a column works too.', 'Operators: `+ - * / ^`, comparisons `== != < <= > >=` (chained: `1 < :x <= 3`), `&` and, `|` or, `!` not, `||` joins text.', 'Functions by their JMP names, in any case: `If(:age >= 15, "older", "younger")`, `Col Mean(:height, :sex)`, `Lag(:sales, 12)`, `Round(:x, 2)`.', 'Click a column or a function to insert it, or drag a column into the formula, where it lands; a function wraps the selected text. ctrl/⌘+Enter is OK.'] },
          { heading: 'Missing values', text: 'As in JMP: arithmetic and comparisons with a missing value are missing, If with a missing condition is missing, `0 & .` is 0 and `1 | .` is 1, and Sum, Mean, Min and Max of their arguments skip missing ones. Division by zero is missing.' },
          { heading: 'Safe to share', text: 'A formula is text that this page reads with its own parser; it never runs as code, so a table from someone else cannot run anything.' },
        ],
      },
    });
  }

  SM.formula = Object.freeze({
    parse, compile, evaluate, apply, edit, recalc, info, removeFormula, adopt, watch,
    refText, quantile: quantileSorted, pnorm, qnorm, roundTo, charOf,
    suppressNextEvaluation: (t) => SUPPRESS.add(t),
    FormulaError,
    functions: Object.freeze(DOCS.map((d) => Object.freeze({ name: d.name, category: d.cat, args: d.args, about: d.about, aliases: d.aliases.slice() }))),
  });
}(typeof self !== 'undefined' ? self : this));
