# Writes tests/fixtures/ecoimport.json: what the Julia package's Ecolego importer makes of
# made-up inputs, for the C++ engine's tests to compare with (tests/test_ecoimport.cpp).
#
#     julia --project=. ../cpp/tools/ecoimport_fixtures.jl        (from ../julia)
#     KOMPARTMENT_ECO_FIXTURES=DIR julia --project=. ../cpp/tools/ecoimport_fixtures.jl
#
# The pieces on their own: bytes decoded as CPython decodes them (UTF-8 with replacement and
# strictly, UTF-16 either way, XML bytes by their byte-order mark), JavaScript's `Number()` and
# pdf.py's, `toPrecision` and `toExponential`, dates, trimming, lengths and positions in UTF-16,
# identifiers, Python's `lower()` and `upper()` (on every code point and around a capital
# sigma), `localeCompare`, entities, the XML reader (every element of every
# document, or the refusal and where), distributions, `.version` files, raw deflate streams
# inflated within limits, and archives read entry by entry. Then whole imports: model.xml texts
# made up here to reach every branch the importer has, bare files in every encoding, and
# archives -- stored, deflated, damaged in every way the reader names, and two that inflate past
# the 256 MB allowance (kept as a recipe, `{"zeros": n}`, a deflate stream of n zero bytes both
# sides write the same way).
#
# With KOMPARTMENT_ECO_FIXTURES set to a directory julia/tools/eco_fixtures.py --synthetic wrote
# (outside the repository), every synthetic case in it is imported too and kept by its id, its
# label and a hash of its input; without it the directory's cases already in the fixture file are
# kept as they are, so that the file can be written again anywhere.
#
# An import's answer is the project and the report as JSON (`json_text`, two spaces) or the
# refusal in its words; a long answer is kept as an FNV-1a hash of its bytes and its length. With
# KOMPARTMENT_FIXTURE_DUMPS set every answer is written there too (`ecoimport-<n>.julia.txt`) with
# a table of the cases (`ecoimport.julia.txt`), for `diff`. Nothing is written anywhere else, and
# what auto learns about splitting a model is not kept (KOMPARTMENT_SPLIT_MEMORY=0).

ENV["KOMPARTMENT_SPLIT_MEMORY"] = "0"

using Kompartment
const K = Kompartment

J(pairs...) = K.JDict(String(k) => v for (k, v) in pairs)

function fnv(bytes::AbstractVector{UInt8})
    h = 0xcbf29ce484222325
    for b in bytes
        h = (h ⊻ b) * 0x100000001b3
    end
    return string(h; base=16, pad=16)
end
kept(bytes::AbstractVector{UInt8}) = "#" * fnv(bytes) * ":" * string(length(bytes))
kept(s::AbstractString) = kept(Vector{UInt8}(codeunits(s)))
hex(bytes) = bytes2hex(Vector{UInt8}(bytes))
bits(x) = string(reinterpret(UInt64, Float64(x)); base=16, pad=16)
B(s::AbstractString) = Vector{UInt8}(codeunits(s))

const DUMPS = get(ENV, "KOMPARTMENT_FIXTURE_DUMPS", "")
const TABLE = String[]
const COUNT = Ref(0)
"""An answer as the fixture keeps it -- a refusal as its words, anything else as a hash --
dumped where asked."""
function answer(what::String, text::AbstractString)
    COUNT[] += 1
    isempty(DUMPS) || write(joinpath(DUMPS, "ecoimport-$(COUNT[]).julia.txt"), text)
    out = startswith(text, "error:") ? String(text) : kept(text)
    push!(TABLE, "$(COUNT[]) $what $out")
    return out
end

# --- splitmix, for what is made up at random ---------------------------------------------------

mutable struct Mix
    s::UInt64
end
function next!(m::Mix)
    m.s += 0x9e3779b97f4a7c15
    z = m.s
    z = (z ⊻ (z >> 30)) * 0xbf58476d1ce4e5b9
    z = (z ⊻ (z >> 27)) * 0x94d049bb133111eb
    return z ⊻ (z >> 31)
end
pick(m::Mix, xs) = xs[Int(next!(m) % UInt64(length(xs))) + 1]
chance(m::Mix, p) = (next!(m) >> 11) * 0x1p-53 < p
rand_bytes(m::Mix, n) = UInt8[UInt8(next!(m) & 0xff) for _ in 1:n]

# --- a deflate stream of n zero bytes, as both sides write it --------------------------------------
#
# One final block with the fixed codes: a literal 0, then matches of 258 at distance 1, the
# rest as one shorter match or literals, and the end of the block.

const LBASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)
const LEXT = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)

function zeros_deflate(n::Int)
    out = UInt8[]
    acc = UInt64(0)
    nbits = 0
    function put(value, count)        # least significant bit first
        acc |= UInt64(value) << nbits
        nbits += count
        while nbits >= 8
            push!(out, UInt8(acc & 0xff))
            acc >>= 8
            nbits -= 8
        end
    end
    function code(value, count)       # a Huffman code, most significant bit first
        for k in count-1:-1:0
            put((value >> k) & 1, 1)
        end
    end
    function litlen(sym)
        if sym <= 143
            code(0x30 + sym, 8)
        elseif sym <= 255
            code(0x190 + sym - 144, 9)
        elseif sym <= 279
            code(sym - 256, 7)
        else
            code(0xc0 + sym - 280, 8)
        end
    end
    function match(len)
        k = findlast(b -> b <= len, LBASE)
        litlen(256 + k)
        LEXT[k] > 0 && put(len - LBASE[k], LEXT[k])
        code(0, 5)                    # distance 1
    end
    put(1, 1)                         # the last block
    put(1, 2)                         # fixed codes
    if n > 0
        litlen(0)
        left = n - 1
        while left >= 258
            match(258)
            left -= 258
        end
        if left >= 3
            match(left)
        else
            for _ in 1:left
                litlen(0)
            end
        end
    end
    litlen(256)
    nbits > 0 && put(0, 8 - nbits)
    return out
end

"""Bytes from segments: `{"hex": ...}` as written, `{"zeros": n}` a deflate stream of n zeros."""
segments_bytes(segs) = reduce(vcat, (haskey(s, "hex") ? hex2bytes(s["hex"]) : zeros_deflate(Int(s["zeros"])) for s in segs);
                              init=UInt8[])

# --- a ZIP archive, written as the cases need it --------------------------------------------------

le16(v) = UInt8[v & 0xff, (v >> 8) & 0xff]
le32(v) = UInt8[v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff]

"""Entries `(name=bytes, data=bytes or nothing, payload=bytes, method=0|8, size=n, flags=0x0800,
extra=bytes, version=20)`: `data` is deflated (or stored) here, `payload` taken as written. Returns
the segments: the archive as hex, with each `zeros` payload left as a recipe."""
function zip_segments(entries; comment=UInt8[])
    segs = Any[]
    body = UInt8[]
    central = UInt8[]
    offset = 0
    flush!() = (isempty(body) || push!(segs, J("hex" => hex(body))); empty!(body))
    for e in entries
        name = e.name isa AbstractString ? B(e.name) : e.name
        method = get(e, :method, 8)
        flags = get(e, :flags, 0x0800)
        zeros_n = get(e, :zeros, nothing)
        payload = if zeros_n !== nothing
            nothing
        elseif haskey(e, :payload)
            e.payload
        elseif method == 8
            K.deflate_bytes(e.data; level=get(e, :level, 6))
        else
            e.data
        end
        plen = payload === nothing ? length(zeros_deflate(zeros_n)) : length(payload)
        size = get(e, :size, haskey(e, :data) ? length(e.data) : (zeros_n !== nothing ? zeros_n : 0))
        crc = haskey(e, :data) ? Int(K.crc32(e.data)) : 0
        extra = get(e, :extra, UInt8[])
        local_ = vcat(le32(0x04034b50), le16(20), le16(flags), le16(method), le16(0), le16(0x21), le32(crc), le32(plen),
                      le32(size & 0xffffffff), le16(length(name)), le16(0), name)
        append!(body, local_)
        if payload === nothing
            flush!()
            push!(segs, J("zeros" => zeros_n))
        else
            append!(body, payload)
        end
        append!(central, vcat(le32(0x02014b50), le16(20), UInt8[get(e, :version, 20), 0], le16(flags), le16(method), le16(0),
                              le16(0x21), le32(crc), le32(plen), le32(size & 0xffffffff), le16(length(name)), le16(length(extra)),
                              le16(0), le16(0), le16(0), le32(0), le32(offset), name, extra))
        offset += length(local_) + plen
    end
    append!(body, central)
    append!(body, vcat(le32(0x06054b50), le16(0), le16(0), le16(length(entries)), le16(length(entries)), le32(length(central)),
                       le32(offset), le16(length(comment)), comment))
    flush!()
    return segs
end
zip_bytes(entries; kw...) = segments_bytes(zip_segments(entries; kw...))

# --- model.xml, made up -------------------------------------------------------------------------

cdata(text) = "<![CDATA[$text]]>"
tag(name, text) = "<$name>$(cdata(text))</$name>"
entry(type, body; index=nothing) =
    index === nothing ? "<entry type=\"$type\">$body</entry>" : "<entry type=\"$type\" index=\"$index\">$body</entry>"
function comp(type, name, id; lists=nothing, sub=nothing, body="", entries=String[], attrs="", tagname="component")
    t = type === nothing ? "" : " type=\"$type\""
    a = name === nothing ? "" : " name=\"$name\""
    l = lists === nothing ? "" : " index-lists=\"$lists\""
    s = sub === nothing ? "" : "<sub-system>$sub</sub-system>"
    i = id === nothing ? "" : "<id>$id</id>"
    "<$tagname$t$a$l$attrs>$i$s$body$(join(entries))</$tagname>"
end
conn(type, name, id, source, target; kw...) = comp(type, name, id; tagname="connection",
                                                   attrs=" source=\"$source\" target=\"$target\"" * get(kw, :attrs, ""),
                                                   (k => v for (k, v) in kw if k != :attrs)...)
compartment(name, id; initial="0", lists=nothing, more="", body="", kw...) =
    comp("compartment", name, id; lists, body, entries=[entry("compartment", tag("initial-condition", initial) * more)], kw...)
expression(name, id, eq; lists=nothing, body="", per=String[], kw...) =
    comp("expression", name, id; lists, body, entries=[entry("expression", tag("equation", eq)); per], kw...)
parameter(name, id, value; lists=nothing, more="", per=String[], body="", kw...) =
    comp("parameter", name, id; lists, body, entries=[entry("parameter", "<value>$value</value>$more"); per], kw...)
transfer(name, id, src, dst, rate; donor=nothing, per=String[], type="transfer", attrs="", kw...) =
    conn(type, name, id, src, dst; attrs,
         entries=[entry("transfer", tag("transfer-equation", rate) *
                                    (donor === nothing ? "" : "<multiply-with-donor>$donor</multiply-with-donor>")); per], kw...)
props(; name="Made up", attrs="", inner="") = "<project-properties$(name === nothing ? "" : " name=\"$name\"")$attrs>$inner</project-properties>"
property(name, text) = "<property name=\"$name\">$(cdata(text))</property>"
nuclide(name, id, half; unit=nothing) = "<nuclide name=\"$name\"><id>$id</id>" * (half === nothing ? "" : "<half-life>$half</half-life>") *
                                        (unit === nothing ? "" : "<unit>$unit</unit>") * "</nuclide>"
material(name, id; unit=nothing) = "<material name=\"$name\"><id>$id</id>" * (unit === nothing ? "" : "<unit>$unit</unit>") * "</material>"
index(name, id; enabled=nothing) = "<index name=\"$name\"" * (enabled === nothing ? "" : " enabled=\"$enabled\"") * "><id>$id</id></index>"
ilist(name, id, indices; predefined=nothing, inner="") =
    "<index-list" * (name === nothing ? "" : " name=\"$name\"") * "><id>$id</id>" *
    (predefined === nothing ? "" : property("predefined-type", predefined)) * join(indices) * inner * "</index-list>"
subsystem(name, id; parent=nothing, type=nothing, enabled=nothing) =
    "<sub-system-block" * (name === nothing ? "" : " name=\"$name\"") * (type === nothing ? "" : " type=\"$type\"") * ">" *
    (id === nothing ? "" : "<id>$id</id>") * (parent === nothing ? "" : "<sub-system>$parent</sub-system>") *
    (enabled === nothing ? "" : "<enabled>$enabled</enabled>") * "</sub-system-block>"
settings(inner; start=0, stop=1000) = "<simulation-settings><start-time>$start</start-time><end-time>$stop</end-time>$inner</simulation-settings>"

function model(; properties=props(), functions="", materials="", lists="", decay="", hierarchy="", blocks="",
               simulation=settings(""), probabilistic="", extra="", head="<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
    head * "<data-model>" * properties *
    (isempty(functions) ? "" : "<function-model>$functions</function-model>") *
    (isempty(materials) ? "" : "<material-model>$materials</material-model>") *
    (isempty(lists) ? "" : "<index-list-model>$lists</index-list-model>") *
    (isempty(decay) ? "" : "<nuclide-decay-model>$decay</nuclide-decay-model>") *
    (isempty(hierarchy) ? "" : "<hierarchy-model>$hierarchy</hierarchy-model>") *
    "<block-model>$blocks</block-model>" * simulation * probabilistic * extra * "</data-model>"
end

const MATERIALS = nuclide("Cs-137", "n-cs", "9.49e8") * nuclide("Ba-137m", "n-ba", "153.12") * nuclide("I-129", "n-i", "Infinity") *
                  material("Salt", "m-salt"; unit="kg")
const LISTS = ilist("Materials", "il-mat", [index("Cs-137", "x-cs"), index("Ba-137m", "x-ba"), index("I-129", "x-i"),
                                            index("Salt", "x-salt")]; predefined="MATERIALS") *
              ilist("Radionuclides", "il-rn", [index("Cs-137", "r-cs"), index("Ba-137m", "r-ba"), index("I-129", "r-i")];
                    predefined="RADIONUCLIDES", inner="<sub-set of=\"il-mat\"/>") *
              ilist("Objects", "il-obj", [index("Lake", "x-lake"), index("Mire", "x-mire"), index("Forest", "x-forest"; enabled="false")]) *
              ilist("Wet", "il-wet", [index("Lake", "w-lake"), index("Mire", "w-mire")]; inner="<sub-set of=\"il-obj\"/>") *
              ilist("Region", "il-reg", [index("North", "x-north"), index("South", "x-south")]) *
              ilist("ObjRegion", "il-or", [index("Lake", "o-lake"), index("Mire", "o-mire")];
                    inner="<mapping to=\"il-reg\"><map from=\"o-lake\" to=\"x-north\"/><map from=\"x-mire\" to=\"x-south\"/><map from=\"zz\" to=\"x-north\"/></mapping>")

"""A model with a little of everything: the base most made-up cases vary."""
function full_model(; blocks_extra="", simulation=nothing, kw...)
    blocks = compartment("Soil", "b-soil"; lists="il-rn,il-obj", initial="1e3",
                         more="<lower-saturation>0</lower-saturation><abs-tol>1e-9</abs-tol>",
                         body="<unit>Bq</unit><comment>top layer</comment>") *
             compartment("Deep soil", "b-deep"; lists="il-rn,il-obj", body="<handle-decay>false</handle-decay>") *
             compartment("Sink box", "b-sink"; body="<unit></unit>") *
             parameter("k leach", "b-k", "0.001"; lists="il-obj",
                       per=[entry("parameter", "<value>0.05</value>"; index="x-lake")],
                       more="<pdf function=\"logt\"><pdf-value>logt(min=1e-4,max=1e-2,mode=1e-3)</pdf-value></pdf>") *
             expression("Total", "b-total", "b-soil + Deep soil"; lists="il-obj",
                        per=[entry("expression", tag("equation", "2*b-soil"); index="x-mire")]) *
             transfer("Leach", "b-leach", "b-soil", "b-deep", "k_leach*1"; lists="il-rn,il-obj", donor="true") *
             transfer("Out", "b-out", "b-deep", "b-src", "0.01") *
             comp("source", "Boundary", "b-src") *
             comp("lookup-table", "Sorption", "b-look"; lists="il-obj",
                  body=tag("lookup-option", "Use Input Below") * "<lookup-cyclic>true</lookup-cyclic>",
                  entries=[entry("lookup-table", tag("lookup-table-time-points", "[0.0, 500.0]") * tag("lookup-table-values", "[1, 4]"))]) *
             comp("discrete-event", "Half way", "b-ev"; entries=[entry("discrete-event", tag("first-expression", "time") *
                                                                      tag("second-expression", "500") * tag("direction", "->"))]) *
             comp("min-max", "Peak", "b-peak"; body=tag("operation", "MAX"),
                  entries=[entry("min-max", tag("target-expression", "b-total") * tag("reset-event", "b-ev"))]) *
             comp("index-operation", "Sum soil", "b-sum"; body=tag("operation", "Sum"),
                  entries=[entry("expression", tag("equation", "b-soil"))]) *
             blocks_extra
    return model(; materials=MATERIALS, lists=LISTS, decay="<decay-pair parent=\"Cs-137\" daughter=\"Ba-137m\" rate=\"0.944\"/>",
                 blocks, simulation=simulation === nothing ? settings(tag("time-unit", "year") * tag("java-solver", "java-ode15s")) : simulation,
                 kw...)
end

xml_cases = Any[]
xcase(name, text; file_name=nothing, version=nothing) = push!(xml_cases, (name=name, kind="xml", payload=text, file_name, version))

# The whole model, and its name and description from every source.
xcase("full", full_model())
xcase("full, named by a file", full_model(; properties=props(; name="model")); file_name="dir\\Some Project.eco", version="6.5.1")
xcase("full, author and comment", full_model(; properties=props(; inner=property("author", " Ann ") * property("comment", "Two\nlines  "))))
xcase("created at", full_model(; properties=props(; inner=property("comment", "Created at 2021-05-25 10:00") *
                                                              "<modification-date>1621966224401</modification-date>")); version="6.5")
xcase("modified", full_model(; properties=props(; name="", inner="<modification-date> 1.6e12 </modification-date>" *
                                                             tag("comment", "a comment element"))))
xcase("modified past what a date holds", full_model(; properties=props(; inner="<modification-date>8.64e15</modification-date>")))
xcase("modified past what a date holds, by one", full_model(; properties=props(; inner="<modification-date>8640000000000001</modification-date>")))
xcase("name element", full_model(; properties=props(; name=nothing, inner="<name>  Named  </name>")))
xcase("full-name element", full_model(; properties=props(; name=nothing, inner="<full-name>Fully</full-name>")); file_name="x.EAS")
xcase("no properties", model(; properties="", blocks=expression("x", "X", "1")); file_name="/a/b/proj.xml")
xcase("no properties, no file", model(; properties="", blocks=expression("x", "X", "1")))
xcase("file name of spaces", model(; properties="", blocks=expression("x", "X", "1")); file_name="   .eco")

# Functions.
xcase("functions", full_model(; functions=
    "<function name=\"f one\" source-file-name=\"f1.java\"><function-metadata>" *
    "<parameter-metadata key=\"a b\" name=\"A\"/><parameter-metadata name=\"2x\"/><parameter-metadata/>" *
    "<parameter-metadata key=\"min\"/><parameter-metadata key=\"a_b\"/><parameter-metadata key=\"\"/>" *
    tag("function-description", "does f") * "</function-metadata></function>" *
    "<function source-file-name=\"g.java\"/><function><function-metadata/></function>" *
    "<function name=\"\">" * tag("function-description", "on the element") * "</function>"))

# Materials, nuclides and their lists.
xcase("units and half-lives", model(; materials=nuclide("A-1", "n1", "3.15e7"; unit="mol") * nuclide("B-2", "n2", "abc"; unit="Bq") *
                                              nuclide("C-3", "n3", nothing; unit="moles") * nuclide("D-4", "n4", "-inf") *
                                              nuclide("1", "n5", "10") * nuclide("0", "n6", "20") * nuclide("10", "n7", "-5") *
                                              material("M", "m1"; unit=" g ") * material("N", "m2"),
                                   lists=ilist("Stuff", "il1", [index("A-1", "s1"), index("B-2", "s2"), index("M", "s3")]),
                                   blocks=compartment("C", "c"; lists="il1"),
                                   simulation=settings(tag("time-unit", "Days"))))
xcase("units, Bq first", model(; materials=nuclide("A-1", "n1", "1"; unit="becquerel") * nuclide("B-2", "n2", "2"; unit="MOL"),
                               blocks=compartment("C", "c")))
xcase("blank names", model(; materials="<nuclide name=\" \"><id>n</id></nuclide><material><id>m</id></material>",
                           lists=ilist("L", "il", ["<index name=\"\"><id>i</id></index>", index("x", "ix")]),
                           decay="<decay-pair parent=\"\" daughter=\"x\"/><decay-pair parent=\"x\" daughter=\"y\"/>" *
                                 "<decay-pair parent=\"x\" daughter=\"z\" rate=\"abc\"/><decay-pair parent=\"x\" daughter=\"w\" rate=\" 0x1F \"/>",
                           blocks=compartment("C", "c")))
for (k, bad) in enumerate(("__proto__", "constructor", "prototype"))
    xcase("prototype nuclide $k", model(; materials=nuclide(bad, "n", "1"), blocks=compartment("C", "c")))
    xcase("prototype index $k", model(; lists=ilist("Inner", "il", [index(" $bad ", "i")]), blocks=compartment("C", "c")))
    xcase("prototype decay $k", model(; decay="<decay-pair parent=\"x\" daughter=\"$bad\"/>", blocks=compartment("C", "c")))
end
xcase("lists by name", model(; materials=nuclide("A-1", "n1", "1") * nuclide("B-2", "n2", "2") * material("M", "m1"),
                             lists=ilist("materials", "l1", [index("A-1", "a"), index("B-2", "b"), index("M", "m")]) *
                                   ilist("RadioNuclides", "l2", []) * ilist("Scenarios", "l3", [index("Base", "s1"), index("Alt", "s2"),
                                                                                                index("Off", "s3"; enabled="FALSE")]) *
                                   ilist("Elements", "l4", [index("A", "e1")]),
                             blocks=compartment("C", "c"; lists="l1,l3")))
xcase("lists by shape", model(; materials=nuclide("A-1", "n1", "1") * nuclide("B-2", "n2", "2"),
                              lists=ilist("Big", "l1", [index("A-1", "a"), index("B-2", "b")]) *
                                    ilist("Small", "l2", [index("A-1", "a2")]; inner="<sub-set of=\"l1\"/>") *
                                    ilist("Other", "l3", [index("A-1", "a3")]; inner="<mapping to=\"l1\"><map from=\"a3\" to=\"a\"/></mapping>"),
                              blocks=compartment("C", "c"; lists="l2")))
xcase("lists by size", model(; materials=nuclide("A-1", "n1", "1") * nuclide("B-2", "n2", "2"),
                             lists=ilist("One", "l1", [index("A-1", "a")]; inner="<sub-set of=\"l2\"/>") *
                                   ilist("Two", "l2", [index("A-1", "a2"), index("B-2", "b2")]; inner="<sub-set of=\"nowhere\"/>"),
                             blocks=compartment("C", "c"; lists="l1")))
xcase("radionuclides named, materials by their sub-set", model(;
    materials=nuclide("A-1", "n1", "1") * material("M", "m"),
    lists=ilist("Mats", "l1", [index("A-1", "a"), index("M", "m")]) *
          ilist("radionuclides", "l2", [index("A-1", "a2")]; inner="<sub-set of=\"l1\"/>"),
    blocks=compartment("C", "c")))
xcase("scenario list of the export", model(;
    lists="<index-list name=\"Scenarios\"><id>l1</id>" * property("predefined-type", " scenarios ") *
          property("kompartment-name", "Cases") * index("A", "a") * index("B", "b") * "</index-list>" *
          ilist("Elements list", "l2", [index("Cs", "e")]; predefined="Elements") *
          ilist("Bad map", "l3", [index("q", "q")]; inner="<mapping to=\"zz\"/>"),
    blocks=compartment("C", "c"; lists="l1")))
xcase("list names to tidy", model(; lists=ilist("min", "l1", [index("a", "a")]) * ilist("1 list", "l2", [index("b", "b")]) *
                                         ilist(nothing, "l3", [index("c", "c")]) * ilist(" ", "l4", []) * ilist("min", "l5", []),
                                   blocks=compartment("C", "c"; lists="l1,l2,l3")))

# Sub-systems.
const HIERARCHY = subsystem(nothing, nothing) * subsystem("Near field", "s1") * subsystem("Rock", "s2"; parent="s1") *
                  subsystem("Visual", "s3"; parent="s1", type="group") * subsystem("Deep", "s4"; parent="s3") *
                  subsystem("Pipe", "s5"; type="transport") * subsystem("Off", "s6"; enabled="false") *
                  subsystem("Lib", "s7"; type="external") * subsystem("Off2", "s8"; parent="s6", enabled="False") *
                  subsystem("", "s9") * subsystem("Near field", "s10")
xcase("sub-systems", model(; hierarchy=HIERARCHY, blocks=
    compartment("A", "x1"; sub="s1") * compartment("A", "x2"; sub="s2") * compartment("B", "x3"; sub="s3") *
    compartment("C", "x4"; sub="s4") * compartment("D", "x5"; sub="s6") * compartment("E", "x6"; sub="s8") *
    compartment("F", "x7"; sub="u1.u2") * compartment("G", "x8"; sub="u1..u3") * compartment("H", "x9"; sub="s10") *
    expression("Sum", "x10", "Near_field.A + Near_field.Rock.A + x4 + u1.u2.F"; sub="s2") *
    comp("transport-begin", "In", "t1"; sub="s5") * comp("transport-end", "Out", "t2"; sub="s5") *
    comp("transport-begin", "Lost", "t3") * comp("transport-element-counter", "N", "t4"; sub="s5") *
    comp("transport-operation", "Op0", "t5"; sub="s5") * comp("transport-operation", "Op1", "t6"; sub="s5",
                                                                  body="<argument/>" * tag("operation", "SUM")) *
    comp("transport-operation", "Op2", "t7"; sub="s5", body="<argument/><argument/>") *
    comp("transport-number", "Num", "t8"; sub="s5", entries=[entry("expression", tag("equation", "3"))]) *
    comp("compartment", "Off itself", "x11"; sub="s1", body="<enabled>false</enabled>")))

# Every kind of block, and what each can say.
xcase("blocks", full_model(; blocks_extra=
    comp("post-processing", "Post", "e1"; entries=[entry("expression", tag("equation", "1"))]) *
    comp("constant", "Const", "e2"; entries=[entry("expression", tag("equation", "2"))]) *
    comp("expression", "Fn", "e3"; body="<argument><argument-key>x y</argument-key></argument><argument><argument-name>z</argument-name></argument><argument/>",
         lists="il-obj", entries=[entry("expression", tag("equation", "x_y*z")), entry("expression", tag("equation", "1"); index="x-lake")]) *
    comp("lookup-table", "ByArg", "l1"; body="<argument><argument-name>q</argument-name></argument>" * tag("lookup-option", "Interpolation-Extrapolation"),
         entries=[entry("lookup-table", tag("lookup-table-time-points", "[0, 1, 2]") * tag("lookup-table-values", "[5, 6]") * "<link/>")]) *
    comp("lookup-table", "ByX", "l2"; body="<argument></argument>" * tag("lookup-option", "Mystery rule"),
         entries=[entry("lookup-table", tag("lookup-table-time-points", "1,,x, 3") * tag("lookup-table-values", "[ ]"))]) *
    comp("lookup-table", "Proto", "l3"; body=tag("lookup-option", "constructor"), entries=[]) *
    comp("lookup-table", "Proto2", "l4"; body=tag("lookup-option", "__proto__"), entries=[]) *
    comp("index-operation", "Pct", "o1"; lists="il-rn", body=tag("operation", "PERCENTILE") * "<percentile>95</percentile>",
         entries=[entry("expression", tag("equation", " b-soil ")), entry("expression", tag("equation", "b-deep"); index="r-cs")]) *
    comp("index-operation", "Pct2", "o2"; body=tag("operation", "median") * property("percentile", " 50 "),
         entries=[entry("expression", tag("equation", "b-soil"))]) *
    comp("index-operation", "Gone", "o3"; entries=[entry("expression", tag("equation", "nowhere"))]) *
    comp("index-operation", "Empty", "o4") *
    comp("aggregate", "Agg", "a1"; body=tag("operation", "Maximum"), entries=[entry("expression", tag("equation", "b-soil+ b-deep +nowhere+"))]) *
    comp("aggregate", "Agg none", "a2"; entries=[entry("expression", tag("equation", "x1+x2"))]) *
    comp("aggregate", "Agg idx", "a3"; lists="il-obj", entries=[entry("expression", tag("equation", "b-soil")),
                                                                entry("expression", tag("equation", "b-deep+b-total"); index="x-lake")]) *
    comp("min-max", "Low", "r1"; body=tag("operation", " min "), entries=[entry("min-max", tag("target-expression", "b-total"))]) *
    comp("min-max", "Odd", "r2"; body=tag("operation", "median"),
         entries=[entry("min-max", tag("start-recording-event", "b-ev") * tag("stop-recording-event", "b-ev"))]) *
    comp("running-mean", "Avg", "r3"; lists="il-obj", entries=[entry("running-mean", tag("target-expression", "b-total")),
                                                               entry("running-mean", tag("reset-event", "b-ev"); index="x-mire")]) *
    comp("snapshot", "Snap", "r4"; entries=[entry("snapshot", tag("snapshot-target", "time") * tag("snapshot-event", "b-ev") *
                                                              tag("snapshot-initial-value", "-1"))]) *
    comp("snapshot", "Snap0", "r5") *
    comp("delay", "Later", "r6"; entries=[entry("delay", tag("delay-target", "b-total") * tag("delay-time", "50"))]) *
    comp("delay", "Later0", "r7") *
    join(comp("discrete-event", "Dir $k", "d$k"; entries=[entry("discrete-event", tag("first-expression", "time") * tag("direction", d))])
         for (k, d) in enumerate(("RIGHT", " left ", "Both", "<-", ">-<", "sideways", "constructor", "__proto__", "toString", ""))) *
    parameter("Inf", "p1", "Infinity") * parameter("inf", "p2", "-infinity") * parameter("INF", "p3", "INFINITY") *
    parameter("abc", "p4", "abc") * parameter("hex", "p5", "0x1F") * parameter("blank", "p6", " ") *
    comp("parameter", "Pdfs", "p7"; lists="il-obj", entries=[
        entry("parameter", "<value>1</value><pdf><pdf-value>norm(mean=1,sd=0.1,group=g1)</pdf-value></pdf>"),
        entry("parameter", "<value>2</value><pdf function=\"weibull\"><pdf-value>weibull(a=1)</pdf-value></pdf>"; index="x-lake"),
        entry("parameter", "<value>3</value><pdf><pdf-value></pdf-value></pdf>"; index="x-mire")]) *
    comp("parameter", "Unread", "p8"; entries=[entry("parameter", "<value>1</value><pdf><pdf-value>nonsense</pdf-value></pdf>")]) *
    comp("parameter", "Unread2", "p9"; lists="il-obj", entries=[
        entry("parameter", "<pdf><pdf-value>x(1)</pdf-value></pdf>"; index="x-lake"),
        entry("parameter", "<pdf><pdf-value>y(</pdf-value></pdf>"; index="x-mire")]) *
    comp("influence", "Arrow", "i1") * comp("widget", "Gadget", "w1") * comp(nothing, nothing, "w2") *
    compartment("Bands", "c1"; lists="il-obj", more="<upper-saturation>10</upper-saturation><abs-tol>0</abs-tol>") *
    compartment("Floor", "c2"; more="<lower-saturation>-1</lower-saturation><abs-tol>Infinity</abs-tol>" * tag("differential-equation", "-1")) *
    comp("compartment", "Idx", "c3"; lists="il-obj,il-rn", entries=[
        entry("compartment", tag("initial-condition", "1"); index="x-lake,r-cs"),
        entry("compartment", tag("initial-condition", "2"); index="r-ba,x-mire"),
        entry("compartment", tag("initial-condition", "3"); index="x-lake, nowhere"),
        entry("compartment", tag("initial-condition", "4"); index="x-lake,x-mire"),
        entry("compartment", tag("abs-tol", "-1") * "<entry-unit>mol</entry-unit>"; index="x-mire,r-i")])))

# Transfers, and discrete ones.
xcase("transfers", full_model(; blocks_extra=
    transfer("Coef", "t1", "b-soil", "b-deep", "1"; type="transfer-coefficient") *
    transfer("Absolute", "t2", "b-src", "b-deep", "2") *
    transfer("Nowhere", "t3", "b-src", "zz", "3") *
    transfer("Both missing", "t4", "zz", "yy", "4") *
    transfer("Per index", "t5", "b-soil", "b-deep", "5"; lists="il-obj", donor="false", per=[
        entry("transfer", "<multiply-with-donor>TRUE</multiply-with-donor>" * tag("equation", "6"); index="x-lake"),
        entry("transfer", "<multiply-with-donor>true</multiply-with-donor>"; index="x-mire"),
        entry("transfer", tag("transfer-equation", "7"); index="x-forest")]) *
    transfer("Per index 2", "t6", "b-soil", "b-deep", "8"; lists="il-obj", per=[
        entry("transfer", "<multiply-with-donor>false</multiply-with-donor>"; index="x-lake")], type="transfer-coefficient") *
    conn("transfer", "Typeless", "t7", "b-soil", "b-deep"; entries=[entry("expression", tag("equation", "9"))]) *
    transfer("Inter", "t8", "b-soil", "c-wet", "1"; attrs=" dimension=\"1\"") *
    compartment("Marsh", "c-wet"; lists="il-rn,il-wet") *
    transfer("Inter2", "t9", "b-soil", "c-reg", "1"; attrs=" dimension=\"2\"") *
    compartment("Regional", "c-reg"; lists="il-rn,il-reg") *
    transfer("Inter3", "t10", "b-src", "c-reg", "1"; attrs=" dimension=\"2\"") *
    transfer("Inter4", "t11", "b-src", "c-reg", "1"; attrs=" dimension=\"x\"")))
const EVENTS_BLOCKS =
    comp("discrete-event", "Fire", "ev1"; entries=[entry("discrete-event", tag("first-expression", "time") * tag("second-expression", "10"))]) *
    comp("discrete-event", "Fire idx", "ev2"; lists="il-obj", entries=[entry("discrete-event", tag("first-expression", "time"))]) *
    compartment("A", "ca") * compartment("B", "cb") * compartment("Ai", "cai"; lists="il-obj") * compartment("Bi", "cbi"; lists="il-obj") *
    "<component type=\"source\" name=\"Out there\"><id>src</id></component>"
xcase("discrete transfers", model(; lists=LISTS, blocks=EVENTS_BLOCKS *
    transfer("Move", "m1", "ca", "cb", "0.5"; donor="true", per=[entry("transfer", tag("transfer-event", " Fire "))]) *
    transfer("Move back", "m2", "cb", "ca", "0.1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    transfer("Move on", "m3", "ca", "cb", "0.2"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    transfer("From outside", "m4", "src", "cb", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    transfer("Amount", "m5", "ca", "cb", "1"; donor="false", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    transfer("Two events", "m6", "cai", "cbi", "1"; donor="true", lists="il-obj", per=[entry("transfer", tag("transfer-event", "Fire")),
                                                                         entry("transfer", tag("transfer-event", "Other"); index="x-lake")]) *
    transfer("Two shares", "m7", "cai", "cbi", "1"; donor="true", lists="il-obj", per=[entry("transfer", tag("transfer-event", "Fire")),
                                                                         entry("transfer", tag("equation", "2"); index="x-lake")]) *
    transfer("To a parameter", "m8", "ca", "pp", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    parameter("pp", "pp", "1") *
    transfer("Unequal lists", "m9", "ca", "cbi", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) *
    transfer("Not an event", "m10", "ca", "cb", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "2*Fire"))]) *
    transfer("Unknown event", "m11", "ca", "cb", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Nothing"))]) *
    transfer("Indexed event", "m12", "ca", "cb", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire_idx[Lake]"))]) *
    transfer("Per cell", "m13", "cai", "cbi", "1"; donor="true", lists="il-obj", per=[entry("transfer", tag("transfer-event", "Fire_idx"))]) *
    transfer("Per cell 2", "m14", "cai", "cbi", "1"; donor="true", lists="il-obj", per=[entry("transfer", tag("transfer-event", "Fire_idx[x]"))]) *
    transfer("Blank event", "m15", "ca", "cb", "1"; donor="true", per=[entry("transfer", "<transfer-event>\u0085</transfer-event>")]) *
    transfer("Odd space", "m16", "ca", "cb", "1"; donor="true", per=[entry("transfer", "<transfer-event>Fire\x1c</transfer-event>")]) *
    transfer("Off move", "m17", "ca", "cb", "1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))], body="<enabled>false</enabled>")))
xcase("discrete transfers, many", model(; blocks=EVENTS_BLOCKS * join(
    transfer("M$k", "mm$k", "ca", "cb", "0.1"; donor="true", per=[entry("transfer", tag("transfer-event", "Fire"))]) for k in 1:8)))

# General variables.
xcase("general variables", full_model(; blocks_extra=
    comp("general-variable", "GV", "g1"; body="<available-object id=\"b-soil\"/><available-object id=\" b-deep \"/><available-object id=\"zz\"/>",
         entries=[entry("expression", tag("equation", "b-soil") * "<entry-unit>kg</entry-unit>")]) *
    comp("select", "Sel", "g2"; body="<selected-object-guid guid=\"G-DEEP\"/><available-object-guid guid=\"G-SOIL\"/><available-object-guid guid=\"nope\"/>") *
    comp("general-variable", "None", "g3") *
    comp("general-variable", "None2", "g4"; body="<available-object id=\"b-soil\"/>") *
    comp("general-variable", "Idx", "g5"; lists="il-obj", entries=[entry("expression", tag("equation", "Not.There")),
                                                                    entry("expression", tag("equation", "b-total"); index="x-lake")]) *
    comp("general-variable", "Many", "g6"; body=join("<available-object id=\"$i\"/>" for i in ("b-soil", "b-deep", "b-k", "b-total", "b-look")),
         entries=[entry("expression", tag("equation", "1 + 2"))]) *
    comp("compartment", "With guid", "gg"; body="<guid> G-SOIL </guid>") *
    comp("compartment", "Deep guid", "gd"; body="<guid>G-DEEP</guid><unit>mol</unit>")))
xcase("one general variable", model(; blocks=compartment("A", "a"; body="<unit>kg</unit>") *
    comp("general-variable", "One", "g"; entries=[entry("expression", tag("equation", "a"))])))
xcase("unchosen general variables", model(; blocks=join(comp("general-variable", "U$k", "u$k") for k in 1:6)))

# Block colours: Ecolego 6's property and the element before it, the switch beside them, the
# types' own colours, numbers Java's Integer.valueOf reads and ones it does not, and the blocks a
# colour goes on to -- both halves of a transfer made in two, the event a discrete transfer becomes.
colour(v) = "<property name=\"color\" type=\"color\">$v</property>"
shown(v) = "<property name=\"color-visible\" type=\"boolean\">$v</property>"
xcase("colours", full_model(; blocks_extra=
    compartment("Red", "k1"; body=colour("-65536") * shown("true")) *
    compartment("Own green", "k2"; body=colour("-4128832")) *
    compartment("Unfilled", "k3"; body=colour("-65536") * shown("false")) *
    compartment("Old", "k4"; body="<color> -16776961 </color><color-visible>TRUE</color-visible>") *
    compartment("Empty first", "k5"; body=colour("") * "<color>+16744448</color>") *
    compartment("Ai", "kai"; lists="il-obj") * compartment("Bi", "kbi"; lists="il-obj") *
    join(parameter("P$k", "kp$k", "1"; body=colour(v)) for (k, v) in enumerate((
        "-0", "+0", "0016711680", "-2147483648", "2147483647", "-2147483649", "2147483648", "99999999999999999999999",
        "1e3", "0x10", "\u0661\u0662", "12 34", "\u00a0-65536\u2028", "-", "+-1", "#ff0000", "-8323200", "-6250336"))) *
    join(expression("Shown $k", "ks$k", "1"; body=colour("-256") * shown(v)) for (k, v) in enumerate(("yes", " True ", "", "1"))) *
    transfer("Painted", "kt1", "k1", "k2", "0.1"; donor="true", body=colour("-256")) *
    transfer("Old green", "kt2", "k1", "k3", "0.1"; type="transfer-coefficient", body="<color>-8323200</color>") *
    transfer("Halves", "kt3", "kai", "kbi", "0.1"; lists="il-obj", donor="true", body=colour("-16711936"),
             per=[entry("transfer", "<multiply-with-donor>false</multiply-with-donor>"; index="x-lake")]) *
    comp("discrete-event", "Go", "kev"; body=colour("-4161408"),
         entries=[entry("discrete-event", tag("first-expression", "time") * tag("second-expression", "5"))]) *
    transfer("Jump", "kt4", "k1", "k3", "1"; donor="true", body=colour("-39271"), per=[entry("transfer", tag("transfer-event", "Go"))])))

# Sub-system interfaces.
iface(type, name, id, objs; sub=nothing, enabled=nothing) =
    comp(type, name, id; sub, body=(enabled === nothing ? "" : "<enabled>$enabled</enabled>") *
                                   join("<interface-object guid=\"$g\"" * (op === nothing ? "" : " operation=\"$op\"") * "/>" for (g, op) in objs))
connector(name, id, links; enabled=nothing) =
    comp("connector", name, id; body=(enabled === nothing ? "" : "<enabled>$enabled</enabled>") *
                                     join("<model-connection source=\"$s\" target=\"$t\"/>" for (s, t) in links))
const IFACE_BLOCKS = model(; hierarchy=subsystem("Lib", "s1"), blocks=
    parameter("Feed", "f1", "1"; body="<guid>GF1</guid>") * parameter("Feed2", "f2", "2"; body="<guid>GF2</guid>") *
    expression("Into", "t1", "0"; sub="s1", body="<guid>GT1</guid>",
               per=[entry("expression", tag("equation", "5"); index="x")]) *
    parameter("Param in", "t2", "0"; sub="s1", body="<guid>GT2</guid>", lists="il",
              per=[entry("parameter", "<value>3</value><pdf><pdf-value>unif(min=1,max=2)</pdf-value></pdf>"; index="i1")]) *
    transfer("Flow in", "t3", "c1", "c2", "0"; body="<guid>GT3</guid>") * compartment("C1", "c1") * compartment("C2", "c2") *
    compartment("Box", "t4"; body="<guid>GT4</guid>") *
    iface("model-input", "In", "mi", [("GT1", "max"), ("GT2", nothing), ("GT3", "Mean"), ("GT4", "add"), ("", nothing)]; sub="s1") *
    iface("model-output", "Out", "mo", [("GF1", nothing), ("GF2", nothing)]) *
    connector("Wires", "w1", [("GF1", "GT1"), ("GF2", "GT1"), ("GF1", "GT2"), ("GF2", "GT3"), ("GF1", "GT4"), ("nope", "GT4"),
                              ("GF1", "nowhere"), ("", "GT1"), ("GF1", " ")]) *
    connector("Off wires", "w2", [("GF2", "GT2")]; enabled="false"),
    lists=ilist("L", "il", [index("I1", "i1")]))
xcase("interfaces", IFACE_BLOCKS)
xcase("interfaces exposed only", model(; blocks=parameter("P", "p", "1") * iface("model-input", "In", "mi", [("G1", nothing)])))
xcase("interfaces exposed only, two", model(; blocks=iface("model-input", "In", "mi", [("G1", nothing), ("G2", "MIN")])))
xcase("interfaces, many converted", model(; blocks=parameter("Src", "s", "1"; body="<guid>GS</guid>") *
    join(parameter("P$k", "p$k", "0"; body="<guid>GP$k</guid>") for k in 1:6) *
    connector("W", "w", [("GS", "GP$k") for k in 1:6])))

# Names to tidy and the rewrite of references.
xcase("names", model(; hierarchy=subsystem("A", "sa") * subsystem("B", "sb"), blocks=
    parameter("k-1", "n1", "1") * parameter("k 1", "n2", "2") * parameter("k_1", "n3", "3") * parameter("min", "n4", "4") *
    parameter("2nd", "n5", "5") * parameter("Ünï", "n6", "6") * parameter("\U1F600", "n7", "7") * parameter("", "n8", "8") *
    parameter("  ", "n9", "9") * parameter("a.b", "n10", "10") * parameter("Deep soil", "n11", "1"; sub="sa") *
    parameter("Deep_soil", "n12", "1"; sub="sb") * parameter("Deep soil", "n13", "1"; sub="sb") *
    parameter("x(1)", "n14", "1") * parameter("A+B", "n15", "1") * parameter("pi", "n16", "1") *
    expression("Uses", "n17", "k-1 + k 1 + min + 2nd + Ünï + a.b + Deep soil + x(1) + A+B + n1 + sa.n11 + A.Deep_soil + k-1x + xk-1") *
    expression("Uses 2", "n18", "Deep soil * 2"; sub="sb", per=[entry("expression", tag("equation", "k 1"); index="q")]) *
    expression("Again", "n19", "")))
xcase("risky names, many", model(; blocks=join(parameter("v-$k", "v$k", "$k") for k in 1:8) *
    expression("Use", "u", join(("v-$k" for k in 1:8), " + "))))
xcase("ambiguous, many", model(; hierarchy=join(subsystem("S$k", "s$k") for k in 1:8), blocks=
    join(parameter("a b", "x$k", "1"; sub="s$k") * parameter("a_b", "y$k", "1"; sub="s$k") for k in 1:8)))

# Simulation settings.
for (k, (inner, prob)) in enumerate((
        (tag("time-unit", "ΟΔΟΣ") * tag("simulation-type", "straße") * tag("java-solver", "java-ﬆiff"), ""),
        (tag("time-unit", "s") * tag("java-solver", "ODE15sBDF") * "<rel-error-tolerance>1e-6</rel-error-tolerance>" *
         "<abs-error-tolerance>-1</abs-error-tolerance>" * tag("saturation-enabled", " FALSE ") * tag("simulation-type", "Probabilistic"),
         "<probabilistic-settings><no-simulations>250.5</no-simulations><seed>7.5</seed><sampling>Latin hypercube</sampling>" *
         "<probabilistic-parameters><selected-parameter> a </selected-parameter><selected-parameter></selected-parameter></probabilistic-parameters>" *
         "<correlation-matrix><correlation-pair/><correlation-pair/></correlation-matrix></probabilistic-settings>"),
        (tag("time-unit", "h") * tag("java-solver", "ODE113"),
         "<probabilistic-settings><sampling>simple</sampling><correlation-matrix><correlation-pair/></correlation-matrix>" *
         "<correlation-enabled>false</correlation-enabled></probabilistic-settings>"),
        (tag("java-solver", "dormand-prince") * tag("output-options", "Produce Specified Output Only") *
         "<time-series-list><time-series type=\"Custom\"><values>[3, 1;2 x,,]</values></time-series>" *
         "<time-series type=\"geometric\"><time-series-start-time>1</time-series-start-time><time-series-end-time>-792842341234.23404823434</time-series-end-time><n>10.5</n></time-series>" *
         "<time-series><increment>300</increment></time-series><time-series><increment>250</increment></time-series>" *
         "<time-series><n>1</n></time-series><time-series type=\"custom\"><values>[]</values></time-series></time-series-list>" *
         "<discrete-times><time-series type=\"custom\"><values>5</values></time-series></discrete-times>", ""),
        (tag("java-solver", "eulerforward") * tag("output-options", "1") * tag("batch-mode", "true"), ""),
        (tag("java-solver", "Mystery") * tag("output-options", "2"), ""),
        (tag("output-options", "0") * tag("java-solver", "RK4"), ""),
        (tag("output-options", "produce no additional output"), ""),
        (tag("output-options", "elsewhere") * tag("time-unit", "fortnights"), ""),
        ("<outputs><output id=\"b-soil\"/><output id=\"b-soil\"/><output id=\"Total\"/><output id=\"zz\"/><output id=\"zz\"/><output/></outputs>", ""),
        ("", "<probabilistic-settings><seed>abc</seed></probabilistic-settings>"),
    ))
    xcase("settings $k", full_model(; simulation=settings(inner; start=k == 2 ? -10 : 0, stop=k == 3 ? 0 : 1e5), probabilistic=prob))
end
xcase("no settings", full_model(; simulation=""))
xcase("settings, no times", full_model(; simulation="<simulation-settings>$(tag("java-solver", "ode45"))</simulation-settings>"))
xcase("settings, span only end", full_model(; simulation="<simulation-settings><end-time>-5</end-time></simulation-settings>"))
xcase("endpoints, every result", model(; blocks=compartment("A", "a") * compartment("B", "b"),
                                       simulation=settings("<outputs><output id=\"a\"/><output id=\"b\"/></outputs>")))
xcase("endpoints, twins", model(; lists=ilist("L", "il", [index("x", "x"), index("y", "y")]), blocks=
    compartment("A", "a"; lists="il") * compartment("B", "b"; lists="il") * compartment("C", "c") *
    transfer("T", "t", "a", "b", "1"; lists="il", per=[entry("transfer", "<multiply-with-donor>false</multiply-with-donor>"; index="x")]),
    simulation=settings("<outputs><output id=\"t\"/><output id=\"a\"/></outputs>")))
xcase("off blocks and twins", model(; lists=ilist("L", "il", [index("x", "x")]), hierarchy=subsystem("Off", "s"; enabled="false"), blocks=
    compartment("A", "a"; lists="il", body="<enabled>false</enabled>") * compartment("B", "b"; lists="il", sub="s") *
    transfer("T", "t", "a", "b", "1"; lists="il", body="<enabled>false</enabled>",
             per=[entry("transfer", "<multiply-with-donor>false</multiply-with-donor>"; index="x")])))
xcase("no block model", "<data-model>" * props() * "</data-model>")
xcase("data-model deep", "<root><a/><b><data-model><block-model>" * expression("e", "e", "1") * "</block-model></data-model></b></root>")
xcase("description, many lists", model(; lists=join(ilist("List $k", "il$k", [index("i", "i$k")]) for k in 1:9),
    blocks=join(compartment("C$k", "c$k"; lists=join(("il$j" for j in 1:k), ",")) for k in 1:9) *
           comp("running-mean", "RM", "rm"; lists="il1,il2") * comp("events", "E", "ev"),
    simulation=settings(tag("time-unit", "hours"); start=1.5e-7, stop=123456789)))

# What is not a model at all, and model.xml that does not parse.
xcase("not XML", "just text")
xcase("no data-model", "<root><x/></root>")
for (k, bad) in enumerate(("<data-model><!-- open", "<data-model><![CDATA[ open", "<data-model><? open", "<data-model><!DOCTYPE open",
                           "<data-model>< a/></data-model>", "<data-model></data-model x", "</data-model>", "<data-model a=\"1\"",
                           "<data-model a></data-model>", "<data-model a=1></data-model>", "<data-model a=\"1></data-model>",
                           "<data-model/><data-model/>", "<data-model><block-model>", "<?xml version=\"1.0\"?>",
                           "<data-model>\U1F600<a></b></data-model>", "<data-model x=\"\u00a0\"\u00a0/>", ""))
    xcase("bad XML $k", bad)
end
xcase("XML with every entity", "<data-model><block-model><component type=\"expression\" name=\"a&#X41;&#12a;&#x42;&#0;&#1114112;&#xD800;&nbsp;&amp;&lt;&gt;&quot;&apos;&#x1F600;&#99999999999999999999;&#;\"><id>X</id>" *
                               entry("expression", "<equation>1 &amp;&amp; 2 &#x3c; 3 &bogus; &#65;</equation>") * "</component></block-model></data-model>")

# Made-up models with their text changed at random, mostly where values, names and entities are
# (after a `>`), so that most of them still read as XML.
let m = Mix(0x5eed)
    bases = [full_model(), xml_cases[findfirst(c -> c.name == "transfers", xml_cases)].payload,
             xml_cases[findfirst(c -> c.name == "general variables", xml_cases)].payload,
             xml_cases[findfirst(c -> c.name == "settings 4", xml_cases)].payload]
    tokens = [" ", "\u00a0", "x", "0", "9", "a", "_", ".", ",", "-", "+", "\n", "\u2028", "\ufeff", "é", "\U1F600", "&amp;", "&#x41;",
              "&#65;", "&nbsp;", "Infinity", "-Infinity", "0x1F", "1e400", "-1e400", "1e-400", "TRUE", "false", "min", "k-1",
              "Deep soil", "Σ", "NaN", "", "' ", "\"", ">", "]]", "&", ";", "  7  ", "1,2", "[1, 2, 3]", "[1;2]",
              "-792842341234.23404823434", "b-soil", "Soil.x", "ev[Lake]", "constructor", "__proto__"]
    for k in 1:40
        text = pick(m, bases)
        for _ in 1:pick(m, (1, 2, 3, 5, 8))
            i = pick(m, findall('>', text))
            j = something(findnext('<', text, i + 1), ncodeunits(text) + 1)
            tok = pick(m, tokens)
            text = chance(m, 0.5) ? text[1:i] * tok * text[i+1:end] : text[1:i] * tok * text[j:end]
        end
        xcase("mutated $k", text)
    end
end

# --- files and archives ----------------------------------------------------------------------------

const MINIMAL = model(; blocks=expression("x", "X", "1"))
file_cases = Any[]
fcase(name, segs; file_name=nothing, version=nothing) = push!(file_cases, (name=name, segments=segs, file_name, version))
fbytes(name, bytes; kw...) = fcase(name, Any[J("hex" => hex(bytes))]; kw...)

utf16(s; le=false) = reduce(vcat, (le ? UInt8[u & 0xff, u >> 8] : UInt8[u >> 8, u & 0xff] for u in transcode(UInt16, s)); init=UInt8[])
fbytes("UTF-16BE", vcat(UInt8[0xfe, 0xff], utf16(MINIMAL)); file_name="old.eco")
fbytes("UTF-16LE", vcat(UInt8[0xff, 0xfe], utf16(MINIMAL; le=true)))
fbytes("UTF-16LE, odd byte and lone surrogates", vcat(UInt8[0xff, 0xfe], utf16(MINIMAL[1:end-13]; le=true), UInt8[0x00, 0xdc, 0x41, 0x00],
                                                      utf16("</data-model>"; le=true), UInt8[0x00, 0xd8, 0x00]))
fbytes("UTF-8 with two marks", vcat(UInt8[0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf], B(MINIMAL)))
fbytes("UTF-8 broken", vcat(B("<data-model><project-properties name=\"a"), UInt8[0xc0, 0xaf, 0xe0, 0x80, 0xed, 0xa0, 0x80, 0xf4, 0x90, 0xff],
                            B("\"/>"), B(MINIMAL[length("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<data-model>")+1:end]), UInt8[0xf0, 0x9f]))
fbytes("a sheet", B("<?xml version=\"1.0\"?><sheet\tname=\"x\"><data-model></data-model></sheet>"))
fbytes("a sheet in UTF-16", vcat(UInt8[0xfe, 0xff], utf16("<sheet>")))
fbytes("neither", B("<data-modeller/>"))
fbytes("PK but not ZIP", B("PK\x03\x04 nothing else"))
fbytes("PK, short", B("PK\x05"))
fbytes("empty", UInt8[])

model_entry(; kw...) = (name="model.xml", data=B(MINIMAL), kw...)
fcase("stored", zip_segments([model_entry(method=0)]); file_name="proj.eco")
fcase("deflated, with a version", zip_segments([(name=".version", data=B("a=1\nversion = 6.5.85 track-changes=false\n")), model_entry()]))
fcase("version stored, in a folder", zip_segments([(name="p\\.version", data=B("xversion=1\tversion\u3000=\u00a07"), method=0),
                                                   (name="p\\model.xml", data=B(MINIMAL))]); version="ignored")
fcase("version damaged", zip_segments([(name=".version", payload=UInt8[0x07, 0x01, 0x02], size=7), model_entry()]))
fcase("version without one", zip_segments([(name=".version", data=B("nothing here = 1"), method=0), model_entry()]))
fcase("model by its tag", zip_segments([(name="a.txt", data=B("<data-model>"), method=0), (name="b.XML", data=B("<root/>")),
                                        (name="c.Xml", data=B(MINIMAL)), (name="d.xml", data=B(MINIMAL))]))
fcase("no model", zip_segments([(name="results/r.dta", data=B("x"^40)), (name="dir/", data=UInt8[], method=0), (name="x.xml", data=B("<x/>"))]))
fcase("nothing in it", zip_segments([]))
fcase("encrypted", zip_segments([model_entry(flags=0x0801)]))
fcase("method 12", zip_segments([model_entry(method=12, payload=UInt8[1, 2, 3])]))
fcase("name not UTF-8 though flagged", zip_segments([(name=UInt8[0x6d, 0xe9, 0x6c], data=B(MINIMAL))]))
fcase("name cut short", zip_segments([(name=UInt8[0x61, 0xe2, 0x82], data=B("x")), model_entry()]))
fcase("name not flagged, not UTF-8", zip_segments([(name=UInt8[0x6d, 0xe9, 0x6c, 0x2e, 0x78, 0x6d, 0x6c], data=B(MINIMAL), flags=0)]))
fcase("name with a mark", zip_segments([(name=vcat(UInt8[0xef, 0xbb, 0xbf], B("model.xml")), data=B(MINIMAL))]))
fcase("name twice", zip_segments([(name="model.xml", data=B("<data-model><broken")), (name="model.xml", data=B(MINIMAL))]))
fcase("version 64", zip_segments([model_entry(version=64)]))
fcase("version 255", zip_segments([model_entry(version=255)]))
fcase("extra field cut", zip_segments([model_entry(extra=UInt8[0x01, 0x00, 0x08, 0x00, 0x61, 0x62])]))
fcase("extra field tail", zip_segments([model_entry(extra=UInt8[0x99, 0x99, 0x00, 0x00, 0x01, 0x02, 0x03])]))
fcase("unicode path short", zip_segments([model_entry(extra=UInt8[0x75, 0x70, 0x03, 0x00, 0x01, 0x61, 0x62])]))
let name = B("model.xml"), crc = le32(Int(K.crc32(name)))
    fcase("unicode path not UTF-8", zip_segments([model_entry(extra=vcat(UInt8[0x75, 0x70, 0x07, 0x00, 0x01], crc, UInt8[0xff, 0xfe]))]))
    fcase("unicode path fine", zip_segments([model_entry(extra=vcat(UInt8[0x75, 0x70, 0x07, 0x00, 0x01], crc, B("ok")))]))
    fcase("unicode path, other crc", zip_segments([model_entry(extra=vcat(UInt8[0x75, 0x70, 0x07, 0x00, 0x01], le32(1), UInt8[0xff, 0xfe]))]))
end
fcase("zip64 sizes", zip_segments([model_entry(method=0, size=0xffffffff, extra=vcat(le16(1), le16(8), le32(length(MINIMAL)), le32(0)))]))
fcase("zip64 field missing", zip_segments([model_entry(method=0, size=0xffffffff, extra=vcat(le16(1), le16(0)))]))
fcase("expands too far", zip_segments([model_entry(size=300 * 1024 * 1024)]))
fcase("size wrong", zip_segments([model_entry(size=5)]))
fcase("deflate damaged: block type", zip_segments([model_entry(payload=UInt8[0x07, 0x00])]))
fcase("deflate damaged: stored lengths", zip_segments([model_entry(payload=UInt8[0x01, 0x05, 0x00, 0x05, 0x00, 0x61])]))
fcase("deflate damaged: too far back", zip_segments([model_entry(payload=UInt8[0x63, 0x00, 0x42, 0x00])]))
fcase("deflate damaged: code lengths", zip_segments([model_entry(payload=UInt8[0x05, 0xff, 0xff, 0xff, 0xff, 0xff])]))
fcase("deflate cut short", zip_segments([model_entry(payload=K.deflate_bytes(B(MINIMAL))[1:20])]))
fcase("allowance: past it", zip_segments([(name="a.xml", zeros=200 * 1024 * 1024), (name="b.xml", data=B("x"), size=100 * 1024 * 1024),
                                          model_entry()]))
fcase("allowance: an entry larger than it says", zip_segments([(name="c.xml", zeros=300 * 1024 * 1024, size=0), model_entry()]))
fcase("allowance: within it", zip_segments([(name="a.xml", zeros=1000), (name="dir/b.dat", zeros=70000, size=70000), model_entry()]))

# The archive's frame: what is before it, after it, and its end records.
let base = zip_bytes([(name="a.txt", data=B("a"), method=0), model_entry()])
    eocd = findlast(B("PK\x05\x06"), base)
    fbytes("with a prefix and a comment", vcat(B("PK\x03\x04junk"), base[1:end-2], UInt8[0x05, 0x00], B("hello")))
    fbytes("comment cut short", vcat(base[1:end-2], UInt8[0x50, 0x00], B("hi")))
    fbytes("end record cut", base[1:end-4])
    fbytes("only an end record", base[first(eocd):end])
    cd_at = first(findfirst(B("PK\x01\x02"), base))
    damaged = copy(base); damaged[cd_at+3] = 0x09
    fbytes("central directory damaged", damaged)
    cut = copy(base); cut[end-9] = UInt8(cut[end-9] + 30)        # the directory's size, too large
    fbytes("central directory truncated", cut)
    off = copy(base); off[end-5] = 0xff; off[end-4] = 0xff        # the directory's offset, too large
    fbytes("central directory offset bad", off)
    hdr = copy(base); hdr[cd_at+42] = 0x00; hdr[cd_at+43] = 0x00; hdr[cd_at+44] = 0x01; hdr[cd_at+45] = 0x00
    fbytes("header offset outside", hdr)
    loc = copy(base); second = first(findnext(B("PK\x03\x04"), base, 5)); loc[second+3] = 0x05
    fbytes("local header damaged", loc)
    past = copy(base); past[cd_at+20] = 0xff; past[cd_at+21] = 0xff
    fbytes("entry past the end", past)
    # ZIP64 end records: one disk, two, and a locator with no record.
    body = base[1:first(eocd)-1]
    count = Int(base[first(eocd)+10]) | (Int(base[first(eocd)+11]) << 8)
    cd_size = sum(Int(base[first(eocd)+11+k]) << (8 * (k - 1)) for k in 1:4)
    cd_off = sum(Int(base[first(eocd)+15+k]) << (8 * (k - 1)) for k in 1:4)
    le64(v) = vcat(le32(v & 0xffffffff), le32(v >> 32))
    record = vcat(B("PK\x06\x06"), le64(44), le16(45), le16(45), le32(0), le32(0), le64(count), le64(count), le64(cd_size), le64(cd_off))
    locator(disks) = vcat(B("PK\x06\x07"), le32(0), le64(length(body)), le32(disks))
    ending = vcat(le32(0x06054b50), le16(0), le16(0), le16(0xffff), le16(0xffff), le32(0xffffffff), le32(0xffffffff), le16(0))
    fbytes("zip64 end records", vcat(body, record, locator(1), ending))
    fbytes("zip64 on two disks", vcat(body, record, locator(2), ending))
    fbytes("zip64 locator, no record", vcat(body, B("PK\x06\x06")[1:2], locator(1), ending))
end

# Archives damaged at random, mostly in their headers.
let m = Mix(0xa5c1)
    bases = [zip_bytes([(name=".version", data=B("version=6.5")), model_entry(), (name="simulation/r.dta", data=B("x"^40))]),
             zip_bytes([model_entry(method=0)])]
    for k in 1:40
        data = copy(pick(m, bases))
        for _ in 1:pick(m, (1, 1, 2, 3))
            starts = [i for i in 1:length(data)-1 if data[i] == 0x50 && data[i+1] == 0x4b]
            i = chance(m, 0.7) && !isempty(starts) ? min(length(data), pick(m, starts) + Int(next!(m) % 46)) :
                Int(next!(m) % UInt64(length(data))) + 1
            data[i] = pick(m, (0x00, 0xff, 0x01, 0x7f, 0x80, 0x3f, UInt8(next!(m) & 0xff)))
        end
        fbytes("damaged archive $k", data)
    end
end

# --- the pieces -------------------------------------------------------------------------------------

byte_strings = Vector{UInt8}[
    UInt8[], B("plain"), B("é€😀"), UInt8[0x41, 0xc3], UInt8[0xc3], UInt8[0xc0, 0x80], UInt8[0xc2, 0x41], UInt8[0xe0, 0x80, 0x80],
    UInt8[0xe0, 0xa0], UInt8[0xe0, 0x9f, 0x80], UInt8[0xed, 0xa0, 0x80], UInt8[0xed, 0x9f, 0xbf], UInt8[0xed, 0x9f],
    UInt8[0xef, 0xbb, 0xbf, 0x41], UInt8[0xef, 0xbb, 0xbf, 0xef, 0xbb, 0xbf, 0x41], UInt8[0xf0, 0x80, 0x80, 0x80],
    UInt8[0xf0, 0x90, 0x80], UInt8[0xf0, 0x90], UInt8[0xf0, 0x8f], UInt8[0xf4, 0x90, 0x80, 0x80], UInt8[0xf4, 0x8f, 0xbf, 0xbf],
    UInt8[0xf4, 0x8f, 0x41], UInt8[0xf5, 0x80], UInt8[0xff], UInt8[0x80, 0x80], UInt8[0xe2, 0x82, 0x28], UInt8[0xf0, 0x9f, 0x98],
    UInt8[0xfe, 0xff, 0x00, 0x41, 0xd8, 0x3d, 0xde, 0x00, 0xdc, 0x00, 0xd8, 0x00, 0x00, 0x41, 0xd8, 0x00],
    UInt8[0xfe, 0xff, 0x00, 0x41, 0x00], UInt8[0xff, 0xfe, 0x41, 0x00, 0x00, 0xd8], UInt8[0xff, 0xfe, 0x41, 0x00, 0x00, 0xd8, 0x41],
    UInt8[0xff, 0xfe, 0xff, 0xfe, 0x41, 0x00], UInt8[0xfe, 0xff, 0xfe, 0xff], UInt8[0xfe], UInt8[0xfe, 0xff],
]
let m = Mix(0xdec0)
    for k in 1:150
        n = Int(next!(m) % 24)
        bs = rand_bytes(m, n)
        # Lean towards the bytes UTF-8 and UTF-16 are made of.
        for i in eachindex(bs)
            chance(m, 0.5) && (bs[i] = pick(m, (0x41, 0x80, 0xbf, 0xc2, 0xdf, 0xe0, 0xed, 0xef, 0xf0, 0xf4, 0xd8, 0xdc, 0x00, 0xfe, 0xff, 0xa0, 0x9f)))
        end
        push!(byte_strings, bs)
    end
end
decoders = Any[]
for bs in byte_strings
    strict = try
        hex(codeunits(K._eco_utf8_strict(bs)))
    catch e
        e isa K._EcoDecodeError || rethrow()
        "error:" * e.msg
    end
    push!(decoders, J("in" => hex(bs), "valid" => isvalid(String, bs), "replace" => hex(codeunits(K._eco_utf8_replace(bs))), "strict" => strict,
                      "be" => hex(codeunits(K._eco_utf16_replace(bs, 1, false))), "le" => hex(codeunits(K._eco_utf16_replace(bs, 1, true))),
                      "be3" => hex(codeunits(K._eco_utf16_replace(bs, 3, false))), "xml" => hex(codeunits(K.decode_eco_xml_bytes(bs)))))
end

number_texts = ["", " ", "12", " 12 ", "\u00a012\u2028", "0x1A", "0X1a", "0x", "0x0x1F", "0x1_0", "0o17", "0O7", "0o8", "0b101", "0b2", "0B11",
                "-0x1A", "+5", "-5", ".5", "5.", ".", "1e", "1e+", "1e-400", "1e400", "-1e400", "4e-320", "Infinity", "-Infinity", "+Infinity",
                "infinity", "NaN", "inf", "1_000", "\x1c12", "1.0000000000000002", "9007199254740993", "-792842341234.23404823434",
                "123456789012345678901234567890", "0x" * "f"^20, "0x" * "1" * "0"^13 * "1", "0b" * "1"^60, "0o" * "7"^30, "1e21", "1e-7",
                "0.1", "2.5", "-0", "00012", "1.5e+3", "1.5E-3", "e5", "5e", "--5", "+-5", "0x1g", "abc", "1,5", "1 5", "\ufeff7"]
let m = Mix(0x0123)
    for k in 1:60
        push!(number_texts, string(pick(m, ("", "-", "+", " ")), Int(next!(m) % 100000), pick(m, ("", ".", ".5", ".25e3", "e-2", "E+10")),
                                   pick(m, ("", " ", "\u00a0"))))
    end
end
numbers = Any[J("in" => t, "number" => bits(K._eco_to_number(t)), "pdf" => bits(K._eco_pdf_string_to_number(t))) for t in number_texts]

doubles = Float64[0.0, -0.0, 1.0, -1.0, 1.25, 1000500, 1001000, 0.0001234565, 123456.5, 1e21, 1e-7, 5e-324, 1.7976931348623157e308,
                  2.5, 0.5, 9.9999995, 99999.95, 999999.5, 0.30000000000000004, 1 / 3, 2 / 3, 1e300, 1e-300, NaN, Inf, -Inf, 4.35, 0.145]
let m = Mix(0x4567)
    for k in 1:120
        push!(doubles, ldexp(Float64(next!(m) >> 11) * 0x1p-53 * 2 - 1, Int(next!(m) % 140) - 70))
    end
end
rounding = Any[J("x" => bits(x), "digits" => d, "out" => bits(K._eco_round_significant(x, d))) for x in doubles for d in (4, 6)]
exponential = Any[J("x" => bits(x), "out" => K._eco_to_exponential(x)) for x in doubles]
date_ms = Float64[0, 1, -1, 1621966224401, 951782400000, 4102444800000, 253402300799999, 253402300800000, 8.64e15, -8.64e15, 8.64e15 + 1,
                  -62135596800001, 1e12 + 0.5, NaN, Inf, 86399999, -86400000, -86400001]
dates = Any[]
for ms in date_ms
    out = try
        K._eco_iso_date(ms)
    catch e
        e isa ArgumentError || rethrow()
        "error:" * e.msg
    end
    push!(dates, J("ms" => bits(ms), "out" => out))
end

string_texts = ["", "plain", "  pad  ", "\u2028 x\u00a0y \ufeff", "\u3000\u1680\u2000\u200a\u202f\u205f a \u0085", "\t\n\v\f\r x \x1c",
                "ΟΔΟΣ", "οδος", "ΑΣ ΣΑ Σ", "ΑΣ.", "Α'Σ'", "ΑΣ\u0301", "ΑΣ\u0301Α", "straße", "ﬆiff", "İstanbul", "ǅ ǆ Ǆ", "Ꭰ ꭰ",
                "ı ſ K Å", "😀 a 😀", "\U1F600\U1F601", "a.b-c d", "ŉ ǰ ẖ", "ΐ ΰ", "ᾀ ᾈ ᾳ ῼ", "ﬀ ﬁ ﬂ ﬃ ﬄ", "Ω ω", "ꞵ Ꞵ", "𐐀 𐐨",
                "Σ", "aΣ", "Σa", "ᾼΣ", "AΣ:", "AΣ.B", "Ⓐ", "ⓐΣ", "ΣΣ", "x\u00adΣ", "\u0345Σ"]
strings = Any[]
for s in string_texts
    pos = Int[K._eco_utf16_pos(s, i) for i in 1:ncodeunits(s)+1]
    push!(strings, J("in" => s, "trim" => K._eco_js_trim(s), "len" => K._eco_js_len(s), "identifier" => K._eco_js_identifier(s),
                     "lower" => K._eco_py_lower(s), "upper" => K._eco_py_upper(s), "pos" => pos))
end

# Every code point on its own, through each mapping: a hash of them all.
case_texts = Dict{String,String}()
let lower = IOBuffer(), upper = IOBuffer(), jl = IOBuffer(), ju = IOBuffer(), flags = IOBuffer()
    for c in 0:0x10ffff
        0xd800 <= c <= 0xdfff && continue
        ch = Char(c)
        s = string(ch)
        write(lower, K._eco_py_lower(s), '\0')
        write(upper, K._eco_py_upper(s), '\0')
        write(jl, lowercase(ch))
        write(ju, uppercase(ch))
        write(flags, UInt8(K._eco_is_cased(ch)) | (UInt8(K._eco_is_case_ignorable(ch)) << 1))
    end
    for (k, io) in (("lower", lower), ("upper", upper), ("julia_lower", jl), ("julia_upper", ju), ("flags", flags))
        case_texts[k] = kept(take!(io))
    end
end

collation_words = ["a_", "a0", "aA", "aa", "a", "A", "_a", "B", "b", "Ab", "aB", "AB", "ab", "L_1", "L1", "L10", "L2", "Z9", "z_", "__", "_",
                   "_0", "0", "Nuclides", "Landscape_objects", "nuclides", "é", "E", "e", "ä", "-", "z"]
collated = sort(collation_words; by=K._eco_collation_key)

entity_texts = ["", "plain", "&amp;", "&amp", "&#65;&#x41;&#X41;&#x;&#;", "&#1114111;&#1114112;&#xD7FF;&#xD800;&#xDFFF;&#xE000;",
                "&nbsp;&lt;&gt;&quot;&apos;", "a&b;c&&d;;", "&#12a;&#0;&#x0;", "&#99999999999999999999;", "&#xFFFFFFFFFFFFFFFF1;",
                "&x41;&#x1F600;", "&AMP;&Amp;", "&#00065;", "&&#65;", "&#6&#65;"]
entities = Any[J("in" => t, "out" => K._eco_decode_entities(t)) for t in entity_texts]

# The XML reader: every element of a document, or where it gave up.
function xml_dump(src)
    root = try
        K.parse_eco_xml(src)
    catch e
        e isa K.EcoXMLError || rethrow()
        return "error:" * e.message * "|" * (e.position === nothing ? "none" : string(e.position))
    end
    io = IOBuffer()
    walk(n, d) = begin
        print(io, "E ", d, " ", ncodeunits(n.name), ":", n.name, " ", n.self_closing ? 1 : 0, " ", length(n.attrs))
        for (k, v) in n.attrs
            print(io, " ", ncodeunits(k), ":", k, "=", ncodeunits(v), ":", v)
        end
        t = K._eco_text(n)
        r = K._eco_trimmed_text(n)
        print(io, " T", ncodeunits(t), ":", t, " R", ncodeunits(r), ":", r, "\n")
        for c in n.children
            walk(c, d + 1)
        end
    end
    walk(root, 0)
    return String(take!(io))
end
xml_texts = String[]
append!(xml_texts, ["<a>\U1F600</b>", "<a x=\"1\" x=\"2\"><![CDATA[&amp;]]>&amp;</a>", "<a x=\"1\" y=\"0\" x=\"2\"/>",
                    "<a> one <!-- two --> three <![CDATA[ four ]]><b/> five &lt; </a>", "<a\u2028b=\"1\"/>", "<a b\u00a0=\"1\"/>",
                    "<a/ >", "<a / >", "<a b='\"'/>", "<a>&amp;&#xZZ;</a >", "<a><b></a></b>", "<!---->", "<!-- -- --><a/>", "<a><!--->--></a>",
                    "<a><?pi ?>t</a>", "<a><!X>t</a>", "<a/>trailing", "lead<a/>", "<a></a>\n<!-- after -->", "<a b=\"&#0;\"/>"])
xmls = Any[]
for c in xml_cases
    push!(xmls, J("case" => c.name, "out" => answer("xml $(c.name)", xml_dump(c.payload))))
end
for (k, t) in enumerate(xml_texts)
    push!(xmls, J("in" => t, "out" => answer("xml $k", xml_dump(t))))
end

pdf_texts = [("logt(min=1,max=9,mode=3)", ""), ("logt(min=1,max=9,mode=3)", "logdt"), ("logn(gm=1,gsd=2, trmin=0.1)", ""),
             ("logn(p1=0.05,x1=1e-3,p2=0.95,x2=0.1,pmin=0.01)", ""), ("logn(mean=1, sd=2)", ""), ("logn(mean=1,sd=2)", "Logn4"),
             ("logn( gsd )", ""), ("logn(x1)", ""), ("pg(values=1;2;x;3, inorder=false,pos=2)", ""), ("pg(values=,pos=x)", ""),
             ("pg()", "pg"), (" norm (mean=0x10, sd=0b11, group= g 1 ) ", ""), ("norm(mean=1,sd=2", ""), ("norm mean=1)", ""),
             ("9norm(mean=1)", ""), ("_x(a=1)", ""), ("unif(min=1,max=2,inorder=False)", "weird"), ("triang(min=1,max=3,mode=2,pos=Infinity)", ""),
             ("dtriang(=1,min=,max=1e400,mode=-Infinity)", ""), ("logu(min=1e-5,max=1e-3,trmin=,trmax= 7 ,pmin=0.1,pmax=0.9)", ""),
             ("logdt(min=1,max=2,mode=1.5)", ""), ("weibull(a=1,b=2)", ""), ("", "unif"), ("unif\u00a0(min=1)", ""), ("unif(min=1)(", ""),
             ("unif(min=1,min=2)", ""), ("pg(values= 1 ; 0x1F ;; 1e400; -2 )", "pg"), ("logn(p1=1)", "logn")]
pdfs = Any[]
for (expr, fn) in pdf_texts
    spec = K._eco_parse_pdf(expr, fn)
    push!(pdfs, J("expr" => expr, "function" => fn, "out" => spec === nothing ? "nothing" : K.json_text(spec; indent=0)))
end

version_texts = ["version=6.5", "a=1\nversion = 6.5.85 x", "xversion=1", "xversion=1 version=2", "version", "version=", "version= ;",
                 "\u3000version\u00a0=\u2028v-1_a.b", "Version=1", "  version  =  7  ", "version=6.5\u00a0", "é version=9"]
versions = Any[J("in" => t, "out" => K._eco_version_in(t)) for t in version_texts]

# Raw deflate streams inflated within limits, as eco_zip.jl inflates them.
streams = Vector{UInt8}[]
let m = Mix(0x1f1a)
    texts = [B(MINIMAL), B("a"^5000), UInt8[], rand_bytes(m, 1000), B(repeat("abcdefgh", 600))]
    for t in texts, level in (0, 1, 6, 9)
        push!(streams, K.deflate_bytes(t; level))
    end
    push!(streams, zeros_deflate(0), zeros_deflate(1), zeros_deflate(2), zeros_deflate(3), zeros_deflate(259), zeros_deflate(70000))
    push!(streams, UInt8[0x07, 0x00], UInt8[0x01, 0x05, 0x00, 0x05, 0x00, 0x61], UInt8[0x63, 0x00, 0x42, 0x00], UInt8[0x05, 0xff, 0xff],
          UInt8[0x05, 0xe0, 0xff, 0xff, 0xff, 0x0f], UInt8[0xfd, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff], UInt8[0x03], UInt8[], UInt8[0x02],
          UInt8[0x00, 0x00, 0x00, 0xff, 0xff], UInt8[0x01, 0x00, 0x00, 0xff, 0xff, 0x41])
    for k in 1:50
        s = copy(pick(m, streams[[1:20; 21:31]]))
        isempty(s) && continue
        r = next!(m) % 3
        if r == 0
            s = s[1:Int(next!(m) % UInt64(length(s))) + 1]
        else
            for _ in 1:Int(next!(m) % 3) + 1
                i = Int(next!(m) % UInt64(length(s))) + 1
                s[i] = r == 1 ? (s[i] ⊻ UInt8(1 << (next!(m) % 8))) : UInt8(next!(m) & 0xff)
            end
        end
        push!(streams, s)
    end
end
const LIMITS = ((1 << 20, 0), (1 << 20, 100000), (100, 0), (1, 0), (1025, 1024), (2000, 0), (4097, 70000))
inflates = Any[]
for s in streams
    runs = Any[]
    for (max_length, hint) in LIMITS
        out, eof, damage = K._eco_raw_inflate(s, max_length, hint)
        push!(runs, J("max" => max_length, "hint" => hint, "out" => kept(out), "eof" => eof, "damage" => damage))
    end
    push!(inflates, J("in" => hex(s), "runs" => runs))
end

# Archives read entry by entry.
function archive_dump(bytes)
    a = try
        K._eco_unzip(bytes)
    catch e
        e isa K.EcoImportError && return "error:EcoImportError:" * e.msg
        e isa ErrorException && return "error:ErrorException:" * e.msg
        rethrow()
    end
    io = IOBuffer()
    for name in K._eco_names(a)
        print(io, ncodeunits(name), ":", name, " ")
        got = try
            kept(K._eco_get(a, name))
        catch e
            e isa K.EcoImportError || rethrow()
            "error:" * e.msg
        end
        print(io, got, "\n")
    end
    return String(take!(io))
end
archives = Any[]
for (k, c) in enumerate(file_cases)
    bytes = segments_bytes(c.segments)
    push!(archives, J("name" => c.name, "out" => answer("archive $(c.name)", archive_dump(bytes))))
end

# --- whole imports ---------------------------------------------------------------------------------

"""An import's answer: the project and the report as JSON, or the refusal in its words."""
function import_answer(f)
    try
        project, report = f()
        return K.json_text(project) * "\n" * K.json_text(K.to_dict(report))
    catch e
        e isa K.EcoImportError && return "error:EcoImportError:" * e.msg
        e isa ArgumentError && return "error:ArgumentError:" * e.msg
        e isa ErrorException && return "error:ErrorException:" * e.msg
        rethrow()
    end
end

imports = Any[]
for c in xml_cases
    out = import_answer(() -> K.import_model_xml(c.payload; file_name=c.file_name, version=c.version))
    push!(imports, J("name" => c.name, "kind" => "xml", "payload" => c.payload, "file_name" => c.file_name, "version" => c.version,
                     "out" => answer("import $(c.name)", out)))
end
for c in file_cases
    bytes = segments_bytes(c.segments)
    out = import_answer(() -> K.import_eco_file(bytes; file_name=c.file_name, version=c.version))
    push!(imports, J("name" => c.name, "kind" => "file", "payload" => c.segments, "size" => length(bytes), "bytes" => kept(bytes),
                     "file_name" => c.file_name, "version" => c.version, "out" => answer("import $(c.name)", out)))
end

# --- the synthetic directory --------------------------------------------------------------------------

path = joinpath(@__DIR__, "..", "tests", "fixtures", "ecoimport.json")
const DIR = get(ENV, "KOMPARTMENT_ECO_FIXTURES", "")
directory = Any[]
if isempty(DIR)
    if isfile(path)
        old = K.parse_json(read(path, String))
        directory = Any[d for d in old["directory"]]
    end
    println("KOMPARTMENT_ECO_FIXTURES not set: the synthetic directory's $(length(directory)) cases already in the fixture file are kept")
else
    manifest = K.parse_json(read(joinpath(DIR, "manifest.json"), String))
    for rec in manifest
        rec["source"] == "synthetic" || continue
        base = joinpath(DIR, "cases", rec["id"])
        kind = rec["kind"]
        # A file read by its path is looked for beside the cases, wherever the directory now is.
        source = kind == "path" ? joinpath(DIR, "cases", basename(rec["path"])) : base * ".payload"
        payload = read(source)
        out = import_answer() do
            if kind == "xml"
                K.import_model_xml(String(copy(payload)); file_name=rec["file_name"], version=rec["version"])
            elseif kind == "file"
                K.import_eco_file(payload; file_name=rec["file_name"], version=rec["version"])
            else
                K.import_eco_file(source; version=rec["version"])
            end
        end
        push!(directory, J("id" => rec["id"], "label" => rec["label"], "kind" => kind, "payload" => kept(payload),
                           "out" => answer("directory $(rec["id"])", out)))
    end
end

isempty(DUMPS) || write(joinpath(DUMPS, "ecoimport.julia.txt"), join(TABLE, "\n"))
write(path, K.json_text(J("decoders" => decoders, "numbers" => numbers, "rounding" => rounding, "exponential" => exponential,
                          "dates" => dates, "strings" => strings, "case" => J((k => case_texts[k] for k in sort(collect(keys(case_texts))))...),
                          "collation" => J("words" => collation_words, "sorted" => collated), "entities" => entities, "xml" => xmls,
                          "pdf" => pdfs, "versions" => versions, "inflate" => inflates, "archives" => archives, "imports" => imports,
                          "directory" => directory); indent=0))
println(path, ": ", length(imports), " imports (", length(xml_cases), " model texts, ", length(file_cases), " files), ",
        length(directory), " of the synthetic directory, ", length(decoders), " byte strings, ", length(numbers), " numbers, ",
        length(xmls), " XML documents, ", length(pdfs), " distributions, ", length(inflates), " deflate streams, ", length(archives), " archives")
