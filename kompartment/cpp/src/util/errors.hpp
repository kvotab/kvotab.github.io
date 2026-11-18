// The Julia package's errors, where this engine raises them as it does.
//
// What the Julia package refuses with an `ArgumentError` is refused here with an
// `ArgumentError`, in the same words, and the service names it as Julia's does.
// Its code raises a few other errors on input nothing sensible sends -- a
// `MethodError` where a number was wanted and text came, an `InexactError` where
// a number too large for an integer is made one, a `TypeError`, an
// `OutOfMemoryError` -- and those are a `JuliaError` here, of the same kind:
// the kind is Julia's, the message only says what happened.

#pragma once

#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace kompartment {

/// Julia's `ArgumentError`: what cannot be done as asked, in the Julia package's words.
struct ArgumentError : std::invalid_argument {
    using std::invalid_argument::invalid_argument;
};

/// One of Julia's other errors, where the Julia package raises it: `kind` is its type's name
/// (`MethodError`, `InexactError`, `TypeError`, `OutOfMemoryError`).
struct JuliaError : std::runtime_error {
    std::string kind;
    JuliaError(std::string kind_, const std::string& message) : std::runtime_error(message), kind(std::move(kind_)) {}
};

/// `Int(x)` of a Float64: the whole number, or Julia's `InexactError` where it is not one or
/// does not fit in 64 bits.
long long jl_to_int(double x);

/// Julia's `Array{Float64}(undef, rows, cols)` refusing what it refuses: a negative size or
/// one whose count overflows ("invalid Array dimensions"), a count of 2^60 or more (the
/// memory's own refusal), and memory the system will not give (`OutOfMemoryError`).
/// Returns the count of elements.
long long jl_array_count(long long rows, long long cols);
/// `Vector{Float64}(undef, n)`'s refusals (a negative `n` is the memory's).
long long jl_vector_count(long long n);
/// `count` zeros (a count `jl_array_count` or `jl_vector_count` has let through), or Julia's
/// `OutOfMemoryError` where the system will not give the room.
std::vector<double> jl_zeros(long long count);

}  // namespace kompartment
