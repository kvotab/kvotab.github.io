/* ==========================================================================
   4e. MATLAB FIGURES (.fig)

   A figure file is a MAT-file (rb-mat.js reads it) whose variable hgS_070000
   -- hgS_050200 in files of MATLAB 5 to 7 -- holds the figure as a tree of
   structs, one for each graphics object:

       type        'figure', 'axes', 'line', 'text', 'uicontrol', ...
       handle      its handle when the figure was saved
       properties  the properties it was saved with, by name
       children    a struct array of the same: its children, the first made
                   first
       special     for an axes, where among its children its title, x, y and
                   z labels are, counted from 1, 0 for one not saved

   Releases from R2014b keep each figure in a form of their own as well,
   hgM_070000, and savefig's 'compact' keeps that one alone. It is shown as
   any variable is and not drawn: the objects it holds are in a part of the
   file MATLAB does not describe.

   In the tree the figure is its objects: each a group named by its place
   among its parent's children, its type and its name or text --

       (1) axes
       (03) graph2d.lineseries 'Ra-226'
       (44) text YLabel 'Mean annual effective dose (\muSv)'

   -- holding its children first and then its properties, a dataset or a
   group each as for any MAT-file; its type, handle and special are its
   attributes.

   Selecting the file, the figure's variable or any object in it draws the
   figure in the information panel, as MATLAB shows it, in SVG (figShowFor).
   The object selected stands out from the rest, and an object clicked in the
   drawing is selected in the tree.
   ========================================================================== */

'use strict';   // see the script manifest in rb.html for why

/* The variables that hold a figure, and the fields each of its objects has. */
const FIG_VARIABLE = /^hgS_\d+$/;
const FIG_NEW_FORM = /^hgM_\d+$/;
const FIG_FIELDS = ['type', 'handle', 'properties', 'children', 'special'];

/* How far a file may take the page. */
const FIG_MAX_DEPTH = 40;        // objects within objects
const FIG_LABEL_CHARS = 40;      // of a name or text shown in an object's name

/* An axes' special: its title and labels, in that order. */
const FIG_LABELS = ['Title', 'XLabel', 'YLabel', 'ZLabel'];

/**
 * The figures of the files open, by the h5wasm file each opened as: when the
 * file is closed or opened again, its figure goes with it.
 */
const figModels = new WeakMap();

/* ── values, as the file holds them ──────────────────────────────────── */

const figNumbersCache = new WeakMap();

/** An array's real numbers as doubles, in MATLAB's order; null for an array of any other class. */
function figNumbers(a) {
  if (!a || typeof a !== 'object' || !MAT_NUMERIC[a.cls] || !a.re) return null;
  if (a.re instanceof Float64Array) return a.re;
  let out = figNumbersCache.get(a);
  if (!out) {
    out = new Float64Array(a.re.length);
    for (let k = 0; k < out.length; k++) out[k] = Number(a.re[k]);
    figNumbersCache.set(a, out);
  }
  return out;
}

function figNumber(a, fallback = NaN) {
  const v = figNumbers(a);
  return v && v.length ? v[0] : fallback;
}

/** An array's size, at least two dimensions. */
function figDims(a) {
  return a && Array.isArray(a.dims) && a.dims.length >= 2 ? a.dims : [0, 0];
}

/** A number as MATLAB writes it short: 0.3333, 1e+06. */
function figShortNumber(x) {
  if (!Number.isFinite(x)) return Number.isNaN(x) ? 'NaN' : (x > 0 ? 'Inf' : '-Inf');
  const s = String(Number(x.toPrecision(5)));
  return s.replace(/e\+?/, 'e+').replace('e+-', 'e-');
}

/**
 * Text as lines: a char array's rows, each element of a cell, the numbers of
 * a numeric array; a newline in a row starts another line.
 */
function figLines(a) {
  if (!a || typeof a !== 'object') return [];
  if (a.cls === 'char') {
    const [rows, cols] = figDims(a);
    if (rows <= 1) return matString(a.units).split(/\r\n|\n|\r/);
    const out = [];
    const row = new Uint16Array(cols);
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) row[j] = a.units[i + rows * j];
      out.push(...matString(row).replace(/\s+$/, '').split(/\r\n|\n|\r/));
    }
    return out;
  }
  if (a.cls === 'cell') return (a.items || []).flatMap(x => (x && x.cls === 'char' && !figDims(x)[0] ? [''] : figLines(x)));
  const v = figNumbers(a);
  return v ? Array.from(v, figShortNumber) : [];
}

/** Text as one string; a word such as a property's 'on' trimmed of the spaces around it. */
function figText(a) {
  return figLines(a).join('\n');
}

function figWord(a) {
  return a && a.cls === 'char' ? matString(a.units).trim().toLowerCase() : '';
}

/** Whether a property says on, as text or as a number; `fallback` when it says neither. */
function figOn(a, fallback) {
  const w = figWord(a);
  if (w === 'on' || w === 'true') return true;
  if (w === 'off' || w === 'false') return false;
  const v = figNumbers(a);
  return v && v.length ? v[0] !== 0 : fallback;
}

const FIG_COLOR_NAMES = {
  r: [1, 0, 0], red: [1, 0, 0], g: [0, 1, 0], green: [0, 1, 0], b: [0, 0, 1], blue: [0, 0, 1],
  c: [0, 1, 1], cyan: [0, 1, 1], m: [1, 0, 1], magenta: [1, 0, 1], y: [1, 1, 0], yellow: [1, 1, 0],
  k: [0, 0, 0], black: [0, 0, 0], w: [1, 1, 1], white: [1, 1, 1]
};

/**
 * A colour: [r, g, b] from 0 to 1, from three numbers, a name or #rrggbb;
 * else the word it is ('none', 'flat', 'interp', 'auto'), or null.
 */
function figColor(a) {
  const v = figNumbers(a);
  if (v && v.length >= 3) {
    const scale = a.cls === 'uint8' ? 255 : 1;
    const c = [v[0], v[1], v[2]].map(x => Math.min(1, Math.max(0, x / scale)));
    return c.every(Number.isFinite) ? c : null;
  }
  const s = figWord(a);
  if (!s) return null;
  if (FIG_COLOR_NAMES[s]) return FIG_COLOR_NAMES[s];
  if (/^#[0-9a-f]{6}$/.test(s)) return [1, 3, 5].map(k => parseInt(s.slice(k, k + 2), 16) / 255);
  if (/^#[0-9a-f]{3}$/.test(s)) return [1, 2, 3].map(k => parseInt(s[k] + s[k], 16) / 255);
  return s;
}

/** A colour as CSS; `fallback` for one that is not three numbers. */
function figCss(c, fallback = 'none') {
  if (!Array.isArray(c)) return fallback;
  return `rgb(${c.map(x => Math.round(x * 255)).join(',')})`;
}

/* ── the objects, laid out in the tree ───────────────────────────────── */

/** Whether an array is a struct of graphics objects as a figure file saves them. */
function figIsObjects(a) {
  return !!(a && a.cls === 'struct' && Array.isArray(a.fields) && FIG_FIELDS.every(f => a.fields.includes(f)));
}

/** A field of element k of a struct, or null. */
function figField(a, k, name) {
  const j = a.fields.indexOf(name);
  return j >= 0 && a.items[k] ? a.items[k][j] : null;
}

/** A property of a one-element struct of properties, by name in any case, or null. */
function figStructProp(s, name) {
  if (!s || s.cls !== 'struct' || matNumel(figDims(s)) !== 1) return null;
  const low = name.toLowerCase();
  const j = s.fields.findIndex(f => f.toLowerCase() === low);
  return j >= 0 ? s.items[0][j] : null;
}

/** Text from a file made fit to be part of a name in the tree: one line, not too long. */
function figLabelText(s) {
  const one = String(s || '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ').replace(/\s+/g, ' ').trim();
  return one.length > FIG_LABEL_CHARS ? `${one.slice(0, FIG_LABEL_CHARS - 1).trimEnd()}…` : one;
}

/** What an object is called after its type: a line's DisplayName, a text's String, a menu's Label. */
function figObjectLabel(type, props) {
  const t = type.toLowerCase();
  const text = (name) => figLines(figStructProp(props, name)).find(s => s.trim()) || '';
  if (t === 'figure') return text('Name');
  if (t === 'text' || t === 'uicontrol' || t.endsWith('textbox') || t.endsWith('textarrow')) return text('String');
  if (t === 'uimenu') return text('Label') || text('Text');
  if (t === 'uipanel' || t === 'uitab' || t.endsWith('buttongroup')) return text('Title');
  if (t === 'axes') return text('Tag');
  return text('DisplayName');
}

/**
 * The names of the children of one object: their place, zero-padded as the
 * tree sorts names as text, their type, a label's part and their label.
 */
function figChildNames(kids, roles) {
  const n = matNumel(figDims(kids));
  const width = String(n).length;
  const names = [];
  for (let i = 0; i < n; i++) {
    const type = figLabelText(matRowText(figField(kids, i, 'type'))) || 'object';
    const role = roles.get(i + 1);
    const label = figObjectLabel(type, figField(kids, i, 'properties'));
    names.push(easLinkName(`(${String(i + 1).padStart(width, '0')}) ${type}${role ? ` ${role}` : ''}${label ? ` '${figLabelText(label)}'` : ''}`));
  }
  return names;
}

/**
 * A string array's text as a char array of its strings, so that the drawing
 * reads it as any other text. Other values are left as they are.
 */
function figPlainValue(value, objects) {
  if (!value || value.cls !== 'opaque' || value.className !== 'string' || !objects || objects.error) return value;
  try {
    const ref = matObjectRef(value.data);
    const props = ref && ref.ids.length === 1 ? objects.propsOf(ref.ids[0]) : null;
    const any = props && props.find(p => p.name === 'any');
    if (!any) return value;
    const s = matStringArray(any.value);
    return { cls: 'cell', dims: s.dims, items: s.strings.map(t => ({ cls: 'char', dims: [1, t.length], units: matUnits(t) })) };
  } catch (_) {
    return value;
  }
}

/**
 * One graphics object -- element k of a struct of them -- as the group it is
 * written as, and as the object the drawing reads: { type, handle, props
 * (by lower-case name), children, special, role, path, parent }.
 */
function figObjectNode(a, k, ctx, model, path, parent, depth) {
  if (++ctx.arrays > MAT_MAX_ARRAYS) {
    ctx.capped = true;
    return null;
  }
  const type = matRowText(figField(a, k, 'type')).trim();
  const handle = figNumber(figField(a, k, 'handle'));
  const special = Array.from(figNumbers(figField(a, k, 'special')) || [], Math.round).filter(Number.isFinite);
  const obj = { type, low: type.toLowerCase(), handle, props: new Map(), children: [], special, role: null, path, parent };
  model.objects++;
  model.byPath.set(path, obj);
  if (Number.isFinite(handle) && !model.byHandle.has(handle)) model.byHandle.set(handle, obj);

  const group = easGroup({
    type: type || undefined,
    handle: Number.isFinite(handle) ? handle : undefined,
    special: special.length ? `[${special.join(' ')}]` : undefined
  });

  const kids = figField(a, k, 'children');
  if (figIsObjects(kids) && matNumel(figDims(kids))) {
    // Which of its children an axes' title and labels are.
    const roles = new Map();
    special.forEach((at, i) => { if (at > 0 && i < FIG_LABELS.length) roles.set(at, FIG_LABELS[i]); });
    if (depth >= FIG_MAX_DEPTH) {
      group.attrs.MATLAB_note = `Objects nested more than ${FIG_MAX_DEPTH} deep are not shown.`;
    } else {
      const names = figChildNames(kids, roles);
      for (let i = 0; i < names.length; i++) {
        const child = figObjectNode(kids, i, ctx, model, `${path}/${names[i]}`, obj, depth + 1);
        if (!child) break;
        child.obj.role = roles.get(i + 1) || null;
        obj.children.push(child.obj);
        matPut(group, names[i], child.node);
      }
    }
  } else if (kids && matNumel(figDims(kids)) && !figIsObjects(kids)) {
    const node = matNode(kids, ctx, depth + 1, new Set());
    if (node) matPut(group, 'children', node);
  }

  const props = figField(a, k, 'properties');
  if (props && props.cls === 'struct' && matNumel(figDims(props)) === 1) {
    props.fields.forEach((name, j) => {
      const value = props.items[0][j];
      obj.props.set(name.toLowerCase(), figPlainValue(value, ctx.objects));
      const node = matNode(value, ctx, depth + 1, new Set());
      if (node) matPut(group, easLinkName(name), node);
    });
  } else if (props && matNumel(figDims(props))) {
    const node = matNode(props, ctx, depth + 1, new Set());
    if (node) matPut(group, 'properties', node);
  }

  // Anything else a file keeps with an object, as it is.
  a.fields.forEach((field, j) => {
    if (FIG_FIELDS.includes(field)) return;
    const node = matNode(a.items[k][j], ctx, depth + 1, new Set());
    if (node) matPut(group, easLinkName(field), node);
  });
  return { node: group, obj };
}

/**
 * The figures some objects draw: a figure itself, a root's figures, and
 * any other object -- an axes saved alone -- in a figure of its own.
 */
function figFiguresOf(objects) {
  const out = [];
  for (const o of objects) {
    if (o.low === 'figure') out.push(o);
    else if (o.low === 'root') out.push(...figFiguresOf(o.children));
    else {
      if (!o.ownFigure) {
        o.ownFigure = { type: 'figure', low: 'figure', handle: NaN, props: new Map(), children: [o], special: [],
                        role: null, path: o.path, parent: null, made: true };
      }
      out.push(o.ownFigure);
    }
  }
  return out;
}

/**
 * The variable written as the objects it holds (matTree's hook), or
 * undefined for a variable that is no figure, which matTree writes as it
 * writes any.
 */
function figVariableNode(v, ctx, path, model) {
  const a = v.array;
  if (!FIG_VARIABLE.test(v.name || '') || !figIsObjects(a)) return undefined;
  const numel = matNumel(figDims(a));
  const tops = [];
  let group;
  if (numel === 1) {
    const one = figObjectNode(a, 0, ctx, model, path, null, 0);
    if (!one) return null;
    group = one.node;
    group.attrs = { ...matAttrs('struct', a.dims), ...group.attrs };
    tops.push(one.obj);
  } else {
    group = easGroup(matAttrs('struct', a.dims));
    const names = figChildNames(a, new Map());
    for (let k = 0; k < numel; k++) {
      const one = figObjectNode(a, k, ctx, model, `${path}/${names[k]}`, null, 1);
      if (!one) break;
      tops.push(one.obj);
      matPut(group, names[k], one.node);
    }
  }
  const figures = figFiguresOf(tops);
  model.roots.set(path, figures);
  model.figures.push(...figures);
  return group;
}

/**
 * The figure a MAT-file holds: the hooks matTree writes it by, and the model
 * the drawing reads, which those fill in as the tree is written. Null when no
 * variable is a figure and none is MATLAB's other form of one.
 *
 * @param {string} fileName
 * @param {Object} mat - From readMatFile
 * @returns {{model: Object, hooks: Object}|null}
 */
function figFileModel(fileName, mat) {
  const holds = (re) => mat.variables.some(v => re.test(v.name || ''));
  if (!mat.variables.some(v => !v.error && FIG_VARIABLE.test(v.name || '') && figIsObjects(v.array)) && !holds(FIG_NEW_FORM)) return null;
  const platform = (/Platform:\s*([A-Za-z0-9_]+)/.exec(mat.header || '') || [])[1] || '';
  const mac = /^MAC/i.test(platform);
  const model = {
    fileName,
    platform,
    // MATLAB's own releases before R2014b wrote no hgM_; what other programs
    // write, as SciPy does, is read with the defaults of the later releases.
    hg2: holds(FIG_NEW_FORM) || !/^(PCWIN|MAC|GLNX|SOL|HP|ALPHA|IBM|SGI|LNX)/i.test(platform),
    newForm: holds(FIG_NEW_FORM),
    // A pixel is 1/72 inch on a Mac and 1/96 elsewhere; a character is a
    // letter of the system's font.
    ppi: mac ? 72 : 96,
    chars: mac ? [6, 15] : [5, 13],
    roots: new Map(),
    byPath: new Map(),
    byHandle: new Map(),
    figures: [],
    objects: 0
  };
  const hooks = {
    variableNode: (v, ctx, path) => figVariableNode(v, ctx, path, model),
    done: () => model.roots.set('/', model.figures)
  };
  return { model, hooks };
}

/** What the root's Information says of a figure file, as markup. */
function figDescribe(model) {
  const e = escapeHtml;
  if (!model.figures.length) {
    return '<p>A MATLAB figure kept only in the form MATLAB uses from R2014b (hgM_070000), as savefig\'s '
      + '<em>compact</em> saves it, which this page does not draw.</p>';
  }
  const counts = new Map();
  const count = (o) => {
    for (const c of o.children) {
      counts.set(c.low, (counts.get(c.low) || 0) + 1);
      count(c);
    }
  };
  model.figures.forEach(count);
  const what = [...counts].filter(([t]) => ['axes', 'graph2d.lineseries', 'line', 'patch', 'surface', 'image', 'text', 'uicontrol'].includes(t))
    .map(([t, n]) => `${n.toLocaleString('en-US')} ${t}`);
  const figs = model.figures.length;
  return `<p>A MATLAB figure file: ${figs === 1 ? 'one figure' : `${figs} figures`}${what.length ? ` (${e(what.join(', '))})` : ''}. `
    + 'Each object is a group of its children and its properties. Select the file, the figure or any object in it to see the figure drawn.</p>';
}

/** Keep a file's figure with the file it was opened as. */
function figRegister(fileKey, model) {
  const file = loadedFiles[fileKey];
  if (file && model) figModels.set(file, model);
}

/** The figure of an open file, or null. */
function figModelOf(fileKey) {
  const file = loadedFiles[fileKey];
  return file ? figModels.get(file) || null : null;
}

/**
 * What selecting a path in a file draws: the figures, and the object to set
 * apart, or null when the path is no figure or object of one.
 */
function figTarget(model, path) {
  if (!model) return null;
  if (model.roots.has(path)) return { figures: model.roots.get(path), highlight: null };
  const obj = model.byPath.get(path);
  if (!obj) return null;
  let fig = obj;
  while (fig && fig.low !== 'figure') fig = fig.parent;
  if (fig) return { figures: [fig], highlight: obj === fig ? null : obj };
  return { figures: figFiguresOf([obj]), highlight: null };
}

/* ── drawing: SVG, fonts and text ────────────────────────────────────── */

const FIG_SVG = 'http://www.w3.org/2000/svg';

/* Each drawing's clip paths are named apart from every other's on the page. */
let figDrawings = 0;

function figEl(name, attrs, parent) {
  const el = document.createElementNS(FIG_SVG, name);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v !== undefined && v !== null && v !== false) el.setAttribute(k, String(v));
  }
  if (parent) parent.appendChild(el);
  return el;
}

/** The smallest and largest finite values of many, or null when none is: a loop, as spreading a million into Math.min overflows the stack. */
function figRange(values) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : null;
}

/** A coordinate as written into a path: two decimals are a hundredth of a pixel. */
function figN(v) {
  return Math.round(v * 100) / 100;
}

/* MATLAB's font names, and what a browser has to draw them with. */
const FIG_FONTS = {
  helvetica: 'Helvetica, Arial, "Liberation Sans", sans-serif',
  arial: 'Arial, Helvetica, "Liberation Sans", sans-serif',
  'ms sans serif': 'Tahoma, Verdana, Arial, sans-serif',
  'lucida grande': '"Lucida Grande", Helvetica, Arial, sans-serif',
  times: '"Times New Roman", Times, serif',
  'times new roman': '"Times New Roman", Times, serif',
  courier: '"Courier New", Courier, monospace',
  'courier new': '"Courier New", Courier, monospace',
  fixedwidth: '"Courier New", Courier, monospace',
  'lucida sans typewriter': '"Lucida Sans Typewriter", "Lucida Console", Menlo, monospace',
  symbol: 'Symbol, serif'
};

/** A font family as CSS: MATLAB's name first, when it is one a browser might have. */
function figFamily(name) {
  const n = String(name || '').trim();
  const known = FIG_FONTS[n.toLowerCase()];
  if (known) return known;
  const safe = n.replace(/["\\;{}<>]/g, '');
  return safe ? `"${safe}", Helvetica, Arial, sans-serif` : FIG_FONTS.helvetica;
}

let figMeasureContext = null;

/** How wide a run of text is drawn, in pixels. */
function figMeasure(text, size, family, bold, italic) {
  if (!figMeasureContext) figMeasureContext = document.createElement('canvas').getContext('2d');
  if (!figMeasureContext) return text.length * size * 0.55;
  figMeasureContext.font = `${italic ? 'italic ' : ''}${bold ? 'bold ' : ''}${size}px ${family}`;
  return figMeasureContext.measureText(text).width;
}

/*
 * The characters MATLAB's TeX reading gives a name, as its documentation
 * lists them, and the few TeX names people use beside those.
 */
const FIG_TEX = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ϵ', varepsilon: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ',
  vartheta: 'ϑ', iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', varpi: 'ϖ', rho: 'ρ',
  sigma: 'σ', varsigma: 'ς', tau: 'τ', upsilon: 'υ', phi: 'ϕ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ', Upsilon: 'ϒ', Phi: 'Φ',
  Psi: 'Ψ', Omega: 'Ω',
  sim: '∼', leq: '≤', infty: '∞', clubsuit: '♣', diamondsuit: '♦', heartsuit: '♥', spadesuit: '♠',
  leftrightarrow: '↔', leftarrow: '←', Leftarrow: '⇐', uparrow: '↑', rightarrow: '→', Rightarrow: '⇒',
  downarrow: '↓', circ: '°', pm: '±', geq: '≥', propto: '∝', partial: '∂', bullet: '•', div: '÷',
  neq: '≠', equiv: '≡', approx: '≈', aleph: 'ℵ', Im: 'ℑ', Re: 'ℜ', wp: '℘', otimes: '⊗', oplus: '⊕',
  oslash: '⊘', cap: '∩', cup: '∪', supseteq: '⊇', supset: '⊃', subseteq: '⊆', subset: '⊂', int: '∫', in: '∈',
  o: 'ο', rfloor: '⌋', lceil: '⌈', nabla: '∇', lfloor: '⌊', cdot: '·', ldots: '…', perp: '⊥', neg: '¬',
  prime: '′', wedge: '∧', times: '×', 0: '∅', rceil: '⌉', surd: '√', mid: '|', vee: '∨', copyright: '©',
  langle: '⟨', rangle: '⟩', forall: '∀', exists: '∃', ni: '∋', cong: '≅', deg: '°', degree: '°', sum: '∑',
  prod: '∏', sqrt: '√', AA: 'Å', aa: 'å', ast: '∗', star: '⋆', mp: '∓', ll: '≪', gg: '≫',
  hbar: 'ℏ', ell: 'ℓ', angle: '∠', emptyset: '∅', notin: '∉', setminus: '∖', dots: '…', cdots: '⋯',
  textdegree: '°', dagger: '†', ddagger: '‡', euro: '€', pounds: '£'
};

/* What MATLAB's TeX reading does besides naming characters. */
const FIG_TEX_COMMANDS = new Set(['bf', 'it', 'sl', 'rm', 'fontname', 'fontsize', 'color']);

/* Named colours \color takes. */
const FIG_TEX_COLORS = {
  red: [1, 0, 0], green: [0, 1, 0], blue: [0, 0, 1], cyan: [0, 1, 1], magenta: [1, 0, 1], yellow: [1, 1, 0],
  black: [0, 0, 0], white: [1, 1, 1], gray: [0.5, 0.5, 0.5], darkgreen: [0, 0.5, 0], orange: [1, 0.5, 0],
  lightblue: [0.3, 0.8, 0.9]
};

/**
 * One line of text as runs drawn alike: { text, level (1 a superscript,
 * -1 a subscript), bold, italic, size (points, or null), family, color }.
 * With the 'tex' interpreter MATLAB reads ^ and _, braces, \bf, \it, \rm,
 * \fontname, \fontsize, \color and the names of characters; with 'latex'
 * its maths is read the same way, here, inside $...$; with 'none', the text
 * is itself.
 */
function figTexRuns(s, interpreter) {
  const text = String(s ?? '');
  if (interpreter === 'none') return [{ text, level: 0 }];
  const src = interpreter === 'latex' ? text.replace(/\$+/g, '') : text;
  const runs = [];
  const base = { level: 0, bold: false, italic: false, size: null, family: null, color: null };
  let i = 0;

  const emit = (t, st) => {
    if (!t) return;
    const last = runs[runs.length - 1];
    if (last && last.level === st.level && last.bold === st.bold && last.italic === st.italic && last.size === st.size
        && last.family === st.family && last.color === st.color) last.text += t;
    else runs.push({ text: t, ...st });
  };
  const argument = () => {
    // {text} after a command, or nothing
    if (src[i] !== '{') return '';
    const end = src.indexOf('}', i);
    if (end < 0) return '';
    const v = src.slice(i + 1, end);
    i = end + 1;
    return v;
  };
  const command = (st) => {
    // at a backslash: a character, a style, or the backslash itself
    i++;
    if (i >= src.length) { emit('\\', st); return; }
    const c = src[i];
    if (!/[A-Za-z0]/.test(c)) { emit(c, st); i++; return; }
    let name = '';
    if (c === '0') { name = '0'; i++; }
    else {
      // MATLAB takes the longest name it knows at the head of the letters
      // that follow, and the rest as text: \muSv is a mu and Sv.
      let word = '';
      while (i < src.length && /[A-Za-z]/.test(src[i])) word += src[i++];
      const known = (w) => FIG_TEX_COMMANDS.has(w) || Object.prototype.hasOwnProperty.call(FIG_TEX, w);
      let k = word.length;
      while (k > 1 && !known(word.slice(0, k))) k--;
      if (known(word.slice(0, k))) { name = word.slice(0, k); i -= word.length - k; } else name = word;
    }
    switch (name) {
      case 'bf': st.bold = true; return;
      case 'it': case 'sl': st.italic = true; return;
      case 'rm': st.bold = false; st.italic = false; return;
      case 'fontname': { const f = argument(); if (f) st.family = f; return; }
      case 'fontsize': { const n = parseFloat(argument()); if (n > 0 && n < 400) st.size = n; return; }
      case 'color': {
        if (src[i] === '[') {
          const end = src.indexOf(']', i);
          i = end < 0 ? src.length : end + 1;
          const v = argument().trim().split(/[\s,]+/).map(Number);
          if (v.length === 3 && v.every(x => x >= 0 && x <= 1)) st.color = figCss(v);
        } else {
          const n = argument().trim().toLowerCase();
          if (FIG_TEX_COLORS[n]) st.color = figCss(FIG_TEX_COLORS[n]);
        }
        return;
      }
      default:
        if (Object.prototype.hasOwnProperty.call(FIG_TEX, name)) emit(FIG_TEX[name], st);
        else emit(`\\${name}`, st);
    }
  };
  const group = (st, closing) => {
    while (i < src.length) {
      const c = src[i];
      if (c === '}' && closing) { i++; return; }
      if (c === '{') { i++; group({ ...st }, true); continue; }
      if (c === '\\') { command(st); continue; }
      if ((c === '^' || c === '_') && i + 1 < src.length) {
        i++;
        const inner = { ...st, level: st.level + (c === '^' ? 1 : -1) };
        if (src[i] === '{') { i++; group(inner, true); }
        else if (src[i] === '\\') command(inner);
        else emit(src[i++], inner);
        continue;
      }
      emit(c, st);
      i++;
    }
  };
  group({ ...base }, false);
  return runs.length ? runs : [{ text: '', level: 0 }];
}

/**
 * Draw text as MATLAB does: lines, each read by its interpreter, placed by
 * its alignment about (x, y), turned by `rotation` degrees counterclockwise,
 * with a box behind it when it has a background or an edge.
 *
 * opts: size (px), family, bold, italic, color, halign ('left', 'center',
 * 'right'), valign ('top', 'cap', 'middle', 'baseline', 'bottom'),
 * rotation, interpreter, background, edge, edgeWidth, margin (px), pt (px
 * per point, for \fontsize).
 *
 * @returns {{width: number, height: number}} The size of the text's box
 */
function figDrawText(parent, lines, x, y, opts) {
  const size = Number.isFinite(opts.size) && opts.size > 0 ? Math.min(opts.size, 400) : 10;
  const family = opts.family || FIG_FONTS.helvetica;
  const list = (Array.isArray(lines) ? lines : [lines]).map(String);
  if (!list.length || list.every(s => s === '')) return { width: 0, height: 0 };
  const lineH = size * 1.2;
  const ascent = size * 0.9;
  const descent = size * 0.22;
  const pt = opts.pt || 1;
  const sizeOf = (r) => (r.size ? r.size * pt : size) * Math.pow(0.7, Math.abs(r.level));
  const parsed = list.map(s => figTexRuns(s, opts.interpreter));
  const widths = parsed.map(runs => runs.reduce((w, r) => w + figMeasure(r.text, sizeOf(r), r.family ? figFamily(r.family) : family,
    r.bold || opts.bold, r.italic || opts.italic), 0));
  const width = Math.max(0, ...widths);
  const height = (list.length - 1) * lineH + ascent + descent;
  let top;
  switch (opts.valign) {
    case 'top': top = 0; break;
    case 'cap': top = -(ascent - size * 0.72); break;
    case 'baseline': top = -((list.length - 1) * lineH + ascent); break;
    case 'bottom': top = -height; break;
    default: top = -height / 2;
  }
  const anchor = opts.halign === 'center' ? 'middle' : opts.halign === 'right' ? 'end' : 'start';
  const left = opts.halign === 'center' ? -width / 2 : opts.halign === 'right' ? -width : 0;
  const g = figEl('g', opts.rotation ? { transform: `translate(${figN(x)} ${figN(y)}) rotate(${figN(-opts.rotation)})` }
    : { transform: `translate(${figN(x)} ${figN(y)})` }, parent);
  const margin = opts.margin || 0;
  if ((opts.background && opts.background !== 'none') || (opts.edge && opts.edge !== 'none')) {
    figEl('rect', {
      x: figN(left - margin), y: figN(top - margin), width: figN(width + 2 * margin), height: figN(height + 2 * margin),
      fill: opts.background && opts.background !== 'none' ? opts.background : 'none',
      stroke: opts.edge && opts.edge !== 'none' ? opts.edge : 'none', 'stroke-width': opts.edgeWidth || 0.5
    }, g);
  }
  parsed.forEach((runs, k) => {
    const baseline = top + ascent + k * lineH;
    const t = figEl('text', {
      x: 0, y: figN(baseline), 'text-anchor': anchor, 'font-family': family, 'font-size': figN(size),
      'font-weight': opts.bold ? 'bold' : null, 'font-style': opts.italic ? 'italic' : null, fill: opts.color || '#000'
    }, g);
    t.style.whiteSpace = 'pre';   // spaces as the text has them, as MATLAB draws them
    let shift = 0;
    for (const r of runs) {
      const rs = sizeOf(r);
      const want = r.level > 0 ? -size * 0.38 * r.level : r.level < 0 ? size * 0.22 * -r.level : 0;
      const span = figEl('tspan', {
        dy: want !== shift ? figN(want - shift) : null,
        'font-size': rs !== size ? figN(rs) : null,
        'font-family': r.family ? figFamily(r.family) : null,
        'font-weight': r.bold && !opts.bold ? 'bold' : null,
        'font-style': r.italic && !opts.italic ? 'italic' : null,
        fill: r.color || null
      }, t);
      span.textContent = r.text;
      shift = want;
    }
  });
  return { width, height };
}

/* ── colour maps and ticks ───────────────────────────────────────────── */

/** MATLAB's jet, for a figure that keeps no colour map of its own. */
function figJet(n = 64) {
  const out = [];
  for (let k = 0; k < n; k++) {
    const t = (k + 0.5) / n * 4;
    const ch = (c) => Math.min(1, Math.max(0, Math.min(t - c + 1.5, -t + c + 1.5)));
    out.push([ch(3), ch(2), ch(1)]);
  }
  return out;
}

/** A colour map, rows of [r, g, b], from an n×3 array; null when it is not one. */
function figColormap(a) {
  const v = figNumbers(a);
  const [n, three] = figDims(a);
  if (!v || three !== 3 || !n) return null;
  const out = [];
  for (let k = 0; k < n; k++) out.push([v[k], v[k + n], v[k + 2 * n]].map(x => Math.min(1, Math.max(0, x))));
  return out;
}

/** The colour of a value through a map: scaled across [lo, hi], or an index into it (direct). */
function figMapColor(cmap, v, clim, direct, zeroBased) {
  if (!Number.isFinite(v) || !cmap.length) return null;
  let k;
  if (direct) k = Math.floor(v) - (zeroBased ? 0 : 1);
  else {
    const [lo, hi] = clim;
    k = hi > lo ? Math.floor((v - lo) / (hi - lo) * cmap.length) : Math.floor(cmap.length / 2);
  }
  return cmap[Math.min(cmap.length - 1, Math.max(0, k))];
}

/** A tick step for a span: 1, 2 or 5 times a power of ten, about `count` of them. */
function figTickStep(span, count) {
  if (!(span > 0) || !Number.isFinite(span)) return 1;
  const raw = span / Math.max(count, 1);
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 5, 10]) if (raw <= m * p * 1.0001) return m * p;
  return 10 * p;
}

function figLinearTicks(lo, hi, count) {
  const step = figTickStep(hi - lo, count);
  const out = [];
  const first = Math.ceil(lo / step - 1e-9);
  for (let k = first; out.length < 1000; k++) {
    const v = k * step;
    if (v > hi + step * 1e-9) break;
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return out;
}

function figLogTicks(lo, hi) {
  if (!(lo > 0 && hi > lo)) return [];
  const a = Math.ceil(Math.log10(lo) - 1e-9);
  const b = Math.floor(Math.log10(hi) + 1e-9);
  if (b < a) return figLinearTicks(lo, hi, 4);
  const every = Math.max(1, Math.ceil((b - a + 1) / 11));
  const out = [];
  for (let e = a; e <= b; e += every) out.push(Math.pow(10, e));
  return out;
}

/**
 * Tick labels as MATLAB writes them for ticks it chose: as many decimals as
 * the step needs, and the power of ten they share apart when they are large
 * or small. Log ticks are 10^{n}.
 *
 * @returns {{labels: string[], exponent: number}}
 */
function figTickLabels(ticks, log) {
  if (log) {
    return { labels: ticks.map(v => {
      const e = Math.log10(v);
      return Math.abs(e - Math.round(e)) < 1e-9 ? `10^{${Math.round(e)}}` : figShortNumber(v);
    }), exponent: 0 };
  }
  const big = Math.max(0, ...ticks.map(Math.abs));
  let exponent = 0;
  if (big > 0) {
    const e = Math.floor(Math.log10(big) + 1e-9);
    if (e >= 4 || e <= -3) exponent = e;
  }
  const scaled = ticks.map(v => v / Math.pow(10, exponent));
  // as few decimals as write every tick exactly: 0.25 needs two
  let decimals = 0;
  const exact = (v) => Math.abs(v * Math.pow(10, decimals) - Math.round(v * Math.pow(10, decimals))) < 1e-6 * Math.max(1, Math.abs(v) * Math.pow(10, decimals));
  while (decimals < 10 && !scaled.every(exact)) decimals++;
  return {
    labels: scaled.map(v => {
      let s = v.toFixed(decimals);
      if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
      return s === '-0' ? '0' : s;
    }),
    exponent
  };
}

/* ── drawing: a figure and what it holds ─────────────────────────────── */

const FIG_DEFAULT_SIZE = [560, 420];
const FIG_AXES_POSITION = [0.13, 0.11, 0.775, 0.815];

/* Objects that hold others and draw nothing themselves, and what draws nothing at all. */
const FIG_GROUPS = /^(hggroup|hgtransform|specgraph\.|graph2d\.|graph3d\.|matlab\.graphics\.primitive\.group)/;
const FIG_NOT_DRAWN = new Set(['uimenu', 'uicontextmenu', 'uitoolbar', 'uipushtool', 'uitoggletool', 'uitogglesplittool',
  'uisplittool', 'light']);

function figP(o, name) {
  return o.props.get(name.toLowerCase());
}

function figVisible(o) {
  return figOn(figP(o, 'Visible'), true);
}

/** Pixels in a unit of length, across (0) or up (1); null for a unit relative to what holds it. */
function figUnitPx(units, model, axis) {
  switch (units) {
    case 'pixels': return 1;
    case 'points': return model.ppi / 72;
    case 'inches': return model.ppi;
    case 'centimeters': return model.ppi / 2.54;
    case 'characters': return model.chars[axis];
    default: return null;
  }
}

/**
 * Where a Position [left bottom width height] puts an object in a box, as
 * SVG pixels { x, y, w, h } with y down: normalized, a fraction of the box;
 * any other unit, a length from its lower left corner.
 */
function figPlace(pos, units, box, model) {
  if (!pos || pos.length < 4 || ![0, 1, 2, 3].every(k => Number.isFinite(pos[k]))) return null;
  const ux = figUnitPx(units, model, 0);
  const uy = figUnitPx(units, model, 1);
  if (ux === null) {
    return { x: box.x + pos[0] * box.w, y: box.y + box.h - (pos[1] + pos[3]) * box.h, w: pos[2] * box.w, h: pos[3] * box.h };
  }
  return { x: box.x + pos[0] * ux, y: box.y + box.h - (pos[1] + pos[3]) * uy, w: pos[2] * ux, h: pos[3] * uy };
}

/** A figure's size in pixels, from its Position. */
function figSize(fig, model) {
  const p = figNumbers(figP(fig, 'Position'));
  const units = figWord(figP(fig, 'Units')) || 'pixels';
  let [w, h] = FIG_DEFAULT_SIZE;
  if (p && p.length >= 4 && p[2] > 0 && p[3] > 0) {
    if (units === 'normalized') { w = p[2] * 1440; h = p[3] * 900; }
    else { w = p[2] * (figUnitPx(units, model, 0) || 1); h = p[3] * (figUnitPx(units, model, 1) || 1); }
  }
  const fit = (v, d) => (Number.isFinite(v) ? Math.min(4000, Math.max(40, v)) : d);
  return { w: fit(w, FIG_DEFAULT_SIZE[0]), h: fit(h, FIG_DEFAULT_SIZE[1]) };
}

/** The objects a figure has, or had, which this drawing leaves out: by type, how many. */
function figNotDrawn(R, o) {
  R.notDrawn.set(o.type || 'object', (R.notDrawn.get(o.type || 'object') || 0) + 1);
}

/**
 * The group an object is drawn in, which says which object it is -- for a
 * click in the drawing -- and is faded when another object is the one
 * selected.
 */
function figObjectGroup(R, parent, o, fade = true) {
  const g = figEl('g', {}, parent);
  if (o.path) {
    g.setAttribute('data-fig-path', o.path);
    // its name in the tree, as the pointer's tooltip
    figEl('title', {}, g).textContent = o.path.slice(o.path.lastIndexOf('/') + 1);
  }
  if (fade && R.focus && !R.focus.has(o)) g.setAttribute('opacity', '0.2');
  return g;
}

/** Note where the object selected is drawn, for the frame around it. */
function figMark(R, o, box) {
  if (R.highlight === o && box && Number.isFinite(box.x + box.y + box.w + box.h)) R.marked = box;
}

/**
 * Draw one figure as SVG.
 *
 * @param {Object} model - The file's (figFileModel)
 * @param {Object} fig - A figure object of it
 * @param {Object|null} highlight - The object to set apart, or null
 * @returns {{svg: SVGSVGElement, width: number, height: number, notDrawn: Map<string, number>}}
 */
function figRender(model, fig, highlight) {
  const { w, h } = figSize(fig, model);
  const R = {
    model, fig, highlight, id: `rbfig${++figDrawings}`, clips: 0, pt: model.ppi / 72,
    notDrawn: new Map(), marked: null,
    cmap: figColormap(figP(fig, 'Colormap')) || figJet(),
    focus: null
  };
  if (highlight) {
    // The object, what it holds and what holds it are drawn as they are; the rest faded.
    R.focus = new Set();
    const down = (o) => { R.focus.add(o); o.children.forEach(down); };
    down(highlight);
    for (let o = highlight.parent; o; o = o.parent) R.focus.add(o);
  }
  const menus = fig.children.filter(c => c.low === 'uimenu' && figVisible(c));
  const menuH = menus.length ? 22 : 0;
  const svg = figEl('svg', { xmlns: FIG_SVG, viewBox: `0 0 ${figN(w)} ${figN(h + menuH)}`, width: figN(w), height: figN(h + menuH) });
  R.svg = svg;
  R.defs = figEl('defs', {}, svg);
  if (menuH) figMenuBar(R, svg, menus, w, menuH);
  const root = figEl('g', menuH ? { transform: `translate(0 ${menuH})` } : {}, svg);
  root.setAttribute('data-fig-path', fig.path || '');
  figEl('rect', { x: 0, y: 0, width: figN(w), height: figN(h),
    fill: figCss(figColor(figP(fig, 'Color')), model.hg2 ? 'rgb(240,240,240)' : 'rgb(204,204,204)') }, root);
  figContents(R, root, fig, { x: 0, y: 0, w, h });
  if (R.marked) {
    const m = R.marked;
    const frame = figEl('rect', { x: figN(m.x - 3), y: figN(m.y - 3), width: figN(m.w + 6), height: figN(m.h + 6),
      fill: 'none', 'stroke-width': 2, 'stroke-dasharray': '6 3', class: 'fig-mark' }, root);
    frame.style.stroke = 'var(--color-kvot-accent, #d9480f)';
  }
  return { svg, width: w, height: h + menuH, notDrawn: R.notDrawn };
}

/** A figure's menus as MATLAB shows them above it: the labels of the top ones. */
function figMenuBar(R, svg, menus, w, height) {
  figEl('rect', { x: 0, y: 0, width: figN(w), height, fill: 'rgb(246,246,246)' }, svg);
  figEl('line', { x1: 0, x2: figN(w), y1: height - 0.5, y2: height - 0.5, stroke: 'rgb(200,200,200)' }, svg);
  let x = 8;
  for (const m of menus) {
    const label = (figText(figP(m, 'Label')) || figText(figP(m, 'Text'))).replace(/&(.)/g, '$1');
    const g = figObjectGroup(R, svg, m);
    const size = 12;
    const { width } = figDrawText(g, label, x, height / 2, { size, valign: 'middle', interpreter: 'none', color: '#222' });
    figMark(R, m, { x: x - 4, y: 2, w: width + 8, h: height - 4 });
    x += width + 16;
  }
}

/**
 * What a figure, panel or other container holds, in the order MATLAB stacks
 * them: axes as saved, then legends and colour bars, then controls, which
 * MATLAB always shows over axes, then annotations.
 */
function figContents(R, g, parent, box) {
  const layers = [[], [], [], []];
  for (const c of parent.children) {
    const t = c.low;
    // An axes hidden by axis off still shows what it holds; anything else hidden -- a
    // legend or colour bar of an older release among them -- is not drawn.
    if (!figVisible(c) && !(t === 'axes' && !['legend', 'colorbar'].includes(figWord(figP(c, 'Tag'))))) continue;
    if (t === 'axes' || t === 'matlab.graphics.axis.polaraxes' || t === 'polaraxes') layers[0].push(c);
    else if (t === 'scribe.legend' || t === 'legend' || t === 'scribe.colorbar' || t === 'colorbar') layers[1].push(c);
    else if (t.startsWith('ui') && !FIG_NOT_DRAWN.has(t)) layers[2].push(c);
    else if (t === 'scribe.scribeaxes' || t === 'annotationpane' || t === 'text') layers[3].push(c);
    else if (!FIG_NOT_DRAWN.has(t)) figNotDrawn(R, c);
  }
  for (const c of layers.flat()) {
    try {
      figDrawFigureChild(R, g, c, box);
    } catch (err) {
      kvotWarn(`A ${c.type} of the figure could not be drawn:`, err);
      figNotDrawn(R, c);
    }
  }
}

function figDrawFigureChild(R, g, c, box) {
  const t = c.low;
  if (t === 'axes') {
    // A legend of older releases is an axes of its own, as is a colour bar.
    figAxes(R, g, c, box);
  } else if (t === 'matlab.graphics.axis.polaraxes' || t === 'polaraxes') {
    figPolarAxes(R, g, c, box);
  } else if (t === 'scribe.legend' || t === 'legend') {
    if (c.children.some(k => figVisible(k))) figAxes(R, g, c, box);
    else figLegend(R, g, c, box);
  } else if (t === 'scribe.colorbar' || t === 'colorbar') {
    figColorbar(R, g, c, box);
  } else if (t === 'scribe.scribeaxes' || t === 'annotationpane') {
    for (const a of c.children) if (figVisible(a)) figAnnotation(R, g, a, box);
  } else if (t === 'text') {
    figTextObject(R, g, c, null, box);
  } else {
    figControl(R, g, c, box);
  }
}

/* ── axes ────────────────────────────────────────────────────────────── */

/**
 * The view [azimuth, elevation] an axes is seen from: its View, or -- in
 * files of releases before R2014b, which keep none -- where its camera is
 * from the middle of its limits, each axis measured in its own span. A
 * camera within 5 degrees of straight above is a 2-D view: limits this page
 * finds itself can differ from MATLAB's by a tick, which tilts it as much.
 */
function figView(ax) {
  const v = figNumbers(figP(ax, 'View'));
  if (v && v.length >= 2 && Number.isFinite(v[0] + v[1])) return [v[0], v[1]];
  const cp = figNumbers(figP(ax, 'CameraPosition'));
  if (!cp || cp.length < 3 || !Number.isFinite(cp[0] + cp[1] + cp[2])) return [0, 90];
  const lims = [0, 1, 2].map(k => figLimits(null, ax, k, figWord(figP(ax, `${'XYZ'[k]}Scale`)) === 'log', 400));
  const saved = figNumbers(figP(ax, 'CameraTarget'));
  const ct = saved && saved.length >= 3 ? saved : lims.map(l => (l[0] + l[1]) / 2);
  const d = [0, 1, 2].map(k => (cp[k] - ct[k]) / (lims[k][1] - lims[k][0] || 1));
  if (!d.every(Number.isFinite)) return [0, 90];
  const el = Math.atan2(d[2], Math.hypot(d[0], d[1])) * 180 / Math.PI;
  if (Math.abs(el) > 85) return [0, el < 0 ? -90 : 90];
  const az = Math.atan2(d[0], -d[1]) * 180 / Math.PI;
  return [az, el];
}

/** The finite values of every array an axes draws, along x (0), y (1) or z (2): [min, max] or null. */
function figExtent(R, ax, which, log) {
  let lo = Infinity;
  let hi = -Infinity;
  const take = (v, pad = 0) => {
    if (!v) return;
    for (let k = 0; k < v.length; k++) {
      const x = v[k];
      if (!Number.isFinite(x) || (log && x <= 0)) continue;
      if (x - pad < lo) lo = x - pad;
      if (x + pad > hi) hi = x + pad;
    }
  };
  const axis = 'xyz'[which];
  const walk = (o) => {
    for (const c of o.children) {
      if (!figVisible(c) || c.role) continue;
      if (figWord(figP(c, `${axis.toUpperCase()}LimInclude`)) === 'off') continue;
      const t = c.low;
      if (t === 'text' || t === 'light') continue;
      if (c.children.length && FIG_GROUPS.test(t)) { walk(c); continue; }
      if (t === 'patch') {
        const V = figP(c, 'Vertices');
        const v = figNumbers(V);
        const [m, cols] = figDims(V);
        if (v && cols > which && m) take(v.subarray(which * m, (which + 1) * m));
        else take(figNumbers(figP(c, `${axis}Data`)));
        continue;
      }
      if (t === 'image') {
        const data = figNumbers(figP(c, `${axis}Data`));
        const [rows, cols] = figDims(figP(c, 'CData'));
        const n = which === 0 ? cols : rows;
        if (which === 2) continue;
        const ends = data && data.length ? [data[0], data[data.length - 1]] : [1, n];
        const half = n > 1 ? Math.abs(ends[1] - ends[0]) / (n - 1) / 2 : 0.5;
        take(Float64Array.from(ends), half);
        continue;
      }
      if (t === 'histogram') {
        if (which === 0) take(figNumbers(figP(c, 'BinEdges')));
        else if (which === 1) { take(figHistogramHeights(c)); take(Float64Array.of(0)); }
        continue;
      }
      let data = figNumbers(figP(c, `${axis}Data`));
      if (!data && which === 0) {
        const ys = figNumbers(figP(c, 'YData'));
        if (ys) data = Float64Array.from(ys, (_, k) => k + 1);
      }
      take(data);
      if (which === 1 && /bar|area|stem/.test(t)) take(Float64Array.of(figNumber(figP(c, 'BaseValue'), 0)));
    }
  };
  walk(ax);
  return lo <= hi ? [lo, hi] : null;
}

/**
 * An axes' limits along one axis: those it was saved with, or those MATLAB
 * chooses for what it draws -- rounded out to ticks, or tight.
 */
function figLimits(R, ax, which, log, length) {
  const axis = 'XYZ'[which];
  const saved = figNumbers(figP(ax, `${axis}Lim`));
  if (saved && saved.length >= 2 && Number.isFinite(saved[0] + saved[1]) && saved[1] > saved[0] && (!log || saved[0] > 0)) {
    return [saved[0], saved[1]];
  }
  let ext = figExtent(R, ax, which, log);
  if (!ext) return log ? [0.1, 1] : [0, 1];
  if (ext[0] === ext[1]) {
    const v = ext[0];
    ext = log ? [v / 10, v * 10] : [v - 1, v + 1];
  }
  const tight = /tight/.test(figWord(figP(ax, `${axis}LimitMethod`)) + figWord(figP(ax, `${axis}LimSpec`)));
  if (tight) return ext;
  if (log) return [Math.pow(10, Math.floor(Math.log10(ext[0]) + 1e-9)), Math.pow(10, Math.ceil(Math.log10(ext[1]) - 1e-9))];
  const step = figTickStep(ext[1] - ext[0], Math.max(2, length / (which === 0 ? 60 : 30)));
  return [Math.floor(ext[0] / step + 1e-9) * step, Math.ceil(ext[1] / step - 1e-9) * step];
}

/** A scale from data to pixels between two ends, the other way round when reversed. */
function figScale(lim, log, from, to) {
  const f = log ? Math.log10 : (v) => v;
  const a = f(lim[0]);
  const b = f(lim[1]);
  const k = (to - from) / (b - a);
  return log ? (v) => (v > 0 ? from + (Math.log10(v) - a) * k : NaN) : (v) => from + (v - a) * k;
}

/**
 * An axes' ticks along one axis, with their labels: those it was saved
 * with, or MATLAB's for its limits. Labels with fewer than ticks repeat, as
 * MATLAB repeats them.
 */
function figTicks(R, ax, which, lim, log, length) {
  const axis = 'XYZ'[which];
  const savedTicks = figP(ax, `${axis}Tick`);
  let ticks = figNumbers(savedTicks);
  ticks = ticks ? Array.from(ticks) : log ? figLogTicks(lim[0], lim[1]) : figLinearTicks(lim[0], lim[1], Math.max(2, length / (which === 0 ? 60 : 30)));
  const span = lim[1] - lim[0];
  ticks = ticks.filter(v => Number.isFinite(v) && v >= lim[0] - span * 1e-9 && v <= lim[1] + span * 1e-9 && (!log || v > 0));
  // more ticks than an axis has room for are thinned to as many as it has
  if (ticks.length > 200) ticks = ticks.filter((_, k) => k % Math.ceil(ticks.length / 200) === 0);
  const savedLabels = figP(ax, `${axis}TickLabel`);
  const interpreter = figWord(figP(ax, 'TickLabelInterpreter')) || (R.model.hg2 ? 'tex' : 'none');
  let labels;
  let exponent = 0;
  if (savedLabels !== undefined && (savedTicks !== undefined || figWord(figP(ax, `${axis}TickLabelMode`)) !== 'auto')) {
    const all = figLines(savedLabels);
    const given = figNumbers(savedTicks);
    // the labels belong to the ticks saved, of which some may lie outside
    const at = given ? Array.from(given) : ticks;
    labels = ticks.map(v => {
      const k = at.findIndex(t => t === v);
      return all.length ? all[(k >= 0 ? k : ticks.indexOf(v)) % all.length] : '';
    });
    const ex = figNumbers(figP(ax, `${axis}AxisExponent`)) || null;
    if (ex && ex[0]) exponent = ex[0];
  } else {
    const made = figTickLabels(ticks, log);
    labels = made.labels;
    exponent = made.exponent;
  }
  return { ticks, labels, exponent, interpreter: savedLabels !== undefined ? interpreter : 'tex' };
}

/** Minor ticks between major ones: a log axis' 2 to 9 of each decade, else fifths or quarters. */
function figMinorTicks(ticks, lim, log) {
  const out = [];
  if (log) {
    const a = Math.floor(Math.log10(lim[0]));
    const b = Math.ceil(Math.log10(lim[1]));
    for (let e = a; e <= b && out.length < 2000; e++) {
      for (let m = 2; m <= 9; m++) {
        const v = m * Math.pow(10, e);
        if (v > lim[0] && v < lim[1]) out.push(v);
      }
    }
    return out;
  }
  // between the two first ticks a file gives, which may be anything
  const sorted = [...new Set(ticks)].sort((a, b) => a - b);
  if (sorted.length < 2) return out;
  const step = sorted[1] - sorted[0];
  if (!(step > 0) || !Number.isFinite(step) || (lim[1] - lim[0]) / step > 1000) return out;
  const mant = Math.round(step / Math.pow(10, Math.floor(Math.log10(step))));
  const parts = mant === 2 ? 4 : 5;
  const minor = step / parts;
  const first = Math.ceil((lim[0] - sorted[0]) / minor);
  for (let k = first; out.length < 2000; k++) {
    const v = sorted[0] + k * minor;
    if (v >= lim[1]) break;
    if (v > lim[0] && !sorted.some(t => Math.abs(t - v) < minor * 1e-6)) out.push(v);
  }
  return out;
}

/** The plot box of an axes in a figure: its Position, made to keep the aspect it was given. */
function figAxesRect(R, ax, box, is3d) {
  const pos = figNumbers(figP(ax, 'Position')) || figNumbers(figP(ax, 'InnerPosition')) || FIG_AXES_POSITION;
  const rect = figPlace(pos, figWord(figP(ax, 'Units')) || 'normalized', box, R.model);
  if (!rect || !(rect.w > 1 && rect.h > 1)) return null;
  if (is3d) return rect;
  const darManual = figWord(figP(ax, 'DataAspectRatioMode')) === 'manual';
  const pbarManual = figWord(figP(ax, 'PlotBoxAspectRatioMode')) === 'manual';
  if (!darManual && !pbarManual) return rect;
  let ratio = NaN;
  if (darManual) {
    const dar = figNumbers(figP(ax, 'DataAspectRatio'));
    const xl = figNumbers(figP(ax, 'XLim'));
    const yl = figNumbers(figP(ax, 'YLim'));
    if (dar && xl && yl) ratio = ((yl[1] - yl[0]) / dar[1]) / ((xl[1] - xl[0]) / dar[0]);
  } else {
    const pbar = figNumbers(figP(ax, 'PlotBoxAspectRatio'));
    if (pbar) ratio = pbar[1] / pbar[0];
  }
  if (!(ratio > 0) || !Number.isFinite(ratio)) return rect;
  if (rect.h / rect.w > ratio) {
    const h = rect.w * ratio;
    return { x: rect.x, y: rect.y + (rect.h - h) / 2, w: rect.w, h };
  }
  const w = rect.h / ratio;
  return { x: rect.x + (rect.w - w) / 2, y: rect.y, w, h: rect.h };
}

/** What an axes is drawn with, read once: fonts, colours, scales, limits. */
function figAxesStyle(R, ax) {
  const P = (n) => figP(ax, n);
  const hg2 = R.model.hg2;
  const ink = hg2 ? [0.15, 0.15, 0.15] : [0, 0, 0];
  const fontUnits = figWord(P('FontUnits')) || 'points';
  const size = figNumber(P('FontSize'), 10);
  return {
    fontPx: (fontUnits === 'pixels' ? size : size * R.pt) || 10 * R.pt,
    family: figFamily(figText(P('FontName')) || 'Helvetica'),
    bold: figWord(P('FontWeight')) === 'bold',
    italic: /italic|oblique/.test(figWord(P('FontAngle'))),
    xColor: figColor(P('XColor')) || ink,
    yColor: figColor(P('YColor')) || ink,
    zColor: figColor(P('ZColor')) || ink,
    lineWidth: figWidth(R, ax),
    box: figOn(P('Box'), false),
    tickDir: figWord(P('TickDir')) || 'in',
    tickLength: Math.min(0.2, Math.max(0, (figNumbers(P('TickLength')) || [0.01])[0] || 0)),
    layerTop: figWord(P('Layer')) === 'top',
    gridColor: hg2 ? (figColor(P('GridColor')) || [0.15, 0.15, 0.15]) : null,
    gridAlpha: hg2 ? figNumber(P('GridAlpha'), 0.15) : 1,
    minorGridAlpha: hg2 ? figNumber(P('MinorGridAlpha'), 0.25) : 1,
    gridStyle: figText(P('GridLineStyle')) || (hg2 ? '-' : ':'),
    minorGridStyle: figText(P('MinorGridLineStyle')) || ':',
    color: figColor(P('Color')),
    visible: figVisible(ax),
    labelScale: hg2 ? figNumber(P('LabelFontSizeMultiplier'), 1.1) : 1,
    titleScale: hg2 ? figNumber(P('TitleFontSizeMultiplier'), 1.1) : 1,
    titleBold: hg2 ? (figWord(P('TitleFontWeight')) || 'bold') === 'bold' : false
  };
}

/** An object's LineWidth in pixels: MATLAB's 0.5 point when it has none, and never wider than a broad brush. */
function figWidth(R, o) {
  const w = figNumber(figP(o, 'LineWidth'), 0.5);
  return Math.min(50, Number.isFinite(w) && w > 0 ? w : 0.5) * R.pt;
}

/** A stroke's dashes for a MATLAB line style, scaled by its width. */
function figDash(style, width) {
  const u = Math.max(1, width);
  switch (style) {
    case '--': return `${figN(6 * u)} ${figN(4 * u)}`;
    case ':': return `${figN(1.2 * u)} ${figN(2.4 * u)}`;
    case '-.': return `${figN(6 * u)} ${figN(3 * u)} ${figN(1.2 * u)} ${figN(3 * u)}`;
    default: return null;
  }
}

/** The clip path of a box, made once per box, by its id. */
function figClip(R, rect) {
  const id = `${R.id}-clip${++R.clips}`;
  const clip = figEl('clipPath', { id }, R.defs);
  figEl('rect', { x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h) }, clip);
  return `url(#${id})`;
}

/**
 * Draw an axes: its box, grid, ticks and labels, and what it holds -- in
 * two dimensions, or seen from its view in three.
 */
function figAxes(R, g, ax, box) {
  const view = figView(ax);
  const is3d = !(Math.abs(Math.abs(view[1]) - 90) < 1e-6 && Math.abs(view[0] % 360) < 1e-6);
  const rect = figAxesRect(R, ax, box, is3d);
  if (!rect) return;
  const gAx = figObjectGroup(R, g, ax, false);
  figMark(R, ax, rect);
  if (is3d) { figAxes3(R, gAx, ax, rect, view); return; }

  const S = figAxesStyle(R, ax);
  const P = (n) => figP(ax, n);
  const xLog = figWord(P('XScale')) === 'log';
  const yLog = figWord(P('YScale')) === 'log';
  const xLim = figLimits(R, ax, 0, xLog, rect.w);
  const yLim = figLimits(R, ax, 1, yLog, rect.h);
  const xRev = figWord(P('XDir')) === 'reverse';
  const yRev = figWord(P('YDir')) === 'reverse';
  const X = figScale(xLim, xLog, xRev ? rect.x + rect.w : rect.x, xRev ? rect.x : rect.x + rect.w);
  const Y = figScale(yLim, yLog, yRev ? rect.y : rect.y + rect.h, yRev ? rect.y + rect.h : rect.y);
  const T = { X, Y, rect, xLim, yLim, xLog, yLog, ax, S };

  if (S.visible && S.color !== 'none') {
    figEl('rect', { x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h),
      fill: figCss(Array.isArray(S.color) ? S.color : [1, 1, 1]) }, gAx);
  }
  const xt = figTicks(R, ax, 0, xLim, xLog, rect.w);
  const yt = figTicks(R, ax, 1, yLim, yLog, rect.h);
  const grid = figEl('g', {}, gAx);
  const data = figEl('g', { 'clip-path': figClip(R, rect) }, gAx);
  const free = figEl('g', {}, gAx);
  const chrome = figEl('g', {}, gAx);
  if (S.visible) figGrid2(R, S.layerTop ? chrome : grid, T, xt, yt);

  for (const c of ax.children) {
    if (c.role || !figVisible(c)) continue;
    figDrawChild(R, c, T, data, free);
  }

  const extents = S.visible ? figRulers2(R, chrome, T, xt, yt) : { below: 0, above: 0, left: 0, right: 0 };
  figAxesLabels2(R, chrome, ax, T, extents);
}

/** Grid lines at the ticks, major and minor, as the axes asks for them. */
function figGrid2(R, g, T, xt, yt) {
  const { ax, S, rect, X, Y } = T;
  const P = (n) => figP(ax, n);
  const lines = (vals, vertical, style, alpha, colorDefault) => {
    if (!vals.length || style === 'none') return;
    let d = '';
    for (const v of vals) {
      const p = vertical ? X(v) : Y(v);
      if (!Number.isFinite(p)) continue;
      d += vertical ? `M${figN(p)} ${figN(rect.y)}V${figN(rect.y + rect.h)}` : `M${figN(rect.x)} ${figN(p)}H${figN(rect.x + rect.w)}`;
    }
    figEl('path', { d, fill: 'none', stroke: figCss(S.gridColor || colorDefault), 'stroke-opacity': alpha < 1 ? alpha : null,
      'stroke-width': figN(S.lineWidth), 'stroke-dasharray': figDash(style, S.lineWidth) }, g);
  };
  if (figOn(P('XGrid'), false)) lines(xt.ticks, true, S.gridStyle, S.gridAlpha, S.xColor);
  if (figOn(P('YGrid'), false)) lines(yt.ticks, false, S.gridStyle, S.gridAlpha, S.yColor);
  if (figOn(P('XMinorGrid'), false)) lines(figMinorTicks(xt.ticks, T.xLim, T.xLog), true, S.minorGridStyle, S.minorGridAlpha, S.xColor);
  if (figOn(P('YMinorGrid'), false)) lines(figMinorTicks(yt.ticks, T.yLim, T.yLog), false, S.minorGridStyle, S.minorGridAlpha, S.yColor);
}

/**
 * The axis lines, ticks and tick labels of a 2-D axes; how far its labels
 * reach out from the box on each side.
 */
function figRulers2(R, g, T, xt, yt) {
  const { ax, S, rect, X, Y } = T;
  const P = (n) => figP(ax, n);
  const xTop = figWord(P('XAxisLocation')) === 'top';
  const yRight = figWord(P('YAxisLocation')) === 'right';
  const len = S.tickLength * Math.max(rect.w, rect.h);
  const dir = S.tickDir === 'out' ? -1 : S.tickDir === 'both' ? 0 : 1;
  const lw = S.lineWidth;
  const out = { below: 0, above: 0, left: 0, right: 0 };
  const left = rect.x;
  const right = rect.x + rect.w;
  const top = rect.y;
  const bottom = rect.y + rect.h;

  const side = (color, d) => figEl('path', { d, fill: 'none', stroke: figCss(color), 'stroke-width': figN(lw), 'stroke-linecap': 'square' }, g);
  // the box, and the axis lines without one
  const xAt = xTop ? top : bottom;
  const yAt = yRight ? right : left;
  side(S.xColor, `M${figN(left)} ${figN(xAt)}H${figN(right)}${S.box ? `M${figN(left)} ${figN(xTop ? bottom : top)}H${figN(right)}` : ''}`);
  side(S.yColor, `M${figN(yAt)} ${figN(top)}V${figN(bottom)}${S.box ? `M${figN(yRight ? left : right)} ${figN(top)}V${figN(bottom)}` : ''}`);

  const tickPath = (vals, vertical, color, length) => {
    let d = '';
    for (const v of vals) {
      const p = vertical ? X(v) : Y(v);
      if (!Number.isFinite(p)) continue;
      const one = (at, inward) => {
        const a = dir === 0 ? -length : 0;
        const b = dir === 0 ? length : length * dir;
        return vertical ? `M${figN(p)} ${figN(at + inward * a)}V${figN(at + inward * b)}` : `M${figN(at + inward * a)} ${figN(p)}H${figN(at + inward * b)}`;
      };
      d += vertical ? one(xAt, xTop ? 1 : -1) : one(yAt, yRight ? -1 : 1);
      if (S.box) d += vertical ? one(xTop ? bottom : top, xTop ? -1 : 1) : one(yRight ? left : right, yRight ? 1 : -1);
    }
    if (d) figEl('path', { d, fill: 'none', stroke: figCss(color), 'stroke-width': figN(lw) }, g);
  };
  tickPath(xt.ticks, true, S.xColor, len);
  tickPath(yt.ticks, false, S.yColor, len);
  const xMinor = figOn(P('XMinorTick'), false) || (!R.model.hg2 ? false : T.xLog && figWord(P('XMinorTick')) === '');
  const yMinor = figOn(P('YMinorTick'), false) || (!R.model.hg2 ? false : T.yLog && figWord(P('YMinorTick')) === '');
  if (xMinor) tickPath(figMinorTicks(xt.ticks, T.xLim, T.xLog), true, S.xColor, len / 2);
  if (yMinor) tickPath(figMinorTicks(yt.ticks, T.yLim, T.yLog), false, S.yColor, len / 2);

  // tick labels
  const fs = S.fontPx;
  const gap = fs * 0.35 + (dir <= 0 ? len : 0);
  const font = { size: fs, family: S.family, bold: S.bold, italic: S.italic, pt: R.pt };
  let xh = 0;
  xt.ticks.forEach((v, k) => {
    const label = xt.labels[k];
    const p = X(v);
    if (!label || !Number.isFinite(p)) return;
    const m = figDrawText(g, String(label).split('\n'), p, xTop ? xAt - gap : xAt + gap,
      { ...font, color: figCss(S.xColor), halign: 'center', valign: xTop ? 'bottom' : 'top', interpreter: xt.interpreter });
    xh = Math.max(xh, m.height);
  });
  let yw = 0;
  yt.ticks.forEach((v, k) => {
    const label = yt.labels[k];
    const p = Y(v);
    if (!label || !Number.isFinite(p)) return;
    const m = figDrawText(g, String(label).split('\n'), yRight ? yAt + gap : yAt - gap, p,
      { ...font, color: figCss(S.yColor), halign: yRight ? 'left' : 'right', valign: 'middle', interpreter: yt.interpreter });
    yw = Math.max(yw, m.width);
  });
  if (xt.exponent) {
    figDrawText(g, `\\times10^{${xt.exponent}}`, right, xTop ? xAt - gap - xh : xAt + gap + xh,
      { ...font, color: figCss(S.xColor), halign: 'right', valign: xTop ? 'bottom' : 'top', interpreter: 'tex' });
    xh += fs * 1.2;
  }
  if (yt.exponent) {
    figDrawText(g, `\\times10^{${yt.exponent}}`, yAt, top - fs * 0.3,
      { ...font, color: figCss(S.yColor), halign: yRight ? 'right' : 'left', valign: 'bottom', interpreter: 'tex' });
    out.above = fs * 1.2;
  }
  const reach = gap + xh;
  if (xTop) out.above = Math.max(out.above, reach); else out.below = reach;
  if (yRight) out.right = gap + yw; else out.left = gap + yw;
  return out;
}

/**
 * An axes' title and labels, where MATLAB puts them: the title over the
 * box, the x label under its tick labels, the y label turned beside its own.
 * A label moved by hand (PositionMode 'manual') stays where it was put.
 */
function figAxesLabels2(R, g, ax, T, ext) {
  const { S, rect, X, Y } = T;
  const P = (n) => figP(ax, n);
  const xTop = figWord(P('XAxisLocation')) === 'top';
  const yRight = figWord(P('YAxisLocation')) === 'right';
  for (const c of ax.children) {
    if (!c.role || c.role === 'ZLabel') continue;
    const lines = figLines(figP(c, 'String'));
    if (!lines.length || lines.every(s => !s.trim()) || !figVisible(c)) continue;
    if (c.role !== 'Title' && !S.visible) continue;
    const title = c.role === 'Title';
    const savedSize = figNumber(figP(c, 'FontSize'));
    const size = (Number.isFinite(savedSize) ? savedSize * R.pt : S.fontPx * (title ? S.titleScale : S.labelScale));
    const weight = figWord(figP(c, 'FontWeight'));
    const opts = {
      size, family: figFamily(figText(figP(c, 'FontName')) || 'Helvetica'), pt: R.pt,
      bold: weight ? weight === 'bold' : (title ? S.titleBold : false),
      italic: /italic|oblique/.test(figWord(figP(c, 'FontAngle'))),
      color: figCss(figColor(figP(c, 'Color')) || (title ? [0, 0, 0] : c.role === 'XLabel' ? S.xColor : S.yColor)),
      interpreter: figWord(figP(c, 'Interpreter')) || 'tex',
      halign: 'center'
    };
    const gl = figObjectGroup(R, g, c);
    let at;
    const manual = figWord(figP(c, 'PositionMode')) === 'manual' && figWord(figP(c, 'Units')) !== 'normalized';
    const pos = figNumbers(figP(c, 'Position'));
    if (manual && pos && pos.length >= 2 && Number.isFinite(X(pos[0]) + Y(pos[1]))) {
      at = [X(pos[0]), Y(pos[1])];
      opts.halign = figWord(figP(c, 'HorizontalAlignment')) || 'center';
      opts.valign = figWord(figP(c, 'VerticalAlignment')) || 'middle';
      opts.rotation = figNumber(figP(c, 'Rotation'), c.role === 'YLabel' ? 90 : 0);
    } else if (title) {
      at = [rect.x + rect.w / 2, rect.y - (ext.above || 0) - size * 0.35];
      opts.valign = 'bottom';
    } else if (c.role === 'XLabel') {
      at = xTop ? [rect.x + rect.w / 2, rect.y - ext.above - size * 0.2] : [rect.x + rect.w / 2, rect.y + rect.h + ext.below + size * 0.2];
      opts.valign = xTop ? 'bottom' : 'top';
    } else {
      at = yRight ? [rect.x + rect.w + ext.right + size * 0.3, rect.y + rect.h / 2] : [rect.x - ext.left - size * 0.3, rect.y + rect.h / 2];
      opts.rotation = 90;
      opts.valign = yRight ? 'top' : 'bottom';
    }
    const m = figDrawText(gl, lines, at[0], at[1], opts);
    if (R.highlight === c) {
      const w = opts.rotation ? m.height : m.width;
      const h = opts.rotation ? m.width : m.height;
      figMark(R, c, { x: at[0] - (opts.rotation ? (yRight ? 0 : w) : w / 2), y: at[1] - (opts.rotation ? h / 2 : (opts.valign === 'bottom' ? h : 0)), w, h });
    }
  }
}

/** One child of an axes, by its type; a group draws what it holds. */
function figDrawChild(R, c, T, data, free) {
  const t = c.low;
  try {
    if (t === 'line' || t === 'graph2d.lineseries') figLine(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'patch') figPatch(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'surface' || t === 'graph3d.surfaceplot') figSurface2(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'image') figImage(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'text') figTextObject(R, figWord(figP(c, 'Clipping')) === 'on' ? data : free, c, T, null);
    else if (t === 'histogram') figHistogram(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'specgraph.baseline' || t === 'baseline') figBaseline(R, c, T, figObjectGroup(R, data, c));
    else if (t === 'light') { /* lights only shade surfaces */ }
    else if (c.children.length && (FIG_GROUPS.test(t) || figSeriesKind(t))) {
      const g = figObjectGroup(R, data, c, false);
      for (const k of c.children) if (figVisible(k)) figDrawChild(R, k, T, g, free);
      figMarkData(R, c, T);
    } else if (figSeriesKind(t)) figSeries(R, c, T, figObjectGroup(R, data, c));
    else figNotDrawn(R, c);
  } catch (err) {
    kvotWarn(`A ${c.type} could not be drawn:`, err);
    figNotDrawn(R, c);
  }
}

/** The box around the data an object draws in an axes, for the frame of the one selected. */
function figMarkData(R, o, T) {
  if (R.highlight !== o) return;
  let x0 = Infinity; let x1 = -Infinity; let y0 = Infinity; let y1 = -Infinity;
  const walk = (c) => {
    const V = figP(c, 'Vertices');
    const [m] = figDims(V);
    const v = figNumbers(V);
    const xs = v && m ? v.subarray(0, m) : figNumbers(figP(c, 'XData'));
    const ys = v && m ? v.subarray(m, 2 * m) : figNumbers(figP(c, 'YData'));
    if (xs && ys) {
      const n = Math.min(xs.length, ys.length);
      for (let k = 0; k < n; k++) {
        const px = T.X(xs[k]);
        const py = T.Y(ys[k]);
        if (!Number.isFinite(px + py)) continue;
        x0 = Math.min(x0, px); x1 = Math.max(x1, px); y0 = Math.min(y0, py); y1 = Math.max(y1, py);
      }
    }
    c.children.forEach(walk);
  };
  walk(o);
  if (x0 <= x1) {
    const r = T.rect;
    const cx0 = Math.max(r.x, x0); const cx1 = Math.min(r.x + r.w, x1);
    const cy0 = Math.max(r.y, y0); const cy1 = Math.min(r.y + r.h, y1);
    if (cx0 <= cx1 && cy0 <= cy1) R.marked = { x: cx0, y: cy0, w: cx1 - cx0, h: cy1 - cy0 };
  }
}

/* ── lines and markers ───────────────────────────────────────────────── */

const FIG_MARKERS = { square: 's', diamond: 'd', pentagram: 'p', hexagram: 'h', none: 'none' };

function figMarkerName(a) {
  const m = figText(a).trim();
  return FIG_MARKERS[m.toLowerCase()] || m || 'none';
}

/** One marker as a piece of path, about (x, y), `s` pixels across. */
function figMarkerPath(m, x, y, s) {
  const r = s / 2;
  const P = (pts) => `M${pts.map(([a, b]) => `${figN(x + a)} ${figN(y + b)}`).join('L')}Z`;
  switch (m) {
    case 'o': return `M${figN(x - r)} ${figN(y)}a${figN(r)} ${figN(r)} 0 1 0 ${figN(2 * r)} 0a${figN(r)} ${figN(r)} 0 1 0 ${figN(-2 * r)} 0`;
    case '.': { const d = Math.max(1, r / 3); return `M${figN(x - d)} ${figN(y)}a${figN(d)} ${figN(d)} 0 1 0 ${figN(2 * d)} 0a${figN(d)} ${figN(d)} 0 1 0 ${figN(-2 * d)} 0`; }
    case 's': { const q = r * 0.9; return P([[-q, -q], [q, -q], [q, q], [-q, q]]); }
    case 'd': return P([[0, -r], [r, 0], [0, r], [-r, 0]]);
    case '^': return P([[0, -r], [r, r * 0.8], [-r, r * 0.8]]);
    case 'v': return P([[0, r], [r, -r * 0.8], [-r, -r * 0.8]]);
    case '>': return P([[r, 0], [-r * 0.8, -r], [-r * 0.8, r]]);
    case '<': return P([[-r, 0], [r * 0.8, -r], [r * 0.8, r]]);
    case '+': return `M${figN(x - r)} ${figN(y)}H${figN(x + r)}M${figN(x)} ${figN(y - r)}V${figN(y + r)}`;
    case 'x': { const q = r * 0.75; return `M${figN(x - q)} ${figN(y - q)}L${figN(x + q)} ${figN(y + q)}M${figN(x - q)} ${figN(y + q)}L${figN(x + q)} ${figN(y - q)}`; }
    case '*': {
      let d = '';
      for (let k = 0; k < 4; k++) {
        const a = k * Math.PI / 4;
        d += `M${figN(x - r * Math.cos(a))} ${figN(y - r * Math.sin(a))}L${figN(x + r * Math.cos(a))} ${figN(y + r * Math.sin(a))}`;
      }
      return d;
    }
    case '_': return `M${figN(x - r)} ${figN(y)}H${figN(x + r)}`;
    case '|': return `M${figN(x)} ${figN(y - r)}V${figN(y + r)}`;
    case 'p': case 'h': {
      const n = m === 'p' ? 5 : 6;
      const pts = [];
      for (let k = 0; k < 2 * n; k++) {
        const a = -Math.PI / 2 + k * Math.PI / n;
        const rr = k % 2 ? r * 0.45 : r * 1.1;
        pts.push([rr * Math.cos(a), rr * Math.sin(a)]);
      }
      return P(pts);
    }
    default: return '';
  }
}

const FIG_OPEN_MARKERS = new Set(['+', 'x', '*', '_', '|']);

/** Markers at points: one path, its face and edge as MATLAB colours them. */
function figMarkers(g, pts, m, size, edge, face, width) {
  if (!m || m === 'none' || !pts.length) return;
  size = Math.min(Math.max(size, 0), 200);
  // markers on the same half pixel draw as one: a million points are no more than the pixels they cover
  const seen = pts.length > 2000 ? new Set() : null;
  let d = '';
  for (const [x, y] of pts) {
    if (seen) {
      const key = Math.round(x * 2) * 65536 + Math.round(y * 2);
      if (seen.has(key)) continue;
      seen.add(key);
    }
    d += figMarkerPath(m, x, y, size);
  }
  if (!d) return;
  if (m === '.') { figEl('path', { d, fill: edge || 'none', stroke: 'none' }, g); return; }
  figEl('path', {
    d, fill: FIG_OPEN_MARKERS.has(m) ? 'none' : (face || 'none'), stroke: edge || 'none',
    'stroke-width': figN(Math.max(0.5, width))
  }, g);
}

/**
 * Points through as few as draw the same: of a run of points within a
 * column of half a pixel, the first, the lowest, the highest and the last.
 */
function figThin(px, py) {
  const xs = [];
  const ys = [];
  let k = 0;
  const n = px.length;
  while (k < n) {
    if (!Number.isFinite(px[k] + py[k])) { xs.push(NaN); ys.push(NaN); k++; continue; }
    const col = Math.floor(px[k] * 2);
    let lo = k; let hi = k; let j = k + 1;
    while (j < n && Number.isFinite(px[j] + py[j]) && Math.floor(px[j] * 2) === col) {
      if (py[j] < py[lo]) lo = j;
      if (py[j] > py[hi]) hi = j;
      j++;
    }
    for (const at of [...new Set([k, Math.min(lo, hi), Math.max(lo, hi), j - 1])]) { xs.push(px[at]); ys.push(py[at]); }
    k = j;
  }
  return [xs, ys];
}

/** A path through points, broken where one is missing. */
function figPolyline(px, py) {
  const parts = [];
  let open = false;
  for (let k = 0; k < px.length; k++) {
    if (!Number.isFinite(px[k] + py[k])) { open = false; continue; }
    parts.push(`${open ? 'L' : 'M'}${figN(px[k])} ${figN(py[k])}`);
    open = true;
  }
  return parts.join('');
}

/** A line's data as pixels: its x, or 1, 2, ... when it has none. */
function figLinePixels(o, T) {
  const ys = figNumbers(figP(o, 'YData'));
  if (!ys) return null;
  const xs = figNumbers(figP(o, 'XData'));
  const n = xs && xs.length === ys.length ? ys.length : ys.length;
  const px = new Float64Array(n);
  const py = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    px[k] = T.X(xs && xs.length === ys.length ? xs[k] : k + 1);
    py[k] = T.Y(ys[k]);
  }
  return [px, py];
}

function figLine(R, o, T, g) {
  const pixels = figLinePixels(o, T);
  if (!pixels) return;
  const [px, py] = pixels;
  const color = figColor(figP(o, 'Color')) || [0, 0, 0];
  const css = figCss(color, 'rgb(0,0,0)');
  const style = figText(figP(o, 'LineStyle')).trim() || '-';
  const width = figWidth(R, o);
  const marker = figMarkerName(figP(o, 'Marker'));
  if (style !== 'none') {
    const [xs, ys] = px.length > 8 * T.rect.w ? figThin(px, py) : [px, py];
    const d = figPolyline(xs, ys);
    if (R.highlight === o && d) {
      const halo = figEl('path', { d, fill: 'none', 'stroke-width': figN(width + 6), 'stroke-opacity': 0.35, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, g);
      halo.style.stroke = 'var(--color-kvot-accent, #d9480f)';
    }
    if (d) figEl('path', { d, fill: 'none', stroke: css, 'stroke-width': figN(width), 'stroke-linejoin': 'round', 'stroke-dasharray': figDash(style, width) }, g);
  }
  if (marker !== 'none') {
    const at = figNumbers(figP(o, 'MarkerIndices'));
    const pts = [];
    const n = px.length;
    const add = (k) => { if (k >= 0 && k < n && Number.isFinite(px[k] + py[k])) pts.push([px[k], py[k]]); };
    if (at && at.length) at.forEach(k => add(k - 1)); else for (let k = 0; k < n; k++) add(k);
    const size = figNumber(figP(o, 'MarkerSize'), 6) * R.pt;
    const edge = figColor(figP(o, 'MarkerEdgeColor'));
    const face = figColor(figP(o, 'MarkerFaceColor'));
    const axesColor = figCss(Array.isArray(T.S.color) ? T.S.color : [1, 1, 1]);
    figMarkers(g, pts, marker, size,
      edge === 'none' ? null : Array.isArray(edge) ? figCss(edge) : css,
      Array.isArray(face) ? figCss(face) : face === 'auto' ? axesColor : null, width);
  }
}

/** A bar chart's base line, at its BaseValue across the axes, when the file keeps none of its own. */
function figBaseline(R, o, T, g) {
  const ys = figNumbers(figP(o, 'YData'));
  if (ys && ys.length) { figLine(R, o, T, g); return; }
  const base = figNumber(figP(o, 'BaseValue'), 0);
  const vertical = figWord(figP(o, 'Orientation')) === 'y';
  const p = vertical ? T.X(base) : T.Y(base);
  if (!Number.isFinite(p)) return;
  const r = T.rect;
  figEl('path', { d: vertical ? `M${figN(p)} ${figN(r.y)}V${figN(r.y + r.h)}` : `M${figN(r.x)} ${figN(p)}H${figN(r.x + r.w)}`,
    stroke: figCss(figColor(figP(o, 'Color')) || [0.15, 0.15, 0.15]), 'stroke-width': figN(figWidth(R, o)) }, g);
}

/* ── patches ─────────────────────────────────────────────────────────── */

/** The colour scale of an axes: its CLim, or the range of what it draws scaled. */
function figCLim(R, T) {
  if (T.clim) return T.clim;
  const saved = figNumbers(figP(T.ax, 'CLim'));
  if (saved && saved.length >= 2 && Number.isFinite(saved[0] + saved[1]) && saved[1] > saved[0]) return (T.clim = [saved[0], saved[1]]);
  let lo = Infinity;
  let hi = -Infinity;
  const walk = (o) => {
    for (const c of o.children) {
      if (figWord(figP(c, 'CDataMapping')) === 'direct') continue;
      const cd = figP(c, c.low === 'patch' ? 'FaceVertexCData' : 'CData');
      const [, cols] = figDims(cd);
      const v = figNumbers(cd);
      if (v && cols !== 3 && (c.low === 'surface' || c.low === 'graph3d.surfaceplot' || c.low === 'patch' || (c.low === 'image' && figWord(figP(c, 'CDataMapping')) === 'scaled'))) {
        for (let k = 0; k < v.length; k++) if (Number.isFinite(v[k])) { if (v[k] < lo) lo = v[k]; if (v[k] > hi) hi = v[k]; }
      }
      if (c.children.length) walk(c);
    }
  };
  walk(T.ax);
  return (T.clim = lo < hi ? [lo, hi] : lo === hi && Number.isFinite(lo) ? [lo - 1, lo + 1] : [0, 1]);
}

/** The colour map an axes draws with: its own, else its figure's. */
function figAxesColormap(R, T) {
  if (!T.cmap) T.cmap = figColormap(figP(T.ax, 'Colormap')) || R.cmap;
  return T.cmap;
}

/**
 * A colour for each of a patch's faces or vertices from its colour data:
 * three numbers each, or a value through the colour map.
 */
function figVertexColors(R, o, T, prop) {
  const cd = figP(o, prop);
  const v = figNumbers(cd);
  const [rows, cols] = figDims(cd);
  if (!v || !rows) return null;
  if (cols === 3) {
    const out = [];
    for (let k = 0; k < rows; k++) out.push([v[k], v[k + rows], v[k + 2 * rows]]);
    return out;
  }
  const direct = figWord(figP(o, 'CDataMapping')) === 'direct';
  const zero = cd.cls !== 'double' && cd.cls !== 'single';
  const cmap = figAxesColormap(R, T);
  const clim = figCLim(R, T);
  const out = [];
  for (let k = 0; k < rows; k++) out.push(figMapColor(cmap, v[k], clim, direct, zero));
  return out;
}

function figPatch(R, o, T, g) {
  const V = figP(o, 'Vertices');
  const F = figP(o, 'Faces');
  let vx; let vy; let faces;
  const vv = figNumbers(V);
  const [m, vc] = figDims(V);
  if (vv && m && vc >= 2) {
    vx = vv.subarray(0, m);
    vy = vv.subarray(m, 2 * m);
    const fv = figNumbers(F);
    const [nf, nk] = figDims(F);
    faces = [];
    if (fv && nf) {
      for (let f = 0; f < nf; f++) {
        const face = [];
        for (let j = 0; j < nk; j++) {
          const idx = fv[f + nf * j];
          if (!Number.isFinite(idx)) break;
          face.push(idx - 1);
        }
        faces.push(face);
      }
    } else faces.push(Array.from({ length: m }, (_, k) => k));
  } else {
    // XData and YData: each column a face
    const X = figP(o, 'XData');
    const xs = figNumbers(X);
    const ys = figNumbers(figP(o, 'YData'));
    const [rows, cols] = figDims(X);
    if (!xs || !ys || xs.length !== ys.length || !rows) return;
    vx = xs; vy = ys; faces = [];
    for (let c = 0; c < cols; c++) faces.push(Array.from({ length: rows }, (_, r) => r + rows * c));
  }
  const px = Float64Array.from(vx, v => T.X(v));
  const py = Float64Array.from(vy, v => T.Y(v));
  const fc = figP(o, 'FaceColor') !== undefined ? figColor(figP(o, 'FaceColor')) : [0, 0, 0];
  const ec = figP(o, 'EdgeColor') !== undefined ? figColor(figP(o, 'EdgeColor')) : [0, 0, 0];
  const fa = figNumber(figP(o, 'FaceAlpha'), 1);
  const ea = figNumber(figP(o, 'EdgeAlpha'), 1);
  const width = figWidth(R, o);
  const style = figText(figP(o, 'LineStyle')).trim() || '-';
  const perFace = figVertexColors(R, o, T, 'FaceVertexCData');
  const colorOf = (f, face) => {
    if (!perFace) return null;
    if (perFace.length === faces.length) return perFace[f];
    if (perFace.length === 1) return perFace[0];
    if (face.length) {
      if (fc === 'interp' || ec === 'interp') {
        const c = [0, 0, 0];
        let n = 0;
        for (const k of face) if (perFace[k]) { c[0] += perFace[k][0]; c[1] += perFace[k][1]; c[2] += perFace[k][2]; n++; }
        return n ? c.map(x => x / n) : null;
      }
      return perFace[face[0]] || null;
    }
    return null;
  };
  const facePath = (face) => {
    let d = '';
    let open = false;
    let broken = false;
    for (const k of face) {
      if (!Number.isFinite(px[k] + py[k])) { open = false; broken = true; continue; }
      d += `${open ? 'L' : 'M'}${figN(px[k])} ${figN(py[k])}`;
      open = true;
    }
    return d && !broken ? `${d}Z` : d;
  };
  const uniform = !(['flat', 'interp'].includes(fc)) && !(['flat', 'interp'].includes(ec));
  const strokeOf = (c) => (ec === 'none' || !ec ? 'none' : Array.isArray(ec) ? figCss(ec) : c ? figCss(c) : 'none');
  const fillOf = (c) => (fc === 'none' || !fc ? 'none' : Array.isArray(fc) ? figCss(fc) : c ? figCss(c) : 'none');
  const attrs = (c) => ({
    fill: fillOf(c), 'fill-opacity': fa < 1 ? fa : null, stroke: strokeOf(c), 'stroke-opacity': ea < 1 ? ea : null,
    'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width), 'stroke-linejoin': 'round'
  });
  if (uniform) {
    const d = faces.map(facePath).join('');
    if (d && (fc !== 'none' || (ec !== 'none' && style !== 'none'))) figEl('path', { d, ...attrs(null), stroke: style === 'none' ? 'none' : strokeOf(null) }, g);
  } else if (faces.length > 3000) {
    // so many faces of their own colours are painted, as a surface is
    const r = figRaster(T.rect);
    if (r) {
      const { ctx } = r;
      faces.forEach((face, f) => {
        const c = colorOf(f, face);
        const fill = fillOf(c);
        const stroke = style === 'none' ? 'none' : strokeOf(c);
        const pts = face.filter(k => Number.isFinite(px[k] + py[k]));
        if (pts.length < 2 || (fill === 'none' && stroke === 'none')) return;
        ctx.beginPath();
        ctx.moveTo(px[pts[0]], py[pts[0]]);
        for (let k = 1; k < pts.length; k++) ctx.lineTo(px[pts[k]], py[pts[k]]);
        if (pts.length === face.length) ctx.closePath();
        if (fill !== 'none') { ctx.globalAlpha = fa < 1 ? fa : 1; ctx.fillStyle = fill; ctx.fill(); }
        if (stroke !== 'none') { ctx.globalAlpha = ea < 1 ? ea : 1; ctx.strokeStyle = stroke; ctx.lineWidth = width; ctx.stroke(); }
      });
      r.put(g);
    }
  } else {
    faces.forEach((face, f) => {
      const d = facePath(face);
      if (d) figEl('path', { d, ...attrs(colorOf(f, face)), stroke: style === 'none' ? 'none' : strokeOf(colorOf(f, face)) }, g);
    });
  }
  const marker = figMarkerName(figP(o, 'Marker'));
  if (marker !== 'none') {
    const size = figNumber(figP(o, 'MarkerSize'), 6) * R.pt;
    const me = figColor(figP(o, 'MarkerEdgeColor'));
    const mf = figColor(figP(o, 'MarkerFaceColor'));
    const groups = new Map();
    const used = new Set(faces.flat());
    for (const k of used) {
      if (!Number.isFinite(px[k] + py[k])) continue;
      const own = perFace ? perFace[perFace.length === px.length ? k : 0] : null;
      const edge = me === 'none' ? null : Array.isArray(me) ? figCss(me) : me === 'flat' ? (own ? figCss(own) : null)
        : (Array.isArray(ec) ? figCss(ec) : own ? figCss(own) : 'rgb(0,0,0)');
      const face = Array.isArray(mf) ? figCss(mf) : mf === 'flat' ? (own ? figCss(own) : null)
        : mf === 'auto' ? figCss(Array.isArray(T.S.color) ? T.S.color : [1, 1, 1]) : null;
      const key = `${edge}|${face}`;
      if (!groups.has(key)) groups.set(key, { edge, face, pts: [] });
      groups.get(key).pts.push([px[k], py[k]]);
    }
    for (const { edge, face, pts } of groups.values()) figMarkers(g, pts, marker, size, edge, face, width);
  }
  figMarkData(R, o, T);
}

/* ── surfaces and images ─────────────────────────────────────────────── */

/** A matrix's element (i, j), in MATLAB's order. */
function figAt(v, rows, i, j) {
  return v[i + rows * j];
}

/** A surface's grid: its x and y at each node, from vectors or matrices, and its size. */
function figGrid(o) {
  const Z = figP(o, 'ZData');
  const [m, n] = figDims(Z);
  const z = figNumbers(Z);
  if (!z || m < 1 || n < 1) return null;
  const X = figP(o, 'XData');
  const Y = figP(o, 'YData');
  const xv = figNumbers(X);
  const yv = figNumbers(Y);
  const xAt = xv && xv.length === m * n && figDims(X)[0] === m ? (i, j) => xv[i + m * j] : xv && xv.length === n ? (i, j) => xv[j] : (i, j) => j + 1;
  const yAt = yv && yv.length === m * n && figDims(Y)[0] === m ? (i, j) => yv[i + m * j] : yv && yv.length === m ? (i) => yv[i] : (i) => i + 1;
  return { m, n, z, xAt, yAt, rectilinear: !(xv && xv.length === m * n) && !(yv && yv.length === m * n) };
}

/** The colour of each node of a surface: from its CData, three numbers or one through the map. */
function figNodeColors(R, o, T, grid) {
  const C = figP(o, 'CData');
  const v = figNumbers(C) || grid.z;
  const dims = figP(o, 'CData') ? figDims(C) : [grid.m, grid.n];
  const { m, n } = grid;
  const out = new Array(m * n).fill(null);
  if (dims.length >= 3 && dims[2] === 3 && dims[0] === m && dims[1] === n) {
    const scale = C.cls === 'uint8' ? 255 : C.cls === 'uint16' ? 65535 : 1;
    for (let k = 0; k < m * n; k++) out[k] = [v[k] / scale, v[k + m * n] / scale, v[k + 2 * m * n] / scale];
    return out;
  }
  if (dims[0] !== m || dims[1] !== n) return out;
  const direct = figWord(figP(o, 'CDataMapping')) === 'direct';
  const cmap = figAxesColormap(R, T);
  const clim = figCLim(R, T);
  for (let k = 0; k < m * n; k++) out[k] = figMapColor(cmap, v[k], clim, direct, C && C.cls !== 'double' && C.cls !== 'single');
  return out;
}

/** A canvas the size of a box, at twice its pixels, and an image of it put back in the drawing. */
function figRaster(rect) {
  const scale = 2;
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.min(4000, Math.ceil(rect.w * scale)));
  canvas.height = Math.max(1, Math.min(4000, Math.ceil(rect.h * scale)));
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.setTransform(canvas.width / rect.w, 0, 0, canvas.height / rect.h, -rect.x * canvas.width / rect.w, -rect.y * canvas.height / rect.h);
  return { canvas, ctx, put: (g) => figEl('image', { href: canvas.toDataURL('image/png'), x: figN(rect.x), y: figN(rect.y),
    width: figN(rect.w), height: figN(rect.h), preserveAspectRatio: 'none' }, g) };
}

const figRgb = (c) => (c ? `rgb(${Math.round(c[0] * 255)},${Math.round(c[1] * 255)},${Math.round(c[2] * 255)})` : null);

/** Where a pixel falls between the ends of a run of increasing or decreasing pixels: [k, t], or null outside them. */
function figBetween(at, p) {
  const n = at.length;
  const up = at[n - 1] >= at[0];
  if (up ? p < at[0] || p > at[n - 1] : p > at[0] || p < at[n - 1]) return null;
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((at[mid] <= p) === up) lo = mid; else hi = mid;
  }
  const span = at[hi] - at[lo];
  return [lo, span ? (p - at[lo]) / span : 0];
}

/**
 * The faces of a surface on a grid of straight lines, blended pixel by
 * pixel between its nodes ('interp'): the values between them taken through
 * the colour map, as MATLAB blends them, or the colours themselves.
 */
function figBlend(R, o, T, grid, g, alpha) {
  const { m, n, xAt, yAt } = grid;
  const xs = Array.from({ length: n }, (_, j) => T.X(xAt(0, j)));
  const ys = Array.from({ length: m }, (_, i) => T.Y(yAt(i, 0)));
  if (!xs.every(Number.isFinite) || !ys.every(Number.isFinite)) return false;
  const C = figP(o, 'CData');
  const dims = C ? figDims(C) : [m, n];
  const v = figNumbers(C) || grid.z;
  const truecolor = dims.length >= 3 && dims[2] === 3;
  if (dims[0] !== m || dims[1] !== n || !v) return false;
  const scale = !truecolor ? 1 : C.cls === 'uint8' ? 255 : C.cls === 'uint16' ? 65535 : 1;
  const direct = figWord(figP(o, 'CDataMapping')) === 'direct';
  const zero = C && C.cls !== 'double' && C.cls !== 'single';
  const cmap = figAxesColormap(R, T);
  const clim = figCLim(R, T);
  const rect = T.rect;
  const k = 2;
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.min(4000, Math.ceil(rect.w * k)));
  canvas.height = Math.max(1, Math.min(4000, Math.ceil(rect.h * k)));
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;
  const img = ctx.createImageData(canvas.width, canvas.height);
  const cols = Array.from({ length: canvas.width }, (_, px) => figBetween(xs, rect.x + (px + 0.5) * rect.w / canvas.width));
  const a = Math.round(Math.min(1, Math.max(0, alpha)) * 255);
  for (let py = 0; py < canvas.height; py++) {
    const row = figBetween(ys, rect.y + (py + 0.5) * rect.h / canvas.height);
    if (!row) continue;
    const [i, s] = row;
    const i2 = Math.min(i + 1, m - 1);
    for (let px = 0; px < canvas.width; px++) {
      const col = cols[px];
      if (!col) continue;
      const [j, t] = col;
      const j2 = Math.min(j + 1, n - 1);
      const mix = (off) => (1 - s) * ((1 - t) * v[off + i + m * j] + t * v[off + i + m * j2]) + s * ((1 - t) * v[off + i2 + m * j] + t * v[off + i2 + m * j2]);
      const c = truecolor ? [mix(0) / scale, mix(m * n) / scale, mix(2 * m * n) / scale] : figMapColor(cmap, mix(0), clim, direct, zero);
      if (!c || !Number.isFinite(c[0] + c[1] + c[2])) continue;
      const at = (py * canvas.width + px) * 4;
      img.data[at] = Math.round(Math.min(1, Math.max(0, c[0])) * 255);
      img.data[at + 1] = Math.round(Math.min(1, Math.max(0, c[1])) * 255);
      img.data[at + 2] = Math.round(Math.min(1, Math.max(0, c[2])) * 255);
      img.data[at + 3] = a;
    }
  }
  ctx.putImageData(img, 0, 0);
  figEl('image', { href: canvas.toDataURL('image/png'), x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h), preserveAspectRatio: 'none' }, g);
  return true;
}

/**
 * A surface seen from above: its faces painted -- each the colour of its
 * first node ('flat'), or blended from its four ('interp') -- and its edges.
 */
function figSurface2(R, o, T, g) {
  const grid = figGrid(o);
  if (!grid) return;
  const { m, n, xAt, yAt } = grid;
  const fc = figP(o, 'FaceColor') !== undefined ? figColor(figP(o, 'FaceColor')) : 'flat';
  const ec = figP(o, 'EdgeColor') !== undefined ? figColor(figP(o, 'EdgeColor')) : [0, 0, 0];
  const fa = figNumber(figP(o, 'FaceAlpha'), 1);
  const colors = fc === 'flat' || fc === 'interp' || ec === 'flat' || ec === 'interp' ? figNodeColors(R, o, T, grid) : null;
  const P = (i, j) => [T.X(xAt(i, j)), T.Y(yAt(i, j))];
  const blended = fc === 'interp' && grid.rectilinear && m > 1 && n > 1 && figBlend(R, o, T, grid, g, fa);
  if (!blended && fc !== 'none' && fc !== null && m > 1 && n > 1) {
    const r = figRaster(T.rect);
    if (r) {
      const { ctx } = r;
      ctx.globalAlpha = fa < 1 ? Math.max(0, fa) : 1;
      for (let i = 0; i < m - 1; i++) {
        for (let j = 0; j < n - 1; j++) {
          let c;
          if (Array.isArray(fc)) c = fc;
          else if (fc === 'interp') {
            const four = [colors[i + m * j], colors[i + 1 + m * j], colors[i + m * (j + 1)], colors[i + 1 + m * (j + 1)]];
            if (four.some(x => !x)) continue;
            c = [0, 1, 2].map(k => (four[0][k] + four[1][k] + four[2][k] + four[3][k]) / 4);
          } else c = colors[i + m * j];
          if (!c) continue;
          const q = [P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)];
          if (q.some(p => !Number.isFinite(p[0] + p[1]))) continue;
          ctx.fillStyle = figRgb(c);
          ctx.strokeStyle = ctx.fillStyle;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(q[0][0], q[0][1]);
          for (let k = 1; k < 4; k++) ctx.lineTo(q[k][0], q[k][1]);
          ctx.closePath();
          ctx.fill();
          if (fa >= 1) ctx.stroke();   // closes the hairline seams between faces
        }
      }
      r.put(g);
    }
  }
  if (ec !== 'none' && ec !== null && (m * n) <= 250000) {
    const width = figWidth(R, o);
    const style = figText(figP(o, 'LineStyle')).trim() || '-';
    if (style !== 'none') {
      let d = '';
      for (let i = 0; i < m; i++) {
        const px = []; const py = [];
        for (let j = 0; j < n; j++) { const p = P(i, j); px.push(p[0]); py.push(p[1]); }
        d += figPolyline(px, py);
      }
      for (let j = 0; j < n; j++) {
        const px = []; const py = [];
        for (let i = 0; i < m; i++) { const p = P(i, j); px.push(p[0]); py.push(p[1]); }
        d += figPolyline(px, py);
      }
      const stroke = Array.isArray(ec) ? figCss(ec) : 'rgb(0,0,0)';
      figEl('path', { d, fill: 'none', stroke, 'stroke-width': figN(width), 'stroke-opacity': figNumber(figP(o, 'EdgeAlpha'), 1),
        'stroke-dasharray': figDash(style, width) }, g);
    }
  }
  figMarkData(R, o, T);
}

/** An image: its pixels between the centres its XData and YData give its first and last. */
function figImage(R, o, T, g) {
  const C = figP(o, 'CData');
  const v = figNumbers(C);
  const dims = figDims(C);
  const [m, n] = dims;
  if (!v || !m || !n || m * n > 16e6) return;
  const truecolor = dims.length >= 3 && dims[2] === 3;
  const canvas = document.createElement('canvas');
  canvas.width = n;
  canvas.height = m;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const img = ctx.createImageData(n, m);
  const scale = C.cls === 'uint8' ? 255 : C.cls === 'uint16' ? 65535 : C.cls === 'logical' ? 1 : 1;
  const direct = (figWord(figP(o, 'CDataMapping')) || 'direct') === 'direct';
  const cmap = figAxesColormap(R, T);
  const clim = figCLim(R, T);
  const alpha = figNumber(figP(o, 'AlphaData'), 1);
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) {
      const k = i + m * j;
      const c = truecolor ? [v[k] / scale, v[k + m * n] / scale, v[k + 2 * m * n] / scale]
        : figMapColor(cmap, v[k], clim, direct, C.cls !== 'double' && C.cls !== 'single');
      const at = (i * n + j) * 4;
      if (!c || !c.every(Number.isFinite)) continue;
      img.data[at] = Math.round(Math.min(1, Math.max(0, c[0])) * 255);
      img.data[at + 1] = Math.round(Math.min(1, Math.max(0, c[1])) * 255);
      img.data[at + 2] = Math.round(Math.min(1, Math.max(0, c[2])) * 255);
      img.data[at + 3] = Math.round(Math.min(1, Math.max(0, Number.isFinite(alpha) ? alpha : 1)) * 255);
    }
  }
  ctx.putImageData(img, 0, 0);
  const xd = figNumbers(figP(o, 'XData'));
  const yd = figNumbers(figP(o, 'YData'));
  const xs = xd && xd.length ? [xd[0], xd[xd.length - 1]] : [1, n];
  const ys = yd && yd.length ? [yd[0], yd[yd.length - 1]] : [1, m];
  const dx = n > 1 ? (xs[1] - xs[0]) / (n - 1) : 1;
  const dy = m > 1 ? (ys[1] - ys[0]) / (m - 1) : 1;
  const x0 = T.X(xs[0] - dx / 2);
  const x1 = T.X(xs[1] + dx / 2);
  const y0 = T.Y(ys[0] - dy / 2);
  const y1 = T.Y(ys[1] + dy / 2);
  if (!Number.isFinite(x0 + x1 + y0 + y1)) return;
  // Drawn as the first row at y0 and the first column at x0, whichever way the axes run.
  const flipX = x1 < x0;
  const flipY = y1 < y0;
  const image = figEl('image', {
    href: canvas.toDataURL('image/png'), x: figN(Math.min(x0, x1)), y: figN(Math.min(y0, y1)),
    width: figN(Math.abs(x1 - x0)), height: figN(Math.abs(y1 - y0)), preserveAspectRatio: 'none',
    transform: flipX || flipY ? `translate(${figN(flipX ? x0 + x1 : 0)} ${figN(flipY ? y0 + y1 : 0)}) scale(${flipX ? -1 : 1} ${flipY ? -1 : 1})` : null
  }, g);
  image.style.imageRendering = 'pixelated';
  figMark(R, o, { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) });
}

/* ── text ────────────────────────────────────────────────────────────── */

/**
 * A text object: in an axes at its Position, in data units or another; in
 * a figure, a fraction of it or a length.
 */
function figTextObject(R, g, o, T, box) {
  const lines = figLines(figP(o, 'String'));
  if (!lines.length || lines.every(s => s === '')) return;
  const pos = figNumbers(figP(o, 'Position')) || [0, 0];
  const units = figWord(figP(o, 'Units')) || (T ? 'data' : 'normalized');
  let x; let y;
  if (T && units === 'data') { x = T.X(pos[0]); y = T.Y(pos[1] ?? 0); }
  else {
    const area = T ? T.rect : box;
    const ux = figUnitPx(units, R.model, 0);
    const uy = figUnitPx(units, R.model, 1);
    if (ux === null) { x = area.x + pos[0] * area.w; y = area.y + area.h - (pos[1] ?? 0) * area.h; }
    else { x = area.x + pos[0] * ux; y = area.y + area.h - (pos[1] ?? 0) * uy; }
  }
  if (!Number.isFinite(x + y)) return;
  const fontUnits = figWord(figP(o, 'FontUnits')) || 'points';
  const fsz = figNumber(figP(o, 'FontSize'), 10);
  const size = fontUnits === 'pixels' ? fsz : fontUnits === 'normalized' && T ? fsz * T.rect.h : fsz * R.pt;
  const edge = figColor(figP(o, 'EdgeColor'));
  const bg = figColor(figP(o, 'BackgroundColor'));
  const gt = figObjectGroup(R, g, o);
  const m = figDrawText(gt, lines, x, y, {
    size, family: figFamily(figText(figP(o, 'FontName')) || 'Helvetica'), pt: R.pt,
    bold: figWord(figP(o, 'FontWeight')) === 'bold', italic: /italic|oblique/.test(figWord(figP(o, 'FontAngle'))),
    color: figCss(figColor(figP(o, 'Color')), 'rgb(0,0,0)'),
    halign: figWord(figP(o, 'HorizontalAlignment')) || 'left',
    valign: figWord(figP(o, 'VerticalAlignment')) || 'middle',
    rotation: figNumber(figP(o, 'Rotation'), 0),
    interpreter: figWord(figP(o, 'Interpreter')) || 'tex',
    background: Array.isArray(bg) ? figCss(bg) : null,
    edge: Array.isArray(edge) ? figCss(edge) : null,
    edgeWidth: figWidth(R, o),
    margin: figNumber(figP(o, 'Margin'), 3) * R.pt
  });
  const halign = figWord(figP(o, 'HorizontalAlignment')) || 'left';
  figMark(R, o, { x: x - (halign === 'center' ? m.width / 2 : halign === 'right' ? m.width : 0), y: y - m.height / 2, w: m.width, h: m.height });
}

/* ── series a file keeps without the objects that draw them ──────────── */

/** The first colour of an axes' colour order, or the one a series' SeriesIndex picks. */
function figSeriesColor(o, T) {
  const order = figP(T.ax, 'ColorOrder');
  const v = figNumbers(order);
  const [n, three] = figDims(order);
  const k = Math.max(0, Math.round(figNumber(figP(o, 'SeriesIndex'), 1)) - 1);
  if (v && three === 3 && n) { const i = k % n; return [v[i], v[i + n], v[i + 2 * n]]; }
  const hg2 = [[0, 0.447, 0.741], [0.85, 0.325, 0.098], [0.929, 0.694, 0.125], [0.494, 0.184, 0.556], [0.466, 0.674, 0.188], [0.301, 0.745, 0.933], [0.635, 0.078, 0.184]];
  return hg2[k % hg2.length];
}

/** A histogram's bar heights: its Values, or its counts as its Normalization asks. */
function figHistogramHeights(o) {
  const values = figNumbers(figP(o, 'Values'));
  if (values) return values;
  const counts = figNumbers(figP(o, 'BinCounts'));
  const edges = figNumbers(figP(o, 'BinEdges'));
  if (!counts) return null;
  const data = figNumbers(figP(o, 'Data'));
  let total = 0;
  if (data) for (let k = 0; k < data.length; k++) if (!Number.isNaN(data[k])) total++;
  if (!total) total = counts.reduce((a, b) => a + b, 0) || 1;
  const width = (k) => (edges && edges.length > k + 1 ? edges[k + 1] - edges[k] : 1);
  let run = 0;
  switch (figWord(figP(o, 'Normalization')) || 'count') {
    case 'probability': return counts.map(c => c / total);
    case 'countdensity': return counts.map((c, k) => c / width(k));
    case 'pdf': return counts.map((c, k) => c / total / width(k));
    case 'cumcount': return counts.map(c => (run += c));
    case 'cdf': return counts.map(c => (run += c) / total);
    default: return counts;
  }
}

function figHistogram(R, o, T, g) {
  const edges = figNumbers(figP(o, 'BinEdges'));
  const heights = figHistogramHeights(o);
  if (!edges || !heights || edges.length < 2) return;
  const across = figWord(figP(o, 'Orientation')) === 'horizontal';
  const fc = figColor(figP(o, 'FaceColor'));
  const face = Array.isArray(fc) ? fc : fc === 'none' ? null : figSeriesColor(o, T);
  const ec = figP(o, 'EdgeColor') !== undefined ? figColor(figP(o, 'EdgeColor')) : [0.15, 0.15, 0.15];
  const stairs = figWord(figP(o, 'DisplayStyle')) === 'stairs';
  const width = figWidth(R, o);
  const base = (across ? T.xLog : T.yLog) ? (across ? T.xLim[0] : T.yLim[0]) : 0;
  let d = '';
  const n = Math.min(heights.length, edges.length - 1);
  for (let k = 0; k < n; k++) {
    const [a, b, h] = [edges[k], edges[k + 1], heights[k]];
    const p = across ? [[base, a], [h, a], [h, b], [base, b]] : [[a, base], [a, h], [b, h], [b, base]];
    const px = p.map(([x, y]) => [T.X(x), T.Y(y)]);
    if (px.some(q => !Number.isFinite(q[0] + q[1]))) continue;
    d += `M${px.map(q => `${figN(q[0])} ${figN(q[1])}`).join('L')}${stairs ? '' : 'Z'}`;
  }
  if (!d) return;
  figEl('path', {
    d, fill: stairs || !face ? 'none' : figCss(face), 'fill-opacity': stairs ? null : figNumber(figP(o, 'FaceAlpha'), 0.6),
    stroke: Array.isArray(ec) ? figCss(ec) : stairs ? figCss(face || [0, 0, 0]) : 'none', 'stroke-width': figN(width)
  }, g);
  figMark(R, o, null);
}

/** What kind of series a type is, when one is drawn from its data: bar, area, stem, stair, errorbar, scatter, quiver. */
function figSeriesKind(type) {
  const m = /(bar|area|stem|stair|errorbar|scatter|quiver)/.exec(type);
  return m ? m[1] : null;
}

function figSeries(R, o, T, g) {
  const kind = figSeriesKind(o.low);
  const ys = figNumbers(figP(o, 'YData'));
  if (!ys || !ys.length) { figNotDrawn(R, o); return; }
  const xv = figNumbers(figP(o, 'XData'));
  const xs = xv && xv.length === ys.length ? xv : Float64Array.from(ys, (_, k) => k + 1);
  const color = figColor(figP(o, kind === 'bar' || kind === 'area' ? 'FaceColor' : 'Color'));
  const own = Array.isArray(color) ? color : figSeriesColor(o, T);
  const css = figCss(own);
  const width = figWidth(R, o);
  const base = figNumber(figP(o, 'BaseValue'), 0);
  const line = (pts) => figPolyline(pts.map(p => T.X(p[0])), pts.map(p => T.Y(p[1])));
  const ec = figColor(figP(o, 'EdgeColor'));
  const edge = Array.isArray(ec) ? figCss(ec) : ec === 'none' ? 'none' : 'rgb(0,0,0)';
  switch (kind) {
    case 'bar': {
      const across = figOn(figP(o, 'Horizontal'), false) || figWord(figP(o, 'Orientation')) === 'horizontal';
      let step = Infinity;
      for (let k = 1; k < xs.length; k++) if (xs[k] !== xs[k - 1]) step = Math.min(step, Math.abs(xs[k] - xs[k - 1]));
      const half = (Number.isFinite(step) ? step : 1) * figNumber(figP(o, 'BarWidth'), 0.8) / 2;
      let d = '';
      xs.forEach((x, k) => {
        const p = across ? [[base, x - half], [ys[k], x - half], [ys[k], x + half], [base, x + half]]
          : [[x - half, base], [x - half, ys[k]], [x + half, ys[k]], [x + half, base]];
        const q = p.map(([a, b]) => [T.X(a), T.Y(b)]);
        if (q.every(v => Number.isFinite(v[0] + v[1]))) d += `M${q.map(v => `${figN(v[0])} ${figN(v[1])}`).join('L')}Z`;
      });
      if (d) figEl('path', { d, fill: css, stroke: edge, 'stroke-width': figN(width) }, g);
      break;
    }
    case 'area': {
      const pts = [[xs[0], base], ...Array.from(xs, (x, k) => [x, ys[k]]), [xs[xs.length - 1], base]];
      const d = line(pts);
      if (d) figEl('path', { d: `${d}Z`, fill: css, stroke: edge, 'stroke-width': figN(width) }, g);
      break;
    }
    case 'stair': {
      const pts = [];
      xs.forEach((x, k) => { if (k) pts.push([x, ys[k - 1]]); pts.push([x, ys[k]]); });
      figEl('path', { d: line(pts), fill: 'none', stroke: css, 'stroke-width': figN(width) }, g);
      break;
    }
    case 'stem': {
      let d = '';
      xs.forEach((x, k) => { d += line([[x, base], [x, ys[k]]]); });
      figEl('path', { d, fill: 'none', stroke: css, 'stroke-width': figN(width) }, g);
      figMarkers(g, Array.from(xs, (x, k) => [T.X(x), T.Y(ys[k])]).filter(p => Number.isFinite(p[0] + p[1])), figMarkerName(figP(o, 'Marker')) === 'none' ? 'none' : (figMarkerName(figP(o, 'Marker')) || 'o'), figNumber(figP(o, 'MarkerSize'), 6) * R.pt, css, null, width);
      break;
    }
    case 'errorbar': {
      figEl('path', { d: line(Array.from(xs, (x, k) => [x, ys[k]])), fill: 'none', stroke: css, 'stroke-width': figN(width) }, g);
      const lo = figNumbers(figP(o, 'YNegativeDelta')) || figNumbers(figP(o, 'LData'));
      const hi = figNumbers(figP(o, 'YPositiveDelta')) || figNumbers(figP(o, 'UData'));
      if (lo || hi) {
        let d = '';
        xs.forEach((x, k) => {
          const a = ys[k] - (lo ? lo[k] || 0 : 0);
          const b = ys[k] + (hi ? hi[k] || 0 : 0);
          d += line([[x, a], [x, b]]);
          const cx = T.X(x);
          for (const y of [a, b]) { const cy = T.Y(y); if (Number.isFinite(cx + cy)) d += `M${figN(cx - 3)} ${figN(cy)}H${figN(cx + 3)}`; }
        });
        figEl('path', { d, fill: 'none', stroke: css, 'stroke-width': figN(width) }, g);
      }
      break;
    }
    case 'scatter': {
      const sizes = figNumbers(figP(o, 'SizeData'));
      const cd = figP(o, 'CData');
      const cv = figNumbers(cd);
      const [cr, cc] = figDims(cd);
      const marker = figMarkerName(figP(o, 'Marker')) === 'none' ? 'o' : figMarkerName(figP(o, 'Marker'));
      const filled = ['flat', 'auto'].includes(figColor(figP(o, 'MarkerFaceColor'))) || Array.isArray(figColor(figP(o, 'MarkerFaceColor')));
      const cmap = figAxesColormap(R, T);
      let clim = null;
      xs.forEach((x, k) => {
        const px = T.X(x);
        const py = T.Y(ys[k]);
        if (!Number.isFinite(px + py)) return;
        let c = own;
        if (cv && cc === 3 && cr === xs.length) c = [cv[k], cv[k + cr], cv[k + 2 * cr]];
        else if (cv && cc === 3) c = [cv[0], cv[1], cv[2]];
        else if (cv && cv.length === xs.length) {
          if (!clim) clim = figRange(cv) || [0, 1];
          c = figMapColor(cmap, cv[k], clim[1] > clim[0] ? clim : [clim[0] - 1, clim[0] + 1], false, false) || own;
        }
        const s = sizes ? (sizes.length === xs.length ? sizes[k] : sizes[0]) : 36;
        const size = Math.sqrt(Math.max(0, s)) * R.pt;
        const mf = figColor(figP(o, 'MarkerFaceColor'));
        figMarkers(g, [[px, py]], marker, size, filled ? (Array.isArray(figColor(figP(o, 'MarkerEdgeColor'))) ? figCss(figColor(figP(o, 'MarkerEdgeColor'))) : null) : figCss(c),
          filled ? figCss(Array.isArray(mf) ? mf : c) : null, width);
      });
      break;
    }
    case 'quiver': {
      const us = figNumbers(figP(o, 'UData'));
      const vs = figNumbers(figP(o, 'VData'));
      if (!us || !vs) { figNotDrawn(R, o); return; }
      let longest = 0;
      for (let k = 0; k < us.length; k++) longest = Math.max(longest, Math.hypot(us[k], vs[k]) || 0);
      let spacing = Infinity;
      for (let k = 1; k < xs.length; k++) if (xs[k] !== xs[k - 1]) spacing = Math.min(spacing, Math.abs(xs[k] - xs[k - 1]));
      const scale = figOn(figP(o, 'AutoScale'), true) && longest > 0 ? 0.9 * (Number.isFinite(spacing) ? spacing : 1) / longest * figNumber(figP(o, 'AutoScaleFactor'), 0.9) / 0.9 : 1;
      let d = '';
      xs.forEach((x, k) => {
        const a = [T.X(x), T.Y(ys[k])];
        const b = [T.X(x + us[k] * scale), T.Y(ys[k] + vs[k] * scale)];
        if (!Number.isFinite(a[0] + a[1] + b[0] + b[1])) return;
        const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
        const head = Math.min(8, Math.hypot(b[0] - a[0], b[1] - a[1]) * 0.3);
        d += `M${figN(a[0])} ${figN(a[1])}L${figN(b[0])} ${figN(b[1])}`
          + `M${figN(b[0] - head * Math.cos(ang - 0.4))} ${figN(b[1] - head * Math.sin(ang - 0.4))}L${figN(b[0])} ${figN(b[1])}`
          + `L${figN(b[0] - head * Math.cos(ang + 0.4))} ${figN(b[1] - head * Math.sin(ang + 0.4))}`;
      });
      figEl('path', { d, fill: 'none', stroke: css, 'stroke-width': figN(width) }, g);
      break;
    }
    default:
      figNotDrawn(R, o);
  }
  figMarkData(R, o, T);
}

/* ── legends, colour bars and annotations ────────────────────────────── */

/** What a legend's entry is drawn with: a line, a patch's face or a marker, of the object it stands for. */
function figLegendToken(R, g, target, x0, x1, y, rowH, T) {
  const t = target ? target.low : '';
  const patchy = /patch|bar|area|histogram|surface|contour/.test(t);
  const first = target && target.children.find(c => c.low === 'patch' || c.low === 'line');
  const src = patchy && target.low !== 'patch' && first && figP(target, 'FaceColor') === undefined ? first : target;
  if (!src) return;
  if (patchy) {
    let fc = figColor(figP(src, 'FaceColor'));
    if (!Array.isArray(fc)) {
      const own = figVertexColors(R, src, T || { ax: target.parent || target, S: {} }, 'FaceVertexCData');
      fc = own && own[0] ? own[0] : t === 'histogram' ? figSeriesColor(target, { ax: target.parent || target }) : fc === 'none' ? null : [0.5, 0.5, 0.5];
    }
    const ec = figColor(figP(src, 'EdgeColor'));
    const h = Math.min(rowH * 0.7, 10 * R.pt);
    figEl('rect', { x: figN(x0), y: figN(y - h / 2), width: figN(x1 - x0), height: figN(h),
      fill: fc ? figCss(fc) : 'none', 'fill-opacity': t === 'histogram' ? figNumber(figP(src, 'FaceAlpha'), 0.6) : figNumber(figP(src, 'FaceAlpha'), 1),
      stroke: Array.isArray(ec) ? figCss(ec) : ec === 'none' ? 'none' : 'rgb(0,0,0)', 'stroke-width': figN(0.5 * R.pt) }, g);
    return;
  }
  const lineSrc = /series|line|stem|stair|errorbar/.test(t) && first && figP(target, 'Color') === undefined ? first : src;
  const color = figColor(figP(lineSrc, 'Color')) || (T ? figSeriesColor(target, T) : [0, 0, 0]);
  const css = figCss(Array.isArray(color) ? color : [0, 0, 0]);
  const style = figText(figP(lineSrc, 'LineStyle')).trim() || (/scatter/.test(t) ? 'none' : '-');
  const width = figWidth(R, lineSrc);
  if (style !== 'none') figEl('path', { d: `M${figN(x0)} ${figN(y)}H${figN(x1)}`, stroke: css, 'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width) }, g);
  const marker = /scatter/.test(t) ? (figMarkerName(figP(src, 'Marker')) === 'none' ? 'o' : figMarkerName(figP(src, 'Marker'))) : figMarkerName(figP(lineSrc, 'Marker'));
  if (marker !== 'none') {
    const mf = figColor(figP(lineSrc, 'MarkerFaceColor'));
    const me = figColor(figP(lineSrc, 'MarkerEdgeColor'));
    figMarkers(g, [[(x0 + x1) / 2, y]], marker, Math.min(figNumber(figP(lineSrc, 'MarkerSize'), 6), 8) * R.pt,
      me === 'none' ? null : Array.isArray(me) ? figCss(me) : css, Array.isArray(mf) ? figCss(mf) : mf === 'flat' || mf === 'auto' ? css : null, width);
  }
}

/**
 * A legend of R2014b and later, which the file keeps as what it says and
 * which objects: each entry's token and text, in the box at its Position.
 */
function figLegend(R, g, o, box) {
  const rect = figPlace(figNumbers(figP(o, 'Position')), figWord(figP(o, 'Units')) || 'normalized', box, R.model);
  if (!rect || rect.w < 2 || rect.h < 2) return;
  const strings = figLines(figP(o, 'String'));
  const handles = Array.from(figNumbers(figP(o, 'PlotChildren')) || []);
  let targets = handles.map(h => R.model.byHandle.get(h) || null);
  if (!targets.length || targets.every(t => !t)) {
    // The objects it stands for, when the file does not say: its axes', in order.
    const axes = R.model.byHandle.get(figNumber(figP(o, 'Axes'))) || (o.parent && o.parent.children.find(c => c.low === 'axes'));
    targets = axes ? axes.children.filter(c => !c.role && c.low !== 'text' && !/baseline|light/.test(c.low)) : [];
  }
  const n = strings.length;
  if (!n) return;
  const gl = figObjectGroup(R, g, o);
  figMark(R, o, rect);
  const boxed = figOn(figP(o, 'Box'), true);
  const bg = figColor(figP(o, 'Color'));
  figEl('rect', { x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h),
    fill: bg === 'none' ? 'none' : figCss(Array.isArray(bg) ? bg : [1, 1, 1]),
    stroke: boxed ? figCss(figColor(figP(o, 'EdgeColor')) || [0.15, 0.15, 0.15]) : 'none', 'stroke-width': figN(figWidth(R, o)) }, gl);
  const size = figNumber(figP(o, 'FontSize'), R.model.hg2 ? 9 : 10) * R.pt;
  const token = ((figNumbers(figP(o, 'ItemTokenSize')) || [30])[0] || 30) * R.pt;
  const across = figWord(figP(o, 'Orientation')) === 'horizontal';
  const cols = across ? n : Math.max(1, Math.round(figNumber(figP(o, 'NumColumns'), 1)));
  const rows = Math.ceil(n / cols);
  const colW = rect.w / cols;
  const rowH = rect.h / rows;
  const textColor = figCss(figColor(figP(o, 'TextColor')) || [0, 0, 0]);
  const interpreter = figWord(figP(o, 'Interpreter')) || 'tex';
  const family = figFamily(figText(figP(o, 'FontName')) || 'Helvetica');
  const pad = 4 * R.pt;
  const length = Math.min(token, colW * 0.45) - pad;
  for (let k = 0; k < n; k++) {
    const col = across ? k : Math.floor(k / rows);
    const row = across ? 0 : k % rows;
    const x = rect.x + col * colW + pad;
    const y = rect.y + (row + 0.5) * rowH;
    const target = targets[k] || null;
    const owner = target && target.parent;
    figLegendToken(R, gl, target, x, x + length, y, rowH, owner ? { ax: owner, S: {} } : null);
    figDrawText(gl, strings[k], x + length + 2 * R.pt, y, { size, family, color: textColor, valign: 'middle', interpreter, pt: R.pt });
  }
}

/** A colour bar of R2014b and later: the colour map between its limits, its ticks and labels. */
function figColorbar(R, g, o, box) {
  const rect = figPlace(figNumbers(figP(o, 'Position')), figWord(figP(o, 'Units')) || 'normalized', box, R.model);
  if (!rect || rect.w < 1 || rect.h < 1) return;
  const loc = figWord(figP(o, 'Location')) || 'eastoutside';
  const vertical = !/north|south/.test(loc);
  const limits = figNumbers(figP(o, 'Limits')) || figNumbers(figP(o, vertical ? 'YLim' : 'XLim'));
  const lim = limits && limits.length >= 2 && limits[1] > limits[0] ? [limits[0], limits[1]] : [0, 1];
  const cmap = figColormap(figP(o, 'Colormap')) || R.cmap;
  const gc = figObjectGroup(R, g, o);
  figMark(R, o, rect);
  const canvas = document.createElement('canvas');
  canvas.width = vertical ? 1 : cmap.length;
  canvas.height = vertical ? cmap.length : 1;
  const ctx = canvas.getContext('2d');
  if (ctx) {
    const img = ctx.createImageData(canvas.width, canvas.height);
    cmap.forEach((c, k) => {
      const at = (vertical ? cmap.length - 1 - k : k) * 4;
      img.data[at] = Math.round(c[0] * 255); img.data[at + 1] = Math.round(c[1] * 255); img.data[at + 2] = Math.round(c[2] * 255); img.data[at + 3] = 255;
    });
    ctx.putImageData(img, 0, 0);
    const im = figEl('image', { href: canvas.toDataURL('image/png'), x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h), preserveAspectRatio: 'none' }, gc);
    im.style.imageRendering = 'pixelated';
  }
  const ink = figCss(figColor(figP(o, vertical ? 'YColor' : 'XColor')) || figColor(figP(o, 'Color')) || [0.15, 0.15, 0.15]);
  if (figOn(figP(o, 'Box'), true)) figEl('rect', { x: figN(rect.x), y: figN(rect.y), width: figN(rect.w), height: figN(rect.h), fill: 'none', stroke: ink, 'stroke-width': figN(0.5 * R.pt) }, gc);
  // each tick with the label saved for it, those inside the limits, no more than an axis holds
  const saved = figNumbers(figP(o, 'Ticks')) || figNumbers(figP(o, vertical ? 'YTick' : 'XTick'));
  const all = saved ? Array.from(saved) : figLinearTicks(lim[0], lim[1], vertical ? rect.h / 30 : rect.w / 60);
  let labels = figLines(figP(o, 'TickLabels'));
  if (!labels.length) labels = figLines(figP(o, vertical ? 'YTickLabel' : 'XTickLabel'));
  let pairs = all.map((v, k) => [v, labels.length ? labels[k % labels.length] : null]).filter(([v]) => v >= lim[0] && v <= lim[1]);
  if (pairs.length > 200) pairs = pairs.filter((_, k) => k % Math.ceil(pairs.length / 200) === 0);
  const ticks = pairs.map(([v]) => v);
  const made = figTickLabels(ticks, false).labels;
  labels = pairs.map(([, l], k) => (l === null ? made[k] : l));
  const size = figNumber(figP(o, 'FontSize'), R.model.hg2 ? 9 : 10) * R.pt;
  const other = vertical ? figWord(figP(o, 'YAxisLocation')) === 'left' || /west/.test(loc) : figWord(figP(o, 'XAxisLocation')) === 'top' || /north/.test(loc);
  const len = Math.min(vertical ? rect.w : rect.h, 4 * R.pt) * 0.6;
  let d = '';
  ticks.forEach((v, k) => {
    const f = (v - lim[0]) / (lim[1] - lim[0]);
    if (vertical) {
      const y = rect.y + rect.h * (1 - f);
      d += `M${figN(rect.x)} ${figN(y)}h${figN(len)}M${figN(rect.x + rect.w)} ${figN(y)}h${figN(-len)}`;
      figDrawText(gc, labels[k] || '', other ? rect.x - size * 0.4 : rect.x + rect.w + size * 0.4, y,
        { size, color: ink, halign: other ? 'right' : 'left', valign: 'middle', interpreter: figWord(figP(o, 'TickLabelInterpreter')) || 'tex', pt: R.pt });
    } else {
      const x = rect.x + rect.w * f;
      d += `M${figN(x)} ${figN(rect.y)}v${figN(len)}M${figN(x)} ${figN(rect.y + rect.h)}v${figN(-len)}`;
      figDrawText(gc, labels[k] || '', x, other ? rect.y - size * 0.4 : rect.y + rect.h + size * 0.4,
        { size, color: ink, halign: 'center', valign: other ? 'bottom' : 'top', interpreter: figWord(figP(o, 'TickLabelInterpreter')) || 'tex', pt: R.pt });
    }
  });
  if (d) figEl('path', { d, stroke: ink, 'stroke-width': figN(0.5 * R.pt) }, gc);
}

/** An arrow's head at (x, y), pointing along `angle`, `length` long and `width` wide. */
function figArrowHead(x, y, angle, length, width) {
  const bx = x - length * Math.cos(angle);
  const by = y - length * Math.sin(angle);
  const nx = -Math.sin(angle) * width / 2;
  const ny = Math.cos(angle) * width / 2;
  const notch = 0.25 * length;
  return `M${figN(x)} ${figN(y)}L${figN(bx + nx)} ${figN(by + ny)}L${figN(bx + notch * Math.cos(angle))} ${figN(by + notch * Math.sin(angle))}L${figN(bx - nx)} ${figN(by - ny)}Z`;
}

/** An annotation, in the figure's own coordinates: a line, an arrow, a text box, a rectangle or an ellipse. */
function figAnnotation(R, g, a, box) {
  const t = a.low.replace(/^scribe\./, '');
  const units = figWord(figP(a, 'Units')) || 'normalized';
  const ga = figObjectGroup(R, g, a);
  const color = figCss(figColor(figP(a, 'Color')) || [0, 0, 0]);
  const width = figWidth(R, a);
  const style = figText(figP(a, 'LineStyle')).trim() || '-';
  const toPx = (x, y) => {
    const u = figUnitPx(units, R.model, 0);
    const v = figUnitPx(units, R.model, 1);
    return u === null ? [box.x + x * box.w, box.y + box.h - y * box.h] : [box.x + x * u, box.y + box.h - y * v];
  };
  if (['line', 'arrow', 'doublearrow', 'textarrow'].includes(t)) {
    let xs = figNumbers(figP(a, 'X'));
    let ys = figNumbers(figP(a, 'Y'));
    const pos = figNumbers(figP(a, 'Position'));
    if ((!xs || !ys) && pos && pos.length >= 4) { xs = [pos[0], pos[0] + pos[2]]; ys = [pos[1], pos[1] + pos[3]]; }
    if (!xs || !ys || xs.length < 2 || ys.length < 2) return;
    const p0 = toPx(xs[0], ys[0]);
    const p1 = toPx(xs[1], ys[1]);
    if (!Number.isFinite(p0[0] + p0[1] + p1[0] + p1[1])) return;
    figEl('path', { d: `M${figN(p0[0])} ${figN(p0[1])}L${figN(p1[0])} ${figN(p1[1])}`, stroke: color, 'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width) }, ga);
    const angle = Math.atan2(p1[1] - p0[1], p1[0] - p0[0]);
    const hl = figNumber(figP(a, 'HeadLength'), 10) * R.pt;
    const hw = figNumber(figP(a, 'HeadWidth'), 10) * R.pt;
    if (t !== 'line') figEl('path', { d: figArrowHead(p1[0], p1[1], angle, hl, hw), fill: color, stroke: color, 'stroke-width': figN(width) }, ga);
    if (t === 'doublearrow') figEl('path', { d: figArrowHead(p0[0], p0[1], angle + Math.PI, hl, hw), fill: color, stroke: color }, ga);
    if (t === 'textarrow') {
      const lines = figLines(figP(a, 'String'));
      figDrawText(ga, lines, p0[0] - 4 * Math.cos(angle), p0[1] - 4 * Math.sin(angle), {
        size: figNumber(figP(a, 'FontSize'), 10) * R.pt, color: figCss(figColor(figP(a, 'TextColor')) || [0, 0, 0]),
        halign: Math.cos(angle) >= 0 ? 'right' : 'left', valign: 'middle', interpreter: figWord(figP(a, 'Interpreter')) || 'tex', pt: R.pt
      });
    }
    figMark(R, a, { x: Math.min(p0[0], p1[0]), y: Math.min(p0[1], p1[1]), w: Math.abs(p1[0] - p0[0]), h: Math.abs(p1[1] - p0[1]) });
    return;
  }
  const pos = figNumbers(figP(a, 'Position'));
  if (!pos || pos.length < 4) return;
  const p0 = toPx(pos[0], pos[1]);
  const p1 = toPx(pos[0] + pos[2], pos[1] + pos[3]);
  const r = { x: Math.min(p0[0], p1[0]), y: Math.min(p0[1], p1[1]), w: Math.abs(p1[0] - p0[0]), h: Math.abs(p1[1] - p0[1]) };
  if (!Number.isFinite(r.x + r.y + r.w + r.h)) return;
  figMark(R, a, r);
  const fc = figColor(figP(a, t === 'textbox' ? 'BackgroundColor' : 'FaceColor'));
  const ec = figColor(figP(a, t === 'textbox' ? 'EdgeColor' : 'Color'));
  const shape = {
    fill: Array.isArray(fc) ? figCss(fc) : 'none', 'fill-opacity': figNumber(figP(a, 'FaceAlpha'), 1),
    stroke: ec === 'none' || style === 'none' ? 'none' : figCss(Array.isArray(ec) ? ec : [0, 0, 0]),
    'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width)
  };
  if (t === 'ellipse' || t === 'scribeellipse') figEl('ellipse', { cx: figN(r.x + r.w / 2), cy: figN(r.y + r.h / 2), rx: figN(r.w / 2), ry: figN(r.h / 2), ...shape }, ga);
  else figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(r.h), ...shape }, ga);
  if (t === 'textbox') {
    const halign = figWord(figP(a, 'HorizontalAlignment')) || 'left';
    const valign = figWord(figP(a, 'VerticalAlignment')) || 'top';
    const margin = figNumber(figP(a, 'Margin'), 5);
    figDrawText(ga, figLines(figP(a, 'String')),
      halign === 'center' ? r.x + r.w / 2 : halign === 'right' ? r.x + r.w - margin : r.x + margin,
      valign === 'middle' ? r.y + r.h / 2 : valign === 'bottom' ? r.y + r.h - margin : r.y + margin, {
        size: figNumber(figP(a, 'FontSize'), 10) * R.pt, color: figCss(figColor(figP(a, 'Color')) || [0, 0, 0]),
        family: figFamily(figText(figP(a, 'FontName')) || 'Helvetica'), bold: figWord(figP(a, 'FontWeight')) === 'bold',
        halign, valign, interpreter: figWord(figP(a, 'Interpreter')) || 'tex', pt: R.pt
      });
  }
}

/* ── controls ────────────────────────────────────────────────────────── */

/** Words broken into lines no wider than `width`, as MATLAB wraps a control's text. */
function figWrap(lines, width, size, family) {
  const out = [];
  for (const line of lines) {
    const words = line.split(/(\s+)/);
    let cur = '';
    for (const w of words) {
      const next = cur + w;
      if (cur.trim() && figMeasure(next, size, family) > width) { out.push(cur.trimEnd()); cur = w.trimStart(); }
      else cur = next;
    }
    out.push(cur);
  }
  return out;
}

/** A control of a window, as it looks when the window opens; a panel with what it holds. */
function figControl(R, g, c, box) {
  const t = c.low;
  const P = (n) => figP(c, n);
  const units = figWord(P('Units')) || (t === 'uicontrol' || t === 'uitable' ? 'pixels' : 'normalized');
  const rect = figPlace(figNumbers(P('Position')), units, box, R.model);
  if (!rect || rect.w <= 0 || rect.h <= 0) return;
  const gc = figObjectGroup(R, g, c);
  figMark(R, c, rect);
  const mac = R.model.ppi === 72;
  const fsz = figNumber(P('FontSize'), R.model.hg2 && mac ? 10 : 8);
  const size = (figWord(P('FontUnits')) === 'pixels' ? fsz : fsz * R.pt) || 11;
  const family = figFamily(figText(P('FontName')) || (R.model.hg2 || mac ? 'Helvetica' : 'MS Sans Serif'));
  const bold = figWord(P('FontWeight')) === 'bold';
  const figBg = figColor(figP(R.fig, 'Color'));
  const surface = R.model.hg2 ? [0.94, 0.94, 0.94] : Array.isArray(figBg) ? figBg : [0.83, 0.82, 0.78];
  const bgSaved = figColor(P('BackgroundColor'));
  const fg = figColor(P('ForegroundColor')) || [0, 0, 0];
  const enabled = figWord(P('Enable')) !== 'off';
  const ink = enabled ? figCss(fg) : 'rgb(140,140,140)';
  const lines = figLines(P('String'));
  const r = rect;
  const font = { size, family, bold, pt: R.pt, interpreter: 'none', color: ink };

  if (t === 'uipanel' || t.endsWith('buttongroup')) {
    const bg = Array.isArray(bgSaved) ? bgSaved : surface;
    const border = figWord(P('BorderType')) || 'etchedin';
    const title = figText(P('Title'));
    figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(r.h), fill: figCss(bg) }, gc);
    const top = title ? r.y + size * 0.6 : r.y;
    if (border !== 'none') {
      figEl('rect', { x: figN(r.x + 0.5), y: figN(top + 0.5), width: figN(Math.max(0, r.w - 1)), height: figN(Math.max(0, r.y + r.h - top - 1)),
        fill: 'none', stroke: border === 'line' ? figCss(figColor(P('HighlightColor')) || [0, 0, 0]) : 'rgb(160,160,160)', 'stroke-width': 1 }, gc);
    }
    if (title) {
      const w = figMeasure(title, size, family, bold);
      const tx = r.x + 8;
      figEl('rect', { x: figN(tx - 2), y: figN(r.y), width: figN(w + 4), height: figN(size * 1.2), fill: figCss(bg) }, gc);
      figDrawText(gc, title, tx, r.y, { ...font, color: figCss(figColor(P('ForegroundColor')) || [0, 0, 0]), valign: 'top' });
    }
    const inner = { x: r.x + 2, y: title ? r.y + size * 1.3 : r.y + 2, w: Math.max(1, r.w - 4), h: Math.max(1, r.h - (title ? size * 1.3 : 2) - 2) };
    figContents(R, gc, c, inner);
    return;
  }
  if (t === 'uicontainer' || t === 'uiflowcontainer' || t === 'uigridcontainer') { figContents(R, gc, c, r); return; }
  if (t === 'uitabgroup') {
    const tabs = c.children.filter(k => k.low === 'uitab');
    const chosen = R.model.byHandle.get(figNumber(P('SelectedTab'))) || tabs[0];
    let x = r.x + 2;
    const tabH = size * 1.8;
    for (const tab of tabs) {
      const label = figText(figP(tab, 'Title'));
      const w = figMeasure(label, size, family) + 16;
      figEl('rect', { x: figN(x), y: figN(r.y), width: figN(w), height: figN(tabH), fill: tab === chosen ? 'rgb(250,250,250)' : 'rgb(225,225,225)', stroke: 'rgb(170,170,170)' }, gc);
      figDrawText(gc, label, x + w / 2, r.y + tabH / 2, { ...font, color: 'rgb(0,0,0)', halign: 'center', valign: 'middle' });
      x += w;
    }
    figEl('rect', { x: figN(r.x), y: figN(r.y + tabH), width: figN(r.w), height: figN(Math.max(0, r.h - tabH)), fill: 'rgb(250,250,250)', stroke: 'rgb(170,170,170)' }, gc);
    if (chosen) figContents(R, gc, chosen, { x: r.x + 1, y: r.y + tabH + 1, w: Math.max(1, r.w - 2), h: Math.max(1, r.h - tabH - 2) });
    return;
  }
  if (t === 'uitable') {
    figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(r.h), fill: 'rgb(255,255,255)', stroke: 'rgb(150,150,150)' }, gc);
    const data = P('Data');
    const names = figLines(P('ColumnName'));
    const v = figNumbers(data);
    const [rows, cols] = figDims(data);
    const cell = (i, j) => (data && data.cls === 'cell' ? figText(data.items[i + rows * j]) : v ? figShortNumber(v[i + rows * j]) : '');
    const rowH = size * 1.5;
    const colW = Math.max(40, (r.w - 30) / Math.max(1, cols));
    const clip = figEl('g', { 'clip-path': figClip(R, r) }, gc);
    figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(rowH), fill: 'rgb(240,240,240)' }, clip);
    for (let j = 0; j < cols; j++) figDrawText(clip, names[j] || String(j + 1), r.x + 30 + (j + 0.5) * colW, r.y + rowH / 2, { ...font, color: 'rgb(0,0,0)', halign: 'center', valign: 'middle' });
    for (let i = 0; i < rows && (i + 1) * rowH < r.h; i++) {
      figDrawText(clip, String(i + 1), r.x + 15, r.y + (i + 1.5) * rowH, { ...font, color: 'rgb(90,90,90)', halign: 'center', valign: 'middle' });
      for (let j = 0; j < cols; j++) figDrawText(clip, cell(i, j), r.x + 30 + (j + 1) * colW - 4, r.y + (i + 1.5) * rowH, { ...font, halign: 'right', valign: 'middle' });
    }
    return;
  }
  if (t !== 'uicontrol') { figNotDrawn(R, c); return; }

  const style = figWord(P('Style')) || 'pushbutton';
  const halign = figWord(P('HorizontalAlignment')) || 'center';
  const value = figNumbers(P('Value'));
  const max = figNumber(P('Max'), 1);
  const min = figNumber(P('Min'), 0);
  const on = value && value.length ? value[0] === max : false;
  const ax = (pad) => (halign === 'left' ? r.x + pad : halign === 'right' ? r.x + r.w - pad : r.x + r.w / 2);
  const box3d = (fill, sunk) => figEl('rect', { x: figN(r.x + 0.5), y: figN(r.y + 0.5), width: figN(Math.max(0, r.w - 1)), height: figN(Math.max(0, r.h - 1)),
    rx: sunk ? 0 : 3, fill: figCss(fill), stroke: sunk ? 'rgb(130,130,130)' : 'rgb(150,150,150)', 'stroke-width': 1 }, gc);
  const clipped = () => figEl('g', { 'clip-path': figClip(R, r) }, gc);
  switch (style) {
    case 'text': {
      figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(r.h), fill: figCss(Array.isArray(bgSaved) ? bgSaved : surface) }, gc);
      figDrawText(clipped(), figWrap(lines, r.w - 2, size, family), ax(1), r.y, { ...font, halign, valign: 'top' });
      break;
    }
    case 'edit': {
      box3d(Array.isArray(bgSaved) ? bgSaved : [1, 1, 1], true);
      const multi = max - min > 1;
      const shown = multi ? figWrap(lines, r.w - 6, size, family) : [lines.join(' ')];
      figDrawText(clipped(), shown, ax(3), multi ? r.y + 2 : r.y + r.h / 2, { ...font, halign, valign: multi ? 'top' : 'middle' });
      break;
    }
    case 'checkbox':
    case 'radiobutton': {
      if (Array.isArray(bgSaved)) figEl('rect', { x: figN(r.x), y: figN(r.y), width: figN(r.w), height: figN(r.h), fill: figCss(bgSaved) }, gc);
      const s = Math.min(13, r.h - 2, size * 1.1);
      const cy = r.y + r.h / 2;
      if (style === 'checkbox') {
        figEl('rect', { x: figN(r.x + 2), y: figN(cy - s / 2), width: figN(s), height: figN(s), rx: 2, fill: 'rgb(255,255,255)', stroke: 'rgb(120,120,120)' }, gc);
        if (on) figEl('path', { d: `M${figN(r.x + 2 + s * 0.2)} ${figN(cy)}L${figN(r.x + 2 + s * 0.42)} ${figN(cy + s * 0.25)}L${figN(r.x + 2 + s * 0.82)} ${figN(cy - s * 0.28)}`, fill: 'none', stroke: 'rgb(30,30,30)', 'stroke-width': 1.6 }, gc);
      } else {
        figEl('circle', { cx: figN(r.x + 2 + s / 2), cy: figN(cy), r: figN(s / 2), fill: 'rgb(255,255,255)', stroke: 'rgb(120,120,120)' }, gc);
        if (on) figEl('circle', { cx: figN(r.x + 2 + s / 2), cy: figN(cy), r: figN(s / 4), fill: 'rgb(30,30,30)' }, gc);
      }
      figDrawText(clipped(), lines.join(' '), r.x + s + 6, cy, { ...font, halign: 'left', valign: 'middle' });
      break;
    }
    case 'slider': {
      const across = r.w >= r.h;
      figEl('rect', { x: figN(r.x + 0.5), y: figN(r.y + 0.5), width: figN(Math.max(0, r.w - 1)), height: figN(Math.max(0, r.h - 1)), fill: 'rgb(232,232,232)', stroke: 'rgb(160,160,160)' }, gc);
      const f = max > min && value && value.length ? Math.min(1, Math.max(0, (value[0] - min) / (max - min))) : 0;
      const thumb = Math.min(across ? r.w : r.h, 12);
      const at = across ? r.x + f * (r.w - thumb) : r.y + (1 - f) * (r.h - thumb);
      figEl('rect', across ? { x: figN(at), y: figN(r.y + 1), width: figN(thumb), height: figN(Math.max(0, r.h - 2)) }
        : { x: figN(r.x + 1), y: figN(at), width: figN(Math.max(0, r.w - 2)), height: figN(thumb) }, gc).setAttribute('fill', 'rgb(200,200,200)');
      break;
    }
    case 'listbox': {
      box3d(Array.isArray(bgSaved) ? bgSaved : [1, 1, 1], true);
      const rowH = size * 1.25;
      const first = Math.max(1, Math.round(figNumber(P('ListboxTop'), 1)));
      const chosen = new Set(value ? Array.from(value) : []);
      const g2 = clipped();
      for (let k = first - 1, row = 0; k < lines.length && row * rowH < r.h; k++, row++) {
        const y = r.y + 2 + row * rowH;
        if (chosen.has(k + 1)) figEl('rect', { x: figN(r.x + 1), y: figN(y), width: figN(Math.max(0, r.w - 2)), height: figN(rowH), fill: 'rgb(0,99,177)' }, g2);
        figDrawText(g2, lines[k], r.x + 4, y + rowH / 2, { ...font, color: chosen.has(k + 1) ? 'rgb(255,255,255)' : ink, halign: 'left', valign: 'middle' });
      }
      break;
    }
    case 'popupmenu': {
      box3d(Array.isArray(bgSaved) ? bgSaved : [1, 1, 1], false);
      const k = value && value.length ? Math.round(value[0]) - 1 : 0;
      const g2 = clipped();
      figDrawText(g2, lines[k] ?? lines[0] ?? '', r.x + 5, r.y + r.h / 2, { ...font, halign: 'left', valign: 'middle' });
      const cx = r.x + r.w - 9;
      const cy = r.y + r.h / 2;
      figEl('path', { d: `M${figN(cx - 3.5)} ${figN(cy - 1.5)}L${figN(cx)} ${figN(cy + 2)}L${figN(cx + 3.5)} ${figN(cy - 1.5)}`, fill: 'none', stroke: 'rgb(60,60,60)', 'stroke-width': 1.3 }, gc);
      break;
    }
    case 'frame':
      figEl('rect', { x: figN(r.x + 0.5), y: figN(r.y + 0.5), width: figN(Math.max(0, r.w - 1)), height: figN(Math.max(0, r.h - 1)),
        fill: figCss(Array.isArray(bgSaved) ? bgSaved : surface), stroke: 'rgb(160,160,160)' }, gc);
      break;
    default: {
      // pushbutton, togglebutton and any style this page does not know
      const bg = Array.isArray(bgSaved) ? bgSaved : R.model.hg2 ? [0.98, 0.98, 0.98] : surface;
      box3d(style === 'togglebutton' && on ? bg.map(x => x * 0.82) : bg, false);
      figDrawText(clipped(), figWrap(lines, r.w - 6, size, family), ax(4), r.y + r.h / 2, { ...font, halign, valign: 'middle' });
    }
  }
}

/* ── polar axes ──────────────────────────────────────────────────────── */

/** A polar axes of R2016a and later: its circles and spokes, labels, and the lines in it. */
function figPolarAxes(R, g, ax, box) {
  const pos = figNumbers(figP(ax, 'Position')) || figNumbers(figP(ax, 'InnerPosition')) || FIG_AXES_POSITION;
  const rect = figPlace(pos, figWord(figP(ax, 'Units')) || 'normalized', box, R.model);
  if (!rect) return;
  const gAx = figObjectGroup(R, g, ax, false);
  figMark(R, ax, rect);
  const S = figAxesStyle(R, ax);
  const rl = figNumbers(figP(ax, 'RLim'));
  const rLim = rl && rl.length >= 2 && rl[1] > rl[0] ? [rl[0], rl[1]] : [0, 1];
  const radius = Math.min(rect.w, rect.h) / 2;
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const zero = { right: 0, top: 90, left: 180, bottom: 270 }[figWord(figP(ax, 'ThetaZeroLocation')) || 'right'] || 0;
  const sign = figWord(figP(ax, 'ThetaDir')) === 'clockwise' ? -1 : 1;
  const at = (thetaDeg, r) => {
    const a = (zero + sign * thetaDeg) * Math.PI / 180;
    const f = (r - rLim[0]) / (rLim[1] - rLim[0]) * radius;
    return [cx + f * Math.cos(a), cy - f * Math.sin(a)];
  };
  figEl('circle', { cx: figN(cx), cy: figN(cy), r: figN(radius), fill: figCss(Array.isArray(S.color) ? S.color : [1, 1, 1]) }, gAx);
  const gridColor = figCss(S.gridColor || [0.15, 0.15, 0.15]);
  const rTicks = Array.from(figNumbers(figP(ax, 'RTick')) || figLinearTicks(rLim[0], rLim[1], 5));
  const tTicks = Array.from(figNumbers(figP(ax, 'ThetaTick')) || [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]);
  let d = '';
  for (const r of rTicks) {
    if (!(r > rLim[0] && r < rLim[1])) continue;
    const f = (r - rLim[0]) / (rLim[1] - rLim[0]) * radius;
    d += `M${figN(cx + f)} ${figN(cy)}a${figN(f)} ${figN(f)} 0 1 0 ${figN(-2 * f)} 0a${figN(f)} ${figN(f)} 0 1 0 ${figN(2 * f)} 0`;
  }
  for (const th of tTicks) { const p = at(th, rLim[1]); d += `M${figN(cx)} ${figN(cy)}L${figN(p[0])} ${figN(p[1])}`; }
  figEl('path', { d, fill: 'none', stroke: gridColor, 'stroke-opacity': S.gridAlpha, 'stroke-width': figN(S.lineWidth) }, gAx);
  figEl('circle', { cx: figN(cx), cy: figN(cy), r: figN(radius), fill: 'none', stroke: figCss(S.xColor), 'stroke-width': figN(S.lineWidth) }, gAx);
  const font = { size: S.fontPx, family: S.family, pt: R.pt, color: figCss(S.xColor), interpreter: 'tex' };
  const tLabels = figLines(figP(ax, 'ThetaTickLabel'));
  tTicks.forEach((th, k) => {
    if (k >= tTicks.length - 1 && tTicks.length > 1 && Math.abs(((th - tTicks[0]) % 360)) < 1e-9) return;
    const p = at(th, rLim[1] + (rLim[1] - rLim[0]) * 0.08);
    figDrawText(gAx, tLabels.length ? tLabels[k % tLabels.length] : `${figShortNumber(th)}°`, p[0], p[1], { ...font, halign: 'center', valign: 'middle' });
  });
  const rLabels = figLines(figP(ax, 'RTickLabel'));
  const rAxis = figNumber(figP(ax, 'RAxisLocation'), 80);
  rTicks.forEach((r, k) => {
    const p = at(rAxis, r);
    figDrawText(gAx, rLabels.length ? rLabels[k % rLabels.length] : figShortNumber(r), p[0] + 2, p[1], { ...font, halign: 'left', valign: 'bottom' });
  });
  const clipCircle = `${R.id}-clip${++R.clips}`;
  figEl('circle', { cx: figN(cx), cy: figN(cy), r: figN(radius) }, figEl('clipPath', { id: clipCircle }, R.defs));
  const data = figEl('g', { 'clip-path': `url(#${clipCircle})` }, gAx);
  for (const c of ax.children) {
    if (!figVisible(c) || c.role) continue;
    if (c.low !== 'line' && c.low !== 'graph2d.lineseries') { if (c.low !== 'text') figNotDrawn(R, c); continue; }
    const th = figNumbers(figP(c, 'ThetaData')) || figNumbers(figP(c, 'XData'));
    const rr = figNumbers(figP(c, 'RData')) || figNumbers(figP(c, 'YData'));
    if (!th || !rr) continue;
    const n = Math.min(th.length, rr.length);
    const px = new Float64Array(n);
    const py = new Float64Array(n);
    for (let k = 0; k < n; k++) { const p = at(th[k] * 180 / Math.PI, rr[k]); px[k] = p[0]; py[k] = p[1]; }
    const gl = figObjectGroup(R, data, c);
    const width = figWidth(R, c);
    const style = figText(figP(c, 'LineStyle')).trim() || '-';
    const css = figCss(figColor(figP(c, 'Color')) || [0, 0, 0]);
    if (style !== 'none') figEl('path', { d: figPolyline(px, py), fill: 'none', stroke: css, 'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width) }, gl);
    const marker = figMarkerName(figP(c, 'Marker'));
    if (marker !== 'none') figMarkers(gl, Array.from(px, (x, k) => [x, py[k]]).filter(p => Number.isFinite(p[0] + p[1])), marker, figNumber(figP(c, 'MarkerSize'), 6) * R.pt, css, null, width);
  }
}

/* ── three dimensions ────────────────────────────────────────────────── */

/**
 * An axes seen from its view: the plot box turned to its azimuth and
 * elevation and fitted into its Position, the grid on the walls at its
 * back, what it holds painted from the back forwards, the axes along the
 * box's lower front edges.
 */
function figAxes3(R, g, ax, rect, view) {
  const S = figAxesStyle(R, ax);
  const P = (n) => figP(ax, n);
  const logs = ['X', 'Y', 'Z'].map(a => figWord(P(`${a}Scale`)) === 'log');
  let lims = null;
  let pbar = figNumbers(P('PlotBoxAspectRatio'));
  pbar = pbar && pbar.length >= 3 && [0, 1, 2].every(k => pbar[k] > 0) ? Array.from(pbar.subarray(0, 3)) : [1, 1, 1];
  const top = Math.max(...pbar);
  const f = (k, v) => {
    const lo = logs[k] ? Math.log10(lims[k][0]) : lims[k][0];
    const hi = logs[k] ? Math.log10(lims[k][1]) : lims[k][1];
    const x = logs[k] ? (v > 0 ? Math.log10(v) : NaN) : v;
    let u = (x - lo) / (hi - lo);
    if (figWord(P(`${'XYZ'[k]}Dir`)) === 'reverse') u = 1 - u;
    return (u - 0.5) * pbar[k] / top;
  };
  const az = view[0] * Math.PI / 180;
  const el = view[1] * Math.PI / 180;
  const right = [Math.cos(az), Math.sin(az), 0];
  const up = [-Math.sin(el) * Math.sin(az), Math.sin(el) * Math.cos(az), Math.cos(el)];
  const toward = [Math.sin(az) * Math.cos(el), -Math.cos(az) * Math.cos(el), Math.sin(el)];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const corners = [];
  for (const i of [-1, 1]) for (const j of [-1, 1]) for (const k of [-1, 1]) corners.push([i * pbar[0] / top / 2, j * pbar[1] / top / 2, k * pbar[2] / top / 2]);
  const sx = corners.map(c => dot(c, right));
  const sy = corners.map(c => dot(c, up));
  // MATLAB stretches the box to fill the axes' Position, unless an aspect
  // ratio was set (axis equal, vis3d), which keeps it as it is.
  const keep = ['DataAspectRatioMode', 'PlotBoxAspectRatioMode', 'CameraViewAngleMode'].some(n => figWord(P(n)) === 'manual');
  let kx = rect.w / (Math.max(...sx) - Math.min(...sx) || 1);
  let ky = rect.h / (Math.max(...sy) - Math.min(...sy) || 1);
  if (keep) kx = ky = Math.min(kx, ky);
  const cx = rect.x + rect.w / 2 - kx * (Math.max(...sx) + Math.min(...sx)) / 2;
  const cy = rect.y + rect.h / 2 + ky * (Math.max(...sy) + Math.min(...sy)) / 2;
  const project = (u) => [cx + kx * dot(u, right), cy - ky * dot(u, up), dot(u, toward)];
  // Each axis drawn as long as it is on the screen: its limits rounded and its
  // ticks spaced as a 2-D axis of that length would have them.
  const drawn = [0, 1, 2].map(k => {
    const a = [0, 0, 0]; const b = [0, 0, 0];
    a[k] = -pbar[k] / top / 2; b[k] = pbar[k] / top / 2;
    const pa = project(a); const pb = project(b);
    return Math.hypot(pb[0] - pa[0], pb[1] - pa[1]) * (k === 0 ? 1.2 : 0.6);
  });
  lims = [0, 1, 2].map(k => figLimits(R, ax, k, logs[k], drawn[k]));
  const data = (x, y, z) => project([f(0, x), f(1, y), f(2, z)]);
  const half = [0, 1, 2].map(k => pbar[k] / top / 2);
  const T = { ax, S, rect, data, project, lims, logs, view, three: true };

  // the walls at the back: of each pair, the one facing away
  const back = [0, 1, 2].map(k => (toward[k] > 0 ? -1 : 1));
  const wall = (k) => {
    const pts = [];
    const [a, b] = [0, 1, 2].filter(i => i !== k);
    for (const [s, t] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
      const u = [0, 0, 0];
      u[k] = back[k] * half[k]; u[a] = s * half[a]; u[b] = t * half[b];
      pts.push(project(u));
    }
    return pts;
  };
  if (S.visible && S.color !== 'none') {
    for (const k of [0, 1, 2]) {
      const pts = wall(k);
      figEl('path', { d: `M${pts.map(p => `${figN(p[0])} ${figN(p[1])}`).join('L')}Z`, fill: figCss(Array.isArray(S.color) ? S.color : [1, 1, 1]) }, g);
    }
  }
  const ticks = [0, 1, 2].map(k => figTicks(R, ax, k, lims[k], logs[k], drawn[k]));
  if (S.visible) {
    let d = '';
    ['XGrid', 'YGrid', 'ZGrid'].forEach((name, k) => {
      if (!figOn(P(name), false)) return;
      for (const v of ticks[k].ticks) {
        const fv = f(k, v);
        if (!Number.isFinite(fv)) continue;
        for (const w of [0, 1, 2]) {
          if (w === k) continue;
          // a line across the back wall w, at this tick
          const other = [0, 1, 2].find(i => i !== k && i !== w);
          const a = [0, 0, 0]; const b = [0, 0, 0];
          a[k] = b[k] = fv; a[w] = b[w] = back[w] * half[w];
          a[other] = -half[other]; b[other] = half[other];
          const pa = project(a); const pb = project(b);
          d += `M${figN(pa[0])} ${figN(pa[1])}L${figN(pb[0])} ${figN(pb[1])}`;
        }
      }
    });
    if (d) figEl('path', { d, fill: 'none', stroke: figCss(S.gridColor || S.xColor), 'stroke-opacity': S.gridAlpha < 1 ? S.gridAlpha : null,
      'stroke-width': figN(S.lineWidth), 'stroke-dasharray': figDash(S.gridStyle, S.lineWidth) }, g);
  }

  // what it holds, painted from the back
  const items = [];
  const gData = figEl('g', { 'clip-path': figClip(R, { x: rect.x - rect.w * 0.2, y: rect.y - rect.h * 0.2, w: rect.w * 1.4, h: rect.h * 1.4 }) }, g);
  const free = figEl('g', {}, g);
  const walk = (o, into) => {
    for (const c of o.children) {
      if (c.role || !figVisible(c)) continue;
      const t = c.low;
      if (t === 'surface' || t === 'graph3d.surfaceplot') figSurface3(R, c, T, items, into);
      else if (t === 'line' || t === 'graph2d.lineseries') figLine3(R, c, T, figObjectGroup(R, into, c));
      else if (t === 'patch') figPatch3(R, c, T, items, into);
      else if (t === 'text') figText3(R, c, T, free);
      else if (c.children.length && (FIG_GROUPS.test(t) || figSeriesKind(t))) walk(c, figObjectGroup(R, into, c, false));
      else if (t !== 'light') figNotDrawn(R, c);
    }
  };
  const gLines = figEl('g', {}, gData);
  walk(ax, gLines);
  if (items.length) {
    items.sort((a, b) => a.depth - b.depth);
    const r = figRaster(rect);
    if (r) {
      for (const it of items) it.paint(r.ctx);
      gData.insertBefore(figEl('g', {}), gLines);
      r.put(gData.firstChild);
    }
  }

  if (!S.visible) { figAxesLabels3(R, g, ax, T, null); return; }
  // the axes along the box's lower front edges, z along its left
  const front = [0, 1, 2].map(k => (toward[k] > 0 ? 1 : -1));
  const floor = toward[2] >= 0 ? -1 : 1;
  const edges = [];
  for (const k of [0, 1]) {
    const o = 1 - k;
    const a = [0, 0, 0]; const b = [0, 0, 0];
    a[o] = b[o] = front[o] * half[o]; a[2] = b[2] = floor * half[2];
    a[k] = -half[k]; b[k] = half[k];
    edges.push({ k, a, b });
  }
  let best = null;
  for (const i of [-1, 1]) for (const j of [-1, 1]) {
    const p = project([i * half[0], j * half[1], 0]);
    if (!best || p[0] < best.x - 1e-9) best = { x: p[0], i, j };
  }
  edges.push({ k: 2, a: [best.i * half[0], best.j * half[1], -half[2]], b: [best.i * half[0], best.j * half[1], half[2]] });
  const centre = project([0, 0, 0]);
  const colors = [S.xColor, S.yColor, S.zColor];
  const reach = [0, 0, 0];
  if (S.box) {
    let d = '';
    for (const c1 of corners) for (const c2 of corners) {
      const diff = [0, 1, 2].filter(q => c1[q] !== c2[q]);
      if (diff.length !== 1 || c1 > c2) continue;
      const p1 = project(c1); const p2 = project(c2);
      d += `M${figN(p1[0])} ${figN(p1[1])}L${figN(p2[0])} ${figN(p2[1])}`;
    }
    figEl('path', { d, fill: 'none', stroke: figCss(S.xColor), 'stroke-width': figN(S.lineWidth), 'stroke-opacity': 0.6 }, g);
  }
  for (const { k, a, b } of edges) {
    const pa = project(a); const pb = project(b);
    figEl('path', { d: `M${figN(pa[0])} ${figN(pa[1])}L${figN(pb[0])} ${figN(pb[1])}`, stroke: figCss(colors[k]), 'stroke-width': figN(S.lineWidth) }, g);
    const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2];
    let out = k === 2 ? [-1, 0] : [mid[0] - centre[0], mid[1] - centre[1]];
    const len = Math.hypot(out[0], out[1]) || 1;
    out = [out[0] / len, out[1] / len];
    const tl = S.tickLength * Math.max(rect.w, rect.h);
    let d = '';
    let widest = 0;
    ticks[k].ticks.forEach((v, n) => {
      const u = [...a];
      u[k] = f(k, v);
      if (!Number.isFinite(u[k])) return;
      const p = project(u);
      d += `M${figN(p[0])} ${figN(p[1])}l${figN(-out[0] * tl)} ${figN(-out[1] * tl)}`;
      const label = ticks[k].labels[n];
      if (!label) return;
      const gap = S.fontPx * 0.5;
      const m = figDrawText(g, label, p[0] + out[0] * gap, p[1] + out[1] * gap, {
        size: S.fontPx, family: S.family, pt: R.pt, color: figCss(colors[k]), interpreter: ticks[k].interpreter,
        halign: out[0] > 0.3 ? 'left' : out[0] < -0.3 ? 'right' : 'center', valign: out[1] > 0.3 ? 'top' : out[1] < -0.3 ? 'bottom' : 'middle'
      });
      widest = Math.max(widest, Math.abs(out[0]) * m.width + Math.abs(out[1]) * m.height);
    });
    if (d) figEl('path', { d, stroke: figCss(colors[k]), 'stroke-width': figN(S.lineWidth) }, g);
    reach[k] = { mid, out, far: S.fontPx * 0.5 + widest };
  }
  figAxesLabels3(R, g, ax, T, reach);
}

/** A 3-D axes' title over the box, and each label beyond its axis' tick labels. */
function figAxesLabels3(R, g, ax, T, reach) {
  const { S, rect } = T;
  for (const c of ax.children) {
    if (!c.role || !figVisible(c)) continue;
    const lines = figLines(figP(c, 'String'));
    if (!lines.length || lines.every(s => !s.trim())) continue;
    const title = c.role === 'Title';
    if (!title && !reach) continue;
    const savedSize = figNumber(figP(c, 'FontSize'));
    const size = Number.isFinite(savedSize) ? savedSize * R.pt : S.fontPx * (title ? S.titleScale : S.labelScale);
    const weight = figWord(figP(c, 'FontWeight'));
    const opts = {
      size, pt: R.pt, family: figFamily(figText(figP(c, 'FontName')) || 'Helvetica'),
      bold: weight ? weight === 'bold' : title && S.titleBold,
      color: figCss(figColor(figP(c, 'Color')) || (title ? [0, 0, 0] : S.xColor)), interpreter: figWord(figP(c, 'Interpreter')) || 'tex', halign: 'center'
    };
    const gl = figObjectGroup(R, g, c);
    if (title) { figDrawText(gl, lines, rect.x + rect.w / 2, rect.y, { ...opts, valign: 'bottom' }); continue; }
    const k = { XLabel: 0, YLabel: 1, ZLabel: 2 }[c.role];
    const r = reach[k];
    if (!r) continue;
    const at = [r.mid[0] + r.out[0] * (r.far + size * 0.6), r.mid[1] + r.out[1] * (r.far + size * 0.6)];
    figDrawText(gl, lines, at[0], at[1], { ...opts, valign: k === 2 ? 'bottom' : 'middle', rotation: k === 2 ? 90 : 0 });
  }
}

function figLine3(R, o, T, g) {
  const xs = figNumbers(figP(o, 'XData'));
  const ys = figNumbers(figP(o, 'YData'));
  const zs = figNumbers(figP(o, 'ZData'));
  if (!ys) return;
  const n = ys.length;
  const px = new Float64Array(n);
  const py = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    const p = T.data(xs && xs.length === n ? xs[k] : k + 1, ys[k], zs && zs.length === n ? zs[k] : 0);
    px[k] = p[0]; py[k] = p[1];
  }
  const css = figCss(figColor(figP(o, 'Color')) || [0, 0, 0]);
  const width = figWidth(R, o);
  const style = figText(figP(o, 'LineStyle')).trim() || '-';
  if (style !== 'none') figEl('path', { d: figPolyline(px, py), fill: 'none', stroke: css, 'stroke-width': figN(width), 'stroke-dasharray': figDash(style, width), 'stroke-linejoin': 'round' }, g);
  const marker = figMarkerName(figP(o, 'Marker'));
  if (marker !== 'none') {
    const mf = figColor(figP(o, 'MarkerFaceColor'));
    figMarkers(g, Array.from(px, (x, k) => [x, py[k]]).filter(p => Number.isFinite(p[0] + p[1])), marker, figNumber(figP(o, 'MarkerSize'), 6) * R.pt, css, Array.isArray(mf) ? figCss(mf) : null, width);
  }
}

function figText3(R, o, T, g) {
  const pos = figNumbers(figP(o, 'Position'));
  if (!pos || pos.length < 2 || (figWord(figP(o, 'Units')) || 'data') !== 'data') return;
  const p = T.data(pos[0], pos[1], pos[2] || 0);
  if (!Number.isFinite(p[0] + p[1])) return;
  figDrawText(figObjectGroup(R, g, o), figLines(figP(o, 'String')), p[0], p[1], {
    size: figNumber(figP(o, 'FontSize'), 10) * R.pt, pt: R.pt, color: figCss(figColor(figP(o, 'Color')) || [0, 0, 0]),
    halign: figWord(figP(o, 'HorizontalAlignment')) || 'left', valign: figWord(figP(o, 'VerticalAlignment')) || 'middle',
    rotation: figNumber(figP(o, 'Rotation'), 0), interpreter: figWord(figP(o, 'Interpreter')) || 'tex'
  });
}

/**
 * Where an object painted with others into one picture lies: an outline to
 * point at and click, which draws nothing, and the frame when it is the one
 * selected.
 */
function figHitArea(R, g, o, pts) {
  const ok = pts.filter(p => p && Number.isFinite(p[0] + p[1]));
  if (ok.length < 3) return;
  const area = figObjectGroup(R, g, o, false);
  figEl('path', { d: `M${ok.map(p => `${figN(p[0])} ${figN(p[1])}`).join('L')}Z`, fill: 'transparent', stroke: 'none' }, area);
  const xs = ok.map(p => p[0]);
  const ys = ok.map(p => p[1]);
  const [x0, x1] = figRange(xs);
  const [y0, y1] = figRange(ys);
  figMark(R, o, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
}

/** A surface's faces, each to be painted at its depth. */
function figSurface3(R, o, T, items, g) {
  const grid = figGrid(o);
  if (!grid || grid.m < 2 || grid.n < 2) return;
  const { m, n, z, xAt, yAt } = grid;
  const fc = figP(o, 'FaceColor') !== undefined ? figColor(figP(o, 'FaceColor')) : 'flat';
  const ec = figP(o, 'EdgeColor') !== undefined ? figColor(figP(o, 'EdgeColor')) : [0, 0, 0];
  const colors = figNodeColors(R, o, T, grid);
  // A surface of more faces than a picture of it shows is painted every so many nodes.
  const step = Math.max(1, Math.ceil(Math.sqrt(m * n / 250000)));
  const P = new Array(m * n);
  for (let i = 0; i < m; i++) for (let j = 0; j < n; j++) P[i + m * j] = T.data(xAt(i, j), yAt(i, j), z[i + m * j]);
  const ring = [];
  for (let j = 0; j < n; j++) ring.push(P[m * j]);
  for (let i = 1; i < m; i++) ring.push(P[i + m * (n - 1)]);
  for (let j = n - 2; j >= 0; j--) ring.push(P[m - 1 + m * j]);
  for (let i = m - 2; i > 0; i--) ring.push(P[i]);
  figHitArea(R, g, o, ring);
  const faded = R.focus && !R.focus.has(o);
  const stroke = Array.isArray(ec) ? figRgb(ec) : ec === 'none' || ec === null ? null : 'rgb(0,0,0)';
  const fa = figNumber(figP(o, 'FaceAlpha'), 1);
  for (let i = 0; i < m - 1; i += step) {
    for (let j = 0; j < n - 1; j += step) {
      const i2 = Math.min(i + step, m - 1);
      const j2 = Math.min(j + step, n - 1);
      const q = [P[i + m * j], P[i2 + m * j], P[i2 + m * j2], P[i + m * j2]];
      if (q.some(p => !Number.isFinite(p[0] + p[1] + p[2]))) continue;
      let c = null;
      if (Array.isArray(fc)) c = fc;
      else if (fc === 'flat') c = colors[i + m * j];
      else if (fc === 'interp') {
        const four = [colors[i + m * j], colors[i2 + m * j], colors[i2 + m * j2], colors[i + m * j2]];
        if (four.every(Boolean)) c = [0, 1, 2].map(k => (four[0][k] + four[1][k] + four[2][k] + four[3][k]) / 4);
      }
      const fill = c ? figRgb(c) : null;
      if (!fill && !stroke) continue;
      items.push({
        depth: (q[0][2] + q[1][2] + q[2][2] + q[3][2]) / 4,
        paint: (ctx) => {
          ctx.globalAlpha = (faded ? 0.2 : 1) * (fill && fa < 1 ? fa : 1);
          ctx.beginPath();
          ctx.moveTo(q[0][0], q[0][1]);
          for (let k = 1; k < 4; k++) ctx.lineTo(q[k][0], q[k][1]);
          ctx.closePath();
          if (fill) { ctx.fillStyle = fill; ctx.fill(); }
          if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 0.5 * R.pt; ctx.stroke(); }
          else if (fill) { ctx.strokeStyle = fill; ctx.lineWidth = 0.5; ctx.stroke(); }
        }
      });
    }
  }
}

/** A patch's faces in three dimensions, each to be painted at its depth. */
function figPatch3(R, o, T, items, g) {
  const V = figP(o, 'Vertices');
  const v = figNumbers(V);
  const [m, cols] = figDims(V);
  const F = figP(o, 'Faces');
  const fv = figNumbers(F);
  const [nf, nk] = figDims(F);
  if (!v || !m || !fv || !nf) return;
  const P = [];
  for (let k = 0; k < m; k++) P.push(T.data(v[k], v[k + m], cols >= 3 ? v[k + 2 * m] : 0));
  const xr = figRange(P.map(p => p[0]));
  const yr = figRange(P.map(p => p[1]));
  if (xr && yr) figHitArea(R, g, o, [[xr[0], yr[0]], [xr[1], yr[0]], [xr[1], yr[1]], [xr[0], yr[1]]]);
  const fc = figP(o, 'FaceColor') !== undefined ? figColor(figP(o, 'FaceColor')) : [0, 0, 0];
  const ec = figP(o, 'EdgeColor') !== undefined ? figColor(figP(o, 'EdgeColor')) : [0, 0, 0];
  const per = figVertexColors(R, o, { ...T, clim: null, cmap: null }, 'FaceVertexCData');
  const faded = R.focus && !R.focus.has(o);
  for (let f = 0; f < nf; f++) {
    const face = [];
    for (let j = 0; j < nk; j++) { const idx = fv[f + nf * j]; if (!Number.isFinite(idx)) break; if (P[idx - 1]) face.push(P[idx - 1]); }
    if (face.length < 2 || face.some(p => !Number.isFinite(p[0] + p[1] + p[2]))) continue;
    const own = per ? (per.length === nf ? per[f] : per[0]) : null;
    const fill = Array.isArray(fc) ? figRgb(fc) : (fc === 'flat' || fc === 'interp') && own ? figRgb(own) : null;
    const stroke = Array.isArray(ec) ? figRgb(ec) : (ec === 'flat' || ec === 'interp') && own ? figRgb(own) : null;
    items.push({
      depth: face.reduce((s, p) => s + p[2], 0) / face.length,
      paint: (ctx) => {
        ctx.globalAlpha = faded ? 0.2 : figNumber(figP(o, 'FaceAlpha'), 1);
        ctx.beginPath();
        ctx.moveTo(face[0][0], face[0][1]);
        for (let k = 1; k < face.length; k++) ctx.lineTo(face[k][0], face[k][1]);
        ctx.closePath();
        if (fill) { ctx.fillStyle = fill; ctx.fill(); }
        if (stroke) { ctx.globalAlpha = faded ? 0.2 : 1; ctx.strokeStyle = stroke; ctx.lineWidth = figWidth(R, o); ctx.stroke(); }
      }
    });
  }
}

/* ── the figure in the information panel ─────────────────────────────── */

/** What MATLAB's window says over a figure: Figure 1: its Name. */
function figCaption(fig) {
  const name = figText(figP(fig, 'Name')).trim();
  const numbered = figOn(figP(fig, 'NumberTitle'), true) && Number.isInteger(fig.handle) && fig.handle > 0;
  if (numbered) return name ? `Figure ${fig.handle}: ${name}` : `Figure ${fig.handle}`;
  return name || 'Figure';
}

/** A drawing made again without the frame round the object selected, as a file to save. */
function figStandalone(model, fig) {
  const { svg } = figRender(model, fig, null);
  svg.removeAttribute('class');
  return new XMLSerializer().serializeToString(svg);
}

function figSave(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The name a figure is saved under: its file's, and its number among several. */
function figSaveName(fileKey, k, count, ext) {
  const base = String(fileKey).replace(/\.[^/.]+$/, '').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_') || 'figure';
  return `${base}${count > 1 ? `-${k + 1}` : ''}.${ext}`;
}

/** The figure as a PNG at twice its size: the SVG drawn into a canvas. */
async function figSavePng(model, fig, name) {
  const { width, height } = figRender(model, fig, null);
  const text = figStandalone(model, fig);
  const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml' }));
  try {
    const img = new Image();
    await new Promise((resolve, reject) => { img.onload = resolve; img.onerror = () => reject(new Error('the drawing could not be made a picture')); img.src = url; });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(width * 2);
    canvas.height = Math.round(height * 2);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!blob) throw new Error('the picture could not be made');
    figSave(blob, name);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Select an object in the tree: the groups above it opened, as they would be
 * by hand, and the object chosen as a click on it chooses it.
 */
async function figRevealInTree(fileKey, path) {
  const tree = document.getElementById('tree');
  if (!tree || !path) return;
  const parts = path.split('/').filter(Boolean);
  const open = async (p) => {
    const row = findTreeItem(p, { fileKey, extra: '.group', root: tree, allowMissingFile: true });
    if (!row) return false;
    const kids = row.nextElementSibling;
    if (kids && kids.classList.contains('tree-group-children') && !kids.classList.contains('expanded')) {
      if (kids.getAttribute('data-lazy') === 'true' && kids.getAttribute('data-loaded') !== 'true') await loadGroupChildren(row, p);
      kids.classList.add('expanded');
      const toggle = row.querySelector('.tree-toggle');
      if (toggle) toggle.classList.remove('collapsed');
    }
    return true;
  };
  if (!(await open('/'))) return;
  let p = '';
  for (let k = 0; k < parts.length - 1; k++) {
    p += `/${parts[k]}`;
    if (!(await open(p))) return;
  }
  const row = findTreeItem(path, { fileKey, extra: '.group', root: tree, allowMissingFile: true });
  if (!row) return;
  row.scrollIntoView({ block: 'nearest' });
  toggleGroup({ stopPropagation() {}, target: row, ctrlKey: false, metaKey: false }, row);
}

/**
 * The figure, or figures, a selected path draws in one file -- with the
 * object it is set apart -- as the block the information panel shows: a
 * caption, buttons to save it, the drawing, and what it leaves out. Null
 * when the path is no figure and no object of one.
 *
 * @param {string} fileKey
 * @param {string} path
 * @returns {HTMLElement|null}
 */
function figShowFor(fileKey, path) {
  const model = figModelOf(fileKey);
  const target = figTarget(model, path);
  if (!target) return null;
  const wrap = document.createElement('div');
  wrap.className = 'fig-view';
  const note = (text) => {
    const p = document.createElement('p');
    p.className = 'fig-note';
    p.textContent = text;
    wrap.appendChild(p);
  };
  if (!target.figures.length) {
    note('This figure is kept only in the form MATLAB uses from R2014b (hgM_070000), as savefig\'s compact option saves it, which this page does not draw.');
    return wrap;
  }
  target.figures.forEach((fig, k) => {
    const block = document.createElement('div');
    block.className = 'fig-block';
    const head = document.createElement('div');
    head.className = 'fig-head';
    const title = document.createElement('span');
    title.className = 'fig-title';
    title.textContent = figCaption(fig);
    head.appendChild(title);
    let drawn;
    try {
      drawn = figRender(model, fig, target.highlight);
    } catch (err) {
      kvotWarn('The figure could not be drawn:', err);
      const p = document.createElement('p');
      p.className = 'fig-note';
      p.textContent = `The figure could not be drawn: ${err && err.message ? err.message : err}`;
      block.appendChild(head);
      block.appendChild(p);
      wrap.appendChild(block);
      return;
    }
    const size = document.createElement('span');
    size.className = 'fig-size';
    size.textContent = `${Math.round(drawn.width)} × ${Math.round(drawn.height)} px`;
    head.appendChild(size);
    const buttons = document.createElement('span');
    buttons.className = 'fig-buttons';
    const button = (label, titleText, action) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'info-btn-csv';
      b.textContent = label;
      b.title = titleText;
      b.addEventListener('click', (ev) => {
        ev.stopPropagation();
        Promise.resolve().then(action).catch(err => reportFailure('figSave', err, { userMessage: `${titleText} failed.` }));
      });
      buttons.appendChild(b);
    };
    const count = target.figures.length;
    button('⬇ SVG', 'Save the figure as an SVG drawing', () => figSave(new Blob([figStandalone(model, fig)], { type: 'image/svg+xml' }), figSaveName(fileKey, k, count, 'svg')));
    button('⬇ PNG', 'Save the figure as a PNG picture, at twice its size', () => figSavePng(model, fig, figSaveName(fileKey, k, count, 'png')));
    head.appendChild(buttons);
    block.appendChild(head);
    const canvas = document.createElement('div');
    canvas.className = 'fig-canvas';
    drawn.svg.setAttribute('class', 'fig-svg');
    drawn.svg.setAttribute('aria-label', figCaption(fig));
    // as wide as the panel, but no more than half again its own size, nor taller than most of the window
    drawn.svg.style.aspectRatio = `${drawn.width} / ${drawn.height}`;
    drawn.svg.style.maxWidth = `min(${Math.round(drawn.width * 1.5)}px, calc(80vh * ${(drawn.width / drawn.height).toFixed(4)}))`;
    canvas.appendChild(drawn.svg);
    block.appendChild(canvas);
    if (drawn.notDrawn.size) {
      const list = [...drawn.notDrawn].map(([t, n]) => (n > 1 ? `${t} (${n})` : t)).join(', ');
      const p = document.createElement('p');
      p.className = 'fig-note';
      p.textContent = `Not drawn here: ${list}.`;
      block.appendChild(p);
    }
    if (!fig.children.length && model.newForm) {
      const p = document.createElement('p');
      p.className = 'fig-note';
      p.textContent = 'The objects of this figure are kept only in the form MATLAB uses from R2014b (hgM_070000), which this page does not draw: a tiled layout, a heatmap or axes of dates are kept so.';
      block.appendChild(p);
    }
    wrap.appendChild(block);
  });
  // An object clicked in the drawing is the one selected in the tree.
  wrap.addEventListener('click', (ev) => {
    const hit = ev.target.closest && ev.target.closest('[data-fig-path]');
    const at = hit && hit.getAttribute('data-fig-path');
    if (!at || at === path || !model.byPath.has(at)) return;
    figRevealInTree(fileKey, at).catch(err => kvotWarn('The object could not be selected in the tree:', err));
  });
  return wrap;
}
