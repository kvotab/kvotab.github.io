# The mass-balance audit (src/domain/massbalance.js). With `mass_balance` on,
# the run carries one budget state per family (each radionuclide, and one for
# what is not indexed by any) per kind of movement; the audit checks that
# what each family holds equals what it started with plus what came in, less
# what went out and decayed, plus what grew in.

budget_index(budget, term, family) = budget.base + (findfirst(==(term), BUDGET_TERMS) - 1) * budget.nfam + family

closed_below(rtol) = (r = py_float(something(rtol, NaN)); max(1e-10, 20 * (isfinite(r) && r > 0 ? r : 1e-6)))

const _AUDIT_KEYS = ("inventory", "start", "in", "out", "decay", "ingrowth", "explicit", "between", "expected", "residual")

"""The closure, family by family and in total (`audit`)."""
function audit(budget, t::Vector{Float64}, y::Vector{Vector{Float64}}; rtol=nothing, abstol=nothing)
    n = length(t)
    F = budget.nfam
    inventory = zeros(F, n)
    for i in 1:n
        yi = y[i]
        for m in budget.members, off in 0:m.width-1
            inventory[m.fam_of[off+1]+1, i] += yi[m.base+off+1]
        end
    end
    function row_at(i, f)
        term(name) = y[i][budget_index(budget, name, f)+1]
        row = OrderedDict{String,Float64}("inventory" => inventory[f+1, i], "start" => inventory[f+1, 1], "in" => term("in"),
                                          "out" => term("out"), "decay" => term("decay"), "ingrowth" => term("ingrowth"),
                                          "explicit" => term("explicit"), "between" => term("between"))
        row["expected"] = row["start"] + row["in"] - row["out"] - row["decay"] + row["ingrowth"] + row["explicit"] +
                          row["between"]
        row["residual"] = row["inventory"] - row["expected"]
        return row
    end
    add_rows(a, b) = OrderedDict{String,Float64}(k => a[k] + b[k] for k in keys(a))
    scale_of(row, scale) = max(scale, abs(row["inventory"]), abs(row["start"]), row["in"], row["out"], row["decay"],
                               row["ingrowth"], abs(row["explicit"]), abs(row["between"]))
    function floor_of(f)
        abstol === nothing && return 0.0
        if abstol isa Real
            a = Float64(abstol)
            return isfinite(a) && a > 0 ? a : 0.0
        end
        most = 0.0
        for m in budget.members, off in 0:m.width-1
            v = abstol[m.base+off+1]
            (m.fam_of[off+1] == f && isfinite(v) && v > most) && (most = v)
        end
        return most
    end
    families = Any[]
    totals = Vector{Any}(nothing, n)
    for f in 0:F-1
        worst = 0.0
        at = t[1]
        scale = 0.0
        last = nothing
        for i in 1:n
            row = row_at(i, f)
            scale = scale_of(row, scale)
            if abs(row["residual"]) > worst
                worst = abs(row["residual"])
                at = t[i]
            end
            last = row
            totals[i] = totals[i] === nothing ? row : add_rows(totals[i], row)
        end
        floor = floor_of(f)
        idle = scale == 0 || scale <= floor
        push!(families, (name=budget.families[f+1], idle=idle, unresolved=idle && scale > 0, floor=floor, scale=scale,
                         worst=idle ? 0.0 : worst, relative=idle ? 0.0 : worst / scale, at=at, final=last))
    end
    tscale, tworst, tat, tfinal = 0.0, 0.0, n > 0 ? t[1] : 0.0, nothing
    for i in 1:n
        row = totals[i]
        row === nothing && continue
        tscale = scale_of(row, tscale)
        if abs(row["residual"]) > tworst
            tworst = abs(row["residual"])
            tat = t[i]
        end
        tfinal = row
    end
    total = (scale=tscale, worst=tworst, relative=tscale > 0 ? tworst / tscale : 0.0, at=tat, final=tfinal)
    worst_family = nothing
    for f in families
        f.idle && continue
        if f.relative > (worst_family === nothing ? -1 : worst_family.relative)
            worst_family = f
        end
    end
    worst_rel = worst_family === nothing ? 0.0 : worst_family.relative
    return (worst=worst_rel, at=worst_family === nothing ? (n > 0 ? t[1] : 0.0) : worst_family.at,
            worst_family=worst_family === nothing ? nothing : worst_family.name,
            closed=worst_rel <= closed_below(rtol), tolerance=closed_below(rtol), families=families, total=total)
end
