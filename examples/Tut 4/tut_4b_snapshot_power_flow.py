# Tut 4b: compile a network and solve one snapshot power flow, built with dss_toolkit
# (src/dss_toolkit). The step between tut_4a_network_plot.py (does the network compile and look
# right?) and tut_4_monte_carlo_hosting_capacity.py (the full study): does the network solve, and
# are its voltages, power flows and asset loadings sensible with the loads as written in the files?
#
# Any network: change DATA_FOLDER and MASTER_FILE_NAME (section 1), as in Tut 4a and Tut 4.
#
# What the script does:
#   1. Compiles the master file and reads the network (source, transformers, rated lines, loads).
#   2. Solves one snapshot power flow with the loads as written in the files (times LOAD_MULTIPLIER).
#      If it does not settle with the controls active (regulators, capacitors), it is solved again
#      with the controls fixed at their present settings, and the results say which one was used.
#   3. Saves every result as CSV files and three figures in the results folder. Nothing is shown
#      on the screen; the terminal only says what is happening and where the results are.
#
# Avry Krywolt, November 13, 2026

import shutil
import sys
from pathlib import Path

SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import engine as eng, extract, paths, plots, reports, results as res, topology as topo

# =============================================================================================
# Settings, in selection order
# =============================================================================================
# ---- 1. Network: a folder and a master file (.dss or .txt), nothing else ----------------------
DATA_FOLDER = "HYDRO_DSS"                         # folder name, path from the repo root, or full path
MASTER_FILE_NAME = "Master.dss"          # .dss or .txt master file in DATA_FOLDER
VOLTAGE_BASES_KV = (22.0, 0.4)                     # line-to-line; None = set by the data (e.g. SetkVBase lines)
BUS_COORDINATES_FILE_NAME = "BusCoords.dss"   # 'bus, x, y' list or OpenDSS SetBusXY file; None = none
                                                             # None = no coordinates file
# CRE21 (Team Nando Tutorial 4, its tut_4_data folder in examples/Tut 4/):
#   DATA_FOLDER = "HYDRO_DSS"; MASTER_FILE_NAME = "Master.dss"; VOLTAGE_BASES_KV = (66.0, 22.0, 0.4)
#   BUS_COORDINATES_FILE_NAME = "BusCoords.dss"

# ---- 2. Power flow ---------------------------------------------------------------------------
LOAD_MULTIPLIER = 1.0                                        # 1.0 = every load at the kW / kvar written in the files
CONTROL_MODE = "active"                                      # "active": regulators / capacitors may act; "fixed": they hold
MAX_ITERATIONS = 15                                          # power-flow iterations per solution (OpenDSS default 15)
MAX_CONTROL_ITERATIONS = 1000                                # rounds of control actions before giving up

# ---- 3. Checks -------------------------------------------------------------------------------
VOLTAGE_LIMITS_PU = (0.94, 1.10)                             # nodes and customers outside these are flagged

# ---- 4. Outputs (everything is saved to files) ----------------------------------------------
RESULTS_FOLDER = "results/tut4b"                              # from the repo root; then <network>/snapshot_power_flow/
N_HIGHEST_LOADED_LINES = 10                                  # lines shown in fig02 on large networks (all are in lines.csv)
ANONYMISE_REPORT = False                                     # True: codes instead of names in the terminal text

# =============================================================================================
# 1. Network: compile and read it
# =============================================================================================
anon = reports.Anonymiser(ANONYMISE_REPORT)
project_root = paths.find_project_root(SCRIPT_FOLDER)


def stop(step, error, data_folder=None):
    """Explain which step failed with OpenDSS's own message (names and paths anonymised if asked)."""
    hidden = [data_folder] if data_folder else []
    print(f"\nFAILED at: {step}\n  {type(error).__name__}: {anon.text(error, hidden)}")
    sys.exit(1)


try:
    master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER, start=SCRIPT_FOLDER, verbose=False)
except Exception as error:
    stop("finding the master file", error)
data_folder = master_file.parent
coordinates_file = data_folder / BUS_COORDINATES_FILE_NAME if BUS_COORDINATES_FILE_NAME else None
engine = eng.start_engine()
plots.apply_style()
try:
    eng.build_circuit(engine, str(master_file), VOLTAGE_BASES_KV, bus_coordinates=coordinates_file)
except Exception as error:
    stop("compiling the network (master file, voltage bases, coordinates file)", error, data_folder)
try:
    info = topo.read_network(engine)
except Exception as error:
    stop("reading the network (graph, transformers, lines, loads)", error, data_folder)

network_name = info.circuit_name.lower()
run_folder = project_root / RESULTS_FOLDER / network_name / "snapshot_power_flow"
shutil.rmtree(run_folder, ignore_errors=True)                # fresh results for every run
res.save_settings({"data_folder": DATA_FOLDER, "master_file": MASTER_FILE_NAME, "voltage_bases_kv": VOLTAGE_BASES_KV,
                   "bus_coordinates_file": BUS_COORDINATES_FILE_NAME, "load_multiplier": LOAD_MULTIPLIER,
                   "control_mode": CONTROL_MODE, "max_iterations": MAX_ITERATIONS,
                   "max_control_iterations": MAX_CONTROL_ITERATIONS, "voltage_limits_pu": VOLTAGE_LIMITS_PU},
                  run_folder / "settings.json")
print(f"Network read: {len(info.buses)} buses, {len(info.loads)} loads, {len(info.assets)} monitored assets")

# =============================================================================================
# 2. Snapshot power flow (again with fixed controls if it does not settle)
# =============================================================================================
eng.run_commands(engine, [f"Set LoadMult={LOAD_MULTIPLIER}"])
eng.set_snapshot_mode(engine, MAX_CONTROL_ITERATIONS, MAX_ITERATIONS, CONTROL_MODE)
converged = eng.solve(engine, verbose=False)
used_control_mode = CONTROL_MODE
if not converged and CONTROL_MODE == "active":
    print("The power flow did not settle with the controls active: solving again with them fixed")
    eng.set_snapshot_mode(engine, MAX_CONTROL_ITERATIONS, MAX_ITERATIONS, "fixed")
    converged = eng.solve(engine, verbose=False)
    used_control_mode = "fixed (active did not settle)"
print(f"Power flow {'converged' if converged else 'DID NOT CONVERGE (results below are not a valid solution)'}, "
      f"controls {used_control_mode}")

# =============================================================================================
# 3. Results tables (CSV files)
# =============================================================================================
try:
    results = extract.collect_results(engine, VOLTAGE_LIMITS_PU, info=info)
except Exception as error:
    stop("reading the power flow results", error, data_folder)
tables = reports.snapshot_tables(results, VOLTAGE_LIMITS_PU)
tables["summary"][1].insert(3, ["Control mode", used_control_mode])
tables["summary"][1].insert(4, ["Load multiplier", LOAD_MULTIPLIER])
tables["network_checks"] = (["Status", "Check", "Detail"], reports.network_checks(info))
if results["reg_taps"]:
    tables["regulators"] = (["Regulator", "Tap"], [[name, tap] for name, tap in results["reg_taps"].items()])
saved = res.save_tables(tables, run_folder)

# =============================================================================================
# 4. Figures (saved only)
# =============================================================================================
case = f"loads x {LOAD_MULTIPLIER:g}, controls {used_control_mode}"
plots.save_figure(plots.plot_voltage_profiles([results], [case], VOLTAGE_LIMITS_PU,
                                              title=f"{network_name}: voltage vs distance from the source"),
                  run_folder / "fig01_voltage_profile.png")
plots.save_figure(plots.plot_power_and_loading([results], [case], title=f"{network_name}: power balance and line loading",
                                               max_lines=N_HIGHEST_LOADED_LINES),
                  run_folder / "fig02_power_and_line_loading.png")
plots.save_figure(plots.plot_node_voltages([results], [case], VOLTAGE_LIMITS_PU, title=f"{network_name}: node voltages"),
                  run_folder / "fig03_node_voltages.png")

where = run_folder.relative_to(project_root).as_posix() if not ANONYMISE_REPORT else "results/tut4/<network>/snapshot_power_flow"
print(f"Saved {len(saved)} tables ({', '.join(f'{n}.csv' for n in saved)}) and 3 figures to {where}")
