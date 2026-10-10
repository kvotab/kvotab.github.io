# Builds a runnable system from a Project (`buildSystem` in src/sim/builder.js,
# as the Python engine's builder.py ports it).
#
# The state vector, the parameter vector and the algebraic slots are laid out
# exactly as the application lays them out -- same order, same offsets -- so
# a state or a slot can be compared with the application's one for one. Every
# equation becomes a statement over all the indices it is written at;
# statements of the same shape that do not read one another are merged; and
# the derivative is a list of phases of (target, value) contributions in the
# order the application adds them:
#
#     dC[i]/dt = sum(inflows) - sum(outflows) + sources
#                - lambda[m] * C[i] + sum over parents p (lambda * ratio * C[i, m := p])

const BUDGET_TERMS = ("in", "out", "decay", "ingrowth", "explicit", "between")
const UNINDEXED = "not by nuclide"
const WINDOW_TAIL = 1e-3
const AVAILABILITY_SCHEMES = ("limit", "shared_limit", "langmuir", "shared_langmuir")
const AVOGADRO_AVAILABILITY = 6.02214076e23
const OPERATION_FUNCTION = Dict("sum" => "sum", "product" => "prod", "min" => "min", "max" => "max",
                                "mean" => "mean", "percentile" => "percentile")

const Tup = OrderedDict{String,String}

# --- helpers over the index space ---------------------------------------------------------

function tuple_by_list(space::IndexSpace, dims, offset::Integer)
    names = tuple_at(space, dims, offset)
    out = Tup()
    for (i, d) in enumerate(dims)
        out[d] = names[i]
    end
    return out
end

"""The enabled position of `dim` for a tuple, through related lists (0-based), or `nothing`."""
function position_in(space::IndexSpace, dim, tup)
    name = get(tup, dim, nothing)
    if name !== nothing
        pos = get(get_list(space, dim).position_of, name, nothing)
        pos !== nothing && return pos
    end
    for (list_name, index_name) in tup
        list_name == dim && continue
        rel = has_list(space, list_name) ? relate(space, dim, list_name) : nothing
        rel === nothing && continue
        if rel.kind === :same
            pos = get(get_list(space, dim).position_of, index_name, nothing)
            pos !== nothing && return pos
        else
            k = get(get_list(space, list_name).position_of, index_name, nothing)
            k === nothing && continue
            pos = rel.table[k+1]
            pos >= 0 && return pos
        end
    end
    return nothing
end

"""The index of `dim` standing for `index_name` of its root list: `nothing` when
`dim` is a root or the name is not its root's, `false` when the root index has
no counterpart in `dim`."""
function derived_index(space::IndexSpace, dim, index_name)
    lst = get_list(space, dim)
    lst.root_name == dim && return nothing
    root = get_list(space, lst.root_name)
    k = get(root.position_of, index_name, nothing)
    k === nothing && return nothing
    rel = relate(space, dim, lst.root_name)
    pos = (rel !== nothing && rel.kind === :map) ? rel.table[k+1] : k
    pos < 0 && return false
    return pos < length(lst.enabled) ? lst.enabled[pos+1].name : false
end

"""Which dimension of `target` each written index pins -- by name, not by position."""
function pin_indices(space::IndexSpace, target::Entry, indices, name, owner_name, context=nothing)
    fixed = Tup()
    written = String[i for i in something(indices, Any[]) if i !== nothing && i != ""]
    given = String[]
    for i in written
        if i != SOURCE_INDEX && i != TARGET_INDEX
            push!(given, i)
            continue
        end
        end_ = context === nothing ? nothing : get(context, i, nothing)
        if end_ !== nothing && end_ != ""
            push!(given, end_)
            continue
        end
        which = i == SOURCE_INDEX ? "flows out of" : "flows into"
        if context !== nothing && get(context, TRANSFER_LIST, nothing) !== nothing
            goes = i == SOURCE_INDEX ? "comes from" : "goes"
            throw(BuildError("'$name[$i]' asks for the compartment this transfer $which, and it has none: it $goes " *
                             "outside the model.", owner_name))
        end
        throw(BuildError("'$i' means the compartment a transfer $which, so it can only be written in a transfer's own " *
                         "equation.", owner_name))
    end
    isempty(given) && return fixed
    as_written() = name * join(("[" * (i === nothing ? "" : i) * "]" for i in something(indices, Any[])))
    dims = target.dims
    if length(given) > length(dims)
        noun = length(given) == 1 ? "index" : "indices"
        what = isempty(dims) ? "nothing, so it holds a single value" :
               "only $(length(dims)) list$(length(dims) == 1 ? "" : "s") ($(join(dims, ", ")))"
        throw(BuildError("'$(as_written())' pins $(length(given)) $noun, but '$name' is indexed by $what.", owner_name))
    end
    function accepted(dim, index_name)
        haskey(get_list(space, dim).position_of, index_name) && return index_name
        d = derived_index(space, dim, index_name)
        return (d === nothing || d === false) ? nothing : d
    end
    claimed = Set{Int}()
    for dim in dims
        pick = findfirst(k -> !(k in claimed) && accepted(dim, given[k]) !== nothing, 1:length(given))
        pick === nothing && (pick = findfirst(k -> accepted(dim, given[k]) !== nothing, 1:length(given)))
        pick === nothing && continue
        fixed[dim] = accepted(dim, given[pick])
        push!(claimed, pick)
    end
    for (k, g) in enumerate(given)
        k in claimed && continue
        disabled_in = [d for d in dims if any(i -> i.name == g && !i.enabled, get_list(space, d).indices)]
        if !isempty(disabled_in)
            throw(BuildError("'$g' is disabled in '$(disabled_in[1])', so '$(as_written())' has no value. Re-enable it, " *
                             "or change this equation.", owner_name))
        end
        owns = [d for d in dims if accepted(d, g) !== nothing]
        if !isempty(owns)
            names = join(owns, "' and '")
            throw(BuildError("'$(as_written())' pins '$names' twice: '$g' belongs to $(length(owns) == 1 ? "it" : "them"), " *
                             "and so does another index in the same reference.", owner_name))
        end
        throw(BuildError("'$g' is not an index of any list that '$name' is indexed by ($(isempty(dims) ? "none" : join(dims, ", ")))",
                         owner_name))
    end
    return fixed
end

"""The index positions a block occupies by being what it is: a transfer is one of
the transfers and knows its two ends; a compartment is one of the compartments."""
function implicit_indices(owner)
    (owner === nothing || owner isa AbstractString) && return nothing
    block = owner.block === nothing ? JDict() : owner.block
    alias = something(jget(block, "alias"), JDict())
    kind = owner.kind
    if kind == "transfer" || startswith(kind, "availability:")
        tname = something(jget(alias, "transfer"), get(owner, :transfer, nothing), Some(owner.name))
        return Dict{String,Any}(TRANSFER_LIST => tname,
                                SOURCE_INDEX => something(jget(alias, "from"), Some(jget(block, "from"))),
                                TARGET_INDEX => something(jget(alias, "to"), Some(jget(block, "to"))))
    end
    if kind == "compartment" || kind == "compartment:dydt"
        return Dict{String,Any}(COMPARTMENT_LIST => something(jget(alias, "compartment"), get(owner, :state_name, nothing),
                                                              Some(owner.name)))
    end
    return nothing
end

describe_tuple(tup) = (s = join(("$k=$v" for (k, v) in tup), ", "); isempty(s) ? "scalar" : s)

"""The decay model flattened: per index its constant, and its (parent, coefficient) pairs."""
struct DecayTables
    lam::Vector{Float64}
    ioff::Vector{Int}
    icnt::Vector{Int}
    ipar::Vector{Int}
    icoef::Vector{Float64}
end

function decay_tables(model::DecayModel, size::Int)
    n = max(1, size)
    ioff = zeros(Int, n)
    icnt = zeros(Int, n)
    ipar = Int[]
    icoef = Float64[]
    for k in 1:n
        ioff[k] = length(ipar)
        parents = k <= length(model.parents) ? model.parents[k] : NamedTuple{(:index, :lambda, :ratio),Tuple{Int,Float64,Float64}}[]
        for p in parents
            push!(ipar, p.index)
            push!(icoef, p.lambda * p.ratio)
        end
        icnt[k] = length(parents)
    end
    lambdas = isempty(model.lambdas) ? zeros(n) : copy(model.lambdas)
    return DecayTables(lambdas, ioff, icnt, ipar, icoef)
end

"""The dimensions along which an entry's equation never changes."""
function flat_dimensions(space::IndexSpace, entry::Entry)
    dims = entry.dims
    length(dims) < 2 && return String[]
    equations = entry.equations
    length(equations) != entry.width && return String[]
    st = strides(space, dims)
    sizes = [list_size(space, d) for d in dims]
    out = String[]
    for (i, d) in enumerate(dims)
        flat = true
        for off in 0:entry.width-1
            pos = (div(off, st[i])) % sizes[i]
            if pos != 0 && equations[off+1] != equations[off-pos*st[i]+1]
                flat = false
                break
            end
        end
        flat && push!(out, d)
    end
    return out
end

"""An entry's trees, each distinct equation's once and in the order they
first appear: the elements that share an equation share its tree, and what
is read from one is read from all of them."""
function _distinct_asts(a::Entry)
    asts = a.asts
    length(asts) <= 1 && return asts
    a.uniform && return asts[1:1]
    seen = Set{String}()
    out = ENode[]
    for (k, ast) in enumerate(asts)
        eq = a.equations[k]
        eq in seen && continue
        push!(seen, eq)
        push!(out, ast)
    end
    return out
end

function _self_refs(ast::ENode, a::Entry, alg_by_name::Dict{String,Entry})
    stack = ENode[ast]
    while !isempty(stack)
        node = pop!(stack)
        if node isa ERef
            if isempty(node.indices)
                q = resolve_reference(node.name, a.system, n -> haskey(alg_by_name, n))
                q == a.name && return true
            end
        elseif node isa EUnary
            push!(stack, node.operand)
        elseif node isa EBinary
            push!(stack, node.left, node.right)
        elseif node isa ECond
            push!(stack, node.test, node.then, node.otherwise)
        elseif node isa ECall
            append!(stack, node.args)
        end
    end
    return false
end

"""Sorts the algebraic blocks into dependency order, in place; a cycle is an error."""
function order_algebraic!(algebraic::Vector{Entry}, alg_by_name::Dict{String,Entry})
    deps = Dict{String,Vector{String}}()
    for a in algebraic
        # The references in the order a JavaScript Set of them iterates: first seen first.
        order = OrderedDict{String,Int}()
        distinct = _distinct_asts(a)
        for ast in distinct
            collect_in_order!(order, ast)
        end
        refs = Set{String}()
        for ast in distinct
            collect_references!(refs, ast)
        end
        rank(name) = get(order, name, length(order))
        resolved = String[]
        have = Set{String}()
        for r in sort!(collect(refs); by=rank)
            q = resolve_reference(r, a.system, n -> haskey(alg_by_name, n))
            if q !== nothing && q != a.name && !(q in have)
                push!(have, q)
                push!(resolved, q)
            end
        end
        for ast in distinct
            if _self_refs(ast, a, alg_by_name)
                local_ = something(a.local_name, a.name)
                hint = isempty(a.dims) ? "" : " To read this block at another index, name that index -- '$local_[<index>]'."
                throw(BuildError("'$local_' refers to itself. An equation cannot read its own value: there is nothing to " *
                                 "read until it has been worked out.$hint", a.name))
            end
        end
        for n in a.needs
            if !(n in have)
                push!(have, n)
                push!(resolved, n)
            end
        end
        deps[a.name] = resolved
        a.reads_alg = resolved
    end
    state = Dict{String,Int}()
    ordered = Entry[]
    stack = String[]
    # Depth first, iteratively: a model can chain tens of thousands of expressions.
    for a0 in algebraic
        get(state, a0.name, 0) == 2 && continue
        work = Tuple{String,Int}[(a0.name, 0)]
        while !isempty(work)
            name, i = work[end]
            if i == 0
                s = get(state, name, 0)
                if s == 2
                    pop!(work)
                    continue
                end
                if s == 1
                    k = findfirst(==(name), stack)
                    cycle = join([stack[k:end]; name], " -> ")
                    throw(BuildError("Circular reference: $cycle. Expressions and transfer rates may not depend on " *
                                     "themselves, directly or indirectly."))
                end
                state[name] = 1
                push!(stack, name)
            end
            ds = get(deps, name, String[])
            if i < length(ds)
                work[end] = (name, i + 1)
                d = ds[i+1]
                sd = get(state, d, 0)
                if sd == 1
                    k = findfirst(==(d), stack)
                    cycle = join([stack[k:end]; d], " -> ")
                    throw(BuildError("Circular reference: $cycle. Expressions and transfer rates may not depend on " *
                                     "themselves, directly or indirectly."))
                end
                sd == 0 && push!(work, (d, 0))
                continue
            end
            pop!(work)
            pop!(stack)
            state[name] = 2
            push!(ordered, alg_by_name[name])
        end
    end
    copyto!(algebraic, ordered)
    return algebraic
end

function _reads_time(node::ENode)
    stack = ENode[node]
    while !isempty(stack)
        n = pop!(stack)
        if n isa ECall
            n.name == "time" && return true
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

"""The algebraic blocks that hold the same value for the whole run, which an initial condition may read."""
function time_invariant_algebraic(algebraic::Vector{Entry}, alg_by_name::Dict{String,Entry}, state_by_name::Dict{String,Entry})
    can = ("expression", "index_reduction", "block_reduction")
    invariant = Set{String}()
    known(n) = haskey(alg_by_name, n) || haskey(state_by_name, n)
    for a in algebraic
        a.kind in can || continue
        distinct = _distinct_asts(a)
        any(_reads_time, distinct) && continue
        refs = Set{String}()
        for ast in distinct
            collect_references!(refs, ast)
        end
        for n in a.needs
            push!(refs, n)
        end
        ok = true
        for r in refs
            q = resolve_reference(r, a.system, known)
            q === nothing && continue
            if q != a.name && !(q in invariant)
                ok = false
                break
            end
        end
        ok && push!(invariant, a.name)
    end
    return invariant
end

function why_not_initial(name, s::Entry, alg_by_name, state_by_name)
    where_ = s.system != "" ? " in '$(s.system)' or at the top level" : ""
    q = resolve_reference(name, s.system, n -> haskey(alg_by_name, n) || haskey(state_by_name, n))
    if q !== nothing && haskey(state_by_name, q)
        return "Initial condition cannot read '$name': it is a compartment, and no compartment has a value until every " *
               "initial condition has been worked out. Use a parameter or an expression that does not read the state."
    end
    a = q === nothing ? nothing : get(alg_by_name, q, nothing)
    if a !== nothing
        why = a.kind == "lookup" ? ", being read from a table at the clock" :
              a.kind == "farfield" ? ", being the release out of a far-field path" : ""
        return "Initial condition cannot read '$name': its value changes over the run$why. Only a parameter, or an " *
               "expression made of parameters and numbers, holds the same value at every moment."
    end
    return "Initial condition may only use parameters, numbers and expressions that do not change over the run; " *
           "'$name' is not one of those$where_."
end

# --- statements -------------------------------------------------------------------------------

"""A statement over several elements as one statement per element, in order."""
function _split_stmt(s::Stmt)
    (s.width <= 1 || s.tree === nothing) && return Stmt[s]
    ls = tree_leaves(s.tree)
    outs = out_indices(s)
    out = Stmt[]
    for i in 1:s.width
        new = TLeaf[l.kind === :K ? KLeaf(leaf_value_at(l, i)) :
                    (l.kind in (:T, :T0, :T1) ? l : TLeaf(l.kind, leaf_index_at(l, i))) for l in ls]
        push!(out, Stmt(outs[i], rebuild(s.tree, new), 1, s.block, s.level; mergeable=false, array=s.array,
                        multiply=s.multiply))
    end
    return out
end

"""
    merge_statements(stmts) -> Vector{Stmt}

Statements at the same level with the same shape, merged into one each: the
order of the result is by level; within a level, merged groups keep the
position of their first statement. Statements that may not be merged stay
where they are.
"""
function merge_statements(stmts::Vector{Stmt})
    by_level = Dict{Tuple{Int,Int},Vector{Stmt}}()
    for s in stmts
        push!(get!(by_level, s.level, Stmt[]), s)
    end
    out = Stmt[]
    for level in sort!(collect(keys(by_level)))
        group_of = Dict{Tuple{Symbol,String,Bool},Vector{Stmt}}()
        order = Any[]
        for s in by_level[level]
            if !s.mergeable || s.tree === nothing
                push!(order, s)
                continue
            end
            key = (s.array, signature(s.tree), s.multiply)
            g = get(group_of, key, nothing)
            if g === nothing
                g = Stmt[]
                group_of[key] = g
                push!(order, g)
            end
            push!(g, s)
        end
        for item in order
            if item isa Stmt
                push!(out, item)
                continue
            end
            if length(item) == 1
                push!(out, item[1])
                continue
            end
            leaves = merge_leaves(Tuple{Vector{TLeaf},Int}[(tree_leaves(s.tree), s.width) for s in item])
            outs = Int[]
            for s in item
                s.out isa Int ? append!(outs, fill(s.out, s.width)) : append!(outs, s.out)
            end
            first_ = item[1]
            push!(out, Stmt(outs, rebuild(first_.tree, leaves), length(outs), first_.block, level;
                            array=first_.array, multiply=first_.multiply))
        end
    end
    return out
end

# --- the builder ----------------------------------------------------------------------------

mutable struct Builder
    project::Project
    space::IndexSpace
    material_list::Union{Nothing,String}
    decay::DecayModel
    material_root::Union{Nothing,String}
    # states
    states::Vector{Entry}
    nstate::Int
    mean_states::Vector{Entry}
    farf_layout::Vector{Entry}
    waste_layout::Vector{Entry}
    waste_by_name::Dict{String,Entry}
    disruption_layout::Vector{Entry}
    budget::Any
    state_by_name::Dict{String,Entry}
    path_by_name::Dict{String,Entry}
    # parameters and tables
    param_layout::Vector{Entry}
    param_by_name::Dict{String,Entry}
    point_layout::Vector{Entry}
    points_by_entry::Dict{Tuple{String,Int},Vector{Entry}}
    nparam::Int
    P::Vector{Float64}
    TAB::Vector{LookupTable}
    lookup_layout::Vector{Entry}
    table_by_name::Dict{String,Entry}
    # algebraic slots
    algebraic::Vector{Entry}
    nalg::Int
    alg_by_name::Dict{String,Entry}
    dydt_slots::Vector{Entry}
    FARF::Vector{Any}
    MEM::Vector{Recorder}
    recorders::Vector{Entry}
    functions::Any
    unit_blocks::Dict{String,JDict}
    # events
    event_slots::Vector{NamedTuple{(:slot, :direction, :name, :index),Tuple{Int,Int,String,Union{Nothing,Tup}}}}
    event_direction::Vector{Int8}
    event_handlers::Dict{Int,Vector{NamedTuple{(:rec, :off, :action),Tuple{Entry,Int,Symbol}}}}
    # statements
    self_reading::Set{String}
    alg_stmts::Dict{String,Vector{Stmt}}
    pass_stmts::Dict{Int,Vector{Stmt}}
    slot_class::Vector{UInt8}
    on_state::Set{String}
    on_clock::Set{String}
    # the derivative
    phases::Vector{Phase}
    nflux::Int
    flux_rate::Vector{Int}
    flux_mbd::Vector{Int}
    flux_mbd_src::Vector{Int}
    decay_lists::Vector{String}
    decaying::Vector{Any}
    DEC_tables::Dict{String,DecayTables}
    DEC::Vector{DecayTables}
    jump_specs::Vector{JumpSpec}
    derivative_blocks::Union{Nothing,Set{String}}
    derivative_stmts::Union{Nothing,Vector{Stmt}}
    initial_before::Vector{Stmt}
    initial_stmts::Vector{Stmt}
    Builder() = new()
end

dims_of(b::Builder, block) = without_scenarios(b.space, something(jget(block, "index_lists"), String[]))

function is_nuclide_dim(b::Builder, d)
    b.material_list === nothing && return false
    l = get_list(b.space, d)
    return l.mapping === nothing && l.root_name == b.material_root
end

entry_tuple(b::Builder, block, dims, off::Integer) =
    pin_scenario(b.space, something(jget(block, "index_lists"), String[]), tuple_by_list(b.space, dims, off))

"""
    build(project) -> Builder

Everything `buildSystem` works out for a project.
"""
function build(project::Project)
    b = Builder()
    if !isempty(project.transports)
        project = expand_transports(project)
    end
    b.project = project
    b.space = project.index_space
    b.material_list = project.material_list_name
    b.decay = decay_model(project)
    b.material_root = b.material_list === nothing ? nothing : get_list(b.space, b.material_list).root_name
    _layout_states!(b)
    _layout_parameters!(b)
    _layout_tables!(b)
    _layout_algebraic!(b)
    _prepare_parsing!(b)
    _parse_all!(b)
    try
        order_algebraic!(b.algebraic, b.alg_by_name)
    catch e
        e isa BuildError || rethrow()
        throw(_semi_loop(b, e))
    end
    _levels!(b)
    _events!(b)
    _generate_algebraic!(b)
    _classes!(b)
    _assembly!(b)
    _jumps!(b)
    b.DEC = [b.DEC_tables[l] for l in b.decay_lists]
    _derivative_reads!(b)
    _initial_state!(b)
    return b
end

function _semi_loop(b::Builder, e::BuildError)
    m = match(r"Circular reference: (.*)\. ", e.message)
    m === nothing && return e
    names = split(m.captures[1], " -> ")
    path = findfirst_value(p -> p[:farf].laplace && p.name in names, b.farf_layout)
    path === nothing && return e
    return BuildError("'$(path.local_name)' is worked out semi-analytically, and what flows into it reads its own " *
                      "release at the same instant ($(m.captures[1])). Its release depends on what flows in, so the two " *
                      "cannot be worked out one after the other: put a compartment between them, or work the path out " *
                      "on cells.", path.name)
end

# --- layout -----------------------------------------------------------------------------------

function _layout_states!(b::Builder)
    project, space = b.project, b.space
    states = Entry[]
    n = 0
    for c in project.blocks["compartments"]
        dims = dims_of(b, c)
        w = width(space, dims)
        push!(states, Entry(name=c["qname"], local_name=c["name"], system=c["system"], base=n, width=w, dims=dims,
                            block=c, kind="compartment", hidden=js_truthy(get(c, "hidden", nothing))))
        n += w
    end
    b.mean_states = Entry[]
    for m in project.blocks["running_means"]
        dims = dims_of(b, m)
        w = width(space, dims)
        e = Entry(name=m["qname"], local_name=m["name"], system=m["system"], base=n, width=w, dims=dims, block=m,
                  kind="running_mean", hidden=true)
        push!(states, e)
        push!(b.mean_states, e)
        n += w
    end
    b.farf_layout = Entry[]
    for f in project.blocks["farfields"]
        problem = something(structure_problem(f), geometry_problem(f), rock_problem(f), Some(nothing))
        problem !== nothing && throw(BuildError(problem, f["qname"]))
        laplace = is_semi_analytic(f)
        if !uses_cells(f) && !laplace
            throw(BuildError("'$(js_text(get(f, "method", nothing)))' is not a way this tool can work a path out " *
                             "($(join(FARF_METHODS, ", ")))", f["qname"]))
        end
        dims = dims_of(b, f)
        nuc_dims = [d for d in dims if is_nuclide_dim(b, d)]
        if length(nuc_dims) > 1
            throw(BuildError("A far-field path runs one decay chain, and it is indexed by two radionuclide dimensions " *
                             "($(join(nuc_dims, " and "))).", f["qname"]))
        end
        m_idx = something(findfirst(d -> is_nuclide_dim(b, d), dims), 0) - 1     # 0-based, -1 for none
        list_name = m_idx >= 0 ? dims[m_idx+1] : nothing
        nnuc = list_name === nothing ? 1 : list_size(space, list_name)
        other_idx = [i for i in 0:length(dims)-1 if i != m_idx]
        other_dims = [dims[i+1] for i in other_idx]
        other_width = width(space, other_dims)
        ncells = cell_count(f)
        st = strides(space, dims)
        other_st = strides(space, other_dims)
        dim_off = zeros(Int, other_width * nnuc)
        for o in 0:other_width-1
            at = 0
            for (k, od) in enumerate(other_dims)
                pos = (div(o, other_st[k])) % list_size(space, od)
                at += pos * st[other_idx[k]+1]
            end
            for m in 0:nnuc-1
                dim_off[o*nnuc+m+1] = at + (m_idx >= 0 ? m * st[m_idx+1] : 0)
            end
        end
        farf = (structure=laplace ? nothing : effective_structure(f), laplace=laplace, nnuc=nnuc,
                other_dims=other_dims, other_width=other_width, ncells=ncells, m_idx=m_idx, list_name=list_name,
                dim_off=dim_off, single_off=collect(0:other_width-1))
        e = Entry(name=f["qname"], local_name=f["name"], system=f["system"], base=n, width=other_width * ncells * nnuc,
                  dims=dims, block=f, kind="farfield", hidden=true, farf=farf)
        push!(states, e)
        push!(b.farf_layout, e)
        n += e.width
    end
    b.waste_layout = Entry[]
    for w in project.blocks["waste_packages"]
        q = w["qname"]
        dims = dims_of(b, w)
        wd = width(space, dims)
        intact = Entry(name="$q intact", local_name=w["name"], system=w["system"], width=wd, dims=dims, block=w,
                       kind="waste_package", hidden=true, base=n, qname=q, unit=project.decay_unit, role="intact")
        exposed = Entry(name="$q exposed", local_name=w["name"], system=w["system"], width=wd, dims=dims, block=w,
                        kind="waste_package", hidden=true, base=n + wd, qname=q, unit=project.decay_unit, role="exposed")
        push!(states, intact, exposed)
        failure = haskey(FAILURE_KEYS, get(w, "failure", nothing)) ? w["failure"] : "never"
        push!(b.waste_layout, Entry(name=q, kind="waste_layout", block=w, dims=dims, width=wd, q=q, intact=intact,
                                    exposed=exposed, failure=failure, disrupted=Any[]))
        n += 2 * wd
    end
    b.waste_by_name = Dict(W[:q] => W for W in b.waste_layout)
    b.disruption_layout = Entry[]
    for d in project.blocks["events"]
        q = d["qname"]
        e = Entry(name=q, local_name=d["name"], system=d["system"], base=n, width=1, dims=String[], block=d,
                  kind="event", hidden=false, qname=q, unit="")
        push!(states, e)
        timing = haskey(TIMING_KEYS, get(d, "timing", nothing)) ? d["timing"] : "at"
        push!(b.disruption_layout, Entry(name=q, kind="disruption", block=d, q=q, entry=e, timing=timing,
                                         actions=normalise_actions(get(d, "actions", nothing)),
                                         index=length(b.disruption_layout), sampled_times=Float64[]))
        n += 1
    end
    b.budget = nothing
    if project.simulation["mass_balance"] === true
        mat = b.material_list === nothing ? nothing : get_list(space, b.material_list)
        families = String[(mat === nothing ? String[] : [i.name for i in mat.enabled])...; UNINDEXED]
        nfam = length(families)
        members = Any[]
        for s in states
            s.kind in ("compartment", "waste_package") || continue
            fam_of = fill(nfam - 1, s.width)
            m = findfirst(d -> is_nuclide_dim(b, d), s.dims)
            if m !== nothing && mat !== nothing
                for off in 0:s.width-1
                    nm = tuple_by_list(space, s.dims, off)[s.dims[m]]
                    fam_of[off+1] = get(mat.position_of, nm, nfam - 1)
                end
            end
            push!(members, (name=s.name, base=s.base, width=s.width, fam_of=fam_of))
        end
        b.budget = (base=n, nfam=nfam, families=families, terms=collect(BUDGET_TERMS), members=members)
        push!(states, Entry(name="#mass-balance", local_name="#mass-balance", system="", base=n,
                            width=length(BUDGET_TERMS) * nfam, dims=String[], block=nothing, kind="budget", hidden=true,
                            budget=b.budget))
        n += length(BUDGET_TERMS) * nfam
    end
    b.states = states
    b.nstate = n
    b.state_by_name = Dict(s.name => s for s in states if s.kind == "compartment")
    b.path_by_name = Dict(f.name => f for f in b.farf_layout)
end

function _layout_parameters!(b::Builder)
    project, space = b.project, b.space
    b.param_layout = Entry[]
    n = 0
    for p in project.blocks["parameters"]
        dims = dims_of(b, p)
        w = width(space, dims)
        push!(b.param_layout, Entry(name=p["qname"], local_name=p["name"], system=p["system"], base=n, width=w,
                                    dims=dims, block=p, kind="parameter"))
        n += w
    end
    b.param_by_name = Dict(p.name => p for p in b.param_layout)
    b.point_layout = Entry[]
    for lk in project.blocks["lookups"]
        dims = dims_of(b, lk)
        w = width(space, dims)
        points_at = entry_lookup(lk, "points")
        for off in 0:w-1
            tup = entry_tuple(b, lk, dims, off)
            points = something(points_at(tup), Any[])
            for (i, pt) in enumerate(points)
                spec = (pt isa AbstractVector && length(pt) > 2) ? pt[3] : nothing
                js_truthy(spec) || continue
                push!(b.point_layout, Entry(name=lk["qname"], kind="point", block=lk, dims=dims, index=tup, off=off,
                                            point=i - 1, at=Float64(pt[1]), value=Float64(pt[2]), spec=spec, slot=n,
                                            tab=-1, row=-1))
                n += 1
            end
        end
    end
    b.points_by_entry = Dict{Tuple{String,Int},Vector{Entry}}()
    for pt in b.point_layout
        push!(get!(b.points_by_entry, (pt.name, pt[:off]), Entry[]), pt)
    end
    b.nparam = n
    P = zeros(max(1, n))
    for pt in b.point_layout
        P[pt[:slot]+1] = pt[:value]
    end
    for e in b.param_layout
        value_of = entry_lookup(e.block, "value")
        for off in 0:e.width-1
            tup = entry_tuple(b, e.block, e.dims, off)
            v = value_of(tup)
            num = _builder_number(v)
            isfinite(num) || throw(BuildError("Value '$(js_text(v))' is not a number", e.name))
            P[e.base+off+1] = num
        end
    end
    b.P = P
end

"""The Python engine's `_js_number`: `Number(v)` with Python's reading of text."""
function _builder_number(v)
    v === nothing && return 0.0
    v isa Bool && return v ? 1.0 : 0.0
    v isa Real && return Float64(v)
    s = strip(js_str(v))
    isempty(s) && return 0.0
    f = py_float(s)
    if isnan(f) && !(lowercase(s) in ("nan", "+nan", "-nan"))
        low = lowercase(s)
        (low == "infinity" || low == "+infinity") && return Inf
        low == "-infinity" && return -Inf
        return NaN
    end
    return f
end

function _layout_tables!(b::Builder)
    project, space = b.project, b.space
    b.TAB = LookupTable[]
    b.lookup_layout = Entry[]
    for lk in project.blocks["lookups"]
        dims = dims_of(b, lk)
        w = width(space, dims)
        cache = Dict{UInt,LookupTable}()
        base = length(b.TAB)
        points_at = entry_lookup(lk, "points")
        for off in 0:w-1
            tup = entry_tuple(b, lk, dims, off)
            points = something(points_at(tup), Any[])
            mine = get(b.points_by_entry, (lk["qname"], off), nothing)
            table = mine === nothing ? get(cache, objectid(points), nothing) : nothing
            if table === nothing
                table = try
                    LookupTable(isempty(points) ? Any[Any[0, 0]] : points, something(get(lk, "interpolation", nothing), "linear"),
                                js_truthy(get(lk, "cyclic", nothing)))
                catch e
                    e isa LookupError || rethrow()
                    at = isempty(dims) ? "" : " at $(describe_tuple(tup))"
                    throw(BuildError("$(e.message)$at", lk["qname"]))
                end
                mine === nothing && (cache[objectid(points)] = table)
            end
            push!(b.TAB, table)
            if mine !== nothing
                order = sort(collect(0:length(points)-1); by=i -> _builder_number(points[i+1][1]))
                rank = Dict(frm => to - 1 for (to, frm) in enumerate(order))
                for pt in mine
                    pt[:tab] = length(b.TAB) - 1
                    pt[:row] = get(rank, pt[:point], pt[:point])
                end
            end
        end
        arg = get(lk, "argument", nothing)
        push!(b.lookup_layout, Entry(name=lk["qname"], local_name=lk["name"], system=lk["system"], width=w, dims=dims,
                                     block=lk, kind="lookup_table", tab=base,
                                     argument=js_truthy(arg) ? arg : nothing))
    end
    b.table_by_name = Dict(lk.name => lk for lk in b.lookup_layout if lk[:argument] !== nothing)
end

function _add_algebraic!(b::Builder, name, kind, block, value_key, over=nothing)
    dims = over !== nothing ? Vector{String}(over) : dims_of(b, block)
    w = width(b.space, dims)
    e = Entry(name=name, local_name=jget(block, "name"), system=something(jget(block, "system"), ""), kind=kind,
              block=block, value_key=value_key, dims=dims, base=b.nalg, width=w,
              hidden=js_truthy(jget(block, "hidden")))
    push!(b.algebraic, e)
    b.nalg += w
    return e
end

function _layout_algebraic!(b::Builder)
    project = b.project
    b.algebraic = Entry[]
    b.nalg = 0
    add(args...) = _add_algebraic!(b, args...)
    for e in project.blocks["expressions"]
        add(e["qname"], "expression", e, "equation")
    end
    for t in project.blocks["transfers"]
        slot = add(t["qname"], "transfer", t, "rate")
        scheme = get(t, "availability", nothing)
        (scheme isa AbstractDict && get(scheme, "scheme", nothing) in AVAILABILITY_SCHEMES) || continue
        slot[:availability] = (scheme=scheme, operands=OrderedDict{String,Entry}())
        keys_ = scheme["scheme"] in ("limit", "shared_limit") ? ["limit"] : ["top", "bottom"]
        for key in keys_
            holder = merge(JDict(t), JDict("entries" => Any[], key => get(scheme, key, nothing)))
            op = add("$(slot.name)#$key", "availability:$key", holder, key, slot.dims)
            op.hidden = true
            op[:transfer] = slot.name
            slot[:availability].operands[key] = op
        end
        slot.needs = [op.name for op in values(slot[:availability].operands)]
    end
    for s in project.blocks["inflows"]
        add(s["qname"], "inflow", s, "rate")
    end
    b.dydt_slots = Entry[]
    for c in project.blocks["compartments"]
        has_dydt(c) || continue
        slot = add("$(c["qname"])#dydt", "compartment:dydt", c, "dydt")
        slot.hidden = true
        slot[:state_name] = c["qname"]
        push!(b.dydt_slots, slot)
    end
    for lk in b.lookup_layout
        lk[:argument] !== nothing && continue
        add(lk.name, "lookup", lk.block, "points")[:tab] = lk[:tab]
    end
    for o in project.blocks["index_reductions"]
        add(o["qname"], "index_reduction", o, "target")
    end
    for g in project.blocks["block_reductions"]
        add(g["qname"], "block_reduction", g, "targets")
    end
    for W in b.waste_layout
        setting = OrderedDict{String,Entry}()
        W[:setting] = setting
        for key in WASTE_EQUATION_KEYS
            (startswith(key, "fail_") && !(key in FAILURE_KEYS[W[:failure]])) && continue
            single = !(key in WASTE_NUCLIDE_KEYS)
            slot = add("$(W[:q])#$key", "waste_package:$key", W.block, key, single ? String[] : nothing)
            slot.hidden = true
            single && (slot[:single] = true)
            setting[key] = slot
        end
        hazard = add("$(W[:q])#hazard", "waste_package:hazard", W.block, nothing, String[])
        hazard.hidden = true
        hazard.needs = [setting[k].name for k in FAILURE_KEYS[W[:failure]]]
        hazard[:waste] = W
        W[:hazard_slot] = hazard
        release = add(W[:q], "waste_package", W.block, nothing)
        release.needs = [hazard.name, setting["irf"].name, setting["degradation_rate"].name]
        release[:waste] = W
        W[:release_slot] = release
    end
    for D in b.disruption_layout
        setting = OrderedDict{String,Entry}()
        D[:setting] = setting
        for key in TIMING_KEYS[D[:timing]]
            isempty(strip(js_str(something(get(D.block, key, nothing), "")))) && continue
            slot = add("$(D[:q])#$key", "event:$key", D.block, key, String[])
            slot.hidden = true
            slot[:single] = true
            setting[key] = slot
        end
        shares = Entry[]
        D[:shares] = shares
        for (k, a) in enumerate(D[:actions])
            holder = JDict("name" => D.block["name"], "system" => get(D.block, "system", nothing), "index_lists" => Any[],
                           "entries" => Any[], "fraction" => a["fraction"])
            slot = add("$(D[:q])#share$(k - 1)", "event:share", holder, "fraction", String[])
            slot.hidden = true
            slot[:single] = true
            push!(shares, slot)
        end
        lam_slot = add("$(D[:q])#lambda", "event:lambda", D.block, nothing, String[])
        lam_slot.hidden = true
        lam_slot.needs = [s.name for s in values(setting)]
        lam_slot[:event] = D
        D[:lambda_slot] = lam_slot
        for (k, a) in enumerate(D[:actions])
            a["kind"] == "fail" || continue
            W = get(b.waste_by_name, get(a, "block", nothing), nothing)
            W === nothing && throw(BuildError("'$(js_text(get(a, "block", nothing)))' is not a set of waste packages, so it " *
                                              "has no packages to fail.", D[:q]))
            append!(W[:hazard_slot].needs, [lam_slot.name, shares[k].name])
            push!(W[:disrupted], (D=D, share=shares[k]))
        end
    end
    b.FARF = Any[]
    for p in b.farf_layout
        setting_base = Dict{String,Int}()
        keys_ = active_equation_keys(p.block)
        for key in keys_
            per_nuclide = key in FARF_NUCLIDE_KEYS
            slot = add("$(p.name)#$key", "farfield:$key", p.block, key, per_nuclide ? nothing : p[:farf].other_dims)
            slot.hidden = true
            setting_base[key] = slot.base
            per_nuclide || (slot[:single] = true)
        end
        rel = add(p.name, "farfield", p.block, nothing)
        rel.needs = ["$(p.name)#$key" for key in keys_]
        rel[:farf] = p
        rel[:farf_index] = length(b.FARF)
        p[:alg_release] = rel
        p[:farf_index] = length(b.FARF)
        push!(b.FARF, make_farfield_path(b, p, rel, setting_base, keys_))
    end
    b.MEM = Recorder[]
    b.recorders = Entry[]
    mean_state_by_name = Dict(m.name => m for m in b.mean_states)
    for kind in RECORDER_KINDS
        for blk in project.blocks[RECORDER_COLLECTION[kind]]
            name = blk["qname"]
            aux = OrderedDict{String,Entry}()
            for key in EQUATION_FIELDS[kind]
                slot = add("$name#$key", "$kind:$key", blk, key)
                slot.hidden = true
                aux[key] = slot
            end
            entry = add(name, kind, blk, nothing)
            entry[:aux] = aux
            entry.needs = [a.name for a in values(aux)]
            rec = Entry(name=name, kind=kind, block=blk, dims=entry.dims, width=entry.width, entry=entry, aux=aux,
                        mem=kind in REMEMBERING_KINDS ? length(b.MEM) : -1,
                        state=get(mean_state_by_name, name, nothing))
            if rec[:mem] >= 0
                for off in 0:entry.width-1
                    tup = entry_tuple(b, blk, entry.dims, off)
                    start = value_at(blk, "start_trigger", tup)
                    op = get(blk, "operation", nothing)
                    push!(b.MEM, Recorder(kind, js_truthy(op) ? string(op) : "max",
                                          !(start !== nothing && !isempty(strip(js_str(start))))))
                end
            end
            push!(b.recorders, rec)
            entry[:recorder] = rec
        end
    end
    b.alg_by_name = Dict(a.name => a for a in b.algebraic)
end

# --- parsing ------------------------------------------------------------------------------------

_known(b::Builder, n) = haskey(b.state_by_name, n) || haskey(b.param_by_name, n) || haskey(b.alg_by_name, n) ||
                        haskey(b.table_by_name, n)

function call_target(b::Builder, name, system)
    isempty(b.table_by_name) && return nothing
    q = resolve_reference(name, something(system, ""), n -> _known(b, n))
    return q === nothing ? nothing : get(b.table_by_name, q, nothing)
end

function _prepare_parsing!(b::Builder)
    try
        b.functions = UserFunctions(b.project.blocks["functions"], (n, s) -> call_target(b, n, something(s, "")) !== nothing)
    catch e
        e isa FunctionError || rethrow()
        throw(BuildError(e.message, e.block_name))
    end
    b.unit_blocks = Dict(x["qname"] => x for x in all_blocks(b.project))
end

function_call(b::Builder, name, system) = length(b.functions) > 0 ? resolve_function(b.functions, name, something(system, "")) : nothing
is_callable(b::Builder, name, system) = call_target(b, name, system) !== nothing || function_call(b, name, system) !== nothing

function parse_model_equation(b::Builder, text, system, owner)
    ast = try
        a = parse_equation(text; calls=n -> is_callable(b, n, system))
        _scale_literals!(a, b, system)
        a
    catch e
        if e isa EquationParseError
            m = match(r"^Unknown function '([^']+)'", e.message)
            if m !== nothing
                throw(BuildError("$(e.message) in \"$text\". If '$(m.captures[1])' is meant to be one of this model’s own, " *
                                 "add a function of that name under Functions and write what it works out to; Ecolego " *
                                 "keeps some functions in a library beside the project, and those do not travel with the " *
                                 "file.", owner))
            end
        end
        rethrow()
    end
    length(b.functions) == 0 && return ast
    try
        return inline_functions(b.functions, ast, owner, something(system, ""))
    catch e
        e isa FunctionError || rethrow()
        throw(BuildError(e.message, something(e.block_name, Some(owner))))
    end
end

function target_entry(b::Builder, name, system)
    q = resolve_reference(name, something(system, ""), n -> _known(b, n))
    q === nothing && return nothing
    return something(get(b.state_by_name, q, nothing), get(b.param_by_name, q, nothing), get(b.alg_by_name, q, nothing),
                     get(b.table_by_name, q, nothing), Some(nothing))
end

"""The reduced list of an index operation: the target's first list the block itself is not indexed by."""
function operated_list(own_dims, target_dims, is_scenario=nothing)
    target = [d for d in something(target_dims, String[]) if !(is_scenario !== nothing && is_scenario(d))]
    isempty(target) && return nothing
    own = collect(something(own_dims, String[]))
    isempty(own) && return target[1]
    return findfirst_value(d -> !(d in own), target)
end

function index_operation_ast(b::Builder, a::Entry, target)
    entry = target_entry(b, target, a.system)
    if entry === nothing
        where_ = a.system != "" ? " or in '$(a.system)'" : ""
        throw(BuildError("'$target' is not a block in this model$where_.", a.name))
    end
    dims = entry.dims
    if isempty(dims)
        throw(BuildError("'$target' holds a single value, so there is no index to reduce over. An index operation needs " *
                         "a target with one more dimension than it has itself.", a.name))
    end
    over = operated_list(a.dims, dims, d -> get_list(b.space, d).for_scenarios)
    if over === nothing
        throw(BuildError("'$(a.local_name)' is indexed by every list '$target' is ($(join(dims, ", "))), so there is " *
                         "nothing left to reduce over.", a.name))
    end
    names = index_names(b.space, over)
    isempty(names) && return (ast=ENum(0.0), text="0", over=over, dropped=nothing)
    op = a.block["operation"]
    fn = OPERATION_FUNCTION[op]
    args = ENode[ERef(target, Dict{String,String}(over => idx)) for idx in names]
    shown = ["$target[$idx]" for idx in names]
    if op == "percentile"
        pushfirst!(args, ENum(Float64(a.block["percentile"])))
        pushfirst!(shown, js_str(a.block["percentile"]))
    end
    return (ast=ECall(fn, args), text="$fn($(join(shown, ", ")))", over=over, dropped=nothing)
end

function aggregate_ast(b::Builder, a::Entry, targets)
    kept, dropped = String[], String[]
    for t in targets
        entry = target_entry(b, t, a.system)
        if entry === nothing
            where_ = a.system != "" ? " or in '$(a.system)'" : ""
            throw(BuildError("'$t' is not a block in this model$where_.", a.name))
        end
        try
            projection(b.space, a.dims, entry.dims, Dict{String,String}(), (owner=a.name, target=t))
            push!(kept, t)
        catch e
            e isa IndexSpaceError || rethrow()
            push!(dropped, t)
        end
    end
    if !isempty(dropped) && isempty(kept)
        frm = isempty(a.dims) ? "a single value" : "'$(join(a.dims, ", "))'"
        throw(BuildError("none of its targets ($(join(dropped, ", "))) can be reached from $frm.", a.name))
    end
    isempty(kept) && return (ast=ENum(0.0), text="0", over=nothing, dropped=dropped)
    length(kept) == 1 && return (ast=ERef(kept[1]), text=kept[1], over=nothing, dropped=dropped)
    fn = OPERATION_FUNCTION[a.block["operation"]]
    return (ast=ECall(fn, ENode[ERef(t) for t in kept]), text="$fn($(join(kept, ", ")))", over=nothing, dropped=dropped)
end

function _parse_all!(b::Builder)
    for a in b.algebraic
        a.equations = String[]
        a.asts = ENode[]
        a.uniform = true
        if a.kind == "lookup" || haskey(a, :recorder) || a.kind in ("farfield", "waste_package", "waste_package:hazard", "event:lambda")
            continue
        end
        if a.kind in ("index_reduction", "block_reduction")
            for off in 0:a.width-1
                tup = entry_tuple(b, a.block, a.dims, off)
                if a.kind == "index_reduction"
                    t = value_at(a.block, "target", tup)
                    spec = index_operation_ast(b, a, js_str(t === nothing ? "" : t))
                else
                    spec = aggregate_ast(b, a, something(value_at(a.block, "targets", tup), String[]))
                end
                push!(a.equations, spec.text)
                push!(a.asts, spec.ast)
                spec.over !== nothing && (a[:over] = spec.over)
                (spec.dropped !== nothing && !isempty(spec.dropped)) && (a[:dropped] = spec.dropped)
            end
            a.uniform = all(e -> e == a.equations[1], a.equations)
            continue
        end
        parsed = Dict{String,ENode}()
        value_of = entry_lookup(a.block, a.value_key)
        # Without per-index entries every element has the block's own value,
        # and no element's indices need to be worked out to find it.
        varies = any(e -> e isa AbstractDict && haskey(e, a.value_key), something(jget(a.block, "entries"), Any[]))
        for off in 0:a.width-1
            v = varies ? value_of(entry_tuple(b, a.block, a.dims, off)) : value_of(nothing)
            eq = js_str(v === nothing ? "0" : v)
            push!(a.equations, eq)
            ast = get(parsed, eq, nothing)
            if ast === nothing
                ast = try
                    parse_model_equation(b, eq, a.system, a.name)
                catch e
                    e isa EquationParseError || rethrow()
                    throw(BuildError("$(e.message) in \"$eq\" (at character $(e.position + 1))", a.name))
                end
                parsed[eq] = ast
            end
            push!(a.asts, ast)
        end
        a.uniform = all(e -> e == a.equations[1], a.equations)
    end
end

function _levels!(b::Builder)
    level = Dict{String,Int}()
    for a in b.algebraic
        lv = 0
        for d in a.reads_alg
            haskey(level, d) && (lv = max(lv, level[d] + 1))
        end
        level[a.name] = lv
        a.level = lv
    end
end

# --- resolution -----------------------------------------------------------------------------

"""
    locate(b, owner, source_dims, pos, fixed_tuple, name, indices, node) -> (kind, target, index)

What a reference reads: its kind (`:state`, `:param`, `:alg`, `:table`), the
entry, and the index -- one `Int`, or one per element of the statement
(`pos`, the positions of the statement's elements along `source_dims`).
"""
function locate(b::Builder, owner, source_dims, pos, fixed_tuple, name, indices, node=nothing)
    space = b.space
    owner_name = owner isa AbstractString ? owner : (owner === nothing ? nothing : owner.name)
    scope = node isa ERef ? node.scope : (node isa ECall ? node.scope : nothing)
    owner_system = scope !== nothing ? scope : ((owner isa AbstractString || owner === nothing) ? "" : owner.system)
    qname = resolve_reference(name, owner_system, n -> _known(b, n))
    target = nothing
    if qname !== nothing
        target = something(get(b.state_by_name, qname, nothing), get(b.param_by_name, qname, nothing),
                           get(b.alg_by_name, qname, nothing), get(b.table_by_name, qname, nothing), Some(nothing))
    end
    if target === nothing
        off = resolve_reference(name, owner_system, n -> n in b.project.disabled)
        if off !== nothing
            throw(BuildError("'$name' is disabled, so it has no value for this equation to read. Enable '$off', or " *
                             "disable this block as well.", owner_name))
        end
        tail = owner_system != "" ?
               "in sub-system '$owner_system' or at the top level of this model. To reach a block in another sub-system, " *
               "give its full path, as in '$owner_system.$name'." : "in this model."
        throw(BuildError("Unknown name '$name'. It is not a parameter, compartment, expression or transfer $tail", owner_name))
    end
    kind = haskey(b.state_by_name, qname) ? :state : haskey(b.param_by_name, qname) ? :param :
           haskey(b.table_by_name, qname) ? :table : :alg
    context = owner isa Entry ? get!(() -> implicit_indices(owner), owner.extra, :implicit_context) :
              implicit_indices(owner)
    fixed = indices isa AbstractDict ? Tup(k => v for (k, v) in indices) :
            pin_indices(space, target, indices, name, owner_name, context)
    for dim in target.dims
        haskey(fixed, dim) && continue
        any(sd -> relate(space, dim, sd) !== nothing, source_dims) && continue
        implied = context === nothing ? nothing : get(context, dim, nothing)
        if implied === nothing && context !== nothing
            root = get_list(space, dim).root_name
            if root != dim && get(context, root, nothing) !== nothing
                own = derived_index(space, dim, context[root])
                if own === false
                    what = root == TRANSFER_LIST ? "transfers" : "compartments"
                    throw(BuildError("'$name' has a value per index of '$dim', which is made of $what, and '$owner_name' " *
                                     "is not one of them. Add it to '$dim', or name one, as '$name[<index>]'.", owner_name))
                end
                implied = own
            end
        end
        if implied !== nothing
            fixed[dim] = implied
            continue
        end
        if dim == COMPARTMENT_LIST
            who = owner_name !== nothing ? "'$owner_name'" : "this equation"
            how = (owner isa Entry && owner.kind == "transfer") ?
                  "Write '$name[$SOURCE_INDEX]' for the compartment it flows out of, or '$name[$TARGET_INDEX]' for the one " *
                  "it flows into." : "Name one, as '$name[<compartment>]'."
            throw(BuildError("'$name' has a value per compartment, and $who does not say which. $how", owner_name))
        end
        if dim == TRANSFER_LIST
            who = owner_name !== nothing ? "'$owner_name'" : "this equation"
            throw(BuildError("'$name' has a value per transfer, and $who is not a transfer, so there is no transfer to take " *
                             "it from. Name one, as '$name[<transfer>]'.", owner_name))
        end
    end
    base = kind === :table ? target[:tab] : target.base
    (target.width == 1 && isempty(target.dims)) && return kind, target, base
    if fixed_tuple !== nothing
        tup = merge(Tup(fixed_tuple), fixed)
        off = 0
        st = strides(space, target.dims)
        for (i, dim) in enumerate(target.dims)
            p = position_in(space, dim, tup)
            if p === nothing
                try
                    projection(space, source_dims, [dim], fixed, (owner=owner_name, target=name))
                catch e
                    e isa IndexSpaceError || rethrow()
                    throw(BuildError(e.message, owner_name))
                end
                throw(BuildError("Cannot resolve index '$dim' of '$name'", owner_name))
            end
            off += p * st[i]
        end
        return kind, target, base + off
    end
    terms = try
        projection(space, source_dims, target.dims, fixed, (owner=owner_name, target=name))
    catch e
        e isa IndexSpaceError || rethrow()
        throw(BuildError(e.message, owner_name))
    end
    constant = base
    index = nothing
    for term in terms
        if term.fixed >= 0
            constant += term.fixed * term.stride
            continue
        end
        v = pos[term.from]
        comp = term.table !== nothing ? [term.table[x+1] for x in v] : v
        part = comp .* term.stride
        index = index === nothing ? part : index .+ part
    end
    index === nothing && return kind, target, constant
    index = index .+ constant
    length(index) == 1 && return kind, target, index[1]
    return kind, target, Vector{Int}(index)
end

const _ARRAY_OF = Dict(:state => :y, :param => :P, :alg => :X)

function make_resolver(b::Builder, owner, source_dims, pos, fixed_tuple)
    owner_name = owner isa AbstractString ? owner : owner.name
    return function (name, indices, node=nothing)
        kind, target, index = locate(b, owner, source_dims, pos, fixed_tuple, name, indices, node)
        if kind === :table
            throw(BuildError("'$name' is a lookup table with an argument, so it has no value of its own; call it, as " *
                             "'$name(...)'.", owner_name))
        end
        (kind === :alg && owner isa Entry && target === owner) && push!(b.self_reading, owner.name)
        return TLeaf(_ARRAY_OF[kind], index)
    end
end

function make_call_resolver(b::Builder, owner, source_dims, pos, fixed_tuple)
    owner_name = owner isa AbstractString ? owner : owner.name
    owner_system = owner isa AbstractString ? "" : owner.system
    return function (name, args)
        call_target(b, name, owner_system) === nothing && return nothing
        length(args) != 1 && throw(BuildError("'$name' is a lookup table and takes exactly one argument; $(length(args)) " *
                                              "were given.", owner_name))
        _, target, index = locate(b, owner, source_dims, pos, fixed_tuple, name, Union{Nothing,String}[], nothing)
        return TTab(TLeaf(:TAB, index), args[1])
    end
end

# --- events ---------------------------------------------------------------------------------

function _events!(b::Builder)
    space = b.space
    b.event_slots = NamedTuple{(:slot, :direction, :name, :index),Tuple{Int,Int,String,Union{Nothing,Tup}}}[]
    for rec in b.recorders
        rec.kind == "trigger" || continue
        rec[:event_base] = length(b.event_slots)
        for off in 0:rec.width-1
            tup = entry_tuple(b, rec.block, rec.dims, off)
            written = value_at(rec.block, "direction", tup)
            js_truthy(written) || (written = get(rec.block, "direction", nothing))
            push!(b.event_slots, (slot=rec[:entry].base + off, direction=get(DIRECTION_SIGN, written, 0), name=rec.name,
                                  index=isempty(rec.dims) ? nothing : tuple_by_list(space, rec.dims, off)))
        end
    end
    b.event_direction = Int8[e.direction for e in b.event_slots]
    b.event_handlers = Dict{Int,Vector{NamedTuple{(:rec, :off, :action),Tuple{Entry,Int,Symbol}}}}()
    for rec in b.recorders
        rec[:mem] < 0 && continue
        for field in EVENT_FIELDS[rec.kind]
            for off in 0:rec.width-1
                tup = entry_tuple(b, rec.block, rec.dims, off)
                written = value_at(rec.block, field, tup)
                text = written === nothing ? "" : strip(js_str(written))
                isempty(text) && continue
                ast = try
                    parse_equation(text)
                catch e
                    e isa EquationParseError || rethrow()
                    throw(BuildError("'$text' is not the name of a discrete event.", rec.name))
                end
                ast isa ERef || throw(BuildError("'$(replace(field, '_' => ' '))' must name a discrete event, not an " *
                                                 "expression; '$text' is one.", rec.name))
                kind, target, index = locate(b, rec[:entry], rec.dims, nothing, tup, ast.name, ast.indices)
                owner = get(target, :recorder, nothing)
                if owner === nothing || owner.kind != "trigger"
                    what = field == "trigger" ? "take a snapshot" : replace(field, '_' => ' ')
                    throw(BuildError("'$(ast.name)' is not a discrete event, so it cannot $what.", rec.name))
                end
                which = owner[:event_base] + (index - target.base)
                push!(get!(b.event_handlers, which, NamedTuple{(:rec, :off, :action),Tuple{Entry,Int,Symbol}}[]),
                      (rec=rec, off=off, action=EVENT_ACTION[field]))
            end
        end
    end
end

# --- statements for the algebraic blocks ----------------------------------------------------

function _generate_algebraic!(b::Builder)
    b.self_reading = Set{String}()
    b.alg_stmts = Dict{String,Vector{Stmt}}()
    for a in b.algebraic
        stmts = _statements_for(b, a)
        if a.name in b.self_reading
            split = Stmt[]
            for s in stmts
                if s.tree !== nothing && s.width > 1
                    append!(split, _split_stmt(s))
                else
                    s.mergeable = false
                    push!(split, s)
                end
            end
            stmts = split
            for s in stmts
                s.mergeable = false
            end
        end
        b.alg_stmts[a.name] = stmts
    end
end

_stmt(a::Entry, out, tree, width; sub=0, multiply=false) = Stmt(out, tree, width, a, (a.level, sub); multiply=multiply)
_special(a::Entry, sp::Special, state::Bool, clock::Bool) =
    Stmt(0, nothing, 0, a, (a.level, 0); mergeable=false, special=sp, array=state ? :state : (clock ? :clock : :X))

_xleaf(i) = TLeaf(:X, i)
_tleaf() = TLeaf(:T)

function _statements_for(b::Builder, a::Entry)
    space = b.space
    out = Stmt[]
    if a.kind == "lookup"
        if a.width == 1 && isempty(a.dims)
            push!(out, _stmt(a, a.base, TTab(TLeaf(:TAB, a[:tab]), _tleaf()), 1))
        elseif a.width > 0
            idx = collect(0:a.width-1)
            push!(out, _stmt(a, a.base .+ idx, TTab(TLeaf(:TAB, a[:tab] .+ idx), _tleaf()), a.width))
        end
        return out
    end
    if a.kind == "farfield"
        push!(out, _special(a, FarfieldRelease(a[:farf_index], a[:farf][:farf].laplace), true, false))
        return out
    end
    if a.kind == "waste_package:hazard"
        W = a[:waste]
        at(key) = (slot = get(W[:setting], key, nothing); slot !== nothing ? _xleaf(slot.base) : _k(0.0))
        tree = _hazard_tree(W[:failure], _tleaf(), at("fail_from"), at("fail_to"), at("fail_start"), at("fail_rate"),
                            at("fail_scale"), at("fail_shape"))
        for dis in W[:disrupted]
            tree = TBin(:+, tree, TBin(:*, _xleaf(dis.D[:lambda_slot].base), _xleaf(dis.share.base)))
        end
        push!(out, _stmt(a, a.base, tree, 1))
        return out
    end
    if a.kind == "event:lambda"
        D = a[:event]
        if D[:timing] != "poisson"
            push!(out, _stmt(a, a.base, _k(0.0), 1))
            return out
        end
        frm = haskey(D[:setting], "from") ? _xleaf(D[:setting]["from"].base) : TLeaf(:T0)
        until = haskey(D[:setting], "until") ? _xleaf(D[:setting]["until"].base) : TLeaf(:T1)
        t = _tleaf()
        inside = TBin(OP_AND, TBin(:>=, t, frm), TBin(:<, t, until))
        rate = _xleaf(D[:setting]["rate"].base)
        tree = TBin(:*, TLeaf(:DIS, D[:index]), TCond(inside, rate, _k(0.0)))
        push!(out, _stmt(a, a.base, tree, 1))
        return out
    end
    if a.kind == "waste_package"
        W = a[:waste]
        a.width == 0 && return out
        if a.width > 1
            idx = collect(0:a.width-1)
            leaf(kind, base) = TLeaf(kind, base .+ idx)
            outs = a.base .+ idx
        else
            leaf = (kind, base) -> TLeaf(kind, base)
            outs = a.base
        end
        tree = TBin(:+, TBin(:*, TBin(:*, _xleaf(W[:hazard_slot].base), leaf(:y, W[:intact].base)),
                             leaf(:X, W[:setting]["irf"].base)),
                    TBin(:*, leaf(:X, W[:setting]["degradation_rate"].base), leaf(:y, W[:exposed].base)))
        push!(out, _stmt(a, outs, tree, a.width))
        return out
    end
    rec = get(a, :recorder, nothing)
    if rec !== nothing
        a.width == 0 && return out
        k = rec.kind
        if k == "trigger"
            if a.width > 1
                idx = collect(0:a.width-1)
                tree = TBin(:-, TLeaf(:X, rec[:aux]["first"].base .+ idx), TLeaf(:X, rec[:aux]["second"].base .+ idx))
                push!(out, _stmt(a, a.base .+ idx, tree, a.width))
            else
                tree = TBin(:-, _xleaf(rec[:aux]["first"].base), _xleaf(rec[:aux]["second"].base))
                push!(out, _stmt(a, a.base, tree, a.width))
            end
            return out
        end
        offs = collect(0:a.width-1)
        outs = a.base .+ offs
        mems = rec[:mem] .+ offs
        if k == "min_max"
            sp = RecorderRead(:min_max, outs, mems, rec[:aux]["target"].base .+ offs, Int[])
        elseif k == "running_mean"
            sp = RecorderRead(:running_mean, outs, mems, rec[:aux]["target"].base .+ offs, rec[:state].base .+ offs)
        elseif k == "snapshot"
            sp = RecorderRead(:snapshot, outs, mems, Int[], Int[])
        else
            sp = RecorderRead(:delay, outs, mems, rec[:aux]["delay"].base .+ offs, Int[])
        end
        push!(out, _special(a, sp, true, false))
        return out
    end
    a.width == 0 && return out
    if a.width == 1 && isempty(a.dims)
        tree = _resolve_stmt_tree(b, a, a.asts[1], String[], nothing, Tup())
        push!(out, _stmt(a, a.base, tree, 1))
    elseif a.uniform
        pos = positions(space, a.dims)
        tree = _resolve_stmt_tree(b, a, a.asts[1], a.dims, pos, nothing)
        push!(out, _stmt(a, a.base .+ collect(0:a.width-1), tree, a.width))
    else
        append!(out, _by_equation(b, a))
    end
    haskey(a, :availability) && append!(out, _availability(b, a))
    return out
end

function _resolve_stmt_tree(b::Builder, a::Entry, ast::ENode, dims, pos, tup)
    try
        return resolve_tree(ast, make_resolver(b, a, dims, pos, tup), make_call_resolver(b, a, dims, pos, tup))
    catch e
        (e isa BuildError || e isa IndexSpaceError) && rethrow()
        e isa ArgumentError && throw(BuildError(e.msg, a.name))
        e isa ErrorException && throw(BuildError(e.msg, a.name))
        rethrow()
    end
end

function _by_equation(b::Builder, a::Entry)
    space = b.space
    dims = a.dims
    flat = flat_dimensions(space, a)
    if !isempty(flat)
        try
            return _groups(b, a, Set(flat))
        catch e
            (e isa BuildError || e isa IndexSpaceError) || rethrow()
        end
    end
    out = Stmt[]
    for off in 0:a.width-1
        tup = tuple_by_list(space, dims, off)
        tree = _resolve_stmt_tree(b, a, a.asts[off+1], dims, nothing, tup)
        push!(out, _stmt(a, a.base + off, tree, 1))
    end
    return out
end

function _groups(b::Builder, a::Entry, flat_set::Set{String})
    space = b.space
    dims = a.dims
    st = strides(space, dims)
    sizes = [list_size(space, d) for d in dims]
    varying = [i for i in 1:length(dims) if !(dims[i] in flat_set)]
    looped = [i for i in 1:length(dims) if dims[i] in flat_set]
    groups = 1
    for i in varying
        groups *= sizes[i]
    end
    # The looped dimensions' positions, in loop order (outer first: the last fastest).
    lsizes = [sizes[i] for i in looped]
    count = isempty(looped) ? 1 : prod(lsizes)
    grids = [zeros(Int, count) for _ in looped]
    if !isempty(looped)
        lst = ones(Int, length(looped))
        for i in length(looped)-1:-1:1
            lst[i] = lst[i+1] * lsizes[i+1]
        end
        for c in 0:count-1
            rest = c
            for j in 1:length(looped)
                q = div(rest, lst[j])
                rest -= q * lst[j]
                grids[j][c+1] = q
            end
        end
    end
    out = Stmt[]
    for g in 0:groups-1
        at = zeros(Int, length(dims))
        rest = g
        for k in length(varying):-1:1
            i = varying[k]
            at[i] = rest % sizes[i]
            rest = div(rest, sizes[i])
        end
        base = a.base + sum(at[i] * st[i] for i in 1:length(dims))
        ast = a.asts[base-a.base+1]
        pos = Vector{Int}[]
        offs = fill(base, count)
        for i in 1:length(dims)
            if dims[i] in flat_set
                p = grids[findfirst(==(i), looped)]
                offs = offs .+ p .* st[i]
            else
                p = fill(at[i], count)
            end
            push!(pos, p)
        end
        tree = _resolve_stmt_tree(b, a, ast, dims, pos, nothing)
        push!(out, _stmt(a, count > 1 ? offs : offs[1], tree, count))
    end
    return out
end

function _availability(b::Builder, a::Entry)
    t = a.block
    src = js_truthy(get(t, "from", nothing)) ? get(b.state_by_name, t["from"], nothing) : nothing
    if src === nothing
        throw(BuildError("'$(t["name"])' has an availability, which is a fraction of what is in the compartment it flows " *
                         "out of, and it does not flow out of one.", t["name"]))
    end
    scheme = a[:availability].scheme
    operands = a[:availability].operands
    a.width == 0 && return Stmt[]
    pos = positions(b.space, a.dims)
    idx = a.width > 1 ? collect(0:a.width-1) : nothing
    terms = _availability_terms(b, t, scheme, src, a, pos)
    amount = _availability_sum(terms)
    ops = Dict{String,TNode}(key => (idx === nothing ? _xleaf(op.base) : TLeaf(:X, op.base .+ idx)) for (key, op) in operands)
    tree = _availability_expression(scheme, amount, ops)
    return Stmt[_stmt(a, idx === nothing ? a.base : a.base .+ idx, tree, a.width; sub=1, multiply=true)]
end

function _availability_terms(b::Builder, transfer, scheme, src::Entry, alg::Entry, pos)
    space = b.space
    base = state_offsets(b, alg.dims, pos, src, transfer["name"], alg.width)
    own = Any[(off=base, factor=1.0, when=nothing)]
    get(scheme, "scheme", nothing) in ("shared_limit", "shared_langmuir") || return own
    over = strip(js_str(something(get(scheme, "over", nothing), "")))
    dims = src.dims
    which = something(findfirst(==(over), dims), 0) - 1
    groups = nothing
    if which < 0 && !isempty(over) && has_list(space, over)
        grouping = get_list(space, over)
        for k in 0:length(dims)-1
            which >= 0 && break
            (grouping.mapping === nothing || grouping.root_name != get_list(space, dims[k+1]).root_name) && continue
            rel = relate(space, over, dims[k+1])
            (rel === nothing || rel.kind !== :map) && continue
            which = k
            groups = rel.table
        end
    end
    which < 0 && return own
    along = dims[which+1]
    size = list_size(space, along)
    size > 1 || return own
    stride = strides(space, dims)[which+1]
    peer = nothing
    at = findfirst(==(along), alg.dims)
    if at !== nothing
        peer = pos[at]
    else
        for k in 1:length(alg.dims)
            rel = relate(space, along, alg.dims[k])
            if rel !== nothing && rel.kind === :map
                peer = [rel.table[x+1] for x in pos[k]]
                break
            end
        end
    end
    if peer === nothing
        throw(BuildError("'$(transfer["name"])' shares its amount along '$along', which the transfer is not indexed by, so " *
                         "there is no telling which member of the group each flux belongs to.", transfer["name"]))
    end
    first_ = base .- stride .* peer
    moles = get(scheme, "basis", nothing) == "moles"
    names = get_list(space, along).enabled
    unit = js_truthy(get(b.project.simulation, "time_unit", nothing)) ? b.project.simulation["time_unit"] : "year"
    seconds_per = TIME_UNITS[unit] * SECONDS_PER_YEAR
    group_at = groups !== nothing ? [groups[x+1] for x in peer] : nothing
    terms = Any[]
    for i in 0:size-1
        (groups !== nothing && groups[i+1] < 0) && continue
        if moles
            lam_i = lam(i < length(names) ? names[i+1].name : nothing, unit, b.project.half_lives)
            factor = _moles_per_unit(b.project.decay_unit, lam_i, seconds_per)
        else
            factor = 1.0
        end
        factor == 0 && continue
        push!(terms, (off=first_ .+ i * stride, factor=factor, when=group_at !== nothing ? (group_at, groups[i+1]) : nothing))
    end
    return terms
end

"""Where a state block is read from inside `source_dims` (`stateOffsetExpr`): an Int, or one per element."""
function state_offsets(b::Builder, source_dims, pos, entry, owner, width)
    entry === nothing && return 0
    if isempty(entry.dims)
        return width <= 1 ? entry.base : fill(entry.base, width)
    end
    terms = try
        projection(b.space, source_dims, entry.dims, Dict{String,String}(), (owner=owner, target=entry.name))
    catch e
        e isa IndexSpaceError || rethrow()
        throw(BuildError(e.message, owner))
    end
    idx = fill(entry.base, max(width, 1))
    for term in terms
        if term.fixed >= 0
            idx .+= term.fixed * term.stride
            continue
        end
        v = pos[term.from]
        comp = term.table !== nothing ? [term.table[x+1] for x in v] : v
        idx = idx .+ comp .* term.stride
    end
    return width > 1 ? idx : idx[1]
end

function farf_inlet(b::Builder, source_dims, pos, entry::Entry, owner, width)
    farf = entry[:farf]
    terms = try
        projection(b.space, source_dims, entry.dims, Dict{String,String}(), (owner=owner, target=entry.name))
    catch e
        e isa IndexSpaceError || rethrow()
        throw(BuildError(e.message, owner))
    end
    stride = Dict{String,Int}()
    farf.list_name !== nothing && (stride[farf.list_name] = 1)
    other_st = strides(b.space, farf.other_dims)
    for (i, d) in enumerate(farf.other_dims)
        stride[d] = other_st[i] * farf.ncells * farf.nnuc
    end
    idx = fill(entry.base, max(width, 1))
    for term in terms
        st = stride[term.dim]
        if term.fixed >= 0
            idx .+= term.fixed * st
            continue
        end
        v = pos[term.from]
        comp = term.table !== nothing ? [term.table[x+1] for x in v] : v
        idx = idx .+ comp .* st
    end
    return width > 1 ? idx : idx[1]
end

# --- which slots move -----------------------------------------------------------------------

function _classes!(b::Builder)
    on_state = Set{String}()
    on_clock = Set{String}()
    for a in b.algebraic
        state = clock = false
        for s in b.alg_stmts[a.name]
            if s.special !== nothing
                state = state || s.array === :state
                clock = clock || s.array === :clock
                continue
            end
            for leaf in tree_leaves(s.tree)
                if leaf.kind === :y
                    state = true
                elseif leaf.kind in (:T, :T0, :T1, :TAB, :DIS)
                    clock = true
                end
            end
        end
        for d in a.reads_alg
            d in on_state && (state = true)
            d in on_clock && (clock = true)
        end
        state && push!(on_state, a.name)
        clock && push!(on_clock, a.name)
    end
    slot_class = zeros(UInt8, max(1, b.nalg))
    b.pass_stmts = Dict(0 => Stmt[], 1 => Stmt[], 2 => Stmt[])
    for a in b.algebraic
        cls = a.name in on_state ? 2 : (a.name in on_clock ? 1 : 0)
        a.cls = cls
        a.width > 0 && (slot_class[a.base+1:a.base+a.width] .= cls)
        for s in b.alg_stmts[a.name]
            s.special !== nothing && (s.array = :X)
            push!(b.pass_stmts[cls], s)
        end
    end
    b.slot_class = slot_class
    b.on_state = on_state
    b.on_clock = on_clock
end

# --- which of the moving blocks the derivative reads ----------------------------------------

"""
The moving blocks the derivative's phases read, and whatever those read in
turn (`derivativeReads`): the derivative and its Jacobian leave the others out
(a dose, a concentration: only results, recorders and events read them).
`derivative_stmts` is the moving pass without them, in the same order, and
`derivative_blocks` their names: both `nothing` when nothing is left out.
"""
function _derivative_reads!(b::Builder)
    b.derivative_blocks = nothing
    b.derivative_stmts = nothing
    slots = Int[]
    for ph in b.phases
        k = ph.kind
        if k === :transfers
            append!(slots, b.flux_rate[ph.a.+1])
        elseif k === :x || k === :mean
            append!(slots, ph.a)
        elseif k === :waste
            push!(slots, ph.s1)
            append!(slots, ph.b)
        elseif k === :move
            push!(slots, ph.s1, ph.s2)
        elseif k === :farf
            append!(slots, vec(farfield_setting_slots(b.FARF[ph.s1+1])))
        elseif k !== :coef
            return
        end
    end
    for W in b.waste_layout
        W.width > 0 && append!(slots, W[:setting]["irf"].base .+ collect(0:W.width-1))
    end
    for D in b.disruption_layout
        for s in D[:shares]
            push!(slots, s.base)
        end
    end
    owner = fill(-1, max(1, b.nalg))
    for (k, a) in enumerate(b.algebraic)
        a.width > 0 && (owner[a.base+1:a.base+a.width] .= k)
    end
    index = Dict(a.name => k for (k, a) in enumerate(b.algebraic))
    need = Set{Int}()
    for s in slots
        o = owner[s+1]
        o >= 1 && push!(need, o)
    end
    stack = collect(need)
    while !isempty(stack)
        a = b.algebraic[pop!(stack)]
        more = Int[index[n] for n in a.reads_alg if haskey(index, n)]
        for s in b.alg_stmts[a.name]
            s.tree === nothing && continue
            for leaf in tree_leaves(s.tree)
                leaf.kind === :X || continue
                if leaf.indices === nothing
                    o = owner[leaf.index+1]
                    o >= 1 && push!(more, o)
                else
                    for i in leaf.indices
                        o = owner[i+1]
                        o >= 1 && push!(more, o)
                    end
                end
            end
        end
        for k in more
            if !(k in need)
                push!(need, k)
                push!(stack, k)
            end
        end
    end
    all(k -> k in need, [k for (k, a) in enumerate(b.algebraic) if a.cls == 2]) && return
    b.derivative_blocks = Set(b.algebraic[k].name for k in need)
    b.derivative_stmts = Stmt[s for (k, a) in enumerate(b.algebraic) if a.cls == 2 && k in need for s in b.alg_stmts[a.name]]
end

# --- the derivative -------------------------------------------------------------------------

"""Which budget family each element of a loop over `dims` is in (`familyExpr`)."""
function family_of(b::Builder, dims, pos, width)
    nfam = b.budget.nfam
    k = findfirst(d -> is_nuclide_dim(b, d), dims)
    k === nothing && return fill(nfam - 1, width)
    dims[k] == b.material_list && return copy(pos[k])
    rel = relate(b.space, b.material_list, dims[k])
    table = rel !== nothing ? rel.table : fill(-1, list_size(b.space, dims[k]))
    return [(f = table[x+1]; f < 0 ? nfam - 1 : f) for x in pos[k]]
end

function endpoint_family(b::Builder, entry::Entry, dims, pos, width)
    any(d -> is_nuclide_dim(b, d), entry.dims) && return family_of(b, dims, pos, width)
    return fill(b.budget.nfam - 1, width)
end

function family_key(b::Builder, entry::Entry, dims)
    (any(d -> is_nuclide_dim(b, d), entry.dims) && any(d -> is_nuclide_dim(b, d), dims)) && return "loop"
    return "unindexed"
end

budget_at(b::Builder, term::AbstractString, fam) = b.budget.base + (findfirst(==(term), BUDGET_TERMS) - 1) * b.budget.nfam .+ fam

_as_vec(v, width) = v isa Integer ? fill(Int(v), width) : Vector{Int}(v)

function _interleave(cols::Vector{Vector{T}}) where {T}
    W = length(cols[1])
    out = Vector{T}(undef, W * length(cols))
    k = 1
    for i in 1:W, c in cols
        out[k] = c[i]
        k += 1
    end
    return out
end

function _assembly!(b::Builder)
    space, project = b.space, b.project
    budget = b.budget
    b.phases = Phase[]
    ph = b.phases
    rate_idx = Vector{Int}[]
    mbd_mask = Vector{Bool}[]
    src_idx = Vector{Int}[]
    contrib_flux = Vector{Int}[]
    contrib_sign = Vector{Float64}[]
    contrib_tgt = Vector{Int}[]
    nflux = 0
    laplace_in = Dict{Int,Vector{Any}}()
    for t in project.blocks["transfers"]
        alg = b.alg_by_name[t["qname"]]
        src = js_truthy(get(t, "from", nothing)) ? get(b.state_by_name, t["from"], nothing) : nothing
        tgt = js_truthy(get(t, "to", nothing)) ? get(b.state_by_name, t["to"], nothing) : nothing
        path = (js_truthy(get(t, "to", nothing)) && tgt === nothing) ? get(b.path_by_name, t["to"], nothing) : nothing
        mbd = get(t, "multiply_by_donor", nothing) !== false
        if mbd && src === nothing
            throw(BuildError("A transfer with no source compartment cannot be multiplied by its donor; set " *
                             "\"multiply_by_donor\": false to give an absolute flux.", t["name"]))
        end
        W = alg.width
        (W == 0 || any(d -> list_size(space, d) == 0, alg.dims)) && continue
        pos = isempty(alg.dims) ? Vector{Int}[] : positions(space, alg.dims)
        k = collect(nflux:nflux+W-1)
        nflux += W
        push!(rate_idx, alg.base .+ collect(0:W-1))
        s_off = src !== nothing ? _as_vec(state_offsets(b, alg.dims, pos, src, t["name"], W), W) : nothing
        g_off = tgt !== nothing ? _as_vec(state_offsets(b, alg.dims, pos, tgt, t["name"], W), W) : nothing
        p_off = path !== nothing ? _as_vec(farf_inlet(b, alg.dims, pos, path, t["name"], W), W) : nothing
        if path !== nothing && path[:farf].laplace
            donor = (mbd && s_off !== nothing) ? s_off : fill(-1, W)
            push!(get!(laplace_in, path[:farf_index], Any[]), (p_off .- path.base, alg.base .+ collect(0:W-1), donor))
        end
        push!(mbd_mask, fill(mbd, W))
        push!(src_idx, s_off !== nothing ? s_off : fill(-1, W))
        cols_t = Vector{Int}[]
        cols_s = Vector{Float64}[]
        if src !== nothing
            push!(cols_t, s_off)
            push!(cols_s, fill(-1.0, W))
        end
        if tgt !== nothing
            push!(cols_t, g_off)
            push!(cols_s, fill(1.0, W))
        end
        if path !== nothing
            push!(cols_t, p_off)
            push!(cols_s, fill(1.0, W))
        end
        if budget !== nothing
            f_s = src !== nothing ? endpoint_family(b, src, alg.dims, pos, W) : nothing
            f_t = tgt !== nothing ? endpoint_family(b, tgt, alg.dims, pos, W) : nothing
            if src !== nothing && tgt === nothing
                push!(cols_t, budget_at(b, "out", f_s))
                push!(cols_s, fill(1.0, W))
            end
            if src === nothing && tgt !== nothing && !haskey(b.waste_by_name, get(t, "from", nothing))
                push!(cols_t, budget_at(b, "in", f_t))
                push!(cols_s, fill(1.0, W))
            end
            if src !== nothing && tgt !== nothing && family_key(b, src, alg.dims) != family_key(b, tgt, alg.dims)
                push!(cols_t, budget_at(b, "between", f_s))
                push!(cols_s, fill(-1.0, W))
                push!(cols_t, budget_at(b, "between", f_t))
                push!(cols_s, fill(1.0, W))
            end
        end
        isempty(cols_t) && continue
        T = _interleave(cols_t)
        S = _interleave(cols_s)
        Fk = _interleave([k for _ in cols_t])
        keep = T .>= 0
        push!(contrib_tgt, T[keep])
        push!(contrib_sign, S[keep])
        push!(contrib_flux, Fk[keep])
    end
    for p in b.farf_layout
        p[:farf].laplace || continue
        F = b.FARF[p[:farf_index]+1]
        W = farfield_slots(F)
        W == 0 && continue
        k = collect(nflux:nflux+W-1)
        nflux += W
        push!(rate_idx, copy(farfield_release_slots(F)))
        push!(mbd_mask, fill(false, W))
        push!(src_idx, fill(-1, W))
        push!(contrib_tgt, copy(farfield_held_idx(F)))
        push!(contrib_sign, fill(-1.0, W))
        push!(contrib_flux, k)
    end
    b.nflux = nflux
    if nflux > 0
        b.flux_rate = reduce(vcat, rate_idx)
        mbd = reduce(vcat, mbd_mask)
        b.flux_mbd = findall(mbd) .- 1
        b.flux_mbd_src = reduce(vcat, src_idx)[b.flux_mbd.+1]
        push!(ph, Phase(:transfers; tgt=isempty(contrib_tgt) ? Int[] : reduce(vcat, contrib_tgt),
                        a=isempty(contrib_flux) ? Int[] : reduce(vcat, contrib_flux),
                        f=isempty(contrib_sign) ? Float64[] : reduce(vcat, contrib_sign)))
    else
        b.flux_rate = Int[]
        b.flux_mbd = Int[]
        b.flux_mbd_src = Int[]
    end

    # Inflows: + rate into the target (or a path's inlet), and 'in' to the budget.
    tg = Vector{Int}[]
    xs = Vector{Int}[]
    for s in project.blocks["inflows"]
        alg = b.alg_by_name[s["qname"]]
        tgt = get(b.state_by_name, get(s, "to", nothing), nothing)
        path = tgt !== nothing ? nothing : get(b.path_by_name, get(s, "to", nothing), nothing)
        W = alg.width
        (W == 0 || any(d -> list_size(space, d) == 0, alg.dims)) && continue
        pos = isempty(alg.dims) ? Vector{Int}[] : positions(space, alg.dims)
        target = tgt !== nothing ? _as_vec(state_offsets(b, alg.dims, pos, tgt, s["name"], W), W) :
                 _as_vec(farf_inlet(b, alg.dims, pos, path, s["name"], W), W)
        rate = alg.base .+ collect(0:W-1)
        if path !== nothing && path[:farf].laplace
            push!(get!(laplace_in, path[:farf_index], Any[]), (target .- path.base, copy(rate), fill(-1, W)))
        end
        cols_t = Vector{Int}[target]
        cols_x = Vector{Int}[rate]
        if budget !== nothing && tgt !== nothing
            push!(cols_t, budget_at(b, "in", endpoint_family(b, tgt, alg.dims, pos, W)))
            push!(cols_x, rate)
        end
        push!(tg, _interleave(cols_t))
        push!(xs, _interleave(cols_x))
    end
    isempty(tg) || push!(ph, Phase(:x; tgt=reduce(vcat, tg), a=reduce(vcat, xs)))
    for p in b.farf_layout
        p[:farf].laplace || continue
        terms = get(laplace_in, p[:farf_index], Any[])
        farfield_set_inflow!(b.FARF[p[:farf_index]+1],
                             isempty(terms) ? Int[] : reduce(vcat, [q[1] for q in terms]),
                             isempty(terms) ? Int[] : reduce(vcat, [q[2] for q in terms]),
                             isempty(terms) ? Int[] : reduce(vcat, [q[3] for q in terms]))
    end

    # Waste packages: fail out of the intact inventory, fail - release into the exposed.
    for W in b.waste_layout
        W.width == 0 && continue
        Pd = W[:intact]
        pos = isempty(Pd.dims) ? Vector{Int}[] : positions(space, Pd.dims)
        carried = any(t -> get(t, "from", nothing) == W[:q] && get(t, "to", nothing) !== nothing &&
                               haskey(b.state_by_name, t["to"]), project.blocks["transfers"])
        idx = collect(0:W.width-1)
        out_budget = (budget !== nothing && !carried) ? budget_at(b, "out", family_of(b, Pd.dims, pos, W.width)) : Int[]
        push!(ph, Phase(:waste; tgt=Pd.base .+ idx, a=W[:exposed].base .+ idx, s1=W[:hazard_slot].base,
                        b=W[:release_slot].base .+ idx, c=out_budget))
    end

    # Disruptive events: the count, and moves at the expected-value rate.
    for D in b.disruption_layout
        push!(ph, Phase(:x; tgt=[D[:entry].base], a=[D[:lambda_slot].base]))
        for (k, a) in enumerate(D[:actions])
            a["kind"] == "move" || continue
            A, B = _move_ends(b, D, a)
            A.width == 0 && continue
            pos = isempty(A.dims) ? Vector{Int}[] : positions(space, A.dims)
            idx = collect(0:A.width-1)
            second = if B !== nothing
                B.base .+ idx
            elseif budget !== nothing
                budget_at(b, "out", family_of(b, A.dims, pos, A.width))
            else
                Int[]
            end
            push!(ph, Phase(:move; tgt=A.base .+ idx, a=second, s1=D[:lambda_slot].base, s2=D[:shares][k].base))
        end
    end

    # Explicit dy/dt terms.
    tg, xs = Vector{Int}[], Vector{Int}[]
    for slot in b.dydt_slots
        st = b.state_by_name[slot[:state_name]]
        slot.width == 0 && continue
        pos = isempty(slot.dims) ? Vector{Int}[] : positions(space, slot.dims)
        idx = collect(0:slot.width-1)
        cols_t = Vector{Int}[st.base .+ idx]
        cols_x = Vector{Int}[slot.base .+ idx]
        if budget !== nothing
            push!(cols_t, budget_at(b, "explicit", endpoint_family(b, st, slot.dims, pos, slot.width)))
            push!(cols_x, slot.base .+ idx)
        end
        push!(tg, _interleave(cols_t))
        push!(xs, _interleave(cols_x))
    end
    isempty(tg) || push!(ph, Phase(:x; tgt=reduce(vcat, tg), a=reduce(vcat, xs)))

    # Running means: dS/dt = target while recording.
    for rec in b.recorders
        (rec.kind != "running_mean" || rec.width == 0) && continue
        idx = collect(0:rec.width-1)
        push!(ph, Phase(:mean; tgt=rec[:state].base .+ idx, a=rec[:aux]["target"].base .+ idx, s1=rec[:mem]))
    end

    # Decay and ingrowth, per decaying state block, along its nuclide list.
    b.decay_lists = String[]
    decay_index = Dict{String,Int}()
    decay_slot(list_name) = get!(decay_index, list_name) do
        push!(b.decay_lists, list_name)
        length(b.decay_lists) - 1
    end
    b.decaying = Any[]
    for s in b.states
        s.kind in ("compartment", "waste_package") || continue
        (get(s.block, "handle_decay", nothing) === false || b.material_list === nothing) && continue
        m = findfirst(d -> is_nuclide_dim(b, d), s.dims)
        m === nothing && continue
        push!(b.decaying, (state=s, m=m, slot=decay_slot(s.dims[m])))
    end
    tables = Dict{String,DecayTables}()
    for lst in b.decay_lists
        model = lst == b.material_list ? b.decay : decay_model_for(project, lst)
        tables[lst] = decay_tables(model, list_size(space, lst))
    end
    tg = Vector{Int}[]
    sc = Vector{Float64}[]
    sr = Vector{Int}[]
    for d in b.decaying
        s = d.state
        s.width == 0 && continue
        D = tables[s.dims[d.m]]
        pos = positions(space, s.dims)
        stride_m = strides(space, s.dims)[d.m]
        nm = pos[d.m]
        si = s.base .+ collect(0:s.width-1)
        lam_v = D.lam[nm.+1]
        fam = budget !== nothing ? family_of(b, s.dims, pos, s.width) : nothing
        cnt = D.icnt[nm.+1]
        maxc = isempty(cnt) ? 0 : maximum(cnt)
        ncols = 1 + (budget !== nothing ? 1 : 0) + maxc * (budget !== nothing ? 2 : 1)
        Tm = fill(-1, s.width, ncols)
        Cm = zeros(s.width, ncols)
        Rm = zeros(Int, s.width, ncols)
        Tm[:, 1] = si
        Cm[:, 1] = -lam_v
        Rm[:, 1] = si
        col = 2
        if budget !== nothing
            Tm[:, 2] = budget_at(b, "decay", fam)
            Cm[:, 2] = lam_v
            Rm[:, 2] = si
            col = 3
        end
        for q in 0:maxc-1
            has = cnt .> q
            o = [h ? D.ioff[x+1] + q : 0 for (h, x) in zip(has, nm)]
            coef = isempty(D.icoef) ? zeros(s.width) : D.icoef[o.+1]
            par = isempty(D.ipar) ? zeros(Int, s.width) : D.ipar[o.+1]
            src = si .+ (par .- nm) .* stride_m
            Tm[:, col] = [h ? x : -1 for (h, x) in zip(has, si)]
            Cm[:, col] = coef
            Rm[:, col] = [h ? x : 0 for (h, x) in zip(has, src)]
            col += 1
            if budget !== nothing
                ba = budget_at(b, "ingrowth", fam)
                Tm[:, col] = [h ? x : -1 for (h, x) in zip(has, ba)]
                Cm[:, col] = coef
                Rm[:, col] = [h ? x : 0 for (h, x) in zip(has, src)]
                col += 1
            end
        end
        Tf, Cf, Rf = vec(permutedims(Tm)), vec(permutedims(Cm)), vec(permutedims(Rm))
        keep = Tf .>= 0
        push!(tg, Tf[keep])
        push!(sc, Cf[keep])
        push!(sr, Rf[keep])
    end
    isempty(tg) || push!(ph, Phase(:coef; tgt=reduce(vcat, tg), f=reduce(vcat, sc), a=reduce(vcat, sr)))

    # Far-field paths: transport inside, then decay along their chain.
    for p in b.farf_layout
        dec = nothing
        if get(p.block, "handle_decay", nothing) !== false && p[:farf].list_name !== nothing
            p[:decay_slot] = decay_slot(p[:farf].list_name)
            if !haskey(tables, p[:farf].list_name)
                model = p[:farf].list_name == b.material_list ? b.decay : decay_model_for(project, p[:farf].list_name)
                tables[p[:farf].list_name] = decay_tables(model, list_size(space, p[:farf].list_name))
            end
            dec = tables[p[:farf].list_name]
        else
            p[:decay_slot] = nothing
        end
        F = b.FARF[p[:farf_index]+1]
        farfield_set_decay!(F, dec)
        p[:farf].laplace || push!(ph, Phase(:farf; s1=p[:farf_index]))
        if dec !== nothing
            nnuc = p[:farf].nnuc
            starts = farfield_cell_starts(F)
            si = vec([s + m for m in 0:nnuc-1, s in starts])
            mm = repeat(collect(0:nnuc-1), length(starts))
            maxc = isempty(dec.icnt) ? 0 : maximum(dec.icnt)
            Tm = fill(-1, length(si), 1 + maxc)
            Cm = zeros(length(si), 1 + maxc)
            Rm = zeros(Int, length(si), 1 + maxc)
            Tm[:, 1] = si
            Cm[:, 1] = -dec.lam[mm.+1]
            Rm[:, 1] = si
            for q in 0:maxc-1
                has = dec.icnt[mm.+1] .> q
                o = [h ? dec.ioff[x+1] + q : 0 for (h, x) in zip(has, mm)]
                Tm[:, 2+q] = [h ? x : -1 for (h, x) in zip(has, si)]
                Cm[:, 2+q] = isempty(dec.icoef) ? zeros(length(si)) : dec.icoef[o.+1]
                base_cell = si .- mm
                Rm[:, 2+q] = [h ? bc + (isempty(dec.ipar) ? 0 : dec.ipar[oo+1]) : 0 for (h, bc, oo) in zip(has, base_cell, o)]
            end
            Tf, Cf, Rf = vec(permutedims(Tm)), vec(permutedims(Cm)), vec(permutedims(Rm))
            keep = Tf .>= 0
            push!(ph, Phase(:coef; tgt=Tf[keep], f=Cf[keep], a=Rf[keep]))
        end
    end
    b.DEC_tables = tables
end

function _move_ends(b::Builder, D::Entry, a)
    A = get(b.state_by_name, get(a, "from", nothing), nothing)
    A === nothing && throw(BuildError("'$(js_text(get(a, "from", nothing)))' is not a compartment, so there is nothing to " *
                                      "move out of it.", D[:q]))
    to = get(a, "to", nothing)
    B = js_truthy(to) ? get(b.state_by_name, to, nothing) : nothing
    (js_truthy(to) && B === nothing) && throw(BuildError("'$to' is not a compartment, so nothing can be moved into it.", D[:q]))
    if B !== nothing && (B.width != A.width || join(B.dims, ",") != join(A.dims, ","))
        fa = isempty(A.dims) ? "by nothing" : join(A.dims, " × ")
        fb = isempty(B.dims) ? "by nothing" : join(B.dims, " × ")
        throw(BuildError("'$(a["from"])' and '$to' are indexed differently ($fa against $fb). An event moves a share cell " *
                         "for cell, so the two have to match.", D[:q]))
    end
    return A, B
end

# --- jumps ----------------------------------------------------------------------------------

function _fail_op(b::Builder, W::Entry, share_slot::Int)
    Pd, M = W[:intact], W[:exposed]
    carrier = findfirst_value(t -> get(t, "from", nothing) == W[:q], b.project.blocks["transfers"])
    to = carrier === nothing ? nothing : get(carrier, "to", nothing)
    tgt = js_truthy(to) ? get(b.state_by_name, to, nothing) : nothing
    path = (js_truthy(to) && tgt === nothing) ? get(b.path_by_name, to, nothing) : nothing
    W.width == 0 && return nothing
    pos = isempty(Pd.dims) ? Vector{Int}[] : positions(b.space, Pd.dims)
    idx = collect(0:W.width-1)
    dest = Int[]
    if tgt !== nothing
        dest = _as_vec(state_offsets(b, Pd.dims, pos, tgt, carrier["name"], W.width), W.width)
    elseif path !== nothing
        dest = _as_vec(farf_inlet(b, Pd.dims, pos, path, carrier["name"], W.width), W.width)
    end
    bud = (b.budget !== nothing && tgt === nothing) ? budget_at(b, "out", family_of(b, Pd.dims, pos, W.width)) : Int[]
    return JumpFail(share_slot, Pd.base .+ idx, M.base .+ idx, W[:setting]["irf"].base .+ idx, dest, bud)
end

function _jumps!(b::Builder)
    b.jump_specs = JumpSpec[]
    for W in b.waste_layout
        W[:failure] == "at" || continue
        ops = JumpOp[]
        op = _fail_op(b, W, -1)
        op !== nothing && push!(ops, op)
        fa = get(W.block, "fail_at", nothing)
        push!(b.jump_specs, JumpSpec(W[:q], ops, W[:setting]["fail_at"].base, fa === nothing ? "" : js_str(fa), -1))
    end
    for D in b.disruption_layout
        ops = JumpOp[JumpCount(D[:entry].base)]
        for (k, a) in enumerate(D[:actions])
            share = D[:shares][k].base
            if a["kind"] == "fail"
                op = _fail_op(b, b.waste_by_name[a["block"]], share)
                op !== nothing && push!(ops, op)
                continue
            end
            A, B = _move_ends(b, D, a)
            A.width == 0 && continue
            pos = isempty(A.dims) ? Vector{Int}[] : positions(b.space, A.dims)
            idx = collect(0:A.width-1)
            to = B !== nothing ? B.base .+ idx : Int[]
            bud = (B === nothing && b.budget !== nothing) ? budget_at(b, "out", family_of(b, A.dims, pos, A.width)) : Int[]
            push!(ops, JumpMove(share, A.base .+ idx, to, bud))
        end
        if D[:timing] == "at"
            at = get(D.block, "at", nothing)
            push!(b.jump_specs, JumpSpec(D[:q], ops, D[:setting]["at"].base, at === nothing ? "" : js_str(at), D[:index]))
        else
            push!(b.jump_specs, JumpSpec(D[:q], ops, nothing, "", D[:index]))
        end
    end
end

# --- initial state --------------------------------------------------------------------------

function _initial_state!(b::Builder)
    space = b.space
    invariant = time_invariant_algebraic(b.algebraic, b.alg_by_name, b.state_by_name)
    used = Set{String}()
    stmts = Stmt[]
    for s in b.states
        s.kind in ("farfield", "budget", "event") && continue
        (s.kind == "waste_package" && s[:role] != "intact") && continue
        key = s.kind == "waste_package" ? "inventory" : "initial"
        parsed = Dict{String,ENode}()
        value_of = entry_lookup(s.block, key)
        for off in 0:s.width-1
            tup = pin_scenario(space, something(get(s.block, "index_lists", nothing), String[]), tuple_by_list(space, s.dims, off))
            v = value_of(tup)
            eq = js_str(v === nothing ? "0" : v)
            function resolve(name, indices, node=nothing)
                reachable(n) = haskey(b.param_by_name, n) || n in invariant
                q = resolve_reference(name, s.system, reachable)
                pr = q === nothing ? nothing : something(get(b.param_by_name, q, nothing), get(b.alg_by_name, q, nothing), Some(nothing))
                pr === nothing && throw(BuildError(why_not_initial(name, s, b.alg_by_name, b.state_by_name), s.name))
                store = haskey(b.param_by_name, q) ? :P : :X
                store === :X && push!(used, q)
                isempty(pr.dims) && return TLeaf(store, pr.base)
                here = Dict{String,Any}(COMPARTMENT_LIST => s.name)
                t = merge(Tup(COMPARTMENT_LIST => s.name), tup, pin_indices(space, pr, indices, name, s.name, here))
                st = strides(space, pr.dims)
                o = 0
                for (i, dim) in enumerate(pr.dims)
                    p = position_in(space, dim, t)
                    if p === nothing
                        msg = dim == TRANSFER_LIST ?
                              "'$name' has a value per transfer, and a compartment is not a transfer. Name one, as '$name[<transfer>]'." :
                              "'$name' is indexed by '$dim', which the initial condition of '$(s.name)' cannot resolve. Give an explicit index."
                        throw(BuildError(msg, s.name))
                    end
                    o += p * st[i]
                end
                return TLeaf(store, pr.base + o)
            end
            ast = get(parsed, eq, nothing)
            tree = try
                if ast === nothing
                    ast = parse_model_equation(b, eq, js_truthy(get(s.block, "system", nothing)) ? s.block["system"] : "", s.name)
                    parsed[eq] = ast
                end
                resolve_tree(ast, resolve)
            catch e
                e isa EquationParseError && throw(BuildError("$(e.message) in initial condition \"$eq\"", s.name))
                (e isa BuildError || e isa IndexSpaceError) && rethrow()
                e isa ArgumentError && throw(BuildError(e.msg, s.name))
                e isa ErrorException && throw(BuildError(e.msg, s.name))
                rethrow()
            end
            push!(stmts, Stmt(s.base + off, tree, 1, nothing, (0, 0); array=:y0))
        end
    end
    before = Stmt[]
    if !isempty(used)
        wanted = copy(used)
        for a in Iterators.reverse(b.algebraic)
            a.name in wanted && union!(wanted, a.reads_alg)
        end
        for a in b.algebraic
            a.name in wanted && append!(before, b.alg_stmts[a.name])
        end
    end
    b.initial_before = before
    b.initial_stmts = stmts
end

# --- small pieces ---------------------------------------------------------------------------

function _hazard_tree(failure, t::TNode, frm::TNode, to::TNode, start::TNode, rate::TNode, scale::TNode, shape::TNode)
    if failure == "uniform"
        width_ = TCall("max", TNode[TBin(:-, to, t), TBin(:*, _k(WINDOW_TAIL), TCall("abs", TNode[TBin(:-, to, frm)]))])
        return TCond(TBin(:<, t, frm), _k(0.0), TBin(:/, _k(1.0), width_))
    elseif failure == "exponential"
        return TCond(TBin(:<, t, start), _k(0.0), rate)
    elseif failure == "weibull"
        age = TCall("max", TNode[TBin(:-, t, start), TBin(:*, _k(1e-12), TCall("abs", TNode[scale]))])
        powr = TCall("power", TNode[TBin(:/, age, scale), TBin(:-, shape, _k(1.0))])
        return TCond(TBin(:<, t, start), _k(0.0), TBin(:*, TBin(:/, shape, scale), powr))
    end
    return _k(0.0)
end

function _moles_per_unit(decay_unit, lam_per_time_unit, seconds_per_time_unit)
    decay_unit == "mol" && return 1.0
    per_second = lam_per_time_unit / seconds_per_time_unit
    per_second > 0 || return 0.0
    return 1 / (per_second * AVOGADRO_AVAILABILITY)
end

function _availability_sum(terms)
    isempty(terms) && return _k(0.0)
    parts = TNode[]
    for term in terms
        read = TLeaf(:y, term.off)
        term.factor != 1 && (read = TBin(:*, _k(term.factor), read))
        if term.when !== nothing
            group_at, value = term.when
            test = TBin(:(==), KLeaf(Float64.(group_at)), _k(Float64(value)))
            read = TCond(test, read, _k(0.0))
        end
        push!(parts, read)
    end
    length(parts) == 1 && return parts[1]
    out = parts[1]
    for p in parts[2:end]
        out = TBin(:+, out, p)
    end
    return out
end

function _availability_expression(scheme, amount::TNode, ops::Dict{String,TNode})
    if scheme["scheme"] in ("limit", "shared_limit")
        body = TCond(TBin(:>, amount, _k(0.0)), TCall("min", TNode[TBin(:/, ops["limit"], amount), _k(1.0)]), _k(1.0))
    else
        a, bb = ops["top"], ops["bottom"]
        body = TCond(TBin(OP_NE, TBin(:+, amount, bb), _k(0.0)), TBin(:/, TBin(:+, amount, a), TBin(:+, amount, bb)), _k(1.0))
    end
    js_truthy(get(scheme, "unavailable", nothing)) && return TBin(:-, _k(1.0), body)
    return body
end
