# The blocks a model is made of, as views onto the model's own dictionary
# (the Python package's blocks.py).
#
# A `Block{K}` reads and writes the block's dictionary in the model: nothing
# is copied, so a view stays right however the model is changed, and `save`
# writes exactly what the views show. Its settings are properties, checked as
# the application checks them -- an interpolation it does not know, a
# failure law it cannot run, an index list the block cannot carry -- and an
# `EditError` is thrown on the spot. Anything a property does not cover is
# still there: `b["some_key"]` reads and writes the raw value, and `b.raw` is
# the dictionary itself.
#
# Two things are not set through properties, because they reach beyond the
# block: its name (`rename_block!`, which rewrites every equation that reads
# it) and its sub-system (`move_block!`).
#
#     soil = m["Soil"]
#     soil.initial = "1e10"
#     set_value!(soil, "5e9"; at="Cs-137")
#     value_at(soil, "Cs-137")                 # "5e9"

"""
    Block{K}

One block of a model, of kind `K` (`:compartment`, `:transfer`, ...): a view
onto its dictionary in the model. The kinds have names of their own --
`Compartment`, `Transfer`, `Inflow`, `Parameter`, `Expression`, `Lookup`,
`IndexReduction`, `BlockReduction`, `FunctionBlock`, `MinMax`, `RunningMean`,
`Snapshot`, `Delay`, `Trigger`, `Farfield`, `WastePackage`, `Event` -- and
their settings are properties: `b.initial`, `b.rate`, `b.unit`,
`b.index_lists`, `b.position`, ...
"""
struct Block{K}
    model::Model
    raw::AbstractDict
end

const Compartment = Block{:compartment}
const Transfer = Block{:transfer}
const Inflow = Block{:inflow}
const Parameter = Block{:parameter}
const Expression = Block{:expression}
const Lookup = Block{:lookup}
const IndexReduction = Block{:index_reduction}
const BlockReduction = Block{:block_reduction}
const FunctionBlock = Block{:function}
const MinMax = Block{:min_max}
const RunningMean = Block{:running_mean}
const Snapshot = Block{:snapshot}
const Delay = Block{:delay}
const Trigger = Block{:trigger}
const Farfield = Block{:farfield}
const WastePackage = Block{:waste_package}
const Event = Block{:event}

"""Every kind, in the Python package's order (`KINDS` in blocks.py)."""
const _BK_KINDS = ("compartment", "transfer", "inflow", "parameter", "expression", "lookup", "index_reduction",
                   "block_reduction", "function", "min_max", "running_mean", "snapshot", "delay", "trigger",
                   "farfield", "waste_package", "event")
const _BK_COLLECTION = Dict(
    "compartment" => "compartments", "transfer" => "transfers", "inflow" => "inflows", "parameter" => "parameters",
    "expression" => "expressions", "lookup" => "lookups", "index_reduction" => "index_reductions",
    "block_reduction" => "block_reductions", "function" => "functions", "min_max" => "min_maxes",
    "running_mean" => "running_means", "snapshot" => "snapshots", "delay" => "delays", "trigger" => "triggers",
    "farfield" => "farfields", "waste_package" => "waste_packages", "event" => "events")
const _BK_SINGULAR = Dict(v => k for (k, v) in _BK_COLLECTION)
const _BK_VALUE_KEY = Dict(
    "compartment" => "initial", "transfer" => "rate", "inflow" => "rate", "parameter" => "value",
    "expression" => "equation", "lookup" => "points", "index_reduction" => "target", "block_reduction" => "targets",
    "function" => "equation", "min_max" => "target", "running_mean" => "target", "snapshot" => "target",
    "delay" => "target", "trigger" => "first", "farfield" => "kd_f", "waste_package" => "inventory", "event" => "at")
const _BK_RECORDER_ENTRIES = ("target", "reset_trigger", "start_trigger", "stop_trigger")
const _BK_ENTRY_KEYS = Dict{String,Tuple{Vararg{String}}}(
    "compartment" => ("initial", "abstol", "non_negative", "dydt"), "transfer" => ("rate",), "inflow" => ("rate",),
    "parameter" => ("value", "pdf"), "expression" => ("equation",), "lookup" => ("points",),
    "index_reduction" => ("target",), "block_reduction" => ("targets",), "function" => (),
    "min_max" => _BK_RECORDER_ENTRIES, "running_mean" => _BK_RECORDER_ENTRIES,
    "snapshot" => ("target", "trigger", "initial"), "delay" => ("target", "delay"),
    "trigger" => ("first", "second", "direction"), "farfield" => FARF_EQUATION_KEYS,
    "waste_package" => WASTE_EQUATION_KEYS, "event" => ())
const _BK_EQUATION_KEYS = Dict{String,Tuple{Vararg{String}}}(
    "compartment" => ("initial", "dydt"), "transfer" => ("rate",), "inflow" => ("rate",), "parameter" => (),
    "expression" => ("equation",), "lookup" => (), "index_reduction" => (), "block_reduction" => (),
    "function" => ("equation",), "min_max" => ("target",), "running_mean" => ("target",),
    "snapshot" => ("target", "initial"), "delay" => ("target", "delay"), "trigger" => ("first", "second"),
    "farfield" => FARF_EQUATION_KEYS, "waste_package" => WASTE_EQUATION_KEYS, "event" => DIS_EQUATION_KEYS)

"""The shapes a block can be drawn as, and each kind's own."""
const _BK_SHAPES = ("rounded", "rect", "ellipse", "hexagon", "cylinder", "diamond")
const _BK_DEFAULT_SHAPE = Dict(
    "compartment" => "rounded", "expression" => "rounded", "parameter" => "hexagon", "lookup" => "rect",
    "index_reduction" => "rounded", "block_reduction" => "rounded", "function" => "rounded", "min_max" => "rect",
    "running_mean" => "rect", "snapshot" => "rect", "delay" => "cylinder", "trigger" => "diamond",
    "farfield" => "rect", "waste_package" => "rect", "event" => "diamond", "inflow" => "rounded",
    "transfer" => "rounded")
"""Default box size per kind, in diagram units."""
const _BK_DEFAULT_SIZE = Dict(
    "compartment" => (136, 54), "farfield" => (152, 58), "waste_package" => (152, 58), "event" => (140, 56),
    "expression" => (136, 54), "parameter" => (120, 44), "lookup" => (132, 54), "index_reduction" => (136, 54),
    "block_reduction" => (136, 54), "function" => (148, 54), "min_max" => (136, 54), "running_mean" => (136, 54),
    "snapshot" => (136, 54), "delay" => (128, 54), "trigger" => (130, 54), "inflow" => (120, 44),
    "transfer" => (120, 44), "system" => (168, 62))
const _BK_LINE_DASHES = ("solid", "dashed", "dotted")
const _BK_TRANSPORT_OPERATIONS = ("sum", "mean")
const _BK_TRANSPORT_ARGUMENTS = ("all", "point", "range")
const _BK_AVAILABILITY_SCHEMES = ("limit", "shared_limit", "langmuir", "shared_langmuir")
const _BK_AVAILABILITY_BASES = ("amount", "moles")

_kind_name(::Block{K}) where {K} = String(K)

"""The block view for a raw block of a collection."""
_view_of(m::Model, collection::AbstractString, raw::AbstractDict) = Block{Symbol(_BK_SINGULAR[collection])}(m, raw)

Base.:(==)(a::Block, b::Block) = getfield(a, :raw) === getfield(b, :raw)
Base.hash(b::Block, h::UInt) = hash(objectid(getfield(b, :raw)), h)

const _BK_SHOWN = Dict(:function => "FunctionBlock")
function Base.show(io::IO, b::Block{K}) where {K}
    name = get(_BK_SHOWN, K, join(uppercasefirst.(split(String(K), '_'))))
    print(io, name, "(", repr(_bk_qualified_name(b)), ")")
end

_name_arg(b::Block) = _bk_qualified_name(b)

# --- fields: the settings stored under a key ---------------------------------------------------------

"""
A documented setting of a block, stored under `key`: read and written as its
`kind` says -- `:equation` (text; a number is written as its equation),
`:text`, `:bool`, `:int`, `:count` (a whole number, or `""` to have it worked
out), `:number` or `:choice` (one of `choices`). `least` refuses an equation
written as a number below it. `name` is the property's own name, for
messages.
"""
struct _Field
    key::String
    kind::Symbol
    default::Any
    choices::Union{Nothing,Tuple}
    least::Union{Nothing,Float64}
    name::String
end
_F(key, kind=:equation, default=nothing; choices=nothing, least=nothing, name=key) =
    _Field(key, kind, default, choices === nothing ? nothing : Tuple(choices), least === nothing ? nothing : Float64(least), name)

const _BK_FIELDS = let
    shared = [_F("unit", :text, ""), _F("comment", :text, ""), _F("symbol", :text, nothing)]
    connection = [_F("rate", :equation, "0")]
    recorder = [_F("target", :equation, "0")]
    triggers = [_F("reset_trigger", :text, nothing), _F("start_trigger", :text, nothing), _F("stop_trigger", :text, nothing)]
    own = Dict{String,Vector{_Field}}(
        "compartment" => [_F("initial", :equation, "0"), _F("dydt", :equation, nothing), _F("abstol", :number, nothing),
                          _F("non_negative", :bool, true), _F("handle_decay", :bool, true)],
        "transfer" => [connection; _F("multiply_by_donor", :bool, true)],
        "inflow" => connection,
        "parameter" => _Field[],
        "expression" => [_F("equation", :equation, "0"),
                         _F("operation", :choice, nothing; choices=_BK_TRANSPORT_OPERATIONS),
                         _F("argument", :choice, nothing; choices=_BK_TRANSPORT_ARGUMENTS)],
        "lookup" => [_F("interpolation", :choice, "linear"; choices=INTERPOLATIONS), _F("cyclic", :bool, false)],
        "index_reduction" => [_F("operation", :choice, "sum"; choices=OPERATIONS), _F("percentile", :number, nothing)],
        "block_reduction" => [_F("operation", :choice, "sum"; choices=AGGREGATE_OPERATIONS)],
        "function" => [_F("equation", :equation, "")],
        "min_max" => [recorder; _F("operation", :choice, "max"; choices=EXTREMES); triggers],
        "running_mean" => [recorder; triggers],
        "snapshot" => [recorder; _F("trigger", :text, nothing); _F("initial", :equation, "0")],
        "delay" => [recorder; _F("delay", :equation, "0")],
        "trigger" => [_F("first", :equation, "0"), _F("second", :equation, "0"),
                      _F("direction", :choice, "rising"; choices=DIRECTIONS)],
        "farfield" => [_F("method", :choice, "discretized"; choices=FARF_METHODS), _F("tw", :equation, "100"),
                       _F("surface", :choice, "f"; choices=SURFACES), _F("f", :equation, "1e5"),
                       _F("aw", :equation, "1000"), _F("aperture", :equation, "0.002"),
                       _F("kd_f", :equation, "0"; least=0), _F("kd_m", :equation, "0"; least=0),
                       _F("de_m", :equation, "1e-4"; least=0), _F("eps_m", :equation, "0.0018"; least=0),
                       _F("rho_m", :equation, "2700"; least=0), _F("pe", :equation, "10"),
                       _F("pen_dep", :equation, "12.5"), _F("pen_dep_0", :equation, ""), _F("n_f", :int, 20),
                       _F("n_m", :int, 20), _F("o_b", :choice, 1; choices=OUTFLOWS), _F("n_b", :count, 0),
                       _F("grid", :choice, "reference"; choices=GRIDS), _F("handle_decay", :bool, true),
                       _F("report_cells", :bool, false)],
        "waste_package" => [_F("failure", :choice, "never"; choices=FAILURES), _F("packages", :int, 1),
                            _F("inventory", :equation, "0"), _F("irf", :equation, "0"),
                            _F("degradation_rate", :equation, "0"), _F("fail_at", :equation, ""),
                            _F("fail_from", :equation, ""), _F("fail_to", :equation, ""),
                            _F("fail_start", :equation, "0"), _F("fail_rate", :equation, ""),
                            _F("fail_scale", :equation, ""), _F("fail_shape", :equation, "1"),
                            _F("handle_decay", :bool, true)],
        "event" => [_F("timing", :choice, "at"; choices=TIMINGS), _F("at", :equation, ""), _F("rate", :equation, ""),
                    _F("from", :equation, ""; name="start"), _F("until", :equation, ""), _F("sampled", :bool, true)],
    )
    tables = Dict{Symbol,Dict{Symbol,_Field}}()
    for kind in _BK_KINDS
        t = Dict{Symbol,_Field}()
        for f in [shared; own[kind]]
            t[Symbol(f.name)] = f
        end
        tables[Symbol(kind)] = t
    end
    tables
end

_field_of(K::Symbol, s::Symbol) = get(_BK_FIELDS[K], s, nothing)

"""The properties each kind has besides its fields: those that can be set, and those that cannot."""
const _BK_SHARED_RW = (:enabled, :index_lists, :value, :color, :shape, :position, :size)
const _BK_SHARED_RO = (:model, :raw, :name, :system, :qualified_name, :effectively_enabled, :entries, :review)
const _BK_OWN_RW = Dict{Symbol,Tuple{Vararg{Symbol}}}(
    :transfer => (:sum_extra_indices, :line_color, :line_width, :dash, :source, :target),
    :inflow => (:sum_extra_indices, :line_color, :line_width, :dash, :target),
    :parameter => (:value, :distribution), :lookup => (:argument, :points), :index_reduction => (:target,),
    :block_reduction => (:targets,), :function => (:parameters, :index_lists), :event => (:index_lists,))
const _BK_OWN_RO = Dict{Symbol,Tuple{Vararg{Symbol}}}(
    :compartment => (:transport_role,), :transfer => (:is_release, :availability), :expression => (:transport_role,),
    :index_reduction => (:over,), :farfield => (:release,), :waste_package => (:release,), :event => (:actions,))

"""What a name is on a kind's class in Python: a field, a property that can (`:rw`) or cannot (`:ro`) be set, or nothing of the kind (`:other`)."""
function _class_attr(K::Symbol, attr)
    s = Symbol(_py_str(attr))
    s in get(_BK_OWN_RW, K, ()) && return :rw
    s in get(_BK_OWN_RO, K, ()) && return :ro
    f = _field_of(K, s)
    f !== nothing && return f
    s in _BK_SHARED_RW && return :rw
    s in _BK_SHARED_RO && return :ro
    return :other
end

function _field_get(raw::AbstractDict, f::_Field)
    v = get(raw, f.key, nothing)
    f.kind === :bool && return js_truthy_switch(v, py_truthy(f.default))
    return (v === nothing && !haskey(raw, f.key)) ? f.default : v
end

_bk_local_name(b::Block) = _py_str(get(getfield(b, :raw), "name", ""))

"""`value` as a field stores it, or an `EditError`."""
function _field_coerce(f::_Field, value, b::Union{Nothing,Block}=nothing)
    where_ = b === nothing ? "" : "$(_bk_local_name(b)): "
    if f.kind === :equation
        text = equation_text(value)
        if f.least !== nothing
            n = _written_number(text)
            if n !== nothing && n < f.least
                floor_ = f.least == 0 ? "zero or positive" : "at least $(js_number(f.least))"
                throw(EditError("$(where_)$(f.name) must be $floor_ (got $text)"))
            end
        end
        return text
    elseif f.kind === :text
        return _py_str(value)
    elseif f.kind === :bool
        return py_truthy(value)
    end
    if f.kind === :count && value isa AbstractString && isempty(strip(value))
        return ""
    end
    if f.kind in (:int, :number, :count)
        v = _ed_pyfloat(value)
        v === nothing && throw(EditError("$(where_)'$(_py_str(value))' is not a number, and $(f.name) has to be one"))
        if f.kind in (:int, :count)
            _is_whole_float(v) || throw(EditError("$(where_)$(f.name) has to be a whole number (got $(_py_str(value)))"))
            return _py_int(v)
        end
        return (_is_whole_float(v) && value isa Integer) ? _py_int(v) : v
    end
    if f.kind === :choice
        any(c -> c == value, something(f.choices, ())) ||
            throw(EditError("$(where_)'$(_py_str(value))' is not a $(_spaced(f.name)) " *
                            "($(join((_py_str(c) for c in something(f.choices, ())), ", ")))"))
        return value
    end
    return value
end

# --- reading a block's properties ---------------------------------------------------------------------

_bk_system(raw::AbstractDict) = (s = get(raw, "system", nothing); py_truthy(s) ? s : "")
_bk_qualified_name(b::Block) = qualified_name(getfield(b, :raw))

"""Python's `transfer.is_release`: it carries a far-field path's or waste packages' release."""
function _transfer_is_release(b::Block)
    src = get(getfield(b, :raw), "from", nothing)
    py_truthy(src) || return false
    found = get_block(getfield(b, :model), src)
    return found !== nothing && _kind_name(found) in ("farfield", "waste_package")
end

"""The transfer carrying a block's release, if it goes anywhere."""
function _release_of(b::Block)
    q = _bk_qualified_name(b)
    for t in transfers(getfield(b, :model))
        get(t.raw, "from", nothing) == q && return t
    end
    return nothing
end

@inline function Base.getproperty(b::Block, s::Symbol)
    (s === :model || s === :raw) && return getfield(b, s)
    return _block_get(b, s)
end

function _block_get(b::Block{K}, s::Symbol) where {K}
    raw = getfield(b, :raw)
    m = getfield(b, :model)
    # What a kind has of its own, which overrides what every block shares.
    if K === :compartment
        s === :transport_role && return get(raw, "transport", nothing)
    elseif K === :transfer || K === :inflow
        s === :sum_extra_indices && return js_truthy_switch(get(raw, "sum_extra_indices", nothing), false)
        s === :line_color && return get(raw, "color", nothing)
        s === :line_width && return get(raw, "line_width", nothing)
        s === :dash && return (d = get(raw, "dash", nothing); py_truthy(d) ? d : "solid")
        if K === :transfer
            s === :source && return get(raw, "from", nothing)
            s === :target && return get(raw, "to", nothing)
            s === :is_release && return _transfer_is_release(b)
            s === :availability && return get(raw, "availability", nothing)
        else
            s === :source && return nothing
            s === :target && return get(raw, "to", nothing)
        end
    elseif K === :parameter
        s === :value && return get(raw, "value", 0)
        s === :distribution && return get(raw, "pdf", nothing)
    elseif K === :expression
        s === :transport_role && return get(raw, "transport", nothing)
    elseif K === :lookup
        s === :argument && return get(raw, "argument", nothing)
        s === :points && return get!(raw, "points", Any[])
    elseif K === :index_reduction
        s === :target && return get(raw, "target", nothing)
        s === :over && return _reduced_list(m, b)
    elseif K === :block_reduction
        s === :targets && return collect(Any, _py_iter(get(raw, "targets", nothing)))
    elseif K === :function
        s === :parameters && return collect(Any, _py_iter(get(raw, "parameters", nothing)))
        s === :index_lists && return Any[]
    elseif K === :farfield || K === :waste_package
        s === :release && return _release_of(b)
    elseif K === :event
        s === :index_lists && return Any[]
        s === :actions && return get!(raw, "actions", Any[])
    end
    f = _field_of(K, s)
    f !== nothing && return _field_get(raw, f)
    s === :kind && return String(K)
    s === :collection && return _BK_COLLECTION[String(K)]
    s === :value_key && return _BK_VALUE_KEY[String(K)]
    s === :entry_keys && return _BK_ENTRY_KEYS[String(K)]
    s === :equation_keys && return _BK_EQUATION_KEYS[String(K)]
    s === :name && return get(raw, "name", "")
    s === :system && return _bk_system(raw)
    s === :qualified_name && return qualified_name(raw)
    s === :enabled && return get(raw, "enabled", nothing) !== false
    s === :effectively_enabled && return get(raw, "enabled", nothing) !== false && system_enabled(m, _bk_system(raw))
    s === :index_lists && return _effective_dims(_N(m), raw)
    s === :entries && return get!(raw, "entries", Any[])
    s === :value && return get(raw, _BK_VALUE_KEY[String(K)], nothing)
    s === :color && return get(raw, "color", nothing)
    s === :shape && return (v = get(raw, "shape", nothing); py_truthy(v) ? v : get(_BK_DEFAULT_SHAPE, String(K), "rounded"))
    s === :position && return _block_position(m, qualified_name(raw))
    s === :size && return _block_size(m, String(K), qualified_name(raw))
    s === :review && return get(raw, "qa", nothing)
    throw(ErrorException("type $(typeof(b)) has no property $s"))
end

function _block_position(m::Model, q)
    entry = get(layout(m), q, nothing)
    (entry isa AbstractDict && get(entry, "x", nothing) !== nothing && get(entry, "y", nothing) !== nothing) ||
        return nothing
    return (entry["x"], entry["y"])
end

function _block_size(m::Model, kind::String, q)
    entry = get(layout(m), q, nothing)
    py_truthy(entry) || (entry = JDict())
    w, h = get(_BK_DEFAULT_SIZE, kind, _BK_DEFAULT_SIZE["compartment"])
    return (get(entry, "w", w), get(entry, "h", h))
end

function Base.propertynames(b::Block{K}, private::Bool=false) where {K}
    own = Symbol[]
    append!(own, get(_BK_OWN_RW, K, ()))
    append!(own, get(_BK_OWN_RO, K, ()))
    append!(own, keys(_BK_FIELDS[K]))
    return Tuple(unique([:kind, :name, :system, :qualified_name, own..., _BK_SHARED_RW..., _BK_SHARED_RO...]))
end

# --- writing a block's properties ---------------------------------------------------------------------

function Base.setproperty!(b::Block{K}, s::Symbol, v) where {K}
    raw = getfield(b, :raw)
    m = getfield(b, :model)
    if K === :transfer || K === :inflow
        if s === :sum_extra_indices
            py_truthy(v) ? (raw["sum_extra_indices"] = true) : delete!(raw, "sum_extra_indices")
            return v
        elseif s === :line_color
            _set_color!(raw, v)
            return v
        elseif s === :line_width
            if v === nothing || (v isa AbstractString && v == "")
                delete!(raw, "line_width")
                return v
            end
            w = _ed_pyfloat(v)
            (w === nothing || !(w > 0)) && throw(EditError("'$(_py_str(v))' is not a line width"))
            raw["line_width"] = min(12.0, max(0.25, w))
            return v
        elseif s === :dash
            if v === nothing || v == "" || v == "solid"
                delete!(raw, "dash")
                return v
            end
            v in _BK_LINE_DASHES || throw(EditError("'$(_py_str(v))' is not a line style ($(join(_BK_LINE_DASHES, ", ")))"))
            raw["dash"] = v
            return v
        elseif s === :target
            set_connection_end!(m, _bk_qualified_name(b), "to", v)
            return v
        elseif K === :transfer && s === :source
            set_connection_end!(m, _bk_qualified_name(b), "from", v)
            return v
        end
    elseif K === :parameter
        if s === :value
            raw["value"] = _coerce_value(b, "value", v)
            return v
        elseif s === :distribution
            v === nothing ? delete!(raw, "pdf") : (raw["pdf"] = _coerce_value(b, "pdf", v))
            return v
        end
    elseif K === :lookup
        if s === :argument
            if v === nothing || v == ""
                delete!(raw, "argument")
                return v
            end
            occursin(NAME_RE, _py_str(v)) || throw(EditError("'$(_py_str(v))' is not a valid argument name"))
            raw["argument"] = _py_str(v)
            return v
        elseif s === :points
            raw["points"] = _points(v, _bk_local_name(b))
            return v
        end
    elseif K === :index_reduction
        s === :target && (set_reduction_target!(m, _bk_qualified_name(b), v); return v)
    elseif K === :block_reduction
        s === :targets && (set_aggregate_targets!(m, _bk_qualified_name(b), v); return v)
    elseif K === :function
        s === :parameters && (set_function_parameters!(m, _bk_qualified_name(b), v); return v)
        if s === :index_lists
            py_truthy(v) && throw(EditError("A function is not indexed: it is worked out at the index it is called at"))
            return v
        end
    elseif K === :event
        if s === :index_lists
            py_truthy(v) && throw(EditError("An event is not indexed: it acts on whole blocks"))
            return v
        end
    end
    f = _field_of(K, s)
    if f !== nothing
        v === nothing ? delete!(raw, f.key) : (raw[f.key] = _field_coerce(f, v, b))
        return v
    end
    if s === :enabled
        py_truthy(v) ? delete!(raw, "enabled") : (raw["enabled"] = false)
    elseif s === :index_lists
        set_dimensions!(m, b, v)
    elseif s === :value
        set_value!(b, v)
    elseif s === :color
        _set_color!(raw, v)
    elseif s === :shape
        if v === nothing || v == ""
            delete!(raw, "shape")
            return v
        end
        v in _BK_SHAPES || throw(EditError("'$(_py_str(v))' is not a shape ($(join(_BK_SHAPES, ", ")))"))
        v == get(_BK_DEFAULT_SHAPE, String(K), nothing) ? delete!(raw, "shape") : (raw["shape"] = v)
    elseif s === :position
        _set_position!(m, _bk_qualified_name(b), v)
    elseif s === :size
        _set_size!(m, _bk_qualified_name(b), v)
    elseif s === :model || s === :raw || s in _BK_SHARED_RO || s in get(_BK_OWN_RO, K, ()) || s in (:kind, :collection)
        throw(ErrorException("property '$s' of $(typeof(b)) has no setter" *
                             (s === :name ? ": use rename_block!" : s === :system ? ": use move_block!" : "")))
    else
        throw(ErrorException("type $(typeof(b)) has no property $s"))
    end
    return v
end

function _set_color!(raw::AbstractDict, v)
    if v === nothing || (v isa AbstractString && v == "")
        delete!(raw, "color")
    else
        raw["color"] = _py_str(v)
    end
    return
end

# --- the raw dictionary -------------------------------------------------------------------------------

Base.getindex(b::Block, key::AbstractString) = getfield(b, :raw)[key]
Base.haskey(b::Block, key::AbstractString) = haskey(getfield(b, :raw), key)
Base.get(b::Block, key::AbstractString, default) = get(getfield(b, :raw), key, default)
Base.keys(b::Block) = collect(keys(getfield(b, :raw)))

"""
    b[key] = value

A raw value set: through the property of that name where the kind has one
that can be set (so it is checked), straight into the dictionary otherwise.
`name` and `system` are refused: `rename_block!` and `move_block!` follow the
change through every reference.
"""
function Base.setindex!(b::Block{K}, value, key::AbstractString) where {K}
    if key == "name" || key == "system"
        throw(EditError("'$key' is not changed this way: use $(key == "name" ? "rename()" : "move_to()"), which " *
                        "follows the change through every reference."))
    end
    attr = _class_attr(K, key)
    if attr isa _Field || attr === :rw
        setproperty!(b, Symbol(key), value)
    else
        getfield(b, :raw)[key] = value
    end
    return b
end

"""A copy of the block's dictionary."""
to_dict(b::Block) = jcopy(getfield(b, :raw))

# --- dimensions and per-index values --------------------------------------------------------------------

function _check_key(b::Block{K}, key) where {K}
    keys_ = _BK_ENTRY_KEYS[String(K)]
    key in keys_ && return
    throw(EditError("A $(_spaced(K)) holds no per-index '$(_py_str(key))' (it may hold " *
                    "$(isempty(keys_) ? "none" : join(keys_, ", ")))"))
end

function _coerce_value(b::Block{K}, key, value) where {K}
    if K === :parameter
        if key == "value"
            value isa Bool && throw(EditError("$(_bk_local_name(b)): $(_py_repr(value)) is not a number"))
            value isa Real && return value
            v = _ed_pyfloat(value)
            v === nothing && throw(EditError("$(_bk_local_name(b)): '$(_py_str(value))' is not a number, and a " *
                                             "parameter's value is one"))
            text = _py_str(value)
            return (_is_whole_float(v) && !occursin('e', lowercase(text)) && !occursin('.', text)) ? _py_int(v) : v
        elseif key == "pdf"
            value === nothing && return nothing
            (value isa AbstractDict && haskey(value, "kind")) ||
                throw(EditError("$(_bk_local_name(b)): a distribution is a dict made by kompartment.distributions"))
            problems = pdf_problems(value)
            isempty(problems) || throw(EditError("$(_bk_local_name(b)): $(join(problems, " "))"))
            return value
        end
    elseif K === :lookup
        key == "points" && return _points(value, _bk_local_name(b))
    end
    attr = _class_attr(K, key)
    attr isa _Field && return _field_coerce(attr, value, b)
    key in _BK_EQUATION_KEYS[String(K)] && return equation_text(value)
    return value
end

"""The points of a lookup table as it stores them, `[[x, y], ...]`, a point's distribution third."""
function _points(pts, name)
    out = Any[]
    for (i, p) in enumerate(_py_iter(pts))
        if p isa AbstractDict
            q = Any[get(p, "x", nothing), get(p, "y", nothing)]
            py_truthy(get(p, "pdf", nothing)) && push!(q, p["pdf"])
            p = q
        end
        seq = p isa AbstractString ? Any[string(c) for c in p] :
              (p isa AbstractVector || p isa Tuple) ? collect(Any, p) : nothing
        x = seq !== nothing && length(seq) >= 1 ? _ed_pyfloat(seq[1]) : nothing
        y = seq !== nothing && length(seq) >= 2 ? _ed_pyfloat(seq[2]) : nothing
        (x === nothing || y === nothing) &&
            throw(EditError("$name: lookup point $i is $(_py_repr(p)); both parts must be numbers"))
        xv = (_is_whole_float(x) && seq[1] isa Integer) ? _py_int(x) : x
        yv = (_is_whole_float(y) && seq[2] isa Integer) ? _py_int(y) : y
        point = Any[xv, yv]
        (length(seq) > 2 && py_truthy(seq[3])) && push!(point, seq[3])
        push!(out, point)
    end
    return out
end

"""
    entry_index(b, at) -> JDict

`at` as `list => index`, checked against the block's dimensions: a
dictionary (or named tuple) by list, a tuple or vector with one index per
dimension in order, or -- for a block with one dimension, or an index only
one of its lists has -- the index alone.
"""
entry_index(b::Block, at) = _ed_index_of(getfield(b, :model), b, at)

function _ed_index_of(m::Model, b::Block, at)
    dims = collect(Any, b.index_lists)
    at === nothing && return JDict()
    if at isa AbstractString || at isa Symbol
        at = _py_str(at isa Symbol ? String(at) : at)
        if length(dims) == 1
            index = JDict(dims[1] => at)
        else
            matches = Any[]
            for d in dims
                lst = _ed_list_any(m, d)
                lst === nothing && throw(EditError("No index list named '$(_py_str(d))'"))
                at in _ed_index_names(lst) && push!(matches, d)
            end
            length(matches) == 1 ||
                throw(EditError("'$at' is ambiguous for $(_bk_local_name(b)), which is indexed by " *
                                "$(isempty(dims) ? "nothing" : join((_py_str(d) for d in dims), ", ")): give the index " *
                                "as {list: index}"))
            index = JDict(matches[1] => at)
        end
    elseif at isa AbstractDict || at isa NamedTuple || at isa Base.Pairs
        index = JDict(_py_str(k isa Symbol ? String(k) : k) => _py_str(v) for (k, v) in _in_order(pairs(at), dims))
    else
        seq = collect(Any, at)
        length(seq) == length(dims) ||
            throw(EditError("$(_bk_local_name(b)) has $(length(dims)) dimension(s) and the index gives $(length(seq))"))
        index = JDict()
        for (d, i) in zip(dims, seq)
            i === nothing || (index[d] = _py_str(i))
        end
    end
    for (lst_name, idx) in index
        lst_name in dims || throw(EditError("'$(_bk_qualified_name(b))' is not indexed by '$lst_name'"))
        lst = _ed_list_any(m, lst_name)
        (lst === nothing || !(idx in _ed_index_names(lst))) &&
            throw(EditError("'$idx' is not an index of '$lst_name'"))
    end
    return index
end

function _ed_set_entry!(m::Model, b::Block{K}, index::AbstractDict, values::AbstractDict) where {K}
    raw = getfield(b, :raw)
    if K === :farfield || K === :waste_package
        nuclide_keys = K === :farfield ? FARF_NUCLIDE_KEYS : WASTE_NUCLIDE_KEYS
        material = material_dimension(m)
        if material !== nothing && haskey(index, material)
            wrong = [k for k in keys(values) if !(k in nuclide_keys)]
            isempty(wrong) || throw(EditError("$(_bk_local_name(b)): $(join(wrong, ", ")) hold one value whatever the " *
                                              "nuclide; only $(join(nuclide_keys, ", ")) are per nuclide"))
        end
    end
    get(raw, "entries", nothing) isa AbstractVector || (raw["entries"] = Any[])
    entries = raw["entries"]
    entry = nothing
    for e in entries
        if _py_or_dict(jget(e, "index")) == index
            entry = e
            break
        end
    end
    if entry === nothing
        entry = JDict("index" => JDict(index))
        push!(entries, entry)
    end
    for (k, v) in values
        entry[k] = v
    end
    return entry
end

"""
The pairs of a dictionary in the order they were written -- or, for one that
keeps no order (a `Dict`), in the order of `keys_` first, so that what is
written to the file does not depend on a hash.
"""
function _in_order(d, keys_)
    (d isa Dict || d isa Base.Pairs{<:Any,<:Any,<:Any,<:Dict}) || return d
    first_ = Any[k => d[k] for k in keys_ if haskey(d, k)]
    rest = sort!(Any[k => v for (k, v) in d if !(k in keys_)]; by=p -> string(first(p)))
    return [first_; rest]
end

"""`d or {}`."""
_py_or_dict(d) = py_truthy(d) ? d : JDict()

"""
    set_value!(b, value, at=nothing, key=nothing)
    set_value!(b, value; at, key)

Sets the block's value, or its value at one index combination (`at`, see
`entry_index`). `key` picks another per-index property than the value itself
-- a compartment's `abstol` or `dydt`, a parameter's `pdf` -- where the kind
has one (`b.entry_keys`).
"""
function set_value!(b::Block{K}, value, at_=nothing, key_=nothing; at=at_, key=key_) where {K}
    key = py_truthy(key) ? _py_str(key) : _BK_VALUE_KEY[String(K)]
    if at === nothing
        attr = _class_attr(K, key)
        if attr isa _Field || attr === :rw || attr === :ro
            setproperty!(b, Symbol(key), value)
        else
            getfield(b, :raw)[key] = _coerce_value(b, key, value)
        end
        return nothing
    end
    _check_key(b, key)
    m = getfield(b, :model)
    _ed_set_entry!(m, b, _ed_index_of(m, b, at), JDict(key => _coerce_value(b, key, value)))
    return nothing
end

"""
    set_entry!(b, at; values...) -> entry

Sets several per-index properties at one index combination at once:
`set_entry!(soil, "Cs-137"; initial="5e9", abstol=1e-3)`.
"""
function set_entry!(b::Block, at; values...)
    m = getfield(b, :model)
    index = _ed_index_of(m, b, at)
    coerced = JDict()
    for (k, v) in values
        key = String(k)
        _check_key(b, key)
        coerced[key] = _coerce_value(b, key, v)
    end
    return _ed_set_entry!(m, b, index, coerced)
end

"""
    value_at(b, at=nothing, key=nothing)
    value_at(b; at, key)

The value that applies at an index combination: the most specific entry that
matches, else the block's own.
"""
function value_at(b::Block{K}, at_=nothing, key_=nothing; at=at_, key=key_) where {K}
    key = py_truthy(key) ? _py_str(key) : _BK_VALUE_KEY[String(K)]
    raw = getfield(b, :raw)
    at === nothing && return get(raw, key, nothing)
    index = _ed_index_of(getfield(b, :model), b, at)
    best, score = nothing, -1
    for e in _py_iter(get(raw, "entries", nothing))
        haskey(e, key) || continue
        ix = _py_or_dict(get(e, "index", nothing))
        if all(((k, v),) -> get(index, k, nothing) == v, ix) && length(ix) > score
            best, score = e[key], length(ix)
        end
    end
    return score >= 0 ? best : get(raw, key, nothing)
end

"""
    clear_value!(b, at, key=nothing)

Removes the value set at one index combination, so the block's own applies
again. An entry left carrying nothing is removed.
"""
function clear_value!(b::Block{K}, at, key_=nothing; key=key_) where {K}
    key = py_truthy(key) ? _py_str(key) : _BK_VALUE_KEY[String(K)]
    index = _ed_index_of(getfield(b, :model), b, at)
    raw = getfield(b, :raw)
    entries = get(raw, "entries", nothing)
    py_truthy(entries) || return nothing
    for e in collect(entries)
        if _py_or_dict(get(e, "index", nothing)) == index && haskey(e, key)
            delete!(e, key)
            if !any(k -> k != "index", keys(e))
                k = findfirst(x -> x == e, entries)
                k === nothing || deleteat!(entries, k)
            end
        end
    end
    return nothing
end

"""Every `(index, value)` set for `key` (the value by default)."""
function overrides(b::Block{K}, key_=nothing; key=key_) where {K}
    key = py_truthy(key) ? _py_str(key) : _BK_VALUE_KEY[String(K)]
    return Any[(JDict(_py_or_dict(get(e, "index", nothing))), e[key])
               for e in _py_iter(get(getfield(b, :raw), "entries", nothing)) if haskey(e, key)]
end

"""Every index combination the block holds a value at, the last dimension varying fastest."""
combinations(b::Block) = index_combinations(getfield(b, :model), b.index_lists)

# --- the edits that reach beyond a block, from its view -------------------------------------------------

rename_block!(b::Block, new_name) = (rename_block!(getfield(b, :model), _bk_qualified_name(b), new_name); b)
move_block!(b::Block, system="") = (move_block!(getfield(b, :model), _bk_qualified_name(b), system); b)
delete_block!(b::Block) = delete_block!(getfield(b, :model), _bk_qualified_name(b))
references_to(b::Block) = references_to(getfield(b, :model), _bk_qualified_name(b))
reads(b::Block) = reads(getfield(b, :model), _bk_qualified_name(b))

# --- what each kind adds -------------------------------------------------------------------------------

"""The transfers out of a compartment."""
function outflows(c::Compartment)
    q = _bk_qualified_name(c)
    return [t for t in transfers(c.model) if get(t.raw, "from", nothing) == q]
end

"""The transfers and inflows into a compartment."""
function inflows(c::Compartment)
    q = _bk_qualified_name(c)
    out = Block[t for t in transfers(c.model) if get(t.raw, "to", nothing) == q]
    append!(out, [s for s in inflows(c.model) if get(s.raw, "to", nothing) == q])
    return out
end

"""
    set_availability!(t, scheme; limit, top, bottom, over, basis, unavailable=false)

Limits a transfer's flux to what is available of the donor: `"limit"`
(`min(limit / amount, 1)`), `"langmuir"` (`(amount + top) / (amount +
bottom)`), or their `shared_` forms, which sum the amount over the group
`over` names (`basis` `"moles"` sums moles). `unavailable` takes one minus
the availability. `nothing` removes it.
"""
function set_availability!(t::Transfer, scheme; limit=nothing, top=nothing, bottom=nothing, over=nothing,
                           basis=nothing, unavailable=false)
    raw = getfield(t, :raw)
    if scheme === nothing
        delete!(raw, "availability")
        return nothing
    end
    scheme in _BK_AVAILABILITY_SCHEMES ||
        throw(EditError("'$(_py_str(scheme))' is not an availability scheme ($(join(_BK_AVAILABILITY_SCHEMES, ", ")))"))
    a = JDict("scheme" => scheme)
    if scheme in ("limit", "shared_limit")
        limit === nothing && throw(EditError("A solubility limit needs its limit"))
        a["limit"] = equation_text(limit)
    else
        (top === nothing || bottom === nothing) && throw(EditError("A Langmuir scheme needs top and bottom"))
        a["top"] = equation_text(top)
        a["bottom"] = equation_text(bottom)
    end
    if startswith(scheme, "shared_")
        py_truthy(over) && (a["over"] = over)
        if basis !== nothing
            basis in _BK_AVAILABILITY_BASES ||
                throw(EditError("'$(_py_str(basis))' is not a basis ($(join(_BK_AVAILABILITY_BASES, ", ")))"))
            a["basis"] = basis
        end
    end
    py_truthy(unavailable) && (a["unavailable"] = true)
    raw["availability"] = a
    return nothing
end

"""
    set_distribution!(p, kind, at=nothing; params...)

Sets a parameter's distribution, for the block or for one index combination:
`set_distribution!(kd, "logt"; at="Cs-137", min=1e-4, max=1e-2, mode=1e-3)`.
`kind` `nothing` removes it. Truncation (`trmin`, `trmax`, `pmin`, `pmax`)
and a correlation `group` go with the parameters.
"""
function set_distribution!(p::Parameter, kind, at_=nothing; at=at_, params...)
    if kind === nothing
        at === nothing ? delete!(getfield(p, :raw), "pdf") : clear_value!(p, at, "pdf")
        return nothing
    end
    spec = make_pdf(kind; params...)
    if at === nothing
        getfield(p, :raw)["pdf"] = spec
    else
        set_value!(p, spec, at, "pdf")
    end
    return nothing
end

"""The distribution that applies at an index combination."""
distribution_at(p::Parameter, at_=nothing; at=at_) = value_at(p, at, "pdf")

"""
    set_point_distribution!(l, i, kind; params...)

Gives point `i` (counted from 1) of a lookup table a distribution; `kind`
`nothing` removes it.
"""
function set_point_distribution!(l::Lookup, i::Integer, kind; params...)
    pts = l.points
    1 <= i <= length(pts) || throw(EditError("$(_bk_local_name(l)) has no point $i"))
    x, y = pts[i][1], pts[i][2]
    pts[i] = kind === nothing ? Any[x, y] : Any[x, y, make_pdf(kind; params...)]
    return nothing
end

"""Reduces over another of the target's index lists."""
reduce_over!(r::IndexReduction, list_name) =
    set_reduction_target!(getfield(r, :model), _bk_qualified_name(r), r.target; over=list_name)

"""Sends a far-field path's or waste packages' release to a compartment (`nothing`: nowhere, only read)."""
set_release!(b::Union{Farfield,WastePackage}, to) = set_release!(getfield(b, :model), _bk_qualified_name(b), to)

"""
    set_failure!(w, failure; settings...)

Sets how waste packages fail, with the settings that law reads:
`set_failure!(pkgs, "weibull"; fail_start=1000, fail_scale=1e5, fail_shape=2)`.
"""
function set_failure!(w::WastePackage, failure; settings...)
    failure in FAILURES || throw(EditError("'$(_py_str(failure))' is not a way of failing ($(join(FAILURES, ", ")))"))
    unknown = [String(k) for k in keys(settings) if !(String(k) in WASTE_SINGLE_KEYS)]
    isempty(unknown) || throw(EditError("A failure law has no $(join(map(_py_repr, unknown), ", "))"))
    w.failure = failure
    for (k, v) in settings
        setproperty!(w, k, v)
    end
    raw = getfield(w, :raw)
    missing_ = [k for k in FAILURE_KEYS[failure] if isempty(strip(_py_str(get(raw, k, WASTE_DEFAULTS[k]))))]
    isempty(missing_) || throw(EditError("'$failure' needs $(join(missing_, ", "))"))
    return nothing
end

"""Fails `fraction` of the intact packages of a waste-package block when the event happens."""
function add_fail_action!(e::Event, packages, fraction="1")
    found = get_block(getfield(e, :model), _name_arg(packages))
    (found === nothing || _kind_name(found) != "waste_package") &&
        throw(EditError("'$(_py_str(_name_arg(packages)))' is not a set of waste packages"))
    a = JDict("kind" => "fail", "fraction" => equation_text(fraction), "block" => _bk_qualified_name(found))
    push!(e.actions, a)
    return a
end

"""Moves `fraction` of `source`'s inventory to `target` (`nothing`: out of the model) when the event happens."""
function add_move_action!(e::Event, source, target=nothing, fraction="1")
    m = getfield(e, :model)
    found = get_block(m, _name_arg(source))
    (found === nothing || _kind_name(found) != "compartment") &&
        throw(EditError("'$(_py_str(_name_arg(source)))' is not a compartment"))
    to = nothing
    if target !== nothing
        t = get_block(m, _name_arg(target))
        (t === nothing || _kind_name(t) != "compartment") &&
            throw(EditError("'$(_py_str(_name_arg(target)))' is not a compartment"))
        t == found && throw(EditError("An event cannot move an inventory onto itself"))
        to = _bk_qualified_name(t)
    end
    a = JDict("kind" => "move", "fraction" => equation_text(fraction), "from" => _bk_qualified_name(found), "to" => to)
    push!(e.actions, a)
    return a
end

"""Removes every action of an event."""
clear_actions!(e::Event) = (getfield(e, :raw)["actions"] = Any[]; nothing)
