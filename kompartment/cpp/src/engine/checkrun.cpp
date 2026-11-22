// Check the run (see checkrun.hpp): a port of the Julia package's engine/checkrun.jl,
// operation for operation.

#include "engine/checkrun.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <optional>
#include <unordered_map>

#include "engine/builder.hpp"
#include "engine/farfield_domain.hpp"
#include "stats/gsa_design.hpp"
#include "stats/pdf.hpp"
#include "util/errors.hpp"

namespace kompartment {

namespace {

constexpr double Inf = std::numeric_limits<double>::infinity();
constexpr int MOST_NAMED = 6;

/// The solvers whose own step budget is ten million (`PORTED_IDS`, `auto` aside).
const char* const TEN_MILLION[] = {"dp45", "auto_julia", "rodas5p", "radau5", "fbdf", "fbdf_krylov", "qndf", "kencarp4", "trbdf2",
                                   "rosenbrock23", "tsit5", "vern7"};

/// `v != null && v !== ''`.
bool is_set(const Json* v) { return v != nullptr && !v->is_null() && !(v->is_string() && v->as_string().empty()); }

double now_s() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

/// The index of the time in `t` nearest `want`, `t` sorted.
std::size_t nearest(const std::vector<double>& t, double want) {
    std::size_t lo = 0;
    std::size_t hi = t.size() - 1;
    while (hi - lo > 1) {
        const std::size_t mid = (lo + hi) >> 1;
        if (t[mid] <= want)
            lo = mid;
        else
            hi = mid;
    }
    return std::fabs(t[hi] - want) < std::fabs(t[lo] - want) ? hi : lo;
}

/// A block's or an entry's own absolute tolerance, a hundred times tighter where it is a
/// positive number.
void tighten_own(Json& holder) {
    const Json* own = pd_prop(holder, "abstol");
    const double n = pd_to_number(own);
    if (is_set(own) && std::isfinite(n) && n > 0) holder.set("abstol", Json(n / CHECK_CAREFUL));
}

/// `model.simulation.max_steps ?? solverDefault('max_steps', id).value ?? null`, `id` the run's
/// solver (`_cr_max_steps`).
Json max_steps_of(const Json& model, const Json& solver) {
    const Json& sim = model.get("simulation");
    const Json& given = sim.is_object() ? sim.get("max_steps") : sim;
    if (sim.is_object() && !given.is_null()) return given;
    const std::string id = solver.is_null() ? std::string("ndf") : solver.is_string() ? solver.as_string() : std::string();
    if (solver.is_null() || solver.is_string()) {
        if (id == "auto") return Json();
        for (const char* s : TEN_MILLION)
            if (id == s) return Json(1.0e7);
    }
    return Json(1.0e6);
}

}  // namespace

Tightened tighten_tolerances(Json& model) {
    if (!model.get("simulation").is_object()) model.set("simulation", Json::object());
    Json& sim = model["simulation"];
    const double rtol = pd_to_number(pd_prop(sim, "rtol"));
    const double abstol = pd_to_number(pd_prop(sim, "abstol"));
    const double tighter = pd_jmax(CHECK_RTOL_FLOOR, rtol / CHECK_CAREFUL);
    sim.set("rtol", Json(tighter));
    sim.set("abstol", Json(abstol / CHECK_CAREFUL));
    const Json* given = pd_prop(sim, "max_steps");
    const double steps = pd_to_number(given);
    if (is_set(given) && std::isfinite(steps) && steps > 0) sim.set("max_steps", Json(gsa_round(steps * 10)));
    for (const char* key : {"compartments", "waste_packages"}) {
        if (!model.get(key).is_array()) continue;
        Json& blocks = model[key];
        for (std::size_t b = 0; b < blocks.size(); b++) {
            Json& block = blocks[b];
            if (!block.is_object()) continue;
            tighten_own(block);
            if (!block.get("entries").is_array()) continue;
            Json& entries = block["entries"];
            for (std::size_t e = 0; e < entries.size(); e++)
                if (entries[e].is_object()) tighten_own(entries[e]);
        }
    }
    return Tightened{tighter, abstol / CHECK_CAREFUL, tighter > rtol / CHECK_CAREFUL};
}

std::pair<Json, Tightened> careful_model(const Json& model, const std::vector<double>& times) {
    Json out = model.copy();
    const Tightened tightened = tighten_tolerances(out);
    Json& sim = out["simulation"];
    sim.set("spacing", Json("series"));
    sim.set("output_times", Json::array({Json::object({{"times", Json::array(times)}})}));
    return {out, tightened};
}

std::vector<std::string> state_labels(const System& sys) {
    const Builder& b = *sys.builder;
    const IndexSpace& space = *b.space;
    std::vector<std::optional<std::string>> labels(static_cast<std::size_t>(sys.nstate));
    const auto units = material_units(sys);
    for (const EntryPtr& ep : b.states) {
        const Entry& entry = *ep;
        try {
            if (entry.kind == "farfield" && entry.farf) {
                const FarfLayout& f = *entry.farf;
                std::vector<std::optional<std::string>> names;
                if (f.list_name) {
                    for (const std::string& n : space.index_names(*f.list_name)) names.emplace_back(n);
                } else {
                    names.emplace_back(std::nullopt);
                }
                std::optional<std::vector<std::string>> cells;
                try {
                    cells = cell_names(entry.block);
                } catch (...) {
                    cells.reset();
                }
                for (int o = 0; o < f.other_width; o++) {
                    const std::vector<std::string> others = f.other_dims.empty() ? std::vector<std::string>{} : space.tuple_at(f.other_dims, o);
                    const int base = entry.base + o * f.ncells * f.nnuc;
                    for (int m = 0; m < f.nnuc; m++) {
                        std::vector<std::optional<std::string>> index;
                        std::size_t k = 0;
                        for (const std::string& dim : entry.dims) {
                            if (f.list_name && dim == *f.list_name)
                                index.push_back(names.at(static_cast<std::size_t>(m)));
                            else
                                index.emplace_back(others.at(k++));
                        }
                        std::string suffix;
                        if (!index.empty()) {
                            suffix = " [";
                            for (std::size_t i = 0; i < index.size(); i++) suffix += (i ? ", " : "") + index[i].value_or("");
                            suffix += "]";
                        }
                        for (int cell = 0; cell < f.ncells; cell++) {
                            const std::string name = cells && cell < static_cast<int>(cells->size()) ? (*cells)[static_cast<std::size_t>(cell)]
                                                                                                    : "cell " + std::to_string(cell + 1);
                            labels.at(static_cast<std::size_t>(base + cell * f.nnuc + m)) = entry.name + suffix + " " + name;
                        }
                    }
                }
                continue;
            }
            std::vector<Json> described;
            describe_entry(described, sys, entry, entry.kind, "y", units);
            for (const Json& d : described) labels.at(static_cast<std::size_t>(d.get("offset").as_int())) = d.get("label").as_string();
        } catch (...) {
            for (int i = 0; i < entry.width; i++)
                labels.at(static_cast<std::size_t>(entry.base + i)) = entry.width > 1 ? entry.name + " [" + std::to_string(i) + "]" : entry.name;
        }
    }
    std::vector<std::string> out;
    out.reserve(labels.size());
    for (std::size_t i = 0; i < labels.size(); i++)
        out.push_back(labels[i] && !labels[i]->empty() ? *labels[i] : "state " + std::to_string(i));
    return out;
}

Json compare_runs(const Project& project, const System& sys, const std::vector<double>& ht, const std::vector<Vec>& hy,
                  const std::vector<double>& ct, const std::vector<Vec>& cy) {
    const std::size_t n = static_cast<std::size_t>(sys.nstate);
    const double rtol = pd_to_number(pd_prop(project.simulation, "rtol"));
    const std::vector<double> per_state = absolute_tolerance(project, sys);
    const double fallback = project.simulation.get("abstol").as_double();
    const std::vector<std::string> names = state_labels(sys);
    const std::size_t T = ht.size();
    // Each of the run's times, in the careful run.
    std::vector<std::size_t> at(T, 0);
    bool same = ct.size() == T;
    for (std::size_t k = 0; k < T; k++) {
        at[k] = (same && ct[k] == ht[k]) ? k : nearest(ct, ht[k]);
        if (at[k] != k) same = false;
    }
    std::vector<double> peak(n, 0.0), diff(n, 0.0);
    std::vector<std::size_t> when(n, 0);
    for (std::size_t k = 0; k < T; k++) {
        const Vec& a = hy[k];
        const Vec& b = cy[at[k]];
        for (std::size_t i = 0; i < n; i++) {
            const double x = a[i];
            const double y = b[i];
            // Math.max of the two magnitudes: NaN if either is, and a NaN is never a peak.
            const double big = (std::isnan(x) || std::isnan(y)) ? std::numeric_limits<double>::quiet_NaN() : std::max(std::fabs(x), std::fabs(y));
            if (big > peak[i]) peak[i] = big;
            const double d = std::fabs(x - y);
            // A state that is not a number in one run and is in the other is as far apart as
            // two runs can be.
            if (d > diff[i] || std::isnan(d)) {
                diff[i] = std::isnan(d) ? Inf : d;
                when[i] = k;
            }
        }
    }
    std::vector<double> share(n, 0.0);
    double worst = 0.0;
    for (std::size_t i = 0; i < n; i++) {
        const double floor_ = (per_state.empty() ? fallback : per_state[i]) / rtol;
        const double size = std::max(peak[i], std::isfinite(floor_) ? floor_ : 0.0);
        const double s = size > 0 ? diff[i] / size : (diff[i] > 0 ? Inf : 0.0);
        share[i] = s;
        if (s > worst) worst = s;
    }
    std::vector<std::size_t> moving;
    for (std::size_t i = 0; i < n; i++)
        if (share[i] > 0) moving.push_back(i);
    std::stable_sort(moving.begin(), moving.end(), [&](std::size_t p, std::size_t q) { return share[p] > share[q]; });
    Json moved = Json::array();
    for (std::size_t j = 0; j < moving.size() && j < MOST_NAMED; j++) {
        const std::size_t i = moving[j];
        const std::size_t w = when[i];
        moved.push(Json::object({{"label", Json(i < names.size() ? names[i] : "state " + std::to_string(i))},
                                 {"state", Json(static_cast<long long>(i))},
                                 {"share", Json(share[i])},
                                 {"at", Json(ht[w])},
                                 {"held", Json(hy[w][i])},
                                 {"careful", Json(cy[at[w]][i])}}));
    }
    return Json::object({{"verdict", Json(worst < CHECK_HOLDS ? "holds" : worst < CHECK_NEARLY ? "nearly" : "does not")},
                         {"worst", Json(worst)},
                         {"moved", moved},
                         {"states", Json(static_cast<long long>(n))},
                         {"times", Json(static_cast<long long>(T))},
                         {"sameTimes", Json(same)}});
}

Json check_run(const Results& held, const std::function<Results(std::shared_ptr<const Project>)>& solve, const Json* model) {
    if (held.y.size() != held.t.size())
        throw ArgumentError("The run on show does not carry its states here, so it cannot be set against another.");
    const Json& json = model != nullptr ? *model : held.project->raw;
    auto [careful_json, tightened] = careful_model(json, held.t);
    const double started = now_s();
    const Results careful = solve(std::make_shared<const Project>(careful_json));
    const double ms = (now_s() - started) * 1000;
    Json report = compare_runs(*held.project, *held.system, held.t, held.y, careful.t, careful.y);
    const Json& sim = held.project->simulation;
    report.set("run", Json::object({{"rtol", Json(pd_to_number(pd_prop(sim, "rtol")))},
                                    {"abstol", Json(pd_to_number(pd_prop(sim, "abstol")))},
                                    {"steps", held.stats.get("nsteps")}}));
    report.set("careful", Json::object({{"rtol", Json(tightened.rtol)},
                                        {"abstol", Json(tightened.abstol)},
                                        {"floor", Json(tightened.floor)},
                                        {"ms", Json(ms)},
                                        {"steps", careful.stats.get("nsteps")},
                                        {"maxSteps", max_steps_of(careful_json, sim.get("solver"))}}));
    return report;
}

}  // namespace kompartment
