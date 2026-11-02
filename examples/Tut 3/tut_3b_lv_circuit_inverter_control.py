# Team Nando Tutorial 3 (volt-watt / volt-var inverter control and PV hosting capacity), built
# with dss_toolkit (src/dss_toolkit). Script B: the AusNet LV test circuit (31 customers),
# compiled from LVcircuit-master.txt (Team Nando Tutorial 3 GitHub, folder TestLVCircuit).
# Script A (tut_3a_simple_network_inverter_control.py) runs the same study on the 3-house network.
#
# What the script does:
#   1. Ranks all 365 days of PV data by daily peak (rank 0 = highest peak = worst case) and
#      simulates every RANK_INTERVAL-th day plus the best day.
#   2. Runs each day in 1-4 PV modes: no PV, PV, PV + volt-watt, PV + volt-var
#      (IEEE 1547-2018 Category B default curves, editable in section 5).
#   3. Compares the modes, and with a penetration sweep, gives the hosting capacity of each mode.
#
# Load data is active power only (kW): reactive power comes from a random power factor per
# customer and time step (section 8). Every random choice has its own named seed, so each one
# can be changed alone; with all seeds fixed, a run is repeated exactly.
#
# Settings are grouped in the order a user would choose them in an interface (see the
# Tut 3 selection flow diagram). Figures are only saved to RESULTS_FOLDER, never shown.
#
# Avry Krywolt, October 26, 2026

import shutil
import sys
from dataclasses import asdict
from pathlib import Path

# Make src/ importable (not needed if the project is installed with: pip install -e .)
SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import engine as eng, hosting, paths, plots, reports, results as res, scenario as sc, timeseries as ts

# =============================================================================================
# Settings, in selection order
# =============================================================================================
# ---- 1. Circuit (the only section that differs from script A) -------------------------------
CIRCUIT_NAME = "lv_test_circuit"
DATA_FOLDER = "tut_3_data"                                   # folder name, path from the repo root, or full path
MASTER_FILE_NAME = "LVcircuit-master.txt"
BUS_COORDINATES_FILE_NAME = "LVcircuit-buscoords.txt"        # copied from Tut 2; used for the maps only

# ---- 2. Fixed study settings ----------------------------------------------------------------
VOLTAGE_BASES_KV = (22.0, 0.4)
VOLTAGE_LIMITS_PU = (0.94, 1.10)                             # statutory limits: -6 % / +10 % of 230 V
TRANSFORMER_RATING_KVA = 500.0                               # nameplate of transformer_MG1_TR1 (Tut 2 used 175)
LOAD_PROFILE_FILE_NAME = "Residential load data 30-min resolution.npy"   # (342 profiles, 365 days, 48 steps) in kW
PV_PROFILE_FILE_NAME = "Residential PV data 30-min resolution.npy"       # (365 days, 48 steps), normalised 0-1

# ---- 3. PV build: "random" (PV on a % of customers) or "sites" (the PV_SITES list) ----------
PV_BUILD = "random"
PV_RATING_KVA = 10.0                                         # random build: every PV system (kVA = Pmpp)
PV_PLACEMENT_SEED = 1                                        # random build: which customers get PV
PV_SITES = [                                                 # sites build: load name and rating of each PV
    {"customer": "Load_MG1_1", "kva": 5.0},
    {"customer": "Load_MG1_8", "kva": 10.0},
    {"customer": "Load_MG1_15", "kva": 7.5},
    {"customer": "Load_MG1_31", "kva": 10.0},
]

# ---- 4. Penetration run (random build only): "single" or "sweep" -----------------------------
PENETRATION_RUN = "single"
SINGLE_PENETRATION_PCT = 100                                 # "single": compare the PV modes at this %
SWEEP_PENETRATIONS_PCT = (0, 20, 40, 60, 80, 100)            # "sweep": every % -> hosting capacity per mode

# ---- 5. PV operation: any 1 to 4 of "no_pv", "pv", "pv_volt_watt", "pv_volt_var" -------------
PV_MODES = ("no_pv", "pv", "pv_volt_watt", "pv_volt_var")
# Inverter control curves: EDIT HERE to test other settings. Voltage in pu of the inverter's rated
# voltage (230 V). Defaults: IEEE Std 1547-2018, Category B (Table 10 volt-watt, Table 8 volt-var).
# The first and last points only extend the curve flat to 0.5 and 1.5 pu.
VOLT_WATT_CURVE = sc.InverterControl(
    mode="volt_watt",
    voltage_pu=(0.50, 1.06, 1.10, 1.50),                     # V1 = 1.06, V2 = 1.10
    output_pu=(1.00, 1.00, 0.20, 0.20),                      # P1 = 1.0, P2 = 0.2 (pu of Pmpp)
    source="IEEE 1547-2018 Table 10, Category B default")
VOLT_VAR_CURVE = sc.InverterControl(
    mode="volt_var",
    voltage_pu=(0.50, 0.92, 0.98, 1.02, 1.08, 1.50),         # V1-V4 = VRef -0.08, -0.02, +0.02, +0.08 (VRef = 1.0)
    output_pu=(0.44, 0.44, 0.00, 0.00, -0.44, -0.44),        # Q1 = +44 % (inject), Q4 = -44 % (absorb), pu of kVA
    source="IEEE 1547-2018 Table 8, Category B default")

# ---- 6. PV days ---------------------------------------------------------------------------
RANK_INTERVAL = 25                                           # simulate ranks 0, 25, 50 ... (0 = highest peak)
INCLUDE_BEST_DAY = True                                      # also simulate the last rank (lowest peak)

# ---- 7. Load day: matched to the PV day, or a random day -----------------------------------
USE_MATCHED_LOAD_DAY = True                                  # True: load day = PV day (LOAD_DAY_SEED unused)
LOAD_DAY_SEED = 1                                            # False: random load day for each PV day

# ---- 8. Demand per load (always random, each with its own seed) -----------------------------
LOAD_PROFILE_SEED = 1                                        # which of the 342 profiles each load gets
POWER_FACTOR_SEED = 1                                        # power factor per load and step -> kvar
POWER_FACTOR_RANGE = (0.90, 0.98)

# ---- 9. Outputs ----------------------------------------------------------------------------
RESULTS_FOLDER = "results/tut3/lv_test_circuit"              # from the repo root; emptied at every run
SAVE_SIMULATIONS = True                                      # also save every run's time series (.npz)

# =============================================================================================
# 1-2. Circuit and data
# =============================================================================================
project_root = paths.find_project_root(SCRIPT_FOLDER)
results_folder = project_root / RESULTS_FOLDER
shutil.rmtree(results_folder, ignore_errors=True)            # fresh results for this run


def output(file_name):
    return paths.output_file_path(file_name, results_folder)


master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER, start=SCRIPT_FOLDER, verbose=False)
data_folder = master_file.parent
setup = hosting.StudySetup(circuit_source=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV,
                           limits=VOLTAGE_LIMITS_PU, transformer_rating_kva=TRANSFORMER_RATING_KVA,
                           bus_coordinates=data_folder / BUS_COORDINATES_FILE_NAME)
engine = eng.start_engine()
plots.apply_style()
customers = hosting.list_customers(engine, setup)
print(f"Circuit '{engine.ActiveCircuit.Name}': {len(customers)} customers")
plots.save_figure(plots.plot_network_map(engine, title="LV test circuit", labels="short"), output("fig_01_network_map.png"))

load_profiles_kw = ts.read_profile_file(data_folder / LOAD_PROFILE_FILE_NAME)
pv_profiles_pu = ts.read_profile_file(data_folder / PV_PROFILE_FILE_NAME)

# =============================================================================================
# 3-8. Study plan (every selection above) -> scenarios
# =============================================================================================
plan = sc.StudyPlan(
    circuit_name=CIRCUIT_NAME,
    pv_build=PV_BUILD, pv_rating_kva=PV_RATING_KVA, pv_placement_seed=PV_PLACEMENT_SEED, pv_sites=PV_SITES,
    penetration_run=PENETRATION_RUN,
    penetrations_pct=SWEEP_PENETRATIONS_PCT if PENETRATION_RUN == "sweep" else (SINGLE_PENETRATION_PCT,),
    pv_modes=PV_MODES, inverter_controls={"volt_watt": VOLT_WATT_CURVE, "volt_var": VOLT_VAR_CURVE},
    rank_interval=RANK_INTERVAL, include_best_day=INCLUDE_BEST_DAY,
    use_matched_load_day=USE_MATCHED_LOAD_DAY, load_day_seed=LOAD_DAY_SEED,
    load_profile_seed=LOAD_PROFILE_SEED, power_factor_seed=POWER_FACTOR_SEED, power_factor_range=POWER_FACTOR_RANGE)
res.save_settings(asdict(plan), output("tut_3_settings.json"))

scenarios, sampled_days = sc.plan_scenarios(plan, customers, load_profiles_kw, pv_profiles_pu)
print(f"{len(sampled_days)} PV days x {len(PV_MODES)} PV modes"
      f"{f' x {len(plan.penetrations_to_run)} penetrations' if plan.is_sweep else ''} = {len(scenarios)} daily runs")
plots.save_figure(plots.plot_pv_day_ranking(pv_profiles_pu, sc.rank_pv_days(pv_profiles_pu), sampled_days),
                  output("fig_02_pv_day_ranking.png"))
pv_map_scenario = max(scenarios, key=lambda s: len(s.der))  # the largest PV fleet of the study
plots.save_figure(plots.plot_der_map(engine, pv_map_scenario, title=f"PV placement ({PV_BUILD} build, "
                                     f"{len(pv_map_scenario.der)} systems)"), output("fig_03_pv_placement.png"))

# =============================================================================================
# Run every day x PV mode (x penetration)
# =============================================================================================
table, simulations = hosting.run_study(engine, setup, scenarios, results_file=output("tut_3_results.csv"),
                                       simulations_folder=output("simulations") if SAVE_SIMULATIONS else None,
                                       keep_simulations=True, verbose=True)
if not table["converged"].all():
    print(f"WARNING: {(~table['converged']).sum()} runs did not converge at every step (see 'converged' in the CSV)")

# =============================================================================================
# Compare the PV modes
# =============================================================================================
mode_labels, mode_colours = sc.PV_MODES, plots.PV_MODE_COLOURS
comparison = hosting.summarise_groups(table, ("pv_mode", "penetration_pct"))
comparison.to_csv(output("tut_3_mode_comparison.csv"), index=False)
reports.print_summary_table(comparison, [
    ("PV mode", "pv_mode", "s"), ("PV %", "penetration_pct", "d"), ("Days", "n_days", "d"),
    ("Days non-compliant", "n_days_noncompliant", "d"), ("Max non-compliant", "max_noncompliant_customers", "d"),
    ("V max (pu)", "v_max_pu", ".4f"), ("V min (pu)", "v_min_pu", ".4f"),
    ("Max utilisation (%)", "max_transformer_utilisation_pct", ".1f"), ("PV curtailed (%)", "pv_curtailed_pct", ".2f")],
    f"PV modes over {len(sampled_days)} ranked PV days ({CIRCUIT_NAME}, {PV_BUILD} PV build)")

# Mode comparison against PV day rank, at the single (or highest swept) penetration
compared = table[table["pv_mode"].eq("no_pv") | table["penetration_pct"].isna()
                 | table["penetration_pct"].eq(max(plan.penetrations_to_run, key=lambda p: p or 0))]
compared_pct = "" if PV_BUILD == "sites" else f", {max(plan.penetrations_to_run)} % PV penetration"
plots.save_figure(plots.plot_metrics_vs_x(
    compared, "pv_rank", {"v_max_pu": "Highest customer voltage (pu)", "n_noncompliant_customers": "Non-compliant customers",
                          "pv_curtailed_pct": "PV energy curtailed (%)", "transformer_utilisation_pct": "Peak transformer utilisation (%)"},
    "pv_mode", f"PV modes by PV day rank (0 = highest peak){compared_pct}", mode_labels,
    xlabel="PV day rank", hlines={"v_max_pu": VOLTAGE_LIMITS_PU[1]}, group_colours=mode_colours),
    output("fig_04_mode_comparison_by_rank.png"))

# Worst PV day (rank 0): customer voltages and PV output in each mode
worst_day = [s for s, (_, row) in zip(simulations, table.iterrows()) if row["pv_rank"] == 0 and row.name in compared.index]
plots.save_figure(plots.plot_panels({mode_labels[s["scenario"].tags["pv_mode"]]: s["V"] for s in worst_day},
                                    "Customer voltage (pu)", limits=VOLTAGE_LIMITS_PU,
                                    title=f"Customer voltages on the worst PV day (day {sampled_days[0][1]}){compared_pct}"),
                  output("fig_05_worst_day_voltages.png"))
with_pv = [s for s in worst_day if s["der"]]
if with_pv:
    plots.save_figure(plots.plot_time_series(
        [with_pv[0]["der_available_P"].sum(axis=1)] + [s["der_P"].sum(axis=1) for s in with_pv],
        f"Total PV active power on the worst PV day{compared_pct}", "kW",
        labels=["Available"] + [mode_labels[s["scenario"].tags["pv_mode"]] for s in with_pv],
        styles=[":"] + ["-"] * len(with_pv),
        colours=[mode_colours["available"]] + [mode_colours[s["scenario"].tags["pv_mode"]] for s in with_pv]),
        output("fig_06_worst_day_pv_active_power.png"))
    plots.save_figure(plots.plot_time_series(
        [s["der_Q"].sum(axis=1) for s in with_pv], f"Total PV reactive power on the worst PV day{compared_pct}",
        "kvar (negative = absorbed)", labels=[mode_labels[s["scenario"].tags["pv_mode"]] for s in with_pv],
        colours=[mode_colours[s["scenario"].tags["pv_mode"]] for s in with_pv]),
        output("fig_07_worst_day_pv_reactive_power.png"))

# =============================================================================================
# Penetration sweep: hosting capacity of each PV mode
# =============================================================================================
if plan.is_sweep:
    pv_rows = table[table["pv_mode"] != "no_pv"]
    by_mode = hosting.hosting_capacity_table(pv_rows, ["pv_mode"])
    by_mode_and_day = hosting.hosting_capacity_table(pv_rows, ["pv_mode", "pv_rank", "pv_day"])
    by_mode.to_csv(output("tut_3_hosting_capacity_by_mode.csv"), index=False)
    by_mode_and_day.to_csv(output("tut_3_hosting_capacity_by_mode_and_day.csv"), index=False)
    reports.print_summary_table(by_mode, [("PV mode", "pv_mode", "s"), ("Hosting capacity (%)", "hosting_capacity_pct", "d"),
                                          ("PV systems", "n_pv_systems_at_capacity", "d")],
                                "Hosting capacity: no non-compliant customer and transformer within its rating on every simulated day")
    sweep = hosting.summarise_groups(pv_rows, ("pv_mode", "penetration_pct"))
    plots.save_figure(plots.plot_metrics_vs_x(
        sweep, "penetration_pct", {"max_noncompliant_customers": "Non-compliant customers (worst day)",
                                   "v_max_pu": "Highest customer voltage (pu)", "pv_curtailed_pct": "PV energy curtailed (%)",
                                   "max_transformer_utilisation_pct": "Peak transformer utilisation (%)"},
        "pv_mode", "PV modes by penetration (worst of the simulated days)", mode_labels,
        xlabel="PV penetration (% of customers)", hlines={"v_max_pu": VOLTAGE_LIMITS_PU[1]}, group_colours=mode_colours),
        output("fig_08_sweep_by_penetration.png"))
    plots.save_figure(plots.plot_bars([mode_labels[m] for m in by_mode["pv_mode"]], list(by_mode["hosting_capacity_pct"]),
                                      "Hosting capacity (% of customers)", "PV hosting capacity per PV mode",
                                      missing_text="fails at 0 %", colours=[mode_colours[m] for m in by_mode["pv_mode"]]),
                      output("fig_09_hosting_capacity.png"))

print(f"\nResults ({len(table)} runs) and figures saved to {results_folder}")
