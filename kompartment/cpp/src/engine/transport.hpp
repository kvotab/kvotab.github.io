// Transport sub-systems, unrolled into the chain they stand for
// (src/sim/transport.js and the helpers of src/domain/transport.js).
//
// A transport is a sub-system drawn as two compartments -- its Begin and its
// End -- standing for a chain of N identical ones. Before anything is laid
// out, the chain is written out as ordinary compartments and transfers: the
// elements in between are copies of Begin (marked `hidden`), the transfers
// between Begin and End are repeated for every pair, and the expressions those
// read are copied per pair. A transport operation (the sum or mean over the
// chain, or a value at a point along it) becomes an expression or a call of
// `transport_point`/`transport_sum`/`transport_mean`. The result is a new
// `Project`, so nothing downstream has to know a chain from a model.

#pragma once

#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "engine/project.hpp"
#include "util/json.hpp"

namespace kompartment {

/// A transport that cannot be unrolled, and the block (or sub-system) it is about.
struct TransportError : std::runtime_error {
    std::optional<std::string> block_name;
    explicit TransportError(const std::string& message, std::optional<std::string> block = std::nullopt)
        : std::runtime_error(message), block_name(std::move(block)) {}
};

/// The sub-systems of a project that are transports.
std::vector<std::string> transport_paths(const Project& project);

/// The project as a file holds it (the application's `toJSON`): the blocks that run and
/// the ones switched off, normalised, in the same key order. The lists and dictionaries
/// it holds are the project's own.
Json project_to_json(const Project& project);

/// The project with every transport written out as its chain: the project a model with
/// transport sub-systems is built from. What stops a transport being one is a
/// `BuildError` naming the block concerned, as the builder reports it; a chain the
/// application would refuse to load once written out is a `ValidationError`. A project
/// none of whose transports is a sub-system comes back as it is (a copy).
std::shared_ptr<const Project> expand_transports(const Project& project);

}  // namespace kompartment
