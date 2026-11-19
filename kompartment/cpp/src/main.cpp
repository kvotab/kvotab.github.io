// kompartment-cpp: opens a Kompartment model, builds it, runs it and writes what it produced.
//
//   kompartment-cpp model.json                 run it and say how it went
//   kompartment-cpp model.json --csv out.csv   ... and write every series as the application's table
//   kompartment-cpp model.json --h5 out.h5     ... and as the application's HDF5 result file
//   kompartment-cpp model.json --repeat 3      run it several times over (timing)
//   kompartment-cpp model.json --split on      solve it in its independent parts (auto, on, off)
//   kompartment-cpp model.json --threads 4     ... on at most four threads (the machine's cores)
//   kompartment-cpp model.json --probabilistic 1000 [--seed 7] [--h5 out.h5 [--want all|mean|<k>]]
//                                              run it over its distributions; write every realisation,
//                                              their mean or the k-th
//   kompartment-cpp model.json --scenarios [--h5 out.h5]
//                                              run every scenario; write them side by side
//   kompartment-cpp --stamp "2026-10-10 09:05:07" ...   the file's created_time (now by default)
//   kompartment-cpp --parity ...               the other engines' arithmetic to the bit
//   kompartment-cpp --serve                    the engine behind the application's local server (serve.py)

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

#include <iostream>

#include "engine/probabilistic.hpp"
#include "engine/runner.hpp"
#include "engine/scenarios.hpp"
#include "io/resultfile.hpp"
#include "service.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {
double now_s() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}
std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot read " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}
/// A number as given on the command line: whole where it is, else the double it reads as;
/// text that is no number as itself (read later as JavaScript's `Number()` reads it).
Json number_or_text(const std::string& s) {
    char* end = nullptr;
    const long long i = std::strtoll(s.c_str(), &end, 10);
    if (!s.empty() && end == s.c_str() + s.size()) return Json(i);
    const double d = std::strtod(s.c_str(), &end);
    if (!s.empty() && end == s.c_str() + s.size()) return Json(d);
    return Json(s);
}
const char* USAGE =
    "usage: kompartment-cpp model.json [--csv out.csv] [--h5 out.h5] [--repeat n] [--split auto|on|off] [--threads n] [--parity]\n"
    "       kompartment-cpp model.json --probabilistic n [--seed s] [--h5 out.h5 [--want all|mean|k]] [--threads n] [--parity]\n"
    "       kompartment-cpp model.json --scenarios [--h5 out.h5] [--threads n] [--parity]\n"
    "       kompartment-cpp --serve | --version\n"
    "\n"
    "  --csv out.csv        every series of the run, as the application's results table\n"
    "  --h5 out.h5          the HDF5 result file the application's Export to HDF5 writes (every series);\n"
    "                       of a probabilistic run, its realisations (--want); of --scenarios, every\n"
    "                       scenario's run side by side\n"
    "  --stamp 'YYYY-MM-DD hh:mm:ss'   the HDF5 file's created_time, as local time (or seconds since\n"
    "                       the epoch); now by default -- the same run and stamp give the same bytes\n"
    "  --repeat n           run it n times over (timing)\n"
    "  --split auto|on|off  the model's Split into parts, for the run\n"
    "  --threads n          the most threads a split, a probabilistic run or scenarios use (every core)\n"
    "  --probabilistic n    run n realisations over the model's distributions (Latin hypercube), the\n"
    "                       series it reports kept, and say how it went\n"
    "  --seed s             the probabilistic run's seed (1)\n"
    "  --want all|mean|k    what the file of a probabilistic run holds: every realisation as float32\n"
    "                       (all, the default), their mean, or realisation k (from 1)\n"
    "  --scenarios          run the model once for each scenario of its scenario list\n"
    "  --parity             the other engines' numbers to the bit (KOMPARTMENT_PARITY=1)\n"
    "  --serve              the engine behind the application's local server (serve.py)\n";
}  // namespace

int main(int argc, char** argv) {
    std::string model_path, csv_path, h5_path, split, stamp_text_given;
    int repeat = 1, threads = 0;
    long long realisations = 0;
    bool probabilistic = false, scenarios = false;
    Json seed(1), want("all");
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if (a == "--serve") {
            // What the engine prints goes to standard error: standard output carries the protocol alone.
            serve_stdio(std::cin, std::cout);
            return 0;
        }
        if (a == "--version") {
            std::printf("kompartment-cpp %s\n", ENGINE_VERSION);
            return 0;
        }
        if (a == "--parity") set_parity(true);
        else if (a == "--csv" && i + 1 < argc) csv_path = argv[++i];
        else if (a == "--h5" && i + 1 < argc) h5_path = argv[++i];
        else if (a == "--stamp" && i + 1 < argc) stamp_text_given = argv[++i];
        else if (a == "--repeat" && i + 1 < argc) repeat = std::atoi(argv[++i]);
        else if (a == "--split" && i + 1 < argc) split = argv[++i];
        else if (a == "--threads" && i + 1 < argc) threads = std::atoi(argv[++i]);
        else if (a == "--probabilistic" && i + 1 < argc) {
            probabilistic = true;
            realisations = std::atoll(argv[++i]);
        } else if (a == "--seed" && i + 1 < argc) seed = number_or_text(argv[++i]);
        else if (a == "--want" && i + 1 < argc) {
            const std::string w = argv[++i];
            want = (w == "all" || w == "mean") ? Json(w) : number_or_text(w);
        } else if (a == "--scenarios") scenarios = true;
        else if (a == "--help" || a == "-h") {
            std::printf("%s", USAGE);
            return 0;
        } else model_path = a;
    }
    if (model_path.empty() || (probabilistic && scenarios) || ((probabilistic || scenarios) && !csv_path.empty())) {
        if (!csv_path.empty() && (probabilistic || scenarios))
            std::fprintf(stderr, "--csv writes one run's table: a probabilistic run or scenarios are written with --h5\n");
        std::fprintf(stderr, "%s", USAGE);
        return 2;
    }
    Stamp stamp;
    if (!stamp_text_given.empty()) {
        std::optional<Stamp> s = parse_stamp(stamp_text_given);
        if (!s) {
            std::fprintf(stderr, "--stamp '%s': a time is YYYY-MM-DD hh:mm:ss, or seconds since the epoch\n", stamp_text_given.c_str());
            return 2;
        }
        stamp = *s;
    }
    const std::string shown = model_path.substr(model_path.find_last_of('/') + 1);
    try {
        double t0 = now_s();
        Json raw = parse_json(read_file(model_path));
        if (!split.empty()) {
            if (!raw.get("simulation").is_object()) raw.set("simulation", Json::object());
            raw["simulation"].set("split", Json(split));
        }
        double t1 = now_s();
        if (probabilistic) {
            ProbabilisticOptions o;
            o.iterations = static_cast<double>(realisations);
            o.seed = seed;
            o.threads = threads;
            for (int r = 0; r < repeat; r++) {
                auto project = std::make_shared<const Project>(raw);
                const double r0 = now_s();
                ProbabilisticResults prob = run_probabilistic(project, o);
                std::printf("%s: %lld realisations of %zu series at %zu times, %zu inputs varied, %s failed, %s on %s threads, read %.3f s, run %.3f s\n",
                            shown.c_str(), prob.held(), prob.outputs.size(), prob.t.size(), prob.inputs.size(), js_text(prob.stats.get("failed")).c_str(),
                            prob.precision.c_str(), js_text(prob.stats.get("threads")).c_str(), t1 - t0, now_s() - r0);
                for (const Json& line : prob.stats.get("trouble").arr()) std::printf("  %s\n", js_text(line).c_str());
                if (r + 1 == repeat && !h5_path.empty()) {
                    const double w0 = now_s();
                    ProbabilisticSaveOptions so;
                    so.want = want;
                    so.now = stamp;
                    save_probabilistic(prob, h5_path, so);
                    std::printf("wrote %s in %.3f s\n", h5_path.c_str(), now_s() - w0);
                }
            }
            return 0;
        }
        if (scenarios) {
            for (int r = 0; r < repeat; r++) {
                const double r0 = now_s();
                auto runs = run_scenarios(raw, std::nullopt, threads > 0 ? threads : 1);
                for (auto& [name, res] : runs) std::printf("%s [%s]: %s\n", shown.c_str(), name.c_str(), res.summary().c_str());
                std::printf("%s: %zu scenarios, read %.3f s, run %.3f s\n", shown.c_str(), runs.size(), t1 - t0, now_s() - r0);
                if (r + 1 == repeat && !h5_path.empty()) {
                    const double w0 = now_s();
                    ScenariosTreeOptions so;
                    so.now = stamp;
                    save_scenarios(runs, h5_path, so);
                    std::printf("wrote %s in %.3f s\n", h5_path.c_str(), now_s() - w0);
                }
            }
            return 0;
        }
        RunOptions options;
        if (threads > 0) options.threads = threads;
        for (int r = 0; r < repeat; r++) {
            auto project = std::make_shared<const Project>(raw);
            // Built here and solved -- in its independent parts on several threads, where the
            // model's `split` setting says so and the plan agrees.
            Results res = run_project(project, nullptr, options);
            auto ms = [&](const char* key) { return res.timing.get(key).is_number() ? res.timing.get(key).as_double() / 1000 : 0.0; };
            std::printf("%s: %d states, read %.3f s, build %.3f s, solve %.3f s  %s\n", shown.c_str(), res.system->nstate, t1 - t0, ms("build_ms"),
                        ms("solve_ms"), res.summary().c_str());
            // What the split did, or why it was not used where it was asked for.
            const Json& account = res.stats.get("split");
            if (account.get("used") == Json(true))
                std::printf("  split: %s parts on %s threads -- %s\n", js_text(account.get("parts")).c_str(), js_text(account.get("workers")).c_str(),
                            js_text(account.get("why")).c_str());
            else if (account.get("mode") == "on")
                std::printf("  not split: %s\n", js_text(account.get("why")).c_str());
            if (r + 1 == repeat && !csv_path.empty()) {
                double w0 = now_s();
                std::ofstream(csv_path) << res.to_csv();
                std::printf("wrote %s in %.3f s\n", csv_path.c_str(), now_s() - w0);
            }
            if (r + 1 == repeat && !h5_path.empty()) {
                const double w0 = now_s();
                SaveOptions so;
                so.now = stamp;
                if (is_hdf5_path(h5_path)) {
                    save_results(res, h5_path, so);
                } else {
                    // Whatever the name ends in, --h5 writes HDF5.
                    std::ofstream out(h5_path, std::ios::binary);
                    const std::string bytes = write_results_hdf5(res, so);
                    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
                    if (!out) throw std::runtime_error("Cannot write " + h5_path);
                }
                std::printf("wrote %s in %.3f s\n", h5_path.c_str(), now_s() - w0);
            }
        }
    } catch (const SolverError& e) {
        std::fprintf(stderr, "%s%s%s\n", e.message.c_str(), e.hint ? " " : "", e.hint ? e.hint->c_str() : "");
        return 1;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
    return 0;
}
