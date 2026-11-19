// A probabilistic run (see probabilistic.hpp): a port of the second part of the Julia
// package's engine/probabilistic.jl -- what a run keeps, the realisations shared out between
// threads, one realisation replayed -- operation for operation.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <exception>
#include <limits>
#include <mutex>
#include <new>
#include <set>
#include <thread>
#include <unordered_map>

#include "engine/errorinfo.hpp"
#include "engine/jacobian.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

/// Julia's `time()`, for how long a run took.
double now_s() {
    using namespace std::chrono;
    return duration<double>(system_clock::now().time_since_epoch()).count();
}

/// `a + b` and `a - b` as Julia's `Int` adds them: wrapping, never undefined.
long long wrap_add(long long a, long long b) {
    return static_cast<long long>(static_cast<unsigned long long>(a) + static_cast<unsigned long long>(b));
}

/// What a descriptor is kept by: its block, else its label (`_pb_keep_name`).
std::string keep_name(const Json& o) {
    const Json& b = o.get("block");
    if (!(b.is_null() || b == "")) return b.is_string() ? b.as_string() : julia_string(b);
    const Json& l = o.get("label");
    if (l.is_null() || l == "") return "";
    return l.is_string() ? l.as_string() : julia_string(l);
}

/// Where each kept series is read from (`_PBTake`): a state or a sum of states, an algebraic
/// slot or a sum of them, a parameter (indices from 0 here), or a derived series (by
/// position in `kept`).
struct Take {
    std::vector<std::pair<std::size_t, std::size_t>> y_one, x_one, p_one;
    std::vector<std::pair<std::size_t, std::vector<std::size_t>>> y_sum, x_sum;
    std::vector<std::size_t> derived;
    std::vector<std::size_t> staged;   // the states' and the algebraic slots' series, by position
};

Take make_take(const std::vector<Json>& kept) {
    Take take;
    for (std::size_t w = 0; w < kept.size(); w++) {
        const Json& o = kept[w];
        const Json& source = o.get("source");
        if (source == "P") {
            take.p_one.emplace_back(w, static_cast<std::size_t>(o.get("offset").as_int()));
        } else if (source == "D") {
            take.derived.push_back(w);
        } else {
            if (o.has("offsets")) {
                std::vector<std::size_t> offs;
                for (const Json& off : o.get("offsets").arr()) offs.push_back(static_cast<std::size_t>(off.as_int()));
                (source == "y" ? take.y_sum : take.x_sum).emplace_back(w, std::move(offs));
            } else {
                (source == "y" ? take.y_one : take.x_one).emplace_back(w, static_cast<std::size_t>(o.get("offset").as_int()));
            }
            take.staged.push_back(w);
        }
    }
    return take;
}

/// The matrices a run fills: one per kept series, a realisation's times together.
template <typename T>
using Held = std::vector<std::vector<T>>;

/// `_pb_take_rows!`: for a run reported at times besides the grid's, every series over every
/// row, read at the first row at or after each grid time.
template <typename T>
void take_rows(Held<T>& values, Results& res, const std::vector<Json>& kept, std::size_t col, const std::vector<double>& grid) {
    const std::size_t times = grid.size();
    const std::vector<double>& t = res.t;
    std::vector<std::size_t> rows(times);
    for (std::size_t j = 0; j < times; j++) {
        // `searchsortedfirst`, then no further than the last row.
        std::size_t r = static_cast<std::size_t>(std::lower_bound(t.begin(), t.end(), grid[j]) - t.begin());
        rows[j] = std::min(r, t.empty() ? 0 : t.size() - 1);
    }
    std::vector<std::vector<double>> cols = res.series_many(kept);
    for (std::size_t w = 0; w < cols.size(); w++) {
        T* M = values[w].data() + col * times;
        const std::vector<double>& c = cols[w];
        for (std::size_t j = 0; j < times; j++) M[j] = static_cast<T>(c.at(rows[j]));
    }
}

/// One realisation's kept series, onto the sample's grid, into row `col` of each matrix
/// (`_pb_take!`): each output time's state read once for every series that reads it, and the
/// algebraic slots worked out once per time -- the numbers `series_many` gives. They are
/// gathered a time at a time in `buf` (kept x times) and written out a series at a time.
template <typename T>
void take(Held<T>& values, Results& res, const std::vector<Json>& kept, const Take& tk, std::size_t col, const std::vector<double>& grid,
          std::vector<double>& buf) {
    const std::size_t times = grid.size();
    if (res.t.size() != times) return take_rows(values, res, kept, col, grid);
    System& sys = *res.system;
    const std::size_t nk = kept.size();
    for (const auto& [w, s] : tk.p_one) {
        T* M = values[w].data() + col * times;
        const double v = sys.P[s];
        for (std::size_t j = 0; j < times; j++) M[j] = static_cast<T>(v);
    }
    if (!tk.y_one.empty() || !tk.y_sum.empty()) {
        for (std::size_t j = 0; j < times; j++) {
            const Vec& y = res.y[j];
            for (const auto& [w, s] : tk.y_one) buf[w + j * nk] = y[s];
            for (const auto& [w, ss] : tk.y_sum) {
                double acc = 0.0;
                for (std::size_t s : ss) acc += y[s];
                buf[w + j * nk] = acc;
            }
        }
    }
    if (!tk.x_one.empty() || !tk.x_sum.empty()) {
        // As `algebraic_rows`: the passes at each time, with the run's histories.
        RunState keep = run_state(sys);
        restore_run_state(sys, res.kept);
        try {
            for (std::size_t j = 0; j < times; j++) {
                const std::vector<double>& X = sys.evaluate_algebraic(res.t[j], res.y[j].data());
                for (const auto& [w, s] : tk.x_one) buf[w + j * nk] = X[s];
                for (const auto& [w, ss] : tk.x_sum) {
                    double acc = 0.0;
                    for (std::size_t s : ss) acc += X[s];
                    buf[w + j * nk] = acc;
                }
            }
        } catch (...) {
            restore_run_state(sys, keep);
            sys.clock_at = NaN;
            throw;
        }
        restore_run_state(sys, keep);
        sys.clock_at = NaN;
    }
    for (std::size_t w : tk.staged) {
        T* M = values[w].data() + col * times;
        for (std::size_t j = 0; j < times; j++) M[j] = static_cast<T>(buf[w + j * nk]);
    }
    if (!tk.derived.empty()) {
        std::vector<Json> which;
        for (std::size_t w : tk.derived) which.push_back(kept[w]);
        std::vector<std::vector<double>> cols = res.series_many(which);
        for (std::size_t k = 0; k < tk.derived.size(); k++) {
            T* M = values[tk.derived[k]].data() + col * times;
            for (std::size_t j = 0; j < times; j++) M[j] = static_cast<T>(cols[k][j]);
        }
    }
}

/// A copy of a built system for another thread (`_pb_clone`): its analytic Jacobian made
/// anew for the copy, so that its plans -- which read the far-field paths through their
/// system -- refresh the copy's own paths, never the first system's from several threads.
std::shared_ptr<System> clone_for_thread(const System& sys) {
    auto c = std::make_shared<System>(sys.clone());
    // A plan holds its system by address, and the copy has just been moved.
    c->jacobian = clone_jacobian(sys.jacobian, *c);
    return c;
}

/// How many threads a run may have: the machine's cores (Julia's `Threads.nthreads()`).
int most_threads() { return static_cast<int>(std::max(1u, std::thread::hardware_concurrency())); }

struct Failure {
    long long i;
    std::string message;
};

/// Realisations `frm` to `to - 1` (from 0) shared out between threads, each on a system of
/// its own, taking the next realisation not yet taken as it finishes one (`_pb_parallel!`).
/// Returns how many threads ran and the failures, by realisation.
template <typename T>
std::pair<int, std::vector<Failure>> run_parallel(Held<T>& values, std::vector<std::uint8_t>& ran, const std::shared_ptr<const Project>& project,
                                                  const std::shared_ptr<System>& sys, const SampleDesign& design, const ValueTable& eff,
                                                  long long frm, long long to, const std::vector<Json>& kept, const Take& tk,
                                                  const std::shared_ptr<const OutputIndex>& outs, const std::vector<double>& grid,
                                                  const RealisationProgress& on_progress, int threads) {
    std::vector<Failure> failures;
    const long long span = to - frm;
    if (span <= 0) return {0, failures};
    const int ntasks = static_cast<int>(std::clamp(static_cast<long long>(std::min(threads, most_threads())), 1LL, span));
    std::atomic<long long> next{frm};
    std::atomic<bool> stop{false};
    std::exception_ptr first_failure;
    std::mutex progress_lock;
    long long done = 0;
    std::vector<std::shared_ptr<System>> systems{sys};
    for (int k = 1; k < ntasks; k++) systems.push_back(clone_for_thread(*sys));
    const std::size_t times = grid.size();
    auto work = [&](const std::shared_ptr<System>& s) {
        std::vector<double> buf(kept.size() * times, 0.0);
        RowPool pool;
        while (!stop.load()) {
            const long long i = next.fetch_add(1);
            if (i >= to) break;
            const long long row = i - frm;
            apply_realisation(*s, design, eff, row, i);
            std::optional<std::string> message;
            try {
                RunOptions options;
                options.on_grid = true;
                options.rows = &pool;
                Results r = run_project(project, s, options);
                r.share_outputs(outs);
                take(values, r, kept, tk, static_cast<std::size_t>(row), grid, buf);
            } catch (...) {
                if (i == frm) {
                    // A failure in the first realisation fails the run, and the others stop.
                    first_failure = std::current_exception();
                    stop.store(true);
                    break;
                }
                message = error_info(std::current_exception()).shown;
            }
            if (message) {
                ran[static_cast<std::size_t>(row)] = 0;
                for (auto& M : values) std::fill(M.begin() + row * static_cast<long long>(times), M.begin() + (row + 1) * static_cast<long long>(times),
                                                 static_cast<T>(NaN));
            }
            std::lock_guard<std::mutex> hold(progress_lock);
            if (message) failures.push_back({i, std::move(*message)});
            done++;
            if (on_progress) on_progress(done, span);
        }
    };
    std::vector<std::exception_ptr> errors(static_cast<std::size_t>(ntasks));
    std::vector<std::thread> helpers;
    auto task = [&](int k) {
        try {
            work(systems[static_cast<std::size_t>(k)]);
        } catch (...) {
            stop.store(true);
            errors[static_cast<std::size_t>(k)] = std::current_exception();
        }
    };
    try {
        for (int k = 1; k < ntasks; k++) helpers.emplace_back(task, k);
    } catch (...) {
        // A thread the system would not give: those started finish what they are on, and stop.
        stop.store(true);
        for (auto& h : helpers) h.join();
        throw;
    }
    task(0);
    for (auto& h : helpers) h.join();
    for (const auto& e : errors)
        if (e) std::rethrow_exception(e);
    if (first_failure) std::rethrow_exception(first_failure);
    std::stable_sort(failures.begin(), failures.end(), [](const Failure& a, const Failure& b) { return a.i < b.i; });
    return {ntasks, std::move(failures)};
}

/// `Matrix{T}(undef, times, span)` for every kept series, refused as Julia refuses one.
template <typename T>
Held<T> make_held(std::size_t count, long long times, long long span) {
    if (count == 0) return {};
    long long n = jl_array_count(times, span);
    try {
        Held<T> held;
        held.reserve(count);
        for (std::size_t k = 0; k < count; k++) held.emplace_back(static_cast<std::size_t>(n));
        return held;
    } catch (const std::bad_alloc&) {
        throw JuliaError("OutOfMemoryError", "OutOfMemoryError()");
    } catch (const std::length_error&) {
        throw JuliaError("OutOfMemoryError", "OutOfMemoryError()");
    }
}

/// The realisations' series, held as `T`, and how many threads ran them and what failed.
template <typename T>
std::pair<int, std::vector<Failure>> fill_values(Held<T>& values, std::vector<std::uint8_t>& ran, const std::shared_ptr<const Project>& project,
                                                 const std::shared_ptr<System>& sys, const SampleDesign& design, const ValueTable& eff,
                                                 long long frm, long long to, const std::vector<Json>& kept,
                                                 const std::shared_ptr<const OutputIndex>& outs, const std::vector<double>& grid,
                                                 const ProbabilisticOptions& o) {
    values = make_held<T>(kept.size(), static_cast<long long>(grid.size()), to - frm);
    Take tk = make_take(kept);
    // 0: every core; any other number as Julia's `threads` (clamped to at least one).
    int threads = o.threads == 0 ? most_threads() : o.threads;
    return run_parallel(values, ran, project, sys, design, eff, frm, to, kept, tk, outs, grid, o.on_progress, threads);
}

ProbabilisticResults run_design(const std::shared_ptr<const Project>& project, const std::shared_ptr<System>& sys, const SampleDesign& design,
                                const ProbabilisticOptions& o, double started) {
    const std::vector<PlanEntry>& plan = design.plan;
    const long long iterations = design.iterations;
    auto [frm, to] = realisation_slice(o.range, iterations);
    ValueTable eff = effective_values(design, frm, to);
    ProbabilisticResults r;
    // What each realisation ran with, recorded: a draw that is no number as the value held over.
    r.samples = eff;

    // Which series there are is the built system's to say, so every realisation -- the first
    // with the rest -- runs on the threads.
    std::shared_ptr<const OutputIndex> outs = index_outputs(outputs_of(*sys, *project));
    std::set<std::string> names;
    if (o.keep) names.insert(o.keep->begin(), o.keep->end());
    std::vector<std::size_t> wanted;
    for (std::size_t k = 0; k < outs->outputs.size(); k++) {
        const Json& out = outs->outputs[k];
        if (!can_be_endpoint(out.get("kind"))) continue;
        if (o.keep_by) {
            if (!o.keep_by(keep_name(out), out)) continue;
        } else if (o.keep) {
            const Json& label = out.get("label");
            if (!(names.count(keep_name(out)) || (label.is_string() && names.count(label.as_string())))) continue;
        }
        wanted.push_back(k);
    }
    std::unordered_map<long long, long long> column;   // a varied input's slot -> its row, from 1
    if (!design.is_designed())
        for (std::size_t k = 0; k < plan.size(); k++)
            if (design.varies[k]) column[plan[k].slot] = static_cast<long long>(k) + 1;
    for (const Json& out : outs->outputs) {
        if (!(out.get("source") == "P")) continue;
        auto it = column.find(out.get("offset").as_int());
        if (it == column.end()) continue;
        r.inputs.push_back(Json::object({{"output", out}, {"k", Json(it->second)}}));
    }
    std::vector<double> grid = project->time_grid();
    const long long times = static_cast<long long>(grid.size());
    const long long series = static_cast<long long>(wanted.size());
    std::string precision = hold_precision(series, times, iterations, o.most_bytes);
    ShapeEstimate size = estimate(series, times, iterations, precision);
    if (size.bytes > (o.large ? o.asked_bytes : o.most_bytes)) {
        std::string what = design.is_designed() ? "runs" : "realisations";
        std::string fewer = design.is_tornado() ? "fewer inputs" : design.is_gsa() ? "a smaller design" : "fewer realisations";
        std::string extra = precision == "float32" ? " even held as float32" : "";
        // `large` is offered where it would go ahead: not where it was given, nor past `asked_bytes`.
        std::string how = !o.large && size.bytes <= o.asked_bytes
                              ? "; pass large=true to go ahead on a machine with the memory for it, or choose fewer endpoints, or " + fewer + "."
                              : ", more than a run may hold with large=true or without; choose fewer endpoints, or " + fewer + ".";
        throw JuliaError("ErrorException", std::to_string(iterations) + " " + what + " of " + std::to_string(series) + " series over " +
                                               std::to_string(times) + " times is " + size.text + extra + how);
    }
    for (std::size_t k : wanted) r.outputs.push_back(outs->outputs[k]);
    r.ran.assign(static_cast<std::size_t>(to - frm), 1);
    std::pair<int, std::vector<Failure>> ranit =
        precision == "float32" ? fill_values(r.values32, r.ran, project, sys, design, eff, frm, to, r.outputs, outs, grid, o)
                               : fill_values(r.values, r.ran, project, sys, design, eff, frm, to, r.outputs, outs, grid, o);
    const std::vector<Failure>& failures = ranit.second;
    Json trouble = Json::array();
    for (std::size_t k = 0; k < failures.size() && k < 5; k++)
        trouble.push(Json("realisation " + std::to_string(failures[k].i + 1) + ": " + failures[k].message));
    r.stats = Json::object({{"failed", Json(static_cast<long long>(failures.size()))}, {"trouble", trouble}, {"ms", Json(1000 * (now_s() - started))}});
    for (const auto& [k, v] : design.stats.obj()) r.stats.set(k, v);
    r.stats.set("threads", Json(static_cast<long long>(std::max(1, ranit.first))));
    r.t = std::move(grid);
    r.precision = precision;
    r.plan = plan;
    r.names = design.names;
    r.iterations = iterations;
    r.first = frm + 1;
    r.last = to;
    r.project = project;
    r.gsa_design = design.gsa_design;
    return r;
}

}  // namespace

std::vector<double> ProbabilisticResults::realisations(std::size_t w) const {
    if (!single()) return values.at(w);
    const std::vector<float>& v = values32.at(w);
    return std::vector<double>(v.begin(), v.end());
}

std::vector<std::string> ProbabilisticResults::labels() const {
    std::vector<std::string> out;
    for (const Json& o : outputs) out.push_back(o.get("label").is_string() ? o.get("label").as_string() : julia_string(o.get("label")));
    return out;
}

std::size_t ProbabilisticResults::index_of(const std::string& label) const {
    for (std::size_t k = 0; k < outputs.size(); k++)
        if (outputs[k].get("label") == label) return k;
    throw JuliaError("KeyError", "KeyError: key " + julia_quote("No kept series labelled '" + label + "'") + " not found");
}

std::vector<double> ProbabilisticResults::sample(const std::string& name) const {
    for (std::size_t k = 0; k < names.size(); k++) {
        if (names[k] != name) continue;
        std::vector<double> out;
        for (long long i = 0; i < samples.realisations; i++) out.push_back(samples(k, i));
        return out;
    }
    throw JuliaError("KeyError", "KeyError: key " + julia_quote("No sampled input named '" + name + "'") + " not found");
}

std::pair<long long, long long> realisation_slice(const std::optional<std::pair<double, double>>& range, long long iterations) {
    if (!range) return {0, iterations};
    // Julia's `round`: the nearest, a tie to the even one; `Int` of it refused past 64 bits.
    long long first = jl_to_int(std::nearbyint(range->first));
    long long last = jl_to_int(std::nearbyint(range->second));
    long long frm = std::max(0LL, std::min(iterations - 1, wrap_add(first, -1)));
    long long to = std::max(frm + 1, std::min(iterations, last));
    return {frm, to};
}

std::vector<std::vector<double>> take_realisation(Results& res, const std::vector<Json>& kept, const std::vector<double>& grid) {
    Held<double> values(kept.size(), std::vector<double>(grid.size(), 0.0));
    std::vector<double> buf(kept.size() * grid.size(), 0.0);
    take(values, res, kept, make_take(kept), 0, grid, buf);
    return values;
}

ProbabilisticResults run_probabilistic(std::shared_ptr<const Project> project, const ProbabilisticOptions& options) {
    const double started = now_s();
    auto sys = std::make_shared<System>(project);
    SampleDesign design = design_for(*project, *sys, options);
    return run_design(project, sys, design, options, started);
}

Replay run_realisation(std::shared_ptr<const Project> project, long long number, const DesignOptions& options) {
    auto sys = std::make_shared<System>(project);
    SampleDesign design = design_for(*project, *sys, options);
    const long long i = std::min(design.iterations - 1, std::max(0LL, wrap_add(number, -1)));
    ValueTable eff = effective_values(design, i, i + 1);
    apply_realisation(*sys, design, eff, 0, i);
    Replay out;
    out.results = run_project(project, sys);
    const bool tornado = design.is_tornado();
    for (std::size_t k = 0; k < design.plan.size(); k++) {
        // Held: not varied, at the model's value in a tornado's point, or held over from a
        // realisation before, the draw being no number.
        const double value = eff(k, 0);
        const bool held = !design.varies[k] || !std::isfinite(design.values(k, i)) || (tornado && value == design.best[k]);
        out.values.push_back({design.names[k], value, held});
    }
    out.number = i + 1;
    out.iterations = design.iterations;
    return out;
}

}  // namespace kompartment
