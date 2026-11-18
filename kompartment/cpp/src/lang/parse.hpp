// The equation language: its tokenizer and parser (src/parser/parser.js).
//
// The tokenizer splits text the application's way, character for character:
// a number (`1e-5`, `1.0E10`); a name, where a dotted path such as
// `NearField.Water` is one name (the dot is taken only when a letter follows
// it); the text inside `[...]`, raw, as one index token; brackets,
// parentheses, commas and the operators, the multi-character ones tried
// first.
//
// The parser has the C family's precedence for everything except `^`, which
// binds tighter than unary minus and is left-associative (`2^3^2` is 64,
// `-a^2` is `-(a^2)`); a sign is allowed at the head of an exponent
// (`2^-1`); `~=` and `!=` are not-equal; `.*`, `./` and `.^` are `*`, `/`,
// `^`.

#pragma once

#include <functional>
#include <set>
#include <string>
#include <string_view>
#include <vector>

#include "lang/ast.hpp"
#include "util/json.hpp"

namespace kompartment {

/// Splits an equation into tokens; throws `EquationSyntaxError` on a character the
/// language does not use.
std::vector<Token> tokenize(std::string_view src);

/// The name tokens that may be references to blocks: a reserved name called as a function
/// is not, nor a name in `skip`.
std::vector<Token> reference_tokens(const std::vector<Token>& tokens, const std::set<std::string>* skip = nullptr);

/// Every name written in an equation, as written, in order (`time` left out). What cannot
/// be tokenized has none.
std::vector<std::string> names_in(const Json& equation);
std::vector<std::string> names_in(std::string_view text);

/// The blocks an equation refers to, as qualified names, resolved from `system`.
std::vector<std::string> references_in(const Json& equation, const std::string& system,
                                       const std::function<bool(const std::string&)>& known,
                                       const std::set<std::string>* skip = nullptr);

/// Says whether a name the function table does not know is a call the model itself
/// defines (a lookup table read at an argument, a user-defined function).
using CallsPredicate = std::function<bool(const std::string&)>;

/// Parses an equation into a tree; empty text is the number 0. Without `calls`, a call of
/// a name the function table does not know is an error.
ENodePtr parse_equation(std::string_view src, const CallsPredicate& calls = nullptr);
/// The same for what a model file holds where an equation is expected (text, a number, null).
ENodePtr parse_equation(const Json& src, const CallsPredicate& calls = nullptr);

/// The names of every block a tree refers to.
void collect_references(std::set<std::string>& out, const ENode& ast);
/// The references of a tree in the order they are met: depth first, left to right.
void collect_in_order(std::vector<std::string>& order, const ENode& ast);
/// Whether a tree calls `time`, anywhere.
bool reads_clock(const ENode& ast);

inline constexpr int MAX_NESTING = 2000;

}  // namespace kompartment
