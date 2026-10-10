# What a probabilistic run says: bands, summaries, a tornado's table and what
# drove the spread. Ports of the Python package's `kompartment/engine/analysis.py`
# and the parts of `kompartment/stats` it reads (`sensitivity.py`'s
# correlations, regression family and first-order index; `distribution.py`'s
# summary), themselves the application's (`src/worker/sim-worker.js`,
# `src/domain/sensitivity.js`, `src/domain/distribution.js`), in the same
# order of operations, so the numbers are Python's to the last bit.
#
# A varied parameter is a series here too, one value per realisation, after
# the kept ones (the application's `withInputs`), so a table can rank a
# parameter as well as an output. Series and inputs are counted from 1, and a
# time by its position in `t`, from 1. A `mask` (one entry per realisation,
# true or non-zero to use it) screens realisations out, exactly as if they had
# failed. Not ported: the measures that read any sample (`family =
# "distribution"`: EASI, delta, mutual information, RSA, PAWN, discrepancy)
# and the global sensitivity designs' tables.

const PROB_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
const PROB_TRANSLATIONS = ("none", "rank", "log")
const SUMMARY_PERCENTILES = (0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)

# --- the series, with the varied parameters among them -----------------------------------

"""How many series a result reads: the kept ones, then each varied parameter as its draws."""
_an_count(r::ProbabilisticResults) = length(r.outputs) + length(r.inputs)

"""Series `k`'s descriptor."""
_an_output(r::ProbabilisticResults, k::Int) = k <= length(r.outputs) ? r.outputs[k] : r.inputs[k-length(r.outputs)]["output"]

"""Whether series `k` is one value per realisation (a varied parameter), and which input it is (0 for none)."""
_an_flat(r::ProbabilisticResults, k::Int) = k > length(r.outputs)
_an_drawn_from(r::ProbabilisticResults, k::Int) = k <= length(r.outputs) ? 0 : r.inputs[k-length(r.outputs)]["k"]

"""Series `k` as a matrix of doubles, realisations × times (× 1 for a varied parameter, NaN where it did not run)."""
function _an_matrix(r::ProbabilisticResults, k::Int)
    if k <= length(r.outputs)
        M = r.values[k]
        return M isa Matrix{Float64} ? M : Matrix{Float64}(M)
    end
    drawn = Float64[x for x in view(r.samples, _an_drawn_from(r, k), :)]
    for i in eachindex(drawn)
        r.ran[i] == 0 && (drawn[i] = NaN)
    end
    return reshape(drawn, :, 1)
end

"""Which series a label (or a position, from 1) names, among the kept series and the varied parameters."""
function _an_index(r::ProbabilisticResults, label)
    label isa Integer && return Int(label)
    for k in 1:_an_count(r)
        _an_output(r, k)["label"] == label && return k
    end
    throw(KeyError("No series labelled '$label'"))
end

"""Whether realisation `i` is used: always without a mask; `mask[i]` true or non-zero (and not NaN) with one."""
function _an_keep(mask, i::Int)
    mask === nothing && return true
    i > length(mask) && return false
    m = mask[i]
    m isa Bool && return m
    m isa Real || return m !== nothing
    return m != 0 && !isnan(m)
end

# --- one series' statistics at every time --------------------------------------------------

"""The finite values of column `j` of `M` over the realisations kept, ascending."""
function _an_finite_sorted(M::AbstractMatrix, j::Int, mask)
    col = Float64[]
    for i in 1:size(M, 1)
        _an_keep(mask, i) || continue
        v = Float64(M[i, j])
        isfinite(v) && push!(col, v)
    end
    return sort!(col)
end

"""The band at each time: order statistics across the realisations that ran, `x[round(q (n - 1))]`."""
function _an_quantiles(M::AbstractMatrix, qs, mask)
    times = size(M, 2)
    out = [zeros(times) for _ in qs]
    for j in 1:times
        s = _an_finite_sorted(M, j, mask)
        n = length(s)
        for (k, q) in enumerate(qs)
            if n == 0
                out[k][j] = NaN
                continue
            end
            idx = Int(floor(Float64(q) * (n - 1) + 0.5))
            out[k][j] = s[min(n - 1, max(0, idx))+1]
        end
    end
    return out
end

"""The mean at each time of the finite values of the realisations kept, summed in order."""
function _an_mean(M::AbstractMatrix, mask)
    times = size(M, 2)
    out = zeros(times)
    for j in 1:times
        total = 0.0
        n = 0
        for i in 1:size(M, 1)
            _an_keep(mask, i) || continue
            v = Float64(M[i, j])
            if isfinite(v)
                total += v
                n += 1
            end
        end
        out[j] = n > 0 ? total / n : NaN
    end
    return out
end

"""The median's 95% interval and the body's (15.9% to 84.1%) at each time."""
function _an_median_spread(M::AbstractMatrix, z::Float64, mask)
    times = size(M, 2)
    err_lo, err_hi, body_lo, body_hi = zeros(times), zeros(times), zeros(times), zeros(times)
    for j in 1:times
        s = _an_finite_sorted(M, j, mask)
        n = length(s)
        if n == 0
            err_lo[j] = err_hi[j] = body_lo[j] = body_hi[j] = NaN
            continue
        end
        at(k) = s[min(n - 1, max(0, k))+1]
        half = (z * sqrt(n)) / 2
        err_lo[j] = at(Int(ceil((n - 1) / 2 - half)))
        err_hi[j] = at(Int(floor((n - 1) / 2 + half)))
        body_lo[j] = at(Int(floor(0.158655 * (n - 1) + 0.5)))
        body_hi[j] = at(Int(floor(0.841345 * (n - 1) + 0.5)))
    end
    return OrderedDict{String,Vector{Float64}}("errLo" => err_lo, "errHi" => err_hi, "bodyLo" => body_lo,
                                               "bodyHi" => body_hi)
end

"""The standard deviation at each time over the finite values kept (n - 1), NaN below two; and the counts."""
function _an_sd(M::AbstractMatrix, mean::Vector{Float64}, mask)
    times = size(M, 2)
    out = zeros(times)
    n = zeros(Int, times)
    for i in 1:size(M, 1)
        _an_keep(mask, i) || continue
        for j in 1:times
            v = Float64(M[i, j])
            ok = isfinite(v)
            d = ok ? v - mean[j] : 0.0
            out[j] += d * d
            n[j] += ok
        end
    end
    sd = Float64[n[j] > 1 ? sqrt(out[j] / max(n[j] - 1, 1)) : NaN for j in 1:times]
    return (sd=sd, n=n)
end

"""The percentiles asked for (probabilities strictly between 0 and 1), with the median, ascending."""
function percentiles_for(list)
    want = Set{Float64}([0.5])
    for p in (list isa Union{AbstractVector,Tuple} ? list : PROB_QUANTILES)
        v = p isa Real ? Float64(p) : py_float(p)
        (isfinite(v) && 0 < v < 1) && push!(want, v)
    end
    return sort!(collect(want))
end

"""
    quantiles(prob, label; qs=(0.05, 0.5, 0.95), mask=nothing) -> OrderedDict(q => values)

The band of one series at each time: order statistics across the realisations
that ran (`x[round(q (n - 1))]` of the sorted finite values).
"""
function quantiles(r::ProbabilisticResults, label; qs=(0.05, 0.5, 0.95), mask=nothing)
    M = _an_matrix(r, _an_index(r, label))
    ys = _an_quantiles(M, qs, mask)
    return OrderedDict{Float64,Vector{Float64}}(Float64(q) => y for (q, y) in zip(qs, ys))
end

"""The mean of one series at each time over the realisations that ran (`prob.mean` in Python)."""
realisations_mean(r::ProbabilisticResults, label; mask=nothing) = _an_mean(_an_matrix(r, _an_index(r, label)), mask)

"""The median's 95% interval (`errLo`, `errHi`) and the body's 68% (`bodyLo`, `bodyHi`) at each time."""
median_spread(r::ProbabilisticResults, label; z::Float64=1.959964, mask=nothing) =
    _an_median_spread(_an_matrix(r, _an_index(r, label)), z, mask)

"""
    bands(prob; percentiles=nothing, mask=nothing) -> Vector

Per series -- every kept one, then every varied parameter as its draws -- the
quantiles (`"q"`, at `"quantiles"`, the median always among them), the mean,
the standard deviation (`"sd"` => (sd, n)) and the median's two intervals
(`"med"`); `"flat" => true` on a varied parameter, whose numbers are single
values.
"""
function bands(r::ProbabilisticResults; percentiles=nothing, mask=nothing)
    qs = percentiles_for(percentiles)
    out = OrderedDict{String,Any}[]
    for k in 1:_an_count(r)
        M = _an_matrix(r, k)
        mean = _an_mean(M, mask)
        band = OrderedDict{String,Any}("q" => _an_quantiles(M, qs, mask), "quantiles" => qs, "mean" => mean,
                                       "sd" => _an_sd(M, mean, mask), "med" => _an_median_spread(M, 1.959964, mask))
        _an_flat(r, k) && (band["flat"] = true)
        push!(out, band)
    end
    return out
end

# --- one output at one time, as a distribution ---------------------------------------------

"""`Math.round`: the nearest integer, halves up."""
_an_js_round(x::Float64) = isfinite(x) ? (f = floor(x); x - f >= 0.5 ? f + 1 : f) : x

"""The value at cumulative probability `p` of a sorted sample, between order statistics (a spreadsheet's PERCENTILE)."""
function sample_value_at(sorted_::AbstractVector{Float64}, p)
    n = length(sorted_)
    n == 0 && return NaN
    n == 1 && return sorted_[1]
    x = _pd_jmin(1.0, _pd_jmax(0.0, _pd_to_number(p))) * (n - 1)
    isnan(x) && return NaN
    lo = Int(floor(x))
    hi = min(n - 1, lo + 1)
    a = sorted_[lo+1]
    return a + (sorted_[hi+1] - a) * (x - lo)
end

"""
    describe_sample(sorted) -> OrderedDict

The application's summary of a sorted sample: `n`, `mean`, `sd` (n - 1),
`skewness`, `kurtosis` (excess), `min`, `max`, `meanBounds` (95%),
`percentiles` (`[(p, value)]`) and `dkw`, the half-width of the 95%
Dvoretzky-Kiefer-Wolfowitz band on its distribution function.
"""
function describe_sample(a::AbstractVector{Float64})
    n = length(a)
    if n == 0
        return OrderedDict{String,Any}("n" => 0, "mean" => NaN, "sd" => NaN, "skewness" => NaN, "kurtosis" => NaN,
                                       "min" => NaN, "max" => NaN, "meanBounds" => [NaN, NaN],
                                       "percentiles" => NamedTuple{(:p, :value),Tuple{Float64,Float64}}[],
                                       "dkw" => NaN)
    end
    mean = _cr_seq_sum(a) / n
    m2 = 0.0
    m3 = 0.0
    m4 = 0.0
    for x in a
        d = x - mean
        d2 = d * d
        m2 += d2
        m3 += d2 * d
        m4 += d2 * d2
    end
    sd = n > 1 ? sqrt(m2 / (n - 1)) : 0.0
    v = m2 / n
    skewness = v > 0 ? (m3 / n) / cpow(v, 1.5) : NaN
    kurtosis = v > 0 ? (m4 / n) / (v * v) - 3 : NaN
    half = n > 1 ? 1.959964 * sd / sqrt(n) : 0.0
    return OrderedDict{String,Any}(
        "n" => n, "mean" => mean, "sd" => sd, "skewness" => skewness, "kurtosis" => kurtosis, "min" => a[1],
        "max" => a[n], "meanBounds" => [mean - half, mean + half],
        "percentiles" => [(p=p, value=sample_value_at(a, p)) for p in SUMMARY_PERCENTILES],
        "dkw" => sqrt(js_log(2 / 0.05) / (2 * n)))
end

"""Each realisation's own peak and the time (from 1) it first reaches it; NaN and 0 where screened out."""
function _an_own_peaks(M::AbstractMatrix, mask)
    n = size(M, 1)
    mx = fill(NaN, n)
    when = zeros(Int, n)
    for i in 1:n
        _an_keep(mask, i) || continue
        best, at = -Inf, 0
        for j in 1:size(M, 2)
            v = Float64(M[i, j])
            if v > best
                best, at = v, j
            end
        end
        if at > 0
            mx[i], when[i] = best, at
        end
    end
    return (max=mx, when=when)
end

"""The time (from 1) where a series is largest on average over the realisations kept."""
function _an_peak_time(M::AbstractMatrix, mask)
    best, most = 1, -Inf
    for j in 1:size(M, 2)
        total, n = 0.0, 0
        for i in 1:size(M, 1)
            _an_keep(mask, i) || continue
            v = Float64(M[i, j])
            isfinite(v) || continue
            total += v
            n += 1
        end
        n == 0 && continue
        mean = total / n
        if mean > most
            most, best = mean, j
        end
    end
    return best
end

"""When the realisations peak: the median and the 5% and 95% points of their peak times."""
function _an_peak_times(t::Vector{Float64}, when::Vector{Int})
    at = sort!(Float64[t[j] for j in when if j > 0])
    isempty(at) && return nothing
    q(p) = at[min(length(at) - 1, max(0, Int(floor(p * (length(at) - 1) + 0.5))))+1]
    return OrderedDict{String,Any}("median" => q(0.5), "low" => q(0.05), "high" => q(0.95), "n" => length(at))
end

"""The time a statistic is read at: a position in `t` from 1, `:peak` or `:max` (or their strings), `nothing` for the last."""
_an_at(at) = at isa AbstractString ? Symbol(at) : at

"""
    summary(prob, label; at=nothing, mask=nothing) -> OrderedDict

One output at one time as a distribution: `"summary"` (see `describe_sample`)
and the sorted `"column"`. `at` is a time's position in `prob.t`, `:peak`
(where the mean peaks), `:max` (each realisation's own peak, with `"peaks"`
saying when) or `nothing` (the last time).
"""
function Base.summary(r::ProbabilisticResults, label; at=nothing, mask=nothing)
    k = _an_index(r, label)
    M = _an_matrix(r, k)
    times = length(r.t)
    flat = _an_flat(r, k)
    a = _an_at(at)
    peaks = nothing
    if a === :max
        found = _an_own_peaks(M, mask)
        s = sort!(filter(isfinite, found.max))
        flat || (peaks = _an_peak_times(r.t, found.when))
        where_ = nothing
    else
        where_ = a === :peak ? _an_peak_time(M, mask) : min(times, max(1, a === nothing ? times : Int(a)))
        s = _an_finite_sorted(M, flat ? 1 : where_, mask)
    end
    frm = _an_drawn_from(r, k)
    return OrderedDict{String,Any}("index" => k, "at" => where_, "peaks" => peaks, "summary" => describe_sample(s),
                                   "column" => s, "of" => r.iterations,
                                   "spec" => frm > 0 ? r.plan[frm]["spec"] : nothing, "screened" => mask !== nothing)
end

# --- a tornado's table -------------------------------------------------------------------

"""The one number of realisation `i`'s series that a table reads: `"final"`, `"at"` (time `at`, from 1), `"max"`, else the least."""
function _an_statistic(M::AbstractMatrix, i::Int, stat::AbstractString, at)
    (1 <= i <= size(M, 1)) || return NaN
    times = size(M, 2)
    stat == "final" && return Float64(M[i, times])
    if stat == "at"
        j = min(times, max(1, at === nothing ? 1 : Int(at)))
        return Float64(M[i, j])
    end
    best = stat == "max" ? -Inf : Inf
    found = false
    for j in 1:times
        v = Float64(M[i, j])
        isfinite(v) || continue
        found = true
        best = stat == "max" ? max(best, v) : min(best, v)
    end
    return found ? best : NaN
end

"""
    tornado_table(prob, label; stat="max", at=1) -> OrderedDict

What each swung input did to one output in a tornado (`run_tornado`): the
statistic (`"max"`, `"final"`, `"at"` time `at` from 1, else the least) of the
central run and of each input's low and high run, the rows by swing, largest
first.
"""
function tornado_table(r::ProbabilisticResults, label; stat::AbstractString="max", at=1)
    haskey(r.stats, "tornado") || throw(ArgumentError("Not a tornado: run it with run_tornado."))
    k = min(_an_count(r), max(1, _an_index(r, label)))
    M = _an_matrix(r, k)
    central = _an_statistic(M, 1, stat, at)
    rows = OrderedDict{String,Any}[]
    for (s2, p) in enumerate(r.stats["tornado"]["swung"])
        e = r.plan[p]
        low = _an_statistic(M, 2 * s2, stat, at)
        high = _an_statistic(M, 2 * s2 + 1, stat, at)
        index = get(e, "index", nothing)
        push!(rows, OrderedDict{String,Any}("k" => p, "name" => e["name"],
                                            "where" => index isa AbstractDict ? collect(values(index)) : Any[],
                                            "low" => low, "high" => high, "lowInput" => r.samples[p, 2*s2],
                                            "highInput" => r.samples[p, 2*s2+1],
                                            "swing" => isfinite(low) && isfinite(high) ? abs(high - low) : NaN))
    end
    sort!(rows; by=row -> isnan(row["swing"]) ? -1.0 : row["swing"], rev=true, alg=Base.Sort.DEFAULT_STABLE)
    return OrderedDict{String,Any}("index" => k, "stat" => stat, "at" => at, "central" => central, "rows" => rows)
end

# --- which inputs drove the spread (stats/sensitivity.py) -----------------------------------

"""A sum added left to right, as numpy's `cumsum(...)[-1]` adds it."""
function _sn_seqsum(v::AbstractVector{Float64})
    isempty(v) && return 0.0
    s = v[1]
    @inbounds for i in 2:length(v)
        s += v[i]
    end
    return s
end

"""How many of `i = 0, 1, ...` pass `i < n`, at most `len` of them."""
function _sn_loop_count(n, len::Int)
    v = Float64(n)
    v > 0 || return 0
    v >= len && return len
    return Int(ceil(v))
end

"""The first `n` of `a`, NaN past its end."""
_sn_col(a::AbstractVector, n::Int) = length(a) == n ? collect(Float64, a) : Float64[i <= length(a) ? a[i] : NaN for i in 1:n]

"""Pearson's correlation over the pairs where both are finite; NaN for fewer than three or a sample that never varies."""
function sn_pearson(x::AbstractVector{Float64}, y::AbstractVector{Float64}, n=nothing)
    count = _sn_loop_count(n === nothing ? length(x) : n, min(length(x), length(y)))
    xv = Float64[]
    yv = Float64[]
    for i in 1:count
        (isfinite(x[i]) && isfinite(y[i])) || continue
        push!(xv, x[i])
        push!(yv, y[i])
    end
    used = length(xv)
    used < 3 && return NaN
    mx = _sn_seqsum(xv) / used
    my = _sn_seqsum(yv) / used
    dx = xv .- mx
    dy = yv .- my
    sxy = _sn_seqsum(dx .* dy)
    sxx = _sn_seqsum(dx .* dx)
    syy = _sn_seqsum(dy .* dy)
    (sxx > 0 && syy > 0) || return NaN
    return sxy / sqrt(sxx * syy)
end

"""Ranks from 1 of the finite values, ties sharing the average of the positions they span; NaN elsewhere."""
function sn_rank(v::AbstractVector, n::Int=length(v))
    col = _sn_col(v, n)
    out = fill(NaN, n)
    fin = Int[i for i in 1:n if isfinite(col[i])]
    m = length(fin)
    m == 0 && return out
    order = fin[sortperm(col[fin]; lt=_cr_np_less, alg=Base.Sort.DEFAULT_STABLE)]
    s = 1
    while s <= m
        e = s
        while e < m && col[order[e+1]] == col[order[e]]
            e += 1
        end
        r = ((s - 1) + (e - 1)) / 2 + 1
        for t in s:e
            out[order[t]] = r
        end
        s = e + 1
    end
    return out
end

"""Each input's Pearson and Spearman coefficient with one output column `y` (NaN where screened)."""
function _sn_at_time(samples, y::Vector{Float64}, iterations::Int)
    K = length(samples)
    p = zeros(K)
    r = zeros(K)
    ry = sn_rank(y, iterations)
    for k in 1:K
        p[k] = sn_pearson(samples[k], y, iterations)
        r[k] = sn_pearson(sn_rank(samples[k], iterations), ry, iterations)
    end
    return p, r
end

"""Where `array.slice(0, most)` stops."""
function _sn_slice_end(most, len::Int)
    most === nothing && return len
    v = Float64(most)
    isnan(v) && return 0
    v == Inf && return len
    v == -Inf && return 0
    k = trunc(Int, v)
    return k < 0 ? max(0, len + k) : min(k, len)
end

"""The inputs that matter at one time, by the size of their Spearman coefficient: rows `(k, pearson, spearman)`."""
function sn_ranked(samples, y::Vector{Float64}, iterations::Int; most=20)
    p, r = _sn_at_time(samples, y, iterations)
    rows = OrderedDict{String,Any}[]
    for k in eachindex(samples)
        (!isfinite(r[k]) && !isfinite(p[k])) && continue
        push!(rows, OrderedDict{String,Any}("k" => k, "pearson" => p[k], "spearman" => r[k]))
    end
    size_(row) = (v = row["spearman"]; (v == v && v != 0) ? abs(v) : 0.0)
    sort!(rows; by=row -> -size_(row), alg=Base.Sort.DEFAULT_STABLE)
    return rows[1:_sn_slice_end(most === nothing ? 20 : most, length(rows))]
end

"""One input's Spearman correlation with one output at every time."""
function sn_over_time(sample::AbstractVector{Float64}, M::AbstractMatrix, iterations::Int, mask)
    times = size(M, 2)
    out = zeros(times)
    rx = sn_rank(sample, iterations)
    y = Vector{Float64}(undef, iterations)
    for j in 1:times
        for i in 1:iterations
            y[i] = (i <= size(M, 1) && _an_keep(mask, i)) ? Float64(M[i, j]) : NaN
        end
        out[j] = sn_pearson(rx, sn_rank(y, iterations), iterations)
    end
    return out
end

"""The lower Cholesky factor, each entry's subtractions in the application's order; `nothing` where a pivot is not above `tol`."""
function _sn_cholesky_lower(a::Matrix{Float64}, d::Int, tol::Float64)
    L = zeros(d, d)
    for j in 1:d
        s = Vector{Float64}(undef, d - j + 1)
        for (r, i) in enumerate(j:d)
            v = a[i, j]
            for l in 1:j-1
                v -= L[i, l] * L[j, l]
            end
            s[r] = v
        end
        s[1] > tol || return nothing
        L[j, j] = sqrt(s[1])
        for (r, i) in enumerate(j+1:d)
            L[i, j] = s[r+1] / L[j, j]
        end
    end
    return L
end

"""The inverse of a symmetric positive-definite matrix by Cholesky and two triangular solves; `nothing` if singular for the purpose."""
function _sn_invert_symmetric(a::Matrix{Float64}, d::Int)
    L = _sn_cholesky_lower(a, d, 1e-10)
    L === nothing && return nothing
    z = zeros(d, d)
    out = zeros(d, d)
    for i in 1:d, c in 1:i
        v = c == i ? 1.0 : 0.0
        for l in 1:i-1
            v -= L[i, l] * z[l, c]
        end
        z[i, c] = v / L[i, i]
    end
    for i in d:-1:1, c in 1:d
        v = z[i, c]
        for l in i+1:d
            v -= L[l, i] * out[l, c]
        end
        out[i, c] = v / L[i, i]
    end
    return out
end

"""
    sn_regression(samples, y; translate="none", mask=nothing) -> OrderedDict

The regression family at one time: R², the standardized coefficients `src`,
the coefficients in units `b` and the partial correlations `pcc`, for every
input -- on the values, on ranks (`"rank"`: SRRC, PRCC) or on logarithms
(`"log"`, where a row with anything not positive is dropped and counted).
"""
function sn_regression(samples, y::Vector{Float64}; translate::AbstractString="none", mask=nothing)
    K = length(samples)
    n = length(y)
    logs = translate == "log"
    src = fill(NaN, K)
    b = fill(NaN, K)
    pcc = fill(NaN, K)
    keep = Bool[_an_keep(mask, i) for i in 1:n]
    offered = count(keep)
    usable(v) = isfinite(v) && (!logs || v > 0)
    cols_in = [_sn_col(s, n) for s in samples]
    good = Bool[keep[i] && usable(y[i]) && all(c -> usable(c[i]), cols_in) for i in 1:n]
    m = count(good)
    dropped = offered - m
    refused() = OrderedDict{String,Any}("r2" => NaN, "src" => src, "b" => b, "pcc" => pcc, "used" => m,
                                        "dropped" => dropped, "ok" => false)
    m < 4 && return refused()
    take(v) = (vals = v[good]; logs ? clog.(vals) : vals)
    function standardize(col::Vector{Float64})
        x = translate == "rank" ? sn_rank(col, m) : col
        mean = _sn_seqsum(x) / m
        d = x .- mean
        ss = _sn_seqsum(d .* d)
        ss > 0 || return nothing
        sd = sqrt(ss / (m - 1))
        return (d ./ sd, sd)
    end
    cols = Vector{Float64}[]
    sds = Float64[]
    which = Int[]
    for k in 1:K
        zk = standardize(take(cols_in[k]))
        zk === nothing && continue
        push!(cols, zk[1])
        push!(sds, zk[2])
        push!(which, k)
    end
    ystd = standardize(take(y))
    (ystd === nothing || isempty(cols)) && return refused()
    zy = ystd[1]
    P = length(cols)
    P >= m - 1 && return refused()
    Rxx = zeros(P, P)
    for a in 1:P, c in a:P
        s = cols[a][1] * cols[c][1]
        for i in 2:m
            s += cols[a][i] * cols[c][i]
        end
        Rxx[a, c] = s
        Rxx[c, a] = s
    end
    Rxx ./= (m - 1)
    rxy = Float64[_sn_seqsum(cols[a] .* zy) / (m - 1) for a in 1:P]
    inv = _sn_invert_symmetric(Rxx, P)
    inv === nothing && return refused()
    beta = Float64[_sn_seqsum(Float64[inv[r, c] * rxy[c] for c in 1:P]) for r in 1:P]
    r2 = _sn_seqsum(rxy .* beta)
    left = max(0.0, 1 - r2)
    isnan(r2) && (left = NaN)
    ysd = ystd[2]
    for (j, k) in enumerate(which)
        src[k] = beta[j]
        b[k] = beta[j] * (ysd / sds[j])
        denom = beta[j] * beta[j] + left * inv[j, j]
        part = _sn_sign(beta[j]) * _pd_sqrt((beta[j] * beta[j]) / denom)
        pcc[k] = denom > 0 ? part : 0.0
    end
    return OrderedDict{String,Any}("r2" => r2, "src" => src, "b" => b, "pcc" => pcc, "used" => m,
                                   "dropped" => dropped, "ok" => true)
end

"""numpy's `sign`: +0 for either zero, NaN for NaN."""
_sn_sign(x::Float64) = isnan(x) ? NaN : x > 0 ? 1.0 : x < 0 ? -1.0 : 0.0

"""A first-order sensitivity index, `Var(E[y|x]) / Var(y)`, estimated by binning the input into equal counts."""
function sn_first_order(x::AbstractVector{Float64}, y::AbstractVector{Float64}; mask=nothing, bins=nothing)
    n = length(x)
    yv = _sn_col(y, n)
    idx = Int[i for i in 1:n if _an_keep(mask, i) && isfinite(x[i]) && isfinite(yv[i])]
    m = length(idx)
    m < 10 && return NaN
    idx = idx[sortperm(x[idx]; lt=_cr_np_less, alg=Base.Sort.DEFAULT_STABLE)]
    x[idx[1]] == x[idx[m]] && return NaN
    ys = yv[idx]
    mean = _sn_seqsum(ys) / m
    d = ys .- mean
    total = _sn_seqsum(d .* d) / m
    total > 0 || return NaN
    B = bins !== nothing ? Float64(bins) : max(4.0, min(50.0, _an_js_round(sqrt(m))))
    between = 0.0
    bb = 0
    while bb < B
        frm = Int(floor((bb * m) / B))
        to = Int(floor(((bb + 1) * m) / B))
        if to > frm
            mb = _sn_seqsum(ys[frm+1:to]) / (to - frm)
            dev = mb - mean
            between += (to - frm) * (dev * dev)
        end
        bb += 1
    end
    between /= m
    raw = between / total - B / m
    return max(0.0, min(1.0, raw))
end

"""
    what_drove(prob, label; at=nothing, inputs=nothing, most=20, translate="none", mask=nothing) -> OrderedDict

Which inputs the spread of one output came from, at one time (the
application's *What drove it*): the inputs ranked by the size of their
Spearman coefficient (`"rows"`: `k`, `pearson`, `spearman`, `name`, `where`),
the leading six's Spearman coefficient at every time (`"curves"`), and the
regression family with the first-order index (`"measures"`: `r2`, `src`, `b`,
`pcc`, `s1`, per row). `at` is a time's position in `prob.t`, `:peak`, `:max`
(each realisation's own peak) or `nothing` (the last); `inputs` the inputs
(positions in the plan) to consider; `translate` `"none"`, `"rank"` or
`"log"` for the regression.
"""
function what_drove(r::ProbabilisticResults, label; at=nothing, inputs=nothing, most=20, translate="none",
                    mask=nothing, family=nothing)
    family === nothing || throw(ArgumentError("The measures that read any sample (family=\"distribution\") are not " *
                                              "ported to Julia yet: read them with the Python package."))
    k = _an_index(r, label)
    M = _an_matrix(r, k)
    times = length(r.t)
    iterations = r.iterations
    flat = _an_flat(r, k)
    a = _an_at(at)
    own = a === :max
    where_ = own ? nothing : a === :peak ? _an_peak_time(M, mask) :
             min(times, max(1, a === nothing ? times : Int(a)))
    peaks = nothing
    if own
        found = _an_own_peaks(M, mask)
        read = found.max
        flat || (peaks = _an_peak_times(r.t, found.when))
    else
        j = flat ? 1 : where_
        read = Float64[i <= size(M, 1) ? M[i, j] : NaN for i in 1:iterations]
    end
    y_masked = Float64[(i <= length(read) && _an_keep(mask, i)) ? read[i] : NaN for i in 1:iterations]
    nplan = size(r.samples, 1)
    use = inputs isa AbstractVector ? sort!(unique(Int[c for c in inputs if c isa Integer && 1 <= c <= nplan])) :
          collect(1:nplan)
    pool = [Float64[x for x in view(r.samples, c, :)] for c in use]
    rows = sn_ranked(pool, y_masked, iterations; most=most)
    for row in rows
        row["k"] = use[row["k"]]
    end
    pos_of = Dict(c => j for (j, c) in enumerate(use))
    curves = Any[]
    for row in rows[1:min(6, end)]
        y = sn_over_time(Float64[x for x in view(r.samples, row["k"], :)], M, iterations, mask)
        push!(curves, OrderedDict{String,Any}("k" => row["k"], "y" => length(y) == times ? y : fill(y[1], times)))
    end
    tr = translate in PROB_TRANSLATIONS ? String(translate) : "none"
    measures = nothing
    if !isempty(pool) && length(pool) <= 3000
        y = Float64[i <= length(read) ? read[i] : NaN for i in 1:iterations]
        reg = sn_regression(pool, y; translate=tr, mask=mask)
        measures = OrderedDict{String,Any}(
            "ok" => reg["ok"], "used" => reg["used"], "r2" => reg["r2"], "translate" => tr, "dropped" => reg["dropped"],
            "src" => Float64[reg["src"][pos_of[row["k"]]] for row in rows],
            "b" => Float64[reg["b"][pos_of[row["k"]]] for row in rows],
            "pcc" => Float64[reg["pcc"][pos_of[row["k"]]] for row in rows],
            "s1" => Float64[sn_first_order(Float64[x for x in view(r.samples, row["k"], :)], y; mask=mask)
                            for row in rows])
    end
    for row in rows
        e = r.plan[row["k"]]
        index = get(e, "index", nothing)
        row["name"] = e["name"]
        row["where"] = index isa AbstractDict ? collect(values(index)) : Any[]
    end
    kept = mask === nothing ? iterations : count(i -> _an_keep(mask, i), 1:iterations)
    sampled = [OrderedDict{String,Any}("k" => c, "name" => e["name"],
                                       "where" => (ix = get(e, "index", nothing); ix isa AbstractDict ? collect(values(ix)) : Any[]))
               for (c, e) in enumerate(r.plan)]
    return OrderedDict{String,Any}("index" => k, "at" => where_, "peaks" => peaks, "t" => r.t, "rows" => rows,
                                   "curves" => curves, "measures" => measures, "distribution" => nothing,
                                   "kept" => kept, "sampled" => sampled, "using" => length(use))
end
