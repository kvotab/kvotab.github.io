// The engine as the application's local server talks to it (src/service.cpp): the
// messages of a run, of a run it is asked to keep and of the questions asked about
// that run afterwards, and what it says to what it does not do; the run's log in the
// archive it writes; a run that meets a value that is not a number, said where it
// starts; local sensitivities answered as the Julia engine's service answers them
// (tools/localsens_fixtures.jl keeps what that said and wrote), refused, and stopped; and
// calibrations the same way (tools/calibrate_fixtures.jl): each step's best said as a
// progress detail, the answer written, the refusals -- and a search stopped part way.
//
// The service is driven here as serve.py drives it -- a line in, the lines that
// answer it out -- through two streams of the test's own, so that a question is
// asked only once the job before it has answered.

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <iostream>
#include <mutex>
#include <regex>
#include <streambuf>
#include <string>
#include <thread>
#include <vector>

#if defined(KOMPARTMENT_HAVE_ZLIB)
#include <zlib.h>
#endif

#include "check.hpp"
#include "engine/analysis.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "model/names.hpp"
#include "service.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
std::string kept_text(const std::string& text) { return text.size() <= 300 ? "=" + text : "#" + fnv(text); }

/// The answer with its time taken (`"ms":` and digits) said as 0, as the fixtures keep it.
std::string without_ms(std::string text) {
    const std::string key = "\"ms\":";
    for (std::size_t at = text.find(key); at != std::string::npos; at = text.find(key, at + key.size())) {
        std::size_t end = at + key.size();
        while (end < text.size() && text[end] >= '0' && text[end] <= '9') end++;
        text.replace(at + key.size(), end - (at + key.size()), "0");
    }
    return text;
}

/// One entry of a ZIP archive, by name, as the engine writes them (stored or deflated); empty
/// when it is not there.
std::string zip_entry(const std::string& zip, const std::string& name) {
    auto u16 = [&](std::size_t at) { return static_cast<std::uint32_t>(static_cast<unsigned char>(zip[at]) | static_cast<unsigned char>(zip[at + 1]) << 8); };
    auto u32 = [&](std::size_t at) { return u16(at) | u16(at + 2) << 16; };
    for (std::size_t at = 0; at + 30 <= zip.size() && u32(at) == 0x04034b50;) {
        const std::uint32_t method = u16(at + 8), packed = u32(at + 18), size = u32(at + 22), name_len = u16(at + 26), extra = u16(at + 28);
        const std::size_t data = at + 30 + name_len + extra;
        if (zip.compare(at + 30, name_len, name) == 0) {
            if (method == 0) return zip.substr(data, size);
#if defined(KOMPARTMENT_HAVE_ZLIB)
            std::string out(size, '\0');
            z_stream zs{};
            if (inflateInit2(&zs, -MAX_WBITS) != Z_OK) return "";
            zs.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(zip.data() + data));
            zs.avail_in = packed;
            zs.next_out = reinterpret_cast<Bytef*>(out.data());
            zs.avail_out = size;
            const int done = inflate(&zs, Z_FINISH);
            inflateEnd(&zs);
            return done == Z_STREAM_END ? out : "";
#else
            return "";
#endif
        }
        at = data + packed;
    }
    return "";
}

/// What the service reads: lines handed over one at a time, the reader waiting for the next.
class Lines : public std::streambuf {
public:
    void put(const std::string& line) {
        std::lock_guard<std::mutex> hold(mutex_);
        waiting_.push_back(line + "\n");
        ready_.notify_all();
    }
    void close() {
        std::lock_guard<std::mutex> hold(mutex_);
        closed_ = true;
        ready_.notify_all();
    }

protected:
    int_type underflow() override {
        std::unique_lock<std::mutex> hold(mutex_);
        ready_.wait(hold, [&] { return closed_ || !waiting_.empty(); });
        if (waiting_.empty()) return traits_type::eof();
        current_ = std::move(waiting_.front());
        waiting_.pop_front();
        setg(current_.data(), current_.data(), current_.data() + current_.size());
        return traits_type::to_int_type(current_[0]);
    }

private:
    std::mutex mutex_;
    std::condition_variable ready_;
    std::deque<std::string> waiting_;
    std::string current_;
    bool closed_ = false;
};

/// What the service writes: every line kept, and a wait for the one that ends a message's answer.
class Answers : public std::streambuf {
public:
    /// The events answering `id`, up to and with the one that ends it (done, error, cancelled).
    std::vector<Json> until_ended(const std::string& id) {
        std::unique_lock<std::mutex> hold(mutex_);
        std::vector<Json> mine;
        std::size_t seen = 0;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
        for (;;) {
            for (; seen < events_.size(); seen++) {
                const Json& e = events_[seen];
                if (!(e.get("id") == Json(id))) continue;
                mine.push_back(e);
                const Json& what = e.get("event");
                if (what == "done" || what == "error" || what == "cancelled") return mine;
            }
            if (arrived_.wait_until(hold, deadline) == std::cv_status::timeout) return mine;
        }
    }
    Json first() {
        std::unique_lock<std::mutex> hold(mutex_);
        arrived_.wait_for(hold, std::chrono::seconds(60), [&] { return !events_.empty(); });
        return events_.empty() ? Json() : events_[0];
    }
    /// Whether an event of this kind has been said under `id`.
    bool has_event(const std::string& id, const char* what) {
        std::lock_guard<std::mutex> hold(mutex_);
        for (const Json& e : events_)
            if (e.get("id") == Json(id) && e.get("event") == what) return true;
        return false;
    }
    bool every_line_json() {
        std::lock_guard<std::mutex> hold(mutex_);
        return !not_json_;
    }

protected:
    int_type overflow(int_type c) override {
        if (c == traits_type::eof()) return c;
        if (c != '\n') {
            line_.push_back(static_cast<char>(c));
            return c;
        }
        std::lock_guard<std::mutex> hold(mutex_);
        try {
            events_.push_back(parse_json(line_));
        } catch (const std::exception&) {
            not_json_ = true;
        }
        line_.clear();
        arrived_.notify_all();
        return c;
    }

private:
    std::mutex mutex_;
    std::condition_variable arrived_;
    std::vector<Json> events_;
    std::string line_;
    bool not_json_ = false;
};

std::string name_of(const std::vector<Json>& events) {
    if (events.empty()) return "(no answer)";
    const Json& last = events.back();
    if (last.get("event") == "error") return last.get("name").as_string();
    return last.get("event").as_string();
}

std::string message_of(const std::vector<Json>& events) {
    if (events.empty() || !events.back().get("message").is_string()) return "";
    return events.back().get("message").as_string();
}

}  // namespace

int main() {
    namespace fs = std::filesystem;
    const fs::path scratch = fs::temp_directory_path() / ("kompartment-cpp-service-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    fs::create_directories(scratch);
    const std::string examples = std::string(KOMPARTMENT_REPO) + "/examples/";
    const std::string model_text = check::read_file(examples + "decay-chain.json");

    Lines in_buffer;
    Answers out_buffer;
    std::istream input(&in_buffer);
    std::ostream output(&out_buffer);
    std::thread engine([&] { serve_stdio(input, output); });

    // It says it is there, and who it is.
    {
        const Json ready = out_buffer.first();
        CHECK(ready.get("event") == "ready");
        CHECK(ready.get("engine") == "cpp");
        CHECK(ready.get("version") == Json(std::string(ENGINE_VERSION)));
        CHECK(ready.get("concurrent").is_number() && ready.get("concurrent").as_double() >= 1);
    }

    // A run, written as Save with results writes it.
    const std::string whole = (scratch / "whole.zip").string();
    {
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("a")}, {"kind", Json("run")}, {"model", Json(model_text)}, {"out", Json(whole)}}), 0));
        const auto events = out_buffer.until_ended("a");
        CHECK_MSG(name_of(events) == "done", "a run ends done: " + name_of(events) + " " + message_of(events));
        bool solving = false, writing = false;
        for (const Json& e : events) {
            if (e.get("event") == "stage" && e.get("stage") == "solving") solving = true;
            if (e.get("event") == "stage" && e.get("stage") == "writing") writing = true;
        }
        CHECK(solving && writing);
        CHECK(!events.empty() && events.back().get("out") == Json(whole));
        CHECK(!events.empty() && events.back().get("ms").is_number());
        const std::string zip = fs::exists(whole) ? check::read_file(whole) : "";
        CHECK(zip.size() > 4 && zip.compare(0, 2, "PK") == 0);

        // The run's log in it, a line an entry, as the Julia engine's service writes it: this
        // engine named as the build, then when, the model, its settings and how it went --
        // what a run made here says, line for line, but for the date and the timings.
        const std::string meta_text = zip_entry(zip, "results/meta.json");
        CHECK_MSG(!meta_text.empty(), "the archive holds results/meta.json");
        const Json meta = meta_text.empty() ? Json::object() : parse_json(meta_text);
        const Json& log = meta.get("log");
        CHECK_MSG(log.is_array() && log.size() > 10, "the archive holds the run's log");
        if (log.is_array() && log.size() > 10) {
            CHECK_EQ(log[std::size_t{0}].as_string(), "Kompartment run log \xe2\x80\x94 build C++ engine " + std::string(ENGINE_VERSION));
            CHECK_MSG(std::regex_match(log[std::size_t{1}].as_string(), std::regex(R"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z)")),
                      "the second line says when, as toISOString writes it: " + log[std::size_t{1}].as_string());
            CHECK_EQ(log[std::size_t{2}].as_string(), "model: " + parse_json(model_text).get("name").as_string());
            auto project = std::make_shared<const Project>(parse_json(model_text));
            Results here = run_project(project, nullptr, RunOptions{});
            RunLogOptions options;
            options.build = "C++ engine " + std::string(ENGINE_VERSION);
            const std::vector<std::string> lines = split(run_log(here, options), '\n');
            CHECK_EQ(lines.size(), log.size());
            for (std::size_t i = 0; i < lines.size() && i < log.size(); i++) {
                if (i == 1 || starts_with(lines[i], "  compile: ")) continue;
                CHECK_MSG(log[i].as_string() == lines[i], "the log's line " + std::to_string(i) + ": " + log[i].as_string() + ", here " + lines[i]);
            }
        }
    }

    // A run that meets a value that is not a number: where it starts, and the block it starts in.
    {
        Json bad = parse_json(model_text);
        bad.set("parameters", Json::array({Json::object({{"name", Json("N")}, {"value", Json(0)}})}));
        bad.set("expressions", Json::array({Json::object({{"name", Json("C")}, {"equation", Json("N/N")}})}));
        Json first = bad.get("compartments")[std::size_t{0}].copy();
        Json transfers = Json::array({Json::object({{"name", Json("Leak")}, {"from", first.get("name")}, {"to", Json()}, {"rate", Json("C")},
                                                    {"multiply_by_donor", Json(false)}})});
        bad.set("transfers", transfers);
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("nan")}, {"kind", Json("run")}, {"model", bad},
                                              {"out", Json((scratch / "nan.zip").string())}}), 0));
        const auto events = out_buffer.until_ended("nan");
        CHECK_MSG(name_of(events) == "SolverError", "a value that is not a number stops the run: " + name_of(events) + " " + message_of(events));
        CHECK_MSG(message_of(events).rfind("The simulation produced a value that is not a number at t=0. It starts in C [Radionuclides=Pu-241] (and 4 more of its "
                                           "indices): N/N comes to 0/0, with N = 0. It reaches the compartment ",
                                           0) == 0,
                  "and says where it starts: " + message_of(events));
        CHECK(!events.empty() && events.back().get("block") == "C");
        CHECK(!events.empty() && events.back().get("hint").is_null());
    }

    // A run kept: its archive has no states, and its series are asked for afterwards --
    // the numbers a run made here has, to the bit.
    const std::string kept = (scratch / "kept.zip").string();
    {
        Json job = Json::object({{"op", Json("job")}, {"id", Json("b")}, {"kind", Json("run")}, {"model", parse_json(model_text)}, {"out", Json(kept)},
                                 {"options", Json::object({{"keep", Json(true)}})}});
        in_buffer.put(json_text(job, 0));
        const auto events = out_buffer.until_ended("b");
        CHECK_MSG(name_of(events) == "done", "a kept run ends done: " + name_of(events) + " " + message_of(events));
        CHECK(fs::exists(kept) && fs::exists(whole) && fs::file_size(kept) < fs::file_size(whole));

        auto project = std::make_shared<const Project>(parse_json(model_text));
        Results here = run_project(project, nullptr, RunOptions{});
        std::vector<Json> outs;
        Json labels = Json::array();
        for (const Json& o : here.outputs()) {
            if (outs.size() == 3) break;
            outs.push_back(o);
            labels.push(o.get("label"));
        }
        const auto columns = here.series_many(outs);
        const std::string series = (scratch / "series.bin").string();
        in_buffer.put(json_text(Json::object({{"op", Json("series")}, {"id", Json("q1")}, {"run", Json("b")}, {"labels", labels}, {"out", Json(series)}}), 0));
        const auto answered = out_buffer.until_ended("q1");
        CHECK_MSG(name_of(answered) == "done", "a series is handed over: " + name_of(answered) + " " + message_of(answered));
        const std::string data = fs::exists(series) ? check::read_file(series) : "";
        std::size_t expected = 0;
        for (const auto& c : columns) expected += c.size() * 8;
        CHECK_EQ(data.size(), expected);
        bool same = data.size() == expected;
        std::size_t at = 0;
        for (const auto& c : columns) {
            for (double v : c) {
                if (!same) break;
                double got;
                std::memcpy(&got, data.data() + at, 8);
                at += 8;
                same = check::same_bits(got, v);
            }
        }
        CHECK_MSG(same, "the series handed over are the run's, to the bit");

        // One it has not
        in_buffer.put(json_text(Json::object({{"op", Json("series")}, {"id", Json("q2")}, {"run", Json("b")}, {"labels", Json::array({Json("No such series")})},
                                              {"out", Json(series)}}), 0));
        const auto refused = out_buffer.until_ended("q2");
        CHECK(name_of(refused) == "ArgumentError");
        CHECK(message_of(refused) == "The engine's run has no series called 'No such series'.");

        // The whole run, when the page wants every state after all.
        const std::string later = (scratch / "later.zip").string();
        in_buffer.put(json_text(Json::object({{"op", Json("archive")}, {"id", Json("q3")}, {"run", Json("b")}, {"out", Json(later)}}), 0));
        CHECK(name_of(out_buffer.until_ended("q3")) == "done");
        CHECK(fs::exists(later) && fs::file_size(later) > fs::file_size(kept));

        // A question a run of one realisation has no answer to.
        in_buffer.put(json_text(Json::object({{"op", Json("bands")}, {"id", Json("q4")}, {"run", Json("b")}, {"out", Json(series)}}), 0));
        CHECK(message_of(out_buffer.until_ended("q4")) == "That run is not a probabilistic run: it has no realisations to ask about.");

        // Let go of, it is no longer there to ask.
        in_buffer.put(json_text(Json::object({{"op", Json("forget")}, {"id", Json("q5")}, {"run", Json("b")}}), 0));
        CHECK(name_of(out_buffer.until_ended("q5")) == "done");
        in_buffer.put(json_text(Json::object({{"op", Json("series")}, {"id", Json("q6")}, {"run", Json("b")}, {"labels", labels}, {"out", Json(series)}}), 0));
        const auto gone = out_buffer.until_ended("q6");
        CHECK(name_of(gone) == "ArgumentError");
        CHECK(message_of(gone).rfind("This engine no longer holds that run", 0) == 0);
    }

    // A solver the other engines have and this one does not: a run, a probabilistic run, a replay and
    // a calibration -- said before anything runs, by the name the page falls back on.
    {
        Json other = parse_json(check::read_file(examples + "biosphere.json"));
        other["simulation"].set("solver", Json("auto"));
        for (const char* kind : {"run", "probabilistic", "replay"}) {
            const std::string id = std::string("auto-") + kind;
            in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json(kind)}, {"model", other},
                                                  {"options", Json::object({{"iterations", Json(4)}, {"workers", Json(2)}})},
                                                  {"out", Json((scratch / "never.zip").string())}}), 0));
            const auto events = out_buffer.until_ended(id);
            CHECK_MSG(name_of(events) == "NotOnThisEngine", std::string(kind) + " with a solver this engine lacks is the page's to do: " + name_of(events) +
                                                                " " + message_of(events));
            CHECK(message_of(events).rfind("'auto' is not one of the C++ engine's solvers", 0) == 0);
        }
        Json targets = Json::array({Json::object({{"output", Json("Dose")}, {"when", Json("peak")}, {"value", Json(1e-6)}})});
        Json variables = Json::array({Json::object({{"key", Json("geoTransit")}, {"lower", Json(100)}, {"upper", Json(1000)}})});
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("auto-calibrate")}, {"kind", Json("calibrate")}, {"model", other},
                                              {"options", Json::object({{"targets", targets}, {"variables", variables}})},
                                              {"out", Json((scratch / "never.zip").string())}}), 0));
        const auto events = out_buffer.until_ended("auto-calibrate");
        CHECK_MSG(name_of(events) == "NotOnThisEngine", "a calibration with a solver this engine lacks is the page's to do: " + name_of(events) + " " +
                                                            message_of(events));
        CHECK(message_of(events).rfind("'auto' is not one of the C++ engine's solvers", 0) == 0);
        bool progressed = false;
        for (const Json& e : events) progressed = progressed || e.get("event") == "progress";
        CHECK_MSG(!progressed, "and says no step of a search first");
    }
    CHECK(!fs::exists(scratch / "never.zip"));

    // --- probabilistic runs -------------------------------------------------------------------
    const std::string bio_text = check::read_file(examples + "biosphere.json");
    auto bio = std::make_shared<const Project>(parse_json(bio_text));
    auto job_line = [&](const std::string& id, const char* kind, const Json& model, const Json& options) {
        return json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json(kind)}, {"model", model}, {"options", options},
                                       {"out", Json((scratch / (id + ".zip")).string())}}),
                         0);
    };
    auto read_doubles = [&](const std::string& path) {
        const std::string data = fs::exists(path) ? check::read_file(path) : "";
        std::vector<double> v(data.size() / 8);
        if (!v.empty()) std::memcpy(v.data(), data.data(), v.size() * 8);
        return v;
    };
    auto same_doubles = [](const std::vector<double>& a, const std::vector<double>& b) {
        if (a.size() != b.size()) return false;
        for (std::size_t i = 0; i < a.size(); i++)
            if (!check::same_bits(a[i], b[i])) return false;
        return true;
    };
    auto bytes_doubles = [](const std::string& bytes) {
        std::vector<double> v(bytes.size() / 8);
        if (!v.empty()) std::memcpy(v.data(), bytes.data(), v.size() * 8);
        return v;
    };
    auto sample_meta = [&](const std::string& id) {
        const std::string zip = fs::exists(scratch / (id + ".zip")) ? check::read_file((scratch / (id + ".zip")).string()) : "";
        const std::string text = zip_entry(zip, "results/sample/meta.json");
        return text.empty() ? Json::object() : parse_json(text);
    };

    // A sample kept: its archive without the series, and every question asked of it answered
    // as a run here answers it, to the bit.
    {
        ProbabilisticOptions here;
        here.iterations = 10;
        here.seed = Json(4);
        here.threads = 1;
        ProbabilisticResults prob = run_probabilistic(bio, here);
        const long long n = prob.iterations;
        const long long kept_series = static_cast<long long>(prob.outputs.size());
        const long long count = static_cast<long long>(an_count(prob));
        in_buffer.put(job_line("p1", "probabilistic", Json(bio_text),
                               Json::object({{"iterations", Json(10)}, {"seed", Json(4)}, {"keep", Json(true)}, {"workers", Json(2)}})));
        const auto events = out_buffer.until_ended("p1");
        CHECK_MSG(name_of(events) == "done", "a kept sample ends done: " + name_of(events) + " " + message_of(events));
        bool building = false, writing = false, rising = true;
        long long last_done = 0;
        for (const Json& e : events) {
            if (e.get("event") == "stage" && e.get("stage") == "building") building = true;
            if (e.get("event") == "stage" && e.get("stage") == "writing") writing = true;
            if (e.get("event") == "progress") {
                rising = rising && e.get("done").as_int() > last_done && e.get("total").as_int() == n;
                last_done = e.get("done").as_int();
            }
        }
        CHECK(building && writing && rising && last_done >= 1);
        const std::string zip = check::read_file((scratch / "p1.zip").string());
        const Json meta = sample_meta("p1");
        CHECK(meta.get("onEngine") == Json(true));
        CHECK(zip_entry(zip, "results/sample/series.f64").empty() && zip_entry(zip, "results/sample/series.f32").empty());
        CHECK(!zip_entry(zip, "results/sample/draws.f64").empty() && !zip_entry(zip, "results/sample/ran.u8").empty());
        CHECK(meta.get("iterations").as_int() == n && meta.get("times").as_int() == static_cast<long long>(prob.t.size()) &&
              static_cast<long long>(meta.get("outputs").size()) == count);
        CHECK(meta.get("stats").get("seed") == Json(4) && meta.get("stats").get("threads") == Json(2));
        CHECK(bytes_doubles(zip_entry(zip, "results/sample/draws.f64")).size() == prob.samples.data.size());

        auto ask = [&](const std::string& id, const char* op, Json q) {
            q.set("op", Json(op));
            q.set("id", Json(id));
            q.set("run", Json("p1"));
            q.set("out", Json((scratch / id).string()));
            in_buffer.put(json_text(q, 0));
            return out_buffer.until_ended(id);
        };
        // Per series, a run per percentile, the mean, the deviation and its count, the median's
        // two intervals.
        Json mask = Json::array();
        for (int b : {1, 1, 0, 1, 0, 1, 1, 1, 0, 1}) mask.push(Json(b));
        std::vector<std::pair<std::string, Json>> asked = {
            {"bands", Json::object({{"percentiles", Json::array({Json(0.05), Json(0.5), Json(0.95)})}, {"mask", Json()}})},
            {"bands", Json::object({{"percentiles", Json::array({Json(0.25), Json(0.75)})}, {"mask", mask}})},
            {"realisations", Json::object({{"series", Json::array({Json(1), Json(kept_series)})}})},
            {"column", Json::object({{"series", Json::array({Json(0), Json(kept_series)})}, {"at", Json(7)}})},
            {"realisation", Json::object({{"series", Json::array({Json(2), Json(kept_series + 1)})}, {"index", Json(3)}})},
        };
        int k = 0;
        for (const auto& [op, q] : asked) {
            const std::string id = "q-" + std::to_string(k++);
            const auto answered = ask(id, op.c_str(), q);
            CHECK_MSG(name_of(answered) == "done", op + " is answered: " + name_of(answered) + " " + message_of(answered));
            CHECK_MSG(same_doubles(read_doubles((scratch / id).string()), bytes_doubles(sample_answer_bytes(Json(op), prob, q))),
                      op + ": the engine's answer is a run's here, to the bit");
        }
        CHECK(read_doubles((scratch / "q-1").string()).size() == static_cast<std::size_t>(2 + 1 + 7) * static_cast<std::size_t>(kept_series * static_cast<long long>(prob.t.size()) + (count - kept_series)));
        // Asked wrongly, or what a run is asked: said so.
        auto wrong = ask("q-w1", "column", Json::object({{"series", Json::array({Json(count)})}, {"at", Json(0)}}));
        CHECK(name_of(wrong) == "ArgumentError" && message_of(wrong) == "The probabilistic run has no series " + std::to_string(count) + ": it has " +
                                                                            std::to_string(count) + ", from 0.");
        wrong = ask("q-w2", "bands", Json::object({{"percentiles", Json::array({Json(0.5)})}, {"mask", Json::array({Json(1), Json(0)})}}));
        CHECK(name_of(wrong) == "ArgumentError" && message_of(wrong) == "The mask has 2 entries for 10 realisations.");
        wrong = ask("q-w3", "series", Json::object({{"labels", Json::array({Json("Dose")})}}));
        CHECK(name_of(wrong) == "ArgumentError" && message_of(wrong) == "'series' is not something this engine is asked of a probabilistic run");
        wrong = ask("q-w4", "column", Json::object({{"series", Json::array({Json(0)})}, {"at", Json(2.5)}}));
        CHECK(name_of(wrong) == "InexactError");
        // The whole sample, series and all.
        CHECK(name_of(ask("q-a", "archive", Json::object())) == "done");
        const std::string whole_sample = check::read_file((scratch / "q-a").string());
        std::vector<double> series_f64 = bytes_doubles(zip_entry(whole_sample, "results/sample/series.f64"));
        std::vector<double> mine;
        for (const auto& v : prob.values) mine.insert(mine.end(), v.begin(), v.end());
        CHECK_MSG(same_doubles(series_f64, mine), "the whole sample's series are a run's here, to the bit");
        // Let go of, and then said to be gone.
        in_buffer.put(json_text(Json::object({{"op", Json("forget")}, {"id", Json("q-f")}, {"run", Json("p1")}}), 0));
        CHECK(name_of(out_buffer.until_ended("q-f")) == "done");
        const auto gone = ask("q-g", "column", Json::object({{"series", Json::array({Json(0)})}, {"at", Json(0)}}));
        CHECK(name_of(gone) == "ArgumentError" && message_of(gone).rfind("This engine no longer holds that run", 0) == 0);

        // The page's limits for a sample the engine holds: taken for a kept sample, and not for
        // one that goes back whole, which a tab must hold.
        const long long size = n * kept_series * static_cast<long long>(prob.t.size()) * 8;
        auto limited = [&](const std::string& id, bool keep, long long most) {
            in_buffer.put(job_line(id, "probabilistic", Json(bio_text),
                                   Json::object({{"iterations", Json(10)}, {"seed", Json(4)}, {"keep", Json(keep)}, {"workers", Json(1)},
                                                 {"most", Json(most)}, {"asked", Json(size)}})));
            return out_buffer.until_ended(id);
        };
        CHECK(name_of(limited("k1", true, size - 1)) == "done" && sample_meta("k1").get("precision") == "float32");
        const auto too_large = limited("k2", true, size / 4);
        CHECK(name_of(too_large) == "ErrorException" && message_of(too_large).find("large=true") != std::string::npos &&
              message_of(too_large).find("even held as float32") != std::string::npos);
        CHECK(name_of(limited("w1", false, size - 1)) == "done" && sample_meta("w1").get("precision") == "double");
    }

    // A tornado and a sensitivity design: their runs go back whole, the inputs counted from 0, the
    // points the design's.
    {
        Json tornado = Json::object({{"low", Json(0.05)}, {"high", Json(0.95)}});
        in_buffer.put(job_line("t1", "probabilistic", Json(bio_text), Json::object({{"seed", Json(3)}, {"tornado", tornado}, {"keep", Json(true)}})));
        CHECK(name_of(out_buffer.until_ended("t1")) == "done");
        const Json meta = sample_meta("t1");
        CHECK(meta.get("iterations").as_int() == 31 && !meta.has("onEngine"));
        Json swung = Json::array();
        for (int k = 0; k < 15; k++) swung.push(Json(k));
        CHECK(meta.get("stats").get("tornado").get("swung") == swung);
        CHECK(!zip_entry(check::read_file((scratch / "t1.zip").string()), "results/sample/series.f64").empty());
        // Kept as a sample where `design_for` runs one, a tornado or a design asked for as the
        // application asks: a tornado of 0 is none, and of {} one (before a design of {}).
        in_buffer.put(job_line("t0", "probabilistic", Json(bio_text),
                               Json::object({{"seed", Json(3)}, {"iterations", Json(5)}, {"tornado", Json(0)}, {"keep", Json(true)},
                                             {"blocks", Json::array({Json("Dose")})}})));
        CHECK(name_of(out_buffer.until_ended("t0")) == "done");
        const Json t0 = sample_meta("t0");
        CHECK_MSG(t0.get("iterations").as_int() == 5 && !t0.get("stats").has("tornado") && t0.get("onEngine") == Json(true) &&
                      zip_entry(check::read_file((scratch / "t0.zip").string()), "results/sample/series.f64").empty(),
                  "a sample asked to be kept, its tornado 0, stays on the engine: " + json_text(t0.get("stats"), 0).substr(0, 200));
        in_buffer.put(job_line("s0", "probabilistic", Json(bio_text),
                               Json::object({{"seed", Json(3)}, {"iterations", Json(5)}, {"tornado", Json::object()}, {"gsa", Json::object()},
                                             {"keep", Json(true)}, {"blocks", Json::array({Json("Dose")})}})));
        CHECK(name_of(out_buffer.until_ended("s0")) == "done");
        const Json s0 = sample_meta("s0");
        CHECK_MSG(s0.get("iterations").as_int() == 31 && s0.get("stats").has("tornado") && !s0.has("onEngine") &&
                      !zip_entry(check::read_file((scratch / "s0.zip").string()), "results/sample/series.f64").empty(),
                  "a tornado of {} goes back whole, its design {} after it");

        Json gsa = Json::object({{"method", Json("morris")}, {"options", Json::object({{"trajectories", Json(2)}, {"points", Json(3)}})}});
        in_buffer.put(job_line("g1", "probabilistic", Json(bio_text),
                               Json::object({{"seed", Json(4)}, {"blocks", Json::array({Json("Dose")})}, {"gsa", gsa}})));
        CHECK(name_of(out_buffer.until_ended("g1")) == "done");
        const Json gmeta = sample_meta("g1");
        CHECK(gmeta.get("stats").get("gsa").get("method") == "morris");
        bool from_zero = gmeta.get("stats").get("gsa").get("factors").size() == 15;
        for (std::size_t k = 0; from_zero && k < 15; k++)
            from_zero = gmeta.get("stats").get("gsa").get("factors")[k].get("members") == Json::array({Json(static_cast<long long>(k))});
        CHECK_MSG(from_zero, "each factor's inputs counted from 0");
        auto sys = std::make_shared<System>(bio);
        DesignOptions d;
        d.seed = Json(4);
        d.gsa = gsa;
        SampleDesign design = design_for(*bio, *sys, d);
        CHECK(gmeta.get("iterations").as_int() == design.iterations);
        std::vector<double> draws;
        for (std::size_t k = 0; k < design.plan.size(); k++)
            for (long long i = 0; i < design.iterations; i++) draws.push_back(design.values(k, i));
        CHECK_MSG(same_doubles(bytes_doubles(zip_entry(check::read_file((scratch / "g1.zip").string()), "results/sample/draws.f64")), draws),
                  "the design's points, as the design draws them");
    }

    // A realisation replayed, kept, its series asked for: realisation 6 as a run here makes it.
    {
        in_buffer.put(job_line("r1", "replay", Json(bio_text),
                               Json::object({{"index", Json(5)}, {"seed", Json(11)}, {"iterations", Json(20)}, {"keep", Json(true)}})));
        const auto events = out_buffer.until_ended("r1");
        CHECK_MSG(name_of(events) == "done", "a replay ends done: " + name_of(events) + " " + message_of(events));
        const std::string zip = check::read_file((scratch / "r1.zip").string());
        const Json meta = parse_json(zip_entry(zip, "results/meta.json"));
        const Json& replayed = meta.get("replayed");
        CHECK(replayed.get("index") == Json(5) && replayed.get("iterations") == Json(20) && replayed.get("values").size() == 15);
        CHECK(meta.get("onEngine") == Json(true) && meta.has("page") && meta.has("massBalance"));
        DesignOptions d;
        d.seed = Json(11);
        d.iterations = 20;
        Replay here = run_realisation(bio, 6, d);
        bool same_values = replayed.get("values").size() == here.values.size();
        for (std::size_t k = 0; same_values && k < here.values.size(); k++) {
            const Json& v = replayed.get("values")[k];
            same_values = v.get("name") == here.values[k].name && v.get("held") == Json(here.values[k].held) &&
                          check::same_bits(v.get("value").as_double(), here.values[k].value);
        }
        CHECK_MSG(same_values, "the replayed inputs are those a replay here sets");
        const std::string series = (scratch / "r1-series").string();
        const std::string label = here.results.outputs().back().get("label").as_string();
        in_buffer.put(json_text(Json::object({{"op", Json("series")}, {"id", Json("r1-q")}, {"run", Json("r1")}, {"labels", Json::array({Json(label)})},
                                              {"out", Json(series)}}), 0));
        CHECK(name_of(out_buffer.until_ended("r1-q")) == "done");
        CHECK_MSG(same_doubles(read_doubles(series), here.results.series(label)), "the replay's series are a replay's here, to the bit: " + label);
    }

    // Refusals, named as the Julia engine names them.
    {
        in_buffer.put(job_line("e1", "probabilistic", Json(model_text), Json::object({{"iterations", Json(3)}})));
        auto e = out_buffer.until_ended("e1");
        CHECK(name_of(e) == "ArgumentError" && message_of(e).rfind("No parameter in this model has a distribution, so every realisation", 0) == 0);
        in_buffer.put(job_line("e2", "probabilistic", Json(bio_text), Json::object({{"iterations", Json(2.5)}})));
        e = out_buffer.until_ended("e2");
        CHECK(name_of(e) == "InexactError" && message_of(e) == "Int64(2.5)");
        in_buffer.put(job_line("e3", "replay", Json(bio_text), Json::object({{"seed", Json("abc")}})));
        CHECK(name_of(out_buffer.until_ended("e3")) == "MethodError");
        Json bad = parse_json(bio_text);
        bad.set("parameters", Json::array({Json::object({{"name", Json("k")}, {"value", Json(1)},
                                                         {"pdf", Json::object({{"kind", Json("pg")}, {"values", Json::array({Json(0), Json(1)})}})}})}));
        bad.set("compartments", Json::array({Json::object({{"name", Json("A")}, {"initial", Json("1 / k")}})}));
        for (const char* key : {"transfers", "expressions", "inflows", "index_reductions", "lookups"}) bad.set(key, Json::array());
        bad.set("nuclides", Json::array());
        in_buffer.put(job_line("e4", "probabilistic", bad, Json::object({{"iterations", Json(4)}})));
        e = out_buffer.until_ended("e4");
        CHECK_MSG(name_of(e) == "SolverError" && message_of(e).rfind("A starts at Infinity", 0) == 0,
                  "a first realisation that fails fails the run: " + name_of(e) + " " + message_of(e));
        in_buffer.put(job_line("e5", "draw", Json(bio_text), Json::object()));
        e = out_buffer.until_ended("e5");
        CHECK(name_of(e) == "ArgumentError" && message_of(e) == "'draw' is not a kind of job this engine runs");
    }

    // Stopped while it runs: it says it was cancelled, and goes on answering.
    {
        // One series kept, so that many realisations fit.
        Results one = run_project(bio, nullptr, RunOptions{});
        const Json label = one.outputs().front().get("label");
        in_buffer.put(job_line("c1", "probabilistic", Json(bio_text),
                               Json::object({{"iterations", Json(20000)}, {"workers", Json(2)}, {"blocks", Json::array({label})}})));
        // Wait for the first realisation to be said, then stop it.
        for (int tries = 0; tries < 2000; tries++) {
            if (out_buffer.has_event("c1", "progress")) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        in_buffer.put(json_text(Json::object({{"op", Json("cancel")}, {"id", Json("c1")}}), 0));
        const auto events = out_buffer.until_ended("c1");
        CHECK_MSG(name_of(events) == "cancelled", "a run stopped while it runs says so: " + name_of(events) + " " + message_of(events));
        CHECK(!fs::exists(scratch / "c1.zip"));
    }

    // Local sensitivities, answered as the Julia engine's service answers them: what is said as
    // the job goes, the refusals named as Julia names them, and the answer written -- the times,
    // the parameters, the counts and every state the page shows with its derivatives -- to the bit,
    // its time taken aside. With parity on, as the fixtures were written.
    {
        const Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/localsens.json"));
        set_parity(true);
        for (const Json& s : fx.get("service").arr()) {
            const std::string id = s.get("id").as_string();
            const std::string out = (scratch / (id + ".json")).string();
            in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json("local-sensitivity")}, {"model", s.get("model")},
                                                  {"options", s.get("options")}, {"out", Json(out)}}), 0));
            const auto events = out_buffer.until_ended(id);
            Json said = Json::array();
            for (const Json& e : events) {
                if (e.get("event") == "progress") continue;
                said.push(e.get("event") == "stage" ? Json("stage:" + e.get("stage").as_string()) : e.get("event"));
            }
            CHECK_MSG(said == s.get("events"), id + ": the engine says " + json_text(said, 0) + ", Julia's " + json_text(s.get("events"), 0));
            const Json last = events.empty() ? Json::object() : events.back();
            for (const char* key : {"name", "message", "hint"})
                CHECK_MSG(last.get(key) == s.get(key), id + ": its " + key + " is " + json_text(last.get(key), 0) + ", Julia's " + json_text(s.get(key), 0));
            const std::string text = fs::exists(out) ? without_ms(check::read_file(out)) : "";
            CHECK_MSG((text.empty() ? std::string() : kept_text(text)) == s.get("out").as_string(), id + ": the answer written is not Julia's");
        }
        set_parity(false);

        // Stopped while it integrates: it says it was cancelled, writes nothing, and goes on
        // answering. 300 cells by twelve parameters: seconds of work, stopped once it is under way.
        Json indices = Json::array(), parameters = Json::array(), names = Json::array();
        std::string rate;
        for (int i = 0; i < 300; i++) indices.push(Json("c" + std::to_string(i)));
        for (int k = 1; k <= 12; k++) {
            parameters.push(Json::object({{"name", Json("k" + std::to_string(k))}, {"value", Json(0.01 * k)}}));
            names.push(Json("k" + std::to_string(k)));
            rate += (k > 1 ? " + " : "") + std::string("k") + std::to_string(k) + " * 0.01";
        }
        const Json cell = Json::array({Json("Cell")});
        const Json cells = Json::object(
            {{"name", Json("cells")},
             {"simulation", parse_json(R"({"start_time": 0, "end_time": 1000, "output_points": 400, "spacing": "linear", "solver": "ndf", "rtol": 1e-10, "abstol": 1e-14})")},
             {"index_lists", Json::array({Json::object({{"name", Json("Cell")}, {"indices", indices}})})},
             {"parameters", parameters},
             {"compartments", Json::array({Json::object({{"name", Json("A")}, {"initial", Json("1")}, {"index_lists", cell}}),
                                           Json::object({{"name", Json("B")}, {"initial", Json("0")}, {"index_lists", cell}})})},
             {"transfers", Json::array({Json::object({{"name", Json("AB")}, {"from", Json("A")}, {"to", Json("B")}, {"rate", Json("(" + rate + ") * (1 + 0.5 * sin(time / 7))")},
                                                      {"index_lists", cell}}),
                                        Json::object({{"name", Json("Bout")}, {"from", Json("B")}, {"to", Json()}, {"rate", Json("k12 * B")}, {"index_lists", cell}})})}});
        const std::string stopped = (scratch / "ls-stopped.json").string();
        const auto started = std::chrono::steady_clock::now();
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("ls-stop")}, {"kind", Json("local-sensitivity")}, {"model", cells},
                                              {"options", Json::object({{"parameters", names}})}, {"out", Json(stopped)}}), 0));
        for (int tries = 0; tries < 2000; tries++) {
            if (out_buffer.has_event("ls-stop", "progress")) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        CHECK_MSG(out_buffer.has_event("ls-stop", "progress"), "the integration says how far it has come");
        in_buffer.put(json_text(Json::object({{"op", Json("cancel")}, {"id", Json("ls-stop")}}), 0));
        const auto events = out_buffer.until_ended("ls-stop");
        const double took = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        CHECK_MSG(name_of(events) == "cancelled", "dy/dp stopped while it integrates says so: " + name_of(events) + " " + message_of(events));
        CHECK_MSG(!fs::exists(stopped), "and writes nothing");
        std::printf("dy/dp stopped after %.2f s\n", took);
    }

    // Calibrations, answered as the Julia engine's service answers them: what is said as the job
    // goes -- each step's best as a progress detail, every one said that of the step its count
    // names, the first always --, the refusals named as Julia names them, and the answer written,
    // to the bit, its time taken aside. With parity on, as the fixtures were written.
    {
        const Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/calibrate.json"));
        set_parity(true);
        for (const Json& s : fx.get("service").arr()) {
            const std::string id = s.get("id").as_string();
            const std::string out = (scratch / (id + ".json")).string();
            in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json("calibrate")}, {"model", s.get("model")},
                                                  {"options", s.get("options")}, {"out", Json(out)}}), 0));
            const auto events = out_buffer.until_ended(id);
            Json said = Json::array();
            const Json& steps = s.get("steps");
            int details = 0;
            bool first = false;
            for (const Json& e : events) {
                if (e.get("event") == "progress") {
                    const Json& d = e.get("detail");
                    const long long k = d.get("evals").is_int() ? d.get("evals").as_int() : 0;
                    const bool same = k >= 1 && static_cast<std::size_t>(k) <= steps.size() &&
                                      kept_text(json_text(d, 0)) == steps[static_cast<std::size_t>(k - 1)].as_string();
                    CHECK_MSG(same, id + ": the detail said for step " + std::to_string(k) + " is not Julia's: " + json_text(d, 0));
                    first = first || k == 1;
                    details++;
                    continue;
                }
                said.push(e.get("event") == "stage" ? Json("stage:" + e.get("stage").as_string()) : e.get("event"));
            }
            CHECK_MSG(said == s.get("events"), id + ": the engine says " + json_text(said, 0) + ", Julia's " + json_text(s.get("events"), 0));
            CHECK_MSG(steps.empty() || (first && details >= 1), id + ": the first step is said");
            const Json last = events.empty() ? Json::object() : events.back();
            for (const char* key : {"name", "message", "hint"})
                CHECK_MSG(last.get(key) == s.get(key), id + ": its " + key + " is " + json_text(last.get(key), 0) + ", Julia's " + json_text(s.get(key), 0));
            const std::string text = fs::exists(out) ? without_ms(check::read_file(out)) : "";
            CHECK_MSG((text.empty() ? std::string() : kept_text(text)) == s.get("out").as_string(), id + ": the answer written is not Julia's");
        }
        set_parity(false);

        // Stopped while it searches: it says it was cancelled, writes nothing, and goes on
        // answering. The biosphere example, with a budget that would take a minute.
        const std::string stopped = (scratch / "cal-stopped.json").string();
        Json targets = Json::array({Json::object({{"output", Json("Well [I-129]")}, {"when", Json("peak")}, {"value", Json(2e7)}, {"scale", Json("log")}})});
        Json variables = Json::array({Json::object({{"key", Json("leachRate[I-129]")}, {"lower", Json(1e-6)}, {"upper", Json(1e-3)}, {"space", Json("log")}}),
                                      Json::object({{"key", Json("geoTransit")}, {"lower", Json(1e-5)}, {"upper", Json(1e-2)}, {"space", Json("log")}})});
        const auto started = std::chrono::steady_clock::now();
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("cal-stop")}, {"kind", Json("calibrate")}, {"model", Json(bio_text)},
                                              {"options", Json::object({{"targets", targets}, {"variables", variables}, {"method", Json("de")},
                                                                        {"maxEvals", Json(100000)}})},
                                              {"out", Json(stopped)}}), 0));
        for (int tries = 0; tries < 2000; tries++) {
            if (out_buffer.has_event("cal-stop", "progress")) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        CHECK_MSG(out_buffer.has_event("cal-stop", "progress"), "the search says how far it has come");
        in_buffer.put(json_text(Json::object({{"op", Json("cancel")}, {"id", Json("cal-stop")}}), 0));
        const auto events = out_buffer.until_ended("cal-stop");
        const double took = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
        CHECK_MSG(name_of(events) == "cancelled", "a calibration stopped while it searches says so: " + name_of(events) + " " + message_of(events));
        CHECK_MSG(!fs::exists(stopped), "and writes nothing");
        std::printf("calibration stopped after %.2f s\n", took);
    }

    // A model that cannot be read, or built, or solved, says which and about what.
    {
        Json bad = parse_json(model_text);
        bad.set("compartments", Json::array({Json::object({{"name", Json("A")}}), Json::object({{"name", Json("A")}})}));
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("v")}, {"kind", Json("run")}, {"model", bad}, {"out", Json((scratch / "v.zip").string())}}), 0));
        const auto events = out_buffer.until_ended("v");
        CHECK_MSG(name_of(events) == "ValidationError", "a model that cannot be read: " + name_of(events) + " " + message_of(events));

        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("j")}, {"kind", Json("run")}, {"model", Json("{not json")},
                                              {"out", Json((scratch / "j.zip").string())}}), 0));
        CHECK(name_of(out_buffer.until_ended("j")) == "JSONError");

        // As the Julia engine's job reads it: a model that is no JSON object refused before anything
        // is said, one it cannot read after the job's stage -- whatever the kind of job.
        const std::pair<const char*, const char*> stages[] = {
            {"run", "solving"}, {"calibrate", "solving"}, {"local-sensitivity", "solving"}, {"replay", "solving"}, {"probabilistic", "building"}};
        for (const auto& [kind, first] : stages) {
            const std::string id = std::string("v-") + kind;
            in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json(kind)}, {"model", bad},
                                                  {"options", Json::object({{"targets", Json::array({Json::object({{"output", Json("A")}, {"value", Json(1)}})})},
                                                                            {"variables", Json::array({Json::object({{"key", Json("k")}})})}})},
                                                  {"out", Json((scratch / "v.zip").string())}}), 0));
            const auto events = out_buffer.until_ended(id);
            CHECK_MSG(events.size() == 2 && events[0].get("event") == "stage" && events[0].get("stage") == first && name_of(events) == "ValidationError" &&
                          message_of(events) == "A: Duplicate block name 'A'",
                      std::string(kind) + ": a model that cannot be read is refused after the stage " + first + ": " + name_of(events) + " " +
                          message_of(events));
            in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id + "-list")}, {"kind", Json(kind)}, {"model", Json("[1, 2]")},
                                                  {"out", Json((scratch / "v.zip").string())}}), 0));
            const auto listed = out_buffer.until_ended(id + "-list");
            CHECK_MSG(listed.size() == 1 && name_of(listed) == "ArgumentError" && message_of(listed) == "A model is one JSON object",
                      std::string(kind) + ": a model that is no JSON object: " + name_of(listed) + " " + message_of(listed));
        }
        // A job with no model reads the empty text; one whose model is null, no object.
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("no-model")}, {"kind", Json("calibrate")}, {"out", Json((scratch / "v.zip").string())}}), 0));
        const auto none = out_buffer.until_ended("no-model");
        CHECK_MSG(none.size() == 1 && name_of(none) == "JSONError" && message_of(none) == "Unexpected end of JSON", "no model: " + name_of(none) + " " + message_of(none));
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json("null-model")}, {"kind", Json("run")}, {"model", Json()},
                                              {"out", Json((scratch / "v.zip").string())}}), 0));
        const auto null_model = out_buffer.until_ended("null-model");
        CHECK_MSG(name_of(null_model) == "ArgumentError" && message_of(null_model) == "A model is one JSON object", "a null model: " + name_of(null_model));
    }

    // A line that is no message is passed over, and the engine goes on answering.
    in_buffer.put("not a message");
    in_buffer.put("[1, 2]");
    in_buffer.put(json_text(Json::object({{"op", Json("forget")}, {"id", Json("still")}, {"run", Json("nothing")}}), 0));
    CHECK(name_of(out_buffer.until_ended("still")) == "done");

    in_buffer.close();
    engine.join();
    CHECK_MSG(out_buffer.every_line_json(), "standard output carries nothing but messages");

    std::error_code ignored;
    fs::remove_all(scratch, ignored);
    return check::summary("test_service");
}
