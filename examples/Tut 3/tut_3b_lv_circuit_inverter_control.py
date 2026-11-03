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
#   3. Repeats every penetration over N_RUNS_PER_PENETRATION randomized runs, redrawing the random
#      items chosen in section 4 for every run.
#   4. Counts every day of every run as one day-case. A day-case passes when its violations
#      (non-compliant customers, plus TRANSFORMER_OVERLOAD_WEIGHT if the transformer goes over its
#      rating) are within VIOLATION_THRESHOLD. With a sweep, the hosting capacity of each PV mode is
#      the highest penetration (and every lower one) where at least PASS_SHARE_THRESHOLD_PCT % of
#      day-cases pass.
#
# Load data is active power only (kW): reactive power comes from a random power factor per
# customer and time step (section 8). Every random choice has its own named seed; with all seeds
# fixed, a run is repeated exactly.
#
# Settings are grouped in the order a user would choose them in an interface (see the Tut 3
# selection flow diagram). Figures are only saved to the results folders, never shown.
#
# Avry Krywolt, November 2, 2026

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

from dss_toolkit import (engine as eng, hosting, network as net, paths, plots, reports, results as res,
                         scenario as sc, timeseries as ts)

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
PV_RATINGS_KVA = (10.0, 16.6, 30.0)                            # random build: ratings a PV system can get (kVA = Pmpp)
PV_RATING_WEIGHTS = (1, 1, 2)                                # chance of each rating (None = equal chances)
PV_RATING_SEED = 1                                           # random build: which rating each PV gets
PV_PLACEMENT_SEED = 1                                        # random build: which customers get PV
PV_SITES = [                                                 # sites build: load name and rating of each PV
    {"customer": "Load_MG1_1", "kva": 5.0},
    {"customer": "Load_MG1_8", "kva": 10.0},
    {"customer": "Load_MG1_15", "kva": 7.5},
    {"customer": "Load_MG1_31", "kva": 10.0},
]

# ---- 4. Penetration run (random build): "single" or "sweep", and randomized runs -------------
PENETRATION_RUN = "sweep"
SINGLE_PENETRATION_PCT = 100                                 # "single": compare the PV modes at this %
SWEEP_PENETRATIONS_PCT = (40, 60, 80, 100)            # "sweep": every % -> hosting capacity per mode
N_RUNS_PER_PENETRATION = 10                                  # randomized runs per penetration (1 to 1000)
DAYS_PER_RUN = "all_sampled"                                 # "all_sampled" (section 6) or "worst_only" (rank 0)
REDRAW_PV_PLACEMENT = True                                   # draw again for every run? (False = same for all runs)
REDRAW_PV_RATING = False
REDRAW_LOAD_DAY = False                                      # only used when the load day is not matched (section 7)
REDRAW_LOAD_PROFILE = True
REDRAW_POWER_FACTOR = True
INTRA_PENETRATION_SEED = 1                                   # seeds of the redrawn items for runs 1, 2, ... (run 0 = own seeds)

# ---- 5. PV operation: any 1 to 4 of "no_pv", "pv", "pv_volt_watt", "pv_volt_var" -------------
PV_MODES = ("pv_volt_watt", "pv_volt_var")
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
RANK_INTERVAL = 45                                           # simulate ranks 0, 25, 50 ... (0 = highest peak)
INCLUDE_BEST_DAY = True                                      # also simulate the last rank (lowest peak)

# ---- 7. Load day: matched to the PV day, or a random day -----------------------------------
USE_MATCHED_LOAD_DAY = True                                  # True: load day = PV day (LOAD_DAY_SEED unused)
LOAD_DAY_SEED = 1                                            # False: random load day for each PV day

# ---- 8. Demand per load (always random, each with its own seed) -----------------------------
LOAD_PROFILE_SEED = 1                                        # which of the 342 profiles each load gets
POWER_FACTOR_SEED = 1                                        # power factor per load and step -> kvar
POWER_FACTOR_RANGE = (0.90, 0.98)

# ---- 9. Pass / fail and hosting capacity ----------------------------------------------------
VIOLATION_THRESHOLD = 10                                     # largest violation score a day-case may have and pass
VIOLATION_THRESHOLD_UNIT = "pct_of_customers"                # "customers" or "pct_of_customers"
TRANSFORMER_OVERLOAD_WEIGHT = 5                              # a transformer overload counts as this many violations
PASS_SHARE_THRESHOLD_PCT = 90                                # % of day-cases that must pass at the hosting capacity

# ---- 10. Outputs ---------------------------------------------------------------------------
RESULTS_FOLDER = "results/tut3/lv_test_circuit"              # from the repo root
SAVE_SIMULATIONS = False                                     # also save every daily run's time series (.npz; large)

# =============================================================================================
# Circuit and data
# =============================================================================================
project_root = paths.find_project_root(SCRIPT_FOLDER)
master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER, start=SCRIPT_FOLDER, verbose=False)
data_folder = master_file.parent
setup = hosting.StudySetup(circuit_source=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV,
                           limits=VOLTAGE_LIMITS_PU, transformer_rating_kva=TRANSFORMER_RATING_KVA,
                           bus_coordinates=data_folder / BUS_COORDINATES_FILE_NAME)
engine = eng.start_engine()
plots.apply_style()
customers = hosting.list_customers(engine, setup)
setup.customer_phases = net.customer_phases(engine)
load_profiles_kw = ts.read_profile_file(data_folder / LOAD_PROFILE_FILE_NAME)
pv_profiles_pu = ts.read_profile_file(data_folder / PV_PROFILE_FILE_NAME)

# =============================================================================================
# Study plan (every selection above) and results folders
# =============================================================================================
plan = sc.StudyPlan(
    circuit_name=CIRCUIT_NAME,
    pv_build=PV_BUILD, pv_ratings_kva=PV_RATINGS_KVA, pv_rating_weights=PV_RATING_WEIGHTS,
    pv_rating_seed=PV_RATING_SEED, pv_placement_seed=PV_PLACEMENT_SEED, pv_sites=PV_SITES,
    penetration_run=PENETRATION_RUN,
    penetrations_pct=SWEEP_PENETRATIONS_PCT if PENETRATION_RUN == "sweep" else (SINGLE_PENETRATION_PCT,),
    n_runs_per_penetration=N_RUNS_PER_PENETRATION, days_per_run=DAYS_PER_RUN,
    redraw_pv_placement=REDRAW_PV_PLACEMENT, redraw_pv_rating=REDRAW_PV_RATING, redraw_load_day=REDRAW_LOAD_DAY,
    redraw_load_profile=REDRAW_LOAD_PROFILE, redraw_power_factor=REDRAW_POWER_FACTOR,
    intra_penetration_seed=INTRA_PENETRATION_SEED,
    pv_modes=PV_MODES, inverter_controls={"volt_watt": VOLT_WATT_CURVE, "volt_var": VOLT_VAR_CURVE},
    rank_interval=RANK_INTERVAL, include_best_day=INCLUDE_BEST_DAY,
    use_matched_load_day=USE_MATCHED_LOAD_DAY, load_day_seed=LOAD_DAY_SEED,
    load_profile_seed=LOAD_PROFILE_SEED, power_factor_seed=POWER_FACTOR_SEED, power_factor_range=POWER_FACTOR_RANGE)
for note in plan.notes():
    print(f"NOTE: {note}")

run_folder = project_root / RESULTS_FOLDER / ("penetration_sweep" if plan.is_sweep else "single_penetration")
shutil.rmtree(run_folder, ignore_errors=True)                # fresh results for this run type


def penetration_folder(penetration_pct):
    """Sweep: one subfolder per penetration (no PV = pen_000). Single penetration: the run folder."""
    if not plan.is_sweep or penetration_pct is None:
        return run_folder
    return run_folder / f"pen_{int(penetration_pct):03d}"


max_violations = hosting.violation_limit(VIOLATION_THRESHOLD, VIOLATION_THRESHOLD_UNIT, len(customers))
res.save_settings({**asdict(plan), "violation_threshold": VIOLATION_THRESHOLD,
                   "violation_threshold_unit": VIOLATION_THRESHOLD_UNIT, "max_violation_score": max_violations,
                   "transformer_overload_weight": TRANSFORMER_OVERLOAD_WEIGHT,
                   "pass_share_threshold_pct": PASS_SHARE_THRESHOLD_PCT}, run_folder / "settings.json")

sampled_days = sc.plan_days(plan, pv_profiles_pu)
worst_rank, best_rank = sampled_days[0][0], sampled_days[-1][0]
day_names = {worst_rank: "worst_day"} if worst_rank == best_rank else {worst_rank: "worst_day", best_rank: "best_day"}
plots.save_figure(plots.plot_network_map(engine, title="LV test circuit", labels="short"), run_folder / "fig01_network_map.png")
plots.save_figure(plots.plot_pv_day_ranking(pv_profiles_pu, sc.rank_pv_days(pv_profiles_pu), sampled_days),
                  run_folder / "fig02_pv_day_ranking.png")

n_daily_runs = plan.n_scenarios(len(sampled_days))
expected = hosting.estimate_runtime(engine, setup, sc.iter_plan_scenarios(plan, customers, load_profiles_kw, pv_profiles_pu),
                                    n_daily_runs)
print(f"{CIRCUIT_NAME}: {N_RUNS_PER_PENETRATION} runs x {len(sampled_days)} PV days x {len(PV_MODES)} PV modes"
      f"{f' x {len(plan.penetrations_to_run)} penetrations' if plan.is_sweep else ''} = {n_daily_runs} daily power flows, "
      f"about {hosting.format_duration(expected)}")

# =============================================================================================
# Run: every randomized run x PV day x PV mode x penetration
# =============================================================================================
time_series = res.TimeSeriesAverage()                        # worst- and best-day time series, averaged over runs


def keep_time_series(sim, row):
    if row["pv_rank"] in day_names:
        time_series.add((row["penetration_pct"], row["pv_mode"], row["pv_rank"]), sim)


table, _ = hosting.run_study(
    engine, setup, sc.iter_plan_scenarios(plan, customers, load_profiles_kw, pv_profiles_pu, setup.customer_phases),
    results_file=lambda row: penetration_folder(row["penetration_pct"]) / "runs.csv",
    simulations_folder=(lambda row: penetration_folder(row["penetration_pct"]) / "simulations") if SAVE_SIMULATIONS else None,
    on_simulation=keep_time_series, n_scenarios=n_daily_runs, progress_every=max(1, n_daily_runs // 10))
if not table["converged"].all():
    print(f"WARNING: {(~table['converged']).sum()} daily runs did not converge at every step (see 'converged' in runs.csv)")

# =============================================================================================
# Pass share, averages over runs, hosting capacity
# =============================================================================================
mode_labels, mode_colours = sc.PV_MODES, plots.PV_MODE_COLOURS
scored = hosting.score_day_cases(table, max_violations, TRANSFORMER_OVERLOAD_WEIGHT)
pass_shares = hosting.pass_share_table(scored)
averaged = hosting.average_runs(scored, ("pv_mode", "penetration_pct", "pv_rank"))
pass_shares.to_csv(run_folder / "pass_share_by_penetration.csv", index=False)
averaged.to_csv(run_folder / "runs_averaged_by_day.csv", index=False)
reports.print_summary_table(pass_shares, [
    ("PV mode", "pv_mode", "s"), ("PV %", "penetration_pct", "d"), ("Runs", "n_runs", "d"), ("Days", "n_days", "d"),
    ("Day-cases", "n_day_cases", "d"), ("Passed", "n_passed", "d"), ("Pass share (%)", "pass_share_pct", ".1f"),
    ("With V violations", "n_voltage_violation_cases", "d"), ("With overload", "n_overload_cases", "d"),
    ("Mean score", "mean_violation_score", ".2f"), ("Worst score", "max_violation_score", "d")],
    f"Day-cases passing (violation score <= {max_violations:g}; overload = {TRANSFORMER_OVERLOAD_WEIGHT} violations)")


def rows_at(frame, penetration_pct):
    """Rows of one penetration plus the no-PV baseline (no PV is simulated once, at 0 %)."""
    at = frame["penetration_pct"].isna() if penetration_pct is None else frame["penetration_pct"].eq(penetration_pct)
    return frame[at | frame["pv_mode"].eq("no_pv")]


def penetration_text(penetration_pct):
    return "PV sites" if penetration_pct is None else f"{penetration_pct} % PV penetration"


# ---- Figures 3-7 for each penetration (in its own folder) ------------------------------------
best_runs = hosting.best_placement_runs(scored)
for penetration_pct in plan.penetrations_to_run:
    folder, label = penetration_folder(penetration_pct), penetration_text(penetration_pct)
    best = best_runs[best_runs["penetration_pct"].isna() if penetration_pct is None
                     else best_runs["penetration_pct"].eq(penetration_pct)]
    if len(best):
        best = best.iloc[0]
        window = sc.TimeWindow.days(sampled_days[0][1])
        fleet = sc.plan_pv_fleet(plan, customers, ts.profiles_in_window(pv_profiles_pu, window), penetration_pct,
                                 int(best["random_run"]))
        plots.save_figure(plots.plot_der_map(
            engine, sc.Scenario(window, {}, fleet), customer_phases=setup.customer_phases,
            title=f"PV placement, {label}: best of {N_RUNS_PER_PENETRATION} runs (run {int(best['random_run'])}, "
                  f"{mode_labels[best['pv_mode']]}, violation score {best['violation_score']:g} over {len(sampled_days)} days)"),
            folder / "fig03_pv_placement_best_run.png")
    plots.save_figure(plots.plot_metrics_vs_x(
        rows_at(averaged, penetration_pct), "pv_rank",
        {"v_max_pu": "Highest customer voltage (pu)", "n_noncompliant_customers": "Non-compliant customers",
         "pv_curtailed_pct": "PV energy curtailed (%)", "transformer_utilisation_pct": "Peak transformer utilisation (%)"},
        "pv_mode", f"PV modes by PV day rank, {label} (mean of {N_RUNS_PER_PENETRATION} runs)", mode_labels,
        xlabel="PV day rank (0 = highest peak)", hlines={"v_max_pu": VOLTAGE_LIMITS_PU[1]}, group_colours=mode_colours),
        folder / "fig04_modes_by_pv_day_rank.png")
    for rank, day_name in day_names.items():
        day = dict(sampled_days)[rank]
        keys = [k for k in time_series.keys() if k[2] == rank and (k[0] == penetration_pct or k[1] == "no_pv")]
        series = {k[1]: time_series.get(k) for k in sorted(keys, key=lambda k: list(PV_MODES).index(k[1]))}
        title = f"{day_name.replace('_', ' ')} (rank {rank}, day {day}), {label}, mean of {N_RUNS_PER_PENETRATION} runs"
        plots.save_figure(plots.plot_voltage_bands({mode_labels[m]: (s["V_mean"], s["V_min"], s["V_max"]) for m, s in series.items()},
                                                   VOLTAGE_LIMITS_PU, title=f"Customer voltages, {title}"),
                          folder / f"fig05_voltages_{day_name}.png")
        with_pv = {m: s for m, s in series.items() if m != "no_pv"}
        if with_pv:
            first = next(iter(with_pv.values()))
            plots.save_figure(plots.plot_time_series(
                [first["pv_available_P_mean"]] + [s["pv_P_mean"] for s in with_pv.values()],
                f"Total PV active power, {title}", "kW", labels=["Available"] + [mode_labels[m] for m in with_pv],
                styles=[":"] + ["-"] * len(with_pv), colours=[mode_colours["available"]] + [mode_colours[m] for m in with_pv]),
                folder / f"fig06_pv_active_power_{day_name}.png")
            plots.save_figure(plots.plot_time_series(
                [s["pv_Q_mean"] for s in with_pv.values()], f"Total PV reactive power, {title}", "kvar (negative = absorbed)",
                labels=[mode_labels[m] for m in with_pv], colours=[mode_colours[m] for m in with_pv]),
                folder / f"fig07_pv_reactive_power_{day_name}.png")

# ---- Sweep: figures 8-10 and hosting capacity (in the sweep folder) ---------------------------
if plan.is_sweep:
    pv_pass_shares = pass_shares[pass_shares["pv_mode"] != "no_pv"]
    capacity = hosting.hosting_capacity_from_pass_share(pv_pass_shares, PASS_SHARE_THRESHOLD_PCT)
    capacity.to_csv(run_folder / "hosting_capacity.csv", index=False)
    reports.print_summary_table(capacity, [
        ("PV mode", "pv_mode", "s"), ("Hosting capacity (%)", "hosting_capacity_pct", "d"),
        ("Day-cases", "n_day_cases", "d"), ("Passed", "n_passed", "d"), ("Pass share (%)", "pass_share_pct", ".1f")],
        f"Hosting capacity: at least {PASS_SHARE_THRESHOLD_PCT} % of day-cases pass at it and every lower penetration")
    for rank, day_name in day_names.items():
        plots.save_figure(plots.plot_metrics_vs_x(
            averaged[averaged["pv_rank"].eq(rank) & averaged["pv_mode"].ne("no_pv")], "penetration_pct",
            {"n_noncompliant_customers": "Non-compliant customers", "v_max_pu": "Highest customer voltage (pu)",
             "pv_curtailed_pct": "PV energy curtailed (%)", "transformer_utilisation_pct": "Peak transformer utilisation (%)"},
            "pv_mode", f"PV modes by penetration, {day_name.replace('_', ' ')} (rank {rank}), mean of {N_RUNS_PER_PENETRATION} runs",
            mode_labels, xlabel="PV penetration (% of customers)", hlines={"v_max_pu": VOLTAGE_LIMITS_PU[1]},
            group_colours=mode_colours), run_folder / f"fig08_modes_by_penetration_{day_name}.png")
    notes = [f"{int(r['n_passed'])} of {int(r['n_day_cases'])} day-cases passed ({r['pass_share_pct']:.1f} %)"
             if r["hosting_capacity_pct"] == r["hosting_capacity_pct"] else "lowest penetration failed"
             for r in capacity.to_dict("records")]
    plots.save_figure(plots.plot_bars(
        [mode_labels[m] for m in capacity["pv_mode"]], list(capacity["hosting_capacity_pct"]),
        "Hosting capacity (% of customers)", "PV hosting capacity per PV mode", missing_text="fails at lowest %",
        colours=[mode_colours[m] for m in capacity["pv_mode"]], notes=notes,
        footnote=f"Day-case passes: violation score <= {max_violations:g} (overload = {TRANSFORMER_OVERLOAD_WEIGHT}); "
                 f"hosting capacity needs >= {PASS_SHARE_THRESHOLD_PCT} % of day-cases passing "
                 f"({N_RUNS_PER_PENETRATION} runs x {len(sampled_days)} days per penetration)."),
        run_folder / "fig09_hosting_capacity.png")
    plots.save_figure(plots.plot_metrics_vs_x(
        pv_pass_shares, "penetration_pct", {"pass_share_pct": "Day-cases passing (%)",
                                            "voltage_violation_case_pct": "Day-cases with voltage violations (%)",
                                            "overload_case_pct": "Day-cases with transformer overload (%)"}, "pv_mode",
        f"Day-cases by penetration ({N_RUNS_PER_PENETRATION} runs x {len(sampled_days)} days each)", mode_labels,
        xlabel="PV penetration (% of customers)", hlines={"pass_share_pct": PASS_SHARE_THRESHOLD_PCT}, ncols=3,
        group_colours=mode_colours),
        run_folder / "fig10_pass_share_by_penetration.png")

print(f"\nResults ({len(table)} daily runs) and figures saved to {run_folder}")
