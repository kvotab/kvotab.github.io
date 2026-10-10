# The equation language's tokenizer (`tokenize` in src/parser/parser.js).
#
# It splits text the same way, character for character: a number (`1e-5`,
# `1.0E10`); a name, where a dotted path such as `NearField.Water` is one
# name (the dot is taken only when a letter follows it); the text inside
# `[...]`, raw, as one index token; brackets, parentheses, commas and the
# operators, the multi-character ones tried first.

struct EquationSyntaxError <: Exception
    message::String
    position::Int          # 0-based, as the application counts
    source::String
end
Base.showerror(io::IO, e::EquationSyntaxError) = print(io, e.message)

"""One token: its kind, its text and where it starts (0-based)."""
struct Token
    type::Symbol      # :number, :ident, :op, :lparen, :rparen, :comma, :lbracket, :rbracket, :index, :eof
    text::String
    pos::Int
end

const EQ_OPERATORS = ("<=", ">=", "==", "~=", "!=", "&&", "||", ".*", "./", ".^",
                      "+", "-", "*", "/", "^", "<", ">", "?", ":")

@inline _is_digit(c::Char) = '0' <= c <= '9'
@inline _is_ident_start(c::Char) = ('a' <= c <= 'z') || ('A' <= c <= 'Z') || c == '_'
@inline _is_ident_part(c::Char) = _is_ident_start(c) || _is_digit(c)

"""
    tokenize(src) -> Vector{Token}

Splits an equation into tokens, as the application does; raises
`EquationSyntaxError` on a character the language does not use.
"""
function tokenize(src::AbstractString)
    chars = collect(String(src))    # positions count characters, as JavaScript's code units do for these texts
    n = length(chars)
    at(k) = k <= n ? chars[k] : '\0'
    tokens = Token[]
    i = 1
    sub(a, b) = String(chars[a:b])
    while i <= n
        c = chars[i]
        if c == ' ' || c == '\t' || c == '\n' || c == '\r'
            i += 1
            continue
        end
        if _is_digit(c) || (c == '.' && _is_digit(at(i + 1)))
            start = i
            while i <= n && _is_digit(chars[i])
                i += 1
            end
            if at(i) == '.'
                i += 1
                while i <= n && _is_digit(chars[i])
                    i += 1
                end
            end
            if at(i) == 'e' || at(i) == 'E'
                save = i
                i += 1
                (at(i) == '+' || at(i) == '-') && (i += 1)
                if _is_digit(at(i))
                    while i <= n && _is_digit(chars[i])
                        i += 1
                    end
                else
                    i = save   # "2e" in "2*ex" is not an exponent
                end
            end
            push!(tokens, Token(:number, sub(start, i - 1), start - 1))
            continue
        end
        if _is_ident_start(c)
            start = i
            while i <= n && _is_ident_part(chars[i])
                i += 1
            end
            while at(i) == '.' && _is_ident_start(at(i + 1))
                i += 1
                while i <= n && _is_ident_part(chars[i])
                    i += 1
                end
            end
            push!(tokens, Token(:ident, sub(start, i - 1), start - 1))
            continue
        end
        if c == '('
            push!(tokens, Token(:lparen, "(", i - 1)); i += 1; continue
        elseif c == ')'
            push!(tokens, Token(:rparen, ")", i - 1)); i += 1; continue
        elseif c == ','
            push!(tokens, Token(:comma, ",", i - 1)); i += 1; continue
        elseif c == '['
            push!(tokens, Token(:lbracket, "[", i - 1))
            i += 1
            start = i
            while i <= n && chars[i] != ']'
                i += 1
            end
            i > start && push!(tokens, Token(:index, sub(start, i - 1), start - 1))
            continue
        elseif c == ']'
            push!(tokens, Token(:rbracket, "]", i - 1)); i += 1; continue
        end
        op = nothing
        for o in EQ_OPERATORS
            m = length(o)
            if i + m - 1 <= n && all(chars[i+k-1] == o[k] for k in 1:m)
                op = o
                break
            end
        end
        if op !== nothing
            push!(tokens, Token(:op, op, i - 1))
            i += length(op)
            continue
        end
        throw(EquationSyntaxError("Unexpected character '$c'", i - 1, String(src)))
    end
    push!(tokens, Token(:eof, "<end>", n))
    return tokens
end

"""The name tokens that may be references to blocks: a reserved name called as
a function is not, nor a name in `skip`."""
function reference_tokens(tokens::Vector{Token}, skip=nothing)
    out = Token[]
    for (k, tok) in enumerate(tokens)
        tok.type === :ident || continue
        (tokens[k+1].type === :lparen && tok.text in RESERVED) && continue
        (skip !== nothing && tok.text in skip) && continue
        push!(out, tok)
    end
    return out
end

"""Every name written in an equation, as written, in order (`time` left out)."""
function names_in(equation)
    text = equation === nothing ? "" : js_str(equation)
    isempty(text) && return String[]
    tokens = try
        tokenize(text)
    catch e
        e isa EquationSyntaxError || rethrow()
        return String[]
    end
    return [t.text for t in reference_tokens(tokens) if t.text != "time"]
end

"""The blocks an equation refers to, as qualified names, resolved from `system`."""
function references_in(equation, system, known; skip=nothing)
    text = equation === nothing ? "" : js_str(equation)
    isempty(text) && return String[]
    tokens = try
        tokenize(text)
    catch e
        e isa EquationSyntaxError || rethrow()
        return String[]
    end
    out = String[]
    for tok in reference_tokens(tokens, skip)
        q = resolve_reference(tok.text, system, known)
        q !== nothing && push!(out, q)
    end
    return out
end
