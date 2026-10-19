# The application's sparse LUs (src/ode/core/sparse.js, refactor.js, blocks.js),
# as the Python engine has them (engine/solvers/sparselu.py).
#
# For a sparse iteration matrix the application chooses between a
# Gilbert-Peierls LU in two column orders, the LU that keeps its pivots and
# that LU a block at a time, on one real factorisation of each. These are
# those LUs and that choice, step for step -- the same pivots, the same
# eliminations in the same order, one rounding per operation and no fused
# multiply-adds -- so a sparse matrix is factorised and solved with as the
# application and the Python engine do it, to the last bit.
#
# Every index held here -- a state, a slot, a step, a place in a list -- is
# counted from zero, as in the application and the Python engine, so the three
# read side by side and hold the same numbers; an array is read at the index
# plus one, and -1 is none.

#: refactor.js: a pivot is chosen among the entries at least this share of the
#: largest in their column, and kept while none below it is more than
#: 1/KEEP_THRESHOLD times it; the SEARCH_COLUMNS sparsest columns are searched;
#: and past REORDER_GROWTH times the work of the last choice made from the
#: start, the pivots are chosen from the start again.
const _SLU_PIVOT_THRESHOLD = 0.1
const _SLU_KEEP_THRESHOLD = 0.01
const _SLU_SEARCH_COLUMNS = 16
const _SLU_REORDER_GROWTH = 1.2
#: refactor.js: the record holds one index per multiply-add; past this many
#: `auto` leaves the matrix to the Gilbert-Peierls LU.
const _SLU_OPS_BUDGET = 4e6

#: What a matrix is factorised with: the caller's dense LU (`auto` chose it),
#: the Gilbert-Peierls LU, the kept-pivot LU whole, or a block at a time.
const _SLU_DENSE = 0
const _SLU_SPARSE = 1
const _SLU_WHOLE = 2
const _SLU_BLOCKS = 3
#: The column orders, as `info["ordering"]` names them.
const _SLU_ORDERINGS = ("natural", "reverse Cuthill-McKee", "threshold Markowitz", "natural columns, threshold rows",
                        "reverse Cuthill-McKee columns, threshold rows", "block triangular, threshold Markowitz")
const _SLU_NATURAL = 0
const _SLU_RCM = 1
const _SLU_MARKOWITZ = 2
const _SLU_NATURAL_COLUMNS = 3
const _SLU_RCM_COLUMNS = 4
const _SLU_BLOCKED = 5
#: The modes `iterationMatrix` takes a sparse LU in.
const _SLU_AUTO = 0
const _SLU_REFACTOR = 1
const _SLU_SPARSE_MODE = 2
#: Which LU the latest factorisation is in: the kept-pivot one, or what a
#: matrix it declined went to -- or none, the latest formation having failed
#: (or none made yet, where there was no trial), which no solve reads.
const _SLU_KEPT = 0
const _SLU_BY_SPARSE = 1
const _SLU_BY_DENSE = 2
const _SLU_NONE_MADE = 3
#: A formation's outcome: factorised, singular, or a value not a number.
const _SLU_OK = 0
const _SLU_SINGULAR = 1
const _SLU_NONFINITE = 2

"""`a` grown in place to hold at least `need`, zeros after what it held (`room` in refactor.js)."""
function _slu_room!(a::Vector{T}, need::Int) where {T}
    need <= length(a) && return a
    cap = max(length(a), 64)
    while cap < need
        cap *= 2
    end
    old = length(a)
    resize!(a, cap)
    @inbounds for k in old+1:cap
        a[k] = zero(T)
    end
    return a
end

# --- Mass - a*J in CSC (`makeMiterBuilder`) ------------------------------------------------------------

"""The pattern of Mass - a*J -- J's with the diagonal, each column's rows in
order -- and where J's entries (`jtom`) and the diagonal sit in it."""
function _slu_miter_structure(n::Int, colptr::Vector{Int}, rowidx::Vector{Int})
    nzj = colptr[n+1]
    mp = zeros(Int, n + 1)
    mi = zeros(Int, nzj + n)
    k = 0
    rows = Int[]
    @inbounds for j in 0:n-1
        m = colptr[j+2] - colptr[j+1]
        resize!(rows, m + 1)
        for p in 0:m-1
            rows[p+1] = rowidx[colptr[j+1]+p+1]
        end
        rows[m+1] = j
        sort!(rows)
        mp[j+1] = k
        last = -1
        for r in rows
            if r != last
                mi[k+1] = r
                k += 1
                last = r
            end
        end
    end
    mp[n+1] = k
    resize!(mi, k)
    pos = fill(-1, n)
    jtom = zeros(Int, nzj)
    diag = fill(-1, n)
    @inbounds for j in 0:n-1
        for p in mp[j+1]:mp[j+2]-1
            pos[mi[p+1]+1] = p
        end
        for p in colptr[j+1]:colptr[j+2]-1
            jtom[p+1] = pos[rowidx[p+1]+1]
        end
        diag[j+1] = pos[j+1]
        for p in mp[j+1]:mp[j+2]-1
            pos[mi[p+1]+1] = -1
        end
    end
    return mp, mi, jtom, diag
end

"""mx := the values of Mass - a*J (`update`)."""
function _slu_miter_update!(mx::Vector{Float64}, a::Float64, values::Vector{Float64}, mass::Vector{Float64},
                            has_mass::Bool, jtom::Vector{Int}, diag::Vector{Int})
    fill!(mx, 0.0)
    @inbounds for p in 0:length(jtom)-1
        mx[jtom[p+1]+1] = -a * values[p+1]
    end
    if has_mass
        @inbounds for i in 0:length(diag)-1
            mx[diag[i+1]+1] += mass[i+1]
        end
    else
        @inbounds for i in 0:length(diag)-1
            mx[diag[i+1]+1] += 1.0
        end
    end
    return mx
end

# --- Gilbert-Peierls LU (`SparseLU`) -------------------------------------------------------------------

"""The Gilbert-Peierls LU: the row each step pivots on (`pinv` by row, `perm`
by step), the column order (`qcol`, used where `has_q`), the depth-first
search's work, L by columns with the unit diagonal first and U with the pivot
last, a solve's work, and how the latest factorisation went."""
mutable struct _SluGP
    n::Int
    pinv::Vector{Int}
    perm::Vector{Int}
    qcol::Vector{Int}
    has_q::Bool
    x::Vector{Float64}
    xi::Vector{Int}
    stack::Vector{Int}
    pstack::Vector{Int}
    mark::Vector{Int}
    stamp::Int
    Lp::Vector{Int}
    Li::Vector{Int}
    Lx::Vector{Float64}
    Up::Vector{Int}
    Ui::Vector{Int}
    Ux::Vector{Float64}
    t::Vector{Float64}
    lnz::Int
    unz::Int
    flops::Int
    singular::Bool
    nonfinite::Bool
    over::Bool
    fail_column::Int
    fail_original::Int
end

function _SluGP(n::Int)
    cap = max(4 * n, 64)
    return _SluGP(n, zeros(Int, n), zeros(Int, n), Int[], false, zeros(n), zeros(Int, n), zeros(Int, n),
                  zeros(Int, n), fill(-1, n), 0, zeros(Int, n + 1), zeros(Int, cap), zeros(cap), zeros(Int, n + 1),
                  zeros(Int, cap), zeros(cap), zeros(n), 0, 0, 0, false, false, false, -1, -1)
end

"""The rows x of L*x = A(:,col) can be nonzero in, into xi[top..n-1] in the
order the solve takes them (`_reach`): an iterative depth-first search, marks
stamped rather than cleared."""
function _slu_gp_reach!(g::_SluGP, ap::Vector{Int}, ai::Vector{Int}, col::Int)
    n = g.n
    xi = g.xi
    stack = g.stack
    pstack = g.pstack
    mark = g.mark
    pinv = g.pinv
    Lp = g.Lp
    Li = g.Li
    g.stamp += 1
    stamp = g.stamp
    top = n
    @inbounds for sp in ap[col+1]:ap[col+2]-1
        start = ai[sp+1]
        mark[start+1] == stamp && continue
        head = 0
        stack[1] = start
        while head >= 0
            j = stack[head+1]
            J = pinv[j+1]
            if mark[j+1] != stamp
                mark[j+1] = stamp
                pstack[head+1] = J < 0 ? 0 : Lp[J+1] + 1
            end
            pend = J < 0 ? 0 : Lp[J+2]
            done = true
            for p in pstack[head+1]:pend-1
                w = Li[p+1]
                mark[w+1] == stamp && continue
                pstack[head+1] = p
                head += 1
                stack[head+1] = w
                done = false
                break
            end
            if done
                head -= 1
                top -= 1
                xi[top+1] = j
            end
        end
    end
    return top
end

"""L*x = A(:,col) for the sparse x, over the reach only (`_spsolve`)."""
function _slu_gp_spsolve!(g::_SluGP, ap::Vector{Int}, ai::Vector{Int}, ax::Vector{Float64}, col::Int)
    n = g.n
    top = _slu_gp_reach!(g, ap, ai, col)
    xi = g.xi
    x = g.x
    pinv = g.pinv
    Lp = g.Lp
    Li = g.Li
    Lx = g.Lx
    flops = 0
    @inbounds begin
        for p in top:n-1
            x[xi[p+1]+1] = 0.0
        end
        for p in ap[col+1]:ap[col+2]-1
            x[ai[p+1]+1] = ax[p+1]
        end
        for px in top:n-1
            j = xi[px+1]
            J = pinv[j+1]
            J < 0 && continue
            flops += Lp[J+2] - Lp[J+1] - 1
            xj = x[j+1]
            xj == 0 && continue
            for p in Lp[J+1]+1:Lp[J+2]-1
                x[Li[p+1]+1] -= Lx[p+1] * xj
            end
        end
    end
    g.flops += flops
    return top
end

"""P*A*Q = L*U, Q the column order `q` where `has_q` (`factorize`); stops as
soon as L and U hold more than `limit` entries, `over` set."""
function _slu_gp_factorize!(g::_SluGP, ap::Vector{Int}, ai::Vector{Int}, ax::Vector{Float64}, q::Vector{Int},
                            has_q::Bool, limit::Float64)
    n = g.n
    g.qcol = q
    g.has_q = has_q
    g.over = false
    g.singular = false
    g.nonfinite = false
    g.fail_column = -1
    g.fail_original = -1
    pinv = g.pinv
    perm = g.perm
    mark = g.mark
    x = g.x
    xi = g.xi
    Lp = g.Lp
    Up = g.Up
    fill!(pinv, -1)
    fill!(mark, -1)
    fill!(x, 0.0)
    g.stamp = 0
    g.flops = 0
    lnz = 0
    unz = 0
    @inbounds for k in 0:n-1
        Lp[k+1] = lnz
        Up[k+1] = unz
        # A column holds at most n entries.
        _slu_room!(g.Li, lnz + n)
        _slu_room!(g.Lx, lnz + n)
        _slu_room!(g.Ui, unz + n)
        _slu_room!(g.Ux, unz + n)
        Li = g.Li
        Lx = g.Lx
        Ui = g.Ui
        Ux = g.Ux
        col = has_q ? q[k+1] : k
        top = _slu_gp_spsolve!(g, ap, ai, ax, col)
        # The pivot: the largest of the rows not yet pivotal; the rows that
        # are belong to U.
        ipiv = -1
        best = -1.0
        for p in top:n-1
            i = xi[p+1]
            if pinv[i+1] < 0
                t = abs(x[i+1])
                if t > best
                    best = t
                    ipiv = i
                end
            else
                Ui[unz+1] = pinv[i+1]
                Ux[unz+1] = x[i+1]
                unz += 1
            end
        end
        if ipiv == -1 || !(best > 0) || !isfinite(best)
            g.singular = true
            g.nonfinite = best == Inf
            g.fail_column = k
            g.fail_original = col
            g.lnz = lnz
            g.unz = unz
            for kk in k:n
                Lp[kk+1] = lnz
                Up[kk+1] = unz
            end
            return g
        end
        pivot = x[ipiv+1]
        Ui[unz+1] = k
        Ux[unz+1] = pivot
        unz += 1
        pinv[ipiv+1] = k
        Li[lnz+1] = ipiv
        Lx[lnz+1] = 1.0
        lnz += 1
        for p in top:n-1
            i = xi[p+1]
            if pinv[i+1] < 0
                Li[lnz+1] = i
                Lx[lnz+1] = x[i+1] / pivot
                lnz += 1
            end
            x[i+1] = 0.0
        end
        if lnz + unz > limit
            g.over = true
            g.lnz = lnz
            g.unz = unz
            return g
        end
    end
    Lp[n+1] = lnz
    Up[n+1] = unz
    g.lnz = lnz
    g.unz = unz
    Li = g.Li
    @inbounds for p in 0:lnz-1
        Li[p+1] = pinv[Li[p+1]+1]
    end
    @inbounds for i in 0:n-1
        perm[pinv[i+1]+1] = i
    end
    return g
end

"""A*x = b into `out`: P b, then L \\ ., then U \\ ., through Q (`solve`)."""
function _slu_gp_solve!(g::_SluGP, b::Vector{Float64}, out::Vector{Float64})
    n = g.n
    perm = g.perm
    t = g.t
    Lp = g.Lp
    Li = g.Li
    Lx = g.Lx
    Up = g.Up
    Ui = g.Ui
    Ux = g.Ux
    @inbounds begin
        for k in 0:n-1
            t[k+1] = b[perm[k+1]+1]
        end
        for j in 0:n-1
            xj = t[j+1]
            xj == 0 && continue
            for p in Lp[j+1]+1:Lp[j+2]-1
                t[Li[p+1]+1] -= Lx[p+1] * xj
            end
        end
        for j in n-1:-1:0
            d = Ux[Up[j+2]]
            xj = t[j+1] / d
            t[j+1] = xj
            xj == 0 && continue
            for p in Up[j+1]:Up[j+2]-2
                t[Ui[p+1]+1] -= Ux[p+1] * xj
            end
        end
        if g.has_q
            qcol = g.qcol
            for k in 0:n-1
                out[qcol[k+1]+1] = t[k+1]
            end
        else
            for k in 0:n-1
                out[k+1] = t[k+1]
            end
        end
    end
    return out
end

# --- reverse Cuthill-McKee, and the blocks --------------------------------------------------------------

"""Reverse Cuthill-McKee on the pattern of A + A' (`reverseCuthillMcKee`): each
component from its node of least degree, neighbours by degree, ties by number."""
function _slu_rcm_order(n::Int, colptr::Vector{Int}, rowidx::Vector{Int})::Vector{Int}
    deg = zeros(Int, n)
    @inbounds for j in 0:n-1, p in colptr[j+1]:colptr[j+2]-1
        i = rowidx[p+1]
        i == j && continue
        deg[i+1] += 1
        deg[j+1] += 1
    end
    ptr = zeros(Int, n + 1)
    @inbounds for i in 0:n-1
        ptr[i+2] = ptr[i+1] + deg[i+1]
    end
    nxt = ptr[1:n]
    adj = zeros(Int, ptr[n+1])
    @inbounds for j in 0:n-1, p in colptr[j+1]:colptr[j+2]-1
        i = rowidx[p+1]
        i == j && continue
        adj[nxt[i+1]+1] = j
        nxt[i+1] += 1
        adj[nxt[j+1]+1] = i
        nxt[j+1] += 1
    end
    seen = fill(-1, n)
    dptr = zeros(Int, n + 1)
    dadj = zeros(Int, ptr[n+1])
    k = 0
    @inbounds for i in 0:n-1
        dptr[i+1] = k
        for p in ptr[i+1]:ptr[i+2]-1
            w = adj[p+1]
            seen[w+1] == i && continue
            seen[w+1] = i
            dadj[k+1] = w
            k += 1
        end
    end
    dptr[n+1] = k
    degree = zeros(Int, n)
    keys = zeros(Int, n)
    @inbounds for i in 0:n-1
        degree[i+1] = dptr[i+2] - dptr[i+1]
        keys[i+1] = degree[i+1] * n + i
    end
    by_degree = sortperm(keys)          # the keys are distinct: one order whatever the sort
    visited = zeros(UInt8, n)
    order = zeros(Int, n)
    queue = zeros(Int, n)
    nb = zeros(Int, n)
    nbk = zeros(Int, n)
    filled = 0
    @inbounds for si in 0:n-1
        seed = by_degree[si+1] - 1
        visited[seed+1] != 0 && continue
        head = 0
        tail = 0
        queue[tail+1] = seed
        tail += 1
        visited[seed+1] = 1
        while head < tail
            v = queue[head+1]
            head += 1
            order[filled+1] = v
            filled += 1
            m = 0
            for p in dptr[v+1]:dptr[v+2]-1
                u = dadj[p+1]
                if visited[u+1] == 0
                    nb[m+1] = u
                    nbk[m+1] = degree[u+1] * n + u
                    m += 1
                end
            end
            idx = sortperm(view(nbk, 1:m))
            for t in 0:m-1
                u = nb[idx[t+1]]
                visited[u+1] = 1
                queue[tail+1] = u
                tail += 1
            end
        end
    end
    rev = zeros(Int, n)
    @inbounds for i in 0:n-1
        rev[i+1] = order[n-i]
    end
    return rev
end

"""The strongly connected components of the pattern's graph, an edge from
column j to row i for each entry (i, j) off the diagonal, numbered in the
order Tarjan's algorithm closes them (`blockTriangular`): block upper
triangular. Without recursion."""
function _slu_block_triangular(n::Int, colptr::Vector{Int}, rowidx::Vector{Int})
    index = fill(-1, n)
    low = zeros(Int, n)
    on_stack = zeros(UInt8, n)
    stack = zeros(Int, n)
    path = zeros(Int, n)
    nxt = zeros(Int, n)
    block = zeros(Int, n)
    counter = 0
    top = 0
    nblocks = 0
    @inbounds for s in 0:n-1
        index[s+1] >= 0 && continue
        depth = 0
        path[1] = s
        index[s+1] = counter
        low[s+1] = counter
        counter += 1
        nxt[s+1] = colptr[s+1]
        stack[top+1] = s
        top += 1
        on_stack[s+1] = 1
        while depth >= 0
            v = path[depth+1]
            if nxt[v+1] < colptr[v+2]
                w = rowidx[nxt[v+1]+1]
                nxt[v+1] += 1
                w == v && continue
                if index[w+1] < 0
                    index[w+1] = counter
                    low[w+1] = counter
                    counter += 1
                    nxt[w+1] = colptr[w+1]
                    stack[top+1] = w
                    top += 1
                    on_stack[w+1] = 1
                    depth += 1
                    path[depth+1] = w
                elseif on_stack[w+1] != 0 && index[w+1] < low[v+1]
                    low[v+1] = index[w+1]
                end
                continue
            end
            if low[v+1] == index[v+1]
                while true
                    top -= 1
                    w = stack[top+1]
                    on_stack[w+1] = 0
                    block[w+1] = nblocks
                    w == v && break
                end
                nblocks += 1
            end
            depth -= 1
            if depth >= 0
                u = path[depth+1]
                if low[v+1] < low[u+1]
                    low[u+1] = low[v+1]
                end
            end
        end
    end
    return nblocks, block
end

# --- the LU that keeps its pivots (`RefactorLU`) -------------------------------------------------------

"""The kept-pivot LU: the slots (every entry of the matrix and its fill, by
row and column, the pattern's and the diagonal's places among them), the
record of the steps, the factor as a solve reads it, and the work of choosing
-- each row's and column's slots in one pool, a list each."""
mutable struct _SluRF
    n::Int
    nnzj::Int
    columns::Vector{Int}
    has_columns::Bool
    slot_row::Vector{Int}
    slot_col::Vector{Int}
    jslot::Vector{Int}
    dslot::Vector{Int}
    nbase::Int
    nslots::Int
    V::Vector{Float64}
    pr::Vector{Int}
    pc::Vector{Int}
    pslot::Vector{Int}
    lstart::Vector{Int}
    ustart::Vector{Int}
    tstart::Vector{Int}
    fill_start::Vector{Int}
    lslot::Vector{Int}
    lrow::Vector{Int}
    uslot::Vector{Int}
    ucol::Vector{Int}
    T::Vector{Int}
    lval::Vector{Float64}
    lstep::Vector{Int}
    uval::Vector{Float64}
    ustep::Vector{Int}
    dval::Vector{Float64}
    row_step::Vector{Int}
    col_step::Vector{Int}
    valid::Bool
    ops::Int
    nnz::Int
    repivots::Int
    full_ops::Int
    limit::Float64
    row_active::Vector{UInt8}
    col_active::Vector{UInt8}
    rc::Vector{Int}
    cc::Vector{Int}
    head::Vector{Int}
    nxt::Vector{Int}
    prv::Vector{Int}
    at::Vector{Int}
    at_stamp::Vector{Int}
    row_start::Vector{Int}
    row_len::Vector{Int}
    row_cap::Vector{Int}
    col_start::Vector{Int}
    col_len::Vector{Int}
    col_cap::Vector{Int}
    pool::Vector{Int}
    pool_top::Int
    z::Vector{Float64}
end

"""For J's pattern (`colptr`, `rowidx`, counted from zero); `columns` a fixed
column order where `has_columns`, else columns chosen by threshold Markowitz too."""
function _slu_rf_new(n::Int, colptr::Vector{Int}, rowidx::Vector{Int}, columns::Vector{Int}, has_columns::Bool)
    nnz = colptr[n+1]
    slot_row = zeros(Int, nnz + n)
    slot_col = zeros(Int, nnz + n)
    jslot = zeros(Int, nnz)
    dslot = zeros(Int, n)
    mark = fill(-1, n)
    ns = 0
    @inbounds for j in 0:n-1
        for p in colptr[j+1]:colptr[j+2]-1
            i = rowidx[p+1]
            slot_row[ns+1] = i
            slot_col[ns+1] = j
            jslot[p+1] = ns
            mark[i+1] = ns
            ns += 1
        end
        if mark[j+1] >= 0
            dslot[j+1] = mark[j+1]
        else
            slot_row[ns+1] = j
            slot_col[ns+1] = j
            dslot[j+1] = ns
            ns += 1
        end
        for p in colptr[j+1]:colptr[j+2]-1
            mark[rowidx[p+1]+1] = -1
        end
    end
    z64() = zeros(Int, 64)
    return _SluRF(n, nnz, columns, has_columns, slot_row, slot_col, jslot, dslot, ns, ns, zeros(ns),
                  zeros(Int, n), zeros(Int, n), zeros(Int, n), zeros(Int, n + 1), zeros(Int, n + 1),
                  zeros(Int, n + 1), zeros(Int, n + 1), z64(), z64(), z64(), z64(), z64(),
                  zeros(64), z64(), zeros(64), z64(), zeros(n), zeros(Int, n), zeros(Int, n),
                  false, 0, 0, 0, 0, Inf,
                  zeros(UInt8, n), zeros(UInt8, n), zeros(Int, n), zeros(Int, n), zeros(Int, n + 2), zeros(Int, n),
                  zeros(Int, n), zeros(Int, n), zeros(Int, n),
                  zeros(Int, n), zeros(Int, n), zeros(Int, n), zeros(Int, n), zeros(Int, n), zeros(Int, n),
                  z64(), 0, zeros(n))
end

"""Mass - a*J into V; false where a value is not finite (`load`)."""
function _slu_rf_load!(r::_SluRF, a::Float64, values::Vector{Float64}, mass::Vector{Float64}, has_mass::Bool)
    n = r.n
    V = r.V
    jslot = r.jslot
    dslot = r.dslot
    @inbounds for s in 0:r.nslots-1
        V[s+1] = 0.0
    end
    finite = true
    @inbounds for p in 0:r.nnzj-1
        v = -a * values[p+1]
        isfinite(v) || (finite = false)
        V[jslot[p+1]+1] = v
    end
    if has_mass
        @inbounds for i in 0:n-1
            V[dslot[i+1]+1] += mass[i+1]
        end
    else
        @inbounds for i in 0:n-1
            V[dslot[i+1]+1] += 1.0
        end
    end
    return finite
end

"""The rows of L and the columns of U as the steps that pivot on them, after every choice (`_order`)."""
function _slu_rf_order!(r::_SluRF)
    n = r.n
    pr = r.pr
    pc = r.pc
    row_step = r.row_step
    col_step = r.col_step
    @inbounds for s in 0:n-1
        row_step[pr[s+1]+1] = s
        col_step[pc[s+1]+1] = s
    end
    nl = r.lstart[n+1]
    nu = r.ustart[n+1]
    _slu_room!(r.lstep, nl)
    _slu_room!(r.ustep, nu)
    _slu_room!(r.lval, nl)
    _slu_room!(r.uval, nu)
    lstep = r.lstep
    ustep = r.ustep
    lrow = r.lrow
    ucol = r.ucol
    @inbounds for k in 0:nl-1
        lstep[k+1] = row_step[lrow[k+1]+1]
    end
    @inbounds for u in 0:nu-1
        ustep[u+1] = col_step[ucol[u+1]+1]
    end
    return r
end

"""L's, U's and the pivots' values in step order, after every factorisation (`_pack`)."""
function _slu_rf_pack!(r::_SluRF)
    n = r.n
    V = r.V
    nl = r.lstart[n+1]
    nu = r.ustart[n+1]
    lslot = r.lslot
    uslot = r.uslot
    pslot = r.pslot
    lval = r.lval
    uval = r.uval
    dval = r.dval
    @inbounds for k in 0:nl-1
        lval[k+1] = V[lslot[k+1]+1]
    end
    @inbounds for u in 0:nu-1
        uval[u+1] = V[uslot[u+1]+1]
    end
    @inbounds for s in 0:n-1
        dval[s+1] = V[pslot[s+1]+1]
    end
    return r
end

"""Replays the record on V: -1, or the first step whose pivot fails (`refactor`)."""
function _slu_rf_refactor!(r::_SluRF)::Int
    n = r.n
    V = r.V
    pslot = r.pslot
    lstart = r.lstart
    ustart = r.ustart
    tstart = r.tstart
    lslot = r.lslot
    uslot = r.uslot
    T = r.T
    bound = 1 / _SLU_KEEP_THRESHOLD
    @inbounds for s in 0:n-1
        piv = V[pslot[s+1]+1]
        ap = abs(piv)
        (!(ap > 0) || ap == Inf) && return s
        lim = bound * ap
        l0 = lstart[s+1]
        l1 = lstart[s+2]
        for k in l0:l1-1
            !(abs(V[lslot[k+1]+1]) <= lim) && return s
        end
        u0 = ustart[s+1]
        u1 = ustart[s+2]
        t = tstart[s+1]
        for k in l0:l1-1
            ls = lslot[k+1]
            f = V[ls+1] / piv
            V[ls+1] = f
            if f == 0
                t += u1 - u0
                continue
            end
            for u in u0:u1-1
                V[T[t+1]+1] -= f * V[uslot[u+1]+1]
                t += 1
            end
        end
    end
    return -1
end

@inline function _slu_bucket_out!(head::Vector{Int}, nxt::Vector{Int}, prv::Vector{Int}, cc::Vector{Int}, j::Int)
    @inbounds begin
        if prv[j+1] >= 0
            nxt[prv[j+1]+1] = nxt[j+1]
        else
            head[cc[j+1]+1] = nxt[j+1]
        end
        if nxt[j+1] >= 0
            prv[nxt[j+1]+1] = prv[j+1]
        end
    end
    return nothing
end

@inline function _slu_bucket_in!(head::Vector{Int}, nxt::Vector{Int}, prv::Vector{Int}, cc::Vector{Int}, j::Int)
    @inbounds begin
        c = cc[j+1]
        prv[j+1] = -1
        nxt[j+1] = head[c+1]
        if head[c+1] >= 0
            prv[head[c+1]+1] = j
        end
        head[c+1] = j
    end
    return nothing
end

"""Each active row's and column's slots, in slot order, in the pool: room for
twice as many again before a list moves (`rowSlots`, `colSlots`)."""
function _slu_lists_from_slots!(r::_SluRF)
    n = r.n
    row_active = r.row_active
    col_active = r.col_active
    slot_row = r.slot_row
    slot_col = r.slot_col
    row_start = r.row_start
    row_len = r.row_len
    row_cap = r.row_cap
    col_start = r.col_start
    col_len = r.col_len
    col_cap = r.col_cap
    fill!(row_len, 0)
    fill!(col_len, 0)
    nslots = r.nslots
    @inbounds for s in 0:nslots-1
        i = slot_row[s+1]
        j = slot_col[s+1]
        (row_active[i+1] == 0 || col_active[j+1] == 0) && continue
        row_len[i+1] += 1
        col_len[j+1] += 1
    end
    top = 0
    @inbounds for i in 0:n-1
        row_cap[i+1] = 2 * row_len[i+1] + 2
        row_start[i+1] = top
        top += row_cap[i+1]
    end
    @inbounds for j in 0:n-1
        col_cap[j+1] = 2 * col_len[j+1] + 2
        col_start[j+1] = top
        top += col_cap[j+1]
    end
    _slu_room!(r.pool, top)
    r.pool_top = top
    pool = r.pool
    fill!(row_len, 0)
    fill!(col_len, 0)
    @inbounds for s in 0:nslots-1
        i = slot_row[s+1]
        j = slot_col[s+1]
        (row_active[i+1] == 0 || col_active[j+1] == 0) && continue
        pool[row_start[i+1]+row_len[i+1]+1] = s
        row_len[i+1] += 1
        pool[col_start[j+1]+col_len[j+1]+1] = s
        col_len[j+1] += 1
    end
    return r
end

"""`val` onto row (or column) `idx`'s list, moving the list to the end of the
pool with twice the room when it is full."""
function _slu_push!(r::_SluRF, row::Bool, idx::Int, val::Int)
    start = row ? r.row_start : r.col_start
    len = row ? r.row_len : r.col_len
    cap = row ? r.row_cap : r.col_cap
    @inbounds begin
        ln = len[idx+1]
        if ln == cap[idx+1]
            grown = 2 * cap[idx+1] + 2
            top = r.pool_top
            _slu_room!(r.pool, top + grown)
            pool = r.pool
            s0 = start[idx+1]
            for k in 0:ln-1
                pool[top+k+1] = pool[s0+k+1]
            end
            start[idx+1] = top
            cap[idx+1] = grown
            r.pool_top = top + grown
        end
        r.pool[start[idx+1]+ln+1] = val
        len[idx+1] = ln + 1
    end
    return nothing
end

"""A fill slot at (i, j) (`_newSlot`): the caller has made room in V and the slot arrays."""
function _slu_new_slot!(r::_SluRF, i::Int, j::Int)::Int
    s = r.nslots
    r.nslots = s + 1
    @inbounds begin
        r.V[s+1] = 0.0
        r.slot_row[s+1] = i
        r.slot_col[s+1] = j
    end
    _slu_push!(r, true, i, s)
    _slu_push!(r, false, j, s)
    @inbounds begin
        r.rc[i+1] += 1
        r.cc[j+1] += 1
    end
    return s
end

"""Chooses the pivots of steps s0.. from V as the kept steps before s0 left it,
eliminating as it goes (`choose`); false when no acceptable pivot remains, a
value is not finite, or the work passes `limit`."""
function _slu_rf_choose!(r::_SluRF, s0::Int)::Bool
    n = r.n
    pr = r.pr
    pc = r.pc
    pslot = r.pslot
    lstart = r.lstart
    ustart = r.ustart
    tstart = r.tstart
    fill_start = r.fill_start
    row_active = r.row_active
    col_active = r.col_active
    rc = r.rc
    cc = r.cc
    head = r.head
    nxt = r.nxt
    prv = r.prv
    at = r.at
    at_stamp = r.at_stamp
    row_start = r.row_start
    row_len = r.row_len
    col_start = r.col_start
    col_len = r.col_len
    has_fixed = r.has_columns
    columns = r.columns
    limit = r.limit
    # The pattern and the fill of the kept steps stay; the rest goes.
    r.nslots = s0 > 0 ? fill_start[s0+1] : r.nbase
    fill!(row_active, 0x01)
    fill!(col_active, 0x01)
    @inbounds for s in 0:s0-1
        row_active[pr[s+1]+1] = 0
        col_active[pc[s+1]+1] = 0
    end
    _slu_lists_from_slots!(r)
    @inbounds for i in 0:n-1
        rc[i+1] = row_len[i+1]
        cc[i+1] = col_len[i+1]
    end
    fill!(head, -1)
    @inbounds for j in 0:n-1
        col_active[j+1] != 0 && _slu_bucket_in!(head, nxt, prv, cc, j)
    end
    fill!(at_stamp, 0)
    stamp = 0
    lp = lstart[s0+1]
    up = ustart[s0+1]
    tp = tstart[s0+1]
    @inbounds for s in s0:n-1
        head[1] >= 0 && return false                 # a column with nothing left in it
        V = r.V
        slot_row = r.slot_row
        slot_col = r.slot_col
        pool = r.pool
        # The search: the SEARCH_COLUMNS sparsest columns with a candidate, or
        # the one column the fixed order names.
        best = Inf
        best_ratio = 0.0
        bslot = -1
        examined = 0
        fixed = has_fixed ? columns[s+1] : -1
        cmax = fixed >= 0 ? 1 : n - s
        c = 1
        while c <= cmax && examined < _SLU_SEARCH_COLUMNS && best > 0
            j = fixed >= 0 ? fixed : head[c+1]
            while j >= 0 && examined < _SLU_SEARCH_COLUMNS && best > 0
                # Scanned once for the largest, dropping the rows eliminated since.
                st = col_start[j+1]
                ln = col_len[j+1]
                m = 0.0
                keep = 0
                for k in 0:ln-1
                    sl = pool[st+k+1]
                    row_active[slot_row[sl+1]+1] == 0 && continue
                    pool[st+keep+1] = sl
                    keep += 1
                    v = abs(V[sl+1])
                    !(v < Inf) && return false       # NaN or infinite
                    if v > m
                        m = v
                    end
                end
                if keep < ln
                    col_len[j+1] = keep
                end
                if m > 0
                    examined += 1
                    thr = _SLU_PIVOT_THRESHOLD * m
                    cj = fixed >= 0 ? 1 : c - 1
                    for k in 0:keep-1
                        sl = pool[st+k+1]
                        v = abs(V[sl+1])
                        v < thr && continue
                        cost = (rc[slot_row[sl+1]+1] - 1) * cj
                        ratio = v / m
                        if cost < best || (cost == best && ratio > best_ratio)
                            best = Float64(cost)
                            best_ratio = ratio
                            bslot = sl
                        end
                    end
                end
                j = fixed >= 0 ? -1 : nxt[j+1]
            end
            c += 1
        end
        bslot < 0 && return false
        p = slot_row[bslot+1]
        q = slot_col[bslot+1]
        pr[s+1] = p
        pc[s+1] = q
        pslot[s+1] = bslot
        fill_start[s+1] = r.nslots
        row_active[p+1] = 0
        col_active[q+1] = 0
        _slu_bucket_out!(head, nxt, prv, cc, q)
        # Its column below and its row to the right, among what is active.
        lst = col_start[q+1]
        lln = col_len[q+1]
        ust = row_start[p+1]
        uln = row_len[p+1]
        _slu_room!(r.lslot, lp + lln)
        _slu_room!(r.lrow, lp + lln)
        _slu_room!(r.uslot, up + uln)
        _slu_room!(r.ucol, up + uln)
        lslot = r.lslot
        lrow = r.lrow
        uslot = r.uslot
        ucol = r.ucol
        lstart[s+1] = lp
        ustart[s+1] = up
        tstart[s+1] = tp
        for k in 0:lln-1
            sl = pool[lst+k+1]
            i = slot_row[sl+1]
            if row_active[i+1] != 0
                lslot[lp+1] = sl
                lrow[lp+1] = i
                lp += 1
            end
        end
        for k in 0:uln-1
            sl = pool[ust+k+1]
            j = slot_col[sl+1]
            if col_active[j+1] != 0
                uslot[up+1] = sl
                ucol[up+1] = j
                up += 1
            end
        end
        l0 = lstart[s+1]
        u0 = ustart[s+1]
        most = (lp - l0) * (up - u0)
        _slu_room!(r.T, tp + most)
        _slu_room!(r.V, r.nslots + most)
        _slu_room!(r.slot_row, r.nslots + most)
        _slu_room!(r.slot_col, r.nslots + most)
        T = r.T
        V = r.V
        slot_col = r.slot_col
        for u in u0:up-1
            _slu_bucket_out!(head, nxt, prv, cc, ucol[u+1])
        end
        piv = V[bslot+1]
        for k in l0:lp-1
            i = lrow[k+1]
            f = V[lslot[k+1]+1] / piv
            V[lslot[k+1]+1] = f
            # Where row i already has an entry, by column.
            stamp += 1
            pool = r.pool
            st = row_start[i+1]
            ln = row_len[i+1]
            keep = 0
            for rr in 0:ln-1
                sl = pool[st+rr+1]
                j = slot_col[sl+1]
                col_active[j+1] == 0 && continue
                pool[st+keep+1] = sl
                keep += 1
                at[j+1] = sl
                at_stamp[j+1] = stamp
            end
            if keep < ln
                row_len[i+1] = keep
            end
            for u in u0:up-1
                j = ucol[u+1]
                # Fill is structure whatever its value now: a later matrix may
                # put a number there.
                t = at_stamp[j+1] == stamp ? at[j+1] : _slu_new_slot!(r, i, j)
                T[tp+1] = t
                tp += 1
                if f != 0
                    V[t+1] -= f * V[uslot[u+1]+1]
                end
            end
        end
        for k in l0:lp-1
            rc[lrow[k+1]+1] -= 1
        end
        for u in u0:up-1
            j = ucol[u+1]
            cc[j+1] -= 1
            _slu_bucket_in!(head, nxt, prv, cc, j)
        end
        tp > limit && return false
    end
    lstart[n+1] = lp
    ustart[n+1] = up
    tstart[n+1] = tp
    fill_start[n+1] = r.nslots
    r.ops = tp
    r.nnz = r.nslots
    return true
end

"""Factorises Mass - a*J; false when it cannot be done with pivots that pass the test (`factor`)."""
function _slu_rf_factor!(r::_SluRF, a::Float64, values::Vector{Float64}, mass::Vector{Float64},
                         has_mass::Bool)::Bool
    r.valid || (r.nslots = r.nbase)
    if !_slu_rf_load!(r, a, values, mass, has_mass)
        r.valid = false
        return false
    end
    from = 0
    if r.valid
        from = _slu_rf_refactor!(r)
        if from < 0
            _slu_rf_pack!(r)
            return true
        end
    end
    r.repivots += 1
    if !_slu_rf_choose!(r, from)
        r.valid = false
        return false
    end
    if from == 0
        r.full_ops = r.ops
    elseif r.ops > _SLU_REORDER_GROWTH * r.full_ops
        _slu_rf_load!(r, a, values, mass, has_mass)
        if !_slu_rf_choose!(r, 0)
            r.valid = false
            return false
        end
        r.full_ops = r.ops
    end
    r.valid = true
    _slu_rf_order!(r)
    _slu_rf_pack!(r)
    return true
end

"""Against the latest factorisation, into `out` (`solve`)."""
function _slu_rf_solve!(r::_SluRF, b::Vector{Float64}, out::Vector{Float64})
    n = r.n
    pr = r.pr
    pc = r.pc
    lstart = r.lstart
    ustart = r.ustart
    lval = r.lval
    lstep = r.lstep
    uval = r.uval
    ustep = r.ustep
    dval = r.dval
    z = r.z
    @inbounds begin
        for s in 0:n-1
            z[s+1] = b[pr[s+1]+1]
        end
        for s in 0:n-1
            zs = z[s+1]
            zs == 0 && continue
            for k in lstart[s+1]:lstart[s+2]-1
                z[lstep[k+1]+1] -= lval[k+1] * zs
            end
        end
        for s in n-1:-1:0
            t = z[s+1]
            for u in ustart[s+1]:ustart[s+2]-1
                t -= uval[u+1] * z[ustep[u+1]+1]
            end
            z[s+1] = t / dval[s+1]
        end
        for s in 0:n-1
            out[pc[s+1]+1] = z[s+1]
        end
    end
    return out
end

# --- a block at a time (`BlockLU`) -----------------------------------------------------------------

"""The block LU: the blocks and their states, the entries between blocks, a
kept-pivot LU for each block of more than one state (`lu_of`, -1 for one of
one state) and where J holds its entries, and the factor laid out by step in
the order the solve takes the blocks."""
mutable struct _SluBK
    n::Int
    nblocks::Int
    start::Vector{Int}
    member::Vector{Int}
    off_ptr::Vector{Int}
    off_row::Vector{Int}
    off_pos::Vector{Int}
    diag_pos::Vector{Int}
    lu_of::Vector{Int}
    lus::Vector{_SluRF}
    pos_ptr::Vector{Int}
    pos::Vector{Int}
    b_values::Vector{Float64}
    b_mass::Vector{Float64}
    base::Vector{Int}
    row_of_step::Vector{Int}
    col_of_step::Vector{Int}
    step_of_row::Vector{Int}
    seg_start::Vector{Int}
    seg_block::Vector{Int}
    Lp::Vector{Int}
    Up::Vector{Int}
    Li::Vector{Int}
    Lx::Vector{Float64}
    Ui::Vector{Int}
    Ux::Vector{Float64}
    D::Vector{Float64}
    off_p::Vector{Int}
    off_step::Vector{Int}
    off_at::Vector{Int}
    off_x::Vector{Float64}
    zs::Vector{Float64}
    laid_out::Int
    valid::Bool
    ops::Int
    limit::Float64
    nnz::Int
end

function _slu_bk_new(n::Int, colptr::Vector{Int}, rowidx::Vector{Int}, nblocks::Int, block::Vector{Int})
    start = zeros(Int, nblocks + 1)
    @inbounds for i in 0:n-1
        start[block[i+1]+2] += 1
    end
    @inbounds for b in 0:nblocks-1
        start[b+2] += start[b+1]
    end
    member = zeros(Int, n)
    local_ = zeros(Int, n)
    filled = start[1:nblocks]
    @inbounds for i in 0:n-1
        b = block[i+1]
        local_[i+1] = filled[b+1] - start[b+1]
        member[filled[b+1]+1] = i
        filled[b+1] += 1
    end
    # The entries between blocks, by column: their rows, and where J holds them.
    off_ptr = zeros(Int, n + 1)
    @inbounds for j in 0:n-1
        c = 0
        for p in colptr[j+1]:colptr[j+2]-1
            block[rowidx[p+1]+1] != block[j+1] && (c += 1)
        end
        off_ptr[j+2] = off_ptr[j+1] + c
    end
    noff = off_ptr[n+1]
    off_row = zeros(Int, noff)
    off_pos = zeros(Int, noff)
    e = 0
    @inbounds for j in 0:n-1, p in colptr[j+1]:colptr[j+2]-1
        block[rowidx[p+1]+1] == block[j+1] && continue
        off_row[e+1] = rowidx[p+1]
        off_pos[e+1] = p
        e += 1
    end
    # A block of one state: where J holds its diagonal (-1: nowhere). A larger
    # one: its pattern in its own numbering, where J holds each of its entries,
    # and its LU.
    diag_pos = fill(-1, nblocks)
    lu_of = fill(-1, nblocks)
    nlus = 0
    total = 0
    @inbounds for b in 0:nblocks-1
        s0 = start[b+1]
        bsize = start[b+2] - s0
        if bsize == 1
            i = member[s0+1]
            for p in colptr[i+1]:colptr[i+2]-1
                rowidx[p+1] == i && (diag_pos[b+1] = p)
            end
            continue
        end
        for lc in 0:bsize-1
            j = member[s0+lc+1]
            for p in colptr[j+1]:colptr[j+2]-1
                block[rowidx[p+1]+1] == b && (total += 1)
            end
        end
        nlus += 1
    end
    lus = _SluRF[]
    pos_ptr = zeros(Int, nlus + 1)
    pos = zeros(Int, total)
    most = 0
    most_entries = 0
    li = 0
    k = 0
    @inbounds for b in 0:nblocks-1
        s0 = start[b+1]
        bsize = start[b+2] - s0
        bsize == 1 && continue
        cp = zeros(Int, bsize + 1)
        cnt = 0
        for lc in 0:bsize-1
            j = member[s0+lc+1]
            for p in colptr[j+1]:colptr[j+2]-1
                block[rowidx[p+1]+1] == b && (cnt += 1)
            end
            cp[lc+2] = cnt
        end
        ri = zeros(Int, cnt)
        pos_ptr[li+1] = k
        kk = 0
        for lc in 0:bsize-1
            j = member[s0+lc+1]
            for p in colptr[j+1]:colptr[j+2]-1
                block[rowidx[p+1]+1] != b && continue
                ri[kk+1] = local_[rowidx[p+1]+1]
                pos[k+1] = p
                kk += 1
                k += 1
            end
        end
        push!(lus, _slu_rf_new(bsize, cp, ri, Int[], false))
        lu_of[b+1] = li
        li += 1
        bsize > most && (most = bsize)
        cnt > most_entries && (most_entries = cnt)
    end
    pos_ptr[nlus+1] = k
    # The steps in the order the solve takes them, the last block first, in
    # segments: one block of more than one state, or a run of blocks of one
    # state each.
    base = zeros(Int, nblocks)
    row_of_step = zeros(Int, n)
    col_of_step = zeros(Int, n)
    step_of_row = zeros(Int, n)
    seg_start = zeros(Int, nblocks + 1)
    seg_block = zeros(Int, nblocks)
    nseg = 0
    g = 0
    @inbounds for b in nblocks-1:-1:0
        bsize = start[b+2] - start[b+1]
        base[b+1] = g
        if bsize == 1
            i = member[start[b+1]+1]
            row_of_step[g+1] = i
            col_of_step[g+1] = i
            step_of_row[i+1] = g
            if nseg > 0 && seg_block[nseg] < 0
                seg_start[nseg+1] = g + 1
            else
                seg_block[nseg+1] = -1
                nseg += 1
                seg_start[nseg+1] = g + 1
            end
        else
            seg_block[nseg+1] = b
            nseg += 1
            seg_start[nseg+1] = g + bsize
        end
        g += bsize
    end
    return _SluBK(n, nblocks, start, member, off_ptr, off_row, off_pos, diag_pos, lu_of, lus, pos_ptr, pos,
                  zeros(most_entries), zeros(most), base, row_of_step, col_of_step, step_of_row,
                  seg_start[1:nseg+1], seg_block[1:nseg], zeros(Int, n + 1), zeros(Int, n + 1), Int[], Float64[],
                  Int[], Float64[], zeros(n), zeros(Int, n + 1), zeros(Int, noff), zeros(Int, noff), zeros(noff),
                  zeros(n), -1, false, 0, Inf, 0)
end

"""Times a block's pivots were chosen again, over every block."""
function _slu_bk_repivots(bk::_SluBK)::Int
    r = 0
    for lu in bk.lus
        r += lu.repivots
    end
    return r
end

"""The larger blocks' steps, L's and U's entries by step, and the entries
between blocks by the steps of their column and their row (`_layout`)."""
function _slu_bk_layout!(bk::_SluBK)
    n = bk.n
    start = bk.start
    member = bk.member
    base = bk.base
    lu_of = bk.lu_of
    lus = bk.lus
    row_of_step = bk.row_of_step
    col_of_step = bk.col_of_step
    step_of_row = bk.step_of_row
    Lp = bk.Lp
    Up = bk.Up
    nl = 0
    nu = 0
    for lu in lus
        nl += lu.lstart[lu.n+1]
        nu += lu.ustart[lu.n+1]
    end
    if length(bk.Li) < nl
        bk.Li = zeros(Int, nl)
        bk.Lx = zeros(nl)
    end
    if length(bk.Ui) < nu
        bk.Ui = zeros(Int, nu)
        bk.Ux = zeros(nu)
    end
    Li = bk.Li
    Ui = bk.Ui
    lq = 0
    uq = 0
    @inbounds for k in bk.nblocks-1:-1:0
        s0 = start[k+1]
        m = start[k+2] - s0
        g0 = base[k+1]
        li = lu_of[k+1]
        if li < 0
            Lp[g0+1] = lq
            Up[g0+1] = uq
            continue
        end
        lu = lus[li+1]
        pr = lu.pr
        pc = lu.pc
        lstart = lu.lstart
        lstep = lu.lstep
        ustart = lu.ustart
        ustep = lu.ustep
        for s in 0:m-1
            i = member[s0+pr[s+1]+1]
            row_of_step[g0+s+1] = i
            col_of_step[g0+s+1] = member[s0+pc[s+1]+1]
            step_of_row[i+1] = g0 + s
            Lp[g0+s+1] = lq
            for q in lstart[s+1]:lstart[s+2]-1
                Li[lq+1] = g0 + lstep[q+1]
                lq += 1
            end
            Up[g0+s+1] = uq
            for u in ustart[s+1]:ustart[s+2]-1
                Ui[uq+1] = g0 + ustep[u+1]
                uq += 1
            end
        end
    end
    Lp[n+1] = lq
    Up[n+1] = uq
    off_ptr = bk.off_ptr
    off_row = bk.off_row
    off_pos = bk.off_pos
    off_p = bk.off_p
    off_step = bk.off_step
    off_at = bk.off_at
    e = 0
    @inbounds for g in 0:n-1
        off_p[g+1] = e
        j = col_of_step[g+1]
        for f in off_ptr[j+1]:off_ptr[j+2]-1
            off_step[e+1] = step_of_row[off_row[f+1]+1]
            off_at[e+1] = off_pos[f+1]
            e += 1
        end
    end
    off_p[n+1] = e
    return bk
end

"""The factor's values in that layout, after every factorisation, and the
entries between blocks from J; false where one is not a number (`_values`)."""
function _slu_bk_values!(bk::_SluBK, a::Float64, values::Vector{Float64})::Bool
    start = bk.start
    base = bk.base
    lu_of = bk.lu_of
    lus = bk.lus
    Lx = bk.Lx
    Ux = bk.Ux
    D = bk.D
    lq = 0
    uq = 0
    @inbounds for k in bk.nblocks-1:-1:0
        li = lu_of[k+1]
        li < 0 && continue
        lu = lus[li+1]
        m = start[k+2] - start[k+1]
        g0 = base[k+1]
        lval = lu.lval
        uval = lu.uval
        dval = lu.dval
        nl = lu.lstart[m+1]
        nu = lu.ustart[m+1]
        for q in 0:nl-1
            Lx[lq+1] = lval[q+1]
            lq += 1
        end
        for u in 0:nu-1
            Ux[uq+1] = uval[u+1]
            uq += 1
        end
        for s in 0:m-1
            D[g0+s+1] = dval[s+1]
        end
    end
    off_x = bk.off_x
    off_at = bk.off_at
    @inbounds for e in 0:length(off_x)-1
        v = -a * values[off_at[e+1]+1]
        isfinite(v) || return false
        off_x[e+1] = v
    end
    return true
end

"""Factorises Mass - a*J a block at a time (`factor`); false when a block
cannot be done with pivots that pass the test, or a value is not a number."""
function _slu_bk_factor!(bk::_SluBK, a::Float64, values::Vector{Float64}, mass::Vector{Float64},
                         has_mass::Bool)::Bool
    start = bk.start
    member = bk.member
    base = bk.base
    D = bk.D
    lu_of = bk.lu_of
    diag_pos = bk.diag_pos
    pos_ptr = bk.pos_ptr
    pos = bk.pos
    b_values = bk.b_values
    b_mass = bk.b_mass
    lus = bk.lus
    limit = bk.limit
    bk.valid = false
    ops = 0
    nnz = length(bk.off_x)
    @inbounds for b in 0:bk.nblocks-1
        s0 = start[b+1]
        li = lu_of[b+1]
        if li < 0
            i = member[s0+1]
            p = diag_pos[b+1]
            d = (p >= 0 ? -a * values[p+1] : 0.0) + (has_mass ? mass[i+1] : 1.0)
            (!(abs(d) > 0) || !isfinite(d)) && return false
            D[base[b+1]+1] = d
            nnz += 1
            continue
        end
        bsize = start[b+2] - s0
        p0 = pos_ptr[li+1]
        for k in 0:pos_ptr[li+2]-p0-1
            b_values[k+1] = values[pos[p0+k+1]+1]
        end
        if has_mass
            for lc in 0:bsize-1
                b_mass[lc+1] = mass[member[s0+lc+1]+1]
            end
        end
        lu = lus[li+1]
        lu.limit = limit == Inf ? Inf : limit - ops
        ok = _slu_rf_factor!(lu, a, b_values, b_mass, has_mass)
        lu.limit = Inf
        ok || return false
        ops += lu.ops
        nnz += lu.nnz
        ops > limit && return false
    end
    bk.ops = ops
    bk.nnz = nnz
    chosen = _slu_bk_repivots(bk)
    if chosen != bk.laid_out
        _slu_bk_layout!(bk)
        bk.laid_out = chosen
    end
    _slu_bk_values!(bk, a, values) || return false
    bk.valid = true
    return true
end

"""Against the latest factorisation, the blocks from the last to the first,
each one's entries between blocks taken off the right-hand side as soon as its
unknown is known (`solve`)."""
function _slu_bk_solve!(bk::_SluBK, b::Vector{Float64}, out::Vector{Float64})
    n = bk.n
    row_of_step = bk.row_of_step
    col_of_step = bk.col_of_step
    Lp = bk.Lp
    Li = bk.Li
    Lx = bk.Lx
    Up = bk.Up
    Ui = bk.Ui
    Ux = bk.Ux
    D = bk.D
    off_p = bk.off_p
    off_step = bk.off_step
    off_x = bk.off_x
    zs = bk.zs
    seg_start = bk.seg_start
    seg_block = bk.seg_block
    @inbounds begin
        for g in 0:n-1
            zs[g+1] = b[row_of_step[g+1]+1]
        end
        for r in 0:length(seg_block)-1
            g0 = seg_start[r+1]
            g1 = seg_start[r+2]
            if seg_block[r+1] < 0
                for g in g0:g1-1
                    xg = zs[g+1] / D[g+1]
                    zs[g+1] = xg
                    out[col_of_step[g+1]+1] = xg
                    xg == 0 && continue
                    for e in off_p[g+1]:off_p[g+2]-1
                        zs[off_step[e+1]+1] -= off_x[e+1] * xg
                    end
                end
                continue
            end
            for g in g0:g1-1
                zg = zs[g+1]
                zg == 0 && continue
                for q in Lp[g+1]:Lp[g+2]-1
                    zs[Li[q+1]+1] -= Lx[q+1] * zg
                end
            end
            for g in g1-1:-1:g0
                t = zs[g+1]
                for u in Up[g+1]:Up[g+2]-1
                    t -= Ux[u+1] * zs[Ui[u+1]+1]
                end
                xg = t / D[g+1]
                zs[g+1] = xg
                out[col_of_step[g+1]+1] = xg
                xg == 0 && continue
                for e in off_p[g+1]:off_p[g+2]-1
                    zs[off_step[e+1]+1] -= off_x[e+1] * xg
                end
            end
        end
    end
    return out
end

# --- the iteration matrix (`iterationMatrix`) -------------------------------------------------------

"""A sparse iteration matrix as `iterationMatrix` makes it: J's pattern, the
structure of Mass - a*J in CSC (`makeMiterBuilder`), the Gilbert-Peierls LU and
its column order, the kept-pivot LU (whole, or a block at a time), the dense
LU a declined matrix goes to where the factor fills in, and `info`."""
mutable struct SparseLUMatrix
    n::Int
    kind::Int
    colptr::Vector{Int}
    rowidx::Vector{Int}
    masked::Vector{Float64}
    mass::Vector{Float64}
    has_mass::Bool
    mp::Vector{Int}
    mi::Vector{Int}
    mx::Vector{Float64}
    jtom::Vector{Int}
    diag_pos::Vector{Int}
    gp::_SluGP
    q::Vector{Int}
    has_q::Bool
    whole::_SluRF
    blocks::_SluBK
    fills_in::Bool
    current::Int
    dense::Matrix{Float64}
    dpiv::Vector{Int}
    fill::Int
    repivots::Int
    fallbacks::Int
    trial_repivots::Int
    ordering::Int
    fail_column::Int
    fail_value::Float64
    fail_nonfinite::Bool
end

"""A kept-pivot LU tried on the start's matrix, stopping once its work passes
`most`: (whether it was made, it)."""
function _slu_trial(n::Int, colptr::Vector{Int}, rowidx::Vector{Int}, values::Vector{Float64},
                    mass::Vector{Float64}, has_mass::Bool, columns::Vector{Int}, has_columns::Bool, most::Float64)
    lu = _slu_rf_new(n, colptr, rowidx, columns, has_columns)
    most < 0 && return false, lu
    lu.limit = most
    ok = _slu_rf_factor!(lu, 1e-3, values, mass, has_mass)
    lu.limit = Inf
    return ok, lu
end

"""The sparse iteration matrix `iterationMatrix` makes in `mode` (`_SLU_AUTO`,
`_SLU_REFACTOR`, `_SLU_SPARSE_MODE`) from J's pattern (`colptr`, `rowidx`,
counted from zero) and its values at the start -- or, its kind `_SLU_DENSE`,
the word that `auto` would factorise it densely. One real factorisation of
each candidate decides: reverse Cuthill-McKee's column order or the model's
own, by fill; the kept-pivot LU a block at a time, whole by threshold
Markowitz, or whole in that column order, where it costs no more than the
alternative; the dense LU where the searching factor fills in; the
Gilbert-Peierls LU otherwise."""
function SparseLUMatrix(n::Int, colptr::Vector{Int}, rowidx::Vector{Int}, values::Vector{Float64},
                        mass::Vector{Float64}, has_mass::Bool, mode::Int, dense_fill::Float64, too_big::Bool,
                        blocks::Bool)
    mp, mi, jtom, diag = _slu_miter_structure(n, colptr, rowidx)
    mx = zeros(length(mi))
    gp = _SluGP(n)
    empty = Int[]
    whole = _slu_rf_new(0, [0], empty, empty, false)
    blocked = _slu_bk_new(0, [0], empty, 0, empty)
    # Reverse Cuthill-McKee first, and the model's own order stopped as soon
    # as it fills in past that.
    _slu_miter_update!(mx, 1e-3, values, mass, has_mass, jtom, diag)
    rcm = _slu_rcm_order(n, mp, mi)
    _slu_gp_factorize!(gp, mp, mi, mx, rcm, true, Inf)
    rcm_fill = gp.singular ? Inf : Float64(gp.lnz + gp.unz)
    _slu_gp_factorize!(gp, mp, mi, mx, rcm, false, rcm_fill)
    best = (gp.singular || gp.over) ? Inf : Float64(gp.lnz + gp.unz)
    has_q = false
    if rcm_fill < best
        best = rcm_fill
        has_q = true
    end
    # Both singular says nothing about the fill: sparse, in the order that
    # suits these graphs, and the formations say whether it is singular.
    if best == Inf
        best = Float64(mp[n+1])
        has_q = true
    end
    fill_ = Int(best)
    ordering = has_q ? _SLU_RCM : _SLU_NATURAL
    fills_in = !too_big && best > dense_fill * n * n
    trial_repivots = 0
    kind = _SLU_SPARSE
    if mode == _SLU_REFACTOR || mode == _SLU_AUTO
        _slu_gp_factorize!(gp, mp, mi, mx, rcm, has_q, Inf)
        alternative = fills_in ? 0.25 * n * n * n / 3 : Float64(gp.flops)
        limit = mode == _SLU_REFACTOR ? Inf : min(_SLU_OPS_BUDGET, alternative)
        # A block at a time first, where the matrix falls into more than one
        # block: a whole trial is then kept only where it costs less.
        by_blocks = false
        if blocks
            nb, block = _slu_block_triangular(n, colptr, rowidx)
            if nb > 1
                bk = _slu_bk_new(n, colptr, rowidx, nb, block)
                bk.limit = limit
                ok = _slu_bk_factor!(bk, 1e-3, values, mass, has_mass)
                bk.limit = Inf
                if ok
                    blocked = bk
                    by_blocks = true
                    limit = min(limit, Float64(bk.ops - 1))
                end
            end
        end
        m_ok, by_m = _slu_trial(n, colptr, rowidx, values, mass, has_mass, empty, false, limit)
        cols = has_q ? rcm : collect(0:n-1)
        c_ok, by_c = _slu_trial(n, colptr, rowidx, values, mass, has_mass, cols, true,
                                m_ok ? min(limit, Float64(by_m.ops)) : limit)
        chosen = 0                      # 0 none, 1 by Markowitz, 2 in the column order
        if c_ok && (!m_ok || by_c.ops < by_m.ops)
            whole = by_c
            chosen = 2
        elseif m_ok
            whole = by_m
            chosen = 1
        end
        if by_blocks && (chosen == 0 || blocked.ops <= whole.ops)
            kind = _SLU_BLOCKS
            ordering = _SLU_BLOCKED
            fill_ = blocked.valid ? blocked.nnz : -1
            trial_repivots = _slu_bk_repivots(blocked)
        elseif chosen != 0
            kind = _SLU_WHOLE
            ordering = chosen == 2 ? (has_q ? _SLU_RCM_COLUMNS : _SLU_NATURAL_COLUMNS) : _SLU_MARKOWITZ
            fill_ = whole.valid ? whole.nnz : -1
            trial_repivots = whole.repivots
        elseif mode == _SLU_REFACTOR
            whole = _slu_rf_new(n, colptr, rowidx, empty, false)
            kind = _SLU_WHOLE
            ordering = _SLU_MARKOWITZ
            fill_ = -1
        end
    end
    if kind == _SLU_SPARSE && mode == _SLU_AUTO && fills_in
        kind = _SLU_DENSE
    end
    current = if kind == _SLU_SPARSE
        _SLU_BY_SPARSE
    elseif (kind == _SLU_WHOLE && whole.valid) || (kind == _SLU_BLOCKS && blocked.valid)
        _SLU_KEPT
    else
        _SLU_NONE_MADE
    end
    return SparseLUMatrix(n, kind, colptr, rowidx, zeros(colptr[n+1]), mass, has_mass, mp, mi, mx, jtom, diag,
                          gp, rcm, has_q, whole, blocked, fills_in, current, zeros(1, 1), zeros(Int, 1), fill_, 0, 0,
                          trial_repivots, ordering, -1, 0.0, false)
end

"""By the Gilbert-Peierls LU in the chosen order (`sparseForm`)."""
function _slu_sw_sparse!(sw::SparseLUMatrix, a::Float64, values::Vector{Float64})::Int
    _slu_miter_update!(sw.mx, a, values, sw.mass, sw.has_mass, sw.jtom, sw.diag_pos)
    g = sw.gp
    _slu_gp_factorize!(g, sw.mp, sw.mi, sw.mx, sw.q, sw.has_q, Inf)
    if g.singular
        sw.fail_column = g.fail_original
        sw.fail_value = g.nonfinite ? Inf : 0.0
        sw.fail_nonfinite = g.nonfinite
        return g.nonfinite ? _SLU_NONFINITE : _SLU_SINGULAR
    end
    return _SLU_OK
end

"""By the dense LU of linalg.js (`formAndFactor`), where a matrix the
kept-pivot LU declined goes when the searching factor fills in."""
function _slu_sw_dense!(sw::SparseLUMatrix, a::Float64, values::Vector{Float64})::Int
    n = sw.n
    if size(sw.dense, 1) != n
        sw.dense = zeros(n, n)
        sw.dpiv = zeros(Int, n)
    end
    lu = sw.dense
    piv = sw.dpiv
    colptr = sw.colptr
    rowidx = sw.rowidx
    fill!(lu, 0.0)
    bad = -1
    bad_value = 0.0
    @inbounds for j in 0:n-1, p in colptr[j+1]:colptr[j+2]-1
        v = -a * values[p+1]
        if bad < 0 && !isfinite(v)
            bad = j
            bad_value = v
        end
        lu[rowidx[p+1]+1, j+1] = v
    end
    if bad >= 0
        sw.fail_column = bad
        sw.fail_value = bad_value
        sw.fail_nonfinite = true
        return _SLU_NONFINITE
    end
    mass = sw.mass
    @inbounds for i in 0:n-1
        lu[i+1, i+1] += sw.has_mass ? mass[i+1] : 1.0
    end
    @inbounds for i in 0:n-1
        piv[i+1] = i
    end
    @inbounds for k in 0:n-1
        p = k
        max_abs = abs(lu[k+1, k+1])
        for i in k+1:n-1
            v = abs(lu[i+1, k+1])
            if v > max_abs
                max_abs = v
                p = i
            end
        end
        if !(max_abs > 0) || !isfinite(max_abs)
            sw.fail_column = k
            sw.fail_value = max_abs
            sw.fail_nonfinite = max_abs != 0
            return max_abs != 0 ? _SLU_NONFINITE : _SLU_SINGULAR
        end
        if p != k
            for j in 0:n-1
                tmp = lu[p+1, j+1]
                lu[p+1, j+1] = lu[k+1, j+1]
                lu[k+1, j+1] = tmp
            end
            t = piv[p+1]
            piv[p+1] = piv[k+1]
            piv[k+1] = t
        end
        pivot = lu[k+1, k+1]
        for i in k+1:n-1
            f = lu[i+1, k+1] / pivot
            f == 0 && continue
            lu[i+1, k+1] = f
            for j in k+1:n-1
                lu[i+1, j+1] -= f * lu[k+1, j+1]
            end
        end
    end
    return _SLU_OK
end

"""Factorises Mass - a*J, the rows `held` marks (where `any_held`) as rows of
the identity: `_SLU_OK`, `_SLU_SINGULAR` or `_SLU_NONFINITE`, with the column
(and the value) in `fail_column` and `fail_value`. A matrix the kept-pivot LU
declines goes to the LU that would otherwise have been used, whose answer is
final."""
function _slu_form!(sw::SparseLUMatrix, a::Float64, values::Vector{Float64}, held::Union{Nothing,Vector{UInt8}})::Int
    use = values
    if held !== nothing
        use = sw.masked
        colptr = sw.colptr
        rowidx = sw.rowidx
        copyto!(use, values)
        @inbounds for j in 0:sw.n-1, p in colptr[j+1]:colptr[j+2]-1
            held[rowidx[p+1]+1] != 0 && (use[p+1] = 0.0)
        end
    end
    kind = sw.kind
    if kind == _SLU_SPARSE
        st = _slu_sw_sparse!(sw, a, use)
        sw.current = st == _SLU_OK ? _SLU_BY_SPARSE : _SLU_NONE_MADE
        return st
    end
    if kind == _SLU_WHOLE
        lu = sw.whole
        ok = _slu_rf_factor!(lu, a, use, sw.mass, sw.has_mass)
        nnz = lu.nnz
        repivots = lu.repivots
    else
        bk = sw.blocks
        ok = _slu_bk_factor!(bk, a, use, sw.mass, sw.has_mass)
        nnz = bk.nnz
        repivots = _slu_bk_repivots(bk)
    end
    st = _SLU_OK
    if ok
        sw.current = _SLU_KEPT
        sw.fill = nnz
    else
        sw.fallbacks += 1
        if sw.fills_in
            st = _slu_sw_dense!(sw, a, use)
            by = _SLU_BY_DENSE
        else
            st = _slu_sw_sparse!(sw, a, use)
            by = _SLU_BY_SPARSE
        end
        sw.current = st == _SLU_OK ? by : _SLU_NONE_MADE
    end
    if st == _SLU_OK
        sw.repivots = repivots - sw.trial_repivots
    end
    return st
end

"""Against the latest formation, into `out` (distinct from `b`): NaN after one
that failed, which the solvers stop at -- the application's answer there is
whatever a half-made factor gives."""
function _slu_solve!(sw::SparseLUMatrix, b::Vector{Float64}, out::Vector{Float64})
    current = sw.current
    if current == _SLU_NONE_MADE
        fill!(out, NaN)
    elseif current == _SLU_BY_SPARSE
        _slu_gp_solve!(sw.gp, b, out)
    elseif current == _SLU_BY_DENSE
        lu = sw.dense
        piv = sw.dpiv
        n = sw.n
        @inbounds begin
            for i in 0:n-1
                out[i+1] = b[piv[i+1]+1]
            end
            for i in 1:n-1
                s = out[i+1]
                for j in 0:i-1
                    s -= lu[i+1, j+1] * out[j+1]
                end
                out[i+1] = s
            end
            for i in n-1:-1:0
                s = out[i+1]
                for j in i+1:n-1
                    s -= lu[i+1, j+1] * out[j+1]
                end
                out[i+1] = s / lu[i+1, i+1]
            end
        end
    elseif sw.kind == _SLU_WHOLE
        _slu_rf_solve!(sw.whole, b, out)
    else
        _slu_bk_solve!(sw.blocks, b, out)
    end
    return out
end

"""Which LU, as `info["lu"]` names it."""
_slu_lu_name(sw::SparseLUMatrix) = sw.kind in (_SLU_WHOLE, _SLU_BLOCKS) ? "refactor" :
                                   (sw.kind == _SLU_SPARSE ? "sparse" : "dense")
