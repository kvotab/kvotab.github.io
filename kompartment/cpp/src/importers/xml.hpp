// A small XML reader, the one the Ecolego importer reads model.xml with: a port of the Julia
// package's importers/xml.jl (itself a port of the Python package's `_xml.py` and the
// application's src/io/xml.js), so that a file is read the same way in all of them. The same
// subset of XML -- elements, attributes, text, CDATA, comments, processing instructions,
// declarations skipped, the five predefined entities and numeric character references, and
// nothing else (no namespaces, no DTDs, no entity declarations) -- the same malformed files
// refused with the same message and position, and the same text for every element.
//
// An element's text is every piece of text directly inside it, concatenated; it is kept as
// where its pieces lie in the document and only put together when asked for.

#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace kompartment::eco {

/// A document this reader cannot read. `position` is where it gave up, counted in UTF-16 code
/// units as the application counts, or none.
struct EcoXMLError : std::runtime_error {
    std::string message;
    std::optional<std::size_t> position;
    EcoXMLError(std::string message_, std::optional<std::size_t> position_);
    /// The message with where it gave up, `... (at character 12)`, whole.
    std::string full() const;
};

struct XmlDoc;

/// One element: its name, its attributes (in the order written; a repeated attribute keeps its
/// first place and its last value), its children, and its text.
struct XmlNode {
    const std::string* name = nullptr;
    std::vector<std::pair<std::string, std::string>> attrs;
    std::vector<const XmlNode*> children;
    const XmlDoc* doc = nullptr;
    std::uint32_t tfirst = 0, tlast = 0;   // the text pieces, from 1 (0: none)
    bool self_closing = false;
};

/// A document read: the text, where each element's text lies, and the elements.
struct XmlDoc {
    std::string src;
    std::vector<std::size_t> pstart, pstop;   // a piece's bytes, half-open
    std::vector<std::uint8_t> pkind;          // 0: text with no `&`, 1: text to decode, 2: CDATA
    std::vector<std::uint32_t> pnext;         // the element's next piece (0: none)
    std::deque<XmlNode> nodes;
    std::unordered_set<std::string> names;
    const XmlNode* root = nullptr;
};

/// Reads a document. Throws EcoXMLError for what it cannot read, with the application's message.
std::unique_ptr<XmlDoc> parse_xml(std::string src);

/// The five predefined entities and numeric character references decoded; anything else left as
/// written.
std::string decode_entities(std::string_view text);

/// The element's text: every piece directly inside it, concatenated, entities decoded (CDATA as
/// written).
std::string text(const XmlNode& n);

/// `js_trim(text(n))`.
std::string trimmed_text(const XmlNode& n);

/// The attribute `key`, or none.
std::optional<std::string> attr(const XmlNode& n, std::string_view key);
/// The attribute `key`, or `fallback`.
std::string attr_or(const XmlNode& n, std::string_view key, std::string_view fallback);
bool has_attr(const XmlNode& n, std::string_view key);

/// The first direct child called `name`, or null.
const XmlNode* child(const XmlNode* node, std::string_view name);
/// Every direct child called `name`.
std::vector<const XmlNode*> children(const XmlNode* node, std::string_view name);
/// The text of the first child called `name`, trimmed, or none when there is no such child or
/// its text is blank.
std::optional<std::string> child_text(const XmlNode* node, std::string_view name);
/// A child's text as a finite number, or none.
std::optional<double> child_number(const XmlNode* node, std::string_view name);
/// Whether a child's text is `true` (in any case, as Python lowers it); none when there is none.
std::optional<bool> child_bool(const XmlNode* node, std::string_view name);

/// Every element under `node`, `node` first, depth first in document order, until `f` says stop
/// (returns true).
void walk(const XmlNode& node, const std::function<bool(const XmlNode&)>& f);
/// The first element anywhere under `node` (`node` included) called `name`, or null.
const XmlNode* find(const XmlNode& node, std::string_view name);

}  // namespace kompartment::eco
