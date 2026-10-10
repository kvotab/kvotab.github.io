# Units in equations: parsing them, the unit an equation comes out in, and a
# number written with a unit (`0.01[m]`) scaled to the unit of what it is
# added to (kompartment/python/kompartment/engine/unitcheck.py, a port of
# src/domain/unitcheck.js).
#
# A unit is a product of powers of symbols times a scale (`km` is m^1 x 1000,
# `g` is kg^1 x 0.001); two units are the same quantity when their powers
# agree, and the same unit when the scales agree too. A literal is converted
# to the unit of what it is added to, compared with or chosen against, when
# that unit is known: `p1 + 1000[mm]` with `p1` in metres is `p1 + 1`.

const _UNIT_NONE = Set(["", "-", "[-]", "1", "unitless", "dimensionless", "none", "n/a", "[]"])
const UNIT_ALIAS = Dict(
    "y" => "year", "yr" => "year", "years" => "year", "a" => "year",
    "sec" => "s", "second" => "s", "seconds" => "s",
    "hour" => "h", "hours" => "h",
    "day" => "d", "days" => "d",
    "litre" => "L", "liter" => "L", "l" => "L",
    "Bequerel" => "Bq", "becquerel" => "Bq",
    "Mole" => "mol", "mole" => "mol", "moles" => "mol",
    "Sievert" => "Sv", "sievert" => "Sv",
    "kilogram" => "kg", "kilograms" => "kg",
    "metre" => "m", "meter" => "m", "metres" => "m", "meters" => "m",
)
const UNIT_PREFIX = (("T", 1e12), ("G", 1e9), ("M", 1e6), ("k", 1e3), ("d", 1e-1), ("c", 1e-2), ("m", 1e-3),
                     ("u", 1e-6), ("µ", 1e-6), ("μ", 1e-6), ("n", 1e-9), ("p", 1e-12))
const UNIT_PREFIXABLE = Set(["Bq", "Sv", "Gy", "g", "kg", "m", "mol", "L", "s", "J", "W", "Pa", "Ci"])

"""A unit: powers of symbols, and a scale."""
struct Dim
    powers::OrderedDict{String,Int}
    scale::Float64
end
Dim() = Dim(OrderedDict{String,Int}(), 1.0)
Dim(powers::AbstractDict) = Dim(OrderedDict{String,Int}(powers), 1.0)

is_one(d::Dim) = isempty(d.powers) && d.scale == 1

function dim_times(a::Dim, b::Dim, sign::Int=1)
    out = copy(a.powers)
    for (sym, n) in b.powers
        nxt = get(out, sym, 0) + n * sign
        if nxt == 0
            delete!(out, sym)
        else
            out[sym] = nxt
        end
    end
    return Dim(out, sign > 0 ? a.scale * b.scale : a.scale / b.scale)
end
dim_over(a::Dim, b::Dim) = dim_times(a, b, -1)

"""`d` to the power `n`, or `nothing` where a symbol would get a power that is not whole."""
function dim_pow(d::Dim, n::Real)
    n == 0 && return Dim()
    out = OrderedDict{String,Int}()
    for (sym, e) in d.powers
        nxt = e * n
        (isfinite(nxt) && isinteger(nxt)) || return nothing
        out[sym] = Int(nxt)
    end
    # Python's float `**`, which is the C library's pow.
    return Dim(out, cpow(d.scale, Float64(n)))
end

function same_kind(a::Dim, b)
    (b === nothing || length(a.powers) != length(b.powers)) && return false
    return all(p -> get(b.powers, p[1], nothing) == p[2], a.powers)
end

dim_factor(a::Dim, b::Dim) = a.scale / b.scale

dim_equals(a::Dim, b) = same_kind(a, b) && abs(dim_factor(a, b) - 1) < 1e-9

"""`Number.prototype.toExponential()` with no argument."""
function _to_exponential(v::Float64)
    v == 0 && return "0e+0"
    digits, n = shortest_digits(abs(v))
    e = n - 1
    body = length(digits) == 1 ? digits : digits[1:1] * "." * digits[2:end]
    return (v < 0 ? "-" : "") * body * "e" * (e >= 0 ? "+" : "-") * string(abs(e))
end

"""A unit's scale in a message: `1000`, `0.001`, `1e+6`."""
function scale_text(scale::Float64)
    s = parse(Float64, @sprintf("%.12g", scale))
    1e-3 <= scale < 1e6 && return js_number(s)
    return replace(_to_exponential(s), r"\.?0+e" => "e")
end

function Base.string(d::Dim)
    is_one(d) && return "unitless"
    up = sort!([(s, n) for (s, n) in d.powers if n > 0])
    down = sort!([(s, n) for (s, n) in d.powers if n < 0])
    part(p) = abs(p[2]) == 1 ? p[1] : "$(p[1])^$(js_number(abs(p[2])))"
    (isempty(up) && isempty(down)) && return "×$(scale_text(d.scale))"
    top = isempty(up) ? "1" : join((part(p) for p in up), "*")
    lead = d.scale == 1 ? "" : "$(scale_text(d.scale)) "
    isempty(down) && return "$lead$top"
    bottom = join((part(p) for p in down), "*")
    return "$lead$top/$(length(down) > 1 ? "(" * bottom * ")" : bottom)"
end
Base.show(io::IO, d::Dim) = print(io, "Dim(", string(d), ")")

_mass_dim(base::String, scale::Float64) = base == "g" ? Dim(OrderedDict("kg" => 1), scale * 1e-3) :
                                          Dim(OrderedDict(base => 1), scale)

function _prefixed(name::String)
    for (pre, scale) in UNIT_PREFIX
        (!startswith(name, pre) || length(name) == length(pre)) && continue
        rest = name[nextind(name, 0, length(pre) + 1):end]
        base = get(UNIT_ALIAS, rest, rest)
        base == "kg" && continue
        base in UNIT_PREFIXABLE && return _mass_dim(base, scale)
    end
    return nothing
end

_is_unit_letter(c::Char) = ('A' <= c <= 'Z') || ('a' <= c <= 'z') || c == 'µ' || c == 'μ'
_is_ascii_digit(c::Char) = '0' <= c <= '9'

function _symbol_dim(raw::AbstractString)
    sym = String(strip(raw))
    isempty(sym) && return Dim()
    lowercase(sym) in _UNIT_NONE && return Dim()
    # `m3`, `km2`: a length with a power written after it.
    chars = collect(sym)
    if length(chars) >= 2 && _is_ascii_digit(chars[end]) && all(_is_unit_letter, chars[1:end-1])
        base = _symbol_dim(String(chars[1:end-1]))
        if length(base.powers) == 1 && haskey(base.powers, "m")
            return dim_pow(base, chars[end] - '0')
        end
    end
    name = get(UNIT_ALIAS, sym, sym)
    name in UNIT_PREFIXABLE && return _mass_dim(name, 1.0)
    p = _prefixed(name)
    return p === nothing ? Dim(OrderedDict(name => 1), 1.0) : p
end

"""
    parse_unit(text) -> Union{Dim,Nothing}

A unit's text as a `Dim`, or `nothing` when it cannot be read: `kg/m3`,
`m^2/year`, `mol per kg`, `1/(m*s)`, `[Bq]`.
"""
function parse_unit(text)
    src = String(strip(text === nothing ? "" : _norm_str(text)))
    lowercase(src) in _UNIT_NONE && return Dim()
    if length(src) >= 2 && first(src) == '[' && last(src) == ']'
        src = String(strip(src[nextind(src, 1):prevind(src, lastindex(src))]))
    end
    lowercase(src) in _UNIT_NONE && return Dim()
    s = collect(src)
    len = length(s)
    max_depth = 32
    at = 1          # 1-based: the next character to read
    depth = 0
    peekc() = at <= len ? s[at] : '\0'
    skip() = (while at <= len && s[at] == ' '; at += 1; end)
    function number()
        k = at
        (k <= len && (s[k] == '+' || s[k] == '-')) && (k += 1)
        k <= len && _is_ascii_digit(s[k]) || return nothing
        while k <= len && _is_ascii_digit(s[k])
            k += 1
        end
        if k + 1 <= len && s[k] == '.' && _is_ascii_digit(s[k+1])
            k += 1
            while k <= len && _is_ascii_digit(s[k])
                k += 1
            end
        end
        v = parse(Float64, String(s[at:k-1]))
        at = k
        return v
    end
    ident_start(c) = _is_unit_letter(c) || c == '_' || c == '%'
    ident_part(c) = ident_start(c) || _is_ascii_digit(c) || c == '.'
    local expr
    function factor()
        skip()
        if at <= len && s[at] == '('
            depth >= max_depth && return nothing
            at += 1
            depth += 1
            inner = expr()
            depth -= 1
            skip()
            (at > len || s[at] != ')') && return nothing
            at += 1
            return inner
        end
        if at <= len && ident_start(s[at])
            k = at + 1
            while k <= len && ident_part(s[k])
                k += 1
            end
            word = String(s[at:k-1])
            at = k
            word == "per" && return nothing
            dim = _symbol_dim(word)
            # A bare negative power: `s-1`.
            if at + 1 <= len && s[at] == '-' && _is_ascii_digit(s[at+1])
                k = at + 1
                while k <= len && _is_ascii_digit(s[k])
                    k += 1
                end
                p = parse(Float64, String(s[at:k-1]))
                at = k
                dim = dim === nothing ? nothing : dim_pow(dim, p)
            end
            return dim
        end
        n = number()
        return n === nothing ? nothing : Dim()
    end
    function term()
        base = factor()
        base === nothing && return nothing
        before = at
        skip()
        (at > len || s[at] != '^') && (at = before)
        if at <= len && s[at] == '^'
            at += 1
            skip()
            local n
            if at <= len && s[at] == '('
                at += 1
                n = number()
                skip()
                if n !== nothing && at <= len && s[at] == '/'
                    at += 1
                    skip()
                    d = number()
                    (d === nothing || d == 0) && return nothing
                    n /= d
                    skip()
                end
                (n === nothing || at > len || s[at] != ')') && return nothing
                at += 1
            else
                n = number()
            end
            n === nothing && return nothing
            base = dim_pow(base, n)
            base === nothing && return nothing
        end
        return base
    end
    function per_word()
        (at + 2 <= len && s[at] == 'p' && s[at+1] == 'e' && s[at+2] == 'r') || return false
        at + 3 > len && return true
        c = s[at+3]
        return !(isletter(c) || isdigit(c) || c == '_' || isnumeric(c))
    end
    expr = function ()
        out = term()
        out === nothing && return nothing
        while true
            save = at
            skip()
            ch = peekc()
            if ch == '*' || ch == '·'
                at += 1
                nxt = term()
                nxt === nothing && return nothing
                out = dim_times(out, nxt)
            elseif ch == '/'
                at += 1
                nxt = term()
                nxt === nothing && return nothing
                out = dim_over(out, nxt)
            elseif per_word()
                at += 3
                rest = expr()
                rest === nothing && return nothing
                return dim_over(out, rest)
            elseif ch != '\0' && (ident_start(ch) || ch == '(') && save != at
                nxt = term()
                nxt === nothing && return nothing
                out = dim_times(out, nxt)
            else
                at = save
                break
            end
        end
        return out
    end
    value = expr()
    skip()
    return (value !== nothing && at > len) ? value : nothing
end

"""Whether two unit texts are the same unit."""
function same_unit(a, b)
    x, y = parse_unit(a), parse_unit(b)
    return x !== nothing && y !== nothing && dim_equals(x, y)
end

struct UnitClash <: Exception
    message::String
end
Base.showerror(io::IO, e::UnitClash) = print(io, e.message)

function _clash_note(l, r)
    (l === nothing || !same_kind(l, r)) && return ""
    f = dim_factor(l, r)
    return " — the same quantity, a factor of $(scale_text(f >= 1 ? f : 1 / f)) apart; only a literal written " *
           "directly against the other side is converted, so the factor is yours to write in here"
end

function _agree(dims, what)
    out = nothing
    for d in dims
        d === nothing && return nothing
        if out === nothing || is_one(out)
            out = d
            continue
        end
        (is_one(d) || dim_equals(out, d)) && continue
        throw(UnitClash("$what do not agree: $(string(out)) and $(string(d))"))
    end
    return out
end

const UNIT_PURE = Set(["exp", "log", "log10", "log2", "ln", "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
                       "tanh", "asinh", "acosh", "atanh", "erf", "erfc", "factorial", "binomial"])
const UNIT_SAME = Set(["abs", "fabs", "ceil", "floor", "round", "fix", "min", "max", "mean", "percentile"])
const UNIT_CLOCK = Set(["time", "start_time", "end_time"])
const _UNIT_COMPARE = Set(["==", "!=", "<", ">", "<=", ">=", "~=", "&&", "||"])

"""
    equation_unit(ast, unit_of, time_dim) -> (dim, clash)

The unit an equation comes out in (`nothing` when it cannot be known), or the
clash that stops it having one. `unit_of(name)` is the `Dim` of a block as
written in the equation, or `nothing`.
"""
function equation_unit(ast::ENode, unit_of, time_dim)
    function walk(node)
        node === nothing && return nothing
        if node isa ENum
            node.dim !== nothing && return node.dim
            node.unit === nothing && return Dim()
            return parse_unit(node.unit)
        elseif node isa ERef
            return unit_of(node.name)
        elseif node isa EUnary
            return node.op == "!" ? Dim() : walk(node.operand)
        elseif node isa EBinary
            op = node.op
            if op in _UNIT_COMPARE
                l = walk(node.left)
                r = walk(node.right)
                if l !== nothing && r !== nothing && !is_one(l) && !is_one(r) && !dim_equals(l, r)
                    throw(UnitClash("$(string(l)) and $(string(r)) cannot be compared$(_clash_note(l, r))"))
                end
                return Dim()
            end
            l = walk(node.left)
            r = walk(node.right)
            (op == "*" || op == ".*") && return (l !== nothing && r !== nothing) ? dim_times(l, r) : nothing
            (op == "/" || op == "./") && return (l !== nothing && r !== nothing) ? dim_over(l, r) : nothing
            if op == "^" || op == ".^"
                l === nothing && return nothing
                is_one(l) && return Dim()
                node.right isa ENum || return nothing
                return dim_pow(l, node.right.value)
            end
            (l === nothing || r === nothing) && return nothing
            is_one(l) && return r
            is_one(r) && return l
            dim_equals(l, r) ||
                throw(UnitClash("$(string(l)) and $(string(r)) cannot be $(op == "-" ? "subtracted" : "added")$(_clash_note(l, r))"))
            return l
        elseif node isa ECond
            walk(node.test)
            return _agree(Any[walk(node.then), walk(node.otherwise)], "the two results")
        elseif node isa ECall
            name = node.name
            args = Any[walk(a) for a in node.args]
            name in UNIT_CLOCK && return time_dim
            if name in UNIT_PURE
                a = isempty(args) ? nothing : args[1]
                (a !== nothing && !is_one(a)) && throw(UnitClash("$name needs a plain number, not $(string(a))"))
                return Dim()
            end
            name == "sqrt" && return (!isempty(args) && args[1] !== nothing) ? dim_pow(args[1], 0.5) : nothing
            if name == "power" || name == "pow"
                (isempty(args) || args[1] === nothing) && return nothing
                is_one(args[1]) && return Dim()
                second = length(node.args) > 1 ? node.args[2] : nothing
                second isa ENum || return nothing
                return dim_pow(args[1], second.value)
            end
            name == "if" && return _agree(args[2:end], "the two results of if")
            if name == "rampUp" || name == "rampDown"
                _agree(args, "the argument and the two ends of $name")
                return Dim()
            end
            if name == "smoothUp" || name == "smoothDown"
                _agree(args[1:min(2, end)], "the argument and the half-way point of $name")
                if length(args) > 2 && args[3] !== nothing && !is_one(args[3])
                    throw(UnitClash("the sharpness of $name is a plain number, not $(string(args[3]))"))
                end
                return Dim()
            end
            (name == "mod" || name == "rem") && return isempty(args) ? nothing : args[1]
            name in ("atan2", "sign", "sgn") && return Dim()
            name == "hypot" && return _agree(args, "the arguments of hypot")
            name in ("sum", "prod", "product") && return name == "sum" ? _agree(args, "the arguments of sum") : nothing
            name in UNIT_SAME && return _agree(args, "the arguments of $name")
            return nothing
        end
        return nothing
    end
    try
        return (dim=walk(ast), clash=nothing)
    catch e
        e isa UnitClash || rethrow()
        return (dim=nothing, clash=e.message)
    end
end

const _AGREE_OPS = Set(["+", "-", "==", "!=", "<", ">", "<=", ">=", "~="])
const _AGREE_CALLS = Set(["min", "max", "if", "ifelse"])

"""Whether an equation's tree holds a number written with a unit."""
function _has_unit_literal(node::ENode)
    stack = ENode[node]
    while !isempty(stack)
        n = pop!(stack)
        if n isa ENum
            n.unit !== nothing && return true
        elseif n isa ECall
            append!(stack, n.args)
        elseif n isa EUnary
            push!(stack, n.operand)
        elseif n isa EBinary
            push!(stack, n.left, n.right)
        elseif n isa ECond
            push!(stack, n.test, n.then, n.otherwise)
        end
    end
    return false
end
has_unit_literal(node::ENode) = _has_unit_literal(node)

"""
    scale_literals(ast, unit_of, time_dim) -> (converted, unconverted)

Converts, in place, each literal written with a unit to the unit of what it is
written against: added to, subtracted from, compared with, or chosen against
(`if`, `min`, `max`, `?:`).
"""
function scale_literals(ast::ENode, unit_of, time_dim)
    converted = Any[]
    unconverted = Any[]
    _has_unit_literal(ast) || return (converted=converted, unconverted=unconverted)
    function dim_of(node)
        try
            return equation_unit(node, unit_of, time_dim).dim
        catch
            return nothing     # the unit of this piece is simply not known
        end
    end
    literal(n) = n isa ENum && n.unit !== nothing && n.dim === nothing
    function against(lit::ENum, other)
        want = other === nothing ? nothing : dim_of(other)
        here = dim_of(lit)
        (here === nothing || is_one(here)) && return
        if want === nothing
            push!(unconverted, (value=lit.value, unit=lit.unit))
            return
        end
        (!same_kind(want, here) || dim_equals(want, here)) && return
        f = dim_factor(here, want)
        push!(converted, (value=lit.value, from=string(here), to=string(want), now=lit.value * f))
        lit.value *= f
        lit.dim = want
        return
    end
    function reconcile(nodes)
        lits = [n for n in nodes if literal(n)]
        isempty(lits) && return
        anchor = nothing
        for n in nodes
            if !literal(n) && dim_of(n) !== nothing
                anchor = n
                break
            end
        end
        if anchor === nothing
            for n in nodes
                if n !== lits[1]
                    anchor = n
                    break
                end
            end
        end
        for lit in lits
            lit === anchor && continue
            against(lit, anchor)
        end
    end
    function walk(node)
        if node isa EBinary
            walk(node.left)
            walk(node.right)
            node.op in _AGREE_OPS && reconcile(ENode[node.left, node.right])
        elseif node isa EUnary
            walk(node.operand)
        elseif node isa ECond
            walk(node.test)
            walk(node.then)
            walk(node.otherwise)
            reconcile(ENode[node.then, node.otherwise])
        elseif node isa ECall
            for a in node.args
                walk(a)
            end
            if node.name in _AGREE_CALLS
                args = collect(ENode, node.args)
                reconcile(node.name in ("if", "ifelse") ? args[2:end] : args)
            end
        end
        return
    end
    walk(ast)
    return (converted=converted, unconverted=unconverted)
end

"""Scales a literal written with a unit to the unit it is added to (the builder's `_scale_literals`)."""
function _scale_literals!(ast::ENode, b, system)
    _has_unit_literal(ast) || return
    tu = get(b.project.simulation, "time_unit", nothing)
    time_dim = parse_unit(py_truthy(tu) ? tu : "year")
    sys = py_truthy(system) ? string(system) : ""
    function unit_of(written)
        q = resolve_reference(_norm_str(written), sys, n -> haskey(b.unit_blocks, n))
        text = py_truthy(q) ? get(b.unit_blocks[q], "unit", nothing) : nothing
        return py_truthy(text) ? parse_unit(text) : nothing
    end
    scale_literals(ast, unit_of, time_dim)
    return
end
