"""Figures. Each plot_* brick creates one figure and returns it; draw_* bricks draw on an
existing axis so they can be combined. show_or_save() decides what happens to a figure.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from . import network as net

INK, LIMIT = "#52514e", "#e34948"
PHASE_COLOURS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a"}
CASE_COLOURS = ["#9a9893", "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4"]
LINE_WIDTH = {3: 4.0, 2: 2.0, 1: 0.8}
LOAD_MARKERS = {"3-phase": ("s", 260, 2.0), "phase-to-phase": ("D", 170, 1.5), "1-phase": ("s", 120, 1.2)}


def apply_style():
    plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": 0.3, "font.size": 10})


def show_or_save(fig, save_as=None, show=True):
    """Save the figure (if 'save_as' is a path) and/or show it, then close it. A skipped figure
    (None) is ignored."""
    if fig is None:
        return
    if save_as:
        Path(save_as).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_as, dpi=150, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)


def draw_limits(ax, limits, horizontal=True):
    for v in limits:
        (ax.axhline if horizontal else ax.axvline)(v, color=LIMIT, ls="--", lw=1)


def hide_axes(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.margins(0.1)


# --- Network map -----------------------------------------------------------------------------
def draw_branches(ax, engine, exclude=()):
    """Lines (thickness = phases) and transformers (dotted)."""
    for b1, b2, n_ph, _ in net.line_segments(engine, exclude):
        (x1, y1), (x2, y2) = net.bus_xy(engine, b1), net.bus_xy(engine, b2)
        ax.plot([x1, x2], [y1, y2], color=INK, lw=LINE_WIDTH.get(n_ph, 1), solid_capstyle="butt", zorder=1)
    for b1, b2 in net.transformer_segments(engine):
        (x1, y1), (x2, y2) = net.bus_xy(engine, b1), net.bus_xy(engine, b2)
        ax.plot([x1, x2], [y1, y2], color=INK, lw=1.5, ls=":", zorder=1)


def short_labels(names):
    """{name: shortest ending of the name (split at '_') that is still unique among 'names'},
    e.g. 'bus_mg1_t1_f1_b12' -> 'b12', but 'bus_mg1_t1_f1_b1' -> 'f1_b1' if 'bus_mg1_t1_f2_b1' exists.
    Names without '_' (e.g. '632') stay as they are."""
    parts = {n: n.split("_") for n in names}
    out = {}
    for n, p in parts.items():
        for k in range(1, len(p) + 1):
            candidate = "_".join(p[-k:])
            if sum("_".join(q[-k:]) == candidate for q in parts.values() if len(q) >= k) == 1:
                break
        out[n] = candidate
    return out


def bus_label_texts(buses, labels):
    """{bus: text} for a label option: True / "full" = full name, "short" = short_labels(),
    False / None = no labels ({}), or a function name -> text."""
    if not labels:
        return {}
    if callable(labels):
        return {b: labels(b) for b in buses}
    if labels == "short":
        return short_labels(buses)
    if labels in (True, "full"):
        return {b: b for b in buses}
    raise ValueError(f"labels must be True, 'full', 'short', False/None or a function, not {labels!r}")


def draw_buses(ax, engine, exclude=(), values=None, cmap="Blues", labels=True, fontsize=8):
    """Bus circles; if 'values' {bus: number} is given the circles are coloured by it.
    'labels': True / "full", "short", False / None, or a function (see bus_label_texts)."""
    buses = net.bus_names(engine, exclude)
    xy = np.array([net.bus_xy(engine, b) for b in buses])
    colours = [values[b] for b in buses] if values else "white"
    sc = ax.scatter(xy[:, 0], xy[:, 1], s=160 if values else 60, c=colours, cmap=cmap if values else None,
                    edgecolors=INK, lw=0.8, zorder=2)
    texts = bus_label_texts(buses, labels)
    for b, (x, y) in zip(buses, xy):
        if b in texts:
            text = f"{texts[b]}\n{values[b]:+.1f}" if values else texts[b]
            ax.annotate(text, (x, y), xytext=(8, 8), textcoords="offset points", fontsize=fontsize)
    return sc


def draw_loads_and_capacitors(ax, engine):
    for bus, kind in net.load_bus_types(engine).items():
        marker, size, lw = LOAD_MARKERS[kind]
        x, y = net.bus_xy(engine, bus)
        ax.scatter(x, y, marker=marker, s=size, facecolors="none", edgecolors="#2a78d6", lw=lw, zorder=3)
    for bus in net.capacitor_buses(engine):
        x, y = net.bus_xy(engine, bus)
        ax.scatter(x, y, marker="^", s=70, color="#eb6834", zorder=3)


def draw_map_legend(ax):
    for n_ph in (3, 2, 1):
        ax.plot([], [], color=INK, lw=LINE_WIDTH[n_ph], label=f"{n_ph}-phase line")
    ax.plot([], [], color=INK, lw=1.5, ls=":", label="Transformer / regulator")
    for kind, (marker, size, lw) in LOAD_MARKERS.items():
        ax.scatter([], [], marker=marker, s=size / 2, facecolors="none", edgecolors="#2a78d6", lw=lw, label=f"{kind} load")
    ax.scatter([], [], marker="^", s=50, color="#eb6834", label="Capacitor")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=4, frameon=False)


def plot_network_map(engine, exclude=(), title="Network", labels=True):
    """Map of the circuit from its bus coordinates. Returns None if there are no coordinates.
    'labels': True / "full", "short", False / None, or a function (see bus_label_texts)."""
    if not net.has_coordinates(engine, exclude):
        print("No bus coordinates in this circuit: the network map is skipped.")
        return None
    fig, ax = plt.subplots(figsize=(9, 6))
    draw_branches(ax, engine, exclude)
    draw_buses(ax, engine, exclude, labels=labels)
    draw_loads_and_capacitors(ax, engine)
    draw_map_legend(ax)
    hide_axes(ax)
    ax.set_title(title)
    return fig


def bus_voltage_change(engine, a, b, exclude=()):
    """{bus: largest change of its phase voltages from case a to case b [% of nominal]}"""
    return {bus: 100 * max((b["vnode"][f"{bus}.{n}"] - a["vnode"][f"{bus}.{n}"] for n in net.bus_nodes(engine, bus)), key=abs)
            for bus in net.bus_names(engine, exclude)}


def plot_voltage_change_map(engine, a, b, exclude=(), highlight=(), title="Voltage change", labels=True):
    """Network map with buses coloured by the voltage change from case a to case b;
    'highlight' buses (e.g. PV locations) get an orange square. 'labels' as in plot_network_map;
    with labels off the change values are not printed either (the colour bar still shows them)."""
    if not net.has_coordinates(engine, exclude):
        print("No bus coordinates in this circuit: the voltage change map is skipped.")
        return None
    change = bus_voltage_change(engine, a, b, exclude)
    fig, ax = plt.subplots(figsize=(9, 6))
    draw_branches(ax, engine, exclude)
    sc = draw_buses(ax, engine, exclude, values=change, cmap="Blues" if min(change.values()) >= 0 else "RdBu_r",
                    labels=labels)
    for bus in highlight:
        x, y = net.bus_xy(engine, net.bus_name(bus))
        ax.scatter(x, y, marker="s", s=420, facecolors="none", edgecolors="#eda100", lw=2, zorder=3)
    fig.colorbar(sc, ax=ax, label="Voltage change [% of nominal]")
    hide_axes(ax)
    ax.set_title(title)
    return fig


# --- Snapshot comparisons --------------------------------------------------------------------
def plot_voltage_profiles(cases, labels, limits, exclude=(), title="Voltage profile"):
    """Node voltage vs distance from the substation, one panel per case."""
    fig, axes = plt.subplots(1, len(cases), figsize=(6 * len(cases), 4.5), sharey=True, squeeze=False)
    for ax, res, label in zip(axes[0], cases, labels):
        for ph, (dist, volt, names) in res["profile"].items():
            keep = [i for i, n in enumerate(names) if not net.is_excluded(n, exclude)]
            ax.plot(dist[keep], volt[keep], "o", ms=6, color=PHASE_COLOURS[ph], label=f"Phase {ph}")
        draw_limits(ax, limits)
        ax.set_title(label); ax.set_xlabel("Distance from the substation [km]")
    axes[0][0].set_ylabel("Node voltage [pu]"); axes[0][0].legend(loc="lower left")
    fig.suptitle(title); fig.tight_layout()
    return fig


def draw_grouped_bars(ax, categories, series, labels, ylabel=None, value_labels=False):
    """Side-by-side bars: one group per category, one bar per series."""
    x = np.arange(len(categories))
    width = 0.8 / len(series)
    for i, (values, label) in enumerate(zip(series, labels)):
        bars = ax.bar(x + (i - (len(series) - 1) / 2) * width, values, width, color=CASE_COLOURS[i], label=label)
        if value_labels:
            ax.bar_label(bars, fmt="%.0f", fontsize=8)
    ax.set_xticks(x, categories, rotation=90 if len(categories) > 12 else 0)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.legend()


def plot_node_voltages(cases, labels, limits, exclude=(), title="Node voltages"):
    nodes = [n for n in cases[0]["vnode"] if not net.is_excluded(n, exclude)]
    fig, ax = plt.subplots(figsize=(13, 4.5))
    draw_grouped_bars(ax, nodes, [[c["vnode"][n] for n in nodes] for c in cases], labels, "Voltage [pu]")
    draw_limits(ax, limits)
    ax.set_ylim(min(limits[0], min(min(c["vnode"][n] for n in nodes) for c in cases)) - 0.02, limits[1] + 0.05)
    ax.set_title(title); fig.tight_layout()
    return fig


def plot_power_and_loading(cases, labels, title="Power balance and line loading"):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5), gridspec_kw={"width_ratios": [1, 1.6]})
    keys = [("Substation P\n[kW]", "P_source"), ("PV P\n[kW]", "P_pv"), ("Load P\n[kW]", "P_load"), ("Substation Q\n[kvar]", "Q_source")]
    draw_grouped_bars(axes[0], [k for k, _ in keys], [[c[k] for _, k in keys] for c in cases], labels, value_labels=True)
    axes[0].set_title("Losses: " + " -> ".join(f"{c['P_loss']:.1f}" for c in cases) + " kW")
    lines = list(cases[0]["lines"])
    draw_grouped_bars(axes[1], lines, [[c["lines"][n][2] for n in lines] for c in cases], labels, "Loading [% of ampacity]")
    axes[1].axhline(100, color=LIMIT, ls="--", lw=1)
    axes[1].tick_params(axis="x", rotation=45)
    fig.suptitle(title); fig.tight_layout()
    return fig


# --- Time series -----------------------------------------------------------------------------
def time_labels(n_steps, step_minutes):
    """Tick positions and 'hh:mm' labels, one label per hour."""
    per_hour = max(1, 60 // step_minutes)
    ticks = list(range(0, n_steps, per_hour))
    return ticks, [f"{t * step_minutes // 60:02d}:00" for t in ticks]


def draw_time_series(ax, profiles, step_minutes, labels=None, styles=None, colour=None, alpha=1.0):
    """Draw each row of 'profiles' (n_profiles x n_steps) against time of day."""
    profiles = np.atleast_2d(profiles)
    for i, row in enumerate(profiles):
        ax.plot(row, ls=styles[i] if styles else "-", color=colour, alpha=alpha, label=labels[i] if labels else None)
    ticks, text = time_labels(profiles.shape[1], step_minutes)
    ax.set_xticks(ticks, text, rotation=60)
    ax.set_xlabel("Time (hh:mm)")
    if labels:
        ax.legend()


def plot_time_series(profiles, title, ylabel, step_minutes=30, labels=None, styles=None, limits=None, hline=None,
                     colour=None, alpha=1.0, figsize=(10, 3.5)):
    """One figure with one line per profile; optional voltage 'limits' or a single 'hline' (e.g. a rating)."""
    fig, ax = plt.subplots(figsize=figsize)
    draw_time_series(ax, profiles, step_minutes, labels, styles, colour, alpha)
    if limits:
        draw_limits(ax, limits)
    if hline is not None:
        ax.axhline(hline, color=LIMIT, ls="--", lw=1)
    ax.set_ylabel(ylabel); ax.set_title(title); fig.tight_layout()
    return fig


def plot_panels(panel_data, ylabel, step_minutes=30, limits=None, hline=None, title="", colour="#2a78d6", alpha=0.6, ncols=2,
                labels=None):
    """Grid of time-series panels: panel_data = {panel title: profiles (n_profiles x n_steps)}.
    With 'labels' (one per profile) every line gets its own colour and a legend; otherwise all
    lines use 'colour'."""
    n = len(panel_data)
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 3.4 * nrows), sharey=True, squeeze=False)
    for ax, (name, profiles) in zip(axes.flat, panel_data.items()):
        draw_time_series(ax, profiles, step_minutes, labels=labels, colour=None if labels else colour,
                         alpha=1.0 if labels else alpha)
        if limits:
            draw_limits(ax, limits)
        if hline is not None:
            ax.axhline(hline, color=LIMIT, ls="--", lw=1)
        ax.set_title(name); ax.set_ylabel(ylabel)
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.suptitle(title); fig.tight_layout()
    return fig


def plot_lines_vs_x(x, series, xlabel, ylabel, title, hline=None, markers=True):
    """series = {label: y values}; e.g. non-compliant customers vs PV penetration per season."""
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, (label, y) in enumerate(series.items()):
        ax.plot(x, y, "o-" if markers else "-", color=CASE_COLOURS[(i + 1) % len(CASE_COLOURS)], lw=2, label=label)
    if hline is not None:
        ax.axhline(hline, color=LIMIT, ls="--", lw=1)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title); ax.legend(); fig.tight_layout()
    return fig
