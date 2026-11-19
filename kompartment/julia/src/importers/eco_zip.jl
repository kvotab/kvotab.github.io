# The entries of an Ecolego archive (.eco, .eas): read as the application reads
# an archive (`read_zip`, util/zip.jl), what cannot be read an `EcoImportError`
# in its words.

"""The most one entry, and the whole archive, may expand to."""
const _ECO_MAX_INFLATED = ZIP_MAX_INFLATED

"""The entries of a ZIP archive; [`EcoImportError`](@ref) for one that cannot be read."""
_eco_unzip(data::Vector{UInt8}) = read_zip(data; error=EcoImportError)
_eco_names(a::ZipEntries) = zip_names(a)
_eco_get(a::ZipEntries, name::String) = a[name]

# Raw deflate as the reader inflates it: the output (at most `max_length` bytes),
# whether the stream ended, and zlib's message for damage (`nothing` for none).
_eco_raw_inflate(src::AbstractVector{UInt8}, max_length::Int, size_hint::Int) = _zip_raw_inflate(src, max_length, size_hint)
