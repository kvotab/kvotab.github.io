#include "util/libm.hpp"

#include <cmath>

namespace kompartment {

namespace {

using Fn1 = double (*)(double);
Fn1 volatile p_sin = static_cast<Fn1>(&std::sin);
Fn1 volatile p_cos = static_cast<Fn1>(&std::cos);
Fn1 volatile p_asin = static_cast<Fn1>(&std::asin);

}  // namespace

double lm_sin(double x) { return p_sin(x); }
double lm_cos(double x) { return p_cos(x); }
double lm_asin(double x) { return p_asin(x); }

}  // namespace kompartment
