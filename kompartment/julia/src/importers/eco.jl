# Importing Ecolego projects (.eco) and assessments (.eas).
#
# A port of the Python package's `kompartment/importers/eco.py`, itself a
# port of the application's importer, `src/io/eco.js`: the same file gives the
# same model -- a project dictionary in Kompartment's own format, key order
# included -- and the same report of what was renamed, skipped, switched off
# or could not come across:
#
#     project, report = import_eco_file("Vault_assessment.eas")
#     println(report.summary)
#
# A .eco file is a ZIP of the Ecolego project folder, and the model is its
# model.xml. An .eas assessment is the same archive with a run stored in it --
# a `simulation/` folder of results -- and is read exactly as a project is:
# the model comes across, the results do not. The older Ecolego 4/5 format, a
# bare XML file (usually UTF-16), is accepted too when it holds a
# `<data-model>`, and refused with an explanation when it is a `<sheet>`.
#
# The mapping is deliberately lossy and says so: what has no equivalent here
# is skipped and listed in the report, so the result is usable or explicitly
# incomplete -- never silently wrong. See the application's INTERNALS.md,
# "Importing .eco projects", and GUIDE.md, "Importing Ecolego projects".
#
# The project this returns is the importer's own output; `Model`'s
# normalisation (key migration, defaults, derived units) is not applied here.

"""A file the importer cannot read: not an Ecolego model, an Ecolego 4/5
`<sheet>`, an archive with no model in it, XML that does not parse, or a name
no model can hold. `EcoImportError` in the Python package (`ImportError` in
the application's src/io/eco.js)."""
struct EcoImportError <: Exception
    msg::String
end
Base.showerror(io::IO, e::EcoImportError) = print(io, e.msg)

include("eco_maps.jl")
include("eco_text.jl")
include("xml.jl")
include("eco_pdf.jl")
include("eco_zip.jl")

# --- the report ---------------------------------------------------------------------------

"""
What an import did: what came across, what was renamed, and above all what
could not come across. `ImportReport` in the Python package.

- `skipped`: `{type, name, why}` per block that has no equivalent here
- `notes`: `{type, name}` per block present but numerically inert
- `renamed`: `{from, to}` per name tidied into an identifier
- `disabled`: qualified names of blocks imported switched off, as in Ecolego
- `disabled_systems`: sub-system path => blocks inside it, for each sub-system
  the file switches off as a whole (`nothing` when none)
- `warnings`: what else is worth reading, each said once
- `counts`: how many of each kind came across

`report.ok` is whether every block came across, `report.summary` a short
account in words; `to_dict(report)` gives all of them as plain data.
"""
mutable struct EcoImportReport
    skipped::Vector{JDict}
    notes::Vector{JDict}
    renamed::Vector{JDict}
    disabled::Vector{String}
    disabled_systems::Union{Nothing,OrderedDict{String,Int}}
    warnings::Vector{String}
    counts::OrderedDict{String,Int}
    said::Set{String}
end
EcoImportReport() = EcoImportReport(JDict[], JDict[], JDict[], String[], nothing, String[],
                                    OrderedDict{String,Int}(), Set{String}())

function Base.getproperty(r::EcoImportReport, s::Symbol)
    s === :ok && return isempty(getfield(r, :skipped))
    s === :summary && return _eco_summary(r)
    return getfield(r, s)
end
Base.propertynames(::EcoImportReport) = (:skipped, :notes, :renamed, :disabled, :disabled_systems, :warnings,
                                         :counts, :ok, :summary)

function Base.show(io::IO, r::EcoImportReport)
    print(io, "<ImportReport $(length(r.skipped)) skipped, $(length(r.renamed)) renamed, ",
          "$(length(r.warnings)) warnings>")
end
Base.show(io::IO, ::MIME"text/plain", r::EcoImportReport) = print(io, _eco_summary(r))

"""A block this tool has no equivalent for, left out."""
_eco_skip!(r::EcoImportReport, type_, name, why::AbstractString) =
    push!(getfield(r, :skipped), JDict("type" => type_, "name" => name, "why" => String(why)))

"""A block imported whole and left out of the run, as the file says."""
_eco_disable!(r::EcoImportReport, name::AbstractString) = push!(getfield(r, :disabled), String(name))

"""A block inside a sub-system the file switches off as a whole."""
function _eco_in_disabled_system!(r::EcoImportReport, path::AbstractString)
    d = getfield(r, :disabled_systems)
    if d === nothing
        d = OrderedDict{String,Int}()
        setfield!(r, :disabled_systems, d)
    end
    d[path] = get(d, path, 0) + 1
end

"""Recorded but harmless: carries no mass, so the numbers are unaffected."""
_eco_note!(r::EcoImportReport, type_, name) = push!(getfield(r, :notes), JDict("type" => type_, "name" => name))

"""A warning, said once however often it is raised."""
function _eco_warn!(r::EcoImportReport, message::AbstractString)
    m = String(message)
    m in getfield(r, :said) && return
    push!(getfield(r, :said), m)
    push!(getfield(r, :warnings), m)
end

"""A name tidied into an identifier."""
_eco_rename!(r::EcoImportReport, from::AbstractString, to::AbstractString) =
    push!(getfield(r, :renamed), JDict("from" => String(from), "to" => String(to)))

"""Counts what came across, from the finished project."""
function _eco_finish!(r::EcoImportReport, project::JDict)
    n(k) = length(_eco_list(project, k))
    setfield!(r, :counts, OrderedDict{String,Int}(
        "index_lists" => n("index_lists"),
        "compartments" => n("compartments"),
        "transfers" => n("transfers"),
        "parameters" => n("parameters"),
        "expressions" => n("expressions"),
        "inflows" => n("inflows"),
        "lookups" => n("lookups"),
        "index_reductions" => n("index_reductions"),
        "block_reductions" => n("block_reductions"),
        "min_maxes" => n("min_maxes"),
        "running_means" => n("running_means"),
        "snapshots" => n("snapshots"),
        "delays" => n("delays"),
        "triggers" => n("triggers"),
        "nuclides" => n("nuclides"),
    ))
end

# A short account in words, one line per kind of thing to say.
function _eco_summary(r::EcoImportReport)
    c = getfield(r, :counts)
    cn(k) = get(c, k, 0)
    lines = String[
        "Imported $(cn("compartments")) compartment(s), $(cn("transfers")) transfer(s), " *
        "$(cn("parameters")) parameter(s), $(cn("expressions")) expression(s), " *
        (cn("lookups") != 0 ? "$(cn("lookups")) lookup table(s), " : "") *
        (cn("index_reductions") != 0 ? "$(cn("index_reductions")) index operation(s), " : "") *
        (cn("block_reductions") != 0 ? "$(cn("block_reductions")) aggregate(s), " : "") *
        "$(cn("index_lists")) index list(s), $(cn("nuclides")) nuclide(s).",
    ]
    skipped = getfield(r, :skipped)
    if !isempty(skipped)
        by_type = OrderedDict{Any,Int}()
        for s in skipped
            by_type[s["type"]] = get(by_type, s["type"], 0) + 1
        end
        push!(lines, "Skipped $(length(skipped)) block(s) this tool cannot represent: " *
                     join(("$n $(_eco_js_string(t))" for (t, n) in by_type), ", ") * ".")
    end
    notes = getfield(r, :notes)
    if !isempty(notes)
        by_type = OrderedDict{Any,Int}()
        for s in notes
            by_type[s["type"]] = get(by_type, s["type"], 0) + 1
        end
        push!(lines, "Ignored $(join(("$n $(_eco_js_string(t))" for (t, n) in by_type), ", ")): these carry " *
                     "no mass, so the results are unaffected.")
    end
    renamed = getfield(r, :renamed)
    isempty(renamed) || push!(lines, "Renamed $(length(renamed)) block(s) to valid identifiers.")
    disabled = getfield(r, :disabled)
    isempty(disabled) || push!(lines, "$(length(disabled)) block(s) are disabled, as they were in " *
                                      "Ecolego, and take no part in the run.")
    ds = getfield(r, :disabled_systems)
    if ds !== nothing && !isempty(ds)
        push!(lines, join(("Sub-system '$p' is switched off as a whole, as it was in Ecolego, " *
                           "with $n block$(n == 1 ? "" : "s") in it; " *
                           "they keep their own switches and come back with it." for (p, n) in ds), " "))
    end
    append!(lines, getfield(r, :warnings))
    return join(lines, "\n")
end

"""The report as plain data: every list, `ok` and the `summary`, in the
order and shape the Python package's `ImportReport.to_dict()` gives them."""
function to_dict(r::EcoImportReport)
    ds = getfield(r, :disabled_systems)
    return JDict(
        "skipped" => Any[JDict(s) for s in getfield(r, :skipped)],
        "notes" => Any[JDict(s) for s in getfield(r, :notes)],
        "renamed" => Any[JDict(s) for s in getfield(r, :renamed)],
        "disabled" => Any[getfield(r, :disabled)...],
        "disabled_systems" => ds === nothing ? nothing : JDict(k => v for (k, v) in ds),
        "warnings" => Any[getfield(r, :warnings)...],
        "counts" => JDict(k => v for (k, v) in getfield(r, :counts)),
        "ok" => r.ok,
        "summary" => _eco_summary(r),
    )
end

# --- what the file's block types become ---------------------------------------------------

"""Block types that become blocks in this tool."""
const _ECO_SUPPORTED = Set([
    "compartment", "expression", "parameter",
    # The file format treats these as expressions with an evaluation mode.
    "post-processing", "constant",
    # Time-dependent data.
    "lookup-table",
    # Reductions: over one of a block's index lists, and over several blocks.
    "index-operation", "aggregate",
    # The blocks that depend on what has already happened, and the events that drive them.
    "min-max", "running-mean", "snapshot", "delay", "discrete-event",
    # Connections.
    "transfer", "transfer-coefficient",
    # The parts of a transport sub-system.
    "transport-begin", "transport-end", "transport-number", "transport-element-counter", "transport-operation",
    # A block that stands in for another.
    "general-variable", "select",
])

"""Ecolego's general variable: a block that stands in for another, written as
the chosen block's id; it becomes an expression reading the chosen block.
`select` is its older name, with the pick and the list given by GUID."""
const _ECO_GENERAL_VARIABLE = Set(["general-variable", "select"])

"""The part each transport block type plays."""
const _ECO_TRANSPORT_ROLE = Dict(
    "transport-begin" => "begin",
    "transport-end" => "end",
    "transport-number" => "number",
    "transport-element-counter" => "counter",
    "transport-operation" => "operation",
)

"""Ecolego's model boundary, folded into the transfers that touch it."""
const _ECO_BOUNDARY = Set(["source", "sink"])

"""Connections that carry no mass and so do not change the numbers."""
const _ECO_NON_NUMERIC = Set(["influence"])

"""Ecolego's sub-system interface: read for its wiring, then dropped."""
const _ECO_INTERFACE = Set(["model-input", "model-output", "connector"])

"""How several outputs into one input are combined."""
const _ECO_INTERFACE_OPERATION = Dict("ADD" => "sum", "MAX" => "max", "MIN" => "min", "MEAN" => "mean",
                                      "PRODUCT" => "prod")

"""multiply-with-donor defaults: a plain transfer is an absolute flux, the
legacy transfer-coefficient a rate multiplied by its donor."""
const _ECO_DONOR_DEFAULT = Dict("transfer" => false, "transfer-coefficient" => true)

# --- small helpers -------------------------------------------------------------------------

# JavaScript's `value ?? fallback` (Python's `_or`): only a missing value falls back.
_eco_or(value, fallback) = value === nothing ? fallback : value

# Python's truthiness, for what the importer tests that way.
_eco_truthy(::Nothing) = false
_eco_truthy(x::Bool) = x
_eco_truthy(x::Number) = !iszero(x)
_eco_truthy(x::AbstractString) = !isempty(x)
_eco_truthy(x::AbstractVector) = !isempty(x)
_eco_truthy(x::AbstractDict) = !isempty(x)
_eco_truthy(x) = true

# `project.get(key) or []`.
function _eco_list(d::AbstractDict, key::AbstractString)
    v = get(d, key, nothing)
    return v isa AbstractVector ? v : Any[]
end

# `_PATH_SEPARATOR.split(name)[-1]`: the part after the last `/` or `\`.
function _eco_last_part(name::AbstractString)
    s = String(name)
    k = findlast(c -> c == '/' || c == '\\', s)
    return k === nothing ? s : s[nextind(s, k):end]
end

# `re.search('<tag[<JS space>>]', text)`: the tag's name followed by white space or `>`.
function _eco_has_tag(text::String, tag::String)
    cu = codeunits(text)
    n = length(cu)
    from = 1
    while true
        r = findnext(tag, text, from)
        r === nothing && return false
        after = first(r) + ncodeunits(tag)
        if after <= n && (cu[after] == UInt8('>') || _eco_js_space_bytes(cu, after, n) > 0)
            return true
        end
        from = first(r) + 1
    end
end

# `{system}.{name}` when the block has a sub-system, its name otherwise.
function _eco_qualified(block::AbstractDict)
    system = get(block, "system", nothing)
    name = get(block, "name", nothing)
    return _eco_truthy(system) ? "$(system).$(name)" : name
end

# `obj` without its empty strings, missing values and empty lists.
function _eco_trim_empty(pairs)
    out = JDict()
    for (k, v) in pairs
        (v === nothing || (v isa AbstractString && isempty(v)) || (v isa AbstractVector && isempty(v))) && continue
        out[k] = v
    end
    return out
end

# `a, b and c`.
function _eco_list_of(parts)
    length(parts) <= 1 && return join(parts)
    return "$(join(parts[1:end-1], ", ")) and $(parts[end])"
end

# --- the entry points ------------------------------------------------------------------------

_eco_looks_like_zip(data::AbstractVector{UInt8}) =
    length(data) >= 4 && data[1] == 0x50 && data[2] == 0x4b && data[3] in (0x03, 0x05, 0x07)

"""
    import_eco_file(path_or_bytes; file_name=nothing, version=nothing) -> (project, report)

Reads an Ecolego project (`.eco`), assessment (`.eas`) or bare `model.xml`:
the file's bytes, or a path to read them from. `file_name` is what bytes do
not know -- which file this is -- and goes into the model's name and
description; a path supplies its own. `version` is the Ecolego version, for
a bare XML file; an archive says which Ecolego wrote it in its `.version`
file, and that is used instead.

Returns `(project, report)` -- `ImportResult` in the Python package: the
project (a `JDict`, in the order and shape the Python package's
`import_eco_file` gives it; a distribution's list of values is a
`Vector{Float64}`) and an [`EcoImportReport`](@ref). Throws
[`EcoImportError`](@ref) for a file it cannot read, and `ArgumentError("Invalid
time value")` for a modification date past what a JavaScript `Date` holds
(Python's `ValueError`).
"""
function import_eco_file(path::AbstractString; file_name=nothing, version=nothing)
    file_name === nothing && (file_name = basename(String(path)))
    return import_eco_file(read(String(path)); file_name=file_name, version=version)
end

function import_eco_file(data::AbstractVector{UInt8}; file_name=nothing, version=nothing)
    raw = data isa Vector{UInt8} ? data : Vector{UInt8}(data)

    # Ecolego 4/5 wrote the model as a bare XML file, usually UTF-16 with a
    # BOM; Ecolego 6 zips the project folder. Both carry the .eco extension.
    if !_eco_looks_like_zip(raw)
        text = decode_eco_xml_bytes(raw)
        if _eco_has_tag(text, "<sheet")
            throw(EcoImportError(
                "This is an Ecolego 4/5 model: a <sheet> document with a different data " *
                "model from Ecolego 6 (compartments live in spreadsheet cells rather " *
                "than a block model). This importer reads the Ecolego 6 format. Open " *
                "the file in Ecolego and save it again to convert it."))
        end
        if !_eco_has_tag(text, "<data-model")
            throw(EcoImportError(
                "This file is neither a ZIP archive nor an Ecolego model XML. " *
                "If it is a project folder, zip it or open its model.xml directly."))
        end
        return import_model_xml(text; file_name=file_name, version=version)
    end

    entries = _eco_unzip(raw)

    # model.xml sits at the archive root in practice, but it is looked for by
    # name anywhere -- and these archives are written on Windows, so a name
    # may use backslashes. By name first, and the bytes only of the one
    # wanted: an assessment's results are never decompressed.
    model_xml = nothing
    for name in _eco_names(entries)
        if _eco_last_part(name) == "model.xml"
            model_xml = decode_eco_xml_bytes(_eco_get(entries, name))
            break
        end
    end
    if model_xml === nothing
        for name in _eco_names(entries)
            endswith(_eco_py_lower(name), ".xml") || continue
            text = decode_eco_xml_bytes(_eco_get(entries, name))
            if _eco_has_tag(text, "<data-model")
                model_xml = text
                break
            end
        end
    end
    if model_xml === nothing
        held = join(_eco_names(entries), ", ")
        isempty(held) && (held = "nothing")
        throw(EcoImportError(
            "No model.xml in the archive (it holds: $held). " *
            "This may be a library or workspace archive rather than a project."))
    end
    return import_model_xml(model_xml; file_name=file_name, version=_eco_ecolego_version(entries))
end

# Which Ecolego wrote the archive: `.version` at its root is a properties
# file, `version=6.5 track-changes=false ...`.
function _eco_ecolego_version(entries::_EcoArchive)
    for name in _eco_names(entries)
        _eco_last_part(name) == ".version" || continue
        text = try
            decode_eco_xml_bytes(_eco_get(entries, name))
        catch e
            e isa EcoImportError || rethrow()
            return nothing
        end
        return _eco_version_in(text)
    end
    return nothing
end

# `re.search('(^|[S])version[S]*=[S]*([A-Za-z0-9_.-]+)', text).group(2)`.
function _eco_version_in(text::String)
    cu = codeunits(text)
    n = length(cu)
    from = 1
    while true
        r = findnext("version", text, from)
        r === nothing && return nothing
        k = first(r)
        from = k + 1
        if k > 1
            p = prevind(text, k)
            _eco_js_space_bytes(cu, p, n) == k - p || continue
        end
        i = k + 7
        while i <= n
            sp = _eco_js_space_bytes(cu, i, n)
            sp == 0 && break
            i += sp
        end
        (i <= n && cu[i] == UInt8('=')) || continue
        i += 1
        while i <= n
            sp = _eco_js_space_bytes(cu, i, n)
            sp == 0 && break
            i += sp
        end
        j = i
        while j <= n && (_eco_is_ident_char(cu[j]) || cu[j] == UInt8('.') || cu[j] == UInt8('-'))
            j += 1
        end
        j > i && return String(view(cu, i:j-1))
    end
end

"""
    import_model_xml(text; file_name=nothing, version=nothing) -> (project, report)

Reads a bare `model.xml`. `file_name` and `version` are what the file around
the XML knows and the XML does not: which file this is and which Ecolego
wrote it. Both go into the description, and the file's name is the model's
when the XML calls it by Ecolego's default, `model`.

Returns `(project, report)`, as [`import_eco_file`](@ref) does. Throws
[`EcoImportError`](@ref) for XML that does not parse, a document with no
`<data-model>`, or a nuclide, material or index called `__proto__`,
`constructor` or `prototype`.
"""
function import_model_xml(text::AbstractString; file_name=nothing, version=nothing)
    src = String(text)
    isvalid(src) || (src = _eco_utf8_replace(Vector{UInt8}(codeunits(src))))
    meta = (fileName=file_name, version=version)
    root = try
        parse_eco_xml(src)
    catch e
        e isa EcoXMLError || rethrow()
        throw(EcoImportError("model.xml is not valid XML: $(_eco_message(e))"))
    end

    data_model = root.name == "data-model" ? root : _eco_find(root, "data-model")
    data_model === nothing && throw(EcoImportError("The XML has no <data-model> element"))

    report = EcoImportReport()
    names = _EcoNameMapper(report)

    project = JDict(
        "name" => "Imported project",
        "description" => "",
        "simulation" => JDict(),
        "index_lists" => Any[],
        "parameters" => Any[],
        "compartments" => Any[],
        "expressions" => Any[],
        "transfers" => Any[],
        "inflows" => Any[],
        "lookups" => Any[],
        "index_reductions" => Any[],
        "block_reductions" => Any[],
        "min_maxes" => Any[],
        "running_means" => Any[],
        "snapshots" => Any[],
        "delays" => Any[],
        "triggers" => Any[],
        "functions" => Any[],
    )

    provenance = _eco_read_project_properties(data_model, project, meta)
    _eco_read_functions(data_model, project, names, report)
    materials = _eco_read_materials(data_model, project, report)
    index_ids = _eco_read_index_lists(data_model, project, names, report, materials)
    _eco_read_decay_chains(data_model, project, report)
    hierarchy = _eco_read_hierarchy(data_model, project, names, report)
    block_name_by_id, wiring, twins, generals = _eco_read_blocks(data_model, project, names, index_ids, report,
                                                                 hierarchy)
    _eco_read_simulation_settings(data_model, project, report)

    # Two rewrites, both textual and both necessary: Ecolego names may hold
    # spaces and punctuation this tool's identifiers cannot, so those blocks
    # were renamed above; and equations may use sub-system-qualified
    # references, which are the block ids.
    _eco_rewrite_renamed_references!(project, names, report, block_name_by_id)
    _eco_drop_unreachable_targets!(project, report)

    # What Ecolego's sub-system inputs and outputs connected, connected
    # directly. Last, so the references it writes are the names the model
    # ended up with.
    _eco_connect_interfaces!(project, wiring, block_name_by_id, report)
    # After the two above, so what a general variable reads is the name the
    # model ended up with.
    _eco_settle_general_variables!(project, generals, block_name_by_id, report)
    _eco_rewrite_endpoint_ids!(project, block_name_by_id, report, twins)

    duplicated = _eco_duplicated(names)
    if !isempty(duplicated)
        more = length(duplicated) > 6 ? "…" : ""
        _eco_warn!(report,
            "$(length(duplicated)) name(s) had to be spelled differently in different " *
            "sub-systems ($(join(first(duplicated, 6), ", "))$more), because the original is not a valid " *
            "identifier and the tidied form was already taken. A bare reference to one " *
            "of those was left as written -- check those equations.")
    end

    _eco_finish!(report, project)
    # Last, so the counts are of the model as it ended up rather than as the
    # file spelled it.
    facts = (author=provenance.author, comment=provenance.comment, modified=provenance.modified,
             fileName=meta.fileName, version=meta.version)
    project["description"] = _eco_describe_model(project, facts)
    # Who wrote it, as the file says -- beside the name and the description,
    # where a model of this tool's own keeps it.
    if _eco_truthy(provenance.author)
        head = JDict("name" => project["name"], "description" => project["description"],
                     "author" => provenance.author)
        for (k, v) in project
            haskey(head, k) || (head[k] = v)
        end
        project = head
    end
    _eco_json_ready!(project)
    return (project=project, report=report)
end

# --- sub-system interfaces ------------------------------------------------------------------

# Wires up what a sub-system interface connected, and drops the interface.
# `connectInterfaces` in src/io/eco.js.
function _eco_connect_interfaces!(project::JDict, wiring, block_name_by_id, report::EcoImportReport)
    links = wiring.links
    operations = wiring.operations
    id_by_guid = wiring.id_by_guid
    exposed = wiring.exposed
    if isempty(links)
        if !isempty(exposed)
            one = length(exposed) == 1
            _eco_warn!(report,
                "$(length(exposed)) sub-system input/output$(one ? " was" : "s were") declared " *
                "but connected to nothing, so nothing was routed: the " *
                "$(one ? "block behind it keeps the value" : "blocks behind them keep the values") " *
                "the file gives $(one ? "it" : "them").")
        end
        return
    end

    by_name = Dict{Any,NamedTuple}()
    holders = (("parameters", "parameter"), ("compartments", "compartment"),
               ("expressions", "expression"), ("transfers", "transfer"),
               ("inflows", "inflow"), ("lookups", "lookup"),
               ("index_reductions", "index_reduction"), ("block_reductions", "block_reduction"),
               ("min_maxes", "min_max"), ("running_means", "running_mean"),
               ("snapshots", "snapshot"), ("delays", "delay"),
               ("triggers", "trigger"))
    for (collection, kind) in holders
        for block in _eco_list(project, collection)
            qname = _eco_qualified(block)
            by_name[qname] = (collection=collection, kind=kind, block=block, qname=qname)
        end
    end

    function found(guid)
        bid = get(id_by_guid, guid, nothing)
        qname = bid === nothing ? nothing : get(block_name_by_id, bid, nothing)
        return qname === nothing ? nothing : get(by_name, qname, nothing)
    end

    by_target = OrderedDict{String,Vector{Any}}()
    for link in links
        push!(get!(by_target, link.target, Any[]), link)
    end

    joined = 0
    lost = String[]
    converted = String[]
    for (target_guid, incoming) in by_target
        target = found(target_guid)
        if target === nothing
            push!(lost, incoming[1].via)
            continue
        end
        sources = [s for s in (found(l.source) for l in incoming) if s !== nothing]
        length(sources) != length(incoming) && push!(lost, incoming[1].via)
        isempty(sources) && continue

        refs = [s.qname for s in sources]
        op = get(operations, target_guid, nothing)
        fn = get(_ECO_INTERFACE_OPERATION, op === nothing ? "ADD" : op, nothing)
        fn = fn === nothing ? "sum" : fn
        equation = length(refs) == 1 ? refs[1] : "$fn($(join(refs, ", ")))"

        rewritten = _eco_wire_into!(project, target, equation)
        if rewritten === nothing
            _eco_warn!(report,
                "'$(target.qname)' is fed by a sub-system interface, and a " *
                "$(replace(_eco_js_string(target.kind), '_' => ' ')) cannot be: its value was " *
                "left as the file gives it.")
            continue
        end
        rewritten == "converted" && push!(converted, target.qname)
        joined += 1
    end

    if joined != 0
        tail = ""
        if !isempty(converted)
            others = length(converted) > 4 ? " and others" : ""
            tail = " $(join(first(converted, 4), ", "))$others " *
                   "$(length(converted) == 1 ? "was a parameter and is" : "were parameters and are") " *
                   "now expressions, since what feeds $(length(converted) == 1 ? "it" : "them") " *
                   "is not a number."
        end
        _eco_warn!(report,
            "$joined sub-system input$(joined == 1 ? "" : "s") $(joined == 1 ? "was" : "were") " *
            "connected straight to what feeds $(joined == 1 ? "it" : "them"). Ecolego routes " *
            "those through model input and output blocks, which are a way to wire a " *
            "ready-made sub-system into a project; this tool has no such library, so the " *
            "two ends are joined directly and the interface blocks are left out." * tail)
    end
    if !isempty(lost)
        shown = join(first(unique(lost), 4), ", ")
        _eco_warn!(report,
            "$(length(lost)) sub-system connection$(length(lost) == 1 ? "" : "s") " *
            "($shown) named a block this tool did " *
            "not import, so $(length(lost) == 1 ? "it" : "they") could not be joined up.")
    end
end

# Puts one equation where a block's own value was: "rewritten", "converted"
# for a parameter that became an expression, or `nothing` for a kind that
# cannot be fed at all.
function _eco_wire_into!(project::JDict, target, equation::String)
    block = target.block
    kind = target.kind

    function clear(key)
        kept = Any[]
        for e in _eco_list(block, "entries")
            rest = JDict(k => v for (k, v) in e if k != key)
            any(k -> k != "index", keys(rest)) && push!(kept, rest)
        end
        block["entries"] = kept
        isempty(kept) && delete!(block, "entries")
    end

    if kind == "expression"
        block["equation"] = equation
        clear("equation")
        return "rewritten"
    end
    if kind == "transfer"
        block["rate"] = equation
        clear("rate")
        return "rewritten"
    end
    if kind == "parameter"
        params = project["parameters"]
        at = findfirst(b -> b === block, params)
        at === nothing || deleteat!(params, at)
        delete!(block, "value")
        clear("value")
        delete!(block, "entries")
        block["equation"] = equation
        push!(get!(project, "expressions", Any[]), block)
        return "converted"
    end
    return nothing
end

# --- the textual rewrite ----------------------------------------------------------------------

_eco_has_ident_char(s::AbstractString) = any(_eco_is_ident_char, codeunits(s))
_eco_has_operator_char(s::AbstractString) = any(b -> b in codeunits("+-*/^()[],"), codeunits(s))

# The runs of `[A-Za-z0-9_]` (or, with `dots`, of `[A-Za-z0-9_.]`) in a text.
function _eco_runs(s::AbstractString; dots::Bool=false)
    out = String[]
    cu = codeunits(s)
    n = length(cu)
    i = 1
    @inbounds while i <= n
        b = cu[i]
        if _eco_is_ident_char(b) || (dots && b == 0x2e)
            j = i + 1
            while j <= n && (_eco_is_ident_char(cu[j]) || (dots && cu[j] == 0x2e))
                j += 1
            end
            push!(out, String(view(cu, i:j-1)))
            i = j
        else
            i += 1
        end
    end
    return out
end

# Which of the rewrite's pairs can change a given text, found without
# searching the text for every one of them (`_Candidates` in the Python
# package): a match needs a non-name character or an end on either side, so
# every run of `[A-Za-z0-9_]` in the name is a whole run of the text where it
# matches; a substitution can make a match that was not there only for a
# pair whose name has the text put in as one of its runs, and those few are
# always tried.
struct _EcoCandidates
    runs::Vector{Set{String}}
    index::Dict{String,Vector{Int}}
    always::Set{Int}
end

function _EcoCandidates(pairs::Vector{Tuple{String,String}})
    runs = [Set(_eco_runs(frm)) for (frm, _) in pairs]
    index = Dict{String,Vector{Int}}()
    for (j, rs) in enumerate(runs)
        # the longest is the rarest
        key = first(sort!(collect(rs); by=r -> (-length(r), r)))
        push!(get!(index, key, Int[]), j)
    end
    always = Set{Int}()
    put_in = Set{String}()
    for (j, (frm, to)) in enumerate(pairs)
        any(r -> r in put_in, _eco_runs(frm; dots=true)) && push!(always, j)
        push!(put_in, to)
    end
    return _EcoCandidates(runs, index, always)
end

function _eco_candidates_of(c::_EcoCandidates, text::AbstractString)
    runs = Set(_eco_runs(text))
    found = copy(c.always)
    for run in runs
        js = get(c.index, run, nothing)
        js === nothing && continue
        for j in js
            issubset(c.runs[j], runs) && push!(found, j)
        end
    end
    return sort!(collect(found))
end

# `out[:i] + to + out[end:]`, by bytes.
function _eco_splice(out::String, i::Int, stop::Int, to::String)
    cu = codeunits(out)
    buf = Vector{UInt8}(undef, (i - 1) + ncodeunits(to) + (length(cu) - stop + 1))
    copyto!(buf, 1, cu, 1, i - 1)
    copyto!(buf, i, codeunits(to), 1, ncodeunits(to))
    copyto!(buf, i + ncodeunits(to), cu, stop, length(cu) - stop + 1)
    return String(buf)
end

# Substitutes renamed blocks throughout every equation. Textual rather than
# token-based, because the original names are exactly the ones the tokenizer
# cannot handle -- `Deep soil` is three tokens. Qualified ids first and
# longest names first, and a match only counts when it is not butted up
# against another name character (`.` included). `rewriteRenamedReferences`.
function _eco_rewrite_renamed_references!(project::JDict, names, report::EcoImportReport, block_name_by_id)
    qualified = Tuple{String,String}[(bid, to) for (bid, to) in block_name_by_id if bid != to]
    ambiguous = Set(_eco_duplicated(names))
    bare = Tuple{String,String}[(frm, to) for (frm, to) in names.by_original if frm != to && !(frm in ambiguous)]

    seen = Set{Tuple{String,String}}()
    pairs = Tuple{String,String}[]
    for (frm, to) in Iterators.flatten((qualified, bare))
        # An empty `from` is found at every position, and one with no name
        # character in it is not a name anything could have referred to.
        (frm == "" || frm == to || !_eco_has_ident_char(frm)) && continue
        (frm, to) in seen && continue
        push!(seen, (frm, to))
        push!(pairs, (frm, to))
    end
    sort!(pairs; by=p -> -_eco_js_len(p[1]), alg=MergeSort)
    isempty(pairs) && return

    touched = 0
    fired = OrderedDict{String,String}()
    candidates = _EcoCandidates(pairs)

    function rewrite(text)
        text isa AbstractVector && return Any[rewrite(t) for t in text]
        (text isa AbstractString && !isempty(text)) || return text
        original = String(text)
        out = original
        for j in _eco_candidates_of(candidates, original)
            frm, to = pairs[j]
            at = 1
            while true
                r = at > ncodeunits(out) ? nothing : findnext(frm, out, at)
                r === nothing && break
                i = first(r)
                stop = i + ncodeunits(frm)                      # the byte after the match
                cu = codeunits(out)
                before_ok = i == 1 || !_eco_is_name_part(cu[i-1])
                after_ok = stop > length(cu) || !_eco_is_name_part(cu[stop])
                if before_ok && after_ok
                    out = _eco_splice(out, i, stop, to)
                    at = i + ncodeunits(to)
                    fired[frm] = to
                else
                    at = stop
                end
            end
        end
        out != original && (touched += 1)
        return out
    end

    collections = (
        ("compartments", ("initial",)),
        ("transfers", ("rate",)),
        ("inflows", ("rate",)),
        ("expressions", ("equation",)),
        # A function's body is an equation, and a call of one is a reference.
        ("functions", ("equation",)),
        # A reducing block names its targets rather than writing an equation,
        # but they are references like any other.
        ("index_reductions", ("target",)),
        ("block_reductions", ("targets",)),
        # A block that remembers names its target, and its event fields name
        # a discrete event.
        ("min_maxes", ("target", "reset_trigger", "start_trigger", "stop_trigger")),
        ("running_means", ("target", "reset_trigger", "start_trigger", "stop_trigger")),
        ("snapshots", ("target", "trigger", "initial")),
        ("delays", ("target", "delay")),
        ("triggers", ("first", "second")),
    )
    for (collection, ks) in collections
        for block in _eco_list(project, collection)
            for k in ks
                haskey(block, k) && (block[k] = rewrite(block[k]))
            end
            for entry in _eco_list(block, "entries")
                for k in ks
                    haskey(entry, k) && (entry[k] = rewrite(entry[k]))
                end
            end
        end
    end

    if touched != 0
        _eco_warn!(report,
            "Rewrote $touched equation(s) to use this tool's block names, including " *
            "sub-system-qualified references. The substitution is textual, because the " *
            "original names are not valid identifiers -- check the results.")
        # A name with an operator in it is also an expression: `A-B` turned
        # every `A - B` in the model into a reference to `A_B`.
        risky = [(frm, to) for (frm, to) in fired if _eco_has_operator_char(frm)]
        if !isempty(risky)
            shown = join(("'$frm' → '$to'" for (frm, to) in first(risky, 6)), ", ")
            _eco_warn!(report,
                "$(length(risky)) of those names contain$(length(risky) == 1 ? "s" : "") " *
                "operator or bracket characters " *
                "($shown$(length(risky) > 6 ? ", …" : "")). Every occurrence of the text " *
                "in an equation was read as the block -- including where it was written " *
                "as arithmetic between two other blocks. Check those equations by hand.")
        end
    end
end

# Drops a reduction whose target was never imported, and lists it in the
# report; an aggregate that lost only some of its targets keeps the rest,
# with a warning. `dropUnreachableTargets`.
function _eco_drop_unreachable_targets!(project::JDict, report::EcoImportReport)
    known = Set{Any}()
    for kind in ("parameters", "compartments", "expressions", "transfers",
                 "inflows", "lookups", "index_reductions", "block_reductions", "functions",
                 "min_maxes", "running_means", "snapshots", "delays", "triggers")
        for b in _eco_list(project, kind)
            push!(known, _eco_qualified(b))
        end
    end

    resolve(ref, system) = resolve_reference(ref, system === nothing ? "" : system, q -> q in known)

    kept_reductions = Any[]
    for o in _eco_list(project, "index_reductions")
        target = get(o, "target", nothing)
        if _eco_truthy(target) && resolve(target, _eco_or_empty(get(o, "system", nothing))) !== nothing
            push!(kept_reductions, o)
            continue
        end
        _eco_skip!(report, "index-operation", get(o, "name", nothing),
                   "it reduces '$(target === nothing ? "(nothing)" : _eco_js_string(target))', " *
                   "which is not in this model")
        delete!(known, _eco_qualified(o))
    end
    project["index_reductions"] = kept_reductions

    kept_aggregates = Any[]
    for g in _eco_list(project, "block_reductions")
        targets = _eco_list(g, "targets")
        system = _eco_or_empty(get(g, "system", nothing))
        kept = Any[t for t in targets if resolve(t, system) !== nothing]
        if length(kept) == length(targets)
            push!(kept_aggregates, g)
            continue
        end
        lost = [t for t in targets if resolve(t, system) === nothing]
        if isempty(kept)
            _eco_skip!(report, "aggregate", get(g, "name", nothing),
                       "none of the blocks it reduces ($(join(lost, ", "))) is in this model")
            delete!(known, _eco_qualified(g))
            continue
        end
        g["targets"] = kept
        more = length(lost) > 4 ? "…" : ""
        _eco_warn!(report,
            "'$(get(g, "name", nothing))' reduces $(length(lost)) block(s) this tool did not import " *
            "($(join(first(lost, 4), ", "))$more); " *
            "they were left out of the total.")
        push!(kept_aggregates, g)
    end
    project["block_reductions"] = kept_aggregates
end

# `system or ''`.
_eco_or_empty(s) = _eco_truthy(s) ? s : ""

# A reference and nothing else: a name, or a path of names.
function _eco_is_reference(text::AbstractString)
    cu = codeunits(text)
    n = length(cu)
    n == 0 && return false
    i = 1
    while true
        (i <= n && (_eco_is_alpha(cu[i]) || cu[i] == UInt8('_'))) || return false
        i += 1
        while i <= n && _eco_is_ident_char(cu[i])
            i += 1
        end
        i > n && return true
        cu[i] == UInt8('.') || return false
        i += 1
    end
end

# Settles each general variable on the block it reads, and says what became
# of them: Ecolego shows the chosen block's unit as the general variable's,
# and the copy the file carries stood in until now. `settleGeneralVariables`.
function _eco_settle_general_variables!(project::JDict, generals, block_name_by_id, report::EcoImportReport)
    isempty(generals) && return
    blocks = Dict{Any,Any}()
    for kind in ("parameters", "compartments", "expressions", "transfers",
                 "inflows", "lookups", "index_reductions", "block_reductions",
                 "min_maxes", "running_means", "snapshots", "delays", "triggers")
        for b in _eco_list(project, kind)
            blocks[_eco_qualified(b)] = b
        end
    end

    resolve(equation, system) =
        resolve_reference(_eco_js_trim(_eco_js_string(_eco_or(equation, ""))), system, q -> haskey(blocks, q))

    read = String[]
    unchosen = String[]
    passed_over = false
    for g in generals
        block = g.block
        qname = _eco_qualified(block)
        own = length(_eco_list(block, "entries"))
        if !g.picked && own == 0
            push!(unchosen, "'$qname'")
            continue
        end
        system = _eco_or_empty(get(block, "system", nothing))
        text = _eco_js_trim(_eco_js_string(_eco_or(get(block, "equation", nothing), "")))
        target = resolve(text, system)
        unit = target !== nothing ? get(blocks[target], "unit", nothing) : nothing
        (unit isa AbstractString && unit != "") && (block["unit"] = unit)

        line = "'$qname' reads '$(target === nothing ? text : target)'"
        (target === nothing && _eco_is_reference(text)) && (line *= ", which is not in this model")
        own != 0 && (line *= " (and makes its own choice at $own $(own == 1 ? "index" : "indices"))")
        chosen = Set{Any}([target])
        for e in _eco_list(block, "entries")
            push!(chosen, resolve(get(e, "equation", nothing), system))
        end
        others = [n for n in (get(block_name_by_id, i, i) for i in g.offered) if !(n in chosen)]
        if !isempty(others)
            shown = ["'$n'" for n in first(others, 3)]
            length(others) > 3 && push!(shown, "$(length(others) - 3) more")
            line *= ", chosen over $(_eco_list_of(shown))"
            passed_over = true
        end
        push!(read, line)
    end
    if !isempty(read)
        one = length(read) == 1
        more = length(read) > 6 ? "; and $(length(read) - 6) more" : ""
        _eco_warn!(report,
            "$(length(read)) general variable$(one ? "" : "s"), $(one ? "a block" : "blocks") that " *
            "stand$(one ? "s" : "") in for one of a list of others, arrived as " *
            "$(one ? "an expression" : "expressions") reading the one chosen, which is what Ecolego " *
            "works out for $(one ? "it" : "them"): $(join(first(read, 6), "; "))$more. " *
            (passed_over ? "The blocks passed over are in the model as they were; to choose one, write its " *
                           "name in the equation." :
                           "To choose another block, write its name in the equation."))
    end
    if !isempty(unchosen)
        one = length(unchosen) == 1
        shown = first(unchosen, 4)
        length(unchosen) > 4 && push!(shown, "$(length(unchosen) - 4) more")
        _eco_warn!(report,
            "$(_eco_list_of(shown)) $(one ? "is a general variable" : "are general variables") with no block " *
            "chosen, which Ecolego will not run; here $(one ? "it reads" : "they read") 0.")
    end
end

# --- names ------------------------------------------------------------------------------------

# Maps Ecolego's names onto identifiers, and remembers the mapping so the
# equations can follow it. Unique per sub-system, as Ecolego's own names are;
# keyed by block id rather than by name. `NameMapper` in src/io/eco.js.
mutable struct _EcoNameMapper
    report::EcoImportReport
    by_key::Dict{Any,String}
    by_original::OrderedDict{String,String}
    used::Dict{String,Set{String}}
    ambiguous::OrderedDict{String,Nothing}
end
_EcoNameMapper(report::EcoImportReport) = _EcoNameMapper(report, Dict{Any,String}(), OrderedDict{String,String}(),
                                                         Dict{String,Set{String}}(), OrderedDict{String,Nothing}())

# One name as an identifier this tool can parse. `key` identifies the thing
# named (the name itself when `nothing`); `fallback` is what to call it when
# the name is missing or blank. A reserved word is taken before the file says
# anything, so `min` is numbered like a clash: `min_1`.
function _eco_map!(m::_EcoNameMapper, original, key=nothing, system::AbstractString="", fallback="block")
    key === nothing && (key = original)
    hit = get(m.by_key, key, nothing)
    hit === nothing || return hit

    given = _eco_js_trim(original === nothing ? "" : string(original))
    absent = given == ""
    clean = _eco_js_identifier(absent ? (fallback === nothing ? "" : string(fallback)) : given)
    (!isempty(clean) && _eco_is_ascii_digit(clean[1])) && (clean = "_" * clean)
    clean == "" && (clean = "block")

    taken = get!(m.used, String(system), Set{String}())
    candidate = clean
    n = 1
    while candidate in taken || candidate in RESERVED
        candidate = "$(clean)_$n"
        n += 1
    end

    # A bare reference is rewritten by name, so a name that maps two ways
    # cannot be rewritten safely. A block with no name has nothing an
    # equation could have referred to it by.
    if !absent
        seen = get(m.by_original, given, nothing)
        if seen === nothing
            m.by_original[given] = candidate
        elseif seen != candidate
            m.ambiguous[given] = nothing
        end
    end

    push!(taken, candidate)
    m.by_key[key] = candidate
    candidate != given && _eco_rename!(m.report, absent ? "(unnamed)" : given, candidate)
    return candidate
end

# A name for a block the file does not have -- a second transfer this import
# makes of one -- free in its sub-system, and taken there. Not a rename.
function _eco_claim!(m::_EcoNameMapper, base::AbstractString, system::AbstractString="")
    taken = get!(m.used, String(system), Set{String}())
    candidate = String(base)
    n = 1
    while candidate in taken || candidate in RESERVED
        candidate = "$(base)_$n"
        n += 1
    end
    push!(taken, candidate)
    return candidate
end

"""Original names that mapped to more than one identifier."""
_eco_duplicated(m::_EcoNameMapper) = collect(keys(m.ambiguous))

# The three words that pass every other test without being names: in the
# application each is a key into every object's prototype.
const _ECO_PROTOTYPE_KEYS = Set(["__proto__", "constructor", "prototype"])

# A nuclide's, material's, index's or decay pair's name, as the file gives
# it, trimmed; `nothing` (and a warning) for a blank one. A prototype key is
# refused outright.
function _eco_key_name(raw, what::AbstractString, report::EcoImportReport)
    name = _eco_js_trim(raw === nothing ? "" : string(raw))
    an = (!isempty(what) && what[1] in "aeiouAEIOU") ? "An" : "A"
    if name == ""
        _eco_warn!(report, "$an $what with no name was left out.")
        return nothing
    end
    if name in _ECO_PROTOTYPE_KEYS
        throw(EcoImportError(
            "$an $what in this file is called '$name', which is not a name but a key " *
            "into every object's prototype; this tool keys its tables by these names " *
            "and cannot hold one. Ecolego never writes it -- rename the $what in " *
            "Ecolego, or check that the file has not been tampered with."))
    end
    return name
end

# --- sections -------------------------------------------------------------------------------

# <hierarchy-model>: every sub-system, parents before children. A sub-system
# is a namespace and gives its blocks a path; a group is only a visual
# grouping and is flattened away; a transport is marked; one the file
# switches off is carried as switched off. `readHierarchy`.
function _eco_read_hierarchy(data_model::EcoXMLNode, project::JDict, names::_EcoNameMapper,
                             report::EcoImportReport)
    model = _eco_child(data_model, "hierarchy-model")
    path_by_id = Dict{String,String}()
    systems = String[]
    disabled_paths = String[]
    transports = String[]
    out = (path_by_id=path_by_id, systems=systems, disabled_paths=disabled_paths, transports=transports)
    model === nothing && return out

    groups = 0
    for el in _eco_children(model, "sub-system-block")
        sid = _eco_child_text(el, "id")
        original = _eco_attr(el, "name")
        # The root carries neither, and is not a level of anything.
        (_eco_truthy(sid) && _eco_truthy(original)) || continue

        parent_id = _eco_child_text(el, "sub-system")
        parent_path = _eco_truthy(parent_id) ? get(path_by_id, parent_id, "") : ""
        kind = _eco_attr(el, "type", "")

        if kind == "group"
            groups += 1
            path_by_id[sid] = parent_path
            continue
        end
        if kind == "external"
            _eco_warn!(report,
                "Sub-system '$original' is an external sub-system; this tool reads it " *
                "as an ordinary one, so its linked library is not applied.")
        end

        local_ = _eco_map!(names, original, "subsystem:$sid", parent_path, "subsystem")
        path = isempty(parent_path) ? local_ : "$parent_path.$local_"
        path_by_id[sid] = path
        push!(systems, path)
        kind == "transport" && push!(transports, path)
        _eco_child_bool(el, "enabled", true) || push!(disabled_paths, path)
    end

    if groups != 0
        _eco_warn!(report,
            "$groups group$(groups == 1 ? " was" : "s were") flattened: a group is a " *
            "visual grouping in Ecolego and does not scope names, so its blocks belong " *
            "to the sub-system around it.")
    end
    isempty(systems) || (project["systems"] = Any[systems...])
    isempty(transports) || (project["transports"] = Any[transports...])
    isempty(disabled_paths) || (project["disabled_systems"] = Any[disabled_paths...])
    return out
end

# <project-properties>: the model's name, and who wrote it, when. Every real
# file calls itself `model`, Ecolego's default, so the file's own name is
# used instead when there is one. Returns `(author, comment, modified)`, the
# last as milliseconds since 1970.
function _eco_read_project_properties(data_model::EcoXMLNode, project::JDict, meta)
    props = _eco_child(data_model, "project-properties")
    from_file = _eco_base_name(meta.fileName)
    if props === nothing
        project["name"] = from_file !== nothing ? from_file : "Imported project"
        return (author=nothing, comment=nothing, modified=nothing)
    end
    declared = _eco_attr(props, "name")
    declared === nothing && (declared = _eco_child_text(props, "name"))
    declared === nothing && (declared = _eco_child_text(props, "full-name"))
    chosen = (!_eco_truthy(declared) || declared == "model") ? from_file : nothing
    chosen === nothing && (chosen = declared !== nothing ? declared : "Imported project")
    project["name"] = chosen
    stamp = _eco_to_number(_eco_child_text(props, "modification-date"))
    author = _eco_property_text(props, "author")
    comment = _eco_property_text(props, "comment")
    _eco_truthy(comment) || (comment = _eco_child_text(props, "comment"))
    return (author=_eco_truthy(author) ? author : nothing,
            comment=_eco_truthy(comment) ? comment : nothing,
            modified=(isfinite(stamp) && stamp > 0) ? stamp : nothing)
end

# `…/model C.eco` -> `model C`.
function _eco_base_name(path)
    _eco_truthy(path) || return nothing
    last = _eco_last_part(string(path))
    cu = codeunits(last)
    n = length(cu)
    for ext in ("eco", "eas", "xml")
        if n >= 4 && cu[n-3] == UInt8('.') && _eco_ascii_ieq(String(view(cu, n-2:n)), ext)
            last = String(view(cu, 1:n-4))
            break
        end
    end
    t = _eco_js_trim(last)
    return isempty(t) ? nothing : t
end

# `Created at[S]+(JS_DOT+)` as a full match, ASCII case ignored: the date.
function _eco_created_at(text::String)
    cu = codeunits(text)
    n = length(cu)
    n >= 10 && _eco_ascii_ieq(String(view(cu, 1:10)), "Created at") || return nothing
    i = 11
    spaces = 0
    while i <= n
        sp = _eco_js_space_bytes(cu, i, n)
        sp == 0 && break
        i += sp
        spaces += 1
    end
    (spaces == 0 || i > n) && return nothing
    rest = String(view(cu, i:n))
    any(c -> c in ('\n', '\r', ' ', ' '), rest) && return nothing
    return rest
end

# What the model is, in up to five lines, for its description: where it came
# from, what is in it, what it is indexed by and what a run of it does; the
# author's own comment leads when there is one. `describeModel`.
function _eco_describe_model(project::JDict, facts)
    author = facts.author
    comment = facts.comment
    modified = facts.modified
    file_name = facts.fileName
    version = facts.version

    lines = String[]
    created = _eco_created_at(_eco_js_trim(comment === nothing ? "" : string(comment)))
    (_eco_truthy(comment) && created === nothing) && push!(lines, _eco_js_trim(comment))

    # Where it came from.
    parts = String[]
    file = _eco_last_part(file_name === nothing ? "" : string(file_name))
    push!(parts, isempty(file) ? "Imported from Ecolego" : "Imported from $file")
    _eco_truthy(version) && push!(parts, "written by Ecolego $version")
    _eco_truthy(author) && push!(parts, "by $author")
    if created !== nothing
        push!(parts, "created $(_eco_js_trim(created))")
    elseif modified !== nothing
        push!(parts, "last changed $(_eco_iso_date(modified))")
    end
    push!(lines, "$(join(parts, ", ")).")

    # What is in it, in the order the panels list the kinds.
    counts = String[]
    for collection in COLLECTIONS
        n = length(_eco_list(project, collection))
        n == 0 && continue
        singular = get(_ECO_SINGULAR, collection, nothing)
        label = singular === nothing ? nothing : get(_ECO_KIND_LABEL, singular, nothing)
        label = lowercase(label === nothing || isempty(label) ? collection : label)
        push!(counts, "$n $(n == 1 ? _eco_singularise(label) : label)")
    end
    if !isempty(counts)
        systems = length(_eco_list(project, "systems"))
        states = _eco_state_count(project)
        push!(lines,
              "Holds $(_eco_list_of(counts))" *
              (systems != 0 ? ", in $systems sub-system$(systems == 1 ? "" : "s")" : "") *
              (states != 0 ? "; $states state$(states == 1 ? "" : "s") to integrate" : "") *
              ".")
    end

    # What it is indexed by: the lists blocks actually carry, most used first.
    used = OrderedDict{String,Int}()
    for collection in COLLECTIONS
        for block in _eco_list(project, collection)
            dims = block isa AbstractDict ? get(block, "index_lists", nothing) : nothing
            dims isa AbstractVector || continue
            for dim in dims
                used[dim] = get(used, dim, 0) + 1
            end
        end
    end
    ranked = sort!(collect(used); by=item -> (-item[2], _eco_collation_key(item[1])), alg=MergeSort)
    dims = String[]
    for (name, _) in ranked
        lst = nothing
        for l in _eco_list(project, "index_lists")
            if get(l, "name", nothing) == name
                lst = l
                break
            end
        end
        n = lst === nothing ? 0 : count(i -> get(i, "enabled", nothing) !== false, _eco_list(lst, "indices"))
        push!(dims, n != 0 ? "$name ($n)" : name)
    end
    if !isempty(dims)
        most = 6
        shown = dims[1:min(most, length(dims))]
        length(dims) > most && push!(shown, "$(length(dims) - most) more")
        push!(lines, "Indexed by $(_eco_list_of(shown)).")
    end

    # What a run of it does.
    sim = get(project, "simulation", nothing)
    sim isa AbstractDict || (sim = JDict())
    if get(sim, "end_time", nothing) !== nothing
        unit = get(sim, "time_unit", nothing)
        unit = unit === nothing ? "year" : unit
        start = get(sim, "start_time", nothing)
        solver = get(sim, "solver", nothing)
        push!(lines, "Runs $(_eco_fmt_count(start === nothing ? 0 : start)) to $(_eco_fmt_count(sim["end_time"])) " *
                     "$(unit)s with $(solver === nothing ? DEFAULT_SOLVER : solver).")
    end
    return join(lines, "\n")
end

# How many state variables the solver will integrate, as the application
# counts them (`Model.state_count` on the project as it stands): one per
# combination of each compartment's and running mean's enabled indices.
function _eco_state_count(project::JDict)
    stored = [l for l in _eco_list(project, "index_lists") if l isa AbstractDict]
    lists = derive_elements(stored)
    for (name, collection) in ((COMPARTMENT_LIST, "compartments"), (TRANSFER_LIST, "transfers"))
        any(l -> get(l, "name", nothing) == name, lists) && continue
        names_ = String[]
        for b in _eco_list(project, collection)
            (b isa AbstractDict && !_eco_truthy(get(b, "hidden", nothing))) || continue
            sys = get(b, "system", nothing)
            n = _eco_truthy(sys) ? "$(sys).$(get(b, "name", nothing))" : get(b, "name", nothing)
            (n isa AbstractString && !isempty(n)) && push!(names_, n)
        end
        isempty(names_) && continue
        push!(lists, JDict("name" => name, "indices" => Any[JDict("name" => n, "enabled" => true) for n in names_]))
    end
    function material_dimension()
        nuc = nothing
        for l in stored
            if _eco_truthy(get(l, "for_nuclides", nothing))
                nuc = l
                break
            end
        end
        explicit = (nuc !== nothing && _eco_truthy(get(nuc, "indices", nothing))) ? nuc :
                   findfirst_value(l -> _eco_truthy(get(l, "for_contaminants", nothing)), stored)
        explicit !== nothing && return _eco_truthy(get(explicit, "indices", nothing)) ? explicit["name"] : nothing
        _eco_truthy(get(project, "nuclides", nothing)) && return NUCLIDE_LIST
        return nothing
    end
    function enabled_count(dim)
        lst = find_list(lists, dim)
        if lst === nothing
            return dim == NUCLIDE_LIST ? length(_eco_list(project, "nuclides")) : 0
        end
        return count(i -> !(i isa AbstractDict && get(i, "enabled", nothing) === false), _eco_list(lst, "indices"))
    end
    function effective_dims(b)
        dims = get(b, "index_lists", nothing)
        dims isa AbstractVector && return dims
        (haskey(b, "actions") || haskey(b, "timing")) && return Any[]
        name = material_dimension()
        (_eco_truthy(name) && get(b, "per_nuclide", nothing) !== false) && return Any[name]
        return Any[]
    end
    n = 0
    for collection in ("compartments", "running_means")
        for b in _eco_list(project, collection)
            c = 1
            for d in effective_dims(b)
                c *= enabled_count(d)
            end
            n += c
        end
    end
    return n
end

# `compartments` -> `compartment`, for the one-of case.
function _eco_singularise(label::String)
    endswith(label, "ies") && return label[1:end-3] * "y"
    (endswith(label, "es") && !endswith(label, "ses")) && return label[1:end-2]
    return endswith(label, "s") ? label[1:end-1] : label
end

# A number short enough for a sentence: 1e5 rather than 100000.
function _eco_fmt_count(v)
    n = _eco_to_number(v)
    isfinite(n) || return _eco_js_string(v)
    if n != 0 && (abs(n) >= 1e6 || abs(n) < 1e-3)
        return replace(_eco_to_exponential(_eco_round_significant(n, 4)), "e+" => "e"; count=1)
    end
    return _eco_js_string(_eco_round_significant(n, 6))
end

# <material-model>: the nuclides with their half-lives (seconds in the file,
# years here; a missing or infinite one is stable), the plain materials with
# their units, and the unit the inventories are in. `readMaterials`.
function _eco_read_materials(data_model::EcoXMLNode, project::JDict, report::EcoImportReport)
    model = _eco_child(data_model, "material-model")
    by_id = Dict{String,String}()
    by_name = OrderedDict{String,Any}()
    nuclide_names = Set{String}()
    units = Dict{String,String}()
    out = (by_id=by_id, by_name=by_name, nuclide_names=nuclide_names, units=units)
    model === nothing && return out

    # A half-life is in seconds, and how many make a year depends on the unit
    # the model runs in.
    said = _eco_py_lower(_eco_or(_eco_child_text(_eco_child(data_model, "simulation-settings"), "time-unit"), ""))
    per_year = _eco_seconds_per_year(get(_ECO_TIME_UNITS, said, "year"))
    half_lives = JDict()
    decay_unit = nothing
    for nuc in _eco_children(model, "nuclide")
        name = _eco_key_name(_eco_attr(nuc, "name"), "nuclide", report)
        _eco_truthy(name) || continue
        nid = _eco_child_text(nuc, "id")
        unit = _eco_normalise_decay_unit(_eco_child_text(nuc, "unit"))
        if _eco_truthy(unit)
            if _eco_truthy(decay_unit) && decay_unit != unit
                _eco_warn!(report,
                    "The nuclides disagree about their unit ($decay_unit and $unit); " *
                    "the model is read as $decay_unit.")
            elseif !_eco_truthy(decay_unit)
                decay_unit = unit
            end
        end
        raw_half_life = _eco_child_text(nuc, "half-life")
        seconds = _eco_to_number(raw_half_life)
        if isfinite(seconds) && seconds > 0
            half_lives[name] = seconds / per_year
        else
            # Stable isotopes are written with an infinite (or absent)
            # half-life. The word, not infinity, which JSON cannot hold.
            half_lives[name] = STABLE
            if _eco_truthy(raw_half_life) && !occursin("inf", _eco_ascii_lower(raw_half_life))
                _eco_warn!(report, "'$name' has no usable half-life; it is treated as stable.")
            end
        end
        _eco_truthy(nid) && (by_id[nid] = name)
        by_name[name] = (id=nid, name=name)
        push!(nuclide_names, name)
    end

    # Plain materials carry no decay and a unit of their own.
    for mat in _eco_children(model, "material")
        name = _eco_key_name(_eco_attr(mat, "name"), "material", report)
        _eco_truthy(name) || continue
        mid = _eco_child_text(mat, "id")
        _eco_truthy(mid) && (by_id[mid] = name)
        by_name[name] = (id=mid, name=name)
        unit = _eco_js_trim(_eco_or(_eco_child_text(mat, "unit"), ""))
        isempty(unit) || (units[name] = unit)
    end

    isempty(half_lives) || (project["half_lives"] = _eco_js_object_order(half_lives))
    # Written whichever it is, so a round trip cannot turn an amount model
    # into an activity one by saying nothing.
    project["decay_unit"] = decay_unit !== nothing ? decay_unit : "Bq"
    return out
end

# ASCII letters lowered, everything else as it is (`re.I | re.A`).
_eco_ascii_lower(s::AbstractString) = map(c -> 'A' <= c <= 'Z' ? c + 32 : c, String(s))

# A nuclide's `<unit>` as one of the two an inventory can be held in, or `nothing`.
function _eco_normalise_decay_unit(raw)
    given = _eco_js_trim(raw === nothing ? "" : string(raw))
    any(w -> _eco_ascii_ieq(given, w), ("mol", "mole", "moles")) && return "mol"
    any(w -> _eco_ascii_ieq(given, w), ("bq", "becquerel", "bequerel")) && return "Bq"
    return nothing
end

# One index list as the importer works on it before it is written out.
mutable struct _EcoList
    name::String
    indices::Vector{Any}
    index_by_id::Dict{String,String}
    id::Union{Nothing,String}
    original::String
    for_scenarios::Bool
    for_elements::Bool
    predefined::Union{Nothing,String}
    sub_set_of_id::Union{Nothing,String}
    mapping_to_id::Union{Nothing,String}
    mapping_pairs::Vector{Tuple{Any,Any}}
    sub_set_of::Union{Nothing,String}
    mapping::Union{Nothing,JDict}
    for_contaminants::Bool
    for_nuclides::Bool
end

# <index-list-model>: the index lists, their sub-sets and mappings (resolved
# by id), and which of them are the material catalogue, the radionuclides,
# the scenarios and the elements -- by Ecolego's predefined-type where the
# file writes one, then by name, then by shape. `readIndexLists`.
function _eco_read_index_lists(data_model::EcoXMLNode, project::JDict, names::_EcoNameMapper,
                               report::EcoImportReport, materials)
    model = _eco_child(data_model, "index-list-model")
    list_by_id = Dict{String,_EcoList}()
    index_by_id = Dict{String,Tuple{String,String}}()    # only for resolving mapping pairs
    model === nothing && return (list_by_id=list_by_id, index_by_id=index_by_id)

    raw = _EcoList[]
    for list_el in _eco_children(model, "index-list")
        # This package's export writes a scenario list under Ecolego's name
        # for it, `Scenarios`, with its own name beside it: that name is the list's.
        own_name = _eco_predefined_type(list_el) == "SCENARIOS" ? _eco_property_text(list_el, "kompartment-name") :
                   nothing
        raw_name = _eco_truthy(own_name) ? own_name : _eco_attr(list_el, "name")
        list_id = _eco_child_text(list_el, "id")
        key = list_id !== nothing ? list_id : (raw_name !== nothing ? raw_name : "")
        name = _eco_map!(names, raw_name, "indexlist:$key", "", "IndexList")
        original_name = _eco_js_trim(raw_name === nothing ? "" : string(raw_name))
        isempty(original_name) && (original_name = name)

        indices = Any[]
        own_index_by_id = Dict{String,String}()
        for idx_el in _eco_children(list_el, "index")
            idx_name = _eco_key_name(_eco_attr(idx_el, "name"), "index of '$original_name'", report)
            _eco_truthy(idx_name) || continue
            idx_id = _eco_child_text(idx_el, "id")
            enabled_attr = _eco_attr(idx_el, "enabled")
            enabled = enabled_attr === nothing ? true : _eco_py_lower(enabled_attr) == "true"
            push!(indices, JDict("name" => idx_name, "enabled" => enabled))
            if _eco_truthy(idx_id)
                own_index_by_id[idx_id] = idx_name
                haskey(index_by_id, idx_id) || (index_by_id[idx_id] = (idx_name, name))
            end
        end

        predefined = _eco_predefined_type(list_el)
        entry = _EcoList(name, indices, own_index_by_id, list_id, original_name,
                         predefined == "SCENARIOS", predefined == "ELEMENTS", predefined,
                         nothing, nothing, Tuple{Any,Any}[], nothing, nothing, false, false)
        sub_set = _eco_child(list_el, "sub-set")
        (sub_set !== nothing && _eco_truthy(_eco_attr(sub_set, "of"))) && (entry.sub_set_of_id = _eco_attr(sub_set, "of"))
        mapping = _eco_child(list_el, "mapping")
        if mapping !== nothing && _eco_truthy(_eco_attr(mapping, "to"))
            entry.mapping_to_id = _eco_attr(mapping, "to")
            entry.mapping_pairs = Tuple{Any,Any}[(_eco_attr(m, "from"), _eco_attr(m, "to"))
                                                 for m in _eco_children(mapping, "map")]
        end
        push!(raw, entry)
        _eco_truthy(list_id) && (list_by_id[list_id] = entry)
    end

    # Resolve id references now that every list is known.
    for entry in raw
        if _eco_truthy(entry.sub_set_of_id)
            root = get(list_by_id, entry.sub_set_of_id, nothing)
            if root !== nothing
                entry.sub_set_of = root.name
            else
                _eco_warn!(report, "Index list '$(entry.original)' is a sub-set of a list that is not in the file.")
            end
        end
        if _eco_truthy(entry.mapping_to_id)
            target = get(list_by_id, entry.mapping_to_id, nothing)
            if target !== nothing
                pairs = Any[]
                for (from_id, to_id) in entry.mapping_pairs
                    frm = from_id === nothing ? nothing : get(entry.index_by_id, from_id, nothing)
                    if frm === nothing
                        hit = from_id === nothing ? nothing : get(index_by_id, from_id, nothing)
                        frm = hit === nothing ? nothing : hit[1]
                    end
                    to = to_id === nothing ? nothing : get(target.index_by_id, to_id, nothing)
                    if to === nothing
                        hit = to_id === nothing ? nothing : get(index_by_id, to_id, nothing)
                        to = hit === nothing ? nothing : hit[1]
                    end
                    (_eco_truthy(frm) && _eco_truthy(to)) && push!(pairs, JDict("from" => frm, "to" => to))
                end
                entry.mapping = JDict("to" => target.name, "pairs" => pairs)
            else
                _eco_warn!(report, "Index list '$(entry.original)' maps to a list that is not in the file.")
            end
        end
    end

    # The material dimensions: by predefined type, then by name, then by shape.
    known = Set(keys(materials.by_name))
    candidates = [e for e in raw if !isempty(e.indices) && all(i -> i["name"] in known, e.indices)]

    function list_named(want)
        for e in raw
            lowercase(_eco_js_trim(e.name)) == want && return e
        end
        return nothing
    end
    usable(e) = e !== nothing && (isempty(e.indices) || any(c -> c === e, candidates))

    catalogue = findfirst_value(e -> e.predefined == "MATERIALS", raw)
    nuclides = findfirst_value(e -> e.predefined == "RADIONUCLIDES", raw)
    (catalogue === nothing && usable(list_named("materials"))) && (catalogue = list_named("materials"))
    (nuclides === nothing && usable(list_named("radionuclides"))) && (nuclides = list_named("radionuclides"))
    # The shape: a sub-set of the materials is the radionuclides, and the list
    # a radionuclide sub-set is taken from is the materials.
    if catalogue === nothing && nuclides !== nothing && _eco_truthy(nuclides.sub_set_of)
        catalogue = findfirst_value(e -> e.name == nuclides.sub_set_of, raw)
    end
    if catalogue === nothing
        catalogue = findfirst_value(e -> !_eco_truthy(e.sub_set_of) && e.mapping === nothing, candidates)
        if catalogue === nothing && !isempty(candidates)
            catalogue = sort(candidates; by=e -> -length(e.indices), alg=MergeSort)[1]
        end
    end
    if nuclides === nothing && catalogue !== nothing
        nuclides = findfirst_value(e -> e !== catalogue && e.sub_set_of == catalogue.name, candidates)
    end

    if catalogue !== nothing
        catalogue.for_contaminants = true
        # A material that is not a radionuclide is measured in its own unit.
        for i in catalogue.indices
            unit = get(materials.units, i["name"], nothing)
            _eco_truthy(unit) && (i["unit"] = unit)
        end
    end
    if nuclides !== nothing && nuclides !== catalogue
        nuclides.for_nuclides = true
        if !_eco_truthy(nuclides.sub_set_of) && catalogue !== nothing
            nuclides.sub_set_of = catalogue.name
        end
        # A file may carry the list without its contents; Ecolego decays what
        # the material model says, so that is what goes here.
        have = Set(i["name"] for i in nuclides.indices)
        added = String[]
        for i in (catalogue !== nothing ? catalogue.indices : Any[])
            (i["name"] in have || !(i["name"] in materials.nuclide_names)) && continue
            push!(nuclides.indices, JDict("name" => i["name"], "enabled" => i["enabled"]))
            push!(added, i["name"])
        end
        if !isempty(added) && isempty(have)
            _eco_warn!(report,
                "'$(nuclides.name)' is empty in this file; its $(length(added)) " *
                "radionuclide$(length(added) == 1 ? "" : "s") were read from the " *
                "material model, which is what Ecolego decays them from.")
        end
    end
    decaying = nuclides !== nothing ? nuclides : catalogue
    if decaying !== nothing
        project["nuclides"] = Any[i["name"] for i in decaying.indices if i["enabled"]]
    end

    # A file that says nothing about its lists still names them: `Scenarios`
    # and `Elements` are Ecolego's own names for its own.
    if !any(e -> e.for_scenarios, raw)
        found = list_named("scenarios")
        found !== nothing && (found.for_scenarios = true)
    end
    if !any(e -> e.for_elements, raw)
        found = list_named("elements")
        if found !== nothing && !found.for_contaminants && !found.for_nuclides
            found.for_elements = true
        end
    end

    scenarios = [e for e in raw if e.for_scenarios]
    named = [i for e in scenarios for i in e.indices if i["enabled"]]
    if length(named) > 1
        _eco_warn!(report,
            "This model has $(length(named)) scenarios ($(scenarios[1].name)). Ecolego " *
            "runs one simulation per scenario; this tool runs one at a time -- pick " *
            "which under Simulation, and every block indexed by that list is read at " *
            "the one selected. It opened on '$(named[1]["name"])'.")
    end

    lists = Any[]
    for e in raw
        out = JDict("name" => e.name, "indices" => e.indices)
        e.for_contaminants && (out["for_contaminants"] = true)
        e.for_nuclides && (out["for_nuclides"] = true)
        e.for_scenarios && (out["for_scenarios"] = true)
        e.for_elements && (out["for_elements"] = true)
        _eco_truthy(e.sub_set_of) && (out["sub_set_of"] = e.sub_set_of)
        e.mapping !== nothing && (out["mapping"] = e.mapping)
        push!(lists, out)
    end
    project["index_lists"] = lists
    return (list_by_id=list_by_id, index_by_id=index_by_id)
end

# <nuclide-decay-model>: the decay pairs, with their branching ratios (1
# where the file's is not a number). `readDecayChains`.
function _eco_read_decay_chains(data_model::EcoXMLNode, project::JDict, report::EcoImportReport)
    model = _eco_child(data_model, "nuclide-decay-model")
    model === nothing && return
    chains = Any[]
    for pair in _eco_children(model, "decay-pair")
        rate = _eco_attr(pair, "rate")
        parent = _eco_key_name(_eco_attr(pair, "parent"), "decay pair parent", report)
        daughter = _eco_key_name(_eco_attr(pair, "daughter"), "decay pair daughter", report)
        (_eco_truthy(parent) && _eco_truthy(daughter)) || continue
        # A missing attribute is `undefined`, which is NaN.
        ratio = rate === nothing ? NaN : _eco_to_number(rate)
        push!(chains, Any[parent, daughter, isfinite(ratio) ? ratio : 1])
    end
    isempty(chains) || (project["chains"] = chains)
end

# <block-model>: every component and connection, as blocks of this tool's
# kinds or as entries in the report. Returns the map from block id to
# qualified name, the sub-system wiring, the transfers made in two (by
# qualified name) and the general variables. `readBlocks`.
function _eco_read_blocks(data_model::EcoXMLNode, project::JDict, names::_EcoNameMapper, index_ids,
                          report::EcoImportReport, hierarchy)
    model = _eco_child(data_model, "block-model")
    if model === nothing
        _eco_warn!(report, "The file has no <block-model>; nothing to import.")
        return (OrderedDict{String,String}(),
                (links=Any[], operations=Dict{String,String}(), exposed=OrderedDict{String,Nothing}(),
                 id_by_guid=Dict{String,String}()),
                OrderedDict{String,String}(), Any[])
    end

    elements = vcat(_eco_children(model, "component"), _eco_children(model, "connection"))

    links = Any[]
    operations = Dict{String,String}()
    exposed = OrderedDict{String,Nothing}()
    # A transfer made in two, by the qualified name of the file's.
    twins = OrderedDict{String,String}()
    generals = Any[]

    block_name_by_id = OrderedDict{String,String}()
    path_by_id = hierarchy.path_by_id
    declared = Set{String}(hierarchy.systems)

    function system_of_element(el)
        # A file that declares no hierarchy still says where its blocks live,
        # so an undeclared parent is taken at its word.
        parent_id = _eco_child_text(el, "sub-system")
        _eco_truthy(parent_id) || return ""
        hit = get(path_by_id, parent_id, nothing)
        hit === nothing || return hit
        all_parts = split(parent_id, '.')
        path = join((_eco_map!(names, part, "subsystem:$(join(all_parts[1:k], '.'))", join(all_parts[1:k-1], '.'),
                               "subsystem")
                     for (k, part) in enumerate(all_parts)), '.')
        path_by_id[parent_id] = path
        if !(path in declared)
            push!(declared, path)
            push!(get!(project, "systems", Any[]), path)
        end
        return path
    end

    dim_ids_of(el) = [s for s in (_eco_js_trim(p) for p in split(_eco_attr(el, "index-lists", ""), ',')) if !isempty(s)]
    dim_lists_of(el) = _EcoList[l for l in (get(index_ids.list_by_id, i, nothing) for i in dim_ids_of(el))
                                if l !== nothing]

    dims_by_id = Dict{String,Vector{_EcoList}}()
    boundary_ids = Set{String}()
    system_by_id = Dict{String,String}()
    disabled_ids = OrderedDict{String,Nothing}()
    id_by_guid = Dict{String,String}()

    # Pass one: block id -> qualified name, so connections can resolve their
    # ends and equations their qualified references.
    for el in elements
        bid = _eco_child_text(el, "id")
        type_ = _eco_attr(el, "type")
        _eco_truthy(bid) || continue
        guid = _eco_child_text(el, "guid")
        _eco_truthy(guid) && (id_by_guid[_eco_js_trim(guid)] = bid)
        _eco_child_bool(el, "enabled", true) || (disabled_ids[bid] = nothing)
        if type_ in _ECO_BOUNDARY
            push!(boundary_ids, bid)
            continue
        end
        type_ in _ECO_SUPPORTED || continue
        dims_by_id[bid] = dim_lists_of(el)
        system = system_of_element(el)
        system_by_id[bid] = system
        local_ = _eco_map!(names, _eco_attr(el, "name"), bid, system, bid)
        block_name_by_id[bid] = isempty(system) ? local_ : "$system.$local_"
    end

    transports = hierarchy.transports
    for el in elements
        type_ = _eco_attr(el, "type")
        original = _eco_attr(el, "name", "(unnamed)")

        type_ in _ECO_BOUNDARY && continue        # folded into the transfers that attach to it
        if type_ in _ECO_INTERFACE
            # Read for its wiring, then dropped. A disabled one routes nothing.
            cid = _eco_child_text(el, "id")
            (cid !== nothing && haskey(disabled_ids, cid)) && continue
            if type_ == "connector"
                for link in _eco_children(el, "model-connection")
                    source = _eco_js_trim(_eco_attr(link, "source", ""))
                    target = _eco_js_trim(_eco_attr(link, "target", ""))
                    (isempty(source) || isempty(target)) ||
                        push!(links, (source=source, target=target, via=original))
                end
            else
                for obj in _eco_children(el, "interface-object")
                    guid = _eco_js_trim(_eco_attr(obj, "guid", ""))
                    isempty(guid) && continue
                    exposed[guid] = nothing
                    op = _eco_py_upper(_eco_js_trim(_eco_attr(obj, "operation", "")))
                    isempty(op) || (operations[guid] = op)
                end
            end
            continue
        end
        if type_ in _ECO_NON_NUMERIC
            _eco_note!(report, type_, original)
            continue
        end
        if !(type_ in _ECO_SUPPORTED)
            _eco_skip!(report, type_ === nothing ? "unknown" : type_, original,
                       "this tool has no equivalent block type")
            continue
        end

        bid = _eco_child_text(el, "id")
        system = bid !== nothing ? get(system_by_id, bid, nothing) : nothing
        system === nothing && (system = system_of_element(el))
        qualified = bid !== nothing ? get(block_name_by_id, bid, nothing) : nothing
        qualified === nothing && (qualified = _eco_map!(names, original, bid !== nothing ? bid : original, system))
        # Blocks carry their own local name and the sub-system holding them.
        name = (!isempty(system) && startswith(qualified, "$system.")) ?
               qualified[ncodeunits(system)+2:end] : qualified
        # Dimension lists in declared order, for resolving entry ids -- and,
        # where the file names none but says there is one, the list that
        # stands for the intersection of a transfer's two ends.
        dim_lists = dim_lists_of(el)
        isempty(dim_lists) && (dim_lists = _eco_intersection_dims(el, original, dims_by_id, report))
        dims = Any[l.name for l in dim_lists if !isempty(l.name)]
        # A block with no index lists is scalar and says so.
        dim_spec = isempty(dims) ? ("per_nuclide" => false) : ("index_lists" => dims)

        unit = _eco_or_str(_eco_child_text(el, "unit"))
        comment = _eco_or_str(_eco_child_text(el, "comment"))
        entries = _eco_read_entries(el, dim_lists, report, original)

        if type_ in _ECO_GENERAL_VARIABLE
            # The pick is the entry's equation; the oldest spelling gives it,
            # and the list, by GUID instead. A pick nobody made reads 0.
            by_guid(node) = node === nothing ? nothing :
                            get(id_by_guid, _eco_js_trim(_eco_attr(node, "guid", "")), nothing)
            picked = _eco_or(_eco_pick_default(entries, "equation"), by_guid(_eco_find(el, "selected-object-guid")))
            offered = String[]
            _eco_walk(el) do node
                oid = if node.name == "available-object"
                    _eco_hasattr(node, "id") ? _eco_js_trim(_eco_attr(node, "id")) : nothing
                elseif node.name == "available-object-guid"
                    by_guid(node)
                else
                    nothing
                end
                (_eco_truthy(oid) && !(oid in offered)) && push!(offered, oid)
                return nothing
            end
            block = _eco_trim_empty((
                "name" => name, "system" => system, dim_spec,
                # Ecolego shows the chosen block's unit as this one's and
                # writes a copy of it, which stands until the block is found.
                "unit" => _eco_truthy(unit) ? unit : _eco_or(_eco_pick_default(entries, "unit"), ""),
                "comment" => comment,
                "equation" => _eco_or(picked, "0"),
                "entries" => _eco_keep_indexed(entries, ("equation",)),
            ))
            push!(project["expressions"], block)
            push!(generals, (block=block, picked=picked !== nothing, offered=offered))
            continue
        end

        is_expression = type_ in ("expression", "post-processing", "constant", "transport-number")
        role = get(_ECO_TRANSPORT_ROLE, type_, nothing)
        role_patch = role === nothing ? () : ("transport" => role,)
        # A part of a transport outside a transport sub-system is a part of
        # nothing: a file edited by hand.
        if role !== nothing && !(system in transports)
            _eco_skip!(report, type_, original, "it is a part of a transport, and is not inside one")
            continue
        end

        if type_ == "compartment" || role in ("begin", "end")
            _eco_readable_tolerances!(entries, original, report)
            block = JDict("name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                          role_patch...,
                          "handle_decay" => _eco_child_bool(el, "handle-decay", true),
                          "initial" => _eco_or(_eco_pick_default(entries, "initial"), "0"),
                          "abstol" => _eco_pick_default(entries, "abstol"),
                          "dydt" => _eco_pick_default(entries, "dydt"))
            block["non_negative"] = _eco_read_non_negative(entries, original, report)
            block["entries"] = _eco_keep_indexed(entries, ("initial", "abstol", "dydt"))
            compartment = _eco_trim_empty(block)
            # An empty <unit> is a compartment that has none, as the export
            # writes one; no <unit> at all is the Bq an Ecolego file means.
            (unit == "" && _eco_child(el, "unit") !== nothing) && (compartment["unit"] = "")
            push!(project["compartments"], compartment)
        elseif role == "counter"
            push!(project["expressions"], _eco_trim_empty((
                "name" => name, "system" => system, dim_spec, "unit" => "", "comment" => comment,
                "transport" => "counter", "equation" => "1")))
        elseif role == "operation"
            # How it is read follows from how many arguments it declares.
            args = length(_eco_children(el, "argument"))
            operation = _eco_child_text(el, "operation")
            push!(project["expressions"], _eco_trim_empty((
                "name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                "transport" => "operation",
                "operation" => operation === nothing ? "MEAN" : operation,
                "argument" => args >= 2 ? "range" : args == 1 ? "point" : "all")))
        elseif is_expression
            if !(type_ in ("expression", "transport-number"))
                _eco_warn!(report,
                    "'$original' is a $type_ expression; this tool evaluates every " *
                    "expression at each step, which is equivalent unless it depended on " *
                    "the evaluation order.")
            end
            # An expression with `<argument>` elements is a function: called
            # with those values rather than read.
            arg_names = [a for a in (_eco_or(_eco_child_text(x, "argument-key"), _eco_child_text(x, "argument-name"))
                                     for x in _eco_children(el, "argument")) if _eco_truthy(a)]
            if !isempty(arg_names) && role === nothing
                parameters = String[]
                for a in arg_names
                    push!(parameters, _eco_safe_parameter(a, parameters))
                end
                per_index = _eco_keep_indexed(entries, ("equation",))
                if !isempty(per_index)
                    _eco_warn!(report,
                        "'$original' is a function of $(join(parameters, ", ")) with " *
                        "$(length(per_index)) equation(s) set per index. A function is " *
                        "worked out where it is called, at the caller's index, so only " *
                        "its default equation came across.")
                end
                push!(project["functions"], _eco_trim_empty((
                    "name" => name, "system" => system, "unit" => unit, "comment" => comment,
                    "parameters" => Any[parameters...],
                    "equation" => _eco_or(_eco_pick_default(entries, "equation"), ""))))
                continue
            end
            push!(project["expressions"], _eco_trim_empty((
                "name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment, role_patch...,
                "equation" => _eco_or(_eco_pick_default(entries, "equation"), "0"),
                "entries" => _eco_keep_indexed(entries, ("equation",)))))
        elseif type_ == "lookup-table"
            # An <argument> makes the table a function of what the caller
            # passes, instead of a series read at the clock.
            arg_el = _eco_child(el, "argument")
            argument = nothing
            if arg_el !== nothing
                argument = _eco_child_text(arg_el, "argument-key")
                _eco_truthy(argument) || (argument = _eco_child_text(arg_el, "argument-name"))
                _eco_truthy(argument) || (argument = "X")
            end
            option = _eco_child_text(el, "lookup-option")
            interpolation = _eco_interpolation_from_eco(option)
            if _eco_truthy(option) && !_eco_truthy(interpolation)
                _eco_warn!(report,
                    "'$original' uses the interpolation rule '$option', which this " *
                    "tool does not know; straight lines between the points were used.")
            end
            block = JDict("name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                          "interpolation" => _eco_or(interpolation, "linear"),
                          "cyclic" => _eco_child_bool(el, "lookup-cyclic", false))
            _eco_truthy(argument) && (block["argument"] = argument)
            block["points"] = _eco_or(_eco_pick_default(entries, "points"), Any[])
            block["entries"] = _eco_keep_indexed(entries, ("points",))
            push!(project["lookups"], _eco_trim_empty(block))
        elseif type_ in ("index-operation", "aggregate")
            # The target is the block's own equation: one id for an index
            # operation, ids joined with `+` for an aggregate.
            spec = _eco_or(_eco_pick_default(entries, "equation"), "")
            raw_op = _eco_child_text(el, "operation")
            operation = _eco_operation_from_eco(raw_op)
            if _eco_truthy(raw_op) && !_eco_truthy(operation)
                _eco_warn!(report,
                    "'$original' reduces with '$raw_op', which this tool does not know; " *
                    "it was summed instead.")
            end
            common = ("name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                      "operation" => _eco_or(operation, "sum"))
            if type_ == "index-operation"
                # Only when it is actually there: Number(null) is 0, which
                # would look like a stated percentile of zero.
                stated = _eco_property_text(el, "percentile")
                pct = _eco_child_number(el, "percentile")
                if pct === nothing
                    pct = (stated === nothing || stated == "") ? nothing : _eco_to_number(stated)
                end
                trimmed = _eco_js_trim(spec)
                block = JDict(common..., "target" => isempty(trimmed) ? nothing : trimmed)
                _eco_is_finite(pct) && (block["percentile"] = pct)
                block["entries"] = Any[JDict("index" => e["index"], "target" => _eco_js_trim(_eco_js_string(e["equation"])))
                                       for e in _eco_keep_indexed(entries, ("equation",))]
                push!(project["index_reductions"], _eco_trim_empty(block))
            else
                push!(project["block_reductions"], _eco_trim_empty((
                    common...,
                    "targets" => _eco_split_targets(spec),
                    "entries" => Any[JDict("index" => e["index"], "targets" => _eco_split_targets(e["equation"]))
                                     for e in _eco_keep_indexed(entries, ("equation",))])))
            end
        elseif haskey(_ECO_KIND_FROM_ECO, type_)
            # The blocks that remember, and the events that drive them.
            kind = _ECO_KIND_FROM_ECO[type_]
            ks = Tuple(vcat(_ECO_EQUATION_FIELDS[kind], _ECO_EVENT_FIELDS[kind]))
            common = ("name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment)
            pick(key, fallback) = _eco_or(_eco_pick_default(entries, key), fallback)
            per_index = _eco_keep_indexed(entries, ks)
            if kind == "min_max"
                raw_op = _eco_child_text(el, "operation")
                op = _eco_extreme_from_eco(raw_op)
                if _eco_truthy(raw_op) && !_eco_truthy(op)
                    _eco_warn!(report,
                        "'$original' records '$raw_op', which this tool does not know; " *
                        "its maximum was recorded instead.")
                end
                push!(project["min_maxes"], _eco_trim_empty((
                    common..., "operation" => _eco_or(op, "max"),
                    "target" => pick("target", "0"),
                    "reset_trigger" => pick("reset_trigger", nothing),
                    "start_trigger" => pick("start_trigger", nothing),
                    "stop_trigger" => pick("stop_trigger", nothing),
                    "entries" => per_index)))
            elseif kind == "running_mean"
                push!(project["running_means"], _eco_trim_empty((
                    common...,
                    "target" => pick("target", "0"),
                    "reset_trigger" => pick("reset_trigger", nothing),
                    "start_trigger" => pick("start_trigger", nothing),
                    "stop_trigger" => pick("stop_trigger", nothing),
                    "entries" => per_index)))
            elseif kind == "snapshot"
                push!(project["snapshots"], _eco_trim_empty((
                    common...,
                    "target" => pick("target", "0"),
                    "trigger" => pick("trigger", nothing),
                    "initial" => pick("initial", "0"),
                    "entries" => per_index)))
            elseif kind == "delay"
                push!(project["delays"], _eco_trim_empty((
                    common...,
                    "target" => pick("target", "0"),
                    "delay" => pick("delay", "0"),
                    "entries" => per_index)))
            else
                push!(project["triggers"], _eco_trim_empty((
                    common...,
                    "first" => pick("first", "0"),
                    "second" => pick("second", "0"),
                    "direction" => pick("direction", "rising"),
                    "entries" => per_index)))
            end
        elseif type_ == "parameter"
            # Only what could not be read is worth saying; a distribution that
            # arrived intact is on the parameter.
            unread = count(e -> _eco_truthy(get(e, "pdf_unread", nothing)), entries)
            if unread != 0
                what = unread == 1 ? "a probability distribution" : "$unread probability distributions"
                _eco_warn!(report,
                    "'$original' has $what " *
                    "this tool could not read; the constant value is used for " *
                    "$(unread == 1 ? "it" : "them").")
            end
            push!(project["parameters"], _eco_trim_empty((
                "name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                "value" => _eco_or(_eco_pick_default(entries, "value"), 0),
                "pdf" => _eco_pick_default(entries, "pdf"),
                "entries" => _eco_keep_indexed(entries, ("value", "pdf")))))
        elseif type_ in ("transfer", "transfer-coefficient")
            function resolve_end(id_attr, which)
                _eco_truthy(id_attr) || return nothing
                id_attr in boundary_ids && return nothing
                end_ = get(block_name_by_id, id_attr, nothing)
                if !_eco_truthy(end_)
                    _eco_warn!(report,
                        "Transfer '$original' $which a block that was not imported; " *
                        "that end was left open.")
                    return nothing
                end
                return end_
            end

            frm = resolve_end(_eco_attr(el, "source"), "starts at")
            to = resolve_end(_eco_attr(el, "target"), "ends at")
            if frm === nothing && to === nothing
                _eco_skip!(report, type_, original, "neither endpoint is a compartment in this model")
                continue
            end

            # Per the file format; the default row's own value still wins. A
            # transfer with no donor cannot be multiplied by one.
            donor = frm === nothing ? false :
                    _eco_or(_eco_pick_default(entries, "multiply_by_donor"), get(_ECO_DONOR_DEFAULT, type_, false))
            rate = _eco_or(_eco_pick_default(entries, "rate"), "0")

            # Ecolego keeps the flag row by row, and here it is one setting of
            # the transfer. Rows that say otherwise become a second transfer
            # between the same two ends, and the first moves nothing there.
            other = frm === nothing ? Any[] :
                    Any[e for e in entries if !isempty(e["index"]) && haskey(e, "multiply_by_donor") &&
                                              e["multiply_by_donor"] != donor]
            moved = Base.IdSet{Any}(other)
            push!(project["transfers"], _eco_trim_empty((
                "name" => name, "system" => system, dim_spec, "unit" => unit, "comment" => comment,
                "from" => frm, "to" => to,
                "rate" => rate,
                "multiply_by_donor" => donor,
                "entries" => _eco_keep_indexed(Any[e in moved ? _eco_with(e, "rate" => "0") : e for e in entries],
                                               ("rate",)))))
            if !isempty(other)
                twin = _eco_claim!(names, "$(name)_$(donor ? "absolute" : "by_donor")", system)
                twins[isempty(system) ? name : "$system.$name"] = isempty(system) ? twin : "$system.$twin"
                push!(project["transfers"], _eco_trim_empty((
                    "name" => twin, "system" => system, dim_spec,
                    "from" => frm, "to" => to,
                    "rate" => "0",
                    "multiply_by_donor" => !donor,
                    "entries" => Any[JDict("index" => e["index"], "rate" => _eco_or(get(e, "rate", nothing), rate))
                                     for e in other])))
                where_ = join((join((string(v) for v in values(e["index"])), ", ") for e in first(other, 3)), "; ")
                more = length(other) > 3 ? "; $(length(other) - 3) more" : ""
                _eco_warn!(report,
                    "'$original' $(donor ? "multiplies by its donor" : "is an absolute flux") at some indices " *
                    "and not at others ($where_$more), which is one setting of a whole transfer here. Those " *
                    "indices are '$twin', $(donor ? "an absolute flux" : "multiplied by the donor"), beside " *
                    "'$name', which moves nothing there; the two move what the file's transfer moves, and a " *
                    "block that reads '$name' reads zero at those indices.")
            end
        end
    end

    # The blocks the file switches off, now that they exist. A block inside a
    # sub-system the file switches off keeps its own switch; the report
    # counts what each such sub-system holds.
    off_names = Set{String}()
    for i in keys(disabled_ids)
        q = get(block_name_by_id, i, nothing)
        _eco_truthy(q) && push!(off_names, q)
    end
    for (whole, twin) in twins
        whole in off_names && push!(off_names, twin)
    end
    off_paths = hierarchy.disabled_paths

    in_off_system(system) = findfirst_value(p -> system == p || startswith(system, "$p."), off_paths)

    if !isempty(off_names) || !isempty(off_paths)
        for collection in ("compartments", "expressions", "transfers", "parameters", "inflows",
                           "lookups", "index_reductions", "block_reductions",
                           "min_maxes", "running_means", "snapshots", "delays", "triggers")
            for block in _eco_list(project, collection)
                qname = _eco_qualified(block)
                via = _eco_truthy(get(block, "system", nothing)) ? in_off_system(block["system"]) : nothing
                _eco_truthy(via) && _eco_in_disabled_system!(report, via)
                qname in off_names || continue
                block["enabled"] = false
                _eco_disable!(report, qname)
            end
        end
    end

    wiring = (links=links, operations=operations, exposed=exposed, id_by_guid=id_by_guid)
    return block_name_by_id, wiring, twins, generals
end

# `x or ''` for a child's text.
_eco_or_str(x) = _eco_truthy(x) ? x : ""

# `{**e, key: value}`.
function _eco_with(e::AbstractDict, kv::Pair)
    out = JDict(e)
    out[kv.first] = kv.second
    return out
end

# The list a transfer written over the intersection of its two ends stands
# on: Ecolego writes that list as `index-lists=""` with `dimension="1"`.
# When one end's list is a sub-set of the other's it *is* the intersection;
# two lists that merely overlap have none this tool can name, and that is
# said. `intersectionDims`.
function _eco_intersection_dims(el::EcoXMLNode, original, dims_by_id, report::EcoImportReport)
    dimension = _eco_attr(el, "dimension")
    width = _eco_to_number(dimension === nothing ? 0 : dimension)
    (!isfinite(width) || width < 1) && return _EcoList[]
    src_id = _eco_attr(el, "source")
    dst_id = _eco_attr(el, "target")
    frm = src_id === nothing ? _EcoList[] : get(dims_by_id, src_id, _EcoList[])
    to = dst_id === nothing ? _EcoList[] : get(dims_by_id, dst_id, _EcoList[])
    # One end outside the model has nothing to intersect with.
    if isempty(frm) || isempty(to)
        only = isempty(frm) ? to : frm
        return length(only) == width ? only : _EcoList[]
    end

    picks = _EcoList[]
    for a in frm
        for b in to
            narrower = if a.name == b.name
                a
            elseif a.sub_set_of == b.name
                a
            elseif b.sub_set_of == a.name
                b
            else
                nothing
            end
            (narrower !== nothing && !any(p -> p === narrower, picks)) && push!(picks, narrower)
        end
    end
    length(picks) == width && return picks

    a_names = join((l.name for l in frm), " × ")
    b_names = join((l.name for l in to), " × ")
    _eco_warn!(report,
        "'$original' is written over the indices its two ends have in common " *
        "($(isempty(a_names) ? "none" : a_names) and " *
        "$(isempty(b_names) ? "none" : b_names)), which is a list " *
        "Ecolego works out and does not write down. Neither end's dimension is " *
        "a sub-set of the other's, so there is no list here that holds exactly " *
        "those indices: '$original' was read as the file spells it, and will " *
        "need a dimension chosen by hand.")
    return _EcoList[]
end

# A block's <entry> elements, each as `{index: {list: index}, ...values}`. An
# entry whose index cannot be resolved against the block's own lists is
# dropped rather than applied to the wrong cells. A transfer's entries are
# read as a transfer's whatever their `type` says. `readEntries`.
function _eco_read_entries(el::EcoXMLNode, dim_lists::Vector{_EcoList}, report::EcoImportReport, block_label)
    out = JDict[]
    transfer = _eco_attr(el, "type") in ("transfer", "transfer-coefficient")
    for entry_el in el.children
        entry_el.name == "entry" || continue
        index = JDict()
        ids = [s for s in (_eco_js_trim(p) for p in split(_eco_attr(entry_el, "index", ""), ',')) if !isempty(s)]

        for (position, idx_id) in enumerate(ids)
            # The ids are written in the order the block declares its lists,
            # so position i belongs to dimension i; a search where it does not.
            positional = position <= length(dim_lists) ? dim_lists[position] : nothing
            if positional !== nothing && haskey(positional.index_by_id, idx_id)
                index[positional.name] = positional.index_by_id[idx_id]
                continue
            end
            owner = findfirst_value(l -> haskey(l.index_by_id, idx_id), dim_lists)
            if owner !== nothing
                index[owner.name] = owner.index_by_id[idx_id]
                continue
            end
            _eco_warn!(report,
                "An entry of '$block_label' is keyed by an index ('$idx_id') that none " *
                "of its index lists contains; that entry was dropped.")
        end

        rec = JDict("index" => index)
        type_ = transfer ? "transfer" : _eco_attr(entry_el, "type")

        if type_ == "compartment"
            _eco_assign_if!(rec, "initial", _eco_child_text(entry_el, "initial-condition"))
            _eco_assign_number_if!(rec, "lower", _eco_child_text(entry_el, "lower-saturation"))
            _eco_assign_number_if!(rec, "upper", _eco_child_text(entry_el, "upper-saturation"))
            # This compartment's own absolute tolerance, at this index.
            _eco_assign_number_if!(rec, "abstol", _eco_child_text(entry_el, "abs-tol"))
            # The extra term in the compartment's rate of change.
            _eco_assign_if!(rec, "dydt", _eco_child_text(entry_el, "differential-equation"))
        elseif type_ == "transfer"
            _eco_assign_if!(rec, "rate", _eco_or(_eco_child_text(entry_el, "transfer-equation"),
                                                 _eco_child_text(entry_el, "equation")))
            mult = _eco_child_text(entry_el, "multiply-with-donor")
            (mult !== nothing && mult != "") && (rec["multiply_by_donor"] = _eco_py_lower(mult) == "true")
            if _eco_truthy(_eco_child_text(entry_el, "transfer-event"))
                _eco_warn!(report,
                    "'$block_label' has a transfer event (a discrete transfer), which " *
                    "this tool does not support.")
            end
        elseif type_ == "expression"
            _eco_assign_if!(rec, "equation", _eco_child_text(entry_el, "equation"))
        elseif type_ == "parameter"
            _eco_assign_number_if!(rec, "value", _eco_child_text(entry_el, "value"))
            # The distribution, kept: `function=` names the kind and the
            # expression the family, and the parser needs both.
            pdf_el = _eco_child(entry_el, "pdf")
            if pdf_el !== nothing
                spec = _eco_parse_pdf(_eco_or(_eco_child_text(pdf_el, "pdf-value"), ""),
                                      _eco_or(_eco_attr(pdf_el, "function"), ""))
                if spec !== nothing && !isempty(spec)
                    rec["pdf"] = spec
                else
                    rec["pdf_unread"] = _eco_or(_eco_child_text(pdf_el, "pdf-value"), "")
                end
            end
        elseif type_ in ("min-max", "running-mean")
            _eco_assign_if!(rec, "target", _eco_child_text(entry_el, "target-expression"))
            _eco_assign_if!(rec, "reset_trigger", _eco_child_text(entry_el, "reset-event"))
            _eco_assign_if!(rec, "start_trigger", _eco_child_text(entry_el, "start-recording-event"))
            _eco_assign_if!(rec, "stop_trigger", _eco_child_text(entry_el, "stop-recording-event"))
        elseif type_ == "snapshot"
            _eco_assign_if!(rec, "target", _eco_child_text(entry_el, "snapshot-target"))
            _eco_assign_if!(rec, "trigger", _eco_child_text(entry_el, "snapshot-event"))
            _eco_assign_if!(rec, "initial", _eco_child_text(entry_el, "snapshot-initial-value"))
        elseif type_ == "delay"
            _eco_assign_if!(rec, "target", _eco_child_text(entry_el, "delay-target"))
            _eco_assign_if!(rec, "delay", _eco_child_text(entry_el, "delay-time"))
        elseif type_ == "discrete-event"
            _eco_assign_if!(rec, "first", _eco_child_text(entry_el, "first-expression"))
            _eco_assign_if!(rec, "second", _eco_child_text(entry_el, "second-expression"))
            direction = _eco_direction_from_eco(_eco_child_text(entry_el, "direction"))
            _eco_truthy(direction) && (rec["direction"] = direction)
        elseif type_ == "lookup-table"
            xs = _eco_number_list(_eco_child_text(entry_el, "lookup-table-time-points"))
            ys = _eco_number_list(_eco_child_text(entry_el, "lookup-table-values"))
            # Walked to the shorter of the two, so a truncated file loses the
            # tail rather than the whole table.
            n = min(length(xs), length(ys))
            if n < length(xs) || n < length(ys)
                _eco_warn!(report,
                    "'$block_label' has $(length(xs)) time point(s) but $(length(ys)) " *
                    "value(s); the extra ones were dropped.")
            end
            points = Any[Any[xs[k], ys[k]] for k in 1:n]
            isempty(points) || (rec["points"] = points)
            if _eco_child(entry_el, "link") !== nothing
                _eco_warn!(report,
                    "'$block_label' takes its table from a linked result, which this " *
                    "tool cannot follow; the stored points were used.")
            end
        end

        entry_unit = _eco_child_text(entry_el, "entry-unit")
        _eco_truthy(entry_unit) && (rec["unit"] = entry_unit)

        length(index) != length(ids) && continue
        push!(out, rec)
    end
    return out
end

# An aggregate's targets, as the format joins them: `a+b`.
_eco_split_targets(text) = Any[t for t in (_eco_js_trim(p) for p in split(text === nothing ? "" : _eco_js_string(text), '+'))
                               if !isempty(t)]

# The predefined-type an index list declares, upper-cased: one file writes
# `SCENARIOS`, an older one `Scenarios`.
function _eco_predefined_type(el::EcoXMLNode)
    text = _eco_property_text(el, "predefined-type")
    return _eco_truthy(text) ? _eco_py_upper(_eco_js_trim(text)) : nothing
end

# The text of a `<property name="...">`, trimmed, or `nothing`.
function _eco_property_text(el::EcoXMLNode, name::AbstractString)
    for p in el.children
        p.name == "property" || continue
        _eco_attr(p, "name") == name && return _eco_js_trim(_eco_text(p))
    end
    return nothing
end

# An array as the format writes it, `[1.0, 2.5, 3.0]`; what is not a number
# is dropped, and an empty element reads as 0, as `Number('')` does.
function _eco_number_list(text)
    text === nothing && return Float64[]
    inner = _eco_js_trim(string(text))
    startswith(inner, "[") && (inner = String(view(codeunits(inner), 2:ncodeunits(inner))))
    endswith(inner, "]") && (inner = String(view(codeunits(inner), 1:ncodeunits(inner)-1)))
    isempty(_eco_js_trim(inner)) && return Float64[]
    out = Float64[]
    for part in split(inner, ',')
        n = _eco_to_number(_eco_js_trim(part))
        isfinite(n) && push!(out, n)
    end
    return out
end

_eco_assign_if!(rec::JDict, key::String, value) = (value !== nothing && value != "") && (rec[key] = value)

function _eco_assign_number_if!(rec::JDict, key::String, value)
    (value === nothing || value == "") && return
    n = _eco_to_number(value)
    if isfinite(n)
        rec[key] = n
    elseif _eco_py_lower(value) == "infinity"
        rec[key] = Inf
    end
end

# Drops an absolute tolerance this tool cannot carry -- infinite, zero or
# negative -- and says so.
function _eco_readable_tolerances!(entries, block_label, report::EcoImportReport)
    dropped = 0
    for e in entries
        haskey(e, "abstol") || continue
        (_eco_is_finite(e["abstol"]) && e["abstol"] > 0) && continue
        delete!(e, "abstol")
        dropped += 1
    end
    if dropped != 0
        _eco_warn!(report,
            "'$block_label' sets an absolute tolerance this tool cannot carry " *
            "($dropped of them -- infinite, zero or negative). The " *
            "simulation's own absolute tolerance applies to those states.")
    end
end

# Ecolego's saturation band, read as the one constraint this tool keeps: a
# floor of zero is "cannot go negative", a negative floor is its opposite,
# and a positive floor or a finite ceiling is dropped with a warning.
function _eco_read_non_negative(entries, block_label, report::EcoImportReport)
    bounded = false
    negative_floor = false
    for e in entries
        lo = get(e, "lower", nothing)
        hi = get(e, "upper", nothing)
        if lo !== nothing && isfinite(_eco_to_number(lo))
            if _eco_to_number(lo) < 0
                negative_floor = true
            elseif _eco_to_number(lo) > 0
                bounded = true
            end
        end
        (hi !== nothing && isfinite(_eco_to_number(hi))) && (bounded = true)
    end
    if bounded
        _eco_warn!(report,
            "'$block_label' has a saturation band. This tool keeps only the " *
            "\"cannot go negative\" part of it, so the " *
            "floor and ceiling were dropped -- express a cap as a rate term " *
            "instead, or the model will not be the one in the file.")
    end
    return !negative_floor
end

# The value of the entry with no index -- Ecolego's default -- or `nothing`.
function _eco_pick_default(entries, key::String)
    for e in entries
        (isempty(e["index"]) && haskey(e, key)) && return e[key]
    end
    return nothing
end

# The entries that carry an index, with only `keys`.
function _eco_keep_indexed(entries, ks)
    out = Any[]
    for e in entries
        isempty(e["index"]) && continue
        rec = JDict("index" => e["index"])
        found = false
        for k in ks
            if haskey(e, k)
                rec[k] = e[k]
                found = true
            end
        end
        found && push!(out, rec)
    end
    return out
end

# --- simulation settings -----------------------------------------------------------------------

"""The solver each Ecolego solver name becomes: four are the same method,
the rest the nearest there is."""
const _ECO_SOLVER_MAP = Dict(
    "ODE45" => "dp45", "ODE23" => "dp45", "ODE113" => "dp45", "ODE853" => "dp45",
    # Ecolego's fixed-step Runge-Kutta methods, rk1 to rk5 in its menu.
    "ODE1" => "dp45", "ODE2" => "dp45", "ODE3" => "dp45", "ODE4" => "dp45", "ODE5" => "dp45",
    "ODE15S" => "ndf", "ODE15SBDF" => "ndf",
    "ODE23S" => "ros23", "ODE23T" => "ros23", "ODE23TB" => "ros23",
    "RADAU5" => "ndf", "KRYLOV" => "ndf", "PADE" => "ndf", "TAYLOR" => "ndf",
)

"""The names above that arrive at the same method rather than a substitute."""
const _ECO_SOLVER_EXACT = Set(["ODE15S", "ODE15SBDF", "ODE23S", "ODE45"])

"""Older names Ecolego still reads, as it reads them."""
const _ECO_SOLVER_ALIAS = Dict(
    "EULERFORWARD" => "ODE1", "EULERBACKWARD" => "ODE1", "HEUN" => "ODE2", "MIDPOINT" => "ODE3",
    "RK4" => "ODE4", "DORMANDPRINCE" => "ODE45", "IMEXSD" => "ODE15S",
)

"""Ecolego's "not set": one magic double written wherever a number was left alone."""
const _ECO_D_AUTO = -792842341234.23404823434

# One number from the file, with Ecolego's "not set" read as absent.
function _eco_auto_number(el::EcoXMLNode, tag::String)
    v = _eco_child_number(el, tag)
    (v === nothing || !isfinite(v)) && return nothing
    return abs(v - _ECO_D_AUTO) <= abs(_ECO_D_AUTO) * 1e-9 ? nothing : v
end

const _ECO_OUTPUT_MODES = Dict(
    "produce no additional output" => "solver",
    "produce additional output" => "both",
    "produce specified output only" => "series",
    "0" => "solver",
    "1" => "both",
    "2" => "series",
)

# When Ecolego saves results and on what times: <output-options> (in words,
# or as the index 0/1/2 older files write), overridden by <batch-mode>, and
# the series in <time-series-list> and <discrete-times>. The index is read
# through `Number()`, so a file with no <output-options> reads as 0.
function _eco_read_output_times(s::EcoXMLNode, sim::JDict, report::EcoImportReport)
    written = _eco_js_trim(_eco_or_str(_eco_child_text(s, "output-options")))
    mode = get(_ECO_OUTPUT_MODES, _eco_py_lower(written), nothing)
    mode === nothing && (mode = get(_ECO_OUTPUT_MODES, _eco_js_string(_eco_to_number(written)), nothing))

    series = vcat(_eco_read_time_series(_eco_child(s, "time-series-list"), sim, report),
                  _eco_read_time_series(_eco_child(s, "discrete-times"), sim, report))
    isempty(series) || (sim["output_times"] = Any[series...])

    # Batch mode reports on the specified times whatever the option says.
    batch = _eco_py_lower(_eco_js_trim(_eco_or_str(_eco_child_text(s, "batch-mode")))) == "true"
    wanted = batch ? "series" : mode
    _eco_truthy(wanted) || return
    if wanted == "solver"
        sim["spacing"] = "solver"
        return
    end
    if isempty(series)
        _eco_warn!(report,
            "The file asks for output on specified times but lists none; " *
            "$(_eco_js_string(sim["output_points"])) logarithmic points were used instead.")
        return
    end
    sim["spacing"] = wanted
end

# The <time-series> children of one list, as this tool's own series.
function _eco_read_time_series(host, sim::JDict, report::EcoImportReport)
    host === nothing && return JDict[]
    out = JDict[]
    for el in _eco_children(host, "time-series")
        type_ = _eco_py_lower(_eco_attr(el, "type", ""))
        if type_ == "custom"
            # `[1000.0, 2000.0]`; the empty tokens go before they are read as
            # numbers, or `[]` would be the single time zero.
            text = replace(_eco_or_str(_eco_child_text(el, "values")), '[' => "", ']' => "")
            times = Float64[]
            for t in _eco_split_times(text)
                v = _eco_to_number(t)
                isfinite(v) && push!(times, v)
            end
            isempty(times) || push!(out, JDict("kind" => "times", "times" => Any[sort(times; lt=<, alg=MergeSort)...]))
            continue
        end
        # Either end may be Ecolego's AUTO, "follow the simulation", which is
        # what this tool's series mean by an empty end.
        frm = _eco_auto_number(el, "time-series-start-time")
        to = _eco_auto_number(el, "time-series-end-time")
        kind = type_ == "geometric" ? "log" : "linear"
        points = _eco_child_number(el, "n")
        if points === nothing
            # An incrementing series says how far apart its points are.
            step = _eco_child_number(el, "increment")
            a = frm === nothing ? sim["start_time"] : frm
            b = to === nothing ? sim["end_time"] : to
            if step !== nothing && step > 0 && b > a
                points = _eco_js_floor((b - a) / step) + 1
                if abs((b - a) / step - _eco_js_round((b - a) / step)) > 1e-9
                    _eco_warn!(report,
                        "An output series steps by $(_eco_js_string(step)) from $(_eco_js_string(a)) " *
                        "to $(_eco_js_string(b)), which " *
                        "does not divide evenly; $(_eco_js_string(points)) points were used.")
                end
            end
        end
        if points === nothing || !(points >= 2)
            _eco_warn!(report, "An output series had no usable number of points and was dropped.")
            continue
        end
        push!(out, JDict("kind" => kind, "points" => _eco_js_round(Float64(points)), "from" => frm, "to" => to))
    end
    return out
end

# `re.split('[<JS space>,;]+', text)` without its empty pieces.
function _eco_split_times(text::String)
    out = String[]
    cu = codeunits(text)
    n = length(cu)
    i = 1
    start = 1
    while i <= n
        b = cu[i]
        k = (b == UInt8(',') || b == UInt8(';')) ? 1 : _eco_js_space_bytes(cu, i, n)
        if k > 0
            start < i && push!(out, String(view(cu, start:i-1)))
            i += k
            start = i
        else
            i += 1
        end
    end
    start <= n && push!(out, String(view(cu, start:n)))
    return out
end

const _ECO_TIME_UNITS = Dict(
    "second" => "second", "seconds" => "second", "s" => "second",
    "minute" => "minute", "minutes" => "minute",
    "hour" => "hour", "hours" => "hour", "h" => "hour",
    "day" => "day", "days" => "day", "d" => "day",
    "year" => "year", "years" => "year", "y" => "year", "a" => "year",
)

# The solver a file names, as a key of the solver map: Ecolego's own keys,
# `java-ode15s` and the like, and a bare `ODE15S`, case, punctuation and the
# `java` prefix dropped.
function _eco_solver_key(text::AbstractString)
    word = filter(c -> ('A' <= c <= 'Z') || ('0' <= c <= '9'), _eco_py_upper(text))
    startswith(word, "JAVA") && (word = word[5:end])
    return get(_ECO_SOLVER_ALIAS, word, word)
end

# <simulation-settings> and <probabilistic-settings>: the time span and unit,
# the solver and tolerances, the saturation switch, the output times, the
# endpoints, and what a probabilistic run would do. A file with none takes
# this tool's defaults. `readSimulationSettings`.
function _eco_read_simulation_settings(data_model::EcoXMLNode, project::JDict, report::EcoImportReport)
    s = _eco_child(data_model, "simulation-settings")
    sim = JDict(SIMULATION_DEFAULTS)
    if s === nothing
        project["simulation"] = sim
        _eco_warn!(report, "No simulation settings in the file; defaults were used.")
        return
    end

    start = _eco_child_number(s, "start-time")
    end_ = _eco_child_number(s, "end-time")
    start === nothing || (sim["start_time"] = start)
    end_ === nothing || (sim["end_time"] = end_)
    if !(sim["end_time"] > sim["start_time"])
        sim["start_time"] = 0
        sim["end_time"] = max(1, end_ === nothing ? 1e5 : end_)
        _eco_warn!(report, "The stored time span was not usable; it was reset.")
    end

    # Ecolego's master switch over every compartment's bounds, mapped onto the
    # floor, which is the part of it there is.
    saturation = _eco_child_text(s, "saturation-enabled")
    if saturation !== nothing && _eco_ascii_ieq(_eco_js_trim(saturation), "false")
        sim["non_negative"] = false
        _eco_warn!(report,
            "Saturation is switched off in this model, so no compartment is held at " *
            "zero -- which is how Ecolego runs it. Each compartment keeps its own " *
            "*cannot go negative* setting; none of them is consulted while the " *
            "switch is off. Turn it back on under Simulation if you want the floor.")
    end

    prob = _eco_child(data_model, "probabilistic-settings")
    if prob !== nothing
        n = _eco_to_number(_eco_child_text(prob, "no-simulations"))
        (isfinite(n) && n > 0) && (sim["iterations"] = _eco_js_round(n))
        # With no <seed>, `Number(null)` is 0, a seed.
        seed = _eco_to_number(_eco_child_text(prob, "seed"))
        isfinite(seed) && (sim["seed"] = _eco_js_round(seed))
        how = _eco_py_lower(_eco_or_str(_eco_child_text(prob, "sampling")))
        isempty(how) || (sim["sampling"] = occursin("latin", how) ? "latin" : "random")
        chosen = Any[t for t in (_eco_js_trim(_eco_text(n2))
                                 for n2 in _eco_children(_eco_child(prob, "probabilistic-parameters"),
                                                         "selected-parameter"))
                     if !isempty(t)]
        isempty(chosen) || (sim["varied"] = chosen)
        pairs = length(_eco_children(_eco_child(prob, "correlation-matrix"), "correlation-pair"))
        if pairs != 0 && _eco_child_text(prob, "correlation-enabled") != "false"
            _eco_warn!(report,
                "The model correlates $pairs pair(s) of parameters when it samples " *
                "them. This tool samples each one independently, so a probabilistic " *
                "run here spreads wider than Ecolego's would.")
        end
    end

    unit = _eco_py_lower(_eco_or_str(_eco_child_text(s, "time-unit")))
    if _eco_truthy(get(_ECO_TIME_UNITS, unit, nothing))
        sim["time_unit"] = _ECO_TIME_UNITS[unit]
    elseif !isempty(unit)
        _eco_warn!(report, "Unrecognised time unit '$unit'; years were assumed.")
    end

    said = _eco_js_trim(_eco_or_str(_eco_child_text(s, "java-solver")))
    solver = _eco_solver_key(said)
    if _eco_truthy(get(_ECO_SOLVER_MAP, solver, nothing))
        sim["solver"] = _ECO_SOLVER_MAP[solver]
        solver == "ODE15SBDF" && (sim["bdf"] = true)
        if !(solver in _ECO_SOLVER_EXACT)
            _eco_warn!(report,
                "The model used the $solver solver, which this tool does not have; " *
                "$(_eco_solver_name(sim["solver"])) was chosen as the closest.")
        end
    elseif !isempty(said)
        _eco_warn!(report,
            "The model names a solver this tool does not know, '$said'; " *
            "$(_eco_solver_name(sim["solver"])) was used.")
    end

    rtol = _eco_child_number(s, "rel-error-tolerance")
    atol = _eco_child_number(s, "abs-error-tolerance")
    (rtol !== nothing && rtol > 0) && (sim["rtol"] = rtol)
    (atol !== nothing && atol > 0) && (sim["abstol"] = atol)

    if sim["start_time"] < 0
        sim["spacing"] = "linear"
        _eco_warn!(report,
            "The simulation starts before zero, so linear output spacing was used " *
            "(logarithmic time needs a non-negative start).")
    end

    _eco_read_output_times(s, sim, report)
    _eco_read_endpoints(s, sim)

    type_ = _eco_py_upper(_eco_or_str(_eco_child_text(s, "simulation-type")))
    if !isempty(type_) && type_ != "DETERMINISTIC"
        _eco_warn!(report,
            "The model is set up for a $(_eco_py_lower(type_)) simulation; this tool " *
            "runs the deterministic case only.")
    end

    project["simulation"] = sim
end

# <function-model>: the project's compiled user-defined functions. Their
# names and parameters come across; their bodies, compiled code in the
# archive, cannot, and the report says so. `readFunctions`.
function _eco_read_functions(data_model::EcoXMLNode, project::JDict, names::_EcoNameMapper, report::EcoImportReport)
    model = _eco_find(data_model, "function-model")
    model === nothing && return
    for el in _eco_children(model, "function")
        original = _eco_attr(el, "name")
        original === nothing && (original = _eco_attr(el, "source-file-name"))
        original === nothing && (original = "function")
        name = _eco_map!(names, original, "fn:$original", "", original)
        meta = _eco_child(el, "function-metadata")
        parameters = String[]
        for p in (meta !== nothing ? _eco_children(meta, "parameter-metadata") : EcoXMLNode[])
            # The key is the identifier; the name is what the dialog showed.
            raw = _eco_attr(p, "key")
            raw === nothing && (raw = _eco_attr(p, "name"))
            raw === nothing && (raw = "p$(length(parameters) + 1)")
            push!(parameters, _eco_safe_parameter(raw, parameters))
        end
        push!(project["functions"], _eco_trim_empty((
            "name" => name,
            "parameters" => Any[parameters...],
            "equation" => "",
            "unit" => "",
            "comment" => _eco_or_str(_eco_child_text(meta !== nothing ? meta : el, "function-description")))))
        source = _eco_attr(el, "source-file-name")
        _eco_warn!(report,
            "'$original' is a user-defined function, whose body is compiled code in the project " *
            "archive ($(source === nothing ? "a compiled source file" : source)). This tool keeps " *
            "its name and its $(length(parameters)) parameter(s); write what it works out " *
            "to as an equation before the model will run.")
    end
end

# The endpoints by the names the blocks ended up with; a repeat is not a fault
# (Ecolego writes one per index), and an id with no block behind it is left
# out, with one warning for all of them. `rewriteEndpointIds`.
function _eco_rewrite_endpoint_ids!(project::JDict, block_name_by_id, report::EcoImportReport, twins)
    sim = get(project, "simulation", nothing)
    ids = sim isa AbstractDict ? get(sim, "endpoints", nothing) : nothing
    (ids isa AbstractVector && !isempty(ids)) || return
    known = Set{Any}()
    for collection in COLLECTIONS
        for b in _eco_list(project, collection)
            push!(known, _eco_qualified(b))
        end
    end
    out = Any[]
    seen = Set{Any}()
    unresolved = 0
    for eid in ids
        # The id first: in these files an id *is* the qualified name.
        name = eid in known ? eid : _eco_or(get(block_name_by_id, eid, nothing), eid)
        name in seen && continue
        if !(name in known)
            unresolved += 1
            continue
        end
        push!(seen, name)
        push!(out, name)
        # Half a transfer is not what was asked for.
        twin = get(twins, name, nothing)
        if _eco_truthy(twin) && !(twin in seen)
            push!(seen, twin)
            push!(out, twin)
        end
    end
    # A list of every block a run has a result for is what keeping everything
    # means here, where a block added later is kept too.
    if !isempty(out) && !_eco_names_every_result(project, seen)
        sim["endpoints"] = out
    else
        delete!(sim, "endpoints")
    end
    if unresolved != 0
        _eco_warn!(report,
            "$unresolved of the model's saved endpoints name blocks that are not in " *
            "the imported model; they were left out of the endpoint list.")
    end
end

# Whether a set of names holds every block a run has a result for: all but
# functions and tables read at a value, the parts of a transport that count,
# and what is switched off. `namesEveryResult`.
function _eco_names_every_result(project::JDict, names)
    any_block = false
    for collection in COLLECTIONS
        collection == "functions" && continue
        for b in _eco_list(project, collection)
            (b isa AbstractDict && get(b, "enabled", nothing) !== false) || continue
            argument = get(b, "argument", nothing)
            (collection == "lookups" && argument !== nothing && _eco_js_trim(string(argument)) != "") && continue
            (collection == "expressions" && get(b, "transport", nothing) in ("counter", "operation")) && continue
            any_block = true
            _eco_qualified(b) in names || return false
        end
    end
    return any_block
end

# Which blocks the model is set up to save: <outputs><output id>, as block
# ids until they are named.
function _eco_read_endpoints(s::EcoXMLNode, sim::JDict)
    lst = _eco_child(s, "outputs")
    lst === nothing && return
    ids = Any[i for i in (_eco_attr(o, "id") for o in _eco_children(lst, "output")) if i isa String && !isempty(i)]
    isempty(ids) || (sim["endpoints"] = ids)
end

# A parameter name this tool's parser can read, kept clear of its siblings.
function _eco_safe_parameter(raw, taken)
    s = _eco_js_trim(raw === nothing ? "" : string(raw))
    io = IOBuffer()
    in_run = false
    for c in s
        if ('A' <= c <= 'Z') || ('a' <= c <= 'z') || ('0' <= c <= '9') || c == '_'
            write(io, c)
            in_run = false
        elseif !in_run
            write(io, '_')
            in_run = true
        end
    end
    name = String(take!(io))
    (!isempty(name) && _eco_is_ascii_digit(name[1])) && (name = "p" * name)
    (isempty(name) || name in RESERVED) && (name = "p$(length(taken) + 1)")
    while name in taken
        name = name * "_"
    end
    return name
end
