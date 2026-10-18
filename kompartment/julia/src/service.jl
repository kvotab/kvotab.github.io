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
# tornado's or a sensitivity design's runs; a `replay` one realisation of a
# probabilistic run, as a run. A `calibrate` job searches for the values that meet
# its targets (`calibrate`), saying each step's best as a progress `detail`, and a
# `local-sensitivity` one integrates dy/dp (`run_sensitivity`); each writes its
# answer as JSON. A run asked to be kept (`"keep": true`) is held here, its
# archive without the states, and `series`, `archive` and `forget` ask about it,
# answered on a task of their own beside the jobs. A sample asked to be kept is
# held the same way, its archive without the kept series, and `bands`,
# `realisations`, `column`, `realisation`, `archive` and `forget` ask about it,
# answered as Python's are (see its notes). Each job is a task of its own:
# the engine takes one a thread at once (`concurrent` in `ready`), and the server
# sends it that many. What this engine does not do it refuses before anything
# runs (`NotOnThisEngine`), and the page does it itself.

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
                            "cores" => Sys.CPU_THREADS,
                            # Jobs at once: one a thread, each a task of its own.
                            "concurrent" => max(1, Threads.nthreads()))
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
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "solving"))
            # Each step's best, as JSON carries it to the page: a misfit that is not a number is null.
            step = p -> tell("detail" => OrderedDict{String,Any}("evals" => p.evals, "fx" => p.fx, "best" => p.best,
                                                                 "values" => p.values))
            result = calibrate(m; targets=_service_option(options, "targets", nothing),
                               variables=_service_option(options, "variables", nothing),
                               method=_service_option(options, "method", nothing),
                               max_evals=_service_option(options, "maxEvals", nothing),
                               seed=_service_option(options, "seed", nothing), on_progress=step, signal=stopped)
            stopped() && throw(_ServiceStopped())
            write(string(job["out"]), json_text(result; indent=0))
        elseif kind == "local-sensitivity"
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "solving"))
            r = run_sensitivity(m, _service_option(options, "parameters", nothing);
                                on_progress=(fraction, at) -> begin
                                    tell("fraction" => Float64(fraction), "at" => Float64(at))
                                    !stopped()
                                end)
            stopped() && throw(_ServiceStopped())
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "writing"))
            # Every state the page shows, by its name, with its derivatives.
            states = Any[OrderedDict{String,Any}("name" => s["label"], "y" => r.y[s["offset"]+1],
                                                 "sens" => Any[block[s["offset"]+1] for block in r.sens])
                         for s in r.series if !s["hidden"]]
            write(string(job["out"]), json_text(OrderedDict{String,Any}("t" => r.t, "chosen" => r.chosen,
                                                                        "stats" => r.stats, "states" => states);
                                                indent=0))
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
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "building"))
            blocks = _service_option(options, "blocks", nothing)
            varied = _service_option(options, "varied", nothing)
            tornado = _service_option(options, "tornado", nothing)
            gsa = _service_option(options, "gsa", nothing)
            # A sample the page asked the engine to keep is this machine's to hold, and
            # may come to what the page drew from its memory rather than a tab's limits.
            keeping = _service_option(options, "keep", false) === true && kept !== nothing &&
                      tornado in (nothing, false) && gsa in (nothing, false)
            most = _service_option(options, "most", nothing)
            asked = _service_option(options, "asked", nothing)
            prob = run_probabilistic(m, Int(_service_option(options, "iterations", 100));
                most_bytes=keeping && most isa Real ? Int(most) : PROB_MOST_BYTES,
                asked_bytes=keeping && asked isa Real ? Int(asked) : PROB_MOST_BYTES_ASKED,
                seed=Int(_service_option(options, "seed", 1)),
                latin=_service_option(options, "latin", true) !== false,
                varied=varied === nothing ? nothing : String[string(v) for v in varied],
                keep=blocks === nothing || isempty(blocks) ? nothing : String[string(b) for b in blocks],
                threads=clamp(Int(_service_option(options, "workers", Threads.nthreads())), 1, Threads.nthreads()),
                large=_service_option(options, "large", false) === true,
                # A tornado, or a sensitivity design, in place of a sample.
                tornado=tornado === false ? nothing : tornado,
                gsa=gsa === false ? nothing : gsa,
                on_progress=(done, total) -> begin
                    stopped() && throw(_ServiceStopped())
                    tell("done" => Int(done), "total" => Int(total))
                end)
            say(OrderedDict{String,Any}("id" => id, "event" => "stage", "stage" => "writing"))
            # A sample the page asked the engine to keep goes without its series.
            write(string(job["out"]), sample_archive(prob; series=!keeping))
            keeping && lock(() -> (kept[id] = Dict{String,Any}("sample" => prob)), kept_lock)
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

"""How df/dy was had, as the page's `Results.jacobian` says it (Python's `jacobian_of`)."""
function _service_jacobian(res)
    j = res.system.jacobian
    (j isa JacobianInfo && j.available) ||
        return OrderedDict{String,Any}("available" => false, "reason" => j isa JacobianInfo ? j.reason : nothing)
    common = OrderedDict{String,Any}("colours" => j.colours, "nnz" => j.nnz, "density" => j.density,
                                     "sparse" => get(res.stats, "sparse", false) === true,
                                     "fill" => get(res.stats, "fill", nothing))
    j.budget_rows === nothing || (common["budgetRows"] = j.budget_rows)
    sim = res.project.simulation
    solver = something(get(sim, "solver", nothing), DEFAULT_SOLVER)
    if get(sim, "jacobian", nothing) == "numeric" && "jacobian" in get(_SIM_SOLVER_OPTIONS, solver, ())
        return merge(OrderedDict{String,Any}("available" => false, "asked" => true), common)
    end
    return merge(OrderedDict{String,Any}("available" => true, "constant" => j.constant), common)
end

"""
What the page reads of a run besides its series (the worker's `donePayload`):
the outputs as it lists them, each parameter's one value with it, the nuclides,
the size of the state vector, how df/dy was had and what the zero floor held --
so that it holds a run the engine holds without building the model itself.
"""
function _service_page(res)
    outs = Any[]
    for o in outputs(res)
        d = OrderedDict{String,Any}("kind" => get(o, "kind", nothing), "block" => get(o, "block", nothing),
                                    "nuclide" => get(o, "nuclide", nothing), "dims" => something(get(o, "dims", nothing), Any[]),
                                    "index" => get(o, "index", nothing), "label" => o["label"],
                                    "unit" => get(o, "unit", nothing),
                                    "constant" => get(o, "source", nothing) == "P" ? res.system.P[Int(o["offset"])+1] : nothing)
        get(o, "timeDependent", true) === false && (d["timeDependent"] = false)
        push!(outs, d)
    end
    held = Any[OrderedDict{String,Any}("label" => h.label, "steps" => h.steps, "fraction" => h.fraction)
               for h in held_at_zero(res)]
    return OrderedDict{String,Any}("outputs" => outs, "nuclides" => material_names(res.project),
                                   "stateCount" => isempty(res.y) ? 0 : length(res.y[1]),
                                   "jacobian" => _service_jacobian(res), "heldAtZero" => held)
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
        extra["page"] = _service_page(res)
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
        if haskey(held, "sample")
            _service_sample_answer(op, held["sample"], q)
            say(OrderedDict{String,Any}("id" => id, "event" => "done", "out" => get(q, "out", nothing)))
            return
        end
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
        elseif op in _SERVICE_SAMPLE_QUERIES
            throw(ArgumentError("That run is not a probabilistic run: it has no realisations to ask about."))
        else
            throw(ArgumentError("'$op' is not something this engine is asked"))
        end
    catch e
        say(_service_error(id, e))
        return
    end
    say(OrderedDict{String,Any}("id" => id, "event" => "done", "out" => get(q, "out", nothing)))
end

"""What a kept sample is asked, besides `archive` and `forget`."""
const _SERVICE_SAMPLE_QUERIES = ("bands", "realisations", "column", "realisation")

"""
A question about a kept sample, its answer written to `q["out"]` as
little-endian doubles, laid out as Python's are: a series numbered from 0 as
the sample's meta lists them, the kept series and then each varied parameter.
"""
function _service_sample_answer(op, prob::ProbabilisticResults, q::AbstractDict)
    if op == "archive"
        write(string(q["out"]), sample_archive(prob))
        return
    end
    op in _SERVICE_SAMPLE_QUERIES ||
        throw(ArgumentError("'$op' is not something this engine is asked of a probabilistic run"))
    n = prob.iterations
    count = _an_count(prob)
    parts = Vector{Float64}[]
    if op == "bands"
        mask = get(q, "mask", nothing)
        mask === nothing || length(mask) == n ||
            throw(ArgumentError("The mask has $(length(mask)) entries for $n realisations."))
        for band in bands(prob; percentiles=get(q, "percentiles", nothing), mask)
            append!(parts, band["q"])
            med = band["med"]
            push!(parts, band["mean"], band["sd"].sd, Float64.(band["sd"].n), med["errLo"], med["errHi"],
                  med["bodyLo"], med["bodyHi"])
        end
    else
        asked = something(get(q, "series", nothing), Any[])
        for k in asked
            (k isa Integer && !(k isa Bool) && 0 <= k < count) ||
                throw(ArgumentError("The probabilistic run has no series $(repr(k)): it has $count, from 0."))
        end
        for k in asked
            # Realisations down, the times (one for a varied parameter) across, in
            # the precision they are held in until what was asked is taken out.
            M = k < length(prob.outputs) ? prob.values[k+1] : _an_matrix(prob, k + 1)
            if op == "realisations"
                push!(parts, Float64.(vec(permutedims(M))))
            elseif op == "column"
                push!(parts, Float64.(M[:, clamp(Int(something(get(q, "at", nothing), 0)), 0, size(M, 2) - 1)+1]))
            else
                push!(parts, Float64.(M[clamp(Int(something(get(q, "index", nothing), 0)), 0, n - 1)+1, :]))
            end
        end
    end
    data = isempty(parts) ? Float64[] : reduce(vcat, parts)
    write(string(q["out"]), collect(reinterpret(UInt8, htol.(data))))
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
    # The runs kept for their pages to ask about, by job id: a run's results,
    # or a probabilistic run's sample.
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
                elseif op in ("series", "archive", "forget") || op in _SERVICE_SAMPLE_QUERIES
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
    # Each job a task of its own, as many at once as the server sends -- which
    # is as many as `concurrent` says.
    running = Task[]
    while true
        job = take!(jobs)
        if job === nothing
            # What was asked before the input closed is done and answered first.
            foreach(wait, running)
            wait(answering)
            return
        end
        id = string(get(job, "id", ""))
        stopped = () -> lock(() -> id in cancelled, cancel_lock)
        if stopped()
            say(OrderedDict{String,Any}("id" => id, "event" => "cancelled"))
            continue
        end
        filter!(!istaskdone, running)
        push!(running, Threads.@spawn _service_job(job, say, stopped, kept, kept_lock))
    end
end
