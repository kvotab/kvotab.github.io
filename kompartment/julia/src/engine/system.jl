# A built model, ready to run: the derivative, the algebraic values and the hooks
# (what `buildSystem` returns in the application).
#
# The equations are compiled into passes -- the slots that never change (worked
# out once), those that change with the clock alone (once per instant), those
# that read the state (on every call) -- and the derivative is assembled as
#
#     dy/dt = A(X) [y; 1]
#
# one product of a sparse matrix with the state and a one: the linear terms'
# coefficients in the columns of the states they read, every other term in the
# last column. A has one entry per term, in the order the application adds the
# terms to each state, duplicates kept, and the product sums each row's terms
# in that order -- each product rounded on its own, never fused -- so the
# derivative is the application's to the last bit.

"""
The derivative's matrix with its terms merged, where the engine need not sum
them in the application's order (parity off): one entry per state and column
read, `vals`, worked out from its sources -- the slots it reads, with their
signs, `src_*`; the constant terms' sum, `konst`; the products of two slots and
the far-field paths' values, added from the terms' own values, `extra_*` -- and
the constant column per row, `b`, from the affine terms. A call is then one
product over these entries, a third of the terms on a large assessment.
"""
mutable struct MergedMatrix
    rowptr::Vector{Int32}
    cols::Vector{Int32}
    vals::Vector{Float64}
    src_ptr::Vector{Int32}       # per entry: its sources' range in src_slot and src_sign
    src_slot::Vector{Int32}
    src_sign::Vector{Float64}
    konst::Vector{Float64}
    extra_pos::Vector{Int32}     # a product or far-field term: its place among the terms
    extra_dest::Vector{Int32}    # and its entry
    fast::Vector{Int32}          # the entries with a source that moves with the state
    extra_fast::Vector{Int32}    # the extra terms of those
    aff_rows::Vector{Int32}      # the rows with affine terms, and those terms' places
    aff_ptr::Vector{Int32}
    aff_pos::Vector{Int32}
    aff_src::Vector{Int32}       # linear sources that land in the constant column: their places among
                                 # lin_xsign (written into the terms with the affine ones)
    b::Vector{Float64}
    row_chunks::Vector{UnitRange{Int}}
    gather_chunks::Vector{UnitRange{Int}}
end

"""Where the derivative's terms come from, and how each row is summed."""
mutable struct Assembler
    n::Int
    # The matrix's indices, and the largest of its sources', as 32-bit integers: on a large
    # assessment, half the memory in them to stream through on every call.
    rowptr::Vector{Int32}        # CSR over n rows, 1-based
    cols::Vector{Int32}          # 1-based; n+1 is the column of the constant one
    data::Vector{Float64}
    # The linear coefficients' sources, rebuilt when the slots they read can have moved: those
    # that read a slot moving with the state from `lin_fast_from` on (on every call, in a
    # model that has them), the others before it (when the clock or the invariants move).
    lin_xsign_pos::Vector{Int32}; lin_xsign_slot::Vector{Int32}; lin_xsign_sign::Vector{Float64}
    lin_fast_from::Int
    lin_xx_pos::Vector{Int}; lin_xx_a::Vector{Int}; lin_xx_b::Vector{Int}; lin_xx_sign::Vector{Float64}
    # The constant coefficients: written once.
    lin_const_pos::Vector{Int}; lin_const_val::Vector{Float64}
    consts_written::Bool
    lin_farf::Vector{Tuple{Int,Vector{Int}}}          # (path, positions)
    # The affine terms, written on every call.
    aff_xsign_pos::Vector{Int}; aff_xsign_slot::Vector{Int}; aff_xsign_sign::Vector{Float64}
    aff_x_pos::Vector{Int}; aff_x_slot::Vector{Int}
    aff_fail_pos::Vector{Int}; aff_fail_h::Vector{Int}; aff_fail_p::Vector{Int}; aff_fail_r::Vector{Int}
    aff_mean_pos::Vector{Int}; aff_mean_slot::Vector{Int}; aff_mean_mem::Vector{Int}
    moves::Int                    # 0 constant, 1 with the clock, 2 with the state
    key_version::Int
    key_clock::Float64
    keyed::Bool
    empty::Bool
    # Shared out between threads, a large matrix: its rows in chunks of about
    # equal entries, and its linear coefficients in equal chunks (the slow ones and
    # those that move with the state apart). Empty: on one.
    row_chunks::Vector{UnitRange{Int}}
    lin_chunks::Vector{UnitRange{Int}}
    lin_fast_chunks::Vector{UnitRange{Int}}
    # Parity off: the terms merged, and the product taken over the merged entries.
    merged::Union{Nothing,MergedMatrix}
end

#: The entries from which a derivative's matrix is shared out between threads. Waking the
#: threads costs tens of microseconds a call: measured on made-up chains, a matrix of 110,000
#: entries solved a fifth slower on eight threads than on one, one of 300,000 broke even, and
#: a large assessment's gained a tenth.
const THREADED_ENTRIES = 250_000

"""`k` ranges over `1:n` of about equal size."""
_even_chunks(n::Int, k::Int) = UnitRange{Int}[(1+div((j-1)*n, k)):div(j*n, k) for j in 1:k if div(j*n, k) >= 1+div((j-1)*n, k)]

#: The fewest coefficients shared out between threads: fewer are written on one.
const THREADED_COEFFICIENTS = 25_000

"""`r` in `k` ranges of about equal size, or none for a range too short to share."""
_range_chunks(r::UnitRange{Int}, k::Int) =
    length(r) < THREADED_COEFFICIENTS ? UnitRange{Int}[] : UnitRange{Int}[(first(r)-1) .+ c for c in _even_chunks(length(r), k)]

"""The rows in `k` ranges of about equal entries."""
function _row_chunks(rowptr::AbstractVector{<:Integer}, n::Int, k::Int)
    m = rowptr[end] - 1
    out = UnitRange{Int}[]
    lo = 1
    for j in 1:k
        target = 1 + div(j * m, k)
        hi = j == k ? n : clamp(searchsortedlast(rowptr, target) - 1, lo - 1, n)
        hi >= lo && push!(out, lo:hi)
        lo = hi + 1
    end
    return out
end

"""
    set_threads!(A::Assembler, threads)

Shares the derivative's matrix out between `threads` threads (1: none). The
sums are the same, row by row and term by term, so the derivative is the
same to the bit however many there are.
"""
function set_threads!(A::Assembler, threads::Integer)
    k = Int(threads)
    if k <= 1 || length(A.data) < THREADED_ENTRIES
        A.row_chunks = UnitRange{Int}[]
        A.lin_chunks = UnitRange{Int}[]
        A.lin_fast_chunks = UnitRange{Int}[]
        if A.merged !== nothing
            A.merged.row_chunks = UnitRange{Int}[]
            A.merged.gather_chunks = UnitRange{Int}[]
        end
        return A
    end
    A.row_chunks = _row_chunks(A.rowptr, A.n, k)
    A.lin_chunks = _range_chunks(1:A.lin_fast_from-1, k)
    A.lin_fast_chunks = _range_chunks(A.lin_fast_from:length(A.lin_xsign_pos), k)
    M = A.merged
    if M !== nothing
        if length(M.vals) >= THREADED_ENTRIES
            M.row_chunks = _row_chunks(M.rowptr, A.n, k)
            M.gather_chunks = _range_chunks(1:length(M.vals), k)
        else
            M.row_chunks = UnitRange{Int}[]
            M.gather_chunks = UnitRange{Int}[]
        end
    end
    return A
end

"""One step of a run's history that a system's recorders keep, and what started it."""
mutable struct System
    project::Project
    builder::Builder
    nstate::Int
    nalg::Int
    nparam::Int
    P::Vector{Float64}
    X::Vector{Float64}
    data::ModelData
    start_time::Float64
    end_time::Float64
    once::PassFunction
    clock::PassFunction
    step::PassFunction
    step_d::PassFunction
    initial::PassFunction
    source::Vector{Any}
    assembler::Assembler
    invariant_version::Int
    slot_class::Vector{UInt8}
    clock_idx::Vector{Int}        # 1-based
    lo_x::Vector{Float64}
    hi_x::Vector{Float64}
    min_change::Float64
    origin::Float64
    lo_t::Float64
    hi_t::Float64
    clock_at::Float64
    jumps::Vector{JumpSpec}
    remembering::Vector{Entry}
    recorders::Vector{Entry}
    laplace::Vector{Any}
    event_slots::Vector{Int}      # 1-based slots of the trigger functions
    event_direction::Vector{Int8}
    event_handlers::Dict{Int,Vector{NamedTuple{(:rec, :off, :action),Tuple{Entry,Int,Symbol}}}}
    jacobian::Any
    compile_ms::Float64
    build_ms::Float64
    sampled_times::Vector{Vector{Float64}}   # per disruption: the occurrences drawn for this run
    run_settings::Any             # what a run reads from the blocks, kept (`run_tolerances`)
end

Base.show(io::IO, s::System) = print(io, "System(", repr(s.project.name), ": ", s.nstate, " states, ", s.nalg,
                                     " algebraic slots, ", s.nparam, " parameters)")

has_events(s::System) = !isempty(s.event_slots)
has_store_step(s::System) = !isempty(s.remembering) || !isempty(s.laplace)

"""
    build_system(project; jacobian=true) -> System

A project built into equations and compiled.
"""
function build_system(project::Project; jacobian::Bool=true)
    t0 = time()
    b = build(project)
    build_done = time()
    data = ModelData()
    data.TAB = b.TAB
    data.MEM = b.MEM
    data.DIS = ones(max(1, length(b.disruption_layout)))
    data.T0 = Float64(project.simulation["start_time"])
    data.T1 = Float64(project.simulation["end_time"])
    data.FARF = b.FARF
    w = CodeWriter(data)
    initial_stmts = merge_statements([Stmt(s.out, s.tree, s.width, s.block, s.level, s.mergeable, s.special, s.array,
                                           s.multiply) for s in b.initial_before])
    append!(initial_stmts, merge_statements(b.initial_stmts))
    step = merge_statements(b.pass_stmts[2])
    passes = Pair{Symbol,Vector{Stmt}}[
        :invariant => merge_statements(b.pass_stmts[0]),
        :at_instant => merge_statements(b.pass_stmts[1]),
        :moving => step,
        :initial => initial_stmts,
    ]
    b.derivative_stmts !== nothing && push!(passes, :moving_derivative => merge_statements(b.derivative_stmts))
    fns, defs = compile_passes(w, passes)
    compiled = time()
    sys = System(project, b, b.nstate, b.nalg, b.nparam, b.P, zeros(max(1, b.nalg)), data, data.T0, data.T1,
                 fns[:invariant], fns[:at_instant], fns[:moving],
                 get(fns, :moving_derivative, fns[:moving]), fns[:initial], defs,
                 Assembler(b), 0, b.slot_class, findall(==(1), b.slot_class[1:b.nalg]), Float64[], Float64[], 0.0,
                 data.T0, NaN, NaN, NaN, b.jump_specs, [r for r in b.recorders if r[:mem] >= 0], b.recorders,
                 Any[F for F in b.FARF if farfield_is_laplace(F)],
                 Int[e.slot + 1 for e in b.event_slots], b.event_direction, b.event_handlers,
                 nothing, 1000 * (compiled - build_done), 1000 * (build_done - t0),
                 [Float64[] for _ in b.disruption_layout], nothing)
    sys.lo_x = zeros(length(sys.clock_idx))
    sys.hi_x = zeros(length(sys.clock_idx))
    setup_assembler!(sys)
    set_threads!(sys.assembler, Threads.nthreads())
    evaluate_invariant!(sys)
    isempty(sys.laplace) || semi_refusals(b, sys.X)
    if !jacobian
        sys.jacobian = (available=false, reason="not asked for")
    elseif sys.nstate == 0
        sys.jacobian = (available=false, reason="the model has no compartments to differentiate")
    else
        sys.jacobian = build_jacobian(sys)
    end
    return sys
end

# --- the assembly -----------------------------------------------------------------------------

function Assembler(b::Builder)
    n = b.nstate
    rows = Int[]
    cols = Int[]
    seq = Float64[]
    nent = Ref(0)
    function entries!(r, c, order)
        ids = collect(nent[]+1:nent[]+length(r))
        nent[] += length(r)
        append!(rows, r)
        append!(cols, c === nothing ? fill(n, length(r)) : c)
        append!(seq, order)
        return ids
    end
    lin = Any[]
    aff = Any[]
    coef_slots = Int[]
    function linear!(r, c, order, kind, data, slots=nothing)
        isempty(r) && return
        push!(lin, (kind, data, entries!(r, c, order)))
        slots !== nothing && append!(coef_slots, slots)
    end
    function affine!(r, order, kind, data)
        isempty(r) && return
        push!(aff, (kind, data, entries!(r, nothing, order)))
    end
    base = 0.0
    for ph in b.phases
        k = ph.kind
        if k === :transfers
            tgt, flux, sign = ph.tgt, ph.a, ph.f
            src_of = fill(-1, b.nflux)
            src_of[b.flux_mbd.+1] = b.flux_mbd_src
            src = src_of[flux.+1]
            rate = b.flux_rate[flux.+1]
            order = base .+ collect(0:length(tgt)-1)
            mbd = src .>= 0
            any(mbd) && linear!(tgt[mbd], src[mbd], order[mbd], :xsign, (rate[mbd], sign[mbd]), rate[mbd])
            any(.!mbd) && affine!(tgt[.!mbd], order[.!mbd], :xsign, (rate[.!mbd], sign[.!mbd]))
            base += length(tgt)
        elseif k === :x
            affine!(ph.tgt, base .+ collect(0:length(ph.tgt)-1), :x, ph.a)
            base += length(ph.tgt)
        elseif k === :waste
            p_idx, m_idx, h, r_idx, budget = ph.tgt, ph.a, ph.s1, ph.b, ph.c
            kk = length(p_idx)
            wd = isempty(budget) ? 2 : 3
            o = base .+ collect(0:kk-1) .* wd
            hs = fill(h, kk)
            linear!(p_idx, p_idx, o, :xsign, (hs, fill(-1.0, kk)), hs)
            affine!(m_idx, o .+ 1, :fail, (h, p_idx, r_idx))
            isempty(budget) || affine!(budget, o .+ 2, :x, r_idx)
            base += kk * wd
        elseif k === :move
            a_idx, second, lam_slot, share_slot = ph.tgt, ph.a, ph.s1, ph.s2
            kk = length(a_idx)
            wd = isempty(second) ? 1 : 2
            o = base .+ collect(0:kk-1) .* wd
            ls = fill(lam_slot, kk)
            ss = fill(share_slot, kk)
            linear!(a_idx, a_idx, o, :xx, (ls, ss, fill(-1.0, kk)), vcat(ls, ss))
            isempty(second) || linear!(second, a_idx, o .+ 1, :xx, (ls, ss, fill(1.0, kk)), vcat(ls, ss))
            base += kk * wd
        elseif k === :mean
            affine!(ph.tgt, base .+ collect(0:length(ph.tgt)-1), :mean, (ph.a, ph.s1))
            base += length(ph.tgt)
        elseif k === :coef
            linear!(ph.tgt, ph.a, base .+ collect(0:length(ph.tgt)-1), :const, ph.f)
            base += length(ph.tgt)
        elseif k === :farf
            F = b.FARF[ph.s1+1]
            rf, cf = farfield_row_col(F)
            linear!(rf, cf, base .+ collect(0:length(rf)-1), :farf, ph.s1, vec(farfield_setting_slots(F)))
            base += length(rf)
        end
    end
    m = length(rows)
    # Rows in order, and within a row the terms in the order they are added.
    order = sortperm(collect(1:m); by=i -> (rows[i], seq[i]))
    pos = Vector{Int}(undef, m)
    pos[order] = 1:m
    rowptr = ones(Int, n + 1)
    counts = zeros(Int, n)
    for r in rows
        counts[r+1] += 1
    end
    for i in 1:n
        rowptr[i+1] = rowptr[i] + counts[i]
    end
    m < typemax(Int32) || throw(BuildError("The derivative has $m terms, more than this engine can index.", nothing))
    A = Assembler(n, Int32.(rowptr), Int32.(cols[order] .+ 1), zeros(m),
                  Int32[], Int32[], Float64[], 1, Int[], Int[], Int[], Float64[], Int[], Float64[], false,
                  Tuple{Int,Vector{Int}}[],
                  Int[], Int[], Float64[], Int[], Int[], Int[], Int[], Int[], Int[], Int[], Int[], Int[],
                  0, -1, NaN, false, m == 0, UnitRange{Int}[], UnitRange{Int}[], UnitRange{Int}[], nothing)
    for (kind, d, ids) in lin
        p = pos[ids]
        if kind === :xsign
            append!(A.lin_xsign_pos, p); append!(A.lin_xsign_slot, d[1] .+ 1); append!(A.lin_xsign_sign, d[2])
        elseif kind === :xx
            append!(A.lin_xx_pos, p); append!(A.lin_xx_a, d[1] .+ 1); append!(A.lin_xx_b, d[2] .+ 1)
            append!(A.lin_xx_sign, d[3])
        elseif kind === :const
            append!(A.lin_const_pos, p); append!(A.lin_const_val, d)
        elseif kind === :farf
            push!(A.lin_farf, (d, p))
        end
    end
    for (kind, d, ids) in aff
        p = pos[ids]
        if kind === :xsign
            append!(A.aff_xsign_pos, p); append!(A.aff_xsign_slot, d[1] .+ 1); append!(A.aff_xsign_sign, d[2])
        elseif kind === :x
            append!(A.aff_x_pos, p); append!(A.aff_x_slot, d .+ 1)
        elseif kind === :fail
            h, p_idx, r_idx = d
            append!(A.aff_fail_pos, p); append!(A.aff_fail_h, fill(h + 1, length(p))); append!(A.aff_fail_p, p_idx .+ 1)
            append!(A.aff_fail_r, r_idx .+ 1)
        elseif kind === :mean
            t_idx, m0 = d
            append!(A.aff_mean_pos, p); append!(A.aff_mean_slot, t_idx .+ 1)
            append!(A.aff_mean_mem, m0 .+ collect(1:length(t_idx)))
        end
    end
    slots = unique(coef_slots)
    classes = isempty(slots) ? UInt8[] : b.slot_class[slots.+1]
    A.moves = any(==(2), classes) ? 2 : (any(==(1), classes) ? 1 : 0)
    # The coefficients read from a slot that moves with the state last, in their order: only
    # they are written again on a call that finds the clock where it was.
    fast = Bool[b.slot_class[s] == 2 for s in A.lin_xsign_slot]
    if any(fast)
        o = [findall(!, fast); findall(fast)]
        A.lin_xsign_pos = A.lin_xsign_pos[o]
        A.lin_xsign_slot = A.lin_xsign_slot[o]
        A.lin_xsign_sign = A.lin_xsign_sign[o]
    end
    A.lin_fast_from = count(!, fast) + 1
    parity() || (A.merged = merge_terms(A, b))
    return A
end

"""The terms merged into one entry per state and column (`MergedMatrix`), with where each
entry's value comes from."""
function merge_terms(A::Assembler, b::Builder)
    n = A.n
    m = length(A.data)
    cls = b.slot_class
    # The entry each linear term adds into: terms are in row order, so a row's entries are
    # found together, each column's first term in the row making its entry.
    term_entry = zeros(Int32, m)
    rowptr = ones(Int32, n + 1)
    cols = Int32[]
    seen_row = zeros(Int32, n)
    seen_entry = zeros(Int32, n)
    aff_rows = Int32[]
    aff_ptr = Int32[1]
    aff_pos = Int32[]
    for i in 1:n
        affine = false
        for k in Int(A.rowptr[i]):Int(A.rowptr[i+1])-1
            c = Int(A.cols[k])
            if c > n
                push!(aff_pos, k)
                affine = true
                continue
            end
            if seen_row[c] == i
                term_entry[k] = seen_entry[c]
            else
                push!(cols, c)
                j = Int32(length(cols))
                seen_row[c] = i
                seen_entry[c] = j
                term_entry[k] = j
            end
        end
        rowptr[i+1] = Int32(length(cols) + 1)
        if affine
            push!(aff_rows, i)
            push!(aff_ptr, Int32(length(aff_pos) + 1))
        end
    end
    nm = length(cols)
    # Each entry's sources, grouped by entry. A linear source whose term lands in the constant
    # column (entry 0) is the constant column's: its value goes into the terms, and from them into b.
    count_src = zeros(Int32, nm + 1)
    aff_src = Int32[]
    for (q, k) in enumerate(A.lin_xsign_pos)
        j = term_entry[k]
        j == 0 ? push!(aff_src, q) : (count_src[j+1] += 1)
    end
    src_ptr = Int32.(cumsum(vcat(1, count_src[2:end])))
    next = copy(src_ptr)
    src_slot = Vector{Int32}(undef, src_ptr[end] - 1)
    src_sign = Vector{Float64}(undef, src_ptr[end] - 1)
    fast_entry = falses(nm)
    for q in eachindex(A.lin_xsign_pos)
        j = term_entry[A.lin_xsign_pos[q]]
        j == 0 && continue
        src_slot[next[j]] = A.lin_xsign_slot[q]
        src_sign[next[j]] = A.lin_xsign_sign[q]
        next[j] += 1
        cls[A.lin_xsign_slot[q]] == 2 && (fast_entry[j] = true)
    end
    konst = zeros(nm)
    for q in eachindex(A.lin_const_pos)
        k = A.lin_const_pos[q]
        j = term_entry[k]
        # A constant in the constant column is a term written once.
        j == 0 ? (A.data[k] = A.lin_const_val[q]) : (konst[j] += A.lin_const_val[q])
    end
    extra_pos = Int32[]
    extra_dest = Int32[]
    extra_moves = Bool[]
    for q in eachindex(A.lin_xx_pos)
        k = A.lin_xx_pos[q]
        term_entry[k] == 0 && continue          # written into the terms, summed into b
        push!(extra_pos, k)
        push!(extra_dest, term_entry[k])
        push!(extra_moves, max(cls[A.lin_xx_a[q]], cls[A.lin_xx_b[q]]) == 2)
    end
    for (_, positions) in A.lin_farf, k in positions
        term_entry[k] == 0 && continue
        push!(extra_pos, k)
        push!(extra_dest, term_entry[k])
        push!(extra_moves, A.moves == 2)
    end
    for (e, moves) in enumerate(extra_moves)
        moves && (fast_entry[extra_dest[e]] = true)
    end
    fast = Int32[j for j in 1:nm if fast_entry[j]]
    extra_fast = Int32[e for e in eachindex(extra_dest) if fast_entry[extra_dest[e]]]
    return MergedMatrix(rowptr, cols, zeros(nm), src_ptr, src_slot, src_sign, konst, extra_pos, extra_dest, fast,
                        extra_fast, aff_rows, aff_ptr, aff_pos, aff_src, zeros(n), UnitRange{Int}[], UnitRange{Int}[])
end

setup_assembler!(sys::System) = (sys.assembler.keyed = false; nothing)

function _set_xsign!(data::Vector{Float64}, pos::Vector{Int32}, slot::Vector{Int32}, sign::Vector{Float64},
                     X::Vector{Float64}, range::UnitRange{Int})
    @inbounds for i in range
        data[pos[i]] = X[slot[i]] * sign[i]
    end
end

"""The coefficients read from slots, over `range` of them: on the threads `chunks` share them out to, or on one."""
function _set_xsign_part!(A::Assembler, X::Vector{Float64}, range::UnitRange{Int}, chunks::Vector{UnitRange{Int}})
    isempty(range) && return
    if isempty(chunks)
        _set_xsign!(A.data, A.lin_xsign_pos, A.lin_xsign_slot, A.lin_xsign_sign, X, range)
    else
        Threads.@threads :dynamic for k in eachindex(chunks)
            _set_xsign!(A.data, A.lin_xsign_pos, A.lin_xsign_slot, A.lin_xsign_sign, X, chunks[k])
        end
    end
end

"""Every linear coefficient: the constants (once), those that never move or follow the clock,
and those that move with the state."""
function _set_linear!(A::Assembler, sys::System, X::Vector{Float64})
    if !A.consts_written
        data = A.data
        @inbounds for i in eachindex(A.lin_const_pos)
            data[A.lin_const_pos[i]] = A.lin_const_val[i]
        end
        A.consts_written = true
    end
    _set_xsign_part!(A, X, 1:A.lin_fast_from-1, A.lin_chunks)
    _set_fast!(A, sys, X)
end

"""The linear coefficients that can move with the state: those read from slots that move with
it, the products of two slots, and the far-field paths'."""
function _set_fast!(A::Assembler, sys::System, X::Vector{Float64})
    data = A.data
    _set_xsign_part!(A, X, A.lin_fast_from:length(A.lin_xsign_pos), A.lin_fast_chunks)
    @inbounds for i in eachindex(A.lin_xx_pos)
        data[A.lin_xx_pos[i]] = X[A.lin_xx_a[i]] * X[A.lin_xx_b[i]] * A.lin_xx_sign[i]
    end
    for (k, p) in A.lin_farf
        F = sys.data.FARF[k+1]
        farfield_refresh!(F, X)
        vals = farfield_values(F)
        @inbounds for i in eachindex(p)
            data[p[i]] = vals[i]
        end
    end
end

function _set_affine!(A::Assembler, sys::System, y::Vector{Float64}, X::Vector{Float64})
    data = A.data
    @inbounds for i in eachindex(A.aff_xsign_pos)
        data[A.aff_xsign_pos[i]] = X[A.aff_xsign_slot[i]] * A.aff_xsign_sign[i]
    end
    @inbounds for i in eachindex(A.aff_x_pos)
        data[A.aff_x_pos[i]] = X[A.aff_x_slot[i]]
    end
    @inbounds for i in eachindex(A.aff_fail_pos)
        data[A.aff_fail_pos[i]] = X[A.aff_fail_h[i]] * y[A.aff_fail_p[i]] - X[A.aff_fail_r[i]]
    end
    if !isempty(A.aff_mean_pos)
        mem = sys.data.MEM
        @inbounds for i in eachindex(A.aff_mean_pos)
            data[A.aff_mean_pos[i]] = mem[A.aff_mean_mem[i]].recording ? X[A.aff_mean_slot[i]] : 0.0
        end
    end
end

# --- the merged matrix (parity off) ---------------------------------------------------------------

"""The product and far-field terms' values, into the terms (`data`), for the merged entries to add."""
function _set_extras!(A::Assembler, sys::System, X::Vector{Float64})
    data = A.data
    @inbounds for i in eachindex(A.lin_xx_pos)
        data[A.lin_xx_pos[i]] = X[A.lin_xx_a[i]] * X[A.lin_xx_b[i]] * A.lin_xx_sign[i]
    end
    for (k, p) in A.lin_farf
        F = sys.data.FARF[k+1]
        farfield_refresh!(F, X)
        vals = farfield_values(F)
        @inbounds for i in eachindex(p)
            data[p[i]] = vals[i]
        end
    end
end

"""The merged entries `js` from their sources: the constant part, then each slot read."""
function _gather!(M::MergedMatrix, X::Vector{Float64}, js)
    vals, ptr, slot, sgn, konst = M.vals, M.src_ptr, M.src_slot, M.src_sign, M.konst
    @inbounds for j in js
        acc = konst[j]
        for q in Int(ptr[j]):Int(ptr[j+1])-1
            acc = muladd(X[slot[q]], sgn[q], acc)
        end
        vals[j] = acc
    end
end

"""Brings the merged entries up to date: every one when the invariants or the clock have moved
since, otherwise those that move with the state."""
function refresh_merged!(A::Assembler, M::MergedMatrix, sys::System, X::Vector{Float64})
    data = A.data
    if A.keyed && A.key_version == sys.invariant_version && (A.moves == 0 || A.key_clock === sys.clock_at)
        A.moves == 2 || return
        # (the product and far-field terms written whole: some may be in the constant column)
        (isempty(A.lin_xx_pos) && isempty(A.lin_farf)) || _set_extras!(A, sys, X)
        _gather!(M, X, M.fast)
        @inbounds for e in M.extra_fast
            M.vals[M.extra_dest[e]] += data[M.extra_pos[e]]
        end
        return
    end
    (isempty(A.lin_xx_pos) && isempty(A.lin_farf)) || _set_extras!(A, sys, X)
    if isempty(M.gather_chunks)
        _gather!(M, X, 1:length(M.vals))
    else
        chunks = M.gather_chunks
        Threads.@threads :dynamic for c in eachindex(chunks)
            _gather!(M, X, chunks[c])
        end
    end
    @inbounds for e in eachindex(M.extra_pos)
        M.vals[M.extra_dest[e]] += data[M.extra_pos[e]]
    end
    A.key_version = sys.invariant_version
    A.key_clock = sys.clock_at
    A.keyed = true
end

"""The constant column, row by row, from the affine terms' values."""
function _merged_affine!(M::MergedMatrix, data::Vector{Float64})
    b = M.b
    @inbounds for (q, i) in enumerate(M.aff_rows)
        acc = 0.0
        for p in Int(M.aff_ptr[q]):Int(M.aff_ptr[q+1])-1
            acc += data[M.aff_pos[p]]
        end
        b[i] = acc
    end
end

function _merged_rows!(dy::Vector{Float64}, M::MergedMatrix, y::Vector{Float64}, rows::UnitRange{Int})
    rowptr, cols, vals, b = M.rowptr, M.cols, M.vals, M.b
    @inbounds for i in rows
        acc = b[i]
        for jj in Int(rowptr[i]):Int(rowptr[i+1])-1
            acc = muladd(vals[jj], y[cols[jj]], acc)
        end
        dy[i] = acc
    end
    return dy
end

"""Brings the linear coefficients up to date, if they can have moved: every one when the
invariants or the clock have moved since they were written, otherwise only those that move
with the state."""
function refresh_linear!(A::Assembler, sys::System, X::Vector{Float64})
    if A.keyed && A.key_version == sys.invariant_version && (A.moves == 0 || A.key_clock === sys.clock_at)
        A.moves == 2 && _set_fast!(A, sys, X)
        return
    end
    _set_linear!(A, sys, X)
    A.key_version = sys.invariant_version
    A.key_clock = sys.clock_at
    A.keyed = true
end

"""The derivative's rows summed: each product rounded, then added in order."""
function assemble!(dy::Vector{Float64}, A::Assembler, sys::System, y::Vector{Float64}, X::Vector{Float64})
    n = A.n
    if A.empty
        fill!(dy, 0.0)
        return dy
    end
    M = A.merged
    if M !== nothing
        refresh_merged!(A, M, sys, X)
        _set_affine!(A, sys, y, X)
        if !isempty(M.aff_src)
            data = A.data
            @inbounds for q in M.aff_src
                data[A.lin_xsign_pos[q]] = X[A.lin_xsign_slot[q]] * A.lin_xsign_sign[q]
            end
        end
        _merged_affine!(M, A.data)
        if isempty(M.row_chunks)
            _merged_rows!(dy, M, y, 1:n)
        else
            chunks = M.row_chunks
            Threads.@threads :dynamic for c in eachindex(chunks)
                _merged_rows!(dy, M, y, chunks[c])
            end
        end
        return dy
    end
    refresh_linear!(A, sys, X)
    _set_affine!(A, sys, y, X)
    if isempty(A.row_chunks)
        _assemble_rows!(dy, A.rowptr, A.cols, A.data, y, n, 1:n)
    else
        chunks = A.row_chunks
        Threads.@threads :dynamic for k in eachindex(chunks)
            _assemble_rows!(dy, A.rowptr, A.cols, A.data, y, n, chunks[k])
        end
    end
    return dy
end

function _assemble_rows!(dy::Vector{Float64}, rowptr::Vector{Int32}, cols::Vector{Int32}, data::Vector{Float64},
                         y::Vector{Float64}, n::Int, rows::UnitRange{Int})
    @inbounds for i in rows
        acc = 0.0
        for jj in Int(rowptr[i]):Int(rowptr[i+1])-1
            c = Int(cols[jj])
            acc += data[jj] * (c <= n ? y[c] : 1.0)
        end
        dy[i] = acc
    end
    return dy
end

# --- evaluating -------------------------------------------------------------------------------

"""The distributed points of the lookup tables back into their tables."""
function refresh_tables!(sys::System)
    for pt in sys.builder.point_layout
        (pt[:tab] < 0 || pt[:row] < 0) && continue
        table = sys.data.TAB[pt[:tab]+1]
        pt[:row] < table.n && set_y!(table, pt[:row], sys.P[pt[:slot]+1])
    end
end

"""Works out the slots that never move (after a parameter has changed)."""
function evaluate_invariant!(sys::System, t=nothing, y=nothing)
    refresh_tables!(sys)
    tt = t === nothing ? sys.start_time : Float64(t)
    yy = y === nothing ? zeros(sys.nstate) : y
    sys.once(tt, yy, sys.X, sys.P, sys.data)
    sys.clock_at = NaN
    sys.invariant_version += 1
    return sys.X
end

"""Works the clock-only slots out every `interval` and interpolates between
(`min_change_time`); 0 is off."""
function use_clock_interpolation!(sys::System, interval::Float64, frm=nothing)
    sys.min_change = isfinite(interval) && interval > 0 ? interval : 0.0
    sys.origin = (frm !== nothing && isfinite(frm)) ? Float64(frm) : sys.start_time
    sys.lo_t = NaN
    sys.hi_t = NaN
    sys.clock_at = NaN
    # A segment's start reads the clock afresh: the coefficients are worked out again.
    sys.assembler.keyed = false
    return sys
end

function _clock_into!(sys::System, t::Float64, y::Vector{Float64}, into::Vector{Float64})
    sys.clock(t, y, sys.X, sys.P, sys.data)
    @inbounds for (k, i) in enumerate(sys.clock_idx)
        into[k] = sys.X[i]
    end
end

"""Brings the clock-only slots up to `t`, if they are not there already."""
function at_instant!(sys::System, t::Float64, y::Vector{Float64})
    t === sys.clock_at && return
    t == sys.clock_at && return
    if sys.min_change > 0 && !isempty(sys.clock_idx)
        k = floor((t - sys.origin) / sys.min_change)
        a = sys.origin + k * sys.min_change
        b = a + sys.min_change
        if a != sys.lo_t
            if a == sys.hi_t
                copyto!(sys.lo_x, sys.hi_x)
            else
                _clock_into!(sys, a, y, sys.lo_x)
            end
            sys.lo_t = a
        end
        if b != sys.hi_t
            _clock_into!(sys, b, y, sys.hi_x)
            sys.hi_t = b
        end
        wgt = (t - a) / sys.min_change
        X = sys.X
        @inbounds for (j, i) in enumerate(sys.clock_idx)
            X[i] = sys.lo_x[j] + wgt * (sys.hi_x[j] - sys.lo_x[j])
        end
        sys.clock_at = t
        return
    end
    sys.clock(t, y, sys.X, sys.P, sys.data)
    sys.clock_at = t
    return
end

"""Every algebraic slot at `(t, y)`, in `sys.X` (the vector is reused)."""
function evaluate_algebraic!(sys::System, t::Float64, y::Vector{Float64})
    at_instant!(sys, t, y)
    sys.step(t, y, sys.X, sys.P, sys.data)
    return sys.X
end

"""The algebraic slots the derivative reads at `(t, y)`; the others are left as they were."""
function evaluate_for_derivative!(sys::System, t::Float64, y::Vector{Float64})
    at_instant!(sys, t, y)
    sys.step_d(t, y, sys.X, sys.P, sys.data)
    return sys.X
end

"""
    rhs!(sys, dy, t, y) -> dy

The derivative at `(t, y)`.
"""
function rhs!(sys::System, dy::Vector{Float64}, t::Float64, y::Vector{Float64})
    at_instant!(sys, t, y)
    sys.step_d(t, y, sys.X, sys.P, sys.data)
    assemble!(dy, sys.assembler, sys, y, sys.X)
    return dy
end

dydt(sys::System, t::Real, y::AbstractVector) = rhs!(sys, zeros(sys.nstate), Float64(t), Vector{Float64}(y))

function initial_state(sys::System)
    y0 = zeros(sys.nstate)
    sys.initial(sys.start_time, y0, sys.X, sys.P, sys.data)
    return y0
end

# --- recorders, events and jumps -----------------------------------------------------------

"""Puts every history back to the start of a run."""
function prime_recorders!(sys::System, t0::Float64, y0::Vector{Float64})
    (isempty(sys.remembering) && isempty(sys.laplace)) && return
    for r in sys.data.MEM
        prime!(r, t0, 0.0)
    end
    # A seed may read another block that remembers -- the peak of a dose
    # worked out from a delayed volume -- and the pass that works it out reads
    # that block's history before it has one: the seeds are worked out again
    # with the histories primed, until none of them moves (the application's
    # `primeRecorders`).
    values = evaluate_algebraic!(sys, t0, y0)
    seeds = Float64[]
    for sweep in 0:length(sys.remembering)
        moved = false
        i = 0
        for rec in sys.remembering
            seed = rec.kind == "snapshot" ? rec[:aux]["initial"] : rec[:aux]["target"]
            for off in 0:rec.width-1
                i += 1
                v = values[seed.base+off+1]
                sweep > 0 && isequal(seeds[i], v) && continue
                sweep == 0 ? push!(seeds, v) : (seeds[i] = v)
                prime!(sys.data.MEM[rec[:mem]+off+1], t0, v)
                moved = true
            end
        end
        moved || break
        values = evaluate_algebraic!(sys, t0, y0)
    end
    for F in sys.laplace
        farfield_prime!(F, t0, y0, values)
    end
end

"""Records a step the solver accepted."""
function store_step!(sys::System, t::Float64, y::Vector{Float64})
    (isempty(sys.remembering) && isempty(sys.laplace)) && return
    values = evaluate_algebraic!(sys, t, y)
    for rec in sys.remembering
        frm = rec.kind == "delay" ? rec[:aux]["target"] : rec[:entry]
        for off in 0:rec.width-1
            store!(sys.data.MEM[rec[:mem]+off+1], t, values[frm.base+off+1])
        end
    end
    for F in sys.laplace
        farfield_store!(F, t, y, values)
    end
end

"""A segment starts at `t` from `y`: only semi-analytical paths are told."""
function start_segment!(sys::System, t::Float64, y::Vector{Float64})
    isempty(sys.laplace) && return
    values = evaluate_algebraic!(sys, t, y)
    for F in sys.laplace
        farfield_store!(F, t, y, values)
    end
end

"""The discrete events' functions at `(t, y)`, into `out`."""
function event_values!(out::Vector{Float64}, sys::System, t::Float64, y::Vector{Float64})
    values = evaluate_algebraic!(sys, t, y)
    @inbounds for (k, s) in enumerate(sys.event_slots)
        out[k] = values[s]
    end
    return out
end

"""Fires the events `which` (1-based) at `(t, y)`."""
function fire_events!(sys::System, which, t::Float64, y::Vector{Float64})
    values = evaluate_algebraic!(sys, t, y)
    mem = sys.data.MEM
    for i in which
        for h in get(sys.event_handlers, i - 1, ())
            rec = h.rec
            off = h.off
            summed = rec[:state] !== nothing ? y[rec[:state].base+off+1] : 0.0
            fire!(mem[rec[:mem]+off+1], h.action, t, values[rec[:aux]["target"].base+off+1], summed)
        end
    end
end

"""
What the events the triggers `which` (1-based) set off do to the state: applied to
a copy of `y`, in the order the model lists them, each once however many of its
trigger's indices fired together, reading their shares from `X` as firing the
triggers left it -- `(state, how many acted)`, or `nothing` when none did (the
application's `events.fire`).
"""
function jumps_at_crossing(sys::System, which, y::Vector{Float64})
    nxt = nothing
    acted = 0
    for j in sys.jumps
        isempty(j.fired_by) && continue
        any(i -> (i - 1) in j.fired_by, which) || continue
        nxt === nothing && (nxt = copy(y))
        apply_jump!(nxt, sys.X, j)
        acted += 1
    end
    return nxt === nothing ? nothing : (nxt, acted)
end

"""Whether an event's occurrences are drawn for this run, and which."""
function set_disruption!(sys::System, index::Int, sampled::Bool, times=Float64[])
    layout = sys.builder.disruption_layout
    0 <= index < length(layout) || return
    sys.data.DIS[index+1] = sampled ? 0.0 : 1.0
    sys.sampled_times[index+1] = sampled ? sort(collect(Float64, times)) : Float64[]
    sys.clock_at = NaN
end

"""Applies a jump's operations to `y`, in place, as the application's generated code does."""
function apply_jump!(y::Vector{Float64}, X::Vector{Float64}, spec::JumpSpec)
    for op in spec.ops
        if op isa JumpCount
            y[op.slot+1] += 1
        elseif op isa JumpFail
            share = op.share_slot < 0 ? 1.0 : X[op.share_slot+1]
            n = length(op.intact)
            fail = Vector{Float64}(undef, n)
            irf = Vector{Float64}(undef, n)
            for i in 1:n
                fail[i] = share * y[op.intact[i]+1]
                irf[i] = X[op.irf[i]+1]
            end
            for i in 1:n
                y[op.intact[i]+1] -= fail[i]
            end
            for i in 1:n
                y[op.exposed[i]+1] += fail[i] * (1 - irf[i])
            end
            for i in eachindex(op.to)
                y[op.to[i]+1] += fail[i] * irf[i]
            end
            for i in eachindex(op.budget)
                y[op.budget[i]+1] += fail[i] * irf[i]
            end
        elseif op isa JumpMove
            share = X[op.share_slot+1]
            n = length(op.from)
            m = Vector{Float64}(undef, n)
            for i in 1:n
                m[i] = share * y[op.from[i]+1]
            end
            for i in 1:n
                y[op.from[i]+1] -= m[i]
            end
            if !isempty(op.to)
                for i in 1:n
                    y[op.to[i]+1] += m[i]
                end
            else
                for i in eachindex(op.budget)
                    y[op.budget[i]+1] += m[i]
                end
            end
        end
    end
    return y
end

slot_value(sys::System, i::Int) = sys.X[i+1]

"""
The times the tables read at the clock turn at, strictly inside (frm, to), in
order (`tableCorners`); `nothing` for a model with more than `limit` of them.
"""
function table_corners(sys::System, frm::Float64, to::Float64, limit::Real=Inf)
    lo = min(frm, to)
    hi = max(frm, to)
    found = Float64[]
    for lk in sys.builder.lookup_layout
        lk[:argument] !== nothing && continue
        rule = get(lk.block, "interpolation", nothing)
        for k in lk[:tab]:lk[:tab]+lk.width-1
            table = k < length(sys.data.TAB) ? sys.data.TAB[k+1] : nothing
            table === nothing && continue
            x = table.x
            length(x) < 2 && continue
            at = rule == "nearest" ? [(x[i] + x[i+1]) / 2 for i in 1:length(x)-1] : copy(x)
            if !table.cyclic
                append!(found, [c for c in at if lo < c < hi])
                continue
            end
            period = x[end] - x[1]
            period > 0 || continue
            first_ = floor((lo - x[1]) / period)
            last = ceil((hi - x[1]) / period)
            (last - first_) * (length(at) - 1) > limit && return nothing
            for p in first_:last, c in at
                t = c + p * period
                lo < t < hi && push!(found, t)
            end
        end
    end
    sort!(found)
    out = Float64[]
    for t in found
        prev = isempty(out) ? -Inf : out[end]
        t - prev <= 1e-9 * max(1.0, abs(t)) && continue
        push!(out, t)
        length(out) > limit && return nothing
    end
    return out
end

"""
Where a step is to end so as not to pass over a pulse in a table read at the
clock, for this rtol (`tableLanding`; see engine/landing.jl): a
[`TableLanding`](@ref), or `nothing` when no table turns. Cyclic tables are left
out, and a table shared by several slots is judged once. Made from the tables
as they stand: a realisation writes its points into them first.
"""
function table_landing(sys::System, rtol::Float64)::Union{Nothing,TableLanding}
    seen = Base.IdSet{Any}()
    tables = Any[]
    for lk in sys.builder.lookup_layout
        lk[:argument] !== nothing && continue
        for k in lk[:tab]:lk[:tab]+lk.width-1
            table = k < length(sys.data.TAB) ? sys.data.TAB[k+1] : nothing
            (table === nothing || table.cyclic || table in seen) && continue
            push!(seen, table)
            push!(tables, table)
        end
    end
    return table_landing(tables, rtol)
end

# --- what a run leaves behind -------------------------------------------------------------

"""What a run leaves on the system that reading its results depends on."""
run_state(sys::System) = (mem=[copy(r) for r in sys.data.MEM], dis=copy(sys.data.DIS),
                          sampled=[copy(v) for v in sys.sampled_times],
                          clock=(sys.min_change, sys.origin),
                          laplace=Any[laplace_run_state(F) for F in sys.laplace])

function restore_run_state!(sys::System, state)
    for (i, r) in enumerate(state.mem)
        sys.data.MEM[i] = copy(r)
    end
    copyto!(sys.data.DIS, state.dis)
    for (F, kept) in zip(sys.laplace, get(state, :laplace, ()))
        laplace_restore_run_state!(F, kept)
    end
    for (k, times) in enumerate(state.sampled)
        sys.sampled_times[k] = copy(times)
    end
    use_clock_interpolation!(sys, state.clock...)
end

# --- a copy for another thread ------------------------------------------------------------

copy_table(t::LookupTable) = LookupTable(t.x, copy(t.y), t.n, t.first, t.last, t.span, t.interpolation, t.cyclic, t.wraps)

"""A new instance with every field the same object as `x`'s."""
function _shallow_copy(x::T) where {T}
    y = ccall(:jl_new_struct_uninit, Any, (Any,), T)::T
    for i in 1:fieldcount(T)
        isdefined(x, i) && setfield!(y, i, getfield(x, i))
    end
    return y
end

"""A copy for another thread: the layout shared (read only, and in the caches once), the values
its own."""
function _clone_assembler(A::Assembler)
    B = _shallow_copy(A)
    B.data = copy(A.data)
    B.keyed = false
    B.row_chunks = UnitRange{Int}[]
    B.lin_chunks = UnitRange{Int}[]
    B.lin_fast_chunks = UnitRange{Int}[]
    if A.merged !== nothing
        M = _shallow_copy(A.merged)
        M.vals = copy(A.merged.vals)
        M.b = copy(A.merged.b)
        M.row_chunks = UnitRange{Int}[]
        M.gather_chunks = UnitRange{Int}[]
        B.merged = M
    end
    # A clone is one of several solved side by side: each on one thread.
    set_threads!(B, 1)
    return B
end

"""
    clone_system(sys) -> System

A copy of a built system that another thread can run beside it: the compiled
passes, the build and every index vector shared; the parameters, the
algebraic slots, the recorders' histories, the tables' values, the
derivative's coefficients and the Jacobian's work space its own.
"""
function clone_system(sys::System)
    d = sys.data
    data = ModelData(d.I, d.F, [copy_table(t) for t in d.TAB], [copy(r) for r in d.MEM], copy(d.DIS), d.T0, d.T1,
                     Any[farfield_clone(F) for F in d.FARF])
    c = System(sys.project, sys.builder, sys.nstate, sys.nalg, sys.nparam, copy(sys.P), copy(sys.X), data,
               sys.start_time, sys.end_time, sys.once, sys.clock, sys.step, sys.step_d, sys.initial, sys.source,
               _clone_assembler(sys.assembler), sys.invariant_version, sys.slot_class, sys.clock_idx, copy(sys.lo_x),
               copy(sys.hi_x), sys.min_change, sys.origin, NaN, NaN, NaN, sys.jumps, sys.remembering, sys.recorders,
               Any[F for F in data.FARF if farfield_is_laplace(F)], sys.event_slots, sys.event_direction,
               sys.event_handlers, nothing, 0.0, 0.0, [copy(v) for v in sys.sampled_times], sys.run_settings)
    c.jacobian = clone_jacobian(sys.jacobian, c)
    return c
end
