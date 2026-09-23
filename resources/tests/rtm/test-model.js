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

/** A FARFCOMP case as model text: years throughout, L = tw so that v = 1. */
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
    ['a row that is not two numbers', '<TABLE t>\n0 1 2\n', 'P all t(x)', /not two numbers/],
    ['a table with no name', '<TABLE>\n0 1\n', 'P all 1', /needs a name/],
  ]) {
    let m = '(no error)';
    try { withTable(table, params); } catch (err) { m = err.message; }
    check(`  refused: ${label}`, re.test(m), m.slice(0, 70));
  }
  let m = '(no error)';
  try {
    RtmModel.compile(`<SETTINGS>\nMODE = batch\n\n<SPECIES>\nX 1\n\n${T}\n<REACTIONS>\nX => , r = t(1)*[X]\n`);
  } catch (err) { m = err.message; }
  check('  and a table read in a rate law is refused, with the way to do it instead',
    /cannot.*<PARAMETERS>/.test(m), m.slice(0, 90));
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
    daughter must sit at the ratio its own decay sets: lambda_parent N_parent
    = lambda_daughter N_daughter. That is a statement about the chain, the
    sorption and the decay together, and it holds to a tenth of a per cent
    for all three pairs -- with Rm from 0.54 to 143, so it is not the
    capacities cancelling.

    In the FRACTURE it does not hold, and should not: flow carries a nuclide
    away before its daughter catches up. Thorium is the slow one and radium
    runs 2.4 times its equilibrium share there.
  */
  const lam = { Th230: 9.1946e-6, Ra226: 4.3322e-4, Pb210: 3.1083e-2, Po210: 1.8289 };
  const cellAt = (i, j, name) => yu[u.cellOf(i, j) * 6 + u.speciesNames.indexOf(name)];
  let offBy = 0;
  for (const [parent, daughter] of [['Pb210', 'Po210'], ['Ra226', 'Pb210'], ['Th230', 'Ra226']]) {
    const want = lam[parent] / lam[daughter];
    for (const cell of [0, u.fracture - 1]) {
      offBy = Math.max(offBy, Math.abs(cellAt(cell, u.matrix.n, daughter) / cellAt(cell, u.matrix.n, parent) / want - 1));
    }
  }
  check('  and deep in the rock the chain reaches secular equilibrium',
    offBy < 5e-3, `worst ${(100 * offBy).toFixed(2)} % from lambda_parent/lambda_daughter`);
  check('  while in the fracture the flow keeps it from doing so',
    Math.abs(cellAt(0, 0, 'Ra226') / cellAt(0, 0, 'Th230') / (lam.Th230 / lam.Ra226) - 1) > 1,
    `radium is ${(cellAt(0, 0, 'Ra226') / cellAt(0, 0, 'Th230') / (lam.Th230 / lam.Ra226)).toFixed(2)} times its equilibrium share`);
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

/* ====================================================================== */
console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) console.log(`failed: ${failures.join(', ')}`);
process.exit(failures.length ? 1 : 0);
