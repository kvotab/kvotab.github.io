// The arithmetic the engine takes when it need not reproduce the other engines' bits.

#pragma once

#include <cmath>

namespace kompartment {

/// `a * b + c`, fused into one rounding where the processor has the instruction (and
/// rounded twice where it would have to be a library call). Only ever used with parity off.
inline double muladd(double a, double b, double c) {
#if defined(__FP_FAST_FMA) || defined(__aarch64__) || defined(__FMA__)
    return std::fma(a, b, c);
#else
    return a * b + c;
#endif
}

}  // namespace kompartment
