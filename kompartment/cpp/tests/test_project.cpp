// The project a run is built from, against the Julia engine's
// (tools/project_fixtures.jl writes tests/fixtures/project.json): every
// bundled example and models made to reach the checks, each as the project it
// is read into -- by a hash of its text -- or the message it is refused with.

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>

#include "check.hpp"
#include "engine/project.hpp"
#include "util/json.hpp"

using namespace kompartment;

static std::string bits(double x) {
    std::uint64_t u;
    std::memcpy(&u, &x, 8);
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(u));
    return buf;
}

static std::string fnv(const std::string& text) {
    std::uint64_t h = 0xcbf29ce484222325ULL;
    for (unsigned char b : text) h = (h ^ b) * 0x100000001b3ULL;
    char buf[20];
    std::snprintf(buf, sizeof buf, "%016llx", static_cast<unsigned long long>(h));
    return buf;
}

static Json strings(const std::vector<std::string>& v) { return Json::array(v); }
static Json opt(const std::optional<std::string>& s) { return s ? Json(*s) : Json(); }

static Json dump(const Project& p) {
    Json blocks = Json::object(), off = Json::object();
    for (const auto& c : block_collections()) {
        blocks.set(c, Json(JArray(p.blocks_of(c))));
        auto it = p.switched_off.find(c);
        if (it != p.switched_off.end()) {
            Json names = Json::array();
            for (const Json& b : it->second) names.push(b.get("qname"));
            off.set(c, names);
        }
    }
    std::vector<std::string> disabled(p.disabled.begin(), p.disabled.end());
    std::sort(disabled.begin(), disabled.end());
    std::vector<std::string> keys;
    for (const auto& [k, v] : p.implicitly_disabled) keys.push_back(k);
    std::sort(keys.begin(), keys.end());
    Json implicit = Json::object();
    for (const auto& k : keys) implicit.set(k, Json(p.implicitly_disabled.at(k)));
    DecayModel dm = p.decay_model();
    Json lambdas = Json::array(), parents = Json::array(), grid = Json::array();
    for (double x : dm.lambdas) lambdas.push(Json(bits(x)));
    for (const auto& ps : dm.parents) {
        Json row = Json::array();
        for (const auto& q : ps) row.push(Json::array({Json(q.index), Json(bits(q.lambda)), Json(bits(q.ratio))}));
        parents.push(row);
    }
    for (double t : p.time_grid()) grid.push(Json(bits(t)));
    return Json::object({
        {"name", p.name}, {"description", p.description}, {"simulation", p.simulation},
        {"output_mode", Json(p.output_mode)}, {"decay_unit", Json(p.decay_unit)},
        {"index_lists", p.index_lists}, {"chains", p.chains},
        {"material_list", opt(p.material_list_name)}, {"nuclide_list", opt(p.nuclide_list_name)},
        {"scenario", opt(p.scenario)}, {"scenarios", strings(p.scenarios)},
        {"blocks", blocks}, {"switched_off", off}, {"disabled", strings(disabled)},
        {"implicitly_disabled", implicit},
        {"systems", strings(p.systems)}, {"transports", strings(p.transports)},
        {"derived_lists", strings(std::vector<std::string>(p.derived_lists.begin(), p.derived_lists.end()))},
        {"decay", Json::object({{"names", strings(dm.names)}, {"lambdas", lambdas}, {"parents", parents}})},
        {"grid", grid},
    });
}

int main() {
    Json fx = parse_json(check::read_file(std::string(KOMPARTMENT_CPP_DIR) + "/tests/fixtures/project.json"));
    const char* dumps = std::getenv("KOMPARTMENT_FIXTURE_DUMPS");
    for (const Json& row : fx.get("cases").arr()) {
        const std::string& name = row.get("name").as_string();
        Json model = row.has("example")
                         ? parse_json(check::read_file(std::string(KOMPARTMENT_REPO) + "/examples/" + row.get("example").as_string() + ".json"))
                         : row.get("model");
        try {
            Json before = model.copy();
            Project p(model);
            CHECK_MSG(before == model, name + ": the model handed in is left as it was");
            Json d = dump(p);
            if (dumps && *dumps) std::ofstream(std::string(dumps) + "/" + name + ".cpp.json") << json_text(d, 1);
            if (row.has("hash")) CHECK_MSG(fnv(json_text(d, 0)) == row.get("hash").as_string(), name + ": the project differs");
            else CHECK_MSG(false, name + " is refused there: " + row.get("error").as_string());
        } catch (const ValidationError& e) {
            if (row.has("error")) CHECK_MSG(row.get("error").as_string() == e.what(), name + " is refused with: " + e.what() + "\n   there: " + row.get("error").as_string());
            else CHECK_MSG(false, name + " is read there, refused here: " + e.what());
        } catch (const std::exception& e) {
            CHECK_MSG(false, name + " threw: " + e.what());
        }
    }
    return check::summary("test_project");
}
