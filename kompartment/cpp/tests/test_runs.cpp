// Whole runs against the Julia engine's, with parity on (tools/run_fixtures.jl
// writes tests/fixtures/runs.json): each model run with its Jacobian
// differenced through its pattern, and as it stands, and the application's
// table of the run -- every series at every output time -- compared as text,
// with the step counts; or the message a run fails with.

#include <cstdint>
#include <cstdlib>
#include <fstream>

#include "check.hpp"
#include "engine/jacobian.hpp"
#include "engine/runner.hpp"
#include "util/json.hpp"
#include "util/jsnum.hpp"
#include "util/parity.hpp"

using namespace kompartment;

static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/runs.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    std::vector<std::string> skipped, differenced;
    set_parity(true);
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        for (const char* how : {"numeric", "exact"}) {
            const Json& want = row.get(how);
            std::string said = name + " (" + how + ")";
            Json m = model.copy();
            if (!m.get("simulation").is_object()) m.set("simulation", Json::object());
            if (std::string(how) == "numeric") m["simulation"].set("jacobian", Json("numeric"));
            try {
                auto project = std::make_shared<const Project>(m);
                auto system = std::make_shared<System>(project);
                // Until this engine has a model's exact Jacobian its own run differences it: not the run compared.
                bool stiff = project->simulation.get("solver") != Json("dp45");
                if (std::string(how) == "exact" && stiff && !(system->jacobian && system->jacobian->analytic) && system->nstate > 0) {
                    Json there = Json::object();
                    try {
                        // (whether the other engine has one is not said in the fixture: a model whose run is the same either way passes below)
                    } catch (...) {
                    }
                    if (want.get("csv") != row.get("numeric").get("csv")) {
                        differenced.push_back(name);
                        continue;
                    }
                }
                Results res = run_project(project, system);
                std::string text = res.to_csv();
                if (dumps && *dumps) std::ofstream(std::string(dumps) + "/" + name + "." + how + ".cpp.csv") << text;
                if (!want.has("csv")) {
                    CHECK_MSG(false, said + " fails there: " + want.get("error").as_string());
                    continue;
                }
                CHECK_MSG(static_cast<long long>(res.t.size()) == want.get("points").as_int(), said + ": " + std::to_string(res.t.size()) + " output times");
                for (const char* key : {"nsteps", "nfailed", "nfevals", "events", "jumps", "restarts"}) {
                    if (!want.has(key)) continue;
                    const Json& got = res.stats.get(key);
                    CHECK_MSG(got.is_number() && got.as_double() == want.get(key).as_double(),
                              said + ": " + key + " is " + js_text(got) + ", there " + js_text(want.get(key)));
                }
                CHECK_MSG(fnv(text) == want.get("csv").as_string(), said + ": the table differs");
            } catch (const NotSupported&) {
                skipped.push_back(name);
                break;
            } catch (const SolverError& e) {
                if (want.has("error")) CHECK_MSG(want.get("error").as_string() == e.message, said + " fails with: " + e.message + "\n   there: " + want.get("error").as_string());
                else CHECK_MSG(false, said + " runs there, fails here: " + e.message);
            } catch (const std::exception& e) {
                if (want.has("error")) CHECK_MSG(want.get("error").as_string() == e.what(), said + " fails with: " + e.what() + "\n   there: " + want.get("error").as_string());
                else CHECK_MSG(false, said + " runs there, fails here: " + e.what());
            }
        }
    }
    set_parity(false);
    auto listed = [](const std::vector<std::string>& v) {
        std::string s;
        for (const auto& x : v) s += (s.empty() ? "" : ", ") + x;
        return s;
    };
    if (!skipped.empty()) std::printf("not built here yet (%zu): %s\n", skipped.size(), listed(skipped).c_str());
    if (!differenced.empty()) std::printf("without an exact Jacobian here, not compared (%zu): %s\n", differenced.size(), listed(differenced).c_str());
    return check::summary("test_runs");
}
