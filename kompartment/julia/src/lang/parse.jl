# The equation language's parser (`parse` in src/parser/parser.js).
#
# The C family's precedence for everything except `^`, which binds tighter
# than unary minus and is left-associative (`2^3^2` is 64, `-a^2` is
# `-(a^2)`); a sign is allowed at the head of an exponent (`2^-1`); `~=` and
# `!=` are not-equal; `.*`, `./` and `.^` are `*`, `/`, `^`.

struct EquationParseError <: Exception
    message::String
    position::Int
    source::String
end
Base.showerror(io::IO, e::EquationParseError) = print(io, e.message)

"""A node of an equation's tree."""
abstract type ENode end

"""A number, and the unit written against it (`0.01[m]`), if any."""
mutable struct ENum <: ENode
    value::Float64
    unit::Union{Nothing,String}
    dim::Any
end
ENum(v::Real) = ENum(Float64(v), nothing, nothing)
ENum(v::Real, unit) = ENum(Float64(v), unit, nothing)

"""A reference to a block: one entry per bracket (`nothing` for `[]`), or a
dictionary naming a list outright (the reducing blocks build those). `scope`
is the sub-system a reference moved in by the function inliner was written in."""
struct ERef <: ENode
    name::String
    indices::Union{Vector{Union{Nothing,String}},Dict{String,String}}
    scope::Union{Nothing,String}
end
ERef(name, indices=Union{Nothing,String}[]) = ERef(String(name), indices, nothing)

struct ECall <: ENode
    name::String
    args::Vector{ENode}
    scope::Union{Nothing,String}
end
ECall(name, args) = ECall(String(name), args, nothing)

struct EUnary <: ENode
    op::String
    operand::ENode
end

struct EBinary <: ENode
    op::String
    left::ENode
    right::ENode
end

struct ECond <: ENode
    test::ENode
    then::ENode
    otherwise::ENode
end

const OP_ALIAS = Dict(".*" => "*", "./" => "/", ".^" => "^", "!=" => "~=")
const BINARY_PRECEDENCE = Dict("||" => 1, "&&" => 2, "==" => 3, "~=" => 3, "<" => 4, "<=" => 4, ">" => 4,
                               ">=" => 4, "+" => 5, "-" => 5, "*" => 6, "/" => 6)
const POWER_PRECEDENCE = 8

"""JavaScript's reading of a number token (`Number("1e-5")`)."""
_number_text(text::AbstractString) = parse(Float64, text)

mutable struct _Parser
    tokens::Vector{Token}
    pos::Int
    text::String
    calls::Any
    depth::Int
end

@inline _peek(p::_Parser) = p.tokens[p.pos]
@inline function _advance!(p::_Parser)
    tok = p.tokens[p.pos]
    p.pos += 1
    return tok
end
_shown(tok::Token) = tok.type === :eof ? "<end>" : tok.text

function _expect!(p::_Parser, kind::Symbol, what::String)
    tok = _peek(p)
    tok.type === kind || throw(EquationParseError("Expected $what but found '$(_shown(tok))'", tok.pos, p.text))
    return _advance!(p)
end

const MAX_NESTING = 2000

function _deeper!(p::_Parser)
    p.depth += 1
    if p.depth > MAX_NESTING
        throw(EquationParseError("This equation is nested too deeply to read. Split it into expression blocks, " *
                                 "which is also how anyone else will be able to follow it.", 0, p.text))
    end
end

function _args_until_rparen!(p::_Parser)
    out = ENode[]
    if _peek(p).type !== :rparen
        while true
            push!(out, _parse_ternary!(p))
            if _peek(p).type === :comma
                _advance!(p)
                continue
            end
            break
        end
    end
    _expect!(p, :rparen, "')'")
    return out
end

function _parse_primary!(p::_Parser)
    _deeper!(p)
    try
        tok = _peek(p)
        kind, value, where_ = tok.type, tok.text, tok.pos
        if kind === :number
            _advance!(p)
            if _peek(p).type === :lbracket
                _advance!(p)
                unit = _peek(p).type === :index ? String(strip(_advance!(p).text)) : ""
                _expect!(p, :rbracket, "']'")
                return ENum(_number_text(value), unit)
            end
            return ENum(_number_text(value))
        end
        if kind === :lparen
            _advance!(p)
            inner = _parse_ternary!(p)
            _expect!(p, :rparen, "')'")
            return inner
        end
        if kind === :op && (value == "-" || value == "+")
            _advance!(p)
            operand = _parse_binary!(p, POWER_PRECEDENCE - 1)
            return value == "-" ? EUnary("-", operand) : operand
        end
        if kind === :ident
            _advance!(p)
            name = value
            if _peek(p).type === :lparen
                fn = lookup_function(name)
                if fn === nothing
                    if !(p.calls !== nothing && p.calls(name))
                        throw(EquationParseError("Unknown function '$name'", where_, p.text))
                    end
                    _advance!(p)
                    return ECall(name, _args_until_rparen!(p))
                end
                _advance!(p)
                args = _args_until_rparen!(p)
                most = fn.max_arity === nothing ? typemax(Int) : fn.max_arity
                if length(args) < fn.arity || length(args) > most
                    wanted = most == typemax(Int) ? "at least $(fn.arity)" :
                             fn.arity == most ? "$(fn.arity)" : "$(fn.arity)-$(most)"
                    throw(EquationParseError("Function '$name' takes $wanted argument(s), got $(length(args))", where_, p.text))
                end
                return ECall(fn.key, args)
            end
            fn = lookup_function(name)
            if fn !== nothing && fn.arity == 0
                return ECall(fn.key, ENode[])
            end
            indices = Union{Nothing,String}[]
            while _peek(p).type === :lbracket
                _advance!(p)
                idx = _peek(p).type === :index ? String(strip(_advance!(p).text)) : ""
                _expect!(p, :rbracket, "']'")
                push!(indices, idx == "" ? nothing : idx)
            end
            return ERef(name, indices)
        end
        throw(EquationParseError("Unexpected '$(_shown(tok))'", where_, p.text))
    finally
        p.depth -= 1
    end
end

function _parse_exponent!(p::_Parser)
    tok = _peek(p)
    if tok.type === :op && (tok.text == "-" || tok.text == "+")
        _advance!(p)
        _deeper!(p)
        try
            operand = _parse_exponent!(p)
            return tok.text == "-" ? EUnary("-", operand) : operand
        finally
            p.depth -= 1
        end
    end
    return _parse_primary!(p)
end

function _parse_power!(p::_Parser)
    left = _parse_primary!(p)
    while _peek(p).type === :op && _peek(p).text == "^"
        _advance!(p)
        right = _parse_exponent!(p)
        left = EBinary("^", left, right)
    end
    return left
end

function _parse_binary!(p::_Parser, min_prec::Int)
    _deeper!(p)
    try
        left = _parse_power!(p)
        while true
            tok = _peek(p)
            tok.type === :op || break
            prec = get(BINARY_PRECEDENCE, tok.text, nothing)
            (prec === nothing || prec < min_prec) && break
            _advance!(p)
            right = _parse_binary!(p, prec + 1)
            left = EBinary(tok.text, left, right)
        end
        return left
    finally
        p.depth -= 1
    end
end

function _parse_ternary!(p::_Parser)
    _deeper!(p)
    try
        test = _parse_binary!(p, 1)
        if _peek(p).type === :op && _peek(p).text == "?"
            _advance!(p)
            then = _parse_ternary!(p)
            colon = _peek(p)
            (colon.type === :op && colon.text == ":") ||
                throw(EquationParseError("Expected ':' in conditional but found '$(_shown(colon))'", colon.pos, p.text))
            _advance!(p)
            otherwise = _parse_ternary!(p)
            return ECond(test, then, otherwise)
        end
        return test
    finally
        p.depth -= 1
    end
end

"""
    parse_equation(src; calls=nothing) -> ENode

Parses an equation into a tree; empty text is the number 0. `calls(name)`
says whether a name the function table does not know is a call the model
itself defines (a lookup table read at an argument, a user-defined
function); without it such a call is an error.
"""
function parse_equation(src; calls=nothing)
    (src === nothing || isempty(strip(js_str(src)))) && return ENum(0.0)
    text = js_str(src)
    raw = try
        tokenize(text)
    catch e
        e isa EquationSyntaxError || rethrow()
        throw(EquationParseError(e.message, e.position, text))
    end
    tokens = Token[t.type === :op ? Token(:op, get(OP_ALIAS, t.text, t.text), t.pos) : t for t in raw]
    p = _Parser(tokens, 1, text, calls, 0)
    ast = _parse_ternary!(p)
    trailing = _peek(p)
    trailing.type === :eof || throw(EquationParseError("Unexpected '$(_shown(trailing))'", trailing.pos, text))
    return ast
end

"""The names of every block a tree refers to."""
function collect_references!(out::Set{String}, ast::ENode)
    stack = ENode[ast]
    while !isempty(stack)
        node = pop!(stack)
        if node isa ERef
            push!(out, node.name)
        elseif node isa ECall
            append!(stack, node.args)
        elseif node isa EUnary
            push!(stack, node.operand)
        elseif node isa EBinary
            push!(stack, node.left)
            push!(stack, node.right)
        elseif node isa ECond
            push!(stack, node.test)
            push!(stack, node.then)
            push!(stack, node.otherwise)
        end
    end
    return out
end
collect_references(ast::ENode) = collect_references!(Set{String}(), ast)

"""The references of a tree in the order `collectReferences` meets them: depth first, left to right."""
function collect_in_order!(order::OrderedDict{String,Int}, ast::ENode)
    if ast isa ERef
        haskey(order, ast.name) || (order[ast.name] = length(order))
    elseif ast isa ECall
        for a in ast.args
            collect_in_order!(order, a)
        end
    elseif ast isa EUnary
        collect_in_order!(order, ast.operand)
    elseif ast isa EBinary
        collect_in_order!(order, ast.left)
        collect_in_order!(order, ast.right)
    elseif ast isa ECond
        collect_in_order!(order, ast.test)
        collect_in_order!(order, ast.then)
        collect_in_order!(order, ast.otherwise)
    end
    return order
end

"""Whether a tree calls `time`, anywhere."""
function reads_clock(ast::ENode)
    stack = ENode[ast]
    while !isempty(stack)
        node = pop!(stack)
        if node isa ECall
            node.name == "time" && return true
            append!(stack, node.args)
        elseif node isa EUnary
            push!(stack, node.operand)
        elseif node isa EBinary
            push!(stack, node.left)
            push!(stack, node.right)
        elseif node isa ECond
            push!(stack, node.test)
            push!(stack, node.then)
            push!(stack, node.otherwise)
        end
    end
    return false
end
