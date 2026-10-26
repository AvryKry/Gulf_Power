"""Building OpenDSS commands for DER (PV systems) and load shapes.

These bricks only build text commands; they do not touch OpenDSS. Send the result to
engine.run_commands() or engine.build_circuit(..., extra_commands=...).
"""
import math


def single_phase_kv(kv_line_to_line):
    """Line-to-neutral kV of a single-phase element on a system with this line-to-line kV."""
    return kv_line_to_line / math.sqrt(3)


def pv_command(name, bus, phases, kv, kva, pmpp=None, pf=1.0, irradiance=1.0, daily_shape=None,
               cutin_pct=0.05, cutout_pct=0.05, vmin_pu=0.5, vmax_pu=1.5, extra=""):
    """'new PVSystem...' command. kv is line-to-line for 3-phase PV, line-to-neutral for 1-phase.
    pmpp defaults to kva. 'daily_shape' is the name of a load shape used in daily mode.
    cutin_pct / cutout_pct: output (% of kVA) at which the inverter turns on / off. OpenDSS's default
    is 20 %, which switches PV off on cloudy days and at dawn and dusk; 0.05 % follows Team Nando.
    vmin_pu / vmax_pu: voltage range in which the PV keeps its constant-power model (OpenDSS's
    default 0.90-1.10 changes the model at exactly the over-voltages a hosting study looks for)."""
    pmpp = kva if pmpp is None else pmpp
    command = (f"new PVSystem.{name} bus1={bus} phases={phases} kV={kv:.6g} kVA={kva:.6g} Pmpp={pmpp:.6g} "
               f"pf={pf} irradiance={irradiance} %cutin={cutin_pct} %cutout={cutout_pct} "
               f"vminpu={vmin_pu} vmaxpu={vmax_pu} model=1")
    if daily_shape:
        command += f" daily={daily_shape}"
    return f"{command} {extra}".strip()


def pv_commands(sites, scale=1.0):
    """Commands for a list of PV sites: dicts with keys name, bus, phases, kv, kva (+ any optional
    argument of pv_command). 'scale' multiplies kva (and pmpp) of every site."""
    commands = []
    for site in sites:
        s = dict(site)
        s["kva"] = s["kva"] * scale
        if s.get("pmpp") is not None:
            s["pmpp"] = s["pmpp"] * scale
        commands.append(pv_command(**s))
    return commands


def loadshape_command(name, p_values, q_values=None, interval_minutes=30, use_actual=True):
    """'new LoadShape...' command for a daily shape. With use_actual=True the values are kW/kvar;
    otherwise they multiply the rated kW of the element."""
    to_text = lambda values: "(" + " ".join(f"{v:.5g}" for v in values) + ")"
    command = (f"new LoadShape.{name} npts={len(p_values)} minterval={interval_minutes} "
               f"useactual={'yes' if use_actual else 'no'} mult={to_text(p_values)}")
    if q_values is not None:
        command += f" qmult={to_text(q_values)}"
    return command


def assign_daily_shape_command(element, shape_name):
    """'edit <element> daily=<shape>' command, e.g. element='Load.Load_MG1_1'"""
    return f"edit {element} daily={shape_name}"
