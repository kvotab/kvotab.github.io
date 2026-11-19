# Writes src/importers/eco_unicode.cpp: the case tables the Ecolego importer's Python
# `str.lower()` and `str.upper()` stand on (`_eco_py_lower` and `_eco_py_upper` in the
# Julia package's importers/eco_maps.jl), as this Julia has them.
#
#     julia ../cpp/tools/eco_unicode.jl        (from ../julia, or anywhere)
#
# The importer maps one character at a time with Julia's `lowercase` and `uppercase`
# (utf8proc's simple mappings), adds Python's full mappings by a table of its own, and
# decides whether a capital sigma ends a word by `isuppercase`, `islowercase` and the
# general categories Lt, Mn, Me, Cf, Lm and Sk. Those are read off this Julia for every
# code point and written as runs. Run this again when the Julia the package runs on
# moves to another version of Unicode; tests/test_ecoimport.cpp checks the tables against
# a hash of every code point mapped, which tools/ecoimport_fixtures.jl writes.

const U = Base.Unicode

scalar(c) = !(0xd800 <= c <= 0xdfff)

# The code points a mapping changes, as runs of one difference and one stride (1 or 2):
# a stride of 2 only where the code point skipped is not mapped at all, so that no two runs
# interleave.
function mapping_runs(f)
    mapped = Tuple{Int,Int}[]
    for c in 0:0x10ffff
        scalar(c) || continue
        m = Int(f(Char(c)))
        m != c && push!(mapped, (c, m - c))
    end
    has = Set(first.(mapped))
    runs = NTuple{4,Int}[]          # first, last, delta, stride
    for (c, d) in mapped
        if !isempty(runs)
            a, b, dd, s = runs[end]
            if dd == d
                if a == b && (c - b == 1 || (c - b == 2 && !((b + 1) in has)))
                    runs[end] = (a, c, d, c - b)
                    continue
                elseif a != b && c - b == s && (s == 1 || !((b + 1) in has))
                    runs[end] = (a, c, d, s)
                    continue
                end
            end
        end
        push!(runs, (c, c, d, 1))
    end
    return runs
end

function ranges(pred)
    out = Tuple{Int,Int}[]
    for c in 0:0x10ffff
        scalar(c) || continue
        pred(Char(c)) || continue
        if !isempty(out) && out[end][2] == c - 1
            out[end] = (out[end][1], c)
        else
            push!(out, (c, c))
        end
    end
    return out
end

cased(c) = isuppercase(c) || islowercase(c) || U.category_code(c) == U.UTF8PROC_CATEGORY_LT
ignorable(c) = U.category_code(c) in (U.UTF8PROC_CATEGORY_MN, U.UTF8PROC_CATEGORY_ME, U.UTF8PROC_CATEGORY_CF,
                                      U.UTF8PROC_CATEGORY_LM, U.UTF8PROC_CATEGORY_SK)

hex(c) = "0x" * uppercase(string(c; base=16, pad=4))

function emit_runs(io, name, runs)
    println(io, "const CaseRun $name[] = {")
    for (k, (a, b, d, s)) in enumerate(runs)
        print(io, k % 3 == 1 ? "    " : " ", "{", hex(a), ", ", hex(b), ", ", d, ", ", s, "},")
        (k % 3 == 0 || k == length(runs)) && println(io)
    end
    println(io, "};")
    println(io, "const std::size_t $(name)_COUNT = sizeof $name / sizeof $name[0];")
    println(io)
end

function emit_ranges(io, name, rs)
    println(io, "const Range $name[] = {")
    for (k, (a, b)) in enumerate(rs)
        print(io, k % 5 == 1 ? "    " : " ", "{", hex(a), ", ", hex(b), "},")
        (k % 5 == 0 || k == length(rs)) && println(io)
    end
    println(io, "};")
    println(io, "const std::size_t $(name)_COUNT = sizeof $name / sizeof $name[0];")
    println(io)
end

io = IOBuffer()
println(io, "// Written by tools/eco_unicode.jl from Julia $(VERSION)'s Unicode tables (utf8proc): do not edit.")
println(io, "//")
println(io, "// What the Ecolego importer's Python `str.lower()` and `str.upper()` map one character at a time")
println(io, "// (Julia's `lowercase` and `uppercase`), and what decides whether a capital sigma ends a word:")
println(io, "// the cased letters (`isuppercase`, `islowercase`, category Lt) and the categories Mn, Me, Cf, Lm")
println(io, "// and Sk. A run maps first, first + stride, ... last, each by adding delta.")
println(io)
println(io, "#include \"importers/eco_unicode.hpp\"")
println(io)
println(io, "namespace kompartment::eco_unicode {")
println(io)
emit_runs(io, "LOWER", mapping_runs(lowercase))
emit_runs(io, "UPPER", mapping_runs(uppercase))
emit_ranges(io, "CASED", ranges(cased))
emit_ranges(io, "IGNORABLE", ranges(ignorable))
println(io, "}  // namespace kompartment::eco_unicode")
path = joinpath(@__DIR__, "..", "src", "importers", "eco_unicode.cpp")
mkpath(dirname(path))
write(path, take!(io))
println(path)
