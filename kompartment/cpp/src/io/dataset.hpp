// A model and the run it produced, in one archive, as Kompartment writes one:
// the application's *Save with results* (src/io/dataset.js), so that an
// archive written here opens in the application as a live run.
//
// What is kept is the state vector, not the series: every other series is
// worked out from (t, y) on demand, so a reopened run answers every question
// a fresh one does. The archive is a ZIP with the run beside the model:
//
//     <name>.json          the model
//     results/meta.json    the run report, the layout signature, the lengths
//     results/t.f64        the output times
//     results/y.f64        the state vector at each of them, time-major
//     results/held.i32     per state, how many steps the zero-floor moved it
//     results/mem.f64      the histories of the blocks that remember

#pragma once

#include <string>
#include <utility>
#include <vector>

#include "engine/runner.hpp"

namespace kompartment {

inline constexpr int DATASET_FORMAT = 1;

/// What the numbers of a run mean, as one string (the application's `layoutSignature`):
/// every entry of the state vector and every recorder slot, by the name and offset the
/// builder gave it.
std::string layout_signature(const System& sys);

/// The file name a model's name gives, as the application makes it.
std::string slug(const Json& name);

struct ArchiveOptions {
    bool states = true;       // false: a run the engine holds and answers for
    Json extra;               // set over the meta, key by key
    Json log;                 // the run log as lines; null for none
    bool compress = true;
};

/// A model and its run as the archive *Save with results* writes.
std::string dataset_archive(Results& res, const ArchiveOptions& options = {});

}  // namespace kompartment
