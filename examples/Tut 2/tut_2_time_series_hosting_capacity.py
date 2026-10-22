# Team Nando Tutorial 2 (time-series analysis and PV hosting capacity of an LV network),
# completed with the dss_toolkit functions (src/dss_toolkit)
#
#   Part A: the tutorial - daily load and PV profiles allocated to every customer, 30-min power flows
#   Part B: the exercise - worst-case seasonal PV profile, penetration sweep 0-100 %,
#           non-compliant customers (E.1), transformer utilisation (E.2) and hosting capacity (E.3)
#
# CLAUDE, October 19, 2026

import sys
from pathlib import Path

# Make src/ importable (not needed if the project is installed with: pip install -e .)
for folder in Path(__file__).resolve().parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

import numpy as np

from dss_toolkit import engine as eng, hosting, network as net, paths, plots, reports, timeseries as ts

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
PV_KVA = 10.0                                  # inverter (and panel) size of every PV system
TRANSFORMER_RATING_KVA = 175.0                 # rating used for the utilisation in E.2
PENETRATIONS = [0, 20, 40, 60, 80, 100]        # % of customers with PV
TUTORIAL_DAYS = [0, 1, 2]                      # days simulated in Part A
SEED = 10
FIGURE_FOLDER = None                           # e.g. "results/tut_2" to save the figures


def figure_path(name):
    return Path(FIGURE_FOLDER) / name if FIGURE_FOLDER else None


def show(fig, name):
    plots.show_or_save(fig, figure_path(name))


def summary_rows(summaries):
    """Rows of the E.1 / E.2 table for one season."""
    return [[s["penetration"], s["n_pv"], s["n_noncompliant"], s["n_over"], s["n_under"],
             reports.fmt(s["v_min"], ".4f"), reports.fmt(s["v_max"], ".4f"), reports.fmt(s["s_peak"], ".1f"),
             reports.fmt(s["utilisation"], ".1f"), reports.fmt(s["p_min"], ".1f")] for s in summaries]


SUMMARY_HEADERS = ["PV %", "PV systems", "Non-compliant", "Over", "Under", "V min (pu)", "V max (pu)",
                   "Peak |S| (kVA)", "Utilisation (%)", "Min P (kW)"]

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
show(plots.plot_network_map(engine, title="LV circuit"), "fig_network.png")   # skipped: no bus coordinates

# A.2 The profile data
load_data = ts.load_profile_data(paths.locate_file(LOAD_DATA_FILE, data_folder, verbose=False))
annual_pv = ts.load_profile_data(paths.locate_file(ANNUAL_PV_FILE, data_folder, verbose=False))
show(plots.plot_time_series(load_data[:, TUTORIAL_DAYS[0], :], f"All load profiles, day {TUTORIAL_DAYS[0]}",
                            "Active power (kW)", colour="#2a78d6", alpha=0.15), "fig_load_profiles.png")
show(plots.plot_time_series(annual_pv, "Normalised PV profiles, every day of the year", "PV output (pu)",
                            colour="#eda100", alpha=0.08), "fig_pv_profiles_year.png")

# A.3 Daily simulations at 100 % penetration with the annual PV data
setup = hosting.StudySetup(master_file=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV, load_data=load_data,
                           limits=LIMITS_PU, transformer_rating_kva=TRANSFORMER_RATING_KVA, pv_kva=PV_KVA, seed=SEED)
tutorial = {day: hosting.simulate_day(engine, setup, day, annual_pv[day], 100) for day in TUTORIAL_DAYS}
reports.print_table(SUMMARY_HEADERS, summary_rows([hosting.summarise_day(s, LIMITS_PU) for s in tutorial.values()]),
                    f"Part A: days {TUTORIAL_DAYS} at 100 % penetration (annual PV data)")
show(plots.plot_panels({f"Day {d}": s["V"] for d, s in tutorial.items()}, "Customer voltage (pu)", limits=LIMITS_PU,
                       title="Customer voltages, 100 % PV penetration"), "fig_tutorial_voltages.png")
show(plots.plot_time_series(annual_pv[TUTORIAL_DAYS], "PV profiles of the simulated days", "PV output (pu)",
                            labels=[f"Day {d}" for d in TUTORIAL_DAYS]), "fig_tutorial_pv.png")

# A.4 Check that OpenDSS used the allocated profile: allocated vs simulated demand of one customer
first = tutorial[TUTORIAL_DAYS[0]]
customer = first["loads"][0]
show(plots.plot_time_series([first["allocation"][customer][1], first["P"][0]], f"Demand check, {customer}",
                            "Active power (kW)", labels=["allocated profile", "simulated (OpenDSS)"], styles=["-", "--"]),
     "fig_demand_check.png")
print(f"Largest difference between allocated and simulated demand of {customer}: "
      f"{np.abs(first['allocation'][customer][1] - first['P'][0]).max():.2e} kW")

# =============================================================================================
# Part B - Exercise: hosting capacity per season
# =============================================================================================
results = {}
for season, (pv_file, day) in SEASON_PV_FILES.items():
    candidates = np.load(paths.locate_file(pv_file, data_folder, verbose=False))
    worst, v_max = hosting.worst_case_pv_profile(engine, setup, day, candidates)
    print(f"\n{season} (day {day}): highest voltage at 100 % PV for each profile = "
          f"{[round(float(v), 4) for v in v_max]} -> worst case is profile {worst}")
    summaries, sims = hosting.penetration_sweep(engine, setup, day, candidates[worst], PENETRATIONS)
    results[season] = {"day": day, "worst": worst, "pv_shape": candidates[worst], "summaries": summaries, "sims": sims}
    reports.print_table(SUMMARY_HEADERS, summary_rows(summaries),
                        f"E.1 / E.2 - {season}, day {day}, PV profile {worst} (transformer rating {TRANSFORMER_RATING_KVA:.0f} kVA)")

# E.1 Non-compliant customers vs penetration
show(plots.plot_lines_vs_x(PENETRATIONS, {s: [x["n_noncompliant"] for x in r["summaries"]] for s, r in results.items()},
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
show(plots.plot_lines_vs_x(PENETRATIONS, {s: [x["utilisation"] for x in r["summaries"]] for s, r in results.items()},
                           "PV penetration (% of customers)", "Peak utilisation (%)",
                           f"E.2 Transformer utilisation (rating {TRANSFORMER_RATING_KVA:.0f} kVA)", hline=100),
     "fig_e2_utilisation.png")

# E.3 Hosting capacity
capacity = {s: hosting.hosting_capacity(r["summaries"]) for s, r in results.items()}
reports.print_table(["Season", "Day", "PV profile", "Hosting capacity (% of customers)", "PV systems"],
                    [[s, r["day"], r["worst"], "below 20" if capacity[s] == 0 else capacity[s],
                      round(len(r["sims"][0]["loads"]) * (capacity[s] or 0) / 100)] for s, r in results.items()],
                    "E.3 PV hosting capacity (no non-compliant customer and transformer within its rating)")
known = [c for c in capacity.values() if c is not None]
print(f"Hosting capacity of the circuit (worst season) = {min(known)} % of customers with {PV_KVA:.0f} kVA PV"
      if known else "No penetration meets the limits")
