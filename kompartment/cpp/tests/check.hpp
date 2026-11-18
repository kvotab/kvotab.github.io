// The tests' few helpers: a check that counts, and a summary that fails the program.

#pragma once

#include <cstdio>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>

namespace check {

inline int& passed() { static int n = 0; return n; }
inline int& failed() { static int n = 0; return n; }

inline void that(bool ok, const std::string& what, const char* file, int line) {
    if (ok) { passed()++; return; }
    failed()++;
    if (failed() <= 40) std::fprintf(stderr, "FAILED %s:%d: %s\n", file, line, what.c_str());
}

inline std::string bits(double x) {
    unsigned long long u;
    std::memcpy(&u, &x, 8);
    char buf[40];
    std::snprintf(buf, sizeof buf, "%.17g (0x%016llx)", x, u);
    return buf;
}

/// Equal to the bit (and a NaN equal to a NaN).
inline bool same_bits(double a, double b) {
    if (a != a && b != b) return true;
    return std::memcmp(&a, &b, 8) == 0;
}

inline std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("Cannot read " + path);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

inline int summary(const char* name) {
    std::printf("%s: %d passed, %d failed\n", name, passed(), failed());
    return failed() ? 1 : 0;
}

}  // namespace check

#define CHECK(cond) check::that((cond), #cond, __FILE__, __LINE__)
#define CHECK_MSG(cond, msg) check::that((cond), (msg), __FILE__, __LINE__)
#define CHECK_EQ(a, b) check::that((a) == (b), std::string(#a " == " #b), __FILE__, __LINE__)
#define CHECK_BITS(a, b) check::that(check::same_bits((a), (b)), std::string(#a " is " #b ": ") + check::bits(a) + " vs " + check::bits(b), __FILE__, __LINE__)
