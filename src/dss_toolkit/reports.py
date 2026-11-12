"""Printing results as tables in the terminal.

print_table() is the only brick that formats text; every other report brick prepares rows and
passes them to it. compare_* bricks print two cases side by side.
"""
import math

from . import extract


# --- Generic table ---------------------------------------------------------------------------
def fmt(value, spec):
    """Format a number with 'spec' (e.g. '.2f'); text is returned as it is and None / NaN as '-'.
    A whole-number spec ('d') also accepts floats (pandas stores integer columns with gaps as float)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    if isinstance(value, str):
        return value
    if spec.endswith("d"):
        return format(int(round(value)), spec)
    return format(round(value, 6) + 0.0 if isinstance(value, float) else value, spec)


def print_table(headers, rows, title=None, align=None):
    """Print rows (lists of text) under headers, with column widths fitted to the content.
    'align' is a string of '<' / '>' per column (default: first column left, others right)."""
    align = align or "<" + ">" * (len(headers) - 1)
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = "-" * (sum(widths) + 3 * len(widths) + 1)
    row_text = lambda r: "| " + " | ".join(f"{str(x):{a}{w}}" for x, a, w in zip(r, align, widths)) + " |"
    if title:
        print(f"\n{title}")
    print(line)
    print(row_text(headers))
    print(line)
    for r in rows:
        print(row_text(r))
    print(line)


def print_summary_table(table, columns, title=None):
    """Print chosen columns of a results DataFrame. columns = [(header, column, format spec)],
    e.g. [("PV %", "penetration_pct", "d"), ("V max (pu)", "v_max_pu", ".4f")]."""
    rows = [[fmt(r[key], spec) for _, key, spec in columns] for r in table.to_dict("records")]
    print_table([header for header, _, _ in columns], rows, title)


# --- Single case -----------------------------------------------------------------------------
def print_element_counts(counts):
    print_table(["Element", "Count"], [[k, v] for k, v in counts.items()], "Elements in the circuit:")


def print_load_inventory(inventory):
    rows = [[n, i["bus"], i["conn"], fmt(i["kV"], ".3f"), fmt(i["kW"], ".1f"), fmt(i["kvar"], ".1f"), i["model"]]
            for n, i in inventory.items()]
    print_table(["Load", "Bus", "Conn", "kV", "kW", "kvar", "Model"], rows, "Loads in the network (rated values):",
                align="<<<>>><")
    print(f"Total rated demand = {sum(i['kW'] for i in inventory.values()):.0f} kW and "
          f"{sum(i['kvar'] for i in inventory.values()):.0f} kvar")


def limit_flag(v, limits):
    return "<" if v < limits[0] else (">" if v > limits[1] else "")


def print_loads(results, limits):
    rows = [[n, bus, fmt(p, ".2f"), fmt(q, ".2f"), fmt(v, ".4f"), limit_flag(v, limits)]
            for n, (bus, p, q, v) in results["loads"].items()]
    print_table(["Load", "Bus", "P (kW)", "Q (kvar)", "V min (pu)", ""], rows,
                f"Loads: power and lowest voltage ('<' below {limits[0]} pu, '>' above {limits[1]} pu):", "<<>>><")


def print_bus_voltages(bus_results):
    """bus_results: {bus: (phases, VUF)} as returned by extract.three_phase_bus_results()."""
    rows = []
    for bus, (phases, vuf) in bus_results.items():
        for i, (ph, pu, v, ang) in enumerate(phases):
            rows.append([bus if i == 0 else "", ph, fmt(pu, ".4f"), fmt(v, ".1f"), fmt(ang, ".2f"),
                         fmt(vuf, ".2f") if i == 0 else ""])
    print_table(["Bus", "Phase", "V (pu)", "V (V)", "Angle (deg)", "VUF (%)"], rows, "Bus voltages:")


def print_transformers(results):
    for name, (p, q, tap, kva) in results["xfmr"].items():
        rows = [[ph + 1, fmt(p[ph], ".2f"), fmt(q[ph], ".2f")] for ph in range(len(p))]
        rows.append(["Total", fmt(p.sum(), ".2f"), fmt(q.sum(), ".2f")])
        print_table(["Phase", "P (kW)", "Q (kvar)"], rows,
                    f"Transformer {name} ({kva:.0f} kVA), winding 2 tap = {tap:.5f} (+ = forward flow):")


def print_feeder_summary(results, limits):
    taps = ", ".join(f"{k} = {v}" for k, v in results["reg_taps"].items()) or "no regulators"
    rows = [["Substation P (kW)", fmt(results["P_source"], ".2f")], ["Substation Q (kvar)", fmt(results["Q_source"], ".2f")],
            ["PV P (kW)", fmt(results["P_pv"], ".2f")], ["Load P (kW)", fmt(results["P_load"], ".2f")],
            ["Total losses P (kW)", fmt(results["P_loss"], ".3f")], ["Line losses P (kW)", fmt(results["P_line_loss"], ".3f")],
            ["Losses (% of substation P)", fmt(100 * results["P_loss"] / results["P_source"], ".2f") if results["P_source"] else "-"],
            ["Min / max / mean V (pu)", f"{results['v_min']:.4f} / {results['v_max']:.4f} / {results['v_mean']:.4f}"],
            [f"Nodes below {limits[0]} / above {limits[1]} pu", f"{results['n_under']} / {results['n_over']}"],
            ["Regulator taps", taps], ["Power balance check (kW)", fmt(extract.power_balance(results), ".3f")]]
    print_table(["Result", "Value"], rows, "Feeder summary:")


def print_line_loading(results):
    rows = [[n, fmt(a, ".0f"), fmt(i, ".1f"), fmt(pct, ".1f")] for n, (i, a, pct) in results["lines"].items()]
    print_table(["Line", "Ampacity (A)", "Current (A)", "Loading (%)"], rows, "Line loading (highest conductor):")


def print_snapshot_report(results, limits):
    """Every single-case table: loads, bus voltages, transformers, line loading and summary."""
    print_loads(results, limits)
    print_bus_voltages(results["p3"])
    print_transformers(results)
    print_line_loading(results)
    print_feeder_summary(results, limits)


# --- Two cases side by side ------------------------------------------------------------------
SUMMARY_KEYS = [("Substation P (kW)", "P_source", ".1f"), ("Substation Q (kvar)", "Q_source", ".1f"),
                ("PV P (kW)", "P_pv", ".1f"), ("Load P (kW)", "P_load", ".1f"), ("Load Q (kvar)", "Q_load", ".1f"),
                ("Total losses P (kW)", "P_loss", ".2f"), ("Total losses Q (kvar)", "Q_loss", ".2f"),
                ("Line losses P (kW)", "P_line_loss", ".2f"), ("Min node V (pu)", "v_min", ".4f"),
                ("Max node V (pu)", "v_max", ".4f"), ("Mean node V (pu)", "v_mean", ".4f"),
                ("Nodes below limit", "n_under", "d"), ("Nodes above limit", "n_over", "d")]


def compare_summary(a, b, labels):
    rows = [[label, fmt(a[k], s), fmt(b[k], s), fmt(b[k] - a[k], s)] for label, k, s in SUMMARY_KEYS]
    for reg in a["reg_taps"]:
        rows.append([f"Tap {reg}", a["reg_taps"][reg], b["reg_taps"].get(reg, "-"), b["reg_taps"].get(reg, 0) - a["reg_taps"][reg]])
    rows.append(["Power balance check (kW)", fmt(extract.power_balance(a), ".3f"), fmt(extract.power_balance(b), ".3f"), ""])
    print_table(["Result", *labels, "Change"], rows, "Feeder summary:")
    if b["P_source"] < 0:
        print(f"*** Reverse power flow at the substation in '{labels[1]}' ***")


def compare_loads(a, b, labels, limits):
    rows = []
    for n, (bus, p1, q1, v1) in a["loads"].items():
        _, p2, q2, v2 = b["loads"][n]
        rows.append([n, bus, fmt(p1, ".1f"), fmt(p2, ".1f"), fmt(q1, ".1f"), fmt(q2, ".1f"),
                     fmt(v1, ".4f"), fmt(v2, ".4f"), limit_flag(v2, limits)])
    h = [f"{x} {lab}" for x in ("P", "Q", "V") for lab in labels]
    print_table(["Load", "Bus", *h, ""], rows, "Loads: P (kW), Q (kvar), lowest V (pu):", "<<>>>>>><")


def compare_bus_voltages(a, b, labels):
    rows = []
    for bus, (ph1, vuf1) in a["p3"].items():
        ph2, vuf2 = b["p3"][bus]
        for (ph, pu1, v1, _), (_, pu2, v2, _) in zip(ph1, ph2):
            rows.append([bus, ph, fmt(pu1, ".4f"), fmt(pu2, ".4f"), fmt(v1, ".1f"), fmt(v2, ".1f")])
        rows.append([bus, "VUF %", fmt(vuf1, ".2f"), fmt(vuf2, ".2f"), "", ""])
    h = [f"V {lab} (pu)" for lab in labels] + [f"V {lab} (V)" for lab in labels]
    print_table(["Bus", "Phase", *h], rows, "Three-phase bus voltages and VUF:")


def compare_transformers(a, b, labels):
    for name, (p1, q1, tap1, kva) in a["xfmr"].items():
        p2, q2, tap2, _ = b["xfmr"][name]
        rows = [[ph + 1, fmt(p1[ph], ".1f"), fmt(p2[ph], ".1f"), fmt(q1[ph], ".1f"), fmt(q2[ph], ".1f"),
                 fmt(100 * math.hypot(p2[ph], q2[ph]) / (kva / len(p2)), ".1f")] for ph in range(len(p1))]
        rows.append(["Total", fmt(p1.sum(), ".1f"), fmt(p2.sum(), ".1f"), fmt(q1.sum(), ".1f"), fmt(q2.sum(), ".1f"), ""])
        h = [f"P {lab}" for lab in labels] + [f"Q {lab}" for lab in labels] + [f"Loading {labels[1]} (%)"]
        print_table(["Phase", *h], rows, f"Transformer {name} ({kva:.0f} kVA), tap {tap1:.5f} -> {tap2:.5f}:")


def compare_line_loading(a, b, labels):
    rows = [[n, fmt(amp, ".0f"), fmt(i1, ".1f"), fmt(b["lines"][n][0], ".1f"), fmt(p1, ".1f"), fmt(b["lines"][n][2], ".1f")]
            for n, (i1, amp, p1) in a["lines"].items()]
    h = [f"I {lab} (A)" for lab in labels] + [f"Loading {lab} (%)" for lab in labels]
    print_table(["Line", "Ampacity (A)", *h], rows, "Line loading:")


def print_comparison(a, b, labels, limits):
    """Every comparison table for two cases (e.g. before and after PV)."""
    compare_summary(a, b, labels)
    compare_loads(a, b, labels, limits)
    compare_bus_voltages(a, b, labels)
    compare_transformers(a, b, labels)
    compare_line_loading(a, b, labels)


def show_structure(obj, name="results", indent=0, max_items=2):
    """Print the keys, types and an example of each value of a (nested) results dictionary."""
    import numpy as np
    pad = "    " * indent
    is_num = lambda x: isinstance(x, (int, float, np.number))
    if isinstance(obj, dict):
        print(f"{pad}{name}: dict with {len(obj)} keys")
        for i, (k, v) in enumerate(obj.items()):
            if indent > 0 and i >= max_items:
                print(f"{pad}    ... ({len(obj) - max_items} more keys of the same form)")
                break
            show_structure(v, repr(k), indent + 1, max_items)
    elif isinstance(obj, np.ndarray):
        print(f"{pad}{name}: numpy array, shape {obj.shape}")
    elif isinstance(obj, (list, tuple)) and obj and all(is_num(x) for x in obj):
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} numbers")
    elif isinstance(obj, (list, tuple)) and obj and all(isinstance(x, str) for x in obj):
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} strings, e.g. {list(obj[:3])}")
    elif isinstance(obj, tuple) and len(obj) <= 6:
        print(f"{pad}{name}: tuple of {len(obj)}")
        for i, v in enumerate(obj):
            show_structure(v, f"[{i}]", indent + 1, max_items)
    elif isinstance(obj, (list, tuple)) and obj:
        print(f"{pad}{name}: {type(obj).__name__} of {len(obj)} items, the first one is:")
        show_structure(obj[0], "[0]", indent + 1, max_items)
    else:
        print(f"{pad}{name}: {type(obj).__name__} = {obj!r}")


# --- Network checks (safe to share) ---------------------------------------------------------------
class Anonymiser:
    """Replaces names with stable codes ('bus_0001', 'load_0042' ...) so printed output can be shared
    without revealing confidential network data. The same name always gets the same code within
    one run. enabled=False returns names unchanged."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._codes = {}

    def __call__(self, name, kind="name"):
        if not self.enabled or name is None:
            return name
        key = (kind, str(name).lower())
        if key not in self._codes:
            self._codes[key] = f"{kind}_{sum(1 for k in self._codes if k[0] == kind) + 1:04d}"
        return self._codes[key]

    def text(self, message, replacements=()):
        """Message with every known name (and each path in 'replacements') replaced."""
        if not self.enabled:
            return message
        out = str(message)
        for path in replacements:
            out = out.replace(str(path), "<data folder>")
        for (kind, name), code in sorted(self._codes.items(), key=lambda kv: -len(kv[0][1])):
            out = out.replace(name, code)
        return out


def check_line(status, label, detail=""):
    """One check: PASS / WARN / FAIL, a label and details."""
    print(f"  [{status:4s}] {label}{(': ' + detail) if detail else ''}")


def print_network_checks(info, coords_share, anonymise=None):
    """Summary of a topology.NetworkInfo with PASS / WARN / FAIL lines, using only counts and
    anonymised names, so it can be shared. coords_share = share of buses with coordinates (0-1)."""
    anon = anonymise or Anonymiser(False)
    from collections import Counter
    kinds = Counter(a.kind for a in info.assets)
    phases = Counter(info.load_phases.values())
    levels = sorted({round(v, 3) for v in info.bus_kv_ll.values() if v > 0}, reverse=True)
    no_base = sum(1 for v in info.bus_kv_ll.values() if v == 0)
    print(f"\nNetwork '{anon(info.circuit_name, 'circuit')}'")
    check_line("PASS", "source bus", anon(info.source_bus, "bus"))
    check_line("PASS" if info.buses else "FAIL", "buses", f"{len(info.buses)}")
    check_line("PASS" if levels else "FAIL", "voltage levels (kV line-to-line)", ", ".join(f"{v:g}" for v in levels) or "none")
    check_line("PASS" if no_base == 0 else "WARN", "buses without a voltage base", f"{no_base}"
               + (" (set VOLTAGE_BASES_KV, or SetkVBase in the data)" if no_base else ""))
    check_line("PASS" if info.base_case_solved else "WARN", "test power flow (no PV, loads as in the files)",
               "converged" if info.base_case_solved else "did NOT converge - check sources, voltage bases, isolated parts")
    check_line("PASS" if not info.islands else "WARN", "parts not connected to the source",
               f"{len(info.islands)}" + (f" ({sum(len(i) for i in info.islands)} buses)" if info.islands else ""))
    check_line("PASS" if kinds.get("head_transformer") else "WARN", "head (substation) transformers", f"{kinds.get('head_transformer', 0)}")
    check_line("PASS", "other transformers", f"{kinds.get('transformer', 0)}")
    check_line("PASS", "rated lines (MV / LV)", f"{kinds.get('mv_line', 0)} / {kinds.get('lv_line', 0)}")
    unrated = sum(1 for e, *_ in info.branches if e.startswith("line.")) - kinds.get("mv_line", 0) - kinds.get("lv_line", 0)
    check_line("PASS" if unrated <= 0 else "WARN", "lines without a rating in the data (not checked)", f"{max(unrated, 0)}")
    check_line("PASS" if info.loads else "FAIL", "loads", f"{len(info.loads)} (" + ", ".join(f"{k}: {v}" for k, v in sorted(phases.items())) + ")")
    check_line("PASS", "loads with a fixed shape", f"{len(info.fixed_loads)}")
    check_line("PASS", "single-phase customers whose phase can be randomized", f"{len(info.tap_points)}")
    check_line("PASS" if coords_share >= 0.999 else ("WARN" if coords_share > 0 else "PASS"), "buses with coordinates in the data",
               f"{100 * coords_share:.1f} %" + ("" if coords_share >= 0.999 else " (the rest are placed automatically)"))
