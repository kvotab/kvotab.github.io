# Where a value that is not a number came from: a port of the application's
# src/sim/nonfinite.js (the Python engine's engine/nonfinite.py).
#
# A run that stops on a NaN or an infinity used to say when and nothing else.
# The state the solver held is known, so the equations are worked out once more
# there and a value that is not a number is followed back the way it came: from
# the compartments whose derivative it reached, through the transfers that
# carried it, and down through each equation a part at a time to the one
# operation that made it out of numbers -- zero divided by zero, the log of a
# negative, an overflow -- and the values that operation read. It is followed
# by value, not by name, and a part of an equation is resolved by the builder's
# own resolvers at the element's tuple and worked out with the code
# generator's own arithmetic. `start_warnings` says the same before a run.
#
# The words are the application's, letter for letter. Indices are the
# builder's, counted from 0; `k` counts the algebraic blocks from 1.

const _NF_MOST_STEPS = 500
const _NF_MOST_FOLLOWED = 2000
const _NF_MOST_NAMED = 3
const _NF_MOST_READS = 6
const _NF_LONGEST_PART = 240
const _NF_ASSEMBLY_PREFIX = r"^(waste_package|event|farfield):"
const _NF_NON_NUMBERS = r"not a number|non-finite|not-a-number|infinite|\bNaN\b"i

_nf_read_by_assembly(a::Entry) =
    a.kind in ("transfer", "inflow", "compartment:dydt", "waste_package", "farfield", "running_mean:target") ||
    occursin(_NF_ASSEMBLY_PREFIX, a.kind)

"""A slot of a block's own -- `T#limit`, `M#target` -- answers as the block."""
_nf_block_of(name) = String(split(String(name), '#'; limit=2)[1])

_nf_finite(v) = v !== nothing && isfinite(v)

# --- one element of an equation, taken apart ---------------------------------------------

struct _NFEquation
    sys::System
    ast::ENode
    ref::Any
    call::Any
    locate::Any
    values::IdDict{Any,Union{Nothing,Float64}}
end

function _nf_equation_at(sys::System, k::Int, off::Int)
    b = sys.builder
    a = b.algebraic[k]
    isempty(a.asts) && return nothing
    ast = a.uniform ? a.asts[1] : a.asts[off+1]
    tup = isempty(a.dims) ? Tup() : tuple_by_list(b.space, a.dims, off)
    # `make_resolver`'s, without its note of a block reading itself: the builder
    # is shared by every clone a probabilistic run makes, and is written only
    # while it builds.
    ref = function (name, indices, node=nothing)
        kind, _, index = locate(b, a, a.dims, nothing, tup, name, indices, node)
        kind === :table && error("'$name' is a lookup table with an argument")
        return TLeaf(_ARRAY_OF[kind], index)
    end
    call = make_call_resolver(b, a, a.dims, nothing, tup)
    locate_fn = node -> locate(b, a, a.dims, nothing, tup, node.name, node.indices, node)
    return _NFEquation(sys, ast, ref, call, locate_fn, IdDict{Any,Union{Nothing,Float64}}())
end

const _NF_ARRAY_OF = Dict(:state => "y", :param => "P", :alg => "X")

function _nf_read(eq::_NFEquation, node::ENode)
    kind, _, index = eq.locate(node)
    return (array=get(_NF_ARRAY_OF, kind, nothing), offset=Int(index))
end

function _nf_value(eq::_NFEquation, node::ENode, t::Float64, y::Vector{Float64})
    haskey(eq.values, node) && return eq.values[node]
    v = try
        Float64(_nf_tree_value(resolve_tree(node, eq.ref, eq.call), t, y, eq.sys))
    catch
        nothing     # a part that will not evaluate is one not followed
    end
    eq.values[node] = v
    return v
end

"""A resolved tree's value for one element, with the code generator's arithmetic."""
function _nf_tree_value(t::TNode, time::Float64, y::Vector{Float64}, sys::System)::Float64
    if t isa TLeaf
        k = t.kind
        k === :K && return t.value
        k === :T && return time
        k === :T0 && return sys.data.T0
        k === :T1 && return sys.data.T1
        k === :y && return y[t.index+1]
        k === :P && return sys.P[t.index+1]
        k === :X && return sys.X[t.index+1]
        k === :DIS && return sys.data.DIS[t.index+1]
        error("A $k leaf is not a value")
    elseif t isa TNeg
        return -_nf_tree_value(t.a, time, y, sys)
    elseif t isa TBin
        return apply_binary(t.op, _nf_tree_value(t.a, time, y, sys), _nf_tree_value(t.b, time, y, sys))
    elseif t isa TCond
        return _nf_tree_value(_nf_tree_value(t.test, time, y, sys) != 0.0 ? t.a : t.b, time, y, sys)
    elseif t isa TCall
        args = Float64[_nf_tree_value(a, time, y, sys) for a in t.args]
        f = get(_INLINE, t.key, nothing)
        f !== nothing && return Float64(getfield(@__MODULE__, f)(args...))
        return Float64(call_value(t.key, args))
    elseif t isa TTab
        return Float64(table_at(sys.data.TAB[t.leaf.index+1], _nf_tree_value(t.arg, time, y, sys)))
    end
    error("Cannot evaluate $(typeof(t))")
end

# --- following a value back --------------------------------------------------------------

mutable struct _NFAt
    sys::System
    t::Float64
    state::Vector{Float64}
    d::Vector{Float64}
    X::Vector{Float64}
    owner::Vector{Int}          # the algebraic block (from 1) of each slot (from 0, at +1); 0 for none
    memo::Dict{Tuple{Int,Int},Any}
end

function _nf_at(at::_NFAt, offset::Int)
    (offset < 0 || offset >= length(at.owner)) && return nothing
    k = at.owner[offset+1]
    k == 0 && return nothing
    return (k, offset - at.sys.builder.algebraic[k].base)
end

function _nf_root_of(at::_NFAt, k::Int, off::Int, depth::Int=0)
    key = (k, off)
    if haskey(at.memo, key)
        found = at.memo[key]
        return found === nothing ? Dict{Symbol,Any}(:k => k, :off => off) : found
    end
    at.memo[key] = nothing
    found = _nf_follow(at, k, off, depth)
    at.memo[key] = found
    return found
end

function _nf_follow(at::_NFAt, k::Int, off::Int, depth::Int)
    here = Dict{Symbol,Any}(:k => k, :off => off)
    depth > _NF_MOST_STEPS && return here
    a = at.sys.builder.algebraic[k]
    X = at.X
    # A block that remembers has no equation; what it is not a number of, if
    # anything now, is its target.
    rec = get(a, :recorder, nothing)
    if rec !== nothing && rec.kind != "trigger" && haskey(rec[:aux], "target")
        target = rec[:aux]["target"]
        nxt = isfinite(X[target.base+off+1]) ? nothing : _nf_at(at, target.base + off)
        return nxt === nothing ? here : _nf_root_of(at, nxt[1], nxt[2], depth + 1)
    end
    eq = try
        _nf_equation_at(at.sys, k, off)
    catch
        nothing
    end
    eq === nothing && return here
    part = _nf_innermost(eq, at.t, at.state)
    if part === nothing
        # The equation comes to a number and the slot does not: the slot is the
        # rate times an availability, and it is that.
        avail = get(a, :availability, nothing)
        if avail !== nothing
            for op in values(avail.operands)
                nxt = isfinite(X[op.base+off+1]) ? nothing : _nf_at(at, op.base + off)
                nxt === nothing || return _nf_root_of(at, nxt[1], nxt[2], depth + 1)
            end
        end
        return here
    end
    if part.node isa ERef
        read = try
            _nf_read(eq, part.node)
        catch
            nothing
        end
        nxt = (read !== nothing && read.array == "X") ? _nf_at(at, read.offset) : nothing
        nxt === nothing || return _nf_root_of(at, nxt[1], nxt[2], depth + 1)
        return merge(here, Dict{Symbol,Any}(:eq => eq, :part => part, :read => read))
    end
    return merge(here, Dict{Symbol,Any}(:eq => eq, :part => part))
end

function _nf_evaluated(sys::System, t::Float64, y::AbstractVector)
    n = sys.nstate
    length(y) < n && return nothing
    state = Vector{Float64}(y[1:n])
    d = zeros(n)
    X = try
        rhs!(sys, d, t, state)
        # Every slot, not only those the derivative runs: a block the
        # derivative reads is in both, and its value is the same in either.
        evaluate_algebraic!(sys, t, state)
    catch
        return nothing
    end
    owner = zeros(Int, max(1, sys.nalg))
    for (k, a) in enumerate(sys.builder.algebraic)
        a.width > 0 && (owner[a.base+1:a.base+a.width] .= k)
    end
    return _NFAt(sys, t, state, d, X, owner, Dict{Tuple{Int,Int},Any}())
end

"""The node of an equation that is not a number while every operand it was
worked out from is one -- the operation that made it -- and its operands."""
function _nf_innermost(eq::_NFEquation, t::Float64, y::Vector{Float64})
    value = node -> _nf_value(eq, node, t, y)
    node = eq.ast
    v = value(node)
    (v === nothing || isfinite(v)) && return nothing
    while true
        parts = _nf_operands(node, value)
        i = findfirst(p -> p.value !== nothing && !isfinite(p.value), parts)
        i === nothing && return (node=node, value=v, operands=parts)
        node, v = parts[i].node, parts[i].value
    end
end

"""The operands a node was worked out from, with their values: only the branch a conditional took."""
function _nf_operands(node::ENode, value)
    of(n) = (node=n, value=value(n))
    if node isa EUnary
        return [of(node.operand)]
    elseif node isa EBinary
        return [of(node.left), of(node.right)]
    elseif node isa ECond
        test = of(node.test)
        test.value === nothing && return [test]
        return [test, of(test.value != 0 ? node.then : node.otherwise)]
    elseif node isa ECall
        args = node.args
        if node.name == "if" && length(args) >= 2
            test = of(args[1])
            test.value === nothing && return [test]
            taken = test.value != 0 ? args[2] : (length(args) > 2 ? args[3] : nothing)
            return taken === nothing ? [test] : [test, of(taken)]
        end
        return [of(a) for a in args]
    end
    return NamedTuple{(:node, :value),Tuple{ENode,Union{Nothing,Float64}}}[]
end

"""The blocks behind the values that are not numbers which the assembly of the
derivative reads, the flows that carry them, and which flows each reach."""
function _nf_from_assembly(at::_NFAt)
    flows_seen = OrderedDict{String,Dict{String,Any}}()
    flows_of = Dict{Int,Vector{String}}()
    roots = Any[]
    followed = 0
    for (k, a) in enumerate(at.sys.builder.algebraic)
        _nf_read_by_assembly(a) || continue
        flow = a.kind in ("transfer", "inflow") ? _nf_block_of(a.name) : nothing
        for off in 0:a.width-1
            isfinite(at.X[a.base+off+1]) && continue
            if flow !== nothing
                seen = get!(() -> Dict{String,Any}("name" => flow, "kind" => a.kind, "count" => 0), flows_seen, flow)
                seen["count"] += 1
            end
            followed += 1
            followed > _NF_MOST_FOLLOWED && continue
            r = _nf_root_of(at, k, off)
            push!(roots, r)
            if flow !== nothing && a.kind == "transfer"
                via = get!(() -> String[], flows_of, r[:k])
                flow in via || push!(via, flow)
            end
        end
    end
    return (flows=collect(values(flows_seen)), blocks=_nf_by_root_block(roots), flows_of=flows_of)
end

"""The blocks behind the values that are not numbers which only results read."""
function _nf_from_the_rest(at::_NFAt, stopping::Set{Int})
    roots = Any[]
    followed = 0
    for (k, a) in enumerate(at.sys.builder.algebraic)
        # The slots behind a block -- a recorder's target, an availability --
        # answer for it: the block's own slot is the one to follow.
        (a.hidden || _nf_read_by_assembly(a)) && continue
        for off in 0:a.width-1
            isfinite(at.X[a.base+off+1]) && continue
            followed += 1
            followed > _NF_MOST_FOLLOWED && return _nf_by_root_block(roots)
            r = _nf_root_of(at, k, off)
            r[:k] in stopping || push!(roots, r)
        end
    end
    return _nf_by_root_block(roots)
end

"""One root per block, at its first element, with which elements it has, in the order of the blocks."""
function _nf_by_root_block(roots)
    by_block = Dict{Int,Any}()
    for r in roots
        had = get(by_block, r[:k], nothing)
        if had === nothing
            by_block[r[:k]] = Dict{Symbol,Any}(:first => r, :offs => Set{Int}([r[:off]]))
        else
            push!(had[:offs], r[:off])
            r[:off] < had[:first][:off] && (had[:first] = r)
        end
    end
    return [by_block[k] for k in sort!(collect(keys(by_block)))]
end

"""The run's states that are not numbers, a block at a time, in the order of the state vector."""
function _nf_group_by(entries, n::Int, bad)
    out = Dict{String,Any}[]
    for s in entries
        count = 0
        first = -1
        for i in 0:s.width-1
            at = s.base + i
            (at >= n || !bad(at)) && continue
            first < 0 && (first = i)
            count += 1
        end
        count == 0 && continue
        push!(out, Dict{String,Any}("name" => _nf_block_of(s.name), "kind" => isempty(s.kind) ? "compartment" : s.kind,
                                    "count" => count, "first" => first, "at" => s.base + first,
                                    "dims" => collect(String, s.dims)))
    end
    return out
end

function _nf_entry_at(entries, offset::Int)
    for e in entries
        e.base <= offset < e.base + e.width && return e
    end
    return nothing
end

function _nf_describe_root(block, at::_NFAt)
    first, offs = block[:first], block[:offs]
    b = at.sys.builder
    a = b.algebraic[first[:k]]
    index = isempty(a.dims) ? nothing : tuple_by_list(b.space, a.dims, first[:off])
    root = Dict{String,Any}("name" => _nf_block_of(a.name), "kind" => a.kind, "index" => index,
                            "count" => length(offs), "value" => at.X[a.base+first[:off]+1], "part" => nothing,
                            "source" => nothing)
    part = get(first, :part, nothing)
    part === nothing && return root
    read = get(first, :read, nothing)
    if part.node isa ERef && read !== nothing
        # A state or a parameter that is not a number: what the equation read.
        holder = read.array == "y" ? _nf_entry_at(b.states, read.offset) :
                 read.array == "P" ? _nf_entry_at(b.param_layout, read.offset) : nothing
        if holder !== nothing
            off = read.offset - holder.base
            root["source"] = Dict{String,Any}(
                "name" => _nf_block_of(holder.name),
                "kind" => read.array == "y" ? (isempty(holder.kind) ? "compartment" : holder.kind) : "parameter",
                "index" => isempty(holder.dims) ? nothing : tuple_by_list(b.space, holder.dims, off),
                "value" => part.value)
            return root
        end
    end
    eq = first[:eq]
    root["part"] = Dict{String,Any}(
        "text" => equation_text(part.node),
        "worked" => _nf_worked_text(part.node, part.operands, part.value),
        "reads" => _nf_reads_of(part.node, eq, at.t, at.state))
    return root
end

"""The references inside a part, each once, with the value it read."""
function _nf_reads_of(node::ENode, eq::_NFEquation, t::Float64, y::Vector{Float64})
    out = OrderedDict{String,Union{Nothing,Float64}}()
    function walk(n)
        if n isa ERef
            text = equation_text(n)
            haskey(out, text) || (out[text] = _nf_value(eq, n, t, y))
            return
        end
        foreach(walk, _nf_children(n))
    end
    walk(node)
    return [(text=k, value=v) for (k, v) in out]
end

function _nf_children(n::ENode)
    n isa EUnary && return ENode[n.operand]
    n isa EBinary && return ENode[n.left, n.right]
    n isa ECond && return ENode[n.test, n.then, n.otherwise]
    n isa ECall && return ENode[n.args...]
    return ENode[]
end

# --- what is found -----------------------------------------------------------------------

"""
    non_finite_at(sys, t, y) -> Dict or nothing

Where the derivative at `(t, y)` stops being a number, and why (`nonFiniteAt`).
"""
function non_finite_at(sys::System, t::Real, y::AbstractVector)
    at = _nf_evaluated(sys, Float64(t), y)
    at === nothing && return nothing
    states = _nf_group_by(sys.builder.states, sys.nstate, i -> !isfinite(at.d[i+1]) || !isfinite(at.state[i+1]))
    isempty(states) && return nothing
    found = _nf_from_assembly(at)
    roots = [_nf_describe_root(b, at) for b in found.blocks]
    root = isempty(roots) ? nothing : roots[1]
    others = String[]
    for r in roots[2:end]
        (r["name"] in others || (root !== nothing && r["name"] == root["name"])) || push!(others, r["name"])
    end
    return Dict{String,Any}("t" => Float64(t), "states" => states, "state_count" => sum(g["count"] for g in states),
                            "flows" => found.flows, "root" => root, "others" => others)
end

"""
    start_warnings(sys, t0, y0) -> Vector

What a run would trip over, said before one is run (`startWarnings`): every
block whose value at the start is not a number of its own making,
`Dict("block", "message", "stops")` each, in the order the equations are worked
out.
"""
start_warnings(sys::System, t0::Real, y0::AbstractVector) = lock(() -> _nf_start_warnings(sys, t0, y0), _NF_LOCK)

function _nf_start_warnings(sys::System, t0::Real, y0::AbstractVector)
    out = Dict{String,Any}[]
    for g in _nf_group_by(sys.builder.states, sys.nstate, i -> !isfinite(y0[i+1]))
        g["kind"] == "compartment" || continue
        push!(out, Dict{String,Any}("block" => g["name"], "stops" => true,
                                    "message" => "Its initial value comes to $(_nf_number(y0[g["at"]+1]))" *
                                                 "$(_nf_where_text(g, sys)), so a run cannot start."))
    end
    isempty(out) || return out
    at = _nf_evaluated(sys, Float64(t0), y0)
    at === nothing && return out
    found = _nf_from_assembly(at)
    stopping = Set{Int}(b[:first][:k] for b in found.blocks)
    for b in found.blocks
        r = _nf_describe_root(b, at)
        via = get(found.flows_of, b[:first][:k], String[])
        through = isempty(via) ? "" : ", through $(length(via) == 1 ? "the transfer" : "the transfers") $(_nf_list(via)),"
        push!(out, Dict{String,Any}("block" => r["name"], "stops" => true,
                                    "message" => "$(_nf_root_sentence(r, true)) The run reads it$through so it will " *
                                                 "stop at its first step."))
    end
    for b in _nf_from_the_rest(at, stopping)
        r = _nf_describe_root(b, at)
        what = r["count"] > 1 ? "these values" : "this value"
        push!(out, Dict{String,Any}("block" => r["name"], "stops" => false,
                                    "message" => "$(_nf_root_sentence(r, true)) Only results read it, so a run goes " *
                                                 "on, with $what at its first point."))
    end
    return out
end

# --- the words ---------------------------------------------------------------------------

"""The message for a run that stopped on a value that is not a number."""
function non_finite_message(found, sys::System, step=nothing)
    lines = step === nothing ?
            ["The simulation produced a value that is not a number at t=$(js_text(found["t"]))."] :
            ["The simulation produced a value that is not a number at t=$(js_text(step.from)).",
             "The state it held there gives numbers; a step of $(_nf_number(step.h)) past it does not."]
    found["root"] === nothing || push!(lines, _nf_root_sentence(found["root"], false))
    push!(lines, _nf_reach_text(found, sys))
    others = found["others"]
    if !isempty(others)
        first, rest = others[1], others[2:end]
        push!(lines, isempty(rest) ? "$first starts one of its own as well." :
                     "$first and $(length(rest)) more $(length(rest) == 1 ? "block" : "blocks") start one of their " *
                     "own as well.")
    end
    return join(lines, " ")
end

function _nf_root_sentence(r, at_start::Bool)
    more = r["count"] - 1
    others = more > 0 ? " (and $more more of its indices)" : ""
    lead = at_start ?
           "Comes to $(_nf_number(r["value"])) at the start$(r["index"] === nothing ? "" : " at " * describe_tuple(r["index"]))$others" :
           "It starts in $(r["name"])$(_nf_index_text(r["index"]))$others"
    s = r["source"]
    if s !== nothing
        what = s["kind"] == "parameter" ? "the parameter $(s["name"])$(_nf_index_text(s["index"])), which is" :
               s["kind"] == "compartment" ? "the compartment $(s["name"])$(_nf_index_text(s["index"])), which holds" :
               "the state $(s["name"])$(_nf_index_text(s["index"])), which is"
        at_start && return "$lead: it reads $what $(_nf_number(s["value"]))."
        return "It starts in $what $(_nf_number(s["value"])), read by $(r["name"])$(_nf_index_text(r["index"]))$others."
    end
    p = r["part"]
    p === nothing || return "$lead: $(p["text"]) comes to $(p["worked"])$(_nf_reads_text(p["reads"]))."
    return at_start ? "$lead." : "$lead, which comes to $(_nf_number(r["value"]))."
end

function _nf_reach_text(found, sys::System)
    states, state_count, flows = found["states"], found["state_count"], found["flows"]
    named = String[]
    for s in states
        index = (length(states) == 1 && s["count"] == 1 && !isempty(s["dims"])) ?
                _nf_index_text(tuple_by_list(sys.builder.space, s["dims"], s["first"])) : ""
        push!(named, "$(s["name"])$index")
    end
    noun = all(s -> s["kind"] == "compartment", states) ? "compartment" : "block"
    text = length(states) == 1 ?
           "It reaches the $noun $(named[1])$(state_count > 1 ? " ($state_count states)" : "")" :
           "It reaches $(length(states)) $(noun)s, $state_count states in all: $(_nf_list(named))"
    if !isempty(flows)
        transfers = [f["name"] for f in flows if f["kind"] == "transfer"]
        inflows = [f["name"] for f in flows if f["kind"] == "inflow"]
        parts = String[]
        isempty(transfers) ||
            push!(parts, "$(length(transfers) == 1 ? "the transfer" : "the transfers") $(_nf_list(transfers))")
        isempty(inflows) || push!(parts, "$(length(inflows) == 1 ? "the inflow" : "the inflows") $(_nf_list(inflows))")
        text *= ", through $(join(parts, " and "))"
    end
    return "$text."
end

"""Up to three names, then how many more."""
function _nf_list(names)
    n = length(names)
    n <= _NF_MOST_NAMED && return n < 2 ? join(names) : "$(join(names[1:end-1], ", ")) and $(names[end])"
    return "$(join(names[1:_NF_MOST_NAMED], ", ")) and $(n - _NF_MOST_NAMED) more"
end

"""What an operation read, the values most likely to be the cause first."""
function _nf_reads_text(reads)
    isempty(reads) && return ""
    telling(v) = v === nothing || !isfinite(v) || v <= 0
    shown = length(reads) <= _NF_MOST_READS ? collect(1:length(reads)) :
            [[i for i in eachindex(reads) if telling(reads[i].value)]; [i for i in eachindex(reads) if !telling(reads[i].value)]][1:_NF_MOST_READS]
    keep = Set(shown)
    ordered = [reads[i] for i in eachindex(reads) if i in keep]
    items = ["$(r.text) = $(r.value === nothing ? "?" : _nf_number(r.value))" for r in ordered]
    more = length(reads) - length(ordered)
    more > 0 && return ", with $(join(items, ", ")) and $more more"
    return ", with " * (length(items) < 2 ? join(items) : "$(join(items[1:end-1], ", ")) and $(items[end])")
end

_nf_index_text(index) = (index === nothing || isempty(index)) ? "" : " [$(describe_tuple(index))]"

function _nf_where_text(g, sys::System)
    isempty(g["dims"]) && return ""
    more = g["count"] - 1
    tail = more > 0 ? " (and $more more of its indices)" : ""
    return " at $(describe_tuple(tuple_by_list(sys.builder.space, g["dims"], g["first"])))$tail"
end

"""A value as it is shown: four figures, written as JavaScript writes a number."""
function _nf_number(v::Real)
    f = Float64(v)
    isfinite(f) || return js_text(f)
    f == 0 && return "0"
    return js_text(parse(Float64, js_to_exponential(f, 3)))
end

"""An operation with its operands' values in place of their equations: `0/0`, `log(0)`."""
function _nf_worked_text(node::ENode, parts, value::Float64)
    function v(i)
        i > length(parts) && return "?"
        x = parts[i].value
        x === nothing && return "?"
        s = _nf_number(x)
        return x < 0 ? "($s)" : s
    end
    big = _nf_overflows(parts, value) ? ", too large for a number" : ""
    node isa EBinary && return "$(v(1))$(_nf_op_text(node.op))$(v(2))$big"
    node isa EUnary && return "-$(v(1))"
    if node isa ECall
        isempty(parts) && return _nf_number(value)
        args = join((_nf_number(p.value === nothing ? NaN : p.value) for p in parts), ", ")
        return "$(node.name)($args)$big"
    end
    return _nf_number(value)
end

"""Whether numbers went in and an infinity came out: an overflow rather than a domain error."""
_nf_overflows(parts, value) = isinf(value) && all(p -> p.value !== nothing && isfinite(p.value), parts) &&
                              !any(p -> p.value == 0, parts)

_nf_op_text(op::AbstractString) = op in ("*", "/", "^") ? String(op) : " $op "

# --- equations back to text --------------------------------------------------------------

const _NF_PRECEDENCE = Dict("||" => 1, "&&" => 2, "==" => 3, "~=" => 3, "<" => 4, "<=" => 4, ">" => 4, ">=" => 4,
                            "+" => 5, "-" => 5, "*" => 6, "/" => 6)
const _NF_UNARY = 7
const _NF_POWER = 8
const _NF_ATOM = 10

function _nf_precedence(node::ENode)
    node isa EBinary && return node.op == "^" ? _NF_POWER : get(_NF_PRECEDENCE, node.op, 0)
    node isa EUnary && return _NF_UNARY
    node isa ECond && return 0
    node isa ENum && return node.value < 0 ? _NF_UNARY : _NF_ATOM
    return _NF_ATOM
end

"""A tree written back out as an equation (`equationText`)."""
function equation_text(node::ENode)
    text = _nf_write(node)
    chars = collect(text)
    length(chars) <= _NF_LONGEST_PART && return text
    keep = div(_NF_LONGEST_PART - 1, 2)
    return String(chars[1:keep]) * "…" * String(chars[end-keep+1:end])
end

function _nf_write(node::ENode)
    wrap(child, tighter) = _nf_precedence(child) < tighter ? "($(_nf_write(child)))" : _nf_write(child)
    if node isa ENum
        return js_text(node.value) * (node.unit === nothing ? "" : "[$(node.unit)]")
    elseif node isa ERef
        idx = node.indices isa AbstractDict ? collect(values(node.indices)) : collect(node.indices)
        return node.name * join("[$(i === nothing ? "" : i)]" for i in idx)
    elseif node isa EUnary
        return "-" * wrap(node.operand, _NF_POWER)
    elseif node isa EBinary
        if node.op == "^"
            r = node.right
            exponent = (r isa EUnary && _nf_precedence(r.operand) >= _NF_ATOM) ? _nf_write(r) : wrap(r, _NF_ATOM)
            return "$(wrap(node.left, _NF_POWER))^$exponent"
        end
        p = get(_NF_PRECEDENCE, node.op, 0)
        return "$(wrap(node.left, p))$(_nf_op_text(node.op))$(wrap(node.right, p + 1))"
    elseif node isa ECond
        return "$(wrap(node.test, 1)) ? $(wrap(node.then, 1)) : $(wrap(node.otherwise, 1))"
    elseif node isa ECall
        return "$(node.name)($(join((_nf_write(a) for a in node.args), ", ")))"
    end
    return "?"
end

# --- the run's side ----------------------------------------------------------------------

_nf_about_non_numbers(e::SolverError) = e.kind == "nonfinite" || occursin(_NF_NON_NUMBERS, e.message)

"""Explicit steps past the last state the solver held, from the shortest the
clock tells apart and four times longer each time, up to `up_to` or the first
that shows a value that is not a number (`stepPast`)."""
function _nf_step_past(sys::System, frm, up_to::Float64)
    n = sys.nstate
    y = Vector{Float64}(frm.y[1:n])
    f = zeros(n)
    rhs!(sys, f, frm.t, y)
    all(isfinite, f) || return nothing
    shortest = 4 * eps(1.0) * max(1.0, abs(frm.t))
    longest = max(up_to, 1024 * shortest)
    h = shortest
    while h <= longest
        found = non_finite_at(sys, frm.t + h, y .+ h .* f)
        found === nothing || return (found=found, h=h)
        h *= 4
    end
    return nothing
end

"""
    explain_non_finite!(e, sys; start, held, end_) -> Bool

Puts what `non_finite_at` finds into a solver's error (`explainNonFinite`):
at the state the solver last held -- its own, if its error carries one, else
the step the runner kept -- and at the instant it failed; else at the start of
the stretch it was solving, if that is where it failed; else, for a failure
about a value that is not a number, short steps past the state held. The
message is said again with the place in it, and the block it starts in
becomes `block_name`. Nothing is changed when nothing is found.
"""
function explain_non_finite!(e::SolverError, sys::System; start=nothing, held=nothing, end_::Float64=NaN)
    (e.kind == "aborted" || e.kind == "span") && return false
    # One at a time: realisations failing together on threads share the
    # builder and the index space, whose look-ups fill caches as they go.
    return lock(() -> _nf_explain!(e, sys, start, held, end_), _NF_LOCK)
end

const _NF_LOCK = ReentrantLock()

function _nf_explain!(e::SolverError, sys::System, start, held, end_::Float64)
    frm = if !isempty(e.last_y) && isfinite(e.last_t)
        (t=e.last_t, y=e.last_y)
    elseif held !== nothing && isfinite(held.t[]) && (start === nothing || !(held.t[] < start[1]))
        (t=held.t[], y=held.y)
    else
        nothing
    end
    tries = Tuple{Float64,Vector{Float64}}[]
    if frm !== nothing
        push!(tries, (frm.t, frm.y))
        (isfinite(e.t) && e.t != frm.t) && push!(tries, (e.t, frm.y))
    elseif start !== nothing && isfinite(start[1]) && (!isfinite(e.t) || e.t == start[1])
        push!(tries, (start[1], start[2]))
    end
    function said(found, step=nothing)
        e.solver_message = e.message
        e.message = non_finite_message(found, sys, step)
        root = found["root"]
        block = root === nothing ? nothing :
                root["source"] !== nothing ? root["source"]["name"] : root["name"]
        block === nothing && !isempty(found["states"]) && (block = found["states"][1]["name"])
        block === nothing || (e.block_name = block)
        return true
    end
    for (t, y) in tries
        found = try
            non_finite_at(sys, t, y)
        catch
            nothing
        end
        found === nothing || return said(found)
    end
    if frm !== nothing && _nf_about_non_numbers(e)
        up_to = max(isfinite(e.t) ? 2 * abs(e.t - frm.t) : 0.0, isfinite(end_) ? 1e-3 * abs(end_ - frm.t) : 0.0)
        past = try
            _nf_step_past(sys, frm, up_to)
        catch
            nothing
        end
        past === nothing || return said(past.found, (from=frm.t, h=past.h))
    end
    return false
end
