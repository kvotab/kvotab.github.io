# Model files: JSON read in key order, and written as the application writes it.
#
# `JSON.stringify(model, null, 2)` writes numbers the JavaScript way
# (`100000`, `0.000015`, `1e-7`), so a model saved here is the file the
# application would save, line for line. Objects are read into ordered
# dictionaries, so the keys come back in the order the file has them.

using OrderedCollections: OrderedDict

"""The type a JSON object is read into: an ordered dictionary."""
const JDict = OrderedDict{String,Any}

include("jsonparse.jl")

"""
    jcopy(x)

A copy of a model's tree, as `deepcopy` gives one: every dictionary and list
copied, the leaves (text and numbers, which cannot change) shared. Several
times faster than `deepcopy`, which keeps a table of every object it has met;
a tree read from JSON has nothing met twice. Anything that is not a JSON
value is left to `deepcopy`.
"""
jcopy(x::Union{Nothing,Bool,Number,String,Symbol}) = x
function jcopy(x::JDict)
    out = JDict()
    sizehint!(out, length(x))
    for (k, v) in x
        out[k] = jcopy(v)
    end
    return out
end
function jcopy(x::Vector{Any})
    out = Vector{Any}(undef, length(x))
    @inbounds for i in eachindex(x)
        out[i] = jcopy(x[i])
    end
    return out
end
jcopy(x::Array{T}) where {T<:Union{Bool,Number,String,Nothing}} = copy(x)
jcopy(x) = deepcopy(x)

"""
    json_text(value; indent=2) -> String

`value` as JSON, formatted as `JSON.stringify(value, null, indent)`: numbers
as JavaScript writes them, keys in the dictionary's order, non-ASCII text as
it is.
"""
function json_text(value; indent::Integer=2)
    io = IOBuffer()
    _write_json(io, value, 0, indent)
    return String(take!(io))
end

function _write_string(io::IO, s::AbstractString)
    write(io, '"')
    for c in s
        if c == '"'
            write(io, "\\\"")
        elseif c == '\\'
            write(io, "\\\\")
        elseif c == '\n'
            write(io, "\\n")
        elseif c == '\r'
            write(io, "\\r")
        elseif c == '\t'
            write(io, "\\t")
        elseif c == '\b'
            write(io, "\\b")
        elseif c == '\f'
            write(io, "\\f")
        elseif c < ' '
            write(io, "\\u", string(UInt16(c); base=16, pad=4))
        else
            write(io, c)
        end
    end
    write(io, '"')
end

function _write_json(io::IO, v, depth::Int, indent::Int)
    if v === nothing
        write(io, "null")
    elseif v isa Bool
        write(io, v ? "true" : "false")
    elseif v isa Real
        write(io, js_number(v))
    elseif v isa AbstractString || v isa Symbol
        _write_string(io, string(v))
    elseif v isa AbstractDict
        if isempty(v)
            write(io, "{}")
            return
        end
        write(io, '{')
        first = true
        for (k, x) in v
            first || write(io, ',')
            first = false
            if indent > 0
                write(io, '\n', ' '^(indent * (depth + 1)))
            end
            _write_string(io, string(k))
            write(io, indent > 0 ? ": " : ":")
            _write_json(io, x, depth + 1, indent)
        end
        indent > 0 && write(io, '\n', ' '^(indent * depth))
        write(io, '}')
    elseif v isa AbstractVector || v isa Tuple
        if isempty(v)
            write(io, "[]")
            return
        end
        write(io, '[')
        first = true
        for x in v
            first || write(io, ',')
            first = false
            if indent > 0
                write(io, '\n', ' '^(indent * (depth + 1)))
            end
            _write_json(io, x, depth + 1, indent)
        end
        indent > 0 && write(io, '\n', ' '^(indent * depth))
        write(io, ']')
    else
        throw(ArgumentError("$(typeof(v)) is not something a model file can hold"))
    end
end

"""
    read_model_file(path) -> JDict

The model a `.json`, `.json.gz` (or `.gz`) or `.zip` file holds. A ZIP holds
the model as a `.json` entry; a saved run beside it, under `results/`, is not
read here.
"""
function read_model_file(path::AbstractString)
    data = read(path)
    name = basename(path)
    if is_gzip(data)
        data = gunzip(data)
    elseif is_zip(data)
        z = read_zip(data)
        names = [n for n in zip_names(z) if !startswith(n, "results/") && endswith(lowercase(n), ".json")]
        isempty(names) && error("'$name' is a ZIP archive with no model in it: it holds " *
                                join(first(zip_names(z), 4), ", "))
        data = zip_read(z, names[1])
    end
    model = parse_json(data)
    model isa AbstractDict || error("'$name' does not hold a model: a model is one JSON object")
    return model
end

"""The file name a model's name gives, as the application makes it."""
function slug(name)
    s = lowercase(replace(string(something(name, "")), r"[^A-Za-z0-9_]+" => "-"))
    s = strip(s, '-')
    return isempty(s) ? "model" : String(s)
end

"""
    write_model_file(path, model; indent=2) -> path

Writes a model as `.json`, `.json.gz` (or `.gz`) or `.zip`, by the name's ending.
"""
function write_model_file(path::AbstractString, model; indent::Integer=2)
    text = json_text(model; indent)
    low = lowercase(basename(path))
    if endswith(low, ".zip")
        write(path, write_zip([(slug(get(model, "name", nothing)) * ".json", Vector{UInt8}(codeunits(text)))];
                              modified=_dos_now()))
    elseif endswith(low, ".gz")
        write(path, gzip(Vector{UInt8}(codeunits(text))))
    else
        write(path, text)
    end
    return path
end

function _dos_now()
    t = Libc.TmStruct(time())
    return (Int(t.year) + 1900, Int(t.month) + 1, Int(t.mday), Int(t.hour), Int(t.min), Int(t.sec))
end

# --- reading values out of raw dictionaries ------------------------------------

"""`d[key]`, or `default` when `d` is not a dictionary or has no such key."""
jget(d, key, default=nothing) = d isa AbstractDict ? get(d, key, default) : default

"""Whether a raw value is truthy as JavaScript reads one (`!!v`)."""
function js_truthy(v)
    v === nothing && return false
    v isa Bool && return v
    v isa Real && return !(v == 0 || isnan(v))
    v isa AbstractString && return !isempty(v)
    return true
end
