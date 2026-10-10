# KLU (SuiteSparse), through its 64-bit-integer interface: the sparse LU of
# the iteration matrix, where the Python engine uses SuperLU.
#
# The structure is analysed once; the first factorisation pivots, and every
# later one refactorises with the same pivots (`klu_l_refactor`) unless the
# pivots have gone bad, judged as SUNDIALS judges them: a crude reciprocal
# condition number below eps^(2/3), confirmed by the estimate of the
# condition number above its inverse. A refactorisation that fails, or that
# fails the test, is followed by a fresh factorisation -- a rule of the
# numbers alone, never of the clock.

"""`klu_l_common` (klu.h, KLU 2.x)."""
mutable struct _KLUCommon
    tol::Cdouble
    memgrow::Cdouble
    initmem_amd::Cdouble
    initmem::Cdouble
    maxwork::Cdouble
    btf::Cint
    ordering::Cint
    scale::Cint
    user_order::Ptr{Cvoid}
    user_data::Ptr{Cvoid}
    halt_if_singular::Cint
    status::Cint
    nrealloc::Cint
    structural_rank::Int64
    numerical_rank::Int64
    singular_col::Int64
    noffdiag::Int64
    flops::Cdouble
    rcond::Cdouble
    condest::Cdouble
    rgrowth::Cdouble
    work::Cdouble
    memusage::Csize_t
    mempeak::Csize_t
    _KLUCommon() = new()
end

const _KLU_OK = Cint(0)
const _KLU_SINGULAR = Cint(1)
const _KLU_ORDER_NATURAL = -1
const _KLU_ORDER_AMD = 0
const _KLU_ORDER_COLAMD = 1
const _KLU_RCOND_FLOOR = cpow(2.0^-52, 2.0 / 3.0)

function _klu_common()::_KLUCommon
    c = _KLUCommon()
    ok = ccall((:klu_l_defaults, libklu), Cint, (Ref{_KLUCommon},), c)
    ok == 1 || error("klu_l_defaults failed")
    # The layout check: the defaults klu.h documents.
    (c.tol == 0.001 && c.btf == 1 && c.ordering == 0 && c.scale == 2 && c.halt_if_singular == 1) ||
        error("klu_l_common does not have the layout this port expects")
    return c
end

"""A KLU factorisation of one structure (0-based compressed columns)."""
mutable struct _KLU
    common::_KLUCommon
    colptr::Vector{Int64}
    rowval::Vector{Int64}
    symbolic::Ptr{Cvoid}
    numeric::Ptr{Cvoid}
    ordering::Int
    nfactor::Int
    nrefactor::Int
    function _KLU(colptr::Vector{Int64}, rowval::Vector{Int64}, ordering::Int)
        k = new(_klu_common(), colptr, rowval, C_NULL, C_NULL, ordering, 0, 0)
        finalizer(_klu_free!, k)
        return k
    end
end

function _klu_free_numeric!(k::_KLU)
    if k.numeric != C_NULL
        ref = Ref{Ptr{Cvoid}}(k.numeric)
        ccall((:klu_l_free_numeric, libklu), Cint, (Ref{Ptr{Cvoid}}, Ref{_KLUCommon}), ref, k.common)
        k.numeric = C_NULL
    end
    return nothing
end

function _klu_free!(k::_KLU)
    _klu_free_numeric!(k)
    if k.symbolic != C_NULL
        ref = Ref{Ptr{Cvoid}}(k.symbolic)
        ccall((:klu_l_free_symbolic, libklu), Cint, (Ref{Ptr{Cvoid}}, Ref{_KLUCommon}), ref, k.common)
        k.symbolic = C_NULL
    end
    return nothing
end

"""Analyses the structure in the given ordering; false when KLU refuses."""
function _klu_analyze!(k::_KLU)::Bool
    n = Int64(length(k.colptr) - 1)
    c = k.common
    if k.ordering == _KLU_ORDER_NATURAL
        k.symbolic = ccall((:klu_l_analyze_given, libklu), Ptr{Cvoid},
                           (Int64, Ptr{Int64}, Ptr{Int64}, Ptr{Int64}, Ptr{Int64}, Ref{_KLUCommon}),
                           n, k.colptr, k.rowval, C_NULL, C_NULL, c)
    else
        c.ordering = Cint(k.ordering)
        k.symbolic = ccall((:klu_l_analyze, libklu), Ptr{Cvoid},
                           (Int64, Ptr{Int64}, Ptr{Int64}, Ref{_KLUCommon}), n, k.colptr, k.rowval, c)
    end
    return k.symbolic != C_NULL
end

"""A fresh factorisation of `values`; false when the matrix is singular (or
KLU fails otherwise)."""
function _klu_factor!(k::_KLU, values::Vector{Float64})::Bool
    _klu_free_numeric!(k)
    k.numeric = ccall((:klu_l_factor, libklu), Ptr{Cvoid},
                      (Ptr{Int64}, Ptr{Int64}, Ptr{Float64}, Ptr{Cvoid}, Ref{_KLUCommon}),
                      k.colptr, k.rowval, values, k.symbolic, k.common)
    k.nfactor += 1
    return k.numeric != C_NULL && k.common.status == _KLU_OK
end

"""The values factorised: refactorised with the pivots kept where they
still serve, freshly otherwise. False: singular."""
function _klu_form!(k::_KLU, values::Vector{Float64})::Bool
    if k.numeric == C_NULL
        return _klu_factor!(k, values)
    end
    ok = ccall((:klu_l_refactor, libklu), Cint,
               (Ptr{Int64}, Ptr{Int64}, Ptr{Float64}, Ptr{Cvoid}, Ptr{Cvoid}, Ref{_KLUCommon}),
               k.colptr, k.rowval, values, k.symbolic, k.numeric, k.common)
    k.nrefactor += 1
    if ok == 1 && k.common.status == _KLU_OK
        ccall((:klu_l_rcond, libklu), Cint, (Ptr{Cvoid}, Ptr{Cvoid}, Ref{_KLUCommon}),
              k.symbolic, k.numeric, k.common)
        rc = k.common.rcond
        if rc >= _KLU_RCOND_FLOOR
            return true
        end
        if !isnan(rc)
            ccall((:klu_l_condest, libklu), Cint,
                  (Ptr{Int64}, Ptr{Float64}, Ptr{Cvoid}, Ptr{Cvoid}, Ref{_KLUCommon}),
                  k.colptr, values, k.symbolic, k.numeric, k.common)
            if k.common.condest <= 1 / _KLU_RCOND_FLOOR
                return true
            end
        end
    end
    return _klu_factor!(k, values)
end

"""`x = W \\ x`, in place."""
function _klu_solve!(k::_KLU, x::Vector{Float64})
    ccall((:klu_l_solve, libklu), Cint, (Ptr{Cvoid}, Ptr{Cvoid}, Int64, Int64, Ptr{Float64}, Ref{_KLUCommon}),
          k.symbolic, k.numeric, Int64(length(x)), Int64(1), x, k.common)
    return x
end

"""The entries the factors hold: those of L and U, diagonals included, and
those of the off-diagonal blocks of the block-triangular form."""
function _klu_fill(k::_KLU)::Int
    k.numeric == C_NULL && return 0
    p = Ptr{Int64}(k.numeric)
    lnz = unsafe_load(p, 3)
    unz = unsafe_load(p, 4)
    # klu_l_numeric: n, nblocks, lnz, unz, max_lnz_block, max_unz_block,
    # Pnum, Pinv, Lip, Uip, Llen, Ulen, LUbx, LUsize, Udiag, Rs, worksize,
    # Work, Xwork, Iwork, Offp, Offi, Offx, nzoff: the 24th 8-byte word.
    nzoff = unsafe_load(p, 24)
    return Int(lnz + unz + nzoff)
end
