// Bytes as text, as the Python port of the Ecolego importer decodes them (the Julia package's
// importers/eco_text.jl): CPython's UTF-8 and UTF-16 decoders with `errors='replace'` (one
// U+FFFD for each maximal ill-formed subpart, as the browser's `TextDecoder` does too), and the
// message of the `UnicodeDecodeError` its strict UTF-8 decoder raises.

#pragma once

#include <stdexcept>
#include <string>
#include <string_view>

namespace kompartment::eco {

/// What CPython's strict UTF-8 decoder raises, with its message.
struct EcoDecodeError : std::runtime_error {
    std::string message;
    explicit EcoDecodeError(const std::string& m) : std::runtime_error(m), message(m) {}
};

/// Whether bytes are UTF-8 as Julia's `isvalid(String, ...)` has it (no overlong forms, no
/// surrogates, nothing past U+10FFFF).
bool is_valid_utf8(std::string_view bytes);

/// `bytes.decode('utf-8', 'replace')`.
std::string utf8_replace(std::string_view bytes);

/// `bytes.decode('utf-8')`; EcoDecodeError with CPython's message for bytes that are not UTF-8.
std::string utf8_strict(std::string_view bytes);

/// `bytes[start:].decode('utf-16-be' or 'utf-16-le', 'replace')` as CPython decodes it.
std::string utf16_replace(std::string_view bytes, std::size_t start, bool little_endian);

/// The text less one leading byte-order mark.
std::string without_bom(std::string text);

/// XML bytes as text, honouring a byte-order mark: UTF-16 big-endian or little-endian, or UTF-8
/// with or without one; undecodable bytes become U+FFFD, and one further byte-order mark after
/// the first is dropped too.
std::string decode_xml_bytes(std::string_view bytes);

}  // namespace kompartment::eco
