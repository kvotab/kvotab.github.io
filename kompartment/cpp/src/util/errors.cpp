#include "util/errors.hpp"

#include <cmath>
#include <cstdio>
#include <limits>
#include <new>

namespace kompartment {

namespace {

// Julia's `GenericMemory` holds fewer than 2^60 elements of 8 bytes.
constexpr long long MEMORY_MOST = 1LL << 60;

const char* const MEMORY_REFUSAL =
    "invalid GenericMemory size: the number of elements is either negative or too large for system address width";

}  // namespace

long long jl_to_int(double x) {
    if (!(x >= -9.223372036854775808e18 && x < 9.223372036854775808e18) || x != std::floor(x)) {
        char buf[64];
        std::snprintf(buf, sizeof buf, "InexactError: Int64(%.17g)", x);
        throw JuliaError("InexactError", buf);
    }
    return static_cast<long long>(x);
}

long long jl_array_count(long long rows, long long cols) {
    if (rows < 0 || cols < 0 || (cols != 0 && rows > std::numeric_limits<long long>::max() / cols))
        throw ArgumentError("invalid Array dimensions");
    long long n = rows * cols;
    if (n >= MEMORY_MOST) throw ArgumentError(MEMORY_REFUSAL);
    return n;
}

long long jl_vector_count(long long n) {
    if (n < 0 || n >= MEMORY_MOST) throw ArgumentError(MEMORY_REFUSAL);
    return n;
}

std::vector<double> jl_zeros(long long count) {
    try {
        return std::vector<double>(static_cast<std::size_t>(count), 0.0);
    } catch (const std::bad_alloc&) {
        throw JuliaError("OutOfMemoryError", "OutOfMemoryError()");
    } catch (const std::length_error&) {
        throw JuliaError("OutOfMemoryError", "OutOfMemoryError()");
    }
}

}  // namespace kompartment
