/* ==========================================================================
   FACSIMILE-STYLE REACTION MODELS: PARSER AND CODE GENERATOR

   Turns a model text (settings, constants, tables, thermodynamic data,
   initial values, equations, reactions, events, outputs) into JavaScript
   functions the solvers in facsimile-ode.js can integrate:

     rhs(t, y, P, H, out)    dy/dt
     jac(t, y, P, H, V)      df/dy, the values of a sparse pattern built
                             symbolically from the equations
     observe(t, y, P, H, out) the equations and outputs at a state
     events(t, y, P, H, out) the event expressions
     init(t0, y, P, H, speciesToo) the <INITIAL> section

   The Jacobian is exact rather than differenced: every expression is
   compiled together with its gradient with respect to the species it
   depends on (forward-mode differentiation at compile time, one term per
   species), so a rate constant that depends on the third-body concentration
   M contributes the right entries in the O2, N2, H2O, AR, H2 and NH3 columns,
   and a step or ramp contributes 0 across its kink rather than the large
   artefact a finite difference reports there.

   The file runs unchanged in a page, in a Web Worker (imported for effect by
   facsimile-worker-entry.js, which is a module) and in Node (require); it
   exposes one global, FacsimileModel.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.FacsimileModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ------------------------------------------------------------------------
     Errors carry the line they refer to, so the editor can point at it.
     ------------------------------------------------------------------------ */
  class ModelError extends Error {
    constructor(message, line) {
      super(line ? `Line ${line}: ${message}` : message);
      this.name = 'ModelError';
      this.line = line || 0;
    }
  }

  /* ------------------------------------------------------------------------
     Expression tokenizer and parser
     ------------------------------------------------------------------------ */
  const NUM_RE = /^(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?/;
  const ID_RE = /^[A-Za-z_][A-Za-z0-9_]*/;

  function tokenize(src, line) {
    const tokens = [];
    let i = 0;
    while (i < src.length) {
      const ch = src[i];
      if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') { i++; continue; }
      const rest = src.slice(i);
      let m;
      if ((m = NUM_RE.exec(rest))) {
        // FACSIMILE writes double precision exponents with a D.
        tokens.push({ t: 'num', v: parseFloat(m[0].replace(/[dD]/, 'e')), pos: i });
        i += m[0].length;
        continue;
      }
      if ((m = ID_RE.exec(rest))) {
        tokens.push({ t: 'id', v: m[0], pos: i });
        i += m[0].length;
        continue;
      }
      if (rest.startsWith('**')) { tokens.push({ t: 'op', v: '**', pos: i }); i += 2; continue; }
      if ('+-*/^@(),'.includes(ch)) {
        tokens.push({ t: 'op', v: ch === '^' || ch === '@' ? '**' : ch, pos: i });
        i++;
        continue;
      }
      throw new ModelError(`Unexpected character "${ch}" in "${src}"`, line);
    }
    return tokens;
  }

  /**
   * Grammar (lowest to highest precedence):
   *   sum     := product (('+'|'-') product)*
   *   product := unary (('*'|'/') unary)*
   *   unary   := ('-'|'+') unary | power
   *   power   := atom ('**' unary)?          right associative; -x**2 = -(x**2), x**-2 allowed
   *   atom    := number | name | name '(' args ')' | '(' sum ')'
   */
  function parseExpression(src, line) {
    const tokens = tokenize(src, line);
    let k = 0;
    const peek = () => tokens[k];
    const next = () => tokens[k++];
    const expectOp = (v) => {
      const tok = next();
      if (!tok || tok.t !== 'op' || tok.v !== v) {
        throw new ModelError(`Expected "${v}" in "${src}"`, line);
      }
    };
    function sum() {
      let node = product();
      while (peek() && peek().t === 'op' && (peek().v === '+' || peek().v === '-')) {
        const op = next().v;
        node = { type: 'bin', op, l: node, r: product() };
      }
      return node;
    }
    function product() {
      let node = unary();
      while (peek() && peek().t === 'op' && (peek().v === '*' || peek().v === '/')) {
        const op = next().v;
        node = { type: 'bin', op, l: node, r: unary() };
      }
      return node;
    }
    function unary() {
      const tok = peek();
      if (tok && tok.t === 'op' && (tok.v === '-' || tok.v === '+')) {
        next();
        const a = unary();
        return tok.v === '-' ? { type: 'neg', a } : a;
      }
      return power();
    }
    function power() {
      const base = atom();
      const tok = peek();
      if (tok && tok.t === 'op' && tok.v === '**') {
        next();
        return { type: 'bin', op: '**', l: base, r: unary() };
      }
      return base;
    }
    function atom() {
      const tok = next();
      if (!tok) throw new ModelError(`Unexpected end of expression "${src}"`, line);
      if (tok.t === 'num') return { type: 'num', v: tok.v };
      if (tok.t === 'id') {
        if (peek() && peek().t === 'op' && peek().v === '(') {
          next();
          const args = [];
          if (!(peek() && peek().t === 'op' && peek().v === ')')) {
            args.push(sum());
            while (peek() && peek().t === 'op' && peek().v === ',') { next(); args.push(sum()); }
          }
          expectOp(')');
          return { type: 'call', name: tok.v, args };
        }
        return { type: 'id', name: tok.v };
      }
      if (tok.t === 'op' && tok.v === '(') {
        const node = sum();
        expectOp(')');
        return node;
      }
      throw new ModelError(`Unexpected "${tok.v}" in "${src}"`, line);
    }
    const node = sum();
    if (k !== tokens.length) {
      throw new ModelError(`Unexpected "${tokens[k].v}" after the expression in "${src}"`, line);
    }
    return node;
  }

  /* Functions the expression language knows, with the JavaScript they become. */
  const FUNCTIONS = {
    exp: { n: 1, js: 'Math.exp' },
    log: { n: 1, js: 'Math.log' },
    ln: { n: 1, js: 'Math.log' },
    log10: { n: 1, js: 'Math.log10' },
    sqrt: { n: 1, js: 'Math.sqrt' },
    abs: { n: 1, js: 'Math.abs' },
    min: { n: 2, js: 'Math.min' },
    max: { n: 2, js: 'Math.max' },
    pow: { n: 2, js: 'Math.pow' },
    ramp: { n: 1 },     // max(x, 0), FACSIMILE's RAMP
    step: { n: 1 },     // 1 for x > 0, else 0 (derivative 0)
    interp: { n: 2 },   // interp(TABLE, x): piecewise linear, clamped at the ends
    state: { n: 1 },    // state(X): the raw state variable of species X
  };

  /* Names referenced by an expression, and whether it reads t. */
  function collectRefs(ast, refs, calls) {
    switch (ast.type) {
      case 'id': refs.add(ast.name); break;
      case 'neg': collectRefs(ast.a, refs, calls); break;
      case 'bin': collectRefs(ast.l, refs, calls); collectRefs(ast.r, refs, calls); break;
      case 'call':
        if (calls) calls.add(ast.name.toLowerCase());
        // The first argument of interp is a table name, not a value.
        ast.args.forEach((a, i) => {
          if (ast.name.toLowerCase() === 'interp' && i === 0 && a.type === 'id') return;
          collectRefs(a, refs, calls);
        });
        break;
      default: break;
    }
    return refs;
  }

  /* ------------------------------------------------------------------------
     Model text parser
     ------------------------------------------------------------------------ */
  const SECTION_RE = /^<\s*([A-Za-z][A-Za-z ]*?)(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*>$/;

  /** Strips comments: '#', FACSIMILE's ';' terminator with trailing text, '!!' markers. */
  function stripComment(raw) {
    let line = raw;
    const hash = line.indexOf('#');
    let comment = '';
    if (hash >= 0) { comment = line.slice(hash + 1).trim(); line = line.slice(0, hash); }
    const bang = line.indexOf('!!');
    if (bang >= 0) line = line.slice(0, bang);
    const semi = line.indexOf(';');
    if (semi >= 0) {
      const after = line.slice(semi + 1).trim();
      if (after && !comment) comment = after;
      line = line.slice(0, semi);
    }
    return { code: line.trim(), comment };
  }

  function parseModelText(text) {
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    const model = {
      settings: [], constants: [], species: [], tables: {}, thermo: [],
      initial: [], equations: [], reactions: [], events: [], outputs: [],
    };
    let section = null;
    let tableName = null;
    lines.forEach((raw, idx) => {
      const line = idx + 1;
      const trimmed = raw.trim();
      if (!trimmed) return;
      if (trimmed.startsWith('*')) return;              // FACSIMILE comment line
      const sec = SECTION_RE.exec(trimmed);
      if (sec) {
        section = sec[1].trim().toUpperCase().replace(/\s+/g, ' ');
        tableName = null;
        if (section === 'TABLE') {
          if (!sec[2]) throw new ModelError('A table needs a name: <TABLE NAME>', line);
          tableName = sec[2];
          if (model.tables[tableName]) throw new ModelError(`Table "${tableName}" is defined twice`, line);
          model.tables[tableName] = { name: tableName, x: [], y: [], line };
        } else if (sec[2]) {
          throw new ModelError(`Section <${section}> does not take a name`, line);
        }
        return;
      }
      const { code, comment } = stripComment(raw);
      if (!code) return;
      if (!section) throw new ModelError('Text before the first section; start with e.g. <SETTINGS>', line);
      switch (section) {
        case 'SETTINGS':
        case 'CONSTANTS':
        case 'INITIAL':
        case 'OUTPUTS':
        case 'EQUATIONS': {
          const eq = code.indexOf('=');
          if (eq < 0) throw new ModelError(`Expected NAME = expression, got "${code}"`, line);
          let name = code.slice(0, eq).trim();
          const expr = code.slice(eq + 1).trim();
          if (!expr) throw new ModelError(`"${name}" has no value`, line);
          let substitution = false;
          if (section === 'EQUATIONS' && name.startsWith('@')) { substitution = true; name = name.slice(1).trim(); }
          if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new ModelError(`"${name}" is not a valid name`, line);
          const entry = { name, expr, line, comment, substitution };
          const key = { SETTINGS: 'settings', CONSTANTS: 'constants', INITIAL: 'initial', OUTPUTS: 'outputs', EQUATIONS: 'equations' }[section];
          model[key].push(entry);
          break;
        }
        case 'SPECIES':
          code.split(/[\s,]+/).filter(Boolean).forEach((name) => {
            if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new ModelError(`"${name}" is not a valid species name`, line);
            if (!model.species.includes(name)) model.species.push(name);
          });
          break;
        case 'TABLE': {
          const nums = code.split(/[\s,]+/).filter(Boolean).map(Number);
          if (nums.length !== 2 || nums.some((v) => !Number.isFinite(v))) {
            throw new ModelError(`A table row is two numbers, got "${code}"`, line);
          }
          const tab = model.tables[tableName];
          if (tab.x.length && nums[0] <= tab.x[tab.x.length - 1]) {
            throw new ModelError(`Table "${tableName}": x must increase (${nums[0]} after ${tab.x[tab.x.length - 1]})`, line);
          }
          tab.x.push(nums[0]);
          tab.y.push(nums[1]);
          break;
        }
        case 'THERMO': {
          const parts = code.split(/\s+/);
          if (parts.length !== 8) throw new ModelError(`A thermo row is a name and seven coefficients, got ${parts.length} fields`, line);
          const coef = parts.slice(1).map((s) => parseFloat(s.replace(/[dD]/, 'e')));
          if (coef.some((v) => !Number.isFinite(v))) throw new ModelError('A thermo coefficient is not a number', line);
          model.thermo.push({ name: parts[0], coef, line });
          break;
        }
        case 'REACTIONS':
          model.reactions.push(parseReactionLine(code, comment, line));
          break;
        case 'EVENTS': {
          const parts = splitTop(code, ',');
          if (parts.length < 2) throw new ModelError('An event is "expression, NAME = value [, NAME = value]"', line);
          const assigns = parts.slice(1).map((p) => {
            const eq = p.indexOf('=');
            if (eq < 0) throw new ModelError(`Expected NAME = value in event, got "${p.trim()}"`, line);
            return { name: p.slice(0, eq).trim(), expr: p.slice(eq + 1).trim() };
          });
          model.events.push({ expr: parts[0].trim(), assigns, line, comment });
          break;
        }
        default:
          throw new ModelError(`Unknown section <${section}>`, line);
      }
    });
    return model;
  }

  /** Splits at a separator outside parentheses. */
  function splitTop(s, sep) {
    const out = [];
    let depth = 0, cur = '';
    for (const ch of s) {
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      if (ch === sep && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
    }
    out.push(cur);
    return out;
  }

  /**
   * One reaction line. Two forms:
   *   A + 2 B = C, kf = expr [, kb = expr | keq = expr]      or rf = / rb =
   *   [FXn]%kf[%kb] : A + 2 B = C           FACSIMILE, kf and kb rate constants
   *   = expr : A = B                        FACSIMILE, an absolute rate
   */
  function parseReactionLine(code, comment, line) {
    let sides, spec = {};
    const colon = code.indexOf(':');
    if (colon >= 0 && (code.startsWith('%') || code.startsWith('=') || /^FX\d+\s*%/i.test(code))) {
      const head = code.slice(0, colon).replace(/^FX\d+\s*/i, '').trim();
      sides = code.slice(colon + 1).trim();
      if (head.startsWith('=')) {
        spec.rf = head.slice(1).trim();
      } else {
        const rates = head.split('%').map((s) => s.trim()).filter(Boolean);
        if (!rates.length || rates.length > 2) throw new ModelError('FACSIMILE reaction needs %kf or %kf%kb before the colon', line);
        spec.kf = rates[0];
        if (rates[1]) spec.kb = rates[1];
      }
    } else {
      const parts = splitTop(code, ',');
      sides = parts[0].trim();
      parts.slice(1).forEach((p) => {
        const eq = p.indexOf('=');
        if (eq < 0) throw new ModelError(`Expected kf = ..., kb = ..., keq = ..., rf = ... or rb = ..., got "${p.trim()}"`, line);
        const key = p.slice(0, eq).trim().toLowerCase();
        if (!['kf', 'kb', 'keq', 'rf', 'rb'].includes(key)) throw new ModelError(`Unknown rate key "${key}" (use kf, kb, keq, rf or rb)`, line);
        if (spec[key]) throw new ModelError(`"${key}" given twice`, line);
        spec[key] = p.slice(eq + 1).trim();
      });
    }
    const eq = sides.indexOf('=');
    if (eq < 0) throw new ModelError(`A reaction needs "=" between reactants and products: "${code}"`, line);
    const reactants = parseSide(sides.slice(0, eq), line);
    const products = parseSide(sides.slice(eq + 1), line);
    if (!Object.keys(spec).length) throw new ModelError('A reaction needs a rate: kf, rf (or FACSIMILE %k)', line);
    if (spec.keq && !spec.kf) throw new ModelError('keq needs kf', line);
    if (spec.kb && spec.keq) throw new ModelError('Give kb or keq, not both', line);
    if (spec.kf && spec.rf) throw new ModelError('Give kf or rf, not both', line);
    if (spec.rb && (spec.kb || spec.keq)) throw new ModelError('Give rb or kb/keq, not both', line);
    if ((spec.kf || spec.kb || spec.keq) && !reactants.length && spec.kf) {
      throw new ModelError('A reaction with no reactants needs an absolute rate rf, not kf', line);
    }
    if (spec.kb && !products.length) throw new ModelError('kb needs products', line);
    return { reactants, products, spec, line, comment, text: code };
  }

  function parseSide(text, line) {
    const out = [];
    const t = text.trim();
    if (!t) return out;
    t.split('+').forEach((term) => {
      const s = term.trim();
      if (!s) throw new ModelError(`Empty term in "${text}"`, line);
      const m = /^(\d+)?\s*\*?\s*([A-Za-z_][A-Za-z0-9_]*)$/.exec(s);
      if (!m) throw new ModelError(`"${s}" is not a species term (write "2 OH" or "OH")`, line);
      const coef = m[1] ? parseInt(m[1], 10) : 1;
      if (!(coef > 0)) throw new ModelError(`Stoichiometric coefficient must be positive in "${s}"`, line);
      const found = out.find((x) => x.name === m[2]);
      if (found) found.coef += coef; else out.push({ name: m[2], coef });
    });
    return out;
  }

  /* ------------------------------------------------------------------------
     Table interpolation helpers, shared by the generated code (as H) and by
     the compile-time evaluator.
     ------------------------------------------------------------------------ */
  function interpTable(tab, x) {
    const xs = tab.x, ys = tab.y, n = xs.length;
    if (n === 1 || x <= xs[0]) return ys[0];
    if (x >= xs[n - 1]) return ys[n - 1];
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
    const f = (x - xs[lo]) / (xs[hi] - xs[lo]);
    return ys[lo] + f * (ys[hi] - ys[lo]);
  }
  function slopeTable(tab, x) {
    const xs = tab.x, ys = tab.y, n = xs.length;
    if (n === 1 || x <= xs[0] || x >= xs[n - 1]) return 0;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
    return (ys[hi] - ys[lo]) / (xs[hi] - xs[lo]);
  }

  /* ------------------------------------------------------------------------
     Compile-time evaluation of constant expressions
     ------------------------------------------------------------------------ */
  function evalAst(ast, lookup, tables, line) {
    switch (ast.type) {
      case 'num': return ast.v;
      case 'id': {
        const v = lookup(ast.name);
        if (v === undefined) throw new ModelError(`"${ast.name}" is not defined here`, line);
        return v;
      }
      case 'neg': return -evalAst(ast.a, lookup, tables, line);
      case 'bin': {
        const a = evalAst(ast.l, lookup, tables, line);
        const b = evalAst(ast.r, lookup, tables, line);
        switch (ast.op) {
          case '+': return a + b;
          case '-': return a - b;
          case '*': return a * b;
          case '/': return a / b;
          case '**': return Math.pow(a, b);
          default: throw new ModelError(`Unknown operator ${ast.op}`, line);
        }
      }
      case 'call': {
        const fn = ast.name.toLowerCase();
        const def = FUNCTIONS[fn];
        if (!def) throw new ModelError(`Unknown function "${ast.name}"`, line);
        if (fn === 'interp') {
          const tab = ast.args[0] && ast.args[0].type === 'id' ? resolveTable(ast.args[0].name, tables, lookup, line) : null;
          if (!tab) throw new ModelError('interp needs a table name as its first argument', line);
          return interpTable(tab, evalAst(ast.args[1], lookup, tables, line));
        }
        if (fn === 'state') throw new ModelError('state() can only be used in equations and outputs', line);
        if (ast.args.length !== def.n) throw new ModelError(`${ast.name} takes ${def.n} argument(s)`, line);
        const a = ast.args.map((x) => evalAst(x, lookup, tables, line));
        switch (fn) {
          case 'exp': return Math.exp(a[0]);
          case 'log': case 'ln': return Math.log(a[0]);
          case 'log10': return Math.log10(a[0]);
          case 'sqrt': return Math.sqrt(a[0]);
          case 'abs': return Math.abs(a[0]);
          case 'min': return Math.min(a[0], a[1]);
          case 'max': return Math.max(a[0], a[1]);
          case 'pow': return Math.pow(a[0], a[1]);
          case 'ramp': return a[0] > 0 ? a[0] : 0;
          case 'step': return a[0] > 0 ? 1 : 0;
          default: throw new ModelError(`Unknown function "${ast.name}"`, line);
        }
      }
      default: throw new ModelError('Bad expression', line);
    }
  }

  /** A table by name, or through a setting whose value is a table name. */
  function resolveTable(name, tables, lookup, line) {
    if (tables[name]) return tables[name];
    const alias = lookup ? lookup(name) : undefined;
    if (typeof alias === 'string' && tables[alias]) return tables[alias];
    if (typeof alias === 'string') throw new ModelError(`"${name}" refers to "${alias}", which is not a table`, line);
    return null;
  }

  /* ------------------------------------------------------------------------
     The code generator
     ------------------------------------------------------------------------ */

  /**
   * Emits straight-line JavaScript for value and gradient. A gradient is a
   * Map from species index to a code string; absent keys are structural zeros.
   */
  class Emitter {
    constructor(ctx) {
      this.ctx = ctx;              // { speciesIndex, P: name->index, tables: name->index, lookupEq(name), speciesRef(i), clamp }
      this.lines = [];
      this.n = 0;
      this.cse = new Map();
    }
    temp(code) {
      // Hoist repeated expressions; cheap and it keeps the derivative code small.
      if (this.cse.has(code)) return this.cse.get(code);
      const name = `v${this.n++}`;
      this.lines.push(`const ${name} = ${code};`);
      this.cse.set(code, name);
      return name;
    }
    isZero(g) { return !g || g.size === 0; }
    scale(g, factor) {                        // factor * g
      const out = new Map();
      if (factor === '0') return out;
      for (const [j, c] of g) out.set(j, this.mulCode(factor, c));
      return out;
    }
    add(a, b, sign = '+') {                   // a + b  or  a - b
      const out = new Map(a);
      for (const [j, c] of b) {
        if (out.has(j)) out.set(j, this.temp(`${out.get(j)} ${sign} ${c}`));
        else out.set(j, sign === '-' ? this.temp(`-${c}`) : c);
      }
      return out;
    }
    mulCode(a, b) {
      if (a === '1') return b;
      if (b === '1') return a;
      return this.temp(`${a} * ${b}`);
    }
    numLiteral(v) {
      const s = String(v);
      return /^-/.test(s) ? `(${s})` : s;
    }

    /** @returns {{v: string, g: Map<number,string>, num?: number}} */
    emit(ast, line) {
      switch (ast.type) {
        case 'num': return { v: this.numLiteral(ast.v), g: new Map(), num: ast.v };
        case 'id': return this.ctx.resolve(ast.name, line, this);
        case 'neg': {
          const a = this.emit(ast.a, line);
          if (a.num !== undefined) return { v: this.numLiteral(-a.num), g: new Map(), num: -a.num };
          return { v: this.temp(`-${a.v}`), g: this.isZero(a.g) ? new Map() : mapMap(a.g, (c) => this.temp(`-${c}`)) };
        }
        case 'bin': return this.emitBinary(ast, line);
        case 'call': return this.emitCall(ast, line);
        default: throw new ModelError('Bad expression node', line);
      }
    }

    emitBinary(ast, line) {
      const a = this.emit(ast.l, line);
      const b = this.emit(ast.r, line);
      // Constant folding of literal arithmetic.
      if (a.num !== undefined && b.num !== undefined) {
        const val = evalAst({ type: 'bin', op: ast.op, l: { type: 'num', v: a.num }, r: { type: 'num', v: b.num } }, () => undefined, {}, line);
        return { v: this.numLiteral(val), g: new Map(), num: val };
      }
      switch (ast.op) {
        case '+': return { v: this.temp(`${a.v} + ${b.v}`), g: this.add(a.g, b.g, '+') };
        case '-': return { v: this.temp(`${a.v} - ${b.v}`), g: this.add(a.g, b.g, '-') };
        case '*': {
          const v = this.temp(`${a.v} * ${b.v}`);
          // d(ab) = b da + a db
          const g = this.add(this.scale(a.g, b.v), this.scale(b.g, a.v));
          return { v, g };
        }
        case '/': {
          const v = this.temp(`${a.v} / ${b.v}`);
          // d(a/b) = da/b - a db/b^2 = (da - v db)/b
          let g = new Map();
          if (!this.isZero(a.g)) g = mapMap(a.g, (c) => this.temp(`${c} / ${b.v}`));
          if (!this.isZero(b.g)) {
            const factor = this.temp(`-${v} / ${b.v}`);
            g = this.add(g, this.scale(b.g, factor));
          }
          return { v, g };
        }
        case '**': {
          // Integer powers of a base with a gradient: multiply out (exact and cheap).
          if (b.num !== undefined && Number.isInteger(b.num) && b.num >= 2 && b.num <= 4) {
            let v = a.v;
            for (let i = 1; i < b.num; i++) v = this.temp(`${v} * ${a.v}`);
            let dv = this.numLiteral(b.num);
            if (b.num > 2) {
              let p = a.v;
              for (let i = 2; i < b.num; i++) p = this.temp(`${p} * ${a.v}`);
              dv = this.temp(`${b.num} * ${p}`);
            } else dv = this.temp(`2 * ${a.v}`);
            return { v, g: this.scale(a.g, dv) };
          }
          const v = this.temp(`Math.pow(${a.v}, ${b.v})`);
          let g = new Map();
          if (!this.isZero(a.g)) {
            // d(a^b)/da = b a^(b-1)
            const da = b.num !== undefined
              ? this.temp(`${b.v} * Math.pow(${a.v}, ${this.numLiteral(b.num - 1)})`)
              : this.temp(`${b.v} * ${v} / ${a.v}`);
            g = this.scale(a.g, da);
          }
          if (!this.isZero(b.g)) {
            // d(a^b)/db = a^b ln a
            const db = this.temp(`${v} * Math.log(${a.v})`);
            g = this.add(g, this.scale(b.g, db));
          }
          return { v, g };
        }
        default: throw new ModelError(`Unknown operator ${ast.op}`, line);
      }
    }

    emitCall(ast, line) {
      const fn = ast.name.toLowerCase();
      const def = FUNCTIONS[fn];
      if (!def) throw new ModelError(`Unknown function "${ast.name}"`, line);
      if (fn === 'interp') {
        if (ast.args.length !== 2 || ast.args[0].type !== 'id') throw new ModelError('interp needs a table name and one argument: interp(TABLE, x)', line);
        const tabIndex = this.ctx.tableIndex(ast.args[0].name, line);
        const x = this.emit(ast.args[1], line);
        const v = this.temp(`H.interp(H.T[${tabIndex}], ${x.v})`);
        let g = new Map();
        if (!this.isZero(x.g)) g = this.scale(x.g, this.temp(`H.slope(H.T[${tabIndex}], ${x.v})`));
        return { v, g };
      }
      if (fn === 'state') {
        if (ast.args.length !== 1 || ast.args[0].type !== 'id') throw new ModelError('state() takes a species name', line);
        return this.ctx.rawState(ast.args[0].name, line, this);
      }
      if (ast.args.length !== def.n) throw new ModelError(`${ast.name} takes ${def.n} argument(s)`, line);
      const a = ast.args.map((x) => this.emit(x, line));
      if (a.every((x) => x.num !== undefined)) {
        const val = evalAst({ type: 'call', name: fn, args: a.map((x) => ({ type: 'num', v: x.num })) }, () => undefined, {}, line);
        return { v: this.numLiteral(val), g: new Map(), num: val };
      }
      switch (fn) {
        case 'exp': {
          const v = this.temp(`Math.exp(${a[0].v})`);
          return { v, g: this.scale(a[0].g, v) };
        }
        case 'log': case 'ln': {
          const v = this.temp(`Math.log(${a[0].v})`);
          return { v, g: this.isZero(a[0].g) ? new Map() : mapMap(a[0].g, (c) => this.temp(`${c} / ${a[0].v}`)) };
        }
        case 'log10': {
          const v = this.temp(`Math.log10(${a[0].v})`);
          return { v, g: this.isZero(a[0].g) ? new Map() : mapMap(a[0].g, (c) => this.temp(`${c} / (${a[0].v} * Math.LN10)`)) };
        }
        case 'sqrt': {
          const v = this.temp(`Math.sqrt(${a[0].v})`);
          return { v, g: this.isZero(a[0].g) ? new Map() : mapMap(a[0].g, (c) => this.temp(`${c} / (2 * ${v})`)) };
        }
        case 'abs': {
          const v = this.temp(`Math.abs(${a[0].v})`);
          return { v, g: this.isZero(a[0].g) ? new Map() : this.scale(a[0].g, this.temp(`(${a[0].v} >= 0 ? 1 : -1)`)) };
        }
        case 'ramp': {
          const v = this.temp(`(${a[0].v} > 0 ? ${a[0].v} : 0)`);
          return { v, g: this.isZero(a[0].g) ? new Map() : this.scale(a[0].g, this.temp(`(${a[0].v} > 0 ? 1 : 0)`)) };
        }
        case 'step': return { v: this.temp(`(${a[0].v} > 0 ? 1 : 0)`), g: new Map() };
        case 'min': case 'max': {
          const cmp = fn === 'min' ? '<=' : '>=';
          const v = this.temp(`(${a[0].v} ${cmp} ${a[1].v} ? ${a[0].v} : ${a[1].v})`);
          if (this.isZero(a[0].g) && this.isZero(a[1].g)) return { v, g: new Map() };
          const pick = this.temp(`(${a[0].v} ${cmp} ${a[1].v} ? 1 : 0)`);
          const g = this.add(this.scale(a[0].g, pick), this.scale(a[1].g, this.temp(`(1 - ${pick})`)));
          return { v, g };
        }
        case 'pow': return this.emitBinary({ type: 'bin', op: '**', l: ast.args[0], r: ast.args[1] }, line);
        default: throw new ModelError(`Unknown function "${ast.name}"`, line);
      }
    }
  }

  function mapMap(m, fn) {
    const out = new Map();
    for (const [k, v] of m) out.set(k, fn(v));
    return out;
  }

  /* ------------------------------------------------------------------------
     compile(text, options) -> model object
     ------------------------------------------------------------------------ */
  /**
   * @param {string} text
   * @param {object} [options]
   * @param {object} [options.settings]  name -> value or expression string; overrides the <SETTINGS> values
   * @param {boolean} [options.clampNegative=true]  species read as max(0, y) in every expression
   */
  function compile(text, options = {}) {
    const clamp = options.clampNegative !== false;
    const m = parseModelText(text);
    const warnings = [];

    // --- species -----------------------------------------------------------
    const species = [...m.species];
    m.reactions.forEach((r) => {
      [...r.reactants, ...r.products].forEach((s) => { if (!species.includes(s.name)) species.push(s.name); });
    });
    if (!species.length) throw new ModelError('The model has no species: add reactions or a <SPECIES> section');
    const speciesIndex = new Map(species.map((s, i) => [s, i]));
    const nspecies = species.length;

    // --- constants: settings then constants, evaluated in order --------------
    const P = [];                         // values
    const Pindex = new Map();             // name -> index into P
    const Pmeta = [];                     // { name, section, expr, comment, line, isTable }
    const tableList = Object.values(m.tables);
    const tableIndex = new Map(tableList.map((t, i) => [t.name, i]));
    const stringValues = new Map();       // settings whose value names a table

    const constLookup = (name) => {
      if (Pindex.has(name)) return P[Pindex.get(name)];
      if (stringValues.has(name)) return stringValues.get(name);
      return undefined;
    };
    const defineConstant = (entry, section) => {
      const { name, line } = entry;
      let expr = entry.expr;
      if (section === 'settings' && options.settings && options.settings[name] !== undefined && options.settings[name] !== '') {
        expr = String(options.settings[name]);
      }
      if (Pindex.has(name) || stringValues.has(name)) throw new ModelError(`"${name}" is defined twice`, line);
      if (speciesIndex.has(name)) throw new ModelError(`"${name}" is a species and cannot be a constant`, line);
      if (m.tables[expr]) {
        // A setting that names a table (a profile chosen in the panel).
        stringValues.set(name, expr);
        Pmeta.push({ name, section, expr, comment: entry.comment, line, isTable: true, index: -1 });
        return;
      }
      let value;
      try {
        value = evalAst(parseExpression(expr, line), constLookup, m.tables, line);
      } catch (e) {
        if (e instanceof ModelError) throw e;
        throw new ModelError(`${name}: ${e.message}`, line);
      }
      if (typeof value !== 'number' || !Number.isFinite(value)) throw new ModelError(`"${name}" does not evaluate to a number`, line);
      Pindex.set(name, P.length);
      Pmeta.push({ name, section, expr, comment: entry.comment, line, isTable: false, index: P.length });
      P.push(value);
    };
    m.settings.forEach((e) => defineConstant(e, 'settings'));
    m.constants.forEach((e) => defineConstant(e, 'constants'));

    // Run constants from <INITIAL> (non-species names) get slots too; their
    // values are computed by init().
    const initialConstNames = [];
    m.initial.forEach((e) => {
      if (speciesIndex.has(e.name)) return;
      if (Pindex.has(e.name) || stringValues.has(e.name)) throw new ModelError(`"${e.name}" is already a constant`, e.line);
      Pindex.set(e.name, P.length);
      Pmeta.push({ name: e.name, section: 'initial', expr: e.expr, comment: e.comment, line: e.line, isTable: false, index: P.length });
      P.push(NaN);
      initialConstNames.push(e.name);
    });

    // --- thermodynamic data -> DG<name> equations, placed after T ------------
    const equations = [];
    let seenT = false;
    let thermoInserted = m.thermo.length === 0;
    const thermoEquations = m.thermo.map((th) => ({
      name: `DG${th.name}`, line: th.line, comment: `Gibbs energy of ${th.name} (cal/mol)`, thermo: th.coef, substitution: false,
    }));
    m.equations.forEach((e) => {
      equations.push(e);
      if (!thermoInserted && e.name === 'T' && !e.substitution) { equations.push(...thermoEquations); thermoInserted = true; seenT = true; }
    });
    if (!thermoInserted) throw new ModelError('The <THERMO> section needs an equation named T (the temperature in K) to compute Gibbs energies from');
    if (m.thermo.length && !seenT) throw new ModelError('The <THERMO> section needs an equation named T');

    // --- structural analysis: which species each name depends on -----------
    const eqIndex = new Map();
    const eqDeps = [];                    // Set of species indices per equation
    const subst = new Map();              // species index -> equation entry index (the @X = ... line)
    let outputDepsRef = null;             // set once the outputs are analysed
    const nameKind = (name) => {
      if (name === 't') return 'time';
      if (speciesIndex.has(name)) return 'species';
      if (Pindex.has(name)) return 'const';
      if (stringValues.has(name)) return 'table-alias';
      if (tableIndex.has(name)) return 'table';
      if (eqIndex.has(name)) return 'equation';
      if (outputDepsRef && outputDepsRef.has(name)) return 'output';
      return null;
    };
    const depsOf = (ast, line, allowSpecies = true) => {
      const refs = collectRefs(ast, new Set());
      const deps = new Set();
      for (const name of refs) {
        const kind = nameKind(name);
        if (kind === null) {
          const hint = /^DG/.test(name) ? ' (is the species missing from <THERMO>?)' : '';
          throw new ModelError(`"${name}" is not defined${hint}`, line);
        }
        if (kind === 'species') {
          if (!allowSpecies) throw new ModelError(`"${name}" is a species and cannot be used here`, line);
          const i = speciesIndex.get(name);
          if (subst.has(i)) eqDeps[subst.get(i)].forEach((d) => deps.add(d)); else deps.add(i);
        } else if (kind === 'equation') {
          eqDeps[eqIndex.get(name)].forEach((d) => deps.add(d));
        } else if (kind === 'output') {
          outputDepsRef.get(name).forEach((d) => deps.add(d));
        } else if (kind === 'table') {
          // interp(TABLE, x) is the only place a table may appear
        }
      }
      // state(X) reads the raw state of X
      collectStateRefs(ast).forEach((name) => {
        if (!speciesIndex.has(name)) throw new ModelError(`state(${name}): "${name}" is not a species`, line);
        deps.add(speciesIndex.get(name));
      });
      return deps;
    };

    equations.forEach((e, k) => {
      if (e.thermo) {
        e.ast = null;
        eqIndex.set(e.name, k);
        eqDeps.push(eqDeps[eqIndex.get('T')]);
        return;
      }
      if (!e.substitution) {
        if (nameKind(e.name) !== null) throw new ModelError(`"${e.name}" is already defined`, e.line);
      } else {
        if (!speciesIndex.has(e.name)) throw new ModelError(`@${e.name}: "${e.name}" is not a species`, e.line);
        if (subst.has(speciesIndex.get(e.name))) throw new ModelError(`@${e.name} is given twice`, e.line);
      }
      e.ast = parseExpression(e.expr, e.line);
      const deps = depsOf(e.ast, e.line);
      // Inside its own @-line a species means the raw state; register after.
      eqDeps.push(deps);
      if (e.substitution) subst.set(speciesIndex.get(e.name), k);
      else eqIndex.set(e.name, k);
    });

    // --- reactions: structure and pattern -----------------------------------
    const reactions = m.reactions.map((r) => {
      const rr = { ...r, net: new Map(), ast: {} };
      r.reactants.forEach((s) => rr.net.set(speciesIndex.get(s.name), (rr.net.get(speciesIndex.get(s.name)) || 0) - s.coef));
      r.products.forEach((s) => rr.net.set(speciesIndex.get(s.name), (rr.net.get(speciesIndex.get(s.name)) || 0) + s.coef));
      for (const [i, c] of [...rr.net]) if (c === 0) rr.net.delete(i);
      for (const key of ['kf', 'kb', 'keq', 'rf', 'rb']) {
        if (r.spec[key]) rr.ast[key] = parseExpression(r.spec[key], r.line);
      }
      return rr;
    });

    // A species that is never produced or consumed is inert; say so.
    const touched = new Set();
    reactions.forEach((r) => r.net.forEach((c, i) => touched.add(i)));
    species.forEach((s, i) => { if (!touched.has(i)) warnings.push(`Species ${s} is not changed by any reaction`); });

    const cols = Array.from({ length: nspecies }, () => new Set());
    const speciesSelfDeps = (i) => (subst.has(i) ? [...eqDeps[subst.get(i)]] : [i]);
    reactions.forEach((r) => {
      const colSet = new Set();
      const addExpr = (key) => { if (r.ast[key]) depsOf(r.ast[key], r.line).forEach((d) => colSet.add(d)); };
      addExpr('kf'); addExpr('kb'); addExpr('keq'); addExpr('rf'); addExpr('rb');
      if (r.ast.kf) r.reactants.forEach((s) => speciesSelfDeps(speciesIndex.get(s.name)).forEach((d) => colSet.add(d)));
      if (r.ast.kb || r.ast.keq) r.products.forEach((s) => speciesSelfDeps(speciesIndex.get(s.name)).forEach((d) => colSet.add(d)));
      r.cols = colSet;
      for (const i of r.net.keys()) for (const j of colSet) cols[j].add(i);
    });
    for (let i = 0; i < nspecies; i++) cols[i].add(i);      // the diagonal, for I - h*J
    const pattern = toCSC(cols, nspecies);
    const pos = new Map();                                    // "i,j" -> position in values
    for (let j = 0; j < nspecies; j++) {
      for (let k = pattern.colPtr[j]; k < pattern.colPtr[j + 1]; k++) pos.set(`${pattern.rowIdx[k]},${j}`, k);
    }

    // --- outputs and events -------------------------------------------------
    // An output may use the outputs above it, so they are registered as they
    // are analysed; nameKind() sees them through outputDeps.
    const outputDeps = new Map();
    outputDepsRef = outputDeps;
    const outputs = m.outputs.map((o) => {
      if (nameKind(o.name) !== null || outputDeps.has(o.name)) throw new ModelError(`Output "${o.name}" is already the name of something else`, o.line);
      const ast = parseExpression(o.expr, o.line);
      outputDeps.set(o.name, depsOf(ast, o.line));
      return { ...o, ast };
    });
    const events = m.events.map((ev) => {
      const ast = parseExpression(ev.expr, ev.line);
      depsOf(ast, ev.line);
      const assigns = ev.assigns.map((a) => {
        const meta = Pmeta.find((p) => p.name === a.name);
        if (!meta || meta.isTable) {
          throw new ModelError(`Event assigns "${a.name}", which is not a numeric setting or constant`, ev.line);
        }
        if (meta.section === 'initial') throw new ModelError(`Event assigns "${a.name}", which is computed in <INITIAL>; assign a setting instead`, ev.line);
        const vast = parseExpression(a.expr, ev.line);
        depsOf(vast, ev.line, false);
        return { name: a.name, index: Pindex.get(a.name), ast: vast };
      });
      return { ...ev, ast, assigns };
    });

    // --- code generation ---------------------------------------------------
    const generated = generateCode({
      species, speciesIndex, nspecies, P, Pindex, Pmeta, tableList, tableIndex, stringValues,
      equations, eqIndex, eqDeps, subst, reactions, pattern, pos, outputs, events,
      initial: m.initial, initialConstNames, clamp, thermo: m.thermo,
    });

    const H = { T: tableList.map((t) => ({ x: Float64Array.from(t.x), y: Float64Array.from(t.y) })), interp: interpTable, slope: slopeTable };
    const fns = {};
    for (const [name, src] of Object.entries(generated.sources)) {
      try {
        fns[name] = new Function('t', 'y', 'P', 'H', 'out', 'extra', src);
      } catch (e) {
        throw new ModelError(`Internal error compiling ${name}: ${e.message}`);
      }
    }

    const observeNames = [...generated.observeNames];
    const model = {
      text, species, nspecies, P: Float64Array.from(P), Pmeta, Pindex,
      tables: tableList, H, pattern, nnz: pattern.nnz,
      density: pattern.nnz / (nspecies * nspecies),
      reactions: reactions.map((r) => ({ text: r.text, line: r.line, comment: r.comment, reactants: r.reactants, products: r.products, spec: r.spec })),
      equations: equations.map((e) => ({ name: e.name, expr: e.expr, comment: e.comment, substitution: e.substitution, timeOnly: e.thermo ? eqDeps[eqIndex.get('T')].size === 0 : eqDeps[equations.indexOf(e)].size === 0 })),
      outputs: outputs.map((o) => ({ name: o.name, expr: o.expr, comment: o.comment })),
      observeNames,
      events: events.map((e) => ({ expr: e.expr, comment: e.comment, assigns: e.assigns.map((a) => a.name) })),
      warnings, sources: generated.sources, clampNegative: clamp,
      settings: Pmeta.filter((p) => p.section === 'settings').map((p) => ({
        name: p.name, expr: p.expr, comment: p.comment, isTable: p.isTable,
        value: p.isTable ? stringValues.get(p.name) : P[p.index],
      })),
      /**
       * Every constant of the run by name: the settings, the <CONSTANTS>
       * lines and the <INITIAL> ones, a table alias as the name of its table.
       *
       * A method rather than a field for two reasons. The <INITIAL> constants
       * are not known until `initialState` has run, and an event recomputes
       * them; and `Pmeta` is longer than `P` -- a table alias takes a name but
       * no numeric slot -- so the index in `Pmeta` is the only thing that says
       * where a value lives. Pairing the two lists off by position gives every
       * constant after the first table alias the value of its neighbour.
       */
      constantValues() {
        const out = {};
        for (const p of Pmeta) out[p.name] = p.isTable ? stringValues.get(p.name) : this.P[p.index];
        return out;
      },
      tableNames: tableList.map((t) => t.name),

      /** dy/dt into out (Float64Array of length nspecies). */
      rhs(t, y, out) { return fns.rhs(t, y, this.P, this.H, out); },
      /** Values of the Jacobian pattern into V (Float64Array of length nnz). */
      jac(t, y, V) { return fns.jac(t, y, this.P, this.H, V); },
      /** Equations followed by outputs (see observeNames). */
      observe(t, y, out) { return fns.observe(t, y, this.P, this.H, out || new Float64Array(observeNames.length)); },
      /** Event expressions. */
      eventValues(t, y, out) { return fns.events(t, y, this.P, this.H, out || new Float64Array(events.length)); },
      nevents: events.length,
      /** Applies event k's assignments and recomputes the run constants. */
      applyEvent(k, t, y0) {
        const ev = events[k];
        ev.assigns.forEach((a) => { this.P[a.index] = evalAst(a.ast, (name) => (Pindex.has(name) ? this.P[Pindex.get(name)] : undefined), {}, ev.line); });
        fns.init(t, y0, this.P, this.H, null, false);
        return ev.assigns.map((a) => `${a.name} = ${this.P[a.index]}`);
      },
      /** Initial state; also fills the run constants in P. */
      initialState(t0 = 0) {
        const y = new Float64Array(nspecies);
        fns.init(t0, y, this.P, this.H, null, true);
        for (let i = 0; i < nspecies; i++) {
          if (!Number.isFinite(y[i])) throw new ModelError(`The initial value of ${species[i]} is not a number`);
        }
        return y;
      },
      /** Numerical check of the analytic Jacobian at (t, y): returns the worst entries. */
      verifyJacobian(t, y) { return verifyJacobian(this, t, y); },
      /** Dense Jacobian by finite differences, for checks. */
      denseNumericalJacobian(t, y) { return numericalJacobian(this, t, y).J; },
    };
    return model;
  }

  function collectStateRefs(ast, out = []) {
    switch (ast.type) {
      case 'call':
        if (ast.name.toLowerCase() === 'state' && ast.args[0] && ast.args[0].type === 'id') out.push(ast.args[0].name);
        else ast.args.forEach((a) => collectStateRefs(a, out));
        break;
      case 'neg': collectStateRefs(ast.a, out); break;
      case 'bin': collectStateRefs(ast.l, out); collectStateRefs(ast.r, out); break;
      default: break;
    }
    return out;
  }

  /** Column sets -> compressed sparse column pattern with sorted rows. */
  function toCSC(cols, n) {
    const colPtr = new Int32Array(n + 1);
    for (let j = 0; j < n; j++) colPtr[j + 1] = colPtr[j] + cols[j].size;
    const nnz = colPtr[n];
    const rowIdx = new Int32Array(nnz);
    for (let j = 0; j < n; j++) {
      const rows = [...cols[j]].sort((a, b) => a - b);
      let k = colPtr[j];
      for (const r of rows) rowIdx[k++] = r;
    }
    return { n, nnz, colPtr, rowIdx };
  }

  /* ------------------------------------------------------------------------
     generateCode: the five functions as source text
     ------------------------------------------------------------------------ */
  function generateCode(c) {
    const { species, speciesIndex, nspecies, Pindex, tableIndex, stringValues, equations, eqIndex, subst, reactions, pattern, pos, outputs, events, initial, clamp } = c;

    /**
     * Builds an Emitter whose name resolution covers species (effective values),
     * constants and the equations emitted so far in the same function.
     */
    function makeEmitter(mode) {
      const eqValues = new Map();          // equation name -> {v, g}
      const speciesValues = new Map();     // species index -> {v, g} (effective)
      const em = new Emitter({
        tableIndex(name, line) {
          if (tableIndex.has(name)) return tableIndex.get(name);
          if (stringValues.has(name) && tableIndex.has(stringValues.get(name))) return tableIndex.get(stringValues.get(name));
          throw new ModelError(`"${name}" is not a table`, line);
        },
        rawState(name, line, emitter) {
          const i = speciesIndex.get(name);
          if (mode === 'init') return { v: `y[${i}]`, g: new Map() };
          return { v: `y[${i}]`, g: new Map([[i, '1']]) };
        },
        resolve(name, line, emitter) {
          if (name === 't') return { v: 't', g: new Map() };
          if (speciesIndex.has(name)) {
            const i = speciesIndex.get(name);
            if (mode === 'init') return { v: `y[${i}]`, g: new Map() };
            if (speciesValues.has(i)) return speciesValues.get(i);
            // Not yet substituted: the raw (clamped) state.
            return baseSpecies(emitter, i);
          }
          if (Pindex.has(name)) return { v: `P[${Pindex.get(name)}]`, g: new Map() };
          if (eqValues.has(name)) return eqValues.get(name);
          if (eqIndex.has(name)) {
            if (mode === 'init') throw new ModelError(`"${name}" depends on the species and cannot be used in <INITIAL>`, line);
            throw new ModelError(`"${name}" is used before it is defined`, line);
          }
          if (stringValues.has(name) || tableIndex.has(name)) throw new ModelError(`"${name}" is a table; use interp(${name}, x)`, line);
          throw new ModelError(`"${name}" is not defined`, line);
        },
      });
      const baseSpecies = (emitter, i) => {
        if (!clamp) return { v: `y[${i}]`, g: new Map([[i, '1']]) };
        // The value is clamped at zero; the derivative is the right-hand one,
        // 1 at zero itself. Most species start at exactly zero, and their
        // consumption terms belong on the diagonal from the first step. A
        // step that leaves a species slightly negative is projected back to
        // zero by the solver (its NonNegative option, on by default), so the
        // Jacobian is never formed at a negative state, where the exact
        // derivative 0 would let Newton overshoot into the positive region.
        const v = emitter.temp(`(y[${i}] > 0 ? y[${i}] : 0)`);
        const d = emitter.temp(`(y[${i}] >= 0 ? 1 : 0)`);
        return { v, g: new Map([[i, d]]) };
      };
      return { em, eqValues, speciesValues };
    }

    /** Emits the equations in order (with @-substitutions) into an emitter. */
    function emitEquations(ctx, mode, upTo = equations.length) {
      const { em, eqValues, speciesValues } = ctx;
      for (let k = 0; k < upTo; k++) {
        const e = equations[k];
        if (e.thermo) {
          const T = eqValues.get('T');
          const a = e.thermo.map((v) => em.numLiteral(v));
          const RR = Pindex.has('R') ? `P[${Pindex.get('R')}]` : '1.98720425864083';
          // H = R T (a1 + a2 T/2 + a3 T^2/3 + a4 T^3/4 + a5 T^4/5 + a6/T); S = R (a1 ln T + a2 T + a3 T^2/2 + a4 T^3/3 + a5 T^4/4 + a7)
          const T2 = em.temp(`${T.v} * ${T.v}`), T3 = em.temp(`${T2} * ${T.v}`), T4 = em.temp(`${T3} * ${T.v}`);
          const h = em.temp(`${RR} * ${T.v} * (${a[0]} + ${a[1]} * ${T.v} / 2 + ${a[2]} * ${T2} / 3 + ${a[3]} * ${T3} / 4 + ${a[4]} * ${T4} / 5 + ${a[5]} / ${T.v})`);
          const s = em.temp(`${RR} * (${a[0]} * Math.log(${T.v}) + ${a[1]} * ${T.v} + ${a[2]} * ${T2} / 2 + ${a[3]} * ${T3} / 3 + ${a[4]} * ${T4} / 4 + ${a[6]})`);
          const g = em.temp(`${h} - ${T.v} * ${s}`);
          if (T.g.size) throw new ModelError('T may not depend on the species when <THERMO> data are used', e.line);
          eqValues.set(e.name, { v: g, g: new Map() });
          continue;
        }
        const r = em.emit(e.ast, e.line);
        const val = { v: r.v, g: r.g };
        if (e.substitution) speciesValues.set(speciesIndex.get(e.name), val);
        else eqValues.set(e.name, val);
      }
    }

    /** Value and gradient of the mass-action product of a side. */
    function massAction(em, ctx, side) {
      let v = '1';
      const terms = side.map((s) => ({ ...em.ctx.resolve(s.name, 0, em), coef: s.coef, i: speciesIndex.get(s.name) }));
      // value
      for (const tm of terms) {
        for (let q = 0; q < tm.coef; q++) v = em.mulCode(v, tm.v);
      }
      // gradient: sum over terms of coef * s^(coef-1) * prod(others) * ds
      let g = new Map();
      terms.forEach((tm, idx) => {
        if (em.isZero(tm.g)) return;
        let other = tm.coef === 1 ? '1' : em.numLiteral(tm.coef);
        for (let q = 1; q < tm.coef; q++) other = em.mulCode(other, tm.v);
        terms.forEach((o, jdx) => {
          if (jdx === idx) return;
          for (let q = 0; q < o.coef; q++) other = em.mulCode(other, o.v);
        });
        g = em.add(g, em.scale(tm.g, other));
      });
      return { v, g };
    }

    const sources = {};

    // ---- rhs and jac share the prefix: species, equations, then reactions ----
    for (const which of ['rhs', 'jac']) {
      const ctx = makeEmitter(which);
      const { em } = ctx;
      emitEquations(ctx, which);
      const body = [];
      const contributions = [];     // jac: { p, code }
      body.push(which === 'rhs' ? 'out.fill(0);' : 'out.fill(0);');
      reactions.forEach((r, ri) => {
        const parts = [];           // { sign: +1|-1, v, g }
        const addRate = (kAst, side, sign, absolute) => {
          const k = em.emit(kAst, r.line);
          let v, g;
          if (absolute) { v = k.v; g = k.g; } else {
            const ma = massAction(em, ctx, side);
            v = em.mulCode(k.v, ma.v);
            g = em.add(em.scale(k.g, ma.v), em.scale(ma.g, k.v));
          }
          parts.push({ sign, v, g });
        };
        if (r.ast.rf) addRate(r.ast.rf, r.reactants, 1, true);
        if (r.ast.kf) addRate(r.ast.kf, r.reactants, 1, false);
        if (r.ast.rb) addRate(r.ast.rb, r.products, -1, true);
        if (r.ast.kb) addRate(r.ast.kb, r.products, -1, false);
        if (r.ast.keq) {
          // kb = kf / keq
          const kf = em.emit(r.ast.kf, r.line);
          const keq = em.emit(r.ast.keq, r.line);
          const kb = em.emit({ type: 'bin', op: '/', l: { type: '_pre', pre: kf }, r: { type: '_pre', pre: keq } }, r.line);
          const ma = massAction(em, ctx, r.products);
          const v = em.mulCode(kb.v, ma.v);
          const g = em.add(em.scale(kb.g, ma.v), em.scale(ma.g, kb.v));
          parts.push({ sign: -1, v, g });
        }
        // Net rate R = sum(sign * part)
        let R = null, gR = new Map();
        parts.forEach((p) => {
          if (R === null) { R = p.sign > 0 ? p.v : em.temp(`-${p.v}`); gR = p.sign > 0 ? p.g : mapMap(p.g, (cd) => em.temp(`-${cd}`)); }
          else { R = em.temp(`${R} ${p.sign > 0 ? '+' : '-'} ${p.v}`); gR = em.add(gR, p.g, p.sign > 0 ? '+' : '-'); }
        });
        if (R === null) return;
        body.push(`// R${ri}: ${r.text.replace(/\s+/g, ' ')}`);
        for (const [i, coef] of r.net) {
          if (which === 'rhs') {
            body.push(coef === 1 ? `out[${i}] += ${R};` : coef === -1 ? `out[${i}] -= ${R};` : `out[${i}] += ${coef} * ${R};`);
          } else {
            for (const [j, gc] of gR) {
              const p = pos.get(`${i},${j}`);
              if (p === undefined) throw new ModelError(`Internal error: Jacobian entry (${species[i]}, ${species[j]}) is outside the pattern`, r.line);
              body.push(coef === 1 ? `out[${p}] += ${gc};` : coef === -1 ? `out[${p}] -= ${gc};` : `out[${p}] += ${coef} * ${gc};`);
            }
          }
        }
      });
      sources[which] = `"use strict";\n${em.lines.join('\n')}\n${body.join('\n')}\nreturn out;`;
    }

    // ---- observe: equations then outputs -------------------------------------
    {
      const ctx = makeEmitter('observe');
      const { em, eqValues } = ctx;
      emitEquations(ctx, 'observe');
      const names = [];
      const body = [];
      let k = 0;
      equations.forEach((e) => {
        if (e.substitution) return;
        names.push(e.name);
        body.push(`out[${k++}] = ${eqValues.get(e.name).v};`);
      });
      outputs.forEach((o) => {
        const r = em.emit(o.ast, o.line);
        eqValues.set(o.name, r);     // later outputs may use earlier ones
        names.push(o.name);
        body.push(`out[${k++}] = ${r.v};`);
      });
      sources.observe = `"use strict";\n${em.lines.join('\n')}\n${body.join('\n')}\nreturn out;`;
      c.observeNames = names;
    }

    // ---- events ---------------------------------------------------------------
    {
      const ctx = makeEmitter('events');
      const { em } = ctx;
      emitEquations(ctx, 'events');
      const body = events.map((ev, k) => `out[${k}] = ${em.emit(ev.ast, ev.line).v};`);
      sources.events = `"use strict";\n${em.lines.join('\n')}\n${body.join('\n')}\nreturn out;`;
    }

    // ---- init: time-only equations at t0, then the <INITIAL> lines -----------
    {
      const ctx = makeEmitter('init');
      const { em, eqValues } = ctx;
      // Only equations that do not depend on the species exist before the
      // state does; those are emitted, in order. A later equation that reads a
      // skipped one is itself species-dependent, so it is skipped as well, and
      // <INITIAL> reports it as unavailable if it is asked for.
      const deps = c.eqDeps;
      for (let k = 0; k < equations.length; k++) {
        const e = equations[k];
        const d = e.thermo ? deps[eqIndex.get('T')] : deps[k];
        if (d.size > 0 || e.substitution) continue;
        if (e.thermo) {
          const T = eqValues.get('T');
          if (!T) continue;
          const a = e.thermo.map((v) => em.numLiteral(v));
          const RR = Pindex.has('R') ? `P[${Pindex.get('R')}]` : '1.98720425864083';
          const T2 = em.temp(`${T.v} * ${T.v}`), T3 = em.temp(`${T2} * ${T.v}`), T4 = em.temp(`${T3} * ${T.v}`);
          const h = em.temp(`${RR} * ${T.v} * (${a[0]} + ${a[1]} * ${T.v} / 2 + ${a[2]} * ${T2} / 3 + ${a[3]} * ${T3} / 4 + ${a[4]} * ${T4} / 5 + ${a[5]} / ${T.v})`);
          const s = em.temp(`${RR} * (${a[0]} * Math.log(${T.v}) + ${a[1]} * ${T.v} + ${a[2]} * ${T2} / 2 + ${a[3]} * ${T3} / 3 + ${a[4]} * ${T4} / 4 + ${a[6]})`);
          eqValues.set(e.name, { v: em.temp(`${h} - ${T.v} * ${s}`), g: new Map() });
          continue;
        }
        const r = em.emit(e.ast, e.line);
        eqValues.set(e.name, { v: r.v, g: new Map() });
      }
      const body = [...em.lines];
      let cursor = em.lines.length;
      // The <INITIAL> lines, in order. Each assignment writes y[i] or P[k]
      // directly, so the temporaries of the next line must come after it, and
      // the common-subexpression table is cleared so that nothing computed from
      // an earlier value of y[i] or P[k] is reused.
      initial.forEach((e) => {
        const ast = parseExpression(e.expr, e.line);
        const r = em.emit(ast, e.line);
        body.push(...em.lines.slice(cursor));
        cursor = em.lines.length;
        if (speciesIndex.has(e.name)) {
          body.push(`if (extra !== false) y[${speciesIndex.get(e.name)}] = ${r.v};`);
        } else {
          body.push(`P[${Pindex.get(e.name)}] = ${r.v};`);
        }
        em.cse.clear();
      });
      // `extra` is speciesToo; the positional parameter `out` is unused here.
      sources.init = `"use strict";\n${body.join('\n')}\nreturn y;`;
    }

    return { sources, observeNames: c.observeNames };
  }

  /* The emitter accepts a pre-emitted operand through a private node type. */
  const originalEmit = Emitter.prototype.emit;
  Emitter.prototype.emit = function (ast, line) {
    if (ast.type === '_pre') return ast.pre;
    return originalEmit.call(this, ast, line);
  };

  /* ------------------------------------------------------------------------
     Numerical checks of the analytic Jacobian
     ------------------------------------------------------------------------ */
  function numericalJacobian(model, t, y, relStep = 1e-4) {
    const n = model.nspecies;
    const f0 = new Float64Array(n), fp = new Float64Array(n), fm = new Float64Array(n);
    const J = Array.from({ length: n }, () => new Float64Array(n));
    const yy = Float64Array.from(y);
    model.rhs(t, yy, f0);
    let ymax = 0;
    for (let i = 0; i < n; i++) ymax = Math.max(ymax, Math.abs(yy[i]));
    for (let j = 0; j < n; j++) {
      const yj = yy[j];
      if (yj !== 0) {
        // Central difference with a step relative to the variable itself.
        const h = relStep * Math.abs(yj);
        yy[j] = yj + h; model.rhs(t, yy, fp);
        yy[j] = yj - h; model.rhs(t, yy, fm);
        yy[j] = yj;
        for (let i = 0; i < n; i++) J[i][j] = (fp[i] - fm[i]) / (2 * h);
      } else {
        // At zero: forward differences (the right-hand derivative, as the
        // generated code has it for a clamped species), extrapolated from two
        // step sizes so that a quadratic term such as k*y^2 contributes 0 here
        // rather than k*h.
        const h = relStep * 1e-6 * Math.max(ymax, 1e-30);
        yy[j] = h; model.rhs(t, yy, fp);
        yy[j] = 2 * h; model.rhs(t, yy, fm);
        yy[j] = 0;
        for (let i = 0; i < n; i++) J[i][j] = (2 * (fp[i] - f0[i]) / h - (fm[i] - f0[i]) / (2 * h));
      }
    }
    return { J, f0 };
  }

  /**
   * Compares the analytic Jacobian with finite differences at (t, y).
   * An entry counts as a discrepancy when the two differ by more than 0.1 %
   * of the larger AND the difference is resolvable: the change it makes to
   * f_i over the perturbation exceeds 1e-9 of |f_i| (below that a finite
   * difference is round-off, not information).
   */
  function verifyJacobian(model, t, y) {
    const n = model.nspecies;
    const V = new Float64Array(model.nnz);
    model.jac(t, y, V);
    const { J: Jn, f0 } = numericalJacobian(model, t, y);
    const { colPtr, rowIdx } = model.pattern;
    const A = Array.from({ length: n }, () => new Float64Array(n));
    for (let j = 0; j < n; j++) for (let k = colPtr[j]; k < colPtr[j + 1]; k++) A[rowIdx[k]][j] = V[k];
    const inPattern = new Set();
    for (let j = 0; j < n; j++) for (let k = colPtr[j]; k < colPtr[j + 1]; k++) inPattern.add(rowIdx[k] * n + j);
    const discrepancies = [];
    let outside = null;
    let checked = 0;
    for (let j = 0; j < n; j++) {
      const hj = y[j] !== 0 ? 1e-4 * Math.abs(y[j]) : 1e-10 * 1e-30;
      for (let i = 0; i < n; i++) {
        const a = A[i][j], nm = Jn[i][j];
        const effect = Math.max(Math.abs(a), Math.abs(nm)) * hj;
        const resolvable = effect > 1e-9 * Math.abs(f0[i]) && effect > 1e-300;
        if (!resolvable) continue;
        checked++;
        const diff = Math.abs(a - nm);
        if (diff > 1e-3 * Math.max(Math.abs(a), Math.abs(nm))) {
          discrepancies.push({ row: model.species[i], col: model.species[j], analytic: a, numeric: nm });
        }
        if (!inPattern.has(i * n + j) && Math.abs(nm) > 0 && (!outside || Math.abs(nm) > Math.abs(outside.numeric))) {
          outside = { row: model.species[i], col: model.species[j], numeric: nm };
        }
      }
    }
    discrepancies.sort((p, q) => Math.abs(q.analytic - q.numeric) / Math.max(Math.abs(q.analytic), Math.abs(q.numeric)) - Math.abs(p.analytic - p.numeric) / Math.max(Math.abs(p.analytic), Math.abs(p.numeric)));
    return { checked, discrepancies, outsidePattern: outside, nnz: model.nnz };
  }

  return { compile, parseModelText, parseExpression, ModelError, interpTable, slopeTable, FUNCTIONS, evalAst };
});
