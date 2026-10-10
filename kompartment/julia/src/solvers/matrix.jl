# The iteration matrix Mass - a*J: formed, factorised, solved with
# (engine/solvers/matrix.py).
#
# A dense matrix is factorised by the application's own dense LU (kernels.jl)
# up to APP_LU_MAX states -- the application's arithmetic, bit for bit -- and
# by LAPACK beyond that; a sparse one by KLU (klu.jl), where the Python
# engine uses SuperLU. (UMFPACK, tried in its place through SparseArrays, was
# 2.5 times slower on landscape-like systems of 2,000 and 20,000 states, and
# allocates afresh at every refactorisation.)
# Which one follows the application's rule: dense for small systems or where
# the sparse factor fills in past a share of n^2, sparse otherwise -- decided
# on real factorisations of the first matrix, never on the clock.

const _MAT_DENSE_MAX_BYTES = 2 * 1024^3
const _MAT_APP_LU_MAX = 200
const _MAT_DENSE_BELOW = 64
const _MAT_DENSE_FILL = 0.15
const _MAT_NATURAL_MARGIN = 1.5
#: The column orderings tried, the model's own first (ORDERINGS).
const _MAT_ORDERINGS = (("NATURAL", _KLU_ORDER_NATURAL), ("AMD", _KLU_ORDER_AMD), ("COLAMD", _KLU_ORDER_COLAMD))

const _MAT_NONE = 0
const _MAT_KERNEL = 1
const _MAT_LAPACK = 2
const _MAT_KLU = 3

"""What the matrix refuses to be made or factorised with (Python's RuntimeError)."""
struct MatrixError <: Exception
    msg::String
end
Base.showerror(io::IO, e::MatrixError) = print(io, e.msg)

_matrix_name(mass::Union{Nothing,Vector{Float64}}) = mass !== nothing ? "M - h*J" : "I - h*J"

function _singular_message(mass::Union{Nothing,Vector{Float64}}, column::Int, hint::Union{Nothing,String})::String
    if mass !== nothing && mass[column+1] == 0
        return "The iteration matrix M - h*J is singular at the algebraic variable in column $column: its " *
               "constraint does not determine it. Check that the constraint depends on its own variable, that no " *
               "two constraints say the same thing, and that the system is index 1."
    end
    base = "The iteration matrix $(_matrix_name(mass)) is singular at column $column"
    return hint !== nothing && !isempty(hint) ? "$base. $hint" : base
end

_non_finite_message(mass::Union{Nothing,Vector{Float64}}, column::Int, value::Float64)::String =
    "The iteration matrix $(_matrix_name(mass)) has an entry that is not a number ($(_pyrepr(value))) at column " *
    "$column: the Jacobian has a non-finite entry there."

"""`_mat_form!(W, a, J, held)` factorises Mass - a*J with the rows `held`
marks as rows of the identity; `_mat_solve!(W, x, b)` answers for the
latest one.

`J` is the pattern's values when there is a pattern, and the dense Jacobian
by columns (`J[i + (j-1)*n]`) otherwise."""
mutable struct IterationMatrix
    n::Int
    pattern::Union{Nothing,Pattern}
    mass::Union{Nothing,Vector{Float64}}
    hints::Dict{String,String}
    info::Dict{String,Any}
    sparse::Bool
    kernels::Bool
    lu::Int
    # the application's LU
    lut::Matrix{Float64}
    piv::Vector{Int}
    fail::Vector{Float64}
    no_held::Vector{UInt8}
    mass_diag::Vector{Float64}
    work::Vector{Float64}
    # LAPACK's
    wd::Matrix{Float64}
    ipiv::Vector{LinearAlgebra.BlasInt}
    # the union structure of the pattern and the diagonal, 0-based
    u_colptr::Vector{Int64}
    u_rowval::Vector{Int64}
    u_nzval::Vector{Float64}
    u_pattern::Vector{Int}
    u_diag::Vector{Int}
    u_diag_add::Vector{Float64}
    masked::Vector{Float64}
    klu::Union{Nothing,_KLU}
    permc::String
end

function IterationMatrix(n::Int, pattern::Union{Nothing,Pattern}, J0::Vector{Float64}, mode::String="auto",
                         mass::Union{Nothing,Vector{Float64}}=nothing,
                         hints::Union{Nothing,Dict{String,String}}=nothing;
                         dense_below::Int=_MAT_DENSE_BELOW, dense_fill::Float64=_MAT_DENSE_FILL)
    hints = hints === nothing ? Dict{String,String}() : hints
    info = Dict{String,Any}("sparse" => false, "lu" => "dense", "fill" => nothing, "ordering" => "natural",
                            "nnz" => pattern !== nothing ? pattern_nnz(pattern) : n * n, "repivots" => 0,
                            "fallbacks" => 0)
    too_big = n * n * 8 > _MAT_DENSE_MAX_BYTES
    kernels = n <= _MAT_APP_LU_MAX
    W = IterationMatrix(n, pattern, mass, hints, info, false, kernels, _MAT_NONE,
                        kernels ? zeros(n, n) : zeros(0, 0), zeros(Int, n), zeros(2), zeros(UInt8, n),
                        mass === nothing ? ones(n) : copy(mass), zeros(n),
                        zeros(0, 0), LinearAlgebra.BlasInt[], Int64[], Int64[], Float64[], Int[], Int[], Float64[],
                        Float64[], nothing, "COLAMD")
    if pattern === nothing
        if too_big
            gb = @sprintf("%.1f", n * n * 8 / 1073741824)
            throw(MatrixError("This model has $n states, and without a sparsity pattern the solver would have to " *
                              "hold the iteration matrix as $n by $n numbers -- $gb GB. " * get(hints, "noPattern", "")))
        end
        W.sparse = false
        return W
    end
    _union_structure!(W, pattern)
    if mode == "dense" && !too_big
        W.sparse = false
        return W
    end
    if mode == "auto" && n < dense_below && !too_big
        W.sparse = false
        return W
    end
    W.sparse = true
    W.permc = "COLAMD"
    if !too_big
        # Which column ordering, and whether to be sparse at all, decided on
        # real factorisations of the first matrix: the fill of the factors.
        # The model's own order is kept unless another fills in far less.
        _sparse_values!(W, 1e-3, J0)
        fills = Dict{String,Int}()
        names = map(first, _MAT_ORDERINGS)
        for name in names
            f = _trial_fill(W, name)
            f === nothing || (fills[name] = f)
        end
        if !isempty(fills)
            least = minimum(Base.values(fills))
            if haskey(fills, "NATURAL") && fills["NATURAL"] <= _MAT_NATURAL_MARGIN * least
                W.permc = "NATURAL"
            else
                best = ""
                for name in names
                    haskey(fills, name) || continue
                    if best == "" || fills[name] < fills[best]
                        best = name
                    end
                end
                W.permc = best
            end
            info["fill"] = fills[W.permc]
            if mode == "auto" && fills[W.permc] > dense_fill * n * n
                W.sparse = false
            end
        end
    end
    if W.sparse
        info["sparse"] = true
        info["lu"] = "KLU"
        info["ordering"] = W.permc
    end
    return W
end

_klu_ordering(name::String) = name == "NATURAL" ? _KLU_ORDER_NATURAL : name == "AMD" ? _KLU_ORDER_AMD : _KLU_ORDER_COLAMD

"""The fill of a trial factorisation of the values in `u_nzval` in one
ordering, or nothing when it fails."""
function _trial_fill(W::IterationMatrix, name::String)::Union{Nothing,Int}
    k = _KLU(W.u_colptr, W.u_rowval, _klu_ordering(name))
    fill = (_klu_analyze!(k) && _klu_factor!(k, W.u_nzval)) ? _klu_fill(k) : nothing
    _klu_free!(k)
    return fill
end

"""The structure of Mass - a*J -- the pattern and the diagonal, in
compressed columns -- worked out once, with where each of the pattern's
entries and each diagonal entry sits in it."""
function _union_structure!(W::IterationMatrix, p::Pattern)
    n = W.n
    colptr = Vector{Int64}(undef, n + 1)
    rowval = Int64[]
    sizehint!(rowval, pattern_nnz(p) + n)
    u_pattern = Vector{Int}(undef, pattern_nnz(p))
    u_diag = Vector{Int}(undef, n)
    colptr[1] = 0
    @inbounds for j in 1:n
        placed = false
        for q in p.colptr[j]:p.colptr[j+1]-1
            r = p.rowval[q]
            if !placed && r >= j
                push!(rowval, j - 1)
                u_diag[j] = length(rowval)
                placed = true
                if r == j
                    u_pattern[q] = length(rowval)
                    continue
                end
            end
            push!(rowval, r - 1)
            u_pattern[q] = length(rowval)
        end
        if !placed
            push!(rowval, j - 1)
            u_diag[j] = length(rowval)
        end
        colptr[j+1] = length(rowval)
    end
    W.u_colptr = colptr
    W.u_rowval = rowval
    W.u_nzval = zeros(length(rowval))
    W.u_pattern = u_pattern
    W.u_diag = u_diag
    W.u_diag_add = W.mass === nothing ? ones(n) : copy(W.mass)
    W.masked = zeros(pattern_nnz(p))
    return W
end

"""The values of -a*J scattered into the union and the diagonal added to
them (`_sparse_matrix`): the same two roundings as forming -a*J and adding
diag(Mass) to it."""
function _sparse_values!(W::IterationMatrix, a::Float64, J::Vector{Float64})
    data = W.u_nzval
    fill!(data, 0.0)
    pos = W.u_pattern
    @inbounds for q in eachindex(pos)
        data[pos[q]] = -a * J[q]
    end
    dpos = W.u_diag
    add = W.u_diag_add
    @inbounds for i in eachindex(dpos)
        data[dpos[i]] += add[i]
    end
    return data
end

"""Mass - a*J factorised; nothing, or the message of why not."""
function _mat_form!(W::IterationMatrix, a::Float64, J::Vector{Float64},
               held::Union{Nothing,Vector{UInt8}}=nothing)::Union{Nothing,String}
    n = W.n
    mass = W.mass
    if W.kernels && !W.sparse
        h = held === nothing ? W.no_held : held
        status = W.pattern === nothing ?
                 _app_form_factor_dense!(a, J, h, W.mass_diag, W.lut, W.piv, W.fail) :
                 _app_form_factor_pattern!(a, W.pattern.colptr, W.pattern.rowval, J, h, W.mass_diag, W.lut, W.piv,
                                           W.fail)
        if status != 0
            col = Int(W.fail[1])
            value = W.fail[2]
            if status == -_LU_NONFINITE || status == _LU_NONFINITE
                return _non_finite_message(mass, col, value)
            end
            return _singular_message(mass, col, get(W.hints, "singular", nothing))
        end
        W.lu = _MAT_KERNEL
        return nothing
    end
    if W.pattern === nothing
        if size(W.wd, 1) != n
            W.wd = zeros(n, n)
            W.ipiv = zeros(LinearAlgebra.BlasInt, n)
        end
        Wd = W.wd
        @inbounds for q in 1:n*n
            Wd[q] = -a * J[q]
        end
        if held !== nothing
            @inbounds for i in 1:n
                held[i] != 0 || continue
                for j in 1:n
                    Wd[i, j] = 0.0
                end
            end
        end
    else
        p = W.pattern
        rows = p.rowval
        if W.sparse
            # The held rows masked, every value checked (the first that is
            # not a number reported), -a*J scattered into the union and the
            # diagonal added: one pass.
            data = W.u_nzval
            fill!(data, 0.0)
            pos = W.u_pattern
            @inbounds for q in eachindex(pos)
                v = (held !== nothing && held[rows[q]] != 0) ? 0.0 : J[q]
                isfinite(v) || return _non_finite_message(mass, p.col_of[q] - 1, v)
                data[pos[q]] = -a * v
            end
            dpos = W.u_diag
            add = W.u_diag_add
            @inbounds for i in eachindex(dpos)
                data[dpos[i]] += add[i]
            end
            ok = _sparse_factor!(W)
            if !ok
                return _singular_message(mass, _singular_column(W), get(W.hints, "singular", nothing))
            end
            return nothing
        end
        vals = W.masked
        @inbounds for q in eachindex(vals)
            vals[q] = (held !== nothing && held[rows[q]] != 0) ? 0.0 : J[q]
        end
        @inbounds for q in eachindex(vals)
            if !isfinite(vals[q])
                return _non_finite_message(mass, p.col_of[q] - 1, vals[q])
            end
        end
        if size(W.wd, 1) != n
            W.wd = zeros(n, n)
            W.ipiv = zeros(LinearAlgebra.BlasInt, n)
        end
        Wd = W.wd
        fill!(Wd, 0.0)
        cols = p.col_of
        @inbounds for q in eachindex(vals)
            Wd[rows[q], cols[q]] = -a * vals[q]
        end
    end
    Wd = W.wd
    md = W.mass_diag
    @inbounds for i in 1:n
        Wd[i, i] += md[i]
    end
    if !all(isfinite, Wd)
        # The first entry that is not a number, in Python's (row-major) order.
        @inbounds for i in 1:n, j in 1:n
            if !isfinite(Wd[i, j])
                return _non_finite_message(mass, j - 1, Wd[i, j])
            end
        end
    end
    _, _, info = LinearAlgebra.LAPACK.getrf!(Wd, W.ipiv; check=false)
    if info > 0
        return _singular_message(mass, Int(info) - 1, get(W.hints, "singular", nothing))
    end
    @inbounds for i in 1:n
        if Wd[i, i] == 0
            return _singular_message(mass, i - 1, get(W.hints, "singular", nothing))
        end
    end
    W.lu = _MAT_LAPACK
    return nothing
end

"""The sparse factorisation of the values in `u_nzval`; false: singular."""
function _sparse_factor!(W::IterationMatrix)::Bool
    k = W.klu
    if k === nothing || k.ordering != _klu_ordering(W.permc)
        k === nothing || _klu_free!(k)
        k = _KLU(W.u_colptr, W.u_rowval, _klu_ordering(W.permc))
        W.klu = k
    end
    if k.symbolic == C_NULL && !_klu_analyze!(k)
        return false
    end
    W.lu = _MAT_KLU
    return _klu_form!(k, W.u_nzval)
end

"""Where a singular sparse matrix has its first zero pivot, as LAPACK finds
it on the matrix made dense (only for the message; 0 when that cannot be)."""
function _singular_column(W::IterationMatrix)::Int
    n = W.n
    try
        n * n * 8 > _MAT_DENSE_MAX_BYTES && return 0
        D = zeros(n, n)
        @inbounds for j in 1:n, q in W.u_colptr[j]+1:W.u_colptr[j+1]
            D[W.u_rowval[q]+1, j] = W.u_nzval[q]
        end
        LinearAlgebra.LAPACK.getrf!(D, zeros(LinearAlgebra.BlasInt, n); check=false)
        for i in 1:n
            abs(D[i, i]) == 0 && return i - 1
        end
        return 0
    catch
        return 0
    end
end

"""`x = W \\ b` for the latest factorisation (`x`, `b` distinct)."""
function _mat_solve!(W::IterationMatrix, x::Vector{Float64}, b::Vector{Float64})
    lu = W.lu
    if lu == _MAT_KERNEL
        return _app_solve!(x, W.lut, W.piv, b)
    elseif lu == _MAT_KLU
        copyto!(x, b)
        return _klu_solve!(W.klu::_KLU, x)
    else
        copyto!(x, b)
        LinearAlgebra.LAPACK.getrs!('N', W.wd, W.ipiv, x)
        return x
    end
end

"""`x = W \\ x` for the latest factorisation."""
function _mat_solve_inplace!(W::IterationMatrix, x::Vector{Float64})
    lu = W.lu
    if lu == _MAT_KERNEL
        b = W.work
        copyto!(b, x)
        return _app_solve!(x, W.lut, W.piv, b)
    elseif lu == _MAT_KLU
        return _klu_solve!(W.klu::_KLU, x)
    else
        LinearAlgebra.LAPACK.getrs!('N', W.wd, W.ipiv, x)
        return x
    end
end

"""Releases the sparse factorisation now rather than at collection."""
function _mat_release!(W::IterationMatrix)
    W.klu === nothing || _klu_free!(W.klu)
    return nothing
end
