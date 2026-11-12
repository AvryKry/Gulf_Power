"""Interactive (zoomable) network maps saved as a single HTML file.

Markers keep their size on screen while you zoom, so the zoomed-out view shows the skeleton of the
feeder and zooming into an LV network spreads its houses apart. Hovering over a bus, load,
transformer or line shows its details; clicking an entry in the legend hides or shows that layer.

The file is fully offline (the Plotly library is written into it): opening it never contacts the
internet, so confidential network data stays on the computer.
Needs the 'plotly' package (pip install plotly).
"""
from pathlib import Path

PHASE_COLOURS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
MULTI_PHASE_COLOUR = "#6250d6"
LINE_COLOURS = {"mv": "#3d3d3a", "lv": "#9a9893"}


def _line_trace(go, xs, ys, name, colour, width, visible=True):
    return go.Scattergl(x=xs, y=ys, mode="lines", line=dict(color=colour, width=width), name=name,
                        hoverinfo="skip", visible=True if visible else "legendonly")


def _marker_trace(go, points, name, colour, size, symbol="circle", visible=True, line_colour=None, opacity=1.0):
    xs, ys, texts = zip(*points) if points else ((), (), ())
    return go.Scattergl(x=xs, y=ys, mode="markers", name=f"{name} ({len(points)})", text=texts,
                        hovertemplate="%{text}<extra></extra>", opacity=opacity,
                        marker=dict(color=colour, size=size, symbol=symbol,
                                    line=dict(color=line_colour or colour, width=1)),
                        visible=True if visible else "legendonly")


def network_figure(info, coords, title="Network map", der=None, customer_phases=None):
    """Plotly figure of a network. info = topology.read_network(); coords = {bus: (x, y)} for
    (ideally) every bus; der = optional list of scenario.DER to show (e.g. a PV placement);
    customer_phases = {load: phase} to colour by (default: the phases found in 'info')."""
    import plotly.graph_objects as go

    phases = customer_phases or info.load_phases
    asset_kind = {a.element: a for a in info.assets}
    segments = {"mv3": ([], []), "mv1": ([], []), "lv3": ([], []), "lv1": ([], []), "tx": ([], [])}
    hover_points = []
    for element, a, b, km, n_phases in info.branches:
        if a not in coords or b not in coords:
            continue
        (x0, y0), (x1, y1) = coords[a], coords[b]
        if element.startswith("transformer."):
            key = "tx"
        else:
            mv = info.bus_kv_ll.get(a, 0) > 1.0
            key = ("mv" if mv else "lv") + ("3" if n_phases >= 3 else "1")
            asset = asset_kind.get(element)
            rating = f"{asset.rating:.0f} A" if asset else "no rating in data"
            hover_points.append(((x0 + x1) / 2, (y0 + y1) / 2,
                                 f"<b>{element}</b><br>{a} - {b}<br>{n_phases} phase, {km * 1000:.0f} m<br>rating {rating}"))
        xs, ys = segments[key]
        xs += [x0, x1, None]
        ys += [y0, y1, None]

    traces = [
        _line_trace(go, *segments["mv3"], "MV line, 3-phase", LINE_COLOURS["mv"], 3),
        _line_trace(go, *segments["mv1"], "MV line, 1/2-phase", LINE_COLOURS["mv"], 1.5),
        _line_trace(go, *segments["lv3"], "LV line, 3-phase", LINE_COLOURS["lv"], 2),
        _line_trace(go, *segments["lv1"], "LV line, 1/2-phase", LINE_COLOURS["lv"], 1),
        go.Scattergl(x=segments["tx"][0], y=segments["tx"][1], mode="lines", name="Transformer link",
                     line=dict(color="#eda100", width=1.5, dash="dot"), hoverinfo="skip"),
        _marker_trace(go, hover_points, "Line details (hover)", "#888780", 5, visible=False, opacity=0.4),
    ]
    # buses without anything else (hidden by default)
    load_buses = {info.loads[l]["bus"].split(".")[0].lower() for l in info.loads}
    bus_points = [(x, y, f"<b>{bus}</b><br>{info.bus_kv_ll.get(bus, 0):.3g} kV") for bus, (x, y) in coords.items()
                  if bus not in load_buses]
    traces.append(_marker_trace(go, bus_points, "Bus", "#c8c6bd", 4, visible=False))
    # transformers (at their first winding bus)
    tx_points, head_points = [], []
    for element, a, b, km, n_phases in info.branches:
        if element.startswith("transformer.") and a in coords:
            asset = asset_kind.get(element)
            text = f"<b>{element}</b><br>{asset.rating:.0f} kVA" if asset else f"<b>{element}</b>"
            x, y = coords[a]
            (head_points if asset and asset.kind == "head_transformer" else tx_points).append((x, y, text))
    traces.append(_marker_trace(go, list(dict.fromkeys(tx_points)), "Transformer", "#eda100", 9, "square"))
    traces.append(_marker_trace(go, list(dict.fromkeys(head_points)), "Head (substation) transformer", "#c0392b", 16, "star"))
    if info.source_bus in coords:
        x, y = coords[info.source_bus]
        traces.append(_marker_trace(go, [(x, y, f"<b>Source</b><br>{info.source_bus}")], "Source", "#2c2c2a", 14, "triangle-up"))
    # loads by phase; fixed-shape loads as diamonds
    groups = {}
    for load, data in info.loads.items():
        bus = data["bus"].split(".")[0].lower()
        if bus not in coords:
            continue
        phase = phases.get(load, "?")
        fixed = info.fixed_loads.get(load)
        x, y = coords[bus]
        text = (f"<b>{load}</b><br>bus {data['bus']}<br>phase {phase}, {data['kV']:.3g} kV"
                + (f"<br>fixed shape: {fixed[0]} ({fixed[1]})" if fixed else ""))
        key = ("fixed" if fixed else "random", phase if phase in PHASE_COLOURS else "multi")
        groups.setdefault(key, []).append((x, y, text))
    for (kind, phase), points in sorted(groups.items()):
        colour = PHASE_COLOURS.get(phase, MULTI_PHASE_COLOUR)
        label = f"Load, phase {phase}" if phase in PHASE_COLOURS else "Load, multi-phase"
        if kind == "fixed":
            traces.append(_marker_trace(go, points, label + ", fixed shape", "white", 10, "diamond", line_colour=colour))
        else:
            traces.append(_marker_trace(go, points, label, colour, 6))
    # optional DER overlay (e.g. a PV placement), coloured by phase
    if der:
        pv_groups = {}
        for d in der:
            data = info.loads.get(d.customer)
            if not data:
                continue
            bus = data["bus"].split(".")[0].lower()
            if bus in coords:
                phase = phases.get(d.customer, "?")
                x, y = coords[bus]
                pv_groups.setdefault(phase, []).append((x, y, f"<b>{d.kind.upper()} {d.customer}</b><br>{d.kva:g} kVA, phase {phase}"))
        for phase, points in sorted(pv_groups.items()):
            traces.append(_marker_trace(go, points, f"PV, phase {phase}", "rgba(0,0,0,0)", 14, "circle-open",
                                        line_colour=PHASE_COLOURS.get(phase, MULTI_PHASE_COLOUR)))
    fig = go.Figure(traces)
    fig.update_layout(title=title, template="plotly_white", hovermode="closest", dragmode="pan",
                      legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="left", x=0, font=dict(size=11)),
                      margin=dict(l=10, r=10, t=50, b=10), height=850)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    return fig


def save_network_html(fig, file_path):
    """Save a figure as one offline HTML file (scroll to zoom, drag to pan, double-click to reset)."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(file_path, include_plotlyjs=True, full_html=True,
                   config={"scrollZoom": True, "displaylogo": False, "toImageButtonOptions": {"scale": 3}})
    return file_path
