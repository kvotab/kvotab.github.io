// The run log against the Julia engine's, with parity on (tools/runlog_fixtures.jl
// writes tests/fixtures/runlog.json): the number formats it writes with, on
// numbers chosen to reach each rounding; then the log of each run as text -- the
// date, the build and the timings fixed, the counts a run of this engine does not
// make set over its own -- or the message the run fails with.

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <map>

#include "check.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
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

std::string formats(double x) {
    std::string out;
    auto put = [&](const std::string& s) { out += (out.empty() ? "" : "|") + s; };
    for (int d : {0, 1, 2, 3, 5, 10, 20}) put(js_to_fixed(x, d));
    for (int f : {0, 1, 2, 3, 6, 15, 20}) put(js_to_exponential(x, f));
    for (int p : {1, 2, 4, 7, 15, 21}) put(js_to_precision(x, p));
    return out;
}

// A model with changes set over it: the simulation's key by key, the rest whole; null takes
// a key away.
Json changed(const Json& model, const Json& set) {
    Json m = model.copy();
    if (!set.is_object()) return m;
    for (const auto& [k, v] : set.obj()) {
        if (k == "simulation" && v.is_object()) {
            if (!m.get("simulation").is_object()) m.set("simulation", Json::object());
            Json& sim = m["simulation"];
            for (const auto& [sk, sv] : v.obj()) {
                if (sv.is_null()) sim.erase(sk);
                else sim.set(sk, sv.copy());
            }
        } else if (v.is_null()) {
            m.erase(k);
        } else {
            m.set(k, v.copy());
        }
    }
    return m;
}

// `2026-11-18T09:30:05.123Z` as a time.
std::chrono::system_clock::time_point parse_iso(const std::string& s) {
    std::tm tm{};
    int ms = 0;
    std::sscanf(s.c_str(), "%d-%d-%dT%d:%d:%d.%dZ", &tm.tm_year, &tm.tm_mon, &tm.tm_mday, &tm.tm_hour, &tm.tm_min, &tm.tm_sec, &ms);
    tm.tm_year -= 1900;
    tm.tm_mon -= 1;
#if defined(_WIN32)
    std::time_t secs = _mkgmtime(&tm);
#else
    std::time_t secs = timegm(&tm);
#endif
    return std::chrono::system_clock::from_time_t(secs) + std::chrono::milliseconds(ms);
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/runlog.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");

    // The number formats.
    {
        std::string all;
        for (const Json& row : fx.get("numbers").arr()) {
            double x = row[0].is_string() ? js_number_of(row[0]) : row[0].as_double();
            std::string text = formats(x);
            all += (all.empty() ? "" : "\n") + text;
            CHECK_MSG(fnv(text) == row[1].as_string(), "the formats of " + check::bits(x) + ": " + text);
        }
        if (dumps && *dumps) std::ofstream(std::string(dumps) + "/numbers.runlog.cpp.txt") << all;
    }

    const std::string at_text = fx.get("at").as_string();
    const auto at = parse_iso(at_text);
    CHECK_MSG(iso_utc(at) == at_text, "the date: " + iso_utc(at) + ", there " + at_text);

    std::vector<std::string> skipped;
    std::map<std::string, Json> examples, built;
    const Json builder = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/builder.json"));
    for (const Json& c : builder.get("cases").arr())
        if (c.has("model")) built[c.get("name").as_string()] = c.get("model");
    set_parity(true);
    for (const Json& c : fx.get("cases").arr()) {
        const std::string& name = c.get("name").as_string();
        Json model;
        if (c.has("example")) {
            const std::string& ex = c.get("example").as_string();
            if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
            model = examples[ex];
        } else if (c.has("built")) {
            model = built[c.get("built").as_string()];
        } else {
            model = c.get("model");
        }
        try {
            auto project = std::make_shared<const Project>(changed(model, c.get("set")));
            auto system = std::make_shared<System>(project);
            RunOptions options;
            if (c.get("solver").is_string()) options.solver = c.get("solver").as_string();
            Results res = run_project(project, system, options);
            res.timing.set("build_ms", fx.get("build_ms"));
            res.timing.set("solve_ms", fx.get("solve_ms"));
            if (c.get("inject").is_object())
                for (const auto& [k, v] : c.get("inject").obj()) res.stats.set(k, v);
            RunLogOptions log;
            if (c.has("project")) log.project = &c.get("project");
            log.build = fx.get("build").as_string();
            log.at = at;
            std::string text = run_log(res, log);
            if (dumps && *dumps) std::ofstream(std::string(dumps) + "/" + name + ".runlog.cpp.txt") << text;
            if (!c.has("log")) {
                CHECK_MSG(false, name + ": fails there: " + c.get("error").as_string());
                continue;
            }
            CHECK_MSG(fnv(text) == c.get("log").as_string(), name + ": the log differs");
        } catch (const NotSupported&) {
            skipped.push_back(name);
        } catch (const SolverError& e) {
            if (c.has("error")) CHECK_MSG(c.get("error").as_string() == e.message, name + " fails with: " + e.message + "\n   there: " + c.get("error").as_string());
            else CHECK_MSG(false, name + " runs there, fails here: " + e.message);
        } catch (const std::exception& e) {
            if (c.has("error")) CHECK_MSG(c.get("error").as_string() == e.what(), name + " fails with: " + e.what() + "\n   there: " + c.get("error").as_string());
            else CHECK_MSG(false, name + " runs there, fails here: " + e.what());
        }
    }
    set_parity(false);
    if (!skipped.empty()) {
        std::string s;
        for (const auto& x : skipped) s += (s.empty() ? "" : ", ") + x;
        std::printf("not built here yet (%zu): %s\n", skipped.size(), s.c_str());
    }
    return check::summary("test_runlog");
}
