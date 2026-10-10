# From equation trees to resolved expression trees.
#
# `resolve` turns a parsed equation into a tree whose leaves are resolved: a
# slot of the state (`:y`), of the parameters (`:P`), of the algebraic values
# (`:X`), a number (`:K`), the clock (`:T`, `:T0`, `:T1`), a lookup table
# (`:TAB`) or an event's expected-value switch (`:DIS`) -- each leaf holding
# one index, or a vector of them, one per element the statement computes.
# Subtrees of numbers alone are folded here, with the arithmetic the
# generated code uses. Statements whose trees have the same shape and that do
# not read one another are merged: their leaves' index vectors concatenated,
# so one loop computes them all.
#
# Indices here are the application's: counted from 0.

abstract type TNode end

const OP_NE = Symbol("~=")
const OP_AND = Symbol("&&")
const OP_OR = Symbol("||")

"""A leaf: one index (or number) for every element, or one shared by all."""
struct TLeaf <: TNode
    kind::Symbol
    index::Int                          # the shared index (y, P, X, TAB, DIS)
    indices::Union{Nothing,Vector{Int}} # one per element, when they differ
    value::Float64                      # the shared number (K)
    values::Union{Nothing,Vector{Float64}}
end
TLeaf(kind::Symbol) = TLeaf(kind, 0, nothing, 0.0, nothing)
TLeaf(kind::Symbol, index::Integer) = TLeaf(kind, Int(index), nothing, 0.0, nothing)
TLeaf(kind::Symbol, indices::AbstractVector{<:Integer}) =
    length(indices) == 1 ? TLeaf(kind, Int(indices[1])) : TLeaf(kind, 0, Vector{Int}(indices), 0.0, nothing)
KLeaf(v::Real) = TLeaf(:K, 0, nothing, Float64(v), nothing)
KLeaf(v::AbstractVector{<:Real}) = length(v) == 1 ? KLeaf(v[1]) : TLeaf(:K, 0, nothing, 0.0, Vector{Float64}(v))

is_vector_leaf(l::TLeaf) = l.indices !== nothing || l.values !== nothing
leaf_width(l::TLeaf) = l.indices !== nothing ? length(l.indices) : l.values !== nothing ? length(l.values) : 1

struct TNeg <: TNode
    a::TNode
end
struct TBin <: TNode
    op::Symbol            # :+ :- :* :/ :^ :< :<= :> :>= :(==) OP_NE OP_AND OP_OR
    a::TNode
    b::TNode
end
struct TCond <: TNode
    test::TNode
    a::TNode
    b::TNode
end
"""A built-in function, by its canonical name."""
struct TCall <: TNode
    key::String
    args::Vector{TNode}
end
"""A lookup table read at an argument."""
struct TTab <: TNode
    leaf::TLeaf
    arg::TNode
end

_k(v) = KLeaf(v)
_fold(t::TNode) = (t isa TLeaf && t.kind === :K && t.values === nothing) ? t.value : nothing

const _BIN_OPS = Dict("+" => :+, "-" => :-, "*" => :*, "/" => :/, "^" => :^, "<" => :<, "<=" => :<=, ">" => :>,
                      ">=" => :>=, "==" => :(==), "~=" => OP_NE, "&&" => OP_AND, "||" => OP_OR)

"""A binary operation on two numbers, as the generated code does it; `b_one`:
the exponent of a power is one number for every element of its statement."""
function apply_binary(op::Symbol, a::Float64, b::Float64, b_one::Bool=true)
    op === :+ && return a + b
    op === :- && return a - b
    op === :* && return a * b
    op === :/ && return a / b
    op === :^ && return b_one ? kf_jspow1(a, b) : kf_jspow(a, b)
    op === :< && return b2f(a < b)
    op === :<= && return b2f(a <= b)
    op === :> && return b2f(a > b)
    op === :>= && return b2f(a >= b)
    op === :(==) && return b2f(a == b)
    op === OP_NE && return b2f(a != b)
    op === OP_AND && return b2f(a != 0 && b != 0)
    op === OP_OR && return b2f(a != 0 || b != 0)
    error("Cannot evaluate operator '$op'")
end

"""A built-in function applied to numbers, as the generated code applies it.
`ones[i]`: argument i is one number for every element of its statement (all
of them when `nothing`), which decides numpy's short cut in a power."""
function call_value(key::String, args::Vector{Float64}, ones::Union{Nothing,Vector{Bool}}=nothing)
    n = length(args)
    if key == "if"
        return args[1] != 0 ? args[2] : (n > 2 ? args[3] : 0.0)
    elseif key == "not"
        return kf_not(args[1])
    elseif key == "min"
        out = args[1]
        for a in args[2:end]
            out = kf_min(out, a)
        end
        return out
    elseif key == "max"
        out = args[1]
        for a in args[2:end]
            out = kf_max(out, a)
        end
        return out
    elseif key == "sum"
        out = args[1]
        for a in args[2:end]
            out = out + a
        end
        return out
    elseif key == "prod"
        out = args[1]
        for a in args[2:end]
            out = out * a
        end
        return out
    elseif key == "mean"
        out = args[1]
        for a in args[2:end]
            out = out + a
        end
        return out / n
    elseif key == "power"
        return (ones === nothing || ones[2]) ? kf_jspow1(args[1], args[2]) : kf_jspow(args[1], args[2])
    elseif key == "smoothDown"
        return kf_smooth_down(args[1], args[2], args[3], ones === nothing || ones[3])
    elseif key == "smoothUp"
        return kf_smooth_up(args[1], args[2], args[3], ones === nothing || ones[3])
    elseif key == "round"
        return kf_round(args[1])
    elseif key == "pi"
        return Float64(pi)
    end
    f = SCALAR_FUNCTIONS[key]
    return f(args)
end

"""Each built-in as a function of a vector of numbers (for folding constants)."""
const SCALAR_FUNCTIONS = Dict{String,Function}(
    "abs" => a -> kf_abs(a[1]), "sqrt" => a -> kf_sqrt(a[1]), "exp" => a -> kf_exp(a[1]),
    "log" => a -> kf_log(a[1]), "log10" => a -> kf_log10(a[1]), "log2" => a -> kf_log2(a[1]),
    "hypot" => a -> kf_hypot(a[1], a[2]), "ceil" => a -> kf_ceil(a[1]), "floor" => a -> kf_floor(a[1]),
    "fix" => a -> kf_fix(a[1]), "sign" => a -> kf_sign(a[1]), "eps" => a -> EPS, "ulp" => a -> kf_ulp(a[1]),
    "mod" => a -> kf_mod(a[1], a[2]), "rem" => a -> kf_rem(a[1], a[2]), "factorial" => a -> kf_factorial(a[1]),
    "binomial" => a -> kf_binomial(a[1], a[2]), "erf" => a -> kf_erf(a[1]), "erfc" => a -> kf_erfc(a[1]),
    "sin" => a -> kf_sin(a[1]), "cos" => a -> kf_cos(a[1]), "tan" => a -> kf_tan(a[1]),
    "asin" => a -> kf_asin(a[1]), "acos" => a -> kf_acos(a[1]), "atan" => a -> kf_atan(a[1]),
    "atan2" => a -> kf_atan2(a[1], a[2]), "sinh" => a -> kf_sinh(a[1]), "cosh" => a -> kf_cosh(a[1]),
    "tanh" => a -> kf_tanh(a[1]), "asinh" => a -> kf_asinh(a[1]), "acosh" => a -> kf_acosh(a[1]),
    "atanh" => a -> kf_atanh(a[1]),
    "and" => a -> b2f(all(x -> x != 0, a)), "or" => a -> b2f(any(x -> x != 0, a)),
    "nand" => a -> 1.0 - b2f(all(x -> x != 0, a)), "nor" => a -> 1.0 - b2f(any(x -> x != 0, a)),
    "xor" => a -> b2f(count(x -> x != 0, a) % 2 == 1),
    "percentile" => a -> kf_percentile(a[1], a[2:end]),
    "interpolationUseEndValues" => a -> interpolate_args(a, "linear"),
    "interpolationExtrapolation" => a -> interpolate_args(a, "extrapolate"),
    "bq2mole" => a -> kf_bq2mole(a[1], a[2]), "mole2bq" => a -> kf_mole2bq(a[1], a[2]),
    "transport_point" => a -> kf_transport_point(a), "transport_sum" => a -> kf_transport_range(a, false),
    "transport_mean" => a -> kf_transport_range(a, true),
    "rampDown" => a -> kf_ramp_down(a[1], a[2], a[3]), "rampUp" => a -> kf_ramp_up(a[1], a[2], a[3]),
    "smoothDown" => a -> kf_smooth_down(a[1], a[2], a[3]), "smoothUp" => a -> kf_smooth_up(a[1], a[2], a[3]),
)

"""Folds a node whose children are all numbers; `nothing` when it cannot."""
function _evaluate_constant(t::TNode)
    if t isa TNeg
        v = _fold(t.a)
        return v === nothing ? nothing : -v
    elseif t isa TBin
        a, b = _fold(t.a), _fold(t.b)
        (a === nothing || b === nothing) && return nothing
        return apply_binary(t.op, a, b)
    elseif t isa TCond
        v = _fold(t.test)
        v === nothing && return nothing
        return _fold(v != 0 ? t.a : t.b)
    elseif t isa TCall
        vals = Float64[]
        for a in t.args
            v = _fold(a)
            v === nothing && return nothing
            push!(vals, v)
        end
        spec = FUNCTION_ARITIES[t.key]
        spec[3] && return nothing
        try
            return call_value(t.key, vals)
        catch
            return nothing      # left for run time, where it raises in place
        end
    end
    return nothing
end

"""
    resolve_tree(ast, ref, call=nothing) -> TNode

The expression tree of a parsed equation, every reference resolved: `ref(name,
indices, node)` gives the leaf a reference reads; `call(name, args)` the tree
of a call the model defines (a table read at an argument), or `nothing`.
"""
function resolve_tree(ast::ENode, ref, call=nothing)
    function walk(node::ENode, depth::Int)
        depth > 20000 && error("This equation is too long or too deeply nested to compile. Split it into expression blocks.")
        node isa ENum && return _k(node.value)
        node isa ERef && return ref(node.name, node.indices, node)
        local out::TNode
        if node isa EUnary
            out = TNeg(walk(node.operand, depth + 1))
        elseif node isa EBinary
            out = TBin(_BIN_OPS[node.op], walk(node.left, depth + 1), walk(node.right, depth + 1))
        elseif node isa ECond
            out = TCond(walk(node.test, depth + 1), walk(node.then, depth + 1), walk(node.otherwise, depth + 1))
        elseif node isa ECall
            name = get(FUNCTION_ALIASES, node.name, node.name)
            args = TNode[walk(a, depth + 1) for a in node.args]
            own = call === nothing ? nothing : call(node.name, args)
            own !== nothing && return own
            haskey(FUNCTION_ARITIES, name) || throw(ArgumentError("Unknown function '$name'"))
            name == "time" && return TLeaf(:T)
            name == "start_time" && return TLeaf(:T0)
            name == "end_time" && return TLeaf(:T1)
            name == "eps" && return _k(2.0^-52)
            name == "pi" && return _k(Float64(pi))
            if name == "if"
                out = TCond(args[1], args[2], length(args) > 2 ? args[3] : _k(0.0))
            else
                out = TCall(name, args)
            end
        else
            error("Cannot emit node type $(typeof(node))")
        end
        v = _evaluate_constant(out)
        return v !== nothing ? _k(v) : out
    end
    return walk(ast, 0)
end

# --- shapes and merging ---------------------------------------------------------------

"""The shape of a tree: its operations and the kinds of its leaves."""
function signature(tree::TNode)
    io = IOBuffer()
    _sig(io, tree)
    return String(take!(io))
end

function _sig(io::IO, t::TNode)
    if t isa TLeaf
        print(io, t.kind)
    elseif t isa TNeg
        print(io, "-(")
        _sig(io, t.a)
        print(io, ')')
    elseif t isa TBin
        print(io, t.op, '(')
        _sig(io, t.a)
        print(io, ',')
        _sig(io, t.b)
        print(io, ')')
    elseif t isa TCond
        print(io, "?(")
        _sig(io, t.test)
        print(io, ',')
        _sig(io, t.a)
        print(io, ',')
        _sig(io, t.b)
        print(io, ')')
    elseif t isa TCall
        print(io, t.key, '(')
        for (i, a) in enumerate(t.args)
            i > 1 && print(io, ',')
            _sig(io, a)
        end
        print(io, ')')
    elseif t isa TTab
        print(io, "tab(")
        _sig(io, t.arg)
        print(io, ')')
    end
end

"""Whether a subtree is one value for every element of its statement: no leaf in it differs from element to element."""
function scalar_subtree(t::TNode)
    t isa TLeaf && return !is_vector_leaf(t)
    t isa TNeg && return scalar_subtree(t.a)
    t isa TBin && return scalar_subtree(t.a) && scalar_subtree(t.b)
    t isa TCond && return scalar_subtree(t.test) && scalar_subtree(t.a) && scalar_subtree(t.b)
    t isa TCall && return all(scalar_subtree, t.args)
    t isa TTab && return !is_vector_leaf(t.leaf) && scalar_subtree(t.arg)
    return true
end

"""Every leaf of a tree, in a fixed order (the order `rebuild` takes)."""
function tree_leaves(tree::TNode)
    out = TLeaf[]
    _leaves!(out, tree)
    return out
end

function _leaves!(out, t::TNode)
    if t isa TLeaf
        push!(out, t)
    elseif t isa TNeg
        _leaves!(out, t.a)
    elseif t isa TBin
        _leaves!(out, t.a)
        _leaves!(out, t.b)
    elseif t isa TCond
        _leaves!(out, t.test)
        _leaves!(out, t.a)
        _leaves!(out, t.b)
    elseif t isa TCall
        for a in t.args
            _leaves!(out, a)
        end
    elseif t isa TTab
        push!(out, t.leaf)
        _leaves!(out, t.arg)
    end
end

"""The same tree with its leaves replaced, in `tree_leaves` order."""
function rebuild(tree::TNode, new::Vector{TLeaf})
    k = Ref(0)
    function walk(t::TNode)
        if t isa TLeaf
            k[] += 1
            return new[k[]]
        elseif t isa TNeg
            return TNeg(walk(t.a))
        elseif t isa TBin
            a = walk(t.a)
            return TBin(t.op, a, walk(t.b))
        elseif t isa TCond
            a = walk(t.test)
            b = walk(t.a)
            return TCond(a, b, walk(t.b))
        elseif t isa TCall
            return TCall(t.key, TNode[walk(a) for a in t.args])
        elseif t isa TTab
            k[] += 1
            leaf = new[k[]]
            return TTab(leaf, walk(t.arg))
        end
        error("rebuild: $(typeof(t))")
    end
    return walk(tree)
end

"""A leaf's index for element `i` (1-based) of a statement of `width` elements."""
@inline leaf_index_at(l::TLeaf, i::Int) = l.indices === nothing ? l.index : l.indices[i]
@inline leaf_value_at(l::TLeaf, i::Int) = l.values === nothing ? l.value : l.values[i]

"""
    merge_leaves(groups) -> Vector{TLeaf}

Leaves of several same-shaped statements, concatenated position by position:
`groups` is a vector of `(leaves, width)`. A leaf that is the same scalar in
every statement stays a scalar; otherwise it becomes one vector covering every
element of every statement, in order.
"""
function merge_leaves(groups::Vector{Tuple{Vector{TLeaf},Int}})
    first_ = groups[1][1]
    out = TLeaf[]
    for i in eachindex(first_)
        leaf = first_[i]
        kind = leaf.kind
        if kind in (:T, :T0, :T1)
            push!(out, leaf)
            continue
        end
        if kind === :K
            same = all(g -> g[1][i].values === nothing, groups) &&
                   all(g -> (g[1][i].value == leaf.value) || (isnan(g[1][i].value) && isnan(leaf.value)), groups)
            if same
                push!(out, leaf)
                continue
            end
            vals = Float64[]
            for (ls, w) in groups
                l = ls[i]
                l.values === nothing ? append!(vals, fill(l.value, w)) : append!(vals, l.values)
            end
            push!(out, TLeaf(:K, 0, nothing, 0.0, vals))
            continue
        end
        same = all(g -> g[1][i].indices === nothing && g[1][i].index == leaf.index, groups)
        if same
            push!(out, leaf)
            continue
        end
        idx = Int[]
        for (ls, w) in groups
            l = ls[i]
            l.indices === nothing ? append!(idx, fill(l.index, w)) : append!(idx, l.indices)
        end
        push!(out, TLeaf(kind, 0, idx, 0.0, nothing))
    end
    return out
end

# --- reading tables -------------------------------------------------------------------

"""`interpolationUseEndValues(XI, X1, Y1, X2, Y2, ...)` and its sibling."""
function interpolate_args(args::AbstractVector{Float64}, interpolation::String)
    key = args[1]
    rest = args[2:end]
    if length(rest) < 2 || length(rest) % 2 != 0
        throw(LookupError("interpolation needs a lookup value and then x, y pairs; got $(length(rest)) value(s) after it"))
    end
    pairs = Any[Any[rest[i], rest[i+1]] for i in 1:2:length(rest)]
    return table_at(LookupTable(pairs, interpolation), key)
end

function interpolate_slope(args::AbstractVector{Float64}, interpolation::String)
    key = args[1]
    rest = args[2:end]
    (length(rest) < 2 || length(rest) % 2 != 0) && return 0.0
    pairs = Any[Any[rest[i], rest[i+1]] for i in 1:2:length(rest)]
    return table_slope(LookupTable(pairs, interpolation), key)
end
