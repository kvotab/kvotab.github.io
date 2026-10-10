# Checking a model without running it (the Python package's check.py): the
# faults an edit can still leave -- mostly by writing into the raw
# dictionary -- found and said in words: a name that is not a name, a
# transfer end that is not a block, an equation that reads nothing, an index
# list nobody defined, a per-index value keyed by an index that does not
# exist, a setting out of range.

"""The equations each kind writes, block-level and per entry."""
const _CHECK_EQUATION_FIELDS = Dict{String,Tuple{Vararg{String}}}(
    "compartment" => ("initial", "dydt"), "transfer" => ("rate",), "inflow" => ("rate",), "expression" => ("equation",),
    "function" => ("equation",), "min_max" => ("target",), "running_mean" => ("target",),
    "snapshot" => ("target", "initial"), "delay" => ("target", "delay"), "trigger" => ("first", "second"),
    "farfield" => ("tw", "f", "aw", "aperture", "kd_f", "kd_m", "de_m", "eps_m", "rho_m", "pe", "pen_dep", "pen_dep_0"),
    "waste_package" => ("inventory", "irf", "degradation_rate", "fail_at", "fail_from", "fail_to", "fail_start",
                        "fail_rate", "fail_scale", "fail_shape"),
    "event" => ("at", "rate", "from", "until"))
const _CHECK_TRIGGER_FIELDS = Dict{String,Tuple{Vararg{String}}}(
    "min_max" => ("reset_trigger", "start_trigger", "stop_trigger"),
    "running_mean" => ("reset_trigger", "start_trigger", "stop_trigger"), "snapshot" => ("trigger",))

"""What is wrong with one equation's characters and names, or `nothing`."""
function _equation_problem(text, system, known, locals_=nothing)
    (text isa AbstractString && !isempty(strip(text))) || return nothing
    tokens = try
        tokenize(text)
    catch e
        e isa EquationSyntaxError || rethrow()
        return "$(e.message) at position $(e.position + 1)"
    end
    depth = 0
    for t in tokens
        if t.type === :lparen
            depth += 1
        elseif t.type === :rparen
            depth -= 1
            depth < 0 && return "a ')' closes nothing"
        end
    end
    depth > 0 && return "a '(' is never closed"
    for tok in reference_tokens(tokens, locals_)
        tok.text in RESERVED && continue   # a function with no arguments written bare: time, pi, eps
        resolve_reference(tok.text, system, known) === nothing && return "reads '$(tok.text)', which is not a block"
    end
    return nothing
end

"""The text of a value written in a message as Python writes it: `{p!r}`."""
_check_repr(v) = _py_repr(v)

"""
    check_model(m) -> Vector{String}

Every fault this package can see in a model, in words (see `check`).
"""
function check_model(m::Model)
    raw = m.raw
    out = String[]
    names = Dict{String,String}()
    known = _ed_known(m)
    lists = _ed_lists(m)
    systems_ = Set{String}(systems(m))
    for collection in COLLECTIONS
        items = get(raw, collection, nothing)
        items === nothing && continue
        if !(items isa AbstractVector)
            push!(out, "'$collection' is not a list of blocks")
            continue
        end
        kind = _BK_SINGULAR[collection]
        for b in items
            if !(b isa AbstractDict)
                push!(out, "'$collection' holds something that is not a block: $(_check_repr(b))")
                continue
            end
            q = qualified_name(b)
            problem = _ed_name_problem(get(b, "name", nothing))
            problem === nothing || push!(out, "$(isempty(q) ? "(unnamed)" : q): $problem")
            haskey(names, q) && push!(out, "'$q' is the name of two blocks ($(names[q]) and $kind)")
            haskey(names, q) || (names[q] = kind)
            q in systems_ && push!(out, "'$q' is the name of a block and of a sub-system")
            where_ = system_of(b)
            if !isempty(where_) && any(p -> _ed_name_problem(p) !== nothing, split(where_, '.'))
                push!(out, "$q: '$where_' is not a valid sub-system path")
            end

            dims = get(b, "index_lists", nothing)
            if dims isa AbstractVector && !(kind in ("function", "event"))
                for d in dims
                    lst = find_list(lists, d)
                    if lst === nothing
                        push!(out, "$q is indexed by '$(_py_str(d))', which is not an index list of the model")
                    elseif !list_applies(lst, kind)
                        push!(out, "$q is a $(_spaced(kind)) and cannot be indexed by '$(_py_str(d))'")
                    end
                end
                clash = clashing_dimensions(lists, [d for d in dims if find_list(lists, d) !== nothing])
                clash === nothing || push!(out, "$q: $(clashing_dimensions_why(clash))")
                for e in _py_iter(get(b, "entries", nothing))
                    ix = e isa AbstractDict ? get(e, "index", nothing) : nothing
                    if !(ix isa AbstractDict)
                        push!(out, "$q: a per-index value has no index")
                        continue
                    end
                    for (lst_name, idx) in ix
                        if !(lst_name in dims)
                            push!(out, "$q: a per-index value is keyed by '$lst_name', which the block is not indexed by")
                            continue
                        end
                        lst = find_list(lists, lst_name)
                        if lst !== nothing && !(idx in _ed_index_names(lst))
                            push!(out, "$q: a per-index value is keyed by '$(_py_str(idx))', which is not an index of '$lst_name'")
                        end
                    end
                end
            end

            system = where_
            locals_ = kind == "function" ? Set{String}(_py_str(p) for p in _py_iter(get(b, "parameters", nothing))) : nothing
            for field in get(_CHECK_EQUATION_FIELDS, kind, ())
                (kind == "expression" && get(b, "transport", nothing) in ("counter", "operation")) && continue
                for holder in Any[b, (e for e in _py_iter(get(b, "entries", nothing)) if e isa AbstractDict)...]
                    problem = _equation_problem(get(holder, field, nothing), system, known, locals_)
                    problem === nothing || push!(out, "$q: its $(_spaced(field)) $problem")
                end
            end
            (kind == "function" && isempty(strip(_py_or_text(get(b, "equation", nothing))))) && push!(out, "$q has no body yet")

            if kind in ("transfer", "inflow")
                for end_ in (kind == "transfer" ? ("from", "to") : ("to",))
                    v = get(b, end_, nothing)
                    v === nothing && continue
                    k = _ed_kind_of(m, v)
                    what = end_ == "from" ? "source" : "target"
                    if k === nothing
                        push!(out, "$q: its $what '$(_py_str(v))' is not a block")
                    elseif !(k in ("compartment", "farfield", "waste_package")) || (k == "waste_package" && end_ == "to")
                        push!(out, "$q: its $what '$(_py_str(v))' is a $(_spaced(k)), which a flux cannot " *
                                   "$(end_ == "from" ? "leave" : "enter")")
                    end
                end
                (kind == "transfer" && get(b, "from", nothing) === nothing && get(b, "to", nothing) === nothing) &&
                    push!(out, "$q runs from nowhere to nowhere")
                if kind == "transfer"
                    own = get(b, "multiply_by_donor", nothing) !== false
                    odd = findfirst_value(e -> e isa AbstractDict && haskey(e, "multiply_by_donor") &&
                                               (e["multiply_by_donor"] !== false) != own, _py_iter(get(b, "entries", nothing)))
                    if odd !== nothing
                        ix = _py_or_dict(get(odd, "index", nothing))
                        at = isempty(ix) ? "one of its entries" : join((_py_str(v) for v in values(ix)), ", ")
                        push!(out, "$q: $at says otherwise about multiplying by the donor, which is one setting for the " *
                                   "whole transfer; make it two transfers, one by the donor and one an absolute flux")
                    end
                end
                (kind == "inflow" && get(b, "to", nothing) === nothing) && push!(out, "$q feeds nothing")
            end
            if kind == "farfield"
                problem = rock_problem(b)
                problem === nothing || push!(out, "$q: $problem")
                a = get(b, "availability", nothing)
                if a isa AbstractDict
                    get(a, "scheme", nothing) in _BK_AVAILABILITY_SCHEMES ||
                        push!(out, "$q: '$(_py_str(get(a, "scheme", nothing)))' is not an availability scheme")
                    for key in ("limit", "top", "bottom")
                        problem = _equation_problem(get(a, key, nothing), system, known)
                        problem === nothing || push!(out, "$q: its availability $key $problem")
                    end
                end
            end
            if kind == "index_reduction"
                t = get(b, "target", nothing)
                (py_truthy(t) && resolve_reference(_py_str(t), system, known) === nothing) &&
                    push!(out, "$q reduces '$(_py_str(t))', which is not a block")
                get(b, "operation", "sum") in OPERATIONS ||
                    push!(out, "$q: '$(_py_str(get(b, "operation", nothing)))' is not a reduction")
            end
            if kind == "block_reduction"
                for t in _py_iter(get(b, "targets", nothing))
                    resolve_reference(_py_str(t), system, known) === nothing && push!(out, "$q combines '$(_py_str(t))', which is not a block")
                end
            end
            if kind == "lookup"
                get(b, "interpolation", "linear") in INTERPOLATIONS ||
                    push!(out, "$q: '$(_py_str(get(b, "interpolation", nothing)))' is not an interpolation rule")
                xs = Float64[]
                for p in _py_iter(get(b, "points", nothing))
                    seq = p isa AbstractString ? Any[string(c) for c in p] :
                          (p isa AbstractVector || p isa Tuple) ? collect(Any, p) : Any[]
                    x = length(seq) >= 1 ? _ed_pyfloat(seq[1]) : nothing
                    x === nothing || push!(xs, x)
                    y = length(seq) >= 2 ? _ed_pyfloat(seq[2]) : nothing
                    if x === nothing || y === nothing
                        push!(out, "$q: a point $(_check_repr(p)) is not two numbers")
                        break
                    end
                end
                any(i -> xs[i+1] < xs[i], 1:length(xs)-1) && push!(out, "$q: its points are not in order of x")
            end
            if haskey(_CHECK_TRIGGER_FIELDS, kind)
                for field in _CHECK_TRIGGER_FIELDS[kind]
                    v = get(b, field, nothing)
                    py_truthy(v) || continue
                    t = resolve_reference(String(strip(_py_str(v))), system, known)
                    (t === nothing || _ed_kind_of(m, t) != "trigger") &&
                        push!(out, "$q: its $(_spaced(field)) '$(_py_str(v))' is not a trigger")
                end
            end
            (kind == "min_max" && !(get(b, "operation", "max") in EXTREMES)) &&
                push!(out, "$q: '$(_py_str(get(b, "operation", nothing)))' is not max or min")
            (kind == "trigger" && !(get(b, "direction", "rising") in DIRECTIONS)) &&
                push!(out, "$q: '$(_py_str(get(b, "direction", nothing)))' is not a crossing direction")
            (kind == "waste_package" && !(get(b, "failure", "never") in FAILURES)) &&
                push!(out, "$q: '$(_py_str(get(b, "failure", nothing)))' is not a way of failing")
            if kind == "event"
                get(b, "timing", "at") in TIMINGS || push!(out, "$q: '$(_py_str(get(b, "timing", nothing)))' is not a timing")
                for a in _py_iter(get(b, "actions", nothing))
                    for end_ in ("block", "from", "to")
                        v = a isa AbstractDict ? get(a, end_, nothing) : nothing
                        (v isa AbstractString && !isempty(v) && resolve_reference(v, system, known) === nothing) &&
                            push!(out, "$q: an action names '$v', which is not a block")
                    end
                    problem = _equation_problem(a isa AbstractDict ? get(a, "fraction", nothing) : nothing, system, known)
                    problem === nothing || push!(out, "$q: an action's share $problem")
                end
            end
        end
    end

    seen_lists = Set{Any}()
    for lst in _py_iter(get(raw, "index_lists", nothing))
        if !(lst isa AbstractDict)
            push!(out, "An index list is not a list: $(_check_repr(lst))")
            continue
        end
        n = get(lst, "name", nothing)
        n in seen_lists && push!(out, "Two index lists are called '$(_py_str(n))'")
        push!(seen_lists, n)
        idx = _ed_index_names(lst)
        length(Set(idx)) != length(idx) && push!(out, "Index list '$(_py_str(n))' has an index twice")
        any(i -> isempty(strip(_py_or_text(i))), idx) && push!(out, "Index list '$(_py_str(n))' has an index with no name")
        if py_truthy(get(lst, "sub_set_of", nothing))
            parent = find_list(lists, lst["sub_set_of"])
            if parent === nothing
                push!(out, "'$(_py_str(n))' is a sub-set of '$(_py_str(lst["sub_set_of"]))', which is not an index list")
            else
                have = Set{Any}(_ed_index_names(parent))
                stray = [i for i in idx if !(i in have)]
                isempty(stray) || push!(out, "'$(_py_str(n))' is a sub-set of '$(_py_str(parent["name"]))' but holds " *
                                             "$(join((_py_str(s) for s in stray), ", ")), which it has not")
            end
        end
        mp = get(lst, "mapping", nothing)
        if mp isa AbstractDict
            parent = find_list(lists, get(mp, "to", nothing))
            if parent === nothing
                push!(out, "'$(_py_str(n))' maps onto '$(_py_str(get(mp, "to", nothing)))', which is not an index list")
            else
                have = Set{Any}(_ed_index_names(parent))
                for p in _py_iter(get(mp, "pairs", nothing))
                    if !(get(p, "to", nothing) in have) || !(get(p, "from", nothing) in idx)
                        push!(out, "'$(_py_str(n))' maps '$(_py_str(get(p, "to", nothing)))' to " *
                                   "'$(_py_str(get(p, "from", nothing)))', and one of them is not an index")
                        break
                    end
                end
            end
        end
    end
    for nuc in nuclides(m)
        half_life(m, nuc) === nothing &&
            push!(out, "$(_py_str(nuc)) has no half-life: ICRP 107 does not know it and the model gives none")
    end
    for pair in _py_iter(get(raw, "chains", nothing))
        ((pair isa AbstractVector || pair isa Tuple) && length(pair) >= 2) ||
            push!(out, "A decay pair is not [parent, daughter, branching]: $(_check_repr(pair))")
    end

    sim = get(raw, "simulation", nothing)
    py_truthy(sim) || (sim = JDict())
    start = _ed_pyfloat(get(sim, "start_time", 0))
    stop = _ed_pyfloat(get(sim, "end_time", 1e5))
    if start === nothing || stop === nothing
        push!(out, "The start or end time is not a number")
    elseif !(stop > start)
        push!(out, "The run ends before it starts (end time not after start time)")
    end
    for key in ("rtol", "abstol")
        v = get(sim, key, nothing)
        v === nothing && continue
        f = _ed_pyfloat(v)
        (f === nothing || !(f > 0) || isinf(f)) && push!(out, "$key has to be a number greater than zero")
    end
    get(sim, "solver", "ndf") in SOLVER_IDS || push!(out, "'$(_py_str(get(sim, "solver", nothing)))' is not a solver")
    get(sim, "spacing", "log") in SPACINGS ||
        push!(out, "'$(_py_str(get(sim, "spacing", nothing)))' is not a way of choosing output times")
    get(sim, "time_unit", "year") in _SIM_TIME_UNITS ||
        push!(out, "'$(_py_str(get(sim, "time_unit", nothing)))' is not a time unit")
    return out
end

"""
    check(m) -> Vector{String}

What is wrong with the model that this package can see, in words: names,
transfer ends, references to nothing, index lists, per-index values,
settings. Empty when nothing is. The model is settled first. Not the whole
of what the application checks -- unit consistency and whether the model
builds are found by `build`.
"""
function check(m::Model)
    settle!(m.raw)
    return check_model(m)
end
