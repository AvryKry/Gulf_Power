# Team Nando Tutorial 2 (time-series analysis and PV hosting capacity of an LV network),
# completed with the dss_toolkit functions (src/dss_toolkit)
#
#   Part A: the tutorial - daily load and PV profiles allocated to every customer, 30-min power flows
#   Part B: the exercise - worst-case seasonal PV profile, penetration sweep 0-100 %,
#           non-compliant customers (E.1), transformer utilisation (E.2) and hosting capacity (E.3)
#
# Every simulation follows the same three steps:
#   1. setup    = the network and how it is judged       (hosting.StudySetup)
#   2. scenario = what is simulated: demand, PV, window    (scenario.random_scenario / penetration_scenarios)
#   3. run      = one table row per scenario               (hosting.run_study)
#
# Avry Krywolt, October 24, 2026

import sys
from pathlib import Path

# Make src/ importable (not needed if the project is installed with: pip install -e .)
for folder in Path(__file__).resolve().parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

import numpy as np
import pandas as pd

from dss_toolkit import engine as eng, hosting, network as net, paths, plots, reports, scenario as sc, timeseries as ts

# ---- Inputs: change these for a different data set ------------------------------------------
DATA_FOLDER = "tut_2_data"                     # folder with the circuit and the .npy files (None = search everywhere)
MASTER_FILE_NAME = "LVcircuit-master.txt"
LOAD_DATA_FILE = "Residential load data 30-min resolution.npy"      # (profiles, days, steps) in kW
ANNUAL_PV_FILE = "Residential PV data 30-min resolution.npy"        # (days, steps), normalised 0-1
SEASON_PV_FILES = {"Summer": ("Residential_PV_profiles_Summer.npy", 21), # (file with 3 profiles, day to study)
                   "Autumn": ("Residential_PV_profiles_Autumn.npy", 59),
                   "Winter": ("Residential_PV_profiles_Winter.npy", 199),
                   "Spring": ("Residential_PV_profiles_Spring.npy", 229)}
VOLTAGE_BASES_KV = (22.0, 0.4)
LIMITS_PU = (0.94, 1.10)                       # statutory limits: -6 % / +10 % of 230 V
TRANSFORMER_RATING_KVA = 175.0                 # rating used for the utilisation in E.2
SCENARIO_OPTIONS = dict(seed=10, pv_kva=10.0, pf_range=(0.9, 0.98))   # same for every scenario
PENETRATIONS = [0, 20, 40, 60, 80, 100]        # % of customers with PV
TUTORIAL_DAYS = [0, 1, 2]                      # days simulated in Part A
REUSE_CIRCUIT = False                          # True = build once, swap profiles (faster on large feeders)
VERIFY_REUSE = False                           # True = check reuse gives the same results as a rebuild
RESULTS_FOLDER = None                          # e.g. "results/tut_2": results table (CSV) + figures (keep gitignored)


def output_path(name):
    return Path(RESULTS_FOLDER) / name if RESULTS_FOLDER else None


def show(fig, name):
    plots.show_or_save(fig, output_path(name))


SUMMARY_COLUMNS = [("Window", "window", "s"), ("PV %", "penetration", "d"), ("PV systems", "n_pv", "d"),
                   ("Non-compliant", "n_noncompliant", "d"), ("Over", "n_over", "d"), ("Under", "n_under", "d"),
                   ("V min (pu)", "v_min", ".4f"), ("V max (pu)", "v_max", ".4f"), ("Peak |S| (kVA)", "s_peak", ".1f"),
                   ("Utilisation (%)", "utilisation", ".1f"), ("Min P (kW)", "p_min", ".1f")]


def print_summary(table, title):
    """Print a results table (DataFrame from hosting.run_study) with the columns above."""
    rows = [[reports.fmt(r[k], f) for _, k, f in SUMMARY_COLUMNS] for r in table.to_dict("records")]
    reports.print_table([h for h, _, _ in SUMMARY_COLUMNS], rows, title)


# =============================================================================================
# Part A - Tutorial
# =============================================================================================
master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER)
data_folder = str(master_file.parent)
engine = eng.start_engine()
plots.apply_style()

# A.1 The network
eng.build_circuit(engine, master_file, VOLTAGE_BASES_KV)
reports.print_element_counts(net.element_counts(engine))
print("DER already in the files:", net.has_der(engine))
reports.print_load_inventory(net.load_inventory(engine))
show(plots.plot_network_map(engine, title="LV circuit", labels="short"), "fig_network.png")  # needs bus coordinates

# A.2 The profile data
load_data = ts.load_profile_data(paths.locate_file(LOAD_DATA_FILE, data_folder, verbose=False))
annual_pv = ts.load_profile_data(paths.locate_file(ANNUAL_PV_FILE, data_folder, verbose=False))
show(plots.plot_time_series(load_data[:, TUTORIAL_DAYS[0], :], f"All load profiles, day {TUTORIAL_DAYS[0]}",
                            "Active power (kW)", colour="#2a78d6", alpha=0.15), "fig_load_profiles.png")
show(plots.plot_time_series(annual_pv, "Normalised PV profiles, every day of the year", "PV output (pu)",
                            colour="#eda100", alpha=0.08), "fig_pv_profiles_year.png")

# A.3 Daily simulations at 100 % penetration: demand AND PV both come from their data for each day
setup = hosting.StudySetup(master_file=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV, limits=LIMITS_PU,
                           transformer_rating_kva=TRANSFORMER_RATING_KVA)
customers = hosting.study_customers(engine, setup)
tutorial_scenarios = [sc.random_scenario(customers, load_data, annual_pv, sc.TimeWindow.days(day), 100, **SCENARIO_OPTIONS)
                      for day in TUTORIAL_DAYS]
tutorial_table, tutorial = hosting.run_study(engine, setup, tutorial_scenarios, keep_simulations=True,
                                             reuse_circuit=REUSE_CIRCUIT)
print_summary(tutorial_table, f"Part A: days {TUTORIAL_DAYS} at 100 % penetration (annual PV data)")
show(plots.plot_panels({f"Day {d}": s["V"] for d, s in zip(TUTORIAL_DAYS, tutorial)}, "Customer voltage (pu)",
                       limits=LIMITS_PU, title="Customer voltages, 100 % PV penetration"), "fig_tutorial_voltages.png")
show(plots.plot_time_series(annual_pv[TUTORIAL_DAYS], "PV profiles of the simulated days", "PV output (pu)",
                            labels=[f"Day {d}" for d in TUTORIAL_DAYS]), "fig_tutorial_pv.png")

# A.4 Check that OpenDSS used the scenario's demand: scenario profile vs simulated demand of one customer
first = tutorial[0]
customer = first["loads"][0]
given = first["scenario"].demand[customer][0]
show(plots.plot_time_series([given, first["P"][0]], f"Demand check, {customer}", "Active power (kW)",
                            labels=["scenario profile", "simulated (OpenDSS)"], styles=["-", "--"]), "fig_demand_check.png")
print(f"Largest difference between scenario and simulated demand of {customer}: {np.abs(given - first['P'][0]).max():.2e} kW")

# =============================================================================================
# Part B - Exercise: hosting capacity per season
# =============================================================================================
results_file = output_path("tut_2_results.csv")
if results_file and results_file.exists():
    results_file.unlink()                                  # start a fresh results table
results = {}
for season, (pv_file, day) in SEASON_PV_FILES.items():
    candidates = np.load(paths.locate_file(pv_file, data_folder, verbose=False))
    window = sc.TimeWindow.days(day)
    # Same demand for every case of this day; the seasonal PV profile replaces the annual one
    full_pv = sc.random_scenario(customers, load_data, annual_pv, window, 100, **SCENARIO_OPTIONS)
    worst, v_max = hosting.worst_case_pv_profile(engine, setup, full_pv, candidates, REUSE_CIRCUIT)
    print(f"\n{season} (day {day}): highest voltage at 100 % PV for each profile = "
          f"{[round(float(v), 4) for v in v_max]} -> worst case is profile {worst}")
    scenarios = [s.with_pv_profile(candidates[worst], season=season, pv_profile=worst)
                 for s in sc.penetration_scenarios(customers, load_data, annual_pv, window, PENETRATIONS, **SCENARIO_OPTIONS)]
    table, sims = hosting.run_study(engine, setup, scenarios, results_file=results_file, keep_simulations=True,
                                    reuse_circuit=REUSE_CIRCUIT)
    results[season] = {"day": day, "worst": worst, "table": table, "sims": sims}
    print_summary(table, f"E.1 / E.2 - {season}, day {day}, PV profile {worst} (transformer rating {TRANSFORMER_RATING_KVA:.0f} kVA)")

all_results = pd.concat([r["table"] for r in results.values()], ignore_index=True)
if results_file:
    print(f"\nResults table ({len(all_results)} runs) saved to {results_file}")

# E.1 Non-compliant customers vs penetration
show(plots.plot_lines_vs_x(PENETRATIONS, {s: r["table"]["n_noncompliant"].tolist() for s, r in results.items()},
                           "PV penetration (% of customers)", "Non-compliant customers",
                           "E.1 Customers outside the voltage limits"), "fig_e1_noncompliant.png")
show(plots.plot_panels({s: r["sims"][-1]["V"] for s, r in results.items()}, "Customer voltage (pu)", limits=LIMITS_PU,
                       title="E.1 Customer voltages at 100 % PV penetration (worst-case profile)"), "fig_e1_voltages.png")

# E.2 Transformer active / reactive power per phase and utilisation
for season, r in results.items():
    sim = r["sims"][-1]
    show(plots.plot_panels({"Active power P (kW)": sim["tx_P"].T, "Reactive power Q (kvar)": sim["tx_Q"].T},
                           "kW / kvar", title=f"E.2 Transformer power per phase, {season}, 100 % PV (negative = reverse flow)",
                           labels=["Phase A", "Phase B", "Phase C"]), f"fig_e2_transformer_{season.lower()}.png")
show(plots.plot_lines_vs_x(PENETRATIONS, {s: r["table"]["utilisation"].tolist() for s, r in results.items()},
                           "PV penetration (% of customers)", "Peak utilisation (%)",
                           f"E.2 Transformer utilisation (rating {TRANSFORMER_RATING_KVA:.0f} kVA)", hline=100),
     "fig_e2_utilisation.png")

# E.3 Hosting capacity
capacity = {s: hosting.hosting_capacity(r["table"]) for s, r in results.items()}
reports.print_table(["Season", "Day", "PV profile", "Hosting capacity (% of customers)", "PV systems"],
                    [[s, r["day"], r["worst"], "below 20" if capacity[s] == 0 else capacity[s],
                      round(len(customers) * (capacity[s] or 0) / 100)] for s, r in results.items()],
                    "E.3 PV hosting capacity (no non-compliant customer and transformer within its rating)")
known = [c for c in capacity.values() if c is not None]
print(f"Hosting capacity of the circuit (worst season) = {min(known)} % of customers with "
      f"{SCENARIO_OPTIONS['pv_kva']:.0f} kVA PV" if known else "No penetration meets the limits")

# Optional: check that reuse_circuit gives the same results as a full rebuild on this network
if VERIFY_REUSE:
    hosting.verify_reuse(engine, setup, tutorial_scenarios + scenarios)