"""Interactive (zoomable) network maps saved as a single HTML file.

The page has the map and, beside it, a panel (part of the page, not of the plot, so it is always
shown, whatever the window size or tab layout; on narrow windows it moves above the map):
  - Mode: what the map shows. "Names and phases" (elements by type, loads and PV by phase),
    lenses that colour elements by how far they are from normal - voltage (buses), current
    (lines), power (transformers), power factor and losses (lines and transformers) - and
    "Devices" (capacitors, fuses, reclosers, switches, regulators, sources). Lenses need power
    flow results (network_figure(..., results=...)). "Sources lens (areas)" colours every bus,
    line and transformer by the source that feeds it (its nearest source), with one tick box per
    source, plus the ties between sources' areas and parts no source reaches; it needs no results.
  - Two checklists: element types and value bands (each with its colour and how many elements
    are in it). An element is shown when both its type and its band are ticked. In the source
    lens the bands are the sources: unticking one hides the area it feeds and its triangle.
  - Show names: writes every shown element's name on the map (best zoomed in). Hovering always
    shows the name and values.
Switching mode keeps the zoom and position, so a problem area found with a lens can be zoomed
into and then identified in "Names and phases".

Markers keep their size on screen while zooming. The file is fully offline (the Plotly library
is written into it): opening it never contacts the internet, so confidential network data stays
on the computer. Needs the 'plotly' package (pip install plotly).
"""
import html
import json
import math
from pathlib import Path

PHASE_COLOURS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
MULTI_PHASE_COLOUR = "#6250d6"
LINE_COLOURS = {"mv": "#3d3d3a", "lv": "#9a9893"}
OUTLINE = "#d3d1c7"
GREAT_DEVIATION = (0.10, 1.10)      # fraction of nominal: the far ends of every lens start here
NEAR_LIMIT_PU = 0.02                # voltage band just inside each limit

MODES = {"names": "Names and phases", "sources": "Sources lens (areas)", "voltage": "Voltage lens (buses)", "current": "Current lens (lines)",
         "power": "Power lens (transformers)", "pf": "Power factor lens", "losses": "Losses lens", "devices": "Devices"}

# value bands: (label, low, high, colour); a value v is in a band when low <= v < high
LOADING_BANDS = [("0 % (no current)", 0, 1e-9, "#2c2c2a"), ("below 1 %", 1e-9, 1, "#3c3489"),
                 ("1-10 %", 1, 10, "#7f77dd"), ("10-50 %", 10, 50, "#85b7eb"), ("50-80 %", 50, 80, "#1d9e75"),
                 ("80-100 %", 80, 100, "#ef9f27"), ("100-110 %", 100, 110, "#d85a30"), ("110-150 %", 110, 150, "#e24b4a"),
                 ("150-300 %", 150, 300, "#a32d2d"), ("above 300 %", 300, math.inf, "#501313")]
PF_BANDS = [("pf 0.95 or more", 0.95, 1.01, "#1d9e75"), ("pf 0.90-0.95", 0.90, 0.95, "#ef9f27"),
            ("pf 0.80-0.90", 0.80, 0.90, "#d85a30"), ("pf below 0.80", 0, 0.80, "#a32d2d")]
LOSS_BANDS = [("losses below 1 %", 0, 1, "#1d9e75"), ("1-3 %", 1, 3, "#85b7eb"), ("3-5 %", 3, 5, "#ef9f27"),
              ("5-10 %", 5, 10, "#d85a30"), ("above 10 %", 10, math.inf, "#a32d2d")]
SOURCE_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#c9a100", "#0f9fb5", "#a64d79", "#7a8c1e", "#8c564b",
                  "#5f6b7a"]            # one per source, in the order of info.sources; used again beyond 10 sources
TIES = ("Ties between sources", "#d4537e")   # lines / transformers joining the areas of two sources
NOT_FED = ("not fed by any source", "#b4b2a9")
NO_RATING, NO_FLOW, REVERSE = ("no rating in the data", "#b4b2a9"), ("no flow (below 1 kVA)", "#b4b2a9"), ("reverse flow", "#d4537e")
# Sources lens: one colour per source, in the order of info.sources (repeats after ten)
SOURCE_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#8e44ad", "#d4a017", "#0f8b8d", "#c0392b", "#8d5524", "#6b8e23", "#1f2f6b"]
SOURCE_TIES = ("Ties between sources", "#d4537e")
NOT_REACHED = ("Not reached by any source", "#b4b2a9")
LENS_MODES = ["sources", "voltage", "current", "power", "pf", "losses"]
DEVICE_STYLE = {"capacitor": ("Capacitors", "#185fa5", "square-open", 13), "fuse": ("Fuses", "#a32d2d", "x", 11),
                "recloser": ("Reclosers", "#d85a30", "diamond", 12), "switch": ("Switches", "#3b6d11", "square", 10),
                "regulator": ("Regulators", "#534ab7", "hexagon", 13)}
# sources lens: one colour per source (repeating past 10, then with another marker shape)
SOURCE_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#c9a100", "#17a2b8", "#a32d2d", "#7a5c3e",
                  "#8c9d1e", "#5f6b7a"]
SOURCE_SYMBOLS = ["triangle-up", "triangle-down", "diamond", "pentagon", "hexagon", "star-triangle-up"]
SOURCE_OUTLINE = "network outline (stays when an area is hidden)"
TIE, ISLAND = ("ties between sources", "#d4537e"), ("no source (island)", "#2c2c2a")


def voltage_bands(limits):
    """Voltage bands (pu) from the limits: the far ends start at GREAT_DEVIATION (below 10 % and
    above 110 % of nominal), then step inward to the limits and a NEAR_LIMIT_PU margin inside
    them, and outward in wider steps."""
    lo, hi = limits
    return [("0 pu (not energized)", -1, 1e-9, "#2c2c2a"), ("below 0.10 pu", 1e-9, GREAT_DEVIATION[0], "#26215c"),
            (f"0.10-0.80 pu", GREAT_DEVIATION[0], 0.80, "#3c3489"), ("0.80-0.90 pu", 0.80, 0.90, "#534ab7"),
            (f"0.90-{lo:g} pu", 0.90, lo, "#185fa5"), (f"{lo:g}-{lo + NEAR_LIMIT_PU:g} pu (near limit)", lo, lo + NEAR_LIMIT_PU, "#85b7eb"),
            ("normal", lo + NEAR_LIMIT_PU, hi - NEAR_LIMIT_PU, "#97c459"),
            (f"{hi - NEAR_LIMIT_PU:g}-{hi:g} pu (near limit)", hi - NEAR_LIMIT_PU, hi, "#ef9f27"),
            (f"{hi:g}-1.15 pu", hi, max(hi, 1.15), "#e24b4a"), ("1.15-1.20 pu", max(hi, 1.15), 1.20, "#a32d2d"),
            ("above 1.20 pu", 1.20, math.inf, "#501313")]


def band_of(value, bands):
    """(label, colour) of the band 'value' is in, or None."""
    for label, low, high, colour in bands:
        if low <= value < high:
            return label, colour
    return None


# --- Traces ------------------------------------------------------------------------------------
CONTEXT = "outline and sources (no value)"
BAND_TITLES = {"names": "Phases", "sources": "Sources (area each one feeds)", "voltage": "Voltage bands", "current": "Loading bands (% of rated current)",
               "power": "Loading bands (% of kVA rating)", "pf": "Power factor bands", "losses": "Loss bands (% of power carried)",
               "sources": "Sources (tick to show)", "devices": "Bands"}


def _meta(modes, group, band=CONTEXT, colour=OUTLINE, on=True, n=0, rank=0):
    return {"modes": [modes] if isinstance(modes, str) else list(modes), "group": group, "band": band, "colour": colour,
            "on": on, "n": n, "rank": rank}


def _segments(go, pairs, coords, colour, width, meta, dash=None):
    xs, ys = [], []
    for a, b in pairs:
        if a in coords and b in coords:
            xs += [coords[a][0], coords[b][0], None]
            ys += [coords[a][1], coords[b][1], None]
    return go.Scattergl(x=xs, y=ys, mode="lines", line=dict(color=colour, width=width, **({"dash": dash} if dash else {})),
                        hoverinfo="skip",
                        meta={**meta, "n": meta.get("n") or len(xs) // 3}, showlegend=False)


def _markers(go, points, colour, size, meta, symbol="circle", line_colour=None, opacity=1.0, hoverable_only=False):
    """points = [(x, y, name, hover html)]."""
    xs, ys, names, hover = (list(v) for v in zip(*points)) if points else ([], [], [], [])
    marker = dict(color="rgba(0,0,0,0)" if hoverable_only else colour, size=size, symbol=symbol,
                  line=dict(color="rgba(0,0,0,0)" if hoverable_only else (line_colour or colour), width=1))
    return go.Scattergl(x=xs, y=ys, mode="markers", text=names, hovertext=hover, hoverinfo="text", opacity=opacity,
                        marker=marker, textposition="top center", textfont=dict(size=10, color="#2c2c2a"),
                        meta={**meta, "names": True, "n": meta["n"] if meta.get("n") else len(xs)},
                        showlegend=False)


def _branch_ends(info):
    return {e: (a, b, km, n) for e, a, b, km, n in info.branches}


def _midpoint(coords, a, b):
    return ((coords[a][0] + coords[b][0]) / 2, (coords[a][1] + coords[b][1]) / 2)


def _short(element):
    return element.split(".", 1)[-1]


def _fmt(v, spec=".1f", unit=""):
    return "n/a" if v is None or v != v else f"{v:{spec}}{unit}"


def _element_hover(element, info, flows, extra=""):
    f = flows.get(element, {})
    asset = info._asset_map.get(element)
    rating = f"{asset.rating:g} {'kVA' if element.startswith('transformer.') else 'A'}" if asset else "no rating in the data"
    return (f"<b>{element}</b>{extra}<br>rating {rating}, loading {_fmt(f.get('loading_pct'), '.1f', ' %')}"
            f"<br>P {_fmt(f.get('P'), '.1f', ' kW')}, Q {_fmt(f.get('Q'), '.1f', ' kvar')}, pf {_fmt(f.get('pf'), '.3f')}"
            f"<br>current {_fmt(f.get('current_a'), '.1f', ' A')}, losses {_fmt(f.get('loss_kw'), '.2f', ' kW')}"
            f" ({_fmt(f.get('loss_pct'), '.2f', ' %')})"
            + (f"<br>nearest source: {info.source_of.get(info._ends.get(element, ('',))[0], '')}" if info.source_of else ""))


def network_figure(info, coords, title="Network map", der=None, customer_phases=None, results=None, limits=(0.94, 1.10),
                   bands=None):
    """Plotly figure of a network with every map mode (see the module text), for save_network_html().
    info = topology.read_network(); coords = {bus: (x, y)} for (ideally) every bus; der = optional
    list of scenario.DER (e.g. a PV placement); customer_phases = {load: phase} to colour by
    (default: the phases in 'info'); results = extract.collect_results(..., info=info) of a
    solved circuit, for the lenses; limits = voltage limits (pu) for the voltage lens; bands =
    {"voltage" / "current" / "power" / "pf" / "losses": [(label, low, high, colour)]} to replace
    the default bands of a lens (voltage_bands(limits), LOADING_BANDS, PF_BANDS, LOSS_BANDS)."""
    bands = {"voltage": voltage_bands(limits), "current": LOADING_BANDS, "power": LOADING_BANDS, "pf": PF_BANDS,
             "losses": LOSS_BANDS, **(bands or {})}
    import plotly.graph_objects as go

    info._asset_map = {a.element: a for a in info.assets}
    info._ends = ends = _branch_ends(info)
    phases = customer_phases or info.load_phases
    flows = (results or {}).get("elements", {})
    traces = []

    # ---- outline of every line, shown under the lenses and devices --------------------------------
    outline_pairs = [(a, b) for e, (a, b, _, _) in ends.items()]
    traces.append(_segments(go, outline_pairs, coords, OUTLINE, 1,
                            _meta([m for m in LENS_MODES if m != "sources"] + ["devices"], "Network outline")))

    # ---- Names and phases ---------------------------------------------------------------------------
    groups = {}
    for element, (a, b, km, n) in ends.items():
        if element.startswith("transformer."):
            groups.setdefault(("Transformer links", "elements without a phase", "#eda100", 1.5), []).append((a, b))
        elif element.startswith("line."):
            mv = info.bus_kv_ll.get(a, 0) > 1.0
            kind = ("MV lines" if mv else "LV lines")
            band = "3-phase lines" if n >= 3 else "1- or 2-phase lines"
            groups.setdefault((kind, band, LINE_COLOURS["mv" if mv else "lv"], (3 if mv else 2) if n >= 3 else (1.5 if mv else 1)),
                              []).append((a, b))
    for (group, band, colour, width), pairs in groups.items():
        traces.append(_segments(go, pairs, coords, colour, width, _meta("names", group, band, colour)))
    line_points = [(*_midpoint(coords, a, b), _short(e), _element_hover(e, info, flows, f"<br>{a} - {b}, {n} phase, {km * 1000:.0f} m"))
                   for e, (a, b, km, n) in ends.items() if e.startswith("line.") and a in coords and b in coords]
    traces.append(_markers(go, line_points, "#888780", 7, _meta("names", "Line hover points and names", "elements without a phase", "#888780"),
                           hoverable_only=True))
    load_buses = {info.loads[l]["bus"].split(".")[0].lower() for l in info.loads}
    bus_points = [(x, y, bus, f"<b>{bus}</b><br>{info.bus_kv_ll.get(bus, 0):.3g} kV") for bus, (x, y) in coords.items()
                  if bus not in load_buses]
    traces.append(_markers(go, bus_points, "#c8c6bd", 4, _meta("names", "Buses", "elements without a phase", "#c8c6bd", on=False)))
    tx_groups = {}
    for a_ in info.assets:
        if not a_.element.startswith("transformer.") or a_.element not in ends:
            continue
        a, b, _, _ = ends[a_.element]
        if a not in coords:
            continue
        head = a_.kind == "head_transformer"
        key = "Head transformers" if head else f"Transformers: {a_.group.replace('_', '-') or 'other'}"
        text = f"<b>{a_.element}</b><br>{a_.rating:.0f} kVA, {a_.group.replace('_', '-')}" + (", head" if head else "")
        tx_groups.setdefault(key, []).append((*coords[a], _short(a_.element), _element_hover(a_.element, info, flows) if flows else text))
    for key, points in sorted(tx_groups.items()):
        head = key.startswith("Head")
        traces.append(_markers(go, points, "#c0392b" if head else "#eda100", 16 if head else 9,
                               _meta(["names", "devices"] if head else "names", key, CONTEXT if head else "elements without a phase",
                                     "#c0392b" if head else "#eda100"),
                               "star" if head else "square"))
    src_points = {}                     # {source name: marker point}
    for src in (info.sources or [{"name": "source", "bus": info.source_bus, "kv_ll": info.bus_kv_ll.get(info.source_bus, 0)}]):
        if src["bus"] in coords:
            pq = (results or {}).get("source_pq", {}).get(src["name"])
            extra = f"<br>P {pq[0]:.1f} kW, Q {pq[1]:.1f} kvar" if pq else ""
            src_points.append((*coords[src["bus"]], src["name"], f"<b>Source {src['name']}</b><br>bus {src['bus']}, {src['kv_ll']:g} kV{extra}"))
    traces.append(_markers(go, src_points, "#2c2c2a", 15, _meta([m for m in MODES if m != "sources"], "Sources", CONTEXT, "#2c2c2a"),
                           "triangle-up"))
    load_groups = {}
    for load, data in info.loads.items():
        bus = data["bus"].split(".")[0].lower()
        if bus not in coords:
            continue
        phase = phases.get(load, "?")
        fixed = info.fixed_loads.get(load)
        v = (results or {}).get("loads", {}).get(load)
        text = (f"<b>{load}</b><br>bus {data['bus']}<br>phase {phase}, {data['kV']:.3g} kV"
                + (f"<br>P {v[1]:.2f} kW, Q {v[2]:.2f} kvar, V min {v[3]:.4f} pu" if v else "")
                + (f"<br>fixed shape: {fixed[0]} ({fixed[1]})" if fixed else ""))
        band = f"Phase {phase}" if phase in PHASE_COLOURS else "Multi-phase"
        load_groups.setdefault(("Loads, fixed shape" if fixed else "Loads", band, phase), []).append((*coords[bus], load, text))
    for (group, band, phase), points in sorted(load_groups.items()):
        colour = PHASE_COLOURS.get(phase, MULTI_PHASE_COLOUR)
        if group.endswith("fixed shape"):
            traces.append(_markers(go, points, "white", 10, _meta("names", group, band, colour), "diamond", line_colour=colour))
        else:
            traces.append(_markers(go, points, colour, 6, _meta("names", group, band, colour)))
    if der:
        pv_groups = {}
        for d in der:
            data = info.loads.get(d.customer)
            if data and data["bus"].split(".")[0].lower() in coords:
                phase = phases.get(d.customer, "?")
                pv_groups.setdefault(phase, []).append((*coords[data["bus"].split(".")[0].lower()], f"PV {d.customer}",
                                                        f"<b>{d.kind.upper()} {d.customer}</b><br>{d.kva:g} kVA, phase {phase}"))
        for phase, points in sorted(pv_groups.items()):
            colour = PHASE_COLOURS.get(phase, MULTI_PHASE_COLOUR)
            band = f"Phase {phase}" if phase in PHASE_COLOURS else "Multi-phase"
            traces.append(_markers(go, points, "rgba(0,0,0,0)", 14, _meta("names", "PV systems", band, colour), "circle-open",
                                   line_colour=colour))

    # ---- Devices ----------------------------------------------------------------------------------------
    dev_groups = {}
    for element, kind in info.devices.items():
        a, b = info.device_buses.get(element, ends.get(element, (None, None))[:2])
        if a not in coords:
            continue
        xy = _midpoint(coords, a, b) if b in coords and element.startswith("line.") else coords[a]
        hover = _element_hover(element, info, flows, f" ({kind})") if element in ends else f"<b>{element}</b> ({kind})<br>bus {a}"
        dev_groups.setdefault(kind, []).append((*xy, _short(element), hover))
    for kind, points in sorted(dev_groups.items()):
        name, colour, symbol, size = DEVICE_STYLE.get(kind, (kind, "#5f5e5a", "circle", 10))
        traces.append(_markers(go, points, colour, size, _meta("devices", name, CONTEXT, colour), symbol))

    # ---- Sources lens (needs only the network) ----------------------------------------------------------
    traces += _source_lens(go, info, coords, flows, ends, src_points)

    # ---- Lenses (need results) --------------------------------------------------------------------------
    if results:
        traces += _voltage_lens(go, info, coords, results, bands["voltage"])
        traces += _flow_lens(go, info, coords, flows, ends, "current", lambda e: e.startswith("line."),
                             lambda f: f["loading_pct"], bands["current"], NO_RATING)
        traces += _flow_lens(go, info, coords, flows, ends, "power", lambda e: e.startswith("transformer."),
                             lambda f: f["loading_pct"], bands["power"], NO_RATING)
        traces += _flow_lens(go, info, coords, flows, ends, "pf", lambda e: True, _pf_value, bands["pf"], NO_FLOW)
        traces += _flow_lens(go, info, coords, flows, ends, "losses", lambda e: True,
                             lambda f: f["loss_pct"] if _has_flow(f) else math.nan, bands["losses"], NO_FLOW)
        traces += _source_lens(go, info, coords, flows, ends, src_points)

    xs = [x for x, _ in coords.values()]
    ys = [y for _, y in coords.values()]
    pad_x = 0.03 * ((max(xs) - min(xs)) or 1) if xs else 1
    pad_y = 0.03 * ((max(ys) - min(ys)) or 1) if ys else 1
    fig = go.Figure(traces)
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=15)), template="plotly_white", hovermode="closest",
                      dragmode="pan", showlegend=False, margin=dict(l=10, r=10, t=40, b=10), uirevision="keep",
                      meta={"band_titles": BAND_TITLES, "lens_modes": LENS_MODES,
                            "modes": {m: label for m, label in MODES.items()
                                      if any(m in t.meta["modes"] and t.meta["group"] not in ("Network outline", "Sources")
                                             for t in traces)}})
    fig.update_xaxes(visible=False, range=[min(xs) - pad_x, max(xs) + pad_x] if xs else None, autorange=False if xs else True)
    fig.update_yaxes(visible=False, range=[min(ys) - pad_y, max(ys) + pad_y] if ys else None, autorange=False if ys else True,
                     scaleanchor="x", scaleratio=1)
    return fig


def _has_flow(f):
    return math.hypot(f["P"], f["Q"]) >= 1.0


def _pf_value(f):
    return f["pf"] if _has_flow(f) else math.nan


def _voltage_lens(go, info, coords, results, bands):
    groups = {}
    for bus, (lo, hi) in results.get("bus_v", {}).items():
        if bus not in coords:
            continue
        # the energized node furthest from 1 pu (lo is the lowest energized node; a bus with no
        # energized node has lo = hi = its highest node, so it falls in a not-energized band)
        value = lo if (1 - lo) >= (hi - 1) else hi
        band = band_of(value, bands)
        kind = "MV buses" if info.bus_kv_ll.get(bus, 0) > 1.0 else "LV buses"
        groups.setdefault((kind, band), []).append((*coords[bus], bus, f"<b>{bus}</b><br>{info.bus_kv_ll.get(bus, 0):.3g} kV, "
                                                                     f"nodes {lo:.4f} - {hi:.4f} pu<br>nearest source: "
                                                                     f"{info.source_of.get(bus, '')}"))
    order = {b[0]: i for i, b in enumerate(bands)}
    return [_markers(go, points, colour, 9 if label != "normal" else 5, _meta("voltage", kind, label, colour, rank=order[label] + 1))
            for (kind, (label, colour)), points in sorted(groups.items(), key=lambda kv: (kv[0][0], order[kv[0][1][0]]))]


def _element_kind(info, element, a):
    """Element type shown in the lens checklists: MV / LV lines, head transformers, transformers by class."""
    if element.startswith("line."):
        return "MV lines" if info.bus_kv_ll.get(a, 0) > 1.0 else "LV lines"
    asset = info._asset_map.get(element)
    if asset and asset.kind == "head_transformer":
        return "Head transformers"
    return f"Transformers: {info.transformer_class.get(element, 'other').replace('_', '-')}"


def _source_lens(go, info, coords, flows, ends, src_points):
    """Sources lens: buses, lines and transformers coloured by the source that feeds them (info.source_of),
    one band per source (so each source's area can be shown or hidden), then the ties between two
    sources' areas (info.source_ties) and the parts no source reaches (islands)."""
    names = [s["name"] for s in info.sources] or [s[2] for s in src_points]
    names += sorted(set(info.source_of.values()) - set(names))
    bands = {n: (n, SOURCE_COLOURS[i % len(SOURCE_COLOURS)]) for i, n in enumerate(names)}
    order = {label: i + 1 for i, label in enumerate(names + [SOURCE_TIES[0], NOT_REACHED[0]])}
    ties = {e for e, _, _ in info.source_ties}

    def hover(element, a, b):
        if flows:
            return _element_hover(element, info, flows)
        return f"<b>{element}</b><br>{a} - {b}<br>source: {info.source_of.get(a, info.source_of.get(b, 'none (not reached)'))}"

    def band(*buses):
        for bus in buses:
            if bus in info.source_of:
                return bands.get(info.source_of[bus], NOT_REACHED)
        return NOT_REACHED

    groups = {}
    for element, (a, b, _, _) in ends.items():
        if not element.startswith(("line.", "transformer.")) or a not in coords or b not in coords:
            continue
        groups.setdefault((_element_kind(info, element, a), SOURCE_TIES if element in ties else band(a, b)), []).append(element)
    for bus, xy in coords.items():
        kind = "MV buses" if info.bus_kv_ll.get(bus, 0) > 1.0 else "LV buses"
        groups.setdefault((kind, band(bus)), []).append(bus)

    # grey outline under the areas, so a hidden source's area still shows where it is
    traces = [_segments(go, [(a, b) for a, b, _, _ in ends.values()], coords, OUTLINE, 1,
                        _meta("sources", "Network outline", "outline of hidden areas (grey)", OUTLINE))]
    for (kind, (label, colour)), items in sorted(groups.items(), key=lambda kv: (kv[0][0], order[kv[0][1][0]])):
        meta = _meta("sources", kind, label, colour, rank=order[label])
        tie = label == SOURCE_TIES[0]
        if kind.endswith("lines"):
            traces.append(_segments(go, [ends[e][:2] for e in items], coords, colour, 3.5 if tie else 2, meta))
            points = [(*_midpoint(coords, *ends[e][:2]), _short(e), hover(e, *ends[e][:2])) for e in items]
            traces.append(_markers(go, points, colour, 8, {**meta, "n": -1}, hoverable_only=not tie))
        elif kind.endswith("buses"):
            points = [(*coords[bus], bus, f"<b>{bus}</b><br>{info.bus_kv_ll.get(bus, 0):.3g} kV<br>source: "
                                          f"{info.source_of.get(bus, 'none (not reached)')}") for bus in items]
            traces.append(_markers(go, points, colour, 5, meta))
        else:
            head = kind.startswith("Head")
            points = [(*coords[ends[e][0]], _short(e), hover(e, *ends[e][:2])) for e in items]
            traces.append(_markers(go, points, colour, 16 if head else 9, meta, "star" if head else "square"))
    # the sources themselves, in their own colour and shown / hidden with their area
    for x, y, name, hover in src_points:
        label, colour = bands.get(name, NOT_REACHED)
        traces.append(_markers(go, [(x, y, name, hover)], colour, 17, _meta("sources", "Sources", label, colour, rank=order[label]),
                               "triangle-up", line_colour="#2c2c2a"))
    return traces


def _is_far_end(mode, label, bands):
    """Bands at the far ends of a lens (great deviation and beyond)."""
    if mode in ("current", "power"):
        return label in ("0 % (no current)", "below 1 %", "1-10 %", "110-150 %", "150-300 %", "above 300 %")
    if mode == "pf":
        return label in ("pf below 0.80", REVERSE[0])
    if mode == "losses":
        return label in ("5-10 %", "above 10 %")
    return False


def _flow_lens(go, info, coords, flows, ends, mode, include, value_of, bands, missing, band_for=None):
    """Lines and transformers grouped by band. band_for(element, flows) -> (label, colour) replaces
    the banding of value_of(flows) when given (used by the source lens); 'bands' then only
    fixes the order of the bands."""
    groups = {}
    for element, f in flows.items():
        if not include(element) or element not in ends:
            continue
        a, b, _, _ = ends[element]
        if a not in coords or b not in coords:
            continue
        if band_for:
            band = band_for(element, f)
        else:
            band = band_of(value, bands) if value == value else missing
        groups.setdefault((_element_kind(info, element, a), band or missing), []).append(element)
    order = {b[0]: i for i, b in enumerate(bands)}
    traces = []
    for (kind, (label, colour)), elements in sorted(groups.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1][0], 99))):
        meta = _meta(mode, kind, label, colour, rank=order.get(label, len(bands)) + 1)
        severe = _is_far_end(mode, label, bands)
        if kind.endswith("lines"):
            traces.append(_segments(go, [ends[e][:2] for e in elements], coords, colour, 3.5 if severe else 2, meta))
            points = [(*_midpoint(coords, *ends[e][:2]), _short(e), _element_hover(e, info, flows)) for e in elements]
            # far-end bands get a visible dot in the middle of each line, so even very short lines
            # (e.g. fuses and switches) stand out; the others are only hover points
            traces.append(_markers(go, points, colour, 8 if severe else 7, {**meta, "n": -1}, hoverable_only=not severe))
        else:
            points = [(*coords[ends[e][0]], _short(e), _element_hover(e, info, flows)) for e in elements]
            traces.append(_markers(go, points, colour, 12 if severe else 9, meta, "square"))
    return traces


def _source_lens(go, info, coords, flows, ends, src_points):
    """Source lens: every bus, line and transformer in the colour of the source that feeds it (the
    nearest source, info.source_of); lines and transformers that join the areas of two sources
    are one band of their own, and anything no source reaches another. One band per source, so
    ticking a source shows or hides its area and its triangle. [] for fewer than two sources."""
    names = [s["name"] for s in info.sources]
    if len(names) < 2:
        return []
    colours = {n: SOURCE_COLOURS[i % len(SOURCE_COLOURS)] for i, n in enumerate(names)}
    bands = [(n, 0, 0, colours[n]) for n in names] + [(TIES[0], 0, 0, TIES[1]), (NOT_FED[0], 0, 0, NOT_FED[1])]
    order = {b[0]: i for i, b in enumerate(bands)}
    tie_elements = {e for e, _, _ in info.source_ties}

    def area(bus):
        source = info.source_of.get(bus)
        return (source, colours[source]) if source in colours else NOT_FED

    traces = _flow_lens(go, info, coords, flows, ends, "sources", lambda e: True, None, bands, NOT_FED,
                        band_for=lambda e, f: TIES if e in tie_elements else area(ends[e][0]))
    groups = {}
    for bus in info.buses:
        if bus in coords:
            label, colour = area(bus)
            kind = "MV buses" if info.bus_kv_ll.get(bus, 0) > 1.0 else "LV buses"
            groups.setdefault((kind, label, colour), []).append(
                (*coords[bus], bus, f"<b>{bus}</b><br>{info.bus_kv_ll.get(bus, 0):.3g} kV<br>fed by: {label}"))
    for (kind, label, colour), points in sorted(groups.items(), key=lambda kv: (kv[0][0], order[kv[0][1]])):
        traces.append(_markers(go, points, colour, 5, _meta("sources", kind, label, colour, rank=order[label] + 1)))
    for name in names:
        if name in src_points:
            traces.append(_markers(go, [src_points[name]], colours[name], 15,
                                   _meta("sources", "Sources", name, colours[name], rank=order[name] + 1),
                                   "triangle-up", line_colour="#2c2c2a"))
    return traces


# --- Page ------------------------------------------------------------------------------------------
PAGE_CSS = """
*{box-sizing:border-box} html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
color:#2c2c2a;background:#fff;font-size:13px}
#app{display:flex;flex-direction:row;height:100vh;width:100vw;overflow:hidden}
#panel{flex:0 0 300px;max-width:300px;height:100vh;overflow-y:auto;border-right:1px solid #d3d1c7;padding:10px 12px;background:#faf9f5}
#main{flex:1 1 auto;min-width:0;height:100vh;position:relative}
#plot{width:100%;height:100%}
h1{font-size:15px;font-weight:600;margin:0 0 8px} h2{font-size:12px;font-weight:600;margin:12px 0 4px;text-transform:uppercase;
letter-spacing:.04em;color:#5f5e5a}
.mode{display:block;width:100%;text-align:left;margin:2px 0;padding:5px 8px;border:1px solid #d3d1c7;border-radius:6px;
background:#fff;cursor:pointer;font-size:13px} .mode.on{background:#2c2c2a;color:#fff;border-color:#2c2c2a}
.row{display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer;line-height:1.25}
.sw{flex:0 0 14px;height:14px;border-radius:3px;border:1px solid rgba(0,0,0,.25)}
.count{margin-left:auto;color:#888780;font-variant-numeric:tabular-nums}
.tools{display:flex;gap:6px;margin:2px 0 4px} .tools button{font-size:11px;padding:2px 8px;border:1px solid #d3d1c7;
border-radius:5px;background:#fff;cursor:pointer}
.hint{color:#5f5e5a;font-size:12px;line-height:1.4;margin-top:10px}
#toggle{position:absolute;top:8px;left:8px;z-index:5;font-size:12px;padding:4px 10px;border:1px solid #b4b2a9;border-radius:6px;
background:#fff;cursor:pointer;display:none}
#app.collapsed #panel{display:none} #app.collapsed #toggle{display:block}
@media (max-width:820px),(max-height:420px) and (max-width:1100px){
 #app{flex-direction:column;height:auto;min-height:100vh;overflow:visible}
 #panel{flex:none;max-width:none;width:100%;height:auto;max-height:45vh;border-right:none;border-bottom:1px solid #d3d1c7}
 #main{height:80vh;min-height:360px} #modes{display:flex;flex-wrap:wrap;gap:4px} .mode{width:auto;margin:0}}
"""

PAGE_JS = """
const fig = FIGURE; const modes = fig.layout.meta.modes; const traces = fig.data;
const state = {}; let mode = Object.keys(modes)[0]; let names = false;
for (const m of Object.keys(modes)) { state[m] = {groups:{}, bands:{}}; }
traces.forEach(t => { for (const m of t.meta.modes) { if (!state[m]) continue;
  const s = state[m]; if (!(t.meta.group in s.groups)) s.groups[t.meta.group] = t.meta.on;
  if (!(t.meta.band in s.bands)) s.bands[t.meta.band] = true; } });
function count(t){ return Math.max(t.meta.n || 0, 0); }
function visible(t){ return t.meta.modes.includes(mode) && state[mode].groups[t.meta.group] !== false && state[mode].bands[t.meta.band] !== false; }
function apply(){ const v = traces.map(t => visible(t)); const md = traces.map(t => t.mode === 'lines' ? 'lines' : (names && visible(t) ? 'markers+text' : 'markers'));
  Plotly.restyle('plot', {visible: v, mode: md}); }
function el(tag, attrs, text){ const e = document.createElement(tag); Object.assign(e, attrs||{}); if (text!==undefined) e.textContent = text; return e; }
function checklist(box, kind){ box.innerHTML = ''; const s = state[mode][kind]; const key = kind === 'groups' ? 'group' : 'band';
  const items = {}; traces.forEach(t => { if (t.meta.modes.includes(mode) && t.meta[key] !== undefined) {
    const k = t.meta[key]; items[k] = items[k] || {n:0, colour:t.meta.colour, rank:t.meta.rank || 0}; items[k].n += count(t); } });
  let keys = Object.keys(items); if (kind === 'bands') keys.sort((a, b) => items[a].rank - items[b].rank);
  if (kind === 'bands' && keys.length <= 1) { box.parentElement.style.display = 'none'; return; }
  box.parentElement.style.display = '';
  if (kind === 'bands') document.getElementById('bandtitle').textContent = (fig.layout.meta.band_titles || {})[mode] || 'Value bands';
  const neutral = kind === 'groups' && (fig.layout.meta.lens_modes || []).includes(mode);
  for (const k of keys) { const row = el('label', {className:'row'}); const cb = el('input', {type:'checkbox', checked: s[k] !== false});
    cb.onchange = () => { s[k] = cb.checked; apply(); };
    const sw = el('span', {className:'sw'}); sw.style.background = neutral ? '#fff' : items[k].colour;
    row.append(cb, sw, el('span', {}, k), el('span', {className:'count'}, items[k].n ? items[k].n : ''));
    box.append(row); } }
function setAll(kind, value){ for (const k in state[mode][kind]) state[mode][kind][k] = value; draw(); }
function draw(){ document.querySelectorAll('.mode').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
  checklist(document.getElementById('groups'), 'groups'); checklist(document.getElementById('bands'), 'bands'); apply(); }
const mbox = document.getElementById('modes');
for (const [m, label] of Object.entries(modes)) { const b = el('button', {className:'mode'}, label); b.dataset.mode = m;
  b.onclick = () => { mode = m; draw(); }; mbox.append(b); }
document.getElementById('names').onchange = e => { names = e.target.checked; apply(); };
document.getElementById('hide').onclick = () => { document.getElementById('app').classList.add('collapsed'); Plotly.Plots.resize('plot'); };
document.getElementById('toggle').onclick = () => { document.getElementById('app').classList.remove('collapsed'); Plotly.Plots.resize('plot'); };
Plotly.newPlot('plot', traces, fig.layout, CONFIG).then(draw);
window.addEventListener('resize', () => Plotly.Plots.resize('plot'));
"""


def save_network_html(fig, file_path):
    """Save a network_figure() as one offline HTML page: the map plus the panel with modes,
    checklists and 'Show names' (see the module text). Scroll to zoom, drag to pan,
    double-click to reset."""
    import plotly.io as pio
    from plotly.offline import get_plotlyjs

    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    figure = json.loads(pio.to_json(fig, validate=False))
    figure["layout"].setdefault("meta", {}).setdefault("modes", {"names": MODES["names"]})
    for t in figure["data"]:
        t.setdefault("meta", _meta("names", t.get("name") or "Elements"))
    title = figure["layout"].get("title", {}).get("text", "Network map")
    figure["layout"]["title"] = {"text": ""}
    config = {"scrollZoom": True, "displaylogo": False, "responsive": True, "toImageButtonOptions": {"scale": 3}}
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{PAGE_CSS}</style>
<script>{get_plotlyjs()}</script></head>
<body><div id="app">
<aside id="panel"><h1>{html.escape(title)}</h1>
<div class="tools"><button id="hide" title="Hide this panel">Hide panel</button></div>
<h2>Mode</h2><div id="modes"></div>
<h2>Show</h2><label class="row"><input type="checkbox" id="names"><span>Show names of shown elements (zoom in first)</span></label>
<section><h2>Element types</h2><div class="tools"><button onclick="setAll('groups', true)">All</button>
<button onclick="setAll('groups', false)">None</button></div><div id="groups"></div></section>
<section><h2 id="bandtitle">Value bands</h2><div class="tools"><button onclick="setAll('bands', true)">All</button>
<button onclick="setAll('bands', false)">None</button></div><div id="bands"></div></section>
<p class="hint">Scroll to zoom, drag to pan, double-click to reset. Hover over any element for its name and values.
Changing mode keeps the zoom. Lines are hoverable at their middle.</p>
</aside>
<main id="main"><button id="toggle">Show panel</button><div id="plot"></div></main></div>
<script>const FIGURE = {json.dumps(figure)}; const CONFIG = {json.dumps(config)};
{PAGE_JS}</script></body></html>"""
    file_path.write_text(page, encoding="utf-8")
    return file_path
