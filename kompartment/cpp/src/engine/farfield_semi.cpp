// The runtime of a far-field path worked out semi-analytically (see farfield_semi.hpp): a port of
// the Julia package's farfield_semi.jl, operation for operation and in its order.

#include "engine/farfield_semi.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <list>
#include <mutex>

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

constexpr double SEMI_RHO = 0.5;
constexpr double SEMI_NEGLIGIBLE = 1e-15;
constexpr double GL5_X[5] = {-0.906179845938664, -0.5384693101056831, 0.0, 0.5384693101056831, 0.906179845938664};
constexpr double GL5_W[5] = {0.23692688505618908, 0.47862867049936647, 0.5688888888888889, 0.47862867049936647, 0.23692688505618908};
constexpr int SEMI_BINOM[6][6] = {{1}, {1, 1}, {1, 2, 1}, {1, 3, 3, 1}, {1, 4, 6, 4, 1}, {1, 5, 10, 10, 5, 1}};

inline double poly(const SemiKernel& kern, int k, double x) {
    const double* a = kern.a.data() + 6 * static_cast<std::size_t>(k);
    return a[0] + x * (a[1] + x * (a[2] + x * (a[3] + x * (a[4] + x * a[5]))));
}

/// Python's dict: -0.0 and 0.0 are one key (and every NaN one too).
inline std::uint64_t tkey(double t) {
    if (t == 0.0) t = 0.0;
    if (t != t) return 0x7ff8000000000000ULL;
    std::uint64_t u;
    std::memcpy(&u, &t, 8);
    return u;
}

std::string bits_text(double x) {
    std::uint64_t u;
    if (x != x) {
        u = 0x7ff8000000000000ULL;
    } else {
        std::memcpy(&u, &x, 8);
    }
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}

}  // namespace

// --- one response, ready to convolve -----------------------------------------------------------

SemiKernel::SemiKernel(const lp::LPResponse& r) {
    t = r.t;
    n = static_cast<int>(t.size());
    np = std::max(0, n - 1);
    const std::vector<double>& h = r.h;
    const std::vector<double>& dh = r.dh;
    const std::vector<double>& d2h = r.d2h;
    a.assign(6 * static_cast<std::size_t>(np), 0.0);
    d.assign(static_cast<std::size_t>(np), 0.0);
    for (int k = 0; k < np; k++) {
        double dk = t[k + 1] - t[k];
        double ya = h[k];
        double da = dk * dh[k];
        double ea = dk * dk * d2h[k];
        double yb = h[k + 1];
        double db = dk * dh[k + 1];
        double eb = dk * dk * d2h[k + 1];
        double* A = a.data() + 6 * static_cast<std::size_t>(k);
        A[0] = ya;
        A[1] = da;
        A[2] = 0.5 * ea;
        A[3] = -10 * ya - 6 * da - 1.5 * ea + 10 * yb - 4 * db + 0.5 * eb;
        A[4] = 15 * ya + 8 * da + 1.5 * ea - 15 * yb + 7 * db - eb;
        A[5] = -6 * ya - 3 * da - 0.5 * ea + 6 * yb - 3 * db + 0.5 * eb;
        d[k] = dk;
    }
    ahead.assign(static_cast<std::size_t>(np) + 1, Inf);
    for (int k = np - 1; k >= 0; k--) ahead[k] = ff_min(ahead[k + 1], t[k + 1] - t[k]);
    m0 = r.m0 > 0 && n > 0 ? r.m0 : 0.0;
    t0 = n > 0 ? t[0] : Inf;
    t_end = n > 0 ? t[n - 1] : -Inf;
    tm0 = n > 0 ? t[0] : Inf;
    P.assign(4 * static_cast<std::size_t>(n), 0.0);
    for (int k = 0; k < np; k++) {
        std::array<double, 4> part = piece_moments(*this, k, t[k], t[k + 1]);
        for (int q = 0; q < 4; q++) P[4 * (k + 1) + q] = P[4 * k + q] + part[q];
    }
}

int piece_at(const SemiKernel& kern, double u) {
    const std::vector<double>& t = kern.t;
    if (u <= t[0]) return 0;
    if (u >= t[kern.np]) return kern.np - 1;
    // bisect_right(t, u) - 1
    int lo = 0, hi = static_cast<int>(t.size());
    while (lo < hi) {
        int mid = (lo + hi) >> 1;
        if (u < t[mid])
            hi = mid;
        else
            lo = mid + 1;
    }
    return lo - 1;
}

double kernel_at(const SemiKernel& kern, double u) {
    if (!(u >= kern.t0) || !(u <= kern.t_end) || kern.np < 1) return 0.0;
    int k = piece_at(kern, u);
    double d = kern.t[k + 1] - kern.t[k];
    return poly(kern, k, (u - kern.t[k]) / d);
}

std::array<double, 4> piece_moments(const SemiKernel& kern, int k, double ua, double ub) {
    double o1 = 0.0, o2 = 0.0, o3 = 0.0, o4 = 0.0;
    if (!(ub > ua)) return {o1, o2, o3, o4};
    double t0 = kern.t[k];
    double d = kern.t[k + 1] - t0;
    double c = 0.5 * (ua + ub);
    double hw = 0.5 * (ub - ua);
    for (int g = 0; g < 5; g++) {
        double u = c + GL5_X[g] * hw;
        double x = (u - t0) / d;
        double h = poly(kern, k, x);
        double w = GL5_W[g] * hw * h;
        o1 += w;
        o2 += w * u;
        o3 += w * u * u;
        o4 += w * u * u * u;
    }
    return {o1, o2, o3, o4};
}

std::array<double, 4> running_moments(const SemiKernel& kern, double D) {
    if (!(D > kern.t0) || kern.np < 1) return {0.0, 0.0, 0.0, 0.0};
    double top = ff_min(D, kern.t_end);
    int k = piece_at(kern, top);
    std::array<double, 4> rest = piece_moments(kern, k, kern.t[k], top);
    const double* P = kern.P.data() + 4 * static_cast<std::size_t>(k);
    return {P[0] + rest[0], P[1] + rest[1], P[2] + rest[2], P[3] + rest[3]};
}

std::vector<std::array<double, 5>> lag_basis(const std::vector<double>& s, int count, double D) {
    std::vector<std::array<double, 5>> coef(static_cast<std::size_t>(count));
    std::array<double, 5> row{};
    for (int k = 0; k < count; k++) {
        row.fill(0.0);
        row[0] = 1.0;
        int deg = 0;
        double den = 1.0;
        double sk = s[k] / D;
        for (int m = 0; m < count; m++) {
            if (m == k) continue;
            double sm = s[m] / D;
            for (int q = deg + 1; q >= 1; q--) row[q] = row[q - 1] - sm * row[q];
            row[0] = -sm * row[0];
            deg++;
            den *= sk - sm;
        }
        for (int q = 0; q <= deg; q++) row[q] /= den;
        coef[k] = row;
    }
    return coef;
}

std::array<double, 6> semi_shift(const std::array<double, 6>& mu, double c, double w, double nc, double nw) {
    double alpha = w / nw;
    double beta = (c - nc) / nw;
    std::array<double, 6> out{};
    for (int m = 0; m <= 5; m++) {
        double s = 0.0;
        for (int k = 0; k <= m; k++) s += SEMI_BINOM[m][k] * ff_pow(alpha, k) * ff_pow(beta, m - k) * mu[k];
        out[m] = s;
    }
    return out;
}

double semi_direct(const SemiKernel& kern, double t, double c, double w, const std::array<double, 4>& e) {
    double u_lo = ff_max(t - (c + w), kern.t0);
    double u_hi = ff_min(t - (c - w), kern.t_end);
    if (!(u_hi > u_lo)) return 0.0;
    int k = piece_at(kern, u_lo);
    double u = u_lo;
    double total = 0.0;
    const std::vector<double>& tl = kern.t;
    while (u < u_hi && k < kern.np) {
        double nxt = ff_min(u_hi, tl[k + 1]);
        if (nxt > u) {
            double t0 = tl[k];
            double d = tl[k + 1] - t0;
            double mid = 0.5 * (u + nxt);
            double hw = 0.5 * (nxt - u);
            for (int g = 0; g < 5; g++) {
                double uu = mid + GL5_X[g] * hw;
                double x = (uu - t0) / d;
                double h = poly(kern, k, x);
                double s = (t - uu - c) / w;
                double v = e[0] + s * (e[1] + s * (e[2] + s * e[3]));
                total += GL5_W[g] * hw * h * v;
            }
        }
        u = nxt;
        k++;
    }
    return total;
}

// --- the recorded inflow of one source -----------------------------------------------------------

namespace {

double ahead_of(const Convolver& cv, double u) {
    double m = Inf;
    for (const auto& kp : cv.tk) {
        const SemiKernel& kern = *kp;
        if (u >= kern.t_end) continue;
        double d = u <= kern.t0 ? kern.ahead[0] : kern.ahead[piece_at(kern, u)];
        if (d < m) m = d;
    }
    return m;
}

double reach_of(const Convolver& cv) {
    double m = -Inf;
    for (const auto& kp : cv.tk)
        if (kp->t_end > m) m = kp->t_end;
    return m;
}

void piece(Convolver& cv, double t, double v) {
    int nr = static_cast<int>(cv.rt.size());
    double ta = cv.rt[nr - 1];
    double c = 0.5 * (ta + t);
    double w = 0.5 * (t - ta);
    int count = std::min(nr + 1, 4);
    double ns[4] = {0, 0, 0, 0}, nv[4] = {0, 0, 0, 0};
    for (int k = 0; k <= count - 2; k++) {
        ns[k] = (cv.rt[nr - (count - 1) + k] - c) / w;
        nv[k] = cv.rv[nr - (count - 1) + k];
    }
    ns[count - 1] = 1.0;
    nv[count - 1] = v;
    double e[4] = {0, 0, 0, 0};
    double basis[5];
    for (int k = 0; k < count; k++) {
        for (double& b : basis) b = 0.0;
        basis[0] = 1.0;
        int deg = 0;
        double den = 1.0;
        for (int m = 0; m < count; m++) {
            if (m == k) continue;
            for (int q = deg + 1; q >= 1; q--) basis[q] = basis[q - 1] - ns[m] * basis[q];
            basis[0] = -ns[m] * basis[0];
            deg++;
            den *= ns[k] - ns[m];
        }
        for (int q = 0; q <= deg; q++) e[q] += nv[k] * basis[q] / den;
    }
    std::array<double, 6> mu{};
    for (int m = 0; m <= 5; m++) {
        double s = 0.0;
        for (int q = 0; q <= 3; q++)
            if ((q + m) % 2 == 0) s += e[q] * 2 / (q + m + 1);
        mu[m] = w * s;
    }
    cv.bc.push_back(c);
    cv.bw.push_back(w);
    cv.bm.push_back(mu);
    cv.bp.push_back(std::array<double, 4>{e[0], e[1], e[2], e[3]});
}

void compact(Convolver& cv, double t_now) {
    double reach = reach_of(cv);
    std::vector<double> bc, bw;
    std::vector<std::array<double, 6>> bm;
    std::vector<std::optional<std::array<double, 4>>> bp;
    for (std::size_t k = 0; k < cv.bc.size(); k++) {
        double c = cv.bc[k];
        double w = cv.bw[k];
        if (t_now - (c + w) > reach) continue;
        const std::array<double, 6>& mu = cv.bm[k];
        const std::optional<std::array<double, 4>>& p = cv.bp[k];
        if (!bc.empty()) {
            std::size_t last = bc.size() - 1;
            double lo = bc[last] - bw[last];
            double hi = c + w;
            double width = hi - lo;
            if (width <= SEMI_RHO * ahead_of(cv, t_now - hi)) {
                double nc = 0.5 * (lo + hi);
                double nw = 0.5 * width;
                std::array<double, 6> merged = semi_shift(bm[last], bc[last], bw[last], nc, nw);
                std::array<double, 6> mine = semi_shift(mu, c, w, nc, nw);
                for (int m = 0; m < 6; m++) merged[m] += mine[m];
                bc[last] = nc;
                bw[last] = nw;
                bm[last] = merged;
                bp[last] = std::nullopt;
                continue;
            }
        }
        bc.push_back(c);
        bw.push_back(w);
        bm.push_back(mu);
        bp.push_back(p);
    }
    cv.bc = std::move(bc);
    cv.bw = std::move(bw);
    cv.bm = std::move(bm);
    cv.bp = std::move(bp);
    cv.compact_at = 2 * cv.bc.size() + 64;
}

/// `searchsorted(t, u, side='right') - 1`, clipped to [0, npc - 1] (numpy's NaN-last order).
inline int np_piece(const std::vector<double>& t, double u, int npc) {
    int lo = 0, hi = static_cast<int>(t.size());
    if (std::isnan(u)) {
        lo = hi;
    } else {
        while (lo < hi) {
            int mid = (lo + hi) >> 1;
            if (t[mid] <= u)
                lo = mid + 1;
            else
                hi = mid;
        }
    }
    int k = lo - 1;
    return k < 0 ? 0 : (k > npc - 1 ? npc - 1 : k);
}

/// The count of `t`'s elements that are <= u, walked down from `cnt`, the count for a later lag --
/// or searched for, the first time (`cnt < 0`).
inline int walk_count(const std::vector<double>& t, double u, int cnt) {
    if (cnt < 0) {
        int lo = 0, hi = static_cast<int>(t.size());
        while (lo < hi) {
            int mid = (lo + hi) >> 1;
            if (t[mid] <= u)
                lo = mid + 1;
            else
                hi = mid;
        }
        return lo;
    }
    while (cnt > 0 && t[cnt - 1] > u) cnt--;
    return cnt;
}

inline int clip_piece(int cnt, int npc) {
    int k = cnt - 1;
    return k < 0 ? 0 : (k > npc - 1 ? npc - 1 : k);
}

/// One block by its moments against piece k of the response (`fromMoments`).
inline double from_moment(const SemiKernel& kern, int k, double uc, double w, const std::array<double, 6>& mu) {
    double t0 = kern.t[k];
    double d = kern.d[k];
    double x = (uc - t0) / d;
    const double* a = kern.a.data() + 6 * static_cast<std::size_t>(k);
    double b0 = a[0], b1 = a[1], b2 = a[2], b3 = a[3], b4 = a[4], b5 = a[5];
    double c5 = b5;
    double c4 = b4 + x * c5;
    double c3 = b3 + x * c4;
    double c2 = b2 + x * c3;
    double c1 = b1 + x * c2;
    double t0c = b0 + x * c1;
    c4 = c4 + x * c5;
    c3 = c3 + x * c4;
    c2 = c2 + x * c3;
    double t1c = c1 + x * c2;
    c4 = c4 + x * c5;
    c3 = c3 + x * c4;
    double t2c = c2 + x * c3;
    c4 = c4 + x * c5;
    double t3c = c3 + x * c4;
    double t4c = c4 + x * c5;
    double t5c = c5;
    double r = -w / d;
    return t0c * mu[0] + r * (t1c * mu[1] + r * (t2c * mu[2] + r * (t3c * mu[3] + r * (t4c * mu[4] + r * t5c * mu[5]))));
}

}  // namespace

void impulse(Convolver& cv, double t, double amount) {
    if (amount == 0 || !std::isfinite(amount)) return;
    cv.imp_t.push_back(t);
    cv.imp_a.push_back(amount);
}

void push_record(Convolver& cv, double t, double v) {
    cv.count++;
    if (t == cv.last_t) {
        if (v == cv.rv.back()) return;
        cv.rt = {t};
        cv.rv = {v};
        return;
    }
    if (t < cv.last_t) throw std::runtime_error("a far-field path was told about an earlier instant after a later one");
    if (!cv.rt.empty()) piece(cv, t, v);
    cv.rt.push_back(t);
    cv.rv.push_back(v);
    if (cv.rt.size() > 4) {
        cv.rt.erase(cv.rt.begin());
        cv.rv.erase(cv.rv.begin());
    }
    cv.last_t = t;
    if (cv.bc.size() > cv.compact_at) compact(cv, t);
}

void history(const Convolver& cv, double t, double* out, SemiScratch& scr) {
    if (cv.ti.empty()) return;
    std::size_t nb = cv.bc.size();
    for (std::size_t idx = 0; idx < cv.ti.size(); idx++) {
        int ti = cv.ti[idx];
        const SemiKernel& kern = *cv.tk[idx];
        int npc = kern.np;
        if (npc < 1) continue;
        double total = 0.0;
        if (nb > 0) {
            // The blocks' moments against the response's pieces, summed as numpy sums them;
            // the wide single pieces directly, in order.
            std::vector<double>& v = scr.v;
            if (v.size() < nb) v.resize(nb);
            std::size_t nv = 0;
            std::vector<int>& wide = scr.wide;
            wide.clear();
            bool anykeep = false;
            const std::vector<double>& kt = kern.t;
            int c_young = -1;
            int c_uc = -1;
            for (std::size_t b = 0; b < nb; b++) {
                double uc = t - cv.bc[b];
                double Wd = cv.bw[b];
                if (!((uc + Wd > kern.t0) && (uc - Wd < kern.t_end))) continue;
                anykeep = true;
                if (cv.bp[b]) {
                    double young = uc - Wd;
                    int ka;
                    if (std::isnan(young)) {
                        ka = np_piece(kt, young, npc);
                    } else {
                        c_young = walk_count(kt, young, c_young);
                        ka = clip_piece(c_young, npc);
                    }
                    double sp = young <= kern.t0 ? kern.ahead[0] : kern.ahead[ka];
                    if (2 * Wd > SEMI_RHO * sp) {
                        wide.push_back(static_cast<int>(b));
                        continue;
                    }
                }
                int k;
                if (std::isnan(uc)) {
                    k = np_piece(kt, uc, npc);
                } else {
                    c_uc = walk_count(kt, uc, c_uc);
                    k = clip_piece(c_uc, npc);
                }
                v[nv++] = from_moment(kern, k, uc, Wd, cv.bm[b]);
            }
            if (anykeep) {
                if (nv > 0) total += np_sum(v.data(), nv);
                for (int b : wide) total += semi_direct(kern, t, cv.bc[b], cv.bw[b], *cv.bp[b]);
            }
        }
        for (std::size_t r = 0; r < cv.imp_t.size(); r++) total += cv.imp_a[r] * kernel_at(kern, t - cv.imp_t[r]);
        out[ti] += total;
    }
}

void step_weights(std::vector<SemiPart>& out, const Convolver& cv, double t, int slot) {
    int nr = static_cast<int>(cv.rt.size());
    double D = t - cv.last_t;
    if (cv.ti.empty() || nr == 0 || !(D > 0)) return;
    int count = std::min(nr + 1, 4);
    std::vector<double> s(static_cast<std::size_t>(count), 0.0);
    for (int k = 0; k <= count - 2; k++) s[k] = t - cv.rt[nr - (count - 1) + k];
    s[count - 1] = 0.0;
    std::optional<std::vector<std::array<double, 5>>> coef;
    for (std::size_t idx = 0; idx < cv.ti.size(); idx++) {
        const SemiKernel& kern = *cv.tk[idx];
        if (!(D > kern.t0)) continue;
        if (!coef) coef = lag_basis(s, count, D);
        std::array<double, 4> mom = running_moments(kern, D);
        double m1 = mom[0];
        double Dq = D;
        double m2 = mom[1] / Dq;
        Dq *= D;
        double m3 = mom[2] / Dq;
        Dq *= D;
        double m4 = mom[3] / Dq;
        double mm[4] = {m1, m2, m3, m4};
        SemiPart part;
        part.i = cv.ti[idx];
        for (int k = 0; k < count; k++) {
            double v = 0.0;
            for (int q = 0; q < count; q++) v += (*coef)[k][q] * mm[q];
            part.w[k] = v;
        }
        part.count = count;
        part.nr = nr;
        part.slot = slot;
        out.push_back(part);
    }
}

void point_parts(std::vector<SemiPart>& out, const Convolver& cv, double t, int slot) {
    int nr = static_cast<int>(cv.rt.size());
    if (nr == 0) return;
    for (std::size_t idx = 0; idx < cv.ti.size(); idx++) {
        const SemiKernel& kern = *cv.tk[idx];
        if (!(kern.m0 > 0)) continue;
        double tau = t - kern.tm0;
        if (!(tau > cv.last_t)) continue;
        int count = std::min(nr + 1, 4);
        double nodes[4] = {0, 0, 0, 0};
        for (int k = 0; k <= count - 2; k++) nodes[k] = cv.rt[nr - (count - 1) + k];
        nodes[count - 1] = t;
        SemiPart part;
        part.i = cv.ti[idx];
        for (int k = 0; k < count; k++) {
            double lk = 1.0;
            for (int m = 0; m < count; m++)
                if (m != k) lk *= (tau - nodes[m]) / (nodes[k] - nodes[m]);
            part.w[k] = kern.m0 * lk;
        }
        part.count = count;
        part.nr = nr;
        part.slot = slot;
        out.push_back(part);
    }
}

double step_sum(const Convolver& cv, const SemiPart& part, double v) {
    int count = part.count, nr = part.nr;
    double r = part.w[count - 1] * v;
    for (int k = 0; k <= count - 2; k++) r += part.w[k] * cv.rv[nr - (count - 1) + k];
    return r;
}

// --- the path ------------------------------------------------------------------------------------

namespace {

/// Unit responses by settings, shared by every path and every run in this process (32 kept), the
/// most recently used last.
struct SemiResponses {
    std::mutex lock;
    std::list<std::pair<std::string, std::shared_ptr<const SemiCombo>>> order;
    std::unordered_map<std::string, std::list<std::pair<std::string, std::shared_ptr<const SemiCombo>>>::iterator> index;
};
SemiResponses& semi_responses_kept() {
    static SemiResponses kept;
    return kept;
}
constexpr std::size_t SEMI_RESPONSES_KEEP = 32;

}  // namespace

void clear_semi_responses() {
    SemiResponses& R = semi_responses_kept();
    std::lock_guard<std::mutex> g(R.lock);
    R.order.clear();
    R.index.clear();
}

std::string semi_response_key(const lp::LPSettings& s, const lp::LPDecay* D, double span, int nnuc) {
    std::string key = bits_text(span) + "|" + std::to_string(nnuc) + "|" + s.surface;
    for (const auto& [k, v] : s.single) key += "|" + k + "=" + bits_text(v);
    for (const auto& [k, vs] : s.each) {
        key += "|" + k + "=";
        for (double v : vs) key += bits_text(v) + ",";
    }
    if (D) {
        key += "|D";
        for (double v : D->lam) key += bits_text(v) + ",";
        key += "/";
        for (int v : D->ioff) key += std::to_string(v) + ",";
        key += "/";
        for (int v : D->icnt) key += std::to_string(v) + ",";
        key += "/";
        for (int v : D->ipar) key += std::to_string(v) + ",";
        key += "/";
        for (double v : D->icoef) key += bits_text(v) + ",";
    }
    return key;
}

std::string js_precision4(double x) {
    if (std::isnan(x)) return "NaN";
    if (std::isinf(x)) return x > 0 ? "Infinity" : "-Infinity";
    if (x == 0) return "0.000";
    char buf[64];
    std::snprintf(buf, sizeof buf, "%.3e", x);
    std::string s = buf;
    std::size_t at = s.find('e');
    std::string mant = s.substr(0, at);
    int e = std::stoi(s.substr(at + 1));
    if (e < -6 || e >= 4) return mant + "e" + (e >= 0 ? "+" : "-") + std::to_string(std::abs(e));
    std::snprintf(buf, sizeof buf, "%.*f", std::max(0, 3 - e), x);
    return buf;
}

LaplaceFarfPath::LaplaceFarfPath(int base_, int nnuc_, int other_width_, std::vector<int> dim_off_, std::vector<int> single_off_,
                                 const std::unordered_map<std::string, int>& setting_base_, std::vector<std::string> keys_,
                                 const std::vector<std::string>& single, const std::string& surface_, int release_base_, double span_,
                                 std::optional<std::vector<std::string>> names_, std::string block_name_)
    : base(base_), nnuc(nnuc_), other_width(other_width_), dim_off(std::move(dim_off_)), single_off(std::move(single_off_)),
      setting_base(setting_base_), keys(std::move(keys_)), is_single(single.begin(), single.end()), surface(surface_.empty() ? "f" : surface_),
      release_base(release_base_), span(span_), names(std::move(names_)), block_name(std::move(block_name_)) {
    laplace = true;
    nslots = other_width * nnuc;
    for (int s = 0; s < nslots; s++) release_slots_.push_back(release_base + dim_off[s]);
    for (int s = 0; s < nslots; s++) held_idx_.push_back(base + s);
    for (int o = 0; o < other_width; o++) cell_starts_.push_back(base + o * nnuc);
    terms_into.assign(static_cast<std::size_t>(nslots), {});
    IN.assign(static_cast<std::size_t>(nslots), 0.0);
    held.assign(static_cast<std::size_t>(nslots), 0.0);
    last_held.assign(static_cast<std::size_t>(nslots), 0.0);
    rec_v.assign(static_cast<std::size_t>(nslots), {});
    imp_t.assign(static_cast<std::size_t>(nslots), {});
    imp_v.assign(static_cast<std::size_t>(nslots), {});
    combos.assign(static_cast<std::size_t>(other_width), nullptr);
    sweep_at = -Inf;
    sweep_next = 0;
    sweep_imp.assign(static_cast<std::size_t>(nslots), 0);
    last_t = -Inf;
    hist_t = NaN;
    hist_vals.assign(static_cast<std::size_t>(nslots), 0.0);
    weight_t = NaN;
    cur.assign(static_cast<std::size_t>(nslots) * nnuc, 0.0);
    res.assign(static_cast<std::size_t>(nslots), 0.0);
}

void LaplaceFarfPath::set_decay(const DecayTables* dec) {
    if (dec)
        D = lp::LPDecay{dec->lam, dec->ioff, dec->icnt, dec->ipar, dec->icoef};
    else
        D.reset();
    restart();
}

void LaplaceFarfPath::set_inflow(std::vector<int> tgt, std::vector<int> rate, std::vector<int> donor) {
    in_tgt = std::move(tgt);
    in_rate = std::move(rate);
    in_donor = std::move(donor);
    terms_into.assign(static_cast<std::size_t>(nslots), {});
    for (std::size_t q = 0; q < in_tgt.size() && q < in_rate.size() && q < in_donor.size(); q++)
        terms_into[static_cast<std::size_t>(in_tgt[q])].push_back({in_rate[q], in_donor[q]});
}

void LaplaceFarfPath::restart() {
    ready = false;
    live.reset();
    sweep.reset();
    sweep_at = -Inf;
    releases.clear();
    last_t = -Inf;
    hist_t = NaN;
    weight_t = NaN;
    weighed = false;
    rec_t.clear();
    for (int s = 0; s < nslots; s++) {
        rec_v[s].clear();
        imp_t[s].clear();
        imp_v[s].clear();
    }
}

int LaplaceFarfPath::setting_at(const std::string& key, int o, int off) const {
    int one = single_off.empty() ? 0 : single_off[o];
    return setting_base.at(key) + (is_single.count(key) ? one : off);
}

lp::LPSettings LaplaceFarfPath::settings_of(const double* X, int o) const {
    int n = nnuc;
    lp::LPSettings s;
    s.surface = surface;
    for (const auto& key : keys) {
        if (is_single.count(key)) {
            s.single[key] = X[setting_at(key, o, dim_off[o * n])];
        } else {
            std::vector<double> v;
            for (int m = 0; m < n; m++) v.push_back(X[setting_at(key, o, dim_off[o * n + m])]);
            s.each[key] = std::move(v);
        }
    }
    return s;
}

namespace {

std::shared_ptr<const SemiCombo> semi_responses(const LaplaceFarfPath& F, const lp::LPSettings& settings) {
    std::unique_ptr<lp::LaplacePath> path;
    try {
        path = lp::prepare_path(settings, F.D ? &*F.D : nullptr, F.nnuc, F.names ? &*F.names : nullptr);
    } catch (const lp::LaplacePathError& e) {
        throw FarfError(e.what());
    }
    int n = F.nnuc;
    std::vector<double> T0 = lp::transfer_at_zero(*path);
    auto combo = std::make_shared<SemiCombo>();
    combo->kernels.assign(static_cast<std::size_t>(n) * n, nullptr);
    for (int j = 0; j < n; j++) {
        double most = 0.0;
        for (int i = 0; i < n; i++)
            if (T0[i * n + j] > most) most = T0[i * n + j];
        for (int i = 0; i < n; i++) {
            if (!path->reaches(j, i)) continue;
            double T = T0[i * n + j];
            if (!(T > SEMI_NEGLIGIBLE * most) || !(T > 1e-300)) continue;
            lp::LPResponse r = lp::unit_response(*path, i, j, F.span);
            if (r.checked && !r.balanced)
                combo->misses.push_back({i, j, r.integral, r.expected, r.T0, r.rel, r.t.empty() ? NaN : r.t.back()});
            if (r.t.size() < 2) continue;
            combo->kernels[i * n + j] = std::make_shared<const SemiKernel>(r);
            combo->pairs++;
        }
    }
    return combo;
}

}  // namespace

void LaplaceFarfPath::prepare(const double* X) {
    SemiResponses& R = semi_responses_kept();
    for (int o = 0; o < other_width; o++) {
        lp::LPSettings settings = settings_of(X, o);
        std::string key = semi_response_key(settings, D ? &*D : nullptr, span, nnuc);
        std::shared_ptr<const SemiCombo> combo;
        {
            std::lock_guard<std::mutex> g(R.lock);
            auto it = R.index.find(key);
            if (it != R.index.end()) {
                combo = it->second->second;
                R.order.splice(R.order.end(), R.order, it->second);   // to the end: the most recently used
            }
        }
        if (!combo) {
            combo = semi_responses(*this, settings);
            std::lock_guard<std::mutex> g(R.lock);
            auto it = R.index.find(key);
            if (it != R.index.end()) {
                R.order.erase(it->second);
                R.index.erase(it);
            }
            R.order.emplace_back(key, combo);
            R.index[key] = std::prev(R.order.end());
            while (R.order.size() > SEMI_RESPONSES_KEEP) {
                R.index.erase(R.order.front().first);
                R.order.pop_front();
            }
        }
        combos[o] = combo;
    }
    ready = true;
    live = convolvers();
}

std::vector<Json> LaplaceFarfPath::balance_warnings() const {
    std::vector<Json> out;
    auto name = [&](int k) { return names ? (*names)[k] : "#" + std::to_string(k + 1); };
    for (int o = 1; o <= static_cast<int>(combos.size()); o++) {
        const auto& combo = combos[o - 1];
        if (!combo) continue;
        for (const SemiCombo::Miss& m : combo->misses) {
            std::string where = other_width > 1 ? " (index combination " + std::to_string(o) + " of " + std::to_string(other_width) + ")" : "";
            out.push_back(Json::object(
                {{"block", Json(block_name)},
                 {"message", Json("the unit response of " + name(m.i) + " to " + name(m.j) + where + " integrates to " + js_precision4(m.integral) +
                                  ", but " + js_precision4(m.expected) + " of a pulse leaves the path by " + js_precision4(m.until) +
                                  " (T(0) = " + js_precision4(m.T0) +
                                  "): the inversion failed there, and the release worked out from it is not reliable")}}));
        }
    }
    return out;
}

std::vector<Convolver> LaplaceFarfPath::convolvers() const {
    int n = nnuc;
    std::vector<Convolver> out;
    for (int o = 0; o < other_width; o++) {
        const auto& kernels = combos[o]->kernels;
        for (int j = 0; j < n; j++) {
            Convolver cv;
            for (int i = 0; i < n; i++) {
                const auto& k = kernels[i * n + j];
                if (!k) continue;
                cv.ti.push_back(o * n + i);
                cv.tk.push_back(k);
            }
            out.push_back(std::move(cv));
        }
    }
    return out;
}

const std::vector<double>& LaplaceFarfPath::inflow(const double* y, const double* X) {
    std::fill(IN.begin(), IN.end(), 0.0);
    for (std::size_t q = 0; q < in_tgt.size(); q++) {
        int d = in_donor[q];
        IN[in_tgt[q]] += (d >= 0 ? y[d] : 1.0) * X[in_rate[q]];
    }
    return IN;
}

void LaplaceFarfPath::weights(double t) {
    if (t == weight_t && weighed) return;
    int n = nnuc;
    std::fill(cur.begin(), cur.end(), 0.0);
    parts.clear();
    if (live && t > last_t) {
        const std::vector<Convolver>& lv = *live;
        for (int slot = 0; slot < nslots; slot++) {
            std::size_t start = parts.size();
            step_weights(parts, lv[slot], t, slot);
            point_parts(parts, lv[slot], t, slot);
            for (std::size_t q = start; q < parts.size(); q++) {
                const SemiPart& part = parts[q];
                cur[part.i * n + (slot % n)] += part.w[part.count - 1];
            }
        }
    }
    weighed = true;
    weight_t = t;
}

const std::vector<double>& LaplaceFarfPath::current_weights(double t) {
    weights(t);
    return cur;
}

void LaplaceFarfPath::release(const double* y, double* X, double t) {
    if (!ready) prepare(X);
    auto kept = releases.find(tkey(t));
    if (kept != releases.end()) {
        for (int s = 0; s < nslots; s++) X[release_slots_[s]] = kept->second[s];
        return;
    }
    double last_recorded = rec_t.empty() ? -Inf : rec_t.back();
    if (t < last_recorded || (!rec_t.empty() && last_t == -Inf)) {
        behind(y, X, t);
        return;
    }
    if (!(t == hist_t)) {
        std::fill(hist_vals.begin(), hist_vals.end(), 0.0);
        if (live) {
            const std::vector<Convolver>& lv = *live;
            for (int slot = 0; slot < nslots; slot++) {
                history(lv[slot], t, hist_vals.data(), scratch);
                points_behind(lv[slot], slot, t, hist_vals.data());
            }
        }
        hist_t = t;
    }
    inflow(y, X);
    weights(t);
    std::copy(hist_vals.begin(), hist_vals.end(), res.begin());
    if (!parts.empty()) {
        const std::vector<Convolver>& lv = *live;
        for (const SemiPart& part : parts) res[part.i] += step_sum(lv[part.slot], part, IN[part.slot]);
    }
    for (int s = 0; s < nslots; s++) X[release_slots_[s]] = res[s];
}

void LaplaceFarfPath::behind(const double* y, double* X, double t) {
    if (!sweep || t < sweep_at) {
        sweep = convolvers();
        sweep_at = -Inf;
        sweep_next = 0;
        std::fill(sweep_imp.begin(), sweep_imp.end(), 0);
    }
    std::vector<Convolver>& sw = *sweep;
    const std::vector<double>& times = rec_t;
    while (sweep_next < static_cast<int>(times.size()) && times[sweep_next] <= t) {
        int q = sweep_next;
        sweep_next++;
        for (int slot = 0; slot < nslots; slot++) push_record(sw[slot], times[q], rec_v[slot][q]);
    }
    for (int slot = 0; slot < nslots; slot++) {
        const std::vector<double>& it = imp_t[slot];
        Convolver& cv = sw[slot];
        while (sweep_imp[slot] < static_cast<int>(it.size()) && it[sweep_imp[slot]] <= t) {
            int q = sweep_imp[slot];
            sweep_imp[slot]++;
            impulse(cv, it[q], imp_v[slot][q]);
        }
    }
    sweep_at = t;
    std::vector<double> out(static_cast<std::size_t>(nslots), 0.0);
    for (int slot = 0; slot < nslots; slot++) {
        history(sw[slot], t, out.data(), scratch);
        points_behind(sw[slot], slot, t, out.data());
    }
    inflow(y, X);
    std::vector<SemiPart> ps;
    for (int slot = 0; slot < nslots; slot++) {
        const Convolver& cv = sw[slot];
        ps.clear();
        step_weights(ps, cv, t, slot);
        point_parts(ps, cv, t, slot);
        for (const SemiPart& part : ps) out[part.i] += step_sum(cv, part, IN[slot]);
    }
    for (int s = 0; s < nslots; s++) X[release_slots_[s]] = out[s];
}

void LaplaceFarfPath::points_behind(const Convolver& cv, int slot, double t, double* out) const {
    for (std::size_t idx = 0; idx < cv.ti.size(); idx++) {
        const SemiKernel& kern = *cv.tk[idx];
        if (!(kern.m0 > 0)) continue;
        double tau = t - kern.tm0;
        if (tau > cv.last_t) continue;
        out[cv.ti[idx]] += kern.m0 * recorded_inflow(slot, tau);
    }
}

double LaplaceFarfPath::recorded_inflow(int slot, double tau) const {
    const std::vector<double>& T = rec_t;
    const std::vector<double>& V = rec_v[slot];
    int n = static_cast<int>(T.size());
    if (n == 0 || !(tau >= T[0])) return 0.0;
    if (tau >= T[n - 1]) return V[n - 1];
    int lo = 0, hi = n - 1;
    while (hi - lo > 1) {
        int c = (lo + hi) >> 1;
        if (T[c] <= tau)
            lo = c;
        else
            hi = c;
    }
    int b = lo + 1;
    int first = b;
    while (first > 0 && b - first < 3 && T[first - 1] < T[first]) first--;
    double v = 0.0;
    for (int k = first; k <= b; k++) {
        double lk = 1.0;
        for (int m = first; m <= b; m++)
            if (m != k) lk *= (tau - T[m]) / (T[k] - T[m]);
        v += lk * V[k];
    }
    return v;
}

void LaplaceFarfPath::prime(double t0, const double* y0, const double* X) {
    if (!ready) prepare(X);
    rec_t.clear();
    for (int s = 0; s < nslots; s++) {
        rec_v[s].clear();
        imp_t[s].clear();
        imp_v[s].clear();
    }
    live = convolvers();
    sweep.reset();
    releases.clear();
    last_t = -Inf;
    hist_t = NaN;
    weight_t = NaN;
    weighed = false;
    store(t0, y0, X);
}

void LaplaceFarfPath::store(double t, const double* y, const double* X) {
    if (!ready) prepare(X);
    if (!live) live = convolvers();
    if (t < last_t) truncate(t);
    std::vector<Convolver>& lv = *live;
    inflow(y, X);
    for (int s = 0; s < nslots; s++) held[s] = y[held_idx_[s]];
    bool same = t == last_t;
    bool record = !same;
    if (same) {
        for (int slot = 0; slot < nslots; slot++) {
            double amount = held[slot] - last_held[slot];
            if (amount != 0) {
                impulse(lv[slot], t, amount);
                imp_t[slot].push_back(t);
                imp_v[slot].push_back(amount);
            }
            if (IN[slot] != rec_v[slot].back()) record = true;
        }
    }
    if (record) {
        rec_t.push_back(t);
        for (int slot = 0; slot < nslots; slot++) {
            double v = IN[slot];
            rec_v[slot].push_back(v);
            push_record(lv[slot], t, v);
        }
    }
    std::uint64_t key = tkey(t);
    if (!releases.count(key)) {
        std::vector<double> r(static_cast<std::size_t>(nslots));
        for (int s = 0; s < nslots; s++) r[s] = X[release_slots_[s]];
        releases.emplace(key, std::move(r));
    }
    last_held = held;
    last_t = t;
    hist_t = NaN;
    weight_t = NaN;
    weighed = false;
}

void LaplaceFarfPath::truncate(double t) {
    std::size_t k = rec_t.size();
    while (k > 0 && rec_t[k - 1] > t) k--;
    rec_t.resize(k);
    for (int slot = 0; slot < nslots; slot++) {
        rec_v[slot].resize(k);
        std::vector<double>& it = imp_t[slot];
        std::size_t ki = it.size();
        while (ki > 0 && it[ki - 1] > t) ki--;
        it.resize(ki);
        imp_v[slot].resize(ki);
    }
    double later = t;
    for (auto it = releases.begin(); it != releases.end();) {
        double x;
        std::memcpy(&x, &it->first, 8);
        if (x > later)
            it = releases.erase(it);
        else
            ++it;
    }
    live = convolvers();
    std::vector<Convolver>& lv = *live;
    for (std::size_t q = 0; q < rec_t.size(); q++)
        for (int slot = 0; slot < nslots; slot++) push_record(lv[slot], rec_t[q], rec_v[slot][q]);
    for (int slot = 0; slot < nslots; slot++)
        for (std::size_t q = 0; q < imp_t[slot].size(); q++) impulse(lv[slot], imp_t[slot][q], imp_v[slot][q]);
    last_t = rec_t.empty() ? -Inf : rec_t.back();
}

LaplaceRunState LaplaceFarfPath::run_state() const { return {rec_t, rec_v, imp_t, imp_v, releases}; }

void LaplaceFarfPath::restore_run_state(const LaplaceRunState& state) {
    rec_t = state.rec_t;
    rec_v = state.rec_v;
    imp_t = state.imp_t;
    imp_v = state.imp_v;
    releases = state.releases;
    sweep.reset();
    sweep_at = -Inf;
    last_t = -Inf;
    live.reset();
    hist_t = NaN;
    weight_t = NaN;
    weighed = false;
}

std::vector<std::vector<int>> LaplaceFarfPath::release_dependencies(const std::function<const std::vector<int>&(int)>& of_x) const {
    int n = nnuc;
    std::vector<std::vector<int>> per_o;
    for (int o = 0; o < other_width; o++) {
        std::vector<int> ps;
        for (int j = 0; j < n; j++)
            for (const auto& [x, d] : terms_into[o * n + j]) {
                if (d >= 0) ps.push_back(d);
                const std::vector<int>& more = of_x(x);
                ps.insert(ps.end(), more.begin(), more.end());
            }
        std::sort(ps.begin(), ps.end());
        ps.erase(std::unique(ps.begin(), ps.end()), ps.end());
        per_o.push_back(std::move(ps));
    }
    std::vector<std::vector<int>> out;
    for (int slot = 0; slot < nslots; slot++) out.push_back(per_o[slot / n]);
    return out;
}

std::vector<int> LaplaceFarfPath::setting_slots() const {
    std::vector<int> out;
    for (const auto& key : keys)
        for (int o = 0; o < other_width; o++)
            for (int m = 0; m < nnuc; m++) out.push_back(setting_at(key, o, dim_off[o * nnuc + m]));
    return out;
}

std::vector<int> LaplaceFarfPath::setting_slots_of(int slot) const {
    std::vector<int> out;
    int o = slot / nnuc;
    for (const auto& key : keys) out.push_back(setting_at(key, o, dim_off[slot]));
    return out;
}

std::shared_ptr<FarfieldPath> LaplaceFarfPath::clone() const {
    auto C = std::make_shared<LaplaceFarfPath>(*this);
    C->IN.assign(static_cast<std::size_t>(nslots), 0.0);
    C->held.assign(static_cast<std::size_t>(nslots), 0.0);
    C->live.reset();
    C->sweep.reset();
    C->sweep_at = -Inf;
    C->sweep_next = 0;
    C->sweep_imp.assign(static_cast<std::size_t>(nslots), 0);
    C->hist_t = NaN;
    C->hist_vals.assign(static_cast<std::size_t>(nslots), 0.0);
    C->weight_t = NaN;
    C->cur.assign(cur.size(), 0.0);
    C->parts.clear();
    C->weighed = false;
    C->scratch = SemiScratch();
    C->res.assign(static_cast<std::size_t>(nslots), 0.0);
    if (ready) {
        // the live convolvers, rebuilt from the records as `truncate` rebuilds them
        C->live = C->convolvers();
        std::vector<Convolver>& lv = *C->live;
        for (std::size_t q = 0; q < C->rec_t.size(); q++)
            for (int slot = 0; slot < nslots; slot++) push_record(lv[slot], C->rec_t[q], C->rec_v[slot][q]);
        for (int slot = 0; slot < nslots; slot++)
            for (std::size_t q = 0; q < C->imp_t[slot].size(); q++) impulse(lv[slot], C->imp_t[slot][q], C->imp_v[slot][q]);
    }
    return C;
}

}  // namespace kompartment
