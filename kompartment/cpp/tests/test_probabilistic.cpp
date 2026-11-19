// Probabilistic runs against the Julia package's (tools/probabilistic_fixtures.jl writes
// tests/fixtures/probabilistic.json): for every bundled example and models made up to
// reach each branch, under seeds, Latin hypercube or not, varied lists, keep lists, ranges
// of realisations, tornadoes, every sensitivity method, float32 holding and the size
// refusal -- the times, the kept series' descriptors and every value of every realisation
// to the bit in the precision held, the samples, which ran, the inputs, the statistics, the
// run log, the sample archive's entries, the bands under several percentiles and masks, the
// service's answers and refusals, a series' quantiles, mean and median intervals; the
// realisations replayed as runs; one realisation's series taken out by hand-made
// descriptors; `percentiles_for` on odd lists. Or the refusal, in the same words.
//
// Every run is made on one thread and compared; then again on two and on eight, which must
// give the same text to the last bit. Besides: progress is said once a realisation, in
// order, and what it throws stops the run and comes out once the threads have stopped.
//
// KOMPARTMENT_PROB_ONLY=text runs only the cases whose name holds it (for a sanitizer build).

#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "check.hpp"
#include "engine/analysis.hpp"
#include "engine/builder.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "io/sample.hpp"
#include "service.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

constexpr double NaN = std::numeric_limits<double>::quiet_NaN();

std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}
std::string bits32(float x) {
    if (std::isnan(x)) return "nan";
    std::uint32_t u;
    std::memcpy(&u, &x, 4);
    char buf[12];
    std::snprintf(buf, sizeof buf, "%08x", static_cast<unsigned>(u));
    return buf;
}
std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}
std::string kept(const std::string& text) { return text.size() <= 300 ? "=" + text : "#" + fnv(text); }
std::string nums(const std::vector<double>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + bits(v[i]);
    return s;
}
std::string nums32(const std::vector<float>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + bits32(v[i]);
    return s;
}
std::string joined(const std::vector<std::string>& parts, const std::string& by) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? by : "") + parts[i];
    return s;
}

std::string said(const std::function<std::string()>& f) {
    try {
        return f();
    } catch (const ArgumentError& e) {
        return std::string("error:ArgumentError:") + e.what();
    } catch (const JuliaError& e) {
        if (e.kind == "ErrorException") return std::string("error:ErrorException:") + e.what();
        return "error:" + e.kind;
    } catch (const SolverError& e) {
        return "error:SolverError:" + e.message;
    } catch (const BuildError& e) {
        return std::string("error:BuildError:") + e.what();
    } catch (const std::invalid_argument& e) {
        return std::string("error:ArgumentError:") + e.what();
    }
}

std::string tdump(const Json& v) {
    switch (v.type()) {
        case Json::Type::Null: return "null";
        case Json::Type::Bool: return v.as_bool() ? "true" : "false";
        case Json::Type::Int: return "i" + std::to_string(v.as_int());
        case Json::Type::Float: return "f" + bits(v.as_double());
        case Json::Type::String: return "s(" + v.as_string() + ")";
        case Json::Type::Array: {
            std::string s = "[";
            for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + tdump(v[i]);
            return s + "]";
        }
        case Json::Type::Object: {
            std::string s = "{";
            bool first = true;
            for (const auto& [k, x] : v.obj()) {
                s += (first ? "" : ";") + k + "=" + tdump(x);
                first = false;
            }
            return s + "}";
        }
    }
    return "";
}

std::vector<std::string> strings(const Json& list) {
    std::vector<std::string> out;
    for (const Json& v : list.arr()) out.push_back(v.as_string());
    return out;
}

ProbabilisticOptions options_of(const Json& o, int threads) {
    ProbabilisticOptions p;
    if (o.has("iterations")) p.iterations = o.get("iterations").as_double();
    p.seed = o.has("seed") ? o.get("seed") : Json(1);
    if (o.has("latin")) p.latin = o.get("latin").as_bool();
    if (o.has("varied")) p.varied = strings(o.get("varied"));
    if (o.has("keep")) p.keep = strings(o.get("keep"));
    p.threads = threads;
    if (o.has("range")) p.range = std::make_pair(o.get("range")[0].as_double(), o.get("range")[1].as_double());
    if (o.has("tornado")) p.tornado = o.get("tornado");
    if (o.has("gsa")) p.gsa = o.get("gsa");
    if (o.has("most_bytes")) p.most_bytes = o.get("most_bytes").as_int();
    if (o.has("asked_bytes")) p.asked_bytes = o.get("asked_bytes").as_int();
    if (o.has("large")) p.large = o.get("large").as_bool();
    return p;
}

Json array_of(std::size_t n, const std::function<Json(std::size_t)>& f) {
    Json a = Json::array();
    for (std::size_t i = 0; i < n; i++) a.push(f(i));
    return a;
}

/// The masks a case's bands are read under, made from the number of realisations.
std::vector<std::pair<std::string, Json>> masks(long long n) {
    const std::size_t m = static_cast<std::size_t>(std::max(0LL, n));
    std::vector<Json> mixed = {Json(1), Json(0), Json(0.5), Json(), Json("x"), Json(NaN), Json(true), Json(false), Json(-0.0), Json(2)};
    return {{"none", Json()},
            {"bools", array_of(m, [](std::size_t i) { return Json(i % 3 != 1); })},
            {"ints", array_of(m, [](std::size_t i) { return Json((i * 7) % 4 == 0 ? 0 : 1); })},
            {"mixed", array_of(m, [&](std::size_t i) { return mixed[i % mixed.size()]; })},
            {"short", array_of(m > 0 ? m - 1 : 0, [](std::size_t) { return Json(1); })},
            {"off", array_of(m, [](std::size_t) { return Json(0); })}};
}

std::vector<std::pair<std::string, Json>> percentile_lists() {
    return {{"default", Json()},
            {"tenths", Json::array({Json(0.1), Json(0.9)})},
            {"again", Json::array({Json(0.9), Json(0.5), Json(0.05), Json(0.5)})},
            {"odd", Json::array({Json(0), Json(1), Json(-1), Json("0.25"), Json(true), Json(), Json("x"), Json(NaN), Json(0.75)})},
            {"text", Json("0.3")}};
}

std::string bands_text(const std::vector<Band>& bs) {
    std::vector<std::string> lines;
    for (const Band& b : bs) {
        std::vector<std::string> q, n;
        for (const auto& y : b.q) q.push_back(nums(y));
        for (long long c : b.sd.n) n.push_back(std::to_string(c));
        lines.push_back("q=" + joined(q, ";") + " at=" + nums(b.quantiles) + " mean=" + nums(b.mean) + " sd=" + nums(b.sd.sd) + " n=" + joined(n, ",") +
                        " med=" + joined({nums(b.med.err_lo), nums(b.med.err_hi), nums(b.med.body_lo), nums(b.med.body_hi)}, ";") +
                        " flat=" + (b.flat ? "true" : "false"));
    }
    return joined(lines, "\n");
}

/// The questions the service is asked of a kept sample, made from its shape.
std::vector<std::pair<std::string, Json>> questions(long long n, long long count) {
    const std::size_t c = static_cast<std::size_t>(count);
    Json all = array_of(c, [](std::size_t k) { return Json(static_cast<long long>(k)); });
    const std::size_t m = static_cast<std::size_t>(std::max(0LL, n));
    auto Q = [](std::initializer_list<std::pair<std::string, Json>> items) { return Json::object(items); };
    return {{"realisations", Q({{"series", all}})},
            {"realisations", Json::object()},
            {"realisations", Q({{"series", Json(1)}})},
            {"column", Q({{"series", Json::array({Json(0), Json(count - 1)})}, {"at", Json(1)}})},
            {"column", Q({{"series", Json::array({Json(count - 1)})}, {"at", Json(1000000)}})},
            {"column", Q({{"series", Json::array({Json(0)})}, {"at", Json(-3)}})},
            {"column", Q({{"series", all}})},
            {"realisation", Q({{"series", all}, {"index", Json(n - 1)}})},
            {"realisation", Q({{"series", Json::array({Json(0)})}, {"index", Json(1000000)}})},
            {"realisation", Q({{"series", Json::array({Json(count - 1)})}, {"index", Json(-2)}})},
            {"bands", Q({{"percentiles", Json::array({Json(0.1), Json(0.9)})},
                         {"mask", array_of(m, [](std::size_t i) { return Json((i * 7) % 4 == 0 ? 0 : 1); })}})},
            {"bands", Q({{"percentiles", Json()}, {"mask", Json()}})},
            {"bands", Q({{"mask", array_of(m + 1, [](std::size_t) { return Json(1); })}})},
            {"realisations", Q({{"series", Json::array({Json(count)})}})},
            {"realisations", Q({{"series", Json::array({Json(true)})}})},
            {"realisations", Q({{"series", Json::array({Json(1.0)})}})},
            {"realisations", Q({{"series", Json::array({Json(-1)})}})},
            {"realisations", Q({{"series", Json("ab")}})},
            {"column", Q({{"series", Q({{"a", Json(1)}})}})},
            {"column", Q({{"series", Json::array({Json(0)})}, {"at", Json(2.5)}})},
            {"realisation", Q({{"series", Json::array({Json(0)})}, {"index", Json("x")}})},
            {"series", Q({{"labels", Json::array({Json("x")})}})},
            {"forget", Json::object()}};
}

std::string answer(const std::string& op, const ProbabilisticResults& prob, const Json& q) {
    std::string bytes = sample_answer_bytes(Json(op), prob, q);
    std::vector<double> v(bytes.size() / 8);
    if (!v.empty()) std::memcpy(v.data(), bytes.data(), v.size() * 8);
    return nums(v);
}

std::string entries_text(const std::vector<std::pair<std::string, std::string>>& entries) {
    std::vector<std::string> lines;
    for (const auto& [name, bytes] : entries) {
        if (name.size() >= 5 && name.compare(name.size() - 5, 5, ".json") == 0) lines.push_back(name + ":\n" + bytes);
        else lines.push_back(name + "=" + std::to_string(bytes.size()) + ":" + fnv(bytes));
    }
    return joined(lines, "\n");
}

std::string labels_of(const std::vector<std::pair<double, std::vector<double>>>& qs) {
    std::vector<std::string> parts;
    for (const auto& [q, y] : qs) parts.push_back(bits(q) + ":" + nums(y));
    return joined(parts, ";");
}

std::string spread_text(const MedianSpread& m) { return joined({nums(m.err_lo), nums(m.err_hi), nums(m.body_lo), nums(m.body_hi)}, ";"); }

std::string run_case(const Json& c, const Json& model, int threads) {
    auto project = std::make_shared<const Project>(model);
    ProbabilisticOptions o = options_of(c.get("options"), threads);
    ProbabilisticResults prob;
    std::string refused = said([&] {
        prob = run_probabilistic(project, o);
        return std::string();
    });
    if (!refused.empty()) return refused;
    const long long n = prob.iterations;
    std::vector<std::string> names = prob.names;
    Json plan = Json::array();
    for (const auto& e : prob.plan) plan.push(e.json());
    Json outputs = Json::array();
    for (const Json& x : prob.outputs) outputs.push(x);
    std::vector<std::string> lines = {"precision=" + prob.precision + " iterations=" + std::to_string(n) + " range=" + std::to_string(prob.first) + ":" +
                                          std::to_string(prob.last) + " held=" + std::to_string(prob.ran.size()),
                                      "plan=" + tdump(plan), "names=" + joined(names, "|"), "outputs=" + tdump(outputs), "t=" + nums(prob.t)};
    const std::size_t series = prob.single() ? prob.values32.size() : prob.values.size();
    for (std::size_t w = 0; w < series; w++)
        lines.push_back("series " + std::to_string(w + 1) + "=" + (prob.single() ? nums32(prob.values32[w]) : nums(prob.values[w])));
    std::string ran;
    for (std::uint8_t r : prob.ran) ran += std::to_string(r);
    Json inputs = Json::array();
    for (const Json& x : prob.inputs) inputs.push(x);
    lines.push_back("samples=" + nums(prob.samples.data));
    lines.push_back("ran=" + ran);
    lines.push_back("inputs=" + tdump(inputs));
    Json stats = prob.stats.shallow();
    stats.erase("ms");
    stats.erase("threads");
    lines.push_back("stats=" + tdump(stats));
    lines.push_back("labels=" + joined(prob.labels(), "|"));
    if (!prob.outputs.empty()) {
        const std::string label = prob.outputs.back().get("label").as_string();
        lines.push_back("realisations " + label + "=" + nums(prob.realisations(label)));
    }
    lines.push_back("no such label=" + said([&] { return nums(prob.realisations(std::string("no such label"))); }));
    if (!prob.names.empty()) lines.push_back("sample " + prob.names.back() + "=" + nums(prob.sample(prob.names.back())));
    prob.stats = prob.stats.shallow();
    prob.stats.set("ms", Json(1234.5));
    prob.stats.set("threads", Json(1));
    lines.push_back("log\n" + run_log(prob));
    prob.stats.set("threads", Json(3));
    lines.push_back("log\n" + joined(probabilistic_log_lines(prob), "\n"));
    for (bool whole : {true, false})
        lines.push_back(std::string("entries ") + (whole ? "true" : "false") + "\n" + said([&] { return entries_text(sample_entries(prob, Json("then"), whole)); }));
    const long long count = static_cast<long long>(an_count(prob));
    for (const auto& [pname, pct] : percentile_lists())
        for (const auto& [mname, mask] : masks(n)) {
            if (!(pname == "default" || mname == "none" || mname == "mixed")) continue;
            const Json* m = mask.is_null() ? nullptr : &mask;
            lines.push_back("bands " + pname + " " + mname + "\n" + said([&] { return bands_text(bands(prob, pct, m)); }));
        }
    for (const auto& [op, q] : questions(n, count)) lines.push_back("answer " + op + " " + json_text(q, 0) + "=" + said([&] { return answer(op, prob, q); }));
    if (count > 0) {
        const std::string label = an_output(prob, 1).get("label").as_string();
        const Json mask = masks(n)[1].second;
        lines.push_back("quantiles=" + said([&] { return labels_of(quantiles(prob, label)); }));
        lines.push_back("quantiles again=" + said([&] { return labels_of(quantiles(prob, label, {0.9, 0.1, 0.9}, &mask)); }));
        lines.push_back("mean=" + said([&] { return nums(realisations_mean(prob, label, &mask)); }));
        lines.push_back("median spread=" + said([&] { return spread_text(median_spread(prob, label, 1.959964, &mask)); }));
        const std::string last = an_output(prob, static_cast<std::size_t>(count)).get("label").as_string();
        lines.push_back("median spread last=" + said([&] { return spread_text(median_spread(prob, last, 1.0)); }));
    }
    return joined(lines, "\n");
}

std::string replay_case(const Json& c, const Json& model) {
    auto project = std::make_shared<const Project>(model);
    ProbabilisticOptions o = options_of(c.get("options"), 1);
    Replay r;
    std::string refused = said([&] {
        r = run_realisation(project, c.get("number").as_int(), o);
        return std::string();
    });
    if (!refused.empty()) return refused;
    Results& res = r.results;
    std::vector<std::string> counts, values;
    for (const char* key : {"nsteps", "nfailed", "nfevals", "events", "jumps", "restarts"})
        if (res.stats.has(key)) counts.push_back(std::string(key) + "=" + js_text(res.stats.get(key)));
    for (const auto& v : r.values) values.push_back(v.name + "=" + bits(v.value) + ":" + (v.held ? "true" : "false"));
    return "number=" + std::to_string(r.number) + " iterations=" + std::to_string(r.iterations) + " values=" + joined(values, "|") +
           "\npoints=" + std::to_string(res.t.size()) + " " + joined(counts, " ") + "\n" + res.to_csv();
}

std::string take_case(const Json& c, const Json& model) {
    auto project = std::make_shared<const Project>(model);
    auto sys = std::make_shared<System>(project);
    RunOptions options;
    options.on_grid = c.get("on_grid").as_bool();
    Results res = run_project(project, sys, options);
    std::vector<double> grid = project->time_grid();
    std::vector<Json> kept_;
    for (const Json& k : c.get("kept").arr()) kept_.push_back(k);
    std::vector<std::string> lines = {"rows=" + std::to_string(res.t.size()) + " grid=" + std::to_string(grid.size())};
    for (const auto& v : take_realisation(res, kept_, grid)) lines.push_back(nums(v));
    return joined(lines, "\n");
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/probabilistic.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const char* only_env = std::getenv("KOMPARTMENT_PROB_ONLY");
    const std::string only = only_env ? only_env : "";
    set_parity(true);
    std::map<std::string, Json> examples;
    auto model_of = [&](const Json& c) {
        if (c.has("example")) {
            const std::string& ex = c.get("example").as_string();
            if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
            return examples[ex];
        }
        return fx.get("models").get(c.get("model").is_string() ? c.get("model").as_string() : c.get("name").as_string());
    };
    std::string all;
    int n = 0, runs = 0, refused = 0, threaded = 0;
    auto record = [&](const Json& c, const std::string& text) {
        std::string head = "## " + c.get("name").as_string() + " " + json_text(c.get("options"), 0);
        all += (n++ ? "\n\n" : "") + head + "\n" + text;
        CHECK_MSG(kept(text) == c.get("out").as_string(),
                  head + "\n   here:  " + kept(text).substr(0, 300) + "\n   there: " + c.get("out").as_string().substr(0, 300));
    };
    for (const Json& c : fx.get("cases").arr()) {
        if (!only.empty() && c.get("name").as_string().find(only) == std::string::npos) continue;
        const Json model = model_of(c);
        std::string text;
        try {
            text = run_case(c, model, 1);
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(c, text);
        runs++;
        if (text.rfind("error:", 0) == 0) {
            refused++;
            continue;
        }
        // The same run on two threads and on eight: the same, to the bit.
        for (int threads : {2, 8}) {
            std::string again;
            try {
                again = run_case(c, model, threads);
            } catch (const std::exception& e) {
                again = std::string("raised here: ") + e.what();
            }
            CHECK_MSG(again == text, c.get("name").as_string() + " " + json_text(c.get("options"), 0) + ": on " + std::to_string(threads) +
                                         " threads it differs from one");
            threaded++;
        }
    }
    for (const Json& c : fx.get("replays").arr()) {
        if (!only.empty() && c.get("name").as_string().find(only) == std::string::npos) continue;
        std::string text;
        try {
            text = replay_case(c, model_of(c));
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(c, text);
    }
    for (const Json& c : fx.get("takes").arr()) {
        if (!only.empty() && c.get("name").as_string().find(only) == std::string::npos) continue;
        std::string text;
        try {
            text = take_case(c, fx.get("models").get(c.get("name").as_string()));
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        record(c, text);
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/probabilistic.cpp.txt", std::ios::binary) << all;

    // `percentiles_for` on odd lists.
    {
        auto lists = percentile_lists();
        const Json& want = fx.get("percentiles");
        CHECK_EQ(want.size(), lists.size());
        for (std::size_t k = 0; k < lists.size() && k < want.size(); k++)
            CHECK_MSG(nums(percentiles_for(lists[k].second)) == want[k].as_string(), "percentiles_for " + lists[k].first);
    }

    // Progress: once a realisation, one call at a time, `done` rising to the total; and what it
    // throws stops the run, coming out once every thread has finished the realisation it was on.
    if (only.empty() || only == "progress") {
        auto project = std::make_shared<const Project>(fx.get("models").get("every kind"));
        ProbabilisticOptions o;
        o.iterations = 40;
        o.threads = 8;
        std::vector<long long> seen;
        std::atomic<int> inside{0};
        bool overlapped = false;
        o.on_progress = [&](long long done, long long total) {
            if (inside.fetch_add(1) != 0) overlapped = true;
            seen.push_back(done);
            CHECK_EQ(total, 40);
            inside.fetch_sub(1);
        };
        ProbabilisticResults prob = run_probabilistic(project, o);
        CHECK_EQ(seen.size(), std::size_t{40});
        bool rising = true;
        for (std::size_t k = 0; k < seen.size(); k++) rising = rising && seen[k] == static_cast<long long>(k + 1);
        CHECK_MSG(rising, "progress counts each realisation once, rising");
        CHECK(!overlapped);
        CHECK(prob.stats.get("threads").as_int() == std::min(8, static_cast<int>(std::max(1u, std::thread::hardware_concurrency()))));

        struct Stop : std::exception {};
        ProbabilisticOptions s = o;
        long long calls = 0;
        s.on_progress = [&](long long done, long long) {
            calls++;
            if (done == 3) throw Stop();
        };
        bool stopped = false;
        try {
            run_probabilistic(project, s);
        } catch (const Stop&) {
            stopped = true;
        }
        CHECK_MSG(stopped, "what progress throws comes out of the run");
        // (The threads busy when it threw finish the realisation they are on, and say so.)
        CHECK_MSG(calls >= 3 && calls < 40, "the run stops: " + std::to_string(calls) + " realisations said");

        // A first realisation that fails fails the run, whatever the other threads did.
        auto first = std::make_shared<const Project>(fx.get("models").get("first fails"));
        ProbabilisticOptions f;
        f.iterations = 30;
        f.threads = 8;
        std::string failed = said([&] {
            run_probabilistic(first, f);
            return std::string();
        });
        CHECK_MSG(failed.rfind("error:SolverError:A starts at Infinity", 0) == 0, "the first realisation's failure fails the run: " + failed);
    }

    set_parity(false);
    std::printf("%d cases (%d runs, %d refused, %d run again on more threads)\n", n, runs, refused, threaded);
    return check::summary("test_probabilistic");
}
