#include "solvers/solverset.hpp"

#include <cmath>
#include <stdexcept>
#include <utility>

#include "util/jsnum.hpp"

namespace kompartment {

const Hints& solver_hints() {
    static const Hints hints{
        {"singular", "A compartment with no way in and no way out will do this."},
        {"noPattern", "Give the model an analytic Jacobian, or run fewer states."},
    };
    return hints;
}

namespace {

SolverError non_finite_error(double at) {
    return SolverError("nonfinite",
                       "The simulation produced a value that is not a number at t=" + py_repr(at) +
                           ". An equation divides by zero, takes the log of zero or a negative, or overflows; the "
                           "state or rate that went first is where to look.",
                       at);
}

SolverError failure_of(const SolverError& e, double t0) {
    const double at = std::isnan(e.t) ? t0 : e.t;
    if (e.kind == "stalled" || e.kind == "steps") {
        return SolverError(e.kind,
                           e.message +
                               " Something is holding a state where it cannot go: most often a compartment kept at "
                               "zero by \"cannot go negative\" while its equations push it below. Turn that setting "
                               "off on the compartment to see what the model really does.",
                           at);
    }
    if (e.kind == "nonfinite") return non_finite_error(at);
    if (e.kind == "singular" || e.kind == "jacobian") return SolverError(e.kind, e.message, at);
    return SolverError(e.kind,
                       "variableOrder failed: " + e.message +
                           ". If the model is not stiff, dormandPrince may do better; if it is very stiff, try "
                           "tightening the tolerances.",
                       at);
}

}  // namespace

SolverError variable_order_failure(const SolverError& e, double t0) {
    if (e.kind == "aborted" || e.kind == "span") return e;
    SolverError failure = failure_of(e, t0);
    if (!e.last_y.empty()) {
        failure.last_t = e.last_t;
        failure.last_y = e.last_y;
    }
    return failure;
}

Solution variable_order(const RhsFunction& f, const Vec& tspan, const Vec& y0, const SolverOptions& o) {
    if (tspan.empty()) throw std::invalid_argument("the time span is empty");
    const double t0 = tspan.front();
    const double t_final = tspan.back();
    if (!(std::fabs(t_final - t0) > 0)) throw SolverError("span", "Simulation start and end time are equal", t0);
    NdfOptions n;
    for (std::size_t i = 0; i < o.non_negative.size(); i++)
        if (o.non_negative[i] != 0) n.non_negative.push_back(static_cast<I32>(i));
    double span = std::fabs(t_final - t0);
    span = span != 0 ? span : 1.0;
    long long counter = 0;
    double last_progress = 0.0;
    RhsFunction fun;
    if (!o.on_step) {
        fun = [&counter, &f](Vec& dy, double t, const Vec& y) {
            counter += 1;
            f(dy, t, y);
        };
    } else {
        const RunProgress& on_step = o.on_step;
        fun = [&counter, &last_progress, &f, &on_step, t0, span](Vec& dy, double t, const Vec& y) {
            counter += 1;
            f(dy, t, y);
            if ((counter & 63) == 0) {
                const double progress = sv::py_min(1.0, std::fabs(t - t0) / span);
                if (progress > last_progress) {
                    last_progress = progress;
                    if (!on_step(progress, static_cast<long>(counter), t)) {
                        throw SolverError("aborted", "Simulation aborted", t);
                    }
                }
            }
        };
    }
    n.rtol = sv::opt_or(o.rtol, 1e-3);
    n.abstol = o.abstol;
    n.abstol_vector = o.abstol_vector;
    n.hmax = sv::opt_or(o.hmax, 0.0);
    n.h0 = sv::opt_or(o.h0, 0.0);
    n.max_order = sv::opt_or(o.max_order, 5);
    n.jacobian = o.jacobian;
    n.bdf = o.bdf;
    n.hints = &solver_hints();
    n.norm_control = o.norm_control;
    n.auto_abstol = o.auto_abstol;
    n.ends_only = o.ends_only;
    n.events = o.events;
    n.on_accepted = o.on_accepted;
    n.on_output = o.on_output;
    n.max_steps = sv::opt_or(o.max_steps, 1e6);
    n.stagnation_tol = (o.stagnation_tol && *o.stagnation_tol > 0) ? *o.stagnation_tol : 0.0;
    n.error_norm = o.error_norm.empty() ? std::string("max") : o.error_norm;
    n.matrix = o.matrix.empty() ? std::string("auto") : o.matrix;
    n.below_tol_run = o.below_tol_run;
    n.rows = o.rows;
    n.landing = o.landing;
    n.weight_floor = o.weight_floor;
    n.iteration_matrix = o.iteration_matrix;
    Solution result;
    try {
        result = ndf(fun, tspan, y0, n);
    } catch (const SolverError& e) {
        if (e.kind == "aborted" || e.kind == "span") throw;
        throw variable_order_failure(e, t0);
    }
    if (result.t.empty() || result.y.empty()) {
        throw SolverError("output", "the variable-order solver produced no output", t0);
    }
    const Json& s = result.stats;
    Json stats = Json::object();
    stats.set("nsteps", s.get("nsteps"));
    stats.set("nfailed", s.get("nfailed"));
    stats.set("nfevals", Json(counter));
    stats.set("npds", s.get("npds"));
    stats.set("ndecomps", s.get("ndecomps"));
    stats.set("nsolves", s.get("nsolves"));
    stats.set("nbelowtol", s.get("nbelowtol"));
    stats.set("sparse", s.get("sparse", Json(false)));
    stats.set("fill", s.get("fill"));
    stats.set("negative", s.get("negative", Json(0)));
    stats.set("held", s.get("held"));
    stats.set("points", Json(static_cast<long long>(result.t.size())));
    stats.set("solver", Json(o.bdf ? "bdf" : "ndf"));
    result.stats = std::move(stats);
    return result;
}

SolverFunction solver_by_id(const std::string& id) {
    if (id == "ndf") return &variable_order;
    if (id == "ros23") return &rosenbrock23;
    if (id == "dp45") return &dormand_prince;
    return nullptr;
}

Solution solve(const std::string& id, const RhsFunction& f, const Vec& tspan, const Vec& y0,
               const SolverOptions& options) {
    const SolverFunction solver = solver_by_id(id);
    if (solver == nullptr) throw std::invalid_argument("there is no solver \"" + id + "\"");
    return solver(f, tspan, y0, options);
}

}  // namespace kompartment
