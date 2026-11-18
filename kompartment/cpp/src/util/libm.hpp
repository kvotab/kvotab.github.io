// The C library's sine, cosine and arcsine, as the Julia package's ccalls have them
// (`csin`, `ccos`, `casin` in julia/src/lang/jsmath.jl), which is what numpy calls
// too: the far field's Laplace-domain arithmetic and the sensitivity designs are
// compared with Julia's to the last bit through them.
//
// sin and cos are called through pointers the compiler cannot see through: on
// Darwin it would make a sin and a cos of the same number one call of
// __sincos_stret, whose bits are not always theirs. (exp and log are plain
// `std::exp` and `std::log`, which are the C library's.)

#pragma once

namespace kompartment {

double lm_sin(double x);
double lm_cos(double x);
double lm_asin(double x);

}  // namespace kompartment
