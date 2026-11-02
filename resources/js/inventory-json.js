/* ==========================================================================
   CANISTER_INVENTORY.HTML: READING A CANISTER INVENTORY (JSON)

   The inventory comes as one JSON object with a member per canister:

     { "10": { "packing_date": "2038-03-07",
               "fuel_elements": {
                 "AI31": { "reactor": "Ringhals 2", "reactor_type": "PWR",
                           "fuel_type": "15*15 AFA 3GAA",
                           "fuel":                { "ac227": 7.0e-10, ... },
                           "crud":                { ... },
                           "structural_material": { ... },
                           "decay_heat_W": 94.3, "declared_heat_W": 93.1 },
                 ... },
               "decay_heat_W": 1029.3, "declared_heat_W": 1000.7 },
       ... }

   Nothing here is tied to those names. A canister's elements are the member
   that holds objects of objects (or an array of them); an element's parts
   are its members that map nuclide names to numbers; its other numbers and
   texts are its properties, and a canister's likewise; the first text of a
   canister that reads as a date (YYYY-MM-DD) is when it was packed. An
   inventory with no elements, a nuclide map straight on each canister, is
   read as one element per canister. An array of canisters does as well as
   an object of them, and an element array as an element object.

   Such a file is large: 47,278 elements of three parts of 56 nuclides make
   238 MB. Read whole into one string and parsed at once it would need the
   string, the parse and every number as an object of its own, and a file a
   few times larger cannot be one string at all. So the file is read a slice
   at a time, the bytes of each canister are found by counting brackets,
   only that canister is parsed, and its numbers go straight into one array
   of all amounts (element x part x nuclide). The parsed canister is then
   dropped.

   Python's json module writes NaN and Infinity, which JSON has no words
   for. A canister that fails to parse is tried again with those words read
   as missing values, and the file's notes say so.

   One global: KVOT_INV_JSON (module.exports under Node). Runs in a worker
   (inventory-worker.js) and, where no worker can start, on the page.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.KVOT_INV_JSON = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ---------------------------------------------------------------------
     Nuclide names
     --------------------------------------------------------------------- */

  const SYMBOLS = ('n H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr '
    + 'Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re '
    + 'Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh '
    + 'Fl Mc Lv Ts Og').split(' ');
  const Z_OF = new Map(SYMBOLS.map((s, z) => [s.toLowerCase(), z]));

  /**
   * A nuclide from the way files name it: cs137, Cs-137, Cs137, 137Cs,
   * am242m, Am-242m1, Pa-234m. Isomers are m and n, as ICRP Publication 107
   * names them (m1 is m, m2 is n).
   *
   * @param {string} key
   * @returns {{key: string, z: number, a: number, iso: string, name: string}|null}
   */
  function nuclideOf(key) {
    const s = String(key ?? '').trim();
    let sym, a, iso;
    let m = /^([A-Za-z]{1,2})[-_ ]?(\d{1,3})[-_ ]?(m\d?|n)?$/i.exec(s);
    if (m) [, sym, a, iso] = m;
    else {
      m = /^(\d{1,3})[-_ ]?(m\d?|n)?[-_ ]?([A-Za-z]{1,2})$/i.exec(s);
      if (!m) return null;
      [, a, iso, sym] = m;
    }
    const z = Z_OF.get(sym.toLowerCase());
    a = Number(a);
    if (z === undefined || z === 0 || !(a >= z) || a > 300) return null;
    iso = (iso || '').toLowerCase();
    iso = iso === 'm1' ? 'm' : iso === 'm2' ? 'n' : iso.replace(/\d+$/, '');
    return { key: s, z, a, iso, name: `${SYMBOLS[z]}-${a}${iso}` };
  }

  /* ---------------------------------------------------------------------
     Finding each member of the top level
     --------------------------------------------------------------------- */

  const WS = new Uint8Array(256);
  for (const c of [0x20, 0x09, 0x0a, 0x0d]) WS[c] = 1;
  const BRACE_O = 0x7b, BRACE_C = 0x7d, BRACKET_O = 0x5b, BRACKET_C = 0x5d;
  const QUOTE = 0x22, BACKSLASH = 0x5c, COLON = 0x3a, COMMA = 0x2c;

  const S = { START: 0, BEFORE_KEY: 1, KEY: 2, COLON: 3, BEFORE_VALUE: 4, COMPOUND: 5, STRING: 6, SCALAR: 7, AFTER_VALUE: 8, DONE: 9 };

  function concat(parts) {
    if (parts.length === 1) return parts[0];
    let n = 0;
    for (const p of parts) n += p.length;
    const out = new Uint8Array(n);
    let at = 0;
    for (const p of parts) { out.set(p, at); at += p.length; }
    return out;
  }

  function badJson(what, offset) {
    const e = new Error(`this is not JSON as expected: ${what} at byte ${offset.toLocaleString('en')}`);
    e.offset = offset;
    return e;
  }

  /**
   * Bytes in, top-level members out: for an object, each member's name and
   * the bytes of its value; for an array, each element's index. Fed a slice
   * at a time; a value may run over any number of slices.
   */
  class MemberScanner {
    constructor(onMember) {
      this.onMember = onMember;
      this.state = S.START;
      this.top = null;          // 'object' | 'array'
      this.offset = 0;          // bytes before the current slice
      this.depth = 0;
      this.inStr = false;
      this.esc = false;
      this.parts = [];
      this.key = null;
      this.index = 0;
    }

    push(b) {
      const n = b.length;
      let i = 0;
      let from = 0;             // where the value being read starts in this slice
      while (i < n) {
        switch (this.state) {
          case S.START: {
            const c = b[i++];
            if (WS[c]) break;
            if (c === BRACE_O) { this.top = 'object'; this.state = S.BEFORE_KEY; }
            else if (c === BRACKET_O) { this.top = 'array'; this.state = S.BEFORE_VALUE; }
            else if (c === 0xef && b[i] === 0xbb && b[i + 1] === 0xbf) i += 2;   // a byte-order mark
            else throw badJson('it does not start with { or [', this.offset + i - 1);
            break;
          }
          case S.BEFORE_KEY: {
            const c = b[i++];
            if (WS[c]) break;
            if (c === BRACE_C && this.index === 0) { this.state = S.DONE; break; }
            if (c !== QUOTE) throw badJson('a member name was expected', this.offset + i - 1);
            this.state = S.KEY;
            this.parts = [];
            from = i;
            break;
          }
          case S.KEY: {
            let j = i, esc = this.esc;
            for (; j < n; j++) {
              const c = b[j];
              if (esc) esc = false;
              else if (c === BACKSLASH) esc = true;
              else if (c === QUOTE) break;
            }
            this.esc = esc;
            if (j < n) {
              this.parts.push(b.subarray(from, j));
              this.key = JSON.parse(`"${new TextDecoder().decode(concat(this.parts))}"`);
              this.parts = [];
              this.state = S.COLON;
              i = j + 1;
            } else {
              this.parts.push(b.slice(from, n));
              i = n;
            }
            break;
          }
          case S.COLON: {
            const c = b[i++];
            if (WS[c]) break;
            if (c !== COLON) throw badJson('a colon was expected', this.offset + i - 1);
            this.state = S.BEFORE_VALUE;
            break;
          }
          case S.BEFORE_VALUE: {
            const c = b[i];
            if (WS[c]) { i++; break; }
            if (this.top === 'array' && c === BRACKET_C && this.index === 0) { this.state = S.DONE; i++; break; }
            if (this.top === 'array') this.key = this.index;
            this.parts = [];
            from = i;
            this.depth = 0; this.inStr = false; this.esc = false;
            if (c === BRACE_O || c === BRACKET_O) this.state = S.COMPOUND;
            else if (c === QUOTE) { this.state = S.STRING; i++; }
            else this.state = S.SCALAR;
            break;
          }
          case S.COMPOUND: {
            let j = i, d = this.depth, inS = this.inStr, esc = this.esc, ended = false;
            for (; j < n; j++) {
              const c = b[j];
              if (inS) {
                if (esc) esc = false;
                else if (c === BACKSLASH) esc = true;
                else if (c === QUOTE) inS = false;
                continue;
              }
              if (c === QUOTE) inS = true;
              else if (c === BRACE_O || c === BRACKET_O) d++;
              else if (c === BRACE_C || c === BRACKET_C) {
                if (--d === 0) { j++; ended = true; break; }
              }
            }
            this.depth = d; this.inStr = inS; this.esc = esc;
            if (ended) {
              this.parts.push(b.subarray(from, j));
              this.emit();
              i = j;
            } else {
              this.parts.push(b.subarray(from, n));
              i = n;
            }
            break;
          }
          case S.STRING: {
            let j = i, esc = this.esc;
            for (; j < n; j++) {
              const c = b[j];
              if (esc) esc = false;
              else if (c === BACKSLASH) esc = true;
              else if (c === QUOTE) break;
            }
            this.esc = esc;
            if (j < n) {
              this.parts.push(b.subarray(from, j + 1));
              this.emit();
              i = j + 1;
            } else {
              this.parts.push(b.subarray(from, n));
              i = n;
            }
            break;
          }
          case S.SCALAR: {
            let j = i;
            for (; j < n; j++) {
              const c = b[j];
              if (c === COMMA || c === BRACE_C || c === BRACKET_C || WS[c]) break;
            }
            if (j < n) {
              this.parts.push(b.subarray(from, j));
              this.emit();
              i = j;
            } else {
              this.parts.push(b.subarray(from, n));
              i = n;
            }
            break;
          }
          case S.AFTER_VALUE: {
            const c = b[i++];
            if (WS[c]) break;
            if (c === COMMA) this.state = this.top === 'object' ? S.BEFORE_KEY : S.BEFORE_VALUE;
            else if ((c === BRACE_C && this.top === 'object') || (c === BRACKET_C && this.top === 'array')) this.state = S.DONE;
            else throw badJson('a comma or the end was expected', this.offset + i - 1);
            break;
          }
          default: {
            const c = b[i++];
            if (!WS[c] && c !== 0) throw badJson('there is more after the end', this.offset + i - 1);
          }
        }
      }
      /* What is still being read must outlive the slice it is in only if the
         slice's buffer is reused; copies keep it safe either way. */
      if (this.parts.length) this.parts = this.parts.map((p) => (p.buffer === b.buffer ? p.slice() : p));
      this.offset += n;
    }

    emit() {
      const bytes = concat(this.parts);
      this.parts = [];
      this.state = S.AFTER_VALUE;
      this.index++;
      this.onMember(this.key, bytes, this.offset);
    }

    end() {
      if (this.state !== S.DONE) {
        throw badJson(this.state === S.START ? 'the file is empty' : 'the file ends part of the way through', this.offset);
      }
    }
  }

  /* NaN, Infinity and -Infinity as Python writes them, outside strings. */
  const PY_WORDS = /("(?:[^"\\]|\\.)*")|-?\bInfinity\b|\bNaN\b/g;

  function parseMember(text) {
    try {
      return { value: JSON.parse(text), lenient: false };
    } catch (err) {
      const fixed = text.replace(PY_WORDS, (m, str) => (str !== undefined ? str : 'null'));
      if (fixed === text) throw err;
      return { value: JSON.parse(fixed), lenient: true };
    }
  }

  /* ---------------------------------------------------------------------
     What a canister is made of
     --------------------------------------------------------------------- */

  const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
  const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?)?(Z|[+-]\d{2}:?\d{2})?$/;

  /** Milliseconds since 1970 (UTC) for an ISO date, NaN for anything else. */
  function dateMs(text) {
    const m = DATE_RE.exec(String(text ?? '').trim());
    if (!m) return NaN;
    const [, y, mo, d, h = '0', mi = '0', s = '0'] = m;
    const ms = Date.UTC(+y, +mo - 1, +d, +h, +mi, 0) + Math.round(parseFloat(s) * 1000);
    const back = new Date(ms);
    return back.getUTCMonth() === +mo - 1 && back.getUTCDate() === +d ? ms : NaN;
  }

  /** A map of nuclide names to numbers (null allowed), most names nuclides. */
  function isNuclideMap(v) {
    if (!isPlain(v)) return false;
    let keys = 0, nuclides = 0;
    for (const k in v) {
      const x = v[k];
      if (x !== null && typeof x !== 'number') return false;
      keys++;
      if (nuclideOf(k)) nuclides++;
    }
    return keys > 0 && nuclides * 2 >= keys;
  }

  const isElement = (v) => isPlain(v) && Object.values(v).some(isNuclideMap);

  /** How canisters hold their elements, from the first one. */
  function shapeOf(canister) {
    if (!isPlain(canister)) return null;
    let best = null;
    for (const [k, v] of Object.entries(canister)) {
      let kind = null, n = 0;
      if (isPlain(v)) {
        const vals = Object.values(v);
        if (vals.length && vals.every(isPlain) && vals.some(isElement)) { kind = 'object'; n = vals.length; }
      } else if (Array.isArray(v) && v.length && v.every(isPlain) && v.some(isElement)) {
        kind = 'array'; n = v.length;
      }
      if (!kind) continue;
      const score = (/element|assembl|fuel|bundle|patron/i.test(k) ? 1e6 : 0) + n;
      if (!best || score > best.score) best = { key: k, kind, score };
    }
    if (best) return { elements: best.key, kind: best.kind };
    return isElement(canister) ? { elements: null, kind: 'self' } : null;
  }

  /* ---------------------------------------------------------------------
     Columns that grow
     --------------------------------------------------------------------- */

  class NumColumn {
    constructor() { this.a = new Float64Array(1024); this.n = 0; }
    set(i, v) {
      if (i >= this.a.length) {
        const b = new Float64Array(Math.max(i + 1, this.a.length * 2));
        b.fill(NaN, this.a.length);
        b.set(this.a);
        this.a = b;
      }
      while (this.n < i) this.a[this.n++] = NaN;
      this.a[i] = v;
      if (i >= this.n) this.n = i + 1;
    }
    done(n) { const out = new Float64Array(n).fill(NaN); out.set(this.a.subarray(0, Math.min(n, this.n))); return out; }
  }

  class TextColumn {
    constructor() { this.codes = new Int32Array(1024).fill(-1); this.values = []; this.index = new Map(); }
    set(i, text) {
      if (i >= this.codes.length) {
        const b = new Int32Array(Math.max(i + 1, this.codes.length * 2)).fill(-1);
        b.set(this.codes);
        this.codes = b;
      }
      let code = this.index.get(text);
      if (code === undefined) { code = this.values.length; this.values.push(text); this.index.set(text, code); }
      this.codes[i] = code;
    }
    done(n) { const out = new Int32Array(n).fill(-1); out.set(this.codes.subarray(0, Math.min(n, this.codes.length))); return { codes: out, values: this.values }; }
  }

  /** Numbers and texts of one kind of record (canisters, or elements). */
  class Fields {
    constructor() { this.num = new Map(); this.text = new Map(); this.skipped = new Set(); }
    put(i, name, v) {
      if (typeof v === 'number') {
        if (this.text.has(name)) return this.text.get(name).set(i, String(v));
        let col = this.num.get(name);
        if (!col) { col = new NumColumn(); this.num.set(name, col); }
        col.set(i, v);
      } else if (typeof v === 'string' || typeof v === 'boolean') {
        let col = this.text.get(name);
        if (!col) {
          col = new TextColumn();
          /* A field first seen as a number turns to text: its numbers so far are kept as text. */
          const was = this.num.get(name);
          if (was) {
            for (let k = 0; k < was.n; k++) if (!Number.isNaN(was.a[k])) col.set(k, String(was.a[k]));
            this.num.delete(name);
          }
          this.text.set(name, col);
        }
        col.set(i, String(v));
      } else if (v !== null && v !== undefined) {
        this.skipped.add(name);
      }
    }
    done(n) {
      const num = {}, text = {};
      for (const [k, c] of this.num) num[k] = c.done(n);
      for (const [k, c] of this.text) text[k] = c.done(n);
      return { num, text, skipped: [...this.skipped] };
    }
  }

  /* ---------------------------------------------------------------------
     The builder: canisters in, columns out
     --------------------------------------------------------------------- */

  class Builder {
    constructor() {
      this.shape = null;
      this.canIds = [];
      this.canFields = new Fields();
      this.dateKey = null;
      this.dates = new NumColumn();
      this.dateText = [];
      this.el0 = new NumColumn();
      this.nEl = new NumColumn();
      this.elIds = [];
      this.elCan = new NumColumn();
      this.elFields = new Fields();
      this.parts = [];                 // part names, in the order first seen
      this.partIndex = new Map();
      this.nucKeys = [];
      this.nucIndex = new Map();
      this.amounts = new Float64Array(0);
      this.stride = 0;                 // parts x nuclides
      this.meta = {};                  // top-level members that are no canister
      this.notes = { lenient: 0, nulls: 0, negative: 0, notFinite: 0, missing: 0, notCanister: [], badDates: 0 };
    }

    get nCan() { return this.canIds.length; }
    get nElements() { return this.elIds.length; }

    /**
     * Room for one more element. The amounts are laid out element by
     * element, part by part, nuclide by nuclide; a part or nuclide first
     * seen part of the way through the file lays them out again, with zero
     * for what the earlier elements did not have.
     */
    room(nParts, nNuc) {
      const stride = nParts * nNuc;
      if (stride !== this.stride) {
        const a = new Float64Array(Math.max(1024, this.nElements * 2) * stride);
        if (this.stride) {
          const was = this.laid;
          for (let e = 0; e < this.nElements; e++) {
            for (let p = 0; p < was.parts; p++) {
              const from = e * this.stride + p * was.nuclides;
              a.set(this.amounts.subarray(from, from + was.nuclides), e * stride + p * nNuc);
            }
          }
          this.notes.missing += this.nElements * (stride - this.stride);
        }
        this.amounts = a;
        this.stride = stride;
        this.laid = { parts: nParts, nuclides: nNuc };
      }
      const need = (this.nElements + 1) * stride;
      if (need > this.amounts.length) {
        const a = new Float64Array(Math.max(need, this.amounts.length * 2));
        a.set(this.amounts);
        this.amounts = a;
      }
    }

    addTopLevel(key, value) {
      if (!this.shape) this.shape = shapeOf(value);
      if (!this.shape || !isPlain(value)) {
        if (value === null || typeof value !== 'object') this.meta[key] = value;
        else this.notes.notCanister.push(String(key));
        return;
      }
      let elements;
      if (this.shape.kind === 'self') elements = [[String(key), value]];
      else {
        const holder = value[this.shape.elements];
        if (isPlain(holder)) elements = Object.entries(holder);
        else if (Array.isArray(holder)) elements = holder.map((e, i) => [String(e && (e.id ?? e.name ?? e.element ?? i + 1)), e]);
        else if (isElement(value)) elements = [[String(key), value]];
        else { this.notes.notCanister.push(String(key)); return; }
      }
      const c = this.nCan;
      this.canIds.push(String(key));
      for (const [k, v] of Object.entries(value)) {
        if (k === this.shape.elements || isNuclideMap(v)) continue;
        if (typeof v === 'string' && (this.dateKey === k || (this.dateKey === null && DATE_RE.test(v.trim())))) {
          if (this.dateKey === null) this.dateKey = k;
          const ms = dateMs(v);
          if (Number.isNaN(ms)) this.notes.badDates++;
          this.dates.set(c, ms);
          this.dateText[c] = v;
          continue;
        }
        this.canFields.put(c, k, v);
      }
      this.el0.set(c, this.nElements);
      let count = 0;
      for (const [eid, el] of elements) {
        if (!isPlain(el)) continue;
        this.addElement(c, eid, el);
        count++;
      }
      this.nEl.set(c, count);
    }

    addElement(c, eid, el) {
      /* Register any new part or nuclide before the room is made. */
      for (const [k, v] of Object.entries(el)) {
        if (!(this.partIndex.has(k) || isNuclideMap(v))) continue;
        if (!this.partIndex.has(k)) { this.partIndex.set(k, this.parts.length); this.parts.push(k); }
        for (const nk in v) if (!this.nucIndex.has(nk)) { this.nucIndex.set(nk, this.nucKeys.length); this.nucKeys.push(nk); }
      }
      const nNuc = this.nucKeys.length;
      this.room(this.parts.length, nNuc);
      const e = this.nElements;
      this.elIds.push(eid);
      this.elCan.set(e, c);
      const base = e * this.stride;
      let given = 0;
      for (const [k, v] of Object.entries(el)) {
        const p = this.partIndex.get(k);
        if (p === undefined) { this.elFields.put(e, k, v); continue; }
        if (!isPlain(v)) { this.elFields.put(e, k, v); continue; }
        const at = base + p * nNuc;
        for (const nk in v) {
          /* A missing amount counts as none, so that sums stay numbers; the
             notes say how many there were. */
          let x = v[nk];
          if (x === null) { this.notes.nulls++; x = 0; }
          else if (!Number.isFinite(x)) { this.notes.notFinite++; x = 0; }
          else if (x < 0) this.notes.negative++;
          this.amounts[at + this.nucIndex.get(nk)] = x;
          given++;
        }
      }
      if (given < this.stride) this.notes.missing += this.stride - given;
    }

    finish() {
      const nCan = this.nCan, nEl = this.nElements;
      if (!nCan) {
        throw new Error(this.notes.notCanister.length || Object.keys(this.meta).length
          ? 'no canisters were found: no member holds fuel elements with nuclide amounts'
          : 'the file holds no canisters');
      }
      const stride = this.stride;
      return {
        meta: this.meta,
        notes: this.notes,
        parts: this.parts.slice(),
        nuclides: this.nucKeys.slice(),
        shape: this.shape,
        canisters: {
          n: nCan,
          id: this.canIds,
          dateKey: this.dateKey,
          date: this.dates.done(nCan),
          dateText: Array.from({ length: nCan }, (_, i) => this.dateText[i] ?? ''),
          el0: Int32Array.from(this.el0.done(nCan)),
          nEl: Int32Array.from(this.nEl.done(nCan)),
          ...this.canFields.done(nCan),
        },
        elements: {
          n: nEl,
          id: this.elIds,
          can: Int32Array.from(this.elCan.done(nEl)),
          ...this.elFields.done(nEl),
        },
        amounts: this.amounts.slice(0, nEl * stride),
      };
    }
  }

  /** The typed arrays of a finished inventory, to hand to postMessage. */
  function transferables(data) {
    const out = [data.amounts.buffer, data.canisters.date.buffer, data.canisters.el0.buffer, data.canisters.nEl.buffer, data.elements.can.buffer];
    for (const rec of [data.canisters, data.elements]) {
      for (const a of Object.values(rec.num)) out.push(a.buffer);
      for (const t of Object.values(rec.text)) out.push(t.codes.buffer);
    }
    return out;
  }

  /** Bytes in (any number of slices), the finished inventory out. */
  function inventoryReader() {
    const builder = new Builder();
    const decoder = new TextDecoder('utf-8');
    const scanner = new MemberScanner((key, bytes, offset) => {
      let parsed;
      try {
        parsed = parseMember(decoder.decode(bytes));
      } catch (err) {
        throw new Error(`canister ${JSON.stringify(String(key))} (near byte ${offset.toLocaleString('en')}) is not valid JSON: ${err.message}`);
      }
      if (parsed.lenient) builder.notes.lenient++;
      builder.addTopLevel(key, parsed.value);
    });
    return { push: (bytes) => scanner.push(bytes), finish: () => { scanner.end(); return builder.finish(); } };
  }

  /**
   * Read an inventory a slice at a time.
   *
   * @param {{size: number, read: function(number, number): Promise<Uint8Array>}} source
   * @param {function(number)} [progress] - share of the bytes read, 0..1
   * @param {{chunk?: number, shouldStop?: function(): boolean}} [opt]
   */
  async function readInventory(source, progress, opt = {}) {
    const reader = inventoryReader();
    const chunk = opt.chunk || (8 << 20);
    for (let at = 0; at < source.size; at += chunk) {
      if (opt.shouldStop && opt.shouldStop()) throw new Error('stopped');
      reader.push(await source.read(at, Math.min(source.size, at + chunk)));
      if (progress) progress(Math.min(1, (at + chunk) / source.size));
    }
    return reader.finish();
  }

  /**
   * Read an inventory from a stream of its bytes: an entry of a zip archive
   * or a gzip file, unpacked as it is read, so that the file is never whole
   * in memory, packed or not.
   *
   * @param {ReadableStream<Uint8Array>} stream
   * @param {{shouldStop?: function(): boolean}} [opt]
   */
  async function readInventoryStream(stream, opt = {}) {
    const reader = inventoryReader();
    const r = stream.getReader();
    try {
      for (;;) {
        if (opt.shouldStop && opt.shouldStop()) throw new Error('stopped');
        let step;
        try {
          step = await r.read();
        } catch (err) {
          /* DecompressionStream says no more than TypeError. */
          throw new Error(`the packed file is damaged (${err.message})`);
        }
        if (step.done) break;
        reader.push(step.value);
      }
    } catch (err) {
      r.cancel().catch(() => {});
      throw err;
    }
    return reader.finish();
  }

  /** A File or Blob as a source for readInventory(). */
  function blobSource(blob) {
    return { size: blob.size, read: async (from, to) => new Uint8Array(await blob.slice(from, to).arrayBuffer()) };
  }

  /* ---------------------------------------------------------------------
     Packed files: zip archives and gzip
     --------------------------------------------------------------------- */

  const u16 = (dv, at) => dv.getUint16(at, true);
  const u32 = (dv, at) => dv.getUint32(at, true);
  const u64 = (dv, at) => Number(dv.getBigUint64(at, true));

  /**
   * The entries of a zip archive, from its central directory. Only the end
   * of the archive and its directory are read, never the whole of it; zip64
   * archives (over 4 GB, or 65,535 entries) are read as well.
   *
   * @param {Blob} blob
   * @returns {Promise<Array<{name: string, flags: number, method: number, csize: number, usize: number, local: number}>>}
   */
  async function zipDirectory(blob) {
    const size = blob.size;
    const tail = new Uint8Array(await blob.slice(Math.max(0, size - (65535 + 22 + 20)), size).arrayBuffer());
    const dv = new DataView(tail.buffer);
    let end = -1;
    for (let i = tail.length - 22; i >= 0; i--) if (u32(dv, i) === 0x06054b50) { end = i; break; }
    if (end < 0) throw new Error('it is not a zip archive (no central directory)');
    let count = u16(dv, end + 10), cdSize = u32(dv, end + 12), cdAt = u32(dv, end + 16);
    if (count === 0xffff || cdSize === 0xffffffff || cdAt === 0xffffffff) {
      const loc = end - 20;
      if (loc < 0 || u32(dv, loc) !== 0x07064b50) throw new Error('its zip64 directory is missing');
      const at = u64(dv, loc + 8);
      const z = new DataView(await blob.slice(at, at + 56).arrayBuffer());
      if (z.byteLength < 56 || u32(z, 0) !== 0x06064b50) throw new Error('its zip64 directory is damaged');
      count = u64(z, 32); cdSize = u64(z, 40); cdAt = u64(z, 48);
    }
    const cd = new Uint8Array(await blob.slice(cdAt, cdAt + cdSize).arrayBuffer());
    const v = new DataView(cd.buffer, cd.byteOffset, cd.byteLength);
    const utf8 = new TextDecoder('utf-8', { fatal: true }), latin = new TextDecoder('latin1');
    const out = [];
    for (let at = 0, n = 0; n < count && at + 46 <= cd.length; n++) {
      if (u32(v, at) !== 0x02014b50) throw new Error('its zip directory is damaged');
      const flags = u16(v, at + 8), method = u16(v, at + 10);
      let csize = u32(v, at + 20), usize = u32(v, at + 24), local = u32(v, at + 42);
      const nlen = u16(v, at + 28), xlen = u16(v, at + 30), clen = u16(v, at + 32);
      const raw = cd.subarray(at + 46, at + 46 + nlen);
      /* UTF-8 when it is (most tools write it, flagged or not), else the old code page as Latin-1. */
      let name;
      try { name = utf8.decode(raw); } catch (e) { name = latin.decode(raw); }
      for (let x = at + 46 + nlen, xend = x + xlen; x + 4 <= xend;) {
        const id = u16(v, x), len = u16(v, x + 2);
        if (id === 1) {
          let p = x + 4;
          if (usize === 0xffffffff) { usize = u64(v, p); p += 8; }
          if (csize === 0xffffffff) { csize = u64(v, p); p += 8; }
          if (local === 0xffffffff) { local = u64(v, p); p += 8; }
        }
        x += 4 + len;
      }
      out.push({ name, flags, method, csize, usize, local });
      at += 46 + nlen + xlen + clen;
    }
    return out;
  }

  /** The bytes of an entry, as they unpack: onBytes counts the packed ones read. */
  async function zipEntryStream(blob, entry, onBytes) {
    if (entry.flags & 1) throw new Error(`${entry.name} is encrypted`);
    if (entry.method !== 0 && entry.method !== 8) throw new Error(`${entry.name} is packed in a way this page cannot unpack (method ${entry.method})`);
    const h = new DataView(await blob.slice(entry.local, entry.local + 30).arrayBuffer());
    if (h.byteLength < 30 || u32(h, 0) !== 0x04034b50) throw new Error(`${entry.name}: the archive is damaged`);
    const start = entry.local + 30 + u16(h, 26) + u16(h, 28);
    return unpack(blob.slice(start, start + entry.csize), entry.method === 8 ? 'deflate-raw' : null, onBytes);
  }

  /** A blob's bytes as a stream, unpacked by a format of DecompressionStream's ('gzip', 'deflate-raw') or as they are. */
  function unpack(blob, format, onBytes) {
    let s = blob.stream();
    if (onBytes) s = s.pipeThrough(new TransformStream({ transform(chunk, ctrl) { onBytes(chunk.byteLength); ctrl.enqueue(chunk); } }));
    if (format) {
      if (typeof DecompressionStream === 'undefined') throw new Error('this browser cannot unpack packed files');
      s = s.pipeThrough(new DecompressionStream(format));
    }
    return s;
  }

  /** What a zip archive's entry is for: its name, with the files that are not data left out. */
  function zipUsable(entry) {
    const base = entry.name.split('/').pop();
    return !(entry.name.endsWith('/') || /^__MACOSX\//.test(entry.name) || base.startsWith('._') || /^(\.DS_Store|Thumbs\.db|desktop\.ini)$/i.test(base));
  }

  return {
    SYMBOLS, nuclideOf, dateMs, isNuclideMap, shapeOf, MemberScanner, Builder, readInventory, readInventoryStream,
    blobSource, transferables, parseMember, zipDirectory, zipEntryStream, unpack, zipUsable,
  };
});
