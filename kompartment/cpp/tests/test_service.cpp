// The engine as the application's local server talks to it (src/service.cpp): the
// messages of a run, of a run it is asked to keep and of the questions asked about
// that run afterwards, and what it says to what it does not do; the run's log in the
// archive it writes; and a run that meets a value that is not a number, said where it
// starts.
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
#include "engine/project.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "model/names.hpp"
#include "service.hpp"
#include "util/json.hpp"

using namespace kompartment;

namespace {

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

    // What it does not do, it says before anything runs, by the name the page falls back on.
    for (const char* kind : {"probabilistic", "replay", "calibrate", "local-sensitivity"}) {
        const std::string id = std::string("n-") + kind;
        in_buffer.put(json_text(Json::object({{"op", Json("job")}, {"id", Json(id)}, {"kind", Json(kind)}, {"model", Json(model_text)},
                                              {"out", Json((scratch / "never.zip").string())}}), 0));
        const auto events = out_buffer.until_ended(id);
        CHECK_MSG(name_of(events) == "NotOnThisEngine", std::string(kind) + " is the page's to do: " + name_of(events));
        CHECK(message_of(events).rfind("The C++ engine runs a model; ", 0) == 0);
    }
    CHECK(!fs::exists(scratch / "never.zip"));

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
