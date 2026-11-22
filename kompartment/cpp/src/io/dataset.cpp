#include "io/dataset.hpp"

#include <algorithm>
#include <chrono>
#include <cstring>

#include "engine/runlog.hpp"
#include "io/zip.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

std::string f64_bytes(const std::vector<double>& v) {
    std::string out(v.size() * 8, '\0');
    if (!v.empty()) std::memcpy(out.data(), v.data(), out.size());   // little-endian, as every machine this builds for
    return out;
}

// The run's statistics and timings as the application names them.
Json stats_named(const Json& stats) {
    std::vector<std::string> keys = stats.is_object() ? stats.obj().keys() : std::vector<std::string>{};
    std::sort(keys.begin(), keys.end());
    Json out = Json::object();
    for (const auto& k : keys) {
        if (k == "held") continue;
        std::string name = k == "solver_points" ? "solverPoints" : k == "thinned_by" ? "thinnedBy" : k == "steps_by" ? "stepsBy"
                           : k == "krylov_iters" ? "krylovIters" : k;
        out.set(name, stats.get(k));
    }
    return out;
}

Json timing_named(const Json& timing) {
    Json out = Json::object();
    for (const auto& [ours, theirs] : {std::pair<const char*, const char*>{"build_ms", "buildMs"}, {"solve_ms", "solveMs"}, {"total_ms", "totalMs"}})
        if (timing.has(ours)) out.set(theirs, timing.get(ours));
    return out;
}

const char* recorder_kind(RecorderKind k) {
    switch (k) {
        case RecorderKind::MinMax: return "min_max";
        case RecorderKind::RunningMean: return "running_mean";
        case RecorderKind::Snapshot: return "snapshot";
        default: return "delay";
    }
}

}  // namespace

std::string layout_signature(const System& sys, bool counts) {
    std::string s, m;
    for (const auto& x : sys.builder->states) {
        if (!s.empty()) s += ",";
        s += x->kind + ":" + x->name + "@" + std::to_string(x->base) + "+" + std::to_string(x->width);
    }
    for (const auto& r : sys.builder->recorders) {
        if (!m.empty()) m += ",";
        m += r->kind + ":" + r->entry->name + "@" + std::to_string(r->mem) + "+" + std::to_string(r->width);
    }
    const std::string n = counts ? std::to_string(sys.nstate) + "," + std::to_string(sys.nalg) + "," + std::to_string(sys.nparam)
                                 : std::to_string(sys.nstate);
    return "v" + std::to_string(DATASET_FORMAT) + "|n=" + n + "|s=" + s + "|m=" + m;
}

std::string slug(const Json& name) {
    std::string text = name.is_null() ? std::string() : js_text(name);
    std::string s;
    bool gap = false;
    for (unsigned char c : text) {
        bool keep = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_';
        if (keep) {
            if (gap && !s.empty()) s.push_back('-');
            gap = false;
            s.push_back(static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c));
        } else {
            gap = true;
        }
    }
    return s.empty() ? "model" : s;
}

std::string dataset_archive(Results& res, const ArchiveOptions& options) {
    const Json& raw = res.project->raw;
    std::string inner = slug(raw.get("name")) + ".json";
    std::size_t nstate = res.y.empty() ? 0 : res.y[0].size();
    std::vector<double> y;
    if (options.states) {
        y.reserve(res.y.size() * nstate);
        for (const auto& row : res.y) y.insert(y.end(), row.begin(), row.end());
    }
    std::string held;
    if (res.stats.get("held").is_array()) {
        for (const Json& h : res.stats.get("held").arr()) {
            std::int32_t v = static_cast<std::int32_t>(h.as_double());
            held.append(reinterpret_cast<const char*>(&v), 4);
        }
    }
    // Every recorder's history end to end, its times then its values, as the run left them.
    std::vector<double> mem;
    Json recorders = Json::array();
    if (options.states)
        for (const Recorder& m : res.kept.mem) {
            mem.insert(mem.end(), m.history.t.begin(), m.history.t.end());
            mem.insert(mem.end(), m.history.v.begin(), m.history.v.end());
            recorders.push(Json::object({{"kind", Json(recorder_kind(m.kind))}, {"n", Json(static_cast<long long>(m.history.t.size()))},
                                         {"recording", Json(m.recording)}, {"totalTime", Json(m.total_time)}, {"lastTime", Json(m.last_time)},
                                         {"resetSum", Json(m.reset_sum)}}));
        }
    const Json& name = raw.get("name");
    Json meta = Json::object({
        {"format", Json(DATASET_FORMAT)},
        {"kind", Json("ecolego-results")},
        {"model", Json(inner)},
        {"name", name.is_null() ? Json("") : name},
        {"stamp", Json(iso_utc(std::chrono::system_clock::now()))},
        {"times", Json(static_cast<long long>(res.t.size()))},
        {"states", Json(static_cast<long long>(nstate))},
        {"outputs", Json(static_cast<long long>(res.outputs().size()))},
        {"signature", Json(layout_signature(*res.system))},
        {"stats", stats_named(res.stats)},
        {"timing", timing_named(res.timing)},
        {"recorders", recorders},
        {"log", options.log},
    });
    if (!options.states) meta.set("onEngine", Json(true));
    if (options.extra.is_object())
        for (const auto& [k, v] : options.extra.obj()) meta.set(k, v);
    std::vector<std::pair<std::string, std::string>> entries;
    entries.emplace_back(inner, json_text(raw, 2));
    entries.emplace_back("results/meta.json", json_text(meta, 2));
    entries.emplace_back("results/t.f64", f64_bytes(res.t));
    if (options.states) entries.emplace_back("results/y.f64", f64_bytes(y));
    if (!held.empty()) entries.emplace_back("results/held.i32", held);
    if (!mem.empty()) entries.emplace_back("results/mem.f64", f64_bytes(mem));
    return zip_archive(entries, options.compress);
}

}  // namespace kompartment
