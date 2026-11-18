#include "engine/landing.hpp"

#include <algorithm>
#include <cmath>
#include <limits>

namespace kompartment {

namespace {

// Turns judged together: one maximum each, so a long step skips quiet stretches.
constexpr long LANDING_BLOCK = 32;

// The area under |table| up to s: straight lines between points, flat beyond them.
double held_by(const TableLanding::Tab& tab, double s) {
    const std::vector<double>& x = tab.x;
    const std::vector<double>& ay = tab.ay;
    std::size_t n = x.size();
    if (s <= x[0]) return (s - x[0]) * ay[0];
    if (s >= x[n - 1]) return tab.cum[n - 1] + (s - x[n - 1]) * ay[n - 1];
    // The last point at or before s, from 0, and no further than the last but one.
    std::size_t j = static_cast<std::size_t>(std::upper_bound(x.begin(), x.end(), s) - x.begin()) - 1;
    j = std::min(j, n - 2);
    double dx = x[j + 1] - x[j];
    double v = dx > 0 ? ay[j] + (ay[j + 1] - ay[j]) * ((s - x[j]) / dx) : ay[j + 1];
    return tab.cum[j] + 0.5 * (s - x[j]) * (ay[j] + v);
}

// The first turn of `tab` (from 0) a step from t to t_next covers whole and that holds more
// than rtol of what the table holds over the step; -1 for none.
long earliest_turn(const TableLanding::Tab& tab, double t, double t_next) {
    // From the first stretch that starts at or after t to the last that ends at or before t_next.
    long i0 = static_cast<long>(std::lower_bound(tab.A.begin(), tab.A.end(), t) - tab.A.begin());
    long i1 = std::max(i0, static_cast<long>(std::upper_bound(tab.B.begin(), tab.B.end(), t_next) - tab.B.begin()));
    if (i1 <= i0) return -1;
    double held = held_by(tab, t_next) - held_by(tab, t);
    long i = i0;
    while (i < i1) {
        long q = i / LANDING_BLOCK;
        long stop = std::min(i1, (q + 1) * LANDING_BLOCK);
        if (i == q * LANDING_BLOCK && stop == (q + 1) * LANDING_BLOCK && !(tab.block_max[static_cast<std::size_t>(q)] > held)) {
            i = stop;
            continue;
        }
        while (i < stop) {
            if (tab.CRIT[static_cast<std::size_t>(i)] > held) return i;
            i++;
        }
    }
    return -1;
}

}  // namespace

std::optional<TableLanding> table_landing(const std::vector<std::shared_ptr<LookupTable>>& tables, double rtol) {
    TableLanding out;
    for (const auto& table : tables) {
        const std::vector<double>& x = table->x;
        const std::vector<double>& y = table->y;
        std::size_t n = x.size();
        if (n < 3) continue;
        TableLanding::Tab tab;
        for (std::size_t i = 1; i + 1 < n; i++) {
            double y0 = y[i - 1], y1 = y[i], y2 = y[i + 1];
            if (!((y1 > y0 && y1 >= y2) || (y1 < y0 && y1 <= y2))) continue;
            double x0 = x[i - 1], x1 = x[i], x2 = x[i + 1];
            double a, b, at;
            switch (table->interpolation) {
                case Interpolation::Below: a = x1; b = x2; at = 0.5 * (x1 + x2); break;
                case Interpolation::Above: a = x0; b = x1; at = 0.5 * (x0 + x1); break;
                case Interpolation::Nearest: a = 0.5 * (x0 + x1); b = 0.5 * (x1 + x2); at = x1; break;
                default:
                    a = x0;
                    b = x2;
                    at = (x0 < x1 && x1 < x2) ? x1 : 0.5 * (x0 + x2);
            }
            if (!(b - a > 1024 * std::numeric_limits<double>::epsilon() * std::max(std::fabs(a), std::fabs(b)))) continue;
            double span = x2 - x0;
            double chord = y0 + (y2 - y0) * ((x1 - x0) / span);
            double bump = 0.5 * span * std::fabs(y1 - chord);
            if (!(bump > 0)) continue;
            tab.A.push_back(a);
            tab.B.push_back(b);
            tab.AT.push_back(at);
            tab.CRIT.push_back(bump / rtol);
        }
        long m = static_cast<long>(tab.A.size());
        if (m == 0) continue;
        tab.x = x;
        tab.ay.resize(n);
        for (std::size_t j = 0; j < n; j++) tab.ay[j] = std::fabs(y[j]);
        tab.cum.assign(n, 0.0);
        for (std::size_t j = 1; j < n; j++) tab.cum[j] = tab.cum[j - 1] + 0.5 * (x[j] - x[j - 1]) * (tab.ay[j - 1] + tab.ay[j]);
        long nb = (m + LANDING_BLOCK - 1) / LANDING_BLOCK;
        tab.block_max.assign(static_cast<std::size_t>(nb), 0.0);
        for (long q = 0; q < nb; q++) {
            double top = 0.0;
            for (long i = q * LANDING_BLOCK; i < std::min(m, (q + 1) * LANDING_BLOCK); i++)
                if (tab.CRIT[static_cast<std::size_t>(i)] > top) top = tab.CRIT[static_cast<std::size_t>(i)];
            tab.block_max[static_cast<std::size_t>(q)] = top;
        }
        out.tabs.push_back(std::move(tab));
    }
    if (out.tabs.empty()) return std::nullopt;
    return out;
}

double TableLanding::operator()(double t, double t_next) const {
    double best = std::numeric_limits<double>::quiet_NaN();
    if (!(t_next > t)) return best;
    for (const Tab& tab : tabs) {
        long i = earliest_turn(tab, t, t_next);
        if (i >= 0 && !(tab.AT[static_cast<std::size_t>(i)] >= best)) best = tab.AT[static_cast<std::size_t>(i)];
    }
    return best;
}

}  // namespace kompartment
