# What the builder works out, as types: layout entries, statements, the
# derivative's phases and the jumps. Every index here is the application's,
# counted from 0; the code generator adds 1 where it reads an array.

struct BuildError <: Exception
    message::String
    block_name::Union{Nothing,String}
    setting::Union{Nothing,String}
end

const SLOT_WORDS = merge(
    Dict(k => lowercase(v) for (k, v) in WASTE_LABEL),
    Dict(k => "$(lowercase(v)) setting" for (k, v) in Dict("at" => "At", "rate" => "Rate", "from" => "From", "until" => "Until")),
    Dict("dydt" => "dy/dt term", "limit" => "availability limit", "top" => "availability numerator",
         "bottom" => "availability denominator", "hazard" => "failure hazard", "lambda" => "rate", "share" => "share"),
)

"""A builder message with its `'Block#setting'` names said in words."""
function in_words(message)
    text = message === nothing ? "" : string(message)
    text = replace(text, r"add '([^']+)' to '([^'#]+)#[^']*'" =>
                         s -> (m = match(r"add '([^']+)' to '([^'#]+)#[^']*'", s);
                               "add '$(m.captures[1])' to the lists $(m.captures[2]) is indexed by"))
    return replace(text, r"'([^'#\s]+)#([A-Za-z_]+\d*)'" => function (s)
        m = match(r"'([^'#\s]+)#([A-Za-z_]+\d*)'", s)
        block, key = m.captures[1], m.captures[2]
        words = get(SLOT_WORDS, key, nothing)
        words === nothing && (words = get(SLOT_WORDS, replace(key, r"\d+$" => ""), nothing))
        words === nothing && (words = "setting $key")
        return "$(block)’s $words"
    end)
end

function BuildError(message::AbstractString, block_name=nothing)
    cut = block_name isa AbstractString ? findfirst('#', block_name) : nothing
    owner = (cut !== nothing && cut > 1) ? block_name[1:cut-1] : block_name
    said = in_words(message)
    full = (owner !== nothing && owner != "") ? "$(owner): $(said)" : said
    setting = (cut !== nothing && cut > 1) ? block_name[cut+1:end] : nothing
    return BuildError(full, owner === nothing ? nothing : String(owner), setting === nothing ? nothing : String(setting))
end
Base.showerror(io::IO, e::BuildError) = print(io, e.message)

"""
A layout entry: a state block, a parameter, an algebraic slot range. The
fields every entry has are typed; the rest (what only some kinds carry) are
in `extra`, read as `e[:tab]`.
"""
mutable struct Entry
    name::String
    local_name::Union{Nothing,String}
    system::String
    kind::String
    block::Any                  # the normalised block (a JDict), or a holder
    value_key::Union{Nothing,String}
    dims::Vector{String}
    base::Int
    width::Int
    hidden::Bool
    equations::Vector{String}
    asts::Vector{ENode}
    uniform::Bool
    reads_alg::Vector{String}
    level::Int
    cls::Int
    needs::Vector{String}
    extra::Dict{Symbol,Any}
end

function Entry(; name="", local_name=nothing, system="", kind="", block=nothing, value_key=nothing,
               dims=String[], base=0, width=0, hidden=false, kw...)
    e = Entry(String(name), local_name === nothing ? nothing : String(local_name), String(system), String(kind), block,
              value_key, Vector{String}(dims), base, width, hidden, String[], ENode[], true, String[], 0, 0, String[],
              Dict{Symbol,Any}())
    for (k, v) in kw
        e.extra[k] = v
    end
    return e
end

Base.getindex(e::Entry, k::Symbol) = e.extra[k]
Base.setindex!(e::Entry, v, k::Symbol) = (e.extra[k] = v)
Base.get(e::Entry, k::Symbol, default) = get(e.extra, k, default)
Base.haskey(e::Entry, k::Symbol) = haskey(e.extra, k)
Base.show(io::IO, e::Entry) = print(io, "Entry(", e.kind, ", ", repr(e.name), ")")

"""What a statement of special code does, when it is not an expression."""
abstract type Special end

"""A far-field path's release: worked out from its cells (or its history)."""
struct FarfieldRelease <: Special
    index::Int        # which path, from 0
    laplace::Bool
end

"""A remembering block's value at each index: `X[out[i]] = MEM[mem[i]].<read>(...)`."""
struct RecorderRead <: Special
    kind::Symbol          # :min_max, :running_mean, :snapshot, :delay
    out::Vector{Int}      # slots written
    mem::Vector{Int}      # recorders read
    arg::Vector{Int}      # the target slot (min/max, running mean) or the delay slot (delay); empty for a snapshot
    state::Vector{Int}    # a running mean's summed state
end

"""One statement of a pass: `array[out] = tree` over `width` elements, or special code."""
mutable struct Stmt
    out::Union{Int,Vector{Int}}
    tree::Union{Nothing,TNode}
    width::Int
    block::Union{Nothing,Entry}
    level::Tuple{Int,Int}
    mergeable::Bool
    special::Union{Nothing,Special}
    array::Symbol         # :X, :y0 (and :state/:clock for special code, before classing)
    multiply::Bool
end

Stmt(out, tree, width, block, level; mergeable=true, special=nothing, array=:X, multiply=false) =
    Stmt(out, tree, width, block, level, mergeable, special, array, multiply)

out_indices(s::Stmt) = s.out isa Int ? fill(s.out, max(s.width, 1)) : s.out

"""
One phase of the derivative's assembly, in the order the application adds the
terms. Which fields mean what depends on `kind`:

- `:transfers` -- `tgt` the state each term goes into, `a` the flux it is, `f` its sign;
- `:x`         -- `tgt` and `a`, the algebraic slot added there;
- `:waste`     -- `tgt` the intact inventory, `a` the exposed one, `s1` the hazard slot,
                  `b` the release slots, `c` the budget's `out` slots (empty without the audit);
- `:move`      -- `tgt` the states moved out of, `a` where they go (empty: nowhere), `s1`
                  the event's rate slot, `s2` its share slot;
- `:mean`      -- `tgt` the summed states, `a` the target slots, `s1` the first recorder;
- `:coef`      -- `tgt`, `f` the coefficient, `a` the state it multiplies;
- `:farf`      -- `s1` the path.
"""
struct Phase
    kind::Symbol
    tgt::Vector{Int}
    a::Vector{Int}
    b::Vector{Int}
    c::Vector{Int}
    f::Vector{Float64}
    s1::Int
    s2::Int
end
Phase(kind; tgt=Int[], a=Int[], b=Int[], c=Int[], f=Float64[], s1=-1, s2=-1) = Phase(kind, tgt, a, b, c, f, s1, s2)

"""What a jump in the state does, one operation at a time."""
abstract type JumpOp end
struct JumpCount <: JumpOp
    slot::Int                  # y[slot] += 1
end
"""Packages failing: a share of the intact inventory fails; the instant
release fraction goes on to `to`, the rest is exposed."""
struct JumpFail <: JumpOp
    share_slot::Int            # -1: all of them (share 1)
    intact::Vector{Int}
    exposed::Vector{Int}
    irf::Vector{Int}
    to::Vector{Int}            # where the instant release goes (empty: nowhere the model holds)
    budget::Vector{Int}        # the audit's `out` (empty without it)
end
"""A share of a compartment moved, cell for cell, into another (or out of the model)."""
struct JumpMove <: JumpOp
    share_slot::Int
    from::Vector{Int}
    to::Vector{Int}            # empty: out of the model
    budget::Vector{Int}
end

struct JumpSpec
    name::String
    ops::Vector{JumpOp}
    slot::Union{Nothing,Int}   # the algebraic slot holding its time; nothing: drawn times
    text::String
    index::Int                 # a disruption's index, -1 for packages
end
