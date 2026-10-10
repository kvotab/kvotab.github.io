# df/dy for the implicit solvers: its structure, a colouring, and its values
# (engine/jacobian.py and engine/analytic.py).
#
# The pattern is read off the statements the derivative is made of -- which
# states each contribution reads, directly or through the algebraic slots that
# read the state -- never probed, so a coefficient that happens to be zero at
# the start is not taken for a structural zero. The values are assembled
# analytically: most of the Jacobian is direct (a transfer's rate, decay, a
# far-field path's cell matrix), and the rest comes through the slots that
# read the state by the chain rule, each slot's gradient a sparse row worked
# out in dependency order by forward-mode tangents of its statements -- the
# application's rules (`TANGENT_RULES` in src/parser/compile.js), term for
# term in the Python engine's order, so the values are its to the last bit.
#
# The budgets of the mass-balance audit follow the solver: at their diagonal
# for the solvers in DIAGONAL_BUDGET_IDS, whole for the others.

const DIAGONAL_BUDGET_IDS = Set(["ndf", "auto", "dp45", "tsit5", "vern7", "scipy_bdf", "scipy_radau", "scipy_lsoda"])

function full_budget(sys::System)
    sys.builder.budget === nothing && return false
    solver = get(sys.project.simulation, "solver", nothing)
    return !((solver === nothing ? DEFAULT_SOLVER : solver) in DIAGONAL_BUDGET_IDS)
end

budget_columns(b::Builder) = (b.budget.base, b.budget.base + length(b.budget.terms) * b.budget.nfam)

"""The colouring with the audit's budgets in one group of their own (when their rows are at the diagonal)."""
function budgets_apart(groups::Vector{Vector{Int}}, b::Builder, full::Bool)
    (b.budget === nothing || full) && return groups
    frm, to = budget_columns(b)          # 0-based [frm, to)
    rest = [filter(c -> c - 1 < frm || c - 1 >= to, g) for g in groups]
    rest = [g for g in rest if !isempty(g)]
    push!(rest, collect(frm+1:to))
    return rest
end

# --- the structure -------------------------------------------------------------------------

_leaf_indices(l::TLeaf, w::Int) = l.indices === nothing ? fill(l.index, w) : l.indices

"""For every algebraic slot that reads the state: the states it depends on
(0-based, sorted), directly or through other such slots."""
function state_dependencies(sys::System)
    b = sys.builder
    deps = Dict{Int,Vector{Int}}()
    moving = b.slot_class
    empty_ = Int[]
    of_x(idx) = moving[idx+1] == 2 ? get(deps, idx, empty_) : empty_
    for a in b.algebraic
        a.cls == 2 || continue
        for s in b.alg_stmts[a.name]
            if s.special !== nothing
                _special_dependencies!(b, a, deps, of_x)
                continue
            end
            W = max(1, s.width)
            outs = out_indices(s)
            length(outs) < W && (outs = fill(outs[1], W))
            ys = Vector{Int}[]
            xs = Vector{Int}[]
            for leaf in tree_leaves(s.tree)
                if leaf.kind === :y
                    push!(ys, _leaf_indices(leaf, W))
                elseif leaf.kind === :X
                    push!(xs, _leaf_indices(leaf, W))
                end
            end
            s.multiply && push!(xs, outs)
            for i in 1:W
                parts = Int[]
                for col in ys
                    push!(parts, col[i])
                end
                for col in xs
                    append!(parts, of_x(col[i]))
                end
                if s.multiply && haskey(deps, outs[i])
                    append!(parts, deps[outs[i]])
                end
                deps[outs[i]] = sort!(unique(parts))
            end
        end
    end
    return deps
end

function _special_dependencies!(b::Builder, a::Entry, deps, of_x)
    if a.kind == "farfield"
        F = b.FARF[a[:farf_index]+1]
        if farfield_is_laplace(F)
            for (s, cols) in enumerate(farfield_release_dependencies(F, of_x))
                deps[farfield_release_slots(F)[s]] = cols
            end
            return
        end
        rel = farfield_rel_idx(F)
        settings = farfield_setting_slots(F)
        for s in 1:farfield_slots(F)
            parts = copy(rel[s])
            for x in settings[s, :]
                append!(parts, of_x(x))
            end
            deps[farfield_release_slots(F)[s]] = sort!(unique(parts))
        end
        return
    end
    rec = get(a, :recorder, nothing)
    rec === nothing && return
    for off in 0:a.width-1
        parts = Int[]
        if rec.kind == "min_max"
            append!(parts, of_x(rec[:aux]["target"].base + off))
        elseif rec.kind == "running_mean"
            push!(parts, rec[:state].base + off)
            append!(parts, of_x(rec[:aux]["target"].base + off))
        elseif rec.kind == "delay"
            append!(parts, of_x(rec[:aux]["delay"].base + off))
        end
        deps[a.base+off] = sort!(unique(parts))
    end
end

"""Which entries of df/dy can be non-zero (rows and columns 1-based in the result)."""
function jacobian_structure(sys::System, full::Bool=false)
    b = sys.builder
    n = sys.nstate
    deps = state_dependencies(sys)
    moving = b.slot_class
    budget_rows = falses(n)
    if b.budget !== nothing && !full
        frm, to = budget_columns(b)
        budget_rows[frm+1:to] .= true
    end
    rows = collect(0:n-1)
    cols = collect(0:n-1)
    empty_ = Int[]
    x_deps(x) = moving[x+1] == 2 ? get(deps, x, empty_) : empty_
    function add(row, dep)
        if !isempty(dep) && !budget_rows[row+1]
            append!(rows, fill(row, length(dep)))
            append!(cols, dep)
        end
    end
    function add_many(tgt, src)
        for (r, c) in zip(tgt, src)
            budget_rows[r+1] && continue
            push!(rows, r)
            push!(cols, c)
        end
    end
    for ph in b.phases
        k = ph.kind
        if k === :transfers
            src_of_flux = fill(-1, b.nflux)
            src_of_flux[b.flux_mbd.+1] = b.flux_mbd_src
            srcs = src_of_flux[ph.a.+1]
            has = srcs .>= 0
            add_many(ph.tgt[has], srcs[has])
            rate = b.flux_rate[ph.a.+1]
            for (r, x) in zip(ph.tgt, rate)
                add(r, x_deps(x))
            end
        elseif k === :x
            for (r, x) in zip(ph.tgt, ph.a)
                add(r, x_deps(x))
            end
        elseif k === :waste
            p_idx, m_idx, h, r_idx, budget = ph.tgt, ph.a, ph.s1, ph.b, ph.c
            add_many(p_idx, p_idx)
            add_many(m_idx, p_idx)
            for (p, m, r) in zip(p_idx, m_idx, r_idx)
                add(p, x_deps(h))
                add(m, x_deps(h))
                add(m, x_deps(r))
            end
            for (o, r) in zip(budget, r_idx)
                add(o, x_deps(r))
            end
        elseif k === :move
            a_idx, second = ph.tgt, ph.a
            extra = sort!(unique([x_deps(ph.s1); x_deps(ph.s2)]))
            add_many(a_idx, a_idx)
            isempty(second) || add_many(second, a_idx)
            for r in a_idx
                add(r, extra)
            end
            for r in second
                add(r, extra)
            end
        elseif k === :mean
            for (r, x) in zip(ph.tgt, ph.a)
                add(r, x_deps(x))
            end
        elseif k === :coef
            add_many(ph.tgt, ph.a)
        elseif k === :farf
            F = b.FARF[ph.s1+1]
            rf, cf = farfield_row_col(F)
            add_many(rf, cf)
            sl = vec(farfield_setting_slots(F))
            settings = isempty(sl) ? empty_ : sort!(unique(reduce(vcat, [x_deps(x) for x in sl]; init=Int[])))
            if !isempty(settings)
                for r in sort!(unique(rf))
                    add(r, settings)
                end
            end
        end
    end
    return Pattern(n, rows .+ 1, cols .+ 1)
end

# --- tangents ------------------------------------------------------------------------------

struct NoDerivative <: Exception
    what::String
end
Base.showerror(io::IO, e::NoDerivative) = print(io, "No derivative rule for ", e.what)

const LN10 = log(10.0)
const TWO_OVER_SQRT_PI = 1.1283791670955126
const _STAIRS = Set(["ceil", "floor", "round", "fix", "sign", "not", "and", "or", "nand", "nor", "xor", "eps", "pi"])
const _LIVE_OR_REFUSE = Set(["interpolationUseEndValues", "interpolationExtrapolation"])
const _HANDLED = Set(["power", "min", "max", "sum", "mean", "prod"])
const _RULE_KEYS = Set(["abs", "sqrt", "exp", "log", "log10", "log2", "hypot", "sin", "cos", "tan", "asin", "acos",
                        "atan", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh", "erf", "erfc", "atan2", "mod",
                        "rem", "ulp", "rampDown", "rampUp", "smoothDown", "smoothUp", "interpolationUseEndValues",
                        "interpolationExtrapolation", "bq2mole", "mole2bq"])

const MaybeF = Union{Nothing,Float64}

@inline _tmul(a::Float64, d::MaybeF) = d === nothing ? nothing : a * d
@inline function _tadd(a::MaybeF, b::MaybeF)
    a === nothing && return b
    b === nothing && return a
    return a + b
end

"""Zero where every live argument tangent is zero: a column the expression does not reach gets 0."""
function _zero_seed_guard(dA, tangent::MaybeF)
    tangent === nothing && return nothing
    any(d -> d !== nothing, dA) || return tangent
    all(d -> d === nothing || d == 0, dA) && return 0.0
    return tangent
end

_const_exponent(t::TNode) = (t isa TLeaf && t.kind === :K && t.values === nothing) ? t.value : nothing

"""The power rule; `b_one`: the exponent is one number for every element (numpy's short cut in its pow)."""
function _power_rule(a::Float64, b::Float64, da::MaybeF, db::MaybeF, V::Float64, exponent, b_one::Bool)
    if db === nothing && exponent !== nothing
        exponent == 0 && return nothing
        exponent == 1 && return da
        exponent == 2 && return 2 * a * da
        exponent == 0.5 && return da / (2 * V)
        return exponent * kf_jspow1(a, exponent - 1) * da
    end
    pw(x, y) = b_one ? kf_jspow1(x, y) : kf_jspow(x, y)
    db === nothing && return b * pw(a, b - 1) * da
    da === nothing && return a > 0 ? V * clog(a) * db : 0.0
    if a > 0
        return V * ((b / a) * da + clog(a) * db)
    end
    return b * pw(a, b - 1) * da
end

"""Forward-mode tangent of one statement along one leaf, element by element."""
mutable struct Tangent
    tables::Vector{LookupTable}
    values::Vector{Float64}
    seed::Int
    pos::Int
end

function tangent_run!(tg::Tangent, tree::TNode, values::Vector{Float64}, seed::Int)
    tg.values = values
    tg.seed = seed
    tg.pos = 0
    return _twalk(tg, tree)
end

function _tleaf!(tg::Tangent)
    tg.pos += 1
    k = tg.pos
    return tg.values[k], (k == tg.seed ? 1.0 : nothing)
end

function _twalk(tg::Tangent, t::TNode)::Tuple{Float64,MaybeF}
    if t isa TLeaf
        return _tleaf!(tg)
    elseif t isa TNeg
        v, d = _twalk(tg, t.a)
        return -v, (d === nothing ? nothing : -d)
    elseif t isa TBin
        op = t.op
        a, da = _twalk(tg, t.a)
        b, db = _twalk(tg, t.b)
        b_one = op === :^ ? scalar_subtree(t.b) : true
        value = apply_binary(op, a, b, b_one)
        op === :+ && return value, _tadd(da, db)
        if op === :-
            db === nothing && return value, da
            return value, (da === nothing ? -db : da - db)
        end
        if op === :*
            (da === nothing && db === nothing) && return value, nothing
            return value, _tadd(_tmul(b, da), _tmul(a, db))
        end
        if op === :/
            (da === nothing && db === nothing) && return value, nothing
            db === nothing && return value, da / b
            da === nothing && return value, (-(value * db)) / b
            return value, (da - value * db) / b
        end
        if op === :^
            (da === nothing && db === nothing) && return value, nothing
            return value, _zero_seed_guard((da, db), _power_rule(a, b, da, db, value, _const_exponent(t.b), b_one))
        end
        return value, nothing
    elseif t isa TCond
        test, _ = _twalk(tg, t.test)
        a, da = _twalk(tg, t.a)
        b, db = _twalk(tg, t.b)
        chosen = test != 0
        value = chosen ? a : b
        (da === nothing && db === nothing) && return value, nothing
        da = da === nothing ? 0.0 : da
        db = db === nothing ? 0.0 : db
        return value, (chosen ? da : db)
    elseif t isa TTab
        tg.pos += 1                               # the table's index is never live
        index = Int(tg.values[tg.pos])
        arg, darg = _twalk(tg, t.arg)
        table = tg.tables[index+1]
        value = table_at(table, arg)
        darg === nothing && return value, nothing
        return value, table_slope(table, arg) * darg
    elseif t isa TCall
        key = t.key
        n = length(t.args)
        A = Vector{Float64}(undef, n)
        dA = Vector{MaybeF}(undef, n)
        for i in 1:n
            A[i], dA[i] = _twalk(tg, t.args[i])
        end
        ones = (key == "power" || key == "smoothDown" || key == "smoothUp") ? Bool[scalar_subtree(x) for x in t.args] : nothing
        value = call_value(key, A, ones)
        all(d -> d === nothing, dA) && return value, nothing
        return value, _call_tangent(key, A, dA, value, t)
    end
    error("tangent: $(typeof(t))")
end

function _call_tangent(key::String, A::Vector{Float64}, dA::Vector{MaybeF}, V::Float64, t::TCall)
    if key == "power"
        return _zero_seed_guard(dA, _power_rule(A[1], A[2], dA[1], dA[2], V, _const_exponent(t.args[2]),
                                                scalar_subtree(t.args[2])))
    end
    if key == "min" || key == "max"
        out = NaN
        for i in length(A):-1:1
            d = dA[i] === nothing ? 0.0 : dA[i]
            A[i] == V && (out = d)
        end
        return out
    end
    if key == "sum"
        out = nothing
        for d in dA
            out = _tadd(out, d)
        end
        return out
    end
    if key == "mean"
        out = nothing
        for d in dA
            out = _tadd(out, d)
        end
        return out === nothing ? nothing : out / length(A)
    end
    if key == "prod"
        p, dp = A[1], dA[1]
        for i in 2:length(A)
            nxt = p * A[i]
            dp = _tadd(dp === nothing ? nothing : A[i] * dp, _tmul(p, dA[i]))
            p = nxt
        end
        return dp
    end
    if !(key in _RULE_KEYS)
        key in _STAIRS && return nothing
        throw(NoDerivative("$key()"))
    end
    tangent = _rule(key, A, dA, V)
    if tangent === nothing && any(d -> d !== nothing, dA) && key in _LIVE_OR_REFUSE
        throw(NoDerivative("$key() with a table that depends on the state"))
    end
    return _zero_seed_guard(dA, tangent)
end

_z(d::MaybeF) = d === nothing ? 0.0 : d

function _rule(key::String, A::Vector{Float64}, dA::Vector{MaybeF}, V::Float64)::MaybeF
    a = A[1]
    da = dA[1]
    key == "abs" && return kf_sign(a) * da
    key == "sqrt" && return da / (2 * V)
    key == "exp" && return V * da
    key == "log" && return da / a
    key == "log10" && return da / (a * LN10)
    key == "log2" && return da / (a * LN2)
    key == "hypot" && return (s = _tadd(_tmul(A[1], dA[1]), _tmul(A[2], dA[2])); s === nothing ? nothing : s / V)
    key == "sin" && return ccos(a) * da
    key == "cos" && return (-csin(a)) * da
    key == "tan" && return (1 + V * V) * da
    key == "asin" && return da / kf_sqrt(1 - a * a)
    key == "acos" && return (-da) / kf_sqrt(1 - a * a)
    key == "atan" && return da / (1 + a * a)
    key == "sinh" && return ccosh(a) * da
    key == "cosh" && return csinh(a) * da
    key == "tanh" && return (1 - V * V) * da
    key == "asinh" && return da / kf_sqrt(a * a + 1)
    key == "acosh" && return da / kf_sqrt(a * a - 1)
    key == "atanh" && return da / (1 - a * a)
    key == "erf" && return TWO_OVER_SQRT_PI * cexp(-a * a) * da
    key == "erfc" && return -TWO_OVER_SQRT_PI * cexp(-a * a) * da
    if key == "atan2"
        s = _tadd(_tmul(A[2], dA[1]), dA[2] === nothing ? nothing : -(A[1] * dA[2]))
        return s === nothing ? nothing : s / (A[1] * A[1] + A[2] * A[2])
    end
    if key == "mod"
        dA[2] === nothing && return da
        A[2] == 0 && return _z(da)
        return _z(da) - floor(A[1] / A[2]) * dA[2]
    end
    if key == "rem"
        dA[2] === nothing && return da
        A[2] == 0 && return NaN
        return _z(da) - trunc(A[1] / A[2]) * dA[2]
    end
    key == "ulp" && return kf_sign(a) * 2.220446049250313e-16 * da
    if key == "rampDown" || key == "rampUp"
        (dA[1] === nothing || dA[2] !== nothing || dA[3] !== nothing) && return nothing
        sign = key == "rampUp" ? 1.0 : -1.0
        lo = kf_min(A[2], A[3])
        hi = kf_max(A[2], A[3])
        inside = (A[1] > lo) & (A[1] < hi)
        return inside ? sign * dA[1] / (hi - lo) : 0.0
    end
    if key == "smoothDown" || key == "smoothUp"
        (dA[1] === nothing || dA[2] !== nothing || dA[3] !== nothing) && return nothing
        sign = key == "smoothUp" ? 1.0 : -1.0
        pos = A[1] > 0
        return pos ? (sign * 2 * A[3] / A[1]) * V * (1 - V) * dA[1] : 0.0
    end
    if key == "interpolationUseEndValues" || key == "interpolationExtrapolation"
        any(d -> d !== nothing, dA[2:end]) && return nothing
        kind = key == "interpolationUseEndValues" ? "linear" : "extrapolate"
        return interpolate_slope(A, kind) * dA[1]
    end
    if key == "bq2mole"
        return _tadd(dA[1] === nothing ? nothing : kf_bq2mole(dA[1], A[2]),
                     dA[2] === nothing ? nothing : kf_bq2mole(A[1], dA[2]))
    end
    if key == "mole2bq"
        return _tadd(dA[1] === nothing ? nothing : kf_mole2bq(dA[1], A[2]),
                     dA[2] === nothing ? nothing : (-V * dA[2] / A[2]))
    end
    throw(NoDerivative("$key()"))
end

"""Refuses, before any evaluation, a statement whose derivative along a live leaf would need a rule nobody wrote."""
# --- the tangent, laid out flat -------------------------------------------------------------
#
# The walk above computes every node's value again for every leaf it seeds,
# and asks each node what it is as it goes. A statement's tree is laid out
# once instead, its nodes in the order the walk finishes them (children
# first): the values of one element are worked out in a single pass, and a
# leaf's tangent is then carried up the one path from it to the root -- every
# node off that path has no tangent, as the walk finds (a node whose
# arguments all have none has none). Each step does the walk's arithmetic,
# in its order, so the numbers are the walk's to the bit.

const _TP_LEAF = 0x01
const _TP_NEG = 0x02
const _TP_BIN = 0x03
const _TP_COND = 0x04
const _TP_TAB = 0x05
const _TP_CALL = 0x06

"""A statement's tree as the tangent reads it: nodes children first, each
leaf at its position in `tree_leaves`."""
struct TangentTape
    kind::Vector{UInt8}
    node::Vector{TNode}
    args::Vector{Vector{Int}}                  # a node's children, in order
    pos::Vector{Int}                           # a leaf's position (a table's: its index's)
    b_one::Vector{Bool}                        # ^: the exponent is one number for every element
    exponent::Vector{Union{Nothing,Float64}}   # ^: a constant exponent
    ones::Vector{Union{Nothing,Vector{Bool}}}  # power, smoothDown, smoothUp: which arguments are one number
    parent::Vector{Int}
    slot::Vector{Int}                          # which of its parent's children a node is
    leaf_node::Vector{Int}                     # the node at each leaf position (0: a table's index)
end

function TangentTape(tree::TNode)
    tp = TangentTape(UInt8[], TNode[], Vector{Int}[], Int[], Bool[], Union{Nothing,Float64}[],
                     Union{Nothing,Vector{Bool}}[], Int[], Int[], Int[])
    _tape_node!(tp, tree)
    m = length(tp.kind)
    resize!(tp.parent, m)
    resize!(tp.slot, m)
    fill!(tp.parent, 0)
    fill!(tp.slot, 0)
    for k in 1:m, (s, c) in enumerate(tp.args[k])
        tp.parent[c] = k
        tp.slot[c] = s
    end
    return tp
end

function _tape_push!(tp::TangentTape, kind::UInt8, t::TNode, args::Vector{Int}, pos::Int)
    push!(tp.kind, kind)
    push!(tp.node, t)
    push!(tp.args, args)
    push!(tp.pos, pos)
    push!(tp.b_one, true)
    push!(tp.exponent, nothing)
    push!(tp.ones, nothing)
    return length(tp.kind)
end

function _tape_node!(tp::TangentTape, t::TNode)::Int
    if t isa TLeaf
        push!(tp.leaf_node, 0)
        p = length(tp.leaf_node)
        k = _tape_push!(tp, _TP_LEAF, t, Int[], p)
        tp.leaf_node[p] = k
        return k
    elseif t isa TNeg
        c = _tape_node!(tp, t.a)
        return _tape_push!(tp, _TP_NEG, t, [c], 0)
    elseif t isa TBin
        a = _tape_node!(tp, t.a)
        b = _tape_node!(tp, t.b)
        k = _tape_push!(tp, _TP_BIN, t, [a, b], 0)
        if t.op === :^
            tp.b_one[k] = scalar_subtree(t.b)
            tp.exponent[k] = _const_exponent(t.b)
        end
        return k
    elseif t isa TCond
        c1 = _tape_node!(tp, t.test)
        c2 = _tape_node!(tp, t.a)
        c3 = _tape_node!(tp, t.b)
        return _tape_push!(tp, _TP_COND, t, [c1, c2, c3], 0)
    elseif t isa TTab
        push!(tp.leaf_node, 0)                    # the table's index: never live
        p = length(tp.leaf_node)
        c = _tape_node!(tp, t.arg)
        return _tape_push!(tp, _TP_TAB, t, [c], p)
    elseif t isa TCall
        cs = Int[_tape_node!(tp, x) for x in t.args]
        k = _tape_push!(tp, _TP_CALL, t, cs, 0)
        key = t.key
        if key == "power" || key == "smoothDown" || key == "smoothUp"
            tp.ones[k] = Bool[scalar_subtree(x) for x in t.args]
        end
        return k
    end
    error("tangent: $(typeof(t))")
end

"""Every node's value for one element (`vals`: its leaves' values), into `nv`."""
function _tape_values!(nv::AbstractVector{Float64}, tp::TangentTape, vals::AbstractVector{Float64},
                       tables::Vector{LookupTable})
    kind = tp.kind
    args = tp.args
    @inbounds for k in eachindex(kind)
        kd = kind[k]
        if kd == _TP_LEAF
            nv[k] = vals[tp.pos[k]]
        elseif kd == _TP_BIN
            c = args[k]
            nv[k] = apply_binary((tp.node[k]::TBin).op, nv[c[1]], nv[c[2]], tp.b_one[k])
        elseif kd == _TP_NEG
            nv[k] = -nv[args[k][1]]
        elseif kd == _TP_COND
            c = args[k]
            nv[k] = nv[c[1]] != 0 ? nv[c[2]] : nv[c[3]]
        elseif kd == _TP_TAB
            index = Int(vals[tp.pos[k]])
            nv[k] = table_at(tables[index+1], nv[args[k][1]])
        else
            c = args[k]
            A = Float64[nv[x] for x in c]
            nv[k] = call_value((tp.node[k]::TCall).key, A, tp.ones[k])
        end
    end
    return nv
end

"""The tangent of the root along the leaf at position `p`, from the values
`nv` of one element: nothing where the walk finds none."""
function _tape_tangent(tp::TangentTape, p::Int, nv::AbstractVector{Float64}, vals::AbstractVector{Float64},
                       tables::Vector{LookupTable})::MaybeF
    k = tp.leaf_node[p]
    d::Float64 = 1.0
    @inbounds while true
        par = tp.parent[k]
        par == 0 && return d
        s = tp.slot[k]
        kd = tp.kind[par]
        c = tp.args[par]
        r::MaybeF = nothing
        if kd == _TP_BIN
            op = (tp.node[par]::TBin).op
            a = nv[c[1]]
            b = nv[c[2]]
            value = nv[par]
            if op === :+
                r = d
            elseif op === :-
                r = s == 1 ? d : -d
            elseif op === :*
                r = s == 1 ? b * d : a * d
            elseif op === :/
                r = s == 1 ? d / b : (-(value * d)) / b
            elseif op === :^
                da = s == 1 ? d : nothing
                db = s == 2 ? d : nothing
                r = _zero_seed_guard((da, db), _power_rule(a, b, da, db, value, tp.exponent[par], tp.b_one[par]))
            end
        elseif kd == _TP_NEG
            r = -d
        elseif kd == _TP_COND
            if s != 1
                chosen = nv[c[1]] != 0
                r = s == 2 ? (chosen ? d : 0.0) : (chosen ? 0.0 : d)
            end
        elseif kd == _TP_TAB
            index = Int(vals[tp.pos[par]])
            r = table_slope(tables[index+1], nv[c[1]]) * d
        else
            t = tp.node[par]::TCall
            A = Float64[nv[x] for x in c]
            dA = MaybeF[nothing for _ in c]
            dA[s] = d
            r = _call_tangent(t.key, A, dA, nv[par], t)
        end
        r === nothing && return nothing
        d = r
        k = par
    end
end

function _check_differentiable(tree::TNode, live::Set{Int})
    pos = Ref(0)
    function walk(t::TNode)::Bool
        if t isa TLeaf
            pos[] += 1
            return pos[] in live
        elseif t isa TNeg
            return walk(t.a)
        elseif t isa TBin
            a = walk(t.a)
            b = walk(t.b)
            return a || b
        elseif t isa TCond
            a = walk(t.test)
            b = walk(t.a)
            c = walk(t.b)
            return b || c || a
        elseif t isa TTab
            pos[] += 1
            return walk(t.arg)
        elseif t isa TCall
            flags = Bool[walk(a) for a in t.args]
            any(flags) || return false
            key = t.key
            (key in _HANDLED || key in _STAIRS) && return true
            if key in _LIVE_OR_REFUSE && any(flags[2:end])
                throw(NoDerivative("$key() with a table that depends on the state"))
            end
            if key in ("rampDown", "rampUp", "smoothDown", "smoothUp") && any(flags[2:end])
                throw(NoDerivative("$key() whose ends depend on the state"))
            end
            key in _RULE_KEYS || throw(NoDerivative("$key()"))
            return true
        end
        return false
    end
    walk(tree)
end

# --- the analytic Jacobian ---------------------------------------------------------------

const NON_FINITE_AT_START = "the generated Jacobian has a non-finite entry at the starting state (an exact derivative " *
                            "may be infinite where sqrt or log meets an empty compartment), and an infinite entry is " *
                            "not a matrix a solver can factorise"

"""One statement's part in the gradients of the slots that read the state."""
struct StatementPlan
    tree::TNode
    tape::TangentTape
    leaves::Vector{TLeaf}
    width::Int
    outs::Vector{Int}                      # 0-based slots
    y_terms::Vector{Tuple{Int,Vector{Int}}}                         # (leaf, G positions per element)
    x_terms::Vector{Tuple{Int,Vector{Int},Vector{Int},Vector{Int}}} # (leaf, element, G source, G destination)
    multiply::Bool
    own::Vector{Tuple{Int,Int,Int}}        # (element, G lo, G hi) of the slot's own gradient, 1-based
end

"""What a statement of special code contributes."""
struct SpecialPlan
    kind::Symbol           # :farfield, :laplace, :zero, :recorder
    entry::Entry
    path::Any
    dst::Vector{Int}
end

"""A direct term group: J[pos] += value, value from `kind`."""
struct DirectTerm
    kind::Symbol           # :xsign, :negxh, :xh, :negxx, :xx, :const, :farf
    pos::Vector{Int}
    a::Vector{Int}         # slots (1-based) or the path
    f::Vector{Float64}     # signs or coefficients
    s1::Int
    s2::Int
end

"""A chain term group: J[dst] += coef[elem] * G[src]."""
struct ChainTerm
    elem::Vector{Int}
    src::Vector{Int}
    dst::Vector{Int}
    kind::Symbol           # :signdonor, :ones, :negy, :y, :negone, :negxsy, :negxly, :xsy, :xly, :recording
    sign::Vector{Float64}
    idx::Vector{Int}       # 1-based states (or recorders)
    s1::Int                # 1-based slot
    width::Int
end

mutable struct Analytic
    sys::System
    pattern::Pattern
    n::Int
    keep::Union{Nothing,Set{String}}
    g_rows::Vector{Int}
    g_row_of::Dict{Int,Int}
    g_cols::Vector{Vector{Int}}
    g_ptr::Vector{Int}                     # 1-based starts, length rows+1
    g_nnz::Int
    tangent::Tangent
    pat_sorted::Vector{Int}
    pat_order::Vector{Int}
    budget_rows::BitVector
    plans::Vector{Any}
    direct::Vector{DirectTerm}
    chain::Vector{ChainTerm}
    constant::Bool
    G::Vector{Float64}
    work::Vector{Float64}                  # the tape's values: every node of every element
    leafwork::Vector{Float64}              # the leaves' values of every element
end

function _pat_pos(an::Analytic, rows::AbstractVector{Int}, cols::AbstractVector{Int})
    out = Vector{Int}(undef, length(rows))
    n = an.n
    for i in eachindex(rows)
        key = rows[i] * n + cols[i]
        k = searchsortedfirst(an.pat_sorted, key)
        (k <= length(an.pat_sorted) && an.pat_sorted[k] == key) || throw(NoDerivative("an entry outside the Jacobian pattern"))
        out[i] = an.pat_order[k]
    end
    return out
end

function _g_pos(an::Analytic, slot::Int, cols::AbstractVector{Int})
    r = an.g_row_of[slot]
    row_cols = an.g_cols[r]
    return [an.g_ptr[r] + searchsortedfirst(row_cols, c) - 1 for c in cols]
end

function Analytic(sys::System, pattern::Pattern, full::Bool)
    b = sys.builder
    n = sys.nstate
    deps = state_dependencies(sys)
    keep = b.derivative_blocks
    if keep !== nothing
        kept = falses(max(1, b.nalg))
        for a in b.algebraic
            (a.name in keep && a.width > 0) && (kept[a.base+1:a.base+a.width] .= true)
        end
        deps = Dict(s => c for (s, c) in deps if kept[s+1])
    end
    g_rows = sort!(collect(keys(deps)))
    g_row_of = Dict(s => k for (k, s) in enumerate(g_rows))
    g_cols = [deps[s] for s in g_rows]
    g_ptr = ones(Int, length(g_rows) + 1)
    for (k, c) in enumerate(g_cols)
        g_ptr[k+1] = g_ptr[k] + length(c)
    end
    # Where each (row, column) sits among the pattern's values (0-based keys).
    pat_key = (pattern.rowval .- 1) .* n .+ (pattern.col_of .- 1)
    order = sortperm(pat_key; alg=Base.Sort.DEFAULT_STABLE)
    budget_rows = falses(n)
    if b.budget !== nothing && !full
        frm, to = budget_columns(b)
        budget_rows[frm+1:to] .= true
    end
    an = Analytic(sys, pattern, n, keep, g_rows, g_row_of, g_cols, g_ptr, g_ptr[end] - 1,
                  Tangent(sys.data.TAB, Float64[], 0, 0), pat_key[order], order, budget_rows, Any[],
                  DirectTerm[], ChainTerm[], false, zeros(g_ptr[end] - 1), Float64[], Float64[])
    _plan_statements!(an)
    _plan_assembly!(an)
    an.constant = _is_constant(an)
    return an
end

function _plan_statements!(an::Analytic)
    b = an.sys.builder
    moving = b.slot_class
    for a in b.algebraic
        (a.cls != 2 || (an.keep !== nothing && !(a.name in an.keep))) && continue
        for s in b.alg_stmts[a.name]
            if s.special !== nothing
                push!(an.plans, _special_plan(an, a))
                continue
            end
            W = max(1, s.width)
            outs = out_indices(s)
            length(outs) < W && (outs = fill(outs[1], W))
            leaves = tree_leaves(s.tree)
            y_terms = Tuple{Int,Vector{Int}}[]
            x_terms = Tuple{Int,Vector{Int},Vector{Int},Vector{Int}}[]
            for (p, leaf) in enumerate(leaves)
                if leaf.kind === :y
                    idx = _leaf_indices(leaf, W)
                    dst = Int[_g_pos(an, outs[i], [idx[i]])[1] for i in 1:W]
                    push!(y_terms, (p, dst))
                elseif leaf.kind === :X
                    idx = _leaf_indices(leaf, W)
                    any(x -> moving[x+1] == 2, idx) || continue
                    elem, src, dst = Int[], Int[], Int[]
                    for i in 1:W
                        x = idx[i]
                        (moving[x+1] != 2 || !haskey(an.g_row_of, x)) && continue
                        r = an.g_row_of[x]
                        cols = an.g_cols[r]
                        isempty(cols) && continue
                        append!(elem, fill(i, length(cols)))
                        append!(src, an.g_ptr[r] .+ (0:length(cols)-1))
                        append!(dst, _g_pos(an, outs[i], cols))
                    end
                    isempty(elem) || push!(x_terms, (p, elem, src, dst))
                end
            end
            live = Set{Int}([p for (p, _) in y_terms]) ∪ Set{Int}([t[1] for t in x_terms])
            isempty(live) || _check_differentiable(s.tree, live)
            own = Tuple{Int,Int,Int}[]
            if s.multiply
                for (i, o) in enumerate(outs)
                    haskey(an.g_row_of, o) || continue
                    r = an.g_row_of[o]
                    push!(own, (i, an.g_ptr[r], an.g_ptr[r+1]))
                end
            end
            push!(an.plans, StatementPlan(s.tree, TangentTape(s.tree), leaves, W, outs, y_terms, x_terms, s.multiply, own))
        end
    end
end

function _special_plan(an::Analytic, a::Entry)
    b = an.sys.builder
    moving = b.slot_class
    if a.kind == "farfield"
        F = b.FARF[a[:farf_index]+1]
        farfield_is_laplace(F) && return SpecialPlan(:laplace, a, F, Int[])
        for x in vec(farfield_setting_slots(F))
            moving[x+1] == 2 && throw(NoDerivative("a far-field path whose settings depend on the state"))
        end
        rel = farfield_rel_idx(F)
        dst = reduce(vcat, [_g_pos(an, farfield_release_slots(F)[s], rel[s]) for s in 1:farfield_slots(F)]; init=Int[])
        return SpecialPlan(:farfield, a, F, dst)
    end
    rec = get(a, :recorder, nothing)
    rec === nothing && throw(NoDerivative(a.kind))
    if rec.kind == "delay"
        for off in 0:a.width-1
            if moving[rec[:aux]["delay"].base+off+1] == 2
                throw(NoDerivative("a delay whose lag depends on the state: its value slides along the recorded history " *
                                   "as the state changes, and that derivative is not one to guess at"))
            end
        end
        return SpecialPlan(:zero, a, nothing, Int[])
    end
    rec.kind == "snapshot" && return SpecialPlan(:zero, a, nothing, Int[])
    return SpecialPlan(:recorder, a, rec, Int[])
end

function _leaf_value(l::TLeaf, i::Int, y, X, P, t)
    k = l.kind
    k === :y && return y[leaf_index_at(l, i)+1]
    k === :X && return X[leaf_index_at(l, i)+1]
    k === :P && return P[leaf_index_at(l, i)+1]
    k === :K && return leaf_value_at(l, i)
    k === :T && return t
    k === :TAB && return Float64(leaf_index_at(l, i))   # read by the tangent as the table's index
    return 0.0
end

function _gradients!(an::Analytic, y::Vector{Float64}, X::Vector{Float64}, t::Float64)
    G = an.G
    fill!(G, 0.0)
    P = an.sys.P
    tables = an.tangent.tables
    for plan in an.plans
        if plan isa SpecialPlan
            _special_gradient!(an, plan, G, y, X, t)
            continue
        end
        plan = plan::StatementPlan
        W = plan.width
        nl = length(plan.leaves)
        tp = plan.tape
        m = length(tp.kind)
        length(an.work) < m * W && resize!(an.work, m * W)
        length(an.leafwork) < nl * W && resize!(an.leafwork, nl * W)
        NV = reshape(view(an.work, 1:m*W), m, W)
        VALS = reshape(view(an.leafwork, 1:nl*W), nl, W)
        for i in 1:W
            for (p, l) in enumerate(plan.leaves)
                VALS[p, i] = _leaf_value(l, i, y, X, P, t)
            end
            _tape_values!(view(NV, :, i), tp, view(VALS, :, i), tables)
        end
        base = nothing
        if plan.multiply
            factor = Vector{Float64}(undef, W)
            for i in 1:W
                factor[i] = NV[m, i]
            end
            for (i, lo, hi) in plan.own
                f_i = factor[i]
                for q in lo:hi-1
                    G[q] *= f_i
                end
            end
            # The rate as it stood before the availability multiplied it in.
            base = [factor[i] != 0 ? X[plan.outs[i]+1] / factor[i] : 0.0 for i in 1:W]
        end
        d = Vector{Float64}(undef, W)
        for (p, dst) in plan.y_terms
            live = true
            for i in 1:W
                di = _tape_tangent(tp, p, view(NV, :, i), view(VALS, :, i), tables)
                if di === nothing
                    live = false
                    break
                end
                d[i] = di
            end
            live || continue
            base !== nothing && (d .= d .* base)
            for i in 1:W
                G[dst[i]] += d[i]
            end
        end
        for (p, elem, src, dst) in plan.x_terms
            live = true
            for i in 1:W
                di = _tape_tangent(tp, p, view(NV, :, i), view(VALS, :, i), tables)
                if di === nothing
                    live = false
                    break
                end
                d[i] = di
            end
            live || continue
            base !== nothing && (d .= d .* base)
            # np.add.at(G, dst, d[elem] * G[src]): every product formed first, then added in order.
            prods = [d[elem[q]] * G[src[q]] for q in eachindex(elem)]
            for q in eachindex(dst)
                G[dst[q]] += prods[q]
            end
        end
    end
    return G
end

function _special_gradient!(an::Analytic, plan::SpecialPlan, G, y, X, t)
    if plan.kind === :laplace
        farfield_laplace_gradient!(an, plan.path, G, y, X, t)
        return
    elseif plan.kind === :farfield
        F = plan.path
        farfield_refresh!(F, X)
        w = vec(farfield_release_weights(F))
        for q in eachindex(plan.dst)
            G[plan.dst[q]] += w[q]
        end
        return
    elseif plan.kind === :zero
        return
    end
    a = plan.entry
    rec = plan.path
    mem = an.sys.data.MEM
    moving = an.sys.builder.slot_class
    for off in 0:a.width-1
        out = a.base + off
        haskey(an.g_row_of, out) || continue
        if rec.kind == "min_max"
            tgt = rec[:aux]["target"].base + off
            if X[out+1] == X[tgt+1] && haskey(an.g_row_of, tgt) && moving[tgt+1] == 2
                r = an.g_row_of[tgt]
                cols = an.g_cols[r]
                pos = _g_pos(an, out, cols)
                src = collect(an.g_ptr[r]:an.g_ptr[r+1]-1)
                vals = G[src]
                for q in eachindex(pos)
                    G[pos[q]] += vals[q]
                end
            end
        elseif rec.kind == "running_mean"
            el = elapsed_at(mem[rec[:mem]+off+1], t)
            st = rec[:state].base + off
            if el > 0
                G[_g_pos(an, out, [st])[1]] += 1.0 / el
            else
                tgt = rec[:aux]["target"].base + off
                if haskey(an.g_row_of, tgt) && moving[tgt+1] == 2
                    r = an.g_row_of[tgt]
                    cols = an.g_cols[r]
                    pos = _g_pos(an, out, cols)
                    vals = G[an.g_ptr[r]:an.g_ptr[r+1]-1]
                    for q in eachindex(pos)
                        G[pos[q]] += vals[q]
                    end
                end
            end
        end
    end
end

function _plan_assembly!(an::Analytic)
    b = an.sys.builder
    br = an.budget_rows
    moving = b.slot_class
    direct = an.direct
    chain = an.chain
    function add_chain!(rows, slots, kind; sign=Float64[], idx=Int[], s1=0)
        elems, srcs, dsts = Int[], Int[], Int[]
        for (i, (r, x)) in enumerate(zip(rows, slots))
            (br[r+1] || moving[x+1] != 2 || !haskey(an.g_row_of, x)) && continue
            g = an.g_row_of[x]
            cols = an.g_cols[g]
            isempty(cols) && continue
            append!(elems, fill(i, length(cols)))
            append!(srcs, an.g_ptr[g] .+ (0:length(cols)-1))
            append!(dsts, _pat_pos(an, fill(r, length(cols)), cols))
        end
        isempty(elems) || push!(chain, ChainTerm(elems, srcs, dsts, kind, sign, idx, s1, length(rows)))
    end
    for ph in b.phases
        k = ph.kind
        if k === :transfers
            tgt, flux, sign = ph.tgt, ph.a, ph.f
            src_of = fill(-1, b.nflux)
            src_of[b.flux_mbd.+1] = b.flux_mbd_src
            src = src_of[flux.+1]
            rate = b.flux_rate[flux.+1]
            keep = (src .>= 0) .& .!br[tgt.+1]
            if any(keep)
                push!(direct, DirectTerm(:xsign, _pat_pos(an, tgt[keep], src[keep]), rate[keep] .+ 1, sign[keep], 0, 0))
            end
            # d/dX[rate] = sign * (y[src] if multiplying by the donor else 1)
            mbd = src .>= 0
            add_chain!(tgt, rate, :signdonor; sign=sign, idx=[m ? s + 1 : 0 for (m, s) in zip(mbd, src)])
        elseif k === :x
            add_chain!(ph.tgt, ph.a, :ones)
        elseif k === :waste
            p_idx, m_idx, h, r_idx, budget = ph.tgt, ph.a, ph.s1, ph.b, ph.c
            push!(direct, DirectTerm(:negxh, _pat_pos(an, p_idx, p_idx), Int[], Float64[], h + 1, 0))
            push!(direct, DirectTerm(:xh, _pat_pos(an, m_idx, p_idx), Int[], Float64[], h + 1, 0))
            hs = fill(h, length(p_idx))
            add_chain!(p_idx, hs, :negy; idx=p_idx .+ 1)
            add_chain!(m_idx, hs, :y; idx=p_idx .+ 1)
            add_chain!(m_idx, r_idx, :negone)
            isempty(budget) || add_chain!(budget, r_idx, :ones)
        elseif k === :move
            a_idx, second, lam_slot, share_slot = ph.tgt, ph.a, ph.s1, ph.s2
            push!(direct, DirectTerm(:negxx, _pat_pos(an, a_idx, a_idx), Int[], Float64[], lam_slot + 1, share_slot + 1))
            if !isempty(second) && !all(br[second.+1])
                keep = .!br[second.+1]
                push!(direct, DirectTerm(:xx, _pat_pos(an, second[keep], a_idx[keep]), Int[], Float64[], lam_slot + 1,
                                         share_slot + 1))
            end
            ls = fill(lam_slot, length(a_idx))
            ss = fill(share_slot, length(a_idx))
            add_chain!(a_idx, ls, :negxsy; idx=a_idx .+ 1, s1=share_slot + 1)
            add_chain!(a_idx, ss, :negxly; idx=a_idx .+ 1, s1=lam_slot + 1)
            if !isempty(second)
                add_chain!(second, ls, :xsy; idx=a_idx .+ 1, s1=share_slot + 1)
                add_chain!(second, ss, :xly; idx=a_idx .+ 1, s1=lam_slot + 1)
            end
        elseif k === :mean
            add_chain!(ph.tgt, ph.a, :recording; idx=ph.s1 .+ collect(1:length(ph.tgt)))
        elseif k === :coef
            keep = .!br[ph.tgt.+1]
            if any(keep)
                push!(direct, DirectTerm(:const, _pat_pos(an, ph.tgt[keep], ph.a[keep]), Int[], ph.f[keep], 0, 0))
            end
        elseif k === :farf
            F = b.FARF[ph.s1+1]
            rf, cf = farfield_row_col(F)
            push!(direct, DirectTerm(:farf, _pat_pos(an, rf, cf), Int[], Float64[], ph.s1, 0))
        end
    end
end

"""True when df/dy moves with neither the clock nor the state (`isConstant`)."""
function _is_constant(an::Analytic)
    b = an.sys.builder
    any(r -> r[:mem] >= 0, b.recorders) && return false
    any(p -> p[:farf].laplace, b.farf_layout) && return false
    moves(a) = a.name in b.on_state || a.name in b.on_clock
    paths = Set{String}(p.name for p in b.farf_layout if !p[:farf].laplace)
    for W in b.waste_layout
        W[:release_slot].name in b.on_clock || push!(paths, W[:q])
    end
    function bare_release(a)
        (isempty(paths) || isempty(a.asts)) && return false
        get(something(a.block, JDict()), "multiply_by_donor", nothing) !== false && return false
        for ast in a.asts
            (ast isa ERef && isempty(ast.indices)) || return false
            q = resolve_reference(ast.name, a.system, n -> n in paths)
            (q === nothing || !(q in paths)) && return false
        end
        return true
    end
    rates = Entry[]
    for blk in Iterators.flatten((b.project.blocks["transfers"], b.project.blocks["inflows"]))
        a = get(b.alg_by_name, something(get(blk, "qname", nothing), get(blk, "name", nothing)), nothing)
        (a !== nothing && !bare_release(a)) && push!(rates, a)
    end
    append!(rates, b.dydt_slots)
    for p in b.farf_layout, key in FARF_EQUATION_KEYS
        a = get(b.alg_by_name, "$(p.name)#$key", nothing)
        a !== nothing && push!(rates, a)
    end
    for W in b.waste_layout
        push!(rates, W[:hazard_slot], W[:setting]["irf"], W[:setting]["degradation_rate"])
    end
    for D in b.disruption_layout
        push!(rates, D[:lambda_slot])
        append!(rates, D[:shares])
    end
    return !any(moves, rates)
end

"""The Jacobian's values at `(t, y)` into `J`; false where one is not finite."""
function analytic_evaluate!(J::Vector{Float64}, an::Analytic, t::Float64, y::Vector{Float64})
    sys = an.sys
    X = evaluate_for_derivative!(sys, t, y)
    G = an.g_nnz > 0 ? _gradients!(an, y, X, t) : an.G
    fill!(J, 0.0)
    for d in an.direct
        pos = d.pos
        k = d.kind
        if k === :xsign
            @inbounds for q in eachindex(pos)
                J[pos[q]] += d.f[q] * X[d.a[q]]
            end
        elseif k === :negxh
            v = -X[d.s1]
            @inbounds for q in eachindex(pos)
                J[pos[q]] += v
            end
        elseif k === :xh
            v = X[d.s1]
            @inbounds for q in eachindex(pos)
                J[pos[q]] += v
            end
        elseif k === :negxx
            v = -(X[d.s1] * X[d.s2])
            @inbounds for q in eachindex(pos)
                J[pos[q]] += v
            end
        elseif k === :xx
            v = X[d.s1] * X[d.s2]
            @inbounds for q in eachindex(pos)
                J[pos[q]] += v
            end
        elseif k === :const
            @inbounds for q in eachindex(pos)
                J[pos[q]] += d.f[q]
            end
        elseif k === :farf
            F = sys.data.FARF[d.s1+1]
            farfield_refresh!(F, X)
            vals = farfield_values(F)
            @inbounds for q in eachindex(pos)
                J[pos[q]] += vals[q]
            end
        end
    end
    for c in an.chain
        coef = _chain_coef(c, sys, y, X)
        @inbounds for q in eachindex(c.dst)
            J[c.dst[q]] += coef[c.elem[q]] * G[c.src[q]]
        end
    end
    all(isfinite, J) || return false
    return true
end

function _chain_coef(c::ChainTerm, sys::System, y, X)
    w = c.width
    k = c.kind
    k === :signdonor && return [c.idx[i] > 0 ? c.sign[i] * y[c.idx[i]] : c.sign[i] * 1.0 for i in 1:w]
    k === :ones && return ones(w)
    k === :negone && return -ones(w)
    k === :negy && return [-y[c.idx[i]] for i in 1:w]
    k === :y && return [y[c.idx[i]] for i in 1:w]
    k === :negxsy && return [-(X[c.s1] * y[c.idx[i]]) for i in 1:w]
    k === :negxly && return [-(X[c.s1] * y[c.idx[i]]) for i in 1:w]
    k === :xsy && return [X[c.s1] * y[c.idx[i]] for i in 1:w]
    k === :xly && return [X[c.s1] * y[c.idx[i]] for i in 1:w]
    k === :recording && return [sys.data.MEM[c.idx[i]].recording ? 1.0 : 0.0 for i in 1:w]
    error("chain coefficient $k")
end

"""What a run hands its solver about df/dy, and how it was obtained."""
struct JacobianInfo
    available::Bool
    reason::Union{Nothing,String}
    pattern::Union{Nothing,Pattern}
    groups::Union{Nothing,Vector{Vector{Int}}}
    constant::Bool
    analytic::Union{Nothing,Analytic}
    nnz::Int
    colours::Int
    density::Float64
    budget_rows::Union{Nothing,String}
end

"""The Jacobian the solvers are handed: its pattern and colouring, and where the model allows, its values."""
function build_jacobian(sys::System)
    full = full_budget(sys)
    pattern = jacobian_structure(sys, full)
    groups = budgets_apart(colour_columns(pattern), sys.builder, full)
    n = sys.nstate
    nnz_ = pattern_nnz(pattern)
    density = nnz_ / max(1, n * n)
    reason = "differenced through its pattern"
    an = nothing
    available = false
    constant = false
    try
        an = Analytic(sys, pattern, full)
        J = zeros(nnz_)
        ok = try
            analytic_evaluate!(J, an, sys.start_time, initial_state(sys))
        catch
            true      # as the application: the model's arithmetic at the start says nothing here
        finally
            sys.clock_at = NaN
        end
        if ok
            available = true
            reason = nothing
            constant = an.constant
        else
            reason = NON_FINITE_AT_START
            an = nothing
        end
    catch e
        e isa NoDerivative || rethrow()
        reason = "no derivative rule for $(e.what)"
        an = nothing
    end
    budget_rows = (sys.builder.budget !== nothing && available) ? (full ? "exact" : "diagonal") : nothing
    return JacobianInfo(available, reason, pattern, groups, constant, an, nnz_, length(groups), density, budget_rows)
end

"""The `JacobianSpec` a solver takes: the analytic values when there are any, unless the settings ask for differences."""
function jacobian_spec(sys::System, numeric::Bool=false)
    j = sys.jacobian
    (j isa JacobianInfo && j.pattern !== nothing) || return nothing
    if numeric || j.analytic === nothing
        return JacobianSpec(j.pattern, j.groups, nothing, false)
    end
    an = j.analytic
    ev = JacobianEvaluate((vals, t, y) -> analytic_evaluate!(vals, an, t, y))
    return JacobianSpec(j.pattern, j.groups, ev, j.constant)
end

"""The Jacobian of a cloned system: the plans shared, the work space and the system its own."""
function clone_jacobian(j, sys::System)
    j isa JacobianInfo || return j
    an = j.analytic
    an === nothing && return j
    an2 = Analytic(sys, an.pattern, an.n, an.keep, an.g_rows, an.g_row_of, an.g_cols, an.g_ptr, an.g_nnz,
                   Tangent(sys.data.TAB, Float64[], 0, 0), an.pat_sorted, an.pat_order, an.budget_rows, an.plans,
                   an.direct, an.chain, an.constant, zeros(length(an.G)), Float64[], Float64[])
    return JacobianInfo(j.available, j.reason, j.pattern, j.groups, j.constant, an2, j.nnz, j.colours, j.density,
                        j.budget_rows)
end
