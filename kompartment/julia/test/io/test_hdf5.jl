# The HDF5 result-file writer, byte for byte against the Python package.
#
#     PYTHONPATH=kompartment/python python3 kompartment/julia/tools/hdf5_fixtures.py OUTDIR
#     julia --project=kompartment/julia kompartment/julia/test/io/test_hdf5.jl OUTDIR [--big]
#
# OUTDIR may also be given as KOMPARTMENT_H5_FIXTURES; without one only the
# self-contained checks run. Every fixture is a tree the Python package built
# and wrote, described step by step; this builds the same tree through the
# Julia API and compares the files. `--big` (or KOMPARTMENT_H5_BIG=1) also
# times a file of 300,000 series of 250 doubles.
#
# The files under test are included into a module of their own, not loaded
# with the package, so the test runs whatever state the rest is in.

module H5Test

using OrderedCollections: OrderedDict
using Dates, Printf

const SRC = joinpath(@__DIR__, "..", "..", "src")
include(joinpath(SRC, "util", "jsnum.jl"))
include(joinpath(SRC, "util", "zip.jl"))
include(joinpath(SRC, "util", "jsonio.jl"))
include(joinpath(SRC, "io", "csv.jl"))
include(joinpath(SRC, "io", "hdf5.jl"))
include(joinpath(SRC, "io", "resultfile.jl"))

# probabilistic_tree derives a dictionary model's index lists with these.
const HAVE_INDEXLISTS = try
    include(joinpath(SRC, "model", "decay.jl"))
    include(joinpath(SRC, "model", "indexlists.jl"))
    true
catch e
    @warn "model/indexlists.jl did not load; the case that needs it is skipped" exception = e
    false
end

# --- stand-ins for what the writers read of a run --------------------------------------------

struct FakeProject
    raw::Any
    index_lists::Any
end

struct FakeResults
    t::Vector{Float64}
    outs::Vector{Any}
    cols::Vector{Vector{Float64}}
    project::Any
    where_::IdDict{Any,Int}
end
FakeResults(t, outs, cols, project) =
    FakeResults(t, outs, cols, project, IdDict{Any,Int}(o => k for (k, o) in enumerate(outs)))

outputs(r::FakeResults) = r.outs
series_many(r::FakeResults, outs::AbstractVector) = [r.cols[r.where_[o]] for o in outs]
series(r::FakeResults, o) = series_many(r, [o])[1]

struct FakeProb
    t::Vector{Float64}
    outputs::Vector{Any}
    values::Vector{Any}
    samples::Any
    ran::Any
    iterations::Int
    inputs::Vector{Any}
end

end # module H5Test

using .H5Test
using .H5Test: H5Group, H5Dataset, H5Attrs, H5F64, H5F32, H5I32, H5STR, HDF5Error, h5group, h5dataset, h5put, write_hdf5,
               lookup3, result_tree, results_tree, write_results_hdf5, probabilistic_tree, scenarios_tree,
               write_scenarios_hdf5, js_string, js_to_number, csv_cell, csv_row, csv_header, to_csv, FakeProject,
               FakeResults, FakeProb, OrderedDict, JDict, parse_json
using Test
using Dates
using Printf

const FIXTURES = let a = filter(x -> !startswith(x, "--"), ARGS)
    !isempty(a) ? a[1] : get(ENV, "KOMPARTMENT_H5_FIXTURES", "")
end
const BIG = "--big" in ARGS || get(ENV, "KOMPARTMENT_H5_BIG", "0") == "1"
const DT = Dict("F64" => H5F64, "F32" => H5F32, "I32" => H5I32, "STR" => H5STR)
const NOW = DateTime(2026, 10, 10, 9, 5, 7)

# --- the fixtures' values, back into Julia's ---------------------------------------------------

const NP = Dict("float64" => Float64, "float32" => Float32, "int64" => Int64, "int32" => Int32, "bool" => Bool,
                "uint8" => UInt8)

function decode_ndarray(spec, dir)
    T = NP[spec["dtype"]]
    raw = haskey(spec, "hex") ? hex2bytes(spec["hex"]) : read(joinpath(dir, spec["file"]))
    flat = collect(reinterpret(T, raw))
    shape = Int[s for s in spec["shape"]]
    length(shape) == 1 && return flat
    length(shape) == 0 && return fill(flat[1])
    # C order in the file: the Julia array with the same [i, j, ...] elements.
    return permutedims(reshape(flat, reverse(shape)...), length(shape):-1:1)
end

function dec(v, dir=FIXTURES)
    if v isa AbstractDict
        if length(v) == 1
            k, x = first(v)
            if startswith(k, '$')
                k == "\$float" && return x == "NaN" ? NaN : x == "Infinity" ? Inf : -Inf
                k == "\$f32" && return Float32(dec(x, dir))
                k == "\$tuple" && return Tuple(dec(y, dir) for y in x)
                k == "\$range" && return x[1]:x[3]:(x[2]-sign(x[3]))
                k == "\$bytes" && return hex2bytes(x)
                k == "\$dict" && return OrderedDict{Any,Any}(dec(p[1], dir) => dec(p[2], dir) for p in x)
                k == "\$codepoints" && return join(Char(UInt32(c)) for c in x)
                k == "\$datetime" && return DateTime(x[1:6]...) + Millisecond(x[7] ÷ 1000)
                k == "\$bigint" && return parse(BigInt, x)
                k == "\$ndarray" && return decode_ndarray(x, dir)
                k == "\$generator" && return (y for y in dec(x, dir))
                k == "\$project" && return FakeProject(dec(x["raw"], dir), dec(x["index_lists"], dir))
            end
        end
        return OrderedDict{String,Any}(String(k) => dec(x, dir) for (k, x) in v)
    elseif v isa AbstractVector
        return Any[dec(x, dir) for x in v]
    end
    return v
end

floats(v) = Float64[Float64(x) for x in dec(v)]

function results_of(spec)
    outs = dec(spec["outputs"])
    FakeResults(floats(spec["t"]), outs, [floats(c) for c in spec["columns"]], dec(spec["project"]))
end

namedtuple(d::AbstractDict) = (; (Symbol(k) => v for (k, v) in d)...)

# --- one case, built the Julia way ---------------------------------------------------------------

function build_ops(case)
    nodes = Dict{Int,Any}()
    for op in case["ops"]
        kind = op["op"]
        if kind == "group"
            nodes[op["id"]] = h5group(dec(op["attrs"]))
        elseif kind == "dataset"
            nodes[op["id"]] = h5dataset(dec(op["data"]), DT[op["dt"]], dec(op["attrs"]), dec(op["dims"]))
        elseif kind == "put"
            h5put(nodes[op["root"]], String[p for p in op["path"]], nodes[op["node"]])
        elseif kind == "at"
            node = nodes[op["root"]]
            for p in op["path"]
                node = node.children[p]
            end
            nodes[op["id"]] = node
        elseif kind == "set_attr"
            nodes[op["node"]].attrs[dec(op["key"])] = dec(op["value"])
        else
            error("unknown op $(kind)")
        end
    end
    return write_hdf5(nodes[case["root"]])
end

function build_result_tree(case)
    outs = dec(case["outputs"])
    cols = [floats(c) for c in case["columns"]]
    object_form = case["object_form"]
    realisations = nothing
    if case["realisations"] !== nothing
        mats = Dict{Int,Any}(Int(p[1]) => dec(p[2]) for p in case["realisations"]["matrices"])
        f = i -> get(mats, i, nothing)
        n = dec(case["realisations"]["iterations"])
        realisations = object_form ? (iterations=n, matrixFor=f) : JDict("iterations" => n, "matrix_for" => f)
    end
    sample = dec(case["sample"])
    object_form && sample isa AbstractDict && (sample = namedtuple(sample))
    tree = result_tree(; t=floats(case["t"]), outputs=outs, column=i -> cols[i], which=Int[w for w in case["which"]],
                       project=dec(case["project"]), index_lists=dec(case["index_lists"]), now=dec(case["now"]),
                       realisations, sample)
    return write_hdf5(tree)
end

function build_probabilistic(case)
    p = case["prob"]
    prob = FakeProb(floats(p["t"]), dec(p["outputs"]), Any[dec(v) for v in p["values"]], dec(p["samples"]),
                    dec(p["ran"]), p["iterations"],
                    Any[JDict("output" => dec(i["output"]), "k" => i["k"]) for i in p["inputs"]])
    which = case["which"] === nothing ? nothing : Any[dec(w) for w in case["which"]]
    tree = probabilistic_tree(prob, dec(case["want"]); which, project=dec(case["project"]),
                              index_lists=dec(case["index_lists"]), now=dec(case["now"]), inputs=case["inputs"])
    return write_hdf5(tree)
end

function build_scenarios(case)
    runs = OrderedDict{String,Any}(String(r[1]) => results_of(r[2]) for r in case["runs"])
    which = case["which"] === nothing ? nothing : Any[dec(w) for w in case["which"]]
    return write_scenarios_hdf5(runs, nothing, which; active=case["active"], project=dec(case["project"]),
                                index_lists=dec(case["index_lists"]), now=NOW)
end

function build_results(case)
    res = results_of(case["results"])
    which = case["which"] === nothing ? nothing :
            Any[w isa AbstractDict ? res.outs[w["\$output"]] : w for w in case["which"]]
    return write_results_hdf5(res, nothing, which; now=NOW)
end

function perf_results(series::Int, times::Int, t, cols)
    nuclides = ["N-$(k)" for k in 0:49]
    outs = Any[]
    for k in 0:series-1
        nuc = nuclides[k%50+1]
        block = "Block$(k ÷ 50)"
        push!(outs, JDict("kind" => "compartment", "block" => block, "nuclide" => nuc, "index" => Any[nuc],
                          "dims" => Any["Radionuclides"], "label" => "$(block) [$(nuc)]", "unit" => "Bq",
                          "source" => "y", "offset" => 0))
    end
    project = FakeProject(JDict("name" => "perf", "simulation" => JDict("time_unit" => "year")),
                          Any[JDict("name" => "Radionuclides",
                                    "indices" => Any[JDict("name" => n, "enabled" => true) for n in nuclides])])
    return FakeResults(t, outs, cols, project)
end

function build_perf(case)
    m = dec(case["columns"])
    cols = [Vector{Float64}(m[k, :]) for k in 1:size(m, 1)]
    res = perf_results(case["series"], case["times"], floats(case["t"]), cols)
    write_results_hdf5(res; now=NOW)                    # compiled
    took = @elapsed bytes = write_results_hdf5(res; now=NOW)
    @printf("  perf: %d series of %d in %.3f s here, %.2f s in Python\n", case["series"], case["times"], took,
            case["seconds"])
    return bytes
end

const BUILD = Dict("ops" => build_ops, "result_tree" => build_result_tree, "probabilistic_tree" => build_probabilistic,
                   "scenarios_tree" => build_scenarios, "results_tree" => build_results, "perf" => build_perf)

function first_difference(a::Vector{UInt8}, b::Vector{UInt8})
    for i in 1:min(length(a), length(b))
        a[i] == b[i] || return i - 1
    end
    return length(a) == length(b) ? -1 : min(length(a), length(b))
end

# --- self-contained checks -----------------------------------------------------------------------

@testset "lookup3" begin
    @test lookup3(UInt8[]) == 0xdeadbeef
    @test lookup3(Vector{UInt8}(codeunits("Four score and seven years ago"))) == 0x17770551
    data = Vector{UInt8}(codeunits("Four score and seven years ago, and then some"))
    @test lookup3(data, 1, 30) == 0x17770551
    @test lookup3(data[1:10], 1, 12) == lookup3(vcat(data[1:10], UInt8[0, 0]))   # past the end reads as zeros
end

@testset "h5put" begin
    root = h5group()
    d = h5dataset([1.0])
    @test h5put(root, ["a", "", "b"], d) === d
    @test root.children["a"].children["b"] === d
    @test_throws HDF5Error h5put(root, ["a", "b"], h5dataset([2.0]))
    @test_throws HDF5Error h5put(root, ["a", "b", "c"], h5dataset([2.0]))
    @test_throws HDF5Error h5put(root, ["x/y"], h5dataset([2.0]))
    @test_throws HDF5Error h5put(root, ["", ""], h5dataset([2.0]))
    @test_throws ArgumentError h5put(root, "a/b", h5dataset([2.0]))
    err = try
        h5dataset([1.0, 2.0, 3.0], H5F64, nothing, [2, 2])
    catch e
        e
    end
    @test err isa HDF5Error && err.msg == "A 2×2 dataset holds 4 values and was given 3"
    @test_throws HDF5Error write_hdf5(h5dataset([1.0]))
    m = h5dataset([1.0 2.0 3.0; 4.0 5.0 6.0])
    @test m.dims == Any[2, 3] && m.data == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
end

@testset "H5Attrs" begin
    a = H5Attrs("b" => 1, "a" => 2)
    a["c"] = 3
    a["b"] = 10                                   # keeps its place
    @test collect(keys(a)) == ["b", "a", "c"] && a["b"] == 10 && length(a) == 3
    a[7] = "seven"                                # a key as String() writes it
    @test haskey(a, "7") && a[7] == "seven"
    delete!(a, "a")
    @test collect(keys(a)) == ["b", "c", "7"]
    @test get(a, "zz", :none) === :none
    @test_throws KeyError a["zz"]
    shared = ["x", "y"]
    p = H5Test.H5Attrs(shared, Any[1, 2], true)
    q = H5Test.H5Attrs(shared, Any[3, 4], true)
    p["x"] = 5                                    # a value: the names stay shared
    @test p.keys === shared
    p["z"] = 6                                    # a name: copied first
    @test shared == ["x", "y"] && collect(keys(p)) == ["x", "y", "z"] && collect(keys(q)) == ["x", "y"]
    # what the file says follows the order, not the container
    t1 = h5group(H5Attrs("u" => "Bq", "17" => 1.5, "0" => true))
    t2 = h5group(OrderedDict{String,Any}("u" => "Bq", "17" => 1.5, "0" => true))
    @test write_hdf5(t1) == write_hdf5(t2)
end

if isempty(FIXTURES) || !isfile(joinpath(FIXTURES, "cases.json"))
    @info "No fixtures: run tools/hdf5_fixtures.py OUTDIR and pass OUTDIR to check the files byte for byte"
else
    manifest = parse_json(read(joinpath(FIXTURES, "cases.json"), String))
    out = joinpath(FIXTURES, "julia")
    mkpath(out)

    @testset "csv and conversions" begin
        for row in manifest["csv"]["values"]
            v = dec(row["value"])
            @test js_string(v) == row["js_string"]
            want = dec(row["js_to_number"])
            got = js_to_number(v)
            @test isequal(got, want) && signbit(got) == signbit(want)
            @test csv_cell(v) == row["csv_cell"]
        end
        tab = manifest["csv"]["table"]
        t, labels, columns = dec(tab["t"]), dec(tab["labels"]), dec(tab["columns"])
        @test to_csv(t, labels, columns) == tab["csv"]
        @test csv_row(Any[1, nothing, "a,b", 1e21, NaN]) == tab["row"]
        @test csv_header(labels) == tab["header"]
    end

    @testset "byte for byte" begin
    @testset "$(case["name"])" for case in manifest["cases"]
        name = case["name"]
        if name == "prob_dict_project" && !H5Test.HAVE_INDEXLISTS
            @test_skip false
        else
            want = read(joinpath(FIXTURES, case["expected"]))
            got = BUILD[case["kind"]](case)
            write(joinpath(out, name * ".h5"), got)
            at = first_difference(got, want)
            at == -1 || println("  $(name): $(length(got)) bytes against $(length(want)); first difference at $(at)")
            @test at == -1
        end
    end
    end

    # Opened by libhdf5 itself, when there is one here.
    h5dump = Sys.which("h5dump")
    if h5dump !== nothing
        @testset "h5dump reads the files" begin
            for name in ("root_attrs", "datasets", "two_collections", "rt_basic", "prob_all", "e2e_scenarios")
                path = joinpath(out, name * ".h5")
                isfile(path) || continue
                @test success(pipeline(`$(h5dump) -A $(path)`; stdout=devnull, stderr=devnull))
            end
        end
    end
end

# --- the timing --------------------------------------------------------------------------------

if BIG
    @testset "300,000 series" begin
        series, times = 300_000, 250
        t = collect(range(0.0, 1e5; length=times))
        cols = [rand(times) for _ in 1:series]
        res = perf_results(series, times, t, cols)
        small = perf_results(100, times, t, cols[1:100])
        write_results_hdf5(small; now=NOW)                  # compiled
        GC.gc()
        took_tree = @elapsed tree = results_tree(res; now=NOW)
        took_write = @elapsed bytes = write_hdf5(tree)
        GC.gc()
        took_all = @elapsed bytes = write_results_hdf5(res; now=NOW)
        @printf("  300,000 series of 250: tree %.3f s, write %.3f s; together %.3f s, %.0f MB\n",
                took_tree, took_write, took_all, length(bytes) / 1e6)
        if !isempty(FIXTURES)
            path = joinpath(FIXTURES, "julia", "big300k.h5")
            mkpath(dirname(path))
            write(path, bytes)
        end
        @test took_all < 2.0
    end
end
