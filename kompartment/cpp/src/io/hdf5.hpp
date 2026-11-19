// Writing HDF5 as Kompartment writes it, byte for byte: the Julia package's
// io/hdf5.jl (the Python package's `kompartment/io/hdf5.py`, the application's
// `src/io/hdf5.js`). The same narrow writer -- groups, datasets of doubles,
// singles, 32-bit integers and strings, attributes on both -- laying out the
// same tree in the same bytes, so a file written here is the file the
// application and the other engines write:
//
//     auto root = h5_group(H5Attrs{{"model", Json("Two boxes")}});
//     h5_put(*root, {"time"}, h5_dataset(std::vector<double>{0, 1, 2}, H5Type::F64, H5Attrs{{"unit", Json("year")}}));
//     h5_put(*root, {"IndexLists", "Radionuclides"}, h5_dataset(Json::array({Json("Cs-137"), Json("H-3")}), H5Type::STR));
//     h5_put(*root, {"Soil", "Cs-137"}, h5_dataset(std::vector<double>{1.0, 0.9, 0.8}));
//     std::string bytes = write_hdf5(*root);
//
// **Which HDF5.** Version 2 object headers with a group's links held in the
// header itself ("compact" storage), which needs no B-tree: a link is a
// message, and a group of four hundred children is four hundred messages.
// Every version 2 structure ends in a Jenkins lookup3 checksum (`lookup3`).
// libhdf5 has read and written these since 1.8; h5py, h5ls, h5dump and the
// result browser's h5wasm open them.
//
// **Strings** are variable-length UTF-8 in a global heap collection, pooled:
// `TRUE` is in the file once however many datasets say it. A boolean attribute
// is written as the string `TRUE` or `FALSE`, which is what Ecolego's own files
// hold. A string that is not UTF-8 is written as `TextEncoder` writes it
// (`h5_utf8`).
//
// **The tree** is made of `H5Group` and `H5Dataset` nodes put together with
// `h5_put`. Children are written in the order they were put, which is what
// keeps a result file's nuclides in the model's order. Attributes are written
// in the order JavaScript lists an object's keys: keys that are array indices
// (`"0"`, `"17"`) first, in numeric order, then the rest in the order they were
// first set. An attribute whose value is null is not written.
//
// Values are converted as the application converts them: a value that is not a
// number is turned into one as JavaScript's `Number()` would (null is 0, a
// numeric string its number, anything else NaN), a float32 dataset rounds to
// nearest, an int32 dataset wraps as JavaScript's `Int32Array` does (after the
// value has become a double, as every JavaScript number is), and text is
// written as `String()` writes it. A dataset's values are doubles, singles, or
// any JSON values: a list's items, a string's characters, a dictionary's keys
// (anything else holds none, as a bare number does in the application).
//
// References: the HDF5 File Format Specification version 3.0, sections III.A
// (superblock version 2), IV.A (object headers version 2 and their messages)
// and III.E (global heap). The checksum is `H5_checksum_lookup3` from
// `H5checksum.c`.

#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>
#include <initializer_list>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

#include "util/json.hpp"

namespace kompartment {

/// A tree that cannot be written (Julia's `HDF5Error`): a name with a slash in it, two
/// things at one path, a shape that does not match its values, a root that is not a group.
struct HDF5Error : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// The datatypes the writer knows: IEEE doubles (a result series), IEEE singles (a
/// probabilistic result's realisations), signed 32-bit integers (counts), and
/// variable-length UTF-8 strings held in the global heap.
enum class H5Type : std::uint8_t { F64, F32, I32, STR };

/// The bytes one value of a type takes in a dataset (a string's 16 are its heap ID).
std::size_t h5_type_size(H5Type t) noexcept;

/// A node's attributes: names and values in the order the names were first set -- setting
/// one again keeps its place, as a JavaScript object does. A result file has hundreds of
/// thousands of these, each with the same names, so the names may be shared between them
/// (and are copied before one set of them changes).
class H5Attrs {
public:
    H5Attrs() = default;
    H5Attrs(std::initializer_list<std::pair<std::string, Json>> items);
    /// Attributes with these names, shared with others of the same shape, and these values.
    H5Attrs(std::shared_ptr<const std::vector<std::string>> names, std::vector<Json> values);

    std::size_t size() const noexcept { return values_.size(); }
    bool empty() const noexcept { return values_.empty(); }
    const std::string& name(std::size_t i) const { return (*names_)[i]; }
    const Json& value(std::size_t i) const { return values_[i]; }
    /// The value of a name, or none.
    const Json* find(std::string_view name) const noexcept;
    bool has(std::string_view name) const noexcept { return find(name) != nullptr; }
    /// Sets a value: a new name goes last, a name already there keeps its place.
    void set(std::string_view name, Json value);
    /// Removes a name; whether it was there.
    bool erase(std::string_view name);

private:
    std::ptrdiff_t slot(std::string_view name) const noexcept;
    std::vector<std::string>& own_names();

    std::shared_ptr<const std::vector<std::string>> names_;
    bool own_ = false;   // `names_` was made here (and is changed only while no other holds it)
    std::vector<Json> values_;
};

/// A node of a tree: an `H5Group` or an `H5Dataset`.
class H5Node {
public:
    virtual ~H5Node() = default;
    bool is_group() const noexcept { return group_; }
    H5Attrs attrs;

protected:
    H5Node(bool group, H5Attrs a) : attrs(std::move(a)), group_(group) {}

private:
    bool group_;
};
using H5Ptr = std::shared_ptr<H5Node>;

/// A group: attributes, and children by name, kept -- and written -- in the order they were put.
class H5Group : public H5Node {
public:
    explicit H5Group(H5Attrs a = {}) : H5Node(true, std::move(a)) {}
    const std::vector<std::pair<std::string, H5Ptr>>& children() const noexcept { return children_; }
    /// The child of that name, or none.
    H5Node* child(std::string_view name) const noexcept;
    /// Adds a child last; false, and nothing changed, when the name is taken. (`h5_put` is how
    /// a tree is put together; a name added here is not checked.)
    bool add(std::string name, H5Ptr node);

private:
    struct NameHash {
        using is_transparent = void;
        std::size_t operator()(std::string_view s) const noexcept { return std::hash<std::string_view>{}(s); }
    };
    std::vector<std::pair<std::string, H5Ptr>> children_;
    std::unordered_map<std::string, std::size_t, NameHash, std::equal_to<>> index_;
};

/// A dataset: its values, their type, attributes, and its dimensions -- none for a plain list.
class H5Dataset : public H5Node {
public:
    /// Doubles, singles, or JSON values as the application would read them: a list's items, a
    /// string's characters, a dictionary's keys; any other value holds none.
    using Data = std::variant<std::vector<double>, std::vector<float>, Json>;

    H5Dataset(Data d, H5Type type, H5Attrs a, std::optional<std::vector<Json>> dimensions)
        : H5Node(false, std::move(a)), data(std::move(d)), dt(type), dims(std::move(dimensions)) {}

    Data data;
    H5Type dt;
    /// The dimensions, each read as JavaScript's `Number()` reads it (`[times, realisations]`
    /// for a probabilistic result; `[]` for a single value written as a scalar); none for a list.
    std::optional<std::vector<Json>> dims;

    /// How many values it holds.
    std::size_t count() const;
};

/// A group with these attributes.
std::shared_ptr<H5Group> h5_group(H5Attrs attrs = {});

/// A dataset (`h5dataset`). The values are given flat, the last dimension varying fastest:
/// with `dims = [times, realisations]`, value `t * n + r` is realisation `r` at time `t` (both
/// from 0). Refused (`HDF5Error`) when the dimensions do not multiply out to the number of
/// values.
std::shared_ptr<H5Dataset> h5_dataset(std::vector<double> data, H5Type dt = H5Type::F64, H5Attrs attrs = {},
                                      std::optional<std::vector<Json>> dims = std::nullopt);
std::shared_ptr<H5Dataset> h5_dataset(std::vector<float> data, H5Type dt = H5Type::F32, H5Attrs attrs = {},
                                      std::optional<std::vector<Json>> dims = std::nullopt);
std::shared_ptr<H5Dataset> h5_dataset(Json data, H5Type dt = H5Type::F64, H5Attrs attrs = {}, std::optional<std::vector<Json>> dims = std::nullopt);

/// Puts `node` at `path` in `root`, making the groups on the way (`h5put`); empty names are
/// skipped. A name with a slash in it is refused -- the one character HDF5 keeps for itself --
/// and so is a second thing at one path, anything put inside a dataset, and a path with no
/// name in it (`HDF5Error`).
H5Ptr h5_put(H5Group& root, const std::vector<std::string>& path, H5Ptr node);

/// The file, as bytes (`write_hdf5`). For the same tree they are the other engines', to the
/// byte. Refused (`HDF5Error`) when the root is not a group or a link has an empty name.
std::string write_hdf5(const H5Node& root);

/// Jenkins' lookup3 over `data`, as `H5_checksum_lookup3` calls it, with an initial value of
/// zero: every version 2 structure ends in four bytes of it over everything before it.
std::uint32_t lookup3(std::string_view data) noexcept;
/// Over `len` bytes from `start` (from 0); bytes past the end of `data` read as zeros.
std::uint32_t lookup3(std::string_view data, std::size_t start, std::size_t len);

/// Text as `TextEncoder` writes it, as the Julia package has it (`_h5_utf8`): UTF-8 as it is;
/// a surrogate pair (each half written as Julia's `Char` writes one) the character it makes,
/// a lone surrogate -- or bytes that are not UTF-8 at all -- U+FFFD. An overlong form is
/// refused (a `JuliaError` of kind `InvalidCharError`), as the Julia package refuses it.
std::string h5_utf8(const std::string& s);

/// A string's characters as Julia iterates them, each as the bytes it is made of: UTF-8
/// characters, and the pieces of what is not UTF-8 as Julia cuts them.
std::vector<std::string> julia_chars(std::string_view s);

}  // namespace kompartment
