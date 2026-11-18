#include "lang/parse.hpp"

#include <algorithm>
#include <cstdlib>
#include <unordered_map>
#include <unordered_set>

#include "lang/functions.hpp"
#include "model/names.hpp"
#include "util/jsnum.hpp"

namespace kompartment {

namespace {

inline bool is_digit(unsigned char c) { return c >= '0' && c <= '9'; }
inline bool is_ident_start(unsigned char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'; }
inline bool is_ident_part(unsigned char c) { return is_ident_start(c) || is_digit(c); }

const char* const OPERATORS[] = {"<=", ">=", "==", "~=", "!=", "&&", "||", ".*", "./", ".^",
                                 "+", "-", "*", "/", "^", "<", ">", "?", ":"};

}  // namespace

std::vector<Token> tokenize(std::string_view src) {
    // Positions count characters, as JavaScript's code units do for these texts: a byte
    // that continues a character is not counted.
    const std::size_t n = src.size();
    std::vector<int> char_at(n + 1);
    {
        int count = 0;
        for (std::size_t k = 0; k < n; k++) {
            char_at[k] = count;
            if ((static_cast<unsigned char>(src[k]) & 0xc0) != 0x80) count++;
            else char_at[k] = count - 1;   // a byte that continues a character has its position
        }
        char_at[n] = count;
    }
    auto at = [&](std::size_t k) -> unsigned char { return k < n ? static_cast<unsigned char>(src[k]) : 0; };
    std::vector<Token> tokens;
    std::size_t i = 0;
    while (i < n) {
        unsigned char c = at(i);
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
            i++;
            continue;
        }
        if (is_digit(c) || (c == '.' && is_digit(at(i + 1)))) {
            std::size_t start = i;
            while (i < n && is_digit(at(i))) i++;
            if (at(i) == '.') {
                i++;
                while (i < n && is_digit(at(i))) i++;
            }
            if (at(i) == 'e' || at(i) == 'E') {
                std::size_t save = i;
                i++;
                if (at(i) == '+' || at(i) == '-') i++;
                if (is_digit(at(i))) {
                    while (i < n && is_digit(at(i))) i++;
                } else {
                    i = save;   // "2e" in "2*ex" is not an exponent
                }
            }
            tokens.push_back({Token::Type::Number, std::string(src.substr(start, i - start)), char_at[start]});
            continue;
        }
        if (is_ident_start(c)) {
            std::size_t start = i;
            while (i < n && is_ident_part(at(i))) i++;
            while (at(i) == '.' && is_ident_start(at(i + 1))) {
                i++;
                while (i < n && is_ident_part(at(i))) i++;
            }
            tokens.push_back({Token::Type::Ident, std::string(src.substr(start, i - start)), char_at[start]});
            continue;
        }
        if (c == '(') { tokens.push_back({Token::Type::LParen, "(", char_at[i]}); i++; continue; }
        if (c == ')') { tokens.push_back({Token::Type::RParen, ")", char_at[i]}); i++; continue; }
        if (c == ',') { tokens.push_back({Token::Type::Comma, ",", char_at[i]}); i++; continue; }
        if (c == '[') {
            tokens.push_back({Token::Type::LBracket, "[", char_at[i]});
            i++;
            std::size_t start = i;
            while (i < n && at(i) != ']') i++;
            if (i > start) tokens.push_back({Token::Type::Index, std::string(src.substr(start, i - start)), char_at[start]});
            continue;
        }
        if (c == ']') { tokens.push_back({Token::Type::RBracket, "]", char_at[i]}); i++; continue; }
        const char* op = nullptr;
        for (const char* o : OPERATORS) {
            std::size_t m = std::char_traits<char>::length(o);
            if (i + m <= n && src.compare(i, m, o) == 0) {
                op = o;
                break;
            }
        }
        if (op) {
            tokens.push_back({Token::Type::Op, op, char_at[i]});
            i += std::char_traits<char>::length(op);
            continue;
        }
        // The whole character, however many bytes it takes.
        std::size_t len = 1;
        while (i + len < n && (static_cast<unsigned char>(src[i + len]) & 0xc0) == 0x80) len++;
        throw EquationSyntaxError("Unexpected character '" + std::string(src.substr(i, len)) + "'", char_at[i], std::string(src));
    }
    tokens.push_back({Token::Type::Eof, "<end>", char_at[n]});
    return tokens;
}

std::vector<Token> reference_tokens(const std::vector<Token>& tokens, const std::set<std::string>* skip) {
    std::vector<Token> out;
    for (std::size_t k = 0; k < tokens.size(); k++) {
        const Token& tok = tokens[k];
        if (tok.type != Token::Type::Ident) continue;
        if (k + 1 < tokens.size() && tokens[k + 1].type == Token::Type::LParen && is_reserved_name(tok.text)) continue;
        if (skip && skip->count(tok.text)) continue;
        out.push_back(tok);
    }
    return out;
}

std::vector<std::string> names_in(std::string_view text) {
    std::vector<std::string> out;
    if (text.empty()) return out;
    std::vector<Token> tokens;
    try {
        tokens = tokenize(text);
    } catch (const EquationSyntaxError&) {
        return out;
    }
    for (const Token& t : reference_tokens(tokens))
        if (t.text != "time") out.push_back(t.text);
    return out;
}

std::vector<std::string> names_in(const Json& equation) {
    if (equation.is_null()) return {};
    return names_in(std::string_view(js_str(equation)));
}

std::vector<std::string> references_in(const Json& equation, const std::string& system,
                                       const std::function<bool(const std::string&)>& known,
                                       const std::set<std::string>* skip) {
    std::vector<std::string> out;
    std::string text = equation.is_null() ? "" : js_str(equation);
    if (text.empty()) return out;
    std::vector<Token> tokens;
    try {
        tokens = tokenize(text);
    } catch (const EquationSyntaxError&) {
        return out;
    }
    for (const Token& tok : reference_tokens(tokens, skip)) {
        auto q = resolve_reference(tok.text, system, known);
        if (q) out.push_back(*q);
    }
    return out;
}

// --- the parser ------------------------------------------------------------------------------------

namespace {

const int POWER_PRECEDENCE = 8;

int binary_precedence(const std::string& op) {
    static const std::unordered_map<std::string_view, int> table = {
        {"||", 1}, {"&&", 2}, {"==", 3}, {"~=", 3}, {"<", 4}, {"<=", 4}, {">", 4}, {">=", 4},
        {"+", 5}, {"-", 5}, {"*", 6}, {"/", 6}};
    auto it = table.find(op);
    return it == table.end() ? -1 : it->second;
}

std::string op_alias(const std::string& op) {
    if (op == ".*") return "*";
    if (op == "./") return "/";
    if (op == ".^") return "^";
    if (op == "!=") return "~=";
    return op;
}

std::string trimmed(const std::string& s) {
    // Julia's strip: every Unicode white space; the ASCII ones are what an index holds.
    std::string_view v = js_trim(s);
    return std::string(v);
}

struct Parser {
    std::vector<Token> tokens;
    std::size_t pos = 0;
    std::string text;
    const CallsPredicate& calls;
    int depth = 0;

    const Token& peek() const { return tokens[pos]; }
    Token advance() { return tokens[pos++]; }
    static std::string shown(const Token& t) { return t.type == Token::Type::Eof ? "<end>" : t.text; }

    Token expect(Token::Type kind, const char* what) {
        const Token& tok = peek();
        if (tok.type != kind) throw EquationParseError(std::string("Expected ") + what + " but found '" + shown(tok) + "'", tok.pos, text);
        return advance();
    }

    struct Deeper {
        Parser& p;
        explicit Deeper(Parser& parser) : p(parser) {
            p.depth++;
            if (p.depth > MAX_NESTING) {
                p.depth--;
                throw EquationParseError("This equation is nested too deeply to read. Split it into expression blocks, "
                                         "which is also how anyone else will be able to follow it.", 0, p.text);
            }
        }
        ~Deeper() { p.depth--; }
    };

    std::vector<ENodePtr> args_until_rparen() {
        std::vector<ENodePtr> out;
        if (peek().type != Token::Type::RParen) {
            for (;;) {
                out.push_back(parse_ternary());
                if (peek().type == Token::Type::Comma) {
                    advance();
                    continue;
                }
                break;
            }
        }
        expect(Token::Type::RParen, "')'");
        return out;
    }

    ENodePtr parse_primary() {
        Deeper deeper(*this);
        Token tok = peek();
        if (tok.type == Token::Type::Number) {
            advance();
            double value = std::strtod(tok.text.c_str(), nullptr);
            if (peek().type == Token::Type::LBracket) {
                advance();
                std::string unit = peek().type == Token::Type::Index ? trimmed(advance().text) : "";
                expect(Token::Type::RBracket, "']'");
                return std::make_shared<ENum>(value, unit);
            }
            return std::make_shared<ENum>(value);
        }
        if (tok.type == Token::Type::LParen) {
            advance();
            ENodePtr inner = parse_ternary();
            expect(Token::Type::RParen, "')'");
            return inner;
        }
        if (tok.type == Token::Type::Op && (tok.text == "-" || tok.text == "+")) {
            advance();
            ENodePtr operand = parse_binary(POWER_PRECEDENCE - 1);
            if (tok.text == "-") return std::make_shared<EUnary>("-", operand);
            return operand;
        }
        if (tok.type == Token::Type::Ident) {
            advance();
            const std::string& name = tok.text;
            if (peek().type == Token::Type::LParen) {
                auto fn = lookup_function(name);
                if (!fn) {
                    if (!(calls && calls(name))) throw EquationParseError("Unknown function '" + name + "'", tok.pos, text);
                    advance();
                    return std::make_shared<ECall>(name, args_until_rparen());
                }
                advance();
                std::vector<ENodePtr> args = args_until_rparen();
                long most = fn->max_arity ? *fn->max_arity : -1;
                long got = static_cast<long>(args.size());
                if (got < fn->arity || (most >= 0 && got > most)) {
                    std::string wanted = most < 0 ? "at least " + std::to_string(fn->arity)
                                         : fn->arity == most ? std::to_string(fn->arity)
                                         : std::to_string(fn->arity) + "-" + std::to_string(most);
                    throw EquationParseError("Function '" + name + "' takes " + wanted + " argument(s), got " + std::to_string(got), tok.pos, text);
                }
                return std::make_shared<ECall>(fn->key, std::move(args));
            }
            auto fn = lookup_function(name);
            if (fn && fn->arity == 0) return std::make_shared<ECall>(fn->key, std::vector<ENodePtr>{});
            std::vector<std::optional<std::string>> indices;
            while (peek().type == Token::Type::LBracket) {
                advance();
                std::string idx = peek().type == Token::Type::Index ? trimmed(advance().text) : "";
                expect(Token::Type::RBracket, "']'");
                if (idx.empty()) indices.emplace_back(std::nullopt);
                else indices.emplace_back(std::move(idx));
            }
            return std::make_shared<ERef>(name, std::move(indices));
        }
        throw EquationParseError("Unexpected '" + shown(tok) + "'", tok.pos, text);
    }

    ENodePtr parse_exponent() {
        Token tok = peek();
        if (tok.type == Token::Type::Op && (tok.text == "-" || tok.text == "+")) {
            advance();
            Deeper deeper(*this);
            ENodePtr operand = parse_exponent();
            if (tok.text == "-") return std::make_shared<EUnary>("-", operand);
            return operand;
        }
        return parse_primary();
    }

    ENodePtr parse_power() {
        ENodePtr left = parse_primary();
        while (peek().type == Token::Type::Op && peek().text == "^") {
            advance();
            ENodePtr right = parse_exponent();
            left = std::make_shared<EBinary>("^", left, right);
        }
        return left;
    }

    ENodePtr parse_binary(int min_prec) {
        Deeper deeper(*this);
        ENodePtr left = parse_power();
        for (;;) {
            const Token& tok = peek();
            if (tok.type != Token::Type::Op) break;
            int prec = binary_precedence(tok.text);
            if (prec < 0 || prec < min_prec) break;
            std::string op = tok.text;
            advance();
            ENodePtr right = parse_binary(prec + 1);
            left = std::make_shared<EBinary>(op, left, right);
        }
        return left;
    }

    ENodePtr parse_ternary() {
        Deeper deeper(*this);
        ENodePtr test = parse_binary(1);
        if (peek().type == Token::Type::Op && peek().text == "?") {
            advance();
            ENodePtr then = parse_ternary();
            const Token& colon = peek();
            if (!(colon.type == Token::Type::Op && colon.text == ":"))
                throw EquationParseError("Expected ':' in conditional but found '" + shown(colon) + "'", colon.pos, text);
            advance();
            ENodePtr otherwise = parse_ternary();
            return std::make_shared<ECond>(test, then, otherwise);
        }
        return test;
    }
};

}  // namespace

ENodePtr parse_equation(std::string_view src, const CallsPredicate& calls) {
    if (js_trim(src).empty()) return std::make_shared<ENum>(0.0);
    std::string text(src);
    std::vector<Token> tokens;
    try {
        tokens = tokenize(text);
    } catch (const EquationSyntaxError& e) {
        throw EquationParseError(e.what(), e.position, text);
    }
    for (Token& t : tokens)
        if (t.type == Token::Type::Op) t.text = op_alias(t.text);
    Parser p{std::move(tokens), 0, text, calls, 0};
    ENodePtr ast = p.parse_ternary();
    const Token& trailing = p.peek();
    if (trailing.type != Token::Type::Eof) throw EquationParseError("Unexpected '" + Parser::shown(trailing) + "'", trailing.pos, text);
    return ast;
}

ENodePtr parse_equation(const Json& src, const CallsPredicate& calls) {
    if (src.is_null()) return std::make_shared<ENum>(0.0);
    return parse_equation(std::string_view(js_str(src)), calls);
}

void collect_references(std::set<std::string>& out, const ENode& ast) {
    switch (ast.kind) {
        case ENode::Kind::Ref: out.insert(as_ref(ast).name); break;
        case ENode::Kind::Call:
            for (const auto& a : as_call(ast).args) collect_references(out, *a);
            break;
        case ENode::Kind::Unary: collect_references(out, *as_unary(ast).operand); break;
        case ENode::Kind::Binary:
            collect_references(out, *as_binary(ast).left);
            collect_references(out, *as_binary(ast).right);
            break;
        case ENode::Kind::Cond:
            collect_references(out, *as_cond(ast).test);
            collect_references(out, *as_cond(ast).then);
            collect_references(out, *as_cond(ast).otherwise);
            break;
        default: break;
    }
}

namespace {
void collect_ordered(std::vector<std::string>& order, std::unordered_set<std::string>& seen, const ENode& ast) {
    switch (ast.kind) {
        case ENode::Kind::Ref:
            if (seen.insert(as_ref(ast).name).second) order.push_back(as_ref(ast).name);
            break;
        case ENode::Kind::Call:
            for (const auto& a : as_call(ast).args) collect_ordered(order, seen, *a);
            break;
        case ENode::Kind::Unary: collect_ordered(order, seen, *as_unary(ast).operand); break;
        case ENode::Kind::Binary:
            collect_ordered(order, seen, *as_binary(ast).left);
            collect_ordered(order, seen, *as_binary(ast).right);
            break;
        case ENode::Kind::Cond:
            collect_ordered(order, seen, *as_cond(ast).test);
            collect_ordered(order, seen, *as_cond(ast).then);
            collect_ordered(order, seen, *as_cond(ast).otherwise);
            break;
        default: break;
    }
}
}  // namespace

void collect_in_order(std::vector<std::string>& order, const ENode& ast) {
    std::unordered_set<std::string> seen(order.begin(), order.end());
    collect_ordered(order, seen, ast);
}

bool reads_clock(const ENode& ast) {
    switch (ast.kind) {
        case ENode::Kind::Call: {
            const ECall& c = as_call(ast);
            if (c.name == "time") return true;
            for (const auto& a : c.args)
                if (reads_clock(*a)) return true;
            return false;
        }
        case ENode::Kind::Unary: return reads_clock(*as_unary(ast).operand);
        case ENode::Kind::Binary: return reads_clock(*as_binary(ast).left) || reads_clock(*as_binary(ast).right);
        case ENode::Kind::Cond:
            return reads_clock(*as_cond(ast).test) || reads_clock(*as_cond(ast).then) || reads_clock(*as_cond(ast).otherwise);
        default: return false;
    }
}

}  // namespace kompartment
