"""Running scenarios and hosting capacity studies.

StudySetup = the network and how it is judged (circuit, voltage bases, limits, transformer).
Scenario   = what is simulated (demand, DER, inverter control, time window), see scenario.py.
simulate() runs one scenario; run_study() runs many and returns one table row per run.

Result columns (one row per simulation, from summarise()):
    n_noncompliant_customers   customers outside the voltage limits at any step
    n_overvoltage_customers / n_undervoltage_customers
    v_min_pu / v_max_pu        lowest / highest customer voltage
    transformer_peak_kva       highest |S| through the monitored transformer
    transformer_utilisation_pct / transformer_phase_utilisation_pct   peak |S| as % of the rating
    transformer_min_p_kw       lowest active power (negative = reverse flow)
    pv_available_kwh / pv_delivered_kwh / pv_curtailed_kwh / pv_curtailed_pct
    pv_reactive_kvarh          reactive energy out of the PV (negative = absorbed, e.g. volt-var)

reuse_circuit (off by default): build the circuit once and only swap profiles / switch DER between
runs instead of recompiling for every run. Faster on large feeders; verify_reuse() checks that it
gives the same results as a rebuild before relying on it. Runs with an inverter control are always
rebuilt (see prepare_circuit).
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import engine as eng, network as net, results as res, timeseries as ts


@dataclass
class StudySetup:
    circuit_source: object           # master file path, or a list of OpenDSS commands
    voltage_bases_kv: tuple          # line-to-line voltage bases, e.g. (22.0, 0.4)
    limits: tuple                    # (lowest, highest) allowed customer voltage [pu]
    transformer: str = None          # transformer to monitor (None = the first one)
    transformer_rating_kva: float = None   # rating used for the utilisation (None = nameplate)
    bus_coordinates: object = None   # coordinates file path or {bus: (x, y)} for maps (None = none)


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


def summarise(sim, limits):
    """One results row: the scenario's tags + the key numbers of the simulation (see the module
    docstring for the columns)."""
    bad = noncompliant_customers(sim["V"], sim["loads"], limits)
    s_total, s_phase = transformer_apparent_power(sim["tx_P"], sim["tx_Q"])
    available, delivered, curtailed, curtailed_pct, reactive = pv_energy(sim)
    tags = {k: v for k, v in sim["scenario"].tags.items() if not isinstance(v, (dict, list))}
    return {**tags, "n_noncompliant_customers": len(set(bad["under"]) | set(bad["over"])),
            "n_overvoltage_customers": len(bad["over"]), "n_undervoltage_customers": len(bad["under"]),
            "v_min_pu": sim["V"].min(), "v_max_pu": sim["V"].max(),
            "transformer_peak_kva": s_total.max(),
            "transformer_utilisation_pct": 100 * s_total.max() / sim["transformer_kva"],
            "transformer_phase_utilisation_pct": 100 * s_phase.max() / (sim["transformer_kva"] / s_phase.shape[1]),
            "transformer_min_p_kw": sim["tx_P"].sum(axis=1).min(),
            "pv_available_kwh": available, "pv_delivered_kwh": delivered, "pv_curtailed_kwh": curtailed,
            "pv_curtailed_pct": curtailed_pct, "pv_reactive_kvarh": reactive, "converged": sim["converged"]}


# --- Many scenarios ----------------------------------------------------------------------------------
def run_study(engine, setup, scenarios, results_file=None, simulations_folder=None, keep_simulations=False,
              reuse_circuit=False, verbose=False):
    """Simulate every scenario. Returns (DataFrame with one row per scenario, list of simulations or None).
    results_file: append each row to this CSV as it is done. simulations_folder: save each full
    simulation as run_<n>.npz. keep_simulations=False keeps only the table in memory."""
    rows = []
    sims = [] if keep_simulations else None
    for i, scenario in enumerate(scenarios):
        sim = simulate(engine, setup, scenario, reuse_circuit)
        row = {"run": i, **summarise(sim, setup.limits)}
        rows.append(row)
        if results_file:
            res.append_row(results_file, row)
        if simulations_folder:
            res.save_simulation(sim, Path(simulations_folder) / f"run_{i}.npz")
        if keep_simulations:
            sims.append(sim)
        if verbose:
            tags = scenario.tags
            print(f"run {i + 1}/{len(scenarios)}: {tags.get('window', '')} {tags.get('pv_mode', '')} "
                  f"{tags.get('penetration_pct', '')}% -> {row['n_noncompliant_customers']} non-compliant, "
                  f"V max {row['v_max_pu']:.4f} pu")
    return res.to_table(rows), sims


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
