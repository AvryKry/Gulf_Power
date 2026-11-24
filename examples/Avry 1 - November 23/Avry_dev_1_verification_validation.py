# Avry dev 1: verification and validation of the dss_toolkit power-flow results, and a GIS overlay
# test. Standalone: it only checks the tool; it does not run hosting capacity studies or draw the
# interactive map. Built with dss_toolkit (src/dss_toolkit, mostly the validation module).
#
# What the script does:
#   1. Verification (does the tool compute what physics says?) on a small LV network, with short,
#      truncated tests (snapshots, one day, one penetration):
#        V1 the largest voltage drop grows linearly with the load          (linear fit, R squared)
#        V2 losses grow with the square of the load                          (fit c + a k^2, R squared)
#        V3 power balance: source + PV = load + losses in every snapshot     (error in %)
#        V4 PV raises voltage linearly; reverse flow appears once PV > load + losses
#        V5 every inverter operating point is on its volt-var / volt-watt curve (IEEE 1547 Cat B), and
#           every inverter reads its voltage in the same per unit as the node voltages (PV rated
#           at its bus voltage base)
#        V6 voltage unbalance grows linearly with PV on one phase only
#        V7 Monte Carlo results converge: runs are added in batches until the 95 % confidence
#           band and the drift of the mean are within tolerance (at least MC_MIN_RUNS runs)
#        V8 runs repeated with the same seeds give identical results
#      One check plot per check, a parity plot of every check (expected vs tool), and
#      verification_checks.csv (one row per check: value, limit, PASS / FAIL).
#   2. Validation (does the tool agree with an independent reference?): the IEEE 123 node test
#      feeder against its published radial power flow results (Kersting), in two cases: regulator
#      taps held at the reference taps, and regulators left to settle on their own. Saves a
#      parity plot of every node voltage, a dot plot of the normalized error of each metric (node
#      voltages, source power per phase, losses, highest line current) with its tolerance, and
#      validation_errors.csv / node_comparison.csv. (Field validation on BC Hydro data comes later,
#      in its own script.)
#   3. GIS overlay: the IEEE European LV test feeder drawn on a street map. Its bus coordinates are
#      British National Grid metres (EPSG:27700); pyproj converts them to web-map coordinates.
#
# Internet: only step 3 uses it, and only when BASEMAP = True. The Python script itself (the
# contextily package) downloads map tile images over HTTPS from the tile server (OpenStreetMap by
# default). The only thing sent is the request for each tile: its zoom level and x / y number,
# which give the area being drawn. No network data, file or result is sent, and no HTML page is
# made (the figure is a PNG). The overlay network is public test data, never BC Hydro data.
# Without internet the network is drawn without the map and the terminal says so.
# Packages for step 3 (once):  pip install pyproj contextily
#
# Avry Krywolt, November 23, 2026

import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

SCRIPT_FOLDER = Path(__file__).resolve().parent
for folder in SCRIPT_FOLDER.parents:
    if (folder / "src" / "dss_toolkit").is_dir():
        sys.path.insert(0, str(folder / "src"))
        break

import pandas as pd

from dss_toolkit import (engine as eng, extract, hosting, network as net, paths, plots, reports, results as res,
                         scenario as sc, timeseries as ts, validation as val)

# =============================================================================================
# Settings, in selection order
# =============================================================================================
# ---- 1. Tests to run ------------------------------------------------------------------------
RUN_VERIFICATION = True
RUN_VALIDATION = True
RUN_GIS_OVERLAY = True

# ---- 2. Verification network: a folder and a master file, and its profiles -------------------
VERIFICATION_DATA_FOLDER = "tut_3_data"                      # LV test circuit (31 customers) from Tut 3
VERIFICATION_MASTER_FILE_NAME = "LVcircuit-master.txt"
VERIFICATION_VOLTAGE_BASES_KV = (22.0, 0.4)
LOAD_PROFILE_FILE_NAME = "Residential load data 30-min resolution.npy"   # V5, V7, V8 only
PV_PROFILE_FILE_NAME = "Residential PV data 30-min resolution.npy"
VOLTAGE_LIMITS_PU = (0.94, 1.10)
TRANSFORMER_RATING_KVA = 500.0

# ---- 3. Verification sweeps (snapshots; loads in the LV test circuit are 1 kW each) ----------
LOAD_MULTIPLIERS = (1, 2, 4, 6, 8)                           # V1, V2: OpenDSS LoadMult values
PV_KW_PER_CUSTOMER = (0, 0.5, 2, 4, 6, 8)                    # V4: PV at every customer, loads x 1
UNBALANCE_PV_KW_PER_CUSTOMER = (0, 2, 4, 6, 8)               # V6: PV only on the customers of one phase
UNBALANCE_PHASE = "A"

# ---- 4. Inverter curves (V5): one day, PV at every customer ---------------------------------
INVERTER_PV_KVA = 10.0                                       # every PV system's rating
VOLT_WATT_CURVE = sc.InverterControl(
    mode="volt_watt", voltage_pu=(0.50, 1.06, 1.10, 1.50), output_pu=(1.00, 1.00, 0.20, 0.20),
    source="IEEE 1547-2018 Table 10, Category B default")
VOLT_VAR_CURVE = sc.InverterControl(
    mode="volt_var", voltage_pu=(0.50, 0.92, 0.98, 1.02, 1.08, 1.50), output_pu=(0.44, 0.44, 0.00, 0.00, -0.44, -0.44),
    source="IEEE 1547-2018 Table 8, Category B default")
INVERTER_TIGHT_SETTINGS = "varchangetolerance=0.01"          # second run with the InvControl allowed to settle
                                                             # closer than the study default (0.1); "" = skip

# ---- 5. Monte Carlo (V7, V8): one day (the highest PV peak), one penetration -----------------
MC_PENETRATION_PCT = 60
MC_PV_RATINGS_KVA = (5.0, 6.6, 10.0)
MC_MIN_RUNS = 200                                            # runs before convergence is judged
MC_MAX_RUNS = 1000                                           # stop here even if not converged
MC_BATCH_RUNS = 100                                          # runs added between convergence checks
MC_TOLERANCES = {"v_max_pu": 0.001, "pass_pct": 3.0}        # 95 % half-width and drift allowed (pu, % points)
MC_VIOLATION_THRESHOLD_PCT = 10                              # a day-case passes with violations <= 10 % of customers
MC_SEED = 1                                                  # PV placement / rating / load profile / power factor
REPEAT_RUNS = 10                                             # V8: runs repeated with the same seeds

# ---- 6. Verification tolerances --------------------------------------------------------------
POWER_BALANCE_LIMIT_PCT = 0.01
FIT_MIN_R_SQUARED = 0.99
INVERTER_TOLERANCE_PU = 0.02                                 # 2 % of the inverter rating

# ---- 7. Validation network and its reference results ----------------------------------------
VALIDATION_DATA_FOLDER = "ieee123_data"
VALIDATION_MASTER_FILE_NAME = "IEEE123Master.dss"
VALIDATION_VOLTAGE_BASES_KV = None                           # None = set by the master file (4.16, 0.48 kV)
REFERENCE_REPORT_FILE_NAME = "reference/ieee123_radial_power_flow.txt"
REFERENCE_TOTALS_FILE_NAME = "reference/ieee123_system_totals.csv"
REFERENCE_TAPS_FILE_NAME = "reference/ieee123_regulator_taps.csv"
REFERENCE_NODE_NAMES = {"RG1": "150r", "RG2": "9r", "RG3": "25r", "RG4": "160r"}   # report name -> OpenDSS bus
VALIDATION_CASES = ("taps_fixed_to_reference", "regulators_settling")
REGULATOR_MAX_TAP_CHANGE = 1                                 # settling case: one tap step per control round
VALIDATION_TOLERANCES_PCT = {"voltage": 1.0, "power": 1.0, "current": 1.0, "losses": 5.0}

# ---- 8. GIS overlay network ------------------------------------------------------------------
GIS_DATA_FOLDER = "european_lv_data"
GIS_MASTER_FILE_NAME = "Master.dss"
GIS_VOLTAGE_BASES_KV = None                                  # None = set by the master file
GIS_COORDINATE_SYSTEM = "EPSG:27700"                         # British National Grid (metres)
BASEMAP = True                                               # False: no internet use at all

# ---- 9. Outputs (everything is saved to files) -----------------------------------------------
RESULTS_FOLDER = "results/avry_dev_1"                        # from the repo root; then <network>/<test>/
ANONYMISE_REPORT = False                                     # True: codes instead of names in the terminal text

# =============================================================================================
# Set-up
# =============================================================================================
anon = reports.Anonymiser(ANONYMISE_REPORT)
project_root = paths.find_project_root(SCRIPT_FOLDER)
engine = eng.start_engine()
plots.apply_style()
started = time.perf_counter()


def stop(step, error, data_folder=None):
    """Explain which step failed with OpenDSS's own message (names and paths anonymised if asked)."""
    hidden = [data_folder] if data_folder else []
    print(f"\nFAILED at: {step}\n  {type(error).__name__}: {anon.text(error, hidden)}")
    sys.exit(1)


def locate(data_folder, master_file_name, what):
    if not data_folder or not master_file_name:
        stop(f"finding the {what} network", ValueError("fill in its DATA_FOLDER and MASTER_FILE_NAME settings"))
    try:
        return paths.locate_file(master_file_name, data_folder, start=SCRIPT_FOLDER, verbose=False)
    except Exception as error:
        stop(f"finding the {what} master file", error)


def fresh_folder(*parts):
    folder = project_root / RESULTS_FOLDER / Path(*parts)
    shutil.rmtree(folder, ignore_errors=True)                # fresh results for every run
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def shown(folder):
    return folder.relative_to(project_root).as_posix() if not ANONYMISE_REPORT else f"{RESULTS_FOLDER}/<network>/..."


settings = {k: v for k, v in globals().items() if k.isupper() and k not in ("SCRIPT_FOLDER",)}

# =============================================================================================
# 1. Verification
# =============================================================================================
if RUN_VERIFICATION:
    master = locate(VERIFICATION_DATA_FOLDER, VERIFICATION_MASTER_FILE_NAME, "verification")
    data_folder = master.parent
    setup = hosting.StudySetup(circuit_source=str(master), voltage_bases_kv=VERIFICATION_VOLTAGE_BASES_KV,
                               limits=VOLTAGE_LIMITS_PU, transformer_rating_kva=TRANSFORMER_RATING_KVA)
    try:
        network_name = hosting.build_study_circuit(engine, setup).lower()
        customers = hosting.list_customers(engine, setup)
        setup.customer_phases = net.customer_phases(engine)
        load_profiles_kw = ts.read_profile_file(data_folder / LOAD_PROFILE_FILE_NAME)
        pv_profiles_pu = ts.read_profile_file(data_folder / PV_PROFILE_FILE_NAME)
    except Exception as error:
        stop("compiling the verification network and reading its profiles", error, data_folder)
    folder = fresh_folder(network_name, "verification")
    res.save_settings(settings, folder / "settings.json")
    checks, points = [], []
    print(f"Verification on {anon.text(network_name)} ({len(customers)} customers)")

    # ---- V1, V2: load sweep ------------------------------------------------------------------
    sweep = val.load_sweep(engine, setup, LOAD_MULTIPLIERS)
    k = [r["x"] for r in sweep]
    drop = [r["largest_drop_pu"] for r in sweep]
    slope, intercept, r2, drop_fit = val.linear_fit(k, drop)
    checks.append(val.check_row("V1", "Voltage drop linear in load", r2, FIT_MIN_R_SQUARED, "R squared",
                                r2 >= FIT_MIN_R_SQUARED, f"drop = {slope:.5f} pu per load multiple {intercept:+.5f}"))
    plots.save_figure(val.plot_fit_check(k, drop, drop_fit, "Load multiplier (x the loads in the files)",
                                         "Largest voltage drop from no load (pu)",
                                         "V1: voltage drop grows linearly with load", f"linear fit R² = {r2:.5f}"),
                      folder / "fig01_v1_voltage_drop_vs_load.png")
    losses = [r["P_loss_kw"] for r in sweep]
    a, c, r2, loss_fit = val.square_fit(k, losses)
    checks.append(val.check_row("V2", "Losses grow with the square of the load", r2, FIT_MIN_R_SQUARED, "R squared",
                                r2 >= FIT_MIN_R_SQUARED, f"losses = {c:.3f} kW (no-load) + {a:.4f} kW x k^2"))
    plots.save_figure(val.plot_fit_check(k, losses, loss_fit, "Load multiplier k", "Active power losses (kW)",
                                         "V2: losses grow with the square of the load",
                                         f"fit {c:.2f} + {a:.3f} k²  (R² = {r2:.5f})"),
                      folder / "fig02_v2_losses_vs_load.png")
    points += sweep
    parity = {"V1 voltage drop": (drop_fit, drop), "V2 losses": (loss_fit, losses)}

    # ---- V4: PV sweep ------------------------------------------------------------------------
    pv_rows = val.pv_sweep(engine, setup, PV_KW_PER_CUSTOMER)
    pv_total = [r["x"] for r in pv_rows]
    rise = [r["voltage_rise_pu"] for r in pv_rows]
    slope, intercept, r2, rise_fit = val.linear_fit(pv_total, rise)
    flow_ok = all(r["reverse_flow"] == r["pv_above_load_and_losses"] for r in pv_rows)
    checks.append(val.check_row("V4", "Voltage rise linear in PV", r2, FIT_MIN_R_SQUARED, "R squared",
                                r2 >= FIT_MIN_R_SQUARED, f"{1000 * slope:.3f} pu per MW at the highest-voltage node"))
    checks.append(val.check_row("V4", "Reverse flow exactly when PV > load + losses",
                                sum(r["reverse_flow"] == r["pv_above_load_and_losses"] for r in pv_rows), len(pv_rows),
                                "cases agreeing", flow_ok,
                                f"{sum(r['reverse_flow'] for r in pv_rows)} of {len(pv_rows)} cases with reverse flow"))
    crossing = next((r["P_load_kw"] + r["P_loss_kw"] for r in pv_rows if r["reverse_flow"]), None)

    def mark_reverse_flow(ax):
        if crossing:
            ax.axvspan(crossing, max(pv_total) * 1.05, color="#eb6834", alpha=0.08, lw=0,
                       label="PV > load + losses: reverse flow")
    plots.save_figure(val.plot_fit_check(pv_total, rise, rise_fit, "Total PV output (kW)",
                                         "Voltage rise at the highest-voltage node (pu)",
                                         "V4: PV raises voltage linearly; power flows back past load + losses",
                                         f"linear fit R² = {r2:.5f}; reverse flow in "
                                         f"{sum(r['reverse_flow'] for r in pv_rows)} of {len(pv_rows)} cases, "
                                         f"{'all' if flow_ok else 'NOT all'} where PV > load + losses",
                                         extra=mark_reverse_flow),
                      folder / "fig03_v4_pv_voltage_rise.png")
    points += pv_rows
    parity["V4 voltage rise"] = (rise_fit, rise)

    # ---- V6: unbalance sweep -----------------------------------------------------------------
    unbalance_rows = val.unbalance_sweep(engine, setup, UNBALANCE_PV_KW_PER_CUSTOMER, UNBALANCE_PHASE)
    pv_phase = [r["x"] for r in unbalance_rows]
    vuf = [r["vuf_pct"] for r in unbalance_rows]
    slope, intercept, r2, vuf_fit = val.linear_fit(pv_phase, vuf)
    bus = anon.text(unbalance_rows[0]["bus"])
    checks.append(val.check_row("V6", "Voltage unbalance linear in one-phase PV", r2, FIT_MIN_R_SQUARED, "R squared",
                                r2 >= FIT_MIN_R_SQUARED, f"{slope:.4f} % per kW at {bus}, {intercept:+.4f} % with no PV"))
    plots.save_figure(val.plot_fit_check(pv_phase, vuf, vuf_fit, f"PV on phase {UNBALANCE_PHASE} only (kW, no load)",
                                         f"Voltage unbalance |V2| / |V1| at {bus} (%)",
                                         "V6: voltage unbalance grows linearly with one-phase PV",
                                         f"linear fit R² = {r2:.5f}"),
                      folder / "fig04_v6_voltage_unbalance.png")
    points += unbalance_rows
    parity["V6 voltage unbalance"] = (vuf_fit, vuf)

    # ---- V3: power balance of every snapshot -------------------------------------------------
    worst = max(r["balance_pct"] for r in points)
    checks.append(val.check_row("V3", "Power balance in every snapshot", worst, POWER_BALANCE_LIMIT_PCT, "% (largest)",
                                worst <= POWER_BALANCE_LIMIT_PCT, f"{len(points)} snapshots"))
    plots.save_figure(val.plot_balance_check(points, POWER_BALANCE_LIMIT_PCT,
                                             "V3: power balance, source + PV - load - losses, every snapshot"),
                      folder / "fig05_v3_power_balance.png")
    parity["V3 source power"] = ([r["P_load_kw"] + r["P_loss_kw"] - r["P_pv_kw"] for r in points],
                                 [r["P_source_kw"] for r in points])
    pd.DataFrame(points).to_csv(folder / "verification_snapshots.csv", index=False)

    # ---- V5: inverter curves on the highest-PV day -------------------------------------------
    plan = sc.StudyPlan(circuit_name=network_name, pv_build="random", pv_modes=("pv_volt_var", "pv_volt_watt"),
                        pv_ratings_kva=(INVERTER_PV_KVA,), penetrations_pct=(100,), days_per_run="worst_only",
                        inverter_controls={"volt_var": VOLT_VAR_CURVE, "volt_watt": VOLT_WATT_CURVE},
                        pv_placement_seed=MC_SEED, pv_rating_seed=MC_SEED, load_profile_seed=MC_SEED,
                        power_factor_seed=MC_SEED)
    point_sets, bases = {}, []
    runs = [("study settings", "")] + ([(INVERTER_TIGHT_SETTINGS, INVERTER_TIGHT_SETTINGS)] if INVERTER_TIGHT_SETTINGS else [])
    for label, extra in runs:
        controls = {"volt_var": replace(VOLT_VAR_CURVE, extra=extra), "volt_watt": replace(VOLT_WATT_CURVE, extra=extra)}
        for scenario in sc.iter_plan_scenarios(replace(plan, inverter_controls=controls), customers, load_profiles_kw,
                                               pv_profiles_pu, setup.customer_phases):
            sim = hosting.simulate(engine, setup, scenario)
            bases += val.inverter_voltage_bases(engine)
            point_sets[(scenario.inverter_control.mode, label)] = pd.DataFrame(
                val.inverter_curve_points(sim, scenario.inverter_control))
    ratios = pd.Series([b["ratio"] for b in bases], dtype=float)
    off = (ratios - 1).abs().max()
    checks.append(val.check_row("V5", "Inverters read voltage in the same pu as the nodes", off, 1e-6,
                                "largest |base / rated kV - 1|", off <= 1e-6,
                                f"{len(ratios)} PV systems: rated kV = bus voltage base"))
    pd.concat(point_sets.values(), ignore_index=True).to_csv(folder / "inverter_points.csv", index=False)
    for number, (mode, curve, ylabel) in enumerate((("volt_var", VOLT_VAR_CURVE, "Reactive power (pu of kVA, + = injected)"),
                                                    ("volt_watt", VOLT_WATT_CURVE, "Active power (pu of Pmpp)")), start=6):
        mine = {label: points for (m, label), points in point_sets.items() if m == mode}
        for label, points in mine.items():
            worst = points["error_pu"].abs().max()
            within = (points["error_pu"].abs() <= INVERTER_TOLERANCE_PU).mean() * 100
            checks.append(val.check_row("V5", f"{mode.replace('_', '-')} points on the curve ({label})", worst,
                                        INVERTER_TOLERANCE_PU, "pu (largest)", worst <= INVERTER_TOLERANCE_PU,
                                        f"{len(points)} points (PV x half-hours), {within:.1f} % within tolerance, "
                                        f"voltages {points['v_pu'].min():.3f}-{points['v_pu'].max():.3f} pu"))
        title = f"V5: {mode.replace('_', '-')} operating points, {len(customers)} PV of {INVERTER_PV_KVA:g} kVA, highest-PV day"
        if mode == "volt_watt":
            title += "\n(below the curve = less sun available than the limit)"
        plots.save_figure(val.plot_inverter_check(mine, curve, INVERTER_TOLERANCE_PU, title, ylabel),
                          folder / f"fig{number:02d}_v5_{mode}_curve.png")
        first = next(iter(mine.values()))
        parity[f"V5 {mode.replace('_', '-')}"] = (first["expected_pu"], first["output_pu"])

    # ---- V7: Monte Carlo convergence ---------------------------------------------------------
    max_violations = hosting.violation_limit(MC_VIOLATION_THRESHOLD_PCT, "pct_of_customers", len(customers))

    def mc_plan(n_runs):
        return sc.StudyPlan(circuit_name=network_name, pv_build="random", pv_modes=("pv",), pv_ratings_kva=MC_PV_RATINGS_KVA,
                            penetrations_pct=(MC_PENETRATION_PCT,), n_runs_per_penetration=n_runs,
                            days_per_run="worst_only", pv_placement_seed=MC_SEED, pv_rating_seed=MC_SEED,
                            load_profile_seed=MC_SEED, power_factor_seed=MC_SEED, intra_penetration_seed=MC_SEED)

    def add_pass(table):
        scored = hosting.score_day_cases(table, max_violations)
        scored["pass_pct"] = 100.0 * scored["passes"]
        return scored

    print(f"V7 Monte Carlo: {MC_PENETRATION_PCT} % PV, highest-PV day, {MC_MIN_RUNS}-{MC_MAX_RUNS} runs")
    mc, converged, state = val.monte_carlo_convergence(
        engine, setup, sc.iter_plan_scenarios(mc_plan(MC_MAX_RUNS), customers, load_profiles_kw, pv_profiles_pu,
                                              setup.customer_phases),
        MC_TOLERANCES, MC_MIN_RUNS, MC_MAX_RUNS, MC_BATCH_RUNS, prepare=add_pass)
    mc.to_csv(folder / "monte_carlo_runs.csv", index=False)
    for column, (mean, half, drift, tolerance, ok) in state.items():
        checks.append(val.check_row("V7", f"Monte Carlo mean of {column} converged", half, tolerance,
                                    "95 % half-width", ok, f"mean {mean:.4g} after {len(mc)} runs, drift {drift:.2g}"))
    plots.save_figure(val.plot_convergence(mc, "v_max_pu", "Highest customer voltage, mean (pu)",
                                           MC_TOLERANCES["v_max_pu"],
                                           f"V7: Monte Carlo convergence, highest voltage ({MC_PENETRATION_PCT} % PV)",
                                           MC_MIN_RUNS), folder / "fig08_v7_convergence_highest_voltage.png")
    plots.save_figure(val.plot_convergence(mc, "pass_pct", "Day-cases passing (%)", MC_TOLERANCES["pass_pct"],
                                           f"V7: Monte Carlo convergence, pass share ({MC_PENETRATION_PCT} % PV)",
                                           MC_MIN_RUNS), folder / "fig09_v7_convergence_pass_share.png")

    # ---- V8: repeat the first runs with the same seeds ----------------------------------------
    repeat, _ = hosting.run_study(engine, setup, sc.iter_plan_scenarios(mc_plan(REPEAT_RUNS), customers, load_profiles_kw,
                                                                        pv_profiles_pu, setup.customer_phases))
    compared = ["v_max_pu", "v_min_pu", "n_noncompliant_customers", "transformer_peak_kva", "pv_delivered_kwh"]
    differences = val.compare_tables(mc.head(REPEAT_RUNS), repeat, compared)
    worst = max(differences.values())
    checks.append(val.check_row("V8", "Same seeds give identical results", worst, 0.0, "largest difference",
                                worst == 0.0, f"{REPEAT_RUNS} runs repeated; compared {', '.join(compared)}"))
    plots.save_figure(val.plot_repeat_check(mc.head(REPEAT_RUNS), repeat, "v_max_pu", "Highest customer voltage (pu)",
                                            f"V8: {REPEAT_RUNS} runs repeated with the same seeds "
                                            f"(largest difference {worst:g})"),
                      folder / "fig10_v8_repeated_runs.png")

    # ---- Parity plot of every check and the checks table ----------------------------------------
    scaled = {}
    for label, (expected, tool) in parity.items():
        scale = max(abs(pd.Series(list(expected), dtype=float)).max(), 1e-12)
        scaled[label] = (pd.Series(list(expected), dtype=float) / scale, pd.Series(list(tool), dtype=float) / scale)
    plots.save_figure(val.plot_parity(scaled, "Expected from first principles (scaled to the largest of each check)",
                                      "Tool (OpenDSS through dss_toolkit), same scale",
                                      "Verification parity: every check point", band=INVERTER_TOLERANCE_PU,
                                      colours={k: val.CHECK_COLOURS.get(k[:12], val.CHECK_COLOURS.get(k[:2])) for k in scaled}),
                      folder / "fig11_verification_parity.png")
    checks_table = pd.DataFrame(checks)
    checks_table.to_csv(folder / "verification_checks.csv", index=False)
    reports.print_summary_table(checks_table, [("Check", "check", "s"), ("What", "name", "s"), ("Value", "value", ".4g"),
                                               ("Limit", "limit", ".4g"), ("Unit", "unit", "s"), ("Result", "result", "s")],
                                "Verification")
    print(f"Verification saved to {shown(folder)}")

# =============================================================================================
# 2. Validation: IEEE 123 node test feeder against the published results
# =============================================================================================
if RUN_VALIDATION:
    master = locate(VALIDATION_DATA_FOLDER, VALIDATION_MASTER_FILE_NAME, "validation")
    data_folder = master.parent
    try:
        reference_nodes, reference_branches = val.read_radial_flow_report(data_folder / REFERENCE_REPORT_FILE_NAME)
        totals = pd.read_csv(data_folder / REFERENCE_TOTALS_FILE_NAME)
        taps = pd.read_csv(data_folder / REFERENCE_TAPS_FILE_NAME).drop_duplicates("transformer")
    except Exception as error:
        stop("reading the reference results", error, data_folder)
    error_rows, node_tables, parity = [], [], {}
    for case in VALIDATION_CASES:
        try:
            network_name = eng.build_circuit(engine, str(master), VALIDATION_VOLTAGE_BASES_KV).lower()
        except Exception as error:
            stop("compiling the validation network", error, data_folder)
        if case == "taps_fixed_to_reference":
            val.set_transformer_taps(engine, dict(zip(taps["transformer"], taps["tap"])))
            eng.set_snapshot_mode(engine, control_mode="fixed")
        elif case == "regulators_settling":
            eng.run_commands(engine, [f"RegControl.{r}.maxtapchange={REGULATOR_MAX_TAP_CHANGE}"
                                      for r in net.element_names(engine.ActiveCircuit.RegControls)])
            eng.set_snapshot_mode(engine, control_mode="active")
        else:
            stop("choosing a validation case", ValueError(f"unknown case {case!r}"))
        converged = eng.solve(engine, verbose=False)
        comparison = val.node_comparison(extract.node_voltages(engine), reference_nodes, REFERENCE_NODE_NAMES)
        comparison.insert(0, "case", case)
        node_tables.append(comparison)
        error_rows += val.compare_metrics(case, val.tool_metrics(engine, comparison),
                                          val.reference_metrics(comparison, totals, reference_branches),
                                          VALIDATION_TOLERANCES_PCT)
        parity[case.replace("_", " ")] = (comparison["reference_pu"], comparison["tool_pu"])
        print(f"Validation case {case}: power flow {'converged' if converged else 'DID NOT CONVERGE'}, "
              f"{len(comparison)} node voltages compared, regulator taps {extract.regulator_taps(engine)}")
    folder = fresh_folder(network_name, "validation")
    res.save_settings(settings, folder / "settings.json")
    nodes = pd.concat(node_tables, ignore_index=True)
    nodes.to_csv(folder / "node_comparison.csv", index=False)
    errors = pd.DataFrame(error_rows)
    errors.to_csv(folder / "validation_errors.csv", index=False)
    plots.save_figure(val.plot_parity(parity, "Reference node voltage, IEEE radial power flow (pu)",
                                      "Tool node voltage (pu)",
                                      f"Validation parity: IEEE 123 node voltages ({len(nodes) // len(parity)} node-phases)",
                                      band=VALIDATION_TOLERANCES_PCT["voltage"] / 100,
                                      markers={k: val.CASE_MARKERS[i] for i, k in enumerate(parity)}),
                      folder / "fig12_validation_parity_node_voltages.png")
    plots.save_figure(val.plot_error_dots(error_rows, "Validation: IEEE 123 node test feeder, tool vs published results"),
                      folder / "fig13_validation_normalized_errors.png")
    summary = errors.groupby("case").agg(metrics=("metric", "size"), passed=("result", lambda r: int((r == "PASS").sum())),
                                         worst_error_pct=("error_pct", lambda e: e.abs().max())).reset_index()
    summary["node_mean_abs_error_pu"] = [nodes.loc[nodes["case"] == c, "error_pu"].abs().mean() for c in summary["case"]]
    reports.print_summary_table(summary, [("Case", "case", "s"), ("Metrics", "metrics", "d"), ("Passed", "passed", "d"),
                                          ("Worst |error| (%)", "worst_error_pct", ".2f"),
                                          ("Mean |V error| (pu)", "node_mean_abs_error_pu", ".4f")],
                                "Validation (tolerances: voltage, power, current 1 %; losses 5 %)")
    for r in errors[errors["result"] == "FAIL"].to_dict("records"):
        print(f"  outside tolerance: {r['case']}, {r['metric']}: {r['error_pct']:+.2f} % (tolerance {r['tolerance_pct']:g} %)")
    print(f"Validation saved to {shown(folder)}")

# =============================================================================================
# 3. GIS overlay: a public test feeder on a street map
# =============================================================================================
if RUN_GIS_OVERLAY:
    master = locate(GIS_DATA_FOLDER, GIS_MASTER_FILE_NAME, "GIS overlay")
    try:
        network_name = eng.build_circuit(engine, str(master), GIS_VOLTAGE_BASES_KV).lower()
    except Exception as error:
        stop("compiling the GIS overlay network", error, master.parent)
    folder = fresh_folder(network_name, "gis_overlay")
    print(f"GIS overlay: {'downloading map tiles (internet)' if BASEMAP else 'no basemap (no internet use)'}")
    figure, note = val.plot_gis_overlay(engine, GIS_COORDINATE_SYSTEM,
                                        f"{network_name}: bus coordinates ({GIS_COORDINATE_SYSTEM}) on a street map",
                                        basemap=BASEMAP)
    plots.save_figure(figure, folder / "fig14_gis_overlay.png")
    extent = val.lon_lat_extent(engine, GIS_COORDINATE_SYSTEM) if figure else None
    with open(folder / "gis_overlay.json", "w") as f:
        json.dump({"note": note, "coordinate_system": GIS_COORDINATE_SYSTEM, "basemap": BASEMAP,
                   "extent_lon_lat": extent}, f, indent=2)
    if extent:
        print(f"  network area: {extent[1]:.4f} to {extent[3]:.4f} N, {extent[0]:.4f} to {extent[2]:.4f} E")
    print(f"  {note}\nGIS overlay saved to {shown(folder)}")

print(f"\nDone in {hosting.format_duration(time.perf_counter() - started)}")
