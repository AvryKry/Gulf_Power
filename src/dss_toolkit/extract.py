"""Extracting results from a solved circuit.

Each brick extracts one kind of result and returns plain Python / numpy values.
collect_results() is the larger brick that combines them into one dictionary (same structure
as in Tutorial 1B, plus "reg_taps" with every regulator).
"""
import numpy as np

from . import network as net


def element_powers(engine, element, terminal=0):
    """(P per conductor [kW], Q per conductor [kvar]) at one terminal of an element, using the
    OpenDSS sign convention (positive = power flowing INTO the element at that terminal)."""
    engine.ActiveCircuit.SetActiveElement(element)
    el = engine.ActiveCircuit.ActiveElement
    n = el.NumConductors
    powers = np.array(el.Powers)[2 * n * terminal: 2 * n * (terminal + 1)]
    return powers[0::2], powers[1::2]


def node_voltages(engine):
    """{node name: voltage [pu]} for every node, e.g. {'671.1': 0.891, ...}"""
    c = engine.ActiveCircuit
    return dict(zip(c.AllNodeNames, c.AllBusVmagPu))


def voltage_statistics(vnode, limits, exclude=()):
    """Min / max / mean voltage, where they occur, and how many nodes are outside 'limits' (pu)."""
    names = [n for n in vnode if not net.is_excluded(n, exclude)]
    v = np.array([vnode[n] for n in names])
    return {"v_min": v.min(), "v_max": v.max(), "v_mean": v.mean(),
            "v_min_node": names[v.argmin()], "v_max_node": names[v.argmax()], "n_nodes": len(v),
            "n_under": int((v < limits[0]).sum()), "n_over": int((v > limits[1]).sum())}


def load_results(engine, vnode):
    """{load: (bus.nodes, P [kW], Q [kvar], lowest voltage of its phases [pu])}"""
    out = {}
    for load in net.element_names(engine.ActiveCircuit.Loads):
        bus = net.element_bus(engine, f"Load.{load}")
        p, q = element_powers(engine, f"Load.{load}")
        v = min(vnode[f"{net.bus_name(bus)}.{ph}"] for ph in net.bus_phases(bus))
        out[load] = (bus, p.sum(), q.sum(), v)
    return out


def pv_results(engine):
    """{PV system: (bus.nodes, P out [kW], Q out [kvar])}  (positive = generation)"""
    out = {}
    for pv in net.element_names(engine.ActiveCircuit.PVSystems):
        p, q = element_powers(engine, f"PVSystem.{pv}")
        out[pv] = (net.element_bus(engine, f"PVSystem.{pv}"), -p.sum(), -q.sum())
    return out


def bus_voltages(engine, bus):
    """([(phase, V [pu], V [V], angle [deg]) per phase], VUF [%] or None if not three-phase)"""
    engine.ActiveCircuit.SetActiveBus(bus)
    b = engine.ActiveCircuit.ActiveBus
    phases = [(int(ph), b.puVmagAngle[2 * i], b.VMagAngle[2 * i], round(b.VMagAngle[2 * i + 1], 2) + 0.0)
              for i, ph in enumerate(b.Nodes)]
    seq = b.SeqVoltages
    vuf = 100 * seq[2] / seq[1] if len(phases) == 3 and seq[1] > 0 else None
    return phases, vuf


def three_phase_bus_results(engine, exclude=()):
    """{bus: (phases, VUF)} for every three-phase bus."""
    return {bus: bus_voltages(engine, bus) for bus in net.three_phase_buses(engine, exclude)}


def transformer_results(engine):
    """{transformer: (P per phase [kW], Q per phase [kvar], winding 2 tap, rating [kVA])} out of
    winding 2 (positive = forward flow to the loads, negative = reverse flow)."""
    out = {}
    tr = engine.ActiveCircuit.Transformers
    for name in net.element_names(tr):
        p, q = element_powers(engine, f"Transformer.{name}", terminal=1)
        n_ph = engine.ActiveCircuit.ActiveElement.NumPhases
        tr.Name, tr.Wdg = name, 2
        out[name] = (-p[:n_ph], -q[:n_ph], tr.Tap, tr.kVA)
    return out


def line_loading(engine, exclude=()):
    """{line: (highest conductor current [A], ampacity [A], loading [%])}; switches are skipped."""
    out = {}
    lines = engine.ActiveCircuit.Lines
    for name in net.element_names(lines):
        lines.Name = name
        if lines.IsSwitch or net.is_excluded(net.bus_name(lines.Bus2), exclude):
            continue
        engine.ActiveCircuit.SetActiveElement(f"Line.{name}")
        el = engine.ActiveCircuit.ActiveElement
        i_max = max(el.CurrentsMagAng[0:2 * el.NumConductors:2])
        out[name] = (i_max, lines.NormAmps, 100 * i_max / lines.NormAmps)
    return out


def feeder_totals(engine):
    """Substation power and losses: P_source, Q_source [kW, kvar], P/Q_loss (lines + transformers),
    P/Q_line_loss (lines only)."""
    c = engine.ActiveCircuit
    return {"P_source": -c.TotalPower[0], "Q_source": -c.TotalPower[1],
            "P_loss": c.Losses[0] / 1000, "Q_loss": c.Losses[1] / 1000,
            "P_line_loss": c.LineLosses[0], "Q_line_loss": c.LineLosses[1]}


def regulator_taps(engine):
    """{regulator control: tap position (-16 to +16)}; disabled controls are not included."""
    rc = engine.ActiveCircuit.RegControls
    taps = {}
    for name in net.element_names(rc):
        rc.Name = name
        taps[name] = rc.TapNumber
    return taps


def voltage_profile(engine):
    """{phase: (distance from the EnergyMeter [km], V [pu], node names)}; needs an EnergyMeter."""
    c = engine.ActiveCircuit
    return {ph: (np.array(c.AllNodeDistancesByPhase(ph)), np.array(c.AllNodeVmagPUByPhase(ph)),
                 list(c.AllNodeNamesByPhase(ph))) for ph in (1, 2, 3)}


def collect_results(engine, limits, exclude=()):
    """Every snapshot result of the solved circuit in one dictionary."""
    r = {"vnode": node_voltages(engine)}
    stats = voltage_statistics(r["vnode"], limits, exclude)
    r.update({k: stats[k] for k in ("v_min", "v_max", "v_mean", "n_under", "n_over")})
    r["loads"] = load_results(engine, r["vnode"])
    r["pv"] = pv_results(engine)
    r["p3"] = three_phase_bus_results(engine, exclude)
    r["xfmr"] = transformer_results(engine)
    r.update(feeder_totals(engine))
    r["P_load"] = sum(x[1] for x in r["loads"].values())
    r["Q_load"] = sum(x[2] for x in r["loads"].values())
    r["P_pv"] = sum(x[1] for x in r["pv"].values())
    r["reg_taps"] = regulator_taps(engine)
    r["reg_tap"] = next(iter(r["reg_taps"].values()), None)
    r["lines"] = line_loading(engine, exclude)
    r["profile"] = voltage_profile(engine)
    return r


def power_balance(results):
    """Substation + PV - load - losses [kW]; close to 0 when the results are consistent."""
    return results["P_source"] + results["P_pv"] - results["P_load"] - results["P_loss"]
