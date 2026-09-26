#!/usr/bin/env python3
"""
High-precision references for resources/tests/farf31/test-model.js.

An implementation of the FARF31 transfer functions that shares no code and no
formulation with farf31-model.js: the recursion of SKB TR 90-01, Appendix C,
Proposition 3 (the P_ijk and Q_ijkl coefficients), evaluated with mpmath at
40 significant digits and inverted with mpmath's own Talbot routine. With
sorption on the fracture surfaces (Ka, Rf = 1 + Ka aw, the page's addition)
the recursion takes F_k = Rf_k (s + lambda_k) + aw De_k h_k tanh(h_k x0) and
the parent's term Rf_(i-1) P_(i-1,j,k); Ka = 0 is TR 90-01's as printed.

For the four reference cases (made-up inputs, FARF31 1.2 outputs) it writes,
at the times of FARF31's out.ts and out.response, and for the made-up cases
`fsorb` (fracture sorption, which FARF31 does not have) and `tail-Pe-C` (a
sharp front and a long slow tail: a matrix that holds C times the water it
faces and fills over 250 travel times, Pe 30 to 300; the working precision
grows with Pe, since the transform reaches e^(Pe/2) at its branch point) at
times of their own:
  - the output release of every nuclide, from the step and ramp responses
    L^-1[T/s] and L^-1[T/s^2] summed over the jumps and slope changes of the
    piecewise-linear input (exact for such an input, and harmless at this
    precision despite the cancellation);
  - the unit responses h_ij = L^-1[T_ij];
  - T_ij(0), the integral of each response.

    python3 resources/tests/farf31/gen-mpmath-ref.py [reference-cases dir] [--only CASE]

The reference directory defaults to $FARF31_REF or
~/Downloads/Farf31-SKB-new/reference-cases. Takes a few minutes; writes
resources/tests/farf31/ref/mpmath-ref.json (--only recomputes one case and
keeps the others; a trailing * takes every case the name begins, as in
--only 'tail-*'). Each case also carries its input, as run() takes it.
"""
import json, os, re, sys, time
import mpmath as mp

mp.mp.dps = 40
HERE = os.path.dirname(os.path.abspath(__file__))
_pos = [a for k, a in enumerate(sys.argv[1:], 1) if not a.startswith('--') and sys.argv[k - 1] != '--only']
REF = _pos[0] if _pos else os.environ.get('FARF31_REF', os.path.expanduser('~/Downloads/Farf31-SKB-new/reference-cases'))

# The cases, as their in.dat/in.par/in.ts say (all made up). A nuclide is
# (name, half-life a, Kd m3/kg, De m2/a[, Ka m]).
CASES = {
    'single': dict(tw=50, Pe=20, aw=500, eps=0.004, x0=0.5,
                   nuc=[('I129', 1.57e7, 0.0, 1e-6)], link=[], src={'I129': [(0, 1), (1e6, 1)]}),
    'pulse': dict(tw=200, Pe=5, aw=1500, eps=0.003, x0=3,
                  nuc=[('Ni59', 7.6e4, 0.01, 5e-6)], link=[],
                  src={'Ni59': [(1000, 0), (1000.1, 1), (1100, 1), (1100.1, 0), (1e7, 0)]}),
    'elem': dict(tw=30, Pe=50, aw=3000, eps=0.002, x0=0.2,
                 nuc=[('Ra226', 1600, 0.02, 2e-6), ('Pb210', 22.2, 0.5, 8e-6)], link=[1],
                 src={'Ra226': [(0, 1e-3), (2e4, 1e-3), (2e4, 0), (1e6, 0)]}),
    'chain': dict(tw=150, Pe=15, aw=800, eps=0.005, x0=1.5,
                  nuc=[('Am241', 432.6, 2.0, 4e-6), ('Np237', 2.144e6, 0.1, 4e-6),
                       ('U233', 1.592e5, 0.05, 4e-6), ('Th229', 7340, 1.0, 4e-6)], link=[1, 2, 3],
                  src={'Am241': [(0, 1e-2), (1e3, 5e-3), (1e4, 1e-4), (1e5, 0)], 'U233': [(0, 2e-4), (1e6, 2e-4)]}),
    # made up: a chain with sorption on the fracture surfaces, element-specific De
    'fsorb': dict(tw=80, Pe=12, aw=600, eps=0.004, x0=0.6,
                  nuc=[('Th230', 7.54e4, 0.3, 2e-6, 0.02), ('Ra226', 1600, 0.01, 3e-6, 0.003), ('Pb210', 22.2, 0.1, 5e-6, 0.01)],
                  link=[1, 2],
                  src={'Th230': [(0, 1e-3), (2e4, 1e-3), (6e4, 0)], 'Ra226': [(0, 2e-4), (1e4, 2e-4), (1e4, 0)]},
                  times=[10 ** (2 + 4.4 * k / 44) for k in range(45)],
                  resp_times=[10 ** (2 + 4.6 * k / 46) for k in range(47)]),
}


def tail_case(Pe, cap):
    """Made up: one stable nuclide whose matrix holds cap times the water it
    faces and fills over x0^2 R/De = 12 500 a, 250 times tw, under a
    constant release for 2e4 a. A step input like this once gave an all-zero
    release."""
    x0, eps, de = 5.0, 0.005, 1e-5
    front = [30 + 5 * k for k in range(23)]
    times = sorted(set([10 ** (1 + 4 * k / 40) for k in range(41)] + front + [2e4 + t for t in front[::2]]))
    resp = sorted(set([10 ** (1 + 4.3 * k / 43) for k in range(44)] + front))
    return dict(tw=50, Pe=Pe, aw=cap / (x0 * eps), eps=eps, x0=x0, nuc=[('X1', 'inf', 0.0, de)], link=[],
                src={'X1': [(0, 1), (2e4, 1)]}, times=times, resp_times=resp, dps=40 + int(Pe / 4.6) + 10)


for _Pe in (30, 100, 300):
    for _cap in (0.1, 1, 10):
        CASES[f'tail-{_Pe}-{_cap:g}'] = tail_case(_Pe, _cap)
RHO = 2700


def transfer_tr9001(c):
    """T(s) as a function returning the lower-triangular matrix, by TR 90-01's
    recursion. Indices 0-based; one chain (the cases have one each)."""
    tw, Pe, a, eps, x0 = (mp.mpf(c[k]) for k in ('tw', 'Pe', 'aw', 'eps', 'x0'))
    lam = [mp.log(2) / mp.mpf(n[1]) for n in c['nuc']]
    R = [eps + mp.mpf(n[2]) * RHO for n in c['nuc']]
    De = [mp.mpf(n[3]) for n in c['nuc']]
    Rf = [1 + (mp.mpf(n[4]) if len(n) > 4 else 0) * a for n in c['nuc']]
    N = len(lam)

    def T(s):
        h = [mp.sqrt(R[k] * (s + lam[k]) / De[k]) for k in range(N)]
        th = [h[k] * mp.tanh(h[k] * x0) for k in range(N)]
        F = [Rf[k] * (s + lam[k]) + a * De[k] * th[k] for k in range(N)]
        Hk = [mp.exp(Pe / 2 * (1 - mp.sqrt(1 + 4 * tw * F[k] / Pe))) for k in range(N)]
        out = [[mp.mpf(0)] * N for _ in range(N)]
        for j in range(N):
            P = {(j, j): mp.mpf(1)}            # P[(i, k)] for fixed j
            Q = {(j, j, j): mp.mpf(1)}         # Q[(i, k, l)]
            out[j][j] = Hk[j]
            for i in range(j + 1, N):
                # K_d^i h_p^l = a R_(i-1) (h_l tanh(h_l x0) - h_i tanh(h_i x0)) / (h_l^2 - h_i^2)
                Kd = {l: a * R[i - 1] * (th[l] - th[i]) / (h[l] ** 2 - h[i] ** 2) for l in range(j, i)}
                for k in range(j, i):
                    acc = Rf[i - 1] * P[(i - 1, k)] + sum(Q[(i - 1, k, l)] * Kd[l] for l in range(k, i))
                    P[(i, k)] = lam[i - 1] / (F[i] - F[k]) * acc
                P[(i, i)] = -sum(P[(i, k)] for k in range(j, i))
                for k in range(j, i):
                    for l in range(k, i):
                        Q[(i, k, l)] = Q[(i - 1, k, l)] * R[i - 1] * lam[i - 1] / De[i] / (h[i] ** 2 - h[l] ** 2)
                    Q[(i, k, i)] = P[(i, k)] - sum(Q[(i, k, l)] for l in range(k, i))
                Q[(i, i, i)] = P[(i, i)]
                out[i][j] = sum(P[(i, k)] * Hk[k] for k in range(j, i + 1))
        return out
    return T


def read_out_ts(path):
    ref, cur = {}, None
    for ln in open(path):
        w = ln.split()
        if len(w) == 1 and re.fullmatch(r'[A-Z][A-Z]?[0-9]+[A-Z]*', w[0]):
            cur = w[0]; ref[cur] = []
        elif len(w) == 3 and cur and re.match(r'[-+0-9.]', w[0]):
            ref[cur].append([float(x) for x in w])
    return ref


def read_out_response(path):
    out, cur = [], None
    for ln in open(path):
        m = re.search(r'MPRES=\s*(\d+)\s*,MSUB=\s*(\d+)\s*\)=\s*(\d+)', ln)
        if m:
            cur = {'i': int(m.group(1)) - 1, 'j': int(m.group(2)) - 1, 'pts': []}; out.append(cur); continue
        w = ln.split()
        if cur and len(w) == 2 and re.match(r'[-+0-9.]', w[0]):
            cur['pts'].append([float(x) for x in w])
    return out


def kinks(pts):
    """Jumps and slope changes of a piecewise-linear series, zero outside."""
    ts = [mp.mpf(p[0]) for p in pts]; vs = [mp.mpf(p[1]) for p in pts]
    nodes = {}
    def add(t, jump, dslope):
        j0, d0 = nodes.get(t, (0, 0)); nodes[t] = (j0 + jump, d0 + dslope)
    add(ts[0], vs[0], 0)
    for k in range(len(ts) - 1):
        if ts[k + 1] == ts[k]:
            add(ts[k], vs[k + 1] - vs[k], 0); continue
        sl = (vs[k + 1] - vs[k]) / (ts[k + 1] - ts[k])
        add(ts[k], 0, sl); add(ts[k + 1], 0, -sl)
    add(ts[-1], -vs[-1], 0)
    return sorted((t, jd[0], jd[1]) for t, jd in nodes.items() if jd[0] != 0 or jd[1] != 0)


def inv(f, t):
    return mp.invertlaplace(f, t, method='talbot')


def case_input(c):
    """The case as farf31-model.js's run() takes it (for tests of cases that
    have no FARF31 files)."""
    link = set(c['link'])
    nucs = []
    for k, n in enumerate(c['nuc']):
        nucs.append({'name': n[0], 'thalf': 'Infinity' if n[1] == 'inf' else n[1], 'kd': n[2], 'de': n[3], 'ka': n[4] if len(n) > 4 else 0,
                     'daughter': (k + 1) in link, 'source': n[0] in c['src']})
    return {'params': {k: c[k] for k in ('tw', 'Pe', 'aw', 'eps', 'x0')},
            'nuclides': nucs, 'series': {k: [list(p) for p in v] for k, v in c['src'].items()}}


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    t0 = time.time()
    path = os.path.join(HERE, 'ref', 'mpmath-ref.json')
    out = {'generator': 'gen-mpmath-ref.py', 'dps': mp.mp.dps, 'cases': {}}
    if only and os.path.exists(path):
        out = json.load(open(path))
    for name, c in CASES.items():
        if only and name != only and not (only.endswith('*') and name.startswith(only[:-1])):
            continue
        mp.mp.dps = c.get('dps', 40)
        names = [n[0] for n in c['nuc']]
        T = transfer_tr9001(c)
        cache = {}
        def Tij(i, j, s):
            key = (s,)
            if key not in cache:
                if len(cache) > 20000: cache.clear()
                cache[key] = T(s)
            return cache[key][i][j]
        sources = [names.index(k) for k in c['src']]
        N = len(names)
        linked = set(c['link'])
        def chain_below(j):
            i = j
            while i + 1 < N and (i + 1) in linked:
                i += 1
            return range(j, i + 1)
        def release(i, t):
            t = mp.mpf(t); tot = mp.mpf(0)
            for j in sources:
                if i not in chain_below(j): continue
                for tk, jump, dsl in kinks(c['src'][names[j]]):
                    if tk >= t: continue
                    u = t - tk
                    if jump: tot += jump * inv(lambda s: Tij(i, j, s) / s, u)
                    if dsl: tot += dsl * inv(lambda s: Tij(i, j, s) / s ** 2, u)
            return float(tot)
        rec = {'T0': {}, 'outputs': {}, 'responses': [], 'input': case_input(c), 'dps': mp.mp.dps}
        for j in sources:
            for i in chain_below(j):
                rec['T0'][f'{i},{j}'] = float(T(mp.mpf(0))[i][j])
        ts_path = os.path.join(REF, name, 'out.ts')
        if 'times' in c:
            for i in range(N):
                if not any(i in chain_below(j) for j in sources): continue
                rec['outputs'][names[i]] = [[t, release(i, t)] for t in c['times']]
                print(f'{name} {names[i]}: {len(c["times"])} outputs, {time.time() - t0:.0f} s', flush=True)
        elif os.path.exists(ts_path):
            ref = read_out_ts(ts_path)
            for key, rows in ref.items():
                i = [n.upper() for n in names].index(key)
                step = 1 if len(rows) <= 130 else 2
                rec['outputs'][names[i]] = [[r[0], release(i, r[0])] for q, r in enumerate(rows) if not q % step]
                print(f'{name} {names[i]}: {len(rec["outputs"][names[i]])} outputs, {time.time() - t0:.0f} s', flush=True)
        rs_path = os.path.join(REF, name, 'out.response')
        if 'resp_times' in c:
            for j in sources:
                for i in chain_below(j):
                    vals = [[t, float(inv(lambda s: Tij(i, j, s), mp.mpf(t)))] for t in c['resp_times']]
                    rec['responses'].append({'i': i, 'j': j, 'values': vals})
                    print(f'{name} response {names[i]} from {names[j]}: {len(vals)} values, {time.time() - t0:.0f} s', flush=True)
        elif os.path.exists(rs_path):
            for blk in read_out_response(rs_path):
                i, j = blk['i'], blk['j']
                if j not in sources: continue
                vals = []
                for q, (t, v) in enumerate(blk['pts']):
                    if len(blk['pts']) > 60 and q % 2: continue
                    vals.append([t, float(inv(lambda s: Tij(i, j, s), mp.mpf(t)))])
                rec['responses'].append({'i': i, 'j': j, 'values': vals})
                print(f'{name} response {names[i]} from {names[j]}: {len(vals)} values, {time.time() - t0:.0f} s', flush=True)
        out['cases'][name] = rec
        mp.mp.dps = 40
    with open(path, 'w') as f:
        json.dump(out, f, indent=1)
    print(f'done in {time.time() - t0:.0f} s')


if __name__ == '__main__':
    main()
