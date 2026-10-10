# The project a run is built from: a model file read, normalised and checked
# (`Project` in src/domain/project.js). It takes the model as the file has it
# and produces the shape the builder reads: every block with its defaults,
# its dimensions and its entries resolved; the index space; the decay model;
# the connections' ends qualified; disabled blocks set aside. Anything the
# application would refuse to load is refused here with the same message.

struct ValidationError <: Exception
    message::String
    block::Union{Nothing,String}
    # The only constructor, so that a block named always prefixes the message,
    # as Python's `ValidationError(message, block)` does (an empty name does not).
    function ValidationError(msg::AbstractString, block=nothing)
        named = block !== nothing && block != ""
        return new(named ? "$(block): $(msg)" : String(msg), block === nothing ? nothing : String(block))
    end
end
Base.showerror(io::IO, e::ValidationError) = print(io, e.message)

const LN2 = log(2.0)
const DECAY_UNITS = ("Bq", "mol")
const INTERPOLATIONS = ("linear", "extrapolate", "below", "above", "nearest")
const OPERATIONS = ("sum", "product", "min", "max", "mean", "percentile")
const AGGREGATE_OPERATIONS = ("sum", "product", "min", "max", "mean")
const EXTREMES = ("max", "min")
const DIRECTIONS = ("rising", "falling", "both")
const FAILURES = ("never", "at", "uniform", "exponential", "weibull")
const FAILURE_KEYS = Dict("never" => String[], "at" => ["fail_at"], "uniform" => ["fail_from", "fail_to"],
                          "exponential" => ["fail_start", "fail_rate"],
                          "weibull" => ["fail_start", "fail_scale", "fail_shape"])
const FAILURE_LABEL = Dict("never" => "never", "at" => "all at one time", "uniform" => "evenly over a window",
                           "exponential" => "at a constant rate", "weibull" => "Weibull")
const WASTE_NUCLIDE_KEYS = ("inventory", "irf", "degradation_rate")
const WASTE_SINGLE_KEYS = ("fail_at", "fail_from", "fail_to", "fail_start", "fail_rate", "fail_scale", "fail_shape")
const WASTE_EQUATION_KEYS = (WASTE_NUCLIDE_KEYS..., WASTE_SINGLE_KEYS...)
const WASTE_LABEL = Dict(
    "inventory" => "Inventory", "irf" => "Instant release fraction", "degradation_rate" => "Matrix degradation rate",
    "fail_at" => "Fail at", "fail_from" => "Failures from", "fail_to" => "Failures until",
    "fail_start" => "Failures start", "fail_rate" => "Failure rate", "fail_scale" => "Weibull scale",
    "fail_shape" => "Weibull shape")
const WASTE_DEFAULTS = JDict(
    "failure" => "never", "packages" => 1, "inventory" => "0", "irf" => "0", "degradation_rate" => "0",
    "fail_at" => "", "fail_from" => "", "fail_to" => "", "fail_start" => "0", "fail_rate" => "", "fail_scale" => "",
    "fail_shape" => "1", "handle_decay" => true)
const TIMINGS = ("at", "poisson")
const ACTIONS = ("fail", "move")
const DIS_EQUATION_KEYS = ("at", "rate", "from", "until")
const DIS_DEFAULTS = JDict("timing" => "at", "at" => "", "rate" => "", "from" => "", "until" => "", "sampled" => true,
                           "actions" => Any[])
const TIMING_KEYS = Dict("at" => ["at"], "poisson" => ["rate", "from", "until"])
const TRANSPORT_ROLES = Dict("compartment" => ("begin", "end"), "expression" => ("number", "counter", "operation"))

const INTERPOLATION_FROM_ECO = Dict(
    "Interpolation-Use End Values" => "linear", "Interpolation-Extrapolation" => "extrapolate",
    "Use Input Below" => "below", "Use Input Above" => "above", "Use Input Nearest" => "nearest")
const OPERATION_FROM_ECO = Dict(
    "SUM" => "sum", "PRODUCT" => "product", "MIN" => "min", "MAX" => "max", "MEAN" => "mean",
    "PERCENTILE" => "percentile", "Sum" => "sum", "Product" => "product", "Minimum" => "min", "Maximum" => "max",
    "Mean" => "mean", "Percentile" => "percentile")
const DIRECTION_FROM_ECO = Dict("RIGHT" => "rising", "LEFT" => "falling", "BOTH" => "both")

const VALUE_KEYS = Dict{String,Vector{String}}(
    "compartment" => ["initial", "abstol", "non_negative", "dydt"],
    "function" => ["equation"],
    # The rate alone: whether it is multiplied by the donor is one setting of the whole transfer.
    "transfer" => ["rate"],
    "expression" => ["equation"],
    "parameter" => ["value", "pdf"],
    "inflow" => ["rate"],
    "lookup" => ["points"],
    "index_reduction" => ["target"],
    "block_reduction" => ["targets"],
    "min_max" => ["target", "reset_trigger", "start_trigger", "stop_trigger"],
    "running_mean" => ["target", "reset_trigger", "start_trigger", "stop_trigger"],
    "snapshot" => ["target", "trigger", "initial"],
    "delay" => ["target", "delay"],
    "trigger" => ["first", "second", "direction"],
    "farfield" => collect(FARF_EQUATION_KEYS),
    "waste_package" => collect(WASTE_EQUATION_KEYS),
    "event" => collect(DIS_EQUATION_KEYS),
)

const BLOCK_COLLECTIONS = ("parameters", "compartments", "expressions", "transfers", "inflows", "lookups",
                           "index_reductions", "block_reductions", "functions", "min_maxes", "running_means",
                           "snapshots", "delays", "triggers", "farfields", "waste_packages", "events")
const KIND_OF = Dict(
    "parameters" => "parameter", "compartments" => "compartment", "expressions" => "expression",
    "transfers" => "transfer", "inflows" => "inflow", "lookups" => "lookup", "index_reductions" => "index_reduction",
    "block_reductions" => "block_reduction", "functions" => "function", "min_maxes" => "min_max",
    "running_means" => "running_mean", "snapshots" => "snapshot", "delays" => "delay", "triggers" => "trigger",
    "farfields" => "farfield", "waste_packages" => "waste_package", "events" => "event")

const BLOCK_DEFAULTS = Dict{String,JDict}(
    "compartment" => JDict("initial" => "0", "non_negative" => true, "handle_decay" => true, "color" => nothing,
                           "unit" => "Bq"),
    "transfer" => JDict("from" => nothing, "to" => nothing, "rate" => "0", "multiply_by_donor" => true,
                        "unit" => "1/year"),
    "expression" => JDict("equation" => "0", "unit" => ""),
    "parameter" => JDict("value" => 0, "unit" => ""),
    "inflow" => JDict("to" => nothing, "rate" => "0", "unit" => "Bq/year"),
    "lookup" => JDict("points" => Any[], "interpolation" => "linear", "cyclic" => false, "argument" => nothing,
                      "unit" => ""),
    "index_reduction" => JDict("target" => nothing, "operation" => "sum", "percentile" => nothing, "unit" => ""),
    "block_reduction" => JDict("targets" => Any[], "operation" => "sum", "unit" => ""),
    "function" => JDict("parameters" => Any[], "equation" => "", "unit" => ""),
    "min_max" => JDict("target" => "0", "operation" => "max", "reset_trigger" => nothing, "start_trigger" => nothing,
                       "stop_trigger" => nothing, "unit" => ""),
    "running_mean" => JDict("target" => "0", "reset_trigger" => nothing, "start_trigger" => nothing,
                            "stop_trigger" => nothing, "unit" => ""),
    "snapshot" => JDict("target" => "0", "trigger" => nothing, "initial" => "0", "unit" => ""),
    "delay" => JDict("target" => "0", "delay" => "0", "unit" => ""),
    "trigger" => JDict("first" => "0", "second" => "0", "direction" => "rising", "unit" => ""),
    "farfield" => merge(FARF_DEFAULTS, JDict("unit" => "")),
    "waste_package" => merge(WASTE_DEFAULTS, JDict("unit" => "")),
    "event" => merge(DIS_DEFAULTS, JDict("unit" => "")),
)

const INDEX_NAME_BAD = r"[\r\n  <>]"

"""
    value_at(block, key, tuple_by_list)

The value of `key` at one index tuple: the most specific matching entry, the
first of them on a tie, else the block's own.
"""
function value_at(block, key, tup)
    best = nothing
    best_score = -1
    for entry in something(get(block, "entries", nothing), Any[])
        haskey(entry, key) || continue
        score = 0
        ok = true
        for (list_name, index_name) in something(get(entry, "index", nothing), JDict())
            if get(tup, list_name, nothing) != index_name
                ok = false
                break
            end
            score += 1
        end
        if ok && score > best_score
            best_score = score
            best = entry[key]
        end
    end
    best_score >= 0 && return best
    return get(block, key, nothing)
end

"""
    entry_lookup(block, key) -> f(tuple_by_list)

`value_at(block, key, tup)` as a function of `tup`, with the entries indexed
once by the lists each names: the same answer, quicker for many tuples.
"""
function entry_lookup(block, key)
    groups = OrderedDict{Vector{String},Dict{Vector{Any},Tuple{Int,Any}}}()
    for (pos, entry) in enumerate(something(get(block, "entries", nothing), Any[]))
        haskey(entry, key) || continue
        index = something(get(entry, "index", nothing), JDict())
        vals = Any[v for v in values(index)]
        g = get!(groups, String[k for k in keys(index)]) do
            Dict{Vector{Any},Tuple{Int,Any}}()
        end
        haskey(g, vals) || (g[vals] = (pos, entry[key]))
    end
    own = get(block, key, nothing)
    isempty(groups) && return _ -> own
    order = sort!(collect(groups); by=item -> -length(item[1]))
    return function (tup)
        best_score = -1
        best_pos = -1
        best = nothing
        for (lists, group) in order
            score = length(lists)
            score < best_score && break
            hit = get(group, Any[get(tup, name, nothing) for name in lists], nothing)
            if hit !== nothing && (score > best_score || hit[1] < best_pos)
                best_score, best_pos, best = score, hit[1], hit[2]
            end
        end
        return best_score >= 0 ? best : own
    end
end

function has_dydt(block)
    is_set(v) = v isa AbstractString && !isempty(strip(v))
    return is_set(get(block, "dydt", nothing)) || any(e -> is_set(get(e, "dydt", nothing)), something(get(block, "entries", nothing), Any[]))
end

"""Decay constant per `time_unit`: ln 2 over the half-life converted into it."""
function lam(nuclide, time_unit, half_lives)
    hl = nuclide === nothing ? nothing : get(half_lives, nuclide, nothing)
    (hl === nothing || !isfinite(hl)) && return 0.0
    return LN2 / (hl / TIME_UNITS[time_unit])
end

"""Decay constants and, per nuclide, the parents growing into it (`buildDecayModel`)."""
struct DecayModel
    names::Vector{String}
    lambdas::Vector{Float64}
    parents::Vector{Vector{NamedTuple{(:index, :lambda, :ratio),Tuple{Int,Float64,Float64}}}}
end

function build_decay_model(names, time_unit, half_lives, decay_unit, chains)
    idx = Dict(n => i - 1 for (i, n) in enumerate(names))
    lambdas = Float64[lam(n, time_unit, half_lives) for n in names]
    parents = [NamedTuple{(:index, :lambda, :ratio),Tuple{Int,Float64,Float64}}[] for _ in names]
    amounts = decay_unit == "mol"
    for pair in chains
        parent, daughter = pair[1], pair[2]
        ratio = length(pair) > 2 ? pair[3] : 1
        pi = get(idx, parent, nothing)
        di = get(idx, daughter, nothing)
        (pi === nothing || di === nothing) && continue
        push!(parents[di+1], (index=pi, lambda=amounts ? lambdas[pi+1] : lambdas[di+1], ratio=Float64(js_number_of(ratio))))
    end
    return DecayModel(collect(String, names), lambdas, parents)
end

function _check_index_name(name, list_name)
    text = name === nothing ? "" : string(name)
    isempty(strip(text)) && throw(ValidationError("An index of '$list_name' has no name", list_name))
    if occursin(INDEX_NAME_BAD, text)
        shown = replace(text, INDEX_NAME_BAD => "?")
        throw(ValidationError("'$shown' is not a usable index name: an index may not contain a line break or " *
                              "angle brackets", list_name))
    end
    return text
end

function normalise_index_lists(raw_lists)
    shown(v) = replace(string(v), INDEX_NAME_BAD => "?")
    for l in something(raw_lists, Any[])
        (l isa AbstractDict && !js_truthy(get(l, "derived", nothing))) || continue
        lname = get(l, "name", nothing)
        occursin(NAME_RE, string(something(lname, ""))) ||
            throw(ValidationError("'$(shown(lname))' is not a valid index list name (letters, digits and underscore; " *
                                  "must not start with a digit)", shown(lname)))
        lname in RESERVED && throw(ValidationError("'$lname' is a reserved name", lname))
        seen = Set{String}()
        for i in something(get(l, "indices", nothing), Any[])
            name = _check_index_name(i isa AbstractString ? i : jget(i, "name"), lname)
            name in seen && throw(ValidationError("'$name' appears twice in index list '$lname'. Two indices of the " *
                                                  "same name are one address for two positions: everything indexed " *
                                                  "by the list would carry a slot nothing can reach.", lname))
            push!(seen, name)
        end
    end
    names_of(l) = Set(i isa AbstractString ? i : jget(i, "name") for i in something(get(l, "indices", nothing), Any[]))
    for l in something(raw_lists, Any[])
        (l isa AbstractDict && !js_truthy(get(l, "derived", nothing)) && get(l, "mapping", nothing) isa AbstractDict) || continue
        target = findfirst_value(x -> x isa AbstractDict && get(x, "name", nothing) == get(l["mapping"], "to", nothing), raw_lists)
        target === nothing && continue
        own = names_of(l)
        theirs = names_of(target)
        for pair in something(get(l["mapping"], "pairs", nothing), Any[])
            jget(pair, "from") in own ||
                throw(ValidationError("Index list '$(l["name"])' maps '$(shown(jget(pair, "from")))', which is not one " *
                                      "of its indices", l["name"]))
            jget(pair, "to") in theirs ||
                throw(ValidationError("Index list '$(l["name"])' maps '$(jget(pair, "from"))' onto " *
                                      "'$(shown(jget(pair, "to")))', which is not an index of '$(target["name"])'", l["name"]))
        end
    end
    out = JDict[]
    for l in something(raw_lists, Any[])
        d = JDict("name" => get(l, "name", nothing), "for_contaminants" => js_truthy(get(l, "for_contaminants", nothing)))
        for key in ("for_nuclides", "for_scenarios", "for_elements")
            js_truthy(get(l, key, nothing)) && (d[key] = true)
        end
        js_truthy(get(l, "sub_set_of", nothing)) && (d["sub_set_of"] = l["sub_set_of"])
        js_truthy(get(l, "mapping", nothing)) && (d["mapping"] = l["mapping"])
        js_truthy(get(l, "comment", nothing)) && (d["comment"] = l["comment"])
        js_truthy(get(l, "derived", nothing)) && (d["derived"] = true)
        js_truthy(get(l, "auto", nothing)) && (d["auto"] = l["auto"])
        js_truthy(get(l, "note", nothing)) && (d["note"] = l["note"])
        idx = Any[]
        for i in something(get(l, "indices", nothing), Any[])
            if i isa AbstractString
                push!(idx, JDict("name" => i, "enabled" => true))
            else
                e = JDict("name" => get(i, "name", nothing), "enabled" => get(i, "enabled", nothing) !== false)
                u = strip(js_str(something(get(i, "unit", nothing), "")))
                isempty(u) || (e["unit"] = String(u))
                push!(idx, e)
            end
        end
        d["indices"] = idx
        push!(out, d)
    end
    return out
end

function series_kind_of(spec)
    get(spec, "times", nothing) isa AbstractVector && return "times"
    k = get(spec, "kind", nothing)
    named = js_str(k !== nothing ? k : (js_truthy(get(spec, "spacing", nothing)) ? spec["spacing"] : "log"))
    return named == "linear" ? "linear" : (named == "times" ? "times" : "log")
end

function normalise_series(raw)
    out = JDict[]
    raw isa AbstractVector || return out
    for spec in raw
        spec isa AbstractDict || continue
        kind = series_kind_of(spec)
        if kind == "times"
            times = sort!([v for v in (js_number_of(x) for x in something(get(spec, "times", nothing), Any[])) if isfinite(v)])
            isempty(times) || push!(out, JDict("kind" => "times", "times" => times))
            continue
        end
        pts = js_number_of(get(spec, "points", 0))
        points = isfinite(pts) ? Int(floor(pts + 0.5)) : 0
        points >= 2 || continue
        num(v) = (v === nothing || v == "") ? nothing : (n = js_number_of(v); isfinite(n) ? n : nothing)
        push!(out, JDict("kind" => kind, "points" => points, "from" => num(get(spec, "from", nothing)),
                         "to" => num(get(spec, "to", nothing))))
    end
    return out
end

_is_jsnum_like(v) = (v isa Real && !(v isa Bool)) || v isa AbstractString

function normalise_points(points, block_name)
    points === nothing && return Any[]
    points isa AbstractVector || throw(ValidationError("Lookup points must be a list of [x, y] pairs", block_name))
    pairs = points
    if length(points) == 2 && points[1] isa AbstractVector && points[2] isa AbstractVector &&
       length(points[1]) == length(points[2]) && all(_is_jsnum_like, points[1]) && length(points[1]) != 2
        pairs = [Any[x, points[2][i]] for (i, x) in enumerate(points[1])]
    end
    out = Any[]
    for (i, pt) in enumerate(pairs)
        if pt isa AbstractVector
            x = length(pt) > 0 ? pt[1] : nothing
            y = length(pt) > 1 ? pt[2] : nothing
            pdf = length(pt) > 2 ? pt[3] : nothing
        elseif pt isa AbstractDict
            x, y, pdf = get(pt, "x", nothing), get(pt, "y", nothing), get(pt, "pdf", nothing)
        else
            x = y = pdf = nothing
        end
        nx = x === nothing ? NaN : js_number_of(x)
        ny = y === nothing ? NaN : js_number_of(y)
        if !isfinite(nx) || !isfinite(ny)
            throw(ValidationError("Lookup point $i is ($(js_text(x)), $(js_text(y))); both parts must be numbers",
                                  block_name))
        end
        push!(out, js_truthy(pdf) ? Any[nx, ny, pdf] : Any[nx, ny])
    end
    return out
end

function normalise_targets(targets, block_name)
    targets === nothing && return String[]
    lst = if targets isa AbstractString
        split(targets, '+')
    elseif targets isa AbstractVector
        targets
    else
        throw(ValidationError("Aggregate targets must be a list of block names", block_name))
    end
    return String[strip(js_str(t)) for t in lst if !isempty(strip(js_str(t)))]
end

function normalise_entry_index(index, material_list_name, dims)
    index === nothing && return JDict()
    if index isa AbstractString
        lst = length(dims) == 1 ? dims[1] : material_list_name
        js_truthy(lst) || throw(ValidationError("Entry index '$index' is ambiguous: name the index list explicitly, as " *
                                                "{ \"ListName\": \"$index\" }"))
        return JDict(lst => index)
    end
    if index isa AbstractVector
        length(index) == length(dims) ||
            throw(ValidationError("Entry index has $(length(index)) component(s) but the block has $(length(dims)) dimension(s)"))
        return JDict(dims[i] => v for (i, v) in enumerate(index) if v !== nothing)
    end
    index isa AbstractDict || throw(ValidationError("Entry index '$(js_text(index))' is not an index: write it as a " *
                                                    "name, a list of names, or an object keyed by index list."))
    return JDict(index)
end

function normalise_entries(raw, kind, material_list_name, dims)
    out = Any[]
    keys_ = VALUE_KEYS[kind]
    for e in something(get(raw, "entries", nothing), Any[])
        e isa AbstractDict || continue
        index = normalise_entry_index(get(e, "index", nothing), material_list_name, dims)
        values_ = JDict(k => e[k] for k in keys_ if haskey(e, k))
        if kind == "lookup" && haskey(values_, "points")
            values_["points"] = normalise_points(values_["points"], get(raw, "name", ""))
        end
        if kind == "block_reduction" && haskey(values_, "targets")
            values_["targets"] = normalise_targets(values_["targets"], get(raw, "name", ""))
        end
        if haskey(values_, "non_negative")
            v = values_["non_negative"]
            values_["non_negative"] = !(v === false || v == "false" || (v isa Real && !(v isa Bool) && v == 0))
        end
        if kind == "farfield" && js_truthy(material_list_name) && haskey(index, material_list_name)
            values_ = JDict(k => v for (k, v) in values_ if k in FARF_NUCLIDE_KEYS)
        end
        if kind == "waste_package" && js_truthy(material_list_name) && haskey(index, material_list_name)
            values_ = JDict(k => v for (k, v) in values_ if k in WASTE_NUCLIDE_KEYS)
        end
        entry = JDict("index" => index)
        merge!(entry, values_)
        push!(out, entry)
    end
    init = get(raw, "initial", nothing)
    if kind == "compartment" && init isa AbstractDict && js_truthy(material_list_name)
        for (nuc, v) in init
            push!(out, JDict("index" => JDict(material_list_name => nuc), "initial" => js_str(v)))
        end
    end
    vbn = get(raw, "values_by_nuclide", nothing)
    if kind == "parameter" && js_truthy(vbn) && js_truthy(material_list_name)
        for (nuc, v) in vbn
            push!(out, JDict("index" => JDict(material_list_name => nuc), "value" => js_number_of(v)))
        end
    end
    return out
end

function normalise_actions(raw)
    raw isa AbstractVector || return JDict[]
    out = JDict[]
    for a in raw
        a isa AbstractDict || continue
        k = get(a, "kind", nothing)
        f = get(a, "fraction", nothing)
        d = JDict("kind" => js_str(k !== nothing ? k : "move"), "fraction" => js_str(f !== nothing ? f : "1"))
        if d["kind"] == "fail"
            b = get(a, "block", nothing)
            d["block"] = b === nothing ? nothing : js_str(b)
        else
            fr = get(a, "from", nothing)
            to = get(a, "to", nothing)
            d["from"] = fr === nothing ? nothing : js_str(fr)
            d["to"] = (to === nothing || to == "") ? nothing : js_str(to)
        end
        push!(out, d)
    end
    return out
end

function summed_dims_why(flux, end_, end_name, dims, size_of=nothing)
    named = ["'$d'" for d in dims]
    lst = length(named) > 1 ? join(named[1:end-1], ", ") * " and " * named[end] : named[1]
    sizes = [size_of === nothing ? nothing : size_of(d) for d in dims]
    count = all(s -> s !== nothing && s != 0, sizes) ? prod(sizes) : nothing
    over = count !== nothing ? "all $count of them" : "all of them"
    each = count !== nothing ? "each of the $count of them" : "each of them"
    body = end_ == "to" ? ": the flux would be added up over $over and delivered into the one '$end_name' cell." :
           ": the flux would be taken out of the one '$end_name' cell once for $each."
    return "'$flux' is indexed by $lst, which '$end_name' is not$body Give both ends the same dimensions, or tick " *
           "\"sum extra indices\" on '$flux' to ask for that total on purpose."
end

_transport_operation(op) = (v = lowercase(strip(js_str(something(op, "")))); isempty(v) ? nothing :
                            v in ("sum", "mean") ? v : v == "point" ? "sum" : nothing)
_transport_argument(arg) = (v = lowercase(strip(js_str(something(arg, "")))); isempty(v) ? nothing :
                            v in ("all", "point", "range") ? v : nothing)
_extreme(name) = (s = uppercase(strip(js_str(something(name, "")))); s == "MIN" ? "min" : s == "MAX" ? "max" : nothing)

const _ICRP_HALF_LIVES = Dict{String,Float64}(n => r.half_life for (n, r) in ICRP107)

mutable struct Project
    raw::JDict
    name::Any
    description::Any
    simulation::JDict
    output_times::Vector{JDict}
    output_mode::String
    solver_points::Bool
    nuclides::Vector{Any}
    decay_unit::String
    decay_ceiling::Float64
    half_lives_override::JDict
    half_lives::Dict{String,Float64}
    chains_override::Union{Nothing,Vector{Any}}
    chains::Vector{Any}
    derived_lists::Set{String}
    index_lists::Vector{JDict}
    index_space::IndexSpace
    material_list_name::Union{Nothing,String}
    nuclide_list_name::Union{Nothing,String}
    scenario::Union{Nothing,String}
    scenarios::Vector{String}
    blocks::Dict{String,Vector{JDict}}
    disabled::Set{String}
    disabled_systems::Vector{String}
    off_reasons::Dict{String,String}
    implicitly_disabled::Dict{String,String}
    switched_off::Dict{String,Vector{JDict}}
    systems::Vector{String}
    transports::Vector{String}
    layout::JDict
    shapes::Vector{Any}
    derived::Vector{Any}
    view::Union{Nothing,JDict}
    ends_by_name::Union{Nothing,Dict{String,Any}}
    grid_cache::Any
    Project() = new()
end

Base.show(io::IO, p::Project) = print(io, "Project(", repr(p.name), ")")

blocks_of(p::Project, collection::AbstractString) = p.blocks[collection]

"""
    Project(raw) -> Project

A model (a dictionary as the file holds it), normalised and validated as the
application loads one.
"""
function Project(raw0::AbstractDict)
    p = Project()
    raw = migrate_keys(raw0)                      # a copy: the caller's is never changed
    p.name = get(raw, "name", nothing) !== nothing ? raw["name"] : "Untitled project"
    p.description = js_truthy(get(raw, "description", nothing)) ? raw["description"] : ""
    sim = JDict(SIMULATION_DEFAULTS)
    rs = get(raw, "simulation", nothing)
    if rs isa AbstractDict
        for (k, v) in rs
            sim[k] = v
        end
    end
    p.simulation = sim
    for key in ("start_time", "end_time", "output_points", "rtol", "abstol")
        v = get(sim, key, nothing)
        (v === nothing || (v isa Real && !(v isa Bool))) && continue
        n = js_number_of(v)
        isfinite(n) || throw(ValidationError("'$(js_text(v))' is not a number, and $(replace(key, '_' => ' ')) has to be one"))
        sim[key] = n
    end
    for (key, least, most, whole) in (("max_step", 0, Inf, false), ("initial_step", 0, Inf, false),
                                      ("max_steps", 1, Inf, true), ("max_order", 1, 5, true),
                                      ("min_order", 1, 5, true), ("newton_kappa", 0, 1, false),
                                      ("max_jac_age", 1, Inf, true), ("below_tol_run", 0, Inf, true),
                                      ("stagnation_tol", 0, 1, false))
        v = get(sim, key, nothing)
        if v === nothing || v == ""
            delete!(sim, key)
            continue
        end
        n = js_number_of(v)
        if !isfinite(n) || n < least || n > most || (whole && !isinteger(n))
            rng = most == Inf ? "of at least $least" : "between $least and $most"
            throw(ValidationError("'$(js_text(v))' is not a $(replace(key, '_' => ' ')): a " *
                                  "$(whole ? "whole number" : "number") $rng"))
        end
        sim[key] = n
    end
    if get(sim, "min_order", nothing) !== nothing &&
       js_number_of(sim["min_order"]) > js_number_of(get(sim, "max_order", 5))
        throw(ValidationError("The lowest order ($(js_text(sim["min_order"]))) is above the highest " *
                              "($(js_text(get(sim, "max_order", 5))))"))
    end
    for (key, allowed) in (("error_norm", ("rms", "max")), ("matrix", ("auto", "refactor", "sparse", "dense")),
                           ("jacobian", ("analytic", "numeric")))
        v = get(sim, key, nothing)
        if v === nothing || v == ""
            delete!(sim, key)
            continue
        end
        v in allowed || throw(ValidationError("'$(js_text(v))' is not a $(replace(key, '_' => ' ')) ($(join(allowed, ", ")))"))
    end
    sim["norm_control"] = js_truthy_switch(get(sim, "norm_control", nothing), false)
    sim["bdf"] = js_truthy_switch(get(sim, "bdf", nothing), false)
    sim["non_negative"] = js_truthy_switch(get(sim, "non_negative", true), true)
    sim["mass_balance"] = js_truthy_switch(get(sim, "mass_balance", nothing), false)
    sim["auto_abstol"] = js_truthy_switch(get(sim, "auto_abstol", nothing), false)
    n = js_number_of(get(sim, "iterations", nothing))
    n = isfinite(n) ? floor(n + 0.5) : n
    sim["iterations"] = isfinite(n) && n > 0 ? Int(n) : 1000
    s = js_number_of(get(sim, "seed", nothing))
    sim["seed"] = isfinite(s) ? Int(floor(s + 0.5)) : 1
    get(sim, "sampling", nothing) != "random" && (sim["sampling"] = "latin")
    haskey(TIME_UNITS, get(sim, "time_unit", nothing)) || throw(ValidationError("Unknown time unit '$(js_text(get(sim, "time_unit", nothing)))'"))
    get(sim, "spacing", nothing) in SPACINGS ||
        throw(ValidationError("'$(js_text(get(sim, "spacing", nothing)))' is not a way of choosing output times ($(join(SPACINGS, ", ")))"))
    p.output_times = normalise_series(get(sim, "output_times", nothing))
    sim["output_times"] = p.output_times
    p.output_mode = sim["spacing"] == "solver" ? "solver" : (sim["spacing"] == "both" ? "both" : "grid")
    p.solver_points = p.output_mode != "grid"

    p.nuclides = collect(Any, something(get(raw, "nuclides", nothing), Any[]))
    du = get(raw, "decay_unit", nothing)
    p.decay_unit = String(strip(js_str(du !== nothing ? du : "Bq")))
    ceiling = get(sim, "decay_ceiling", nothing) !== nothing ? js_number_of(sim["decay_ceiling"]) : NaN
    p.decay_ceiling = isfinite(ceiling) && ceiling > 0 ? ceiling : Inf
    p.decay_unit in DECAY_UNITS || throw(ValidationError("Unknown decay unit '$(p.decay_unit)' ($(join(DECAY_UNITS, " or ")))"))
    p.half_lives_override = JDict(something(get(raw, "half_lives", nothing), JDict()))
    p.half_lives = copy(_ICRP_HALF_LIVES)
    for (nuc, v) in p.half_lives_override
        v === nothing && continue
        if occursin(r"^(stable|inf(inity)?)$"i, strip(js_str(v)))
            p.half_lives[nuc] = Inf
            continue
        end
        years = js_number_of(v)
        (isfinite(years) && years > 0) ||
            throw(ValidationError("The half-life of '$nuc' must be a number of years greater than zero, or 'stable' -- " *
                                  "'$(js_text(v))' is neither.", nuc))
        p.half_lives[nuc] = years
    end
    # A list stated -- an empty one too, which means no decay chains -- replaces the default pairs.
    p.chains_override = chains_stated(get(raw, "chains", nothing)) ? Any[collect(Any, c) for c in raw["chains"]] : nothing
    p.raw = raw
    for pair in something(p.chains_override, Any[])
        parent = length(pair) > 0 ? pair[1] : nothing
        daughter = length(pair) > 1 ? pair[2] : nothing
        named = "[" * join((json_text(x; indent=0) for x in pair), ", ") * "]"
        if !(parent isa AbstractString) || isempty(strip(parent)) || !(daughter isa AbstractString) || isempty(strip(daughter))
            throw(ValidationError("A decay pair is [parent, daughter, branching]; $named does not name two nuclides."))
        end
        ratio = length(pair) > 2 ? pair[3] : nothing
        r = length(pair) < 3 ? 1.0 : js_number_of(ratio)
        if !isfinite(r) || r <= 0 || r > 1
            gives = length(pair) < 3 ? "none" : json_text(ratio; indent=0)
            throw(ValidationError("The branching from '$parent' to '$daughter' must be greater than zero and at most 1; " *
                                  "$named gives $gives."))
        end
        length(pair) < 3 && push!(pair, 1)
    end

    declared = desugar_nuclides(raw)
    lists = derive_block_lists(derive_elements(declared), raw)
    p.derived_lists = Set{String}(l["name"] for l in lists if js_truthy(get(l, "derived", nothing)))
    p.index_lists = normalise_index_lists(lists)
    try
        p.index_space = IndexSpace(p.index_lists)
    catch e
        e isa IndexSpaceError || rethrow()
        throw(ValidationError(e.message, e.detail))
    end
    materials = material_list(p.index_space)
    p.material_list_name = materials === nothing ? nothing : materials.name
    nuc = nuclide_list(p.index_space)
    p.nuclide_list_name = nuc === nothing ? p.material_list_name : nuc.name
    p.chains = p.chains_override !== nothing ? p.chains_override :
               Any[Any[c[1], c[2], c[3]] for c in default_chains(material_names(p))]
    if get(raw, "scenario", nothing) !== nothing && set_scenario!(p.index_space, raw["scenario"]) === nothing
        sc = scenarios(p.index_space)
        set_scenario!(p.index_space, isempty(sc) ? nothing : sc[1])
    end
    p.scenario = p.index_space.scenario
    p.scenarios = scenarios(p.index_space)

    p.ends_by_name = nothing
    p.blocks = Dict{String,Vector{JDict}}()
    for collection in BLOCK_COLLECTIONS
        p.blocks[collection] = JDict[]
    end
    for collection in BLOCK_COLLECTIONS
        kind = KIND_OF[collection]
        p.blocks[collection] = JDict[_normalise_block(p, b, kind) for b in something(get(raw, collection, nothing), Any[])
                                     if b isa AbstractDict]
    end

    p.disabled = Set{String}()
    ds = get(raw, "disabled_systems", nothing)
    p.disabled_systems = ds isa AbstractVector ?
                         String[strip(js_str(x)) for x in ds if x !== nothing && !isempty(strip(js_str(x)))] : String[]
    function off_by_system(block)
        home = js_truthy(get(block, "system", nothing)) ? block["system"] : ""
        home == "" && return nothing
        hits = sort!([q for q in p.disabled_systems if is_within(home, q)]; by=length)
        return isempty(hits) ? nothing : hits[1]
    end
    p.off_reasons = Dict{String,String}()
    p.switched_off = Dict{String,Vector{JDict}}()
    for collection in BLOCK_COLLECTIONS
        kept, off = JDict[], JDict[]
        for b in p.blocks[collection]
            by = get(b, "enabled", nothing) === false ? nothing : off_by_system(b)
            if get(b, "enabled", nothing) === false || by !== nothing
                push!(p.disabled, b["qname"])
                push!(off, b)
                by !== nothing && (p.off_reasons[b["qname"]] = "it is in '$by', which is disabled")
            else
                push!(kept, b)
            end
        end
        p.blocks[collection] = kept
        isempty(off) || (p.switched_off[collection] = off)
    end
    block_systems = String[]
    for c in COLLECTIONS, b in something(get(raw, c, nothing), Any[])
        b isa AbstractDict && push!(block_systems, js_truthy(get(b, "system", nothing)) ? string(b["system"]) : "")
    end
    p.systems = system_paths(something(get(raw, "systems", nothing), Any[]), something(get(raw, "transports", nothing), Any[]),
                             block_systems)
    tr = get(raw, "transports", nothing)
    p.transports = tr isa AbstractVector ?
                   unique(String[strip(js_str(something(x, ""))) for x in tr if !isempty(strip(js_str(something(x, ""))))]) :
                   String[]
    for q in p.disabled_systems
        q in p.systems || throw(ValidationError("'$q' is listed as a disabled sub-system, but there is no sub-system of that name", q))
    end
    _resolve_endpoints!(p)
    p.layout = JDict(something(get(raw, "layout", nothing), JDict()))
    p.shapes = get(raw, "shapes", nothing) isa AbstractVector ? jcopy(raw["shapes"]) : Any[]
    p.derived = get(raw, "derived", nothing) isa AbstractVector ? jcopy(raw["derived"]) : Any[]
    p.view = js_truthy(get(raw, "view", nothing)) ? JDict(raw["view"]) : nothing
    p.grid_cache = nothing
    validate!(p)
    return p
end

material_names(p::Project) = p.material_list_name === nothing ? String[] : index_names(p.index_space, p.material_list_name)
nuclide_names(p::Project) = p.nuclide_list_name === nothing ? String[] : index_names(p.index_space, p.nuclide_list_name)

function _normalise_block(p::Project, raw::AbstractDict, kind::String)
    base = merge(jcopy(BLOCK_DEFAULTS[kind]), JDict(raw))
    base["kind"] = kind
    roles = get(TRANSPORT_ROLES, kind, ())
    role = get(raw, "transport", nothing) in roles ? raw["transport"] : nothing
    if role !== nothing
        base["transport"] = role
    else
        delete!(base, "transport")
    end
    role == "counter" && (base["equation"] = "1")
    if role == "operation"
        base["operation"] = something(_transport_operation(get(raw, "operation", nothing)), "mean")
        base["argument"] = something(_transport_argument(get(raw, "argument", nothing)), "all")
    end
    kind == "compartment" && (base["non_negative"] = get(base, "non_negative", nothing) !== false)
    kind == "transfer" && (base["multiply_by_donor"] = get(base, "multiply_by_donor", nothing) !== false)
    if kind in ("transfer", "inflow")
        sei = get(base, "sum_extra_indices", nothing)
        if sei === true || sei == "true"
            base["sum_extra_indices"] = true
        else
            delete!(base, "sum_extra_indices")
        end
    end
    base["comment"] = get(raw, "comment", nothing) !== nothing ? raw["comment"] : ""
    if kind == "lookup"
        interp = get(raw, "interpolation", nothing)
        base["interpolation"] = (interp === nothing || interp == "") ? "linear" :
                                something(get(INTERPOLATION_FROM_ECO, strip(js_str(interp)), nothing), interp)
        base["cyclic"] = js_truthy(get(raw, "cyclic", nothing))
        base["argument"] = js_truthy(get(raw, "argument", nothing)) ? js_str(raw["argument"]) : nothing
        base["points"] = normalise_points(get(raw, "points", nothing), get(raw, "name", ""))
    end
    if kind in ("index_reduction", "block_reduction")
        op = get(raw, "operation", nothing)
        base["operation"] = (op === nothing || op == "") ? "sum" : something(get(OPERATION_FROM_ECO, strip(js_str(op)), nothing), op)
    end
    if kind == "index_reduction"
        base["target"] = get(raw, "target", nothing) === nothing ? nothing : js_str(raw["target"])
        base["percentile"] = get(raw, "percentile", nothing) === nothing ? nothing : js_number_of(raw["percentile"])
    end
    kind == "block_reduction" && (base["targets"] = normalise_targets(get(raw, "targets", nothing), get(raw, "name", "")))
    if kind == "function"
        params = get(raw, "parameters", nothing)
        base["parameters"] = String[strip(js_str(x)) for x in (params isa AbstractVector ? params : Any[])
                                    if x !== nothing && !isempty(strip(js_str(x)))]
        base["equation"] = get(raw, "equation", nothing) === nothing ? "" : js_str(raw["equation"])
        base["system"] = js_truthy(get(raw, "system", nothing)) ? raw["system"] : ""
        base["index_lists"] = String[]
        base["entries"] = Any[]
        base["qname"] = qualified_name(base)
        return base
    end
    if kind == "min_max"
        op = get(raw, "operation", nothing)
        base["operation"] = (op === nothing || op == "") ? "max" : something(_extreme(op), op)
    end
    if kind == "farfield"
        for key in FARF_STRUCTURE_KEYS
            given = get(raw, key, nothing) !== nothing ? raw[key] : BLOCK_DEFAULTS["farfield"][key]
            if key == "n_b" && (given === nothing || (given isa AbstractString && isempty(strip(given))))
                base[key] = ""
                continue
            end
            v = js_number_of(given)
            base[key] = isfinite(v) ? Int(floor(v + 0.5)) : get(raw, key, nothing)
        end
        s = get(raw, "surface", nothing)
        base["surface"] = (s === nothing || s == "") ? surface_of(raw) : s
        used = SURFACE_KEY[surface_of(base)]
        get(base, used, nothing) === nothing && (base[used] = FARF_SURFACE_DEFAULTS[used])
        delete!(base, "to")
    end
    if kind == "waste_package"
        f = get(raw, "failure", nothing)
        base["failure"] = (f === nothing || f == "") ? "never" : f
        np = get(raw, "packages", nothing)
        n = js_number_of(np !== nothing ? np : WASTE_DEFAULTS["packages"])
        base["packages"] = isfinite(n) ? Int(floor(n + 0.5)) : np
        v = get(raw, "handle_decay", nothing)
        base["handle_decay"] = !(v === false || v == "false" || (v isa Real && !(v isa Bool) && v == 0))
        delete!(base, "to")
    end
    if kind == "event"
        t = get(raw, "timing", nothing)
        base["timing"] = (t === nothing || t == "") ? "at" : t
        v = get(raw, "sampled", nothing)
        base["sampled"] = !(v === false || v == "false" || (v isa Real && !(v isa Bool) && v == 0))
        base["actions"] = normalise_actions(get(raw, "actions", nothing))
    end
    if kind == "trigger"
        d = get(raw, "direction", nothing)
        base["direction"] = (d === nothing || d == "") ? "rising" :
                            something(get(DIRECTION_FROM_ECO, uppercase(strip(js_str(d))), nothing), d)
    end
    base["index_lists"] = _dimensions_for(p, raw, kind)
    kind == "event" && (base["index_lists"] = String[])
    unit = get(raw, "unit", nothing)
    unit === nothing && kind in ("transfer", "inflow") && (unit = _derived_unit(p, base, kind))
    unit === nothing && kind == "compartment" && (unit = _inventory_unit(p, base))
    unit === nothing && kind in ("farfield", "waste_package") && (unit = "$(p.decay_unit)/$(p.simulation["time_unit"])")
    if unit === nothing
        u = get(BLOCK_DEFAULTS[kind], "unit", nothing)
        unit = js_truthy(u) ? u : ""
    end
    base["unit"] = unit
    get(base, "transport", nothing) in ("number", "counter") && (base["unit"] = "")
    base["system"] = js_truthy(get(raw, "system", nothing)) ? raw["system"] : ""
    base["qname"] = qualified_name(base)
    base["entries"] = normalise_entries(raw, kind, p.nuclide_list_name, base["index_lists"])
    if kind == "transfer"
        raws = get(raw, "entries", nothing) isa AbstractVector ? raw["entries"] : Any[]
        at = findfirst(e -> e isa AbstractDict && haskey(e, "multiply_by_donor") &&
                                (e["multiply_by_donor"] !== false) != base["multiply_by_donor"], raws)
        if at !== nothing
            index = at <= length(base["entries"]) ? get(base["entries"][at], "index", nothing) : nothing
            where_ = join((js_str(v) for v in values(something(index, JDict()))), ", ")
            isempty(where_) && (where_ = "one of its entries")
            said = base["multiply_by_donor"] ? "It multiplies its rate by the donor" : "Its rate is an absolute flux"
            throw(ValidationError("$said, and $where_ says otherwise. That is one setting for the whole transfer -- it " *
                                  "makes the rate a coefficient or a flux, and gives it its unit -- so a model that needs " *
                                  "both has two transfers between the same compartments: one by the donor and one an " *
                                  "absolute flux, each with a zero rate where the other applies.", get(base, "name", nothing)))
        end
    end
    get(base, "initial", nothing) isa AbstractDict && (base["initial"] = "0")
    if kind == "compartment"
        for holder in Any[base, base["entries"]...]
            haskey(holder, "dydt") || continue
            if holder["dydt"] === nothing || isempty(strip(js_str(holder["dydt"])))
                delete!(holder, "dydt")
            else
                holder["dydt"] = js_str(holder["dydt"])
            end
        end
    end
    vk = get(VALUE_KEYS, kind, nothing)
    value_key = vk === nothing ? nothing : vk[1]
    if value_key !== nothing && haskey(raw, "default") && !haskey(raw, value_key)
        base[value_key] = raw["default"]
    end
    for key in ("values_by_nuclide", "default", "per_nuclide")
        delete!(base, key)
    end
    return base
end

function _derived_unit(p::Project, block, kind)
    t = js_truthy(get(p.simulation, "time_unit", nothing)) ? p.simulation["time_unit"] : "year"
    function unit_of(name)
        name === nothing && return ""
        cs = isdefined(p, :blocks) ? get(p.blocks, "compartments", JDict[]) : JDict[]
        c = findfirst_value(x -> x["qname"] == name, cs)
        c === nothing && (c = findfirst_value(x -> get(x, "name", nothing) == name, cs))
        return c === nothing ? "" : String(strip(js_str(something(get(c, "unit", nothing), ""))))
    end
    per(q) = occursin(r"[/\s]", q) ? "($q)/$t" : "$q/$t"
    if kind == "inflow"
        u = unit_of(get(block, "to", nothing))
        return isempty(u) ? "" : per(u)
    end
    get(block, "multiply_by_donor", nothing) !== false && return "1/$t"
    fr = get(block, "from", nothing)
    u = unit_of(fr !== nothing ? fr : get(block, "to", nothing))
    return isempty(u) ? "" : per(u)
end

function _inventory_unit(p::Project, base)
    dims = something(get(base, "index_lists", nothing), String[])
    function is_material(d)
        l = findfirst_value(x -> x["name"] == d, p.index_lists)
        l === nothing && return false
        return js_truthy(get(l, "for_contaminants", nothing)) || js_truthy(get(l, "for_nuclides", nothing)) ||
               (js_truthy(get(l, "sub_set_of", nothing)) && l["sub_set_of"] == p.material_list_name)
    end
    material = findfirst_value(is_material, dims)
    material === nothing && return p.decay_unit
    return dimension_unit(p, material)
end

function material_unit(p::Project, name)
    lists = p.index_lists
    catalogue = findfirst_value(l -> js_truthy(get(l, "for_contaminants", nothing)), lists)
    own = catalogue === nothing ? nothing : findfirst_value(i -> get(i, "name", nothing) == name, catalogue["indices"])
    stated = own === nothing ? "" : strip(js_str(something(get(own, "unit", nothing), "")))
    isempty(stated) || return String(stated)
    nuclides = findfirst_value(l -> js_truthy(get(l, "for_nuclides", nothing)), lists)
    nuclides === nothing && (nuclides = catalogue)
    is_nuclide = nuclides !== nothing ? any(i -> get(i, "name", nothing) == name, nuclides["indices"]) : name in p.nuclides
    return is_nuclide ? (p.decay_unit == "mol" ? "mol" : "Bq") : ""
end

function dimension_unit(p::Project, list_name)
    lists = p.index_lists
    lst = findfirst_value(l -> get(l, "name", nothing) == list_name, lists)
    if lst === nothing
        return any(l -> js_truthy(get(l, "for_contaminants", nothing)) || js_truthy(get(l, "for_nuclides", nothing)), lists) ?
               "" : (p.decay_unit == "mol" ? "mol" : "Bq")
    end
    one = nothing
    for i in lst["indices"]
        get(i, "enabled", nothing) === false && continue
        u = material_unit(p, get(i, "name", nothing))
        isempty(u) && return ""
        if one === nothing
            one = u
        elseif one != u
            return ""
        end
    end
    return something(one, "")
end

function _endpoint_dims(p::Project, name)
    name === nothing && return nothing
    if p.ends_by_name === nothing
        p.ends_by_name = Dict{String,Any}()
        for key in ("compartments", "farfields", "waste_packages")
            for b in something(get(p.raw, key, nothing), Any[])
                (b isa AbstractDict && js_truthy(get(b, "name", nothing))) && (p.ends_by_name[qualified_name(b)] = b)
            end
        end
    end
    ends = p.ends_by_name
    q = something(resolve_reference(name, "", n -> haskey(ends, n)), name)
    end_ = get(ends, q, nothing)
    end_ === nothing && return nothing
    if get(end_, "index_lists", nothing) isa AbstractVector
        try
            return normalise_dims(end_["index_lists"])
        catch e
            e isa IndexSpaceError || rethrow()
            throw(ValidationError(e.message, get(end_, "name", nothing)))
        end
    end
    implied = (p.nuclide_list_name !== nothing && list_size(p.index_space, p.nuclide_list_name) > 0) ?
              p.nuclide_list_name : p.material_list_name
    return (js_truthy(implied) && get(end_, "per_nuclide", nothing) !== false) ? [implied] : String[]
end

function _dimensions_for(p::Project, raw, kind)
    kind == "function" && return String[]
    if get(raw, "index_lists", nothing) isa AbstractVector
        dims = try
            normalise_dims(raw["index_lists"])
        catch e
            e isa IndexSpaceError || rethrow()
            throw(ValidationError(e.message, get(raw, "name", nothing)))
        end
        for d in dims
            has_list(p.index_space, d) || throw(ValidationError("Unknown index list '$d'", get(raw, "name", nothing)))
            lst = findfirst_value(l -> l["name"] == d, p.index_lists)
            list_applies(lst, kind) || throw(ValidationError(list_applies_why(lst, kind), get(raw, "name", nothing)))
        end
        clash = clashing_dimensions(p.index_lists, dims)
        clash === nothing || throw(ValidationError(clashing_dimensions_why(clash), get(raw, "name", nothing)))
        return dims
    end
    if kind in ("transfer", "inflow")
        shared = shared_dims(p.index_lists, _endpoint_dims(p, get(raw, "from", nothing)), _endpoint_dims(p, get(raw, "to", nothing)))
        shared !== nothing && return collect(String, shared.dims)
    end
    implied = (p.nuclide_list_name !== nothing && list_size(p.index_space, p.nuclide_list_name) > 0) ?
              p.nuclide_list_name : p.material_list_name
    (js_truthy(implied) && get(raw, "per_nuclide", nothing) !== false) && return [implied]
    return String[]
end

function blocks_by_name(p::Project)
    out = OrderedDict{String,JDict}()
    for collection in COLLECTIONS
        for b in get(p.blocks, collection, JDict[])
            haskey(out, b["qname"]) && throw(ValidationError("Duplicate block name '$(b["qname"])'", b["qname"]))
            out[b["qname"]] = b
        end
    end
    return out
end

all_blocks(p::Project) = JDict[b for c in COLLECTIONS for b in get(p.blocks, c, JDict[])]

function _resolve_endpoints!(p::Project)
    ends = Set{String}(b["qname"] for c in ("compartments", "farfields", "waste_packages") for b in p.blocks[c])
    known = n -> n in ends
    for conn in Iterators.flatten((p.blocks["transfers"], p.blocks["inflows"]))
        for end_ in ("from", "to")
            ref = get(conn, end_, nothing)
            ref === nothing && continue
            conn[end_] = known(ref) ? ref :
                         something(resolve_reference(ref, js_truthy(get(conn, "system", nothing)) ? conn["system"] : "", known), ref)
        end
    end
    _follow_disabled_ends!(p)
end

function _follow_disabled_ends!(p::Project)
    p.implicitly_disabled = copy(p.off_reasons)
    kept = JDict[]
    for t in p.blocks["transfers"]
        if get(t, "from", nothing) !== nothing && t["from"] in p.disabled
            p.implicitly_disabled[t["qname"]] = "its donor '$(t["from"])' is disabled, so there is no inventory for it to move"
            push!(p.disabled, t["qname"])
            continue
        end
        if get(t, "to", nothing) !== nothing && t["to"] in p.disabled
            p.implicitly_disabled["$(t["qname"])#to"] = "it flows into '$(t["to"])', which is disabled, so what it moves " *
                                                         "leaves the model"
            t["to"] = nothing
        end
        push!(kept, t)
    end
    p.blocks["transfers"] = kept
    kept = JDict[]
    for s in p.blocks["inflows"]
        if get(s, "to", nothing) !== nothing && s["to"] in p.disabled
            p.implicitly_disabled[s["qname"]] = "it flows into '$(s["to"])', which is disabled, so there is nothing for it to feed"
            push!(p.disabled, s["qname"])
            continue
        end
        push!(kept, s)
    end
    p.blocks["inflows"] = kept
end

decay_model(p::Project) = decay_model_for(p, p.material_list_name)

function decay_model_for(p::Project, list_name)
    names = (list_name !== nothing && has_list(p.index_space, list_name)) ? index_names(p.index_space, list_name) : String[]
    chains = p.chains_override !== nothing ? p.chains_override :
             Any[Any[c[1], c[2], c[3]] for c in default_chains(names; ceiling=p.decay_ceiling)]
    return build_decay_model(names, p.simulation["time_unit"], p.half_lives, p.decay_unit, chains)
end

function validate!(p::Project)
    names = Set{String}()
    order = ("parameters", "compartments", "expressions", "transfers", "inflows", "lookups", "index_reductions",
             "block_reductions", "min_maxes", "running_means", "snapshots", "delays", "triggers", "farfields",
             "waste_packages", "events", "functions")
    everything = JDict[b for c in order for b in p.blocks[c]]
    for b in everything
        bname = get(b, "name", nothing)
        (js_truthy(bname) && occursin(NAME_RE, string(bname))) ||
            throw(ValidationError("'$(js_text(bname))' is not a valid name (letters, digits and underscore; must not start " *
                                  "with a digit)", bname === nothing ? nothing : string(bname)))
        bname in RESERVED && throw(ValidationError("'$bname' is a reserved name", bname))
        is_valid_path(get(b, "system", nothing)) ||
            throw(ValidationError("'$(js_text(get(b, "system", nothing)))' is not a valid sub-system path", b["qname"]))
        b["qname"] in p.systems && throw(ValidationError("'$(b["qname"])' is both a block and a sub-system, and the two " *
                                                         "cannot share a name", b["qname"]))
        if b["qname"] in names
            sys = get(b, "system", "")
            throw(ValidationError("Duplicate block name '$(b["qname"])'" * (js_truthy(sys) ? " in sub-system '$sys'" : ""),
                                  b["qname"]))
        end
        push!(names, b["qname"])
    end
    for c in p.blocks["compartments"]
        for holder in Any[c, c["entries"]...]
            v0 = get(holder, "abstol", nothing)
            (v0 === nothing || v0 == "") && continue
            v = js_number_of(v0)
            (isfinite(v) && v > 0) && continue
            where_ = holder !== c ? get(holder, "index", nothing) : nothing
            at = (where_ !== nothing && !isempty(where_)) ? " for $(join((js_str(x) for x in values(where_)), ", "))" : ""
            throw(ValidationError("Absolute tolerance$at must be a number greater than zero (got $(js_text(v0)))", c["qname"]))
        end
    end
    compartments = Set(c["qname"] for c in p.blocks["compartments"])
    paths = Set(b["qname"] for b in Iterators.flatten((p.blocks["farfields"], p.blocks["waste_packages"])))
    releasing = Dict{String,String}()
    for t in p.blocks["transfers"]
        fr = get(t, "from", nothing)
        (fr === nothing || !(fr in paths)) && continue
        held = get(releasing, fr, nothing)
        if held !== nothing
            throw(ValidationError("'$fr' has two releases, '$held' and '$(t["name"])'. A block has one -- for a path the " *
                                  "flux out of the far end, for waste packages what leaves them -- and each of these " *
                                  "would deliver the whole of it, so the model would release twice what the block let go.",
                                  t["name"]))
        end
        releasing[fr] = t["name"]
    end
    for t in p.blocks["transfers"]
        fr, to = get(t, "from", nothing), get(t, "to", nothing)
        fr !== nothing && !(fr in compartments) && !(fr in paths) &&
            throw(ValidationError("Unknown source compartment '$fr'", t["name"]))
        to !== nothing && !(to in compartments) && !(to in paths) &&
            throw(ValidationError("Unknown target compartment '$to'", t["name"]))
        if fr !== nothing && fr in paths
            get(t, "multiply_by_donor", nothing) !== false &&
                throw(ValidationError("'$fr' is a far-field path, so there is no single donor inventory to multiply by: a " *
                                      "release carries the flux out of the path itself.", t["name"]))
            to !== nothing && to in paths &&
                throw(ValidationError("A release from one far-field path cannot be delivered straight into another: give " *
                                      "it a compartment in between.", t["name"]))
        end
        fr === nothing && to === nothing && throw(ValidationError("A transfer must have a source, a target, or both", t["name"]))
        fr == to && throw(ValidationError("Source and target are both '$(js_text(fr))'", t["name"]))
    end
    for s in p.blocks["inflows"]
        to = get(s, "to", nothing)
        (to in compartments || to in paths) || throw(ValidationError("Unknown target compartment '$(js_text(to))'", s["name"]))
    end
    holds = Dict{String,JDict}(b["qname"] => b for c in ("compartments", "farfields", "waste_packages") for b in p.blocks[c])
    size_of(name) = has_list(p.index_space, name) ? list_size(p.index_space, name) : nothing
    for flux in Iterators.flatten((p.blocks["transfers"], p.blocks["inflows"]))
        js_truthy(get(flux, "sum_extra_indices", nothing)) && continue
        for end_ in ("from", "to")
            e = get(flux, end_, nothing)
            at = e === nothing ? nothing : get(holds, e, nothing)
            at === nothing && continue
            summed = summed_dims(p.index_lists, flux["index_lists"], at["index_lists"])
            isempty(summed) && continue
            throw(ValidationError(summed_dims_why(flux["qname"], end_, at["qname"], summed, size_of), flux["qname"]))
        end
    end
    for prob in waste_problems(p)
        throw(ValidationError(prob.message, prob.name))
    end
    for prob in disruption_problems(p)
        throw(ValidationError(prob.message, prob.name))
    end
    root = p.material_list_name !== nothing ? get_list(p.index_space, p.material_list_name).root_name : nothing
    for f in Iterators.flatten((p.blocks["farfields"], p.blocks["waste_packages"]))
        if f["kind"] == "farfield"
            problem = something(structure_problem(f), geometry_problem(f), rock_problem(f), Some(nothing))
            problem !== nothing && throw(ValidationError(problem, f["qname"]))
        end
        chains = [d for d in f["index_lists"] if root !== nothing && has_list(p.index_space, d) &&
                  get_list(p.index_space, d).mapping === nothing && get_list(p.index_space, d).root_name == root]
        if length(chains) > 1
            what = f["kind"] == "farfield" ? "A far-field path runs" : "Waste packages run"
            throw(ValidationError("$what one decay chain along one dimension, and '$(f["name"])' is indexed by " *
                                  "$(length(chains)) of them ($(join(chains, " × "))). A sub-set of the radionuclides is a " *
                                  "second set of the same nuclides: pick the one the path carries.", f["qname"]))
        end
    end
    for l in p.blocks["lookups"]
        l["interpolation"] in INTERPOLATIONS ||
            throw(ValidationError("'$(js_text(l["interpolation"]))' is not an interpolation rule ($(join(INTERPOLATIONS, ", ")))", l["qname"]))
        arg = get(l, "argument", nothing)
        arg !== nothing && !occursin(NAME_RE, string(arg)) &&
            throw(ValidationError("'$arg' is not a valid argument name", l["qname"]))
    end
    for f in p.blocks["functions"]
        seen = Set{String}()
        for q in f["parameters"]
            occursin(NAME_RE, q) || throw(ValidationError("'$q' is not a valid parameter name (letters, digits and " *
                                                          "underscore; must not start with a digit)", f["qname"]))
            q in RESERVED && throw(ValidationError("'$q' is a reserved name, so it cannot be a parameter", f["qname"]))
            q in seen && throw(ValidationError("'$q' is named twice in the parameters of '$(f["name"])'", f["qname"]))
            push!(seen, q)
        end
    end
    for o in p.blocks["index_reductions"]
        o["operation"] in OPERATIONS ||
            throw(ValidationError("'$(js_text(o["operation"]))' is not a reduction ($(join(OPERATIONS, ", ")))", o["qname"]))
        if o["operation"] == "percentile"
            pc = get(o, "percentile", nothing)
            (pc !== nothing && 0 <= pc <= 100) ||
                throw(ValidationError("A percentile must be between 0 and 100; '$(py_text(pc))' is not", o["qname"]))
        end
        js_truthy(get(o, "target", nothing)) || throw(ValidationError("An index operation needs a block to reduce", o["qname"]))
    end
    for m in p.blocks["min_maxes"]
        m["operation"] in EXTREMES ||
            throw(ValidationError("'$(js_text(m["operation"]))' is not a min/max operation ($(join(EXTREMES, ", ")))", m["qname"]))
    end
    for e in p.blocks["triggers"]
        e["direction"] in DIRECTIONS ||
            throw(ValidationError("'$(js_text(e["direction"]))' is not a crossing direction ($(join(DIRECTIONS, ", ")))", e["qname"]))
    end
    for a in p.blocks["block_reductions"]
        a["operation"] in AGGREGATE_OPERATIONS ||
            throw(ValidationError("'$(js_text(a["operation"]))' is not a reduction an aggregate can do " *
                                  "($(join(AGGREGATE_OPERATIONS, ", ")))", a["qname"]))
        if isempty(a["targets"]) && !any(e -> js_truthy(get(e, "targets", nothing)), a["entries"])
            throw(ValidationError("An aggregate needs at least one block to reduce", a["qname"]))
        end
    end
    unknown = [n for n in nuclide_names(p) if get(p.half_lives, n, nothing) === nothing]
    if !isempty(unknown)
        throw(ValidationError("No half-life for $(join(unknown, ", ")). Set one on the Decay tab -- or type \"stable\" " *
                              "there for a nuclide that does not decay -- or give it under \"half_lives\" in the project file."))
    end
    for b in everything
        for entry in b["entries"]
            for (list_name, index_name) in something(get(entry, "index", nothing), JDict())
                has_list(p.index_space, list_name) ||
                    throw(ValidationError("Entry refers to unknown index list '$list_name'", b["name"]))
                list_name in b["index_lists"] ||
                    throw(ValidationError("Entry is keyed by '$list_name', which '$(b["name"])' is not indexed by", b["name"]))
                any(i -> i.name == index_name, get_list(p.index_space, list_name).indices) ||
                    throw(ValidationError("'$(js_text(index_name))' is not an index of '$list_name'", b["name"]))
            end
        end
    end
    sim = p.simulation
    start, end_ = sim["start_time"], sim["end_time"]
    end_ > start || throw(ValidationError("End time must be greater than start time"))
    sim["spacing"] == "log" && start < 0 && throw(ValidationError("Logarithmic output needs a non-negative start time"))
    points = get(sim, "output_points", nothing)
    if !(sim["spacing"] in ("series", "both")) && !(points !== nothing && points >= 2)
        throw(ValidationError("At least 2 output points are required"))
    end
    points !== nothing && points > MAX_OUTPUT_POINTS &&
        throw(ValidationError("$(js_text(points)) output points is more than this can report ($MAX_OUTPUT_POINTS)."))
    for (key, label) in (("rtol", "Relative"), ("abstol", "Absolute"))
        v = js_number_of(get(sim, key, nothing))
        v > 0 || throw(ValidationError("$label tolerance must be greater than zero (got $(py_text(get(sim, key, nothing))))"))
    end
    return p
end

"""How Python's f-string shows a value in a message (`None`, `1e-05`)."""
py_text(v::Nothing) = "None"
py_text(v::Bool) = v ? "True" : "False"
py_text(v::Integer) = string(v)
py_text(v::AbstractFloat) = py_repr(v)
py_text(v) = string(v)

function waste_problems(p::Project)
    out = NamedTuple{(:name, :field, :message),Tuple{String,String,String}}[]
    for b in p.blocks["waste_packages"]
        name = b["qname"]
        f = js_truthy(get(b, "failure", nothing)) ? b["failure"] : "never"
        if !(f in FAILURES)
            push!(out, (name=name, field="failure", message="'$(js_text(f))' is not a way for packages to fail ($(join(FAILURES, ", ")))."))
            continue
        end
        for key in FAILURE_KEYS[f]
            if isempty(strip(js_str(something(get(b, key, nothing), ""))))
                push!(out, (name=name, field=key, message="Packages that fail $(FAILURE_LABEL[f]) need " *
                                                          "$(lowercase(WASTE_LABEL[key])): a number or an equation."))
            end
        end
        function num(key)
            v = js_number_of(strip(js_str(something(get(b, key, nothing), ""))))
            return isfinite(v) ? v : nothing
        end
        if f == "uniform"
            a, z = num("fail_from"), num("fail_to")
            if a !== nothing && z !== nothing && !(z > a)
                push!(out, (name=name, field="fail_to", message="The failures end ($(js_number(z))) before they begin ($(js_number(a)))."))
            end
        end
        if f == "weibull" && num("fail_shape") !== nothing && !(num("fail_shape") > 0)
            push!(out, (name=name, field="fail_shape", message="A Weibull shape has to be above 0."))
        end
        if f == "weibull" && num("fail_scale") !== nothing && !(num("fail_scale") > 0)
            push!(out, (name=name, field="fail_scale", message="A Weibull scale has to be above 0."))
        end
        if f == "exponential" && num("fail_rate") !== nothing && num("fail_rate") < 0
            push!(out, (name=name, field="fail_rate", message="A failure rate cannot be negative."))
        end
        np = get(b, "packages", nothing)
        if np !== nothing && np != ""
            n = js_number_of(np)
            if !(isfinite(n) && isinteger(n)) || n < 1
                push!(out, (name=name, field="packages", message="'$(js_text(np))' is not a number of packages: a whole number, at least 1."))
            end
        end
        for (values_, where_) in Any[(b, nothing), ((e, get(e, "index", nothing)) for e in something(get(b, "entries", nothing), Any[]))...]
            function at(key)
                text = strip(js_str(something(get(values_, key, nothing), "")))
                v = js_number_of(text)
                return (!isempty(text) && isfinite(v)) ? v : nothing
            end
            cell = (where_ !== nothing && !isempty(where_)) ? " (at $(join((js_str(x) for x in values(where_)), " · ")))" : ""
            irf = at("irf")
            if irf !== nothing && (irf < 0 || irf > 1)
                push!(out, (name=name, field="irf", message="The instant release fraction is between 0 and 1$cell."))
            end
            d = at("degradation_rate")
            if d !== nothing && d < 0
                push!(out, (name=name, field="degradation_rate", message="A degradation rate cannot be negative$cell."))
            end
        end
    end
    return out
end

function disruption_problems(p::Project)
    out = NamedTuple{(:name, :field, :message),Tuple{String,String,String}}[]
    wastes = Set(w["qname"] for w in p.blocks["waste_packages"])
    compartments = Set(c["qname"] for c in p.blocks["compartments"])
    for b in p.blocks["events"]
        name = b["qname"]
        timing = js_truthy(get(b, "timing", nothing)) ? b["timing"] : "at"
        if !(timing in TIMINGS)
            push!(out, (name=name, field="timing", message="'$(js_text(timing))' is not a way for an event to happen ($(join(TIMINGS, ", ")))."))
            continue
        end
        if timing == "at" && isempty(strip(js_str(something(get(b, "at", nothing), ""))))
            push!(out, (name=name, field="at", message="An event at a time needs the time: a number or an equation."))
        end
        if timing == "poisson" && isempty(strip(js_str(something(get(b, "rate", nothing), ""))))
            push!(out, (name=name, field="rate", message="A random event needs its rate: occurrences per unit time."))
        end
        function num(text)
            t = strip(js_str(something(text, "")))
            isempty(t) && return nothing
            v = js_number_of(t)
            return isfinite(v) ? v : nothing
        end
        if timing == "poisson" && num(get(b, "rate", nothing)) !== nothing && num(get(b, "rate", nothing)) < 0
            push!(out, (name=name, field="rate", message="A rate cannot be negative."))
        end
        fr, un = num(get(b, "from", nothing)), num(get(b, "until", nothing))
        if timing == "poisson" && fr !== nothing && un !== nothing && !(un > fr)
            push!(out, (name=name, field="until", message="The window ends ($(py_text(un))) before it opens ($(py_text(fr)))."))
        end
        for (k, a) in enumerate(normalise_actions(get(b, "actions", nothing)))
            field = "actions[$(k - 1)]"
            if !(a["kind"] in ACTIONS)
                push!(out, (name=name, field=field, message="'$(a["kind"])' is not something an event can do ($(join(ACTIONS, ", ")))."))
                continue
            end
            if a["kind"] == "fail"
                if !js_truthy(get(a, "block", nothing))
                    push!(out, (name=name, field=field, message="Which packages fail? Name a waste-package block."))
                elseif !(a["block"] in wastes)
                    push!(out, (name=name, field=field, message="'$(a["block"])' is not a set of waste packages, so it has no packages to fail."))
                end
            else
                if !js_truthy(get(a, "from", nothing))
                    push!(out, (name=name, field=field, message="Move what? Name a compartment."))
                elseif !(a["from"] in compartments)
                    push!(out, (name=name, field=field, message="'$(a["from"])' is not a compartment, so there is nothing to move out of it."))
                end
                if get(a, "to", nothing) !== nothing && !(a["to"] in compartments)
                    push!(out, (name=name, field=field, message="'$(a["to"])' is not a compartment, so nothing can be moved into it."))
                end
                if get(a, "to", nothing) !== nothing && a["to"] == get(a, "from", nothing)
                    push!(out, (name=name, field=field, message="Moving $(a["from"]) into itself changes nothing."))
                end
            end
            f = num(get(a, "fraction", nothing))
            if f !== nothing && (f < 0 || f > 1)
                push!(out, (name=name, field=field, message="A share is between 0 and 1; $(py_text(f)) is not."))
            end
        end
    end
    return out
end

# --- the output grid -----------------------------------------------------------------

"""The output times: one series over the run, or the combined list of series."""
function time_grid(p::Project)
    sim = p.simulation
    key = (sim["start_time"], sim["end_time"], get(sim, "output_points", nothing), sim["spacing"],
           isempty(p.output_times) ? nothing : json_text(p.output_times; indent=0))
    if p.grid_cache === nothing || p.grid_cache[1] != key
        p.grid_cache = (key, _time_grid(p, key[1], key[2], key[3], key[4]))
    end
    return copy(p.grid_cache[2])
end

function _time_grid(p::Project, start, end_, points, spacing)
    start = Float64(start)
    end_ = Float64(end_)
    if spacing == "series" || (spacing == "both" && !isempty(p.output_times))
        return combine_series(p.output_times, start, end_)
    end
    n = max(2, Int(floor(Float64(points) + 0.5)))
    t = zeros(n)
    if spacing in ("log", "solver", "both")
        lo = start > 0 ? start : max(end_, 1.0) * 1e-6
        a, b = js_log(lo), js_log(end_)
        t[1] = start
        for i in 1:n-1
            t[i+1] = js_exp(a + ((b - a) * i) / (n - 1))
        end
        t[n] = end_
    else
        for i in 0:n-1
            t[i+1] = start + ((end_ - start) * i) / (n - 1)
        end
    end
    return t
end
