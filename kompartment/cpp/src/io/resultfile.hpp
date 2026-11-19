// A run's results as an HDF5 tree, as Kompartment writes one: the Julia package's
// io/resultfile.jl (the Python package's `kompartment/io/resultfile.py`, the
// application's `src/io/resultfile.js`) -- the result browser's convention (Ecolego's
// own shape) laid over io/hdf5, so that a file written here is, for the same numbers,
// the file the application and the other engines write, to the byte:
//
//     /time                        the output grid, once, with its unit
//     /IndexLists/Radionuclides    the members of each index list, by name
//     /Soil/                       a block, as a group, when it is indexed
//          @IndexLists = ['Radionuclides']
//          @time_dependent = 'TRUE'
//          Cs-137                  one series per member
//     /NearField/Flux              a block that is not indexed, as a dataset
//
// Two dimensions nest: a block indexed by areas and nuclides is
// `/Dose/<area>/<nuclide>`, the nuclide the leaf and each `<area>` a group carrying the
// `IndexLists` that gets the nuclides drawn together. A value that cannot change over the
// run (`timeDependent` false on its descriptor) is one value -- one per realisation in a
// file of realisations -- and says `time_dependent = 'FALSE'`.
//
// A probabilistic run is written as the page's *Save -> Realisations* writes it: every
// realisation as float32 (one row per output time, one column per realisation), their
// mean, or one realisation by number, with the varied inputs beside them. Several
// scenarios' runs are written as one file, the scenario list one more index of every
// series.
//
// Which series to write is said as the Julia package says it: a list of labels,
// descriptors (found by their label), or positions counted from 1.
//
//     Results res = run_project(project);
//     save_results(res, "out.h5");                        // every series
//     ProbabilisticResults prob = run_probabilistic(project, options);
//     ProbabilisticSaveOptions o;
//     o.want = Json("mean");
//     save_probabilistic(prob, "mean.h5", o);

#pragma once

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "engine/probabilistic.hpp"
#include "engine/runner.hpp"
#include "io/dataset.hpp"
#include "io/hdf5.hpp"
#include "util/json.hpp"

namespace kompartment {

/// When a file says it was made (`created_time`), as the page's clock reads it: now; a local
/// time as given; or seconds since the epoch, read as the local time (as Python's
/// `datetime.fromtimestamp` splits it).
struct Stamp {
    enum class Kind { Now, Local, Epoch };
    Kind kind = Kind::Now;
    int year = 1970, month = 1, day = 1, hour = 0, minute = 0, second = 0;
    double seconds = 0;

    static Stamp now() { return {}; }
    static Stamp local(int year, int month, int day, int hour = 0, int minute = 0, int second = 0);
    static Stamp epoch(double seconds);
};

/// `YYYY-MM-DD hh:mm:ss`, the time a stamp says.
std::string stamp_text(const Stamp& when);

/// A stamp as written on the command line: `YYYY-MM-DD hh:mm:ss` (or with a `T`), a date, or
/// seconds since the epoch; none when it is none of these.
std::optional<Stamp> parse_stamp(const std::string& text);

/// The model's description as the markup the result browser renders (`description_html`), or
/// none when there is nothing to say: the text escaped -- it is plain text, so a `<` in it is
/// a `<` somebody meant -- then blank lines made paragraphs and single newlines breaks.
std::optional<std::string> description_html(const Json& text);

/// A series' values by its position in the outputs (from 0).
using ColumnFunction = std::function<std::vector<double>(std::size_t)>;

/// Every realisation of a probabilistic run, for `result_tree`: `matrix_for(i)` (i from 0)
/// gives series i's values as float32, `times x n` of them, time-major (every realisation at
/// the first time, then at the second), `n` for one that cannot change over the run, or none
/// for a series that was not part of the run. `iterations` is n; none is JavaScript's
/// `undefined`.
struct TreeRealisations {
    std::optional<Json> iterations;
    std::function<std::optional<std::vector<float>>(std::size_t)> matrix_for;
};

/// That the curves are the mean of a probabilistic run (`of` = "mean") or its k-th
/// realisation (`of` = k, from 1), and of how many (`iterations`); none is `undefined`.
struct TreeSample {
    std::optional<Json> iterations;
    std::optional<Json> of;
};

/// The tree for a run (`result_tree`), ready for `write_hdf5`.
///
/// `t` is the output times; `outputs` the series descriptors (`"label"`, `"block"`, `"kind"`,
/// `"nuclide"`, `"index"`, `"dims"`, `"unit"`, `"timeDependent"`) in order; `column(i)` one
/// series' values; `which` the outputs to write, as positions in `outputs` (from 0). `model`
/// is the model as a dictionary, for its name, description and settings (anything else is
/// taken as an empty one); `index_lists` its index lists, each a dictionary with `"name"` and
/// `"indices"` (or the shorthand `"elements"`); `now` the `created_time`. `realisations`
/// writes every run of a probabilistic result, and `sample` says that the curves are a mean
/// or one realisation of one.
std::shared_ptr<H5Group> result_tree(const std::vector<double>& t, const std::vector<Json>& outputs, const ColumnFunction& column,
                                     const std::vector<std::size_t>& which, const Json& model, const Json& index_lists,
                                     const Stamp& now = {}, const TreeRealisations* realisations = nullptr,
                                     const TreeSample* sample = nullptr);

/// Where each asked-for output is, from 0 (`_rf_which_of`): every one when none are asked for;
/// a label (the first output of it), a descriptor (by its label, else by being the same
/// one), or a position counted from 1 (Julia's). An `ArgumentError` for a label that is not
/// there; a position out of range is Julia's `BoundsError`.
std::vector<std::size_t> which_outputs(const std::vector<Json>& outputs, const std::optional<std::vector<Json>>& which);

/// What a file names as its model, and what it is read against.
struct ResultTreeOptions {
    /// The series to write (labels, descriptors or positions from 1); none: every one.
    std::optional<std::vector<Json>> which;
    /// The model the file names, as a project (its file; for a probabilistic run, its index
    /// lists too) or as a model's dictionary; neither: the run's own.
    std::shared_ptr<const Project> project;
    std::optional<Json> model;
    /// The index lists to write, each a dictionary with `"name"` and `"indices"` (or
    /// `"elements"`); none: the run's own (a probabilistic run: the model's).
    std::optional<Json> index_lists;
    Stamp now;
};

/// What `results_tree` may be told besides: where the series' values come from, and that
/// they are realisations or a sample of a probabilistic run (see `result_tree`).
struct ResultsTreeOptions : ResultTreeOptions {
    /// Overrides where series i's values come from (from 0); none: the run's own, worked out
    /// in one pass.
    ColumnFunction column;
    const TreeRealisations* realisations = nullptr;
    const TreeSample* sample = nullptr;
};

/// The tree of a run, as the page's *Export to HDF5* builds it (`results_tree`).
std::shared_ptr<H5Group> results_tree(Results& res, const ResultsTreeOptions& options = {});

/// A run as an HDF5 result file's bytes (`write_results_hdf5`).
std::string write_results_hdf5(Results& res, const ResultsTreeOptions& options = {});

/// What of a probabilistic run a file holds.
struct ProbabilisticTreeOptions : ResultTreeOptions {
    /// `"all"` -- every realisation, as float32, one row per output time and one column per
    /// realisation, or one value per realisation for a series that cannot change over the run
    /// -- `"mean"`, the mean at every time of the realisations that ran, or a realisation by
    /// its number, from 1 (rounded, and brought into the realisations held).
    Json want = Json("all");
    /// The varied parameters too, one value per realisation (NaN for one that did not run).
    bool inputs = true;
};

/// A probabilistic run as a result file's tree, as the page's *Save -> Realisations* writes it
/// (`probabilistic_tree`). The file says what it holds, so it is not taken for a
/// deterministic run. The times are the sample's own grid.
std::shared_ptr<H5Group> probabilistic_tree(const ProbabilisticResults& prob, const ProbabilisticTreeOptions& options = {});

/// A probabilistic run as an HDF5 result file's bytes (`write_probabilistic_hdf5`).
std::string write_probabilistic_hdf5(const ProbabilisticResults& prob, const ProbabilisticTreeOptions& options = {});

/// Which scenario a file of several is read against.
struct ScenariosTreeOptions : ResultTreeOptions {
    /// The scenario whose series and output times the file is read against; none: the first.
    std::optional<std::string> active;
};

/// Several scenarios' runs as one result file (`scenarios_tree`), as the page writes a table
/// that holds more than one scenario: each series once per scenario, with the scenario list
/// as one more index of it, so every block holds a group per scenario the way it holds one
/// per nuclide. `runs` are scenario name and run, in the model's order. Each other scenario's
/// series of the same label follows the active one's, read onto its times (linearly, NaN
/// outside its own span). With one run the file is that run's alone, as `results_tree`
/// writes it.
std::shared_ptr<H5Group> scenarios_tree(std::vector<std::pair<std::string, Results>>& runs, const ScenariosTreeOptions& options = {});

/// Several scenarios' runs as one HDF5 result file's bytes (`write_scenarios_hdf5`).
std::string write_scenarios_hdf5(std::vector<std::pair<std::string, Results>>& runs, const ScenariosTreeOptions& options = {});

/// How a run is saved (`save`).
struct SaveOptions : ResultsTreeOptions {
    /// The blocks whose series are written, by name (instead of `which`).
    std::optional<std::vector<std::string>> blocks;
    /// Subtracted from the file's `/time` (and the table's time column), and nothing else.
    double time_origin = 0;
    /// For an archive: what `dataset_archive` takes.
    ArchiveOptions archive;
};

/// Writes a run to `path`, chosen by its ending (`save`): `.h5` (`.hdf5`, `.hdf`, `.he5`) as
/// the HDF5 result file the application's *Export to HDF5* writes, `.csv` as its table,
/// `.zip` as the model and its run in one archive, as *Save with results* writes it. An
/// archive keeps the whole run, and a table takes only `which` and `time_origin`; anything
/// else is refused, in the Julia package's words. Returns `path`.
std::string save_results(Results& res, const std::string& path, const SaveOptions& options = {});

/// How a probabilistic run is saved.
struct ProbabilisticSaveOptions : ProbabilisticTreeOptions {
    double time_origin = 0;
};

/// Writes a probabilistic run as the HDF5 result file the application's *Save ->
/// Realisations* writes (`save`). Returns `path`.
std::string save_probabilistic(const ProbabilisticResults& prob, const std::string& path, const ProbabilisticSaveOptions& options = {});

/// Writes several scenarios' runs as one HDF5 result file (`write_scenarios_hdf5` with a path).
std::string save_scenarios(std::vector<std::pair<std::string, Results>>& runs, const std::string& path,
                           const ScenariosTreeOptions& options = {});

/// Whether a path names an HDF5 file: it ends `.h5`, `.hdf5`, `.hdf` or `.he5`, in any case.
bool is_hdf5_path(const std::string& path);

}  // namespace kompartment
