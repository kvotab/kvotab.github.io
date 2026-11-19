#include "engine/runner.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <set>

#include "engine/derived.hpp"
#include "engine/farfield.hpp"
#include "engine/farfield_domain.hpp"
#include "engine/jacobian.hpp"
#include "engine/landing.hpp"
#include "engine/massbalance.hpp"
#include "engine/nonfinite.hpp"
#include "engine/switchtimes.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

namespace kompartment {

namespace {

double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

void check_initial_state(const System& sys, const Vec& y0) {
    for (std::size_t i = 0; i < y0.size(); i++) {
        if (std::isfinite(y0[i])) continue;
        const Entry* at = nullptr;
        for (const auto& s : sys.builder->states)
            if (s->base <= static_cast<int>(i) && static_cast<int>(i) < s->base + s->width) {
                at = s.get();
                break;
            }
        std::string where;
        if (at && !at->dims.empty()) where = " at " + describe_tuple(tuple_by_list(*sys.builder->space, at->dims, static_cast<int>(i) - at->base));
        std::string name = at ? at->name : "State " + std::to_string(i);
        std::string v = js_text(y0[i]);
        throw SolverError("nonfinite", name + " starts at " + v + where + ", which is not a number the simulation can start from. Its initial "
                          "inventory works out to " + v + " -- most often a division by a parameter that is zero, or a log or square root of one.", 0.0);
    }
}

struct StepCollector {
    std::vector<double> t;
    std::vector<Vec> y;
    long stride = 1;
    long seen = 0;
    double last = -std::numeric_limits<double>::infinity();

    void collect(double time, const Vec& state) {
        if (!(time > last)) return;
        last = time;
        long s = seen++;
        if (s % stride != 0) return;
        t.push_back(time);
        y.push_back(state);
        if (t.size() >= static_cast<std::size_t>(MAX_SOLVER_POINTS) * 2) {
            std::vector<double> nt;
            std::vector<Vec> ny;
            for (std::size_t i = 0; i < t.size(); i += 2) {
                nt.push_back(t[i]);
                ny.push_back(std::move(y[i]));
            }
            t = std::move(nt);
            y = std::move(ny);
            stride *= 2;
        }
    }
};

// A run's solution, as the runner keeps it: times, rows and counts.
struct RunSolution {
    std::vector<double> t;
    std::vector<Vec> y;
    Json stats = Json::object();
};

RunSolution as_run(const Solution& s) {
    RunSolution r;
    r.t = s.t;
    r.y.reserve(s.y.size());
    for (const Vec& row : s.y) r.y.push_back(row);
    r.stats = s.stats.is_object() ? s.stats : Json::object();
    return r;
}

double number_at(const Json& stats, const char* key) {
    const Json& v = stats.get(key);
    return v.is_number() ? v.as_double() : 0.0;
}
void add_to(Json& stats, const char* key, double amount) {
    double sum = number_at(stats, key) + amount;
    stats.set(key, Json(static_cast<long long>(sum)));
}
void add_held(Json& stats, const Json& s) {
    const Json& held = s.get("held");
    if (!held.is_array()) return;
    if (!stats.get("held").is_array()) {
        stats.set("held", held.shallow());
        return;
    }
    Json& mine = stats["held"];
    for (std::size_t i = 0; i < held.size() && i < mine.size(); i++) mine[i] = Json(static_cast<long long>(mine[i].as_double() + held[i].as_double()));
}
void add_method_steps(Json& into, const Json& from) {
    const Json& by = from.get("steps_by");
    if (!by.is_object()) return;
    if (!into.get("steps_by").is_object()) into.set("steps_by", Json::object());
    Json& acc = into["steps_by"];
    for (const auto& [name, n] : by.obj()) acc.set(name, Json(static_cast<long long>(number_at(acc, name.c_str()) + n.as_double())));
    add_to(into, "switches", number_at(from, "switches"));
}

RunSolution from_steps(const StepCollector& steps, const RunSolution& solution) {
    RunSolution out;
    out.t.push_back(solution.t.front());
    out.y.push_back(solution.y.front());
    for (std::size_t i = 0; i < steps.t.size(); i++) {
        if (!(steps.t[i] > out.t.back())) continue;
        out.t.push_back(steps.t[i]);
        out.y.push_back(steps.y[i]);
    }
    if (solution.t.back() > out.t.back()) {
        out.t.push_back(solution.t.back());
        out.y.push_back(solution.y.back());
    }
    out.stats = solution.stats.shallow();
    out.stats.set("points", Json(static_cast<long long>(out.t.size())));
    out.stats.set("solver_points", Json(static_cast<long long>(steps.seen)));
    out.stats.set("thinned_by", Json(static_cast<long long>(steps.stride > 1 ? steps.stride : 0)));
    return out;
}

RunSolution merge_steps(const RunSolution& solution, const StepCollector& steps) {
    RunSolution out;
    auto push = [&](double tv, const Vec& yv) {
        if (!out.t.empty() && std::fabs(tv - out.t.back()) <= std::fabs(out.t.back() == 0 ? tv : out.t.back()) * 1e-9) return;
        out.t.push_back(tv);
        out.y.push_back(yv);
    };
    std::size_t i = 0, j = 0;
    const double inf = std::numeric_limits<double>::infinity();
    while (i < solution.t.size() || j < steps.t.size()) {
        double a = i < solution.t.size() ? solution.t[i] : inf;
        double b = j < steps.t.size() ? steps.t[j] : inf;
        if (a <= b) push(a, solution.y[i++]);
        else push(b, steps.y[j++]);
    }
    out.stats = solution.stats.shallow();
    out.stats.set("points", Json(static_cast<long long>(out.t.size())));
    out.stats.set("solver_points", Json(static_cast<long long>(steps.seen)));
    out.stats.set("thinned_by", Json(static_cast<long long>(steps.stride > 1 ? steps.stride : 0)));
    return out;
}

// Integrates in segments, restarting at every declared corner.
RunSolution solve_across_breaks(const std::function<RunSolution(const Vec&, const Vec&)>& solve, const Vec& grid, const Vec& y0,
                                const Vec& breaks, const std::function<Vec(double, const Vec&)>& jump_at) {
    RunSolution out;
    Json& stats = out.stats;
    for (const char* key : {"nsteps", "nfailed", "nfevals", "restarts"}) stats.set(key, Json(0));
    stats.set("breaks", Json(static_cast<long long>(breaks.size())));
    Vec ends = breaks;
    ends.push_back(grid.back());
    Vec y = y0;
    double at = grid.front();
    std::size_t nxt = 0;
    for (double end : ends) {
        if (!(end > at)) continue;
        Vec inside = {at};
        while (nxt < grid.size() && grid[nxt] <= at) nxt++;
        while (nxt < grid.size() && grid[nxt] < end) inside.push_back(grid[nxt++]);
        inside.push_back(end);
        RunSolution seg = solve(inside, y);
        for (std::size_t i = 0; i < seg.t.size(); i++) {
            if (i == 0 && !out.t.empty() && seg.t[i] == out.t.back()) continue;
            out.t.push_back(seg.t[i]);
            out.y.push_back(seg.y[i]);
        }
        const Json& s = seg.stats;
        for (const char* key : {"nsteps", "nfailed", "nfevals", "restarts"}) add_to(stats, key, number_at(s, key));
        if (!s.empty()) {
            if (!js_truthy(stats.get("solver")) && js_truthy(s.get("solver"))) stats.set("solver", s.get("solver"));
            if (!s.get("sparse").is_null()) stats.set("sparse", s.get("sparse"));
            if (!s.get("fill").is_null()) stats.set("fill", s.get("fill"));
            // `jumps` here are the events a trigger set off inside the segment; the corners'
            // own are added by `run_project`.
            for (const char* key : {"npds", "ndecomps", "negative", "events", "jumps"})
                if (!s.get(key).is_null()) add_to(stats, key, number_at(s, key));
            add_held(stats, s);
            add_method_steps(stats, s);
        }
        y = seg.y.back();
        at = seg.t.back();
        if (jump_at) y = jump_at(at, y);
    }
    add_to(stats, "restarts", static_cast<double>(ends.size() - 1));
    return out;
}

// Integrates a model with discrete events, restarting at each crossing.
RunSolution solve_with_events(System& sys, const RhsFunction& f, SolverFunction solver, const Vec& grid, const Vec& y0,
                              const SolverOptions& opts) {
    double last = grid.back();
    RunSolution out;
    Json& stats = out.stats;
    for (const char* key : {"nsteps", "nfailed", "nfevals", "events", "restarts"}) stats.set(key, Json(0));
    double t = grid.front();
    Vec y = y0;
    std::size_t nxt = 0;
    int guard = 0;
    for (;;) {
        if (guard > MAX_EVENTS)
            throw std::runtime_error("The simulation hit " + std::to_string(MAX_EVENTS) + " discrete events without reaching t=" + js_number(last) +
                                     ". An event whose two expressions stay equal fires again the moment the solver restarts; check the "
                                     "crossing direction.");
        guard++;
        while (nxt < grid.size() && grid[nxt] <= t) nxt++;
        if (nxt >= grid.size()) break;
        Vec span = {t};
        span.insert(span.end(), grid.begin() + static_cast<std::ptrdiff_t>(nxt), grid.end());
        Solution seg = solver(f, span, y, opts);
        for (std::size_t i = 0; i < seg.t.size(); i++) {
            if (i == 0 && !out.t.empty() && seg.t[i] == out.t.back()) continue;
            out.t.push_back(seg.t[i]);
            out.y.push_back(seg.y[i]);
        }
        const Json& s = seg.stats;
        for (const char* key : {"nsteps", "nfailed", "nfevals"}) add_to(stats, key, number_at(s, key));
        if (!stats.has("solver")) stats.set("solver", s.get("solver"));
        stats.set("sparse", s.has("sparse") ? s.get("sparse") : stats.get("sparse"));
        add_to(stats, "negative", number_at(s, "negative"));
        add_held(stats, s);
        add_method_steps(stats, s);
        if (!seg.stopped) break;
        t = seg.stopped->t;
        y = seg.stopped->y;
        std::vector<int> which(seg.stopped->which.begin(), seg.stopped->which.end());
        sys.fire_events(which, t, y.data());
        // An event a trigger sets off moves the state, and the next segment starts from what
        // it leaves. The row *at* the crossing is the state before, as a timed event's corner
        // is: the segment ends on it here, so the next segment's first row, the state after,
        // is the seam dropped.
        if (auto acted = sys.jumps_at_crossing(which, y)) {
            if (out.t.empty() || out.t.back() != t) {
                out.t.push_back(t);
                out.y.push_back(y);
            }
            y = acted->first;
            add_to(stats, "jumps", acted->second);
        }
        sys.store_step(t, y.data());
        add_to(stats, "events", static_cast<double>(which.size()));
        add_to(stats, "restarts", 1);
    }
    return out;
}

}  // namespace

RunState run_state(const System& sys) {
    RunState state{sys.data.MEM, sys.data.DIS, sys.sampled_times, sys.min_change, sys.origin, {}};
    for (int k : sys.laplace) state.laplace.push_back(static_cast<const LaplaceFarfPath&>(*sys.data.FARF[static_cast<std::size_t>(k)]).run_state());
    return state;
}

void restore_run_state(System& sys, const RunState& state) {
    sys.data.MEM = state.mem;
    sys.data.DIS = state.dis;
    for (std::size_t q = 0; q < sys.laplace.size() && q < state.laplace.size(); q++)
        static_cast<LaplaceFarfPath&>(*sys.data.FARF[static_cast<std::size_t>(sys.laplace[q])]).restore_run_state(state.laplace[q]);
    sys.sampled_times = state.sampled;
    sys.use_clock_interpolation(state.min_change, state.origin);
}

std::vector<double> absolute_tolerance(const Project& project, const System& sys) {
    double fallback = project.simulation.get("abstol").as_double();
    std::vector<double> per_state(static_cast<std::size_t>(sys.nstate), fallback);
    bool asked = false;
    for (const auto& s : sys.builder->states) {
        if (s->kind != "compartment" && s->kind != "waste_package") continue;
        for (int off = 0; off < s->width; off++) {
            Json v = value_at(s->block, "abstol", tuple_by_list(*sys.builder->space, s->dims, off));
            if (v.is_null() || v == "") continue;
            double n = py_float_nan(v);
            if (!(std::isfinite(n) && n > 0)) continue;
            per_state[static_cast<std::size_t>(s->base + off)] = n;
            asked = true;
        }
    }
    if (!asked) per_state.clear();
    return per_state;
}

std::vector<std::uint8_t> non_negative_states(const Project& project, const System& sys) {
    std::vector<std::uint8_t> out(static_cast<std::size_t>(sys.nstate), 0);
    const Json& on = project.simulation.get("non_negative");
    if (on.is_bool() && !on.as_bool()) return out;
    for (const auto& s : sys.builder->states) {
        if (s->kind != "compartment" && s->kind != "waste_package") continue;
        for (int i = 0; i < s->width; i++) {
            Json v = value_at(s->block, "non_negative", tuple_by_list(*sys.builder->space, s->dims, i));
            out[static_cast<std::size_t>(s->base + i)] = !(v.is_bool() && !v.as_bool());
        }
    }
    return out;
}

Results run_project(std::shared_ptr<const Project> project, std::shared_ptr<System> system, const RunOptions& options) {
    if (!system) system = std::make_shared<System>(project);
    double t0 = now_s();
    System& sys = *system;
    // Equations standing over the model's own (the local sensitivity's): integrated by this
    // run's machinery in their place.
    const Equations* equations = options.equations;
    // Layers handed in are held instead of laid out: a part of a split run is given the whole
    // model's. Any other run lays out its own, so a system handed from run to run lets go of
    // the last one's.
    pin_layers(sys, options.layers);
    // A far-field path lays its matched layers out at the first instant of a run and holds
    // them to the end of it: this is that instant, every run.
    for (const auto& F : sys.data.FARF) F->restart();
    double build_ms = 1000 * (now_s() - t0);
    Vec grid = project->time_grid();
    Vec y0 = equations ? equations->y0 : sys.initial_state();
    check_initial_state(sys, y0);
    int nstate = sys.nstate;
    Vec abstol = absolute_tolerance(*project, sys);
    std::vector<std::uint8_t> non_negative = non_negative_states(*project, sys);
    if (equations) {
        // The equations' own tolerance per element; nothing after the states held at zero.
        abstol = equations->abstol;
        if (non_negative.size() < y0.size()) non_negative.resize(y0.size(), 0);
    }
    std::optional<StepCollector> steps;
    if (project->solver_points && !options.on_grid) steps.emplace();
    Vec span = (steps && project->output_mode == "solver") ? Vec{grid.front(), grid.back()} : grid;
    double solve_start = now_s();
    Results res;
    res.project = project;
    res.system = system;
    res.timing = Json::object();
    if (nstate == 0) {
        res.t = grid;
        res.y.assign(grid.size(), Vec{});
        if (sys.has_store_step()) {
            sys.prime_recorders(grid.front(), {});
            for (double tt : grid) sys.store_step(tt, nullptr);
        }
        if (options.on_progress) options.on_progress(1.0, grid.back());
        res.stats = Json::object({{"solver", Json()}, {"integrated", Json(false)}, {"points", Json(static_cast<long long>(grid.size()))}});
        res.timing.set("build_ms", Json(build_ms));
        res.timing.set("solve_ms", Json(1000 * (now_s() - solve_start)));
        res.kept = run_state(sys);
        return res;
    }
    const Json& sim = project->simulation;
    std::string asked = equations ? equations->solver : sim.get("solver").is_null() ? "ndf" : js_str(sim.get("solver"));
    // The quickest solver for what the model asks, unless the policy says to keep to its own;
    // equations keep to theirs whatever happens.
    std::string solver_id = equations ? asked : options.solver ? *options.solver : quicker_solver(asked);
    SolverFunction solve_fn = solver_by_id(solver_id);
    if (!solve_fn) {
        std::string here = "dp45, ndf, ros23";
        // A solver the other engines have: theirs to run (the service says so by the name the
        // page falls back on).
        if (std::find(solver_ids().begin(), solver_ids().end(), solver_id) != solver_ids().end())
            throw NotSupported("'" + solver_id + "' is not one of the C++ engine's solvers. Run it with one of its own: " + here +
                               "; or on an engine that has it.");
        throw std::invalid_argument("Unknown solver '" + solver_id + "'. Available here: " + here + ".");
    }
    sys.prime_recorders(grid.front(), y0);
    SolverOptions opts;
    opts.rtol = sim.get("rtol").as_double();
    if (!abstol.empty()) opts.abstol_vector = &abstol;
    else opts.abstol = sim.get("abstol").as_double();
    bool numeric = sim.get("jacobian") == "numeric";
    std::optional<JacobianSpec> jac;
    if (!equations) {
        jac = jacobian_spec(sys, numeric);
        if (jac) opts.jacobian = &*jac;
    } else {
        opts.jacobian = equations->jacobian;
        // Some of the equations' entries weighed against others as well, and the matrix Newton
        // iterates with, solved a block at a time.
        opts.weight_floor = equations->weight_floor;
        opts.iteration_matrix = equations->iteration_matrix;
    }
    opts.non_negative = non_negative;
    opts.auto_abstol = sim.get("auto_abstol") == Json(true);
    auto positive = [&](const char* key) -> std::optional<double> {
        const Json& v = sim.get(key);
        return (v.is_number() && v.as_double() > 0) ? std::optional<double>(v.as_double()) : std::nullopt;
    };
    auto number = [&](const char* key) -> std::optional<double> {
        const Json& v = sim.get(key);
        return v.is_number() ? std::optional<double>(v.as_double()) : std::nullopt;
    };
    opts.hmax = positive("max_step");
    opts.h0 = positive("initial_step");
    opts.max_steps = number("max_steps");
    opts.max_order = number("max_order");
    opts.bdf = sim.get("bdf") == Json(true);
    opts.norm_control = sim.get("norm_control") == Json(true);
    opts.error_norm = sim.get("error_norm").is_string() ? sim.get("error_norm").as_string() : "";
    opts.stagnation_tol = number("stagnation_tol");
    opts.below_tol_run = number("below_tol_run");
    opts.matrix = sim.get("matrix").is_string() ? sim.get("matrix").as_string() : "";
    bool store = sys.has_store_step();
    // The last step the solver accepted, should the run fail on a value that is not a
    // number: the equations are looked at there to say where it came from
    // (engine/nonfinite). The NDF hands back its own with its error, and is spared the
    // copy; the others say only when, so the runner keeps it.
    std::optional<HeldStep> held;
    if (solver_id != "ndf") held.emplace(HeldStep{std::numeric_limits<double>::quiet_NaN(), Vec(y0.size(), 0.0)});
    if (store || steps || held) {
        StepCollector* collector = steps ? &*steps : nullptr;
        HeldStep* hold = held ? &*held : nullptr;
        opts.on_accepted = [&sys, store, collector, hold](double t, const Vec& y) {
            if (store) sys.store_step(t, y.data());
            if (collector) collector->collect(t, y);
            if (hold) {
                hold->t = t;
                hold->y.assign(y.begin(), y.end());
            }
        };
    }
    if (store) opts.on_output = [&sys](double t, const Vec& y) { sys.store_step(t, y.data()); };
    opts.ends_only = steps && project->output_mode == "solver";
    std::optional<EventFunctions> events;
    if (sys.has_events()) {
        events.emplace(static_cast<int>(sys.event_slots.size()), [&sys](Vec& out, double t, const Vec& y) { sys.event_values(out.data(), t, y.data()); },
                       sys.builder->event_direction);
        opts.events = &*events;
    }
    // Where a step ends instead of passing over a pulse in a table read at the clock, which
    // no solver would otherwise see. Made for each run from the tables as they stand.
    std::optional<TableLanding> landing = table_landing(sys.clock_tables(), sim.get("rtol").as_double());
    if (landing) opts.landing = [&landing](double t, double t_next) { return (*landing)(t, t_next); };
    if (options.rows) {
        reset_rows(*options.rows);
        opts.rows = options.rows;
    }
    if (options.on_progress) opts.on_step = [&options](double fraction, long, double at) { return options.on_progress(fraction, at); };

    // Every jump the state makes in the run, and when.
    std::vector<std::pair<const JumpSpec*, double>> jumps;
    for (const JumpSpec& j : sys.builder->jump_specs) {
        if (j.slot) jumps.emplace_back(&j, sys.X[static_cast<std::size_t>(*j.slot)]);
        else
            for (double at : sys.sampled_times[static_cast<std::size_t>(j.index)]) jumps.emplace_back(&j, at);
    }
    for (const auto& [j, at] : jumps) {
        if (!j->slot) continue;
        if (!std::isfinite(at) || sys.builder->slot_class[static_cast<std::size_t>(*j->slot)] != 0)
            throw BuildError("The time every package fails has to come to a number before the run; '" + j->name + "' says '" + j->text + "'.", j->name);
    }
    Vec breaks;
    {
        std::set<double> found;
        for (double b : switch_times(*project))
            if (span.front() < b && b < span.back()) found.insert(b);
        for (const auto& [j, at] : jumps)
            if (span.front() < at && at < span.back()) found.insert(at);
        breaks.assign(found.begin(), found.end());
    }
    long jumped = 0;
    std::function<Vec(double, const Vec&)> jump_at;
    if (!jumps.empty())
        jump_at = [&](double t, const Vec& y) {
            Vec nxt = y;
            for (const auto& [j, at] : jumps)
                if (at == t) {
                    sys.apply_jump(nxt, *j);
                    jumped++;
                }
            return nxt;
        };
    double min_change = sim.get("min_change_time").is_null() ? 0.0 : py_float_nan(sim.get("min_change_time"));
    if (!std::isfinite(min_change)) min_change = 0.0;
    RhsFunction f = equations ? equations->dydt : RhsFunction([&sys](Vec& dy, double t, const Vec& y) { sys.rhs(dy.data(), t, y.data()); });
    // Where the stretch being solved began: a solver that fails at its first instant has
    // nothing later to say where, and this is where.
    std::optional<StretchStart> stretch;
    stretch.emplace(span.front(), y0);
    auto solve_span = [&](const Vec& grid2, const Vec& start) -> RunSolution {
        stretch.emplace(grid2.front(), start);
        sys.use_clock_interpolation(min_change, grid2.front());
        if (equations && equations->on_segment) equations->on_segment(grid2.front(), min_change);
        sys.start_segment(grid2.front(), start.data());
        if (sys.has_events()) return solve_with_events(sys, f, solve_fn, grid2, start, opts);
        return as_run(solve_fn(f, grid2, start, opts));
    };
    RunSolution solution;
    try {
        solution = !breaks.empty() ? solve_across_breaks(solve_span, span, y0, breaks, jump_at) : solve_span(span, y0);
        // The corners' jumps, added to those the triggers set off.
        if (!jumps.empty()) add_to(solution.stats, "jumps", static_cast<double>(jumped));
        if (steps) solution = project->output_mode == "both" ? merge_steps(solution, *steps) : from_steps(*steps, solution);
    } catch (SolverError& e) {
        if (solver_id != asked && e.kind != "aborted") {
            // The quicker solver could not finish: the model's own runs it instead.
            RunOptions again = options;
            again.solver = asked;
            Results other = run_project(project, system, again);
            other.stats.set("tried", Json(solver_id));
            return other;
        }
        std::vector<std::string> hints;
        bool said = e.message.find("cannot go negative") != std::string::npos;
        bool stalled_one_step = (solver_id == "ros23" || solver_id == "dp45") && e.message.find("stopped making progress") != std::string::npos;
        if (!said && solver_id == "dp45")
            hints.push_back("This model looks stiff; switch the solver to \"" + solver_label("ndf") + "\" or \"" + solver_label("ros23") + "\", or to \"" +
                            solver_label("auto") + "\", which finds that out for itself.");
        bool any_held = std::find(non_negative.begin(), non_negative.end(), 1) != non_negative.end();
        if (!said && !stalled_one_step && solver_id != "ndf" && any_held)
            hints.push_back("If a compartment reaches zero at this time, its \"cannot go negative\" setting is the likely cause: \"" +
                            solver_label("ndf") + "\" carries a binding constraint, and turning the setting off on that compartment shows what "
                            "the model is really doing.");
        // A value that is not a number is the model's, whatever the solver made of it, and
        // no hint about solvers is the answer to it: said instead, where it starts and what
        // it reaches (the application's runner).
        if (explain_non_finite(e, sys, stretch, held ? &*held : nullptr, span.back())) hints.clear();
        if (!hints.empty()) e.hint = join(hints, " ");
        throw;
    }
    solution.stats.set("compiled", Json(true));
    if (solver_id != asked) solution.stats.set("asked", Json(asked));
    // What a far-field path has to say about the run (`stats.farfield`, `stats.layers`).
    {
        FarfieldWarnings warned = farfield_warnings(sys);
        if (!warned.farfield.empty()) solution.stats.set("farfield", Json(JArray(warned.farfield.begin(), warned.farfield.end())));
        if (!warned.layers.empty()) solution.stats.set("layers", Json(JArray(warned.layers.begin(), warned.layers.end())));
    }
    double now = now_s();
    res.t = std::move(solution.t);
    res.y = std::move(solution.y);
    res.stats = solution.stats;
    res.timing.set("build_ms", Json(build_ms));
    res.timing.set("solve_ms", Json(1000 * (now - solve_start)));
    res.timing.set("total_ms", Json(1000 * (now - t0)));
    res.kept = run_state(sys);
    return res;
}

// --- what a run reports ------------------------------------------------------------------------------------

namespace {

std::optional<std::string> material_dim(const System& sys, const std::vector<std::string>& dims) {
    const IndexSpace& space = *sys.builder->space;
    const auto& material = sys.builder->material_list;
    if (!material) return std::nullopt;
    const auto& root = space.get_list(*material).root_name;
    for (const auto& d : dims) {
        if (!space.has_list(d)) continue;
        const IndexList& lst = space.get_list(d);
        if (lst.mapping.is_null() && lst.root_name == root) return d;
    }
    return std::nullopt;
}

bool history_kind(const std::string& kind) {
    return kind == "min_max" || kind == "running_mean" || kind == "snapshot" || kind == "delay" || kind == "trigger" || kind == "event";
}

bool time_dependent(const System& sys, const std::string& kind, const char* source, int offset) {
    if (source[0] == 'P') return false;
    if (source[0] == 'X' && !history_kind(kind)) return sys.builder->slot_class[static_cast<std::size_t>(offset)] != 0;
    return true;
}

Json descriptor(const std::string& kind, const std::string& block, const Json& nuclide, const Json& index, const Json& dims, const std::string& label,
                const std::string& unit, const char* source, int offset) {
    return Json::object({{"kind", Json(kind)}, {"block", Json(block)}, {"nuclide", nuclide}, {"index", index}, {"dims", dims}, {"label", Json(label)},
                         {"unit", Json(unit)}, {"source", Json(source)}, {"offset", Json(offset)}});
}

}  // namespace

std::unordered_map<std::string, std::string> material_units(const System& sys) {
    std::unordered_map<std::string, std::string> units;
    for (const auto& n : sys.project->material_names()) units[n] = sys.project->material_unit(n);
    return units;
}

// The series one layout entry stands for: one per index tuple, or one.
void describe_entry(std::vector<Json>& out, const System& sys, const Entry& entry, const std::string& kind, const char* source,
                    const std::unordered_map<std::string, std::string>& units) {
    const IndexSpace& space = *sys.builder->space;
    const std::vector<std::string>& dims = entry.dims;
    std::string unit;
    if (entry.kind == "waste_package" && !entry.role.empty()) unit = entry.unit;
    else if (entry.kind != "event" && entry.block.get("unit").is_string()) unit = entry.block.get("unit").as_string();
    auto still = [&](Json d, int offset) {
        if (!time_dependent(sys, kind, source, offset)) d.set("timeDependent", Json(false));
        return d;
    };
    if (dims.empty()) {
        out.push_back(still(descriptor(kind, entry.name, Json(), Json(), Json::array(), entry.name, unit, source, entry.base), entry.base));
        return;
    }
    std::optional<std::string> md = material_dim(sys, dims);
    std::size_t mpos = md ? static_cast<std::size_t>(std::find(dims.begin(), dims.end(), *md) - dims.begin()) : 0;
    std::size_t nd = dims.size();
    std::vector<const std::vector<ListIndex>*> members;
    for (const auto& d : dims) members.push_back(&space.get_list(d).enabled);
    const std::vector<int>& st = space.strides(dims);
    Json dims_json = Json::array(dims);
    for (int off = 0; off < entry.width; off++) {
        std::vector<std::string> names(nd);
        int rest = off;
        for (std::size_t i = 0; i < nd; i++) {
            int k = rest / st[i];
            rest -= k * st[i];
            names[i] = (*members[i])[static_cast<std::size_t>(k)].name;
        }
        Json material = md ? Json(names[mpos]) : Json();
        std::string u = unit;
        if (u.empty() && md && kind != "trigger") {
            auto it = units.find(names[mpos]);
            if (it != units.end()) u = it->second;
        }
        std::string label = entry.name + " [" + join(names, ", ") + "]";
        out.push_back(still(descriptor(kind, entry.name, material, Json::array(names), dims_json.shallow(), label, u, source, entry.base + off),
                            entry.base + off));
    }
}

std::vector<Json> outputs_of(System& sys, const Project& project) {
    std::unordered_map<std::string, std::string> units = material_units(sys);
    std::vector<Json> out;
    const Builder& b = *sys.builder;
    for (const auto& s : b.states) {
        if (s->kind == "compartment") {
            if (!s->hidden) describe_entry(out, sys, *s, "compartment", "y", units);
            continue;
        }
        if (s->kind == "farfield")
            for (Json& d : farfield_outputs(sys, *s)) out.push_back(std::move(d));
        if (s->kind == "waste_package") describe_entry(out, sys, *s, "waste_inventory", "y", units);
        if (s->kind == "event") describe_entry(out, sys, *s, "event", "y", units);
    }
    for (const auto& a : b.algebraic) {
        if (a->kind == "inflow" || a->hidden) continue;
        describe_entry(out, sys, *a, a->kind, "X", units);
    }
    for (const auto& p : b.param_layout) describe_entry(out, sys, *p, "parameter", "P", units);
    for (const auto& pt : b.point_layout) {
        std::vector<std::string> names;
        for (const auto& d : pt->dims) names.push_back(*pt->index.find(d));
        std::optional<std::string> md = material_dim(sys, pt->dims);
        Json material = md ? Json(*pt->index.find(*md)) : Json();
        std::string at = "@" + js_number(pt->at);
        std::string unit = pt->block.get("unit").is_string() ? pt->block.get("unit").as_string() : "";
        if (unit.empty() && md) {
            auto it = units.find(*pt->index.find(*md));
            if (it != units.end()) unit = it->second;
        }
        std::vector<std::string> index = names;
        index.push_back(at);
        std::vector<std::string> dims = pt->dims;
        dims.push_back(POINT_LIST);
        Json d = Json::object({{"kind", Json("lookup")}, {"block", Json(pt->name)}, {"nuclide", material}, {"index", Json::array(index)},
                               {"dims", Json::array(dims)}, {"label", Json(pt->name + " [" + join(index, ", ") + "]")}, {"unit", Json(unit)},
                               {"source", Json("P")}, {"offset", Json(pt->slot)}, {"timeDependent", Json(false)}});
        out.push_back(d);
    }
    for (Json& d : derived_outputs(project, out)) out.push_back(d);
    return out;
}

std::shared_ptr<const OutputIndex> index_outputs(std::vector<Json> outputs) {
    auto index = std::make_shared<OutputIndex>();
    index->outputs = std::move(outputs);
    for (std::size_t i = 0; i < index->outputs.size(); i++) index->by_label.emplace(index->outputs[i].get("label").as_string(), i);
    return index;
}

const OutputIndex& Results::described() {
    if (!described_) described_ = index_outputs(outputs_of(*system, *project));
    return *described_;
}

const std::vector<Json>& Results::outputs() { return described().outputs; }

std::vector<std::string> Results::labels() {
    std::vector<std::string> out;
    for (const Json& o : outputs()) out.push_back(o.get("label").as_string());
    return out;
}

bool Results::has(const std::string& label) { return described().by_label.count(label) != 0; }

const Json& Results::find_output(const std::string& label) {
    const OutputIndex& index = described();
    auto it = index.by_label.find(label);
    if (it == index.by_label.end()) throw std::out_of_range("No output labelled '" + label + "'");
    return index.outputs[it->second];
}

std::vector<double> Results::series(const std::string& label) { return series_many({find_output(label)})[0]; }
std::vector<double> Results::series(const Json& output) { return series_many({output})[0]; }

std::vector<std::vector<double>> Results::series_many(const std::vector<Json>& outs) {
    std::size_t n = t.size();
    std::vector<std::vector<double>> cols(outs.size(), std::vector<double>(n, 0.0));
    std::vector<std::size_t> alg;
    auto offsets_of = [](const Json& o) {
        std::vector<int> offs;
        if (o.has("offsets")) {
            for (const Json& x : o.get("offsets").arr()) offs.push_back(static_cast<int>(x.as_int()));
        } else {
            offs.push_back(static_cast<int>(o.get("offset").as_int()));
        }
        return offs;
    };
    for (std::size_t k = 0; k < outs.size(); k++) {
        const Json& o = outs[k];
        const std::string& source = o.get("source").as_string();
        if (source == "P") {
            std::fill(cols[k].begin(), cols[k].end(), system->P[static_cast<std::size_t>(o.get("offset").as_int())]);
        } else if (source == "y") {
            // A sum over states is taken in the order its offsets list them.
            std::vector<int> offs = offsets_of(o);
            if (!o.has("offsets")) {
                for (std::size_t i = 0; i < n; i++) cols[k][i] = y[i][static_cast<std::size_t>(offs[0])];
            } else {
                for (std::size_t i = 0; i < n; i++) {
                    double acc = 0.0;
                    for (int off : offs) acc += y[i][static_cast<std::size_t>(off)];
                    cols[k][i] = acc;
                }
            }
        } else if (source == "X") {
            alg.push_back(k);
        } else if (source == "D") {
            // A value read off another series' finished curve.
            const Json& d = o.get("derived");
            const OutputIndex& index = described();
            auto from = d.get("of").is_string() ? index.by_label.find(d.get("of").as_string()) : index.by_label.end();
            if (from == index.by_label.end()) {
                std::fill(cols[k].begin(), cols[k].end(), std::numeric_limits<double>::quiet_NaN());
            } else {
                std::vector<double> src = series_many({index.outputs[from->second]})[0];
                // `py_float(something(at, NaN))`, as the Julia package reads them: a descriptor read
                // back from JSON holds null where the time or period was no number.
                std::vector<double> v = derived_reduce(d.get("kind").as_string(), t, src, py_float_nan(d.get("at")), py_float_nan(d.get("period")));
                for (std::size_t i = 0; i < n && i < v.size(); i++) cols[k][i] = v[i];
            }
        } else {
            std::fill(cols[k].begin(), cols[k].end(), std::numeric_limits<double>::quiet_NaN());
        }
    }
    if (alg.empty()) return cols;
    std::set<int> wanted;
    for (std::size_t k : alg)
        for (int off : offsets_of(outs[k])) wanted.insert(off);
    std::vector<int> need(wanted.begin(), wanted.end());
    std::unordered_map<int, std::size_t> column;
    for (std::size_t j = 0; j < need.size(); j++) column[need[j]] = j;
    std::vector<std::vector<double>> XS = algebraic_rows(need);
    for (std::size_t k : alg) {
        std::vector<int> offs = offsets_of(outs[k]);
        if (!outs[k].has("offsets")) {
            std::size_t j = column[offs[0]];
            for (std::size_t i = 0; i < n; i++) cols[k][i] = XS[i][j];
        } else {
            // Rows summed left to right, as the application's loops sum them.
            for (int off : offs) {
                std::size_t j = column[off];
                for (std::size_t i = 0; i < n; i++) cols[k][i] = cols[k][i] + XS[i][j];
            }
        }
    }
    return cols;
}

std::vector<std::vector<double>> Results::algebraic_rows(const std::vector<int>& need) {
    std::size_t n = t.size();
    System& sys = *system;
    std::vector<std::vector<double>> out(n, std::vector<double>(need.size(), 0.0));
    RunState keep = run_state(sys);
    restore_run_state(sys, kept);
    try {
        for (std::size_t i = 0; i < n; i++) {
            const std::vector<double>& X = sys.evaluate_algebraic(t[i], y[i].data());
            for (std::size_t j = 0; j < need.size(); j++) out[i][j] = X[static_cast<std::size_t>(need[j])];
        }
    } catch (...) {
        restore_run_state(sys, keep);
        sys.clock_at = std::numeric_limits<double>::quiet_NaN();
        throw;
    }
    restore_run_state(sys, keep);
    sys.clock_at = std::numeric_limits<double>::quiet_NaN();
    return out;
}

std::vector<Json> Results::held_at_zero() {
    std::vector<Json> out;
    const Json& held = stats.get("held");
    if (!held.is_array() || !js_truthy(stats.get("nsteps"))) return out;
    double nsteps = stats.get("nsteps").as_double();
    for (std::size_t i = 0; i < held.size(); i++) {
        double steps = held[i].as_double();
        if (steps == 0) continue;
        const Entry* state = nullptr;
        for (const auto& s : system->builder->states)
            if (s->base <= static_cast<int>(i) && static_cast<int>(i) < s->base + s->width) {
                state = s.get();
                break;
            }
        if (!state) continue;
        std::string label = state->name;
        if (!state->dims.empty()) label += " [" + join(system->builder->space->tuple_at(state->dims, static_cast<int>(i) - state->base), ", ") + "]";
        out.push_back(Json::object({{"label", Json(label)}, {"steps", held[i]}, {"fraction", Json(steps / nsteps)}}));
    }
    std::stable_sort(out.begin(), out.end(), [](const Json& a, const Json& b) {
        double fa = a.get("fraction").as_double(), fb = b.get("fraction").as_double();
        if (fa != fb) return fa > fb;
        return lowercase(a.get("label").as_string()) < lowercase(b.get("label").as_string());
    });
    return out;
}

Json Results::mass_balance() {
    const auto& budget = system->builder->budget;
    if (!budget) return Json();
    std::vector<double> abstol = absolute_tolerance(*project, *system);
    return audit(*budget, t, y, project->simulation.get("rtol"), abstol, project->simulation.get("abstol").as_double());
}

std::string Results::summary() {
    std::vector<std::string> parts;
    parts.push_back(stats.get("solver").is_string() ? stats.get("solver").as_string() : "no solver");
    if (stats.get("nsteps").is_number()) parts.push_back(js_number(stats.get("nsteps").as_double()) + " steps");
    if (js_truthy(stats.get("nfailed"))) parts.push_back(js_number(stats.get("nfailed").as_double()) + " failed");
    parts.push_back(std::to_string(t.size()) + " output times");
    if (timing.get("total_ms").is_number()) {
        char buf[32];
        std::snprintf(buf, sizeof buf, "%.2f s", timing.get("total_ms").as_double() / 1000);
        parts.push_back(buf);
    }
    std::size_t held = held_at_zero().size();
    if (held) parts.push_back(std::to_string(held) + " state(s) held at zero");
    return join(parts, ", ");
}

std::string Results::to_csv(const std::vector<Json>* which, double time_origin) {
    const std::vector<Json>& outs = which ? *which : outputs();
    std::vector<std::vector<double>> cols = series_many(outs);
    auto cell = [](const std::string& s) {
        if (s.find_first_of(",\"\n\r") == std::string::npos) return s;
        std::string q = "\"";
        for (char c : s) {
            if (c == '"') q += '"';
            q += c;
        }
        return q + "\"";
    };
    std::string text = "time";
    for (const Json& o : outs) text += "," + cell(o.get("label").as_string());
    for (std::size_t i = 0; i < t.size(); i++) {
        text += "\n" + js_number(time_origin == 0 ? t[i] : t[i] - time_origin);
        for (const auto& c : cols) text += "," + js_number(c[i]);
    }
    return text;
}

}  // namespace kompartment
