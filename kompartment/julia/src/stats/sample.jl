# Drawing values from the distributions on a model, as Kompartment draws them:
# the Python package's `kompartment/stats/sample.py` (the application's
# `src/domain/sample.js`).
#
# Everything is an inverse CDF rather than a sampler of its own, which buys
# reproducibility (a run is a seed and nothing else), truncation (the same
# inverse CDF fed a uniform confined to [F(lo), F(hi)]) and Latin hypercube
# sampling (a statement about the uniforms, not the shapes) at once.
#
# **The same numbers as the application.** The generator is mulberry32 and its
# output is bit for bit the application's for the same seed; so is every stream
# (`stream_for`, one per sampled input, seeded from the run's seed and the
# input's name) and every column of uniforms (`uniforms`).

"""
    Mulberry32(seed=1)

A small, fast, seeded generator: mulberry32, the application's. Thirty-two
bits of state stepped by a constant; `next_uniform!(g)` is the next number in
[0, 1), exactly as the application's `rng(seed)()` gives it. A seed of 0 is
taken as 1.
"""
mutable struct Mulberry32
    a::UInt32
    Mulberry32(seed::UInt32) = new(seed == 0 ? UInt32(1) : seed)
end

const _SM_STEP = 0x6d2b79f5

"""`v >>> 0`: JavaScript's ToUint32."""
function _sm_to_uint32(v)
    x = _pd_to_number(v)
    isfinite(x) || return UInt32(0)
    r = rem(trunc(x), 4294967296.0)
    r < 0 && (r += 4294967296.0)
    return UInt32(r)
end

Mulberry32(seed=1) = Mulberry32(_sm_to_uint32(seed))

"""The next number in [0, 1) from `g`."""
@inline function next_uniform!(g::Mulberry32)
    a = g.a + _SM_STEP
    g.a = a
    t = (a ⊻ (a >> 15)) * (a | 0x00000001)
    t ⊻= t + ((t ⊻ (t >> 7)) * (t | 0x0000003d))
    return Float64(t ⊻ (t >> 14)) / 4294967296.0
end

"""The next `n` numbers from `g`, as `n` calls would give them."""
function take_uniforms!(g::Mulberry32, n::Integer)
    out = Vector{Float64}(undef, max(0, n))
    @inbounds for i in eachindex(out)
        out[i] = next_uniform!(g)
    end
    return out
end

"""FNV-1a over a name's UTF-16 code units, as the application hashes it: a 32-bit integer."""
function fnv_hash(text::AbstractString)
    h = 0x811c9dc5
    for u in transcode(UInt16, String(text))
        h = (h ⊻ UInt32(u)) * 0x01000193
    end
    return h
end

"""Two 32-bit values into one, well enough that neighbours do not collide."""
function _sm_mix(a::UInt32, b::UInt32)
    h = a ⊻ ((b ⊻ (b >> 16)) * 0x85ebca6b)
    h = (h ⊻ (h >> 13)) * 0xc2b2ae35
    return h ⊻ (h >> 16)
end

"""
    stream_for(seed, name) -> Mulberry32

A stream of its own for one named thing: the run's seed mixed with a hash of
the name. `name` is what is drawn for, as the application spells it: the
sampled input's name (`Kd[Tc-99]`), a correlation group's name for its
members, `correlation:<name>` for a correlation's scores,
`<event>#occurrences#<i>` for a disruptive event's dice.
"""
stream_for(seed, name) = Mulberry32(_sm_mix(_sm_to_uint32(seed), fnv_hash(_pd_js_str(_pd_nullish(name) ? "" : name))))

"""
    uniforms(n, g::Mulberry32; latin=true) -> Vector{Float64}

`n` uniforms in (0, 1) from `g`, stratified or not. Latin hypercube (the
default): one from each of `n` equal slices, in an order shuffled by
Fisher-Yates, so the draws cover the range evenly. Otherwise `n` independent
draws. The application's numbers, drawn in its order.
"""
function uniforms(n::Integer, g::Mulberry32; latin::Bool=true)
    n < 0 && throw(ArgumentError("Invalid typed array length: a column cannot hold fewer than no uniforms"))
    latin || return take_uniforms!(g, n)
    first = take_uniforms!(g, n)
    out = Vector{Float64}(undef, n)
    @inbounds for i in 1:n
        out[i] = (Float64(i - 1) + first[i]) / n
    end
    # Fisher-Yates: otherwise every parameter would rise together through the
    # run and the sample would lie on a diagonal.
    if n > 1
        picks = Vector{Int}(undef, n - 1)
        @inbounds for step in 1:n-1
            picks[step] = floor(Int, next_uniform!(g) * Float64(n - step + 1))
        end
        @inbounds for step in 1:n-1
            i = n - step              # from n - 1 down to 1, counted from 0
            j = picks[step]
            out[i+1], out[j+1] = out[j+1], out[i+1]
        end
    end
    return out
end

"""`values[index]` as JavaScript reads it: NaN unless a whole index in range; a number as a double."""
function _sm_element(values, index::Float64)
    (isnan(index) || isinf(index) || index != floor(index)) && return NaN
    i = Int(index)
    (i < 0 || i >= length(values)) && return NaN
    v = values[firstindex(values)+i]
    return v isa Real ? Float64(v) : NaN
end

"""`((spec.pos ?? 0) + at) % length`, with JavaScript's `+` and `%`."""
function _sm_list_index(pos, at::Integer, len::Integer)
    _pd_nullish(pos) && (pos = 0)
    total = pos isa AbstractString ? _pd_string_to_number(pos * _pd_js_number_str(at)) :
            _pd_to_number(pos) + Float64(at)
    isfinite(total) || return NaN
    return rem(total, Float64(len))
end

"""
    value_at_probability(spec, u, at=0) -> Float64

One value from `spec` for the uniform `u`; NaN where the distribution is not
filled in. A list (`pg`) is not drawn from: in order (`inorder`, the default)
it hands out value `(pos + at) % n` to realisation `at` (counted from 0); out
of order it takes the value at `u`. Every other kind is its quantile at `u`
read between the two probabilities its truncation leaves, never exactly 0 or
1, and clamped to a value truncation that the round trip through the CDF
misses by a billionth. A list's values may be any vector of numbers.
"""
function value_at_probability(spec, u, at::Integer=0)
    (!_pd_truthy(spec) || _pd_meta(_pd_prop(spec, "kind")) === nothing || !pdf_complete(spec)) && return NaN
    if spec["kind"] == "pg"
        v = _pd_prop(spec, "values")
        (_pd_nullish(v) || !(v isa AbstractVector) || isempty(v)) && return NaN
        if _pd_prop(spec, "inorder") === false
            x = _pd_to_number(u) * length(v)
            return _sm_element(v, _pd_jmin(Float64(length(v) - 1), isfinite(x) ? floor(x) : x))
        end
        return _sm_element(v, _sm_list_index(_pd_prop(spec, "pos"), at, length(v)))
    end
    # Truncation is the same curve read between two probabilities rather than
    # between 0 and 1 -- never by rejection.
    cuts = probability_cuts(spec)
    lo, hi = cuts.lo, cuts.hi
    q = _pd_jmin(1 - 1e-12, _pd_jmax(1e-12, lo + _pd_to_number(u) * (hi - lo)))
    v = pdf_quantile(spec, q)
    cuts.reversed && return v
    trmin = _pd_prop(spec, "trmin")
    trmax = _pd_prop(spec, "trmax")
    (!_pd_nullish(trmin) && v < _pd_to_number(trmin)) && return _pd_to_number(trmin)
    (!_pd_nullish(trmax) && v > _pd_to_number(trmax)) && return _pd_to_number(trmax)
    return v
end

"""
    distributed_slots(sys::System) -> Vector{JDict}

Every distributed value in a built model and where it lives in `P`: the
lookup-table points that carry a distribution first, named `<table>@<time>`,
then every parameter slot whose distribution (its entry's own or the block's)
is filled in, in the layout's order. Each is `JDict("slot" => offset in P
(from 0), "name", "index" => the index tuple, "spec")`.
"""
function distributed_slots(sys::System)
    b = sys.builder
    out = JDict[]
    for pt in b.point_layout
        spec = get(pt, :spec, nothing)
        (_pd_truthy(spec) && pdf_complete(spec)) || continue
        index = get(pt, :index, nothing)
        push!(out, JDict("slot" => pt[:slot], "name" => "$(_pd_js_str(pt.name))@$(_pd_js_str(pt[:at]))",
                         "index" => index === nothing ? Tup() : index, "spec" => spec))
    end
    space = b.space
    for entry in b.param_layout
        dims = entry.dims
        for off in 0:entry.width-1
            tup = isempty(dims) ? Tup() : tuple_by_list(space, dims, off)
            spec = value_at(entry.block, "pdf", tup)
            (_pd_truthy(spec) && pdf_complete(spec)) || continue
            push!(out, JDict("slot" => entry.base + off, "name" => entry.name, "index" => tup, "spec" => spec))
        end
    end
    return out
end
