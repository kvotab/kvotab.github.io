# df/dy for the implicit solvers: its structure, a colouring, and values
# differenced through it (engine/jacobian.py: Pattern, colour_columns,
# difference_increment, difference_jacobian, _group_entries).

const _JAC_SQRT_EPS = sqrt(2.0^-52)

"""A square sparsity pattern in compressed columns: 1-based, the rows sorted
within each column, no duplicates. `col_of[p]` is the column of entry `p`."""
struct Pattern
    n::Int
    colptr::Vector{Int}
    rowval::Vector{Int}
    col_of::Vector{Int}
end

"""The pattern of the (row, col) pairs given (1-based; duplicates allowed)."""
function Pattern(n::Integer, rows::AbstractVector{<:Integer}, cols::AbstractVector{<:Integer})
    n = Int(n)
    length(rows) == length(cols) || throw(ArgumentError("rows and cols differ in length"))
    count = zeros(Int, n + 1)
    @inbounds for q in eachindex(cols)
        c = Int(cols[q])
        r = Int(rows[q])
        (1 <= c <= n && 1 <= r <= n) || throw(ArgumentError("entry ($r, $c) is outside a $n by $n pattern"))
        count[c+1] += 1
    end
    ptr = ones(Int, n + 1)
    @inbounds for j in 1:n
        ptr[j+1] = ptr[j] + count[j+1]
    end
    next = ptr[1:n]
    raw = Vector{Int}(undef, length(rows))
    @inbounds for q in eachindex(cols)
        c = Int(cols[q])
        raw[next[c]] = Int(rows[q])
        next[c] += 1
    end
    colptr = Vector{Int}(undef, n + 1)
    rowval = Int[]
    sizehint!(rowval, length(raw))
    colptr[1] = 1
    @inbounds for j in 1:n
        seg = sort!(view(raw, ptr[j]:ptr[j+1]-1))
        last = 0
        for r in seg
            if r != last
                push!(rowval, r)
                last = r
            end
        end
        colptr[j+1] = length(rowval) + 1
    end
    col_of = Vector{Int}(undef, length(rowval))
    @inbounds for j in 1:n, p in colptr[j]:colptr[j+1]-1
        col_of[p] = j
    end
    return Pattern(n, colptr, rowval, col_of)
end

"""The number of entries of a pattern."""
pattern_nnz(p::Pattern) = length(p.rowval)

"""Groups of columns that share no row: greedy, largest degree first, ties
in column order (`colourColumns`). Columns are 1-based."""
function colour_columns(p::Pattern)::Vector{Vector{Int}}
    n = p.n
    colptr, rowval = p.colptr, p.rowval
    # For each row, the columns with an entry in it (the pattern by rows).
    rcount = zeros(Int, n + 1)
    @inbounds for r in rowval
        rcount[r+1] += 1
    end
    rowptr = ones(Int, n + 1)
    @inbounds for i in 1:n
        rowptr[i+1] = rowptr[i] + rcount[i+1]
    end
    rowcols = Vector{Int}(undef, length(rowval))
    nxt = rowptr[1:n]
    @inbounds for j in 1:n, q in colptr[j]:colptr[j+1]-1
        r = rowval[q]
        rowcols[nxt[r]] = j
        nxt[r] += 1
    end
    degree = [colptr[j+1] - colptr[j] for j in 1:n]
    order = sortperm(degree; rev=true, alg=Base.Sort.DEFAULT_STABLE)   # stable, as Array.sort is
    colour = fill(-1, n)
    used = fill(-1, n + 1)
    ncolours = 0
    @inbounds for j in order
        for k in colptr[j]:colptr[j+1]-1
            r = rowval[k]
            for q in rowptr[r]:rowptr[r+1]-1
                c = colour[rowcols[q]]
                if c >= 0
                    used[c+1] = j
                end
            end
        end
        c = 0
        while used[c+1] == j
            c += 1
        end
        colour[j] = c
        ncolours = max(ncolours, c + 1)
    end
    groups = [Int[] for _ in 1:ncolours]
    @inbounds for j in 1:n
        push!(groups[colour[j]+1], j)
    end
    return groups
end

"""sqrt(eps) times the larger of |y_j| and the threshold, rounded to what
the addition actually changed (into `dl`)."""
function difference_increment!(dl::Vector{Float64}, y::Vector{Float64}, threshold::Vector{Float64})
    @inbounds for i in eachindex(y)
        d = _JAC_SQRT_EPS * max(abs(y[i]), threshold[i])
        d = d == 0 ? _JAC_SQRT_EPS : d
        moved = (y[i] + d) - y[i]
        dl[i] = moved == 0 ? d : moved
    end
    return dl
end

difference_increment(y::Vector{Float64}, threshold::Vector{Float64}) =
    difference_increment!(similar(y), y, threshold)

"""The entries of each colour, in the pattern's order (`_group_entries`)."""
function group_entries(p::Pattern, groups::Vector{Vector{Int}})::Vector{Vector{Int}}
    colour = zeros(Int, p.n)
    for (c, g) in enumerate(groups), j in g
        colour[j] = c
    end
    out = [Int[] for _ in groups]
    @inbounds for q in eachindex(p.col_of)
        c = colour[p.col_of[q]]
        c > 0 && push!(out[c], q)
    end
    return out
end

"""`difference_jacobian(f!, t, y, f0, pattern, groups, threshold)`: the
same, into a new vector (Python's `difference_jacobian`)."""
function difference_jacobian(f!::F, t::Float64, y::Vector{Float64}, f0::Vector{Float64}, p::Pattern,
                             groups::Vector{Vector{Int}}, threshold::Vector{Float64}) where {F}
    return difference_jacobian!(zeros(pattern_nnz(p)), f!, t, y, f0, p, groups, threshold,
                                DifferenceWork(p, groups, p.n))
end

"""What differencing through a pattern needs, made once for a solve: the
groups' entries, the increments, the shifted state and the derivative at it."""
struct DifferenceWork
    entries::Vector{Vector{Int}}
    dl::Vector{Float64}
    ytry::Vector{Float64}
    fg::Vector{Float64}
end

DifferenceWork(p::Union{Nothing,Pattern}, groups::Union{Nothing,Vector{Vector{Int}}}, n::Int) =
    DifferenceWork(p === nothing || groups === nothing ? Vector{Int}[] : group_entries(p, groups),
                   zeros(n), zeros(n), zeros(n))

"""One-sided differences through the pattern, one evaluation of `f!(out, t,
y)` per colour, into the pattern's values `out` (`differenceJacobian`)."""
function difference_jacobian!(out::Vector{Float64}, f!::F, t::Float64, y::Vector{Float64}, f0::Vector{Float64},
                              p::Pattern, groups::Vector{Vector{Int}}, threshold::Vector{Float64},
                              w::DifferenceWork) where {F}
    dl = difference_increment!(w.dl, y, threshold)
    ytry = w.ytry
    copyto!(ytry, y)
    rowval, col_of = p.rowval, p.col_of
    @inbounds for (g, entries) in zip(groups, w.entries)
        for j in g
            ytry[j] = ytry[j] + dl[j]
        end
        f!(w.fg, t, ytry)
        fg = w.fg
        for q in entries
            r = rowval[q]
            out[q] = (fg[r] - f0[r]) / dl[col_of[q]]
        end
        for j in g
            ytry[j] = y[j]
        end
    end
    return out
end
