#include "service.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <mutex>
#include <set>
#include <thread>

#include "engine/farfield.hpp"
#include "engine/jacobian.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "io/dataset.hpp"
#include "model/names.hpp"
#include "model/simulation.hpp"
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

// A run the page asked the engine to keep, and what it is asked one question at a time.
struct Kept {
    std::mutex mutex;
    Results results;
    std::set<std::string> labels;
    bool listed = false;
};

struct Service {
    std::ostream& out;
    std::mutex say_mutex;
    std::mutex cancel_mutex;
    std::set<std::string> cancelled;
    std::mutex kept_mutex;
    std::map<std::string, std::shared_ptr<Kept>> kept;

    void say(const Json& event) {
        std::lock_guard<std::mutex> hold(say_mutex);
        out << json_text(event, 0) << "\n";
        out.flush();
    }
    bool stopped(const std::string& id) {
        std::lock_guard<std::mutex> hold(cancel_mutex);
        return cancelled.count(id) != 0;
    }

    Json error_event(const std::string& id, const char* name, const std::string& message, const std::optional<std::string>& block = std::nullopt,
                     const std::optional<std::string>& hint = std::nullopt) {
        return Json::object({{"id", Json(id)}, {"event", Json("error")}, {"name", Json(name)}, {"message", Json(message)},
                             {"block", block ? Json(*block) : Json()}, {"hint", hint ? Json(*hint) : Json()}});
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

    void job(const Json& job) {
        std::string id = js_str(job.get("id").is_null() ? Json("") : job.get("id"));
        const Json& kind = job.get("kind");
        const Json& options = job.get("options");
        double started = now_s();
        double last = 0.0;
        try {
            const Json& model = job.get("model");
            Json raw = model.is_string() ? parse_json(model.as_string()) : model;
            if (!(kind == "run")) {
                std::string what = kind == "probabilistic" ? "a probabilistic run" : kind == "replay" ? "one realisation of a probabilistic run"
                                   : kind == "calibrate" ? "a calibration" : kind == "local-sensitivity" ? "a local sensitivity" : "'" + js_text(kind) + "'";
                throw NotOnThisEngine("The C++ engine runs a model; " + what + " is not something it does yet.");
            }
            say(Json::object({{"id", Json(id)}, {"event", Json("stage")}, {"stage", Json("solving")}}));
            auto project = std::make_shared<const Project>(raw);
            RunOptions run_options;
            run_options.on_progress = [&](double fraction, double at) {
                double now = now_s();
                if (now - last >= 0.1) {
                    last = now;
                    say(Json::object({{"id", Json(id)}, {"event", Json("progress")}, {"fraction", Json(fraction)}, {"at", Json(at)}}));
                }
                return !stopped(id);
            };
            Results res = run_project(project, nullptr, run_options);
            if (stopped(id)) {
                say(Json::object({{"id", Json(id)}, {"event", Json("cancelled")}}));
                return;
            }
            say(Json::object({{"id", Json(id)}, {"event", Json("stage")}, {"stage", Json("writing")}}));
            ArchiveOptions archive;
            archive.log = run_log_of(res);
            std::string out_path = js_str(job.get("out"));
            if (options.get("keep") == Json(true)) {
                archive.states = false;
                archive.extra = Json::object({{"massBalance", res.mass_balance()}, {"page", page_of(res)}});
                write_file(out_path, dataset_archive(res, archive));
                auto held = std::make_shared<Kept>();
                held->results = std::move(res);
                std::lock_guard<std::mutex> hold(kept_mutex);
                kept[id] = held;
            } else {
                write_file(out_path, dataset_archive(res, archive));
            }
            say(Json::object({{"id", Json(id)}, {"event", Json("done")}, {"out", Json(out_path)},
                              {"ms", Json(static_cast<long long>(std::llround((now_s() - started) * 1000)))}}));
        } catch (const SolverError& e) {
            if (stopped(id) || e.kind == "aborted") say(Json::object({{"id", Json(id)}, {"event", Json("cancelled")}}));
            else say(error_event(id, "SolverError", e.message, e.block_name, e.hint));
        } catch (const BuildError& e) {
            say(error_event(id, "BuildError", e.what(), e.block_name));
        } catch (const ValidationError& e) {
            say(error_event(id, "ValidationError", e.what(), e.block));
        } catch (const NotOnThisEngine& e) {
            say(error_event(id, "NotOnThisEngine", e.what()));
        } catch (const NotSupported& e) {
            // A model this engine cannot build yet is the page's to solve, as what it does not do is.
            say(error_event(id, "NotOnThisEngine", e.what()));
        } catch (const FarfError& e) {
            say(error_event(id, "FarfError", e.what()));
        } catch (const JsonError& e) {
            say(error_event(id, "JSONError", e.what()));
        } catch (const std::exception& e) {
            say(error_event(id, "Error", e.what()));
        }
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
            if (!held)
                throw std::invalid_argument("This engine no longer holds that run: it may have been restarted since, or the run let go of. Run it again.");
            std::lock_guard<std::mutex> hold(held->mutex);
            Results& res = held->results;
            if (op == "series") {
                std::vector<std::string> labels;
                if (q.get("labels").is_array())
                    for (const Json& x : q.get("labels").arr()) labels.push_back(js_str(x));
                if (!held->listed) {
                    for (const Json& o : res.outputs()) held->labels.insert(o.get("label").as_string());
                    held->listed = true;
                }
                std::vector<std::string> missing;
                for (const auto& l : labels)
                    if (!held->labels.count(l)) missing.push_back(l);
                if (!missing.empty())
                    throw std::invalid_argument("The engine's run has no series called '" + missing[0] + "'" +
                                                (missing.size() > 1 ? " (nor " + std::to_string(missing.size() - 1) + " more)" : "") + ".");
                std::vector<Json> outs;
                for (const auto& l : labels) outs.push_back(res.find_output(l));
                std::string data;
                if (!outs.empty())
                    for (const auto& col : res.series_many(outs)) data.append(reinterpret_cast<const char*>(col.data()), col.size() * 8);
                write_file(js_str(q.get("out")), data);
            } else if (op == "archive") {
                ArchiveOptions archive;
                archive.log = run_log_of(res);
                write_file(js_str(q.get("out")), dataset_archive(res, archive));
            } else if (op == "bands" || op == "realisations" || op == "column" || op == "realisation") {
                throw std::invalid_argument("That run is not a probabilistic run: it has no realisations to ask about.");
            } else {
                throw std::invalid_argument("'" + js_text(op) + "' is not something this engine is asked");
            }
        } catch (const SolverError& e) {
            say(error_event(id, "SolverError", e.message, e.block_name, e.hint));
            return;
        } catch (const std::exception& e) {
            say(error_event(id, "ArgumentError", e.what()));
            return;
        }
        say(Json::object({{"id", Json(id)}, {"event", Json("done")}, {"out", q.get("out")}}));
    }
};

}  // namespace

void serve_stdio(std::istream& input, std::ostream& output) {
    Service service{output, {}, {}, {}, {}, {}};
    Inbox jobs, queries;
    unsigned cores = std::max(1u, std::thread::hardware_concurrency());
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
            } else if (op == "series" || op == "archive" || op == "forget" || op == "bands" || op == "realisations" || op == "column" ||
                       op == "realisation") {
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
    service.say(Json::object({{"event", Json("ready")}, {"engine", Json("cpp")}, {"version", Json(ENGINE_VERSION)}, {"threads", Json(static_cast<long long>(cores))},
                              {"cores", Json(static_cast<long long>(cores))}, {"concurrent", Json(static_cast<long long>(cores))}}));
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
