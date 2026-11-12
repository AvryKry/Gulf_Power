"""Starting OpenDSS, building a circuit and solving it.

Every brick takes the OpenDSS engine (from start_engine()) as its first argument, so no brick
depends on global variables and the same functions work for any circuit.

A circuit source is either the path of a master file (compiled) or a list of OpenDSS commands
(a circuit written inside the script, e.g. the 3-house network of Team Nando Tutorial 3).
"""
from pathlib import Path

import dss as _dss


def start_engine(allow_forms=False):
    """Return the DSS-Python engine, set so that OpenDSS does not open windows or change
    Python's working folder when it compiles a file."""
    engine = _dss.DSS
    engine.AllowForms = allow_forms
    engine.AllowChangeDir = False
    return engine


def run_commands(engine, commands):
    """Send a list of OpenDSS commands (text) to the engine, in order."""
    for command in commands:
        engine.Text.Command = command


def is_command_list(circuit_source):
    """True if 'circuit_source' is a list of OpenDSS commands rather than a master file path."""
    return isinstance(circuit_source, (list, tuple))


def compile_circuit(engine, circuit_source):
    """Clear OpenDSS and create the circuit: compile a master file (which redirects to all the
    other files), or run a list of commands. Return the circuit name."""
    if is_command_list(circuit_source):
        run_commands(engine, ["Clear", *circuit_source])
    else:
        run_commands(engine, ["Clear", f'Compile "{circuit_source}"'])
    return engine.ActiveCircuit.Name


def set_voltage_bases(engine, voltage_bases_kv):
    """Set the voltage bases (line-to-line kV) and calculate the base of every bus."""
    bases = ", ".join(str(kv) for kv in voltage_bases_kv)
    run_commands(engine, [f"Set VoltageBases=[{bases}]", "CalcVoltageBases"])


DSS_COMMAND_WORDS = ("setbusxy", "setkvbase", "buscoords", "redirect", "compile", "new", "edit", "set", "makebuslist")


def is_dss_command_file(path):
    """True if the first meaningful line of a file is an OpenDSS command (e.g. 'SetBusXY ...'),
    False for a plain 'bus, x, y' list."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            text = line.strip()
            if text and not text.startswith(("!", "//", "#")):
                return text.split()[0].lower().rstrip(",") in DSS_COMMAND_WORDS
    return False


def bus_coordinate_commands(bus_coordinates):
    """Commands that give the buses map coordinates. 'bus_coordinates' is a dict {bus: (x, y)}, a
    plain coordinates file (lines 'bus, x, y'), or a file of OpenDSS commands (e.g. SetBusXY /
    SetkVBase lines, which is how some utility exports write them); the format is detected."""
    if isinstance(bus_coordinates, dict):
        return ["MakeBusList"] + [f"SetBusXY bus={bus} x={x} y={y}" for bus, (x, y) in bus_coordinates.items()]
    path = Path(bus_coordinates)
    if is_dss_command_file(path):
        return ["MakeBusList", f'Redirect "{path}"']
    return ["MakeBusList", f'Buscoords "{path}"']


def apply_bus_coordinates(engine, bus_coordinates):
    """Give the buses map coordinates (see bus_coordinate_commands) and return the number of lines
    skipped because their bus is not in the circuit (common in utility exports, which may list
    buses of parts left out of the model). A file of OpenDSS commands is run one line at a time;
    any other error stops with the file name and line number. A list applies several sources in
    order, e.g. [utility file (with SetkVBase lines), {bus: (x, y)} for the buses it misses]."""
    if isinstance(bus_coordinates, (list, tuple)):
        return sum(apply_bus_coordinates(engine, source) for source in bus_coordinates if source)
    if isinstance(bus_coordinates, dict) or not is_dss_command_file(bus_coordinates):
        run_commands(engine, bus_coordinate_commands(bus_coordinates))
        return 0
    run_commands(engine, ["MakeBusList"])
    skipped = 0
    with open(bus_coordinates, encoding="utf-8", errors="replace") as f:
        for number, line in enumerate(f, start=1):
            text = line.strip()
            if not text or text.startswith(("!", "//", "#")):
                continue
            try:
                engine.Text.Command = text
            except Exception as error:
                if "not found" in str(error).lower():
                    skipped += 1
                    continue
                raise RuntimeError(f"{Path(bus_coordinates).name}, line {number}: {error}") from None
    return skipped


def set_snapshot_mode(engine, max_control_iterations=1000):
    """One power flow, with controls (e.g. regulators) allowed to act before the final solution."""
    run_commands(engine, ["Set ControlMode=static", "Set Mode=snapshot", f"Set MaxControlIter={max_control_iterations}"])


def set_daily_mode(engine, step_minutes, max_control_iterations=1000):
    """Daily mode, one time step per Solve(). Step k uses value k of every daily load shape."""
    run_commands(engine, ["Set ControlMode=static", f"Set Mode=daily number=1 stepsize={step_minutes}m",
                          "Set hour=0", f"Set MaxControlIter={max_control_iterations}"])


def build_circuit(engine, circuit_source, voltage_bases_kv=None, extra_commands=(), bus_coordinates=None):
    """Create the circuit (master file or command list), add/modify elements with
    'extra_commands' (e.g. PV systems or corrections), set the voltage bases (None = leave them to
    the circuit files, e.g. a 'Set VoltageBases' line or per-bus SetkVBase commands) and, if given,
    the bus coordinates (applied last, so per-bus kV bases in a coordinates file are kept).
    Returns the circuit name."""
    name = compile_circuit(engine, circuit_source)
    run_commands(engine, extra_commands)
    if voltage_bases_kv:
        set_voltage_bases(engine, voltage_bases_kv)
    if bus_coordinates:
        apply_bus_coordinates(engine, bus_coordinates)
    return name


def solve(engine, label="", verbose=True):
    """Solve the power flow once. Return True if it converged."""
    solution = engine.ActiveCircuit.Solution
    solution.Solve()
    if verbose:
        state = "converged" if solution.Converged else "DID NOT CONVERGE"
        print(f"Power flow {state}{' - ' + label if label else ''} "
              f"({solution.Iterations} iterations, {solution.ControlIterations} control iterations)")
    return solution.Converged
