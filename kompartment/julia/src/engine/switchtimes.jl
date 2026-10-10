# The times a model says it changes at, where the solver is restarted
# (src/domain/switchtimes.js, and `constantValue` in src/domain/transport.js):
# the declared switch times (a number, or the name of a parameter or an
# expression that comes to one before the run starts), plus the times waste
# packages fail at and events happen at.

const _SWITCH_NUMBER = r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$"
const FAILURE_TIME_KEYS = Dict("never" => String[], "at" => ["fail_at"], "uniform" => ["fail_from", "fail_to"],
                               "exponential" => ["fail_start"], "weibull" => ["fail_start"])

function declared_switch_times(project::Project)
    lst = get(project.simulation, "switch_times", nothing)
    return lst isa AbstractVector ? lst : Any[]
end

function switch_times(project::Project)
    sim = project.simulation
    start = py_float(something(get(sim, "start_time", nothing), 0))
    end_ = py_float(something(get(sim, "end_time", nothing), 0))
    out = Set{Float64}()
    function consider(v)
        (v === nothing || !(v > start) || !(v < end_)) && return
        push!(out, v)
    end
    for entry in declared_switch_times(project)
        consider(resolve_switch_time(project, entry))
    end
    for w in project.blocks["waste_packages"]
        failure = haskey(FAILURE_TIME_KEYS, get(w, "failure", nothing)) ? w["failure"] : "never"
        for key in FAILURE_TIME_KEYS[failure]
            consider(resolve_switch_time(project, get(w, key, nothing)))
        end
    end
    for d in project.blocks["events"]
        keys_ = (get(d, "timing", nothing) in ("at", "poisson") ? d["timing"] : "at") == "at" ? ["at"] : ["from", "until"]
        for key in keys_
            consider(resolve_switch_time(project, get(d, key, nothing)))
        end
    end
    return sort!(collect(out))
end

function resolve_switch_time(project::Project, entry)
    if entry isa Real && !(entry isa Bool)
        return isfinite(entry) ? Float64(entry) : nothing
    end
    name = strip(js_str(something(entry, "")))
    isempty(name) && return nothing
    occursin(_SWITCH_NUMBER, name) && return parse(Float64, name)
    found = _find_by_name(project, name)
    found === nothing && return nothing
    v = constant_value(project, found[1], found[2])
    return (v !== nothing && isfinite(v)) ? v : nothing
end

function _find_by_name(project::Project, name)
    for (collection, kind) in (("parameters", "parameter"), ("expressions", "expression"))
        for b in project.blocks[collection]
            qualified_name(b) == name && return (b, kind)
        end
    end
    return nothing
end

function _scenario_dims(project::Project)
    lists = project.index_lists
    root = findfirst_value(l -> js_truthy(get(l, "for_scenarios", nothing)), lists)
    root === nothing && return String[]
    by_name = Dict(l["name"] => l for l in lists)
    out = String[]
    for l in lists
        at = l["name"]
        i = 0
        while js_truthy(at) && i <= length(by_name)
            if at == root["name"]
                push!(out, l["name"])
                break
            end
            at = parent_list_name(get(by_name, at, nothing))
            i += 1
        end
    end
    return out
end

function _active_scenario(project::Project)
    lst = findfirst_value(l -> js_truthy(get(l, "for_scenarios", nothing)), project.index_lists)
    names = String[]
    for i in something(lst === nothing ? nothing : get(lst, "indices", nothing), Any[])
        item = i isa AbstractString ? JDict("name" => i, "enabled" => true) : i
        (js_truthy(get(item, "name", nothing)) && get(item, "enabled", nothing) !== false) && push!(names, item["name"])
    end
    isempty(names) && return nothing
    return project.scenario in names ? project.scenario : names[1]
end

function _constant_entry(project::Project, block, key, dims)
    isempty(dims) && return get(block, key, nothing)
    scen = Set(_scenario_dims(project))
    all(d -> d in scen, dims) || return nothing
    active = _active_scenario(project)
    for e in something(get(block, "entries", nothing), Any[])
        (e isa AbstractDict && haskey(e, key) && all(v -> v == active, values(something(get(e, "index", nothing), JDict())))) &&
            return e[key]
    end
    return get(block, key, nothing)
end

"""A block's value for the run when it has one: a parameter's number, or an
expression made of numbers and such blocks."""
function constant_value(project::Project, block, kind, seen=Set{String}())
    block === nothing && return nothing
    dims = something(get(block, "index_lists", nothing), String[])
    if kind == "parameter"
        v = py_float(something(_constant_entry(project, block, "value", dims), NaN))
        return isfinite(v) ? v : nothing
    end
    kind == "expression" || return nothing
    text = _constant_entry(project, block, "equation", dims)
    text === nothing && return nothing
    ast = try
        parse_equation(js_str(text))
    catch e
        e isa EquationParseError && return nothing
        rethrow()
    end
    system = js_truthy(get(block, "system", nothing)) ? block["system"] : ""
    own = qualified_name(block)
    function find(q)
        for b in project.blocks["parameters"]
            qualified_name(b) == q && return (b, "parameter")
        end
        for b in project.blocks["expressions"]
            qualified_name(b) == q && return (b, "expression")
        end
        return nothing
    end
    ok = Ref(true)
    function ref(name, indices, node=nothing)
        ok[] || return KLeaf(0.0)
        if !isempty(indices)
            ok[] = false
            return KLeaf(0.0)
        end
        q = resolve_reference(name, system, n -> find(n) !== nothing)
        if q === nothing || q == own || q in seen
            ok[] = false
            return KLeaf(0.0)
        end
        target = find(q)
        v = constant_value(project, target[1], target[2], seen ∪ Set([own]))
        if v === nothing
            ok[] = false
            return KLeaf(0.0)
        end
        return KLeaf(v)
    end
    tree = try
        resolve_tree(ast, ref)
    catch
        return nothing
    end
    ok[] || return nothing
    sim = project.simulation
    start = py_float(something(get(sim, "start_time", nothing), 0))
    end_ = py_float(something(get(sim, "end_time", nothing), 0))
    v = try
        evaluate_tree(tree, start, start, end_)
    catch
        return nothing
    end
    return isfinite(v) ? v : nothing
end

"""A tree of numbers and the clock, worked out with the generated code's arithmetic."""
function evaluate_tree(t::TNode, T::Float64, T0::Float64, T1::Float64)
    if t isa TLeaf
        t.kind === :K && return t.value
        t.kind === :T && return T
        t.kind === :T0 && return T0
        t.kind === :T1 && return T1
        error("a $(t.kind) leaf has no value here")
    elseif t isa TNeg
        return -evaluate_tree(t.a, T, T0, T1)
    elseif t isa TBin
        a = evaluate_tree(t.a, T, T0, T1)
        b = evaluate_tree(t.b, T, T0, T1)
        t.op === :^ && return _finite_constant(t.b) ? cpow(a, b) : kf_jspow(a, b)
        return apply_binary(t.op, a, b)
    elseif t isa TCond
        return evaluate_tree(t.test, T, T0, T1) != 0 ? evaluate_tree(t.a, T, T0, T1) : evaluate_tree(t.b, T, T0, T1)
    elseif t isa TCall
        args = Float64[evaluate_tree(a, T, T0, T1) for a in t.args]
        t.key == "power" && return _finite_constant(t.args[2]) ? cpow(args[1], args[2]) : kf_jspow(args[1], args[2])
        return call_value(t.key, args)
    end
    error("cannot evaluate $(typeof(t))")
end
