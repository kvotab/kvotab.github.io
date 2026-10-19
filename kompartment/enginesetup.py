"""
What the engines behind serve.py need, whether this machine has it, and help
getting what it lacks.

The page solves its models in the browser and needs nothing. The engines need
their languages: the Python engine a Python 3.9 or newer with NumPy and SciPy
(numba makes it several times quicker, and is optional), the Julia engine
Julia 1.10 or newer with the packages its project lists. serve.py checks at
every start (`python_state`, `julia_state`), says what is missing and how to
get it, and, at a terminal, offers to get it:

- Python: a Python of the engine's own, a virtual environment at
  ~/.kompartment/python made from the Python serve.py runs on, with NumPy,
  SciPy and numba installed into it. Nothing is installed into anybody's own
  Python, and one a system manages (Homebrew's, a Linux distribution's) is
  never asked to take a package. Once it is there, serve.py runs the engine on
  it unless told another (`--python`).
- numba, where the engine runs without it: into the engine's own Python where
  it has one, else by making it one, as above.
- Julia: its official installer (juliaup), which asks its own questions.
- Julia's packages: the project's, resolved, installed and compiled once --
  which is the minute the engine's first start would otherwise take.

A question answered no is remembered (~/.kompartment/serve.json) and not asked
again; `python3 serve.py --setup` sets up whatever is missing without asking.
KOMPARTMENT_HOME puts ~/.kompartment elsewhere.
"""

import json
import os
import shutil
import subprocess
import sys

#: Where what serve.py sets up for the engines lives: a Python of the engine's own,
#: and the questions answered no. Outside the application's folder, which is a checkout.
HOME = os.environ.get("KOMPARTMENT_HOME") or os.path.join(os.path.expanduser("~"), ".kompartment")

#: The Python engine's own Python, a virtual environment.
VENV = os.path.join(HOME, "python")

#: What the Python engine needs, as pip names it; and what makes it quicker.
PYTHON_NEEDS = ["numpy>=1.22", "scipy>=1.8"]
PYTHON_WANTS = ["numba>=0.62"]

#: The oldest Python and Julia the engines run on (python/pyproject.toml, julia/Project.toml).
PYTHON_OLDEST = (3, 9)
JULIA_OLDEST = (1, 10)

#: The oldest Python numba 0.62 installs on: it has no wheel for 3.9.
NUMBA_PYTHON = (3, 10)

#: How Julia is installed, as the people who make it say: juliaup, which asks its own questions.
JULIA_INSTALL = (["winget", "install", "--name", "Julia", "--id", "9NJNWW8PVKMN", "-e", "-s", "msstore"]
                 if os.name == "nt" else ["sh", "-c", "curl -fsSL https://install.julialang.org | sh"])

#: What to type to have serve.py set up what is missing.
SETUP = "python3 serve.py --setup"


def venv_python(folder):
    """The interpreter of the virtual environment in `folder`."""
    return os.path.join(folder, "Scripts", "python.exe") if os.name == "nt" else os.path.join(folder, "bin", "python")


# --- what this machine has -----------------------------------------------------

_PYTHON_PROBE = """
import importlib.util, json, sys
def has(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False
print(json.dumps({"version": list(sys.version_info[:2]), "numpy": has("numpy"), "scipy": has("scipy"),
                  "numba": importlib.util.find_spec("numba") is not None}))
"""


def python_state(python, env=None):
    """What `python` has of what the Python engine needs -- `{"version": [3, 12],
    "numpy": True, "scipy": True, "numba": False}` -- or `{"error": why}` where it
    does not run. NumPy and SciPy are imported, so a broken install counts as none."""
    try:
        done = subprocess.run([python, "-c", _PYTHON_PROBE], env=env, capture_output=True, text=True, timeout=120)
        return json.loads(done.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"could not be started with {python} ({e})"}
    except (ValueError, IndexError):
        return {"error": f"could not be started with {python}"}


def python_lacks(state):
    """What a Python of this state lacks for the engine, said after "the Python
    engine": None where it has everything it needs."""
    if "error" in state:
        return state["error"]
    if tuple(state["version"]) < PYTHON_OLDEST:
        return "needs Python {}.{} or newer, and this is {}.{}".format(*PYTHON_OLDEST, *state["version"])
    missing = [label for name, label in (("numpy", "NumPy"), ("scipy", "SciPy")) if not state.get(name)]
    return f"needs {' and '.join(missing)}" if missing else None


def find_julia(asked="julia"):
    """`asked` where it is a path; else Julia on PATH, or where juliaup and
    Homebrew put it -- which a terminal opened before it was installed, or an
    editor's, may not have on its PATH. None where there is none."""
    if os.path.sep in asked or (os.altsep and os.altsep in asked):
        return asked if os.path.exists(asked) else None
    found = shutil.which(asked)
    if found or asked != "julia":
        return found
    places = [os.path.join(os.path.expanduser("~"), ".juliaup", "bin", "julia.exe" if os.name == "nt" else "julia")]
    if os.name != "nt":
        places += ["/opt/homebrew/bin/julia", "/usr/local/bin/julia"]
    return next((p for p in places if os.path.exists(p)), None)


# Two lines: the version, and the project's packages that are not installed. It
# asks where each would be found, which installs nothing.
_JULIA_PROBE = """
using TOML
deps = TOML.parsefile(joinpath(dirname(Base.active_project()), "Project.toml"))["deps"]
gone = String[n for n in keys(deps)
              if (id = Base.identify_package(n)) === nothing || Base.locate_package(id) === nothing]
println(VERSION)
println(join(sort(gone), ","))
"""


def julia_state(julia, project, env=None):
    """What `julia` has of what the Julia engine needs -- `{"version": "1.13.1",
    "missing": []}`, the packages of `project` it has not installed -- or
    `{"error": why}` where it does not run. A third of a second, installing nothing."""
    try:
        done = subprocess.run([julia, f"--project={project}", "--startup-file=no", "-e", _JULIA_PROBE], env=env,
                              capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"could not be started with {julia} ({e})"}
    lines = done.stdout.strip().splitlines() if done.returncode == 0 else []
    if len(lines) < 1:
        return {"error": f"could not be started with {julia}"}
    version, gone = lines[-2:] if len(lines) >= 2 else (lines[-1], "")
    return {"version": version.strip(), "missing": [n for n in gone.strip().split(",") if n]}


def julia_lacks(state):
    """What a Julia of this state lacks for the engine, said after "the Julia
    engine": None where it has everything it needs."""
    if "error" in state:
        return state["error"]
    try:
        version = tuple(int(x) for x in state["version"].split("-")[0].split(".")[:2])
    except ValueError:
        version = JULIA_OLDEST
    if version < JULIA_OLDEST:
        return "needs Julia {}.{} or newer, and this is {}".format(*JULIA_OLDEST, state["version"])
    if state["missing"]:
        return f"needs its packages, which are not installed ({', '.join(state['missing'])})"
    return None


# --- the questions -------------------------------------------------------------

def _answers():
    return os.path.join(HOME, "serve.json")


def declined():
    """The engines whose setup was declined at an earlier start."""
    try:
        with open(_answers(), encoding="utf-8") as f:
            return set(json.load(f).get("declined", []))
    except (OSError, ValueError, AttributeError):
        return set()


def remember_declined(names):
    try:
        os.makedirs(HOME, exist_ok=True)
        with open(_answers(), "w", encoding="utf-8") as f:
            json.dump({"declined": sorted(names)}, f)
    except OSError:
        pass


def ask(question):
    """A yes from the person at the terminal; anything else is no."""
    try:
        return input(f"  {question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def interactive():
    """Whether somebody is at a terminal to answer: never in a script, a test or a service."""
    return sys.stdin.isatty() and sys.stdout.isatty()


# --- setting up ----------------------------------------------------------------

def set_up_python(base):
    """The Python engine's own Python: a virtual environment made from `base`,
    with NumPy and SciPy, and numba where it installs (it is optional). Its
    interpreter, or None where it could not be made; pip says why as it goes."""
    print(f"  Making a Python for the engine at {VENV}, from {base}")
    if subprocess.run([base, "-m", "venv", VENV]).returncode:
        print("  It could not be made: that Python has no venv module"
              + (" (on Debian and Ubuntu: sudo apt install python3-venv)" if sys.platform.startswith("linux") else ""))
        return None
    python = venv_python(VENV)
    print("  Installing NumPy and SciPy into it")
    if subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", *PYTHON_NEEDS]).returncode:
        print("  NumPy and SciPy did not install: pip's messages above say why")
        return None
    install_numba(python)
    return python


def install_numba(python):
    """numba into `python`, the engine's own: optional, so a failure costs only speed."""
    print("  Installing numba, which makes the engine several times quicker")
    if subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", *PYTHON_WANTS]).returncode:
        print("  numba did not install (pip's messages above say why): the engine runs without it, slower")
        return False
    return True


def install_julia():
    """Julia, by its official installer, which asks its own questions: where it
    put Julia, or None."""
    print(f"  Running {' '.join(JULIA_INSTALL)}")
    if subprocess.run(JULIA_INSTALL).returncode:
        print("  Julia did not install: the installer's messages above say why")
        return None
    found = find_julia("julia")
    if not found:
        print("  Julia is installed, but not where serve.py looks: open a new terminal and start it again,"
              " or pass --julia PATH")
    return found


#: How the Julia engine's packages are installed. The registry first, where there is
#: none: a Julia that has never installed a package has nothing to resolve against,
#: and `Pkg.resolve` -- unlike `Pkg.instantiate` -- does not fetch one. Resolved
#: before installing: a manifest older than the project (a checkout pulled since the
#: packages were last installed) is otherwise installed as it stands, and a package
#: the project has gained since is not.
JULIA_PACKAGES = ("using Pkg; isempty(Pkg.Registry.reachable_registries()) && Pkg.Registry.add(); "
                  "Pkg.resolve(); Pkg.instantiate(); Pkg.precompile()")


def install_julia_packages(julia, project, env=None):
    """The Julia engine's packages, installed and compiled: a few minutes, once."""
    print(f"  Installing the Julia engine's packages and compiling them, a few minutes once ({project})")
    if subprocess.run([julia, f"--project={project}", "--startup-file=no", "-e", JULIA_PACKAGES],
                      env=env).returncode:
        print("  They did not install: Julia's messages above say why")
        return False
    return True


# --- at serve.py's start -------------------------------------------------------

def prepare(python, python_asked, julia, use_python, use_julia, project, setup=False, env=None):
    """The engines' interpreters, and why each cannot be used, after checking
    them -- and, at a terminal or with `setup`, setting up what is missing.

    `python` is the Python asked for (`--python`), else the one serve.py runs
    on (`python_asked` false), in which case the engine's own Python is used
    once there is one. Returns `(python, why, julia, why, notes)`: the
    interpreters, why each engine cannot be used (None where it can) with how
    to get what it lacks, and lines worth saying about the rest.
    """
    said_no = declined()
    answers = {"no": set(said_no), "notes": []}
    asking = interactive()

    def may(name):
        """Whether this start offers to set the engine up: asked to, or at a terminal and not told no before."""
        return setup or (asking and name not in said_no)

    py, py_why = (_python(python, python_asked, setup, may, answers, env) if use_python
                  else (python, "is switched off (--no-python)"))
    jl, jl_why = (_julia(julia, project, setup, asking, may, answers, env) if use_julia
                  else (julia, "is switched off (--no-julia)"))
    if answers["no"] != said_no:
        remember_declined(answers["no"])
    return py, py_why, jl, jl_why, answers["notes"]


def _python(python, asked, setup, may, answers, env):
    """The Python engine's interpreter and why it cannot be used: see `prepare`."""
    own = venv_python(VENV)
    if not asked and os.path.exists(own) and python_lacks(python_state(own, env)) is None:
        python = own
    state = python_state(python, env)
    why = python_lacks(state)
    if why and may("python"):
        print(f"The Python engine {why}" + ("" if "error" in state else f" ({python})") + ".")
        if setup or ask(f"Make it a Python of its own at {VENV}, with NumPy, SciPy and numba -- about 300 MB, "
                        "and nothing installed into your own Python?"):
            answers["no"].discard("python")
            # Made from the Python asked for where it is new enough, else from the one serve.py runs on.
            new_enough = lambda s: "error" not in s and tuple(s["version"]) >= PYTHON_OLDEST  # noqa: E731
            base = python if new_enough(state) else sys.executable
            made = set_up_python(base) if new_enough(python_state(base, env)) else None
            if made is None and not new_enough(python_state(base, env)):
                print("  A Python {}.{} or newer is needed to make one from: pass it with --python".format(
                    *PYTHON_OLDEST))
            if made:
                python, state = made, python_state(made, env)
                why = python_lacks(state)
        else:
            answers["no"].add("python")
    if why:
        return python, f"{why} ({SETUP} sets it up)"
    # A Python named with --python stays the engine's: numba, which it can do
    # without, does not move the engine onto one of its own.
    if not state.get("numba") and (python == own or not asked):
        python, state = _numba(python, own, state, setup, may, answers, env)
    if not state.get("numba"):
        quicker = "Python engine without numba, which makes it several times quicker"
        if tuple(state["version"]) < NUMBA_PYTHON:
            answers["notes"].append("{} and needs Python {}.{} or newer: pass one with --python".format(
                quicker, *NUMBA_PYTHON))
        elif python == own:
            answers["notes"].append(f"{quicker} ({SETUP} installs it)")
        else:
            answers["notes"].append(f"{quicker}: {python} -m pip install numba, or {SETUP}")
    if python == own:
        answers["notes"].append(f"Python engine on its own Python, {VENV}")
    return python, None


def _numba(python, own, state, setup, may, answers, env):
    """numba for an engine that runs without it, offered as Julia's packages are:
    into the engine's own Python where it has one, else by making it one, since
    nothing is installed into anybody's own. Not offered on a Python numba does
    not install on. The interpreter and its state afterwards; a no, or an install
    that failed, is remembered, so that the next start does not ask again."""
    if not may("numba") or tuple(state["version"]) < NUMBA_PYTHON:
        return python, state
    print(f"The Python engine runs without numba, which makes it several times quicker ({python}).")
    if python == own:
        if setup or ask("Install numba into the engine's own Python? A few tens of MB."):
            install_numba(own)
    elif setup or ask(f"Make it a Python of its own at {VENV}, with NumPy, SciPy and numba -- about 300 MB, "
                      "and nothing installed into your own Python?"):
        made = set_up_python(python)
        if made:
            python = made
    state = python_state(python, env)
    if state.get("numba"):
        answers["no"].discard("numba")
    else:
        answers["no"].add("numba")
    return python, state


def _julia(julia, project, setup, asking, may, answers, env):
    """The Julia engine's interpreter and why it cannot be used: see `prepare`."""
    found = find_julia(julia)
    if not found and (os.path.sep in julia or (os.altsep and os.altsep in julia)):
        # Asked for by its path: that one or none, and nothing installed in its place.
        return julia, f"has no Julia at {julia}"
    if not found:
        why = "needs Julia, which is not installed here"
        if may("julia"):
            print(f"The Julia engine {why}.")
            if setup and not asking:
                # Its installer asks questions of its own, which nobody is here to answer.
                answers["notes"].append(f"Julia is installed by: {' '.join(JULIA_INSTALL)}")
            elif setup or ask("Install it with its official installer, juliaup, which asks its own questions?"):
                answers["no"].discard("julia")
                found = install_julia()
            else:
                answers["no"].add("julia")
        if not found:
            return julia, f"{why} ({SETUP} installs it, or pass --julia PATH)"
    state = julia_state(found, project, env)
    why = julia_lacks(state)
    if why and state.get("missing") and may("julia"):
        print(f"The Julia engine {why}.")
        if setup or ask("Install them now, and compile them? A few minutes, once."):
            answers["no"].discard("julia")
            install_julia_packages(found, project, env)
            state = julia_state(found, project, env)
            why = julia_lacks(state)
        else:
            answers["no"].add("julia")
    if why and state.get("missing"):
        why = f"{why} ({SETUP} installs them)"
    return found, why
