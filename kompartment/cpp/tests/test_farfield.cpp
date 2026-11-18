// Far-field paths against the Julia engine's, with parity on
// (tools/farfield_fixtures.jl writes tests/fixtures/farfield.json).
//
// The helpers first: the arithmetic and the geometry a path is made of, each
// called on the fixture's numbers and compared to the bit, or word for word.
// Then models made up to reach every branch of a path on cells: the path as it
// is laid out, the series it reports, the derivative and every slot at a few
// instants with the path's rates and layers there, the tangents of its rates,
// the Jacobian, whole runs (differenced and exact, and again on the same
// system), and runs on layers held from outside -- each text Julia's, or the
// refusal in Julia's words. Then, without Julia: a copy of a system runs as its
// system does, and with parity off the derivative is the summed one and a run
// ends where the parity run ends.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/farfield.hpp"
#include "engine/jacobian_analytic.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

static std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static double unbits(const std::string& s) {
    std::uint64_t u = std::strtoull(s.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}
static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
// A NaN is a NaN whatever its bits.
template <class V>
static std::string nums(const V& v) {
    std::string s;
    bool first = true;
    for (double x : v) {
        if (!first) s += ",";
        first = false;
        s += std::isnan(x) ? std::string("nan") : bits(x);
    }
    return s;
}
static std::string num(double x) { return nums(std::vector<double>{x}); }
template <class V>
static std::string ints(const V& v) {
    std::string s;
    bool first = true;
    for (auto x : v) {
        if (!first) s += ",";
        first = false;
        s += std::to_string(static_cast<long long>(x));
    }
    return s;
}
static const char* yes(bool b) { return b ? "true" : "false"; }
// A short text is kept as it is, a long one as its hash (Julia counts a text's characters, not its bytes).
static std::string kept(const std::string& text) {
    std::size_t characters = 0;
    for (unsigned char c : text)
        if ((c & 0xC0) != 0x80) characters++;
    return characters <= 400 ? "=" + text : "#" + fnv(text);
}
static std::string joined(const std::vector<std::string>& parts, const std::string& sep) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? sep : "") + parts[i];
    return s;
}

// --- the helpers -------------------------------------------------------------------------------------------

static std::string helper(const std::string& fn, const std::vector<double>& x, const std::vector<int>& n, const std::vector<std::string>& s) {
    try {
        if (fn == "np_spacing") return num(np_spacing(x[0]));
        if (fn == "np_sign") return num(np_sign(x[0]));
        if (fn == "num_text") return num_text(x[0]);
        if (fn == "to_precision") return js_to_precision(x[0], n[0]);
        if (fn == "py_hypot") return num(py_hypot(x[0], x[1]));
        if (fn == "js_div") return num(js_div(x[0], x[1]));
        if (fn == "py_pow") {
            try {
                return num(py_pow(x[0], x[1]));
            } catch (const std::domain_error&) {
                return "throws";
            }
        }
        if (fn == "ff_pow") return num(ff_pow(x[0], n[0]));
        if (fn == "np_sum") return num(np_sum(x));
        if (fn == "zeroin") return num(zeroin([](double v) { return v * v * v - 2 * v - 5; }, x[0], x[1]));
        if (fn == "penetration_scale") return num(penetration_scale(x[0], x[1], x[2], x[3], x[4], x[5], x[6]));
        if (fn == "layer_depths") {
            std::vector<double> d(static_cast<std::size_t>(n[0]), 0.0);
            layer_depths(d.data(), x[0], n[0], x[1], x[2]);
            return nums(d);
        }
        if (fn == "layer_depths_tangent") {
            std::vector<double> d(static_cast<std::size_t>(n[0]), 0.0), dd(static_cast<std::size_t>(n[0]), 0.0);
            layer_depths(d.data(), x[0], n[0], x[1], x[2]);
            layer_depths_tangent(dd.data(), x[0], n[0], x[1], x[2], d.data(), x[3], x[4], x[5]);
            return nums(dd);
        }
        if (fn == "matched_grid") {
            std::vector<double> d(static_cast<std::size_t>(n[0]), 0.0), h(static_cast<std::size_t>(n[0]), 0.0);
            double L = x[2];
            double q = matched_grid(d.data(), h.data(), x[0], n[0], x[1], [L]() { return L; });
            return nums(d) + "|" + nums(h) + "|" + num(q);
        }
        if (fn == "coarse") {
            auto msg = coarse_layers_warning(x.data() + 1, static_cast<int>(x.size()) - 1, x[0], s[0]);
            return msg ? *msg : "nothing";
        }
        if (fn == "cells") {
            FarfStructure g{n[0], n[1], n[2], n[3], false};
            auto [rows, cols] = cell_structure(g);
            return ints(rows) + "|" + ints(cols) + "|" + ints(release_cells(g));
        }
    } catch (const FarfError& e) {
        return std::string("error: ") + e.what();
    }
    return "no such helper";
}

// --- the models --------------------------------------------------------------------------------------------

// What went wrong, as the fixture has it: the kind of refusal and its words.
template <class F>
static std::string or_refusal(F&& f) {
    try {
        return f();
    } catch (const FarfError& e) {
        return std::string("path: ") + e.what();
    } catch (const SolverError& e) {
        return "solver: " + e.message;
    } catch (const BuildError& e) {
        return std::string("build: ") + e.what();
    } catch (const ValidationError& e) {
        return std::string("model: ") + e.what();
    }
}

// The states the derivative is asked at: the initial one, and two made from it.
static std::vector<std::vector<double>> states(const std::vector<double>& y0) {
    std::size_t n = y0.size();
    std::vector<std::vector<double>> out(3, y0);
    for (std::size_t i = 1; i <= n; i++) {
        out[1][i - 1] = y0[i - 1] * (1.0 + 0.25 * static_cast<double>((i * 7) % 5)) + 0.5 * static_cast<double>((i * 3) % 4);
        out[2][i - 1] = std::fabs(y0[i - 1]) * 0.3 + 1e-3 * static_cast<double>(i);
    }
    return out;
}

static const FarfPath* cells_of(const std::shared_ptr<FarfieldPath>& F) { return dynamic_cast<const FarfPath*>(F.get()); }

// A path as it was laid out.
static std::string layout_text(const std::shared_ptr<FarfieldPath>& path) {
    const FarfPath* F = cells_of(path);
    if (!F) return "semi-analytical";
    std::vector<std::string> lines;
    lines.push_back("nf=" + std::to_string(F->nf) + " nm=" + std::to_string(F->nm) + " ob=" + std::to_string(F->ob) + " nb=" + std::to_string(F->nb) +
                    " base=" + std::to_string(F->base) + " nnuc=" + std::to_string(F->nnuc) + " other_width=" + std::to_string(F->other_width) +
                    " release_base=" + std::to_string(F->release_base) + " matched=" + yes(F->matched) + " surface=" + F->surface +
                    " ncells=" + std::to_string(F->ncells) + " nnz=" + std::to_string(F->nnz) + " nrel=" + std::to_string(F->nrel) +
                    " slots=" + std::to_string(F->nslots) + " block=" + F->block_name);
    lines.push_back("keys=" + joined(F->keys, ","));
    lines.push_back("key_pos=" + ints(F->key_pos));
    lines.push_back("rows=" + ints(F->rows));
    lines.push_back("cols=" + ints(F->cols));
    lines.push_back("settings=" + ints(F->setting_slots()));
    lines.push_back("row_flat=" + ints(F->row_flat()));
    lines.push_back("col_flat=" + ints(F->col_flat()));
    lines.push_back("rel=" + ints(F->rel_at));
    lines.push_back("release=" + ints(F->release_slots()));
    lines.push_back("starts=" + ints(F->cell_starts()));
    lines.push_back("lam=" + nums(F->lam));
    return joined(lines, "\n");
}

// What a run has changed of a path: its rates and its layers.
static std::string path_text(const std::shared_ptr<FarfieldPath>& path) {
    const FarfPath* F = cells_of(path);
    if (!F) return "semi-analytical";
    return "vals=" + nums(F->vals) + "\nrel_w=" + nums(F->rel_w) + "\nd=" + nums(F->layers_d) + "\nh=" + nums(F->layers_h) + "\nq=" + nums(F->layers_q) +
           "\nlaid_out=" + ints(F->laid_out);
}
static std::string paths_text(const System& sys) {
    std::vector<std::string> parts;
    for (const auto& F : sys.data.FARF) parts.push_back(path_text(F));
    return joined(parts, "\n--\n");
}

// The series the paths report.
static std::string outputs_text(System& sys, const Project& p) {
    std::vector<std::string> lines;
    for (const Json& o : outputs_of(sys, p)) {
        const std::string& kind = o.get("kind").as_string();
        if (kind.rfind("farfield", 0) != 0) continue;
        std::vector<std::string> index, dims;
        if (o.get("index").is_array())
            for (const Json& x : o.get("index").arr()) index.push_back(js_str(x));
        for (const Json& x : o.get("dims").arr()) dims.push_back(js_str(x));
        std::string at;
        if (o.has("offsets")) {
            std::vector<long long> offs;
            for (const Json& x : o.get("offsets").arr()) offs.push_back(x.as_int());
            at = "offsets=" + ints(offs);
        } else {
            at = "offset=" + std::to_string(o.get("offset").as_int());
        }
        lines.push_back(kind + "|" + o.get("block").as_string() + "|" + (o.get("nuclide").is_null() ? std::string("-") : o.get("nuclide").as_string()) + "|" +
                        (o.get("index").is_null() ? std::string("-") : joined(index, ",")) + "|" + joined(dims, ",") + "|" + o.get("label").as_string() + "|" +
                        o.get("unit").as_string() + "|" + o.get("source").as_string() + "|" + at);
    }
    return joined(lines, "\n");
}

// A run as the fixture has it: the application's table of it, its counts, and what the paths said.
static std::string run_text(Results& res) {
    std::vector<std::string> counts;
    for (const char* key : {"nsteps", "nfailed", "nfevals", "events", "jumps", "restarts"})
        if (res.stats.has(key)) counts.push_back(std::string(key) + "=" + js_text(res.stats.get(key)));
    std::vector<std::string> said;
    if (res.stats.get("layers").is_array())
        for (const Json& w : res.stats.get("layers").arr()) said.push_back(w.get("block").as_string() + ": " + w.get("message").as_string());
    return "points=" + std::to_string(res.t.size()) + " " + joined(counts, " ") + " csv=" + fnv(res.to_csv()) + "\n" + joined(said, "\n");
}

static std::string layers_text(const std::optional<FarfLayerMap>& layers) {
    if (!layers) return "none";
    std::vector<std::string> lines;
    for (const auto& [name, combos] : *layers)
        for (const auto& [key, g] : combos) {
            std::string shown = key;
            for (char& c : shown)
                if (c == '\0') c = '/';
            lines.push_back(name + "|" + shown + "|" + nums(g.d) + "|" + nums(g.h) + "|" + num(g.q));
        }
    return joined(lines, "\n");
}

// Layers to hold that are not the model's own: every other combination's, a quarter thicker;
// of the rest, every other one's with a layer too few, which a path does not take; the
// others left to the paths.
static FarfLayerMap altered(const FarfLayerMap& layers) {
    FarfLayerMap out;
    int k = 0;
    for (const auto& [name, combos] : layers) {
        out[name];
        for (const auto& [key, g] : combos) {
            k++;
            FarfLayers other = g;
            if (k % 2 == 1) {
                for (double& v : other.d) v = v * 1.25;
                for (double& v : other.h) v = v * 1.25;
            } else if (k % 4 == 0) {
                other.d.pop_back();
            } else {
                continue;
            }
            out[name][key] = other;
        }
    }
    return out;
}

// The audit of a run, family by family.
static std::string audit_text(const Json& a) {
    std::vector<std::string> lines;
    lines.push_back("worst=" + num(a.get("worst").as_double()) + " at=" + num(a.get("at").as_double()) + " family=" +
                    (a.get("worstFamily").is_null() ? std::string("-") : a.get("worstFamily").as_string()) + " closed=" + yes(a.get("closed").as_bool()));
    for (const Json& f : a.get("families").arr())
        lines.push_back(f.get("name").as_string() + " idle=" + yes(f.get("idle").as_bool()) + " scale=" + num(f.get("scale").as_double()) + " worst=" +
                        num(f.get("worst").as_double()) + " relative=" + num(f.get("relative").as_double()) + " at=" + num(f.get("at").as_double()));
    const Json& total = a.get("total");
    lines.push_back("total scale=" + num(total.get("scale").as_double()) + " worst=" + num(total.get("worst").as_double()) + " relative=" +
                    num(total.get("relative").as_double()) + " at=" + num(total.get("at").as_double()));
    return joined(lines, "\n");
}

struct Worked {
    std::map<std::string, std::string> out;
    std::vector<std::vector<double>> dy;        // the derivative at each instant reached
    std::vector<double> end;                    // the state a run ends at
    bool ran = false;
};

static Worked sections(const Json& model) {
    Worked w;
    auto& out = w.out;
    Json numeric = model.copy();
    if (!numeric.get("simulation").is_object()) numeric.set("simulation", Json::object());
    numeric["simulation"].set("jacobian", Json("numeric"));
    auto project = std::make_shared<const Project>(model);
    {
        System sys(project);
        std::vector<std::string> parts;
        for (const auto& F : sys.data.FARF) parts.push_back(layout_text(F));
        out["layout"] = joined(parts, "\n--\n");
        out["outputs"] = outputs_text(sys, *project);

        // The derivative and every slot at a few instants, with the paths' rates and layers
        // there; then the tangents of the rates along a direction made up here.
        std::vector<double> y0 = sys.initial_state();
        out["y0"] = nums(y0);
        sys.prime_recorders(sys.start_time, y0);
        double times[3] = {sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time};
        std::vector<std::vector<double>> ys = states(y0);
        for (int k = 0; k < 3; k++) {
            std::string at = std::to_string(k + 1);
            std::string refused = or_refusal([&]() {
                std::vector<double> X = sys.evaluate_algebraic(times[k], ys[static_cast<std::size_t>(k)].data());
                std::vector<double> dy = sys.dydt(times[k], ys[static_cast<std::size_t>(k)]);
                out["X" + at] = nums(X);
                out["dy" + at] = nums(dy);
                out["paths" + at] = paths_text(sys);
                w.dy.push_back(dy);
                return std::string();
            });
            if (!refused.empty()) {
                out["X" + at] = refused;
                break;
            }
        }
        std::vector<double> X = sys.X;
        std::vector<double> dX(X.size()), zero(X.size(), 0.0);
        for (std::size_t i = 1; i <= X.size(); i++)
            dX[i - 1] = static_cast<double>(static_cast<long>((i * 37) % 11) - 5) * 1e-3 * (std::fabs(X[i - 1]) + 1);
        parts.clear();
        for (const auto& path : sys.data.FARF) {
            auto* F = dynamic_cast<FarfPath*>(path.get());
            if (!F) {
                parts.push_back("semi-analytical");
                continue;
            }
            parts.push_back(or_refusal([&]() {
                FarfTangent T(*F);
                bool still = farfield_tangent(T, *F, X.data(), zero.data());
                bool moving = farfield_tangent(T, *F, X.data(), dX.data());
                return std::string("still=") + yes(still) + " moving=" + yes(moving) + "\ndvals=" + nums(T.dvals) + "\ndrel=" + nums(T.drel);
            }));
        }
        out["tangent"] = joined(parts, "\n--\n");
    }
    {
        // The Jacobian: whether there is one, its pattern, and its values where the derivative was asked.
        System sys(project);
        const std::shared_ptr<JacobianInfo>& j = sys.jacobian;
        out["jacobian"] = std::string("available=") + yes(j->available) + " constant=" + yes(j->constant) + " state_free=" +
                          (j->analytic ? yes(analytic_state_free(*j->analytic)) : "-") + " reason=" + j->reason.value_or("") + " budget_rows=" +
                          j->budget_rows.value_or("") + " nnz=" + std::to_string(j->nnz) + " colours=" + std::to_string(j->colours);
        out["pattern"] = ints(j->pattern->colptr) + "|" + ints(j->pattern->rowval);
        std::shared_ptr<Analytic> an;
        try {
            an = make_analytic(sys, *j->pattern, full_budget(sys));
            out["plan"] = std::string("constant=") + yes(analytic_constant(*an)) + " state_free=" + yes(analytic_state_free(*an)) +
                          " rows=" + std::to_string(analytic_gradient_rows(*an)) + " entries=" + std::to_string(analytic_gradient_entries(*an));
        } catch (const NoDerivative& e) {
            out["plan"] = std::string("refused: ") + e.what();
        }
        if (an) {
            std::vector<double> y0 = sys.initial_state();
            sys.prime_recorders(sys.start_time, y0);
            double times[3] = {sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time};
            std::vector<std::vector<double>> ys = states(y0);
            for (int k = 0; k < 3; k++) {
                Vec Jv(j->pattern->nnz(), 0.0);
                out["J" + std::to_string(k + 1)] = or_refusal([&]() {
                    bool ok = analytic_evaluate(Jv, *an, times[k], ys[static_cast<std::size_t>(k)]);
                    return std::string(ok ? "1" : "0") + ":" + nums(Jv) + "|" + nums(analytic_gradients(*an));
                });
            }
        }
    }
    // Whole runs: with the Jacobian differenced, then as the model stands -- twice on one
    // system, the second run laying its layers out afresh -- and on layers held from outside.
    out["run numeric"] = or_refusal([&]() {
        auto pn = std::make_shared<const Project>(numeric);
        Results res = run_project(pn, std::make_shared<System>(pn));
        return run_text(res);
    });
    auto system = std::make_shared<System>(project);
    System& sys = *system;
    out["run"] = or_refusal([&]() {
        Results res = run_project(project, system);
        if (!res.y.empty()) w.end = res.y.back();
        w.ran = true;
        Json audit = res.mass_balance();
        if (!audit.is_null()) out["audit"] = audit_text(audit);
        return run_text(res);
    });
    out["paths after"] = paths_text(sys);
    out["run again"] = or_refusal([&]() {
        Results res = run_project(project, system);
        return run_text(res);
    });
    std::optional<FarfLayerMap> layers;
    std::string refused = or_refusal([&]() {
        layers = whole_layers(sys, *project);
        return std::string();
    });
    if (!refused.empty()) out["layers"] = refused;
    if (layers) {
        out["layers"] = layers_text(layers);
        RunOptions held;
        held.layers = &*layers;
        out["run on its layers"] = or_refusal([&]() {
            Results res = run_project(project, system, held);
            return run_text(res);
        });
        FarfLayerMap other = altered(*layers);
        held.layers = &other;
        out["run on other layers"] = or_refusal([&]() {
            Results res = run_project(project, system, held);
            return run_text(res);
        });
        out["paths on other layers"] = paths_text(sys);
        out["run let go"] = or_refusal([&]() {
            Results res = run_project(project, system);
            return run_text(res);
        });
    }
    // A copy of the system runs as its system does.
    {
        auto copy = std::make_shared<System>(sys.clone());
        // (A plan holds its system by address, and the copy has just been moved.)
        copy->jacobian = clone_jacobian(sys.jacobian, *copy);
        std::string its = or_refusal([&]() {
            Results res = run_project(project, copy);
            return run_text(res);
        });
        std::string mine = or_refusal([&]() {
            Results res = run_project(project, system);
            return run_text(res);
        });
        out["a copy runs alike"] = its == mine && mine == out["run"] ? "yes" : "no:\n" + its + "\n" + mine;
    }
    return w;
}

// With parity off: the derivative from the merged matrix against the one summed term by
// term, a copy's against its system's, and a run that ends where the parity run ends.
static void quick(const std::string& name, const Json& model, const Worked& exact) {
    auto project = std::make_shared<const Project>(model);
    auto system = std::make_shared<System>(project);
    System& fast = *system;
    std::vector<double> y0 = fast.initial_state();
    fast.prime_recorders(fast.start_time, y0);
    System copy = fast.clone();
    double times[3] = {fast.start_time, fast.start_time + 0.37 * (fast.end_time - fast.start_time), fast.end_time};
    std::vector<std::vector<double>> ys = states(y0);
    for (std::size_t k = 0; k < exact.dy.size(); k++) {
        std::vector<double> dy, again;
        try {
            dy = fast.dydt(times[k], ys[k]);
            again = copy.dydt(times[k], ys[k]);
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + ": the derivative " + std::to_string(k + 1) + " is refused with parity off: " + e.what());
            break;
        }
        bool close = true, same = true;
        double scale = 0;
        for (double v : exact.dy[k])
            if (std::isfinite(v)) scale = std::max(scale, std::fabs(v));
        for (std::size_t i = 0; i < dy.size(); i++) {
            double want = exact.dy[k][i];
            if (std::isnan(want) || std::isinf(want)) continue;
            if (!(std::fabs(dy[i] - want) <= 1e-9 * std::max(scale, 1e-300))) close = false;
            if (!check::same_bits(dy[i], again[i])) same = false;
        }
        CHECK_MSG(close, name + ": the merged derivative " + std::to_string(k + 1) + " is not the summed one");
        CHECK_MSG(same, name + ": a copy's derivative " + std::to_string(k + 1) + " differs from its system's");
    }
    if (!exact.ran || exact.end.empty()) return;
    try {
        Results res = run_project(project, system);
        const std::vector<double>& end = res.y.back();
        double scale = 0;
        for (double v : exact.end) scale = std::max(scale, std::fabs(v));
        bool close = end.size() == exact.end.size();
        for (std::size_t i = 0; close && i < end.size(); i++)
            if (!(std::fabs(end[i] - exact.end[i]) <= 1e-4 * std::max(scale, 1e-300))) close = false;
        CHECK_MSG(close, name + ": with parity off the run ends elsewhere");
    } catch (const std::exception& e) {
        CHECK_MSG(false, name + ": with parity off the run fails: " + e.what());
    }
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/farfield.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    // (Says what it is at, for a failure that takes the program with it.)
    const bool trace = std::getenv("KOMPARTMENT_TEST_TRACE") != nullptr;

    long calls = 0;
    for (const Json& row : fx.get("helpers").arr()) {
        std::vector<double> x;
        std::vector<int> n;
        std::vector<std::string> s;
        for (const Json& v : row.get("x").arr()) x.push_back(unbits(v.as_string()));
        for (const Json& v : row.get("n").arr()) n.push_back(static_cast<int>(v.as_int()));
        for (const Json& v : row.get("s").arr()) s.push_back(v.as_string());
        const std::string& fn = row.get("fn").as_string();
        if (trace) std::fprintf(stderr, "%ld %s\n", calls, fn.c_str());
        std::string got = helper(fn, x, n, s);
        const std::string& want = row.get("out").as_string();
        if (got != want) {
            std::string args;
            for (double v : x) args += (args.empty() ? "" : ", ") + check::bits(v);
            for (int v : n) args += (args.empty() ? "" : ", ") + std::to_string(v);
            CHECK_MSG(false, fn + "(" + args.substr(0, 300) + ") is\n    " + got.substr(0, 300) + "\n  and Julia's\n    " + want.substr(0, 300));
        } else {
            CHECK(true);
        }
        calls++;
    }

    std::vector<std::string> skipped;
    long models = 0, refused = 0;
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        const Json& model = row.get("model");
        const JObject& want = row.get("values").obj();
        if (trace) std::fprintf(stderr, "%s\n", name.c_str());
        try {
            set_parity(true);
            Worked w;
            try {
                w = sections(model);
            } catch (const BuildError& e) {
                w.out.clear();
                w.out["refused"] = std::string("build: ") + e.what();
            } catch (const ValidationError& e) {
                w.out.clear();
                w.out["refused"] = std::string("model: ") + e.what();
            }
            if (dumps && *dumps) {
                std::ofstream f(std::string(dumps) + "/" + name + ".farfield.cpp.txt");
                bool first = true;
                for (auto [k, v] : w.out) {
                    if (k == "a copy runs alike") continue;
                    for (char& ch : v)
                        if (ch == ',') ch = '\n';
                    f << (first ? "" : "\n") << "## " << k << "\n" << v;
                    first = false;
                }
            }
            for (const auto& [key, value] : want) {
                auto it = w.out.find(key);
                if (it == w.out.end()) {
                    CHECK_MSG(false, name + ": " + key + " is not worked out here; Julia's is " + value.as_string().substr(0, 300));
                    continue;
                }
                std::string got = kept(it->second);
                if (got == value.as_string()) {
                    CHECK(true);
                } else if (got[0] == '=' || value.as_string()[0] == '=') {
                    CHECK_MSG(false, name + ": " + key + " is\n    " + it->second.substr(0, 600) + "\n  and Julia's\n    " + value.as_string().substr(0, 600));
                } else {
                    CHECK_MSG(false, name + ": " + key + " differs");
                }
            }
            for (const auto& [key, value] : w.out)
                if (key != "a copy runs alike") CHECK_MSG(want.has(key), name + ": " + key + " is worked out here and not by Julia: " + value.substr(0, 300));
            if (w.out.count("refused")) {
                refused++;
                continue;
            }
            models++;
            CHECK_MSG(w.out["a copy runs alike"] == "yes", name + ": a copy of the system runs otherwise: " + w.out["a copy runs alike"].substr(0, 600));
            set_parity(false);
            quick(name, model, w);
        } catch (const NotSupported&) {
            skipped.push_back(name);
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    set_parity(false);
    std::printf("%ld helper calls, %ld models worked out, %ld refused as Julia refuses them\n", calls, models, refused);
    if (!skipped.empty()) std::printf("not built here yet (%zu): %s\n", skipped.size(), joined(skipped, ", ").c_str());
    return check::summary("test_farfield");
}
