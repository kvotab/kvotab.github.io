#!/usr/bin/env node
/* ==========================================================================
   THE REACTIVE-TRANSPORT COMPILER, AGAINST THINGS WITH KNOWN ANSWERS

   A reactive-transport code can be wrong in a way that still looks like
   chemistry, so every check here is against something independent: a closed
   solution, a conservation law, or a convergence rate that has to come out at
   a particular number.

       node resources/tests/rtm/test-model.js [--verbose]

   Exit status is 0 when every check passes.
   ========================================================================== */
'use strict';

const path = require('path');

const jsDir = path.join(__dirname, '..', '..', 'js');
require(path.join(jsDir, 'facsimile-model.js'));
const FacsimileODE = require(path.join(jsDir, 'facsimile-solver.js'));
const RtmModel = require(path.join(jsDir, 'rtm-model.js'));
const { RTM_DEFAULT_MODEL } = require(path.join(jsDir, 'rtm-default.js'));

const verbose = process.argv.includes('--verbose');
let checks = 0;
const failures = [];

function check(label, ok, detail) {
  checks++;
  const good = ok === true;
  console.log(`${good ? 'ok  ' : 'FAIL'}  ${label}${detail ? `: ${detail}` : ''}`);
  if (!good) failures.push(label);
}

function close(label, got, want, rtol, unit) {
  const rel = Math.abs(got - want) / Math.max(Math.abs(want), 1e-300);
  check(label, rel <= rtol, `${got.toExponential(6)} vs ${want.toExponential(6)}${unit || ''} `
    + `(${rel.toExponential(2)} relative, allowed ${rtol.toExponential(0)})`);
}

/** erfc, Abramowitz & Stegun 7.1.26: |error| < 1.5e-7, plenty here. */
function erfc(x) {
  const z = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * z);
  const e = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741
    + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-z * z);
  return x >= 0 ? e : 2 - e;
}

const run = (model, opts) => FacsimileODE.runModel(model, {
  solver: 'ndf', rtol: 1e-10, atol: 1e-18, ...opts,
});
const last = (r) => r.y[r.y.length - 1];

/* ======================================================================
   1. Chemistry, against a closed solution
   ====================================================================== */
console.log('\n--- chemistry ---');
{
  // A -> B -> C, the textbook consecutive first-order pair.
  const k1 = 0.5;
  const k2 = 0.2;
  const T = 10;
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = ${T}

<SPECIES>
A 1.0
B 0.0
C 0.0

<REACTIONS>
A => B, k = ${k1}
B => C, k = ${k2}
`);
  const y = last(run(m, { tend: T }));
  const A = Math.exp(-k1 * T);
  const B = (k1 / (k2 - k1)) * (Math.exp(-k1 * T) - Math.exp(-k2 * T));
  close('A -> B -> C reproduces A(t)', y[0], A, 1e-7);
  close('  and B(t)', y[1], B, 1e-7);
  close('  and C(t)', y[2], 1 - A - B, 1e-7);
}
{
  // Mass action must read the stoichiometric coefficient as an order:
  // 2A -> B has rate k[A]^2, so 1/A is linear in t with slope 2k.
  const k = 0.3;
  const T = 5;
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = ${T}

<SPECIES>
A 1.0
B 0.0

<REACTIONS>
2 A => B, k = ${k}
`);
  const y = last(run(m, { tend: T }));
  close('2A -> B is second order in A', y[0], 1 / (1 + 2 * k * T), 1e-7);
  close('  and B is half of what A lost', y[1], (1 - y[0]) / 2, 1e-9);
}
{
  // A rate law of the reader's own, with its own parameters.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
S 1.0
P 0.0

<REACTIONS>
S => P, r = vmax*[S]/(km + [S]), vmax = 2, km = 0.5
`);
  const y0 = m.initialState();
  const out = new Float64Array(2);
  m.rhs(0, y0, out);
  close('a Michaelis-Menten rate law is read as written', out[1], (2 * 1) / (0.5 + 1), 1e-12);
}
{
  // A source is a reaction with nothing on the left, a sink one with nothing
  // on the right; together they must reach source/sink.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 100

<SPECIES>
P 0

<REACTIONS>
=> P, k = 2.5
P => , k = 0.5
`);
  close('a source and a sink reach their steady state', last(run(m, { tend: 200 }))[0], 5, 1e-9);
}
{
  // Reversible mass action settles at kf/kb.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 50

<SPECIES>
A 1.0
B 0.0

<REACTIONS>
A <=> B, kf = 2.0, kb = 0.5
`);
  const y = last(run(m, { tend: 100 }));
  close('a reversible pair settles at kf/kb', y[1] / y[0], 4, 1e-7);
  close('  conserving A + B', y[0] + y[1], 1, 1e-10);
}
{
  // A fixed species drives the chemistry and never moves itself.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 10

<SPECIES>
W 55.0 fixed
A 1.0
B 0.0

<REACTIONS>
A + W => B + W, k = 0.01
`);
  const y = last(run(m, { tend: 10 }));
  // W is declared first, so the state is [W, A, B]: reading y[1] as B was
  // this test's own mistake, and it read A -- which was exactly right.
  const at = (name) => y[m.speciesNames.indexOf(name)];
  check('a fixed species is not consumed', at('W') === 55.0, `W = ${at('W')}`);
  close('  but still drives the rate', at('B'), 1 - Math.exp(-0.01 * 55 * 10), 1e-7);
  close('  and A decays at k[W]', at('A'), Math.exp(-0.01 * 55 * 10), 1e-7);
}

/* ======================================================================
   2. Transport, against closed solutions and conservation
   ====================================================================== */
console.log('\n--- transport ---');
{
  // Diffusion into a half-space: C = C0 erfc(x / 2 sqrt(Dt)). The error must
  // fall by four each time the cells are doubled -- second order -- which is
  // a much stronger statement than any single number being close.
  const D = 1e-9;
  const T = 1e5;
  const L = 0.1;
  const errs = [];
  for (const cells of [100, 200, 400]) {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${cells}
LENGTH = ${L}
DIFFUSION = 1
LEFT = dirichlet
RIGHT = neumann
TEND = ${T}

<SPECIES>
X 0.0 D=${D} left=1

<REACTIONS>
`);
    const y = last(run(m, { tend: T }));
    let worst = 0;
    for (let i = 0; i < m.cells; i++) {
      const exact = erfc(m.grid.centres[i] / (2 * Math.sqrt(D * T)));
      if (exact > 1e-3) worst = Math.max(worst, Math.abs(y[i] - exact) / exact);
    }
    errs.push(worst);
    if (verbose) console.log(`      ${cells} cells: ${worst.toExponential(3)}`);
  }
  const r1 = errs[0] / errs[1];
  const r2 = errs[1] / errs[2];
  check('diffusion matches erfc and converges at second order',
    r1 > 3.2 && r2 > 3.2, `error falls ${r1.toFixed(2)}x then ${r2.toFixed(2)}x when the cells double`);
}
{
  // Advection with dispersion: Ogata-Banks. Upwind differencing adds a
  // numerical dispersion of v*dx/2, so that is what it is compared against.
  const v = 1e-6;
  const D = 1e-8;
  const L = 0.2;
  const T = 1e5;
  const cells = 400;
  const dx = L / cells;
  const Deff = D + (v * dx) / 2;
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${cells}
LENGTH = ${L}
DIFFUSION = 1
ADVECTION = 1
VELOCITY = ${v}
LEFT = dirichlet
RIGHT = neumann
TEND = ${T}

<SPECIES>
X 0.0 D=${D} left=1

<REACTIONS>
`);
  const y = last(run(m, { tend: T, atol: 1e-14 }));
  const ob = (x) => 0.5 * (erfc((x - v * T) / (2 * Math.sqrt(Deff * T)))
    + Math.exp((v * x) / Deff) * erfc((x + v * T) / (2 * Math.sqrt(Deff * T))));
  let worst = 0;
  for (let i = 0; i < m.cells; i++) {
    const exact = ob(m.grid.centres[i]);
    if (exact > 0.02 && exact < 0.98) worst = Math.max(worst, Math.abs(y[i] - exact));
  }
  check('advection matches Ogata-Banks across the front', worst < 0.01,
    `worst absolute difference ${worst.toExponential(3)}`);
  /*
    And the front is in the right place. Against the ANALYTIC half-height, not
    against v*t: at x = v*t the Ogata-Banks solution is 0.586 here, not 0.5,
    because the second term is nowhere near negligible at this Peclet number.
    Comparing with v*t was this test's own mistake and failed a correct answer.
  */
  let lo = 0;
  let hi = L;
  for (let i = 0; i < 80; i++) { const mid = (lo + hi) / 2; if (ob(mid) > 0.5) lo = mid; else hi = mid; }
  const exactHalf = (lo + hi) / 2;
  let half = 0;
  for (let i = 0; i < m.cells - 1; i++) if (y[i] >= 0.5 && y[i + 1] < 0.5) half = m.grid.centres[i];
  check('  and the half-height is where Ogata-Banks puts it',
    Math.abs(half - exactHalf) < 1.5 * dx,
    `${half.toFixed(6)} m vs ${exactHalf.toFixed(6)} m, within ${(Math.abs(half - exactHalf) / dx).toFixed(2)} cells`);
}
{
  /*
    The third-type inlet and the free outlet -- Danckwerts' pair.

    A robin face prescribes the WHOLE flux through it as u*cb: the flow brings
    cb in, and nothing else crosses. A free face lets the flow take what it
    takes and puts no diffusion across. Together they make the column a closed
    account: whatever comes in at one end and leaves at the other is all that
    changes the mass in it. That is an identity, so it is checked as one,
    against round-off rather than against a tolerance.

    A dirichlet face is not that, and should not come out as though it were:
    it adds a diffusive flux D*(cb - C)/d on top of the flow, which is exactly
    the inlet over-prediction the third-type condition exists to avoid.
  */
  const V = 1e-6;
  const mk = (left, right) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 40
LENGTH = 1.0
DIFFUSION = 1
ADVECTION = 1
VELOCITY = ${V}
LEFT = ${left}
RIGHT = ${right}
TEND = 2e6

<SPECIES>
X 0.0 D=2e-7 left=1.0

<REACTIONS>
`);
  const balance = (m) => {
    const y = last(run(m, { tend: 2e6, rtol: 1e-10, atol: 1e-20 }));
    const f = new Float64Array(m.nspecies);
    m.rhs(0, y, f);
    let dM = 0;
    for (let i = 0; i < m.cells; i++) dM += f[i] * m.grid.width[i];
    const want = V * 1.0 - V * y[m.cells - 1];
    return Math.abs(dM - want) / Math.abs(want);
  };
  check('a robin inlet with a free outlet balances what goes in against what leaves',
    balance(mk('robin', 'free')) < 1e-12, balance(mk('robin', 'free')).toExponential(2));
  check('  and a dirichlet inlet does not, because it adds diffusion to the flow',
    balance(mk('dirichlet', 'neumann')) > 1e-2,
    `${(100 * balance(mk('dirichlet', 'neumann'))).toFixed(1)} % out`);
  /*
    As arithmetic, free and neumann are the same face: the advective outflow
    is applied at every cell whatever the far boundary says, so a Neumann
    outlet already lets the flow leave. They are separate words because they
    say different things and are wrong in different ways -- the warnings tell
    them apart -- and this is the check that the claim is true.
  */
  const a = last(run(mk('robin', 'free'), { tend: 2e6, rtol: 1e-10, atol: 1e-20 }));
  const b = last(run(mk('robin', 'neumann'), { tend: 2e6, rtol: 1e-10, atol: 1e-20 }));
  check('  and free and neumann are the same arithmetic at an outlet',
    a.every((v, i) => v === b[i]), 'every cell identical');
}
{
  /*
    The third-type inlet against its own closed solution: van Genuchten and
    Alves (1982), the flux-type entry to a semi-infinite column. Not at one
    grid -- the error has to fall by four each time the cells are doubled, or
    it is the formulation that is wrong rather than the resolution.
  */
  const V = 1e-6;
  const D = 2e-8;
  const T = 3e5;
  /*
    The file's erfc is Abramowitz & Stegun 7.1.26, whose error bound is
    ABSOLUTE: 1.5e-7 whatever the answer. That is fine everywhere else here and
    useless below, because the solution's third term multiplies erfc by
    exp(v*x/D), which reaches e^50 at the far end of this column -- an
    absolute error of 1e-7 becomes 1e14. This is the Numerical Recipes form,
    whose 1.2e-7 is a FRACTIONAL bound and so survives the tail.
  */
  const erfcRel = (x) => {
    const z = Math.abs(x);
    const t = 1 / (1 + 0.5 * z);
    const y = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196
      + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398
        + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? y : 2 - y;
  };
  const flux3 = (x, t, v, d) => {
    const A = 0.5 * erfcRel((x - v * t) / (2 * Math.sqrt(d * t)));
    const B = Math.sqrt((v * v * t) / (Math.PI * d)) * Math.exp(-((x - v * t) ** 2) / (4 * d * t));
    const e = (v * x) / d;
    const C = e > 700 ? 0
      : 0.5 * (1 + e + (v * v * t) / d) * Math.exp(e) * erfcRel((x + v * t) / (2 * Math.sqrt(d * t)));
    return A + B - C;
  };
  const errAt = (n, left, right) => {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${n}
LENGTH = 1
DIFFUSION = 1
ADVECTION = 1
VELOCITY = ${V}
LEFT = ${left}
RIGHT = ${right}
TEND = ${T}

<SPECIES>
X 0.0 D=${D} left=1.0

<REACTIONS>
`);
    const y = last(run(m, { tend: T, rtol: 1e-10, atol: 1e-16 }));
    // Upwind differencing adds v*dx/2 of dispersion, so that is the D the
    // scheme is actually solving with -- the same correction the Ogata-Banks
    // check above makes.
    const dEff = D + (V * (1 / n)) / 2;
    let worst = 0;
    for (let i = 0; i < n; i++) {
      const exact = flux3(m.grid.centres[i], T, V, dEff);
      if (exact > 1e-3) worst = Math.max(worst, Math.abs(y[i] - exact) / exact);
    }
    return worst;
  };
  const e400 = errAt(400, 'robin', 'free');
  const e800 = errAt(800, 'robin', 'free');
  check('a robin inlet matches the flux-type solution', e400 < 0.01, e400.toExponential(3));
  check('  and converges on it at second order', e800 > 0 && e400 / e800 > 3.4,
    `${e400.toExponential(3)} -> ${e800.toExponential(3)}, a factor of ${(e400 / e800).toFixed(2)}`);
  // The same comparison for a first-type inlet, which is solving a different
  // problem and must not come out looking like this one.
  const dir = errAt(400, 'dirichlet', 'neumann');
  check('  while a dirichlet inlet is a different problem and says so',
    dir > 0.1, `${(100 * dir).toFixed(0)} % away from the flux-type solution`);
}
{
  // The words, their aliases, and what the page says when a face is asked for
  // something the flow cannot give it.
  const mk = (left, right, adv) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 5
LENGTH = 1
DIFFUSION = 1
ADVECTION = ${adv}
VELOCITY = 1e-6
LEFT = ${left}
RIGHT = ${right}
TEND = 1

<SPECIES>
X 0 D=1e-9 left=1

<REACTIONS>
`);
  check('cauchy is robin and outflow is free',
    mk('cauchy', 'outflow', 1).settings.LEFT === 'robin'
    && mk('cauchy', 'outflow', 1).settings.RIGHT === 'free');
  check('a robin face with nothing flowing into it is called out',
    /robin/.test(mk('robin', 'free', 0).warnings.join(' '))
    && /nothing flows in/.test(mk('robin', 'free', 0).warnings.join(' ')),
    mk('robin', 'free', 0).warnings.join(' | ').slice(0, 80));
  check('  and a free face with no flow to carry anything out of it',
    /nothing to carry/.test(mk('dirichlet', 'free', 0).warnings.join(' ')),
    mk('dirichlet', 'free', 0).warnings.join(' | ').slice(0, 70));
  check('  and a free face the flow points into', 
    /points into the model/.test(mk('free', 'neumann', 1).warnings.join(' ')),
    mk('free', 'neumann', 1).warnings.join(' | ').slice(0, 70));
  check('neither a robin nor a dirichlet inlet moves the first cell from where it was put',
    mk('robin', 'free', 1).initialState()[0] === 0
    && mk('dirichlet', 'free', 1).initialState()[0] === 0,
    `robin ${mk('robin', 'free', 1).initialState()[0]}, dirichlet ${mk('dirichlet', 'free', 1).initialState()[0]}`);
  let message = '(no error)';
  try { mk('mixed', 'free', 1); } catch (e) { message = e.message; }
  check('and a word that is not a boundary is refused with the list',
    /must be one of/.test(message) && /robin/.test(message), message.slice(0, 80));
}
{
  // A closed box may neither create nor destroy, on either grid.
  for (const grid of ['linear', 'log']) {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 60
LENGTH = 1
GRID = ${grid}
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
X 0.0 D=1e-4

<REACTIONS>

<INITIAL>
X 0-9 1.0
`);
    const y0 = m.initialState();
    const mass = (y) => Array.from(y).reduce((a, b, i) => a + b * m.grid.width[i], 0);
    const before = mass(y0);
    const after = mass(last(run(m, { tend: 1e4, atol: 1e-18 })));
    check(`a closed box conserves mass on a ${grid} grid`,
      Math.abs(after - before) / before < 1e-12,
      `${(Math.abs(after - before) / before).toExponential(2)} relative change`);
  }
}
{
  // Everything relaxes to the mean, which is the only steady state a closed
  // box with no chemistry has.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 40
LENGTH = 1
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
X 0.0 D=1e-3

<REACTIONS>

<INITIAL>
X 0-19 2.0
`);
  const y = last(run(m, { tend: 1e5 }));
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of y) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  check('a closed box relaxes flat to the mean',
    Math.abs(lo - 1) < 1e-9 && Math.abs(hi - 1) < 1e-9,
    `between ${lo.toFixed(12)} and ${hi.toFixed(12)}, expected 1`);
}
{
  // A species with no D does not move, however long it is left.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 1
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
M 0.0 D=1e-3
S 0.0

<REACTIONS>

<INITIAL>
M 0-4 1.0
S 0-4 1.0
`);
  const y = last(run(m, { tend: 1e5 }));
  const at = (cell, s) => y[cell * 2 + s];
  check('a species with no diffusion coefficient stays put',
    at(0, 1) === 1 && at(19, 1) === 0, `S is ${at(0, 1)} at the left and ${at(19, 1)} at the right`);
  check('  while one with a coefficient spreads', Math.abs(at(19, 0) - 0.25) < 1e-6,
    `M reached ${at(19, 0).toFixed(9)}, expected the mean 0.25`);
}

/* ======================================================================
   1b. The functions an expression may use
   ====================================================================== */
console.log('\n--- functions ---');
{
  // Every function the Help lists, each with a value that is only right if the
  // function is the one it claims to be, and each differentiated exactly.
  const cases = [
    ['exp([A])', Math.exp(2)],
    ['log([A])', Math.log(2)],
    ['ln([A])', Math.log(2)],
    ['log10([A])', Math.log10(2)],
    ['sqrt([A])', Math.SQRT2],
    ['abs(0-[A])', 2],
    ['sign([A]-3)', -1],
    ['step([A]-1)', 1],
    ['step([A]-3)', 0],
    ['ramp([A]-1.5)', 0.5],
    ['ramp([A]-3)', 0],
    ['[A]^3', 8],
    ['[A]**3', 8],
    ['2.5E0*[A]', 5],
    ['2.5e0*[A]', 5],
  ];
  for (const [law, want] of cases) {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
A 2.0
B 0.0

<REACTIONS>
A => B, r = ${law}
`);
    const out = new Float64Array(m.nspecies);
    m.rhs(0, m.initialState(), out);
    const bad = RtmModel.verifyJacobian(m, 0, Float64Array.of(2.0, 0.5)).discrepancies.length;
    check(`${law} gives ${want} and differentiates exactly`,
      Math.abs(out[1] - want) <= 1e-12 * Math.max(Math.abs(want), 1) && bad === 0,
      `rate ${out[1]}, ${bad} Jacobian discrepancies`);
  }
}
{
  // The three that are refused in a rate law, each for its own reason, and
  // each of which still works where nothing is differentiated.
  const inLaw = (law) => {
    try {
      RtmModel.compile(`<SETTINGS>\nMODE=batch\n<SPECIES>\nA 2\n<REACTIONS>\nA => , r = ${law}\n`);
    } catch (e) { return e.message; }
    return '(no error)';
  };
  check('min in a rate law is refused for jumping', /derivative jumps/.test(inLaw('min([A],1)')));
  check('max in a rate law is refused for jumping', /derivative jumps/.test(inLaw('max([A],1)')));
  check('pow in a rate law is refused for needing a logarithm',
    /logarithm of the base/.test(inLaw('pow([A],2)')));
  check('  and is told what to write instead', /\[A\]\^2/.test(inLaw('pow([A],2)')));
  check('a function that does not exist says so',
    /not a function this page knows/.test(inLaw('tanh([A])')));
  check('and an exponent that depends on a concentration is refused',
    /may not depend on a concentration/.test(inLaw('[A]^[A]')));

  // All three in <PARAMETERS>, where they are worked out once.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 1
DIFFUSION = 0
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
A 0

<PARAMETERS>
V all min(1+i, 2) + max(0.5, 0) + pow(2, i)

<REACTIONS>
=> A, k = V
`);
  const out = new Float64Array(m.nspecies);
  m.rhs(0, m.initialState(), out);
  const want = [0, 1, 2, 3].map((i) => Math.min(1 + i, 2) + 0.5 + 2 ** i);
  check('min, max and pow all work in <PARAMETERS>',
    out.every((v, i) => Math.abs(v - want[i]) < 1e-15),
    `${Array.from(out).join(', ')} against ${want.join(', ')}`);
}

/* ======================================================================
   2b. Parameters that vary from cell to cell
   ====================================================================== */
console.log('\n--- per-cell parameters ---');
{
  // The case this exists for: a dose rate that dies away from a surface.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 1e-4
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
P 0 D=1e-9

<PARAMETERS>
DOSE all 1.0*exp(-x/3.0e-5)

<REACTIONS>
=> P, k = G*DOSE, G = 2.0
`);
  const out = new Float64Array(m.nspecies);
  m.rhs(0, m.initialState(), out);
  let worst = 0;
  for (let i = 0; i < m.cells; i++) {
    const want = 2.0 * Math.exp(-m.grid.centres[i] / 3.0e-5);
    worst = Math.max(worst, Math.abs(out[i] - want) / want);
  }
  check('a parameter may be an expression in x, the cell centre', worst < 1e-14,
    `worst relative difference from the analytic profile ${worst.toExponential(2)}`);
  check('  and the Jacobian is still exact',
    RtmModel.verifyJacobian(m, 0, m.initialState()).discrepancies.length === 0);
}
{
  // A later line overrides an earlier one, and i is the cell index.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 5
LENGTH = 1
DIFFUSION = 0
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
P 0

<PARAMETERS>
A all 10*i
A 2   99

<REACTIONS>
=> P, k = A
`);
  const out = new Float64Array(m.nspecies);
  m.rhs(0, m.initialState(), out);
  check('a cell range overrides the value set for all of them',
    Array.from(out).join(',') === '0,10,99,30,40', Array.from(out).join(','));
}
{
  let message = '(no error)';
  try {
    RtmModel.compile('<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<REACTIONS>\nA => , k = NOPE\n');
  } catch (e) { message = e.message; }
  check('an unknown name in a rate law is still refused', /not a parameter/.test(message),
    message.slice(0, 80));
}

/* ======================================================================
   2c. The mass matrix
   ====================================================================== */
console.log('\n--- the mass matrix ---');
{
  // R dC/dt = -kC has the solution exp(-kt/R): retardation slows everything
  // on the right-hand side, reactions included.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 10

<SPECIES>
A 1.0 R=2.5

<REACTIONS>
A => , k = 0.4
`);
  // rtol here is the integrator's, not the model's: at the suite's usual 1e-10
  // this lands 1.9e-9 out, which is the NDF's own accumulated error.
  close('a retardation factor slows a decay to exp(-kt/R)',
    last(run(m, { tend: 10, rtol: 1e-12 }))[0], Math.exp((-0.4 * 10) / 2.5), 1e-9);
  check('  and the Jacobian is scaled with it',
    RtmModel.verifyJacobian(m, 0, Float64Array.of(0.6)).discrepancies.length === 0);
}
{
  // And it slows transport the same way: R dC/dt = D C'' is diffusion at D/R.
  const D = 4e-9;
  const R = 4;
  const T = 1e5;
  const L = 0.1;
  const cells = 400;
  const mk = (extra) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${cells}
LENGTH = ${L}
DIFFUSION = 1
LEFT = dirichlet
RIGHT = neumann
TEND = ${T}

<SPECIES>
X 0.0 D=${D} left=1${extra}

<REACTIONS>
`);
  const y = last(run(mk(`  R=${R}`), { tend: T }));
  const centres = mk('').grid.centres;
  let worst = 0;
  for (let i = 0; i < cells; i++) {
    const exact = erfc(centres[i] / (2 * Math.sqrt((D / R) * T)));
    if (exact > 1e-3) worst = Math.max(worst, Math.abs(y[i] - exact) / exact);
  }
  check('a retardation factor turns diffusion at D into diffusion at D/R',
    worst < 5e-3, `worst relative error against erfc with D/R: ${worst.toExponential(3)}`);
}
{
  // It may come from a parameter, which is how a porosity varies down a column.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 1
DIFFUSION = 0
LEFT = neumann
RIGHT = neumann
TEND = 1

<SPECIES>
A 1.0 R=POR

<PARAMETERS>
POR all 1+i

<REACTIONS>
A => , k = 1
`);
  const out = new Float64Array(m.nspecies);
  m.rhs(0, m.initialState(), out);
  const want = [-1, -0.5, -1 / 3, -0.25];
  check('the mass coefficient may be a per-cell parameter',
    out.every((v, i) => Math.abs(v - want[i]) < 1e-15), Array.from(out).map((v) => v.toFixed(6)).join(', '));
}
{
  let message = '(no error)';
  try {
    RtmModel.compile('<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1 R=0\n<REACTIONS>\nA => , k=1\n');
  } catch (e) { message = e.message; }
  check('a zero mass is refused rather than silently made algebraic',
    /greater than zero/.test(message) && /EQUILIBRIUM/.test(message), message.slice(0, 90));
}

/* ======================================================================
   2d. Equilibrium and speciation
   ====================================================================== */
console.log('\n--- equilibrium and speciation ---');
{
  // Water autoprotolysis from a badly wrong start.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
H+   1e-3
OH-  1e-3

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
`);
  check('the conserved total is found from the stoichiometry alone',
    m.conservation.length === 1 && Array.from(m.conservation[0]).join(',') === '-1,1',
    m.conservation.map((v) => Array.from(v).join(',')).join(' | '));
  const r = RtmModel.speciate(m);
  close('speciation reaches Kw', r.y[0] * r.y[1], 1e-14, 1e-10);
  close('  with H+ = OH- when it started balanced', r.y[0], 1e-7, 1e-9);
  check('  conserving the charge difference', Math.abs((r.y[0] - r.y[1]) - 0) < 1e-20,
    `H+ - OH- = ${(r.y[0] - r.y[1]).toExponential(2)}`);
  check('  and converging', r.cells[0].converged, `${r.cells[0].iterations} iterations`);
}
{
  // Three coupled equilibria: a carbonate system, where no hand-written start
  // is right and the totals must survive the rearrangement.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = 1

<SPECIES>
H+      1e-7
OH-     1e-7
CO2     1e-3
HCO3-   1e-5
CO3-2   1e-9

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
CO2 <=> H+ + HCO3-, logK = -6.35
HCO3- <=> H+ + CO3-2, logK = -10.33
`);
  const y = m.initialState();
  const nm = m.speciesNames;
  const at = (s) => y[nm.indexOf(s)];
  close('a carbonate system satisfies Kw', at('H+') * at('OH-'), 1e-14, 1e-8);
  close('  and K1', (at('H+') * at('HCO3-')) / at('CO2'), 10 ** -6.35, 1e-8);
  close('  and K2', (at('H+') * at('CO3-2')) / at('HCO3-'), 10 ** -10.33, 1e-8);
  close('  conserving total carbon', at('CO2') + at('HCO3-') + at('CO3-2'), 1e-3 + 1e-5 + 1e-9, 1e-9);
  close('  and conserving charge',
    at('H+') - at('OH-') - at('HCO3-') - 2 * at('CO3-2'), 1e-7 - 1e-7 - 1e-5 - 2e-9, 1e-7);
  check('  EQUILIBRATE did it at compile time', !!m.speciated, `${m.speciated && m.speciated.length} cells`);
}
{
  // Given a kf, the equilibrium is also held while the run goes on.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
H+   1e-3
OH-  1e-3
X    1e-4

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14, kf = 1.4e-3

<REACTIONS>
X => , k = 1.0
`);
  check('kf turns an equilibrium into a fast reversible pair', m.nchannels === 3, `${m.nchannels} channels`);
  const y = last(run(m, { tend: 10, atol: 1e-24, nonNegative: true }));
  close('  and the run holds the product at K', y[0] * y[1], 1e-14, 1e-6);
  close('  while the rest of the chemistry is untouched', y[2], 1e-4 * Math.exp(-10), 1e-6);
  check('  and the Jacobian covers the pair',
    RtmModel.verifyJacobian(m, 0, m.initialState()).discrepancies.length === 0);
}
{
  // A species no equilibrium touches takes no part, which matters because it
  // may be zero: ln 0 is where a speciation that included it went singular.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = 1

<SPECIES>
H+   1e-3
OH-  1e-3
P    0
Q    3.0

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14

<REACTIONS>
=> P, k = 1.0
`);
  check('only the species the equilibria touch take part',
    m.conservation.length === 1 && Array.from(m.conservation[0]).join(',') === '-1,1,0,0',
    m.conservation.map((v) => Array.from(v).join(',')).join(' | '));
  const y = m.initialState();
  close('  and they still speciate', y[0], 1e-7, 1e-9);
  check('  while a species that starts at zero is left at zero', y[2] === 0, String(y[2]));
  check('  and one that starts elsewhere is left there', y[3] === 3.0, String(y[3]));
}
{
  // Speciation in every cell of a transport model, not just the first.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 6
LENGTH = 1
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 1
EQUILIBRATE = 1

<SPECIES>
H+   1e-3 D=1e-9
OH-  1e-3 D=1e-9

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14

<INITIAL>
H+  0-2  1e-2
`);
  const y = m.initialState();
  let worst = 0;
  for (let c = 0; c < 6; c++) worst = Math.max(worst, Math.abs(y[c * 2] * y[c * 2 + 1] - 1e-14) / 1e-14);
  check('every cell is speciated, not just the first', worst < 1e-8,
    `worst departure from Kw across the cells ${worst.toExponential(2)}`);
  check('  and the cells that started differently end differently',
    Math.abs(y[0] - y[8]) / y[0] > 0.1, `cell 0 H+ = ${y[0].toExponential(3)}, cell 4 = ${y[8].toExponential(3)}`);
}
{
  const bad = [
    ['an equilibrium with no K', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\nB 1\n<EQUILIBRIUM>\nA <=> B\n', /needs K/],
    ['an equilibrium naming an unknown species', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<EQUILIBRIUM>\nA <=> Z, K = 1\n', /not in <SPECIES>/],
  ];
  for (const [label, text, pattern] of bad) {
    let message = '(no error)';
    try { RtmModel.compile(text); } catch (e) { message = e.message; }
    check(`${label} is refused`, pattern.test(message), message.slice(0, 80));
  }
}

/* ======================================================================
   2f. What "fixed" means
   ====================================================================== */
console.log('\n--- fixed species ---');
{
  // A fixed species drives the chemistry without being touched by it. The
  // statement that matters is that its row is exactly zero -- not small.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 5
LENGTH = 1e-4
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1e-7
LEFT = dirichlet
RIGHT = neumann
TEND = 1e4

<SPECIES>
W  10.0  fixed  D=1e-9  left=99.0
A  1.0          D=1e-9  left=1.0

<REACTIONS>
W + A => , k = 5.0
=> W, k = 1.0
`);
  const y = m.initialState();
  const out = new Float64Array(m.nspecies);
  m.rhs(0, y, out);
  let worstRhs = 0;
  for (let c = 0; c < 5; c++) worstRhs = Math.max(worstRhs, Math.abs(out[c * 2]));
  check('a fixed species has an exactly zero row, source and boundary and all',
    worstRhs === 0, `largest |dW/dt| ${worstRhs}`);
  check('  and it is still consumed on paper, so A does move', out[1] < 0, String(out[1]));

  const V = new Float64Array(m.nnz);
  m.jac(0, y, V);
  let worstJac = 0;
  for (let col = 0; col < m.pattern.n; col++) {
    for (let k = m.pattern.colPtr[col]; k < m.pattern.colPtr[col + 1]; k++) {
      if (m.pattern.rowIdx[k] % 2 === 0) worstJac = Math.max(worstJac, Math.abs(V[k]));
    }
  }
  check('  and its whole Jacobian row is zero too', worstJac === 0, `largest entry ${worstJac}`);
  check('  while the column is not: A depends on it',
    RtmModel.verifyJacobian(m, 0, y).discrepancies.length === 0);
  check('  and it does not move even with a D and a Dirichlet face',
    Array.from(last(run(m, { tend: 1e4 }))).filter((_, i) => i % 2 === 0)
      .every((v) => v === 10.0),
    Array.from(last(run(m, { tend: 1e4 }))).filter((_, i) => i % 2 === 0).join(', '));
}
{
  // A Dirichlet face is a boundary condition and nothing more: it must not
  // change what the cells start at. It once seeded the cell touching it with
  // the face value, which silently overrode the <SPECIES> line and made the
  // Crank benchmark (zero everywhere at t = 0) three times less accurate.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 1e-4
DIFFUSION = 1
LEFT = dirichlet
RIGHT = neumann
TEND = 1

<SPECIES>
W  10.0  fixed  D=1e-9  left=99.0
A  1.0          D=1e-9  left=7.0
B  1.0          D=1e-9  left=7.0

<INITIAL>
A  0  3.0

<REACTIONS>
`);
  const y = m.initialState();
  const at = (cell, name) => y[cell * 3 + m.speciesNames.indexOf(name)];
  check('a Dirichlet face leaves the cell that touches it at its stated start',
    at(0, 'B') === 1.0, `B in cell 0 is ${at(0, 'B')}, not the 1.0 on its line`);
  check('  a fixed species keeps what it was given', at(0, 'W') === 10.0, String(at(0, 'W')));
  check('  and <INITIAL> still sets that cell', at(0, 'A') === 3.0, String(at(0, 'A')));
  check('  while the cells behind it are untouched',
    at(1, 'A') === 1.0 && at(1, 'B') === 1.0 && at(3, 'B') === 1.0,
    `${at(1, 'A')}, ${at(1, 'B')}, ${at(3, 'B')}`);
}
{
  // Held inside an equilibrium: a buffered pH. The relation still has to hold,
  // but charge stops being conserved -- the outside supplies the difference --
  // so the count of conserved totals must drop with it.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = 1

<SPECIES>
H+   1e-3  fixed
OH-  1e-3

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
`);
  check('fixing one species of an equilibrium leaves nothing conserved',
    m.conservation.length === 0, `${m.conservation.length} totals`);
  const y = m.initialState();
  check('a fixed species is not moved by the speciation', y[0] === 1e-3, y[0].toExponential(6));
  close('  and the free one goes to K over it', y[1], 1e-11, 1e-9);
  close('  so the relation still holds', y[0] * y[1], 1e-14, 1e-9);
}
{
  // Fixing both sides of a relation cannot be satisfied, and says so rather
  // than returning something that quietly does not hold.
  let message = '(no error)';
  try {
    RtmModel.compile(`
<SETTINGS>
MODE = batch
EQUILIBRATE = 1

<SPECIES>
H+   1e-3  fixed
OH-  1e-3  fixed

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
`);
  } catch (e) { message = e.message; }
  check('fixing every species of an equilibrium is refused',
    /free to move/.test(message) && /fixed/.test(message), message.slice(0, 110));
}

/* ======================================================================
   2g. Dual porosity: a rock matrix beside the fracture
   ====================================================================== */
console.log('\n--- dual porosity ---');
/*
  Two independent references. First SKB's own implementation of the
  formulation in TR-19-06 -- FARFCOMP -- whose layer thicknesses, rates and
  release curves were dumped once into farf-fixture.json (via kompartment,
  which holds itself to the same file). Then Neretnieks' closed solution for a
  fracture beside a semi-infinite matrix, which knows nothing of either code.
*/
const FARF = JSON.parse(require('fs').readFileSync(path.join(__dirname, 'farf-fixture.json'), 'utf8'));

/**
 * A FARFCOMP case as model text: years throughout, L = tw so that v = 1, and
 * FARFCOMP's own layers, which are no longer the page's default.
 */
function farfText(c, extra = {}) {
  const S = c.settings || c;
  const tw = S.tw;
  const aw = S.f / tw;
  const Rm = S.eps_m + S.rho_m * (S.kd_m[0] || 0);
  const Rf = 1 + (S.kd_f[0] || 0) * aw;
  const dz0 = tw / S.n_f;
  const lam = c.half_life ? Math.LN2 / c.half_life[0] : 0;
  return `
<SETTINGS>
MODE = transport
CELLS = ${S.n_f}
LENGTH = ${tw}
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1
LEFT = robin
RIGHT = free
PECLET = ${S.pe}
MATRIX_CELLS = ${S.n_m}
MATRIX_GRID = reference
MATRIX_DEPTH = ${S.pen_dep}
MATRIX_FIRST = ${S.pen_dep_0 == null ? 0 : S.pen_dep_0}
MATRIX_POROSITY = ${S.eps_m}
WETTED_SURFACE = ${aw}
TEND = ${c.tf || 1}

<SPECIES>
X 0 D=0 left=0 R=${Rf} Dm=${S.de_m[0]} Rm=${Rm}

<PARAMETERS>
S all 0
S 0 ${1 / dz0} fracture

<REACTIONS>
=> X, k = S
${lam ? `X => , k = ${lam}, on = ${extra.on || 'inventory'}` : ''}
`;
}
{
  // The geometry and every rate, against FARFCOMP's own intermediate values.
  // The reference's rates carry 1/R_f on the fracture side and 1/R_m on the
  // matrix side; here those come in through the mass matrix, so they are put
  // back to compare the raw coefficients.
  let worstD = 0;
  let worstRate = 0;
  for (const c of FARF.jacobians) {
    const m = RtmModel.compile(farfText(c));
    const E = new Map(c.entries.map(([r, col, v]) => [`${r},${col}`, v]));
    const cell = (k, j) => k * (c.n_m + 1) + j;
    const fdf = c.f_df[0];
    const rm = c.r_m[0];
    for (let j = 0; j < c.n_m; j++) worstD = Math.max(worstD, Math.abs(m.matrix.d[j] - c.d[j]) / c.d[j]);
    const sp = m.dual.species[0];
    const rel = (a, b) => Math.abs(a - b) / Math.abs(b);
    worstRate = Math.max(worstRate,
      rel(m.dual.advF * fdf, c.adv_f[0]),
      c.d_f[0] > 0 ? rel(m.dual.dF * fdf, c.d_f[0]) : Math.abs(m.dual.dF),
      rel(sp.diffFM1 * fdf, E.get(`${cell(0, 1)},${cell(0, 0)}`)),
      rel(sp.diffM1F / rm, E.get(`${cell(0, 0)},${cell(0, 1)}`)));
    for (let j = 0; j < c.n_m - 1; j++) {
      worstRate = Math.max(worstRate,
        rel(sp.diffMMF[j] / rm, E.get(`${cell(0, j + 2)},${cell(0, j + 1)}`)),
        rel(sp.diffMMB[j] / rm, E.get(`${cell(0, j + 1)},${cell(0, j + 2)}`)));
    }
  }
  check(`the matrix layers are FARFCOMP's, bit for bit, in ${FARF.jacobians.length} cases`,
    worstD < 1e-14, `worst ${worstD.toExponential(1)} relative`);
  check('  and so is every rate: advection, dispersion, wall exchange, layer to layer',
    worstRate < 1e-14, `worst ${worstRate.toExponential(1)} relative`);
  // The deep case: twenty layers from 4e-8 m to 8 m, and a Jacobian whose rows
  // span sixteen orders. The analytic one must still be right, and the check
  // must still be able to say so.
  const deep = RtmModel.compile(farfText(FARF.jacobians.find((c) => c.name === 'deep')));
  const v = RtmModel.verifyJacobian(deep, 0, Float64Array.from(deep.initialState(), () => 1e-3));
  check('  the twenty-layer Jacobian agrees with a central difference',
    v.discrepancies.length === 0, `${v.discrepancies.length} of ${v.checked} disagree, ${v.unresolvable} below the floor`);
}
{
  /*
    Release curves: a unit release per year into the first cell, and what
    comes out of the last, against FARFCOMP's own solution at rtol 1e-9. Read
    at the reference's times with a cubic Hermite between accepted steps --
    a straight line across a step on the rising front is worth 2e-5, which
    is more than either integration's error.
  */
  const hermite = (m, r, idx, want) => {
    let hi = 1;
    while (hi < r.t.length - 1 && r.t[hi] < want) hi++;
    const lo = hi - 1;
    const H = r.t[hi] - r.t[lo];
    const f = H > 0 ? (want - r.t[lo]) / H : 0;
    const fl = new Float64Array(m.nspecies);
    const fh = new Float64Array(m.nspecies);
    m.rhs(r.t[lo], r.y[lo], fl);
    m.rhs(r.t[hi], r.y[hi], fh);
    const y0 = r.y[lo][idx];
    const y1 = r.y[hi][idx];
    const d0 = fl[idx] * H;
    const d1 = fh[idx] * H;
    return (2 * f ** 3 - 3 * f ** 2 + 1) * y0 + (f ** 3 - 2 * f ** 2 + f) * d0
      + (-2 * f ** 3 + 3 * f ** 2) * y1 + (f ** 3 - f ** 2) * d1;
  };
  const release = (c, extra) => {
    const m = RtmModel.compile(farfText(c, extra));
    const r = run(m, { tend: c.tf, rtol: 1e-9, atol: 1e-20, maxPoints: 1e9 });
    const idx = m.cellOf(m.fracture - 1, 0) * m.speciesNames.length;
    let worst = 0;
    for (let k = 0; k < c.t.length; k++) worst = Math.max(worst, Math.abs(hermite(m, r, idx, c.t[k]) - c.release[0][k]));
    return worst;
  };
  for (const c of FARF.releases) {
    check(`the release of case "${c.name}" is FARFCOMP's to 1e-7 over ${c.t.length} times`,
      release(c) < 1e-7, `worst ${release(c).toExponential(2)}`);
  }
  // Decay acts on everything in a cell, sorbed included. Told it acts on the
  // water alone, the sorbing case comes out wrong by more than half -- the
  // difference `on = inventory` exists to make.
  const sorbing = FARF.releases.find((c) => c.name === 'sorbing');
  const wrong = release(sorbing, { on: 'water' });
  check('  and decay written as a rate on the water alone is wrong by half',
    wrong > 0.3, `worst ${wrong.toExponential(2)}`);
}
{
  // Neretnieks (1980): a step at the inlet, no dispersion, no fracture
  // sorption, a matrix deep enough to be infinite over the run:
  //   c/c0 = erfc( aw*tw*sqrt(De*Rm) / (2*sqrt(t - tw)) )   for t > tw.
  // Nothing of FARFCOMP in it. The upwind grid disperses on its own, by less
  // as the cells are doubled, so the error has to fall -- at first order,
  // since that is the order of what is left.
  const tw = 20;
  const aw = 500;
  const De = 1e-3;
  const Rm = 0.0018;
  const T = 120;
  const exact = (t) => (t > tw ? erfc((aw * tw * Math.sqrt(De * Rm)) / (2 * Math.sqrt(t - tw))) : 0);
  const errAt = (nf) => {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${nf}
LENGTH = ${tw}
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1
LEFT = robin
RIGHT = free
MATRIX_CELLS = 80
MATRIX_DEPTH = 60
MATRIX_FIRST = 1e-6
MATRIX_POROSITY = ${Rm}
WETTED_SURFACE = ${aw}
TEND = ${T}

<SPECIES>
X 0 D=0 left=1 Dm=${De}

<REACTIONS>
`);
    const r = run(m, { tend: T, rtol: 1e-8, atol: 1e-14, maxPoints: 1e9 });
    const idx = m.cellOf(nf - 1, 0);
    let worst = 0;
    for (let i = 0; i < r.t.length; i++) {
      const t = r.t[i];
      if (t < tw * 1.5) continue;
      worst = Math.max(worst, Math.abs(r.y[i][idx] - exact(t)));
    }
    return worst;
  };
  // The matrix is made fine enough -- eighty layers from a micrometre -- that
  // what is left is the fracture's own upwind dispersion, which is first
  // order: the error should roughly halve per doubling. With a coarser
  // matrix it levelled off at 1e-2 whatever the fracture did, which is how
  // this check found out which grid it was measuring.
  const e50 = errAt(50);
  const e100 = errAt(100);
  const e200 = errAt(200);
  check('the breakthrough follows Neretnieks\' closed solution', e200 < 0.01, `worst ${e200.toExponential(2)} at 200 cells`);
  check('  and converges on it at first order as the fracture is refined',
    e50 / e100 > 1.6 && e100 / e200 > 1.6,
    `${e50.toExponential(2)} -> ${e100.toExponential(2)} -> ${e200.toExponential(2)}`);
}
{
  // A closed dual-porosity box: no flow, no faces open, no reactions. What
  // the fracture loses the rock must hold, weighted by what each holds per
  // unit of wall -- 1/aw of water for the fracture, Rm*d_j of capacity for
  // layer j -- to round-off.
  const aw = 200;
  const Rm = 0.05;
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 3
LENGTH = 1
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
MATRIX_CELLS = 6
MATRIX_DEPTH = 0.5
MATRIX_POROSITY = 0.02
WETTED_SURFACE = ${aw}
TEND = 1e9

<SPECIES>
X 1.0 D=1e-9 Dm=1e-10 Rm=${Rm}

<INITIAL>
X all 0 matrix

<REACTIONS>
`);
  const total = (y) => {
    let sum = 0;
    for (let i = 0; i < m.fracture; i++) {
      sum += y[m.cellOf(i, 0)] * m.grid.width[i] / aw;
      for (let j = 1; j <= m.matrix.n; j++) sum += y[m.cellOf(i, j)] * m.grid.width[i] * Rm * m.matrix.d[j - 1];
    }
    return sum;
  };
  const r = run(m, { tend: 1e9, rtol: 1e-10, atol: 1e-20 });
  const before = total(m.initialState());
  const after = total(last(r));
  const yEnd = last(r);
  check('a closed dual-porosity box conserves mass to round-off',
    Math.abs(after - before) / before < 1e-11, `${((after - before) / before).toExponential(2)} relative`);
  // The rock's capacity per unit wall is Rm*depth = 0.025 against the water's
  // 1/aw = 0.005, so at equilibrium the water keeps a sixth of what it had.
  const share = (1 / aw) / (1 / aw + Rm * m.matrix.depth);
  close('  and shares it out by capacity: the fracture keeps 1/aw of the whole',
    yEnd[m.cellOf(0, 0)], share, 2e-3);
  close('  the deepest layer the same', yEnd[m.cellOf(0, m.matrix.n)], share, 2e-3);
}
{
  // A reaction in the rock acts on its water: a first-order sink in a matrix
  // that nothing enters or leaves runs at eps_m*k/Rm, exactly. And told it is
  // a rate on the inventory, at k.
  const eps = 0.01;
  const Rm = 0.5;
  const k = 0.3;
  const mk = (on) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 1
DIFFUSION = 0
LEFT = neumann
RIGHT = neumann
MATRIX_CELLS = 2
MATRIX_DEPTH = 1
MATRIX_POROSITY = ${eps}
WETTED_SURFACE = 10
TEND = 2

<SPECIES>
X 1.0 Rm=${Rm}

<REACTIONS>
X => , k = ${k}, on = ${on}
`);
  // No D and no Dm: every cell, fracture or rock, is on its own.
  const yw = last(run(mk('water'), { tend: 2, rtol: 1e-12 }));
  const yi = last(run(mk('inventory'), { tend: 2, rtol: 1e-12 }));
  close('a first-order loss in the rock water runs at eps*k/Rm', yw[1], Math.exp(-eps * k * 2 / Rm), 1e-9);
  close('  and in the fracture, at k', yw[0], Math.exp(-k * 2), 1e-9);
  close('  while a loss of the inventory runs at k in the rock too', yi[1], Math.exp(-k * 2), 1e-9);
}
{
  // Decay on the inventory makes the daughter of the parent's whole
  // inventory, which then takes up its own share between water and rock: a
  // parent that hardly sorbs and a daughter that sorbs hard, in a rock cell
  // nothing leaves, keep their atoms, Rm_p*C_p + Rm_d*C_d, to round-off.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 1
DIFFUSION = 0
LEFT = neumann
RIGHT = neumann
MATRIX_CELLS = 1
MATRIX_DEPTH = 1
MATRIX_POROSITY = 0.01
WETTED_SURFACE = 10
TEND = 20
<SPECIES>
P 1 R=2 Rm=0.5
D 0 R=7 Rm=100
<REACTIONS>
P => D, k = 0.1, on = inventory
`);
  const y = last(run(m, { tend: 20, rtol: 1e-12, atol: 1e-20 }));
  const rock = m.cellOf(0, 1) * 2;
  const frac = m.cellOf(0, 0) * 2;
  close('a daughter is born of the parent’s whole inventory: atoms kept in the rock',
    0.5 * y[rock] + 100 * y[rock + 1], 0.5, 1e-11);
  close('  and in the fracture, with its own R there', 2 * y[frac] + 7 * y[frac + 1], 2, 1e-11);
  let message = '(no error)';
  try {
    RtmModel.compile('<SETTINGS>\nMODE = batch\n<SPECIES>\nA 1\nB 1\nC 0\n<REACTIONS>\nA + B => C, k = 1, on = inventory\n');
  } catch (e) { message = e.message; }
  check('  and a share of the inventory of two species at once is refused', /more than one/.test(message), message.slice(0, 70));
}
{
  // What a matrix needs, what "matrix" and "fracture" address, and what is warned about.
  const base = (extra) => `
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 1
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1e-6
LEFT = robin
RIGHT = free
${extra}
TEND = 1

<SPECIES>
X 0 D=1e-9 left=1 Dm=1e-10

<REACTIONS>
`;
  const refuse = (extra) => { try { RtmModel.compile(base(extra)); } catch (e) { return e.message; } return '(no error)'; };
  check('a matrix without a depth is refused', /MATRIX_DEPTH/.test(refuse('MATRIX_CELLS = 3\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 100')));
  check('  without a porosity', /MATRIX_POROSITY/.test(refuse('MATRIX_CELLS = 3\nMATRIX_DEPTH = 1\nWETTED_SURFACE = 100')));
  check('  without the wall area', /WETTED_SURFACE|APERTURE/.test(refuse('MATRIX_CELLS = 3\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01')));
  let batchMsg = '(no error)';
  try {
    RtmModel.compile(base('MATRIX_CELLS = 3\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 100')
      .replace('MODE = transport', 'MODE = batch'));
  } catch (e) { batchMsg = e.message; }
  check('  and in a batch', /MODE = transport/.test(batchMsg), batchMsg.slice(0, 60));
  const ap = RtmModel.compile(base('MATRIX_CELLS = 3\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nAPERTURE = 0.004'));
  close('APERTURE 2b gives aw = 2/(2b)', ap.matrix.aw, 500, 1e-15);
  check('a first layer too thick for its depth is refused with the limit',
    /smaller than/.test(refuse('MATRIX_CELLS = 4\nMATRIX_DEPTH = 1\nMATRIX_FIRST = 0.5\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 100')));
  const quiet = RtmModel.compile(base('MATRIX_CELLS = 3\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 100')
    .replace('Dm=1e-10', ''));
  check('a matrix nothing diffuses into is warned about', /nothing diffuses/.test(quiet.warnings.join(' ')));
  const coarse = RtmModel.compile(base('MATRIX_CELLS = 2\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 100\nPECLET = 10'));
  check('  and a grid coarser than its Peclet number', /Pe\/2/.test(coarse.warnings.join(' ')), coarse.warnings.join(' | ').slice(0, 70));
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 1
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
MATRIX_CELLS = 2
MATRIX_DEPTH = 1
MATRIX_POROSITY = 0.1
WETTED_SURFACE = 10
TEND = 1

<SPECIES>
X 0 Dm=1e-10
Y 0 Rm=0.5

<PARAMETERS>
S all 1
S 1 5 matrix
Q all 2 fracture

<INITIAL>
X 0 3.0
X 1 7.0 matrix

<REACTIONS>
=> Y, k = S
`);
  const y0 = m.initialState();
  check('<INITIAL> without "matrix" sets the fracture cell and its rock stays put',
    y0[m.cellOf(0, 0) * 2] === 3 && y0[m.cellOf(0, 1) * 2] === 0, `${y0[m.cellOf(0, 0) * 2]}, ${y0[m.cellOf(0, 1) * 2]}`);
  check('  and with it, the rock and not the fracture',
    y0[m.cellOf(1, 0) * 2] === 0 && y0[m.cellOf(1, 1) * 2] === 7 && y0[m.cellOf(1, 2) * 2] === 7,
    `${y0[m.cellOf(1, 0) * 2]}, ${y0[m.cellOf(1, 1) * 2]}, ${y0[m.cellOf(1, 2) * 2]}`);
  const out = new Float64Array(m.nspecies);
  m.rhs(0, y0, out);
  // Y's source: S everywhere (1), then 5 in the rock behind cell 1 and the
  // fracture there untouched by that line. In the rock a rate per unit water
  // enters as eps_m*S and the concentration moves at eps_m*S/Rm = 0.2*S.
  const yAt = (i, j) => out[m.cellOf(i, j) * 2 + 1];
  check('a parameter line with "matrix" reaches the rock alone, scaled by water over capacity',
    yAt(1, 0) === 1 && Math.abs(yAt(1, 1) - 5 * 0.1 / 0.5) < 1e-14 && Math.abs(yAt(0, 1) - 1 * 0.1 / 0.5) < 1e-14,
    `fracture ${yAt(1, 0)}, rock ${yAt(1, 1)}, other rock ${yAt(0, 1)}`);
  check('  and states are named cell.layer', m.species[m.cellOf(1, 2) * 2] === 'X@1.2', m.species[m.cellOf(1, 2) * 2]);
}

/* ======================================================================
   2d'. A far-field path as Kompartment's defaults have it
   ====================================================================== */
console.log('\n--- a far-field path as Kompartment has it ---');
/*
  Kompartment's far-field path starts with twelve matrix layers matched to
  diffusion into the rock, and the rock going on past the release point. The
  same here, read off Kompartment's own module further down (section 9); this
  is what does not need it: the settings that describe a path the way SKB
  does, the outlet, the flux through each end, and the transfer function
  against FARF31's exact one.
*/

/** A path in Kompartment's terms as model text. */
function pathText(p, o = {}) {
  const nf = o.nf || p.nf || 20;
  const L = o.length || p.tw;
  return `
<SETTINGS>
MODE = transport
CELLS = ${nf}
LENGTH = ${L}
TRAVEL_TIME = ${p.tw}
PECLET = ${p.pe}
LEFT = robin
RIGHT = ${o.right || 'semi-infinite'}
${o.nm ? `MATRIX_CELLS = ${o.nm}` : ''}
${o.grid ? `MATRIX_GRID = ${o.grid}` : ''}
MATRIX_DEPTH = ${p.penDep}
MATRIX_POROSITY = ${p.eps}
MATRIX_DENSITY = ${p.rho}
TRANSPORT_RESISTANCE = ${p.f}
TIME_UNIT = year

<SPECIES>
X 0 D=0 left=0 De=${p.de} Kd=${p.kd}${p.kdf ? ` Kdf=${p.kdf}` : ''}

<PARAMETERS>
S all 0
S 0 ${nf / L} fracture        # one unit a year into the first cell, per m2 of water

<REACTIONS>
=> X, k = S
${p.lam ? `X => , k = ${p.lam}, on = inventory` : ''}
`;
}

/** Kompartment's default path: T_w 100 a, F 1e5 a/m, Pe 10, 12.5 m of rock. */
const KDEF = { tw: 100, f: 1e5, pe: 10, penDep: 12.5, eps: 0.0018, rho: 2700, nf: 20, de: 1e-4, kd: 0 };

/**
 * x in A x = b, A dense and row-major, by partial pivoting. The transfer
 * function below is (sI - J)^-1 at a real s, a few hundred states.
 */
function solveDense(A, b, n) {
  const x = Float64Array.from(b);
  for (let k = 0; k < n; k++) {
    let p = k;
    for (let i = k + 1; i < n; i++) if (Math.abs(A[i * n + k]) > Math.abs(A[p * n + k])) p = i;
    if (p !== k) {
      for (let j = 0; j < n; j++) { const t = A[k * n + j]; A[k * n + j] = A[p * n + j]; A[p * n + j] = t; }
      const t = x[k]; x[k] = x[p]; x[p] = t;
    }
    for (let i = k + 1; i < n; i++) {
      const f = A[i * n + k] / A[k * n + k];
      if (f === 0) continue;
      for (let j = k; j < n; j++) A[i * n + j] -= f * A[k * n + j];
      x[i] -= f * x[k];
    }
  }
  for (let k = n - 1; k >= 0; k--) {
    let s = x[k];
    for (let j = k + 1; j < n; j++) s -= A[k * n + j] * x[j];
    x[k] = s / A[k * n + k];
  }
  return x;
}

/** The flux through one end at the state y, as the page works it out. */
function faceFlux(m, side, si, y) {
  const f = m.faces[side][si];
  let out = f.constant;
  for (const [idx, w] of f.terms) out += w * y[idx];
  return out;
}

/**
 * The model's transfer function at a real frequency s: the Laplace
 * transform of what leaves through the right-hand end after a unit pulse into
 * the first cell, w.(sI - J)^-1 b with b the source.
 */
function discreteTransfer(m, s) {
  const n = m.nspecies;
  const V = new Float64Array(m.nnz);
  m.jac(0, new Float64Array(n), V);
  const A = new Float64Array(n * n);
  const { colPtr, rowIdx } = m.pattern;
  for (let c = 0; c < n; c++) for (let k = colPtr[c]; k < colPtr[c + 1]; k++) A[rowIdx[k] * n + c] -= V[k];
  for (let i = 0; i < n; i++) A[i * n + i] += s;
  const b = new Float64Array(n);
  m.rhs(0, new Float64Array(n), b);
  return faceFlux(m, 'right', 0, solveDense(A, b, n));
}

/**
 * FARF31's exact transfer function for one nuclide (TR 90-01; the clean page
 * FARF31.html works it out the same way): flux in at the inlet to flux out at
 * the end of a semi-infinite stream tube, a matrix of finite depth beside it.
 */
function farf31Transfer(p, s) {
  const z = s + (p.lam || 0);
  const aw = p.f / p.tw;
  const Rm = p.eps + p.rho * p.kd;
  const Rf = 1 + (p.kdf || 0) * aw;
  const g = Rf * z + aw * Math.sqrt(p.de * Rm * z) * Math.tanh(p.penDep * Math.sqrt((Rm * z) / p.de));
  return Math.exp((p.pe / 2) * (1 - Math.sqrt(1 + (4 * p.tw * g) / p.pe)));
}
{
  // What a path needs to say, and what it is given when it does not.
  const m = RtmModel.compile(pathText(KDEF));
  check('a rock matrix that does not say how many layers has twelve, as Kompartment’s path',
    m.matrix.n === 12 && m.settings.MATRIX_CELLS === 12, `${m.matrix.n}`);
  check('  laid out matched to diffusion into the rock, the first worked out from the path',
    m.matrix.grid === 'matched' && m.matrix.rule === 'matched' && m.matrix.h !== null, `${m.matrix.grid}, ${m.matrix.rule}`);
  close('  TRANSPORT_RESISTANCE over TRAVEL_TIME is the wetted surface', m.matrix.aw, 1000, 1e-15);
  check('  TRAVEL_TIME sets the flow: LENGTH over it, ADVECTION on',
    m.settings.VELOCITY === 1 && m.settings.ADVECTION === 1, `v ${m.settings.VELOCITY}`);
  check('  and the rock goes on past the end for five cells at 20 cells and Pe 10',
    m.extra && m.extra.n === 5 && m.settings.EXTRA_CELLS === 5 && m.cells === 25 * 13, m.extra && `${m.extra.n}`);
  check('  which are laid out past LENGTH, as wide as the last cell',
    m.extra.centres[0] === 102.5 && m.extra.width.every((w) => w === 5), `${m.extra.centres[0]}`);
  const none = RtmModel.compile(pathText(KDEF).replace('MATRIX_DEPTH', 'MATRIX_CELLS = 0\nMATRIX_DEPTH'));
  check('MATRIX_CELLS = 0 is no rock at all, and what was said of it is called unused',
    none.matrix === null && /MATRIX_CELLS = 0/.test(none.warnings.join(' ')) && /not used/.test(none.warnings.join(' ')),
    none.warnings.join(' | ').slice(0, 90));
  const ref = RtmModel.compile(pathText(KDEF, { grid: 'reference' }));
  check('MATRIX_GRID = reference is FARFCOMP’s layers: ratio e, nodes at the centres',
    ref.matrix.h === null && Math.abs(ref.matrix.q - Math.E) < 1e-12 && ref.matrix.rule === 'e', `${ref.matrix.q}`);
  const given = RtmModel.compile(pathText(KDEF).replace('MATRIX_DEPTH', 'MATRIX_FIRST = 1e-3\nMATRIX_DEPTH'));
  check('MATRIX_FIRST is the first layer whichever the grid', given.matrix.d[0] === 1e-3 && given.matrix.rule === 'given');
  const still = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 3
LENGTH = 1
LEFT = neumann
RIGHT = neumann
MATRIX_DEPTH = 0.5
MATRIX_POROSITY = 0.02
WETTED_SURFACE = 200
<SPECIES>
X 1 D=1e-9 Dm=1e-10
<REACTIONS>
`);
  check('  and with no flow and no decay to size it by, the first layer is FARFCOMP’s',
    still.matrix.rule === 'e' && Math.abs(still.matrix.d[0] / ((0.5 * (Math.E - 1)) / (Math.exp(12) - 1)) - 1) < 1e-9,
    `${still.matrix.d[0].toExponential(4)}`);
}
{
  // The SKB parameterisation, said the way it is said there.
  const base = (settings, sp = 'X 0 D=0 left=0 Dm=1e-4') => `
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 8
${settings}
TEND = 1
<SPECIES>
${sp}
<REACTIONS>
`;
  const refuse = (text) => { try { RtmModel.compile(text); } catch (e) { return e.message; } return '(no error)'; };
  const por = RtmModel.compile(base('TRAVEL_TIME = 4\nPOROSITY = 0.5'));
  check('TRAVEL_TIME with a porosity: the Darcy VELOCITY is POROSITY*LENGTH/TRAVEL_TIME', por.settings.VELOCITY === 1, `${por.settings.VELOCITY}`);
  check('  a VELOCITY that says otherwise is refused', /disagree/.test(refuse(base('TRAVEL_TIME = 4\nVELOCITY = 3'))));
  check('  and so is ADVECTION = 0', /ADVECTION/.test(refuse(base('TRAVEL_TIME = 4\nADVECTION = 0'))));
  check('TRANSPORT_RESISTANCE with no flow to divide it by is refused',
    /travel time/.test(refuse(base('MATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nTRANSPORT_RESISTANCE = 1e4'))));
  check('  and one that disagrees with WETTED_SURFACE',
    /disagree/.test(refuse(base('TRAVEL_TIME = 4\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nTRANSPORT_RESISTANCE = 1e4\nWETTED_SURFACE = 100'))));
  const agree = RtmModel.compile(base('TRAVEL_TIME = 4\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nTRANSPORT_RESISTANCE = 1e4\nAPERTURE = 0.0008'));
  close('  one that agrees with APERTURE stands', agree.matrix.aw, 2500, 1e-15);
  // Kd and Kdf become Rm and R: read back through the derivative of a lone layer.
  const kd = RtmModel.compile(base('TRAVEL_TIME = 4\nMATRIX_CELLS = 1\nMATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nMATRIX_DENSITY = 2000\nWETTED_SURFACE = 100',
    'X 0 D=0 left=0 De=1e-4 Kd=0.002 Kdf=0.01'));
  const y = new Float64Array(kd.nspecies);
  const f = new Float64Array(kd.nspecies);
  y[kd.cellOf(0, 0)] = 1;
  kd.rhs(0, y, f);
  // One layer a metre deep: the wall exchange 2*De/d = 2e-4 per m2, aw = 100
  // of wall per m3 of water, into R = 1 + Kdf*aw beside the advection u/dz =
  // 2/2 out of the cell, and into Rm = eps + rho*Kd in the rock.
  close('Kd= is the capacity eps + rho*Kd in the rock', f[kd.cellOf(0, 1)], 2e-4 / (0.01 + 2000 * 0.002), 1e-14);
  close('Kdf= is the retardation 1 + Kdf*aw in the fracture', f[kd.cellOf(0, 0)],
    -(1 + 2e-4 * 100) / (1 + 0.01 * 100), 1e-14);
  check('Kd beside Rm is refused', /both Kd and Rm/.test(refuse(base('MATRIX_DEPTH = 1\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 1', 'X 0 Dm=1 Kd=1 Rm=2'))));
  check('  Kdf beside R', /both Kdf and R/.test(refuse(base('WETTED_SURFACE = 1', 'X 0 Kdf=1 R=2'))));
  check('  Kdf with no wetted surface', /Kdf/.test(refuse(base('', 'X 0 Kdf=1'))));
  check('  and a negative Kd', /zero or more/.test(refuse(base('', 'X 0 Kd=-1'))));
  const lone = RtmModel.compile(base('', 'X 0 D=1e-9 Dm=1e-10 Kd=0.1'));
  check('rock properties with no rock are called unused', /no rock matrix/.test(lone.warnings.join(' ')), lone.warnings.join(' | ').slice(0, 80));
}
{
  // The semi-infinite end.
  const text = (right, extra = '', sp = 'X 0 D=0 left=1') => `
<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 100
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1
PECLET = 10
LEFT = robin
RIGHT = ${right}
${extra}
TEND = 1
<SPECIES>
${sp}
<REACTIONS>
`;
  const refuse = (t) => { try { RtmModel.compile(t); } catch (e) { return e.message; } return '(no error)'; };
  check('LEFT = semi-infinite is refused: it is an outlet', /outlet/.test(refuse(text('free').replace('LEFT = robin', 'LEFT = semi-infinite'))));
  check('  so is a semi-infinite end the water does not leave by', /VELOCITY/.test(refuse(text('semi-infinite').replace('VELOCITY = 1', 'VELOCITY = -1'))));
  check('  and EXTRA_CELLS without one', /semi-infinite/.test(refuse(text('free', 'EXTRA_CELLS = 3'))));
  const three = RtmModel.compile(text('semi-infinite', 'EXTRA_CELLS = 3'));
  check('EXTRA_CELLS given is the count', three.extra.n === 3);
  const zero = RtmModel.compile(text('semi-infinite', 'EXTRA_CELLS = 0'));
  check('  and 0 closes the last cell itself by extrapolation', zero.extra === null && zero.cells === 20);
  // Counted as Kompartment counts them: rho = (2N - Pe)/(2N + Pe) per cell,
  // and none at all where the grid's own dispersion is all there is.
  const counts = [10, 20, 25, 40, 50].map((pe) => {
    const x = RtmModel.compile(text('semi-infinite').replace('PECLET = 10', `PECLET = ${pe}`)).extra;
    return x ? x.n : 0;
  });
  check('  and worked out, the fewest cells with rho^n under a tenth: 5, 3, 2, 0, 0 at Pe 10, 20, 25, 40, 50 on 20 cells',
    counts.join(',') === '5,3,2,0,0', counts.join(', '));
  const dOnly = RtmModel.compile(text('semi-infinite', '', 'X 0 D=2.5 left=1').replace('PECLET = 10\n', ''));
  check('  a species’ own D counts as dispersion: D/(D + u*dz) = 1/3 needs 3', dOnly.extra.n === 3, `${dOnly.extra.n}`);
  // The column goes on: a line reaching the last cell reaches the extra cells,
  // a source in the first does not.
  const go = RtmModel.compile(`${text('semi-infinite', '', 'X 0 D=0 left=0 R=Q\nY 0')}
<PARAMETERS>
Q all 2
Q 15-19 3
S all 0
S 0 1

<INITIAL>
Y 10-19 0.5
Y 3 0.7
`.replace('<REACTIONS>\n', '<REACTIONS>\n=> X, k = S\n'));
  const y0 = go.initialState();
  const f0 = new Float64Array(go.nspecies);
  go.rhs(0, y0, f0);
  check('the cells past the end start as the last cell does', y0[go.cellOf(22, 0) * 2 + 1] === 0.5 && y0[go.cellOf(3, 0) * 2 + 1] === 0.7,
    `${y0[go.cellOf(22, 0) * 2 + 1]}`);
  // With nothing in X yet, its derivative is the source over R: only cell 0.
  check('  hold what a line reaching the last cell gives, and no source of the first',
    f0[go.cellOf(0, 0) * 2] === 0.5 && f0[go.cellOf(21, 0) * 2] === 0, `${f0[go.cellOf(0, 0) * 2]}, ${f0[go.cellOf(21, 0) * 2]}`);
  // X at 1 in cell 21 alone: cell 22 takes u/dz = 0.2 of it by advection and
  // D/dz^2 = 7.5/25 = 0.3 by dispersion, divided by its R.
  const one = new Float64Array(go.nspecies);
  one[go.cellOf(21, 0) * 2] = 1;
  go.rhs(0, one, f0);
  close('  and R = 3 there, from "Q 15-19 3"', f0[go.cellOf(22, 0) * 2], (0.2 + 0.3) / 3, 1e-14);
}
{
  /*
    THE FLUX THROUGH EACH END against the column's own balance: what the
    cells gain is what comes in at x = 0 less what leaves at x = LENGTH, at
    any state whatever -- for every kind of end, both ways of flowing, and a
    rock matrix behind the cells. Exact, so to round-off.
  */
  const kinds = [['robin', 'semi-infinite', 1], ['robin', 'free', 1], ['dirichlet', 'dirichlet', 1],
    ['dirichlet', 'neumann', -1], ['neumann', 'robin', -1], ['robin', 'semi-infinite', 1, true]];
  let worst = 0;
  for (const [L, R, dir, rock] of kinds) {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 12
LENGTH = 6
DIFFUSION = 1
ADVECTION = 1
VELOCITY = ${0.3 * dir}
POROSITY = 0.6
PECLET = 15
LEFT = ${L}
RIGHT = ${R}
${rock ? 'MATRIX_DEPTH = 0.2\nMATRIX_POROSITY = 0.01\nWETTED_SURFACE = 50' : ''}
<SPECIES>
X 0.3 D=0.02 left=1.3 right=0.4 R=1.7${rock ? ' Dm=1e-3 Kd=1e-4' : ''}
<REACTIONS>
`);
    const y = Float64Array.from({ length: m.nspecies }, (_, k) => 0.2 + ((k * 7919) % 101) / 101);
    const f = new Float64Array(m.nspecies);
    m.rhs(0, y, f);
    const aw = rock ? 50 : 0;
    const Rm = rock ? 0.01 + 2700 * 1e-4 : 0;
    let held = 0;
    for (let i = 0; i < m.fracture; i++) {
      held += m.grid.width[i] * 1.7 * f[m.cellOf(i, 0)];
      if (rock) for (let j = 1; j <= m.matrix.n; j++) held += m.grid.width[i] * aw * Rm * m.matrix.d[j - 1] * f[m.cellOf(i, j)];
    }
    const net = faceFlux(m, 'left', 0, y) - faceFlux(m, 'right', 0, y);
    worst = Math.max(worst, Math.abs(held - net) / Math.max(Math.abs(net), 1e-300));
  }
  check('what the column gains is the flux in at x = 0 less the flux out at LENGTH, for every end',
    worst < 1e-12, `worst ${worst.toExponential(2)} relative over ${kinds.length} pairs`);
}
{
  /*
    AGAINST FARF31. The model's own transfer function -- the transform of the
    release after a unit pulse in -- beside the exact one FARF31 inverts, at
    real frequencies from far below the path's own to where the exact one has
    fallen to e^-15. Kompartment's path is the same matrix (section 9), so
    this is how far its default is from FARF31 too.
  */
  const freqs = (p) => {
    const out = [];
    for (let s = 1e-9; farf31Transfer(p, s) > Math.exp(-15) && out.length < 200; s *= 1.6) out.push(s);
    return out;
  };
  // How far ln T is off where T is above e^-5, which is the bulk of a release,
  // and the worst over the whole range.
  const misses = (p, o) => {
    const m = RtmModel.compile(pathText(p, o));
    let bulk = 0;
    let all = 0;
    for (const s of freqs(p)) {
      const e = Math.abs(Math.log(discreteTransfer(m, s) / farf31Transfer(p, s)));
      all = Math.max(all, e);
      if (farf31Transfer(p, s) > Math.exp(-5)) bulk = Math.max(bulk, e);
    }
    return { bulk, all };
  };
  const ra = { tw: 235.2, f: 80090, pe: 10, penDep: 4.5, eps: 0.0019, rho: 2700, nf: 20, de: 8.5e-7, kd: 4.5e-4, lam: 4.3322e-4 };
  const now = misses(KDEF, {});
  const old = misses(KDEF, { right: 'free', grid: 'reference', nm: 20 });
  const fine = misses(KDEF, { nf: 40 });
  check('the default path’s transfer function is FARF31’s to 3 % in the bulk of a release',
    now.bulk < 0.03, `|ln T| off by ${now.bulk.toExponential(2)} where T > e^-5, ${now.all.toExponential(2)} down to e^-15`);
  check('  where the old layers and a Danckwerts outlet were 9 % out', old.bulk > 3 * now.bulk, `${old.bulk.toExponential(2)}`);
  check('  and what is left is the 20 fracture cells, at second order: 40 cells are 4 times closer',
    now.bulk / fine.bulk > 3.5, `${fine.bulk.toExponential(2)}`);
  const raNow = misses(ra, {});
  const raOld = misses(ra, { right: 'free', grid: 'reference', nm: 20 });
  check('  the same for a sorbing nuclide that decays on the way (Ra-226 on the TR-19-06 path)',
    raNow.bulk < 0.03 && raOld.bulk > 3 * raNow.bulk, `${raNow.bulk.toExponential(2)} against ${raOld.bulk.toExponential(2)}`);
  const m20 = misses(KDEF, { nm: 20 });
  check('  and twelve matched layers do as well as twenty', Math.abs(m20.bulk - now.bulk) < 1e-3 * now.bulk + 1e-6,
    `${m20.bulk.toExponential(3)} against ${now.bulk.toExponential(3)}`);
  const tracer = RtmModel.compile(pathText(KDEF));
  close('  a tracer that does not decay all comes out: T(0) = 1', discreteTransfer(tracer, 0), 1, 1e-12);
}
{
  // The analytic Jacobian of a whole path with a decay chain behind it, and
  // a path that holds its decay constant -- the first layer sized by it.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 50
TRAVEL_TIME = 50
PECLET = 10
LEFT = robin
RIGHT = semi-infinite
MATRIX_DEPTH = 12.5
MATRIX_POROSITY = 0.0018
TRANSPORT_RESISTANCE = 1e5
TIME_UNIT = year
<SPECIES>
P 0 D=0 left=1 De=3.15e-5 Kd=0.0017
Q 0 D=0 left=0 De=3.15e-5 Kd=0.05 Kdf=1e-4
<REACTIONS>
P => Q, k = 2.8234E-6, on = inventory
Q => , k = 1.8289, on = inventory
`);
  const v = RtmModel.verifyJacobian(m, 0, Float64Array.from(m.initialState(), (_, k) => 1e-3 * (1 + (k % 7))));
  check('the analytic Jacobian of a semi-infinite path with a chain agrees with a central difference',
    v.discrepancies.length === 0, `${v.discrepancies.length} of ${v.checked} disagree, ${v.unresolvable} below the floor`);
  // Q's decay, 1.83 a year, is faster than anything the path lets through, so
  // the layers are sized by it: sqrt(De/(Rm*lam))/10.
  const Rm = 0.0018 + 2700 * 0.05;
  close('  and a short-lived member sizes the first layer by its decay', m.matrix.d[0], Math.sqrt(3.15e-5 / Rm / 1.8289) / 10, 1e-12);
}

/* ======================================================================
   2e. The pattern, folded into the three blocks the page draws
   ====================================================================== */
console.log('\n--- the pattern as three blocks ---');
{
  // The Jacobian tab cannot be sent the whole pattern of a long column, so the
  // worker folds it into a cell against itself and against each neighbour.
  // That is only a picture of the matrix if the three blocks put it back
  // together exactly, which is what this counts.
  const fold = (model) => {
    const ns = model.speciesNames.length;
    const p = model.pattern;
    const masks = [new Uint8Array(ns * ns), new Uint8Array(ns * ns), new Uint8Array(ns * ns)];
    let outside = 0;
    for (let col = 0; col < p.n; col++) {
      const cc = Math.floor(col / ns);
      for (let k = p.colPtr[col]; k < p.colPtr[col + 1]; k++) {
        const row = p.rowIdx[k];
        const rc = Math.floor(row / ns);
        const at = (row - rc * ns) * ns + (col - cc * ns);
        if (rc === cc) masks[0][at] = 1;
        else if (cc === rc - 1) masks[1][at] = 1;
        else if (cc === rc + 1) masks[2][at] = 1;
        else outside++;
      }
    }
    const count = masks.map((m2) => m2.reduce((a, v) => a + v, 0));
    return { ns, count, outside,
      rebuilt: count[0] * model.cells + (count[1] + count[2]) * (model.cells - 1) };
  };
  for (const [label, text] of [
    ['the built-in model', RTM_DEFAULT_MODEL],
    ['it as a batch', RTM_DEFAULT_MODEL.replace(/^MODE.*$/m, 'MODE = batch')],
  ]) {
    const m = RtmModel.compile(text);
    const f = fold(m);
    check(`${label}: nothing reaches past one neighbour`, f.outside === 0, `${f.outside} entries`);
    check(`  and the blocks rebuild all ${m.nnz} non-zeros`, f.rebuilt === m.nnz,
      `${f.rebuilt} rebuilt from ${f.count.join(' + ')}`);
    check('  with the chemistry block genuinely sparse',
      f.count[0] < 0.5 * f.ns * f.ns,
      `${f.count[0]} of ${f.ns * f.ns} (${(100 * f.count[0] / (f.ns * f.ns)).toFixed(1)} %)`);
  }
}

/* ======================================================================
   2h. The time unit, and the examples the page offers
   ====================================================================== */
console.log('\n--- the time unit ---');
{
  /*
    TIME_UNIT converts nothing: it says what the model's own numbers mean, so
    that the page can label an axis and read "500 a" in a box. Two models that
    differ only in the word must therefore give the SAME numbers.
  */
  const mk = (unit) => RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 10
TIME_UNIT = ${unit}

<SPECIES>
A 1.0

<REACTIONS>
A => , k = 0.3
`);
  // rtol here is the integrator's: at the suite's usual 1e-10 this lands
  // 4e-9 out, which is the NDF's own accumulated error, not the unit's doing.
  const a = last(run(mk('second'), { tend: 10, rtol: 1e-12 }));
  const b = last(run(mk('year'), { tend: 10, rtol: 1e-12 }));
  check('the unit is a label, not a conversion: the numbers do not move',
    a[0] === b[0], `${a[0]} and ${b[0]}`);
  close('  and they are what the rate constant says', a[0], Math.exp(-3), 1e-9);
  check('it is resolved to a name and a size', mk('a').timeUnit.name === 'year'
    && mk('a').timeUnit.symbol === 'a' && mk('a').timeUnit.seconds === 365.25 * 86400,
    JSON.stringify(mk('a').timeUnit));
  for (const [word, want] of [['s', 'second'], ['min', 'minute'], ['h', 'hour'],
    ['d', 'day'], ['yr', 'year'], ['YEARS', 'year']]) {
    check(`  "${word}" means ${want}`, mk(word).settings.TIME_UNIT === want, mk(word).settings.TIME_UNIT);
  }
  let message = '(no error)';
  try { mk('fortnight'); } catch (e) { message = e.message; }
  check('  and a unit it does not know is refused', /TIME_UNIT must be one of/.test(message),
    message.slice(0, 60));
  check('a model that says nothing is in seconds',
    RtmModel.compile('<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<REACTIONS>\nA => , k=1\n')
      .timeUnit.name === 'second');
}
{
  // Numerical dispersion against the real thing, which is the other thing a
  // grid can be too coarse for.
  const mk = (cells, D, extra) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${cells}
LENGTH = 1
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1e-6
${extra}
LEFT = robin
RIGHT = free
TEND = 1

<SPECIES>
X 0 D=${D} left=1

<REACTIONS>
`);
  const warns = (m) => m.warnings.join(' ');
  check('a grid that disperses more than the species does is called out',
    /grid disperses more than X/.test(warns(mk(10, 1e-9, ''))), warns(mk(10, 1e-9, '')).slice(0, 72));
  check('  and says how many cells would not',
    /\d+ cells would bring/.test(warns(mk(10, 1e-9, ''))));
  check('  while a grid fine enough is quiet', warns(mk(10, 1e-6, '')) === '', warns(mk(10, 1e-6, '')));
  check('a PECLET coarser than the grid is called out too',
    /Pe\/2/.test(warns(mk(4, 1e-9, 'PECLET = 10'))), warns(mk(4, 1e-9, 'PECLET = 10')).slice(0, 60));
  check('  and one the grid can reach is quiet', !/Pe\/2/.test(warns(mk(10, 1e-9, 'PECLET = 10'))));
}

/* ======================================================================
   2i. What skbrtm's databases needed: names, constants, grids, a surface,
       tables, cells held
   ====================================================================== */
console.log('\n--- names with groups, constants as arithmetic, aliases ---');
{
  const rhsOf = (text) => {
    const m = RtmModel.compile(text);
    const y = m.initialState();
    const f = new Float64Array(y.length);
    m.rhs(0, y, f);
    const at = (name, cell = 0) => f[cell * m.speciesNames.length + m.speciesNames.indexOf(name)];
    return { m, y, f, at, clean: RtmModel.verifyJacobian(m, 0, y) };
  };
  const batch = (species, rx) => rhsOf(`<SETTINGS>\nMODE = batch\n\n<SPECIES>\n${species}\n\n<REACTIONS>\n${rx}\n`);

  const a = batch('Fe+2 2\nO2 3\nFe(OH)3 0', 'Fe+2 + 0.25 O2 => Fe(OH)3, r = k*[Fe+2]*[O2], k = 0.5');
  check('a species may be named with a group in round brackets: Fe(OH)3',
    a.m.speciesNames.includes('Fe(OH)3'), a.m.speciesNames.join(' '));
  close('  and it is made at the rate its law says', a.at('Fe(OH)3'), 0.5 * 2 * 3, 1e-15);
  let msg = '(no error)';
  try { batch('Fe(OH 1', 'Fe(OH => , k = 1'); } catch (e) { msg = e.message; }
  check('  while an unclosed bracket is not a name', /not a species name.*round brackets/.test(msg), msg.slice(0, 80));

  const b = batch('A 8\nB 0', 'A => B, r = k*[A]**(2/3), k = 3');
  close('an exponent written as arithmetic, (2/3), is worked out: 3 * 8^(2/3)', b.at('B'), 12, 1e-14);
  check('  and differentiated: the Jacobian agrees with a difference',
    b.clean.discrepancies.length === 0 && b.clean.checked > 0, JSON.stringify(b.clean.discrepancies));
  close('a power of ten with a negative exponent, 10**-3, is a number', batch('A 2', 'A => , r = 10**-3*[A]').at('A'), -2e-3, 1e-15);
  const d = batch('A 9', 'A => , r = [A]**n, n = 0.5');
  close('an exponent may be a constant of the line: [A]**n, n = 0.5', d.at('A'), -3, 1e-15);
  check('  and is differentiated as one', d.clean.discrepancies.length === 0);
  const e = rhsOf(`<SETTINGS>\nMODE = transport\nCELLS = 3\nLENGTH = 1\nDIFFUSION = 0\n\n<SPECIES>\nA 2\n\n`
    + `<PARAMETERS>\nN all 1 + i\n\n<REACTIONS>\nA => , r = [A]**N\n`);
  check('an exponent may be a parameter that differs from cell to cell: 2^1, 2^2, 2^3',
    [0, 1, 2].every((c) => Math.abs(e.at('A', c) + 2 ** (c + 1)) < 1e-14), [0, 1, 2].map((c) => e.at('A', c)).join(', '));
  check('  with a Jacobian that agrees in every cell', e.clean.discrepancies.length === 0);

  const f = batch('A 1', 'A => , r = (kr/kh)*[A], kr = 1.33*10**12, kh = 1.3*10**-3');
  close('a constant may be arithmetic: kr/kh = 1.33*10**12 / (1.3*10**-3), as the text means',
    -f.at('A'), 1.33e12 / 1.3e-3, 1e-15);
  close('a constant may use one named before it: kb = kf/4', batch('A 1', 'A => , r = kb*[A], kf = 2, kb = kf/4').at('A'), -0.5, 1e-15);
  msg = '(no error)';
  try { batch('A 1', 'A => , r = k*[A], k = 2*kk'); } catch (err) { msg = err.message; }
  check('  but a name it does not know is refused, not read as zero', /Parameter k = "2\*kk" is not a number/.test(msg), msg.slice(0, 90));

  const h = batch('A 2\nB 5', 'A => , r = k*c*[A], k = 0.1, c = [B]');
  close('an alias, c = [B], is that concentration in the law', h.at('A'), -0.1 * 5 * 2, 1e-15);
  {
    // The entry the alias adds: d(dA/dt)/dB = -k*[A] = -0.2.
    const V = new Float64Array(h.m.nnz);
    h.m.jac(0, h.y, V);
    const { colPtr, rowIdx } = h.m.pattern;
    let dAdB = null;
    for (let k = colPtr[1]; k < colPtr[2]; k++) if (rowIdx[k] === 0) dAdB = V[k];
    check('  and the Jacobian has the entry it adds, d(dA/dt)/dB = -0.2, agreeing with a difference',
      dAdB !== null && Math.abs(dAdB + 0.2) < 1e-15 && h.clean.discrepancies.length === 0 && !h.clean.outsidePattern,
      `${dAdB}`);
  }
  const skb = batch('bt_Fe+2 380.482\nFe+2 1.0E-6\nFeOH3 0',
    'bt_Fe+2 = Fe+2, r = k*ab0*(c_3/c30)**(2/3)*(10**-3/pm)*(1-c_2/c20), k = 5.45e-13, ab0 = 6.141, '
    + 'c_3 = [bt_Fe+2], c30 = 380.482, pm = 1.8e-3, c_2 = [Fe+2], c20 = 1.8e-6');
  close('skbrtm\'s biotite line reads as written: aliases, (2/3), 10**-3 and a bare =',
    skb.at('Fe+2'), 5.45e-13 * 6.141 * 1 * (1e-3 / 1.8e-3) * (1 - 1e-6 / 1.8e-6), 1e-14);
  check('  and its Jacobian agrees', skb.clean.discrepancies.length === 0);

  // A name may stand for an expression that reads the water, as a step of a program: the law reads it in brackets.
  const named = batch('A 2\nB 5\nC 0',
    'A => C, r = k*x*y, c = [A], x = c*(1 - [B]/cmax), b2 = [B], y = exp(-0.1*b2), k = 0.3, cmax = 10');
  const plain = batch('A 2\nB 5\nC 0', 'A => C, r = 0.3*[A]*(1 - [B]/10)*exp(-0.1*[B])');
  close('a name may stand for an expression of the water, x = c*(1 - [B]/cmax), y = exp(-0.1*b2), the law reading each '
    + 'in brackets', named.at('A'), plain.at('A'), 1e-15);
  check('  and its Jacobian agrees', named.clean.discrepancies.length === 0 && !named.clean.outsidePattern);
  const refusedName = (rx) => { try { batch('A 2\nB 5', rx); return '(no error)'; } catch (err) { return err.message; } };
  const before = refusedName('A => , r = y, y = 2*b2, b2 = [B]');
  const word = refusedName('A => , r = TK*[A], TK = [B]');
  const twice = refusedName('A => , r = x, x = [A], x = [B]');
  check('  refused: a name used before it is given, a name a rate law reads already, a name given twice',
    /uses b2, which is given after it on the line/.test(before) && /names something a rate law reads already/.test(word)
    && /x is given twice on the line/.test(twice), `${before} | ${word} | ${twice}`);
  // A power's exponent may go with the temperature, which no species moves, and be negated.
  const pk = batch('A 2', 'A => , r = 10^(-pk)*[A]^(-n)*[A]^2, pk = 2 + 300*(1/TK - 1/298.15), n = 0.5');
  close('a power\'s exponent may read the temperature and be negated: 10^(-pk), pk in TK, [A]^(-n)',
    pk.at('A'), -0.01 * 2 ** 1.5, 1e-15);
  check('  and its Jacobian agrees', pk.clean.discrepancies.length === 0 && !pk.clean.outsidePattern);

  const s = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 2\nLENGTH = 2*0.5\nTEND = 365*86400\n\n'
    + '<SPECIES>\nA 2*3 D=1e-9*2\n\n<REACTIONS>\n');
  check('a setting may be arithmetic: TEND = 365*86400', s.settings.TEND === 31536000, String(s.settings.TEND));
  check('  and so may the numbers on a species line: 2*3, D=1e-9*2',
    s.initialState()[0] === 6 && s.speciesList[0].D === 2e-9, `${s.initialState()[0]}, ${s.speciesList[0].D}`);
}

console.log('\n--- grids: power-law, faces given outright, a log ratio, a surface layer ---');
{
  const grid = (settings) => RtmModel.compile(`<SETTINGS>\nMODE = transport\n${settings}\nTEND = 1\n\n`
    + '<SPECIES>\nX 0 D=1e-9\n\n<REACTIONS>\n').grid;
  const worst = (a, b) => Math.max(...Array.from(a, (v, i) => Math.abs(v - b[i])));
  const p3 = grid('CELLS = 10\nLENGTH = 1e-4\nGRID = powerlaw');
  check('GRID = powerlaw puts the faces at L*(i/N)^3',
    worst(p3.faces, Array.from({ length: 11 }, (_, i) => 1e-4 * (i / 10) ** 3)) < 1e-20);
  check('  the centres midway between them, the widths face to face',
    p3.centres.every((c, i) => Math.abs(c - (p3.faces[i] + p3.faces[i + 1]) / 2) < 1e-20)
    && p3.width.every((w, i) => Math.abs(w - (p3.faces[i + 1] - p3.faces[i])) < 1e-20));
  const p2 = grid('CELLS = 10\nLENGTH = 1e-4\nGRID = powerlaw\nGRID_POWER = 2');
  check('  and GRID_POWER sets the exponent', Math.abs(p2.faces[5] - 1e-4 * 0.25) < 1e-20, String(p2.faces[5]));
  const fl = grid('FACES = 0, 1, 3, 6');
  check('FACES as a list is the grid: three cells of 1, 2 and 3 m, centres 0.5, 2 and 4.5',
    fl.n === 3 && fl.L === 6 && worst(fl.width, [1, 2, 3]) === 0 && worst(fl.centres, [0.5, 2, 4.5]) === 0,
    `${fl.n} cells, ${Array.from(fl.width)}`);
  const fe = grid('CELLS = 10\nFACES = 1e-4*(i/10)^3');
  check('  and as an expression in i it gives what powerlaw does', worst(fe.faces, p3.faces) < 1e-20);
  const lg = grid('CELLS = 5\nLENGTH = 1\nGRID = log\nGRID_RATIO = 10');
  close('GRID_RATIO sets how much larger the last log cell is than the first', lg.width[4] / lg.width[0], 10, 1e-12);
  const l0 = grid('CELLS = 5\nLENGTH = 1\nGRID = log');
  close('  and without it the ratio is still 1000', l0.width[4] / l0.width[0], 1000, 1e-12);
  const sl = grid('CELLS = 10\nLENGTH = 1e-4\nGRID = log\nSURFACE_LAYER = 2.5e-7');
  check('SURFACE_LAYER makes the first cell exactly that thick', sl.width[0] === 2.5e-7, String(sl.width[0]));
  close('  lays the other nine out over the rest by the same GRID', sl.width[9] / sl.width[1], 1000, 1e-12);
  close('  and the column is still LENGTH long', sl.faces[10], 1e-4, 1e-15);
  for (const [label, settings, re] of [
    ['a first face that is not 0', 'FACES = 1, 2, 3', /must be 0/],
    ['faces that do not increase', 'FACES = 0, 2, 1', /must increase/],
    ['a CELLS that disagrees with the faces', 'CELLS = 4\nFACES = 0, 1, 2', /describes 2 cells/],
    ['a surface layer as long as the column', 'CELLS = 4\nLENGTH = 1\nSURFACE_LAYER = 1', /less than LENGTH/],
    ['a surface layer with the faces given', 'FACES = 0, 1, 2\nSURFACE_LAYER = 0.1', /cannot be combined/],
  ]) {
    let m = '(no error)';
    try { grid(settings); } catch (err) { m = err.message; }
    check(`  refused: ${label}`, re.test(m), m.slice(0, 70));
  }

  // A closed box on a power-law grid still conserves what it holds.
  const box = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 20\nLENGTH = 1e-4\nGRID = powerlaw\n'
    + 'LEFT = neumann\nRIGHT = neumann\nTEND = 10\n\n<SPECIES>\nX 0 D=1e-9\n\n<INITIAL>\nX 0 1\n\n<REACTIONS>\n');
  const inv = (y) => Array.from(box.grid.width).reduce((s2, w, i) => s2 + w * y[i], 0);
  const drift = Math.abs(inv(last(run(box, { tend: 10 }))) - inv(box.initialState())) / inv(box.initialState());
  check(`a closed power-law column conserves its content (drift ${drift.toExponential(1)})`, drift < 1e-12);

  // b1 of skbrtm: Crank's slab on a power-law grid, and doubling the cells.
  const crank = (x, t, L, D) => {
    let c = 1;
    for (let k = 0; k < 400; k++) {
      const kn = ((2 * k + 1) * Math.PI) / (2 * L);
      c -= (4 / ((2 * k + 1) * Math.PI)) * Math.sin(kn * x) * Math.exp(-D * kn * kn * t);
    }
    return c;
  };
  const err = (n) => {
    const m = RtmModel.compile(`<SETTINGS>\nMODE = transport\nCELLS = ${n}\nLENGTH = 0.1\nGRID = powerlaw\n`
      + 'LEFT = dirichlet\nRIGHT = neumann\nTEND = 864000\n\n<SPECIES>\nTracer 0 D=1e-9 left=1\n\n<REACTIONS>\n');
    const y = last(run(m, { tend: 864000, rtol: 1e-10, atol: 1e-14 }));
    return Math.max(...Array.from(m.grid.centres, (x, i) => Math.abs(y[i] - crank(x, 864000, 0.1, 1e-9))));
  };
  const e50 = err(50);
  const e100 = err(100);
  check(`skbrtm's b1 on our power-law grid: ${e50.toExponential(2)} from Crank at ten days with 50 cells`, e50 < 1e-3);
  check(`  and ${(e50 / e100).toFixed(2)}x closer with 100`, e50 / e100 > 1.9);
}

console.log('\n--- a surface: the cell width in expressions, a layer that stays put ---');
{
  const perCell = (text) => {
    const m = RtmModel.compile(text);
    const y = m.initialState();
    const f = new Float64Array(y.length);
    m.rhs(0, y, f);
    return { m, y, f };
  };
  const w = perCell('<SETTINGS>\nMODE = transport\nCELLS = 4\nLENGTH = 1\nGRID = log\nGRID_RATIO = 8\nDIFFUSION = 0\n\n'
    + '<SPECIES>\nA 0\nB 0\nC 0\n\n<PARAMETERS>\nW all w\nXL all xl\nXR all xr\n\n'
    + '<REACTIONS>\n=> A, r = W\n=> B, r = XL\n=> C, r = XR\n');
  const g = w.m.grid;
  check('w, xl and xr in <PARAMETERS> are the cell\'s width and its two faces',
    [0, 1, 2, 3].every((c) => w.f[c * 3] === g.width[c] && w.f[c * 3 + 1] === g.faces[c] && w.f[c * 3 + 2] === g.faces[c + 1]));
  // A surface amount stated per m2 comes out the same whatever the grid.
  for (const kind of ['linear', 'log', 'powerlaw']) {
    const m = RtmModel.compile(`<SETTINGS>\nMODE = transport\nCELLS = 10\nLENGTH = 1e-4\nGRID = ${kind}\n\n`
      + '<SPECIES>\nU_site 0\n\n<INITIAL>\nU_site 0 2.1e-4*1/w*1e-3\n\n<REACTIONS>\n');
    close(`  a site density per m2, 2.1e-4/w, is 2.1e-4 mol/m2 of surface on a ${kind} grid`,
      m.initialState()[0] * m.grid.width[0] * 1e3, 2.1e-4, 1e-14);
  }
  /*
    What the layer is for. Two surface sites S in the first cell, per m2,
    react with each other -- S + S => P, second order in a CONCENTRATION --
    and P diffuses away. Per m2 of surface that rate is k*(G/w0)^2*w0, so it
    grows as the first cell thins: refine the grid and the answer moves,
    which is exactly what skbrtm's fuel-dissolution example does. With the
    first cell pinned by SURFACE_LAYER the answer stops depending on CELLS.
  */
  const surface = (cells, layer) => {
    const m = RtmModel.compile(`<SETTINGS>\nMODE = transport\nCELLS = ${cells}\nLENGTH = 1e-4\nGRID = log\n`
      + `${layer ? `SURFACE_LAYER = ${layer}\n` : ''}LEFT = neumann\nRIGHT = neumann\nTEND = 1\n\n`
      + '<SPECIES>\nS 0\nO2 1e-3 D=1e-9\nP 0 D=1e-9\n\n<INITIAL>\nS 0 1e-7/w\n\n'
      + '<REACTIONS>\nS + S => P, r = k*[S]**2, k = 1e-3\nS + O2 => P, r = k*[S]*[O2], k = 1e-2\n');
    // One second: long enough to make some, short enough that the sites are
    // barely touched, so the rate itself is what is measured.
    const y = last(run(m, { tend: 1, rtol: 1e-9, atol: 1e-24 }));
    const ns = m.speciesNames.length;
    const iP = m.speciesNames.indexOf('P');
    return Array.from(m.grid.width).reduce((sum, wc, c) => sum + wc * y[c * ns + iP], 0);
  };
  const free = [10, 20, 40].map((n) => surface(n, 0));
  const pinned = [10, 20, 40].map((n) => surface(n, 2.5e-7));
  const spread = (v) => (Math.max(...v) - Math.min(...v)) / Math.max(...v);
  check(`without a surface layer the product per m2 moves with the grid by ${(spread(free) * 100).toFixed(0)} %`,
    spread(free) > 0.2, free.map((v) => v.toExponential(3)).join(', '));
  check(`  and with SURFACE_LAYER = 2.5e-7 m by ${(spread(pinned) * 100).toExponential(1)} %`,
    spread(pinned) < 1e-3, pinned.map((v) => v.toExponential(4)).join(', '));
}

console.log('\n--- tables ---');
{
  const withTable = (table, params, length = 2, cells = 4) => {
    const m = RtmModel.compile(`<SETTINGS>\nMODE = transport\nCELLS = ${cells}\nLENGTH = ${length}\nDIFFUSION = 0\n\n`
      + `<SPECIES>\nX 0\n\n${table}\n<PARAMETERS>\n${params}\n\n<REACTIONS>\n=> X, r = P\n`);
    const y = m.initialState();
    const f = new Float64Array(y.length);
    m.rhs(0, y, f);
    return { m, f: Array.from(f) };
  };
  const T = '<TABLE t>\n0 0\n1 10\n2 30\n';
  const lin = withTable(T, 'P all t(x)');
  check('a <TABLE> read as t(x) is interpolated at each cell centre: 2.5, 7.5, 15, 25',
    lin.f.every((v, i) => Math.abs(v - [2.5, 7.5, 15, 25][i]) < 1e-14), lin.f.join(', '));
  check('  interp(t, x), as FACSIMILE writes it, is the same thing',
    withTable(T, 'P all interp(t, x)').f.join() === lin.f.join());
  const past = withTable(T, 'P all t(x)', 4);
  check('  and beyond its last row it holds the last value: 5, 20, 30, 30',
    past.f.every((v, i) => Math.abs(v - [5, 20, 30, 30][i]) < 1e-14), past.f.join(', '));
  const lg = withTable('<TABLE e log>\n0 1\n1 0.1\n', 'P all e(x)', 1, 2);
  close('a log table interpolates the logarithm: 0.1^(1/4) a quarter of the way along',
    lg.f[0], 0.1 ** 0.25, 1e-14);
  check('  and that is the table in the name: its parameter is listed', lin.m.tables.includes('t'));
  const init = RtmModel.compile(`<SETTINGS>\nMODE = transport\nCELLS = 4\nLENGTH = 2\n\n<SPECIES>\nX 0\n\n${T}\n`
    + '<INITIAL>\nX all t(x)\n\n<REACTIONS>\n');
  check('a table may give a starting profile in <INITIAL> too',
    Array.from(init.initialState()).every((v, i) => Math.abs(v - [2.5, 7.5, 15, 25][i]) < 1e-14));
  for (const [label, table, params, re] of [
    ['x that does not increase', '<TABLE t>\n0 1\n0 2\n', 'P all t(x)', /must increase/],
    ['a log table with a zero in it', '<TABLE t log>\n0 1\n1 0\n', 'P all t(x)', /above zero/],
    ['a row of one number', '<TABLE t>\n0\n', 'P all t(x)', /not two numbers/],
    ['rows of different widths', '<TABLE t>\n0 1 2\n1 2\n', 'P all t(x, 1)', /not 3 numbers/],
    ['a table of two columns read without saying which', '<TABLE t>\n0 1 2\n', 'P all t(x)', /say which/],
    ['a column it has not got', '<TABLE t>\nx A B\n0 1 2\n', 'P all t(x, C)', /no column "C"/],
    ['a table with no name', '<TABLE>\n0 1\n', 'P all 1', /needs a name/],
  ]) {
    let m = '(no error)';
    try { withTable(table, params); } catch (err) { m = err.message; }
    check(`  refused: ${label}`, re.test(m), m.slice(0, 70));
  }
  // A rate law reads a table at the clock, never at a concentration: the
  // table's slope would be part of the Jacobian.
  let m = '(no error)';
  try {
    RtmModel.compile(`<SETTINGS>\nMODE = batch\n\n<SPECIES>\nX 1\n\n${T}\n<REACTIONS>\nX => , r = t([X])*[X]\n`);
  } catch (err) { m = err.message; }
  check('  and a table read in a rate law at a concentration is refused, with the way to do it instead',
    /read at a time/.test(m) && /<PARAMETERS>/.test(m), m.slice(0, 90));
  const cols = withTable('<TABLE c>\nx  A  B\n0  1  10\n2  3  30\n', 'P all c(x, B) + c(x, 1)');
  check('a table of several columns, named in its first row, is read by name or by number: B + A at the centres',
    cols.f.every((v, i) => Math.abs(v - ([12.5, 17.5, 22.5, 27.5][i] + [1.25, 1.75, 2.25, 2.75][i])) < 1e-13), cols.f.join(', '));
  const ll = withTable('<TABLE p loglog>\n1 1\n100 1e-4\n', 'P all p(x)', 40, 4);
  // Cell centres 5, 15, 25, 35: a power law x^-2 between the two rows.
  check('a loglog table is a power law between its rows: x^-2 at 5, 15, 25, 35',
    ll.f.every((v, i) => Math.abs(v / [5, 15, 25, 35][i] ** -2 - 1) < 1e-12), ll.f.join(', '));
}

/* ======================================================================
   Sources that follow the clock: a release history
   ====================================================================== */
console.log('\n--- sources that follow the clock ---');
{
  // t in a rate law is the clock: a loss that fades with time,
  // dA/dt = -k exp(-t/tau) A, has A = exp(-k tau (1 - exp(-t/tau))).
  const k = 0.5;
  const tau = 3;
  const T = 10;
  const m = RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = ${T}\n\n<SPECIES>\nA 1\n\n<REACTIONS>\n`
    + `A => , r = k*exp(-t/tau)*[A], k = ${k}, tau = ${tau}\n`);
  close('t in a rate law is the clock: a loss that fades with time, against its closed form',
    last(run(m, { tend: T }))[0], Math.exp(-k * tau * (1 - Math.exp(-T / tau))), 1e-8);
  check('  and a Jacobian that follows the clock is not said to be constant', m.jacobianConstant === false);
  let msg = '(no error)';
  try {
    RtmModel.compile('<SETTINGS>\nMODE = batch\n\n<SPECIES>\nA 1\n\n<PARAMETERS>\nt all 2\n\n<REACTIONS>\nA => , k = 1\n');
  } catch (e) { msg = e.message; }
  check('  and a parameter called t is refused: t is the time', /"t" is the time/.test(msg), msg.slice(0, 60));
}
{
  /*
    A PULSE IN A RELEASE HISTORY, ten years of it in five thousand, into a
    store that decays. The run is started again at every corner of a table
    read at the clock, so the pulse is integrated whole; without that the
    solver's steps have grown long over the quiet stretch before it, and it
    steps clean over the pulse and sees nothing at all.
  */
  const m = RtmModel.compile(`<SETTINGS>
MODE = batch
TEND = 5000
TIME_UNIT = year

<TABLE pulse>
0       0
999.99  0
1000    1
1010    1
1010.01 0

<SPECIES>
X 0

<REACTIONS>
=> X, r = pulse(t)
X => , k = 1e-3
`);
  check('the run is started again at each corner of a table read at the clock',
    m.breaks(0, 5000).join(',') === '999.99,1000,1010,1010.01', m.breaks(0, 5000).join(','));
  // The table's own integral: ten years at one, and the two ramps of a
  // hundredth of a year, each worth half of that.
  const exact = (lo, hi) => (Math.exp(-1e-3 * (5000 - hi)) - Math.exp(-1e-3 * (5000 - lo))) / 1e-3;
  const want = exact(1000, 1010) + 0.5 * 0.01 * (Math.exp(-1e-3 * 4000) + Math.exp(-1e-3 * (5000 - 1010)));
  const seen = last(run(m, { tend: 5000, rtol: 1e-9, atol: 1e-14 }))[0];
  close('  so a pulse of ten years in five thousand is seen whole', seen, want, 1e-5);
  const blind = Object.assign(Object.create(m), { breaks: undefined });
  const missed = last(run(blind, { tend: 5000, rtol: 1e-9, atol: 1e-14 }))[0];
  check('  where a run that is not started again steps over it and sees nothing',
    missed < 1e-6 * want, `${missed.toExponential(2)} against ${want.toExponential(4)}`);
  // Where a table turns follows its argument: a delay moves the corners, a
  // factor scales them, and an argument that is not a line in t has none
  // the run can know of.
  const at = (arg) => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1e4\n\n<TABLE p>\n0 0\n10 1\n20 0\n\n`
    + `<SPECIES>\nX 0\n\n<REACTIONS>\n=> X, r = p(${arg})\n`).breaks(0, 1e4).join(',');
  check('  the corners follow the argument: a delay, a factor, and none for one that is not a line in t',
    at('t - 1000') === '1000,1010,1020' && at('2*t') === '5,10' && at('t/100') === '1000,2000'
      && at('sqrt(t)') === '', `${at('t - 1000')} | ${at('2*t')} | ${at('t/100')} | ${at('sqrt(t)')}`);
}
{
  /*
    A RELEASE HISTORY THROUGH A FAR-FIELD PATH, against FARF31. The path is
    Kompartment's default one; the nuclide Ra-226, which the rock holds back
    by five orders; the history a rise, a plateau and a decline over twenty
    thousand years. FARF31.html convolves the history with the path's exact
    response (TR 90-01), and the model converges on that at second order as
    the cells along the path are refined: the 20 cells of the default are
    where its error is, as the transfer function above showed.
  */
  const Farf31Model = require(path.join(jsDir, 'farf31-model.js'));
  const hist = [[0, 0], [500, 0], [600, 1], [2000, 1], [5000, 0.2], [20000, 0]];
  const times = Array.from({ length: 41 }, (_, k) => 600 * (40000 / 600) ** (k / 40));
  const ref = Farf31Model.run({
    settings: { evalTimes: times, check: false },
    params: { tw: 100, Pe: 10, aw: 1000, eps: 0.0018, x0: 12.5, rho: 2700 },
    nuclides: [{ name: 'Ra', thalf: 1600, kd: 4.5e-4, de: 1e-4, source: true }],
    series: { Ra: hist },
  }).at.out[0];
  const peakRef = Math.max(...ref);
  const peakAt = (nf) => {
    const m = RtmModel.compile(`<SETTINGS>
MODE = transport
CELLS = ${nf}
LENGTH = 100
TRAVEL_TIME = 100
PECLET = 10
LEFT = robin
RIGHT = semi-infinite
MATRIX_DEPTH = 12.5
MATRIX_POROSITY = 0.0018
TRANSPORT_RESISTANCE = 1E5
TIME_UNIT = year

<TABLE release>
${hist.map(([t, v]) => `${t} ${v}`).join('\n')}

<SPECIES>
Ra 0 D=0 left=0 De=1e-4 Kd=4.5e-4

<PARAMETERS>
IN all 0
IN 0 1/w fracture

<REACTIONS>
=> Ra, r = IN*release(t)
Ra => , k = ${Math.LN2 / 1600}, on = inventory
`);
    const r = run(m, { tend: 40000, rtol: 1e-8, atol: 1e-20, maxPoints: 1e9 });
    let k = 1;
    let peak = 0;
    for (const tw of times) {
      while (k < r.t.length - 1 && r.t[k] < tw) k++;
      const a = (tw - r.t[k - 1]) / (r.t[k] - r.t[k - 1]);
      peak = Math.max(peak, faceFlux(m, 'right', 0, r.y[k - 1]) * (1 - a) + faceFlux(m, 'right', 0, r.y[k]) * a);
    }
    return Math.abs(peak / peakRef - 1);
  };
  const [e20, e40, e80] = [20, 40, 80].map(peakAt);
  check('a release history through the default path converges on FARF31’s convolution of it at second order',
    e40 < e20 / 3.5 && e80 < e40 / 3.5 && e80 < 0.025,
    `peak off by ${(100 * e20).toFixed(1)} %, ${(100 * e40).toFixed(1)} %, ${(100 * e80).toFixed(2)} % on 20, 40, 80 cells`);
}

console.log('\n--- a species held in some cells only ---');
{
  const res = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 10\nLENGTH = 1e-2\nLEFT = neumann\n'
    + 'RIGHT = neumann\nTEND = 1e5\n\n<SPECIES>\nX 0 D=1e-9\n\n<INITIAL>\nX 0 1 fixed\n\n<REACTIONS>\n');
  const y = last(run(res, { tend: 1e5 }));
  check('a cell held with "fixed" in <INITIAL> is a reservoir: it stays at 1',
    Math.abs(y[0] - 1) < 1e-12, String(y[0]));
  check('  and still feeds its neighbours', y[1] > 0.1 && y[1] < 1 && y[1] > y[2], `${y[1]}, ${y[2]}`);
  check('  with a Jacobian that agrees', RtmModel.verifyJacobian(res, 0, res.initialState()).discrepancies.length === 0);
  check('  and the model says which cells it holds',
    res.held.length === 1 && res.held[0].species === 'X' && res.held[0].cells.join() === '0', JSON.stringify(res.held));

  const rx = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 10\nLENGTH = 1\nDIFFUSION = 0\nTEND = 1\n\n'
    + '<SPECIES>\nA 1\nB 0\n\n<INITIAL>\nB 5-9 0 fixed\n\n<REACTIONS>\nA => B, k = 1\n');
  const z = last(run(rx, { tend: 1 }));
  const B = (c) => z[c * 2 + 1];
  const A = (c) => z[c * 2];
  close('where B is free the reaction makes it: 1 - exp(-1)', B(2), 1 - Math.exp(-1), 1e-8);
  // The row is zero; what is left is the factorisation's round-off, which
  // the page writes back out (rtmHoldFixed).
  check('  where it is held it stays at 0', [5, 6, 7, 8, 9].every((c) => Math.abs(B(c)) < 1e-15), [5, 9].map(B).join(', '));
  close('  while A still decays there, since only B is held', A(7), Math.exp(-1), 1e-8);
  const keep = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 5\nLENGTH = 1\n\n'
    + '<SPECIES>\nX 3 D=1e-3\n\n<INITIAL>\nX 3-4 fixed\n\n<REACTIONS>\n');
  check('"fixed" with no value holds a species where it already is',
    keep.initialState()[4] === 3 && keep.fixedAt[3] === 1 && keep.fixedAt[2] === 0);
  let msg = '(no error)';
  try {
    RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 3\nLENGTH = 1\nEQUILIBRATE = 1\n\n<SPECIES>\n'
      + 'H+ 1e-7\nOH- 1e-7\n\n<INITIAL>\nH+ 0 1e-7 fixed\n\n<EQUILIBRIUM>\n <=> H+ + OH-, logK = -14\n\n<REACTIONS>\n');
  } catch (err) { msg = err.message; }
  check('a species held in some cells cannot be speciated, and the text says why',
    /held in some cells only/.test(msg), msg.slice(0, 80));
}

console.log('\n--- opening skbrtm databases ---');
{
  /*
    A small skbrtm case written out here -- the databases are not in this
    repository -- that touches every rule the importer follows: the script's
    order and time span, decimal commas and bounds in a REGRESSION, a name in
    two cases, <= and a bare =, a placeholder line, skbrtm's (kr/kh), a
    boundary_values it ignores, a colon for a semicolon, a lone cell_id,
    a species constant in one cell only, a value per cell width.
  */
  const RtmImport = require(path.join(jsDir, 'rtm-import.js'));
  const files = [
    { name: 'run.py', text: [
      "pm = parent_directory() + '/databases/'",
      "p0 = pm + 'reaction.in'", "p1 = pm + 'sourceterm.in'", "p2 = pm + 'diffusion.in'",
      "p3 = pm + 'solutions.in'", "p4 = pm + 'doserate.in'",
      'paths = [p4, p1, p0, p2, p3]',
      "solver = Solver(processes = (*db.sourceterm, *db.reaction, *db.diffusion),",
      "                solutions = (*db.solution,),",
      "                t_span    = (0, 2, 'days'), rtol = 1e-4)"].join('\n') },
    { name: 'doserate.in', text: 'REGRESSION;dose\nbounds; (0., None, 0., None)\nfunction; exponential\n'
      + 'predictor;response\n-1,0e-06;9,0\n0,0;4,0\n1,0e-06;2,0\n2,0e-06;1,0\n' },
    { name: 'sourceterm.in', text: "SOURCETERM;radiolysis\nparameters; {'g_scale' : 2.0}\n"
      + 'SPECIES;EXPRESSION;ARGUMENTS\nH2O2;G*dose(coordinates)*g_scale;G = 1.0e-7\n' },
    { name: 'reaction.in', text: 'REACTION;chem\nSTOICHIOMETRY;EXPRESSION;ARGUMENTS\n'
      + 'H2O2 + Site => Ox;r = k*[h2o2]*[Site];k = 2.0\n'
      + 'Fe+2 + 0.25O2 = Fe(OH)3;r = (kr/kh)*[O2]*[Fe+2];kr = 1.33*10**12, kh = 1.3*10**-3\n'
      + 'Ox <= Red;r = k*[Red];k = 3.0\n'
      + 'Tr = Tr;r = k;k = 0\n' },
    { name: 'diffusion.in', text: "DIFFUSION;col\ncells;6\ngrid_type;'powerlaw'\nmax_length;1e-5\nmin_length;0\n"
      + "boundary_conditions;('dirichlet', 'neumann')\nboundary_values; {'left': {'o2': 5e-4}}\n"
      + 'SPECIES;DIFFUSION_COEFFICIENT\nSite;0.\nOx;0.\n' },
    { name: 'solutions.in', text: "SOLUTION; surface\nunits; mol/L\ncell_id; 0\nconstant; Red\nparameters; {'sites' : 1e-4}\n"
      + 'SPECIES;CONCENTRATION\nSite; sites/cell_width*1e-3\nO2; 2.5e-4\nFe+2; 1e-6\nRed; 1e-3\n\n'
      + 'SOLUTION; water\nunits: mol/L\ncell_id; 1-6\nSPECIES;CONCENTRATION\nO2; 2.5e-4\nFe+2; 1e-6\n\n'
      + 'SOLUTION; one cell\nunits; mol/L\ncell_id; 3\nSPECIES;CONCENTRATION\nTr; 1.0\n' },
  ];
  const res = RtmImport.convert(files);
  let m = null;
  let msg = '(compiled)';
  try { m = RtmModel.compile(res.text); } catch (e) { msg = e.message; }
  check('a set of skbrtm databases and their script opens as one model that compiles', !!m, msg);
  if (m) {
    const ns = m.speciesNames.length;
    const at = (name, cell = 0) => m.initialState()[cell * ns + m.speciesNames.indexOf(name)];
    const s = m.settings;
    check('the script gives the time span: 2 days is 172800 s', s.TEND === 172800, String(s.TEND));
    check('  and DIFFUSION the column: 6 power-law cells over 10 um, dirichlet | neumann',
      s.MODE === 'transport' && m.fracture === 6 && s.GRID === 'powerlaw' && s.LEFT === 'dirichlet'
      && s.RIGHT === 'neumann' && Math.abs(m.grid.L - 1e-5) < 1e-20);
    check('names keep their spelling, and [h2o2] is the H2O2 of the stoichiometry',
      m.speciesNames.includes('H2O2') && !m.speciesNames.includes('h2o2') && m.speciesNames.includes('Fe(OH)3'),
      m.speciesNames.join(' '));
    check('a species DIFFUSION does not list moves at 1e-9; one it gives 0 does not',
      m.speciesList.find((x) => x.name === 'O2').D === 1e-9 && !m.mobile[m.speciesNames.indexOf('Site')]);
    close('a value per cell width is per m2: Site holds 1e-4 * 1e-3 mol per m2 of the first cell',
      at('Site') * m.grid.width[0], 1e-7, 1e-12);
    check('  and nowhere else, as its SOLUTION says', at('Site', 1) === 0);
    check('a species constant in one SOLUTION is held in those cells only: Red, in cell 0',
      m.held.length === 1 && m.held[0].species === 'Red' && m.held[0].cells.join() === '0' && at('Red') === 1e-3,
      JSON.stringify(m.held));
    check('boundary_values, which skbrtm ignores, becomes the face value: O2 at 5e-4',
      m.speciesList.find((x) => x.name === 'O2').left === 5e-4);
    check('  and the cell by the face starts where the column behind it does', at('O2') === 2.5e-4, String(at('O2')));
    check('a lone cell_id 3 goes in cell 3, every species set there as a SOLUTION does',
      at('Tr', 3) === 1 && at('O2', 3) === 0 && at('Tr', 0) === 0);
    check('the REGRESSION is its own table, the rows its bounds keep, interpolated in the log',
      /<TABLE dose log>\n# x -> value\n0  4\n1e-6  2\n2e-6  1\n/.test(res.text), res.text.slice(res.text.indexOf('<TABLE'), res.text.indexOf('<TABLE') + 60));
    const y = m.initialState();
    const f = new Float64Array(y.length);
    m.rhs(0, y, f);
    const x0 = m.grid.centres[0];
    close('the source reads it at each cell: G*dose(x)*g_scale in cell 0',
      f[m.speciesNames.indexOf('H2O2')], 1e-7 * 4 * Math.pow(2, -x0 / 1e-6) * 2, 1e-12);
    check('"Ox <= Red" runs from Red to Ox', /Red => Ox, r = k\*\[Red\]/.test(res.text));
    check('the placeholder "Tr = Tr" is kept as a comment', /^# Tr = Tr/m.test(res.text));
    const says = (re) => res.warnings.some((w) => re.test(w));
    check('it says that skbrtm reads (kr/kh) a million times smaller', says(/Fe\+2.*1\.000e-6 times/));
    check('  that skbrtm puts the lone cell_id in cell 0', says(/cell 3.*cell 0/));
    check('  that skbrtm ignores boundary_values', says(/ignores boundary_values/));
    check('  and that it reads nothing from "units: mol/L"', says(/units: mol\/L/));
    let ran = null;
    try { ran = run(m, { tend: s.TEND, rtol: 1e-6, atol: 1e-20, nonNegative: true }); } catch (e) { ran = e.message; }
    check('and the model runs to its TEND', ran && typeof ran === 'object' && ran.t[ran.t.length - 1] === s.TEND,
      typeof ran === 'string' ? ran : String(ran && ran.t[ran.t.length - 1]));
  }
  // The real thing, when it is on this machine: skbrtm-main's five cases.
  const skb = path.join(require('os').homedir(), 'Downloads', 'skbrtm-main');
  if (require('fs').existsSync(skb)) {
    const fs = require('fs');
    let ok = 0;
    const cases = [['benchmarks/b0_benchmark', 'b0_main.py'], ['benchmarks/b1_benchmark', 'b1_main.py'],
      ['examples/batch/0_example', '0_example.py'], ['examples/batch/fuel dissolution', 'BRUM1Cell.py'],
      ['examples/transport/fuel dissolution', 'BRUM1D.py']];
    const bad = [];
    for (const [dir, script] of cases) {
      const d = path.join(skb, dir);
      try {
        const fl = [{ name: script, text: fs.readFileSync(path.join(d, script), 'utf8') }];
        for (const fn of fs.readdirSync(path.join(d, 'databases'))) fl.push({ name: fn, text: fs.readFileSync(path.join(d, 'databases', fn), 'utf8') });
        const mm = RtmModel.compile(RtmImport.convert(fl).text);
        run(mm, { tend: mm.settings.TEND, rtol: 1e-6, atol: 1e-20, nonNegative: true, stagnationTol: 0.5 });
        ok++;
      } catch (e) { bad.push(`${dir}: ${e.message.slice(0, 60)}`); }
    }
    check(`skbrtm-main's ${cases.length} cases open, compile and run`, ok === cases.length, bad.join(' | '));
  } else {
    console.log('      (skbrtm-main is not in ~/Downloads here; its own cases were not tried)');
  }
}

console.log('\n--- the examples ---');
{
  /*
    Every example the page offers has to compile and run, or the picker hands
    the reader something broken. Two of them are checked further, because they
    are the ones with a published answer.
  */
  const { RTM_EXAMPLES } = require(path.join(jsDir, 'rtm-examples.js'));
  const byId = (id) => RTM_EXAMPLES.find((e) => e.id === id);
  let broke = 0;
  let worstWarn = '';
  for (const e of RTM_EXAMPLES) {
    try {
      const m = RtmModel.compile(e.text);
      if (!m.speciesNames.length) throw new RtmModel.RtmError('no species');
      // Every field the picker shows.
      if (!e.id || !e.label || !e.group || !e.about) throw new RtmModel.RtmError('a field is missing');
      FacsimileODE.runModel(m, { solver: 'ndf', rtol: 1e-6, atol: 1e-24, tend: m.settings.TEND,
        nonNegative: true, maxSteps: 4e5, maxPoints: 4, stagnationTol: 0.5 });
      if (m.warnings.length && !worstWarn) worstWarn = `${e.id}: ${m.warnings[0].slice(0, 50)}`;
    } catch (err) {
      broke++;
      console.log(`      ${e.id} failed: ${String(err.message).slice(0, 90)}`);
    }
  }
  check(`all ${RTM_EXAMPLES.length} examples compile and run`, broke === 0, `${broke} failed`);
  check('  and none of them raises a warning', worstWarn === '', worstWarn);

  // Robertson: the point everyone quotes, and the invariant.
  const rob = RtmModel.compile(byId('robertson').text);
  const r = run(rob, { tend: 1e7, rtol: 1e-12, atol: 1e-18, maxPoints: 1e9 });
  let hi = 1;
  while (hi < r.t.length - 1 && r.t[hi] < 0.4) hi++;
  const lo = hi - 1;
  const f = (0.4 - r.t[lo]) / (r.t[hi] - r.t[lo]);
  const at = [0, 1, 2].map((j) => r.y[lo][j] + f * (r.y[hi][j] - r.y[lo][j]));
  close('Robertson at t = 0.4 matches the published A', at[0], 0.9851721, 1e-6);
  close('  the published B', at[1], 3.3864e-5, 1e-4);
  close('  the published C', at[2], 0.0147939, 1e-5);
  let worst = 0;
  for (const y of r.y) worst = Math.max(worst, Math.abs(y[0] + y[1] + y[2] - 1));
  check('  and A + B + C never leaves 1', worst < 1e-13, worst.toExponential(2));

  // The matrix-diffusion example, against the erfc it says it follows.
  const mt = RtmModel.compile(byId('matrixtracer').text);
  const rt = run(mt, { tend: 120, rtol: 1e-8, atol: 1e-14, maxPoints: 1e9 });
  const idx = mt.cellOf(mt.fracture - 1, 0);
  const tw = 20;
  const exact = (t) => (t > tw ? erfc((500 * tw * Math.sqrt(1e-3 * 0.0018)) / (2 * Math.sqrt(t - tw))) : 0);
  let mtWorst = 0;
  for (let i = 0; i < rt.t.length; i++) {
    if (rt.t[i] < tw * 1.5) continue;
    mtWorst = Math.max(mtWorst, Math.abs(rt.y[i][idx] - exact(rt.t[i])));
  }
  check('the matrix-diffusion example follows the erfc it claims', mtWorst < 0.011,
    `worst ${mtWorst.toExponential(2)}`);

  // The U-238 chain: in years, and mass has to end up somewhere.
  const u = RtmModel.compile(byId('u238chain').text);
  check('the U-238 chain is a model in years', u.timeUnit.name === 'year');
  check('  with six nuclides, a rock matrix and decay on the inventory',
    u.speciesNames.length === 6 && u.matrix.n === 20 && u.nchannels === 7,
    `${u.speciesNames.length} species, ${u.matrix ? u.matrix.n : 0} layers, ${u.nchannels} channels`);
  const ru = run(u, { tend: 1e6, rtol: 1e-6, atol: 1e-20, maxPoints: 4 });
  const yu = last(ru);
  const has = (name) => yu[u.cellOf(0, 0) * 6 + u.speciesNames.indexOf(name)];
  check('  and the daughters grow in from a source of the parent alone',
    has('U238') > 0 && has('Th230') > 0 && has('Ra226') > 0,
    `U238 ${has('U238').toExponential(2)}, Th230 ${has('Th230').toExponential(2)}, Ra226 ${has('Ra226').toExponential(2)}`);
  /*
    SECULAR EQUILIBRIUM, which is the check this example is worth.

    Deep in the rock nothing flows, so after a million years each short-lived
    daughter must sit at the activity of its parent: lambda_parent N_parent =
    lambda_daughter N_daughter, N the whole inventory, Rm*C. That is a
    statement about the chain, the sorption and the decay together: with Rm
    from 1.2 to 143 the concentrations themselves are a hundred times apart.
    It only holds if a daughter is born of the parent's whole inventory and
    then takes up its own share -- until 2026-10-06 a daughter here was born
    of the parent's concentration times its own capacity, which made atoms,
    and this check, written against that, compared the concentrations.

    In the FRACTURE it does not hold, and should not: flow carries a nuclide
    away before its daughter catches up.
  */
  const lam = { Th230: 9.1946e-6, Ra226: 4.3322e-4, Pb210: 3.1083e-2, Po210: 1.8289 };
  const Rm = { Th230: 0.0019 + 2700 * 5.3e-2, Ra226: 0.0019 + 2700 * 4.5e-4, Pb210: 0.0019 + 2700 * 2.5e-2,
    Po210: 0.0019 + 2700 * 2.5e-2 };
  const cellAt = (i, j, name) => yu[u.cellOf(i, j) * 6 + u.speciesNames.indexOf(name)];
  let offBy = 0;
  for (const [parent, daughter] of [['Pb210', 'Po210'], ['Ra226', 'Pb210'], ['Th230', 'Ra226']]) {
    const want = (lam[parent] * Rm[parent]) / (lam[daughter] * Rm[daughter]);
    for (const cell of [0, u.fracture - 1]) {
      offBy = Math.max(offBy, Math.abs(cellAt(cell, u.matrix.n, daughter) / cellAt(cell, u.matrix.n, parent) / want - 1));
    }
  }
  check('  and deep in the rock the chain reaches secular equilibrium',
    offBy < 5e-3, `worst ${(100 * offBy).toFixed(2)} % from the parent's activity`);
  const share = cellAt(0, 0, 'Ra226') / cellAt(0, 0, 'Th230') / (lam.Th230 / lam.Ra226);
  check('  while in the fracture the flow keeps it from doing so', Math.abs(share - 1) > 0.5,
    `radium is ${share.toFixed(2)} times its equilibrium share`);
}

/* ======================================================================
   2x. Equilibria held throughout the run (EQUILIBRATE = always)

   Held exactly, a relation is an algebraic equation: the totals it conserves
   are integrated and the species are solved for at every instant. So the
   checks are exact ones -- every stored point on every relation; the totals
   what the sources put in; the state at the end the speciation of the totals
   the end has, worked out apart.
   ====================================================================== */
console.log('\n--- equilibria held throughout the run ---');
{
  const carb = (equilibrate, opts = {}) => `
<SETTINGS>
MODE = batch
TEND = 1e5
EQUILIBRATE = ${equilibrate}

<SPECIES>
H+      ${opts.h || '1e-7'}${opts.fixH ? '  fixed' : ''}
OH-     1e-7
CO2     2e-4
HCO3-   2e-3${opts.rHCO3 ? `  R=${opts.rHCO3}` : ''}
CO3-2   1e-9
Cl-     ${opts.cl || '0'}

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14${opts.kfWater ? `, kf = ${opts.kfWater}` : ''}
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33

<REACTIONS>
${opts.reactions !== undefined ? opts.reactions : '=> H+ + Cl-, k = 1.5e-8'}
`;
  const at = (m) => (name) => m.speciesNames.indexOf(name);

  // --- the setting ---
  check('EQUILIBRATE = always holds the equilibria: five species algebraic',
    RtmModel.compile(carb('always')).nalgebraic === 5);
  const startOnly = RtmModel.compile(carb('start'));
  check('  start means 1: the start only, nothing algebraic', startOnly.settings.EQUILIBRATE === 1
    && !startOnly.nalgebraic);
  let refused = '';
  try { RtmModel.compile(carb('alway')); } catch (e) { refused = e.message; }
  check('  a word it does not know is refused, not read as no', /EQUILIBRATE is 0, 1, start or always/.test(refused),
    refused);

  // --- acid into a carbonate water ---
  const m = RtmModel.compile(carb('always'));
  const i = at(m);
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  let onRel = 0;
  let carbon = 0;
  let chloride = 0;
  let charge = 0;
  for (let p = 0; p < r.t.length; p++) {
    const c = m.toConcentrations(r.y[p]);
    const [H, OH, CO2, HCO3, CO3, Cl] = ['H+', 'OH-', 'CO2', 'HCO3-', 'CO3-2', 'Cl-'].map((n) => c[i(n)]);
    onRel = Math.max(onRel, Math.abs(Math.log10(H * OH) + 14), Math.abs(Math.log10(H * HCO3 / CO2) + 6.35),
      Math.abs(Math.log10(H * CO3 / HCO3) + 10.33));
    carbon = Math.max(carbon, Math.abs((CO2 + HCO3 + CO3) / 2.200001e-3 - 1));
    chloride = Math.max(chloride, Math.abs(Cl - 1.5e-8 * r.t[p]) / 1.5e-3);
    charge = Math.max(charge, Math.abs((H - OH - HCO3 - 2 * CO3 - Cl) / -2.000002e-3 - 1));
  }
  check('acid into a carbonate water: every stored point on all three relations', onRel < 1e-9,
    `${r.t.length} points, worst ${onRel.toExponential(1)} in log K`);
  check('  carbon conserved', carbon < 1e-12, `${carbon.toExponential(1)} relative`);
  check('  the chloride the source put in', chloride < 1e-10, `${chloride.toExponential(1)}`);
  check('  and the charge the equilibria cannot change, acid adding H+ and Cl- alike', charge < 1e-10,
    `${charge.toExponential(1)} relative`);
  // The answer at the end, apart: the same totals, speciated from scratch.
  const tEnd = r.t[r.t.length - 1];
  const clEnd = 1.5e-8 * tEnd;
  const apart = RtmModel.compile(carb(1, { h: String(1e-7 + clEnd), cl: String(clEnd), reactions: '' })).initialState();
  const end = m.toConcentrations(r.y[r.y.length - 1]);
  let worstEnd = 0;
  for (const n of ['H+', 'OH-', 'CO2', 'HCO3-', 'CO3-2']) worstEnd = Math.max(worstEnd, Math.abs(end[i(n)] / apart[i(n)] - 1));
  check('  the state at the end is the speciation of the totals the end has', worstEnd < 1e-7,
    `pH ${(-Math.log10(end[i('H+')])).toFixed(6)}, worst species ${worstEnd.toExponential(1)} relative`);

  // --- the Jacobian, the consistent start, the methods that cannot ---
  const v0 = RtmModel.verifyJacobian(m, 0, m.initialState());
  const v1 = RtmModel.verifyJacobian(m, tEnd, r.y[r.y.length - 1]);
  check('the Jacobian, ln C and the totals included, at the start and the end',
    v0.discrepancies.length === 0 && v1.discrepancies.length === 0, `${v0.checked} and ${v1.checked} entries`);
  const y0 = m.initialState();
  const knocked = Float64Array.from(y0);
  for (const n of ['H+', 'OH-', 'CO2', 'HCO3-', 'CO3-2']) knocked[i(n)] += 0.7;
  const settled = m.consistentInitial(0, knocked, { rtol: 1e-8 });
  let back = 0;
  for (let k = 0; k < y0.length; k++) back = Math.max(back, Math.abs(knocked[k] - y0[k]));
  check('  a state knocked off its relations is put back where it was, the totals held', settled.solved && back < 1e-9,
    `${settled.iterations} iterations, ${back.toExponential(1)}`);
  let methodRefused = '';
  try { FacsimileODE.runModel(m, { solver: 'ros23', tend: 1, rtol: 1e-6, atol: 1e-20 }); } catch (e) { methodRefused = e.message; }
  check('  a method with no mass matrix is refused, and says why', /algebraic/.test(methodRefused),
    methodRefused.slice(0, 80));

  // --- a retarded species weighs its coefficient into the totals ---
  const mr = RtmModel.compile(carb('always', { rHCO3: 2.5 }));
  const ir = at(mr);
  const rr = FacsimileODE.runModel(mr, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const inv = (c) => c[ir('CO2')] + 2.5 * c[ir('HCO3-')] + c[ir('CO3-2')];
  const inv0 = inv(mr.toConcentrations(rr.y[0]));
  let invWorst = 0;
  for (const y of rr.y) invWorst = Math.max(invWorst, Math.abs(inv(mr.toConcentrations(y)) / inv0 - 1));
  check('with R = 2.5 on HCO3-, the carbon inventory is what is conserved', invWorst < 1e-12,
    `${invWorst.toExponential(1)} relative`);

  // --- a buffered pH: H+ fixed, so the carbonate ratio is too ---
  const mf = RtmModel.compile(carb('always', { fixH: true, reactions: '=> CO2, k = 1e-9' }));
  const iff = at(mf);
  const rf = FacsimileODE.runModel(mf, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const cf = mf.toConcentrations(rf.y[rf.y.length - 1]);
  const totalF = cf[iff('CO2')] + cf[iff('HCO3-')] + cf[iff('CO3-2')];
  check('H+ fixed: the carbonate takes what the source adds and keeps the buffered ratio',
    Math.abs(cf[iff('H+')] - 1e-7) < 1e-20 && Math.abs(Math.log10(cf[iff('H+')] * cf[iff('HCO3-')] / cf[iff('CO2')]) + 6.35) < 1e-9
      && Math.abs(totalF / (2.200001e-3 + 1e-9 * rf.t[rf.t.length - 1]) - 1) < 1e-10,
    `carbon ${totalF.toExponential(6)}`);

  // --- held relations beside a fast pair ---
  const mk = RtmModel.compile(carb('always', { kfWater: 1e-3 }));
  const ik = at(mk);
  const rk = FacsimileODE.runModel(mk, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  let heldTwo = 0;
  let pair = 0;
  for (const y of rk.y) {
    const c = mk.toConcentrations(y);
    heldTwo = Math.max(heldTwo, Math.abs(Math.log10(c[ik('H+')] * c[ik('HCO3-')] / c[ik('CO2')]) + 6.35),
      Math.abs(Math.log10(c[ik('H+')] * c[ik('CO3-2')] / c[ik('HCO3-')]) + 10.33));
    pair = Math.max(pair, Math.abs(Math.log10(c[ik('H+')] * c[ik('OH-')]) + 14));
  }
  check('a relation with a kf stays a fast pair beside the two held', mk.nalgebraic === 4 && heldTwo < 1e-9
    && pair < 1e-3, `held ${heldTwo.toExponential(1)}, the pair ${pair.toExponential(1)} in log K`);

  // --- a closed column: what moves between cells, conserved over them ---
  const col = `
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 0.01
GRID = log
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 2e4
EQUILIBRATE = always

<SPECIES>
H+      1e-7   D=9.3e-9
OH-     1e-7   D=5.3e-9
CO2     2e-4   D=1.9e-9
HCO3-   2e-3   D=1.2e-9
CO3-2   1e-9   D=0.9e-9

<INITIAL>
H+  0-4  3e-3

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33

<REACTIONS>
`;
  const mc = RtmModel.compile(col);
  const ic = at(mc);
  const nsC = mc.speciesNames.length;
  const rc = FacsimileODE.runModel(mc, { solver: 'ndf', tend: 2e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const w = mc.grid.width;
  const totals = (y) => {
    const c = mc.toConcentrations(y);
    let carbonT = 0;
    let protons = 0;
    for (let k = 0; k < mc.cells; k++) {
      const b = k * nsC;
      carbonT += w[k] * (c[b + ic('CO2')] + c[b + ic('HCO3-')] + c[b + ic('CO3-2')]);
      protons += w[k] * (c[b + ic('H+')] - c[b + ic('OH-')] - c[b + ic('HCO3-')] - 2 * c[b + ic('CO3-2')]);
    }
    return [carbonT, protons];
  };
  const [c0T, p0T] = totals(rc.y[0]);
  let colWorst = 0;
  let colRel = 0;
  for (const y of rc.y) {
    const [cT, pT] = totals(y);
    colWorst = Math.max(colWorst, Math.abs(cT / c0T - 1), Math.abs((pT - p0T) / c0T));
    const c = mc.toConcentrations(y);
    for (let k = 0; k < mc.cells; k++) {
      const b = k * nsC;
      colRel = Math.max(colRel, Math.abs(Math.log10(c[b + ic('H+')] * c[b + ic('OH-')]) + 14));
    }
  }
  check('a closed column, species diffusing at five rates: carbon and protons conserved over it',
    colWorst < 1e-10, `${colWorst.toExponential(1)} relative, ${rc.t.length} points`);
  check('  and every cell on its relations all the while', colRel < 1e-9, `${colRel.toExponential(1)} in log K`);
  const vc = RtmModel.verifyJacobian(mc, 0, mc.initialState());
  check('  its Jacobian, transport between cells included', vc.discrepancies.length === 0, `${vc.checked} entries`);
}

/* ======================================================================
   2y. Activity (ACTIVITY = davies | debye-huckel)

   The activity coefficients are PHREEQC's rule, so the checks are the rule
   worked out here by hand, PHREEQC's own A and B, and the relations holding
   in activities wherever the page uses them: the start, held throughout, and
   a fast pair. The comparison with PHREEQC itself is in test-phreeqc.js.
   ====================================================================== */
console.log('\n--- activity ---');
{
  check('a charge is read from the end of the name', [['H+', 1], ['SO4-2', -2], ['UO2+2', 2], ['e-', -1],
    ['CO2', 0], ['Fe(OH)2+', 1], ['UO2(CO3)3-4', -4]].every(([n, z]) => RtmModel.chargeOf(n) === z));
  // PHREEQC 3.8.6's DH_A and DH_B, asked of it at these temperatures.
  const ab25 = RtmModel.debyeHuckelAB(25);
  const ab15 = RtmModel.debyeHuckelAB(15);
  check('A and B from the temperature, as PHREEQC works them out (25 and 15 C)',
    Math.abs(ab25.A / 0.5100247894 - 1) < 1e-9 && Math.abs(ab25.B / 0.3284906340 - 1) < 1e-9
      && Math.abs(ab15.A / 0.5017022572 - 1) < 1e-9 && Math.abs(ab15.B / 0.3269184571 - 1) < 1e-9,
    `A ${ab25.A.toFixed(10)}, B ${ab25.B.toFixed(10)} at 25 C`);

  // The four forms, by hand, at I = 0.1.
  const sp = (name, opts = {}) => ({ name, z: opts.z ?? null, dha: opts.a ?? null, dhb: opts.b ?? null, line: 1 });
  const species = [sp('Na+'), sp('Ca+2', { a: 5, b: 0.165 }), sp('CO2'), sp('H2O'), sp('X-', { z: 0, b: 0 })];
  const warn = [];
  const act = RtmModel.activityModel({ ACTIVITY: 'debye-huckel', TEMPERATURE: 25, given: new Set() }, species, warn);
  const C = Float64Array.of(0.1, 0, 0.01, 55.5, 0.3);
  const lnG = new Float64Array(5);
  const dG = new Float64Array(5);
  const w = RtmModel.activityAt(act, C, 0, lnG, dG);
  // A and B at the water's activity, 1 - 0.017 times the solutes, as PHREEQC takes them (calc_rho_0).
  const abW = RtmModel.debyeHuckelAB(25, 1, 1 - 0.017 * 0.41);
  const A = abW.A;
  const B = abW.B;
  const sq = Math.sqrt(0.05);
  const want = [-A * (sq / (1 + sq) - 0.3 * 0.05), -A * 4 * sq / (1 + B * 5 * sq) + 0.165 * 0.05, 0.1 * 0.05, 0, 0];
  check('Davies, WATEQ with a and b, b I for a neutral species, 1 for the water and for z=0 b=0, A and B at the '
    + 'water\'s activity',
    Math.abs(w.I - 0.05) < 1e-15 && want.every((v, i) => Math.abs(lnG[i] / Math.LN10 - v) < 1e-14),
    `I ${w.I}, log gamma ${Array.from(lnG, (v) => (v / Math.LN10).toFixed(6)).join(' ')}`);
  check('  a(H2O) = 1 - 0.017 times the solutes, the water itself left out',
    Math.abs(Math.exp(w.lnAw) - (1 - 0.017 * 0.41)) < 1e-15, Math.exp(w.lnAw).toFixed(8));
  // d(ln gamma)/dI against a difference.
  let dWorst = 0;
  for (let i = 0; i < 5; i++) {
    const h = 1e-6;
    const up = Float64Array.from(C);
    const dn = Float64Array.from(C);
    up[0] += 2 * h;                       // Na+: I moves by h
    dn[0] -= 2 * h;
    const g1 = new Float64Array(5);
    const g2 = new Float64Array(5);
    RtmModel.activityAt(act, up, 0, g1, new Float64Array(5));
    RtmModel.activityAt(act, dn, 0, g2, new Float64Array(5));
    dWorst = Math.max(dWorst, Math.abs((g1[i] - g2[i]) / (2 * h) - dG[i]) / Math.max(Math.abs(dG[i]), 1));
  }
  check('  and their derivatives in I, against differences', dWorst < 1e-7, dWorst.toExponential(1));

  // The settings.
  const water = (more) => `
<SETTINGS>
MODE = batch
TEND = 1e5
${more}

<SPECIES>
H+      1e-7    a=9
OH-     1e-7    a=3.5
CO2     2e-4
HCO3-   2e-3    a=5.4
CO3-2   1e-9    a=5.4
Na+     0.1     a=4.08  b=0.082
Cl-     0.098   a=3.63  b=0.017

<EQUILIBRIUM>
H2O <=> H+ + OH-,          logK = -14.3433
CO2 + H2O <=> H+ + HCO3-,  logK = -6.4180
HCO3- <=> H+ + CO3-2,      logK = -10.4284

<REACTIONS>
`;
  let refused = '';
  try { RtmModel.compile(water('ACTIVITY = truesdell')); } catch (e) { refused = e.message; }
  check('ACTIVITY is none, davies, debye-huckel, sit, pitzer or llnl',
    /ACTIVITY must be one of none, davies, debye-huckel.*sit, pitzer, llnl/.test(refused), refused);
  check('  and debye-hückel is debye-huckel', RtmModel.compile(water('ACTIVITY = debye-hückel')).act.kind === 'debye-huckel');
  refused = '';
  try { RtmModel.compile(water('ACTIVITY = davies\nTEMPERATURE = 400')); } catch (e) { refused = e.message; }
  check('  TEMPERATURE outside 0 to 350 C is refused', /0 to 350 C/.test(refused), refused);
  check('  TEMPERATURE with no ACTIVITY says it does nothing',
    RtmModel.compile(water('TEMPERATURE = 15')).warnings.some((x) => /TEMPERATURE sets/.test(x)));
  check('  and ACTIVITY with no EQUILIBRATE and no kf says nothing uses it',
    RtmModel.compile(water('ACTIVITY = davies')).warnings.some((x) => /nothing uses it/.test(x)));
  refused = '';
  try { RtmModel.compile(water('').replace('Na+     0.1     a=4.08', 'Na+     0.1     z=1.5')); } catch (e) { refused = e.message; }
  check('  a charge that is no whole number is refused', /a charge is a whole number/.test(refused), refused);

  // H2O in a relation: nothing without ACTIVITY; a(H2O) with it.
  const plain = RtmModel.compile(water('EQUILIBRATE = 1').replace(/^H2O <=>/m, ' <=>').replace('CO2 + H2O <=>', 'CO2 <=>'));
  const wet = RtmModel.compile(water('EQUILIBRATE = 1'));
  const y0 = plain.initialState();
  const y1 = wet.initialState();
  check('H2O in a relation is the water: without ACTIVITY it changes nothing',
    y0.every((v, i) => v === y1[i]) && wet.equilibria[0].water === -1 && wet.equilibria[1].water === -1,
    `water ${wet.equilibria.map((e) => e.water).join(', ')}`);

  // Every relation in activities, worked out apart from the page's own code.
  const gammaOf = { 'H+': [1, 9, 0], 'OH-': [-1, 3.5, 0], CO2: [0, null, 0.1], 'HCO3-': [-1, 5.4, 0],
    'CO3-2': [-2, 5.4, 0], 'Na+': [1, 4.08, 0.082], 'Cl-': [-1, 3.63, 0.017] };
  const logA = (m, c) => {
    let I = 0;
    let sum = 0;
    m.speciesNames.forEach((n, i) => { I += 0.5 * gammaOf[n][0] ** 2 * c[i]; sum += c[i]; });
    const s = Math.sqrt(I);
    const ab = RtmModel.debyeHuckelAB(15, 1, 1 - 0.017 * sum);
    const la = { H2O: Math.log10(1 - 0.017 * sum) };
    m.speciesNames.forEach((n, i) => {
      const [z, a, b] = gammaOf[n];
      la[n] = Math.log10(c[i]) + (z === 0 ? b * I : -ab.A * z * z * s / (1 + ab.B * a * s) + b * I);
    });
    return { la, I };
  };
  const off = (la) => Math.max(Math.abs(la['H+'] + la['OH-'] - la.H2O + 14.3433),
    Math.abs(la['H+'] + la['HCO3-'] - la.CO2 - la.H2O + 6.4180), Math.abs(la['H+'] + la['CO3-2'] - la['HCO3-'] + 10.4284));
  const settings = 'ACTIVITY = debye-huckel\nTEMPERATURE = 15';
  const start = RtmModel.compile(water(`EQUILIBRATE = 1\n${settings}`));
  const c0 = start.initialState();
  check('the start speciated in activities: every relation, the water in two of them',
    off(logA(start, c0).la) < 1e-12 && Math.abs((c0[2] + c0[3] + c0[4]) / 2.200001e-3 - 1) < 1e-14,
    `${off(logA(start, c0).la).toExponential(1)} in log K at I = ${logA(start, c0).I.toFixed(4)}`);

  // Held throughout, while salt raises the ionic strength from 0.1 to 0.5.
  const held = RtmModel.compile(`${water(`EQUILIBRATE = always\n${settings}`)}=> Na+ + Cl-, k = 4e-6\n`);
  const run = FacsimileODE.runModel(held, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  let worst = 0;
  let carbon = 0;
  for (const y of run.y) {
    const c = held.toConcentrations(y);
    worst = Math.max(worst, off(logA(held, c).la));
    carbon = Math.max(carbon, Math.abs((c[2] + c[3] + c[4]) / 2.200001e-3 - 1));
  }
  const cEnd = held.toConcentrations(run.y[run.y.length - 1]);
  check('held throughout as salt raises I from 0.1 to 0.5: every stored point on every relation, in activities',
    worst < 1e-12 && logA(held, cEnd).I > 0.49, `${worst.toExponential(1)} in log K over ${run.t.length} points, `
      + `I ${logA(held, cEnd).I.toFixed(3)} at the end`);
  check('  carbon conserved', carbon < 1e-12, carbon.toExponential(1));
  const vh0 = RtmModel.verifyJacobian(held, 0, held.initialState());
  const vh1 = RtmModel.verifyJacobian(held, 1e5, run.y[run.y.length - 1]);
  check('  the Jacobian, the ionic strength and the water included, at the start and the end',
    vh0.discrepancies.length === 0 && vh1.discrepancies.length === 0, `${vh0.checked} and ${vh1.checked} entries`);
  {
    /*
      A AND B AT THE WATER'S ACTIVITY in a hot brine: held throughout, the
      cells speciated in their components (an iron couple tied to the
      electron) and whole (the same couple untied, which changes nothing else):
      the same run, the water's ln a an unknown of the components' speciation
      wherever A and B read it; and at the end every coefficient the closed
      form at the water's own a(H2O).
    */
    const brine = (elec) => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1e4\nACTIVITY = debye-huckel\nEQUILIBRATE = always\n`
      + `TEMPERATURE = 90\n\n<SPECIES>\nH+ 1e-7 a=9\nOH- 1e-7 a=3.5\nNa+ 3 a=4.08 b=0.082\nCl- 3 a=3.63 b=0.017\nCO2 1e-3\n`
      + `HCO3- 1e-3 a=5.4\nCO3-2 1e-6 a=5.4\nFe+2 1e-4 a=6\nFe+3 1e-6 a=9\n${elec ? 'e- electron\n' : ''}\n<EQUILIBRIUM>\n`
      + 'H2O <=> H+ + OH-, logK = -12.4\nCO2 + H2O <=> H+ + HCO3-, logK = -6.3\nHCO3- <=> H+ + CO3-2, logK = -10.1\n'
      + `${elec ? 'Fe+2 <=> Fe+3 + e-, logK = -13\n' : ''}\n<REACTIONS>\n=> Na+ + Cl-, k = 1e-4\n=> CO2, k = 1e-8\n`);
    const times = [10, 3000, 9999];
    const ends = [false, true].map((elec) => {
      const m = brine(elec);
      const r = FacsimileODE.runModel(m, { solver: 'ndf', rtol: 1e-10, atol: 1e-18, tend: 1e4, outputTimes: times });
      return { m, c: times.map((t, k) => m.toConcentrations(r.grid.y[k], t)) };
    });
    let same = 0;
    for (let k = 0; k < times.length; k++) {
      for (const n of ['H+', 'OH-', 'Na+', 'CO2', 'HCO3-', 'CO3-2']) {
        const i0 = ends[0].m.speciesNames.indexOf(n);
        const i1 = ends[1].m.speciesNames.indexOf(n);
        same = Math.max(same, Math.abs(ends[1].c[k][i1] / ends[0].c[k][i0] - 1));
      }
    }
    const m0 = ends[0].m;
    const c = ends[0].c[2];
    const ns = m0.speciesNames.length;
    const lnG = new Float64Array(ns);
    const w = RtmModel.activityAt(m0.act, c, 0, lnG, new Float64Array(ns), 0);
    let sum = 0;
    let I = 0;
    m0.speciesNames.forEach((n, i) => { sum += c[i]; I += 0.5 * RtmModel.chargeOf(n) ** 2 * c[i]; });
    const aw = 1 - 0.017 * sum;
    const ab = RtmModel.debyeHuckelAB(90, 1, aw);
    const ab1 = RtmModel.debyeHuckelAB(90);
    const sq = Math.sqrt(I);
    const gNa = Math.LN10 * (-ab.A * sq / (1 + ab.B * 4.08 * sq) + 0.082 * I);
    check('A and B at the water\'s activity: a 3 to 4 mol/kgw brine at 90 C held throughout, speciated in its components '
      + 'and whole, the same run, and its coefficients the closed form at its own a(H2O)', same < 1e-9
      && Math.abs(lnG[m0.speciesNames.indexOf('Na+')] - gNa) < 1e-13 && Math.abs(w.lnAw - Math.log(aw)) < 1e-15
      && Math.abs(ab.A / ab1.A - 1) > 1e-7,
    `the two within ${same.toExponential(1)}; a(H2O) ${aw.toFixed(5)}, A ${(ab.A / ab1.A - 1).toExponential(2)} from a(H2O) = 1's, `
      + `ln gamma(Na+) within ${Math.abs(lnG[m0.speciesNames.indexOf('Na+')] - gNa).toExponential(1)}`);
  }
  // The end apart: a fresh speciation of the totals the end has.
  const tEnd = run.t[run.t.length - 1];
  const apartText = water(`EQUILIBRATE = 1\n${settings}`)
    .replace('Na+     0.1 ', `Na+     ${0.1 + 4e-6 * tEnd} `).replace('Cl-     0.098 ', `Cl-     ${0.098 + 4e-6 * tEnd} `);
  const apart = RtmModel.compile(apartText).initialState();
  let apartWorst = 0;
  for (let i = 0; i < apart.length; i++) apartWorst = Math.max(apartWorst, Math.abs(cEnd[i] / apart[i] - 1));
  check('  and the end is the speciation, in activities, of the totals the end has', apartWorst < 1e-7,
    `${apartWorst.toExponential(1)} relative`);
  // The same with the constants fixed where the water started: how much activity matters here.
  const fixedPh = -Math.log10(RtmModel.compile(apartText.replace(settings, '')).initialState()[0]);
  check('  where concentrations alone would put -log[H+] elsewhere', Math.abs(fixedPh + Math.log10(cEnd[0])) > 0.05,
    `${(-Math.log10(cEnd[0])).toFixed(4)} in activities, ${fixedPh.toFixed(4)} without`);

  // A fast pair: its backward constant follows I, and it relaxes to K in activities.
  const pair = RtmModel.compile(`${water(`EQUILIBRATE = 1\n${settings}`).replace('logK = -14.3433', 'logK = -14.3433, kf = 1e3')}`
    + '=> Na+ + Cl-, k = 4e-6\n');
  const vp0 = RtmModel.verifyJacobian(pair, 0, pair.initialState());
  const rp = FacsimileODE.runModel(pair, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const pEnd = rp.y[rp.y.length - 1];
  const vp1 = RtmModel.verifyJacobian(pair, 1e5, pEnd);
  const la = logA(pair, pEnd).la;
  check('a fast pair relaxes to its K in activities, and its Jacobian follows I',
    Math.abs(la['H+'] + la['OH-'] - la.H2O + 14.3433) < 1e-8 && vp0.discrepancies.length === 0
      && vp1.discrepancies.length === 0 && !pair.jacobianConstant,
    `${(la['H+'] + la['OH-'] - la.H2O + 14.3433).toExponential(1)} in log K; ${vp0.checked} entries`);

  // A column, the relations held in every cell: the Jacobian across cells.
  const col = RtmModel.compile(water(`EQUILIBRATE = always\n${settings}`)
    .replace('MODE = batch', 'MODE = transport\nCELLS = 6\nLENGTH = 0.01\nDIFFUSION = 1')
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)(.*)$/gm, (m0, n, s1, v, rest) => `${n}${s1}${v}${rest}  D=1e-9`));
  const colY = col.initialState();
  for (let k = 0; k < colY.length; k++) colY[k] += 1e-3 * Math.sin(k);
  const vc = RtmModel.verifyJacobian(col, 0, colY);
  check('  and in a column with every relation held, the Jacobian across the cells', vc.discrepancies.length === 0
    && col.nalgebraic === 6 * 5, `${vc.checked} entries`);
}

/* ======================================================================
   2z. Minerals at saturation (`mineral`)

   A mineral is a pure phase: activity 1, its amount free to reach zero. Held
   (EQUILIBRATE = always), its saturation is a relation while there is any of
   it, and the run stops where the last of it dissolves or the water becomes
   supersaturated. So the checks are the saturation index at every stored
   point, the totals the mineral counts in, and each event's instant against
   a speciation of the totals there.
   ====================================================================== */
console.log('\n--- minerals at saturation ---');
{
  const water = (opts = {}) => `
<SETTINGS>
MODE = batch
TEND = ${opts.tend || 2e5}
EQUILIBRATE = ${opts.eq || 'always'}
${opts.settings || ''}

<SPECIES>
H+      1e-7
OH-     1e-7
CO2     1e-4
HCO3-   2e-3
CO3-2   ${opts.co3 || '1e-5'}
Ca+2    ${opts.ca || '1e-3'}
Cl-     ${opts.cl || '1e-4'}
Calcite ${opts.calcite ?? '5e-4'}   mineral

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33
${opts.relation || 'Calcite <=> Ca+2 + CO3-2, logK = -8.48'}

<REACTIONS>
${opts.rx || ''}
`;
  const iCa = 5;
  const iCO3 = 4;
  const iCal = 7;
  const si = (c) => Math.log10(c[iCa] * c[iCO3]) + 8.48;
  const caT = (c) => c[iCa] + c[iCal];
  const cT = (c) => c[2] + c[3] + c[4] + c[iCal];

  // --- what a mineral line may say, and what a relation with one may ---
  const refusal = (text) => { try { RtmModel.compile(text); return ''; } catch (e) { return e.message; } };
  check('a mineral is immobile and never held: D on one is refused',
    /Calcite is a mineral, which stays where it is and is never held: it takes no D/.test(
      refusal(water().replace('Calcite 5e-4   mineral', 'Calcite 5e-4   mineral  D=1e-9'))));
  check('  two minerals in one relation are refused', /two minerals/.test(refusal(water({
    relation: 'Calcite <=> Ca+2 + CO3-2, logK = -8.48\nAragonite <=> Calcite, logK = -0.1' })
    .replace('Calcite 5e-4   mineral', 'Calcite 5e-4   mineral\nAragonite 0   mineral'))));
  check('  a mineral in two relations is refused', /in two relations/.test(refusal(water({
    relation: 'Calcite <=> Ca+2 + CO3-2, logK = -8.48\nCalcite + H+ <=> Ca+2 + HCO3-, logK = 1.85' }))));
  check('  a mineral is no fast pair', /is not a fast pair/.test(refusal(water({
    relation: 'Calcite <=> Ca+2 + CO3-2, logK = -8.48, kf = 1' }))));
  check('  and is never held in some cells', /a mineral is never held/.test(refusal(`${water()}\n<INITIAL>\nCalcite 0-0 1e-3 fixed\n`
    .replace('MODE = batch', 'MODE = batch'))));

  // --- immobile: a species no column carries ---
  const column = (word) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 1
ADVECTION = 1
VELOCITY = 1e-3
LEFT = robin
RIGHT = free
TEND = 500

<SPECIES>
Site   0   ${word}
Tr     0   D=1e-9  left=1

<INITIAL>
Site 0-4 1
`);
  const carried = FacsimileODE.runModel(column(''), { solver: 'ndf', tend: 500, rtol: 1e-6, atol: 1e-12 });
  const stays = FacsimileODE.runModel(column('immobile'), { solver: 'ndf', tend: 500, rtol: 1e-6, atol: 1e-12 });
  const siteAt = (r, c) => r.y[r.y.length - 1][c * 2];
  check('under advection a species with no D is carried; `immobile` stays where it is',
    siteAt(carried, 9) > 0.1 && siteAt(stays, 0) === 1 && siteAt(stays, 9) === 0,
    `cell 9: ${siteAt(carried, 9).toFixed(3)} carried, ${siteAt(stays, 9)} immobile`);

  // --- the start: precipitated to saturation, or dissolved away ---
  const sup = RtmModel.compile(water({ eq: 1 })).initialState();
  check('a supersaturated start precipitates calcite to saturation, Ca and C conserved',
    Math.abs(si(sup)) < 1e-12 && sup[iCal] > 5e-4 && Math.abs(caT(sup) / 1.5e-3 - 1) < 1e-14
      && Math.abs(cT(sup) / 2.61e-3 - 1) < 1e-14, `calcite ${sup[iCal].toExponential(4)}, SI ${si(sup).toExponential(1)}`);
  const sub = RtmModel.compile(water({ eq: 1, co3: '1e-7', ca: '1e-5', calcite: '1e-6' })).initialState();
  check('  an undersaturated one dissolves what little there is, and stays undersaturated',
    sub[iCal] === 0 && si(sub) < -1 && Math.abs(caT(sub) / (1e-5 + 1e-6) - 1) < 1e-14,
    `calcite ${sub[iCal]}, SI ${si(sub).toFixed(3)}`);

  // --- held: acid dissolves the calcite away ---
  const m = RtmModel.compile(water({ rx: '=> H+ + Cl-, k = 1e-8' }));
  check('held, the mineral is one event in its cell', m.nevents === 1 && m.heldEquilibria.minerals === 1);
  const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 2e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const c0 = m.toConcentrations(r.y[0]);
  let onSat = 0;
  let below = -Infinity;
  let totals = 0;
  for (const y of r.y) {
    const c = m.toConcentrations(y);
    if (c[iCal] > 0) onSat = Math.max(onSat, Math.abs(si(c))); else below = Math.max(below, si(c));
    totals = Math.max(totals, Math.abs(caT(c) / caT(c0) - 1), Math.abs(cT(c) / cT(c0) - 1));
  }
  const ev = r.events[0];
  check('acid: at saturation while there is calcite, Ca and C conserved with it',
    onSat < 1e-12 && totals < 1e-12, `|SI| ${onSat.toExponential(1)}, totals ${totals.toExponential(1)}`);
  check('  one event, where the last of it dissolves, and undersaturated after',
    r.events.length === 1 && ev.expr === 'Calcite has dissolved away' && below < 1e-8
      && si(m.toConcentrations(r.y[r.y.length - 1])) < -1,
    `${ev && ev.expr} at t = ${ev && ev.t.toFixed(1)}; SI with none at most ${below.toExponential(1)}`);
  // The event's instant, apart: the start with all its calcite in the water
  // and the acid added by then, speciated afresh, is just saturated and has
  // none of it -- a little earlier there would be some left, a little later
  // the water would be undersaturated.
  const tE = ev.t;
  const names = ['H+', 'OH-', 'CO2', 'HCO3-', 'CO3-2', 'Ca+2', 'Cl-'];
  const moved = Float64Array.from(c0);
  moved[0] += 1e-8 * tE;
  moved[6] += 1e-8 * tE;
  moved[iCO3] += c0[iCal];
  moved[iCa] += c0[iCal];
  moved[iCal] = 0;
  let atText = water({ eq: 1, calcite: '0' });
  names.forEach((nm, i) => {
    atText = atText.replace(new RegExp(`^${nm.replace(/[+]/g, '\\+')}( +)\\S+$`, 'm'), `${nm}$1${moved[i]}`);
  });
  const atE = RtmModel.compile(atText).initialState();
  check('  the event instant: the water there is just saturated, with none of the mineral',
    Math.abs(si(atE)) < 1e-7 && atE[iCal] < 1e-10 * caT(c0), `SI ${si(atE).toExponential(1)} with calcite ${atE[iCal].toExponential(1)}`);
  const vA = RtmModel.verifyJacobian(m, 0, m.initialState());
  const vB = RtmModel.verifyJacobian(m, 2e5, r.y[r.y.length - 1]);
  check('  the Jacobian with the mineral there, and with none', vA.discrepancies.length === 0
    && vB.discrepancies.length === 0, `${vA.checked} and ${vB.checked} entries`);
  // A point stored while there was calcite is read back with it, whatever the run went on to.
  const early = m.toConcentrations(r.y[Math.floor(r.y.length / 4)]);
  check('  a point stored before the event is read back as it was', early[iCal] > 0 && Math.abs(si(early)) < 1e-12,
    `calcite ${early[iCal].toExponential(3)}`);

  // --- precipitation: a Ca source into an undersaturated water ---
  const mp = RtmModel.compile(water({ co3: '1e-6', ca: '1e-5', cl: '2e-5', calcite: '0', rx: '=> Ca+2 + Cl- + Cl-, k = 1e-8' }));
  const rp = FacsimileODE.runModel(mp, { solver: 'ndf', tend: 2e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const cp = mp.toConcentrations(rp.y[rp.y.length - 1]);
  check('a Ca source into an undersaturated water: calcite precipitates where it saturates, and stays there',
    rp.events.length === 1 && rp.events[0].expr === 'Calcite precipitates' && Math.abs(si(cp)) < 1e-12 && cp[iCal] > 0,
    `${rp.events.map((e) => `${e.expr} at ${e.t.toFixed(0)}`).join(', ')}; calcite ${cp[iCal].toExponential(3)}`);

  // --- a column: an acid front dissolves the calcite cell by cell ---
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 0.1
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1e-6
PECLET = 20
LEFT = robin
RIGHT = free
TEND = 3e5
EQUILIBRATE = always

<SPECIES>
H+      1e-7    D=1e-9  left=3e-3
OH-     1e-7    D=1e-9
CO2     1e-4    D=1e-9
HCO3-   2e-3    D=1e-9
CO3-2   1e-5    D=1e-9
Ca+2    1e-3    D=1e-9
Cl-     1e-4    D=1e-9  left=3.1e-3
Calcite 2e-4    mineral

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33
Calcite <=> Ca+2 + CO3-2, logK = -8.48
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: 3e5, rtol: 1e-6, atol: 1e-20, nonNegative: true });
  const order = rc.events.map((e) => Number(/cell (\d+)/.exec(e.expr)[1]));
  const vc = RtmModel.verifyJacobian(col, 3e5, rc.y[rc.y.length - 1]);
  check('a column: the acid front dissolves the calcite cell by cell, in order, and the Jacobian holds',
    rc.events.length === 10 && order.every((c, k) => c === k) && vc.discrepancies.length === 0,
    `${rc.events.length} events, cells ${order.join(' ')}; ${vc.checked} entries`);
  // Every stored point read back as the run had it, cell by cell: at
  // saturation wherever there is calcite, and none at all where there is not
  // -- not the 1e-29 a damped step leaves, nor a cell left unsettled because
  // one before it missed a tolerance under rounding.
  let offSat = 0;
  let crumbs = 0;
  let unsettled = 0;
  for (const y of rc.y) {
    const c = col.toConcentrations(y);
    if (!col.consistentInitial(0, Float64Array.from(y), { rtol: 1e-12, fromState: true }).solved) unsettled++;
    for (let k = 0; k < 10; k++) {
      const b = k * 8;
      if (c[b + 7] > 0) offSat = Math.max(offSat, Math.abs(Math.log10(c[b + 5] * c[b + 4]) + 8.48));
      if (c[b + 7] > 0 && c[b + 7] < 1e-12) crumbs++;
    }
  }
  check('  every stored point read back: at saturation where there is calcite, none at all where there is not',
    offSat < 1e-12 && crumbs === 0 && unsettled === 0,
    `|SI| ${offSat.toExponential(1)}; ${crumbs} crumbs, ${unsettled} unsettled of ${rc.y.length}`);

  // --- activities ---
  const ma = RtmModel.compile(water({ settings: 'ACTIVITY = debye-huckel', rx: '=> H+ + Cl-, k = 1e-8', tend: 5e4 }));
  const ra = FacsimileODE.runModel(ma, { solver: 'ndf', tend: 5e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  let siAct = 0;
  const lnG = new Float64Array(8);
  for (const y of ra.y) {
    const c = ma.toConcentrations(y);
    if (!(c[iCal] > 0)) continue;
    RtmModel.activityAt(ma.act, c, 0, lnG, new Float64Array(8));
    siAct = Math.max(siAct, Math.abs((Math.log(c[iCa]) + lnG[iCa] + Math.log(c[iCO3]) + lnG[iCO3]) / Math.LN10 + 8.48));
  }
  check('with ACTIVITY the saturation is in activities, the mineral at 1',
    siAct < 1e-12 && RtmModel.verifyJacobian(ma, 0, ma.initialState()).discrepancies.length === 0, siAct.toExponential(1));
}

/* ======================================================================
   2w. Limited advection (ADVECTION_SCHEME = limited)

   A front at a Peclet number of 400 against van Genuchten and Alves's
   closed solution for the flux inlet, beside upwinding on the same grids:
   sharper, closer to second order as the cells are refined, nothing below
   zero, and a Jacobian a difference of the state agrees with.
   ====================================================================== */
console.log('\n--- limited advection ---');
{
  const erfcRel = (x) => {
    const z = Math.abs(x);
    const t = 1 / (1 + 0.5 * z);
    const y = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196
      + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398
        + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? y : 2 - y;
  };
  const flux3 = (x, t, v, d) => {
    const A = 0.5 * erfcRel((x - v * t) / (2 * Math.sqrt(d * t)));
    const B = Math.sqrt((v * v * t) / (Math.PI * d)) * Math.exp(-((x - v * t) ** 2) / (4 * d * t));
    const e = (v * x) / d;
    const C = e > 700 ? 0
      : 0.5 * (1 + e + (v * v * t) / d) * Math.exp(e) * erfcRel((x + v * t) / (2 * Math.sqrt(d * t)));
    return A + B - C;
  };
  const v = 1e-3;
  const T = 500;
  const front = (n, scheme) => {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${n}
LENGTH = 1
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = ${scheme}
VELOCITY = ${v}
PECLET = 400
LEFT = robin
RIGHT = free
TEND = ${T}

<SPECIES>
Tr  0  left=1
`);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: T, rtol: 1e-8, atol: 1e-14, nonNegative: true });
    const y = r.y[r.y.length - 1];
    let err = 0;
    let low = Infinity;
    for (let i = 0; i < n; i++) {
      err = Math.max(err, Math.abs(y[i] - flux3(m.grid.centres[i], T, v, v / 400)));
      low = Math.min(low, y[i]);
    }
    return { m, y, err, low };
  };
  const u40 = front(40, 'upwind');
  const l40 = front(40, 'limited');
  const u160 = front(160, 'upwind');
  const l160 = front(160, 'limited');
  check('a front at Pe 400: limited is sharper than upwinding on the same cells',
    l40.err < u40.err / 2 && l160.err < u160.err / 3,
    `largest error ${l40.err.toExponential(2)} against ${u40.err.toExponential(2)} at 40 cells, `
      + `${l160.err.toExponential(2)} against ${u160.err.toExponential(2)} at 160`);
  check('  and closer to second order: four times the cells take the error down by more than six',
    l40.err / l160.err > 6, `${(l40.err / l160.err).toFixed(1)} times`);
  check('  with nothing below zero', l40.low >= 0 && l160.low >= 0, `${l40.low.toExponential(1)}, ${l160.low.toExponential(1)}`);
  const vl = RtmModel.verifyJacobian(l40.m, T, l40.y);
  check('  and a Jacobian that moves with the state, checked across the front', vl.discrepancies.length === 0
    && !l40.m.jacobianConstant && u40.m.jacobianConstant, `${vl.checked} entries`);
  let word = '';
  try { RtmModel.compile('<SETTINGS>\nADVECTION_SCHEME = tvd\n<SPECIES>\nA 1\n'); } catch (e) { word = e.message; }
  check('  ADVECTION_SCHEME is upwind or limited', /ADVECTION_SCHEME must be one of upwind, limited/.test(word), word);

  // A reactive front: acid dissolving calcite, the relations held, limited.
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 0.1
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
VELOCITY = 1e-6
PECLET = 50
LEFT = robin
RIGHT = free
TEND = 3e5
EQUILIBRATE = always

<SPECIES>
H+      1e-7    D=1e-9  left=3e-3
OH-     1e-7    D=1e-9
CO2     1e-4    D=1e-9
HCO3-   2e-3    D=1e-9
CO3-2   1e-5    D=1e-9
Ca+2    1e-3    D=1e-9
Cl-     1e-4    D=1e-9  left=3.1e-3
Calcite 2e-4    mineral

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33
Calcite <=> Ca+2 + CO3-2, logK = -8.48
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: 3e5, rtol: 1e-6, atol: 1e-20, nonNegative: true });
  const order = rc.events.map((e) => Number(/cell (\d+)/.exec(e.expr)[1]));
  const vc = RtmModel.verifyJacobian(col, rc.t[Math.floor(rc.t.length / 3)], rc.y[Math.floor(rc.y.length / 3)]);
  check('acid dissolving calcite down a column, limited: cell by cell in order, the Jacobian across the front',
    rc.events.length === 10 && order.every((c, k) => c === k) && vc.discrepancies.length === 0,
    `${rc.events.length} events, cells ${order.join(' ')}; ${vc.checked} entries, ${vc.discrepancies.length} off`
      + `${vc.discrepancies.length ? ` ${JSON.stringify(vc.discrepancies.slice(0, 3))}` : ''}`);
}

/* ======================================================================
   2v. Activities and saturation in rate laws ({X}, I, SI, SR, <PHASES>)

   A rate law may read an activity, the ionic strength, or the saturation of
   a phase. The checks: each against the same quantity worked out apart, a
   kinetic mineral that ends where holding it at saturation puts it, and the
   Jacobian through all of them (the PHREEQC KINETICS comparison is in
   test-phreeqc.js).
   ====================================================================== */
console.log('\n--- activities and saturation in rate laws ---');
{
  const water = (extra, rx, opts = {}) => `
<SETTINGS>
MODE = batch
TEND = 1e6
EQUILIBRATE = always
ACTIVITY = ${opts.activity || 'debye-huckel'}

<SPECIES>
H+      1e-7    a=9
OH-     1e-7    a=3.5
CO2     1e-4
HCO3-   2e-3    a=5.4
CO3-2   1e-5    a=5.4
Ca+2    1e-4    a=5  b=0.165
Na+     2e-3    a=4.08  b=0.082
Cl-     1e-4    a=3.63  b=0.017
${extra}

<EQUILIBRIUM>
H2O <=> H+ + OH-,          logK = -14
CO2 + H2O <=> H+ + HCO3-,  logK = -6.35
HCO3- <=> H+ + CO3-2,      logK = -10.33
${opts.relations || ''}

<PHASES>
${opts.phases !== undefined ? opts.phases : 'Calcite <=> Ca+2 + CO3-2,  logK = -8.48'}

<REACTIONS>
${rx}
${opts.params ? `\n<PARAMETERS>\n${opts.params}\n` : ''}`;
  const rateOf = (m, name) => {
    const f = new Float64Array(m.nspecies);
    m.rhs(0, m.initialState(), f);
    return f[m.speciesNames.indexOf(name)];
  };
  const m1 = RtmModel.compile(water('X 0', '=> X, r = 2*{H+}*{Ca+2}'));
  const c1 = m1.toConcentrations(m1.initialState());
  const lnG = new Float64Array(9);
  const w1 = RtmModel.activityAt(m1.act, c1, 0, lnG, new Float64Array(9));
  const iCa = m1.speciesNames.indexOf('Ca+2');
  check('{X} in a rate law is the activity: 2 {H+}{Ca+2} against the coefficients worked out apart',
    Math.abs(rateOf(m1, 'X') / (2 * c1[0] * Math.exp(lnG[0]) * c1[iCa] * Math.exp(lnG[iCa])) - 1) < 1e-14
      && RtmModel.verifyJacobian(m1, 0, m1.initialState()).discrepancies.length === 0,
    `${rateOf(m1, 'X').toExponential(6)}, gamma(Ca+2) ${Math.exp(lnG[iCa]).toFixed(5)}`);
  const m2 = RtmModel.compile(water('X 0', '=> X, r = I'));
  check('  I is the ionic strength of the cell', Math.abs(rateOf(m2, 'X') / w1.I - 1) < 1e-14, w1.I.toExponential(6));
  const m2p = RtmModel.compile(water('X 0', '=> X, r = I', { params: 'I all 7' }));
  check('  unless the text has a parameter called I', rateOf(m2p, 'X') === 7);
  const m3 = RtmModel.compile(water('X 0', '=> X, r = {Ca+2}', { activity: 'none' }).replace(/ [ab]=[0-9.]+/g, ''));
  check('  and without ACTIVITY an activity is the concentration', rateOf(m3, 'X') === 1e-4);

  // A mineral that dissolves at a rate, k (1 - SR), ends where holding it puts it.
  const kin = RtmModel.compile(water('Calcite 0.01 mineral',
    'Calcite => Ca+2 + CO3-2, r = k*(1 - SR(Calcite)), k = 1e-7'));
  const rk = FacsimileODE.runModel(kin, { solver: 'ndf', tend: 1e6, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const ck = kin.toConcentrations(rk.y[rk.y.length - 1]);
  const held = RtmModel.compile(water('Calcite 0.01 mineral', '',
    { relations: 'Calcite <=> Ca+2 + CO3-2, logK = -8.48', phases: '' }));
  const ch = held.toConcentrations(held.initialState());
  const iCal = kin.speciesNames.indexOf('Calcite');
  let apart = 0;
  for (let i = 0; i < ck.length; i++) apart = Math.max(apart, Math.abs(ck[i] / ch[i] - 1));
  const vk0 = RtmModel.verifyJacobian(kin, 0, kin.initialState());
  const vk1 = RtmModel.verifyJacobian(kin, 1e6, rk.y[rk.y.length - 1]);
  check('calcite dissolving at k (1 - SR) ends on the state calcite held at saturation has',
    apart < 1e-9 && vk0.discrepancies.length === 0 && vk1.discrepancies.length === 0,
    `${(0.01 - ck[iCal]).toExponential(5)} mol dissolved, every species within ${apart.toExponential(1)}; `
      + `${vk0.checked} and ${vk1.checked} entries`);
  const siRate = RtmModel.compile(water('X 0', '=> X, r = SI(Calcite)'));
  const cs = siRate.toConcentrations(siRate.initialState());
  const lnGs = new Float64Array(9);
  RtmModel.activityAt(siRate.act, cs, 0, lnGs, new Float64Array(9));
  const siApart = (Math.log(cs[iCa]) + lnGs[iCa] + Math.log(cs[4]) + lnGs[4]) / Math.LN10 + 8.48;
  check('  SI(Calcite) is log(IAP/K) in activities', Math.abs(rateOf(siRate, 'X') - siApart) < 1e-13,
    rateOf(siRate, 'X').toFixed(6));
  const fromEq = RtmModel.compile(water('Calcite 0.01 mineral\nX 0', '=> X, r = SI(Calcite)',
    { relations: 'Calcite <=> Ca+2 + CO3-2, logK = -8.48', phases: '' }));
  check('  and of a mineral held in <EQUILIBRIUM>, 0 while there is any', Math.abs(rateOf(fromEq, 'X')) < 1e-12);
  const refused = (rx) => { try { RtmModel.compile(water('X 0', rx)); return ''; } catch (e) { return e.message; } };
  check('  a phase that is nowhere is refused, and says where to give it',
    /SI\(Nope\): "Nope" is no phase. Give its dissolution in <PHASES>/.test(refused('=> X, r = SI(Nope)')));
}

/* ======================================================================
   2u. Diffusion that keeps the charge (DIFFUSION = nernst-planck)

   A step of HCl in a closed column: coupled, H+ and Cl- spread together at
   the ambipolar coefficient 2 D_H D_Cl/(D_H + D_Cl) and the water stays
   neutral; each on its own, the acid runs ahead of its chloride. Against
   the closed solution for a step in an unbounded column, on a column the
   spread does not reach the ends of.
   ====================================================================== */
console.log('\n--- diffusion that keeps the charge ---');
{
  const N = 400;
  const L = 0.04;
  const T = 2e3;
  const DH = 9.31e-9;
  const DCl = 2.03e-9;
  const step = (how, more = '') => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${N}
LENGTH = ${L}
DIFFUSION = ${how}
LEFT = neumann
RIGHT = neumann
TEND = ${T}

<SPECIES>
H+    1e-6   D=${DH}
Cl-   1e-6   D=${DCl}
${more}

<INITIAL>
H+   0-${N / 2 - 1}  1e-3
Cl-  0-${N / 2 - 1}  1e-3
`);
  const spread = (how) => {
    const m = step(how);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: T, rtol: 1e-8, atol: 1e-16 });
    const y = r.y[r.y.length - 1];
    let charge = 0;
    let amb = 0;
    let own = 0;
    const Damb = (2 * DH * DCl) / (DH + DCl);
    const exact = (x, D) => 1e-6 + ((1e-3 - 1e-6) / 2) * erfc((x - L / 2) / (2 * Math.sqrt(D * T)));
    for (let i = 0; i < N; i++) {
      const x = m.grid.centres[i];
      charge = Math.max(charge, Math.abs(y[2 * i] - y[2 * i + 1]) / 1e-3);
      amb = Math.max(amb, Math.abs(y[2 * i] - exact(x, Damb)) / 1e-3);
      own = Math.max(own, Math.abs(y[2 * i] - exact(x, DH)) / 1e-3);
    }
    return { m, y, charge, amb, own };
  };
  const fick = spread(1);
  const np = spread('nernst-planck');
  check('each species on its own: the acid runs ahead of its chloride, at its own D', fick.charge > 0.1 && fick.own < 2e-3,
    `charge up to ${fick.charge.toFixed(3)} of the step; H+ within ${fick.own.toExponential(1)} of erfc at D_H`);
  check('  nernst-planck: HCl spreads at 2 D_H D_Cl/(D_H + D_Cl), the water neutral',
    np.charge < 1e-12 && np.amb < 1e-4, `within ${np.amb.toExponential(1)} of the closed solution, charge `
      + `${np.charge.toExponential(1)} of the step`);
  const vnp = RtmModel.verifyJacobian(np.m, T, np.y);
  check('  and its Jacobian, every ion against every other across each face', vnp.discrepancies.length === 0
    && !np.m.jacobianConstant, `${vnp.checked} entries`);
  // Equal coefficients in a neutral water: the coupling is nothing.
  const same = (how) => {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 50
LENGTH = 0.01
DIFFUSION = ${how}
LEFT = neumann
RIGHT = neumann
TEND = 2e3

<SPECIES>
Na+   1e-6   D=1e-9
Cl-   1e-6   D=1e-9

<INITIAL>
Na+  0-24  1e-3
Cl-  0-24  1e-3
`);
    return FacsimileODE.runModel(m, { solver: 'ndf', tend: 2e3, rtol: 1e-8, atol: 1e-16 });
  };
  const a = same(1);
  const b = same('nernst-planck');
  const ya = a.y[a.y.length - 1];
  const yb = b.y[b.y.length - 1];
  let diff = 0;
  for (let i = 0; i < ya.length; i++) diff = Math.max(diff, Math.abs(ya[i] - yb[i]) / 1e-3);
  check('  where every D is the same it changes nothing', diff < 1e-9, diff.toExponential(1));
  let word = '';
  try { step('nernst'); } catch (e) { word = e.message; }
  check('  DIFFUSION is 0, 1 or nernst-planck', /DIFFUSION is 0, 1, nernst-planck/.test(word), word);
  // Beside held equilibria: the coupling reaches the totals through the species.
  const held = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 8
LENGTH = 0.01
DIFFUSION = nernst-planck
LEFT = neumann
RIGHT = neumann
TEND = 1e3
EQUILIBRATE = always

<SPECIES>
H+      1e-7   D=9.31e-9
OH-     1e-7   D=5.27e-9
CO2     1e-4   D=1.92e-9
HCO3-   2e-3   D=1.18e-9
CO3-2   1e-5   D=0.955e-9
Na+     2e-3   D=1.33e-9
Cl-     1e-4   D=2.03e-9

<INITIAL>
H+   0-1  2e-3
Cl-  0-1  2.1e-3

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33
`);
  const yh = held.initialState();
  for (let k = 0; k < yh.length; k++) yh[k] += 1e-4 * Math.sin(k);
  const vh = RtmModel.verifyJacobian(held, 0, yh);
  check('  and beside equilibria held, the Jacobian through the totals', vh.discrepancies.length === 0, `${vh.checked} entries`);

  /*
    At a Dirichlet end the coupling acts too, between the water held there
    and the cell beside it, half a cell away: acid held against a salt water
    puts no charge into the first cell, where each species on its own puts
    in H+ faster than Na+ leaves.
  */
  const endHeld = (how) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 0.02
DIFFUSION = ${how}
LEFT = dirichlet
RIGHT = neumann
TEND = 3600

<SPECIES>
H+    1e-7   D=9.31e-9   left=1e-2
Na+   1e-2   D=1.33e-9   left=1e-12
Cl-   1e-2   D=2.03e-9   left=1e-2
`);
  const chargeIn = (how) => {
    const m = endHeld(how);
    const y = m.initialState();
    const out = new Float64Array(y.length);
    m.rhs(0, y, out);
    const q = out[0] + out[1] - out[2];
    return { m, y, q, flux: Math.max(...[0, 1, 2].map((k) => Math.abs(out[k]))) };
  };
  const fickEnd = chargeIn(1);
  const npEnd = chargeIn('nernst-planck');
  check('  at a Dirichlet end as between cells: acid held against salt puts no charge into the cell beside it',
    Math.abs(npEnd.q) < 1e-13 * npEnd.flux && Math.abs(fickEnd.q) > 0.3 * fickEnd.flux,
    `charge ${(Math.abs(npEnd.q) / npEnd.flux).toExponential(1)} of the largest flux; each on its own `
      + `${(Math.abs(fickEnd.q) / fickEnd.flux).toFixed(2)}`);
  const ye = npEnd.y.slice();
  for (let k = 0; k < ye.length; k++) ye[k] *= 1 + 0.3 * Math.sin(k);
  const ve = RtmModel.verifyJacobian(npEnd.m, 0, ye);
  check('  and its Jacobian there', ve.discrepancies.length === 0, `${ve.checked} entries`);

  /*
    DIFFUSION_GRADIENT = activity, each species on its own: across a face
    the difference in concentration times f = 1 + dln gamma/dln C between
    the two cells, held between 0.2 and 2.25, and 1 where one side has under
    1e-10 of the other -- by hand, from the cells' own gammas. K+ nearly
    level where the ionic strength is not: f held at 2.25; a trace of Br-
    on one side: 1.
  */
  const actCol = (more, how = 1) => RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 0.004
DIFFUSION = ${how}
DIFFUSION_GRADIENT = activity
LEFT = neumann
RIGHT = neumann
TEND = 3600
${more}

<SPECIES>
Na+   0.1      D=1.33e-9
Cl-   0.101    D=2.03e-9
K+    1e-3     D=1.96e-9
Br-   1e-15    D=2.01e-9

<INITIAL>
Na+  1  0.01
Cl-  1  0.010001
K+   1  1.001e-3
Br-  1  1e-3
`);
  {
    const m = actCol('ACTIVITY = davies');
    const y = m.initialState();
    const ns = m.speciesNames.length;
    const out = new Float64Array(y.length);
    m.rhs(0, y, out);
    const lnG = [0, 1].map((c) => {
      const g = new Float64Array(ns);
      RtmModel.activityAt(m.act, y, c * ns, g, new Float64Array(ns));
      return g;
    });
    const Dk = { 'Na+': 1.33e-9, 'Cl-': 2.03e-9, 'K+': 1.96e-9, 'Br-': 2.01e-9 };
    const f = {};
    let worst = 0;
    m.speciesNames.forEach((n, k) => {
      const ca = y[k];
      const cb = y[ns + k];
      f[n] = Math.max(ca, cb) / Math.min(ca, cb) >= 1e10 ? 1
        : Math.min(2.25, Math.max(0.2, 1 + (lnG[1][k] - lnG[0][k]) / Math.log(cb / ca)));
      const want = (Dk[n] * f[n] * (cb - ca)) / (0.002 * 0.002);
      worst = Math.max(worst, Math.abs(out[k] - want) / Math.abs(want));
    });
    check('DIFFUSION_GRADIENT = activity: the difference times 1 + dln gamma/dln C, held between 0.2 and 2.25, '
      + 'none for a trace', worst < 1e-12 && f['K+'] === 2.25 && f['Br-'] === 1 && f['Na+'] > 0.5 && f['Na+'] < 1,
    `f: Na+ ${f['Na+'].toFixed(4)}, Cl- ${f['Cl-'].toFixed(4)}, K+ ${f['K+']} (held), Br- ${f['Br-']} (a trace); `
      + `the rates within ${worst.toExponential(1)} of them`);
    let msg = '';
    try { actCol(''); } catch (e) { msg = e.message; }
    check('  without ACTIVITY it is refused, and says why', /DIFFUSION_GRADIENT = activity .* needs activity coefficients: set ACTIVITY/.test(msg), msg);
  }
  // Coupled and down the activities: acid against salt in a closed column stays neutral.
  {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 0.02
DIFFUSION = nernst-planck
DIFFUSION_GRADIENT = activity
ACTIVITY = davies
LEFT = neumann
RIGHT = neumann
TEND = 18000

<SPECIES>
H+    1e-7       D=9.31e-9
Na+   0.05       D=1.33e-9
Cl-   0.0500001  D=2.03e-9

<INITIAL>
H+   0-9  0.05
Na+  0-9  1e-7
`);
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 18000, rtol: 1e-8, atol: 1e-16 });
    const y = r.y[r.y.length - 1];
    let charge = 0;
    let mass = 0;
    for (let i = 0; i < 20; i++) {
      charge = Math.max(charge, Math.abs(y[3 * i] + y[3 * i + 1] - y[3 * i + 2]) / 0.05);
      mass += y[3 * i + 2];
    }
    check('  coupled and down the activities, acid against salt stays neutral and keeps its chloride',
      charge < 1e-12 && Math.abs(mass / (20 * 0.0500001) - 1) < 1e-12, `charge ${charge.toExponential(1)} of the salt, `
        + `chloride ${Math.abs(mass / (20 * 0.0500001) - 1).toExponential(1)} off`);
  }
}

/* ======================================================================
   2v. Ion exchange (exchange, exchanger)

   PHREEQC's Gaines-Thomas: an exchanger X- that is no amount, its activity
   solved for, and species on it whose activity is their equivalent
   fraction. Against the closed solution of a binary Na/Ca exchange, as a
   capacity loaded from a water that stays as it is, in the half-reaction,
   exchange-reaction and Gapon forms, with the ion's activity coefficient,
   as a column whose Ca front moves at v/R with R = 1 + CEC/(2 Ca), and as
   a pair with a kf; and the texts it refuses.
   ====================================================================== */
console.log('\n--- ion exchange ---');
{
  const K = 10 ** 0.8;     // Ca+2 + 2 NaX <=> CaX2 + 2 Na+, with NaX at logK 0
  const CEC = 1e-3;
  const batch = (species, rel, more = '') => RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
${more}

<SPECIES>
${species}

<EQUILIBRIUM>
${rel}
`);
  const val = (m, y, name) => y[m.speciesNames.indexOf(name)];
  const half = 'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8';

  // The closed solution: x of Ca onto the exchanger from Na0, Ca0 and an
  // exchanger all Na, beta_Ca/beta_Na^2 = K Ca/Na^2.
  const Na0 = 1e-3;
  const Ca0 = 2e-4;
  const f = (x) => (2 * x / CEC) * (Na0 + 2 * x) ** 2 - K * (Ca0 - x) * ((CEC - 2 * x) / CEC) ** 2;
  let lo = 0;
  let hi = Ca0;
  for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (f(mid) > 0) hi = mid; else lo = mid; }
  const x = (lo + hi) / 2;
  const given = batch(`Na+ ${Na0}\nCa+2 ${Ca0}\nCl- ${Na0 + 2 * Ca0}\nX- exchanger\nNaX exchange ${CEC}\nCaX2 exchange`,
    half, 'EQUILIBRATE = start');
  const yg = given.initialState();
  const dev = Math.max(...[['CaX2', x], ['NaX', CEC - 2 * x], ['Na+', Na0 + 2 * x], ['Ca+2', Ca0 - x]]
    .map(([n, v]) => Math.abs(val(given, yg, n) / v - 1)));
  check('a binary Na/Ca exchange, the exchanger all Na at the start, against the closed solution',
    dev < 1e-9 && given.speciated[0].converged, `within ${dev.toExponential(1)}; ${(x * 1e3).toFixed(5)} mM of Ca taken up`);
  check('  the sites are the capacity, and the totals of Na and Ca are kept',
    Math.abs((val(given, yg, 'NaX') + 2 * val(given, yg, 'CaX2')) / CEC - 1) < 1e-12
    && Math.abs((val(given, yg, 'Na+') + val(given, yg, 'NaX')) / (Na0 + CEC) - 1) < 1e-12
    && Math.abs((val(given, yg, 'Ca+2') + val(given, yg, 'CaX2')) / Ca0 - 1) < 1e-12);
  // The same exchange written between the species on the exchanger.
  const swap = batch(`Na+ ${Na0}\nCa+2 ${Ca0}\nCl- ${Na0 + 2 * Ca0}\nX- exchanger\nNaX exchange ${CEC}\nCaX2 exchange`,
    'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 NaX <=> CaX2 + 2 Na+, logK = 0.8', 'EQUILIBRATE = start');
  const ys = swap.initialState();
  check('  written as Ca+2 + 2 NaX <=> CaX2 + 2 Na+, CaX2 takes 2 sites and the answer is the same',
    swap.act.ex.n[swap.speciesNames.indexOf('CaX2')] === 2
    && Math.abs(val(swap, ys, 'CaX2') / x - 1) < 1e-9);

  // A capacity, loaded from the water, which stays as it is.
  const loaded = batch(`Na+ ${Na0}\nCa+2 ${Ca0}\nCl- ${Na0 + 2 * Ca0}\nX- exchanger ${CEC}\nNaX exchange\nCaX2 exchange`,
    half, 'EQUILIBRATE = start');
  const yl = loaded.initialState();
  const bNa = val(loaded, yl, 'NaX') / CEC;
  const bCa = 2 * val(loaded, yl, 'CaX2') / CEC;
  check('a capacity on the exchanger\'s line is loaded from the water, which stays as it is',
    Math.abs(val(loaded, yl, 'Na+') / Na0 - 1) < 1e-14 && Math.abs(val(loaded, yl, 'Ca+2') / Ca0 - 1) < 1e-14
    && Math.abs(bNa + bCa - 1) < 1e-14 && Math.abs((bCa / bNa ** 2) / (K * Ca0 / Na0 ** 2) - 1) < 1e-12,
    `fractions Na ${bNa.toFixed(6)}, Ca ${bCa.toFixed(6)}`);
  check('  and the exchanger\'s value is its activity, which no total counts',
    Math.abs(Math.log(val(loaded, yl, 'NaX') / CEC) - Math.log(val(loaded, yl, 'Na+')) - Math.log(val(loaded, yl, 'X-'))) < 1e-12);
  const noCa = batch(`Na+ ${Na0}\nCa+2 0\nCl- ${Na0}\nX- exchanger ${CEC}\nNaX exchange\nCaX2 exchange`, half);
  const yn = noCa.initialState();
  check('  an ion the water has none of puts none of its species on it',
    val(noCa, yn, 'CaX2') === 0 && Math.abs(val(noCa, yn, 'NaX') / CEC - 1) < 1e-15);

  // Gapon: Ca0.5X takes one site, its ion to the power 0.5.
  const gapon = batch(`Na+ ${Na0}\nCa+2 ${Ca0}\nCl- ${Na0 + 2 * Ca0}\nX- exchanger ${CEC}\nNaX exchange\nCa0_5X exchange`,
    'Na+ + X- <=> NaX, logK = 0\n0.5 Ca+2 + X- <=> Ca0_5X, logK = 0.4');
  const yq = gapon.initialState();
  const gN = val(gapon, yq, 'NaX') / CEC;
  const gC = val(gapon, yq, 'Ca0_5X') / CEC;
  check('Gapon, 0.5 Ca+2 + X- <=> Ca0_5X: one site each, Ca0_5X/NaX = K Ca^0.5/Na',
    Math.abs(gN + gC - 1) < 1e-14 && Math.abs((gC / gN) / (10 ** 0.4 * Math.sqrt(Ca0) / Na0) - 1) < 1e-12);

  // The ion's activity coefficient: WATEQ with the a and b on the species'
  // line and its ion's charge, to the ion's power; Davies where both are 0.
  // A and B at the water's activity: Na+, Ca+2 and Cl- its solutes.
  const { A, B } = RtmModel.debyeHuckelAB(25, 1, 1 - 0.017 * 0.13);
  const act = (more) => {
    const m = batch(`Na+ 0.05\nCa+2 0.01\nCl- 0.07\nX- exchanger ${CEC}\nNaX exchange ${more[0]}\nCaX2 exchange ${more[1]}`,
      half, 'ACTIVITY = debye-huckel');
    const y = m.initialState();
    const lnG = new Float64Array(m.speciesNames.length);
    RtmModel.activityAt(m.act, y, 0, lnG, new Float64Array(m.speciesNames.length), 0);
    return { m, y, lnG };
  };
  const I = 0.5 * (0.05 + 4 * 0.01 + 0.07);
  const sq = Math.sqrt(I);
  const wateq = (z, a, b) => Math.LN10 * (-A * z * z * sq / (1 + B * a * sq) + b * I);
  const davies = (z) => -Math.LN10 * A * z * z * (sq / (1 + sq) - 0.3 * I);
  const g1 = act(['a=4.08 b=0.082', 'a=5 b=0.165']);
  const iNaX = g1.m.speciesNames.indexOf('NaX');
  const iCaX2 = g1.m.speciesNames.indexOf('CaX2');
  const shift = (j, n) => Math.log(n * val(g1.m, g1.y, j) / CEC) - Math.log(val(g1.m, g1.y, j));
  check('an exchange species\' coefficient: its ion\'s, WATEQ with its own a and b, and its fraction',
    Math.abs(g1.lnG[iNaX] - shift('NaX', 1) - wateq(1, 4.08, 0.082)) < 1e-12
    && Math.abs(g1.lnG[iCaX2] - shift('CaX2', 2) - wateq(2, 5, 0.165)) < 1e-12,
    `ln gamma ${g1.lnG[iNaX].toFixed(6)}, ${g1.lnG[iCaX2].toFixed(6)}`);
  const g2 = act(['a=0 b=0', '']);
  check('  Davies where a and b are both 0, and none without them',
    Math.abs(g2.lnG[iNaX] - shift('NaX', 1) - davies(1)) < 1e-12 && Math.abs(g2.lnG[iCaX2] - shift('CaX2', 2)) < 1e-12);
  check('  and neither counts in the ionic strength nor in the water',
    g1.m.act.z[iNaX] === 0 && g1.m.act.z[g1.m.speciesNames.indexOf('X-')] === 0 && !g1.m.act.solute[iNaX]);
  // {NaX} in a rate law: the fraction, times the ion's coefficient.
  const rate = (more) => {
    const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
${more}

<SPECIES>
Na+ 0.05
Cl- 0.05
T 1
X- exchanger
NaX exchange 6e-4 ${more ? 'a=4.08 b=0.082' : ''}
KX exchange 4e-4

<EQUILIBRIUM>
Na+ + X- <=> NaX, logK = 0
K+ + X- <=> KX, logK = 0.7

<REACTIONS>
T => , r = k*{NaX}, k = 0.1
`.replace('Cl- 0.05', 'Cl- 0.05\nK+ 0'));
    const r = run(m, { tend: 1 });
    return 1 - last(r)[m.speciesNames.indexOf('T')];
  };
  const r0 = rate('');
  const r1 = rate('ACTIVITY = debye-huckel');
  const I2 = 0.05;
  // The water's activity: Na+, Cl- and T, which goes from 1 to 1 - r1 (its middle, to 1e-10 in g).
  const ab2 = RtmModel.debyeHuckelAB(25, 1, 1 - 0.017 * (0.1 + 1 - r1 / 2));
  const g = Math.exp(Math.LN10 * (-ab2.A * Math.sqrt(I2) / (1 + ab2.B * 4.08 * Math.sqrt(I2)) + 0.082 * I2));
  check('{NaX} in a rate law is its equivalent fraction, times its ion\'s coefficient under ACTIVITY',
    Math.abs(r0 / 0.06 - 1) < 1e-9 && Math.abs(r1 / (0.06 * g) - 1) < 1e-9,
    `${r0.toFixed(9)} and ${r1.toFixed(9)} taken in 1 s`);

  // A kinetic exchange, between the species on the exchanger, relaxing to
  // Gaines-Thomas: kf on the concentrations, as every pair has it, and the
  // fractions' 1/CEC with the other coefficients in its kb.
  const kin = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1e4

<SPECIES>
Na+ ${Na0}
Ca+2 ${Ca0}
Cl- ${Na0 + 2 * Ca0}
X- exchanger
NaX exchange ${CEC}
CaX2 exchange

<EQUILIBRIUM>
Na+ + X- <=> NaX, logK = 0
Ca+2 + 2 NaX <=> CaX2 + 2 Na+, logK = 0.8, kf = 1e8
`);
  const rk = run(kin, { tend: 1e4 });
  const yk = last(rk);
  check('a kinetic exchange, Ca+2 + 2 NaX <=> CaX2 + 2 Na+ with a kf, relaxes to the same exchange',
    Math.abs(yk[kin.speciesNames.indexOf('CaX2')] / x - 1) < 1e-6,
    `CaX2 within ${Math.abs(yk[kin.speciesNames.indexOf('CaX2')] / x - 1).toExponential(1)}`);

  // A column: CaCl2 water into one whose exchanger is all Na. Behind the
  // front the exchanger is all Ca, CEC/2 of it per litre, so the front moves
  // at v/R, R = 1 + CEC/(2 Ca_in); the chloride at v.
  const N = 80;
  const L = 0.08;
  const v = 1e-5;
  const Cin = 6e-4;
  const Rf = 1 + CEC / (2 * Cin);
  const T = (0.04 * Rf) / v;
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${N}
LENGTH = ${L}
VELOCITY = ${v}
DIFFUSION = 1
ADVECTION = 1
EQUILIBRATE = always
TEND = ${T}

<SPECIES>
Na+   1e-3    D=1e-10  left=0
Ca+2  1e-12   D=1e-10  left=${Cin}
Cl-   1e-3    D=1e-10  left=${2 * Cin}
X-    exchanger ${CEC}
NaX   exchange
CaX2  exchange

<EQUILIBRIUM>
${half}
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: T, rtol: 1e-8, atol: 1e-20, nonNegative: true,
    outputTimes: [T / 4, T / 2, T] });
  const nsc = col.speciesNames.length;
  const [iNa, iCa, iCl, , iNx, iCx] = [0, 1, 2, 3, 4, 5];
  let sites = 0;
  let gt = 0;
  for (const yy of rc.grid.y) {
    const c = col.toConcentrations(yy);
    for (let i = 0; i < N; i++) {
      const b = i * nsc;
      sites = Math.max(sites, Math.abs((c[b + iNx] + 2 * c[b + iCx]) / CEC - 1));
      if (c[b + iCa] > 1e-9 && c[b + iNa] > 1e-9) {
        gt = Math.max(gt, Math.abs(Math.log10((2 * c[b + iCx] / CEC) / (c[b + iNx] / CEC) ** 2
          / (K * c[b + iCa] / c[b + iNa] ** 2))));
      }
    }
  }
  const cEnd = col.toConcentrations(rc.grid.y[rc.grid.y.length - 1]);
  const at = (k, level) => {
    for (let i = 0; i < N - 1; i++) {
      const a = cEnd[i * nsc + k];
      const b2 = cEnd[(i + 1) * nsc + k];
      if (a >= level && b2 < level) return col.grid.centres[i] + ((a - level) / (a - b2)) * (col.grid.centres[i + 1] - col.grid.centres[i]);
    }
    return NaN;
  };
  const xCa = at(iCa, Cin / 2);
  check('a column, CaCl2 water into an exchanger all Na: the sites and Gaines-Thomas held in every cell throughout',
    sites < 1e-12 && gt < 1e-9, `sites within ${sites.toExponential(1)}, the relation within ${gt.toExponential(1)} in log`);
  const xCl = at(iCl, (1e-3 + 2 * Cin) / 2);
  check('  and the Ca front at v t/R, R = 1 + CEC/(2 Ca), the chloride ahead of it at v t',
    Math.abs(xCa - 0.04) < 2 * (L / N) && Math.abs(xCl - v * T) < 2 * (L / N),
    `Ca at ${(xCa * 100).toFixed(3)} cm for 4 cm (R = ${Rf.toFixed(4)}); chloride at ${(xCl * 100).toFixed(3)} cm for `
      + `${(v * T * 100).toFixed(3)} cm`);
  const yv = col.initialState();
  for (let k = 0; k < yv.length; k++) yv[k] += 1e-3 * Math.sin(k);
  const vj = RtmModel.verifyJacobian(col, 0, yv);
  check('  its Jacobian, the exchanger in the relations and out of the totals', vj.discrepancies.length === 0,
    `${vj.checked} entries`);

  // The texts it refuses.
  const refusal = (species, rel, more = '') => {
    try { batch(species, rel, more); } catch (e) { return e.message; }
    return '';
  };
  const cases = [
    ['a species on an exchanger with no exchanger', 'Na+ 1e-3\nNaX exchange 1e-3', 'Na+ <=> NaX, logK = 0',
      /no species is one/],
    ['an exchanger in no relation', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange', 'Na+ <=> NaX, logK = 0',
      /gives NaX no sites/],
    ['a relation that loses sites', 'Na+ 1e-3\nCa+2 1e-4\nX- exchanger 1e-3\nNaX exchange\nCaX2 exchange',
      'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8\nCa+2 + NaX <=> CaX2 + Na+, logK = 1',
      /does not keep the exchanger's sites/],
    ['the exchanger in a fast pair', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange', 'Na+ + X- <=> NaX, logK = 0, kf = 1',
      /no amount and cannot react at a rate/],
    ['a capacity and amounts in the same cell', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange 1e-3',
      'Na+ + X- <=> NaX, logK = 0', /amounts there as well/],
    ['no capacity at all', 'Na+ 1e-3\nX- exchanger\nNaX exchange', 'Na+ + X- <=> NaX, logK = 0', /has no capacity/],
    ['a and b without a relation from one ion', 'Na+ 1e-3\nCl- 1e-3\nX- exchanger 1e-3\nNaCl exchange a=4 b=0',
      'Na+ + Cl- + X- <=> NaCl, logK = 0', /no relation forms it from X- and one ion/, 'ACTIVITY = davies'],
    ['a charge on an exchange species', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange z=1', 'Na+ + X- <=> NaX, logK = 0',
      /takes no z/],
    ['an exchange species that moves', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange D=1e-9', 'Na+ + X- <=> NaX, logK = 0',
      /stays where it is.*takes no D/],
    ['a without b', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange a=4', 'Na+ + X- <=> NaX, logK = 0', /a and b together/],
    ['two exchangers in one relation', 'Na+ 1e-3\nX- exchanger 1e-3\nY- exchanger 1e-3\nNaX exchange\nNaY exchange',
      'Na+ + X- <=> NaX, logK = 0\nNa+ + Y- <=> NaY, logK = 0\nNaX + Y- <=> NaY + X-, logK = 0', /joins two exchangers/],
  ];
  const wrong = cases.filter(([, sp, rel, re, more]) => !re.test(refusal(sp, rel, more)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, sp, rel, , more]) => `${what}: "${refusal(sp, rel, more)}"`).join(' | '));
  const quiet = batch(`Na+ 1e-3\nX- exchanger ${CEC}\nNaX exchange a=4.08 b=0.082`, 'Na+ + X- <=> NaX, logK = 0');
  check('  and without ACTIVITY, an a and b on a species on the exchanger are said to be unused',
    quiet.warnings.some((w) => /a and b given to one are not used/.test(w)) && quiet.activity === null);
  const start = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 0.01
VELOCITY = 1e-6
ADVECTION = 1
EQUILIBRATE = start

<SPECIES>
Na+ 1e-3
X- exchanger ${CEC}
NaX exchange

<EQUILIBRIUM>
Na+ + X- <=> NaX, logK = 0
`);
  check('  and in a column whose exchanger is put on its relations at the start only, that is said',
    start.warnings.some((w) => /at the start only, and then stays as it is/.test(w))
    && !col.warnings.some((w) => /stays as it is while the water moves/.test(w)));
}

/* ======================================================================
   2w. Surface complexation (surface, sites=)

   PHREEQC's SURFACE without electrostatics (-no_edl): species on a surface
   whose activity is their fraction of the sites of their kind, the bare
   site an amount like the rest. Against the closed solution of a one-site
   isotherm, as sites loaded from a water that stays as it is, with a
   bidentate species, with two kinds of site, read by a rate law, as a pair
   with a kf, under ACTIVITY, as a column whose zinc front moves at v/R with
   R = 1 + q(C)/C; and the texts it refuses.
   ====================================================================== */
console.log('\n--- surface complexation ---');
{
  const batch = (species, rel, more = '', reactions = '') => RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
${more}

<SPECIES>
${species}

<EQUILIBRIUM>
${rel}
${reactions ? `\n<REACTIONS>\n${reactions}\n` : ''}`);
  const val = (m, y, name) => y[m.speciesNames.indexOf(name)];
  const W = 'Hfo_wOH + H+ <=> Hfo_wOH2+, logK = 7.29\nHfo_wOH <=> Hfo_wO- + H+, logK = -8.93\n'
    + 'Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+, logK = -1.99';
  const sp4 = 'Hfo_wOH2+ surface\nHfo_wO- surface\nHfo_wOZn+ surface';

  // Sites loaded from a water, which stays as it is: each fraction the
  // relations give it, the four summing to one.
  const H = 1e-7;
  const Zn = 1e-6;
  const T = 2e-4;
  const loaded = batch(`H+ ${H}\nOH- 1e-7\nZn+2 ${Zn}\nNa+ 1e-3\nCl- 1.002e-3\nHfo_wOH surface sites=${T}\n${sp4}`,
    `${W}\n <=> H+ + OH-, logK = -14`);
  const yl = loaded.initialState();
  const w = [1, 10 ** 7.29 * H, 10 ** -8.93 / H, 10 ** -1.99 * Zn / H];
  const sum = w.reduce((a, b) => a + b, 0);
  const names = ['Hfo_wOH', 'Hfo_wOH2+', 'Hfo_wO-', 'Hfo_wOZn+'];
  const dl = Math.max(...names.map((n, i) => Math.abs(val(loaded, yl, n) / (T * w[i] / sum) - 1)));
  check('sites on a species\' line are loaded from the water, which stays as it is: each fraction the closed form\'s',
    dl < 1e-13 && val(loaded, yl, 'H+') === H && val(loaded, yl, 'Zn+2') === Zn,
    `within ${dl.toExponential(1)}; ${names.map((n) => `${n} ${(val(loaded, yl, n) / T).toFixed(6)}`).join(', ')}`);
  check('  a surface species counts in no ionic strength and no water, and its coefficient is n/sites',
    !loaded.act.solute[loaded.speciesNames.indexOf('Hfo_wOZn+')] && loaded.act.z[loaded.speciesNames.indexOf('Hfo_wOZn+')] === 0
    && Math.abs(loaded.act.sf.shift[loaded.speciesNames.indexOf('Hfo_wOZn+')] - Math.log(1 / T)) < 1e-12);

  // Amounts given, the water and the surface put on the relations together:
  // a one-site isotherm at a fixed pH, x H = K (T - x)(Zn0 - x).
  const K = 10 ** -1.99;
  const Zn0 = 1e-4;
  const qa = K;
  const qb = -(K * (T + Zn0) + H);
  const qc = K * T * Zn0;
  const x = (-qb - Math.sqrt(qb * qb - 4 * qa * qc)) / (2 * qa);
  const one = batch(`H+ ${H} fixed\nZn+2 ${Zn0}\nHfo_wOH ${T} surface\nHfo_wOZn+ surface`,
    'Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+, logK = -1.99', 'EQUILIBRATE = start');
  const yo = one.initialState();
  const d1 = Math.max(Math.abs(val(one, yo, 'Hfo_wOZn+') / x - 1), Math.abs(val(one, yo, 'Zn+2') / (Zn0 - x) - 1),
    Math.abs(val(one, yo, 'Hfo_wOH') / (T - x) - 1));
  check('a one-site isotherm at a fixed pH, the zinc and the sites given, against the closed solution',
    d1 < 1e-10 && one.speciated[0].converged, `within ${d1.toExponential(1)}; ${(x / Zn0 * 100).toFixed(4)} % of the zinc taken up`);

  // Bidentate: 2 Hfo_wOH + Zn+2 <=> (Hfo_wO)2Zn + 2 H+ takes two sites, its
  // fraction 2C/T, as PHREEQC has it.
  const bi = batch(`H+ ${H} fixed\nZn+2 ${Zn0}\nHfo_wOH ${T} surface\nHfo_wO_2Zn surface`,
    '2 Hfo_wOH + Zn+2 <=> Hfo_wO_2Zn + 2 H+, logK = -6', 'EQUILIBRATE = start');
  const yb = bi.initialState();
  const f0 = val(bi, yb, 'Hfo_wOH') / T;
  const f2 = 2 * val(bi, yb, 'Hfo_wO_2Zn') / T;
  const relB = Math.log10(f2 * H * H / (f0 * f0 * val(bi, yb, 'Zn+2')));
  check('a bidentate species takes two sites: its fraction 2C/sites, the sites kept, the relation in fractions',
    bi.act.sf.n[bi.speciesNames.indexOf('Hfo_wO_2Zn')] === 2 && Math.abs(f0 + f2 - 1) < 1e-13 && Math.abs(relB + 6) < 1e-10
    && Math.abs((val(bi, yb, 'Zn+2') + val(bi, yb, 'Hfo_wO_2Zn')) / Zn0 - 1) < 1e-13,
    `fractions ${f0.toFixed(6)} and ${f2.toFixed(6)}, log K ${relB.toFixed(10)}`);

  // Two kinds of site, PHREEQC's strong and weak: each its own total.
  const two = batch(`H+ ${H} fixed\nZn+2 ${Zn0}\nHfo_sOH 5e-6 surface\nHfo_sOZn+ surface\nHfo_wOH ${T} surface\nHfo_wOZn+ surface`,
    'Hfo_sOH + Zn+2 <=> Hfo_sOZn+ + H+, logK = 0.99\nHfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+, logK = -1.99', 'EQUILIBRATE = start');
  const yt = two.initialState();
  const sS = val(two, yt, 'Hfo_sOH') + val(two, yt, 'Hfo_sOZn+');
  const sW = val(two, yt, 'Hfo_wOH') + val(two, yt, 'Hfo_wOZn+');
  const rS = Math.log10((val(two, yt, 'Hfo_sOZn+') / sS) * H / ((val(two, yt, 'Hfo_sOH') / sS) * val(two, yt, 'Zn+2')));
  check('  two kinds of site, strong and weak: each kind\'s sites kept apart, each species its fraction of its own',
    two.act.sf.types.length === 2 && Math.abs(sS / 5e-6 - 1) < 1e-13 && Math.abs(sW / T - 1) < 1e-13 && Math.abs(rS - 0.99) < 1e-10,
    `strong sites ${(val(two, yt, 'Hfo_sOZn+') / sS * 100).toFixed(3)} % zinc, weak ${(val(two, yt, 'Hfo_wOZn+') / sW * 100).toFixed(3)} %`);

  // {Hfo_wOZn+} in a rate law: the fraction.
  const rl = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
H+ ${H} fixed
Zn+2 1e-6
Tr 1
Hfo_wOH surface sites=${T}
Hfo_wOZn+ surface

<EQUILIBRIUM>
Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+, logK = -1.99

<REACTIONS>
Tr => , r = k*{Hfo_wOZn+}, k = 1
`);
  const frac = val(rl, rl.initialState(), 'Hfo_wOZn+') / T;
  const used = 1 - last(run(rl, { tend: 1 }))[rl.speciesNames.indexOf('Tr')];
  check('{Hfo_wOZn+} in a rate law is the species\' fraction of its sites',
    Math.abs(used / frac - 1) < 1e-9, `${used.toExponential(6)} taken in 1 s for a fraction of ${frac.toExponential(6)}`);

  // A relation with a kf relaxes to the same isotherm.
  const kin = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1e4

<SPECIES>
H+ ${H} fixed
Zn+2 ${Zn0}
Hfo_wOH ${T} surface
Hfo_wOZn+ surface

<EQUILIBRIUM>
Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+, logK = -1.99, kf = 1e3
`);
  const yk = last(run(kin, { tend: 1e4 }));
  check('a sorption with a kf relaxes to the same isotherm',
    Math.abs(yk[kin.speciesNames.indexOf('Hfo_wOZn+')] / x - 1) < 1e-6,
    `within ${Math.abs(yk[kin.speciesNames.indexOf('Hfo_wOZn+')] / x - 1).toExponential(1)}`);

  // Under ACTIVITY the water's ions take their coefficients and the surface
  // species keep their fractions: the relation holds between the zinc's and
  // the proton's activities and the fractions.
  const ac = batch(`H+ 1e-6\nOH- 1e-8\nZn+2 ${Zn0}\nNa+ 0.05\nCl- 0.0502\nHfo_wOH surface sites=${T}\n${sp4}`,
    `${W}\n <=> H+ + OH-, logK = -14`, 'ACTIVITY = debye-huckel\nEQUILIBRATE = start');
  const ya = ac.initialState();
  const lnG = new Float64Array(ac.speciesNames.length);
  RtmModel.activityAt(ac.act, ya, 0, lnG, new Float64Array(ac.speciesNames.length), 0);
  const la = (n) => Math.log10(val(ac, ya, n)) + lnG[ac.speciesNames.indexOf(n)] / Math.LN10;
  const relA = la('Hfo_wOZn+') + la('H+') - la('Hfo_wOH') - la('Zn+2');
  const fr = names.reduce((a, n) => a + val(ac, ya, n), 0) / T;
  check('  under ACTIVITY: the ions\' coefficients, the surface species\' fractions, and the relation between them',
    Math.abs(relA + 1.99) < 1e-10 && Math.abs(fr - 1) < 1e-13 && lnG[ac.speciesNames.indexOf('Zn+2')] < -0.5
    && Math.abs(lnG[ac.speciesNames.indexOf('Hfo_wOZn+')] - Math.log(1 / T)) < 1e-12,
    `log K ${relA.toFixed(10)}; ln gamma of Zn+2 ${lnG[ac.speciesNames.indexOf('Zn+2')].toFixed(4)}`);

  // A column: zinc into one whose sites are bare. A Langmuir isotherm,
  // S + Zn+2 <=> SZn+2: behind the front the sites hold q(C) = T K C/(1 + K C),
  // so the front moves at v/R, R = 1 + q(Cin)/Cin.
  const N = 80;
  const L = 0.08;
  const v = 1e-5;
  const Cin = 1e-4;
  const KL = 1e4;
  const Ts = 1e-3;
  const Rf = 1 + (Ts * KL / (1 + KL * Cin));
  const Tend = (0.04 * Rf) / v;
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${N}
LENGTH = ${L}
VELOCITY = ${v}
DIFFUSION = 1
ADVECTION = 1
EQUILIBRATE = always
TEND = ${Tend}

<SPECIES>
Zn+2   1e-12   D=1e-10  left=${Cin}
S      surface sites=${Ts}
SZn+2  surface

<EQUILIBRIUM>
S + Zn+2 <=> SZn+2, logK = ${Math.log10(KL)}
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: Tend, rtol: 1e-8, atol: 1e-20, nonNegative: true,
    outputTimes: [Tend / 4, Tend / 2, Tend] });
  const nsc = col.speciesNames.length;
  let sites = 0;
  let iso = 0;
  for (const yy of rc.grid.y) {
    const c = col.toConcentrations(yy);
    for (let i = 0; i < N; i++) {
      const b = i * nsc;
      sites = Math.max(sites, Math.abs((c[b + 1] + c[b + 2]) / Ts - 1));
      if (c[b] > 1e-9) iso = Math.max(iso, Math.abs(Math.log10((c[b + 2] / Ts) / ((c[b + 1] / Ts) * c[b]) / KL)));
    }
  }
  const cEnd = col.toConcentrations(rc.grid.y[rc.grid.y.length - 1]);
  let xZn = NaN;
  for (let i = 0; i < N - 1; i++) {
    const a = cEnd[i * nsc];
    const b2 = cEnd[(i + 1) * nsc];
    if (a >= Cin / 2 && b2 < Cin / 2) {
      xZn = col.grid.centres[i] + ((a - Cin / 2) / (a - b2)) * (col.grid.centres[i + 1] - col.grid.centres[i]);
      break;
    }
  }
  check('a column, zinc into bare sites: the sites and the isotherm held in every cell throughout',
    sites < 1e-12 && iso < 1e-9, `sites within ${sites.toExponential(1)}, the relation within ${iso.toExponential(1)} in log`);
  check('  and the zinc front at v t/R, R = 1 + q(C)/C', Math.abs(xZn - 0.04) < 2 * (L / N),
    `at ${(xZn * 100).toFixed(3)} cm for 4 cm (R = ${Rf})`);
  const yv = col.initialState();
  for (let k = 0; k < yv.length; k++) yv[k] += 1e-3 * Math.sin(k);
  const vj = RtmModel.verifyJacobian(col, 0, yv);
  check('  its Jacobian, the sites a total of their own', vj.discrepancies.length === 0, `${vj.checked} entries`);

  // The texts it refuses.
  const refusal = (species, rel, more = '') => {
    try { batch(species, rel, more); } catch (e) { return e.message; }
    return '';
  };
  const R1 = 'S + Zn+2 <=> SZn+2, logK = 4';
  const cases = [
    ['sites on a species not on a surface', 'Zn+2 1e-6 sites=1e-3\nS surface 1e-3\nSZn+2 surface', R1, /sites are a surface's/],
    ['sites and an amount on one line', 'Zn+2 1e-6\nS surface 1e-3 sites=1e-3\nSZn+2 surface', R1, /both an amount and the sites/],
    ['sites given twice on one surface', 'Zn+2 1e-6\nS surface sites=1e-3\nSZn+2 surface sites=1e-3', R1, /each given its sites/],
    ['sites and amounts in the same cell', 'Zn+2 1e-6\nS surface sites=1e-3\nSZn+2 surface 1e-4', R1, /amounts.*as well/],
    ['no sites at all', 'Zn+2 1e-6\nS surface\nSZn+2 surface', R1, /has no sites/],
    ['a relation that loses sites', 'Zn+2 1e-6\nS surface 1e-3\nSZn+2 surface\nS2Zn+2 surface',
      `${R1}\n2 S + Zn+2 <=> S2Zn+2, logK = 6\nSZn+2 + Zn+2 <=> S2Zn+2, logK = 1`, /does not keep the surface's sites/],
    ['two species on a surface on one side', 'Zn+2 1e-6\nS surface 1e-3\nSZn+2 surface', 'S + SZn+2 <=> Zn+2, logK = 4',
      /gives SZn\+2 no sites/],
    ['a surface and an exchanger in one relation', 'Na+ 1e-3\nX- exchanger 1e-3\nNaX exchange\nS surface 1e-3\nSNa+ surface',
      'Na+ + X- <=> NaX, logK = 0\nS + NaX <=> SNa+ + X-, logK = 1', /a surface and an exchanger/],
    ['a mineral and a surface in one relation', 'Zn+2 1e-6\nOH- 1e-7\nZnO 1 mineral\nS surface 1e-3\nSZn+2 surface',
      `${R1}\nZnO + S <=> SZn+2 + 2 OH-, logK = -10`, /a mineral and a surface/],
    ['a species on a surface that moves', 'Zn+2 1e-6\nS surface 1e-3 D=1e-9\nSZn+2 surface', R1, /stays where it is.*takes no D/],
    ['a and b on a species on a surface', 'Zn+2 1e-6\nS surface 1e-3\nSZn+2 surface a=4 b=0', R1, /takes no a or b/],
  ];
  const wrong = cases.filter(([, sp, rel, re, more]) => !re.test(refusal(sp, rel, more)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, sp, rel, , more]) => `${what}: "${refusal(sp, rel, more)}"`).join(' | '));
  const start = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 0.01
VELOCITY = 1e-6
ADVECTION = 1
EQUILIBRATE = start

<SPECIES>
Zn+2 1e-6
S surface sites=1e-3
SZn+2 surface

<EQUILIBRIUM>
${R1}
`);
  check('  and in a column whose surface is put on its relations at the start only, that is said',
    start.warnings.some((wn) => /on the surface is put on its relations at the start only/.test(wn))
    && !col.warnings.some((wn) => /stays as it is while the water moves/.test(wn)));
}

/* ======================================================================
   2x. The diffuse double layer (potential, area=, grams=)

   PHREEQC's SURFACE unless told -no_edl: the surface's potential in each
   relation by the charge it puts on the surface, and Gouy and Chapman's
   equation for it. Against the same two equations solved by bisection, as
   amounts speciated and as sites loaded from a water that stays; a column
   of acid into a charged surface, the relation and the equation held in
   every cell and its Jacobian; and the texts it refuses.
   ====================================================================== */
console.log('\n--- the diffuse double layer ---');
{
  const batch = (species, rel, more = '') => RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = start
${more}

<SPECIES>
${species}

<EQUILIBRIUM>
${rel}
`);
  const val = (m, y, name) => y[m.speciesNames.indexOf(name)];
  // PHREEQC's constants, and the dielectric constant of water at 25 C.
  const F = 96493.5;
  const Rg = 8.31470;
  const eps0 = 8.854e-12;
  const eps = RtmModel.debyeHuckelAB(25).eps;
  const T = 298.15;
  const H = 1e-7;
  const lk = 7.29;
  const sites = 2e-4;
  const AM = 600 * 0.09;
  const I = 0.5 * (0.1 + 0.1 + H);
  const S = Math.sqrt(8000 * Rg * T * eps * eps0 * I);
  // theta = K H e^(-F psi/RT) / (1 + ...); F sites theta/(A M) = S sinh(F psi/2RT): bisection in psi.
  const theta = (psi) => { const x = 10 ** lk * H * Math.exp(-F * psi / (Rg * T)); return x / (1 + x); };
  const g = (psi) => F * sites * theta(psi) / AM - S * Math.sinh(F * psi / (2 * Rg * T));
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (g(mid) > 0) lo = mid; else hi = mid; }
  const psi = (lo + hi) / 2;
  const sp = (s1) => `H+ ${H} fixed\nNa+ 0.1\nCl- 0.1\nS_psi potential area=600 grams=0.09\n${s1}\nS_OH2+ surface`;
  const rel = 'S_OH + H+ <=> S_OH2+, logK = 7.29';
  for (const [how, s1] of [['the amounts given and speciated', `S_OH ${sites} surface`],
    ['the sites loaded from the water', `S_OH surface sites=${sites}`]]) {
    const m = batch(sp(s1), rel);
    const y = m.initialState();
    const a = val(m, y, 'S_psi');
    const psiPage = -Math.log(a) * Rg * T / F;
    const th = val(m, y, 'S_OH2+') / sites;
    check(`${how}: the potential and the charge Gouy and Chapman's equation gives, against bisection`,
      Math.abs(psiPage / psi - 1) < 1e-10 && Math.abs(th / theta(psi) - 1) < 1e-10
      && Math.abs((val(m, y, 'S_OH') + val(m, y, 'S_OH2+')) / sites - 1) < 1e-13,
      `psi ${(psiPage * 1e3).toFixed(6)} mV for ${(psi * 1e3).toFixed(6)}; ${(th * 100).toFixed(4)} % of the sites charged `
        + `where without the layer it would be ${(100 * 10 ** lk * H / (1 + 10 ** lk * H)).toFixed(2)} %`);
  }
  const m0 = batch(sp(`S_OH ${sites} surface`), rel);
  check('  the potential is in the relation by the charge it puts on the surface, and in no total',
    m0.equilibria[0].net.some(([k, c]) => m0.speciesNames[k] === 'S_psi' && c === -1)
    && m0.rank[m0.speciesNames.indexOf('S_psi')] === 3
    && m0.conservation.every((u) => u[m0.speciesNames.indexOf('S_psi')] === 0));

  // A column: acid into water over a surface that takes the protons up and
  // charges. Held in every cell, the relation with the potential in it and
  // Gouy and Chapman, and the Jacobian of the projected form.
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 0.02
VELOCITY = 1e-5
DIFFUSION = 1
ADVECTION = 1
EQUILIBRATE = always
TEND = 4000

<SPECIES>
H+      1e-8    D=1e-9  left=1e-4
OH-     1e-6    D=1e-9  left=1e-10
Na+     0.01    D=1e-9  left=0.01
Cl-     0.01    D=1e-9  left=0.0101
S_psi   potential  area=600  grams=0.09
S_OH    surface  sites=${sites}
S_OH2+  surface
S_O-    surface

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
${rel}
S_OH <=> S_O- + H+, logK = -8.93
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: 4000, rtol: 1e-7, atol: 1e-20, nonNegative: true,
    outputTimes: [1000, 2000, 4000] });
  const nsc = col.speciesNames.length;
  const at = (n) => col.speciesNames.indexOf(n);
  let worstGC = 0;
  let worstRel = 0;
  let lowPH = 14;
  for (const yy of rc.grid.y) {
    const c = col.toConcentrations(yy);
    for (let i = 0; i < 20; i++) {
      const b = i * nsc;
      const a = c[b + at('S_psi')];
      const u = Math.log(a);
      const Q = c[b + at('S_OH2+')] - c[b + at('S_O-')];
      const Ii = 0.5 * (c[b + at('H+')] + c[b + at('OH-')] + c[b + at('Na+')] + c[b + at('Cl-')]);
      const Si = Math.sqrt(8000 * Rg * T * eps * eps0 * Ii);
      worstGC = Math.max(worstGC, Math.abs(F * Q / AM + Si * Math.sinh(u / 2)) / (Si * Math.cosh(u / 2) / 2));
      worstRel = Math.max(worstRel, Math.abs(Math.log10(c[b + at('S_OH2+')] / (c[b + at('S_OH')] * c[b + at('H+')] * a)) - lk));
      lowPH = Math.min(lowPH, -Math.log10(c[b + at('H+')]));
    }
  }
  check('a column of acid into a surface that charges: the relation with its potential and Gouy and Chapman held in '
    + 'every cell', worstGC < 1e-9 && worstRel < 1e-9 && rc.stats.stoppedBy === null && lowPH < 4.5,
  `Gouy-Chapman within ${worstGC.toExponential(1)} in ln a, the relation within ${worstRel.toExponential(1)}; `
    + `${rc.stats.nsteps} steps, pH down to ${lowPH.toFixed(3)}`);
  const vj0 = RtmModel.verifyJacobian(col, 0, col.initialState());
  const vj1 = RtmModel.verifyJacobian(col, 2000, rc.grid.y[1]);
  check('  its Jacobian, the potential through the speciation, at the start and on the way',
    vj0.discrepancies.length === 0 && vj1.discrepancies.length === 0, `${vj0.checked} and ${vj1.checked} entries`);

  // The texts it refuses.
  const refusal = (species, rl, more = '') => {
    try { batch(species, rl, more); } catch (e) { return e.message; }
    return '';
  };
  const base = `H+ ${H} fixed\nNa+ 0.1\nCl- 0.1\nS_OH ${sites} surface\nS_OH2+ surface`;
  const cases = [
    ['a potential with no surface', `H+ ${H}\nS_psi potential area=600 grams=0.09`, ' <=> H+, logK = -7', /no species is on a surface/],
    ['a potential not named for its surface', `${base}\nPsi potential area=600 grams=0.09`, rel, /named for its surface/],
    ['a potential of no surface there is', `${base}\nX_psi potential area=600 grams=0.09`, rel, /no species on a surface is named X_/],
    ['two potentials on one surface', `${base}\nS_psi potential area=600 grams=0.09\nS_p2 potential area=600 grams=0.09`, rel,
      /each the potential of/],
    ['a relation written with the potential', `${base}\nS_psi potential area=600 grams=0.09`,
      'S_OH + H+ + S_psi <=> S_OH2+, logK = 7.29', /puts the potential in/],
    ['a charge put on at a rate', `${base}\nS_psi potential area=600 grams=0.09`, `${rel}, kf = 1e6`, /takes no kf/],
    ['a potential without its area and grams', `${base}\nS_psi potential`, rel, /needs the surface's area/],
    ['area given to a species that is no potential', `${base} area=600\nS_psi potential area=600 grams=0.09`, rel,
      /area and grams are a surface's/],
    ['a potential that moves', `${base}\nS_psi potential area=600 grams=0.09 D=1e-9`, rel, /takes no D/],
    ['a charge on a potential', `${base}\nS_psi potential area=600 grams=0.09 z=1`, rel, /takes no z, a or b/],
    ['a potential no relation acts through', `${base}\nS_psi potential area=600 grams=0.09\nS_OHNa+ surface`,
      'S_OH2+ + Na+ <=> S_OHNa+ + H+, logK = -3', /No relation puts a charge on the surface/],
    ['a potential without EQUILIBRATE', `${base}\nS_psi potential area=600 grams=0.09`, rel, /needs EQUILIBRATE/,
      'EQUILIBRATE = 0'],
  ];
  const wrong = cases.filter(([, sp2, rl, re, more]) => !re.test(refusal(sp2, rl, more)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, sp2, rl, , more]) => `${what}: "${refusal(sp2, rl, more)}"`).join(' | '));
  const quiet = batch(`${base}\nS_psi potential area=600 grams=0.09`, rel, 'TEMPERATURE = 40');
  check('  and TEMPERATURE, which the double layer reads, is not said to do nothing without ACTIVITY',
    !quiet.warnings.some((wn) => /TEMPERATURE/.test(wn)));
}

console.log('\n--- redox: the electron ---');
{
  const batch = (species, rel, more = '', reactions = '') => RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
${more}

<SPECIES>
${species}

<EQUILIBRIUM>
${rel}
${reactions ? `\n<REACTIONS>\n${reactions}\n` : ''}`);
  const val = (m, y, name) => y[m.speciesNames.indexOf(name)];
  const FE = 'Fe+2 <=> Fe+3 + e-, logK = -13.02';
  const MN = 'Mn+2 <=> Mn+3 + e-, logK = -25.51';

  // One couple at a given pe: Fe3/Fe2 = K/a(e-), the electron held there at the start.
  const atPe = batch('Fe+2 1e-3\nFe+3 0\nCl- 2e-3\ne- electron pe=12', FE, 'EQUILIBRATE = start');
  const ya = atPe.initialState();
  const ratio = 10 ** (-13.02 + 12);
  check('one couple at a given pe: the valence states share the element as the pe has it (Fe3/Fe2 = K/a(e-))',
    Math.abs(val(atPe, ya, 'Fe+3') / (1e-3 * ratio / (1 + ratio)) - 1) < 1e-12
    && Math.abs(val(atPe, ya, 'Fe+2') + val(atPe, ya, 'Fe+3') - 1e-3) < 1e-18
    && Math.abs(Math.log10(val(atPe, ya, 'e-')) + 12) < 1e-12 && atPe.speciated[0].converged,
    `Fe+3 ${val(atPe, ya, 'Fe+3').toExponential(6)}, from none`);
  // Without a pe, the couple's own ratio sets it.
  const own = batch('Fe+2 9e-4\nFe+3 1e-4\ne- electron', FE, 'EQUILIBRATE = start');
  const pe = -Math.log10(val(own, own.initialState(), 'e-'));
  check('  given no pe, the valence states as written set it: pe = -log K - log(Fe2/Fe3)',
    Math.abs(pe - (13.02 - Math.log10(9))) < 1e-12, `pe ${pe.toFixed(12)}`);

  // Two couples tied to the electron are the redox reaction between them.
  for (const [what, start] of [['as written', 'Fe+2 1e-6\nFe+3 1e-4\nMn+2 1e-4\nMn+3 1e-8'],
    ['from none of the products', 'Fe+2 0\nFe+3 1e-4\nMn+2 1e-4\nMn+3 0']]) {
    const tied = batch(`${start}\ne- electron`, `${FE}\n${MN}`, 'EQUILIBRATE = start');
    const full = batch(start, 'Fe+3 + Mn+2 <=> Fe+2 + Mn+3, logK = -12.49', 'EQUILIBRATE = start');
    const yt = tied.initialState();
    const yf = full.initialState();
    const d = Math.max(...['Fe+2', 'Fe+3', 'Mn+2', 'Mn+3'].map((n) => Math.abs(val(tied, yt, n) / val(full, yf, n) - 1)));
    check(`two couples tied to the electron are the reaction between them, ${what}`,
      d < 1e-9 && tied.speciated[0].converged && full.speciated[0].converged,
      `within ${d.toExponential(1)}; Mn+3 ${val(tied, yt, 'Mn+3').toExponential(4)}`);
  }

  // A held run: an oxidant consumed at k[Ox] moves electrons from Fe(2) to
  // Fe(3), and the couples tied to the electron share them out by their K.
  const kFe = -13.02;
  const kA = -13.5;
  const k = 1e-3;
  const Ox0 = 5e-5;
  const held = batch(`Fe+2 1e-4\nFe+3 1e-8\nA 1e-4\nB 1e-8\nOx ${Ox0}\nRed 0\ne- electron`,
    `${FE}\nA <=> B + e-, logK = ${kA}`, 'EQUILIBRATE = always',
    `Ox + Fe+2 => Red + Fe+3, r = k*[Ox], k = ${k}`);
  const c0 = held.toConcentrations(held.initialState());
  const FeT = val(held, c0, 'Fe+2') + val(held, c0, 'Fe+3');
  const AT = val(held, c0, 'A') + val(held, c0, 'B');
  const O0 = val(held, c0, 'Fe+3') + val(held, c0, 'B');
  const rh = run(held, { tend: 5000, outputTimes: [500, 1000, 2000, 5000] });
  let dev = 0;
  rh.grid.t.forEach((t, q) => {
    const c = held.toConcentrations(rh.grid.y[q]);
    const O = O0 + Ox0 * (1 - Math.exp(-k * t));
    const KF = 10 ** kFe;
    const KA = 10 ** kA;
    let lo = -60;
    let hi = 60;
    for (let i = 0; i < 300; i++) {
      const mid = (lo + hi) / 2;
      const a = Math.exp(mid);
      if (FeT * KF / (KF + a) + AT * KA / (KA + a) > O) lo = mid; else hi = mid;
    }
    const a = Math.exp((lo + hi) / 2);
    dev = Math.max(dev, Math.abs(val(held, c, 'Fe+3') / (FeT * KF / (KF + a)) - 1),
      Math.abs(val(held, c, 'B') / (AT * KA / (KA + a)) - 1), Math.abs(Math.log(val(held, c, 'e-') / a)));
  });
  check('a held run: an oxidant at k[Ox] moves electrons the two couples share by their K, against the closed solution',
    dev < 1e-8 && held.warnings.length === 0, `within ${dev.toExponential(1)} over 5000 s`);

  // Fixed, the electron is a redox buffer: the pe stays, and the couple with it.
  const buffered = batch('Fe+2 1e-4\nFe+3 1e-8\nOx 5e-5\nRed 0\ne- electron pe=12 fixed', FE,
    'EQUILIBRATE = always', `Ox + Fe+2 => Red + Fe+3, r = k*[Ox], k = ${k}`);
  const rb = run(buffered, { tend: 2000 });
  const cb = buffered.toConcentrations(last(rb));
  check('  fixed, the electron holds the pe: Fe3/Fe2 stays K/a(e-) while the oxidant comes and goes',
    Math.abs((val(buffered, cb, 'Fe+3') / val(buffered, cb, 'Fe+2')) / ratio - 1) < 1e-9
    && Math.abs(Math.log10(val(buffered, cb, 'e-')) + 12) < 1e-14, `Fe3/Fe2 ${(val(buffered, cb, 'Fe+3') / val(buffered, cb, 'Fe+2')).toExponential(6)}`);

  // The equivalence point: oxygen into a water whose Fe(2) it oxidises to
  // Fe(OH)3, with methane tied to the same pe. Past the point the pe jumps by
  // ten and methane falls to 1e-140; the run goes through it.
  const jump = batch(`H+ 1e-7\nOH- 1e-7\nNa+ 3e-3\nCl- 1e-3\nFe+2 2e-5\nFe+3 0\nO2 0\nH2 0\nCH4 0
HCO3- 2e-3\nCO2 2e-4\nFe(OH)3 0\ne- electron pe=-3`,
  `H2O <=> OH- + H+, logK = -14\n${FE}\n2 H2O <=> O2 + 4 H+ + 4 e-, logK = -86.08
2 H+ + 2 e- <=> H2, logK = -3.15\nHCO3- + 9 H+ + 8 e- <=> CH4 + 3 H2O, logK = 27.85
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+, logK = -12.56\nCO2 + H2O <=> HCO3- + H+, logK = -6.35`,
  'EQUILIBRATE = always', '=> O2, r = 1e-8');
  const rj = run(jump, { tend: 1000, rtol: 1e-8, outputTimes: [250, 1000] });
  const ce = jump.toConcentrations(last(rj));
  const c250 = jump.toConcentrations(rj.grid.y[0]);
  const peAt = (c) => -Math.log10(val(jump, c, 'e-'));
  check('the equivalence point: oxygen past the last Fe(2) sends the pe up by nine, and the run goes through it',
    Math.abs(val(jump, ce, 'O2') / 5e-6 - 1) < 1e-6 && peAt(c250) < 4 && peAt(ce) > 12.5
    && Math.abs(val(jump, ce, 'Fe(OH)3') + val(jump, ce, 'Fe+3') + val(jump, ce, 'Fe+2') - 2e-5) < 1e-17,
    `pe ${peAt(c250).toFixed(2)} at 250 s, ${peAt(ce).toFixed(2)} at the end; O2 ${val(jump, ce, 'O2').toExponential(6)} `
      + `for 5e-6; ${rj.stats.nsteps} steps, ${rj.stats.nfailed} failed`);

  // A redox front in a column: Fe(3) water into a column whose immobile
  // reductant it oxidises. Behind the front the reductant is spent, so the
  // front moves at v/R, R = 1 + Y/Fe3_in, as a sorbing species would.
  const N = 80;
  const L = 0.08;
  const v = 1e-5;
  const Cin = 6e-4;
  const Ycap = 1e-3;
  const Rf = 1 + Ycap / Cin;
  const T = (0.04 * Rf) / v;
  const col = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = ${N}
LENGTH = ${L}
VELOCITY = ${v}
DIFFUSION = 1
ADVECTION = 1
EQUILIBRATE = always
TEND = ${T}

<SPECIES>
Fe+2  1e-9   D=1e-10  left=1e-9
Fe+3  1e-15  D=1e-10  left=${Cin}
Yr    ${Ycap}  immobile
Yo    1e-12  immobile
e-    electron

<EQUILIBRIUM>
${FE}
Yr <=> Yo + e-, logK = -5
`);
  const rc = FacsimileODE.runModel(col, { solver: 'ndf', tend: T, rtol: 1e-8, atol: 1e-20, nonNegative: true,
    outputTimes: [T / 2, T] });
  const nsc = col.speciesNames.length;
  let rel = 0;
  for (const yy of rc.grid.y) {
    const c = col.toConcentrations(yy);
    for (let i = 0; i < N; i++) {
      const b = i * nsc;
      rel = Math.max(rel, Math.abs(Math.log10(c[b + 1] * c[b + 4] / c[b]) + 13.02),
        Math.abs(Math.log10(c[b + 3] * c[b + 4] / c[b + 2]) + 5));
    }
  }
  const cEnd = col.toConcentrations(rc.grid.y[1]);
  let xFe = NaN;
  for (let i = 0; i < N - 1; i++) {
    const a = cEnd[i * nsc + 1];
    const b2 = cEnd[(i + 1) * nsc + 1];
    if (a >= Cin / 2 && b2 < Cin / 2) { xFe = col.grid.centres[i] + ((a - Cin / 2) / (a - b2)) * (col.grid.centres[i + 1] - col.grid.centres[i]); break; }
  }
  check('a redox front: Fe(3) water into a column of reductant, the couples held in every cell, the front at v t/R',
    rel < 1e-12 && Math.abs(xFe - 0.04) < 2 * (L / N),
    `relations within ${rel.toExponential(1)} in log; front at ${(xFe * 100).toFixed(3)} cm for 4 cm (R = ${Rf.toFixed(4)})`);
  /*
    Its Jacobian, through each cell's speciation, on a short column where
    every couple is buffered and the activities follow the ionic strength:
    at the start, and part of the way. (A cell the front has passed holds
    Fe(2) at 1e-12, where ln Fe(2) moves by 1e9 per unit of a total and a
    central difference cannot follow it; and a total nudged by the
    difference's step can be one no water has.)
  */
  const small = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 3
LENGTH = 0.003
VELOCITY = 1e-5
DIFFUSION = 1
ADVECTION = 1
EQUILIBRATE = always
ACTIVITY = davies
TEND = 100

<SPECIES>
Fe+2  1e-4   D=1e-10  left=1e-9
Fe+3  1e-6   D=1e-10  left=${Cin}
Na+   1e-3   D=1e-10  left=1e-3
Cl-   3e-3   D=1e-10  left=2e-3
Yr    ${Ycap}  immobile
Yo    1e-4   immobile
e-    electron

<EQUILIBRIUM>
${FE}
Yr <=> Yo + e-, logK = -5
`);
  const rs = FacsimileODE.runModel(small, { solver: 'ndf', tend: 100, rtol: 1e-8, atol: 1e-20, nonNegative: true,
    outputTimes: [50] });
  const vj0 = RtmModel.verifyJacobian(small, 0, small.initialState());
  const vj1 = RtmModel.verifyJacobian(small, 50, rs.grid.y[0]);
  check('  its Jacobian, through each cell\'s speciation, against a central difference, at the start and on the way',
    vj0.discrepancies.length === 0 && vj1.discrepancies.length === 0, `${vj0.checked} and ${vj1.checked} entries`);

  // Under ACTIVITY the electron's coefficient is 1, and it counts in neither I nor the water.
  const wa = batch('Na+ 0.05\nCl- 0.05\nFe+2 1e-4\nFe+3 1e-6\ne- electron pe=4', FE, 'ACTIVITY = davies\nEQUILIBRATE = start');
  const ie = wa.speciesNames.indexOf('e-');
  const lnG = new Float64Array(wa.speciesNames.length);
  RtmModel.activityAt(wa.act, wa.initialState(), 0, lnG, new Float64Array(wa.speciesNames.length), 0);
  check('under ACTIVITY the electron\'s activity coefficient is 1, and it is neither an ion nor a solute',
    lnG[ie] === 0 && wa.act.z[ie] === 0 && !wa.act.solute[ie]);
  // A rate law reads the electron's activity.
  const reads = batch('Fe+2 1e-4\nFe+3 1e-6\nT 1\ne- electron pe=4', FE, 'EQUILIBRATE = start', 'T => , r = 1e3*[e-]');
  const rr = run(reads, { tend: 1 });
  check('  and a rate law reads its activity, 10^-pe, as [e-]',
    Math.abs((1 - last(rr)[reads.speciesNames.indexOf('T')]) / 0.1 - 1) < 1e-9);

  // The texts it refuses, and what it says.
  const refusal = (species, rel, more = '', reactions = '') => {
    try { batch(species, rel, more, reactions); } catch (e) { return e.message; }
    return '';
  };
  const cases = [
    ['two electrons', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron\nE- electron', `${FE}\nFe+2 <=> Fe+3 + E-, logK = -13`,
      /a model has one/, 'EQUILIBRATE = start'],
    ['an electron in no relation', 'Fe+2 1e-4\nOH- 1e-7\nFeOH+ 0\ne- electron pe=4', 'Fe+2 + OH- <=> FeOH+, logK = 4',
      /is the electron and in no relation/],
    ['the electron in a fast pair', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron pe=4', `${FE}, kf = 1`,
      /no amount and cannot react at a rate/],
    ['the electron in a reaction, the relations not held', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron pe=4', FE,
      /can take or give electrons only where the relations with it are held/, '', 'Fe+3 + e- => Fe+2, k = 1'],
    ['an electron that moves', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron pe=4 D=1e-9', FE, /never moves: it takes no D/],
    ['a charge on the electron', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron pe=4 z=-1', FE, /takes no z, a or b/],
    ['a pe on anything else', 'Fe+2 1e-4 pe=4\nFe+3 1e-6\ne- electron', FE, /pe is the electron's/],
    ['an activity and a pe', 'Fe+2 1e-4\nFe+3 1e-6\ne- 1e-4 electron pe=4', FE, /both an activity and a pe/],
    ['nothing to start from', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron', FE, /has nothing to start from/],
    ['fixed with no pe', 'Fe+2 1e-4\nFe+3 1e-6\ne- electron fixed', FE, /is fixed: give it the pe/, 'EQUILIBRATE = start'],
  ];
  const wrong = cases.filter(([, sp, rel, re, more, rx]) => !re.test(refusal(sp, rel, more, rx)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, sp, rel, , more, rx]) => `${what}: "${refusal(sp, rel, more, rx)}"`).join(' | '));
  /*
    A reaction that takes or gives electrons, held all through the run: the
    couples tied to the electron share out what it moves, so X + e- => Fe+2
    is X => Fe+3 with the couple at one pe -- O2 taking its share of the
    electrons as the iron is oxidised -- run for run, and its Jacobian.
  */
  const eRx = (rx) => batch('Fe+2 1e-3\nFe+3 1e-6\ne- electron\nO2 0\nH+ 1e-7 fixed\nX 1e-3 mineral',
    `${FE}\n0.5 H2O <=> 0.25 O2 + H+ + e-, logK = -20.78`, 'EQUILIBRATE = always', rx);
  const viaE = eRx('X + e- => Fe+2, r = 2*[X]');
  const viaFe3 = eRx('X => Fe+3, r = 2*[X]');
  const rE = run(viaE, { tend: 1, rtol: 1e-10 });
  const rF = run(viaFe3, { tend: 1, rtol: 1e-10 });
  const yE = viaE.toConcentrations(last(rE), rE.t[rE.t.length - 1]);
  const yF = viaFe3.toConcentrations(last(rF), rF.t[rF.t.length - 1]);
  const dE = Math.max(...yE.map((v, i) => Math.abs(v - yF[i]) / Math.max(Math.abs(yF[i]), 1e-30)));
  const jE = RtmModel.verifyJacobian(viaE, rE.t[rE.t.length >> 1], rE.y[rE.y.length >> 1]);
  check('a reaction that takes electrons, the relations held: X + e- => Fe+2 is X => Fe+3, the couples sharing out '
    + 'the electrons, O2 its part of them; and the Jacobian', dE < 1e-12 && yE[viaE.speciesNames.indexOf('O2')] > 1e-6
    && jE.discrepancies.length === 0,
  `the two runs apart by ${dE.toExponential(1)}, Fe+3 ${yE[viaE.speciesNames.indexOf('Fe+3')].toExponential(4)}, O2 `
    + `${yE[viaE.speciesNames.indexOf('O2')].toExponential(4)}; the Jacobian ${jE.discrepancies.length} of ${jE.checked} off`);
  const startOnly = batch('Fe+2 9e-4\nFe+3 1e-4\ne- electron', FE, 'EQUILIBRATE = start');
  check('  and relations with the electron put on at the start only are said to be, the pe staying put after',
    startOnly.warnings.some((w) => /put on at the start only: the pe then stays as it was/.test(w))
    && !held.warnings.some((w) => /the pe then stays/.test(w)));
}

/* ======================================================================
   2t. The specific ion interaction theory (ACTIVITY = sit, <SIT>)

   PHREEQC's SIT (sit.cpp): log gamma = -A z^2 sqrt(I)/(1 + 1.5 sqrt(I)) +
   sum over the species paired with it of (eps + eps1 I) m, and the water's
   activity from SIT's osmotic coefficient. Here against the same formulas
   written out apart from the page's code: the coefficients and their
   derivatives, the start, a run held throughout as salt raises I, a fast
   pair, an exchanger, a rate law, the electron's projected form with its
   reduced speciation, and a column; and the texts it refuses. Against
   PHREEQC itself in test-phreeqc.js.
   ====================================================================== */
console.log('\n--- SIT ---');
{
  /*
    SIT written out apart from the page: log10 gamma of each species and
    log10 a(H2O), A the water's own, at the a(H2O) it gives (a fixed point
    from the pure water's A; debyeHuckelAB's A at an a(H2O) is PHREEQC's,
    test-phreeqc.js).
  */
  const sitHand = (names, c, pairs, tc = 25) => {
    const z = names.map((n) => (n === 'H2O' ? 0 : RtmModel.chargeOf(n)));
    let I = 0;
    let osum = 0;
    names.forEach((n, i) => { if (n !== 'H2O') { I += 0.5 * z[i] * z[i] * c[i]; osum += c[i]; } });
    const sq = Math.sqrt(I);
    const T = 1 + 1.5 * sq;
    const lg = names.map(() => 0);
    let osPairs = 0;
    for (const [a, b, e, e1 = 0] of pairs) {
      const i = names.indexOf(a);
      const j = names.indexOf(b);
      lg[i] += (e + e1 * I) * c[j];
      lg[j] += (e + e1 * I) * c[i];
      const half = !z[i] && !z[j] ? 0.5 : 1;
      osPairs += c[i] * c[j] * (e * half + e1 * (1 + half * I));
    }
    const lawAt = (A) => -(osum + Math.LN10 * ((-2 * A / 3.375) * (T - 2 * Math.log(T) - 1 / T) + osPairs)) / 55.50837
      / Math.LN10;
    let A = RtmModel.debyeHuckelAB(tc).A;
    for (let it = 0; it < 20; it++) A = RtmModel.debyeHuckelAB(tc, 1, 10 ** lawAt(A)).A;
    const D = (-A * sq) / T;
    names.forEach((n, i) => { if (n !== 'H2O') lg[i] += z[i] * z[i] * D; });
    return { lg, I, law: lawAt(A), A };
  };

  // The coefficients, by hand.
  const sp = (name) => ({ name, z: null, dha: null, dhb: null, line: 1 });
  const names = ['Na+', 'Cl-', 'Ca+2', 'HCO3-', 'CO2', 'UO2(CO3)3-4'];
  const pairs = [['Na+', 'Cl-', 0.03], ['Ca+2', 'Cl-', 0.14], ['Na+', 'HCO3-', 0, 0.01], ['CO2', 'CO2', 0.05],
    ['CO2', 'Na+', 0.02], ['Na+', 'UO2(CO3)3-4', -0.01]];
  const act = RtmModel.activityModel({ ACTIVITY: 'sit', TEMPERATURE: 25, given: new Set() }, names.map(sp), [],
    pairs.map(([a, b, e, e1], i) => ({ text: `${a} ${b} ${e}${e1 ? ` eps1=${e1}` : ''}`, line: i + 1 })));
  const C = Float64Array.of(1.0, 1.2, 0.1, 0.003, 0.01, 1e-6);
  const lnG = new Float64Array(6);
  const dG = new Float64Array(6);
  const w = RtmModel.activityAt(act, C, 0, lnG, dG);
  const hand = sitHand(names, C, pairs);
  const worst = Math.max(...names.map((n, i) => Math.abs(lnG[i] / Math.LN10 - hand.lg[i])));
  const A1 = RtmModel.debyeHuckelAB(25).A;
  check('each coefficient by hand: the Debye-Hueckel term, A at the water\'s own a(H2O), the pairs, a neutral species '
    + 'paired with itself, eps1 I', worst < 1e-15 && Math.abs(w.I - hand.I) < 1e-15 && hand.A !== A1,
  `within ${worst.toExponential(1)} in log gamma at I = ${w.I}; `
      + `${names.map((n, i) => `${n} ${(lnG[i] / Math.LN10).toFixed(5)}`).join(', ')}; A ${hand.A.toPrecision(12)} for `
      + `${A1.toPrecision(12)} at a(H2O) = 1`);
  check('  and the water\'s activity, from SIT\'s osmotic coefficient', Math.abs(w.lnAw / Math.LN10 - hand.law) < 1e-16,
    `log a(H2O) ${(w.lnAw / Math.LN10).toFixed(10)}`);
  // The derivatives the Jacobians read: in I, in each partner, and the water's in each species.
  let dWorst = 0;
  const dAwv = Float64Array.from(w.dAwv);
  const dGw = w.dGw ? Float64Array.from(w.dGw) : null;
  for (let k = 0; k < 6; k++) {
    const h = 1e-4 * Math.max(C[k], 1e-3);
    const up = Float64Array.from(C);
    const dn = Float64Array.from(C);
    up[k] += h;
    dn[k] -= h;
    const g1 = new Float64Array(6);
    const g2 = new Float64Array(6);
    const w1 = RtmModel.activityAt(act, up, 0, g1, new Float64Array(6));
    const w2 = RtmModel.activityAt(act, dn, 0, g2, new Float64Array(6));
    dWorst = Math.max(dWorst, Math.abs((w1.lnAw - w2.lnAw) / (2 * h) - dAwv[k]) / Math.max(Math.abs(dAwv[k]), 1e-6));
    for (let s = 0; s < 6; s++) {
      const r = act.sit.rows[s];
      let an = dG[s] * 0.5 * act.z[k] * act.z[k] + dGw[s] * dAwv[k];
      if (r) for (let q = 0; q < r.k.length; q++) if (r.k[q] === k) an += Math.LN10 * (r.e[q] + w.I * r.e1[q]);
      dWorst = Math.max(dWorst, Math.abs((g1[s] - g2[s]) / (2 * h) - an) / Math.max(Math.abs(an), 1e-3));
    }
  }
  check('  their derivatives, in I, in each species paired, through A in the water\'s, and the water\'s in each '
    + 'species, against differences', dWorst < 1e-6 && dGw.some((v) => v !== 0), dWorst.toExponential(1));

  // A water held throughout as salt goes in.
  const water = (more, pairsText = '') => `
<SETTINGS>
MODE = batch
TEND = 1e5
ACTIVITY = sit
${more}

<SPECIES>
H+      1e-7
OH-     1e-7
CO2     2e-4
HCO3-   2e-3
CO3-2   1e-9
Na+     0.1
Cl-     0.098

<EQUILIBRIUM>
H2O <=> H+ + OH-,          logK = -14.0
CO2 + H2O <=> H+ + HCO3-,  logK = -6.35
HCO3- <=> H+ + CO3-2,      logK = -10.33

<SIT>
H+    Cl-     0.12
Na+   Cl-     0.03
Na+   OH-     0.04
Na+   HCO3-   0.0
Na+   CO3-2  -0.08
CO2   Na+     0.02   eps1=0.001
${pairsText}
<REACTIONS>
`;
  const wPairs = [['H+', 'Cl-', 0.12], ['Na+', 'Cl-', 0.03], ['Na+', 'OH-', 0.04], ['Na+', 'HCO3-', 0],
    ['Na+', 'CO3-2', -0.08], ['CO2', 'Na+', 0.02, 0.001]];
  const off = (m, c) => {
    const h = sitHand(m.speciesNames, c, wPairs);
    const la = (n) => Math.log10(c[m.speciesNames.indexOf(n)]) + h.lg[m.speciesNames.indexOf(n)];
    return { by: Math.max(Math.abs(la('H+') + la('OH-') - h.law + 14), Math.abs(la('H+') + la('HCO3-') - la('CO2') - h.law + 6.35),
      Math.abs(la('H+') + la('CO3-2') - la('HCO3-') + 10.33)), I: h.I };
  };
  const start = RtmModel.compile(water('EQUILIBRATE = 1'));
  const c0 = start.initialState();
  check('the start speciated in SIT\'s activities: every relation, the water in two of them',
    off(start, c0).by < 1e-12 && Math.abs((c0[2] + c0[3] + c0[4]) / 2.200001e-3 - 1) < 1e-14,
    `${off(start, c0).by.toExponential(1)} in log K`);
  const held = RtmModel.compile(`${water('EQUILIBRATE = always')}=> Na+ + Cl-, k = 1.5e-5\n`);
  const run1 = FacsimileODE.runModel(held, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  let hw = 0;
  for (const y of run1.y) hw = Math.max(hw, off(held, held.toConcentrations(y)).by);
  const hEnd = held.toConcentrations(run1.y[run1.y.length - 1]);
  const vh0 = RtmModel.verifyJacobian(held, 0, held.initialState());
  const vh1 = RtmModel.verifyJacobian(held, 1e5, run1.y[run1.y.length - 1]);
  check('held throughout as salt raises I from 0.1 to 1.6: every stored point on every relation, in SIT\'s activities',
    hw < 1e-12 && off(held, hEnd).I > 1.5, `${hw.toExponential(1)} in log K over ${run1.t.length} points, I `
      + `${off(held, hEnd).I.toFixed(3)} at the end`);
  check('  the Jacobian, the partners and the water included, at the start and the end',
    vh0.discrepancies.length === 0 && vh1.discrepancies.length === 0, `${vh0.checked} and ${vh1.checked} entries`);
  const pair = RtmModel.compile(`${water('EQUILIBRATE = 1').replace('logK = -14.0', 'logK = -14.0, kf = 1e3')}`
    + '=> Na+ + Cl-, k = 1.5e-5\n');
  const rp = FacsimileODE.runModel(pair, { solver: 'ndf', tend: 1e5, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const pEnd = rp.y[rp.y.length - 1];
  const ph = sitHand(pair.speciesNames, pEnd, wPairs);
  const kw = Math.log10(pEnd[0]) + ph.lg[0] + Math.log10(pEnd[1]) + ph.lg[1] - ph.law + 14;
  const vp = [RtmModel.verifyJacobian(pair, 0, pair.initialState()), RtmModel.verifyJacobian(pair, 1e5, pEnd)];
  check('a fast pair relaxes to its K in SIT\'s activities, and its Jacobian reads the partners',
    Math.abs(kw) < 1e-7 && vp.every((v) => v.discrepancies.length === 0), `${kw.toExponential(1)} in log K; `
      + `${vp[0].checked} entries`);
  // A rate law reading an activity and a saturation.
  const rated = RtmModel.compile(`${water('EQUILIBRATE = always')}=> Na+ + Cl-, k = 1.5e-5\n`
    + 'CO2 => HCO3- + H+, r = 1e-7 * {CO2} * (1 - SR(Natron))\n'
    + '<PHASES>\nNatron <=> 2 Na+ + CO3-2, logK = -1.3\n');
  const vr = RtmModel.verifyJacobian(rated, 0, rated.initialState());
  check('  a rate law reading {CO2} and SR(phase) under SIT: its Jacobian through the partners', vr.discrepancies.length === 0,
    `${vr.checked} entries`);
  // A column held throughout: the Jacobian across the cells.
  const col = RtmModel.compile(water('EQUILIBRATE = always')
    .replace('MODE = batch', 'MODE = transport\nCELLS = 5\nLENGTH = 0.01\nDIFFUSION = 1')
    .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)$/gm, (m0, n, s1, v) => `${n}${s1}${v}  D=1e-9`));
  const colY = col.initialState();
  for (let k = 0; k < colY.length; k++) colY[k] += 1e-3 * Math.sin(k);
  const vc = RtmModel.verifyJacobian(col, 0, colY);
  check('  and in a column with every relation held, the Jacobian across the cells', vc.discrepancies.length === 0
    && col.nalgebraic === 5 * 5, `${vc.checked} entries`);

  // An exchanger: each species on it takes its ion's coefficient to the ion's power.
  const ex = RtmModel.compile(water('EQUILIBRATE = always')
    .replace('Cl-     0.098', 'Cl-     0.098\nCa+2    0.001\nX-      exchanger 1e-3\nNaX     exchange\nCaX2    exchange  a=5 b=0.1')
    .replace('HCO3- <=> H+ + CO3-2,      logK = -10.33', 'HCO3- <=> H+ + CO3-2,      logK = -10.33\n'
      + 'Na+ + X- <=> NaX,           logK = 0\nCa+2 + 2 X- <=> CaX2,      logK = 0.8')
    .replace('CO2   Na+     0.02   eps1=0.001', 'CO2   Na+     0.02   eps1=0.001\nCa+2  Cl-     0.14'));
  const ey = ex.toConcentrations(ex.initialState());
  const eg = new Float64Array(ex.speciesNames.length);
  RtmModel.activityAt(ex.act, ey, 0, eg, new Float64Array(ex.speciesNames.length));
  const at = (n) => ex.speciesNames.indexOf(n);
  const cap = ey[at('NaX')] + 2 * ey[at('CaX2')];
  const exOff = Math.max(Math.abs(eg[at('NaX')] - eg[at('Na+')] - Math.log(1 / cap)),
    Math.abs(eg[at('CaX2')] - eg[at('Ca+2')] - Math.log(2 / cap)));
  const ve = RtmModel.verifyJacobian(ex, 0, ex.initialState());
  check('a species on an exchanger takes its ion\'s SIT coefficient, as PHREEQC\'s does: NaX Na+\'s, CaX2 Ca+2\'s; '
    + 'a and b given to one are not used, and said so', exOff < 1e-13 && ve.discrepancies.length === 0
    && ex.warnings.some((x) => /a and b given to CaX2 are not used/.test(x)), `within ${exOff.toExponential(1)}; `
      + `${ve.checked} Jacobian entries`);

  // The electron under SIT: the projected form, each cell speciated in its components and V's sums.
  const redox = (more = '', species = '', rels = '', sitMore = '') => `
<SETTINGS>
MODE = batch
TEND = 1e4
ACTIVITY = sit
EQUILIBRATE = always
${more}

<SPECIES>
H+      1e-7
OH-     1e-7
Na+     0.5
Cl-     0.5
Fe+2    1e-4
Fe+3    1e-9
FeCl+   1e-6
SO4-2   1e-3
HS-     1e-6
NaSO4-  1e-4
O2      1e-12
e-      electron pe=-2
${species}
<EQUILIBRIUM>
H2O <=> H+ + OH-,                    logK = -14.0
Fe+2 <=> Fe+3 + e-,                  logK = -13.02
Fe+2 + Cl- <=> FeCl+,                logK = 0.14
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O, logK = 33.65
Na+ + SO4-2 <=> NaSO4-,              logK = 0.7
2 H2O <=> O2 + 4 H+ + 4 e-,          logK = -86.08
${rels}
<SIT>
Na+    Cl-     0.03
H+     Cl-     0.12
Na+    OH-     0.04
Fe+2   Cl-     0.17
Fe+3   Cl-     0.56   eps1=0.01
FeCl+  Cl-     0.2
Na+    SO4-2  -0.12
Na+    HS-     0.05
Na+    NaSO4-  0.0
O2     Na+     0.03
O2     O2      0.01
${sitMore}
<REACTIONS>
=> O2, k = 2e-9
`;
  const rPairs = [['Na+', 'Cl-', 0.03], ['H+', 'Cl-', 0.12], ['Na+', 'OH-', 0.04], ['Fe+2', 'Cl-', 0.17],
    ['Fe+3', 'Cl-', 0.56, 0.01], ['FeCl+', 'Cl-', 0.2], ['Na+', 'SO4-2', -0.12], ['Na+', 'HS-', 0.05],
    ['Na+', 'NaSO4-', 0], ['O2', 'Na+', 0.03], ['O2', 'O2', 0.01]];
  // Every relation at every stored point against SIT written out, at the run's temperature.
  const redoxOff = (mdl, run, tc = 25) => {
    let off = 0;
    for (const y of run.y) {
      const c = mdl.toConcentrations(y);
      const nm = mdl.speciesNames.filter((n) => n !== 'e-');
      const cc = nm.map((n) => c[mdl.speciesNames.indexOf(n)]);
      const h = sitHand(nm, cc, rPairs, tc);
      const la = (n) => (n === 'e-' ? Math.log10(c[mdl.speciesNames.indexOf('e-')])
        : Math.log10(cc[nm.indexOf(n)]) + h.lg[nm.indexOf(n)]);
      off = Math.max(off, Math.abs(la('H+') + la('OH-') - h.law + 14), Math.abs(la('Fe+3') + la('e-') - la('Fe+2') + 13.02),
        Math.abs(la('FeCl+') - la('Fe+2') - la('Cl-') - 0.14),
        Math.abs(la('HS-') + 4 * h.law - la('SO4-2') - 9 * la('H+') - 8 * la('e-') - 33.65),
        Math.abs(la('NaSO4-') - la('Na+') - la('SO4-2') - 0.7), Math.abs(la('O2') + 4 * la('H+') + 4 * la('e-') - 2 * h.law + 86.08));
    }
    return off;
  };
  const ox = RtmModel.compile(redox());
  const ro = FacsimileODE.runModel(ox, { solver: 'ndf', tend: 1e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const rw = redoxOff(ox, ro);
  const oEnd = ox.toConcentrations(ro.y[ro.y.length - 1]);
  const vo = [RtmModel.verifyJacobian(ox, 0, ox.initialState()), RtmModel.verifyJacobian(ox, 1e4, ro.y[ro.y.length - 1])];
  check('the electron under SIT, oxygen into a saline Fe and S water: every stored point on every relation in SIT\'s '
    + 'activities, the pe from -2 to above 11', rw < 1e-12 && -Math.log10(oEnd[ox.speciesNames.indexOf('e-')]) > 11,
  `${rw.toExponential(1)} in log K over ${ro.t.length} points; pe ${(-Math.log10(oEnd[ox.speciesNames.indexOf('e-')])).toFixed(4)} `
    + `at the end, ${ro.stats.nfailed} steps failed`);
  check('  its Jacobian through each cell\'s speciation, at the start and the end',
    vo.every((v) => v.discrepancies.length === 0), `${vo[0].checked} and ${vo[1].checked} entries`);
  // At 150 C the water is on its vapour pressure and A goes a part in 1e3 as far as ln a(H2O): the speciation's ln a column.
  const hox = RtmModel.compile(redox('TEMPERATURE = 150'));
  const hro = FacsimileODE.runModel(hox, { solver: 'ndf', tend: 1e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const hmid = Math.floor(hro.y.length / 2);
  const hvo = [[0, hox.initialState()], [hro.t[hmid], hro.y[hmid]], [1e4, hro.y[hro.y.length - 1]]]
    .map(([t, y]) => RtmModel.verifyJacobian(hox, t, y));
  const hrw = redoxOff(hox, hro, 150);
  check('  and at 150 C, on the vapour pressure, where A goes a part in 1e3 as far as ln a(H2O): every stored point on '
    + 'every relation, and the Jacobian at the start, the middle and the end', hrw < 1e-12
    && hvo.every((v) => v.discrepancies.length === 0), `${hrw.toExponential(1)} in log K over ${hro.t.length} points; `
      + `${hvo.map((v) => v.checked).join(', ')} entries`);
  // An ion in no relation but paired, a species on an exchanger, a column: the Jacobian.
  const variants = [
    ['an ion outside every relation, paired in <SIT>', redox('', 'K+      0.1', '', 'K+     Cl-     0.0\nK+     SO4-2  -0.06\nK+     HS-     0.02')],
    ['an exchanger', redox('', 'X-      exchanger 1e-3\nNaX     exchange\nFeX2    exchange',
      'Na+ + X- <=> NaX, logK = 0\nFe+2 + 2 X- <=> FeX2, logK = 0.44')],
  ];
  const vv = variants.map(([label, t]) => {
    const m = RtmModel.compile(t.replace('MODE = batch', 'MODE = transport\nCELLS = 3\nLENGTH = 0.01\nDIFFUSION = 1')
      .replace(/^(\S+)(\s+)([0-9][0-9.eE+-]*)$/gm, (m0, n, s1, v) => `${n}${s1}${v}  D=1e-9`));
    const y = m.initialState();
    return [label, RtmModel.verifyJacobian(m, 0, y)];
  });
  check(`  and with ${vv.map(([l]) => l).join(', and with ')}, in a column of three cells`,
    vv.every(([, v]) => v.discrepancies.length === 0 && v.checked > 200), vv.map(([l, v]) => `${v.checked} entries`).join(', '));

  // The texts it refuses.
  const refuse = (t) => { try { RtmModel.compile(t); return ''; } catch (e) { return e.message; } };
  const cases = [
    ['<SIT> without ACTIVITY = sit', water('').replace('ACTIVITY = sit', 'ACTIVITY = davies'), /is read under ACTIVITY = sit, not davies/],
    ['a species not in <SPECIES>', water('', 'K+ Cl- 0.0'), /"K\+" in <SIT> is not in <SPECIES>/],
    ['a species that is no solute', water('').replace('Cl-     0.098', 'Cl-     0.098\nCalcite 1 mineral')
      .replace('<REACTIONS>', 'Calcite Na+ 0.1\n<REACTIONS>'), /Calcite is no solute/],
    ['a pair given twice, either way round', water('', 'Cl- Na+ 0.05'), /Cl- and Na\+ are paired twice in <SIT>, on lines/],
    ['a line that is not two species and a number', water('', 'Na+ 0.03'), /is not two species and their coefficient/],
    ['anything but eps1=', water('', 'H+ OH- 0.1 eps2=0.1'), /takes eps1= .* and nothing else/],
  ];
  const wrong = cases.filter(([, t, re]) => !re.test(refuse(t)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, t]) => `${what}: "${refuse(t)}"`).join(' | '));
  check('  and a and b on a species under SIT are said not to be used',
    RtmModel.compile(water('').replace('Na+     0.1', 'Na+     0.1  a=4 b=0.06')).warnings
      .some((x) => /ACTIVITY = sit takes no a or b/.test(x)));
}

/* ======================================================================
   2s. A gas phase (gas, GAS_VOLUME, GAS_PRESSURE)

   PHREEQC's GAS_PHASE, ideal: a gas's activity is its partial pressure, n R
   T/V in a fixed volume, its share of the bubble times the total at a fixed
   pressure, the bubble there only while the water holds its gases at the
   total between them. Against the closed forms: CO2 shared between water and
   a volume of gas, and CO2 coming into a water with N2 at a fixed pressure --
   when the bubble forms, what it then holds, when it dissolves again --; the
   electron's projected form with a bubble; and the texts it refuses.
   ====================================================================== */
console.log('\n--- a gas phase ---');
{
  const R = 0.0820597;
  const T = 298.15;
  const KC = 10 ** -1.468;
  const KN = 10 ** -3.18;
  // CO2 between water and 0.5 L of gas, carbonic acid taking some: the start, then CO2 coming in.
  const vol = `
<SETTINGS>
MODE = batch
TEND = 1e4
EQUILIBRATE = always
GAS_VOLUME = 0.5

<SPECIES>
H+      1e-4
OH-     1e-10
CO2     1e-3
HCO3-   1e-6
CO2(g)  0      gas

<EQUILIBRIUM>
 <=> H+ + OH-,              logK = -14
CO2 <=> H+ + HCO3-,         logK = -6.35
CO2(g) <=> CO2,             logK = -1.468

<REACTIONS>
=> CO2, k = 1e-8
`;
  const mv = RtmModel.compile(vol);
  const at = (m, c, n) => c[m.speciesNames.indexOf(n)];
  const henry = (m, c) => {
    const p = at(m, c, 'CO2(g)') * R * T / 0.5;
    return Math.abs(Math.log10(at(m, c, 'CO2')) - Math.log10(KC * p));
  };
  // By hand: CO2 from the gas pressure p; H+ from what the relations conserve, H+ - OH- - HCO3- as the start
  // gives it; all carbon 1.001e-3.
  const Ctot = 1e-3 + 1e-6;
  const Hx = 1e-4 - 1e-10 - 1e-6;
  const solve = (f, a, b) => { for (let i = 0; i < 200; i++) { const m = 0.5 * (a + b); if (f(m) > 0) b = m; else a = m; } return 0.5 * (a + b); };
  const pHand = solve((p) => {
    const co2 = KC * p;
    const h = (Hx + Math.sqrt(Hx * Hx + 4 * (1e-14 + 10 ** -6.35 * co2))) / 2;
    return co2 + (10 ** -6.35 * co2) / h + p * 0.5 / (R * T) - Ctot;
  }, 1e-12, 1);
  const c0 = mv.toConcentrations(mv.initialState());
  const p0 = at(mv, c0, 'CO2(g)') * R * T / 0.5;
  check('a fixed volume: CO2 shared between the water and 0.5 L of gas as the closed form shares it, n R T/V its pressure',
    Math.abs(p0 / pHand - 1) < 1e-12 && henry(mv, c0) < 1e-14, `${p0.toExponential(8)} atm for ${pHand.toExponential(8)}`);
  const rv = FacsimileODE.runModel(mv, { solver: 'ndf', tend: 1e4, rtol: 1e-9, atol: 1e-20, nonNegative: true });
  let hw = 0;
  let cw = 0;
  for (let k = 0; k < rv.t.length; k++) {
    const c = mv.toConcentrations(rv.y[k]);
    hw = Math.max(hw, henry(mv, c));
    cw = Math.max(cw, Math.abs((at(mv, c, 'CO2') + at(mv, c, 'HCO3-') + at(mv, c, 'CO2(g)')) / (Ctot + 1e-8 * rv.t[k]) - 1));
  }
  const vv = [RtmModel.verifyJacobian(mv, 0, mv.initialState()), RtmModel.verifyJacobian(mv, 1e4, rv.y[rv.y.length - 1])];
  check('  CO2 coming in: Henry\'s law at every stored point, the carbon all there, and the Jacobian',
    hw < 1e-12 && cw < 1e-10 && vv.every((v) => v.discrepancies.length === 0),
    `${hw.toExponential(1)} in log, carbon ${cw.toExponential(1)}; ${vv[0].checked} and ${vv[1].checked} entries`);

  // A bubble at 1 atm: CO2 made at k into a water with N2, then used up.
  const bubble = (n2, rx) => `
<SETTINGS>
MODE = batch
TEND = 4e4
EQUILIBRATE = always
GAS_PRESSURE = 1

<SPECIES>
CO2     0.01
N2      ${n2}
X       0.05
Y       0.1
Z       0
CO2(g)  0  gas
N2(g)   0  gas

<EQUILIBRIUM>
CO2(g) <=> CO2,  logK = -1.468
N2(g) <=> N2,    logK = -3.18

<REACTIONS>
${rx}
`;
  // CO2 at a steady 1e-6 mol/kg/s: the bubble forms when CO2/KC + N2/KN reaches 1, N2 all still dissolved.
  const mb = RtmModel.compile(bubble(1e-4, 'X => X + CO2, k = 2e-5'));
  const tForm = ((1 - 1e-4 / KN) * KC - 0.01) / 1e-6;
  const rb = FacsimileODE.runModel(mb, { solver: 'ndf', tend: 4e4, rtol: 1e-10, atol: 1e-22, nonNegative: true });
  const formed = rb.events.find((e) => /a bubble forms/.test(e.expr));
  // After it, by hand: x the CO2 share of the bubble, the gases' amounts from what is not dissolved.
  const shareAt = (t) => solve((x) => {
    const nC = 0.01 + 1e-6 * t - KC * x;
    const nN = 1e-4 - KN * (1 - x);
    return x - nC / (nC + nN);
  }, 0, 1);
  const kEnd = rb.t.length - 1;
  const cEnd = mb.toConcentrations(rb.y[kEnd]);
  const xEnd = at(mb, cEnd, 'CO2(g)') / (at(mb, cEnd, 'CO2(g)') + at(mb, cEnd, 'N2(g)'));
  const xHand = shareAt(rb.t[kEnd]);
  let bw = 0;
  for (const y of rb.y) {
    const c = mb.toConcentrations(y);
    const N = at(mb, c, 'CO2(g)') + at(mb, c, 'N2(g)');
    const pc = at(mb, c, 'CO2') / KC;
    const pn = at(mb, c, 'N2') / KN;
    bw = Math.max(bw, N > 0 ? Math.max(Math.abs(Math.log(pc + pn)), Math.abs(at(mb, c, 'CO2(g)') / N - pc / (pc + pn)))
      : Math.max(0, Math.log(pc + pn)));
  }
  check('a fixed pressure: the bubble forms when the water holds CO2 and N2 at 1 atm between them, as the closed form '
    + 'says, and then holds them in the shares the closed form gives', !!formed && Math.abs(formed.t / tForm - 1) < 1e-6
    && Math.abs(xEnd - xHand) < 1e-9 && bw < 1e-12,
  `formed at ${formed ? formed.t.toFixed(3) : '-'} s for ${tForm.toFixed(3)}; CO2 ${(xEnd * 100).toFixed(6)} % of it at the end `
    + `for ${(xHand * 100).toFixed(6)}; every stored point within ${bw.toExponential(1)}`);
  // Made and then used up: the bubble forms, and dissolves again.
  const mb2 = RtmModel.compile(bubble(1e-4, 'X => CO2, k = 1e-3\nCO2 + Y => Z, k = 1e-3'));
  const rb2 = FacsimileODE.runModel(mb2, { solver: 'ndf', tend: 4e4, rtol: 1e-9, atol: 1e-20, nonNegative: true });
  const ev = rb2.events.map((e) => e.expr);
  let k2 = 0;
  while (k2 < rb2.t.length - 1 && rb2.t[k2] < 5e3) k2++;
  const vb = [RtmModel.verifyJacobian(mb2, rb2.t[k2], rb2.y[k2]), RtmModel.verifyJacobian(mb2, 4e4, rb2.y[rb2.y.length - 1])];
  check('  CO2 made and then used up: the bubble forms and dissolves again, and the Jacobian with it there and gone',
    ev.join(', ') === 'a bubble forms, the bubble has dissolved' && vb.every((v) => v.discrepancies.length === 0),
    `${rb2.events.map((e) => `${e.expr} at ${e.t.toFixed(0)} s`).join(', ')}; ${vb[0].checked} and ${vb[1].checked} entries`);

  // Hydrogen from a rate law into a saline water with the electron: the bubble in each cell's speciation.
  const h2 = (act, cells = 1) => `
<SETTINGS>
MODE = ${cells > 1 ? 'transport' : 'batch'}
${cells > 1 ? `CELLS = ${cells}\nLENGTH = 0.01\nDIFFUSION = 1` : ''}
TEND = 2e4
EQUILIBRATE = always
GAS_PRESSURE = 1
${act}

<SPECIES>
H+      1e-7     D=1e-9
OH-     1e-7     D=1e-9
Na+     0.1      D=1e-9
Cl-     0.1      D=1e-9
H2      1e-6     D=1e-9
N2      5e-4     D=1e-9
e-      electron pe=-4
H2(g)   0  gas
N2(g)   0  gas

<EQUILIBRIUM>
H2O <=> H+ + OH-,          logK = -14
2 H+ + 2 e- <=> H2,        logK = -3.15
H2(g) <=> H2,              logK = -3.105
N2(g) <=> N2,              logK = -3.18
${act.includes('sit') ? '\n<SIT>\nNa+ Cl- 0.03\nH+ Cl- 0.12\nNa+ OH- 0.04\nH2 Na+ 0.01\nN2 Na+ 0.02\n' : ''}
<REACTIONS>
=> H2, k = 5e-8
`;
  const lines = ['', 'ACTIVITY = sit'].map((act) => {
    const m = RtmModel.compile(h2(act));
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 2e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
    const lnG = new Float64Array(m.speciesNames.length);
    let worst = 0;
    for (const y of r.y) {
      const c = m.toConcentrations(y);
      if (m.act.kind !== 'none') RtmModel.activityAt(m.act, c, 0, lnG, new Float64Array(m.speciesNames.length));
      const g = (n) => (m.act.kind !== 'none' ? Math.exp(lnG[m.speciesNames.indexOf(n)]) : 1);
      const ph = at(m, c, 'H2') * g('H2') / 10 ** -3.105;
      const pn = at(m, c, 'N2') * g('N2') / 10 ** -3.18;
      const N = at(m, c, 'H2(g)') + at(m, c, 'N2(g)');
      worst = Math.max(worst, N > 0 ? Math.max(Math.abs(Math.log(ph + pn)), Math.abs(at(m, c, 'H2(g)') / N - ph / (ph + pn)))
        : Math.max(0, Math.log(ph + pn)));
    }
    const v = [RtmModel.verifyJacobian(m, 0, m.initialState()), RtmModel.verifyJacobian(m, 2e4, r.y[r.y.length - 1])];
    return { act: act || 'no activity model', worst, events: r.events.map((e) => e.expr), v };
  });
  const hcol = RtmModel.compile(h2('ACTIVITY = sit', 3));
  const rcol = FacsimileODE.runModel(hcol, { solver: 'ndf', tend: 2e4, rtol: 1e-8, atol: 1e-20, nonNegative: true });
  const vcol = RtmModel.verifyJacobian(hcol, 2e4, rcol.y[rcol.y.length - 1]);
  check('the electron and a bubble: hydrogen from a rate law forms one, every stored point on it, each cell speciated '
    + 'in its components, with no activity model and under SIT, and in a column of three cells',
  lines.every((l) => l.worst < 1e-12 && l.events.join() === 'a bubble forms' && l.v.every((v) => v.discrepancies.length === 0))
    && rcol.events.length === 3 && vcol.discrepancies.length === 0,
  `${lines.map((l) => `${l.act}: ${l.worst.toExponential(1)}, ${l.v[0].checked} and ${l.v[1].checked} entries`).join('; ')}; `
    + `the column ${vcol.checked} entries`);

  // The texts it refuses.
  const refuse = (t) => { try { RtmModel.compile(t); return ''; } catch (e) { return e.message; } };
  const B1 = bubble(1e-4, '');
  const cases = [
    ['a gas with neither volume nor pressure', B1.replace('GAS_PRESSURE = 1\n', ''), /give the gas phase GAS_VOLUME/],
    ['both', B1.replace('GAS_PRESSURE = 1', 'GAS_PRESSURE = 1\nGAS_VOLUME = 1'), /both given/],
    ['a gas in no relation', B1.replace('N2(g) <=> N2,    logK = -3.18\n', ''), /N2\(g\) is a gas and in no relation/],
    ['two gases in one relation', B1.replace('N2(g) <=> N2,    logK = -3.18', 'N2(g) <=> N2,    logK = -3.18\nN2(g) <=> CO2(g), logK = 0'),
      /two gases in it/],
    ['a gas in two relations at a fixed pressure', B1.replace('N2(g) <=> N2,    logK = -3.18',
      'N2(g) <=> N2,    logK = -3.18\nN2(g) + X <=> Z, logK = 1'), /in two relations/],
    ['a kf on a bubble\'s relation', B1.replace('logK = -3.18', 'logK = -3.18, kf = 1e3'), /takes no kf/],
    ['a gas that moves', B1.replace('N2(g)   0  gas', 'N2(g)   0  gas  D=1e-9'), /takes no D/],
    ['a charge on a gas', B1.replace('N2(g)   0  gas', 'N2(g)   0  gas  z=1'), /takes no z, a or b/],
  ];
  const wrong = cases.filter(([, t, re]) => !re.test(refuse(t)));
  check(`refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, t]) => `${what}: "${refuse(t)}"`).join(' | '));
  // Real gases: Peng and Robinson's equation, in a fixed volume and in a bubble.
  const real = (fixed) => `
<SETTINGS>
MODE = batch
TEND = 1e5
EQUILIBRATE = always
${fixed}

<SPECIES>
CO2     0.6
N2      0.02
X       0.5
CO2(g)  0  gas  Tc=304.2  Pc=72.86  omega=0.225
N2(g)   0  gas  Tc=126.2  Pc=33.5   omega=0.039

<EQUILIBRIUM>
CO2(g) <=> CO2,  logK = -1.468
N2(g) <=> N2,    logK = -3.18

<GAS_PAIRS>
CO2(g)  N2(g)  -0.02

<REACTIONS>
X => CO2, k = 1e-5
`;
  const rl = ['GAS_VOLUME = 0.2', 'GAS_PRESSURE = 10'].map((fixed) => {
    const m = RtmModel.compile(real(fixed));
    const r = FacsimileODE.runModel(m, { solver: 'ndf', tend: 1e5, rtol: 1e-9, atol: 1e-20, nonNegative: true });
    const v = [RtmModel.verifyJacobian(m, 0, m.initialState()), RtmModel.verifyJacobian(m, 1e5, r.y[r.y.length - 1])];
    const c = m.toConcentrations(r.y[r.y.length - 1]);
    // The relations in fugacity at the end: phi from the equation at the run's own composition.
    const gas = m.act.gas;
    const n = [at(m, c, 'CO2(g)'), at(m, c, 'N2(g)')];
    const N = n[0] + n[1];
    const x = Float64Array.of(n[0] / N, n[1] / N);
    const st = RtmModel.prState(gas.pr, x, gas.fixed === 'pressure' ? gas.pressure : 0, gas.fixed === 'volume' ? gas.volume / N : 0);
    const off2 = Math.max(Math.abs(Math.log(at(m, c, 'CO2')) - Math.log(10 ** -1.468 * Math.exp(gas.pr.lnPhi[0]) * x[0] * st.P)),
      Math.abs(Math.log(at(m, c, 'N2')) - Math.log(10 ** -3.18 * Math.exp(gas.pr.lnPhi[1]) * x[1] * st.P)));
    return { fixed, v, off2, P: st.P, phi: Math.exp(gas.pr.lnPhi[0]), events: r.events.map((e) => e.expr) };
  });
  check('real gases (Tc, Pc, omega, <GAS_PAIRS>): each relation holds in fugacity, phi from Peng and Robinson\'s '
    + 'equation, in a fixed volume and in a bubble at 10 atm; and the Jacobian, phi read through every gas',
  rl.every((l) => l.off2 < 1e-10 && l.v.every((v) => v.discrepancies.length === 0)),
  rl.map((l) => `${l.fixed}: ${l.off2.toExponential(1)} in ln f, P ${l.P.toFixed(3)} atm, phi(CO2) ${l.phi.toFixed(5)}, `
    + `${l.v[0].checked} and ${l.v[1].checked} entries${l.events.length ? `, ${l.events.join(', ')}` : ''}`).join('; '));
  const RF = real('GAS_VOLUME = 0.2');
  const rcases = [
    ['real and ideal gases in one phase', RF.replace('N2(g)   0  gas  Tc=126.2  Pc=33.5   omega=0.039', 'N2(g)   0  gas'),
      /all real gases, held by Peng and Robinson's equation, or all ideal/],
    ['Tc without Pc', RF.replace('Tc=126.2  Pc=33.5', 'Tc=126.2'), /Tc without Pc/],
    ['a critical constant on a species that is no gas', RF.replace('X       0.5', 'X       0.5  Tc=300'), /a real gas's/],
    ['a pair of a species that is no gas', RF.replace('CO2(g)  N2(g)  -0.02', 'CO2(g)  X  -0.02'), /"X" in <GAS_PAIRS> is not a gas/],
    ['a pair given twice', RF.replace('CO2(g)  N2(g)  -0.02', 'CO2(g)  N2(g)  -0.02\nN2(g)  CO2(g)  0'), /paired twice/],
    ['pairs for ideal gases', RF.replace(/  Tc=\S+  Pc=\S+\s+omega=\S+/g, ''), /no gas is given Tc and Pc/],
    ['PRESSURE other than a bubble\'s', real('GAS_PRESSURE = 10\nPRESSURE = 3'), /a bubble at a fixed pressure puts the water at its own/],
  ];
  const rwrong = rcases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${rcases.map((c) => c[0]).join('; ')}`, !rwrong.length,
    rwrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
  const noGas = RtmModel.compile(vol.replace('CO2(g)  0      gas\n', '').replace('CO2(g) <=> CO2,             logK = -1.468\n', ''));
  check('  and GAS_VOLUME with no gas is said to do nothing; TEMPERATURE with a gas and no ACTIVITY is not',
    noGas.warnings.some((x) => /GAS_VOLUME is a gas phase's, and no species is a gas/.test(x))
    && !RtmModel.compile(vol.replace('GAS_VOLUME = 0.5', 'GAS_VOLUME = 0.5\nTEMPERATURE = 15')).warnings
      .some((x) => /TEMPERATURE sets/.test(x)));
}

/* ======================================================================
   2r. The temperature (dH, analytic, TEMPERATURE that varies, TK and TC)

   A relation's log K at a temperature as PHREEQC's k_calc has it: van 't
   Hoff's equation from dH, or the analytic expression, which replaces logK
   and dH. TEMPERATURE a number; a parameter, a temperature that differs
   from cell to cell, where each cell must be exactly the one-cell model at
   its own temperature, whatever the chemistry; a table read at the clock,
   where a closed batch must be at every stored point where a model at that
   temperature puts it. A mineral that replaces another as the water heats
   -- gypsum and anhydrite -- at the temperature the closed form gives;
   rate laws reading TK and TC; a phase's saturation; fast pairs; and the
   texts it refuses.
   ====================================================================== */
console.log('\n--- the temperature ---');
{
  const Rk = 0.00831470;
  const vh = (logK, dH, T) => logK - dH * (298.15 - T) / (Math.LN10 * Rk * T * 298.15);
  const an = (a, T) => a[0] + a[1] * T + a[2] / T + a[3] * Math.log10(T) + a[4] / (T * T) + a[5] * T * T;
  const W = [-283.971, -0.05069842, 13323.0, 102.24447, -1119669.0, 0];
  const one = (T, rel) => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = start\nTEMPERATURE = ${T}\n\n`
    + `<SPECIES>\nA 1\nB 0\nH+ 1e-7\nOH- 1e-7\n\n<EQUILIBRIUM>\n${rel}\n`);
  const at50 = one(50, 'A <=> B, logK = 0.3, dH = 20\n <=> H+ + OH-, logK = -14, dH = 55.8, analytic = '
    + W.slice(0, 5).join(' '));
  const y50 = at50.initialState();
  const lkB = Math.log10(y50[1] / y50[0]);
  const lkW = Math.log10(y50[2] * y50[3]);
  check('a relation\'s log K at TEMPERATURE: van \'t Hoff\'s from dH, and the analytic expression, which replaces '
    + 'logK and dH as PHREEQC has it', Math.abs(lkB - vh(0.3, 20, 323.15)) < 1e-12 && Math.abs(lkW - an(W, 323.15)) < 1e-12,
  `log K ${lkB.toFixed(12)} and ${lkW.toFixed(12)} at 50 C, for ${vh(0.3, 20, 323.15).toFixed(12)} and ${an(W, 323.15).toFixed(12)}`);
  const at25 = one(25, 'A <=> B, K = 2, dH = 20\n <=> H+ + OH-, logK = -14');
  check('  at 25 C, logK or K as written, dH or not',
    Math.abs(at25.equilibria[0].lnK - Math.log(2)) < 1e-15 && at25.equilibria[1].lnK === -14 * Math.LN10);

  // A heated batch: A <=> B from 10 to 80 C and back to 40 along a table read at the clock.
  const heat = '<TABLE heat>\n0 10\n0.5 80\n1 40\n';
  const Tof = (t) => 273.15 + (t <= 0.5 ? 10 + 140 * t : 80 - 80 * (t - 0.5));
  const mh = RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\nTEMPERATURE = heat(t)\n\n${heat}\n`
    + '<SPECIES>\nA 1\nB 0\n\n<EQUILIBRIUM>\nA <=> B, logK = 0.3, dH = 20\n');
  const rh = run(mh, { tend: 1 });
  let wh = 0;
  for (let k = 0; k < rh.t.length; k++) {
    const c = mh.toConcentrations(rh.y[k], rh.t[k]);
    wh = Math.max(wh, Math.abs(Math.log10(c[1] / c[0]) - vh(0.3, 20, Tof(rh.t[k]))));
  }
  const tAt = mh.temperatures(0.25);
  check('TEMPERATURE = heat(t), a table read at the clock: K at every stored point the one at its time, the run started '
    + 'again where the table turns, and the Jacobian', wh < 1e-13 && mh.breaks(0, 1).join(',') === '0.5'
    && Math.abs(tAt[0] - 45) < 1e-12 && mh.temperature.clock && !mh.temperature.cells
    && RtmModel.verifyJacobian(mh, rh.t[rh.t.length >> 1], rh.y[rh.y.length >> 1]).discrepancies.length === 0,
  `${rh.t.length} points, worst ${wh.toExponential(1)} in log K`);

  /*
    EACH CELL ITS OWN TEMPERATURE, AND EACH TIME ITS OWN: in a column where
    nothing moves, cell i must be the one-cell model at its temperature to the
    last bit, and in a closed batch heated along a table every stored state
    the one a model at that time's temperature starts from -- the
    relations' log K, the Debye-Hueckel A and B, an exchanger, a double
    layer's constant, a gas's R T in a fixed volume, Peng and Robinson's
    terms, the electron's held form and SIT's.
  */
  const temps = [5, 25, 60, 95];
  const chem = [
    ['ACTIVITY = debye-huckel', 'Na+ 1e-3 a=4.08 b=0.082\nCa+2 2e-4 a=5 b=0.165\nCl- 1.4e-3 a=3.63 b=0.017\nX- exchanger\n'
      + 'NaX exchange 1e-3\nCaX2 exchange 0', 'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8, dH = 7.2', '',
    'an exchanger'],
    ['ACTIVITY = davies', 'H+ 1e-7 fixed\nNa+ 0.1\nCl- 0.1\nS_psi potential area=600 grams=0.09\nS_OH surface sites=2e-4\n'
      + 'S_OH2+ surface', 'S_OH + H+ <=> S_OH2+, logK = 7.29, dH = -20', '', 'a double layer'],
    ['GAS_VOLUME = 0.5', 'H+ 1e-4\nOH- 1e-10\nCO2 1e-3\nHCO3- 1e-6\nCO2(g) 0 gas', ' <=> H+ + OH-, logK = -14, dH = 55.8\n'
      + 'CO2 <=> H+ + HCO3-, logK = -6.35, dH = 9.1\nCO2(g) <=> CO2, logK = -1.468, dH = -19.98', '', 'a gas in a fixed volume'],
    ['GAS_VOLUME = 0.05', 'H+ 1e-4\nOH- 1e-10\nCO2 0.3\nHCO3- 1e-6\nCO2(g) 0.5 gas Tc=304.2 Pc=72.86 omega=0.225',
      ' <=> H+ + OH-, logK = -14, dH = 55.8\nCO2 <=> H+ + HCO3-, logK = -6.35, dH = 9.1\nCO2(g) <=> CO2, logK = -1.468, '
      + 'dH = -19.98', '', 'a real gas in one'],
    ['GAS_PRESSURE = 10', 'CO2 0.5\nN2 0.05\nCO2(g) 0.1 gas Tc=304.2 Pc=72.86 omega=0.225\nN2(g) 0.1 gas Tc=126.2 Pc=33.5 '
      + 'omega=0.039', 'CO2(g) <=> CO2, logK = -1.468, dH = -19.98\nN2(g) <=> N2, logK = -3.18, dH = -10.4', '',
    'a bubble of real gases'],
    ['ACTIVITY = davies', 'Fe+2 1e-3\nFe+3 1e-5\nCl- 2.03e-3\nH+ 1e-5\nOH- 1e-9\nFeOH+2 0\ne- electron',
      'Fe+2 <=> Fe+3 + e-, logK = -13.02, dH = 40.5\n <=> H+ + OH-, logK = -14, dH = 55.8\nFe+3 <=> FeOH+2 + H+, logK = -2.19, '
      + 'dH = 43.5', '', 'the electron'],
    ['ACTIVITY = sit', 'Na+ 1\nCl- 1\nH+ 1e-7\nOH- 1e-7\nNaCl 0', ' <=> H+ + OH-, logK = -14, dH = 55.8\n'
      + 'Na+ + Cl- <=> NaCl, logK = -0.5, dH = 5', '<SIT>\nNa+ Cl- 0.03\nH+ Cl- 0.12\nNa+ OH- 0.04\n', 'SIT'],
    ['ACTIVITY = davies', 'Ca+2 1e-3\nCO3-2 1e-3\nHCO3- 0\nH+ 1e-8\nOH- 1e-6\nCalcite 0.01 mineral',
      ' <=> H+ + OH-, logK = -14, dH = 55.8\nCO3-2 + H+ <=> HCO3-, logK = 10.329, dH = -14.9\n'
      + 'Calcite <=> Ca+2 + CO3-2, logK = -8.48, dH = -9.6', '', 'a mineral'],
    ['ACTIVITY = davies\nPRESSURE = 500', 'Ca+2 1e-3\nCO3-2 1e-3\nHCO3- 0\nH+ 1e-8\nOH- 1e-6\nCalcite 0.01 mineral',
      ' <=> H+ + OH-, logK = -14, dH = 55.8\nCO3-2 + H+ <=> HCO3-, logK = 10.329, dH = -14.9\n'
      + 'Calcite <=> Ca+2 + CO3-2, logK = -8.48, dH = -9.6', '<VOLUMES>\nCa+2  -0.35 -7.3 6.1 -2.5 1.2 5 1.6 -57 -6e-3 1\n'
      + 'CO3-2  6 0 0 -5.7 6.9 0 1.4 106 -0.034 1\nHCO3-  8.5 0 -11.7 0 1.6 0 0 116 0 1\nCalcite  36.9\n',
    'molar volumes at 500 atm'],
  ];
  const text = (head, T, more, [s, sp, rel, extra]) => `<SETTINGS>\n${head}\nTEND = 1\nEQUILIBRATE = always\n${s}\n`
    + `TEMPERATURE = ${T}\n\n${more}\n<SPECIES>\n${sp}\n\n<EQUILIBRIUM>\n${rel}\n\n${extra}`;
  const column = 'MODE = transport\nCELLS = 4\nLENGTH = 1\nDIFFUSION = 0\nLEFT = neumann\nRIGHT = neumann';
  const profile = `<PARAMETERS>\nTc all ${temps[0]}\n${temps.slice(1).map((v, i) => `Tc ${i + 1} ${v}`).join('\n')}\n`;
  const differ = (a, b) => {
    let w = 0;
    for (let s = 0; s < b.length; s++) {
      if (Math.abs(a[s]) < 1e-25 && Math.abs(b[s]) < 1e-25) continue;
      w = Math.max(w, Math.abs(a[s] - b[s]) / Math.max(Math.abs(b[s]), 1e-30));
    }
    return w;
  };
  const cellWorst = [];
  const timeWorst = [];
  for (const c of chem) {
    const prof = RtmModel.compile(text(column, 'Tc', profile, c));
    const cp = prof.toConcentrations(prof.initialState());
    const ns = prof.speciesNames.length;
    let w = 0;
    temps.forEach((T, i) => {
      const m1 = RtmModel.compile(text('MODE = batch', T, '', c));
      w = Math.max(w, differ(cp.subarray(i * ns, (i + 1) * ns), m1.toConcentrations(m1.initialState())));
    });
    cellWorst.push(`${c[4]} ${w.toExponential(0)}`);
    if (w > 1e-14) cellWorst.push('FAIL');
    const mt = RtmModel.compile(text('MODE = batch', 'heat(t)', heat, c));
    const rt = FacsimileODE.runModel(mt, { solver: 'ndf', tend: 1, rtol: 1e-9, atol: 1e-20 });
    let wt = 0;
    for (const k of [rt.t.length >> 2, rt.t.length >> 1, (3 * rt.t.length) >> 2, rt.t.length - 1]) {
      const m1 = RtmModel.compile(text('MODE = batch', Tof(rt.t[k]) - 273.15, '', c));
      wt = Math.max(wt, differ(mt.toConcentrations(rt.y[k], rt.t[k]), m1.toConcentrations(m1.initialState())));
    }
    timeWorst.push(`${c[4]} ${wt.toExponential(0)}`);
    if (wt > 1e-13) timeWorst.push('FAIL');
  }
  check('TEMPERATURE = Tc, a parameter: each cell of a column the one-cell model at its own temperature, chemistry by '
    + 'chemistry', !cellWorst.includes('FAIL'), cellWorst.join(', '));
  check('  and heated along a table: each stored state the start of a model at that time\'s temperature',
    !timeWorst.includes('FAIL'), timeWorst.join(', '));

  /*
    ONE MINERAL OVER TO ANOTHER, as gypsum goes over to anhydrite as a water
    heats: P1 and P2 the same solid, P2 the less soluble at 25 C and P1 above
    the temperature where their log K cross. Each is held while it is there;
    when the water becomes supersaturated in P1, P2 cannot be there beside
    it, and goes. The time is where log K1 = log K2 along the table, and the
    water is at the stable one's solubility, sqrt K, before and after.
  */
  const poly = (start) => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n`
    + `TEMPERATURE = warm(t)\n\n<TABLE warm>\n0 25\n1 75\n\n<SPECIES>\nA 1e-3\nB 1e-3\n${start}\n\n<EQUILIBRIUM>\n`
    + 'P1 <=> A + B, logK = -2, dH = 5\nP2 <=> A + B, logK = -2.3, dH = 40\n');
  let lo = 280;
  let hi = 400;
  for (let i = 0; i < 200; i++) { const mid = (lo + hi) / 2; if (vh(-2, 5, mid) > vh(-2.3, 40, mid)) lo = mid; else hi = mid; }
  const tCross = ((lo + hi) / 2 - 298.15) / 50;
  const mp = poly('P1 0.5 mineral\nP2 0 mineral');
  const y0 = mp.toConcentrations(mp.initialState());
  const rp = run(mp, { tend: 1 });
  const ev = rp.events[0] || {};
  const yEnd = mp.toConcentrations(rp.y[rp.y.length - 1], 1);
  const both = poly('P1 0.25 mineral\nP2 0.25 mineral');
  const yb = both.toConcentrations(both.initialState());
  check('one mineral over to another as the water heats: P2, stable at the start, goes over to P1 where their log K '
    + 'cross along the table', rp.events.length === 1 && Math.abs(ev.t - tCross) < 1e-8
    && /P1 precipitates, and P2 has dissolved away/.test(ev.expr)
    && Math.abs(y0[0] - Math.sqrt(10 ** -2.3)) < 1e-14 && y0[2] === 0 && Math.abs(y0[3] - 0.5 + y0[0] - 1e-3) < 1e-14
    && Math.abs(yEnd[0] / Math.sqrt(10 ** vh(-2, 5, 348.15)) - 1) < 1e-12 && yEnd[3] === 0
    && Math.abs(yb[3] - y0[3]) < 1e-14 && yb[2] === 0,
  `at t = ${ev.t} for ${tCross.toFixed(10)} (${(25 + 50 * tCross).toFixed(4)} C): "${ev.expr}"; both given, P1 goes over to P2`);

  // Rate laws: Arrhenius on TK cell by cell, TC along the clock, and a phase's saturation with its dH.
  const col3 = (more, sp, body) => RtmModel.compile(`<SETTINGS>\n${column.replace('CELLS = 4', 'CELLS = 3')}\nTEND = 1\n`
    + `TEMPERATURE = Tc\n\n<PARAMETERS>\nTc all 10 + 35*i\n\n${more}\n<SPECIES>\n${sp}\n\n${body}\n`);
  const arr = col3('', 'A 1\nB 0', '<REACTIONS>\nA => B, r = k25*exp(-Ea/Rg*(1/TK - 1/298.15))*[A], k25 = 0.05, Ea = 60000, '
    + 'Rg = 8.314\n');
  const ya = last(run(arr, { tend: 1, rtol: 1e-11 }));
  const kOf = (T) => 0.05 * Math.exp((-60000 / 8.314) * (1 / T - 1 / 298.15));
  const wa = Math.max(...[0, 1, 2].map((i) => Math.abs(ya[2 * i] / Math.exp(-kOf(283.15 + 35 * i)) - 1)));
  const tcm = RtmModel.compile('<SETTINGS>\nMODE = batch\nTEND = 1\nTEMPERATURE = ramp(t)\n\n<TABLE ramp>\n0 10\n1 90\n\n'
    + '<SPECIES>\nA 1\n\n<REACTIONS>\nA => , r = 0.01*TC*[A]\n');
  const wc = Math.abs(last(run(tcm, { tend: 1, rtol: 1e-11 }))[0] / Math.exp(-0.01 * 50) - 1);
  const sim = col3('<PHASES>\nCalcite <=> Ca+2 + CO3-2, logK = -8.48, dH = -9.6\n', 'Ca+2 1e-3 fixed\nCO3-2 1e-5 fixed\nX 0',
    '<REACTIONS>\n=> X, r = SI(Calcite)\n');
  const ys = last(run(sim, { tend: 1 }));
  const ws = Math.max(...[0, 1, 2].map((i) => Math.abs(ys[3 * i + 2] - (-8 - vh(-8.48, -9.6, 283.15 + 35 * i)))));
  check('rate laws read the cell\'s temperature as TK and TC, and a phase\'s saturation its log K there',
    wa < 1e-8 && wc < 1e-8 && ws < 1e-13, `Arrhenius ${wa.toExponential(1)}, TC along the clock ${wc.toExponential(1)}, `
      + `SI ${ws.toExponential(1)}`);

  // Fast pairs: kb = kf/K at the cell's temperature, with and without ACTIVITY, and along the clock.
  const pair = (a) => RtmModel.compile(`<SETTINGS>\n${column.replace('CELLS = 4', 'CELLS = 3')}\nTEND = 1\nACTIVITY = ${a}\n`
    + 'TEMPERATURE = Tc\n\n<PARAMETERS>\nTc all 10 + 35*i\n\n<SPECIES>\nA 1\nB 0\n\n<EQUILIBRIUM>\n'
    + 'A <=> B, logK = 0.3, dH = 20, kf = 100\n');
  const pw = ['none', 'davies'].map((a) => {
    const m = pair(a);
    const r = run(m, { tend: 1 });
    const y = last(r);
    return Math.max(...[0, 1, 2].map((i) => Math.abs(Math.log10(y[2 * i + 1] / y[2 * i]) - vh(0.3, 20, 283.15 + 35 * i))))
      + (RtmModel.verifyJacobian(m, 0.5, r.y[r.y.length >> 1]).discrepancies.length ? 1 : 0);
  });
  const clockPair = RtmModel.compile('<SETTINGS>\nMODE = batch\nTEND = 1\nTEMPERATURE = ramp(t)\n\n<TABLE ramp>\n0 10\n1 90\n\n'
    + '<SPECIES>\nA 1\nB 0\n\n<EQUILIBRIUM>\nA <=> B, logK = 0.3, dH = 20, kf = 1e6\n');
  const rcp = run(clockPair, { tend: 1 });
  let wcp = 0;
  for (let k = 0; k < rcp.t.length; k++) {
    if (rcp.t[k] < 1e-3) continue;
    wcp = Math.max(wcp, Math.abs(Math.log10(rcp.y[k][1] / rcp.y[k][0]) - vh(0.3, 20, 283.15 + 80 * rcp.t[k])));
  }
  check('  a fast pair\'s kb = kf/K at the cell\'s temperature, without ACTIVITY and with, and one that follows the clock',
    pw[0] < 1e-14 && pw[1] < 1e-14 && wcp < 1e-5, `${pw.map((v) => v.toExponential(1)).join(', ')} in log K; `
      + `along the clock within ${wcp.toExponential(1)}, a pair with kf = 1e6 lagging its K`);

  // What it refuses.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const base = (T, rel = 'A <=> B, logK = 0.3, dH = 20') => `<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n`
    + `TEMPERATURE = ${T}\n\n<TABLE warm>\n0 25\n1 75\n\n<PARAMETERS>\nT0 all 400\n\n<SPECIES>\nA 1\nB 0\n\n<EQUILIBRIUM>\n${rel}\n`;
  const cases = [
    ['dH with no logK', base(25, 'A <=> B, dH = 20'), /give logK = \.\.\. as well/],
    ['seven terms', base(25, 'A <=> B, analytic = 1 2 3 4 5 6 7'), /at most six/],
    ['no log K at all', base(25, 'A <=> B, analytic = 0 0'), /needs K = \.\.\., logK = \.\.\. or analytic/],
    ['a name that is not a parameter', base('Tx + 1'), /"Tx" in TEMPERATURE is not a parameter/],
    ['a table read at a place', base('warm(x)'), /in TEMPERATURE is read at a time/],
    ['a cell outside 0 to 350 C', base('T0'), /TEMPERATURE comes to 400 C/],
    ['a number outside it', base(400), /0 to 350 C/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
}

/*
   SOLID SOLUTIONS, against what holds them. MA and MB the end members of
   MAB, dissolving to A + X and B + X: where the solid is there, each
   relation holds the water at the member's activity in it, its mole
   fraction times Guggenheim's lambda, or inside a miscibility gap the
   activity the gap's edge gives it, and the totals are what they were.
   The gap is where the two members' activities are the same at two
   compositions, PHREEQC's tolerance 1e-6, and for a regular solution (a1 =
   0) where ln((1 - x)/x) = a0 (1 - 2x). A solid that forms does so where
   the water first holds it at saturation: for an ideal one where
   IAP_A/K_A + IAP_B/K_B comes to 1, a time the source of X gives in closed
   form; a0 goes as 1/T, so a0 at 25 C is a0 (T/298.15) at T.
*/
console.log('\n--- solid solutions ---');
{
  const lam = (a0, a1, xb) => {
    const xc = 1 - xb;
    return [xb * xb * (a0 - a1 * (3 - 4 * xb)), xc * xc * (a0 + a1 * (4 * xb - 1))];
  };
  const ssText = (o) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1}\nEQUILIBRATE = always\n${o.settings || ''}\n`
    + `<SPECIES>\nA  ${o.a}\nB  ${o.b}\nX  ${o.x || 2e-3}\nMA ${o.ma} mineral\nMB ${o.mb} mineral\n${o.sp || ''}\n`
    + `<EQUILIBRIUM>\nMA <=> A + X, logK = -6\nMB <=> B + X, logK = -7\n${o.rel || ''}\n`
    + `<SOLID_SOLUTIONS>\nMAB  MA  MB  ${o.prm || ''}\n${o.more || ''}`;
  const ssModel = (o) => RtmModel.compile(ssText(o));
  const defOf = (m) => m.equilibria.find((eq) => eq.grp && eq.grp.kind === 'ss').grp;
  // ln of each member's activity in the solid: x lambda, or inside the gap the gap's edge's.
  const lnAct = (a0, a1, gap, xb) => {
    if (gap && xb > gap.xb1 && xb < gap.xb2) return [gap.lnAc, gap.lnAb];
    const [lc, lb] = lam(a0, a1, xb);
    return [Math.log(1 - xb) + lc, Math.log(xb) + lb];
  };
  // How far the water is from the solid: ln(A X/K_A) less ln a_A, and the same for B, the larger.
  const off = (c, a0, a1, gap) => {
    const [A, B, X, nA, nB] = c;
    const [la, lb] = lnAct(a0, a1, gap, nB / (nA + nB));
    return Math.max(Math.abs(Math.log(A * X) + 6 * Math.LN10 - la), Math.abs(Math.log(B * X) + 7 * Math.LN10 - lb));
  };
  /*
    The most any composition of the solid is supersaturated by: the largest
    sum x_q ln(IAP_q/(K_q a_q(x))) over x, on a grid and then, about its best
    point, by ternary search, which finds the top where there is no gap and
    the function is concave.
  */
  const drive = (c, a0, a1) => {
    const [A, B, X] = c;
    const f = (xb) => {
      const [lc, lb] = lam(a0, a1, xb);
      return (1 - xb) * (Math.log(A * X) + 6 * Math.LN10 - Math.log(1 - xb) - lc)
        + xb * (Math.log(B * X) + 7 * Math.LN10 - Math.log(xb) - lb);
    };
    let at = 1;
    for (let i = 2; i < 2000; i++) if (f(i / 2000) > f(at / 2000)) at = i;
    let lo = (at - 1) / 2000 || 1e-12;
    let hi = Math.min((at + 1) / 2000, 1 - 1e-12);
    for (let i = 0; i < 200; i++) {
      const m1 = lo + (hi - lo) / 3;
      const m2 = hi - (hi - lo) / 3;
      if (f(m1) < f(m2)) lo = m1; else hi = m2;
    }
    return f((lo + hi) / 2);
  };

  // 1. The start, ideal, binary and binary with a gap.
  const sets = [['', 0, 0], ['a0=1.5 a1=0.3', 1.5, 0.3], ['a0=3.43 a1=-1.82', 3.43, -1.82]];
  const starts = [[1e-3, 1e-3, 1e-3, 1e-3], [1e-3, 1e-4, 1e-3, 0], [1e-3, 2e-3, 1e-4, 1e-3], [1e-4, 3e-3, 0, 1e-3],
    [1e-9, 1e-9, 0, 0]];
  let worstRel = 0;
  let worstTot = 0;
  let inGap = 0;
  let absent = 0;
  let worstDrive = -Infinity;
  for (const [prm, a0, a1] of sets) {
    for (const [a, b, ma, mb] of starts) {
      const m = ssModel({ a, b, ma, mb, prm });
      const gap = a0 || a1 ? RtmModel.binaryAt(defOf(m), 298.15).gap : null;
      const c = m.toConcentrations(m.initialState());
      const [A, B, X, nA, nB] = c;
      worstTot = Math.max(worstTot, Math.abs(A + nA - a - ma) / (a + ma), Math.abs(B + nB - b - mb) / (b + mb),
        Math.abs(X + nA + nB - 2e-3 - ma - mb) / (2e-3 + ma + mb));
      if (nA + nB > 0) {
        worstRel = Math.max(worstRel, off(c, a0, a1, gap));
        const xb = nB / (nA + nB);
        if (gap && xb > gap.xb1 && xb < gap.xb2) inGap++;
      } else {
        absent++;
        worstDrive = Math.max(worstDrive, drive(c, a0, a1));
      }
    }
  }
  check('a solid solution at the start, ideal, binary, and binary with a miscibility gap: each relation holds the water '
    + 'at the member\'s x lambda, or the gap\'s edge\'s, and the totals stay', worstRel < 1e-12 && worstTot < 1e-14
    && inGap >= 1 && absent === 3 && worstDrive < 0,
  `relations within ${worstRel.toExponential(1)} in ln, totals ${worstTot.toExponential(1)}; ${inGap} start(s) inside the `
    + `gap; ${absent} with none of it, no composition supersaturated (best ${worstDrive.toFixed(2)})`);

  // 2. The gap: equal activities at its two compositions, the spinodal between, and the regular solution's.
  const mGap = ssModel({ a: 1e-3, b: 1e-3, ma: 0, mb: 0, prm: 'a0=3.43 a1=-1.82' });
  const g = RtmModel.binaryAt(defOf(mGap), 298.15).gap;
  const actAt = (a0, a1, xb) => { const [lc, lb] = lam(a0, a1, xb); return [(1 - xb) * Math.exp(lc), xb * Math.exp(lb)]; };
  const [c1, b1] = actAt(3.43, -1.82, g.xb1);
  const [c2, b2] = actAt(3.43, -1.82, g.xb2);
  // d2(G/RT)/dxb2 of PHREEQC's Guggenheim solid: zero at the spinodal, below it between.
  const g2 = (a0, a1, u) => 1 / (u * (1 - u)) + 2 * (3 * a1 - a0) - 12 * a1 * u;
  const spin = Math.max(...[g.xsm1, g.xsm2].map((u) => Math.abs(g2(3.43, -1.82, u) * u * (1 - u))));
  const regular = (a0) => {
    // ln((1 - x)/x) = a0 (1 - 2x) on (0, 1/2), by bisection
    let lo = 1e-12;
    let hi = 0.5 - 1e-12;
    for (let i = 0; i < 200; i++) {
      const mid = (lo + hi) / 2;
      if (Math.log((1 - mid) / mid) - a0 * (1 - 2 * mid) > 0) lo = mid; else hi = mid;
    }
    return (lo + hi) / 2;
  };
  const reg = (a0) => RtmModel.binaryAt(defOf(ssModel({ a: 1e-3, b: 1e-3, ma: 0, mb: 0, prm: `a0=${a0}` })), 298.15).gap;
  const r25 = reg(2.5);
  const xr = regular(2.5);
  check('  its miscibility gap: the two compositions where the members\' activities are the same, the spinodal '
    + 'between them, and for a1 = 0 the regular solution\'s, none at a0 = 1.9 below PHREEQC\'s critical 2',
  Math.abs(c1 - c2) < 1e-6 && Math.abs(b1 - b2) < 1e-6 && g.xb1 < g.xsm1 && g.xsm1 < g.xsm2 && g.xsm2 < g.xb2
    && spin < 1e-4 && g2(3.43, -1.82, (g.xsm1 + g.xsm2) / 2) < 0
    && Math.abs(r25.xb1 - xr) < 1e-6 && Math.abs(r25.xb2 - (1 - xr)) < 1e-6 && reg(1.9) === null && reg(2.05) !== null,
  `xSr ${g.xb1.toFixed(6)} to ${g.xb2.toFixed(6)}, activities the same to ${Math.max(Math.abs(c1 - c2), Math.abs(b1 - b2))
    .toExponential(1)}, spinodal ${g.xsm1.toFixed(4)} to ${g.xsm2.toFixed(4)} (${spin.toExponential(1)}); a0 = 2.5: `
    + `${r25.xb1.toFixed(8)} for ${xr.toFixed(8)}`);

  // 3. Forming where the water first holds it at saturation: X comes in at 1e-3 a unit of time.
  const forms = [['', 1, 0], ['a0=1.5', Math.exp(1.5 / 4), 1.5]].map(([prm, lambda, a0]) => {
    const m = ssModel({ a: 1e-4, b: 1e-5, x: 1e-3, ma: 0, mb: 0, prm, tend: 30, more: '\n<REACTIONS>\n=> X, k = 1e-3\n' });
    const r = run(m, { tend: 30 });
    const e = r.events[0] || { t: NaN, expr: '' };
    // A/K_A = B/K_B, so x = 1/2 and lambda the same for both: 200 X/lambda = 1.
    const want = (lambda / 200 - 1e-3) / 1e-3;
    let worst = 0;
    for (let k = 0; k < r.t.length; k++) {
      if (r.t[k] <= e.t) continue;
      worst = Math.max(worst, off(m.toConcentrations(r.y[k], r.t[k]), a0, 0, null));
    }
    return { by: Math.abs(e.t - want), n: r.events.length, ok: /^the solid solution MAB precipitates/.test(e.expr), worst, t: e.t };
  });
  check('  forming where the water first holds it at saturation, sum IAP/(K lambda) = 1: ideal, and binary, '
    + 'at the time the source gives in closed form', forms.every((f) => f.by < 1e-8 && f.n === 1 && f.ok && f.worst < 1e-9),
  forms.map((f) => `t = ${f.t.toFixed(9)}, within ${f.by.toExponential(1)}, relations after ${f.worst.toExponential(1)}`)
    .join('; '));

  // 4. Through the gap: B comes in, the solid's composition rises into the gap, across it and out above it.
  const mThrough = ssModel({ a: 1e-3, b: 1e-7, ma: 1e-3, mb: 0, prm: 'a0=3.43 a1=-1.82', tend: 60,
    more: '\n<REACTIONS>\n=> B + X, k = 3e-4\n' });
  const rThrough = run(mThrough, { tend: 60, rtol: 1e-9 });
  const ev = rThrough.events;
  let worstT = 0;
  let modes = '';
  for (let k = 0; k < rThrough.t.length; k++) {
    const c = mThrough.toConcentrations(rThrough.y[k], rThrough.t[k]);
    const xb = c[4] / (c[3] + c[4]);
    worstT = Math.max(worstT, off(c, 3.43, -1.82, g));
    const mode = xb >= g.xb2 ? '3' : xb > g.xb1 ? '2' : '1';
    if (mode !== modes[modes.length - 1]) modes += mode;
  }
  const atEv = ev.length === 2 ? run(mThrough, { tend: 60, rtol: 1e-9, outputTimes: [ev[0].t, ev[1].t] }).grid.y
    .map((y, k) => { const c = mThrough.toConcentrations(y, ev[k].t); return c[4] / (c[3] + c[4]); }) : [NaN, NaN];
  check('  through the gap: the run stops where the composition comes to the gap and where it leaves it, each '
    + 'relation held all the way', ev.length === 2 && /MAB comes to its miscibility gap/.test(ev[0].expr)
    && /MAB leaves its miscibility gap/.test(ev[1].expr) && modes === '123' && worstT < 1e-9
    && Math.abs(atEv[0] - g.xb1) < 1e-7 && Math.abs(atEv[1] - g.xb2) < 1e-7,
  `at t = ${ev.map((e) => e.t.toFixed(5)).join(' and ')}, x_B there ${atEv.map((v) => v.toFixed(8)).join(' and ')}; `
    + `branches ${modes}; relations within ${worstT.toExponential(1)}`);

  // 5. Dissolving away: X taken out, the solid goes; after it the water is undersaturated in every composition.
  const mAway = ssModel({ a: 1e-3, b: 1e-4, ma: 1e-4, mb: 1e-5, prm: 'a0=1.5', tend: 30, more: '\n<REACTIONS>\nX => , k = 0.2\n' });
  const rAway = run(mAway, { tend: 30 });
  const ea = rAway.events[0] || { t: NaN, expr: '' };
  let afterZero = true;
  let afterDrive = -Infinity;
  let before = 0;
  for (let k = 0; k < rAway.t.length; k++) {
    const c = mAway.toConcentrations(rAway.y[k], rAway.t[k]);
    if (rAway.t[k] < ea.t) before = Math.max(before, off(c, 1.5, 0, null));
    else if (rAway.t[k] > ea.t) {
      if (c[3] !== 0 || c[4] !== 0) afterZero = false;
      afterDrive = Math.max(afterDrive, drive(c, 1.5, 0));
    }
  }
  const endDrive = drive(mAway.toConcentrations(last(rAway), 30), 1.5, 0);
  check('  dissolving away: the run stops where the last of it goes, both members held at none after it, the water '
    + 'undersaturated in every composition', rAway.events.length === 1
    && /the solid solution MAB has dissolved away/.test(ea.expr) && afterZero && afterDrive < 1e-12 && endDrive < -1
    && before < 1e-9,
  `at t = ${ea.t.toFixed(6)}; relations before within ${before.toExponential(1)}; after it the most any composition `
    + `is supersaturated by ${afterDrive.toExponential(2)}, ${endDrive.toFixed(2)} at the end`);

  /*
    6. Under ACTIVITY, and held in the projected form a model with an
    electron takes: ions, a run through the gap, Davies and SIT; with an
    iron couple tied to the electron beside it, which changes nothing of the
    rest, the run is the same, and the Jacobian is a difference's at the end
    of a run below the gap, inside it and above it.
  */
  const ionic = (act, elec, tend) => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = ${tend}\nEQUILIBRATE = always\n${act}\n\n`
    + '<SPECIES>\nA+ 1e-3\nB+ 1e-7\nX- 2e-3\nNa+ 1e-3\nMA 1e-3 mineral\nMB 0 mineral\nFe+2 1e-4\nFe+3 1e-6\n'
    + `${elec ? 'e- electron\n' : ''}\n<EQUILIBRIUM>\nMA <=> A+ + X-, logK = -6\nMB <=> B+ + X-, logK = -7\n`
    + `${elec ? 'Fe+2 <=> Fe+3 + e-, logK = -13.02\n' : ''}\n<SOLID_SOLUTIONS>\nMAB  MA  MB  a0=3.43 a1=-1.82\n\n`
    + '<REACTIONS>\n=> B+ + X-, k = 3e-4\n');
  const acts = [['', 'none'], ['ACTIVITY = davies', 'Davies'], ['ACTIVITY = sit', 'SIT']];
  const held = acts.map(([act, label]) => {
    let worst = 0;
    let bad = 0;
    let measured = 0;
    let projected = true;
    for (const tend of [0.1, 10, 39]) {
      const ends = [false, true].map((elec) => {
        const m = ionic(act, elec, tend);
        if (elec) projected = projected && !!m.heldEquilibria;
        const r = run(m, { tend });
        const v = RtmModel.verifyJacobian(m, tend, last(r));
        bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
        measured += v.checked;
        return m.toConcentrations(last(r), tend);
      });
      for (let s = 0; s < 8; s++) worst = Math.max(worst, Math.abs(ends[1][s] / ends[0][s] - 1));
    }
    return { label, worst, bad, measured, projected };
  });
  check('  under ACTIVITY, none, Davies and SIT, with an electron and without: the same run, and the Jacobian a '
    + 'difference\'s below the gap, inside it and above it', held.every((h) => h.worst < 1e-8 && h.bad === 0 && h.projected),
  held.map((h) => `${h.label} ${h.worst.toExponential(1)}, ${h.measured} entries`).join('; '));

  /*
    7. The temperature: a0 and a1 go as 1/T from where they are given, their
    energies held, so a0 at 25 C is a0 (298.15/T) at T, and g0 = a0 R T is
    the same solid; heated along a table, a composition inside the gap of a
    regular solution leaves it where the gap's edge, ln((1 - x)/x) = a0(T)
    (1 - 2x), comes to it.
  */
  const at50 = (prm) => {
    const m = RtmModel.compile(ssText({ a: 1e-3, b: 1e-3, ma: 1e-3, mb: 1e-3, prm, settings: 'TEMPERATURE = 50\n' }));
    return { m, c: m.toConcentrations(m.initialState()) };
  };
  const R = 0.00831470;
  const given = at50('a0=3.43 a1=-1.82');
  const forms50 = [at50(`a0=${3.43 * 298.15 / 323.15} a1=${-1.82 * 298.15 / 323.15} tc=50`),
    at50(`g0=${3.43 * R * 298.15} g1=${-1.82 * R * 298.15}`)];
  let worst50 = 0;
  for (const f of forms50) for (let s = 0; s < 5; s++) worst50 = Math.max(worst50, Math.abs(f.c[s] / given.c[s] - 1));
  const p50 = RtmModel.binaryAt(defOf(given.m), 323.15);
  const heat = RtmModel.compile(ssText({ a: 1e-6, b: 1e-7, x: 1e-6, ma: 0.7, mb: 0.3, prm: 'a0=2.2',
    settings: 'TEMPERATURE = warm(t)\n\n<TABLE warm>\n0 25\n1 75\n' }));
  const rh = run(heat, { tend: 1 });
  const eh = rh.events[0] || { t: NaN, expr: '' };
  const xh = (() => { const c = heat.toConcentrations(run(heat, { tend: 1, outputTimes: [eh.t] }).grid.y[0], eh.t); return c[4] / (c[3] + c[4]); })();
  const xEdge = regular(2.2 * 298.15 / (298.15 + 50 * eh.t));
  // With the temperature going with time the gap is solved to round-off: the regular solution's edge, exactly.
  const heatDef = defOf(heat);
  const smooth = Math.max(...[300, 305.123, 310, 320].map((tk) => Math.abs(RtmModel.binaryAt(heatDef, tk).gap.xb1
    - regular(2.2 * 298.15 / tk))));
  const start = heat.toConcentrations(heat.initialState());
  const xs = start[4] / (start[3] + start[4]);
  check('  a0 and a1 go as 1/T, g0 = a0 R T is the same solid, and a water heated along a table leaves the gap where '
    + 'its edge comes to the composition', worst50 < 1e-13 && Math.abs(p50.a0 / (3.43 * 298.15 / 323.15) - 1) < 1e-15
    && rh.events.length === 1 && /MAB leaves its miscibility gap/.test(eh.expr) && Math.abs(xh - xEdge) < 1e-7
    && xs > regular(2.2) && xs < 1 - regular(2.2) && smooth < 1e-12,
  `at 50 C the three forms within ${worst50.toExponential(1)}; heated, x_B ${xs.toFixed(6)} inside the gap at 25 C leaves it `
    + `at ${(25 + 50 * eh.t).toFixed(5)} C, x_B there ${xh.toFixed(9)} and the edge ${xEdge.toFixed(9)} `
    + `(${Math.abs(xh - xEdge).toExponential(1)}), the gap the exact one to ${smooth.toExponential(1)}`);

  // 8. What it refuses.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const one = { a: 1e-3, b: 1e-3, ma: 0, mb: 0 };
  const cases = [
    ['one member', ssText({ ...one, prm: '' }).replace('MAB  MA  MB', 'MAB  MA'), /two or more/],
    ['a member not in <SPECIES>', ssText({ ...one }).replace('MAB  MA  MB', 'MAB  MA  MC'), /"MC" in <SOLID_SOLUTIONS> is not in <SPECIES>/],
    ['a member that is not a mineral', ssText({ ...one }).replace('MAB  MA  MB', 'MAB  MA  A'), /an end member is a mineral/],
    ['a member of two', ssText({ ...one, more: 'MAC  MA  MB\n' }), /end member of two solid solutions/],
    ['a member in no relation', ssText({ ...one, sp: 'MC 0 mineral\n' }).replace('MAB  MA  MB', 'MAB  MA  MC'), /in no relation/],
    ['a word it does not take', ssText({ ...one, prm: 'a2=1' }), /takes a0= and a1=/],
    ['a0 and g0', ssText({ ...one, prm: 'a0=1 g0=2' }), /one or the other/],
    ['a0 for three members', ssText({ ...one, sp: 'MC 0 mineral\nC 1e-3\n', rel: 'MC <=> C + X, logK = -8\n', prm: 'a0=1' })
      .replace('MAB  MA  MB', 'MAB  MA  MB  MC'), /are for two/],
    ['tc with nothing given at it', ssText({ ...one, prm: 'tc=50' }), /tc= is the temperature/],
    ['tc outside 0 to 350 C', ssText({ ...one, prm: 'a0=1 tc=400' }), /0 to 350 C/],
    ['no EQUILIBRATE', ssText({ ...one }).replace('EQUILIBRATE = always\n', ''), /needs EQUILIBRATE/],
    ['a name twice', ssText({ ...one, more: 'MAB  MA  MB\n' }), /is given twice/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
}

/*
   PITZER'S EQUATIONS, against what has to come out of them. One salt alone
   is Pitzer's single-electrolyte form, ln gamma+- and the osmotic
   coefficient in closed form. J(x), which E-theta is made of and which
   PHREEQC takes from Harvie's Chebyshev series, is Pitzer's integral, here
   by Gauss-Legendre quadrature, to that series' 1e-9. Under the MacInnes
   scaling ln gamma(Cl-) is KCl's at the ionic strength, and a water with no
   chloride is scaled by the Cl- it would have. A parameter goes with the
   temperature only by its six terms. The coefficients are the tests' own,
   round numbers, no database's. The Jacobian of a held water with every
   kind of parameter, against differences.
*/
console.log('\n--- Pitzer ---');
{
  const pzModel = (settings, species, pitzer, more = '') => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1\n`
    + `ACTIVITY = pitzer\n${settings}\n\n<SPECIES>\n${species}\n\n${more}<PITZER>\n${pitzer}\n`);
  const coefficients = (m, c) => {
    const ns = m.speciesNames.length;
    const lnG = new Float64Array(ns);
    const dG = new Float64Array(ns);
    const w = RtmModel.activityAt(m.act, c, 0, lnG, dG, 0);
    return { lnG, w, at: (n) => lnG[m.speciesNames.indexOf(n)] };
  };

  // 1. One salt, NaCl: ln gamma+- = f + m (2 b0 + 2 b1 h(x)) + 1.5 m^2 C, phi - 1 = -A sqrt(I)/(1 + b sqrt(I)) + m B + m^2 C.
  const b0 = 0.08;
  const b1 = 0.27;
  const cphi = 0.001;
  let worstG = 0;
  let worstW = 0;
  let warned = true;
  for (const m of [0.1, 1, 3, 6]) {
    const mod = pzModel('TEMPERATURE = 25', `Na+ ${m}\nCl- ${m}`, `B0 Na+ Cl- ${b0}\nB1 Na+ Cl- ${b1}\nC0 Na+ Cl- ${cphi}`);
    warned = warned && mod.warnings.some((w) => /MacInnes scaling is off, as PHREEQC turns it off/.test(w));
    const { at, w } = coefficients(mod, mod.initialState());
    const A = RtmModel.debyeHuckelAB(25, 1, Math.exp(w.lnAw)).A0;
    const s = Math.sqrt(m);
    const f = -A * (s / (1 + 1.2 * s) + (2 / 1.2) * Math.log(1 + 1.2 * s));
    const lng = f + m * (2 * b0 + (2 * b1 / (4 * m)) * (1 - (1 + 2 * s - 2 * m) * Math.exp(-2 * s))) + 1.5 * m * m * cphi;
    const phi = 1 - (A * s) / (1 + 1.2 * s) + m * (b0 + b1 * Math.exp(-2 * s)) + m * m * cphi;
    worstG = Math.max(worstG, Math.abs((at('Na+') + at('Cl-')) / 2 - lng));
    worstW = Math.max(worstW, Math.abs(w.lnAw + (2 * m * phi) / 55.50837));
  }
  check('Pitzer: NaCl alone is the single-salt form, ln gamma+- and the osmotic coefficient, at 0.1 to 6 mol/kg; '
    + 'without K+ and Cl- the MacInnes scaling is off, as in PHREEQC', worstG < 1e-14 && worstW < 1e-14 && warned,
  `ln gamma+- within ${worstG.toExponential(1)}, ln a(H2O) within ${worstW.toExponential(1)}`);

  // 2. J(x) against Pitzer's integral, J = (1/x) int (1 + q + q^2/2 - e^q) y^2 dy, q = -(x/y) e^-y.
  const GL = (() => {
    const n = 20;
    const xs = [];
    const ws = [];
    for (let i = 1; i <= n; i++) {
      let z = Math.cos((Math.PI * (i - 0.25)) / (n + 0.5));
      for (let it = 0; it < 100; it++) {
        let p0 = 1;
        let p1 = 0;
        for (let k = 1; k <= n; k++) { const p2 = p1; p1 = p0; p0 = ((2 * k - 1) * z * p1 - (k - 1) * p2) / k; }
        const dp = (n * (z * p0 - p1)) / (z * z - 1);
        const dz = p0 / dp;
        z -= dz;
        if (Math.abs(dz) < 1e-16) { xs.push(z); ws.push(2 / ((1 - z * z) * dp * dp)); break; }
      }
    }
    return { xs, ws };
  })();
  const Jq = (x) => {
    const f = (y) => { const q = -(x / y) * Math.exp(-y); return (1 + q + (q * q) / 2 - (q < -700 ? 0 : Math.exp(q))) * y * y; };
    const edges = [0];
    for (let k = -12; k <= 2; k += 0.05) edges.push(10 ** k);
    edges.push(150);
    let sum = 0;
    for (let i = 0; i + 1 < edges.length; i++) {
      const h = (edges[i + 1] - edges[i]) / 2;
      const mid = (edges[i] + edges[i + 1]) / 2;
      for (let j = 0; j < GL.xs.length; j++) sum += GL.ws[j] * h * f(mid + h * GL.xs[j]);
    }
    return sum / x;
  };
  const jo = new Float64Array(4);
  let worstJ = 0;
  for (const x of [0.001, 0.01, 0.1, 0.5, 1, 1.5, 3, 10, 30, 100]) {
    RtmModel.pitzerJ(x, jo);
    worstJ = Math.max(worstJ, Math.abs(jo[0] - Jq(x)));
  }
  const et = new Float64Array(3);
  const ep = new Float64Array(3);
  const em = new Float64Array(3);
  let worstE = 0;
  for (const [zj, zk] of [[1, 2], [-1, -2], [2, 3]]) {
    for (const I of [0.01, 0.1, 1, 6]) {
      RtmModel.pitzerEtheta(zj, zk, I, 0.39, et);
      const h = I * 1e-5;
      RtmModel.pitzerEtheta(zj, zk, I + h, 0.39, ep);
      RtmModel.pitzerEtheta(zj, zk, I - h, 0.39, em);
      worstE = Math.max(worstE, Math.abs((ep[0] - em[0]) / (2 * h) / et[1] - 1), Math.abs((ep[1] - em[1]) / (2 * h) / et[2] - 1));
    }
  }
  check('  E-theta: J(x) from Harvie\'s series, as PHREEQC has it, is Pitzer\'s integral by quadrature at x = 0.001 to 100, '
    + 'and E-theta\'s derivatives in I its differences', worstJ < 1e-9 && worstE < 1e-7,
  `J within ${worstJ.toExponential(1)}, the derivatives ${worstE.toExponential(1)}`);

  // 3. The MacInnes scaling: ln gamma(Cl-) = KCl's ln gamma+- at I; and a water with no chloride.
  const block = 'B0 Na+ Cl- 0.08\nB1 Na+ Cl- 0.27\nC0 Na+ Cl- 0.001\nB0 K+ Cl- 0.05\nB1 K+ Cl- 0.21\nC0 K+ Cl- -0.0008\n'
    + 'B0 Na+ SO4-2 0.02\nB1 Na+ SO4-2 1.1\nC0 Na+ SO4-2 0.005\nTHETA Cl- SO4-2 0.03\nPSI Cl- SO4-2 Na+ 0.0014';
  const mac = pzModel('TEMPERATURE = 25', 'Na+ 2.5\nCl- 1.5\nSO4-2 0.5', block);
  const { at: atMac, w: wMac } = coefficients(mac, mac.initialState());
  const I = wMac.I;
  const A = RtmModel.debyeHuckelAB(25, 1, Math.exp(wMac.lnAw)).A0;
  const s = Math.sqrt(I);
  const x = 2 * s;
  const xxx = (1 - (1 + x - (x * x) / 2) * Math.exp(-x)) / (x * x);
  const gamclm = -A * (s / (1 + 1.2 * s) + (2 / 1.2) * Math.log(1 + 1.2 * s)) + 2 * I * 0.05 + 2 * I * 0.21 * xxx
    + 1.5 * -0.0008 * I * I;
  const noCl = pzModel('TEMPERATURE = 25', 'Na+ 1\nSO4-2 0.5', block);
  const trace = pzModel('TEMPERATURE = 25', 'Na+ 1\nSO4-2 0.5\nCl- 1e-30', block);
  const g1 = coefficients(noCl, noCl.initialState());
  const g2 = coefficients(trace, trace.initialState());
  const dNoCl = Math.max(Math.abs(g1.at('Na+') - g2.at('Na+')), Math.abs(g1.at('SO4-2') - g2.at('SO4-2')),
    Math.abs(g1.w.lnAw - g2.w.lnAw));
  check('  the MacInnes scaling: ln gamma(Cl-) is KCl\'s at the ionic strength, and a water with no chloride is scaled by '
    + 'the Cl- it would have, K+ and Cl- named in <PITZER> without being species',
  Math.abs(atMac('Cl-') - gamclm) < 1e-14 && dNoCl < 1e-14 && mac.act.pz.icon && noCl.act.pz.icon,
  `ln gamma(Cl-) within ${Math.abs(atMac('Cl-') - gamclm).toExponential(1)}; no chloride against a trace of it `
    + `${dNoCl.toExponential(1)}`);

  // 4. The temperature: at 60 C as at 25 C with each parameter's value at 60 C (A_phi given, the same at both).
  const terms = 'B0 Na+ Cl- 0.08 -700 -4 0.009 -3e-6 2e4\nB1 Na+ Cl- 0.27 0 0 6e-5 1e-6\nC0 Na+ Cl- 0.001 30 0.09 -5e-5\n'
    + 'B0 Ca+2 Cl- 0.31 0 0 -3e-4 1.4e-7\nB1 Ca+2 Cl- 1.6 0 0 7.6e-3\nTHETA Ca+2 Na+ 0.07 1 0.01\nPSI Ca+2 Na+ Cl- -0.007 0 0 1e-5\n'
    + 'APHI 0.39 -10 0 0 1e-4';
  const hot = pzModel('TEMPERATURE = 60', 'Na+ 2\nCa+2 0.5\nCl- 3', terms);
  const val = (line) => {
    const parts = line.split(/\s+/);
    const n = parts[0] === 'PSI' ? 3 : parts[0] === 'APHI' ? 0 : 2;
    const a = new Float64Array(6);
    parts.slice(1 + n).forEach((v, i) => { a[i] = Number(v); });
    return `${parts.slice(0, 1 + n).join(' ')} ${n ? RtmModel.pitzerParam(a, 333.15) : RtmModel.pitzerParam(a, 333.15)}`;
  };
  const cold = pzModel('TEMPERATURE = 25', 'Na+ 2\nCa+2 0.5\nCl- 3', terms.split('\n').map(val).join('\n'));
  const gh = coefficients(hot, hot.initialState());
  const gc = coefficients(cold, cold.initialState());
  const dT = Math.max(...['Na+', 'Ca+2', 'Cl-'].map((n) => Math.abs(gh.at(n) - gc.at(n))), Math.abs(gh.w.lnAw - gc.w.lnAw));
  const p60 = 0.08 - 700 * (1 / 333.15 - 1 / 298.15) - 4 * Math.log(333.15 / 298.15) + 0.009 * 35 - 3e-6 * (333.15 ** 2 - 298.15 ** 2)
    + 2e4 * (1 / 333.15 ** 2 - 1 / 298.15 ** 2);
  const a6 = Float64Array.from([0.08, -700, -4, 0.009, -3e-6, 2e4]);
  check('  a parameter goes with the temperature by its six terms, as PHREEQC\'s calc_pitz_param has them, and only so',
    dT < 1e-14 && Math.abs(RtmModel.pitzerParam(a6, 333.15) - p60) < 1e-15 && RtmModel.pitzerParam(a6, 298.1505) === 0.08,
    `at 60 C the same as at 25 C with the values at 60 C to ${dT.toExponential(1)}`);

  // 5. A held water with every kind of parameter: NaCl and CO2 coming in, the Jacobian against differences.
  const all = 'B0 Na+ Cl- 0.08\nB0 K+ Cl- 0.05\nB0 Ca+2 Cl- 0.3\nB0 Na+ SO4-2 0.02\nB0 Ca+2 SO4-2 0.2\nB0 Na+ HCO3- 0.03\n'
    + 'B1 Na+ Cl- 0.27\nB1 K+ Cl- 0.21\nB1 Ca+2 Cl- 1.6\nB1 Na+ SO4-2 1.1\nB1 Ca+2 SO4-2 3.2\nB2 Ca+2 SO4-2 -54\n'
    + 'C0 Na+ Cl- 0.001\nC0 K+ Cl- -0.0008\nC0 Ca+2 Cl- -0.0003\nC0 Na+ SO4-2 0.005\n'
    + 'THETA K+ Na+ -0.01\nTHETA Ca+2 Na+ 0.07\nTHETA Cl- SO4-2 0.03\n'
    + 'LAMBDA CO2 Na+ 0.1\nLAMBDA CO2 Cl- -0.005\nLAMBDA CO2 CO2 0.02\nZETA CO2 Na+ Cl- -0.003\n'
    + 'PSI K+ Na+ Cl- -0.002\nPSI Ca+2 Na+ Cl- -0.007\nPSI Cl- SO4-2 Na+ 0.0014\n'
    + 'MU CO2 CO2 Na+ -0.001\nMU CO2 CO2 CO2 0.0005\nETA CO2 Ca+2 Na+ 0.002\nALPHAS Ca+2 SO4-2 1.4 12';
  const heldText = (extra = {}) => `<SETTINGS>\nMODE = ${extra.column ? 'transport\nCELLS = 3\nLENGTH = 0.03\nDIFFUSION = 1' : 'batch'}\n`
    + `TEND = 1e4\nACTIVITY = pitzer\nEQUILIBRATE = ${extra.pairs ? 'start' : 'always'}\nTEMPERATURE = ${extra.tc || 25}\n`
    + `${extra.atm ? `PRESSURE = ${extra.atm}\n` : ''}\n<SPECIES>\n`
    + `H+ 1e-7 ${extra.column ? 'D=1e-9' : ''}\nOH- 1e-7\nNa+ 3\nK+ 0.1\nCl- 3.1\nCa+2 0.1\nSO4-2 0.1\nHSO4- 1e-9\nCO2 1e-3\n`
    + `HCO3- 1e-3\nCO3-2 1e-5\nAnhydrite 0.1 mineral\n${extra.sp || ''}\n<EQUILIBRIUM>\n`
    + `H2O <=> H+ + OH-, logK = -14${extra.pairs ? ', kf = 1e6' : ''}\n`
    + `CO2 + H2O <=> H+ + HCO3-, logK = -6.35${extra.pairs ? ', kf = 1e3' : ''}\n`
    + `HCO3- <=> H+ + CO3-2, logK = -10.33${extra.pairs ? ', kf = 1e3' : ''}\n`
    + `HSO4- <=> H+ + SO4-2, logK = -1.98${extra.pairs ? ', kf = 1e3' : ''}\n`
    + `${extra.pairs ? '' : 'Anhydrite <=> Ca+2 + SO4-2, logK = -4.36\n'}${extra.rel || ''}\n<PITZER>\n${extra.pz || ''}${all}\n\n`
    + '<REACTIONS>\n=> Na+ + Cl-, k = 2e-4\n=> CO2, k = 1e-7\n';
  const jac = (label, extra) => {
    const out = { label, bad: 0, checked: 0, events: 0 };
    for (const tend of [10, 3000, 9999]) {
      const m = RtmModel.compile(heldText(extra).replace('TEND = 1e4', `TEND = ${tend}`));
      const r = run(m, { tend, rtol: 1e-9 });
      const v = RtmModel.verifyJacobian(m, tend, last(r));
      out.bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
      out.checked += v.checked;
    }
    return out;
  };
  const jacs = [jac('held', {}), jac('fast pairs', { pairs: true }), jac('a column of three cells', { column: true }),
    jac('an exchanger', { sp: 'X- 0.05 exchanger\nNaX 0 exchange\nCaX2 0 exchange', rel: 'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8\n' })];
  check('  the Jacobian of a water with every kind of parameter, held, as fast pairs, in a column and with an exchanger, '
    + 'against differences', jacs.every((j) => j.bad === 0),
  jacs.map((j) => `${j.label} ${j.bad} of ${j.checked}`).join('; '));

  /*
    5b. Hot. At 150 C, on the vapour pressure times a(H2O), A_phi is the
    water's own a(H2O)'s, the a(H2O) the osmotic coefficient gives with
    that A_phi (PHREEQC works A_phi out afresh at every iteration), and F of
    a charge of 1 or 2 reads the pressure the water is at there. NaCl alone
    by hand at that A_phi and pressure; then the derivatives the Jacobians
    read, against differences, which without A_phi's and the pressure's
    part in ln a(H2O) are a percent off at 150 C and half at 250 C.
  */
  const salt = pzModel('TEMPERATURE = 150', 'Na+ 3\nCl- 3', `B0 Na+ Cl- ${b0}\nB1 Na+ Cl- ${b1}\nC0 Na+ Cl- ${cphi}`);
  const hotSalt = coefficients(salt, salt.initialState());
  const wSalt = RtmModel.debyeHuckelAB(150, 1, Math.exp(hotSalt.w.lnAw));
  const sh = Math.sqrt(3);
  const B1h = 1.2 - (7e-5 + 1.93e-9 * (423.15 - 250) ** 2) * wSalt.atm;
  const fh = -wSalt.A0 * (sh / (1 + B1h * sh) + (2 / B1h) * Math.log(1 + B1h * sh));
  const lngh = fh + 3 * (2 * b0 + ((2 * b1) / 12) * (1 - (1 + 2 * sh - 6) * Math.exp(-2 * sh))) + 1.5 * 9 * cphi;
  const phih = 1 - (wSalt.A0 * sh) / (1 + 1.2 * sh) + 3 * (b0 + b1 * Math.exp(-2 * sh)) + 9 * cphi;
  const dSaltG = Math.abs((hotSalt.at('Na+') + hotSalt.at('Cl-')) / 2 - lngh);
  const dSaltW = Math.abs(hotSalt.w.lnAw + (6 * phih) / 55.50837);
  const A0pure = RtmModel.debyeHuckelAB(150).A0;
  check('  at 150 C, on the vapour pressure times a(H2O): A_phi is the water\'s own a(H2O)\'s, the one the osmotic '
    + 'coefficient gives with it, and F of a charge of 1 is at the pressure the water is at there',
  dSaltG < 1e-14 && dSaltW < 1e-14 && wSalt.atm > 1 && Math.abs(wSalt.A0 - A0pure) > 1e-6,
  `3 mol/kg NaCl: ln gamma+- within ${dSaltG.toExponential(1)}, ln a(H2O) within ${dSaltW.toExponential(1)}; A_phi `
    + `${wSalt.A0.toPrecision(10)} at a(H2O) = ${Math.exp(hotSalt.w.lnAw).toFixed(5)} (${A0pure.toPrecision(10)} at 1), `
    + `${wSalt.atm.toFixed(4)} atm`);
  const derivs = [['150 C, on the vapour pressure', 'TEMPERATURE = 150', ''],
    ['150 C at 10 atm', 'TEMPERATURE = 150\nPRESSURE = 10', ''], ['150 C with APHI', 'TEMPERATURE = 150', 'APHI 0.392 -11 0 0.0005\n'],
    ['250 C', 'TEMPERATURE = 250', '']].map(([label, settings, more]) => {
    const m = pzModel(settings, 'H+ 1e-7\nOH- 1e-7\nNa+ 3\nK+ 0.1\nCl- 3.1\nCa+2 0.1\nSO4-2 0.1\nCO2 1e-3\nHCO3- 1e-3\n'
      + 'CO3-2 1e-5', `${more}${all}`);
    const act = m.act;
    const ns = m.speciesNames.length;
    const C = Float64Array.from(m.initialState());
    const dG = new Float64Array(ns);
    const w = RtmModel.activityAt(act, C, 0, new Float64Array(ns), dG, 0);
    const dAwv = Float64Array.from(w.dAwv);
    const dGw = w.dGw ? Float64Array.from(w.dGw) : new Float64Array(ns);
    const { n, sysOf } = act.pz;
    const D = Float64Array.from(act.pz.D);
    const diff = (k, h) => {
      const up = Float64Array.from(C);
      const dn = Float64Array.from(C);
      up[k] += h;
      dn[k] -= h;
      const g1 = new Float64Array(ns);
      const g2 = new Float64Array(ns);
      const w1 = RtmModel.activityAt(act, up, 0, g1, new Float64Array(ns), 0);
      const w2 = RtmModel.activityAt(act, dn, 0, g2, new Float64Array(ns), 0);
      return { g: g1.map((v, i) => (v - g2[i]) / (2 * h)), w: (w1.lnAw - w2.lnAw) / (2 * h) };
    };
    let worst = 0;
    let without = 0;
    for (let k = 0; k < ns; k++) {
      if (!(C[k] >= 1e-4)) continue;
      // Central differences at h and 2h, extrapolated (Richardson).
      const a = diff(k, 2e-3 * C[k]);
      const b = diff(k, 1e-3 * C[k]);
      worst = Math.max(worst, Math.abs((4 * b.w - a.w) / 3 - dAwv[k]) / Math.abs(dAwv[k]));
      for (let s = 0; s < ns; s++) {
        const fixed = dG[s] * 0.5 * act.z[k] * act.z[k] + D[sysOf[s] * n + sysOf[k]];
        const an = fixed + dGw[s] * dAwv[k];
        const fd = (4 * b.g[s] - a.g[s]) / 3;
        worst = Math.max(worst, Math.abs(fd - an) / Math.max(Math.abs(an), 1e-3));
        without = Math.max(without, Math.abs(fd - fixed) / Math.max(Math.abs(fixed), 1e-3));
      }
    }
    return { label, worst, without, dGw: Math.max(...Array.from(dGw, Math.abs)) };
  });
  check('  the derivatives the Jacobians read, in I, in each species, and through A_phi and the pressure in ln a(H2O), '
    + 'and ln a(H2O)\'s own, against differences: on the vapour pressure and above it, with APHI, at 150 and 250 C',
  derivs.every((d) => d.worst < 1e-6 && d.dGw > 0),
  derivs.map((d) => `${d.label} ${d.worst.toExponential(1)} (${d.without.toExponential(1)} without A_phi's and the `
    + 'pressure\'s part)').join('; '));
  const hotJacs = [jac('held', { tc: 150 }), jac('with APHI', { tc: 150, pz: 'APHI 0.392 -11 0 0.0005\n' }),
    jac('at 10 atm', { tc: 150, atm: 10 })];
  check('  and the Jacobian of the held water at 150 C, on the vapour pressure, with APHI, and at 10 atm, against '
    + 'differences', hotJacs.every((j) => j.bad === 0), hotJacs.map((j) => `${j.label} ${j.bad} of ${j.checked}`).join('; '));

  // 6. What it refuses.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const sp = 'Na+ 1\nCl- 1\nCa+2 0.1\nSO4-2 0.1\nCO2 0.01\nAnhydrite 0 mineral';
  const tx = (p, act = 'pitzer') => `<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = ${act}\n\n<SPECIES>\n${sp}\n\n<PITZER>\n${p}\n`;
  const cases = [
    ['a <PITZER> without ACTIVITY = pitzer', tx('B0 Na+ Cl- 0.08', 'davies'), /read under ACTIVITY = pitzer, not davies/],
    ['an unknown type', tx('B3 Na+ Cl- 0.08'), /"B3" is no Pitzer parameter/],
    ['too few numbers', tx('B0 Na+ Cl-'), /takes two species and its value/],
    ['seven numbers', tx('B0 Na+ Cl- 1 2 3 4 5 6 7'), /up to five more terms/],
    ['a species not in <SPECIES>', tx('B0 Na+ Br- 0.1'), /"Br-" in <PITZER> is not in <SPECIES>/],
    ['a mineral', tx('LAMBDA CO2 Anhydrite 0.1'), /Anhydrite is no solute/],
    ['B0 between two cations', tx('B0 Na+ Ca+2 0.1'), /B0 is between a cation and an anion/],
    ['THETA between a cation and an anion', tx('THETA Na+ Cl- 0.1'), /THETA is between two ions of one sign/],
    ['PSI of three cations', tx('PSI Na+ Ca+2 Na+ 0.1'), /PSI is between two ions of one sign and one of the other/],
    ['LAMBDA of two ions', tx('LAMBDA Na+ Cl- 0.1'), /LAMBDA is between a neutral species and any other/],
    ['ZETA without a neutral species', tx('ZETA Na+ Ca+2 Cl- 0.1'), /ZETA is between a neutral species, a cation and an anion/],
    ['MU with one neutral species', tx('MU CO2 Na+ Cl- 0.1'), /MU is between three species, two of them neutral/],
    ['a parameter twice, either way round', tx('B0 Na+ Cl- 0.08\nB0 Cl- Na+ 0.07'), /B0 Cl- Na\+ is given twice, on lines/],
    ['APHI twice', tx('APHI 0.39\nAPHI 0.4'), /APHI is given twice/],
    ['ALPHAS with three numbers', tx('ALPHAS Ca+2 SO4-2 1 2 3'), /ALPHAS takes the pair's alpha1 and alpha2/],
    ['MACINNES yes with no K+ and Cl-', tx('B0 Na+ Cl- 0.08\nMACINNES yes'), /MACINNES yes needs the B0, B1 or C0 of K\+ and Cl-/],
    ['MACINNES maybe', tx('MACINNES maybe'), /MACINNES yes or MACINNES no/],
  ];
  const wrong = cases.filter(([, t, re]) => !re.test(refuse(t)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, t]) => `${what}: "${refuse(t)}"`).join(' | '));
}

/*
   LLNL'S ACTIVITY MODEL, against its closed form: an ion's B-dot form with
   A, B and B-dot straight between the tables' two temperatures either side
   (a table temperature's own at it), a neutral species given a= at 1, one
   given drummond Drummond's formula in kelvin, a neutral species given
   neither 0.1 I; a species on an exchanger its ion's form and its fraction.
   The tables are the tests' own.
*/
console.log('\n--- LLNL ---');
{
  const tables = 'TEMPERATURES 0 25 60 100\nDH_A 0.49 0.51 0.55 0.60\nDH_B 0.325 0.329 0.335 0.342\nBDOT 0.037 0.041 0.044 0.046\n'
    + 'CO2 -1.03 0.00128 256 0.44 -0.0016';
  const tab = [0, 25, 60, 100];
  const lin = (T, v) => {
    let i = 0;
    while (i + 1 < tab.length && T > tab[i + 1]) i++;
    const f = T === tab[i] ? 0 : (T - tab[i]) / (tab[i + 1] - tab[i]);
    return (1 - f) * v[i] + f * v[Math.min(i + 1, tab.length - 1)];
  };
  let worst = 0;
  for (const T of [0, 25, 40, 80, 100]) {
    const m = RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = llnl\nTEMPERATURE = ${T}\n\n<SPECIES>\n`
      + `Na+ 1 a=4\nCl- 1 a=3\nCa+2 0.1 a=6\nCO2 0.01 drummond\nSiO2 0.001 a=3\nNH3 0.001\n\n<LLNL>\n${tables}\n`);
    const ns = m.speciesNames.length;
    const lnG = new Float64Array(ns);
    const w = RtmModel.activityAt(m.act, m.initialState(), 0, lnG, new Float64Array(ns), 0);
    const I = w.I;
    const s = Math.sqrt(I);
    const A = lin(T, [0.49, 0.51, 0.55, 0.60]);
    const B = lin(T, [0.325, 0.329, 0.335, 0.342]);
    const bd = lin(T, [0.037, 0.041, 0.044, 0.046]);
    const g = (z, a) => -A * z * z * s / (1 + a * B * s) + bd * I;
    const tk = T + 273.15;
    const co2 = ((-1.03 + 0.00128 * tk + 256 / tk) * I - (0.44 - 0.0016 * tk) * I / (I + 1)) / Math.LN10;
    const at = (n) => lnG[m.speciesNames.indexOf(n)] / Math.LN10;
    worst = Math.max(worst, Math.abs(at('Na+') - g(1, 4)), Math.abs(at('Ca+2') - g(2, 6)), Math.abs(at('CO2') - co2),
      Math.abs(at('SiO2')), Math.abs(at('NH3') - 0.1 * I), Math.abs(w.lnAw - Math.log(1 - 0.017 * 2.112)));
  }
  check('LLNL: an ion\'s B-dot form, A, B and B-dot straight between the tables\' temperatures, a neutral species given a= at '
    + '1, Drummond\'s CO2, 0.1 I without either, at 0 to 100 C on and between the tables\' rows', worst < 1e-15,
  `within ${worst.toExponential(1)} in log gamma`);

  // An exchanger: NaX takes Na+'s form with its own a, and its fraction; the Jacobian of a held water with CO2 coming in.
  const held = (tend, more = '') => RtmModel.compile(`<SETTINGS>\nMODE = batch\nTEND = ${tend}\nACTIVITY = llnl\n`
    + `EQUILIBRATE = always\nTEMPERATURE = 40\n${more}\n<SPECIES>\nH+ 1e-7 a=9\nOH- 1e-7 a=3.5\nNa+ 1 a=4\nCl- 1 a=3\n`
    + 'Ca+2 0.01 a=6\nCO2 1e-3 drummond\nHCO3- 1e-3 a=4\nCO3-2 1e-6 a=4.5\nNaHCO3 1e-5\nX- 0.05 exchanger\n'
    + 'NaX 0 exchange a=4\nCaX2 0 exchange a=6\n\n<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -13.5\n'
    + 'CO2 + H2O <=> H+ + HCO3-, logK = -6.3\nHCO3- <=> H+ + CO3-2, logK = -10.2\nNa+ + HCO3- <=> NaHCO3, logK = -0.2\n'
    + 'Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8\n\n<REACTIONS>\n=> CO2, k = 1e-7\n=> Na+ + Cl-, k = 1e-4\n'
    + `\n<LLNL>\n${tables}\n`);
  const mx = held(1);
  const cx = mx.toConcentrations(mx.initialState());
  const nx = mx.speciesNames.length;
  const lx = new Float64Array(nx);
  const wx = RtmModel.activityAt(mx.act, cx, 0, lx, new Float64Array(nx), 0);
  const sx = Math.sqrt(wx.I);
  const A40 = lin(40, [0.49, 0.51, 0.55, 0.60]);
  const B40 = lin(40, [0.325, 0.329, 0.335, 0.342]);
  const bd40 = lin(40, [0.037, 0.041, 0.044, 0.046]);
  // ln gamma of NaX: ln(n/capacity), its share of the sites per mole, and Na+'s form with NaX's own a.
  const iNaX = mx.speciesNames.indexOf('NaX');
  const dEx = Math.abs(lx[iNaX] - Math.log(1 / 0.05) - Math.LN10 * (-A40 * sx / (1 + 4 * B40 * sx) + bd40 * wx.I));
  let bad = 0;
  let measured = 0;
  for (const tend of [10, 3000, 9999]) {
    const m = held(tend);
    const r = run(m, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m, tend, last(r));
    bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    measured += v.checked;
  }
  check('  a species on an exchanger its ion\'s B-dot form with its own a, and its fraction; the Jacobian of a held water '
    + 'with an exchanger and Drummond\'s CO2, against differences', dEx < 1e-13 && bad === 0,
  `NaX within ${dEx.toExponential(1)}; the Jacobian ${bad} of ${measured} entries off`);

  // What it refuses.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const base = (act, sp, ll) => `<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = ${act}\nTEMPERATURE = 25\n\n<SPECIES>\n${sp}\n`
    + `${ll === null ? '' : `\n<LLNL>\n${ll}\n`}`;
  const ok = 'Na+ 1 a=4\nCl- 1 a=3';
  const cases = [
    ['an <LLNL> without ACTIVITY = llnl', base('davies', ok, tables), /read under ACTIVITY = llnl, not davies/],
    ['drummond without it', base('davies', 'Na+ 1\nCl- 1\nCO2 1e-3 drummond', null), /read under ACTIVITY = llnl/],
    ['ACTIVITY = llnl without its tables', base('llnl', ok, null), /takes its tables in <LLNL>/],
    ['tables of different lengths', base('llnl', ok, tables.replace('DH_B 0.325 0.329 0.335 0.342', 'DH_B 0.325 0.329')),
      /DH_B has 2 values and TEMPERATURES 4/],
    ['temperatures that do not rise', base('llnl', ok, tables.replace('TEMPERATURES 0 25 60 100', 'TEMPERATURES 0 60 25 100')),
      /TEMPERATURES in <LLNL> rise/],
    ['a temperature outside them', base('llnl', ok, tables).replace('TEMPERATURE = 25', 'TEMPERATURE = 150'),
      /150 C, is outside LLNL's tables in <LLNL>, 0 to 100 C/],
    ['an ion with no a=', base('llnl', 'Na+ 1\nCl- 1 a=3', tables), /Na\+ is an ion and ACTIVITY = llnl: it takes a=/],
    ['drummond and a=', base('llnl', `${ok}\nCO2 1e-3 drummond a=3`, tables), /drummond and a or b/],
    ['drummond with no CO2 coefficients', base('llnl', `${ok}\nCO2 1e-3 drummond`, tables.split('\nCO2')[0]),
      /needs CO2 with Drummond's five coefficients/],
    ['a word it does not take', base('llnl', ok, `${tables}\nBDOT2 1 2 3 4`), /"BDOT2" in <LLNL>/],
    ['a table given twice', base('llnl', ok, `${tables}\nBDOT 1 2 3 4`), /BDOT is given twice in <LLNL>/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
}

/*
   MOLAR VOLUMES AND LOG K AT THE PRESSURE (<VOLUMES>), against PHREEQC's
   formulas written out here from its calc_rho_0, calc_dielectrics and
   calc_vm: each species' volume at the temperature, pressure and ionic
   strength, the water's own, and each relation's ln K less sum nu V (P - 1
   atm)/(R T); the water at the pressure given or at the vapour pressure
   times a(H2O), whichever is higher. The volumes are the tests' own.
*/
console.log('\n--- molar volumes and log K at the pressure ---');
{
  // PHREEQC's water, written out: its density at the pressure, compressibility and dielectric constant, Av and QBrn.
  const pWater = (tc, atm, aw) => {
    const T = tc + 273.15;
    const th = 1 - T / 647.096;
    const rhoSat = 322 * (1 + 1.99274064 * th ** (1 / 3) + 1.09965342 * th ** (2 / 3) - 0.510839303 * th ** (5 / 3)
      - 1.75493479 * th ** (16 / 3) - 45.5170352 * th ** (43 / 3) - 6.7469445e5 * th ** (110 / 3));
    const poly = (c) => c[0] + tc * (c[1] + tc * (c[2] + tc * (c[3] + tc * c[4])));
    const p0 = poly([5.1880000e-02, -4.1885519e-04, 6.6780748e-06, -3.6648699e-08, 8.3501912e-11]);
    const p1 = poly([-6.0251348e-06, 3.6696407e-07, -9.2056269e-09, 6.7024182e-11, -1.5947241e-13]);
    const p2 = poly([-2.2983596e-09, -4.0133819e-10, 1.2619821e-11, -9.8952363e-14, 2.3363281e-16]);
    const p3 = poly([7.0517647e-11, 6.8566831e-12, -2.2829750e-13, 1.8113313e-15, -4.2475324e-18]);
    const pSat = Math.exp(11.6702 - 3816.44 / (T - 46.13)) * Math.min(aw, 1);
    const P = Math.max(atm, pSat);
    const pa = P - (pSat - 1e-6);
    const rho = rhoSat + pa * (p0 + pa * (p1 + pa * (p2 + Math.sqrt(pa) * p3)));
    const kappa0 = (p0 + pa * (2 * p1 + pa * (3 * p2 + Math.sqrt(pa) * 3.5 * p3))) / rho;
    const d1000 = 342.79 * Math.exp(T * (-5.0866e-3 + T * 9.469e-7));
    const c = -2.0525 + 3115.9 / (T - 182.89);
    const b = -8032.5 + 4.2142e6 / T + 2.1417 * T;
    const pb = P * 1.01325;
    const eps = d1000 + c * Math.log((b + pb) / (b + 1000));
    const e2 = 1.671008e-3 / (eps * T);
    const kap = Math.sqrt(8 * 3.14159265358979 * 6.02252e23 * e2 * (rho / 1e3) / 1e3);
    return { T, P, pSat, Vw: 18.016 / (rho / 1e3), B: kap / 1e8, QBrn: c / (b + pb) / eps / eps * 41.84004,
      Av: kap * e2 * 0.0820597 * 1e3 * T * (c / (b + pb) * 1.01325 / eps - kappa0 / 3) };
  };
  // calc_vm, written out: -Vm's ten numbers in PHREEQC's units, or millero's six; an ion's terms in I.
  const pVolume = (v, z, tc, w, I) => {
    if (v.millero) {
      const m = v.millero;
      let V = m[0] + tc * (m[1] + tc * m[2]);
      if (z) V += z * z * 0.5 * w.Av * Math.sqrt(I) + (m[3] + tc * (m[4] + tc * m[5])) * I;
      return V;
    }
    const q = [...v, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0].slice(0, 10);
    if (v.length < 10) q[9] = 1;
    const pbS = 2600 + w.P * 1.01325;
    const TKs = tc + 45.15;
    let V = q[0] * 4.184004 + q[1] * 4184.004 / pbS + (q[2] * 41.84004 + q[3] * 418400.4 / pbS) / TKs - q[4] * 1e5 * w.QBrn;
    if (z) {
      V += z * z * 0.5 * w.Av * Math.sqrt(I) / (q[5] < 1e-5 ? 1 : 1 + q[5] * w.B * Math.sqrt(I));
      if (q[6] || q[7] || q[8]) V += (q[6] + q[7] / TKs + q[8] * TKs) * I ** q[9];
    }
    return V;
  };
  const VOLS = { 'Na+': [1.5, -3, -2, -0.5, 0.1, 4, 0.3, 50, -0.003, 0.6], 'Cl-': [4, 5, 4, -3, 1.7, 0, -0.3, 20, 0, 1],
    'Ca+2': Object.assign([], { millero: [18, 0.02, -0.0001, 1.5, 0.01, 0] }), 'CO3-2': [6, -3, 0, -5, 5, 0, 0.2, 100, -0.014, 0.9],
    'HCO3-': [8, 0.4], CaCO3: [-0.25, -8, 9, -2.5, -0.03] };
  const VM0 = { Calcite: 37 };
  const volText = `${Object.entries(VOLS).map(([n, v]) => `${n}  ${v.millero ? `millero  ${v.millero.join(' ')}` : v.join(' ')}`).join('\n')}\n`
    + 'Calcite  37\n';
  const charge = { 'Na+': 1, 'Cl-': -1, 'Ca+2': 2, 'CO3-2': -2, 'HCO3-': -1, CaCO3: 0, 'H+': 1, 'OH-': -1 };
  const text = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1}\nACTIVITY = debye-huckel\nTEMPERATURE = ${o.tc}\n`
    + `${o.atm ? `PRESSURE = ${o.atm}\n` : ''}${o.held ? 'EQUILIBRATE = always\n' : ''}\n<SPECIES>\nH+ 1e-8 a=9\nOH- 1e-6 a=3.5\n`
    + 'Na+ 1 a=4 b=0.08\nCl- 1 a=3.5\nCa+2 0.02 a=5 b=0.16\nCO3-2 1e-4 a=5.4\nHCO3- 0.005 a=5.4\nCaCO3 1e-4\nCalcite 0.1 mineral\n'
    + `${o.species || ''}\n<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -14\nHCO3- <=> H+ + CO3-2, logK = -10.3${o.kf ? `, kf = ${o.kf}` : ''}\n`
    + 'Ca+2 + CO3-2 <=> CaCO3, logK = 3.2\nCalcite <=> Ca+2 + CO3-2, logK = -8.5\n'
    + `${o.eq || ''}\n<REACTIONS>\n${o.react || '=> Na+ + Cl-, k = 0'}\n\n<VOLUMES>\n${volText}${o.vol || ''}`;
  // Each relation's ln K at the pressure, written out: less sum nu V (P - 1) 101325e-9/(R T), the water's too.
  const lnKP = (m, eq, C, I, aw, w) => {
    const f = w.P > 1 ? 1e-9 * (w.P * 101325 - 101325) / (0.0083147 * w.T) : 0;
    let dv = (eq.water || 0) * w.Vw;
    for (const [s, nu] of eq.net) {
      const n = m.speciesNames[s];
      if (VM0[n] !== undefined) dv += nu * VM0[n];
      else if (VOLS[n]) dv += nu * pVolume(VOLS[n], charge[n], w.T - 273.15, w, I);
    }
    return eq.lnK - f * dv;
  };
  const residuals = (m, C, cell = 0) => {
    const ns = m.speciesNames.length;
    const lnG = new Float64Array(ns);
    const wa = RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns), cell);
    const w = pWater(m.act.temperature, m.act.wt.atmGiven, Math.exp(wa.lnAw));
    let worst = 0;
    for (const eq of m.equilibria) {
      let r = lnKP(m, eq, C, wa.I, Math.exp(wa.lnAw), w) - (eq.water || 0) * wa.lnAw;
      for (const [s, nu] of eq.net) if (eq.mineral !== s) r -= nu * (Math.log(C[s]) + lnG[s]);
      if (eq.mineral >= 0 && !(C[eq.mineral] > 0)) continue;
      worst = Math.max(worst, Math.abs(r));
    }
    return { worst, w, wa };
  };

  // 1. Each species' volume and the water's, at 25 C and 500 atm, 80 C and 50 atm, and 150 C at its vapour pressure.
  let dV = 0;
  let dK = 0;
  for (const [tc, atm] of [[25, 500], [80, 50], [150, 0]]) {
    const m = RtmModel.compile(text({ tc, atm }));
    const y = m.toConcentrations ? m.toConcentrations(m.initialState()) : m.initialState();
    const mv = RtmModel.molarVolumes(m.act, y, 0, 0);
    const w = pWater(tc, atm || 1, Math.exp(mv.water.lnAw));
    for (const [n, v] of Object.entries(VOLS)) {
      dV = Math.max(dV, Math.abs(mv.V[m.speciesNames.indexOf(n)] - pVolume(v, charge[n], tc, w, mv.water.I)));
    }
    dV = Math.max(dV, Math.abs(mv.Vw - w.Vw), Math.abs(mv.V[m.speciesNames.indexOf('Calcite')] - 37), Math.abs(mv.P - w.P));
    for (const eq of m.equilibria) {
      dK = Math.max(dK, Math.abs(RtmModel.lnKAtP(eq, 0, mv.water) - lnKP(m, eq, y, mv.water.I, 0, w)));
    }
  }
  check('volumes: each species\' molar volume, -Vm\'s ten numbers in PHREEQC\'s units with b and the terms in I, millero\'s six, '
    + 'a mineral\'s own and the water\'s, and each relation\'s ln K less sum nu V (P - 1)/(R T), at 25 C and 500 atm, 80 C and 50 '
    + 'atm, and 150 C at the vapour pressure times a(H2O), against PHREEQC\'s formulas written out', dV < 1e-11 && dK < 1e-13,
  `volumes within ${dV.toExponential(1)} cm3/mol, ln K ${dK.toExponential(1)}`);

  // 2. Held while 1 mol/kgw of salt goes in at 500 atm: every stored point on its relations at the pressure; the Jacobian.
  const held = (tc, atm, tend) => RtmModel.compile(text({ tc, atm, held: true, tend, react: `=> Na+ + Cl-, k = ${1 / 1e5}` }));
  const runs = [[25, 500], [150, 0], [110, 0]].map(([tc, atm]) => {
    const m = held(tc, atm, 1e5);
    const r = run(m, { tend: 1e5 });
    let worst = 0;
    let I0 = 0;
    let I1 = 0;
    let P0 = 0;
    let P1 = 0;
    r.y.forEach((yy, i) => {
      const C = m.toConcentrations ? m.toConcentrations(yy) : yy;
      const rs = residuals(m, C);
      worst = Math.max(worst, rs.worst);
      if (i === 0) { I0 = rs.wa.I; P0 = rs.w.P; }
      I1 = rs.wa.I;
      P1 = rs.w.P;
    });
    let bad = 0;
    let checked = 0;
    for (const tend of [10, 3e4, 9e4]) {
      const m2 = held(tc, atm, tend);
      const r2 = run(m2, { tend, rtol: 1e-9 });
      const v = RtmModel.verifyJacobian(m2, tend, last(r2));
      bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
      checked += v.checked;
    }
    return { tc, atm, worst, I0, I1, P0, P1, bad, checked, points: r.y.length };
  });
  check('  held while 1 mol/kgw of NaCl goes in, at 500 atm and at 150 and 110 C on the vapour pressure: every stored point '
    + 'on its relations at the pressure, the volumes going with I, and with a(H2O) the pressure; the Jacobian against '
    + 'differences', runs.every((x) => x.worst < 1e-10 && x.bad === 0),
  runs.map((x) => `${x.tc} C ${x.atm ? `${x.atm} atm` : `${x.P0.toFixed(4)} to ${x.P1.toFixed(4)} atm`}, I ${x.I0.toFixed(2)} to `
    + `${x.I1.toFixed(2)}: ${x.worst.toExponential(1)} in ln K at ${x.points} points, the Jacobian ${x.bad} of ${x.checked} off`).join('; '));

  // 3. A fast pair at 500 atm: its backward constant kf/K at the pressure; a phase of <PHASES> and a mineral's saturation
  //    in a rate law; an exchanger's relations, whose species have no volume of their own.
  const pairText = (o = {}) => '<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = debye-huckel\nTEMPERATURE = 25\nPRESSURE = 500\n'
    + `${o.held ? 'EQUILIBRATE = always\n' : ''}\n<SPECIES>\nH+ 1e-8 a=9\nNa+ 1 a=4 b=0.08\nCl- 1 a=3.5\nCa+2 0.02 a=5 b=0.16\n`
    + `HCO3- 0.005 a=5.4\nCO3-2 1e-4 a=5.4\nX 0\n${o.species || ''}\n<EQUILIBRIUM>\n`
    + `${o.eq || 'HCO3- <=> H+ + CO3-2, logK = -10.3, kf = 2'}\n\n<PHASES>\nAragonite <=> Ca+2 + CO3-2, logK = -8.3\n\n`
    + `<REACTIONS>\n${o.react || '=> Na+ + Cl-, k = 1e-3'}\n\n<VOLUMES>\n${volText.split('\n')
      .filter((l) => /^(Na\+|Cl-|Ca\+2|CO3-2|HCO3-) /.test(l)).join('\n')}\nAragonite  34\n`;
  const pm = RtmModel.compile(pairText());
  const y0 = pm.initialState();
  const ns = pm.speciesNames.length;
  const f0 = new Float64Array(ns);
  pm.rhs(0, y0, f0);
  const lnG0 = new Float64Array(ns);
  const wa0 = RtmModel.activityAt(pm.act, y0, 0, lnG0, new Float64Array(ns), 0);
  const w0 = pWater(25, 500, Math.exp(wa0.lnAw));
  const at = (n) => pm.speciesNames.indexOf(n);
  const vOf = (n) => (VM0[n] !== undefined ? VM0[n] : pVolume(VOLS[n], charge[n], 25, w0, wa0.I));
  const fP = 1e-9 * (500 * 101325 - 101325) / (0.0083147 * w0.T);
  const lnK1 = -10.3 * Math.LN10 - fP * (vOf('CO3-2') - vOf('HCO3-'));
  const back = (2 / Math.exp(lnK1)) * Math.exp(lnG0[at('H+')] + lnG0[at('CO3-2')] - lnG0[at('HCO3-')]) * y0[at('H+')] * y0[at('CO3-2')];
  const pairApart = Math.abs(f0[at('CO3-2')] / (2 * y0[at('HCO3-')] - back) - 1);
  const pr = run(pm, { tend: 300 });
  const vp0 = RtmModel.verifyJacobian(pm, 0, y0);
  const vp1 = RtmModel.verifyJacobian(pm, 300, last(pr));
  // Saturation in a rate law: Aragonite of <PHASES> with its own volume; Calcite, a mineral held in <EQUILIBRIUM>.
  const sm = RtmModel.compile(pairText({ react: '=> X, r = SI(Aragonite)' }));
  const fs = new Float64Array(ns);
  sm.rhs(0, sm.initialState(), fs);
  const siArag = (Math.log(y0[at('Ca+2')]) + lnG0[at('Ca+2')] + Math.log(y0[at('CO3-2')]) + lnG0[at('CO3-2')]
    - (-8.3 * Math.LN10 - fP * (vOf('Ca+2') + vOf('CO3-2') - 34))) / Math.LN10;
  const siApart = Math.abs(fs[at('X')] - siArag);
  const vs = RtmModel.verifyJacobian(sm, 0, sm.initialState());
  // An exchanger: NaX and CaX2 on X-, at 500 atm; ln K less sum nu V of the ions alone.
  const ex = RtmModel.compile(pairText({ held: true, species: 'Xx- 0.05 exchanger\nNaXx 0 exchange\nCaXx2 0 exchange\n',
    eq: 'HCO3- <=> H+ + CO3-2, logK = -10.3\nNa+ + Xx- <=> NaXx, logK = 0\nCa+2 + 2 Xx- <=> CaXx2, logK = 0.8',
    react: '=> Na+ + Cl-, k = 1e-5' }));
  const cx = ex.toConcentrations(ex.initialState());
  const mvx = RtmModel.molarVolumes(ex.act, cx, 0, 0);
  const wx = pWater(25, 500, Math.exp(mvx.water.lnAw));
  const vx = (n) => pVolume(VOLS[n], charge[n], 25, wx, mvx.water.I);
  const eqNa = ex.equilibria.find((e) => /NaXx/.test(e.text));
  const eqCa = ex.equilibria.find((e) => /CaXx2/.test(e.text));
  const exApart = Math.max(Math.abs(RtmModel.lnKAtP(eqNa, 0, mvx.water) - (0 + fP * vx('Na+'))),
    Math.abs(RtmModel.lnKAtP(eqCa, 0, mvx.water) - (0.8 * Math.LN10 + fP * vx('Ca+2'))));
  let exBad = 0;
  let exChecked = 0;
  for (const tend of [1, 3e4]) {
    const m2 = RtmModel.compile(pairText({ held: true, species: 'Xx- 0.05 exchanger\nNaXx 0 exchange\nCaXx2 0 exchange\n',
      eq: 'HCO3- <=> H+ + CO3-2, logK = -10.3\nNa+ + Xx- <=> NaXx, logK = 0\nCa+2 + 2 Xx- <=> CaXx2, logK = 0.8',
      react: '=> Na+ + Cl-, k = 1e-5' }).replace('TEND = 1\n', `TEND = ${tend}\n`));
    const r2 = run(m2, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m2, tend, last(r2));
    exBad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    exChecked += v.checked;
  }
  check('  a fast pair\'s backward constant kf/K at the pressure; SI in a rate law of a phase of <PHASES> with its own '
    + 'volume; an exchanger\'s relations, ln K less sum nu V of the ions alone; each with its Jacobian against differences',
  pairApart < 1e-12 && siApart < 1e-12 && exApart < 1e-12 && vp0.discrepancies.length + vp1.discrepancies.length === 0
    && vs.discrepancies.length === 0 && exBad === 0,
  `the pair's rate within ${pairApart.toExponential(1)}, SI ${siApart.toExponential(1)} (${fs[at('X')].toFixed(4)}), `
    + `the exchanger's ln K ${exApart.toExponential(1)}; the Jacobians ${vp0.checked + vp1.checked + vs.checked + exChecked} entries, `
    + `${vp0.discrepancies.length + vp1.discrepancies.length + vs.discrepancies.length + exBad} off`);

  // 4. At one atmosphere and below 100 C nothing is corrected, and the text says so; what is refused.
  const idle = RtmModel.compile(text({ tc: 25 }));
  const idleSaid = idle.warnings.some((x) => /<VOLUMES>: the water is at 1 atm at 25 C/.test(x));
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const base = text({ tc: 25, atm: 100 });
  const cases = [
    ['<VOLUMES> without ACTIVITY', base.replace('ACTIVITY = debye-huckel', 'ACTIVITY = none').replace(/ a=[0-9.]+| b=[0-9.]+/g, ''),
      /it is read with ACTIVITY/],
    ['<VOLUMES> under ACTIVITY = llnl', `${base.replace('ACTIVITY = debye-huckel', 'ACTIVITY = llnl')}\n<LLNL>\n`
      + 'TEMPERATURES 0 25 60 100\nDH_A 0.49 0.51 0.55 0.6\nDH_B 0.325 0.329 0.335 0.342\nBDOT 0.037 0.041 0.044 0.046\n',
    /not read under ACTIVITY = llnl/],
    ['a species not in <SPECIES> or <PHASES>', `${base}Nope  3\n`, /"Nope" in <VOLUMES> is not in <SPECIES> or <PHASES>/],
    ['H2O', `${base}H2O  18\n`, /the water's molar volume is its own/],
    ['a mineral given two numbers', base.replace('Calcite  37', 'Calcite  37 1'), /it takes one number, its molar volume/],
    ['eleven numbers', base.replace('CaCO3  -0.25 -8 9 -2.5 -0.03', 'CaCO3  1 2 3 4 5 6 7 8 9 10 11'), /has 11 numbers/],
    ['millero with seven', base.replace('millero  18 0.02 -0.0001 1.5 0.01 0', 'millero  18 0.02 -0.0001 1.5 0.01 0 1'),
      /millero takes up to six/],
    ['a1 0', base.replace('CaCO3  -0.25', 'CaCO3  0'), /a1, the first number, where it is not 0/],
    ['a species given twice', `${base}CaCO3  1\n`, /CaCO3 is given twice in <VOLUMES>/],
    ['a word that is no number', base.replace('HCO3-  8 0.4', 'HCO3-  8 abc'), /"abc" is no number/],
  ];
  const exRefused = refuse(pairText({ species: 'Xx- 0.05 exchanger\nNaXx 0 exchange\n',
    eq: 'Na+ + Xx- <=> NaXx, logK = 0' }).replace('Aragonite  34\n', 'Aragonite  34\nNaXx  10\n'));
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  at 1 atm and 25 C the volumes change nothing, and a warning says so; refused, each with its reason: `
    + `${cases.map((c) => c[0]).join('; ')}; a species on an exchanger`, idleSaid && !wrong.length
    && /PHREEQC works out a molar volume for a solute, a mineral and a gas, and no other/.test(exRefused),
  `${idleSaid ? '' : 'no warning; '}${wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | ')}${
    /no other/.test(exRefused) ? '' : ` exchanger: "${exRefused}"`}`);
}

/*
   THE CONDUCTANCE, THE DENSITY AND THE VISCOSITY (<CONDUCTANCE>), and the
   sodium adsorption ratio. PHREEQC's calc_SC, calc_dens and viscosity()
   are held to PHREEQC itself in test-phreeqc.js; here, what needs no
   PHREEQC. Pure water's viscosity, Huber et al. (2009), against IAPWS
   R12-08's own check values, and at 25 C PHREEQC's 0.8900239182946. At
   infinite dilution: PHREEQC's older equation falls below Nernst and
   Einstein's conductance as the square root of the salt, Kohlrausch's law;
   Falkenhagen's, by the Debye-Hueckel-Onsager limiting law, its relaxation
   and electrophoretic terms worked out here from SI's constants and the
   water's dielectric constant. The SAR by hand, from the dissolved Na, Ca
   and Mg; what is refused. The numbers are the tests' own.
*/
console.log('\n--- the conductance, the density and the viscosity ---');
{
  // A salt at m mol/kgw; H+ there at nothing, its dw choosing the equation: Falkenhagen's where its sixth number is above 24.
  const text = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = debye-huckel\n\n<SPECIES>\nH+ 0 a=9\n`
    + `Na+ ${o.m || 1e-3} a=4\nCl- ${o.m || 1e-3} a=3.5\n${o.species || ''}\n<REACTIONS>\n=> Na+ + Cl-, k = 0\n\n${o.out || ''}`
    + `<CONDUCTANCE>\nH+   gfw 1  dw 9e-9 0 0 0 0 ${o.falk ? 25 : 0}\nNa+  gfw 23  dw 1.3e-9\nCl-  gfw 35.5  dw 2e-9\n${o.cond || ''}`;
  const props = (tx, keys) => {
    const m = RtmModel.compile(tx);
    const which = Int32Array.from(keys.map((k) => m.quantities.findIndex((q) => q.key === k)));
    const out = new Float64Array(keys.length).fill(NaN);
    if (![...which].some((x) => x < 0)) m.quantitiesAt(m.initialState(), 0, 0, which, out);
    return out;
  };
  // Pure water's viscosity: IAPWS R12-08's check values (uPa s, at T K and rho kg/m3), and 25 C at the water's own density.
  const iapws = [[298.15, 998, 889.7351], [373.15, 1000, 307.883622], [873.15, 600, 77.430195]];
  const iapwsOff = Math.max(...iapws.map(([T, rho, mu]) => Math.abs(RtmModel.waterViscosity(T, rho / 1e3) * 1e3 - mu)));
  const [visc25] = props(text({ m: 1e-10 }), ['viscos']);
  check('pure water\'s viscosity (Huber et al. 2009, as PHREEQC has it): IAPWS R12-08\'s check values to their six decimals, '
    + 'and at 25 C and the water\'s density PHREEQC\'s 0.8900239182946 mPa s', iapwsOff < 6e-7
    && Math.abs(visc25 / 0.8900239182946 - 1) < 1e-12,
  `IAPWS within ${iapwsOff.toExponential(1)} uPa s; ${visc25.toPrecision(13)} at 25 C`);

  // The older equation: below Nernst and Einstein's sum of z^2 Dw m (F^2/RT, PHREEQC's F and R) as the square root of m.
  const F = 96493.5;
  const R = 8.31470;
  const ne = (m) => ((1e7 * F * F) / (R * 298.15)) * 3.3e-9 * m;
  const short = [1e-8, 1e-6].map((m) => 1 - props(text({ m }), ['SC'])[0] / ne(m));
  // Falkenhagen's: the molar conductivity, SC V^2/(1e3 m) as calc_SC scales it, V the litres of a kilogram of water's
  // solution, falling from the ions' sum of Dw F^2/RT as (B1 Lambda0 + 2 B2) sqrt(m).
  const lambda = (m) => {
    const [sc, rho] = props(text({ m, falk: true }), ['SC', 'rho']);
    const V = (1 + 1e-3 * m * 58.5) / rho;
    return { L: (sc * V * V) / (1e3 * m), rho };
  };
  const [l1, l2] = [2e-10, 2e-9].map(lambda);
  const slope = (l2.L - l1.L) / (Math.sqrt(2e-9) - Math.sqrt(2e-10));
  const T = 298.15;
  const eps = 342.79 * Math.exp(T * (-5.0866e-3 + T * 9.469e-7)) + (-2.0525 + 3115.9 / (T - 182.89))
    * Math.log((-8032.5 + 4.2142e6 / T + 2.1417 * T + 1.01325) / (-8032.5 + 4.2142e6 / T + 2.1417 * T + 1000));
  const e = 1.602176634e-19;
  const kB = 1.380649e-23;
  const eps0 = 8.8541878128e-12;
  const NA = 6.02214076e23;
  const kappa = Math.sqrt((2000 * NA * e * e * l1.rho) / (eps0 * eps * kB * T));  // 1/m to a sqrt(mol/kgw)
  const q = 0.5;
  const B1 = ((e * e * kappa) / (12 * Math.PI * eps0 * eps * kB * T)) * (q / (1 + Math.sqrt(q)));
  const B2 = ((e * e * NA * kappa) / (6 * Math.PI * 0.8900239182946e-3)) * 1e4;  // S cm2/mol, an ion
  const L0 = ((1e4 * F * F) / (R * 1e-3 * 298.15e3)) * 3.3e-9;
  const onsager = -(B1 * L0 + 2 * B2);
  check('  at infinite dilution: PHREEQC\'s older equation below Nernst and Einstein as the square root of the salt '
    + '(Kohlrausch), and Falkenhagen\'s by the Debye-Hueckel-Onsager limiting law, its terms from SI\'s constants',
  short[0] > 0 && short[0] < 1e-4 && Math.abs(short[1] / short[0] / 10 - 1) < 0.01 && Math.abs(slope / onsager - 1) < 1e-4
    && Math.abs((l1.L - onsager * Math.sqrt(2e-10)) / L0 - 1) < 1e-7,
  `${short.map((x) => x.toExponential(2)).join(' and ')} short at 1e-8 and 1e-6 mol/kgw; the slope ${slope.toFixed(3)} for `
    + `Onsager's ${onsager.toFixed(3)} S cm2/mol to a sqrt(mol/kgw) (B1 ${B1.toFixed(4)}, 2 B2 ${(2 * B2).toFixed(2)}, eps ${eps.toFixed(3)})`);

  // The SAR, of what is dissolved; none without Na or without Ca and Mg; SC an <OUTPUT> took first stays its.
  const sarText = '<SETTINGS>\nMODE = batch\nTEND = 1\nACTIVITY = davies\n\n<SPECIES>\nNa+ 0.01\nNaSO4- 0.001\nCa+2 0.002\n'
    + 'CaSO4 0.0005\nMg+2 0.001\nSO4-2 0.003\nCl- 0.0105\n\n<REACTIONS>\n=> Na+ + Cl-, k = 0\n';
  const [sar] = props(sarText, ['SAR']);
  const noCa = RtmModel.compile(sarText.replace(/^(Ca\+2|CaSO4|Mg\+2) .*\n/gm, ''));
  const plain = RtmModel.compile(sarText);
  const taken = RtmModel.compile(text({ out: '<OUTPUT>\nSC = 2 * [Na+]\n\n' }));
  const scs = taken.quantities.filter((x) => x.key === 'SC');
  check('  the sodium adsorption ratio of the dissolved Na, Ca and Mg, by hand; none without Ca and Mg; no SC without '
    + '<CONDUCTANCE>; an <OUTPUT> named SC keeps the name', Math.abs(sar - 11 / Math.sqrt(3.5)) < 1e-12
    && !noCa.quantities.some((x) => x.key === 'SAR') && !plain.quantities.some((x) => ['SC', 'rho', 'viscos'].includes(x.key))
    && scs.length === 1 && scs[0].group === 'outputs',
  `SAR ${sar} for ${11 / Math.sqrt(3.5)}; ${scs.length} SC (${scs.map((x) => x.group).join(', ')})`);

  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (err) { return err.message; } };
  const base = text();
  const cases = [
    ['without ACTIVITY', base.replace('ACTIVITY = debye-huckel', 'ACTIVITY = none').replace(/ a=[0-9.]+/g, ''), /it is read with ACTIVITY/],
    ['under ACTIVITY = llnl', `${base.replace('ACTIVITY = debye-huckel', 'ACTIVITY = llnl')}\n<LLNL>\n`
      + 'TEMPERATURES 0 25 60 100\nDH_A 0.49 0.51 0.55 0.6\nDH_B 0.325 0.329 0.335 0.342\nBDOT 0.037 0.041 0.044 0.046\n',
    /not read under ACTIVITY = llnl/],
    ['a solute without its gfw', base.replace('Na+  gfw 23  dw', 'Na+  dw'), /gives no gfw for Na\+/],
    ['no species', `${base}Nope  gfw 3\n`, /Nope in <CONDUCTANCE> is no species/],
    ['a species given twice', `${base}Na+  gfw 23\n`, /Na\+ is given twice in <CONDUCTANCE>/],
    ['dw with eight numbers', base.replace('dw 1.3e-9', 'dw 1.3e-9 1 2 3 4 5 6 7'), /dw takes 1 to 7 numbers, not 8/],
    ['a word that is no number', base.replace('gfw 35.5', 'gfw abc'), /"abc" is no number/],
    ['a number before a word', base.replace('Cl-  gfw 35.5', 'Cl-  35.5 gfw'), /"35.5" is not one of them/],
    ['H2O given a dw', `${base}H2O  gfw 18 dw 1e-9\n`, /H2O in <CONDUCTANCE> takes its gfw alone/],
    ['a solute given vm', base.replace('Cl-  gfw 35.5', 'Cl-  gfw 35.5 vm 4 5'), /a solute's molar volume is in <VOLUMES>/],
    ['gfw 0', base.replace('gfw 35.5', 'gfw 0'), /gfw is above zero/],
    ['a mineral', text({ species: 'Rock 1 mineral\n', cond: 'Rock  gfw 100\n' }), /Rock in <CONDUCTANCE> is not dissolved/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((x) => x[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
}

/*
   SITES THAT GO WITH A MINERAL (sites= per=, PHREEQC's equilibrium_phase):
   a surface's sites so many per mole of a mineral held at saturation, as it
   dissolves. The sites are 0.05 times the mineral at every stored point,
   the relations hold, the zinc on them comes off into the water as they go
   and the total stays (what loading the surface from the water put on it
   included, as PHREEQC's -equilibrate has it); the Jacobian against
   differences. Made-up constants.
*/
console.log('\n--- sites that go with a mineral ---');
{
  const text = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1e4}\nEQUILIBRATE = always\n\n<SPECIES>\n`
    + 'H+ 1e-7\nOH- 1e-7\nCa+2 0.01\nSO4-2 0.01\nZn+2 1e-6\nAnh 0.05 mineral\n'
    + `Sx_OH ${o.amount || 0} surface sites=${o.sites || 0.05} per=${o.per || 'Anh'}\nSx_OH2+ 0 surface\nSx_O- 0 surface\n`
    + `Sx_OZn+ 0 surface\n${o.species || ''}\n<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -14\n`
    + 'Anh <=> Ca+2 + SO4-2, logK = -4.4\nSx_OH + H+ <=> Sx_OH2+, logK = 7\nSx_OH <=> Sx_O- + H+, logK = -9\n'
    + `Sx_OH + Zn+2 <=> Sx_OZn+ + H+, logK = 1\n${o.eq || ''}\n<REACTIONS>\n${o.react || 'Ca+2 =>, r = 1e-4*[Ca+2]'}\n`;
  const m = RtmModel.compile(text());
  const r = run(m, { tend: 1e4 });
  const at = (n) => m.speciesNames.indexOf(n);
  const onSf = ['Sx_OH', 'Sx_OH2+', 'Sx_O-', 'Sx_OZn+'].map(at);
  let ratio = 0;
  let rel = 0;
  let zn = 0;
  let zn0 = 0;
  let M0 = 0;
  let M1 = 0;
  let znOn0 = 0;
  let znOn1 = 0;
  r.y.forEach((yy, i) => {
    const C = m.toConcentrations(yy);
    const sites = onSf.reduce((acc, k) => acc + C[k], 0);
    ratio = Math.max(ratio, Math.abs(sites / (0.05 * C[at('Anh')]) - 1));
    // The relations, at the concentrations: a surface species' activity its fraction of the sites.
    const lnA = (n) => Math.log(C[at(n)]) - (onSf.includes(at(n)) ? Math.log(sites) : 0);
    rel = Math.max(rel, Math.abs(lnA('H+') + lnA('OH-') + 14 * Math.LN10),
      Math.abs(lnA('Ca+2') + lnA('SO4-2') + 4.4 * Math.LN10),
      Math.abs(lnA('Sx_OH2+') - lnA('Sx_OH') - lnA('H+') - 7 * Math.LN10),
      Math.abs(lnA('Sx_O-') + lnA('H+') - lnA('Sx_OH') + 9 * Math.LN10),
      Math.abs(lnA('Sx_OZn+') + lnA('H+') - lnA('Sx_OH') - lnA('Zn+2') - Math.LN10));
    if (i === 0) { M0 = C[at('Anh')]; znOn0 = C[at('Sx_OZn+')]; zn0 = C[at('Zn+2')] + znOn0; }
    zn = Math.max(zn, Math.abs(C[at('Zn+2')] + C[at('Sx_OZn+')] - zn0) / zn0);
    M1 = C[at('Anh')];
    znOn1 = C[at('Sx_OZn+')];
  });
  let bad = 0;
  let checked = 0;
  for (const tend of [10, 3000, 9000]) {
    const m2 = RtmModel.compile(text({ tend }));
    const r2 = run(m2, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m2, tend, last(r2));
    bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    checked += v.checked;
  }
  check('sites that go with a mineral: as calcium is taken out and the mineral dissolves, its surface\'s sites are 0.05 '
    + 'times it at every stored point, the relations hold with each species\' fraction of them, the zinc on them comes '
    + 'off into the water and the total stays; the Jacobian against differences', ratio < 1e-12 && rel < 1e-10 && zn < 1e-12
    && M1 < M0 - 0.002 && znOn1 < znOn0 && bad === 0,
  `the mineral ${M0.toFixed(5)} to ${M1.toFixed(5)}, the sites within ${ratio.toExponential(1)} of 0.05 times it, the `
    + `relations ${rel.toExponential(1)}, zinc on them ${znOn0.toExponential(3)} to ${znOn1.toExponential(3)}; the Jacobian `
    + `${bad} of ${checked} off`);

  // Amounts given with the sites: they make 0.05 per mole, or are refused; and what else is refused.
  // The whole state the start puts the water, the mineral and the surface at, given as amounts.
  const C0 = m.toConcentrations(m.initialState());
  let gtext = text();
  m.speciesNames.forEach((n, k) => {
    const esc = n.replace(/[+()]/g, (ch) => `\\${ch}`);
    gtext = gtext.replace(new RegExp(`^${esc} [^ \\n]+`, 'm'), `${n} ${C0[k]}`);
  });
  const given = RtmModel.compile(gtext);
  const Cg = given.toConcentrations(given.initialState());
  const sameStart = m.speciesNames.every((n, k) => C0[k] === 0 || Math.abs(Cg[k] / C0[k] - 1) < 1e-10);
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const cases = [
    ['per= naming no mineral', text({ per: 'Ca+2' }), /which is no mineral in <SPECIES>/],
    ['per= without sites=', text().replace('sites=0.05 per=Anh', 'per=Anh'), /per names the mineral a surface's sites, its potential's area, or an exchanger's sites, go with/],
    ['a mineral with two relations', text({ species: 'CaSO4 0', eq: 'Anh <=> CaSO4, logK = -2.3' }),
      /Anh is in two relations/],
    ['a relation taking more of the surface than it makes', text({ species: 'Sx_O2Zn 0 surface',
      eq: '2 Sx_OH + Zn+2 <=> Sx_O2Zn + 2 H+, logK = -2' }), /takes more species of the surface of Sx_OH than it makes/],
    ['a rate law changing the mineral', text({ react: 'Anh => Ca+2 + SO4-2, k = 1e-6' }), /changes Anh, which carries the sites/],
    ['amounts that do not make the sites', text().replace(/^Sx_OH [^\n]*$/m, 'Sx_OH 1e-3 surface sites=0.05 per=Anh'),
      /take 0\.001 sites, and 0\.05 per Anh make 0\.0025/],
    ['a double layer on them given grams', `${text()}`.replace('Sx_OZn+ 0 surface\n', 'Sx_OZn+ 0 surface\nSx_psi 1 potential area=600 grams=1\n'),
      /whose sites go with Anh, and its area goes with it too/],
    ['an area per mole on sites that are not', text({ species: 'Sy_OH 1e-4 surface\nSy_psi 1 potential area=600 per=Anh' }),
      /has its area per mole of Anh, and the sites of Sy_OH on its surface are not/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  // Used up: the run stops, and says why.
  let usedUp = '';
  try {
    const mu = RtmModel.compile(text({ tend: 1e6, react: 'Ca+2 =>, r = 1e-3*[Ca+2]' }).replace('Anh 0.05 mineral', 'Anh 0.002 mineral'));
    run(mu, { tend: 1e6 });
    usedUp = '(ran)';
  } catch (e) { usedUp = e.message; }
  // With a double layer whose area goes with the mineral too, 500 m2 to each mole: Gouy and Chapman at the area it has.
  const ddl = (tend) => RtmModel.compile(text({ tend }).replace('Sx_OZn+ 0 surface\n',
    'Sx_OZn+ 0 surface\nSx_psi 1 potential area=500 per=Anh\n'));
  const md = ddl(1e4);
  const rd = run(md, { tend: 1e4 });
  const eps = RtmModel.debyeHuckelAB(25).eps;
  const kS = Math.sqrt(8000 * 8.31470 * 298.15 * eps * 8.854e-12);
  let gcWorst = 0;
  let Mfirst = 0;
  let Mlast = 0;
  rd.y.forEach((yy, i) => {
    const C = md.toConcentrations(yy);
    const k = (n) => md.speciesNames.indexOf(n);
    const Q = C[k('Sx_OH2+')] - C[k('Sx_O-')] + C[k('Sx_OZn+')];
    const M = C[k('Anh')];
    const lnG = new Float64Array(C.length);
    const w = RtmModel.activityAt(md.act, C, 0, lnG, new Float64Array(C.length));
    const u = Math.log(C[k('Sx_psi')]);
    const sigma = (96493.5 * Q) / (500 * M);
    gcWorst = Math.max(gcWorst, Math.abs(sigma + kS * Math.sqrt(w.I) * Math.sinh(u / 2)) / Math.abs(sigma));
    if (i === 0) Mfirst = M;
    Mlast = M;
  });
  let dBad = 0;
  let dChecked = 0;
  for (const tend of [10, 5000]) {
    const m2 = ddl(tend);
    const r2 = run(m2, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m2, tend, last(r2));
    dBad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    dChecked += v.checked;
  }
  check('  with a double layer whose area goes with the mineral as well, 500 m2 to each mole of it: Gouy and Chapman hold at '
    + 'every stored point at the area the mineral has there; the Jacobian against differences', gcWorst < 1e-9 && dBad === 0
    && Mlast < Mfirst, `the mineral ${Mfirst.toFixed(5)} to ${Mlast.toFixed(5)}, the charge's balance within `
      + `${gcWorst.toExponential(1)}; the Jacobian ${dBad} of ${dChecked} off`);
  check('  amounts given with the sites start where loading them puts them; refused, each with its reason: '
    + `${cases.map((c) => c[0]).join('; ')}; and a run in which the mineral is used up stops and says why`,
  sameStart && !wrong.length && /Anh has dissolved away, and the sites of the surface that goes with it/.test(usedUp),
  `${sameStart ? '' : 'the start differs; '}${wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | ')}${
    /dissolved away/.test(usedUp) ? '' : ` used up: "${usedUp.slice(0, 160)}"`}`);

  /*
    Made and used at a rate, PHREEQC's kinetic_reactant: the mineral with no
    relation, dissolving at a rate law. Each reaction that changes it takes
    its sites with it, so many per mole, and the zinc on them comes off as
    above; a reaction that writes the surface's species as well is refused,
    and one that uses the mineral up stops the run, as above.
  */
  const kinText = (o = {}) => text({ tend: o.tend || 1e4, react: o.react || 'Anh => Ca+2 + SO4-2, r = 2e-4*[Anh]' })
    .replace('Anh <=> Ca+2 + SO4-2, logK = -4.4\n', '');
  const mk = RtmModel.compile(kinText());
  const rk = run(mk, { tend: 1e4 });
  const atk = (n) => mk.speciesNames.indexOf(n);
  const onK = ['Sx_OH', 'Sx_OH2+', 'Sx_O-', 'Sx_OZn+'].map(atk);
  let kRatio = 0;
  let kRel = 0;
  let kZn = 0;
  let kZn0 = 0;
  let kM = [0, 0];
  let kOn = [0, 0];
  rk.y.forEach((yy, i) => {
    const C = mk.toConcentrations(yy);
    const sites = onK.reduce((acc, k) => acc + C[k], 0);
    kRatio = Math.max(kRatio, Math.abs(sites / (0.05 * C[atk('Anh')]) - 1));
    const lnA = (n) => Math.log(C[atk(n)]) - (onK.includes(atk(n)) ? Math.log(sites) : 0);
    kRel = Math.max(kRel, Math.abs(lnA('H+') + lnA('OH-') + 14 * Math.LN10),
      Math.abs(lnA('Sx_OH2+') - lnA('Sx_OH') - lnA('H+') - 7 * Math.LN10),
      Math.abs(lnA('Sx_OZn+') + lnA('H+') - lnA('Sx_OH') - lnA('Zn+2') - Math.LN10));
    if (i === 0) { kM[0] = C[atk('Anh')]; kOn[0] = C[atk('Sx_OZn+')]; kZn0 = C[atk('Zn+2')] + kOn[0]; }
    kZn = Math.max(kZn, Math.abs(C[atk('Zn+2')] + C[atk('Sx_OZn+')] - kZn0) / kZn0);
    kM[1] = C[atk('Anh')];
    kOn[1] = C[atk('Sx_OZn+')];
  });
  let kBad = 0;
  let kChecked = 0;
  for (const tend of [10, 3000, 9000]) {
    const m2 = RtmModel.compile(kinText({ tend }));
    const r2 = run(m2, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m2, tend, last(r2));
    kBad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    kChecked += v.checked;
  }
  const kBoth = refuse(kinText({ react: 'Anh + 0.05 Sx_OH => Ca+2 + SO4-2, r = 2e-4*[Anh]' }));
  let kUsedUp = '';
  try {
    const mu = RtmModel.compile(kinText({ tend: 2e6, react: 'Anh => Ca+2 + SO4-2, r = 1e-7*(m/0.05)^0.6, m = ramp([Anh])' }));
    run(mu, { tend: 2e6 });
    kUsedUp = '(ran)';
  } catch (e) { kUsedUp = e.message; }
  check('sites that go with a mineral made and used at a rate, no relation of its own: each reaction that changes it '
    + 'takes its sites with it, 0.05 to each mole, at every stored point; the relations hold, the zinc on them comes off and '
    + 'the total stays; the Jacobian against differences; a reaction that writes the surface\'s species as well is refused, '
    + 'and one that uses it up stops the run and says why', kRatio < 1e-12 && kRel < 1e-10 && kZn < 1e-12 && kM[1] < 0.2 * kM[0]
    && kOn[1] < kOn[0] && kBad === 0 && /and the species on them as well/.test(kBoth)
    && /Anh has dissolved away, and the sites of the surface that goes with it/.test(kUsedUp),
  `the mineral ${kM[0].toFixed(5)} to ${kM[1].toFixed(5)}, the sites within ${kRatio.toExponential(1)} of 0.05 times it, the `
    + `relations ${kRel.toExponential(1)}, zinc on them ${kOn[0].toExponential(3)} to ${kOn[1].toExponential(3)}; the `
    + `Jacobian ${kBad} of ${kChecked} off${/and the species/.test(kBoth) ? '' : `; both: "${kBoth}"`}${
      /dissolved away/.test(kUsedUp) ? '' : `; used up: "${kUsedUp.slice(0, 160)}"`}`);
}

/*
   AN EXCHANGER'S SITES THAT GO WITH A MINERAL (sites= per= on a species on
   it, PHREEQC's `CaX2 Montmorillonite equilibrium_phase 0.165`): as calcium
   is taken out, anhydrite held at saturation dissolves, and the sites, 0.1
   to each mole of it in the form of CaX2, go with it. At every stored point
   what is on the exchanger is 0.1 times the mineral, and the relations hold
   with each species' activity its fraction of what is on it now, n C over
   the sum of n C -- Gaines-Thomas at the capacity the cell has then, which
   in exchange between ions of different charge is not the capacity it
   started with; the sodium and the sulphate stay; the Jacobian against
   differences, without activity coefficients, under Davies and under SIT
   (each species on it taking its ion's coefficient). Then the mineral made
   and used at a rate, a column, the electron's projected form, and what is
   refused. Made-up constants.
*/
console.log('\n--- an exchanger\'s sites that go with a mineral ---');
{
  const text = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1e4}\nEQUILIBRATE = ${o.equilibrate || 'always'}\n`
    + `${o.act ? `ACTIVITY = ${o.act}\n` : ''}\n<SPECIES>\nH+ 1e-7\nOH- 1e-7\nCa+2 0.01\nSO4-2 0.01\nNa+ 0.05\nCl- 0.05\n`
    + `${o.redox ? 'Fe+2 1e-4\nFe+3 1e-6\ne- electron\n' : ''}Anh ${o.anh || 0.05} mineral\nX- exchanger${o.cap ? ` ${o.cap}` : ''}\n`
    + `CaX2 ${o.amount || 0} exchange sites=${o.sites || 0.1} per=${o.per || 'Anh'}\nNaX ${o.naAmount || 0} exchange\n`
    + `${o.redox ? 'FeX2 0 exchange\n' : ''}${o.species || ''}\n<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -14\n`
    + `${o.redox ? 'Fe+2 <=> Fe+3 + e-, logK = -13\nFe+2 + 2 X- <=> FeX2, logK = 0.44\n' : ''}`
    + `${o.kinetic ? '' : 'Anh <=> Ca+2 + SO4-2, logK = -4.36\n'}Na+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8\n`
    + `${o.eq || ''}\n${o.act === 'sit' ? '<SIT>\nH+ Cl- 0.12\nNa+ Cl- 0.03\nNa+ OH- 0.04\nCa+2 Cl- 0.14\nNa+ SO4-2 -0.12\n\n' : ''}`
    + `<REACTIONS>\n${o.react !== undefined ? o.react : o.kinetic ? 'Anh => Ca+2 + SO4-2, r = 2e-4*[Anh]' : 'Ca+2 =>, r = 3e-4*[Ca+2]'}\n`
    + `${o.redox ? 'Fe+3 + e- =>, r = 1e-5*[Fe+3]\n' : ''}`;
  // At every stored point and in every cell: what is on the exchanger against 0.1 times the mineral, the relations
  // with each species' activity, its coefficient beyond its ion's against ln(n/sum), and the sodium and sulphate.
  const look = (m, r, o = {}) => {
    const at = (n) => m.speciesNames.indexOf(n);
    const ns = m.speciesNames.length;
    const out = { ratio: 0, rel: 0, frac: 0, kept: 0, M: [0, 0], f: [0, 0] };
    let na0 = 0;
    let s0 = 0;
    r.y.forEach((yy, i) => {
      const C = m.toConcentrations(yy);
      for (let c = 0; c < m.cells; c++) {
        const b = c * ns;
        const v = (n) => C[b + at(n)];
        const sum = v('NaX') + 2 * v('CaX2') + (o.redox ? 2 * v('FeX2') : 0);
        out.ratio = Math.max(out.ratio, Math.abs(sum / (0.1 * v('Anh')) - 1));
        const lnG = new Float64Array(ns);
        RtmModel.activityAt(m.act, C, b, lnG, new Float64Array(ns), c);
        const lnA = (n) => Math.log(v(n)) + lnG[at(n)];
        out.rel = Math.max(out.rel, Math.abs(lnA('NaX') - lnA('Na+') - lnA('X-')),
          Math.abs(lnA('CaX2') - lnA('Ca+2') - 2 * lnA('X-') - 0.8 * Math.LN10));
        if (!o.kinetic) out.rel = Math.max(out.rel, Math.abs(lnA('Ca+2') + lnA('SO4-2') + 4.36 * Math.LN10));
        const ion = (n) => (o.act === 'sit' ? lnG[at(n)] : 0);
        out.frac = Math.max(out.frac, Math.abs(lnG[at('NaX')] - ion('Na+') + Math.log(sum)),
          Math.abs(lnG[at('CaX2')] - ion('Ca+2') - Math.log(2 / sum)));
        if (m.cells === 1) {
          const na = v('Na+') + v('NaX');
          const s = v('SO4-2') + v('Anh');
          if (i === 0) { na0 = na; s0 = s; }
          out.kept = Math.max(out.kept, Math.abs(na / na0 - 1), Math.abs(s / s0 - 1));
        }
        if (c === 0) {
          if (i === 0) { out.M[0] = v('Anh'); out.f[0] = (2 * v('CaX2')) / sum; }
          out.M[1] = v('Anh');
          out.f[1] = (2 * v('CaX2')) / sum;
        }
      }
    });
    return out;
  };
  const jac = (mk, tends) => {
    let bad = 0;
    let checked = 0;
    for (const tend of tends) {
      const m2 = mk(tend);
      const r2 = run(m2, { tend, rtol: 1e-9 });
      const v = RtmModel.verifyJacobian(m2, tend, last(r2));
      bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
      checked += v.checked;
    }
    return { bad, checked };
  };
  const held = [{}, { act: 'davies' }, { act: 'sit' }].map((o) => {
    const m = RtmModel.compile(text(o));
    const res = look(m, run(m, { tend: 1e4 }), o);
    return { ...res, act: o.act || 'none', ...jac((tend) => RtmModel.compile(text({ ...o, tend })), [10, 3000, 9000]) };
  });
  check('an exchanger\'s sites that go with a mineral held at saturation, 0.1 to each mole of it as CaX2: as calcium is '
    + 'taken out and the mineral dissolves, what is on the exchanger is 0.1 times it at every stored point, the relations '
    + 'hold with each species\' fraction of what is on it now, the calcium\'s share falls, the sodium and the sulphate stay; '
    + 'the Jacobian against differences; without activity coefficients, under Davies and under SIT', held.every((h) =>
    h.ratio < 1e-12 && h.rel < 1e-10 && h.frac < 1e-12 && h.kept < 1e-12 && h.M[1] < h.M[0] - 0.005 && h.f[1] < h.f[0] - 0.04
    && h.bad === 0),
  held.map((h) => `${h.act}: the mineral ${h.M[0].toFixed(5)} to ${h.M[1].toFixed(5)}, calcium's share ${h.f[0].toFixed(3)} to `
    + `${h.f[1].toFixed(3)}, the sites within ${h.ratio.toExponential(1)}, the relations ${h.rel.toExponential(1)}, the `
    + `fractions ${h.frac.toExponential(1)}, the totals ${h.kept.toExponential(1)}; the Jacobian ${h.bad} of ${h.checked} off`)
    .join('; '));

  // Made and used at a rate, no relation of its own: each reaction that changes it takes its sites with it, as CaX2.
  const km = RtmModel.compile(text({ kinetic: true }));
  const kr = look(km, run(km, { tend: 1e4 }), { kinetic: true });
  const kj = jac((tend) => RtmModel.compile(text({ kinetic: true, tend })), [10, 3000, 9000]);
  // In a column, salt in at the inlet; and with the electron, whose models are held in the projected form.
  const column = (tend) => RtmModel.compile(text({ tend, act: 'davies', anh: 0.3 }).replace('MODE = batch\n',
    'MODE = transport\nCELLS = 8\nLENGTH = 0.1\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1e-5\nLEFT = robin\nRIGHT = free\n')
    .replace(/^(H\+|OH-) 1e-7$/gm, '$1 1e-7 D=1e-9 left=1e-7').replace(/^(Ca\+2|SO4-2) 0\.01$/gm, '$1 0.01 D=1e-9 left=0')
    .replace(/^(Na\+|Cl-) 0\.05$/gm, '$1 0.05 D=1e-9 left=0.2').replace('Ca+2 =>, r = 3e-4*[Ca+2]', ''));
  const cm = column(1e4);
  const cr = look(cm, run(cm, { tend: 1e4, rtol: 1e-9 }));
  const cj = jac(column, [500, 3000, 10000]);
  const em = RtmModel.compile(text({ redox: true, anh: 0.03 }));
  const er = look(em, run(em, { tend: 1e4 }), { redox: true });
  const ej = jac((tend) => RtmModel.compile(text({ redox: true, anh: 0.03, tend })), [10, 3000, 9000]);
  check('  made and used at a rate, no relation of its own: each reaction that changes the mineral takes its sites with it; '
    + 'in a column with salt coming in; and with the electron, held in the projected form: what is on the exchanger the '
    + 'mineral\'s 0.1 times, the relations, the Jacobian against differences', [[kr, kj], [cr, cj], [er, ej]].every(([x, j]) =>
    x.ratio < 1e-12 && x.rel < 1e-10 && x.frac < 1e-12 && j.bad === 0) && kr.M[1] < 0.2 * kr.M[0] && kr.kept < 1e-12
    && cr.M[1] < cr.M[0] - 0.05 && er.kept < 1e-12,
  [['at a rate', kr, kj], ['the column\'s inlet cell', cr, cj], ['with the electron', er, ej]].map(([w, x, j]) => `${w}: the `
    + `mineral ${x.M[0].toFixed(5)} to ${x.M[1].toFixed(5)}, calcium's share ${x.f[0].toFixed(3)} to ${x.f[1].toFixed(3)}, the `
    + `sites within ${x.ratio.toExponential(1)}, the relations ${x.rel.toExponential(1)}; the Jacobian ${j.bad} of ${j.checked} `
    + 'off').join('; '));

  // Amounts given with the sites: the start loading puts them where they are; and what is refused, with its reason.
  const m0 = RtmModel.compile(text());
  const C0 = m0.toConcentrations(m0.initialState());
  let gtext = text();
  m0.speciesNames.forEach((n, k) => {
    if (n === 'X-') return;
    const esc = n.replace(/[+()]/g, (ch) => `\\${ch}`);
    gtext = gtext.replace(new RegExp(`^${esc} [^ \\n]+`, 'm'), `${n} ${C0[k]}`);
  });
  const given = RtmModel.compile(gtext);
  const Cg = given.toConcentrations(given.initialState());
  const sameStart = m0.speciesNames.every((n, k) => n === 'X-' || C0[k] === 0 || Math.abs(Cg[k] / C0[k] - 1) < 1e-10);
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const cases = [
    ['sites= without per=', text().replace('sites=0.1 per=Anh', 'sites=0.1'), /there sites go with per=/],
    ['per= without sites=', text().replace('sites=0.1 per=Anh', 'per=Anh'), /or an exchanger's sites, go with/],
    ['per= naming no mineral', text({ per: 'Ca+2' }), /which is no mineral in <SPECIES>/],
    ['two species the form its sites go in', text().replace('NaX 0 exchange', 'NaX 0 exchange sites=0.05 per=Anh'),
      /one species on an exchanger is the form its sites go in/],
    ['its relations not held all through', text({ equilibrate: 1 }), /EQUILIBRATE = always/],
    ['a relation on it with a rate', text({ eq: 'Ca+2 + 2 NaX <=> CaX2 + 2 Na+, logK = 0.8, kf = 1e3' }), /has a rate, kf/],
    ['a capacity on the exchanger\'s line', text({ cap: 0.005 }), /the mineral gives the capacity, and the exchanger's line none/],
    ['amounts that do not make the sites', text({ amount: 0.001 }), /give amounts that make them/],
    ['a reaction changing the mineral held at saturation', text({ react: 'Anh => Ca+2 + SO4-2, r = 1e-6' }),
      /it changes by that alone/],
    ['a reaction that writes what is on it beside the mineral at a rate',
      text({ kinetic: true, react: 'Anh + 0.05 CaX2 => 1.05 Ca+2 + SO4-2, r = 2e-4*[Anh]' }),
      /and what is on them as well: the sites go with it by themselves/],
    ['a mineral in two relations', text({ species: 'CaSO4 0', eq: 'Anh <=> CaSO4, logK = -2.3' }), /Anh is in two relations/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  const usedUp = (o, tend) => { try { run(RtmModel.compile(text({ ...o, tend })), { tend }); return '(ran)'; } catch (e) { return e.message; } };
  const heldUp = usedUp({ anh: 0.02, react: 'Ca+2 =>, r = 1e-3*[Ca+2]' }, 1e5);
  const kinUp = usedUp({ kinetic: true, react: 'Anh => Ca+2 + SO4-2, r = 1e-7*(m/0.05)^0.6, m = ramp([Anh])' }, 2e6);
  const sayUp = /Anh has dissolved away, and the sites of the exchanger that goes with it/;
  check('  amounts given with the sites start where loading them puts them; refused, each with its reason: '
    + `${cases.map((c) => c[0]).join('; ')}; and a run in which the mineral is used up, held or at a rate, stops and says why`,
  sameStart && !wrong.length && sayUp.test(heldUp) && sayUp.test(kinUp),
  `${sameStart ? '' : 'the start differs; '}${wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | ')}${
    sayUp.test(heldUp) ? '' : ` held, used up: "${heldUp.slice(0, 160)}"`}${sayUp.test(kinUp) ? '' : ` at a rate: "${kinUp.slice(0, 160)}"`}`);
}

/*
   A MINERAL'S BOUNDS, AND ONE HELD AT ANOTHER PHASE'S SATURATION
   (PHREEQC's dissolve_only, precipitate_only, -force_equality and
   alternative reactions). Calcium taken out of a water over anhydrite, then
   put back: under dissolve_only it is never above what it starts with, the
   water left supersaturated there, dissolving once it is not and stopping
   at what it started with on the way back; under precipitate_only what it
   starts with is set aside and what precipitates beside it comes and goes;
   under force_equality it is held at saturation from none, below none. And
   a pH-stat: NaOH dissolving as much as holds SI(Fix_H+) = -8 while acid
   comes in, the pH held, the sodium the reagent gives the water what it
   loses. The Jacobians against differences; what is refused. Made-up
   constants.
*/
console.log('\n--- a mineral\'s bounds, and one held at another phase\'s saturation ---');
{
  const text = (flag, ca, anh, k, tend = 2e4) => `<SETTINGS>\nMODE = batch\nTEND = ${tend}\nEQUILIBRATE = always\n\n<SPECIES>\n`
    + `H+ 1e-7\nOH- 1e-7\nCa+2 ${ca}\nSO4-2 0.02\nNa+ 0.04\nCl- 0.04\nAnh ${anh} mineral ${flag}\n\n<EQUILIBRIUM>\n`
    + 'H2O <=> H+ + OH-, logK = -14\nAnh <=> Ca+2 + SO4-2, logK = -4.36\n\n<REACTIONS>\n'
    + `Ca+2 + 2 Cl- =>, r = ${k}*(1 - step(t - 1e4))\n=> Ca+2 + 2 Cl-, r = ${k}*step(t - 1e4)\n`;
  const times = [0, 2.5e3, 5e3, 7.5e3, 1e4, 1.25e4, 1.5e4, 1.75e4, 2e4];
  const look = (flag, ca, anh, k) => {
    const m = RtmModel.compile(text(flag, ca, anh, k));
    const r = run(m, { tend: 2e4, outputTimes: times });
    const at = (n) => m.speciesNames.indexOf(n);
    const M = [];
    const SI = [];
    r.grid.y.forEach((yy, i) => {
      const C = m.toConcentrations(yy, r.grid.t[i]);
      M.push(C[at('Anh')]);
      SI.push(Math.log10(C[at('Ca+2')] * C[at('SO4-2')]) + 4.36);
    });
    let bad = 0;
    let checked = 0;
    for (const tend of [10, 6000, 16000]) {
      const m2 = RtmModel.compile(text(flag, ca, anh, k, tend));
      const v = RtmModel.verifyJacobian(m2, tend, last(run(m2, { tend, rtol: 1e-9 })));
      bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
      checked += v.checked;
    }
    return { M, SI, events: r.events.map((e) => e.expr || ''), bad, checked };
  };
  const dis = look('dissolve_only', 0.02, 0.05, 3e-6);
  const pre = look('precipitate_only', 0.02, 0.05, 1e-6);
  const preOut = look('precipitate_only', 0.002, 0.05, 1e-7);
  const frc = look('force_equality', 0.002, 0, 1e-7);
  const f = (x) => x.toFixed(5);
  check('a mineral\'s bounds: under dissolve_only never above what it starts with, the water supersaturated while it is '
    + 'there, dissolving once the water is not and back at what it started with on the way up; under precipitate_only what '
    + 'it starts with set aside, what precipitates beside it coming and going, and with the water undersaturated none of it '
    + 'dissolving; under force_equality held at saturation from none, below none; the Jacobians against differences',
  dis.M[0] === 0.05 && dis.SI[0] > 0.9 && Math.abs(dis.SI[4]) < 1e-9 && dis.M[4] < 0.04 && dis.M[8] === 0.05 && dis.SI[8] > 0.9
    && dis.events.length === 2 && /dissolves/.test(dis.events[0]) && /precipitates no more \(dissolve_only\)/.test(dis.events[1])
    && pre.M[0] > 0.06 && pre.M.every((v) => v > 0.05) && pre.SI.every((v) => Math.abs(v) < 1e-9)
    && preOut.M.every((v) => v === 0.05) && preOut.SI[8] < preOut.SI[0]
    && frc.M[0] < 0 && frc.M[4] < frc.M[0] && frc.SI.every((v) => Math.abs(v) < 1e-9)
    && [dis, pre, preOut, frc].every((x) => x.bad === 0),
  `dissolve_only: ${dis.M.map(f).join(' ')} (SI ${dis.SI[0].toFixed(3)} to ${dis.SI[4].toExponential(0)} and back), `
    + `"${dis.events.join('", "')}"; precipitate_only: ${f(pre.M[0])} to ${f(Math.min(...pre.M))}, and undersaturated `
    + `${f(preOut.M[0])} throughout; force_equality: ${frc.M[0].toExponential(3)} to ${frc.M[4].toExponential(3)}; the `
    + `Jacobians ${[dis, pre, preOut, frc].reduce((a, x) => a + x.bad, 0)} of `
    + `${[dis, pre, preOut, frc].reduce((a, x) => a + x.checked, 0)} off`);

  // Under precipitate_only, what precipitated beside what it started with dissolving again: that is left, and said so.
  {
    const m = RtmModel.compile(text('precipitate_only', 0.02, 0.05, 1e-6, 1.9e4)
      .replace(/r = [^*\n]+\*\(1 - step\(t - 1e4\)\)/, 'r = 1e-6').replace(/\n=> Ca\+2 \+ 2 Cl-[^\n]*\n/, '\n'));
    const tt = Array.from({ length: 20 }, (_, i) => i * 1e3);
    const r = run(m, { tend: 1.9e4, outputTimes: tt });
    const M = r.grid.y.map((yy, i) => m.toConcentrations(yy, tt[i])[m.speciesNames.indexOf('Anh')]);
    const said = r.events.map((e) => e.expr || '');
    check('  under precipitate_only, what precipitated beside what it started with dissolving again: what it started '
      + 'with left, none of it dissolving, and the event says so, not that it has dissolved away',
    said.length === 1 && /^Anh is back at what it started with, and dissolves no more \(precipitate_only\)$/.test(said[0])
      && M[0] > 0.06 && M[18] === 0.05 && M[19] === 0.05,
    `"${said.join('", "')}" at ${r.events.map((e) => e.t.toFixed(0)).join(', ')} s; ${M[0].toFixed(5)} to ${M[19]}`);
  }

  // A pH-stat: NaOH dissolving as much as holds SI(Fix_H+) = -8, acid coming in.
  const stat = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1e4}\nEQUILIBRATE = always\n`
    + `${o.act ? 'ACTIVITY = davies\n' : ''}\n<SPECIES>\nH+ 1e-7\nOH- 1e-7\nCO2 1e-3\nHCO3- 1e-3\nCO3-2 1e-6\nNa+ 1e-3\n`
    + `Cl- 1e-6\n${o.species || 'NaOH_r 0.01 mineral'}\n\n<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -14\n`
    + 'CO2 + H2O <=> H+ + HCO3-, logK = -6.35\nHCO3- <=> H+ + CO3-2, logK = -10.33\n'
    + `${o.rel || 'NaOH_r <=> Na+ + OH-, SI(Fix_H+) = -8'}\n\n<PHASES>\n${o.phases || 'Fix_H+ <=> H+, logK = 0'}\n\n`
    + `<REACTIONS>\n=> H+ + Cl-, r = 2e-7\n`;
  const statRuns = [{}, { act: true }].map((o) => {
    const m = RtmModel.compile(stat(o));
    const r = run(m, { tend: 1e4, outputTimes: [0, 2500, 5000, 7500, 1e4] });
    const at = (n) => m.speciesNames.indexOf(n);
    const ns = m.speciesNames.length;
    let pH = 0;
    let na = 0;
    let na0 = 0;
    let used = 0;
    r.grid.y.forEach((yy, i) => {
      const C = m.toConcentrations(yy);
      const lnG = new Float64Array(ns);
      if (m.act) RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(ns));
      pH = Math.max(pH, Math.abs(-(Math.log(C[at('H+')]) + lnG[at('H+')]) / Math.LN10 - 8));
      const total = C[at('Na+')] + C[at('NaOH_r')];
      if (i === 0) { na0 = total; used = C[at('NaOH_r')]; }
      na = Math.max(na, Math.abs(total / na0 - 1));
      if (i === 4) used -= C[at('NaOH_r')];
    });
    let bad = 0;
    let checked = 0;
    for (const tend of [10, 3000, 9000]) {
      const m2 = RtmModel.compile(stat({ ...o, tend }));
      const v = RtmModel.verifyJacobian(m2, tend, last(run(m2, { tend, rtol: 1e-9 })));
      bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
      checked += v.checked;
    }
    return { pH, na, used, bad, checked };
  });
  check('  a pH-stat, NaOH dissolving as much as holds SI(Fix_H+) = -8 while acid comes in: the pH held, the NaOH used the '
    + 'acid that came in, the sodium the water gains what the reagent loses; without activity coefficients and under '
    + 'Davies; the Jacobians against differences', statRuns.every((x) => x.pH < 1e-12 && Math.abs(x.used / 2e-3 - 1) < 1e-3
    && x.na < 1e-14 && x.bad === 0),
  statRuns.map((x, i) => `${i ? 'Davies' : 'none'}: pH within ${x.pH.toExponential(1)} of 8, NaOH used `
    + `${x.used.toExponential(6)} for 2e-3 of acid, sodium kept ${x.na.toExponential(1)}; the Jacobian ${x.bad} of `
    + `${x.checked} off`).join('; '));

  // What is refused, each with its reason.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const cases = [
    ['a bound on what is no mineral', text('', 0.02, 0.05, 3e-6).replace('Na+ 0.04', 'Na+ 0.04 dissolve_only'),
      /which is a mineral's held at saturation/],
    ['dissolve_only and precipitate_only both', text('dissolve_only precipitate_only', 0.02, 0.05, 3e-6),
      /one of them/],
    ['a bound on a mineral with no relation', text('dissolve_only', 0.02, 0.05, 3e-6)
      .replace('Anh <=> Ca+2 + SO4-2, logK = -4.36\n', '').replace('Ca+2 + 2 Cl- =>', 'Anh => Ca+2 + SO4-2, r = 1e-9\nCa+2 + 2 Cl- =>'),
    /has none/],
    ['its relations not held all through', text('dissolve_only', 0.02, 0.05, 3e-6).replace('EQUILIBRATE = always', 'EQUILIBRATE = 1'),
      /EQUILIBRATE = always/],
    ['precipitate_only and force_equality', text('precipitate_only force_equality', 0.02, 0.05, 3e-6), /below none it would/],
    ['a rate law reading a mineral set aside in part', text('precipitate_only', 0.02, 0.05, 3e-6)
      .replace(/r = [^*\n]+\*\(1 - step\(t - 1e4\)\)/, 'r = 3e-6*[Anh]'), /reads Anh, which is given precipitate_only/],
    ['SI() on a relation with no mineral', stat({ rel: 'H2O <=> OH- + H+, SI(Fix_H+) = -8\nNaOH_r <=> Na+ + OH-, SI(Fix_H+) = -8' }),
      /has no mineral in it/],
    ['SI() of no phase in <PHASES>', stat({ rel: 'NaOH_r <=> Na+ + OH-, SI(Fix_OH-) = -6' }), /there is no phase Fix_OH- in <PHASES>/],
    ['SI() with a log K of its own', stat({ rel: 'NaOH_r <=> Na+ + OH-, SI(Fix_H+) = -8, logK = 2' }), /takes its log K from that phase/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx).slice(0, 160)}"`).join(' | '));
}

/*
   CD-MUSIC (PHREEQC's SURFACE with -cd_music): a surface with three
   potentials, planes 0, 1 and 2, the species' charges split over them by
   dz0, dz1 and dz2. Against PHREEQC's equations written out here: at every
   stored point of a run that adds acid, each relation holds with each
   plane's potential to the charge it puts there, sigma0 = c0 (psi0 - psi1),
   sigma0 + sigma1 = c1 (psi1 - psi2), and sigma0 + sigma1 + sigma2 +
   sigmad = 0 with the diffuse layer's charge from every ion and a
   fictitious one for the water's own charge; the Jacobian against
   differences, the water given a charge of its own (in charge balance its
   derivative has a corner, PHREEQC's fictitious ion). Made-up constants.
*/
console.log('\n--- CD-MUSIC ---');
{
  const F = 96493.5;
  const R = 8.31470;
  const T = 298.15;
  const fRT = F / (R * T);
  const area = 98;
  const grams = 1;
  const c0 = 0.9;
  const c1 = 0.74;
  // name, charge, dz0, dz1, dz2, type
  const SURF = [['S_uOH', -0.5, 0, 0, 0, 'u'], ['S_uOH2', 0.5, 1, 0, 0, 'u'], ['S_uOHNa', 0.5, 0, 1, 0, 'u'],
    ['S_uOH2Cl', -0.5, 1, -1, 0, 'u'], ['S_uOHZn', 1.5, 0.6, 1.4, 0, 'u'], ['S_tO', -0.5, 0, 0, 0, 't'],
    ['S_tOH', 0.5, 1, 0, 0, 't'], ['S_tONa', 0.5, 0, 0, 1, 't']];
  const text = (o = {}) => `<SETTINGS>\nMODE = batch\nTEND = ${o.tend || 1e4}\nEQUILIBRATE = always\nACTIVITY = davies\n\n<SPECIES>\n`
    + 'H+ 1e-7\nOH- 1e-7\nNa+ 0.01\nCl- 0.0098\nZn+2 1e-6\nZnOH+ 1e-9\n'
    + `${SURF.map(([n, z, d0, d1, d2]) => `${n} ${n === 'S_uOH' ? 0.00345 : n === 'S_tO' ? 0.0027 : 0} surface z=${z}`
      + `${d0 ? ` dz0=${d0}` : ''}${d1 ? ` dz1=${d1}` : ''}${d2 ? ` dz2=${d2}` : ''}`).join('\n')}\n`
    + `S_psi 1 potential area=${area} grams=${grams} c0=${c0} c1=${c1}\nS_psib 1 potential\nS_psid 1 potential\n${o.species || ''}\n`
    + '<EQUILIBRIUM>\nH2O <=> H+ + OH-, logK = -14\nZn+2 + H2O <=> ZnOH+ + H+, logK = -9\n'
    + 'S_uOH + H+ <=> S_uOH2, logK = 9.2\nS_uOH + Na+ <=> S_uOHNa, logK = -0.6\nS_uOH + H+ + Cl- <=> S_uOH2Cl, logK = 8.4\n'
    + 'S_uOH + Zn+2 <=> S_uOHZn, logK = 3\nS_tO + H+ <=> S_tOH, logK = 9.2\nS_tO + Na+ <=> S_tONa, logK = -0.6\n'
    + `\n<REACTIONS>\n${o.react || '=> H+ + Cl-, k = 1e-7'}\n`;
  const m = RtmModel.compile(text());
  const r = run(m, { tend: 1e4 });
  const k = (n) => m.speciesNames.indexOf(n);
  const eps = RtmModel.debyeHuckelAB(25).eps;
  const kS = Math.sqrt(8000 * R * T * eps * 8.854e-12);
  const ions = m.speciesNames.map((n, i) => [i, m.act.z[i]]).filter(([, z]) => z);
  let rel = 0;
  let planes = 0;
  let u20 = 0;
  let u21 = 0;
  r.y.forEach((yy, step) => {
    const C = m.toConcentrations(yy);
    const lnG = new Float64Array(C.length);
    RtmModel.activityAt(m.act, C, 0, lnG, new Float64Array(C.length));
    const u = ['S_psi', 'S_psib', 'S_psid'].map((n) => Math.log(C[k(n)]));
    const psi = u.map((v) => -v / fRT);
    const sites = { u: 0, t: 0 };
    for (const [n, , , , , t] of SURF) sites[t] += C[k(n)];
    const lnA = (n) => {
      const s = SURF.find((x) => x[0] === n);
      return s ? Math.log(C[k(n)] / sites[s[5]]) : Math.log(C[k(n)]) + lnG[k(n)];
    };
    const dz = (n) => SURF.find((x) => x[0] === n).slice(2, 5);
    // Each relation on the surface: sum nu ln a = ln K + sum over the planes of (charge put there) u.
    const check = (prod, reac, logK) => {
      let lhs = 0;
      const put = [0, 0, 0];
      for (const n of prod) { lhs += lnA(n); if (SURF.some((x) => x[0] === n)) dz(n).forEach((v, i) => { put[i] += v; }); }
      for (const n of reac) { lhs -= lnA(n); if (SURF.some((x) => x[0] === n)) dz(n).forEach((v, i) => { put[i] -= v; }); }
      return Math.abs(lhs - logK * Math.LN10 - (put[0] * u[0] + put[1] * u[1] + put[2] * u[2]));
    };
    rel = Math.max(rel, check(['S_uOH2'], ['S_uOH', 'H+'], 9.2), check(['S_uOHNa'], ['S_uOH', 'Na+'], -0.6),
      check(['S_uOH2Cl'], ['S_uOH', 'H+', 'Cl-'], 8.4), check(['S_uOHZn'], ['S_uOH', 'Zn+2'], 3),
      check(['S_tOH'], ['S_tO', 'H+'], 9.2), check(['S_tONa'], ['S_tO', 'Na+'], -0.6));
    // The planes' charges, C/m2: plane 0 the sites' own with dz0, planes 1 and 2 their dz.
    const cq = F / (area * grams);
    let s0 = 0;
    let s1 = 0;
    let s2 = 0;
    for (const [n, z, d0, d1, d2] of SURF) { s0 += (z - d1 - d2) * C[k(n)]; s1 += d1 * C[k(n)]; s2 += d2 * C[k(n)]; }
    s0 *= cq;
    s1 *= cq;
    s2 *= cq;
    // The diffuse layer's, PHREEQC's: every ion, and a fictitious one for the water's own charge.
    let D = 0;
    let net = 0;
    for (const [i, z] of ions) { D += C[i] * (Math.exp(z * u[2]) - 1); net += C[i] * z; }
    D += Math.abs(net) * (Math.exp(-(net >= 0 ? 1 : -1) * u[2]) - 1);
    const sd = (u[2] < 0 ? -1 : 1) * 0.5 * kS * Math.sqrt(D);
    const scale = Math.abs(s0) + Math.abs(s1) + Math.abs(s2) + Math.abs(sd);
    planes = Math.max(planes, Math.abs(s0 - c0 * (psi[0] - psi[1])) / scale, Math.abs(s0 + s1 - c1 * (psi[1] - psi[2])) / scale,
      Math.abs(s0 + s1 + s2 + sd) / scale);
    if (step === 0) u20 = psi[0];
    u21 = psi[0];
  });
  let bad = 0;
  let checked = 0;
  for (const tend of [10, 5000, 9000]) {
    const m2 = RtmModel.compile(text({ tend }));
    const r2 = run(m2, { tend, rtol: 1e-9 });
    const v = RtmModel.verifyJacobian(m2, tend, last(r2));
    bad += v.discrepancies.length + (v.outsidePattern ? 1 : 0);
    checked += v.checked;
  }
  check('CD-MUSIC: while acid goes in, every stored point holds each relation with each plane\'s potential to the charge it '
    + 'puts there, and PHREEQC\'s three equations, the capacitances between planes 0, 1 and 2 and the diffuse layer\'s charge '
    + 'from every ion and a fictitious one; the Jacobian against differences, the water given a charge of its own',
  rel < 1e-10 && planes < 1e-10 && bad === 0 && u21 > u20,
  `the relations within ${rel.toExponential(1)}, the planes ${planes.toExponential(1)} of their charges; psi0 ${(u20 * 1e3).toFixed(2)} `
    + `to ${(u21 * 1e3).toFixed(2)} mV; the Jacobian ${bad} of ${checked} off`);

  // What is refused, each with its reason.
  const refuse = (tx) => { try { RtmModel.compile(tx); return '(compiled)'; } catch (e) { return e.message; } };
  const base = text();
  const cases = [
    ['plane 2 missing', base.replace('S_psid 1 potential\n', ''), /three potentials, S_psi, S_psib and S_psid: S_psid is not in/],
    ['plane 1 without plane 0', base.replace(/^S_psi 1 potential[^\n]*\n/m, ''), /S_psib is plane 1 of a CD-MUSIC surface, whose first/],
    ['no capacitances', base.replace(' c0=0.9 c1=0.74', ''), /takes its capacitances, c0 between planes 0 and 1/],
    ['an area on plane 1', base.replace('S_psib 1 potential', 'S_psib 1 potential area=98 grams=1'), /its area, grams and capacitances are given on/],
    ['capacitances on a double layer', base.replace('S_psib 1 potential\nS_psid 1 potential\n', ''), /given c0 and c1, a CD-MUSIC surface's capacitances, and has no planes 1/],
    ['dz that do not add up to the charge', base.replace('S_uOH2Cl 0 surface z=-0.5 dz0=1 dz1=-1', 'S_uOH2Cl 0 surface z=-0.5 dz0=1'),
      /puts 0 of charge on its CD-MUSIC surface and 1, 0 and 0 on its planes/],
    ['dz off a CD-MUSIC surface', `${base}Q_OH 1e-3 surface dz0=1\n`.replace('<EQUILIBRIUM>\n', '<EQUILIBRIUM>\nQ_OH + H+ <=> Q_OH2+, logK = 7\n')
      .replace('Q_OH 1e-3 surface dz0=1\n', '').replace('S_psid 1 potential\n', 'S_psid 1 potential\nQ_OH 1e-3 surface dz0=1\nQ_OH2+ 0 surface\n'),
    /Q_OH is given dz0, dz1 and dz2, the charges a species puts on the planes of a CD-MUSIC surface, and its surface is none/],
    ['sites loaded from the water', base.replace('S_uOH 0.00345 surface z=-0.5', 'S_uOH 0 surface z=-0.5 sites=0.00345'),
      /on a CD-MUSIC surface, which is not loaded so/],
    ['a half charge off a surface', base.replace('Na+ 0.01', 'Na+ 0.01 z=0.5'), /a charge is a whole number, but on a surface/],
  ];
  const wrong = cases.filter(([, tx, re]) => !re.test(refuse(tx)));
  check(`  refused, each with its reason: ${cases.map((c) => c[0]).join('; ')}`, !wrong.length,
    wrong.map(([what, tx]) => `${what}: "${refuse(tx)}"`).join(' | '));
}

/* ======================================================================
   2z. What a run can be read as: QUANTITIES, <OUTPUT>, <DATA> and what each species is made of

   A species' name read as its formula; each quantity of a water against
   the same worked out by hand from the model's own activity coefficients;
   <OUTPUT> in the language of the rate laws, with an output above it, a
   parameter and x; and <DATA>, read, and its mistakes refused. A water
   from PHREEQC against PHREEQC's own numbers is in test-phreeqc.js.
   ====================================================================== */
console.log('\n--- what a run can be read as ---');
{
  const sorted = (o) => (o ? Object.fromEntries(Object.entries(o).sort(([a], [b]) => a.localeCompare(b))) : null);
  const formulas = [
    ['Ca+2', { Ca: 1 }], ['CaHCO3+', { Ca: 1, H: 1, C: 1, O: 3 }], ['UO2_2(OH)2+2', { U: 2, O: 6, H: 2 }],
    ['(UO2)2(OH)2+2', { U: 2, O: 6, H: 2 }], ['Ca0.5X', { Ca: 0.5, X: 1 }], ['Hfo_wOCa+', { Hfo_w: 1, O: 1, Ca: 1 }],
    ['CaSO4:2H2O', { Ca: 1, S: 1, O: 6, H: 4 }], ['CO2(g)', { C: 1, O: 2 }], ['Fe+++', { Fe: 1 }], ['e-', null], ['(Ca', null],
  ];
  const misread = formulas.filter(([n, want]) => {
    const got = RtmModel.elementsOf(n);
    return JSON.stringify(sorted(got ? Object.fromEntries(got) : null)) !== JSON.stringify(sorted(want));
  });
  check('a species\' name read as its formula: the charge left off, parentheses, From PHREEQC\'s UO2_2, Gapon\'s Ca0.5X, '
    + 'a surface\'s Hfo_w, a hydrate', !misread.length,
  misread.map(([n]) => `${n}: ${JSON.stringify(RtmModel.elementsOf(n) && Object.fromEntries(RtmModel.elementsOf(n)))}`).join(' | '));

  const water = `
<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = 1

<SPECIES>
H+       1e-7
OH-      1e-7
Na+      2e-3
Cl-      1e-3
Ca+2     1e-3
CO2      1e-4
HCO3-    2e-3
CO3-2    1e-5
NaHCO3   1e-5
CaHCO3+  1e-5

<EQUILIBRIUM>
 <=> H+ + OH-,                logK = -14
CO2 <=> H+ + HCO3-,           logK = -6.35
HCO3- <=> H+ + CO3-2,         logK = -10.33
Na+ + HCO3- <=> NaHCO3,       logK = -0.25
Ca+2 + HCO3- <=> CaHCO3+,     logK = 1.106

<PHASES>
Calcite <=> Ca+2 + CO3-2, logK = -8.48

<OUTPUT>
alk    = [HCO3-] + 2*[CO3-2] + [OH-] - [H+] + [NaHCO3] + [CaHCO3+], unit = eq/kgw
twice  = 2 * alk
pH2    = -log10({H+})
si     = SI(Calcite)
aw     = {H2O}
`;
  const m = RtmModel.compile(water);
  const c = m.initialState();
  const ns = m.speciesNames.length;
  const at = (n) => m.speciesNames.indexOf(n);
  const lnG = new Float64Array(ns);
  RtmModel.activityAt(m.act, c, 0, lnG, new Float64Array(ns));
  const la = (n) => (Math.log(c[at(n)]) + lnG[at(n)]) / Math.LN10;
  const z = { 'H+': 1, 'OH-': -1, 'Na+': 1, 'Cl-': -1, 'Ca+2': 2, 'HCO3-': -1, 'CO3-2': -2, 'CaHCO3+': 1 };
  let cb = 0;
  let ab = 0;
  let I = 0;
  for (const [n, zz] of Object.entries(z)) { cb += zz * c[at(n)]; ab += Math.abs(zz) * c[at(n)]; I += 0.5 * zz * zz * c[at(n)]; }
  const C = (...ns2) => ns2.reduce((acc, n) => acc + c[at(n)], 0);
  const want = {
    pH: -la('H+'), I, charge: (100 * cb) / ab, 'tot(C)': C('CO2', 'HCO3-', 'CO3-2', 'NaHCO3', 'CaHCO3+'),
    'tot(Ca)': C('Ca+2', 'CaHCO3+'), 'tot(Na)': C('Na+', 'NaHCO3'), 'SI(Calcite)': la('Ca+2') + la('CO3-2') + 8.48,
    'la(Ca+2)': la('Ca+2'), alk: C('HCO3-', 'OH-', 'NaHCO3', 'CaHCO3+') + 2 * c[at('CO3-2')] - c[at('H+')],
  };
  want.twice = 2 * want.alk;
  want.pH2 = want.pH;
  want.si = want['SI(Calcite)'];
  const keys = Object.keys(want);
  const which = Int32Array.from(keys.map((k) => m.quantities.findIndex((q) => q.key === k)));
  const got = new Float64Array(keys.length);
  if (![...which].some((x) => x < 0)) m.quantitiesAt(c, 0, 0, which, got);
  const off = keys.filter((k, q) => which[q] < 0 || Math.abs(got[q] - want[k]) > 1e-12 * Math.max(1, Math.abs(want[k])));
  const qOf = (k) => m.quantities.find((q) => q.key === k);
  check('each quantity of a water as worked out by hand from its own activity coefficients: pH, I, the charge balance, the '
    + 'totals of C, Ca and Na, SI(Calcite) of <PHASES>, a log activity, and <OUTPUT> -- an alkalinity, an output of an '
    + 'output, {H+}, SI() and {H2O}', !off.length && !qOf('tot(Cl)') && qOf('alk').axis === 'conc' && qOf('pH').axis === 'index'
    && qOf('tot(C)').group === 'totals' && Math.abs(got[keys.indexOf('pH')] - got[keys.indexOf('pH2')]) < 1e-14,
  off.length ? off.map((k) => `${k}: ${got[keys.indexOf(k)]} for ${want[k]}`).join(' | ')
    : `pH ${got[0].toFixed(4)}, SI(Calcite) ${got[keys.indexOf('SI(Calcite)')].toFixed(4)}, ${m.quantities.length} quantities`);
  const aw = new Float64Array(2);
  m.quantitiesAt(c, 0, 0, Int32Array.from(['aw', 'a(H2O)'].map((k) => m.quantities.findIndex((q) => q.key === k))), aw);
  check('  {H2O} in <OUTPUT> is the water\'s activity, a(H2O) among the quantities',
    Math.abs(aw[0] - aw[1]) < 1e-15 && aw[0] < 1 && aw[0] > 0.99, aw[0]);

  // In a column: x, a parameter, an output in cells of their own.
  const column = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 4
LENGTH = 1
TEND = 10

<SPECIES>
A  1  D=1e-9

<PARAMETERS>
k  all  3*x

<OUTPUT>
where = x
kx    = k * [A] + t
`);
  const cc = column.initialState();
  const wx = Int32Array.from(['where', 'kx'].map((k) => column.quantities.findIndex((q) => q.key === k)));
  const vals = [0, 1, 2, 3].map((cell) => { const o = new Float64Array(2); column.quantitiesAt(cc, 7, cell, wx, o); return [...o]; });
  check('  in a column: x the cell\'s centre, a parameter of the cell, and t the time asked at',
    vals.every(([w, kx], i) => Math.abs(w - (i + 0.5) * 0.25) < 1e-15 && Math.abs(kx - (3 * w + 7)) < 1e-12),
  JSON.stringify(vals));
  const refuseOut = (o) => { try { RtmModel.compile(water.replace(/<OUTPUT>[\s\S]*$/, `<OUTPUT>\n${o}\n`)); return ''; } catch (e) { return e.message; } };
  const badOut = [
    ['no name', 'Ca+2 * 2', /a line of <OUTPUT> is a name and what it is/],
    ['a name taken by a species', 'CO2 = [CO2] * 2', /the name is taken/],
    ['a name taken by a quantity', 'pH = 7', /the name is taken/],
    ['a species that is not', 'y = [Mg+2]', /\[Mg\+2\] is no species/],
    ['a phase that is not', 'y = SI(Gypsum)', /SI\(Gypsum\) -- "Gypsum" is no phase/],
    ['a name that is nothing', 'y = q * 2', /"q" is no species in brackets or braces/],
    ['something after the unit', 'y = [CO2], unit = mol/kgw, axis = left', /comes its unit, unit = mg\/kgw, and nothing else/],
  ];
  const wrongOut = badOut.filter(([, o, re]) => !re.test(refuseOut(o)));
  check(`  and refused, each with its reason: ${badOut.map((x) => x[0]).join(', ')}`, !wrongOut.length,
    wrongOut.map(([w, o]) => `${w}: "${refuseOut(o)}"`).join(' | '));

  // <DATA>: tables in time and in distance, and the mistakes it refuses.
  const dataModel = (d) => `<SETTINGS>\nMODE = transport\nCELLS = 4\nLENGTH = 1\nTEND = 10\n\n<SPECIES>\nA  1  D=1e-9\nB  0  D=1e-9\n\n<DATA>\n${d}\n`;
  const dm = RtmModel.compile(dataModel('time  A  B  cell = 2\n0  1  0\n5  0.5  -\ndistance  A  at = 2*2.5\n0.125  0.9\n0.375  0.7'));
  check('<DATA>: a table in time at a cell and one in distance at a time, a dash for a value not measured',
    dm.data.length === 2 && dm.data[0].kind === 'time' && dm.data[0].cell === 2 && JSON.stringify(dm.data[0].rows) === '[[0,1,0],[5,0.5,null]]'
    && dm.data[1].kind === 'distance' && dm.data[1].at === 5 && dm.data[1].rows.length === 2, JSON.stringify(dm.data));
  const refuseData = (d) => { try { RtmModel.compile(dataModel(d)); return ''; } catch (e) { return e.message; } };
  const badData = [
    ['a column that is nothing', 'time  A  C\n0  1  2', /"C" is no species and none of the page's quantities/],
    ['a row too short', 'time  A  B\n0  1', /has 3 columns, time and A, B/],
    ['a cell past the column', 'time  A  cell = 9\n0  1', /cell = 9, where the column has 4/],
    ['no time', 'time  A\n-  1', /the time always/],
    ['a time table at a time', 'time  A  at = 3\n0  1', /at = is for one in distance/],
    ['rows before a heading', '0  1', /<DATA> begins with a line naming the columns/],
  ];
  const wrongData = badData.filter(([, d, re]) => !re.test(refuseData(d)));
  check(`  and refused, each with its reason: ${badData.map((x) => x[0]).join(', ')}`, !wrongData.length,
    wrongData.map(([w, d]) => `${w}: "${refuseData(d)}"`).join(' | '));

  // COMPOSITION: what each species is made of, a mineral's from its relation, held or kinetic; the sulfate's sulfur and
  // the carbonate's equivalents, and the two quantities they make.
  const cm = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies

<SPECIES>
Ca+2      1e-3
Mg+2      2e-4
CO3-2     1e-5
HCO3-     2e-3
CO2       1e-4
CaHCO3+   1e-5
CaCO3     2e-6
H+        1e-8
SO4-2     1e-3
CaSO4     1e-4
HS-       1e-6
Calcite   0.01  mineral
Gypsum    0     mineral
Dolomite  0.02  mineral
X-        exchanger 2e-3
CaX2      exchange

<REACTIONS>
Dolomite => Ca+2 + Mg+2 + 2 CO3-2, r = 1e-12

<EQUILIBRIUM>
HCO3- <=> H+ + CO3-2,              logK = -10.329
CO2 + H2O <=> H+ + HCO3-,          logK = -6.352
Ca+2 + HCO3- <=> CaHCO3+,          logK = 1.106
Ca+2 + CO3-2 <=> CaCO3,            logK = 3.224
Ca+2 + SO4-2 <=> CaSO4,            logK = 2.25
Calcite <=> Ca+2 + CO3-2,          logK = -8.48
Gypsum <=> Ca+2 + SO4-2 + 2 H2O,   logK = -4.58
Ca+2 + 2 X- <=> CaX2,              logK = 0.8
`);
  const cn = cm.speciesNames;
  const termsOf = (el) => ((cm.composition.elements.find((e) => e.el === el) || { terms: [] }).terms)
    .map(([k, n, where]) => `${cn[k]}*${n}${where === 'water' ? '' : `@${where}`}`).sort().join(' ');
  const made = {
    C: 'CO2*1 CO3-2*1 CaCO3*1 CaHCO3+*1 Calcite*1@mineral Dolomite*2@mineral HCO3-*1',
    Ca: 'Ca+2*1 CaCO3*1 CaHCO3+*1 CaSO4*1 CaX2*1@exchange Calcite*1@mineral Dolomite*1@mineral Gypsum*1@mineral',
    Mg: 'Dolomite*1@mineral Mg+2*1',
    S: 'CaSO4*1 Gypsum*1@mineral HS-*1 SO4-2*1',
  };
  const madeOff = Object.entries(made).filter(([el, want]) => termsOf(el) !== want);
  check('what each species is made of: a solute\'s from its name, one on the exchanger the same, a mineral held at '
    + 'saturation from its relation (Gypsum\'s water left out) and a kinetic one from its reaction, Dolomite two C; '
    + 'no H or O, and no X', !madeOff.length && cm.composition.elements.every((e) => !['H', 'O', 'X'].includes(e.el)),
  madeOff.map(([el]) => `${el}: ${termsOf(el)}`).join(' | '));
  const listOf = (pairs) => pairs.map(([k, n]) => `${cn[k]}*${n}`).sort().join(' ');
  check('  the sulfate\'s sulfur in a species with four O to each S, not HS-; the carbonate\'s equivalents, CO3-2 and '
    + 'CaCO3 two, HCO3- and CaHCO3+ one, CO2 none',
  listOf(cm.composition.sulfate) === 'CaSO4*1 SO4-2*1'
    && listOf(cm.composition.carbonate) === 'CO3-2*2 CaCO3*2 CaHCO3+*1 HCO3-*1',
  `${listOf(cm.composition.sulfate)} | ${listOf(cm.composition.carbonate)}`);
  // VALENCE STATES, and the couples a redox ladder places: from a name that is a formula with one element left over, and
  // from the relations -- a complex its ions', a mineral or a species on an exchanger its ions', a mineral made with the
  // electron what the electrons it moves leave it.
  const vm = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = always
ACTIVITY = davies

<SPECIES>
H+  1e-7
OH- 1e-7
e-  electron pe=4
Na+ 1e-3
Cl- 1e-3
Ca+2 1e-3
NO3- 1e-4
NO2- 0
N2  0
NH4+ 0
SO4-2 1e-3
HS- 0
S2O3-2 0
CO3-2 1e-5
HCO3- 2e-3
CH4 0
Fe+2 1e-5
Fe+3 0
Fe(OH)3 0
Fe(OH)3- 0
FeSO4 0
FeHS+ 0
Mn+2 1e-6
O2  0
Pyrolusite 1e-6 mineral
Pyrite 0 mineral
Calcite 1e-3 mineral
X- exchanger 1e-3
FeX2 exchange

<EQUILIBRIUM>
 <=> H+ + OH-, logK = -14
NO3- + 2 H+ + 2 e- <=> NO2- + H2O, logK = 28.570
2 NO3- + 12 H+ + 10 e- <=> N2 + 6 H2O, logK = 207.08
NO3- + 10 H+ + 8 e- <=> NH4+ + 3 H2O, logK = 119.077
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O, logK = 33.65
2 SO4-2 + 10 H+ + 8 e- <=> S2O3-2 + 5 H2O, logK = 38.014
CO3-2 + H+ <=> HCO3-, logK = 10.329
CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O, logK = 41.071
Fe+2 <=> Fe+3 + e-, logK = -13.02
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+, logK = -12.56
Fe+2 + 3 H2O <=> Fe(OH)3- + 3 H+, logK = -31
Fe+2 + SO4-2 <=> FeSO4, logK = 2.25
Fe+2 + HS- <=> FeHS+, logK = 5.62
Pyrolusite + 4 H+ + 2 e- <=> Mn+2 + 2 H2O, logK = 41.38
Calcite <=> Ca+2 + CO3-2, logK = -8.48
Fe+2 + 2 X- <=> FeX2, logK = 0.44

<REACTIONS>
Pyrite + 3.5 O2 => Fe+2 + 2 SO4-2 + 2 H+, k = 0
`);
  const vn = vm.speciesNames;
  const stateIn = (nm, el) => {
    const e = vm.composition.elements.find((x) => x.el === el);
    const tm = e && e.terms.find(([k]) => vn[k] === nm);
    return tm ? tm[3] : undefined;
  };
  const wantStates = [['NO3-', 'N', 5], ['NO2-', 'N', 3], ['N2', 'N', 0], ['NH4+', 'N', -3], ['SO4-2', 'S', 6], ['HS-', 'S', -2],
    ['S2O3-2', 'S', 2], ['CH4', 'C', -4], ['HCO3-', 'C', 4], ['Fe(OH)3', 'Fe', 3], ['Fe(OH)3-', 'Fe', 2], ['FeSO4', 'Fe', 2],
    ['FeSO4', 'S', 6], ['FeHS+', 'Fe', 2], ['FeHS+', 'S', -2], ['Pyrolusite', 'Mn', 4], ['Calcite', 'C', 4], ['Calcite', 'Ca', 2],
    ['FeX2', 'Fe', 2], ['O2', 'O', undefined], ['Pyrite', 'Fe', null], ['Pyrite', 'S', null]];
  const statesOff = wantStates.filter(([nm, el, s]) => stateIn(nm, el) !== s);
  check('valence states: from a name that is a formula with one element left over, H +1 and O -2 -- Fe(OH)3- Fe(2), S2O3-2 '
    + 'S(2), a mean -- and from the relations, a complex its ions\' (FeSO4 Fe(2) and S(6), FeHS+ S(-2)), a mineral and a '
    + 'species on an exchanger their ions\' (Calcite, FeX2), a mineral made with the electron what it moves leaves it '
    + '(Pyrolusite Mn(4)); not from a reaction with O2, whose electrons go through the oxygen, which would make Pyrite\'s S '
    + 'S(6): its Fe and S untold', !statesOff.length,
  statesOff.map(([nm, el, s]) => `${nm} ${el}: ${stateIn(nm, el)} for ${s}`).join(', '));
  const coupleList = vm.composition.couples.map((c) => `${c.ox.join('+')}/${c.red.join('+')} ${c.el}(${c.hi})/${c.el}(${c.lo})`).join(', ');
  check('  the couples: each relation with the electron in it between two valence states, the oxidised first, the water\'s '
    + 'own (O, H) not among them', coupleList === 'NO3-/NO2- N(5)/N(3), NO3-/N2 N(5)/N(0), NO3-/NH4+ N(5)/N(-3), '
    + 'SO4-2/HS- S(6)/S(-2), SO4-2/S2O3-2 S(6)/S(2), CO3-2/CH4 C(4)/C(-4), Fe+3/Fe+2 Fe(3)/Fe(2), Pyrolusite/Mn+2 Mn(4)/Mn(2)',
  coupleList);
  // Each element's total in each of its valence states, PHREEQC's TOT("Fe(2)"), on the redox zones example's water: by hand.
  {
    const zt = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES.find((e) => e.id === 'redoxzones').text;
    const zm = RtmModel.compile(zt);
    const zy = zm.toConcentrations(zm.initialState());
    const zc = (nm) => zy[zm.speciesNames.indexOf(nm)];
    const zk = zm.quantities.map((q) => q.key);
    const zq = new Float64Array(zk.length);
    zm.quantitiesAt(zy, 0, 0, Int32Array.from(zk.map((_, i) => i)), zq);
    const zv = (key) => zq[zk.indexOf(key)];
    const byHand = {
      'tot(N(5))': zc('NO3-'), 'tot(N(3))': zc('NO2-'), 'tot(N(0))': 2 * zc('N2'),
      'tot(Fe(3))': zc('Fe+3') + zc('FeOH+2') + zc('Fe(OH)2+') + zc('Fe(OH)3') + zc('Fe(OH)4-'), 'tot(Fe(2))': zc('Fe+2') + zc('FeOH+'),
      'tot(S(6))': zc('SO4-2') + zc('HSO4-'), 'tot(S(-2))': zc('HS-') + zc('H2S'),
      'tot(C(4))': zc('CO3-2') + zc('HCO3-') + zc('CO2'), 'tot(C(-4))': zc('CH4'),
    };
    const wantKeys = Object.keys(byHand);
    const offBy = wantKeys.filter((key) => !(Math.abs(zv(key) - byHand[key]) <= 1e-15 * Math.max(byHand[key], 1e-300)));
    // Not without the electron: the radiolysis default's radicals and peroxides, CO3- and C2O6-2, are carbon(5) by formula.
    const noElectron = RtmModel.compile(RTM_DEFAULT_MODEL).quantities.filter((q) => /^tot\(.+\(.+\)\)$/.test(q.key)).length;
    check('each element\'s total in each of its valence states, PHREEQC\'s TOT("Fe(2)"), the oxidised first: on the redox zones '
      + 'example\'s water, nitrogen in three, iron, sulfur and carbon in two, each the sum of its species by hand; manganese '
      + 'dissolved in one alone, so none; and none in a model without the electron, the radiolysis default, whose radicals no '
      + 'formula gives a state', !offBy.length && noElectron === 0 && zk.filter((key) => /^tot\(.+\(.+\)\)$/.test(key)).join(' ')
      === 'tot(C(4)) tot(C(-4)) tot(Fe(3)) tot(Fe(2)) tot(N(5)) tot(N(3)) tot(N(0)) tot(S(6)) tot(S(-2))',
    `${zk.filter((key) => /^tot\(.+\(.+\)\)$/.test(key)).join(' ')}${offBy.length ? `; off: ${offBy.join(', ')}` : ''}`);
    /*
      The example run at the panel's tolerances, its steps a tenth of the run long -- runModel given no maximum step, as
      the page gives it none but the model's MAX_STEP: every point shown keeps its iron and its manganese, and is the
      speciation of its totals, re-speciated from what it shows settling at its first evaluation -- the one a step after pyrolusite
      has dissolved away among them, its FeS none in the run and 3e-45 in the state, which read as some did not settle
      -- and the zones in their order: the oxygen gone, then the nitrate;
      manganese(2) and iron(2) as the pyrolusite and the ferrihydrite go; FeS taking the iron(2) as the sulfate is
      reduced; methane last.
    */
    const zr = FacsimileODE.runModel(zm, { solver: 'ndf', tend: 160, rtol: 1e-6, atol: 1e-20, matrix: 'auto', maxPoints: 4000,
      stagnationTol: 0.5 });
    // And stopping at the days the order is read at, which moves the steps.
    const zd = FacsimileODE.runModel(zm, { solver: 'ndf', tend: 160, rtol: 1e-6, atol: 1e-20, matrix: 'auto', maxPoints: 4000,
      stagnationTol: 0.5, breaks: [30, 52, 55] });
    const el = (y, e) => zm.composition.elements.find((x) => x.el === e).terms.reduce((a, [k, n]) => a + n * y[k], 0);
    let keep = 0;
    const atDay = (d) => {
      const i = zd.t.findIndex((t) => Math.abs(t - d) < 1e-9);
      return Float64Array.from(zm.toConcentrations(zd.y[i], zd.t[i]));
    };
    let zMoved = 0;
    let zUnsettled = 0;
    let zLate = 0;
    let zRes = 0;
    for (let i = 0; i < zr.t.length; i++) {
      const y = Float64Array.from(zm.toConcentrations(zr.y[i], zr.t[i]));
      keep = Math.max(keep, Math.abs(el(y, 'Fe') - 2e-4) / 2e-4, Math.abs(el(y, 'Mn') - 1e-4) / 1e-4);
      let sp = null;
      try { sp = RtmModel.speciate(zm, y, { t: zr.t[i] }); } catch (e) { sp = null; }
      if (!sp || sp.cells.some((c) => !c.converged)) { zUnsettled++; continue; }
      for (const c of sp.cells) { if (c.iterations > 1) zLate++; zRes = Math.max(zRes, c.residual); }
      for (let k = 0; k < y.length; k++) {
        const isMin = !!zm.mineral[k % zm.speciesNames.length];
        if (!isMin && !(y[k] > 1e-30)) continue;
        zMoved = Math.max(zMoved, Math.abs(sp.y[k] - y[k]) / (isMin ? Math.max(Math.abs(y[k]), 1e-9) : y[k]));
      }
    }
    const qOf = (y, key) => { zm.quantitiesAt(y, 0, 0, Int32Array.of(zk.indexOf(key)), zq); return zq[0]; };
    const d30 = atDay(30);
    const d52 = atDay(52);
    const d55 = atDay(55);
    const d160 = atDay(160);
    const order = qOf(d30, 'tot(N(5))') > 5e-5 && d30[zm.speciesNames.indexOf('O2')] < 1e-6
      && qOf(d52, 'tot(N(5))') < 1e-12 && d52[zm.speciesNames.indexOf('Mn+2')] > 0.99e-4 && qOf(d52, 'tot(Fe(2))') > 1e-4
      && d55[zm.speciesNames.indexOf('Ferrihydrite')] === 0 && qOf(d55, 'tot(Fe(2))') > 1.9e-4
      && d160[zm.speciesNames.indexOf('FeS_ppt')] > 1.9e-4 && qOf(d160, 'tot(S(6))') < 1e-6 && qOf(d160, 'tot(S(-2))') > 9e-5
      && qOf(d160, 'tot(C(-4))') > 1e-4;
    check('  the example run with steps a tenth of the run long: every point shown keeps its iron and its manganese and is its '
      + 'own speciation, re-speciated from what it shows settling at its first evaluation, the one a step after the pyrolusite '
      + 'has gone among them, its FeS none and not the state\'s 3e-45; the zones in order -- oxygen gone by day 30, nitrate by '
      + '52, manganese(2) and iron(2) then, the ferrihydrite gone by 55, FeS holding the iron and the sulfate reduced by 160, '
      + 'methane',
    keep < 1e-12 && zUnsettled === 0 && zLate === 0 && zRes < 1e-12 && zMoved < 1e-4 && order && zr.events
      && zr.events.length === 3,
    `kept to ${keep.toExponential(1)}; re-speciated, ${zUnsettled} unsettled, ${zLate} cells past their first evaluation, `
      + `the relations and totals holding at the points shown to ${zRes.toExponential(1)}, the polishing step moving them by `
      + `${zMoved.toExponential(1)}; ${zr.t.length} points, ${zr.events ? zr.events.length : 0} events`);
  }
  const cc0 = cm.initialState();
  const ci = (n) => cc0[cn.indexOf(n)];
  const twoQ = Int32Array.from(['alk(CO3)', 'tot(SO4)', 'tot(S)'].map((k) => cm.quantities.findIndex((q) => q.key === k)));
  const twoV = new Float64Array(3);
  if (![...twoQ].some((x) => x < 0)) cm.quantitiesAt(cc0, 0, 0, twoQ, twoV);
  const alkWant = ci('HCO3-') + 2 * ci('CO3-2') + ci('CaHCO3+') + 2 * ci('CaCO3');
  // speciate for a diagram: one cell of a column, the rest left as they are, and an element's total set.
  const two = RtmModel.compile(`
<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 1
TEND = 1

<SPECIES>
H+      1e-7   D=1e-9
OH-     1e-7   D=1e-9
Na+     3e-3   D=1e-9
CO2     1e-4   D=1e-9
HCO3-   2e-3   D=1e-9
CO3-2   1e-5   D=1e-9

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14
CO2 <=> H+ + HCO3-,     logK = -6.352
HCO3- <=> H+ + CO3-2,   logK = -10.329
`);
  const y2 = two.initialState();
  const nsT = two.speciesNames.length;
  const weightsC = new Float64Array(nsT);
  for (const nm of ['CO2', 'HCO3-', 'CO3-2']) weightsC[two.speciesNames.indexOf(nm)] = 1;
  const sp2 = RtmModel.speciate(two, y2, { cells: [1], total: { weights: weightsC, value: 0.05, name: 'C' } });
  const totC = (y, cell) => ['CO2', 'HCO3-', 'CO3-2'].reduce((acc, nm) => acc + y[cell * nsT + two.speciesNames.indexOf(nm)], 0);
  const lnKres = Math.abs(Math.log(sp2.y[nsT + two.speciesNames.indexOf('H+')] * sp2.y[nsT + two.speciesNames.indexOf('HCO3-')]
    / sp2.y[nsT + two.speciesNames.indexOf('CO2')]) - Math.log(10 ** -6.352));
  check('  speciate for a diagram: one cell of a column alone, the other as it was, and the carbon\'s total set there '
    + 'through the conserved total that carries it, the relations held',
  sp2.cells.length === 1 && sp2.cells[0].converged && [...y2.subarray(0, nsT)].every((v, k) => v === sp2.y[k])
    && Math.abs(totC(sp2.y, 1) / 0.05 - 1) < 1e-12 && lnKres < 1e-10
    && Math.abs(sp2.y[nsT + two.speciesNames.indexOf('Na+')] - 3e-3) < 1e-18,
  `cell 1: total C ${totC(sp2.y, 1).toExponential(6)}, ln K within ${lnKres.toExponential(1)}`);
  // A sweep: the text with one number put in, and runs of it as the worker makes them.
  const swText = '<SETTINGS>\nMODE = transport   # a column\nVELOCITY = 1e-5\n\n<SPECIES>\nCa+2  1e-3  D=1e-9  left=2e-3  # calcium\n'
    + 'X-    exchanger 5e-3\nNa+   D=1e-9\n\n<PARAMETERS>\nk  all  3*x  fracture\nk  0  7\n';
  const wv = (kind, name, v) => RtmModel.withValue(swText, { kind, name }, v).split('\n');
  const edits = [
    ['a setting the text gives', wv('setting', 'VELOCITY', 2e-6)[2], 'VELOCITY = 0.000002'],
    ['a setting it does not, added to <SETTINGS>', wv('setting', 'TEND', 100)[1], 'TEND = 100'],
    ['a species\' start, its comment kept', wv('initial', 'Ca+2', 5e-4)[5], 'Ca+2  0.0005  D=1e-9  left=2e-3  # calcium'],
    ['an exchanger\'s capacity, after its word', wv('initial', 'X-', 0.01)[6], 'X-    exchanger 0.01'],
    ['a start where the line has none', wv('initial', 'Na+', 1e-3)[7], 'Na+  0.001   D=1e-9'],
    ['what flows in', wv('left', 'Ca+2', 1e-5)[5], 'Ca+2  1e-3  D=1e-9  left=0.00001  # calcium'],
    ['what flows in where nothing did', wv('left', 'Na+', 1e-5)[7], 'Na+   D=1e-9  left=0.00001'],
    ['every line of a parameter, its cells and scope kept', wv('parameter', 'k', 2.5).slice(10, 12).join('|'), 'k  all  2.5  fracture|k  0  2.5'],
  ];
  // And the number each has as the text gives it, which the page starts a sweep's values from.
  const vi = (kind, name) => RtmModel.valueIn(swText, { kind, name });
  edits.push(['the numbers the text gives each, null where it gives none', JSON.stringify([vi('setting', 'VELOCITY'),
    vi('setting', 'TEND'), vi('initial', 'Ca+2'), vi('initial', 'X-'), vi('initial', 'Na+'), vi('left', 'Ca+2'), vi('left', 'Na+'),
    vi('parameter', 'k')]), JSON.stringify([1e-5, null, 1e-3, 5e-3, 0, 2e-3, null, null])]);
  const editsOff = edits.filter(([, got, want]) => got !== want);
  let noParam = '';
  try { RtmModel.withValue(swText, { kind: 'parameter', name: 'q' }, 1); } catch (e) { noParam = e.message; }
  check(`a sweep's text: ${edits.map(([w]) => w).join(', ')}; and a parameter that is not there refused`,
    !editsOff.length && /no parameter q/.test(noParam), editsOff.map(([w, got]) => `${w}: "${got}"`).join(' | ') || noParam);
  global.RtmModel = RtmModel;
  global.FacsimileODE = FacsimileODE;
  const { handleRtmMessage } = require(path.join(jsDir, 'rtm-worker.js'));
  const decay = '<SETTINGS>\nMODE = batch\nTEND = 10\n\n<SPECIES>\nA 1\nB 0\n\n<PARAMETERS>\nkk all 0.1\n\n<REACTIONS>\nA => B, r = kk*[A]\n';
  const solverSw = { method: 'ndf', rtol: 1e-8, atol: 1e-20, nonNegative: true, maxPoints: 4000 };
  // An exchanger without ACTIVITY makes an activity model of its own, kind none, which marks nothing dissolved, its water's
  // activity being 1: the water is still the water -- its pH, its ionic strength, its totals, its species in the
  // composition, the solutes a diagram can hold.
  const exNone = '<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n\n<SPECIES>\nH+ 1e-7\nOH- 1e-7\nNa+ 1e-3\nCa+2 1e-3\n'
    + 'CaCl+ 0\nCl- 3e-3\nX- exchanger 1e-3\nNaX exchange\nCaX2 exchange\n\n<EQUILIBRIUM>\n <=> H+ + OH-, logK = -14\n'
    + 'Ca+2 + Cl- <=> CaCl+, logK = 0.4\nNa+ + X- <=> NaX, logK = 0\nCa+2 + 2 X- <=> CaX2, logK = 0.8\n';
  const exm = RtmModel.compile(exNone);
  let exSummary = null;
  handleRtmMessage({ type: 'compile', id: 9, text: exNone }, (m) => { exSummary = m; });
  const exKeys = exm.quantities.map((q) => q.key);
  const exQ = new Float64Array(exKeys.length);
  exm.quantitiesAt(exm.toConcentrations(exm.initialState()), 0, 0, Int32Array.from(exKeys.map((_, i) => i)), exQ);
  const exCa = (exm.composition.elements.find((e) => e.el === 'Ca') || { terms: [] }).terms
    .map(([k, , w]) => `${exm.speciesNames[k]}@${w}`).join(' ');
  check('an exchanger without ACTIVITY: the water is still the water -- the pH, the ionic strength and the calcium dissolved '
    + 'among the quantities, the pH 7 of its H+; the calcium in the water and on the exchanger in the composition; every '
    + 'species dissolved among the solutes a diagram can hold',
  ['pH', 'I', 'tot(Ca)'].every((k) => exKeys.includes(k)) && Math.abs(exQ[exKeys.indexOf('pH')] - 7) < 1e-9
    && exCa === 'Ca+2@water CaCl+@water CaX2@exchange' && !!exSummary && exSummary.model.solutes.join(' ') === 'H+ OH- Na+ Ca+2 CaCl+ Cl-',
  `${exKeys.join(' ')} | ${exCa} | ${exSummary && exSummary.model ? exSummary.model.solutes.join(' ') : JSON.stringify(exSummary).slice(0, 200)}`);
  // MAX_STEP: the longest step the worker's run takes, where the panel's Maximum step is 0; the panel's where it is not.
  {
    const zText = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES.find((e) => e.id === 'redoxzones').text;
    const longest = (solver) => {
      let got = null;
      handleRtmMessage({ type: 'run', id: 11, text: zText, solver }, (msg) => { if (msg.type === 'result') got = msg; });
      let most = 0;
      for (let i = 1; i < got.n; i++) most = Math.max(most, got.t[i] - got.t[i - 1]);
      return [got.n, most];
    };
    const [nModel, hModel] = longest({ ...solverSw, rtol: 1e-6 });
    const [nPanel, hPanel] = longest({ ...solverSw, rtol: 1e-6, hmax: 5 });
    check('MAX_STEP: the redox zones example, MAX_STEP = 1, run by the worker: no step longer than a day, 160 points and more; '
      + 'the panel\'s Maximum step, 5 days, in its place where it is given',
    /^MAX_STEP = 1\b/m.test(zText) && hModel <= 1 + 1e-9 && nModel >= 161 && hPanel > 1 + 1e-9 && hPanel <= 5 + 1e-9,
    `${nModel} points, the longest step ${hModel.toFixed(4)} d; with the panel's 5 d ${nPanel} points, ${hPanel.toFixed(4)} d`);
  }
  /*
    Redox zones along a plume, the redoxplume example, run by the worker as the page runs it. Every point shown is the
    speciation of its totals: re-speciated from what it shows, each settles at its first evaluation, its relations and
    totals holding there to rounding; the one polishing step moves a trace species by what the point's conditioning
    lets it, 7e-7 of nitrate at 1e-25 where a front is passing, far from what a point not settled moved. A mineral
    the run holds at none is read back as none: FeS(ppt) in the oxic water ahead of the plume is 1e-33 or so in the state,
    the arithmetic's, and read as some it was held at saturation where it cannot be -- the speciation did not settle, and
    the point was shown as the solver left it. And the zones from the inlet, by the pe: methane below -2.5, iron below 3,
    manganese below 10, nitrate below 12.5, the oxygen ahead of them; each moving downstream from day 20 to 30 to 40.
  */
  {
    const pText = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES.find((e) => e.id === 'redoxplume').text;
    const pm = RtmModel.compile(pText);
    const pns = pm.speciesNames.length;
    let got = null;
    handleRtmMessage({ type: 'run', id: 13, text: pText, solver: { ...solverSw, rtol: 1e-6 } }, (msg) => {
      if (msg.type === 'result' || msg.type === 'error') got = msg;
    });
    const ran = !!got && got.type === 'result' && got.width === 30 * pns;
    const shown = (i) => Float64Array.from(got.states.subarray(i * got.width, (i + 1) * got.width));
    let moved = 0;
    let unsettled = 0;
    let late = 0;
    let atShown = 0;
    let read = 0;
    const zones = [];
    if (ran) {
      const every = [];
      for (let i = 0; i < got.n; i += 10) every.push(i);
      if (every[every.length - 1] !== got.n - 1) every.push(got.n - 1);
      for (const i of every) {
        const y = shown(i);
        read++;
        let sp = null;
        try { sp = RtmModel.speciate(pm, y, { t: got.t[i] }); } catch (e) { sp = null; }
        if (!sp || sp.cells.some((c) => !c.converged)) { unsettled++; continue; }
        for (const c of sp.cells) { if (c.iterations > 1) late++; atShown = Math.max(atShown, c.residual); }
        for (let k = 0; k < y.length; k++) {
          const isMin = !!pm.mineral[k % pns];
          if (!isMin && !(y[k] > 1e-30)) continue;
          moved = Math.max(moved, Math.abs(sp.y[k] - y[k]) / (isMin ? Math.max(Math.abs(y[k]), 1e-9) : y[k]));
        }
      }
      const peQ = Int32Array.of(pm.quantities.findIndex((q) => q.key === 'pe'));
      const peOut = new Float64Array(1);
      const zoneOf = (pe) => (pe < -2.5 ? 'methane' : pe < 3 ? 'iron' : pe < 10 ? 'manganese' : pe < 12.5 ? 'nitrate' : 'oxygen');
      for (const day of [20, 30, 40]) {
        const i = got.t.findIndex((t) => t >= day - 1e-9);
        const y = shown(i);
        const z = Array.from({ length: 30 }, (_, c) => zoneOf(pm.quantitiesAt(y, got.t[i], c, peQ, peOut)[0]));
        const order = z.filter((v, c) => c === 0 || v !== z[c - 1]);
        zones.push({ day, order: order.join(' '), ends: order.map((v) => z.lastIndexOf(v) + 1) });
      }
    }
    const inOrder = zones.length === 3 && zones.every((zz) => zz.order === 'methane iron manganese nitrate oxygen');
    const downstream = inOrder && [0, 1, 2, 3].every((q) => zones[0].ends[q] < zones[1].ends[q] && zones[1].ends[q] < zones[2].ends[q]);
    check('redox zones along a plume, the example run as the page runs it: every tenth point shown is its own speciation, '
      + 're-speciated from what it shows settling at its first evaluation -- a mineral the run holds at none, FeS in the oxic '
      + 'water, read back as none and not as the arithmetic\'s 1e-33 of it -- and the zones from the inlet by the pe, methane, '
      + 'iron, manganese, nitrate, the oxygen, each moving downstream from day 20 to 30 to 40',
    ran && unsettled === 0 && late === 0 && atShown < 1e-12 && moved < 1e-4 && read > 300 && inOrder && downstream,
    ran ? `${got.n} points, ${read} read: ${unsettled} unsettled, ${late} cells past their first evaluation, the relations and `
      + `totals holding at the points shown to ${atShown.toExponential(1)}, the polishing step moving them by ${moved.toExponential(1)}; `
      + zones.map((zz) => `day ${zz.day}: ${zz.order} to ${zz.ends.join(', ')} m`).join('; ')
      : (got ? got.error : 'no reply'));
  }
  /*
    The water as PHREEQC lists it, as the worker answers the Composition tab (listing): the redox zones example's water at
    its last stored point -- each species' ln gamma, every quantity, each phase's log IAP and log K -- each phase's SI
    the quantity's, and under Davies every ion of one charge with one gamma; a model without ACTIVITY, the carbonate
    example, every gamma 1; and a run the worker does not have, said so, for the page to send it.
  */
  {
    const exs = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES;
    const listed = (id) => {
      const text = exs.find((e) => e.id === id).text;
      let run = null;
      handleRtmMessage({ type: 'run', id: 14, text, solver: { ...solverSw, rtol: 1e-6 } }, (msg) => { if (msg.type === 'result') run = msg; });
      let li = null;
      handleRtmMessage({ type: 'listing', id: 15, runKey: run.runKey, index: run.n - 1, cell: 0 }, (msg) => { li = msg; });
      return { m: RtmModel.compile(text), li };
    };
    const z = listed('redoxzones');
    const siOff = Math.max(...z.li.phases.map((p) => Math.abs(p.logIAP - p.logK
      - z.li.values[z.m.quantities.findIndex((q) => q.key === `SI(${p.name})`)])));
    const byCharge = new Map();
    for (const nm of z.m.composition ? z.m.speciesNames : []) {
      const k = z.m.speciesNames.indexOf(nm);
      const charge = /([+-])(\d*)$/.exec(nm);
      if (!charge || nm === 'e-') continue;
      const zc = (charge[1] === '+' ? 1 : -1) * (Number(charge[2]) || 1);
      if (!byCharge.has(zc)) byCharge.set(zc, []);
      byCharge.get(zc).push(z.li.lnG[k]);
    }
    const spread = Math.max(...[...byCharge.values()].map((g) => Math.max(...g) - Math.min(...g)));
    const c = listed('carbonate');
    let missing = null;
    handleRtmMessage({ type: 'listing', id: 16, runKey: 99999, index: 0, cell: 0 }, (msg) => { missing = msg; });
    check('the water as PHREEQC lists it, as the worker answers the Composition tab: a ln gamma for each species and every '
      + 'quantity; each phase\'s log IAP less its log K its SI, the redox zones example\'s pyrolusite, ferrihydrite and FeS; '
      + 'under Davies every ion of one charge one gamma; without ACTIVITY every gamma 1; a run the worker has not, said so',
    z.li.type === 'listing' && z.li.lnG.length === z.m.speciesNames.length && z.li.values.length === z.m.quantities.length
      && z.li.phases.length >= 3 && siOff < 1e-12 && spread < 1e-12 && byCharge.size >= 4 && Math.abs(z.li.tc - 25) < 1e-12
      && [...c.li.lnG].every((v) => v === 0) && missing && missing.missing === true,
    `${z.li.phases.map((p) => `${p.name} SI ${(p.logIAP - p.logK).toFixed(3)}`).join(', ')}; SI off by ${siOff.toExponential(1)}; `
      + `${byCharge.size} charges, gamma apart within one by ${spread.toExponential(1)}; ${missing ? JSON.stringify(missing) : 'no reply'}`);
  }
  /*
    A budget over the run, as the worker answers the Composition tab (budget): what the column holds of an element or a
    species at each stored point, weighed by capacity and water as the model's own balance is, and what crosses each end.
    What no reaction makes or takes closes: a tracer, a tracer into the rock matrix (its rock band), the calcium of the
    acid column between the water and the calcite. A batch's carbon made by its source, 1e-5 a day for 160 days. And at
    the steady state of a decaying nuclide (on its inventory, R = 10), what comes in less what goes out is what decays,
    k times what the column holds -- the weights against the fluxes through the ends, no summing over stored points in it.
  */
  {
    const exs = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES;
    const budgetOf = (id, of) => {
      let run = null;
      handleRtmMessage({ type: 'run', id: 21, text: exs.find((e) => e.id === id).text, solver: { ...solverSw, rtol: 1e-6 } },
        (msg) => { if (msg.type === 'result') run = msg; });
      let b = null;
      handleRtmMessage({ type: 'budget', id: 22, runKey: run.runKey, of }, (msg) => { b = msg; });
      return { run, b };
    };
    const closes = ({ b }) => {
      let scale = 0;
      let off = 0;
      for (let i = 0; i < b.total.length; i++) {
        scale = Math.max(scale, Math.abs(b.total[i]), Math.abs(b.total[0] + b.cumIn[i]));
        off = Math.max(off, Math.abs(b.byReactions[i]));
      }
      return off / scale;
    };
    const names = ({ b }) => b.bands.map((x) => x.name).join(' | ');
    const tr = budgetOf('tracer', { kind: 'species', name: 'X' });
    const mt = budgetOf('matrixtracer', { kind: 'species', name: 'X' });
    const ac = budgetOf('acidcolumn', { kind: 'element', name: 'Ca' });
    const rz = budgetOf('redoxzones', { kind: 'element', name: 'C' });
    const nu = budgetOf('nuclideindices', { kind: 'species', name: 'Nuclide' });
    const L = (x) => x.run.n - 1;
    const rock = mt.b.bands.find((x) => x.name === 'in the rock');
    const calcite = ac.b.bands.find((x) => x.name === 'Calcite');
    const k = 0.023104906;
    const steady = (nu.b.fluxIn[L(nu)] - nu.b.fluxOut[L(nu)]) / (k * nu.b.total[L(nu)]) - 1;
    check('a budget over the run, as the worker answers the Composition tab: what no reaction makes or takes closes -- a '
      + 'tracer, a tracer into the rock with its rock band, the acid column\'s calcium between the water and the calcite as '
      + 'the calcite dissolves; a batch\'s carbon made by its source, 1e-5 a day for 160 days; and at a decaying nuclide\'s '
      + 'steady state what comes in less what goes out is k times what the column holds',
    closes(tr) < 1e-6 && closes(mt) < 1e-5 && closes(ac) < 1e-5 && rock && rock.values[L(mt)] > 0
      && names(ac) === 'in the water | Calcite' && calcite.values[L(ac)] < calcite.values[0]
      && !rz.b.transport && Math.abs(rz.b.byReactions[L(rz)] / 1.6e-3 - 1) < 1e-9 && Math.abs(steady) < 1e-8,
    `tracer ${closes(tr).toExponential(1)}; into the rock ${closes(mt).toExponential(1)} (${names(mt)}); calcium `
      + `${closes(ac).toExponential(1)} (${names(ac)}, the calcite ${calcite ? `${calcite.values[0].toExponential(3)} to `
      + `${calcite.values[L(ac)].toExponential(3)}` : 'none'}); the batch's carbon made ${rz.b.byReactions[L(rz)].toExponential(6)}; `
      + `the nuclide's steady balance off by ${steady.toExponential(1)}`);
  }
  /*
    A nuclide's name is one atom of its element: an element and a number between 0.75 and 1.35 times its atomic weight
    is a mass number (U238, Ra226+2, C14, Cl36, He4; and tritium's H3), where a formula's count is far from it (O2, N2, H2,
    S8, C60, CaCl2). The U-238 chain's uranium then the sum of its two nuclides' amounts -- tot(U) by hand, and the budget
    of the element the budgets of U238 and U234 added -- and the far field's and the release history's nuclides each one.
  */
  {
    const read = (nm) => { const m = RtmModel.elementsOf(nm); return m ? [...m].map(([e, c]) => `${e}${c === 1 ? '' : c}`).join(' ') : 'null'; };
    const names = { U238: 'U', 'Ra226+2': 'Ra', C14: 'C', Cl36: 'Cl', He4: 'He', H3: 'H', I129: 'I', Cs135: 'Cs', O2: 'O2', N2: 'N2',
      H2: 'H2', S8: 'S8', C60: 'C60', CaCl2: 'Ca Cl2', 'UO2+2': 'U O2', U3: 'U3', H2O: 'H2 O' };
    const misread = Object.entries(names).filter(([nm, want]) => read(nm) !== want).map(([nm, want]) => `${nm} as ${read(nm)}, not ${want}`);
    const exs = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES;
    const chain = exs.find((e) => e.id === 'u238chain').text;
    const cm = RtmModel.compile(chain);
    const cy = cm.toConcentrations ? cm.toConcentrations(cm.initialState()) : cm.initialState();
    // A state of its own, every nuclide some: tot(U) the two uranium nuclides', each once.
    const cs = Float64Array.from(cy, (v, i) => (i < cm.speciesNames.length ? 0.1 * (i + 1) : v));
    const totU = new Float64Array(1);
    cm.quantitiesAt(cs, 0, 0, Int32Array.of(cm.quantities.findIndex((q) => q.key === 'tot(U)')), totU);
    const byHand = cs[cm.speciesNames.indexOf('U238')] + cs[cm.speciesNames.indexOf('U234')];
    let run = null;
    handleRtmMessage({ type: 'run', id: 31, text: chain, solver: { ...solverSw, rtol: 1e-6 } }, (msg) => { if (msg.type === 'result') run = msg; });
    const budget = (of) => { let b = null; handleRtmMessage({ type: 'budget', id: 32, runKey: run.runKey, of }, (msg) => { b = msg; }); return b; };
    const bU = budget({ kind: 'element', name: 'U' });
    const b8 = budget({ kind: 'species', name: 'U238' });
    const b4 = budget({ kind: 'species', name: 'U234' });
    let apart = 0;
    for (let i = 0; i < run.n; i++) {
      apart = Math.max(apart, Math.abs(bU.total[i] - b8.total[i] - b4.total[i]) / Math.max(bU.total[i], 1e-300),
        Math.abs(bU.cumOut[i] - b8.cumOut[i] - b4.cumOut[i]) / Math.max(bU.cumOut[i], 1e-300));
    }
    const once = (id, el) => {
      const m = RtmModel.compile(exs.find((e) => e.id === id).text);
      const e = m.composition.elements.find((x) => x.el === el);
      return e ? e.terms.map(([k, c]) => `${m.speciesNames[k]}x${c}`).join(' ') : 'none';
    };
    const fr = [once('farfield', 'Ra'), once('releasehistory', 'I'), once('releasehistory', 'Cs')];
    check('a nuclide\'s name is one atom of its element -- U238, Ra226+2, C14, Cl36, He4, I129, Cs135, tritium\'s H3 -- and a '
      + 'formula\'s count stays its count, O2, H2, S8, C60, CaCl2; the U-238 chain\'s tot(U) its two uranium nuclides\' sum, '
      + 'its uranium\'s budget theirs added, and the far field\'s and the release history\'s nuclides each one atom',
    !misread.length && Math.abs(totU[0] / byHand - 1) < 1e-15 && apart < 1e-12
      && fr.join(' | ') === 'Ra226x1 | I129x1 | Cs135x1',
    `${misread.join(', ') || 'every name as it should be'}; tot(U) ${totU[0]} for ${byHand}; the budgets apart by `
      + `${apart.toExponential(1)}; ${fr.join(' | ')}`);
  }
  /*
    The plume's start with more calcite. Only a relation that holds places a species that starts at none: FeS(ppt) at none
    in the oxic water once put Fe+2 at e^302, capped at the largest total, every iron species after it, and the capped
    steps took 95 iterations a cell at 5e-3 mol/kgw of calcite and did not settle in a hundred at 1e-2 -- reported as a
    singular matrix, which it never was. From 5e-3 to 1 mol/kgw each starts in a few iterations a cell, and each cell's
    water takes the same calcite whatever there is of it. Where a start does not settle (three iterations allowed), it
    says so, not that the matrix is singular.
  */
  {
    const pText = require(path.join(jsDir, 'rtm-examples.js')).RTM_EXAMPLES.find((e) => e.id === 'redoxplume').text;
    const withCalcite = (cal) => pText.replace(/^Calcite +5e-3 +mineral/m, `Calcite      ${cal}     mineral`);
    const starts = ['5e-3', '1e-2', '1e-1', '1'].map((cal) => {
      try {
        const m = RtmModel.compile(withCalcite(cal));
        const y = m.initialState();
        const k = m.speciesNames.indexOf('Calcite');
        return { cal, its: Math.max(...m.speciated.map((c) => c.iterations)), took: Number(cal) - y[k] };
      } catch (e) { return { cal, error: e.message }; }
    });
    const ran = starts.every((r) => !r.error);
    const same = ran && starts.every((r) => Math.abs(r.took / starts[0].took - 1) < 1e-9);
    // Without its reaction and EQUILIBRATE, the electron at a pe: the start speciated by itself, three iterations allowed.
    const bare = withCalcite('1e-2').replace(/^EQUILIBRATE = always$/m, '').replace(/<PARAMETERS>[\s\S]*$/, '')
      .replace(/^e- +electron$/m, 'e-           electron pe=13');
    let said = '';
    try { RtmModel.speciate(RtmModel.compile(bare), undefined, { maxIter: 3 }); } catch (e) { said = e.message; }
    check('the plume\'s start with more calcite, 5e-3 to 1 mol/kgw: each compiles and starts in a few iterations a cell, a '
      + 'mineral at none placing no species, and each cell\'s water takes the same calcite whatever there is of it; a start '
      + 'that does not settle says so, not that the matrix is singular',
    ran && starts.every((r) => r.its <= 10) && same && Math.abs(starts[0].took - 7.43e-4) < 1e-6
      && /^The speciation does not settle in cell 0, neither with the minerals it starts with nor with any one of them gone/.test(said),
    starts.map((r) => (r.error ? `${r.cal}: ${r.error}` : `${r.cal}: ${r.its} iterations, ${r.took.toExponential(5)} mol taken`)).join('; ')
      + ` | ${said}`);
  }
  let swReply = null;
  handleRtmMessage({ type: 'sweep', id: 1, text: decay, solver: solverSw, vary: [{ kind: 'parameter', name: 'kk' }, { kind: 'setting', name: 'TEND' }],
    values: [[0.1, 0.2, 0.4], [10, -5]], cell: 0 }, (msg) => { if (msg.type !== 'progress') swReply = msg; });
  let direct = null;
  handleRtmMessage({ type: 'run', id: 2, text: RtmModel.withValue(RtmModel.withValue(decay, { kind: 'parameter', name: 'kk' }, 0.2),
    { kind: 'setting', name: 'TEND' }, 10), solver: solverSw }, (msg) => { if (msg.type === 'result') direct = msg; });
  const okRuns = swReply.runs.filter((r) => r.ok);
  const worstDecay = Math.max(...okRuns.map((r) => Math.abs(r.cellStates[(r.m - 1) * 2] / Math.exp(-r.values[0] * r.values[1]) - 1)));
  const second = swReply.runs[1];
  check('  a sweep of a parameter and a setting, every pair run: A decays as exp(-kk t) in each, the same to the bit as the text '
    + 'with those numbers run by itself, and a TEND below zero refused for its runs alone',
  okRuns.length === 3 && worstDecay < 1e-6 && second.cellStates[(second.m - 1) * 2] === direct.states[(direct.n - 1) * 2]
    && swReply.runs.slice(3).every((r) => !r.ok && /simulated time must be positive/.test(r.error)),
  `A within ${worstDecay.toExponential(1)} of exp(-kk t); ${swReply.runs.filter((r) => !r.ok).length} refused: ${(swReply.runs[3] || {}).error}`);

  // The draws of the uncertainty bands: runs given one by one, each read at the same times.
  let unReply = null;
  const unTimes = [0, 1, 2.5, 5, 10];
  handleRtmMessage({ type: 'sweep', id: 4, text: decay, solver: { ...solverSw, rtol: 1e-10 }, vary: [{ kind: 'parameter', name: 'kk' }],
    combos: [[0.1], [0.3]], times: unTimes, cell: 0 }, (msg) => { if (msg.type !== 'progress') unReply = msg; });
  let unDirect = null;
  const unModel = RtmModel.compile(RtmModel.withValue(decay, { kind: 'parameter', name: 'kk' }, 0.3));
  unDirect = FacsimileODE.runModel(unModel, { solver: 'ndf', tend: 10, rtol: 1e-10, atol: 1e-20, nonNegative: true, outputTimes: unTimes,
    maxPoints: 4, stagnationTol: 0.5 });
  const unWorst = Math.max(...unReply.runs.flatMap((r) => unTimes.map((t, j) => Math.abs(r.cellStates[j * 2] - Math.exp(-r.values[0] * t)))));
  check('  runs given one by one, as the uncertainty bands draw them, each read at the same times: A is exp(-kk t) at each, '
    + 'the same to the bit as the text run by itself at those times',
  unReply.runs.length === 2 && unReply.runs.every((r) => r.ok && r.m === unTimes.length && unTimes.every((t, j) => r.t[j] === t))
    && unWorst < 1e-8 && unTimes.every((t, j) => unReply.runs[1].cellStates[j * 2] === unDirect.grid.y[j][0]),
  `within ${unWorst.toExponential(1)} of exp(-kk t)`);

  // FITTING: the numbers moved until the run meets what <DATA> measured, as the worker fits them.
  const fitOf = (text, params, extra = {}) => {
    let reply = null;
    handleRtmMessage({ type: 'fit', id: 3, text, solver: { ...solverSw, rtol: 1e-9 }, params, ...extra },
      (msg) => { if (msg.type !== 'progress') reply = msg; });
    return reply;
  };
  const fts = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const decayData = (rows) => `${decay}\n<DATA>\ntime  A  cell = 0\n${rows.join('\n')}\n`;
  const fExact = fitOf(decayData(fts.map((t) => `${t} ${Math.exp(-0.25 * t)}`)), [{ kind: 'parameter', name: 'kk', start: 0.1 }]);
  // The same with a pattern of noise, whose answer is worked out by hand: the residual, log10(exp(-kk t)/d), is straight
  // in kk, so kk = -sum(t ln d)/sum(t^2), and in log10 kk the standard error is s/(kk sqrt(sum t^2)).
  const fNoise = [0.02, -0.015, 0.01, -0.02, 0.005, 0.018, -0.012, 0, -0.008, 0.016];
  const fd = fts.map((t, i) => Math.exp(-0.25 * t) * 10 ** fNoise[i]);
  const fNoisy = fitOf(decayData(fts.map((t, i) => `${t} ${fd[i]}`)), [{ kind: 'parameter', name: 'kk', start: 0.1 }]);
  const St2 = fts.reduce((acc, t) => acc + t * t, 0);
  const kHat = -fts.reduce((acc, t, i) => acc + t * Math.log(fd[i]), 0) / St2;
  const sHat = Math.sqrt(fts.reduce((acc, t, i) => acc + ((-kHat * t - Math.log(fd[i])) / Math.LN10) ** 2, 0) / (fts.length - 1));
  const seHat = sHat / (kHat * Math.sqrt(St2));
  const fTwo = fitOf(`${decay}\n<DATA>\ntime  A  cell = 0\n${fts.map((t) => `${t} ${2 * Math.exp(-0.3 * t)}`).join('\n')}\n`,
    [{ kind: 'parameter', name: 'kk', start: 0.1 }, { kind: 'initial', name: 'A', start: 1 }]);
  check('a fit: kk from a decay measured exactly, to the solver\'s tolerance; from one measured with noise, kk and its '
    + 'standard error as worked out by hand; kk and the start of A together',
  fExact.type === 'fit' && Math.abs(fExact.params[0].value / 0.25 - 1) < 1e-7 && Math.abs(fNoisy.params[0].value / kHat - 1) < 1e-6
    && Math.abs(fNoisy.params[0].se / seHat - 1) < 1e-4 && Math.abs(fNoisy.sd / sHat - 1) < 1e-6
    && Math.abs(fTwo.params[0].value / 0.3 - 1) < 1e-7 && Math.abs(fTwo.params[1].value / 2 - 1) < 1e-7,
  `kk ${fExact.params[0].value} in ${fExact.runs} runs; noisy ${fNoisy.params[0].value} for ${kHat}, se ${fNoisy.params[0].se} for `
    + `${seHat}; two ${fTwo.params.map((p) => p.value.toPrecision(9)).join(', ')}`);
  // A relation's log K and a reaction's own constant: B over A is K, the total grows by q a second.
  const pair = (logK, q) => '<SETTINGS>\nMODE = batch\nTEND = 10\nEQUILIBRATE = always\n\n<SPECIES>\nA  1e-3\nB  1e-3\n\n'
    + `<EQUILIBRIUM>\nA <=> B, logK = ${logK}\n\n<REACTIONS>\n=> A, r = q, q = ${q}\n`;
  const K = 10 ** 0.7;
  const fPair = fitOf(`${pair(0, 1e-3)}\n<DATA>\ntime  A  B  cell = 0\n${fts.map((t) => {
    const T = 2e-3 + 2e-3 * t;
    return `${t} ${T / (1 + K)} ${(T * K) / (1 + K)}`;
  }).join('\n')}\n`, [{ kind: 'logK', name: 'A <=> B', start: 0 }, { kind: 'rate', name: '=> A | q', start: 1e-3 }]);
  // Along a column: a tracer's front at one time, the velocity fitted, the data the page's own at the cells' centres.
  const front = (v) => `<SETTINGS>\nMODE = transport\nCELLS = 20\nLENGTH = 1\nVELOCITY = ${v}\nADVECTION = 1\nDIFFUSION = 1\n`
    + 'LEFT = robin\nRIGHT = free\nTEND = 2e5\n\n<SPECIES>\nX  0  D=1e-7  left=1\n';
  const fm = RtmModel.compile(front(2e-6));
  const fr = FacsimileODE.runModel(fm, { solver: 'ndf', rtol: 1e-10, atol: 1e-20, tend: 2e5, nonNegative: true, outputTimes: [2e5] });
  const fy = fr.grid.y[0];
  const fFront = fitOf(`${front(1e-6)}\n<DATA>\ndistance  X  at = 2e5\n${Array.from(fm.grid.centres).map((x, i) => `${x} ${fy[i]}`)
    .filter((_, i) => i % 2 === 0 && fy[i] > 1e-6).join('\n')}\n`, [{ kind: 'setting', name: 'VELOCITY', start: 1e-6 }]);
  check('  a relation\'s log K and a reaction\'s constant fitted together; a velocity fitted to a front measured along the '
    + 'column at one time', fPair.type === 'fit' && Math.abs(fPair.params[0].value - 0.7) < 1e-7
    && Math.abs(fPair.params[1].value / 2e-3 - 1) < 1e-7 && fFront.type === 'fit' && Math.abs(fFront.params[0].value / 2e-6 - 1) < 1e-6,
  `log K ${fPair.params[0].value}, q ${fPair.params[1].value}; velocity ${fFront.params[0].value} in ${fFront.runs} runs`);
  const refuseFit = (text, params, extra) => { const r = fitOf(text, params, extra); return r.type === 'error' ? r.error : ''; };
  const exactText = decayData(fts.map((t) => `${t} ${Math.exp(-0.25 * t)}`));
  const badFit = [
    ['a start not above zero for a number fitted in its logarithm', refuseFit(exactText, [{ kind: 'parameter', name: 'kk', start: 0 }]),
      /fitted in its logarithm, so that it stays above zero/],
    ['no column to fit to', refuseFit(exactText, [{ kind: 'parameter', name: 'kk', start: 0.1 }], { columns: ['B'] }),
      /no values of the columns asked for/],
    ['a value after the run ends', refuseFit(decayData(['20 0.1']), [{ kind: 'parameter', name: 'kk', start: 0.1 }]),
      /after the run ends at 10/],
    ['a number that is not there', refuseFit(exactText, [{ kind: 'parameter', name: 'q', start: 0.1 }]), /no parameter q/],
  ];
  const badFitOff = badFit.filter(([, got, re]) => !re.test(got));
  check(`  and refused, each with its reason: ${badFit.map(([w]) => w).join(', ')}`, !badFitOff.length,
    badFitOff.map(([w, got]) => `${w}: "${got}"`).join(' | '));
  check('  alk(CO3), the carbonate\'s alkalinity, and tot(SO4) where some of the sulfur is not sulfate, by hand',
    ![...twoQ].some((x) => x < 0) && Math.abs(twoV[0] / alkWant - 1) < 1e-14
    && Math.abs(twoV[1] / (ci('SO4-2') + ci('CaSO4')) - 1) < 1e-14 && Math.abs(twoV[2] - twoV[1] - ci('HS-')) < 1e-18,
  `${[...twoQ].join(',')}: ${[...twoV].join(', ')} for ${alkWant}`);

  /*
    THE BOUNDARIES OF A MAP, found between the grid's points by the worker.
    Without activity coefficients each of iron's species is a line in pH and
    pe -- log(C/C(Fe+2)) = a + b pH + c pe, from the log Ks -- so every
    boundary is a straight line and every point where three meet is where two
    of them cross. Grids with a boundary along a grid line, with the point
    where three meet on a point of the grid, and one of 3 x 3 whose middle is
    that point.
  */
  const askW = (msg) => {
    let reply = null;
    handleRtmMessage(msg, (m) => { if (m.type !== 'progress') reply = m; });
    if (reply.type === 'error') throw new Error(reply.error);
    return reply;
  };
  const ironText = '<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n\n<SPECIES>\nH+  1e-7\nOH-  1e-7\ne-  electron  pe=4\n'
    + 'Na+  1e-3\nCl-  1e-3\nFe+2  1e-6\nFe+3  0\nFeOH+  0\nFeOH+2  0\nFe(OH)2+  0\n\n<EQUILIBRIUM>\n <=> H+ + OH-,  logK = -14\n'
    + 'Fe+2 <=> Fe+3 + e-,  logK = -13.02\nFe+2 + H2O <=> FeOH+ + H+,  logK = -9.5\nFe+3 + H2O <=> FeOH+2 + H+,  logK = -2.19\n'
    + 'Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,  logK = -5.67\n';
  const ironLine = { 'Fe+2': [0, 0, 0], 'Fe+3': [-13.02, 0, 1], 'FeOH+': [-9.5, 1, 0], 'FeOH+2': [-15.21, 1, 1], 'Fe(OH)2+': [-18.69, 2, 1] };
  const ironModel = RtmModel.compile(ironText);
  const ironTerms = ironModel.composition.elements.find((e) => e.el === 'Fe').terms.filter((tm) => tm[2] === 'water');
  const ironName = (q) => ironModel.speciesNames[ironTerms[q][0]];
  // Where two lines cross, the point where three fields meet.
  const crossOf = (A, B, C) => {
    const m00 = A[1] - B[1];
    const m01 = A[2] - B[2];
    const m10 = B[1] - C[1];
    const m11 = B[2] - C[2];
    const v0 = B[0] - A[0];
    const v1 = C[0] - B[0];
    const det = m00 * m11 - m01 * m10;
    return [(v0 * m11 - m01 * v1) / det, (m00 * v1 - v0 * m10) / det];
  };
  const mapOf = (text, axes, criterion) => {
    const g = askW({ type: 'diagram', id: 5, text, at: 'start', cell: 0, axes });
    return askW({ type: 'diagramBounds', id: 6, text, at: 'start', cell: 0, axes, grid: g.states, criterion });
  };
  const ironGrids = [[0, 12, 11, -6, 18, 9], [0, 12, 101, -6, 18, 81], [0.99, 12.99, 101, -4.98, 19.02, 81], [1.19, 3.19, 3, 12.02, 14.02, 3]];
  const ironOut = ironGrids.map(([x0, x1, n1, y0, y1, n2]) => {
    const b = mapOf(ironText, [{ kind: 'pH', from: x0, to: x1, n: n1 }, { kind: 'pe', from: y0, to: y1, n: n2 }],
      { kind: 'predominance', terms: ironTerms.map(([k, n]) => [k, n]) });
    let line = 0;
    for (const ln of b.lines) {
      const A = ironLine[ironName(ln.a)];
      const B = ironLine[ironName(ln.b)];
      ln.x.forEach((x, q) => {
        line = Math.max(line, Math.abs(A[0] - B[0] + (A[1] - B[1]) * x + (A[2] - B[2]) * ln.y[q]) / Math.hypot(A[1] - B[1], A[2] - B[2]));
      });
    }
    let meet = 0;
    for (const jn of b.junctions) {
      const [px, py] = crossOf(...jn.labels.map((q) => ironLine[ironName(q)]));
      meet = Math.max(meet, Math.abs(px - jn.x), Math.abs(py - jn.y));
    }
    const area = b.fields.reduce((s, f) => s + f.area, 0) / Math.abs((x1 - x0) * (y1 - y0)) - 1;
    const pairs = b.lines.map((ln) => [ironName(ln.a), ironName(ln.b)].sort().join('|')).sort();
    return { n: `${n1} x ${n2}`, line, meet, area, solved: b.junctions.every((jn) => jn.solved), nj: b.junctions.length,
      pairs: [...new Set(pairs)].join(' '), unsolved: b.unsolved };
  });
  const ironPairs = 'Fe(OH)2+|Fe+2 Fe(OH)2+|FeOH+ Fe(OH)2+|FeOH+2 Fe+2|Fe+3 Fe+2|FeOH+ Fe+2|FeOH+2 Fe+3|FeOH+2';
  check('the boundaries of a Pourbaix map of iron without activity coefficients: every point of every boundary on the straight '
    + 'line its two species\' log Ks give, to 1e-10 in pH and pe, every point where three meet where two of those lines cross, '
    + 'to 1e-12, and the fields\' areas the frame\'s -- on a grid of 11 x 9, one with a boundary along a grid line, one with '
    + 'the point where three meet on a point of it, and one of 3 x 3 whose middle is that point',
  ironOut.every((o) => o.line < 1e-10 && o.meet < 1e-12 && Math.abs(o.area) < 1e-12 && o.solved && !o.unsolved)
    && ironOut.slice(0, 3).every((o) => o.pairs === ironPairs && o.nj === 3),
  ironOut.map((o) => `${o.n}: lines within ${o.line.toExponential(1)}, ${o.nj} meeting points within ${o.meet.toExponential(1)}, `
    + `area ${o.area.toExponential(1)}`).join('; ') + ` | ${ironOut[0].pairs}`);

  // A phase map: calcium's total held, carbonate's and sulfate's activities varied, no complexes: SI(Calcite) is
  // log Ca + la(CO3-2) + 8.48, SI(Gypsum) log Ca + la(SO4-2) + 4.58, and the boundaries are where either is zero or they meet.
  const phaseText = '<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n\n<SPECIES>\nH+  1e-7\nOH-  1e-7\nCa+2  1e-2\n'
    + 'Cl-  2e-2\nCO3-2  1e-6\nSO4-2  1e-4\n\n<EQUILIBRIUM>\n <=> H+ + OH-,  logK = -14\n\n<PHASES>\n'
    + 'Calcite <=> Ca+2 + CO3-2,  logK = -8.48\nGypsum <=> Ca+2 + SO4-2 + 2 H2O,  logK = -4.58\n';
  const phaseLine = { 'SI(Calcite)|none': [6.48, 1, 0], 'SI(Gypsum)|none': [2.58, 0, 1], 'SI(Calcite)|SI(Gypsum)': [3.9, 1, -1] };
  const pb = mapOf(phaseText, [{ kind: 'la', species: 'CO3-2', from: -10, to: -2, n: 41 }, { kind: 'la', species: 'SO4-2', from: -6, to: -1, n: 26 }],
    { kind: 'phase', keys: ['SI(Calcite)', 'SI(Gypsum)'] });
  const phaseName = (q) => ['SI(Calcite)', 'SI(Gypsum)', 'none'][q];
  let phaseWorst = 0;
  const phasePairs = [];
  for (const ln of pb.lines) {
    const key = [phaseName(ln.a), phaseName(ln.b)].join('|');
    phasePairs.push(key);
    const L = phaseLine[key];
    ln.x.forEach((x, q) => { phaseWorst = Math.max(phaseWorst, Math.abs(L[0] + L[1] * x + L[2] * ln.y[q]) / Math.hypot(L[1], L[2])); });
  }
  const pj = pb.junctions[0];
  const phaseArea = pb.fields.reduce((s, f) => s + f.area, 0) / 40 - 1;
  check('  a mineral stability map without activity coefficients: calcite\'s and gypsum\'s boundaries with each other and with '
    + 'neither where their saturation indices say, to 1e-10, and the point all three meet, to 1e-12',
  phaseWorst < 1e-10 && pb.junctions.length === 1 && pj.solved && Math.abs(pj.x + 6.48) < 1e-12
    && Math.abs(pj.y + 2.58) < 1e-12 && Math.abs(phaseArea) < 1e-12 && phasePairs.length === 3,
  `${phasePairs.join(', ')} within ${phaseWorst.toExponential(1)}; meeting at (${pj && pj.x}, ${pj && pj.y}); area ${phaseArea.toExponential(1)}`);

  // Of the water as a run leaves it: the run kept, or sent again once the worker has let it go.
  let ranIron = null;
  handleRtmMessage({ type: 'run', id: 7, text: ironText, solver: solverSw }, (msg) => { if (msg.type === 'result') ranIron = msg; });
  const endAxes = [{ kind: 'pH', from: 0, to: 12, n: 11 }, { kind: 'pe', from: -6, to: 18, n: 9 }];
  const endCrit = { kind: 'predominance', terms: ironTerms.map(([k, n]) => [k, n]) };
  const endGrid = askW({ type: 'diagram', id: 8, text: ironText, at: 'end', cell: 0, axes: endAxes, runKey: ranIron.runKey });
  const endKept = askW({ type: 'diagramBounds', id: 9, text: ironText, at: 'end', cell: 0, axes: endAxes, runKey: ranIron.runKey,
    grid: endGrid.states, criterion: endCrit });
  const endGone = askW({ type: 'diagramBounds', id: 10, text: ironText, at: 'end', cell: 0, axes: endAxes, runKey: -1,
    grid: endGrid.states, criterion: endCrit });
  const endSent = askW({ type: 'diagramBounds', id: 11, text: ironText, at: 'end', cell: 0, axes: endAxes, runKey: -2,
    grid: endGrid.states, criterion: endCrit, t: ranIron.t, states: ranIron.states, n: ranIron.n, width: ranIron.width });
  const sameLines = (p, q) => JSON.stringify(p.lines) === JSON.stringify(q.lines) && JSON.stringify(p.junctions) === JSON.stringify(q.junctions);
  check('  of the water as a run leaves it: the boundaries of the run kept; asked of a run the worker no longer has, it says so, '
    + 'and with the run sent, the same to the bit', endKept.type === 'diagramBounds' && endKept.junctions.length === 3
    && endGone.missing === true && sameLines(endKept, endSent),
  `${endKept.lines.length} lines; ${JSON.stringify(endGone).slice(0, 60)}`);

  /*
    Eh: the electron's pe in volts, ln 10 RT/F times it at the water's
    temperature, with the R and F PHREEQC prints its redox couples' Eh with
    (RtmModel.ehPerPe; against what PHREEQC prints in test-phreeqc.js). As a
    quantity, in a column whose cells are at 10, 45 and 80 C and in a water
    warmed along the clock; measured, a column of <DATA>; on a map, the pe-pH
    map of iron with its pe in volts: every boundary on the line the log Ks
    give, a point's pe its Eh over the volts of a pe at the water's
    temperature -- at 25 C, and in the same water at 60 C, where the iron
    couple's boundary is at 13.02 pe as at 25 C and so higher in volts.
  */
  const perOf = (tk) => (Math.LN10 * 0.0083147 * tk) / 96.4935;
  const ehRedox = '<SPECIES>\nH+  1e-7\nOH-  1e-7\ne-  electron  pe=4\nFe+2  1e-6\nFe+3  0\n\n<EQUILIBRIUM>\n <=> H+ + OH-,  logK = -14\n'
    + 'Fe+2 <=> Fe+3 + e-,  logK = -13.02\n';
  const ehCol = RtmModel.compile('<SETTINGS>\nMODE = transport\nCELLS = 3\nLENGTH = 1\nDIFFUSION = 0\nLEFT = neumann\nRIGHT = neumann\n'
    + `TEND = 1\nEQUILIBRATE = always\nTEMPERATURE = Tc\n\n<PARAMETERS>\nTc all 10 + 35*i\n\n${ehRedox}`);
  const ehRamp = RtmModel.compile('<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\nTEMPERATURE = ramp(t)\n\n'
    + `<TABLE ramp>\n0 10\n1 90\n\n${ehRedox}\n<DATA>\ntime  Eh  pe  cell = 0\n0  0.21  3.9\n1  0.25  -\n`);
  // The pe and the Eh at each cell and time asked, the electron put at a pe of the test's own there.
  const ehAt = (m, cells, times, tkAt) => {
    const which = Int32Array.from(['pe', 'Eh'].map((k) => m.quantities.findIndex((q) => q.key === k)));
    const ie = m.speciesNames.indexOf('e-');
    const ns = m.speciesNames.length;
    let worst = 0;
    for (const cell of cells) {
      for (const t of times) {
        const c = Float64Array.from(m.toConcentrations ? m.toConcentrations(m.initialState()) : m.initialState());
        const pe = 13.3 - 4.1 * cell - 9.7 * t;
        c[cell * ns + ie] = 10 ** -pe;
        const out = new Float64Array(2);
        m.quantitiesAt(c, t, cell, which, out);
        const want = perOf(tkAt(cell, t)) * pe;
        worst = Math.max(worst, Math.abs(out[0] - pe), Math.abs(out[1] - want) / Math.abs(want));
      }
    }
    return worst;
  };
  const ehWorst = [ehAt(ehCol, [0, 1, 2], [0, 0.5], (cell) => 283.15 + 35 * cell),
    ehAt(ehRamp, [0], [0, 0.25, 0.5, 1], (cell, t) => 283.15 + 80 * t)];
  const ehQ = ehCol.quantities.find((q) => q.key === 'Eh');
  const ehKeys = ehCol.quantities.map((q) => q.key);
  const ehData = ehRamp.data[0];
  check('Eh, the electron\'s pe in volts at the water\'s temperature with PHREEQC\'s R and F: a quantity of the water beside '
    + 'the pe, in V, in a column whose cells are at 10, 45 and 80 C and in a water warmed along the clock from 10 to 90 C, '
    + 'to 1e-15; 0.059156 V a pe at 25 C; none without the electron; and a column of <DATA>',
  ehWorst.every((w) => w < 1e-15) && ehQ && ehQ.unit === 'V' && ehQ.axis === 'index' && ehQ.group === 'water'
    && ehKeys.indexOf('Eh') === ehKeys.indexOf('pe') + 1 && Math.abs(RtmModel.ehPerPe(298.15) - 0.059156031) < 1e-9
    && !RtmModel.compile(phaseText).quantities.some((q) => q.key === 'Eh')
    && ehData && ehData.columns.join(' ') === 'Eh pe' && ehData.rows.length === 2 && ehData.rows[1][2] === null,
  `worst ${ehWorst.map((w) => w.toExponential(1)).join(', ')}; ${ehQ && `${ehQ.key} ${ehQ.unit} ${ehQ.axis}`}; `
    + `${RtmModel.ehPerPe(298.15)} V a pe`);
  const ehMaps = [25, 60].map((tc) => {
    const per = perOf(tc + 273.15);
    const text = ironText.replace('EQUILIBRATE = always\n', `EQUILIBRATE = always\nTEMPERATURE = ${tc}\n`);
    const b = mapOf(text, [{ kind: 'pH', from: 0, to: 12, n: 101 }, { kind: 'Eh', from: -6 * per, to: 18 * per, n: 81 }],
      { kind: 'predominance', terms: ironTerms.map(([k, n]) => [k, n]) });
    let line = 0;
    let couple = NaN;
    for (const ln of b.lines) {
      const A = ironLine[ironName(ln.a)];
      const B = ironLine[ironName(ln.b)];
      // In pH and Eh, the pe the Eh over the volts of a pe.
      const norm = Math.hypot(A[1] - B[1], (A[2] - B[2]) / per);
      ln.x.forEach((x, q) => {
        line = Math.max(line, Math.abs(A[0] - B[0] + (A[1] - B[1]) * x + ((A[2] - B[2]) * ln.y[q]) / per) / norm);
      });
      if ([ironName(ln.a), ironName(ln.b)].sort().join('|') === 'Fe+2|Fe+3') couple = Math.max(...ln.y);
    }
    let meet = 0;
    for (const jn of b.junctions) {
      const [px, py] = crossOf(...jn.labels.map((q) => ironLine[ironName(q)]));
      meet = Math.max(meet, Math.abs(px - jn.x), Math.abs(py * per - jn.y));
    }
    const pairs = [...new Set(b.lines.map((ln) => [ironName(ln.a), ironName(ln.b)].sort().join('|')))].sort().join(' ');
    return { tc, per, line, meet, couple, pairs, nj: b.junctions.length,
      solved: b.junctions.every((jn) => jn.solved) && !b.unsolved };
  });
  const refusedAxes = (axes, text) => {
    try { askW({ type: 'diagram', id: 12, text, at: 'start', cell: 0, axes }); return ''; } catch (e) { return e.message; }
  };
  const ehBoth = refusedAxes([{ kind: 'pe', from: 0, to: 10, n: 3 }, { kind: 'Eh', from: 0, to: 0.5, n: 3 }], ironText);
  const ehNone = refusedAxes([{ kind: 'pH', from: 2, to: 12, n: 3 }, { kind: 'Eh', from: 0, to: 0.5, n: 3 }], phaseText);
  check('  a Pourbaix map over pH and Eh: every boundary on the line its two species\' log Ks give, a point\'s pe its Eh over '
    + 'the volts of a pe there, to 1e-10, every point where three meet to 1e-12 -- at 25 C, and in the same water at 60 C '
    + 'with the iron couple\'s boundary at 13.02 pe, 0.7702 V and 0.8606 V; an Eh beside a pe, or of a model without the '
    + 'electron, refused', ehMaps.every((o) => o.line < 1e-10 && o.meet < 1e-12 && o.solved && o.nj === 3 && o.pairs === ironPairs
    && Math.abs(o.couple - 13.02 * o.per) < 1e-10)
    && Math.abs(ehMaps[0].couple - 0.770211) < 1e-6 && Math.abs(ehMaps[1].couple - 0.860627) < 1e-6
    && /hold the same thing/.test(ehBoth) && /An Eh is the electron's, and the model has none/.test(ehNone),
  `${ehMaps.map((o) => `${o.tc} C: lines within ${o.line.toExponential(1)}, ${o.nj} meeting points within `
    + `${o.meet.toExponential(1)}, the couple at ${o.couple.toFixed(6)} V`).join('; ')} | "${ehBoth}" | "${ehNone}"`);

  /*
    ACTIVITY RATIOS, AND THE MOST STABLE PHASE PER MOLE OF AN ELEMENT, as
    Garrels and Christ draw silicate stability diagrams. Without activity
    coefficients, the water's activity 1, each phase's saturation index over
    its aluminium is, but for log a(Al+3)/a(H+)^3 which all of them share, a
    line in s = log a(H4SiO4) and r = log a(K+)/a(H+) from the log Ks:
    gibbsite -8.11, kaolinite s - 7.435/2, K-mica s + r/3 - 12.703/3,
    K-feldspar r + 3s - (22.7 - 20.573). Every boundary is then straight,
    the point where three meet is where two cross, and the map is the same
    whatever aluminium is dissolved. A phase's makeup comes from what it
    dissolves into, a mineral's from its relation; the ratio is held at each
    point over the pH the water has, under an activity model too.
  */
  const silSpecies = '<SPECIES>\nH+  1e-7\nOH-  1e-7\nK+  1e-4\nNa+  1e-3\nCl-  1.1e-3\nAl+3  1e-9\nAlOH+2  0\nAl(OH)2+  0\n'
    + 'Al(OH)3  0\nAl(OH)4-  0\nH4SiO4  1e-4\nH3SiO4-  0\n\n<EQUILIBRIUM>\n <=> H+ + OH-,  logK = -14\nAl+3 + H2O <=> AlOH+2 + H+,  logK = -5\n'
    + 'Al+3 + 2 H2O <=> Al(OH)2+ + 2 H+,  logK = -10.1\nAl+3 + 3 H2O <=> Al(OH)3 + 3 H+,  logK = -16.9\n'
    + 'Al+3 + 4 H2O <=> Al(OH)4- + 4 H+,  logK = -22.7\nH4SiO4 <=> H3SiO4- + H+,  logK = -9.83\n\n<PHASES>\n'
    + 'K_feldspar + 8 H2O <=> K+ + Al(OH)4- + 3 H4SiO4,  logK = -20.573\nKaolinite + 6 H+ <=> H2O + 2 H4SiO4 + 2 Al+3,  logK = 7.435\n'
    + 'Gibbsite + 3 H+ <=> Al+3 + 3 H2O,  logK = 8.11\nK_mica + 10 H+ <=> K+ + 3 Al+3 + 3 H4SiO4,  logK = 12.703\n'
    + 'Quartz + 2 H2O <=> H4SiO4,  logK = -3.98\n';
  const silText = `<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n\n${silSpecies}`;
  const silModel = RtmModel.compile(silText);
  const makeups = Object.fromEntries(silModel.quantities.filter((q) => q.makeup).map((q) => [q.key, JSON.stringify(q.makeup)]));
  const calciteMade = RtmModel.compile('<SETTINGS>\nMODE = batch\nTEND = 1\nEQUILIBRATE = always\n\n<SPECIES>\nCa+2  1e-3\nCO3-2  1e-3\n'
    + 'Calcite  1e-3  mineral\n\n<EQUILIBRIUM>\nCalcite <=> Ca+2 + CO3-2,  logK = -8.48\n').quantities.find((q) => q.key === 'SI(Calcite)');
  const silLine = { K_feldspar: [-2.127, 3, 1], Kaolinite: [-7.435 / 2, 1, 0], Gibbsite: [-8.11, 0, 0], K_mica: [-12.703 / 3, 1, 1 / 3] };
  const silKeys = ['SI(K_feldspar)', 'SI(Kaolinite)', 'SI(Gibbsite)', 'SI(K_mica)'];
  const silName = (q) => silKeys[q].slice(3, -1);
  const silMaps = [['1e-9', 1e-9], ['1e-12', 1e-12]].map(([al, alv]) => {
    const b = mapOf(silText.replace('Al+3  1e-9', `Al+3  ${al}`), [{ kind: 'la', species: 'H4SiO4', from: -6, to: -2, n: 41 },
      { kind: 'ratio', species: 'K+', from: 0, to: 10, n: 51 }], { kind: 'phase', keys: silKeys, per: [1, 2, 1, 3] });
    let line = 0;
    for (const ln of b.lines) {
      const A = silLine[silName(ln.a)];
      const B = silLine[silName(ln.b)];
      ln.x.forEach((x, q) => {
        line = Math.max(line, Math.abs(A[0] - B[0] + (A[1] - B[1]) * x + (A[2] - B[2]) * ln.y[q]) / Math.hypot(A[1] - B[1], A[2] - B[2]));
      });
    }
    let meet = 0;
    for (const jn of b.junctions) {
      const [px, py] = crossOf(...jn.labels.map((q) => silLine[silName(q)]));
      meet = Math.max(meet, Math.abs(px - jn.x), Math.abs(py - jn.y));
    }
    const pairs = [...new Set(b.lines.map((ln) => [silName(ln.a), silName(ln.b)].sort().join('|')))].sort().join(' ');
    const area = b.fields.reduce((sum, f) => sum + f.area, 0) / 40 - 1;
    return { al: alv, line, meet, pairs, area, junctions: b.junctions.map((jn) => [jn.x, jn.y]),
      none: b.fields.some((f) => f.label >= silKeys.length), solved: b.junctions.every((jn) => jn.solved) && !b.unsolved };
  });
  const quartz = mapOf(silText, [{ kind: 'la', species: 'H4SiO4', from: -6, to: -2, n: 41 }, { kind: 'ratio', species: 'K+', from: 0, to: 10, n: 51 }],
    { kind: 'phase', keys: ['SI(Quartz)'] });
  const quartzOff = Math.max(...quartz.lines.flatMap((ln) => ln.x.map((x) => Math.abs(x + 3.98))));
  check('a silicate stability map over log a(H4SiO4) and log a(K+)/a(H+), each phase per mole of aluminium: every boundary on '
    + 'the line the log Ks give, to 1e-10, gibbsite, kaolinite and K-mica meeting where two of them cross, to 1e-12, K-feldspar '
    + 'beside K-mica, no field of none; the same map with a thousand times less aluminium dissolved; quartz at saturation along '
    + 'log a(H4SiO4) = -3.98; each phase made of what it dissolves into, a mineral of its relation',
  silMaps.every((o) => o.line < 1e-10 && o.meet < 1e-12 && o.solved && !o.none && Math.abs(o.area) < 1e-12
    && o.pairs === 'Gibbsite|K_mica Gibbsite|Kaolinite K_feldspar|K_mica K_mica|Kaolinite' && o.junctions.length === 1)
    && Math.abs(silMaps[0].junctions[0][0] + 4.3925) < 1e-12 && Math.abs(silMaps[0].junctions[0][1] - 1.5505) < 1e-12
    && Math.abs(silMaps[1].junctions[0][0] - silMaps[0].junctions[0][0]) < 1e-12 && quartzOff < 1e-10 && quartz.lines.length > 0
    && makeups['SI(K_feldspar)'] === '{"K":1,"Al":1,"Si":3}' && makeups['SI(Kaolinite)'] === '{"Si":2,"Al":2}'
    && makeups['SI(Gibbsite)'] === '{"Al":1}' && makeups['SI(K_mica)'] === '{"K":1,"Al":3,"Si":3}' && makeups['SI(Quartz)'] === '{"Si":1}'
    && calciteMade && JSON.stringify(calciteMade.makeup) === '{"C":1,"Ca":1}',
  `${silMaps.map((o) => `Al ${o.al}: lines within ${o.line.toExponential(1)}, meeting at ${o.junctions.map((j) => j.map((v) => v.toFixed(6)).join(', '))} `
    + `within ${o.meet.toExponential(1)}; ${o.pairs}`).join(' | ')}; quartz within ${quartzOff.toExponential(1)}`);
  // The ratio held under an activity model: log a(K+) - log a(H+) the axis's at each point, the pH the water's.
  const silAct = silText.replace('EQUILIBRATE = always', 'EQUILIBRATE = always\nACTIVITY = davies');
  const rg = askW({ type: 'diagram', id: 13, text: silAct, at: 'start', cell: 0,
    axes: [{ kind: 'la', species: 'H4SiO4', from: -5, to: -3, n: 5 }, { kind: 'ratio', species: 'K+', from: 0, to: 4, n: 9 }] });
  let held = 0;
  for (let p = 0; p < rg.n1 * rg.n2; p++) {
    const la = (k) => rg.quant[p * rg.nq + rg.keys.indexOf(`la(${k})`)];
    held = Math.max(held, Math.abs(la('K+') - la('H+') - rg.y[Math.floor(p / rg.n1)]), Math.abs(-la('H+') - rg.pHHeld),
      Math.abs(la('H4SiO4') - rg.x[p % rg.n1]));
  }
  const smallAxes = [{ kind: 'la', species: 'H4SiO4', from: -5, to: -3, n: 3 }, { kind: 'ratio', species: 'K+', from: 0, to: 1, n: 3 }];
  const small = askW({ type: 'diagram', id: 14, text: silText, at: 'start', cell: 0, axes: smallAxes });
  const refusedRatio = [refusedAxes([{ kind: 'pH', from: 2, to: 12, n: 3 }, { kind: 'ratio', species: 'Cl-', from: 0, to: 1, n: 3 }], silText),
    refusedAxes([{ kind: 'pH', from: 2, to: 12, n: 3 }, { kind: 'ratio', species: 'K+', from: 0, to: 1, n: 3 }], ironText),
    (() => {
      try {
        askW({ type: 'diagramBounds', id: 15, text: silText, at: 'start', cell: 0, axes: smallAxes, grid: small.states,
          criterion: { kind: 'phase', keys: silKeys, per: [1, 2, 0, 3] } });
        return '';
      } catch (e) { return e.message; }
    })()];
  check('  the ratio held under Davies activities: log a(K+) - log a(H+) the axis\'s, log a(H4SiO4) the other\'s and the pH the '
    + 'water\'s at each point, to 1e-11, where the activity coefficients stop moving; a ratio of an anion, of a species the model '
    + 'has not, and a phase weighed by nothing, refused',
  held < 1e-11 && Number.isFinite(rg.pHHeld) && !rg.failed && /a ratio is a cation's/.test(refusedRatio[0])
    && /log a\(K\+\)\/a\(H\+\): it is no species dissolved in the water/.test(refusedRatio[1])
    && /positive number for each/.test(refusedRatio[2]),
  `within ${held.toExponential(1)}, the pH held at ${rg.pHHeld}; ${refusedRatio.map((x) => `"${x}"`).join(' | ')}`);

  /*
    PRINCIPAL COMPONENTS (RtmModel.pca), as the Composition tab gives them.
    Two variables correlated by r have eigenvalues 1 + r and 1 - r and
    components (1, 1) and (1, -1) over root 2. A table of six waters and four
    variables of the test's own against numpy.linalg.eigh (2.5.4) on the same
    standardised table. Waters on a line between two end members -- mixing
    and nothing else -- are one component, and a variable that does not vary
    is left out.
  */
  const X2 = [[1, 2], [2, 2.5], [3, 5], [4, 4], [5, 6.5]];
  const mx = X2.reduce((s, w) => s + w[0], 0) / 5;
  const my = X2.reduce((s, w) => s + w[1], 0) / 5;
  const rr = X2.reduce((s, w) => s + (w[0] - mx) * (w[1] - my), 0)
    / Math.sqrt(X2.reduce((s, w) => s + (w[0] - mx) ** 2, 0) * X2.reduce((s, w) => s + (w[1] - my) ** 2, 0));
  const p2 = RtmModel.pca(X2);
  const half = Math.SQRT1_2;
  check('principal components of two variables correlated by r: eigenvalues 1 + r and 1 - r, components (1, 1) and (1, -1) '
    + 'over root 2, to 1e-15', Math.abs(p2.values[0] - (1 + rr)) < 1e-15 && Math.abs(p2.values[1] - (1 - rr)) < 1e-15
    && Math.abs(p2.vectors[0][0] - half) < 1e-15 && Math.abs(p2.vectors[1][0] - half) < 1e-15
    && Math.abs(p2.vectors[0][1] - half) < 1e-15 && Math.abs(p2.vectors[1][1] + half) < 1e-15,
  `r ${rr}: ${p2.values.join(', ')}`);
  const X6 = [[7.1, 0.3, 120, 4], [6.8, 0.5, 140, 3.2], [7.6, 0.2, 95, 5.1], [7.3, 0.25, 110, 4.4], [6.5, 0.7, 160, 2.9], [7.0, 0.4, 130, 3.8]];
  const numpyEig = [3.9249416652653926, 0.0679779771454686, 0.006319761116472023, 0.000760596472667597];
  const p6 = RtmModel.pca(X6);
  const Z6 = X6.map((w) => w.map((v, k) => (v - p6.mean[k]) / p6.sd[k]));
  const C6 = [0, 1, 2, 3].map((a) => [0, 1, 2, 3].map((b) => Z6.reduce((s, z) => s + z[a] * z[b], 0) / 5));
  let eqWorst = 0;
  let orthWorst = 0;
  let backWorst = 0;
  for (let j = 0; j < 4; j++) {
    for (let a = 0; a < 4; a++) {
      eqWorst = Math.max(eqWorst, Math.abs(C6[a].reduce((s, c, b) => s + c * p6.vectors[b][j], 0) - p6.values[j] * p6.vectors[a][j]));
      orthWorst = Math.max(orthWorst, Math.abs(p6.vectors.reduce((s, v) => s + v[a] * v[j], 0) - (a === j ? 1 : 0)));
    }
  }
  Z6.forEach((z, i) => z.forEach((v, a) => { backWorst = Math.max(backWorst, Math.abs(p6.scores[i].reduce((s, sc, j) => s + sc * p6.vectors[a][j], 0) - v)); }));
  const projWorst = Math.max(...X6.flatMap((w, i) => RtmModel.pca(X6).project(w).map((v, j) => Math.abs(v - p6.scores[i][j]))));
  const npWorst = Math.max(...p6.values.map((v, j) => Math.abs(v - numpyEig[j]))) / numpyEig[0];
  check('  six waters of four variables: the eigenvalues numpy\'s to 1e-13 of the largest, each component an eigenvector of the '
    + 'correlation matrix to 1e-14 and of length one, at right angles to the rest, the eigenvalues summing to the four variables, '
    + 'the scores giving back the standardised table, and a water put on the components where its own scores are',
  npWorst < 1e-13 && eqWorst < 1e-14 && orthWorst < 1e-14 && Math.abs(p6.values.reduce((s, v) => s + v, 0) - 4) < 1e-13
    && backWorst < 1e-13 && projWorst < 1e-14 && p6.explained.every((e) => e >= 0),
  `numpy ${npWorst.toExponential(1)}, R v = l v ${eqWorst.toExponential(1)}, orthonormal ${orthWorst.toExponential(1)}, `
    + `back ${backWorst.toExponential(1)}, put on ${projWorst.toExponential(1)}`);
  const endA = [1e-3, 1.2e-3, 2e-3, 5e-4, 7];
  const endB = [1e-2, 1.1e-2, 1e-3, 3e-3, 7];
  const mixed = Array.from({ length: 11 }, (_, i) => endA.map((a, k) => a + (i / 10) * (endB[k] - a)));
  const pm = RtmModel.pca(mixed);
  const refusedPca = [[[[1, 2], [2, 3]], /three waters or more/], [[[1, 5], [2, 5], [3, 5]], /two things that vary.*have one/]]
    .filter(([X, re]) => { try { RtmModel.pca(X); return true; } catch (e) { return !re.test(e.message); } });
  check('  waters that only mix two end members lie on one component, all of their variance; a variable the same in every '
    + 'water is left out; fewer than three waters, or than two variables that vary, refused',
  pm.explained[0] > 1 - 1e-12 && pm.kept.join(',') === '0,1,2,3' && !refusedPca.length,
  `the first ${pm.explained[0]}, kept ${pm.kept.join(', ')}`);
}

/* ======================================================================
   3. The Jacobian
   ====================================================================== */
console.log('\n--- the Jacobian ---');
{
  const cases = [
    ['a batch reaction set', 'MODE = batch'],
    ['a transport model', 'MODE = transport'],
  ];
  for (const [label, mode] of cases) {
    const m = RtmModel.compile(RTM_DEFAULT_MODEL.replace(/^MODE\s*=.*$/m, mode));
    for (const [what, fill] of [['as it starts', false], ['with every species present', true]]) {
      const y = m.initialState();
      if (fill) for (let i = 0; i < y.length; i++) if (!(y[i] > 0)) y[i] = 1e-9 * (1 + (i % 5));
      const v = RtmModel.verifyJacobian(m, 0, y);
      check(`${label} ${what}: the analytic Jacobian matches a central difference`,
        v.discrepancies.length === 0 && !v.outsidePattern,
        `${v.checked} entries measured, ${v.unresolvable} below the noise floor`
        + (v.discrepancies.length ? `, ${v.discrepancies.length} disagreed` : ''));
    }
  }
}
{
  // The derivative of a power, which is the one the rate laws lean on and the
  // one a hand-written differentiator gets wrong.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
A 2.0
B 3.0
C 0.0

<REACTIONS>
A + B => C, r = k*[A]**3*[B]**2, k = 0.5
`);
  const V = new Float64Array(m.nnz);
  m.jac(0, m.initialState(), V);
  const { colPtr, rowIdx } = m.pattern;
  const at = (r, c) => { for (let k = colPtr[c]; k < colPtr[c + 1]; k++) if (rowIdx[k] === r) return V[k]; return 0; };
  // r = 0.5 A^3 B^2 ; dr/dA = 1.5 A^2 B^2 = 1.5*4*9 = 54 ; C gains it, A loses it
  close('d/dA of k A^3 B^2 is right', at(2, 0), 54, 1e-12);
  close('d/dB of k A^3 B^2 is right', at(2, 1), 2 * 0.5 * 8 * 3, 1e-12);
  close('  and the reactant row is its negative', at(0, 0), -54, 1e-12);
}

/* ======================================================================
   4. The model text itself
   ====================================================================== */
console.log('\n--- reading the model text ---');
{
  const bad = [
    ['an unknown section', '<NOPE>\n', /not a section/],
    ['a species used but not declared', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<REACTIONS>\nA => Q, k=1\n', /not in <SPECIES>/],
    ['a reaction with no rate', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<REACTIONS>\nA => \n', /k = \.\.\.|rate law/],
    ['a bare name in a rate law', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\n<REACTIONS>\nA => , r = A\n', /brackets|\[name\]/],
    ['a power whose exponent is a concentration', '<SETTINGS>\nMODE=batch\n<SPECIES>\nA 1\nB 1\n<REACTIONS>\nA => , r = [A]**[B]\n', /may not depend on a concentration/],
    ['transport with one cell', '<SETTINGS>\nMODE=transport\nCELLS=1\n<SPECIES>\nA 1\n<REACTIONS>\n', /at least 2/],
    ['an initial patch past the end', '<SETTINGS>\nMODE=transport\nCELLS=5\n<SPECIES>\nA 1\n<REACTIONS>\n\n<INITIAL>\nA 9 1\n', /past the last/],
  ];
  for (const [label, text, pattern] of bad) {
    let message = '(no error)';
    try { RtmModel.compile(text); } catch (e) { message = e.message; }
    check(`${label} is refused, and says why`, pattern.test(message), message.slice(0, 90));
  }
}
{
  // Chemical names must survive, since they are what a chemist writes.
  const m = RtmModel.compile(`
<SETTINGS>
MODE = batch
TEND = 1

<SPECIES>
e-      1e-9
H+      1e-7
OH-     1e-7
C2O4-2  0
UO2+2   0
U_site  1

<REACTIONS>
e- + H+ => , k = 2.3e10
C2O4-2 + UO2+2 => U_site, r = k*[C2O4-2]*[UO2+2], k = 1
`);
  check('chemical names survive parsing',
    m.speciesNames.join(' ') === 'e- H+ OH- C2O4-2 UO2+2 U_site', m.speciesNames.join(' '));
}
{
  const m = RtmModel.compile(RTM_DEFAULT_MODEL);
  check('the built-in model compiles', m.nspecies === 36 * 20 && m.nreactions === 127,
    `${m.speciesNames.length} species x ${m.cells} cells = ${m.nspecies}, ${m.nreactions} reactions`);
  check('  with no warnings', m.warnings.length === 0, m.warnings.join('; ') || 'none');
  const r = run(m, { tend: 1e4, rtol: 1e-6, atol: 1e-22, nonNegative: true });
  check('  and integrates', r.t.length > 1,
    `${r.stats.nsteps} steps, ${r.stats.sparse ? 'sparse' : 'dense'} LU`);
  let lowest = Infinity;
  for (const v of last(r)) lowest = Math.min(lowest, v);
  check('  without going negative', lowest >= -1e-20, `lowest concentration ${lowest.toExponential(2)}`);
}

/* ======================================================================
   Kompartment's solvers, and the derivative that works out only the rates
   ====================================================================== */
console.log('\n--- Kompartment’s solvers here ---');
{
  const OJ = require(path.join(jsDir, 'facsimile-ode-julia.js'));
  const { RTM_EXAMPLES } = require(path.join(jsDir, 'rtm-examples.js'));
  const byId = (id) => RtmModel.compile(RTM_EXAMPLES.find((e) => e.id === id).text);

  // The derivative no longer works out the rates' gradients, and the
  // Jacobian no longer the rates: each must still be what the other's
  // differences say.
  const rob = byId('robertson');
  const y = Float64Array.of(0.9, 3e-5, 0.1);
  const v = RtmModel.verifyJacobian(rob, 0, y);
  check('the Jacobian, worked out without the rates, agrees with differences of the derivative',
    v.discrepancies.length === 0 && v.checked > 0, `${v.checked} entries, ${v.discrepancies.length} out`);

  // Which models can say their Jacobian never moves: transport is linear, so
  // only a rate law whose derivative reads a concentration moves it.
  check('a tracer column has one Jacobian for the whole run', byId('tracer').jacobianConstant === true);
  check('and so has the decay chain in the rock', byId('u238chain').jacobianConstant === true);
  check('Robertson’s kinetics do not', rob.jacobianConstant === false);
  check('nor does the built-in model', RtmModel.compile(RTM_DEFAULT_MODEL).jacobianConstant === false);

  const tracer = () => byId('tracer');
  const opts = { tend: tracer().settings.TEND, rtol: 1e-6, atol: 1e-20, nonNegative: true, stagnationTol: 0.5, maxPoints: 4000 };
  const ndf = run(tracer(), opts);
  // Rosenbrock 2-3 forms its Jacobian every step; told it cannot change, once.
  const ros = run(tracer(), { ...opts, solver: 'ros23' });
  check('Rosenbrock 2-3 forms the tracer’s Jacobian once', ros.stats.npds === 1, `${ros.stats.npds} Jacobians`);
  // Compared on what is in the column, not on the far tail of the front.
  const inColumn = (r) => last(r).reduce((a, b) => a + b, 0);
  close('and agrees with the NDF on what is in the column', inColumn(ros), inColumn(ndf), 1e-5);
  // Dormand-Prince on a column that is not stiff.
  const dp = run(tracer(), { ...opts, solver: 'dp45' });
  close('Dormand–Prince agrees with it too', inColumn(dp), inColumn(ndf), 1e-5);
  // Auto: explicit until it turns stiff, then the NDF.
  const auto = run(tracer(), { ...opts, solver: OJ.solver('auto') });
  check('Auto hands the tracer column to the NDF', !!auto.stats.stepsBy && auto.stats.stepsBy.NDF > 0
    && auto.stats.switches === 1, JSON.stringify(auto.stats.stepsBy));
  close('and agrees with it', inColumn(auto), inColumn(ndf), 1e-6);
  const ab = byId('ab');
  const abAuto = run(ab, { tend: ab.settings.TEND, rtol: 1e-6, atol: 1e-12, solver: OJ.solver('auto') });
  check('and leaves A → B → C explicit throughout', !('NDF' in abAuto.stats.stepsBy), JSON.stringify(abAuto.stats.stepsBy));
  close('getting C right', last(abAuto)[2], 1 - Math.exp(-0.5 * 20) - (0.5 / 0.3) * (Math.exp(-0.2 * 20) - Math.exp(-0.5 * 20)), 1e-6);
  // The rest, briefly: each runs and agrees on the A -> B -> C batch.
  for (const id of ['julia_auto', 'julia_tsit5', 'julia_vern7', 'julia_rosenbrock23', 'julia_fbdf_krylov']) {
    const r = run(byId('ab'), { tend: 20, rtol: 1e-8, atol: 1e-14, solver: OJ.solver(id) });
    close(`${id} on A → B → C`, last(r)[2], 1 - Math.exp(-0.5 * 20) - (0.5 / 0.3) * (Math.exp(-0.2 * 20) - Math.exp(-0.5 * 20)),
      id === 'julia_rosenbrock23' ? 1e-5 : 1e-6);
  }
  // The first step and norm control reach the NDF here as on the canister page.
  const h0 = run(byId('ab'), { tend: 20, rtol: 1e-6, atol: 1e-12, h0: 1e-8 });
  check('the first step is the one asked for', h0.t[1] === 1e-8, String(h0.t[1]));
  const nc = run(byId('robertson'), { tend: 40, rtol: 1e-6, atol: 1e-20, normControl: true });
  const plain = run(byId('robertson'), { tend: 40, rtol: 1e-6, atol: 1e-20 });
  check('norm control loosens Robertson’s run', nc.stats.nsteps < plain.stats.nsteps, `${nc.stats.nsteps} against ${plain.stats.nsteps}`);
}

/* ======================================================================
   9. Kompartment's far-field path, from its own module
   ====================================================================== */
/*
  The far-field path Kompartment builds, put beside the model text that says
  the same path here: the layers, the cells past the release point, every
  entry of the transport matrix and the release. Kompartment's module is an
  ES module, so this part waits for it; it runs last for that reason alone.

  Kompartment's states are what each cell holds, inventories, and these are
  concentrations, so its matrix is this one seen through the capacities:
  A[r][c] = cap_r/cap_c * J[r][c], with cap = R in the fracture and
  aw*Rm*d_j in layer j, per unit volume of water. The release likewise: its
  weights act on inventories, R*dz*c per m2 of the water's cross-section.
*/
async function kompartmentPath() {
  console.log('\n--- Kompartment’s own far-field path ---');
  const { pathToFileURL } = require('url');
  const K = await import(pathToFileURL(path.join(__dirname, '..', '..', '..', 'kompartment', 'src', 'domain', 'farfield.js')).href);
  const chain = (p) => `
<SETTINGS>
MODE = transport
CELLS = ${p.nf}
LENGTH = ${p.tw}
TRAVEL_TIME = ${p.tw}
PECLET = ${p.pe}
LEFT = robin
RIGHT = semi-infinite
${p.nm === 12 ? '' : `MATRIX_CELLS = ${p.nm}`}
MATRIX_DEPTH = ${p.penDep}
${p.first ? `MATRIX_FIRST = ${p.first}` : ''}
MATRIX_POROSITY = ${p.eps}
MATRIX_DENSITY = ${p.rho}
TRANSPORT_RESISTANCE = ${p.f}
TIME_UNIT = year

<SPECIES>
${p.nucs.map((n, k) => `N${k} 0 D=0 left=0 De=${n.de} Kd=${n.kd}${n.kdf ? ` Kdf=${n.kdf}` : ''}`).join('\n')}

<PARAMETERS>
S all 0
S 0 ${p.nf / p.tw} fracture

<REACTIONS>
=> N0, k = S
${p.nucs.map((n, k) => (n.lam ? `N${k} => ${k + 1 < p.nucs.length ? `N${k + 1}` : ''}, k = ${n.lam}, on = inventory` : '')).join('\n')}
`;
  const year = (t) => Math.LN2 / t;
  const cases = [
    { name: 'the default path', tw: 100, f: 1e5, pe: 10, penDep: 12.5, eps: 0.0018, rho: 2700, nf: 20, nm: 12,
      nucs: [{ de: 1e-4, kd: 0, lam: 0 }] },
    // Kompartment's own example: the U-238 chain through 50 years of rock.
    { name: 'its far-field example', tw: 50, f: 1e5, pe: 10, penDep: 12.5, eps: 0.0018, rho: 2700, nf: 20, nm: 20,
      nucs: [{ de: 3.15e-5, kd: 0.0017, lam: year(4.468e9) }, { de: 3.15e-5, kd: 0.0017, lam: year(245500) },
        { de: 3.15e-5, kd: 0.05, lam: year(75380) }] },
    { name: 'a short-lived nuclide', tw: 100, f: 1e5, pe: 10, penDep: 12.5, eps: 0.0018, rho: 2700, nf: 20, nm: 12,
      nucs: [{ de: 1e-4, kd: 0.01, lam: 1.83 }] },
    { name: 'fracture sorption', tw: 30, f: 3e4, pe: 25, penDep: 4, eps: 0.003, rho: 2650, nf: 15, nm: 12,
      nucs: [{ de: 5e-5, kd: 0.001, kdf: 0.002, lam: 0 }] },
    { name: 'a first layer given', tw: 100, f: 1e5, pe: 10, penDep: 12.5, eps: 0.0018, rho: 2700, nf: 20, nm: 12, first: 1e-3,
      nucs: [{ de: 1e-4, kd: 0, lam: 0 }] },
  ];
  let layersSame = true;
  let countsSame = true;
  let worstEntry = 0;
  let entries = 0;
  let strays = 0;
  let worstRelease = 0;
  for (const p of cases) {
    const m = RtmModel.compile(chain(p));
    const ns = p.nucs.length;
    const aw = p.f / p.tw;
    const nucs = p.nucs.map((n) => ({ de: n.de, rm: p.eps + p.rho * n.kd, lam: n.lam, rf: 1 + (n.kdf || 0) * aw }));
    const g = K.pathGrid({ grid: 'matched', penDep: p.penDep, nm: p.nm, first: p.first || null, aw, tw: p.tw, pe: p.pe, nucs });
    for (let j = 0; j < p.nm; j++) if (g.d[j] !== m.matrix.d[j] || g.h[j] !== m.matrix.h[j]) layersSame = false;
    const block = { n_f: p.nf, n_m: p.nm, o_b: K.CONTINUES, n_b: '', pe: p.pe };
    if ((m.extra ? m.extra.n : 0) !== K.extraCells(block)) countsSame = false;
    const st = K.cellStructure(block);
    const V = new Float64Array(m.nnz);
    m.jac(0, new Float64Array(m.nspecies), V);
    const J = new Map();
    const { colPtr, rowIdx } = m.pattern;
    for (let c = 0; c < m.nspecies; c++) for (let k = colPtr[c]; k < colPtr[c + 1]; k++) J.set(`${rowIdx[k]},${c}`, V[k]);
    for (let s = 0; s < ns; s++) {
      const n = p.nucs[s];
      const c = K.coefficients({ nf: p.nf, nm: p.nm, tw: p.tw, f: p.f, surface: 'f', kd_f: n.kdf || 0, kd_m: n.kd,
        de_m: n.de, eps_m: p.eps, rho_m: p.rho, pe: p.pe, pen_dep: p.penDep, pen_dep_0: p.first || null,
        grid: 'matched', lam: n.lam }, g);
      const vals = new Float64Array(st.nnz);
      K.cellValues(block, c, vals);
      // Kompartment's matrix, with the decay it adds to every cell beside it.
      const A = new Map();
      for (let e = 0; e < st.nnz; e++) {
        const key = `${st.rows[e]},${st.cols[e]}`;
        A.set(key, (A.get(key) || 0) + vals[e] - (st.rows[e] === st.cols[e] ? n.lam : 0));
      }
      const Rf = 1 + (n.kdf || 0) * aw;
      const Rm = p.eps + p.rho * n.kd;
      const cap = (cell) => { const j = cell % (p.nm + 1); return j === 0 ? Rf : aw * Rm * g.d[j - 1]; };
      for (const [key, a] of A) {
        const [r, cc] = key.split(',').map(Number);
        const seen = (cap(r) / cap(cc)) * (J.get(`${r * ns + s},${cc * ns + s}`) || 0);
        worstEntry = Math.max(worstEntry, Math.abs(seen - a) / Math.abs(a));
        entries++;
      }
      // ...and nothing moving this nuclide here that Kompartment does not have.
      for (const [key, v] of J) {
        const [r, cc] = key.split(',').map(Number);
        if (r % ns === s && cc % ns === s && v !== 0 && !A.has(`${(r - s) / ns},${(cc - s) / ns}`)) strays++;
      }
      // The chain: Kompartment adds lambda_p times the parent's inventory to
      // the daughter's, in every cell; seen through the capacities that is
      // this model's d(C_d)/d(C_p).
      if (s > 0) {
        const lp = p.nucs[s - 1].lam;
        const Rp = 1 + (p.nucs[s - 1].kdf || 0) * aw;
        const Rmp = p.eps + p.rho * p.nucs[s - 1].kd;
        const capP = (cell) => { const j = cell % (p.nm + 1); return j === 0 ? Rp : aw * Rmp * g.d[j - 1]; };
        const ncell = m.cells;
        for (let cell = 0; cell < ncell; cell++) {
          const seen = (cap(cell) / capP(cell)) * J.get(`${cell * ns + s},${cell * ns + s - 1}`);
          worstEntry = Math.max(worstEntry, Math.abs(seen - lp) / lp);
          entries++;
        }
      }
      const cells = K.releaseCells(block);
      const w = new Float64Array(cells.length);
      K.releaseWeights(block, c, w);
      const y = Float64Array.from({ length: m.nspecies }, (_, k) => 0.1 + ((k * 104729) % 997) / 997);
      let theirs = 0;
      cells.forEach((cell, q) => { theirs += w[q] * Rf * (p.tw / p.nf) * y[cell * ns + s]; });
      worstRelease = Math.max(worstRelease, Math.abs(faceFlux(m, 'right', s, y) - theirs) / Math.abs(theirs));
    }
  }
  check(`the matched layers are Kompartment’s, bit for bit, in ${cases.length} paths`, layersSame);
  check('  and so are the cells past the release point', countsSame);
  check('  and every entry of its transport matrix and its chain, through the capacities',
    worstEntry < 1e-12 && strays === 0, `${entries} entries, worst ${worstEntry.toExponential(2)} relative, ${strays} not in Kompartment's`);
  check('  and its release, read at the same plane with the same weights',
    worstRelease < 1e-13, `worst ${worstRelease.toExponential(2)} relative`);
  let sameCount = true;
  for (const nf of [5, 10, 20, 40]) {
    for (const pe of [2, 10, 25, 40, 100]) {
      const m = RtmModel.compile(pathText({ ...KDEF, pe }, { nf }));
      if ((m.extra ? m.extra.n : 0) !== K.autoExtraCells(nf, pe)) sameCount = false;
    }
  }
  check('  and the count of them over 20 pairs of cells and Peclet numbers', sameCount);
}

/*
  SENSITIVITY INDICES (resources/js/rtm-gsa/indices.js), as the Uncertainty
  tab gives them, through the page's own path: Kompartment's EASI, delta and
  PAWN against GlobalSensitivity.jl's and SALib's numbers for the same
  samples (Kompartment's fixtures) -- delta with the reference's bootstrap
  replayed and its interval SALib's, root B times GlobalSensitivity.jl's --
  and on the Ishigami function, whose first-order indices are known exactly
  (a = 7, b = 0.1: 0.3139, 0.4424 and 0), with a fourth input it never
  reads. x3 matters only through x1: no first-order index, but a delta.
  The page reads delta off the value's normal scores, which do not change
  it: off the scores it is the value's to within the estimate's own
  wobble, and where most runs share one value -- which makes a kernel
  density of the value a spike -- the scores' delta is still a delta.
*/
async function sensitivityIndices() {
  const { pathToFileURL } = require('url');
  const fs = require('fs');
  const I = await import(pathToFileURL(path.join(__dirname, '..', '..', 'js', 'rtm-gsa', 'indices.js')).href);
  const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', '..', 'kompartment', 'test', 'fixtures', name), 'utf8'));
  const dec = (s) => { const b = Buffer.from(s, 'base64'); return new Float64Array(b.buffer, b.byteOffset, b.length / 8).slice(); };
  const g = fixture('gsa-reference.json');
  const sl = fixture('salib-reference.json');
  const XE = g.easi.x.map(dec);
  const s1c = dec(g.easi.S1c);
  const easiOff = Math.max(...(await I.indicesOf(XE, dec(g.easi.y), { boots: 4 })).inputs.map((r, k) => Math.abs(r.s1 - s1c[k])));
  const XD = g.delta.x.map(dec);
  const YD = dec(g.delta.y);
  const adj = dec(g.delta.adjusted);
  const low = dec(g.delta.low);
  let deltaOff = 0;
  let bandOff = 0;
  for (let k = 0; k < XD.length; k++) {
    const R = g.delta.resamples[k].map((r) => Int32Array.from(r));
    const got = (await I.indicesOf([XD[k]], YD, { resamples: R, scores: false })).inputs[0];
    deltaOff = Math.max(deltaOff, Math.abs(got.delta - adj[k]));
    bandOff = Math.max(bandOff, Math.abs(got.deltaLow - (adj[k] - (adj[k] - low[k]) * Math.sqrt(R.length))));
  }
  const ten = sl.pawn.find((c) => c.S === 10);
  const median = dec(ten.median);
  const pawnOff = Math.max(...(await I.indicesOf(sl.sample.X.map(dec), dec(sl.sample.Y), { boots: 4 })).inputs
    .map((r, k) => Math.abs(r.pawn - median[k])));
  check('sensitivity indices through the Uncertainty tab\'s path: EASI\'s corrected first-order index GlobalSensitivity.jl\'s, '
    + 'Borgonovo\'s delta reduced for its bias GlobalSensitivity.jl\'s with its bootstrap replayed, its interval SALib\'s, root B '
    + 'times as wide as GlobalSensitivity.jl\'s, and PAWN\'s median over ten slices SALib\'s, each to 1e-12',
  easiOff < 1e-12 && deltaOff < 1e-12 && bandOff < 1e-12 && pawnOff < 1e-12,
  `EASI ${easiOff.toExponential(1)}, delta ${deltaOff.toExponential(1)}, its interval ${bandOff.toExponential(1)}, PAWN ${pawnOff.toExponential(1)}`);
  const next = I.seeded(7);
  const n = 2048;
  const xs = [0, 1, 2, 3].map(() => Float64Array.from({ length: n }, () => -Math.PI + 2 * Math.PI * next()));
  const y = Float64Array.from({ length: n }, (_, i) => Math.sin(xs[0][i]) + 7 * Math.sin(xs[1][i]) ** 2
    + 0.1 * xs[2][i] ** 4 * Math.sin(xs[0][i]));
  const V = 49 / 8 + (0.1 * Math.PI ** 4) / 5 + (0.01 * Math.PI ** 8) / 18 + 0.5;
  const exact = [0.5 * (1 + (0.1 * Math.PI ** 4) / 5) ** 2 / V, 49 / 8 / V, 0, 0];
  const ish = await I.indicesOf(xs, y, { boots: 100, seed: 3 });
  const again = await I.indicesOf(xs, y, { boots: 100, seed: 3 });
  const plain = await I.indicesOf(xs, y, { boots: 100, seed: 3, scores: false });
  const [a1, a2, a3, a4] = ish.inputs;
  const offPlain = Math.max(...ish.inputs.map((r, k) => Math.abs(r.delta - plain.inputs[k].delta)));
  check('  on the Ishigami function, 2048 runs and a fourth input it never reads: each first-order index within its 95 % interval '
    + 'of the exact one, 0.3139, 0.4424, 0 and 0, and within 0.03 of it; delta largest for x2, then x1, then x3 -- which matters '
    + 'only through x1, its first-order index nothing -- clear of the unused input\'s, and off the normal scores within 0.015 of '
    + 'delta off the value; the same seed the same intervals',
  ish.inputs.every((r, k) => r.s1Low <= exact[k] && exact[k] <= r.s1High && Math.abs(r.s1 - exact[k]) < 0.03)
    && a2.delta > a1.delta && a1.delta > a3.delta && a3.deltaLow > a4.deltaHigh && offPlain < 0.015
    && JSON.stringify(again.inputs) === JSON.stringify(ish.inputs),
  `${ish.inputs.map((r, k) => `x${k + 1} S1 ${r.s1.toFixed(4)} [${r.s1Low.toFixed(4)}, ${r.s1High.toFixed(4)}] for ${exact[k].toFixed(4)}, `
    + `delta ${r.delta.toFixed(4)} (off the value ${plain.inputs[k].delta.toFixed(4)}), PAWN ${r.pawn.toFixed(4)}`).join('; ')}`);
  // A value most runs share exactly: x1 below 0.4, else 0.4, and a second input it never reads.
  const shared = Float64Array.from({ length: 400 }, (_, i) => Math.min(xs[0][i], 0.4));
  const two = [xs[0].slice(0, 400), xs[1].slice(0, 400)];
  const sc = await I.indicesOf(two, shared, { boots: 100, seed: 3 });
  const pl = await I.indicesOf(two, shared, { boots: 100, seed: 3, scores: false });
  const many = shared.filter((v) => v === 0.4).length;
  check('  a value most runs share exactly, x1 cut off at 0.4: off the value itself delta is no density\'s, far beyond 1; off its '
    + 'normal scores x1\'s a delta, between 0.4 and 0.8, and the unused input\'s what chance gives 400 runs, under 0.1 and its '
    + 'interval below x1\'s; x1\'s first-order index all but 1',
  many > 150 && pl.inputs[0].delta > 1e6 && sc.inputs[0].delta > 0.4 && sc.inputs[0].delta < 0.8
    && sc.inputs[1].delta < 0.1 && sc.inputs[1].deltaHigh < sc.inputs[0].deltaLow && sc.inputs[0].s1 > 0.98,
  `${many} of 400 at 0.4: off the value ${pl.inputs[0].delta.toExponential(2)}; off the scores x1 ${sc.inputs[0].delta.toFixed(4)}, `
    + `x2 ${sc.inputs[1].delta.toFixed(4)} [${sc.inputs[1].deltaLow.toFixed(3)}, ${sc.inputs[1].deltaHigh.toFixed(3)}]; S1 ${sc.inputs[0].s1.toFixed(3)}`);
}

/* ====================================================================== */
kompartmentPath().catch((e) => check('Kompartment’s far-field module could be read', false, e.message))
  .then(() => sensitivityIndices()).catch((e) => check('the sensitivity indices could be worked out', false, e.message)).then(() => {
  console.log(`\n${checks - failures.length} of ${checks} checks passed`);
  if (failures.length) console.log(`failed: ${failures.join(', ')}`);
  process.exit(failures.length ? 1 : 0);
});
