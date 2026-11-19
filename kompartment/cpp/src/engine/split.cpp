#include "engine/split.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <numeric>
#include <regex>
#include <set>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <variant>

#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

#include "build_stamp.hpp"   // written by tools/build_stamp.cmake: KOMPARTMENT_BUILD_STAMP
#include "engine/builder.hpp"
#include "engine/errorinfo.hpp"
#include "engine/farfield.hpp"
#include "engine/jacobian.hpp"
#include "engine/transport.hpp"
#include "io/dataset.hpp"
#include "model/names.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

// This engine's, measured on made-up models of independent decay chains -- 16 chains of 12
// nuclides through 15 to 150 compartments (2,880 to 28,800 states, 300 output times), and one
// of 600 compartments (115,200 states) -- split into 2 to 10 bins on a 10-core Apple M1 Max (8
// performance cores, 2 efficiency cores), in the default (fast) mode, the machine otherwise
// quiet (tests/test_split.cpp times the 28,800-state one with KOMPARTMENT_SPLIT_TIMING=1):
//
// - a bin's solve costs, per step, its share of the whole model's: a part of a sixteenth to a
//   half of the states paid -0.02 to 0.00 of a whole derivative call besides, and took fewer
//   steps than the whole. Bins side by side slow each other's solves, by 2 % (2 bins) to
//   5-12 % (8 bins; 21 % at 115,200 states), which a `shared_work` of 0.02 stands for;
// - a bin's build shrinks with its share: what it pays whatever it holds came to 0.04 to 0.06
//   of a whole build (`build_fixed`). Builds side by side slow each other down more -- by 0.4
//   to 0.6 of a build for every other bin built beside it, on the larger models
//   (`build_contention`) -- but a build is a fiftieth of a solve here;
// - a split costs, past its slowest bin's build and solve, 0.5 to 9 ms -- the parts filed back
//   into the whole model, growing with its states and its output times (`start_ms`); a
//   bundled example solved in half a millisecond takes about one split;
// - 8 bins gave 5.3-5.5x a whole solve, 4 bins 3.1-3.3x, 2 bins 1.8x; 10 bins, two of them on
//   the efficiency cores, no more than 8 (`untimed_bins`);
// - a whole solve of 70 ms split into 8 bins took 14 ms, one of 7 ms 2.5 ms: splitting pays
//   down to a few milliseconds here, so the floors are where the time it saves stops being
//   worth a run that differs from the whole one in its last digits (`auto_solve_ms`), and,
//   before a model has been timed, the size such a solve takes (`auto_states`).
const SplitConstants SPLIT_CONSTANTS = [] {
    SplitConstants c;
    c.shared_work = 0.02;
    c.auto_states = 5000;
    c.auto_solve_ms = 100.0;
    c.auto_gain = 1.2;
    c.auto_gain_untimed = 2.0;
    c.start_ms = 5.0;
    c.build_fixed = 0.05;
    c.build_contention = 0.5;
    c.untimed_bins = 8;
    return c;
}();

namespace {

double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

/// Seconds since 1970, as Julia's `time()`.
double epoch_s() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

/// Julia's `max` and `min` of two floats: a NaN wins, and +0.0 is above -0.0.
double jl_max(double x, double y) {
    bool take_y = (y > x) || (std::signbit(y) < std::signbit(x));
    return take_y ? (std::isnan(x) ? x : y) : (std::isnan(y) ? y : x);
}
double jl_min(double x, double y) {
    bool take_y = (y < x) || (std::signbit(y) > std::signbit(x));
    return take_y ? (std::isnan(x) ? x : y) : (std::isnan(y) ? y : x);
}

/// Julia's `isless` of two floats: a NaN after every number, -0.0 before +0.0.
bool jl_isless(double x, double y) {
    if (std::isnan(x)) return false;
    if (std::isnan(y)) return true;
    if (x == y) return std::signbit(x) && !std::signbit(y);
    return x < y;
}

/// `floor(Int, x + 0.5)` (`_js_round_int`).
long long js_round_int(double x) { return jl_to_int(std::floor(x + 0.5)); }

/// Python's truthiness of what a model file holds: null, false, zero and what is empty are not.
bool py_truthy(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return false;
        case Json::Type::Bool: return v.as_bool();
        case Json::Type::Int: return v.as_int() != 0;
        case Json::Type::Float: return v.as_double() != 0;
        default: return !v.empty();
    }
}

const JArray NO_ITEMS;
const JArray& items(const Json& v) { return v.is_array() ? v.arr() : NO_ITEMS; }

std::string joined(const std::vector<std::string>& parts, const std::string& by) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? by : "") + parts[i];
    return s;
}

/// What a run's error says, as the Julia package words a split that failed
/// (`_split_error_text`): its message where it has one, else as `showerror` writes it.
std::string error_text(const std::exception_ptr& e) { return error_info(e).shown; }

bool is_aborted(const std::exception_ptr& e) {
    try {
        std::rethrow_exception(e);
    } catch (const SolverError& x) {
        return x.kind == "aborted";
    } catch (...) {
        return false;
    }
}

/// The blocks whose dependency the Jacobian's pattern deliberately leaves out.
const char* unseen(const std::string& kind) {
    if (kind == "delay")
        return "a delay reports the past, which no present state can move, so the Jacobian gives it no column and a dependency through it is "
               "invisible to this partition";
    if (kind == "snapshot")
        return "a snapshot reports the past, which no present state can move, so the Jacobian gives it no column and a dependency through it is "
               "invisible to this partition";
    if (kind == "trigger") return "an event moves a state its condition never mentions, which is not a derivative and so is not in the Jacobian";
    return nullptr;
}

const std::string TIMES = "\xc3\x97";               // x
const std::string APOSTROPHE = "\xe2\x80\x99";      // '

/// What earlier runs measured (`_known_value`): a number, or none.
std::optional<double> known_value(const Json& known, const char* key) {
    if (!known.is_object()) return std::nullopt;
    const Json& v = known.get(key);
    if (!v.is_number()) return std::nullopt;
    return v.as_double();
}

/// The entries of the recorders that remember (a min/max, a running mean), each by the name
/// `split_jobs` gives it, with its place in the system's histories.
std::vector<std::pair<std::string, int>> remembering_entries(const System& sys) {
    std::vector<std::pair<std::string, int>> out;
    const IndexSpace& space = *sys.builder->space;
    for (const auto& rec : sys.builder->recorders) {
        if (!((rec->kind == "min_max" || rec->kind == "running_mean") && rec->mem >= 0)) continue;
        for (int off = 0; off < rec->width; off++) {
            std::vector<std::string> index = rec->dims.empty() ? std::vector<std::string>{} : space.tuple_at(rec->dims, off);
            out.emplace_back(rec->kind + ":" + rec->name + "[" + joined(index, ",") + "]", rec->mem + off);
        }
    }
    return out;
}

/// For every entry of a recorder that remembers: `(key, job, slot)` -- or the refusal, when
/// the states its target reads are in more than one job and no part can give it back
/// (`_recorder_owners`).
std::variant<std::vector<SplitRecorder>, std::string> recorder_owners(const System& sys, const std::vector<int>& owner, int smallest,
                                                                      const std::unordered_map<std::string, int>& job_of_material) {
    std::vector<SplitRecorder> out;
    std::vector<EntryPtr> remembering;
    for (const auto& r : sys.builder->recorders)
        if ((r->kind == "min_max" || r->kind == "running_mean") && r->mem >= 0) remembering.push_back(r);
    if (remembering.empty()) return out;
    const auto deps = state_dependencies(sys);
    const IndexSpace& space = *sys.builder->space;
    for (const auto& rec : remembering) {
        const EntryPtr& target = rec->aux_at("target");
        const std::optional<std::string> d = material_dim(sys, rec->dims);
        std::optional<std::size_t> at;
        if (d)
            for (std::size_t k = 0; k < rec->dims.size(); k++)
                if (rec->dims[k] == *d) {
                    at = k;
                    break;
                }
        for (int off = 0; off < rec->width; off++) {
            std::set<int> jobs;
            auto it = deps.find(target->base + off);
            if (it != deps.end())
                for (int s : it->second) jobs.insert(owner[static_cast<std::size_t>(s)]);
            if (jobs.size() > 1) return "'" + rec->name + "' remembers a value read from more than one part, so no part can give it back";
            std::vector<std::string> index = rec->dims.empty() ? std::vector<std::string>{} : space.tuple_at(rec->dims, off);
            // A target that reads no state is the same in every build that holds the entry, but
            // an entry per material is built only where its material is switched on: it is that
            // job's to give back (the smallest job's never held it, and the split was solved
            // whole instead).
            int job = smallest;
            if (!jobs.empty()) {
                job = *jobs.begin();
            } else if (at) {
                auto found = job_of_material.find(index[*at]);
                if (found != job_of_material.end()) job = found->second;
            }
            out.push_back({rec->kind + ":" + rec->name + "[" + joined(index, ",") + "]", job, rec->mem + off});
        }
    }
    return out;
}

SplitJobs no_jobs(const std::string& why) {
    SplitJobs out;
    out.why = why;
    return out;
}

// --- one bin's model ----------------------------------------------------------------------------------

bool is_material_list(const Json& lst) { return py_truthy(lst.get("for_contaminants")) || py_truthy(lst.get("for_nuclides")); }

/// An index's name as a list holds it: the text itself, or a dictionary's `name` (`_index_name`).
Json index_name(const Json& i) {
    if (i.is_string()) return i;
    if (i.is_object()) return i.get("name");
    return Json();
}

bool is_material_index(const Json& model, const std::string& name) {
    for (const Json& lst : items(model.get("index_lists"))) {
        if (!is_material_list(lst)) continue;
        for (const Json& i : items(lst.get("indices")))
            if (index_name(i) == name) return true;
    }
    return false;
}

/// The model with `name` switched back on in the material lists, and among its nuclides in the
/// catalogue's order (`_switch_on`).
Json switch_on(const Json& model, const std::string& name) {
    Json out = model.copy();
    if (out.get("index_lists").is_array())
        for (Json& lst : out["index_lists"].arr()) {
            if (!is_material_list(lst)) continue;
            if (!lst.get("indices").is_array()) continue;
            for (Json& i : lst["indices"].arr())
                if (i.is_object() && i.get("name") == name) i.set("enabled", Json(true));
        }
    const Json& nuclides = out.get("nuclides");
    if (nuclides.is_array()) {
        bool there = false;
        for (const Json& n : nuclides.arr()) there = there || n == name;
        if (!there) {
            const Json* catalogue = nullptr;
            for (const Json& l : items(out.get("index_lists")))
                if (py_truthy(l.get("for_contaminants"))) {
                    catalogue = &l;
                    break;
                }
            std::vector<Json> on(nuclides.arr().begin(), nuclides.arr().end());
            on.push_back(Json(name));
            Json kept = Json::array();
            if (catalogue)
                for (const Json& i : items(catalogue->get("indices"))) {
                    Json n = index_name(i);
                    // Julia's `n in Set{Any}(...)`: equal by value.
                    if (std::any_of(on.begin(), on.end(), [&](const Json& x) { return x == n; })) kept.push(n);
                }
            out.set("nuclides", kept);
        }
    }
    return out;
}

/// The histories of the recorders that remember, by the name `split_jobs` gives each entry (`_remembered`).
std::map<std::string, Recorder> remembered(const System& sys, const std::vector<Recorder>& mem) {
    std::map<std::string, Recorder> out;
    for (const auto& [key, slot] : remembering_entries(sys)) out[key] = mem[static_cast<std::size_t>(slot)];
    return out;
}

/// One bin, on a thread: the model with its materials alone switched on, built, run on the
/// output grid holding the whole model's far-field layers, and its states, counts and
/// recorders' histories sent back. `hear(fraction, t)` is the part's progress; false from it
/// stops the part.
PartRun part_run(const Json& model, const std::vector<std::string>& materials, const FarfLayerMap* layers, const ProgressFunction& hear) {
    double started = now_s();
    BuiltPart built = build_part(part_model(model, materials));
    double build_ms = 1000 * (now_s() - started);
    RunOptions options;
    options.on_grid = true;
    options.on_progress = hear;
    options.layers = layers;
    Results res = run_project(built.project, built.system, options);
    std::optional<std::vector<std::string>> keys = state_keys(*built.system);
    if (!keys) throw std::runtime_error("two states of this part share a name");
    PartRun out;
    out.t = std::move(res.t);
    out.y = std::move(res.y);
    out.keys = std::move(*keys);
    out.stats = res.stats.shallow();
    if (out.stats.has("held")) {
        out.held = out.stats.get("held");
        out.stats.erase("held");
    }
    const RunState& state = res.kept;
    out.mem = remembered(*built.system, state.mem);
    out.dis = state.dis;
    out.sampled = state.sampled;
    out.clock = {state.min_change, state.origin};
    out.build_ms = build_ms;
    out.solve_ms = res.timing.get("solve_ms").as_double();
    out.pinned = built.pinned;
    return out;
}

/// `get(stats, key, 0) + v`, as Julia adds: integers stay integers.
Json added(const Json& was, const Json& v) {
    if ((was.is_null() || was.is_int()) && v.is_int()) return Json(static_cast<long long>((was.is_null() ? 0 : was.as_int()) + v.as_int()));
    return Json((was.is_null() ? 0.0 : was.as_double()) + v.as_double());
}

const char* const SUMMED[] = {"nsteps", "nfailed", "nfevals", "npds", "ndecomps", "restarts", "breaks", "events", "jumps", "nbelowtol", "negative"};

/// Julia's `Float64(v)` of what a split's memory holds: a number or a Boolean; anything else
/// is its `MethodError` (see `split_close`).
double memory_float(const Json& v) {
    if (v.is_number()) return v.as_double();
    if (v.is_bool()) return v.as_bool() ? 1.0 : 0.0;
    const char* type = v.is_string() ? "String" : v.is_array() ? "Vector{Any}" : "OrderedCollections.OrderedDict{String, Any}";
    throw JuliaError("MethodError", std::string("MethodError: no method matching Float64(::") + type + ")");
}

// --- what auto learns --------------------------------------------------------------------------------------

struct SplitMemory {
    std::mutex lock;
    std::unordered_map<std::string, Json> entries;
    bool read = false;
};

SplitMemory& split_memory() {
    static SplitMemory m;
    return m;
}

std::string trimmed(const char* s) { return s ? std::string(js_trim(s)) : std::string(); }

std::string read_text(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot read " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

/// The file read once a process, its entries kept where this process has none of its own
/// (`_read_split_memory!`); called holding the lock.
void read_split_memory(SplitMemory& m) {
    if (m.read) return;
    m.read = true;
    std::optional<std::string> path = split_memory_path();
    std::error_code ec;
    if (!path || !std::filesystem::is_regular_file(*path, ec)) return;
    Json kept;
    try {
        kept = parse_json(read_text(*path));
    } catch (...) {
        return;
    }
    if (!kept.is_object()) return;
    for (const auto& [key, entry] : kept.obj())
        if (entry.is_object() && !m.entries.count(key)) m.entries[key] = entry.copy();
}

}  // namespace

// --- the partition -----------------------------------------------------------------------------------------

StatePartition state_partition(const Pattern* pattern) {
    StatePartition out;
    const int n = pattern ? pattern->n : 0;
    if (n == 0) return out;
    std::vector<int> parent(static_cast<std::size_t>(n));
    std::iota(parent.begin(), parent.end(), 0);
    auto root = [&](int x) {
        while (parent[static_cast<std::size_t>(x)] != x) {
            parent[static_cast<std::size_t>(x)] = parent[static_cast<std::size_t>(parent[static_cast<std::size_t>(x)])];
            x = parent[static_cast<std::size_t>(x)];
        }
        return x;
    };
    for (int j = 0; j < n; j++)
        for (I32 p = pattern->colptr[static_cast<std::size_t>(j)]; p < pattern->colptr[static_cast<std::size_t>(j) + 1]; p++) {
            int a = root(pattern->rowval[static_cast<std::size_t>(p)]);
            int b = root(j);
            if (a == b) continue;
            if (a < b) parent[static_cast<std::size_t>(b)] = a;
            else parent[static_cast<std::size_t>(a)] = b;
        }
    std::vector<int> number(static_cast<std::size_t>(n), 0);
    out.of.resize(static_cast<std::size_t>(n));
    for (int i = 0; i < n; i++) {
        int r = root(i);
        if (number[static_cast<std::size_t>(r)] == 0) number[static_cast<std::size_t>(r)] = ++out.count;
        out.of[static_cast<std::size_t>(i)] = number[static_cast<std::size_t>(r)] - 1;
    }
    out.sizes.assign(static_cast<std::size_t>(out.count), 0);
    for (int i = 0; i < n; i++) out.sizes[static_cast<std::size_t>(out.of[static_cast<std::size_t>(i)])]++;
    out.largest = *std::max_element(out.sizes.begin(), out.sizes.end());
    return out;
}

std::optional<std::string> why_not_split(const System& sys) {
    const auto& j = sys.jacobian;
    if (!(j && j->available)) return std::string("the model has no analytic Jacobian, so there is no sparsity pattern to read the parts off");
    if (!j->pattern || j->pattern->n == 0) return std::string("the model has no states to split");
    for (const auto& rec : sys.builder->recorders) {
        const char* why = unseen(rec->kind);
        if (!why) continue;
        std::string kind = rec->kind;
        std::replace(kind.begin(), kind.end(), '_', ' ');
        return "'" + rec->name + "' is a " + kind + ": " + why;
    }
    // A semi-analytical path's release is a convolution over what flowed into it during the
    // run, and the series of a split run are worked out afterwards on the whole model's
    // system, which never saw that history.
    for (const auto& p : sys.builder->farf_layout)
        if (p->farf && p->farf->laplace)
            return "'" + p->name +
                   "' is worked out semi-analytically: its release is a convolution over what flowed into it during the run, which the whole "
                   "model the series are worked out on afterwards does not have";
    // (A trigger, which is what makes an event slot, is refused above among the recorders:
    // the Julia package's own order, kept.)
    const std::size_t n = sys.event_slots.size();
    if (n > 0) {
        std::string many = n == 1 ? "an event" : std::to_string(n) + " events";
        return "the model has " + many + ", and an event moves a state its condition never mentions, which is not a derivative and so is not in "
               "the Jacobian";
    }
    return std::nullopt;
}

Partition partition_of(const System& sys) {
    Partition out;
    std::optional<std::string> refusal = why_not_split(sys);
    if (refusal) {
        out.refusal = refusal;
        return out;
    }
    StatePartition p = state_partition(&*sys.jacobian->pattern);
    out.ok = true;
    out.count = p.count;
    out.of = std::move(p.of);
    out.sizes = std::move(p.sizes);
    out.largest = p.largest;
    return out;
}

// --- names and materials of the states ---------------------------------------------------------------------

std::optional<std::vector<std::string>> state_keys(const System& sys) {
    const Builder& b = *sys.builder;
    const IndexSpace& space = *b.space;
    std::vector<std::optional<std::string>> keys(static_cast<std::size_t>(sys.nstate));
    for (const auto& entry : b.states) {
        const std::string& kind = entry->kind;
        if (kind == "farfield" && entry->farf) {
            const FarfLayout& farf = *entry->farf;
            std::vector<std::optional<std::string>> names;
            if (!farf.list_name) names.push_back(std::nullopt);
            else
                for (auto& s : space.index_names(*farf.list_name)) names.push_back(std::move(s));
            for (int o = 0; o < farf.other_width; o++) {
                std::vector<std::string> others = farf.other_dims.empty() ? std::vector<std::string>{} : space.tuple_at(farf.other_dims, o);
                const int base = entry->base + o * farf.ncells * farf.nnuc;
                for (int m = 0; m < farf.nnuc; m++) {
                    std::string text;
                    std::size_t k = 0;
                    bool first = true;
                    for (const auto& dim : entry->dims) {
                        const std::optional<std::string>& v =
                            (farf.list_name && dim == *farf.list_name) ? names[static_cast<std::size_t>(m)] : std::optional<std::string>(others[k++]);
                        text += (first ? "" : ",") + v.value_or("");
                        first = false;
                    }
                    for (int cell = 0; cell < farf.ncells; cell++)
                        keys[static_cast<std::size_t>(base + cell * farf.nnuc + m)] = kind + ":" + entry->name + "[" + text + "]#" + std::to_string(cell);
                }
            }
            continue;
        }
        if (kind == "budget" && entry->budget) {
            const Budget& budget = *entry->budget;
            for (std::size_t t = 0; t < budget.terms.size(); t++)
                for (int f = 0; f < budget.nfam; f++)
                    keys[static_cast<std::size_t>(entry->base) + t * static_cast<std::size_t>(budget.nfam) + static_cast<std::size_t>(f)] =
                        "budget:" + budget.terms[t] + ":" + budget.families[static_cast<std::size_t>(f)];
            continue;
        }
        for (int off = 0; off < entry->width; off++) {
            std::vector<std::string> index = entry->dims.empty() ? std::vector<std::string>{} : space.tuple_at(entry->dims, off);
            keys[static_cast<std::size_t>(entry->base + off)] = kind + ":" + entry->name + "[" + joined(index, ",") + "]";
        }
    }
    std::unordered_set<std::string> seen;
    std::vector<std::string> out;
    out.reserve(keys.size());
    for (auto& k : keys) {
        if (!k || seen.count(*k)) return std::nullopt;
        seen.insert(*k);
        out.push_back(std::move(*k));
    }
    return out;
}

std::vector<std::optional<std::string>> state_materials(const System& sys) {
    const Builder& b = *sys.builder;
    const IndexSpace& space = *b.space;
    std::vector<std::optional<std::string>> out(static_cast<std::size_t>(sys.nstate));
    for (const auto& entry : b.states) {
        if (entry->kind == "farfield" && entry->farf) {
            const FarfLayout& farf = *entry->farf;
            if (!farf.list_name) continue;
            const std::vector<std::string> names = space.index_names(*farf.list_name);
            for (int o = 0; o < farf.other_width; o++) {
                const int base = entry->base + o * farf.ncells * farf.nnuc;
                for (int m = 0; m < farf.nnuc; m++)
                    for (int cell = 0; cell < farf.ncells; cell++) out[static_cast<std::size_t>(base + cell * farf.nnuc + m)] = names[static_cast<std::size_t>(m)];
            }
            continue;
        }
        if (entry->kind == "budget" && entry->budget) {
            const Budget& budget = *entry->budget;
            for (std::size_t t = 0; t < budget.terms.size(); t++)
                for (int f = 0; f < budget.nfam; f++) {
                    const std::string& family = budget.families[static_cast<std::size_t>(f)];
                    out[static_cast<std::size_t>(entry->base) + t * static_cast<std::size_t>(budget.nfam) + static_cast<std::size_t>(f)] =
                        family == UNINDEXED ? std::nullopt : std::optional<std::string>(family);
                }
            continue;
        }
        std::optional<std::string> d = material_dim(sys, entry->dims);
        if (!d) continue;
        const std::size_t at = static_cast<std::size_t>(std::find(entry->dims.begin(), entry->dims.end(), *d) - entry->dims.begin());
        for (int off = 0; off < entry->width; off++) out[static_cast<std::size_t>(entry->base + off)] = space.tuple_at(entry->dims, off)[at];
    }
    return out;
}

// --- the jobs ----------------------------------------------------------------------------------------------

SplitJobs split_jobs(const System& sys) {
    Partition part = partition_of(sys);
    if (!part.ok) return no_jobs(*part.refusal);
    const Builder& b = *sys.builder;
    if (!b.material_list) return no_jobs("the model has no materials to divide it by");
    if (part.count < 2) return no_jobs("the model is one part: every state can reach every other");
    std::optional<std::vector<std::string>> keys = state_keys(sys);
    if (!keys) return no_jobs("two states of the model share a name, so a part could not be filed back by it");
    const std::vector<std::optional<std::string>> materials = state_materials(sys);
    const int n = sys.nstate;
    const std::vector<int>& of = *part.of;
    const int count = part.count;

    // Parts that share a material are one job.
    std::vector<int> parent(static_cast<std::size_t>(count));
    std::iota(parent.begin(), parent.end(), 0);
    auto find = [&](int x) {
        while (parent[static_cast<std::size_t>(x)] != x) {
            parent[static_cast<std::size_t>(x)] = parent[static_cast<std::size_t>(parent[static_cast<std::size_t>(x)])];
            x = parent[static_cast<std::size_t>(x)];
        }
        return x;
    };
    std::unordered_map<std::string, int> first_part;
    for (int i = 0; i < n; i++) {
        const auto& m = materials[static_cast<std::size_t>(i)];
        if (!m) continue;
        const int p = of[static_cast<std::size_t>(i)];
        auto was = first_part.find(*m);
        if (was == first_part.end()) first_part.emplace(*m, p);
        else if (find(was->second) != find(p)) parent[static_cast<std::size_t>(find(p))] = find(was->second);
    }
    // The groups with a material, numbered in the order they first appear.
    std::vector<int> job_of(static_cast<std::size_t>(count), -1);
    std::vector<std::vector<std::string>> names;
    std::vector<std::unordered_set<std::string>> seen;
    std::vector<long long> owned;
    std::vector<char> carries(static_cast<std::size_t>(count), 0);
    for (int i = 0; i < n; i++)
        if (materials[static_cast<std::size_t>(i)]) carries[static_cast<std::size_t>(of[static_cast<std::size_t>(i)])] = 1;
    for (int p = 0; p < count; p++) {
        if (!carries[static_cast<std::size_t>(p)]) continue;
        const int r = find(p);
        if (job_of[static_cast<std::size_t>(r)] < 0) {
            job_of[static_cast<std::size_t>(r)] = static_cast<int>(names.size());
            names.emplace_back();
            seen.emplace_back();
            owned.push_back(0);
        }
        job_of[static_cast<std::size_t>(p)] = job_of[static_cast<std::size_t>(r)];
    }
    if (names.size() < 2) return no_jobs("every part shares a material with another, so the model builds as one job");
    std::vector<int> owner(static_cast<std::size_t>(n), 0);
    for (int i = 0; i < n; i++) {
        const int j = job_of[static_cast<std::size_t>(find(of[static_cast<std::size_t>(i)]))];
        owner[static_cast<std::size_t>(i)] = j;
        if (j < 0) continue;
        owned[static_cast<std::size_t>(j)]++;
        const auto& m = materials[static_cast<std::size_t>(i)];
        if (m && !seen[static_cast<std::size_t>(j)].count(*m)) {
            seen[static_cast<std::size_t>(j)].insert(*m);
            names[static_cast<std::size_t>(j)].push_back(*m);
        }
    }
    // The parts with no material go to the smallest job, which every build holds them anyway.
    int smallest = 0;
    for (int k = 0; k < static_cast<int>(names.size()); k++)
        if (owned[static_cast<std::size_t>(k)] < owned[static_cast<std::size_t>(smallest)]) smallest = k;
    for (int i = 0; i < n; i++)
        if (owner[static_cast<std::size_t>(i)] < 0) {
            owner[static_cast<std::size_t>(i)] = smallest;
            owned[static_cast<std::size_t>(smallest)]++;
        }
    // A material the model has but no state carries rides with the smallest job, so that
    // every material is switched on somewhere.
    std::unordered_set<std::string> placed;
    for (const auto& ms : names) placed.insert(ms.begin(), ms.end());
    for (const auto& m : b.space->index_names(*b.material_list))
        if (!placed.count(m)) {
            names[static_cast<std::size_t>(smallest)].push_back(m);
            seen[static_cast<std::size_t>(smallest)].insert(m);
        }
    std::unordered_map<std::string, int> job_of_material;
    for (std::size_t k = 0; k < names.size(); k++)
        for (const auto& m : names[k]) job_of_material[m] = static_cast<int>(k);
    auto recorders = recorder_owners(sys, owner, smallest, job_of_material);
    if (std::holds_alternative<std::string>(recorders)) return no_jobs(std::get<std::string>(recorders));
    SplitJobs out;
    for (std::size_t k = 0; k < names.size(); k++) out.jobs.push_back({names[k], owned[k]});
    out.owner = std::move(owner);
    out.keys = std::move(*keys);
    out.parts = count;
    out.recorders = std::move(std::get<std::vector<SplitRecorder>>(recorders));
    return out;
}

// --- the plan ----------------------------------------------------------------------------------------------

double job_cost(double states, double total, const SplitConstants& c) { return c.shared_work + (1 - c.shared_work) * (total > 0 ? states / total : 1.0); }

std::vector<std::vector<int>> pack_jobs(const std::vector<double>& costs, long long workers) {
    const std::size_t n = static_cast<std::size_t>(std::max<long long>(1, std::min<long long>(workers, static_cast<long long>(costs.size()))));
    std::vector<double> load(n, 0.0);
    std::vector<std::vector<int>> bins(n);
    std::vector<int> order(costs.size());
    std::iota(order.begin(), order.end(), 0);
    // By (-cost, index), as Julia's `isless` orders them: the largest first, ties in order.
    std::stable_sort(order.begin(), order.end(),
                     [&](int a, int b) { return jl_isless(-costs[static_cast<std::size_t>(a)], -costs[static_cast<std::size_t>(b)]); });
    for (int j : order) {
        std::size_t k = 0;
        for (std::size_t b = 1; b < n; b++)
            if (load[b] < load[k]) k = b;
        load[k] += costs[static_cast<std::size_t>(j)];
        bins[k].push_back(j);
    }
    for (auto& b : bins) std::sort(b.begin(), b.end());
    return bins;
}

std::string with_commas(long long n) {
    unsigned long long a = n < 0 ? 0ULL - static_cast<unsigned long long>(n) : static_cast<unsigned long long>(n);
    std::string s = std::to_string(a);
    std::string out;
    for (std::size_t i = 1; i <= s.size(); i++) {
        if (i > 1 && (s.size() - i + 1) % 3 == 0) out += ',';
        out += s[i - 1];
    }
    return (n < 0 ? "-" : "") + out;
}

SplitPlan no_split(const std::string& mode, const std::string& why, std::optional<double> predicted) {
    SplitPlan p;
    p.use = false;
    p.mode = mode;
    p.why = why;
    p.predicted = predicted;
    return p;
}

SplitPlan plan_split(const System& sys, const Project& project, const PlanOptions& options) {
    const SplitConstants& c = options.constants;
    const std::string m = (options.mode == "on" || options.mode == "off") ? options.mode.as_string() : std::string("auto");
    if (m == "off") return no_split(m, "switched off");
    if (sys.nstate == 0) return no_split(m, "the model has nothing to integrate");
    if (!options.on_grid && project.output_mode != "grid")
        return no_split(m, "the results are reported at the solver" + APOSTROPHE + "s own steps, which would be different in every part");
    if (!options.nest) return no_split(m, "this run is itself one of several side by side, which do not start more");
    SplitJobs found = split_jobs(sys);
    if (found.why) return no_split(m, *found.why);
    const long long n = sys.nstate;
    const long long cores = std::max<long long>(1, jl_to_int(std::floor(options.workers)));
    // (The Julia package says "start Julia with more (julia --threads=auto)"; this engine runs on
    // as many threads as the machine has cores, unless told fewer.)
    if (cores < 2) return no_split(m, "there is one thread to run on");
    // Packed by states: a bin is one build, so the work every part repeats is paid once per
    // bin whatever it holds.
    std::vector<double> states;
    long long largest = 0;
    for (const auto& j : found.jobs) {
        states.push_back(static_cast<double>(j.states));
        largest = std::max(largest, j.states);
    }
    struct Packed {
        std::vector<std::vector<int>> bins;
        std::vector<long long> states;
    };
    auto packed = [&](long long k) {
        Packed p;
        p.bins = pack_jobs(states, k);
        for (const auto& b : p.bins) {
            long long s = 0;
            for (int j : b) s += found.jobs[static_cast<std::size_t>(j)].states;
            p.states.push_back(s);
        }
        return p;
    };
    Packed choice = packed(cores);
    SplitPlan plan;
    plan.use = true;
    plan.mode = m;
    plan.jobs = found.jobs;
    plan.owner = found.owner;
    plan.keys = found.keys;
    plan.bins = choice.bins;
    plan.parts = found.parts;
    plan.recorders = found.recorders;
    const std::string size = std::to_string(found.jobs.size()) + " parts, the largest " +
                             std::to_string(js_round_int(static_cast<double>(100 * largest) / static_cast<double>(n))) + "% of the states";
    auto bins_text = [](const Packed& p) { return std::to_string(p.bins.size()); };
    if (m == "on") {
        plan.why = "asked for: " + size + ", on " + bins_text(choice) + " cores";
        return plan;
    }
    // Auto: what a split is expected to gain over a whole solve of S ms, packed as `p` is.
    const std::optional<double> S_known = known_value(options.known, "solve_ms");
    const bool timed = S_known && std::isfinite(*S_known);
    const double S = S_known.value_or(0.0);
    const double B = jl_max(0.0, options.build_ms);
    std::optional<double> fixed = known_value(options.known, "build_fixed");
    if (!fixed) fixed = c.build_fixed;
    const double N = static_cast<double>(n);
    auto expected = [&](const Packed& p) {
        if (!fixed) {
            double load = 0;
            for (std::size_t k = 0; k < p.states.size(); k++) load = k ? jl_max(load, job_cost(static_cast<double>(p.states[k]), N, c)) : job_cost(static_cast<double>(p.states[k]), N, c);
            return S / (load * (B + S) + c.start_ms);
        }
        // The part of a build that does not shrink with the part, as a split of this model
        // measured it or as this engine takes it; slower for every bin built beside it.
        const double f = *fixed;
        const double slower = 1 + c.build_contention * static_cast<double>(static_cast<long long>(p.bins.size()) - 1);
        double worst = 0;
        for (std::size_t k = 0; k < p.states.size(); k++) {
            const double s = static_cast<double>(p.states[k]);
            const double bin = B * (f + (1 - f) * s / N) * slower + S * job_cost(s, N, c);
            worst = k ? jl_max(worst, bin) : bin;
        }
        return S / (worst + c.start_ms);
    };
    if (timed && c.build_contention > 0) {
        double best = -std::numeric_limits<double>::infinity();
        const long long most = std::min<long long>(cores, static_cast<long long>(states.size()));
        for (long long k = 2; k <= most; k++) {
            Packed p = packed(k);
            double e = expected(p);
            if (e > best) {
                best = e;
                choice = std::move(p);
            }
        }
    }
    // A split this model has had, measured, decides.
    if (std::optional<double> gain = known_value(options.known, "gain")) {
        if (*gain < c.auto_gain)
            return no_split(m, "split, it was measured at " + js_to_fixed(*gain, 1) + TIMES + ", which is not enough to be worth it");
        std::optional<double> bins = known_value(options.known, "bins");
        if (!timed && c.build_contention > 0 && bins) choice = packed(std::clamp<long long>(jl_to_int(*bins), 2, cores));
        plan.bins = choice.bins;
        plan.predicted = *gain;
        plan.why = size + "; measured at " + js_to_fixed(*gain, 1) + TIMES + " the last time, on " + bins_text(choice) + " cores";
        return plan;
    }
    if (timed) {
        const double predicted = expected(choice);
        if (S < c.auto_solve_ms) return no_split(m, "a whole solve takes " + std::to_string(js_round_int(S)) + " ms, too short to be worth dividing", predicted);
        if (predicted < c.auto_gain)
            return no_split(m, size + "; expected " + js_to_fixed(predicted, 1) + TIMES + " on " + bins_text(choice) + " cores, not enough", predicted);
        plan.bins = choice.bins;
        plan.predicted = predicted;
        plan.why = size + "; expected " + js_to_fixed(predicted, 1) + TIMES + " faster on " + bins_text(choice) + " cores";
        return plan;
    }
    if (c.untimed_bins > 0) choice = packed(std::min(cores, c.untimed_bins));
    double load = 0;
    for (std::size_t k = 0; k < choice.states.size(); k++)
        load = k ? jl_max(load, job_cost(static_cast<double>(choice.states[k]), N, c)) : job_cost(static_cast<double>(choice.states[k]), N, c);
    const double shape = 1 / load;
    if (n < c.auto_states) return no_split(m, with_commas(n) + " states, too few to be worth dividing before a run has been timed", shape);
    if (shape < c.auto_gain_untimed) return no_split(m, size + "; at most " + js_to_fixed(shape, 1) + TIMES + " on " + bins_text(choice) + " cores, not enough", shape);
    plan.bins = choice.bins;
    plan.predicted = shape;
    plan.why = size + "; up to " + js_to_fixed(shape, 1) + TIMES + " faster on " + bins_text(choice) + " cores";
    return plan;
}

BinnedJobs bin_jobs(const SplitPlan& plan) {
    std::vector<int> bin_of(plan.jobs.size(), 0);
    for (std::size_t b = 0; b < plan.bins.size(); b++)
        for (int j : plan.bins[b]) bin_of[static_cast<std::size_t>(j)] = static_cast<int>(b);
    BinnedJobs out;
    for (const auto& members : plan.bins) {
        SplitJob job;
        for (int j : members) {
            const SplitJob& one = plan.jobs[static_cast<std::size_t>(j)];
            job.materials.insert(job.materials.end(), one.materials.begin(), one.materials.end());
            job.states += one.states;
        }
        out.jobs.push_back(std::move(job));
    }
    for (int o : plan.owner) out.owner.push_back(bin_of[static_cast<std::size_t>(o)]);
    for (const auto& r : plan.recorders) out.recorders.push_back({r.key, bin_of[static_cast<std::size_t>(r.job)], r.slot});
    return out;
}

// --- one bin's model ---------------------------------------------------------------------------------------

Json part_model(const Json& model, const std::vector<std::string>& keep, bool copy_it) {
    Json out = copy_it ? model.copy() : model;
    const std::unordered_set<std::string> want(keep.begin(), keep.end());
    if (out.get("index_lists").is_array())
        for (Json& lst : out["index_lists"].arr()) {
            if (!is_material_list(lst)) continue;
            Json indices = Json::array();
            for (const Json& i : items(lst.get("indices"))) {
                Json idx = i.is_string() ? Json::object({{"name", i}, {"enabled", Json(true)}}) : i.shallow();
                const Json& name = idx.get("name");
                if (!(name.is_string() && want.count(name.as_string()))) idx.set("enabled", Json(false));
                indices.push(idx);
            }
            lst.set("indices", indices);
        }
    const Json& nuclides = out.get("nuclides");
    if (nuclides.is_array()) {
        Json kept = Json::array();
        for (const Json& n : nuclides.arr())
            if (n.is_string() && want.count(n.as_string())) kept.push(n);
        out.set("nuclides", kept);
    }
    return out;
}

BuiltPart build_part(const Json& model) {
    static const std::regex pinned_by("'([^']+)' is disabled in '([^']+)'");
    std::vector<std::string> pinned;
    Json current = model;
    for (;;) {
        try {
            auto project = std::make_shared<const Project>(current);
            auto system = std::make_shared<System>(project);
            return {project, system, pinned};
        } catch (...) {
            std::exception_ptr e = std::current_exception();
            const std::string text = error_text(e);
            std::smatch found;
            if (!std::regex_search(text, found, pinned_by)) std::rethrow_exception(e);
            const std::string name = found[1].str();
            if (std::find(pinned.begin(), pinned.end(), name) != pinned.end() || !is_material_index(current, name)) std::rethrow_exception(e);
            pinned.push_back(name);
            current = switch_on(current, name);
        }
    }
}

std::pair<std::vector<int>, std::vector<int>> place_states(const std::unordered_map<std::string, int>& whole, const std::vector<std::string>& keys,
                                                           const std::vector<int>& owner, int job) {
    std::vector<int> frm, to;
    for (std::size_t k = 0; k < keys.size(); k++) {
        auto it = whole.find(keys[k]);
        if (it == whole.end() || owner[static_cast<std::size_t>(it->second)] != job) continue;
        frm.push_back(static_cast<int>(k));
        to.push_back(it->second);
    }
    return {frm, to};
}

// --- the parts, back into one run ---------------------------------------------------------------------------

Assembled assemble_parts(const std::vector<std::string>& keys, const std::vector<int>& owner, const std::vector<PartRun>& outcomes) {
    const std::size_t n = keys.size();
    std::unordered_map<std::string, int> whole;
    for (std::size_t i = 0; i < n; i++) whole[keys[i]] = static_cast<int>(i);
    if (outcomes.empty()) throw JuliaError("BoundsError", "BoundsError: attempt to access 0-element Vector at index [1]");
    const std::vector<double>& t = outcomes.front().t;
    for (const PartRun& o : outcomes) {
        bool same = o.t.size() == t.size();
        for (std::size_t i = 0; same && i < t.size(); i++) same = o.t[i] == t[i];
        if (!same) throw std::runtime_error("the parts came back on different output times");
    }
    const std::size_t nt = t.size();
    std::vector<Vec> Y(nt, Vec(n, 0.0));
    std::vector<char> filled(n, 0);
    std::vector<double> share(n, 0.0);
    bool held_any = false;
    Json stats = Json::object({{"nsteps", Json(0)}, {"nfailed", Json(0)}, {"nfevals", Json(0)}});
    for (std::size_t jj = 0; jj < outcomes.size(); jj++) {
        const PartRun& o = outcomes[jj];
        auto [frm, to] = place_states(whole, o.keys, owner, static_cast<int>(jj));
        for (std::size_t r = 0; r < nt; r++) {
            const Vec& row = o.y[r];
            Vec& dest = Y[r];
            for (std::size_t q = 0; q < frm.size(); q++) dest[static_cast<std::size_t>(to[q])] = row[static_cast<std::size_t>(frm[q])];
        }
        for (int i : to) filled[static_cast<std::size_t>(i)] = 1;
        const Json& s = o.stats;
        for (const char* key : SUMMED) {
            const Json& v = s.get(key);
            if (v.is_number() && std::isfinite(v.as_double())) stats.set(key, added(stats.get(key), v));
        }
        if (!py_truthy(stats.get("solver")) && py_truthy(s.get("solver"))) stats.set("solver", s.get("solver"));
        if (!s.get("sparse").is_null()) stats.set("sparse", s.get("sparse"));
        add_method_steps(stats, s);
        // What a part said about a far-field path's layers, once however many parts the path is in.
        for (const Json& w : items(s.get("layers"))) {
            if (!stats.get("layers").is_array()) stats.set("layers", Json::array());
            Json& said = stats["layers"];
            bool there = false;
            for (const Json& x : said.arr()) there = there || (x.get("block") == w.get("block") && x.get("message") == w.get("message"));
            if (!there) said.push(w);
        }
        if (s.has("compiled")) {
            const Json& was = stats.get("compiled");
            const bool before = !stats.has("compiled") || (was.is_bool() && was.as_bool());
            stats.set("compiled", Json(before && s.get("compiled").is_bool() && s.get("compiled").as_bool()));
        }
        if (!o.held.is_null()) {
            const Json& ns = s.get("nsteps");
            const double steps = jl_max(1.0, ns.is_number() ? ns.as_double() : 1.0);
            for (std::size_t q = 0; q < frm.size(); q++) {
                const double v = o.held[static_cast<std::size_t>(frm[q])].as_double();
                if (v != 0) {
                    share[static_cast<std::size_t>(to[q])] = v / steps;
                    held_any = true;
                }
            }
        }
    }
    for (std::size_t i = 0; i < n; i++)
        if (!filled[i]) throw std::runtime_error("no part carried the state '" + keys[i] + "'");
    if (held_any) {
        const double total = stats.get("nsteps").as_double();
        Json held = Json::array();
        for (double v : share) held.push(Json(js_round_int(v * total)));
        stats.set("held", held);
    }
    return {t, std::move(Y), stats};
}

SplitRun run_split(const std::shared_ptr<const Project>& project, System& sys, const SplitPlan& plan, const SplitRunOptions& options) {
    const BinnedJobs work = bin_jobs(plan);
    const std::vector<SplitJob>& jobs = work.jobs;
    const int nb = static_cast<int>(jobs.size());
    const int count = !options.threads ? nb : std::max(1, std::min(*options.threads, nb));
    std::vector<int> order(static_cast<std::size_t>(nb));
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](int a, int b) { return jobs[static_cast<std::size_t>(a)].states > jobs[static_cast<std::size_t>(b)].states; });
    const double started = now_s();
    // The far-field paths' layers as the whole model lays them out, for every part to hold: a
    // part alone would size them by its own nuclides.
    const std::optional<FarfLayerMap> layers = whole_layers(sys, *project);
    const Json model = project_to_json(*project);
    std::vector<std::optional<PartRun>> outcome(static_cast<std::size_t>(nb));
    // Where each part is: its fraction, and its clock -- the run's start until it has said.
    std::vector<std::pair<double, double>> progress(static_cast<std::size_t>(nb), {0.0, sys.start_time});
    std::mutex heard;
    std::atomic<bool> stop{false};
    std::atomic<int> next{0};
    std::vector<std::exception_ptr> failures(static_cast<std::size_t>(count));
    std::mutex finishing;
    std::condition_variable finished_one;
    int finished = 0;
    const double end_time = sys.end_time;
    auto hearing = [&](int j) {
        return ProgressFunction([&, j](double fraction, double at) {
            {
                std::lock_guard<std::mutex> hold(heard);
                progress[static_cast<std::size_t>(j)] = {fraction, at};
            }
            return !stop.load();
        });
    };
    std::vector<std::thread> tasks;
    tasks.reserve(static_cast<std::size_t>(count));
    auto join_all = [&] {
        for (auto& task : tasks)
            if (task.joinable()) task.join();
    };
    auto bin = [&](int w) {
        try {
            while (!stop.load()) {
                const int k = next.fetch_add(1);
                if (k >= nb) break;
                const int j = order[static_cast<std::size_t>(k)];
                outcome[static_cast<std::size_t>(j)] = part_run(model, jobs[static_cast<std::size_t>(j)].materials, layers ? &*layers : nullptr, hearing(j));
                std::lock_guard<std::mutex> hold(heard);
                progress[static_cast<std::size_t>(j)] = {1.0, end_time};
            }
        } catch (...) {
            // One part that fails stops the others: the run is solved whole instead.
            stop = true;
            failures[static_cast<std::size_t>(w)] = std::current_exception();
        }
        {
            std::lock_guard<std::mutex> hold(finishing);
            finished++;
        }
        finished_one.notify_all();
    };
    try {
        for (int w = 0; w < count; w++) tasks.emplace_back(bin, w);
    } catch (...) {
        // A thread the system would not start: those started are stopped and waited for.
        stop = true;
        join_all();
        throw;
    }
    bool stopped = false;
    if (options.on_progress) {
        try {
            for (;;) {
                bool all_done;
                {
                    std::unique_lock<std::mutex> hold(finishing);
                    all_done = finished_one.wait_for(hold, std::chrono::milliseconds(100), [&] { return finished == count; });
                }
                double fraction = 0, at = 0;
                {
                    std::lock_guard<std::mutex> hold(heard);
                    for (const auto& p : progress) fraction += p.first;
                    fraction /= nb;
                    at = progress.front().second;
                    for (const auto& p : progress) at = jl_min(at, p.second);
                }
                if (!stopped && !options.on_progress(fraction, at)) {
                    stopped = true;
                    stop = true;
                }
                if (all_done) break;
            }
        } catch (...) {
            // Whatever ended it early -- the progress callback -- the parts still running are
            // told to stop, and are waited for, before it goes further.
            stop = true;
            join_all();
            throw;
        }
    }
    join_all();
    std::exception_ptr failed;
    for (const auto& cause : failures) {
        if (!cause) continue;
        // The parts stopped because another failed say only that they stopped.
        if (!failed || is_aborted(failed)) failed = cause;
    }
    if (stopped) throw SolverError("aborted", "Simulation aborted", 0.0);
    if (failed) std::rethrow_exception(failed);
    for (const auto& o : outcome)
        if (!o) throw SolverError("aborted", "Simulation aborted", 0.0);
    const double wall_ms = 1000 * (now_s() - started);
    std::vector<PartRun> outcomes;
    outcomes.reserve(outcome.size());
    for (auto& o : outcome) outcomes.push_back(std::move(*o));
    Assembled assembled = assemble_parts(plan.keys, work.owner, outcomes);
    // The recorders' histories, from the job that owns what each one reads.
    RunState state = run_state(sys);
    for (const auto& r : work.recorders) {
        const auto& mem = outcomes[static_cast<std::size_t>(r.job)].mem;
        auto it = mem.find(r.key);
        if (it == mem.end()) throw std::runtime_error("the part that owns '" + r.key + "' did not send its history back");
        state.mem[static_cast<std::size_t>(r.slot)] = it->second;
    }
    const PartRun& first = outcomes.front();
    // Julia's `copyto!` of the first part's disruptions and draws over the whole model's.
    if (first.dis.size() > state.dis.size() || first.sampled.size() > state.sampled.size())
        throw JuliaError("BoundsError", "BoundsError: the parts hold more than the whole model");
    std::copy(first.dis.begin(), first.dis.end(), state.dis.begin());
    std::copy(first.sampled.begin(), first.sampled.end(), state.sampled.begin());
    state.min_change = first.clock.first;
    state.origin = first.clock.second;
    state.laplace.clear();
    restore_run_state(sys, state);
    Json summary = Json::array();
    for (std::size_t j = 0; j < jobs.size(); j++) {
        const PartRun& o = outcomes[j];
        const Json& nsteps = o.stats.get("nsteps");
        summary.push(Json::object({{"materials", Json::array(jobs[j].materials)},
                                   {"states", Json(jobs[j].states)},
                                   {"nsteps", nsteps},
                                   {"buildMs", Json(o.build_ms)},
                                   {"solveMs", Json(o.solve_ms)}}));
    }
    std::vector<double> solving;
    for (const PartRun& o : outcomes) solving.push_back(o.solve_ms);
    const long long n = sys.nstate;
    // What one thread would have taken for the whole model, and what the split takes (each
    // part's build and solve, packed as the threads take them): kept for deciding the next run.
    SplitRun out;
    out.whole_ms = whole_solve_ms(summary, solving, n, options.constants);
    std::vector<double> spent;
    for (std::size_t j = 0; j < outcomes.size(); j++) spent.push_back(outcomes[j].build_ms + solving[j]);
    double longest = 0;
    bool any = false;
    for (const auto& b : pack_jobs(spent, count)) {
        double sum = 0.0;
        for (int j : b) sum = sum + spent[static_cast<std::size_t>(j)];
        longest = any ? jl_max(longest, sum) : sum;
        any = true;
    }
    out.expected_ms = longest + options.constants.start_ms;
    out.t = std::move(assembled.t);
    out.y = std::move(assembled.y);
    out.stats = assembled.stats;
    out.wall_ms = wall_ms;
    out.jobs = summary;
    return out;
}

double whole_solve_ms(const Json& jobs, const std::vector<double>& solving, long long states, const SplitConstants& c) {
    const std::size_t n = jobs.size();
    const double total = static_cast<double>(states);
    double stretched = 0;
    for (std::size_t j = 0; j < n; j++) {
        const double v = solving[j] / job_cost(jobs[j].get("states").as_double(), total, c);
        stretched = j ? jl_max(stretched, v) : v;
    }
    std::vector<double> steps;
    for (std::size_t j = 0; j < n; j++) {
        const Json& s = jobs[j].get("nsteps");
        if (!(s.is_number() && s.as_double() > 0)) return stretched;
        steps.push_back(s.as_double());
    }
    double per_step = 0;
    for (std::size_t j = 0; j < n; j++) per_step = j ? per_step + solving[j] / steps[j] : solving[j] / steps[j];
    double most = steps[0];
    for (double s : steps) most = jl_max(most, s);
    const double summed = per_step / (c.shared_work * static_cast<double>(n) + 1 - c.shared_work) * most;
    return jl_min(stretched, summed);
}

std::optional<double> build_fixed(const Json& jobs, long long states, double build_ms, double contention) {
    if (!(build_ms > 0 && states > 0)) return std::nullopt;
    const double slower = 1 + contention * static_cast<double>(static_cast<long long>(jobs.size()) - 1);
    std::vector<double> seen;
    for (const Json& j : jobs.arr()) {
        const double share = j.get("states").as_double() / static_cast<double>(states);
        if (share < 1) seen.push_back((j.get("buildMs").as_double() / slower / build_ms - share) / (1 - share));
    }
    if (seen.empty()) return std::nullopt;
    // Summed in order. (Julia's `sum` of a vector may take more than nine terms in another
    // order; a split has as many as it has bins, and these are timings.)
    double sum = seen[0];
    for (std::size_t k = 1; k < seen.size(); k++) sum = sum + seen[k];
    return jl_min(2.0, jl_max(0.0, sum / static_cast<double>(seen.size())));
}

// --- what auto learns --------------------------------------------------------------------------------------

const std::string& split_engine_stamp() {
    static const std::string stamp = KOMPARTMENT_BUILD_STAMP;
    return stamp;
}

std::optional<std::string> split_memory_path() {
    if (trimmed(std::getenv("KOMPARTMENT_SPLIT_MEMORY")) == "0") return std::nullopt;
    std::string root = trimmed(std::getenv("KOMPARTMENT_CACHE"));
    if (root.empty()) {
#if defined(_WIN32)
        std::string home = trimmed(std::getenv("USERPROFILE"));
#else
        std::string home = trimmed(std::getenv("HOME"));
#endif
        if (home.empty()) return std::nullopt;
        root = (std::filesystem::path(home) / ".kompartment" / "cpp").string();
    }
    return (std::filesystem::path(root) / "split-memory-cpp.json").string();
}

std::string split_memory_key(const std::string& signature) { return signature + "|cpp|" + split_engine_stamp(); }

Json split_recall(const std::string& key) {
    SplitMemory& m = split_memory();
    std::lock_guard<std::mutex> hold(m.lock);
    read_split_memory(m);
    auto it = m.entries.find(key);
    return it == m.entries.end() ? Json() : it->second.copy();
}

bool split_close(const Json& a, const Json& b) {
    if (a.is_null() || b.is_null()) return a.is_null() && b.is_null();
    // Julia's `Float64(a)`: a measurement written as anything but a number or a Boolean throws
    // its MethodError here -- out of `split_remember!`, failing the run (a fault of the Julia
    // package's, reached only by a memory file written by hand; kept as it stands).
    const double x = memory_float(a), y = memory_float(b);
    return std::fabs(x - y) <= 0.25 * jl_max(std::fabs(x), std::fabs(y));
}

void split_remember(const std::string& key, const Json& entry) {
    SplitMemory& m = split_memory();
    std::lock_guard<std::mutex> hold(m.lock);
    read_split_memory(m);
    auto it = m.entries.find(key);
    const std::optional<Json> before = it == m.entries.end() ? std::nullopt : std::optional<Json>(it->second);
    Json now = entry.is_object() ? entry.shallow() : Json::object();
    now.set("when", Json(epoch_s()));
    m.entries[key] = now;
    if (before) {
        bool close = true;
        for (const char* k : {"solve_ms", "gain", "build_fixed"}) close = close && split_close(before->get(k), entry.get(k));
        if (close) return;
    }
    const std::optional<std::string> path = split_memory_path();
    if (!path) return;
    try {
        namespace fs = std::filesystem;
        fs::create_directories(fs::path(*path).parent_path());
        Json kept = Json::object();
        std::error_code ec;
        if (fs::is_regular_file(*path, ec)) {
            Json old;
            try {
                old = parse_json(read_text(*path));
            } catch (...) {
            }
            if (old.is_object())
                for (const auto& [k, v] : old.obj()) kept.set(k, v);
        }
        kept.set(key, now);
        if (kept.size() > SPLIT_MEMORY_KEEP) {
            auto when = [](const Json& v) {
                const Json& w = v.get("when");
                return w.is_number() ? w.as_double() : 0.0;
            };
            std::vector<std::pair<std::string, Json>> all(kept.obj().begin(), kept.obj().end());
            std::stable_sort(all.begin(), all.end(), [&](const auto& a, const auto& b) { return -when(a.second) < -when(b.second); });
            all.resize(SPLIT_MEMORY_KEEP);
            Json newest = Json::object();
            for (auto& [k, v] : all) newest.set(k, v);
            kept = newest;
        }
#if defined(_WIN32)
        const std::string tmp = *path + "." + std::to_string(_getpid()) + ".part";
#else
        const std::string tmp = *path + "." + std::to_string(getpid()) + ".part";
#endif
        {
            std::ofstream out(tmp, std::ios::binary);
            if (!out) throw std::runtime_error("Cannot write " + tmp);
            out << json_text(kept, 0);
            if (!out) throw std::runtime_error("Cannot write " + tmp);
        }
        fs::rename(tmp, *path);
    } catch (...) {
        // What cannot be kept is not: the run is not the worse for it.
    }
}

void split_memory_forget() {
    SplitMemory& m = split_memory();
    std::lock_guard<std::mutex> hold(m.lock);
    m.entries.clear();
    m.read = false;
}

// --- the run ---------------------------------------------------------------------------------------------

Results run_whole_or_split(const std::shared_ptr<const Project>& project, const RunOptions& options) {
    const double t0 = now_s();
    auto sys = std::make_shared<System>(project);
    const double build_ms = 1000 * (now_s() - t0);
    const std::string key = split_memory_key(layout_signature(*sys));
    const Json known = split_recall(key);
    const int cores = options.threads ? *options.threads : static_cast<int>(std::max(1u, std::thread::hardware_concurrency()));
    const Json& mode = project->simulation.get("split");
    PlanOptions po;
    po.mode = py_truthy(mode) ? mode : Json("auto");
    po.workers = cores;
    po.nest = options.nest;
    po.build_ms = build_ms;
    po.known = known;
    po.on_grid = options.on_grid;
    SplitPlan plan = plan_split(*sys, *project, po);
    std::optional<Results> results;
    if (plan.use) {
        try {
            SplitRunOptions so;
            so.threads = options.threads;
            so.on_progress = options.on_progress;
            SplitRun split = run_split(project, *sys, plan, so);
            Results r;
            r.project = project;
            r.system = sys;
            r.t = std::move(split.t);
            r.y = std::move(split.y);
            r.stats = split.stats;
            r.timing = Json::object({{"build_ms", Json(build_ms)}, {"solve_ms", Json(split.wall_ms)}, {"total_ms", Json(1000 * (now_s() - t0))}});
            r.kept = run_state(*sys);
            results = std::move(r);
            plan.ran = split.jobs;
            plan.wall_ms = split.wall_ms;
            const double whole_ms = known_value(known, "solve_ms").value_or(split.whole_ms);
            plan.gain = split.expected_ms > 0 ? std::optional<double>(whole_ms / split.expected_ms) : std::nullopt;
            std::optional<double> fixed = build_fixed(split.jobs, sys->nstate, build_ms, SPLIT_CONSTANTS.build_contention);
            split_remember(key, Json::object({{"solve_ms", Json(whole_ms)},
                                              {"gain", plan.gain ? Json(*plan.gain) : Json()},
                                              {"build_fixed", fixed ? Json(*fixed) : Json()},
                                              {"bins", Json(static_cast<long long>(plan.bins.size()))}}));
        } catch (const SolverError& e) {
            if (e.kind == "aborted") throw;
            plan.use = false;
            plan.why = "tried, and solved whole instead: " + e.message;
            results.reset();
        } catch (...) {
            plan.use = false;
            plan.why = "tried, and solved whole instead: " + error_text(std::current_exception());
            results.reset();
        }
    }
    if (!results) {
        RunOptions whole;
        whole.on_progress = options.on_progress;
        whole.on_grid = options.on_grid;
        Results r = run_project(project, sys, whole);
        r.timing.set("build_ms", Json(build_ms));
        const Json& total = r.timing.get("total_ms");
        r.timing.set("total_ms", Json((total.is_number() ? total.as_double() : 0.0) + build_ms));
        Json entry = known.is_object() ? known.shallow() : Json::object();
        const Json& solve = r.timing.get("solve_ms");
        entry.set("solve_ms", Json(jl_max(0.0, solve.is_number() ? solve.as_double() : 0.0)));
        split_remember(key, entry);
        results = std::move(r);
    }
    Json account = Json::object({{"used", Json(plan.use)}, {"mode", Json(plan.mode)}, {"why", Json(plan.why)},
                                 {"predicted", plan.predicted ? Json(*plan.predicted) : Json()}});
    if (plan.use) {
        account.set("parts", Json(plan.parts));
        account.set("workers", Json(static_cast<long long>(plan.bins.size())));
        account.set("jobs", plan.ran);
        account.set("wallMs", Json(plan.wall_ms));
        account.set("gain", plan.gain ? Json(*plan.gain) : Json());
    }
    results->stats.set("split", account);
    return std::move(*results);
}

}  // namespace kompartment
