"""Time-series simulation bricks: profile data, putting a scenario's demand and DER into the
circuit, stepping through time and recording results.
"""
import numpy as np

from . import der as der_text, engine as eng, extract, network as net


# --- Profile data (no OpenDSS needed) ---------------------------------------------------------
def load_profile_data(path, mmap=False, to_print=False):
    """Load a .npy profile file (and print its shape if to_print). mmap=True reads it lazily from
    disk (for files too large for memory; only the slices used are read)."""
    data = np.load(path, mmap_mode="r" if mmap else None)
    if to_print:
        print(f"{getattr(path, 'name', path)}: shape {data.shape}")
    return data


def profiles_in_window(data, window):
    """The part of 'data' inside a TimeWindow. data has days and steps as its last two axes:
    (days, steps) -> (n_steps,); (profiles, days, steps) -> (profiles, n_steps). Windows may span days."""
    days, steps = data.shape[-2:]
    if steps != window.steps_per_day:
        raise ValueError(f"data has {steps} steps per day but the window expects {window.steps_per_day}")
    end = window.start_step + window.n_steps
    if window.start_step < 0 or end > days * steps:
        raise ValueError(f"window steps {window.start_step}-{end - 1} are outside the data ({days} days)")
    flat = np.asarray(data).reshape(*data.shape[:-2], days * steps)
    return np.array(flat[..., window.start_step:end])


def reactive_power(p, power_factor):
    """Q [kvar] for active power p [kW] at a (lagging) power factor; both can be arrays."""
    return np.asarray(p) * np.tan(np.arccos(power_factor))


def random_power_factors(rng, n_steps, pf_range):
    """A random power factor for every time step, uniform within pf_range = (low, high)."""
    return rng.uniform(pf_range[0], pf_range[1], n_steps)


def customer_order(names, seed):
    """A fixed random order of the customers. Taking the first n of the same order for every
    penetration keeps the customers that already have PV when the penetration increases."""
    return list(np.random.default_rng(seed).permutation(names))


def pv_customers(order, penetration_pct):
    """The customers with PV for a penetration (% of customers), taken from 'order'."""
    return order[:round(len(order) * penetration_pct / 100)]


# --- Putting a scenario into the circuit -----------------------------------------------------------
def demand_commands(demand, step_minutes):
    """Commands that give every load its (P, Q) profile: {load: (P, Q)} -> list of text commands."""
    commands = []
    for load, (p, q) in demand.items():
        shape = f"load_shape_{load}"
        commands += [der_text.loadshape_command(shape, p, q, step_minutes),
                     der_text.assign_daily_shape_command(f"Load.{load}", shape)]
    return commands


def pv_der_commands(d, load_info, step_minutes):
    """Commands for one PV DER: its own normalised shape + a PVSystem at the customer's bus."""
    shape = f"shape_{d.name}"
    return [der_text.loadshape_command(shape, d.profile, interval_minutes=step_minutes, use_actual=False),
            der_text.pv_command(d.name, load_info["bus"], len(net.bus_phases(load_info["bus"])), load_info["kV"],
                                d.kva, d.pmpp, daily_shape=shape)]


# One command builder per DER kind: add "storage", "ev" ... here as the toolkit grows
DER_BUILDERS = {"pv": pv_der_commands}
DER_CLASSES = {"pv": "PVSystem"}


def der_commands(der_list, inventory, step_minutes):
    """Commands for every DER of a scenario; 'inventory' = net.load_inventory(engine)."""
    commands = []
    for d in der_list:
        if d.kind not in DER_BUILDERS:
            raise NotImplementedError(f"DER kind '{d.kind}' has no builder yet (see timeseries.DER_BUILDERS)")
        commands += DER_BUILDERS[d.kind](d, inventory[d.customer], step_minutes)
    return commands


def existing_der(engine):
    """Lower-case names ('pvsystem.pv_x') of the DER elements already in the circuit."""
    found = set()
    for cls in DER_CLASSES.values():
        found.update(f"{cls.lower()}.{n.lower()}" for n in net.element_names(getattr(engine.ActiveCircuit, cls + "s")))
    return found


def edit_if_exists(commands, existing):
    """Turn 'new <Class.name> ...' into 'edit <Class.name> ...' for elements that already exist
    (OpenDSS refuses to define a DER element twice)."""
    out = []
    for c in commands:
        words = c.split(maxsplit=2)
        if words[0].lower() == "new" and words[1].lower() in existing:
            c = "edit " + " ".join(words[1:])
        out.append(c)
    return out


def apply_scenario(engine, scenario):
    """Give the loads the scenario's demand and add its DER (DER already in the circuit, e.g. when
    the circuit is reused, are edited instead). Returns the DER element names."""
    inventory = net.load_inventory(engine)
    missing = [c for c in scenario.customers if c not in inventory]
    if missing:
        raise KeyError(f"customers not in the circuit: {missing[:5]}")
    step = scenario.window.step_minutes
    commands = demand_commands(scenario.demand, step) + der_commands(scenario.der, inventory, step)
    eng.run_commands(engine, edit_if_exists(commands, existing_der(engine)))
    return [f"{DER_CLASSES[d.kind]}.{d.name}" for d in scenario.der]


def set_der_enabled(engine, elements, enabled):
    """Switch DER elements (e.g. 'PVSystem.pv_load_1') on or off without removing them."""
    eng.run_commands(engine, [f"edit {e} enabled={'yes' if enabled else 'no'}" for e in elements])


# --- Stepping through time ---------------------------------------------------------------------------
def run_daily(engine, n_steps, step_minutes, recorders):
    """Solve n_steps time steps in daily mode (works for windows longer than one day). 'recorders' =
    {name: function(engine)} is called after every step; returns ({name: array, one row per step},
    whether every step converged)."""
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


def record_der(elements):
    """Recorder: (P out, Q out) of every DER element (e.g. 'PVSystem.pv_x'), shape (2, n_der)."""
    def record(engine):
        out = np.zeros((2, len(elements)))
        for i, e in enumerate(elements):
            p, q = extract.element_powers(engine, e)
            out[:, i] = -p.sum(), -q.sum()
        return out
    return record
