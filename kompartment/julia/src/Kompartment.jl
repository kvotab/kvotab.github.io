"""
    Kompartment

Kompartment's models in Julia: open a model file (Kompartment's own JSON, or
an Ecolego project or assessment), build it into equations, run it with the
application's solvers, and save what it produced -- the table, the HDF5
result file the assessment tools read.

```julia
using Kompartment
m = Kompartment.load("biosphere.json")
res = run(m)
res["Dose [I-129]"]
to_csv(res, "biosphere.csv")
```

The equations are compiled to native code: each pass of a model (the
values that never change, those that follow the clock, those that read the
state) becomes a Julia function, and the derivative is assembled as one
sparse product in the application's order. The solvers are ports of the
application's own, so a run takes the steps the application takes.
"""
module Kompartment

using LinearAlgebra
using SparseArrays
using Printf
using Dates
using OrderedCollections: OrderedDict
import FunctionWrappers
import FunctionWrappers: FunctionWrapper

# --- utilities -------------------------------------------------------------------
include("util/jsnum.jl")
include("util/zip.jl")
include("util/jsonio.jl")
include("lang/jsmath.jl")
include("lang/tokenize.jl")
include("lang/functions.jl")
include("lang/parse.jl")

# --- the model as a file holds it ----------------------------------------------------
include("model/names.jl")
include("model/decay.jl")
include("model/indexlists.jl")
include("engine/farfield_domain.jl")
include("model/keys.jl")
include("model/simulation.jl")
include("model/normalise.jl")

# --- the engine ----------------------------------------------------------------------
include("engine/timeseries.jl")
include("engine/indexspace.jl")
include("engine/project.jl")
include("engine/lookup.jl")
include("engine/recorders.jl")
include("engine/userfunctions.jl")
include("engine/tree.jl")
include("engine/builder_types.jl")
include("engine/pending.jl")
include("engine/farfield.jl")
include("engine/transport.jl")
include("engine/unitcheck.jl")
include("engine/builder.jl")
include("engine/codegen.jl")
include("engine/system.jl")

# --- the solvers and the run ----------------------------------------------------------
include("solvers/solvers.jl")
include("io/csv.jl")
include("io/hdf5.jl")
include("io/resultfile.jl")
include("engine/jacobian.jl")
include("engine/switchtimes.jl")
include("engine/derived.jl")
include("engine/massbalance.jl")
include("engine/runner.jl")

# --- many runs: probabilistic runs and what they say -----------------------------------
include("stats/normal.jl")
include("stats/pdf.jl")
include("stats/sample.jl")
include("stats/correlate.jl")

# --- importing ------------------------------------------------------------------------
include("importers/eco.jl")
include("importers/open.jl")

# --- the package's face ---------------------------------------------------------------
include("api.jl")

# --- editing a model, as the Python package's API edits one ---------------------------------
include("model/edit_base.jl")
include("model/distributions.jl")
include("model/blocks.jl")
include("model/edit.jl")
include("model/edit_views.jl")
include("model/check.jl")
include("model/edit_precompile.jl")

# --- the run in words, the run with its model, and saving ------------------------------------
include("engine/runlog.jl")
include("io/dataset.jl")
include("io/save.jl")

# --- many runs: probabilistic runs and what they say ------------------------------------------
include("engine/probabilistic.jl")
include("engine/analysis.jl")

include("precompile.jl")

# Opening, running and saving. `load` and `select` are left unexported (FileIO and DataFrames export
# the same names): `Kompartment.load(path)`, and `outputs(res, block)` to pick series.
export Model, Results, System, Project, from_json, to_json, save, simulation, set_simulation!, build,
       run_file, outputs, labels, series, series_many, to_csv, to_dict, to_matrix, total, mass_balance,
       held_at_zero, dydt, initial_state, evaluate_algebraic!, import_ecolego, results_tree, write_hdf5,
       write_results_hdf5, run_scenarios, scenarios_tree, write_scenarios_hdf5, values_at_start, run_log,
       load_results, DatasetError,
       run_probabilistic, run_tornado, run_realisation, ProbabilisticResults, realisations,
       quantiles, realisations_mean, median_spread, bands, what_drove, tornado_table, probabilistic_tree,
       write_probabilistic_hdf5

# The editing API. Left unexported for their generic names, reached as `Kompartment.name`
# or as properties (`m.parameters`, `m.systems`, ...): check, update!, combinations,
# reads, parameters, functions, events, systems, transports, materials, nuclides,
# scenarios, shapes, derived, layout, Shape and the `distributions` module.
export EditError, DistributionError, Block, Compartment, Transfer, Inflow, Parameter, Expression, Lookup,
       IndexReduction, BlockReduction, FunctionBlock, MinMax, RunningMean, Snapshot, Delay, Trigger, Farfield,
       WastePackage, Event, IndexListView, SimulationView, OutputSeries, ViewSettings,
       new_model, block, get_block, blocks, block_names, compartments, transfers, inflows, expressions, lookups,
       index_reductions, block_reductions, min_maxes, running_means, snapshots, delays, triggers, farfields,
       waste_packages, set_value!, set_entry!, value_at, clear_value!, overrides, entry_index, set_distribution!,
       distribution_at, set_point_distribution!, make_pdf, set_availability!, set_failure!, add_fail_action!,
       add_move_action!, clear_actions!, reduce_over!, outflows,
       add_compartment!, add_parameter!, add_expression!, add_transfer!, add_inflow!, add_lookup!,
       add_index_reduction!, add_block_reduction!, add_function!, add_min_max!, add_running_mean!, add_snapshot!,
       add_delay!, add_trigger!, add_farfield!, add_waste_package!, add_event!, add_transport!,
       add_transport_operation!, unique_name, default_dimensions,
       rename_block!, move_block!, move_blocks!, delete_block!, delete_blocks!, set_connection_end!, set_release!,
       set_dimensions!, set_reduction_target!, set_aggregate_targets!, set_function_parameters!, references_to,
       references_graph,
       add_index_list!, index_list, all_index_lists, add_index!, add_indices!, remove_index!, rename_index!,
       set_index_enabled!, rename_index_list!, delete_index_list!, map_index!, set_list_role!, index_list_users,
       set_scenario_list!, add_scenarios!, scenario, set_scenario!, index_combinations, combination_count,
       add_nuclides!, add_material!, remove_material!, remove_nuclide!, set_material_unit!, material_unit,
       half_life, set_half_life!, decay_chains, set_decay_chains!, reset_decay_chains!, add_decay_pair!,
       remove_decay_pair!, set_decay_ratio!, decay_unit, set_decay_unit!, material_dimension,
       add_system!, rename_system!, move_system!, delete_system!, set_system_enabled!, system_enabled,
       system_position, set_system_position!, add_shape!, remove_shape!, move_shape!, add_derived!,
       remove_derived!, record_review!, clear_review!, review_status, review_stamp, state_count, check_model,
       settle!, put_values!, add_output_series!, remove_output_series!, solver_settings

end # module
