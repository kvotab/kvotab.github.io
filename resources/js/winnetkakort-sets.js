/* ==========================================================================
   WINNETKAKORT - THE CARD SETS

   Everything winnetkakort.html knows about arithmetic lives here, apart from
   the page, so it can be tested in Node (resources/tests/winnetkakort): the
   groups of piles ("högar"), the facts in each pile, the forms a fact can be
   asked in, the strategy hint for each fact, and how a typed answer is read.

   A FACT is one thing to learn, identified by `key`. The same fact in two
   piles has the same key - 8 + 7 in "Stora plus" and in "Dubblor och nästan
   dubblor" - so knowing it in one pile counts in the other, and the progress
   grids find it whichever pile it was practised in. Each pile makes its own
   fact objects, because the hint belongs to the pile: 8 + 9 is a near double
   in one pile and a "plus 9" in another.

     kind 'op'    a ∘ b = c with ∘ one of + - * /. It can be asked as
                  a ∘ b = ? (form 'c'), a ∘ ? = c (form 'b') or
                  ? ∘ b = c (form 'a'); `forms` says which, `form0` which
                  one is the pile's own.
     kind 'text'  everything else (dubbelt av, procent, kvadratrot): a list
                  of tokens with exactly one BLANK, asked only that way.

   Tokens are what the page draws: {num} a number (paren: in brackets, for a
   negative second term), {op} an operator, {frac: [p, q]}, {pow: [b, e]},
   {sqrt: n}, a plain string (a word, '=' or '%'), and BLANK.
   ========================================================================== */

const WK_SETS = (() => {
  'use strict';

  const BLANK = Object.freeze({ blank: true });

  /* Decimal results rounded to ten places: 0.05 * 100 is 5.000000000000001. */
  const tidy = x => Math.round(x * 1e10) / 1e10;

  const OPS = {
    '+': { name: 'add', calc: (a, b) => a + b },
    '-': { name: 'sub', calc: (a, b) => a - b },
    '*': { name: 'mul', calc: (a, b) => a * b },
    '/': { name: 'div', calc: (a, b) => a / b },
  };

  function op(sym, a, b, extra) {
    return Object.assign({
      key: `${OPS[sym].name}:${a}:${b}`, kind: 'op', op: sym, a, b, c: tidy(OPS[sym].calc(a, b)),
      forms: ['c', 'b', 'a'], form0: 'c',
    }, extra);
  }
  const add = (a, b, extra) => op('+', a, b, extra);
  const sub = (a, b, extra) => op('-', a, b, extra);
  const mul = (a, b, extra) => op('*', a, b, extra);
  const div = (a, b, extra) => op('/', a, b, extra);

  function text(key, tokens, answer, extra) {
    return Object.assign({ key, kind: 'text', tokens, answer: tidy(answer) }, extra);
  }

  const range = (from, to) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
  const num = n => ({ num: n });

  /* Unicode has a glyph for these; the others are written p/q in plain text. */
  const FRACTION_GLYPHS = {
    '1/2': '½', '1/3': '⅓', '2/3': '⅔', '1/4': '¼', '3/4': '¾', '1/5': '⅕',
    '2/5': '⅖', '3/5': '⅗', '4/5': '⅘', '1/10': '⅒',
  };

  /* ── Hints ──────────────────────────────────────────────────────────────
     A hint is a way of thinking, not the answer: it names a known fact to
     start from (a double, a tiokompis, a table already learnt) or a step to
     take, and leaves the last step to the child. The test suite checks that
     no hint contains its own answer.

     `pic` is an optional picture: 'ten' (tiorutor, for sums within 20),
     'array' (rows of dots, for the tables) or 'line' (a number line).     */

  const H = {
    countOn: f => {
      const big = Math.max(f.a, f.b), small = Math.min(f.a, f.b);
      return `Börja på ${big} och räkna ${small === 1 ? 'ett steg' : small + ' steg'} till.`;
    },
    double: f => `Dubbelt av ${f.a}: samma tal två gånger.`,
    nearDouble: f => {
      const low = Math.min(f.a, f.b);
      return `Nästan en dubbel: ${low} + ${low} = ${low * 2}, och så en till.`;
    },
    tenFriend: known => `Hur många fattas från ${known} till 10?`,
    makeTen: f => {
      const big = Math.max(f.a, f.b), small = Math.min(f.a, f.b), fill = 10 - big;
      return `Fyll på till 10: ${big} + ${fill} = 10. Hur mycket är kvar av ${small}?`;
    },
    nearTen: f => {
      const big = Math.max(f.a, f.b), small = Math.min(f.a, f.b), less = 10 - big;
      return `Lägg till 10 och ta bort ${less} igen: ${small} + 10 = ${small + 10}.`;
    },
    tenAndOnes: f => {
      if (f.op === '+') return `Ett tiotal och ${Math.min(f.a, f.b)} ental.`;
      if (f.b === 10) return `Ta bort tiotalet från ${f.a}. Vilka ental blir kvar?`;
      return `${f.a} är ett tiotal och ${f.b} ental. Vad blir kvar när entalen tas bort?`;
    },
    countBack: f => `Börja på ${f.a} och räkna ${f.b === 1 ? 'ett steg' : f.b + ' steg'} bakåt.`,
    fromTen: f => `Tänk på tiokompisarna: ${f.b} + ? = 10.`,
    thinkAdd: f => `Tänk plus: ${f.b} + ? = ${f.a}.`,
    viaTen: f => {
      const down = f.a - 10;
      return `Gå via 10: ${f.a} − ${down} = 10. Hur mycket mer ska bort?`;
    },
    minusNearTen: f => `Ta bort 10 och lägg tillbaka ${10 - f.b}: ${f.a} − 10 = ${f.a - 10}.`,
    /* "tio tiotal" in words: 100 − 90 would otherwise say the 10 it asks for. */
    tens: f => {
      const t = n => (n === 100 ? 'tio' : n / 10);
      return `Räkna med tiotal: ${t(f.a)} tiotal ${f.op === '+' ? '+' : '−'} ${t(f.b)} tiotal.`;
    },
    hundredFriend: known => known % 10 === 0
      ? `Tiokompisar, fast med tiotal: ${known / 10} tiotal + ? tiotal = tio tiotal.`
      : 'Gå först till närmaste hela tiotal. Hur långt är det sedan till 100?',
    table: f => {
      const k = f.a, n = f.b;
      if (k === 1) return 'Ett gånger ett tal är talet självt.';
      if (k === 10) return `Tio gånger ett tal: skriv en nolla efter ${n}.`;
      switch (n) {
        case 1: return 'Ett tal gånger ett är talet självt.';
        case 2: return `Dubbelt av ${k}.`;
        case 3: return `Tänk ${k} · 2 och lägg till en ${k} till.`;
        case 4: return `Dubbelt av dubbelt: först ${k} · 2, sedan dubbelt av det.`;
        case 5: return k % 2 === 0 ? `Hälften av ${k} är ${k / 2}. Sätt en nolla efter.` : `Hälften av ${k} · 10.`;
        case 6: return `Tänk ${k} · 5 och lägg till en ${k} till.`;
        case 7: return `Tänk ${k} · 5 och ${k} · 2 och lägg ihop.`;
        case 8: return `Dubbelt av ${k} · 4.`;
        case 9: return `Tänk ${k} · 10 och ta bort en ${k}.`;
        case 10: return `Tio gånger ett tal: skriv en nolla efter ${k}.`;
        default: return `Tänk på ${n}:ans tabell.`;
      }
    },
    divide: f => `Tänk gånger: ${f.b} · ? = ${f.a}.`,
    powerOfTen: f => {
      const steps = { 10: 'ett steg', 100: 'två steg', 1000: 'tre steg' }[f.b];
      return f.op === '*'
        ? `Gånger ${f.b}: talet blir ${f.b} gånger större, och varje siffra flyttar ${steps} åt vänster.`
        : `Delat med ${f.b}: talet blir ${f.b} gånger mindre, och varje siffra flyttar ${steps} åt höger.`;
    },
    negative: f => {
      if (f.b < 0) return `Att ta bort ett negativt tal är samma sak som att lägga till: ${fmtPlain(f.a)} − (${fmtPlain(f.b)}) = ${fmtPlain(f.a)} + ${-f.b}.`;
      return `Börja på ${fmtPlain(f.a)} på tallinjen och gå ${f.b} steg åt ${f.op === '+' ? 'höger' : 'vänster'}.`;
    },
  };

  /* The hint for a missing number is the same whichever pile the fact is in:
     turn the question round into the operation the child already knows. */
  function inverseHint(f, form) {
    const A = fmtPlain(f.a), B = fmtPlain(f.b), C = fmtPlain(f.c);
    switch (f.op) {
      case '+': return form === 'b'
        ? `Hur mycket fattas från ${A} till ${C}?`
        : `Hur mycket fattas från ${B} till ${C}?`;
      case '-': return form === 'b'
        ? `Hur mycket ska bort från ${A} för att ${C} ska bli kvar? Tänk ${C} + ? = ${A}.`
        : `Vilket tal blir ${C} när du tar bort ${B}? Tänk ${C} + ${B}.`;
      case '*': {
        const known = form === 'b' ? f.a : f.b;
        const table = Number.isInteger(known) && known >= 2 && known <= 10 ? ` Tänk på ${known}:ans tabell.` : '';
        return `Vilket tal gånger ${fmtPlain(known)} blir ${C}?${table}`;
      }
      case '/': return form === 'b'
        ? `Vilket tal gånger ${C} blir ${A}?`
        : `Vilket tal blir ${C} när det delas med ${B}? Tänk ${C} · ${B}.`;
      default: return '';
    }
  }

  function tenPicture(f, form) {
    if (f.kind !== 'op' || f.neg || (f.op !== '+' && f.op !== '-')) return null;
    if (!Number.isInteger(f.a) || !Number.isInteger(f.b) || f.a < 0 || f.b < 0) return null;
    if (f.friend === 10) {
      /* A tiokompis always shows the frame: the empty squares are the point. */
      return { type: 'ten', parts: [{ n: form === 'a' ? f.b : f.a, tone: 'a' }], crossed: 0 };
    }
    if (form !== 'c') return null;
    if (f.op === '+' && f.c <= 20) return { type: 'ten', parts: [{ n: f.a, tone: 'a' }, { n: f.b, tone: 'b' }], crossed: 0 };
    if (f.op === '-' && f.a <= 20) return { type: 'ten', parts: [{ n: f.a, tone: 'a' }], crossed: f.b };
    return null;
  }

  function hint(f, form) {
    const known = form === 'a' ? f.b : f.a;
    let words;
    if (f.kind === 'op' && form !== 'c' && !f.friend) words = inverseHint(f, form);
    else if (f.friend === 10) words = H.tenFriend(known);
    else if (f.friend === 100) words = H.hundredFriend(known);
    else words = typeof f.hint === 'function' ? f.hint(f) : (f.hint || '');
    let pic = tenPicture(f, form);
    if (!pic && f.kind === 'op' && form === 'c') {
      if (f.op === '*' && f.a <= 10 && f.b <= 10 && Number.isInteger(f.a) && Number.isInteger(f.b)) {
        pic = { type: 'array', rows: f.a, cols: f.b };
      } else if (f.op === '/' && f.b <= 10 && f.c <= 10 && Number.isInteger(f.c)) {
        pic = { type: 'array', rows: f.c, cols: f.b };
      } else if (f.pic === 'line') {
        pic = { type: 'line', mark: f.a };
      }
    }
    return { text: words, pic };
  }

  /* ── The piles ────────────────────────────────────────────────────────── */

  function pairs(test) {
    const out = [];
    for (const a of range(1, 9)) for (const b of range(1, 9)) if (test(a, b)) out.push([a, b]);
    return out;
  }

  const smallPlus = pairs((a, b) => a + b <= 10);
  const bigPlus = pairs((a, b) => a + b >= 11);
  const isDouble = (a, b) => a === b;
  const isNearDouble = (a, b) => Math.abs(a - b) === 1;

  function plusHint(a, b) {
    if (isDouble(a, b)) return H.double;
    if (isNearDouble(a, b) && a + b > 3) return H.nearDouble;
    if (a + b >= 11) return Math.max(a, b) >= 8 ? H.nearTen : H.makeTen;
    return H.countOn;
  }

  function smallMinusHint(a, b) {
    if (b <= 2) return H.countBack;
    if (a === 10) return H.fromTen;
    return H.thinkAdd;
  }

  const TABLE_NAMES = n => `${n}:ans tabell`;

  const GROUPS = [
    {
      id: 'inom10', title: 'Plus och minus inom 10', grade: 'åk 1', color: 'green',
      desc: 'Talen upp till 10. Börja med tiokompisarna – de kommer tillbaka i nästan allt annat.',
      sets: [
        {
          id: 'tio', title: 'Tiokompisar',
          facts: () => range(0, 10).map(a => add(a, 10 - a, { key: `tio:${a}`, friend: 10, forms: ['b', 'a'], form0: 'b' })),
        },
        {
          id: 'p12', title: 'Plus 1 och plus 2',
          facts: () => smallPlus.filter(([a, b]) => Math.min(a, b) <= 2).map(([a, b]) => add(a, b, { hint: H.countOn })),
        },
        {
          id: 'dub10', title: 'Dubblor och nästan dubblor',
          facts: () => smallPlus.filter(([a, b]) => isDouble(a, b) || isNearDouble(a, b))
            .map(([a, b]) => add(a, b, { hint: isDouble(a, b) ? H.double : H.nearDouble })),
        },
        {
          id: 'lp', title: 'Lilla plus',
          facts: () => smallPlus.map(([a, b]) => add(a, b, { hint: plusHint(a, b) })),
        },
        {
          id: 'm10', title: 'Minus från 10',
          facts: () => range(0, 10).map(b => sub(10, b, { hint: H.fromTen })),
        },
        {
          id: 'lm', title: 'Lilla minus',
          facts: () => smallPlus.map(([b, c]) => sub(b + c, b, { hint: smallMinusHint(b + c, b) })),
        },
      ],
    },
    {
      id: 'inom20', title: 'Plus och minus inom 20', grade: 'åk 1–2', color: 'blue',
      desc: 'Tiotalsövergång: när svaret går över 10. Tänk via 10.',
      sets: [
        {
          id: 'ti', title: 'Tio och ental',
          facts: () => [
            ...range(1, 9).map(a => add(10, a, { hint: H.tenAndOnes })),
            ...range(1, 9).map(a => sub(10 + a, a, { hint: H.tenAndOnes })),
            ...range(1, 9).map(a => sub(10 + a, 10, { hint: H.tenAndOnes })),
          ],
        },
        {
          id: 'p98', title: 'Plus 9 och plus 8',
          facts: () => bigPlus.filter(([a, b]) => Math.max(a, b) >= 8).map(([a, b]) => add(a, b, { hint: H.nearTen })),
        },
        {
          id: 'dub20', title: 'Dubblor och nästan dubblor',
          facts: () => bigPlus.filter(([a, b]) => isDouble(a, b) || isNearDouble(a, b))
            .map(([a, b]) => add(a, b, { hint: isDouble(a, b) ? H.double : H.nearDouble })),
        },
        {
          id: 'sp', title: 'Stora plus',
          facts: () => bigPlus.map(([a, b]) => add(a, b, { hint: plusHint(a, b) })),
        },
        {
          id: 'm98', title: 'Minus 9 och minus 8',
          facts: () => [
            ...range(11, 18).map(a => sub(a, 9, { hint: H.minusNearTen })),
            ...range(11, 17).map(a => sub(a, 8, { hint: H.minusNearTen })),
          ],
        },
        {
          id: 'sm', title: 'Stora minus',
          facts: () => bigPlus.map(([b, c]) => sub(b + c, b, { hint: b >= 8 ? H.minusNearTen : H.viaTen })),
        },
      ],
    },
    {
      id: 'storre', title: 'Större tal', grade: 'åk 2–3', color: 'yellow',
      desc: 'Det du kan inom 10 fungerar med tiotal också: 3 + 5 = 8, så 30 + 50 = 80. Och hundrakompisar, dubbelt och hälften.',
      sets: [
        {
          id: 'htp', title: 'Hela tiotal – plus',
          facts: () => smallPlus.map(([a, b]) => add(a * 10, b * 10, { hint: H.tens })),
        },
        {
          id: 'htm', title: 'Hela tiotal – minus',
          facts: () => smallPlus.map(([b, c]) => sub((b + c) * 10, b * 10, { hint: H.tens })),
        },
        {
          id: 'hk', title: 'Hundrakompisar',
          facts: () => [...range(1, 9).map(t => t * 10), ...range(0, 9).map(t => t * 10 + 5)]
            .sort((x, y) => x - y)
            .map(a => add(a, 100 - a, { key: `hk:${a}`, friend: 100, forms: ['b', 'a'], form0: 'b' })),
        },
        {
          id: 'dh', title: 'Dubbelt och hälften',
          facts: () => {
            const ns = [...range(1, 10), 15, 20, 25, 50];
            return [
              ...ns.map(n => text(`dbl:${n}`, ['Dubbelt av', num(n), '=', BLANK], 2 * n, { hint: doubleHint(n) })),
              ...ns.map(n => text(`half:${2 * n}`, ['Hälften av', num(2 * n), '=', BLANK], n, { hint: halfHint(2 * n) })),
            ];
          },
        },
      ],
    },
    {
      id: 'ganger', title: 'Multiplikation', grade: 'åk 2–4', color: 'red',
      desc: 'En tabell i taget. Tabellerna hjälper varandra: 4:an är dubbelt av 2:an, och 9:an är 10:an minus en gång.',
      sets: [
        ...range(1, 10).map(n => ({
          id: `t${n}`, title: TABLE_NAMES(n),
          facts: () => range(1, 10).map(k => mul(k, n, { hint: H.table })),
        })),
        { id: 't15', title: 'Tabell 1–5 blandat', facts: () => tables(range(1, 5)) },
        { id: 't610', title: 'Tabell 6–10 blandat', facts: () => tables(range(6, 10)) },
        { id: 'tall', title: 'Alla tabeller', facts: () => tables(range(1, 10)) },
      ],
    },
    {
      id: 'delat', title: 'Division', grade: 'åk 3–5', color: 'purple',
      desc: 'Division är multiplikation baklänges: 42 delat med 6 är det tal som 6 ska gångras med för att bli 42.',
      sets: [
        ...range(2, 10).map(n => ({
          id: `d${n}`, title: `Delat med ${n}`,
          facts: () => range(1, 10).map(q => div(n * q, n, { hint: H.divide })),
        })),
        {
          id: 'dall', title: 'Delat med 2–10 blandat',
          facts: () => range(2, 10).flatMap(n => range(1, 10).map(q => div(n * q, n, { hint: H.divide }))),
        },
      ],
    },
    {
      id: 'mer', title: 'Mer huvudräkning', grade: 'åk 4–6', color: 'teal',
      desc: 'Tiopotenser, kvadrattal, bråk, procent och negativa tal.',
      sets: [
        {
          id: 'tiop', title: 'Gånger och delat med 10, 100 och 1000',
          facts: () => [
            ...[[7, 10], [45, 10], [3.5, 10], [0.8, 10], [6, 100], [2.4, 100], [0.05, 100], [3, 1000], [1.2, 1000], [0.25, 1000]]
              .map(([a, b]) => mul(a, b, { hint: H.powerOfTen })),
            ...[[70, 10], [450, 10], [36, 10], [5, 10], [800, 100], [250, 100], [4, 100], [6000, 1000], [1500, 1000], [300, 1000]]
              .map(([a, b]) => div(a, b, { hint: H.powerOfTen })),
          ],
        },
        {
          id: 'kv', title: 'Kvadrattal och kvadratrötter',
          facts: () => [
            ...range(1, 12).map(n => text(`sq:${n}`, [{ pow: [n, 2] }, '=', BLANK], n * n, { hint: `${n}² betyder ${n} · ${n}.` })),
            ...range(1, 12).map(n => text(`sqrt:${n * n}`, [{ sqrt: n * n }, '=', BLANK], n,
              { hint: `Vilket tal gånger sig självt blir ${n * n}?` })),
          ],
        },
        {
          id: 'delav', title: 'Del av ett tal',
          facts: () => [
            [1, 2, [8, 14, 16, 20, 50]], [1, 3, [9, 15, 21, 30]], [1, 4, [8, 20, 28, 40, 100]],
            [1, 5, [15, 35, 50]], [1, 10, [30, 70, 200]], [3, 4, [8, 20, 40, 100]], [2, 3, [9, 15, 30]],
          ].flatMap(([p, q, ns]) => ns.map(n => text(`of:${p}/${q}:${n}`,
            [{ frac: [p, q] }, 'av', num(n), '=', BLANK], (n / q) * p, { hint: fractionOfHint(p, q, n) }))),
        },
        {
          id: 'proc', title: 'Procent av ett tal',
          facts: () => [
            [50, [16, 40, 90, 250]], [25, [12, 40, 80, 200]], [10, [45, 70, 250, 600]], [1, [50, 300, 700]],
            [20, [35, 45, 200]], [75, [12, 40, 200]], [5, [60, 80]],
          ].flatMap(([p, ns]) => ns.map(n => text(`pct:${p}:${n}`,
            [num(p), '%', 'av', num(n), '=', BLANK], (n * p) / 100, { hint: PERCENT_HINTS[p] }))),
        },
        {
          id: 'bdp', title: 'Bråk, decimaltal och procent',
          facts: () => [
            ...[[1, 2], [1, 4], [3, 4], [1, 5], [2, 5], [1, 10], [3, 10], [1, 20], [1, 100]].map(([p, q]) =>
              text(`f2p:${p}/${q}`, [{ frac: [p, q] }, '=', BLANK, '%'], (100 * p) / q,
                { hint: 'Procent betyder hundradelar. Skriv bråket med 100 i nämnaren.' })),
            ...[0.5, 0.25, 0.75, 0.1, 0.05, 0.3, 0.01].map(d =>
              text(`d2p:${d}`, [num(d), '=', BLANK, '%'], d * 100,
                { hint: 'Procent betyder hundradelar: gånger 100 flyttar siffrorna två steg åt vänster.' })),
            ...[50, 25, 10, 5, 75, 40, 1].map(p =>
              text(`p2d:${p}`, [num(p), '%', '=', BLANK], p / 100,
                { note: 'Svara med ett decimaltal.', hint: 'Procent betyder hundradelar: dela med 100.' })),
            ...[[1, 2], [1, 4], [3, 4], [1, 5], [1, 10]].map(([p, q]) =>
              text(`f2d:${p}/${q}`, [{ frac: [p, q] }, '=', BLANK], p / q,
                { note: 'Svara med ett decimaltal.', hint: `Ett bråk är en division: ${p} / ${q}. Tänk på pengar: hur många öre är det av en krona?` })),
          ],
        },
        {
          id: 'neg', title: 'Negativa tal',
          facts: () => [
            [3, '-', 5], [2, '-', 7], [4, '-', 9], [1, '-', 6], [0, '-', 4], [6, '-', 10],
            [-3, '+', 5], [-6, '+', 2], [-8, '+', 8], [-4, '+', 10], [-7, '+', 3], [-1, '+', 9],
            [-2, '-', 3], [-5, '-', 4], [-6, '-', 6], [-1, '-', 8],
            [5, '-', -2], [3, '-', -4], [-6, '-', -2], [-1, '-', -5],
          ].map(([a, sym, b]) => op(sym, a, b, { hint: H.negative, pic: 'line', forms: ['c'], neg: true })),
        },
      ],
    },
  ];

  function tables(ns) {
    return ns.flatMap(n => range(1, 10).map(k => mul(k, n, { hint: H.table })));
  }

  function doubleHint(n) {
    if (n <= 10) return `Dubbelt är samma tal två gånger: ${n} + ${n}.`;
    if (n % 10 === 0) return `Tänk dubbelt av ${n / 10} och räkna med tiotal.`;
    return `Dela upp ${n}: dubbelt av ${n - 5} och dubbelt av 5.`;
  }

  function halfHint(m) {
    if (m <= 20) return `Vilket tal plus sig självt blir ${m}?`;
    if (m % 20 === 0) return `Tänk hälften av ${m / 10} och räkna med tiotal.`;
    return `Dela upp ${m}: hälften av ${m - 10} och hälften av 10.`;
  }

  function fractionOfHint(p, q, n) {
    const part = FRACTION_GLYPHS[`1/${q}`] || `1/${q}`;
    if (p === 1) return `${part} av ${n} är ${n} delat i ${q} lika stora delar.`;
    return `Ta först ${part} av ${n}. ${FRACTION_GLYPHS[`${p}/${q}`] || `${p}/${q}`} är ${p} sådana delar.`;
  }

  const PERCENT_HINTS = {
    50: '50 % är hälften.',
    25: '25 % är en fjärdedel – hälften av hälften.',
    10: '10 % är en tiondel: dela med 10.',
    1: '1 % är en hundradel: dela med 100.',
    20: '20 % är dubbelt så mycket som 10 %.',
    75: '75 % är 50 % och 25 % tillsammans.',
    5: '5 % är hälften av 10 %.',
  };

  /* ── Building the registry ────────────────────────────────────────────── */

  const setById = Object.create(null);
  const factByKey = Object.create(null);
  const allSets = [];

  for (const group of GROUPS) {
    for (const set of group.sets) {
      set.group = group.id;
      set.color = group.color;
      set.facts = set.facts().map(f => Object.assign(f, { set: set.id }));
      setById[set.id] = set;
      allSets.push(set);
      for (const f of set.facts) if (!(f.key in factByKey)) factByKey[f.key] = f;
    }
  }

  /* ── Asking a fact ────────────────────────────────────────────────────── */

  /**
   * The form to ask a fact in.
   *
   * @param {Object} fact
   * @param {'vanlig'|'saknat'|'blandat'} mode - the page's "Frågor" setting
   * @param {function(): number} random - Math.random or a seeded stand-in
   * @returns {'c'|'b'|'a'|'text'}
   */
  function pickForm(fact, mode, random) {
    if (fact.kind !== 'op') return 'text';
    const forms = fact.forms;
    let pool;
    if (mode === 'saknat') pool = forms.filter(f => f !== 'c');
    else if (mode === 'blandat') pool = forms;
    if (!pool || !pool.length) return fact.form0;
    return pool[Math.floor(random() * pool.length) % pool.length];
  }

  /**
   * The tokens to draw and the number that answers them.
   *
   * @returns {{tokens: Array, answer: number, note: (string|undefined)}}
   */
  function question(fact, form) {
    if (fact.kind === 'text') return { tokens: fact.tokens, answer: fact.answer, note: fact.note };
    const second = { num: fact.b, paren: fact.b < 0 };
    const parts = [num(fact.a), { op: fact.op }, second, '=', num(fact.c)];
    const at = { a: 0, b: 2, c: 4 }[form];
    const answer = { a: fact.a, b: fact.b, c: fact.c }[form];
    parts[at] = BLANK;
    return { tokens: parts, answer, note: fact.note };
  }

  /** The complete statement, for the back of the card: 7 · 8 = 56. */
  function statement(fact) {
    if (fact.kind === 'text') return { tokens: fact.tokens.map(t => (t === BLANK ? num(fact.answer) : t)), answer: fact.answer };
    return {
      tokens: [num(fact.a), { op: fact.op }, { num: fact.b, paren: fact.b < 0 }, '=', num(fact.c)],
      answer: fact.c,
    };
  }

  /* ── Reading an answer ────────────────────────────────────────────────── */

  /**
   * A typed answer as a number, or null when it is not one.
   *
   * Takes what a Swedish child types: a decimal comma or point, spaces (or
   * the no-break and thin spaces a paste brings) between groups of digits,
   * the minus sign, hyphen or dash, and a trailing % that the card already
   * shows.
   *
   * @param {string} raw
   * @returns {number|null}
   */
  function parseAnswer(raw) {
    let s = String(raw ?? '').trim();
    s = s.replace(/[\s   ]+/g, '').replace(/[−–—]/g, '-').replace(/%$/, '');
    s = s.replace(',', '.');
    if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return null;
    const x = Number(s);
    return Number.isFinite(x) ? x : null;
  }

  const sameNumber = (x, y) => Math.abs(x - y) < 1e-9;

  /* ── Plain text, for the tiles, the summary and the grid caption ─────── */

  const SIGNS = {
    punkt: { '+': '+', '-': '−', '*': '·', '/': '/' },
    kryss: { '+': '+', '-': '−', '*': '×', '/': '÷' },
  };

  /** Swedish number: decimal comma, the true minus sign, no grouping under 10 000. */
  function fmtPlain(x) {
    const neg = x < 0;
    const [whole, frac] = String(Math.abs(tidy(x))).split('.');
    const grouped = whole.length > 4 ? whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : whole;
    return (neg ? '−' : '') + grouped + (frac ? ',' + frac : '');
  }

  function tokenText(t, signs, blankText) {
    if (t === BLANK) return blankText;
    if (typeof t === 'string') return t;
    if ('num' in t) return t.paren ? `(${fmtPlain(t.num)})` : fmtPlain(t.num);
    if ('op' in t) return (SIGNS[signs] || SIGNS.punkt)[t.op];
    if ('frac' in t) return FRACTION_GLYPHS[t.frac.join('/')] || t.frac.join('/');
    if ('pow' in t) return `${t.pow[0]}${t.pow[1] === 2 ? '²' : '^' + t.pow[1]}`;
    if ('sqrt' in t) return `√${t.sqrt}`;
    return '';
  }

  /** "7 · 8 = ?" - a percent sign hugs its number with a no-break space. */
  function plainText(tokens, signs = 'punkt', blankText = '?') {
    let out = '';
    tokens.forEach((t, i) => {
      const piece = tokenText(t, signs, blankText);
      if (i === 0) out = piece;
      else if (t === '%') out += ' %';
      else out += ' ' + piece;
    });
    return out;
  }

  return {
    GROUPS, allSets, setById, factByKey, BLANK, FRACTION_GLYPHS,
    pickForm, question, statement, hint, parseAnswer, sameNumber, fmtPlain, plainText, SIGNS,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = WK_SETS;
