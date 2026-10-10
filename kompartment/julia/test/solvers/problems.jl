# The problems of tools/solver_fixtures.py, written again in Julia with the
# same arithmetic in the same order, so that a derivative here is the Python
# one to the last bit. Each returns (f, jacobian parts, events), the parts
# being (n, rows, cols, values!(vals, t, y) or nothing, constant) with 1-based
# rows and columns.

const RHS = SolverTest.RHSFunction

function prob_robertson(p)
    f = RHS((dy, t, y) -> begin
        dy[1] = -0.04 * y[1] + 1e4 * y[2] * y[3]
        dy[2] = 0.04 * y[1] - 1e4 * y[2] * y[3] - 3e7 * y[2] * y[2]
        dy[3] = 3e7 * y[2] * y[2]
        nothing
    end)
    values! = (v, t, y) -> begin
        v[1] = -0.04
        v[2] = 0.04
        v[3] = 1e4 * y[3]
        v[4] = -1e4 * y[3] - 6e7 * y[2]
        v[5] = 6e7 * y[2]
        v[6] = 1e4 * y[2]
        v[7] = -1e4 * y[2]
        true
    end
    return f, (3, [1, 2, 1, 2, 3, 1, 2], [1, 1, 2, 2, 2, 3, 3], values!, false), nothing
end

function prob_vdp(p)
    mu = p["mu"]
    f = RHS((dy, t, y) -> begin
        dy[1] = y[2]
        dy[2] = mu * ((1.0 - y[1] * y[1]) * y[2]) - y[1]
        nothing
    end)
    values! = (v, t, y) -> begin
        v[1] = -2.0 * mu * y[1] * y[2] - 1.0
        v[2] = 1.0
        v[3] = mu * (1.0 - y[1] * y[1])
        true
    end
    return f, (2, [2, 1, 2], [1, 2, 2], values!, false), nothing
end

function prob_decay3(p)
    l1, l2, l3 = p["l"]
    f = RHS((dy, t, y) -> begin
        dy[1] = -l1 * y[1]
        dy[2] = l1 * y[1] - l2 * y[2]
        dy[3] = l2 * y[2] - l3 * y[3]
        nothing
    end)
    vals = [-l1, l1, -l2, l2, -l3]
    values! = (v, t, y) -> (copyto!(v, vals); true)
    return f, (3, [1, 2, 2, 3, 3], [1, 1, 2, 2, 3], values!, true), nothing
end

function prob_orego(p)
    s, q, w = 77.27, 8.375e-6, 0.161
    f = RHS((dy, t, y) -> begin
        dy[1] = s * (y[2] - y[1] * y[2] + y[1] - q * y[1] * y[1])
        dy[2] = (-y[2] - y[1] * y[2] + y[3]) / s
        dy[3] = w * (y[1] - y[3])
        nothing
    end)
    return f, nothing, nothing
end

function prob_hires(p)
    f = RHS((dy, t, y) -> begin
        f7 = 280.0 * y[6] * y[8] - 1.81 * y[7]
        dy[1] = -1.71 * y[1] + 0.43 * y[2] + 8.32 * y[3] + 0.0007
        dy[2] = 1.71 * y[1] - 8.75 * y[2]
        dy[3] = -10.03 * y[3] + 0.43 * y[4] + 0.035 * y[5]
        dy[4] = 8.32 * y[2] + 1.71 * y[3] - 1.12 * y[4]
        dy[5] = -1.745 * y[5] + 0.43 * y[6] + 0.43 * y[7]
        dy[6] = -280.0 * y[6] * y[8] + 0.69 * y[4] + 1.71 * y[5] - 0.43 * y[6] + 0.69 * y[7]
        dy[7] = f7
        dy[8] = -f7
        nothing
    end)
    return f, nothing, nothing
end

function prob_ball(p)
    g = 9.81
    f = RHS((dy, t, y) -> begin
        dy[1] = y[2]
        dy[2] = -g
        nothing
    end)
    ev = SolverTest.EventFunctions(1, (out, t, y) -> (out[1] = y[1]; nothing), Int8[-1])
    return f, nothing, ev
end

function prob_nonneg(p)
    f = RHS((dy, t, y) -> begin
        dy[1] = -0.5 - 0.1 * y[1] + 0.05 * y[2]
        dy[2] = 0.1 * y[1] - 0.05 * y[2]
        nothing
    end)
    return f, (2, [1, 2, 1, 2], [1, 1, 2, 2], nothing, false), nothing
end

function prob_chain(p)
    k = Vector{Float64}(p["k"])
    n = length(k)
    f = RHS((dy, t, y) -> begin
        @inbounds for i in 1:n
            dy[i] = -k[i] * y[i]
        end
        @inbounds for i in 2:n
            dy[i] += k[i-1] * y[i-1]
        end
        nothing
    end)
    rows, cols, vals = Int[], Int[], Float64[]
    for i in 1:n
        push!(rows, i); push!(cols, i); push!(vals, -k[i])
        if i < n
            push!(rows, i + 1); push!(cols, i); push!(vals, k[i])
        end
    end
    values! = (v, t, y) -> (copyto!(v, vals); true)
    return f, (n, rows, cols, values!, true), nothing
end

"""landscape_matrix of solver_fixtures.py: 0-based loops, 1-based storage."""
function landscape_matrix(nb::Int, B::Int=10)
    n = nb * B
    rows, cols, vals = Int[], Int[], Float64[]
    out = zeros(n)
    rate(i, a) = ldexp(Float64(1 + mod(i * a, 97)), -mod(i * a, 13))
    flow(src, dst, r) = (push!(rows, dst + 1); push!(cols, src + 1); push!(vals, r); out[src+1] += r)
    for b in 0:nb-1
        base = b * B
        for j in 0:B-1
            i = base + j
            if j + 1 < B
                flow(i, i + 1, rate(i, 7919))
                flow(i + 1, i, rate(i, 104729) * 0.25)
            end
            flow(i, base + mod(j + 4, B), rate(i, 1299709) * 0.125)
        end
        last = base + B - 1
        b + 1 < nb && flow(last, base + B, rate(b, 15485863))
        b + 5 < nb && flow(last, base + 5 * B + 1, rate(b, 32452843) * 0.5)
    end
    for i in 0:n-1
        push!(rows, i + 1); push!(cols, i + 1); push!(vals, -(out[i+1] + 1e-3 * (1 + i % 5)))
    end
    src = zeros(n)
    src[1:B:end] .= 1.0
    return n, rows, cols, vals, src
end

function prob_landscape(p)
    n, rows, cols, vals, src = landscape_matrix(Int(p["nb"]))
    A = sparse(rows, cols, vals, n, n)
    # The derivative by rows, each row's entries in column order (scipy's CSR
    # product, without its fused multiply-adds: agreement here is to the
    # tolerance only).
    At = sparse(cols, rows, vals, n, n)          # columns of At are the rows of A
    cp, rv, nz = At.colptr, At.rowval, At.nzval
    f = RHS((dy, t, y) -> begin
        @inbounds for i in 1:n
            s = 0.0
            for q in cp[i]:cp[i+1]-1
                s += nz[q] * y[rv[q]]
            end
            dy[i] = s + src[i]
        end
        nothing
    end)
    I, J, V = findnz(A)
    data = copy(A.nzval)
    values! = (v, t, y) -> (copyto!(v, data); true)
    return f, (n, I, J, values!, true), nothing
end

function prob_robertson_dae(p)
    f = RHS((dy, t, y) -> begin
        dy[1] = -0.04 * y[1] + 1e4 * y[2] * y[3]
        dy[2] = 0.04 * y[1] - 1e4 * y[2] * y[3] - 3e7 * y[2] * y[2]
        dy[3] = y[1] + y[2] + y[3] - 1.0
        nothing
    end)
    values! = (v, t, y) -> begin
        v[1] = -0.04
        v[2] = 0.04
        v[3] = 1.0
        v[4] = 1e4 * y[3]
        v[5] = -1e4 * y[3] - 6e7 * y[2]
        v[6] = 1.0
        v[7] = 1e4 * y[2]
        v[8] = -1e4 * y[2]
        v[9] = 1.0
        true
    end
    return f, (3, [1, 2, 3, 1, 2, 3, 1, 2, 3], [1, 1, 1, 2, 2, 2, 3, 3, 3], values!, false), nothing
end

function prob_decay3_nan(p)
    f0, parts, ev = prob_decay3(p)
    f = RHS((dy, t, y) -> begin
        f0(dy, t, y)
        if t > 5.0
            dy[2] = NaN
        end
        nothing
    end)
    return f, parts, ev
end

function prob_blowup(p)
    f = RHS((dy, t, y) -> (dy[1] = 1.0 / ((1.0 - t) * (1.0 - t)); nothing))
    return f, nothing, nothing
end

const PROBLEMS = Dict{String,Function}(
    "robertson" => prob_robertson, "vdp" => prob_vdp, "decay3" => prob_decay3, "orego" => prob_orego,
    "hires" => prob_hires, "ball" => prob_ball, "nonneg" => prob_nonneg, "chain" => prob_chain,
    "landscape" => prob_landscape, "robertson_dae" => prob_robertson_dae, "decay3_nan" => prob_decay3_nan,
    "blowup" => prob_blowup,
)

"""The JacobianSpec of a case: "none", "pattern" (differenced through it) or "exact"."""
function jacobian_of(parts, how::String)
    (how == "none" || parts === nothing) && return nothing
    n, rows, cols, values!, constant = parts
    pattern = SolverTest.Pattern(n, rows, cols)
    groups = SolverTest.colour_columns(pattern)
    if how == "pattern" || values! === nothing
        return SolverTest.JacobianSpec(pattern, groups, nothing, false)
    end
    if how == "exact_nan" || how == "exact_nan0"
        # Not a number in the third entry after t = 1 (from the start with "exact_nan0").
        always = how == "exact_nan0"
        spoiled = (v, t, y) -> begin
            values!(v, t, y)
            if always || t > 1.0
                v[3] = NaN
            end
            true
        end
        return SolverTest.JacobianSpec(pattern, groups, SolverTest.JacobianEvaluate(spoiled), false)
    end
    return SolverTest.JacobianSpec(pattern, groups, SolverTest.JacobianEvaluate(values!), constant)
end
