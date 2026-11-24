"""Verification and validation of the toolkit's power-flow results (used by Avry_dev_1).

Verification (is the tool computing what physics says it should?), on a small LV network:
    V1 voltage drop grows linearly with load          load_sweep() + linear_fit()
    V2 losses grow with the square of the load        load_sweep() + square_fit()
    V3 power balance: source + PV = load + losses     every snapshot (extract.power_balance)
    V4 PV raises voltage linearly; reverse flow appears once PV > load + losses     pv_sweep()
    V5 inverter output follows its volt-var / volt-watt curve        inverter_curve_points()
    V6 voltage unbalance grows linearly with one-phase injection      unbalance_sweep()
    V7 Monte Carlo results converge as runs are added                 monte_carlo_convergence()
    V8 a run repeated with the same seeds gives identical results     compare_tables()
Validation (does the tool agree with an independent reference?):
    the IEEE 123 node test feeder against the published radial power flow results
    (read_radial_flow_report(), reference_metrics(), tool_metrics(), compare_metrics()).
GIS overlay: the network drawn on a web map (plot_gis_overlay()). This is the only function of
the toolkit that uses the internet: contextily downloads map tiles (images) for the area shown.
Only the tile numbers of that area are sent; no network data leaves the computer, and nothing
else is uploaded. Without internet (or without pyproj / contextily) the network is drawn
without the map and a note says why.

Every check returns plain rows (dicts) for one verification_checks.csv; plots only build figures
(plots.save_figure() saves them).
"""
import re

import matplotlib.pyplot as plt
import numpy as np

from . import der as der_text, engine as eng, extract, hosting, network as net, plots, results as res

CHECK_COLOURS = {"V1": "#2a78d6", "V2": "#eb6834", "V3": "#1baf7a", "V4": "#6250d6", "V5 volt-var": "#e87ba4",
                 "V5 volt-watt": "#52514e", "V6": "#eda100"}
CASE_MARKERS = {0: "o", 1: "s", 2: "D", 3: "^"}


# --- Check rows --------------------------------------------------------------------------------
def check_row(check, name, value, limit, unit, passed, detail=""):
    """One row of verification_checks.csv."""
    return {"check": check, "name": name, "value": value, "limit": limit, "unit": unit,
            "result": "PASS" if passed else "FAIL", "detail": detail}


def linear_fit(x, y):
    """Least-squares line y = slope x + intercept: (slope, intercept, R squared, fitted y)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    return slope, intercept, r_squared(y, fitted), fitted


def square_fit(x, y):
    """y = c + a x^2 (c = losses that do not depend on the load, e.g. transformer no-load losses):
    (a, c, R squared, fitted y)."""
    a, c, r2, fitted = linear_fit(np.asarray(x, float) ** 2, y)
    return a, c, r2, fitted


def r_squared(y, fitted):
    y, fitted = np.asarray(y, float), np.asarray(fitted, float)
    total = ((y - y.mean()) ** 2).sum()
    return 1.0 - ((y - fitted) ** 2).sum() / total if total > 0 else 1.0


# --- Snapshots and sweeps -----------------------------------------------------------------------
def snapshot(engine, limits, commands=(), control_mode="active", max_control_iterations=1000, max_iterations=15):
    """Run 'commands', solve one snapshot and return extract.collect_results() plus
    balance_kw (extract.power_balance) and balance_pct (% of the power put into the network:
    source power taken from the grid + PV)."""
    eng.run_commands(engine, commands)
    eng.set_snapshot_mode(engine, max_control_iterations, max_iterations, control_mode)
    converged = eng.solve(engine, verbose=False)
    r = extract.collect_results(engine, limits)
    r["converged"] = converged
    r["balance_kw"] = extract.power_balance(r)
    r["balance_pct"] = 100 * abs(r["balance_kw"]) / max(max(r["P_source"], 0) + r["P_pv"], 1e-9)
    return r


def _row(case, x, r, **extra):
    return {"case": case, "x": x, "converged": r["converged"], "P_source_kw": r["P_source"],
            "Q_source_kvar": r["Q_source"], "P_load_kw": r["P_load"], "P_pv_kw": r["P_pv"], "P_loss_kw": r["P_loss"],
            "v_min_pu": r["v_min"], "v_max_pu": r["v_max"], "balance_kw": r["balance_kw"],
            "balance_pct": r["balance_pct"], **extra}


def load_sweep(engine, setup, multipliers):
    """V1 / V2: one snapshot per load multiplier (OpenDSS LoadMult, no PV) plus one at almost no
    load (the reference for the voltage drop). Rows: x = multiplier, largest_drop_pu (largest
    fall of any node voltage from the no-load solution), losses and power balance."""
    hosting.build_study_circuit(engine, setup)
    reference = snapshot(engine, setup.limits, ["Set LoadMult=0.000001"])["vnode"]
    rows = []
    for k in multipliers:
        r = snapshot(engine, setup.limits, [f"Set LoadMult={k}"])
        drop = max(reference[n] - v for n, v in r["vnode"].items() if reference.get(n, 0) > extract.DEAD_NODE_PU)
        rows.append(_row("load_sweep", k, r, largest_drop_pu=drop))
    return rows


def add_pv_to_customers(engine, customers, kw_each, name_prefix="vv_pv"):
    """Commands for one PV system (unity power factor, full sun) of kw_each kVA at each customer's
    bus, using der.pv_command(); kvarMax = kVA so an inverter control may use it."""
    inventory = net.load_inventory(engine)
    commands = []
    for c in customers:
        bus = inventory[c]["bus"]
        commands.append(der_text.pv_command(f"{name_prefix}_{c}", bus, len(net.bus_phases(bus)), net.der_kv(inventory[c]),
                                            kw_each, kvar_max=kw_each))
    return commands


def pv_sweep(engine, setup, pv_kw_per_customer, load_multiplier=1.0, customers=None):
    """V4: PV of each size [kW] at every customer (or 'customers'), loads at load_multiplier.
    Rows: x = total PV [kW], voltage_rise_pu at the node with the highest voltage at the largest
    PV (its voltage minus that without PV), reverse_flow (source power below 0), whether PV is above
    load + losses, and the power balance."""
    rows, voltages = [], []
    for kw in pv_kw_per_customer:
        hosting.build_study_circuit(engine, setup)
        chosen = customers or net.element_names(engine.ActiveCircuit.Loads)
        commands = [f"Set LoadMult={load_multiplier}"] + (add_pv_to_customers(engine, chosen, kw) if kw > 0 else [])
        r = snapshot(engine, setup.limits, commands)
        voltages.append(r["vnode"])
        rows.append(_row("pv_sweep", r["P_pv"], r, pv_kw_each=kw, reverse_flow=r["P_source"] < 0,
                         pv_above_load_and_losses=r["P_pv"] > r["P_load"] + r["P_loss"]))
    node = max(voltages[-1], key=voltages[-1].get)
    for row, v in zip(rows, voltages):
        row.update(rise_node=node, voltage_rise_pu=v[node] - voltages[0][node])
    return rows


def sequence_voltages(engine, bus):
    """(positive, negative) sequence voltage magnitudes [V] of a three-phase bus."""
    engine.ActiveCircuit.SetActiveBus(bus)
    b = engine.ActiveCircuit.ActiveBus
    v = np.asarray(b.Voltages).reshape(-1, 2)
    nodes = list(b.Nodes)
    phasors = np.array([complex(*v[nodes.index(n)]) for n in (1, 2, 3)])
    a = np.exp(2j * np.pi / 3)
    v1 = (phasors[0] + a * phasors[1] + a * a * phasors[2]) / 3
    v2 = (phasors[0] + a * a * phasors[1] + a * phasors[2]) / 3
    return abs(v1), abs(v2)


def voltage_unbalance_pct(engine, bus):
    """Voltage unbalance factor |V2| / |V1| [%] of a three-phase bus."""
    v1, v2 = sequence_voltages(engine, bus)
    return 100 * v2 / v1


def unbalance_sweep(engine, setup, pv_kw_per_customer, phase="A", load_multiplier=0.000001):
    """V6: PV of each size [kW] only at the customers on one feeder phase (network.customer_phases),
    almost no load, so the injection is the only unbalance. Rows: x = PV on that phase [kW],
    vuf_pct at the three-phase bus with the largest unbalance at the largest PV."""
    rows, unbalance = [], []
    for kw in pv_kw_per_customer:
        hosting.build_study_circuit(engine, setup)
        on_phase = [c for c, p in net.customer_phases(engine).items() if p == phase]
        commands = [f"Set LoadMult={load_multiplier}"] + (add_pv_to_customers(engine, on_phase, kw) if kw > 0 else [])
        r = snapshot(engine, setup.limits, commands)
        unbalance.append({b: voltage_unbalance_pct(engine, b) for b in net.three_phase_buses(engine)})
        rows.append(_row("unbalance_sweep", r["P_pv"], r, pv_kw_each=kw, phase=phase, n_customers_on_phase=len(on_phase)))
    bus = max(unbalance[-1], key=unbalance[-1].get)
    for row, vuf in zip(rows, unbalance):
        row.update(bus=bus, vuf_pct=vuf[bus])
    return rows


# --- V5 inverter curves -------------------------------------------------------------------------
def inverter_voltage_bases(engine):
    """Every PV system's rated kV against the voltage base of its bus (network.bus_kv_base):
    rows pv, bus, kv_rated, kv_base, ratio. ratio = 1 means the inverter reads its voltage in the
    same per unit as the node voltages (what network.der_kv sets up)."""
    rows = []
    pvs = engine.ActiveCircuit.PVSystems
    for name in net.element_names(pvs):
        bus = net.element_bus(engine, f"PVSystem.{name}")
        engine.ActiveCircuit.SetActiveElement(f"PVSystem.{name}")
        kv = float(engine.ActiveCircuit.ActiveCktElement.Properties("kV").Val)
        phases = engine.ActiveCircuit.ActiveCktElement.NumPhases
        base = net.bus_kv_base(engine, bus, phases)
        rows.append({"pv": name, "bus": net.bus_name(bus), "kv_rated": kv, "kv_base": base,
                     "ratio": base / kv if base else float("nan")})
    return rows


def inverter_curve_points(sim, control, min_available_pu=0.05):
    """Every (PV, step) of a daily simulation (hosting.simulate) with an inverter control, against
    the control's curve. Volt-var: Q [pu of kVA] vs curve(V). Volt-watt: P [pu of Pmpp] vs
    min(available, curve(V)). V is the customer's node voltage, which is also the inverter's
    voltage when the PV is rated at the bus voltage base (inverter_voltage_bases). Steps where the
    PV has less than min_available_pu are left out (the inverter is off). Rows: customer, step, v_pu, output_pu, expected_pu, error_pu."""
    scenario = sim["scenario"]
    row_of = {load.lower(): i for i, load in enumerate(sim["loads"])}
    rows = []
    for j, d in enumerate(scenario.der):
        rating = d.pmpp or d.kva
        for step in range(sim["der_P"].shape[0]):
            available = sim["der_available_P"][step, j] / rating
            if available < min_available_pu:
                continue
            v = sim["V"][row_of[d.customer.lower()], step]
            curve = float(np.interp(v, control.voltage_pu, control.output_pu))
            if control.mode == "volt_var":
                output, expected = sim["der_Q"][step, j] / d.kva, curve
            else:
                output, expected = sim["der_P"][step, j] / rating, min(available, curve)
            rows.append({"mode": control.mode, "settings": control.extra or "study defaults", "customer": d.customer,
                         "step": step, "v_pu": v, "available_pu": available, "output_pu": output,
                         "expected_pu": expected, "error_pu": output - expected})
    return rows


# --- V7 / V8 Monte Carlo -----------------------------------------------------------------------
def running_mean_ci(values, z=1.96):
    """Running mean and 95 % confidence half-width after 1, 2, ... n values."""
    values = np.asarray(values, float)
    n = np.arange(1, len(values) + 1)
    mean = np.cumsum(values) / n
    square = np.cumsum(values ** 2) / n
    std = np.sqrt(np.maximum(square - mean ** 2, 0) * n / np.maximum(n - 1, 1))
    return mean, z * std / np.sqrt(n)


def convergence_state(table, metrics):
    """{metric: (mean, half-width, change of the mean over the last 10 % of runs, tolerance, ok)}.
    'metrics' = {column: tolerance}; converged when the 95 % half-width and the recent change of
    the mean are both within the tolerance."""
    state = {}
    for column, tolerance in metrics.items():
        mean, half = running_mean_ci(table[column].astype(float))
        back = max(1, len(mean) // 10)
        drift = abs(mean[-1] - mean[-1 - back]) if len(mean) > back else float("inf")
        state[column] = (mean[-1], half[-1], drift, tolerance, half[-1] <= tolerance and drift <= tolerance)
    return state


def monte_carlo_convergence(engine, setup, scenarios, metrics, min_runs=200, max_runs=2000, batch_runs=100,
                            prepare=None, base_circuit=None):
    """V7: run scenarios (an iterator, e.g. scenario.iter_plan_scenarios) in batches with
    hosting.run_study() until every metric has converged (convergence_state) and at least
    min_runs are done, or max_runs is reached. prepare(table) adds metric columns (e.g. passes
    from hosting.score_day_cases). Returns (table, converged, state)."""
    import itertools
    import pandas as pd
    tables, done = [], 0
    while done < max_runs:
        n = min(batch_runs, max_runs - done)
        part, _ = hosting.run_study(engine, setup, itertools.islice(scenarios, n), base_circuit=base_circuit)
        if part.empty:
            break
        part["run"] += done
        tables.append(part)
        done += len(part)
        table = pd.concat(tables, ignore_index=True)
        table = prepare(table) if prepare else table
        state = convergence_state(table, metrics)
        print(f"  Monte Carlo: {done} runs, " + ", ".join(
            f"{c} {m:.4g} +/- {h:.2g}" for c, (m, h, _, _, _) in state.items()), flush=True)
        if done >= min_runs and all(s[-1] for s in state.values()):
            return table, True, state
    return table, False, state


def compare_tables(first, second, columns):
    """V8: largest absolute difference of each numeric column between two result tables."""
    n = min(len(first), len(second))
    return {c: float(np.abs(first[c].iloc[:n].astype(float).values - second[c].iloc[:n].astype(float).values).max())
            for c in columns}


# --- IEEE 123 validation -----------------------------------------------------------------------
PHASES = "ABC"
_NODE = re.compile(r"^\s*NODE:\s*(\S+)\s+VOLTS:(.*)MAG/ANG")
_BRANCH = re.compile(r"^\s*TO NODE\s+(\S+)\s+(<VRG>)?[.\s]*:(.*)AMP/DG")


def _columns(text):
    """Three 16-character phase columns 'magnitude angle' of a radial flow report line."""
    values = []
    for k in range(3):
        parts = text[16 * k: 16 * (k + 1)].split()
        values.append((float(parts[0]), float(parts[1])) if len(parts) == 2 else None)
    return values


def read_radial_flow_report(path):
    """Kersting's radial power flow report (IEEE PES test feeder results). Returns
    (node voltages: rows node, phase, v_pu, angle_deg; branch currents: rows to_node, phase,
    current_a, regulator)."""
    nodes, branches = [], []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _NODE.match(line)
            if m:
                for phase, value in zip(PHASES, _columns(m.group(2))):
                    if value:
                        nodes.append({"node": m.group(1).lower(), "phase": phase, "v_pu": value[0], "angle_deg": value[1]})
                continue
            m = _BRANCH.match(line)
            if m:
                for phase, value in zip(PHASES, _columns(m.group(3))):
                    if value:
                        branches.append({"to_node": m.group(1).lower(), "phase": phase, "current_a": value[0],
                                         "regulator": bool(m.group(2))})
    return res.to_table(nodes), res.to_table(branches)


def set_transformer_taps(engine, taps, step_pu=0.00625, winding=2):
    """Hold regulator transformers at given tap positions: {transformer: tap (-16..16)}; tap
    voltage = 1 + tap x step_pu (5/8 % per step). Solve with control_mode "fixed" to keep them."""
    eng.run_commands(engine, [f"Edit Transformer.{t} wdg={winding} Tap={1 + tap * step_pu:.6f}" for t, tap in taps.items()])


def node_comparison(vnode, reference_nodes, node_names=None):
    """Tool vs reference voltage of every node in both. vnode = extract.node_voltages();
    node_names = {reference node: OpenDSS bus} where the names differ (e.g. RG1 -> 150r)."""
    node_names = {k.lower(): v.lower() for k, v in (node_names or {}).items()}
    rows = []
    for r in reference_nodes.to_dict("records"):
        bus = node_names.get(r["node"], r["node"])
        key = f"{bus}.{PHASES.index(r['phase']) + 1}"
        if key in vnode:
            rows.append({"node": r["node"], "bus": bus, "phase": r["phase"], "reference_pu": r["v_pu"],
                         "tool_pu": vnode[key], "error_pu": vnode[key] - r["v_pu"]})
    return res.to_table(rows)


def phase_powers(engine, source="source"):
    """Active and reactive power supplied by a voltage source per phase: ([kW A, B, C], [kvar A, B, C])."""
    p, q = extract.element_powers(engine, f"Vsource.{source}")
    return -p[:3], -q[:3]


def highest_line_currents(engine):
    """Highest current of any line per phase [A] (by the node number of the line's first bus)."""
    best = {ph: 0.0 for ph in PHASES}
    lines = engine.ActiveCircuit.Lines
    for name in net.element_names(lines):
        lines.Name = name
        el = engine.ActiveCircuit.ActiveCktElement
        current = el.CurrentsMagAng[0:2 * el.NumConductors:2]
        for node, i in zip(net.bus_nodes_from_text(lines.Bus1), current):
            if 1 <= node <= 3:
                best[PHASES[node - 1]] = max(best[PHASES[node - 1]], i)
    return best


def voltage_metrics(comparison, column):
    """{metric: value}: lowest / highest / mean node voltage per phase of one column."""
    out = {}
    for phase, group in comparison.groupby("phase"):
        out[f"Lowest voltage, phase {phase}"] = group[column].min()
        out[f"Highest voltage, phase {phase}"] = group[column].max()
        out[f"Mean voltage, phase {phase}"] = group[column].mean()
    return out


def reference_metrics(comparison, totals, branches):
    """Reference value of every validation metric. totals = the system totals table
    (quantity, phase_a, phase_b, phase_c, total); branches = read_radial_flow_report()[1]."""
    t = {r["quantity"]: r for r in totals.to_dict("records")}
    out = voltage_metrics(comparison, "reference_pu")
    for phase in PHASES:
        out[f"Source active power, phase {phase}"] = t["input_active_power"][f"phase_{phase.lower()}"]
        out[f"Source reactive power, phase {phase}"] = t["input_reactive_power"][f"phase_{phase.lower()}"]
    out["Source active power, total"] = t["input_active_power"]["total"]
    out["Source reactive power, total"] = t["input_reactive_power"]["total"]
    out["Active power losses, total"] = t["losses_active_power"]["total"]
    out["Reactive power losses, total"] = t["losses_reactive_power"]["total"]
    lines = branches[~branches["regulator"]]
    for phase in PHASES:
        out[f"Highest line current, phase {phase}"] = lines.loc[lines["phase"] == phase, "current_a"].max()
    return out


def tool_metrics(engine, comparison):
    """Tool value of every validation metric (same names as reference_metrics) of the solved circuit."""
    out = voltage_metrics(comparison, "tool_pu")
    p, q = phase_powers(engine)
    for k, phase in enumerate(PHASES):
        out[f"Source active power, phase {phase}"] = p[k]
        out[f"Source reactive power, phase {phase}"] = q[k]
    totals = extract.feeder_totals(engine)
    out["Source active power, total"] = totals["P_source"]
    out["Source reactive power, total"] = totals["Q_source"]
    out["Active power losses, total"] = totals["P_loss"]
    out["Reactive power losses, total"] = totals["Q_loss"]
    for phase, i in highest_line_currents(engine).items():
        out[f"Highest line current, phase {phase}"] = i
    return out




def metric_group(metric):
    """voltage, power, losses or current: which tolerance applies to a metric."""
    m = metric.lower()
    return "losses" if "losses" in m else "voltage" if "voltage" in m else "current" if "current" in m else "power"


def compare_metrics(case, tool, reference, tolerances_pct):
    """Rows of validation_errors.csv: normalized error (tool - reference) / reference [%] of every
    metric and whether it is within tolerances_pct[metric_group(metric)]."""
    rows = []
    for metric, ref in reference.items():
        value = tool[metric]
        error = 100 * (value - ref) / ref if ref else float("nan")
        tolerance = tolerances_pct[metric_group(metric)]
        unit = "pu" if "voltage" in metric.lower() else "A" if "current" in metric.lower() else (
            "kvar" if "reactive" in metric.lower() else "kW")
        rows.append({"case": case, "metric": metric, "group": metric_group(metric), "unit": unit, "reference": ref,
                     "tool": value, "error_pct": error, "tolerance_pct": tolerance,
                     "result": "PASS" if abs(error) <= tolerance else "FAIL"})
    return rows


# --- Figures --------------------------------------------------------------------------------------
def plot_fit_check(x, y, fitted, xlabel, ylabel, title, note, extra=None):
    """A verification check plot: simulated points and the first-principles fit."""
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    order = np.argsort(x)
    ax.plot(np.asarray(x)[order], np.asarray(fitted)[order], color=plots.INK, lw=1.5, label="first-principles fit")
    ax.scatter(x, y, s=50, color="#2a78d6", zorder=3, edgecolor="white", linewidth=1, label="tool (OpenDSS)")
    if extra:
        extra(ax)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=False, loc="upper left")
    ax.annotate(note, xy=(0, 0), xycoords="axes fraction", xytext=(0, -46), textcoords="offset points",
                fontsize=9, color=plots.INK, va="top")
    return fig


def plot_balance_check(rows, limit_pct, title):
    """V3: power balance error of every snapshot (log scale), with the limit."""
    fig, ax = plt.subplots(figsize=(7, 4))
    cases = sorted({r["case"] for r in rows})
    for k, case in enumerate(cases):
        values = [max(r["balance_pct"], 1e-12) for r in rows if r["case"] == case]
        ax.scatter(np.full(len(values), k) + np.linspace(-0.15, 0.15, len(values)), values, s=40,
                   color=plots.CASE_COLOURS[(k + 1) % len(plots.CASE_COLOURS)], edgecolor="white", zorder=3)
    ax.axhline(limit_pct, color=plots.LIMIT, ls="--", lw=1)
    ax.text(len(cases) - 0.5, limit_pct, f" limit {limit_pct:g} %", va="bottom", ha="right", color=plots.LIMIT, fontsize=9)
    ax.set_yscale("log")
    ax.set_xticks(range(len(cases)), [c.replace("_", " ") for c in cases])
    ax.set_ylabel("|source + PV - load - losses|\n(% of the power put into the network)")
    ax.set_title(title, fontsize=11)
    return fig


def plot_inverter_check(point_sets, control, tolerance_pu, title, ylabel):
    """V5: inverter operating points ({label: points table}) against the curve, with the tolerance band."""
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    every = np.concatenate([p["v_pu"].values for p in point_sets.values()])
    v = np.linspace(min(every.min(), 0.9) - 0.01, max(every.max(), 1.12) + 0.01, 300)
    curve = np.interp(v, control.voltage_pu, control.output_pu)
    ax.fill_between(v, curve - tolerance_pu, curve + tolerance_pu, color="#9a9893", alpha=0.25, lw=0,
                    label=f"curve +/- {tolerance_pu:g} pu")
    ax.plot(v, curve, color=plots.INK, lw=1.5, label="curve (settings)")
    for k, (label, points) in enumerate(point_sets.items()):
        ax.scatter(points["v_pu"], points["output_pu"], s=14 if k == 0 else 10, marker="o" if k == 0 else "x",
                   color=["#2a78d6", "#eb6834"][k % 2], alpha=0.6, zorder=3 + k, label=label)
    ax.set_xlabel("PV terminal voltage (pu)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=False, fontsize=8)
    return fig


def plot_convergence(table, column, ylabel, tolerance, title, min_runs=None):
    """V7: running mean and 95 % confidence band of one metric as runs are added."""
    mean, half = running_mean_ci(table[column].astype(float))
    n = np.arange(1, len(mean) + 1)
    fig, ax = plt.subplots(figsize=(7, 4))
    low, high = mean - half, mean + half
    if (table[column] >= 0).all():                       # a share or count cannot go below 0
        low = np.maximum(low, 0)
    ax.fill_between(n, low, high, color="#2a78d6", alpha=0.2, lw=0, label="95 % confidence band")
    ax.plot(n, mean, color="#2a78d6", lw=2, label="running mean")
    ax.axhspan(mean[-1] - tolerance, mean[-1] + tolerance, color="#9a9893", alpha=0.15, lw=0,
               label=f"final mean +/- {tolerance:g}")
    if min_runs:
        ax.axvline(min_runs, color=plots.INK, ls=":", lw=1)
    ax.set_xlabel("Monte Carlo runs")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    return fig


def plot_repeat_check(first, second, column, ylabel, title):
    """V8: the same runs, first and repeated (identical seeds), side by side."""
    fig, ax = plt.subplots(figsize=(7, 4))
    n = min(len(first), len(second))
    ax.plot(range(n), first[column].iloc[:n], "o", ms=9, color="#2a78d6", mfc="none", mew=2, label="first run")
    ax.plot(range(n), second[column].iloc[:n], "x", ms=7, color="#eb6834", mew=2, label="repeated (same seeds)")
    ax.set_xlabel("Monte Carlo run")
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=False)
    return fig


def plot_parity(groups, xlabel, ylabel, title, band=None, colours=None, markers=None, equal=True):
    """Parity plot: {label: (expected / reference values, tool values)} with the 1:1 line and an
    optional relative band (e.g. 0.01 = +/- 1 %)."""
    fig, ax = plt.subplots(figsize=(5.8, 5.8))
    every = np.concatenate([np.concatenate([np.asarray(a, float), np.asarray(b, float)]) for a, b in groups.values()])
    lo, hi = np.nanmin(every), np.nanmax(every)
    pad = 0.04 * (hi - lo or 1)
    line = np.array([lo - pad, hi + pad])
    if band:
        ax.fill_between(line, line * (1 - band), line * (1 + band), color="#9a9893", alpha=0.2, lw=0,
                        label=f"+/- {100 * band:g} %")
    ax.plot(line, line, color=plots.INK, lw=1, label="tool = expected")
    for k, (label, (x, y)) in enumerate(groups.items()):
        colour = (colours or {}).get(label, plots.CASE_COLOURS[(k + 1) % len(plots.CASE_COLOURS)])
        ax.scatter(x, y, s=22, color=colour, marker=(markers or {}).get(label, "o"), alpha=0.75, edgecolor="white",
                   linewidth=0.5, zorder=3, label=label)
    ax.set_xlim(*line)
    ax.set_ylim(*line)
    if equal:
        ax.set_aspect("equal")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    return fig


def plot_error_dots(rows, title):
    """Validation dot plot: normalized error [%] of every metric, one marker per case, with each
    metric's tolerance band."""
    metrics = list(dict.fromkeys(r["metric"] for r in rows))
    cases = list(dict.fromkeys(r["case"] for r in rows))
    fig, ax = plt.subplots(figsize=(8, 0.32 * len(metrics) + 1.6))
    for i, metric in enumerate(metrics):
        tol = next(r["tolerance_pct"] for r in rows if r["metric"] == metric)
        ax.add_patch(plt.Rectangle((-tol, i - 0.4), 2 * tol, 0.8, color="#9a9893", alpha=0.18, lw=0))
    for k, case in enumerate(cases):
        mine = [r for r in rows if r["case"] == case]
        y = [metrics.index(r["metric"]) + (k - (len(cases) - 1) / 2) * 0.22 for r in mine]
        ax.scatter([r["error_pct"] for r in mine], y, s=36, marker=CASE_MARKERS.get(k, "o"),
                   color=plots.CASE_COLOURS[(k + 1) % len(plots.CASE_COLOURS)], edgecolor="white", zorder=3,
                   label=case.replace("_", " "))
    ax.axvline(0, color=plots.INK, lw=1)
    ax.set_yticks(range(len(metrics)), metrics, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Normalized error, (tool - reference) / reference (%)\nshaded: tolerance of each metric")
    ax.set_title(title, fontsize=11)
    ax.grid(axis="y", alpha=0)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    return fig


# --- GIS overlay ----------------------------------------------------------------------------------
GIS_PACKAGES = "pip install pyproj contextily"


def projected_segments(engine, source_crs, target_crs="EPSG:3857"):
    """Line segments [(x1, y1, x2, y2, phases)] and transformer points of the circuit, its bus
    coordinates converted from source_crs (e.g. "EPSG:27700", British National Grid) to target_crs
    (web maps use EPSG:3857). Needs pyproj."""
    from pyproj import Transformer
    to_map = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    segments = []
    for b1, b2, n_ph, _ in net.line_segments(engine):
        p1, p2 = net.bus_xy(engine, b1), net.bus_xy(engine, b2)
        if p1 and p2 and any(p1) and any(p2):
            (x1, x2), (y1, y2) = to_map.transform([p1[0], p2[0]], [p1[1], p2[1]])
            segments.append((x1, y1, x2, y2, n_ph))
    transformers = []
    for b1, b2 in net.transformer_segments(engine):
        p = net.bus_xy(engine, b2) or net.bus_xy(engine, b1)
        if p and any(p):
            transformers.append(to_map.transform(p[0], p[1]))
    return segments, transformers


def plot_gis_overlay(engine, source_crs, title, basemap=True, provider=None, zoom="auto", loads=True):
    """The network on a web map. Returns (figure, note). The map tiles are downloaded by contextily
    (an HTTPS request per tile: only the tile numbers of the area shown are sent; nothing about the
    network). basemap=False, no internet or a missing package: drawn without the map, and the
    note says why. provider: a contextily / xyzservices provider (default OpenStreetMap)."""
    try:
        segments, transformers = projected_segments(engine, source_crs)
    except ImportError:
        return None, f"GIS overlay skipped: pyproj is not installed ({GIS_PACKAGES})"
    if not segments:
        return None, "GIS overlay skipped: the circuit has no bus coordinates"
    fig, ax = plt.subplots(figsize=(8, 8))
    for x1, y1, x2, y2, n_ph in segments:
        ax.plot([x1, x2], [y1, y2], color="#e34948" if n_ph == 3 else "#2a78d6", lw=2.2 if n_ph == 3 else 1.0, zorder=3)
    if loads:
        from pyproj import Transformer
        to_map = Transformer.from_crs(source_crs, "EPSG:3857", always_xy=True)
        points = [net.bus_xy(engine, net.bus_name(i["bus"])) for i in net.load_inventory(engine).values()]
        points = [to_map.transform(*p) for p in points if p and any(p)]
        if points:
            ax.scatter(*zip(*points), s=10, color="#1baf7a", zorder=4, label="customers")
    if transformers:
        ax.scatter(*zip(*transformers), s=120, marker="s", color="#6250d6", edgecolor="white", zorder=5,
                   label="transformer")
    phases = {n_ph for *_, n_ph in segments}
    if 3 in phases:
        ax.plot([], [], color="#e34948", lw=2.2, label="three-phase line")
    if phases - {3}:
        ax.plot([], [], color="#2a78d6", lw=1.0, label="one- or two-phase line")
    ax.set_aspect("equal")
    note = "basemap off (BASEMAP = False)"
    if basemap:
        try:
            import contextily as ctx
            ctx.add_basemap(ax, crs="EPSG:3857", source=provider or ctx.providers.OpenStreetMap.Mapnik, zoom=zoom,
                            attribution_size=7)
            note = "basemap: map tiles downloaded by contextily"
        except ImportError:
            note = f"basemap skipped: contextily is not installed ({GIS_PACKAGES})"
        except Exception as error:
            note = f"basemap skipped: map tiles could not be downloaded ({type(error).__name__})"
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    ax.set_title(title, fontsize=11)
    ax.legend(frameon=True, fontsize=8, loc="upper right")
    if not note.startswith("basemap: "):
        ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, color=plots.INK)
    return fig, note


def lon_lat_extent(engine, source_crs):
    """(west, south, east, north) of the circuit in degrees, to check where the coordinates land."""
    from pyproj import Transformer
    to_degrees = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    xy = [net.bus_xy(engine, b) for b in net.bus_names(engine)]
    xy = [p for p in xy if p and any(p)]
    lon, lat = to_degrees.transform([p[0] for p in xy], [p[1] for p in xy])
    return min(lon), min(lat), max(lon), max(lat)
