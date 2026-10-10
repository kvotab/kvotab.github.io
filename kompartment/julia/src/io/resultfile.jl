# A run's results as an HDF5 tree, as Kompartment writes one.
#
# A port of the Python package's `kompartment/io/resultfile.py`, itself a port
# of the application's `src/io/resultfile.js`: the result-browser convention
# (Ecolego's own shape) laid over hdf5.jl, so a file written from Julia is, for
# the same numbers, the file the application and the Python package write, to
# the byte:
#
#     /time                        the output grid, once, with its unit
#     /IndexLists/Radionuclides    the members of each index list, by name
#     /Soil/                       a block, as a group, when it is indexed
#          @IndexLists = ['Radionuclides']
#          @time_dependent = 'TRUE'
#          Cs-137                  one series per member
#     /NearField/Flux              a block that is not indexed, as a dataset
#
# Two dimensions nest: a block indexed by areas and nuclides is
# `/Dose/<area>/<nuclide>`, the nuclide the leaf and each `<area>` a group
# carrying the `IndexLists` that gets the nuclides drawn together. A value
# that cannot change over the run (`timeDependent` false on its descriptor) is
# one value -- one per realisation in a file of realisations -- and says
# `time_dependent = 'FALSE'`.
#
# Indices are 1-based throughout: `which` holds 1-based positions in the
# outputs, `column(i)` and a realisations' `matrix_for(i)` are called with the
# 1-based position of the output, and a probabilistic input's `"k"` is a
# 1-based row of `samples`.
#
# What this file needs from the rest of the package -------------------------------------
#
# Results (`results_tree`, `write_results_hdf5`, `scenarios_tree`):
#   res.t                    Vector{Float64}, the output times
#   outputs(res)             the series descriptors, in order (a Vector of JDict): "label", "block",
#                            "kind", "nuclide", "index", "dims", "unit", "source", "offset", and
#                            "timeDependent" => false only on a series that cannot change over the run
#   series_many(res, outs)   one Vector{Float64} per descriptor of `outs` (a Vector of descriptors taken
#                            from `outputs(res)`), in order
#   series(res, out)         one descriptor's Vector{Float64}
#   res.project              the engine Project: `raw` (the model file's dictionary -- "name",
#                            "description", "simulation", "index_lists"...) and `index_lists` (a Vector of
#                            JDict, each with "name" and "indices" => [JDict("name" => ..., "enabled" => ...)],
#                            and "for_scenarios" => true on the scenario list)
#
# A probabilistic run (`probabilistic_tree`, `write_probabilistic_hdf5`):
#   prob.t                   Vector{Float64}, the sample's output grid, the one every realisation was
#                            reported on
#   prob.outputs             the kept series' descriptors (as above), in order
#   prob.values              one matrix per kept series, n × times: row i is realisation i (Float64 or
#                            Float32; a failed realisation's row NaN)
#   prob.samples             a matrix, inputs × n: row k is what was drawn for varied input k
#   prob.ran                 a Vector of n (Bool or UInt8), false/0 where a realisation failed; or nothing
#   prob.iterations          Int
#   prob.inputs              a Vector of JDict("output" => a varied parameter's descriptor, "k" => its row of
#                            `samples`, 1-based); empty when nothing was varied that way
#
# Scenarios: `runs` is an ordered dictionary (or a vector of pairs) scenario name => Results, in the
# model's order.

# The Results interface (the methods are the Results type's own).
function outputs end
function series_many end
function series end

# JavaScript's `undefined`: a property that is not there, as distinct from `null` (`nothing`).
struct _RfUndefined end
const _RF_UNDEF = _RfUndefined()
Base.show(io::IO, ::_RfUndefined) = print(io, "undefined")

const _RfAttrs = OrderedDict{String,Any}

"""A dictionary's shallow copy (`{**d}`, `dict(d)`), its keys as strings."""
function _rf_copy(d)
    out = _RfAttrs()
    for (k, v) in d
        out[k isa AbstractString ? String(k) : js_string(k)] = v
    end
    return out
end

# The helpers below take what a descriptor holds, which is anything: they are
# compiled once for `Any` (`@nospecialize`) and test types themselves, so a
# result file of three hundred thousand series is not three million dynamic
# dispatches.

"""`obj[key]` for a dictionary, and `undefined` for anything else."""
function _rf_get(@nospecialize(obj), key::String)
    obj isa _RfAttrs && return get(obj, key, _RF_UNDEF)
    obj isa H5Attrs && return get(obj, key, _RF_UNDEF)
    obj isa Dict{String,Any} && return get(obj, key, _RF_UNDEF)
    return obj isa AbstractDict ? get(obj, key, _RF_UNDEF) : _RF_UNDEF
end

_rf_nullish(@nospecialize(v)) = v === nothing || v === _RF_UNDEF

"""`v ?? default`."""
_rf_nz(@nospecialize(v), @nospecialize(default)) = _rf_nullish(v) ? default : v

"""JavaScript's ToBoolean: an object or array is true however empty; 0, NaN and '' are not."""
function _rf_truthy(@nospecialize(v))
    _rf_nullish(v) && return false
    v isa Bool && return v
    v isa String && return !isempty(v)
    v isa Float64 && return !(v == 0 || isnan(v))
    v isa Int && return v != 0
    v isa Real && return !(v == 0 || isnan(v))
    v isa AbstractString && return !isempty(v)
    return true
end

"""Python's truthiness, for the places the Python package writes `x or []`."""
function _rf_pytruthy(v)
    _rf_nullish(v) && return false
    v isa Bool && return v
    v isa Number && return v != 0
    (v isa AbstractString || v isa AbstractArray || v isa AbstractDict || v isa Tuple) && return !isempty(v)
    return true
end

"""`String(v)`, with `undefined` written as JavaScript writes it."""
_rf_text(@nospecialize(v))::String = v isa String ? v : v === _RF_UNDEF ? "undefined" : js_string(v)::String

"""`obj.key` for a dictionary or an object: the property, or `undefined`."""
function _rf_attr(obj, key::String)
    obj isa AbstractDict && return get(obj, key, _RF_UNDEF)
    s = Symbol(key)
    return hasproperty(obj, s) ? getproperty(obj, s) : _RF_UNDEF
end

"""An object's property, or `nothing` when it has none (`getattr(obj, name, None)`)."""
_rf_prop(obj, s::Symbol) = (obj !== nothing && !(obj isa AbstractDict) && hasproperty(obj, s)) ? getproperty(obj, s) : nothing

"""What Python's `for x in v` walks: a list's items, a string's characters, a dictionary's keys."""
_rf_iter(v::Union{AbstractVector,Tuple}) = v
_rf_iter(v::AbstractArray) = _csv_c_order(v)
_rf_iter(v::AbstractString) = [string(c) for c in v]
_rf_iter(v::AbstractDict) = collect(keys(v))
_rf_iter(v) = throw(ArgumentError("'$(typeof(v))' is not a list"))

"""Python's `int(x)`."""
_rf_pyint(x::Integer) = Int(x)
_rf_pyint(x::AbstractFloat) = Int(trunc(x))
_rf_pyint(x::AbstractString) = parse(Int, strip(x))
_rf_pyint(x) = throw(ArgumentError("'$(x)' is not a whole number"))

"""JavaScript's whitespace off both ends."""
_rf_strip(s::AbstractString) = _csv_js_strip(s)

"""What a name has to be before it can be a link (`linkName`): a slash is the
one character HDF5 keeps for itself, and is replaced by U+2044."""
function _rf_link_name(@nospecialize(s))::String
    out::String = s isa String ? s : _rf_nullish(s) ? "" : js_string(s)::String
    occursin('/', out) && (out = replace(out, '/' => '⁄'))
    t = _rf_strip(out)
    return (isempty(t) || t == "." || t == "..") ? "_" : String(t)
end

"""Puts `node` at `path`, numbering the last name past one already taken."""
function _rf_place(root::H5Group, path::Vector{String}, node::H5Node)
    try
        return h5put(root, path, node)
    catch first
        head = path[1:end-1]
        last = path[end]
        for n in 2:999
            try
                return h5put(root, [head; "$(last) ($(n))"], node)
            catch
                # keep counting
            end
        end
        throw(first)
    end
end

"""`a === b` for the values a descriptor holds."""
function _rf_strictly_equal(@nospecialize(a), @nospecialize(b))
    if a isa AbstractString || b isa AbstractString
        return a isa AbstractString && b isa AbstractString && a == b
    end
    if a isa Bool || b isa Bool
        return a isa Bool && b isa Bool && a == b
    end
    a isa Real && b isa Real && return a == b
    return a === b
end

"""`values.indexOf(wanted)`, 1-based (0 when it is not there): strict equality, so NaN is never found."""
function _rf_index_of(values, @nospecialize(wanted))
    for (i, v) in enumerate(values)
        _rf_strictly_equal(v, wanted) && return i
    end
    return 0
end

"""Where one series goes, and which dimension its group carries (`pathOf`)."""
function _rf_path_of(@nospecialize(o))
    block = _rf_get(o, "block")
    _rf_nullish(block) && (block = _rf_get(o, "label"))
    _rf_nullish(block) && (block = "value")
    text::String = block isa String ? block : js_string(block)::String
    if occursin('.', text)
        parts = String[_rf_link_name(p) for p in split(text, '.')]
    else
        parts = sizehint!(String[], 4)
        push!(parts, _rf_link_name(text))
    end
    dims = _rf_get(o, "dims")
    index = _rf_get(o, "index")
    (_rf_nullish(dims) || _rf_nullish(index)) && return parts, nothing
    if dims isa Vector{Any} && index isa Vector{Any}            # a descriptor read from JSON
        return _rf_nest!(parts, dims, index, _rf_get(o, "nuclide"))
    end
    return _rf_nest!(parts, _rf_iter(dims), _rf_iter(index), _rf_get(o, "nuclide"))
end

# The rest of the path, from the index: compiled for the list types it meets.
function _rf_nest!(parts::Vector{String}, dims, index, @nospecialize(nuclide))
    (isempty(dims) || isempty(index)) && return parts, nothing
    # The nuclide is the leaf when there is one; otherwise the last dimension.
    leaf = length(index)
    if !_rf_nullish(nuclide)
        at = _rf_index_of(index, nuclide)
        at >= 1 && (leaf = at)
    end
    for i in 1:length(index)
        i == leaf || push!(parts, _rf_link_name(index[i]))
    end
    push!(parts, _rf_link_name(index[leaf]))
    leaf_dim::Any = leaf <= length(dims) ? dims[leaf] : nothing
    return parts, leaf_dim
end

"""
    description_html(text) -> Union{String,Nothing}

The model's description as the markup the result browser renders
(`descriptionHTML`), or `nothing` when there is nothing to say. The text is
escaped first -- the description is plain text, so a `<` in it is a `<`
somebody meant -- then blank lines become paragraphs and single newlines
breaks.
"""
function description_html(text)
    s = _rf_nullish(text) ? "" : js_string(text)
    clean = _rf_strip(replace(s, r"\r\n?" => "\n"))
    isempty(clean) && return nothing
    io = IOBuffer()
    for para in split(clean, r"\n{2,}")
        escaped = replace(para, '&' => "&amp;", '<' => "&lt;", '>' => "&gt;")
        print(io, "<p>", replace(escaped, '\n' => "<br>"), "</p>")
    end
    return String(take!(io))
end

# A time as the page's clock reads it: local. `nothing` is now, a DateTime is
# taken as the local time it already is, a Date is its midnight, and a number
# is seconds since the epoch.
function _rf_stamp(when)
    if when === nothing
        d = Dates.now()
    elseif when isa DateTime
        d = when
    elseif when isa Date
        d = DateTime(when)
    elseif when isa Real
        # As Python's `datetime.fromtimestamp` splits it: whole seconds and
        # microseconds rounded half to even, a full second carried.
        x = Float64(when)
        ip = trunc(x)
        fp = round((x - ip) * 1e6, RoundNearest)
        if fp >= 1e6
            ip += 1
        elseif fp < 0
            ip -= 1
        end
        tm = Libc.TmStruct(ip)
        return @sprintf("%d-%02d-%02d %02d:%02d:%02d", tm.year + 1900, tm.month + 1, tm.mday, tm.hour, tm.min, tm.sec)
    else
        throw(ArgumentError("a time is a DateTime, a Date or seconds since the epoch, not a $(typeof(when))"))
    end
    return @sprintf("%d-%02d-%02d %02d:%02d:%02d", Dates.year(d), Dates.month(d), Dates.day(d), Dates.hour(d),
                    Dates.minute(d), Dates.second(d))
end

"""The model as a dictionary: an engine Project's file (`raw`), or the dictionary given."""
function _rf_project_dict(project)
    project === nothing && return _RfAttrs()
    project isa AbstractDict && return project
    for f in (:raw, :_raw)
        r = _rf_prop(project, f)
        r isa AbstractDict && return r
    end
    sim = _rf_prop(project, :simulation)
    return _RfAttrs("name" => _rf_prop(project, :name), "description" => _rf_prop(project, :description),
                    "simulation" => _rf_pytruthy(sim) ? sim : _RfAttrs())
end

_rf_length(values) = values isa Union{AbstractArray,Tuple,AbstractString} ? length(values) : 0

"""`column(i)[0]` as a double: NaN where there is none."""
function _rf_first(values)
    _rf_length(values) == 0 && return NaN
    return js_to_number(first(values))
end

"""`sample.of === 'mean' ? 'mean' : Number(sample.of)`."""
_rf_realisation_of(of) = (of isa AbstractString && of == "mean") ? "mean" : of === _RF_UNDEF ? NaN : js_to_number(of)

function _rf_matrix_of(realisations, i::Int)
    fn = _rf_get(realisations, "matrix_for")
    fn === _RF_UNDEF && (fn = _rf_get(realisations, "matrixFor"))
    if fn === _RF_UNDEF
        fn = _rf_prop(realisations, :matrix_for)
        fn === nothing && (fn = _rf_prop(realisations, :matrixFor))
    end
    return fn(i)
end

"""
    result_tree(; t, outputs, column, which, project=nothing, index_lists=nothing,
                now=nothing, realisations=nothing, sample=nothing) -> H5Group

The tree for a run (`resultTree`), ready for `write_hdf5`.

`t` is the output times; `outputs` the series descriptors (`"label"`,
`"block"`, `"kind"`, `"nuclide"`, `"index"`, `"dims"`, `"unit"`,
`"timeDependent"`) in order; `column(i)` one series' values; `which` the
outputs to write, as **1-based** positions in `outputs`. `project` is the model,
for its name, description and settings (its dictionary, or an engine Project,
whose `raw` is read); `index_lists` its index lists, each a dictionary with
`"name"` and `"indices"` (or the shorthand `"elements"`). `now` is the
`created_time`: a `DateTime` (taken as local time), a `Date`, or seconds since
the epoch; `nothing` is now.

`realisations` -- `Dict("iterations" => n, "matrix_for" => fn)` (or anything
with those properties; `matrixFor` is read too) -- writes every run of a
probabilistic result: `fn(i)` returns `times × n` values for series `i`, flat
and time-major (float32), `n` of them for one that cannot change over the run,
or `nothing` for a series that was not part of the run. `sample` --
`Dict("iterations" => n, "of" => "mean" | k)` -- says that the curves are the
mean of a probabilistic run or its `k`-th realisation.
"""
function result_tree(; t, outputs, column, which, project=nothing, index_lists=nothing, now=nothing,
                     realisations=nothing, sample=nothing)
    project = _rf_project_dict(project)
    sim = _rf_nz(_rf_get(project, "simulation"), _RfAttrs())
    time_unit = _rf_nz(_rf_get(sim, "time_unit"), "year")
    created = _rf_stamp(now)
    iterations = realisations !== nothing ? _rf_attr(realisations, "iterations") : _RF_UNDEF
    name = _rf_get(project, "name")
    probabilistic = _rf_truthy(realisations)
    attrs = H5Attrs(
        "model" => _rf_nullish(name) ? "model" : name,
        "created_time" => created,
        "source" => "Kompartment",
        "time_unit" => time_unit,
        "start_time" => js_to_number(_rf_nz(_rf_get(sim, "start_time"), 0)),
        "end_time" => js_to_number(_rf_nz(_rf_get(sim, "end_time"), 0)),
        "solver" => js_string(_rf_nz(_rf_get(sim, "solver"), "")),
        "series" => length(which),
        "probabilistic" => probabilistic,
    )
    if probabilistic
        attrs["n_iter"] = iterations === _RF_UNDEF ? nothing : iterations
    end
    sampled = _rf_truthy(sample)
    if sampled
        n = _rf_attr(sample, "iterations")
        attrs["n_iter"] = n === _RF_UNDEF ? nothing : n
        attrs["realisation"] = _rf_realisation_of(_rf_attr(sample, "of"))
    end
    attrs["Information"] = description_html(_rf_get(project, "description"))
    root = h5group(attrs)

    # `probabilistic` on /time is whether the *time axis* is a matrix, which it
    # never is: every realisation is reported on the one output grid.
    h5put(root, ["time"], h5dataset(t, H5F64, H5Attrs(
        "unit" => time_unit, "created_time" => created, "name" => "time", "probabilistic" => false)))

    # The index lists, whole: the members of a dimension and their order, and
    # only the members that are switched on. An index may be the bare string a
    # file wrote it as, and that string is its name.
    for lst in (_rf_pytruthy(index_lists) ? index_lists : ())
        indices = _rf_get(lst, "indices")
        names = Any[]
        if _rf_truthy(indices)
            for i in _rf_iter(indices)
                i === nothing && continue
                if i isa Union{AbstractDict,AbstractVector,Tuple}
                    enabled = _rf_get(i, "enabled")
                    (enabled isa Bool && !enabled) && continue
                    push!(names, _rf_get(i, "name"))
                else
                    push!(names, i)
                end
            end
        else
            elements = _rf_get(lst, "elements")
            _rf_nullish(elements) || append!(names, _rf_iter(elements))
        end
        members = String[_rf_text(e) for e in names if !_rf_nullish(e)]
        isempty(members) && continue
        list_name = _rf_get(lst, "name")
        list_name === _RF_UNDEF && (list_name = nothing)
        _rf_place(root, ["IndexLists", _rf_link_name(list_name)],
                  h5dataset(members, H5STR, H5Attrs("name" => list_name, "members" => length(members))))
    end

    n_iter = _rf_nullish(iterations) ? 0 : iterations
    keys_plain = ["unit", "time_dependent", "probabilistic", "kind", "block", "name", "index", "created_time"]
    keys_matrix = ["unit", "time_dependent", "probabilistic", "n_iter", "kind", "block", "name", "index",
                   "created_time"]
    keys_sample = ["unit", "time_dependent", "probabilistic", "n_iter", "realisation", "kind", "block", "name",
                   "index", "created_time"]
    sample_n = nothing
    sample_of = nothing
    if sampled
        n = _rf_attr(sample, "iterations")
        sample_n = n === _RF_UNDEF ? nothing : n
        sample_of = _rf_realisation_of(_rf_attr(sample, "of"))
    end
    for i in which
        o = outputs[i]
        path, leaf_dim = _rf_path_of(o)
        # Every run of it, where there is one, as float32: a Monte Carlo sample
        # does not need the digits, and Ecolego writes its own series so.
        matrix = probabilistic ? _rf_matrix_of(realisations, i) : nothing
        matrix === _RF_UNDEF && (matrix = nothing)
        still = _rf_get(o, "timeDependent") === false
        if matrix !== nothing
            if still && _rf_length(matrix) > js_to_number(n_iter)
                k = _rf_pyint(n_iter)
                values = matrix[1:(k >= 0 ? k : max(_rf_length(matrix) + k, 0))]
            else
                values = matrix
            end
        else
            values = still ? Float64[_rf_first(column(i))] : column(i)
        end
        unit = _rf_get(o, "unit")
        unit = _rf_truthy(unit) ? unit : ""
        # The names are the same for every series of a shape, so the series
        # share one vector of them (copied should one change) and each has
        # only its values: unit, time_dependent, probabilistic, [n_iter,
        # [realisation]], kind, block, name, index, created_time.
        label = _rf_get(o, "label")
        block = _rf_text(_rf_nz(_rf_get(o, "block"), ""))
        vals = Vector{Any}(undef, matrix !== nothing ? 9 : (sampled ? 10 : 8))
        vals[1] = unit
        vals[2] = !still
        vals[3] = matrix !== nothing
        k = 4
        if matrix !== nothing
            vals[k] = iterations === _RF_UNDEF ? nothing : iterations
            k += 1
        elseif sampled
            vals[k] = sample_n
            vals[k+1] = sample_of
            k += 2
        end
        vals[k] = _rf_text(_rf_nz(_rf_get(o, "kind"), ""))
        vals[k+1] = block
        vals[k+2] = label === _RF_UNDEF ? nothing : label
        # What the browser writes as the column heading of this series.
        vals[k+3] = (label === _RF_UNDEF ? NaN : label,)
        vals[k+4] = created
        node_attrs = H5Attrs(matrix !== nothing ? keys_matrix : sampled ? keys_sample : keys_plain, vals, true)
        dims = matrix !== nothing && !still ? Any[length(t), iterations] : nothing
        node = h5dataset(values, matrix !== nothing ? H5F32 : H5F64, node_attrs, dims)
        _rf_place(root, path, node)
        _rf_truthy(leaf_dim) || continue
        holder = root
        for k in 1:length(path)-1
            holder = holder isa H5Group ? get(holder.children, path[k], nothing) : nothing
        end
        holder isa H5Group || continue
        # Said once per group, the same way every time, so two series of one
        # block cannot disagree about what the group is. (The Python builds a
        # new dictionary, `{**before, ...}`; setting the keys of an ordered one
        # in place gives the same keys in the same order.)
        before = holder.attrs === nothing ? H5Attrs() : holder.attrs
        a = before isa H5Attrs ? before : H5Attrs(_h5_pairs(before))
        _rf_group_attrs!(a, leaf_dim, still, matrix !== nothing, unit, block)
        holder.attrs = a
    end
    return root
end

# What a group of one block's series says about them, set on the group's own
# attributes in place.
function _rf_group_attrs!(a::H5Attrs, @nospecialize(leaf_dim), still::Bool, probabilistic::Bool, @nospecialize(unit),
                          block::String)
    i = _h5_slot(a, "unit")
    group_unit = (i == 0 || (a.vals[i] == unit) === true) ? unit : ""
    i = _h5_slot(a, "IndexLists")
    lists = i == 0 ? nothing : a.vals[i]
    if !(lists isa Vector{Any} && length(lists) == 1 && lists[1] === leaf_dim)
        a["IndexLists"] = Any[leaf_dim]
    end
    a["time_dependent"] = !still
    a["probabilistic"] = probabilistic
    a["unit"] = group_unit
    a["block"] = block
    return a
end

# --- from a Results -----------------------------------------------------------------------

"""Where each asked-for output is, 1-based: by position, by label, or as the descriptor itself."""
function _rf_which_of(outs, which)
    which === nothing && return collect(1:length(outs))
    # Where each label is first: a large model reports hundreds of thousands of
    # series, and a search through them for every one asked for took longer
    # than writing the file. An output given as itself is found by its label,
    # which finds it or an earlier one of the same label, as the search did.
    first = Dict{Any,Int}()
    for (j, o) in enumerate(outs)
        label = o isa AbstractDict ? get(o, "label", nothing) : nothing
        haskey(first, label) || (first[label] = j)
    end
    out = Int[]
    for w in which
        if w isa AbstractString || w isa AbstractDict
            label = w isa AbstractString ? w : get(w, "label", nothing)
            k = get(first, label, nothing)
            if k === nothing && w isa AbstractDict
                k = findfirst(o -> o === w, outs)
            end
            k === nothing && throw(ArgumentError("No output labelled '$(label)'"))
            push!(out, k)
        elseif w isa Integer
            push!(out, Int(w))
        else
            push!(out, _rf_pyint(w))
        end
    end
    return out
end

"""
    results_tree(res, which=nothing; project=nothing, index_lists=nothing, now=nothing,
                 column=nothing, realisations=nothing, sample=nothing) -> H5Group

The tree of a run, as the page's *Export to HDF5* builds it.

`res` is a run's results (`res.t`, `outputs(res)`, `series_many`, `series`,
`res.project`); `which` the series to write -- 1-based positions in
`outputs(res)`, labels, or descriptors -- every one of them by default.
`project` is the model the file names (a dictionary or a Project): by default
the model the run was built from. `index_lists` defaults to the index lists the
run was built with. `column(i)` overrides where series `i`'s values come from
(the mean of a probabilistic run, say); by default they are the run's own,
worked out in one pass. `now`, `realisations` and `sample` are as in
`result_tree`.
"""
function results_tree(res, which=nothing; project=nothing, index_lists=nothing, now=nothing, column=nothing,
                      realisations=nothing, sample=nothing)
    outs = outputs(res)
    chosen = _rf_which_of(outs, which)
    project === nothing && (project = _rf_project_dict(res.project))
    if index_lists === nothing
        lists = _rf_prop(res.project, :index_lists)
        index_lists = _rf_pytruthy(lists) ? lists : Any[]
    end
    if column === nothing
        wanted = unique(chosen)
        cache = Dict{Int,Any}()
        if !isempty(wanted)
            for (k, values) in zip(wanted, series_many(res, [outs[k] for k in wanted]))
                cache[k] = values
            end
        end
        column = i -> get!(() -> series(res, outs[i]), cache, i)
    end
    return result_tree(; t=res.t, outputs=outs, column, which=chosen, project, index_lists, now, realisations,
                       sample)
end

"""
    write_results_hdf5(res, path=nothing, which=nothing; kwargs...) -> Vector{UInt8}

A run as an HDF5 result file's bytes, written to `path` too when one is given.
The keyword arguments are `results_tree`'s.
"""
function write_results_hdf5(res, path=nothing, which=nothing; kwargs...)
    data = write_hdf5(results_tree(res, which; kwargs...))
    path === nothing || write(path, data)
    return data
end

# --- a probabilistic run ------------------------------------------------------------------

"""The index lists the application hands a result file for a model: the stored ones and those derived from them."""
function _rf_index_lists_of(project)
    project === nothing && return Any[]
    lists = _rf_prop(project, :index_lists)
    # An engine Project's lists, as dictionaries (a model's views of its lists are read from its file instead).
    (lists isa AbstractVector && all(l -> l isa AbstractDict, lists)) && return lists
    raw = _rf_project_dict(project)
    stored = raw isa AbstractDict ? get(raw, "index_lists", nothing) : nothing
    return derive_block_lists(derive_elements(stored isa AbstractVector ? stored : Any[]), raw)
end

"""numpy's pairwise sum of `a[lo:lo+n-1]` (`pairwise_sum` in its loops), which is what
`sum(axis=0)` does down a single column."""
function _rf_pairwise_sum(a::Vector{Float64}, lo::Int, n::Int)
    if n < 8
        res = 0.0
        for i in 0:n-1
            res += a[lo+i]
        end
        return res
    elseif n <= 128
        r1, r2, r3, r4 = a[lo], a[lo+1], a[lo+2], a[lo+3]
        r5, r6, r7, r8 = a[lo+4], a[lo+5], a[lo+6], a[lo+7]
        i = 8
        while i < n - (n % 8)
            r1 += a[lo+i]; r2 += a[lo+i+1]; r3 += a[lo+i+2]; r4 += a[lo+i+3]
            r5 += a[lo+i+4]; r6 += a[lo+i+5]; r7 += a[lo+i+6]; r8 += a[lo+i+7]
            i += 8
        end
        res = ((r1 + r2) + (r3 + r4)) + ((r5 + r6) + (r7 + r8))
        while i < n
            res += a[lo+i]
            i += 1
        end
        return res
    end
    n2 = n ÷ 2
    n2 -= n2 % 8
    return _rf_pairwise_sum(a, lo, n2) + _rf_pairwise_sum(a, lo + n2, n - n2)
end

"""The mean of each column over the rows that are finite there, NaN where none
is -- summed as numpy sums `np.where(finite, m, 0).sum(axis=0)`: down the
rows one at a time, or pairwise when there is one column."""
function _rf_finite_mean(m::AbstractMatrix)
    n, times = size(m)
    out = Vector{Float64}(undef, times)
    if times == 1
        xs = Vector{Float64}(undef, n)
        count = 0
        for i in 1:n
            v = Float64(m[i, 1])
            finite = isfinite(v)
            xs[i] = finite ? v : 0.0
            count += finite
        end
        total = 0.0 + _rf_pairwise_sum(xs, 1, n)
        out[1] = count > 0 ? total / max(count, 1) : NaN
        return out
    end
    for j in 1:times                                    # each column summed from its first row down
        total = 0.0
        count = 0
        for i in 1:n
            v = Float64(m[i, j])
            if isfinite(v)
                total += v
                count += 1
            end
        end
        out[j] = count > 0 ? total / max(count, 1) : NaN
    end
    return out
end

_rf_item(obj, key::String) = obj isa AbstractDict ? get(obj, key, nothing) : _rf_prop(obj, Symbol(key))

"""
    probabilistic_tree(prob, want="all"; which=nothing, project=nothing, index_lists=nothing,
                       now=nothing, inputs=true) -> H5Group

A probabilistic run as a result file's tree, as the page's *Save →
Realisations* writes it.

`want` is what of the sample: `"all"` -- every realisation, one row per output
time and one column per realisation, as float32, or one value per realisation
for a series that cannot change over the run -- `"mean"`, the mean at every
time of the realisations that ran, or a realisation by its number, from 1
(clamped to the ones there are). The file says which, so it is not taken for a
deterministic run.

`which` picks the kept series (labels, 1-based positions or descriptors), every
one by default; with `inputs` the varied parameters come too, one value per
realisation (NaN for one that did not run). `project` is the model the file
names (a dictionary or an engine Project) and gives the index lists unless
`index_lists` does. The times are the sample's own grid. See the top of this
file for what `prob` has to provide.
"""
function probabilistic_tree(prob, want="all"; which=nothing, project=nothing, index_lists=nothing, now=nothing,
                            inputs::Bool=true)
    t = Float64[Float64(x) for x in prob.t]
    times = length(t)
    kept = [_rf_copy(o) for o in prob.outputs]
    described = Any[o for o in kept]
    source = Tuple{Symbol,Int}[(:kept, w) for w in 1:length(kept)]
    ran_raw = _rf_prop(prob, :ran)
    ran = ran_raw === nothing ? nothing : Bool[x != 0 for x in ran_raw]
    if inputs
        taken = Set{Any}(get(o, "label", nothing) for o in kept)
        for inp in something(_rf_prop(prob, :inputs), Any[])
            o = _rf_copy(_rf_item(inp, "output"))
            get(o, "label", nothing) in taken && continue
            push!(described, o)
            push!(source, (:input, _rf_pyint(_rf_item(inp, "k"))))
        end
    end
    values = prob.values
    n = !isempty(values) ? size(values[1], 1) : ran !== nothing ? length(ran) : _rf_pyint(prob.iterations)
    chosen = _rf_which_of(described, which)

    function draws(j::Int)
        col = Float64[Float64(x) for x in view(prob.samples, j, :)]
        if ran !== nothing && length(ran) == length(col)
            for i in eachindex(col)
                ran[i] || (col[i] = NaN)
            end
        end
        return col
    end
    rows(k::Int) = source[k][1] === :kept ? values[source[k][2]] : reshape(draws(source[k][2]), :, 1)
    still(k::Int) = source[k][1] === :input || get(described[k], "timeDependent", nothing) === false

    realisations = nothing
    sample = nothing
    if want isa AbstractString && want == "all"
        matrix_for = function (k::Int)
            m = rows(k)
            # Time-major: every realisation at the first time, then at the
            # second -- which is a column-major matrix's own order.
            return still(k) ? Float32[Float32(Float64(x)) for x in view(m, :, 1)] :
                   Float32[Float32(Float64(x)) for x in vec(m)]
        end
        column = k -> fill(NaN, times)
        realisations = _RfAttrs("iterations" => n, "matrix_for" => matrix_for)
    elseif want isa AbstractString && want == "mean"
        column = function (k::Int)
            m = rows(k)
            mean = _rf_finite_mean(m)
            return size(m, 2) == 1 ? fill(mean[1], times) : mean
        end
        sample = _RfAttrs("iterations" => n, "of" => "mean")
    else
        number = js_to_number(want)
        r = isfinite(number) ? floor(number + 0.5) : 1.0
        one = r >= n ? n : r <= 1 ? 1 : Int(r)
        one = min(n, max(1, one))
        column = function (k::Int)
            m = rows(k)
            return size(m, 2) == 1 ? fill(Float64(m[one, 1]), times) : Float64[Float64(x) for x in view(m, one, :)]
        end
        sample = _RfAttrs("iterations" => n, "of" => one)
    end
    # The run's own model where none is given: its name and index lists.
    project === nothing && (project = _rf_prop(prob, :project))
    index_lists === nothing && (index_lists = _rf_index_lists_of(project))
    return result_tree(; t, outputs=described, column, which=chosen, project, index_lists, now, realisations,
                       sample)
end

"""
    write_probabilistic_hdf5(prob, path=nothing, want="all"; kwargs...) -> Vector{UInt8}

A probabilistic run as an HDF5 result file's bytes, written to `path` too when
one is given. The keyword arguments are `probabilistic_tree`'s.
"""
function write_probabilistic_hdf5(prob, path=nothing, want="all"; kwargs...)
    data = write_hdf5(probabilistic_tree(prob, want; kwargs...))
    path === nothing || write(path, data)
    return data
end

# --- scenarios side by side -----------------------------------------------------------------

"""A curve on one time axis, read onto another (the page's `ontoAxis`): linear
between the first axis's points, NaN outside its span, and the curve itself
where the two are the same times."""
function _rf_onto_axis(frm, to)
    a_t = Float64[Float64(x) for x in frm]
    b_t = Float64[Float64(x) for x in to]
    a_t == b_t && return identity
    nb = length(b_t)
    idx = zeros(Int, nb)
    w = zeros(nb)
    k = 1
    last = length(a_t)
    for j in 1:nb
        x = b_t[j]
        while k + 1 <= length(a_t) && a_t[k+1] < x
            k += 1
        end
        idx[j] = k
        a, b = a_t[k], a_t[min(k + 1, last)]
        w[j] = (x < a_t[1] || x > a_t[last]) ? NaN : (b > a ? (x - a) / (b - a) : 0.0)
    end
    return function (v)
        v = Float64[Float64(x) for x in v]
        out = Vector{Float64}(undef, nb)
        for j in 1:nb
            i = idx[j]
            a = v[i]
            b = v[min(i + 1, length(v))]
            out[j] = a + (b - a) * w[j]
        end
        return out
    end
end

"""Python's `str(v)`, for the labels the Python package builds with an f-string."""
function _rf_pystr(v)
    v isa AbstractString && return String(v)
    v === nothing && return "None"
    v isa Bool && return v ? "True" : "False"
    v isa Integer && return string(v)
    if v isa AbstractFloat
        x = Float64(v)
        isnan(x) && return "nan"
        isinf(x) && return x > 0 ? "inf" : "-inf"
        x == 0 && return signbit(x) ? "-0.0" : "0.0"
        sign = x < 0 ? "-" : ""
        digits, decpt = shortest_digits(abs(x))
        k = length(digits)
        if decpt <= -4 || decpt > 16
            mant = k == 1 ? digits : digits[1:1] * "." * digits[2:end]
            e = decpt - 1
            return sign * mant * "e" * (e < 0 ? "-" : "+") * lpad(string(abs(e)), 2, '0')
        elseif decpt <= 0
            return sign * "0." * "0"^(-decpt) * digits
        elseif decpt >= k
            return sign * digits * "0"^(decpt - k) * ".0"
        end
        return sign * digits[1:decpt] * "." * digits[decpt+1:end]
    end
    return string(v)
end

"""The scenario list's name, as the page finds it: the model's list marked as
the scenario list, `Scenarios` where there is none."""
function _rf_scenario_list_name(project, results)
    raw = project !== nothing ? _rf_project_dict(project) : _rf_project_dict(results.project)
    stored = raw isa AbstractDict ? get(raw, "index_lists", nothing) : nothing
    for lst in (_rf_pytruthy(stored) ? _rf_iter(stored) : ())
        if lst isa AbstractDict && _rf_truthy(get(lst, "for_scenarios", nothing))
            return get(lst, "name", nothing)
        end
    end
    lists = _rf_prop(results.project, :index_lists)
    for lst in (_rf_pytruthy(lists) ? _rf_iter(lists) : ())
        if lst isa AbstractDict && _rf_truthy(get(lst, "for_scenarios", nothing))
            return get(lst, "name", nothing)
        end
    end
    return "Scenarios"
end

_rf_label(o) = o isa AbstractDict ? get(o, "label", nothing) : nothing

"""
    scenarios_tree(runs, which=nothing; active=nothing, project=nothing, index_lists=nothing,
                   now=nothing) -> H5Group

Several scenarios' runs as one result file, as the page writes a table that
holds more than one scenario: each series once per scenario, with the scenario
list as one more index of it, so every block holds a group per scenario the
way it holds one per nuclide.

`runs` is an ordered dictionary (or a vector of pairs) scenario => results, in
the model's order. `active` is the scenario the file is read against -- its
series and its output times -- the first by default; each other scenario's
series of the same label follows it, read onto those times (linearly, NaN
outside its own span). `which` picks the active run's series (1-based
positions, labels or descriptors), every one by default. With one run there is
nothing beside it and the file is that run's alone, as `results_tree` writes
it.
"""
function scenarios_tree(runs, which=nothing; active=nothing, project=nothing, index_lists=nothing, now=nothing)
    entries = runs isa AbstractDict ? collect(pairs(runs)) : collect(runs)
    names = Any[p.first for p in entries]
    isempty(names) && throw(ArgumentError("There are no runs to write."))
    active === nothing && (active = names[1])
    at = findfirst(nm -> isequal(nm, active), names)
    at === nothing && throw(ArgumentError("No run of the scenario '$(active)'"))
    r = entries[at].second
    others = [(p.first, p.second) for p in entries if !isequal(p.first, active)]
    project === nothing && (project = _rf_project_dict(r.project))
    if index_lists === nothing
        lists = _rf_prop(r.project, :index_lists)
        index_lists = _rf_pytruthy(lists) ? lists : Any[]
    end
    isempty(others) && return results_tree(r, which; project, index_lists, now)
    outs = outputs(r)
    chosen = _rf_which_of(outs, which)
    own = Dict{Int,Any}()
    for (i, values) in zip(chosen, series_many(r, [outs[i] for i in chosen]))
        own[i] = values
    end
    beside = []
    for (name, e) in others
        eo = outputs(e)
        by_label = Dict{Any,Int}()
        for (j, o) in enumerate(eo)
            by_label[_rf_label(o)] = j
        end
        wanted = unique(Int[by_label[_rf_label(outs[i])] for i in chosen if haskey(by_label, _rf_label(outs[i]))])
        cols = Dict{Int,Any}()
        if !isempty(wanted)
            for (j, values) in zip(wanted, series_many(e, [eo[j] for j in wanted]))
                cols[j] = values
            end
        end
        push!(beside, (name, eo, by_label, cols, _rf_onto_axis(e.t, r.t)))
    end
    spec = []
    for i in chosen
        o = outs[i]
        push!(spec, (o, "$(_rf_pystr(_rf_label(o))) · $(_rf_pystr(active))", active, own[i]))
        for (name, eo, by_label, cols, onto) in beside
            j = get(by_label, _rf_label(o), nothing)
            j === nothing && continue
            push!(spec, (eo[j], "$(_rf_pystr(_rf_label(o))) · $(_rf_pystr(name))", name, onto(cols[j])))
        end
    end
    list_name = _rf_scenario_list_name(project, r)
    souts = Any[]
    for (out, label, scenario, _) in spec
        d = _rf_copy(out)
        dims = get(out, "dims", nothing)
        index = get(out, "index", nothing)
        d["dims"] = Any[(_rf_pytruthy(dims) ? _rf_iter(dims) : ())..., list_name]
        d["index"] = Any[(_rf_pytruthy(index) ? _rf_iter(index) : ())..., scenario]
        d["label"] = label
        push!(souts, d)
    end
    values = [c[4] for c in spec]
    return result_tree(; t=r.t, outputs=souts, column=k -> values[k], which=collect(1:length(spec)), project,
                       index_lists, now)
end

"""
    write_scenarios_hdf5(runs, path=nothing, which=nothing; kwargs...) -> Vector{UInt8}

Several scenarios' runs as one HDF5 result file's bytes, written to `path` too
when one is given. The keyword arguments are `scenarios_tree`'s.
"""
function write_scenarios_hdf5(runs, path=nothing, which=nothing; kwargs...)
    data = write_hdf5(scenarios_tree(runs, which; kwargs...))
    path === nothing || write(path, data)
    return data
end
