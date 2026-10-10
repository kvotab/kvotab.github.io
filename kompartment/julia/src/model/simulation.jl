# The simulation settings: their defaults, the solvers and the time units.

"""In the order the application offers them (`SOLVER_IDS` in src/ode/solvers.js)."""
const SOLVER_IDS = ("ndf", "ros23", "dp45", "auto", "auto_julia", "rodas5p", "radau5", "fbdf", "fbdf_krylov", "qndf",
                 "kencarp4", "trbdf2", "rosenbrock23", "tsit5", "vern7", "scipy_bdf", "scipy_radau", "scipy_lsoda")
const DEFAULT_SOLVER = "ndf"
const SPACINGS = ("log", "linear", "series", "solver", "both")
const SERIES_KINDS = ("log", "linear", "times")
const SECONDS_PER_YEAR = 365.25 * 24 * 3600

"""Each time unit as a fraction of a year."""
const TIME_UNITS = Dict("second" => 1 / 31557600, "minute" => 60 / 31557600, "hour" => 3600 / 31557600,
                        "day" => 1 / 365.25, "year" => 1.0)
const SAMPLINGS = ("latin", "random")
const SPLIT_MODES = ("auto", "on", "off")
const MAX_OUTPUT_POINTS = 100000

"""What the application uses when a file leaves a setting out."""
const SIMULATION_DEFAULTS = JDict(
    "start_time" => 0,
    "end_time" => 1e5,
    "output_points" => 250,
    "spacing" => "log",
    "solver" => DEFAULT_SOLVER,
    "rtol" => 1e-3,
    "abstol" => 1e-6,
    "time_unit" => "year",
    "non_negative" => true,
    "iterations" => 1000,
    "seed" => 1,
    "sampling" => "latin",
)

"""The labels the application gives its solvers."""
const SOLVER_LABELS = OrderedDict(
    "ndf" => "stiff, NDF", "ros23" => "stiff, low order, Rosenbrock 2-3", "dp45" => "non-stiff, Dormand-Prince 4-5",
    "auto" => "stiff or non-stiff, switching as it runs",
    "auto_julia" => "stiff or non-stiff, as DifferentialEquations.jl chooses",
    "rodas5p" => "stiff, Rosenbrock 5", "radau5" => "stiff, Radau IIA 5",
    "fbdf" => "stiff, fixed-leading-coefficient BDF", "fbdf_krylov" => "stiff, FBDF by GMRES, no matrix",
    "qndf" => "stiff, quasi-constant-step NDF", "kencarp4" => "stiff, ESDIRK 4",
    "trbdf2" => "stiff, ESDIRK 2 (loose tolerances)",
    "rosenbrock23" => "stiff, low order, Rosenbrock 2-3 as in Julia", "tsit5" => "non-stiff, Tsitouras 5",
    "vern7" => "non-stiff, Verner 7", "scipy_bdf" => "SciPy BDF, stiff",
    "scipy_radau" => "SciPy Radau IIA, stiff", "scipy_lsoda" => "SciPy LSODA, auto-switching",
)
