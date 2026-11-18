#include "solvers/sparselu.hpp"

#include "util/fastmath.hpp"
#include "util/parity.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace kompartment {

namespace slu {

const char* const ORDERINGS[6] = {"natural", "reverse Cuthill-McKee", "threshold Markowitz",
                                  "natural columns, threshold rows",
                                  "reverse Cuthill-McKee columns, threshold rows",
                                  "block triangular, threshold Markowitz"};

namespace {

using sv::INF;

/// `a` grown in place to hold at least `need`, zeros after what it held (`room` in refactor.js).
template <class T>
inline void room(std::vector<T>& a, I64 need) {
    if (need <= static_cast<I64>(a.size())) return;
    std::size_t cap = std::max<std::size_t>(a.size(), 64);
    while (static_cast<I64>(cap) < need) cap *= 2;
    a.resize(cap);
}

inline std::size_t sz(I64 n) { return static_cast<std::size_t>(n); }

}  // namespace

// --- Mass - a*J in CSC (`makeMiterBuilder`) -----------------------------------------------------------

MiterStructure miter_structure(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx) {
    const I32 nzj = colptr[n];
    MiterStructure m;
    m.mp.assign(sz(n) + 1, 0);
    m.mi.assign(sz(nzj) + sz(n), 0);
    I32 k = 0;
    std::vector<I32> rows;
    for (int j = 0; j < n; j++) {
        const I32 cnt = colptr[j + 1] - colptr[j];
        rows.resize(sz(cnt) + 1);
        for (I32 p = 0; p < cnt; p++) rows[p] = rowidx[colptr[j] + p];
        rows[cnt] = j;
        std::sort(rows.begin(), rows.end());
        m.mp[j] = k;
        I32 last = -1;
        for (I32 r : rows) {
            if (r != last) {
                m.mi[k] = r;
                k += 1;
                last = r;
            }
        }
    }
    m.mp[n] = k;
    m.mi.resize(sz(k));
    std::vector<I32> pos(sz(n), -1);
    m.jtom.assign(sz(nzj), 0);
    m.diag.assign(sz(n), -1);
    for (int j = 0; j < n; j++) {
        for (I32 p = m.mp[j]; p < m.mp[j + 1]; p++) pos[m.mi[p]] = p;
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) m.jtom[p] = pos[rowidx[p]];
        m.diag[j] = pos[j];
        for (I32 p = m.mp[j]; p < m.mp[j + 1]; p++) pos[m.mi[p]] = -1;
    }
    return m;
}

void miter_update(Vec& mx, double a, const Vec& values, const Vec& mass, bool has_mass, const std::vector<I32>& jtom,
                  const std::vector<I32>& diag) {
    std::fill(mx.begin(), mx.end(), 0.0);
    const std::size_t nj = jtom.size();
    for (std::size_t p = 0; p < nj; p++) mx[jtom[p]] = -a * values[p];
    const std::size_t n = diag.size();
    if (has_mass) {
        for (std::size_t i = 0; i < n; i++) mx[diag[i]] += mass[i];
    } else {
        for (std::size_t i = 0; i < n; i++) mx[diag[i]] += 1.0;
    }
}

// --- Gilbert-Peierls LU (`SparseLU`) ------------------------------------------------------------------

GP::GP(int n_)
    : n(n_),
      pinv(sz(n_), 0),
      perm(sz(n_), 0),
      x(sz(n_), 0.0),
      xi(sz(n_), 0),
      stack(sz(n_), 0),
      pstack(sz(n_), 0),
      mark(sz(n_), -1),
      Lp(sz(n_) + 1, 0),
      Li(std::max<std::size_t>(4 * sz(n_), 64), 0),
      Lx(std::max<std::size_t>(4 * sz(n_), 64), 0.0),
      Up(sz(n_) + 1, 0),
      Ui(std::max<std::size_t>(4 * sz(n_), 64), 0),
      Ux(std::max<std::size_t>(4 * sz(n_), 64), 0.0),
      t(sz(n_), 0.0) {}

namespace {

/// The rows x of L*x = A(:,col) can be nonzero in, into xi[top..n-1] in the
/// order the solve takes them (`_reach`): an iterative depth-first search, marks
/// stamped rather than cleared.
I32 gp_reach(GP& g, const I32* ap, const I32* ai, I32 col) {
    const I32 n = g.n;
    I32* xi = g.xi.data();
    I32* stack = g.stack.data();
    I64* pstack = g.pstack.data();
    I32* mark = g.mark.data();
    const I32* pinv = g.pinv.data();
    const I64* Lp = g.Lp.data();
    const I32* Li = g.Li.data();
    g.stamp += 1;
    const I32 stamp = g.stamp;
    I32 top = n;
    for (I32 sp = ap[col]; sp < ap[col + 1]; sp++) {
        const I32 start = ai[sp];
        if (mark[start] == stamp) continue;
        I32 head = 0;
        stack[0] = start;
        while (head >= 0) {
            const I32 j = stack[head];
            const I32 J = pinv[j];
            if (mark[j] != stamp) {
                mark[j] = stamp;
                pstack[head] = J < 0 ? 0 : Lp[J] + 1;
            }
            const I64 pend = J < 0 ? 0 : Lp[J + 1];
            bool done = true;
            for (I64 p = pstack[head]; p < pend; p++) {
                const I32 w = Li[p];
                if (mark[w] == stamp) continue;
                pstack[head] = p;
                head += 1;
                stack[head] = w;
                done = false;
                break;
            }
            if (done) {
                head -= 1;
                top -= 1;
                xi[top] = j;
            }
        }
    }
    return top;
}

/// L*x = A(:,col) for the sparse x, over the reach only (`_spsolve`).
I32 gp_spsolve(GP& g, const I32* ap, const I32* ai, const double* ax, I32 col) {
    const I32 n = g.n;
    const I32 top = gp_reach(g, ap, ai, col);
    const I32* xi = g.xi.data();
    double* x = g.x.data();
    const I32* pinv = g.pinv.data();
    const I64* Lp = g.Lp.data();
    const I32* Li = g.Li.data();
    const double* Lx = g.Lx.data();
    I64 flops = 0;
    for (I32 p = top; p < n; p++) x[xi[p]] = 0.0;
    for (I32 p = ap[col]; p < ap[col + 1]; p++) x[ai[p]] = ax[p];
    for (I32 px = top; px < n; px++) {
        const I32 j = xi[px];
        const I32 J = pinv[j];
        if (J < 0) continue;
        flops += Lp[J + 1] - Lp[J] - 1;
        const double xj = x[j];
        if (xj == 0) continue;
        for (I64 p = Lp[J] + 1; p < Lp[J + 1]; p++) x[Li[p]] -= Lx[p] * xj;
    }
    g.flops += flops;
    return top;
}

}  // namespace

void gp_factorize(GP& g, const std::vector<I32>& ap_, const std::vector<I32>& ai_, const Vec& ax_,
                  const std::vector<I32>& q, bool has_q, double limit) {
    const I32 n = g.n;
    if (has_q) g.qcol.assign(q.begin(), q.end());
    g.has_q = has_q;
    g.over = false;
    g.singular = false;
    g.nonfinite = false;
    g.fail_column = -1;
    g.fail_original = -1;
    const I32* ap = ap_.data();
    const I32* ai = ai_.data();
    const double* ax = ax_.data();
    I32* pinv = g.pinv.data();
    I32* perm = g.perm.data();
    double* x = g.x.data();
    const I32* xi = g.xi.data();
    I64* Lp = g.Lp.data();
    I64* Up = g.Up.data();
    std::fill(g.pinv.begin(), g.pinv.end(), -1);
    std::fill(g.mark.begin(), g.mark.end(), -1);
    std::fill(g.x.begin(), g.x.end(), 0.0);
    g.stamp = 0;
    g.flops = 0;
    I64 lnz = 0;
    I64 unz = 0;
    for (I32 k = 0; k < n; k++) {
        Lp[k] = lnz;
        Up[k] = unz;
        // A column holds at most n entries.
        room(g.Li, lnz + n);
        room(g.Lx, lnz + n);
        room(g.Ui, unz + n);
        room(g.Ux, unz + n);
        I32* Li = g.Li.data();
        double* Lx = g.Lx.data();
        I32* Ui = g.Ui.data();
        double* Ux = g.Ux.data();
        const I32 col = has_q ? q[k] : k;
        const I32 top = gp_spsolve(g, ap, ai, ax, col);
        // The pivot: the largest of the rows not yet pivotal; the rows that
        // are belong to U.
        I32 ipiv = -1;
        double best = -1.0;
        for (I32 p = top; p < n; p++) {
            const I32 i = xi[p];
            if (pinv[i] < 0) {
                const double t = std::fabs(x[i]);
                if (t > best) {
                    best = t;
                    ipiv = i;
                }
            } else {
                Ui[unz] = pinv[i];
                Ux[unz] = x[i];
                unz += 1;
            }
        }
        if (ipiv == -1 || !(best > 0) || !std::isfinite(best)) {
            g.singular = true;
            g.nonfinite = best == INF;
            g.fail_column = k;
            g.fail_original = col;
            g.lnz = lnz;
            g.unz = unz;
            for (I32 kk = k; kk <= n; kk++) {
                Lp[kk] = lnz;
                Up[kk] = unz;
            }
            return;
        }
        const double pivot = x[ipiv];
        Ui[unz] = k;
        Ux[unz] = pivot;
        unz += 1;
        pinv[ipiv] = k;
        Li[lnz] = ipiv;
        Lx[lnz] = 1.0;
        lnz += 1;
        for (I32 p = top; p < n; p++) {
            const I32 i = xi[p];
            if (pinv[i] < 0) {
                Li[lnz] = i;
                Lx[lnz] = x[i] / pivot;
                lnz += 1;
            }
            x[i] = 0.0;
        }
        if (static_cast<double>(lnz + unz) > limit) {
            g.over = true;
            g.lnz = lnz;
            g.unz = unz;
            return;
        }
    }
    Lp[n] = lnz;
    Up[n] = unz;
    g.lnz = lnz;
    g.unz = unz;
    I32* Li = g.Li.data();
    for (I64 p = 0; p < lnz; p++) Li[p] = pinv[Li[p]];
    for (I32 i = 0; i < n; i++) perm[pinv[i]] = i;
}

void gp_solve(GP& g, const Vec& b, Vec& out) {
    const I32 n = g.n;
    const I32* perm = g.perm.data();
    double* t = g.t.data();
    const I64* Lp = g.Lp.data();
    const I32* Li = g.Li.data();
    const double* Lx = g.Lx.data();
    const I64* Up = g.Up.data();
    const I32* Ui = g.Ui.data();
    const double* Ux = g.Ux.data();
    for (I32 k = 0; k < n; k++) t[k] = b[perm[k]];
    for (I32 j = 0; j < n; j++) {
        const double xj = t[j];
        if (xj == 0) continue;
        for (I64 p = Lp[j] + 1; p < Lp[j + 1]; p++) t[Li[p]] -= Lx[p] * xj;
    }
    for (I32 j = n - 1; j >= 0; j--) {
        const double d = Ux[Up[j + 1] - 1];
        const double xj = t[j] / d;
        t[j] = xj;
        if (xj == 0) continue;
        for (I64 p = Up[j]; p < Up[j + 1] - 1; p++) t[Ui[p]] -= Ux[p] * xj;
    }
    if (g.has_q) {
        const I32* qcol = g.qcol.data();
        for (I32 k = 0; k < n; k++) out[qcol[k]] = t[k];
    } else {
        for (I32 k = 0; k < n; k++) out[k] = t[k];
    }
}

// --- reverse Cuthill-McKee, and the blocks ------------------------------------------------------------

std::vector<I32> rcm_order(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx) {
    std::vector<I32> deg(sz(n), 0);
    for (int j = 0; j < n; j++) {
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
            const I32 i = rowidx[p];
            if (i == j) continue;
            deg[i] += 1;
            deg[j] += 1;
        }
    }
    std::vector<I32> ptr(sz(n) + 1, 0);
    for (int i = 0; i < n; i++) ptr[i + 1] = ptr[i] + deg[i];
    std::vector<I32> nxt(ptr.begin(), ptr.begin() + n);
    std::vector<I32> adj(sz(ptr[n]), 0);
    for (int j = 0; j < n; j++) {
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
            const I32 i = rowidx[p];
            if (i == j) continue;
            adj[nxt[i]] = j;
            nxt[i] += 1;
            adj[nxt[j]] = i;
            nxt[j] += 1;
        }
    }
    std::vector<I32> seen(sz(n), -1);
    std::vector<I32> dptr(sz(n) + 1, 0);
    std::vector<I32> dadj(sz(ptr[n]), 0);
    I32 k = 0;
    for (int i = 0; i < n; i++) {
        dptr[i] = k;
        for (I32 p = ptr[i]; p < ptr[i + 1]; p++) {
            const I32 w = adj[p];
            if (seen[w] == i) continue;
            seen[w] = i;
            dadj[k] = w;
            k += 1;
        }
    }
    dptr[n] = k;
    // A node's key is its degree, then its number: the keys are distinct, so there is one order
    // whatever the sort, and a key's node is its remainder by n.
    std::vector<I32> degree(sz(n), 0);
    std::vector<I64> keys(sz(n), 0);
    for (int i = 0; i < n; i++) {
        degree[i] = dptr[i + 1] - dptr[i];
        keys[i] = static_cast<I64>(degree[i]) * n + i;
    }
    std::sort(keys.begin(), keys.end());
    std::vector<std::uint8_t> visited(sz(n), 0);
    std::vector<I32> order(sz(n), 0);
    std::vector<I32> queue(sz(n), 0);
    std::vector<I64> nbk(sz(n), 0);
    I32 filled = 0;
    for (int si = 0; si < n; si++) {
        const I32 seed = static_cast<I32>(keys[si] % n);
        if (visited[seed] != 0) continue;
        I32 head = 0;
        I32 tail = 0;
        queue[tail] = seed;
        tail += 1;
        visited[seed] = 1;
        while (head < tail) {
            const I32 v = queue[head];
            head += 1;
            order[filled] = v;
            filled += 1;
            I32 m = 0;
            for (I32 p = dptr[v]; p < dptr[v + 1]; p++) {
                const I32 u = dadj[p];
                if (visited[u] == 0) {
                    nbk[m] = static_cast<I64>(degree[u]) * n + u;
                    m += 1;
                }
            }
            std::sort(nbk.begin(), nbk.begin() + m);
            for (I32 t = 0; t < m; t++) {
                const I32 u = static_cast<I32>(nbk[t] % n);
                visited[u] = 1;
                queue[tail] = u;
                tail += 1;
            }
        }
    }
    std::vector<I32> rev(sz(n), 0);
    for (int i = 0; i < n; i++) rev[i] = order[n - 1 - i];
    return rev;
}

std::pair<I32, std::vector<I32>> block_triangular(int n, const std::vector<I32>& colptr,
                                                  const std::vector<I32>& rowidx) {
    std::vector<I32> index(sz(n), -1);
    std::vector<I32> low(sz(n), 0);
    std::vector<std::uint8_t> on_stack(sz(n), 0);
    std::vector<I32> stack(sz(n), 0);
    std::vector<I32> path(sz(n), 0);
    std::vector<I32> nxt(sz(n), 0);
    std::vector<I32> block(sz(n), 0);
    I32 counter = 0;
    I32 top = 0;
    I32 nblocks = 0;
    for (int s = 0; s < n; s++) {
        if (index[s] >= 0) continue;
        I32 depth = 0;
        path[0] = s;
        index[s] = counter;
        low[s] = counter;
        counter += 1;
        nxt[s] = colptr[s];
        stack[top] = s;
        top += 1;
        on_stack[s] = 1;
        while (depth >= 0) {
            const I32 v = path[depth];
            if (nxt[v] < colptr[v + 1]) {
                const I32 w = rowidx[nxt[v]];
                nxt[v] += 1;
                if (w == v) continue;
                if (index[w] < 0) {
                    index[w] = counter;
                    low[w] = counter;
                    counter += 1;
                    nxt[w] = colptr[w];
                    stack[top] = w;
                    top += 1;
                    on_stack[w] = 1;
                    depth += 1;
                    path[depth] = w;
                } else if (on_stack[w] != 0 && index[w] < low[v]) {
                    low[v] = index[w];
                }
                continue;
            }
            if (low[v] == index[v]) {
                for (;;) {
                    top -= 1;
                    const I32 w = stack[top];
                    on_stack[w] = 0;
                    block[w] = nblocks;
                    if (w == v) break;
                }
                nblocks += 1;
            }
            depth -= 1;
            if (depth >= 0) {
                const I32 u = path[depth];
                if (low[v] < low[u]) low[u] = low[v];
            }
        }
    }
    return {nblocks, std::move(block)};
}

// --- the LU that keeps its pivots (`RefactorLU`) ------------------------------------------------------

RF rf_new(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx, const std::vector<I32>& columns,
          bool has_columns) {
    RF r;
    const I32 nnz = colptr[n];
    r.n = n;
    r.nnzj = nnz;
    r.columns = columns;
    r.has_columns = has_columns;
    r.slot_row.assign(sz(nnz) + sz(n), 0);
    r.slot_col.assign(sz(nnz) + sz(n), 0);
    r.jslot.assign(sz(nnz), 0);
    r.dslot.assign(sz(n), 0);
    std::vector<I32> mark(sz(n), -1);
    I32 ns = 0;
    for (int j = 0; j < n; j++) {
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
            const I32 i = rowidx[p];
            r.slot_row[ns] = i;
            r.slot_col[ns] = j;
            r.jslot[p] = ns;
            mark[i] = ns;
            ns += 1;
        }
        if (mark[j] >= 0) {
            r.dslot[j] = mark[j];
        } else {
            r.slot_row[ns] = j;
            r.slot_col[ns] = j;
            r.dslot[j] = ns;
            ns += 1;
        }
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) mark[rowidx[p]] = -1;
    }
    r.nbase = ns;
    r.nslots = ns;
    r.V.assign(sz(ns), 0.0);
    r.pr.assign(sz(n), 0);
    r.pc.assign(sz(n), 0);
    r.pslot.assign(sz(n), 0);
    r.lstart.assign(sz(n) + 1, 0);
    r.ustart.assign(sz(n) + 1, 0);
    r.tstart.assign(sz(n) + 1, 0);
    r.fill_start.assign(sz(n) + 1, 0);
    r.lslot.assign(64, 0);
    r.lrow.assign(64, 0);
    r.uslot.assign(64, 0);
    r.ucol.assign(64, 0);
    r.T.assign(64, 0);
    r.lval.assign(64, 0.0);
    r.lstep.assign(64, 0);
    r.uval.assign(64, 0.0);
    r.ustep.assign(64, 0);
    r.dval.assign(sz(n), 0.0);
    r.row_step.assign(sz(n), 0);
    r.col_step.assign(sz(n), 0);
    r.row_active.assign(sz(n), 0);
    r.col_active.assign(sz(n), 0);
    r.rc.assign(sz(n), 0);
    r.cc.assign(sz(n), 0);
    r.head.assign(sz(n) + 2, 0);
    r.nxt.assign(sz(n), 0);
    r.prv.assign(sz(n), 0);
    r.at.assign(sz(n), 0);
    r.at_stamp.assign(sz(n), 0);
    r.row_start.assign(sz(n), 0);
    r.row_len.assign(sz(n), 0);
    r.row_cap.assign(sz(n), 0);
    r.col_start.assign(sz(n), 0);
    r.col_len.assign(sz(n), 0);
    r.col_cap.assign(sz(n), 0);
    r.pool.assign(64, 0);
    r.z.assign(sz(n), 0.0);
    return r;
}

namespace {

/// Mass - a*J into V; false where a value is not finite (`load`).
bool rf_load(RF& r, double a, const Vec& values, const Vec& mass, bool has_mass) {
    const I32 n = r.n;
    double* V = r.V.data();
    const I32* jslot = r.jslot.data();
    const I32* dslot = r.dslot.data();
    for (I32 s = 0; s < r.nslots; s++) V[s] = 0.0;
    bool finite = true;
    for (I32 p = 0; p < r.nnzj; p++) {
        const double v = -a * values[p];
        if (!std::isfinite(v)) finite = false;
        V[jslot[p]] = v;
    }
    if (has_mass) {
        for (I32 i = 0; i < n; i++) V[dslot[i]] += mass[i];
    } else {
        for (I32 i = 0; i < n; i++) V[dslot[i]] += 1.0;
    }
    return finite;
}

/// The rows of L and the columns of U as the steps that pivot on them, after every choice (`_order`).
void rf_order(RF& r) {
    const I32 n = r.n;
    for (I32 s = 0; s < n; s++) {
        r.row_step[r.pr[s]] = s;
        r.col_step[r.pc[s]] = s;
    }
    const I32 nl = r.lstart[n];
    const I32 nu = r.ustart[n];
    room(r.lstep, nl);
    room(r.ustep, nu);
    room(r.lval, nl);
    room(r.uval, nu);
    for (I32 k = 0; k < nl; k++) r.lstep[k] = r.row_step[r.lrow[k]];
    for (I32 u = 0; u < nu; u++) r.ustep[u] = r.col_step[r.ucol[u]];
}

/// L's, U's and the pivots' values in step order, after every factorisation (`_pack`).
void rf_pack(RF& r) {
    const I32 n = r.n;
    const double* V = r.V.data();
    const I32 nl = r.lstart[n];
    const I32 nu = r.ustart[n];
    const I32* lslot = r.lslot.data();
    const I32* uslot = r.uslot.data();
    const I32* pslot = r.pslot.data();
    double* lval = r.lval.data();
    double* uval = r.uval.data();
    double* dval = r.dval.data();
    for (I32 k = 0; k < nl; k++) lval[k] = V[lslot[k]];
    for (I32 u = 0; u < nu; u++) uval[u] = V[uslot[u]];
    for (I32 s = 0; s < n; s++) dval[s] = V[pslot[s]];
}

/// Replays the record on V: -1, or the first step whose pivot fails (`refactor`).
I32 rf_refactor(RF& r) {
    const I32 n = r.n;
    double* V = r.V.data();
    const I32* pslot = r.pslot.data();
    const I32* lstart = r.lstart.data();
    const I32* ustart = r.ustart.data();
    const I64* tstart = r.tstart.data();
    const I32* lslot = r.lslot.data();
    const I32* uslot = r.uslot.data();
    const I32* T = r.T.data();
    const double bound = 1 / KEEP_THRESHOLD;
    for (I32 s = 0; s < n; s++) {
        const double piv = V[pslot[s]];
        const double ap = std::fabs(piv);
        if (!(ap > 0) || ap == INF) return s;
        const double lim = bound * ap;
        const I32 l0 = lstart[s];
        const I32 l1 = lstart[s + 1];
        for (I32 k = l0; k < l1; k++)
            if (!(std::fabs(V[lslot[k]]) <= lim)) return s;
        const I32 u0 = ustart[s];
        const I32 u1 = ustart[s + 1];
        I64 t = tstart[s];
        for (I32 k = l0; k < l1; k++) {
            const I32 ls = lslot[k];
            const double f = V[ls] / piv;
            V[ls] = f;
            if (f == 0) {
                t += u1 - u0;
                continue;
            }
            // NOTE(speed): within one row the targets T[t] are distinct slots and none is a
            // source (the sources are the pivot row's), so this loop could be a gather, a
            // multiply-subtract and a scatter, bit for bit; one after another here, as the record is.
            for (I32 u = u0; u < u1; u++) {
                V[T[t]] -= f * V[uslot[u]];
                t += 1;
            }
        }
    }
    return -1;
}

inline void bucket_out(I32* head, I32* nxt, I32* prv, const I32* cc, I32 j) {
    if (prv[j] >= 0) {
        nxt[prv[j]] = nxt[j];
    } else {
        head[cc[j]] = nxt[j];
    }
    if (nxt[j] >= 0) prv[nxt[j]] = prv[j];
}

inline void bucket_in(I32* head, I32* nxt, I32* prv, const I32* cc, I32 j) {
    const I32 c = cc[j];
    prv[j] = -1;
    nxt[j] = head[c];
    if (head[c] >= 0) prv[head[c]] = j;
    head[c] = j;
}

/// Each active row's and column's slots, in slot order, in the pool: room for
/// twice as many again before a list moves (`rowSlots`, `colSlots`).
void lists_from_slots(RF& r) {
    const I32 n = r.n;
    const std::uint8_t* row_active = r.row_active.data();
    const std::uint8_t* col_active = r.col_active.data();
    const I32* slot_row = r.slot_row.data();
    const I32* slot_col = r.slot_col.data();
    I64* row_start = r.row_start.data();
    I32* row_len = r.row_len.data();
    I32* row_cap = r.row_cap.data();
    I64* col_start = r.col_start.data();
    I32* col_len = r.col_len.data();
    I32* col_cap = r.col_cap.data();
    std::fill(r.row_len.begin(), r.row_len.end(), 0);
    std::fill(r.col_len.begin(), r.col_len.end(), 0);
    const I32 nslots = r.nslots;
    for (I32 s = 0; s < nslots; s++) {
        const I32 i = slot_row[s];
        const I32 j = slot_col[s];
        if (row_active[i] == 0 || col_active[j] == 0) continue;
        row_len[i] += 1;
        col_len[j] += 1;
    }
    I64 top = 0;
    for (I32 i = 0; i < n; i++) {
        row_cap[i] = 2 * row_len[i] + 2;
        row_start[i] = top;
        top += row_cap[i];
    }
    for (I32 j = 0; j < n; j++) {
        col_cap[j] = 2 * col_len[j] + 2;
        col_start[j] = top;
        top += col_cap[j];
    }
    room(r.pool, top);
    r.pool_top = top;
    I32* pool = r.pool.data();
    std::fill(r.row_len.begin(), r.row_len.end(), 0);
    std::fill(r.col_len.begin(), r.col_len.end(), 0);
    for (I32 s = 0; s < nslots; s++) {
        const I32 i = slot_row[s];
        const I32 j = slot_col[s];
        if (row_active[i] == 0 || col_active[j] == 0) continue;
        pool[row_start[i] + row_len[i]] = s;
        row_len[i] += 1;
        pool[col_start[j] + col_len[j]] = s;
        col_len[j] += 1;
    }
}

/// `val` onto a row's (or a column's) list, moving the list to the end of the
/// pool with twice the room when it is full.
inline void list_push(RF& r, I64* start, I32* len, I32* cap, I32 idx, I32 val) {
    const I32 ln = len[idx];
    if (ln == cap[idx]) {
        const I32 grown = 2 * cap[idx] + 2;
        const I64 top = r.pool_top;
        room(r.pool, top + grown);
        I32* pool = r.pool.data();
        const I64 s0 = start[idx];
        for (I32 k = 0; k < ln; k++) pool[top + k] = pool[s0 + k];
        start[idx] = top;
        cap[idx] = grown;
        r.pool_top = top + grown;
    }
    r.pool[sz(start[idx] + ln)] = val;
    len[idx] = ln + 1;
}

/// A fill slot at (i, j) (`_newSlot`): the caller has made room in V and the slot arrays.
inline I32 new_slot(RF& r, I32 i, I32 j) {
    const I32 s = r.nslots;
    r.nslots = s + 1;
    r.V[s] = 0.0;
    r.slot_row[s] = i;
    r.slot_col[s] = j;
    list_push(r, r.row_start.data(), r.row_len.data(), r.row_cap.data(), i, s);
    list_push(r, r.col_start.data(), r.col_len.data(), r.col_cap.data(), j, s);
    r.rc[i] += 1;
    r.cc[j] += 1;
    return s;
}

/// Chooses the pivots of steps s0.. from V as the kept steps before s0 left it,
/// eliminating as it goes (`choose`); false when no acceptable pivot remains, a
/// value is not finite, or the work passes `limit`.
bool rf_choose(RF& r, I32 s0) {
    const I32 n = r.n;
    I32* pr = r.pr.data();
    I32* pc = r.pc.data();
    I32* pslot = r.pslot.data();
    I32* lstart = r.lstart.data();
    I32* ustart = r.ustart.data();
    I64* tstart = r.tstart.data();
    I32* fill_start = r.fill_start.data();
    std::uint8_t* row_active = r.row_active.data();
    std::uint8_t* col_active = r.col_active.data();
    I32* rc = r.rc.data();
    I32* cc = r.cc.data();
    I32* head = r.head.data();
    I32* nxt = r.nxt.data();
    I32* prv = r.prv.data();
    I32* at = r.at.data();
    I32* at_stamp = r.at_stamp.data();
    I64* row_start = r.row_start.data();
    I32* row_len = r.row_len.data();
    I64* col_start = r.col_start.data();
    I32* col_len = r.col_len.data();
    const bool has_fixed = r.has_columns;
    const I32* columns = r.columns.data();
    const double limit = r.limit;
    // The pattern and the fill of the kept steps stay; the rest goes.
    r.nslots = s0 > 0 ? fill_start[s0] : r.nbase;
    std::fill(r.row_active.begin(), r.row_active.end(), std::uint8_t{1});
    std::fill(r.col_active.begin(), r.col_active.end(), std::uint8_t{1});
    for (I32 s = 0; s < s0; s++) {
        row_active[pr[s]] = 0;
        col_active[pc[s]] = 0;
    }
    lists_from_slots(r);
    for (I32 i = 0; i < n; i++) {
        rc[i] = row_len[i];
        cc[i] = col_len[i];
    }
    std::fill(r.head.begin(), r.head.end(), -1);
    for (I32 j = 0; j < n; j++)
        if (col_active[j] != 0) bucket_in(head, nxt, prv, cc, j);
    std::fill(r.at_stamp.begin(), r.at_stamp.end(), 0);
    I32 stamp = 0;
    I32 lp = lstart[s0];
    I32 up = ustart[s0];
    I64 tp = tstart[s0];
    for (I32 s = s0; s < n; s++) {
        if (head[0] >= 0) return false;                 // a column with nothing left in it
        double* V = r.V.data();
        I32* slot_row = r.slot_row.data();
        I32* slot_col = r.slot_col.data();
        I32* pool = r.pool.data();
        // The search: the SEARCH_COLUMNS sparsest columns with a candidate, or
        // the one column the fixed order names.
        double best = INF;
        double best_ratio = 0.0;
        I32 bslot = -1;
        int examined = 0;
        const I32 fixed = has_fixed ? columns[s] : -1;
        const I32 cmax = fixed >= 0 ? 1 : n - s;
        I32 c = 1;
        while (c <= cmax && examined < SEARCH_COLUMNS && best > 0) {
            I32 j = fixed >= 0 ? fixed : head[c];
            while (j >= 0 && examined < SEARCH_COLUMNS && best > 0) {
                // Scanned once for the largest, dropping the rows eliminated since.
                const I64 st = col_start[j];
                const I32 ln = col_len[j];
                double m = 0.0;
                I32 keep = 0;
                for (I32 k = 0; k < ln; k++) {
                    const I32 sl = pool[st + k];
                    if (row_active[slot_row[sl]] == 0) continue;
                    pool[st + keep] = sl;
                    keep += 1;
                    const double v = std::fabs(V[sl]);
                    if (!(v < INF)) return false;       // NaN or infinite
                    if (v > m) m = v;
                }
                if (keep < ln) col_len[j] = keep;
                if (m > 0) {
                    examined += 1;
                    const double thr = PIVOT_THRESHOLD * m;
                    const I64 cj = fixed >= 0 ? 1 : c - 1;
                    for (I32 k = 0; k < keep; k++) {
                        const I32 sl = pool[st + k];
                        const double v = std::fabs(V[sl]);
                        if (v < thr) continue;
                        const double cost = static_cast<double>((static_cast<I64>(rc[slot_row[sl]]) - 1) * cj);
                        const double ratio = v / m;
                        if (cost < best || (cost == best && ratio > best_ratio)) {
                            best = cost;
                            best_ratio = ratio;
                            bslot = sl;
                        }
                    }
                }
                j = fixed >= 0 ? -1 : nxt[j];
            }
            c += 1;
        }
        if (bslot < 0) return false;
        const I32 p = slot_row[bslot];
        const I32 q = slot_col[bslot];
        pr[s] = p;
        pc[s] = q;
        pslot[s] = bslot;
        fill_start[s] = r.nslots;
        row_active[p] = 0;
        col_active[q] = 0;
        bucket_out(head, nxt, prv, cc, q);
        // Its column below and its row to the right, among what is active.
        const I64 lst = col_start[q];
        const I32 lln = col_len[q];
        const I64 ust = row_start[p];
        const I32 uln = row_len[p];
        room(r.lslot, static_cast<I64>(lp) + lln);
        room(r.lrow, static_cast<I64>(lp) + lln);
        room(r.uslot, static_cast<I64>(up) + uln);
        room(r.ucol, static_cast<I64>(up) + uln);
        I32* lslot = r.lslot.data();
        I32* lrow = r.lrow.data();
        I32* uslot = r.uslot.data();
        I32* ucol = r.ucol.data();
        lstart[s] = lp;
        ustart[s] = up;
        tstart[s] = tp;
        for (I32 k = 0; k < lln; k++) {
            const I32 sl = pool[lst + k];
            const I32 i = slot_row[sl];
            if (row_active[i] != 0) {
                lslot[lp] = sl;
                lrow[lp] = i;
                lp += 1;
            }
        }
        for (I32 k = 0; k < uln; k++) {
            const I32 sl = pool[ust + k];
            const I32 j = slot_col[sl];
            if (col_active[j] != 0) {
                uslot[up] = sl;
                ucol[up] = j;
                up += 1;
            }
        }
        const I32 l0 = lstart[s];
        const I32 u0 = ustart[s];
        const I64 most = static_cast<I64>(lp - l0) * static_cast<I64>(up - u0);
        // A slot is held in 32 bits: a factor past that is declined (it would not fit in memory).
        if (static_cast<I64>(r.nslots) + most > std::numeric_limits<I32>::max()) return false;
        room(r.T, tp + most);
        room(r.V, static_cast<I64>(r.nslots) + most);
        room(r.slot_row, static_cast<I64>(r.nslots) + most);
        room(r.slot_col, static_cast<I64>(r.nslots) + most);
        I32* T = r.T.data();
        V = r.V.data();
        slot_col = r.slot_col.data();
        for (I32 u = u0; u < up; u++) bucket_out(head, nxt, prv, cc, ucol[u]);
        const double piv = V[bslot];
        for (I32 k = l0; k < lp; k++) {
            const I32 i = lrow[k];
            const double f = V[lslot[k]] / piv;
            V[lslot[k]] = f;
            // Where row i already has an entry, by column.
            stamp += 1;
            pool = r.pool.data();
            const I64 st = row_start[i];
            const I32 ln = row_len[i];
            I32 keep = 0;
            for (I32 rr = 0; rr < ln; rr++) {
                const I32 sl = pool[st + rr];
                const I32 j = slot_col[sl];
                if (col_active[j] == 0) continue;
                pool[st + keep] = sl;
                keep += 1;
                at[j] = sl;
                at_stamp[j] = stamp;
            }
            if (keep < ln) row_len[i] = keep;
            for (I32 u = u0; u < up; u++) {
                const I32 j = ucol[u];
                // Fill is structure whatever its value now: a later matrix may
                // put a number there.
                const I32 t = at_stamp[j] == stamp ? at[j] : new_slot(r, i, j);
                T[tp] = t;
                tp += 1;
                if (f != 0) V[t] -= f * V[uslot[u]];
            }
        }
        for (I32 k = l0; k < lp; k++) rc[lrow[k]] -= 1;
        for (I32 u = u0; u < up; u++) {
            const I32 j = ucol[u];
            cc[j] -= 1;
            bucket_in(head, nxt, prv, cc, j);
        }
        if (static_cast<double>(tp) > limit) return false;
    }
    lstart[n] = lp;
    ustart[n] = up;
    tstart[n] = tp;
    fill_start[n] = r.nslots;
    r.ops = tp;
    r.nnz = r.nslots;
    return true;
}

}  // namespace

bool rf_factor(RF& r, double a, const Vec& values, const Vec& mass, bool has_mass) {
    if (!r.valid) r.nslots = r.nbase;
    if (!rf_load(r, a, values, mass, has_mass)) {
        r.valid = false;
        return false;
    }
    I32 from = 0;
    if (r.valid) {
        from = rf_refactor(r);
        if (from < 0) {
            rf_pack(r);
            return true;
        }
    }
    r.repivots += 1;
    if (!rf_choose(r, from)) {
        r.valid = false;
        return false;
    }
    if (from == 0) {
        r.full_ops = r.ops;
    } else if (static_cast<double>(r.ops) > REORDER_GROWTH * static_cast<double>(r.full_ops)) {
        rf_load(r, a, values, mass, has_mass);
        if (!rf_choose(r, 0)) {
            r.valid = false;
            return false;
        }
        r.full_ops = r.ops;
    }
    r.valid = true;
    rf_order(r);
    rf_pack(r);
    return true;
}

void rf_solve(RF& r, const Vec& b, Vec& out) {
    const I32 n = r.n;
    const I32* pr = r.pr.data();
    const I32* pc = r.pc.data();
    const I32* lstart = r.lstart.data();
    const I32* ustart = r.ustart.data();
    const double* lval = r.lval.data();
    const I32* lstep = r.lstep.data();
    const double* uval = r.uval.data();
    const I32* ustep = r.ustep.data();
    const double* dval = r.dval.data();
    double* z = r.z.data();
    for (I32 s = 0; s < n; s++) z[s] = b[pr[s]];
    for (I32 s = 0; s < n; s++) {
        const double zs = z[s];
        if (zs == 0) continue;
        for (I32 k = lstart[s]; k < lstart[s + 1]; k++) z[lstep[k]] -= lval[k] * zs;
    }
    for (I32 s = n - 1; s >= 0; s--) {
        double t = z[s];
        for (I32 u = ustart[s]; u < ustart[s + 1]; u++) t -= uval[u] * z[ustep[u]];
        z[s] = t / dval[s];
    }
    for (I32 s = 0; s < n; s++) out[pc[s]] = z[s];
}

// --- a block at a time (`BlockLU`) --------------------------------------------------------------------

BK bk_new(int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx, I32 nblocks,
          const std::vector<I32>& block) {
    BK bk;
    bk.n = n;
    bk.nblocks = nblocks;
    std::vector<I32>& start = bk.start;
    start.assign(sz(nblocks) + 1, 0);
    for (int i = 0; i < n; i++) start[block[i] + 1] += 1;
    for (I32 b = 0; b < nblocks; b++) start[b + 1] += start[b];
    std::vector<I32>& member = bk.member;
    member.assign(sz(n), 0);
    std::vector<I32> local(sz(n), 0);
    std::vector<I32> filled(start.begin(), start.begin() + nblocks);
    for (int i = 0; i < n; i++) {
        const I32 b = block[i];
        local[i] = filled[b] - start[b];
        member[filled[b]] = i;
        filled[b] += 1;
    }
    // The entries between blocks, by column: their rows, and where J holds them.
    bk.off_ptr.assign(sz(n) + 1, 0);
    for (int j = 0; j < n; j++) {
        I32 c = 0;
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++)
            if (block[rowidx[p]] != block[j]) c += 1;
        bk.off_ptr[j + 1] = bk.off_ptr[j] + c;
    }
    const I32 noff = bk.off_ptr[n];
    bk.off_row.assign(sz(noff), 0);
    bk.off_pos.assign(sz(noff), 0);
    I32 e = 0;
    for (int j = 0; j < n; j++) {
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
            if (block[rowidx[p]] == block[j]) continue;
            bk.off_row[e] = rowidx[p];
            bk.off_pos[e] = p;
            e += 1;
        }
    }
    // A block of one state: where J holds its diagonal (-1: nowhere). A larger
    // one: its pattern in its own numbering, where J holds each of its entries,
    // and its LU.
    bk.diag_pos.assign(sz(nblocks), -1);
    bk.lu_of.assign(sz(nblocks), -1);
    I32 nlus = 0;
    I32 total = 0;
    for (I32 b = 0; b < nblocks; b++) {
        const I32 s0 = start[b];
        const I32 bsize = start[b + 1] - s0;
        if (bsize == 1) {
            const I32 i = member[s0];
            for (I32 p = colptr[i]; p < colptr[i + 1]; p++)
                if (rowidx[p] == i) bk.diag_pos[b] = p;
            continue;
        }
        for (I32 lc = 0; lc < bsize; lc++) {
            const I32 j = member[s0 + lc];
            for (I32 p = colptr[j]; p < colptr[j + 1]; p++)
                if (block[rowidx[p]] == b) total += 1;
        }
        nlus += 1;
    }
    bk.lus.reserve(sz(nlus));
    bk.pos_ptr.assign(sz(nlus) + 1, 0);
    bk.pos.assign(sz(total), 0);
    I32 most = 0;
    I32 most_entries = 0;
    I32 li = 0;
    I32 k = 0;
    const std::vector<I32> none;
    for (I32 b = 0; b < nblocks; b++) {
        const I32 s0 = start[b];
        const I32 bsize = start[b + 1] - s0;
        if (bsize == 1) continue;
        std::vector<I32> cp(sz(bsize) + 1, 0);
        I32 cnt = 0;
        for (I32 lc = 0; lc < bsize; lc++) {
            const I32 j = member[s0 + lc];
            for (I32 p = colptr[j]; p < colptr[j + 1]; p++)
                if (block[rowidx[p]] == b) cnt += 1;
            cp[lc + 1] = cnt;
        }
        std::vector<I32> ri(sz(cnt), 0);
        bk.pos_ptr[li] = k;
        I32 kk = 0;
        for (I32 lc = 0; lc < bsize; lc++) {
            const I32 j = member[s0 + lc];
            for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
                if (block[rowidx[p]] != b) continue;
                ri[kk] = local[rowidx[p]];
                bk.pos[k] = p;
                kk += 1;
                k += 1;
            }
        }
        bk.lus.push_back(rf_new(bsize, cp, ri, none, false));
        bk.lu_of[b] = li;
        li += 1;
        if (bsize > most) most = bsize;
        if (cnt > most_entries) most_entries = cnt;
    }
    bk.pos_ptr[nlus] = k;
    // The steps in the order the solve takes them, the last block first, in
    // segments: one block of more than one state, or a run of blocks of one
    // state each.
    bk.base.assign(sz(nblocks), 0);
    bk.row_of_step.assign(sz(n), 0);
    bk.col_of_step.assign(sz(n), 0);
    bk.step_of_row.assign(sz(n), 0);
    std::vector<I32> seg_start(sz(nblocks) + 1, 0);
    std::vector<I32> seg_block(sz(nblocks), 0);
    I32 nseg = 0;
    I32 g = 0;
    for (I32 b = nblocks - 1; b >= 0; b--) {
        const I32 bsize = start[b + 1] - start[b];
        bk.base[b] = g;
        if (bsize == 1) {
            const I32 i = member[start[b]];
            bk.row_of_step[g] = i;
            bk.col_of_step[g] = i;
            bk.step_of_row[i] = g;
            if (nseg > 0 && seg_block[nseg - 1] < 0) {
                seg_start[nseg] = g + 1;
            } else {
                seg_block[nseg] = -1;
                nseg += 1;
                seg_start[nseg] = g + 1;
            }
        } else {
            seg_block[nseg] = b;
            nseg += 1;
            seg_start[nseg] = g + bsize;
        }
        g += bsize;
    }
    bk.seg_start.assign(seg_start.begin(), seg_start.begin() + nseg + 1);
    bk.seg_block.assign(seg_block.begin(), seg_block.begin() + nseg);
    // A run of blocks of one state each is solved level by level: first the states
    // that wait for no other of the run, then those waiting only for these, and so
    // on. Solved in the order the blocks come, a chain of compartments is taken link
    // after link, every division waiting for the one before; by level it is every
    // chain's first link, then every chain's second, steps side by side that the
    // processor works at once. The steps of a run are numbered in that order here,
    // and `run_orig` keeps the order the blocks came in, because every sum is still
    // taken in that order (see `bk_solve`) -- the other engines' bits.
    bk.quick = !parity();
    bk.run_orig.assign(sz(n), 0);
    {
        std::vector<I32> level(sz(n), 0);
        std::vector<I32> states;
        std::vector<I32> place;
        for (I32 r = 0; r < nseg; r++) {
            if (bk.seg_block[r] >= 0) continue;
            const I32 g0 = bk.seg_start[r];
            const I32 g1 = bk.seg_start[r + 1];
            I32 deepest = 0;
            for (I32 s = g0; s < g1; s++) {
                const I32 j = bk.col_of_step[s];
                const I32 lv = level[s];
                if (lv > deepest) deepest = lv;
                for (I32 f = bk.off_ptr[j]; f < bk.off_ptr[j + 1]; f++) {
                    const I32 bi = block[bk.off_row[f]];
                    if (start[bi + 1] - start[bi] != 1) continue;
                    const I32 h = bk.base[bi];
                    if (h > s && h < g1 && level[h] <= lv) level[h] = lv + 1;
                }
            }
            if (deepest == 0) {
                for (I32 s = g0; s < g1; s++) bk.run_orig[s] = s;
                continue;
            }
            place.assign(sz(deepest) + 2, 0);
            for (I32 s = g0; s < g1; s++) place[level[s] + 1] += 1;
            for (I32 l = 0; l <= deepest; l++) place[l + 1] += place[l];
            states.assign(sz(g1 - g0), 0);
            for (I32 s = g0; s < g1; s++) {
                const I32 at = place[level[s]]++;
                states[at] = bk.row_of_step[s];
                bk.run_orig[s] = g0 + at;
            }
            for (I32 s = g0; s < g1; s++) {
                const I32 i = states[s - g0];
                bk.base[block[i]] = s;
                bk.row_of_step[s] = i;
                bk.col_of_step[s] = i;
                bk.step_of_row[i] = s;
            }
        }
    }
    bk.pull_p.assign(sz(n) + 1, 0);
    bk.pull_step.assign(sz(noff), 0);
    bk.pull_at.assign(sz(noff), 0);
    bk.pull_x.assign(sz(noff), 0.0);
    bk.push_p.assign(sz(n) + 1, 0);
    bk.push_step.assign(sz(noff), 0);
    bk.push_at.assign(sz(noff), 0);
    bk.push_x.assign(sz(noff), 0.0);
    bk.b_values.assign(sz(most_entries), 0.0);
    bk.b_mass.assign(sz(most), 0.0);
    bk.Lp.assign(sz(n) + 1, 0);
    bk.Up.assign(sz(n) + 1, 0);
    bk.D.assign(sz(n), 0.0);
    if (bk.quick) bk.Dinv.assign(sz(n), 0.0);
    bk.off_p.assign(sz(n) + 1, 0);
    bk.off_step.assign(sz(noff), 0);
    bk.off_at.assign(sz(noff), 0);
    bk.off_x.assign(sz(noff), 0.0);
    bk.zs.assign(sz(n), 0.0);
    return bk;
}

I64 bk_repivots(const BK& bk) {
    I64 r = 0;
    for (const RF& lu : bk.lus) r += lu.repivots;
    return r;
}

namespace {

/// The larger blocks' steps, L's and U's entries by step, and the entries
/// between blocks by the steps of their column and their row (`_layout`).
void bk_layout(BK& bk) {
    const I32 n = bk.n;
    const I32* start = bk.start.data();
    const I32* member = bk.member.data();
    const I32* base = bk.base.data();
    I32* row_of_step = bk.row_of_step.data();
    I32* col_of_step = bk.col_of_step.data();
    I32* step_of_row = bk.step_of_row.data();
    I64* Lp = bk.Lp.data();
    I64* Up = bk.Up.data();
    I64 nl = 0;
    I64 nu = 0;
    for (const RF& lu : bk.lus) {
        nl += lu.lstart[lu.n];
        nu += lu.ustart[lu.n];
    }
    if (static_cast<I64>(bk.Li.size()) < nl) {
        bk.Li.assign(sz(nl), 0);
        bk.Lx.assign(sz(nl), 0.0);
    }
    if (static_cast<I64>(bk.Ui.size()) < nu) {
        bk.Ui.assign(sz(nu), 0);
        bk.Ux.assign(sz(nu), 0.0);
    }
    I32* Li = bk.Li.data();
    I32* Ui = bk.Ui.data();
    I64 lq = 0;
    I64 uq = 0;
    for (I32 k = bk.nblocks - 1; k >= 0; k--) {
        const I32 s0 = start[k];
        const I32 m = start[k + 1] - s0;
        const I32 g0 = base[k];
        const I32 li = bk.lu_of[k];
        if (li < 0) {
            Lp[g0] = lq;
            Up[g0] = uq;
            continue;
        }
        const RF& lu = bk.lus[li];
        const I32* pr = lu.pr.data();
        const I32* pc = lu.pc.data();
        const I32* lstart = lu.lstart.data();
        const I32* lstep = lu.lstep.data();
        const I32* ustart = lu.ustart.data();
        const I32* ustep = lu.ustep.data();
        for (I32 s = 0; s < m; s++) {
            const I32 i = member[s0 + pr[s]];
            row_of_step[g0 + s] = i;
            col_of_step[g0 + s] = member[s0 + pc[s]];
            step_of_row[i] = g0 + s;
            Lp[g0 + s] = lq;
            for (I32 q = lstart[s]; q < lstart[s + 1]; q++) {
                Li[lq] = g0 + lstep[q];
                lq += 1;
            }
            Up[g0 + s] = uq;
            for (I32 u = ustart[s]; u < ustart[s + 1]; u++) {
                Ui[uq] = g0 + ustep[u];
                uq += 1;
            }
        }
    }
    Lp[n] = lq;
    Up[n] = uq;
    const I32* off_ptr = bk.off_ptr.data();
    const I32* off_row = bk.off_row.data();
    const I32* off_pos = bk.off_pos.data();
    I32* off_p = bk.off_p.data();
    I32* off_step = bk.off_step.data();
    I32* off_at = bk.off_at.data();
    I32 e = 0;
    for (I32 g = 0; g < n; g++) {
        off_p[g] = e;
        const I32 j = col_of_step[g];
        for (I32 f = off_ptr[j]; f < off_ptr[j + 1]; f++) {
            off_step[e] = step_of_row[off_row[f]];
            off_at[e] = off_pos[f];
            e += 1;
        }
    }
    off_p[n] = e;
    // The runs of blocks of one state: an entry whose row is in the run goes to that
    // step's list, the lists filled in the order the blocks came, so that a step's
    // sum is taken in the order it always was; the others, to the segments after the
    // run, stay with their column.
    const I32 nseg = static_cast<I32>(bk.seg_block.size());
    const I32* seg_start = bk.seg_start.data();
    const I32* seg_block = bk.seg_block.data();
    const I32* run_orig = bk.run_orig.data();
    I32* pull_p = bk.pull_p.data();
    std::fill(bk.pull_p.begin(), bk.pull_p.end(), 0);
    for (I32 r = 0; r < nseg; r++) {
        if (seg_block[r] >= 0) continue;
        const I32 g1 = seg_start[r + 1];
        for (I32 g = seg_start[r]; g < g1; g++)
            for (I32 q = off_p[g]; q < off_p[g + 1]; q++)
                if (off_step[q] < g1) pull_p[off_step[q] + 1] += 1;
    }
    for (I32 g = 0; g < n; g++) pull_p[g + 1] += pull_p[g];
    bk.npull = pull_p[n];
    std::vector<I32> next(bk.pull_p.begin(), bk.pull_p.begin() + n);
    I32 np = 0;
    for (I32 r = 0; r < nseg; r++) {
        const I32 g0 = seg_start[r];
        const I32 g1 = seg_start[r + 1];
        if (seg_block[r] >= 0) {
            for (I32 g = g0; g < g1; g++) bk.push_p[g] = np;
            continue;
        }
        for (I32 at = g0; at < g1; at++) {
            bk.push_p[at] = np;
            const I32 h = run_orig[at];
            for (I32 q = off_p[h]; q < off_p[h + 1]; q++) {
                const I32 t = off_step[q];
                if (t < g1) {
                    const I32 p = next[t]++;
                    bk.pull_step[p] = h;
                    bk.pull_at[p] = q;
                } else {
                    bk.push_step[np] = t;
                    bk.push_at[np] = q;
                    np += 1;
                }
            }
        }
    }
    bk.push_p[n] = np;
}

/// The factor's values in that layout, after every factorisation, and the
/// entries between blocks from J; false where one is not a number (`_values`).
bool bk_values(BK& bk, double a, const Vec& values) {
    const I32* start = bk.start.data();
    const I32* base = bk.base.data();
    double* Lx = bk.Lx.data();
    double* Ux = bk.Ux.data();
    double* D = bk.D.data();
    I64 lq = 0;
    I64 uq = 0;
    for (I32 k = bk.nblocks - 1; k >= 0; k--) {
        const I32 li = bk.lu_of[k];
        if (li < 0) continue;
        const RF& lu = bk.lus[li];
        const I32 m = start[k + 1] - start[k];
        const I32 g0 = base[k];
        const double* lval = lu.lval.data();
        const double* uval = lu.uval.data();
        const double* dval = lu.dval.data();
        const I32 nl = lu.lstart[m];
        const I32 nu = lu.ustart[m];
        for (I32 q = 0; q < nl; q++) {
            Lx[lq] = lval[q];
            lq += 1;
        }
        for (I32 u = 0; u < nu; u++) {
            Ux[uq] = uval[u];
            uq += 1;
        }
        for (I32 s = 0; s < m; s++) D[g0 + s] = dval[s];
    }
    double* off_x = bk.off_x.data();
    const I32* off_at = bk.off_at.data();
    const std::size_t noff = bk.off_x.size();
    for (std::size_t e = 0; e < noff; e++) {
        const double v = -a * values[off_at[e]];
        if (!std::isfinite(v)) return false;
        off_x[e] = v;
    }
    for (I32 p = 0; p < bk.npull; p++) bk.pull_x[p] = off_x[bk.pull_at[p]];
    for (I32 p = 0, np = bk.push_p[bk.n]; p < np; p++) bk.push_x[p] = off_x[bk.push_at[p]];
    return true;
}

}  // namespace

bool bk_factor(BK& bk, double a, const Vec& values, const Vec& mass, bool has_mass) {
    const I32* start = bk.start.data();
    const I32* member = bk.member.data();
    const I32* base = bk.base.data();
    double* D = bk.D.data();
    const I32* pos_ptr = bk.pos_ptr.data();
    const I32* pos = bk.pos.data();
    const double limit = bk.limit;
    bk.valid = false;
    I64 ops = 0;
    I64 nnz = static_cast<I64>(bk.off_x.size());
    for (I32 b = 0; b < bk.nblocks; b++) {
        const I32 s0 = start[b];
        const I32 li = bk.lu_of[b];
        if (li < 0) {
            const I32 i = member[s0];
            const I32 p = bk.diag_pos[b];
            const double d = (p >= 0 ? -a * values[p] : 0.0) + (has_mass ? mass[i] : 1.0);
            if (!(std::fabs(d) > 0) || !std::isfinite(d)) return false;
            D[base[b]] = d;
            nnz += 1;
            continue;
        }
        const I32 bsize = start[b + 1] - s0;
        const I32 p0 = pos_ptr[li];
        const I32 cnt = pos_ptr[li + 1] - p0;
        for (I32 k = 0; k < cnt; k++) bk.b_values[k] = values[pos[p0 + k]];
        if (has_mass) {
            for (I32 lc = 0; lc < bsize; lc++) bk.b_mass[lc] = mass[member[s0 + lc]];
        }
        RF& lu = bk.lus[li];
        lu.limit = limit == INF ? INF : limit - static_cast<double>(ops);
        const bool ok = rf_factor(lu, a, bk.b_values, bk.b_mass, has_mass);
        lu.limit = INF;
        if (!ok) return false;
        ops += lu.ops;
        nnz += lu.nnz;
        if (static_cast<double>(ops) > limit) return false;
    }
    bk.ops = ops;
    bk.nnz = nnz;
    const I64 chosen = bk_repivots(bk);
    if (chosen != bk.laid_out) {
        bk_layout(bk);
        bk.laid_out = chosen;
    }
    if (!bk_values(bk, a, values)) return false;
    if (bk.quick) {
        double* inv = bk.Dinv.data();
        const I32 n = bk.n;
        for (I32 g = 0; g < n; g++) inv[g] = 1.0 / D[g];
    }
    bk.valid = true;
    return true;
}

void bk_solve(BK& bk, const Vec& b, Vec& out_) {
    const I32 n = bk.n;
    const I32* row_of_step = bk.row_of_step.data();
    const I32* col_of_step = bk.col_of_step.data();
    const I64* Lp = bk.Lp.data();
    const I32* Li = bk.Li.data();
    const double* Lx = bk.Lx.data();
    const I64* Up = bk.Up.data();
    const I32* Ui = bk.Ui.data();
    const double* Ux = bk.Ux.data();
    const double* D = bk.D.data();
    const I32* off_p = bk.off_p.data();
    const I32* off_step = bk.off_step.data();
    const double* off_x = bk.off_x.data();
    double* zs = bk.zs.data();
    double* out = out_.data();
    const I32* seg_start = bk.seg_start.data();
    const I32* seg_block = bk.seg_block.data();
    const I32 nseg = static_cast<I32>(bk.seg_block.size());
    const I32* run_orig = bk.run_orig.data();
    const I32* pull_p = bk.pull_p.data();
    const I32* pull_step = bk.pull_step.data();
    const double* pull_x = bk.pull_x.data();
    const I32* push_p = bk.push_p.data();
    const I32* push_step = bk.push_step.data();
    const double* push_x = bk.push_x.data();
    for (I32 g = 0; g < n; g++) zs[g] = b[row_of_step[g]];
    if (bk.quick) {
        // The same solve, a pivot multiplied by its reciprocal.
        const double* inv = bk.Dinv.data();
        for (I32 r = 0; r < nseg; r++) {
            const I32 g0 = seg_start[r];
            const I32 g1 = seg_start[r + 1];
            if (seg_block[r] < 0) {
                for (I32 g = g0; g < g1; g++) {
                    double acc = zs[g];
                    for (I32 p = pull_p[g], end = pull_p[g + 1]; p < end; p++) acc = muladd(-pull_x[p], zs[pull_step[p]], acc);
                    const double xg = acc * inv[g];
                    zs[g] = xg;
                    out[col_of_step[g]] = xg;
                }
                if (push_p[g1] > push_p[g0]) {
                    for (I32 at = g0; at < g1; at++) {
                        const I32 end = push_p[at + 1];
                        I32 p = push_p[at];
                        if (p == end) continue;
                        const double xh = zs[run_orig[at]];
                        for (; p < end; p++) zs[push_step[p]] = muladd(-push_x[p], xh, zs[push_step[p]]);
                    }
                }
                continue;
            }
            for (I32 g = g0; g < g1; g++) {
                const double zg = zs[g];
                if (zg == 0) continue;
                for (I64 q = Lp[g]; q < Lp[g + 1]; q++) zs[Li[q]] -= Lx[q] * zg;
            }
            for (I32 g = g1 - 1; g >= g0; g--) {
                double t = zs[g];
                for (I64 u = Up[g]; u < Up[g + 1]; u++) t -= Ux[u] * zs[Ui[u]];
                const double xg = t * inv[g];
                zs[g] = xg;
                out[col_of_step[g]] = xg;
                if (xg == 0) continue;
                for (I32 e = off_p[g]; e < off_p[g + 1]; e++) zs[off_step[e]] -= off_x[e] * xg;
            }
        }
        return;
    }
    for (I32 r = 0; r < nseg; r++) {
        const I32 g0 = seg_start[r];
        const I32 g1 = seg_start[r + 1];
        if (seg_block[r] < 0) {
            // A run of blocks of one state, level by level. A step's right-hand side
            // has had the earlier segments' entries taken off it already; the run's
            // own are taken off here, in the order the blocks came, skipping an
            // unknown that is zero -- the operations, and their order, of taking each
            // unknown's column off as soon as it is known, so the same numbers to the bit.
            for (I32 g = g0; g < g1; g++) {
                double acc = zs[g];
                for (I32 p = pull_p[g], end = pull_p[g + 1]; p < end; p++) {
                    const double xh = zs[pull_step[p]];
                    if (xh != 0) acc -= pull_x[p] * xh;
                }
                const double xg = acc / D[g];
                zs[g] = xg;
                out[col_of_step[g]] = xg;
            }
            // What the run hands the segments after it, in the order the blocks came.
            if (push_p[g1] > push_p[g0]) {
                for (I32 at = g0; at < g1; at++) {
                    const I32 end = push_p[at + 1];
                    I32 p = push_p[at];
                    if (p == end) continue;
                    const double xh = zs[run_orig[at]];
                    if (xh == 0) continue;
                    for (; p < end; p++) zs[push_step[p]] -= push_x[p] * xh;
                }
            }
            continue;
        }
        for (I32 g = g0; g < g1; g++) {
            const double zg = zs[g];
            if (zg == 0) continue;
            for (I64 q = Lp[g]; q < Lp[g + 1]; q++) zs[Li[q]] -= Lx[q] * zg;
        }
        for (I32 g = g1 - 1; g >= g0; g--) {
            double t = zs[g];
            for (I64 u = Up[g]; u < Up[g + 1]; u++) t -= Ux[u] * zs[Ui[u]];
            const double xg = t / D[g];
            zs[g] = xg;
            out[col_of_step[g]] = xg;
            if (xg == 0) continue;
            for (I32 e = off_p[g]; e < off_p[g + 1]; e++) zs[off_step[e]] -= off_x[e] * xg;
        }
    }
}

namespace {

/// A kept-pivot LU tried on the start's matrix, stopping once its work passes
/// `most`: whether it was made, into `lu`.
bool trial(RF& lu, int n, const std::vector<I32>& colptr, const std::vector<I32>& rowidx, const Vec& values,
           const Vec& mass, bool has_mass, const std::vector<I32>& columns, bool has_columns, double most) {
    lu = rf_new(n, colptr, rowidx, columns, has_columns);
    if (most < 0) return false;
    lu.limit = most;
    const bool ok = rf_factor(lu, 1e-3, values, mass, has_mass);
    lu.limit = INF;
    return ok;
}

/// By the Gilbert-Peierls LU in the chosen order (`sparseForm`).
int sw_sparse(SparseLUMatrix& sw, double a, const Vec& values) {
    miter_update(sw.mx, a, values, sw.mass, sw.has_mass, sw.jtom, sw.diag_pos);
    GP& g = sw.gp;
    gp_factorize(g, sw.mp, sw.mi, sw.mx, sw.q, sw.has_q, INF);
    if (g.singular) {
        sw.fail_column = g.fail_original;
        sw.fail_value = g.nonfinite ? INF : 0.0;
        sw.fail_nonfinite = g.nonfinite;
        return g.nonfinite ? NONFINITE : SINGULAR;
    }
    return OK;
}

/// By the dense LU of linalg.js (`formAndFactor`), where a matrix the
/// kept-pivot LU declined goes when the searching factor fills in. Held by rows.
int sw_dense(SparseLUMatrix& sw, double a, const Vec& values) {
    const I32 n = sw.n;
    const std::size_t N = sz(n);
    if (sw.dpiv.size() != N) {
        sw.dense.assign(N * N, 0.0);
        sw.dpiv.assign(N, 0);
    }
    double* lu = sw.dense.data();
    I32* piv = sw.dpiv.data();
    const I32* colptr = sw.colptr.data();
    const I32* rowidx = sw.rowidx.data();
    std::fill(sw.dense.begin(), sw.dense.end(), 0.0);
    I32 bad = -1;
    double bad_value = 0.0;
    for (I32 j = 0; j < n; j++) {
        for (I32 p = colptr[j]; p < colptr[j + 1]; p++) {
            const double v = -a * values[p];
            if (bad < 0 && !std::isfinite(v)) {
                bad = j;
                bad_value = v;
            }
            lu[sz(rowidx[p]) * N + sz(j)] = v;
        }
    }
    if (bad >= 0) {
        sw.fail_column = bad;
        sw.fail_value = bad_value;
        sw.fail_nonfinite = true;
        return NONFINITE;
    }
    for (I32 i = 0; i < n; i++) lu[sz(i) * N + sz(i)] += sw.has_mass ? sw.mass[i] : 1.0;
    for (I32 i = 0; i < n; i++) piv[i] = i;
    for (I32 k = 0; k < n; k++) {
        I32 p = k;
        double max_abs = std::fabs(lu[sz(k) * N + sz(k)]);
        for (I32 i = k + 1; i < n; i++) {
            const double v = std::fabs(lu[sz(i) * N + sz(k)]);
            if (v > max_abs) {
                max_abs = v;
                p = i;
            }
        }
        if (!(max_abs > 0) || !std::isfinite(max_abs)) {
            sw.fail_column = k;
            sw.fail_value = max_abs;
            sw.fail_nonfinite = max_abs != 0;
            return max_abs != 0 ? NONFINITE : SINGULAR;
        }
        double* rk = lu + sz(k) * N;
        if (p != k) {
            double* rp = lu + sz(p) * N;
            for (I32 j = 0; j < n; j++) {
                const double tmp = rp[j];
                rp[j] = rk[j];
                rk[j] = tmp;
            }
            const I32 t = piv[p];
            piv[p] = piv[k];
            piv[k] = t;
        }
        const double pivot = rk[k];
        for (I32 i = k + 1; i < n; i++) {
            double* ri = lu + sz(i) * N;
            const double f = ri[k] / pivot;
            if (f == 0) continue;
            ri[k] = f;
            for (I32 j = k + 1; j < n; j++) ri[j] -= f * rk[j];
        }
    }
    return OK;
}

}  // namespace

}  // namespace slu

SparseLUMatrix::SparseLUMatrix(int n_, std::vector<I32> colptr_, std::vector<I32> rowidx_, const Vec& values,
                               Vec mass_, bool has_mass_, int mode, double dense_fill, bool too_big, bool by_block)
    : n(n_),
      colptr(std::move(colptr_)),
      rowidx(std::move(rowidx_)),
      mass(std::move(mass_)),
      has_mass(has_mass_),
      gp(n_) {
    using namespace slu;
    {
        MiterStructure m = miter_structure(n, colptr, rowidx);
        mp = std::move(m.mp);
        mi = std::move(m.mi);
        jtom = std::move(m.jtom);
        diag_pos = std::move(m.diag);
    }
    mx.assign(mi.size(), 0.0);
    masked.assign(static_cast<std::size_t>(colptr[n]), 0.0);
    const std::vector<I32> none;
    // Reverse Cuthill-McKee first, and the model's own order stopped as soon
    // as it fills in past that.
    miter_update(mx, 1e-3, values, mass, has_mass, jtom, diag_pos);
    std::vector<I32> rcm = rcm_order(n, mp, mi);
    gp_factorize(gp, mp, mi, mx, rcm, true, sv::INF);
    const double rcm_fill = gp.singular ? sv::INF : static_cast<double>(gp.lnz + gp.unz);
    gp_factorize(gp, mp, mi, mx, rcm, false, rcm_fill);
    double best = (gp.singular || gp.over) ? sv::INF : static_cast<double>(gp.lnz + gp.unz);
    has_q = false;
    if (rcm_fill < best) {
        best = rcm_fill;
        has_q = true;
    }
    // Both singular says nothing about the fill: sparse, in the order that
    // suits these graphs, and the formations say whether it is singular.
    if (best == sv::INF) {
        best = static_cast<double>(mp[n]);
        has_q = true;
    }
    fill = static_cast<I64>(best);
    ordering = has_q ? RCM : NATURAL;
    fills_in = !too_big && best > dense_fill * n * n;
    trial_repivots = 0;
    kind = SPARSE;
    if (mode == REFACTOR || mode == AUTO) {
        gp_factorize(gp, mp, mi, mx, rcm, has_q, sv::INF);
        const double alternative = fills_in ? 0.25 * n * n * n / 3 : static_cast<double>(gp.flops);
        double limit = mode == REFACTOR ? sv::INF : std::min(OPS_BUDGET, alternative);
        // A block at a time first, where the matrix falls into more than one
        // block: a whole trial is then kept only where it costs less.
        bool by_blocks = false;
        if (by_block) {
            auto [nb, block] = block_triangular(n, colptr, rowidx);
            if (nb > 1) {
                BK bk = bk_new(n, colptr, rowidx, nb, block);
                bk.limit = limit;
                const bool ok = bk_factor(bk, 1e-3, values, mass, has_mass);
                bk.limit = sv::INF;
                if (ok) {
                    limit = std::min(limit, static_cast<double>(bk.ops - 1));
                    blocks = std::move(bk);
                    by_blocks = true;
                }
            }
        }
        RF by_m;
        RF by_c;
        const bool m_ok = trial(by_m, n, colptr, rowidx, values, mass, has_mass, none, false, limit);
        std::vector<I32> cols;
        if (has_q) {
            cols = rcm;
        } else {
            cols.resize(static_cast<std::size_t>(n));
            for (int i = 0; i < n; i++) cols[i] = i;
        }
        const bool c_ok = trial(by_c, n, colptr, rowidx, values, mass, has_mass, cols, true,
                                m_ok ? std::min(limit, static_cast<double>(by_m.ops)) : limit);
        int chosen = 0;                     // 0 none, 1 by Markowitz, 2 in the column order
        if (c_ok && (!m_ok || by_c.ops < by_m.ops)) {
            whole = std::move(by_c);
            chosen = 2;
        } else if (m_ok) {
            whole = std::move(by_m);
            chosen = 1;
        }
        if (by_blocks && (chosen == 0 || blocks.ops <= whole.ops)) {
            kind = BLOCKS;
            ordering = BLOCKED;
            fill = blocks.valid ? blocks.nnz : -1;
            trial_repivots = bk_repivots(blocks);
        } else if (chosen != 0) {
            kind = WHOLE;
            ordering = chosen == 2 ? (has_q ? RCM_COLUMNS : NATURAL_COLUMNS) : MARKOWITZ;
            fill = whole.valid ? whole.nnz : -1;
            trial_repivots = whole.repivots;
        } else if (mode == REFACTOR) {
            whole = rf_new(n, colptr, rowidx, none, false);
            kind = WHOLE;
            ordering = MARKOWITZ;
            fill = -1;
        }
    }
    if (kind == SPARSE && mode == AUTO && fills_in) kind = DENSE;
    if (kind == SPARSE) {
        current = BY_SPARSE;
    } else if ((kind == WHOLE && whole.valid) || (kind == BLOCKS && blocks.valid)) {
        current = KEPT;
    } else {
        current = NONE_MADE;
    }
    q = std::move(rcm);
}

namespace slu {

int form(SparseLUMatrix& sw, double a, const Vec& values, const std::uint8_t* held) {
    const Vec* use = &values;
    // NOTE(speed): the held rows are zeroed in a copy of the values at every formation; the
    // loaders (`miter_update`, `rf_load`, the block LU's) could skip the held rows instead.
    if (held != nullptr) {
        Vec& masked = sw.masked;
        const I32* colptr = sw.colptr.data();
        const I32* rowidx = sw.rowidx.data();
        std::copy(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(masked.size()), masked.begin());
        for (I32 j = 0; j < sw.n; j++)
            for (I32 p = colptr[j]; p < colptr[j + 1]; p++)
                if (held[rowidx[p]] != 0) masked[p] = 0.0;
        use = &masked;
    }
    const int kind = sw.kind;
    if (kind == SPARSE) {
        const int st = sw_sparse(sw, a, *use);
        sw.current = st == OK ? BY_SPARSE : NONE_MADE;
        return st;
    }
    bool ok;
    I64 nnz;
    I64 repivots;
    if (kind == WHOLE) {
        RF& lu = sw.whole;
        ok = rf_factor(lu, a, *use, sw.mass, sw.has_mass);
        nnz = lu.nnz;
        repivots = lu.repivots;
    } else {
        BK& bk = sw.blocks;
        ok = bk_factor(bk, a, *use, sw.mass, sw.has_mass);
        nnz = bk.nnz;
        repivots = bk_repivots(bk);
    }
    int st = OK;
    if (ok) {
        sw.current = KEPT;
        sw.fill = nnz;
    } else {
        sw.fallbacks += 1;
        int by;
        if (sw.fills_in) {
            st = sw_dense(sw, a, *use);
            by = BY_DENSE;
        } else {
            st = sw_sparse(sw, a, *use);
            by = BY_SPARSE;
        }
        sw.current = st == OK ? by : NONE_MADE;
    }
    if (st == OK) sw.repivots = repivots - sw.trial_repivots;
    return st;
}

void solve(SparseLUMatrix& sw, const Vec& b, Vec& out) {
    const int current = sw.current;
    if (current == NONE_MADE) {
        std::fill(out.begin(), out.end(), sv::NOT_A_NUMBER);
    } else if (current == BY_SPARSE) {
        gp_solve(sw.gp, b, out);
    } else if (current == BY_DENSE) {
        const I32 n = sw.n;
        const std::size_t N = static_cast<std::size_t>(n);
        const double* lu = sw.dense.data();
        const I32* piv = sw.dpiv.data();
        for (I32 i = 0; i < n; i++) out[i] = b[piv[i]];
        for (I32 i = 1; i < n; i++) {
            const double* ri = lu + static_cast<std::size_t>(i) * N;
            double s = out[i];
            for (I32 j = 0; j < i; j++) s -= ri[j] * out[j];
            out[i] = s;
        }
        for (I32 i = n - 1; i >= 0; i--) {
            const double* ri = lu + static_cast<std::size_t>(i) * N;
            double s = out[i];
            for (I32 j = i + 1; j < n; j++) s -= ri[j] * out[j];
            out[i] = s / ri[i];
        }
    } else if (sw.kind == WHOLE) {
        rf_solve(sw.whole, b, out);
    } else {
        bk_solve(sw.blocks, b, out);
    }
}

const char* lu_name(const SparseLUMatrix& sw) {
    return (sw.kind == WHOLE || sw.kind == BLOCKS) ? "refactor" : (sw.kind == SPARSE ? "sparse" : "dense");
}

}  // namespace slu

}  // namespace kompartment
