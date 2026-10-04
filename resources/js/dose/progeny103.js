/*
  Systemic models of radioactive progeny in the ICRP 103 system, as the
  element sections of the OIR series define them (Publications 134, 137, 141
  and 151, "Treatment of radioactive progeny"), which Publication 158 adopts
  (paras 152-154): the model an element X follows when it is produced in the
  body after intake of a parent of element Y is set by Y's section, and is
  the same for every chain that Y heads.

  resources/data/dose/icrp103/progeny.json holds them:

    parents  { Y: set name }: the set of progeny models a chain headed by Y uses
    sets     { name: { X: spec } }

  A spec says, for one progeny element X:

    base     the element whose characteristic model is the starting point
             (default X), or
    model    a complete model (compartments, transfers, entry): where the
             section gives one of its own (thallium, gold and mercury in lead
             chains) or the adult model of Publication 151 is kept
             (selenium and silver chains)
    key      which of the element's models to start from (mercury: inorganic)
    from     "set": start from that set's spec for X, then apply ops
    ops      changes to the model, in order:
               {op: 'carve', from: [names], add: [{name, region, rate | like +
                 factor | share (+ per) | ofOutflow (+ excluding), out}]}
                 adds compartments fed from central blood and takes their
                 inflow from the `from` compartments, so that the total
                 outflow from blood is kept; at other ages the added inflows
                 keep their ratio to the inflow they are taken from
               {op: 'rename', name, to, region}
               {op: 'remove', name}           a compartment and its transfers
               {op: 'set', from, to, rate}    a constant transfer coefficient
               {op: 'entry', name}
    entry    where X absorbed to blood, or arriving from a site its model does
             not have, enters (default the model's entry)
    fA       absorption from the small intestine when X has no element file
    identify { "Name" or "El:Name": name in X's model, or null }: a parent
             compartment identified with one of X's (or explicitly not)
    sameName true (default): a parent compartment with the name of one of X's
             is that compartment; false, or a list of the names this holds for
    sameOther the unspecific soft-tissue pools (ST0-ST2, Other) of another
             element's model: false (default) never X's own; true, X's pool
             of the same name; 'progeny', so only where that model is a
             progeny's, not the chain parent's (the radium set's thorium and
             radium, as the ICRP's own coefficients show)
    unid     the transfer from a site X's model does not have to `entry`, d-1:
               blood (1000), soft, surface (bone surface; default soft),
               volume ('turnover' (default), 'nonexch', 'decay' or a rate),
               byRegion {region: rate}, byName {name: rate}
             a rate may be {like: name}: the rate from that compartment of X's
             model to blood, at each age; {exhale: rate}: out of the body (radon
             progeny formed in the air of the respiratory tract)
    decayAtSite  true: X decays where it is produced (francium, astatine, ...)

  Noble gases produced in the body follow the generic OIR model whatever the
  set (ICRP 137 paras 711, 179; ICRP 134 para 485; ICRP 141 para 563): to
  blood at 100 d-1 from bone surfaces, 1.5 from exchangeable and 0.36 from
  non-exchangeable bone volume (and from bone volume not so divided), from
  soft tissues with a half-time of 30 min (radon), 20 min (xenon) or 15 min
  (krypton; argon, ICRP 151 para 135), exhaled from blood at 1000 d-1.
*/

/* Reference age-specific bone turnover rates, d-1 (Publication 89; the rates
   of the alkaline-earth models from non-exchangeable bone volume to blood). */
export const BONE_TURNOVER = {
  ages: [100, 365, 1825, 3650, 5475, 9125],
  'T-bone-V': [0.00822, 0.00288, 0.00181, 0.00132, 0.000959, 0.000493],
  'C-bone-V': [0.00822, 0.00288, 0.00153, 0.000904, 0.000521, 0.0000821],
};

export const GAS_PROGENY = {
  Rn: { soft: Math.LN2 / (30 / 1440) },
  Xe: { soft: Math.LN2 / (20 / 1440) },
  Kr: { soft: Math.LN2 / (15 / 1440) },
  Ar: { soft: Math.LN2 / (15 / 1440) }, // from chlorine (ICRP 151 para 135)
  surface: 100, exch: 1.5, nonexch: 0.36, volume: 0.36, exhale: 1000,
};

/** 'exch', 'nonexch' or 'volume' for a bone volume compartment's name. */
export function boneVolumeKind(name) {
  if (/non.?exch|vol(ume)? 2$/i.test(name)) return 'nonexch';
  if (/exch|vol(ume)? 1$/i.test(name)) return 'exch';
  return 'volume';
}

/** The spec of X for a chain headed by Y, with `from` resolved; null if none. */
export function progenySpec(progeny, headEl, el) {
  const setName = progeny?.parents?.[headEl];
  if (!setName) return null;
  return resolve(progeny, setName, el, 0);
}

function resolve(progeny, setName, el, depth) {
  if (depth > 8) throw new Error(`progeny sets: a loop at ${setName}`);
  const set = progeny.sets[setName];
  if (!set) throw new Error(`progeny set ${setName} missing`);
  let spec = set[el];
  if (spec === undefined && set['*inherit']) return resolve(progeny, set['*inherit'], el, depth + 1);
  if (!spec) return null;
  if (typeof spec === 'string') {
    // "set" or "set:El": that set's spec (for this element, or for El as a model for this one)
    const [s, e] = spec.split(':');
    const other = resolve(progeny, s, e || el, depth + 1);
    return other && e && e !== el ? { base: other.base || e, ...other } : other;
  }
  if (spec.from) {
    const fromEl = spec.fromEl || el;
    const prior = resolve(progeny, spec.from, fromEl, depth + 1);
    if (!prior) throw new Error(`progeny set ${spec.from} has no ${fromEl}`);
    const { from, fromEl: _, ops, ...rest } = spec;
    spec = { ...prior, ...rest, ops: [...(prior.ops || []), ...(ops || [])] };
    if (fromEl !== el && !spec.base && !spec.model) spec.base = fromEl;
  }
  return { ...spec, set: setName };
}

const rateAt = (rates, a) => (rates.length === 1 ? rates[0] : rates[a]);

/**
 * The systemic model of X as the spec defines it, built from `elements` (the
 * page's element files) and a default-model picker.
 */
export function buildProgenyModel(spec, el, elements, modelOf) {
  let model;
  if (spec.model) {
    model = clone(spec.model);
    model.ages ||= [7300];
  } else {
    const E = elements[spec.base || el];
    if (!E) throw new Error(`progeny model for ${el}: no element ${spec.base || el}`);
    model = clone(modelOf(E, spec.key || 'default'));
  }
  const n = model.ages.length;
  const full = (rates) => (rates.length === n ? rates.slice() : Array.from({ length: n }, (_, a) => rateAt(rates, a)));
  const find = (a, b) => model.transfers.find(([x, y]) => x === a && y === b);
  const blood = () => spec.blood || model.entry;
  const inflow = (name) => { const t = find(blood(), name); return t ? full(t[2]) : new Array(n).fill(0); };
  const toBlood = (name) => { const t = find(name, blood()); return t ? full(t[2]) : new Array(n).fill(0); };
  for (const op of spec.ops || []) {
    if (op.op === 'rename') {
      const region = op.region || model.compartments[op.name];
      delete model.compartments[op.name];
      model.compartments[op.to] = region;
      for (const t of model.transfers) { if (t[0] === op.name) t[0] = op.to; if (t[1] === op.name) t[1] = op.to; }
      if (model.entry === op.name) model.entry = op.to;
    } else if (op.op === 'remove') {
      delete model.compartments[op.name];
      model.transfers = model.transfers.filter(([a, b]) => a !== op.name && b !== op.name);
    } else if (op.op === 'set') {
      const t = find(op.from, op.to);
      const rates = Array.isArray(op.rate) ? op.rate : [op.rate];
      if (t) t[2] = full(rates); else model.transfers.push([op.from, op.to, full(rates)]);
    } else if (op.op === 'entry') {
      model.entry = op.name;
    } else if (op.op === 'boneByAge') {
      // ICRP 158 para 450 (137mBa from caesium): the total outflow from blood
      // kept, deposition on bone surfaces in proportion to that of the
      // element's own model at each age, the rest in proportion to the adult's.
      const ref = modelOf(elements[op.element], 'default');
      const RB = ref.entry;
      const rn = ref.ages.length;
      const rAt = (rates, a) => (rates.length === 1 ? rates[0] : rates[a]);
      const frac = (surf, a) => {
        const tot = ref.transfers.filter(([x]) => x === RB).reduce((s, t) => s + rAt(t[2], a), 0);
        const t = ref.transfers.find(([x, y]) => x === RB && y === surf);
        return t ? rAt(t[2], a) / tot : 0;
      };
      const B = blood();
      const outs = model.transfers.filter(([x]) => x === B);
      const R = outs.reduce((s, t) => s + t[2][t[2].length - 1], 0);
      const bone0 = outs.filter(([, y]) => op.surfaces.includes(y)).reduce((s, t) => s + t[2][t[2].length - 1], 0);
      // At the parent's reference ages: the adult's values from its adult age.
      const ages = ref.ages.slice();
      if (op.adultAge) ages[ages.length - 1] = op.adultAge;
      const boneAt = ages.map((_, a) => op.surfaces.map((sf) => {
        const t = outs.find(([, y]) => y === sf);
        return t ? t[2][t[2].length - 1] * frac(sf, a) / frac(sf, rn - 1) : 0;
      }));
      for (const t of model.transfers) {
        const last = t[2][t[2].length - 1];
        if (t[0] !== B) { t[2] = ages.map(() => last); continue; }
        const k = op.surfaces.indexOf(t[1]);
        t[2] = ages.map((_, a) => (k >= 0 ? boneAt[a][k]
          : last * (R - boneAt[a].reduce((s, x) => s + x, 0)) / (R - bone0)));
      }
      model.ages = ages;
    } else if (op.op === 'carve') {
      const B = blood();
      const from = op.from || [];
      const src = Array.from({ length: n }, (_, a) => from.reduce((s, f) => s + inflow(f)[a], 0));
      const srcA = src[n - 1];
      const sumOf = (names) => Array.from({ length: n }, (_, a) => names.reduce((s, f) => s + inflow(f)[a], 0));
      const total = (excl) => Array.from({ length: n }, (_, a) => model.transfers
        .filter(([x, y]) => x === B && !excl.includes(y)).reduce((s, t) => s + rateAt(t[2], a), 0));
      const added = new Array(n).fill(0);
      for (const it of op.add) {
        let rin;
        if (it.rate != null) rin = src.map((s) => it.rate * (srcA > 0 ? s / srcA : 1));
        else if (it.like) rin = inflow(it.like).map((x) => x * (it.factor ?? 1));
        else if (it.share != null) rin = sumOf(it.per || from).map((x) => x * it.share);
        else if (it.ofOutflow != null) rin = total(it.excluding || []).map((x) => x * it.ofOutflow);
        else throw new Error(`carve: ${it.name} has no inflow`);
        const out = it.out === 'same' || it.out == null
          ? (it.like ? toBlood(it.like) : toBlood(from[0]))
          : full(Array.isArray(it.out) ? it.out : [it.out]);
        model.compartments[it.name] = it.region;
        model.transfers.push([B, it.name, rin], [it.name, B, out]);
        rin.forEach((x, a) => { added[a] += x; });
      }
      for (const f of from) {
        const t = find(B, f);
        if (!t) continue;
        t[2] = full(t[2]).map((x, a) => (src[a] > 0 ? x * (1 - added[a] / src[a]) : x));
        if (t[2].some((x) => x < 0)) throw new Error(`carve: ${f} inflow below zero`);
      }
    } else throw new Error(`progeny op ${op.op}`);
  }
  if (spec.entry) model.entry = spec.entry;
  delete model.entryRespiratory;
  delete model.entryRespiratoryByState;
  delete model.entryFractions;
  model.label = `${el} formed in the body in ${spec.set} chains (OIR series)` + (spec.model ? '' : `: ${model.label || `${spec.base || el} model`}${spec.ops?.length ? ', modified' : ''}`);
  return model;
}

/** The rule for X produced at a place its model does not have. */
export function unidentifiedRule(spec, region, name, el) {
  const u = spec.unid || {};
  const pick = (v) => (v === undefined ? undefined : v);
  let r = pick(u.byName?.[`${el}:${name}`]) ?? pick(u.byName?.[name]) ?? pick(u.byRegion?.[region]);
  if (r === undefined) {
    if (region === 'Blood') r = u.blood ?? 1000;
    else if (region === 'T-bone-V' || region === 'C-bone-V') r = u.volume ?? 'turnover';
    else if (region === 'T-bone-S' || region === 'C-bone-S') r = u.surface ?? u.soft;
    else r = u.soft;
  }
  if (r === undefined || r === null) throw new Error(`progeny ${spec.set}: no rule for ${name} (${region})`);
  return r;
}

function clone(x) { return JSON.parse(JSON.stringify(x)); }
