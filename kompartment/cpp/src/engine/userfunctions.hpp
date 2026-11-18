// The model's own functions, written out where they are called
// (src/sim/functions.js). A function block is a name, a list of parameters
// and one equation; a call of it is replaced by its body with the arguments
// put in for the parameters, so nothing downstream has to know functions
// exist. A reference in the body that is not a parameter means what it means
// where the function is written, and carries that scope with it.

#pragma once

#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "lang/ast.hpp"
#include "util/json.hpp"

namespace kompartment {

inline constexpr int MAX_FUNCTION_DEPTH = 32;

struct FunctionError : std::runtime_error {
    std::optional<std::string> block_name;
    FunctionError(const std::string& message, std::optional<std::string> block)
        : std::runtime_error(message), block_name(std::move(block)) {}
};

/// The functions of one model, parsed once, ready to be inlined.
class UserFunctions {
public:
    struct Def {
        std::string name;
        std::vector<std::string> parameters;
        Json block;
        ENodePtr ast;
    };

    UserFunctions() = default;
    /// `callable(name, system)`: whether a name the function table does not know is a call
    /// the model defines some other way (a table read at an argument).
    explicit UserFunctions(const JArray& functions,
                           const std::function<bool(const std::string&, const std::string&)>& callable = nullptr);

    std::size_t size() const { return defs_.size(); }
    /// The function a name written in `system` calls, or none.
    std::optional<std::string> resolve(const std::string& written, const std::string& system) const;
    /// `ast` with every call of a function of the model replaced by its body.
    ENodePtr inline_functions(const ENodePtr& ast, const std::optional<std::string>& owner = std::nullopt,
                              const std::string& system = "") const;

private:
    ENodePtr expand(const ENodePtr& ast, const std::optional<std::string>& owner, const std::string& system,
                    const std::vector<std::string>& stack, int depth) const;

    std::unordered_map<std::string, Def> defs_;
    std::unordered_set<std::string> declared_;
};

}  // namespace kompartment
