# A run's results saved as a file: the HDF5 result file the assessment tools
# read, or the table.

const _HDF5_ENDINGS = (".h5", ".hdf5", ".hdf", ".he5")

"""
    save(res::Results, path; blocks=nothing, outputs=nothing, time_origin=0.0, kwargs...) -> path

Writes a run, chosen by the name's ending: `.h5` (`.hdf5`, `.hdf`) as the
HDF5 result file the application's *Export to HDF5* writes, `.csv` as its
table, `.zip` as the model and its run in one archive, as *Save with results*
writes it (the application opens it with the run in place, and so does
[`load_results`](@ref); see `dataset_archive` for its keyword arguments). Every series by default; `blocks` names the blocks whose series
are written, and `outputs` picks series one by one -- descriptors, labels or
1-based positions. A file of two blocks is

    save(res, "out.h5"; blocks=["Soil", "Well"])

`time_origin` is subtracted from the file's `/time` (and the table's time
column), and nothing else: the series and the file's start and end time stay
the run's. The other keyword arguments are [`results_tree`](@ref)'s.
"""
function save(res::Results, path::AbstractString; blocks=nothing, outputs=nothing, time_origin::Real=0.0,
              kwargs...)
    if blocks !== nothing
        outputs === nothing || throw(ArgumentError("give `blocks` or `outputs`, not both"))
        outputs = JDict[]
        for b in (blocks isa AbstractString ? [blocks] : blocks)
            found = select(res, b)
            isempty(found) && throw(ArgumentError("No series of a block '$b' in this run"))
            append!(outputs, found)
        end
    end
    low = lowercase(path)
    if any(e -> endswith(low, e), _HDF5_ENDINGS)
        tree = results_tree(res, outputs; kwargs...)
        if time_origin != 0
            stamp = tree.children["time"]
            stamp.data = Float64.(stamp.data) .- Float64(time_origin)
        end
        write(path, write_hdf5(tree))
    elseif endswith(low, ".zip")
        (blocks === nothing && outputs === nothing && time_origin == 0) ||
            throw(ArgumentError("an archive keeps the whole run: `blocks`, `outputs` and `time_origin` are for a " *
                                "result file or a table"))
        write(path, dataset_archive(res; kwargs...))
    elseif endswith(low, ".csv")
        isempty(kwargs) || throw(ArgumentError("a table takes only `outputs` and `time_origin`"))
        every = Kompartment.outputs(res)
        chosen = outputs === nothing ? nothing : JDict[every[k] for k in _rf_which_of(every, outputs)]
        to_csv(res, path; outputs=chosen, time_origin)
    else
        throw(ArgumentError("'$path': a result file ends .h5 (HDF5), .csv (the table) or .zip (the model and its run)"))
    end
    return path
end
