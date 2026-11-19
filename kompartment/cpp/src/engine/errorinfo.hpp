// An error as the Julia package names and shows it.
//
// Where the Julia package says what went wrong in words -- a realisation that
// failed, in a probabilistic run's "trouble"; an error the service reports to
// the page -- it writes `sprint(showerror, e)` and names the error by its type.
// This engine raises the same errors as types of its own (engine/, solvers/,
// util/errors.hpp); here each is given the name and the text Julia's would have.

#pragma once

#include <exception>
#include <optional>
#include <string>

namespace kompartment {

struct ErrorInfo {
    /// Its type's name, as Julia's `nameof(typeof(e))` gives it: `SolverError`,
    /// `ArgumentError`, `ErrorException`, `InexactError`...
    std::string name;
    /// What `sprint(showerror, e)` writes: an `ArgumentError`'s with its name in front, a
    /// `SolverError`'s message alone.
    std::string shown;
    /// What the service says it was (`_service_error`): its `message` where it has one, the
    /// shown text without its name in front otherwise.
    std::string message;
    /// A `BuildError`'s or a `SolverError`'s block, and a `SolverError`'s hint.
    std::optional<std::string> block;
    std::optional<std::string> hint;
};

/// The error `e` holds, as the Julia package names and shows it. An error this engine raises
/// of a model it cannot build yet (`NotSupported`) keeps that name: the service calls it what
/// the page falls back on.
ErrorInfo error_info(const std::exception_ptr& e);

}  // namespace kompartment
