// The exact Jacobian against the Julia engine's, with parity on
// (tools/jacobian_fixtures.jl writes tests/fixtures/jacobian.json): whether a
// model has one, constant or free of the state, and why not; its pattern and
// colouring; the plan made of it directly; and the values the plan writes at a
// few instants and states, with the gradients of the slots they are assembled
// from, to the bit. Then, without Julia: the values by the
// walk over each statement's tree against those from the trees laid out flat,
// a copy of the system against its original, and the values against central
// differences of the derivative wherever those say the derivative is smooth.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/jacobian_analytic.hpp"
#include "engine/system.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

static std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
static std::string nums(const std::vector<double>& v) {
    std::string s;
    for (double x : v) {
        if (!s.empty()) s += ",";
        s += bits(x);
    }
    return s;
}
template <class V>
static std::string ints(const V& v) {
    std::string s;
    for (auto x : v) {
        if (!s.empty()) s += ",";
        s += std::to_string(x);
    }
    return s;
}
static const char* yes(bool b) { return b ? "true" : "false"; }

struct Point {
    double t;
    std::vector<double> y;
};

// Where the Jacobian is asked for: the initial state at the start, two states made from it
// at later instants, and -- after the second has been recorded as a step taken -- the
// initial one again at another instant.
static std::vector<Point> points(const System& sys, const std::vector<double>& y0) {
    std::size_t n = y0.size();
    double t0 = sys.start_time, t1 = sys.end_time;
    std::vector<Point> out = {{t0, y0}, {t0 + 0.37 * (t1 - t0), y0}, {t1, y0}, {t0 + 0.6 * (t1 - t0), y0}};
    for (std::size_t i = 1; i <= n; i++) {
        out[1].y[i - 1] = y0[i - 1] * (1.0 + 0.25 * static_cast<double>((i * 7) % 5)) + 0.5 * static_cast<double>((i * 3) % 4);
        out[2].y[i - 1] = std::fabs(y0[i - 1]) * 0.3 + 1e-3 * static_cast<double>(i);
    }
    return out;
}

// The analytic values against central differences of the derivative at `(t, y)`: an entry
// is compared where two differences, one over half the other's step, agree with each other
// -- the derivative is smooth there -- and every entry must be when the model is said to be
// smooth. How many entries were compared, and how many there are.
static std::pair<long, long> against_differences(const std::string& name, System& sys, Analytic& an, const Pattern& pattern, double t,
                                                 const std::vector<double>& y, bool smooth, bool full) {
    std::size_t n = y.size();
    Vec J(pattern.nnz(), 0.0);
    if (!analytic_evaluate(J, an, t, y)) {
        CHECK_MSG(!smooth, name + ": a smooth model's Jacobian is not finite where it is differenced");
        return {0, static_cast<long>(pattern.nnz())};
    }
    // The audit's rows at their diagonal are left out of the pattern on purpose.
    std::vector<char> partial(n, 0);
    if (sys.builder->budget && !full) {
        int from = sys.builder->budget->base, to = from + static_cast<int>(sys.builder->budget->terms.size()) * sys.builder->budget->nfam;
        for (int r = from; r < to; r++) partial[static_cast<std::size_t>(r)] = 1;
    }
    const double eps = 2.220446049250313e-16;
    long compared = 0, total = 0;
    bool agree = true, structure = true, all_smooth = true;
    std::string worst;
    std::vector<double> yp = y;
    for (std::size_t c = 0; c < n; c++) {
        double h = std::cbrt(eps) * std::max(std::fabs(y[c]), 1e-3);
        std::vector<double> f[4];
        double steps[4] = {h, -h, 0.5 * h, -0.5 * h};
        for (int k = 0; k < 4; k++) {
            yp[c] = y[c] + steps[k];
            f[k] = sys.dydt(t, yp);
        }
        yp[c] = y[c];
        std::vector<char> in_pattern(n, 0);
        for (I32 q = pattern.colptr[c]; q < pattern.colptr[c + 1]; q++) in_pattern[static_cast<std::size_t>(pattern.rowval[static_cast<std::size_t>(q)])] = 1;
        I32 q = pattern.colptr[c];
        for (std::size_t r = 0; r < n; r++) {
            double fd1 = (f[0][r] - f[1][r]) / (2 * h);
            double fd2 = (f[2][r] - f[3][r]) / h;
            double noise = 256 * eps * (std::fabs(f[0][r]) + std::fabs(f[1][r]) + std::fabs(f[2][r]) + std::fabs(f[3][r])) / h + 1e-300;
            bool is_smooth = std::fabs(fd1 - fd2) <= 1e-6 * std::max(std::fabs(fd1), std::fabs(fd2)) + noise;
            if (!in_pattern[r]) {
                // Outside the pattern nothing may depend on this state.
                if (smooth && !partial[r] && !(is_smooth && std::fabs(fd2) <= noise)) structure = false;
                continue;
            }
            double exact = J[static_cast<std::size_t>(q++)];
            total++;
            if (!is_smooth) {
                all_smooth = false;
                continue;
            }
            compared++;
            if (!(std::fabs(exact - fd2) <= 1e-5 * std::max(std::fabs(exact), std::fabs(fd2)) + 4 * noise)) {
                if (agree) worst = " (row " + std::to_string(r) + ", column " + std::to_string(c) + ": " + check::bits(exact) + " against " + check::bits(fd2) + ")";
                agree = false;
            }
        }
    }
    CHECK_MSG(agree, name + ": the exact Jacobian is not the differenced one" + worst);
    if (smooth) {
        CHECK_MSG(all_smooth, name + ": said to be smooth, and the differences say otherwise");
        CHECK_MSG(structure, name + ": the derivative depends on a state outside the pattern");
    }
    return {compared, total};
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/jacobian.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    std::vector<std::string> skipped;
    long exact_models = 0, refused = 0, compared = 0, entries = 0, values = 0;
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        bool smooth = row.has("smooth") && row.get("smooth").as_bool();
        try {
            auto project = std::make_shared<const Project>(model);
            set_parity(true);
            System sys(project);
            std::map<std::string, std::string> out;
            std::string info, plan;
            const std::shared_ptr<JacobianInfo>& j = sys.jacobian;
            std::shared_ptr<Analytic> an;
            bool full = false;
            if (!j->pattern) {
                info = "none: " + j->reason.value_or("");
            } else {
                info = std::string("available=") + yes(j->available) + " constant=" + yes(j->constant) + " state_free=" +
                       (j->analytic ? yes(analytic_state_free(*j->analytic)) : "-") + " reason=" + j->reason.value_or("") + " budget_rows=" +
                       j->budget_rows.value_or("") + " nnz=" + std::to_string(j->nnz) + " colours=" + std::to_string(j->colours);
                out["pattern"] = ints(j->pattern->colptr) + "|" + ints(j->pattern->rowval);
                std::string groups;
                for (std::size_t g = 0; g < j->groups->size(); g++) groups += (g ? "|" : "") + ints((*j->groups)[g]);
                out["groups"] = groups;
                full = full_budget(sys);
                try {
                    an = make_analytic(sys, *j->pattern, full);
                    plan = std::string("constant=") + yes(analytic_constant(*an)) + " state_free=" + yes(analytic_state_free(*an)) +
                           " rows=" + std::to_string(analytic_gradient_rows(*an)) + " entries=" + std::to_string(analytic_gradient_entries(*an));
                    exact_models++;
                } catch (const NoDerivative& e) {
                    plan = std::string("refused: ") + e.what();
                    refused++;
                }
            }
            CHECK_MSG(info == row.get("info").as_string(), name + ": the Jacobian is said to be\n    " + info + "\n  and Julia's\n    " + row.get("info").as_string());
            if (row.has("plan") || !plan.empty())
                CHECK_MSG(row.has("plan") && plan == row.get("plan").as_string(),
                          name + ": the plan is\n    " + plan + "\n  and Julia's\n    " + (row.has("plan") ? row.get("plan").as_string() : "none"));
            if (an) {
                std::vector<double> y0 = sys.initial_state();
                sys.prime_recorders(sys.start_time, y0);
                std::vector<Point> at = points(sys, y0);
                Vec J(j->pattern->nnz(), 0.0), walked(j->pattern->nnz(), 0.0);
                for (std::size_t k = 0; k < at.size(); k++) {
                    std::string key = "J" + std::to_string(k + 1);
                    try {
                        bool ok = analytic_evaluate(J, *an, at[k].t, at[k].y);
                        // (The gradients of the slots too: an entry of the Jacobian is a sum over many
                        // of them, and a last bit lost in one is seldom seen in the sum.)
                        std::string gradients = nums(analytic_gradients(*an));
                        out["G" + std::to_string(k + 1)] = gradients;
                        out[key] = std::string(ok ? "1" : "0") + ":" + nums(J);
                        values += static_cast<long>(J.size() + analytic_gradients(*an).size());
                        // The walk over the trees gives what the trees laid out flat give.
                        bool ok2 = analytic_evaluate_walked(walked, *an, at[k].t, at[k].y);
                        CHECK_MSG(ok == ok2 && nums(J) == nums(walked) && gradients == nums(analytic_gradients(*an)),
                                  name + ": " + key + " by the walk differs from the tape's");
                    } catch (const std::exception&) {
                        out[key] = "threw";
                    }
                    if (k == 1) sys.store_step(at[k].t, at[k].y.data());
                }
                // A copy has a plan of its own that reads the copy, and gives the same values.
                if (j->analytic) {
                    System copy = sys.clone();
                    CHECK_MSG(copy.jacobian && copy.jacobian->analytic && copy.jacobian->analytic != j->analytic, name + ": a copy shares its system's plan");
                    if (copy.jacobian && copy.jacobian->analytic) {
                        CHECK_MSG(analytic_system(*copy.jacobian->analytic) == &copy, name + ": a copy's plan reads another system");
                        CHECK_MSG(analytic_system(*j->analytic) == &sys, name + ": a system's plan reads another system");
                        Vec mine(J.size(), 0.0), its(J.size(), 0.0);
                        bool ok1 = analytic_evaluate(mine, *j->analytic, at[2].t, at[2].y);
                        bool ok2 = analytic_evaluate(its, *copy.jacobian->analytic, at[2].t, at[2].y);
                        CHECK_MSG(ok1 == ok2 && nums(mine) == nums(its), name + ": a copy's Jacobian differs from its system's");
                        // A parameter changed in the copy moves the copy's values alone.
                        if (!copy.P.empty()) {
                            for (double& p : copy.P) p = p * 1.5 + 0.25;
                            copy.evaluate_invariant();
                            copy.clock_at = std::numeric_limits<double>::quiet_NaN();
                            analytic_evaluate(its, *copy.jacobian->analytic, at[2].t, at[2].y);
                            Vec again(J.size(), 0.0);
                            sys.clock_at = std::numeric_limits<double>::quiet_NaN();
                            analytic_evaluate(again, *j->analytic, at[2].t, at[2].y);
                            CHECK_MSG(nums(mine) == nums(again), name + ": a copy's parameters moved its system's Jacobian");
                        }
                    }
                }
                auto [c, e] = against_differences(name, sys, *an, *j->pattern, at[2].t, at[2].y, smooth, full);
                compared += c;
                entries += e;
            }
            if (dumps && *dumps) {
                std::ofstream f(std::string(dumps) + "/" + name + ".jacobian.cpp.txt");
                f << "## info\n" << info << "\n## plan\n" << plan << "\n";
                for (auto [k, v] : out) {
                    for (char& ch : v)
                        if (ch == ',') ch = '\n';
                    f << "## " << k << "\n" << v << "\n";
                }
            }
            for (const auto& [key, hash] : row.get("values").obj()) CHECK_MSG(fnv(out[key]) == hash.as_string(), name + ": " + key + " differs");
            CHECK_MSG(out.size() == row.get("values").obj().size(), name + ": more is worked out here than Julia works out");
        } catch (const NotSupported&) {
            skipped.push_back(name);
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    set_parity(false);
    std::printf("%ld plans made, %ld refused; %ld values compared with Julia's; %ld of %ld entries compared with differences\n", exact_models, refused,
                values, compared, entries);
    if (!skipped.empty()) {
        std::string names;
        for (const auto& s : skipped) names += (names.empty() ? "" : ", ") + s;
        std::printf("not built here yet (%zu): %s\n", skipped.size(), names.c_str());
    }
    return check::summary("test_jacobian");
}
