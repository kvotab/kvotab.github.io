/* ==========================================================================
   distributions.html: EXPRESSIONS OF DISTRIBUTIONS

   The Monte Carlo calculation draws every distribution an expression names
   and evaluates the expression draw by draw: "A * B + C", "exp(A) / (1 +
   B^2)", "max(A, B)". The letters are the distributions' letters; the rest
   is numbers, + - * / ^, parentheses and a few functions. The text is
   parsed here into a tree and evaluated over whole arrays at once; nothing
   in it is ever handed to eval.

   Grammar (^ binds tighter than a leading minus, and to the right):
     sum     = product (('+' | '-') product)*
     product = unary (('*' | '/') unary)*
     unary   = ('-' | '+') unary | power
     power   = atom ('^' unary)?
     atom    = number | letter | name '(' sum (',' sum)* ')' | '(' sum ')' | constant
   ========================================================================== */

const FUNCTIONS = {
  exp: [1, 1, Math.exp],
  ln: [1, 1, Math.log],
  log: [1, 1, Math.log],
  log10: [1, 1, Math.log10],
  sqrt: [1, 1, Math.sqrt],
  abs: [1, 1, Math.abs],
  floor: [1, 1, Math.floor],
  ceil: [1, 1, Math.ceil],
  pow: [2, 2, Math.pow],
  min: [2, Infinity, Math.min],
  max: [2, Infinity, Math.max],
};
const CONSTANTS = { pi: Math.PI, e: Math.E };

export const EXPRESSION_FUNCTIONS = Object.keys(FUNCTIONS);

/* ---- tokens ------------------------------------------------------------------ */

function tokenize(text) {
  const tokens = [];
  const re = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(\*\*|[-+*/^(),]))/y;
  let at = 0;
  /* the minus, times and division signs of typeset text are the operators */
  const src = String(text).replace(/[\u2212\u2013]/g, '-').replace(/[\u00d7\u00b7\u22c5]/g, '*').replace(/\u00f7/g, '/');
  while (at < src.length) {
    re.lastIndex = at;
    const m = re.exec(src);
    if (!m) {
      if (/^\s*$/.test(src.slice(at))) break;
      const where = src.slice(at).search(/\S/) + at;
      throw new Error(`Cannot read “${src[where]}” at position ${where + 1}.`);
    }
    at = re.lastIndex;
    if (m[1] !== undefined) tokens.push({ t: 'num', v: Number(m[1]), at });
    else if (m[2] !== undefined) tokens.push({ t: 'name', v: m[2], at });
    else tokens.push({ t: 'op', v: m[3] === '**' ? '^' : m[3], at });
  }
  return tokens;
}

/* ---- the parser --------------------------------------------------------------------- */

/**
 * The tree of an expression and the distribution letters it uses.
 *
 * @param {string} text
 * @param {function(string): boolean} isVariable   whether a name is a distribution
 * @returns {{tree: Object, variables: string[]}}
 */
export function parseExpression(text, isVariable) {
  const tokens = tokenize(text);
  if (!tokens.length) throw new Error('The expression is empty.');
  let i = 0;
  const variables = new Set();
  const peek = () => tokens[i];
  const take = (v) => {
    const t = tokens[i];
    if (!t || t.v !== v) throw new Error(t ? `Expected “${v}” before “${t.v}”.` : `Expected “${v}” at the end.`);
    i++;
  };
  function sum() {
    let node = product();
    while (peek() && (peek().v === '+' || peek().v === '-')) {
      const op = tokens[i++].v;
      node = { op, a: node, b: product() };
    }
    return node;
  }
  function product() {
    let node = unary();
    while (peek() && (peek().v === '*' || peek().v === '/')) {
      const op = tokens[i++].v;
      node = { op, a: node, b: unary() };
    }
    return node;
  }
  function unary() {
    const t = peek();
    if (t && t.t === 'op' && (t.v === '-' || t.v === '+')) {
      i++;
      const inner = unary();
      return t.v === '-' ? { op: 'neg', a: inner } : inner;
    }
    return power();
  }
  function power() {
    const base = atom();
    if (peek() && peek().v === '^') {
      i++;
      return { op: '^', a: base, b: unary() };
    }
    return base;
  }
  function atom() {
    const t = tokens[i++];
    if (!t) throw new Error('The expression ends too early.');
    if (t.t === 'num') return { num: t.v };
    if (t.t === 'op' && t.v === '(') {
      const node = sum();
      take(')');
      return node;
    }
    if (t.t === 'name') {
      if (peek() && peek().v === '(') {
        const f = Object.prototype.hasOwnProperty.call(FUNCTIONS, t.v) ? FUNCTIONS[t.v] : null;
        if (!f) throw new Error(`There is no function “${t.v}”. Functions: ${EXPRESSION_FUNCTIONS.join(', ')}.`);
        i++;
        const args = [sum()];
        while (peek() && peek().v === ',') { i++; args.push(sum()); }
        take(')');
        if (args.length < f[0] || args.length > f[1]) throw new Error(`${t.v}() takes ${f[0] === f[1] ? f[0] : `at least ${f[0]}`} argument${f[0] > 1 ? 's' : ''}.`);
        return { fn: t.v, args };
      }
      if (isVariable(t.v)) { variables.add(t.v); return { v: t.v }; }
      if (Object.prototype.hasOwnProperty.call(CONSTANTS, t.v)) return { num: CONSTANTS[t.v] };
      throw new Error(`There is no distribution “${t.v}”.`);
    }
    throw new Error(`Unexpected “${t.v}”.`);
  }
  const tree = sum();
  if (i < tokens.length) throw new Error(`Unexpected “${tokens[i].v}” after a complete expression.`);
  return { tree, variables: [...variables] };
}

/* ---- evaluation ------------------------------------------------------------------------ */

const BINARY = {
  '+': (x, y) => x + y,
  '-': (x, y) => x - y,
  '*': (x, y) => x * y,
  '/': (x, y) => x / y,
  '^': (x, y) => Math.pow(x, y),
};

/**
 * The expression evaluated over n draws: env maps each letter to a
 * Float64Array of n draws. Returns a Float64Array (or a number for an
 * expression without letters).
 */
export function evaluateExpression(tree, env, n) {
  function ev(node) {
    if (node.num !== undefined) return node.num;
    if (node.v !== undefined) return env[node.v];
    if (node.op === 'neg') {
      const a = ev(node.a);
      if (typeof a === 'number') return -a;
      const out = new Float64Array(n);
      for (let i = 0; i < n; i++) out[i] = -a[i];
      return out;
    }
    if (node.op) {
      const f = BINARY[node.op];
      const a = ev(node.a);
      const b = ev(node.b);
      if (typeof a === 'number' && typeof b === 'number') return f(a, b);
      const out = new Float64Array(n);
      if (typeof a === 'number') for (let i = 0; i < n; i++) out[i] = f(a, b[i]);
      else if (typeof b === 'number') for (let i = 0; i < n; i++) out[i] = f(a[i], b);
      else for (let i = 0; i < n; i++) out[i] = f(a[i], b[i]);
      return out;
    }
    const fn = FUNCTIONS[node.fn][2];
    const args = node.args.map(ev);
    if (args.every((a) => typeof a === 'number')) return fn(...args);
    const out = new Float64Array(n);
    const vals = new Array(args.length);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < args.length; j++) vals[j] = typeof args[j] === 'number' ? args[j] : args[j][i];
      out[i] = fn(...vals);
    }
    return out;
  }
  return ev(tree);
}
