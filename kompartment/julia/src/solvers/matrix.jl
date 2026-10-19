# The iteration matrix Mass - a*J: formed, factorised, solved with
# (engine/solvers/matrix.py).
#
# A sparse matrix is factorised by the application's own sparse LUs
# (sparselu.jl), chosen as it chooses them -- the application's choice, fill
# and factors, to the bit, as the Python engine has them. (They were quicker
# than KLU in the default mode too, on every example and made-up model tried.)
# A dense one is factorised by the application's dense LU (kernels.jl) up to
# APP_LU_MAX states -- its arithmetic, bit for bit, or with parity off Julia's
# own -- and by LAPACK beyond. Which one follows the application's rule: dense
# for small systems or where the sparse factor fills in past a share of n^2,
# sparse otherwise -- decided on real factorisations of the first matrix,
# never on the clock.

const _MAT_DENSE_MAX_BYTES = 2 * 1024^3
const _MAT_APP_LU_MAX = 200
const _MAT_DENSE_BELOW = 24
const _MAT_DENSE_FILL = 0.15

const _MAT_NONE = 0
const _MAT_KERNEL = 1
const _MAT_LAPACK = 2
const _MAT_FAST = 4            # Julia's own dense LU (kernels.jl), where parity is off

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

"""The matrix Newton iterates with: `IterationMatrix`, or one a caller makes for a system of a known block form
(`iteration_matrix` in `ndf`), with `_mat_form!`, `_mat_solve_inplace!`, `_mat_release!` and `_mat_info`."""
abstract type AbstractIterationMatrix end

"""`_mat_form!(W, a, J, held)` factorises Mass - a*J with the rows `held`
marks as rows of the identity; `_mat_solve!(W, x, b)` answers for the
latest one.

`J` is the pattern's values when there is a pattern, and the dense Jacobian
by columns (`J[i + (j-1)*n]`) otherwise."""
mutable struct IterationMatrix <: AbstractIterationMatrix
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
    masked::Vector{Float64}
    # the application's sparse LUs (sparselu.jl)
    sw::Union{Nothing,SparseLUMatrix}
end

"""The application's mode code for a sparse LU (sparselu.jl): what is not
`auto` or `refactor` is the searching LU, as in the Python engine."""
_slu_mode(mode::String) = mode == "auto" ? _SLU_AUTO : mode == "refactor" ? _SLU_REFACTOR : _SLU_SPARSE_MODE

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
                        zeros(0, 0), LinearAlgebra.BlasInt[], Float64[], nothing)
    if pattern === nothing
        if too_big
            gb = @sprintf("%.1f", n * n * 8 / 1073741824)
            throw(MatrixError("This model has $n states, and without a sparsity pattern the solver would have to " *
                              "hold the iteration matrix as $n by $n numbers -- $gb GB. " * get(hints, "noPattern", "")))
        end
        W.sparse = false
        return W
    end
    W.masked = zeros(pattern_nnz(pattern))
    if mode == "dense" && !too_big
        W.sparse = false
        return W
    end
    if mode == "auto" && n < dense_below && !too_big
        W.sparse = false
        return W
    end
    sw = SparseLUMatrix(n, pattern.colptr .- 1, pattern.rowval .- 1, J0, mass === nothing ? ones(n) : copy(mass),
                        mass !== nothing, _slu_mode(mode), dense_fill, too_big, true)
    info["fill"] = sw.fill < 0 ? nothing : sw.fill
    info["ordering"] = _SLU_ORDERINGS[sw.ordering+1]
    if sw.kind == _SLU_DENSE
        W.sparse = false
        return W
    end
    W.sw = sw
    W.sparse = true
    info["sparse"] = true
    info["lu"] = _slu_lu_name(sw)
    return W
end

"""Mass - a*J factorised; nothing, or the message of why not."""
function _mat_form!(W::IterationMatrix, a::Float64, J::Vector{Float64},
               held::Union{Nothing,Vector{UInt8}}=nothing)::Union{Nothing,String}
    n = W.n
    mass = W.mass
    sw = W.sw
    if sw !== nothing
        st = _slu_form!(sw, a, J, held)
        st == _SLU_OK && return nothing
        st == _SLU_NONFINITE && return _non_finite_message(mass, sw.fail_column, sw.fail_value)
        return _singular_message(mass, sw.fail_column, get(W.hints, "singular", nothing))
    end
    if W.kernels && !W.sparse
        h = held === nothing ? W.no_held : held
        exact = parity()
        status = if exact
            W.pattern === nothing ?
                _app_form_factor_dense!(a, J, h, W.mass_diag, W.lut, W.piv, W.fail) :
                _app_form_factor_pattern!(a, W.pattern.colptr, W.pattern.rowval, J, h, W.mass_diag, W.lut, W.piv,
                                          W.fail)
        else
            formed = W.pattern === nothing ? _fast_form_dense!(W.lut, a, J, h, W.mass_diag, W.fail) :
                     _fast_form_pattern!(W.lut, a, W.pattern.colptr, W.pattern.rowval, J, h, W.mass_diag, W.fail)
            formed != 0 ? formed : _fast_factor!(W.lut, W.piv, W.fail)
        end
        if status != 0
            col = Int(W.fail[1])
            value = W.fail[2]
            if status == -_LU_NONFINITE || status == _LU_NONFINITE
                return _non_finite_message(mass, col, value)
            end
            return _singular_message(mass, col, get(W.hints, "singular", nothing))
        end
        W.lu = exact ? _MAT_KERNEL : _MAT_FAST
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

"""`x = W \\ b` for the latest factorisation (`x`, `b` distinct)."""
function _mat_solve!(W::IterationMatrix, x::Vector{Float64}, b::Vector{Float64})
    W.sw === nothing || return _slu_solve!(W.sw, b, x)
    lu = W.lu
    if lu == _MAT_FAST
        copyto!(x, b)
        return _fast_solve!(x, W.lut, W.piv)
    elseif lu == _MAT_KERNEL
        return _app_solve!(x, W.lut, W.piv, b)
    else
        copyto!(x, b)
        LinearAlgebra.LAPACK.getrs!('N', W.wd, W.ipiv, x)
        return x
    end
end

"""`x = W \\ x` for the latest factorisation."""
function _mat_solve_inplace!(W::IterationMatrix, x::Vector{Float64})
    if W.sw !== nothing
        b = W.work
        copyto!(b, x)
        return _slu_solve!(W.sw, b, x)
    end
    lu = W.lu
    if lu == _MAT_FAST
        return _fast_solve!(x, W.lut, W.piv)
    elseif lu == _MAT_KERNEL
        b = W.work
        copyto!(b, x)
        return _app_solve!(x, W.lut, W.piv, b)
    else
        LinearAlgebra.LAPACK.getrs!('N', W.wd, W.ipiv, x)
        return x
    end
end

"""Nothing to release: every factorisation is Julia's own memory."""
_mat_release!(::IterationMatrix) = nothing

"""Which LU, and how full its factor is: `sparse`, `fill`, `lu`."""
function _mat_info(W::IterationMatrix)
    sw = W.sw
    if sw !== nothing
        W.info["fill"] = sw.fill < 0 ? nothing : sw.fill
        W.info["repivots"] = sw.repivots
        W.info["fallbacks"] = sw.fallbacks
    end
    return W.info
end
