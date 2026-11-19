#include "io/sample.hpp"

#include <chrono>
#include <cstring>

#include "engine/project.hpp"
#include "engine/runlog.hpp"
#include "io/dataset.hpp"
#include "io/zip.hpp"
#include "util/errors.hpp"

namespace kompartment {

namespace {

const char* const SAMPLE_DIR = "results/sample/";

/// Little-endian bytes of numbers, as every machine this builds for holds them.
template <typename T>
std::string le_bytes(const std::vector<T>& v) {
    std::string out(v.size() * sizeof(T), '\0');
    if (!v.empty()) std::memcpy(out.data(), v.data(), out.size());
    return out;
}

/// Each of a list of input numbers (from 1) counted from 0.
Json from_zero(const Json& list) {
    Json out = Json::array();
    for (const Json& k : list.arr()) out.push(Json(k.as_int() - 1));
    return out;
}

}  // namespace

Json sample_stats(const Json& stats) {
    Json out = stats;
    const Json& tornado = stats.get("tornado");
    if (tornado.is_object() && tornado.has("swung")) {
        out = out.shallow();
        Json mine = tornado.shallow();
        mine.set("swung", from_zero(tornado.get("swung")));
        out.set("tornado", mine);
    }
    const Json& gsa = stats.get("gsa");
    if (gsa.is_object() && gsa.get("factors").is_array()) {
        out = out.shallow();
        Json factors = Json::array();
        for (const Json& f : gsa.get("factors").arr()) {
            if (f.is_object() && f.has("members")) {
                Json mine = f.shallow();
                mine.set("members", from_zero(f.get("members")));
                factors.push(mine);
            } else {
                factors.push(f);
            }
        }
        Json mine = gsa.shallow();
        mine.set("factors", factors);
        out.set("gsa", mine);
    }
    return out;
}

std::vector<std::pair<std::string, std::string>> sample_entries(const ProbabilisticResults& r, const Json& stamp, bool series) {
    const long long n = r.iterations;
    const std::size_t times = r.t.size();
    const std::size_t kept = r.single() ? r.values32.size() : r.values.size();
    // A series is held a realisation to a row, as the file has it: each realisation's times
    // one after another.
    for (std::size_t j = 0; j < kept; j++)
        if (r.held() != n)
            throw ArgumentError("series " + std::to_string(j + 1) + " is " + std::to_string(r.held()) + " \xc3\x97 " + std::to_string(times) + ", not " +
                                std::to_string(n) + " \xc3\x97 " + std::to_string(times) + ": a part of a run cannot be written as a sample");
    // Each input's values, an input after another.
    std::vector<double> draws;
    draws.reserve(r.samples.data.size());
    for (std::size_t k = 0; k < r.samples.inputs; k++)
        for (long long i = 0; i < r.samples.realisations; i++) draws.push_back(r.samples(k, i));
    Json outputs = Json::array();
    Json flat = Json::array();
    Json drawn_from = Json::array();
    for (const Json& o : r.outputs) {
        outputs.push(o);
        flat.push(Json(0));
        drawn_from.push(Json(-1));
    }
    for (const Json& inp : r.inputs) {
        outputs.push(inp.get("output"));
        flat.push(Json(1));
        drawn_from.push(Json(inp.get("k").as_int() - 1));
    }
    Json plan = Json::array();
    for (const auto& e : r.plan) plan.push(e.json());
    Json meta = Json::object({
        {"format", Json(SAMPLE_FORMAT)},
        {"kind", Json("kompartment-sample")},
        {"stamp", stamp},
        {"iterations", Json(n)},
        {"times", Json(static_cast<long long>(times))},
        {"precision", Json(r.single() ? "float32" : "double")},
        {"kept", Json(static_cast<long long>(kept))},
        {"outputs", outputs},
        {"flat", flat},
        {"drawnFrom", drawn_from},
        {"plan", plan},
        {"stats", sample_stats(r.stats)},
    });
    if (!series) meta.set("onEngine", Json(true));
    std::vector<std::pair<std::string, std::string>> entries;
    entries.emplace_back(std::string(SAMPLE_DIR) + "meta.json", json_text(meta, 1));
    entries.emplace_back(std::string(SAMPLE_DIR) + "t.f64", le_bytes(r.t));
    if (series) {
        if (r.single()) {
            std::vector<float> held;
            for (const auto& m : r.values32) held.insert(held.end(), m.begin(), m.end());
            entries.emplace_back(std::string(SAMPLE_DIR) + "series.f32", le_bytes(held));
        } else {
            std::vector<double> held;
            for (const auto& m : r.values) held.insert(held.end(), m.begin(), m.end());
            entries.emplace_back(std::string(SAMPLE_DIR) + "series.f64", le_bytes(held));
        }
    }
    entries.emplace_back(std::string(SAMPLE_DIR) + "draws.f64", le_bytes(draws));
    entries.emplace_back(std::string(SAMPLE_DIR) + "ran.u8", std::string(r.ran.begin(), r.ran.end()));
    return entries;
}

std::string sample_archive(const ProbabilisticResults& r, const SampleArchiveOptions& options) {
    const Json& raw = options.project ? *options.project : r.project->raw;
    std::string name = options.inner ? *options.inner : slug(raw.get("name")) + ".json";
    std::vector<std::pair<std::string, std::string>> entries;
    entries.emplace_back(name, json_text(raw, 2));
    Json stamp = options.stamp ? *options.stamp : Json(iso_utc(std::chrono::system_clock::now()));
    for (auto& e : sample_entries(r, stamp, options.series)) entries.push_back(std::move(e));
    return zip_archive(entries, options.compress, options.modified);
}

}  // namespace kompartment
