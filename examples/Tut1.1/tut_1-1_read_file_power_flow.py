# This code adapts from tut_1_alternate....py and reads in parsed .dss files from 
# the IEEE 13-node network to make the comparison with the same grid with PV integration
# Power systems are created using imported .dss files FROM the ditto parser example IEEE 13 node network
# These examples use the dss library, not the COM port

# Avry Krywolt, October 15, 2026

# Import the dss library and check the object type
import dss
dss_py = dss.DSS
print(dss)
print("\n")      # <module 'dss' from '...\\site-packages\\dss\\__init__.py'>
print(dss.DSS)  # <dss.IDSS.IDSS object at 0x...>
print("\n") 

# Import other libraries necessary for this script
import math
import numpy as np
import matplotlib.pyplot as plt
import os
from pathlib import Path

# FUNCTION to find folders under start containing the file with file_name and within
# a folder with given folder_name if given, unspecified folder location if not
def find_folders_with(file_name, start, folder_name=None):
    """Search all the folders under 'start' (skipping hidden folders such as .git and .venv)
    and return the ones that contain 'file_name' (and are called 'folder_name', if given)"""
    found = []
    for root, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        if file_name in files and (folder_name is None or Path(root).name == folder_name):
            found.append(Path(root))
    return found

# FUNCTION to return true if the passed bus name begins with one of the declared
# stub prefixes
def is_stub(bus_name):
    return bus_name.lower().startswith(stub_prefixes)

# FUNCTION returning bus coordinates of the passed bus in x and y
def bus_xy(bus_name):
    DSSCircuit.SetActiveBus(bus_name)
    return DSSCircuit.ActiveBus.x, DSSCircuit.ActiveBus.y

# FUNCTION returning the phases of a bus connection, excluding the neutral EXAMPLE: '632.1.2.3.0' -> {1, 2, 3}
def phases_of(bus_text):
    nodes = bus_text.split('.')[1:]
    return {int(n) for n in nodes if n != '0'} if nodes else {1, 2, 3}   # no nodes written = all 3 phases

# FUNCTION Return all the buses (except the stub buses) that have the three phases
def three_phase_buses():
    buses = []
    for bus in DSSCircuit.AllBusNames:
        DSSCircuit.SetActiveBus(bus)
        if not is_stub(bus) and len(DSSCircuit.ActiveBus.Nodes) == 3:
            buses.append(bus)
    return buses

# FUNCTION showing the structure of the passed object
def show_structure(obj, name, indent=0, max_items=2):
    """Print the structure of a results dictionary: keys, types and a short example of each value"""
    pad = "    " * indent
    is_num = lambda x: isinstance(x, (int, float, np.number))
    if isinstance(obj, dict):
        print(f"{pad}{name}: dict with {len(obj)} keys")
        for i, (k, v) in enumerate(obj.items()):
            if indent > 0 and i >= max_items:
                print(f"{pad}    ... ({len(obj) - max_items} more keys of the same form)")
                break
            show_structure(v, repr(k), indent + 1, max_items)
    elif isinstance(obj, np.ndarray):
        print(f"{pad}{name}: numpy array of {obj.size} numbers, e.g. {np.round(obj[:3], 3).tolist()}")
    elif isinstance(obj, (list, tuple)) and obj and all(is_num(x) for x in obj):
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} numbers, e.g. {[int(x) if isinstance(x, (int, np.integer)) else round(float(x), 3) for x in obj[:3]]}")
    elif isinstance(obj, (list, tuple)) and obj and all(isinstance(x, str) for x in obj):
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} strings, e.g. {list(obj[:3])}")
    elif isinstance(obj, tuple) and len(obj) <= 6:
        print(f"{pad}{name}: tuple of {len(obj)}")
        for i, v in enumerate(obj):
            show_structure(v, f"[{i}]", indent + 1, max_items)
    elif isinstance(obj, (list, tuple)):
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} items, the first one is:")
        show_structure(obj[0], "[0]", indent + 1, max_items)
    elif isinstance(obj, (float, np.floating)):
        print(f"{pad}{name}: float = {float(obj):.4f}")
    else:
        print(f"{pad}{name}: {type(obj).__name__} = {obj!r}")

# FUNCTION collecting the results as extracted and printed to the terminal and storing for comparison
def collect_results():
    r = {}
    # Node voltages (2.8.7)
    r["vnode"] = dict(zip(DSSCircuit.AllNodeNames, DSSCircuit.AllBusVmagPu))
    v = np.array([vv for n, vv in r["vnode"].items() if not is_stub(n)])
    r["v_min"], r["v_max"], r["v_mean"] = v.min(), v.max(), v.mean()
    r["n_under"], r["n_over"] = int((v < V_MIN_PU).sum()), int((v > V_MAX_PU).sum())

    # Loads: P, Q and lowest voltage of the connected phases (2.8.1 and 2.8.2)
    r["loads"] = {}
    for load in DSSCircuit.Loads.AllNames:
        DSSCircuit.SetActiveElement(f"Load.{load}")
        powers = np.array(DSSCircuit.ActiveElement.Powers)
        bus_and_nodes = DSSCircuit.ActiveElement.BusNames[0]
        bus = bus_and_nodes.split('.')[0]
        v_load = min(r["vnode"][f"{bus}.{n}"] for n in bus_and_nodes.split('.')[1:])
        r["loads"][load] = (bus_and_nodes, powers[0::2].sum(), powers[1::2].sum(), v_load)

    # PV systems: P and Q injected into the network
    r["pv"] = {}
    if DSSCircuit.PVSystems.Count > 0:
        for pv in DSSCircuit.PVSystems.AllNames:
            DSSCircuit.SetActiveElement(f"PVSystem.{pv}")
            powers = np.array(DSSCircuit.ActiveElement.Powers)
            r["pv"][pv] = (DSSCircuit.ActiveElement.BusNames[0], -powers[0::2].sum(), -powers[1::2].sum())

    # Three-phase bus voltages and VUF (2.8.3)
    r["p3"] = {}
    for bus in three_phase_buses():
        DSSCircuit.SetActiveBus(bus)
        b = DSSCircuit.ActiveBus
        phases = [(ph, b.puVmagAngle[2 * i], b.VMagAngle[2 * i], b.VMagAngle[2 * i + 1]) for i, ph in enumerate(b.Nodes)]
        r["p3"][bus] = (phases, 100 * b.SeqVoltages[2] / b.SeqVoltages[1])

    # Transformers: P and Q per phase out of winding 2, and tap (2.8.4)
    r["xfmr"] = {}
    for tr in DSSCircuit.Transformers.AllNames:
        DSSCircuit.SetActiveElement(f"Transformer.{tr}")
        P = -np.array(DSSCircuit.ActiveElement.Powers[8:13:2])
        Q = -np.array(DSSCircuit.ActiveElement.Powers[9:14:2])
        DSSCircuit.Transformers.Name = tr
        DSSCircuit.Transformers.Wdg = 2
        r["xfmr"][tr] = (P, Q, DSSCircuit.Transformers.Tap, DSSCircuit.Transformers.kVA)

    # Losses, substation power and regulator tap (2.8.5 and 2.8.6)
    r["P_line_loss"], r["Q_line_loss"] = DSSCircuit.LineLosses[0], DSSCircuit.LineLosses[1]
    r["P_loss"], r["Q_loss"] = DSSCircuit.Losses[0] / 1000, DSSCircuit.Losses[1] / 1000
    r["P_source"], r["Q_source"] = -DSSCircuit.TotalPower[0], -DSSCircuit.TotalPower[1]
    r["P_load"] = sum(x[1] for x in r["loads"].values())
    r["Q_load"] = sum(x[2] for x in r["loads"].values())
    r["P_pv"] = sum(x[1] for x in r["pv"].values())
    DSSCircuit.RegControls.First
    r["reg_tap"] = DSSCircuit.RegControls.TapNumber

    # Line loading (2.8.8)
    r["lines"] = {}
    DSSCircuit.Lines.First
    while True:
        name = DSSCircuit.Lines.Name
        if not DSSCircuit.Lines.IsSwitch and not is_stub(DSSCircuit.Lines.Bus2):
            DSSCircuit.SetActiveElement(f"Line.{name}")
            n_cond = DSSCircuit.ActiveElement.NumConductors
            i_max = max(DSSCircuit.ActiveElement.CurrentsMagAng[0:2 * n_cond:2])
            r["lines"][name] = (i_max, DSSCircuit.Lines.NormAmps, 100 * i_max / DSSCircuit.Lines.NormAmps)
        if not DSSCircuit.Lines.Next:
            break

    # Voltage profile: node voltages and distance from the EnergyMeter, per phase (used in 2.11.6)
    r["profile"] = {ph: (np.array(DSSCircuit.AllNodeDistancesByPhase(ph)),
                         np.array(DSSCircuit.AllNodeVmagPUByPhase(ph)),
                         list(DSSCircuit.AllNodeNamesByPhase(ph))) for ph in (1, 2, 3)}
    return r

# Declare values for dss file folder name, master file name, and root markers to help with file search
# These values can be changed when pulling files from a different location
DSS_FOLDER_NAME = "tut_1-1_dss_files"   # folder name, path relative to the project root, or full path
MASTER_FILE_NAME = "Tut_1-1_Master.dss"          # file that calls all the other .dss files
ROOT_MARKERS = (".git", ".gitignore", "requirements.txt")   # files/folders that identify the project root

# Declare prefixes of "stub" buses to ignore in network mapping
# Enter "none" in parenthesis to show all buses in network map
stub_prefixes = ("load", "l611cap", "l675cap")

# Define the statutory limits on the pu voltage
# The default range is 0.95->1.05, following ANSI C84.1
# The same standard used for the IEEE 13 Node Test Feeder 
V_MIN_PU = 0.95   # lower statutory limit (pu)
V_MAX_PU = 1.05   # upper statutory limit (pu)

# Identify working directory (where python is running) and project root (where root markers reside)
my_directory = Path(os.getcwd()).resolve()
project_root = my_directory
for folder in [my_directory, *my_directory.parents]:
    if any((folder / marker).exists() for marker in ROOT_MARKERS):
        project_root = folder
        break

# Search for declared file folder and master file in declared folder, then stepping
# down through project root until candidates returns TRUE (when the master file is identified)
# using the find_folders_with function declared above
candidates = [Path(DSS_FOLDER_NAME),                    # full path
              my_directory / DSS_FOLDER_NAME,          # next to this notebook
              project_root / DSS_FOLDER_NAME]          # relative to the project root
candidates = [c for c in candidates if (c / MASTER_FILE_NAME).is_file()]
if not candidates:                                     # search the whole project
    candidates = find_folders_with(MASTER_FILE_NAME, project_root, Path(DSS_FOLDER_NAME).name)

if not candidates:
    options = find_folders_with(MASTER_FILE_NAME, project_root)
    options_txt = "\n".join(f"    {p.relative_to(project_root).as_posix()}" for p in options) or "    (none)"
    raise FileNotFoundError(f"No folder called '{DSS_FOLDER_NAME}' with a {MASTER_FILE_NAME} was found in {project_root}\n"
                            f"Folders in the project that contain a {MASTER_FILE_NAME} (paths relative to the project root):\n{options_txt}")

# Identify and flag if more than one master file is identified
dss_folder = candidates[0].resolve()
if len(set(c.resolve() for c in candidates)) > 1:
    print(f"WARNING: '{DSS_FOLDER_NAME}' was found in more than one place, the first one is used.")
master_file = str(dss_folder / MASTER_FILE_NAME)       # used by the Compile command in 2.4

# Identify and print all paths as a verification
print(f"Python is running in:            my_directory = {my_directory}")
print(f"The project root is:             project_root = {project_root}")
print(f"The .dss files are located in:   dss_folder   = {dss_folder}")
print(f"{MASTER_FILE_NAME} found: {Path(master_file).is_file()}\n")


# Setup DSS and map DSS commands to simple fuctions rather than nested executables
DSSText = dss_py.Text
DSSCircuit = dss_py.ActiveCircuit
DSSSolution = dss_py.ActiveCircuit.Solution
ControlQueue = dss_py.ActiveCircuit.CtrlQueue
dss_py.AllowForms = True
dss_py.AllowChangeDir = False

# Open and read the master file as a verification step
with open(master_file) as f:
    print(f"Reading from {master_file}:\n")
    print("--------------------------------")
    print(f.read())
    print("--------------------------------")

# Clear DSS and then DSS-compile the master file to execute all associated commands
# in the dss files accessed via redirect within the master dss file
DSSText.Command = 'Clear'
DSSText.Command = f'Compile "{master_file}"'
print(f"\nCircuit '{DSSCircuit.Name}' was read from the .dss files\n")

# After reading in the circuit, check the count of all the elements as a sanity check
# and to ensure the circuit has been properly loaded by the compile function
# Note that the line total is the combination of the line.dss and the switches.dss
print("Elements in the circuit:")
print("------------------------------")
print(f"| Buses          | {DSSCircuit.NumBuses:>5} |")
print(f"| Nodes          | {DSSCircuit.NumNodes:>5} |")
print(f"| Lines          | {DSSCircuit.Lines.Count:>5} |")
print(f"| Transformers   | {DSSCircuit.Transformers.Count:>5} |")
print(f"| Regulators     | {DSSCircuit.RegControls.Count:>5} |")
print(f"| Capacitors     | {DSSCircuit.Capacitors.Count:>5} |")
print(f"| Loads          | {DSSCircuit.Loads.Count:>5} |")
print(f"| PV Systems     | {DSSCircuit.PVSystems.Count:>5} |")
print(f"| Generators     | {DSSCircuit.Generators.Count:>5} |")
print(f"| Storage        | {DSSCircuit.Storages.Count:>5} |")
print("------------------------------")

# Plot the network into a figure, transformers represented as dotted lines, 
# Buses marked as circles and a triangle indicates capacitor buses
# 3 phase loads marked with large box, 2 phase with a diamon, and single phase laods with a small box
fig, ax = plt.subplots(figsize=(9, 6))

# Declare line thickness for 3, 2, and 1 phase lines
LINE_WIDTH = {3: 4.0, 2: 2.0, 1: 0.8}

# Lines: thickness = number of phases
DSSCircuit.Lines.First
while True:
    b1 = DSSCircuit.Lines.Bus1.split('.')[0]  # remove the node numbers, e.g. '632.1.2.3' -> '632'
    b2 = DSSCircuit.Lines.Bus2.split('.')[0]
    if not is_stub(b2):
        n_ph = len(phases_of(DSSCircuit.Lines.Bus1))
        (x1, y1), (x2, y2) = bus_xy(b1), bus_xy(b2)
        ax.plot([x1, x2], [y1, y2], color="#52514e", lw=LINE_WIDTH[n_ph], solid_capstyle="butt", zorder=1)
    if not DSSCircuit.Lines.Next:
        break

# Transformers (dotted)
for tr in DSSCircuit.Transformers.AllNames:
    DSSCircuit.SetActiveElement(f"Transformer.{tr}")
    b1, b2 = [b.split('.')[0] for b in DSSCircuit.ActiveElement.BusNames]
    (x1, y1), (x2, y2) = bus_xy(b1), bus_xy(b2)
    ax.plot([x1, x2], [y1, y2], color="#52514e", lw=1.5, ls=":", zorder=1)

# Buses
for bus in DSSCircuit.AllBusNames:
    if not is_stub(bus):
        x, y = bus_xy(bus)
        ax.scatter(x, y, s=60, color="white", edgecolors="#52514e", zorder=2)
        ax.annotate(bus, (x, y), xytext=(8, 8), textcoords="offset points", ha="left", fontsize=9)

# Loads: collect the phases used by all the loads at each bus, and whether any is phase-to-phase (delta)
load_phases, load_delta = {}, {}
for load in DSSCircuit.Loads.AllNames:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    bus_text = DSSCircuit.ActiveElement.BusNames[0]          # e.g. '671.1.2'
    bus = bus_text.split('.')[0]
    load_phases.setdefault(bus, set()).update(phases_of(bus_text))
    DSSCircuit.Loads.Name = load
    load_delta[bus] = load_delta.get(bus, False) or DSSCircuit.Loads.IsDelta
for bus, phases in load_phases.items():
    x, y = bus_xy(bus)
    if len(phases) == 3:      # three-phase load bus (one single-phase load on each phase)
        ax.scatter(x, y, marker="s", s=260, facecolors="none", edgecolors="#2a78d6", lw=2.0, zorder=3)
    elif load_delta[bus]:     # load connected between two phases
        ax.scatter(x, y, marker="D", s=170, facecolors="none", edgecolors="#2a78d6", lw=1.5, zorder=3)
    else:                     # single-phase load
        ax.scatter(x, y, marker="s", s=120, facecolors="none", edgecolors="#2a78d6", lw=1.2, zorder=3)

# Capacitors
for cap in DSSCircuit.Capacitors.AllNames:
    DSSCircuit.SetActiveElement(f"Capacitor.{cap}")
    x, y = bus_xy(DSSCircuit.ActiveElement.BusNames[0].split('.')[0])
    ax.scatter(x, y - 22, marker="^", s=70, color="#eb6834", zorder=3)   # drawn just below the bus

# Legend (empty plots are used only to create the legend entries)
ax.plot([], [], color="#52514e", lw=LINE_WIDTH[3], label="3-phase line")
ax.plot([], [], color="#52514e", lw=LINE_WIDTH[2], label="2-phase line")
ax.plot([], [], color="#52514e", lw=LINE_WIDTH[1], label="1-phase line")
ax.plot([], [], color="#52514e", lw=1.5, ls=":", label="Transformer / regulator")
ax.scatter([], [], marker="s", s=150, facecolors="none", edgecolors="#2a78d6", lw=2.0, label="3-phase load")
ax.scatter([], [], marker="D", s=90, facecolors="none", edgecolors="#2a78d6", lw=1.5, label="Phase-to-phase load")
ax.scatter([], [], marker="s", s=70, facecolors="none", edgecolors="#2a78d6", lw=1.2, label="1-phase load")
ax.scatter([], [], marker="^", s=50, color="#eb6834", label="Capacitor")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=4, frameon=False)
ax.set_xticks([]); ax.set_yticks([])
for side in ax.spines.values():
    side.set_visible(False)
ax.margins(0.1)

ax.set_title("Figure 1. IEEE 13 Node Test Feeder (read from the .dss files)")
plt.show()

# Now identify the loads in the system, the number of loads identified should align with the counted loads
# The model identification only works if the loads are declared as model 8 within the dss files
zip_type = {(0, 0, 1): "Const. P", (1, 0, 0): "Const. Z", (0, 1, 0): "Const. I"}
total_kw, total_kvar = 0, 0
print("Loads in the network:")
print("-----------------------------------------------------------------------")
print(f"| {'Load Name':<14} | {'Bus':<9} | {'Conn':<5} | {'kV':>5} | {'kW':>5} | {'kvar':>5} | {'Model':<8} |")
print("-----------------------------------------------------------------------")
DSSCircuit.Loads.First
while True:
    ld = DSSCircuit.Loads
    DSSCircuit.SetActiveElement(f"Load.{ld.Name}")
    bus = DSSCircuit.ActiveElement.BusNames[0]
    conn = "delta" if ld.IsDelta else "wye"
    zipv = tuple(round(z) for z in ld.ZIPV[0:3])
    print(f"| {ld.Name:<14} | {bus:<9} | {conn:<5} | {ld.kV:>5.2f} | {ld.kW:>5.0f} | {ld.kvar:>5.0f} | {zip_type.get(zipv, 'Mixed'):<8} |")
    total_kw += ld.kW
    total_kvar += ld.kvar
    if not DSSCircuit.Loads.Next:
        break
print("-----------------------------------------------------------------------")
print(f"Total rated demand = {total_kw:.0f} kW and {total_kvar:.0f} kvar")

# Now set the control modes, voltage bases, and max control iterations
# For the simple power flow conducted control mode is static and the mode is snapshot
# This setup becomes more complex with more complex model runs
DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[0.48, 4.16]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

# Run the circuit and display run time parameters if the power flow converges
DSSSolution.Solve()
if DSSSolution.Converged:
    print("The Circuit was Successfully Solved - IEEE 13 Node Test Feeder NO PV")
    print(f"Power flow iterations = {DSSSolution.Iterations}, control iterations = {DSSSolution.ControlIterations}")
    print("\n")


## Extract results from the power flow solution and print the reuslts into the output terminal

# Find the load active and reactive powers 
load_names = DSSCircuit.Loads.AllNames
print("Active power (P) and Reactive power (Q) demand of the loads:")
print("-------------------------------------------")
print(f"| {'Load Name':<14} | {'P (kW)':>9} | {'Q (kVAr)':>9} |")
print("-------------------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")
    powers = np.array(DSSCircuit.ActiveElement.Powers)
    P = powers[0::2].sum()  # add the P of every conductor
    Q = powers[1::2].sum()  # add the Q of every conductor
    print(f"| {load:<14} | {P:>9.3f} | {Q:>9.3f} |")
print("-------------------------------------------")

# Print the bus voltages of the load buses per phase (those buses connected to a load)
# Indicate with <, > if the pu voltage is below or above the statutory limitations
print("Voltage [in p.u.] of the buses connected to the loads (lowest connected phase):")
print("--------------------------------------------")
print(f"| {'Load Name':<14} | {'Bus':<9} | {'V (pu)':>8} |")
print("--------------------------------------------")
for load in load_names:
    DSSCircuit.SetActiveElement(f"Load.{load}")              # Set the load as an active element
    bus_and_nodes = DSSCircuit.ActiveElement.BusNames[0]       # e.g. '671.1.2'
    bus_name = bus_and_nodes.split('.')[0]                     # e.g. '671'
    nodes = [int(n) for n in bus_and_nodes.split('.')[1:]]     # e.g. [1, 2]
    DSSCircuit.SetActiveBus(bus_name)                          # Set the bus as an active element
    bus_nodes = list(DSSCircuit.ActiveBus.Nodes)               # the phases that exist at this bus
    v_pu = [DSSCircuit.ActiveBus.puVmagAngle[2 * bus_nodes.index(n)] for n in nodes]
    flag = "<" if min(v_pu) < V_MIN_PU else (">" if min(v_pu) > V_MAX_PU else "")
    print(f"| {load:<14} | {bus_and_nodes:<9} | {min(v_pu):>8.4f} | {flag}")
print("--------------------------------------------")

# Find the voltage magnitudes in detail for all the buses
print("Voltage magnitudes of all the buses:")
print("------------------------------------------------------------------")
print(f"| {'Bus':<6} | {'Phase':^5} | {'V (pu)':>7} | {'V (V)':>9} | {'Angle (deg)':>11} | {'VUF':>7} |")
print("------------------------------------------------------------------")
for bus in DSSCircuit.AllBusNames:            # all the buses in the circuit
    if is_stub(bus):                          # skip the 1m stub buses (see 2.5.2)
        continue
    DSSCircuit.SetActiveBus(bus)
    nodes = DSSCircuit.ActiveBus.Nodes
    if len(nodes) == 3:                       # VUF is only defined for three-phase buses
        seq = DSSCircuit.ActiveBus.SeqVoltages   # [V0, V1, V2]
        vuf = f"{100 * seq[2] / seq[1]:.2f}%"
    else:
        vuf = "-"
    for i, phase in enumerate(nodes):         # Loop over the phases of the bus
        v_pu = DSSCircuit.ActiveBus.puVmagAngle[2 * i]
        v_mag = DSSCircuit.ActiveBus.VMagAngle[2 * i]
        v_ang = round(DSSCircuit.ActiveBus.VMagAngle[2 * i + 1], 2) + 0.0   # + 0.0 avoids printing -0.00
        print(f"| {bus if i == 0 else '':<6} | {phase:^5} | {v_pu:>7.4f} | {v_mag:>9.1f} | {v_ang:>11.2f} | {vuf if i == 0 else '':>7} |")
    print("------------------------------------------------------------------")

# Extract the transformer taps, active and reactive power of each phase, and total active and reqactive power
for tr in DSSCircuit.Transformers.AllNames:
    DSSCircuit.SetActiveElement(f"Transformer.{tr}")
    active_power = -np.array(DSSCircuit.ActiveElement.Powers[8:13:2])    # selecting 8, 10, and 12
    reactive_power = -np.array(DSSCircuit.ActiveElement.Powers[9:14:2])  # selecting 9, 11, and 13
    DSSCircuit.Transformers.Name = tr
    DSSCircuit.Transformers.Wdg = 2
    print(f"Transformer {tr} ({DSSCircuit.Transformers.kVA:.0f} kVA), winding 2 tap = {DSSCircuit.Transformers.Tap:.5f}")
    print("---------------------------------")
    print(f"| Phase |  P (kW)  | Q (kVAr)  |")
    print("---------------------------------")
    for phase, P, Q in zip(range(1, 4), active_power, reactive_power):
        print(f"|   {phase}   | {P:>8.2f} | {Q:>8.2f}  |")
    print("---------------------------------")
    print(f"| Total | {active_power.sum():>8.2f} | {reactive_power.sum():>8.2f}  |")
    print("---------------------------------\n")

# Capture the active and reactive line losses and total losses
# which also counts transformer losses
line_loss = DSSCircuit.LineLosses
total_loss = DSSCircuit.Losses
print(f"Results of the Power Losses: ")
print(f"Line active power (P) losses     = {line_loss[0]:.3f} kW")
print(f"Line reactive power (Q) losses   = {line_loss[1]:.3f} kVAr")
print(f"Total active power (P) losses    = {total_loss[0] / 1000:.3f} kW   (lines + transformers)")
print(f"Total reactive power (Q) losses  = {total_loss[1] / 1000:.3f} kVAr")

# Capture the power supplied by the source and the regulator tap
# The regulator tap position `RegControls.TapNumber` goes from -16 to +16, 
# each step changes the voltage by 0.625%.
total_power = DSSCircuit.TotalPower
print(f"Substation active power (P)   = {-total_power[0]:.2f} kW")
print(f"Substation reactive power (Q) = {-total_power[1]:.2f} kVAr")
print(f"Losses as a % of the substation power = {100 * DSSCircuit.Losses[0] / 1000 / -total_power[0]:.2f} %")

DSSCircuit.RegControls.First
print(f"Regulator {DSSCircuit.RegControls.Name} tap position = {DSSCircuit.RegControls.TapNumber}")

# Check overall node voltage compliance and compile stats for entire power flow
node_names = DSSCircuit.AllNodeNames
node_v_pu = DSSCircuit.AllBusVmagPu
v = np.array([vv for n, vv in zip(node_names, node_v_pu) if not is_stub(n)])
real_nodes = [n for n in node_names if not is_stub(n)]

print(f"Number of nodes checked       = {len(v)}")
print(f"Minimum voltage               = {v.min():.4f} pu at node {real_nodes[v.argmin()]}")
print(f"Maximum voltage               = {v.max():.4f} pu at node {real_nodes[v.argmax()]}")
print(f"Average voltage               = {v.mean():.4f} pu")
print(f"Nodes below {V_MIN_PU} pu          = {(v < V_MIN_PU).sum()}")
print(f"Nodes above {V_MAX_PU} pu          = {(v > V_MAX_PU).sum()}")

# Capture the line loading of releavnt lines (not stub lines (0A), and not switch lines)
print("Line loading:")
print("----------------------------------------------------")
print(f"| {'Line':<10} | {'Ampacity':>8} | {'Current':>9} | {'Loading':>8} |")
print("----------------------------------------------------")
DSSCircuit.Lines.First
while True:
    name = DSSCircuit.Lines.Name
    if not DSSCircuit.Lines.IsSwitch and not is_stub(DSSCircuit.Lines.Bus2):
        DSSCircuit.SetActiveElement(f"Line.{name}")
        n_cond = DSSCircuit.ActiveElement.NumConductors
        i_max = max(DSSCircuit.ActiveElement.CurrentsMagAng[0:2 * n_cond:2])  # magnitudes at terminal 1
        amps = DSSCircuit.Lines.NormAmps
        print(f"| {name:<10} | {amps:>6.0f} A | {i_max:>7.1f} A | {100 * i_max / amps:>6.1f} % |")
    if not DSSCircuit.Lines.Next:
        break
print("----------------------------------------------------")

# Collect the results from the power flow in a dictionary, print confirmation
no_pv = collect_results()
print(f"No PV results stored for {len(no_pv['loads'])} loads, {len(no_pv['lines'])} lines and {len(no_pv['p3'])} three-phase buses")

# Show teh structure of the data stored
# show_structure(no_pv, "No PV")


## Now clear DSS, establish a new circuit, identical to the original
# and add 6 PV systems into the grid

# Read the network again from the .dss files
print("\n\nNEW POWER FLOW RUN WITH PV BEGINS\n\n")
DSSText.Command = 'Clear'
DSSText.Command = f'Compile "{master_file}"'

# Add the PV systems
DSSText.Command = 'new PVSystem.PV_675 bus1=675.1.2.3 phases=3 kV=4.16 kVA=500 Pmpp=500 pf=1 irradiance=1 model=1'
DSSText.Command = 'new PVSystem.PV_680 bus1=680.1.2.3 phases=3 kV=4.16 kVA=500 Pmpp=500 pf=1 irradiance=1 model=1'
DSSText.Command = 'new PVSystem.PV_634 bus1=634.1.2.3 phases=3 kV=0.48 kVA=250 Pmpp=250 pf=1 irradiance=1 model=1'
DSSText.Command = 'new PVSystem.PV_611 bus1=611.3 phases=1 kV=(4.16 3 sqrt /) kVA=100 Pmpp=100 pf=1 irradiance=1 model=1'
DSSText.Command = 'new PVSystem.PV_652 bus1=652.1 phases=1 kV=(4.16 3 sqrt /) kVA=100 Pmpp=100 pf=1 irradiance=1 model=1'
DSSText.Command = 'new PVSystem.PV_645 bus1=645.2 phases=1 kV=(4.16 3 sqrt /) kVA=100 Pmpp=100 pf=1 irradiance=1 model=1'

# Set the control mode and the voltage bases
DSSText.Command = 'set controlmode=static'
DSSText.Command = 'set mode=snapshot'
DSSText.Command = 'Set VoltageBases=[0.48, 4.16]'
DSSText.Command = 'calcvoltagebases'
DSSText.Command = 'Set maxcontroliter=1000'

# The number of PV systems should now reflect the number added
print(f"Number of PV systems in the circuit = {DSSCircuit.PVSystems.Count}")

# run teh power flow, store the results, and print the PV results to the output
DSSSolution.Solve()
if DSSSolution.Converged:
    print("The Circuit with PV was Successfully Solved - IEEE 13 Node Test Feeder WITH PV")
    print(f"Power flow iterations = {DSSSolution.Iterations}, control iterations = {DSSSolution.ControlIterations}")
    print("\n")

with_pv = collect_results()

print("Active power (P) and Reactive power (Q) output of the PV systems:")
print("------------------------------------------------")
print(f"| {'PV Name':<8} | {'Bus':<10} | {'P (kW)':>9} | {'Q (kVAr)':>9} |")
print("------------------------------------------------")
for pv, (bus, P, Q) in with_pv["pv"].items():
    print(f"| {pv:<8} | {bus:<10} | {P:>9.1f} | {round(Q, 1) + 0.0:>9.1f} |")
print("------------------------------------------------")
print(f"| {'Total':<8} | {'':<10} | {with_pv['P_pv']:>9.1f} | {'':>9} |")
print("------------------------------------------------")

# Compare results from the case without and with pv in a printed table
summary_rows = [
    ("Substation P  [kW]", "P_source", "{:.1f}"),
    ("Substation Q  [kvar]", "Q_source", "{:.1f}"),
    ("PV generation P  [kW]", "P_pv", "{:.1f}"),
    ("Load P  [kW]", "P_load", "{:.1f}"),
    ("Load Q  [kvar]", "Q_load", "{:.1f}"),
    ("Total losses P  [kW]", "P_loss", "{:.2f}"),
    ("Total losses Q  [kvar]", "Q_loss", "{:.2f}"),
    ("Line losses P  [kW]", "P_line_loss", "{:.2f}"),
    ("Line losses Q  [kvar]", "Q_line_loss", "{:.2f}"),
    ("Minimum node voltage  [pu]", "v_min", "{:.4f}"),
    ("Maximum node voltage  [pu]", "v_max", "{:.4f}"),
    ("Average node voltage  [pu]", "v_mean", "{:.4f}"),
    (f"Nodes below {V_MIN_PU} pu", "n_under", "{:d}"),
    (f"Nodes above {V_MAX_PU} pu", "n_over", "{:d}"),
    ("Regulator tap position", "reg_tap", "{:d}"),
]

# Summary Comparsion
print("Feeder summary:")
print("--------------------------------------------------------------------------")
print(f"| {'Result':<34} | {'No PV':>9} | {'With PV':>9} | {'Change':>9} |")
print("--------------------------------------------------------------------------")
for label, key, fmt in summary_rows:
    a, b = no_pv[key], with_pv[key]
    print(f"| {label:<34} | {fmt.format(a):>9} | {fmt.format(b):>9} | {fmt.format(b - a):>9} |")
print("--------------------------------------------------------------------------")
loss6 = 100 * no_pv["P_loss"] / no_pv["P_load"]
loss7 = 100 * with_pv["P_loss"] / with_pv["P_load"]
print(f"| {'Losses as % of load':<34} | {loss6:>9.2f} | {loss7:>9.2f} | {loss7 - loss6:>9.2f} |")
print("--------------------------------------------------------------------------")

for name, c in (("No PV", no_pv), ("With PV", with_pv)):
    balance = c["P_source"] + c["P_pv"] - c["P_load"] - c["P_loss"]
    print(f"Power balance check ({name}): substation + PV - load - losses = {balance:.3f} kW")
if with_pv["P_source"] < 0:
    print("*** Reverse power flow: the feeder is exporting power to the substation ***")

# Load powers comparison
    print("Load powers and voltages (lowest connected phase):")
print("------------------------------------------------------------------------------------------------")
print(f"| {'Load':<14} | {'Bus':<9} | {'P no PV':>8} | {'P w/ PV':>8} | {'Q no PV':>8} | {'Q w/ PV':>8} | {'V no PV':>8} | {'V w/ PV':>8} |")
print(f"| {'':<14} | {'':<9} | {'[kW]':>8} | {'[kW]':>8} | {'[kvar]':>8} | {'[kvar]':>8} | {'[pu]':>8} | {'[pu]':>8} |")
print("------------------------------------------------------------------------------------------------")
for load in no_pv["loads"]:
    bus, P6, Q6, V6 = no_pv["loads"][load]
    _, P7, Q7, V7 = with_pv["loads"][load]
    flag = "<" if V7 < V_MIN_PU else (">" if V7 > V_MAX_PU else "")
    print(f"| {load:<14} | {bus:<9} | {P6:>8.1f} | {P7:>8.1f} | {Q6:>8.1f} | {Q7:>8.1f} | {V6:>8.4f} | {V7:>8.4f} | {flag}")
print("------------------------------------------------------------------------------------------------")

# 3-phase bus voltage comparison
print("Voltage magnitudes and voltage unbalance factor (VUF) of the three-phase buses:")
print("------------------------------------------------------------------------")
print(f"| {'Bus':<5} | {'Phase':^5} | {'V no PV':>9} | {'V w/ PV':>9} | {'V no PV':>10} | {'V w/ PV':>10} |")
print(f"| {'':<5} | {'':^5} | {'[pu]':>9} | {'[pu]':>9} | {'[V]':>10} | {'[V]':>10} |")
print("------------------------------------------------------------------------")
for bus in no_pv["p3"]:                       # the three-phase buses found by collect_results()
    phases6, vuf6 = no_pv["p3"][bus]
    phases7, vuf7 = with_pv["p3"][bus]
    for (ph, pu6, v6, _), (_, pu7, v7, _) in zip(phases6, phases7):
        print(f"| {bus:<5} | {ph:^5} | {pu6:>9.4f} | {pu7:>9.4f} | {v6:>10.1f} | {v7:>10.1f} |")
    print(f"| {bus:<5} | {'VUF':^5} | {vuf6:>8.2f}% | {vuf7:>8.2f}% | {'':>10} | {'':>10} |")
    print("------------------------------------------------------------------------")

# Transformer power comparison
for tr in no_pv["xfmr"]:
    P6, Q6, tap6, kva = no_pv["xfmr"][tr]
    P7, Q7, tap7, _ = with_pv["xfmr"][tr]
    print(f"Transformer {tr} ({kva:.0f} kVA), winding 2 tap: no PV = {tap6:.5f}, with PV = {tap7:.5f}")
    print("-------------------------------------------------------------------------")
    print(f"| {'Phase':^5} | {'P no PV':>9} | {'P w/ PV':>9} | {'Q no PV':>9} | {'Q w/ PV':>9} | {'Loading w/ PV':>13} |")
    print(f"| {'':^5} | {'[kW]':>9} | {'[kW]':>9} | {'[kvar]':>9} | {'[kvar]':>9} | {'[% rating]':>13} |")
    print("-------------------------------------------------------------------------")
    for phase in range(3):
        loading = 100 * math.hypot(P7[phase], Q7[phase]) / (kva / 3)
        print(f"| {phase + 1:^5} | {P6[phase]:>9.1f} | {P7[phase]:>9.1f} | {Q6[phase]:>9.1f} | {Q7[phase]:>9.1f} | {loading:>12.1f}% |")
    print("-------------------------------------------------------------------------")
    print(f"| {'Total':^5} | {P6.sum():>9.1f} | {P7.sum():>9.1f} | {Q6.sum():>9.1f} | {Q7.sum():>9.1f} | {'':>13} |")
    print("-------------------------------------------------------------------------\n")

# Line loading comparison
print("Line loading (highest conductor current / ampacity):")
print("--------------------------------------------------------------------------")
print(f"| {'Line':<10} | {'Ampacity':>8} | {'I no PV':>9} | {'I w/ PV':>9} | {'Load no PV':>10} | {'Load w/ PV':>10} |")
print("--------------------------------------------------------------------------")
for line_name in no_pv["lines"]:
    i6, amps, pct6 = no_pv["lines"][line_name]
    i7, _, pct7 = with_pv["lines"][line_name]
    print(f"| {line_name:<10} | {amps:>6.0f} A | {i6:>7.1f} A | {i7:>7.1f} A | {pct6:>8.1f} % | {pct7:>8.1f} % |")
print("--------------------------------------------------------------------------")

# Figure generation - comparison of voltage profile along the feeder, at each node
PHASE_COLOURS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a"}   # phase 1, 2, 3
NO_PV, WITH_PV = "#9a9893", "#2a78d6"                          # grey = no PV, blue = with PV
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.3, "font.size": 10})

def draw_limits(ax):
    ax.axhline(V_MIN_PU, color="#e34948", ls="--", lw=1)
    ax.axhline(V_MAX_PU, color="#e34948", ls="--", lw=1)

fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
for ax, res, title in zip(axes, (no_pv, with_pv), ("Case 6: no PV", "Case 7: with PV")):
    for ph in (1, 2, 3):
        dist, volt, names = res["profile"][ph]
        keep = [i for i, n in enumerate(names) if not is_stub(n)]
        ax.plot(dist[keep], volt[keep], "o", ms=6, color=PHASE_COLOURS[ph], label=f"Phase {ph}")
    draw_limits(ax)
    ax.set_ylim(0.86, 1.07)
    ax.set_title(title)
    ax.set_xlabel("Distance from the substation [km]")
axes[0].set_ylabel("Node voltage [pu]")
axes[0].legend(loc="lower left")
fig.suptitle("Figure 2. Voltage profile along the feeder")
fig.tight_layout()
plt.show()

# Figure generation - bar hcart comparison of node voltage
nodes = [n for n in no_pv["vnode"] if not is_stub(n)]
x = np.arange(len(nodes))
fig, ax = plt.subplots(figsize=(13, 4.5))
ax.bar(x - 0.2, [no_pv["vnode"][n] for n in nodes], 0.4, color=NO_PV, label="No PV")
ax.bar(x + 0.2, [with_pv["vnode"][n] for n in nodes], 0.4, color=WITH_PV, label="With PV")
draw_limits(ax)
ax.set_xticks(x, nodes, rotation=90)
ax.set_ylim(0.85, 1.10)
ax.set_ylabel("Voltage [pu]")
ax.set_title("Figure 3. Node voltages before and after PV")
ax.legend(loc="upper right", ncol=2)
fig.tight_layout()
plt.show()

# Figure generation - power flow and line losses bar chart comparison
fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), gridspec_kw={"width_ratios": [1, 1.6]})

ax = axes[0]
items = [("Substation P\n[kW]", "P_source"), ("PV P\n[kW]", "P_pv"), ("Load P\n[kW]", "P_load"), ("Substation Q\n[kvar]", "Q_source")]
x = np.arange(len(items))
bars6 = ax.bar(x - 0.2, [no_pv[k] for _, k in items], 0.4, color=NO_PV, label="No PV")
bars7 = ax.bar(x + 0.2, [with_pv[k] for _, k in items], 0.4, color=WITH_PV, label="With PV")
ax.bar_label(bars6, fmt="%.0f", fontsize=8)
ax.bar_label(bars7, fmt="%.0f", fontsize=8)
ax.set_xticks(x, [label for label, _ in items])
ax.set_title(f"Power balance (losses: {no_pv['P_loss']:.1f} kW -> {with_pv['P_loss']:.1f} kW)")
ax.legend()

ax = axes[1]
line_names = list(no_pv["lines"])
x = np.arange(len(line_names))
ax.bar(x - 0.2, [no_pv["lines"][n][2] for n in line_names], 0.4, color=NO_PV, label="No PV")
ax.bar(x + 0.2, [with_pv["lines"][n][2] for n in line_names], 0.4, color=WITH_PV, label="With PV")
ax.axhline(100, color="#e34948", ls="--", lw=1)
ax.set_xticks(x, line_names, rotation=45, ha="right")
ax.set_ylabel("Loading [% of ampacity]")
ax.set_title("Line loading (highest conductor)")
ax.legend(loc="upper right")

fig.suptitle("Figure 5. Feeder power balance and line loading")
fig.tight_layout()
plt.show()

# Figure generation - gradient voltage change in pu from PV implementation, in network topology
fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), gridspec_kw={"width_ratios": [1, 1.6]})

ax = axes[0]
items = [("Substation P\n[kW]", "P_source"), ("PV P\n[kW]", "P_pv"), ("Load P\n[kW]", "P_load"), ("Substation Q\n[kvar]", "Q_source")]
x = np.arange(len(items))
bars6 = ax.bar(x - 0.2, [no_pv[k] for _, k in items], 0.4, color=NO_PV, label="No PV")
bars7 = ax.bar(x + 0.2, [with_pv[k] for _, k in items], 0.4, color=WITH_PV, label="With PV")
ax.bar_label(bars6, fmt="%.0f", fontsize=8)
ax.bar_label(bars7, fmt="%.0f", fontsize=8)
ax.set_xticks(x, [label for label, _ in items])
ax.set_title(f"Power balance (losses: {no_pv['P_loss']:.1f} kW -> {with_pv['P_loss']:.1f} kW)")
ax.legend()

ax = axes[1]
line_names = list(no_pv["lines"])
x = np.arange(len(line_names))
ax.bar(x - 0.2, [no_pv["lines"][n][2] for n in line_names], 0.4, color=NO_PV, label="No PV")
ax.bar(x + 0.2, [with_pv["lines"][n][2] for n in line_names], 0.4, color=WITH_PV, label="With PV")
ax.axhline(100, color="#e34948", ls="--", lw=1)
ax.set_xticks(x, line_names, rotation=45, ha="right")
ax.set_ylabel("Loading [% of ampacity]")
ax.set_title("Line loading (highest conductor)")
ax.legend(loc="upper right")

fig.suptitle("Figure 5. Feeder power balance and line loading")
fig.tight_layout()
plt.show()

