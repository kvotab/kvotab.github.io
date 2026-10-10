# The far-field pathway's settings: what a path block holds, its defaults, and
# the checks a project makes of it before anything is built
# (src/domain/farfield.js). The cells, the rates and the release are in
# farfield.jl.

"""How the downstream end is closed; 4 is the rock going on past the release point."""
const OUTFLOWS = (0, 1, 2, 3, 4)
const CONTINUES = 4
const FARF_METHODS = ("discretized", "semi-analytical")
const SURFACES = ("f", "aw", "aperture")
const SURFACE_KEY = Dict("f" => "f", "aw" => "aw", "aperture" => "aperture")
const GRIDS = ("matched", "reference")
const FARF_NUCLIDE_KEYS = ("kd_f", "eps_m", "kd_m", "de_m")
const FARF_SINGLE_KEYS = ("tw", "f", "aw", "aperture", "rho_m", "pe", "pen_dep", "pen_dep_0")
const FARF_EQUATION_KEYS = ("tw", "f", "aw", "aperture", "kd_f", "kd_m", "de_m", "eps_m", "rho_m", "pe", "pen_dep",
                            "pen_dep_0")
const FARF_STRUCTURE_KEYS = ("n_f", "n_m", "o_b", "n_b")
const FARF_CHOICE_KEYS = ("surface", "grid", "method")

"""What a new path starts with (`FARF_DEFAULTS` in src/domain/farfield.js)."""
const FARF_DEFAULTS = JDict(
    "method" => "discretized",
    "tw" => "100", "surface" => "f", "f" => "1e5", "kd_f" => "0", "kd_m" => "0", "de_m" => "1e-4", "eps_m" => "0.0018",
    "rho_m" => "2700", "pe" => "10", "pen_dep" => "12.5", "pen_dep_0" => "", "n_f" => 20, "n_m" => 12,
    "o_b" => CONTINUES, "n_b" => "", "grid" => "matched", "handle_decay" => true, "report_cells" => false,
)

"""What a saved path that does not mention these meant: the reference implementation's numerics."""
const FARF_LEGACY = JDict("o_b" => 1, "n_b" => 0, "grid" => "reference", "surface" => "f",
                          "method" => "discretized", "n_m" => 20)

"""A surface setting's equation when the path gives none."""
const FARF_SURFACE_DEFAULTS = Dict("f" => "1e5", "aw" => "1000", "aperture" => "0.002")

"""The rock's settings, each zero or more."""
const ROCK_KEYS = ("kd_f", "kd_m", "de_m", "eps_m", "rho_m")
const ROCK_TERM = Dict(
    "kd_f" => "The sorption on the fracture coating K_d,f",
    "kd_m" => "The partition coefficient in the rock matrix K_d,m",
    "de_m" => "The effective diffusivity in the rock matrix D_e,m",
    "eps_m" => "The porosity of the rock matrix ε_m",
    "rho_m" => "The dry bulk density of the rock matrix ρ_m",
)

"""
    py_float(v) -> Float64

Python's `float(v)` where it succeeds, NaN where it raises: what the far-field
checks read a setting as (an empty string is NaN, not 0).
"""
py_float(v::Bool) = v ? 1.0 : 0.0
py_float(v::Real) = Float64(v)
function py_float(v::AbstractString)
    s = strip(v)
    isempty(s) && return NaN
    low = lowercase(s)
    low in ("inf", "+inf", "infinity", "+infinity") && return Inf
    low in ("-inf", "-infinity") && return -Inf
    low in ("nan", "+nan", "-nan") && return NaN
    x = tryparse(Float64, replace(s, '_' => ""))
    return x === nothing ? NaN : x
end
py_float(v) = NaN

_farf_empty(v) = v === nothing || (v isa AbstractString && isempty(strip(v)))
_is_whole(v) = (f = py_float(v); isfinite(f) && isinteger(f))

"""Whether a path is worked out on cells, which is what gives it states."""
function uses_cells(block)
    m = jget(block, "method")
    return m === nothing || m == "" || m == "discretized"
end

"""Whether a path is worked out semi-analytically."""
is_semi_analytic(block) = block isa AbstractDict && get(block, "method", nothing) == "semi-analytical"

"""How a path gives its flow-wetted surface: F unless it says otherwise."""
function surface_of(block)
    s = jget(block, "surface")
    return s in SURFACES ? String(s) : "f"
end

"""Every equation but the two ways of giving the surface the path does not use."""
function active_equation_keys(block)
    used = SURFACE_KEY[surface_of(block)]
    others = setdiff(Set(values(SURFACE_KEY)), Set([used]))
    return [k for k in FARF_EQUATION_KEYS if !(k in others)]
end

"""How many cells of rock past the release point the semi-infinite outlet needs."""
function auto_extra_cells(nf, pe)
    n = py_float(nf)
    p = py_float(pe)
    (isfinite(n) && isinteger(n)) && n >= 1 || return 0
    (p > 0 && isfinite(p)) || (p = 10.0)
    rho = (2 * n - p) / (2 * n + p)
    rho > 0 || return 0
    k = 0
    left = 1.0
    while left > 0.1 && k < 10000
        left *= rho
        k += 1
    end
    return k
end

"""The extra cells past the release point."""
function extra_cells(block)
    nb = jget(block, "n_b")
    if _farf_empty(nb)
        return py_float(jget(block, "o_b")) == CONTINUES ? auto_extra_cells(jget(block, "n_f"), jget(block, "pe")) : 0
    end
    return Int(py_float(nb))
end

"""The structure the cells are built on: the semi-infinite outlet as extra
cells closed by linear extrapolation (`effectiveStructure`)."""
function effective_structure(block)
    ob = py_float(jget(block, "o_b"))
    nf = Int(py_float(jget(block, "n_f")))
    nm = Int(py_float(jget(block, "n_m")))
    nb = extra_cells(block)
    if ob == CONTINUES
        return (n_f=nf, n_m=nm, o_b=2, n_b=nb, downstream=true)
    end
    return (n_f=nf, n_m=nm, o_b=Int(ob), n_b=nb, downstream=js_truthy(jget(block, "downstream")))
end

cell_index(k::Integer, j::Integer, nm::Integer) = k * (nm + 1) + j

"""How many cells one nuclide's path has; one for a semi-analytical path."""
function cell_count(g)
    is_semi_analytic(g) && return 1
    uses_cells(g) || return 0
    e = effective_structure(g)
    return (e.n_f + e.n_b) * (e.n_m + 1)
end

"""The cells whose inventory is the path's."""
function held_cells(block)
    is_semi_analytic(block) && return 1
    uses_cells(block) || return 0
    e = effective_structure(block)
    return (e.downstream ? e.n_f : e.n_f + e.n_b) * (e.n_m + 1)
end

"""What each cell is called: `F3` the third fracture cell, `M3_1` the first matrix layer behind it."""
function cell_names(g)
    e = effective_structure(g)
    nf, nm, nb = e.n_f, e.n_m, e.n_b
    names = fill("", (nf + nb) * (nm + 1))
    for k in 0:(nf+nb-1)
        names[cell_index(k, 0, nm)+1] = "F$(k + 1)"
        for j in 1:nm
            names[cell_index(k, j, nm)+1] = "M$(k + 1)_$(j)"
        end
    end
    return names
end

"""What is wrong with a path's cell counts and outflow condition, or `nothing`."""
function structure_problem(g)
    if is_semi_analytic(g)
        v = jget(g, "surface")
        return (v === nothing || v == "" || v in SURFACES) ? nothing : "surface must be one of $(join(SURFACES, ", "))"
    end
    function whole(key, least)
        v = jget(g, key)
        _is_whole(v) || return "$key must be a whole number"
        py_float(v) < least && return "$key must be at least $least"
        return nothing
    end
    for problem in (whole("n_f", 1), whole("n_m", 2), _farf_empty(jget(g, "n_b")) ? nothing : whole("n_b", 0))
        problem !== nothing && return problem
    end
    ob = py_float(jget(g, "o_b"))
    ob in OUTFLOWS || return "o_b must be one of $(join(OUTFLOWS, ", "))"
    for (key, allowed) in (("method", FARF_METHODS), ("grid", GRIDS), ("surface", SURFACES))
        v = jget(g, key)
        if v !== nothing && v != "" && !(v in allowed)
            return "$key must be one of $(join(allowed, ", "))"
        end
    end
    e = effective_structure(g)
    ob, nf, nb = e.o_b, e.n_f, e.n_b
    ob == 2 && nf + nb < 2 && return "a linearly extrapolated outflow needs at least two fracture cells"
    ob == 3 && nf + nb < 3 && return "a quadratically extrapolated outflow needs at least three fracture cells"
    nb == 0 && ob == 3 && nf < 3 && return "reading the release under a quadratic outflow needs three fracture cells"
    nb == 0 && ob == 2 && nf < 2 && return "reading the release under a linear outflow needs two fracture cells"
    return nothing
end

"""The penetration-depth check ahead of a run, when the depths are numbers."""
function geometry_problem(block)
    nm = py_float(jget(block, "n_m"))
    pen_dep = py_float(jget(block, "pen_dep"))
    raw_first = jget(block, "pen_dep_0")
    first = (raw_first == "" || raw_first === nothing) ? nothing : py_float(raw_first)
    if is_semi_analytic(block)
        return isfinite(pen_dep) && !(pen_dep > 0) ? "the penetration depth must be a positive length" : nothing
    end
    (!isfinite(pen_dep) || !(isfinite(nm) && isinteger(nm))) && return nothing
    pen_dep > 0 || return "the penetration depth must be a positive length"
    (first === nothing || !isfinite(first)) && return nothing
    first > 0 || return "the first matrix layer must be a positive length"
    if first * nm > pen_dep * (1 + 1e-12)
        return "$(Int(nm)) matrix layers starting at $(py_repr(first)) m cannot add up to a penetration depth of " *
               "$(py_repr(pen_dep)) m: the layers grow with depth, so the first must be smaller than " *
               "$(py_repr(pen_dep / nm)) m"
    end
    return nothing
end

"""Each rock setting written as a number is zero or more (`rockProblem`)."""
function rock_problem(block)
    holders = Any[block]
    append!(holders, something(jget(block, "entries"), Any[]))
    for holder in holders
        holder isa AbstractDict || continue
        for key in ROCK_KEYS
            v = get(holder, key, nothing)
            (v === nothing || isempty(strip(js_str(v)))) && continue
            n = py_float(v)
            (!isfinite(n) || n >= 0) && continue
            at = holder === block ? "" :
                 " at " * join((js_text(x) for x in values(something(get(holder, "index", nothing), JDict()))), ", ")
            what = ROCK_TERM[key]
            return "$(lowercase(what[1:1]))$(what[2:end]) must be zero or positive (got $(js_text(v))$at)"
        end
    end
    return nothing
end

"""Python's `repr` of a float in a message (`12.5`, `1e-05`, `100.0`)."""
function py_repr(x::Real)
    f = Float64(x)
    isnan(f) && return "nan"
    isinf(f) && return f > 0 ? "inf" : "-inf"
    f == 0 && return signbit(f) ? "-0.0" : "0.0"
    digits, n = shortest_digits(abs(f))
    sign = f < 0 ? "-" : ""
    k = length(digits)
    # Python's repr: fixed notation for 1e-4 <= |x| < 1e16, else exponential.
    e = n - 1
    if -4 <= e < 16
        if n <= 0
            return sign * "0." * "0"^(-n) * digits
        elseif n >= k
            return sign * digits * "0"^(n - k) * ".0"
        else
            return sign * digits[1:n] * "." * digits[n+1:end]
        end
    end
    mant = k == 1 ? digits : digits[1:1] * "." * digits[2:end]
    return sign * mant * "e" * (e < 0 ? "-" : "+") * lpad(string(abs(e)), 2, '0')
end
