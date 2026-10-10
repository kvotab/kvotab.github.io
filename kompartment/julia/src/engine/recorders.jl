# The blocks that remember: min/max, running mean, snapshot, delay -- and
# triggers (src/domain/recorders.js, src/sim/history.js). A remembering block
# is not a function of the state: it keeps (time, value) pairs recorded as the
# solver accepts steps, and reads them back.

const RECORDER_KINDS = ("min_max", "running_mean", "snapshot", "delay", "trigger")
const REMEMBERING_KINDS = ("min_max", "running_mean", "snapshot", "delay")
const RECORDER_COLLECTION = Dict("min_max" => "min_maxes", "running_mean" => "running_means",
                                 "snapshot" => "snapshots", "delay" => "delays", "trigger" => "triggers")
const DIRECTION_SIGN = Dict("rising" => 1, "falling" => -1, "both" => 0)
const EVENT_FIELDS = Dict("min_max" => ("reset_trigger", "start_trigger", "stop_trigger"),
                          "running_mean" => ("reset_trigger", "start_trigger", "stop_trigger"),
                          "snapshot" => ("trigger",), "delay" => (), "trigger" => ())
const EVENT_ACTION = Dict("reset_trigger" => :reset, "start_trigger" => :start, "stop_trigger" => :stop,
                          "trigger" => :snapshot)
const EQUATION_FIELDS = Dict("min_max" => ("target",), "running_mean" => ("target",),
                             "snapshot" => ("target", "initial"), "delay" => ("target", "delay"),
                             "trigger" => ("first", "second"))

"""A growing list of (time, value) pairs, read back by time."""
mutable struct History
    t::Vector{Float64}
    v::Vector{Float64}
end
History() = History(Float64[], Float64[])

Base.length(h::History) = length(h.t)
Base.empty!(h::History) = (empty!(h.t); empty!(h.v); h)
last_time(h::History) = isempty(h.t) ? -Inf : h.t[end]
last_value(h::History) = isempty(h.v) ? 0.0 : h.v[end]

function add!(h::History, time::Float64, value::Float64)
    n = length(h.t)
    if n > 0 && time <= h.t[end]
        h.t[end] = time
        h.v[end] = value
        return
    end
    if n >= 2 && h.v[end] == value && h.v[end-1] == value
        h.t[end] = time
        return
    end
    push!(h.t, time)
    push!(h.v, value)
    return
end

"""The 0-based index of the last time at or before `time`, -1 when there is none."""
function _below(h::History, time::Float64)
    lo, hi = 0, length(h.t) - 1
    (hi < 0 || time < h.t[1]) && return -1
    t = h.t
    while lo < hi
        mid = (lo + hi + 1) >> 1
        if t[mid+1] <= time
            lo = mid
        else
            hi = mid - 1
        end
    end
    return lo
end

function hold(h::History, time::Float64)
    n = length(h.t)
    n == 0 && return 0.0
    time <= h.t[1] && return h.v[1]
    time >= h.t[end] && return h.v[end]
    return h.v[_below(h, time)+1]
end

function lerp(h::History, time::Float64)
    n = length(h.t)
    n == 0 && return 0.0
    time <= h.t[1] && return h.v[1]
    time >= h.t[end] && return h.v[end]
    i = _below(h, time) + 1
    t0, t1 = h.t[i], h.t[i+1]
    t1 == t0 && return h.v[i+1]
    return h.v[i] + ((time - t0) / (t1 - t0)) * (h.v[i+1] - h.v[i])
end

"""One remembering block at one index tuple (`MEM[k]`)."""
mutable struct Recorder
    kind::Symbol                # :min_max, :running_mean, :snapshot, :delay
    history::History
    sign::Int
    starts_recording::Bool
    recording::Bool
    total_time::Float64
    last_time::Float64
    reset_sum::Float64
end
Recorder(kind::AbstractString, operation::AbstractString="max", recording::Bool=true) =
    Recorder(Symbol(kind), History(), operation == "min" ? -1 : 1, recording, recording, 0.0, 0.0, 0.0)

Base.copy(r::Recorder) = Recorder(r.kind, History(copy(r.history.t), copy(r.history.v)), r.sign, r.starts_recording,
                                  r.recording, r.total_time, r.last_time, r.reset_sum)

function prime!(r::Recorder, t0::Float64, seed::Float64)
    empty!(r.history)
    r.recording = r.starts_recording
    r.total_time = 0.0
    r.last_time = t0
    r.reset_sum = 0.0
    if r.kind === :running_mean
        add!(r.history, t0, r.recording ? seed : 0.0)
        return
    end
    add!(r.history, t0, seed)
end

function store!(r::Recorder, t::Float64, current::Float64)
    k = r.kind
    if k === :min_max
        current != last_value(r.history) && add!(r.history, t, current)
    elseif k === :delay
        add!(r.history, t, current)
    elseif k === :running_mean
        if r.recording
            add!(r.history, t, current)
            r.total_time += t - r.last_time
        end
        r.last_time = t
    end
end

function fire!(r::Recorder, what::Symbol, t::Float64, target::Float64, summed::Float64=0.0)
    if what === :snapshot
        add!(r.history, t, target)
    elseif what === :reset
        add!(r.history, t, target)
        if r.kind === :running_mean
            r.reset_sum = summed
            r.total_time = 0.0
            r.last_time = t
        end
    elseif what === :start
        r.recording = true
        r.last_time = t
    elseif what === :stop
        r.recording = false
    end
end

# Python's `max(a, b)` and `min(a, b)`: the first unless the second is strictly beyond it.
@inline py_max(a::Float64, b::Float64) = b > a ? b : a
@inline py_min(a::Float64, b::Float64) = b < a ? b : a

function extreme(r::Recorder, t::Float64, target::Float64)
    t <= last_time(r.history) && return hold(r.history, t)
    r.recording || return last_value(r.history)
    last = last_value(r.history)
    (last != last || target != target) && return NaN       # Math.max / Math.min: NaN wins
    return r.sign > 0 ? py_max(last, target) : py_min(last, target)
end

held(r::Recorder, t::Float64) = hold(r.history, t)
delayed(r::Recorder, t::Float64, lag::Float64) = lerp(r.history, t - lag)
elapsed_at(r::Recorder, t::Float64) = r.recording ? r.total_time + t - r.last_time : r.total_time

function mean_of(r::Recorder, t::Float64, summed::Float64, target::Float64)
    t <= last_time(r.history) && return hold(r.history, t)
    elapsed = elapsed_at(r, t)
    return elapsed > 0 ? (summed - r.reset_sum) / elapsed : target
end
