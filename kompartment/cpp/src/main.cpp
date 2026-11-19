// kompartment-cpp: opens a Kompartment model, builds it, runs it and writes what it produced.
//
//   kompartment-cpp model.json                 run it and say how it went
//   kompartment-cpp model.json --csv out.csv   ... and write every series as the application's table
//   kompartment-cpp model.json --repeat 3      run it several times over (timing)
//   kompartment-cpp model.json --split on      solve it in its independent parts (auto, on, off)
//   kompartment-cpp model.json --threads 4     ... on at most four threads (the machine's cores)
//   kompartment-cpp --parity ...               the other engines' arithmetic to the bit
//   kompartment-cpp --serve                    the engine behind the application's local server (serve.py)

#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <string>

#include <iostream>

#include "engine/runner.hpp"
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
const char* USAGE = "usage: kompartment-cpp model.json [--csv out.csv] [--repeat n] [--split auto|on|off] [--threads n] [--parity]\n";
}  // namespace

int main(int argc, char** argv) {
    std::string model_path, csv_path, split;
    int repeat = 1, threads = 0;
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
        else if (a == "--repeat" && i + 1 < argc) repeat = std::atoi(argv[++i]);
        else if (a == "--split" && i + 1 < argc) split = argv[++i];
        else if (a == "--threads" && i + 1 < argc) threads = std::atoi(argv[++i]);
        else if (a == "--help" || a == "-h") {
            std::printf("%s", USAGE);
            return 0;
        } else model_path = a;
    }
    if (model_path.empty()) {
        std::fprintf(stderr, "%s", USAGE);
        return 2;
    }
    try {
        double t0 = now_s();
        Json raw = parse_json(read_file(model_path));
        if (!split.empty()) {
            if (!raw.get("simulation").is_object()) raw.set("simulation", Json::object());
            raw["simulation"].set("split", Json(split));
        }
        double t1 = now_s();
        RunOptions options;
        if (threads > 0) options.threads = threads;
        for (int r = 0; r < repeat; r++) {
            auto project = std::make_shared<const Project>(raw);
            // Built here and solved -- in its independent parts on several threads, where the
            // model's `split` setting says so and the plan agrees.
            Results res = run_project(project, nullptr, options);
            auto ms = [&](const char* key) { return res.timing.get(key).is_number() ? res.timing.get(key).as_double() / 1000 : 0.0; };
            std::printf("%s: %d states, read %.3f s, build %.3f s, solve %.3f s  %s\n", model_path.substr(model_path.find_last_of('/') + 1).c_str(),
                        res.system->nstate, t1 - t0, ms("build_ms"), ms("solve_ms"), res.summary().c_str());
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
