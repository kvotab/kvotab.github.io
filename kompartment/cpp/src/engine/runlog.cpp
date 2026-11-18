#include "engine/runlog.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>

#include "engine/jacobian.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

// The words' own characters, in UTF-8.
const std::string EM_DASH = "\xe2\x80\x94";    // --
const std::string EN_DASH = "\xe2\x80\x93";    // -
const std::string RSQUO = "\xe2\x80\x99";      // '
const std::string MINUS = "\xe2\x88\x92";      // -
const std::string TIMES = "\xc3\x97";          // x

// `something(v, fallback)`: the value, or the fallback where there is none.
Json or_else(const Json& v, const Json& fallback) { return v.is_null() ? fallback : v; }

// `v == 1` as Julia compares a value a file or a run holds with 1.
bool is_one(const Json& v) { return (v.is_number() && v.as_double() == 1) || (v.is_bool() && v.as_bool()); }

double number_or(const Json& v, double fallback) { return v.is_null() ? fallback : v.as_double(); }

/// A number as the mass-balance audit's report writes it.
std::string audit_num(double v) {
    if (v == 0) return "0";
    if (std::fabs(v) >= 1e-3 && std::fabs(v) < 1e6) return js_text(std::strtod(js_to_precision(v, 4).c_str(), nullptr));
    return js_to_exponential(v, 3);
}

// Julia's `isspace`: the ASCII white space, U+0085, and the space separators (Zs).
bool julia_space(char32_t c) {
    return (c >= 0x09 && c <= 0x0d) || c == 0x20 || c == 0x85 || c == 0xa0 || c == 0x1680 || (c >= 0x2000 && c <= 0x200a) || c == 0x202f ||
           c == 0x205f || c == 0x3000;
}

// One character at byte `i`, never past the end.
char32_t char_at(std::string_view s, std::size_t i, std::size_t& len) {
    char32_t c = utf8_at(s, i, len);
    if (i + len > s.size()) len = s.size() - i;
    return c;
}

/// Every run of JavaScript's white space (`/\s+/g`) as one space.
std::string one_space(std::string_view text) {
    std::string out;
    bool gap = false;
    for (std::size_t i = 0; i < text.size();) {
        std::size_t len;
        char32_t c = char_at(text, i, len);
        if (julia_space(c) || c == 0xa0 || c == 0xfeff || c == 0x2028 || c == 0x2029 || c == 0x1680 || c == 0x202f || c == 0x205f || c == 0x3000) {
            gap = true;
        } else {
            if (gap) out.push_back(' ');
            gap = false;
            out.append(text.substr(i, len));
        }
        i += len;
    }
    if (gap) out.push_back(' ');
    return out;
}

/// `s.slice(0, units)` in UTF-16 code units, as JavaScript counts them.
std::string utf16_prefix(std::string_view s, int units) {
    int n = 0;
    for (std::size_t i = 0; i < s.size();) {
        std::size_t len;
        char32_t c = char_at(s, i, len);
        n += c >= 0x10000 ? 2 : 1;
        if (n > units) return std::string(s.substr(0, i));
        i += len;
    }
    return std::string(s);
}

/// Julia's `strip`: its white space off both ends.
std::string julia_strip(std::string_view s) {
    std::size_t a = 0;
    while (a < s.size()) {
        std::size_t len;
        if (!julia_space(char_at(s, a, len))) break;
        a += len;
    }
    std::size_t b = s.size();
    while (b > a) {
        std::size_t start = b - 1;
        while (start > a && (static_cast<unsigned char>(s[start]) & 0xc0) == 0x80) start--;
        std::size_t len;
        if (!julia_space(char_at(s, start, len))) break;
        b = start;
    }
    return std::string(s.substr(a, b - a));
}

// What `"$(v)"` makes of a value Julia reads from a file: text as it is, every other value
// as JavaScript writes it (the same for what a model file holds there).
std::string as_text(const Json& v) { return v.is_string() ? v.as_string() : js_text(v); }

bool given(const Json& v) { return !v.is_null() && !(v.is_string() && v.as_string().empty()); }

/// One line per setting, in the order somebody reads them.
std::vector<std::string> settings_lines(const Json& sim, const Json& raw) {
    std::vector<std::string> out;
    auto put = [&](const std::string& label, const Json& v) {
        if (given(v)) out.push_back("  " + label + ": " + js_text(v));
    };
    put("time unit", sim.get("time_unit"));
    put("span", Json(js_text(sim.get("start_time")) + " " + EN_DASH + " " + js_text(sim.get("end_time"))));
    const Json& spacing = sim.get("spacing");
    put("output times", spacing == "series" ? Json("a series of the model" + RSQUO + "s own")
                                            : Json(js_text(or_else(sim.get("output_points"), Json("?"))) + ", " + (spacing.is_null() ? "log" : as_text(spacing))));
    put("solver", sim.get("solver"));
    put("relative tolerance", sim.get("rtol"));
    put("absolute tolerance", sim.get("abstol"));
    const Json& non_negative = sim.get("non_negative");
    put("cannot go negative", Json(non_negative.is_bool() && !non_negative.as_bool() ? "off everywhere" : "per compartment"));
    if (js_truthy(sim.get("mass_balance"))) put("mass-balance audit", Json("on"));
    if (js_truthy(sim.get("auto_abstol")))
        put("tolerance follows the solution", Json("each component" + RSQUO + "s absolute tolerance rises with it"));
    Json unit = or_else(raw.get("decay_unit"), or_else(raw.get("decayUnit"), Json("")));
    put("decay unit", Json(julia_strip(js_text(unit)) == "mol" ? "mol" : "Bq"));
    const Json& ceiling = sim.get("decay_ceiling");
    // `ceiling isa Real && ceiling > 0`: a number, or `true`.
    if ((ceiling.is_number() && ceiling.as_double() > 0) || (ceiling.is_bool() && ceiling.as_bool()))
        put("decay chains stop above", Json(js_text(ceiling) + " years"));
    return out;
}

}  // namespace

std::string iso_utc(std::chrono::system_clock::time_point at) {
    using namespace std::chrono;
    const long long ms = duration_cast<milliseconds>(at.time_since_epoch()).count();
    long long secs = ms / 1000, frac = ms % 1000;
    if (frac < 0) {
        frac += 1000;
        secs -= 1;
    }
    std::time_t t = static_cast<std::time_t>(secs);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[40];
    std::snprintf(buf, sizeof buf, "%04d-%02d-%02dT%02d:%02d:%02d.%03lldZ", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min,
                  tm.tm_sec, frac);
    return buf;
}

std::vector<std::string> describe_audit(const Json& a, const std::string& time_unit) {
    const std::string unit = time_unit.empty() ? "" : " " + time_unit;
    std::vector<std::string> out;
    if (a.get("closed").as_bool()) {
        std::string line = "mass balance: closes " + EM_DASH + " worst relative residual " + js_to_exponential(a.get("worst").as_double(), 1);
        if (!a.get("worstFamily").is_null())
            line += " (" + as_text(a.get("worstFamily")) + " at t = " + audit_num(a.get("at").as_double()) + unit + ")";
        out.push_back(line);
    } else {
        out.push_back("mass balance: DOES NOT CLOSE " + EM_DASH + " relative residual " + js_to_exponential(a.get("worst").as_double(), 2) + " in " +
                      js_text(a.get("worstFamily")) + " at t = " + audit_num(a.get("at").as_double()) + unit +
                      "; a state held at zero, or an amount the equations moved that nothing accounts for");
    }
    for (const Json& f : a.get("families").arr()) {
        const std::string name = as_text(f.get("name"));
        if (f.get("unresolved").as_bool()) {
            out.push_back("  " + name + ": never more than " + audit_num(f.get("scale").as_double()) + " held or moved, within the absolute tolerance " +
                          audit_num(f.get("floor").as_double()) + " -- too little for the solver to resolve, so not audited");
            continue;
        }
        if (f.get("idle").as_bool()) {
            out.push_back("  " + name + ": nothing held or moved");
            continue;
        }
        const Json& r = f.get("final");
        std::vector<std::string> parts = {"start " + audit_num(r.get("start").as_double()), "+ in " + audit_num(r.get("in").as_double()),
                                          MINUS + " out " + audit_num(r.get("out").as_double()), MINUS + " decay " + audit_num(r.get("decay").as_double()),
                                          "+ ingrowth " + audit_num(r.get("ingrowth").as_double())};
        for (const char* key : {"explicit", "between"}) {
            double x = r.get(key).as_double();
            if (x != 0) parts.push_back((x < 0 ? MINUS : std::string("+")) + " " + key + " " + audit_num(std::fabs(x)));
        }
        out.push_back("  " + name + ": holds " + audit_num(r.get("inventory").as_double()) + " at the end = " + join(parts, " ") + "; residual " +
                      audit_num(r.get("residual").as_double()) + " (" + js_to_exponential(f.get("relative").as_double(), 1) +
                      " relative, worst at t = " + audit_num(f.get("at").as_double()) + unit + ")");
    }
    return out;
}

std::optional<std::string> describe_method_steps(const Json& stats) {
    const Json& by = stats.get("steps_by").is_null() ? stats.get("stepsBy") : stats.get("steps_by");
    if (!by.is_object()) return std::nullopt;
    std::vector<std::string> parts;
    bool first = true;
    for (const auto& [name, n] : by.obj()) {
        parts.push_back(name + " " + js_text(n) + (first ? std::string(" step") + (is_one(n) ? "" : "s") : std::string()));
        first = false;
    }
    Json sw = or_else(stats.get("switches"), Json(0));
    return join(parts, ", ") + "; " + js_text(sw) + " switch" + (is_one(sw) ? "" : "es");
}

std::vector<std::string> run_log_lines(Results& res, const RunLogOptions& options) {
    const Json& raw = options.project ? *options.project : res.project->raw;
    const Json& sim = res.project->simulation;
    const Json& s = res.stats;
    std::vector<std::string> out;
    out.push_back("Kompartment run log" + (options.build.empty() ? std::string() : " " + EM_DASH + " build " + options.build));
    out.push_back(iso_utc(options.at));
    out.push_back("model: " + js_text(or_else(raw.get("name"), Json("Untitled"))));
    const Json& description = raw.get("description");
    if (description.is_string() && !description.as_string().empty()) out.push_back("  " + utf16_prefix(one_space(description.as_string()), 200));
    out.push_back("");
    out.push_back("settings");
    for (auto& line : settings_lines(raw.get("simulation").is_object() ? raw.get("simulation") : sim, raw)) out.push_back(std::move(line));
    out.push_back("");
    out.push_back("run");
    const Json& integrated = s.get("integrated");
    if (integrated.is_bool() && !integrated.as_bool()) {
        out.push_back("  nothing integrated: no compartments, the algebraic blocks over the output grid");
    } else {
        out.push_back("  states: " + std::to_string(res.system->nstate));
        out.push_back("  steps: " + js_text(or_else(s.get("nsteps"), Json("?"))) + ", rejected: " + js_text(or_else(s.get("nfailed"), Json(0))) +
                      ", f evaluations: " + js_text(or_else(s.get("nfevals"), Json("?"))));
        if (auto methods = describe_method_steps(s)) out.push_back("  methods: " + *methods);
        const Json& asked = s.get("asked");
        if (!asked.is_null())
            out.push_back("  solver run: " + js_text(s.get("solver")) + ", the quicker for the " + js_text(asked) + " the model asks for");
        const Json& tried = s.get("tried");
        if (!tried.is_null()) out.push_back("  solver run: the model's own, after " + js_text(tried) + " could not finish");
        if (js_truthy(s.get("nbelowtol"))) out.push_back("  steps taken below tolerance: " + js_text(s.get("nbelowtol")));
        if (!s.get("events").is_null())
            out.push_back("  events: " + js_text(s.get("events")) + ", restarts: " + js_text(or_else(s.get("restarts"), Json(0))));
        if (!s.get("jumps").is_null())
            out.push_back("  jumps: " + js_text(s.get("jumps")) + " " + EM_DASH +
                          " package failures at a time and disruptive events, applied to the state at their corners and crossings");
        const auto& j = res.system->jacobian;
        if (j && j->available) {
            const Json& sparse = s.get("sparse");
            out.push_back(std::string("  df/dy: analytic, ") + (sparse.is_bool() && sparse.as_bool() ? "sparse" : "dense") +
                          (j->colours > 0 ? ", " + std::to_string(j->colours) + " colours" : std::string()) + (j->constant ? ", constant" : ""));
        } else if (j) {
            out.push_back("  df/dy: differenced" + (j->reason && !j->reason->empty() ? " " + EM_DASH + " " + *j->reason : std::string()));
        }
    }
    const Json& split = s.get("split");
    if (split.is_object() && js_truthy(split.get("used"))) {
        const Json jobs = or_else(split.get("jobs"), Json::array());
        out.push_back("  split: " + js_text(or_else(split.get("parts"), Json(static_cast<long long>(jobs.size())))) + " independent parts on " +
                      js_text(split.get("workers")) + " cores (" + js_text(split.get("mode")) + ") " + EM_DASH + " " + js_text(split.get("why")));
        // One line per thread: the parts it was given, solved together.
        if (jobs.is_array())
            for (const Json& job : jobs.arr()) {
                std::vector<std::string> materials;
                const Json listed = or_else(job.get("materials"), Json::array());
                if (listed.is_array())
                    for (const Json& m : listed.arr()) materials.push_back(js_text(m));
                out.push_back("    " + join(materials, ", ") + ": " + js_text(job.get("states")) + " states, " + js_text(or_else(job.get("nsteps"), Json("?"))) +
                              " steps, compile " + js_to_fixed(number_or(job.get("buildMs"), 0), 1) + " ms, solve " +
                              js_to_fixed(number_or(job.get("solveMs"), 0), 0) + " ms");
            }
        const Json& gain = split.get("gain");
        if (js_truthy(gain)) out.push_back("    about " + js_to_fixed(gain.as_double(), 1) + TIMES + " a whole solve, by this machine's estimate");
    } else if (split.is_object()) {
        out.push_back("  not split (" + js_text(split.get("mode")) + "): " + js_text(split.get("why")));
    }
    out.push_back("  output points: " + std::to_string(res.t.size()));
    out.push_back("  series: " + std::to_string(res.outputs().size()));
    out.push_back("  compile: " + js_to_fixed(number_or(res.timing.get("build_ms"), 0.0), 1) + " ms, solve: " +
                  js_to_fixed(number_or(res.timing.get("solve_ms"), 0.0), 0) + " ms");
    const std::vector<Json> held = res.held_at_zero();
    if (!held.empty()) {
        out.push_back("");
        out.push_back("held at zero: " + std::to_string(held.size()) + " state" + (held.size() == 1 ? "" : "s") + " the model pushed below zero");
        for (std::size_t i = 0; i < held.size() && i < 20; i++)
            out.push_back("  " + held[i].get("label").as_string() + ": " + js_text(held[i].get("steps")) + " steps, " +
                          js_to_fixed(100 * held[i].get("fraction").as_double(), 1) + "% of the run");
        if (held.size() > 20) out.push_back("  and " + std::to_string(held.size() - 20) + " more");
    }
    for (const char* key : {"farfield", "layers"}) {
        const Json& said = s.get(key);
        if (!(said.is_array() && !said.empty())) continue;
        const std::size_t n = said.size();
        out.push_back("");
        if (std::string(key) == "farfield")
            out.push_back("semi-analytical far-field paths: " + std::to_string(n) + " unit response" + (n == 1 ? "" : "s") + " missed " +
                          (n == 1 ? "its" : "their") + " mass balance");
        else
            out.push_back("far-field matrix layers: " + std::to_string(n) + " " + (n == 1 ? "path grows" : "paths grow") + " coarse at depth");
        for (const Json& w : said.arr()) out.push_back("  " + js_text(w.get("block")) + ": " + js_text(w.get("message")));
    }
    const Json audit = res.mass_balance();
    if (!audit.is_null()) {
        out.push_back("");
        const Json& unit = sim.get("time_unit");
        for (auto& line : describe_audit(audit, unit.is_null() ? std::string() : as_text(unit))) out.push_back(std::move(line));
    }
    return out;
}

std::string run_log(Results& res, const RunLogOptions& options) { return join(run_log_lines(res, options), "\n"); }

}  // namespace kompartment
