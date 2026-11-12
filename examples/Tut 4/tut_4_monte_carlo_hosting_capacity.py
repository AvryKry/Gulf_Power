# Tutorial 4 (Monte Carlo PV hosting capacity on any network), built with dss_toolkit
# (src/dss_toolkit). Combines Team Nando Tutorial 4 (MV-LV network, build once, many randomized
# runs, all assets checked) with the Tutorial 3 study (ranked PV days, four PV modes with IEEE 1547
# inverter control, day-case pass share, hosting capacity).
#
# Any network: change DATA_FOLDER and MASTER_FILE_NAME (section 1). Run tut_4a_network_plot.py first
# on new network data to check it compiles and looks right.
#
# What the script does:
#   1. Compiles the network once and reads it: source, head (substation) transformer, every other
#      transformer, MV and LV lines with a rating, loads and their phases, loads with a fixed shape
#      (e.g. commercial loads, kept as they are), and where each single-phase customer's phase is set.
#   2. Ranks the 365 days of PV data by daily peak (rank 0 = highest peak = worst case) and simulates
#      every RANK_INTERVAL-th day (plus the best day).
#   3. Runs each day in 1-4 PV modes: no PV, PV, PV + volt-watt, PV + volt-var.
#   4. Repeats every penetration over N_RUNS_PER_PENETRATION randomized runs, redrawing the random
#      items chosen in section 3 for every run. PV is added constructively: within a run, a customer
#      with PV at 20 % keeps it (and its rating) at 40 %.
#   5. Counts every day of every run as one day-case. A day-case's violation score = non-compliant
#      customers + TRANSFORMER_OVERLOAD_WEIGHT per overloaded transformer (head included) +
#      LINE_OVERLOAD_WEIGHT per overloaded line. It passes when the score is within
#      VIOLATION_THRESHOLD. With a sweep, the hosting capacity of each PV mode is the highest
#      penetration (and every lower one) where at least PASS_SHARE_THRESHOLD_PCT % of day-cases pass.
#
# Every random choice has its own named seed; with all seeds fixed, a study is repeated exactly.
# Settings are grouped in the order a user would choose them (see the Tut 4 decision tree).
# Figures are only saved to the results folders, never shown.
#
# Avry Krywolt, November 11, 2026

import shutil
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

from dss_toolkit import (basecircuit, engine as eng, hosting, interactive, paths, plots, reports, results as res,
                         scenario as sc, timeseries as ts, topology as topo)

# =============================================================================================
# Settings, in selection order
# =============================================================================================
# ---- 1. Network: a folder and a master file (.dss or .txt), nothing else ----------------------
DATA_FOLDER = "tut_3_data"                                   # folder name, path from the repo root, or full path
MASTER_FILE_NAME = "LVcircuit-master.txt"
VOLTAGE_BASES_KV = (22.0, 0.4)                               # line-to-line; None = set by the data (SetkVBase lines)
BUS_COORDINATES_FILE_NAME = "LVcircuit-buscoords.txt"        # 'bus, x, y' list or SetBusXY file; None = generated
PROFILE_FOLDER = None                                        # folder of the .npy profiles (None = DATA_FOLDER)
LOAD_PROFILE_FILE_NAME = "Residential load data 30-min resolution.npy"   # (profiles, 365 days, 48 steps) in kW
PV_PROFILE_FILE_NAME = "Residential PV data 30-min resolution.npy"       # (365 days, 48 steps), normalised 0-1
VOLTAGE_LIMITS_PU = (0.94, 1.10)                             # statutory limits at the customers
FIXED_LOAD_SHAPES = {}                                       # {load: shape} to fix by hand; {load: None} = random
RATING_OVERRIDES_KVA = {}                                    # {transformer: kVA} replaces a nameplate rating
# CRE21 (Team Nando Tutorial 4, put its tut_4_data folder in examples/Tut 4/):
#   DATA_FOLDER = "tut_4_data"; MASTER_FILE_NAME = "Master.txt"; VOLTAGE_BASES_KV = (66.0, 22.0, 0.4)
#   BUS_COORDINATES_FILE_NAME = None
#   LOAD_PROFILE_FILE_NAME = "Data House - 30 mins resolution.npy"
#   PV_PROFILE_FILE_NAME = "Data PV - 30 mins resolution.npy"
#   PV_RATINGS_KVA = (2.5, 3.5, 5.5, 8.0); PV_RATING_WEIGHTS = (0.08, 0.24, 0.52, 0.16)   (AusNet sizes)
ANONYMISE_REPORT = False                                     # True: codes instead of names in the network checks

# ---- 2. PV build: "random" (PV on a % of customers) or "sites" (the PV_SITES list) ----------
PV_BUILD = "random"
PV_RATINGS_KVA = (5.0, 6.6, 10.0)                            # ratings a random PV system can get (kVA = Pmpp)
PV_RATING_WEIGHTS = (1, 1, 2)                                # chance of each rating (None = equal chances)
PV_RATING_SEED = 1                                           # which rating each customer gets
PV_PLACEMENT_SEED = 1                                        # the order in which customers get PV
PV_SITES = [                                                 # sites build: load name and rating of each PV
    {"customer": "Load_MG1_1", "kva": 5.0},
    {"customer": "Load_MG1_8", "kva": 10.0},
]

# ---- 3. Penetration run (random build) and randomized runs -----------------------------------
PENETRATION_RUN = "sweep"                                    # "single" or "sweep"
SINGLE_PENETRATION_PCT = 100                                 # "single": compare the PV modes at this %
SWEEP_PENETRATIONS_PCT = (0, 20, 40, 60, 80, 100)            # "sweep": every % -> hosting capacity per mode
N_RUNS_PER_PENETRATION = 10                                  # randomized runs per penetration (1 to 1000)
REDRAW_PV_PLACEMENT = True                                   # draw again for every run? (False = same for all runs)
REDRAW_PV_RATING = True
REDRAW_LOAD_DAY = False                                      # only used when the load day is not matched (section 6)
REDRAW_LOAD_PROFILE = True
REDRAW_POWER_FACTOR = True
REDRAW_PHASE_CONNECTION = True                               # only used with RANDOMIZE_PHASE_CONNECTION (section 7)
INTRA_PENETRATION_SEED = 1                                   # seeds of the redrawn items for runs 1, 2 ... (run 0 = own seeds)

# ---- 4. PV operation: any 1 to 4 of "no_pv", "pv", "pv_volt_watt", "pv_volt_var" -------------
PV_MODES = ("no_pv", "pv", "pv_volt_watt", "pv_volt_var")
# Inverter control curves: EDIT HERE to test other settings. Voltage in pu of the inverter's rated
# voltage. Defaults: IEEE Std 1547-2018, Category B (Table 10 volt-watt, Table 8 volt-var).
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

# ---- 5. PV days (fewer days = shorter run) -------------------------------------------------
RANK_INTERVAL = 100                                          # simulate ranks 0, 100, 200, 300 (0 = highest peak)
INCLUDE_BEST_DAY = True                                      # also simulate the last rank (lowest peak)

# ---- 6. Load day: matched to the PV day, or a random day -----------------------------------
USE_MATCHED_LOAD_DAY = True                                  # True: load day = PV day (LOAD_DAY_SEED unused)
LOAD_DAY_SEED = 1                                            # False: random load day for each PV day

# ---- 7. Customers (loads without a fixed shape) ----------------------------------------------
LOAD_PROFILE_SEED = 1                                        # which profile each customer gets
POWER_FACTOR_SEED = 1                                        # power factor per customer and step -> kvar
POWER_FACTOR_RANGE = (0.90, 0.98)
RANDOMIZE_PHASE_CONNECTION = False                           # True: single-phase customers get a random phase
PHASE_CONNECTION_SEED = 1                                    # (PV follows its customer's phase)

# ---- 8. Pass / fail and hosting capacity ----------------------------------------------------
VIOLATION_THRESHOLD = 10                                     # largest violation score a day-case may have and pass
VIOLATION_THRESHOLD_UNIT = "pct_of_customers"                # "customers" or "pct_of_customers"
TRANSFORMER_OVERLOAD_WEIGHT = 5                              # each overloaded transformer counts as this many violations
LINE_OVERLOAD_WEIGHT = 5                                     # each overloaded line counts as this many violations
PASS_SHARE_THRESHOLD_PCT = 90                                # % of day-cases that must pass at the hosting capacity

# ---- 9. Outputs: any of the groups below (tables and settings.json are always saved) ----------
OUTPUTS = ("study_figures", "penetration_figures", "box_plots", "network_map_html")
RESULTS_FOLDER = "results/tut4"                              # from the repo root; then <network>/<run type>/

# =============================================================================================
# 1. Network: compile once, read it, give every bus coordinates
# =============================================================================================
project_root = paths.find_project_root(SCRIPT_FOLDER)
master_file = paths.locate_file(MASTER_FILE_NAME, DATA_FOLDER, start=SCRIPT_FOLDER, verbose=False)
data_folder = master_file.parent
profile_folder = (paths.locate_file(LOAD_PROFILE_FILE_NAME, PROFILE_FOLDER, start=SCRIPT_FOLDER, verbose=False).parent
                  if PROFILE_FOLDER else data_folder)
coordinates_file = data_folder / BUS_COORDINATES_FILE_NAME if BUS_COORDINATES_FILE_NAME else None
anon = reports.Anonymiser(ANONYMISE_REPORT)
engine = eng.start_engine()
plots.apply_style()

eng.build_circuit(engine, str(master_file), VOLTAGE_BASES_KV, bus_coordinates=coordinates_file)
info = topo.read_network(engine, RATING_OVERRIDES_KVA, FIXED_LOAD_SHAPES)
coords_share = len(info.coordinates) / max(len(info.buses), 1)
reports.print_network_checks(info, coords_share, anon)
coords = topo.generate_layout(info)                         # data coordinates, completed or generated
generated = {bus: xy for bus, xy in coords.items() if bus not in info.coordinates}
setup = hosting.StudySetup(circuit_source=str(master_file), voltage_bases_kv=VOLTAGE_BASES_KV, limits=VOLTAGE_LIMITS_PU,
                           bus_coordinates=[coordinates_file, generated],   # the data file keeps any SetkVBase lines
                           customer_phases=info.load_phases)
customers = info.random_customers                            # random profiles and PV; fixed-shape loads keep theirs
load_profiles_kw = ts.read_profile_file(profile_folder / LOAD_PROFILE_FILE_NAME)
pv_profiles_pu = ts.read_profile_file(profile_folder / PV_PROFILE_FILE_NAME)
network_name = info.circuit_name.lower()

# =============================================================================================
# 2. Study plan (every selection above) and results folders
# =============================================================================================
plan = sc.StudyPlan(
    circuit_name=network_name,
    pv_build=PV_BUILD, pv_ratings_kva=PV_RATINGS_KVA, pv_rating_weights=PV_RATING_WEIGHTS,
    pv_rating_seed=PV_RATING_SEED, pv_placement_seed=PV_PLACEMENT_SEED, pv_sites=PV_SITES,
    penetration_run=PENETRATION_RUN,
    penetrations_pct=SWEEP_PENETRATIONS_PCT if PENETRATION_RUN == "sweep" else (SINGLE_PENETRATION_PCT,),
    n_runs_per_penetration=N_RUNS_PER_PENETRATION,
    redraw_pv_placement=REDRAW_PV_PLACEMENT, redraw_pv_rating=REDRAW_PV_RATING, redraw_load_day=REDRAW_LOAD_DAY,
    redraw_load_profile=REDRAW_LOAD_PROFILE, redraw_power_factor=REDRAW_POWER_FACTOR,
    redraw_phase_connection=REDRAW_PHASE_CONNECTION, intra_penetration_seed=INTRA_PENETRATION_SEED,
    pv_modes=PV_MODES, inverter_controls={"volt_watt": VOLT_WATT_CURVE, "volt_var": VOLT_VAR_CURVE},
    rank_interval=RANK_INTERVAL, include_best_day=INCLUDE_BEST_DAY,
    use_matched_load_day=USE_MATCHED_LOAD_DAY, load_day_seed=LOAD_DAY_SEED,
    load_profile_seed=LOAD_PROFILE_SEED, power_factor_seed=POWER_FACTOR_SEED, power_factor_range=POWER_FACTOR_RANGE,
    randomize_phase_connection=RANDOMIZE_PHASE_CONNECTION, phase_connection_seed=PHASE_CONNECTION_SEED)
for note in plan.notes():
    print(f"NOTE: {note}")
if RANDOMIZE_PHASE_CONNECTION and not info.tap_points:
    print("NOTE: no single-phase customer's phase can be changed in this network: phases are kept as in the data")

run_folder = project_root / RESULTS_FOLDER / network_name / ("penetration_sweep" if plan.is_sweep else "single_penetration")
shutil.rmtree(run_folder, ignore_errors=True)                # fresh results for this run type
box_folder = run_folder / "box_plots"


def penetration_folder(penetration_pct):
    """One subfolder per penetration (no PV = pen_000); 'pv_sites' for a site list."""
    return run_folder / ("pv_sites" if penetration_pct is None else f"pen_{int(penetration_pct):03d}")


max_violations = hosting.violation_limit(VIOLATION_THRESHOLD, VIOLATION_THRESHOLD_UNIT, len(info.loads))
res.save_settings({**asdict(plan), "data_folder": DATA_FOLDER, "master_file": MASTER_FILE_NAME,
                   "voltage_bases_kv": VOLTAGE_BASES_KV, "voltage_limits_pu": VOLTAGE_LIMITS_PU,
                   "fixed_load_shapes": FIXED_LOAD_SHAPES, "rating_overrides_kva": RATING_OVERRIDES_KVA,
                   "violation_threshold": VIOLATION_THRESHOLD, "violation_threshold_unit": VIOLATION_THRESHOLD_UNIT,
                   "max_violation_score": max_violations, "transformer_overload_weight": TRANSFORMER_OVERLOAD_WEIGHT,
                   "line_overload_weight": LINE_OVERLOAD_WEIGHT, "pass_share_threshold_pct": PASS_SHARE_THRESHOLD_PCT,
                   "outputs": OUTPUTS}, run_folder / "settings.json")
fixed_table = topo.fixed_loads_table(info)
res.to_table(fixed_table).reindex(columns=["load", "shape", "found_by", "phase", "bus"]).to_csv(
    run_folder / "fixed_loads.csv", index=False)
print(f"{len(customers)} customers get random profiles{' and may get PV' if PV_BUILD == 'random' else ''}; "
      f"{len(info.fixed_loads)} loads keep a fixed shape (fixed_loads.csv)")

sampled_days = sc.plan_days(plan, pv_profiles_pu)
worst_rank, best_rank = sampled_days[0][0], sampled_days[-1][0]
day_names = {worst_rank: "worst_day"} if worst_rank == best_rank else {worst_rank: "worst_day", best_rank: "best_day"}
big_network = len(info.buses) > 300                          # no bus labels on the PNG maps

# =============================================================================================
# 3. Build the study circuit once (every PV system and inverter control in place, switched off)
# =============================================================================================
pv_candidates = list(customers) + [s["customer"] for s in PV_SITES if PV_BUILD == "sites"]
pv_candidates = list(dict.fromkeys(next((l for l in info.loads if l.lower() == c.lower()), c) for c in pv_candidates))
base = basecircuit.BaseCircuit(engine, setup, info, pv_candidates, plan.inverter_controls)


def scenarios():
    return sc.iter_plan_scenarios(plan, customers, load_profiles_kw, pv_profiles_pu, info.load_phases,
                                  tap_points=info.tap_points)


n_daily_runs = plan.n_scenarios(len(sampled_days))
per_day = sum(len(plan.penetrations_for(m)) for m in PV_MODES)
expected = hosting.estimate_runtime(engine, setup, scenarios(), n_daily_runs, n_sample=min(8, per_day),
                                    base_circuit=base, pool=per_day)
print(f"{anon(network_name, 'circuit')}: {N_RUNS_PER_PENETRATION} runs x {len(sampled_days)} PV days x {len(PV_MODES)} PV modes"
      f"{f' x {len(plan.penetrations_to_run)} penetrations' if plan.is_sweep else ''} = {n_daily_runs} daily power flows, "
      f"about {hosting.format_duration(expected)} (timed on the worst PV day, so probably less)")

# =============================================================================================
# 4. Run: every randomized run x PV day x PV mode x penetration
# =============================================================================================
time_series = res.TimeSeriesAverage()                        # worst- and best-day time series, averaged over runs


def keep_time_series(sim, row):
    if row["pv_rank"] in day_names:
        time_series.add((row["penetration_pct"], row["pv_mode"], row["pv_rank"]), sim)


table, _ = hosting.run_study(
    engine, setup, scenarios(), base_circuit=base,
    results_file=lambda row: penetration_folder(row["penetration_pct"]) / "runs.csv",
    on_simulation=keep_time_series, n_scenarios=n_daily_runs, progress_every=max(1, n_daily_runs // 10))
if not table["converged"].all():
    print(f"WARNING: {(~table['converged']).sum()} daily runs did not converge at every step (see 'converged' in runs.csv)")

# =============================================================================================
# 5. Pass share, averages over runs, hosting capacity
# =============================================================================================
mode_labels, mode_colours = sc.PV_MODES, plots.PV_MODE_COLOURS
scored = hosting.score_day_cases(table, max_violations, TRANSFORMER_OVERLOAD_WEIGHT, LINE_OVERLOAD_WEIGHT)
scored["noncompliant_customer_pct"] = 100 * scored["n_noncompliant_customers"] / len(info.loads)
pass_shares = hosting.pass_share_table(scored)
averaged = hosting.average_runs(scored, ("pv_mode", "penetration_pct", "pv_rank"))
scored.to_csv(run_folder / "day_cases.csv", index=False)
pass_shares.to_csv(run_folder / "pass_share_by_penetration.csv", index=False)
averaged.to_csv(run_folder / "runs_averaged_by_day.csv", index=False)
reports.print_summary_table(pass_shares, [
    ("PV mode", "pv_mode", "s"), ("PV %", "penetration_pct", "d"), ("Day-cases", "n_day_cases", "d"),
    ("Passed", "n_passed", "d"), ("Pass share (%)", "pass_share_pct", ".1f"),
    ("V violations", "n_voltage_violation_cases", "d"), ("Transf. overload", "n_transformer_overload_cases", "d"),
    ("Line overload", "n_line_overload_cases", "d"), ("Mean score", "mean_violation_score", ".2f"),
    ("Worst score", "max_violation_score", "d")],
    f"Day-cases passing (score <= {max_violations:g}; each overloaded transformer = {TRANSFORMER_OVERLOAD_WEIGHT}, "
    f"each overloaded line = {LINE_OVERLOAD_WEIGHT})")
if plan.is_sweep:
    pv_pass_shares = pass_shares[pass_shares["pv_mode"] != "no_pv"]
    capacity = hosting.hosting_capacity_from_pass_share(pv_pass_shares, PASS_SHARE_THRESHOLD_PCT)
    capacity.to_csv(run_folder / "hosting_capacity.csv", index=False)
    reports.print_summary_table(capacity, [
        ("PV mode", "pv_mode", "s"), ("Hosting capacity (%)", "hosting_capacity_pct", "d"),
        ("Day-cases", "n_day_cases", "d"), ("Passed", "n_passed", "d"), ("Pass share (%)", "pass_share_pct", ".1f")],
        f"Hosting capacity: at least {PASS_SHARE_THRESHOLD_PCT} % of day-cases pass at it and every lower penetration")

# Metrics shown against PV day rank / penetration: only those this network has
ALL_METRICS = {"n_noncompliant_customers": "Non-compliant customers", "v_max_pu": "Highest customer voltage (pu)",
               "pv_curtailed_pct": "PV energy curtailed (%)",
               "max_head_transformer_utilisation_pct": "Head transformer, peak loading (%)",
               "max_transformer_utilisation_pct": "Distribution transformers, highest loading (%)",
               "max_mv_line_utilisation_pct": "MV lines, highest loading (%)",
               "max_lv_line_utilisation_pct": "LV lines, highest loading (%)"}
METRICS = {c: label for c, label in ALL_METRICS.items() if c in averaged and averaged[c].notna().any()}
HLINES = {"v_max_pu": VOLTAGE_LIMITS_PU[1], **{c: 100 for c in METRICS if c.endswith("utilisation_pct")}}


def rows_at(frame, penetration_pct):
    """Rows of one penetration plus the no-PV baseline (no PV is simulated once, at 0 %)."""
    at = frame["penetration_pct"].isna() if penetration_pct is None else frame["penetration_pct"].eq(penetration_pct)
    return frame[at | frame["pv_mode"].eq("no_pv")]


def penetration_text(penetration_pct):
    return "PV sites" if penetration_pct is None else f"{penetration_pct} % PV penetration"


def runs_text():
    return f"{N_RUNS_PER_PENETRATION} runs x {len(sampled_days)} days"


# =============================================================================================
# 6. Study figures (fig01-06, in the run folder)
# =============================================================================================
if "network_map_html" in OUTPUTS:
    interactive.save_network_html(interactive.network_figure(info, coords, title=f"{network_name} network"),
                                  run_folder / "network_map.html")
if "study_figures" in OUTPUTS:
    plots.save_figure(plots.plot_network_map(engine, title=f"{network_name} network",
                                             labels=False if big_network else "short"), run_folder / "fig01_network_map.png")
    plots.save_figure(plots.plot_pv_day_ranking(pv_profiles_pu, sc.rank_pv_days(pv_profiles_pu), sampled_days),
                      run_folder / "fig02_pv_day_ranking.png")
    if plan.is_sweep:
        for number, (rank, day_name) in zip((3, 4), day_names.items()):
            plots.save_figure(plots.plot_metrics_vs_x(
                averaged[averaged["pv_rank"].eq(rank) & averaged["pv_mode"].ne("no_pv")], "penetration_pct", METRICS,
                "pv_mode", f"PV modes by penetration, {day_name.replace('_', ' ')} (rank {rank}), "
                           f"mean of {N_RUNS_PER_PENETRATION} runs", mode_labels,
                xlabel="PV penetration (% of customers)", hlines=HLINES, group_colours=mode_colours),
                run_folder / f"fig{number:02d}_modes_by_penetration_{day_name}.png")
        notes = [f"{int(r['n_passed'])} of {int(r['n_day_cases'])} day-cases passed ({r['pass_share_pct']:.1f} %)"
                 if r["hosting_capacity_pct"] == r["hosting_capacity_pct"] else "lowest penetration failed"
                 for r in capacity.to_dict("records")]
        plots.save_figure(plots.plot_bars(
            [mode_labels[m] for m in capacity["pv_mode"]], list(capacity["hosting_capacity_pct"]),
            "Hosting capacity (% of customers)", "PV hosting capacity per PV mode", missing_text="fails at lowest %",
            colours=[mode_colours[m] for m in capacity["pv_mode"]], notes=notes,
            footnote=f"Day-case passes: violation score <= {max_violations:g} (each overloaded transformer = "
                     f"{TRANSFORMER_OVERLOAD_WEIGHT}, line = {LINE_OVERLOAD_WEIGHT}); hosting capacity needs >= "
                     f"{PASS_SHARE_THRESHOLD_PCT} % of day-cases passing ({runs_text()} per penetration)."),
            run_folder / "fig05_hosting_capacity.png")
        plots.save_figure(plots.plot_metrics_vs_x(
            pv_pass_shares, "penetration_pct",
            {"pass_share_pct": "Day-cases passing (%)", "voltage_violation_case_pct": "Day-cases with voltage violations (%)",
             "transformer_overload_case_pct": "Day-cases with a transformer overload (%)",
             "line_overload_case_pct": "Day-cases with a line overload (%)"}, "pv_mode",
            f"Day-cases by penetration ({runs_text()} each)", mode_labels, xlabel="PV penetration (% of customers)",
            hlines={"pass_share_pct": PASS_SHARE_THRESHOLD_PCT}, group_colours=mode_colours),
            run_folder / "fig06_pass_share_by_penetration.png")

# =============================================================================================
# 7. Figures for each penetration (fig07-14, in pen_xxx folders)
# =============================================================================================
if "penetration_figures" in OUTPUTS:
    best_runs = hosting.best_placement_runs(scored)
    for penetration_pct in plan.penetrations_to_run:
        folder, label = penetration_folder(penetration_pct), penetration_text(penetration_pct)
        best = best_runs[best_runs["penetration_pct"].isna() if penetration_pct is None
                         else best_runs["penetration_pct"].eq(penetration_pct)]
        if len(best) and (penetration_pct is None or penetration_pct > 0):
            best = best.iloc[0]
            run = int(best["random_run"])
            window = sc.TimeWindow.days(sampled_days[0][1])
            fleet = sc.plan_pv_fleet(plan, customers, ts.profiles_in_window(pv_profiles_pu, window), penetration_pct, run)
            phases = info.load_phases
            if RANDOMIZE_PHASE_CONNECTION and info.tap_points:
                phases = sc.assign_phase_connections(info.tap_points, info.load_phases,
                                                     plan.run_seeds(run)["phase_connection"])[1]
            title = (f"PV placement, {label}: best of {N_RUNS_PER_PENETRATION} runs (run {run}, "
                     f"{mode_labels[best['pv_mode']]}, violation score {best['violation_score']:g} over {len(sampled_days)} days)")
            plots.save_figure(plots.plot_der_map(engine, sc.Scenario(window, {}, fleet), customer_phases=phases, title=title,
                                                 labels=False if big_network else "short"),
                              folder / "fig07_pv_placement_best_run.png")
            if "network_map_html" in OUTPUTS:
                interactive.save_network_html(interactive.network_figure(info, coords, title, der=fleet, customer_phases=phases),
                                              folder / "pv_placement_best_run.html")
        plots.save_figure(plots.plot_metrics_vs_x(
            rows_at(averaged, penetration_pct), "pv_rank", METRICS, "pv_mode",
            f"PV modes by PV day rank, {label} (mean of {N_RUNS_PER_PENETRATION} runs)", mode_labels,
            xlabel="PV day rank (0 = highest peak)", hlines=HLINES, group_colours=mode_colours),
            folder / "fig08_modes_by_pv_day_rank.png")
        for offset, (rank, day_name) in enumerate(day_names.items()):
            day = dict(sampled_days)[rank]
            keys = [k for k in time_series.keys() if k[2] == rank and (k[0] == penetration_pct or k[1] == "no_pv")]
            series = {k[1]: time_series.get(k) for k in sorted(keys, key=lambda k: list(PV_MODES).index(k[1]))}
            title = f"{day_name.replace('_', ' ')} (rank {rank}, day {day}), {label}, mean of {N_RUNS_PER_PENETRATION} runs"
            plots.save_figure(plots.plot_voltage_bands({mode_labels[m]: (s["V_mean"], s["V_min"], s["V_max"])
                                                        for m, s in series.items()},
                                                       VOLTAGE_LIMITS_PU, title=f"Customer voltages, {title}"),
                              folder / f"fig{9 + offset:02d}_voltages_{day_name}.png")
            with_pv = {m: s for m, s in series.items() if m != "no_pv"}
            if with_pv:
                first = next(iter(with_pv.values()))
                plots.save_figure(plots.plot_time_series(
                    [first["pv_available_P_mean"]] + [s["pv_P_mean"] for s in with_pv.values()],
                    f"Total PV active power, {title}", "kW", labels=["Available"] + [mode_labels[m] for m in with_pv],
                    styles=[":"] + ["-"] * len(with_pv), colours=[mode_colours["available"]] + [mode_colours[m] for m in with_pv]),
                    folder / f"fig{11 + offset:02d}_pv_active_power_{day_name}.png")
                plots.save_figure(plots.plot_time_series(
                    [s["pv_Q_mean"] for s in with_pv.values()], f"Total PV reactive power, {title}",
                    "kvar (negative = absorbed)", labels=[mode_labels[m] for m in with_pv],
                    colours=[mode_colours[m] for m in with_pv]),
                    folder / f"fig{13 + offset:02d}_pv_reactive_power_{day_name}.png")

# =============================================================================================
# 8. Box plots (fig15-22, in box_plots/): the spread over every day-case (runs x days)
# =============================================================================================
if "box_plots" in OUTPUTS:
    BOX_PLOTS = [  # (file name, column, axis label, reference line)
        ("fig15_noncompliant_customers", "noncompliant_customer_pct", "Non-compliant customers (% of customers)",
         VIOLATION_THRESHOLD if VIOLATION_THRESHOLD_UNIT == "pct_of_customers" else None),
        ("fig16_highest_voltage", "v_max_pu", "Highest customer voltage (pu)", VOLTAGE_LIMITS_PU[1]),
        ("fig17_head_transformer_loading", "max_head_transformer_utilisation_pct", "Head transformer, peak loading (%)", 100),
        ("fig18_distribution_transformer_loading", "max_transformer_utilisation_pct",
         "Distribution transformers, highest loading (%)", 100),
        ("fig19_mv_line_loading", "max_mv_line_utilisation_pct", "MV lines, highest loading (%)", 100),
        ("fig20_lv_line_loading", "max_lv_line_utilisation_pct", "LV lines, highest loading (%)", 100),
        ("fig21_pv_curtailed_kwh", "pv_curtailed_kwh", "PV energy curtailed (kWh per day)", None),
        ("fig22_pv_curtailed_pct", "pv_curtailed_pct", "PV energy curtailed (% of available)", None)]
    box_rows = scored.assign(penetration_pct=scored["penetration_pct"].fillna(0))
    for file_name, column, ylabel, hline in BOX_PLOTS:
        rows = box_rows if not column.startswith("pv_curtailed") else box_rows[box_rows["pv_mode"] != "no_pv"]
        if column not in rows or rows[column].isna().all():
            print(f"{file_name[:5]} skipped ({ylabel.split(',')[0]}): none with a rating in this network")
            continue
        plots.save_figure(plots.plot_box_by_group(
            rows, column, ylabel, f"{ylabel} - every day-case ({runs_text()} per box)", group_labels=mode_labels,
            group_colours=mode_colours, hline=hline), box_folder / f"{file_name}.png")

print(f"\nResults ({len(table)} daily runs) and figures saved to "
      f"{run_folder.relative_to(project_root).as_posix() if not ANONYMISE_REPORT else 'results/tut4/<network>/'}")
