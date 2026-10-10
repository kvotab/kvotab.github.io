# Radionuclide data: half-lives, elements and the decay chains between them.
#
# ICRP Publication 107 as Kompartment carries it (`data/icrp107.json`). Worked
# out from it, the way the application works them out: a nuclide's half-life
# in years (Inf for a stable one, `nothing` for a name the table does not
# know), its element, and the decay pairs among a set of nuclides when a model
# states none -- each modelled nuclide's daughters, with the branching that
# reaches them through the members that are not modelled (`collapse` in
# src/domain/decaydb.js).

const STABLE = "stable"

struct NuclideRow
    half_life::Float64
    progeny::Vector{Tuple{String,Float64}}
end

const ICRP107 = let
    data = parse_json(read(joinpath(@__DIR__, "..", "..", "data", "icrp107.json"), String))
    table = OrderedDict{String,NuclideRow}()
    for row in data["nuclides"]
        name, half, progeny = row[1], row[2], row[3]
        table[name] = NuclideRow(half === nothing ? Inf : Float64(half),
                                 [(String(p[1]), Float64(p[2])) for p in progeny])
    end
    table
end

known_nuclides() = collect(keys(ICRP107))
is_known_nuclide(name) = haskey(ICRP107, name)

"""Half-life in years; Inf when stable, `nothing` when unknown."""
function half_life(name)
    row = get(ICRP107, name, nothing)
    return row === nothing ? nothing : row.half_life
end

"""Whether a half-life as a file may write it means "does not decay"."""
means_stable(v::AbstractFloat) = isinf(v)
means_stable(v::AbstractString) = occursin(r"^(stable|inf(inity)?)$"i, strip(v))
means_stable(v) = false

const _SYMBOL = r"^([A-Za-z]{1,3})(?=$|[-\s0-9])"

"""The element symbol of a nuclide's name (`Cs-137` -> `Cs`), or `nothing`."""
function element_of(nuclide)
    m = match(_SYMBOL, strip(string(something(nuclide, ""))))
    m === nothing && return nothing
    s = m.captures[1]
    return uppercase(s[1:1]) * lowercase(s[2:end])
end

function _distribution(name, keep::Set{String}, memo::Dict{String,OrderedDict{String,Float64}}, ceiling::Float64)
    hit = get(memo, name, nothing)
    hit !== nothing && return hit
    out = OrderedDict{String,Float64}()
    memo[name] = out  # before the walk, so a cycle cannot recurse forever
    row = get(ICRP107, name, nothing)
    row === nothing && return out
    for (daughter, branching) in row.progeny
        if daughter in keep
            out[daughter] = get(out, daughter, 0.0) + branching
            continue
        end
        half = half_life(daughter)
        (half === nothing || isinf(half)) && continue   # the activity leaves the chain
        half > ceiling && continue                       # a sink within any assessment's span
        for (target, share) in _distribution(daughter, keep, memo, ceiling)
            out[target] = get(out, target, 0.0) + branching * share
        end
    end
    return out
end

"""
    default_chains(nuclides; ceiling=Inf, min_branching=1e-9) -> Vector{Tuple{String,String,Float64}}

The decay pairs a set of nuclides makes, `(parent, daughter, branching)`,
the branching being the total probability that one decay of the parent
reaches the daughter through nuclides that are not in the set. A daughter
longer-lived than `ceiling` years is a sink rather than passed through.
"""
function default_chains(nuclides; ceiling::Real=Inf, min_branching::Real=1e-9)
    keep = Set{String}(n for n in nuclides if haskey(ICRP107, n))
    memo = Dict{String,OrderedDict{String,Float64}}()
    pairs = Tuple{String,String,Float64}[]
    for name in keys(ICRP107)          # the table's order, whatever order was asked for
        name in keep || continue
        for (daughter, branching) in _distribution(name, keep, memo, Float64(ceiling))
            branching < min_branching && continue
            push!(pairs, (name, daughter, branching))
        end
    end
    sort!(pairs; by=p -> (locale_key(p[1]), -p[3]))  # stable, as the application's sort is
    return pairs
end
