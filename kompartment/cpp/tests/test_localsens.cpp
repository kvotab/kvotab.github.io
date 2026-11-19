// Local sensitivities against the Julia package's (tools/localsens_fixtures.jl writes
// tests/fixtures/localsens.json), with parity on: for every model the builder's fixtures
// build, the bundled examples as the Julia package's own tests take them, and models made up
// to reach each branch -- the problem (the parameters chosen, the slots, the steps, the
// initial state with dy0/dp, the tolerances, the weight floor and the state each sensitivity is
// held with, the big Jacobian's pattern
// and colouring, the right-hand side and the big Jacobian's values at three points, the block
// iteration matrix formed and solved with and without a state held), then the run (its
// progress, the times, every series of y and dy/dp to the bit, the counts, the states as the
// page names them, every elasticity), or the refusal in the same words. For every model: its
// parameter slots and labels, its states, whether df/dp is generated and why not, what
// `uncarried` says of every slot, and df/dp along every slot at three points. Besides: the
// solver's words taken out of a message, the rewording of a differenced failure, elasticities
// and slot labels on odd inputs.
//
// KOMPARTMENT_LOCALSENS_ONLY=text runs only the cases whose name holds it (for a sanitizer build).

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/errorinfo.hpp"
#include "engine/farfield_domain.hpp"
#include "engine/localsens.hpp"
#include "engine/paramtangent.hpp"
#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "solvers/solvers.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
double unbits(const std::string& s) {
    if (s == "nan") return NaN;
    std::uint64_t u = std::strtoull(s.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
std::string kept(const std::string& text) { return text.size() <= 300 ? "=" + text : "#" + fnv(text); }
std::string nums(const std::vector<double>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + bits(v[i]);
    return s;
}
template <class T>
std::string ints(const std::vector<T>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + std::to_string(static_cast<long long>(v[i]));
    return s;
}
std::string joined(const std::vector<std::string>& parts, const std::string& by) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? by : "") + parts[i];
    return s;
}

std::string tdump(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return "i" + std::to_string(v.as_int());
        case Json::Type::Float: return "f" + bits(v.as_double());
        case Json::Type::String: return "s(" + v.as_string() + ")";
        case Json::Type::Array: {
            std::string s = "[";
            for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + tdump(v[i]);
            return s + "]";
        }
        case Json::Type::Object: {
            std::string s = "{";
            bool first = true;
            for (const auto& [k, x] : v.obj()) {
                s += (first ? "" : ";") + k + "=" + tdump(x);
                first = false;
            }
            return s + "}";
        }
    }
    return "";
}
Json array_of(const std::vector<Json>& items) {
    Json a = Json::array();
    for (const Json& x : items) a.push(x);
    return a;
}

/// What a call gives, or the error it raises as the service names it: its type, its message,
/// and a solver's kind, hint and block.
std::string said(const std::function<std::string()>& f) {
    try {
        return f();
    } catch (...) {
        std::exception_ptr e = std::current_exception();
        ErrorInfo info = error_info(e);
        std::string s = "error:" + info.name + ":" + info.message;
        try {
            std::rethrow_exception(e);
        } catch (const SolverError& x) {
            s += "|kind=" + x.kind + "|hint=" + (x.hint ? *x.hint : std::string()) + "|block=" + (x.block_name ? *x.block_name : std::string());
        } catch (...) {
        }
        return s;
    }
}

/// Where the problem is looked at: its initial state at the start, two states made from it at later instants.
std::vector<std::pair<double, std::vector<double>>> points(double t0, double t1, const std::vector<double>& Y0, std::size_t n) {
    const std::size_t N = Y0.size();
    std::vector<double> a(N), b(N);
    for (std::size_t k = 0; k < N; k++) {
        const long long i = static_cast<long long>(k) + 1;
        a[k] = k < n ? Y0[k] * (1.0 + 0.25 * static_cast<double>((i * 7) % 5)) + 0.5 * static_cast<double>((i * 3) % 4)
                     : Y0[k] + 0.1 * static_cast<double>((i * 5) % 7) - 0.3;
        b[k] = std::fabs(Y0[k]) * 0.3 + 1e-3 * static_cast<double>(i);
    }
    return {{t0, Y0}, {t0 + 0.37 * (t1 - t0), a}, {t1, b}};
}

double min_change(const Project& project) {
    const Json& v = project.simulation.get("min_change_time");
    const double x = v.is_null() ? 0.0 : py_float_nan(v);
    return std::isfinite(x) ? x : 0.0;
}

SensitivityOptions options_of(const Json& o) {
    SensitivityOptions so;
    so.most = o.get("most");
    so.differenced = o.get("differenced") == Json(true);
    return so;
}

std::vector<std::string> problem_lines(SensitivityProblem& pr, const Project& project) {
    System& sys = *pr.system;
    std::vector<std::string> lines;
    lines.push_back("n=" + std::to_string(pr.n) + " m=" + std::to_string(pr.m) + " tangent=" + (pr.tangent ? "true" : "false") +
                    " why=" + (pr.why.reason ? *pr.why.reason : std::string("-")) + " rtol=" + bits(pr.rtol));
    lines.push_back("chosen=" + tdump(pr.chosen));
    lines.push_back("wanted=" + tdump(array_of(pr.wanted)));
    std::vector<double> steps;
    for (const Json& e : pr.wanted) steps.push_back(step_for(sys.P[static_cast<std::size_t>(e.get("slot").as_int())]));
    lines.push_back("steps=" + nums(steps));
    lines.push_back("y0=" + nums(pr.equations.y0));
    lines.push_back("abstol=" + nums(pr.equations.abstol));
    lines.push_back("floor=" + ints(pr.weight_floor.from) + "|" + nums(pr.weight_floor.factor));
    lines.push_back("held=" + ints(pr.held_with));
    const Pattern& big = *pr.jacobian.pattern;
    lines.push_back("pattern=" + ints(big.colptr) + "|" + ints(big.rowval));
    std::string groups = "none";
    if (pr.jacobian.groups) {
        std::vector<std::string> parts;
        for (const auto& g : *pr.jacobian.groups) parts.push_back(ints(g));
        groups = joined(parts, "|");
    }
    lines.push_back("groups=" + groups);
    lines.push_back(std::string("evaluate=") + (pr.jacobian.evaluate ? "true" : "false"));
    // As a run starts: the clock's anchors where the stretch starts, the histories primed.
    const double t0 = sys.start_time, t1 = sys.end_time;
    const double mc = min_change(project);
    sys.use_clock_interpolation(mc, t0);
    pr.equations.on_segment(t0, mc);
    sys.prime_recorders(t0, pr.equations.y0);
    const std::size_t N = pr.equations.y0.size();
    const std::size_t nnz = big.nnz();
    int k = 0;
    for (const auto& [t, Y] : points(t0, t1, pr.equations.y0, static_cast<std::size_t>(pr.n))) {
        k++;
        Vec out(N, 0.0);
        lines.push_back("dydt " + std::to_string(k) + "=" + said([&] {
                            pr.equations.dydt(out, t, Y);
                            return nums(out);
                        }));
        if (!pr.jacobian.evaluate) continue;
        Vec vals(nnz, 0.0);
        bool ok = false;
        lines.push_back("jac " + std::to_string(k) + "=" + said([&] {
                            ok = pr.jacobian.evaluate(vals, t, Y);
                            return std::string(ok ? "1" : "0") + ":" + nums(vals);
                        }));
        if (!(k == 1 && ok)) continue;
        // The block iteration matrix, formed and solved as the NDF forms and solves it: with no
        // state held, with the first held (its row the identity in every block, nothing of the
        // coupling under it), and with none again.
        lines.push_back("matrix=" + said([&] {
                            std::unique_ptr<AbstractIterationMatrix> W =
                                pr.equations.iteration_matrix(static_cast<int>(N), &big, vals, "auto", nullptr, &solver_hints());
                            std::vector<std::uint8_t> held(N, 0);
                            held[0] = 1;
                            std::vector<std::string> parts;
                            const std::pair<const std::vector<std::uint8_t>*, double> steps_[] = {
                                {nullptr, 1e-3 * (t1 - t0)}, {&held, 0.25}, {nullptr, 2.0}};
                            for (const auto& [h, a] : steps_) {
                                std::optional<std::string> msg = W->form(a, vals, h);
                                Vec x(N);
                                for (std::size_t i = 1; i <= N; i++) x[i - 1] = 0.125 * static_cast<double>((static_cast<long long>(i) * 37) % 11) - 0.6;
                                if (!msg) W->solve_inplace(x);
                                const Json& info = W->info();
                                parts.push_back(std::string("held=") + (h ? "true" : "false") + " a=" + bits(a) + " msg=" + (msg ? *msg : std::string("-")) +
                                                " sparse=" + (info.get("sparse") == Json(true) ? "true" : "false") + " lu=" + info.get("lu").as_string() +
                                                " fill=" + tdump(info.get("fill")) + " x=" + nums(x));
                            }
                            W->release();
                            return joined(parts, "\n");
                        }));
    }
    return lines;
}

std::vector<std::string> run_lines(const Json& model, const Json& params, const Json& o) {
    std::vector<std::pair<double, double>> prog;
    const bool abort = o.get("abort") == Json(true);
    SensitivityOptions so = options_of(o);
    so.on_progress = [&](double f, double at) {
        prog.emplace_back(f, at);
        return !abort;
    };
    SensitivityRun r;
    std::string err = said([&] {
        r = run_sensitivity(std::make_shared<const Project>(model), params, so);
        return std::string();
    });
    std::vector<std::string> said_progress;
    for (const auto& [f, at] : prog) said_progress.push_back(bits(f) + ":" + bits(at));
    std::vector<std::string> lines = {"progress=" + joined(said_progress, ",")};
    if (!err.empty()) {
        lines.push_back(err);
        return lines;
    }
    Json stats = r.stats.shallow();
    stats.erase("ms");
    lines.push_back(std::string("tangent=") + (r.tangent ? "true" : "false") + " points=" + std::to_string(r.t.size()) + " stats=" + tdump(stats));
    lines.push_back("chosen=" + tdump(r.chosen));
    lines.push_back("series=" + tdump(array_of(r.series)));
    lines.push_back("t=" + nums(r.t));
    for (std::size_t i = 0; i < r.y.size(); i++) lines.push_back("y " + std::to_string(i + 1) + "=" + nums(r.y[i]));
    for (std::size_t k = 0; k < r.sens.size(); k++)
        for (std::size_t i = 0; i < r.sens[k].size(); i++)
            lines.push_back("s " + std::to_string(k + 1) + " " + std::to_string(i + 1) + "=" + nums(r.sens[k][i]));
    for (std::size_t k = 0; k < r.sens.size(); k++)
        for (std::size_t i = 0; i < r.sens[k].size(); i++)
            lines.push_back("e " + std::to_string(k + 1) + " " + std::to_string(i + 1) + "=" +
                            nums(elasticity(r.y[i], r.sens[k][i], r.chosen[k].get("value"))));
    return lines;
}

std::string case_text(const Json& model, const Json& params, const Json& o) {
    std::shared_ptr<const Project> project;
    std::unique_ptr<SensitivityProblem> pr;
    std::string head = said([&] {
        project = std::make_shared<const Project>(model);
        pr = sensitivity_problem(project, params, options_of(o));
        return std::string();
    });
    if (!head.empty()) return head;
    std::vector<std::string> lines = problem_lines(*pr, *project);
    lines.push_back("run");
    for (std::string& l : run_lines(model, params, o)) lines.push_back(std::move(l));
    return joined(lines, "\n");
}

/// A model's parameter slots and states as the page names them, whether df/dp is generated, what
/// `uncarried` says, and df/dp along every parameter slot at three points.
std::string slots_text(const Json& model) {
    std::shared_ptr<const Project> project;
    std::shared_ptr<System> sys;
    std::string head = said([&] {
        project = std::make_shared<const Project>(model);
        sys = std::make_shared<System>(project);
        return std::string();
    });
    if (!head.empty()) return head;
    const std::vector<Json> slots = parameter_slots(*sys);
    std::vector<std::string> labels;
    for (const Json& e : slots) labels.push_back(slot_label(e));
    std::vector<std::string> lines = {"slots=" + tdump(array_of(slots)), "labels=" + joined(labels, "|"), "series=" + tdump(array_of(state_series(*sys)))};
    ParamTangent t = param_tangent(*sys);
    lines.push_back(std::string("tangent=") + (t.available ? "true" : "false") + " reason=" + (t.reason ? *t.reason : std::string("-")));
    lines.push_back("uncarried=" + said([&] {
                        std::optional<std::string> u = uncarried(*project, *sys, slots);
                        return u ? *u : std::string("-");
                    }));
    for (const Json& e : slots)
        lines.push_back("uncarried " + std::to_string(e.get("slot").as_int()) + "=" + said([&] {
                            std::optional<std::string> u = uncarried(*project, *sys, {e});
                            return u ? *u : std::string("-");
                        }));
    if (!t.available) return joined(lines, "\n");
    std::vector<double> y0 = sys->initial_state();
    sys->prime_recorders(sys->start_time, y0);
    const std::size_t np = static_cast<std::size_t>(sys->nparam);
    int k = 0;
    for (const auto& [tt, y] : points(sys->start_time, sys->end_time, y0, y0.size())) {
        k++;
        for (std::size_t slot = 0; slot < np; slot++) {
            std::vector<double> w(np, 0.0);
            w[slot] = 1.0;
            lines.push_back("pvp " + std::to_string(k) + " " + std::to_string(slot) + "=" + said([&] { return nums(param_pvp(*t.plan, tt, y, w)); }));
        }
        std::vector<double> w(np);
        for (std::size_t i = 1; i <= np; i++) w[i - 1] = 0.5 + 0.25 * static_cast<double>(i % 3);
        lines.push_back("pvp " + std::to_string(k) + " ones=" + said([&] { return nums(param_pvp(*t.plan, tt, y, w)); }));
    }
    return joined(lines, "\n");
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/localsens.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const char* only_env = std::getenv("KOMPARTMENT_LOCALSENS_ONLY");
    const std::string only = only_env ? only_env : "";
    set_parity(true);
    std::map<std::string, Json> examples;
    std::function<Json(const Json&)> model_of = [&](const Json& c) -> Json {
        if (c.has("example")) {
            const std::string& ex = c.get("example").as_string();
            if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
            return examples[ex];
        }
        if (c.has("builder")) return model_of(fx.get("builder")[static_cast<std::size_t>(c.get("builder").as_int())]);
        const Json& m = c.get("model");
        return m.is_string() ? fx.get("models").get(m.as_string()) : m;
    };
    std::string all;
    int n = 0, runs = 0, refused = 0;
    auto record = [&](const std::string& head, const std::string& text, const Json& want) {
        all += (n++ ? "\n\n" : "") + std::string("## ") + head + "\n" + text;
        CHECK_MSG(kept(text) == want.as_string(), head + "\n   here:  " + kept(text).substr(0, 300) + "\n   there: " + want.as_string().substr(0, 300));
    };
    for (const Json& c : fx.get("cases").arr()) {
        if (!only.empty() && c.get("name").as_string().find(only) == std::string::npos) continue;
        std::string text;
        try {
            text = case_text(model_of(c), c.get("parameters"), c.get("options"));
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(c.get("name").as_string() + " " + json_text(c.get("parameters"), 0) + " " + json_text(c.get("options"), 0), text, c.get("out"));
        runs++;
        if (text.rfind("error:", 0) == 0) refused++;
    }
    int slots = 0;
    for (const Json& s : fx.get("slots").arr()) {
        if (!only.empty() && s.get("name").as_string().find(only) == std::string::npos) continue;
        std::string text;
        try {
            text = slots_text(model_of(s));
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record("slots " + s.get("name").as_string(), text, s.get("out"));
        slots++;
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/localsens.cpp.txt", std::ios::binary) << all;

    // The solver's words, out of the messages a solve gives up with.
    for (const Json& w : fx.get("words").arr())
        CHECK_MSG(ls_solver_words(w.get("in").as_string()) == w.get("out").as_string(), "the solver's words in: " + w.get("in").as_string());

    // Differenced failures reworded, or not.
    int failures = 0;
    if (only.empty()) {
        for (const Json& f : fx.get("failures").arr()) {
            SensitivityOptions so;
            so.differenced = f.get("differenced") == Json(true);
            auto project = std::make_shared<const Project>(fx.get("models").get(f.get("model").as_string()));
            std::unique_ptr<SensitivityProblem> pr = sensitivity_problem(project, f.get("parameters"), so);
            SolverError e(f.get("kind").as_string(), f.get("message").as_string(), unbits(f.get("t").as_string()));
            std::optional<SolverError> out = ls_differenced_failure(e, *pr, so.differenced);
            std::string got = out ? out->kind + "|" + out->message + "|" + bits(out->t) + "|" + (out->hint ? *out->hint : std::string("-")) : "-";
            CHECK_MSG(got == f.get("out").as_string(), f.get("model").as_string() + " " + json_text(f.get("parameters"), 0) + " " + f.get("kind").as_string() +
                                                           ":\n   here:  " + got + "\n   there: " + f.get("out").as_string());
            failures++;
        }
    }

    // Elasticities and slot labels on odd inputs.
    for (const Json& e : fx.get("elasticity").arr()) {
        const std::vector<double> y = {1.0, 0.0, -2.0, NaN, std::numeric_limits<double>::infinity(), 3.0};
        const std::vector<double> s = {0.5, 1.0, 3.0, 1.0, 2.0};
        CHECK_MSG(nums(elasticity(y, s, e.get("p"))) == e.get("out").as_string(), "elasticity for p = " + json_text(e.get("p"), 0));
    }
    for (const Json& l : fx.get("labels").arr())
        CHECK_MSG(slot_label(l.get("in")) == l.get("out").as_string(), "slot_label of " + json_text(l.get("in"), 0) + ": " + slot_label(l.get("in")));

    set_parity(false);
    std::printf("%d cases (%d refused), %d models' slots, %d failures\n", runs, refused, slots, failures);
    return check::summary("test_localsens");
}
