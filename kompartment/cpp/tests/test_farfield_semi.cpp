// Far-field paths worked out semi-analytically (src/engine/farfield_semi.*) against the Julia
// engine's, with parity on (tools/farfield_semi_fixtures.jl writes
// tests/fixtures/farfield_semi.json).
//
// Models made up to reach every branch of the runtime, each worked through as the tool works
// it: the paths as laid out and their unit responses, the series they report, the derivative
// and every slot at a few instants, a history recorded step by step with the convolvers it
// leaves, the Jacobian, whole runs with the warnings they give, and a run on settings changed
// under the system -- each text Julia's, or the refusal in Julia's words. Then, without Julia:
// a copy of a system runs as its system does, and with parity off the derivative is within a
// hair of the parity one and a run ends where the parity run ends.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/farfield.hpp"
#include "engine/farfield_semi.hpp"
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
static std::string nums(std::initializer_list<double> v) { return nums(std::vector<double>(v)); }
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

static std::vector<std::vector<double>> states(const std::vector<double>& y0) {
    std::size_t n = y0.size();
    std::vector<std::vector<double>> out(3, y0);
    for (std::size_t i = 1; i <= n; i++) {
        out[1][i - 1] = y0[i - 1] * (1.0 + 0.25 * static_cast<double>((i * 7) % 5)) + 0.5 * static_cast<double>((i * 3) % 4);
        out[2][i - 1] = std::fabs(y0[i - 1]) * 0.3 + 1e-3 * static_cast<double>(i);
    }
    return out;
}

static const LaplaceFarfPath* semi_of(const std::shared_ptr<FarfieldPath>& F) { return dynamic_cast<const LaplaceFarfPath*>(F.get()); }

static std::string layout_text(const std::shared_ptr<FarfieldPath>& path) {
    const LaplaceFarfPath* F = semi_of(path);
    if (!F) return "cells";
    std::string D = "none";
    if (F->D) D = nums(F->D->lam) + "/" + ints(F->D->ioff) + "/" + ints(F->D->icnt) + "/" + ints(F->D->ipar) + "/" + nums(F->D->icoef);
    std::vector<std::string> single(F->is_single.begin(), F->is_single.end());
    return "base=" + std::to_string(F->base) + " nnuc=" + std::to_string(F->nnuc) + " other_width=" + std::to_string(F->other_width) +
           " release_base=" + std::to_string(F->release_base) + " surface=" + F->surface + " slots=" + std::to_string(F->nslots) +
           " span=" + nums({F->span}) + " block=" + F->block_name + "\nkeys=" + joined(F->keys, ",") + "\nsingle=" + joined(single, ",") +
           "\ndim_off=" + ints(F->dim_off) + "\nsingle_off=" + ints(F->single_off) + "\nrelease=" + ints(F->release_slots_) +
           "\nheld=" + ints(F->held_idx_) + "\nstarts=" + ints(F->cell_starts_) + "\nnames=" + (F->names ? joined(*F->names, ",") : "-") +
           "\ndecay=" + D + "\nin=" + ints(F->in_tgt) + "|" + ints(F->in_rate) + "|" + ints(F->in_donor) + "\nsettings=" + ints(F->setting_slots());
}

static std::string responses_text(const std::shared_ptr<FarfieldPath>& path) {
    const LaplaceFarfPath* F = semi_of(path);
    if (!F) return "cells";
    std::vector<std::string> lines;
    for (std::size_t o = 0; o < F->combos.size(); o++) {
        const auto& combo = F->combos[o];
        if (!combo) {
            lines.push_back("combination " + std::to_string(o + 1) + ": none");
            continue;
        }
        lines.push_back("combination " + std::to_string(o + 1) + ": pairs=" + std::to_string(combo->pairs));
        for (const auto& m : combo->misses)
            lines.push_back("missed " + std::to_string(m.i) + " " + std::to_string(m.j) + " " + nums({m.integral, m.expected, m.T0, m.rel, m.until}));
        for (std::size_t q = 0; q < combo->kernels.size(); q++) {
            const auto& k = combo->kernels[q];
            if (!k) continue;
            lines.push_back("kernel " + std::to_string(q) + " n=" + std::to_string(k->n) + " np=" + std::to_string(k->np) + " " +
                            nums({k->t0, k->t_end, k->m0, k->tm0}) + " " + fnv(joined({nums(k->t), nums(k->a), nums(k->d), nums(k->ahead), nums(k->P)}, "|")));
        }
    }
    return joined(lines, "\n");
}

static std::string convolver_text(const Convolver& cv) {
    std::vector<double> bm;
    for (const auto& m : cv.bm) bm.insert(bm.end(), m.begin(), m.end());
    std::vector<std::string> bp;
    for (const auto& p : cv.bp) bp.push_back(p ? nums(*p) : std::string("-"));
    return "n=" + std::to_string(cv.bc.size()) + " at=" + std::to_string(cv.compact_at) + " count=" + std::to_string(cv.count) + " last=" +
           nums({cv.last_t}) + " rt=" + nums(cv.rt) + " rv=" + nums(cv.rv) + " imp=" + nums(cv.imp_t) + "/" + nums(cv.imp_a) + " ti=" + ints(cv.ti) + " " +
           fnv(joined({nums(cv.bc), nums(cv.bw), nums(bm), joined(bp, ";")}, "|"));
}

// Julia's isless on numbers: NaN after everything, -0 before 0.
static bool jl_isless(double a, double b) {
    if (std::isnan(b)) return !std::isnan(a);
    if (std::isnan(a)) return false;
    if (a == b) return std::signbit(a) && !std::signbit(b);
    return a < b;
}

static std::string history_text(const std::shared_ptr<FarfieldPath>& path) {
    const LaplaceFarfPath* F = semi_of(path);
    if (!F) return "cells";
    std::vector<std::string> lines;
    lines.push_back("records=" + std::to_string(F->rec_t.size()) + " " + fnv(nums(F->rec_t)) + " last=" + nums({F->last_t}) + " ready=" + yes(F->ready));
    for (int s = 0; s < F->nslots; s++)
        lines.push_back("slot " + std::to_string(s) + " " + fnv(nums(F->rec_v[s])) + " imp=" + nums(F->imp_t[s]) + "/" + nums(F->imp_v[s]));
    std::vector<std::pair<double, const std::vector<double>*>> ks;
    for (const auto& [key, v] : F->releases) {
        double x;
        std::memcpy(&x, &key, 8);
        ks.push_back({x, &v});
    }
    std::sort(ks.begin(), ks.end(), [](const auto& a, const auto& b) { return jl_isless(a.first, b.first); });
    std::vector<std::string> rel;
    for (const auto& [k, v] : ks) rel.push_back(nums({k}) + ":" + nums(*v));
    lines.push_back("releases=" + std::to_string(ks.size()) + " " + fnv(joined(rel, ";")));
    if (!F->live) {
        lines.push_back("live none");
    } else {
        for (const Convolver& cv : *F->live) lines.push_back(convolver_text(cv));
    }
    return joined(lines, "\n");
}
static std::string histories_text(const System& sys) {
    std::vector<std::string> parts;
    for (const auto& F : sys.data.FARF) parts.push_back(history_text(F));
    return joined(parts, "\n--\n");
}

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

static std::string run_text(Results& res) {
    std::vector<std::string> counts;
    for (const char* key : {"nsteps", "nfailed", "nfevals", "events", "jumps", "restarts"})
        if (res.stats.has(key)) counts.push_back(std::string(key) + "=" + js_text(res.stats.get(key)));
    std::vector<std::string> said;
    for (const char* key : {"farfield", "layers"})
        if (res.stats.get(key).is_array())
            for (const Json& w : res.stats.get(key).arr()) said.push_back(w.get("block").as_string() + ": " + w.get("message").as_string());
    return "points=" + std::to_string(res.t.size()) + " " + joined(counts, " ") + " csv=" + fnv(res.to_csv()) + "\n" + joined(said, "\n");
}

static std::string audit_text(const Json& a) {
    std::vector<std::string> lines;
    lines.push_back("worst=" + nums({a.get("worst").as_double()}) + " at=" + nums({a.get("at").as_double()}) + " family=" +
                    (a.get("worstFamily").is_null() ? std::string("-") : a.get("worstFamily").as_string()) + " closed=" + yes(a.get("closed").as_bool()));
    for (const Json& f : a.get("families").arr())
        lines.push_back(f.get("name").as_string() + " idle=" + yes(f.get("idle").as_bool()) + " scale=" + nums({f.get("scale").as_double()}) + " worst=" +
                        nums({f.get("worst").as_double()}) + " relative=" + nums({f.get("relative").as_double()}) + " at=" + nums({f.get("at").as_double()}));
    const Json& total = a.get("total");
    lines.push_back("total scale=" + nums({total.get("scale").as_double()}) + " worst=" + nums({total.get("worst").as_double()}) + " relative=" +
                    nums({total.get("relative").as_double()}) + " at=" + nums({total.get("at").as_double()}));
    return joined(lines, "\n");
}

static std::string releases_text(System& sys, double t) {
    std::vector<std::string> parts;
    for (const auto& path : sys.data.FARF) {
        auto* F = dynamic_cast<LaplaceFarfPath*>(path.get());
        if (!F) continue;
        std::vector<double> rel;
        for (int s : F->release_slots_) rel.push_back(sys.X[static_cast<std::size_t>(s)]);
        std::string text = nums(rel);
        parts.push_back(text + " w=" + nums(F->current_weights(t)));
    }
    return joined(parts, " / ");
}

using Out = std::map<std::string, std::string>;

static void history_sections(Out& out, const std::shared_ptr<const Project>& project) {
    System sys(project);
    std::vector<double> y0 = sys.initial_state();
    sys.prime_recorders(sys.start_time, y0);
    double span = sys.end_time - sys.start_time;
    std::size_t n = y0.size();
    auto state = [&](int k) {
        std::vector<double> y(n);
        for (std::size_t i = 1; i <= n; i++)
            y[i - 1] = y0[i - 1] * (1.0 + 0.01 * k) + 1e-3 * static_cast<double>((static_cast<int>(i) * 7 + k) % 5) +
                       0.05 * k * ((i % 3) == 0 ? 1.0 : 0.0);
        return y;
    };
    std::vector<double> times(91, 0.0);
    for (int k = 1; k <= 90; k++) {
        double x = static_cast<double>(k) / 90;
        times[k] = sys.start_time + span * (x * x * x);
    }
    std::vector<std::string> lines;
    std::string refused = or_refusal([&]() {
        for (int k = 1; k <= 90; k++) {
            double t = times[k];
            std::vector<double> y = state(k);
            if (k == 30) {
                sys.store_step(t, y.data());
                std::vector<double> y2 = y;
                for (const auto& path : sys.data.FARF) {
                    const LaplaceFarfPath* F = semi_of(path);
                    if (!F) continue;
                    for (int s : F->held_idx_) y2[s] += 0.25 * (1 + std::fabs(y2[s]));
                }
                sys.store_step(t, y2.data());
                lines.push_back("twice " + std::to_string(k) + ": " + releases_text(sys, t));
                continue;
            }
            if (k == 50) {
                std::vector<double> y40 = state(40);
                sys.evaluate_algebraic(times[40], y40.data());
                lines.push_back("behind " + std::to_string(k) + ": " + releases_text(sys, times[40]));
                std::vector<double> y44 = state(44);
                double mid = 0.5 * (times[44] + times[45]);
                sys.evaluate_algebraic(mid, y44.data());
                lines.push_back("between " + std::to_string(k) + ": " + releases_text(sys, mid));
            }
            if (k == 70) {
                std::vector<double> y65 = state(65);
                sys.store_step(times[65], y65.data());
                lines.push_back("earlier " + std::to_string(k) + ": " + releases_text(sys, times[65]));
            }
            sys.store_step(t, y.data());
            if (k % 9 == 0) {
                double ahead = t + 0.3 * (times[std::min(k + 1, 90)] - t) + 1e-9 * span;
                std::vector<double> yn = state(k + 1);
                sys.evaluate_algebraic(ahead, yn.data());
                lines.push_back("ahead " + std::to_string(k) + ": " + releases_text(sys, ahead));
                std::vector<double> dy = sys.dydt(ahead, yn);
                lines.push_back("dy " + std::to_string(k) + ": " + nums(dy));
            }
        }
        return std::string();
    });
    if (!refused.empty()) {
        out["history steps"] = joined(lines, "\n") + "\n" + refused;
        return;
    }
    out["history steps"] = joined(lines, "\n");
    out["history"] = histories_text(sys);
    System C = sys.clone();
    double t = times[90] * 1.01;
    std::vector<double> y91 = state(91);
    std::vector<double> a = sys.evaluate_algebraic(t, y91.data());
    std::vector<double> b = C.evaluate_algebraic(t, y91.data());
    out["history copied"] = std::string(nums(a) == nums(b) ? "alike " : "otherwise ") + histories_text(C);
}

struct Worked {
    Out out;
    std::vector<std::vector<double>> dy;
    std::vector<double> end;
    bool ran = false;
};

static Worked sections(const Json& model, const Json& changed) {
    Worked w;
    Out& out = w.out;
    Json numeric = model.copy();
    if (!numeric.get("simulation").is_object()) numeric.set("simulation", Json::object());
    numeric["simulation"].set("jacobian", Json("numeric"));
    auto project = std::make_shared<const Project>(model);
    {
        System sys(project);
        std::vector<std::string> parts, resp;
        for (const auto& F : sys.data.FARF) {
            parts.push_back(layout_text(F));
            resp.push_back(responses_text(F));
        }
        out["layout"] = joined(parts, "\n--\n");
        out["responses"] = joined(resp, "\n--\n");
        std::vector<std::string> said;
        for (const Json& x : farfield_warnings(sys).farfield) said.push_back(x.get("block").as_string() + ": " + x.get("message").as_string());
        out["warnings"] = joined(said, "\n");
        out["outputs"] = outputs_text(sys, *project);
        std::vector<double> y0 = sys.initial_state();
        out["y0"] = nums(y0);
        sys.prime_recorders(sys.start_time, y0);
        out["primed"] = histories_text(sys);
        double times[3] = {sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time};
        std::vector<std::vector<double>> ys = states(y0);
        for (int k = 0; k < 3; k++) {
            std::string at = std::to_string(k + 1);
            std::string refused = or_refusal([&]() {
                std::vector<double> X = sys.evaluate_algebraic(times[k], ys[static_cast<std::size_t>(k)].data());
                std::vector<double> dy = sys.dydt(times[k], ys[static_cast<std::size_t>(k)]);
                out["X" + at] = nums(X);
                out["dy" + at] = nums(dy);
                w.dy.push_back(dy);
                return std::string();
            });
            if (!refused.empty()) {
                out["X" + at] = refused;
                break;
            }
        }
    }
    history_sections(out, project);
    {
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
            double fs[3] = {1e-3, 1e-2, 3e-2};
            for (int q = 1; q <= 3; q++) {
                std::vector<double> y = y0;
                for (double& v : y) v = v * (1 + 0.1 * q);
                sys.store_step(sys.start_time + fs[q - 1] * (sys.end_time - sys.start_time), y.data());
            }
            double times[3] = {sys.start_time, sys.start_time + 0.37 * (sys.end_time - sys.start_time), sys.end_time};
            std::vector<std::vector<double>> ys = states(y0);
            for (int k = 0; k < 3; k++) {
                Vec Jv(j->pattern->nnz(), 0.0);
                double floor_t = sys.start_time + 0.05 * (sys.end_time - sys.start_time);
                double tt = times[k] > floor_t ? times[k] : floor_t;
                out["J" + std::to_string(k + 1)] = or_refusal([&]() {
                    bool ok = analytic_evaluate(Jv, *an, tt, ys[static_cast<std::size_t>(k)]);
                    return std::string(ok ? "1" : "0") + ":" + nums(Jv) + "|" + nums(analytic_gradients(*an));
                });
            }
        }
    }
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
    out["history after"] = histories_text(sys);
    out["run again"] = or_refusal([&]() {
        Results res = run_project(project, system);
        return run_text(res);
    });
    // A copy of the system runs as its system does.
    {
        auto copy = std::make_shared<System>(sys.clone());
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
    if (!changed.is_null()) {
        const std::string& name = changed.arr()[0].as_string();
        double value = unbits(changed.arr()[1].as_string());
        const EntryPtr& e = sys.builder->param_by_name.at(name);
        for (int q = 0; q < e->width; q++) sys.P[static_cast<std::size_t>(e->base + q)] = value;
        sys.evaluate_invariant();
        out["run changed"] = or_refusal([&]() {
            Results res = run_project(project, system);
            return run_text(res);
        });
    }
    return w;
}

// With parity off: the derivative within a hair of the parity one, a copy's the same as its
// system's, and a run that ends where the parity run ends.
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
        CHECK_MSG(close, name + ": the derivative " + std::to_string(k + 1) + " with parity off is not the parity one");
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
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/farfield_semi.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const bool trace = std::getenv("KOMPARTMENT_TEST_TRACE") != nullptr;
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
                w = sections(model, row.get("changed"));
            } catch (const BuildError& e) {
                w.out.clear();
                w.out["refused"] = std::string("build: ") + e.what();
            } catch (const ValidationError& e) {
                w.out.clear();
                w.out["refused"] = std::string("model: ") + e.what();
            }
            if (dumps && *dumps) {
                std::ofstream f(std::string(dumps) + "/" + name + ".semi.cpp.txt");
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
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    set_parity(false);
    std::printf("%ld models worked out, %ld refused as Julia refuses them\n", models, refused);
    return check::summary("test_farfield_semi");
}
