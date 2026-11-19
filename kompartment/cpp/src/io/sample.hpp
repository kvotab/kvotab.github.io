// A probabilistic run as the application's archive holds one: `results/sample/`
// beside the model, as src/io/dataset.js writes it (`sampleEntries`) and reads it
// back (`readSample`, `sampleResult`) -- the Julia package's src/io/sample.jl. The
// engine hands a probabilistic run to the page this way, and the page holds it as
// the sample it is: bands, histograms and *What drove it* worked out there from
// these numbers, or asked of the engine where it keeps the sample.
//
//     results/sample/meta.json     what it all is (`format`, `iterations`, `times`, `precision`,
//                                  `outputs`, `flat`, `drawnFrom`, `plan`, `stats`...)
//     results/sample/t.f64         the output times
//     results/sample/series.f64    the kept series, realisation after realisation (`.f32` when
//                                  the run held float32); not there when the engine holds them
//     results/sample/draws.f64     each varied input's values, an input after another
//     results/sample/ran.u8        which realisations integrated

#pragma once

#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "engine/probabilistic.hpp"
#include "util/json.hpp"

namespace kompartment {

/// The sample's own format, bumped only as `DATASET_FORMAT` is.
inline constexpr int SAMPLE_FORMAT = 1;

/// The run's statistics as the page reads them: a tornado's swung inputs, and the inputs of
/// each of a sensitivity design's factors, counted from 0, as it counts them (`_sample_stats`).
Json sample_stats(const Json& stats);

/// A probabilistic run as the entries of `results/sample/` (the application's
/// `sampleEntries`): the kept series realisation after realisation, in the precision the run
/// held them in, then each varied input's draws, which realisations integrated, and what it
/// all is. `series` false leaves the kept series out, for a sample the engine holds and
/// answers for (`onEngine` in the meta). A part of a run (a range of its realisations) is
/// refused, in the Julia package's words.
std::vector<std::pair<std::string, std::string>> sample_entries(const ProbabilisticResults& r, const Json& stamp = Json(), bool series = true);

struct SampleArchiveOptions {
    /// The model as its file holds it; the run's own when null.
    const Json* project = nullptr;
    /// The model's entry name; `<slug of its name>.json` when none.
    std::optional<std::string> inner;
    /// When, as the meta says it; now (`toISOString`) when none is given.
    std::optional<Json> stamp;
    bool compress = true;
    /// The entries' time, seconds since the epoch (the epoch itself by default).
    double modified = 0;
    bool series = true;
};

/// The model and a probabilistic run of it as one archive: the model at the root, the sample
/// under `results/sample/` (`sample_archive`).
std::string sample_archive(const ProbabilisticResults& r, const SampleArchiveOptions& options = {});

}  // namespace kompartment
