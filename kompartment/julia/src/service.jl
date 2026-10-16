# The Julia engine behind the application's local server.
#
# `serve.py` in the application's folder serves the page and can hand its runs
# to an engine on the same machine instead of solving them in the browser; this
# is the Julia one. The server starts it once and keeps it:
#
#     julia --project=kompartment/julia --threads=auto,1 -e 'using Kompartment; Kompartment.serve_stdio()'
#
# The protocol is Python's (kompartment/python/kompartment/service.py), word for
# word: a line of JSON per message, jobs and cancels in on standard input,
# `ready`, `stage`, `progress`, `done`, `error` and `cancelled` out on standard
# output, which carries nothing else -- what the engine prints goes to standard
# error. A `run` job writes the model and its run as *Save with results* writes
# them; a `probabilistic` one the model and the sample (`sample_archive`).

const _SERVICE_PROGRESS_EVERY = 0.1

"""A run the page has stopped, raised out of a progress report."""
struct _ServiceStopped <: Exception end

function _service_ready()
    OrderedDict{String,Any}("event" => "ready", "engine" => "julia", "version" => string(pkgversion(@__MODULE__)),
                            "julia" => string(VERSION), "threads" => Threads.nthreads(),
                            "cores" => Sys.CPU_THREADS)
end

function _service_error(id::String, e)
    block = e isa BuildError ? e.block_name : nothing
    hint = hasproperty(e, :hint) ? getproperty(e, :hint) : nothing
    # The message without the type in front of it: the page shows the name beside it.
    message = sprint(showerror, e)
    prefix = "$(nameof(typeof(e))): "
    startswith(message, prefix) && (message = message[ncodeunits(prefix)+1:end])
    hasproperty(e, :message) && getproperty(e, :message) isa AbstractString && (message = getproperty(e, :message))
    OrderedDict{String,Any}("id" => id, "event" => "error", "name" => string(nameof(typeof(e))),
                            "message" => message, "block" => block, "hint" => hint)
end

function _service_option(options, key, default)
    v = options isa AbstractDict ? get(options, key, nothing) : nothing
    return v === nothing ? default : v
end

"""One job, said as it goes; the last thing said is `done`, `error` or `cancelled`."""
function _service_job(job::AbstractDict, say, stopped)
    id = string(get(job, "id", ""))
    kind = get(job, "kind", nothing)
    options = get(job, "options", nothing)
    started = time()
    last = Ref(0.0)
    tell(fields...) = begin
        now_ = time()
        if now_ - last[] >= _SERVICE_PROGRESS_EVERY
            last[] = now_
            say(OrderedDict{String,Any}("id" => id, "event" => "progress", fields...))
        end
    end
    try
        model = get(job, "model", "")
        m = from_json(model isa AbstractString ? model : json_text(model))
        if kind == "run"
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "solving"))
            res = run(m; on_progress=(fraction, at) -> begin
                tell("fraction" => Float64(fraction), "at" => Float64(at))
                !stopped()
            end)
            stopped() && throw(_ServiceStopped())
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "writing"))
            write(string(job["out"]), dataset_archive(res))
        elseif kind == "probabilistic"
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "building"))
            blocks = _service_option(options, "blocks", nothing)
            varied = _service_option(options, "varied", nothing)
            prob = run_probabilistic(m, Int(_service_option(options, "iterations", 100));
                seed=Int(_service_option(options, "seed", 1)),
                latin=_service_option(options, "latin", true) !== false,
                varied=varied === nothing ? nothing : String[string(v) for v in varied],
                keep=blocks === nothing || isempty(blocks) ? nothing : String[string(b) for b in blocks],
                threads=clamp(Int(_service_option(options, "workers", Threads.nthreads())), 1, Threads.nthreads()),
                large=_service_option(options, "large", false) === true,
                on_progress=(done, total) -> begin
                    stopped() && throw(_ServiceStopped())
                    tell("done" => Int(done), "total" => Int(total))
                end)
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "writing"))
            write(string(job["out"]), sample_archive(prob))
        else
            throw(ArgumentError("'$kind' is not a kind of job this engine runs"))
        end
    catch e
        inner = e isa CompositeException && !isempty(e.exceptions) ? e.exceptions[1] : e
        inner isa TaskFailedException && (inner = inner.task.exception)
        if stopped() || inner isa _ServiceStopped || (inner isa SolverError && inner.kind == "aborted")
            say(OrderedDict{String,Any}("id" => id, "event" => "cancelled"))
        else
            say(_service_error(id, inner))
        end
        return
    end
    say(OrderedDict{String,Any}("id" => id, "event" => "done", "out" => string(job["out"]),
                                "ms" => round(Int, (time() - started) * 1000)))
end

"""
    serve_stdio(; input=stdin, output=stdout)

Reads jobs until `input` closes; see the notes at the top of src/service.jl.
Started with an interactive thread (`--threads=auto,1`), the reading goes on
there, so a cancel is heard while every other thread is solving.
"""
function serve_stdio(; input::IO=stdin, output::IO=stdout)
    proto = output
    output === stdout && redirect_stdout(stderr)
    lock_ = ReentrantLock()
    say(event) = lock(lock_) do
        println(proto, json_text(event; indent=0))
        flush(proto)
    end
    jobs = Channel{Any}(Inf)
    cancelled = Set{String}()
    cancel_lock = ReentrantLock()
    reader = () -> begin
        try
            for line in eachline(input)
                isempty(strip(line)) && continue
                msg = try
                    parse_json(line)
                catch
                    continue
                end
                msg isa AbstractDict || continue
                op = get(msg, "op", nothing)
                if op == "cancel"
                    lock(() -> push!(cancelled, string(get(msg, "id", ""))), cancel_lock)
                elseif op == "job"
                    put!(jobs, msg)
                end
            end
        finally
            put!(jobs, nothing)
        end
    end
    Threads.nthreads(:interactive) > 0 ? Threads.@spawn(:interactive, reader()) : Threads.@spawn(reader())
    say(_service_ready())
    while true
        job = take!(jobs)
        job === nothing && return
        id = string(get(job, "id", ""))
        stopped = () -> lock(() -> id in cancelled, cancel_lock)
        if stopped()
            say(OrderedDict{String,Any}("id" => id, "event" => "cancelled"))
            continue
        end
        _service_job(job, say, stopped)
    end
end
