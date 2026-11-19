// The project a run is built from: a model file read, normalised and checked
// (`Project` in src/domain/project.js). It takes the model as the file has it
// and produces the shape the builder reads: every block with its defaults,
// its dimensions and its entries resolved; the index space; the decay model;
// the connections' ends qualified; disabled blocks set aside. Anything the
// application would refuse to load is refused here with the same message.

#pragma once

#include <functional>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "engine/indexspace.hpp"
#include "util/json.hpp"

namespace kompartment {

/// A model the application would refuse to load. A block named prefixes the message.
struct ValidationError : std::runtime_error {
    std::optional<std::string> block;
    explicit ValidationError(const std::string& message, std::optional<std::string> block_ = std::nullopt);
};

const std::vector<std::string>& block_collections();        // in the order blocks are normalised
std::string kind_of_collection(std::string_view collection);
/// The settings of a kind of block that hold a value per index, the first its own value.
const std::vector<std::string>& value_keys(std::string_view kind);
const std::vector<std::string>& waste_nuclide_keys();
const std::vector<std::string>& waste_single_keys();
const std::vector<std::string>& waste_equation_keys();
const std::vector<std::string>& dis_equation_keys();
/// What each timing reads as a value; a trigger is read as a name, by the builder.
std::vector<std::string> timing_keys(std::string_view timing);
std::vector<std::string> failure_keys(std::string_view failure);
std::string waste_label(std::string_view key);

/// The value of `key` at one index tuple: the most specific matching entry, the first of
/// them on a tie, else the block's own (null when it has none).
Json value_at(const Json& block, std::string_view key, const Tup& tup);

/// `value_at(block, key, tup)` as a function of `tup`, with the entries indexed once by
/// the lists each names: the same answer, quicker for many tuples.
std::function<Json(const Tup&)> entry_lookup(const Json& block, const std::string& key);

bool has_dydt(const Json& block);

/// Decay constants and, per nuclide, the parents growing into it (`buildDecayModel`).
struct DecayModel {
    struct Parent {
        int index;
        double lambda;
        double ratio;
    };
    std::vector<std::string> names;
    std::vector<double> lambdas;
    std::vector<std::vector<Parent>> parents;
};

/// How Python's f-string shows a value in a message (`None`, `1e-05`).
std::string py_text(const Json& v);

/// A Json list of text as strings (what is not text as JavaScript writes it).
std::vector<std::string> strings_of(const Json& list);

struct Problem {
    std::string name, field, message;
};

class Project {
public:
    /// A model (a dictionary as the file holds it), normalised and validated as the
    /// application loads one. The caller's dictionary is never changed.
    explicit Project(const Json& raw);

    Json raw;
    Json name;
    Json description;
    Json simulation;                 // a dictionary: the settings, defaults filled in
    Json output_times;               // the series, normalised
    std::string output_mode;         // grid, solver, both
    bool solver_points = false;
    Json nuclides;
    std::string decay_unit;
    double decay_ceiling = 0;
    Json half_lives_override;
    bool chains_stated = false;
    Json chains_override;
    Json chains;                     // [[parent, daughter, branching], ...]
    std::set<std::string> derived_lists;
    Json index_lists;                // normalised dictionaries
    IndexSpace index_space;
    std::optional<std::string> material_list_name;
    std::optional<std::string> nuclide_list_name;
    std::optional<std::string> scenario;
    std::vector<std::string> scenarios;
    std::unordered_map<std::string, JArray> blocks;   // by collection: the enabled blocks
    std::unordered_set<std::string> disabled;
    std::vector<std::string> disabled_systems;
    std::unordered_map<std::string, std::string> off_reasons;
    std::unordered_map<std::string, std::string> implicitly_disabled;
    std::unordered_map<std::string, JArray> switched_off;
    std::vector<std::string> systems;
    std::vector<std::string> transports;
    Json layout;
    Json shapes;
    Json derived;
    Json view;

    const JArray& blocks_of(std::string_view collection) const;
    std::vector<std::string> material_names() const;
    std::vector<std::string> nuclide_names() const;
    /// A nuclide's half-life in years: the model's own where it gives one, the table's
    /// otherwise; none for a name neither knows.
    std::optional<double> half_life_of(const std::string& nuclide) const;
    /// Decay constant per time unit: ln 2 over the half-life converted into it.
    double lam(const std::string& nuclide, const std::string& time_unit) const;
    DecayModel decay_model() const;
    DecayModel decay_model_for(const std::optional<std::string>& list_name) const;

    std::string material_unit(const std::string& name) const;
    std::string dimension_unit(const std::string& list_name) const;

    /// Every enabled block by qualified name, in the collections' order.
    std::vector<std::pair<std::string, Json>> blocks_by_name() const;
    std::vector<Json> all_blocks() const;

    std::vector<Problem> waste_problems() const;
    std::vector<Problem> disruption_problems() const;

    /// The output times: one series over the run, or the combined list of series.
    std::vector<double> time_grid() const;

    double start_time() const { return simulation.get("start_time").as_double(); }
    double end_time() const { return simulation.get("end_time").as_double(); }
    std::string time_unit() const { return simulation.get("time_unit").as_string(); }

private:
    Json normalise_block(const Json& raw_block, const std::string& kind);
    std::vector<std::string> dimensions_for(const Json& raw_block, const std::string& kind);
    std::optional<std::vector<std::string>> endpoint_dims(const Json& name);
    std::string derived_unit(const Json& block, const std::string& kind) const;
    std::string inventory_unit(const Json& base) const;
    void resolve_endpoints();
    void follow_disabled_ends();
    void validate();

    std::unordered_map<std::string, double> half_lives_;   // the model's own
    std::optional<std::unordered_map<std::string, Json>> ends_by_name_;
    // The output times last worked out, under `grid_lock_`: every realisation of a
    // probabilistic run asks for them, from whichever thread runs it.
    mutable std::string grid_key_;
    mutable std::vector<double> grid_;
    CacheLock grid_lock_;
};

/// Normalised pieces, as the application reads them.
Json normalise_index_lists(const Json& raw_lists);
Json normalise_series(const Json& raw);
Json normalise_points(const Json& points, const Json& block_name);
Json normalise_targets(const Json& targets, const Json& block_name);
Json normalise_actions(const Json& raw);

}  // namespace kompartment
