"""Running scenarios and hosting capacity studies.

Randomized studies: each penetration is repeated over many randomized runs. Every day of every run
is a day-case; score_day_cases() counts its violations (non-compliant customers, plus a weight for a
transformer overload), pass_share_table() gives the share of day-cases that pass, and
hosting_capacity_from_pass_share() declares the hosting capacity from a pass-share threshold.

StudySetup = the network and how it is judged (circuit, voltage bases, limits, transformer).
Scenario   = what is simulated (demand, DER, inverter control, time window), see scenario.py.
simulate() runs one scenario; run_study() runs many and returns one table row per run.

Result columns (one row per simulation, from summarise()):
    n_noncompliant_customers   customers outside the voltage limits at any step
    n_overvoltage_customers / n_undervoltage_customers
    v_min_pu / v_max_pu        lowest / highest customer voltage
    transformer_peak_kva       highest |S| through the monitored transformer
    transformer_utilisation_pct / transformer_phase_utilisation_pct   peak |S| as % of the rating
    transformer_overloaded     peak |S| above the transformer rating
    transformer_min_p_kw       lowest active power (negative = reverse flow)
    v_max_phase_a_pu ... _c_pu, v_max_phase_spread_pu   per phase (when StudySetup.customer_phases is set)
    pv_available_kwh / pv_delivered_kwh / pv_curtailed_kwh / pv_curtailed_pct
    pv_reactive_kvarh          reactive energy out of the PV (negative = absorbed, e.g. volt-var)

reuse_circuit (off by default): build the circuit once and only swap profiles / switch DER between
runs instead of recompiling for every run. Faster on large feeders; verify_reuse() checks that it
gives the same results as a rebuild before relying on it. Runs with an inverter control are always
rebuilt (see prepare_circuit).
"""
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pandas.api import types as pd_types

from . import engine as eng, network as net, results as res, timeseries as ts


@dataclass
class StudySetup:
    circuit_source: object           # master file path, or a list of OpenDSS commands
    voltage_bases_kv: tuple          # line-to-line voltage bases, e.g. (22.0, 0.4)
    limits: tuple                    # (lowest, highest) allowed customer voltage [pu]
    transformer: str = None          # transformer to monitor (None = the first one)
    transformer_rating_kva: float = None   # rating used for the utilisation (None = nameplate)
    bus_coordinates: object = None   # coordinates file path or {bus: (x, y)} for maps (None = none)
    customer_phases: dict = None     # {load: "A"/"B"/"C"} (network.customer_phases) for per-phase results


# --- The circuit ---------------------------------------------------------------------------------
_BASE = {}   # reuse_circuit state per engine: circuit, marker, DER / control elements, initial taps


def build_study_circuit(engine, setup):
    """Build the circuit of a setup (with its bus coordinates). Returns the circuit name."""
    return eng.build_circuit(engine, setup.circuit_source, setup.voltage_bases_kv,
                             bus_coordinates=setup.bus_coordinates)


def list_customers(engine, setup):
    """Build the circuit and return its load (customer) names."""
    build_study_circuit(engine, setup)
    return net.element_names(engine.ActiveCircuit.Loads)


def transformer_taps(engine):
    """{transformer: [tap of each winding]}, e.g. to restore regulator taps between runs."""
    tr = engine.ActiveCircuit.Transformers
    taps = {}
    for name in net.element_names(tr):
        tr.Name = name
        taps[name] = []
        for w in range(1, tr.NumWindings + 1):
            tr.Wdg = w
            taps[name].append(tr.Tap)
    return taps


def restore_transformer_taps(engine, taps):
    tr = engine.ActiveCircuit.Transformers
    for name, values in taps.items():
        tr.Name = name
        for w, tap in enumerate(values, start=1):
            tr.Wdg = w
            tr.Tap = tap


def prepare_circuit(engine, setup, scenario, reuse_circuit=False):
    """Put the scenario into the circuit. Rebuild (default): build, then add everything.
    Reuse: keep the circuit built for this setup, switch off DER and controls not in the scenario,
    restore the initial taps and reset controls, then swap in the scenario's profiles, DER and
    control. Returns the scenario's DER element names.
    A scenario with an inverter control is always rebuilt: OpenDSS (DSS C-API 0.14) crashes when an
    InvControl is added to a circuit that has already been solved."""
    if reuse_circuit and scenario.inverter_control is not None:
        _BASE.pop(id(engine), None)          # the rebuilt circuit is not a clean base for reuse
        reuse_circuit = False
    state = _BASE.get(id(engine))
    circuit_ok = (reuse_circuit and state is not None and state["circuit"] == repr(setup.circuit_source)
                  and state["marker"] in net.element_names(engine.ActiveCircuit.LoadShapes))
    if not circuit_ok:
        build_study_circuit(engine, setup)
        if reuse_circuit:
            marker = f"toolkit_base_{len(_BASE) + 1}"
            eng.run_commands(engine, [f"new LoadShape.{marker} npts=1 mult=(1)"])
            state = _BASE[id(engine)] = {"circuit": repr(setup.circuit_source), "marker": marker, "elements": set(),
                                         "taps": transformer_taps(engine)}
    if reuse_circuit:
        loads = net.element_names(engine.ActiveCircuit.Loads)
        if sorted(scenario.customers) != sorted(loads):
            raise ValueError("reuse_circuit needs a demand profile for every load of the circuit")
        ts.set_elements_enabled(engine, sorted(state["elements"]), False)
        restore_transformer_taps(engine, state["taps"])
        eng.run_commands(engine, ["Reset"])
    der_elements, control_elements = ts.apply_scenario(engine, scenario)
    if reuse_circuit:
        ts.set_elements_enabled(engine, der_elements + control_elements, True)
        state["elements"].update(der_elements + control_elements)
    return der_elements


# --- One scenario ----------------------------------------------------------------------------------
def simulate(engine, setup, scenario, reuse_circuit=False):
    """Run a scenario over its whole time window. Returns P, Q, V (customers x steps),
    tx_P, tx_Q (steps x phases), der_P, der_Q (steps x DER), der_available_P (steps x DER, what
    the DER could have delivered) and the scenario itself."""
    elements = prepare_circuit(engine, setup, scenario, reuse_circuit)
    loads = net.element_names(engine.ActiveCircuit.Loads)
    transformer = setup.transformer or net.element_names(engine.ActiveCircuit.Transformers)[0]
    w = scenario.window
    records, converged = ts.run_daily(engine, w.n_steps, w.step_minutes,
                                      {"loads": ts.record_loads(loads), "transformer": ts.record_transformer(transformer),
                                       "der": ts.record_der(elements)})
    engine.ActiveCircuit.Transformers.Name = transformer
    der = records["der"] if elements else np.zeros((w.n_steps, 2, 0))
    available = np.array([d.available_power_kw for d in scenario.der]).T if scenario.der else np.zeros((w.n_steps, 0))
    return {"scenario": scenario, "loads": loads, "der": elements, "converged": converged,
            "transformer": transformer,
            "transformer_kva": setup.transformer_rating_kva or engine.ActiveCircuit.Transformers.kVA,
            "P": records["loads"][:, 0, :].T, "Q": records["loads"][:, 1, :].T, "V": records["loads"][:, 2, :].T,
            "tx_P": records["transformer"][:, 0, :], "tx_Q": records["transformer"][:, 1, :],
            "der_P": der[:, 0, :], "der_Q": der[:, 1, :], "der_available_P": available}


# --- Metrics (no OpenDSS needed) ---------------------------------------------------------------------
def noncompliant_customers(voltages, names, limits):
    """Customers whose voltage is outside 'limits' at any time step: {'under': [...], 'over': [...]}"""
    return {"under": [n for n, v in zip(names, voltages) if v.min() < limits[0]],
            "over": [n for n, v in zip(names, voltages) if v.max() > limits[1]]}


def transformer_apparent_power(p, q):
    """|S| [kVA] per step: (total of the three phases, per phase). p, q have shape (n_steps, n_phases)."""
    return np.hypot(p.sum(axis=1), q.sum(axis=1)), np.hypot(p, q)


def pv_energy(sim):
    """(available, delivered, curtailed [kWh], curtailed [% of available], reactive [kvarh]) of
    the simulation's DER. Curtailed = what an inverter control (or the kVA limit) held back."""
    hours = sim["scenario"].window.hours_per_step
    available = float(sim["der_available_P"].sum() * hours)
    delivered = float(sim["der_P"].sum() * hours)
    curtailed = max(available - delivered, 0.0)
    return available, delivered, curtailed, 100 * curtailed / available if available else 0.0, float(sim["der_Q"].sum() * hours)


def phase_voltage_maxima(sim, customer_phases):
    """{"v_max_phase_a_pu": ..., "v_max_phase_b_pu": ..., "v_max_phase_c_pu": ...,
    "v_max_phase_spread_pu": highest minus lowest of the three} over the simulation's customers."""
    maxima = {}
    for ph in "ABC":
        rows = [i for i, c in enumerate(sim["loads"]) if customer_phases.get(c) == ph]
        maxima[f"v_max_phase_{ph.lower()}_pu"] = float(sim["V"][rows].max()) if rows else np.nan
    values = [v for v in maxima.values() if not np.isnan(v)]
    maxima["v_max_phase_spread_pu"] = max(values) - min(values) if values else np.nan
    return maxima


def summarise(sim, limits, customer_phases=None):
    """One results row: the scenario's tags + the key numbers of the simulation (see the module
    docstring for the columns). With 'customer_phases' the row also gives the highest voltage on
    each phase and their spread."""
    bad = noncompliant_customers(sim["V"], sim["loads"], limits)
    s_total, s_phase = transformer_apparent_power(sim["tx_P"], sim["tx_Q"])
    available, delivered, curtailed, curtailed_pct, reactive = pv_energy(sim)
    tags = {k: v for k, v in sim["scenario"].tags.items() if not isinstance(v, (dict, list))}
    phases = phase_voltage_maxima(sim, customer_phases) if customer_phases else {}
    utilisation = 100 * s_total.max() / sim["transformer_kva"]
    return {**tags, "n_noncompliant_customers": len(set(bad["under"]) | set(bad["over"])),
            "n_overvoltage_customers": len(bad["over"]), "n_undervoltage_customers": len(bad["under"]),
            "v_min_pu": sim["V"].min(), "v_max_pu": sim["V"].max(), **phases,
            "transformer_peak_kva": s_total.max(), "transformer_utilisation_pct": utilisation,
            "transformer_overloaded": bool(utilisation > 100),
            "transformer_phase_utilisation_pct": 100 * s_phase.max() / (sim["transformer_kva"] / s_phase.shape[1]),
            "transformer_min_p_kw": sim["tx_P"].sum(axis=1).min(),
            "pv_available_kwh": available, "pv_delivered_kwh": delivered, "pv_curtailed_kwh": curtailed,
            "pv_curtailed_pct": curtailed_pct, "pv_reactive_kvarh": reactive, "converged": sim["converged"]}


# --- Many scenarios ----------------------------------------------------------------------------------
def run_study(engine, setup, scenarios, results_file=None, simulations_folder=None, keep_simulations=False,
              reuse_circuit=False, verbose=False, on_simulation=None, n_scenarios=None, progress_every=None):
    """Simulate every scenario (a list or any iterable, e.g. scenario.iter_plan_scenarios). Returns
    (DataFrame with one row per scenario, list of simulations or None).
    results_file: CSV to append each row to as it is done, or a function row -> CSV path (e.g. one
    file per penetration). simulations_folder: folder (or function row -> folder) to save each full
    simulation as run_<n>.npz. keep_simulations=False keeps only the table in memory.
    on_simulation(sim, row): called after every simulation (e.g. to average time series without
    keeping them). verbose: one line per run; progress_every=n: a progress line with the time left
    every n runs (n_scenarios = total, for an iterable without a length)."""
    rows = []
    sims = [] if keep_simulations else None
    total = n_scenarios if n_scenarios is not None else (len(scenarios) if hasattr(scenarios, "__len__") else None)
    started = time.perf_counter()
    for i, scenario in enumerate(scenarios):
        sim = simulate(engine, setup, scenario, reuse_circuit)
        row = {"run": i, **summarise(sim, setup.limits, setup.customer_phases)}
        rows.append(row)
        if results_file:
            res.append_row(results_file(row) if callable(results_file) else results_file, row)
        if simulations_folder:
            folder = simulations_folder(row) if callable(simulations_folder) else simulations_folder
            res.save_simulation(sim, Path(folder) / f"run_{i}.npz")
        if on_simulation:
            on_simulation(sim, row)
        if keep_simulations:
            sims.append(sim)
        if verbose:
            tags = scenario.tags
            print(f"run {i + 1}/{total or '?'}: {tags.get('window', '')} {tags.get('pv_mode', '')} "
                  f"{tags.get('penetration_pct', '')}% -> {row['n_noncompliant_customers']} non-compliant, "
                  f"V max {row['v_max_pu']:.4f} pu")
        elif progress_every and ((i + 1) % progress_every == 0 or i + 1 == total):
            elapsed = time.perf_counter() - started
            left = f", about {format_duration(elapsed / (i + 1) * (total - i - 1))} left" if total else ""
            print(f"  {i + 1}/{total or '?'} daily runs done in {format_duration(elapsed)}{left}", flush=True)
    return res.to_table(rows), sims


def format_duration(seconds):
    """'45 s', '12.5 min' or '3.2 h'."""
    return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.1f} min" if seconds < 5400 else f"{seconds / 3600:.1f} h"


def estimate_runtime(engine, setup, scenarios, n_total, n_sample=8):
    """Seconds the whole study should take, from timing the first 'n_sample' scenarios of an iterable
    (they are simulated and thrown away). Use it to print the expected run time before a long study."""
    sample = []
    for scenario in scenarios:
        sample.append(scenario)
        if len(sample) == n_sample:
            break
    started = time.perf_counter()
    for scenario in sample:
        simulate(engine, setup, scenario)
    return (time.perf_counter() - started) / max(len(sample), 1) * n_total


def worst_case_pv_profile(engine, setup, scenario, candidates, reuse_circuit=False):
    """Index of the candidate PV profile (rows of 'candidates') that gives the highest customer
    voltage when swapped into 'scenario', and the highest voltage of each candidate."""
    v_max = [simulate(engine, setup, scenario.with_pv_profile(c), reuse_circuit)["V"].max() for c in candidates]
    return int(np.argmax(v_max)), v_max


def hosting_capacity(table, max_utilisation_pct=100):
    """Largest penetration for which this and every lower penetration has no non-compliant customer
    and a transformer utilisation within 'max_utilisation_pct' %. 'table' = DataFrame or list of rows
    with 'penetration_pct', 'n_noncompliant_customers' and 'transformer_utilisation_pct'.
    None if even the lowest fails."""
    rows = table.to_dict("records") if hasattr(table, "to_dict") else list(table)
    capacity = None
    for r in sorted(rows, key=lambda r: r["penetration_pct"]):
        if r["n_noncompliant_customers"] > 0 or r["transformer_utilisation_pct"] > max_utilisation_pct:
            break
        capacity = r["penetration_pct"]
    return capacity


def hosting_capacity_table(table, group_by=("pv_mode",), max_utilisation_pct=100):
    """Hosting capacity of every group of rows (e.g. per PV mode, or per PV mode and day). Within a
    group, each penetration is judged by its worst row (most non-compliant customers, highest
    utilisation), so a penetration passes only if it passes on every day of the group.
    Returns a DataFrame: the group columns, hosting_capacity_pct, and the PV systems at that %."""
    group_by = list(group_by)
    rows = []
    for keys, group in table.dropna(subset=["penetration_pct"]).groupby(group_by, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        worst = group.groupby("penetration_pct", as_index=False).agg(
            n_noncompliant_customers=("n_noncompliant_customers", "max"),
            transformer_utilisation_pct=("transformer_utilisation_pct", "max"),
            n_pv_systems=("n_pv_systems", "max"))
        capacity = hosting_capacity(worst, max_utilisation_pct)
        n_pv = None if capacity is None else int(worst.loc[worst["penetration_pct"] == capacity, "n_pv_systems"].iloc[0])
        rows.append({**dict(zip(group_by, keys)), "hosting_capacity_pct": capacity, "n_pv_systems_at_capacity": n_pv,
                     "highest_penetration_tested_pct": worst["penetration_pct"].max()})
    return res.to_table(rows)


def summarise_groups(table, group_by=("pv_mode", "penetration_pct")):
    """One row per group of results rows (e.g. per PV mode and penetration, over all simulated
    days): days simulated, days with a non-compliant customer, the worst values, and the PV
    curtailment over the whole group (curtailed energy / available energy)."""
    grouped = table.groupby(list(group_by), sort=False, dropna=False)
    summary = grouped.agg(n_days=("pv_day", "nunique"),
                          n_days_noncompliant=("n_noncompliant_customers", lambda n: int((n > 0).sum())),
                          max_noncompliant_customers=("n_noncompliant_customers", "max"),
                          v_max_pu=("v_max_pu", "max"), v_min_pu=("v_min_pu", "min"),
                          max_transformer_utilisation_pct=("transformer_utilisation_pct", "max"),
                          pv_available_kwh=("pv_available_kwh", "sum"), pv_curtailed_kwh=("pv_curtailed_kwh", "sum"),
                          pv_reactive_kvarh=("pv_reactive_kvarh", "sum")).reset_index()
    available = summary["pv_available_kwh"].where(summary["pv_available_kwh"] > 0)
    summary["pv_curtailed_pct"] = (100 * summary["pv_curtailed_kwh"] / available).fillna(0.0)
    return summary


# --- Randomized runs: day-cases, pass share and hosting capacity --------------------------------------
# A day-case is one simulation: one randomized run of one penetration and PV mode, on one day.
def violation_limit(threshold, unit, n_customers):
    """Largest violation score a day-case may have and still pass. unit "customers": 'threshold'
    customers; unit "pct_of_customers": 'threshold' % of the circuit's customers."""
    if unit == "customers":
        return float(threshold)
    if unit == "pct_of_customers":
        return threshold / 100 * n_customers
    raise ValueError(f"unit must be 'customers' or 'pct_of_customers', not {unit!r}")


def score_day_cases(table, max_violations, transformer_overload_weight=5):
    """Add to a results table: voltage_violations (= non-compliant customers), overload_violations
    (= transformer_overload_weight if the transformer went over its rating, else 0),
    violation_score (their sum) and passes (violation_score <= max_violations)."""
    table = table.copy()
    table["voltage_violations"] = table["n_noncompliant_customers"]
    table["overload_violations"] = np.where(table["transformer_overloaded"], transformer_overload_weight, 0)
    table["violation_score"] = table["voltage_violations"] + table["overload_violations"]
    table["passes"] = table["violation_score"] <= max_violations
    return table


def pass_share_table(scored, group_by=("pv_mode", "penetration_pct")):
    """Per group (by default each PV mode and penetration), every day of every run counted as its own
    day-case: n_day_cases, n_passed, pass_share_pct, day-cases with voltage violations and with a
    transformer overload, and the mean / worst violation score."""
    grouped = scored.groupby(list(group_by), sort=False, dropna=False)
    table = grouped.agg(n_runs=("random_run", "nunique"), n_days=("pv_day", "nunique"),
                        n_day_cases=("passes", "size"), n_passed=("passes", "sum"),
                        n_voltage_violation_cases=("voltage_violations", lambda v: int((v > 0).sum())),
                        n_overload_cases=("overload_violations", lambda v: int((v > 0).sum())),
                        mean_violation_score=("violation_score", "mean"),
                        max_violation_score=("violation_score", "max")).reset_index()
    table["n_passed"] = table["n_passed"].astype(int)
    table["pass_share_pct"] = 100 * table["n_passed"] / table["n_day_cases"]
    table["voltage_violation_case_pct"] = 100 * table["n_voltage_violation_cases"] / table["n_day_cases"]
    table["overload_case_pct"] = 100 * table["n_overload_cases"] / table["n_day_cases"]
    return table


def hosting_capacity_from_pass_share(pass_shares, pass_share_threshold_pct, group_by=("pv_mode",)):
    """Hosting capacity per group (e.g. PV mode): the highest penetration whose pass share, and the
    pass share of every lower penetration, is at least 'pass_share_threshold_pct'. Returns a
    DataFrame with hosting_capacity_pct (None if the lowest fails) and the day-cases passed there."""
    rows = []
    for keys, group in pass_shares.dropna(subset=["penetration_pct"]).groupby(list(group_by), sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        capacity, at_capacity = None, None
        for r in group.sort_values("penetration_pct").to_dict("records"):
            if r["pass_share_pct"] < pass_share_threshold_pct:
                break
            capacity, at_capacity = r["penetration_pct"], r
        rows.append({**dict(zip(group_by, keys)), "hosting_capacity_pct": capacity,
                     "n_day_cases": None if at_capacity is None else at_capacity["n_day_cases"],
                     "n_passed": None if at_capacity is None else at_capacity["n_passed"],
                     "pass_share_pct": None if at_capacity is None else at_capacity["pass_share_pct"],
                     "pass_share_threshold_pct": pass_share_threshold_pct,
                     "highest_penetration_tested_pct": group["penetration_pct"].max()})
    return res.to_table(rows)


def average_runs(table, group_by=("pv_mode", "penetration_pct", "pv_rank")):
    """Mean of every numeric result over the randomized runs of each group (by default each PV mode,
    penetration and PV day), plus n_runs. Days stay separate unless 'group_by' leaves pv_rank out."""
    numeric = [c for c in table.columns if c not in group_by and c not in ("run", "random_run")
               and pd_types.is_numeric_dtype(table[c]) and not pd_types.is_bool_dtype(table[c])]
    grouped = table.groupby(list(group_by), sort=False, dropna=False)
    averaged = grouped[numeric].mean().reset_index()
    averaged.insert(len(group_by), "n_runs", grouped.size().values)
    return averaged


PLACEMENT_RANKING = [("violation_score", True), ("pv_delivered_kwh", False), ("pv_curtailed_kwh", True),
                     ("pv_reactive_abs_kvarh", True), ("pv_kva_phase_spread", True), ("v_max_phase_spread_pu", True),
                     ("first_simulation", True)]


def best_placement_runs(scored, group_by=("penetration_pct",)):
    """The best (randomized run, PV mode) of each group, every day of the run added together, ranked by
    PLACEMENT_RANKING: fewest violations, most PV energy delivered, least curtailed, least reactive
    energy, best phase balance (smallest spread of installed PV kVA between phases, then of the
    phases' highest voltages), then the first evaluated. "no_pv" rows are left out.
    Returns one row per group: random_run, pv_mode and the ranking values."""
    with_pv = scored[scored["pv_mode"] != "no_pv"].copy()
    with_pv["pv_reactive_abs_kvarh"] = with_pv["pv_reactive_kvarh"].abs()
    for column in ("pv_kva_phase_spread", "v_max_phase_spread_pu"):
        if column not in with_pv:
            with_pv[column] = 0.0
    keys = list(group_by) + ["random_run", "pv_mode"]
    runs = with_pv.groupby(keys, sort=False, dropna=False).agg(
        violation_score=("violation_score", "sum"), pv_delivered_kwh=("pv_delivered_kwh", "sum"),
        pv_curtailed_kwh=("pv_curtailed_kwh", "sum"), pv_reactive_abs_kvarh=("pv_reactive_abs_kvarh", "sum"),
        pv_kva_phase_spread=("pv_kva_phase_spread", "first"), v_max_phase_spread_pu=("v_max_phase_spread_pu", "mean"),
        first_simulation=("run", "min")).reset_index()
    columns, ascending = zip(*PLACEMENT_RANKING)
    ranked = runs.sort_values(list(columns), ascending=list(ascending), kind="stable")
    return ranked.groupby(list(group_by), sort=False, dropna=False).head(1).reset_index(drop=True)


def verify_reuse(engine, setup, scenarios, atol=1e-6):
    """Run the scenarios with a full rebuild and with reuse_circuit=True and compare every recorded
    array. Returns {array: largest difference} and prints PASS/FAIL. Run this on a new network
    before using reuse_circuit for a study."""
    rebuilt = [simulate(engine, setup, s, reuse_circuit=False) for s in scenarios]
    _BASE.pop(id(engine), None)
    reused = [simulate(engine, setup, s, reuse_circuit=True) for s in scenarios]
    diff = {k: max(float(np.abs(a[k] - b[k]).max()) if a[k].size else 0.0 for a, b in zip(rebuilt, reused))
            for k in res.SIM_ARRAYS}
    worst = max(diff.values())
    print(f"reuse_circuit check on {len(scenarios)} scenarios: largest difference {worst:.2e} -> "
          f"{'PASS' if worst <= atol else 'FAIL'} (tolerance {atol:g})")
    return diff
