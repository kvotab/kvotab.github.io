# The model's own functions, written out where they are called
# (src/sim/functions.js). A function block is a name, a list of parameters
# and one equation; a call of it is replaced by its body with the arguments
# put in for the parameters, so nothing downstream has to know functions
# exist. A reference in the body that is not a parameter means what it means
# where the function is written, and carries that scope with it.

const MAX_FUNCTION_DEPTH = 32

struct FunctionError <: Exception
    message::String
    block_name::Union{Nothing,String}
end
Base.showerror(io::IO, e::FunctionError) = print(io, e.message)

function _scoped(ast::ENode, params::Set{String}, system::String)
    if ast isa ERef
        return ast.name in params ? ast : ERef(ast.name, ast.indices, system)
    elseif ast isa EUnary
        return EUnary(ast.op, _scoped(ast.operand, params, system))
    elseif ast isa EBinary
        return EBinary(ast.op, _scoped(ast.left, params, system), _scoped(ast.right, params, system))
    elseif ast isa ECond
        return ECond(_scoped(ast.test, params, system), _scoped(ast.then, params, system),
                     _scoped(ast.otherwise, params, system))
    elseif ast isa ECall
        return ECall(ast.name, ENode[_scoped(a, params, system) for a in ast.args], ast.scope)
    end
    return ast
end

function _substitute(ast::ENode, bound::Dict{String,ENode}, fn_name::String)
    if ast isa ERef
        arg = get(bound, ast.name, nothing)
        arg === nothing && return ast
        if !isempty(ast.indices)
            throw(FunctionError("'$(ast.name)[…]' asks for an index of a parameter of '$fn_name'. An argument is a " *
                                "single value, already worked out where the function is called: put the index there " *
                                "instead.", fn_name))
        end
        return arg
    elseif ast isa EUnary
        return EUnary(ast.op, _substitute(ast.operand, bound, fn_name))
    elseif ast isa EBinary
        return EBinary(ast.op, _substitute(ast.left, bound, fn_name), _substitute(ast.right, bound, fn_name))
    elseif ast isa ECond
        return ECond(_substitute(ast.test, bound, fn_name), _substitute(ast.then, bound, fn_name),
                     _substitute(ast.otherwise, bound, fn_name))
    elseif ast isa ECall
        return ECall(ast.name, ENode[_substitute(a, bound, fn_name) for a in ast.args], ast.scope)
    end
    return ast
end

struct FunctionDef
    name::String
    parameters::Vector{String}
    block::JDict
    ast::ENode
end

"""The functions of one model, parsed once, ready to be inlined."""
mutable struct UserFunctions
    defs::Dict{String,FunctionDef}
    declared::Set{String}
end

function UserFunctions(functions::Vector{JDict}, callable_=nothing)
    uf = UserFunctions(Dict{String,FunctionDef}(), Set{String}(qualified_name(f) for f in functions if js_truthy(get(f, "name", nothing))))
    for f in functions
        js_truthy(get(f, "name", nothing)) || continue
        name = qualified_name(f)
        parameters = String[string(p) for p in something(get(f, "parameters", nothing), Any[])]
        eq = get(f, "equation", nothing)
        text = strip(js_str(eq === nothing ? "" : eq))
        if isempty(text)
            what = isempty(parameters) ? "numbers and the built-in functions" : "its parameters ($(join(parameters, ", ")))"
            throw(FunctionError("'$name' has no body yet. Write what it works out to in terms of $what, or delete it " *
                                "and the equations that call it.", name))
        end
        system = js_truthy(get(f, "system", nothing)) ? string(f["system"]) : ""
        ast = try
            parse_equation(text; calls=n -> resolve_function(uf, n, system) !== nothing ||
                                            (callable_ !== nothing && callable_(n, system)))
        catch e
            e isa EquationParseError || rethrow()
            throw(FunctionError("$(e.message) in the body of '$name' (at character $(e.position + 1))", name))
        end
        uf.defs[name] = FunctionDef(name, parameters, f, _scoped(ast, Set(parameters), system))
    end
    return uf
end

Base.length(uf::UserFunctions) = length(uf.defs)

function resolve_function(uf::UserFunctions, written, system)
    q = resolve_reference(written, something(system, ""), n -> n in uf.declared)
    return (q !== nothing && q in uf.declared) ? q : nothing
end

inline_functions(uf::UserFunctions, ast::ENode, owner=nothing, system::AbstractString="") =
    _expand(uf, ast, owner, String(system), String[], 0)

function _expand(uf::UserFunctions, ast::ENode, owner, system::String, stack::Vector{String}, depth::Int)
    if depth > MAX_FUNCTION_DEPTH
        who = isempty(stack) ? owner : stack[end]
        throw(FunctionError("'$who' nests function calls more than $MAX_FUNCTION_DEPTH deep.", owner))
    end
    go(node) = _expand(uf, node, owner, system, stack, depth)
    (ast isa ERef || ast isa ENum) && return ast
    ast isa EUnary && return EUnary(ast.op, go(ast.operand))
    ast isa EBinary && return EBinary(ast.op, go(ast.left), go(ast.right))
    ast isa ECond && return ECond(go(ast.test), go(ast.then), go(ast.otherwise))
    if ast isa ECall
        args = ENode[go(a) for a in ast.args]
        scope = ast.scope !== nothing ? ast.scope : system
        q = resolve_function(uf, ast.name, scope)
        fn = q === nothing ? nothing : get(uf.defs, q, nothing)
        fn === nothing && return ECall(ast.name, args, ast.scope)
        if fn.name in stack
            chain = join([stack; fn.name], " → ")
            throw(FunctionError("'$(fn.name)' calls itself ($chain). A function is worked out where it is called, so " *
                                "there would be nothing to stop at.", isempty(stack) ? owner : stack[1]))
        end
        params = fn.parameters
        if length(args) != length(params)
            named = isempty(params) ? "" : " ($(join(params, ", ")))"
            throw(FunctionError("'$(fn.name)' takes $(length(params)) argument$(length(params) == 1 ? "" : "s")$named, " *
                                "but is called with $(length(args)).", owner))
        end
        body = _substitute(fn.ast, Dict{String,ENode}(zip(params, args)), fn.name)
        fsys = js_truthy(get(fn.block, "system", nothing)) ? string(fn.block["system"]) : ""
        return _expand(uf, body, owner, fsys, [stack; fn.name], depth + 1)
    end
    return ast
end
