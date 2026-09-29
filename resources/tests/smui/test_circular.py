#!/usr/bin/env python3
"""Analyze > Specialized Modeling > Circular Statistics, the backend
(resources/py/smui/circular.py), through the page's dispatch and JSON round
trip, checked against:

  - scipy.stats.circmean, circvar, circstd and vonmises.fit called directly;
  - pingouin's circ_mean, circ_r, circ_rayleigh, circ_vtest, circ_corrcc and
    circ_corrcl (pingouin is GPL: a reference here, nothing of it is in the
    page; its checks are skipped without it), also on its bundled
    orientation data (Berens 2009), read at run time: axial angles with
    spike counts as Freq;
  - the formulas of Mardia and Jupp (2000), Fisher (1993) and Zar (2010)
    written out again here: the moments, skewness and kurtosis, Upton's and
    Fisher's intervals, the Watson-Williams F, the uniform scores W, the von
    Mises information and its likelihood-ratio interval;
  - a brute-force median direction, Monte Carlo coverage of the intervals
    and the size of the tests, simulated truth;
  - the code under each result, run on a CSV export of its table.

    python3 resources/tests/smui/test_circular.py
"""
import contextlib
import io
import math
import os
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq
from scipy.special import i0e, i1e

from backend import FAILED, Checks, call, table

check = Checks()
if 'circular' in FAILED:
    print('circular did not import:', FAILED['circular'])
    sys.exit(1)
try:
    import pingouin as pg  # noqa: E402  (a reference only)
except ImportError:
    pg = None
    print('pingouin is not installed: its reference checks are skipped')
from smui import circular as C  # noqa: E402

rng = np.random.default_rng(20260927)
TAU = 2 * np.pi


def code_ns(columns, code, label):
    """Run a result's code on a CSV export of its table; its variables."""
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(columns).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(compile(code, label, 'exec'), ns)
        except Exception as e:   # the check below reports it
            ns['__error__'] = f'{type(e).__name__}: {e}'
        finally:
            os.chdir(here)
    check(f'the code of {label} runs', ns.get('__error__', True), True)
    return ns


def close_arr(a, b, rel=1e-9):
    """Two sequences of numbers equal within rel (relative to each value, at least 1e-12)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= np.maximum(1e-12, rel * np.maximum(np.abs(a), np.abs(b)))))


def cdist(a, b):
    """The circular distance of angles in radians."""
    return np.abs(np.mod(np.asarray(a) - b + np.pi, TAU) - np.pi)


# ---- the summary of a von Mises sample, in degrees ------------------------------------
n = 60
th = stats.vonmises.rvs(2.2, loc=np.deg2rad(200), size=n, random_state=rng) % TAU
deg = np.rad2deg(th)
deg[7] = np.nan
ok = np.isfinite(deg)
t0 = th[ok]
tid = table({'dir': deg})
r = call('circular.summary', table=tid, column='dir', v_dir=210)
check('n leaves out the missing angle', r['n'], int(ok.sum()))
check.near('mean direction = scipy circmean', r['mean'], float(np.rad2deg(stats.circmean(t0))), rel=1e-12)
Rb = abs(np.mean(np.exp(1j * t0)))
check.near('R̄ = |mean of e^(iθ)|', r['rbar'], float(Rb), rel=1e-12)
if pg is not None:
    check.near('mean direction = pingouin circ_mean', r['mean'], float(np.rad2deg(pg.circ_mean(t0)) % 360), rel=1e-12)
    check.near('R̄ = pingouin circ_r', r['rbar'], float(pg.circ_r(t0)), rel=1e-12)
check.near('circular variance = scipy circvar (1 − R̄)', r['circ_var'], float(stats.circvar(t0)), rel=1e-12)
check.near('circular SD = scipy circstd, in degrees', r['circ_sd'], float(np.rad2deg(stats.circstd(t0))), rel=1e-12)
Rb = abs(np.mean(np.exp(1j * t0)))
check.near('angular deviation √(2(1 − R̄)) (Zar)', r['ang_dev'], float(np.rad2deg(np.sqrt(2 * (1 - Rb)))), rel=1e-12)
mu = np.angle(np.mean(np.exp(1j * t0)))
rho2 = float(np.mean(np.cos(2 * (t0 - mu))))
check.near('circular dispersion (1 − ρ₂)/(2R̄²) (Fisher)', r['dispersion'], (1 - rho2) / (2 * Rb ** 2), rel=1e-11)
m2 = np.mean(np.exp(2j * t0))
check.near('circular skewness (Fisher 1993)', r['skewness'], float(abs(m2) * np.sin(np.angle(m2) - 2 * mu) / (1 - Rb) ** 1.5), rel=1e-10)
check.near('circular kurtosis (Fisher 1993)', r['kurtosis'], float((abs(m2) * np.cos(np.angle(m2) - 2 * mu) - Rb ** 4) / (1 - Rb) ** 2), rel=1e-10)
nt_ = len(t0)
check.near('Rayleigh Z = nR̄²', r['rayleigh']['Z'], float(nt_ * Rb ** 2), rel=1e-12)
check.near('Rayleigh p: Zar\'s exp(√(1 + 4n + 4(n² − R²)) − (1 + 2n))', r['rayleigh']['p'], float(np.exp(np.sqrt(1 + 4 * nt_ + 4 * (nt_ ** 2 - (nt_ * Rb) ** 2)) - (1 + 2 * nt_))), rel=1e-9)
v = float(nt_ * Rb * np.cos(np.angle(np.mean(np.exp(1j * t0))) - np.deg2rad(210)))
check.near('V = nR̄ cos(mean − 210°)', r['vtest']['V'], v, rel=1e-12)
check.near('V test p = 1 − Φ(V√(2/n))', r['vtest']['p'], float(stats.norm.sf(v * np.sqrt(2 / nt_))), rel=1e-12)
if pg is not None:
    z, p = pg.circ_rayleigh(t0)
    check.near('Rayleigh Z = pingouin', r['rayleigh']['Z'], float(z), rel=1e-12)
    check.near('Rayleigh p = pingouin', r['rayleigh']['p'], float(p), rel=1e-9)
    v_, pv = pg.circ_vtest(t0, dir=np.deg2rad(210))
    check.near('V = pingouin circ_vtest', r['vtest']['V'], float(v_), rel=1e-12)
    check.near('V test p = pingouin\'s (where it is not rounded to 0)', r['vtest']['p'], float(pv), rel=1e-6, abs_=1e-12)

# ---- the median direction against a brute-force search -----------------------------------
grid = np.deg2rad(np.arange(0, 360, 0.001))
for label, sample in (('odd n', t0[:31]), ('even n', t0[:30]), ('all', t0)):
    tt = table({'a': np.rad2deg(sample)})
    rr = call('circular.summary', table=tt, column='a')
    dd = np.array([np.mean(cdist(sample, g)) for g in grid])
    check.near(f'median ({label}): its mean distance = the least on a 0.001° grid', np.deg2rad(rr['median_dist']), float(dd.min()), rel=1e-7)
    check.near(f'median ({label}): the mean distance at it', float(np.mean(cdist(sample, np.deg2rad(rr['median'])))), float(dd.min()), rel=1e-7)
    if len(sample) % 2:
        check(f'median ({label}) is one of the angles', bool(np.min(cdist(sample, np.deg2rad(rr['median']))) < 1e-9), True)
    else:
        # the middle of the flat arc between the two middle angles
        flat = grid[dd <= dd.min() + 1e-12]
        check.near(f'median ({label}) = the middle of the flat arc of least distance', rr['median'], float(np.rad2deg(stats.circmean(flat)) % 360), rel=1e-5)
        check(f'median ({label}): one flat arc, one median', rr['median_ties'], 1)

# ---- intervals for the mean direction: the formulas, then their coverage -----------------
lo = {x['method']: x for x in r['ci']['rows']}
vm_row = lo['von Mises (Upton 1986)']
nn = len(t0)
Rn = nn * Rb
c2 = stats.chi2.ppf(0.95, 1)
h = np.arccos(np.sqrt(2 * nn * (2 * Rn ** 2 - nn * c2) / (4 * nn - c2)) / Rn) if Rb < 0.9 else np.arccos(np.sqrt(nn ** 2 - (nn ** 2 - Rn ** 2) * np.exp(c2 / nn)) / Rn)
check.near('Upton\'s interval (Zar\'s form): the half width', vm_row['half'], float(np.rad2deg(h)), rel=1e-10)
check.near('Upton\'s interval: the lower limit', vm_row['lower'], float(np.rad2deg(mu - h) % 360), rel=1e-10)
hf = np.arcsin(stats.norm.ppf(0.975) * np.sqrt((1 - rho2) / (2 * nn * Rb ** 2)))
fi_row = lo['Any unimodal, large n (Fisher 1993)']
check.near('Fisher\'s interval: arcsin(z σ̂), σ̂² = (1 − ρ₂)/(2nR̄²)', fi_row['half'], float(np.rad2deg(hf)), rel=1e-10)
check.near('Fisher\'s interval: the upper limit', fi_row['upper'], float(np.rad2deg(mu + hf) % 360), rel=1e-10)
# R̄ above 0.9: Upton's other formula
tc = np.deg2rad(40 + rng.normal(0, 8, 25))
rc = call('circular.summary', table=table({'a': np.rad2deg(tc)}), column='a')
Rc = abs(np.mean(np.exp(1j * tc)))
check('a concentrated sample has R̄ above 0.9', bool(Rc > 0.9), True)
hc = np.arccos(np.sqrt(25 ** 2 - (25 ** 2 - (25 * Rc) ** 2) * np.exp(c2 / 25)) / (25 * Rc))
check.near('Upton\'s interval for R̄ ≥ 0.9', rc['ci']['rows'][0]['half'], float(np.rad2deg(hc)), rel=1e-10)
# nearly uniform: no interval from the data
tu = rng.uniform(0, TAU, 12)
ru = call('circular.summary', table=table({'a': np.rad2deg(tu)}), column='a')
Ru = abs(np.mean(np.exp(1j * tu)))
check('R̄ below √(χ²/2n): no von Mises interval', (ru['ci']['rows'][0]['lower'] is None) == bool(Ru < np.sqrt(c2 / 24)), True)
# coverage by simulation: von Mises samples of 30 with κ = 2, true mean 1 radian
cover_u = cover_f = total = 0
for _ in range(1500):
    s = stats.vonmises.rvs(2.0, loc=1.0, size=30, random_state=rng)
    Cm, Sm, Rm, mm = C._moments(s)
    r2 = float(np.mean(np.cos(2 * (s - mm))))
    hu, hff = C.mean_ci(30, Rm, r2, 0.05)
    total += 1
    cover_u += hu is not None and cdist(mm, 1.0) <= hu
    cover_f += hff is not None and cdist(mm, 1.0) <= hff
check('Upton\'s 95% interval covers the true mean direction 93-97% of the time (1500 samples)', 0.93 <= cover_u / total <= 0.97, True)
check('Fisher\'s 95% interval covers it 92-97% of the time (n = 30, a little below 25 it would drift)', 0.92 <= cover_f / total <= 0.97, True)
print(f'   (coverage: Upton {cover_u / total:.3f}, Fisher {cover_f / total:.3f})')

# ---- the Rayleigh test: its size under uniformity ------------------------------------------
rej = sum(C.rayleigh(20, abs(np.mean(np.exp(1j * rng.uniform(0, TAU, 20)))))[1] < 0.05 for _ in range(4000))
check('Rayleigh test at α = 0.05 rejects 4-6% of uniform samples of 20', 0.04 <= rej / 4000 <= 0.06, True)

# ---- units: degrees, radians and a clock describe the same angles ---------------------------
for units, period, vals in (('radians', None, t0), ('clock', 24.0, t0 * 24 / TAU), ('clock', 7.0, t0 * 7 / TAU)):
    rr = call('circular.summary', table=table({'a': vals}), column='a', units=units, period=period)
    P = TAU if units == 'radians' else period
    check.near(f'{units} {period or ""}: R̄ is the same', rr['rbar'], r['rbar'], rel=1e-12)
    check.near(f'{units} {period or ""}: the mean direction in its units', rr['mean'], r['mean'] * P / 360, rel=1e-12)
    check.near(f'{units} {period or ""}: the circular SD in its units', rr['circ_sd'], r['circ_sd'] * P / 360, rel=1e-12)
    check.near(f'{units} {period or ""}: the median in its units', rr['median'], r['median'] * P / 360, rel=1e-9)
try:
    call('circular.summary', table=table({'a': [1.0, 2, 3]}), column='a', units='clock', period=0)
    check('a clock with period 0 is refused', False, True)
except Exception as e:
    check('a clock with period 0 is refused', 'period' in str(e), True)

# ---- binned axial data with Freq: pingouin's orientation tuning data (Berens 2009) ----------
if pg is not None:
    ori = pg.read_dataset('circular')
    tb = table({'orientation': ori['Orientation'].to_numpy(float), 'spikes': ori['N1Spikes'].to_numpy(float)})
    # orientations repeat every 180°: a clock of period 180 doubles them, as pingouin's circ_axial
    ra = call('circular.summary', table=tb, column='orientation', units='clock', period=180, freq='spikes', v_dir=67.5)
    ax = pg.circ_axial(np.deg2rad(ori['Orientation'].to_numpy(float)), 2)
    w = ori['N1Spikes'].to_numpy(float)
    check('Freq: n is the spike count', ra['n'], int(w.sum()))
    check.near('axial data with Freq: R̄ = pingouin circ_r(circ_axial, w)', ra['rbar'], float(pg.circ_r(ax, w)), rel=1e-12)
    check.near('axial data with Freq: the mean orientation = circ_mean / 2', ra['mean'], float(np.rad2deg(pg.circ_mean(ax, w)) % 360 / 2), rel=1e-12)
    z, p = pg.circ_rayleigh(ax, w)
    check.near('axial data with Freq: Rayleigh Z = pingouin', ra['rayleigh']['Z'], float(z), rel=1e-12)
    check.near('axial data with Freq: Rayleigh p = pingouin', ra['rayleigh']['p'], float(p), rel=1e-9, abs_=1e-300)
    v, _ = pg.circ_vtest(ax, dir=np.deg2rad(135), w=w)
    check.near('axial data with Freq: V = pingouin circ_vtest', ra['vtest']['V'], float(v), rel=1e-12)
    rep = pd.DataFrame({'orientation': np.repeat(ori['Orientation'].to_numpy(float), ori['N1Spikes'].to_numpy(int))})
    rr = call('circular.summary', table=table({'orientation': rep['orientation'].to_numpy()}), column='orientation', units='clock', period=180)
    check('Freq = the same rows repeated (Berens\'s counts)', (rr['n'], round(rr['rbar'], 12), round(rr['median'], 9)), (ra['n'], round(ra['rbar'], 12), round(ra['median'], 9)))
# Freq on a simulated table: the same as its rows repeated
fq_ = rng.integers(1, 4, 30).astype(float)
aq_ = np.rad2deg(stats.vonmises.rvs(1.5, loc=2.0, size=30, random_state=rng) % TAU)
rq = call('circular.summary', table=table({'a': aq_, 'f': fq_}), column='a', freq='f', v_dir=100)
rq2 = call('circular.summary', table=table({'a': np.repeat(aq_, fq_.astype(int))}), column='a', v_dir=100)
check('Freq = the same rows repeated (n, R̄, median, V)', (rq['n'], round(rq['rbar'], 12), round(rq['median'], 9), round(rq['vtest']['V'], 9)),
      (rq2['n'], round(rq2['rbar'], 12), round(rq2['median'], 9), round(rq2['vtest']['V'], 9)))
try:
    call('circular.summary', table=table({'a': [1.0, 2, 3], 'f': [1, 1.5, 2]}), column='a', freq='f')
    check('a fractional Freq is refused', False, True)
except Exception as e:
    check('a fractional Freq is refused', 'whole numbers' in str(e), True)

# ---- the von Mises fit ----------------------------------------------------------------------
vm = call('circular.vonmises', table=tid, column='dir')
k_sc, mu_sc, _ = stats.vonmises.fit(t0, fscale=1)
check.near('κ̂ = scipy vonmises.fit', vm['kappa'], float(k_sc), rel=1e-9)
check.near('μ̂ = scipy vonmises.fit, in degrees', vm['mu'], float(np.rad2deg(mu_sc) % 360), rel=1e-9)
check.near('κ̂ solves A₁(κ) = R̄', float(i1e(vm['kappa']) / i0e(vm['kappa'])), float(Rb), rel=1e-12)


def ll(mu_, k_):
    return float(np.sum(k_ * np.cos(t0 - mu_) - np.log(TAU * i0e(k_)) - k_))


kk, mm = vm['kappa'], np.deg2rad(vm['mu'])
hstep = 1e-4
d2k = (ll(mm, kk + hstep) - 2 * ll(mm, kk) + ll(mm, kk - hstep)) / hstep ** 2
d2m = (ll(mm + hstep, kk) - 2 * ll(mm, kk) + ll(mm - hstep, kk)) / hstep ** 2
check.near('SE of κ = 1/√(observed information), numerically', vm['se_kappa'], float(1 / np.sqrt(-d2k)), rel=1e-5)
check.near('SE of μ = 1/√(observed information), in degrees', vm['se_mu'], float(np.rad2deg(1 / np.sqrt(-d2m))), rel=1e-5)
est = {e['term']: e for e in vm['estimates']['rows']}
kr = est['κ (concentration)']
top = ll(mm, kk)
check.near('κ\'s likelihood-ratio interval: 2(ℓ̂ − ℓ) = χ²₁(0.95) at the lower limit', 2 * (top - ll(mm, kr['lower'])), float(stats.chi2.ppf(0.95, 1)), rel=1e-8)
check.near('and at the upper limit', 2 * (top - ll(mm, kr['upper'])), float(stats.chi2.ppf(0.95, 1)), rel=1e-8)
check.near('the log likelihood', vm['loglik'], top, rel=1e-12)
kf = kk
small = max(kf - 2 / (nn * kf), 0) if kf < 2 else (nn - 1) ** 3 * kf / (nn ** 3 + nn)
check.near('Best and Fisher\'s small-sample κ', vm['kappa_small'], float(small), rel=1e-12)
dens = np.asarray(vm['curve']['density'])
xs = np.asarray(vm['curve']['x'])
check.near('the fitted density integrates to 1 (per degree)', float(np.trapezoid(dens, xs)), 1.0, rel=1e-6)
check('every angle the same: κ is infinite, an error', 'error' in call('circular.vonmises', table=table({'a': [10.0] * 5}), column='a'), True)
# the truth of a large simulated sample
big = stats.vonmises.rvs(2.5, loc=np.deg2rad(220), size=6000, random_state=rng) % TAU
vb = call('circular.vonmises', table=table({'a': np.rad2deg(big)}), column='a')
check('simulated truth: μ = 220° recovered within 2°', abs(vb['mu'] - 220) < 2, True)
check('simulated truth: κ = 2.5 recovered within 0.15', abs(vb['kappa'] - 2.5) < 0.15, True)

# ---- circular-linear and circular-circular correlation ---------------------------------------
x_lin = 4 + 2.5 * np.cos(th - np.deg2rad(250)) + rng.normal(0, 1, n)
th2 = (th + np.deg2rad(15) + stats.vonmises.rvs(4.0, size=n, random_state=rng)) % TAU
tx = table({'dir': deg, 'speed': x_lin, 'dir2': np.rad2deg(th2)})
cl = call('circular.linear', table=tx, y='dir', x='speed')
xl_ = x_lin[ok]
rxc_, rxs_, rcs_ = np.corrcoef(xl_, np.cos(t0))[0, 1], np.corrcoef(xl_, np.sin(t0))[0, 1], np.corrcoef(np.cos(t0), np.sin(t0))[0, 1]
R2_ = (rxc_ ** 2 + rxs_ ** 2 - 2 * rxc_ * rxs_ * rcs_) / (1 - rcs_ ** 2)
check.near('circular-linear R² (Mardia 1976) written out', cl['r2'], float(R2_), rel=1e-12)
check.near('circular-linear p: nR² against χ² on 2 DF', cl['p'], float(stats.chi2.sf(len(t0) * R2_, 2)), rel=1e-10)
if pg is not None:
    rp, pp = pg.circ_corrcl(t0, x_lin[ok])
    check.near('circular-linear R = pingouin circ_corrcl', cl['r'], float(rp), rel=1e-12)
    check.near('circular-linear p = pingouin', cl['p'], float(pp), rel=1e-10)
check('circular-linear: its n', cl['n'], int(ok.sum()))
cc = call('circular.circular', table=tx, y='dir', x='dir2')
sa_ = np.sin(t0 - stats.circmean(t0))
sb_ = np.sin(th2[ok] - stats.circmean(th2[ok]))
rjs_ = np.sum(sa_ * sb_) / np.sqrt(np.sum(sa_ ** 2) * np.sum(sb_ ** 2))
zjs_ = rjs_ * np.sqrt(len(t0) * np.mean(sa_ ** 2) * np.mean(sb_ ** 2) / np.mean(sa_ ** 2 * sb_ ** 2))
check.near('circular-circular r (Jammalamadaka and SenGupta) written out', cc['r'], float(rjs_), rel=1e-12)
check.near('circular-circular p: 2(1 − Φ(|z|))', cc['p'], float(2 * stats.norm.sf(abs(zjs_))), rel=1e-10)
if pg is not None:
    rc_, pc_ = pg.circ_corrcc(t0, th2[ok])
    check.near('circular-circular r = pingouin circ_corrcc', cc['r'], float(rc_), rel=1e-12)
    check.near('circular-circular p = pingouin', cc['p'], float(pc_), rel=1e-10)
ccs = call('circular.circular', table=tx, y='dir2', x='dir')
check.near('circular-circular r is symmetric', ccs['r'], cc['r'], rel=1e-12)
check('the same column twice is refused', 'error' in call('circular.circular', table=tx, y='dir', x='dir'), True)

# ---- groups: Watson-Williams and the uniform scores -------------------------------------------
g_lab = np.array(['winter'] * 30 + ['summer'] * 30)
tg_ = np.concatenate([stats.vonmises.rvs(2.5, loc=np.deg2rad(220), size=30, random_state=rng), stats.vonmises.rvs(2.0, loc=np.deg2rad(260), size=30, random_state=rng)]) % TAU
tg = table({'dir': np.rad2deg(tg_), 'season': g_lab.tolist()}, levels={'season': ['winter', 'summer']})
gr = call('circular.groups', table=tg, y='dir', x='season')
check('groups in the table\'s level order', [x['level'] for x in gr['groups']], ['winter', 'summer'])
for gi, lv in enumerate(['winter', 'summer']):
    s = tg_[g_lab == lv]
    check.near(f'{lv}: the mean direction = scipy circmean', gr['groups'][gi]['mean'], float(np.rad2deg(stats.circmean(s))), rel=1e-12)
    check.near(f'{lv}: R̄', gr['groups'][gi]['rbar'], float(abs(np.mean(np.exp(1j * s)))), rel=1e-12)
Rj = np.array([abs(np.sum(np.exp(1j * tg_[g_lab == lv]))) for lv in ('winter', 'summer')])
Rall = abs(np.sum(np.exp(1j * tg_)))
kap = brentq(lambda k: i1e(k) / i0e(k) - Rj.sum() / 60, 1e-9, 1e4)
F = (1 + 3 / (8 * kap)) * ((Rj.sum() - Rall) / 1) / ((60 - Rj.sum()) / 58)
check.near('Watson-Williams κ̂ = A₁⁻¹(ΣRⱼ/n)', gr['ww']['kappa'], float(kap), rel=1e-9)
check.near('Watson-Williams F (Mardia and Jupp 2000)', gr['ww']['F'], float(F), rel=1e-9)
check.near('Watson-Williams p on (1, 58) DF', gr['ww']['p'], float(stats.f.sf(F, 1, 58)), rel=1e-8)
rk = stats.rankdata(tg_)
gam = TAU * rk / 60
W = sum(2 * (np.cos(gam[g_lab == lv]).sum() ** 2 + np.sin(gam[g_lab == lv]).sum() ** 2) / 30 for lv in ('winter', 'summer'))
check.near('uniform scores W (Mardia-Watson-Wheeler)', gr['uscores']['W'], float(W), rel=1e-11)
check.near('uniform scores p on 2 DF', gr['uscores']['p'], float(stats.chi2.sf(W, 2)), rel=1e-10)
# three groups, one with a tie
t3 = np.concatenate([tg_, [tg_[0]]])
g3 = np.concatenate([g_lab, ['spring']])
g3[:10] = 'spring'
gr3 = call('circular.groups', table=table({'dir': np.rad2deg(t3), 'g': g3.tolist()}, levels={'g': ['winter', 'spring', 'summer']}), y='dir', x='g')
check('three groups: 2 and 58 DF', (gr3['ww']['df_num'], gr3['ww']['df_den']), (2, 58))
check('three groups: uniform scores on 4 DF', gr3['uscores']['df'], 4)
check('tied angles are noted', any('Tied' in s for s in gr3['notes']), True)
# the size of both tests under the null: one mean direction, κ = 2
rej_w = rej_u = 0
for _ in range(300):
    s = stats.vonmises.rvs(2.0, loc=1.0, size=40, random_state=rng) % TAU
    tt = table({'a': np.rad2deg(s), 'g': ['p'] * 20 + ['q'] * 20})
    gg = call('circular.groups', table=tt, y='a', x='g')
    rej_w += gg['ww']['p'] < 0.05
    rej_u += gg['uscores']['p'] < 0.05
check('Watson-Williams at α = 0.05 rejects 2-9% of null samples (300)', 0.02 <= rej_w / 300 <= 0.09, True)
check('the uniform-scores test rejects 1-9% of them', 0.01 <= rej_u / 300 <= 0.09, True)
print(f'   (null rejections: Watson-Williams {rej_w / 300:.3f}, uniform scores {rej_u / 300:.3f})')
low = call('circular.groups', table=table({'a': np.rad2deg(rng.uniform(0, TAU, 40)), 'g': ['p'] * 20 + ['q'] * 20}), y='a', x='g')
check('diffuse groups: the Watson-Williams assumption is flagged', any('κ̂' in s or '0.45' in s for s in low['notes']), True)
check('a continuous X is not a grouping', 'error' in call('circular.groups', table=tx, y='dir', x='speed'), True)

# ---- the code under each result, on a CSV export --------------------------------------------
cols = {'dir': deg, 'speed': x_lin, 'dir2': np.rad2deg(th2)}
ns = code_ns(cols, r['code'], 'the summary')
if 'm' in ns:
    check.near('its code: the mean direction', float(np.rad2deg(ns['m'])), r['mean'], rel=1e-12)
    check.near('its code: R̄', float(ns['R']), r['rbar'], rel=1e-12)
    check.near('its code: Upton\'s half width', float(np.rad2deg(ns['h'])), vm_row['half'], rel=1e-10)
    check.near('its code: Fisher\'s half width', float(np.rad2deg(ns['hf'])), fi_row['half'], rel=1e-10)
    check.near('its code: the V statistic', float(ns['V']), r['vtest']['V'], rel=1e-12)
ns = code_ns(cols, vm['code'], 'the von Mises fit')
if 'kappa' in ns:
    check.near('its code: κ', float(ns['kappa']), vm['kappa'], rel=1e-9)
ns = code_ns(cols, cl['code'], 'the circular-linear correlation')
if 'R2' in ns:
    check.near('its code: R²', float(ns['R2']), cl['r2'], rel=1e-12)
ns = code_ns(cols, cc['code'], 'the circular-circular correlation')
if 'r' in ns:
    check.near('its code: r', float(ns['r']), cc['r'], rel=1e-12)
ns = code_ns({'dir': np.rad2deg(tg_), 'season': g_lab.tolist()}, gr['code'], 'the groups')
if 'F' in ns:
    check.near('its code: Watson-Williams F', float(ns['F']), gr['ww']['F'], rel=1e-8)
    check.near('its code: uniform scores W', float(ns['W']), gr['uscores']['W'], rel=1e-11)
if pg is not None:
    ns = code_ns({'orientation': ori['Orientation'].to_numpy(float), 'spikes': ori['N1Spikes'].to_numpy(float)}, ra['code'], 'the summary with a clock and Freq')
    if 'R' in ns:
        check.near('its code with Freq: R̄', float(ns['R']), ra['rbar'], rel=1e-12)
        check.near('its code with a clock: the mean in its units', float(ns['m'] * 180 / TAU), ra['mean'], rel=1e-12)
# a By group: the code keeps the group's rows
rw = call('circular.summary', table=tg, column='dir', rows=[i for i in range(60) if g_lab[i] == 'summer'], where=[{'column': 'season', 'value': 'summer'}])
ns = code_ns({'dir': np.rad2deg(tg_), 'season': g_lab.tolist()}, rw['code'], 'a By group\'s summary')
if 'R' in ns:
    check.near('its code for a By group: R̄ of the group', float(ns['R']), rw['rbar'], rel=1e-12)

# ---- small and odd inputs ---------------------------------------------------------------------
check('one angle: an error', 'error' in call('circular.summary', table=table({'a': [10.0, None]}), column='a'), True)
two = call('circular.summary', table=table({'a': [0.0, 180.0]}), column='a')
check('opposite angles: R̄ 0, no mean direction', (round(two['rbar'], 12), two['mean']), (0.0, None))
check('opposite angles: no interval', [x['lower'] for x in two['ci']['rows']], [None, None])
wrap = call('circular.summary', table=table({'a': [350.0, 10.0, 355.0, 5.0]}), column='a')
check.near('angles on both sides of 0: the mean is 0 (not 180)', min(wrap['mean'], 360 - wrap['mean']), 0.0, abs_=1e-9)

# ---- the code on the whole table's CSV leaves out the rows the report leaves out ----------------
# (the page sends the report's rows; the code reads the whole table, as File > Export CSV writes it)
from smui import data as _D  # noqa: E402
from test_charts import run_snippet_more  # noqa: E402


def frame_of(tid):
    """The table as File > Export CSV writes it: every column, by name."""
    t = _D.TABLES[tid]
    out = {}
    for name, v in t['cols'].items():
        out[name] = np.asarray(v, dtype=float) if t['meta'][name]['dataType'] == 'numeric' else pd.Series(list(v), dtype=object)
    return pd.DataFrame(out)


def run_whole(tid, code, label):
    """Run a result's code on the whole table's CSV; its variables."""
    return code_ns({k: v for k, v in frame_of(tid).items()}, code, label)


n_ex = 80
th_ex = stats.vonmises.rvs(1.8, loc=np.deg2rad(230), size=n_ex, random_state=rng) % TAU
dir_ex = np.round(np.rad2deg(th_ex), 1)
sea_ex = rng.choice(['winter', 'summer'], n_ex).tolist()
sea_ex[4] = None
fq_ex = rng.integers(1, 4, n_ex).astype(float)
fq_ex[6] = 0.0
sp_ex = np.round(4 + 2 * np.cos(th_ex - 1) + rng.normal(0, 1, n_ex), 2)
dir2_ex = np.round(np.rad2deg((th_ex + stats.vonmises.rvs(4, loc=0.3, size=n_ex, random_state=rng)) % TAU), 1)
tex = table({'dir': dir_ex, 'season': sea_ex, 'f': fq_ex, 'speed': sp_ex, 'dir2': dir2_ex}, levels={'season': ['winter', 'summer']})
rows_ex = [r for r in range(n_ex) if r not in (2, 9, 30, 41)]          # four rows excluded in the page
ex = call('circular.summary', table=tex, column='dir', rows=rows_ex, freq='f')
check('the code drops the rows the report leaves out', 'df = df.drop(index=[2, 9, 30, 41])' in ex['code'], True)
ns = run_whole(tex, ex['code'], 'the summary with rows left out')
if 'R' in ns:
    check.near('its code on the whole table: the report\'s R̄ (excluded rows left out)', float(ns['R']), ex['rbar'], rel=1e-12)
    check.near('... and the report\'s mean direction', float(np.rad2deg(ns['m'])), ex['mean'], rel=1e-12)
winter = [r for r in rows_ex if sea_ex[r] == 'winter']
exw = call('circular.summary', table=tex, column='dir', rows=winter, freq='f', where=[{'column': 'season', 'value': 'winter'}])
ns = run_whole(tex, exw['code'], 'a By group with rows left out')
if 'R' in ns:
    check('a By group: the where line, then the group\'s rows left out', ('df = df[df["season"] == "winter"]' in exw['code'], 'df = df.drop(index=[' in exw['code']), (True, True))
    check.near('its code: the group\'s R̄ without its excluded rows', float(ns['R']), exw['rbar'], rel=1e-12)
for fn, extra, key, what in (('circular.vonmises', {'column': 'dir'}, 'kappa', 'κ'), ('circular.linear', {'y': 'dir', 'x': 'speed'}, 'R2', 'R²'),
                             ('circular.circular', {'y': 'dir', 'x': 'dir2'}, 'r', 'r'), ('circular.groups', {'y': 'dir', 'x': 'season'}, 'F', 'Watson-Williams F')):
    res = call(fn, table=tex, rows=rows_ex, freq='f', **extra)
    ns = run_whole(tex, res['code'], f'{fn} with rows left out')
    want = {'kappa': res.get('kappa'), 'R2': res.get('r2'), 'r': res.get('r'), 'F': (res.get('ww') or {}).get('F')}[key]
    if key in ns:
        check.near(f'{fn}: its code on the whole table gives the report\'s {what}', float(ns[key]), want, rel=1e-8)

# ---- the graphs' matplotlib code, run with Agg on the CSV, against the report's numbers ----------
PAL = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
TICKS = [[d / 360, f'{d}°'] for d in (0, 45, 90, 135, 180, 225, 270, 315)]
tmpdir = tempfile.mkdtemp(prefix='smui-circ-charts-')


def figure(code, tid, label):
    out, err = run_snippet_more(code, frame_of(tid), 'data', tmpdir)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
    check(f'{label}: one figure', len(out['figures']) if out else 0, 1)
    return out['figures'][0] if out and out['figures'] else None


def xy_page(f, r, compass=True):
    """The page's place on the circle (smui-p-circular.js xy)."""
    return (r * math.sin(TAU * f), r * math.cos(TAU * f)) if compass else (r * math.cos(TAU * f), r * math.sin(TAU * f))


def page_dots(vals, P, compass=True):
    """The dot plot's dots as the page places them: 72 bins, stacked outward in row order."""
    fr = [((v % P) / P) for v in vals]
    idx = [min(71, math.floor(f * 72)) for f in fr]
    most = max([1] + [idx.count(k) for k in set(idx)])
    step = min(0.065, 0.55 / most)
    seen, pos = {}, []
    for f, k in zip(fr, idx):
        s_ = seen.get(k, 0)
        seen[k] = s_ + 1
        pos.append(xy_page(f, 1.07 + s_ * step, compass))
    return pos, 1.07 + (most - 1) * step + 0.08


def near_pts(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for p, q in zip(a, b))


drawn = [r for r in rows_ex if np.isfinite(dir_ex[r]) and fq_ex[r] > 0]      # the dots: each row once
for compass in (True, False):
    tag = 'compass' if compass else 'mathematical'
    plot = {'compass': compass, 'ticks': TICKS, 'bins': 24, 'area': True, 'vm': True}
    sm_ = call('circular.summary', table=tex, column='dir', rows=rows_ex, freq='f', plot=plot)
    F = figure(sm_['dot_code'], tex, f'dot plot ({tag})')
    if F:
        A = F['axes'][0]
        pts = A['scatter'][0]['xy'] if A['scatter'] else []
        want, reach = page_dots([dir_ex[r] for r in drawn], 360.0, compass)
        check(f'dot plot ({tag}): a dot for each row of the report (Freq draws it once), where the page puts it', near_pts(pts, want), True)
        check(f'dot plot ({tag}): the dots in the points\' colour', set(A['scatter'][0]['colors']), {'#2f6690ff'})
        tip = [a for a in A['annotations'] if a['s'] == '']
        mt = xy_page(sm_['mean'] / 360, sm_['rbar'], compass)
        check(f'dot plot ({tag}): the mean vector ends at the mean direction, R̄ out', bool(tip) and near_pts([tip[0]['xy']], [mt], 1e-9), True)
        check(f'dot plot ({tag}): in red', tip[0]['color'] if tip else None, '#b0413e')
        ci = sm_['ci']['rows'][0]
        f0, f1 = (ci['lower'] % 360) / 360, (ci['upper'] % 360) / 360
        f1 = f1 + 1 if f1 < f0 else f1
        arc = [ln for ln in A['lines'] if len(ln['x']) == 41]
        check(f'dot plot ({tag}): the von Mises interval as an arc from its lower limit to its upper', bool(arc) and near_pts([(arc[0]['x'][0], arc[0]['y'][0]), (arc[0]['x'][-1], arc[0]['y'][-1])],
                                                                                                                      [xy_page(f0, 0.97, compass), xy_page(f1, 0.97, compass)], 1e-9), True)
        circle = [ln for ln in A['lines'] if len(ln['x']) == 181]
        check(f'dot plot ({tag}): the unit circle', bool(circle) and max(abs(math.hypot(a, b) - 1) for a, b in zip(circle[0]['x'], circle[0]['y'])) < 1e-12, True)
        labels = [(t['s'], t['xy']) for t in A['annotations'] if t['s']]
        check(f'dot plot ({tag}): the labels around the circle', [lab for lab, _ in labels], [t for _, t in TICKS])
        check(f'dot plot ({tag}): at radius 0.8, in their places', near_pts([xy for _, xy in labels], [xy_page(f, 0.8, compass) for f, _ in TICKS]), True)
        L = max(1.25, reach)
        check(f'dot plot ({tag}): the range and no axes', (A['xlim'], A['ylim'], A['visible']), ([-L, L], [-L, L], False))
        check(f'dot plot ({tag}): the title and the size', (A['title'], F['size']), ('dir circular dot plot', [3.4, 3.4]))
    F = figure(sm_['rose_code'], tex, f'rose diagram ({tag})')
    if F:
        A = F['axes'][0]
        cnt = np.zeros(24)
        for r in drawn:
            cnt[min(23, math.floor(((dir_ex[r] % 360) / 360) * 24))] += fq_ex[r]
        check.near(f'rose ({tag}): the bars are √(the Freq-weighted counts of the 24 bins)', max(abs(b['h'] - w) for b, w in zip(A['bars'], np.sqrt(cnt))) if len(A['bars']) == 24 else 1e9, 0.0, abs_=1e-12)
        check.near(f'rose ({tag}): each bin a 24th of the turn, from 0', max(abs(b['x'] - TAU * j / 24) + abs(b['w'] - TAU / 24) for j, b in enumerate(A['bars'])) if A['bars'] else 1e9, 0.0, abs_=1e-12)
        vmr = call('circular.vonmises', table=tex, column='dir', rows=rows_ex, freq='f')
        top = float(np.sqrt(cnt).max())
        curve = [ln for ln in A['lines'] if len(ln['x']) == 361]
        want_r = np.sqrt(vmr['n'] * np.asarray(vmr['curve']['density']) * 360 / 24)
        check(f'rose ({tag}): the fitted von Mises as counts per bin, the report\'s fit', bool(curve) and close_arr(curve[0]['y'], want_r, 1e-6)
              and close_arr(curve[0]['x'], np.asarray(vmr['curve']['x']) * TAU / 360, 1e-12), True)
        mean_ln = [ln for ln in A['lines'] if len(ln['x']) == 2 and ln['color'] == '#b0413eff']
        check(f'rose ({tag}): the mean direction, R̄ times the longest bar', bool(mean_ln) and close_arr(mean_ln[0]['x'], [np.deg2rad(sm_['mean'])] * 2, 1e-12)
              and close_arr(mean_ln[0]['y'], [0, sm_['rbar'] * top], 1e-12), True)
        check.near(f'rose ({tag}): the radial range', A['ylim'][1], top * 1.04, rel=1e-12)
        check(f'rose ({tag}): the labels around the circle', A['xticklabels'], [t for _, t in TICKS])
        check(f'rose ({tag}): the title', A['title'], 'dir rose diagram')
# the rose with the radius the count, 12 bins, no fit
sm_ = call('circular.summary', table=tex, column='dir', rows=rows_ex, freq='f', plot={'compass': True, 'ticks': TICKS, 'bins': 12, 'area': False, 'vm': False})
F = figure(sm_['rose_code'], tex, 'rose diagram (the radius the count)')
if F:
    A = F['axes'][0]
    cnt = np.zeros(12)
    for r in drawn:
        cnt[min(11, math.floor(((dir_ex[r] % 360) / 360) * 12))] += fq_ex[r]
    check('rose (the radius the count): 12 bars, the counts, no curve', ([b['h'] for b in A['bars']], [ln for ln in A['lines'] if len(ln['x']) == 361]), (cnt.tolist(), []))
# grouped by season: the dots in the groups' colours, each group's mean vector
sm_ = call('circular.summary', table=tex, column='dir', rows=rows_ex, freq='f', plot={'compass': True, 'ticks': TICKS, 'bins': 24, 'area': True, 'vm': False,
                                                                                         'group': 'season', 'labels': ['Winter', 'Summer']})
gr_ = call('circular.groups', table=tex, y='dir', x='season', rows=rows_ex, freq='f')
F = figure(sm_['dot_code'], tex, 'dot plot by season')
if F:
    A = F['axes'][0]
    pos, _ = page_dots([dir_ex[r] for r in drawn], 360.0)
    for i, lv in enumerate(['winter', 'summer']):
        sc_ = [x for x in A['scatter'] if x['label'] == ['Winter', 'Summer'][i]]
        want = [p for p, r in zip(pos, drawn) if sea_ex[r] == lv]
        check(f'dot plot by season: the {lv} dots, where the page puts them (a row without a season keeps its place, undrawn)', bool(sc_) and near_pts(sc_[0]['xy'], want), True)
        check(f'dot plot by season: {lv} in the palette\'s colour {i + 1}', set(sc_[0]['colors']) if sc_ else None, {PAL[i] + 'ff'})
        g = [x for x in gr_['groups'] if x['level'] == lv][0]
        tips = [a for a in A['annotations'] if a['s'] == '' and a['color'] == PAL[i]]
        check(f'dot plot by season: the {lv} mean vector, the groups\' report', bool(tips) and near_pts([tips[0]['xy']], [xy_page(g['mean'] / 360, g['rbar'])], 1e-9), True)
    check('dot plot by season: the legend names the groups as the page does', F['legend'], ['Winter', 'Summer'])
    check('dot plot by season: no overall mean vector, no interval', ([a for a in A['annotations'] if a['s'] == '' and a['color'] == '#b0413e'], [ln for ln in A['lines'] if len(ln['x']) == 41]), ([], []))
    check('dot plot by season: the size', F['size'], [3.4, 3.64])
# an angle by a continuous X, and by another angle
both = [r for r in rows_ex if fq_ex[r] > 0]
for fn, xname, sz, two in (('circular.linear', 'speed', [3.8, 3.0], False), ('circular.circular', 'dir2', [3.4, 3.2], True)):
    res = call(fn, table=tex, y='dir', x=xname, rows=rows_ex, freq='f', plot={'ticks': TICKS})
    F = figure(res['plot_code'], tex, f'dir by {xname}')
    if F:
        A = F['axes'][0]
        xv = {'speed': sp_ex, 'dir2': dir2_ex}[xname]
        want = [((xv[r] % 360) if two else xv[r], dir_ex[r] % 360) for r in both]
        check(f'dir by {xname}: a point for each row (Freq draws it once), the angle on its circle', near_pts(A['scatter'][0]['xy'] if A['scatter'] else [], want, 1e-12), True)
        check(f'dir by {xname}: the angle axis 0 to 360 with the circle\'s labels', (A['ylim'], A['yticklabels'], A['yticks']), ([0.0, 360.0], [t for _, t in TICKS], [360 * f for f, _ in TICKS]))
        if two:
            check(f'dir by {xname}: the other angle too', (A['xlim'], A['xticklabels']), ([0.0, 360.0], [t for _, t in TICKS]))
        check(f'dir by {xname}: the titles and the size', (A['xlabel'], A['ylabel'], A['title'], F['size']), (xname, 'dir', f'dir by {xname}', sz))

sys.exit(check.done())
