# Views onto the rest of a model's dictionary (the Python package's IndexList,
# Shape and View in model.py, and simulation.py): an index list, a shape
# drawn on a canvas, what the diagram shows, and the simulation settings,
# each read and written in place and checked as the application checks it.
# And the model's own properties: `m.name`, `m.simulation`, `m.decay_unit`,
# ... beside its fields `m.raw`, `m.path` and `m.import_report`.

# --- an index list ------------------------------------------------------------------------------------------

"""
    IndexListView

One index list of a model, as a view onto its dictionary: `l.name`,
`l.indices`, `l.enabled_indices`, `l.subset_of`, `l.mapping`, `l.comment`,
... Edits go through the model, which carries a renamed or removed index
into every per-index value, sub-set, mapping and equation that names it:
`add_index!(l, "Bog")`, `rename_index!(l, "Bog", "Fen")`,
`set_index_enabled!(l, "Fen", false)`, `remove_index!(l, "Fen")`.
"""
struct IndexListView
    model::Model
    raw::AbstractDict
end

function Base.getproperty(l::IndexListView, s::Symbol)
    (s === :model || s === :raw) && return getfield(l, s)
    raw = getfield(l, :raw)
    s === :name && return get(raw, "name", "")
    s === :indices && return _ed_index_names(raw)
    s === :enabled_indices && return _ed_enabled_names(raw)
    s === :is_materials && return py_truthy(get(raw, "for_contaminants", nothing))
    s === :is_nuclides && return py_truthy(get(raw, "for_nuclides", nothing))
    s === :is_scenarios && return py_truthy(get(raw, "for_scenarios", nothing))
    s === :is_derived && return py_truthy(get(raw, "derived", nothing))
    s === :subset_of && return get(raw, "sub_set_of", nothing)
    s === :mapping && return get(raw, "mapping", nothing)
    s === :comment && return get(raw, "comment", "")
    throw(ErrorException("type IndexListView has no property $s"))
end

function Base.setproperty!(l::IndexListView, s::Symbol, v)
    if s === :comment
        raw = getfield(l, :raw)
        py_truthy(v) ? (raw["comment"] = _py_str(v)) : delete!(raw, "comment")
        return v
    end
    throw(ErrorException("property $s of IndexListView cannot be set this way"))
end

Base.propertynames(::IndexListView, private::Bool=false) =
    (:model, :raw, :name, :indices, :enabled_indices, :is_materials, :is_nuclides, :is_scenarios, :is_derived,
     :subset_of, :mapping, :comment)

function Base.show(io::IO, l::IndexListView)
    shown = l.indices
    more = length(shown) > 6 ? "..." : ""
    print(io, "IndexListView(", _py_str(l.name), ": ", join(_py_str.(shown[1:min(6, end)]), ", "), more, ")")
end

_lname(l::IndexListView) = getfield(l, :raw) |> r -> get(r, "name", "")

"""Adds an index to the list. A radionuclide goes into the catalogue as well."""
add_index!(l::IndexListView, name) = add_index!(getfield(l, :model), _lname(l), name)
"""Adds several indices to the list."""
add_indices!(l::IndexListView, names) = (foreach(n -> add_index!(l, n), names); nothing)
"""Removes an index from the list, and every per-index value keyed by it."""
remove_index!(l::IndexListView, name) = remove_index!(getfield(l, :model), _lname(l), name)
"""Renames an index of the list everywhere it is written."""
rename_index!(l::IndexListView, old, new) = rename_index!(getfield(l, :model), _lname(l), old, new)
"""Takes an index out of the run (`false`) or back in; its values stay."""
set_index_enabled!(l::IndexListView, name, on) = set_index_enabled!(getfield(l, :model), _lname(l), name, on)
"""For a mapping: which of this list's indices `parent_index` belongs to."""
map_index!(l::IndexListView, parent_index, own_index) = map_index!(getfield(l, :model), _lname(l), parent_index, own_index)
"""Renames the list, and every block dimension and per-index value keyed by it."""
rename_index_list!(l::IndexListView, new_name) = rename_index_list!(getfield(l, :model), _lname(l), new_name)
"""Deletes the list; refused while anything is indexed by it."""
delete_index_list!(l::IndexListView) = delete_index_list!(getfield(l, :model), _lname(l))
"""The lists defined from this one, and the blocks indexed by it."""
index_list_users(l::IndexListView) = index_list_users(getfield(l, :model), _lname(l))

# --- a shape drawn on a canvas --------------------------------------------------------------------------------

const _SHAPE_ALLOWED = ("figure", "x", "y", "w", "h", "fill", "line", "line_width", "dash", "text", "text_size",
                        "text_font", "text_align", "text_bold", "text_italic", "flip_x", "flip_y")

"""
    Shape

An annotation drawn on a sub-system's canvas -- a box, an arrow, a figure, a
sticky note -- as a view onto its dictionary. Nothing in the model reads it.
`update!(s; fill="blue", text="...")`, `move_shape!(s, "NearField")`,
`remove_shape!(s)`.
"""
struct Shape
    model::Model
    raw::AbstractDict
end

function Base.getproperty(sh::Shape, s::Symbol)
    (s === :model || s === :raw) && return getfield(sh, s)
    raw = getfield(sh, :raw)
    s === :id && return get(raw, "id", "")
    s === :system && return (v = get(raw, "system", nothing); py_truthy(v) ? v : "")
    String(s) in _SHAPE_ALLOWED && return get(raw, String(s), nothing)
    throw(ErrorException("type Shape has no property $s"))
end

Base.propertynames(::Shape, private::Bool=false) = (:model, :raw, :id, :system, Symbol.(_SHAPE_ALLOWED)...)
Base.show(io::IO, sh::Shape) = print(io, "Shape(", sh.id, " ", _py_str(get(sh.raw, "figure", nothing)), " on '", sh.system, "')")

"""
    update!(shape; patch...) -> shape

Changes a shape's properties, checked as the application checks them:
`fill` and `line` one of the shape colours or `"none"`; `dash`, `text_font`
and `text_align` from their lists.
"""
function update!(sh::Shape; patch...)
    raw = getfield(sh, :raw)
    for (k, value) in patch
        key = String(k)
        key in _SHAPE_ALLOWED || throw(EditError("A shape has no '$key'"))
        if key in ("fill", "line")
            v = String(strip(_js_string(value)))
            (v != "none" && !(v in _ED_SHAPE_COLORS)) &&
                throw(EditError("'$(_py_str(value))' is not a shape colour ($(join(_ED_SHAPE_COLORS, ", ")), none)"))
            raw[key] = v
            continue
        end
        (key == "dash" && !(value in _ED_SHAPE_DASHES)) && throw(EditError("'$(_py_str(value))' is not a line style"))
        (key == "text_font" && !(value in _ED_SHAPE_TEXT_FONTS)) &&
            throw(EditError("'$(_py_str(value))' is not a hand to write in ($(join(_ED_SHAPE_TEXT_FONTS, ", ")))"))
        (key == "text_align" && !(value in _ED_SHAPE_TEXT_ALIGNS)) &&
            throw(EditError("'$(_py_str(value))' is not an alignment ($(join(_ED_SHAPE_TEXT_ALIGNS, ", ")))"))
        if key in ("text_bold", "text_italic", "flip_x", "flip_y")
            py_truthy(value) ? (raw[key] = true) : delete!(raw, key)
            continue
        end
        if key == "text"
            text = _js_string(value)
            isempty(strip(text)) ? delete!(raw, "text") : (raw["text"] = text)
            continue
        end
        raw[key] = value
    end
    return sh
end

"""Moves a shape onto another sub-system's canvas (`""`: the top level)."""
function move_shape!(sh::Shape, system)
    m = getfield(sh, :model)
    (py_truthy(system) && !(system in systems(m))) && throw(EditError("No sub-system named '$(_py_str(system))'"))
    raw = getfield(sh, :raw)
    py_truthy(system) ? (raw["system"] = system) : delete!(raw, "system")
    return nothing
end

"""Removes a shape from its canvas."""
remove_shape!(sh::Shape) = remove_shape!(getfield(sh, :model), sh.id)

# --- what the diagram and the chart show -------------------------------------------------------------------------

"""What the diagram shows when a model says nothing."""
const _ED_DEFAULT_VIEW = JDict(
    "show_expressions" => true, "show_parameters" => false, "show_lookups" => true, "show_reductions" => true,
    "show_functions" => true, "show_warning_list" => true, "show_recorders" => true, "show_influences" => "selected",
    "show_sinks" => true, "show_sources" => true, "show_help" => false, "show_tooltips" => false, "show_grid" => true,
    "snap_to_grid" => true, "connection_label" => "name", "chart_time_scale" => "log", "chart_value_scale" => "log")
const _ED_CONNECTION_LABELS = ("name", "rate", "none")
const _ED_INFLUENCE_MODES = ("none", "all", "selected")
const _ED_CHART_SCALES = ("log", "linear")

"""
    ViewSettings

What the diagram and the chart show (`m.view`): every setting a property,
defaults filled in -- `show_parameters`, `show_influences` (`"none"`, `"all"`
or `"selected"`), `connection_label` (`"name"`, `"rate"` or `"none"`),
`chart_time_scale` and `chart_value_scale` (`"log"` or `"linear"`), ...
"""
struct ViewSettings
    model::Model
end

function Base.getproperty(v::ViewSettings, s::Symbol)
    s === :model && return getfield(v, :model)
    key = String(s)
    haskey(_ED_DEFAULT_VIEW, key) || throw(ErrorException("The view has no setting '$key'"))
    view_ = get(getfield(v, :model).raw, "view", nothing)
    return get(py_truthy(view_) ? view_ : JDict(), key, _ED_DEFAULT_VIEW[key])
end

function Base.setproperty!(v::ViewSettings, s::Symbol, value)
    haskey(_ED_DEFAULT_VIEW, String(s)) || throw(ErrorException("The view has no setting '$s'"))
    update!(v; (s => value,)...)
    return value
end

Base.propertynames(::ViewSettings, private::Bool=false) = Tuple(Symbol.(keys(_ED_DEFAULT_VIEW)))

"""Sets several view settings at once, checked as the application checks them."""
function update!(v::ViewSettings; settings...)
    label = get(settings, :connection_label, nothing)
    (label !== nothing && !(label in _ED_CONNECTION_LABELS)) &&
        throw(EditError("'$(_py_str(label))' is not a label mode ($(join(_ED_CONNECTION_LABELS, ", ")))"))
    inf = get(settings, :show_influences, nothing)
    (inf !== nothing && !(inf isa Bool) && !(inf in _ED_INFLUENCE_MODES)) &&
        throw(EditError("'$(_py_str(inf))' is not a way of showing influences ($(join(_ED_INFLUENCE_MODES, ", ")))"))
    for key in (:chart_time_scale, :chart_value_scale)
        scale = get(settings, key, nothing)
        (scale !== nothing && !(scale in _ED_CHART_SCALES)) &&
            throw(EditError("'$(_py_str(scale))' is not a chart scale ($(join(_ED_CHART_SCALES, ", ")))"))
    end
    m = getfield(v, :model)
    merged = JDict(_ED_DEFAULT_VIEW)
    view_ = get(m.raw, "view", nothing)
    if py_truthy(view_)
        for (k, x) in view_
            merged[k] = x
        end
    end
    for (k, x) in settings
        merged[String(k)] = x
    end
    m.raw["view"] = merged
    return v
end

"""The view settings, defaults filled in."""
function to_dict(v::ViewSettings)
    out = JDict(_ED_DEFAULT_VIEW)
    view_ = get(getfield(v, :model).raw, "view", nothing)
    if py_truthy(view_)
        for (k, x) in view_
            out[k] = x
        end
    end
    return out
end

Base.show(io::IO, v::ViewSettings) = print(io, "ViewSettings(", to_dict(v), ")")

# --- the simulation settings ---------------------------------------------------------------------------------------

const _SIM_TIME_UNITS = ("second", "minute", "hour", "day", "year")
"""The solvers' own settings: kind (a switch, a choice, a number or a whole number), and the allowed range or choices."""
const _SIM_SOLVER_SETTINGS = Dict{String,Tuple{Symbol,Any}}(
    "bdf" => (:switch, nothing), "max_step" => (:number, (0, Inf)), "initial_step" => (:number, (0, Inf)),
    "max_steps" => (:whole, (1, Inf)), "max_order" => (:whole, (1, 5)), "min_order" => (:whole, (1, 5)),
    "norm_control" => (:switch, nothing), "error_norm" => (:choice, ("rms", "max")),
    "stagnation_tol" => (:number, (0, 1)), "newton_kappa" => (:number, (0, 1)), "max_jac_age" => (:whole, (1, Inf)),
    "below_tol_run" => (:whole, (0, Inf)), "matrix" => (:choice, ("auto", "refactor", "sparse", "dense")),
    "jacobian" => (:choice, ("analytic", "numeric")), "auto_abstol" => (:switch, nothing))
"""Which of those each solver reads (`SOLVER_OPTIONS` in src/ode/solvers.js)."""
const _SIM_SOLVER_OPTIONS = let
    ndf = ("bdf", "max_step", "initial_step", "max_steps", "max_order", "norm_control", "error_norm", "stagnation_tol",
           "below_tol_run", "matrix", "jacobian", "auto_abstol")
    Dict{String,Tuple{Vararg{String}}}(
        "ndf" => ndf, "auto" => ndf,
        "ros23" => ("max_step", "initial_step", "max_steps", "jacobian"),
        "dp45" => ("max_step", "initial_step", "max_steps"),
        "auto_julia" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                         "error_norm", "auto_abstol", "newton_kappa", "max_order", "min_order"),
        "rodas5p" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "below_tol_run", "error_norm",
                      "auto_abstol"),
        "radau5" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                     "auto_abstol", "newton_kappa"),
        "fbdf" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                   "error_norm", "auto_abstol", "newton_kappa", "max_order", "min_order"),
        "fbdf_krylov" => ("max_step", "initial_step", "max_steps", "below_tol_run", "error_norm", "auto_abstol",
                          "newton_kappa", "max_order", "min_order"),
        "qndf" => ("bdf", "max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                   "error_norm", "auto_abstol", "newton_kappa", "max_order", "min_order"),
        "kencarp4" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                       "error_norm", "auto_abstol", "newton_kappa"),
        "trbdf2" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "max_jac_age", "below_tol_run",
                     "error_norm", "auto_abstol", "newton_kappa"),
        "rosenbrock23" => ("max_step", "initial_step", "max_steps", "matrix", "jacobian", "below_tol_run",
                           "error_norm", "auto_abstol"),
        "tsit5" => ("max_step", "initial_step", "max_steps", "below_tol_run", "error_norm", "auto_abstol"),
        "vern7" => ("max_step", "initial_step", "max_steps", "below_tol_run", "error_norm", "auto_abstol"),
        "scipy_bdf" => (), "scipy_radau" => (), "scipy_lsoda" => ())
end
"""The settings `SimulationView` checks as they are set."""
const _SIM_PROPERTIES = (:start_time, :end_time, :time_unit, :output_points, :spacing, :solver, :rtol, :abstol,
                         :non_negative, :mass_balance, :split, :decay_ceiling, :switch_times, :iterations, :seed,
                         :sampling, :endpoints)

"""
`_number` of simulation.py: Python's `float(value)` checked against a range,
a whole number where one is wanted.
"""
function _sim_number(key, value; least=-Inf, most=Inf, above=nothing, whole=false)
    v = _ed_pyfloat(value)
    v === nothing && throw(EditError("'$(_py_str(value))' is not a number, and $(_spaced(key)) has to be one"))
    (isnan(v) || (isinf(v) && most != Inf)) && throw(EditError("'$(_py_str(value))' is not a $(_spaced(key))"))
    (above !== nothing && !(v > above)) &&
        throw(EditError("$(_spaced(key)) must be greater than $(_py_g(above)) (got $(_py_str(value)))"))
    if v < least || v > most || (whole && !_is_whole_float(v))
        rng = most == Inf ? "of at least $(_py_g(least))" : "between $(_py_g(least)) and $(_py_g(most))"
        throw(EditError("'$(_py_str(value))' is not a $(_spaced(key)): a $(whole ? "whole number" : "number") $rng"))
    end
    return (_is_whole_float(v) && (whole || !(value isa AbstractFloat))) ? _py_int(v) : v
end

"""Python's `round(x)`: the nearest whole number, halves to even."""
_py_round(x::Integer) = x
_py_round(x::Real) = _py_int(round(Float64(x)))

"""
    SimulationView

The settings a model is run with (`m.simulation`), as a view onto its
`simulation` dictionary: reading a property reads the file's value (or the
application's default), setting one writes it, checked against the rules
Kompartment's loader applies. `sim["max_step"]` reads any setting and
`sim["max_step"] = 10` sets it (checked where the key is known);
`update!(sim; end_time=1e6, rtol=1e-6)` sets several.
"""
struct SimulationView
    raw::AbstractDict
end

"""
    OutputSeries

One series of output times in `simulation.output_times`: `kind` (`"log"`,
`"linear"` or `"times"`), `points` between `start` and `stop` (`nothing` for
the run's own), or an explicit list of `times`.
"""
struct OutputSeries
    raw::AbstractDict
end

Base.getindex(s::SimulationView, key::AbstractString) =
    get(getfield(s, :raw), key, get(SIMULATION_DEFAULTS, key, nothing))
Base.setindex!(s::SimulationView, value, key::AbstractString) = (_sim_set!(s, String(key), value); s)
Base.haskey(s::SimulationView, key::AbstractString) = haskey(getfield(s, :raw), key)
Base.get(s::SimulationView, key::AbstractString, default) = get(getfield(s, :raw), key, default)
Base.keys(s::SimulationView) = collect(keys(getfield(s, :raw)))
Base.iterate(s::SimulationView, st...) = iterate(keys(s), st...)

"""The settings as the file will have them (a copy)."""
to_dict(s::SimulationView) = JDict(getfield(s, :raw))

function Base.getproperty(s::SimulationView, p::Symbol)
    p === :raw && return getfield(s, :raw)
    raw = getfield(s, :raw)
    p in (:start_time, :end_time, :time_unit, :output_points, :spacing, :solver, :rtol, :abstol, :iterations, :seed,
          :sampling) && return s[String(p)]
    p === :non_negative && return (v = get(raw, "non_negative", true); !(v === false || v == "false" || (v isa Real && v == 0)))
    p === :mass_balance && return any(x -> x == get(raw, "mass_balance", nothing), (true, "true", 1))
    p === :split && return get(raw, "split", "auto")
    p === :decay_ceiling && return get(raw, "decay_ceiling", nothing)
    p === :switch_times && return collect(Any, _py_iter(get(raw, "switch_times", nothing)))
    p === :endpoints && return collect(Any, _py_iter(get(raw, "endpoints", nothing)))
    p === :output_series && return OutputSeries[OutputSeries(x) for x in _py_iter(get(raw, "output_times", nothing)) if x isa AbstractDict]
    throw(ErrorException("type SimulationView has no property $p"))
end

Base.propertynames(::SimulationView, private::Bool=false) = (:raw, :output_series, _SIM_PROPERTIES...)

function Base.setproperty!(s::SimulationView, p::Symbol, value)
    p in _SIM_PROPERTIES || throw(ErrorException("SimulationView has no setting $p to set this way: use sim[\"$p\"] = value"))
    _sim_property_set!(s, p, value)
    return value
end

function _sim_property_set!(s::SimulationView, p::Symbol, value)
    raw = getfield(s, :raw)
    if p === :start_time || p === :end_time
        raw[String(p)] = _sim_number(String(p), value)
    elseif p === :time_unit
        value in _SIM_TIME_UNITS || throw(EditError("Unknown time unit '$(_py_str(value))' ($(join(_SIM_TIME_UNITS, ", ")))"))
        raw["time_unit"] = value
    elseif p === :output_points
        n = _sim_number("output_points", value; least=2, most=MAX_OUTPUT_POINTS)
        raw["output_points"] = _py_round(n)
    elseif p === :spacing
        value in SPACINGS || throw(EditError("'$(_py_str(value))' is not a way of choosing output times ($(join(SPACINGS, ", ")))"))
        if value in ("series", "both") && !py_truthy(get(raw, "output_times", nothing))
            # Seeded from the grid that was in force, as the application does.
            op = _ed_pyfloat(get(raw, "output_points", 250))
            op === nothing && throw(ArgumentError("could not convert $(_py_repr(get(raw, "output_points", 250))) to float"))
            raw["output_times"] = Any[JDict("kind" => get(raw, "spacing", nothing) == "linear" ? "linear" : "log",
                                            "points" => max(2, _py_round(op)), "from" => nothing, "to" => nothing)]
        end
        raw["spacing"] = value
    elseif p === :solver
        value in SOLVER_IDS || throw(EditError("Unknown solver '$(_py_str(value))' ($(join(SOLVER_IDS, ", ")))"))
        raw["solver"] = value
    elseif p === :rtol || p === :abstol
        raw[String(p)] = _sim_number(String(p), value; above=0)
    elseif p === :non_negative || p === :mass_balance
        raw[String(p)] = py_truthy(value)
    elseif p === :split
        value in SPLIT_MODES || throw(EditError("'$(_py_str(value))' is not a way of splitting ($(join(SPLIT_MODES, ", ")))"))
        raw["split"] = value
    elseif p === :decay_ceiling
        value === nothing ? delete!(raw, "decay_ceiling") : (raw["decay_ceiling"] = _sim_number("decay_ceiling", value; above=0))
    elseif p === :switch_times
        py_truthy(value) ? (raw["switch_times"] = collect(Any, value)) : delete!(raw, "switch_times")
    elseif p === :iterations
        n = _py_round(_sim_number("iterations", value))
        n < 1 && throw(EditError("A probabilistic run needs at least one realisation"))
        raw["iterations"] = n
    elseif p === :seed
        raw["seed"] = _py_round(_sim_number("seed", value))
    elseif p === :sampling
        value in SAMPLINGS || throw(EditError("'$(_py_str(value))' is not a way of sampling ($(join(SAMPLINGS, ", ")))"))
        raw["sampling"] = value
    elseif p === :endpoints
        out = Any[]
        for n in _py_iter(value)
            t = _py_str(n)
            (!isempty(t) && !(t in out)) && push!(out, t)
        end
        isempty(out) ? delete!(raw, "endpoints") : (raw["endpoints"] = out)
    end
    return
end

"""Sets any setting by its key, checked where the key is known; `nothing` removes it (`Simulation.set`)."""
function _sim_set!(s::SimulationView, key::String, value)
    raw = getfield(s, :raw)
    if value === nothing
        delete!(raw, key)
        return
    end
    p = Symbol(key)
    if p in _SIM_PROPERTIES
        _sim_property_set!(s, p, value)
    elseif haskey(_SIM_SOLVER_SETTINGS, key)
        _sim_solver_setting!(s, key, value)
    else
        raw[key] = value
    end
    return
end

function _sim_solver_setting!(s::SimulationView, key::String, value)
    raw = getfield(s, :raw)
    kind, allowed = _SIM_SOLVER_SETTINGS[key]
    if value === nothing || (value isa AbstractString && value == "")
        delete!(raw, key)
        return
    end
    if kind === :switch
        raw[key] = py_truthy(value)
    elseif kind === :choice
        value in allowed || throw(EditError("'$(_py_str(value))' is not a $(_spaced(key)) ($(join(allowed, ", ")))"))
        raw[key] = value
    else
        least, most = allowed
        raw[key] = _sim_number(key, value; least, most, whole=kind === :whole)
    end
    if key in ("min_order", "max_order")
        lo = get(raw, "min_order", 1)
        hi = get(raw, "max_order", 5)
        lo > hi && throw(EditError("The lowest order ($(_py_str(lo))) is above the highest ($(_py_str(hi)))"))
    end
    return
end

"""Sets several simulation settings at once: `update!(m.simulation; end_time=1e6, rtol=1e-6)`."""
function update!(s::SimulationView; settings...)
    for (k, v) in settings
        _sim_set!(s, String(k), v)
    end
    return s
end

"""The solver-specific settings the chosen solver reads, as the file has them."""
function solver_settings(s::SimulationView)
    raw = getfield(s, :raw)
    return JDict(k => raw[k] for k in get(_SIM_SOLVER_OPTIONS, s.solver, ()) if haskey(raw, k))
end

"""
    add_output_series!(sim, kind="log", points=nothing, start=nothing, stop=nothing, times=nothing) -> OutputSeries

Adds a series of output times: `kind` `"log"` or `"linear"` takes `points`
between `start` and `stop` (`nothing` for the run's own); `"times"` takes
`times`. Does not change `spacing` -- set it to `"series"` to use them.
"""
function add_output_series!(s::SimulationView, kind="log", points=nothing, start=nothing, stop=nothing, times=nothing)
    kind in SERIES_KINDS || throw(EditError("'$(_py_str(kind))' is not a kind of series ($(join(SERIES_KINDS, ", ")))"))
    if kind == "times"
        spec = JDict("kind" => "times", "times" => sort!(Any[_sim_number("time", t) for t in _py_iter(times)]))
    else
        n = _py_round(_sim_number("points", points !== nothing ? points : (kind == "log" ? 100 : 11)))
        n < 2 && throw(EditError("A series needs at least 2 points"))
        spec = JDict("kind" => kind, "points" => n, "from" => start === nothing ? nothing : _sim_number("from", start),
                     "to" => stop === nothing ? nothing : _sim_number("to", stop))
    end
    push!(get!(getfield(s, :raw), "output_times", Any[]), spec)
    return OutputSeries(spec)
end

"""Removes a series by its position (counted from 1); with none left, spacing goes back to `log`."""
function remove_output_series!(s::SimulationView, index::Integer)
    raw = getfield(s, :raw)
    series = get(raw, "output_times", nothing)
    series = py_truthy(series) ? series : Any[]
    1 <= index <= length(series) || throw(EditError("No output series $index"))
    deleteat!(series, index)
    (isempty(series) && get(raw, "spacing", nothing) in ("series", "both")) && (raw["spacing"] = "log")
    return nothing
end

function Base.show(io::IO, s::SimulationView)
    print(io, "SimulationView(", js_text(s.start_time), "..", js_text(s.end_time), " ", s.time_unit, ", ", s.spacing,
          ", solver=", s.solver, ", rtol=", js_text(s.rtol), ", abstol=", js_text(s.abstol), ")")
end

function Base.getproperty(o::OutputSeries, p::Symbol)
    p === :raw && return getfield(o, :raw)
    raw = getfield(o, :raw)
    if p === :kind
        get(raw, "times", nothing) isa AbstractVector && return "times"
        k = get(raw, "kind", nothing)
        py_truthy(k) || (k = get(raw, "spacing", nothing))
        k = py_truthy(k) ? _py_str(k) : "log"
        return k in SERIES_KINDS ? k : "log"
    end
    p === :points && return get(raw, "points", nothing)
    p === :start && return get(raw, "from", nothing)
    p === :stop && return get(raw, "to", nothing)
    p === :times && return collect(Any, _py_iter(get(raw, "times", nothing)))
    throw(ErrorException("type OutputSeries has no property $p"))
end

function Base.setproperty!(o::OutputSeries, p::Symbol, value)
    raw = getfield(o, :raw)
    if p === :points
        n = _py_round(_sim_number("points", value))
        n < 2 && throw(EditError("A series needs at least 2 points"))
        raw["points"] = n
    elseif p === :start
        raw["from"] = (value === nothing || value == "") ? nothing : _sim_number("from", value)
    elseif p === :stop
        raw["to"] = (value === nothing || value == "") ? nothing : _sim_number("to", value)
    elseif p === :times
        raw["times"] = sort!(Any[_sim_number("time", v) for v in value])
    else
        throw(ErrorException("property $p of OutputSeries cannot be set"))
    end
    return value
end

Base.propertynames(::OutputSeries, private::Bool=false) = (:raw, :kind, :points, :start, :stop, :times)

# --- the model's own properties ----------------------------------------------------------------------------------------

@inline function Base.getproperty(m::Model, s::Symbol)
    (s === :raw || s === :path || s === :import_report) && return getfield(m, s)
    return _model_property(m, s)
end

function _model_property(m::Model, s::Symbol)
    s === :name && return model_name(m)
    s === :description && return model_description(m)
    s === :author && return model_author(m)
    s === :created && return read_model_stamp(get(m.raw, "created", nothing))
    s === :saved && return read_model_stamp(get(m.raw, "saved", nothing))
    s === :simulation && return SimulationView(simulation(m))
    s === :view && return ViewSettings(m)
    s === :layout && return layout(m)
    s === :index_lists && return index_lists(m)
    s === :scenarios && return scenarios(m)
    s === :scenario && return scenario(m)
    s === :materials && return materials(m)
    s === :nuclides && return nuclides(m)
    s === :decay_unit && return decay_unit(m)
    s === :decay_chains && return decay_chains(m)
    s === :has_own_chains && return has_own_chains(m)
    s === :systems && return systems(m)
    s === :transports && return transports(m)
    s === :shapes && return shapes(m)
    s === :derived && return derived(m)
    s === :review_tracking && return review_tracking(m)
    s === :compartments && return compartments(m)
    s === :transfers && return transfers(m)
    s === :inflows && return inflows(m)
    s === :parameters && return parameters(m)
    s === :expressions && return expressions(m)
    s === :lookups && return lookups(m)
    s === :index_reductions && return index_reductions(m)
    s === :block_reductions && return block_reductions(m)
    s === :functions && return functions(m)
    s === :min_maxes && return min_maxes(m)
    s === :running_means && return running_means(m)
    s === :snapshots && return snapshots(m)
    s === :delays && return delays(m)
    s === :triggers && return triggers(m)
    s === :farfields && return farfields(m)
    s === :waste_packages && return waste_packages(m)
    s === :events && return events(m)
    return getfield(m, s)
end

function Base.setproperty!(m::Model, s::Symbol, v)
    if s === :raw || s === :path || s === :import_report
        return setfield!(m, s, convert(fieldtype(Model, s), v))
    elseif s === :name
        set_model_name!(m, v)
    elseif s === :description
        set_model_description!(m, v)
    elseif s === :author
        set_model_author!(m, v)
    elseif s === :scenario
        set_scenario!(m, v)
    elseif s === :decay_unit
        set_decay_unit!(m, v)
    elseif s === :review_tracking
        set_review_tracking!(m, v)
    else
        throw(ErrorException("property $s of Model cannot be set this way"))
    end
    return v
end

Base.propertynames(::Model, private::Bool=false) =
    (:raw, :path, :import_report, :name, :description, :author, :created, :saved, :simulation, :view, :layout,
     :index_lists, :scenarios, :scenario, :materials, :nuclides, :decay_unit, :decay_chains, :has_own_chains,
     :systems, :transports, :shapes, :derived, :review_tracking, :compartments, :transfers, :inflows, :parameters,
     :expressions, :lookups, :index_reductions, :block_reductions, :functions, :min_maxes, :running_means,
     :snapshots, :delays, :triggers, :farfields, :waste_packages, :events)
