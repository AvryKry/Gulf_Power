"""Time-series (daily) simulation: load and PV profiles, allocation to customers, stepping
through the day and recording results.
"""
import math

import numpy as np

from . import der, engine as eng, extract, network as net


# --- Profile data (no OpenDSS needed) ---------------------------------------------------------
def load_profile_data(path):
    """Load a .npy profile file and print its shape."""
    data = np.load(path)
    print(f"{path.name if hasattr(path, 'name') else path}: shape {data.shape}")
    return data


def reactive_power(p, power_factor):
    """Q [kvar] for active power p [kW] at a (lagging) power factor; both can be arrays."""
    return np.asarray(p) * np.tan(np.arccos(power_factor))


def random_power_factors(rng, n_steps, pf_range):
    """A random power factor for every time step, uniform within pf_range = (low, high)."""
    return rng.uniform(pf_range[0], pf_range[1], n_steps)


def customer_order(names, seed):
    """A fixed random order of the customers. Taking the first n customers of the same order for
    every penetration keeps the customers that already have PV when the penetration increases."""
    return list(np.random.default_rng(seed).permutation(names))


def pv_customers(order, penetration_pct):
    """The customers with PV for a penetration (% of customers), taken from 'order'."""
    return order[:round(len(order) * penetration_pct / 100)]


# --- Allocation to the circuit -----------------------------------------------------------------
def allocate_load_profiles(engine, load_names, day_profiles, rng, pf_range, step_minutes):
    """Give every load a random profile from 'day_profiles' (n_profiles x n_steps, in kW) and a
    reactive profile from random power factors. Returns {load: (profile index, P, Q)}."""
    allocation, commands = {}, []
    for load in load_names:
        index = int(rng.integers(day_profiles.shape[0]))
        p = day_profiles[index]
        q = reactive_power(p, random_power_factors(rng, len(p), pf_range))
        shape = f"load_shape_{load}"
        commands += [der.loadshape_command(shape, p, q, step_minutes), der.assign_daily_shape_command(f"Load.{load}", shape)]
        allocation[load] = (index, p, q)
    eng.run_commands(engine, commands)
    return allocation


def add_rooftop_pv(engine, customers, pv_shape, step_minutes, kva, pmpp=None, shape_name="pv_shape"):
    """Add one PV system at the bus of each customer (load), with the same phases and kV as the
    load, following the normalised daily profile 'pv_shape' (0 to 1). Returns the PV names."""
    inventory = net.load_inventory(engine)
    commands = [der.loadshape_command(shape_name, pv_shape, interval_minutes=step_minutes, use_actual=False)]
    names = []
    for load in customers:
        info = inventory[load]
        name = f"pv_{load}"
        commands.append(der.pv_command(name, info["bus"], len(net.bus_phases(info["bus"])), info["kV"], kva, pmpp,
                                       daily_shape=shape_name))
        names.append(name)
    eng.run_commands(engine, commands)
    return names


# --- Stepping through the day -----------------------------------------------------------------
def run_daily(engine, n_steps, step_minutes, recorders):
    """Solve n_steps time steps in daily mode. 'recorders' = {name: function(engine)} is called after
    every step; returns {name: numpy array with one row per step} and whether every step converged."""
    eng.set_daily_mode(engine, step_minutes)
    records = {name: [] for name in recorders}
    converged = True
    for _ in range(n_steps):
        converged &= eng.solve(engine, verbose=False)
        for name, record in recorders.items():
            records[name].append(record(engine))
    return {name: np.array(rows) for name, rows in records.items()}, converged


def record_loads(load_names):
    """Recorder: (P, Q, lowest phase V [pu]) of every load, as an array of shape (3, n_loads)."""
    def record(engine):
        results = extract.load_results(engine, extract.node_voltages(engine))
        return np.array([[results[n][1], results[n][2], results[n][3]] for n in load_names]).T
    return record


def record_transformer(name):
    """Recorder: (P per phase, Q per phase) out of winding 2 of one transformer, shape (2, n_phases)."""
    def record(engine):
        p, q, _, _ = extract.transformer_results(engine)[name]
        return np.array([p, q])
    return record
