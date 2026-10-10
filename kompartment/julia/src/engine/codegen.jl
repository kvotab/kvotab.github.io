# The model's passes as native code.
#
# Each pass -- the slots that never change, those that follow the clock alone,
# those that read the state, the initial state -- becomes one Julia function,
#
#     (t, y, X, P, D) -> nothing
#
# compiled by Julia's JIT. A statement over one element is written out with
# its indices as literals; a merged statement over many is a loop, its index
# vectors held in `D.I` (or written as `start + k` where they are a run). The
# arithmetic is the Python engine's, operation for operation: no fused
# multiply-adds, the C library's transcendental functions, numpy's min and
# max. A large pass is cut into functions of at most `CHUNK` statements, so
# that no one function grows past what the compiler handles quickly.

"""What a model's generated code reads besides the state, the algebraic slots and the parameters."""
mutable struct ModelData
    I::Vector{Vector{Int}}           # index vectors (1-based)
    F::Vector{Vector{Float64}}       # number vectors
    TAB::Vector{LookupTable}
    MEM::Vector{Recorder}
    DIS::Vector{Float64}
    T0::Float64
    T1::Float64
    FARF::Vector{Any}
end
ModelData() = ModelData(Vector{Int}[], Vector{Float64}[], LookupTable[], Recorder[], Float64[], 0.0, 0.0, Any[])

"""A compiled pass: `pass(t, y, X, P, D)`."""
const PassFunction = FunctionWrapper{Nothing,Tuple{Float64,Vector{Float64},Vector{Float64},Vector{Float64},ModelData}}

"""Statements per generated function; a longer pass calls several in turn."""
const CHUNK = Ref(400)

"""Whether the generated code checks its indices (slower; for finding a builder's mistake)."""
const CHECK_BOUNDS = Ref(false)

mutable struct CodeWriter
    data::ModelData
    int_cache::Dict{UInt,Int}
end
CodeWriter(data::ModelData) = CodeWriter(data, Dict{UInt,Int}())

const _G = @__MODULE__
_g(name::Symbol) = GlobalRef(_G, name)

"""The position of an index vector (1-based values) in `D.I`, shared by every statement that uses the same one."""
function _bind_ints!(w::CodeWriter, v::Vector{Int})
    h = hash(v)
    k = get(w.int_cache, h, 0)
    if k > 0 && w.data.I[k] == v
        return k
    end
    push!(w.data.I, v)
    w.int_cache[h] = length(w.data.I)
    return length(w.data.I)
end

function _bind_floats!(w::CodeWriter, v::Vector{Float64})
    push!(w.data.F, v)
    return length(w.data.F)
end

"""Whether a 0-based index vector is a run (start, start+1, ...)."""
function _is_run(v::Vector{Int})
    n = length(v)
    n == 0 && return false
    s = v[1]
    @inbounds for i in 2:n
        v[i] == s + i - 1 || return false
    end
    return true
end

"""How element `k` of an index (0-based in the builder) is read: a literal, `start + k`, or `Ij[k]`."""
function _index_expr!(w::CodeWriter, locals::Dict{Int,Symbol}, binds::Vector{Any}, l::TLeaf, k)
    if l.indices === nothing
        return l.index + 1
    end
    v = l.indices
    allsame = all(==(v[1]), v)
    allsame && return v[1] + 1
    _is_run(v) && return :($(v[1]) + $k)
    j = _bind_ints!(w, v .+ 1)
    sym = get!(locals, j) do
        s = Symbol("i_", j)
        push!(binds, :($s = I[$j]))
        s
    end
    return :($sym[$k])
end

function _value_expr!(w::CodeWriter, locals_f::Dict{Int,Symbol}, binds::Vector{Any}, l::TLeaf, k)
    l.values === nothing && return l.value
    v = l.values
    all(x -> x === v[1] || (isnan(x) && isnan(v[1])), v) && return v[1]
    j = _bind_floats!(w, v)
    sym = get!(locals_f, j) do
        s = Symbol("f_", j)
        push!(binds, :($s = F[$j]))
        s
    end
    return :($sym[$k])
end

const _INLINE = Dict(
    "abs" => :kf_abs, "sqrt" => :kf_sqrt, "exp" => :kf_exp, "log" => :kf_log, "log10" => :kf_log10,
    "log2" => :kf_log2, "sin" => :kf_sin, "cos" => :kf_cos, "tan" => :kf_tan, "sinh" => :kf_sinh, "cosh" => :kf_cosh,
    "tanh" => :kf_tanh, "asin" => :kf_asin, "acos" => :kf_acos, "atan" => :kf_atan, "ceil" => :kf_ceil,
    "floor" => :kf_floor, "sign" => :kf_sign, "atan2" => :kf_atan2, "hypot" => :kf_hypot,
    "fix" => :kf_fix, "ulp" => :kf_ulp, "mod" => :kf_mod, "rem" => :kf_rem, "factorial" => :kf_factorial,
    "binomial" => :kf_binomial, "erf" => :kf_erf, "erfc" => :kf_erfc, "asinh" => :kf_asinh, "acosh" => :kf_acosh,
    "atanh" => :kf_atanh, "bq2mole" => :kf_bq2mole, "mole2bq" => :kf_mole2bq, "rampDown" => :kf_ramp_down,
    "rampUp" => :kf_ramp_up,
)

_finite_constant(t::TNode) = t isa TLeaf && t.kind === :K &&
                             (t.values === nothing ? isfinite(t.value) : all(isfinite, t.values))

"""
A power as the Python engine's numpy works it out: `np.power` for a finite
constant exponent and `js_pow` otherwise, each with numpy's short cut for the
exponents 2, 0.5 and -1 where the exponent is one number for every element
of the statement (`np_pow`), and the C library's pow where it is one per
element.
"""
function _power_expr(exponent::TNode, a, b)
    one_value = scalar_subtree(exponent)
    if _finite_constant(exponent)
        if one_value && exponent isa TLeaf
            v = exponent.value
            v == 2.0 && return :(let v_ = $a; v_ * v_ end)
            v == 0.5 && return Expr(:call, _g(:kf_sqrt), a)
            v == -1.0 && return :(1.0 / $a)
            return Expr(:call, _g(:cpow), a, b)
        end
        return Expr(:call, _g(one_value ? :np_pow : :cpow), a, b)
    end
    return Expr(:call, _g(one_value ? :kf_jspow1 : :kf_jspow), a, b)
end

"""A tree as a Julia expression for element `k` (a symbol, or nothing for a one-element statement)."""
function tree_expr!(w::CodeWriter, li::Dict{Int,Symbol}, lf::Dict{Int,Symbol}, binds::Vector{Any}, t::TNode, k)
    go(x) = tree_expr!(w, li, lf, binds, x, k)
    if t isa TLeaf
        kind = t.kind
        kind === :K && return _value_expr!(w, lf, binds, t, k)
        kind === :T && return :t
        kind === :T0 && return :T0
        kind === :T1 && return :T1
        idx = _index_expr!(w, li, binds, t, k)
        kind === :y && return :(y[$idx])
        kind === :P && return :(P[$idx])
        kind === :X && return :(X[$idx])
        kind === :DIS && return :(DIS[$idx])
        error("A $kind leaf is not a value")
    elseif t isa TNeg
        return :(-($(go(t.a))))
    elseif t isa TBin
        a = go(t.a)
        b = go(t.b)
        op = t.op
        op === :+ && return :($a + $b)
        op === :- && return :($a - $b)
        op === :* && return :($a * $b)
        op === :/ && return :($a / $b)
        op === :^ && return _power_expr(t.b, a, b)
        op === :< && return :(ifelse($a < $b, 1.0, 0.0))
        op === :<= && return :(ifelse($a <= $b, 1.0, 0.0))
        op === :> && return :(ifelse($a > $b, 1.0, 0.0))
        op === :>= && return :(ifelse($a >= $b, 1.0, 0.0))
        op === :(==) && return :(ifelse($a == $b, 1.0, 0.0))
        op === OP_NE && return :(ifelse($a != $b, 1.0, 0.0))
        op === OP_AND && return :(ifelse(($a != 0.0) & ($b != 0.0), 1.0, 0.0))
        op === OP_OR && return :(ifelse(($a != 0.0) | ($b != 0.0), 1.0, 0.0))
        error("Cannot emit operator '$op'")
    elseif t isa TCond
        test = go(t.test)
        a = go(t.a)
        b = go(t.b)
        return :(($test != 0.0) ? $a : $b)
    elseif t isa TCall
        key = t.key
        args = Any[go(x) for x in t.args]
        f = get(_INLINE, key, nothing)
        f !== nothing && return Expr(:call, _g(f), args...)
        if key == "smoothDown" || key == "smoothUp"
            return Expr(:call, _g(key == "smoothDown" ? :kf_smooth_down : :kf_smooth_up), args...,
                        scalar_subtree(t.args[3]))
        end
        key == "power" && return _power_expr(t.args[2], args[1], args[2])
        key == "round" && return Expr(:call, _g(:kf_round), args[1])
        key == "not" && return Expr(:call, _g(:kf_not), args[1])
        if key == "min" || key == "max"
            fn = _g(key == "min" ? :kf_min : :kf_max)
            out = args[1]
            for a in args[2:end]
                out = Expr(:call, fn, out, a)
            end
            return out
        end
        if key == "sum" || key == "prod" || key == "mean"
            op = key == "prod" ? :* : :+
            out = args[1]
            for a in args[2:end]
                out = Expr(:call, op, out, a)
            end
            return key == "mean" ? :($out / $(Float64(length(args)))) : out
        end
        if key in ("and", "or", "nand", "nor", "xor")
            truth = Any[:($a != 0.0) for a in args]
            if key == "xor"
                cnt = Expr(:call, :+, (:(Int($x)) for x in truth)...)
                return :(ifelse(($cnt) % 2 == 1, 1.0, 0.0))
            end
            comb = truth[1]
            for x in truth[2:end]
                comb = key in ("and", "nand") ? :($comb & $x) : :($comb | $x)
            end
            key == "and" && return :(ifelse($comb, 1.0, 0.0))
            key == "or" && return :(ifelse($comb, 1.0, 0.0))
            return :(1.0 - ifelse($comb, 1.0, 0.0))
        end
        if key == "percentile"
            return Expr(:call, _g(:kf_percentile), args[1], Expr(:vect, args[2:end]...))
        end
        key == "interpolationUseEndValues" &&
            return Expr(:call, _g(:interpolate_args), Expr(:vect, args...), "linear")
        key == "interpolationExtrapolation" &&
            return Expr(:call, _g(:interpolate_args), Expr(:vect, args...), "extrapolate")
        key == "transport_point" && return Expr(:call, _g(:kf_transport_point), Expr(:vect, args...))
        key == "transport_sum" && return Expr(:call, _g(:kf_transport_range), Expr(:vect, args...), false)
        key == "transport_mean" && return Expr(:call, _g(:kf_transport_range), Expr(:vect, args...), true)
        error("Cannot emit a call of '$key'")
    elseif t isa TTab
        arg = go(t.arg)
        idx = _index_expr!(w, li, binds, t.leaf, k)
        return Expr(:call, _g(:table_at), :(TAB[$idx]), arg)
    end
    error("Cannot emit $(typeof(t))")
end

"""One statement as a block of code."""
function stmt_expr!(w::CodeWriter, s::Stmt)
    li = Dict{Int,Symbol}()
    lf = Dict{Int,Symbol}()
    binds = Any[]
    if s.special !== nothing
        return special_expr!(w, s.special)
    end
    array = s.array === :y0 ? :y : :X
    if s.width <= 1 && s.out isa Int
        rhs = tree_expr!(w, li, lf, binds, s.tree, nothing)
        o = s.out + 1
        body = s.multiply ? :($array[$o] = $array[$o] * $rhs) : :($array[$o] = $rhs)
        isempty(binds) && return body
        return Expr(:let, Expr(:block, binds...), body)
    end
    k = :k
    rhs = tree_expr!(w, li, lf, binds, s.tree, k)
    outs = s.out isa Int ? fill(s.out, s.width) : s.out
    if _is_run(outs)
        o = :($(outs[1]) + k)
    else
        j = _bind_ints!(w, outs .+ 1)
        push!(binds, :(o_ = I[$j]))
        o = :(o_[k])
    end
    body = s.multiply ? :($array[$o] = $array[$o] * $rhs) : :($array[$o] = $rhs)
    loop = :(for k in 1:$(s.width)
        $body
    end)
    return Expr(:let, Expr(:block, binds...), loop)
end

function special_expr!(w::CodeWriter, sp::RecorderRead)
    n = length(sp.out)
    jo = _bind_ints!(w, sp.out .+ 1)
    jm = _bind_ints!(w, sp.mem .+ 1)
    if sp.kind === :snapshot
        return :(let o_ = I[$jo], m_ = I[$jm]
            for k in 1:$n
                X[o_[k]] = $(_g(:held))(MEM[m_[k]], t)
            end
        end)
    end
    ja = _bind_ints!(w, sp.arg .+ 1)
    if sp.kind === :min_max
        return :(let o_ = I[$jo], m_ = I[$jm], a_ = I[$ja]
            for k in 1:$n
                X[o_[k]] = $(_g(:extreme))(MEM[m_[k]], t, X[a_[k]])
            end
        end)
    elseif sp.kind === :delay
        return :(let o_ = I[$jo], m_ = I[$jm], a_ = I[$ja]
            for k in 1:$n
                X[o_[k]] = $(_g(:delayed))(MEM[m_[k]], t, X[a_[k]])
            end
        end)
    end
    js = _bind_ints!(w, sp.state .+ 1)
    return :(let o_ = I[$jo], m_ = I[$jm], a_ = I[$ja], s_ = I[$js]
        for k in 1:$n
            X[o_[k]] = $(_g(:mean_of))(MEM[m_[k]], t, y[s_[k]], X[a_[k]])
        end
    end)
end

function special_expr!(w::CodeWriter, sp::FarfieldRelease)
    k = sp.index + 1
    return sp.laplace ? :($(_g(:farfield_release!))(FARF[$k], y, X, t)) : :($(_g(:farfield_release!))(FARF[$k], y, X))
end

const _PASS_PROLOGUE = quote
    I = D.I
    F = D.F
    TAB = D.TAB
    MEM = D.MEM
    DIS = D.DIS
    T0 = D.T0
    T1 = D.T1
    FARF = D.FARF
end

"""
    pass_function(w, name, stmts) -> Expr

The definition of one pass, `name(t, y, X, P, D)`, cut into chunks.
"""
function pass_definitions!(w::CodeWriter, name::Symbol, stmts::Vector{Stmt})
    defs = Any[]
    bodies = [stmt_expr!(w, s) for s in stmts]
    chunk = max(1, CHUNK[])
    wrap(body) = CHECK_BOUNDS[] ? body : :(@inbounds $body)
    if length(bodies) <= chunk
        push!(defs, :(function $name(t::Float64, y::Vector{Float64}, X::Vector{Float64}, P::Vector{Float64},
                                    D::$(_g(:ModelData)))
            $(_PASS_PROLOGUE)
            $(wrap(Expr(:block, bodies...)))
            return nothing
        end))
        return defs
    end
    calls = Any[]
    for (c, lo) in enumerate(1:chunk:length(bodies))
        part = Symbol(name, "_", c)
        hi = min(lo + chunk - 1, length(bodies))
        push!(defs, :(@noinline function $part(t::Float64, y::Vector{Float64}, X::Vector{Float64}, P::Vector{Float64},
                                               D::$(_g(:ModelData)))
            $(_PASS_PROLOGUE)
            $(wrap(Expr(:block, bodies[lo:hi]...)))
            return nothing
        end))
        push!(calls, :($part(t, y, X, P, D)))
    end
    push!(defs, :(function $name(t::Float64, y::Vector{Float64}, X::Vector{Float64}, P::Vector{Float64},
                                D::$(_g(:ModelData)))
        $(calls...)
        return nothing
    end))
    return defs
end

#: Numbers the models compiled in this process; builds on several threads at once (a split
#: run's parts) each take a number of their own.
const _MODEL_COUNTER = Threads.Atomic{Int}(0)

"""
    compile_passes(w, passes) -> Dict{Symbol,PassFunction}

Evaluates the passes' definitions in a module of their own and wraps each in
a `PassFunction`, which the solvers call without being compiled again for
every model.
"""
function compile_passes(w::CodeWriter, passes::Vector{Pair{Symbol,Vector{Stmt}}})
    number = Threads.atomic_add!(_MODEL_COUNTER, 1) + 1
    # While the package itself is being precompiled no new module may be made,
    # so the workload's model is defined in this one, under names of its own.
    precompiling = ccall(:jl_generating_output, Cint, ()) == 1
    mod = precompiling ? _G : Module(Symbol("KompartmentModel", number))
    prefix = precompiling ? "_precompiled_model$(number)_" : ""
    named(name) = Symbol(prefix, name)
    defs = Any[]
    for (name, stmts) in passes
        append!(defs, pass_definitions!(w, named(name), stmts))
    end
    for d in defs
        Core.eval(mod, d)
    end
    out = Dict{Symbol,PassFunction}()
    for (name, _) in passes
        f = Base.invokelatest(getfield, mod, named(name))
        out[name] = Base.invokelatest(PassFunction, f)
    end
    return out, defs
end
