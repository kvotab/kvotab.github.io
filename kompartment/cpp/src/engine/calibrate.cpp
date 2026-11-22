// Calibration (see calibrate.hpp): a port of the Julia package's engine/calibrate.jl,
// operation for operation.

#include "engine/calibrate.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <string>
#include <unordered_map>
#include <utility>

#include "engine/builder.hpp"
#include "engine/localsens.hpp"
#include "engine/system.hpp"
#include "stats/gsa_design.hpp"
#include "stats/optimise.hpp"
#include "stats/pdf.hpp"
#include "stats/precision.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();
constexpr double Inf = std::numeric_limits<double>::infinity();

/// Julia's `time()`, for how long a calibration took.
double now_s() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

/// Whether `got` meets `want` to 1% (0 to 1e-12), both being numbers (`_cb_within`).
bool within(double want, double got) {
    return (std::isfinite(got) && std::isfinite(want)) && (want == 0 ? std::fabs(got) < 1e-12 : std::fabs((got - want) / want) < 0.01);
}

/// One variable of the search: its slot, its space, its bounds and start in that space.
struct Variable {
    std::string key;
    std::size_t slot = 0;
    OptimiseSpace space = OptimiseSpace::Linear;
    double lower = 0.0, upper = 0.0, start = 0.0;
};

/// How far each value is moved to difference the residuals for the precision: a thousandth --
/// of the value itself where it is searched as it is, of its logarithm's unit where it is
/// searched in the logarithm -- and never more than a quarter of the range.
constexpr double PRECISION_STEP = 1e-3;

bool all_finite(const std::vector<double>& v) {
    for (double x : v)
        if (!std::isfinite(x)) return false;
    return true;
}

}  // namespace

double reading_of(Results& res, const Json& target) {
    const Json* want_label = pd_prop(target, "output");
    if (!(want_label && want_label->is_string())) return NaN;
    const std::string& want = want_label->as_string();
    const Json* o = nullptr;
    for (const Json& x : res.outputs()) {
        const Json& label = x.get("label");
        if (label.is_null() ? want.empty() : (label.is_string() && label.as_string() == want)) {
            o = &x;
            break;
        }
    }
    if (o == nullptr) return NaN;
    const std::vector<double> v = res.series_many({*o})[0];
    const std::vector<double>& t = res.t;
    if (v.empty()) return NaN;
    const Json* when = pd_prop(target, "when");
    if (when && *when == "peak") {
        double best = -Inf;
        for (double x : v)
            if (x > best) best = x;
        return best;
    }
    if (when && *when == "end") return v.back();
    const double at_time = pd_to_number(pd_prop(target, "time"));
    std::size_t at = 0;
    double gap = Inf;
    for (std::size_t i = 0; i < t.size(); i++) {
        const double d = std::fabs(t[i] - at_time);
        if (d < gap) {
            gap = d;
            at = i;
        }
    }
    return v[at];
}

std::vector<Json> variables_of(std::shared_ptr<const Project> project) {
    const System sys(project);
    std::vector<Json> out;
    for (const Json& e : parameter_slots(sys)) {
        const Json& unit = e.get("unit");
        out.push_back(Json::object({{"key", Json(slot_label(e))},
                                    {"name", e.get("name")},
                                    {"index", e.get("index")},
                                    {"slot", e.get("slot")},
                                    {"value", e.get("value")},
                                    {"unit", unit.is_null() ? Json("") : unit}}));
    }
    return out;
}

Json calibrate(std::shared_ptr<const Project> project, const CalibrateOptions& o) {
    const double started = now_s();
    std::vector<Json> targets;
    if (!o.targets.is_null())
        for (const Json& t : optimise_items(o.targets))
            if (pd_truthy(t) && pd_truthy(pd_prop(t, "output"))) targets.push_back(t);
    if (targets.empty()) throw OptimiseError("No endpoint has been given a target value.");
    const std::vector<Json> wanted = o.variables.is_null() ? std::vector<Json>{} : optimise_items(o.variables);
    if (wanted.empty()) throw OptimiseError("No parameter has been allowed to vary.");

    auto sys = std::make_shared<System>(project);
    // A label two slots share is the later one's, as a dictionary set in turn keeps it.
    std::unordered_map<std::string, Json> by_label;
    for (const Json& e : parameter_slots(*sys)) by_label[slot_label(e)] = e;
    std::vector<Variable> vars;
    for (const Json& v : wanted) {
        const Json* key = pd_prop(v, "key");
        const Json* found = nullptr;
        if (key && key->is_string()) {
            auto it = by_label.find(key->as_string());
            if (it != by_label.end()) found = &it->second;
        }
        if (found == nullptr) throw OptimiseError("'" + pd_js_str(key) + "' is not a parameter of this model.");
        const OptimiseSpace space = optimise_space(pd_prop(v, "space")).value_or(OptimiseSpace::Linear);
        const double lo = pd_to_number(pd_prop(v, "lower"));
        const double hi = pd_to_number(pd_prop(v, "upper"));
        if (!(hi > lo))
            throw OptimiseError("'" + pd_js_str(key) + "' has no range: " + pd_js_number_str(lo) + " to " + pd_js_number_str(hi) + ".");
        // A range that does not end gives a search no size to start from.
        if (!std::isfinite(lo) || !std::isfinite(hi))
            throw OptimiseError("'" + pd_js_str(key) + "' needs finite bounds: " + pd_js_number_str(lo) + " to " + pd_js_number_str(hi) + ".");
        if (!space_ok(space, lo, hi))
            throw OptimiseError("'" + pd_js_str(key) + "' is searched in the logarithm, so both bounds have to be above zero.");
        const double s = pd_to_number(pd_prop(v, "start"));
        const double at0 = std::isfinite(s) ? s : found->get("value").as_double();
        Variable var;
        var.key = key->as_string();
        var.slot = static_cast<std::size_t>(found->get("slot").as_int());
        var.space = space;
        var.lower = space_to(space, lo);
        var.upper = space_to(space, hi);
        var.start = space_to(space, pd_jmin(hi, pd_jmax(lo, std::isfinite(at0) ? at0 : lo)));
        vars.push_back(std::move(var));
    }

    std::vector<double>& P = sys->P;
    // What the model held before any of this, so it can be put back.
    std::vector<double> before;
    for (const Variable& v : vars) before.push_back(P[v.slot]);
    std::optional<std::vector<double>> last;
    // The series a run of this system reports, described at the first run that finishes and
    // handed to every later one (they never change with the parameters' values).
    std::shared_ptr<const OutputIndex> outs;
    // A run is not stopped part way: the search stops between evaluations.
    auto evaluate = [&](const std::vector<double>& x) {
        for (std::size_t i = 0; i < vars.size(); i++) P[vars[i].slot] = space_from(vars[i].space, x[i]);
        sys->evaluate_invariant();
        try {
            RunOptions run;
            run.on_grid = true;
            Results res = run_project(project, sys, run);
            if (!outs) outs = index_outputs(outputs_of(*sys, *project));
            res.share_outputs(outs);
            std::vector<double> readings;
            readings.reserve(targets.size());
            for (const Json& t : targets) readings.push_back(reading_of(res, t));
            last = std::move(readings);
        } catch (const NotSupported&) {
            // What this engine does not have is no fact about the model: the calibration is
            // to be done where it can be (the Julia package, with nothing of the kind,
            // reads every error here as a corner the solver cannot carry).
            throw;
        } catch (...) {
            // A corner the solver cannot carry is a fact about the model.
            last = std::vector<double>(targets.size(), NaN);
        }
        return objective_of(*last, targets);
    };
    OptimiseContext ctx;
    for (const Variable& v : vars) ctx.start.push_back(v.start);
    ctx.objective = [&](const std::vector<double>& x) { return evaluate(x).objective; };
    ctx.residuals = [&](const std::vector<double>& x) { return evaluate(x).residuals; };
    const OptimiseMethod method = optimise_method(&o.method).value_or(OptimiseMethod::Nelder);
    OptimiseOptions opts;
    std::vector<double> lowers, uppers;
    for (const Variable& v : vars) {
        lowers.push_back(v.lower);
        uppers.push_back(v.upper);
    }
    opts.lower = Json::array(lowers);
    opts.upper = Json::array(uppers);
    const double budget = o.max_evals.is_null() ? 300.0 : pd_to_number(o.max_evals);
    opts.max_evals = Json(pd_jmax(10.0, gsa_round(budget)));
    opts.seed = o.seed.is_null() ? Json(1) : o.seed;
    opts.signal = o.signal;
    if (o.on_progress)
        opts.on_step = [&](const OptimiseStep& p) {
            CalibrateStep step;
            step.evals = p.evals;
            step.fx = p.fx;
            step.best = p.best;
            // In the values a reader knows, not in the search space.
            if (p.best_x) {
                std::vector<double> values;
                for (std::size_t i = 0; i < vars.size(); i++) values.push_back(space_from(vars[i].space, (*p.best_x)[i]));
                step.values = std::move(values);
            }
            o.on_progress(step);
        };
    const OptimiseResult out = run_optimise_method(method, ctx, opts);

    // The best point, read once more so the readings reported are the ones that belong to
    // the values reported.
    std::optional<std::vector<double>> readings;
    double objective = out.fx;
    std::vector<double> residuals;
    if (out.x) {
        const Objective got = evaluate(*out.x);
        readings = last;
        objective = got.objective;
        residuals = got.residuals;
    }
    // A stop asked for, as the Julia package's `_op_aborted` asks it.
    auto stopped = [&] { return o.signal ? o.signal() : false; };

    // The values at a point of the search, as the model holds them, and which sit on a bound.
    Json values = Json::array();
    if (out.x) {
        for (std::size_t i = 0; i < vars.size(); i++) {
            const Variable& v = vars[i];
            // Within a thousandth of the range searched, in the space it was searched in, is
            // *on* a bound -- the same rule at every bound, 0 included.
            const double reach = std::fabs(v.upper - v.lower) * 1e-3;
            const double u = (*out.x)[i];
            const Json pinned = std::fabs(u - v.lower) <= reach ? Json("lower") : std::fabs(u - v.upper) <= reach ? Json("upper") : Json();
            values.push(Json::object({{"key", Json(v.key)},
                                      {"was", Json(before[i])},
                                      {"value", Json(space_from(v.space, u))},
                                      {"lower", Json(space_from(v.space, v.lower))},
                                      {"upper", Json(space_from(v.space, v.upper))},
                                      {"pinned", pinned}}));
        }
    }

    // The precision of the values found: the residuals differenced along each value about the
    // answer -- central where both sides are inside the bounds, one-sided against a bound --
    // and `precision_of` on what that gives. A value on a bound is held; one the model would
    // not run around is said so. Null when the signal stops it part way.
    auto precision_around = [&](const std::vector<double>& x) -> Json {
        PrecisionInput in;
        in.residuals = residuals;
        long long runs = 0;
        auto at = [&](std::size_t k, double u) -> std::optional<std::vector<double>> {
            std::vector<double> xp = x;
            xp[k] = u;
            runs++;
            Objective got = evaluate(xp);
            if (!all_finite(*last)) return std::nullopt;
            return std::move(got.residuals);
        };
        for (std::size_t k = 0; k < vars.size(); k++) {
            if (stopped()) return Json();
            const Variable& v = vars[k];
            if (!values[k].get("pinned").is_null()) {
                in.columns.emplace_back(std::nullopt);
                in.failed.emplace_back(std::nullopt);
                continue;
            }
            const double span = v.upper - v.lower;
            const double own = v.space == OptimiseSpace::Log ? 1.0 : std::fabs(x[k]);
            const double h = std::min(span / 4, PRECISION_STEP * (own > 0 ? own : span));
            const bool up = x[k] + h <= v.upper;
            const bool down = x[k] - h >= v.lower;
            std::optional<std::vector<double>> col;
            if (h > 0 && up && down) {
                const auto p = at(k, x[k] + h);
                const auto q = p ? at(k, x[k] - h) : std::nullopt;
                if (p && q) {
                    std::vector<double> c;
                    for (std::size_t i = 0; i < p->size(); i++) c.push_back(((*p)[i] - (*q)[i]) / (2 * h));
                    col = std::move(c);
                }
            } else if (h > 0 && (up || down)) {
                const double step = up ? h : -h;
                const auto p = at(k, x[k] + step);
                if (p) {
                    std::vector<double> c;
                    for (std::size_t i = 0; i < p->size(); i++) c.push_back(((*p)[i] - residuals[i]) / step);
                    col = std::move(c);
                }
            }
            in.failed.push_back(col ? std::nullopt : std::optional<std::string>("did not run"));
            in.columns.push_back(std::move(col));
        }
        for (std::size_t k = 0; k < vars.size(); k++) {
            in.keys.push_back(vars[k].key);
            in.log.push_back(vars[k].space == OptimiseSpace::Log);
            in.values.push_back(values[k].get("value").as_double());
            const Json& pinned = values[k].get("pinned");
            in.pinned.push_back(pinned.is_null() ? std::nullopt : std::optional<std::string>(pinned.as_string()));
        }
        Json found = precision_of(in);
        found.set("runs", Json(runs));
        return found;
    };
    // How well they are known: after the search, so nothing the search decided depends on it
    // and its count of evaluations is its own. Not for a search that was stopped -- a stop is
    // a stop -- nor one the model could not finish at its best point.
    Json precision;
    if (out.x && o.precision && out.reason != "stopped" && !stopped() && all_finite(*readings)) precision = precision_around(*out.x);
    for (std::size_t i = 0; i < vars.size(); i++) P[vars[i].slot] = before[i];
    sys->evaluate_invariant();

    bool matched = readings.has_value();
    for (std::size_t i = 0; matched && i < targets.size(); i++) matched = within(pd_to_number(pd_prop(targets[i], "value")), (*readings)[i]);
    Json said = Json::array();
    for (std::size_t i = 0; i < targets.size(); i++) {
        const Json& t = targets[i];
        const Json* scale = pd_prop(t, "scale");
        said.push(Json::object({{"output", *pd_prop(t, "output")},
                                {"want", Json(pd_to_number(pd_prop(t, "value")))},
                                {"got", Json(readings ? (*readings)[i] : NaN)},
                                {"scale", pd_nullish(scale) ? Json("relative") : *scale}}));
    }
    return Json::object({{"ok", Json(out.x.has_value() && std::isfinite(objective))},
                         {"matched", Json(matched)},
                         {"method", o.method.is_null() ? Json("nelder") : o.method},
                         {"reason", Json(out.reason)},
                         {"evals", Json(out.evals)},
                         {"ms", Json(static_cast<long long>(std::nearbyint(1000 * (now_s() - started))))},
                         {"objective", Json(objective)},
                         {"values", values},
                         {"precision", precision},
                         {"targets", said}});
}

}  // namespace kompartment
