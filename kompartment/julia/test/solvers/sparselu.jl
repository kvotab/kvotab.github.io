# The application's sparse LUs (src/solvers/sparselu.jl): against the Python
# package's port of them, which is the application's to the bit
# (tools/sparse_fixtures.py), where the fixtures have been written; and always
# against a dense solve, in every mode and kind.
#
#     PYTHONPATH=../python python3 tools/sparse_fixtures.py <scratch>/sparse
#     KOMPARTMENT_SPARSE_FIXTURES=<scratch>/sparse julia --project=. test/solvers/sparselu.jl

module SparseLUTests

using Test
using LinearAlgebra
using Random
using Kompartment
const K = Kompartment

const FIXTURES = get(ENV, "KOMPARTMENT_SPARSE_FIXTURES", "")
const MODES = Dict("auto" => K._SLU_AUTO, "refactor" => K._SLU_REFACTOR, "sparse" => K._SLU_SPARSE_MODE)

unhx(h) = collect(reinterpret(Float64, hex2bytes(h)))
hx(v::Vector{Float64}) = bytes2hex(collect(reinterpret(UInt8, v)))
fill_or_nothing(f::Int) = f < 0 ? nothing : f

"""A matrix case through the port as the Python package took it: what differs, or nothing."""
function replay_matrix(c, ex)
    n = c["n"]
    too_big = n * n * 8 > c["denseMaxBytes"]
    if c["mode"] == "auto" && n < c["denseBelow"] && !too_big
        return ex["made"]["kind"] == K._SLU_DENSE ? nothing : "dense by size"
    end
    has_mass = c["mass"] !== nothing
    mass = has_mass ? unhx(c["mass"]) : ones(n)
    sw = K.SparseLUMatrix(n, Int.(c["colPtr"]), Int.(c["rowIdx"]), unhx(c["values"]), mass, has_mass,
                          MODES[c["mode"]], Float64(c["denseFill"]), too_big, c["blocks"])
    made = ex["made"]
    got = (sw.kind, K._SLU_ORDERINGS[sw.ordering+1], fill_or_nothing(sw.fill))
    got == (made["kind"], made["ordering"], made["fill"]) || return "chose $got, Python $made"
    sw.kind == K._SLU_DENSE && return nothing
    for (k, (op, step)) in enumerate(zip(c["ops"], ex["steps"]))
        if haskey(op, "form")
            f = op["form"]
            held = f["held"] === nothing ? nothing : UInt8.(f["held"])
            st = K._slu_form!(sw, Float64(f["a"]), unhx(f["values"]), held)
            got = (st, fill_or_nothing(sw.fill), sw.repivots, sw.fallbacks)
            want = (step["status"], step["fill"], step["repivots"], step["fallbacks"])
            got == want || return "form $k: $got, Python $want"
            if st != K._SLU_OK
                (sw.fail_column, sw.fail_nonfinite) == (step["column"], step["nonfinite"]) ||
                    return "form $k failed at $(sw.fail_column), Python at $(step["column"])"
            end
        else
            hx(K._slu_solve!(sw, unhx(op["solve"]), zeros(n))) == step["x"] || return "solve $k"
        end
    end
    return nothing
end

"""A single-LU case through the port as the Python package took it: what differs, or nothing."""
function replay_part(c, ex)
    n = c["n"]
    colptr = Int.(c["colPtr"])
    rowidx = Int.(c["rowIdx"])
    has_mass = c["mass"] !== nothing
    mass = has_mass ? unhx(c["mass"]) : ones(n)
    steps = ex["steps"]
    if c["lu"] == "gp"
        mp, mi, jtom, diag = K._slu_miter_structure(n, colptr, rowidx)
        mx = zeros(length(mi))
        g = K._SluGP(n)
        rcm = c["order"] == "rcm"
        q = collect(0:n-1)
        if rcm
            K._slu_miter_update!(mx, 1e-3, unhx(c["values"]), mass, has_mass, jtom, diag)
            q = K._slu_rcm_order(n, mp, mi)
            q == Int.(ex["order"]) || return "reverse Cuthill-McKee's order"
        end
        for (k, (op, step)) in enumerate(zip(c["ops"], steps))
            if haskey(op, "form")
                K._slu_miter_update!(mx, Float64(op["form"]["a"]), unhx(op["form"]["values"]), mass, has_mass,
                                     jtom, diag)
                K._slu_gp_factorize!(g, mp, mi, mx, q, rcm, Inf)
                if step["singular"]
                    (g.singular, g.nonfinite, g.fail_original) == (true, step["nonfinite"], step["column"]) ||
                        return "factorisation $k"
                else
                    (g.singular, g.lnz, g.unz, g.flops) == (false, step["lnz"], step["unz"], step["flops"]) ||
                        return "factorisation $k"
                end
            elseif haskey(step, "x")
                hx(K._slu_gp_solve!(g, unhx(op["solve"]), zeros(n))) == step["x"] || return "solve $k"
            end
        end
        return nothing
    end
    if c["lu"] == "blocks"
        nblocks, block = K._slu_block_triangular(n, colptr, rowidx)
        (nblocks, block) == (ex["blocks"]["nblocks"], Int.(ex["blocks"]["block"])) || return "the blocks"
        lu = K._slu_bk_new(n, colptr, rowidx, nblocks, block)
        factor! = K._slu_bk_factor!
        solve! = K._slu_bk_solve!
        repivots = K._slu_bk_repivots
    else
        given = get(c, "columns", nothing)
        columns = given === nothing ? Int[] : Int.(given)
        lu = K._slu_rf_new(n, colptr, rowidx, columns, given !== nothing)
        factor! = K._slu_rf_factor!
        solve! = K._slu_rf_solve!
        repivots = r -> r.repivots
    end
    for (k, (op, step)) in enumerate(zip(c["ops"], steps))
        if haskey(op, "form")
            ok = factor!(lu, Float64(op["form"]["a"]), unhx(op["form"]["values"]), mass, has_mass)
            got = (ok, lu.ops, lu.nnz, repivots(lu), lu.valid)
            want = (step["ok"], step["ops"], step["nnz"], step["repivots"], step["valid"])
            got == want || return "factorisation $k: $got, Python $want"
        elseif haskey(step, "x")
            hx(solve!(lu, unhx(op["solve"]), zeros(n))) == step["x"] || return "solve $k"
        end
    end
    return nothing
end

@testset "the application's sparse LUs" begin
    @testset "against the Python package, to the bit" begin
        if isempty(FIXTURES) || !isdir(FIXTURES)
            @info "KOMPARTMENT_SPARSE_FIXTURES not set: the sparse LUs' parity tests skipped"
        else
            fx = K.parse_json(read(joinpath(FIXTURES, "sparselu.json"), String))
            kinds = Dict{Int,Int}()
            for (k, c) in enumerate(fx["matrices"])
                why = replay_matrix(c, c["expect"])
                why === nothing || @info "matrix case $k: $why"
                @test why === nothing
                kind = c["expect"]["made"]["kind"]
                kinds[kind] = get(kinds, kind, 0) + 1
            end
            # Every choice was made.
            @test all(get(kinds, k, 0) > 0 for k in (K._SLU_DENSE, K._SLU_SPARSE, K._SLU_WHOLE, K._SLU_BLOCKS))
            for (k, c) in enumerate(fx["parts"])
                why = replay_part(c, c["expect"])
                why === nothing || @info "single-LU case $k ($(c["lu"])): $why"
                @test why === nothing
            end
        end
    end

    @testset "against a dense solve" begin
        rng = MersenneTwister(4)
        for trial in 1:60
            n = rand(rng, 2:80)
            kind = trial % 3
            rows = Int[]
            cols = Int[]
            for j in 0:n-1
                push!(rows, j)
                push!(cols, j)
                if kind == 0                    # random entries
                    for _ in 1:rand(rng, 0:3)
                        push!(rows, rand(rng, 0:n-1))
                        push!(cols, j)
                    end
                elseif kind == 1                # a chain feeding down, with a little back flow
                    j + 1 < n && (push!(rows, j + 1); push!(cols, j))
                    j > 0 && rand(rng) < 0.3 && (push!(rows, j - 1); push!(cols, j))
                else                            # blocks of cells one way round
                    j % 5 != 4 && j + 1 < n && (push!(rows, j + 1); push!(cols, j))
                    j % 5 != 0 && (push!(rows, j - 1); push!(cols, j))
                    j + 5 < n && (push!(rows, j + 5); push!(cols, j))
                end
            end
            p = K.Pattern(n, rows .+ 1, cols .+ 1)
            colptr = p.colptr .- 1
            rowidx = p.rowval .- 1
            nnz = length(rowidx)
            for mode in (K._SLU_AUTO, K._SLU_REFACTOR, K._SLU_SPARSE_MODE)
                J0 = randn(rng, nnz)
                sw = K.SparseLUMatrix(n, colptr, rowidx, J0, ones(n), false, mode, 0.15, false, true)
                sw.kind == K._SLU_DENSE && continue
                for a in (1e-3, 0.5, 30.0)
                    J = J0 .* (1 .+ 0.5 .* randn(rng, nnz))
                    K._slu_form!(sw, a, J, nothing) == K._SLU_OK || continue
                    A = Matrix{Float64}(I, n, n)
                    for jj in 1:n, q in p.colptr[jj]:p.colptr[jj+1]-1
                        A[p.rowval[q], jj] -= a * J[q]
                    end
                    b = randn(rng, n)
                    x = K._slu_solve!(sw, b, zeros(n))
                    @test norm(A * x - b) <= 1e-9 * (norm(A) * norm(x) + norm(b))
                end
            end
        end
    end
end

end # module
