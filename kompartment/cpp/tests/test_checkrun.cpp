// Check the run against the Julia package's, with parity on (tools/checkrun_fixtures.jl
// writes tests/fixtures/checkrun.json): for bundled examples and made-up models, what each
// state is called and the report of a check of a run of it -- the careful run solved and set
// against the run -- as the JSON text the service writes, to the character; and runs made
// up to reach every rule of the comparison (a state not a number in one run, infinite in
// one, in both, shares that tie, a careful run at other times), the same.

#include <cstdint>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#include "check.hpp"
#include "engine/checkrun.hpp"
#include "engine/runner.hpp"
#include "engine/system.hpp"
#include "util/json.hpp"
#include "util/parity.hpp"

using namespace kompartment;

namespace {

double unbits(const std::string& s) {
    if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
    std::uint64_t u = std::strtoull(s.c_str(), nullptr, 16);
    double x;
    std::memcpy(&x, &u, 8);
    return x;
}

std::vector<double> row_of(const Json& v) {
    std::vector<double> out;
    for (const Json& x : v.arr()) out.push_back(unbits(x.as_string()));
    return out;
}

std::vector<Vec> rows_of(const Json& v) {
    std::vector<Vec> out;
    for (const Json& r : v.arr()) out.push_back(row_of(r));
    return out;
}

}  // namespace

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/checkrun.json"));
    set_parity(true);
    for (const Json& c : fx.get("cases").arr()) {
        const std::string& name = c.get("name").as_string();
        const Json raw = c.get("model").copy();
        auto project = std::make_shared<const Project>(raw.copy());
        Results held = run_project(project);
        const std::vector<std::string> labels = state_labels(*held.system);
        const Json& want = c.get("labels");
        bool same = labels.size() == want.size();
        for (std::size_t i = 0; same && i < labels.size(); i++) same = labels[i] == want[i].as_string();
        CHECK_MSG(same, name + ": what the states are called");
        Json report = check_run(held, [](std::shared_ptr<const Project> p) { return run_project(p); }, &raw);
        report["careful"].erase("ms");
        const std::string text = json_text(report, 0);
        CHECK_MSG(text == c.get("report").as_string(), name + ": the report\n   here:  " + text + "\n   there: " + c.get("report").as_string());
    }

    // Runs made up to reach every rule of the comparison.
    auto project = std::make_shared<const Project>(fx.get("compare_model").copy());
    auto system = std::make_shared<System>(project);
    for (const Json& c : fx.get("compares").arr()) {
        const Json r = compare_runs(*project, *system, row_of(c.get("held_t")), rows_of(c.get("held_y")), row_of(c.get("careful_t")),
                                    rows_of(c.get("careful_y")));
        const std::string text = json_text(r, 0);
        CHECK_MSG(text == c.get("report").as_string(), "made-up runs\n   here:  " + text + "\n   there: " + c.get("report").as_string());
    }

    // What the careful run's model is made of.
    Json m = parse_json(R"({"simulation": {"rtol": 1e-11, "abstol": 1e-6, "max_steps": "700"},
        "compartments": [{"abstol": "2e-5", "entries": [{"abstol": 1e-3}, {"abstol": ""}, null]}, {"abstol": 0}]})");
    const Tightened t = tighten_tolerances(m);
    CHECK(t.floor && t.rtol == CHECK_RTOL_FLOOR && t.abstol == 1e-6 / CHECK_CAREFUL);
    CHECK(m.get("simulation").get("max_steps") == Json(7000.0));
    CHECK(m.get("compartments")[0].get("abstol") == Json(2e-5 / CHECK_CAREFUL));
    CHECK(m.get("compartments")[0].get("entries")[0].get("abstol") == Json(1e-3 / CHECK_CAREFUL));
    CHECK(m.get("compartments")[0].get("entries")[1].get("abstol") == Json(""));
    CHECK(m.get("compartments")[1].get("abstol") == Json(0));
    return check::summary("test_checkrun");
}
