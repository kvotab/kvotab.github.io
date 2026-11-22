#include "service.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <set>
#include <thread>

#include "engine/analysis.hpp"
#include "engine/calibrate.hpp"
#include "engine/checkrun.hpp"
#include "engine/errorinfo.hpp"
#include "engine/farfield.hpp"
#include "engine/jacobian.hpp"
#include "engine/localsens.hpp"
#include "engine/probabilistic.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "io/dataset.hpp"
#include "io/sample.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
#include "util/errors.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

void write_file(const std::string& path, const std::string& bytes) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot write " + path);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

/// Little-endian doubles, as every machine this builds for holds them.
std::string f64_bytes(const std::vector<double>& v) {
    std::string out(v.size() * 8, '\0');
    if (!v.empty()) std::memcpy(out.data(), v.data(), out.size());
    return out;
}

/// A run the page has stopped, raised out of a progress report (`_ServiceStopped`).
struct ServiceStopped : std::exception {
    const char* what() const noexcept override { return "stopped"; }
};

/// What a job's options say of `key` (`_service_option`): its value, or `fallback` where the
/// options do not say or say null.
Json option(const Json& options, const char* key, const Json& fallback = Json()) {
    if (!options.is_object()) return fallback;
    const Json& v = options.get(key);
    return v.is_null() ? fallback : v;
}

/// Julia's type name of a value a job's JSON holds, for a `MethodError` about it.
std::string julia_type_name(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "Nothing";
        case Json::Type::Bool: return "Bool";
        case Json::Type::Int: return "Int64";
        case Json::Type::Float: return "Float64";
        case Json::Type::String: return "String";
        case Json::Type::Array: return "Vector{Any}";
        case Json::Type::Object: return "OrderedCollections.OrderedDict{String, Any}";
    }
    return "Any";
}

/// Julia's `Int(v)` of an option: a whole number as it is, a Boolean as 0 or 1, any other
/// number refused where it is not a whole one (`InexactError`), and anything else a `MethodError`.
long long int_of(const Json& v) {
    if (v.is_int()) return v.as_int();
    if (v.is_bool()) return v.as_bool() ? 1 : 0;
    if (v.is_float()) return jl_to_int(v.as_double());
    throw JuliaError("MethodError", "MethodError: no method matching Int64(::" + julia_type_name(v) + ")");
}

/// A dictionary's entry as Julia shows it, iterating a dictionary a job's JSON holds: a
/// `Pair{String, Any}`, its type said since its values' types do not say it.
std::string julia_pair(const std::string& key, const Json& value) {
    return "Pair{String, Any}(" + julia_quote(key) + ", " + julia_show(value) + ")";
}

/// What Julia's `String[string(v) for v in list]` makes of a list an option gives: each
/// item as `string()` writes it -- a text's characters, a number once, a dictionary's pairs.
std::vector<std::string> option_strings(const Json& list) {
    std::vector<std::string> out;
    switch (list.type()) {
        case Json::Type::Array:
            for (const Json& v : list.arr()) out.push_back(julia_string(v));
            break;
        case Json::Type::String: {
            const std::string& s = list.as_string();
            for (std::size_t i = 0; i < s.size();) {
                std::size_t n = 1;
                while (i + n < s.size() && (static_cast<unsigned char>(s[i + n]) & 0xc0) == 0x80) n++;
                out.push_back(s.substr(i, n));
                i += n;
            }
            break;
        }
        case Json::Type::Object:
            for (const auto& [k, v] : list.obj()) out.push_back(julia_pair(k, v));
            break;
        default: out.push_back(julia_string(list));
    }
    return out;
}

/// Julia's `isempty` of an option: an empty list, text or dictionary (a number never is).
bool empty_option(const Json& v) {
    return (v.is_array() || v.is_object() || v.is_string()) && v.size() == 0;
}

/// `v === false ? nothing : v`.
Json unless_false(const Json& v) { return v.is_bool() && !v.as_bool() ? Json() : v; }

/// `x + 1` as Julia's `Int` adds: wrapping.
long long plus_one(long long x) { return static_cast<long long>(static_cast<unsigned long long>(x) + 1u); }

// A queue a thread waits on; closed, it gives nothing more.
class Inbox {
public:
    void put(Json v) {
        {
            std::lock_guard<std::mutex> hold(mutex_);
            items_.push_back(std::move(v));
        }
        ready_.notify_one();
    }
    void close() {
        {
            std::lock_guard<std::mutex> hold(mutex_);
            closed_ = true;
        }
        ready_.notify_all();
    }
    bool take(Json& out) {
        std::unique_lock<std::mutex> hold(mutex_);
        ready_.wait(hold, [&] { return closed_ || !items_.empty(); });
        if (items_.empty()) return false;
        out = std::move(items_.front());
        items_.pop_front();
        return true;
    }

private:
    std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<Json> items_;
    bool closed_ = false;
};

// A run the page asked the engine to keep -- a run's results or a probabilistic run's
// sample -- and what it is asked, one question at a time.
struct Kept {
    std::mutex mutex;
    std::optional<Results> results;
    std::shared_ptr<const ProbabilisticResults> sample;
    std::set<std::string> labels;
    bool listed = false;
};

/// An edit that cannot be worked out over a held run's states -- they moved, or the model
/// remembers the path of the run -- so the page solves the model (`NotReused`).
struct NotReused : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// Whether a system remembers the path of its run (`system.memory` in the application): a
/// recorder, or a semi-analytical far-field path, which keeps what it took in -- neither of
/// which a system built afresh over kept states has.
bool remembers(const System& sys) {
    if (!sys.builder->MEM.empty()) return true;
    for (const EntryPtr& e : sys.builder->farf_layout)
        if (e->farf && e->farf->laplace) return true;
    return false;
}

/// What a kept sample is asked, besides `archive` and `forget`.
bool sample_query(const Json& op) { return op == "bands" || op == "realisations" || op == "column" || op == "realisation"; }

struct Service {
    std::ostream& out;
    std::mutex say_mutex;
    std::mutex cancel_mutex;
    std::set<std::string> cancelled;
    std::mutex kept_mutex;
    std::map<std::string, std::shared_ptr<Kept>> kept;
    int cores = 1;

    void say(const Json& event) {
        std::lock_guard<std::mutex> hold(say_mutex);
        out << json_text(event, 0) << "\n";
        out.flush();
    }
    bool stopped(const std::string& id) {
        std::lock_guard<std::mutex> hold(cancel_mutex);
        return cancelled.count(id) != 0;
    }

    // An error as the Julia engine's service says it (`_service_error`): named by its type,
    // its message without the name in front, the block of a build's or a solver's, a solver's
    // hint. What this engine does not do -- a model it cannot build yet, a solver it does not
    // have -- is `NotOnThisEngine`, which the page does itself.
    Json error_event(const std::string& id, const std::exception_ptr& e) {
        ErrorInfo info;
        try {
            std::rethrow_exception(e);
        } catch (const NotOnThisEngine& x) {
            info = {"NotOnThisEngine", x.what(), x.what(), std::nullopt, std::nullopt};
        } catch (const NotReused& x) {
            info = {"NotReused", x.what(), x.what(), std::nullopt, std::nullopt};
        } catch (...) {
            info = error_info(e);
            if (info.name == "NotSupported") info.name = "NotOnThisEngine";
        }
        return Json::object({{"id", Json(id)}, {"event", Json("error")}, {"name", Json(info.name)}, {"message", Json(info.message)},
                             {"block", info.block ? Json(*info.block) : Json()}, {"hint", info.hint ? Json(*info.hint) : Json()}});
    }

    // How df/dy was had, as the page's `Results.jacobian` says it.
    Json jacobian_of(Results& res) {
        const auto& j = res.system->jacobian;
        if (!(j && j->available)) return Json::object({{"available", Json(false)}, {"reason", (j && j->reason) ? Json(*j->reason) : Json()}});
        Json common = Json::object({{"colours", Json(j->colours)}, {"nnz", Json(static_cast<long long>(j->nnz))}, {"density", Json(j->density)},
                                    {"sparse", Json(res.stats.get("sparse") == Json(true))}, {"fill", res.stats.get("fill")}});
        if (j->budget_rows) common.set("budgetRows", Json(*j->budget_rows));
        Json out_ = Json::object();
        if (res.project->simulation.get("jacobian") == "numeric") {
            out_.set("available", Json(false));
            out_.set("asked", Json(true));
        } else {
            out_.set("available", Json(true));
            out_.set("constant", Json(j->constant));
        }
        for (const auto& [k, v] : common.obj()) out_.set(k, v);
        return out_;
    }

    // What the page reads of a run besides its series: the outputs as it lists them, each
    // parameter's one value with it, the nuclides, the size of the state vector, how df/dy
    // was had and what the zero floor held -- so that it holds a run the engine holds
    // without building the model itself.
    Json page_of(Results& res) {
        Json outs = Json::array();
        for (const Json& o : res.outputs()) {
            Json d = Json::object({{"kind", o.get("kind")}, {"block", o.get("block")}, {"nuclide", o.get("nuclide")},
                                   {"dims", o.get("dims").is_null() ? Json::array() : o.get("dims")}, {"index", o.get("index")}, {"label", o.get("label")},
                                   {"unit", o.get("unit")},
                                   {"constant", o.get("source") == "P" ? Json(res.system->P[static_cast<std::size_t>(o.get("offset").as_int())]) : Json()}});
            if (o.get("timeDependent") == Json(false)) d.set("timeDependent", Json(false));
            outs.push(d);
        }
        Json held = Json::array();
        for (const Json& h : res.held_at_zero()) held.push(h);
        return Json::object({{"outputs", outs}, {"nuclides", Json::array(res.project->material_names())},
                             {"stateCount", Json(static_cast<long long>(res.y.empty() ? 0 : res.y[0].size()))}, {"jacobian", jacobian_of(res)},
                             {"heldAtZero", held}});
    }

    // The run's log as the archive keeps it, a line an entry: the Julia engine's, with this
    // engine named as the build.
    Json run_log_of(Results& res) {
        RunLogOptions options;
        options.build = "C++ engine " + std::string(ENGINE_VERSION);
        Json lines = Json::array();
        for (const auto& line : split(run_log(res, options), '\n')) lines.push(Json(line));
        return lines;
    }

    // A run's archive -- without its states, and the run kept, when the page asked for that
    // -- with which realisation it replays, if it replays one (`_service_write_run`).
    void write_run(Results res, const std::string& id, const Json& options, const std::string& out_path, const Json& replayed = Json()) {
        ArchiveOptions archive;
        archive.log = run_log_of(res);
        Json extra = Json::object();
        if (!replayed.is_null()) extra.set("replayed", replayed);
        if (option(options, "keep") == Json(true)) {
            archive.states = false;
            extra.set("massBalance", res.mass_balance());
            extra.set("page", page_of(res));
            archive.extra = extra;
            write_file(out_path, dataset_archive(res, archive));
            auto held = std::make_shared<Kept>();
            held->results = std::move(res);
            std::lock_guard<std::mutex> hold(kept_mutex);
            kept[id] = held;
        } else {
            if (!extra.empty()) archive.extra = extra;
            write_file(out_path, dataset_archive(res, archive));
        }
    }

    void job(const Json& job) {
        std::string id = js_str(job.get("id").is_null() ? Json("") : job.get("id"));
        const Json& kind = job.get("kind");
        const Json& options = job.get("options");
        double started = now_s();
        double last = 0.0;
        // Progress said at most every tenth of a second.
        auto tell = [&](Json event) {
            double now = now_s();
            if (now - last >= 0.1) {
                last = now;
                say(event);
            }
        };
        auto stage = [&](const char* what) { say(Json::object({{"id", Json(id)}, {"event", Json("stage")}, {"stage", Json(what)}})); };
        try {
            // A job with no model reads the empty text (`get(job, "model", "")`).
            const Json model = job.has("model") ? job.get("model") : Json("");
            // A check is of a run held here, and reads no model of its own.
            Json raw = kind == "check-run" ? Json::object() : model.is_string() ? parse_json(model.as_string()) : model;
            // (`from_json`, before anything else is said.)
            if (!raw.is_object()) throw ArgumentError("A model is one JSON object");
            if (!(kind == "run" || kind == "probabilistic" || kind == "replay" || kind == "local-sensitivity" || kind == "calibrate" ||
                  kind == "check-run" || kind == "re-evaluate"))
                throw ArgumentError("'" + julia_string(kind) + "' is not a kind of job this engine runs");
            // The model is read as a project where the Julia engine's job reads it -- after its
            // stage is said and its options are taken -- so that a model it refuses is refused at
            // the same point.
            auto project_of = [&] { return std::make_shared<const Project>(raw); };
            std::string out_path = js_str(job.get("out"));
            if (kind == "run") {
                stage("solving");
                RunOptions run_options;
                run_options.on_progress = [&](double fraction, double at) {
                    tell(Json::object({{"id", Json(id)}, {"event", Json("progress")}, {"fraction", Json(fraction)}, {"at", Json(at)}}));
                    return !stopped(id);
                };
                Results res = run_project(project_of(), nullptr, run_options);
                if (stopped(id)) throw ServiceStopped();
                stage("writing");
                write_run(std::move(res), id, options, out_path);
            } else if (kind == "re-evaluate") {
                // An edit worked out over the states of a run held here, held in its place: only
                // the algebra over them changes, which is a build without a single step -- as the
                // page re-evaluates a run it holds itself.
                const std::string run_id = js_str(option(options, "run", Json("")));
                std::shared_ptr<Kept> held;
                {
                    std::lock_guard<std::mutex> hold(kept_mutex);
                    auto it = kept.find(run_id);
                    if (it != kept.end()) held = it->second;
                }
                if (!held || !held->results)
                    throw ArgumentError("This engine no longer holds that run: it may have been restarted since, or the run let go of. "
                                        "Run it again.");
                stage("building");
                const Results& was = *held->results;
                auto project = project_of();
                const double built = now_s();
                auto system = std::make_shared<System>(project);
                if (remembers(*system) || remembers(*was.system)) throw NotReused("the model remembers");
                if (layout_signature(*system) != layout_signature(*was.system)) throw NotReused("the states moved");
                Results res;
                res.project = project;
                res.system = system;
                res.t = was.t;
                res.y = was.y;
                res.stats = was.stats.copy();
                res.timing = was.timing.is_object() ? was.timing.copy() : Json::object();
                res.timing.set("build_ms", Json((now_s() - built) * 1000));
                res.kept = run_state(*system);
                stage("writing");
                write_run(std::move(res), id, options, out_path);
            } else if (kind == "check-run") {
                // The run held here for the page, solved again more carefully here and set
                // against itself: the page need not fetch it to check it.
                const std::string run_id = js_str(option(options, "run", Json("")));
                std::shared_ptr<Kept> held;
                {
                    std::lock_guard<std::mutex> hold(kept_mutex);
                    auto it = kept.find(run_id);
                    if (it != kept.end()) held = it->second;
                }
                if (!held || !held->results)
                    throw ArgumentError("This engine no longer holds that run: it may have been restarted since, or the run let go of. "
                                        "Run it again.");
                stage("building");
                Json report = check_run(*held->results, [&](std::shared_ptr<const Project> careful) {
                    stage("solving");
                    RunOptions run_options;
                    run_options.on_progress = [&](double fraction, double at) {
                        tell(Json::object({{"id", Json(id)}, {"event", Json("progress")}, {"fraction", Json(fraction)}, {"at", Json(at)}}));
                        return !stopped(id);
                    };
                    Results res = run_project(careful, nullptr, run_options);
                    if (stopped(id)) throw ServiceStopped();
                    return res;
                });
                stage("writing");
                write_file(out_path, json_text(report, 0));
            } else if (kind == "calibrate") {
                stage("solving");
                CalibrateOptions calibration;
                calibration.targets = option(options, "targets");
                calibration.variables = option(options, "variables");
                calibration.method = option(options, "method");
                calibration.max_evals = option(options, "maxEvals");
                calibration.seed = option(options, "seed");
                // Each step's best, as JSON carries it to the page: a misfit that is not a number is null.
                calibration.on_progress = [&](const CalibrateStep& p) {
                    tell(Json::object({{"id", Json(id)},
                                       {"event", Json("progress")},
                                       {"detail", Json::object({{"evals", Json(p.evals)},
                                                                {"fx", Json(p.fx)},
                                                                {"best", Json(p.best)},
                                                                {"values", p.values ? Json::array(*p.values) : Json()}})}}));
                };
                calibration.signal = [&] { return stopped(id); };
                Json result = calibrate(project_of(), calibration);
                if (stopped(id)) throw ServiceStopped();
                write_file(out_path, json_text(result, 0));
            } else if (kind == "local-sensitivity") {
                stage("solving");
                SensitivityOptions sensitivity;
                sensitivity.on_progress = [&](double fraction, double at) {
                    tell(Json::object({{"id", Json(id)}, {"event", Json("progress")}, {"fraction", Json(fraction)}, {"at", Json(at)}}));
                    return !stopped(id);
                };
                SensitivityRun r = run_sensitivity(project_of(), option(options, "parameters"), sensitivity);
                if (stopped(id)) throw ServiceStopped();
                stage("writing");
                // Every state the page shows, by its name, with its derivatives.
                Json states = Json::array();
                for (const Json& s : r.series) {
                    if (s.get("hidden") == Json(true)) continue;
                    const std::size_t at = static_cast<std::size_t>(s.get("offset").as_int());
                    Json sens = Json::array();
                    for (const auto& block : r.sens) sens.push(Json::array(block[at]));
                    states.push(Json::object({{"name", s.get("label")}, {"y", Json::array(r.y[at])}, {"sens", sens}}));
                }
                write_file(out_path, json_text(Json::object({{"t", Json::array(r.t)}, {"chosen", r.chosen}, {"stats", r.stats}, {"states", states}}), 0));
            } else if (kind == "replay") {
                stage("solving");
                const Json varied = option(options, "varied");
                const Json iterations = option(options, "iterations");
                const Json tornado = option(options, "tornado");
                long long number = plus_one(int_of(option(options, "index", Json(0))));
                DesignOptions design;
                design.seed = Json(int_of(option(options, "seed", Json(1))));
                if (!iterations.is_null()) design.iterations = static_cast<double>(int_of(iterations));
                design.latin = !(option(options, "latin", Json(true)) == Json(false));
                if (!varied.is_null()) design.varied = option_strings(varied);
                design.tornado = unless_false(tornado);
                Replay r = run_realisation(project_of(), number, design);
                stage("writing");
                Json values = Json::array();
                for (const auto& v : r.values)
                    values.push(Json::object({{"name", Json(v.name)}, {"value", Json(v.value)}, {"held", Json(v.held)}}));
                Json replayed = Json::object({{"index", Json(r.number - 1)}, {"iterations", Json(r.iterations)}, {"values", values}});
                write_run(std::move(r.results), id, options, out_path, replayed);
            } else {
                stage("building");
                const Json blocks = option(options, "blocks");
                const Json varied = option(options, "varied");
                const Json tornado = option(options, "tornado");
                const Json gsa = option(options, "gsa");
                // A sample the page asked the engine to keep is this machine's to hold, and may
                // come to what the page drew from its memory rather than a tab's limits. A sample
                // is what `design_for` runs when neither a tornado nor a design is asked for.
                const bool keeping = option(options, "keep") == Json(true) && !pb_truthy_opt(tornado) && !pb_truthy_opt(gsa);
                const Json most = option(options, "most");
                const Json asked = option(options, "asked");
                ProbabilisticOptions po;
                po.iterations = static_cast<double>(int_of(option(options, "iterations", Json(100))));
                po.most_bytes = keeping && (most.is_number() || most.is_bool()) ? int_of(most) : PROB_MOST_BYTES;
                po.asked_bytes = keeping && (asked.is_number() || asked.is_bool()) ? int_of(asked) : PROB_MOST_BYTES_ASKED;
                po.seed = Json(int_of(option(options, "seed", Json(1))));
                po.latin = !(option(options, "latin", Json(true)) == Json(false));
                if (!varied.is_null()) po.varied = option_strings(varied);
                if (!(blocks.is_null() || empty_option(blocks))) po.keep = option_strings(blocks);
                po.threads = static_cast<int>(std::clamp(int_of(option(options, "workers", Json(static_cast<long long>(cores)))), 1LL,
                                                         static_cast<long long>(cores)));
                po.large = option(options, "large") == Json(true);
                // A tornado, or a sensitivity design, in place of a sample.
                po.tornado = unless_false(tornado);
                po.gsa = unless_false(gsa);
                po.on_progress = [&](long long done, long long total) {
                    if (stopped(id)) throw ServiceStopped();
                    tell(Json::object({{"id", Json(id)}, {"event", Json("progress")}, {"done", Json(done)}, {"total", Json(total)}}));
                };
                auto prob = std::make_shared<ProbabilisticResults>(run_probabilistic(project_of(), po));
                stage("writing");
                // A sample the page asked the engine to keep goes without its series.
                SampleArchiveOptions archive;
                archive.series = !keeping;
                write_file(out_path, sample_archive(*prob, archive));
                if (keeping) {
                    auto held = std::make_shared<Kept>();
                    held->sample = prob;
                    std::lock_guard<std::mutex> hold(kept_mutex);
                    kept[id] = held;
                }
            }
            say(Json::object({{"id", Json(id)}, {"event", Json("done")}, {"out", Json(out_path)},
                              {"ms", Json(static_cast<long long>(std::nearbyint((now_s() - started) * 1000)))}}));
        } catch (...) {
            std::exception_ptr e = std::current_exception();
            bool aborted = false;
            try {
                std::rethrow_exception(e);
            } catch (const ServiceStopped&) {
                aborted = true;
            } catch (const SolverError& x) {
                aborted = x.kind == "aborted";
            } catch (...) {
            }
            if (aborted || stopped(id)) say(Json::object({{"id", Json(id)}, {"event", Json("cancelled")}}));
            else say(error_event(id, e));
        }
    }

    // A question about a kept sample, its answer written to `q["out"]` as little-endian
    // doubles, laid out as the other engines lay them out (`_service_sample_answer`): a series
    // numbered from 0 as the sample's meta lists them, the kept series and then each varied
    // parameter.
    void sample_answer(const Json& op, const ProbabilisticResults& prob, const Json& q) {
        if (op == "archive") {
            write_file(js_str(q.get("out")), sample_archive(prob));
            return;
        }
        write_file(js_str(q.get("out")), sample_answer_bytes(op, prob, q));
    }

    void query(const Json& q) {
        std::string id = js_str(q.get("id").is_null() ? Json("") : q.get("id"));
        const Json& op = q.get("op");
        std::string run_id = js_str(q.get("run").is_null() ? Json("") : q.get("run"));
        try {
            if (op == "forget") {
                {
                    std::lock_guard<std::mutex> hold(kept_mutex);
                    kept.erase(run_id);
                }
                say(Json::object({{"id", Json(id)}, {"event", Json("done")}}));
                return;
            }
            std::shared_ptr<Kept> held;
            {
                std::lock_guard<std::mutex> hold(kept_mutex);
                auto it = kept.find(run_id);
                if (it != kept.end()) held = it->second;
            }
            if (!held) throw ArgumentError("This engine no longer holds that run: it may have been restarted since, or the run let go of. Run it again.");
            std::lock_guard<std::mutex> hold(held->mutex);
            if (held->sample) {
                sample_answer(op, *held->sample, q);
            } else {
                Results& res = *held->results;
                if (op == "series") {
                    const Json& asked = q.get("labels");
                    std::vector<std::string> labels = asked.is_null() ? std::vector<std::string>{} : option_strings(asked);
                    if (!held->listed) {
                        for (const Json& o : res.outputs()) held->labels.insert(o.get("label").as_string());
                        held->listed = true;
                    }
                    std::vector<std::string> missing;
                    for (const auto& l : labels)
                        if (!held->labels.count(l)) missing.push_back(l);
                    if (!missing.empty())
                        throw ArgumentError("The engine's run has no series called '" + missing[0] + "'" +
                                            (missing.size() > 1 ? " (nor " + std::to_string(missing.size() - 1) + " more)" : "") + ".");
                    std::vector<Json> outs;
                    for (const auto& l : labels) outs.push_back(res.find_output(l));
                    std::string data;
                    if (!outs.empty())
                        for (const auto& col : res.series_many(outs)) data += f64_bytes(col);
                    write_file(js_str(q.get("out")), data);
                } else if (op == "archive") {
                    ArchiveOptions archive;
                    archive.log = run_log_of(res);
                    write_file(js_str(q.get("out")), dataset_archive(res, archive));
                } else if (sample_query(op)) {
                    throw ArgumentError("That run is not a probabilistic run: it has no realisations to ask about.");
                } else {
                    throw ArgumentError("'" + julia_string(op) + "' is not something this engine is asked");
                }
            }
        } catch (...) {
            say(error_event(id, std::current_exception()));
            return;
        }
        say(Json::object({{"id", Json(id)}, {"event", Json("done")}, {"out", q.get("out")}}));
    }
};

}  // namespace

std::string sample_answer_bytes(const Json& op, const ProbabilisticResults& prob, const Json& q) {
    if (!sample_query(op)) throw ArgumentError("'" + julia_string(op) + "' is not something this engine is asked of a probabilistic run");
    const long long n = prob.iterations;
    const std::size_t count = an_count(prob);
    std::vector<double> data;
    if (op == "bands") {
        const Json& mask = q.get("mask");
        if (!mask.is_null() && mask_length(mask) != n)
            throw ArgumentError("The mask has " + std::to_string(mask_length(mask)) + " entries for " + std::to_string(n) + " realisations.");
        for (const Band& band : bands(prob, q.get("percentiles"), mask.is_null() ? nullptr : &mask)) {
            for (const auto& y : band.q) data.insert(data.end(), y.begin(), y.end());
            data.insert(data.end(), band.mean.begin(), band.mean.end());
            data.insert(data.end(), band.sd.sd.begin(), band.sd.sd.end());
            for (long long c : band.sd.n) data.push_back(static_cast<double>(c));
            for (const auto* part : {&band.med.err_lo, &band.med.err_hi, &band.med.body_lo, &band.med.body_hi})
                data.insert(data.end(), part->begin(), part->end());
        }
        return f64_bytes(data);
    }
    // The series asked for, as Julia goes through `something(q["series"], [])`: a list's
    // items, a number once, a text's characters, a dictionary's pairs.
    const Json& asked = q.get("series");
    std::vector<Json> ks;
    std::vector<std::string> shown;   // what is not a series number, as Julia's `repr` shows it
    switch (asked.type()) {
        case Json::Type::Null: break;
        case Json::Type::Array:
            for (const Json& k : asked.arr()) {
                ks.push_back(k);
                shown.push_back(julia_show(k));
            }
            break;
        case Json::Type::String:
            for (const std::string& c : option_strings(asked)) {
                ks.push_back(Json(c));
                shown.push_back("'" + (c == "'" ? std::string("\\'") : c == "\\" ? std::string("\\\\") : c) + "'");
            }
            break;
        case Json::Type::Object:
            for (const auto& [k, v] : asked.obj()) {
                ks.push_back(Json());
                shown.push_back(julia_pair(k, v));
            }
            break;
        default:
            ks.push_back(asked);
            shown.push_back(julia_show(asked));
    }
    for (std::size_t a = 0; a < ks.size(); a++) {
        const Json& k = ks[a];
        bool ok = k.is_int() && !asked.is_object() && !asked.is_string() && k.as_int() >= 0 && static_cast<unsigned long long>(k.as_int()) < count;
        if (!ok) throw ArgumentError("The probabilistic run has no series " + shown[a] + ": it has " + std::to_string(count) + ", from 0.");
    }
    for (const Json& kj : ks) {
        // Realisations down, the times (one for a varied parameter) across, in the precision
        // they are held in until what was asked is taken out.
        const std::size_t k = static_cast<std::size_t>(kj.as_int());
        SeriesMatrix M = an_matrix(prob, k + 1);
        if (op == "realisations") {
            for (long long i = 0; i < M.rows; i++)
                for (std::size_t j = 0; j < M.cols; j++) data.push_back(M(i, j));
        } else if (op == "column") {
            const Json& at = q.get("at");
            long long j = std::clamp(int_of(at.is_null() ? Json(0) : at), 0LL, static_cast<long long>(M.cols) - 1);
            for (long long i = 0; i < M.rows; i++) data.push_back(M(i, static_cast<std::size_t>(j)));
        } else {
            // Brought into the realisations held: a part of a run holds fewer than the design has.
            const Json& index = q.get("index");
            const long long wanted = int_of(index.is_null() ? Json(0) : index);
            if (M.rows == 0)
                throw JuliaError("BoundsError", "BoundsError: attempt to access 0x" + std::to_string(M.cols) + " Matrix{Float64} at index [0, :]");
            const long long i = std::clamp(wanted, 0LL, M.rows - 1);
            for (std::size_t j = 0; j < M.cols; j++) data.push_back(M(i, j));
        }
    }
    return f64_bytes(data);
}

void serve_stdio(std::istream& input, std::ostream& output) {
    Service service{output, {}, {}, {}, {}, {}};
    service.cores = static_cast<int>(std::max(1u, std::thread::hardware_concurrency()));
    Inbox jobs, queries;
    const long long cores = service.cores;
    std::thread reader([&] {
        std::string line;
        while (std::getline(input, line)) {
            if (js_trim(line).empty()) continue;
            Json msg;
            try {
                msg = parse_json(line);
            } catch (const std::exception&) {
                continue;
            }
            if (!msg.is_object()) continue;
            const Json& op = msg.get("op");
            if (op == "cancel") {
                std::lock_guard<std::mutex> hold(service.cancel_mutex);
                service.cancelled.insert(js_str(msg.get("id").is_null() ? Json("") : msg.get("id")));
            } else if (op == "job") {
                jobs.put(msg);
            } else if (op == "series" || op == "archive" || op == "forget" || sample_query(op)) {
                queries.put(msg);
            }
        }
        jobs.close();
        queries.close();
    });
    // Beside the jobs: a page reading one run while the next one solves.
    std::thread answering([&] {
        Json q;
        while (queries.take(q)) service.query(q);
    });
    service.say(Json::object({{"event", Json("ready")}, {"engine", Json("cpp")}, {"version", Json(ENGINE_VERSION)}, {"threads", Json(cores)},
                              {"cores", Json(cores)}, {"concurrent", Json(cores)}}));
    // Each job a thread of its own, as many at once as the server sends -- which is as many
    // as `concurrent` says.
    std::vector<std::thread> running;
    Json job;
    while (jobs.take(job)) {
        std::string id = js_str(job.get("id").is_null() ? Json("") : job.get("id"));
        if (service.stopped(id)) {
            service.say(Json::object({{"id", Json(id)}, {"event", Json("cancelled")}}));
            continue;
        }
        running.emplace_back([&service, job] { service.job(job); });
    }
    // What was asked before the input closed is done and answered first.
    for (auto& t : running) t.join();
    answering.join();
    reader.join();
}

}  // namespace kompartment
