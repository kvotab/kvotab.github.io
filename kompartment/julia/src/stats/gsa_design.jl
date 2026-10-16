# The designs of the global sensitivity methods: the Python package's
# `build_design` and the builders behind it, in `kompartment/stats/gsa.py` and
# `kompartment/stats/salib.py` (the application's `src/domain/gsa.js` and
# `salib.js`).
#
# A design is the runs a method asks for, each a probability per input:
# Morris's walks or trajectories, the radial design, Saltelli's design for
# Sobol, eFAST's curves, RBD-FAST's random balance, a two-level fractional
# factorial, DGSM's base points and steps, Shapley's orders and conditional
# draws. A probabilistic run reads each probability through its input's
# distribution and runs the model at every point (`design_for`). What is read
# off the outputs -- the indices -- is the page's, or the Python package's.
#
# **Python's numbers.** The streams and the columns of uniforms are the
# application's (sample.jl), every sum is added in Python's order, and sin,
# cos, asin and log are the C library's, as numpy calls them, so a design here
# is Python's to the last bit. V8's sin, cos and asin can differ from those in
# the last bit; the page checks the points an engine ran against its own design
# to a billionth.
#
# A design is a dictionary with Python's keys (`"method"`, `"K"`, `"runs"`,
# `"options"`, `"seed"`, ...); `"u"` is K × runs, row k input k's
# probabilities. Positions inside a design (a Shapley order, an RBD-FAST
# permutation) count from 0, as Python's do.

const _GD_PI = 3.141592653589793

"""`ToInt32`, as a store into an `Int32Array` does it."""
function _gd_int32(v::Float64)
    isfinite(v) || return 0
    r = rem(trunc(v), 4294967296.0)
    r < 0 && (r += 4294967296.0)
    return r >= 2147483648.0 ? Int(r - 4294967296.0) : Int(r)
end

"""`Math.round`: the nearest whole number, halves up."""
function _gd_round(x::Float64)
    isfinite(x) || return x
    f = floor(x)
    return x - f >= 0.5 ? f + 1 : f
end

"""A whole number as an `Int` where it is one, as Python's arithmetic keeps it."""
_gd_whole(v::Float64) = isfinite(v) && v == floor(v) && abs(v) < 9.0e15 ? Int(v) : v

"""`Number.isInteger`."""
_gd_is_integer(v) = v isa Integer && !(v isa Bool) || (v isa AbstractFloat && isfinite(v) && v == floor(v))

"""`sin(pi x)`, reduced exactly first, as Julia's `sinpi` (and Python's `sinpi`)."""
function gsa_sinpi(x::Float64)
    isfinite(x) || return NaN
    r = rem(x, 2.0)
    r < 0 && (r += 2)
    r < 0.25 && return csin(_GD_PI * r)
    r < 0.75 && return ccos(_GD_PI * (r - 0.5))
    r < 1.25 && return -csin(_GD_PI * (r - 1))
    r < 1.75 && return -ccos(_GD_PI * (r - 1.5))
    return csin(_GD_PI * (r - 2))
end

"""`n` evenly spaced from `a` to `b`, both included."""
function _gd_linspace(a::Float64, b::Float64, n::Int)
    n <= 0 && return Float64[]
    n == 1 && return [a]
    step = (b - a) / (n - 1)
    out = Float64[a + Float64(i) * step for i in 0:n-1]
    out[n] = b
    return out
end

"""A uniformly random permutation of 0..n-1, Fisher-Yates from the end."""
function gsa_random_permutation(n::Integer, g::Mulberry32)
    p = collect(0:Int(n)-1)
    for i in length(p)-1:-1:1
        j = floor(Int, next_uniform!(g) * (i + 1))
        p[i+1], p[j+1] = p[j+1], p[i+1]
    end
    return p
end

"""A standard normal from two uniforms, Box-Muller; the stream decides both."""
function _gd_gaussian(g::Mulberry32)
    u = next_uniform!(g)
    while !(u > 0)
        u = next_uniform!(g)
    end
    v = next_uniform!(g)
    return sqrt(-2 * clog(u)) * ccos((2 * _GD_PI) * v)
end

"""Every permutation of 0..n-1, in lexicographic order, as Combinatorics' `permutations`."""
function gsa_permutations(n::Integer)
    out = Vector{Int}[]
    a = collect(0:Int(n)-1)
    while true
        push!(out, copy(a))
        i = n - 2
        while i >= 0 && a[i+1] >= a[i+2]
            i -= 1
        end
        i < 0 && return out
        j = n - 1
        while a[j+1] <= a[i+1]
            j -= 1
        end
        a[i+1], a[j+1] = a[j+1], a[i+1]
        reverse!(a, i + 2, n)
    end
end

# --- the methods' settings ------------------------------------------------------------------

"""
The settings of each method, `(key, default, kind)` with the choices of a
`:choice`, in the order the application lists them; a default that is a
function is worked out from the number of inputs.
"""
const GSA_METHODS = OrderedDict{String,Vector{Tuple{String,Any,Symbol,Vector{String}}}}(
    "morris" => [("design", "walks", :choice, ["walks", "trajectories"]), ("trajectories", 10, :int, String[]),
                 ("points", 10, :int, String[]), ("levels", 100, :int, String[]), ("candidates", 0, :int, String[]),
                 ("relative", false, :switch, String[]), ("resamples", 100, :int, String[])],
    "sobol" => [("samples", 1000, :int, String[]), ("second", false, :switch, String[]), ("blocks", 1, :int, String[]),
                ("estimator", "jansen1999", :choice, ["jansen1999", "sobol2007", "homma1996", "janon2014"]),
                ("resamples", 100, :int, String[])],
    "efast" => [("samples", 1000, :int, String[]), ("harmonics", 4, :int, String[])],
    "rbdfast" => [("samples", 1000, :int, String[]), ("harmonics", 6, :int, String[])],
    "ff" => [("low", 0.05, :number, String[]), ("high", 0.95, :number, String[]), ("pairs", false, :switch, String[])],
    "dgsm" => [("samples", 100, :int, String[]), ("step", 0.001, :number, String[]),
               ("crossed", false, :switch, String[]), ("resamples", 100, :int, String[])],
    "radial" => [("samples", 100, :int, String[]), ("resamples", 100, :int, String[])],
    # Song, Nelson and Staum's advice: over random orders, one outer sample and
    # three inner ones; over all of them (K!, affordable to four), more outer samples.
    "shapley" => [("perms", K -> K <= 4 ? 0 : 100, :int, String[]), ("nVar", 1000, :int, String[]),
                  ("nOuter", K -> K <= 4 ? 10 : 1, :int, String[]), ("nInner", 3, :int, String[])],
)

"""
    gsa_options(method, K, given=nothing) -> OrderedDict

A method's settings with every one filled in: what `given` says where it can be
read, the default elsewhere. A switch is read for its truth, a choice must be
one of its values, and a number is read as JavaScript's `Number()` reads it (an
`int` rounded); anything else takes the default.
"""
function gsa_options(method, K::Integer, given=nothing)
    out = OrderedDict{String,Any}()
    spec = method isa AbstractString ? get(GSA_METHODS, method, nothing) : nothing
    spec === nothing && return out
    for (key, default, kind, choices) in spec
        want = given isa AbstractDict ? get(given, key, nothing) : nothing
        d = default isa Function ? default(Int(K)) : default
        if kind === :switch
            out[key] = want === nothing ? d : _pd_truthy(want)
        elseif kind === :choice
            out[key] = want isa AbstractString && want in choices ? String(want) : d
        else
            v = want === nothing || (want isa AbstractString && isempty(want)) ? NaN : _pd_to_number(want)
            out[key] = isfinite(v) ? (kind === :int ? _gd_whole(_gd_round(v)) : v) : d
        end
    end
    return out
end

"""`n!` in floating point, multiplied as the application's recursion multiplies it."""
function _gd_factorial(n::Integer)
    f = 1.0
    for i in 2:n
        f = i * f
    end
    return f
end

"""
    gsa_runs(method, K, options=nothing) -> Number

How many runs a design of `method` over `K` inputs is, before any is made (0
for a method there is not).
"""
function gsa_runs(method, K::Integer, options=nothing)
    o = gsa_options(method, K, options)
    if method == "morris"
        return o["trajectories"] * (o["design"] == "trajectories" ? K + 1 : o["points"])
    elseif method == "radial"
        return o["samples"] * (K + 1)
    elseif method == "sobol"
        return o["blocks"] * (o["second"] ? 2K + 2 : K + 2) * o["samples"]
    elseif method == "efast"
        return K * efast_samples(o["samples"], o["harmonics"])
    elseif method == "rbdfast"
        return o["samples"]
    elseif method == "ff"
        k2 = 2
        while k2 < K
            k2 *= 2
        end
        return 2k2
    elseif method == "dgsm"
        return o["samples"] * (1 + K + (o["crossed"] ? (K * (K - 1)) ÷ 2 : 0))
    elseif method == "shapley"
        orders = o["perms"] > 0 ? o["perms"] : _gd_factorial(K)
        return _gd_whole(Float64(o["nVar"] + orders * (K - 1) * o["nOuter"] * o["nInner"]))
    end
    return 0
end

"""
    gsa_refusal(method, K, options=nothing) -> Union{String,Nothing}

Why a design cannot be made as asked, in a sentence, or `nothing`.
"""
function gsa_refusal(method, K::Integer, options=nothing)
    o = gsa_options(method, K, options)
    (method isa AbstractString && haskey(GSA_METHODS, method)) ||
        return "There is no method called $(_pd_js_str(method))."
    K < 1 && return "Nothing is sampled, so there is nothing to vary."
    positive(v) = _gd_is_integer(v) && v >= 1
    if method == "morris"
        if !positive(o["trajectories"]) || !(o["points"] >= 2) || !(o["levels"] >= 2)
            return "Morris needs at least one trajectory of two points, over at least two levels."
        end
        if o["design"] == "trajectories" && 0 < o["candidates"] < o["trajectories"]
            return "Fewer candidates than trajectories to keep; 0 keeps every one drawn."
        end
    elseif method == "radial"
        o["samples"] >= 2 || return "The radial design needs at least two base points."
    elseif method == "sobol"
        (o["samples"] >= 2 && positive(o["blocks"])) || return "Sobol needs at least two samples and one block."
        (o["blocks"] > 1 && o["blocks"] > o["samples"]) && return "More blocks than samples."
    elseif method == "efast" || method == "rbdfast"
        (o["samples"] >= 8 && positive(o["harmonics"])) || return "This needs at least a few samples and one harmonic."
        (method == "rbdfast" && 2 * o["harmonics"] >= o["samples"] / 2) && return "Too many harmonics for so few samples."
    elseif method == "ff"
        (o["low"] > 0 && o["high"] < 1 && o["low"] < o["high"]) ||
            return "The two levels must be probabilities, the low one below the high."
    elseif method == "dgsm"
        o["samples"] >= 2 || return "DGSM needs at least two points."
        (o["step"] > 0 && o["step"] < 0.5) || return "The step must be a small probability."
    elseif method == "shapley"
        if o["perms"] <= 0 && K > 8
            k = _pd_js_str(K)
            return "All $(k)! orders of $k inputs is too many; give a number of random orders."
        end
        (o["nVar"] >= 2 && positive(o["nOuter"]) && o["nInner"] >= 2) ||
            return "Shapley needs at least two variance samples, one outer and two inner samples."
    end
    return nothing
end

# --- Morris: GlobalSensitivity.jl's random walks, and Morris's own trajectories -------------

"""
GlobalSensitivity.jl's Morris design: `trajectories` random walks of `points`
runs. Each walk starts at a random level of each input and every step moves one
input, chosen at random, one level up or down on a grid of `levels`, bouncing
off the ends. Levels sit at the middles of equal slices of probability.
"""
function morris_design(K::Int; trajectories::Int=10, points::Int=10, levels::Int=100, next::Mulberry32)
    levels >= 2 || throw(ArgumentError("Morris needs at least two levels."))
    points >= 2 || throw(ArgumentError("A Morris trajectory needs at least two points."))
    runs = trajectories * points
    u = zeros(K, runs)
    at = zeros(Int, K)
    for t in 0:trajectories-1
        for k in 1:K
            at[k] = _gd_int32(floor(next_uniform!(next) * levels))
        end
        for s in 0:points-1
            j = floor(Int, next_uniform!(next) * K)
            step = next_uniform!(next) < 0.5 ? -1 : 1
            if 0 <= j < K
                at[j+1] = _gd_int32(Float64(at[j+1] + step))
                if at[j+1] > levels - 1
                    at[j+1] -= 2
                elseif at[j+1] < 0
                    at[j+1] += 2
                end
            end
            for k in 1:K
                u[k, t*points+s+1] = (at[k] + 0.5) / levels
            end
        end
    end
    return OrderedDict{String,Any}("method" => "morris", "K" => K, "trajectories" => trajectories,
                                   "points" => points, "levels" => levels, "u" => u, "runs" => runs)
end

"""
One trajectory, in levels (0 to `p - 1`): `K + 1` rows of `K`. Each input moves
once, in a random order and a random direction, by half the levels, from a
start in the lower half (or the upper, for a step down). The draws: the order
(Fisher-Yates from the end), then the directions, then the starts.
"""
function morris_trajectory(K::Int, p::Int, g::Mulberry32)
    half = p ÷ 2
    order = collect(1:K)
    for i in K-1:-1:1
        j = floor(Int, next_uniform!(g) * (i + 1))
        order[i+1], order[j+1] = order[j+1], order[i+1]
    end
    direction = Int[next_uniform!(g) < 0.5 ? -1 : 1 for _ in 1:K]
    at = Int[floor(Int, next_uniform!(g) * half) for _ in 1:K]
    for k in 1:K
        direction[k] < 0 && (at[k] += half)
    end
    rows = Matrix{Int}(undef, K + 1, K)
    rows[1, :] = at
    for (r, k) in enumerate(order)
        at[k] += direction[k] * half
        rows[r+1, :] = at
    end
    return rows
end

"""
SALib's distance between two trajectories: every point of one to every point of
the other, summed, held in single precision as SALib holds its distance matrix
(so that a tie is broken where SALib breaks it); zero for two the same.
"""
function trajectory_distance(a::AbstractMatrix, b::AbstractMatrix)
    s = 0.0
    for ra in axes(a, 1), rb in axes(b, 1)
        q = 0.0
        for k in axes(a, 2)
            t = Float64(a[ra, k]) - Float64(b[rb, k])
            q += t * t
        end
        s += sqrt(q)
    end
    return a == b ? 0.0 : Float64(Float32(s))
end

"""SALib's `sum_distances` of a set of candidates: the root of the summed squared pair distances."""
function _gd_spread(set::AbstractVector{Int}, D::Matrix{Float64})
    s = 0.0
    for x in 1:length(set), y in x+1:length(set)
        v = D[set[x], set[y]]
        s += v * v
    end
    return sqrt(s)
end

"""The position of the largest, the last of equals, as numpy's `argsort()[-1]` has it."""
function _gd_last_max(values::AbstractVector)
    best = 1
    for i in 2:length(values)
        values[i] >= values[best] && (best = i)
    end
    return best
end

"""
The `k` most spread-out of the candidate trajectories, SALib's
`LocalOptimisation` (Ruano et al. 2012): which candidates, counted from 1,
ascending; every one when `k` is not below their number.
"""
function optimal_trajectories(candidates::AbstractVector, k::Int)
    N = length(candidates)
    k >= N && return collect(1:N)
    D = zeros(N, N)
    for j in 1:N, l in j+1:N
        d = trajectory_distance(candidates[j], candidates[l])
        D[j, l] = d
        D[l, j] = d
    end
    by_row = [_cr_argsort(D[r, :]) for r in 1:N]
    tried = Vector{Int}[]
    scores = Float64[]
    for i in 1:k-1
        # Each row's i farthest, and the row itself.
        sets = [vcat(reverse(by_row[r][N-i+1:N]), r) for r in 1:N]
        best = sets[_gd_last_max([_gd_spread(s, D) for s in sets])]
        for _ in 1:k-i-1
            grown = [vcat(best, c) for c in 1:N if !(c in best)]
            best = grown[_gd_last_max([_gd_spread(s, D) for s in grown])]
        end
        push!(tried, best)
        push!(scores, _gd_spread(best, D))
    end
    isempty(tried) && throw(ArgumentError("Fewer than two trajectories to keep among the candidates."))
    return sort(tried[_gd_last_max(scores)])
end

"""
A design of Morris trajectories, `K + 1` runs each, at the middles of the level
slices; with `candidates` above the number wanted, that many are drawn and the
most spread out kept.
"""
function morris_trajectory_design(K::Int; trajectories::Int=10, levels::Int=4, candidates::Int=0, next::Mulberry32)
    p = max(2, 2 * Int(_gd_round(levels / 2)))
    drawn = max(trajectories, candidates)
    everyone = [morris_trajectory(K, p, next) for _ in 1:drawn]
    keep = drawn > trajectories ? optimal_trajectories(everyone, trajectories) : collect(1:drawn)
    points = K + 1
    u = zeros(K, length(keep) * points)
    for (t, which) in enumerate(keep)
        rows = everyone[which]
        for r in 1:points, k in 1:K
            u[k, (t-1)*points+r] = (rows[r, k] + 0.5) / p
        end
    end
    return OrderedDict{String,Any}("method" => "morris", "design" => "trajectories", "K" => K,
                                   "trajectories" => length(keep), "points" => points, "levels" => p,
                                   "candidates" => drawn, "u" => u, "runs" => length(keep) * points)
end

# --- the radial design, Campolongo, Saltelli and Cariboni 2011 ------------------------------

"""
The radial design: each of `N` base points run as it is, then once per input
moved to its perturbation point; `base` and `step` hold one column of `N`
probabilities per input. `N (K + 1)` runs.
"""
function radial_design(K::Int, base::AbstractVector, step::AbstractVector)
    N = isempty(base) ? 0 : length(base[1])
    per = K + 1
    u = zeros(K, N * per)
    for k in 1:K, i in 0:N-1
        for r in 0:per-1
            u[k, i*per+r+1] = base[k][i+1]
        end
        u[k, i*per+1+k] = step[k][i+1]
    end
    return OrderedDict{String,Any}("method" => "radial", "K" => K, "N" => N, "per" => per, "u" => u,
                                   "runs" => N * per)
end

# --- Sobol: Saltelli's design ----------------------------------------------------------------

"""
Saltelli's design: samples A and B of `n` points, and A with each input's
column from B; with `second`, B with each column from A too, for every pair's
interaction; `blocks` repeats the design. `draw(k, which, block)` gives the `n`
probabilities of input k (from 1) in sample `"A"` or `"B"` of a block (from 0).
"""
function sobol_design(K::Int, n::Int; second::Bool=false, blocks::Int=1, draw)
    per = (second ? 2K + 2 : K + 2) * n
    u = zeros(K, blocks * per)
    place!(k, src, offset) = (u[k, offset+1:offset+n] = src)
    for b in 0:blocks-1
        base = b * per
        for k in 1:K
            A = draw(k, "A", b)
            B = draw(k, "B", b)
            place!(k, A, base)
            place!(k, B, base + n)
            # A with column j from B, for each j; then B with column j from A.
            for j in 1:K
                place!(k, k == j ? B : A, base + (1 + j) * n)
            end
            if second
                for j in 1:K
                    place!(k, k == j ? A : B, base + (1 + K + j) * n)
                end
            end
        end
    end
    return OrderedDict{String,Any}("method" => "sobol", "K" => K, "n" => n, "second" => second, "blocks" => blocks,
                                   "u" => u, "runs" => blocks * per)
end

# --- eFAST and RBD-FAST ----------------------------------------------------------------------

"""The smallest number of points at or above `n` that eFAST can use with `M` harmonics."""
function efast_samples(n, M::Integer)
    N = max(_gd_round(Float64(n)), Float64(4 * M * M + 1))
    (isfinite(N) && M >= 1) || throw(ArgumentError("eFAST needs a number of points and at least one harmonic."))
    N = Int(N)
    while true
        w = fld(N - 1, 2M)
        (fld(w, 2M) >= 1 && M * w <= fld(N, 2) - 1) && return N
        N += 1
    end
end

"""omega_1 and the complementary frequencies, as GlobalSensitivity.jl chooses them."""
function efast_frequencies(K::Int, N::Int, M::Int)
    K < 1 && throw(ArgumentError("eFAST needs an input."))
    omega = Float64[floor((N - 1) / (2M))]
    m = floor(omega[1] / (2M))
    if m >= K - 1
        # floor.(Int, range(1, m, length = K - 1))
        r = K - 1 == 1 ? [1.0] : Float64[1 + (i * (m - 1)) / (K - 2) for i in 0:K-2]
        append!(omega, floor.(r))
    else
        append!(omega, Float64[m != 0 ? rem(i, m) + 1 : NaN for i in 0:K-2])
    end
    return omega
end

"""
The eFAST design: `N` points along one curve per input, `K N` runs. Along curve
i input i oscillates at omega_1 and every other at a lower frequency; `phases`
holds one phase per curve, in [0, 2).
"""
function efast_design(K::Int, N::Int; harmonics::Int=4, phases::AbstractVector{Float64})
    omega = efast_frequencies(K, N, harmonics)
    u = zeros(K, K * N)
    temp = zeros(K)
    s = Float64[(2 / N) * r for r in 0:N-1]
    for i in 1:K
        temp[i] = omega[1]
        for k in 1:i-1
            temp[k] = omega[k+1]
        end
        for k in i+1:K
            temp[k] = omega[k]
        end
        phi0 = phases[i]
        for j in 1:K, r in 1:N
            u[j, (i-1)*N+r] = 0.5 + (1 / _GD_PI) * casin(gsa_sinpi(temp[j] * s[r] + phi0))
        end
    end
    return OrderedDict{String,Any}("method" => "efast", "K" => K, "N" => N, "harmonics" => harmonics,
                                   "omega" => omega, "u" => u, "runs" => K * N)
end

"""
The random balance design: one periodic curve of `N` runs, each input along it
in its own order; `perms` holds one random permutation of 0..N-1 per input.
"""
function rbd_fast_design(K::Int, N::Int; perms::AbstractVector)
    s0 = _gd_linspace(-_GD_PI, _GD_PI, N)
    s = zeros(K, N)
    u = zeros(K, N)
    for k in 1:K, i in 1:N
        sk = s0[perms[k][i]+1]
        s[k, i] = sk
        u[k, i] = 0.5 + casin(csin(sk)) / _GD_PI
    end
    return OrderedDict{String,Any}("method" => "rbdfast", "K" => K, "N" => N, "s" => s, "u" => u, "runs" => N)
end

# --- a two-level fractional factorial of resolution IV (Saltelli 2008, eq. 2.31) -------------

"""A Sylvester-Hadamard matrix of order `k`, a power of two from 2 up."""
function gsa_hadamard(k::Int)
    (k >= 2 && k & (k - 1) == 0) || throw(ArgumentError("A Hadamard matrix of order $k is not a power of two from 2 up"))
    h = ones(Int8, k, k)
    h[2, 2] = -1
    bot = right = 2
    while bot < k
        blk = h[1:bot, 1:right]
        h[1:bot, right+1:2right] = blk
        h[bot+1:2bot, 1:right] = blk
        h[bot+1:2bot, right+1:2right] = -blk
        bot *= 2
        right *= 2
    end
    return h
end

"""
The fractional factorial: the columns of a Hadamard matrix and of its negative,
each input low or high; `2^ceil(log2 K) * 2` runs (4 for up to two inputs).
"""
function ff_design(K::Int; low::Float64=0.05, high::Float64=0.95)
    k2 = 2
    while k2 < K
        k2 *= 2
    end
    H = gsa_hadamard(k2)
    rows = 2k2
    signs = vcat(H, -H)
    u = Float64[signs[r, k] > 0 ? high : low for k in 1:K, r in 1:rows]
    return OrderedDict{String,Any}("method" => "ff", "K" => K, "rows" => rows, "signs" => signs, "low" => low,
                                   "high" => high, "u" => u, "runs" => rows)
end

# --- DGSM: Sobol and Kucherenko's derivative-based measures -----------------------------------

"""
The DGSM design: each base point, then one step along each input (and each
pair with `crossed`); `base` holds one column of `N` probabilities per input.
The step is in probability, forward except where that would leave (0, 1).
`K + 1` runs a point, `K (K - 1) / 2` more with `crossed`.
"""
function dgsm_design(K::Int, base::AbstractVector; step::Float64=1e-3, crossed::Bool=false)
    N = isempty(base) ? 0 : length(base[1])
    per = 1 + K + (crossed ? (K * (K - 1)) ÷ 2 : 0)
    # h[i * K + k]: the step input k takes at point i
    h = Float64[base[k][i] + step < 1 ? step : -step for k in 1:K, i in 1:N]
    u = zeros(K, N * per)
    for k in 1:K, i in 0:N-1, r in 0:per-1
        u[k, i*per+r+1] = base[k][i+1]
    end
    for k in 1:K, i in 0:N-1
        u[k, i*per+1+k] += h[k, i+1]
    end
    if crossed
        p = 1 + K
        for a in 1:K, c in a+1:K
            for i in 0:N-1
                u[a, i*per+p+1] += h[a, i+1]
                u[c, i*per+p+1] += h[c, i+1]
            end
            p += 1
        end
    end
    return OrderedDict{String,Any}("method" => "dgsm", "K" => K, "N" => N, "per" => per, "step" => step,
                                   "crossed" => crossed, "h" => vec(h), "u" => u, "runs" => N * per)
end

# --- Shapley effects: Song, Nelson and Staum's algorithm --------------------------------------

"""
    gsa_cholesky(A, n) -> Union{Vector{Float64},Nothing}

The lower Cholesky factor of a symmetric matrix (row-major, `n * n` long; only
its lower triangle is read), row-major and flat too, or `nothing` if it is not
positive definite: a pivot not above 1e-14. Each entry is `(A[i][j] - sum_l
L[i][l] L[j][l]) / L[j][j]`, the terms subtracted in order.
"""
function gsa_cholesky(A::AbstractVector{Float64}, n::Int)
    L = zeros(n * n)
    for j in 0:n-1, i in j:n-1
        s = A[i*n+j+1]
        for l in 0:j-1
            s -= L[i*n+l+1] * L[j*n+l+1]
        end
        if i == j
            s > 1e-14 || return nothing
            L[j*n+j+1] = sqrt(s)
        else
            L[i*n+j+1] = s / L[j*n+j+1]
        end
    end
    return L
end

"""A Cholesky factor of a matrix that is positive semi-definite but not quite definite."""
function _gd_jitter_cholesky(A::Vector{Float64}, n::Int)
    eps = 1e-12
    while eps < 1
        B = copy(A)
        for i in 0:n-1
            B[i*n+i+1] += eps
        end
        L = gsa_cholesky(B, n)
        L === nothing || return L
        eps *= 10
    end
    throw(ArgumentError("A conditional covariance could not be factorised."))
end

"""The inputs' joint law in probability space: independent, or a Gaussian copula."""
struct _GDCopula
    K::Int
    corr::Union{Nothing,Vector{Float64}}
    next::Mulberry32
    cache::Dict{Vector{Int},Union{Nothing,Vector{Float64}}}
end
_GDCopula(K, corr, next) = _GDCopula(K, corr === nothing ? nothing : Vector{Float64}(corr), next,
                                     Dict{Vector{Int},Union{Nothing,Vector{Float64}}}())

_gd_sub(law::_GDCopula, idx) = Float64[law.corr[a*law.K+b+1] for a in idx for b in idx]

"""z ~ N(mu, L L')."""
function _gd_draw_z(law::_GDCopula, m::Int, L::Vector{Float64}, mu)
    e = Float64[_gd_gaussian(law.next) for _ in 1:m]
    z = zeros(m)
    for a in 0:m-1
        s = mu === nothing ? 0.0 : mu[a+1]
        for b in 0:a
            s += L[a*m+b+1] * e[b+1]
        end
        z[a+1] = s
    end
    return z
end

"""`n` draws of the inputs `idx` (from 0) from their joint marginal, a row each."""
function _gd_subset(law::_GDCopula, idx::Vector{Int}, n::Int)
    if law.corr === nothing
        return [Float64[next_uniform!(law.next) for _ in idx] for _ in 1:n]
    end
    L = get!(law.cache, idx) do
        gsa_cholesky(_gd_sub(law, idx), length(idx))
    end
    L === nothing && throw(ArgumentError("The correlations between these inputs are not a valid correlation matrix."))
    return [normal_phi.(_gd_draw_z(law, length(idx), L, nothing)) for _ in 1:n]
end

"""`n` draws of the inputs `plus` given `minus` (from 0) at the probabilities `u_minus`."""
function _gd_given(law::_GDCopula, plus::Vector{Int}, minus::Vector{Int}, u_minus::Vector{Float64}, n::Int)
    if law.corr === nothing
        return [Float64[next_uniform!(law.next) for _ in plus] for _ in 1:n]
    end
    # GlobalSensitivity.jl's find_cond_mean_var: B - C'D^-1 C, and C'D^-1
    # times the conditioning values as normal scores.
    corr, K = law.corr, law.K
    p, q = length(plus), length(minus)
    z_minus = Float64[normal_quantile(v) for v in u_minus]
    Ld = gsa_cholesky(_gd_sub(law, minus), q)
    Ld === nothing && throw(ArgumentError("The correlations between these inputs are not a valid correlation matrix."))
    # Solve D X = C for X = D^-1 C, one column per member of `plus`.
    X = zeros(q * p)
    for c in 0:p-1
        col = Float64[corr[minus[r+1]*K+plus[c+1]+1] for r in 0:q-1]
        w = zeros(q)
        for r in 0:q-1
            s = col[r+1]
            for l in 0:r-1
                s -= Ld[r*q+l+1] * w[l+1]
            end
            w[r+1] = s / Ld[r*q+r+1]
        end
        for r in q-1:-1:0
            s = w[r+1]
            for l in r+1:q-1
                s -= Ld[l*q+r+1] * X[l*p+c+1]
            end
            X[r*p+c+1] = s / Ld[r*q+r+1]
        end
    end
    mu = zeros(p)
    cov = zeros(p * p)
    for a in 0:p-1
        s = 0.0
        for r in 0:q-1
            s += X[r*p+a+1] * z_minus[r+1]
        end
        mu[a+1] = s
        for b in 0:p-1
            c = corr[plus[a+1]*K+plus[b+1]+1]
            for r in 0:q-1
                c -= corr[minus[r+1]*K+plus[a+1]+1] * X[r*p+b+1]
            end
            cov[a*p+b+1] = c
        end
    end
    # Symmetrised, and a variance rounding made a hair negative is zero.
    for a in 0:p-1, b in a+1:p-1
        v = (cov[a*p+b+1] + cov[b*p+a+1]) / 2
        cov[a*p+b+1] = v
        cov[b*p+a+1] = v
    end
    L = gsa_cholesky(cov, p)
    L === nothing && (L = _gd_jitter_cholesky(cov, p))
    return [normal_phi.(_gd_draw_z(law, p, L, mu)) for _ in 1:n]
end

"""
Song, Nelson and Staum's design for Shapley effects: `n_var` points for the
output's variance, then for each order of the inputs -- all `K!` of them with
`perms = -1`, or `perms` random ones -- and each step along it, `n_outer`
conditioning points with `n_inner` conditional draws each. With `corr`, a K x K
correlation matrix of the normal scores (row-major), the inputs are drawn from
a Gaussian copula and every conditional draw respects it.
"""
function shapley_design(K::Int; perms::Int=-1, n_var::Int, n_outer::Int, n_inner::Int=3, corr=nothing,
                        next::Mulberry32)
    perms < -1 && throw(ArgumentError("Invalid array length"))
    orders = perms == -1 ? gsa_permutations(K) : [gsa_random_permutation(K, next) for _ in 1:perms]
    law = _GDCopula(K, corr, next)
    runs = n_var + length(orders) * (K - 1) * n_outer * n_inner
    u = zeros(K, max(0, runs))
    at = 1
    for row in _gd_subset(law, collect(0:K-1), n_var)
        u[:, at] = row
        at += 1
    end
    for perm in orders, j in 1:K-1
        plus = perm[1:j]
        minus = perm[j+1:end]
        for fixed in _gd_subset(law, minus, n_outer)
            for drawn in _gd_given(law, plus, minus, fixed, n_inner)
                u[plus.+1, at] = drawn
                u[minus.+1, at] = fixed
                at += 1
            end
        end
    end
    return OrderedDict{String,Any}("method" => "shapley", "K" => K, "orders" => orders, "nVar" => n_var,
                                   "nOuter" => n_outer, "nInner" => n_inner, "correlated" => corr !== nothing,
                                   "u" => u, "runs" => runs)
end

# --- a design from a run's seed ---------------------------------------------------------------

"""
    build_design(method, keys, options=nothing; seed=1, corr=nothing) -> OrderedDict

A method's design, drawn from a run's seed, with its settings (`"options"`) and
`"seed"` recorded. `keys` names each input, for its streams: every column a
method samples freely comes from a stream named after the input it belongs to,
Latin hypercube, as a probabilistic run draws, so the same seed gives an input
the same numbers whichever other inputs are in the model. The walks, the
orders and the conditional draws have one stream each (`#gsa#morris`,
`#gsa#shapley`). `corr` reaches Shapley only. Throws the reason when the
design cannot be made as asked.
"""
function build_design(method, keys::AbstractVector, options=nothing; seed=1, corr=nothing)
    K = length(keys)
    o = gsa_options(method, K, options)
    refused = gsa_refusal(method, K, o)
    refused === nothing || throw(ArgumentError(refused))
    names = String[_pd_js_str(k) for k in keys]
    col(name, n) = uniforms(n, stream_for(seed, name); latin=true)
    d = if method == "morris"
        nxt = stream_for(seed, "#gsa#morris")
        o["design"] == "trajectories" ?
            morris_trajectory_design(K; trajectories=o["trajectories"], levels=o["levels"],
                                     candidates=o["candidates"], next=nxt) :
            morris_design(K; trajectories=o["trajectories"], points=o["points"], levels=o["levels"], next=nxt)
    elseif method == "radial"
        radial_design(K, [col("$k#radial#base", o["samples"]) for k in names],
                      [col("$k#radial#step", o["samples"]) for k in names])
    elseif method == "sobol"
        sobol_design(K, o["samples"]; second=o["second"], blocks=o["blocks"],
                     draw=(k, which, b) -> col("$(names[k])#sobol#$which#$b", o["samples"]))
    elseif method == "efast"
        N = efast_samples(o["samples"], o["harmonics"])
        phases = Float64[2 * next_uniform!(stream_for(seed, "$k#efast")) for k in names]
        efast_design(K, N; harmonics=o["harmonics"], phases)
    elseif method == "rbdfast"
        rbd_fast_design(K, o["samples"];
                        perms=[gsa_random_permutation(o["samples"], stream_for(seed, "$k#rbdfast")) for k in names])
    elseif method == "ff"
        ff_design(K; low=Float64(o["low"]), high=Float64(o["high"]))
    elseif method == "dgsm"
        dgsm_design(K, [col("$k#dgsm", o["samples"]) for k in names]; step=Float64(o["step"]), crossed=o["crossed"])
    else    # shapley: gsa_refusal has turned away any other name
        shapley_design(K; perms=o["perms"] > 0 ? o["perms"] : -1, n_var=o["nVar"], n_outer=o["nOuter"],
                       n_inner=o["nInner"], corr, next=stream_for(seed, "#gsa#shapley"))
    end
    d["options"] = o
    # What the intervals are drawn from, so that reading the table again gives the same one.
    d["seed"] = seed
    return d
end
