#include "util/parity.hpp"

#include <atomic>
#include <cstdlib>
#include <cstring>

namespace kompartment {

namespace {

bool env_is(const char* name, std::initializer_list<const char*> words) {
    const char* v = std::getenv(name);
    if (!v) return false;
    std::string s(v);
    std::size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
    s = a == std::string::npos ? "" : s.substr(a, b - a + 1);
    for (char& c : s)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    for (const char* w : words)
        if (s == w) return true;
    return false;
}

std::atomic<bool>& parity_flag() {
    static std::atomic<bool> flag{env_is("KOMPARTMENT_PARITY", {"1", "true", "yes", "on"})};
    return flag;
}

std::atomic<SolverPolicy>& policy_flag() {
    static std::atomic<SolverPolicy> flag{env_is("KOMPARTMENT_SOLVERS", {"model"}) ? SolverPolicy::Model : SolverPolicy::Fastest};
    return flag;
}

}  // namespace

bool parity() noexcept { return parity_flag().load(std::memory_order_relaxed); }
void set_parity(bool on) noexcept { parity_flag().store(on, std::memory_order_relaxed); }

SolverPolicy solver_policy() noexcept { return parity() ? SolverPolicy::Model : policy_flag().load(std::memory_order_relaxed); }
void set_solver_policy(SolverPolicy policy) noexcept { policy_flag().store(policy, std::memory_order_relaxed); }

std::string quicker_solver(const std::string& asked) {
    return (solver_policy() == SolverPolicy::Fastest && asked == "ros23") ? "ndf" : asked;
}

}  // namespace kompartment
