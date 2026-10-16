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
# them; a `probabilistic` one the model and the sample (`sample_archive`), or a
# tornado's runs -- a sensitivity design is refused (`NotOnThisEngine`), and the
# page runs it itself. A run asked to be kept (`"keep": true`) is held here, its archive without the
# states, and `series`, `archive` and `forget` ask about it, answered on a task
# of their own beside the jobs.

const _SERVICE_PROGRESS_EVERY = 0.1

"""A run the page has stopped, raised out of a progress report."""
struct _ServiceStopped <: Exception end

"""
What this engine does not do, said before anything runs: the page does it
itself, in the browser, when it hears this.
"""
struct NotOnThisEngine <: Exception
    message::String
end
Base.showerror(io::IO, e::NotOnThisEngine) = print(io, e.message)

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

"""The mass-balance audit with the names the page reads it by."""
function _service_audit(a)
    a === nothing && return nothing
    family(f) = OrderedDict{String,Any}("name" => f.name, "idle" => f.idle, "unresolved" => f.unresolved,
                                        "floor" => f.floor, "scale" => f.scale, "worst" => f.worst,
                                        "relative" => f.relative, "at" => f.at, "final" => f.final)
    tot = a.total
    OrderedDict{String,Any}("worst" => a.worst, "at" => a.at, "worstFamily" => a.worst_family, "closed" => a.closed,
                            "tolerance" => a.tolerance, "families" => Any[family(f) for f in a.families],
                            "total" => OrderedDict{String,Any}("scale" => tot.scale, "worst" => tot.worst,
                                                               "relative" => tot.relative, "at" => tot.at,
                                                               "final" => tot.final))
end

function _service_option(options, key, default)
    v = options isa AbstractDict ? get(options, key, nothing) : nothing
    return v === nothing ? default : v
end

"""
One job, said as it goes; the last thing said is `done`, `error` or `cancelled`.
A run asked to be kept goes into `kept` under its id.
"""
function _service_job(job::AbstractDict, say, stopped, kept=nothing, kept_lock=ReentrantLock())
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
            _service_write_run(res, job, options, kept, kept_lock)
        elseif kind == "calibrate"
            throw(NotOnThisEngine("Calibration is not on the Julia engine."))
        elseif kind == "local-sensitivity"
            throw(NotOnThisEngine("Local sensitivity is not on the Julia engine."))
        elseif kind == "replay"
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "solving"))
            varied = _service_option(options, "varied", nothing)
            iterations = _service_option(options, "iterations", nothing)
            tornado = _service_option(options, "tornado", nothing)
            r = run_realisation(m, Int(_service_option(options, "index", 0)) + 1;
                seed=Int(_service_option(options, "seed", 1)),
                iterations=iterations === nothing ? nothing : Int(iterations),
                latin=_service_option(options, "latin", true) !== false,
                varied=varied === nothing ? nothing : String[string(v) for v in varied],
                tornado=tornado === false ? nothing : tornado)
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "writing"))
            replayed = OrderedDict{String,Any}("index" => r.number - 1, "iterations" => r.iterations,
                "values" => Any[OrderedDict{String,Any}("name" => v.name, "value" => v.value, "held" => v.held)
                                for v in r.values])
            _service_write_run(r.results, job, options, kept, kept_lock; replayed)
        elseif kind == "probabilistic"
            _service_option(options, "gsa", nothing) === nothing ||
                throw(NotOnThisEngine("Sensitivity designs are not on the Julia engine."))
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "building"))
            blocks = _service_option(options, "blocks", nothing)
            varied = _service_option(options, "varied", nothing)
            tornado = _service_option(options, "tornado", nothing)
            prob = run_probabilistic(m, Int(_service_option(options, "iterations", 100));
                seed=Int(_service_option(options, "seed", 1)),
                latin=_service_option(options, "latin", true) !== false,
                varied=varied === nothing ? nothing : String[string(v) for v in varied],
                keep=blocks === nothing || isempty(blocks) ? nothing : String[string(b) for b in blocks],
                threads=clamp(Int(_service_option(options, "workers", Threads.nthreads())), 1, Threads.nthreads()),
                large=_service_option(options, "large", false) === true,
                tornado=tornado === false ? nothing : tornado,
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
A run's archive -- without its states, and the run kept, when the page asked for
that -- with which realisation it replays, if it replays one.
"""
function _service_write_run(res, job, options, kept, kept_lock; replayed=nothing)
    extra = OrderedDict{String,Any}()
    replayed === nothing || (extra["replayed"] = replayed)
    if _service_option(options, "keep", false) === true && kept !== nothing
        extra["massBalance"] = _service_audit(mass_balance(res))
        write(string(job["out"]), dataset_archive(res; states=false, extra))
        lock(() -> (kept[string(job["id"])] = Dict{String,Any}("results" => res, "labels" => nothing)), kept_lock)
    else
        write(string(job["out"]), dataset_archive(res; extra=isempty(extra) ? nothing : extra))
    end
end

"""A question about a kept run, answered with `done` or `error` under the question's own id."""
function _service_query(q::AbstractDict, kept::AbstractDict, kept_lock, say)
    id = string(get(q, "id", ""))
    op = get(q, "op", nothing)
    run_id = string(get(q, "run", ""))
    try
        if op == "forget"
            lock(() -> delete!(kept, run_id), kept_lock)
            say(OrderedDict{String,Any}("id" => id, "event" => "done"))
            return
        end
        held = lock(() -> get(kept, run_id, nothing), kept_lock)
        held === nothing && throw(ArgumentError("This engine no longer holds that run: it may have been restarted " *
                                                "since, or the run let go of. Run it again."))
        res = held["results"]
        if op == "series"
            asked = get(q, "labels", nothing)
            labels = String[string(x) for x in (asked === nothing ? Any[] : asked)]
            held["labels"] === nothing && (held["labels"] = Set{String}(String(o["label"]) for o in outputs(res)))
            missing_ = [l for l in labels if !(l in held["labels"])]
            isempty(missing_) || throw(ArgumentError("The engine's run has no series called '$(missing_[1])'" *
                                                     (length(missing_) > 1 ? " (nor $(length(missing_) - 1) more)" : "") * "."))
            cols = isempty(labels) ? Vector{Float64}[] : series_many(res, labels)
            data = isempty(cols) ? Float64[] : reduce(vcat, cols)
            write(string(q["out"]), collect(reinterpret(UInt8, htol.(data))))
        elseif op == "archive"
            write(string(q["out"]), dataset_archive(res))
        else
            throw(ArgumentError("'$op' is not something this engine is asked"))
        end
    catch e
        say(_service_error(id, e))
        return
    end
    say(OrderedDict{String,Any}("id" => id, "event" => "done", "out" => get(q, "out", nothing)))
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
    queries = Channel{Any}(Inf)
    cancelled = Set{String}()
    cancel_lock = ReentrantLock()
    # The runs kept for their pages to ask about, by job id.
    kept = Dict{String,Any}()
    kept_lock = ReentrantLock()
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
                elseif op in ("series", "archive", "forget")
                    put!(queries, msg)
                end
            end
        finally
            put!(jobs, nothing)
            put!(queries, nothing)
        end
    end
    Threads.nthreads(:interactive) > 0 ? Threads.@spawn(:interactive, reader()) : Threads.@spawn(reader())
    # Beside the jobs: a page reading one run while the next one solves.
    answering = Threads.@spawn begin
        while true
            q = take!(queries)
            q === nothing && break
            _service_query(q, kept, kept_lock, say)
        end
    end
    say(_service_ready())
    while true
        job = take!(jobs)
        if job === nothing
            # What was asked before the input closed is answered first.
            wait(answering)
            return
        end
        id = string(get(job, "id", ""))
        stopped = () -> lock(() -> id in cancelled, cancel_lock)
        if stopped()
            say(OrderedDict{String,Any}("id" => id, "event" => "cancelled"))
            continue
        end
        _service_job(job, say, stopped, kept, kept_lock)
    end
end
