// Solving a model in its independent parts, against the Julia package's
// (tools/split_fixtures.jl writes tests/fixtures/split.json): for every bundled example
// and models made up to reach each branch, the partition, the names states are filed back
// by, their materials, the jobs, every plan under 33 sets of options and 3 sets of
// constants -- its decision, its words, its bins and the jobs its threads are given -- and
// the far-field paths' layers as the whole model lays them out; split runs at 2 and 4
// threads and on bins fixed by hand -- every state and every series to the bit, the counts
// summed, the account and the run log; a split that fails and is solved whole; the formulas
// on numbers made up for them; patterns partitioned; parts assembled and refused; models cut
// to one job's materials and built.
//
// Besides, here: every split run again on 1, 2, 3 and 8 threads for the same bins, the same
// bits; progress said and a run stopped; a split whose progress throws, solved whole, to the
// bit of a whole run; a run side by side, one thread, a system given; what auto learns, in
// this process and in its file; this engine's constants.
//
// KOMPARTMENT_SPLIT_ONLY=text runs only the cases whose name holds it (for a sanitizer build).
// KOMPARTMENT_SPLIT_TIMING=1 times a made-up model of independent chains, whole and split.

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <regex>
#include <set>
#include <string>
#include <thread>
#include <vector>

#include "check.hpp"
#include "engine/builder.hpp"
#include "engine/farfield.hpp"
#include "engine/project.hpp"
#include "engine/runlog.hpp"
#include "engine/runner.hpp"
#include "engine/split.hpp"
#include "engine/transport.hpp"
#include "model/names.hpp"
#include "util/errors.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;
namespace fs = std::filesystem;

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
std::string shorter(const std::string& text) { return text.size() <= 200 ? text : "#" + fnv(text); }
std::string joined(const std::vector<std::string>& parts, const std::string& by) {
    std::string s;
    for (std::size_t i = 0; i < parts.size(); i++) s += (i ? by : "") + parts[i];
    return s;
}
std::string nums(const std::vector<double>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + bits(v[i]);
    return s;
}
template <typename T>
std::string ints(const std::vector<T>& v) {
    std::string s;
    for (std::size_t i = 0; i < v.size(); i++) s += (i ? "," : "") + std::to_string(v[i]);
    return s;
}
template <typename T>
std::string ints(const std::optional<std::vector<T>>& v) {
    return v ? ints(*v) : "null";
}
std::string num(const std::optional<double>& v) { return v ? bits(*v) : "null"; }
std::string num(const Json& v) { return v.is_null() ? "null" : bits(v.as_double()); }
std::string str(const std::optional<std::string>& v) { return v ? *v : "null"; }
std::string yes(bool b) { return b ? "true" : "false"; }

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
    } catch (const ValidationError& e) {
        return std::string("error:ValidationError:") + e.what();
    } catch (const std::invalid_argument& e) {
        return std::string("error:ArgumentError:") + e.what();
    } catch (const NotSupported&) {
        throw;
    } catch (const std::runtime_error& e) {
        return std::string("error:ErrorException:") + e.what();
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
/// A dictionary Julia keeps in no order of its own, its keys sorted; `without` left out.
std::string sorted_dump(const Json& d, const std::string& without = "") {
    std::vector<std::string> keys;
    for (const auto& [k, _] : d.obj())
        if (k != without) keys.push_back(k);
    std::sort(keys.begin(), keys.end());
    std::string s = "{";
    for (std::size_t i = 0; i < keys.size(); i++) s += (i ? ";" : "") + keys[i] + "=" + tdump(d.get(keys[i]));
    return s + "}";
}

std::vector<std::string> strings(const Json& list) {
    std::vector<std::string> out;
    for (const Json& v : list.arr()) out.push_back(v.as_string());
    return out;
}

SplitConstants constants_of(const Json& c) {
    SplitConstants k;
    k.shared_work = c.get("shared_work").as_double();
    k.auto_states = c.get("auto_states").as_int();
    k.auto_solve_ms = c.get("auto_solve_ms").as_double();
    k.auto_gain = c.get("auto_gain").as_double();
    k.auto_gain_untimed = c.get("auto_gain_untimed").as_double();
    k.start_ms = c.get("start_ms").as_double();
    if (!c.get("build_fixed").is_null()) k.build_fixed = c.get("build_fixed").as_double();
    k.build_contention = c.get("build_contention").as_double();
    k.untimed_bins = c.get("untimed_bins").as_int();
    return k;
}

std::string jobs_text(const std::vector<SplitJob>& jobs) {
    std::vector<std::string> parts;
    for (const auto& j : jobs) parts.push_back(joined(j.materials, ",") + "/" + std::to_string(j.states));
    return joined(parts, ";");
}
std::string recorders_text(const std::vector<SplitRecorder>& rs) {
    std::vector<std::string> parts;
    for (const auto& r : rs) parts.push_back(r.key + "/" + std::to_string(r.job) + "/" + std::to_string(r.slot));
    return joined(parts, ";");
}
std::string bins_text(const std::vector<std::vector<int>>& bins) {
    std::vector<std::string> parts;
    for (const auto& b : bins) parts.push_back(ints(b));
    return joined(parts, ";");
}

std::string plan_text(const SplitPlan& plan) {
    std::string t = "use=" + yes(plan.use) + " mode=" + plan.mode + " why=" + plan.why + " predicted=" + num(plan.predicted);
    if (!plan.use) return t;
    BinnedJobs binned = bin_jobs(plan);
    return t + " jobs=" + jobs_text(plan.jobs) + " owner=" + shorter(ints(plan.owner)) + " bins=" + bins_text(plan.bins) +
           " parts=" + std::to_string(plan.parts) + " recorders=" + recorders_text(plan.recorders) + " | binned jobs=" + jobs_text(binned.jobs) +
           " owner=" + shorter(ints(binned.owner)) + " recorders=" + recorders_text(binned.recorders);
}

PlanOptions plan_options(const Json& o, const SplitConstants& c) {
    PlanOptions p;
    p.mode = o.get("mode");
    p.workers = o.get("workers").as_double();
    p.nest = !(o.get("nest") == Json(false));
    p.build_ms = o.has("build_ms") ? o.get("build_ms").as_double() : 0.0;
    p.known = o.get("known");
    p.on_grid = o.get("on_grid") == Json(true);
    p.constants = c;
    return p;
}

std::string model_text(const Json& model, const Json& options, const std::vector<SplitConstants>& constants) {
    auto project = std::make_shared<const Project>(model.copy());
    auto sys = std::make_shared<System>(project);
    std::vector<std::string> lines;
    Partition part = partition_of(*sys);
    lines.push_back("partition ok=" + yes(part.ok) + " refusal=" + str(part.refusal) + " count=" + std::to_string(part.count) +
                    " largest=" + std::to_string(part.largest) + " of=" + shorter(ints(part.of)) + " sizes=" + shorter(ints(part.sizes)));
    if (sys->nstate > 0) {
        auto keys = state_keys(*sys);
        lines.push_back("keys=" + (keys ? shorter(joined(*keys, "|")) : std::string("null")));
        std::vector<std::string> ms;
        for (const auto& m : state_materials(*sys)) ms.push_back(m ? *m : "~");
        lines.push_back("materials=" + shorter(joined(ms, "|")));
    }
    SplitJobs jobs = split_jobs(*sys);
    lines.push_back(jobs.why ? "jobs why=" + *jobs.why
                             : "jobs=" + jobs_text(jobs.jobs) + " owner=" + shorter(ints(jobs.owner)) + " parts=" + std::to_string(jobs.parts) +
                                   " recorders=" + recorders_text(jobs.recorders));
    for (std::size_t i = 0; i < options.size(); i++)
        for (std::size_t k = 0; k < constants.size(); k++) {
            const PlanOptions po = plan_options(options[i], constants[k]);
            lines.push_back("plan " + std::to_string(i + 1) + "/" + std::to_string(k + 1) + " " + said([&] { return plan_text(plan_split(*sys, *project, po)); }));
        }
    // Last: laying the layers out works the whole system out at its first instant.
    auto layers = whole_layers(*sys, *project);
    if (!layers) {
        lines.push_back("layers=null");
    } else {
        for (const auto& [path, combos] : *layers)
            for (const auto& [key, g] : combos) {
                std::string shown = key;
                std::replace(shown.begin(), shown.end(), '\0', '|');
                lines.push_back("layers " + path + " " + shown + " d=" + nums(g.d) + " h=" + nums(g.h) + " q=" + bits(g.q));
            }
    }
    return joined(lines, "\n");
}

Json with_split(const Json& raw, const std::string& mode) {
    Json r = raw.copy();
    if (!r.get("simulation").is_object()) r.set("simulation", Json::object());
    r["simulation"].set("split", Json(mode));
    return r;
}

std::string results_text(Results& res) {
    std::vector<std::string> rows;
    for (const auto& row : res.y) rows.push_back(nums(row));
    return "t=" + nums(res.t) + "\ny=" + joined(rows, ";") + "\ncsv\n" + res.to_csv();
}

std::string account_text(const Json& account) {
    std::vector<std::string> keys;
    for (const auto& [k, _] : account.obj()) keys.push_back(k);
    std::string line = "account keys=" + joined(keys, ",") + " used=" + yes(account.get("used").as_bool()) + " mode=" + account.get("mode").as_string() +
                       " why=" + account.get("why").as_string() + " predicted=" + num(account.get("predicted"));
    if (!account.get("used").as_bool()) return line;
    std::vector<std::string> jobs;
    for (const Json& j : account.get("jobs").arr()) {
        std::vector<std::string> jk;
        for (const auto& [k, _] : j.obj()) jk.push_back(k);
        jobs.push_back(joined(strings(j.get("materials")), ",") + "/" + js_text(j.get("states")) + "/" + tdump(j.get("nsteps")) + "/" + joined(jk, ","));
    }
    return line + "\nparts=" + js_text(account.get("parts")) + " workers=" + js_text(account.get("workers")) + " jobs=" + joined(jobs, ";");
}

struct LogFix {
    std::string build;
    std::chrono::system_clock::time_point at;
    double build_ms, solve_ms;
};

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

/// A split run as `run_project` makes it, the model's split switched on, at `threads` threads.
std::string run_text(const Json& model, int threads, const LogFix& fix, Results* out = nullptr) {
    auto project = std::make_shared<const Project>(with_split(model, "on"));
    RunOptions o;
    o.threads = threads;
    Results res = run_project(project, nullptr, o);
    std::vector<std::string> lines = {account_text(res.stats.get("split")), "stats=" + sorted_dump(res.stats, "split"), results_text(res)};
    // The log, its timings fixed.
    res.timing.set("build_ms", Json(fix.build_ms));
    res.timing.set("solve_ms", Json(fix.solve_ms));
    Json& account = res.stats["split"];
    if (account.get("used").as_bool()) {
        account.set("wallMs", Json(fix.solve_ms));
        account.set("gain", Json(2.25));
        Json& jobs = account["jobs"];
        for (std::size_t k = 0; k < jobs.size(); k++) {
            jobs[k].set("buildMs", Json(1.25 * static_cast<double>(k + 1)));
            jobs[k].set("solveMs", Json(100.5 * static_cast<double>(k + 1)));
        }
    }
    RunLogOptions log;
    log.build = fix.build;
    log.at = fix.at;
    lines.push_back("log\n" + run_log(res, log));
    if (out) *out = std::move(res);
    return joined(lines, "\n");
}

/// A split run on bins fixed, as `run_split` makes it, on `threads` threads.
std::string binned_text(const Json& model, const std::vector<std::vector<int>>& bins, int threads) {
    auto project = std::make_shared<const Project>(with_split(model, "on"));
    auto sys = std::make_shared<System>(project);
    PlanOptions po;
    po.mode = Json("on");
    po.workers = static_cast<double>(std::max<std::size_t>(2, bins.size()));
    SplitPlan plan = plan_split(*sys, *project, po);
    plan.bins = bins;
    SplitRunOptions so;
    so.threads = threads;
    SplitRun split = run_split(project, *sys, plan, so);
    Results res;
    res.project = project;
    res.system = sys;
    res.t = split.t;
    res.y = split.y;
    res.stats = split.stats;
    res.timing = Json::object({{"build_ms", Json(0.0)}, {"solve_ms", Json(0.0)}, {"total_ms", Json(0.0)}});
    res.kept = run_state(*sys);
    std::vector<std::string> jobs;
    for (const Json& j : split.jobs.arr())
        jobs.push_back(joined(strings(j.get("materials")), ",") + "/" + js_text(j.get("states")) + "/" + tdump(j.get("nsteps")));
    return "jobs=" + joined(jobs, ";") + "\nstats=" + sorted_dump(split.stats) + "\n" + results_text(res);
}

std::vector<std::vector<int>> bins_of(const Json& b) {
    std::vector<std::vector<int>> out;
    for (const Json& bin : b.arr()) {
        out.emplace_back();
        for (const Json& j : bin.arr()) out.back().push_back(static_cast<int>(j.as_int()));
    }
    return out;
}

// --- the formulas, on the numbers the Julia tool makes up -----------------------------------------------

Json jw(long long states, const Json& nsteps) { return Json::object({{"states", Json(states)}, {"nsteps", nsteps}}); }
Json bj(long long states, double ms) { return Json::object({{"states", Json(states)}, {"buildMs", Json(ms)}}); }

std::string formulas_text(const std::vector<SplitConstants>& cs) {
    std::vector<std::string> lines;
    const std::vector<std::pair<long long, long long>> pairs = {{25, 100}, {0, 100}, {100, 100}, {7, 0}, {3, 9}, {2880, 28800}, {1, 3}};
    for (const auto& c : cs)
        for (const auto& [s, t] : pairs)
            lines.push_back("job_cost " + std::to_string(s) + " " + std::to_string(t) + " = " + bits(job_cost(static_cast<double>(s), static_cast<double>(t), c)));
    const std::vector<std::pair<std::vector<double>, long long>> packs = {{{5, 3, 3, 2, 1}, 2},
                                                                         {{5, 3, 3, 2, 1}, 3},
                                                                         {{1, 1, 1, 1}, 3},
                                                                         {{10}, 4},
                                                                         {{}, 3},
                                                                         {{4, 4, 4, 4, 4, 4, 4}, 3},
                                                                         {{2.5, 1.25, 3.75, 0.5}, 2},
                                                                         {{5, 3, 3, 2, 1}, 0},
                                                                         {{7, 1, 1, 1, 1, 1, 1, 1}, 2},
                                                                         {{0.1 + 0.2, 0.3, 0.30000000000000004, 0.3}, 2}};
    for (std::size_t k = 0; k < packs.size(); k++) lines.push_back("pack_jobs " + std::to_string(k + 1) + " = " + bins_text(pack_jobs(packs[k].first, packs[k].second)));
    struct Whole {
        Json jobs;
        std::vector<double> solving;
        long long n;
    };
    const std::vector<Whole> wholes = {
        {Json::array({jw(50, Json(1000)), jw(50, Json(1000))}), {1000.0, 1000.0}, 100},
        {Json::array({jw(10, Json(1000)), jw(90, Json(800))}), {900.0, 300.0}, 100},
        {Json::array({jw(10, Json(100)), jw(90, Json(1000))}), {100.0, 1000.0}, 100},
        {Json::array({jw(10, Json()), jw(90, Json(800))}), {900.0, 300.0}, 100},
        {Json::array({jw(10, Json(0)), jw(90, Json(800))}), {900.0, 300.0}, 100},
        {Json::array({jw(10, Json(true)), jw(90, Json(800))}), {900.0, 300.0}, 100},
        {Json::array({jw(3, Json(17)), jw(5, Json(23)), jw(7, Json(29))}), {1.5, 2.25, 3.125}, 15},
        {Json::array({jw(2880, Json(1626)), jw(5760, Json(1702)), jw(20160, Json(1590))}), {80.3, 161.7, 655.1}, 28800}};
    for (const auto& c : cs)
        for (const auto& w : wholes) lines.push_back("whole_solve_ms " + std::to_string(w.jobs.size()) + " = " + bits(whole_solve_ms(w.jobs, w.solving, w.n, c)));
    struct Fixed {
        Json jobs;
        long long n;
        double b, k;
    };
    const std::vector<Fixed> fixeds = {{Json::array({bj(10, 550.0), bj(30, 650.0)}), 100, 500.0, 0.0},
                                       {Json::array({bj(10, 715.0), bj(30, 845.0)}), 100, 500.0, 0.3},
                                       {Json::array({bj(10, 550.0), bj(30, 650.0)}), 100, 0.0, 0.0},
                                       {Json::array({bj(100, 1.0)}), 100, 1.0, 0.0},
                                       {Json::array({bj(10, 1e9)}), 100, 1.0, 0.0},
                                       {Json::array({bj(10, 1.0)}), 100, 100.0, 0.0},
                                       {Json::array({bj(10, 3.0), bj(20, 4.0), bj(30, 5.0), bj(40, 6.0)}), 100, 9.0, 0.05},
                                       {Json::array({bj(10, 550.0)}), 0, 500.0, 0.0},
                                       {Json::array({bj(2880, 31.5), bj(5760, 44.25), bj(8640, 61.0)}), 28800, 102.5, 0.0}};
    for (const auto& f : fixeds)
        lines.push_back("build_fixed " + std::to_string(f.jobs.size()) + " " + std::to_string(f.n) + " " + bits(f.b) + " " + bits(f.k) + " = " +
                        num(build_fixed(f.jobs, f.n, f.b, f.k)));
    for (long long x : {0LL, 7LL, 999LL, 1000LL, 10080LL, 1234567LL, -1234567LL, 100000LL, 12345678901LL})
        lines.push_back("with_commas " + std::to_string(x) + " = " + with_commas(x));
    SplitPlan plan3 = no_split("on", "");
    plan3.jobs = {{{"A"}, 3}, {{"B", "C"}, 5}, {{"D"}, 2}};
    plan3.bins = {{1}, {0, 2}};
    plan3.owner = {0, 0, 0, 1, 1, 1, 1, 1, 2, 2};
    plan3.recorders = {{"min_max:Peak[D]", 2, 7}, {"running_mean:Mean[B]", 1, 3}};
    BinnedJobs got = bin_jobs(plan3);
    lines.push_back("bin_jobs = " + jobs_text(got.jobs) + " owner=" + ints(got.owner) + " recorders=" + recorders_text(got.recorders));
    return joined(lines, "\n");
}

std::string partitions_text(const Json& patterns) {
    std::vector<std::string> lines;
    for (const Json& p : patterns.arr()) {
        const int n = static_cast<int>(p.get("n").as_int());
        std::vector<I32> rows, cols;
        const Json& colptr = p.get("colptr");
        const Json& rowval = p.get("rowval");
        for (int j = 0; j < n; j++)
            for (long long q = colptr[static_cast<std::size_t>(j)].as_int(); q < colptr[static_cast<std::size_t>(j) + 1].as_int(); q++) {
                rows.push_back(static_cast<I32>(rowval[static_cast<std::size_t>(q)].as_int()));
                cols.push_back(j);
            }
        Pattern pattern(n, rows, cols);
        StatePartition s = state_partition(&pattern);
        lines.push_back("pattern " + std::to_string(n) + ": count=" + std::to_string(s.count) + " of=" + ints(s.of) + " sizes=" + ints(s.sizes) +
                        " largest=" + std::to_string(s.largest));
    }
    StatePartition none = state_partition(nullptr);
    lines.push_back("none: count=" + std::to_string(none.count) + " largest=" + std::to_string(none.largest));
    return joined(lines, "\n");
}

std::string assemble_text(const Json& c) {
    std::vector<PartRun> outcomes;
    for (const Json& o : c.get("outcomes").arr()) {
        PartRun p;
        for (const Json& x : o.get("t").arr()) p.t.push_back(x.as_double());
        for (const Json& r : o.get("y").arr()) {
            p.y.emplace_back();
            for (const Json& x : r.arr()) p.y.back().push_back(x.as_double());
        }
        p.keys = strings(o.get("keys"));
        p.stats = o.get("stats");
        p.held = o.get("held");
        outcomes.push_back(std::move(p));
    }
    std::vector<int> owner;
    for (const Json& x : c.get("owner").arr()) owner.push_back(static_cast<int>(x.as_int()));
    return said([&] {
        Assembled a = assemble_parts(strings(c.get("keys")), owner, outcomes);
        std::vector<std::string> rows;
        for (const auto& r : a.y) rows.push_back(nums(r));
        return "t=" + nums(a.t) + " y=" + joined(rows, ";") + " stats=" + sorted_dump(a.stats);
    });
}

std::string parts_text(const Json& fx, const Json& pinned_model) {
    std::vector<std::string> lines;
    for (const Json& keep : fx.get("keeps").arr())
        lines.push_back("part_model " + joined(strings(keep), ",") + " = " + json_text(part_model(fx.get("lists"), strings(keep)), 0));
    // Cut as a split run cuts it: from the model as its project writes it, every list written out.
    const Json pinned = project_to_json(Project(pinned_model.copy()));
    for (const Json& keep : fx.get("built").arr()) {
        BuiltPart part = build_part(part_model(pinned, strings(keep)));
        lines.push_back("build_part " + joined(strings(keep), ",") + " pinned=" + joined(part.pinned, ",") + " keys=" + joined(*state_keys(*part.system), "|") +
                        " nuclides=" + json_text(project_to_json(*part.project).get("nuclides"), 0));
    }
    for (const Json& rate : fx.get("rates").arr()) {
        Json bad = pinned_model.copy();
        bad["transfers"][std::size_t{0}].set("rate", rate);
        bad.set("nuclides", Json::array({Json("Cs-137"), Json("Sr-90"), Json("I-129")}));
        lines.push_back("build_part " + rate.as_string() + " = " + said([&] {
                            BuiltPart p = build_part(part_model(project_to_json(Project(bad)), {"Sr-90"}));
                            return "pinned " + joined(p.pinned, ",");
                        }));
    }
    return joined(lines, "\n");
}

/// The largest difference over every state, as a share of the largest value.
double worst(const Results& a, const Results& b) {
    double peak = 0, off = 0;
    for (std::size_t r = 0; r < a.y.size(); r++)
        for (std::size_t i = 0; i < a.y[r].size(); i++) {
            peak = std::max(peak, std::fabs(a.y[r][i]));
            off = std::max(off, std::fabs(a.y[r][i] - b.y[r][i]));
        }
    return peak == 0 ? off : off / peak;
}

bool same_bits(const Results& a, const Results& b) {
    if (a.t.size() != b.t.size() || a.y.size() != b.y.size()) return false;
    for (std::size_t r = 0; r < a.t.size(); r++)
        if (!check::same_bits(a.t[r], b.t[r]) || a.y[r].size() != b.y[r].size()) return false;
    for (std::size_t r = 0; r < a.y.size(); r++)
        for (std::size_t i = 0; i < a.y[r].size(); i++)
            if (!check::same_bits(a.y[r][i], b.y[r][i])) return false;
    return true;
}

double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

void set_env(const char* name, const std::string& value) {
#if defined(_WIN32)
    _putenv_s(name, value.c_str());
#else
    setenv(name, value.c_str(), 1);
#endif
}
void unset_env(const char* name) {
#if defined(_WIN32)
    _putenv_s(name, "");
#else
    unsetenv(name);
#endif
}

/// `count` decay chains of `length` made-up nuclides through `compartments` compartments in a line, as
/// tools/split_fixtures.jl makes them (the half-lives and rates by the C library's `pow`).
Json chains(int count, int length, int compartments, int points = 40, double rtol = 1e-6) {
    const std::string letters = "abcdefghijklmnopqrstuvwxyz";
    Json names = Json::array(), pairs = Json::array();
    Json half = Json::object();
    for (int c = 0; c < count; c++) {
        std::string element = std::string("Q") + letters[static_cast<std::size_t>(c % 26)] + (c < 26 ? "" : std::string(1, letters[static_cast<std::size_t>(c / 26)]));
        std::vector<std::string> chain;
        for (int k = 0; k < length; k++) chain.push_back(element + "-" + std::to_string(100 + k));
        for (int k = 0; k < length; k++) {
            names.push(Json(chain[static_cast<std::size_t>(k)]));
            half.set(chain[static_cast<std::size_t>(k)], Json(std::pow(10.0, 1 + ((k * 7 + c * 3) % 11) * 0.5)));
        }
        for (int k = 0; k + 1 < length; k++)
            pairs.push(Json::array({Json(chain[static_cast<std::size_t>(k)]), Json(chain[static_cast<std::size_t>(k) + 1]), Json(1.0)}));
    }
    Json params = Json::array(), comps = Json::array(), transfers = Json::array();
    for (int j = 0; j < 5; j++)
        params.push(Json::object({{"name", Json("k" + std::to_string(j))}, {"value", Json(std::pow(10.0, -1 - j * 0.7))}, {"index_lists", Json::array()}}));
    for (int i = 0; i < compartments; i++)
        comps.push(Json::object({{"name", Json("C" + std::to_string(i))}, {"initial", Json(i == 0 ? "1e6" : "0")}, {"index_lists", Json::array({Json("Radionuclides")})}}));
    for (int i = 0; i + 1 < compartments; i++)
        transfers.push(Json::object({{"name", Json("T" + std::to_string(i))},
                                     {"from", Json("C" + std::to_string(i))},
                                     {"to", Json("C" + std::to_string(i + 1))},
                                     {"rate", Json("k" + std::to_string(i % 5))},
                                     {"index_lists", Json::array({Json("Radionuclides")})}}));
    return Json::object({{"name", Json(std::to_string(count) + " chains of " + std::to_string(length) + " through " + std::to_string(compartments))},
                         {"nuclides", names},
                         {"half_lives", half},
                         {"chains", pairs},
                         {"simulation", Json::object({{"start_time", Json(0)},
                                                      {"end_time", Json(1e5)},
                                                      {"output_points", Json(points)},
                                                      {"spacing", Json("log")},
                                                      {"solver", Json("ndf")},
                                                      {"rtol", Json(rtol)},
                                                      {"abstol", Json(1e-6)},
                                                      {"time_unit", Json("year")}})},
                         {"parameters", params},
                         {"compartments", comps},
                         {"transfers", transfers}});
}

/// The made-up model of independent chains, whole against split on 2, 4 and 8 threads, warmed, and
/// what auto decides for it: KOMPARTMENT_SPLIT_TIMING=1.
void timing() {
    split_memory_forget();
    const Json model = chains(16, 12, 150, 300, 1e-8);
    auto run = [&](const std::string& mode, std::optional<int> threads) {
        auto project = std::make_shared<const Project>(with_split(model, mode));
        RunOptions o;
        o.threads = threads;
        double t0 = now_s();
        Results r = run_project(project, nullptr, o);
        return std::make_pair(std::move(r), now_s() - t0);
    };
    std::printf("\n%s: %d states, %s mode, %u threads here\n", model.get("name").as_string().c_str(), 16 * 12 * 150, parity() ? "parity" : "fast",
                std::thread::hardware_concurrency());
    // Warmed: each once before it is timed, then the best of three.
    auto best = [&](const std::string& mode, std::optional<int> threads) {
        auto first = run(mode, threads);
        double fastest = first.second;
        Results kept = std::move(first.first);
        for (int k = 0; k < 3; k++) {
            auto again = run(mode, threads);
            if (again.second < fastest) {
                fastest = again.second;
                kept = std::move(again.first);
            }
        }
        return std::make_pair(std::move(kept), fastest);
    };
    auto [whole, whole_s] = best("off", std::nullopt);
    std::printf("  whole: %.3f s (build %.0f ms, solve %.0f ms, %s steps)\n", whole_s, whole.timing.get("build_ms").as_double(),
                whole.timing.get("solve_ms").as_double(), js_text(whole.stats.get("nsteps")).c_str());
    for (int threads : {2, 4, 8}) {
        auto [parted, s] = best("on", threads);
        const Json& account = parted.stats.get("split");
        double bmin = 1e300, bmax = 0, smin = 1e300, smax = 0;
        long long nmin = 1LL << 62, nmax = 0;
        for (const Json& j : account.get("jobs").arr()) {
            bmin = std::min(bmin, j.get("buildMs").as_double());
            bmax = std::max(bmax, j.get("buildMs").as_double());
            smin = std::min(smin, j.get("solveMs").as_double());
            smax = std::max(smax, j.get("solveMs").as_double());
            nmin = std::min(nmin, static_cast<long long>(j.get("nsteps").as_int()));
            nmax = std::max(nmax, static_cast<long long>(j.get("nsteps").as_int()));
        }
        std::printf("  split on %d: %.3f s, %.2fx (solve wall %.0f ms; parts: build %.0f-%.0f ms, solve %.0f-%.0f ms, %lld-%lld steps; worst %.2g of the peak)\n",
                    threads, s, whole_s / s, account.get("wallMs").as_double(), bmin, bmax, smin, smax, nmin, nmax, worst(whole, parted));
    }
    // What auto decides: untimed, then with the whole solve it timed, then with the split it measured.
    split_memory_forget();
    for (int k = 0; k < 3; k++) {
        auto [r, s] = run("auto", std::nullopt);
        const Json& a = r.stats.get("split");
        std::printf("  auto, run %d: %s (%.3f s) -- %s\n", k + 1, a.get("used").as_bool() ? ("split on " + js_text(a.get("workers"))).c_str() : "whole", s,
                    a.get("why").as_string().c_str());
    }
}

}  // namespace

int main() {
    // What auto learns from these runs is kept in this process only, unless a check below asks.
    set_env("KOMPARTMENT_SPLIT_MEMORY", "0");
    if (const char* t = std::getenv("KOMPARTMENT_SPLIT_TIMING"); t && *t) {
        timing();
        return 0;
    }
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/split.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    const char* only_env = std::getenv("KOMPARTMENT_SPLIT_ONLY");
    const std::string only = only_env ? only_env : "";
    auto wanted = [&](const std::string& name) { return only.empty() || name.find(only) != std::string::npos; };
    set_parity(true);
    std::map<std::string, Json> examples;
    auto model_of = [&](const std::string& name) {
        if (fx.get("models").has(name)) return fx.get("models").get(name);
        if (!examples.count(name)) examples[name] = parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + name + ".json"));
        return examples[name];
    };
    std::vector<SplitConstants> constants;
    for (const Json& c : fx.get("constants").arr()) constants.push_back(constants_of(c));
    const LogFix fix{fx.get("build").as_string(), parse_iso(fx.get("at").as_string()), fx.get("build_ms").as_double(), fx.get("solve_ms").as_double()};

    std::string all;
    int n = 0, models = 0, runs = 0, threaded = 0;
    auto record = [&](const std::string& head, const Json& row, const std::string& text) {
        all += (n++ ? "\n\n" : "") + std::string("## ") + head + "\n" + text;
        CHECK_MSG(kept(text) == row.get("out").as_string(), head + "\n   here:  " + kept(text).substr(0, 300) + "\n   there: " + row.get("out").as_string().substr(0, 300));
    };
    auto guarded = [](const std::function<std::string()>& f) {
        try {
            return f();
        } catch (const std::exception& e) {
            return std::string("raised here: ") + e.what();
        }
    };

    // The partition, the names, the materials, the jobs, every plan, the layers.
    for (const Json& c : fx.get("cases").arr()) {
        const std::string name = c.get("name").as_string();
        if (!wanted(name)) continue;
        record("model " + name, c, guarded([&] { return model_text(model_of(name), fx.get("options"), constants); }));
        models++;
    }

    // Split runs, as `run_project` makes them and on bins fixed by hand; each again on other
    // numbers of threads for the same bins, the same bits.
    for (const Json& r : fx.get("runs").arr()) {
        const std::string name = r.get("name").as_string();
        if (!wanted(name)) continue;
        const int threads = static_cast<int>(r.get("threads").as_int());
        const Json model = model_of(name);
        std::string head = "run " + name + " on " + std::to_string(threads);
        std::vector<std::vector<int>> bins;
        std::string text;
        if (r.has("bins")) {
            head += " bins " + json_text(r.get("bins"), 0);
            bins = bins_of(r.get("bins"));
            text = guarded([&] { return binned_text(model, bins, threads); });
        } else {
            Results res;
            text = guarded([&] { return run_text(model, threads, fix, &res); });
            const Json& account = res.stats.get("split");
            if (account.get("used") == Json(true)) {
                // The bins this run was given, from its plan.
                auto project = std::make_shared<const Project>(with_split(model, "on"));
                System sys(project);
                PlanOptions po;
                po.mode = Json("on");
                po.workers = threads;
                bins = plan_split(sys, *project, po).bins;
                // The same bins as `run_split` runs them: the run's own states and series.
                const std::string direct = guarded([&] { return binned_text(model, bins, threads); });
                const std::size_t from = text.find("\nstats=") + 1;
                const std::string from_run = text.substr(from, text.find("\nlog\n") - from);
                CHECK_MSG(direct.find(from_run) != std::string::npos, head + ": run_split gives what the run gave");
            }
        }
        record(head, r, text);
        runs++;
        if (bins.empty()) continue;
        const std::string once = guarded([&] { return binned_text(model, bins, 1); });
        for (int t : {2, 3, 8}) {
            CHECK_MSG(guarded([&] { return binned_text(model, bins, t); }) == once, head + ": on " + std::to_string(t) + " threads the bins give other bits");
            threaded++;
        }
    }

    if (wanted("formulas")) record("formulas", fx.get("formulas"), guarded([&] { return formulas_text(constants); }));
    if (wanted("partitions")) record("partitions", fx.get("partitions"), guarded([&] { return partitions_text(fx.get("partitions").get("patterns")); }));
    for (const Json& c : fx.get("assemble").arr())
        if (wanted("assemble")) record("assemble " + c.get("name").as_string(), c, guarded([&] { return assemble_text(c); }));
    if (wanted("parts")) record("parts", fx.get("parts"), guarded([&] { return parts_text(fx.get("parts"), fx.get("models").get("pinned")); }));
    if (dumps && *dumps) std::ofstream(std::string(dumps) + "/split.cpp.txt", std::ios::binary) << all;

    const Json biosphere = model_of("biosphere");
    auto project_of = [](const Json& model, const std::string& mode) { return std::make_shared<const Project>(with_split(model, mode)); };

    // The account and the log.
    if (wanted("account")) {
        RunOptions o;
        o.threads = 3;
        Results parted = run_project(project_of(biosphere, "on"), nullptr, o);
        const Json& account = parted.stats.get("split");
        std::vector<std::string> keys;
        for (const auto& [k, _] : account.obj()) keys.push_back(k);
        CHECK_EQ(joined(keys, ","), "used,mode,why,predicted,parts,workers,jobs,wallMs,gain");
        CHECK_EQ(account.get("why").as_string(), "asked for: 4 parts, the largest 25% of the states, on 3 cores");
        CHECK(account.get("predicted").is_null());
        CHECK(account.get("wallMs").as_double() > 0 && account.get("gain").as_double() > 0);
        CHECK(parted.timing.get("solve_ms").as_double() == account.get("wallMs").as_double());
        const std::string log = run_log(parted);
        CHECK_MSG(log.find("split: 4 independent parts on 3 cores (on) \xe2\x80\x94 asked for: 4 parts") != std::string::npos, "the log's split line");
        CHECK_MSG(log.find("    I-129, Se-79: 8 states, ") != std::string::npos, "the log's line per thread");
        CHECK_MSG(log.find(" a whole solve, by this machine's estimate") != std::string::npos, "the log's gain");
        // Off: the account says so, and nothing else.
        Results whole = run_project(project_of(biosphere, "off"), nullptr, o);
        CHECK_EQ(json_text(whole.stats.get("split"), 0), "{\"used\":false,\"mode\":\"off\",\"why\":\"switched off\",\"predicted\":null}");
        CHECK_MSG(run_log(whole).find("  not split (off): switched off") != std::string::npos, "the log's line for a run not split");
        CHECK(worst(whole, parted) < 2e-4);
    }

    // Progress, and a stop.
    if (wanted("progress")) {
        std::vector<std::pair<double, double>> heard;
        RunOptions o;
        o.threads = 4;
        o.on_progress = [&](double f, double at) {
            heard.emplace_back(f, at);
            return true;
        };
        Results r = run_project(project_of(biosphere, "on"), nullptr, o);
        CHECK(r.stats.get("split").get("used").as_bool());
        CHECK(!heard.empty());
        CHECK(!heard.empty() && heard.back() == std::make_pair(1.0, biosphere.get("simulation").get("end_time").as_double()));
        bool rising = true;
        for (std::size_t k = 0; k + 1 < heard.size(); k++) rising = rising && heard[k].first <= heard[k + 1].first && heard[k].second <= heard[k + 1].second;
        CHECK_MSG(rising, "progress only rises");
        // Stopped: the parts stop and the run says so.
        Json longer = with_split(biosphere, "on");
        longer["simulation"].set("end_time", Json(biosphere.get("simulation").get("end_time").as_double() * 1000));
        RunOptions stop;
        stop.threads = 4;
        stop.on_progress = [](double, double) { return false; };
        std::string kind;
        try {
            run_project(std::make_shared<const Project>(longer), nullptr, stop);
        } catch (const SolverError& e) {
            kind = e.kind;
        }
        CHECK_EQ(kind, std::string("aborted"));
    }

    // A split that does not add up is solved whole: here the first word from the split fails it,
    // as parts that came back on different times would. The whole run is a whole run to the bit.
    if (wanted("fallback")) {
        bool failed = false;
        RunOptions o;
        o.threads = 4;
        o.on_progress = [&](double, double) -> bool {
            if (failed) return true;
            failed = true;
            throw std::runtime_error("the parts came back on different output times");
        };
        Results r = run_project(project_of(biosphere, "on"), nullptr, o);
        CHECK(!r.stats.get("split").get("used").as_bool());
        CHECK_EQ(r.stats.get("split").get("why").as_string(), std::string("tried, and solved whole instead: the parts came back on different output times"));
        Results whole = run_project(project_of(biosphere, "off"), nullptr, RunOptions{});
        CHECK_MSG(same_bits(r, whole), "the run it falls back on is the whole run's, to the bit");
        // The model whose part cannot start: its fallback is the whole run too.
        const Json fails = model_of("a part that fails");
        RunOptions two;
        two.threads = 2;
        Results f = run_project(project_of(fails, "on"), nullptr, two);
        Results w = run_project(project_of(fails, "off"), nullptr, two);
        CHECK(f.stats.get("split").get("why").as_string().rfind("tried, and solved whole instead: A starts at Infinity", 0) == 0);
        CHECK_MSG(same_bits(f, w), "a part that fails: the whole run, to the bit");
    }

    // Not split side by side, on one thread, or with the system given.
    if (wanted("refused")) {
        RunOptions side;
        side.threads = 4;
        side.nest = false;
        Results r = run_project(project_of(biosphere, "on"), nullptr, side);
        CHECK_EQ(r.stats.get("split").get("why").as_string(), std::string("this run is itself one of several side by side, which do not start more"));
        auto project = project_of(biosphere, "on");
        CHECK(!run_project(project, std::make_shared<System>(project)).stats.has("split"));
        RunOptions one;
        one.threads = 1;
        CHECK_EQ(run_project(project_of(biosphere, "on"), nullptr, one).stats.get("split").get("why").as_string(), std::string("there is one thread to run on"));
        // With no threads asked for, as many as the machine has (and the plan says so).
        Results every = run_project(project_of(model_of("chains(6,5,4)"), "on"), nullptr, RunOptions{});
        const long long cores = std::max(1u, std::thread::hardware_concurrency());
        if (cores >= 2) CHECK_EQ(every.stats.get("split").get("workers").as_int(), std::min(6LL, cores));
    }

    // Auto is the default, and learns: a model it has not timed is too small, and once timed, too quick.
    if (wanted("learns")) {
        split_memory_forget();
        auto project = std::make_shared<const Project>(biosphere);
        RunOptions o;
        o.threads = 4;
        Results first = run_project(project, nullptr, o);
        CHECK_EQ(first.stats.get("split").get("mode").as_string(), std::string("auto"));
        CHECK_EQ(first.stats.get("split").get("why").as_string(), std::string("16 states, too few to be worth dividing before a run has been timed"));
        Results again = run_project(project, nullptr, o);
        CHECK_MSG(std::regex_match(again.stats.get("split").get("why").as_string(), std::regex(R"(^a whole solve takes \d+ ms, too short to be worth dividing$)")),
                  "timed: " + again.stats.get("split").get("why").as_string());
        split_memory_forget();
    }

    // What auto learns is kept for the next process: in KOMPARTMENT_CACHE, by this build's stamp.
    if (wanted("memory")) {
        const fs::path dir = fs::temp_directory_path() / ("kompartment-split-test-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        fs::create_directories(dir);
        set_env("KOMPARTMENT_CACHE", dir.string());
        unset_env("KOMPARTMENT_SPLIT_MEMORY");
        split_memory_forget();
        CHECK_EQ(split_memory_path().value_or(""), (dir / "split-memory-cpp.json").string());
        RunOptions o;
        o.threads = 4;
        run_project(std::make_shared<const Project>(biosphere), nullptr, o);
        const fs::path path = dir / "split-memory-cpp.json";
        CHECK(fs::exists(path));
        Json kept_ = fs::exists(path) ? parse_json(check::read_file(path.string())) : Json::object();
        CHECK_EQ(kept_.size(), std::size_t{1});
        if (kept_.size() == 1) {
            const auto& [key, entry] = kept_.obj().items().front();
            CHECK(key.find("|cpp|" + split_engine_stamp()) != std::string::npos);
            CHECK(entry.get("solve_ms").as_double() > 0);
            CHECK(entry.get("when").as_double() > 1.7e9);
        }
        // A process that starts afresh reads it before it plans.
        split_memory_forget();
        Results again = run_project(std::make_shared<const Project>(biosphere), nullptr, o);
        CHECK_MSG(std::regex_match(again.stats.get("split").get("why").as_string(), std::regex(R"(^a whole solve takes \d+ ms, too short.*)")),
                  "read from the file: " + again.stats.get("split").get("why").as_string());
        // A measurement within a quarter of the one kept is not written again; one further off is.
        const std::string text = check::read_file(path.string());
        const std::string key = split_memory_key("a layout");
        split_remember(key, Json::object({{"solve_ms", Json(100.0)}, {"gain", Json()}, {"build_fixed", Json()}}));
        const std::string with_one = check::read_file(path.string());
        CHECK(with_one != text && parse_json(with_one).size() == 2);
        split_remember(key, Json::object({{"solve_ms", Json(110.0)}, {"gain", Json()}, {"build_fixed", Json()}}));
        CHECK_MSG(check::read_file(path.string()) == with_one, "a measurement close to the one kept is not written");
        CHECK_EQ(split_recall(key).get("solve_ms").as_double(), 110.0);
        split_remember(key, Json::object({{"solve_ms", Json(200.0)}, {"gain", Json()}, {"build_fixed", Json()}}));
        CHECK_EQ(parse_json(check::read_file(path.string())).get(key).get("solve_ms").as_double(), 200.0);
        // Past a thousand entries the oldest are dropped.
        {
            Json many = Json::object();
            for (int k = 0; k < 1005; k++) many.set("old " + std::to_string(k), Json::object({{"solve_ms", Json(1.0)}, {"when", Json(1000.0 + k)}}));
            std::ofstream(path, std::ios::binary) << json_text(many, 0);
        }
        split_memory_forget();
        split_remember(key, Json::object({{"solve_ms", Json(5.0)}}));
        const Json trimmed = parse_json(check::read_file(path.string()));
        CHECK_EQ(trimmed.size(), SPLIT_MEMORY_KEEP);
        CHECK(trimmed.has(key) && !trimmed.has("old 0") && !trimmed.has("old 5") && trimmed.has("old 6") && trimmed.has("old 1004"));
        CHECK(trimmed.obj().items().front().first == key);
        // Off: nowhere to keep it.
        set_env("KOMPARTMENT_SPLIT_MEMORY", " 0 ");
        CHECK(!split_memory_path());
        set_env("KOMPARTMENT_SPLIT_MEMORY", "0");
        unset_env("KOMPARTMENT_CACHE");
        split_memory_forget();
        std::error_code ec;
        fs::remove_all(dir, ec);
        // Close, as the Julia package measures it.
        CHECK(split_close(Json(), Json()));
        CHECK(!split_close(Json(), Json(1.0)));
        CHECK(split_close(Json(100.0), Json(125.0)) && !split_close(Json(100.0), Json(134.0)) && split_close(Json(true), Json(1)));
        CHECK(said([] { return std::to_string(split_close(Json("x"), Json(1.0))); }) == "error:MethodError");
    }

    // This engine's constants and its formulas.
    if (wanted("constants")) {
        const SplitConstants& C = SPLIT_CONSTANTS;
        CHECK(job_cost(25, 100) == C.shared_work + (1 - C.shared_work) * 0.25);
        CHECK(C.auto_gain >= 1 && C.auto_gain_untimed >= C.auto_gain && C.untimed_bins >= 2 && C.build_fixed && *C.build_fixed >= 0);
        auto bio = std::make_shared<const Project>(biosphere);
        System sys(bio);
        PlanOptions po;
        po.workers = 8;
        po.known = Json::object({{"solve_ms", Json(40000.0)}});
        po.build_ms = 500.0;
        SplitPlan p = plan_split(sys, *bio, po);
        const double slower = 1 + C.build_contention * (4 - 1);
        const double bin = 500.0 * (*C.build_fixed + (1 - *C.build_fixed) * 4.0 / 16.0) * slower + 40000.0 * job_cost(4, 16);
        CHECK_MSG(p.use && p.bins.size() == 4 && p.predicted && std::fabs(*p.predicted - 40000.0 / (bin + C.start_ms)) <= 1e-12 * *p.predicted,
                  "biosphere's plan: " + p.why);
        po.known = Json();
        po.build_ms = 0;
        CHECK_EQ(plan_split(sys, *bio, po).why, std::string("16 states, too few to be worth dividing before a run has been timed"));
    }

    set_parity(false);
    std::printf("%d cases (%d models, %d runs, %d run again on other numbers of threads)\n", n, models, runs, threaded);
    return check::summary("test_split");
}
