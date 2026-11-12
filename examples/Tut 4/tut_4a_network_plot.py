# Tut 4a: compile a network and draw it as a zoomable map - nothing else.
# Use it first on any new network data (e.g. a utility export) to check that it compiles, that its
# voltage levels, transformers, lines and loads are read as expected, and that it looks right.
#
#   1. Compile the master file (.dss or .txt) in DATA_FOLDER, set voltage bases and coordinates.
#   2. Print network checks (PASS / WARN / FAIL) using counts only; with ANONYMISE_REPORT = True every
#      name in the printed output is replaced by a code, so the output can be shared safely.
#   3. Give every bus coordinates (from the data, or generated for the buses that have none).
#   4. Save network_map.html: open it in a browser, scroll to zoom, drag to pan, hover for details,
#      click legend entries to hide/show layers. The file is fully offline.
#
# Avry Krywolt, November 11, 2026

import sys
from pathlib import Path

SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import engine as eng, interactive, paths, reports, topology as topo

# =============================================================================================
# Settings
# =============================================================================================
DATA_FOLDER = "HYDRO_DSS"                         # folder name, path from the repo root, or full path
MASTER_FILE_NAME = "Master.dss"          # .dss or .txt master file in DATA_FOLDER
VOLTAGE_BASES_KV = (22.0, 0.4)                     # line-to-line; None = set by the data (e.g. SetkVBase lines)
BUS_COORDINATES_FILE_NAME = "BusCoords.dss"   # 'bus, x, y' list or OpenDSS SetBusXY file; None = none
# CRE21 (Team Nando Tutorial 4):  DATA_FOLDER = "tut_4_data", MASTER_FILE_NAME = "Master.txt",
#                                 VOLTAGE_BASES_KV = (66.0, 22.0, 0.4), BUS_COORDINATES_FILE_NAME = None
ANONYMISE_REPORT = True                           # True: codes instead of names in everything printed
RESULTS_FOLDER = "results/tut4"                    # from the repo root; the map goes in <circuit>/network_map/

# =============================================================================================
# 1. Compile
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
    eng.compile_circuit(engine, str(master_file))
except Exception as error:
    stop("compiling the master file (a file it redirects to may be missing or have a bad line)", error, data_folder)
try:
    if VOLTAGE_BASES_KV:
        eng.set_voltage_bases(engine, VOLTAGE_BASES_KV)
except Exception as error:
    stop("setting the voltage bases", error, data_folder)
try:
    skipped = eng.apply_bus_coordinates(engine, coordinates_file) if coordinates_file else 0
except Exception as error:
    stop("reading the bus coordinates file", error, data_folder)
if skipped:
    print(f"NOTE: {skipped} lines of the coordinates file name buses that are not in the circuit (skipped)")

# =============================================================================================
# 2. Read and check the network
# =============================================================================================
try:
    info = topo.read_network(engine)
except Exception as error:
    stop("reading the network (graph, transformers, lines, loads)", error, data_folder)
coords_share = len(info.coordinates) / max(len(info.buses), 1)
reports.print_network_checks(info, coords_share, anon)
fixed = topo.fixed_loads_table(info)
if fixed:
    reports.print_table(["Load", "Shape", "Found by", "Phase"],
                        [[anon(r["load"], "load"), anon(r["shape"], "shape"), r["found_by"], r["phase"]] for r in fixed[:20]],
                        f"Loads with a fixed shape (first 20 of {len(fixed)})")

# =============================================================================================
# 3. Coordinates for every bus
# =============================================================================================
output_folder = project_root / RESULTS_FOLDER / info.circuit_name.lower() / "network_map"
coords = topo.generate_layout(info)
if coords_share < 0.999:
    topo.save_coordinates(coords, output_folder / "generated_bus_coordinates.csv")
    print(f"\n{len(info.buses) - len(info.coordinates)} buses had no coordinates: positions were generated "
          f"(saved as generated_bus_coordinates.csv; copy it to the data folder and set it as BUS_COORDINATES_FILE_NAME to edit or reuse them)")

# =============================================================================================
# 4. Interactive map
# =============================================================================================
try:
    figure = interactive.network_figure(info, coords, title=f"{info.circuit_name} network")
    map_file = interactive.save_network_html(figure, output_folder / "network_map.html")
except ImportError:
    print("\nFAILED at: drawing the map - the 'plotly' package is missing (pip install plotly)")
    sys.exit(1)
print(f"\nMap saved in the repo folder: {map_file.relative_to(project_root).as_posix() if not ANONYMISE_REPORT else 'results/tut4/<circuit>/network_map/network_map.html'}")
