"""Running scenarios and hosting capacity studies.

StudySetup = the network and how it is judged (circuit, voltage bases, limits, transformer).
Scenario   = what is simulated (demand, DER, time window), see scenario.py.
simulate() runs one scenario; run_study() runs many and returns one table row per run.

reuse_circuit (off by default): build the circuit once and only swap profiles / switch DER between
runs instead of recompiling for every run. Faster on large feeders; verify_reuse() checks that it
gives the same results as a rebuild before relying on it.
"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import engine as eng, network as net, results as res, timeseries as ts


@dataclass
class StudySetup:
    master_file: str                 # master file of the circuit
    voltage_bases_kv: tuple          # line-to-line voltage bases, e.g. (22.0, 0.4)
    limits: tuple                    # (lowest, highest) allowed customer voltage [pu]
    transformer: str = None          # transformer to monitor (None = the first one)
    transformer_rating_kva: float = None   # rating used for the utilisation (None = nameplate)


# --- The circuit ---------------------------------------------------------------------------------
_BASE = {}   # reuse_circuit state per engine: master file, marker, DER elements, initial taps


def study_customers(engine, setup):
    """Build the circuit and return its load (customer) names."""
    eng.build_circuit(engine, setup.master_file, setup.voltage_bases_kv)
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
    """Put the scenario into the circuit. Rebuild (default): compile, then add everything.
    Reuse: keep the circuit built for this setup, switch off DER not in the scenario, restore
    the initial taps and reset controls, then swap in the scenario's profiles and DER."""
    state = _BASE.get(id(engine))
    circuit_ok = (reuse_circuit and state is not None and state["master"] == setup.master_file
                  and state["marker"] in net.element_names(engine.ActiveCircuit.LoadShapes))
    if not circuit_ok:
        eng.build_circuit(engine, setup.master_file, setup.voltage_bases_kv)
        if reuse_circuit:
            marker = f"toolkit_base_{len(_BASE) + 1}"
            eng.run_commands(engine, [f"new LoadShape.{marker} npts=1 mult=(1)"])
            state = _BASE[id(engine)] = {"master": setup.master_file, "marker": marker, "der": set(),
                                         "taps": transformer_taps(engine)}
    if reuse_circuit:
        loads = net.element_names(engine.ActiveCircuit.Loads)
        if sorted(scenario.customers) != sorted(loads):
            raise ValueError("reuse_circuit needs a demand profile for every load of the circuit")
        ts.set_der_enabled(engine, sorted(state["der"]), False)
        restore_transformer_taps(engine, state["taps"])
        eng.run_commands(engine, ["Reset"])
    elements = ts.apply_scenario(engine, scenario)
    if reuse_circuit:
        ts.set_der_enabled(engine, elements, True)
        state["der"].update(elements)
    return elements


# --- One scenario ----------------------------------------------------------------------------------
def simulate(engine, setup, scenario, reuse_circuit=False):
    """Run a scenario over its whole time window. Returns P, Q, V (customers x steps),
    tx_P, tx_Q (steps x phases), der_P, der_Q (steps x DER) and the scenario itself."""
    elements = prepare_circuit(engine, setup, scenario, reuse_circuit)
    loads = net.element_names(engine.ActiveCircuit.Loads)
    transformer = setup.transformer or net.element_names(engine.ActiveCircuit.Transformers)[0]
    w = scenario.window
    records, converged = ts.run_daily(engine, w.n_steps, w.step_minutes,
                                      {"loads": ts.record_loads(loads), "transformer": ts.record_transformer(transformer),
                                       "der": ts.record_der(elements)})
    engine.ActiveCircuit.Transformers.Name = transformer
    der = records["der"] if elements else np.zeros((w.n_steps, 2, 0))
    return {"scenario": scenario, "loads": loads, "der": elements, "converged": converged,
            "transformer": transformer,
            "transformer_kva": setup.transformer_rating_kva or engine.ActiveCircuit.Transformers.kVA,
            "P": records["loads"][:, 0, :].T, "Q": records["loads"][:, 1, :].T, "V": records["loads"][:, 2, :].T,
            "tx_P": records["transformer"][:, 0, :], "tx_Q": records["transformer"][:, 1, :],
            "der_P": der[:, 0, :], "der_Q": der[:, 1, :]}


# --- Metrics (no OpenDSS needed) ---------------------------------------------------------------------
def noncompliant_customers(voltages, names, limits):
    """Customers whose voltage is outside 'limits' at any time step: {'under': [...], 'over': [...]}"""
    return {"under": [n for n, v in zip(names, voltages) if v.min() < limits[0]],
            "over": [n for n, v in zip(names, voltages) if v.max() > limits[1]]}


def transformer_apparent_power(p, q):
    """|S| [kVA] per step: (total of the three phases, per phase). p, q have shape (n_steps, n_phases)."""
    return np.hypot(p.sum(axis=1), q.sum(axis=1)), np.hypot(p, q)


def summarise(sim, limits):
    """One results row: the scenario's tags + the key numbers of the simulation."""
    bad = noncompliant_customers(sim["V"], sim["loads"], limits)
    s_total, s_phase = transformer_apparent_power(sim["tx_P"], sim["tx_Q"])
    hours = sim["scenario"].window.step_minutes / 60
    tags = {k: v for k, v in sim["scenario"].tags.items() if not isinstance(v, (dict, list))}
    return {**tags, "n_noncompliant": len(set(bad["under"]) | set(bad["over"])), "n_over": len(bad["over"]),
            "n_under": len(bad["under"]), "v_min": sim["V"].min(), "v_max": sim["V"].max(),
            "s_peak": s_total.max(), "utilisation": 100 * s_total.max() / sim["transformer_kva"],
            "phase_utilisation": 100 * s_phase.max() / (sim["transformer_kva"] / s_phase.shape[1]),
            "p_min": sim["tx_P"].sum(axis=1).min(), "pv_energy_kwh": sim["der_P"].sum() * hours,
            "converged": sim["converged"]}


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
            print(f"run {i}: {scenario.tags.get('window', '')} {scenario.tags.get('penetration', '')}% -> "
                  f"{row['n_noncompliant']} non-compliant, V max {row['v_max']:.4f}")
    return res.to_table(rows), sims


def worst_case_pv_profile(engine, setup, scenario, candidates, reuse_circuit=False):
    """Index of the candidate PV profile (rows of 'candidates') that gives the highest customer
    voltage when swapped into 'scenario', and the highest voltage of each candidate."""
    v_max = [simulate(engine, setup, scenario.with_pv_profile(c), reuse_circuit)["V"].max() for c in candidates]
    return int(np.argmax(v_max)), v_max


def hosting_capacity(table, max_utilisation=100):
    """Largest penetration for which this and every lower penetration has no non-compliant customer
    and a transformer utilisation within 'max_utilisation' %. 'table' = DataFrame or list of rows
    with 'penetration', 'n_noncompliant' and 'utilisation'. None if even the lowest fails."""
    rows = table.to_dict("records") if hasattr(table, "to_dict") else list(table)
    capacity = None
    for r in sorted(rows, key=lambda r: r["penetration"]):
        if r["n_noncompliant"] > 0 or r["utilisation"] > max_utilisation:
            break
        capacity = r["penetration"]
    return capacity


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
