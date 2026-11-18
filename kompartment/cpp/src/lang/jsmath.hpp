// The arithmetic of the application, where it is compared to the last digit.
//
// The model's own equations are evaluated with the C library's exp, log, pow
// and the rest -- which is what the Python engine's numpy and the Julia
// engine use too, so a derivative here is theirs to the last bit; those are
// plain `std::exp` and so on.
//
// Here are V8's own `Math.exp`, `Math.log`, `Math.log10`, `Math.pow`,
// `Math.log1p` and `Math.expm1` -- V8 carries ports of fdlibm
// (src/base/ieee754.cc) -- for the few numbers that are compared with the
// application's to the last digit: the output times of a logarithmic grid,
// above all, where a time column that differs in its seventeenth digit makes
// two result files that cannot be joined on time.

#pragma once

namespace kompartment {

double js_exp(double x);
double js_log(double x);
double js_log10(double x);
double js_pow(double x, double y);
double js_log1p(double x);
double js_expm1(double x);

}  // namespace kompartment
