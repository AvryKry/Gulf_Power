"""Reading the topology of the active circuit (names, buses, phases, coordinates).

The smallest bricks: they read one kind of information and return plain Python values.
'exclude' is always a tuple of name prefixes to leave out (e.g. the converter's stub buses);
an empty tuple keeps everything.
"""


# --- Text helpers (no OpenDSS needed) -------------------------------------------------------
def bus_name(bus_text):
    """'632.1.2.3.0' -> '632'"""
    return bus_text.split(".")[0]


def bus_phases(bus_text):
    """'632.1.2.3.0' -> {1, 2, 3}. The neutral (.0) is not a phase; no nodes written = 3 phases."""
    nodes = bus_text.split(".")[1:]
    return {int(n) for n in nodes if n != "0"} if nodes else {1, 2, 3}


def is_excluded(name, exclude=()):
    """True if 'name' (a bus, node or element name) starts with one of the 'exclude' prefixes."""
    return bool(exclude) and name.lower().startswith(tuple(p.lower() for p in exclude))


# --- Element names ---------------------------------------------------------------------------
def element_names(collection):
    """All names in an OpenDSS collection (e.g. circuit.Loads). OpenDSS returns ['NONE'] for an
    empty collection; this returns [] instead."""
    return list(collection.AllNames) if collection.Count > 0 else []


def element_bus(engine, element, terminal=0):
    """Bus text of one terminal of an element, e.g. element_bus(engine, 'Load.671a') -> '671.1.2'"""
    engine.ActiveCircuit.SetActiveElement(element)
    return engine.ActiveCircuit.ActiveElement.BusNames[terminal]


def element_counts(engine):
    """Number of buses, nodes and elements of each type in the circuit."""
    c = engine.ActiveCircuit
    return {"Buses": c.NumBuses, "Nodes": c.NumNodes, "Lines": c.Lines.Count,
            "Transformers": c.Transformers.Count, "Regulators": c.RegControls.Count,
            "Capacitors": c.Capacitors.Count, "Loads": c.Loads.Count, "PV Systems": c.PVSystems.Count,
            "Generators": c.Generators.Count, "Storage": c.Storages.Count}


def has_der(engine):
    """True if the circuit already contains PV systems, generators or storage."""
    counts = element_counts(engine)
    return counts["PV Systems"] + counts["Generators"] + counts["Storage"] > 0


# --- Buses -----------------------------------------------------------------------------------
def bus_names(engine, exclude=()):
    return [b for b in engine.ActiveCircuit.AllBusNames if not is_excluded(b, exclude)]


def bus_nodes(engine, bus):
    """Phases (node numbers) that exist at a bus, e.g. [1, 3]."""
    engine.ActiveCircuit.SetActiveBus(bus)
    return [int(n) for n in engine.ActiveCircuit.ActiveBus.Nodes]


def three_phase_buses(engine, exclude=()):
    """Buses that have all three phases."""
    return [b for b in bus_names(engine, exclude) if len(bus_nodes(engine, b)) == 3]


def bus_xy(engine, bus):
    """(x, y) coordinates of a bus, or None if the circuit has no coordinates for it."""
    engine.ActiveCircuit.SetActiveBus(bus)
    b = engine.ActiveCircuit.ActiveBus
    return (b.x, b.y) if b.Coorddefined else None


def has_coordinates(engine, exclude=()):
    return any(bus_xy(engine, b) is not None for b in bus_names(engine, exclude))


# --- Branches --------------------------------------------------------------------------------
def line_segments(engine, exclude=()):
    """[(bus1, bus2, n_phases, is_switch)] for every line whose far bus is not excluded."""
    lines = engine.ActiveCircuit.Lines
    segments = []
    for name in element_names(lines):
        lines.Name = name
        if not is_excluded(bus_name(lines.Bus2), exclude):
            segments.append((bus_name(lines.Bus1), bus_name(lines.Bus2), len(bus_phases(lines.Bus1)), lines.IsSwitch))
    return segments


def transformer_segments(engine):
    """[(bus1, bus2)] for every two-winding transformer."""
    segments = []
    for name in element_names(engine.ActiveCircuit.Transformers):
        engine.ActiveCircuit.SetActiveElement(f"Transformer.{name}")
        buses = engine.ActiveCircuit.ActiveElement.BusNames
        segments.append((bus_name(buses[0]), bus_name(buses[1])))
    return segments


# --- Loads -----------------------------------------------------------------------------------
ZIP_TYPES = {(0, 0, 1): "Const. P", (1, 0, 0): "Const. Z", (0, 1, 0): "Const. I"}


def load_inventory(engine):
    """Rated data of every load: {name: {bus, conn, kV, kW, kvar, model}}."""
    loads = engine.ActiveCircuit.Loads
    inventory = {}
    for name in element_names(loads):
        loads.Name = name
        if loads.Model == 8:
            model = ZIP_TYPES.get(tuple(round(z) for z in loads.ZIPV[0:3]), "ZIP mixed")
        else:
            model = {1: "Const. P", 2: "Const. Z", 5: "Const. I"}.get(loads.Model, f"model={loads.Model}")
        inventory[name] = {"bus": element_bus(engine, f"Load.{name}"), "conn": "delta" if loads.IsDelta else "wye",
                           "kV": loads.kV, "kW": loads.kW, "kvar": loads.kvar, "model": model}
    return inventory


def load_bus_types(engine):
    """{bus: '3-phase' | 'phase-to-phase' | '1-phase'} from the phases used by all loads at a bus."""
    phases, delta = {}, {}
    for name, info in load_inventory(engine).items():
        bus = bus_name(info["bus"])
        phases.setdefault(bus, set()).update(bus_phases(info["bus"]))
        delta[bus] = delta.get(bus, False) or info["conn"] == "delta"
    return {bus: "3-phase" if len(ph) == 3 else ("phase-to-phase" if delta[bus] else "1-phase")
            for bus, ph in phases.items()}


def capacitor_buses(engine):
    return [bus_name(element_bus(engine, f"Capacitor.{c}")) for c in element_names(engine.ActiveCircuit.Capacitors)]
