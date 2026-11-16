# Tut 4c: troubleshoot network data on a map - compile, solve one snapshot power flow, and draw the
# network with lenses that colour every bus, line and transformer by how far it is from normal.
# Combines Tut 4a (compile + map) and Tut 4b (snapshot power flow); built with dss_toolkit.
#
# Any network: change DATA_FOLDER and MASTER_FILE_NAME (section 1), as in Tut 4a and 4b.
#
# What the script does:
#   1. Compiles the master file and reads the network: every voltage source (any number), the
#      areas each one feeds, transformer classes (head, substation, distribution, regulator,
#      step-up) and devices (capacitors, fuses, reclosers, switches, regulators).
#   2. Solves one snapshot power flow (as in Tut 4b, again with fixed controls if it does not settle).
#   3. Saves network_map.html: open it in a browser. The panel beside the map picks a mode
#      (names and phases, voltage / current / power / power factor / losses lenses, devices) and
#      ticks element types and value bands on and off. Changing mode keeps the zoom, so a problem
#      found in a lens can be zoomed into and identified in "Names and phases".
#   4. Saves three short tables: sources.csv (one row per source), out_of_range.csv (only the
#      elements at the far ends: above 110 % of their rating or nominal voltage, or not energized)
#      and loading_by_code.csv (loading of each line / transformer code: how many at 0 %, below
#      10 %, above 110 %, median and highest).
#
# Avry Krywolt, November 14, 2026

import shutil
import sys
from pathlib import Path

SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import engine as eng, extract, interactive, paths, reports, results as res, topology as topo

# =============================================================================================
# Settings, in selection order
# =============================================================================================
# ---- 1. Network: a folder and a master file (.dss or .txt), nothing else ----------------------
DATA_FOLDER = "tut_4_data"                         # folder name, path from the repo root, or full path
MASTER_FILE_NAME = "Master.txt"          # .dss or .txt master file in DATA_FOLDER
VOLTAGE_BASES_KV = (22.0, 0.4)                     # line-to-line; None = set by the data (e.g. SetkVBase lines)
BUS_COORDINATES_FILE_NAME = None   # 'bus, x, y' list or OpenDSS SetBusXY file; None = none
# CRE21 (Team Nando Tutorial 4, its tut_4_data folder in examples/Tut 4/):
#   DATA_FOLDER = "tut_4_data"; MASTER_FILE_NAME = "Master.txt"; VOLTAGE_BASES_KV = (66.0, 22.0, 0.4)
#   BUS_COORDINATES_FILE_NAME = None

# ---- 2. Devices: .dss files in DATA_FOLDER whose elements are shown as devices --------------
DEVICE_FILE_NAMES = {"capacitor": "Capacitors.dss", "fuse": "Fuses.dss", "recloser": "Reclosers.dss",                           "switch": "Switches.dss"}                                       # {kind: file}; kinds: capacitor, fuse, recloser, switch
# e.g. DEVICE_FILE_NAMES = {"capacitor": "Capacitors.dss", "fuse": "Fuses.dss", "recloser": "Reclosers.dss",
#                           "switch": "Switches.dss"}
# Found without files: Capacitor elements, regulators (transformers driven by a RegControl, or 1:1),
# lines marked Switch=yes, Fuse / Recloser / SwtControl objects, and those words in line names.
HEAD_TRANSFORMERS = None                                     # None = found automatically; or a list of transformer names

# ---- 3. Power flow (as in Tut 4b) -------------------------------------------------------------
LOAD_MULTIPLIER = 1.0                                        # 1.0 = every load at the kW / kvar written in the files
CONTROL_MODE = "active"                                      # "active": regulators / capacitors may act; "fixed": they hold
MAX_ITERATIONS = 15                                          # power-flow iterations per solution (OpenDSS default 15)
MAX_CONTROL_ITERATIONS = 1000                                # rounds of control actions before giving up

# ---- 4. Lens bands ----------------------------------------------------------------------------
VOLTAGE_LIMITS_PU = (0.94, 1.10)                             # voltage lens bands are built around these
LOADING_BANDS = interactive.LOADING_BANDS                    # current and power lenses (% of rating); edit to change
PF_BANDS = interactive.PF_BANDS
LOSS_BANDS = interactive.LOSS_BANDS
# The far ends of every lens start below 10 % and above 110 % of nominal (rating or voltage).

# ---- 5. Outputs (everything is saved to files) ----------------------------------------------
RESULTS_FOLDER = "results/tut4c"                              # from the repo root; then <network>/troubleshooting/
ANONYMISE_REPORT = False                                     # True: codes instead of names in the terminal text

# =============================================================================================
# 1. Network: compile and read it (sources, transformer classes, devices)
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
try:
    eng.build_circuit(engine, str(master_file), VOLTAGE_BASES_KV, bus_coordinates=coordinates_file)
except Exception as error:
    stop("compiling the network (master file, voltage bases, coordinates file)", error, data_folder)
try:
    info = topo.read_network(engine, device_files={kind: data_folder / name for kind, name in DEVICE_FILE_NAMES.items()},
                             head_transformers_override=HEAD_TRANSFORMERS)
except Exception as error:
    stop("reading the network (sources, graph, transformers, devices, loads)", error, data_folder)

network_name = info.circuit_name.lower()
run_folder = project_root / RESULTS_FOLDER / network_name / "troubleshooting"
shutil.rmtree(run_folder, ignore_errors=True)                # fresh results for every run
res.save_settings({"data_folder": DATA_FOLDER, "master_file": MASTER_FILE_NAME, "voltage_bases_kv": VOLTAGE_BASES_KV,
                   "bus_coordinates_file": BUS_COORDINATES_FILE_NAME, "device_files": DEVICE_FILE_NAMES,
                   "head_transformers": HEAD_TRANSFORMERS, "load_multiplier": LOAD_MULTIPLIER, "control_mode": CONTROL_MODE,
                   "max_iterations": MAX_ITERATIONS, "max_control_iterations": MAX_CONTROL_ITERATIONS,
                   "voltage_limits_pu": VOLTAGE_LIMITS_PU, "loading_bands": LOADING_BANDS, "pf_bands": PF_BANDS,
                   "loss_bands": LOSS_BANDS}, run_folder / "settings.json")
heads = sum(1 for a in info.assets if a.kind == "head_transformer")
print(f"Network read: {len(info.buses)} buses, {len(info.sources)} sources, {heads} head transformers, "
      f"{len(info.devices)} devices, {len(info.source_ties)} ties between sources' areas")
for note in info.device_notes:
    print(f"NOTE: {anon.text(note, [data_folder])}")

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
print(f"Power flow {'converged' if converged else 'DID NOT CONVERGE (the map shows an invalid solution)'}, "
      f"controls {used_control_mode}")
try:
    results = extract.collect_results(engine, VOLTAGE_LIMITS_PU, info=info)
except Exception as error:
    stop("reading the power flow results", error, data_folder)

# =============================================================================================
# 3. Map with every mode (saved only; open network_map.html in a browser)
# =============================================================================================
case = ("loads as in the files" if LOAD_MULTIPLIER == 1 else f"loads x {LOAD_MULTIPLIER:g}") + ", " + (
    "regulators and capacitors allowed to act" if used_control_mode == "active" else "regulators and capacitors held")
coords = topo.generate_layout(info)
figure = interactive.network_figure(info, coords, f"{network_name}: {case}", results=results, limits=VOLTAGE_LIMITS_PU,
                                    bands={"current": LOADING_BANDS, "power": LOADING_BANDS, "pf": PF_BANDS,
                                           "losses": LOSS_BANDS})
interactive.save_network_html(figure, run_folder / "network_map.html")

# =============================================================================================
# 4. Three short tables (CSV files)
# =============================================================================================
saved = res.save_tables({"sources": reports.sources_table(info, results),
                         "out_of_range": reports.out_of_range_table(info, results),
                         "loading_by_code": reports.loading_by_code_table(info, results)}, run_folder)
where = run_folder.relative_to(project_root).as_posix() if not ANONYMISE_REPORT else "results/tut4/<network>/troubleshooting"
print(f"Saved network_map.html and {', '.join(f'{n}.csv' for n in saved)} to {where}")
