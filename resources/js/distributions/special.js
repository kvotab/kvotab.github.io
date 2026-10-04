/* ==========================================================================
   distributions.html: SPECIAL FUNCTIONS

   What the distributions need beneath their densities: the error function
   and the normal quantile, the gamma function and its relatives, the
   incomplete gamma and beta functions with their inverses, and the
   saddle-point terms that keep binomial and Poisson probabilities accurate
   for large counts.

   Methods followed (the code is written here):
   - erf, erfc, erfcx: W. J. Cody, "Rational Chebyshev approximations for the
     error function", Math. Comp. 23 (1969) 631-637; the coefficients of his
     CALERF (Netlib SPECFUN, public domain), with its IEEE double constants.
   - the normal quantile: M. J. Wichura, "Algorithm AS 241: the percentage
     points of the normal distribution", Appl. Statist. 37 (1988) 477-484,
     polished by one Halley step against erfc.
   - log Gamma, digamma, trigamma: Stirling's series and its derivatives
     after an upward recurrence; Taylor series about 1 and 2 for log Gamma.
   - stirlerr and bd0: C. Loader, "Fast and accurate computation of binomial
     probabilities" (2000), the method R's dbinom and dpois use.
   - the incomplete gamma function: its power series below a + 1 and its
     continued fraction above (DLMF 8.7.1, 8.9.2), evaluated by Lentz's
     method, and for a shape above 10^5 N. M. Temme's uniform asymptotic
     expansion ("The asymptotic expansion of the incomplete gamma
     functions", SIAM J. Math. Anal. 10 (1979) 757-766; DLMF 8.12); the
     incomplete beta function by its continued fraction (DLMF 8.17.22) on
     the side of the mean where it converges fast.
   - the inverses: a starting point from the normal approximation
     (Wilson-Hilferty for gamma, Abramowitz & Stegun 26.5.22 for beta) or
     from the power-law tails, then safeguarded Halley steps.
   ========================================================================== */

export const EPS = 2.220446049250313e-16;
export const LN_SQRT_2PI = 0.9189385332046727417803297;
export const LN_2PI = 1.8378770664093454835606594;
export const SQRT_2PI = 2.5066282746310005024157652;
export const EULER = 0.5772156649015328606065121;
export const LN2 = Math.LN2;
export const LN10 = Math.LN10;
const TINY = 1e-300;

/* ---- the error function (Cody's CALERF) ---------------------------------- */

const XSMALL = 1.11e-16;
const XBIG = 26.543;
const XHUGE = 6.71e7;
const XMAX = 2.53e307;
const XNEG = -26.628;
const SQRPI = 5.6418958354775628695e-1;   // 1/sqrt(pi)
const CA = [3.16112374387056560e0, 1.13864154151050156e2, 3.77485237685302021e2, 3.20937758913846947e3, 1.85777706184603153e-1];
const CB = [2.36012909523441209e1, 2.44024637934444173e2, 1.28261652607737228e3, 2.84423683343917062e3];
const CC = [5.64188496988670089e-1, 8.88314979438837594e0, 6.61191906371416295e1, 2.98635138197400131e2,
  8.81952221241769090e2, 1.71204761263407058e3, 2.05107837782607147e3, 1.23033935479799725e3, 2.15311535474403846e-8];
const CD = [1.57449261107098347e1, 1.17693950891312499e2, 5.37181101862009858e2, 1.62138957456669019e3,
  3.29079923573345963e3, 4.36261909014324716e3, 3.43936767414372164e3, 1.23033935480374942e3];
const CP = [3.05326634961232344e-1, 3.60344899949804439e-1, 1.25781726111229246e-1, 1.60837851487422766e-2,
  6.58749161529837803e-4, 1.63153871373020978e-2];
const CQ = [2.56852019228982242e0, 1.87295284992346047e0, 5.27905102951428412e-1, 6.05183413124413191e-2,
  2.33520497626869185e-3];

/* jint 0: erf, 1: erfc, 2: erfcx = exp(x^2) erfc(x). */
function calerf(x, jint) {
  let y = Math.abs(x);
  let result;
  if (y <= 0.46875) {
    const ysq = y > XSMALL ? y * y : 0;
    let xnum = CA[4] * ysq;
    let xden = ysq;
    for (let i = 0; i < 3; i++) {
      xnum = (xnum + CA[i]) * ysq;
      xden = (xden + CB[i]) * ysq;
    }
    result = x * (xnum + CA[3]) / (xden + CB[3]);
    if (jint !== 0) result = 1 - result;
    if (jint === 2) result *= Math.exp(ysq);
    return result;
  }
  if (y <= 4) {
    let xnum = CC[8] * y;
    let xden = y;
    for (let i = 0; i < 7; i++) {
      xnum = (xnum + CC[i]) * y;
      xden = (xden + CD[i]) * y;
    }
    result = (xnum + CC[7]) / (xden + CD[7]);
    if (jint !== 2) {
      const ysq = Math.trunc(y * 16) / 16;
      const del = (y - ysq) * (y + ysq);
      result = Math.exp(-ysq * ysq) * Math.exp(-del) * result;
    }
  } else {
    result = 0;
    let done = false;
    if (y >= XBIG) {
      if (jint !== 2 || y >= XMAX) done = true;
      else if (y >= XHUGE) { result = SQRPI / y; done = true; }
    }
    if (!done) {
      const ysq = 1 / (y * y);
      let xnum = CP[5] * ysq;
      let xden = ysq;
      for (let i = 0; i < 4; i++) {
        xnum = (xnum + CP[i]) * ysq;
        xden = (xden + CQ[i]) * ysq;
      }
      result = ysq * (xnum + CP[4]) / (xden + CQ[4]);
      result = (SQRPI - result) / y;
      if (jint !== 2) {
        const yt = Math.trunc(y * 16) / 16;
        const del = (y - yt) * (y + yt);
        result = Math.exp(-yt * yt) * Math.exp(-del) * result;
      }
    }
  }
  if (jint === 0) {
    result = (0.5 - result) + 0.5;
    if (x < 0) result = -result;
  } else if (jint === 1) {
    if (x < 0) result = 2 - result;
  } else if (x < 0) {
    if (x < XNEG) result = Infinity;
    else {
      const yt = Math.trunc(x * 16) / 16;
      const del = (x - yt) * (x + yt);
      y = Math.exp(yt * yt) * Math.exp(del);
      result = (y + y) - result;
    }
  }
  return result;
}

export function erf(x) { return Number.isNaN(x) ? NaN : calerf(x, 0); }
export function erfc(x) { return Number.isNaN(x) ? NaN : calerf(x, 1); }
export function erfcx(x) { return Number.isNaN(x) ? NaN : calerf(x, 2); }

/* ---- the standard normal ------------------------------------------------- */

export function normPdf(z) { return Math.exp(-0.5 * z * z - LN_SQRT_2PI); }
export function normLogPdf(z) { return -0.5 * z * z - LN_SQRT_2PI; }
export function normCdf(z) { return 0.5 * erfc(-z * Math.SQRT1_2); }
export function normSf(z) { return 0.5 * erfc(z * Math.SQRT1_2); }

/* ln Phi(z), finite far into the left tail where Phi itself underflows. */
export function normLogCdf(z) {
  if (z < -5) {
    const u = -z * Math.SQRT1_2;
    return Math.log(0.5 * erfcx(u)) - u * u;
  }
  if (z > 0) return Math.log1p(-normSf(z));
  return Math.log(normCdf(z));
}
export function normLogSf(z) { return normLogCdf(-z); }

const PA = [3.3871328727963666080e0, 1.3314166789178437745e2, 1.9715909503065514427e3, 1.3731693765509461125e4,
  4.5921953931549871457e4, 6.7265770927008700853e4, 3.3430575583588128105e4, 2.5090809287301226727e3];
const PB = [1, 4.2313330701600911252e1, 6.8718700749205790830e2, 5.3941960214247511077e3, 2.1213794301586595867e4,
  3.9307895800092710610e4, 2.8729085735721942674e4, 5.2264952788528545610e3];
const PC = [1.42343711074968357734e0, 4.63033784615654529590e0, 5.76949722146069140550e0, 3.64784832476320460504e0,
  1.27045825245236838258e0, 2.41780725177450611770e-1, 2.27238449892691845833e-2, 7.74545014278341407640e-4];
const PD = [1, 2.05319162663775882187e0, 1.67638483018380384940e0, 6.89767334985100004550e-1,
  1.48103976427480074590e-1, 1.51986665636164571966e-2, 5.47593808499534494600e-4, 1.05075007164441684324e-9];
const PE = [6.65790464350110377720e0, 5.46378491116411436990e0, 1.78482653991729133580e0, 2.96560571828504891230e-1,
  2.65321895265761230930e-2, 1.24266094738807843860e-3, 2.71155556874348757815e-5, 2.01033439929228813265e-7];
const PF = [1, 5.99832206555887937690e-1, 1.36929880922735805310e-1, 1.48753612908506148525e-2,
  7.86869131145613259100e-4, 1.84631831751005468180e-5, 1.42151175831644588870e-7, 2.04426310338993978564e-15];

function poly(c, x) {
  let s = c[c.length - 1];
  for (let i = c.length - 2; i >= 0; i--) s = s * x + c[i];
  return s;
}

/* The quantile of the lower half, p <= 0.5, to full precision. */
function normQuantileLower(p) {
  if (p <= 0) return -Infinity;
  const q = p - 0.5;
  let x;
  if (Math.abs(q) <= 0.425) {
    const r = 0.180625 - q * q;
    x = q * poly(PA, r) / poly(PB, r);
  } else {
    let r = Math.sqrt(-Math.log(p));
    if (r <= 5) { r -= 1.6; x = -poly(PC, r) / poly(PD, r); }
    else { r -= 5; x = -poly(PE, r) / poly(PF, r); }
  }
  /* One Halley step on Phi(x) = p, whose error erfc gives to full relative
     precision in this half. */
  if (x > -37) {
    const e = 0.5 * erfc(-x * Math.SQRT1_2) - p;
    const u = e * SQRT_2PI * Math.exp(0.5 * x * x);
    x -= u / (1 + 0.5 * x * u);
  }
  return x;
}

/* z with Phi(z) = p. For p above one half 1 - p is exact in floating point,
   so the upper half loses nothing by symmetry. */
export function normQuantile(p) {
  if (Number.isNaN(p) || p < 0 || p > 1) return NaN;
  if (p === 0) return -Infinity;
  if (p === 1) return Infinity;
  return p <= 0.5 ? normQuantileLower(p) : -normQuantileLower(1 - p);
}

/* z with 1 - Phi(z) = q, for upper-tail probabilities too small for p. */
export function normIsf(q) { return -normQuantile(q); }

/* ---- the gamma function and its relatives ---------------------------------- */

/* B_2k / (2k (2k - 1)), the coefficients of Stirling's series. */
const STIRLING = [1 / 12, -1 / 360, 1 / 1260, -1 / 1680, 1 / 1188, -691 / 360360, 1 / 156, -3617 / 122400];

/* lgamma(x) - [(x - 1/2) ln x - x + ln sqrt(2 pi)] for x >= 10. */
function stirlingCorrection(x) {
  const f = 1 / (x * x);
  let s = STIRLING[STIRLING.length - 1];
  for (let i = STIRLING.length - 2; i >= 0; i--) s = s * f + STIRLING[i];
  return s / x;
}

/* zeta(2) .. zeta(14); higher ones are summed. */
const ZETA = [0, 0, 1.6449340668482264365, 1.2020569031595942854, 1.0823232337111381915, 1.0369277551433699263,
  1.0173430619844491397, 1.0083492773819228268, 1.0040773561979443394, 1.0020083928260822144,
  1.0009945751278180853, 1.0004941886041194646, 1.0002460865533080483, 1.0001227133475784891,
  1.0000612481350587048];
for (let k = 15; k <= 26; k++) {
  let s = 1;
  for (let j = 2; j <= 7; j++) s += Math.pow(j, -k);
  ZETA[k] = s;
}

/* lgamma(1 + e) for |e| < 0.2: -gamma e + sum (-1)^k zeta(k) e^k / k. */
function lgamma1pSeries(e) {
  let s = 0;
  let pw = -e;
  for (let k = 2; k <= 26; k++) {
    pw *= -e;
    s += ZETA[k] * pw / k;
  }
  return -EULER * e + s;
}

export function lgamma(x) {
  if (Number.isNaN(x)) return NaN;
  if (x === Infinity) return Infinity;
  if (x <= 0) {
    if (Number.isInteger(x)) return Infinity;
    return Math.log(Math.PI / Math.abs(Math.sin(Math.PI * x))) - lgamma(1 - x);
  }
  if (x < 1e-8) return -Math.log(x) - EULER * x;
  if (Math.abs(x - 1) < 0.2) return lgamma1pSeries(x - 1);
  if (Math.abs(x - 2) < 0.2) return Math.log1p(x - 2) + lgamma1pSeries(x - 2);
  if (x >= 10) return (x - 0.5) * Math.log(x) - x + LN_SQRT_2PI + stirlingCorrection(x);
  let prod = 1;
  let y = x;
  while (y < 10) { prod *= y; y += 1; }
  return (y - 0.5) * Math.log(y) - y + LN_SQRT_2PI + stirlingCorrection(y) - Math.log(prod);
}

/* Gamma(x) for the moments that need the function itself. */
export function gammaFn(x) {
  if (Number.isInteger(x) && x > 0 && x <= 171) {
    let r = 1;
    for (let i = 2; i < x; i++) r *= i;
    return r;
  }
  if (x > 0) return Math.exp(lgamma(x));
  if (Number.isInteger(x)) return NaN;
  // reflection: Gamma(x) Gamma(1 - x) = pi / sin(pi x)
  return Math.PI / (Math.sin(Math.PI * x) * gammaFn(1 - x));
}

export function digamma(x) {
  if (Number.isNaN(x)) return NaN;
  if (x <= 0 && Number.isInteger(x)) return NaN;
  if (x < 0) return digamma(1 - x) - Math.PI / Math.tan(Math.PI * x);
  let r = 0;
  while (x < 10) { r -= 1 / x; x += 1; }
  const f = 1 / (x * x);
  const t = f * (1 / 12 - f * (1 / 120 - f * (1 / 252 - f * (1 / 240 - f * (1 / 132 - f * (691 / 32760 - f / 12))))));
  return r + Math.log(x) - 0.5 / x - t;
}

export function trigamma(x) {
  if (Number.isNaN(x)) return NaN;
  if (x <= 0 && Number.isInteger(x)) return NaN;
  if (x < 0) {
    const s = Math.sin(Math.PI * x);
    return -trigamma(1 - x) + (Math.PI * Math.PI) / (s * s);
  }
  let r = 0;
  while (x < 10) { r += 1 / (x * x); x += 1; }
  const f = 1 / (x * x);
  const t = f * (1 / 6 - f * (1 / 30 - f * (1 / 42 - f * (1 / 30 - f * (5 / 66 - f * (691 / 2730 - f * 7 / 6))))));
  return r + 1 / x + 0.5 * f + t / x;
}

/* ln B(a, b), kept accurate when a or b is large by differencing Stirling
   corrections instead of whole log gammas. */
export function lbeta(a, b) {
  if (a > b) { const t = a; a = b; b = t; }
  if (!(a > 0)) return a === 0 ? Infinity : NaN;
  if (a >= 10) {
    const corr = stirlingCorrection(a) + stirlingCorrection(b) - stirlingCorrection(a + b);
    return -0.5 * Math.log(b) + LN_SQRT_2PI + corr + (a - 0.5) * Math.log(a / (a + b)) + b * Math.log1p(-a / (a + b));
  }
  if (b >= 10) {
    const corr = stirlingCorrection(b) - stirlingCorrection(a + b);
    return lgamma(a) + corr + a - a * Math.log(a + b) + (b - 0.5) * Math.log1p(-a / (a + b));
  }
  return lgamma(a) + lgamma(b) - lgamma(a + b);
}

/* ln C(n, k) for real n >= k >= 0. */
export function lchoose(n, k) {
  if (k < 0 || k > n) return -Infinity;
  if (k === 0 || k === n) return 0;
  return -Math.log(n + 1) - lbeta(n - k + 1, k + 1);
}

/* ---- Loader's saddle-point terms ------------------------------------------ */

/* ln Gamma(n + 1) - [(n + 1/2) ln n - n + ln sqrt(2 pi)]. */
export function stirlerr(n) {
  if (n >= 10) return stirlingCorrection(n);
  if (n <= 0) return n === 0 ? 0 : NaN;
  return lgamma(n + 1) - (n + 0.5) * Math.log(n) + n - LN_SQRT_2PI;
}

/* x ln(x / np) + np - x, without the cancellation when x is near np. */
export function bd0(x, np) {
  if (Math.abs(x - np) < 0.1 * (x + np)) {
    let v = (x - np) / (x + np);
    let s = (x - np) * v;
    if (Math.abs(s) < Number.MIN_VALUE) return s;
    let ej = 2 * x * v;
    v *= v;
    for (let j = 1; j < 1000; j++) {
      ej *= v;
      const s1 = s + ej / (2 * j + 1);
      if (s1 === s) return s1;
      s = s1;
    }
  }
  return x * Math.log(x / np) + np - x;
}

/* ln(lambda^x e^-lambda / Gamma(x + 1)) for real x >= 0. */
export function logDpoisRaw(x, lambda) {
  if (lambda === 0) return x === 0 ? 0 : -Infinity;
  if (!Number.isFinite(lambda) || x < 0) return -Infinity;
  if (x <= lambda * Number.MIN_VALUE) return -lambda;
  if (lambda < x * Number.MIN_VALUE) return -lambda + x * Math.log(lambda) - lgamma(x + 1);
  return -stirlerr(x) - bd0(x, lambda) - 0.5 * (LN_2PI + Math.log(x));
}

export function dpoisRaw(x, lambda) { return Math.exp(logDpoisRaw(x, lambda)); }

/* ln of the binomial probability of x in n with p (and q = 1 - p), for
   real x and n. */
export function logDbinomRaw(x, n, p, q) {
  if (p === 0) return x === 0 ? 0 : -Infinity;
  if (q === 0) return x === n ? 0 : -Infinity;
  if (x === 0) {
    if (n === 0) return 0;
    return p < 0.1 ? -bd0(n, n * q) - n * p : n * Math.log(q);
  }
  if (x === n) return q < 0.1 ? -bd0(n, n * p) - n * q : n * Math.log(p);
  if (x < 0 || x > n) return -Infinity;
  const lc = stirlerr(n) - stirlerr(x) - stirlerr(n - x) - bd0(x, n * p) - bd0(n - x, n * q);
  const lf = LN_2PI + Math.log(x) + Math.log1p(-x / n);
  return lc - 0.5 * lf;
}

/* ---- the incomplete gamma function ------------------------------------------ */

const MAX_TERMS = 10000000;

/* d - log1p(d), without the cancellation for small d. */
function dMinusLog1p(d) {
  if (Math.abs(d) < 0.1) {
    let s = 0;
    let p = d * d;
    for (let k = 2; k < 80; k++) {
      const t = p / k;
      s += k % 2 === 0 ? t : -t;
      if (Math.abs(t) <= 1e-17 * Math.abs(s)) break;
      p *= d;
    }
    return s;
  }
  return d - Math.log1p(d);
}

/* Temme's uniform asymptotic expansion (DLMF 8.12.3-8.12.11) for a large:
   Q = erfc(eta sqrt(a/2))/2 + R, R = e^(-a eta^2/2)/sqrt(2 pi a) (c0 + c1/a),
   eta^2/2 = lambda - 1 - ln lambda, lambda = x/a. Near lambda = 1 the c's are
   their series in eta, where their closed forms cancel. With a >= 1e5 the
   first term left out is below 1e-16 of the result. */
const TEMME_C0 = [-1 / 3, 1 / 12, -2 / 135, 1 / 864, 1 / 2835, -139 / 777600, 1 / 25515];
const TEMME_C1 = [-1 / 540, -1 / 288, 1 / 378, -77 / 77760];
const TEMME_MIN_A = 1e5;

function gammaIncTemme(a, x) {
  const d = (x - a) / a;
  const half = dMinusLog1p(d);   // eta^2 / 2
  const eta = (d < 0 ? -1 : 1) * Math.sqrt(2 * half);
  let c0;
  let c1;
  if (Math.abs(d) < 0.01) {
    c0 = poly(TEMME_C0, eta);
    c1 = poly(TEMME_C1, eta);
  } else {
    c0 = 1 / d - 1 / eta;
    c1 = 1 / (eta * eta * eta) - 1 / (d * d * d) - 1 / (d * d) - 1 / (12 * d);
  }
  const R = Math.exp(-a * half) / Math.sqrt(2 * Math.PI * a) * (c0 + c1 / a);
  const s = eta * Math.sqrt(a / 2);
  if (eta >= 0) {
    const Q = Math.min(1, Math.max(0, 0.5 * erfc(s) + R));
    return [1 - Q, Q];
  }
  const P = Math.min(1, Math.max(0, 0.5 * erfc(-s) - R));
  return [P, 1 - P];
}

/* [P(a, x), Q(a, x)], the regularized lower and upper incomplete gamma
   functions; the smaller of the two is computed directly. */
export function gammaInc(a, x) {
  if (!(a > 0) || Number.isNaN(x)) return [NaN, NaN];
  if (x <= 0) return [0, 1];
  if (x === Infinity) return [1, 0];
  if (a >= TEMME_MIN_A) return gammaIncTemme(a, x);
  if (x < a + 1) {
    let sum = 1;
    let term = 1;
    let ap = a;
    for (let n = 0; n < MAX_TERMS; n++) {
      ap += 1;
      term *= x / ap;
      sum += term;
      if (term <= sum * 1e-17) break;
    }
    const P = Math.min(1, dpoisRaw(a, x) * sum);
    return [P, 1 - P];
  }
  let b = x + 1 - a;
  let c = 1 / TINY;
  let d = 1 / b;
  let h = d;
  for (let i = 1; i < MAX_TERMS; i++) {
    const an = -i * (i - a);
    b += 2;
    d = an * d + b;
    if (Math.abs(d) < TINY) d = TINY;
    c = b + an / c;
    if (Math.abs(c) < TINY) c = TINY;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-16) break;
  }
  const Q = Math.min(1, Math.exp(Math.log(a) + logDpoisRaw(a, x)) * h);
  return [1 - Q, Q];
}

export function gammaP(a, x) { return gammaInc(a, x)[0]; }
export function gammaQ(a, x) { return gammaInc(a, x)[1]; }

/* x^(a-1) e^-x / Gamma(a), the derivative of P(a, x) in x. */
function gammaDensity(a, x) {
  if (x <= 0) return a < 1 ? Infinity : (a === 1 ? 1 : 0);
  return Math.exp(Math.log(a / x) + logDpoisRaw(a, x));
}

/* x with P(a, x) = p (and Q(a, x) = q, which is used instead of p when it is
   the smaller, so that upper-tail quantiles keep their precision). */
export function gammaIncInv(a, p, q = 1 - p) {
  if (!(a > 0) || Number.isNaN(p)) return NaN;
  if (p <= 0) return 0;
  if (q <= 0) return Infinity;
  const upper = q < p;
  const target = upper ? q : p;
  const lgA = lgamma(a);
  /* the starting point */
  let x;
  const z = upper ? -normQuantile(q) : normQuantile(p);
  if (a > 1) {
    const t = 1 / (9 * a);
    x = a * Math.pow(1 - t + z * Math.sqrt(t), 3);
  }
  if (!(x > 0)) {
    /* the tails: P ~ x^a / Gamma(a + 1) near 0, Q ~ x^(a-1) e^-x / Gamma(a) far out */
    if (!upper) {
      x = Math.exp((Math.log(p) + lgamma(a + 1)) / a);
      if (x === 0) return 0;   // below the smallest double
    } else {
      x = -Math.log(q) - lgA;
      for (let i = 0; i < 3 && x > 0; i++) x = -Math.log(q) - lgA + (a - 1) * Math.log(x);
      if (!(x > 0)) x = Math.max(a, 1);
    }
  }
  if (!Number.isFinite(x) || x <= 0) x = Math.max(a, 1e-3);
  let lo = 0;
  let hi = Infinity;
  const logTarget = Math.log(target);
  for (let it = 0; it < 200; it++) {
    const [P, Q] = gammaInc(a, x);
    const T = upper ? Q : P;
    /* T rises with x for the lower tail and falls for the upper one */
    const below = upper ? T > target : T < target;
    if (below) lo = x; else hi = x;
    const dens = gammaDensity(a, x);
    let xn;
    if (T > 0 && dens > 0 && Number.isFinite(dens)) {
      if (target < 1e-3) {
        /* Newton on ln T, which is close to linear in the far tails */
        const g = Math.log(T) - logTarget;
        const dg = (upper ? -dens : dens) / T;
        xn = x - g / dg;
      } else {
        const f = T - target;
        const df = upper ? -dens : dens;
        let dx = f / df;
        const corr = 1 - 0.5 * dx * ((a - 1) / x - 1);
        if (corr > 0.5 && corr < 2) dx /= corr;
        xn = x - dx;
      }
    }
    if (!(xn > lo && xn < hi)) {
      if (hi === Infinity) xn = Math.max(2 * x, x + 1);
      else if (lo > 0 && hi / lo > 4) xn = Math.sqrt(lo * hi);
      else if (lo === 0) xn = hi / 4;
      else xn = 0.5 * (lo + hi);
    }
    if (Math.abs(xn - x) <= 4 * EPS * xn || xn === x) return xn;
    x = xn;
  }
  return x;
}

/* ---- the incomplete beta function ------------------------------------------- */

/* The continued fraction for I_x(a, b) (without its front factor). */
function betaContinuedFraction(a, b, x) {
  const qab = a + b;
  const qap = a + 1;
  const qam = a - 1;
  let c = 1;
  let d = 1 - qab * x / qap;
  if (Math.abs(d) < TINY) d = TINY;
  d = 1 / d;
  let h = d;
  for (let m = 1; m < MAX_TERMS; m++) {
    const m2 = 2 * m;
    let aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < TINY) d = TINY;
    c = 1 + aa / c;
    if (Math.abs(c) < TINY) c = TINY;
    d = 1 / d;
    h *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < TINY) d = TINY;
    c = 1 + aa / c;
    if (Math.abs(c) < TINY) c = TINY;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < 1e-16) break;
  }
  return h;
}

/* [I_x(a, b), 1 - I_x(a, b)], with y = 1 - x passed in when the caller
   knows it more accurately than 1 - x can be computed. */
export function betaInc(a, b, x, y = 1 - x) {
  if (!(a > 0) || !(b > 0) || Number.isNaN(x)) return [NaN, NaN];
  if (x <= 0) return [0, 1];
  if (y <= 0) return [1, 0];
  /* The front factor x^a y^b / B(a, b). When both a and b are large it is
     the binomial probability of a in a + b (Loader's form) times ab/(a + b),
     which keeps its precision where a ln x + b ln y - ln B(a, b) would lose
     it to cancellation between terms of a million. With one of them small
     the direct form is the accurate one (ln B differences Stirling's
     corrections itself). */
  let front;
  if (Math.min(a, b) > 30) front = logDbinomRaw(a, a + b, x, y) + Math.log(a * b / (a + b));
  else {
    const lx = x < 0.5 ? Math.log(x) : Math.log1p(-y);
    const ly = y < 0.5 ? Math.log(y) : Math.log1p(-x);
    front = a * lx + b * ly - lbeta(a, b);
  }
  if (x < (a + 1) / (a + b + 2)) {
    const I = Math.min(1, Math.exp(front - Math.log(a)) * betaContinuedFraction(a, b, x));
    return [I, 1 - I];
  }
  const J = Math.min(1, Math.exp(front - Math.log(b)) * betaContinuedFraction(b, a, y));
  return [1 - J, J];
}

/* x^(a-1) (1-x)^(b-1) / B(a, b). */
function betaDensity(a, b, x, y) {
  if (x <= 0 || y <= 0) return 0;
  const lx = x < 0.5 ? Math.log(x) : Math.log1p(-y);
  const ly = y < 0.5 ? Math.log(y) : Math.log1p(-x);
  return Math.exp((a - 1) * lx + (b - 1) * ly - lbeta(a, b));
}

/* Solve I_x(a, b) = p for x <= one half or so, starting from x0; returns
   [x, 1 - x]. */
function betaSolve(a, b, p, x0) {
  let x = x0;
  let lo = 0;
  let hi = 1;
  const logP = Math.log(p);
  for (let it = 0; it < 300; it++) {
    const y = 1 - x;
    const [I] = betaInc(a, b, x, y);
    if (I < p) lo = x; else hi = x;
    const dens = betaDensity(a, b, x, y);
    let xn = NaN;
    if (I > 0 && dens > 0 && Number.isFinite(dens)) {
      if (p < 1e-3) {
        xn = x - (Math.log(I) - logP) / (dens / I);
      } else {
        let dx = (I - p) / dens;
        const corr = 1 - 0.5 * dx * ((a - 1) / x - (b - 1) / y);
        if (corr > 0.5 && corr < 2) dx /= corr;
        xn = x - dx;
      }
    }
    if (!(xn > lo && xn < hi)) {
      if (lo > 0 && hi / lo > 4) xn = Math.sqrt(lo * hi);
      else if (lo === 0) xn = hi / 4;
      else xn = 0.5 * (lo + hi);
    }
    if (Math.abs(xn - x) <= 4 * EPS * xn || xn === x) return xn;
    x = xn;
  }
  return x;
}

/* x with I_x(a, b) = p; returns [x, 1 - x] with the smaller of the two
   computed directly, so that quantiles near 1 keep their precision. */
export function betaIncInv(a, b, p, q = 1 - p) {
  if (!(a > 0) || !(b > 0) || Number.isNaN(p)) return [NaN, NaN];
  if (p <= 0) return [0, 1];
  if (q <= 0) return [1, 0];
  /* the starting point, and from it which variable to solve for */
  let x;
  let y;
  if (a >= 1 && b >= 1) {
    const z = p < q ? -normQuantile(p) : normQuantile(q);
    const lam = (z * z - 3) / 6;
    const h = 2 / (1 / (2 * a - 1) + 1 / (2 * b - 1));
    const w = z * Math.sqrt(h + lam) / h - (1 / (2 * b - 1) - 1 / (2 * a - 1)) * (lam + 5 / 6 - 2 / (3 * h));
    const e = Math.exp(2 * w);
    if (Number.isFinite(e)) {
      x = a / (a + b * e);
      y = b * e / (a + b * e);
    } else {
      x = 0;
      y = 1;
    }
  } else {
    const lnab = Math.log(a + b);
    const t = Math.exp(a * (Math.log(a) - lnab)) / a;
    const u = Math.exp(b * (Math.log(b) - lnab)) / b;
    const w = t + u;
    if (p < t / w) {
      x = Math.pow(a * w * p, 1 / a);
      if (x === 0) return [0, 1];   // below the smallest double
      y = 1 - x;
    } else {
      y = Math.pow(b * w * q, 1 / b);
      if (y === 0) return [1, 0];
      x = 1 - y;
    }
  }
  /* Solved against the smaller of p and q, which is the one that is exact:
     1 - 1e-100 is 1 in floating point, and a solve against it finds any x
     whose I rounds to 1. Each side starts from its own variable, which stays
     a good start when its complement rounds to 1. */
  if (p <= q) {
    const xs = betaSolve(a, b, p, x > 0 && x < 1 ? x : a / (a + b));
    return [xs, 1 - xs];
  }
  const ys = betaSolve(b, a, q, y > 0 && y < 1 ? y : b / (a + b));
  return [1 - ys, ys];
}

/* ---- small helpers ----------------------------------------------------------- */

/* ln(1 - e^x) for x < 0, accurate at both ends. */
export function log1mexp(x) {
  return x > -Math.LN2 ? Math.log(-Math.expm1(x)) : Math.log1p(-Math.exp(x));
}

/* ln(1 + e^x) without overflow. */
export function log1pexp(x) {
  if (x <= -37) return Math.exp(x);
  if (x <= 18) return Math.log1p(Math.exp(x));
  if (x <= 33.3) return x + Math.exp(-x);
  return x;
}

export function logSumExp(values) {
  let m = -Infinity;
  for (const v of values) if (v > m) m = v;
  if (m === -Infinity || m === Infinity) return m;
  let s = 0;
  for (const v of values) s += Math.exp(v - m);
  return m + Math.log(s);
}
