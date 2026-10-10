# Making sampled inputs move together, as Kompartment does it: Iman and Conover
# (1982). The Python package's `kompartment/stats/correlate.py` (the
# application's `src/domain/correlate.js`).
#
# A probabilistic run draws every distributed input on a stream of its own, so
# two inputs are independent unless the model says otherwise, in its
# simulation settings:
#
#     "correlations": [
#       {"a": "Kd[Tc-99]", "b": "Kd[I-129]", "r": 0.8},
#       {"group": "Kd", "r": 0.9}
#     ]
#
# -- a *pair* names two sampled inputs as the sampling plan spells them, a
# *group* correlates every sampled index of one parameter with every other.
#
# Iman-Conover *permutes* each correlated column so that the columns' ranks
# correlate as the target matrix says; nothing about any one column changes,
# only which realisation gets which value. The arithmetic is the Python
# package's, in the same order, so the same seed gives the same permutation.

"""A value in a message, or `?` for none (`v ?? '?'`)."""
_cr_or_q(v) = _pd_nullish(v) ? "?" : _pd_js_str(v)

"""The simulation settings a correlation list is read from: a model dictionary's, or a Project's."""
_cr_simulation_of(project::Project) = project.simulation
_cr_simulation_of(project::AbstractDict) = get(project, "simulation", _PD_MISSING)
_cr_simulation_of(project) = hasproperty(project, :raw) ? _cr_simulation_of(getproperty(project, :raw)) : _PD_MISSING

"""
    correlation_pairs(project, names) -> (pairs, problems)

The pairs a model asks for, read off `simulation.correlations`. `names` are
every sampled input, as the sampling plan spells them (`Kd[Tc-99]`). Returns
`pairs` -- `(a, b, r)` by position in `names`, counted from 1, `a < b` -- and
`problems`, what was ignored and why: a coefficient outside [-1, 1], a name
that is not sampled, an input paired with itself, a group with fewer than two
members, a pair given twice (the first coefficient is kept).
"""
function correlation_pairs(project, names::AbstractVector)
    at = Dict{String,Int}()
    for (k, n) in enumerate(names)
        at[_pd_js_str(n)] = k
    end
    pairs = NamedTuple{(:a, :b, :r),Tuple{Int,Int,Float64}}[]
    problems = String[]
    seen = Set{Tuple{Int,Int}}()
    function add(i::Int, j::Int, r::Float64, where_::String)
        if i == j
            push!(problems, "$where_: an input cannot be correlated with itself.")
            return
        end
        key = i < j ? (i, j) : (j, i)
        if key in seen
            push!(problems, "$where_: $(_pd_js_str(names[i])) and $(_pd_js_str(names[j])) are correlated twice; " *
                            "the first coefficient is kept.")
            return
        end
        push!(seen, key)
        push!(pairs, (a=min(i, j), b=max(i, j), r=r))
    end
    correlations = _pd_prop(_cr_simulation_of(project), "correlations")
    list = _pd_nullish(correlations) ? Any[] : correlations
    list isa AbstractDict && (list = collect(keys(list)))
    for c in list
        r_raw = _pd_prop(c, "r")
        r = _pd_to_number(r_raw)
        group = _pd_prop(c, "group")
        where_ = _pd_truthy(group) ? "group $(_pd_js_str(group))" :
                 "$(_cr_or_q(_pd_prop(c, "a"))) – $(_cr_or_q(_pd_prop(c, "b")))"
        if !isfinite(r) || r < -1 || r > 1
            push!(problems, "$where_: a correlation is a number between -1 and 1, not $(_pd_js_str(r_raw)).")
            continue
        end
        if !_pd_nullish(group)
            # Every sampled index of the parameter: `Kd[...]`, and the bare name
            # for a parameter with no index -- which has one slot, and is said.
            prefix = "$(_pd_js_str(group))["
            members = Int[k for (k, n) in enumerate(names)
                          if n isa AbstractString && ((group isa AbstractString && n == group) || startswith(n, prefix))]
            if length(members) < 2
                push!(problems, "$where_: $(length(members) == 1 ? "only one" : "no") sampled index carries that name, " *
                                "so there is nothing to correlate it with.")
                continue
            end
            for x in 1:length(members), y in x+1:length(members)
                add(members[x], members[y], r, where_)
            end
            continue
        end
        a = _pd_prop(c, "a")
        b = _pd_prop(c, "b")
        i = get(at, _pd_js_str(a), nothing)
        j = get(at, _pd_js_str(b), nothing)
        if i === nothing || j === nothing
            missing_ = Any[v for v in (i === nothing ? a : nothing, j === nothing ? b : nothing) if _pd_truthy(v)]
            push!(problems, "$where_: $(join((_pd_js_str(v) for v in missing_), " and ")) " *
                            "$(length(missing_) == 1 ? "is" : "are") not a sampled input of this model (spelled as in " *
                            "the sampling plan, e.g. Kd[Tc-99]).")
            continue
        end
        add(i, j, r, where_)
    end
    return (pairs=pairs, problems=problems)
end

"""`s = 0; for (v of values) s += v`: a sum in order."""
function _cr_seq_sum(values)
    s = 0.0
    @inbounds for v in values
        s += v
    end
    return s
end

"""`a < b` as numpy's sort compares: NaN after everything, -0 equal to +0."""
_cr_np_less(a::Float64, b::Float64) = a < b || (isnan(b) && !isnan(a))

"""numpy's `argsort(v, kind='stable')`, 1-based."""
_cr_argsort(v::AbstractVector{Float64}) = sortperm(v; lt=_cr_np_less, alg=Base.Sort.DEFAULT_STABLE)

"""`Float64Array.from(values).sort()`: ascending, -0 before +0, NaN last."""
function _cr_typed_sort(values)
    s = sort(collect(Float64, values); lt=_cr_np_less, alg=Base.Sort.DEFAULT_STABLE)
    zeros_ = findall(==(0.0), s)
    if !isempty(zeros_)
        negative = count(i -> signbit(s[i]), zeros_)
        for (k, i) in enumerate(zeros_)
            s[i] = k <= negative ? -0.0 : 0.0
        end
    end
    return s
end

"""
    iman_conover(columns, pairs, names, seed) -> (columns, adjusted)

Reorders the correlated columns in place so their ranks correlate as asked.
`columns` are one per sampled input, `n` long each; `pairs` from
`correlation_pairs`; `names` what each column is called, which names its score
stream; `seed` the run's seed. Returns which columns moved (positions, from 1)
and the largest change the target matrix needed to become a correlation
matrix (0 when it already was one). Nothing moves with no pairs, or with fewer
than three realisations.
"""
function iman_conover(columns::AbstractVector, pairs, names::AbstractVector, seed)
    isempty(pairs) && return (columns=Int[], adjusted=0.0)
    n = isempty(columns) ? 0 : length(columns[1])
    # Two realisations cannot carry a correlation, and one cannot be ranked.
    n < 3 && return (columns=Int[], adjusted=0.0)

    involved = sort!(collect(Set{Int}(k for p in pairs for k in (p.a, p.b))))
    size_ = length(involved)
    pos = Dict(k => i for (i, k) in enumerate(involved))

    # The target, and the nearest correlation matrix to it when it is not one.
    target = _cr_identity(size_)
    for p in pairs
        i = pos[p.a] - 1
        j = pos[p.b] - 1
        r = Float64(p.r)
        target[i*size_+j+1] = r
        target[j*size_+i+1] = r
    end
    adjusted = _cr_nearest_correlation!(target, size_)
    chol_target = _cr_cholesky(target, size_)

    # Scores: normal quantiles of evenly spaced probabilities, shuffled on a
    # stream named for the input.
    base = Float64[normal_probit(i / (n + 1))::Float64 for i in 1:n]
    scores = Matrix{Float64}(undef, n, size_)
    for j in 1:size_
        k = involved[j]
        name = 1 <= k <= length(names) ? names[k] : _PD_MISSING
        nxt = stream_for(seed, "correlation:$(_pd_js_str(name))")
        col = copy(base)
        picks = _cr_fisher_yates_picks(nxt, n)
        for (step, i) in enumerate(n-1:-1:1)
            t = picks[step]
            col[i+1], col[t+1] = col[t+1], col[i+1]
        end
        scores[:, j] = col
    end

    # What the scores correlate to by accident, taken out; what is wanted, put
    # in: T = S (P F^-1)^T.
    chol_scores = _cr_cholesky(_cr_correlation_of(scores, n, size_), size_)
    inv = _cr_invert_lower(chol_scores, size_)
    m = zeros(size_ * size_)            # P F^-1
    for i in 0:size_-1, j in 0:size_-1
        s = 0.0
        for l in 0:size_-1
            s += chol_target[i*size_+l+1] * inv[l*size_+j+1]
        end
        m[i*size_+j+1] = s
    end
    t_mat = Matrix{Float64}(undef, n, size_)
    for i in 0:size_-1
        s = zeros(n)
        for j in 0:size_-1
            mij = m[i*size_+j+1]
            @inbounds for r in 1:n
                s[r] = s[r] + scores[r, j+1] * mij
            end
        end
        t_mat[:, i+1] = s
    end

    # Each input takes the rank pattern of its column of T: the realisation
    # holding the largest score gets the input's largest value, and so on.
    for j in 1:size_
        col = columns[involved[j]]
        ordered = _cr_typed_sort(col)
        order = _cr_argsort(t_mat[:, j])
        for (rank, where_) in enumerate(order)
            col[where_] = ordered[rank]
        end
    end
    return (columns=involved, adjusted=adjusted)
end

"""The `j` of each Fisher-Yates step, `i` from `n - 1` down to 1: `floor(next() * (i + 1))`."""
function _cr_fisher_yates_picks(nxt::Mulberry32, n::Int)
    n < 2 && return Int[]
    return Int[floor(Int, next_uniform!(nxt) * Float64(i + 1)) for i in n-1:-1:1]
end

"""The identity of order `size`, flat, row-major."""
function _cr_identity(size_::Int)
    out = zeros(size_ * size_)
    for i in 0:size_-1
        out[i*size_+i+1] = 1.0
    end
    return out
end

"""The sample correlation matrix of the columns of `scores` (n × size), flat."""
function _cr_correlation_of(scores::Matrix{Float64}, n::Int, size_::Int)
    mean = Float64[_cr_seq_sum(view(scores, :, j)) / n for j in 1:size_]
    cov = zeros(size_ * size_)
    d = Vector{Float64}(undef, n)
    for i in 0:size_-1
        di = scores[:, i+1] .- mean[i+1]
        for j in i:size_-1
            mj = mean[j+1]
            @inbounds for r in 1:n
                d[r] = di[r] * (scores[r, j+1] - mj)
            end
            cov[i*size_+j+1] = _cr_seq_sum(d)
        end
    end
    out = zeros(size_ * size_)
    for i in 0:size_-1, j in i:size_-1
        c = cov[i*size_+j+1] / sqrt(cov[i*size_+i+1] * cov[j*size_+j+1])
        out[i*size_+j+1] = c
        out[j*size_+i+1] = c
    end
    return out
end

"""Cholesky, lower triangular, flat; a pivot below 1e-12 is floored there (rounding, not repair)."""
function _cr_cholesky(a::Vector{Float64}, size_::Int)
    low = zeros(size_ * size_)
    for i in 0:size_-1, j in 0:i
        s = a[i*size_+j+1]
        for l in 0:j-1
            s -= low[i*size_+l+1] * low[j*size_+l+1]
        end
        if i == j
            low[i*size_+i+1] = _pd_sqrt(_pd_jmax(s, 1e-12))
        else
            low[i*size_+j+1] = s / low[j*size_+j+1]
        end
    end
    return low
end

"""The inverse of a lower-triangular matrix, by forward substitution; flat."""
function _cr_invert_lower(low::Vector{Float64}, size_::Int)
    out = zeros(size_ * size_)
    for col in 0:size_-1, i in 0:size_-1
        s = i == col ? 1.0 : 0.0
        for l in 0:i-1
            s -= low[i*size_+l+1] * out[l*size_+col+1]
        end
        out[i*size_+col+1] = s / low[i*size_+i+1]
    end
    return out
end

"""
Moves a symmetric unit-diagonal matrix, in place, to a correlation matrix near
it: eigenvalues below 1e-6 lifted to it and the matrix rebuilt, then the
diagonal scaled back to one. Returns the largest change to any coefficient.
"""
function _cr_nearest_correlation!(c::Vector{Float64}, size_::Int)
    values, vectors = _cr_jacobi_eigen(c, size_)
    floor_ = 1e-6
    all(v -> v >= floor_, values) && return 0.0
    before = copy(c)
    for i in 0:size_-1, j in 0:size_-1
        s = 0.0
        for l in 0:size_-1
            s += vectors[i*size_+l+1] * _pd_jmax(values[l+1], floor_) * vectors[j*size_+l+1]
        end
        c[i*size_+j+1] = s
    end
    d = Float64[_pd_sqrt(c[i*size_+i+1]) for i in 0:size_-1]
    for i in 0:size_-1, j in 0:size_-1
        c[i*size_+j+1] = c[i*size_+j+1] / (d[i+1] * d[j+1])
    end
    worst = 0.0
    for i in eachindex(c)
        worst = _pd_jmax(worst, abs(c[i] - before[i]))
    end
    return worst
end

"""Eigenvalues and eigenvectors of a symmetric matrix by cyclic Jacobi; vectors are columns."""
function _cr_jacobi_eigen(a0::Vector{Float64}, size_::Int)
    a = copy(a0)
    v = _cr_identity(size_)
    for _sweep in 1:100
        off = 0.0
        for i in 0:size_-1, j in i+1:size_-1
            off += a[i*size_+j+1] * a[i*size_+j+1]
        end
        off < 1e-22 && break
        for p in 0:size_-1, q in p+1:size_-1
            apq = a[p*size_+q+1]
            abs(apq) < 1e-300 && continue
            theta = (a[q*size_+q+1] - a[p*size_+p+1]) / (2 * apq)
            sign_ = (theta == 0 || isnan(theta)) ? 1.0 : copysign(1.0, theta)
            t = sign_ / (abs(theta) + sqrt(theta * theta + 1))
            c = 1 / sqrt(t * t + 1)
            s = t * c
            for k in 0:size_-1
                akp = a[k*size_+p+1]
                akq = a[k*size_+q+1]
                a[k*size_+p+1] = c * akp - s * akq
                a[k*size_+q+1] = s * akp + c * akq
            end
            for k in 0:size_-1
                apk = a[p*size_+k+1]
                aqk = a[q*size_+k+1]
                a[p*size_+k+1] = c * apk - s * aqk
                a[q*size_+k+1] = s * apk + c * aqk
            end
            for k in 0:size_-1
                vkp = v[k*size_+p+1]
                vkq = v[k*size_+q+1]
                v[k*size_+p+1] = c * vkp - s * vkq
                v[k*size_+q+1] = s * vkp + c * vkq
            end
        end
    end
    return Float64[a[i*size_+i+1] for i in 0:size_-1], v
end
