# Tutorial 1-1 rebuilt with the dss_toolkit functions (src/dss_toolkit)
# Reads a feeder from .dss files, solves it without and with PV, and compares the two cases
# Same procedure and results as tut_1-1_read_file_power_flow.py
#
# Avry Krywolt, October 19, 2026

import sys
from pathlib import Path

# Make src/ importable (not needed if the project is installed with: pip install -e .)
for folder in Path(__file__).resolve().parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import der, engine as eng, extract, network as net, paths, plots, reports

# Script inputs - change these to change data file locations, Pv implementtaion strategies
DSS_FOLDER_NAME = "tut_1-1_dss_files"         # folder name, path relative to the project root, or full path
MASTER_FILE_NAME = "Tut_1-1_Master.dss"
VOLTAGE_BASES_KV = (0.48, 4.16)
LIMITS_PU = (0.95, 1.05)                      # ANSI C84.1 Range A
STUB_PREFIXES = ("load", "l611cap", "l675cap")  # converter stub buses to leave out; () keeps everything
PV_SITES = [
    dict(name="PV_675", bus="675.1.2.3", phases=3, kv=4.16, kva=500),
    dict(name="PV_680", bus="680.1.2.3", phases=3, kv=4.16, kva=500),
    dict(name="PV_634", bus="634.1.2.3", phases=3, kv=0.48, kva=250),
    dict(name="PV_611", bus="611.3", phases=1, kv=der.single_phase_kv(4.16), kva=100),
    dict(name="PV_652", bus="652.1", phases=1, kv=der.single_phase_kv(4.16), kva=100),
    dict(name="PV_645", bus="645.2", phases=1, kv=der.single_phase_kv(4.16), kva=100),
]
LABELS = ("No PV", "With PV")
FIGURE_FOLDER = "results/tut1-1"                          # e.g. "results/tut_1-1" to save the figures (keep it gitignored)


def run_case(engine, master_file, extra_commands, label):
    """Build, solve and collect one snapshot case."""
    eng.build_circuit(engine, master_file, VOLTAGE_BASES_KV, extra_commands)
    eng.set_snapshot_mode(engine)
    eng.solve(engine, label)
    return extract.collect_results(engine, LIMITS_PU, STUB_PREFIXES)


def figure_path(name):
    return Path(FIGURE_FOLDER) / name if FIGURE_FOLDER else None


# ---- 1. Read and inspect the network ---------------------------------------------------------
master_file = paths.locate_file(MASTER_FILE_NAME, DSS_FOLDER_NAME)
engine = eng.start_engine()
print(f"Circuit '{eng.compile_circuit(engine, master_file)}' read from {master_file.name}")
reports.print_element_counts(net.element_counts(engine))
print("DER already in the files:", net.has_der(engine))
reports.print_load_inventory(net.load_inventory(engine))
plots.apply_style()
plots.show_or_save(plots.plot_network_map(engine, STUB_PREFIXES, "Figure 1. Network"), figure_path("fig1_network.png"))

# ---- 2. Case without PV ----------------------------------------------------------------------
no_pv = run_case(engine, master_file, [], LABELS[0])
reports.print_snapshot_report(no_pv, LIMITS_PU)

# ---- 3. Case with PV -------------------------------------------------------------------------
with_pv = run_case(engine, master_file, der.pv_commands(PV_SITES), LABELS[1])
reports.print_table(["PV", "Bus", "P (kW)", "Q (kvar)"],
                    [[n, b, reports.fmt(p, ".1f"), reports.fmt(q, ".1f")] for n, (b, p, q) in with_pv["pv"].items()],
                    "PV system output:")

# ---- 4. Comparison ---------------------------------------------------------------------------
reports.print_comparison(no_pv, with_pv, LABELS, LIMITS_PU)
cases = [no_pv, with_pv]
plots.show_or_save(plots.plot_voltage_profiles(cases, LABELS, LIMITS_PU, STUB_PREFIXES, "Figure 2. Voltage profile"), figure_path("fig2_profile.png"))
plots.show_or_save(plots.plot_node_voltages(cases, LABELS, LIMITS_PU, STUB_PREFIXES, "Figure 3. Node voltages"), figure_path("fig3_nodes.png"))
plots.show_or_save(plots.plot_voltage_change_map(engine, no_pv, with_pv, STUB_PREFIXES, [s["bus"] for s in PV_SITES],
                                                 "Figure 4. Voltage change with PV [% of nominal]"), figure_path("fig4_dv_map.png"))
plots.show_or_save(plots.plot_power_and_loading(cases, LABELS, "Figure 5. Power balance and line loading"), figure_path("fig5_power.png"))
