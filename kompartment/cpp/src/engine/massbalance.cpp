#include "engine/massbalance.hpp"

#include <algorithm>
#include <cmath>

#include "engine/farfield_domain.hpp"

namespace kompartment {

namespace {

struct Row {
    double inventory = 0, start = 0, in = 0, out = 0, decay = 0, ingrowth = 0, explicit_ = 0, between = 0, expected = 0, residual = 0;
};

Row sum(const Row& a, const Row& b) {
    return {a.inventory + b.inventory, a.start + b.start, a.in + b.in, a.out + b.out, a.decay + b.decay, a.ingrowth + b.ingrowth,
            a.explicit_ + b.explicit_, a.between + b.between, a.expected + b.expected, a.residual + b.residual};
}

Json json_of(const Row& r) {
    return Json::object({{"inventory", Json(r.inventory)}, {"start", Json(r.start)}, {"in", Json(r.in)}, {"out", Json(r.out)},
                         {"decay", Json(r.decay)}, {"ingrowth", Json(r.ingrowth)}, {"explicit", Json(r.explicit_)},
                         {"between", Json(r.between)}, {"expected", Json(r.expected)}, {"residual", Json(r.residual)}});
}

double scale_of(const Row& r, double scale) {
    return std::max({scale, std::fabs(r.inventory), std::fabs(r.start), r.in, r.out, r.decay, r.ingrowth, std::fabs(r.explicit_), std::fabs(r.between)});
}

}  // namespace

Json audit(const Budget& budget, const std::vector<double>& t, const std::vector<std::vector<double>>& y, const Json& rtol,
           const std::vector<double>& abstol, double abstol_all) {
    std::size_t n = t.size();
    std::size_t F = static_cast<std::size_t>(budget.nfam);
    std::vector<std::vector<double>> inventory(F, std::vector<double>(n, 0.0));
    for (std::size_t i = 0; i < n; i++)
        for (const auto& m : budget.members)
            for (int off = 0; off < m.width; off++)
                inventory[static_cast<std::size_t>(m.fam_of[static_cast<std::size_t>(off)])][i] += y[i][static_cast<std::size_t>(m.base + off)];
    auto term = [&](std::size_t i, int which, std::size_t f) { return y[i][static_cast<std::size_t>(budget.base + which * budget.nfam) + f]; };
    auto row_at = [&](std::size_t i, std::size_t f) {
        Row r;
        r.inventory = inventory[f][i];
        r.start = inventory[f][0];
        r.in = term(i, 0, f);
        r.out = term(i, 1, f);
        r.decay = term(i, 2, f);
        r.ingrowth = term(i, 3, f);
        r.explicit_ = term(i, 4, f);
        r.between = term(i, 5, f);
        r.expected = r.start + r.in - r.out - r.decay + r.ingrowth + r.explicit_ + r.between;
        r.residual = r.inventory - r.expected;
        return r;
    };
    auto floor_of = [&](std::size_t f) {
        if (abstol.empty()) return std::isfinite(abstol_all) && abstol_all > 0 ? abstol_all : 0.0;
        double most = 0.0;
        for (const auto& m : budget.members)
            for (int off = 0; off < m.width; off++) {
                double v = abstol[static_cast<std::size_t>(m.base + off)];
                if (static_cast<std::size_t>(m.fam_of[static_cast<std::size_t>(off)]) == f && std::isfinite(v) && v > most) most = v;
            }
        return most;
    };
    double r = rtol.is_null() ? std::nan("") : value_number(rtol);
    double tolerance = std::max(1e-10, 20 * (std::isfinite(r) && r > 0 ? r : 1e-6));
    Json families = Json::array();
    std::vector<Row> totals(n);
    std::vector<char> has_total(n, 0);
    const Json* worst_family = nullptr;
    std::vector<Json> family_rows;
    for (std::size_t f = 0; f < F; f++) {
        double worst = 0.0, at = n ? t[0] : 0.0, scale = 0.0;
        Row last;
        for (std::size_t i = 0; i < n; i++) {
            Row row = row_at(i, f);
            scale = scale_of(row, scale);
            if (std::fabs(row.residual) > worst) {
                worst = std::fabs(row.residual);
                at = t[i];
            }
            last = row;
            totals[i] = has_total[i] ? sum(totals[i], row) : row;
            has_total[i] = 1;
        }
        double floor = floor_of(f);
        bool idle = scale == 0 || scale <= floor;
        family_rows.push_back(Json::object({{"name", Json(budget.families[f])}, {"idle", Json(idle)}, {"unresolved", Json(idle && scale > 0)},
                                            {"floor", Json(floor)}, {"scale", Json(scale)}, {"worst", Json(idle ? 0.0 : worst)},
                                            {"relative", Json(idle ? 0.0 : worst / scale)}, {"at", Json(at)}, {"final", n ? json_of(last) : Json()}}));
    }
    for (const Json& f : family_rows) families.push(f);
    double tscale = 0.0, tworst = 0.0, tat = n ? t[0] : 0.0;
    Json tfinal;
    for (std::size_t i = 0; i < n; i++) {
        if (!has_total[i]) continue;
        tscale = scale_of(totals[i], tscale);
        if (std::fabs(totals[i].residual) > tworst) {
            tworst = std::fabs(totals[i].residual);
            tat = t[i];
        }
        tfinal = json_of(totals[i]);
    }
    for (const Json& f : families.arr()) {
        if (f.get("idle").as_bool()) continue;
        if (f.get("relative").as_double() > (worst_family ? worst_family->get("relative").as_double() : -1.0)) worst_family = &f;
    }
    double worst_rel = worst_family ? worst_family->get("relative").as_double() : 0.0;
    return Json::object({
        {"worst", Json(worst_rel)},
        {"at", worst_family ? worst_family->get("at") : Json(n ? t[0] : 0.0)},
        {"worstFamily", worst_family ? worst_family->get("name") : Json()},
        {"closed", Json(worst_rel <= tolerance)},
        {"tolerance", Json(tolerance)},
        {"families", families},
        {"total", Json::object({{"scale", Json(tscale)}, {"worst", Json(tworst)}, {"relative", Json(tscale > 0 ? tworst / tscale : 0.0)},
                                {"at", Json(tat)}, {"final", tfinal}})},
    });
}

}  // namespace kompartment
