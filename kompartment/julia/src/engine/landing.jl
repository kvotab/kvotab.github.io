# Where a step has to end so as not to pass over a pulse in a table
# (`src/sim/landing.js` in the application, `kompartment/engine/landing.py` in
# Python, number for number).
#
# A solver looks at the derivative at the ends of its steps and at its stages
# inside them, and nowhere else. A table read at the clock that rises and falls
# back between two of those places is never seen, and what it would have put
# into the model is lost: a pulse after a time of none arrives as nothing, a
# spike on a steady release as the steady release alone.
#
# So each turn of each such table -- a point higher than both its neighbours, or
# lower -- is a place a step may not cover whole when the turn matters: when the
# area it adds to the straight line between its neighbours is more than rtol of
# what the table holds over that step. Such a step ends at the turn instead. A
# turn is judged over the stretch a step would have to cover to miss it, by the
# interpolation rule, and the step ends inside that stretch, never on a jump.
# Tables read at an expression, and cyclic ones, are left out.

"""Turns judged together: one maximum each, so a long step skips quiet stretches."""
const LANDING_BLOCK = 32

struct LandingTab
    x::Vector{Float64}
    ay::Vector{Float64}
    cum::Vector{Float64}
    A::Vector{Float64}      # where the stretch of each turn starts
    B::Vector{Float64}      # ... and ends
    AT::Vector{Float64}     # the time inside it a step ends on
    CRIT::Vector{Float64}   # the area the turn adds, over rtol
    block_max::Vector{Float64}
end

"""
`landing(t, t_next)`: where a step from t to t_next is to end instead, or NaN
(`tableLanding`). Made by [`table_landing`](@ref).
"""
struct TableLanding
    tabs::Vector{LandingTab}
end

"""
The rule for `tables` (each with `x`, `y` and `interpolation`), or `nothing`
when none of them turns (`tableLanding`).
"""
function table_landing(tables, rtol::Float64)::Union{Nothing,TableLanding}
    tabs = LandingTab[]
    for table in tables
        x = Vector{Float64}(table.x)
        y = Vector{Float64}(table.y)
        n = length(x)
        n < 3 && continue
        rule = Symbol(table.interpolation)
        A = Float64[]
        B = Float64[]
        AT = Float64[]
        CRIT = Float64[]
        for i in 2:n-1
            y0 = y[i-1]
            y1 = y[i]
            y2 = y[i+1]
            ((y1 > y0 && y1 >= y2) || (y1 < y0 && y1 <= y2)) || continue
            x0 = x[i-1]
            x1 = x[i]
            x2 = x[i+1]
            if rule === :below
                a, b, at = x1, x2, 0.5 * (x1 + x2)
            elseif rule === :above
                a, b, at = x0, x1, 0.5 * (x0 + x1)
            elseif rule === :nearest
                a, b, at = 0.5 * (x0 + x1), 0.5 * (x1 + x2), x1
            else
                a, b = x0, x2
                at = (x0 < x1 && x1 < x2) ? x1 : 0.5 * (x0 + x2)
            end
            (b - a > 1024 * eps(1.0) * max(abs(a), abs(b))) || continue
            span = x2 - x0
            chord = y0 + (y2 - y0) * ((x1 - x0) / span)
            bump = 0.5 * span * abs(y1 - chord)
            bump > 0 || continue
            push!(A, a)
            push!(B, b)
            push!(AT, at)
            push!(CRIT, bump / rtol)
        end
        m = length(A)
        m == 0 && continue
        ay = abs.(y)
        cum = zeros(n)
        for j in 2:n
            cum[j] = cum[j-1] + 0.5 * (x[j] - x[j-1]) * (ay[j-1] + ay[j])
        end
        nb = cld(m, LANDING_BLOCK)
        block_max = zeros(nb)
        for q in 0:nb-1
            top = 0.0
            for i in q*LANDING_BLOCK:min(m, (q + 1) * LANDING_BLOCK)-1
                if CRIT[i+1] > top
                    top = CRIT[i+1]
                end
            end
            block_max[q+1] = top
        end
        push!(tabs, LandingTab(x, ay, cum, A, B, AT, CRIT, block_max))
    end
    return isempty(tabs) ? nothing : TableLanding(tabs)
end

"""The area under |table| up to s: straight lines between points, flat beyond them."""
function _held_by(tab::LandingTab, s::Float64)::Float64
    x = tab.x
    ay = tab.ay
    n = length(x)
    s <= x[1] && return (s - x[1]) * ay[1]
    s >= x[n] && return tab.cum[n] + (s - x[n]) * ay[n]
    j = min(searchsortedlast(x, s), n - 1)
    dx = x[j+1] - x[j]
    v = dx > 0 ? ay[j] + (ay[j+1] - ay[j]) * ((s - x[j]) / dx) : ay[j+1]
    return tab.cum[j] + 0.5 * (s - x[j]) * (ay[j] + v)
end

"""
The first turn of `tab` (1-based) a step from t to t_next covers whole and that
holds more than rtol of what the table holds over the step; 0 for none.
"""
function _earliest_turn(tab::LandingTab, t::Float64, t_next::Float64)::Int
    # 0-based, as the other two engines count, from the first stretch that
    # starts at or after t to the last that ends at or before t_next
    i0 = searchsortedfirst(tab.A, t) - 1
    i1 = max(i0, searchsortedlast(tab.B, t_next))
    i1 <= i0 && return 0
    held = _held_by(tab, t_next) - _held_by(tab, t)
    i = i0
    while i < i1
        q = i ÷ LANDING_BLOCK
        stop = min(i1, (q + 1) * LANDING_BLOCK)
        if i == q * LANDING_BLOCK && stop == (q + 1) * LANDING_BLOCK && !(tab.block_max[q+1] > held)
            i = stop
            continue
        end
        while i < stop
            tab.CRIT[i+1] > held && return i + 1
            i += 1
        end
    end
    return 0
end

function (L::TableLanding)(t::Float64, t_next::Float64)::Float64
    best = NaN
    t_next > t || return best
    for tab in L.tabs
        i = _earliest_turn(tab, t, t_next)
        if i > 0 && !(tab.AT[i] >= best)
            best = tab.AT[i]
        end
    end
    return best
end
