# df/dp, differentiated rather than differenced: the Python package's
# `kompartment/engine/paramtangent.py` (`buildParamTangent` in the
# application's src/sim/jacobian.js). The driving term of the forward
# sensitivity equations `S' = J·S + df/dp`, taken by the same forward-mode
# rules the analytic Jacobian uses (`Tangent`, engine/jacobian.jl), seeded on
# the parameters instead of on the state. engine/localsens.jl uses it where it
# is available, as the application does, and differences df/dp otherwise.
#
# `param_pvp(plan, t, y, w)` is `(df/dp)·w` at `(t, y)` with the state held
# fixed: the directional derivative along `w`, a vector over the parameter
# slots. Every algebraic slot's tangent is carried through all three passes --
# the slots worked out once for the run, those that move with the clock and
# those that read the state -- in the builder's dependency order, and the
# derivative's assembly is differentiated along it:
#
# - a transfer's flux `donor × rate` loses its first term (the donor is held
#   fixed), so it contributes `donor × d(rate)`, or `d(rate)` where it does not
#   multiply by the donor;
# - a source, a compartment's dy/dt term and a running mean's integral
#   contribute their slot's tangent;
# - decay and ingrowth have coefficients from the half-lives and drop out;
# - the mass-balance budget's rows get nothing, as in the application, whose
#   parameter tangent writes them only along the state.
#
# The blocks that remember: a min/max follows its target's tangent where the
# target is the extreme, a running mean its target's only before any time has
# passed, a snapshot and a delay nothing (a delay whose lag moves with a
# parameter is refused). A lookup table read at the clock has no tangent.
#
# Refused, with the application's reasons, where it refuses: a model with no
# parameters, a far-field path, a waste package or a disruptive event (each has
# runtime pieces that differentiate along the state and not along a parameter),
# a function with no derivative rule applied to something a parameter reaches,
# and a derivative that is not a number at the start of the run.

struct _PTRefused <: Exception
    message::String
end

"""One statement's part in df/dp: where its parameter leaves and its moving slots' leaves are."""
struct _PTStatement
    tree::TNode
    leaves::Vector{TLeaf}
    outs::Vector{Int}                           # the slots it writes, 0-based
    width::Int
    p_terms::Vector{Tuple{Int,Vector{Int}}}     # (leaf, from 1; the parameter slot of each element, 0-based)
    x_terms::Vector{Tuple{Int,Vector{Int}}}     # (leaf; the algebraic slot of each element, 0-based)
    multiply::Bool
end

"""A remembering block's part in df/dp."""
struct _PTRecorder
    entry::Entry
    rec::Entry
end

"""What `param_pvp` walks: the statements in dependency order, and the assembly's terms."""
struct ParamTangentPlan
    sys::System
    n::Int
    nalg::Int
    tangent::Tangent
    items::Vector{Union{_PTStatement,_PTRecorder}}
    transfers::Any          # (tgt, flux, sign, rate slots, the donor of each flux or -1), or nothing
    xs::Vector{Tuple{Vector{Int},Vector{Int}}}
    means::Vector{Tuple{Vector{Int},Vector{Int},Int}}
end

function ParamTangentPlan(sys::System)
    b = sys.builder
    n = sys.nstate
    nalg = sys.nalg
    moves = falses(max(1, nalg))     # structurally reached by a parameter
    items = Union{_PTStatement,_PTRecorder}[]
    for a in b.algebraic
        for s in b.alg_stmts[a.name]
            if s.special !== nothing
                push!(items, _pt_special(a, moves))
                continue
            end
            W = max(1, s.width)
            outs = out_indices(s)
            length(outs) < W && (outs = fill(outs[1], W))
            leaves = tree_leaves(s.tree)
            p_terms = Tuple{Int,Vector{Int}}[]
            x_terms = Tuple{Int,Vector{Int}}[]
            for (pos, leaf) in enumerate(leaves)
                if leaf.kind === :P
                    push!(p_terms, (pos, _leaf_indices(leaf, W)))
                elseif leaf.kind === :X
                    idx = _leaf_indices(leaf, W)
                    any(x -> moves[x+1], idx) && push!(x_terms, (pos, idx))
                end
            end
            live = Set{Int}(pos for (pos, _) in p_terms) ∪ Set{Int}(pos for (pos, _) in x_terms)
            isempty(live) || _check_differentiable(s.tree, live)
            reached = falses(W)
            isempty(p_terms) || (reached .= true)
            for (_, idx) in x_terms, i in 1:W
                moves[idx[i]+1] && (reached[i] = true)
            end
            if s.multiply
                for i in 1:W
                    moves[outs[i]+1] && (reached[i] = true)
                end
            end
            for i in 1:W
                moves[outs[i]+1] = reached[i]
            end
            push!(items, _PTStatement(s.tree, leaves, outs, W, p_terms, x_terms, s.multiply))
        end
    end
    # The assembly: the same phases the derivative is made of.
    budget = falses(n)
    if b.budget !== nothing
        frm, to = budget_columns(b)
        budget[frm+1:to] .= true
    end
    transfers = nothing
    xs = Tuple{Vector{Int},Vector{Int}}[]
    means = Tuple{Vector{Int},Vector{Int},Int}[]
    for ph in b.phases
        k = ph.kind
        if k === :transfers
            keep = .!budget[ph.tgt.+1]
            src_of = fill(-1, b.nflux)
            src_of[b.flux_mbd.+1] = b.flux_mbd_src
            transfers = (ph.tgt[keep], ph.a[keep], ph.f[keep], b.flux_rate, src_of)
        elseif k === :x
            keep = .!budget[ph.tgt.+1]
            push!(xs, (ph.tgt[keep], ph.a[keep]))
        elseif k === :mean
            push!(means, (ph.tgt, ph.a, ph.s1))
        elseif k === :waste || k === :move || k === :farf
            throw(_PTRefused("a block whose derivative along a parameter is not generated"))
        end
        # :coef -- decay and ingrowth, whose coefficients are not parameters.
    end
    return ParamTangentPlan(sys, n, nalg, Tangent(sys.data.TAB, Float64[], 0, 0), items, transfers, xs, means)
end

function _pt_special(a::Entry, moves::BitVector)
    rec = get(a, :recorder, nothing)
    (a.kind == "farfield" || rec === nothing) &&
        throw(_PTRefused("a far-field path, whose derivative along a parameter is not generated"))
    for off in 0:a.width-1
        i = a.base + off
        if rec.kind == "min_max" || rec.kind == "running_mean"
            moves[i+1] = moves[rec[:aux]["target"].base+off+1]
        elseif rec.kind == "delay"
            if moves[rec[:aux]["delay"].base+off+1]
                throw(_PTRefused("a delay whose lag depends on a parameter: its value slides along the recorded " *
                                 "history, and that derivative is not one to guess at"))
            end
            moves[i+1] = false
        else
            moves[i+1] = false
        end
    end
    return _PTRecorder(a, rec)
end

"""Element `i`'s leaf values, as the tangent reads them (a table's leaf: its index)."""
function _pt_values!(vals::Vector{Float64}, sys::System, leaves::Vector{TLeaf}, i::Int, y, X, t::Float64)
    for (p, l) in enumerate(leaves)
        k = l.kind
        vals[p] = k === :y ? y[leaf_index_at(l, i)+1] :
                  k === :X ? X[leaf_index_at(l, i)+1] :
                  k === :P ? sys.P[leaf_index_at(l, i)+1] :
                  k === :K ? leaf_value_at(l, i) :
                  k === :T ? t :
                  k === :T0 ? sys.start_time :
                  k === :T1 ? sys.end_time :
                  k === :DIS ? sys.data.DIS[leaf_index_at(l, i)+1] :
                  k === :TAB ? Float64(leaf_index_at(l, i)) : 0.0
    end
    return vals
end

"""
    param_pvp(plan, t, y, w) -> Vector{Float64}

`(df/dp)·w` at `(t, y)`, the state held fixed: `w` is a weight per parameter slot.
"""
function param_pvp(pt::ParamTangentPlan, t::Float64, y::Vector{Float64}, w::Vector{Float64})
    sys = pt.sys
    X = evaluate_algebraic!(sys, t, y)
    dX = zeros(max(1, pt.nalg))
    vals = Float64[]
    for item in pt.items
        if item isa _PTRecorder
            _pt_recorder!(pt, item, X, dX, t)
            continue
        end
        s = item::_PTStatement
        W = s.width
        terms = Tuple{Int,Vector{Float64}}[]
        for (pos, idx) in s.p_terms
            weight = Float64[w[x+1] for x in idx]
            any(!=(0), weight) && push!(terms, (pos, weight))
        end
        for (pos, idx) in s.x_terms
            weight = Float64[dX[x+1] for x in idx]
            any(!=(0), weight) && push!(terms, (pos, weight))
        end
        before = s.multiply ? Float64[dX[o+1] for o in s.outs] : nothing
        if isempty(terms) && (before === nothing || !any(!=(0), before))
            if s.multiply
                for o in s.outs
                    dX[o+1] = 0.0
                end
            end
            continue
        end
        length(vals) < length(s.leaves) && resize!(vals, length(s.leaves))
        d = zeros(W)
        for (pos, weight) in terms
            tangent = Vector{Float64}(undef, W)
            live = true
            for i in 1:W
                _pt_values!(vals, sys, s.leaves, i, y, X, t)
                _, ti = tangent_run!(pt.tangent, s.tree, vals, pos)
                if ti === nothing
                    live = false
                    break
                end
                tangent[i] = ti
            end
            live || continue
            for i in 1:W
                d[i] = d[i] + tangent[i] * weight[i]
            end
        end
        if s.multiply
            # X[out] *= factor: the rate's own tangent scaled by the factor,
            # plus the rate times the factor's tangent. The slot holds rate *
            # factor, so the rate is read back out.
            new = Vector{Float64}(undef, W)
            for i in 1:W
                _pt_values!(vals, sys, s.leaves, i, y, X, t)
                f, _ = tangent_run!(pt.tangent, s.tree, vals, 0)
                rate = f != 0 ? X[s.outs[i]+1] / f : 0.0
                new[i] = before[i] * f + rate * d[i]
            end
            for i in 1:W
                dX[s.outs[i]+1] = new[i]
            end
        else
            for i in 1:W
                dX[s.outs[i]+1] = d[i]
            end
        end
    end
    n = pt.n
    out = zeros(n)
    if pt.transfers !== nothing
        tgt, flux, sign, rate_slots, src_of = pt.transfers
        dflux = Float64[dX[rate_slots[q]+1] * (src_of[q] >= 0 ? y[src_of[q]+1] : 1.0) for q in eachindex(rate_slots)]
        add = zeros(n)
        for q in eachindex(tgt)
            add[tgt[q]+1] += sign[q] * dflux[flux[q]+1]
        end
        out .+= add
    end
    for (tgt, xs) in pt.xs
        add = zeros(n)
        for q in eachindex(tgt)
            add[tgt[q]+1] += dX[xs[q]+1]
        end
        out .+= add
    end
    mem = sys.data.MEM
    for (s_idx, t_idx, first) in pt.means
        for q in eachindex(s_idx)
            recording = mem[first+q].recording ? 1.0 : 0.0
            out[s_idx[q]+1] += recording * dX[t_idx[q]+1]
        end
    end
    return out
end

function _pt_recorder!(pt::ParamTangentPlan, item::_PTRecorder, X, dX, t::Float64)
    a, rec = item.entry, item.rec
    for off in 0:a.width-1
        i = a.base + off
        if rec.kind == "min_max"
            tgt = rec[:aux]["target"].base + off
            dX[i+1] = X[i+1] == X[tgt+1] ? dX[tgt+1] : 0.0
        elseif rec.kind == "running_mean"
            tgt = rec[:aux]["target"].base + off
            el = elapsed_at(pt.sys.data.MEM[rec[:mem]+off+1], t)
            dX[i+1] = el > 0 ? 0.0 : dX[tgt+1]
        else
            dX[i+1] = 0.0
        end
    end
end

"""
    param_tangent(sys) -> (available, reason, plan)

The plan of df/dp for a built model, or why there is none (`buildParamTangent`):
no analytic Jacobian, no parameters, a far-field path, a waste package or a
disruptive event, a function with no derivative rule, or a derivative that is
not a number at the start of the run.
"""
function param_tangent(sys::System)
    refused(reason) = (available=false, reason=String(reason), plan=nothing)
    jac = sys.jacobian
    if !(jac isa JacobianInfo && jac.available)
        reason = jac isa JacobianInfo ? jac.reason : nothing
        return refused("there is no analytic Jacobian: $(reason === nothing ? "None" : reason)")
    end
    sys.nparam > 0 || return refused("the model holds no parameters")
    b = sys.builder
    for (what, layout) in (("far-field path", b.farf_layout), ("waste package", b.waste_layout),
                           ("disruptive event", b.disruption_layout))
        isempty(layout) || return refused("the model has a $what, whose derivative along a parameter is not generated")
    end
    plan = try
        ParamTangentPlan(sys)
    catch e
        e isa NoDerivative && return refused("no derivative rule for $(e.what)")
        e isa _PTRefused && return refused(e.message)
        rethrow()
    end
    # The same question the Jacobian's own tangent answers at build: whether what
    # it gives at the start of the run is a number. A seed of ones exercises every
    # parameter at once.
    probe = try
        param_pvp(plan, sys.start_time, initial_state(sys), ones(sys.nparam))
    catch e
        e isa InterruptException && rethrow()
        nothing
    finally
        sys.clock_at = NaN
    end
    if probe !== nothing && !all(isfinite, probe)
        return refused("df/dp has a non-finite entry at the starting state, and a driving term that is not a number " *
                       "is not one to integrate")
    end
    return (available=true, reason=nothing, plan=plan)
end
