"""Starting OpenDSS, building a circuit and solving it.

Every brick takes the OpenDSS engine (from start_engine()) as its first argument, so no brick
depends on global variables and the same functions work for any circuit.
"""
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


def compile_circuit(engine, master_file):
    """Clear OpenDSS and compile the master file (which redirects to all the other files).
    Return the circuit name."""
    run_commands(engine, ["Clear", f'Compile "{master_file}"'])
    return engine.ActiveCircuit.Name


def set_voltage_bases(engine, voltage_bases_kv):
    """Set the voltage bases (line-to-line kV) and calculate the base of every bus."""
    bases = ", ".join(str(kv) for kv in voltage_bases_kv)
    run_commands(engine, [f"Set VoltageBases=[{bases}]", "CalcVoltageBases"])


def set_snapshot_mode(engine, max_control_iter=1000):
    """One power flow, with controls (e.g. regulators) allowed to act before the final solution."""
    run_commands(engine, ["Set ControlMode=static", "Set Mode=snapshot", f"Set MaxControlIter={max_control_iter}"])


def set_daily_mode(engine, step_minutes, max_control_iter=1000):
    """Daily mode, one time step per Solve(). Step k uses value k of every daily load shape."""
    run_commands(engine, ["Set ControlMode=static", f"Set Mode=daily number=1 stepsize={step_minutes}m",
                          "Set hour=0", f"Set MaxControlIter={max_control_iter}"])


def build_circuit(engine, master_file, voltage_bases_kv, extra_commands=()):
    """Compile the circuit, add/modify elements with 'extra_commands' (e.g. PV systems or
    corrections), then set the voltage bases. Return the circuit name."""
    name = compile_circuit(engine, master_file)
    run_commands(engine, extra_commands)
    set_voltage_bases(engine, voltage_bases_kv)
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
