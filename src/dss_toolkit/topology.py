"""Reading a whole network from the compiled circuit: its graph, assets, loads and layout.

Nothing here depends on file names or element names: everything is read from the circuit that
OpenDSS compiled, so the same functions work on a 3-bus test case, the 31-customer LV circuit, a
3,000-customer MV-LV feeder or utility data.

    read_network(engine)        everything below in one NetworkInfo (call once after building)
    network graph               which buses each power-delivery element joins, line lengths,
                                every source (any number), a spanning tree grown from all of them
                                (each bus belongs to its nearest source), islands (parts no source
                                reaches) and ties between sources (meshed parts)
    transformer classes         regulator, step-up, substation (MV secondary), distribution (LV)
    assets                      every transformer and line with a usable rating, sorted into
                                head (substation) transformers, other transformers, MV and LV lines
    devices                     capacitors, fuses, reclosers, switches and regulators to show on maps
    fixed_load_shapes           loads that keep their own load shape (e.g. commercial loads)
    phase_tap_points            where each single-phase customer's phase is chosen (for phase
                                randomization)
    generate_layout             map coordinates when the data has none (or only some)
"""
import heapq
import re
import zlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import network as net

# OpenDSS length units (Lines.Units) -> km
UNIT_TO_KM = {0: 1.0, 1: 1.609344, 2: 0.3048, 3: 1.0, 4: 0.001, 5: 0.0003048, 6: 2.54e-5, 7: 1e-5, 8: 1e-6}
DEFAULT_LINE_NORMAMPS = 400.0      # OpenDSS's rating for a line whose data gives none
MV_THRESHOLD_KV = 1.0              # line-to-line kV above which a line counts as MV
HEAD_MAX_DISTANCE_KM = 0.2         # a head transformer stands at its source's station (km along the network)
TRANSFORMER_CLASSES = ("regulator", "step_up", "substation", "distribution")
DEVICE_KINDS = ("capacitor", "fuse", "recloser", "switch", "regulator")


@dataclass
class NetworkInfo:
    """What read_network() found. All names are OpenDSS names (lower case)."""
    circuit_name: str
    source_bus: str
    buses: list
    bus_kv_ll: dict                         # {bus: line-to-line base kV (0 = no base set)}
    branches: list                          # [(element, bus_from, bus_to, length_km, n_phases)]
    tree_parent: dict                       # {bus: (parent bus, element)} spanning tree from the source
    tree_depth_km: dict                     # {bus: distance from the source along the tree [km]}
    islands: list                           # [set of buses] not connected to the source
    assets: list                            # [Asset]
    loads: dict                             # net.load_inventory()
    load_phases: dict                       # {load: "A"/"B"/"C"/"ABC"}
    fixed_loads: dict                       # {load: (shape, how it was found)}
    tap_points: dict                        # {load: TapPoint} for single-phase loads
    coordinates: dict = field(default_factory=dict)   # {bus: (x, y)} read from the circuit
    base_case_solved: bool = True                     # the snapshot test solve converged
    sources: list = field(default_factory=list)       # [{"name", "bus", "kv_ll"}] every voltage source
    source_of: dict = field(default_factory=dict)     # {bus: name of the nearest source (tree root)}
    source_ties: list = field(default_factory=list)   # [(element, bus, bus)] joining two sources' areas
    transformer_class: dict = field(default_factory=dict)   # {transformer: class, see TRANSFORMER_CLASSES}
    devices: dict = field(default_factory=dict)       # {element: kind, see DEVICE_KINDS}
    device_buses: dict = field(default_factory=dict)  # {device element: (bus 1, bus 2 or None)}
    device_notes: list = field(default_factory=list)  # what could not be matched (missing files, names)

    @property
    def random_customers(self):
        """Loads that get random profiles (and may get PV): every load without a fixed shape."""
        return [c for c in self.loads if c not in self.fixed_loads]

    def assets_of(self, kind):
        return [a for a in self.assets if a.kind == kind]


@dataclass(frozen=True)
class Asset:
    """One monitored element. kind: "head_transformer" (fed from the source side), "transformer",
    "mv_line" or "lv_line". rating: kVA (transformers) or A (lines). pct_scale converts OpenDSS's
    % of normal rating to % of 'rating' (transformers are normally rated at 110 % of nameplate).
    group: transformer class (TRANSFORMER_CLASSES) or "mv" / "lv"; code: line code or transformer
    code (or the rating when there is none), to group similar elements; source: nearest source."""
    element: str
    kind: str
    rating: float
    pct_scale: float = 1.0
    group: str = ""
    code: str = ""
    source: str = ""


@dataclass(frozen=True)
class TapPoint:
    """Where a single-phase customer's phase is decided: 'element' (a Load or the Line feeding
    its single-phase branch) connects at 'bus_text' of terminal 'terminal' to a 3-phase bus.
    Changing that node moves every customer downstream of it to another phase."""
    element: str
    terminal: int
    bus_text: str
    allowed_nodes: tuple = (1, 2, 3)        # energized phases at the connection point


# --- Graph ---------------------------------------------------------------------------------
def source_bus(engine):
    """Bus of the circuit's first voltage source (the one on the 'New Circuit' line)."""
    vs = engine.ActiveCircuit.Vsources
    vs.First
    engine.ActiveCircuit.SetActiveElement(f"Vsource.{vs.Name}")
    return net.bus_name(engine.ActiveCircuit.ActiveElement.BusNames[0]).lower()


def sources(engine):
    """Every enabled voltage source: [{"name", "bus", "kv_ll"}]. OpenDSS solves all of them
    together; the first is the one defined on the 'New Circuit' line."""
    circuit = engine.ActiveCircuit
    vs = circuit.Vsources
    found = []
    i = vs.First
    while i:
        circuit.SetActiveElement(f"Vsource.{vs.Name}")
        if circuit.ActiveCktElement.Enabled:
            found.append({"name": vs.Name.lower(), "bus": net.bus_name(circuit.ActiveCktElement.BusNames[0]).lower(),
                          "kv_ll": vs.BasekV})
        i = vs.Next
    return found


def line_lengths_km(engine):
    """{'line.name': length [km]}"""
    lines = engine.ActiveCircuit.Lines
    lengths = {}
    i = lines.First
    while i:
        lengths[f"line.{lines.Name.lower()}"] = lines.Length * UNIT_TO_KM.get(lines.Units, 1.0)
        i = lines.Next
    return lengths


def branches(engine):
    """[(element, bus_from, bus_to, length_km, n_phases)] for every terminal pair of every
    enabled power-delivery element (lines, transformers, reactors, switches ...)."""
    circuit = engine.ActiveCircuit
    lengths = line_lengths_km(engine)
    pd = circuit.PDElements
    found = []
    i = pd.First
    while i:
        element = circuit.ActiveCktElement
        name = element.Name.lower()
        buses = [net.bus_name(b).lower() for b in element.BusNames]
        for other in buses[1:]:
            if other != buses[0]:
                found.append((name, buses[0], other, lengths.get(name, 0.0), element.NumPhases))
        i = pd.Next
    return found


def spanning_tree(source, branch_list):
    """Shortest-path tree grown from the source bus, or from several source buses at once (a list):
    each bus is reached from its nearest source along the network (km; fewer branches on ties).
    ({bus: (parent, element)}, {bus: distance km}, islands = [set of buses] no source reaches).
    On a radial network this is the network itself."""
    roots = [source] if isinstance(source, str) else list(dict.fromkeys(source))
    adjacency = defaultdict(list)
    for element, a, b, km, _ in branch_list:
        adjacency[a].append((b, element, km))
        adjacency[b].append((a, element, km))
    parent = {r: (None, None) for r in roots}
    depth = {r: 0.0 for r in roots}
    hops = {r: 0 for r in roots}
    heap = [(0.0, 0, i, r) for i, r in enumerate(roots)]
    done, counter = set(), len(roots)
    while heap:
        km_here, n, _, bus = heapq.heappop(heap)
        if bus in done:
            continue
        done.add(bus)
        for other, element, km in adjacency[bus]:
            new = (km_here + km, n + 1)
            if other not in done and (other not in depth or new < (depth[other], hops[other])):
                parent[other] = (bus, element)
                depth[other], hops[other] = new
                counter += 1
                heapq.heappush(heap, (new[0], new[1], counter, other))
    unreached = set(adjacency) - set(parent)
    islands = []
    while unreached:
        start = unreached.pop()
        island, queue = {start}, deque([start])
        while queue:
            for other, _, _ in adjacency[queue.popleft()]:
                if other in unreached:
                    unreached.discard(other)
                    island.add(other)
                    queue.append(other)
        islands.append(island)
    return parent, depth, islands


def tree_roots(parent):
    """{bus: the root (source bus) of its tree}."""
    root = {}
    for bus in parent:
        path, b = [], bus
        while b not in root and parent[b][0] is not None:
            path.append(b)
            b = parent[b][0]
        r = root.get(b, b)
        for p in path + [b]:
            root[p] = r
    return root


def source_ties(parent, branch_list, roots):
    """[(element, bus, bus)] that join the areas of two different sources (the network is meshed
    there: those sources can feed each other)."""
    return [(e, a, b) for e, a, b, _, _ in branch_list
            if a in roots and b in roots and roots[a] != roots[b]]


def bus_base_kv(engine):
    """{bus: line-to-line base kV} (0 where no voltage base was set)."""
    circuit = engine.ActiveCircuit
    return {circuit.Buses(i).Name.lower(): circuit.Buses(i).kVBase * np.sqrt(3) for i in range(circuit.NumBuses)}


def bus_coordinates(engine):
    """{bus: (x, y)} for buses that have coordinates."""
    circuit = engine.ActiveCircuit
    coords = {}
    for i in range(circuit.NumBuses):
        b = circuit.Buses(i)
        if b.Coorddefined:
            coords[b.Name.lower()] = (b.x, b.y)
    return coords


def bus_node_sets(engine):
    """{bus: set of node numbers present}."""
    nodes = defaultdict(set)
    for node in engine.ActiveCircuit.AllNodeNames:
        bus, _, n = node.rpartition(".")
        nodes[bus.lower()].add(int(n))
    return nodes


# --- Assets ----------------------------------------------------------------------------------
def transformer_classes(engine):
    """{transformer element: class}, read from OpenDSS (no names needed):
      "regulator"     named by a RegControl, or every winding at the same kV (1:1 ratio);
      "step_up"       a later winding at a higher kV than winding 1 (e.g. a generator transformer);
      "substation"    steps down to a secondary of 1 kV or more (feeds an MV network);
      "distribution"  steps down to LV (below 1 kV)."""
    circuit = engine.ActiveCircuit
    regulated = set()
    rc = circuit.RegControls
    i = rc.First
    while i:
        regulated.add(rc.Transformer.lower())
        i = rc.Next
    classes = {}
    tr = circuit.Transformers
    i = tr.First
    while i:
        name = tr.Name.lower()
        kvs = []
        for w in range(1, tr.NumWindings + 1):
            tr.Wdg = w
            kvs.append(tr.kV)
        circuit.SetActiveElement(f"Transformer.{name}")
        phases = circuit.ActiveCktElement.NumPhases
        ll = [kv * (np.sqrt(3) if phases == 1 else 1.0) for kv in kvs]   # compare as line-to-line
        if name in regulated or max(kvs) <= 1.02 * min(kvs):
            classes[f"transformer.{name}"] = "regulator"
        elif max(kvs[1:]) > kvs[0] * 1.02:
            classes[f"transformer.{name}"] = "step_up"
        elif min(ll[1:]) >= MV_THRESHOLD_KV:
            classes[f"transformer.{name}"] = "substation"
        else:
            classes[f"transformer.{name}"] = "distribution"
        i = tr.Next
    return classes


def head_transformers(parent, branch_list, classes, roots, depth=None, max_distance_km=HEAD_MAX_DISTANCE_KM):
    """Head (substation) transformers, any number per source: the first step-down transformers on
    the paths out of each source (regulators are passed through) that stand at the source's
    station, i.e. within 'max_distance_km' of it along the network. A source modelled at
    distribution voltage reaches its first transformers (distribution transformers) only along
    feeder lines, so it has no head transformer: the source itself is the supply point."""
    depth = depth or {}
    heads = set()
    for element, a, b, _, _ in branch_list:
        if classes.get(element) not in ("substation", "distribution"):
            continue
        primary = a if parent.get(b, (None, None))[0] == a else b
        if primary not in roots or depth.get(primary, 0.0) > max_distance_km:
            continue
        bus, first = primary, True
        while bus in parent and parent[bus][0] is not None:
            bus, up = parent[bus]
            if up.startswith("transformer.") and classes.get(up) != "regulator":
                first = False
                break
        if first:
            heads.add(element)
    return heads


def assets(engine, parent, kv_ll, rating_overrides_kva=None, classes=None, heads=None, roots=None, source_of=None):
    """Every transformer and every rated line as an Asset (with its class or MV / LV group, its
    line or transformer code and its nearest source). 'heads' = the head transformers (default:
    head_transformers()). Lines at the OpenDSS default rating (400 A, i.e. no rating in the data)
    are left out; count them with unrated_lines()."""
    circuit = engine.ActiveCircuit
    overrides = {k.lower(): v for k, v in (rating_overrides_kva or {}).items()}
    classes = classes if classes is not None else transformer_classes(engine)
    roots = roots if roots is not None else tree_roots(parent)
    if heads is None:
        heads = head_transformers(parent, branches(engine), classes, roots)   # (no depths: station check skipped)
    source_of = source_of if source_of is not None else roots
    result = []
    tr = circuit.Transformers
    i = tr.First
    while i:
        name = tr.Name.lower()
        element = f"transformer.{name}"
        tr.Wdg = 1
        kva = tr.kVA
        code = tr.XfmrCode or f"{kva:g} kVA"
        circuit.SetActiveElement(f"Transformer.{name}")
        normhkva = float(circuit.ActiveCktElement.Properties("normhkVA").Val or 0) or 1.1 * kva
        rating = overrides.get(name, kva)
        bus = net.bus_name(circuit.ActiveCktElement.BusNames[0]).lower()
        result.append(Asset(element, "head_transformer" if element in heads else "transformer", rating,
                            normhkva / rating, classes.get(element, ""), code.lower(), source_of.get(bus, "")))
        i = tr.Next
    lines = circuit.Lines
    i = lines.First
    while i:
        if lines.NormAmps != DEFAULT_LINE_NORMAMPS:                 # switches included when they have a rating
            bus = net.bus_name(lines.Bus1).lower()
            mv = kv_ll.get(bus, 0) > MV_THRESHOLD_KV
            result.append(Asset(f"line.{lines.Name.lower()}", "mv_line" if mv else "lv_line", lines.NormAmps,
                                1.0, "mv" if mv else "lv", (lines.LineCode or f"{lines.NormAmps:g} A").lower(),
                                source_of.get(bus, "")))
        i = lines.Next
    return result


# --- Devices -----------------------------------------------------------------------------------
NEW_ELEMENT = re.compile(r'^\s*new\s+(?:object\s*=\s*)?"?([a-z]+)\.([^\s"]+)', re.IGNORECASE)
DEVICE_WORDS = {"fuse": "fuse", "fuses": "fuse", "recloser": "recloser", "recl": "recloser",
                "switch": "switch", "sw": "switch", "sectionalizer": "switch", "breaker": "switch"}


def elements_in_file(path):
    """['class.name'] of every 'New Class.Name' line in a .dss file (comments skipped)."""
    found = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = NEW_ELEMENT.match(line.split("!", 1)[0].split("//", 1)[0])
            if m:
                found.append(f"{m.group(1).lower()}.{m.group(2).lower()}")
    return found


def devices(engine, device_files=None, classes=None):
    """({element: kind}, notes) for maps: kind is capacitor, fuse, recloser, switch or regulator.
    Found, in order of trust:
      1. device_files = {kind: path of a .dss file}: every element the file creates is that kind
         (e.g. fuses written as 'New Line' commands in Fuses.dss);
      2. the data: Capacitor elements, transformers driven by a RegControl, the elements watched
         by Fuse / Recloser / SwtControl objects, and lines marked Switch=yes;
      3. whole words in line names (fuse, recloser / recl, switch / sw, breaker).
    notes lists files not found and names in the files that are not in the circuit."""
    circuit = engine.ActiveCircuit
    present = {n.lower() for n in circuit.PDElements.AllNames}
    found, notes = {}, []
    for kind, path in (device_files or {}).items():
        path = Path(path)
        if not path.is_file():
            notes.append(f"{kind}: file {path.name} not found")
            continue
        names = elements_in_file(path)
        missing = [n for n in names if n not in present]
        for n in names:
            if n in present:
                found.setdefault(n, kind)
        if missing:
            notes.append(f"{kind}: {len(missing)} of {len(names)} elements in {path.name} are not in the circuit "
                         f"(disabled, or controls such as CapControl)")
    for e in present:
        if e.startswith("capacitor."):
            found.setdefault(e, "capacitor")
    for e, c in (classes if classes is not None else transformer_classes(engine)).items():
        if c == "regulator":
            found.setdefault(e, "regulator")
    for collection, kind, attr in ((circuit.Fuses, "fuse", "MonitoredObj"), (circuit.Reclosers, "recloser", "MonitoredObj"),
                                   (circuit.SwtControls, "switch", "SwitchedObj")):
        i = collection.First
        while i:
            target = (getattr(collection, attr) or "").lower()
            if target in present:
                found.setdefault(target, kind)
            i = collection.Next
    lines = circuit.Lines
    i = lines.First
    while i:
        e = f"line.{lines.Name.lower()}"
        if e not in found:
            if lines.IsSwitch:
                found[e] = "switch"
            else:
                words = [DEVICE_WORDS[w] for w in re.split(r"[_\-\s.]+", lines.Name.lower()) if w in DEVICE_WORDS]
                if words:
                    found[e] = words[0]
        i = lines.Next
    return found, notes


def unrated_lines(engine):
    """Names of lines at the OpenDSS default rating (no rating in the data); they are not checked."""
    lines = engine.ActiveCircuit.Lines
    found = []
    i = lines.First
    while i:
        if lines.NormAmps == DEFAULT_LINE_NORMAMPS:
            found.append(lines.Name.lower())
        i = lines.Next
    return found


# --- Loads -------------------------------------------------------------------------------------
TOKEN = re.compile(r"[a-z]+\d+|\d+[a-z]+[a-z\d]*")


def name_tokens(name):
    """Parts of a name that mix letters and digits, e.g. 'Load_shape_Com_LV5' -> {'lv5'}."""
    return {t for t in re.split(r"[_\-\s.]+", name.lower()) if TOKEN.fullmatch(t)}


def upstream_transformer(load_bus, parent):
    """Name of the first transformer between a load's bus and the source, or None."""
    bus = load_bus
    while bus in parent and parent[bus][0] is not None:
        bus, element = parent[bus]
        if element.startswith("transformer."):
            return element.split(".", 1)[1]
    return None


def fixed_load_shapes(engine, loads, parent, overrides=None):
    """{load: (shape, how it was found)} for loads that keep their own load shape, found by:
      1. "linked in circuit": the load already has a daily (or yearly) shape in the compiled circuit;
      2. "name match": the load has no shape, but exactly one load shape's name shares a letter+digit
         part (e.g. 'lv5') with the load's name or with the transformer feeding it, and that part
         belongs to only one transformer (CRE21: Load_shape_Com_LV5 <-> transformer hv_f0_lv5_tx);
      3. 'overrides' = {load: shape} sets a shape by hand ({load: None} makes a load random again).
    Every other load gets random profiles."""
    circuit = engine.ActiveCircuit
    shapes = [s for s in net.element_names(circuit.LoadShapes) if s.lower() != "default"]
    shape_tokens = defaultdict(list)
    for s in shapes:
        for t in name_tokens(s):
            shape_tokens[t].append(s)
    transformer_tokens = defaultdict(set)
    for t in net.element_names(circuit.Transformers):
        for token in name_tokens(t):
            transformer_tokens[token].add(t.lower())
    fixed = {}
    ld = circuit.Loads
    for load, info in loads.items():
        ld.Name = load
        linked = ld.daily or ld.Yearly
        if linked and linked.lower() != "default":
            fixed[load] = (linked, "linked in circuit")
            continue
        transformer = upstream_transformer(net.bus_name(info["bus"]).lower(), parent)
        tokens = name_tokens(load) | (name_tokens(transformer) if transformer else set())
        matches = {s for t in tokens if len(shape_tokens.get(t, [])) == 1 and len(transformer_tokens.get(t, ())) <= 1
                   for s in shape_tokens[t]}
        if len(matches) == 1:
            fixed[load] = (matches.pop(), "name match")
    for load, shape in (overrides or {}).items():
        key = next((l for l in loads if l.lower() == load.lower()), None)
        if key is None:
            raise KeyError(f"FIXED_LOAD_SHAPES: '{load}' is not a load of the circuit")
        if shape is None:
            fixed.pop(key, None)
        else:
            fixed[key] = (shape, "setting")
    return fixed


def phase_tap_points(loads, branch_list, node_sets, max_depth=50, energized=None):
    """{load: TapPoint} for every single-phase load: the element whose connection to a 3-phase bus
    decides the load's phase - the load itself if it sits on a 3-phase bus (e.g. CRE21 houses),
    otherwise the line at the top of its single-phase branch (e.g. a service line from a pole).
    'energized' = {bus: set of nodes with voltage}: only those phases may be chosen (e.g. an LV
    network behind a single-phase split-phase transformer has a dead third phase)."""
    energized = energized if energized is not None else node_sets
    feeding = {}
    for element, a, b, _, n_phases in branch_list:
        if element.startswith("line."):
            feeding.setdefault(b, (element, a))
    points = {}
    for load, info in loads.items():
        if len(net.bus_phases(info["bus"])) != 1:
            continue
        bus = net.bus_name(info["bus"]).lower()
        if len(node_sets.get(bus, ())) >= 3:
            allowed = tuple(sorted(n for n in energized.get(bus, ()) if 1 <= n <= 3))
            if len(allowed) >= 2:
                points[load] = TapPoint(f"load.{load}", 0, info["bus"], allowed)
            continue
        for _ in range(max_depth):
            if bus not in feeding:
                break
            element, upstream = feeding[bus]
            if len(node_sets.get(upstream, ())) >= 3:
                allowed = tuple(sorted(n for n in energized.get(upstream, ()) if 1 <= n <= 3))
                if len(allowed) >= 2:
                    points[load] = TapPoint(element, 0, None, allowed)
                break
            bus = upstream
    return points


# --- Everything at once ------------------------------------------------------------------------
def read_network(engine, rating_overrides_kva=None, fixed_load_overrides=None, device_files=None,
                 head_transformers_override=None):
    """Read the compiled circuit into a NetworkInfo (sources, graph, assets, transformer classes,
    devices, loads, phases, fixed loads, tap points, coordinates). Call it after build_circuit().
    device_files = {kind: .dss path} (see devices()); head_transformers_override = [transformer
    names] replaces the automatic choice of head transformers."""
    circuit = engine.ActiveCircuit
    source_list = sources(engine)
    source = source_list[0]["bus"] if source_list else source_bus(engine)
    branch_list = branches(engine)
    parent, depth, islands = spanning_tree([s["bus"] for s in source_list] or [source], branch_list)
    roots = tree_roots(parent)
    bus_source = {s["bus"]: s["name"] for s in reversed(source_list)}
    source_of = {bus: bus_source.get(root, root) for bus, root in roots.items()}
    classes = transformer_classes(engine)
    if head_transformers_override is not None:
        heads = {f"transformer.{n.lower().removeprefix('transformer.')}" for n in head_transformers_override}
    else:
        heads = head_transformers(parent, branch_list, classes, roots, depth)
    kv_ll = bus_base_kv(engine)
    loads = net.load_inventory(engine)
    node_sets = bus_node_sets(engine)
    energized, solved = energized_nodes(engine)
    taps = phase_tap_points(loads, branch_list, node_sets, energized=energized if solved else None)
    # fill in the bus text of line tap points (needed to change their node later)
    lines = circuit.Lines
    taps = {c: (TapPoint(t.element, t.terminal, _line_bus1(lines, t.element), t.allowed_nodes) if t.bus_text is None else t)
            for c, t in taps.items()}
    device_map, device_notes = devices(engine, device_files, classes)
    device_buses = {}
    for element in device_map:
        circuit.SetActiveElement(element)
        names = [net.bus_name(b).lower() for b in circuit.ActiveCktElement.BusNames]
        device_buses[element] = (names[0], names[1] if len(names) > 1 and names[1] != names[0] else None)
    return NetworkInfo(
        circuit_name=circuit.Name, source_bus=source, buses=[b.lower() for b in circuit.AllBusNames],
        bus_kv_ll=kv_ll, branches=branch_list, tree_parent=parent, tree_depth_km=depth, islands=islands,
        assets=assets(engine, parent, kv_ll, rating_overrides_kva, classes, heads, roots, source_of),
        loads=loads, load_phases=net.customer_phases(engine),
        fixed_loads=fixed_load_shapes(engine, loads, parent, fixed_load_overrides),
        tap_points=taps, coordinates=bus_coordinates(engine), base_case_solved=solved,
        sources=source_list, source_of=source_of, source_ties=source_ties(parent, branch_list, roots),
        transformer_class=classes, devices=device_map, device_notes=device_notes,
        device_buses=device_buses)


def energized_nodes(engine, threshold_pu=0.1):
    """({bus: nodes with more than 'threshold_pu' voltage}, converged) from one snapshot solve of
    the circuit as compiled. Also a quick health check of new network data.
    If the power flow does not settle (e.g. regulators or capacitors that keep switching), it is
    reported as not converged and every node is taken as energized, so nothing else is blocked."""
    from . import engine as eng
    eng.set_snapshot_mode(engine)
    circuit = engine.ActiveCircuit
    converged = eng.solve(engine, verbose=False)
    found = defaultdict(set)
    for node, v in zip(circuit.AllNodeNames, circuit.AllBusVmagPu):
        bus, _, n = node.rpartition(".")
        if v > threshold_pu or not converged:
            found[bus.lower()].add(int(n))
    return found, converged


def _line_bus1(lines, element):
    lines.Name = element.split(".", 1)[1]
    return lines.Bus1


# --- Layout --------------------------------------------------------------------------------------
def generate_layout(info, existing=None, min_share=0.5, seed=1):
    """Map coordinates {bus: (x, y)} for every bus of a NetworkInfo.
    If 'existing' coordinates (default: those in the circuit) cover at least 'min_share' of the
    buses, they are kept and each missing bus is placed next to its nearest placed relative along
    the tree. Otherwise a two-level schematic layout is made:
      - the MV skeleton (buses above 1 kV) is spread out with a force-directed layout, so feeder
        branches separate instead of crossing;
      - each LV network (everything below a transformer whose secondary is LV) is drawn as its own
        small radial fan around its transformer, sized to fit between neighbouring transformers.
    A network with no MV part (e.g. one LV feeder) is drawn as one radial fan from the source."""
    existing = info.coordinates if existing is None else {k.lower(): v for k, v in existing.items()}
    if info.buses and len(existing) >= min_share * len(info.buses):
        return fill_missing_coordinates(info, existing)
    children = defaultdict(list)
    for bus, (parent, element) in info.tree_parent.items():
        if parent is not None:
            children[parent].append((bus, element))
    is_mv = lambda bus: info.bus_kv_ll.get(bus, 0) > MV_THRESHOLD_KV
    # LV groups: roots are LV buses fed through a transformer from an MV bus (or the source itself)
    lv_roots = [bus for bus, (parent, element) in info.tree_parent.items()
                if parent is not None and element and element.startswith("transformer.")
                and is_mv(parent) and not is_mv(bus)]
    skeleton = [b for b in info.tree_parent if is_mv(b)]
    coords = {}
    roots = [b for b, (p, _) in info.tree_parent.items() if p is None]
    if len(roots) > 1:                       # several sources: fan out from a common centre
        children["__sources__"] = [(r, None) for r in roots]
    top = "__sources__" if len(roots) > 1 else info.source_bus
    if len(skeleton) < 3:
        coords.update(_radial_fan(top, children, (0.0, 0.0), 10.0))
        coords.pop("__sources__", None)
    else:
        sk = _force_layout(skeleton, info, seed)
        coords.update(sk)
        points = np.array(list(sk.values()))
        centre = points.mean(axis=0)
        anchors = {r: np.array(sk[info.tree_parent[r][0]]) for r in lv_roots}
        anchor_xy = np.array(list(anchors.values())) if anchors else np.zeros((1, 2))
        for root, anchor in anchors.items():
            d = np.linalg.norm(anchor_xy - anchor, axis=1)
            d = d[d > 0]
            radius = 0.4 * (d.min() if len(d) else 1.0)
            outward = anchor - centre
            outward = outward / (np.linalg.norm(outward) or 1.0)
            coords.update(_radial_fan(root, children, tuple(anchor + outward * radius), radius))
    # anything not placed yet (islands, buses below unusual elements): small grids to the right
    placed = np.array(list(coords.values())) if coords else np.zeros((1, 2))
    right = placed[:, 0].max() + 0.05 * (np.ptp(placed[:, 0]) or 1.0)
    missing = [b for b in info.buses if b not in coords]
    for j, bus in enumerate(missing):
        coords[bus] = (right + 0.02 * (j % 20), 0.02 * (j // 20))
    return coords


def _radial_fan(root, children, centre, radius):
    """Radial tree below 'root': rings by number of branches from the root, each subtree given an
    angle in proportion to its leaves; scaled so the outer ring has 'radius'."""
    leaves, order, stack = {}, [], [root]
    while stack:
        b = stack.pop()
        order.append(b)
        stack.extend(c for c, _ in children[b])
    for b in reversed(order):
        leaves[b] = max(1, sum(leaves[c] for c, _ in children[b]))
    polar = {root: (0.0, 0.0)}
    stack = [(root, 0.0, 2 * np.pi, 0)]
    while stack:
        bus, start, span, ring = stack.pop()
        angle = start
        for child, _ in _centre_largest(children[bus], leaves):
            share = span * leaves[child] / leaves[bus]
            polar[child] = (ring + 1, angle + share / 2)
            stack.append((child, angle, share, ring + 1))
            angle += share
    rings = max((r for r, _ in polar.values()), default=1) or 1
    cx, cy = centre
    return {b: (cx + radius * r / rings * np.cos(a), cy + radius * r / rings * np.sin(a)) for b, (r, a) in polar.items()}


def _centre_largest(kids, leaves):
    """Children ordered so the largest subtree sits in the middle of its parent's wedge (a long
    feeder then runs straight instead of curling), smaller ones alternating either side."""
    ordered = sorted(kids, key=lambda c: -leaves[c[0]])
    arranged = []
    for i, kid in enumerate(ordered):
        if i % 2:
            arranged.insert(0, kid)
        else:
            arranged.append(kid)
    return arranged


def _force_layout(buses, info, seed, iterations=300):
    """Fruchterman-Reingold layout of the MV skeleton (tree edges between the given buses),
    started from a radial layout so that it is repeatable."""
    index = {b: i for i, b in enumerate(buses)}
    edges = np.array([(index[b], index[p]) for b, (p, _) in info.tree_parent.items()
                      if p is not None and b in index and p in index])
    children = defaultdict(list)
    for b, (p, e) in info.tree_parent.items():
        if p is not None and b in index and p in index:
            children[p].append((b, e))
    tops = [b for b in buses if info.tree_parent.get(b, (None, None))[0] is None]
    if len(tops) > 1:                        # several sources: one fan from a common centre
        children["__sources__"] = [(t, None) for t in tops]
        root = "__sources__"
    else:
        root = min(buses, key=lambda b: info.tree_depth_km.get(b, 0))
    start = _radial_fan(root, children, (0.0, 0.0), 1.0)
    rng = np.random.default_rng(seed)
    pos = np.array([start.get(b, tuple(rng.uniform(-1, 1, 2))) for b in buses], dtype=float)
    n = len(buses)
    k = np.sqrt(4.0 / n)
    temperature = 0.1
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2) + 1e-9
        force = (delta / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        if len(edges):
            d = pos[edges[:, 0]] - pos[edges[:, 1]]
            length = np.linalg.norm(d, axis=1) + 1e-9
            pull = d * (length / k)[:, None]
            np.add.at(force, edges[:, 0], -pull)
            np.add.at(force, edges[:, 1], pull)
        step = np.linalg.norm(force, axis=1) + 1e-9
        pos += force / step[:, None] * np.minimum(step, temperature)[:, None]
        temperature *= 0.985
    return {b: (float(x), float(y)) for b, (x, y) in zip(buses, pos)}


def fill_missing_coordinates(info, existing):
    """Keep 'existing' coordinates and place every missing bus a small step away from its nearest
    placed relative in the tree (parent, grandparent ... or a placed child)."""
    coords = dict(existing)
    known = np.array(list(existing.values())) if existing else np.zeros((1, 2))
    step = max(float(np.ptp(known[:, 0]) + np.ptp(known[:, 1])) / 2000, 1e-6)
    children = defaultdict(list)
    for bus, (parent, _) in info.tree_parent.items():
        if parent is not None:
            children[parent].append(bus)
    for bus in info.buses:
        if bus in coords:
            continue
        b, hops = bus, 0
        while b not in coords and b in info.tree_parent and info.tree_parent[b][0] is not None:
            b, hops = info.tree_parent[b][0], hops + 1
        if b not in coords:
            placed_child = next((c for c in children[bus] if c in coords), None)
            b, hops = (placed_child, 1) if placed_child else (None, 0)
        x, y = coords[b] if b else (0.0, 0.0)
        angle = (zlib.crc32(bus.encode()) % 360) * np.pi / 180   # stable spread
        coords[bus] = (x + hops * step * np.cos(angle), y + hops * step * np.sin(angle))
    return coords


def save_coordinates(coords, path):
    """Write coordinates as 'bus, x, y' lines (readable by OpenDSS Buscoords)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for bus, (x, y) in coords.items():
            f.write(f"{bus}, {x:.6f}, {y:.6f}\n")


def fixed_loads_table(info):
    """Rows {load, shape, found_by, phase, bus} of the loads that keep a fixed shape (for a CSV or a
    printed table)."""
    return [{"load": load, "shape": shape, "found_by": how, "phase": info.load_phases.get(load, "?"),
             "bus": info.loads[load]["bus"]} for load, (shape, how) in sorted(info.fixed_loads.items())]
