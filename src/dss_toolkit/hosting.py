"""PV hosting capacity studies built from the time-series bricks.

A StudySetup holds everything that stays the same between runs (circuit, data, settings), so the
same study can be repeated on any network and any profile data by changing only the setup.
"""
from dataclasses import dataclass

import numpy as np

from . import engine as eng, network as net, timeseries as ts


@dataclass
class StudySetup:
    master_file: str                 # master file of the circuit
    voltage_bases_kv: tuple          # line-to-line voltage bases, e.g. (22.0, 0.4)
    load_data: np.ndarray            # load profiles [kW], shape (n_profiles, n_days, n_steps)
    limits: tuple                    # (lowest, highest) allowed customer voltage [pu]
    transformer: str = None          # transformer to monitor (None = the first one)
    transformer_rating_kva: float = None   # rating used for the utilisation (None = nameplate)
    pv_kva: float = 10.0             # inverter size of each PV system
    pv_pmpp: float = None            # panel size (None = pv_kva)
    pf_range: tuple = (0.9, 0.98)    # range of the random load power factors
    step_minutes: int = 30
    seed: int = 10                   # same seed = same demand allocation and same PV customers

    @property
    def n_steps(self):
        return self.load_data.shape[-1]


# --- One day ---------------------------------------------------------------------------------
def simulate_day(engine, setup, day, pv_shape, penetration_pct):
    """Build the circuit, allocate the demand of 'day', add PV to 'penetration_pct' % of the
    customers and run the whole day. Returns all the recorded results."""
    eng.build_circuit(engine, setup.master_file, setup.voltage_bases_kv)
    loads = net.element_names(engine.ActiveCircuit.Loads)
    transformer = setup.transformer or net.element_names(engine.ActiveCircuit.Transformers)[0]
    rng = np.random.default_rng([setup.seed, day])           # same demand for every penetration
    allocation = ts.allocate_load_profiles(engine, loads, setup.load_data[:, day, :], rng, setup.pf_range, setup.step_minutes)
    with_pv = ts.pv_customers(ts.customer_order(loads, setup.seed), penetration_pct)
    ts.add_rooftop_pv(engine, with_pv, pv_shape, setup.step_minutes, setup.pv_kva, setup.pv_pmpp)
    records, converged = ts.run_daily(engine, setup.n_steps, setup.step_minutes,
                                      {"loads": ts.record_loads(loads), "transformer": ts.record_transformer(transformer)})
    engine.ActiveCircuit.Transformers.Name = transformer
    return {"day": day, "penetration": penetration_pct, "loads": loads, "pv_customers": with_pv,
            "allocation": allocation, "converged": converged, "transformer": transformer,
            "transformer_kva": setup.transformer_rating_kva or engine.ActiveCircuit.Transformers.kVA,
            "P": records["loads"][:, 0, :].T, "Q": records["loads"][:, 1, :].T, "V": records["loads"][:, 2, :].T,
            "tx_P": records["transformer"][:, 0, :], "tx_Q": records["transformer"][:, 1, :]}


# --- Metrics (no OpenDSS needed) ---------------------------------------------------------------
def noncompliant_customers(voltages, names, limits):
    """Customers whose voltage is outside 'limits' at any time step: {'under': [...], 'over': [...]}"""
    return {"under": [n for n, v in zip(names, voltages) if v.min() < limits[0]],
            "over": [n for n, v in zip(names, voltages) if v.max() > limits[1]]}


def transformer_apparent_power(p, q):
    """|S| [kVA] per step: (total of the three phases, per phase). p, q have shape (n_steps, n_phases)."""
    return np.hypot(p.sum(axis=1), q.sum(axis=1)), np.hypot(p, q)


def summarise_day(sim, limits):
    """The key results of one simulated day."""
    bad = noncompliant_customers(sim["V"], sim["loads"], limits)
    s_total, s_phase = transformer_apparent_power(sim["tx_P"], sim["tx_Q"])
    return {"penetration": sim["penetration"], "n_pv": len(sim["pv_customers"]),
            "n_noncompliant": len(set(bad["under"]) | set(bad["over"])), "n_over": len(bad["over"]), "n_under": len(bad["under"]),
            "v_min": sim["V"].min(), "v_max": sim["V"].max(), "s_peak": s_total.max(),
            "utilisation": 100 * s_total.max() / sim["transformer_kva"],
            "phase_utilisation": 100 * s_phase.max() / (sim["transformer_kva"] / s_phase.shape[1]),
            "p_min": sim["tx_P"].sum(axis=1).min(), "converged": sim["converged"]}


# --- Studies -----------------------------------------------------------------------------------
def penetration_sweep(engine, setup, day, pv_shape, penetrations):
    """Simulate the same day for every penetration. Returns (list of summaries, list of simulations)."""
    sims = [simulate_day(engine, setup, day, pv_shape, pen) for pen in penetrations]
    return [summarise_day(s, setup.limits) for s in sims], sims


def worst_case_pv_profile(engine, setup, day, candidates, penetration_pct=100):
    """Index of the candidate PV profile (rows of 'candidates') that gives the highest customer
    voltage at 'penetration_pct', and the highest voltage of each candidate."""
    v_max = [simulate_day(engine, setup, day, shape, penetration_pct)["V"].max() for shape in candidates]
    return int(np.argmax(v_max)), v_max


def hosting_capacity(summaries, max_utilisation=100):
    """Largest penetration for which this and every lower penetration has no non-compliant
    customer and a transformer utilisation within 'max_utilisation' %. None if even the lowest fails."""
    capacity = None
    for s in sorted(summaries, key=lambda s: s["penetration"]):
        if s["n_noncompliant"] > 0 or s["utilisation"] > max_utilisation:
            break
        capacity = s["penetration"]
    return capacity
