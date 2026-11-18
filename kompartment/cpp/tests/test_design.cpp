// The designs of probabilistic runs against the Julia package's
// (tools/design_fixtures.jl writes tests/fixtures/design.json): for every bundled
// example and models made up to reach each branch, under seeds, iteration counts,
// varied lists, tornadoes and every sensitivity method -- the sampling plan, the
// names, every value drawn, the statistics and a sensitivity design's own, to the
// bit; what realisations in several ranges are set to; and the system each of a few
// realisations is set into: its parameters, invariant slots, tables and dice. Or the
// refusal, in the same words.

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/probabilistic.hpp"
#include "engine/project.hpp"
#include "engine/system.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

std::string bits(double x) {
    if (std::isnan(x)) return "nan";
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
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
std::string nums(const double* v, std::size_t n) {
    std::string s;
    for (std::size_t i = 0; i < n; i++) s += (i ? "," : "") + bits(v[i]);
    return s;
}
std::string nums(const std::vector<double>& v) { return nums(v.data(), v.size()); }
double unF(const Json& s) {
    std::uint64_t u = std::strtoull(s.as_string().c_str() + 2, nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}

std::string said(const std::function<std::string()>& f) {
    try {
        return f();
    } catch (const ArgumentError& e) {
        return std::string("error:ArgumentError:") + e.what();
    } catch (const JuliaError& e) {
        return "error:" + e.kind;
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

std::string tdump(const GsaDesign& d) {
    std::string s = "{";
    bool first = true;
    for (const auto& [k, x] : d.fields.obj()) {
        s += (first ? "" : ";") + k + "=";
        first = false;
        if (k == "u") {
            s += "[";
            for (int r = 0; r < d.K; r++) {
                s += (r ? ",[" : "[");
                for (long long c = 0; c < d.runs; c++) s += (c ? "," : "") + ("f" + bits(d.at(r, c)));
                s += "]";
            }
            s += "]";
        } else {
            s += tdump(x);
        }
    }
    return s + "}";
}

DesignOptions options_of(const Json& o) {
    DesignOptions d;
    if (o.has("seed")) d.seed = o.get("seed");
    if (o.has("iterations")) {
        const Json& v = o.get("iterations");
        d.iterations = v.is_string() ? unF(v) : v.as_double();
    }
    if (o.has("latin")) d.latin = o.get("latin").as_bool();
    if (o.has("varied")) {
        std::vector<std::string> varied;
        for (const Json& v : o.get("varied").arr()) varied.push_back(v.as_string());
        d.varied = varied;
    }
    if (o.has("tornado")) d.tornado = o.get("tornado");
    if (o.has("gsa")) d.gsa = o.get("gsa");
    return d;
}

std::string system_text(const System& sys) {
    std::vector<double> X;
    for (int i = 0; i < sys.nalg; i++)
        if (sys.builder->slot_class[static_cast<std::size_t>(i)] == 0) X.push_back(sys.X[static_cast<std::size_t>(i)]);
    std::string tabs, times;
    for (std::size_t i = 0; i < sys.data.TAB.size(); i++) tabs += (i ? ";" : "") + nums(sys.data.TAB[i]->y);
    for (std::size_t i = 0; i < sys.sampled_times.size(); i++) times += (i ? ";" : "") + nums(sys.sampled_times[i]);
    return "P=" + nums(sys.P) + "\nX=" + nums(X) + "\nTAB=" + tabs + "\nDIS=" + nums(sys.data.DIS) + "\nT=" + times;
}

std::string run_case(const Json& c, const Json& model) {
    auto project = std::make_shared<const Project>(model);
    auto sys = std::make_shared<System>(project);
    DesignOptions o = options_of(c.get("options"));
    SampleDesign d;
    std::string refused = said([&] {
        d = design_for(*project, *sys, o);
        return std::string();
    });
    if (!refused.empty()) return refused;
    // The plan alone, the system built for it without its Jacobian: the design's.
    if (c.get("options").empty()) {
        Json alone = Json::array();
        for (const auto& e : sampling_plan(project)) alone.push(e.json());
        CHECK_MSG(tdump(alone) == tdump(d.plan_json()), c.get("name").as_string() + ": the sampling plan alone differs");
    }
    long long n = d.iterations;
    std::vector<std::string> names;
    std::string varies;
    for (std::size_t k = 0; k < d.plan.size(); k++) varies += d.varies[k] ? "1" : "0";
    std::string joined;
    for (std::size_t k = 0; k < d.names.size(); k++) joined += (k ? "|" : "") + d.names[k];
    std::vector<std::string> lines = {"plan=" + tdump(d.plan_json()),
                                      "names=" + joined,
                                      "best=" + nums(d.best),
                                      "varies=" + varies,
                                      "iterations=" + std::to_string(n),
                                      "values=" + nums(d.values.data),
                                      "seed=" + tdump(d.seed),
                                      "stats=" + tdump(d.stats),
                                      "gsa=" + (d.gsa_design ? tdump(*d.gsa_design) : std::string("none")),
                                      std::string("designed=") + (d.is_designed() ? "true" : "false") + "," + (d.is_tornado() ? "true" : "false") +
                                          "," + (d.is_gsa() ? "true" : "false")};
    const long long ranges[7][2] = {{0, n}, {1, std::min(n, 4LL)}, {n - 1, n}, {0, 0}, {2, 2}, {n, n + 1}, {3, 1}};
    for (const auto& r : ranges)
        lines.push_back("effective " + std::to_string(r[0]) + " " + std::to_string(r[1]) + "=" +
                        said([&] { return nums(effective_values(d, r[0], r[1]).data); }));
    ValueTable eff = effective_values(d, 0, n);
    lines.push_back("built\n" + system_text(*sys));
    for (long long i : {0LL, 1LL, n - 1, 1LL}) {
        if (!(0 <= i && i < n)) continue;
        std::string failed = said([&] {
            apply_realisation(*sys, d, eff, i, i);
            return std::string();
        });
        if (!failed.empty()) {
            lines.push_back("realisation " + std::to_string(i) + ": " + failed);
            break;
        }
        lines.push_back("realisation " + std::to_string(i) + "\n" + system_text(*sys));
    }
    std::string text;
    for (std::size_t k = 0; k < lines.size(); k++) text += (k ? "\n" : "") + lines[k];
    return text;
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/design.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    set_parity(true);
    for (const Json& e : fx.get("endpoints").arr())
        CHECK_MSG(can_be_endpoint(e[0]) == e[1].as_bool(), "can_be_endpoint(" + json_text(e[0], 0) + ")");
    std::map<std::string, Json> examples;
    std::string all;
    int n = 0;
    for (const Json& c : fx.get("cases").arr()) {
        Json model;
        if (c.has("example")) {
            const std::string& ex = c.get("example").as_string();
            if (!examples.count(ex)) examples[ex] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + ex + ".json"));
            model = examples[ex];
        } else {
            model = fx.get("models").get(c.get("model").as_string());
        }
        std::string head = "## " + c.get("name").as_string() + " " + json_text(c.get("options"), 0);
        std::string text;
        try {
            text = run_case(c, model);
        } catch (const std::exception& e) {
            text = std::string("raised here: ") + e.what();
        }
        all += (n++ ? "\n\n" : "") + head + "\n" + text;
        CHECK_MSG(kept(text) == c.get("out").as_string(), head + "\n   here:  " + kept(text).substr(0, 200) + "\n   there: " + c.get("out").as_string().substr(0, 200));
    }
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/design.cpp.txt", std::ios::binary) << all;
    set_parity(false);
    std::printf("%d cases\n", n);
    return check::summary("test_design");
}
